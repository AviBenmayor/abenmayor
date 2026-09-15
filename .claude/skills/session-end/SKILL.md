---
name: session-end
description: Run the session-end ritual for a project in this repo — one Haiku agent updates CHECKPOINT.md and appends batched QUESTIONS.md entries from dictated text, runs the project's ticket hook so no decision ships without a ticket, and Fable verifies the header isn't stale. Use at the end of a working session, when wrapping up, or when the owner says "wrap up", "close out the session", "update the checkpoint", or "let's stop here". Takes the project directory as an argument (e.g. `loci`); if omitted, derive it from the current git branch.
---

# Session end

This replaces re-reading CLAUDE.md's "Session operating model" prose each session.
Follow the steps below in order.

## Steps

### 1. Resolve the project

Same rule as `session-start`: use the argument passed to this skill, or if none was
given, take the text before the first `/` in `git branch --show-current`. Call this
`$PROJECT`. If `$PROJECT/docs/CHECKPOINT.md` does not exist, stop — nothing to update.

### 2. Collect the batched questions

Gather every `docs/QUESTIONS.md` entry that was deferred during the session under the
scope-creep pressure valve (interesting-but-off-focus items noted instead of coded).
These live in this conversation's own turns, not in a file yet — write them out as plain
dictated text: one line per question, with enough context that Haiku can paste it in
verbatim rather than infer what was meant.

### 3. Dispatch ONE Haiku agent with dictated text

Post the one-line spec first: *"Dispatching Haiku to update `$PROJECT/docs/CHECKPOINT.md`
and append N batched questions."* Then send Haiku a prompt that supplies, as already-
decided dictated text (Haiku executes, it does not interpret or draft):

- The new **phase line** (replaces the `Phase:` line under `## Current state`).
- Each new **decision log entry**, dated, appended under `## Decision log` — every entry
  must state what was decided **and why**; a decision that reverses an earlier one marks
  the old entry *superseded*, never deletes it.
- The **session log** entry (new `### YYYY-MM-DD — Session N` heading at the end of the
  decision log, matching the existing heading style).
- The **next actions** list (replaces `## Next actions`).
- The **questions from step 2**, appended to `docs/QUESTIONS.md` Part B.

### 4. Run the project's ticket hook — same edit as the decision

A CHECKPOINT decision with no matching ticket definition blocks every session on the
tree at the next `check-tickets` run. The Haiku agent writes the decision log entry and
the ticket definition in **one edit**, then runs the hook before finishing:

```bash
grep -n 'check-tickets\|^tickets:' "$PROJECT/Makefile"   # find this project's target
```

For `loci`, that's `uv run loci check-tickets` (also folded into `make check`). If
`$PROJECT/Makefile` has no such target, note that in the handback — don't invent one.

Done when: the hook target is found and run clean (or its absence is explicitly noted),
never skipped silently.

### 5. Verify the header isn't stale

Fable does this directly — it's a cheap probe, not a dispatch. The `**Last updated:**`
summary line and the `Phase:` line must both reflect the same latest state as the
session log entry Haiku just appended; the next-actions list must match the body.
Literal check:

```bash
# Most recent session-log heading and the decision id it introduces
LATEST=$(grep -n '^### 20' "$PROJECT/docs/CHECKPOINT.md" | tail -1)
DID=$(echo "$LATEST" | grep -oE 'D[0-9]+' | tail -1)
echo "$LATEST"

# That decision id must appear in both the top summary line and the Phase: line —
# if either grep comes back empty, the header is stale
grep -n "^\*\*Last updated:\*\*.*$DID" "$PROJECT/docs/CHECKPOINT.md"
grep -n "^Phase:.*$DID" "$PROJECT/docs/CHECKPOINT.md"
```

If either grep is empty, the header did not get updated — send Haiku back to fix it
before treating the ritual as done. Do not paper over a stale header by editing it
yourself; the point of the hook is that Haiku's dictated edit is the single source of
truth for what changed.

### 6. Commit only if asked

Never commit as part of this ritual by default. Only run `git add` / `git commit` if the
owner explicitly asked for it in this session — CHECKPOINT/QUESTIONS updates otherwise
stay as uncommitted working-tree changes for the owner to review.

## Reference

### Concurrent sessions

If step 3 in `session-start` found peers on `$PROJECT` earlier this session, message them
again before this ritual's CHECKPOINT/QUESTIONS/ticket edit lands — the same collision
risk applies on the way out as on the way in.
