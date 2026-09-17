"""Address-level ACS demographics (D56): income, tenure, and vehicle
ownership per residential PLUTO lot, TAKEN DIRECTLY from the lot's 2020
census tract -- no apportionment. A PLUTO tax lot sits in exactly one
census tract, unlike the H3 hex grid (grid/acs.py), where a hex can
straddle several tracts and unit-share (dasymetric) weighting is required.
Direct assignment is strictly simpler and loses nothing: there is nothing
to apportion when the geography is 1:1.

Tract assignment -- the cheapest correct path, not a spatial join
--------------------------------------------------------------------------
PLUTO's own `bct2020` column (2020 census tract, DCP-computed) already sits
on every tax lot; it is the exact field grid/acs.py's `_tract_hex_weights`
already trusts to interpolate demographics onto hexes. Since
`address_id` IS the tax lot's BBL for every lot that has one
(sources/cities/nyc/addresses.py), joining address -> tract is a lookup on
BBL against the raw PLUTO extract, not a point-in-polygon join: no TIGER
shapefile download, no `spatial` extension call needed here at all.

Measured coverage (2026-09-09, data/raw/pluto.csv, all 5 boroughs, the same
UnitsRes > 0 + valid-lat/lon filter addresses.py applies): 767,337
residential lots, every one with a non-blank, non-colliding BBL, and all
but 6 (99.9992%) with a non-null `bct2020`. The 6 addresses with no tract
get NULL demographics, never dropped -- they still appear in
analysis.address_demographics with tract_geoid IS NULL.

ACS values
--------------------------------------------------------------------------
Reuses grid.acs.fetch_acs's cache-first tract-level ACS pull
(data/raw/acs/tracts_2023.json already carries every variable this module
needs -- B01003, B11001, B19013, B25003, B08201, B25044 for income/tenure/
vehicles, plus B01002, B01001, B03002, B15003, B25010, B11016 for age, race,
education and household size -- so this module makes no new Census API call),
and grid.acs's OWN definitions of every derived measure: `SHARE_SPECS` and
`INTENSIVE_SPECS` (which cells make which column), `_sum_cells` (the handbook
sum rule within a tract) and `_moe_proportion` (the handbook derived-proportion
MOE). They are imported, never copied: the hex table and this table therefore
cannot define `college_share` (or any other measure) two different ways, and
adding a measure to grid/acs.py adds it here for free.

Because there is no apportionment, the "sum-of-squares across tracts" step in
grid/acs.py's `build_acs` does not apply here: each address's numerator and
denominator MOEs ARE the tract's own MOEs, taken as-is. Nor does the hex
table's "a unit-weighted mean of tract medians is not a median" caveat -- for
median_hh_income, median_age and avg_hh_size this table holds the tract's own
published figure, not a weighted mean of several tracts'. This table is
strictly LESS modelled than analysis.hex_demographics, which is why D56 made
it the canonical demographic carrier for the address screen.

THE STREET FRAME (owner ruling 4, 2026-09-16)
--------------------------------------------------------------------------
D84 put a second sampling frame into `analysis.address`: a point every 100 m
along every kept CSCL street segment, `bbl` NULL, `units` 0. Until 2026-09-16
those 50,199 rows had NO row here at all, and every join to this table being a
LEFT join, they surfaced as NULL and never raised. The owner's ruling: the
street frame gets everything the lot frame has.

A street midpoint sits in exactly one census tract for the same reason a lot
centroid does, so the VALUE rule is unchanged -- the tract's own ACS row, taken
verbatim, no apportionment. Only the ASSIGNMENT differs, and it has to:

  * a LOT is assigned by a BBL lookup against PLUTO's `bct2020`, which is DCP's
    own point-in-polygon, precomputed. There is no polygon in this repo and
    never was; the module that claims "no point-in-polygon join" is describing
    the fact that DCP already did it.
  * a STREET midpoint has no BBL (it is not a tax lot), so there is nothing to
    look up. It is assigned by an ACTUAL point-in-polygon against 2020 TIGER
    census-tract polygons -- `assign_tracts_by_point` below.

NOT the nearest lot's tract, which would make an industrial street inherit the
income of the one apartment building 300 m away, and not the nearest tract
centroid, which is the same error wearing a spatial costume.

VINTAGE DISCIPLINE -- THE ERROR THE DATABASE CANNOT CATCH (CONTEXT 7.4b)
--------------------------------------------------------------------------
ACS 2023 5-year is published on 2020 tract geography; ACS 2009/2013 sit on 2010
geography. A street midpoint resolved against 2010 tract polygons and joined to
an ACS 2023 row produces a plausible-looking number for the wrong place, in the
wrong tract, with no NULL and no error anywhere. Three guards, all fail-loud:

  1. `ACS_TRACT_VINTAGE` maps the ACS year to the tract geography it is
     published on; an unknown year raises rather than defaulting.
  2. the polygon file's own field names are read (`GEOID10` is a 2010 file,
     `GEOID`/`GEOID20` a 2020 one) and must agree with (1).
  3. the polygon GEOIDs are cross-checked against the GEOIDs the ACS pull
     itself returned -- `MIN_ACS_GEOID_OVERLAP` of the in-scope polygons must
     appear in the ACS keyset. This is the guard that actually bites: a
     2010-vintage file whose fields were renamed still fails here, because
     NYC's tract ids were substantially recut between 2010 and 2020.

The polygon file is read through DuckDB `spatial`'s `ST_Read`. Its CRS is read
from `ST_Read_Meta` and, if it is not EPSG:4326, reprojected EXPLICITLY with
`ST_Transform(..., always_xy := true)`: DuckDB `GEOMETRY` carries no SRID, so
nothing else in the stack would have caught a NAD83 (4269) TIGER file silently
mixing with 4326 address coordinates. Containment is topological, so there is
no metric step and no reprojection to a projected CRS -- unlike every distance
in this project.

A point that no polygon contains gets a row with `tract_geoid IS NULL` and
every measure NULL. It is never dropped: "in the universe, tract unknown" and
"not in the universe" are different facts and the no-eligibility-gate rule
(owner 2026-09-13) forbids the second.

CAVEATS THE DATABASE CANNOT ENFORCE, STREET FRAME
--------------------------------------------------------------------------
1. THE ROW DESCRIBES THE TRACT, NOT THE STREET. A street midpoint has no
   residents -- `units` is 0 by construction. `median_hh_income` on a street
   row is the income of the households in the surrounding tract, which is the
   catchment the point sits in, not a property of the point. This is the same
   relationship a lot row has to its tract, but for a lot the tract at least
   contains the lot's own households; for a street point it contains none.
2. ONE STREET IS NOT ONE TRACT. Census tract boundaries in NYC very often RUN
   ALONG street centrelines, so (a) the two ends of one street segment can sit
   in different tracts and will get different demographics, and (b) the
   midpoint of a boundary street sits ON the line. `ST_Intersects` matches both
   neighbours there; the tie is broken DETERMINISTICALLY by the lower GEOID and
   COUNTED (`boundary_ties` in the report), never resolved by whichever polygon
   the planner happened to reach first. Two points 100 m apart on the same
   street straddling a boundary are a real geography, not a defect -- but
   anyone reading a street row as "this street's income" is over-reading it.
3. DO NOT SUM population/households ACROSS FRAMES EITHER. The lot-frame caveat
   below now compounds: a tract's population is repeated on every lot row AND
   on every street point in it.

THE UNIVERSE IS `analysis.address`, AND IS PRUNED TO IT
--------------------------------------------------------------------------
This table was built from the raw 5-borough PLUTO extract, so after D78 clipped
`analysis.address` to MN+BK it held 485,495 rows for addresses that no longer
exist in the screen's universe -- 63% orphans, invisible because every read
joins FROM `analysis.address`. `prune_out_of_scope` removes them, idempotently,
and `write_address_demographics` calls it. Note this contradicts the aside in
`sources/cities/nyc/addresses.py` (SCREEN_BOROUGHS) that this table is
deliberately citywide: that rationale ("a POI in Queens is still the nearest
pharmacy to an address in Brooklyn") is about POI SUPPLY, which is keyed on
geometry, not about a table keyed on `address_id`, which can only ever be read
by joining the universe it is being pruned to.

THE canonical demographic carrier (D38/D56)
--------------------------------------------------------------------------
analysis.address_demographics is the ONE address-grain demographic table.
`analysis.address_gaps` used to carry a parallel copy of all 36 measures,
joined by CONTAINING H3 HEX (sql/008, first version) -- so the same address
had two different median_hh_income values, one tract-direct and one doubly
modelled. That copy is removed; model/address_gaps.py joins no demographics
at all now and keeps only `h3_index` so an address can still be rolled back
up to the grid. Anything wanting a demographic about an address joins THIS
table on address_id.

CAVEAT THE DATABASE CANNOT ENFORCE -- do not SUM population/households
--------------------------------------------------------------------------
Every address in the same tract carries that tract's FULL population and
household count (this is a per-address ATTRIBUTE lookup, not an
apportionment). Summing `population` or `households` over more than one
address is an N-times overcount, N being the number of addresses sharing
that tract -- exactly the double-count failure mode CLAUDE.md warns about,
just at address grain instead of edge-mirroring. `median_hh_income`,
`renter_share`, `zero_vehicle_*_share` and their MOEs are fine to read
per-address or to take medians/means-of-medians over, because they are
already tract-level rates/medians repeated verbatim, not counts. If a
population TOTAL is needed at some aggregate (NTA, borough, city), get it
from analysis.hex_demographics (apportioned) or straight from ACS by
tract -- never by summing this table's population column across addresses.
"""
from __future__ import annotations

import math
import pathlib

import pandas as pd

from loci.grid.acs import (
    ACS_YEAR,
    BORO_COUNTY,
    INTENSIVE_SPECS,
    PLUTO_CSV,
    SHARE_SPECS,
    _clean,
    _moe_proportion,
    _sum_cells,
    fetch_acs,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: ACS 5-year vintage -> the DECENNIAL TRACT GEOGRAPHY it is published on.
#: CONTEXT.md 7.4b. Closed on purpose: an ACS year that is not in this dict
#: raises rather than defaulting to 2020, because the failure mode of guessing
#: is a plausible number attached to the wrong polygon.
ACS_TRACT_VINTAGE: dict[int, int] = {2009: 2010, 2013: 2010, 2018: 2010, 2023: 2020}

#: Census tract polygons, ONE FILE PER TRACT VINTAGE. Only the street frame
#: needs them (a lot is assigned by PLUTO's precomputed `bct2020`), so a
#: lot-only build never touches this path and never requires the download.
#:
#: Use TIGER/Line, NOT the cartographic-boundary (`cb_*_500k`) file: the
#: cartographic files are clipped to the shoreline, and a street midpoint on a
#: pier, a bridge deck or a bulkhead would fall outside every polygon and take
#: a NULL tract for a reason that is an artifact of the file, not a fact about
#: the city. TIGER/Line tracts extend to the county boundary, water included.
TRACT_POLYGON_DIR = REPO_ROOT / "data" / "raw" / "boundaries"
TRACT_POLYGONS: dict[int, pathlib.Path] = {
    2010: TRACT_POLYGON_DIR / "tl_2010_36_tract10.geojson",
    2020: TRACT_POLYGON_DIR / "tl_2020_36_tract.geojson",
}

#: Which GEOID field name proves which vintage. TIGER suffixes every field of a
#: 2010-vintage file with `10` and leaves the 2020 files unsuffixed (the 2020
#: cartographic files use `GEOID20`). Reading the field name is guard #2; it is
#: cheap and it catches the "downloaded the wrong decade" mistake before any
#: geometry is touched.
TRACT_GEOID_FIELDS: dict[int, tuple[str, ...]] = {
    2010: ("GEOID10",),
    2020: ("GEOID", "GEOID20"),
}

#: Guard #3, the one that actually bites. At least this share of the in-scope
#: tract polygons must carry a GEOID the ACS pull itself returned. NYC's tracts
#: were substantially recut between 2010 and 2020, so a mismatched vintage
#: cannot clear this bar even if someone renamed the fields. Set below 1.0 only
#: because TIGER carries a handful of water-only tracts that ACS does not
#: publish, never to tolerate a vintage mismatch.
MIN_ACS_GEOID_OVERLAP = 0.98

#: The five NYC county FIPS, as the first five characters of a tract GEOID.
#: The statewide TIGER file is clipped to these before any join -- the
#: `staging.alcohol_licences` lesson (a statewide feed ingested with no clip
#: reached Buffalo). A Westchester polygon could never contain an NYC street
#: point, but carrying 5,400 of them into a spatial join to prove it is waste,
#: and the drop is COUNTED rather than assumed.
NYC_TRACT_PREFIXES: tuple[str, ...] = tuple(
    "36" + c for c in ("005", "047", "061", "081", "085"))

#: What `analysis.address.frame` calls the two sampling frames. Restated here
#: rather than imported, because model/address_gaps.py pulls in osmnx and scipy
#: and this module needs neither; `tests/test_street_frame_coverage.py` asserts
#: these are the same two strings address_gaps.FRAMES declares, so they cannot
#: drift silently.
LOT_FRAME = "lot"
STREET_FRAME = "street"

# Columns this table carries -- the drift test (tests/test_address_demographics.py)
# asserts analysis.address_demographics' column list matches this constant, so
# an edit to one without the other fails loudly instead of silently drifting.
#
# The 2026-09-09 age / race / education / household-size block is NOT written
# out by hand: it is generated from grid/acs.py's own INTENSIVE_SPECS and
# SHARE_SPECS, the same two dicts build_acs drives the hex table from. Adding
# a measure to grid/acs.py therefore adds it here automatically, and the drift
# test (tests/test_address_gaps_demographics.py) asserts every
# hex_demographics measure has an address_demographics twin -- so a demographic
# can no longer land on the hex grid alone (D38/D56).
ADDRESS_DEMOGRAPHICS_MEASURES: tuple[str, ...] = (
    "population",
    "households",
    "median_hh_income",
    "renter_share",
    "zero_vehicle_hh_share",
    "zero_vehicle_owner_share",
    "zero_vehicle_renter_share",
    *INTENSIVE_SPECS,          # median_age, avg_hh_size
    *SHARE_SPECS,              # under_18_share ... one_person_hh_share
)

ADDRESS_DEMOGRAPHICS_COLUMNS = [
    "address_id", "bbl", "tract_geoid", "acs_year",
    *[c for m in ADDRESS_DEMOGRAPHICS_MEASURES for c in (m, f"{m}_moe")],
]


def load_bbl_tract_map(pluto_csv: pathlib.Path | str = PLUTO_CSV) -> pd.DataFrame:
    """BBL -> 2020 census tract GEOID, straight off the raw PLUTO extract.

    Same construction grid/acs.py's `_tract_hex_weights` uses for the hex
    table: county from borocode (BORO_COUNTY), tract from `bct2020` with its
    leading borough digit stripped and zero-padded to 6. Returns one row per
    BBL with a non-null bct2020; a BBL missing from the result has no tract
    (caller must left-join and expect NaN, not drop).
    """
    lots = pd.read_csv(
        pluto_csv, dtype=str,
        usecols=["BBL", "borocode", "bct2020"],
    )
    lots = lots.rename(columns={"BBL": "bbl"})
    lots = lots[lots["bct2020"].notna() & (lots["bct2020"] != "")]
    lots["county"] = lots["borocode"].map(BORO_COUNTY)
    lots = lots[lots["county"].notna()].copy()
    lots["tract_geoid"] = "36" + lots["county"] + lots["bct2020"].str[1:].str.zfill(6)
    lots = lots.drop_duplicates(subset="bbl")
    return lots[["bbl", "tract_geoid"]]


# ------------------------------------------------- the street frame: tracts

def tract_vintage_for(year: int) -> int:
    """The decennial tract geography ACS 5-year `year` is published on.

    Raises on an unlisted year. There is no sensible default: guessing 2020 for
    an ACS 2013 build would resolve every street midpoint against polygons that
    did not exist in 2013 and join the result to 2013 estimates, and nothing
    downstream -- no NULL, no constraint, no row count -- would show it.
    """
    if year not in ACS_TRACT_VINTAGE:
        raise RuntimeError(
            f"ACS {year} has no declared tract vintage. Add it to "
            f"ACS_TRACT_VINTAGE (CONTEXT.md 7.4b: 2009/2013/2018 are 2010 "
            f"geography, 2023 is 2020) -- refusing to guess, because the wrong "
            f"geography produces a plausible number for the wrong place.")
    return ACS_TRACT_VINTAGE[year]


def _layer_meta(mem, path: pathlib.Path) -> tuple[list[str], tuple[str, str] | None]:
    """(field names, (crs_auth_name, crs_auth_code)) of the polygon file's
    first layer, straight from GDAL via `ST_Read_Meta`."""
    row = mem.execute("SELECT layers FROM ST_Read_Meta(?)", [str(path)]).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"{path} has no readable layer (ST_Read_Meta returned nothing).")
    layer = row[0][0]
    fields = [f["name"] for f in layer["fields"]]
    geom_fields = layer.get("geometry_fields") or []
    if not geom_fields:
        raise RuntimeError(f"{path} carries no geometry field -- this is not a polygon layer.")
    crs = geom_fields[0].get("crs") or {}
    auth = crs.get("auth_name"), crs.get("auth_code")
    return fields, (auth if all(auth) else None)


def _geoid_field(fields: list[str], vintage: int, path: pathlib.Path) -> str:
    """GUARD #2. The GEOID field name states the file's vintage; it must agree
    with the vintage the ACS year demands."""
    wanted = TRACT_GEOID_FIELDS[vintage]
    present = [f for f in fields if f in wanted]
    if present:
        return present[0]
    wrong = sorted({f for v, names in TRACT_GEOID_FIELDS.items() if v != vintage
                    for f in fields if f in names})
    if wrong:
        other = [v for v, names in TRACT_GEOID_FIELDS.items() if set(names) & set(wrong)]
        raise RuntimeError(
            f"{path} is a {other[0]}-vintage tract file (it carries {wrong}), but "
            f"this build needs {vintage} geography. Resolving a point against the "
            f"wrong decade's polygons and joining it to the other decade's ACS "
            f"estimates is silent and plausible -- refusing. See CONTEXT.md 7.4b.")
    raise RuntimeError(
        f"{path} carries none of the expected {vintage} tract GEOID fields "
        f"{wanted}; its fields are {sorted(fields)}.")


def _read_tract_polygons(mem, path: pathlib.Path, vintage: int) -> dict:
    """Create table `tract(tract_geoid, geom)` in `mem`, clipped to the five NYC
    counties and reprojected to EPSG:4326 if it is not already. Returns a report.

    REPROJECTION IS EXPLICIT. DuckDB `GEOMETRY` carries no SRID: a NAD83
    (EPSG:4269) TIGER file and 4326 address coordinates mix without complaint,
    and the ~1 m disagreement between the datums would land squarely on the
    tract boundaries that run down NYC's street centrelines -- exactly where the
    street frame's points are. `always_xy := true` because EPSG:4326's authority
    axis order is (lat, lon) and every coordinate in this project is (lon, lat).
    """
    path = pathlib.Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is absent: the {vintage} census-tract polygons the STREET "
            f"frame is assigned by. Without them the 50,199 street-frame "
            f"addresses would silently keep no demographics row at all, which is "
            f"the exact absence owner ruling 4 (2026-09-16) exists to remove. "
            f"Download TIGER/Line tl_{vintage}_36_tract (NOT the cb_*_500k "
            f"cartographic file, which is clipped to the shoreline).")
    fields, crs = _layer_meta(mem, path)
    geoid = _geoid_field(fields, vintage, path)
    if crs is None:
        raise RuntimeError(
            f"{path} declares no CRS. DuckDB GEOMETRY carries no SRID, so an "
            f"undeclared CRS cannot be checked by anything downstream -- refusing "
            f"rather than assuming EPSG:4326.")
    auth_name, auth_code = crs
    if (auth_name, auth_code) == ("EPSG", "4326"):
        geom_expr = "geom"
    else:
        geom_expr = (f"ST_Transform(geom, '{auth_name}:{auth_code}', 'EPSG:4326', "
                     f"always_xy := true)")
    mem.execute(f"""
        CREATE OR REPLACE TABLE tract_all AS
        SELECT CAST("{geoid}" AS VARCHAR) AS tract_geoid, {geom_expr} AS geom
        FROM ST_Read(?)
    """, [str(path)])
    n_all = mem.execute("SELECT count(*) FROM tract_all").fetchone()[0]
    prefixes = ", ".join(f"'{p}'" for p in NYC_TRACT_PREFIXES)
    mem.execute(f"""
        CREATE OR REPLACE TABLE tract AS
        SELECT tract_geoid, geom FROM tract_all
        WHERE substr(tract_geoid, 1, 5) IN ({prefixes})
    """)
    n_nyc, n_distinct, min_len, max_len = mem.execute(
        "SELECT count(*), count(DISTINCT tract_geoid), min(length(tract_geoid)), "
        "max(length(tract_geoid)) FROM tract").fetchone()
    if n_nyc == 0:
        raise RuntimeError(
            f"{path} holds {n_all:,} tract polygons, none of them in the five NYC "
            f"counties {NYC_TRACT_PREFIXES}. Wrong state file, or a GEOID field "
            f"that is not a full 11-character tract id.")
    if n_distinct != n_nyc:
        raise RuntimeError(
            f"{path}: {n_nyc:,} NYC tract polygons but only {n_distinct:,} distinct "
            f"GEOIDs. A duplicated tract would fan a point-in-polygon join out and "
            f"silently duplicate a street address's demographics row.")
    if (min_len, max_len) != (11, 11):
        raise RuntimeError(
            f"{path}: tract GEOIDs are {min_len}-{max_len} characters, not 11. "
            f"This table joins ACS on an 11-character tract GEOID.")
    return {"polygons_in_file": int(n_all), "polygons_nyc": int(n_nyc),
            "polygons_dropped_outside_nyc": int(n_all - n_nyc),
            "geoid_field": geoid, "source_crs": f"{auth_name}:{auth_code}",
            "reprojected": geom_expr != "geom", "tract_vintage": vintage,
            "path": str(path)}


def _check_geoids_against_acs(mem, acs_geoids: set[str], vintage: int,
                              year: int, path: pathlib.Path) -> float:
    """GUARD #3, the one that bites. The polygons and the ACS pull must be
    talking about the same tracts."""
    n = mem.execute("SELECT count(*) FROM tract").fetchone()[0]
    mem.execute("CREATE OR REPLACE TABLE _acs_geoid(tract_geoid VARCHAR)")
    if acs_geoids:
        mem.executemany("INSERT INTO _acs_geoid VALUES (?)",
                        [(g,) for g in sorted(acs_geoids)])
    hit = mem.execute(
        "SELECT count(*) FROM tract t WHERE EXISTS "
        "(SELECT 1 FROM _acs_geoid a WHERE a.tract_geoid = t.tract_geoid)").fetchone()[0]
    share = hit / n if n else 0.0
    if share < MIN_ACS_GEOID_OVERLAP:
        raise RuntimeError(
            f"only {share:.1%} of the {n:,} NYC tract polygons in {path} carry a "
            f"GEOID that ACS {year} returned (floor {MIN_ACS_GEOID_OVERLAP:.0%}). "
            f"ACS {year} is published on {vintage} tract geography; this file is "
            f"almost certainly the other decade's. A point resolved against the "
            f"wrong decade's polygons gets a real tract id, a real income and no "
            f"NULL anywhere -- which is why this raises instead of warning.")
    return float(share)


#: Half-width, IN DEGREES, of the box drawn around a street point to decide
#: whether its tract assignment is BOUNDARY-AMBIGUOUS. 0.0001 deg is 11.1 m of
#: latitude and 8.4 m of longitude at 40.7 deg N -- deliberately anisotropic and
#: deliberately not a metric buffer, because this is a CONFIDENCE FLAG, not a
#: distance, and turning it into one would mean reprojecting 50,199 points to
#: EPSG:2263 to answer a yes/no question.
#:
#: WHY IT MATTERS MORE THAN THE EXACT TIE COUNT. NYC census-tract boundaries
#: very often follow street centrelines -- and the street frame's points sit ON
#: street centrelines. But TIGER digitised its boundary from its own centreline
#: file, not from CSCL, so the two lines differ by a metre or two and the point
#: lands cleanly on ONE side. `n_tract_candidates` is then 1 and nothing looks
#: uncertain, when in truth the assignment was decided by sub-metre disagreement
#: between two agencies' cartography. This flag is what makes that visible.
#: Set to 0 to skip the widened join entirely.
BOUNDARY_EPS_DEG = 0.0001


def assign_tracts_by_point(
    points_df: pd.DataFrame, acs_geoids: set[str], year: int,
    polygons: pathlib.Path | str | None = None,
    boundary_eps_deg: float = BOUNDARY_EPS_DEG,
) -> tuple[pd.DataFrame, dict]:
    """Point-in-polygon tract assignment for points with no tax lot.

    `points_df`: address_id, lon, lat. Returns (frame with one row per input
    address_id carrying `tract_geoid` -- NULL where no polygon contains the
    point -- and `n_tract_candidates`, report).

    EVERY input row comes back. A point outside every polygon is an EXPLICIT
    NULL, never an omission: the no-eligibility-gate rule (owner 2026-09-13)
    makes "in the universe, tract unknown" a row that must exist.

    `ST_Intersects`, not `ST_Contains`: NYC tract boundaries run along street
    centrelines, so a street midpoint on a boundary street sits ON the shared
    edge. `ST_Contains` excludes the boundary and would hand every such point a
    NULL -- a manufactured gap, on exactly the streets the frame exists to see.
    `ST_Intersects` matches BOTH neighbours there, which is a real fan-out: it
    is collapsed here by taking the lower GEOID, deterministically, and the tie
    is COUNTED and reported rather than resolved by scan order.
    """
    import duckdb

    vintage = tract_vintage_for(year)
    path = pathlib.Path(polygons) if polygons is not None else TRACT_POLYGONS[vintage]
    cols = ["address_id", "lon", "lat"]
    missing = [c for c in cols if c not in points_df.columns]
    if missing:
        raise ValueError(f"points_df is missing {missing}; needs {cols}")

    mem = duckdb.connect()
    try:
        mem.execute("INSTALL spatial; LOAD spatial;")
        report = _read_tract_polygons(mem, path, vintage)
        report["acs_geoid_overlap"] = _check_geoids_against_acs(
            mem, acs_geoids, vintage, year, path)
        pts = points_df[cols].copy()
        pts["lon"] = pd.to_numeric(pts["lon"], errors="coerce")
        pts["lat"] = pd.to_numeric(pts["lat"], errors="coerce")
        mem.register("_pts", pts)
        # ONE pass. The join predicate is the WIDENED box, which strictly
        # contains the exact one, so the FILTERed aggregates below are the exact
        # point-in-polygon answer and `n_tract_near` is the ambiguity flag --
        # got for the price of a slightly looser join rather than a second scan.
        eps = float(boundary_eps_deg)
        join_geom = (f"ST_Expand(ST_Point(p.lon, p.lat), {eps})" if eps > 0
                     else "ST_Point(p.lon, p.lat)")
        out = mem.execute(f"""
            SELECT p.address_id,
                   count(t.tract_geoid) FILTER (
                       ST_Intersects(t.geom, ST_Point(p.lon, p.lat)))  AS n_tract_candidates,
                   min(t.tract_geoid) FILTER (
                       ST_Intersects(t.geom, ST_Point(p.lon, p.lat)))  AS tract_geoid,
                   count(t.tract_geoid)                                AS n_tract_near
            FROM _pts p
            LEFT JOIN tract t
                   ON p.lon IS NOT NULL AND p.lat IS NOT NULL
                  AND ST_Intersects(t.geom, {join_geom})
            GROUP BY 1
        """).fetchdf()
    finally:
        mem.close()

    if len(out) != points_df["address_id"].nunique():
        raise RuntimeError(
            f"point-in-polygon returned {len(out):,} rows for "
            f"{points_df['address_id'].nunique():,} distinct address_ids -- the "
            f"GROUP BY was supposed to make that impossible. Refusing to write a "
            f"frame that has silently gained or lost addresses.")
    report.update({
        "points": int(len(out)),
        "assigned": int((out["n_tract_candidates"] > 0).sum()),
        "no_tract": int((out["n_tract_candidates"] == 0).sum()),
        "boundary_ties": int((out["n_tract_candidates"] > 1).sum()),
        "max_candidates": int(out["n_tract_candidates"].max()) if len(out) else 0,
        "missing_coords": int(pts[["lon", "lat"]].isna().any(axis=1).sum()),
        # MAPPING CONFIDENCE, not an error count: how many points sit within
        # BOUNDARY_EPS_DEG of more than one tract. Their assignment is correct
        # as computed and decided by ~1 m of cartography. Expect this to be
        # LARGE for the street frame -- NYC tract boundaries follow street
        # centrelines -- and near zero for anything lot-shaped.
        "boundary_eps_deg": eps,
        "boundary_ambiguous": int((out["n_tract_near"] > 1).sum()) if eps > 0 else None,
    })
    return out[["address_id", "tract_geoid", "n_tract_candidates"]], report


def load_street_frame(con, boroughs: list[str] | None = None) -> pd.DataFrame:
    """The street-midpoint rows of `analysis.address`: address_id, lon, lat,
    borough. Never raises on empty -- a warehouse built before D84 legitimately
    has none, and the caller reports the count."""
    where = [f"COALESCE(frame, '{LOT_FRAME}') = '{STREET_FRAME}'"]
    params: list = []
    if boroughs:
        where.append(f"borough IN ({', '.join('?' for _ in boroughs)})")
        params = list(boroughs)
    return con.execute(
        f"SELECT address_id, lon, lat, borough FROM analysis.address "
        f"WHERE {' AND '.join(where)}", params).fetchdf()


def _cross_check_b25044_vs_b25003(acs: dict[str, dict], year: int) -> None:
    """Same fail-loud sanity check grid/acs.py's `build_acs` runs before
    trusting a pull: B25044's owner+renter total should reconcile with
    B25003's total occupied-unit count for the same tract. A material
    aggregate mismatch means a Census cell index is wrong, not that the data
    is noisy -- this module must raise rather than silently compute wrong
    shares from a bad pull, independent of whether grid/acs.py has already
    run this cycle."""
    diffs, denom = [], 0.0
    for rec in acs.values():
        b25003_tot = _clean(rec.get("B25003_001E"))
        b25044_tot = _clean(rec.get("B25044_001E"))
        b25044_own = _clean(rec.get("B25044_002E"))
        b25044_rent = _clean(rec.get("B25044_009E"))
        if None in (b25003_tot, b25044_tot, b25044_own, b25044_rent):
            continue
        diffs.append(abs(b25044_tot - b25003_tot))
        diffs.append(abs(b25044_tot - (b25044_own + b25044_rent)))
        denom += b25003_tot
    if denom > 0 and (sum(diffs) / denom) > 0.02:
        raise RuntimeError(
            f"B25044/B25003 tract-total cross-check failed for ACS {year} 5-year "
            "-- re-verify cell indices before trusting this pull (see grid/acs.py's "
            "identical check)."
        )


def _cross_check_b01001_vs_b01003(acs: dict[str, dict], year: int) -> None:
    """B01001 (sex by age) and B01003 (total population) are two different ACS
    tables that must report the SAME tract population. If they do not, an age
    cell index is wrong or a GETVARS chunk merged badly -- either way the age-band
    shares would be silently mis-normalised. Raise rather than ingest a silent
    wrong number. Mirrors the identical check in grid/acs.py's build_acs, run
    here too so this module is safe to call whether or not `loci acs` ran first.
    """
    diffs, denom = [], 0.0
    for rec in acs.values():
        a = _clean(rec.get("B01003_001E"))
        b = _clean(rec.get("B01001_001E"))
        if a is None or b is None:
            continue
        diffs.append(abs(b - a))
        denom += a
    if denom > 0 and (sum(diffs) / denom) > 0.02:
        raise RuntimeError(
            f"B01001/B01003 tract-population cross-check failed for ACS {year} "
            "5-year -- re-verify the B01001 cell indices before trusting this pull "
            "(see grid/acs.py's identical check)."
        )


def _tract_row_stats(rec: dict) -> dict:
    """Direct (unapportioned) per-tract stats: the tract's own E/M cells,
    with the three proportion shares (renter, zero-vehicle overall,
    zero-vehicle by tenure) derived via the ACS handbook formula. No
    weighting, no RSS across tracts -- an address sits in exactly one
    tract, so this IS the address's value."""
    pop, pop_m = _clean(rec.get("B01003_001E")), _clean(rec.get("B01003_001M"))
    hh, hh_m = _clean(rec.get("B11001_001E")), _clean(rec.get("B11001_001M"))
    inc, inc_m = _clean(rec.get("B19013_001E")), _clean(rec.get("B19013_001M"))

    occ, occ_m = _clean(rec.get("B25003_001E")), _clean(rec.get("B25003_001M"))
    rent, rent_m = _clean(rec.get("B25003_003E")), _clean(rec.get("B25003_003M"))
    renter_share = rent / occ if (occ and occ > 0 and rent is not None) else None
    renter_share_moe = _moe_proportion(rent, rent_m, occ, occ_m) if occ else None

    veh_den, veh_den_m = _clean(rec.get("B08201_001E")), _clean(rec.get("B08201_001M"))
    veh0, veh0_m = _clean(rec.get("B08201_002E")), _clean(rec.get("B08201_002M"))
    zv_hh = veh0 / veh_den if (veh_den and veh_den > 0 and veh0 is not None) else None
    zv_hh_moe = _moe_proportion(veh0, veh0_m, veh_den, veh_den_m) if veh_den else None

    own_den, own_den_m = _clean(rec.get("B25044_002E")), _clean(rec.get("B25044_002M"))
    own0, own0_m = _clean(rec.get("B25044_003E")), _clean(rec.get("B25044_003M"))
    zv_own = own0 / own_den if (own_den and own_den > 0 and own0 is not None) else None
    zv_own_moe = _moe_proportion(own0, own0_m, own_den, own_den_m) if own_den else None

    rt_den, rt_den_m = _clean(rec.get("B25044_009E")), _clean(rec.get("B25044_009M"))
    rt0, rt0_m = _clean(rec.get("B25044_010E")), _clean(rec.get("B25044_010M"))
    zv_rt = rt0 / rt_den if (rt_den and rt_den > 0 and rt0 is not None) else None
    zv_rt_moe = _moe_proportion(rt0, rt0_m, rt_den, rt_den_m) if rt_den else None

    out = {
        "population": pop, "population_moe": pop_m,
        "households": hh, "households_moe": hh_m,
        "median_hh_income": inc, "median_hh_income_moe": inc_m,
        "renter_share": renter_share, "renter_share_moe": renter_share_moe,
        "zero_vehicle_hh_share": zv_hh, "zero_vehicle_hh_share_moe": zv_hh_moe,
        "zero_vehicle_owner_share": zv_own, "zero_vehicle_owner_share_moe": zv_own_moe,
        "zero_vehicle_renter_share": zv_rt, "zero_vehicle_renter_share_moe": zv_rt_moe,
    }

    # ---- age / race / education / household size (2026-09-09) --------------
    # INTENSIVE fields (median_age, avg_hh_size): the tract's own median or
    # average, and its own MOE, taken verbatim. grid/acs.py has to take a
    # unit-share-weighted MEAN of tract medians because a hex straddles
    # tracts; an address does not, so the "a mean of medians is not a median"
    # approximation that the hex table carries simply does not arise here.
    # This is the tract's published median, full stop.
    for col, stem in INTENSIVE_SPECS.items():
        out[col] = _clean(rec.get(stem + "E"))
        out[f"{col}_moe"] = _clean(rec.get(stem + "M"))

    # SHARE fields: numerator cells summed WITHIN the tract by the ACS
    # handbook sum rule (`_sum_cells`: estimates add, MOEs root-sum-square),
    # divided by the denominator cell from the SAME table, with the handbook's
    # derived-proportion MOE (`_moe_proportion`). Identical arithmetic to
    # grid/acs.py's SHARE_SPECS loop minus the across-tract apportionment step,
    # and driven by the same SHARE_SPECS dict so the two cannot drift.
    for col, (num_cells, den_cell) in SHARE_SPECS.items():
        n_est, n_moe = _sum_cells(rec, num_cells)
        d_est, d_moe = _sum_cells(rec, (den_cell,))
        if d_est and d_est > 0 and n_est is not None:
            out[col] = n_est / d_est
            out[f"{col}_moe"] = _moe_proportion(n_est, n_moe, d_est, d_moe)
        else:
            out[col] = None
            out[f"{col}_moe"] = None

    return out


def build_address_demographics(
    con, addresses_df: pd.DataFrame,
    year: int = ACS_YEAR, pluto_csv: pathlib.Path | str = PLUTO_CSV,
    street_df: pd.DataFrame | None = None,
    polygons: pathlib.Path | str | None = None,
    report: dict | None = None,
) -> pd.DataFrame:
    """addresses_df: must carry `address_id`, `bbl` (sources/cities/nyc/addresses.py's
    output, concatenated across boroughs). Returns one row per address_id,
    every column in ADDRESS_DEMOGRAPHICS_COLUMNS, ready for
    `write_address_demographics`. Addresses whose BBL has no tract (blank
    BBL, or a lot missing bct2020) get tract_geoid + every demographic
    column as NULL/NaN -- never dropped from the returned frame.

    `street_df` (address_id, lon, lat) adds the D84 STREET frame, assigned by
    point-in-polygon (`assign_tracts_by_point`) instead of by BBL, with `bbl`
    NULL on every such row -- which is also what marks the row's provenance: a
    NULL bbl in this table means "tract found by point-in-polygon", a non-NULL
    one means "tract taken from PLUTO's bct2020". No extra column is needed to
    say which, and none is added.

    The two frames share EVERYTHING downstream of the tract id: the same ACS
    pull, the same `_tract_row_stats`, the same per-tract dict, the same merge.
    A street point and a lot in the same tract therefore carry byte-identical
    values, which is the property that makes the street frame an extension of
    this table rather than a second table wearing its name.

    `report`, if given, is filled in place with the street-frame diagnostics
    (`no_tract`, `boundary_ties`, the vintage guards' findings).
    """
    acs = fetch_acs(year)
    _cross_check_b25044_vs_b25003(acs, year)
    _cross_check_b01001_vs_b01003(acs, year)

    tract_map = load_bbl_tract_map(pluto_csv)
    # The LOT rule, unchanged (D56): this frame's grain is the tax lot and each
    # value is the lot's OWN tract, found by a BBL lookup against PLUTO's
    # DCP-computed `bct2020`. A row with no BBL cannot be assigned this way --
    # merging on a blank key would either drop it silently or match some other
    # blank-BBL lot -- so it is excluded HERE, explicitly, and picked up by the
    # street branch below if the caller supplied one.
    frame = addresses_df[["address_id", "bbl"]].copy()
    # Object dtype, not StringDtype: `tract_map.bbl` is object and pandas
    # refuses to merge the two.
    bbl_str = frame["bbl"].fillna("").astype(str).str.strip()
    keep = bbl_str != ""
    if not keep.all():
        import warnings
        warnings.warn(
            f"address_demographics: {int((~keep).sum()):,} rows of the LOT frame "
            f"have no BBL and cannot take a bct2020 lookup. Street-frame points "
            f"belong in `street_df`, not here (D56/D84/owner ruling 4).")
    merged = frame[keep].merge(tract_map, on="bbl", how="left")
    merged["bbl"] = merged["bbl"].astype(object)

    rep = report if report is not None else {}
    rep["lot_rows"] = int(len(merged))
    rep["lot_no_tract"] = int(merged["tract_geoid"].isna().sum())

    # ---- the STREET frame (owner ruling 4, 2026-09-16) ---------------------
    # Assigned by an actual point-in-polygon against the tract vintage the ACS
    # year is published on. Every street point comes back, including the ones
    # no polygon contains: they get an EXPLICIT NULL tract and NULL measures,
    # never an absent row.
    if street_df is not None and len(street_df):
        assigned, street_rep = assign_tracts_by_point(
            street_df, set(acs), year, polygons=polygons)
        rep["street"] = street_rep
        street_rows = pd.DataFrame({
            "address_id": assigned["address_id"].to_numpy(),
            "bbl": pd.Series([None] * len(assigned), dtype=object),
            "tract_geoid": assigned["tract_geoid"].to_numpy(),
        })
        merged = pd.concat([merged, street_rows], ignore_index=True)
    elif street_df is not None:
        rep["street"] = {"points": 0, "assigned": 0, "no_tract": 0, "boundary_ties": 0}

    dup = merged["address_id"].duplicated()
    if dup.any():
        raise RuntimeError(
            f"{int(dup.sum()):,} duplicate address_id rows across the lot and "
            f"street frames -- (address_id, acs_year) is this table's key and a "
            f"duplicate would fan out every join to it. The frames are supposed "
            f"to be disjoint by construction (a street point has no BBL).")

    # Compute each distinct tract's stats once, not once per address --
    # NYC has ~767k addresses over ~2,300 tracts. Shared by BOTH frames.
    stats_by_tract = {
        geoid: _tract_row_stats(acs[geoid])
        for geoid in merged["tract_geoid"].dropna().unique()
        if geoid in acs
    }
    stats_df = pd.DataFrame.from_dict(stats_by_tract, orient="index")
    stats_df.index.name = "tract_geoid"
    stats_df = stats_df.reset_index()

    out = merged.merge(stats_df, on="tract_geoid", how="left")
    out["acs_year"] = year
    rep["rows"] = int(len(out))
    return out[ADDRESS_DEMOGRAPHICS_COLUMNS]


def prune_out_of_scope(con) -> int:
    """Delete every analysis.address_demographics row whose `address_id` is
    absent from analysis.address, and report how many were removed. Idempotent:
    a second call removes 0.

    WHY (audit finding 15, 2026-09-16). This table is built from the raw
    5-borough PLUTO extract while `analysis.address` was clipped to MN+BK by
    D78's own `model/address_gaps.prune_out_of_scope`. 485,495 of its 767,337
    rows -- 63% -- described addresses that are not in the universe. Nothing
    surfaced it, because every read joins FROM `analysis.address`: the orphans
    are invisible to queries and visible only in the row count, which is exactly
    the kind of number that gets quoted as coverage.

    Same shape as `model/address_gaps.prune_out_of_scope`, with one difference
    that matters: that one takes the borough scope as an argument, because it
    owns the universe. This one does not take a scope at all -- the universe IS
    `analysis.address`, and taking a second, independent scope here is how the
    two would drift apart again.

    FAILS LOUD ON AN EMPTY UNIVERSE. If `analysis.address` has never been built,
    every row here is technically an orphan and an unguarded DELETE would empty
    the table and report success. That is the silent-zero failure this project
    refuses; it raises instead.
    """
    n_universe = con.execute("SELECT count(*) FROM analysis.address").fetchone()[0]
    if n_universe == 0:
        raise RuntimeError(
            "analysis.address is EMPTY, so every analysis.address_demographics "
            "row looks like an orphan and this prune would delete all of them "
            "while reporting success. Run `loci address-gaps` first; refusing to "
            "empty the table on the strength of a missing universe.")
    n = con.execute(
        "SELECT count(*) FROM analysis.address_demographics d WHERE NOT EXISTS "
        "(SELECT 1 FROM analysis.address a WHERE a.address_id = d.address_id)"
    ).fetchone()[0]
    if n:
        con.execute(
            "DELETE FROM analysis.address_demographics WHERE NOT EXISTS "
            "(SELECT 1 FROM analysis.address a "
            "  WHERE a.address_id = analysis.address_demographics.address_id)")
    return int(n)


def write_address_demographics(con, df: pd.DataFrame, year: int = ACS_YEAR,
                               prune: bool = True) -> int:
    """DELETE this ACS vintage, INSERT `df`, then clip to `analysis.address`.

    Returns the number of rows LEFT IN THE TABLE for this vintage, not the
    length of `df`: after the prune those differ by exactly the orphan count,
    and returning `len(df)` would report a coverage number the table does not
    hold. `prune=False` exists for the round-trip tests that build a frame with
    no `analysis.address` behind it.
    """
    con.execute("DELETE FROM analysis.address_demographics WHERE acs_year = ?", [year])
    con.register("_addr_demo", df)
    cols = ", ".join(ADDRESS_DEMOGRAPHICS_COLUMNS)
    try:
        con.execute(
            f"INSERT INTO analysis.address_demographics ({cols}) "
            f"SELECT {cols} FROM _addr_demo")
    finally:
        con.unregister("_addr_demo")
    if prune:
        prune_out_of_scope(con)
    return int(con.execute(
        "SELECT count(*) FROM analysis.address_demographics WHERE acs_year = ?",
        [year]).fetchone()[0])


def summarize(df: pd.DataFrame, addresses_df: pd.DataFrame,
              income_threshold: float | None = None) -> dict:
    """Sanity numbers for the CLI report. `addresses_df` must carry `borough`
    (added by the caller from sources/cities/nyc/addresses.BOROCODE loop),
    joined on address_id, so the MN/BK-vs-citywide comparison uses the same
    universe the table was built from."""
    merged = df.merge(addresses_df[["address_id", "borough"]].drop_duplicates("address_id"),
                       on="address_id", how="left")
    n = len(merged)
    n_tract = merged["tract_geoid"].notna().sum()
    # `bbl` IS the provenance marker: non-NULL = PLUTO bct2020 lookup (lot
    # frame), NULL = point-in-polygon (street frame). See build_address_demographics.
    is_street = merged["bbl"].isna() | (merged["bbl"].astype(str).str.strip() == "")

    mnbk = merged[merged["borough"].isin(["MN", "BK"])]
    out = {
        "n_addresses": n,
        "n_with_tract": int(n_tract),
        "tract_assignment_rate": n_tract / n if n else 0.0,
        "n_lot_frame": int((~is_street).sum()),
        "n_street_frame": int(is_street.sum()),
        "street_with_tract": int(merged.loc[is_street, "tract_geoid"].notna().sum()),
        "street_tract_assignment_rate": (
            float(merged.loc[is_street, "tract_geoid"].notna().mean())
            if is_street.any() else None),
        "citywide_median_income": merged["median_hh_income"].median(),
        "mnbk_median_income": mnbk["median_hh_income"].median(),
        "citywide_median_zero_vehicle_hh_share": merged["zero_vehicle_hh_share"].median(),
        "mnbk_median_zero_vehicle_hh_share": mnbk["zero_vehicle_hh_share"].median(),
    }

    inc = merged["median_hh_income"]
    moe = merged["median_hh_income_moe"]
    valid = inc.notna() & moe.notna() & (inc != 0)
    out["median_income_moe_share"] = (moe[valid] / inc[valid]).median() if valid.any() else None

    if income_threshold is not None:
        within = valid & ((inc - income_threshold).abs() <= moe)
        out["income_threshold"] = income_threshold
        out["share_within_one_moe_of_threshold"] = within[valid].mean() if valid.any() else None

    return out
