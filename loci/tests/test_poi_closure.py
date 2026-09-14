"""The closure ledger (`staging.poi_closure`, model/poi_closure.py, sql/027).

docs/retrodiction-2026-09.md §4 found ZERO observable closures because
`sources/universal/foursquare_places._ensure_cache` fetched with
`WHERE date_closed IS NULL`. These tests pin the three things that could turn
the fix into a worse bug than the one it repairs.

  1. A CLOSED VENUE NEVER REACHES THE SUPPLY SET. The screen answers "what is
     open here today"; a shut laundromat counted as supply erases the very gap
     the screen exists to find. Asserted against the REAL adapter's
     `normalize()`, and against the fact that nothing in model/poi_closure
     writes staging.poi.
  2. THE location_key JOIN IS THE LEDGER'S OWN RULE. A closure is minted by
     `poi_presence.mint_key`, the same function, so it hashes as the open
     location did; and the fallback link is `score.dedup.names_match` within
     `MATCH_METERS`, so it can never be looser than the rule that formed the
     cluster. A looser rule would attach one storefront's closure to its
     neighbour -- manufacturing a closure that never happened.
  3. PRECEDENCE: a SOURCE-PUBLISHED date_closed closes a location; absence from
     a snapshot never does (D79). And where two closures land on one ledger
     row, the EARLIEST survives -- the direction that can only shorten an
     observed spell, never invent survival.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from loci import db as locidb
from loci.model import poi_closure as pc
from loci.model import poi_presence as pp
from loci.sources.universal.foursquare_places import FoursquarePlacesAdapter

TODAY = dt.date(2026, 9, 13)
MN = (-73.9857, 40.7484)
BK = (-73.9903, 40.6906)
NOW = dt.datetime(2026, 9, 14, 12, 0, 0)


def _poi(pid, source, name, category, lon, lat, cluster, *, opened=None,
         canonical=True):
    return (pid, source, category, name, lon, lat, opened,
            json.dumps({}), cluster, canonical)


BASE = [
    _poi("a1", "foursquare_os_places", "Apollo Bagels", "cafe_bakery", *MN, 1,
         opened="2023-03-04"),
    _poi("b1", "overture_places", "Zanzibar Hardware", "hardware", *BK, 2),
]


@pytest.fixture
def con():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS staging")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute("""CREATE TABLE staging.poi (
        poi_id VARCHAR PRIMARY KEY, source_id VARCHAR, source_record_id VARCHAR,
        category VARCHAR, tier SMALLINT, name VARCHAR, geom GEOMETRY,
        observed_on DATE, opened_on DATE, closed_on DATE, confidence FLOAT, attrs JSON)""")
    c.execute("CREATE TABLE analysis.poi_dedup (poi_id VARCHAR PRIMARY KEY, "
              "cluster_id BIGINT, is_canonical BOOLEAN, category VARCHAR)")
    c.execute("CREATE TABLE analysis.hex (h3_index VARCHAR PRIMARY KEY, borough VARCHAR)")
    for lon, lat, boro in ((*MN, "Manhattan"), (*BK, "Brooklyn")):
        c.execute("INSERT OR IGNORE INTO analysis.hex "
                  "SELECT h3_latlng_to_cell_string(?, ?, 9), ?", [lat, lon, boro])
    for pid, src, cat, name, lon, lat, opened, attrs, cluster, canon in BASE:
        c.execute(
            "INSERT INTO staging.poi (poi_id, source_id, category, tier, name, geom, "
            "opened_on, attrs) VALUES (?,?,?,1,?,ST_Point(?,?),CAST(? AS DATE),"
            "CAST(? AS JSON))", [pid, src, cat, name, lon, lat, opened, attrs])
        c.execute("INSERT INTO analysis.poi_dedup VALUES (?,?,?,?)",
                  [pid, cluster, canon, cat])
    pc.ensure_schema(c)
    return c


def _closure(con, fsq_id, category, name, lon, lat, closed, *, key=True,
             created=dt.date(2020, 1, 1)):
    """Insert one closure, minting the key exactly as `load` does."""
    nk = pp.name_key_of(name)
    lk = pp.mint_key(category, nk, lon, lat) if (key and category and nk) else None
    con.execute(f"INSERT INTO {pc.TABLE} VALUES (?,?,?,?,?,?,?,?,?,?)",
                [fsq_id, lk, category, name, lon, lat, created, closed,
                 pc.SOURCE, NOW])


# ------------------------------------------------- 1. the supply set is safe
def test_a_closed_venue_never_reaches_staging_poi():
    """The REAL adapter's normalize() drops any row carrying a date_closed.

    This is the invariant the whole change rests on: `staging.poi` -> dedup ->
    `poi_supply` is the screen's supply, and it is OPEN BUSINESSES ONLY."""
    rows = [
        {"id": "x1", "name": "Shuttered Nails", "labels": ["Business and Professional "
         "Services > Health and Beauty Service > Nail Salon"],
         "lat": MN[1], "lon": MN[0], "created": "2019-01-01",
         "refreshed": "2026-06-01", "closed": "2025-04-01"},
        {"id": "x2", "name": "Open Nails", "labels": ["Business and Professional "
         "Services > Health and Beauty Service > Nail Salon"],
         "lat": BK[1], "lon": BK[0], "created": "2019-01-01",
         "refreshed": "2026-06-01", "closed": None},
    ]
    out = list(FoursquarePlacesAdapter().normalize(rows))
    assert [r.source_record_id for r in out] == ["x2"]


def test_loading_closures_writes_nothing_into_staging_poi(con):
    before = con.execute("SELECT count(*) FROM staging.poi").fetchone()[0]
    _closure(con, "f1", "cafe_bakery", "Apollo Bagels", *MN, dt.date(2025, 6, 1))
    pc.apply_to_ledger(con)
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == before
    assert con.execute(
        "SELECT count(*) FROM analysis.poi_dedup").fetchone()[0] == len(BASE)


# ------------------------------------------------------- 2. the join is the rule
def test_a_closure_matches_its_ledger_row_on_the_minted_key(con):
    pp.snapshot(con, month="2026-09", today=TODAY)
    _closure(con, "f1", "cafe_bakery", "Apollo Bagels", *MN, dt.date(2025, 6, 1))
    rep = pc.apply_to_ledger(con)
    assert rep["written"] == 1
    row = con.execute(
        "SELECT closed_on, closed_src FROM analysis.poi_presence "
        "WHERE display_name = 'Apollo Bagels'").fetchone()
    assert row == (dt.date(2025, 6, 1), "foursquare:key")


def test_a_different_category_at_the_same_point_is_not_closed(con):
    """The key carries the category, and so does the link. A bakery closing
    must never close the hardware store at the same coordinate."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    _closure(con, "f1", "hardware", "Apollo Bagels", *MN, dt.date(2025, 6, 1))
    rep = pc.apply_to_ledger(con)
    assert rep["written"] == 0


def test_a_neighbouring_storefront_is_never_closed_by_a_name_that_does_not_match(con):
    """Same category, 5 m away, unrelated name -> no match. Widening the link
    past `names_match` is the fusing-distinct-storefronts bug, which here would
    manufacture a closure that never happened."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    _closure(con, "f1", "cafe_bakery", "Unrelated Patisserie",
             MN[0] + 0.00005, MN[1], dt.date(2025, 6, 1))
    assert pc.apply_to_ledger(con)["written"] == 0


def test_a_coordinate_that_rounds_across_the_key_boundary_is_carried_by_the_link(con):
    """~8 m away, same name and category: the hash cannot match, the dedup's own
    name+distance rule can. That is sql/018 pass B, reused."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    _closure(con, "f1", "cafe_bakery", "Apollo Bagels",
             MN[0] + 0.0001, MN[1] + 0.0001, dt.date(2025, 6, 1))
    rep = pc.apply_to_ledger(con)
    assert rep["written"] == 1
    assert con.execute(
        "SELECT closed_src FROM analysis.poi_presence "
        "WHERE display_name = 'Apollo Bagels'").fetchone()[0] == "foursquare:link"


def test_a_nameless_closure_cannot_match_and_says_so(con):
    """`mint_key` folds the canonical poi_id in when the normalized name is
    empty (sql/018 caveat 6) and a closure has no poi_id; `names_match` refuses
    an empty token set. Such a row is LOADED and counted, never matched."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    _closure(con, "f1", "cafe_bakery", "龍康", *MN, dt.date(2025, 6, 1),
             key=False)
    assert pc.apply_to_ledger(con)["written"] == 0
    assert con.execute(f"SELECT count(*) FROM {pc.TABLE}").fetchone()[0] == 1


# ---------------------------------------------------------- 3. precedence
def test_absence_from_a_snapshot_is_not_a_closure(con):
    """D79. The hardware store vanishes from the warehouse in October; its
    `last_seen_month` falls behind and `closed_on` stays NULL, because only a
    source-published date_closed closes a location."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    con.execute("DELETE FROM analysis.poi_dedup WHERE poi_id = 'b1'")
    con.execute("DELETE FROM staging.poi WHERE poi_id = 'b1'")
    pp.snapshot(con, month="2026-10", today=dt.date(2026, 10, 14))
    row = con.execute(
        "SELECT last_seen_month, closed_on, closed_src FROM analysis.poi_presence "
        "WHERE display_name = 'Zanzibar Hardware'").fetchone()
    assert row == ("2026-09", None, None)


def test_a_source_date_closed_beats_absence(con):
    """The same disappearance, but this time a source published a date. THAT
    closes it -- and the date is the source's, not the month it vanished."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    _closure(con, "f9", "hardware", "Zanzibar Hardware", *BK, dt.date(2026, 2, 11))
    con.execute("DELETE FROM analysis.poi_dedup WHERE poi_id = 'b1'")
    con.execute("DELETE FROM staging.poi WHERE poi_id = 'b1'")
    pp.snapshot(con, month="2026-10", today=dt.date(2026, 10, 14))
    row = con.execute(
        "SELECT last_seen_month, closed_on, closed_src FROM analysis.poi_presence "
        "WHERE display_name = 'Zanzibar Hardware'").fetchone()
    assert row == ("2026-09", dt.date(2026, 2, 11), "foursquare:key")


def test_the_earliest_closure_wins_when_two_land_on_one_row(con):
    """Conservative direction: it can only shorten an observed spell."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    _closure(con, "f1", "cafe_bakery", "Apollo Bagels", *MN, dt.date(2025, 6, 1))
    _closure(con, "f2", "cafe_bakery", "Apollo Bagels",
             MN[0] + 0.0001, MN[1], dt.date(2024, 2, 2))
    pc.apply_to_ledger(con)
    assert con.execute(
        "SELECT closed_on FROM analysis.poi_presence "
        "WHERE display_name = 'Apollo Bagels'").fetchone()[0] == dt.date(2024, 2, 2)


def test_poi_snapshot_fills_the_closure_columns_and_is_idempotent(con):
    _closure(con, "f1", "cafe_bakery", "Apollo Bagels", *MN, dt.date(2025, 6, 1))
    r1 = pp.snapshot(con, month="2026-09", today=TODAY)
    assert r1.closures["written"] == 1
    r2 = pp.snapshot(con, month="2026-09", today=TODAY)
    assert r2.closures["written"] == 1
    assert con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE closed_on IS NOT NULL"
    ).fetchone()[0] == 1


def test_a_retracted_closure_disappears_on_the_next_snapshot(con):
    """`apply_to_ledger` re-derives both columns rather than accumulating them,
    so a closure a later release retracts is not frozen into the ledger."""
    _closure(con, "f1", "cafe_bakery", "Apollo Bagels", *MN, dt.date(2025, 6, 1))
    pp.snapshot(con, month="2026-09", today=TODAY)
    con.execute(f"DELETE FROM {pc.TABLE}")
    pp.snapshot(con, month="2026-09", today=TODAY)
    assert con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE closed_on IS NOT NULL"
    ).fetchone()[0] == 0


def test_the_reporting_view_exposes_closed_on(con):
    _closure(con, "f1", "cafe_bakery", "Apollo Bagels", *MN, dt.date(2025, 6, 1))
    pp.snapshot(con, month="2026-09", today=TODAY)
    row = con.execute(
        "SELECT closed_on, closed_src, is_closed FROM analysis.poi_first_seen "
        "WHERE display_name = 'Apollo Bagels'").fetchone()
    assert row == (dt.date(2025, 6, 1), "foursquare:key", True)


def test_check_presence_invariants_still_hold_with_closures(con):
    _closure(con, "f1", "cafe_bakery", "Apollo Bagels", *MN, dt.date(2025, 6, 1))
    pp.snapshot(con, month="2026-09", today=TODAY)
    errors, stats = pp.coverage_check(con)
    assert errors == []
    assert stats["coverage_pct"] == 100.0
