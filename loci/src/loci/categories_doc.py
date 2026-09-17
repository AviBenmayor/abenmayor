"""Render docs/CATEGORIES.md — the human-readable mirror of categories.py.

CONTEXT.md v2 (commit bb21798, D116) stopped embedding the fifteen-category
table and points here instead (§4.2): `src/loci/categories.py` (slugs, tiers,
labels, tier weights) and `src/loci/categories.yaml` (the NAICS 2022 anchor
and the `headline` demotion flag, D30/owner ruling 2026-09-14) are the single
sources of truth. A hand-maintained copy of the table is exactly the kind of
doc CLAUDE.md's "machine-check the docs against the code" habit exists to
kill — `tests/test_category_registry.py` asserts this file's table is a
byte-for-byte match on order, numbering and tier weights every time the suite
runs.

Same contract as `loci gen-paid-sources` / `loci gen-sources`: one definition
emits the document, the document is never hand-edited.

Exposed as `loci gen-categories`.
"""
from __future__ import annotations

import pathlib

import yaml

from loci.categories import CATEGORIES, TIER_WEIGHTS

ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = pathlib.Path(__file__).resolve().parent
DOC_PATH = ROOT / "docs" / "CATEGORIES.md"
CATEGORIES_YAML = PKG / "categories.yaml"

TIER_LABEL = {1: "T1 Necessities", 2: "T2 Personal services",
              3: "T3 Food & gathering", 4: "T4 Civic & wellness"}

#: Demoted from headline claims by owner ruling (CONTEXT.md §4.2, D30 precedent,
#: 2026-09-14) — carried here only for the footnote, not re-derived from it;
#: `headline: false` in categories.yaml is still the source of truth.
DEMOTED_NOTE = (
    "**Demoted from headline claims** (owner ruling 2026-09-14, D30 precedent): a gap "
    "in this category can still lead nowhere near as often as it looks like it should "
    "be a coverage hole rather than a real gap. It keeps its row, ratio and place on "
    "the map — `model/recommend.non_headline_categories()` only blocks it from being "
    "the LEAD card. See CONTEXT.md §4.2."
)


_COUNT_WORDS = {15: "Fifteen", 16: "Sixteen", 17: "Seventeen", 18: "Eighteen"}


def _count_word(n: int) -> str:
    """The bundle size as a word, so the sentence cannot lie about the table."""
    return _COUNT_WORDS.get(n, str(n))


def _yaml() -> dict:
    return yaml.safe_load(CATEGORIES_YAML.read_text())["categories"]


def _definitions(ymeta: dict) -> list[str]:
    """One block per slug that pins a `definition:` in categories.yaml -- the
    inclusion rule a hand count must use to count the same things the feeds
    do. Rendered verbatim so the doc cannot paraphrase it."""
    rows = [(cat, ymeta[cat.slug]["definition"].strip())
            for cat in CATEGORIES.values()
            if ymeta.get(cat.slug, {}).get("definition")]
    if not rows:
        return []
    out = ["", "### Pinned definitions", "",
           ("A `definition:` in categories.yaml is the inclusion rule a hand "
            "enumeration (ground truth, base rate) counts against. Verbatim.")]
    for cat, text in rows:
        out += ["", f"- **{cat.label}** (`{cat.slug}`): {text}"]
        if ymeta[cat.slug].get("ships_as") == "signal":
            out += ["", ("  Ships as a **non-filtering signal** (owner ruling 2026-09-17, "
                         "docs/CATEGORY-EXPANSION.md §4): `headline: false`, it can reorder "
                         "or annotate a card and never gates one; its gaps are not "
                         "opportunity claims.")]
    return out


def render() -> str:
    ymeta = _yaml()
    md = [
        "# Loci — the daily-needs bundle",
        "",
        ("**GENERATED — do not edit.** Rendered by `loci gen-categories` from "
         "[`src/loci/categories.py`](../src/loci/categories.py) (slugs, tiers, labels, "
         "tier weights) and [`src/loci/categories.yaml`](../src/loci/categories.yaml) "
         "(the NAICS 2022 anchor and the headline-demotion flag). "
         "`tests/test_category_registry.py` fails if this table drifts from either file."),
        "",
        "## The daily-needs bundle",
        "",
        (f"{_count_word(len(CATEGORIES))} categories in four weighted tiers. Tier "
         "weights are judgment calls, stated explicitly so a reader can disagree "
         "with them precisely."),
        "",
        "| Tier | w | # | Category | NAICS 2022 | Headline |",
        "|---|---|---|---|---|---|",
    ]
    prev_tier = None
    for i, cat in enumerate(CATEGORIES.values(), 1):
        naics = ", ".join(ymeta.get(cat.slug, {}).get("naics_2022", []) or ["-"])
        headline = "no" if ymeta.get(cat.slug, {}).get("headline") is False else "yes"
        if cat.tier != prev_tier:
            tier_cell = f"**{TIER_LABEL[cat.tier]}**"
            weight_cell = f"**{TIER_WEIGHTS[cat.tier]:.2f}**"
            prev_tier = cat.tier
        else:
            tier_cell = weight_cell = ""
        md.append(f"| {tier_cell} | {weight_cell} | {i} | {cat.label} | {naics} "
                  f"| {headline} |")

    demoted = [c.label for c in CATEGORIES.values()
               if ymeta.get(c.slug, {}).get("headline") is False]
    md += ["", "### Demoted from headline claims", "", DEMOTED_NOTE, ""]
    for label in demoted:
        md.append(f"- {label}")
    md += _definitions(ymeta)
    md.append("")

    return "\n".join(md) + "\n"


def generate() -> int:
    """Write docs/CATEGORIES.md. Returns the number of categories rendered."""
    DOC_PATH.write_text(render())
    return len(CATEGORIES)
