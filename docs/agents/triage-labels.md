# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the
actual label strings used in Linear (team Go To Market).

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the
corresponding label string from this table.

These labels are **not created by setup**. Before the first `/triage` run, check
`list_issue_labels` for the Go To Market team and create any that are missing with
`create_issue_label`. Edit the right-hand column if the team ends up using other names.
