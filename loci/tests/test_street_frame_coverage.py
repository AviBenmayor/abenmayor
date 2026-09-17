"""The street frame gets everything the lot frame has (owner ruling 4,
2026-09-16) -- and the absences it used to have are now impossible to
reintroduce silently.

WHAT WENT WRONG, AND WHY NOTHING CAUGHT IT. D84 added 50,199 `frame='street'`
rows to `analysis.address`. Every builder downstream filtered them out --
`COALESCE(frame,'lot') = 'lot'` in `model/address_bike.py` and
`model/address_bike_growth.py`, a `bbl`-keyed merge in
`model/address_demographics.py` -- and every consumer joined LEFT. So a third
of the universe carried NULL demographics, NULL bike growth and NULL forecast,
and read downstream as "no data here", indistinguishable from "we measured and
there is nothing here". No row count moved, no constraint fired, no test failed.

That is the failure class this file exists to make loud: an ABSENCE that is
identical, at every join, to a measured zero. The assertions below are
therefore about ROWS EXISTING, not about values being right -- the values are
pinned by tests/test_address_demographics.py and tests/test_address_bike_growth.py.

Everything here runs on a temporary DuckDB and a hand-written GeoJSON. Nothing
opens the live warehouse, in either mode.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import duckdb
import numpy as np
import pandas as pd
import pytest

from loci import db as locidb
from loci.model import address_bike as ab
from loci.model import address_bike_growth as bg
from loci.model import address_demographics as ad

# Two adjacent 2020 tracts sharing the meridian -73.99, which is where a
# boundary-street midpoint gets to sit. A third, far away, is never hit.
TRACT_A = "36061000100"      # Manhattan
TRACT_B = "36047000200"      # Brooklyn


def _write_tract_geojson(path: pathlib.Path, *, vintage: int = 2020) -> pathlib.Path:
    """Two touching square tracts, EPSG:4326, TIGER field naming for `vintage`."""
    geoid = "GEOID" if vintage == 2020 else "GEOID10"
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {geoid: TRACT_A},
         "geometry": {"type": "Polygon", "coordinates": [[
             [-74.00, 40.70], [-73.99, 40.70], [-73.99, 40.71],
             [-74.00, 40.71], [-74.00, 40.70]]]}},
        {"type": "Feature", "properties": {geoid: TRACT_B},
         "geometry": {"type": "Polygon", "coordinates": [[
             [-73.99, 40.70], [-73.98, 40.70], [-73.98, 40.71],
             [-73.99, 40.71], [-73.99, 40.70]]]}},
    ]}
    path.write_text(json.dumps(fc))
    return path


def _fake_tract(inc: float = 80000.0) -> dict:
    """One synthetic ACS tract record whose B25044/B25003 and B01001/B01003
    totals reconcile, so `build_address_demographics`' fail-loud cross-checks
    pass on it."""
    return {
        "B01003_001E": "1000", "B01003_001M": "100",
        "B01001_001E": "1000", "B01001_001M": "100",
        "B11001_001E": "400", "B11001_001M": "40",
        "B19013_001E": str(int(inc)), "B19013_001M": "5000",
        "B25003_001E": "380", "B25003_001M": "30",
        "B25003_003E": "190", "B25003_003M": "20",
        "B08201_001E": "400", "B08201_001M": "40",
        "B08201_002E": "80", "B08201_002M": "15",
        "B25044_001E": "380", "B25044_001M": "30",
        "B25044_002E": "190", "B25044_002M": "20",
        "B25044_003E": "19", "B25044_003M": "6",
        "B25044_009E": "190", "B25044_009M": "20",
        "B25044_010E": "76", "B25044_010M": "12",
    }


def _write_pluto(path: pathlib.Path) -> pathlib.Path:
    pd.DataFrame([
        {"BBL": "1000010001", "borocode": "1", "bct2020": "1000100"},
        {"BBL": "3000010001", "borocode": "3", "bct2020": "3000200"},
    ]).to_csv(path, index=False)
    return path


#: The universe every demographics test below runs on: two lot addresses (one
#: per tract) and four street midpoints -- one squarely inside each tract, one
#: ON the shared boundary, and one in the Atlantic, outside every polygon.
UNIVERSE = [
    # (address_id, bbl,          borough, lon,     lat,    frame)
    ("1000010001", "1000010001", "MN", -73.995, 40.705, "lot"),
    ("3000010001", "3000010001", "BK", -73.985, 40.705, "lot"),
    ("ST-MN-1",    None,         "MN", -73.995, 40.705, "street"),
    ("ST-BK-1",    None,         "BK", -73.985, 40.705, "street"),
    ("ST-EDGE",    None,         "BK", -73.990, 40.705, "street"),   # on the line
    # 5.5 m inside TRACT_B: assigned cleanly, decided by cartography
    ("ST-NEAR",    None,         "BK", -73.98995, 40.705, "street"),
    ("ST-PIER",    None,         "BK", -73.500, 40.500, "street"),   # no polygon
]
STREET_IDS = [r[0] for r in UNIVERSE if r[5] == "street"]


@pytest.fixture
def warehouse():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.executemany(
        "INSERT INTO analysis.address (address_id, bbl, borough, lon, lat, frame, "
        "present_count, eligible, n_missing, reach_source, reach_hash, "
        "graph_version, run_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, TRUE, 0, 'tiers', 'test', 'test', now())",
        UNIVERSE)
    return con


@pytest.fixture
def built(warehouse, tmp_path, monkeypatch):
    """The demographics table as `loci address-demographics` would leave it:
    lot frame from PLUTO's bct2020, street frame from point-in-polygon, then
    the prune."""
    monkeypatch.setattr(ad, "fetch_acs",
                        lambda year=2023, refresh=False: {TRACT_A: _fake_tract(),
                                                          TRACT_B: _fake_tract(60000)})
    polys = _write_tract_geojson(tmp_path / "tl_2020_36_tract.geojson")
    lots = pd.DataFrame([{"address_id": a, "bbl": b}
                         for a, b, *_ in UNIVERSE if b is not None])
    report: dict = {}
    df = ad.build_address_demographics(
        warehouse, lots, year=2023, pluto_csv=_write_pluto(tmp_path / "pluto.csv"),
        street_df=ad.load_street_frame(warehouse), polygons=polys, report=report)
    ad.write_address_demographics(warehouse, df, year=2023)
    return warehouse, report


# ----------------------------------------------- (a) no street row is missing

def test_no_street_address_lacks_a_demographics_row(built):
    """THE assertion. Before owner ruling 4 this count was 50,199."""
    con, _ = built
    missing = con.execute("""
        SELECT count(*) FROM analysis.address a
        WHERE COALESCE(a.frame, 'lot') = 'street'
          AND NOT EXISTS (SELECT 1 FROM analysis.address_demographics d
                          WHERE d.address_id = a.address_id)""").fetchone()[0]
    assert missing == 0


def test_every_address_in_the_universe_has_exactly_one_row(built):
    """(address_id, acs_year) is the key. The street frame must ARRIVE without
    fanning the lot frame out -- a point on a tract boundary intersects TWO
    polygons, and the tie-break is what stops that becoming two rows."""
    con, _ = built
    rows, addrs = con.execute(
        "SELECT count(*), count(DISTINCT address_id) "
        "FROM analysis.address_demographics").fetchone()
    assert rows == addrs == len(UNIVERSE)


def test_a_street_point_and_a_lot_in_one_tract_get_identical_values(built):
    """The street frame is an EXTENSION of this table, not a second table
    wearing its name: same ACS pull, same per-tract stats, same merge."""
    con, _ = built
    got = dict(con.execute(
        "SELECT address_id, median_hh_income FROM analysis.address_demographics "
        "WHERE address_id IN ('1000010001', 'ST-MN-1')").fetchall())
    assert got["ST-MN-1"] == got["1000010001"] == 80000.0


# ----------------------------- (c) outside every polygon = a row, NULL tract

def test_a_street_point_outside_every_tract_is_a_row_with_a_null_tract(built):
    """A pier, a bridge deck, a boundary tie into the harbour. The row EXISTS
    and states the absence; it is never an omission, because "in the universe,
    tract unknown" and "not in the universe" are different facts and only one
    of them is true here (owner, no eligibility gate, 2026-09-13)."""
    con, report = built
    row = con.execute(
        "SELECT tract_geoid, median_hh_income, population "
        "FROM analysis.address_demographics WHERE address_id = 'ST-PIER'").fetchone()
    assert row is not None, "the un-tracted street point was DROPPED, not recorded"
    assert row == (None, None, None)
    assert report["street"]["no_tract"] == 1
    assert report["street"]["points"] == len(STREET_IDS)
    assert (report["street"]["assigned"] + report["street"]["no_tract"]
            == report["street"]["points"])


def test_a_boundary_street_point_is_assigned_once_and_the_tie_is_counted(built):
    """NYC tract boundaries run down street centrelines, so a midpoint ON the
    line intersects both neighbours. It takes the lower GEOID, deterministically,
    and the tie is REPORTED -- not resolved by whichever polygon the scan
    reached first, and not turned into a NULL by an ST_Contains that excludes
    the boundary (which would manufacture a gap on exactly the streets the
    frame exists to see)."""
    con, report = built
    assert report["street"]["boundary_ties"] == 1
    assert report["street"]["max_candidates"] == 2
    assert con.execute(
        "SELECT tract_geoid FROM analysis.address_demographics "
        "WHERE address_id = 'ST-EDGE'").fetchone()[0] == min(TRACT_A, TRACT_B)


def test_a_point_metres_from_a_boundary_is_assigned_cleanly_and_flagged(built):
    """THE caveat the exact tie count hides. NYC tract boundaries follow street
    centrelines and the street frame sits ON street centrelines -- but TIGER
    digitised its boundary from its own centreline file, not from CSCL, so the
    two lines differ by a metre or two and the point lands cleanly on one side.
    `n_tract_candidates` is 1 and nothing looks uncertain, when the assignment
    was in fact decided by sub-metre disagreement between two agencies.

    ST-NEAR sits 5.5 m inside TRACT_B. It gets TRACT_B, unambiguously and
    correctly as computed -- and it is COUNTED as boundary-ambiguous, which is
    the only way a reader can know how much of the street frame's demographics
    rests on cartography rather than on geography."""
    con, report = built
    assert con.execute(
        "SELECT tract_geoid FROM analysis.address_demographics "
        "WHERE address_id = 'ST-NEAR'").fetchone()[0] == TRACT_B
    # ST-EDGE (an exact tie) and ST-NEAR (5.5 m away) -- not the two interior
    # points, and not the pier.
    assert report["street"]["boundary_ambiguous"] == 2
    assert report["street"]["boundary_ties"] == 1


def test_street_rows_carry_a_null_bbl_which_is_the_provenance_marker(built):
    """No extra column says how a tract was found: a NULL `bbl` means
    point-in-polygon, a non-NULL one means PLUTO's precomputed bct2020."""
    con, _ = built
    assert con.execute(
        "SELECT count(*) FROM analysis.address_demographics d "
        "JOIN analysis.address a USING (address_id) "
        "WHERE COALESCE(a.frame,'lot') = 'street' AND d.bbl IS NOT NULL"
    ).fetchone()[0] == 0


# --------------------------------------------------- the vintage guards bite

def test_a_2010_vintage_polygon_file_is_refused_for_an_acs_2023_build(tmp_path):
    """The silent, plausible-looking error CONTEXT 7.4b is about: ACS 2023 is
    published on 2020 tract geography, so resolving a point against 2010
    polygons yields a real tract id and a real income for the wrong place, with
    no NULL and no error anywhere downstream."""
    polys = _write_tract_geojson(tmp_path / "tl_2010_36_tract10.geojson", vintage=2010)
    pts = pd.DataFrame([{"address_id": "ST-MN-1", "lon": -73.995, "lat": 40.705}])
    with pytest.raises(RuntimeError, match="2010-vintage"):
        ad.assign_tracts_by_point(pts, {TRACT_A, TRACT_B}, 2023, polygons=polys)


def test_polygons_whose_geoids_the_acs_pull_never_returned_are_refused(tmp_path):
    """Guard #3, the one that survives a renamed field: the polygons and the ACS
    estimates have to be talking about the same tracts."""
    polys = _write_tract_geojson(tmp_path / "tl_2020_36_tract.geojson")
    pts = pd.DataFrame([{"address_id": "ST-MN-1", "lon": -73.995, "lat": 40.705}])
    with pytest.raises(RuntimeError, match="GEOID that ACS 2023 returned"):
        ad.assign_tracts_by_point(pts, {"36061999999"}, 2023, polygons=polys)


def test_the_acs_year_to_tract_vintage_map_is_closed():
    assert ad.tract_vintage_for(2023) == 2020
    assert ad.tract_vintage_for(2013) == 2010
    with pytest.raises(RuntimeError, match="no declared tract vintage"):
        ad.tract_vintage_for(2021)


def test_a_missing_polygon_file_raises_rather_than_dropping_the_street_frame(tmp_path):
    pts = pd.DataFrame([{"address_id": "ST-MN-1", "lon": -73.995, "lat": 40.705}])
    with pytest.raises(FileNotFoundError, match="census-tract polygons"):
        ad.assign_tracts_by_point(pts, {TRACT_A}, 2023,
                                  polygons=tmp_path / "not_downloaded.geojson")


def test_the_frame_vocabulary_matches_address_gaps():
    """address_demographics restates 'lot'/'street' rather than importing them
    (address_gaps drags in osmnx and scipy). This is the anti-drift pin."""
    from loci.model.address_gaps import FRAMES

    assert set(FRAMES) == {ad.LOT_FRAME, ad.STREET_FRAME}


# ------------------------------------------------------------- (d) the prune

def test_the_prune_removes_orphans_and_touches_nothing_in_the_universe(built):
    """Audit finding 15: the table was built on the unclipped 5-borough PLUTO
    universe and held 485,495 rows for addresses D78 had removed. Invisible,
    because every read joins FROM analysis.address -- so the orphans only ever
    showed up in a row count, which is precisely the number that gets quoted as
    coverage."""
    con, _ = built
    before = dict(con.execute(
        "SELECT address_id, tract_geoid FROM analysis.address_demographics").fetchall())
    con.execute(
        "INSERT INTO analysis.address_demographics (address_id, bbl, tract_geoid, "
        "acs_year, median_hh_income) VALUES ('4000010001', '4000010001', "
        "'36081000100', 2023, 999999.0)")   # a Queens lot, outside the screen

    removed = ad.prune_out_of_scope(con)

    assert removed == 1
    after = dict(con.execute(
        "SELECT address_id, tract_geoid FROM analysis.address_demographics").fetchall())
    assert after == before, "the prune moved a row that is IN the universe"
    assert ad.prune_out_of_scope(con) == 0, "the prune is not idempotent"


def test_the_prune_refuses_to_run_against_an_empty_universe(built):
    """If analysis.address has never been built, every row here looks like an
    orphan and an unguarded DELETE would empty the table and report success --
    the silent zero this project refuses to ingest."""
    con, _ = built
    con.execute("DELETE FROM analysis.address")
    with pytest.raises(RuntimeError, match="EMPTY"):
        ad.prune_out_of_scope(con)
    assert con.execute(
        "SELECT count(*) FROM analysis.address_demographics").fetchone()[0] == len(UNIVERSE)


def test_the_writer_prunes(warehouse, tmp_path, monkeypatch):
    """The prune is not an operator step that can be forgotten between runs."""
    monkeypatch.setattr(ad, "fetch_acs",
                        lambda year=2023, refresh=False: {TRACT_A: _fake_tract()})
    lots = pd.DataFrame([
        {"address_id": "1000010001", "bbl": "1000010001"},
        {"address_id": "9000019999", "bbl": "1000010001"},   # not in the universe
    ])
    df = ad.build_address_demographics(
        warehouse, lots, year=2023, pluto_csv=_write_pluto(tmp_path / "pluto.csv"))
    assert len(df) == 2
    n = ad.write_address_demographics(warehouse, df, year=2023)
    assert n == 1, "write_address_demographics returned len(df), not what it stored"
    assert con_ids(warehouse) == {"1000010001"}


def con_ids(con) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT address_id FROM analysis.address_demographics").fetchall()}


# ------------------------------------------- (b) the bike sweep and its rows

#: One dock alive across both of the 2026-08 vintage's twelve-month windows.
_M = dt.date(2026, 8, 1)


@pytest.fixture
def bike_warehouse(tmp_path):
    """The smallest warehouse `build_growth` reads: one balanced dock, a lot
    address and a street address that both reach it."""
    con = duckdb.connect(str(tmp_path / "bike.duckdb"))
    con.execute("CREATE SCHEMA staging; CREATE SCHEMA analysis")
    con.execute("""
        CREATE TABLE staging.citibike_station_month (
            station_id VARCHAR, station_name VARCHAR, lon DOUBLE, lat DOUBLE,
            month DATE, day_type VARCHAR, daypart VARCHAR,
            starts BIGINT, ends BIGINT, member_starts BIGINT,
            casual_starts BIGINT, member_ends BIGINT, casual_ends BIGINT,
            days_in_cell SMALLINT, ingested_at TIMESTAMP)""")
    con.execute("""
        CREATE TABLE staging.citibike_station (
            station_id VARCHAR, name VARCHAR, lon DOUBLE, lat DOUBLE,
            first_month DATE, last_month DATE, months_active INTEGER,
            ingested_at TIMESTAMP)""")
    con.execute("""
        CREATE TABLE analysis.address (
            address_id VARCHAR, borough VARCHAR, lon DOUBLE, lat DOUBLE,
            frame VARCHAR DEFAULT 'lot')""")
    con.execute("""
        CREATE TABLE analysis.address_bike_station (
            address_id VARCHAR, borough VARCHAR, station_id VARCHAR,
            dist_m DOUBLE, radius_m REAL, graph_version VARCHAR,
            run_at TIMESTAMP)""")
    con.execute((pathlib.Path(bg.__file__).resolve().parents[1]
                 / "sql" / "038_bike_growth.sql").read_text())

    first, last = dt.date(2024, 9, 1), dt.date(2026, 8, 1)
    con.execute(
        "INSERT INTO staging.citibike_station VALUES ('D1', 'dock D1', -73.95, "
        "40.70, ?, ?, 24, now())", [first, last])
    month = first
    while month <= last:
        con.execute(
            "INSERT INTO staging.citibike_station_month VALUES ('D1', 'dock D1', "
            "-73.95, 40.70, ?, 'weekday', 'midday', 500, 500, 500, 0, 500, 0, 21, now())",
            [month])
        month = bg.add_months(month, 1)

    con.executemany(
        "INSERT INTO analysis.address VALUES (?, 'BK', -73.95, 40.70, ?)",
        [("LOT-1", "lot"), ("ST-1", "street"), ("ST-2", "street")])
    con.executemany(
        "INSERT INTO analysis.address_bike_station VALUES (?, 'BK', 'D1', 120.0, "
        "400.0, 'test', now())", [("LOT-1",), ("ST-1",)])
    return con


def test_no_street_address_lacks_a_bike_growth_row(bike_warehouse):
    """The street frame goes through the SAME sweep and the SAME vintage. ST-2
    reaches no dock and still gets a row -- NULL with its reason stored -- which
    is the distinction the old lot-only universe destroyed."""
    bg.build_growth(bike_warehouse, _M, ["BK"])
    missing = bike_warehouse.execute("""
        SELECT count(*) FROM analysis.address a
        WHERE COALESCE(a.frame, 'lot') = 'street'
          AND NOT EXISTS (SELECT 1 FROM analysis.address_bike_growth g
                          WHERE g.address_id = a.address_id
                            AND g.asof_month = ?)""", [_M]).fetchone()[0]
    assert missing == 0
    assert bike_warehouse.execute(
        "SELECT count(*) FROM analysis.address_bike_growth").fetchone()[0] == 3
    assert bike_warehouse.execute(
        "SELECT n_docks_balanced, bike_growth_12m FROM analysis.address_bike_growth "
        "WHERE address_id = 'ST-2'").fetchone() == (0, None)


def test_growth_refuses_a_universe_whose_street_frame_was_never_swept(bike_warehouse):
    """The silent zero this widening could otherwise create: a street frame in
    the universe but absent from analysis.address_bike_station writes rows that
    all say "no balanced dock" -- a fact about the pipeline, not about Citi
    Bike, and indistinguishable downstream from a real dock desert."""
    bike_warehouse.execute(
        "DELETE FROM analysis.address_bike_station WHERE address_id = 'ST-1'")
    with pytest.raises(RuntimeError, match="ZERO rows in"):
        bg.build_growth(bike_warehouse, _M, ["BK"])
    assert bike_warehouse.execute(
        "SELECT count(*) FROM analysis.address_bike_growth").fetchone()[0] == 0


def test_address_universe_lot_subset_is_unchanged_by_the_widening(bike_warehouse):
    """`frames=('lot',)` reproduces the pre-2026-09-16 universe exactly, and the
    widened one is that plus the street rows -- nothing dropped, nothing
    rewritten."""
    wide = bg.address_universe(bike_warehouse, ["BK"])
    narrow = bg.address_universe(bike_warehouse, ["BK"], frames=("lot",))
    assert set(narrow["address_id"]) == {"LOT-1"}
    assert set(wide["address_id"]) == {"LOT-1", "ST-1", "ST-2"}
    pd.testing.assert_frame_equal(
        wide[wide["address_id"].isin(narrow["address_id"])].reset_index(drop=True),
        narrow.reset_index(drop=True))


def test_load_address_points_lot_subset_is_unchanged_by_the_widening(bike_warehouse):
    wide = ab.load_address_points(bike_warehouse, ["BK"])
    narrow = ab.load_address_points(bike_warehouse, ["BK"], frames=("lot",))
    pd.testing.assert_frame_equal(
        wide[wide["address_id"].isin(narrow["address_id"])].reset_index(drop=True),
        narrow.reset_index(drop=True))


def test_extra_query_nodes_do_not_move_an_existing_distance():
    """THE proof that widening the Dijkstra sweep cannot perturb a lot number.

    The sweep is one bounded single-source shortest path per distinct query
    NODE over a CSR built from the walk-graph pickle alone -- the address frame
    never reaches `_to_csr`. So adding query nodes adds rows and moves none.
    Asserted on a synthetic line graph rather than argued, and asserted across
    a BATCH boundary, because the batching is the one place an implementation
    could make one query's answer depend on its neighbours.

    (And note what is NOT done here: the CSR is built with each edge stored
    ONCE and `dijkstra(directed=False)`. scipy's csr_matrix SUMS duplicate
    (row, col) entries, so mirroring edges by hand would silently DOUBLE every
    length -- the bug score/access.py warns about.)
    """
    from scipy.sparse import csr_matrix

    from loci.model.address_transit_profile import catchment_pairs

    n = 6
    rows = np.arange(n - 1)
    A = csr_matrix((np.full(n - 1, 100.0), (rows, rows + 1)), shape=(n, n))
    targets = np.array([5], dtype=np.int64)

    q1, t1, d1 = catchment_pairs(A, np.array([0], dtype=np.int64), targets,
                                 radius_m=550.0, batch=2)
    q2, t2, d2 = catchment_pairs(A, np.array([0, 1, 2, 3], dtype=np.int64), targets,
                                 radius_m=550.0, batch=2)
    keep = q2 == 0
    assert np.array_equal(d1, d2[keep])
    assert np.array_equal(t1, t2[keep])
    # five 100 m edges, counted ONCE each. A mirrored-edge bug reads 1000.0.
    assert d1.tolist() == [500.0]
