"""Tests for the CHECKPOINT-decision → Linear-ticket coverage audit.

The two subtle failure modes this file exists to pin:
  * D5 must never match inside D50 (the log has both);
  * QUESTIONS.md reuses the `Dnn` prefix for a DIFFERENT id space, so
    "QUESTIONS.md D6" is not a citation of decision D6.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from loci import decisions, tickets

# A miniature decision log: one pre-cutoff entry, one wrapped title, one that is
# only ever named in a QUESTIONS.md citation, one ruling, one uncovered.
FIXTURE = """
## Decision log

**D5 — Pre-cutoff history, no ticket expected.** *(2026-09-01)*
Why: this predates the Linear push.

**D30 — Covered by a plain citation.** *(2026-09-03)*
Why: a ticket cites it.

**D31 — Named only in the QUESTIONS.md form.** *(2026-09-03)*
Why: the only mention is "QUESTIONS.md D31", which is a different id space.

**D32 — Covered by a ruling.** *(2026-09-03, owner)*
Why: owner scope call.

**D33 — Title that wraps
across two lines.** *(2026-09-05)*
Why: nothing cites it.

**D50 — Covered, and must not be satisfied by a D5 citation.** *(2026-09-08)*
Why: boundary case.
"""

DEFS = [
    ("E0 · Foundations", "Cites D30 plainly", 2, 1, "docs",
     "Reasoning.\n\nDone 2026-09-03 (CHECKPOINT D30); Pushed to Linear as GTM-1."),
    ("E0 · Foundations", "Mentions only the QUESTIONS id", 2, 1, "docs",
     "QUESTIONS.md D31 asks about thresholds. Pushed to Linear as GTM-2."),
    ("E0 · Foundations", "Cites D5 and D50, unpushed", 2, 1, "docs",
     "Per D5 the old rule stood; superseded per D50."),
]
RULINGS = {"D32": "Owner scope ruling; no work item."}


@pytest.fixture
def parsed():
    return decisions.parse_decisions(FIXTURE)


@pytest.fixture
def result(parsed):
    return decisions.audit(parsed, DEFS, RULINGS, since_num=29, since_date="2026-09-03")


def verdict(rows, did):
    return next(r.how for r in rows if r.decision.id == did)


def test_parses_ids_dates_and_wrapped_titles(parsed):
    assert [d.id for d in parsed] == ["D5", "D30", "D31", "D32", "D33", "D50"]
    assert parsed[0].date == "2026-09-01"
    assert parsed[4].title == "Title that wraps across two lines"


def test_pre_cutoff_entry_is_out_of_scope(result):
    rows, _ = result
    assert "D5" not in {r.decision.id for r in rows}


def test_covered_by_citation(result):
    rows, _ = result
    assert verdict(rows, "D30") == "ticket"


def test_covered_by_ruling(result):
    rows, _ = result
    row = next(r for r in rows if r.decision.id == "D32")
    assert row.how == "ruling" and row.detail == RULINGS["D32"]


def test_uncovered(result):
    rows, _ = result
    assert verdict(rows, "D33") == "uncovered"


def test_questions_md_citation_is_not_a_decision_citation(result):
    """"QUESTIONS.md D31" must not count — it is a different id space."""
    rows, _ = result
    assert verdict(rows, "D31") == "uncovered"


def test_d5_citation_does_not_cover_d50(result):
    """The D50 verdict must come from the literal `D50`, never from `D5`."""
    rows, _ = result
    assert verdict(rows, "D50") == "ticket"
    assert decisions.cited_ids("superseded per D50.") == {"D50"}
    assert "D50" not in decisions.cited_ids("Per D5 the old rule stood.")


def test_unpushed_lists_definitions_without_a_push_marker(result):
    _, unpushed = result
    assert unpushed == [("Cites D5 and D50, unpushed", "D50")]


def test_a_named_prerequisite_is_not_a_push_marker():
    """"hard prerequisite for GTM-48" must not read as "this was pushed"."""
    defs = [("E0 · Foundations", "New work", 2, 1, "docs",
             "Blocks GTM-48. Done 2026-09-09 (CHECKPOINT D30).")]
    _, unpushed = decisions.audit(decisions.parse_decisions(FIXTURE), defs, {},
                                  since_num=29, since_date="2026-09-03")
    assert [t for t, _ in unpushed] == ["New work"]


def test_h_prefixed_questions_ids_are_ignored():
    assert decisions.cited_ids("QUESTIONS.md H-D9 tracks the mapping.") == set()


def test_state_column_defaults_to_backlog_and_is_honoured():
    """The optional 7th tuple element is the Linear state; 6-tuples stay Backlog."""
    states = {}
    for row in tickets.T:
        states.setdefault(row[6] if len(row) > 6 else "Backlog", 0)
        states[row[6] if len(row) > 6 else "Backlog"] += 1
    assert states["Backlog"] > 0 and states["Done"] > 0


def test_live_repo_has_no_uncovered_decisions():
    rows, _ = decisions.run()
    uncovered = [r.decision.id for r in rows if r.how == "uncovered"]
    assert not uncovered, f"decisions with no ticket and no ruling: {uncovered}"


def test_rulings_reference_real_decisions():
    ids = {d.id for d in decisions.parse_decisions(decisions.CHECKPOINT.read_text())}
    assert set(tickets.RULINGS) <= ids


def test_hook_emits_one_line_of_json_and_exits_zero():
    p = subprocess.run([sys.executable, "-m", "loci.cli", "check-tickets", "--hook"],
                       capture_output=True, text=True)
    assert p.returncode == 0
    payload = json.loads(p.stdout.strip())
    assert set(payload) <= {"decision", "reason", "systemMessage"}
