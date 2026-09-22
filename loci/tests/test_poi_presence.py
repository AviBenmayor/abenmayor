"""The first-seen ledger (`analysis.poi_presence`, model/poi_presence.py).

The fixture builds the two objects the ledger reads -- staging.poi and
analysis.poi_dedup -- at the real warehouse's grain, so the SQL under test is
the SQL that runs in production.

What is asserted, in order of how badly a regression would hurt:

  1. IDEMPOTENCE. Re-running a month must not move `first_seen_month` and must
     not double-count `n_months_seen`. A ledger that drifts on a re-run is
     worse than no ledger: every later "opened in month X" is then wrong and
     nothing says so.
  2. THE THREE KINDS. 'backfill_censored' only ever at the ledger's first
     month; 'observed' for a location that genuinely appears later; and
     'source_date' whenever a source dates it -- including the one-way upgrade
     of a censored row a source finally dates.
  3. A CENSORED ROW IS NOT AN OPENING. `analysis.poi_first_seen` must return
     NULL for its first_seen_month, because that is the only guard against
     reporting the entire backfill as openings in the ledger's first month.
  4. `last_inspection_date` IS NEVER A FIRST-SEEN. Same trap as
     tests/test_chains_detect.py, asserted here too because FIRST_SEEN_FIELDS
     now lives in this module.
  5. KEY STABILITY. A cluster that keeps its identity but gets renumbered by a
     dedup re-run must keep its ledger row; two distinct storefronts that
     collide on the minted key must NOT be fused.
  6. FAIL LOUD. An empty poi_dedup raises instead of writing an empty month.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from loci import db as locidb
from loci.model import poi_presence as pp

TODAY = dt.date(2026, 9, 13)
LATER = dt.date(2026, 10, 14)

MN = (-73.9857, 40.7484)
BK = (-73.9903, 40.6906)


def _poi(pid, source, name, category, lon, lat, cluster, *,
         opened=None, attrs=None, canonical=True):
    return {"poi_id": pid, "source_id": source, "name": name, "category": category,
            "lon": lon, "lat": lat, "cluster_id": cluster, "opened_on": opened,
            "attrs": json.dumps(attrs or {}), "is_canonical": canonical}


BASE = [
    # dated by a source (FSQ opened_on)
    _poi("a1", "foursquare_os_places", "Apollo Bagels", "cafe_bakery", *MN, 1,
         opened="2025-03-04"),
    # undated: Overture only -> censored at backfill
    _poi("b1", "overture_places", "Zanzibar Hardware", "hardware", *BK, 2),
    # a two-source cluster, only the non-canonical member carries the date
    _poi("c1", "nyc_dohmh_restaurants", "Old Diner", "restaurant", *MN, 3,
         attrs={"last_inspection_date": "2026-08-01"}),
    _poi("c2", "foursquare_os_places", "Old Diner", "restaurant", *MN, 3,
         opened="2011-06-01", canonical=False),
    # the DOS MM/DD/YYYY path
    _poi("d1", "nys_dos_appearance_enhancement", "Glow Nails Inc", "nails_beauty",
         *BK, 4, attrs={"license_issue_date": "08/14/2026"}),
]


def _make(con, rows):
    con.execute("DELETE FROM analysis.poi_dedup")
    con.execute("DELETE FROM staging.poi")
    for r in rows:
        con.execute(
            "INSERT INTO staging.poi (poi_id, source_id, category, tier, name, geom, "
            "opened_on, attrs) VALUES (?,?,?,1,?,ST_Point(?,?),CAST(? AS DATE),"
            "CAST(? AS JSON))",
            [r["poi_id"], r["source_id"], r["category"], r["name"],
             r["lon"], r["lat"], r["opened_on"], r["attrs"]])
        con.execute("INSERT INTO analysis.poi_dedup VALUES (?,?,?,?)",
                    [r["poi_id"], r["cluster_id"], r["is_canonical"], r["category"]])


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
    c.execute("CREATE TABLE analysis.hex (h3_index VARCHAR PRIMARY KEY, "
              "borough VARCHAR)")
    for lon, lat, boro in ((*MN, "Manhattan"), (*BK, "Brooklyn")):
        c.execute("INSERT OR IGNORE INTO analysis.hex "
                  "SELECT h3_latlng_to_cell_string(?, ?, 9), ?", [lat, lon, boro])
    _make(c, BASE)
    pp.ensure_schema(c)
    return c


def _ledger(con):
    return {r[0]: r for r in con.execute(
        "SELECT display_name, first_seen_kind, first_seen_month, last_seen_month, "
        "n_months_seen, first_seen_src_date, location_key "
        "FROM analysis.poi_presence").fetchall()}


# ------------------------------------------------------------------ the kinds
def test_backfill_marks_undated_locations_left_censored(con):
    r = pp.snapshot(con, month="2026-09", today=TODAY)
    assert r.n_locations == 4                      # 5 POI rows, 4 clusters
    led = _ledger(con)
    assert led["Zanzibar Hardware"][1] == "backfill_censored"
    assert led["Apollo Bagels"][1] == "source_date"
    assert led["Glow Nails Inc"][1] == "source_date"
    # the date lives on the NON-canonical member and must still be found
    assert led["Old Diner"][1] == "source_date"
    assert led["Old Diner"][5] == dt.date(2011, 6, 1)


def test_a_censored_row_never_reports_an_opening_month(con):
    """The guard. `first_seen_month` on the table is '2026-09' so the last-seen
    arithmetic has an anchor, but the VIEW -- the reporting surface every
    consumer reads -- must return NULL."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    raw, view, censored = con.execute("""
        SELECT (SELECT first_seen_month FROM analysis.poi_presence
                WHERE display_name = 'Zanzibar Hardware'),
               (SELECT first_seen_month FROM analysis.poi_first_seen
                WHERE display_name = 'Zanzibar Hardware'),
               (SELECT is_left_censored FROM analysis.poi_first_seen
                WHERE display_name = 'Zanzibar Hardware')""").fetchone()
    assert raw == "2026-09"
    assert view is None
    assert censored is True
    # and nothing in the view claims a September opening
    assert con.execute("SELECT count(*) FROM analysis.poi_first_seen "
                       "WHERE first_seen_month = '2026-09'").fetchone()[0] == 0


def test_a_location_appearing_after_the_backfill_is_observed_not_censored(con):
    pp.snapshot(con, month="2026-09", today=TODAY)
    _make(con, BASE + [
        _poi("e1", "overture_places", "Newcomer Laundromat", "laundry", *BK, 9)])
    r = pp.snapshot(con, month="2026-10", today=LATER)
    assert r.n_new == 1
    led = _ledger(con)
    assert led["Newcomer Laundromat"][1] == "observed"
    assert led["Newcomer Laundromat"][2] == "2026-10"
    # and the view DOES report it, because October is a real observation
    assert con.execute("SELECT first_seen_month FROM analysis.poi_first_seen "
                       "WHERE display_name = 'Newcomer Laundromat'").fetchone()[0] \
        == "2026-10"


def test_a_source_date_upgrades_a_censored_row_one_way(con):
    """Censoring may only ever shrink. When a feed finally publishes an open
    date for a location we could only censor, the kind becomes 'source_date'
    -- and `ledger_started_month` still records when we first held the row."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    rows = [dict(r) for r in BASE]
    for r in rows:
        if r["poi_id"] == "b1":
            r["opened_on"] = "2018-02-01"
    _make(con, rows)
    r = pp.snapshot(con, month="2026-10", today=LATER)
    assert r.upgraded == 1
    kind, month, started = con.execute(
        "SELECT first_seen_kind, first_seen_month, ledger_started_month "
        "FROM analysis.poi_presence WHERE display_name = 'Zanzibar Hardware'"
    ).fetchone()
    assert (kind, month, started) == ("source_date", "2018-02", "2026-09")


def test_last_inspection_date_is_never_a_first_seen_field():
    """Same trap as chains/detect.py, asserted where the list now lives: it is
    a LAST-seen date, and reading it as a first-seen would date every
    long-established restaurant to its most recent inspection."""
    blob = " ".join(expr for expr, _ in pp.FIRST_SEEN_FIELDS)
    assert "last_inspection" not in blob
    assert "last_inspection" not in " ".join(label for _, label in pp.FIRST_SEEN_FIELDS)


def test_a_future_source_date_is_refused(con):
    """A source date after today is a data error, not an opening. Taking it
    would let a location claim it opened after we saw it."""
    rows = [dict(r) for r in BASE]
    for r in rows:
        if r["poi_id"] == "b1":
            r["opened_on"] = "2030-01-01"
    _make(con, rows)
    pp.snapshot(con, month="2026-09", today=TODAY)
    kind, = con.execute("SELECT first_seen_kind FROM analysis.poi_presence "
                        "WHERE display_name = 'Zanzibar Hardware'").fetchone()
    assert kind == "backfill_censored"


# ------------------------------------------------------------- idempotence
def test_rerunning_a_month_changes_nothing(con):
    pp.snapshot(con, month="2026-09", today=TODAY)
    before = _ledger(con)
    r2 = pp.snapshot(con, month="2026-09", today=TODAY)
    after = _ledger(con)
    assert before == after
    assert r2.n_new == 0
    assert all(v[4] == 1 for v in after.values())       # n_months_seen still 1


def test_a_second_month_advances_last_seen_but_not_first_seen(con):
    pp.snapshot(con, month="2026-09", today=TODAY)
    pp.snapshot(con, month="2026-10", today=LATER)
    led = _ledger(con)
    hw = led["Zanzibar Hardware"]
    assert hw[2] == "2026-09"        # first_seen_month pinned
    assert hw[3] == "2026-10"        # last_seen_month advanced
    assert hw[4] == 2                # n_months_seen incremented exactly once
    # and re-running October is still a no-op
    pp.snapshot(con, month="2026-10", today=LATER)
    assert _ledger(con)["Zanzibar Hardware"][4] == 2


def test_a_location_that_disappears_keeps_its_history_and_loses_its_cluster_id(con):
    pp.snapshot(con, month="2026-09", today=TODAY)
    _make(con, [r for r in BASE if r["poi_id"] != "b1"])
    r = pp.snapshot(con, month="2026-10", today=LATER)
    assert r.n_gone == 1
    row = con.execute(
        "SELECT last_seen_month, cluster_id_latest, n_months_seen "
        "FROM analysis.poi_presence WHERE display_name = 'Zanzibar Hardware'"
    ).fetchone()
    # A stale cluster_id is worse than none: it would attach October's dedup
    # numbering to a storefront we did not see in October.
    assert row == ("2026-09", None, 1)


def test_an_out_of_order_month_is_refused_without_force(con):
    pp.snapshot(con, month="2026-10", today=LATER)
    with pytest.raises(ValueError, match="refusing to snapshot"):
        pp.snapshot(con, month="2026-09", today=TODAY)


# ------------------------------------------------------------- key stability
def test_a_dedup_renumbering_does_not_lose_a_location(con):
    """cluster_id is renumbered by every dedup re-run (sql/018). The ledger's
    identity must survive that -- otherwise every location would look brand new
    the first month after a re-dedup, and 227k fake openings would be
    reported."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    keys_before = {k for _, _, _, _, _, _, k in _ledger(con).values()}
    renumbered = [dict(r, cluster_id=r["cluster_id"] + 5000) for r in BASE]
    _make(con, renumbered)
    r = pp.snapshot(con, month="2026-10", today=LATER)
    assert r.n_new == 0
    assert r.n_gone == 0
    assert {k for _, _, _, _, _, _, k in _ledger(con).values()} == keys_before


def test_a_same_month_reingest_does_not_fuse_cluster_ids(con):
    """D138 REGRESSION. A full source re-ingest can be re-run for the SAME
    calendar month (e.g. twice in one September) and reshuffle integer
    `cluster_id`s in the process. If a location drops out entirely (its
    source ids shuffled away) and a fresh dedup run reuses ITS OLD integer
    for a completely different storefront, the old `last_seen_month < month`
    stale-nulling guard was a no-op -- the departed row's `last_seen_month`
    already equalled `month` from the earlier run this same month, so it
    never got NULLed, and `coverage_check` found two ledger rows (two
    distinct histories) both claiming one live `cluster_id`. This is exactly
    the 94-row fusion the D137 brewery re-run's `poi-snapshot` hit."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    zanzibar_cluster = next(r["cluster_id"] for r in BASE if r["poi_id"] == "b1")

    # Simulate the re-ingest: Zanzibar Hardware's source ids are gone (as a
    # full re-ingest can shuffle away), and dedup's fresh numbering reuses
    # its OLD integer cluster_id for an unrelated new storefront.
    reingested = [r for r in BASE if r["poi_id"] != "b1"] + [
        _poi("shuffled1", "overture_places", "Fresh Arrival Clinic", "clinic",
             *MN, zanzibar_cluster)]
    _make(con, reingested)

    # Re-run for the SAME month, as the D137 addendum's same-day re-run did.
    pp.snapshot(con, month="2026-09", today=TODAY)

    errors, stats = pp.coverage_check(con)
    assert errors == [], errors
    assert stats["uncovered_clusters"] == 0

    zanzibar_row = con.execute(
        "SELECT cluster_id_latest FROM analysis.poi_presence "
        "WHERE display_name = 'Zanzibar Hardware'").fetchone()
    assert zanzibar_row == (None,)          # split off, never fused

    clinic_row = con.execute(
        "SELECT cluster_id_latest FROM analysis.poi_presence "
        "WHERE display_name = 'Fresh Arrival Clinic'").fetchone()
    assert clinic_row == (zanzibar_cluster,)  # the fresh owner keeps its own id

    dupes = con.execute(
        "SELECT cluster_id_latest FROM analysis.poi_presence "
        "WHERE cluster_id_latest IS NOT NULL GROUP BY 1 HAVING count(*) > 1"
    ).fetchall()
    assert dupes == []


def test_a_small_coordinate_move_is_carried_by_the_name_link(con):
    """Enough to cross the 4-dp rounding boundary the minted key uses, well
    inside dedup's 40 m match radius. The hash alone would mint a new key; the
    name+distance link is what stops that."""
    pp.snapshot(con, month="2026-09", today=TODAY)
    moved = [dict(r, lat=r["lat"] + 0.00012, lon=r["lon"] + 0.00012,
                  cluster_id=r["cluster_id"] + 900) for r in BASE]
    _make(con, moved)
    r = pp.snapshot(con, month="2026-10", today=LATER)
    assert (r.n_new, r.n_gone) == (0, 0)
    assert r.n_matched_link >= 1


def test_two_nameless_storefronts_at_one_coordinate_are_never_fused(con):
    """The measured collision population is entirely POIs whose name
    normalizes to nothing -- CJK and Arabic shopfront names (`norm_tokens`
    keeps only [a-z0-9]) and all-generic names like "Chicken Kitchen" -- often
    sharing a fallback geocode. `mint_key` folds the canonical poi_id in for
    exactly those rows. Fusing them would delete a real storefront and
    manufacture a retail gap."""
    rows = BASE + [
        _poi("z1", "overture_places", "\u4e2d\u6587\u540d", "restaurant", *MN, 77),
        _poi("z2", "overture_places", "\u0645\u0637\u0639\u0645", "restaurant", *MN, 78),
    ]
    _make(con, rows)
    r = pp.snapshot(con, month="2026-09", today=TODAY)
    assert r.n_locations == 6
    assert r.hash_collisions == 0            # disambiguated by content, not by a suffix
    n, k = con.execute("SELECT count(*), count(DISTINCT location_key) "
                       "FROM analysis.poi_presence").fetchone()
    assert (n, k) == (6, 6)


def test_nameless_colliders_are_idempotent_across_runs(con):
    """REGRESSION. The first implementation disambiguated a collision with a
    positional '-2' suffix, which depended on which collider was processed
    first. On the live warehouse the second snapshot therefore minted 63
    duplicate rows for locations it already held, and two ledger rows ended up
    claiming one cluster -- caught by coverage_check, which is why that
    assertion exists. Re-running a month must mint nothing."""
    rows = BASE + [
        _poi("z1", "overture_places", "\u4e2d\u6587\u540d", "restaurant", *MN, 77),
        _poi("z2", "overture_places", "\u0645\u0637\u0639\u0645", "restaurant", *MN, 78),
    ]
    _make(con, rows)
    pp.snapshot(con, month="2026-09", today=TODAY)
    before = _ledger(con)
    r2 = pp.snapshot(con, month="2026-09", today=TODAY)
    assert (r2.n_new, r2.n_gone) == (0, 0)
    assert _ledger(con) == before
    errors, _ = pp.coverage_check(con)
    assert errors == []
    # and a real second month still carries them forward, not re-mints them
    r3 = pp.snapshot(con, month="2026-10", today=LATER)
    assert (r3.n_new, r3.n_gone) == (0, 0)
    assert pp.coverage_check(con)[0] == []


def test_a_named_location_does_not_hash_its_poi_id(con):
    """The poi_id clause must apply ONLY to nameless rows. A named location's
    key has to survive its canonical member changing -- which is the ordinary
    case when a registry feed lands and outranks an aggregator."""
    a = pp.mint_key("restaurant", "apollo", -73.9857, 40.7484, "poi-1")
    b = pp.mint_key("restaurant", "apollo", -73.9857, 40.7484, "poi-2")
    assert a == b
    c = pp.mint_key("restaurant", "", -73.9857, 40.7484, "poi-1")
    d = pp.mint_key("restaurant", "", -73.9857, 40.7484, "poi-2")
    assert c != d


# ------------------------------------------------------------------ the guard
def test_an_empty_dedup_raises_instead_of_writing_an_empty_month(con):
    con.execute("DELETE FROM analysis.poi_dedup")
    with pytest.raises(RuntimeError, match="poi_dedup is empty"):
        pp.snapshot(con, month="2026-09", today=TODAY)


def test_coverage_check_passes_after_a_snapshot_and_fails_before_one(con):
    errors, _ = pp.coverage_check(con)
    assert errors and "no ledger row" in errors[0]
    pp.snapshot(con, month="2026-09", today=TODAY)
    errors, stats = pp.coverage_check(con)
    assert errors == []
    assert stats["coverage_pct"] == 100.0
    assert stats["uncovered_clusters"] == 0


def test_coverage_check_catches_an_ingest_without_a_snapshot(con):
    pp.snapshot(con, month="2026-09", today=TODAY)
    _make(con, BASE + [
        _poi("n1", "overture_places", "Fresh Arrival Clinic", "clinic", *MN, 61)])
    errors, stats = pp.coverage_check(con)
    assert errors and "1 of 5" in errors[0]
    assert stats["uncovered_clusters"] == 1


def test_dry_run_writes_nothing(con):
    r = pp.snapshot(con, month="2026-09", dry_run=True, today=TODAY)
    assert r.n_locations == 4 and r.dry_run
    assert con.execute("SELECT count(*) FROM analysis.poi_presence").fetchone()[0] == 0
