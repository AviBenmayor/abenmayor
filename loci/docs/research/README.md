# The research-question framework

Every Loci research question — "how long does a favorable regime last," "which
neighborhoods are next," whatever comes after — follows this exact sequence and lands
in the same folder shape. This file is the spec; `src/loci/research.py` is the
machinery that enforces it, and `.claude/skills/research-question/SKILL.md` (repo root
`.claude/skills/`) is the operator sequence a session runs to produce one.

**The rule: every RQ follows this exactly.** No RQ skips a stage or invents its own
file names. A stage can be honestly *not done yet* (see STATUS.yaml below) — it can
never be silently skipped.

## The fixed sequence

1. **Interview** — Socratic pass with the owner that surfaces the question's hidden
   assumptions (unit of analysis, what "favorable"/the outcome means, scope).
2. **Seed** — crystallize the interview into `SEED.yaml`: goal, constraints,
   acceptance criteria, ontology schema, evaluation principles, exit conditions.
   Immutable once written — a changed question is a new generation, not an edit.
3. **Data audit** — `DATA-AUDIT.md`: every input the question needs, its source,
   history depth, grain, and status (present/partial/missing), with every gap mapped
   to a ticket.
4. **Build** — `notebook.ipynb`: the ten fixed sections (Question, Data & provenance,
   Build panel, Method, Results, Sensitivity, Drivers, Validation, ANSWER, Caveats &
   next data), executed end to end from the warehouse.
5. **Answer** — `ANSWER.md`: the plain-language answer, its confidence, a validation
   table (each row RUN with a result or TICKETED with an id), and gaps mapped to
   tickets.
6. **Review** — methodology/verdict pass (contrarian + statistician at minimum; add
   urban-planner/investor/data-scientist when the question calls for it).
7. **Tickets** — every gap and follow-up generated through `src/loci/tickets.py`,
   never hand-written, under the "Research questions" Linear milestone.
8. **Checkpoint** — a dated `docs/CHECKPOINT.md` decision entry for the RQ, with its
   ticket defined in the same edit (the existing `check-tickets` hook already enforces
   this repo-wide; it applies to research-question decisions too).

## The folder

```
docs/research/RQ-NNN-<slug>/
├── SEED.yaml         # stage 2 — immutable
├── QUESTION.md        # stage 2 — human-readable mirror of the seed
├── DATA-AUDIT.md       # stage 3
├── notebook.ipynb     # stage 4
├── ANSWER.md            # stage 5
└── STATUS.yaml        # per-stage status; see below
```

`NNN` is a zero-padded 3-digit sequence number, assigned by `loci research new` as the
next free number — never picked by hand, so two concurrent sessions can't collide on
one.

## STATUS.yaml and the gate

A stage's file does not have to exist yet for the RQ folder to pass the gate — but
that has to be said explicitly, not left to a missing file being silently ignored.
`STATUS.yaml` carries one entry per stage:

```yaml
seed: {status: done}
question: {status: pending, reason: "not started"}
data_audit: {status: pending, reason: "being written by another agent"}
notebook: {status: blocked, reason: "waiting on GTM-999 (macro ingest)"}
answer: {status: pending, reason: "not started"}
```

- `status: done` (the default if a stage is omitted, or if there is no STATUS.yaml at
  all) means the corresponding file **must exist**. A `done` stage whose file is
  missing fails the check — this is what stops a folder from silently regressing
  (e.g. `ANSWER.md` deleted after being marked done).
- `status: pending` or `status: blocked` requires a `reason`, and lets the file be
  absent without failing the check — the honest way to say "not there yet, and here's
  why."

`loci research check` — see `src/loci/research.py` — also scans `QUESTION.md`,
`DATA-AUDIT.md`, and `ANSWER.md` for `GTM-\d+` ticket citations and fails if any of
them is not defined in `src/loci/tickets.py`. This is the same drift discipline as
`loci check-tickets` and `loci check-questions`, applied to the research-question
folders.

## The gate

```
loci research check
```

Run it the way `check-sources`/`check-tickets`/`check-questions` are run: as part of
`make check`, and as an exit gate at the end of the research-question skill sequence,
alongside `loci check-tickets`. Non-zero exit blocks the session; the printed lines
say exactly which folder and which stage.

## Commands

```
loci research new <slug> [--title "..."]   # scaffold RQ-NNN-<slug>/ at the next free NNN
loci research check                        # the drift gate above
loci research run <RQ-id>                  # execute notebook.ipynb in place (nbclient)
```

`loci research run` needs `nbformat` and `nbclient`, which are not yet in
`pyproject.toml` — add them (`uv add nbformat nbclient`) before the first real run.
