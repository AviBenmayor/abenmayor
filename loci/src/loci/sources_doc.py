"""Render docs/SOURCES.md — the human-readable mirror of the LIVE registry.

CONTEXT.md v2 (commit bb21798, D116) stopped embedding the source table and
points here instead (§4.6): `src/loci/registry.yaml` is the single source of
truth, and a hand-maintained copy of 44 rows is exactly the kind of doc that
drifts silently. This module renders the non-wishlist sources — the ones
actually in or committed to the pipeline — the same way `loci gen-paid-sources`
renders the wishlist.

Same contract as PAID-SOURCES.md and PORTABILITY.md: one definition
(`registry.yaml`) emits the document, the document is never hand-edited, and
`registry.validate()` fails if it is not a byte-identical render. That check
replaces the old "every dataset_id must appear in CONTEXT.md" drift check,
which broke the moment CONTEXT.md stopped embedding the table it was matching
against.

`status: wishlist` entries are out of scope here — they mirror
docs/PAID-SOURCES.md instead (see registry.py's status split).

Exposed as `loci gen-sources`.
"""
from __future__ import annotations

import pathlib

from loci import registry

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC_PATH = ROOT / "docs" / "SOURCES.md"

ROLE_ORDER = ("poi", "panel", "outcome", "control", "validation", "excluded")
ROLE_LABEL = {
    "poi": "Business locations, present day",
    "panel": "Longitudinal business panel",
    "outcome": "Outcome variables",
    "control": "Controls and context",
    "validation": "Validation",
    "excluded": "Excluded",
}
STATUS_LABEL = {
    "planned": "planned",
    "verified": "verified",
    "deferred": "deferred",
    "excluded": "excluded",
}


def sources() -> list[dict]:
    """Non-wishlist registry entries, role-grouped then id-sorted."""
    rows = [s for s in registry.load()["sources"] if s.get("status") != "wishlist"]
    return sorted(rows, key=lambda s: (ROLE_ORDER.index(s["role"]), s["id"]))


def _flat(text: str) -> str:
    """Collapse a folded YAML block back to one line."""
    return " ".join(str(text).split())


def _one_liner(text: str, limit: int = 180) -> str:
    """First sentence of a bias/note field, for a table cell — truncated, not
    paraphrased, because the point is to name that more sits in the registry."""
    flat = _flat(text)
    if len(flat) <= limit:
        return flat
    first = flat.split(". ", 1)[0]
    if len(first) <= limit:
        return first.rstrip(".") + " …"
    return flat[: limit - 1].rsplit(" ", 1)[0].rstrip(".") + " …"


def dataset_cell(s: dict) -> str:
    if s.get("dataset_id"):
        return f"`{s['dataset_id']}`"
    if s.get("dataset_ids"):
        return ", ".join(f"`{d}`" for d in s["dataset_ids"])
    return "-"


def cost_cell(s: dict) -> str:
    cost = s.get("cost", {})
    amount = cost.get("amount")
    return "$0" if amount == 0 else f"${amount}/{cost.get('unit', '?')}"


def render() -> str:
    rows = sources()
    by_role: dict[str, list[dict]] = {r: [] for r in ROLE_ORDER}
    for s in rows:
        by_role[s["role"]].append(s)
    reg = registry.load()

    md = [
        "# Loci — data source registry (live pipeline)",
        "",
        ("**GENERATED — do not edit.** Rendered by `loci gen-sources` from the "
         "non-wishlist entries in [`src/loci/registry.yaml`](../src/loci/registry.yaml). "
         "`loci check-sources` fails if this file differs from a fresh render, so a claim "
         "here is a claim in the registry with its dated evidence beside it."),
        "",
        (f"Registry verified {reg['verified_on']}. **{len(rows)} sources** in or committed "
         "to the pipeline, grouped by role. The post-raise wishlist is generated "
         "separately into [`docs/PAID-SOURCES.md`](PAID-SOURCES.md); the per-source "
         "portability classing is generated into "
         "[`docs/PORTABILITY.md`](PORTABILITY.md)."),
        "",
    ]
    for role in ROLE_ORDER:
        group = by_role[role]
        if not group:
            continue
        md += [f"## {ROLE_LABEL[role]}", "",
               "| Source | Dataset ID | Tier | Geography | Cost | Status | Known bias |",
               "|---|---|---|---|---|---|---|"]
        for s in group:
            md.append(
                f"| **{s['name']}** | {dataset_cell(s)} | {s['tier']} "
                f"| {s.get('geography', '-')} | {cost_cell(s)} "
                f"| {STATUS_LABEL.get(s['status'], s['status'])} "
                f"| {_one_liner(s.get('bias', '-'))} |"
            )
        md.append("")

    return "\n".join(md) + "\n"


def generate() -> int:
    """Write docs/SOURCES.md. Returns the number of sources rendered."""
    rows = sources()
    DOC_PATH.write_text(render())
    return len(rows)
