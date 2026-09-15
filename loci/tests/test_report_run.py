"""AC-16, AC-18, AC-19, AC-20, AC-21, end to end through `loci.report.run.generate`.
Own local warehouse fixture (see `test_report_prose.py`'s note on why sibling
test modules do not import each other's fixtures under pytest's default
import mode). `cache.CACHE_DIR` is monkeypatched to `tmp_path` and `out=` is
always passed explicitly so these tests never touch the real
`data/interim/report_cache` or `docs/recommendations`.
"""
from __future__ import annotations

import datetime as dt
import json

import loci.db as locidb
from loci.categories import CATEGORIES
from loci.report import cache, run
from loci.report.clients import FakePlaces, FakeProse, PlaceStatusResult
from loci.report.render import HEADINGS, PROSE_UNAVAILABLE

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


def _db(include_unknown_poi: bool = True):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, neighborhood, "
        "nta_code, eligible, present_count, n_missing, reach_source, reach_hash, "
        "graph_version, run_at, homes_400m, vacant_storefronts_400m) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [ADDR_ID, "3012340001", -73.9500, 40.7100, "BK", "Testville", "BK0601", True,
         12, 3, "tiers", "h", "g", dt.datetime(2026, 9, 11), 3000.0, 1.0])
    con.execute(
        "UPDATE analysis.address SET street_name = 'Test Street' WHERE address_id = ?",
        [ADDR_ID])
    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, "
        "supply_ratio_vs_base) VALUES (?,?,?,?)",
        [(ADDR_ID, "BK", c, 0.1 if c == "grocery" else 0.9) for c in CATEGORIES])
    con.execute(
        "INSERT INTO analysis.address_demographics (address_id, bbl, acs_year, "
        "median_hh_income, renter_share) VALUES (?,?,?,?,?)",
        [ADDR_ID, "3012340001", 2023, 90_000.0, 0.6])
    _poi(con, "poi:open", "Test Grocery", "grocery", "nyc_dcwp_licenses", 50.0,
        {"active": "true", "expires": "2030-01-01"}, 1)
    if include_unknown_poi:
        _poi(con, "poi:unk1", "Mystery Cafe", "cafe_bakery", "overture_places", 150.0, {}, 2)
    return con


def _clients(prose_text=None):
    places = FakePlaces({"Mystery Cafe": PlaceStatusResult(
        verdict="open", url="https://maps/1")})
    web = None
    prose = FakeProse(text=prose_text or json.dumps(
        {"1": "s1", "2": "s2", "3": "s3", "4": "s4"}))
    return places, web, prose


def _generate(con, tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    out = kw.pop("out", tmp_path / "report.md")
    return run.generate(con, ADDR_ID, out=out, **kw)


# --------------------------------------------------------------- AC-16

def test_ac16_writes_a_file_with_all_four_headings_non_empty(tmp_path, monkeypatch):
    con = _db()
    result = _generate(con, tmp_path, monkeypatch, clients=_clients())
    assert result.path is not None
    text = (tmp_path / "report.md").read_text()
    assert text == result.markdown
    for h in HEADINGS:
        assert h in text


def test_ac16_renders_with_no_anthropic_key_available():
    """`clients=(places, web, None)` -- the seed's own required case: report
    still renders all four headings with a 'prose unavailable' line."""
    import tempfile
    from pathlib import Path

    con = _db()
    with tempfile.TemporaryDirectory() as d:
        import loci.report.cache as cache_mod
        old = cache_mod.CACHE_DIR
        cache_mod.CACHE_DIR = Path(d) / "cache"
        try:
            result = run.generate(con, ADDR_ID, out=Path(d) / "r.md",
                                  clients=(None, None, None))
        finally:
            cache_mod.CACHE_DIR = old
    for h in HEADINGS:
        assert h in result.markdown
    assert result.markdown.count(PROSE_UNAVAILABLE) == 4


# --------------------------------------------------------------- AC-18

def test_ac18_ledger_sum_never_exceeds_the_cap_and_abort_is_logged(tmp_path, monkeypatch, caplog):
    import logging

    con = _db()
    places, web, prose = _clients()
    with caplog.at_level(logging.WARNING):
        result = _generate(con, tmp_path, monkeypatch, cap_usd=0.05,
                           clients=(places, web, prose))
    spent = con.execute(
        "SELECT COALESCE(sum(usd), 0) FROM analysis.spend_ledger WHERE run_id = ?",
        [result.run_id]).fetchone()[0]
    assert float(spent) <= 0.05 + 1e-9
    # A cap this small (0.05) cannot afford the $0.50 prose reservation, so
    # the report is generated on closure/search spend alone and the abort is
    # logged somewhere in the pipeline.
    assert any("cap" in r.message.lower() for r in caplog.records)


# --------------------------------------------------------------- AC-19

def test_ac19_second_run_within_30_days_makes_zero_paid_calls(tmp_path, monkeypatch):
    # No 'unknown' POI here: a run that RESOLVES a closure changes the pack's
    # hash by design (cache.py's own docstring -- a landed verdict must bust
    # a stale cache entry, never serve behind it), so this proves the STEADY
    # STATE claim AC-19 makes ("a second run within 30 days makes zero paid
    # calls"), not the (also-true, separately covered by test_report_enrich.py)
    # claim that a closure check itself is billed correctly.
    con = _db(include_unknown_poi=False)
    places1, web1, prose1 = _clients()
    r1 = _generate(con, tmp_path, monkeypatch, clients=(places1, web1, prose1))
    assert r1.cached is False
    assert len(prose1.calls) == 1              # the one prose call every fresh run makes

    places2, web2, prose2 = _clients()
    r2 = _generate(con, tmp_path, monkeypatch, clients=(places2, web2, prose2))
    assert r2.cached is True
    assert places2.calls == []
    assert prose2.calls == []
    assert r2.total_usd == 0.0


def test_ac19_no_cache_forces_a_fresh_run(tmp_path, monkeypatch):
    con = _db(include_unknown_poi=False)
    places1, web1, prose1 = _clients()
    _generate(con, tmp_path, monkeypatch, clients=(places1, web1, prose1))

    places2, web2, prose2 = _clients()
    r2 = _generate(con, tmp_path, monkeypatch, no_cache=True,
                   clients=(places2, web2, prose2))
    assert r2.cached is False
    assert len(prose2.calls) == 1               # --no-cache re-spent the one prose call


# --------------------------------------------------------------- AC-20

def test_ac20_dry_run_makes_no_paid_calls_and_prints_a_plan(tmp_path, monkeypatch):
    con = _db()
    places, web, prose = _clients()
    result = _generate(con, tmp_path, monkeypatch, dry_run=True,
                       clients=(places, web, prose))
    assert places.calls == []
    assert prose.calls == []
    assert con.execute("SELECT count(*) FROM analysis.spend_ledger").fetchone()[0] == 0
    assert len(result.plan) > 0
    assert result.total_usd > 0.0        # estimated cost from the plan
    assert result.path is None           # dry-run never writes docs/recommendations


# --------------------------------------------------------- --no-closure-checks

def test_closure_checks_false_makes_zero_places_calls_and_shows_the_disabled_line(
        tmp_path, monkeypatch):
    """This fixture's synthetic address grades below C (see the sibling test
    below), so unforced it renders the no-trade note -- `render.is_below_c`
    is forced False here so this test can keep proving what it always proved
    (the full memo's closure-checks-disabled line and its POI appendix),
    independent of the grade gate GTM-172 added."""
    import loci.report.render as render_mod

    monkeypatch.setattr(render_mod, "is_below_c", lambda pack: False)
    con = _db()      # include_unknown_poi=True by default -- "Mystery Cafe"
    places, web, prose = _clients()
    result = _generate(con, tmp_path, monkeypatch, closure_checks=False,
                       clients=(places, web, prose))
    assert places.calls == []
    assert con.execute(
        "SELECT count(*) FROM analysis.poi_closure_evidence").fetchone()[0] == 0
    assert "Closure checks disabled for this run (status shown as of" in result.markdown
    # The unknown POI is still listed, status untouched -- in the appendix now
    # (investor review item 4: the raw POI table moved out of section 2).
    assert "## Appendix — supply detail" in result.markdown
    assert "Mystery Cafe" in result.markdown
    assert "unknown" in result.markdown


def test_below_c_grade_renders_the_no_trade_note_end_to_end(tmp_path, monkeypatch):
    """Investor review item 2, the other half of the gate: THIS fixture's
    synthetic address grades below C on the real grading rules (unforced --
    see the sibling test above, which forces the opposite path). The
    no-trade note has no POI table/appendix, no rents/leases web signals
    (item 2's "no web enrichment beyond news"), and still makes zero paid
    Places calls when `--no-closure-checks` is set."""
    con = _db()
    places, web, prose = _clients()
    result = _generate(con, tmp_path, monkeypatch, closure_checks=False,
                       clients=(places, web, prose))
    assert "**NO TRADE.**" in result.markdown
    assert "## Appendix — supply detail" not in result.markdown
    assert "Mystery Cafe" not in result.markdown
    for h in HEADINGS:
        assert h in result.markdown
    assert places.calls == []


# --------------------------------------------------------------- AC-21

def test_ac21_prose_called_exactly_once_with_one_ledger_row(tmp_path, monkeypatch):
    con = _db()
    places, web, prose = _clients()
    result = _generate(con, tmp_path, monkeypatch, clients=(places, web, prose))
    assert len(prose.calls) == 1
    rows = con.execute(
        "SELECT usd FROM analysis.spend_ledger WHERE run_id = ? AND provider = 'anthropic'",
        [result.run_id]).fetchall()
    assert len(rows) == 1
    assert "s1" in result.markdown and "s4" in result.markdown
