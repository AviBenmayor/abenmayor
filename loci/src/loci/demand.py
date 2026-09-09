"""Necessity/discretionary classification of the 15 categories, DERIVED from
`spend.yaml`'s BLS CEX `income_elasticity` (GTM-109 contrarian review).

`demand.yaml` no longer stores a class per category. It stores the rule --
`cutoff_elasticity` (spend.yaml elasticity strictly above it -> discretionary)
and `low_income_cutoff` -- plus per-category evidence/notes. This module joins
the two files at load time.

Why: the old hand-coded binary contradicted spend.yaml, and no cut point on the
CEX scale reproduced it (hair_barber and tailor_repair share elasticity 0.30
with opposite classes; nails_beauty and grocery share 0.35 with opposite
classes). Cutting at 0.35 reproduces all seven of Meltzer & Schuetz's own
paper-backed rows exactly -- see demand.yaml's header for the full argument and
`tests/test_demand_caveat.py` for the pinned 7/7 check.

Both loaders fail CLOSED, the same way `model/gaps._check_reach_complete` does
for reach.yaml: a category silently missing from either config -- or missing an
elasticity in spend.yaml -- must never be silently treated as either necessity
or discretionary by default.
"""
from __future__ import annotations

import math
import pathlib

import yaml

from loci.categories import CATEGORIES

PKG = pathlib.Path(__file__).resolve().parent
DEMAND_PATH = PKG / "demand.yaml"
SPEND_PATH = PKG / "spend.yaml"

ALLOWED_ELASTICITY = {"necessity", "discretionary"}
# `assumed` is deliberately GONE: GTM-109 converted all eight owner priors into
# `cex` derivations. Re-introducing it would need a new review, so the
# vocabulary refuses it rather than letting a prior slip back in unmarked.
ALLOWED_EVIDENCE = {"paper", "cex"}

#: Attached to every emitted caveat (QUESTIONS X6). Meltzer & Schuetz find race
#: predicts retail NET of income, so an income-only annotation can launder
#: under-provision as "absent demand". Never strip this from a rendered caveat.
X6_DISCLAIMER = (
    "Context only, not a verdict: low supply in a low-income area is at least "
    "as likely to be under-provision as absent demand (QUESTIONS X6)."
)


class DemandConfigError(ValueError):
    """`demand.yaml`/`spend.yaml` are missing a category, missing an
    elasticity, or use a value outside the allowed vocabulary. Raised instead
    of silently defaulting, mirroring `model.gaps._check_reach_complete`."""


def _demand_doc() -> dict:
    return yaml.safe_load(DEMAND_PATH.read_text())


def load_spend_elasticities() -> dict[str, float]:
    """`{category: income_elasticity}` from spend.yaml -- the BLS CEX figure in
    [0, 1] that is the SOLE input to the necessity/discretionary split. Fails
    closed if any category in `loci.categories.CATEGORIES` has no elasticity;
    that is the drift check between categories.yaml and spend.yaml."""
    doc = yaml.safe_load(SPEND_PATH.read_text())
    cats = doc.get("categories", {}) or {}
    out, missing = {}, []
    for c in CATEGORIES:
        entry = cats.get(c) or {}
        e = entry.get("income_elasticity")
        if e is None:
            missing.append(c)
            continue
        try:
            out[c] = float(e)
        except (TypeError, ValueError):
            missing.append(c)
    if missing:
        raise DemandConfigError(
            f"spend.yaml has no usable `income_elasticity` for {len(missing)} of "
            f"{len(CATEGORIES)} categories: {', '.join(missing)}. The demand class is "
            "DERIVED from that number (GTM-109) -- a category without one must not be "
            "silently classified as necessity or discretionary; add it to spend.yaml."
        )
    return out


def load_cutoff_elasticity() -> float:
    """`cutoff_elasticity` from demand.yaml: spend.yaml elasticity STRICTLY
    GREATER than this is discretionary, at or below is necessity. 0.35 is the
    value that reproduces 7/7 of Meltzer & Schuetz's paper-backed rows."""
    doc = _demand_doc()
    if "cutoff_elasticity" not in doc:
        raise DemandConfigError(
            "demand.yaml has no `cutoff_elasticity`. The necessity/discretionary "
            "split is derived from spend.yaml's BLS CEX elasticity by that cut point "
            "(GTM-109); without it there is no rule to apply."
        )
    return float(doc["cutoff_elasticity"])


def classify(elasticity: float, cutoff: float | None = None) -> str:
    """The whole rule, in one place: `elasticity > cutoff` -> 'discretionary',
    else 'necessity'. Strictly greater, so grocery/hardware/nails_beauty at
    exactly 0.35 are necessities."""
    if cutoff is None:
        cutoff = load_cutoff_elasticity()
    return "discretionary" if elasticity > cutoff else "necessity"


def load_demand() -> dict[str, dict]:
    """The derived classification, one entry per category in
    `loci.categories.CATEGORIES`::

        {category: {"income_elasticity": "necessity" | "discretionary",
                    "elasticity": float,     # the spend.yaml CEX number
                    "evidence": "paper" | "cex",
                    "annotate": bool,        # False only for clinic (D30)
                    "note": str}}

    `income_elasticity` keeps its old name and its old two-value vocabulary so
    every existing consumer (model/gaps.py, the schema comments, GTM-110's
    address port) keeps working -- but it is now COMPUTED from
    `elasticity`, never read from demand.yaml.

    Fails closed (`DemandConfigError`) if a category is absent from
    demand.yaml, absent from spend.yaml, or carries an `evidence` value outside
    {paper, cex}.
    """
    doc = _demand_doc()
    cats = doc.get("categories", {}) or {}
    cutoff = load_cutoff_elasticity()
    elasticities = load_spend_elasticities()

    missing = [c for c in CATEGORIES if c not in cats]
    if missing:
        raise DemandConfigError(
            f"demand.yaml is missing {len(missing)} of {len(CATEGORIES)} categories: "
            f"{', '.join(missing)}. A category absent from demand.yaml must not be "
            "silently annotated (or silently skipped) -- add it, with an `evidence` "
            "and a `note`."
        )

    bad_evidence = [(c, (cats[c] or {}).get("evidence")) for c in CATEGORIES
                    if (cats[c] or {}).get("evidence") not in ALLOWED_EVIDENCE]
    if bad_evidence:
        raise DemandConfigError(
            "demand.yaml has invalid values -- evidence not in {paper, cex}: "
            + ", ".join(f"{c}={v!r}" for c, v in bad_evidence)
            + ". (`assumed` was retired by GTM-109: every former owner prior is now "
            "derived from spend.yaml's BLS CEX elasticity.)"
        )

    out = {}
    for c in CATEGORIES:
        entry = cats[c] or {}
        e = elasticities[c]
        out[c] = {
            "income_elasticity": classify(e, cutoff),
            "elasticity": e,
            "evidence": entry["evidence"],
            "annotate": bool(entry.get("annotate", True)),
            "note": entry.get("note", ""),
        }
    return out


def load_low_income_cutoff() -> float:
    """`low_income_cutoff` from demand.yaml -- the share of the citywide MEAN
    household income (ACS B19025/B11001, household-weighted; see
    `loci.grid.acs.load_citywide_mean_hh_income`) below which a hex is
    low-income. Mirrors Meltzer & Schuetz's own cutoff."""
    return float(_demand_doc()["low_income_cutoff"])


def discretionary_categories() -> set[str]:
    """Every category the rule derives as discretionary, regardless of whether
    it is annotated."""
    return {c for c, e in load_demand().items()
            if e["income_elasticity"] == "discretionary"}


def caveat_categories() -> set[str]:
    """The set actually eligible for a demand caveat: discretionary AND not
    excluded from the annotation (`annotate: false` -- clinic, per D30). This
    is what `model/gaps.py` uses; `discretionary_categories()` is the broader
    classification question."""
    return {c for c, e in load_demand().items()
            if e["income_elasticity"] == "discretionary" and e["annotate"]}


def ratio_moe(x: float, x_moe: float | None,
              y: float | None, y_moe: float | None) -> float | None:
    """Standard ACS derived-RATIO margin of error (ACS General Handbook,
    "Calculating Margins of Error for Derived Ratios")::

        R = X / Y
        MOE(R) ~= (1 / Y) * sqrt( MOE(X)^2 + R^2 * MOE(Y)^2 )

    X is the unit's `median_hh_income` with its ACS MOE -- the hex's
    (`analysis.hex_demographics`) for the frozen hex screen, the address's
    tract-level one (`analysis.address_demographics`) for the D38 address
    screen. Y is the citywide MEAN household income and its MOE, from the
    county-level B19025/B11001 aggregates (`loci.grid.acs.
    load_citywide_mean_hh_income`). Both inputs are published at 90%
    confidence, the Census convention, so the result is a 90% MOE too.

    Two stated approximations. (1) The formula is the RATIO form -- the terms
    ADD -- not the PROPORTION form, where X is a subset of Y and the second
    term is subtracted; one unit's median income is not a subset of a citywide
    mean. (2) It assumes X and Y independent. A tract contributes on the order
    of 1e-3 of the citywide aggregate, so the induced correlation is
    negligible; Y's own MOE is under 1% of Y regardless and the numerator term
    dominates by two orders of magnitude.

    Returns None if either MOE is unknown -- the caller must then treat the
    ratio as unclassifiable rather than as exact (FAIL CLOSED: no MOE, no
    assertion, hence no caveat).

    GTM-110 note: this is the shared home of a formula that `model/gaps.py`
    also carries as its own private `_ratio_moe`. gaps.py is FROZEN HISTORY
    (D38: the hex screen takes no new edits), so its copy is deliberately left
    alone rather than rewired to import this one; `tests/test_address_demand.py`
    pins the two implementations against each other so they cannot drift
    silently while both exist.
    """
    if x_moe is None or y in (None, 0):
        return None
    r = x / y
    ym = y_moe or 0.0
    return math.sqrt(x_moe ** 2 + (r ** 2) * (ym ** 2)) / y
