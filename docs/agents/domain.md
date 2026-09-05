# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring
the codebase.

This is a **multi-context repo**: every top-level directory is an independent project with
its own vocabulary. Never merge two projects' glossaries.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root. It lists each project (context) and where its
  `CONTEXT.md` lives. Read only the contexts relevant to the directory you are working in.
- **The project's `CONTEXT.md`**: `<project>/docs/CONTEXT.md` (preferred, per the
  Cross-Project Standards in `CLAUDE.md`) or `<project>/CONTEXT.md` for older projects.
- **Decision records**:
  - `docs/adr/` at the repo root for repo-wide decisions (cross-project standards).
  - `<project>/docs/adr/` for project-scoped decisions.
  - Projects that keep a **`docs/CHECKPOINT.md` decision log** (D-numbered, dated,
    append-only, with *superseded* markers) use that log as their ADR record. Read it before
    proposing anything, and do not relitigate a logged decision. `<project>/docs/adr/` is
    optional there and supplements the log; it does not replace it.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't
suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs`
and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually
get resolved. A new project directory with no `CONTEXT.md` is the expected state.

## File structure

```
/
├── CONTEXT-MAP.md                   ← index of contexts
├── docs/adr/                        ← repo-wide decisions
├── loci/
│   └── docs/
│       ├── CONTEXT.md               ← charter + glossary
│       ├── CHECKPOINT.md            ← decision log (ADR record for this project)
│       └── adr/                     ← optional, supplements the log
├── hearth/
│   ├── CONTEXT.md
│   └── docs/adr/
└── <other-project>/                 ← no CONTEXT.md yet; created lazily
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a
hypothesis, a test name), use the term as defined in that project's `CONTEXT.md`. Don't
drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing
language the project doesn't use (reconsider) or there's a real gap (note it for
`/domain-modeling`, or as a `docs/QUESTIONS.md` entry in projects that keep one).

## Flag ADR conflicts

If your output contradicts an existing ADR or a logged decision, surface it explicitly rather
than silently overriding:

> _Contradicts D9 (PostGIS abandoned for DuckDB), but worth reopening because…_
