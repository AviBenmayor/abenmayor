"""Census TIGER/Line ZCTA polygons, all three vintages served nationally
(2000, 2010, 2020) -- GEOGRAPHY pillar input for RQ-002 (Greenpoint towers,
docs/research/RQ-002-greenpoint-towers-retail/). Registry id
`census_tiger_zcta` (drafted, not yet registered -- see
docs/research/RQ-002-greenpoint-towers-retail/drafts/registry-census.yaml).

WHY THIS EXISTS
---------------------------------------------------------------------------
DATA-AUDIT.md's GEOGRAPHY row found the exact gap this fills: nothing in the
warehouse or registry lets a lon/lat-grain table (`analysis.poi_first_seen`,
`analysis.licence_interval`, etc. -- none of which carry a `zip` column) be
spatially joined to ZIP 11222 at all. This module is a plain polygon fetch +
point-in-polygon helper, not a POI source: it writes no `staging.poi` rows
and touches no warehouse table (research-only, like `zillow.py`/
`acs_zcta_panel.py` in this same directory).

THREE VINTAGES, THREE FILES, VERIFIED LIVE 2026-09-22
---------------------------------------------------------------------------
ZCTA5 boundaries are redrawn once a decade to track the ZCTA5 codes tabulated
in each decennial census. TIGER/Line re-releases the classic (2000, 2010)
vintages in the modern shapefile format under this same TIGER2010 tree, so
all three vintages come from stable, HEAD-verified national URLs:

  2000: https://www2.census.gov/geo/tiger/TIGER2010/ZCTA5/2000/tl_2010_us_zcta500.zip
        (TIGER2010-era release OF THE 2000 ZCTA5 boundaries; field ZCTA5CE00)
  2010: https://www2.census.gov/geo/tiger/TIGER2010/ZCTA5/2010/tl_2010_us_zcta510.zip
        (field ZCTA5CE10)
  2020: https://www2.census.gov/geo/tiger/TIGER2020/ZCTA520/tl_2020_us_zcta520.zip
        (field ZCTA5CE20)

Each is a national file, ~500-530 MB zipped, ~33,000 ZCTAs -- ALL ZCTAs are
kept (no state/NYC pre-filter on the primary output), per the owner's "never
limit data pulls" rule (CLAUDE.md / feedback_never_limit_data_pulls). An
NYC-subset file is written alongside each national one purely as a
convenience (smaller file to load for NYC-only work); it is NOT a
replacement for the national file and nothing here treats it as the primary
artifact.

CRS: NAD83 IN, EPSG:4326 OUT -- EXPLICIT, NOT ASSUMED
---------------------------------------------------------------------------
TIGER/Line ships geometry in NAD83 (EPSG:4269), not WGS84. Per CLAUDE.md's
invariant ("DuckDB GEOMETRY carries no SRID; everything is EPSG:4326 by
convention"), this module reprojects explicitly with `to_crs(epsg=4326)`
(pyproj-backed, not a silent relabel) before writing anything out, and every
output parquet's geometry is WGS84 by construction. NAD83->WGS84 is a
sub-meter shift in the contiguous US, but "close enough to skip" is exactly
the kind of unchecked assumption CLAUDE.md calls out -- reproject for real.

OUTPUT SHAPE
---------------------------------------------------------------------------
data/interim/rq002/zcta_boundaries/zcta_{year}.parquet -- one row per ZCTA:
  zcta (str, 5-digit, zero-padded), vintage (int: 2000/2010/2020),
  geometry (WKB, EPSG:4326). Written with geopandas' GeoParquet writer
  (`to_parquet`), which embeds the CRS in the file's own metadata; a plain
  `pd.read_parquet` still gets a valid WKB `geometry` column since GeoParquet
  is a superset of Parquet, so downstream code that only wants WKB does not
  need geopandas installed.
data/interim/rq002/zcta_boundaries/zcta_{year}_nyc.parquet -- convenience
  subset (`zcta` string prefix in NYC's ZIP3 set, see NYC_ZIP_PREFIXES).

POINT-IN-POLYGON HELPER
---------------------------------------------------------------------------
`assign_zcta(lon, lat, vintage=2020)` and `assign_zcta_df(df, lon_col,
lat_col, vintage=2020)` do exact point-in-polygon against the vintage's
national polygon set (via a cached `shapely.STRtree`, not a bounding-box
approximation). A point matching zero or more than one polygon returns None
/ raises respectively -- ZCTAs do not overlap by construction, so a
multi-match means a data problem, not a legitimate ambiguity to hide.

CAVEATS THE DATABASE / THIS MODULE CANNOT ENFORCE
---------------------------------------------------------------------------
- ZCTA boundaries are NOT ZIP codes: a ZCTA is the Census Bureau's own
  areal approximation of USPS ZIP delivery routes, built from the block
  assignments of the people who reported that ZIP on their census form. A
  ZCTA5 code that is numerically identical across vintages is NOT
  guaranteed to cover the same area (2010->2020 in particular redrew many
  NYC ZCTA boundaries) -- callers must pass the vintage matching the data
  being joined, never assume 2020 boundaries apply to a pre-2020 point-in-
  time table.
- PO-box-only and non-residential ZIP codes are not autonomous ZCTAs in any
  vintage (they get absorbed into a neighboring ZCTA's polygon or have no
  ZCTA at all) -- `assign_zcta` on such a point returns whatever ZCTA
  physically contains it, which will not equal that ZIP code.
- This module does not build the ZIP-merge crosswalk (11211+11249,
  10021+10065+10075, 11101+11109) -- that is explicitly a peer session's
  (abenmayor-9f, RQ-001) job per this task's brief.
"""
from __future__ import annotations

import pathlib
import zipfile

import geopandas as gpd
import pandas as pd
import requests
import shapely

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
RAW_DIR = REPO_ROOT / "data" / "raw" / "census_tiger_zcta"
INTERIM_DIR = REPO_ROOT / "data" / "interim" / "rq002" / "zcta_boundaries"

# Verified live 2026-09-22 (HTTP HEAD, 200 + application/zip on all three).
URLS: dict[int, str] = {
    2000: "https://www2.census.gov/geo/tiger/TIGER2010/ZCTA5/2000/tl_2010_us_zcta500.zip",
    2010: "https://www2.census.gov/geo/tiger/TIGER2010/ZCTA5/2010/tl_2010_us_zcta510.zip",
    2020: "https://www2.census.gov/geo/tiger/TIGER2020/ZCTA520/tl_2020_us_zcta520.zip",
}
RAW_FILES: dict[int, pathlib.Path] = {
    year: RAW_DIR / pathlib.Path(url).name for year, url in URLS.items()
}
# Shapefile attribute field carrying the ZCTA5 code, per vintage (verified
# against each file's own .dbf after download).
ZCTA_FIELD: dict[int, str] = {2000: "ZCTA5CE00", 2010: "ZCTA5CE10", 2020: "ZCTA5CE20"}

VINTAGES = (2000, 2010, 2020)

# ZIP3 prefixes covering the five NYC boroughs' ZIP ranges (Manhattan
# 100-102, Bronx 104, Staten Island 103, Brooklyn 112, Queens 111/113/114/116),
# for the NYC convenience subset only -- NOT used to filter the primary
# national output.
NYC_ZIP3_SET = {"100", "101", "102", "103", "104", "111", "112", "113", "114", "116"}


def fetch_raw(year: int, *, force: bool = False, timeout: int = 900) -> pathlib.Path:
    """Download (or reuse the cached copy of) the national ZCTA5 shapefile
    zip for `year`. Streams to disk (files run 500+ MB) and fails loud on a
    non-2xx response or a zero-byte body -- never caches a truncated file."""
    if year not in URLS:
        raise ValueError(f"unknown ZCTA vintage {year!r}; expected one of {VINTAGES}")
    path = RAW_FILES[year]
    if path.exists() and not force:
        if path.stat().st_size == 0:
            path.unlink()
        else:
            return path
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with requests.get(URLS[year], stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        tmp = path.with_suffix(".part")
        n_bytes = 0
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if chunk:
                    fh.write(chunk)
                    n_bytes += len(chunk)
        if n_bytes == 0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"ZCTA {year} download returned an empty body from {URLS[year]}")
        tmp.rename(path)
    return path


def load_vintage(year: int, *, force: bool = False,
                  path: pathlib.Path | None = None) -> gpd.GeoDataFrame:
    """National ZCTA polygon set for `year`, reprojected to EPSG:4326.

    Columns: zcta (str, 5-digit), vintage (int), geometry (WGS84 polygon/
    multipolygon). Fails loud if the read comes back empty or the expected
    ZCTA field is missing (schema drift upstream)."""
    zip_path = path or fetch_raw(year, force=force)
    gdf = gpd.read_file(zip_path)
    if gdf.empty:
        raise RuntimeError(f"ZCTA {year} shapefile at {zip_path} parsed to zero rows")
    field = ZCTA_FIELD[year]
    if field not in gdf.columns:
        raise RuntimeError(
            f"ZCTA {year} shapefile at {zip_path} is missing expected field "
            f"{field!r} (has: {list(gdf.columns)}) -- schema likely changed upstream")
    gdf = gdf[[field, "geometry"]].rename(columns={field: "zcta"})
    gdf["zcta"] = gdf["zcta"].astype(str).str.zfill(5)
    gdf["vintage"] = year
    if gdf.crs is None:
        raise RuntimeError(f"ZCTA {year} shapefile has no CRS set -- cannot reproject safely")
    gdf = gdf.to_crs(epsg=4326)
    return gdf[["zcta", "vintage", "geometry"]].reset_index(drop=True)


def build(*, force: bool = False, years: tuple[int, ...] = VINTAGES) -> dict[int, pathlib.Path]:
    """Fetch + reproject every vintage, write national + NYC-subset
    GeoParquet under data/interim/rq002/zcta_boundaries/. Prints one
    progress line per vintage."""
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[int, pathlib.Path] = {}
    for year in years:
        gdf = load_vintage(year, force=force)
        national_path = INTERIM_DIR / f"zcta_{year}.parquet"
        gdf.to_parquet(national_path)
        nyc = gdf[gdf["zcta"].str[:3].isin(NYC_ZIP3_SET)]
        nyc_path = INTERIM_DIR / f"zcta_{year}_nyc.parquet"
        nyc.to_parquet(nyc_path)
        print(f"[census_zcta_boundaries] {year}: {len(gdf)} ZCTAs nationally, "
              f"{len(nyc)} NYC-prefix ZCTAs -> {national_path.name}, {nyc_path.name}")
        out[year] = national_path
    return out


# ------------------------------------------------------------- point lookup

_TREE_CACHE: dict[int, tuple["shapely.STRtree", pd.Series]] = {}


def _tree_for(vintage: int) -> tuple["shapely.STRtree", pd.Series]:
    if vintage not in VINTAGES:
        raise ValueError(f"unknown ZCTA vintage {vintage!r}; expected one of {VINTAGES}")
    if vintage in _TREE_CACHE:
        return _TREE_CACHE[vintage]
    path = INTERIM_DIR / f"zcta_{vintage}.parquet"
    if not path.exists():
        raise RuntimeError(
            f"{path} does not exist -- run census_zcta_boundaries.build() first "
            f"(vintage {vintage} has not been fetched)")
    gdf = gpd.read_parquet(path)
    tree = shapely.STRtree(gdf.geometry.values)
    codes = gdf["zcta"].reset_index(drop=True)
    _TREE_CACHE[vintage] = (tree, codes)
    return tree, codes


def assign_zcta(lon: float, lat: float, vintage: int = 2020) -> str | None:
    """Point-in-polygon ZCTA lookup for one (lon, lat) in EPSG:4326 against
    `vintage`'s national polygon set. Returns the ZCTA5 code, or None if the
    point falls in no ZCTA (open water, unassigned territory). Raises if the
    point matches more than one ZCTA -- ZCTAs are non-overlapping by
    construction, so that would mean a data problem, not legitimate
    ambiguity."""
    tree, codes = _tree_for(vintage)
    point = shapely.Point(lon, lat)
    candidate_idx = tree.query(point, predicate="intersects")
    if len(candidate_idx) == 0:
        return None
    if len(candidate_idx) > 1:
        matches = sorted(set(codes.iloc[candidate_idx]))
        if len(matches) == 1:
            return matches[0]  # duplicate polygon rows for the same ZCTA, not a real conflict
        raise RuntimeError(
            f"point ({lon}, {lat}) matched {len(matches)} distinct ZCTAs at vintage "
            f"{vintage}: {matches} -- ZCTAs should not overlap")
    return str(codes.iloc[candidate_idx[0]])


def assign_zcta_df(df: pd.DataFrame, lon_col: str = "lon", lat_col: str = "lat",
                    vintage: int = 2020) -> pd.Series:
    """Vectorized point-in-polygon ZCTA lookup for every row of `df`. Returns
    a Series aligned to `df.index`, one ZCTA5 code (or None) per row. Uses a
    single spatial join against the cached STRtree rather than calling
    `assign_zcta` in a Python loop."""
    tree, codes = _tree_for(vintage)
    points = shapely.points(df[lon_col].to_numpy(), df[lat_col].to_numpy())
    # `point_idx`/`poly_idx` from shapely.STRtree.query are POSITIONAL
    # (0-based into `points`/the tree's own geometry array), NOT aligned to
    # `df.index` -- df may have an arbitrary index. Every downstream
    # position -> label translation is explicit below.
    point_idx, poly_idx = tree.query(points, predicate="intersects")
    result = pd.Series([None] * len(df), index=df.index, dtype=object)
    if len(point_idx) == 0:
        return result
    # Group polygon matches per point (still positional); flag (don't
    # silently pick) multi-matches that resolve to genuinely different ZCTA
    # codes.
    matched = pd.DataFrame({"point_idx": point_idx, "zcta": codes.iloc[poly_idx].to_numpy()})
    grouped = matched.groupby("point_idx")["zcta"].agg(lambda s: sorted(set(s)))
    conflicts = grouped[grouped.apply(len) > 1]
    if not conflicts.empty:
        first_pos = conflicts.index[0]
        raise RuntimeError(
            f"{len(conflicts)} point(s) matched multiple distinct ZCTAs at vintage "
            f"{vintage} (first: row label {df.index[first_pos]!r} -> {conflicts.iloc[0]}) -- "
            "ZCTAs should not overlap")
    single = grouped.apply(lambda s: s[0])
    result.iloc[single.index.to_numpy()] = single.to_numpy()
    return result


if __name__ == "__main__":
    build()
