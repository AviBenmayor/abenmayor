"""NYC Building Footprints (OTI, Open Data 5zhs-2jue) -> staging.building_footprint.

    loci footprints ingest [--file PATH]

WHAT IT IS
---------------------------------------------------------------------------
One polygon per building (BIN), citywide, maintained by OTI from the same
orthoimagery this project reads, with `height_roof` (feet above ground, from
the 2017 LiDAR / photogrammetry), `ground_elevation`, `construction_year`,
`feature_code` (2100 building, 5100 garage, 5110 shed ...), `last_status_type`
(Constructed | Demolition | Alteration | ...) and `last_edited_date`.
Metadata: https://github.com/CityOfNewYork/nyc-geo-metadata/blob/main/Metadata/
Metadata_BuildingFootprints.md. Verified 2026-09-17: 1,083,030 features in the
GeoJSON export, keys exactly {name, base_bbl, shape_area, construction_year,
ground_elevation, mappluto_bbl, objectid, feature_code, shape_length,
height_roof, last_status_type, bin, last_edited_date, geom_source, doitt_id};
rowsUpdatedAt 2026-09-13.

THE PULL. Whole city, one GeoJSON export
(https://data.cityofnewyork.us/api/geospatial/5zhs-2jue?method=export&format=GeoJSON,
~856 MB), read through DuckDB spatial's ST_Read in ~35 s. Not paged through
the Socrata JSON API: a 1.08M-row geometry pull through $limit/$offset is an
hour of requests for the same bytes.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
* `construction_year` before 2017 is RPAD (the assessor's roll), not imagery
  (memo §2). A 1910 here means "the roll says 1910".
* `height_roof` is FEET and is the HIGHEST point of the roof, so a one-storey
  shed with a parapet reads ~5 m and a bulkhead adds a storey to a walk-up.
* A lot can carry many BINs and a BIN can straddle lots; `base_bbl` is the
  join key to PLUTO and `mappluto_bbl` the one OTI resolved. Consumers UNION
  by base_bbl and never assume one polygon per lot.
* `last_status_type = 'Demolition'` rows are KEPT: a demolished building is
  the 2022 side of a 2022->2024 change.
"""
from __future__ import annotations

import datetime as dt
import pathlib

SOURCE_ID = "nyc_building_footprints"
DATASET_ID = "5zhs-2jue"
EXPORT_URL = (f"https://data.cityofnewyork.us/api/geospatial/{DATASET_ID}"
              f"?method=export&format=GeoJSON")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
RAW_ROOT = REPO_ROOT / "data" / "raw" / SOURCE_ID
TABLE = "staging.building_footprint"

#: Fail-loud floor: 1,083,030 at verification. A read that returns a tenth of
#: that is a truncated download, not a city that lost its buildings.
MIN_ROWS = 900_000

COLUMNS = ("bin", "bbl", "mappluto_bbl", "geom", "height_roof_ft", "ground_elev_ft",
           "construction_year", "feature_code", "last_status", "last_edited",
           "geom_source", "shape_area_sqft", "doitt_id", "ingested_at")


class FootprintsError(RuntimeError):
    pass


def latest_raw(root: pathlib.Path = RAW_ROOT) -> pathlib.Path:
    files = sorted(root.glob(f"{DATASET_ID}_*.geojson"))
    if not files:
        raise FootprintsError(
            f"no {DATASET_ID}_*.geojson under {root}. Download the export first:\n"
            f"  curl -L -o {root}/{DATASET_ID}_{dt.date.today()}.geojson '{EXPORT_URL}'")
    return files[-1]


def ingest(con, path: pathlib.Path | None = None, *, min_rows: int = MIN_ROWS) -> dict:
    """Whole-table DELETE/INSERT from the GeoJSON export. Returns counts."""
    path = path or latest_raw()
    con.execute("LOAD spatial")
    n = con.execute("SELECT count(*) FROM ST_Read(?)", [str(path)]).fetchone()[0]
    if n < min_rows:
        raise FootprintsError(f"{path} holds {n:,} features, under the {min_rows:,} floor "
                              f"-- a truncated download, not a smaller city")
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    con.execute("BEGIN")
    try:
        con.execute(f"DELETE FROM {TABLE}")
        con.execute(f"""
            INSERT INTO {TABLE} ({', '.join(COLUMNS)})
            SELECT bin, base_bbl, mappluto_bbl, geom,
                   TRY_CAST(height_roof AS DOUBLE), TRY_CAST(ground_elevation AS DOUBLE),
                   TRY_CAST(construction_year AS INTEGER), feature_code, last_status_type,
                   TRY_CAST(last_edited_date AS TIMESTAMP), geom_source,
                   TRY_CAST(shape_area AS DOUBLE), doitt_id, ?
            FROM ST_Read(?)
        """, [now, str(path)])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    got = con.execute(f"SELECT count(*), count(DISTINCT bbl), "
                      f"sum(CASE WHEN last_status = 'Demolition' THEN 1 ELSE 0 END) "
                      f"FROM {TABLE}").fetchone()
    return {"file": str(path), "rows": int(got[0]), "bbls": int(got[1]),
            "demolition_rows": int(got[2] or 0)}
