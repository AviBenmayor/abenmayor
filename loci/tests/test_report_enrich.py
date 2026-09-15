"""AC-17, AC-18: `loci.report.enrich`. Own local warehouse fixture (pytest's
default import mode does not resolve `tests.<module>` cross-imports between
sibling test files -- see `test_report_prose.py`'s note), condensed from the
same pattern `test_report_evidence.py::_synthetic_db` uses.

Also covers investor review item 5 (GTM-172, 2026-09-14/15): the web-hit
quality gate (`filter_hits`) and item 2's `skip_rents_leases` wiring."""
from __future__ import annotations

import datetime as dt
import json

import loci.db as locidb
from loci.categories import CATEGORIES
from loci.evidence.web_search import Hit
from loci.report import evidence as ev
from loci.report.clients import FakePlaces, PlaceStatusResult
from loci.report.enrich import RejectedHit, enrich, filter_hits
from loci.report.evidence import EvidencePack
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


# ------------------------------------------------- investor review item 5: web layer


def _hit(url, title="", snippet="", published="2026-09-10", domain=None):
    from loci.evidence.web_search import domain_of

    return Hit(url=url, title=title, snippet=snippet, published=published,
              domain=domain if domain is not None else domain_of(url))


def _filter_pack() -> EvidencePack:
    """A minimal pack for `filter_hits` -- pure function, no DB needed. The
    locality it geo-scopes against is 'Test Street' / 'Testville'."""
    return EvidencePack(
        address={"address_id": "addr1", "street_name": "Test Street"},
        scores={}, grades=[], forecast=None, supply=[], demand={}, legality={},
        context={"neighborhood": "Testville", "borough": "BK", "catchment_m": 500.0})


def test_filter_hits_bans_reddit_youtube_instagram_facebook_tiktok_dnainfo():
    pack = _filter_pack()
    hits = [
        _hit("https://www.reddit.com/r/nyc/comments/1/test-street", snippet="Test Street talk"),
        _hit("https://www.youtube.com/watch?v=1", snippet="Test Street walking tour"),
        _hit("https://www.instagram.com/p/1", snippet="Test Street pic"),
        _hit("https://www.facebook.com/events/1", snippet="Test Street event"),
        _hit("https://www.tiktok.com/@x/video/1", snippet="Test Street"),
        _hit("https://www.dnainfo.com/new-york/test-street-news", snippet="Test Street"),
    ]
    kept, rejected = filter_hits(hits, pack, tag="news")
    assert kept == []
    assert {r.reason for r in rejected} == {"banned_domain"}
    assert len(rejected) == 6


def test_filter_hits_rejects_tag_archive_and_search_index_urls():
    pack = _filter_pack()
    hits = [
        _hit("https://example.com/tag/test-street", snippet="Test Street rents"),
        _hit("https://example.com/category/nyc-retail", snippet="Test Street rents"),
        _hit("https://example.com/archive/2026/09", snippet="Test Street rents"),
        _hit("https://example.com/search?q=test+street", snippet="Test Street rents"),
    ]
    kept, rejected = filter_hits(hits, pack, tag="leases")
    assert kept == []
    assert all(r.reason == "index_or_archive_url" for r in rejected)


def test_filter_hits_rejects_a_chamber_of_commerce_homepage_but_not_a_deep_link():
    pack = _filter_pack()
    homepage = _hit("https://www.testvillechamber.org/", snippet="Test Street business news")
    deep_link = _hit("https://www.testvillechamber.org/news/test-street-retail",
                     snippet="Test Street retail news")
    kept_home, rejected_home = filter_hits([homepage], pack, tag="news")
    kept_deep, rejected_deep = filter_hits([deep_link], pack, tag="news")
    assert kept_home == [] and rejected_home[0].reason == "chamber_homepage"
    assert kept_deep == [deep_link]


def test_filter_hits_rejects_off_corridor_hits():
    """The geo-scope check (item 5): a hit that never mentions this address's
    own street or neighborhood is rejected -- the Gowanus-priced-off-Court-
    Street failure mode from the investor review."""
    pack = _filter_pack()
    off_corridor = _hit("https://example.com/court-street-comps",
                        snippet="Court Street asking rents are strong this quarter")
    on_corridor = _hit("https://example.com/testville-comps",
                       snippet="Test Street asking rents in Testville")
    kept, rejected = filter_hits([off_corridor, on_corridor], pack, tag="leases")
    assert kept == [on_corridor]
    assert rejected[0].reason == "off_corridor"


def test_filter_hits_rents_require_a_dated_page_and_a_figure_with_a_unit():
    pack = _filter_pack()
    no_date = _hit("https://example.com/a", snippet="Test Street asking $45/sq ft",
                   published=None)
    no_unit = _hit("https://example.com/b", snippet="Test Street asking $302.72")
    good = _hit("https://example.com/c", snippet="Test Street asking $45.00/sq ft")
    kept, rejected = filter_hits([no_date, no_unit, good], pack, tag="rents")
    assert kept == [good]
    reasons = {r.url: r.reason for r in rejected}
    assert reasons["https://example.com/a"] == "undated"
    assert reasons["https://example.com/b"] == "no_rent_figure_with_unit"


def test_filter_hits_leases_and_news_do_not_require_a_rent_figure():
    pack = _filter_pack()
    lease_hit = _hit("https://example.com/lease", snippet="Test Street storefront for lease",
                     published=None)
    kept, rejected = filter_hits([lease_hit], pack, tag="leases")
    assert kept == [lease_hit]
    assert rejected == []


def test_enrich_only_surfaces_hits_that_survive_the_quality_gate():
    class _Web:
        def __init__(self):
            self.calls = []

        def search(self, query, *, max_results=8):
            self.calls.append(query)
            if "rent" in query:
                return [
                    _hit("https://www.reddit.com/r/x", snippet="Testville rent talk"),
                    _hit("https://example.com/good", snippet="Testville asking $50/sq ft"),
                ]
            return []

    con = _db_with_n_unknowns(0)
    pack = ev.assemble(con, ADDR_ID)
    budget = Budget(run_id="e8", cap_usd=1.0, con=con)
    result = enrich(pack, budget, None, _Web())
    assert [h.url for h in result.rents] == ["https://example.com/good"]
    assert any(r.reason == "banned_domain" for r in result.rejected_hits)


def test_skip_rents_leases_only_runs_the_news_search():
    class _Web:
        def __init__(self):
            self.calls = []

        def search(self, query, *, max_results=8):
            self.calls.append(query)
            return []

    con = _db_with_n_unknowns(0)
    pack = ev.assemble(con, ADDR_ID)
    budget = Budget(run_id="e9", cap_usd=1.0, con=con)
    web = _Web()
    result = enrich(pack, budget, None, web, skip_rents_leases=True)
    assert result.rents == [] and result.leases == []
    assert len(web.calls) == 1
    assert "news" in web.calls[0].lower()
