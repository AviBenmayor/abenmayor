---
name: research-question
description: Run a Loci research question end to end through its fixed framework — interview, seed, data audit, notebook build, methodology review, answer, tickets, checkpoint. Use when the owner poses a new Loci research question ("how long do favorable conditions last," "which neighborhoods are next," etc.), when asked to "start a research question," "run RQ-NNN," or "answer this as an RQ." Takes the question (or an existing RQ-NNN id to resume) as an argument.
---

# Research question

Runs a Loci research question through `docs/research/README.md`'s fixed sequence, using
`loci research` (`src/loci/research.py`) as the scaffold and drift gate. This replaces
ad-hoc analysis: nothing that would produce a numeric answer to a Loci question skips
this sequence.

Model routing for every step below follows CLAUDE.md's Cross-Project Standards: Fable
(the executive) dispatches and relays, never reads large files or runs analyses itself.
Sonnet runs and interprets analyses and writes the code; Opus (or the project's
specialist agents) is the judgment layer only — methodology review and verdicts, not
analysis execution. Haiku does mechanical edits (CHECKPOINT, ticket text from dictated
decisions). Every dispatch gets a one-line spec shown to the owner first.

## Before anything: check for concurrent sessions

Per CLAUDE.md — if another session may be working the same project, coordinate scope
before touching `cli.py`, `tickets.py`, `docs/CHECKPOINT.md`, or claiming a D-id/RQ
number. Run cheap probes (`git status --short`, `git diff --stat`) and check for an
uncommitted diff or a peer message before step 7 (tickets) and step 8 (checkpoint) in
particular — those are the two steps that write to shared files.

## Steps

### 1. Interview

Invoke the `interview` skill on the question as the owner posed it. Surfaces unit of
analysis, what the outcome/"favorable"/success means, scope, and constraints. Fable
runs this directly with the owner — it is a conversation, not a dispatch.

### 2. Seed

Invoke the `seed` skill on the interview transcript to crystallize it into the seed
YAML (goal, constraints, acceptance_criteria, ontology_schema, evaluation_principles,
exit_conditions, metadata — see `src/loci/research_template/SEED.yaml` for the shape
and `docs/research/RQ-001-regime-durability/SEED.yaml` for a worked example).

### 3. Scaffold and save the seed

```
loci research new <slug> --title "<Title>"
```

This creates `docs/research/RQ-NNN-<slug>/` at the next free number with the full
template file set (`SEED.yaml`, `QUESTION.md`, `DATA-AUDIT.md`, `notebook.ipynb`,
`ANSWER.md`, `STATUS.yaml`, all stages `pending`). Overwrite the scaffolded
`SEED.yaml` with the seed from step 2, then fill `QUESTION.md`'s sections (Question as
asked, Interview rulings, Definitions, Tiers/unit, Out of scope) from the same
material — every constraint in `SEED.yaml` should be traceable to a line in
`QUESTION.md`. Set `question: {status: done}` in `STATUS.yaml` once it's filled.

### 4. Data audit — Sonnet dispatch

One-line spec: *"Dispatching Sonnet to write DATA-AUDIT.md for RQ-NNN: every input the
question needs, checked against registry.yaml and the warehouse."*

The dispatched agent fills `DATA-AUDIT.md`'s table (Pillar | Input | Source | Publisher
| History | Grain | Status | Gap → ticket) by checking `src/loci/registry.yaml` and
the warehouse for what's already landed. Every `missing`/`partial` row must cite a
ticket id — if the ticket doesn't exist yet, note it in the handback rather than
inventing an id; step 7 creates real ones. Set `data_audit: {status: done}` in
`STATUS.yaml` when finished, or leave it `pending`/`blocked` with a reason if genuinely
not startable yet (e.g. a peer session owns it — see RQ-001's STATUS.yaml for exactly
that case).

### 5. Build the notebook — Sonnet dispatch

One-line spec: *"Dispatching Sonnet to build and run RQ-NNN's notebook: sections 1-7
from the warehouse."*

Fill the notebook's ten fixed sections (see `docs/research/README.md` §4) using data
named in `DATA-AUDIT.md`. This is analysis execution — running and interpreting code
against a clear spec — so it stays on Sonnet, not Opus. Run it with:

```
loci research run <RQ-id>
```

(needs `nbformat`/`nbclient` — `uv add` them if `loci research run` reports they're
missing; that's a one-line pyproject.toml edit, cheap enough not to need its own
dispatch, but still surface it to the owner before running `uv add`). Set
`notebook: {status: done}` once it executes clean end to end.

### 6. Methodology / verdict review — Opus

Dispatch the project's specialist agents on the executed notebook, not on a description
of it:

- **contrarian** — adversarial pass: coverage bias, reverse causality, a data gap
  wearing a costume, parameter artifacts, saturation.
- **statistician** — identification, censoring/survival handling, multiple testing,
  whether the baseline comparison is honest.
- Add **urban-planner** (ground-truth plausibility), **investor** (does this answer a
  buyer's decision), or **data-scientist** (modeling-choice review) when the question
  calls for it.

This is the judgment layer CLAUDE.md reserves for Opus — verdicts on whether the
result survives scrutiny, not the analysis run itself (that already happened in step
5). Feed their verdicts into `ANSWER.md`'s Confidence section and Validation table.

### 7. Write ANSWER.md

Fill `ANSWER.md`: the plain-language answer (versioned, labeled provisional if it is),
Confidence, the Validation table (every row `RUN` with its result inline, or
`TICKETED` with an id — never silently skipped), and Gaps → tickets. Copy the Answer
section into the notebook's section 8 cell so the executed notebook stands alone. Set
`answer: {status: done}` in `STATUS.yaml`.

### 8. Generate tickets

Before editing `tickets.py`: confirm no peer session holds it (see the concurrent-
session check above). Add ticket definitions to `src/loci/tickets.py` for the RQ
parent and its subtickets (framework/infra follow-ups, data gaps from step 4, the
review findings from step 6, a recurring drift re-run if the question warrants one),
under the **"Research questions"** Linear milestone (create the milestone via the
Linear MCP connector if it doesn't exist yet — epics are Milestones, not Projects, per
CLAUDE.md). Each ticket's description carries the reasoning, not just the task. Then:

```
loci gen-tickets
```

to regenerate `docs/TICKETS.md` and the Linear export files, and push through the
Linear MCP connector.

### 9. Checkpoint

One edit: append the dated `docs/CHECKPOINT.md` decision entry for this RQ *and* its
ticket definition in `tickets.py` together (the existing `check-tickets` hook already
blocks a decision with no ticket — this is that same rule, applied here). Follow the
`session-end` skill's step 4 pattern (Haiku, dictated text) rather than hand-drafting
prose.

### 10. Exit gate

```
loci research check
loci check-tickets
```

Both must exit 0 before the RQ is considered shipped for this session. `loci research
check` fails on any RQ folder missing a required stage file (without an honest
`STATUS.yaml` pending/blocked entry) or citing a ticket id not defined in
`tickets.py`; `loci check-tickets` fails on a CHECKPOINT decision with no ticket. A
non-zero exit here is not a warning — it means step 6-9 above left something
inconsistent, and the session is not done until it's fixed or explicitly marked
pending/blocked with a reason.

## Reference

- `docs/research/README.md` — the framework spec these steps implement.
- `src/loci/research.py` — `loci research new|check|run`.
- `docs/research/RQ-001-regime-durability/` — the first RQ, worked (in progress).
