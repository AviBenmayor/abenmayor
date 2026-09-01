"""Research questions: parse docs/QUESTIONS.md and guard it against drift.

QUESTIONS.md is the build compass — every question names the ticket(s) or epic that
answer it. `validate()` asserts those references are real, so the questions and the
ticket plan (src/loci/tickets.py) cannot silently diverge. Exposed as
`loci check-questions`.

Block syntax the parser expects:

    ### M1 — Question text
    - **Status:** open
    - **Prediction:** P3            (Part A only; "—" when none)
    - **Answered by:** `Ticket title` · `Ticket title`   (Part A)
    - **Unblocks:** E3 · Residual and Panel              (Part B)
"""
from __future__ import annotations

import pathlib
import re

from loci.tickets import EPICS, T, map_labels

ROOT = pathlib.Path(__file__).resolve().parents[2]
QUESTIONS_PATH = ROOT / "docs" / "QUESTIONS.md"

VALID_STATUS = {"open", "in-progress", "answered", "deferred", "dropped"}
PREDICTIONS = {"P1", "P2", "P3"}
PROJECT_ID = re.compile(r"^[MDXTC]\d+$")      # Part A: what the project answers
HOMEWORK_ID = re.compile(r"^H-[LDMT]\d+$")    # Part B: what the owner must research
HEADING = re.compile(r"^### (?P<id>\S+) — (?P<text>.+)$")
FIELD = re.compile(r"^- \*\*(?P<key>[^*]+):\*\* ?(?P<val>.*)$")
CITED = re.compile(r"`([^`]+)`")

# Tickets in these epics carrying these labels decide whether the finding is defensible;
# each should sit behind some question. A miss is a warning, not a failure.
LOAD_BEARING_EPICS = {"E3 · Residual and Panel", "E4 · Validation and Artifact"}
LOAD_BEARING_LABELS = {"rigor", "critical"}


def parse(text: str) -> list[dict]:
    """Return one dict per `### ID — text` block with its bullet fields, lower-cased keys."""
    blocks: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            cur = {"id": m["id"], "text": m["text"].strip(), "fields": {}}
            blocks.append(cur)
            continue
        if cur is None:
            continue
        f = FIELD.match(line)
        if f:
            cur["fields"][f["key"].strip().lower()] = f["val"].strip()
    return blocks


def validate() -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Empty errors means QUESTIONS.md agrees with tickets.py."""
    text = QUESTIONS_PATH.read_text()
    blocks = parse(text)
    titles = {t[1] for t in T}
    epics = {name for name, _, _ in EPICS}
    errors: list[str] = []
    warnings: list[str] = []

    ids = [b["id"] for b in blocks]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate question ids: {dupes}")

    claimed: set[str] = set()
    cited: set[str] = set()
    n_project = n_homework = 0

    for b in blocks:
        qid, f = b["id"], b["fields"]
        is_project = bool(PROJECT_ID.match(qid))
        is_homework = bool(HOMEWORK_ID.match(qid))
        if not (is_project or is_homework):
            errors.append(f"{qid}: id matches neither [MDXTC]<n> nor H-[LDMT]<n>")
            continue

        status = f.get("status")
        if status not in VALID_STATUS:
            errors.append(f"{qid}: status {status!r} not in {sorted(VALID_STATUS)}")

        if is_project:
            n_project += 1
            pred = f.get("prediction", "—")
            if pred not in PREDICTIONS | {"—", "-", ""}:
                errors.append(f"{qid}: prediction {pred!r} is not P1/P2/P3 or —")
            elif pred in PREDICTIONS:
                claimed.add(pred)
            answered = f.get("answered by")
            if not answered:
                errors.append(f"{qid}: missing 'Answered by'")
            else:
                for title in CITED.findall(answered):
                    cited.add(title)
                    if title not in titles:
                        errors.append(f"{qid}: cites unknown ticket {title!r}")
        else:
            n_homework += 1
            epic = f.get("unblocks")
            if epic not in epics:
                errors.append(f"{qid}: unblocks unknown epic {epic!r}")

    for p in sorted(PREDICTIONS - claimed):
        errors.append(f"prediction {p} is not claimed by any question")

    for epic, title, _prio, _est, labels, _desc in T:
        if epic in LOAD_BEARING_EPICS and title not in cited:
            if set(map_labels(labels).split(",")) & LOAD_BEARING_LABELS:
                warnings.append(f"load-bearing ticket not behind any question: {title!r} ({epic})")

    if not errors:
        print(f"ok — {n_project} project questions, {n_homework} homework items, "
              f"{len(cited)} tickets cited, P1–P3 all claimed, no tickets.py drift")
    return errors, warnings
