"""AC-21: exactly one `ProseClient.complete` call, and exactly one
`analysis.spend_ledger` row for it (the estimate-before/true-up-after
pattern corrects that ONE row rather than inserting a second).

Also covers investor review item 2 (GTM-172, 2026-09-14/15): `build_prompt`
picks `OUTLINE_FULL` vs `OUTLINE_NO_TRADE` by `render.is_below_c(pack)`, and
item 6: `forecast.model_version` never reaches the evidence JSON handed to
the model."""
from __future__ import annotations

import json

import pytest

import loci.db as locidb
from loci.report import clients as clients_mod
from loci.report.clients import ClaudeCliProse, FakeProse, default_clients
from loci.report.enrich import Enrichment
from loci.report.evidence import EvidencePack, POIRow
from loci.report.ledger import Budget
from loci.report.prose import (
    MAX_NO_TRADE_WORDS, MAX_PROSE_WORDS, OUTLINE_FULL, OUTLINE_NO_TRADE, _jsonable,
    build_prompt, write_prose,
)


def _pack(grade="C") -> EvidencePack:
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
                 "overall_grade": grade, "verdict": "wait for more evidence",
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


# ------------------------------------------------- investor review item 2: outline

def test_build_prompt_picks_the_full_outline_for_a_grade_c_or_better():
    system, _ = build_prompt(_pack(grade="C"), Enrichment())
    assert system == OUTLINE_FULL
    assert str(MAX_PROSE_WORDS) in system


def test_build_prompt_picks_the_no_trade_outline_below_grade_c():
    system, _ = build_prompt(_pack(grade="D"), Enrichment())
    assert system == OUTLINE_NO_TRADE
    assert str(MAX_NO_TRADE_WORDS) in system
    assert "no poi table" in system.lower()


def test_word_budgets_are_700_full_and_250_no_trade():
    assert MAX_PROSE_WORDS == 700
    assert MAX_NO_TRADE_WORDS == 250


# --------------------------------------------- investor review item 1 and 6: rules

def test_both_outlines_forbid_discussing_the_falsification_test():
    for outline in (OUTLINE_FULL, OUTLINE_NO_TRADE):
        assert "falsification" in outline.lower()
        assert "never state whether a falsification test exists" in outline.lower()


def test_both_outlines_forbid_internal_identifiers():
    for outline in (OUTLINE_FULL, OUTLINE_NO_TRADE):
        low = outline.lower()
        assert "run id" in low
        assert "model version" in low
        assert "supply hash" in low


def test_both_outlines_require_a_dated_url_for_every_web_claim():
    for outline in (OUTLINE_FULL, OUTLINE_NO_TRADE):
        assert "published" in outline.lower()
        assert "url" in outline.lower()


def test_jsonable_strips_the_forecast_model_version():
    doc = _jsonable(_pack(), Enrichment())
    assert "model_version" not in (doc["forecast"] or {})
    assert doc["forecast"]["p_opening"] == 0.21     # the rest of the forecast survives


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


def test_totally_unparseable_reply_does_not_leak_raw_text_into_a_section():
    """The pre-fix bug: a reply that is neither JSON nor headinged markdown
    used to land WHOLE in section 0, indistinguishable from real narrative
    (this is exactly what the 2026-09-15 regression reports showed in
    section 1: a raw JSON-looking blob as "prose"). Now a totally
    unparseable reply yields no sections at all -- `render.py` prints the
    honest `PROSE_PARSE_FAILED` line and the raw text moves to the
    provenance footer, never into the body as if it were narrative."""
    con = _db()
    budget = _budget(con)
    fake = FakeProse(text="not json at all, and no numbered headings either")
    sections = write_prose(_pack(), Enrichment(), fake, budget)
    assert sections == {}
    assert sections.called is True
    assert sections.parsed is False
    assert sections.raw_text == "not json at all, and no numbered headings either"


# --------------------------------- CLI-style replies (GTM-183 regression)

def test_cli_style_fenced_json_reply_parses_into_all_four_sections():
    """`ClaudeCliProse` (GTM-172) shells out to `claude -p`, which is not
    guaranteed to return bare JSON the way the metered API does -- observed
    to sometimes wrap its reply in a ``` fence."""
    con = _db()
    budget = _budget(con)
    payload = json.dumps({"1": "one", "2": "two", "3": "three", "4": "four"})
    fake = FakeProse(text=f"```json\n{payload}\n```")
    sections = write_prose(_pack(), Enrichment(), fake, budget)
    assert sections == {0: "one", 1: "two", 2: "three", 3: "four"}
    assert sections.called is True
    assert sections.parsed is True


def test_cli_style_plain_json_reply_parses_into_all_four_sections():
    con = _db()
    budget = _budget(con)
    fake = FakeProse(text=json.dumps({"1": "one", "2": "two", "3": "three", "4": "four"}))
    sections = write_prose(_pack(), Enrichment(), fake, budget)
    assert sections == {0: "one", 1: "two", 2: "three", 3: "four"}


def test_cli_style_preamble_before_json_reply_parses_into_all_four_sections():
    con = _db()
    budget = _budget(con)
    payload = json.dumps({"1": "one", "2": "two", "3": "three", "4": "four"})
    fake = FakeProse(text=f"Here is the requested JSON:\n\n{payload}")
    sections = write_prose(_pack(), Enrichment(), fake, budget)
    assert sections == {0: "one", 1: "two", 2: "three", 3: "four"}


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
