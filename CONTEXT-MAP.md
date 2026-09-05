# Context Map

This repo holds independent projects, one per top-level directory. Each is its own bounded
context with its own glossary. Consumer rules are in `docs/agents/domain.md`.

| Context | Directory | Glossary | Decision record |
| --- | --- | --- | --- |
| Loci | `loci/` | `loci/docs/CONTEXT.md` | `loci/docs/CHECKPOINT.md` decision log |
| Hearth | `hearth/` | `hearth/CONTEXT.md` | none yet |

Directories not listed (`agents/`, `alpha_research/`, `arbitrage/`, `claude-beacon/`,
`dashboard/`, `habit_tracker/`, `mag/`, `mta_time/`, `notchopped/`, `professor/`) have no
`CONTEXT.md` yet. Add a row when `/domain-modeling` creates one; place new glossaries at
`<project>/docs/CONTEXT.md`.

Repo-wide decisions go in `docs/adr/`.
