"""Per-category REACH: fixed distances that replace the single citywide walk
window in the gap screen (QUESTIONS D6, CHECKPOINT D33).

The old screen (`model/gaps.py`, rule="window") asks one question at one
window w: "is category c present within w, and is c present within w for
>=80% of walkable hexes?" Both halves move with w, so tightening w can make a
gap DISAPPEAR (D31's Manhattan sweep) — a monotonicity violation. Reach
separates the two questions: reach(c) is a property of the CATEGORY, set once
from revealed spacing; "is hex h missing c" is then a property of the HEX
alone (nearest-c distance vs. that fixed reach), so shrinking any reach can
only ever grow the missing set.

Reach values are DATA (`reach.yaml`), never hardcoded here. `compute_reach_table`
regenerates them from analysis.hex_poi_distance; `load_reach` reads what's
checked in.
"""
from __future__ import annotations

import pathlib

import yaml

from loci.categories import CATEGORIES

PKG = pathlib.Path(__file__).resolve().parent
REACH_PATH = PKG / "reach.yaml"
REACH_TIERS_PATH = PKG / "reach_tiers.yaml"

# hex_poi_distance holds no pairs beyond the 30-minute walk cap, so a hex with
# no row for a category is right-censored, not "infinitely far." Quantiles
# below this cap are exact; a quantile that lands ON the cap is a lower bound.
CENSOR_M = 2450.0


def _check_reach_complete(reach: dict[str, float], source: str) -> None:
    """Fail closed: a category absent from `reach` must never be silently
    treated as always-present. Shared by every `source`, and by
    tests/test_address_gaps.py part (f)."""
    missing = sorted(set(CATEGORIES) - set(reach))
    if missing:
        raise ValueError(
            f"reach source {source!r} is missing {len(missing)} of {len(CATEGORIES)} "
            f"categories: {', '.join(missing)}"
        )


def load_reach(source: str = "tiers") -> dict[str, float]:
    """{category: reach_m}. `source='tiers'` (default, CHECKPOINT D41: ADOPTED
    src/loci/reach_tiers.yaml, cited/analog walk-distance tiers) or
    `source='p80'` (the older revealed-spacing table, reach.yaml, still
    selectable via `loci address-gaps --reach p80` for comparison). Fails
    closed if the selected table is missing one of the 15 Loci categories."""
    if source == "tiers":
        doc = yaml.safe_load(REACH_TIERS_PATH.read_text())
        cats = doc.get("categories") or {}
        reach = {c: float(v["reach_m"]) for c, v in cats.items()}
    elif source == "p80":
        doc = yaml.safe_load(REACH_PATH.read_text())
        reach = {c: float(m) for c, m in doc["reach_m"].items()}
    else:
        raise ValueError(f"unknown reach source {source!r}; expected 'tiers' or 'p80'")
    _check_reach_complete(reach, source)
    return reach


def load_reach_meta() -> dict:
    """The checked-in reach table's generation parameters (quantile, min_pop,
    version, computed_on) -- provenance for analysis.hex_gaps_reach so two runs
    made at different quantiles (or from an edited reach.yaml) are
    distinguishable after the fact. Values are None if reach.yaml predates
    this field."""
    doc = yaml.safe_load(REACH_PATH.read_text())
    return {
        "quantile": doc.get("quantile"),
        "min_pop": doc.get("min_pop"),
        "version": doc.get("version"),
        "computed_on": doc.get("computed_on"),
    }


def load_validation_geometry() -> dict:
    """Geometry of the Google Places coverage validator (QUESTIONS M8, D53).

    Lives in reach_tiers.yaml next to the walk thresholds it is derived from,
    because it IS one of those thresholds re-expressed: the validator's Nearby
    Search takes a circular locationRestriction, so it can only ever measure a
    straight-line disc, while the gap screen thresholds on NETWORK distance.
    The disc radius is therefore the network threshold divided by NYC's
    measured circuity -- never a hardcoded metre count here.

    Returns the yaml block plus `radius_m`, the derived straight-line radius.
    Raises if the yaml's pinned `derived_radius_m` disagrees with the
    derivation, so an edit to one number without the other fails loudly
    instead of silently changing what future runs measure.
    """
    doc = yaml.safe_load(REACH_TIERS_PATH.read_text())
    v = doc.get("validation")
    if not v:
        raise ValueError(f"{REACH_TIERS_PATH.name} has no `validation:` block")
    network_m = float(v["network_threshold_m"])
    circuity = float(v["circuity"])
    if circuity < 1.0:
        raise ValueError(f"circuity must be >= 1.0 (network >= straight line); got {circuity}")
    radius_m = int(round(network_m / circuity))
    pinned = v.get("derived_radius_m")
    if pinned is not None and int(pinned) != radius_m:
        raise ValueError(
            f"{REACH_TIERS_PATH.name} validation block is inconsistent: "
            f"derived_radius_m={pinned} but round({network_m} / {circuity}) = {radius_m}"
        )
    return {**v, "network_threshold_m": network_m, "circuity": circuity, "radius_m": radius_m}


def validation_radius_m() -> int:
    """The straight-line radius (m) the Google validator must use. Derived from
    reach_tiers.yaml's `validation` block; see load_validation_geometry."""
    return load_validation_geometry()["radius_m"]


def compute_reach_table(con, quantile: float = 0.80, min_pop: float = 800.0) -> list[tuple]:
    """Recompute the reach table from the live DB. Read-only.

    Returns rows (category, n_poi, n_pop_hexes, n_censored_30min, median_m,
    p75_m, reach_m) where reach_m is the `quantile`-th percentile of the
    hex-to-nearest-c network distance over populated hexes (population >
    min_pop). "Populated" matches model/gaps.py's min_pop so the reach table
    and the gap screen agree on which hexes count.
    """
    rows = con.execute(
        """
        WITH pop_hex AS (
          SELECT h3_index FROM analysis.hex_demographics
          WHERE acs_year = 2023 AND population > ?
        ),
        cats AS (SELECT DISTINCT category FROM analysis.hex_poi_distance),
        nearest AS (
          SELECT ph.h3_index, c.category,
                 (SELECT MIN(p.network_m) FROM analysis.hex_poi_distance p
                   WHERE p.h3_index = ph.h3_index AND p.category = c.category) AS d
          FROM pop_hex ph CROSS JOIN cats c
        ),
        npois AS (
          SELECT p.category, count(DISTINCT p.poi_id) n_poi
          FROM staging.poi p JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id AND d.is_canonical
          GROUP BY 1
        )
        SELECT n.category, npois.n_poi, count(*) AS n_pop_hexes,
               sum((d IS NULL)::int) AS n_censored_30min,
               median(coalesce(d, ?)) AS median_m,
               quantile_cont(coalesce(d, ?), 0.75) AS p75_m,
               quantile_cont(coalesce(d, ?), ?) AS reach_m
        FROM nearest n JOIN npois ON npois.category = n.category
        GROUP BY 1, 2 ORDER BY 1
        """,
        [min_pop, CENSOR_M, CENSOR_M, CENSOR_M, quantile],
    ).fetchall()
    return rows


def write_reach_table(con, quantile: float = 0.80, min_pop: float = 800.0) -> dict[str, float]:
    """Recompute and overwrite reach.yaml. Returns the new {category: reach_m}."""
    rows = compute_reach_table(con, quantile=quantile, min_pop=min_pop)
    reach = {cat: round(float(reach_m), 0) for cat, *_rest, reach_m in rows}
    doc = {
        "version": 1,
        "quantile": quantile,
        "min_pop": min_pop,
        "reach_m": reach,
    }
    REACH_PATH.write_text(
        "# Regenerated by loci reach-table --write. See module docstring in reach.py\n"
        "# and CHECKPOINT D33 / QUESTIONS D6 for the definition and caveats.\n"
        + yaml.safe_dump(doc, sort_keys=False)
    )
    return reach
