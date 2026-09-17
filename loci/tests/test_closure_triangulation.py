"""Went-dark triangulation (model/closure_triangulation.py, sql/052).

The rule under test is D79 made mechanical: a stale venue ALONE writes
nothing; a stale venue plus an independent premises signal writes one row
with the kinds that agreed and a date BOUND, never a date. And the table is
staged: nothing here may touch the evidence ledger or poi_status.
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci import db as locidb
from loci.model import closure_triangulation as ct

ASOF = dt.date(2026, 9, 17)
LON, LAT = -73.95, 40.68


def _con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _stale(con, pid, name, category, lon=LON, lat=LAT, refreshed=dt.date(2021, 6, 1)):
    con.execute("""
        INSERT INTO staging.poi_stale (poi_id, source_id, category, tier, name, geom,
            stale_reason, date_refreshed, ingested_at)
        VALUES (?, 'foursquare_os_places', ?, 1, ?, ST_Point(?, ?),
                'refreshed_before_min', ?, now())""",
                [pid, category, name, lon, lat, refreshed])


def _storefront(con, premises, year, vacant, activity, lon=LON, lat=LAT):
    con.execute("""
        INSERT INTO analysis.storefront (storefront_id, premises_id, filing_due_date,
            reporting_year, universe, observed_1231, borough, bbl, nta_code, geom,
            vacant_1231, activity_canonical, source, ingested_at)
        VALUES (?, ?, ?, ?, 'full', ?, 'BK', '3000010001', 'BK0101', ST_Point(?, ?),
                ?, ?, 'test', now())""",
                [f"{premises}-{year}", premises, dt.date(year + 1, 6, 30), year,
                 dt.date(year, 12, 31), lon, lat, vacant, activity])


def _licence(con, nbr, name, category, end, *, event_premises=True, lon=LON, lat=LAT):
    from loci.model.poi_presence import name_key_of
    con.execute("""
        INSERT INTO analysis.licence_event (licence_number, source, category, business_name,
            name_key, bbl, borough, lon, lat, geom, issue_date, end_date, interval_end,
            ended, days_since_issue, successor_checkable, event_business, event_premises,
            at_risk_5y, label_asof, built_at)
        VALUES (?, 'nys_sla_inactive_licenses', ?, ?, ?, '3000010001', 'BK', ?, ?,
                ST_Point(?, ?), DATE '2015-01-01', ?, ?, TRUE, 1000, TRUE, TRUE, ?,
                TRUE, ?, now())""",
                [nbr, category, name, name_key_of(name), lon, lat, lon, lat, end, end,
                 event_premises, ASOF])


def _presence(con, key, name, category, lon=LON, lat=LAT):
    from loci.model.poi_presence import name_key_of
    con.execute("""
        INSERT INTO analysis.poi_presence (location_key, category, name_key, display_name,
            lon, lat, borough, first_seen_month, last_seen_month, first_seen_kind,
            n_months_seen, poi_id_latest, ledger_started_month, last_snapshot_at)
        VALUES (?, ?, ?, ?, ?, ?, 'BK', '2026-08', '2026-09', 'backfill_censored', 2,
                ?, '2026-08', now())""",
                [key, category, name_key_of(name), name, lon, lat, f"poi:{key}"])


def test_a_stale_venue_alone_writes_nothing():
    con = _con()
    _stale(con, "s1", "Lonely Cafe", "cafe_bakery")
    rep = ct.build(con, asof=ASOF)
    assert rep["written"] == 0 and rep["not_written_stale_only"] == 1
    assert ct.validate(con) == []


def test_a_compatible_ll157_flip_corroborates_with_a_bound_not_a_date():
    con = _con()
    _stale(con, "s1", "Corner Bistro", "restaurant", refreshed=dt.date(2021, 3, 1))
    _storefront(con, "P1", 2019, False, "FOOD SERVICES")
    _storefront(con, "P1", 2020, False, "FOOD SERVICES")
    _storefront(con, "P1", 2021, True, "NO BUSINESS ACTIVITY IDENTIFIED")
    rep = ct.build(con, asof=ASOF)
    assert rep["written"] == 1 and rep["by_kinds"] == {"stale,ll157_vacancy_flip": 1}
    row = con.execute("SELECT kinds, n_kinds, flip_premises_id, closed_after, closed_before, "
                      "flip_shared_by, would_flip FROM analysis.closure_triangulation").fetchone()
    assert row[0] == "stale,ll157_vacancy_flip" and row[1] == 2 and row[2] == "P1"
    assert row[3] == dt.date(2020, 12, 31) and row[4] == dt.date(2021, 12, 31)
    assert row[5] == 1 and row[6] is False           # no presence match -> nothing flips


def test_an_incompatible_trade_does_not_corroborate():
    """A bank going dark 10 m from a stale nail salon is not the salon closing."""
    con = _con()
    _stale(con, "s1", "Glam Nails", "nails_beauty")
    _storefront(con, "P1", 2020, False, "FINANCE & INSURANCE")
    _storefront(con, "P1", 2021, True, None)
    rep = ct.build(con, asof=ASOF)
    assert rep["written"] == 0


def test_a_flip_before_the_lookback_does_not_corroborate():
    con = _con()
    _stale(con, "s1", "Corner Bistro", "restaurant", refreshed=dt.date(2023, 12, 1))
    _storefront(con, "P1", 2019, False, "FOOD SERVICES")
    _storefront(con, "P1", 2020, True, None)        # vacant 2020-12-31 < 2022-12-01
    assert ct.build(con, asof=ASOF)["written"] == 0


def test_a_flip_beyond_30m_does_not_corroborate():
    con = _con()
    _stale(con, "s1", "Corner Bistro", "restaurant")
    _storefront(con, "P1", 2020, False, "FOOD SERVICES", lon=LON + 0.0005)   # ~42 m east
    _storefront(con, "P1", 2021, True, None, lon=LON + 0.0005)
    assert ct.build(con, asof=ASOF)["written"] == 0


def test_a_same_name_licence_end_corroborates_and_a_different_name_does_not():
    con = _con()
    _stale(con, "s1", "Corner Bistro", "restaurant")
    _stale(con, "s2", "Other Place", "restaurant", lon=LON + 0.002)
    _licence(con, "L1", "CORNER BISTRO INC", "restaurant", dt.date(2021, 8, 31))
    rep = ct.build(con, asof=ASOF)
    assert rep["by_kinds"] == {"stale,licence_end": 1}
    row = con.execute("SELECT stale_poi_id, licence_number, closed_after, closed_before "
                      "FROM analysis.closure_triangulation").fetchone()
    assert row == ("s1", "L1", None, dt.date(2021, 8, 31))


def test_three_kinds_agree_only_when_the_licence_end_sits_in_the_ll157_window():
    con = _con()
    _stale(con, "s1", "Corner Bistro", "restaurant", refreshed=dt.date(2016, 1, 1))
    _storefront(con, "P1", 2020, False, "FOOD SERVICES")
    _storefront(con, "P1", 2021, True, None)
    # ended 2017: the premises traded on for three more years -> not this closure
    _licence(con, "L1", "CORNER BISTRO", "restaurant", dt.date(2017, 5, 31))
    rep = ct.build(con, asof=ASOF)
    assert rep["by_kinds"] == {"stale,ll157_vacancy_flip": 1}
    assert rep["licence_kind_dropped_as_inconsistent"] == 1
    # now one that ended inside the window
    con.execute("UPDATE analysis.licence_event SET end_date = DATE '2021-03-31', "
                "interval_end = DATE '2021-03-31'")
    rep = ct.build(con, asof=ASOF)
    assert rep["by_kinds"] == {"stale,ll157_vacancy_flip,licence_end": 1}
    row = con.execute("SELECT n_kinds, closed_after, closed_before "
                      "FROM analysis.closure_triangulation").fetchone()
    assert row == (3, dt.date(2020, 12, 31), dt.date(2021, 12, 31))
    assert ct.validate(con) == []


def test_would_flip_names_the_presence_match_and_never_writes_evidence():
    con = _con()
    _stale(con, "s1", "Corner Bistro", "restaurant")
    _storefront(con, "P1", 2020, False, "FOOD SERVICES")
    _storefront(con, "P1", 2021, True, None)
    _presence(con, "loc1", "Corner Bistro", "restaurant")
    before = con.execute("SELECT count(*) FROM analysis.poi_closure_evidence").fetchone()[0]
    rep = ct.build(con, asof=ASOF)
    assert rep["would_flip_poi_status"] == 1 and rep["would_flip_from_unknown"] == 1
    row = con.execute("SELECT matched_location_key, matched_poi_id, matched_status_now, "
                      "would_flip FROM analysis.closure_triangulation").fetchone()
    assert row[0] == "loc1" and row[1] == "poi:loc1" and row[3] is True
    after = con.execute("SELECT count(*) FROM analysis.poi_closure_evidence").fetchone()[0]
    assert before == after == 0


def test_one_flip_shared_by_several_stale_venues_is_counted_once():
    con = _con()
    for i in range(3):
        _stale(con, f"s{i}", f"Place {i}", "restaurant", lon=LON + i * 0.00005)
    _storefront(con, "P1", 2020, False, "FOOD SERVICES")
    _storefront(con, "P1", 2021, True, None)
    rep = ct.build(con, asof=ASOF)
    assert rep["written"] == 3 and rep["distinct_flip_premises"] == 1
    assert rep["flip_shared_with_other_stale_venues"] == 3
    assert {r[0] for r in con.execute(
        "SELECT flip_shared_by FROM analysis.closure_triangulation").fetchall()} == {3}


def test_the_check_refuses_a_single_kind_row():
    con = _con()
    with pytest.raises(Exception, match=r"CHECK|n_kinds"):
        con.execute("""INSERT INTO analysis.closure_triangulation (stale_poi_id, source_id,
            category, lon, lat, geom, kinds, n_kinds, closed_before, would_flip, asof_date,
            built_at) VALUES ('x', 's', 'bar', 0, 0, ST_Point(0, 0), 'stale', 1,
            DATE '2020-01-01', FALSE, DATE '2026-09-17', now())""")


def test_empty_stale_table_raises():
    con = _con()
    with pytest.raises(RuntimeError, match="empty"):
        ct.build(con, asof=ASOF)
