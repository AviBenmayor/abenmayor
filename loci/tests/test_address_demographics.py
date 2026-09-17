"""Synthetic, no-network tests for the address-level ACS demographics table
(D56): the BBL -> tract lookup, the direct (unapportioned) per-tract stat
derivation, and a drift test tying the table's column list to the
hand-maintained ADDRESS_DEMOGRAPHICS_COLUMNS constant."""
import math

import pandas as pd

from loci import db as locidb
from loci.model.address_demographics import (
    ADDRESS_DEMOGRAPHICS_COLUMNS,
    build_address_demographics,
    load_bbl_tract_map,
    write_address_demographics,
)

TRACT_A = "36061000100"   # Manhattan, county 061, bct2020 "1000100"
TRACT_B = "36047000200"   # Brooklyn, county 047, bct2020 "3000200"


def _fake_tract(pop=1000, hh=400, inc=80000, inc_moe=5000,
                 occ=380, rent=190, veh_den=400, veh0=80,
                 own_den=190, own0=19, rt_den=190, rt0=76) -> dict:
    """One synthetic tract; owner+renter reconciles with occ so the
    cross-table check in build_address_demographics passes."""
    return {
        "B01003_001E": str(pop), "B01003_001M": "100",
        "B11001_001E": str(hh), "B11001_001M": "40",
        "B19013_001E": str(inc), "B19013_001M": str(inc_moe),
        "B25003_001E": str(occ), "B25003_001M": "30",
        "B25003_003E": str(rent), "B25003_003M": "20",
        "B08201_001E": str(veh_den), "B08201_001M": "40",
        "B08201_002E": str(veh0), "B08201_002M": "15",
        "B25044_001E": str(occ), "B25044_001M": "30",
        "B25044_002E": str(own_den), "B25044_002M": "20",
        "B25044_003E": str(own0), "B25044_003M": "6",
        "B25044_009E": str(rt_den), "B25044_009M": "20",
        "B25044_010E": str(rt0), "B25044_010M": "12",
    }


def _write_pluto_fixture(path) -> None:
    df = pd.DataFrame([
        # borocode 1 = Manhattan (county 061); bct2020 "1000100" -> geoid TRACT_A
        {"BBL": "1000010001", "borocode": "1", "bct2020": "1000100"},
        {"BBL": "1000010002", "borocode": "1", "bct2020": "1000100"},
        # borocode 3 = Brooklyn (county 047); bct2020 "3000200" -> geoid TRACT_B
        {"BBL": "3000010001", "borocode": "3", "bct2020": "3000200"},
        # a lot with NO bct2020 at all -- must not be dropped downstream,
        # just left with no tract.
        {"BBL": "1000010003", "borocode": "1", "bct2020": ""},
    ])
    df.to_csv(path, index=False)


def test_load_bbl_tract_map_matches_grid_acs_geoid_construction(tmp_path):
    pluto_csv = tmp_path / "pluto.csv"
    _write_pluto_fixture(pluto_csv)
    tmap = load_bbl_tract_map(pluto_csv)
    lookup = dict(zip(tmap["bbl"], tmap["tract_geoid"]))
    assert lookup["1000010001"] == TRACT_A
    assert lookup["3000010001"] == TRACT_B
    # the blank-bct2020 lot is absent from the map entirely (left-join in the
    # caller turns that into a NULL tract, not a KeyError)
    assert "1000010003" not in lookup


def test_build_address_demographics_direct_no_apportionment(tmp_path, monkeypatch):
    """Two addresses share TRACT_A -- since assignment is direct (not
    dasymetric), both must get the IDENTICAL tract-level values, unlike the
    hex table where per-hex unit-share weights would differ them. A third
    address in TRACT_B gets TRACT_B's values. A fourth, with no tract, gets
    every demographic column NULL but is NOT dropped from the frame."""
    pluto_csv = tmp_path / "pluto.csv"
    _write_pluto_fixture(pluto_csv)

    fake_acs = {TRACT_A: _fake_tract(), TRACT_B: _fake_tract(pop=500, inc=60000)}
    monkeypatch.setattr("loci.model.address_demographics.fetch_acs",
                         lambda year=2023, refresh=False: fake_acs)

    addresses_df = pd.DataFrame([
        {"address_id": "1000010001", "bbl": "1000010001"},
        {"address_id": "1000010002", "bbl": "1000010002"},
        {"address_id": "3000010001", "bbl": "3000010001"},
        {"address_id": "1000010003", "bbl": "1000010003"},
    ])

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    df = build_address_demographics(con, addresses_df, year=2023, pluto_csv=pluto_csv)

    assert len(df) == 4   # nothing dropped, including the no-tract address
    assert list(df.columns) == ADDRESS_DEMOGRAPHICS_COLUMNS

    by_id = df.set_index("address_id")

    a1, a2 = by_id.loc["1000010001"], by_id.loc["1000010002"]
    assert a1["tract_geoid"] == a2["tract_geoid"] == TRACT_A
    for col in ("median_hh_income", "renter_share", "zero_vehicle_hh_share"):
        assert math.isclose(a1[col], a2[col], rel_tol=1e-9)
    assert math.isclose(a1["median_hh_income"], 80000.0)
    assert math.isclose(a1["renter_share"], 190.0 / 380.0, rel_tol=1e-6)
    assert math.isclose(a1["zero_vehicle_hh_share"], 80.0 / 400.0, rel_tol=1e-6)
    assert math.isclose(a1["zero_vehicle_owner_share"], 19.0 / 190.0, rel_tol=1e-6)
    assert math.isclose(a1["zero_vehicle_renter_share"], 76.0 / 190.0, rel_tol=1e-6)
    assert a1["renter_share_moe"] is not None and a1["renter_share_moe"] >= 0.0

    b1 = by_id.loc["3000010001"]
    assert b1["tract_geoid"] == TRACT_B
    assert math.isclose(b1["median_hh_income"], 60000.0)

    no_tract = by_id.loc["1000010003"]
    assert pd.isna(no_tract["tract_geoid"])
    for col in ("median_hh_income", "renter_share", "zero_vehicle_hh_share"):
        assert pd.isna(no_tract[col])


def test_build_address_demographics_raises_on_cross_table_mismatch(tmp_path, monkeypatch):
    """Fail loud: a corrupted B25044 pull for a tract that IS actually used
    by an address must raise, not silently compute a wrong share."""
    pluto_csv = tmp_path / "pluto.csv"
    _write_pluto_fixture(pluto_csv)

    bad = _fake_tract()
    bad["B25044_002E"] = "1"   # owner total slashed -> cross-check fails
    fake_acs = {TRACT_A: bad}
    monkeypatch.setattr("loci.model.address_demographics.fetch_acs",
                         lambda year=2023, refresh=False: fake_acs)

    addresses_df = pd.DataFrame([{"address_id": "1000010001", "bbl": "1000010001"}])
    con = locidb.connect(":memory:")
    locidb.init_schema(con)

    try:
        build_address_demographics(con, addresses_df, year=2023, pluto_csv=pluto_csv)
    except RuntimeError as exc:
        assert "cross-check" in str(exc)
    else:
        raise AssertionError("expected a RuntimeError on the B25044/B25003 mismatch")


def test_write_address_demographics_round_trips(tmp_path, monkeypatch):
    pluto_csv = tmp_path / "pluto.csv"
    _write_pluto_fixture(pluto_csv)
    fake_acs = {TRACT_A: _fake_tract()}
    monkeypatch.setattr("loci.model.address_demographics.fetch_acs",
                         lambda year=2023, refresh=False: fake_acs)

    addresses_df = pd.DataFrame([
        {"address_id": "1000010001", "bbl": "1000010001"},
        {"address_id": "1000010002", "bbl": "1000010002"},
    ])
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    # The universe the writer clips to (audit finding 15, 2026-09-16). Both
    # addresses are IN it, so the prune must be a no-op here; that it is NOT a
    # no-op when an address is missing is pinned by
    # tests/test_street_frame_coverage.py::test_the_writer_prunes.
    con.executemany(
        "INSERT INTO analysis.address (address_id, bbl, borough, lon, lat, frame, "
        "present_count, eligible, n_missing, reach_source, reach_hash, "
        "graph_version, run_at) VALUES (?, ?, 'MN', -73.99, 40.70, 'lot', 0, TRUE, "
        "0, 'tiers', 'test', 'test', now())",
        [("1000010001", "1000010001"), ("1000010002", "1000010002")])
    df = build_address_demographics(con, addresses_df, year=2023, pluto_csv=pluto_csv)
    n = write_address_demographics(con, df, year=2023)
    assert n == 2

    got = con.execute("SELECT address_id, tract_geoid, median_hh_income "
                       "FROM analysis.address_demographics ORDER BY address_id").fetchall()
    assert got == [
        ("1000010001", TRACT_A, 80000.0),
        ("1000010002", TRACT_A, 80000.0),
    ]

    # idempotent re-write for the same acs_year: DELETE + INSERT, not an
    # ever-growing append.
    n2 = write_address_demographics(con, df, year=2023)
    assert n2 == 2
    total = con.execute("SELECT count(*) FROM analysis.address_demographics").fetchone()[0]
    assert total == 2


def test_address_demographics_table_columns_match_documented_constant():
    """Drift test: the live table's column list (information_schema) must
    equal ADDRESS_DEMOGRAPHICS_COLUMNS. Catches a DDL edit that forgets to
    update the constant, or vice versa."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='analysis' AND table_name='address_demographics' "
        "ORDER BY ordinal_position").fetchall()]
    assert cols == ADDRESS_DEMOGRAPHICS_COLUMNS
