---
name: session-start
description: Run the session-start ritual for a project in this repo — cheap git probes, one Sonnet agent briefing from CHECKPOINT.md/QUESTIONS.md, and one narrow deliverable proposed via AskUserQuestion buttons. Use at the start of a working session, when resuming a project, or when the owner says "let's start on <project>", "what's the state of <project>", "continue where we left off", "pick up where we left off", or "brief me". Takes the project directory as an argument (e.g. `loci`); if omitted, derive it from the current git branch.
---

# Session start

This replaces re-reading CLAUDE.md's "Session operating model" prose each session.
Follow the steps below in order instead of re-deriving them.

Fable (the executive) runs steps 1–3 directly — they are cheap probes, never worth an
agent. Steps 4–5 are the only dispatch in this ritual.

## Steps

### 1. Resolve the project

Use the argument passed to this skill as the project directory name under the repo
root. If no argument was given, run:

```bash
git branch --show-current | cut -d'/' -f1
```

The text before the first `/` is the project (branch `loci/eny-investment-and-query-app`
→ project `loci`). Call this `$PROJECT` below. If `$PROJECT/docs/CHECKPOINT.md` does not
exist, say so and stop — this project has not adopted the document trio yet, so there is
nothing to brief from.

### 2. Cheap probes only

Run directly, scoped to the project:

```bash
git status --short
git diff --stat
git log --oneline -5
```

Done when: you can state in one line whether the tree is clean, what's uncommitted, and
what landed most recently. Do not read any file content yet — that's step 4's job.

### 3. Check for peer sessions

Run `ListAgents` (or this environment's equivalent listing of other active Claude
sessions/teammates). If any peer is working on `$PROJECT`, message them before you touch
`$PROJECT/docs/CHECKPOINT.md`, `docs/QUESTIONS.md`, or any index/hash file — collisions
on these are exactly what `project_concurrent_sessions` exists to prevent. If the tool is
unavailable in this environment, note that and proceed; do not block the ritual on it.

### 4. Dispatch ONE Sonnet agent to brief

One dispatch, not a chain. Before sending it, post the one-line spec to the owner:
*"Dispatching Sonnet to brief from `$PROJECT/docs/CHECKPOINT.md` and `QUESTIONS.md`."*
Then send a prompt that:

- Reads `$PROJECT/docs/CHECKPOINT.md` and `$PROJECT/docs/QUESTIONS.md` in full.
- Does **not** read `$PROJECT/docs/CHECKPOINT-ARCHIVE.md` (if present) unless a specific
  decision id needs context the live file doesn't carry — the archive exists precisely
  so routine briefings don't have to load it.
- Returns exactly this shape, nothing else:
  1. **Charter one-liner** — what the project is, in one sentence.
  2. **Phase** — the current phase/state line from CHECKPOINT.md.
  3. **Scope arc** — has scope shifted or been corrected since the charter was written
     (check for a scope-correction banner)?
  4. **Uncommitted work** — anything in flight the session log flags as unfinished.
  5. **Blockers table** — verbatim, with each row's unblocking action.
  6. **Top 3 load-bearing open questions** — from QUESTIONS.md, ranked by what most
     narrows the next decision, not by recency.
  7. **Next actions** — verbatim from CHECKPOINT.md's next-actions list.

Done when: the agent has returned all seven fields, or explicitly marked one empty (no
guessing where a field is missing).

### 5. Digest and propose one deliverable

Compress the agent's report into **10 lines or fewer** for the owner — this is Fable's
own synthesis, not a re-paste of the agent's output. Then propose **one narrow
deliverable** for the session using `AskUserQuestion` with buttons. Never propose a
deliverable, or any other question to the owner, as plain prose — the owner's standing
rule is buttons only. Wait for the owner's pick before dispatching any work agent.

## Reference

### Model routing

Route every dispatch by task type, not by convenience:

| Model | Use for |
|---|---|
| **Haiku** | Dictated edits only: commits, doc regeneration, CHECKPOINT/QUESTIONS edits from text the owner already decided, file moves, running an existing command and reporting its output. |
| **Sonnet** | Reading and summarizing docs or diffs, drafting tickets, writing straightforward code against a spec that's already clear. This briefing step is a Sonnet job. |
| **Opus** (or a specialist agent: `contrarian`, `statistician`, `data-scientist`, `investor`, `urban-planner`) | Anything judgment-heavy: modeling choices, methodology review, whether a result survives scrutiny, and — per the owner's 2026-09-08 tightening — **all analysis and design work**, not just the hardest cases. |

The 2026-09-08 tilt narrowed Haiku specifically: it no longer interprets output or drafts
tickets from scratch, only executes what's already been dictated. When in doubt between
Sonnet and Opus for anything that involves interpreting a result rather than transcribing
one, pick Opus.

### Dispatch-spec rule

Every dispatch in this ritual — the step-4 briefing agent and anything the owner picks in
step 5 — gets a one-line spec shown to the owner *before* it runs, so it can be vetoed
before tokens are spent. Independent dispatches run in parallel, never queued one after
another when nothing depends on the prior result.
