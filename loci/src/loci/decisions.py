"""Audit the CHECKPOINT decision log against the ticket definitions.

Every decision that changed the code or the method should leave a Linear ticket
behind it; otherwise the work is invisible to the tracker and a later session
re-derives it. `loci check-tickets` (and the Claude Code Stop hook that calls it
with `--hook`) enforces that.

A decision is COVERED when any of:

  (a) it is listed in `tickets.RULINGS` — pure owner scope/policy rulings that
      produce no work item. An explicit human statement outranks an inferred
      citation, so this is checked first;
  (b) a ticket definition in `tickets.T` CITES it, in the CHECKPOINT form
      ("CHECKPOINT D37", "per D38", "(D53)", "D38/D49") — NOT in the
      QUESTIONS.md form ("QUESTIONS.md D6", "H-D9"), because QUESTIONS.md
      reuses the D-prefix for a completely different id space;
  (c) it predates `tickets.TICKET_COVERAGE_SINCE` — pre-Linear history.

Pure text + regex over two files. No DB, no network; runs in milliseconds.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "docs" / "CHECKPOINT.md"

# `**D39 — title that may wrap` … `.** *(2026-09-05, owner)*`
_ENTRY_RE = re.compile(r"^\*\*(D\d+)\s+—\s+", re.MULTILINE)
_DATE_RE = re.compile(r"\*\((\d{4}-\d{2}-\d{2})")
# The house-style push marker — "Pushed to Linear 2026-09-05 as GTM-109",
# "DONE 2026-09-05 (CHECKPOINT D38, Linear GTM-25)". Deliberately NOT any
# mention of a GTM id: tickets routinely name OTHER issues as prerequisites
# ("hard prerequisite for GTM-48"), and counting those as proof of a push would
# silently exempt exactly the new definitions this check exists to catch.
_GTM_RE = re.compile(r"\b(?:Linear|as)\s+GTM-\d+\b")

# A bare decision reference. `(?!\d)` is what keeps D5 from matching inside D50.
# `(?<![\w-])` rejects `H-D9` (a QUESTIONS id) and any mid-word D.
_CITE_RE = re.compile(r"(?<![\w-])D\s?(\d+)(?!\d)")

# Text immediately before a match that means "this is a QUESTIONS id, not a
# decision id": `QUESTIONS.md D6`, `QUESTIONS D9`, and the second element of
# `QUESTIONS.md D6/D8` or `QUESTIONS.md D6, D8`.
_QUESTIONS_PREFIX_RE = re.compile(r"QUESTIONS(?:\.md)?\s*(?:D\s?\d+\s*[,/]\s*)*$")


@dataclass
class Decision:
    """One `**Dnn — title.**` entry in the CHECKPOINT decision log."""

    id: str
    title: str
    date: str
    body: str

    @property
    def num(self) -> int:
        return int(self.id[1:])


@dataclass
class Coverage:
    """Verdict for one in-scope decision."""

    decision: Decision
    how: str  # "ticket" | "ruling" | "uncovered"
    detail: str = ""
    tickets: list[str] = field(default_factory=list)


def parse_decisions(text: str) -> list[Decision]:
    """Pull every `**Dnn — …**` entry out of a CHECKPOINT.md body.

    Titles may wrap across lines; the date lives in the trailing `*(date, …)*`.
    Ids are not unique in the log (parallel sessions collided on D22/D23/D28),
    so the first entry for an id wins and later ones are ignored — the collisions
    are all pre-cutoff history.
    """
    starts = [m.start() for m in _ENTRY_RE.finditer(text)]
    out: list[Decision] = []
    seen: set[str] = set()
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[start:end]
        did = _ENTRY_RE.match(chunk).group(1)
        if did in seen:
            continue
        seen.add(did)
        head, _, rest = chunk.partition(".**")
        title = head.split("—", 1)[1].strip().replace("\n", " ") if "—" in head else ""
        title = re.sub(r"\s+", " ", title)
        dm = _DATE_RE.search(rest[:120])
        out.append(Decision(id=did, title=title, date=dm.group(1) if dm else "",
                            body=rest.strip()))
    return out


def cited_ids(text: str) -> set[str]:
    """Decision ids cited by a block of ticket prose, in the CHECKPOINT form only."""
    found: set[str] = set()
    for m in _CITE_RE.finditer(text):
        before = text[max(0, m.start() - 40):m.start()]
        if _QUESTIONS_PREFIX_RE.search(before):
            continue
        found.add(f"D{int(m.group(1))}")
    return found


def audit(decisions: list[Decision], ticket_defs, rulings: dict[str, str],
          since_num: int, since_date: str,
          pushed_without_id: frozenset[str] = frozenset(),
          ) -> tuple[list[Coverage], list[tuple[str, str]]]:
    """Return (coverage rows for in-scope decisions, unpushed ticket rows).

    `ticket_defs` is `tickets.T`: (epic, title, priority, estimate, labels,
    description[, state]) — read the description positionally at index 5, NOT as
    `row[-1]`, which is the optional state on the Done entries. An "unpushed" ticket cites an
    in-scope decision but carries no `GTM-nn` anywhere in its description — the
    definition exists but was never pushed to Linear — unless its title is in
    `pushed_without_id`, the audited list of tickets that are live in Linear but
    never recorded their id in the description.
    """
    by_decision: dict[str, list[str]] = {}
    unpushed: list[tuple[str, str]] = []
    for row in ticket_defs:
        title, desc = row[1], row[5]
        cites = {d for d in cited_ids(f"{title}\n{desc}")
                 if int(d[1:]) >= since_num}
        for d in cites:
            by_decision.setdefault(d, []).append(title)
        if cites and not _GTM_RE.search(desc) and title not in pushed_without_id:
            unpushed.append((title, ",".join(sorted(cites, key=lambda s: int(s[1:])))))

    rows: list[Coverage] = []
    for dec in decisions:
        if dec.num < since_num or (dec.date and since_date and dec.date < since_date):
            continue
        if dec.id in rulings:
            rows.append(Coverage(dec, "ruling", rulings[dec.id]))
        elif dec.id in by_decision:
            rows.append(Coverage(dec, "ticket", "", sorted(by_decision[dec.id])))
        else:
            rows.append(Coverage(dec, "uncovered"))
    return rows, unpushed


def run(checkpoint: pathlib.Path | None = None):
    """Audit the live repo. Returns (coverage rows, unpushed rows)."""
    from loci import tickets

    text = (checkpoint or CHECKPOINT).read_text()
    return audit(parse_decisions(text), tickets.T, tickets.RULINGS,
                 int(tickets.TICKET_COVERAGE_SINCE[1:]),
                 tickets.TICKET_COVERAGE_SINCE_DATE,
                 tickets.PUSHED_WITHOUT_ID)
