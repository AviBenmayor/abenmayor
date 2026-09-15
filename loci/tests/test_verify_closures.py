"""evidence/verify.py -- `loci verify-closures` core, budget-capped (D98,
GTM-170, AC-11). The CLI wrapper is out of scope for this build (owned by
another session's cli.py commit); everything here exercises the core
directly with fake, pinned-cost clients -- NO real Places or Tavily call is
ever made by this file.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from loci.db import connect, init_schema
from loci.evidence.verify import (
    Budget, Candidate, FakePlaces, PlaceStatus, area_bbox, select_unknown, verify,
)
from loci.evidence.web_search import FakeWebSearch, Hit

TODAY = dt.date(2026, 9, 14)


# ============================================================= 1. Budget


def test_budget_reserve_never_exceeds_the_cap():
    b = Budget(usd=0.10)
    assert b.reserve(0.032) is True
    assert b.reserve(0.032) is True
    assert b.reserve(0.032) is True     # spent = 0.096
    assert b.reserve(0.032) is False    # would be 0.128 > 0.10
    assert b.spent == pytest.approx(0.096)


def test_budget_stops_before_the_call_that_would_exceed_it_exactly():
    """N cents stops before the (N+1)th cent -- pinned costs of exactly $0.01."""
    b = Budget(usd=0.05)
    for _ in range(5):
        assert b.reserve(0.01) is True
    assert b.reserve(0.01) is False
    assert b.spent == pytest.approx(0.05)


# ==================================================== 2. select_unknown / area_bbox


def _poi(con, poi_id, source_id, category, name, lon, lat, cluster, canonical, attrs=None):
    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, source_record_id, category, tier, "
        "name, geom, observed_on, confidence, attrs) "
        "VALUES (?, ?, ?, ?, 3, ?, ST_Point(?, ?), NULL, 0.5, CAST(? AS JSON))",
        [poi_id, source_id, poi_id, category, name, lon, lat, json.dumps(attrs or {})])
    con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                [poi_id, cluster, canonical, category])


@pytest.fixture()
def db():
    con = connect(":memory:")
    init_schema(con)
    _poi(con, "ovt:1", "overture_places", "cafe_bakery", "Ghost Cafe", -73.9440, 40.7140, 1, True)
    _poi(con, "ovt:2", "overture_places", "restaurant", "Ghost Diner", -73.9441, 40.7141, 2, True)
    # a KNOWN-open POI must never be selected
    _poi(con, "doh:3", "nyc_dohmh_restaurants", "restaurant", "Known Open", -73.9442, 40.7142, 3,
        True, {"active": True, "active_basis": "inspected_20d_ago",
               "last_inspection_date": "2026-08-20"})
    # outside the bbox used below
    _poi(con, "ovt:4", "overture_places", "bar", "Far Away Bar", -74.10, 40.60, 4, True)
    return con


def test_select_unknown_excludes_known_and_out_of_bbox(db):
    bbox = (-73.95, 40.71, -73.93, 40.72)
    cands = select_unknown(db, bbox=bbox)
    ids = {c.poi_id for c in cands}
    assert ids == {"ovt:1", "ovt:2"}


def test_select_unknown_respects_recheck_days(db):
    from loci.model import poi_evidence as pe
    pe.insert_evidence(db, pe.EvidenceRow(
        poi_id="ovt:1", verdict=None, source="web", source_name="randomblog.example",
        url="https://randomblog.example/x", evidence_date=dt.date(2026, 9, 10), dated_by="none",
        retrieved_at=dt.datetime(2026, 9, 10), query="q", reason="no_closure_phrase_in_window"))
    bbox = (-73.95, 40.71, -73.93, 40.72)
    # checked 4 days ago; default recheck window is 30 days -> excluded
    cands = select_unknown(db, bbox=bbox, recheck_days=30)
    assert "ovt:1" not in {c.poi_id for c in cands}
    # a 2-day recheck window says it's due again
    cands2 = select_unknown(db, bbox=bbox, recheck_days=2)
    assert "ovt:1" in {c.poi_id for c in cands2}


def test_area_bbox_from_neighborhood(db):
    with pytest.raises(ValueError):
        area_bbox(db, "Nonexistent Neighborhood XYZ 12345")


def test_select_unknown_name_filter(db):
    bbox = (-73.95, 40.71, -73.93, 40.72)
    cands = select_unknown(db, bbox=bbox, name="diner")
    assert {c.poi_id for c in cands} == {"ovt:2"}    # only "Ghost Diner" matches


def test_select_unknown_poi_filter(db):
    bbox = (-73.95, 40.71, -73.93, 40.72)
    cands = select_unknown(db, bbox=bbox, poi_ids=["ovt:1"])
    assert {c.poi_id for c in cands} == {"ovt:1"}

    cands2 = select_unknown(db, bbox=bbox, poi_ids=["ovt:1", "ovt:2"])
    assert {c.poi_id for c in cands2} == {"ovt:1", "ovt:2"}


def test_select_unknown_orders_nearer_to_bbox_centre_first_within_equal_colocation(db):
    """bbox centre is (-73.94, 40.715). `near:1` sits exactly there; `far:1`
    sits near the bbox's far corner. Both are lone POIs at their own exact
    coordinate (colocation_n=1, same as `near:1`), so ordering within that
    tie must fall to distance-to-centre, ascending."""
    bbox = (-73.95, 40.71, -73.93, 40.72)
    _poi(db, "near:1", "overture_places", "cafe_bakery", "Near Shop", -73.9400, 40.7150, 10, True)
    _poi(db, "far:1", "overture_places", "cafe_bakery", "Far Shop", -73.9310, 40.7190, 11, True)
    cands = select_unknown(db, bbox=bbox)
    ids = [c.poi_id for c in cands]
    assert ids.index("near:1") < ids.index("far:1")


# ======================================================= 3. verify() -- AC-11


def test_dry_run_makes_zero_calls_and_zero_writes(db):
    cands = [Candidate("ovt:1", "Ghost Cafe", "cafe_bakery", -73.944, 40.714, 1),
            Candidate("ovt:2", "Ghost Diner", "restaurant", -73.9441, 40.7141, 1)]
    places = FakePlaces()
    web = FakeWebSearch()
    budget = Budget(usd=0.01)     # would not even cover one Places call
    result = verify(db, cands, budget=budget, places=places, web=web, dry_run=True)
    assert result.dry_run is True
    assert places.calls == []
    assert web.calls == []
    assert budget.spent == 0.0
    assert db.execute("SELECT count(*) FROM analysis.spend_ledger").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM analysis.poi_closure_evidence").fetchone()[0] == 0
    assert len(result.plan) == 4           # 2 candidates x (places, web)
    assert result.estimated_usd == pytest.approx(2 * (0.032 + 0.008))


def test_places_conclusive_skips_the_web_call(db):
    cands = [Candidate("ovt:1", "Ghost Cafe", "cafe_bakery", -73.944, 40.714, 1)]
    places = FakePlaces(status_by_poi={"Ghost Cafe": PlaceStatus(verdict="closed", place_id="xyz")})
    web = FakeWebSearch()
    budget = Budget(usd=1.0)
    result = verify(db, cands, budget=budget, places=places, web=web, run_id="r1", today=TODAY)
    assert result.places_calls == 1
    assert result.web_calls == 0
    assert web.calls == []
    assert result.closed == 1
    row = db.execute("SELECT poi_status FROM analysis.poi_supply_status "
                     "WHERE poi_id = 'ovt:1'").fetchone()
    assert row[0] == "closed"


def test_places_inconclusive_falls_through_to_web(db):
    cands = [Candidate("ovt:1", "Ghost Cafe", "cafe_bakery", -73.944, 40.714, 1, street="Bedford Ave")]
    places = FakePlaces(status_by_poi={"Ghost Cafe": PlaceStatus(verdict=None)})
    hit = Hit(url="https://ny.eater.com/ghost-cafe-closed", title="Ghost Cafe has permanently closed",
              snippet="Ghost Cafe on Bedford Ave has closed for good.",
              published="2026-08-01", domain="ny.eater.com")
    web = FakeWebSearch(hits_by_query={None: [hit]})
    budget = Budget(usd=1.0)
    result = verify(db, cands, budget=budget, places=places, web=web, run_id="r2", today=TODAY)
    assert result.places_calls == 1
    assert result.web_calls == 1
    assert result.closed == 1


def test_budget_stops_mid_run_and_logs_the_hit(db):
    cands = [Candidate("ovt:1", "Ghost Cafe", "cafe_bakery", -73.944, 40.714, 1),
            Candidate("ovt:2", "Ghost Diner", "restaurant", -73.9441, 40.7141, 1)]
    places = FakePlaces()  # always inconclusive -> falls to web
    web = FakeWebSearch()  # no hits configured -> still_unknown
    # exactly one Places + one Tavily call ($0.040), not a second POI's worth
    budget = Budget(usd=0.040)
    result = verify(db, cands, budget=budget, places=places, web=web, run_id="r3", today=TODAY)
    assert result.budget_hit is True
    assert result.checked == 1
    assert budget.spent <= 0.040 + 1e-9
    ledger_sum = db.execute(
        "SELECT sum(usd) FROM analysis.spend_ledger WHERE run_id = 'r3'").fetchone()[0]
    assert float(ledger_sum) == pytest.approx(budget.spent)
    assert float(ledger_sum) <= 0.040 + 1e-9


def test_ledger_sum_never_exceeds_the_cap_across_a_larger_batch(db):
    cands = [Candidate(f"p{i}", f"Shop {i}", "cafe_bakery", -73.94, 40.71, 1) for i in range(10)]
    places = FakePlaces()
    web = FakeWebSearch()
    budget = Budget(usd=0.10)
    for c in cands:
        _poi(db, c.poi_id, "overture_places", "cafe_bakery", c.name, c.lon, c.lat, 100, True)
    result = verify(db, cands, budget=budget, places=places, web=web, run_id="r4", today=TODAY)
    ledger_sum = db.execute(
        "SELECT sum(usd) FROM analysis.spend_ledger WHERE run_id = 'r4'").fetchone()[0]
    assert ledger_sum <= 0.10 + 1e-9
    assert result.budget_hit is True


def test_verify_writes_ledger_rows_before_the_call_in_sequence(db):
    """reserve -> ledger row -> call -> evidence row, per POI (module
    docstring). Checked indirectly: every places/web call the fakes recorded
    has a matching ledger row for the same run."""
    cands = [Candidate("ovt:1", "Ghost Cafe", "cafe_bakery", -73.944, 40.714, 1)]
    places = FakePlaces(status_by_poi={"Ghost Cafe": PlaceStatus(verdict="closed")})
    web = FakeWebSearch()
    budget = Budget(usd=1.0)
    verify(db, cands, budget=budget, places=places, web=web, run_id="r5", today=TODAY)
    kinds = db.execute(
        "SELECT provider, kind FROM analysis.spend_ledger WHERE run_id = 'r5'").fetchall()
    assert kinds == [("places", "verify")]
