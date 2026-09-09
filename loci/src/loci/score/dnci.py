"""Daily Needs Completeness Index (GTM-29 calibration + GTM-30 index).

Per category, a saturating score s_c = 1 - exp(-n_c / k_c): the first reachable
establishment lands near 0.55, later ones add little (the 12th bodega barely
matters). Categories combine by a WEIGHTED GEOMETRIC MEAN, never arithmetic —
this is the methodological crux (CONTEXT.md §4.4). An arithmetic mean lets a hex
with 50 restaurants and no grocery/pharmacy/laundry score well, which is exactly
the failure the thesis exists to detect; only the geometric form punishes zeros.

k_c (GTM-29): essentials are tight (one grocery ~ sufficient), food is loose (one
restaurant in a 10-min walk is thin, not complete). Anchored so the first
establishment scores ~0.55 for essentials. Open question #2 — tune vs observed
count distributions later.
"""
from __future__ import annotations

import math

from loci.categories import CATEGORIES, TIER_WEIGHTS

EPS = 0.01

# Per-category saturation constant. Lower k = saturates faster (one is nearly enough).
_K_BY_TIER = {1: 1.25, 2: 1.5, 3: 3.0, 4: 1.75}
K = {slug: _K_BY_TIER[c.tier] for slug, c in CATEGORIES.items()}

# Category weight = its tier's weight split evenly among the tier's categories,
# so all category weights sum to 1.0 (a proper weighted geometric mean).
_tier_counts: dict[int, int] = {}
for _c in CATEGORIES.values():
    _tier_counts[_c.tier] = _tier_counts.get(_c.tier, 0) + 1
W = {slug: TIER_WEIGHTS[c.tier] / _tier_counts[c.tier] for slug, c in CATEGORIES.items()}


def category_score(slug: str, n: int) -> float:
    return 1.0 - math.exp(-n / K[slug])


def dnci_from_counts(counts: dict[str, int]) -> float:
    """Weighted geometric mean of saturating category scores. counts maps
    category -> n_reachable; missing categories count as 0."""
    logsum = 0.0
    for slug, w in W.items():
        s = category_score(slug, counts.get(slug, 0))
        logsum += w * math.log(max(s, EPS))
    return math.exp(logsum)


# ---------------------------------------------------------------------------
# RETIRED UNDER D38 (2026-09-09). `build_dnci` -- which materialised
# analysis.hex_dnci, one DNCI per hex per walk threshold -- is DELETED with the
# table. The DNCI was the E3 causal-supply-model input (regress DNCI on
# density/income/transit, read the residual as opportunity); the SCOPE
# CORRECTION at the top of CHECKPOINT.md records that E3 answered the wrong
# question, and D38 then moved the geography off the hex entirely. Nothing on
# the address path reads it.
#
# `dnci_from_counts` and `category_score` STAY: they are pure functions with no
# database at all, and tests/test_dnci.py uses them to pin the index's two
# load-bearing properties -- the geometric mean punishes a missing essential
# rather than letting an abundance of restaurants paper over it, and each
# category saturates. Those are project decisions worth keeping executable
# whatever geography the screen runs on.
# ---------------------------------------------------------------------------
