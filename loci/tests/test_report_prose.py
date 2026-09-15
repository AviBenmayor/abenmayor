"""AC-21: exactly one `ProseClient.complete` call, and exactly one
`analysis.spend_ledger` row for it (the estimate-before/true-up-after
pattern corrects that ONE row rather than inserting a second)."""
from __future__ import annotations

import json

import pytest

import loci.db as locidb
from loci.report import clients as clients_mod
from loci.report.clients import ClaudeCliProse, FakeProse, default_clients
from loci.report.enrich import Enrichment
from loci.report.evidence import EvidencePack, POIRow
from loci.report.ledger import Budget
from loci.report.prose import build_prompt, write_prose


def _pack() -> EvidencePack:
    """Minimal hand-built pack -- `prose.py` only reads a handful of fields
    (see `prose._jsonable`), duplicated here rather than imported from
    `tests/test_report_render.py` (pytest's default import mode does not put
    the repo root, only `tests/`, on `sys.path`, so `tests.<module>` cross-
    imports between sibling test files do not resolve during collection)."""
    return EvidencePack(
        address={"address_id": "addr1", "bbl": "3012340001", "lat": 40.71, "lon": -73.95,
                 "street_name": "Test Street", "borough": "BK"},
        scores={"asof": "2026-09-14", "live_hash": "abc123"},
        grades=[{"category": "grocery", "category_label": "Grocery / supermarket",
                 "overall_grade": "C", "verdict": "wait for more evidence",
                 "supply_ratio_vs_base": 0.4}],
        forecast={"p_opening": 0.21, "issued_month": "2026-06", "horizon_months": 12,
                 "model_version": "0.1.1+deadbeef"},
        supply=[POIRow(poi_id="p1", name="Test Grocery", category="grocery", dist_m=50.0,
                       status="open", basis="nyc_dcwp_licenses:valid_to_2030-01-01",
                       colocation=None)],
        demand={"homes_400m": 3000, "median_hh_income": 90000, "revenue_p50": 600000},
        legality={"legality": "commercial", "legality_basis": "commercially zoned (C4-1)",
                  "zonedist1": "C4-1", "histdist": None, "landmark": None},
        context={"neighborhood": "Testville", "borough": "BK", "catchment_m": 500.0},
        provenance={"asof": "2026-09-14"},
    )


def _budget(con, run_id="p1", cap_usd=1.0, dry_run=False):
    return Budget(run_id=run_id, cap_usd=cap_usd, con=con, dry_run=dry_run)


def _db():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def test_build_prompt_carries_no_number_outside_the_evidence():
    pack = _pack()
    system, user = build_prompt(pack, Enrichment())
    doc = json.loads(user)
    assert doc["address_id"] == "addr1"
    assert doc["lead_category"] == "grocery"
    assert "JSON object" in system


def test_write_prose_calls_the_client_exactly_once():
    con = _db()
    budget = _budget(con)
    fake = FakeProse(text=json.dumps({"1": "a", "2": "b", "3": "c", "4": "d"}))
    pack = _pack()
    sections = write_prose(pack, Enrichment(), fake, budget)
    assert len(fake.calls) == 1
    assert sections == {0: "a", 1: "b", 2: "c", 3: "d"}


def test_write_prose_writes_exactly_one_anthropic_ledger_row():
    con = _db()
    budget = _budget(con)
    fake = FakeProse(text=json.dumps({"1": "a", "2": "b", "3": "c", "4": "d"}),
                     input_tokens=13_500, output_tokens=5_800)
    write_prose(_pack(), Enrichment(), fake, budget)
    rows = con.execute(
        "SELECT provider, usd FROM analysis.spend_ledger WHERE provider = 'anthropic'"
    ).fetchall()
    assert len(rows) == 1
    expected = budget.estimate_anthropic(13_500, 5_800)
    assert float(rows[0][1]) == pytest.approx(expected)


def test_write_prose_under_dry_run_makes_no_call_and_only_plans():
    con = _db()
    budget = _budget(con, dry_run=True)
    fake = FakeProse()
    sections = write_prose(_pack(), Enrichment(), fake, budget)
    assert fake.calls == []
    assert sections == {}
    assert len(budget.plan) == 1
    assert con.execute("SELECT count(*) FROM analysis.spend_ledger").fetchone()[0] == 0


def test_malformed_json_reply_falls_back_to_section_zero():
    con = _db()
    budget = _budget(con)
    fake = FakeProse(text="not json at all")
    sections = write_prose(_pack(), Enrichment(), fake, budget)
    assert sections == {0: "not json at all"}


# ------------------------------------------------- ClaudeCliProse (GTM-172)


class _FakeCompletedProcess:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def _patch_subprocess(monkeypatch, stdout: str = "Fake CLI prose.", calls=None):
    calls = calls if calls is not None else []

    def fake_run(cmd, *, capture_output, text, timeout, check):
        calls.append(cmd)
        return _FakeCompletedProcess(stdout)

    monkeypatch.setattr(clients_mod.subprocess, "run", fake_run)
    return calls


def test_claude_cli_prose_calls_subprocess_exactly_once_with_the_prompt(monkeypatch):
    calls = _patch_subprocess(monkeypatch, stdout="Some prose about the address.")
    client = ClaudeCliProse()
    result = client.complete("SYSTEM PROMPT", "USER PROMPT JSON",
                             model="claude-fable-5-1", max_tokens=8000)
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--output-format" in cmd and "text" in cmd
    # the concatenated system+user prompt reaches the CLI, as the argument
    # immediately following -p
    prompt_arg = cmd[cmd.index("-p") + 1]
    assert "SYSTEM PROMPT" in prompt_arg
    assert "USER PROMPT JSON" in prompt_arg
    assert "--model" in cmd and "claude-fable-5-1" in cmd
    assert result.text == "Some prose about the address."
    assert result.plan_billed is True
    assert result.input_tokens > 0 and result.output_tokens > 0


def test_claude_cli_prose_timeout_env_var(monkeypatch):
    monkeypatch.setenv("LOCI_REPORT_CLI_TIMEOUT", "45")
    client = ClaudeCliProse()
    assert client._timeout == 45.0


def test_write_prose_with_cli_client_writes_one_zero_usd_plan_billed_row(monkeypatch):
    """`analysis.spend_ledger.provider` carries a DB-level CHECK constraint
    (sql/033_poi_closure_evidence.sql) that does not yet admit a distinct
    `"claude_cli"` value -- see `ledger.PROSE_RESERVE_USD`'s docstring. The
    plan-billed call is still recorded as exactly one row (AC-21), $0.00,
    with `detail` naming it plan-billed."""
    calls = _patch_subprocess(monkeypatch, stdout=json.dumps(
        {"1": "a", "2": "b", "3": "c", "4": "d"}))
    con = _db()
    budget = _budget(con)
    client = ClaudeCliProse()
    sections = write_prose(_pack(), Enrichment(), client, budget)
    assert len(calls) == 1                          # exactly one CLI invocation
    assert sections == {0: "a", 1: "b", 2: "c", 3: "d"}
    rows = con.execute(
        "SELECT provider, usd, detail FROM analysis.spend_ledger").fetchall()
    assert len(rows) == 1                            # AC-21: exactly one ledger row
    provider, usd, detail = rows[0]
    assert provider == "anthropic"
    assert float(usd) == 0.0
    assert detail.startswith("plan-billed, est ")


def test_default_clients_picks_claude_cli_when_no_api_key_and_claude_on_path(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(
        clients_mod.shutil, "which",
        lambda name: "/usr/local/bin/claude" if name == "claude" else None)

    places, web, prose = default_clients()

    assert places is None
    assert web is None
    assert isinstance(prose, ClaudeCliProse)


def test_default_clients_picks_nothing_when_no_key_and_no_cli(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(clients_mod.shutil, "which", lambda name: None)

    prose = clients_mod._default_prose()

    assert prose is None
