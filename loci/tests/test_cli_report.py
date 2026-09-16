"""`loci report` (D99/D100, GTM-171/172) -- the CLI wiring around
`loci.geo.geosearch.resolve` and `loci.report.run.generate` (both already
tested on their own: `tests/test_geosearch.py`, `tests/test_report_*.py`).
This file proves only the CLI's OWN contract end to end: AC-20 (`--dry-run`
prints the plan and makes zero paid calls) and the exit-2 refusal on
`NotInCoverage` (seed "Search rule" / AC-15's message, reused verbatim by
`loci report`).

Own local warehouse fixture (same shape as `test_report_run.py`'s `_db()` --
sibling test modules do not import each other's fixtures under pytest's
default import mode, per that module's own note). `loci.report.clients.
default_clients` is monkeypatched to injected fakes -- never called for real,
per its own docstring ("Never called by a test") -- so this test never
touches the network or a real API key.
"""
from __future__ import annotations

import datetime as dt
import json

import loci.db as locidb
from loci.categories import CATEGORIES

ADDR_ID = "addr1"


def _db():
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
        [(ADDR_ID, "BK", c, 0.9) for c in CATEGORIES])
    con.execute(
        "INSERT INTO analysis.address_demographics (address_id, bbl, acs_year, "
        "median_hh_income, renter_share) VALUES (?,?,?,?,?)",
        [ADDR_ID, "3012340001", 2023, 90_000.0, 0.6])
    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, category, tier, name, geom, "
        "observed_on, attrs) VALUES (?, ?, ?, 1, ?, ST_Point(?, ?), ?, ?)",
        ["poi:open", "nyc_dcwp_licenses", "grocery", "Test Grocery", -73.9500,
         40.7100 + 50.0 / 111_320.0, dt.date(2026, 1, 1),
         json.dumps({"active": "true", "expires": "2030-01-01"})])
    con.execute(
        "INSERT INTO analysis.poi_dedup (poi_id, cluster_id, is_canonical, category) "
        "VALUES (?, ?, TRUE, ?)", ["poi:open", 1, "grocery"])
    return con


def _fake_clients():
    from loci.report.clients import FakePlaces, FakeProse

    places = FakePlaces({})
    web = None
    prose = FakeProse(text=json.dumps({"1": "s1", "2": "s2", "3": "s3", "4": "s4"}))
    return places, web, prose


def _invoke(monkeypatch, con, args, tmp_path):
    from typer.testing import CliRunner

    from loci import cli
    from loci.report import cache, clients

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cli.locidb, "connect", lambda *a, **k: con)
    monkeypatch.setattr(clients, "default_clients", _fake_clients)
    return CliRunner().invoke(cli.app, args)


# --------------------------------------------------------------- AC-20

def test_dry_run_prints_plan_and_spends_nothing(monkeypatch, tmp_path):
    con = _db()
    result = _invoke(monkeypatch, con, ["report", ADDR_ID, "--dry-run"], tmp_path)

    assert result.exit_code == 0, result.stdout
    assert "run_id=" in result.stdout
    assert "$" in result.stdout
    n_ledger_rows = con.execute(
        "SELECT count(*) FROM analysis.spend_ledger").fetchone()[0]
    assert n_ledger_rows == 0


def test_dry_run_prints_the_report_path_and_total_usd(monkeypatch, tmp_path):
    """AC-20 end to end through the command: the CLI's own contract is that
    it prints path/total/run_id on a real run, and prints the estimated
    total plus zero-spend confirmation on a dry run -- proved here by
    shelling out through `cli.app`, not by calling `report.run.generate`
    directly (that path is already covered by `tests/test_report_run.py`)."""
    con = _db()
    result = _invoke(monkeypatch, con,
                     ["report", ADDR_ID, "--dry-run", "--cap", "2.0"], tmp_path)

    assert result.exit_code == 0, result.stdout
    assert "dry run" in result.stdout
    assert "zero paid calls" in result.stdout


def test_dry_run_accepts_no_closure_checks(monkeypatch, tmp_path):
    con = _db()
    result = _invoke(monkeypatch, con,
                     ["report", ADDR_ID, "--dry-run", "--no-closure-checks"], tmp_path)

    assert result.exit_code == 0, result.stdout
    assert "zero paid calls" in result.stdout
    n_ledger_rows = con.execute(
        "SELECT count(*) FROM analysis.spend_ledger").fetchone()[0]
    assert n_ledger_rows == 0


# --------------------------------------------------------------- exit 2

def test_not_in_coverage_exits_2_with_the_exact_message(monkeypatch, tmp_path):
    from loci.geo import geosearch

    con = _db()
    monkeypatch.setattr(geosearch, "geocode", lambda *a, **k: None)
    result = _invoke(monkeypatch, con,
                     ["report", "1 Nowhere Ave, Staten Island"], tmp_path)

    assert result.exit_code == 2
    assert "not in Loci coverage" in result.stdout


# ------------------------------------------- owner ruling R3: --category

def test_category_option_forces_the_lead_category(monkeypatch, tmp_path):
    con = _db()
    out = tmp_path / "forced.md"
    result = _invoke(monkeypatch, con,
                     ["report", ADDR_ID, "--category", "hardware", "--no-cache",
                      "--out", str(out)], tmp_path)

    assert result.exit_code == 0, result.stdout
    assert "lead category **hardware**" in out.read_text()


def test_a_demoted_category_is_refused_with_exit_2_and_named_in_the_message(
        monkeypatch, tmp_path):
    """Owner ruling R3: `headline: false` (clinic, tailor_repair, hair_barber
    -- the D30 precedent) may not lead a memo by accident. The refusal names
    the flag that overrides it, so the analyst has to say it out loud."""
    con = _db()
    result = _invoke(monkeypatch, con,
                     ["report", ADDR_ID, "--category", "tailor_repair", "--no-cache",
                      "--out", str(tmp_path / "r.md")], tmp_path)

    assert result.exit_code == 2
    assert "REFUSE" in result.stdout
    assert "--allow-demoted" in result.stdout
    assert not (tmp_path / "r.md").exists()


def test_allow_demoted_lets_a_demoted_category_lead(monkeypatch, tmp_path):
    con = _db()
    out = tmp_path / "demoted.md"
    result = _invoke(monkeypatch, con,
                     ["report", ADDR_ID, "--category", "tailor_repair", "--allow-demoted",
                      "--no-cache", "--out", str(out)], tmp_path)

    assert result.exit_code == 0, result.stdout
    assert "lead category **tailor_repair**" in out.read_text()


def test_an_unknown_category_is_refused_with_exit_2(monkeypatch, tmp_path):
    con = _db()
    result = _invoke(monkeypatch, con,
                     ["report", ADDR_ID, "--category", "taco_truck", "--no-cache"],
                     tmp_path)
    assert result.exit_code == 2
    assert "REFUSE" in result.stdout


# --------------------------- owner ruling R2: same-BBL conflict gates the run

def test_a_same_bbl_conflict_exits_3_prints_the_conflict_and_writes_nothing(
        monkeypatch, tmp_path):
    import loci.report.render as render_mod

    docs = tmp_path / "recommendations"
    docs.mkdir()
    (docs / "graham-ave-376-2026-09-13.md").write_text(
        "# Hand memo\n\nBBL 3012340001\n\n| lead_category | 0.30 / **tailor_repair** |\n")
    monkeypatch.setattr(render_mod, "OUT_DIR", docs)
    con = _db()
    out = tmp_path / "r.md"
    result = _invoke(monkeypatch, con,
                     ["report", ADDR_ID, "--no-cache", "--out", str(out)], tmp_path)

    assert result.exit_code == 3
    assert "same-BBL conflict" in result.stdout
    assert "tailor_repair" in result.stdout
    assert not out.exists()
    assert con.execute("SELECT count(*) FROM analysis.spend_ledger").fetchone()[0] == 0
