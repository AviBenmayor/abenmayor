"""Commercial LEGALITY at address grain (D82, seed 2026-09-14, deliverable 1).

WHAT IS PINNED, AND WHY:

  1. THE THREE-BRANCH RULE, exactly as the seed states it -- ineligible only
     when a zoning/landuse/ownertype test fires AND no open commercial POI is
     at the address; grandfathered is the NARROWER R-no-overlay-only case
     with an open POI; everything else is commercial (AC-2, AC-3).
  2. HISTDIST / LANDMARK NEVER MOVE THE VERDICT (AC-7, D82) -- they are card
     labels only.
  3. THE REAL BBLS from the seed's own dig (AC-4), skipped when the warehouse
     is absent so a fresh clone / CI does not fail on missing data.
  4. sql/031's committed view text matches the generator (drift test, same
     idiom as tests/test_poi_colocation.py::test_sql_file_matches_generator).
"""
from __future__ import annotations

import datetime as dt
import pathlib

import pandas as pd
import pytest

from loci import db as locidb
from loci.model import address_legality as al

MIGRATION = pathlib.Path(locidb.SQL_DIR) / "031_address_legality.sql"

#: NOT NULL columns on analysis.address (sql/002), plus the ten this module
#: adds. A minimal, explicit insert list -- no reliance on column order.
REQUIRED_COLS = ("address_id", "lon", "lat", "borough", "present_count",
                 "eligible", "n_missing", "reach_source", "reach_hash",
                 "graph_version", "run_at")
LEGALITY_INPUT_COLS = ("bbl", "zonedist1", "overlay1", "overlay2", "landuse",
                       "ownertype", "histdist", "landmark", "retailarea",
                       "bldgclass", "has_open_commercial_poi", "legality",
                       "legality_basis")
ALL_COLS = REQUIRED_COLS + LEGALITY_INPUT_COLS


@pytest.fixture()
def warehouse():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _row(address_id, *, bbl=None, zonedist1=None, overlay1=None, overlay2=None,
         landuse=None, ownertype=None, histdist=None, landmark=None,
         retailarea=None, bldgclass=None,
         has_open_commercial_poi=False, lon=-73.98, lat=40.75, borough="MN"):
    return {
        "address_id": address_id, "lon": lon, "lat": lat, "borough": borough,
        "present_count": 0, "eligible": True, "n_missing": 0,
        "reach_source": "tiers", "reach_hash": "t", "graph_version": "g",
        "run_at": dt.datetime(2026, 9, 14),
        "bbl": bbl, "zonedist1": zonedist1, "overlay1": overlay1,
        "overlay2": overlay2, "landuse": landuse, "ownertype": ownertype,
        "histdist": histdist, "landmark": landmark,
        "retailarea": retailarea, "bldgclass": bldgclass,
        "has_open_commercial_poi": has_open_commercial_poi,
        "legality": None, "legality_basis": None,
    }


def _insert(con, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)[list(ALL_COLS)]
    con.register("_rows", frame)
    con.execute(f"INSERT INTO analysis.address ({', '.join(ALL_COLS)}) "
                f"SELECT {', '.join(ALL_COLS)} FROM _rows")
    con.unregister("_rows")


def _legality(con, rows: list[dict]) -> pd.DataFrame:
    """Insert `rows` and return (address_id, legality, legality_basis) using
    `legality_case_sql()` directly -- the SAME expression `build_legality_columns`
    UPDATEs with, exercised here as a plain SELECT so the branch logic is
    tested with no spatial join and no PLUTO CSV at all."""
    _insert(con, rows)
    legality, basis = al.legality_case_sql("a")
    ids = [r["address_id"] for r in rows]
    holes = ", ".join("?" for _ in ids)
    return con.execute(
        f"SELECT a.address_id, {legality} AS legality, {basis} AS legality_basis "
        f"FROM analysis.address a WHERE a.address_id IN ({holes}) "
        f"ORDER BY a.address_id", ids).fetchdf()


# ============================================================ 1. the branches

def test_r_no_overlay_no_open_poi_is_ineligible(warehouse):
    out = _legality(warehouse, [_row("a", zonedist1="R6", has_open_commercial_poi=False)])
    assert out.loc[0, "legality"] == "ineligible"
    assert "no grandfathering evidence" in out.loc[0, "legality_basis"]


def test_r_no_overlay_WITH_open_poi_is_grandfathered(warehouse):
    """AC-3: the pinned fixture -- an R-zoned, no-overlay address with an open
    commercial POI is 'grandfathered' and eligible, not 'ineligible'."""
    out = _legality(warehouse, [_row("a", zonedist1="R6", has_open_commercial_poi=True)])
    assert out.loc[0, "legality"] == "grandfathered"
    assert "grandfathered" in out.loc[0, "legality_basis"]
    assert "non-closed" in out.loc[0, "legality_basis"]


# ------------------------------------------ D97 item 3: grandfathering evidence

def test_retailarea_evidence_alone_grandfathers_with_no_poi_at_all(warehouse):
    """41/31 Carmine St's shape: R6, no overlay, a PLUTO retailarea figure on
    the lot, and NO commercial POI evidence at all -- PLUTO's own retail
    record is sufficient on its own (D97 item 3)."""
    out = _legality(warehouse, [_row("a", zonedist1="R6", retailarea="9375",
                                     bldgclass="C7", has_open_commercial_poi=False)])
    assert out.loc[0, "legality"] == "grandfathered"
    assert "retail evidence" in out.loc[0, "legality_basis"]


def test_bldgclass_k_prefix_alone_grandfathers(warehouse):
    """156 Henry St's shape: bldgclass K4 (store building) is sufficient
    retail evidence even with retailarea unset/zero."""
    out = _legality(warehouse, [_row("a", zonedist1="R7-1", retailarea="0",
                                     bldgclass="K4")])
    assert out.loc[0, "legality"] == "grandfathered"


def test_bldgclass_s_prefix_alone_grandfathers(warehouse):
    out = _legality(warehouse, [_row("a", zonedist1="R6", retailarea=None,
                                     bldgclass="S1")])
    assert out.loc[0, "legality"] == "grandfathered"


def test_bldgclass_that_is_not_k_or_s_is_not_evidence(warehouse):
    out = _legality(warehouse, [_row("a", zonedist1="R6", retailarea="0",
                                     bldgclass="C1")])
    assert out.loc[0, "legality"] == "ineligible"


def test_zero_retailarea_is_not_evidence_on_its_own(warehouse):
    """21 Washington Square North's shape: retailarea 0, bldgclass C1 (not
    K/S), no POI evidence -- still 'ineligible', the AC-4 pinned answer."""
    out = _legality(warehouse, [_row("a", zonedist1="R6", retailarea="0",
                                     bldgclass="C1", has_open_commercial_poi=False)])
    assert out.loc[0, "legality"] == "ineligible"


def test_malformed_retailarea_fails_open_to_no_evidence_not_an_error(warehouse):
    """TRY_CAST, not CAST: a garbage retailarea value must read as "no
    evidence", never raise and abort the UPDATE."""
    out = _legality(warehouse, [_row("a", zonedist1="R6", retailarea="not a number",
                                     bldgclass="C1")])
    assert out.loc[0, "legality"] == "ineligible"


def test_r_with_c1_overlay_is_commercial(warehouse):
    """The C1/C2 overlay is the escape hatch from the R branch entirely --
    zoned residential but with a mapped commercial overlay, so neither
    ineligible nor grandfathered applies."""
    out = _legality(warehouse, [_row("a", zonedist1="R6", overlay1="C1-4")])
    assert out.loc[0, "legality"] == "commercial"


def test_c_district_is_commercial(warehouse):
    """4 East 8th Street's zoning shape: C1-7, no R prefix at all."""
    out = _legality(warehouse, [_row("a", zonedist1="C1-7")])
    assert out.loc[0, "legality"] == "commercial"


def test_park_landuse_no_open_poi_is_ineligible(warehouse):
    """Isolated from BOTH the R-no-overlay branch and the commercial-zoning
    branch (D97 item 4): a manufacturing-district zonedist1 (neither R- nor
    C-prefixed, no overlay) so only the landuse=09 test can fire."""
    out = _legality(warehouse, [_row("a", zonedist1="M1-2", landuse="09",
                                     has_open_commercial_poi=False)])
    assert out.loc[0, "legality"] == "ineligible"
    assert "open space" in out.loc[0, "legality_basis"]


def test_commercial_zoning_beats_park_landuse(warehouse):
    """D97 item 4: commercial zoning is decided FIRST and unconditionally --
    a park-coded lot that is ALSO zoned C reads 'commercial', not
    'ineligible'. Contrast the isolated test above (non-commercial zoning)."""
    out = _legality(warehouse, [_row("a", zonedist1="C4-2", landuse="09",
                                     has_open_commercial_poi=False)])
    assert out.loc[0, "legality"] == "commercial"


def test_park_landuse_can_also_stack_with_r_no_overlay(warehouse):
    """A real park lot is often ALSO zoned R (no separate park district) --
    the R-no-overlay branch's basis text wins by CASE priority, and the
    outcome is 'ineligible' either way."""
    out = _legality(warehouse, [_row("a", zonedist1="R6", landuse="09",
                                     has_open_commercial_poi=False)])
    assert out.loc[0, "legality"] == "ineligible"


def test_parking_landuse_10_does_NOT_trigger_ineligible(warehouse):
    """Seed's own note: only landuse 09 (open space), never 10 (parking)."""
    out = _legality(warehouse, [_row("a", zonedist1="R6", overlay1="C1-4",
                                     landuse="10")])
    assert out.loc[0, "legality"] == "commercial"


def test_institutional_ownertype_no_open_poi_is_ineligible(warehouse):
    """51 Washington Square South's shape: R7-2, ownertype X, no overlay --
    both the R-no-overlay branch AND the ownertype branch fire; either alone
    is sufficient for 'ineligible'."""
    out = _legality(warehouse, [_row("a", zonedist1="R7-2", ownertype="X")])
    assert out.loc[0, "legality"] == "ineligible"


def test_ownertype_x_lot_in_c4_is_commercial_not_ineligible(warehouse):
    """D97 item 4, the contrarian's explicit test case: commercial zoning is
    decided FIRST and unconditionally, so a city-owned/institutional lot
    (ownertype X) that is ALSO zoned C4 reads 'commercial' -- institutional
    ownertype can only make an address ineligible when the lot is NOT
    commercially zoned (contrast 51 Washington Square South, R7-2 with no
    overlay, below)."""
    out = _legality(warehouse, [_row("a", zonedist1="C4-2", ownertype="X")])
    assert out.loc[0, "legality"] == "commercial"


def test_ownertype_alone_in_a_commercially_zoned_lot_is_commercial(warehouse):
    """Same point with a different institutional code: ownertype 'C' (city
    ownership) in a C4 district is 'commercial', not 'ineligible' -- the
    PRE-D97 behaviour of this exact fixture."""
    out = _legality(warehouse, [_row("a", zonedist1="C4-2", ownertype="C")])
    assert out.loc[0, "legality"] == "commercial"


def test_institutional_ownertype_alone_in_a_noncommercial_zone_is_ineligible(warehouse):
    """Isolates the ownertype branch from BOTH the R-no-overlay branch and
    the commercial-zoning branch: a manufacturing-district lot (neither R-
    nor C-prefixed) that is nonetheless city-owned."""
    out = _legality(warehouse, [_row("a", zonedist1="M1-1", ownertype="C")])
    assert out.loc[0, "legality"] == "ineligible"
    assert "ownertype" in out.loc[0, "legality_basis"]


@pytest.mark.parametrize("code", ["C", "O", "P", "X"])
def test_every_institutional_ownertype_code_is_covered(warehouse, code):
    """M1-1 (not R-, not C-prefixed) isolates the ownertype branch -- see
    D97 item 4: a C4-zoned fixture here would always read 'commercial'
    regardless of ownertype, exercising nothing."""
    out = _legality(warehouse, [_row("a", zonedist1="M1-1", ownertype=code)])
    assert out.loc[0, "legality"] == "ineligible"


def test_private_ownertype_does_not_trigger_ineligible(warehouse):
    out = _legality(warehouse, [_row("a", zonedist1="M1-1", ownertype="")])
    assert out.loc[0, "legality"] == "commercial"


def test_park_or_institutional_WITH_open_poi_falls_to_commercial_not_grandfathered(warehouse):
    """Seed's exact wording only grants 'grandfathered' to the R-no-overlay
    case. A park lot or institutional campus with grandfathering evidence on
    it (a concession stand, a hospital gift shop) is not that -- it reads
    'commercial', the honest "a real business record exists here" answer.
    M1-1 (not R-, not C-prefixed) isolates this from the commercial-zoning
    branch (D97 item 4)."""
    out = _legality(warehouse, [
        _row("park", zonedist1="M1-1", landuse="09", has_open_commercial_poi=True),
        _row("inst", zonedist1="M1-1", ownertype="X", has_open_commercial_poi=True),
    ])
    assert list(out["legality"]) == ["commercial", "commercial"]


def test_r_no_overlay_open_poi_beats_park_and_institutional_priority(warehouse):
    """When a lot is BOTH R-no-overlay AND park/institutional, the
    grandfathered branch (checked first in legality_case_sql) wins once an
    open POI is present -- the R-no-overlay test is the sole gate on
    'grandfathered', and it does not matter what else about the lot is also
    true."""
    out = _legality(warehouse, [_row("a", zonedist1="R6", landuse="09",
                                     has_open_commercial_poi=True)])
    assert out.loc[0, "legality"] == "grandfathered"


def test_no_pluto_record_is_unknown_not_dropped(warehouse):
    """D75/D97 item 5: nothing leaves the universe, but a street-frame point
    with no BBL match is not silently defaulted to 'commercial' either -- it
    gets the fourth verdict, 'unknown', and the basis says exactly why. AC-6
    and the map export must never exclude or grey an 'unknown' address the
    way they do 'ineligible' ones (see tests/test_recommendation_legality.py
    and cli.py's export for that half of the contract)."""
    out = _legality(warehouse, [_row("a", zonedist1=None)])
    assert out.loc[0, "legality"] == "unknown"
    assert out.loc[0, "legality_basis"] == "no PLUTO lot"


def test_legality_is_always_one_of_the_four_values(warehouse):
    assert set(al.LEGALITY_VALUES) == {"commercial", "grandfathered", "ineligible", "unknown"}


# ==================================================== 2. AC-7: no character leak

def test_histdist_and_landmark_never_move_the_verdict(warehouse):
    """AC-7 / D82: toggling histdist and landmark on an otherwise-identical
    row must not change legality OR legality_basis -- they are card labels
    (fit-out cost warnings) only. Exercised on THREE zoning shapes (bare R,
    park, institutional) since a bug that only skipped one CASE branch would
    hide behind a single-shape test."""
    base = dict(zonedist1="R6")
    park = dict(zonedist1="R6", landuse="09")
    inst = dict(zonedist1="M1-1", ownertype="X")
    commercial = dict(zonedist1="C4-2")
    for shape in (base, park, inst, commercial):
        plain = _row("plain", **shape, histdist=None, landmark=None)
        labeled = _row("labeled", **shape,
                       histdist="Greenwich Village Historic District",
                       landmark="INDIVIDUAL LANDMARK")
        out = _legality(warehouse, [plain, labeled])
        row_plain = out.set_index("address_id").loc["plain"]
        row_labeled = out.set_index("address_id").loc["labeled"]
        assert row_plain["legality"] == row_labeled["legality"]
        assert row_plain["legality_basis"] == row_labeled["legality_basis"]
        warehouse.execute("DELETE FROM analysis.address")


def test_histdist_and_landmark_are_not_read_by_any_predicate_sql():
    """Stronger than the behavioural test above: the generated SQL text for
    every branch of the rule must not mention histdist or landmark at all."""
    legality, basis = al.legality_case_sql("a")
    for expr in (al.zoning_ineligible_sql("a"), al.r_no_overlay_sql("a"),
                al.park_landuse_sql("a"), al.institutional_owner_sql("a"),
                al.commercially_zoned_sql("a"), al.retail_evidence_sql("a"),
                al.grandfathering_evidence_sql("a"), legality, basis):
        assert "histdist" not in expr.lower()
        assert "landmark" not in expr.lower()


# =============================================== 3. "at the address" matching

def _mem_spatial_con():
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


def test_open_poi_match_finds_a_poi_inside_the_radius_and_not_outside_it():
    """A synthetic address + two synthetic POIs (bypassing the real
    analysis.poi_supply_status view entirely): one 10 m away (inside
    POI_MATCH_RADIUS_M), one ~40 m away (outside). Only the near one should
    match, and only when it is 'open' and in a commercial category."""
    con = _mem_spatial_con()
    con.execute("""
        CREATE TABLE addr (address_id VARCHAR, lon DOUBLE, lat DOUBLE)
    """)
    con.execute("INSERT INTO addr VALUES ('a', -73.98000, 40.75000)")
    con.execute("""
        CREATE TABLE poi (poi_id VARCHAR, category VARCHAR, poi_status VARCHAR,
                          geom GEOMETRY)
    """)
    # ~10 m north: 1e-4 deg lat is about 11 m.
    con.execute("""
        INSERT INTO poi VALUES
            ('near_open',  'grocery', 'open',   ST_Point(-73.98000, 40.75010)),
            ('near_closed','grocery', 'closed', ST_Point(-73.98000, 40.75010)),
            ('far_open',   'grocery', 'open',   ST_Point(-73.98000, 40.75040))
    """)
    sql = al.open_poi_match_sql(address_table="addr", poi_view="poi")
    matched = {r[0] for r in con.execute(sql).fetchall()}
    assert matched == {"a"}, (
        "expected the near OPEN grocery to match and the closed one / the "
        "far one not to")


def test_open_poi_match_includes_unknown_status_not_just_open():
    """D97 item 3: the match test is now `poi_status <> 'closed'`, not
    `= 'open'` -- an 'unknown'-status POI (never resolved either way) must
    still count as grandfathering evidence (D79: uncertainty is never
    evidence of closure), while a 'closed' one at the SAME distance must
    not."""
    con = _mem_spatial_con()
    con.execute("CREATE TABLE addr (address_id VARCHAR, lon DOUBLE, lat DOUBLE)")
    con.execute("INSERT INTO addr VALUES ('a', -73.98000, 40.75000)")
    con.execute("""
        CREATE TABLE poi (poi_id VARCHAR, category VARCHAR, poi_status VARCHAR,
                          geom GEOMETRY)
    """)
    con.execute("""
        INSERT INTO poi VALUES
            ('near_unknown', 'grocery', 'unknown', ST_Point(-73.98000, 40.75010)),
            ('near_closed',  'grocery', 'closed',  ST_Point(-73.98000, 40.75010))
    """)
    sql = al.open_poi_match_sql(address_table="addr", poi_view="poi")
    matched = {r[0] for r in con.execute(sql).fetchall()}
    assert matched == {"a"}


def test_pad_lon_uses_cos_latitude_and_catches_an_18m_east_poi():
    """D97 item 2: at 40.72N the OLD fixed-latitude-rate pad covered only
    ~15.1 m east-west for a nominal 20 m radius -- a true match up to ~4.9 m
    further east would be dropped by the bounding-box pre-filter before the
    real haversine test ever ran. This POI sits a VERIFIED ~18 m due east
    (0.0002144 deg of longitude at this latitude, computed with the same
    cos(latitude) correction the fix applies), inside POI_MATCH_RADIUS_M but
    outside the old, too-narrow pre-filter box."""
    import math

    con = _mem_spatial_con()
    lat = 40.72
    lon0 = -73.98000
    # 18 m due east at this latitude: delta_lon = 18 / (111320 * cos(lat)).
    delta_lon = 18.0 / (111_320.0 * math.cos(math.radians(lat)))
    lon_east = lon0 + delta_lon
    con.execute("CREATE TABLE addr (address_id VARCHAR, lon DOUBLE, lat DOUBLE)")
    con.execute("INSERT INTO addr VALUES ('a', ?, ?)", [lon0, lat])
    con.execute("""
        CREATE TABLE poi (poi_id VARCHAR, category VARCHAR, poi_status VARCHAR,
                          geom GEOMETRY)
    """)
    con.execute("INSERT INTO poi VALUES ('east_poi', 'grocery', 'open', "
                "ST_Point(?, ?))", [lon_east, lat])
    sql = al.open_poi_match_sql(address_table="addr", poi_view="poi")
    matched = {r[0] for r in con.execute(sql).fetchall()}
    assert matched == {"a"}, (
        "an ~18 m due-east POI must match a 20 m radius -- the OLD "
        "fixed-latitude-rate pre-filter pad (~15.1 m east-west coverage at "
        "this latitude) would have dropped it before the real distance "
        "test ever ran")


def _grid_fixture_con():
    """An address and a POI table laid out around ONE grid cell edge, with
    every case that can distinguish the bucketed join from the reference one.

    The cell edge is at `lon = -73.980` exactly (a multiple of
    `POI_GRID_DEG`), so `floor(lon / POI_GRID_DEG)` changes value there. Each
    address sits a hair to one side of it and each POI a hair to the other,
    which is the only arrangement in which a 3x3 neighbourhood that was one
    cell too small would silently lose a row."""
    import math

    con = _mem_spatial_con()
    edge_lon, lat = -73.980, 40.72
    # metres -> degrees at this latitude, the same two rates the pre-filter uses
    def dlat(m):
        return m / al.METRES_PER_DEGREE

    def dlon(m):
        return m / (al.METRES_PER_DEGREE * math.cos(math.radians(lat)))

    r = al.POI_MATCH_RADIUS_M

    con.execute("CREATE TABLE addr (address_id VARCHAR, lon DOUBLE, lat DOUBLE)")
    con.executemany("INSERT INTO addr VALUES (?, ?, ?)", [
        # west of the edge, POIs east of it -> match must cross the cell edge
        ("west_near",    edge_lon - dlon(2.0),  lat),
        ("west_far",     edge_lon - dlon(30.0), lat),
        # east of the edge, a POI west of it
        ("east_near",    edge_lon + dlon(2.0),  lat),
        # exactly ON the edge (floor() sends it to the eastern cell)
        ("on_edge",      edge_lon,              lat),
        # a north-south edge case too: lat edge at 40.720 exactly
        ("lat_edge",     -73.9855,              40.720),
        # duplicate coordinates: two address ids at one point
        ("dup_a",        -73.9705,              lat),
        ("dup_b",        -73.9705,              lat),
        # nothing anywhere near it
        ("isolated",     -73.9500,              lat),
        # NULL coordinates must match nothing and must not raise
        ("null_coords",  None,                  None),
    ])

    con.execute("CREATE TABLE poi (poi_id VARCHAR, category VARCHAR, "
                "poi_status VARCHAR, geom GEOMETRY)")
    con.executemany(
        "INSERT INTO poi VALUES (?, ?, ?, ST_Point(?, ?))", [
            # 4 m east of the edge: inside 20 m of west_near, across the cell edge
            ("across_edge",   "grocery", "open",    edge_lon + dlon(4.0), lat),
            # 1 m west of the edge: catches east_near and on_edge
            ("just_west",     "grocery", "unknown", edge_lon - dlon(1.0), lat),
            # EXACTLY at the radius from west_far (30 m west of it): the
            # floating-point boundary of `<= radius_m`
            ("exactly_at_r",  "grocery", "open",
             edge_lon - dlon(30.0) - dlon(r), lat),
            # duplicate POI coordinates, both on the duplicate addresses
            ("dup_poi_1",     "grocery", "open",    -73.9705, lat),
            ("dup_poi_2",     "bar",     "unknown", -73.9705, lat),
            # a closed POI on top of the isolated address -- excluded by status
            ("closed_on_iso", "grocery", "closed",  -73.9500, lat),
            # 3 m north of the lat cell edge, address is ON the edge
            ("across_lat_edge", "grocery", "open",  -73.9855, 40.720 + dlat(3.0)),
            # far enough away to be in the 3x3 neighbourhood but outside 20 m
            ("neighbour_cell", "grocery", "open",   edge_lon + dlon(60.0), lat),
        ])
    return con


def test_bucketed_match_agrees_with_the_reference_on_boundary_cases():
    """GTM-169: `open_poi_match_sql` gained a grid-bucket equi-join so DuckDB
    stops planning a nested loop (6.8e10 pair evaluations, ~2,000 s). The
    bucket may only change WHICH PAIRS the exact test sees, never the
    answer -- so the fast query is pinned row-for-row against
    `open_poi_match_reference_sql`, the pre-change form, on a fixture built
    entirely out of the cases a too-small neighbourhood would break: POIs
    just across a cell edge (east-west AND north-south), an address exactly
    on an edge, a POI exactly at the radius, duplicate coordinates on both
    sides, and NULL coordinates."""
    con = _grid_fixture_con()
    fast = sorted(r[0] for r in con.execute(al.open_poi_match_sql(
        address_table="addr", poi_view="poi")).fetchall())
    ref = sorted(r[0] for r in con.execute(al.open_poi_match_reference_sql(
        address_table="addr", poi_view="poi")).fetchall())
    assert fast == ref, (
        "the bucketed join returned a different row set than the reference "
        f"bounding-box join: fast={fast} reference={ref}")
    # Guard the guard: a fixture that matched nothing, or everything, would
    # pass the comparison above while testing nothing at all.
    assert "west_near" in fast, "the across-the-cell-edge match was lost"
    assert "east_near" in fast and "on_edge" in fast
    assert "lat_edge" in fast, "the across-the-LATITUDE-edge match was lost"
    assert {"dup_a", "dup_b"} <= set(fast)
    assert "isolated" not in fast, "a 'closed' POI must not match"
    assert "null_coords" not in fast


def test_bucketed_match_returns_one_row_per_address_despite_the_3x3_fanout():
    """The POI side is fanned out to nine cells. If the GROUP BY were ever
    dropped, an address near several POIs would come back up to nine times
    per POI and `build_legality_columns`' UPDATE ... FROM would silently do
    nine times the work -- the same duplicate-fanout class of bug that
    edge-mirroring caused elsewhere in this project."""
    con = _grid_fixture_con()
    rows = [r[0] for r in con.execute(al.open_poi_match_sql(
        address_table="addr", poi_view="poi")).fetchall()]
    assert len(rows) == len(set(rows)), f"duplicate address_ids: {rows}"


def test_grid_cell_is_wider_than_the_prefilter_pad_at_nyc_latitudes():
    """The ONE correctness invariant of the bucket (see `POI_GRID_DEG`): a
    cell must be at least as wide as the pad, or the 3x3 neighbourhood stops
    being a superset of the bounding box. Checked at the widest latitude in
    the five boroughs (Wakefield, ~40.92N) and well past it."""
    for lat in (40.4, 40.72, 40.92, 45.0):
        al.assert_grid_covers_pad(lat)          # must not raise
        assert al.pad_lon_deg(lat) < al.POI_GRID_DEG
        assert al.pad_lat_deg() < al.POI_GRID_DEG


def test_grid_guard_raises_rather_than_silently_narrowing_the_join():
    """Fail loud, not quiet: a radius (or a latitude) that outgrows the cell
    must stop the build, because the failure mode is dropped grandfathering
    evidence -- an address quietly labelled 'ineligible'. D97 item 2 is the
    precedent for taking a silently-narrowed spatial pre-filter seriously."""
    with pytest.raises(ValueError, match="POI_GRID_DEG"):
        al.assert_grid_covers_pad(40.72, radius_m=500.0)
    with pytest.raises(ValueError, match="POI_GRID_DEG"):
        al.assert_grid_covers_pad(89.9)


def test_poi_cte_stays_materialized():
    """Not cosmetic: without the hint DuckDB inlines the CTE into each arm of
    the 3x3 fan-out and re-evaluates the four-CTE `poi_supply_status` view
    nine times -- measured at 561 s on a 50k-address sample against 296 s for
    the nested loop it replaced, and 0.9 s with the hint."""
    assert "AS MATERIALIZED" in al.open_poi_match_sql()


def test_poi_match_radius_is_a_same_building_distance_not_a_block():
    """Documents the empirical choice (see module docstring): wide enough to
    absorb a PLUTO-vs-POI geocode offset, narrow enough it is not a walkshed."""
    assert 10.0 <= al.POI_MATCH_RADIUS_M <= 30.0


def test_commercial_poi_categories_is_the_full_retail_registry():
    """Documents the decision the seed left open: every one of the 17
    registered categories is retail/food/personal-service, so all 17 count as
    a 'commercial POI'. A future NON-retail category added to the registry
    would silently start granting 'grandfathered' unless this test is
    updated alongside it -- which is the point of pinning it. 16th, 2026-09-17:
    bathhouse_sauna (NAICS 812199, a personal-care service premises) IS a
    commercial use, so it joins the set. 17th, 2026-09-22 (D137): brewery
    (NAICS 312120, a production/retail premises) IS a commercial use too."""
    from loci.categories import CATEGORIES

    assert al.commercial_poi_categories() == frozenset(CATEGORIES)
    assert len(al.commercial_poi_categories()) == 17


# ===================================================== 4. generated-SQL parity

def test_sql_file_matches_generator():
    """sql/031_address_legality.sql's view is GENERATED from
    passthrough_view_sql(). A hand edit there would give
    analysis.address_legality a second definition."""
    text = MIGRATION.read_text()
    assert al.passthrough_view_sql().strip() in text, (
        "sql/031_address_legality.sql is stale -- regenerate the view section "
        "from loci.model.address_legality.passthrough_view_sql()")
    lines = text.splitlines()
    for col in al.PLUTO_LEGALITY_COLUMNS:
        assert any(f"ADD COLUMN IF NOT EXISTS {col}" in ln and "VARCHAR" in ln
                  for ln in lines), f"sql/031 is missing the {col} ALTER"
    for col in ("has_open_commercial_poi", "legality", "legality_basis",
               "legality_run_at"):
        assert col in text


# ================================================ 5. AC-4: real-warehouse BBLs

#: (bbl, address, expected legality). From the seed's own earlier dig,
#: verified against data/raw/pluto.csv 2026-09-14. MacDougal Alley's carriage
#: houses are NOT resolvable in this PLUTO vintage's `address` field at all
#: (no row matches "MACDOUGAL ALLEY"), so a second Washington Square North
#: rowhouse stands in for it -- both are the same zoning shape the seed cites
#: (R6, no overlay).
REAL_BBLS = [
    ("1005510010", "21 Washington Square N (R6, no overlay)", "ineligible"),
    ("1005510015", "26 Washington Square N (R6, no overlay)", "ineligible"),
    ("1005500023", "4 East 8th Street (C1-7)", "commercial"),
    ("1005410018", "51 Washington Square S (NYU, ownertype X)", "ineligible"),
    # A REAL legal non-conforming café on an R6, no-overlay block, found by
    # querying the warehouse for open DOHMH restaurants whose address row is
    # R6/no-overlay and manually distance-checked with the corrected
    # `_haversine_m_sql` (see test_haversine_matches_a_reference_calculation):
    # "Cotenna" (nyc_dohmh_restaurants:50014197, active) sits a VERIFIED
    # 18.89 m from this address point -- inside POI_MATCH_RADIUS_M -- and
    # "Quique Crudo" (nyc_dohmh_restaurants:50139570) a verified 18.95 m.
    ("1005270009", "18 Bedford Street (R6, no overlay, open DOHMH restaurant "
                   "'Cotenna' 18.9 m away)", "grandfathered"),
]


#: The command a loud xfail/CLI-exit1 reason should send a reader to. Named
#: once so the reason text and the CLI's own error message cannot drift
#: apart (D97 item 7).
REAPPLY_COMMAND = "loci address-legality build"


def _warehouse_or_skip():
    """SKIP only when there is nothing to check at all (warehouse file
    absent, or the sql/031 columns have never been migrated in) -- CI and a
    fresh clone must not fail on missing data. But when the warehouse IS
    present and the migration HAS run and `legality` is entirely NULL (the
    build step itself has simply never executed against this file), that is
    a data-readiness gap this project's own code created and can name
    exactly how to fix -- XFAIL, loudly, naming the re-apply command,
    D97 item 7: a green suite must never quietly hide an unapplied layer
    behind a bare 'skipped'."""
    if not locidb.DEFAULT_PATH.exists():
        pytest.skip(f"warehouse absent at {locidb.DEFAULT_PATH}; AC-4 cannot be checked")
    import duckdb as _duckdb
    try:
        con = locidb.connect(read_only=True)
    except _duckdb.IOException as exc:
        # D69: a concurrent writer holding the file (a peer's rebuild in
        # progress) is the NORMAL state here, not an error -- this file's
        # own REAL_BBLS docstring already says so. A lock conflict is
        # genuinely "cannot check right now", distinct from the "checked and
        # it is unpopulated" case XFAIL is for below.
        pytest.skip(f"warehouse locked by a concurrent writer (D69): {exc}")
    has_col = con.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema='analysis' "
        "AND table_name='address' AND column_name='legality'").fetchone()[0]
    if not has_col:
        pytest.skip("analysis.address has no legality column yet -- "
                    f"run `{REAPPLY_COMMAND}`")
    n = con.execute(
        "SELECT count(*) FROM analysis.address WHERE legality IS NOT NULL").fetchone()[0]
    if not n:
        pytest.xfail(
            "analysis.address.legality is entirely NULL -- the sql/031 columns "
            "exist but the build step has never populated them on this "
            f"warehouse (or ran before D97's rule change). Re-apply with: "
            f"`{REAPPLY_COMMAND}`")
    return con


@pytest.mark.parametrize("bbl, label, expected", REAL_BBLS)
def test_real_bbls_match_the_pinned_legality(bbl, label, expected):
    """AC-4. Provisional while a peer session's address rebuild is in
    progress (2026-09-14 coordination note) -- run again after it completes
    if this fails on a NULL rather than a mismatch."""
    con = _warehouse_or_skip()
    row = con.execute(
        "SELECT legality, legality_basis, zonedist1, ownertype "
        "FROM analysis.address WHERE bbl = ?", [bbl]).fetchone()
    assert row is not None, f"{label} (bbl {bbl}) not found in analysis.address"
    legality, basis, zonedist1, ownertype = row
    assert legality == expected, (
        f"{label}: expected {expected!r}, got {legality!r} "
        f"(zonedist1={zonedist1!r}, ownertype={ownertype!r}, basis={basis!r})")


# ======================================== 6. the ST_Distance_Sphere bug (D97 fix)

def test_haversine_matches_a_reference_calculation():
    """2026-09-14: a peer-reported miss on 1004710039 ("379 Broome St") traced
    to DuckDB spatial's ST_Distance_Sphere returning 8.88 m for a pair whose
    true distance is 32.21 m in this environment (reproduced independently;
    see `_haversine_m_sql`'s docstring). This pins the REPLACEMENT formula
    against a reference implementation (Python's own haversine, not DuckDB's)
    so a future DuckDB spatial upgrade that fixes ST_Distance_Sphere is not
    mistaken for a regression here."""
    import math

    con = _mem_spatial_con()
    lon1, lat1 = -73.9965728, 40.7201126
    lon2, lat2 = -73.996572811102, 40.720402277551
    # Literal numbers, not "?" placeholders: `_haversine_m_sql` reuses each
    # argument expression twice in the formula (once alone, once in the
    # midpoint average), so a repeated "?" would need each occurrence bound
    # separately -- literals sidestep that entirely and are exactly how
    # `open_poi_match_sql` calls this (with column references, not params).
    expr = al._haversine_m_sql(repr(lon1), repr(lat1), repr(lon2), repr(lat2))
    got = con.execute(f"SELECT {expr}").fetchone()[0]

    R = 6_371_000.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    reference_m = R * 2 * math.asin(math.sqrt(a))

    assert got == pytest.approx(reference_m, rel=1e-6)
    assert got == pytest.approx(32.21, abs=0.05)


def test_st_distance_sphere_with_flip_matches_haversine_within_1pct():
    """D97 item 1 (contrarian review): retracts the earlier claim that
    DuckDB spatial's `ST_Distance_Sphere` is broken in this environment. It
    is NOT broken -- `db.py`'s own D16 comment already documents that it
    reads a bare `ST_Point(x, y)` as (LATITUDE, LONGITUDE), the reverse of
    this project's (lon, lat) convention, and must be wrapped in
    `ST_FlipCoordinates` (db.METRES_SQL). This pins that the FLIPPED call
    agrees with this module's own `_haversine_m_sql` to within 1% relative
    error -- proof that the extension itself is fine, and that
    `_haversine_m_sql` remains a plain, independently-checkable choice
    rather than a workaround for a broken dependency."""
    con = _mem_spatial_con()
    lon1, lat1 = -73.9965728, 40.7201126
    lon2, lat2 = -73.996572811102, 40.720402277551
    flipped = con.execute(
        "SELECT ST_Distance_Sphere("
        f"ST_FlipCoordinates(ST_Point({lon1}, {lat1})), "
        f"ST_FlipCoordinates(ST_Point({lon2}, {lat2})))").fetchone()[0]
    haversine = con.execute(
        f"SELECT {al._haversine_m_sql(repr(lon1), repr(lat1), repr(lon2), repr(lat2))}"
    ).fetchone()[0]
    assert flipped == pytest.approx(haversine, rel=0.01)
    # And the UNFLIPPED call is the peer-reported bug, reproduced here so a
    # future reader does not have to take the docstring's word for it.
    unflipped = con.execute(
        f"SELECT ST_Distance_Sphere(ST_Point({lon1}, {lat1}), ST_Point({lon2}, {lat2}))"
    ).fetchone()[0]
    assert unflipped != pytest.approx(haversine, rel=0.01)


def test_calibration_shifts_read_as_real_metres():
    """A pure 0.001-degree latitude shift must read as ~111.3 m (the standard
    111,320 m/degree), and a pure 0.001-degree longitude shift at ~40.7N must
    read as ~84.4 m (111,320 * cos(40.7deg)) -- the exact check that caught
    ST_Distance_Sphere returning 30.7 m and 111.2 m for these two instead."""
    con = _mem_spatial_con()
    lon0, lat0 = -73.9965728, 40.7201126
    lat_expr = al._haversine_m_sql(repr(lon0), repr(lat0), repr(lon0), repr(lat0 + 0.001))
    lon_expr = al._haversine_m_sql(repr(lon0), repr(lat0), repr(lon0 + 0.001), repr(lat0))
    lat_shift = con.execute(f"SELECT {lat_expr}").fetchone()[0]
    lon_shift = con.execute(f"SELECT {lon_expr}").fetchone()[0]
    assert lat_shift == pytest.approx(111.3, abs=1.0)
    assert lon_shift == pytest.approx(84.4, abs=1.0)


def test_open_poi_match_no_longer_uses_st_distance_sphere():
    """Checks the EMITTED SQL, not the source text -- `_haversine_m_sql`'s own
    docstring mentions the retired function by name (it explains why it is
    retired), so a source-text grep would false-positive on the explanation
    itself."""
    sql = al.open_poi_match_sql()
    assert "ST_Distance_Sphere" not in sql
    assert "ST_Point" not in sql
    assert "radians(" in sql


def test_broome_st_address_has_no_open_commercial_poi_truly_within_radius():
    """2026-09-14: a peer-reported claim said address_id 1004710039 ("379
    Broome St") should read has_open_commercial_poi=True because an open
    café sat "12.6 m away" -- a figure produced by the buggy
    ST_Distance_Sphere this module no longer uses. Independently
    recalculated with the verified `_haversine_m_sql`, the TRUE nearest open
    commercial POI to that address (Stone Street Coffee Soho) is ~26.98 m
    away -- outside POI_MATCH_RADIUS_M. This address is zoned C6-2G (a
    commercial district, not R), so its own legality is 'commercial' either
    way; this test pins that the fix does not manufacture a false positive
    there just because a since-corrected distance once suggested one."""
    con = _warehouse_or_skip()
    row = con.execute(
        "SELECT legality, has_open_commercial_poi, zonedist1 "
        "FROM analysis.address WHERE address_id = '1004710039'").fetchone()
    assert row is not None, "379 Broome St (1004710039) not found"
    legality, has_open, zonedist1 = row
    assert legality == "commercial"        # C6-2G either way -- not R-branch at all
    assert zonedist1 == "C6-2G"


# ============================================ 7. `address-legality stats` exit 1

def test_stats_cli_exits_1_when_legality_column_is_entirely_null(warehouse):
    """D97 item 7: `loci address-legality stats` must not print a silently
    all-zero distribution -- it must fail loud and name the re-apply command
    when analysis.address holds rows but legality was never populated on
    this warehouse (a database that ran sql/031's ALTERs but never the
    build step)."""
    from unittest import mock

    from typer.testing import CliRunner

    from loci import cli
    from loci.model import recommend as rec

    _insert(warehouse, [_row("a", zonedist1="R6")])  # legality left NULL

    with mock.patch.object(rec, "connect_read_only", lambda *a, **k: warehouse):
        result = CliRunner().invoke(cli.app, ["address-legality", "stats"])

    assert result.exit_code == 1
    assert "address-legality build" in result.output


def test_stats_cli_succeeds_when_legality_is_populated(warehouse):
    """Sibling to the test above: a warehouse where legality IS populated
    must NOT trip the guard (proves the check is about "entirely NULL", not
    "not every value is non-NULL")."""
    from unittest import mock

    from typer.testing import CliRunner

    from loci import cli
    from loci.model import recommend as rec

    row = _row("a", zonedist1="C1-7")
    row["legality"] = "commercial"
    row["legality_basis"] = "commercially zoned (C1-7)"
    _insert(warehouse, [row])

    with mock.patch.object(rec, "connect_read_only", lambda *a, **k: warehouse):
        result = CliRunner().invoke(cli.app, ["address-legality", "stats"])

    assert result.exit_code == 0
