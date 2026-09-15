"""`loci verify-closures` (D98, GTM-170, AC-11) -- the CLI wrapper around
`loci.evidence.verify` (already tested directly, with fakes, in
`tests/test_verify_closures.py`). This file proves only the CLI's OWN
contract: `--dry-run` makes zero paid calls and constructs NEITHER paid
client (the real `GooglePlacesClient`/`TavilyWebSearch` classes are patched
to raise on construction, so a regression that builds them eagerly fails
loud), and a real run wires the injected clients through and stops at the
budget cap -- proved by call-counting fakes, dependency-injected by
monkeypatching the classes `verify_closures_cmd` imports locally (exactly
`tests/test_cli_report.py`'s own pattern: patch the attribute on the module
the CLI imports from, since the CLI's `from module import Class` binds at
call time, not at cli.py load time).

Own local warehouse fixture, same shape as `test_verify_closures.py`'s `db`
fixture (sibling test modules do not import each other's fixtures under
pytest's default import mode, per `test_cli_report.py`'s own note).
"""
from __future__ import annotations

import json

from loci import db as locidb


def _poi(con, poi_id, source_id, category, name, lon, lat, cluster, canonical=True, attrs=None):
    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, source_record_id, category, tier, "
        "name, geom, observed_on, confidence, attrs) "
        "VALUES (?, ?, ?, ?, 3, ?, ST_Point(?, ?), NULL, 0.5, CAST(? AS JSON))",
        [poi_id, source_id, poi_id, category, name, lon, lat, json.dumps(attrs or {})])
    con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                [poi_id, cluster, canonical, category])


def _db():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _poi(con, "ovt:1", "overture_places", "cafe_bakery", "Ghost Cafe", -73.9440, 40.7140, 1)
    _poi(con, "ovt:2", "overture_places", "restaurant", "Ghost Diner", -73.9441, 40.7141, 2)
    return con


def _invoke(monkeypatch, con, args):
    from typer.testing import CliRunner

    from loci import cli

    monkeypatch.setattr(cli.locidb, "connect", lambda *a, **k: con)
    return CliRunner().invoke(cli.app, args)


class _RaisesOnConstruction:
    """Stands in for a paid client class. Constructing it fails loud -- a
    `--dry-run` that built this anyway (a regression) fails the test instead
    of silently passing."""

    def __init__(self, *a, **k):
        raise AssertionError("dry-run must never construct a paid client")


def test_dry_run_makes_zero_calls_and_constructs_neither_client(monkeypatch):
    from loci.evidence import web_search
    from loci.validation import google_places

    monkeypatch.setattr(google_places, "GooglePlacesClient", _RaisesOnConstruction)
    monkeypatch.setattr(web_search, "TavilyWebSearch", _RaisesOnConstruction)

    con = _db()
    result = _invoke(monkeypatch, con,
                     ["verify-closures", "--budget", "1.00",
                      "--bbox", "-73.95,40.71,-73.93,40.72", "--dry-run"])

    assert result.exit_code == 0, result.stdout
    assert "ZERO calls made, ZERO rows written" in result.stdout
    assert "ovt:1" in result.stdout and "ovt:2" in result.stdout
    # verify_closures_cmd closes its own connection when done (like `colocation`
    # does) -- the zero-writes claim is instead proven the same way
    # test_verify_closures.py::test_dry_run_makes_zero_calls_and_zero_writes
    # proves it at the core layer: `verify(..., dry_run=True)` never touches
    # `con` at all in that branch, so there is nothing here left to check
    # post-close.


def test_missing_bbox_and_area_fails_loud(monkeypatch):
    con = _db()
    result = _invoke(monkeypatch, con, ["verify-closures", "--budget", "1.00"])
    assert result.exit_code == 1
    assert "exactly one of --bbox or --area" in result.stdout


class _FakePlacesClient:
    """Call-counting Places stand-in, dependency-injected via monkeypatch of
    `loci.validation.google_places.GooglePlacesClient` (the class the CLI's
    local `from loci.validation.google_places import GooglePlacesClient`
    resolves at call time). Always inconclusive, so every candidate falls
    through to the web client too -- exercises both legs of the budget."""
    instances: list = []

    def __init__(self, *a, **k):
        self.calls: list = []
        _FakePlacesClient.instances.append(self)

    def place_status(self, name, lat, lon, radius_m=50):
        from loci.evidence.verify import PlaceStatus
        self.calls.append(name)
        return PlaceStatus(verdict=None)


class _FakeTavilyClient:
    instances: list = []

    def __init__(self, *a, **k):
        self.calls: list = []
        _FakeTavilyClient.instances.append(self)

    def search(self, query, *, max_results=8):
        self.calls.append(query)
        return []


def test_real_run_wires_the_injected_clients_and_stops_at_the_budget_cap(monkeypatch):
    """AC-11: budget of exactly one Places call ($0.032) must stop BEFORE the
    web call ($0.008) it cannot afford, on the FIRST candidate -- the second
    candidate (ovt:2) must never be touched. Pinned costs match
    `evidence.verify.PLACES_TEXT_SEARCH_USD` / `evidence.web_search.
    TAVILY_SEARCH_USD` exactly, restated here (not imported) so a change to
    either constant makes this test's own math visibly wrong rather than
    silently tracking it."""
    from loci.evidence import web_search
    from loci.validation import google_places

    _FakePlacesClient.instances = []
    _FakeTavilyClient.instances = []
    monkeypatch.setattr(google_places, "GooglePlacesClient", _FakePlacesClient)
    monkeypatch.setattr(web_search, "TavilyWebSearch", _FakeTavilyClient)

    con = _db()
    result = _invoke(monkeypatch, con,
                     ["verify-closures", "--budget", "0.032",
                      "--bbox", "-73.95,40.71,-73.93,40.72"])

    assert result.exit_code == 0, result.stdout
    assert len(_FakePlacesClient.instances) == 1
    assert len(_FakeTavilyClient.instances) == 1
    places, web = _FakePlacesClient.instances[0], _FakeTavilyClient.instances[0]
    assert places.calls == ["Ghost Cafe"]      # only the first candidate
    assert web.calls == []                     # budget refused before the web call
    assert "budget hit" in result.stdout.lower() or "yes" in result.stdout
    assert "$0.032" in result.stdout
