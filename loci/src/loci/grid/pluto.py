"""Build commercial zoning capacity and development-headroom controls onto the
H3 grid, from NYC MapPLUTO tax-lot data.

CONTEXT.md §1.3, §4.5. `comm_far_capacity` is a **required** control for the
supply model: without it the residual's underserved tail fills with park
edges, industrial zones, and cemetery-adjacent blocks -- places with no retail
because retail is not *legal* there, not because it is under-provided.

Source: NYC MapPLUTO, Socrata dataset `64uk-42ks` (CONTEXT.md §3.4). This is
not a POI source -- it writes analysis.hex_controls, not staging.poi -- so it
is a plain builder module (see src/loci/grid/build.py), not a SourceAdapter.

Writes only the 5 PLUTO-derived columns of analysis.hex_controls via
UPSERT, leaving the MTA-derived columns (walk_m_to_subway, subway_routes,
subway_riders_2024) untouched so this can run before or after that loader.
"""
from __future__ import annotations

import pathlib

import h3
import pandas as pd

from loci import db as locidb

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PLUTO_CSV = REPO_ROOT / "data" / "raw" / "pluto.csv"

RES = 9

# Columns pulled from the ~90-column MapPLUTO export. Selected by name in SQL
# (case-insensitive), so this list documents the contract rather than driving it.
_PLUTO_COLUMNS = (
    "latitude", "longitude", "lotarea", "commfar", "residfar",
    "builtfar", "unitsres", "yearbuilt", "zonedist1", "bbl",
)


def _read_lots(con, pluto_csv: pathlib.Path) -> pd.DataFrame:
    """Read the columns needed from the MapPLUTO CSV, coerce to numeric, and
    drop lots with no usable coordinates or lot area. Everything is read as
    VARCHAR first (ALL_VARCHAR) because the raw export mixes blanks and
    numbers in the same column and a strict auto-inferred type would error."""
    df = con.execute(
        """
        SELECT
            TRY_CAST(latitude  AS DOUBLE) AS lat,
            TRY_CAST(longitude AS DOUBLE) AS lon,
            TRY_CAST(lotarea   AS DOUBLE) AS lotarea,
            COALESCE(TRY_CAST(commfar  AS DOUBLE), 0) AS commfar,
            COALESCE(TRY_CAST(residfar AS DOUBLE), 0) AS residfar,
            COALESCE(TRY_CAST(builtfar AS DOUBLE), 0) AS builtfar,
            COALESCE(TRY_CAST(unitsres AS DOUBLE), 0) AS unitsres
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        """,
        [str(pluto_csv)],
    ).df()

    keep = (
        df["lat"].notna() & df["lon"].notna()
        & (df["lat"] != 0) & (df["lon"] != 0)
        & df["lotarea"].notna() & (df["lotarea"] > 0)
    )
    return df.loc[keep].reset_index(drop=True)


def _assign_hex(lots: pd.DataFrame) -> pd.DataFrame:
    """Assign each lot to its H3 res-9 cell from (lat, lon)."""
    lots = lots.copy()
    lots["h3_index"] = [
        h3.latlng_to_cell(lat, lon, RES)
        for lat, lon in zip(lots["lat"], lots["lon"])
    ]
    return lots.drop(columns=["lat", "lon"])


def _aggregate(con) -> pd.DataFrame:
    """Area-weighted per-hex aggregation of the `_pluto_lots` table already
    registered on `con` (columns: h3_index, lotarea, commfar, residfar,
    builtfar, unitsres -- all lotarea > 0), restricted to cells present in
    analysis.hex. Factored out so the arithmetic is testable without the CSV.
    """
    return con.execute(
        """
        SELECT
            l.h3_index,
            SUM(l.commfar  * l.lotarea) / SUM(l.lotarea) AS comm_far_capacity,
            SUM(l.residfar * l.lotarea) / SUM(l.lotarea) AS resid_far,
            SUM(l.builtfar * l.lotarea) / SUM(l.lotarea) AS built_far,
            SUM(GREATEST(l.residfar - l.builtfar, 0) * l.lotarea)
                / SUM(l.lotarea)                          AS dev_headroom,
            SUM(l.unitsres)                               AS units_res
        FROM _pluto_lots l
        JOIN analysis.hex h ON h.h3_index = l.h3_index
        GROUP BY l.h3_index
        """
    ).df()


def build_pluto_controls(con, pluto_csv: pathlib.Path | str = PLUTO_CSV) -> int:
    """Load MapPLUTO, aggregate onto the H3 grid, and UPSERT the 5 PLUTO
    columns of analysis.hex_controls. Idempotent; co-exists with the MTA
    writer (walk_m_to_subway, subway_routes, subway_riders_2024 untouched).
    Returns the number of hex rows written.
    """
    pluto_csv = pathlib.Path(pluto_csv)
    if not pluto_csv.exists():
        raise FileNotFoundError(
            f"MapPLUTO CSV not found at {pluto_csv}. Download it once from "
            "https://data.cityofnewyork.us/api/views/64uk-42ks/rows.csv?accessType=DOWNLOAD"
        )

    lots = _read_lots(con, pluto_csv)
    lots = _assign_hex(lots)

    con.register("_pluto_lots", lots[["h3_index", "lotarea", "commfar", "residfar", "builtfar", "unitsres"]])
    try:
        agg = _aggregate(con)
    finally:
        con.unregister("_pluto_lots")

    con.register("_pluto_agg", agg)
    try:
        con.execute(
            """
            INSERT INTO analysis.hex_controls
                (h3_index, comm_far_capacity, resid_far, built_far, dev_headroom, units_res)
            SELECT h3_index, comm_far_capacity, resid_far, built_far, dev_headroom, units_res
            FROM _pluto_agg
            ON CONFLICT (h3_index) DO UPDATE SET
                comm_far_capacity = EXCLUDED.comm_far_capacity,
                resid_far         = EXCLUDED.resid_far,
                built_far         = EXCLUDED.built_far,
                dev_headroom      = EXCLUDED.dev_headroom,
                units_res         = EXCLUDED.units_res
            """
        )
    finally:
        con.unregister("_pluto_agg")

    return len(agg)


def main() -> None:
    con = locidb.connect()
    locidb.init_schema(con)
    n = build_pluto_controls(con)
    print(f"wrote controls for {n} hexes")


if __name__ == "__main__":
    main()
