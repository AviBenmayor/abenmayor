"""Income elasticity of demand, per category (docs/CHECKPOINT.md demand-caveat
ticket). Loads `demand.yaml` (Meltzer & Schuetz 2012 for the categories they
cover, owner priors elsewhere -- see that file's header) and validates it
fails closed, the same way `model/gaps._check_reach_complete` does for
reach.yaml: a category silently missing from the config must never be
silently treated as either necessity or discretionary by default.
"""
from __future__ import annotations

import pathlib

import yaml

from loci.categories import CATEGORIES

PKG = pathlib.Path(__file__).resolve().parent
DEMAND_PATH = PKG / "demand.yaml"

ALLOWED_ELASTICITY = {"necessity", "discretionary"}
ALLOWED_EVIDENCE = {"paper", "assumed"}


class DemandConfigError(ValueError):
    """The demand config is missing a category or uses a value outside the
    allowed vocabulary. Raised instead of silently defaulting, mirroring
    `model.gaps._check_reach_complete`."""


def load_demand() -> dict[str, dict]:
    """The checked-in demand classification: {category: {"income_elasticity":
    ..., "evidence": ..., "note": ...}}. Fails closed (raises
    `DemandConfigError`) if any of the 15 categories in
    `loci.categories.CATEGORIES` is absent, or if a value falls outside the
    allowed vocabulary -- never defaults a missing/bad entry to either class."""
    doc = yaml.safe_load(DEMAND_PATH.read_text())
    cats = doc.get("categories", {})

    missing = [c for c in CATEGORIES if c not in cats]
    if missing:
        raise DemandConfigError(
            f"demand.yaml is missing {len(missing)} of {len(CATEGORIES)} categories: "
            f"{', '.join(missing)}. A category absent from demand.yaml must not be "
            "silently classified as necessity or discretionary -- add it."
        )

    bad_elasticity, bad_evidence = [], []
    for cat, entry in cats.items():
        if cat not in CATEGORIES:
            continue  # not our concern here; extra rows are harmless
        elasticity = entry.get("income_elasticity")
        evidence = entry.get("evidence")
        if elasticity not in ALLOWED_ELASTICITY:
            bad_elasticity.append((cat, elasticity))
        if evidence not in ALLOWED_EVIDENCE:
            bad_evidence.append((cat, evidence))

    if bad_elasticity or bad_evidence:
        parts = []
        if bad_elasticity:
            parts.append(
                "income_elasticity not in {necessity, discretionary}: "
                + ", ".join(f"{c}={v!r}" for c, v in bad_elasticity)
            )
        if bad_evidence:
            parts.append(
                "evidence not in {paper, assumed}: "
                + ", ".join(f"{c}={v!r}" for c, v in bad_evidence)
            )
        raise DemandConfigError("demand.yaml has invalid values -- " + "; ".join(parts))

    return {c: cats[c] for c in CATEGORIES}


def load_low_income_cutoff() -> float:
    """`low_income_cutoff` from demand.yaml -- the share of the citywide
    population-weighted mean household income below which a hex is
    `income_class = 'low'` (mirrors Meltzer & Schuetz's own cutoff)."""
    doc = yaml.safe_load(DEMAND_PATH.read_text())
    return float(doc["low_income_cutoff"])


def discretionary_categories() -> set[str]:
    """Convenience: the set of category slugs classified discretionary."""
    demand = load_demand()
    return {c for c, e in demand.items() if e["income_elasticity"] == "discretionary"}
