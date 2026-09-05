# Issue tracker: Linear

Issues, specs, and epics for every project in this repo live in **Linear**, not GitHub Issues.
Use the `claude.ai Linear` MCP connector for all operations. GitHub is the code host only.

## Workspace layout

| Thing | Where it lives |
| --- | --- |
| Workspace | `avi-benmayor` (https://linear.app/avi-benmayor) |
| Team | **Go To Market**, issue key `GTM` |
| Project | one Linear **Project per top-level repo directory** (e.g. `loci/` → project "Loci", `https://linear.app/avi-benmayor/project/loci-723fa10296fb`) |
| Epic | a **Milestone inside the project**. Never create a Project per epic; that fragments the workspace. |
| Ticket | an issue in the project, assigned to a milestone. Every issue belongs to a milestone; an orphan is a bug. |

Infer the project from the directory the work is in. If no Linear project exists for that
directory yet, ask before creating one with `save_project` (team Go To Market, name = the
directory's project name).

## Conventions

- **Find the project**: `list_projects` (team Go To Market) and `get_project`.
- **Create an issue**: `save_issue` with team `Go To Market`, the directory's project,
  a milestone, a title, and a markdown description. **The description carries the
  reasoning, not just the task**: say why this approach and what breaks under the
  alternative. Use real newlines, not `\n` escapes.
- **Read an issue**: `get_issue` by identifier (`GTM-42`), then `list_comments` on it.
- **List issues**: `list_issues` filtered by project, state, label, or milestone.
- **Comment on an issue**: `save_comment`.
- **Apply / remove labels**: `save_issue` with the updated label set. Labels are
  team-scoped; check `list_issue_labels` first and create missing ones with
  `create_issue_label` rather than inventing near-duplicates.
- **Close**: `save_issue` setting state to `Done`, or `Canceled` for wontfix, with a
  closing comment.
- **Priority**: reserve **Urgent** for load-bearing items: checks that decide whether the
  work is valid, and cheap verifications that de-risk large downstream commitments.

## Generated tickets

Projects that generate tickets from code (Loci: `loci gen-tickets` emits
`docs/TICKETS.md`, `docs/linear-import.csv`, `docs/linear-tickets.json`) treat the
generator as the source of truth. When a skill wants to publish a batch of tickets for such
a project, **add them to the project's definition list and regenerate**, then push the JSON
payload. Do not hand-write issues that the generator will not know about.

Single ad-hoc issues (a bug found mid-session, a triaged request) can be created directly.

## If the Linear tools are missing

MCP servers connected mid-session are invisible until Claude Code restarts. If no
`mcp__claude_ai_Linear__*` tools appear, check `claude mcp list`; a `✔ Connected` server
whose tools do not appear means restart, not reconfigure. Do not fall back to `gh issue`.

## Pull requests as a triage surface

**PRs as a request surface: no.** This is a solo repo; GitHub PRs are not read as feature
requests and do not enter the triage queue.

## When a skill says "publish to the issue tracker"

Create a Linear issue in the directory's project (see Generated tickets first).

## When a skill says "fetch the relevant ticket"

`get_issue` on the `GTM-nn` identifier, plus `list_comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: one issue labelled `wayfinder:map` holding the Notes / Decisions-so-far / Fog
  body, in the directory's project.
- **Child ticket**: a **sub-issue** of the map (set the parent on `save_issue`), labelled
  `wayfinder:<type>` (`research` / `prototype` / `grilling` / `task`). Once claimed it is
  assigned to the driving dev.
- **Blocking**: Linear's native **blocked by** relation where the connector can set it;
  otherwise a `Blocked by: GTM-nn, GTM-nn` line at the top of the child description. A
  ticket is unblocked when every blocker is Done.
- **Frontier query**: `list_issues` for the map's open sub-issues, drop any with an open
  blocker or an assignee; first in map order wins.
- **Claim**: assign the issue to yourself, the session's first write.
- **Resolve**: `save_comment` with the answer, set state `Done`, then append a context
  pointer (gist + link) to the map's Decisions-so-far.
