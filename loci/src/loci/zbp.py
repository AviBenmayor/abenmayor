"""NAICS crosswalk loader for Census ZBP/CBP validation (docs/CHECKPOINT.md
ZBP-validation ticket). Loads `zbp_naics.yaml` and validates it fails closed,
the same way `demand.load_demand()` does for demand.yaml and
`model.gaps._check_reach_complete` does for reach.yaml: a category silently
missing from the crosswalk must never be silently treated as "zero
establishments" -- it must raise, because that silence is indistinguishable
from a real gap.
"""
from __future__ import annotations

import pathlib
import re

import yaml

from loci.categories import CATEGORIES

PKG = pathlib.Path(__file__).resolve().parent
ZBP_NAICS_PATH = PKG / "zbp_naics.yaml"

ALLOWED_CONFIDENCE = {"high", "medium"}
_NAICS_RE = re.compile(r"^\d{6}$")


class ZbpConfigError(ValueError):
    """The zbp_naics config is missing a category, has a malformed NAICS
    code, or uses a confidence value outside the allowed vocabulary. Raised
    instead of silently proceeding with a partial crosswalk."""


def load_zbp_naics() -> dict[str, list[dict]]:
    """The checked-in NAICS crosswalk: {category: [{"naics": "445110",
    "confidence": "high", "note": ...}, ...]}. Fails closed if any of the 15
    categories in `loci.categories.CATEGORIES` is absent, has an empty code
    list, a non-6-digit NAICS code, or a confidence value outside
    {high, medium}."""
    doc = yaml.safe_load(ZBP_NAICS_PATH.read_text())
    cats = doc.get("categories", {})

    missing = [c for c in CATEGORIES if c not in cats]
    if missing:
        raise ZbpConfigError(
            f"zbp_naics.yaml is missing {len(missing)} of {len(CATEGORIES)} "
            f"categories: {', '.join(missing)}. A category absent from the "
            "crosswalk must not be silently treated as zero establishments "
            "-- add it (even a medium-confidence single code beats silence)."
        )

    bad_codes: list[tuple[str, str]] = []
    bad_confidence: list[tuple[str, str]] = []
    empty: list[str] = []
    for cat in CATEGORIES:
        entries = cats.get(cat) or []
        if not entries:
            empty.append(cat)
            continue
        for entry in entries:
            code = str(entry.get("naics", ""))
            conf = entry.get("confidence")
            if not _NAICS_RE.match(code):
                bad_codes.append((cat, code))
            if conf not in ALLOWED_CONFIDENCE:
                bad_confidence.append((cat, str(conf)))

    if empty or bad_codes or bad_confidence:
        parts = []
        if empty:
            parts.append(f"categories with no NAICS codes: {', '.join(empty)}")
        if bad_codes:
            parts.append(
                "non-6-digit NAICS codes: "
                + ", ".join(f"{c}={code!r}" for c, code in bad_codes)
            )
        if bad_confidence:
            parts.append(
                "confidence not in {high, medium}: "
                + ", ".join(f"{c}={v!r}" for c, v in bad_confidence)
            )
        raise ZbpConfigError("zbp_naics.yaml has invalid entries -- " + "; ".join(parts))

    return {c: cats[c] for c in CATEGORIES}


def naics_to_category() -> dict[str, str]:
    """Flatten the crosswalk to {naics_code: category}, for the SQL rollup.
    A NAICS code that (by construction of this file) belongs to more than one
    category is not expected; if one is ever added, the later category in
    CATEGORIES iteration order wins silently, so keep codes category-exclusive
    when editing this file."""
    out: dict[str, str] = {}
    for cat, entries in load_zbp_naics().items():
        for entry in entries:
            out[str(entry["naics"])] = cat
    return out


def all_naics_codes() -> set[str]:
    """Every NAICS code mapped to any of the 15 categories."""
    return set(naics_to_category())
