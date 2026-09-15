"""model/poi_evidence.py -- the closure-evidence precedence rule (D98,
GTM-170, AC-8/AC-9).

WHAT IS BEING PINNED, AND WHY EACH MATTERS

1. AC-8: a web/Places evidence row can move a POI off 'unknown', and the
   winning verdict's basis names its own provenance (the URL).
2. AC-9: precedence is by DATE, not by source type. Newest evidence_date
   wins; a tie keeps the base; an undated (`dated_by='none'`) row can only
   ever resolve an 'unknown' base, never overturn a dated one.
3. ONE RULE, TWO RENDERINGS. `resolve()` (Python) and `wrap_status_sql()` /
   `wrap_basis_sql()` (SQL, layered on `poi_presence.poi_is_open()` /
   `poi_status_basis()`) must agree row for row -- exactly the discipline
   tests/test_poi_colocation.py already holds the base predicate to.
4. `poi_status_date()` / `poi_status_date_sql()` -- the base predicate's date
   twin -- must also agree between Python and SQL.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from loci.db import connect, init_schema
from loci.model import poi_evidence as pe
from loci.model import poi_presence as pp

TODAY = dt.date(2026, 9, 14)
FRESH = (TODAY - dt.timedelta(days=30)).isoformat()
ANCIENT = (TODAY - dt.timedelta(days=1500)).isoformat()


# =========================================================== 1. resolve()


def _ev(*, verdict="closed", source="web", evidence_date, dated_by="published",
       url="https://ny.eater.com/x", domain_class="news", poi_id="p1"):
    return pe.EvidenceRow(
        poi_id=poi_id, verdict=verdict, source=source, source_name="Eater NY",
        url=url, evidence_date=evidence_date, dated_by=dated_by,
        retrieved_at=dt.datetime(2026, 9, 14, 12, 0, 0), query="q",
        domain_class=domain_class)


def test_evidence_overrides_unknown_unconditionally_even_if_undated():
    base = (pp.STATUS_UNKNOWN, "overture_places:no_status_field")
    ev = _ev(evidence_date=dt.date(2020, 1, 1), dated_by="none")
    status, basis = pe.resolve(base, None, ev)
    assert status == "closed"
    assert basis.startswith("web_evidence:closed:")
    assert "https://ny.eater.com/x" in basis


def test_ac9_web_evidence_older_than_open_base_is_ignored():
    """AC-9, direction 1: web closed 2026-05-01 vs an inspection-open base
    dated 2026-07-01 -> stays 'open' (evidence is NOT newer)."""
    base = ("open", "nyc_dohmh_restaurants:inspected_20d_ago")
    base_date = dt.date(2026, 7, 1)
    ev = _ev(verdict="closed", evidence_date=dt.date(2026, 5, 1))
    status, basis = pe.resolve(base, base_date, ev)
    assert status == "open"
    assert basis == base[1]


def test_ac9_web_evidence_newer_than_open_base_wins():
    """AC-9, direction 2 (reversed dates): base dated 2026-05-01, web closed
    dated 2026-07-01 -> 'closed'."""
    base = ("open", "nyc_dohmh_restaurants:inspected_20d_ago")
    base_date = dt.date(2026, 5, 1)
    ev = _ev(verdict="closed", evidence_date=dt.date(2026, 7, 1))
    status, basis = pe.resolve(base, base_date, ev)
    assert status == "closed"
    assert basis.startswith("web_evidence:closed:news:2026-07-01:")


def test_tie_keeps_base():
    base = ("open", "some:basis")
    base_date = dt.date(2026, 6, 1)
    ev = _ev(verdict="closed", evidence_date=dt.date(2026, 6, 1))
    status, basis = pe.resolve(base, base_date, ev)
    assert (status, basis) == base


def test_undated_evidence_never_overturns_a_dated_base():
    base = ("open", "some:basis")
    base_date = dt.date(2020, 1, 1)          # ancient base, evidence is later in wall time
    ev = _ev(verdict="closed", evidence_date=dt.date(2026, 9, 1), dated_by="none")
    status, basis = pe.resolve(base, base_date, ev)
    assert (status, basis) == base           # dated_by='none' refuses to override a dated base


def test_no_evidence_or_inconclusive_evidence_is_a_no_op():
    base = ("open", "some:basis")
    assert pe.resolve(base, dt.date(2026, 1, 1), None) == base
    inconclusive = _ev(verdict=None, evidence_date=dt.date(2099, 1, 1))
    assert pe.resolve(base, dt.date(2026, 1, 1), inconclusive) == base


def test_google_places_basis_string_format():
    ev = pe.EvidenceRow(
        poi_id="p1", verdict="closed", source="places", source_name="Google Places",
        url="https://www.google.com/maps/place/?q=place_id:abc123",
        evidence_date=dt.date(2026, 9, 1), dated_by="retrieval",
        retrieved_at=dt.datetime(2026, 9, 14), query="places:searchText")
    assert ev.basis() == "google_places:closed:2026-09-01:https://www.google.com/maps/place/?q=place_id:abc123"


# ================================================== 2. poi_status_date()

DATE_TABLE = [
    # label, attrs, closed_on, observed_on, expected date
    ("ledger closed_on wins outright",
     {"active": True, "active_basis": "inspected_20d_ago", "last_inspection_date": FRESH},
     dt.date(2025, 3, 1), None, dt.date(2025, 3, 1)),
    ("published-closed -> last_inspection_date",
     {"active": False, "active_basis": "closed_at_last_inspection",
      "last_inspection_date": "2026-06-15"}, None, None, dt.date(2026, 6, 15)),
    ("expired licence -> the expiry date",
     {"active": True, "active_basis": "valid_to_2025-01-01", "expires": "2025-01-01"},
     None, None, dt.date(2025, 1, 1)),
    ("open via valid licence -> observed_on, not the future expiry",
     {"active": True, "active_basis": "valid_to_2028-01-31", "expires": "2028-01-31"},
     None, dt.date(2026, 8, 1), dt.date(2026, 8, 1)),
    ("open via fresh inspection -> last_inspection_date",
     {"active": True, "active_basis": "inspected_20d_ago", "last_inspection_date": FRESH},
     None, None, dt.date.fromisoformat(FRESH)),
    ("open via roster -> observed_on",
     {"active": True, "active_basis": "published_active_roster"},
     None, dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
    ("stale DOHMH -> unknown, no date",
     {"active": False, "active_basis": "stale_1200d", "last_inspection_date": ANCIENT},
     None, None, None),
    ("no status field at all -> unknown, no date",
     {}, None, None, None),
]


@pytest.mark.parametrize("label,attrs,closed_on,observed_on,expected",
                         DATE_TABLE, ids=[r[0] for r in DATE_TABLE])
def test_poi_status_date_truth_table(label, attrs, closed_on, observed_on, expected):
    got = pe.poi_status_date(attrs, closed_on=closed_on, observed_on=observed_on, today=TODAY)
    assert got == expected, label


# ============================================ 3. the synthetic warehouse (AC-8)


def _poi(con, poi_id, source_id, category, name, lon, lat, cluster, canonical, attrs=None,
        observed_on=None):
    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, source_record_id, category, tier, "
        "name, geom, observed_on, confidence, attrs) "
        "VALUES (?, ?, ?, ?, 3, ?, ST_Point(?, ?), ?, 0.5, CAST(? AS JSON))",
        [poi_id, source_id, poi_id, category, name, lon, lat, observed_on,
         json.dumps(attrs or {})])
    con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                [poi_id, cluster, canonical, category])


@pytest.fixture()
def db():
    con = connect(":memory:")
    init_schema(con)
    return con


def test_ac8_web_evidence_moves_an_unknown_poi_to_closed(db):
    _poi(db, "ovt:g1", "overture_places", "cafe_bakery", "Windclimb", -73.9440, 40.7140, 900, True)
    pe.insert_evidence(db, pe.EvidenceRow(
        poi_id="ovt:g1", verdict="closed", source="web", source_name="Eater NY",
        url="https://ny.eater.com/windclimb-closed", evidence_date=dt.date(2026, 8, 1),
        dated_by="published", retrieved_at=dt.datetime(2026, 9, 1), query="q",
        domain_class="news"))
    row = db.execute(
        "SELECT poi_status, poi_status_basis, evidence_verdict, evidence_url "
        "FROM analysis.poi_supply_status WHERE poi_id = 'ovt:g1'").fetchone()
    status, basis, ev_verdict, ev_url = row
    assert status == "closed"
    assert "https://ny.eater.com/windclimb-closed" in basis
    assert ev_verdict == "closed"
    assert ev_url == "https://ny.eater.com/windclimb-closed"


def test_ac9_precedence_in_the_live_view_both_directions(db):
    # base: DOHMH inspected 2026-07-01 -> 'open'
    _poi(db, "doh:g2", "nyc_dohmh_restaurants", "restaurant", "Old Spot", -73.9441, 40.7141, 901,
        True, {"active": True, "active_basis": "inspected_20d_ago",
               "last_inspection_date": "2026-07-01"})
    pe.insert_evidence(db, pe.EvidenceRow(
        poi_id="doh:g2", verdict="closed", source="web", source_name="Eater NY",
        url="https://ny.eater.com/old-spot-closed", evidence_date=dt.date(2026, 5, 1),
        dated_by="published", retrieved_at=dt.datetime(2026, 9, 1), query="q",
        domain_class="news"))
    status = db.execute(
        "SELECT poi_status FROM analysis.poi_supply_status WHERE poi_id = 'doh:g2'").fetchone()[0]
    assert status == "open"          # evidence is OLDER than the base -> ignored

    # reversed: base dated 2026-05-01, evidence dated 2026-07-01 -> 'closed'
    _poi(db, "doh:g3", "nyc_dohmh_restaurants", "restaurant", "New Spot", -73.9442, 40.7142, 902,
        True, {"active": True, "active_basis": "inspected_20d_ago",
               "last_inspection_date": "2026-05-01"})
    pe.insert_evidence(db, pe.EvidenceRow(
        poi_id="doh:g3", verdict="closed", source="web", source_name="Eater NY",
        url="https://ny.eater.com/new-spot-closed", evidence_date=dt.date(2026, 7, 1),
        dated_by="published", retrieved_at=dt.datetime(2026, 9, 1), query="q",
        domain_class="news"))
    status = db.execute(
        "SELECT poi_status FROM analysis.poi_supply_status WHERE poi_id = 'doh:g3'").fetchone()[0]
    assert status == "closed"


def test_places_evidence_can_reopen_a_wrongly_gated_poi(db):
    """Google Places CLOSED_PERMANENTLY isn't the only verdict places can
    give -- OPERATIONAL is 'open', and (unlike web) Places evidence may
    produce it. AC-10's channel, exercised at the model layer."""
    _poi(db, "ovt:g4", "overture_places", "hardware", "Ghost Hardware", -73.9443, 40.7143, 903, True)
    pe.insert_evidence(db, pe.EvidenceRow(
        poi_id="ovt:g4", verdict="open", source="places", source_name="Google Places",
        url="https://www.google.com/maps/place/?q=place_id:xyz",
        evidence_date=dt.date(2026, 9, 10), dated_by="retrieval",
        retrieved_at=dt.datetime(2026, 9, 10), query="places:searchText"))
    status, basis = db.execute(
        "SELECT poi_status, poi_status_basis FROM analysis.poi_supply_status "
        "WHERE poi_id = 'ovt:g4'").fetchone()
    assert status == "open"
    assert basis.startswith("google_places:open:2026-09-10:")


def test_insert_evidence_is_a_replace_not_a_duplicate(db):
    _poi(db, "ovt:g5", "overture_places", "bar", "Test Bar", -73.9444, 40.7144, 904, True)
    row1 = pe.EvidenceRow(
        poi_id="ovt:g5", verdict=None, source="web", source_name="Yelp", url="https://yelp.com/x",
        evidence_date=dt.date(2026, 8, 1), dated_by="none", retrieved_at=dt.datetime(2026, 8, 1),
        query="q1", reason="domain_class=aggregator:not_first_party_or_news")
    row2 = pe.EvidenceRow(
        poi_id="ovt:g5", verdict="closed", source="web", source_name="Yelp", url="https://yelp.com/x",
        evidence_date=dt.date(2026, 9, 1), dated_by="published", retrieved_at=dt.datetime(2026, 9, 1),
        query="q2")
    pe.insert_evidence(db, row1)
    pe.insert_evidence(db, row2)
    n = db.execute("SELECT count(*) FROM analysis.poi_closure_evidence WHERE poi_id = 'ovt:g5'"
                   ).fetchone()[0]
    assert n == 1
    assert row1.evidence_id() == row2.evidence_id()


def test_default_view_stays_byte_identical_without_evidence():
    """The wiring in poi_presence.py must not change the default rendering
    tests/test_poi_colocation.py::test_sql_file_matches_generator pins."""
    assert "evidence_verdict" not in pp.colocation_view_sql()
    assert "evidence_verdict" in pp.colocation_view_sql(evidence=True)


# ======================================== 4. SQL/Python parity (poi_status_date)


def test_poi_status_date_sql_and_python_agree(db):
    _poi(db, "a1", "nyc_dohmh_restaurants", "restaurant", "A", -73.95, 40.71, 1, True,
        {"active": True, "active_basis": "inspected_20d_ago", "last_inspection_date": FRESH})
    _poi(db, "a2", "nyc_dohmh_restaurants", "restaurant", "B", -73.951, 40.711, 2, True,
        {"active": False, "active_basis": "closed_at_last_inspection",
         "last_inspection_date": FRESH})
    _poi(db, "a3", "nys_sla_liquor_licenses", "bar", "C", -73.952, 40.712, 3, True,
        {"active": True, "active_basis": "valid_to_2028-01-31", "expires": "2028-01-31"},
        observed_on="2026-08-01")
    _poi(db, "a4", "nyc_dohmh_childcare", "childcare", "D", -73.953, 40.713, 4, True,
        {"active": True, "active_basis": "published_active_roster"}, observed_on="2026-09-01")
    _poi(db, "a5", "overture_places", "cafe_bakery", "E", -73.954, 40.714, 5, True)

    rows = db.execute(f"""
        SELECT p.poi_id, p.attrs, p.observed_on,
               {pe.poi_status_date_sql('p', 'NULL', "DATE '2026-09-14'")} AS sql_date
        FROM staging.poi p WHERE p.poi_id LIKE 'a%'
    """).fetchall()
    assert rows
    for poi_id, attrs, observed_on, sql_date in rows:
        py_date = pe.poi_status_date(json.loads(attrs), observed_on=observed_on, today=TODAY)
        assert py_date == sql_date, poi_id
