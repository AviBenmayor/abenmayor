"""The 15 daily-needs categories and their tier weights (CONTEXT.md §2.1).

City-agnostic domain vocabulary. Every adapter normalizes into these slugs; the
scorer weights by tier. No source-specific or NYC-specific names here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    slug: str
    tier: int
    label: str


CATEGORIES: dict[str, Category] = {c.slug: c for c in (
    # Tier 1 — necessities
    Category("grocery",       1, "Grocery / supermarket"),
    Category("convenience",   1, "Bodega / convenience"),
    Category("pharmacy",      1, "Pharmacy"),
    Category("laundry",       1, "Laundromat / dry cleaner"),
    # Tier 2 — personal services
    Category("hair_barber",   2, "Hair / barber"),
    Category("nails_beauty",  2, "Nail / beauty"),
    Category("tailor_repair", 2, "Tailor / repair"),
    # Tier 3 — food & gathering
    Category("restaurant",    3, "Restaurant"),
    Category("cafe_bakery",   3, "Cafe / bakery"),
    Category("bar",           3, "Bar / pub"),
    # Tier 4 — civic & wellness
    Category("childcare",     4, "Childcare"),
    Category("clinic",        4, "Clinic / urgent care"),
    Category("fitness",       4, "Fitness"),
    Category("bank",          4, "Bank branch"),
    Category("hardware",      4, "Hardware / home supply"),
    # 16th slug, AC-1 Step 1 (CONTEXT.md §7, GTM-198). Landed through the
    # fail-closed checklist (docs/CATEGORY-EXPANSION.md) as far as G0; gates
    # G3-G8 need a warehouse fit and are NOT passed -- see the CHECKPOINT entry
    # that records them. A destination amenity, not a daily need: the
    # prevalence-gap premise (near-zero willingness to travel) does not hold,
    # so its gaps annotate, they do not lead (categories.yaml headline: false).
    Category("bathhouse_sauna", 4, "Bathhouse / sauna"),
)}

TIER_WEIGHTS: dict[int, float] = {1: 0.40, 2: 0.20, 3: 0.25, 4: 0.15}


def tier_of(slug: str) -> int:
    return CATEGORIES[slug].tier
