"""The fail-closed category-registry invariants (GTM-112, docs/CATEGORY-EXPANSION.md).

Every gate in the expansion checklist that can be checked WITHOUT a warehouse
lives here. The point is not to re-test what each module already tests
(`reach.load_reach`, `zbp.py`, `demand.load_demand` all raise on their own);
it is to make the SET of surfaces a slug must land on machine-readable, so a
16th slug added to `categories.py` alone fails the suite instead of silently
appearing in the screen with a missing row somewhere downstream.

TWO EXCEPTIONS ARE PINNED, NOT FIXED — both are DELIBERATE and documented at
their own site: `bank` has no `benchmarks.yaml` row ("not listable as a
small-business comp", benchmarks.yaml:111) and `clinic` has no `GOOGLE_TYPES`
mapping (`doctor` is every solo physician's office, a different population from
clinic's 621111/621493 anchor — google_places.py:81, D30). They are asserted as
an EXACT set rather than tolerated, so a new slug cannot join them quietly:
adding a 16th category without a benchmarks row or a Google type widens the set
and fails, which forces the same explicit ruling these two got.
"""
from __future__ import annotations

import pathlib
import re

import yaml

from loci.categories import CATEGORIES, TIER_WEIGHTS
from loci.sources.universal.foursquare_places import GROUP_CATEGORY, LEAF_CATEGORY
from loci.validation.google_places import GOOGLE_TYPES

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "loci"
DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"
SLUGS = frozenset(CATEGORIES)

#: Pre-existing holes. NOT a licence to add more — the assertions below demand
#: equality, so a new slug landing in either set fails the test.
KNOWN_MISSING_BENCHMARK = frozenset({"bank"})
KNOWN_MISSING_GOOGLE_TYPE = frozenset({"clinic"})
#: Slugs admitted at G0 whose FITTED artifacts cannot exist before the first
#: ingest on the announced supply hash (owner ruling 2026-09-17, GTM-198 G8).
#: Asserted as an EXACT set: the moment `loci supply-ratio --fit-baseline`
#: writes the row, this constant must be emptied or the test fails -- a fit
#: that lands silently is the same defect as a row that never lands.
UNFITTED_PENDING_INGEST = frozenset({"bathhouse_sauna"})


def _load(rel: str) -> dict:
    return yaml.safe_load((PKG / rel).read_text())


# --------------------------------------------------------------- the yaml rows
# Each entry: (file, dotted path to the block keyed by category slug).
REQUIRED_BLOCKS = [
    ("categories.yaml", "categories"),
    ("reach.yaml", "reach_m"),
    ("reach_tiers.yaml", "categories"),
    ("conveniences.yaml", "distance_min"),
    ("demand.yaml", "categories"),
    ("spend.yaml", "categories"),
    ("zbp_naics.yaml", "categories"),
]


def test_every_slug_has_a_row_in_every_required_yaml():
    for rel, key in REQUIRED_BLOCKS:
        block = _load(rel)[key]
        assert SLUGS - set(block) == set(), f"{rel}:{key} is missing rows"
        assert set(block) - SLUGS == set(), f"{rel}:{key} has rows for unknown slugs"


def test_categories_yaml_rows_are_complete():
    for slug, row in _load("categories.yaml")["categories"].items():
        for field in ("label", "naics_2022", "naics_2017", "sources"):
            assert row.get(field), f"{slug} has no {field} in categories.yaml"


def test_naics_2022_codes_exist_in_the_census_structure_file():
    codes = {
        line.split(",", 1)[0].strip().strip('"')
        for line in (PKG / "naics" / "naics_2022.csv").read_text().splitlines()[1:]
    }
    for slug, row in _load("categories.yaml")["categories"].items():
        naics = row["naics_2022"]
        for code in (naics if isinstance(naics, list) else [naics]):
            assert str(code) in codes, f"{slug}: NAICS 2022 {code} not in naics_2022.csv"


# ------------------------------------------------------------- adapter vocabs
def test_every_slug_is_reachable_from_the_universal_adapters():
    """A slug no universal adapter can emit is a category that can only ever be
    missing — the D29 'data gap wearing a costume' by construction."""
    src = _load("categories.yaml")["categories"]
    for adapter in ("osm", "overture"):
        covered = {s for s, row in src.items() if (row.get("sources") or {}).get(adapter)}
        assert SLUGS - covered == set(), f"categories.yaml: no {adapter} vocab for these slugs"
    fsq = set(GROUP_CATEGORY.values()) | set(LEAF_CATEGORY.values())
    assert SLUGS - fsq == set(), "foursquare_places.py maps no leaf/group to these slugs"


# ------------------------------------------------------- generated model files
def test_generated_model_tables_cover_every_slug():
    """`loci supply-ratio --fit-baseline` (D73) and `loci density-elasticity fit`
    (D70) must have been re-run after the slug landed; a category with no
    baseline has no ratio and no regime note on the card."""
    block = _load("model/density_elasticity.yaml")["categories"]
    assert SLUGS - set(block) == set(), "density_elasticity.yaml has not been re-fit"
    block = _load("model/supply_baseline.yaml")["categories"]
    unfitted = SLUGS - set(block)
    assert unfitted == UNFITTED_PENDING_INGEST, (
        f"supply_baseline.yaml unfitted set {sorted(unfitted)} != the sanctioned "
        f"{sorted(UNFITTED_PENDING_INGEST)} (GTM-198 G8: a baseline lands with "
        "the first ingest on the announced hash, never by hand)"
    )


# ------------------------------------------------------------ the pinned holes
def test_benchmark_rows_exist_except_the_one_known_hole():
    b = _load("benchmarks.yaml")
    for key in ("categories", "occupancy_cost_ratio"):
        missing = SLUGS - set(b[key])
        assert missing == KNOWN_MISSING_BENCHMARK, (
            f"benchmarks.yaml:{key} missing {sorted(missing)}; the only sanctioned "
            f"hole is {sorted(KNOWN_MISSING_BENCHMARK)}"
        )


def test_google_type_map_covers_every_slug_except_the_one_known_hole():
    missing = SLUGS - set(GOOGLE_TYPES)
    assert missing == KNOWN_MISSING_GOOGLE_TYPE, (
        f"GOOGLE_TYPES missing {sorted(missing)}; a slug with no Google type can "
        f"never reach coverage grade A (recommend_grades.yaml coverage.validated_grade)"
    )


# ------------------------------------------------------------------- the tiers
def test_tier_weights_partition_the_bundle():
    assert set(TIER_WEIGHTS) == {c.tier for c in CATEGORIES.values()}
    assert abs(sum(TIER_WEIGHTS.values()) - 1.0) < 1e-9


# --------------------------------------------------------------- docs vs code
_ROW = re.compile(r"^\|.*\|\s*(\d{1,2})\s*\|\s*([^|]+?)\s*\|")


def test_context_section_2_1_table_matches_categories_py():
    """The docs-drift half of the CLAUDE.md 'machine-check the docs against the
    code' habit. CONTEXT.md v2 (D116) stopped embedding this table and points
    at docs/CATEGORIES.md instead (§4.2); this test now targets that generated
    doc, which `loci gen-categories` renders from categories.py."""
    text = (DOCS / "CATEGORIES.md").read_text()
    body = text.split("## The daily-needs bundle", 1)[1].split("\n### ", 1)[0]
    rows = [m.groups() for m in (_ROW.match(ln) for ln in body.splitlines()) if m]
    assert [int(n) for n, _ in rows] == list(range(1, len(CATEGORIES) + 1)), (
        "docs/CATEGORIES.md does not number exactly 1..N"
    )
    assert [label for _, label in rows] == [c.label for c in CATEGORIES.values()], (
        "docs/CATEGORIES.md labels/order have drifted from categories.py"
    )
    for w in TIER_WEIGHTS.values():
        assert f"**{w:.2f}**" in body, f"docs/CATEGORIES.md does not state tier weight {w:.2f}"
    from loci import categories_doc
    assert text == categories_doc.render(), (
        "docs/CATEGORIES.md differs from a fresh render — it is GENERATED; "
        "run `loci gen-categories`"
    )
