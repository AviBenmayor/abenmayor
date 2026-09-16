"""`loci chains detect` against a synthetic warehouse.

The fixture builds the three objects detect reads -- staging.poi,
analysis.poi_dedup, analysis.poi_supply, analysis.hex -- at the same grain the
real warehouse uses, so the SQL under test is the SQL that runs in production.

What is asserted, in order of how badly a regression would hurt:

  1. DEDUP: two sources carrying the same storefront are ONE location. Without
     this a chain's count is its source count, not its store count.
  2. The FLOOR is published: `locations_dated` must equal the number of
     locations that actually carry a date, or `locations_new_12m` reads as a
     measurement instead of a lower bound.
  3. `last_inspection_date` is NOT read as a first-seen. A long-established
     restaurant inspected last month must not count as new.
  4. The flag rule fires on both arms and on NEITHER for a flat brand --
     the regression that once flagged all 26,151 brands was `apply()`
     coercing a returned None to NaN.
  5. The month is idempotent: re-running replaces, never duplicates.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from loci import db as locidb
from loci.chains import detect
from loci.model import poi_presence

TODAY = dt.date(2026, 9, 13)
RECENT = (TODAY - dt.timedelta(days=30)).isoformat()      # inside 3m and 12m
MIDYEAR = (TODAY - dt.timedelta(days=200)).isoformat()    # inside 12m only
OLD = "2015-04-02"                                        # outside both


def _poi(pid, source, name, category, lon, lat, cluster, *,
         opened=None, attrs=None, canonical=True):
    return {"poi_id": pid, "source_id": source, "name": name, "category": category,
            "lon": lon, "lat": lat, "cluster_id": cluster, "opened_on": opened,
            "attrs": json.dumps(attrs or {}), "is_canonical": canonical}


#: One storefront per cluster_id. Coordinates are inside a single H3 res-9 cell
#: per borough so the borough join is exercised without a real grid.
MN = (-73.9857, 40.7484)
BK = (-73.9903, 40.6906)

ROWS = [
    # --- fastbrand: 4 locations, 3 of them dated inside 12m -> FLAG_NEW_12M
    _poi("a1", "foursquare_os_places", "FastBrand #101", "cafe_bakery", *MN, 1,
         opened=RECENT),
    _poi("a2", "overture_places", "FastBrand", "cafe_bakery", *MN, 1,
         canonical=False),                       # same storefront, second source
    _poi("a3", "foursquare_os_places", "FastBrand - Williamsburg", "cafe_bakery",
         *BK, 2, opened=RECENT),
    _poi("a4", "foursquare_os_places", "FASTBRAND LLC", "cafe_bakery", *BK, 3,
         opened=MIDYEAR),
    _poi("a5", "overture_places", "FastBrand", "cafe_bakery", *MN, 4),   # undated

    # --- smallbrand: 3 locations, 2 new -> FLAG_FAST_SMALL
    _poi("b1", "foursquare_os_places", "SmallBrand", "fitness", *MN, 5, opened=RECENT),
    _poi("b2", "foursquare_os_places", "SmallBrand", "fitness", *BK, 6, opened=MIDYEAR),
    _poi("b3", "overture_places", "SmallBrand", "fitness", *BK, 7, opened=OLD),

    # --- flatbrand: 3 old locations -> NOT flagged
    _poi("c1", "foursquare_os_places", "FlatBrand", "grocery", *MN, 8, opened=OLD),
    _poi("c2", "foursquare_os_places", "FlatBrand", "grocery", *BK, 9, opened=OLD),
    _poi("c3", "foursquare_os_places", "FlatBrand", "grocery", *BK, 10, opened=OLD),

    # --- oldrestaurant: inspected last month but open since forever. The
    #     last_inspection_date trap: reading it as a first-seen flags it.
    _poi("d1", "nyc_dohmh_restaurants", "Old Diner", "restaurant", *MN, 11,
         attrs={"last_inspection_date": RECENT}),
    _poi("d2", "nyc_dohmh_restaurants", "Old Diner", "restaurant", *BK, 12,
         attrs={"last_inspection_date": RECENT}),
    _poi("d3", "nyc_dohmh_restaurants", "Old Diner", "restaurant", *BK, 13,
         attrs={"last_inspection_date": RECENT}),

    # --- salon: the DOS license_issue_date path (MM/DD/YYYY in attrs)
    _poi("e1", "nys_dos_appearance_enhancement", "Glow Nails Inc", "nails_beauty",
         *MN, 14, attrs={"license_issue_date": "08/14/2026"}),
    _poi("e2", "nys_dos_appearance_enhancement", "GLOW NAILS", "nails_beauty",
         *BK, 15, attrs={"license_issue_date": "07/02/2026"}),

    # --- a lone storefront: below MIN_LOCATIONS, must not appear at all
    _poi("f1", "overture_places", "One Off Deli", "convenience", *MN, 16),

    # --- junk name: must produce no brand
    _poi("g1", "nyc_dcwp_inspections", "PARADISELAUNDROMATNY@GMAIL.COM", "laundry",
         *BK, 17),
    _poi("g2", "nyc_dcwp_inspections", "PARADISELAUNDROMATNY@GMAIL.COM", "laundry",
         *MN, 18),
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
    c.execute("CREATE TABLE analysis.hex (h3_index VARCHAR PRIMARY KEY, "
              "borough VARCHAR)")

    for r in ROWS:
        c.execute(
            "INSERT INTO staging.poi (poi_id, source_id, category, tier, name, geom, "
            "opened_on, attrs) VALUES (?,?,?,1,?,ST_Point(?,?),CAST(? AS DATE),CAST(? AS JSON))",
            [r["poi_id"], r["source_id"], r["category"], r["name"],
             r["lon"], r["lat"], r["opened_on"], r["attrs"]])
        c.execute("INSERT INTO analysis.poi_dedup VALUES (?,?,?,?)",
                  [r["poi_id"], r["cluster_id"], r["is_canonical"], r["category"]])

    c.execute("""CREATE VIEW analysis.poi_supply AS
                 SELECT p.poi_id, p.source_id, p.category, p.name, p.geom, d.cluster_id
                 FROM staging.poi p JOIN analysis.poi_dedup d USING (poi_id)
                 WHERE d.is_canonical""")
    for lon, lat, boro in ((*MN, "Manhattan"), (*BK, "Brooklyn")):
        c.execute("INSERT OR IGNORE INTO analysis.hex "
                  "SELECT h3_latlng_to_cell_string(?, ?, 9), ?", [lat, lon, boro])
    detect.ensure_schema(c)
    # detect now reads first-seen from the LEDGER, never from the sources
    # directly, so the fixture has to run the snapshot the monthly job runs
    # before it. This is the integration, not a mock.
    poi_presence.snapshot(c, month="2026-09", today=TODAY)
    return c


def _by_key(rows):
    return {r["brand_key"]: r for r in rows}


def test_dedup_one_storefront_two_sources_is_one_location(con):
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    fast = _by_key(rows)["fastbrand"]
    # 5 POI rows, 4 clusters -- the Overture/FSQ pair is one storefront.
    assert fast["locations_total"] == 4
    assert fast["n_sources"] == 2


def test_dated_subset_is_published_beside_the_growth_count(con):
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    fast = _by_key(rows)["fastbrand"]
    assert fast["locations_dated"] == 3        # a5's cluster carries no date
    assert fast["locations_new_12m"] == 3
    assert fast["locations_new_3m"] == 2
    assert fast["locations_dated"] <= fast["locations_total"]


def test_last_inspection_date_is_never_read_as_a_first_seen(con):
    """The trap: DOHMH's only date is the LAST inspection. Reading it as a
    first-seen would date every established restaurant to last month and label
    the entire food tier a new chain."""
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    diner = _by_key(rows)["old diner"]
    assert diner["locations_dated"] == 0
    assert diner["locations_new_12m"] == 0
    assert diner["flagged"] is False


def test_license_issue_date_is_read_as_a_first_seen(con):
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    glow = _by_key(rows)["glow nails"]
    assert glow["locations_total"] == 2
    assert glow["locations_dated"] == 2
    assert glow["locations_new_12m"] == 2


@pytest.mark.parametrize("new_12m,total,expect", [
    (3, 400, True),      # absolute arm
    (2, 8, True),        # fast-small arm
    (2, 9, False),       # ... which does not fire above the size cut
    (0, 2, False),
    (1, 3, False),
])
def test_flag_rule_arms(new_12m, total, expect):
    assert (detect.flag_for(new_12m, total) is not None) is expect


def test_a_flat_brand_is_not_flagged(con):
    """Regression: DataFrame.apply coerced a returned None to NaN, and
    `nan is not None` is True, so every brand came back flagged."""
    result, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    by = _by_key(rows)
    assert by["flatbrand"]["flagged"] is False
    assert by["fastbrand"]["flagged"] is True
    assert by["smallbrand"]["flagged"] is True
    assert result.n_flagged < result.n_brands


def test_singletons_and_junk_names_never_become_brands(con):
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    keys = _by_key(rows)
    assert "one off deli" not in keys          # below MIN_LOCATIONS
    assert not any("gmail" in k for k in keys)  # junk name -> no brand


def test_boroughs_and_category_join_key(con):
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    fast = _by_key(rows)["fastbrand"]
    assert fast["boroughs"] == "Brooklyn,Manhattan"
    assert fast["n_boroughs"] == 2
    assert fast["loci_category"] == "cafe_bakery"   # the recommend-card join key


def test_writing_a_month_is_idempotent(con):
    detect.build(con, month="2026-09", today=TODAY)
    first = con.execute("SELECT count(*) FROM chains.brand_snapshot").fetchone()[0]
    detect.build(con, month="2026-09", today=TODAY)
    again = con.execute("SELECT count(*) FROM chains.brand_snapshot").fetchone()[0]
    assert first == again > 0
    assert con.execute("SELECT count(DISTINCT snapshot_month) "
                       "FROM chains.brand_snapshot").fetchone()[0] == 1


def test_brand_latest_delta_needs_two_snapshots(con):
    detect.build(con, month="2026-08", today=TODAY)
    row = con.execute("SELECT months_observed, locations_delta_since "
                      "FROM chains.brand_latest WHERE brand_key = 'fastbrand'").fetchone()
    assert row == (1, None), "one snapshot cannot yield a delta; NULL, never 0"

    detect.build(con, month="2026-09", today=TODAY)
    months, delta = con.execute(
        "SELECT months_observed, locations_delta_since "
        "FROM chains.brand_latest WHERE brand_key = 'fastbrand'").fetchone()
    assert (months, delta) == (2, 0)


def test_bad_month_is_rejected(con):
    with pytest.raises(ValueError, match="YYYY-MM"):
        detect.build(con, month="September 2026", dry_run=True, today=TODAY)


# ---------------------------------------------------------------------------
# the first-seen ledger (GTM / owner 2026-09-13)
# ---------------------------------------------------------------------------
def test_detect_reports_the_three_first_seen_kinds(con):
    """The run summary must split the dated/undated population by HOW it was
    dated. Without the split, `locations_new_12m` reads as a measurement when
    most of its denominator is left-censored backfill."""
    result, _ = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    assert result.n_by_source + result.n_observed + result.n_censored \
        == result.n_locations
    assert result.n_by_source + result.n_observed == result.n_dated
    # at the ledger's first month nothing can be 'observed' -- everything
    # either carries a source date or is left-censored
    assert result.n_observed == 0
    assert result.n_by_source > 0 and result.n_censored > 0


def test_detect_refuses_to_run_without_the_ledger(con):
    """Fail loud. A missing ledger would zero every `locations_dated`, which
    reads as "no chain is growing" -- a finding -- when it means "not
    measured"."""
    con.execute("DROP VIEW analysis.poi_first_seen")
    con.execute("DROP TABLE analysis.poi_presence")
    with pytest.raises(RuntimeError, match="poi_first_seen does not exist"):
        detect.build(con, month="2026-09", dry_run=True, today=TODAY)


def test_detect_never_reads_last_inspection_date_from_the_ledger_either(con):
    """The trap, asserted through the new code path: the ledger is the only
    source of first_seen now, and `last_inspection_date` is not one of its
    fields. Old Diner is inspected this month and must stay undated."""
    from loci.model import poi_presence as pp

    assert "last_inspection" not in " ".join(e for e, _ in pp.FIRST_SEEN_FIELDS)
    kind, month, on = con.execute(
        "SELECT first_seen_kind, first_seen_month, first_seen_on "
        "FROM analysis.poi_first_seen WHERE display_name = 'Old Diner'").fetchone()
    assert (kind, month, on) == ("backfill_censored", None, None)
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    diner = _by_key(rows)["old diner"]
    assert diner["locations_dated"] == 0 and diner["flagged"] is False


def test_brand_location_is_keyed_on_the_ledger_not_on_cluster_id(con):
    """cluster_id is renumbered by every dedup re-run, so the old key made two
    months of chains.brand_location incomparable."""
    detect.build(con, month="2026-09", today=TODAY)
    keys = [r[0] for r in con.execute(
        "SELECT DISTINCT location_key FROM chains.brand_location").fetchall()]
    assert keys and all(k.startswith("loc_") for k in keys)
    ledger = {r[0] for r in con.execute(
        "SELECT location_key FROM analysis.poi_presence").fetchall()}
    assert set(keys) <= ledger


# ===================== the sql/039 derived signals: filings, coverage, press
#
# Three columns whose whole purpose is to keep a ZERO honest (GTM-189, D109).
# `pipeline_filings_12m = 0` means "the filing channel can see this trade and
# saw nothing" for a café and "the filing channel is blind to this trade" for a
# gym, and nothing in the number tells them apart -- `pipeline_coverage` is the
# column that does. So what is asserted here is mostly about the DIFFERENCE
# BETWEEN 0 AND NULL, in both directions.

def _with_pipeline(con, rows):
    """A minimal analysis.storefront_pipeline. `rows` is
    (business_name_key, entry_date, is_open)."""
    con.execute("CREATE TABLE analysis.storefront_pipeline ("
                "business_name_key VARCHAR, entry_date DATE, is_open BOOLEAN)")
    for key, entry, is_open in rows:
        con.execute("INSERT INTO analysis.storefront_pipeline VALUES (?, CAST(? AS DATE), ?)",
                    [key, entry, is_open])


def test_the_twelve_month_window_is_the_snapshots_calendar_months_not_the_clock():
    """Anchored on the snapshot, not on `today`: the month is this table's unit
    of idempotence, so a re-run of 2026-09 next March has to produce the number
    September produced."""
    assert detect.month_window_12m("2026-09") == (dt.date(2025, 10, 1),
                                                  dt.date(2026, 10, 1))
    # ... and the year boundary, in both directions.
    assert detect.month_window_12m("2026-01") == (dt.date(2025, 2, 1),
                                                  dt.date(2026, 2, 1))
    assert detect.month_window_12m("2026-12") == (dt.date(2026, 1, 1),
                                                  dt.date(2027, 1, 1))


def test_filing_real_categories_is_derived_from_the_feed_map_not_typed():
    """The five categories NYC's filing feeds can attribute a licence to. Read
    out of model/filing_categories.yaml, so adding a feed moves it. Pinned here
    so it moving is a VISIBLE event: every `structural_zero` in the warehouse
    depends on this set, and a silent widening would turn blind spots into
    measured zeroes with nobody deciding it."""
    assert detect.filing_real_categories() == frozenset(
        {"restaurant", "bar", "cafe_bakery", "grocery", "pharmacy"})


def test_a_covered_category_counts_filings_inside_the_window(con):
    """ALL filings, open and not-yet-open alike. This measures how much
    paperwork the brand generated; the candidate predicate's `pipeline_open` is
    a different measure and deliberately excludes open rows."""
    _with_pipeline(con, [
        ("fastbrand", "2026-08-01", False),      # in window, not yet open
        ("fastbrand", "2026-01-15", True),       # in window, OPEN -- still counts
        ("fastbrand", "2024-03-01", False),      # older than the window
        ("flatbrand", "2026-09-30", False),      # last day of the snapshot month
    ])
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    by = _by_key(rows)
    assert by["fastbrand"]["pipeline_filings_12m"] == 2
    assert by["flatbrand"]["pipeline_filings_12m"] == 1
    assert by["fastbrand"]["pipeline_coverage"] == "real"


def test_a_brand_the_pipeline_never_names_gets_a_real_zero(con):
    """0 here IS a measurement: the channel can see cafés and this café filed
    nothing. That is exactly why `pipeline_coverage` has to travel with it."""
    _with_pipeline(con, [("someone else", "2026-08-01", False)])
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    fast = _by_key(rows)["fastbrand"]
    assert fast["pipeline_filings_12m"] == 0
    assert fast["pipeline_coverage"] == "real"


def test_a_category_the_feeds_cannot_see_is_marked_structural_zero(con):
    """SmallBrand is a gym. No NYC filing feed carries a trade field that would
    attribute a filing to fitness (GTM-152, D80), so its zero is a blind spot
    and the render prints words instead of the digit."""
    _with_pipeline(con, [("fastbrand", "2026-08-01", False)])
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    small = _by_key(rows)["smallbrand"]
    assert small["loci_category"] == "fitness"
    assert small["pipeline_coverage"] == "structural_zero"
    assert small["pipeline_filings_12m"] == 0, \
        "the count is still measured; it is the COVERAGE that says what it means"
    assert _by_key(rows)["glow nails"]["pipeline_coverage"] == "structural_zero"


def test_a_missing_pipeline_table_leaves_the_count_null_never_zero(con):
    """A warehouse without the filing pipeline is a normal state -- the table
    is built by a separate command. "We did not measure that channel" must not
    be recorded as "that channel saw nothing"; the coverage label is a fact
    about the CATEGORY and survives either way."""
    import pandas as pd

    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    fast = _by_key(rows)["fastbrand"]
    assert pd.isna(fast["pipeline_filings_12m"])
    assert fast["pipeline_coverage"] == "real"


def test_press_hits_are_counted_in_the_same_window(con):
    con.execute(
        "INSERT INTO chains.press_hits VALUES "
        "('fastbrand', 'https://ny.eater.com/1', 'Opening', DATE '2026-08-01', "
        " 's', 0.9, 'q', 'brand', now()), "
        "('fastbrand', 'https://ny.eater.com/2', 'Old news', DATE '2024-02-01', "
        " 's', 0.9, 'q', 'brand', now())")
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    by = _by_key(rows)
    assert by["fastbrand"]["press_hits_12m"] == 1
    assert by["flatbrand"]["press_hits_12m"] == 0, \
        "the table exists and says nothing about this brand — a real zero"


def test_a_missing_press_table_leaves_the_column_null_never_zero(con):
    import pandas as pd

    con.execute("DROP TABLE chains.press_hits")
    _, rows = detect.build(con, month="2026-09", dry_run=True, today=TODAY)
    assert pd.isna(_by_key(rows)["fastbrand"]["press_hits_12m"])


def test_the_signals_survive_the_write_and_reach_brand_latest(con):
    """The columns are only worth anything if they are IN the snapshot: the
    reason a brand was admitted has to be reproducible from the month it was
    admitted in, not re-derived against a press table that has moved since."""
    _with_pipeline(con, [("fastbrand", "2026-08-01", False)])
    con.execute(
        "INSERT INTO chains.press_hits VALUES "
        "('smallbrand', 'https://ny.eater.com/3', 'A gym', DATE '2026-07-01', "
        " 's', 0.9, 'q', 'brand', now())")
    detect.build(con, month="2026-09", today=TODAY)

    got = dict(con.execute(
        "SELECT brand_key, pipeline_filings_12m FROM chains.brand_snapshot"
    ).fetchall())
    assert got["fastbrand"] == 1

    # chains.brand_latest is `SELECT s.*` and DuckDB binds a view's columns at
    # CREATE time -- sql/039 re-creates it for exactly this reason.
    coverage, press = con.execute(
        "SELECT pipeline_coverage, press_hits_12m FROM chains.brand_latest "
        "WHERE brand_key = 'smallbrand'").fetchone()
    assert (coverage, press) == ("structural_zero", 1)


def test_re_running_a_month_rewrites_the_signals_rather_than_duplicating(con):
    """The month is a DELETE+INSERT. This is also the reason the hand-entered
    evidence block lives in watchlist.yaml and not here."""
    detect.build(con, month="2026-09", today=TODAY)
    _with_pipeline(con, [("fastbrand", "2026-08-01", False)])
    detect.build(con, month="2026-09", today=TODAY)
    rows = con.execute("SELECT pipeline_filings_12m FROM chains.brand_snapshot "
                       "WHERE brand_key = 'fastbrand'").fetchall()
    assert rows == [(1,)]
