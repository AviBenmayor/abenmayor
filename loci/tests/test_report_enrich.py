"""AC-17, AC-18: `loci.report.enrich`. Own local warehouse fixture (pytest's
default import mode does not resolve `tests.<module>` cross-imports between
sibling test files -- see `test_report_prose.py`'s note), condensed from the
same pattern `test_report_evidence.py::_synthetic_db` uses."""
from __future__ import annotations

import datetime as dt
import json

import loci.db as locidb
from loci.categories import CATEGORIES
from loci.report import evidence as ev
from loci.report.clients import FakePlaces, PlaceStatusResult
from loci.report.enrich import enrich
from loci.report.ledger import PRICES, Budget

ADDR_ID = "addr1"


def _poi(con, poi_id, name, category, source_id, dlat_m, attrs, cluster_id):
    lat = 40.7100 + dlat_m / 111_320.0
    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, category, tier, name, geom, "
        "observed_on, attrs) VALUES (?, ?, ?, 1, ?, ST_Point(?, ?), ?, ?)",
        [poi_id, source_id, category, name, -73.9500, lat, dt.date(2026, 1, 1),
         json.dumps(attrs)])
    con.execute(
        "INSERT INTO analysis.poi_dedup (poi_id, cluster_id, is_canonical, category) "
        "VALUES (?, ?, TRUE, ?)", [poi_id, cluster_id, category])


def _db_with_n_unknowns(n: int):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, neighborhood, "
        "nta_code, eligible, present_count, n_missing, reach_source, reach_hash, "
        "graph_version, run_at, homes_400m) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [ADDR_ID, "3012340001", -73.9500, 40.7100, "BK", "Testville", "BK0601", True,
         12, 3, "tiers", "h", "g", dt.datetime(2026, 9, 11), 3000.0])
    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, "
        "supply_ratio_vs_base) VALUES (?,?,?,?)",
        [(ADDR_ID, "BK", c, 0.1 if c == "grocery" else 0.9) for c in CATEGORIES])
    con.execute(
        "INSERT INTO analysis.address_demographics (address_id, bbl, acs_year, "
        "median_hh_income) VALUES (?,?,?,?)", [ADDR_ID, "3012340001", 2023, 90_000.0])
    for i in range(n):
        _poi(con, f"poi:unk{i}", f"Mystery Shop {i}", "grocery", "overture_places",
            50.0 * (i + 1), {}, i)
    return con


def test_every_unknown_poi_is_checked_when_the_cap_is_large():
    con = _db_with_n_unknowns(5)
    pack = ev.assemble(con, ADDR_ID)
    assert len(ev.unknown_pois(pack)) == 5
    budget = Budget(run_id="e1", cap_usd=1.0, con=con)
    places = FakePlaces({f"Mystery Shop {i}": PlaceStatusResult(
        verdict="open", url=f"https://maps/{i}") for i in range(5)})
    result = enrich(pack, budget, places, None)
    assert result.checks_planned == 5
    assert result.checks_done == 5
    assert result.cap_hit is False
    assert len(places.calls) == 5


def test_the_cap_stops_checks_early_and_logs_cap_hit(caplog):
    import logging

    con = _db_with_n_unknowns(5)
    pack = ev.assemble(con, ADDR_ID)
    # room for exactly 2 places checks (2 * 0.032 = 0.064) and nothing more
    budget = Budget(run_id="e2", cap_usd=0.064, con=con)
    places = FakePlaces({f"Mystery Shop {i}": PlaceStatusResult(
        verdict="open", url=f"https://maps/{i}") for i in range(5)})
    with caplog.at_level(logging.WARNING):
        result = enrich(pack, budget, places, None)
    assert result.checks_done == 2
    assert result.cap_hit is True
    assert any("cap hit" in r.message.lower() for r in caplog.records)
    assert budget.spent() <= 0.064 + 1e-9


def test_conclusive_places_result_skips_the_web_fallback():
    con = _db_with_n_unknowns(1)
    pack = ev.assemble(con, ADDR_ID)
    budget = Budget(run_id="e3", cap_usd=1.0, con=con)
    places = FakePlaces({"Mystery Shop 0": PlaceStatusResult(
        verdict="closed", url="https://maps/0")})

    class _WebNoClosureFallback:
        """The 3 general searches (rents/leases/news) always run; only the
        PER-POI closure fallback must not fire when Places was conclusive."""
        def search(self, query, *, max_results=8):
            if "Mystery Shop 0" in query:
                raise AssertionError(
                    "web closure fallback should not run when Places was conclusive")
            return []

    result = enrich(pack, budget, places, _WebNoClosureFallback())
    assert result.checks_done == 1
    row = con.execute(
        "SELECT verdict, source FROM analysis.poi_closure_evidence WHERE poi_id = ?",
        ["poi:unk0"]).fetchone()
    assert row == ("closed", "places")


def test_no_clients_configured_means_zero_checks_and_no_spend():
    con = _db_with_n_unknowns(3)
    pack = ev.assemble(con, ADDR_ID)
    budget = Budget(run_id="e4", cap_usd=1.0, con=con)
    result = enrich(pack, budget, None, None)
    assert result.checks_planned == 3
    assert result.checks_done == 0
    assert result.cap_hit is False
    assert budget.spent() == 0.0


def test_supply_status_refreshes_after_a_conclusive_check():
    con = _db_with_n_unknowns(1)
    pack = ev.assemble(con, ADDR_ID)
    assert pack.supply[0].status == "unknown"
    budget = Budget(run_id="e5", cap_usd=1.0, con=con)
    places = FakePlaces({"Mystery Shop 0": PlaceStatusResult(
        verdict="closed", url="https://maps/0")})
    enrich(pack, budget, places, None)
    assert pack.supply[0].status == "closed"


def test_closure_checks_false_makes_zero_places_calls_and_writes_zero_evidence():
    con = _db_with_n_unknowns(3)
    pack = ev.assemble(con, ADDR_ID)
    budget = Budget(run_id="e7", cap_usd=1.0, con=con)
    places = FakePlaces({f"Mystery Shop {i}": PlaceStatusResult(
        verdict="open", url=f"https://maps/{i}") for i in range(3)})
    result = enrich(pack, budget, places, None, closure_checks=False)
    assert result.checks_planned == 0
    assert result.checks_done == 0
    assert result.closure_checks_disabled is True
    assert places.calls == []
    assert con.execute(
        "SELECT count(*) FROM analysis.poi_closure_evidence").fetchone()[0] == 0
    # poi_status is untouched -- still 'unknown' for all three.
    assert all(p.status == "unknown" for p in pack.supply)
    # No closure-check charges landed on the ledger (only whatever the 3
    # general searches would have charged, and there's no web client here).
    assert budget.spent() == 0.0


def test_dry_run_makes_no_places_calls_and_only_charges_the_plan():
    con = _db_with_n_unknowns(3)
    pack = ev.assemble(con, ADDR_ID)
    budget = Budget(run_id="e6", cap_usd=1.0, con=con, dry_run=True)
    places = FakePlaces({f"Mystery Shop {i}": PlaceStatusResult(
        verdict="open", url=f"https://maps/{i}") for i in range(3)})
    result = enrich(pack, budget, places, None)
    assert places.calls == []                    # the real client is never touched
    assert result.checks_done == 0                # dry-run "checks" are plan entries, not writes
    assert con.execute(
        "SELECT count(*) FROM analysis.poi_closure_evidence").fetchone()[0] == 0
    assert len(budget.plan) == 3                  # one planned Places charge per unknown POI
    assert all(p.provider == "places" for p in budget.plan)
