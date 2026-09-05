"""Machine checks that src/loci/categories.yaml is actually anchoring the
category taxonomy (docs/CHECKPOINT.md, 2026-09-05 NAICS-anchor decision).

Three properties:
  (a) every slug used as a key anywhere in reach.yaml, conveniences.yaml,
      demand.yaml, benchmarks.yaml, spend.yaml, or in the OSM tag map
      (src/loci/sources/universal/osm_overpass.py) has an entry in
      categories.yaml -- the anchor covers everything actually in use, not a
      subset.
  (b) every naics_2022 code in categories.yaml exists in naics_2022.csv at
      the 6-digit level -- codes are verified against the real reference
      file, never recalled from memory.
  (c) no two slugs in categories.yaml share a 6-digit naics_2022 code -- the
      pivot taxonomy must not silently double-count an establishment class
      across two Loci categories.
"""
from __future__ import annotations

import csv
from pathlib import Path

import yaml

NAICS_DIR = Path(__file__).resolve().parents[1] / "src" / "loci" / "naics"
SRC = Path(__file__).resolve().parents[1] / "src" / "loci"


def _load_categories() -> dict:
    with open(SRC / "categories.yaml") as f:
        return yaml.safe_load(f)["categories"]


def _load_naics_2022_codes() -> set[str]:
    codes = set()
    with open(NAICS_DIR / "naics_2022.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["level"] == "6":
                codes.add(row["code"])
    return codes


def _keys_of(yaml_path: Path, top_key: str | None = None) -> set[str]:
    """Top-level string keys of a mapping, optionally nested one level under
    `top_key` (e.g. demand.yaml's `categories:` block)."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    if top_key is not None:
        data = data[top_key]
    return {k for k in data.keys() if isinstance(k, str)}


def test_naics_reference_csv_exists_and_is_nonempty():
    codes = _load_naics_2022_codes()
    assert len(codes) > 900, "expected >900 six-digit 2022 NAICS codes (got %d)" % len(codes)


def test_every_used_slug_is_anchored():
    categories = _load_categories()
    anchored = set(categories.keys())

    used: set[str] = set()
    used |= _keys_of(SRC / "reach.yaml", top_key="reach_m")
    used |= _keys_of(SRC / "conveniences.yaml", top_key="distance_min")
    used |= _keys_of(SRC / "demand.yaml", top_key="categories")
    used |= _keys_of(SRC / "benchmarks.yaml", top_key="categories")
    used |= _keys_of(SRC / "spend.yaml", top_key="categories")

    # OSM tag map: values of TAG_CATEGORY, not keys -- import the module and
    # read the dict directly rather than re-parsing the source.
    from loci.sources.universal.osm_overpass import TAG_CATEGORY
    used |= set(TAG_CATEGORY.values())

    missing = used - anchored
    assert not missing, (
        f"slugs used in yamls/OSM tag map but missing from categories.yaml: {sorted(missing)}"
    )


def test_every_naics_2022_code_is_real():
    categories = _load_categories()
    real_codes = _load_naics_2022_codes()

    bad: list[tuple[str, str]] = []
    for slug, entry in categories.items():
        for code in entry.get("naics_2022", []):
            if code not in real_codes:
                bad.append((slug, code))

    assert not bad, f"naics_2022 codes not found in naics_2022.csv at 6-digit level: {bad}"


def test_no_two_slugs_share_a_naics_2022_code():
    categories = _load_categories()

    code_to_slugs: dict[str, list[str]] = {}
    for slug, entry in categories.items():
        for code in entry.get("naics_2022", []):
            code_to_slugs.setdefault(code, []).append(slug)

    collisions = {code: slugs for code, slugs in code_to_slugs.items() if len(slugs) > 1}
    assert not collisions, f"naics_2022 codes shared by more than one slug: {collisions}"


def test_categories_yaml_covers_all_15_category_slugs():
    """Sanity check against the canonical slug list in categories.py."""
    from loci.categories import CATEGORIES

    categories = _load_categories()
    assert set(categories.keys()) == set(CATEGORIES.keys())
