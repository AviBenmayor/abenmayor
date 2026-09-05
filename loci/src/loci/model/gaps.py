"""Present-day investment screen: conspicuous single-category gaps (per hex).

An area "ripe for investment" is one that is already walkable and lived-in but is
missing an OBVIOUS business — one that comparable walkable areas normally have, so
its absence stands out and genuinely hinders the area's walkability. That missing
business is the opportunity, today. No growth model; this is a cross-sectional
targeting screen.

Two rules, selected by `rule`:

- `"window"` (default, unchanged): among populated hexes, measure each category's
  PREVALENCE within one shared walk window `threshold`. A missing category counts
  as a conspicuous gap only if its prevalence >= `expected`. FAILS MONOTONICITY
  (CHECKPOINT D33): shrinking `threshold` can make a gap disappear, because
  `expected` is re-evaluated at every window and can drop a category out of
  eligibility entirely (D31's Manhattan sweep — hardware gaps at 10 min vanish at
  5 min because hardware's 5-min prevalence falls below 0.80, not because any
  hardware store moved). Kept only for continuity; do not extend it.

- `"reach"` (QUESTIONS D6): each category gets a fixed REACH distance, set once
  from revealed spacing (`loci.reach`), not re-derived per hex or per window. A
  hex is missing category c iff its nearest c is farther than reach(c). This is
  monotone by construction: reach(c) is fixed per call, so tightening any reach
  (or adding a POI, which can only shrink a nearest-distance) can only add hexes
  to the missing set, never remove them. See tests/test_gaps_monotonicity.py.

Both rules share ONE walkability gate (`_eligible_universe`): a hex is in scope
iff >= `min_present` of the 15 categories are present within the walk window
(the WINDOW rule's own definition, default 10 min / 800 m) — regardless of which
rule then classifies "missing". Before this was factored out, the reach rule
gated on reach-based presence instead, which is a different, stricter test, and
shrank its eligible universe ~22% versus the window rule; the two rules must
agree on the population they are screening even when they disagree on what
"missing" means within it.

**Demand-side annotation (CHECKPOINT demand-caveat ticket; Meltzer & Schuetz
2012, `loci.demand`):** every gap row also carries `median_hh_income`,
`renter_share`, `income_class` ('low'/'mid_high'/None) and `demand_caveat` --
context, never a filter. A missing DISCRETIONARY category (restaurant,
cafe_bakery, bar, fitness per the paper; a few more by owner assumption -- see
`demand.yaml`) in a `income_class='low'` hex is plausibly demand-following
(the paper finds discretionary retail disproportionately locates in
higher-income areas even though necessity retail does not undersupply
low-income areas), not a conspicuous supply gap, so `demand_caveat=True` flags
it. Both rules pick `lead` preferring a NON-caveated missing category (ties
keep each rule's existing ordering: highest prevalence for window, smallest
reach for reach) -- only when EVERY missing category at a hex is caveated does
`lead` fall back to one of them. `caveated_missing` lists every caveated
category among `missing_expected`, not just the lead. This changes which
category is reported as `lead`, but never the set of gap hexes or the set of
(hex, category) missing pairs -- see tests/test_demand_caveat.py part (c).
"""
from __future__ import annotations

import hashlib
import json
import math

from loci.categories import CATEGORIES
from loci.demand import load_demand, load_low_income_cutoff
from loci.reach import load_reach, load_reach_meta

ALLCATS = list(CATEGORIES)


def _window_presence(con, threshold: int, min_pop: float) -> dict[str, tuple[float, set[str]]]:
    """Category presence per populated hex within the walk window
    (network_m <= threshold * 80, i.e. an ~80 m/min pedestrian pace — 10 min
    -> 800 m). {h3_index: (population, {categories present})}. This is the
    WINDOW rule's own presence definition (query unchanged from before this
    fix, so `rule="window"` output is byte-for-byte identical), and — since
    the gate fix below — the sole source of the walkability gate for every
    rule, not just window."""
    rows = con.execute("""
        SELECT h.h3_index, dm.population, list(a.category) present
        FROM analysis.hex h
        JOIN analysis.hex_demographics dm ON dm.h3_index=h.h3_index AND dm.acs_year=2023
        JOIN (SELECT DISTINCT h3_index, category FROM analysis.hex_poi_distance
              WHERE network_m <= ? * 80.0) a ON a.h3_index=h.h3_index
        WHERE dm.population > ?
        GROUP BY 1,2
    """, [threshold, min_pop]).fetchall()
    return {h: (pop, set(pr)) for h, pop, pr in rows}


def _gate(presence: dict[str, tuple[float, set[str]]], min_present: int
          ) -> dict[str, tuple[float, set[str]]]:
    """The walkability gate: keep only hexes with >= `min_present` categories
    present in `presence`. Takes a WINDOW presence dict (see `_window_presence`)
    ONLY — this is what makes the gate the same test for every rule (defect
    review item 1). Do not call this with a reach-based presence dict; that is
    exactly the bug being fixed."""
    return {h: v for h, v in presence.items() if len(v[1]) >= min_present}


def _income_context(con) -> tuple[float | None, dict[str, tuple[float | None, float | None, str | None]]]:
    """Demand-caveat inputs (CHECKPOINT demand-caveat ticket): the citywide
    population-weighted mean household income (over hexes with population > 0
    and non-null income, acs_year=2023 -- same vintage the rest of gaps.py
    uses) and, per hex, (median_hh_income, renter_share, income_class).
    `income_class` is 'low' if median_hh_income < `low_income_cutoff` (from
    demand.yaml) times that citywide mean, else 'mid_high'; None wherever
    median_hh_income is NULL for the hex or the citywide mean itself is
    unavailable. Read-only context for annotation -- never used to gate which
    hexes are eligible or which categories are missing."""
    cutoff = load_low_income_cutoff()
    citywide_mean = con.execute("""
        SELECT sum(population * median_hh_income) / sum(population)
        FROM analysis.hex_demographics
        WHERE acs_year = 2023 AND population > 0 AND median_hh_income IS NOT NULL
    """).fetchone()[0]
    rows = con.execute("""
        SELECT h3_index, median_hh_income, renter_share
        FROM analysis.hex_demographics WHERE acs_year = 2023
    """).fetchall()
    income_threshold = cutoff * citywide_mean if citywide_mean is not None else None
    ctx = {}
    for h, income, renter in rows:
        if income is None or income_threshold is None:
            ctx[h] = (income, renter, None)
        else:
            ctx[h] = (income, renter, "low" if income < income_threshold else "mid_high")
    return citywide_mean, ctx


def _pick_lead(missing: list[str], caveated: set[str], key) -> str:
    """Shared lead-selection rule for both rules (module docstring): prefer a
    NON-caveated missing category, ranked by `key` (higher-is-more-expected
    for window's prevalence, lower-is-more-expected for reach's distance --
    callers pass the right direction via `max`/`min` already baked into
    `key`'s caller). Ties keep each rule's existing order (Python's max/min
    are stable, and `missing` is already built in ALLCATS order). Falls back
    to ranking the full `missing` list only when every missing category at
    this hex is caveated."""
    candidates = [c for c in missing if c not in caveated] or missing
    return key(candidates)


def _eligible_universe(con, threshold: int, min_present: int, min_pop: float
                        ) -> dict[str, tuple[float, set[str]]]:
    """The frozen, rule-independent eligible universe: fetch window presence
    and gate it, in one call. Both `compute_gaps` (window) and
    `_compute_gaps_reach` use this, so the eligible universe — and its size —
    is identical under either rule."""
    return _gate(_window_presence(con, threshold, min_pop), min_present)


def compute_gaps(con, threshold: int = 10, min_present: int = 12,
                 expected: float = 0.80, min_pop: float = 800.0,
                 rule: str = "window", reach: dict[str, float] | None = None):
    """Pure computation: returns (rows, aux) without writing.

    `rule="window"` (default): `expected` is the prevalence a category needs
    before its absence counts as a conspicuous gap; it is the screen's most
    sensitive knob (bank/hardware sit near 0.80-0.85), so sweep it with
    `loci gaps-sweep` before trusting a top-N list. Known to violate
    monotonicity — see module docstring / CHECKPOINT D33. `aux` is the
    prevalence dict.

    `rule="reach"`: `expected`/`threshold` are ignored for the missing test;
    `reach` (default `loci.reach.load_reach()`) supplies a fixed per-category
    distance and MUST cover every category in `loci.categories.CATEGORIES` —
    an absent category raises rather than silently counting as always-present
    (defect review item 2). Row shape matches the window rule except
    `lead_prevalence` is reused to carry `reach(lead)` in metres (not a 0-1
    share) so both rules write to the same table shape. `aux` carries the
    reach dict plus provenance (`reach_quantile`, `reach_min_pop`, `reach_hash`)
    for `build_gaps` to persist.
    """
    if rule == "reach":
        reach_meta: dict = {"quantile": None, "min_pop": None}
        if reach is None:
            reach = load_reach()
            reach_meta = load_reach_meta()
        out = _compute_gaps_reach(con, threshold=threshold, min_present=min_present,
                                  min_pop=min_pop, reach=reach)
        aux = {
            "reach": dict(reach),
            "reach_quantile": reach_meta.get("quantile"),
            "reach_min_pop": reach_meta.get("min_pop"),
            "reach_hash": _reach_hash(reach),
        }
        return out, aux
    if rule != "window":
        raise ValueError(f"unknown rule {rule!r}, expected 'window' or 'reach'")

    presence = _window_presence(con, threshold, min_pop)
    n = len(presence) or 1
    prevalence = {c: sum(1 for _, pr in presence.values() if c in pr) / n for c in ALLCATS}

    discretionary = {c for c, e in load_demand().items() if e["income_elasticity"] == "discretionary"}
    _citywide_mean, income_ctx = _income_context(con)

    out = []
    for h, (pop, pr) in _gate(presence, min_present).items():
        missing = [c for c in ALLCATS if c not in pr and prevalence[c] >= expected]
        if not missing:
            continue
        income, renter, income_class = income_ctx.get(h, (None, None, None))
        caveated = {c for c in missing if c in discretionary and income_class == "low"}
        lead = _pick_lead(missing, caveated, key=lambda cands: max(cands, key=lambda c: prevalence[c]))
        caveated_missing = [c for c in missing if c in caveated]
        # NOTE: `missing_expected` (the joined `missing` string) stays the LAST
        # element of the row tuple -- tests/test_gaps_monotonicity.py's
        # `_missing_set` helper unpacks rows as `h, *_rest, missing` and
        # depends on that position, and it must stay untouched (spec: keep
        # its existing tests passing). `build_gaps` maps every column by
        # NAME (not position) into the DB, so this ordering is free to differ
        # from the tables' physical column order.
        out.append((h, threshold, pop, len(pr), lead, prevalence[lead],
                    income, renter, income_class, lead in caveated,
                    ",".join(caveated_missing), ",".join(missing)))
    return out, prevalence


def _check_reach_complete(reach: dict[str, float]) -> None:
    """Fail closed (defect review item 2): a category absent from `reach`
    must never be silently treated as always-present (the old
    `reach.get(c, math.inf)` default). Raise, naming exactly what's missing."""
    missing_cats = [c for c in ALLCATS if c not in reach]
    if missing_cats:
        raise ValueError(
            f"reach table is missing {len(missing_cats)} of {len(ALLCATS)} categories: "
            f"{', '.join(missing_cats)}. An absent category must not silently count as "
            "always-present -- add it to reach.yaml (see `loci reach-table --write`) "
            "or pass a complete `reach` dict."
        )


def _reach_hash(reach: dict[str, float]) -> str:
    """Short, stable hash of the {category: reach_m} actually used for a run,
    independent of dict insertion order. Populated even when `reach` was
    passed explicitly (e.g. in tests, or with reach.yaml's quantile/min_pop
    unknown), so analysis.hex_gaps_reach can always distinguish two runs that
    used different reach values (defect review item 4)."""
    blob = json.dumps({c: reach[c] for c in sorted(reach)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _compute_gaps_reach(con, threshold: int, min_present: int, min_pop: float,
                        reach: dict[str, float]):
    """`rule="reach"` implementation. Nearest-category distance per eligible
    hex, compared to a fixed per-category reach.

    The eligibility gate is the SHARED `_eligible_universe` (window-rule
    definition — defect review item 1) so the reach rule's eligible universe
    matches the window rule's exactly, never a reach-based gate. The output
    loop is driven by that eligible-hex set, not by whatever hexes happen to
    have rows in hex_poi_distance: a category with no row for a given hex
    (nothing within the 30-minute cap) is looked up with a `math.inf` default,
    so it is correctly classified as beyond reach -- a maximal gap -- rather
    than the hex silently vanishing from the classification because its
    distance dict is sparse (defect review item 3).
    """
    _check_reach_complete(reach)

    eligible = _eligible_universe(con, threshold, min_present, min_pop)

    dist_rows = con.execute("""
        SELECT dm.h3_index, p.category, MIN(p.network_m) AS d
        FROM analysis.hex_demographics dm
        JOIN analysis.hex_poi_distance p ON p.h3_index = dm.h3_index
        WHERE dm.acs_year = 2023 AND dm.population > ?
        GROUP BY 1, 2
    """, [min_pop]).fetchall()
    dist_by_hex: dict[str, dict[str, float]] = {}
    for h, cat, d in dist_rows:
        dist_by_hex.setdefault(h, {})[cat] = d

    discretionary = {c for c, e in load_demand().items() if e["income_elasticity"] == "discretionary"}
    _citywide_mean, income_ctx = _income_context(con)

    out = []
    for h, (pop, _window_pr) in eligible.items():
        # .get(h, {}) alone already guarantees no KeyError for a hex entirely
        # absent from dist_by_hex; the inner .get(c, math.inf) guarantees no
        # single missing category silently drops out either -- both default
        # to "beyond reach", never to "present".
        dists = dist_by_hex.get(h, {})
        present = {c for c in ALLCATS if dists.get(c, math.inf) <= reach[c]}
        missing = [c for c in ALLCATS if c not in present]
        if not missing:
            continue
        income, renter, income_class = income_ctx.get(h, (None, None, None))
        caveated = {c for c in missing if c in discretionary and income_class == "low"}
        # "Lead" = the missing category with the SMALLEST reach — the one
        # areas like this are expected to have closest, so its absence is
        # the most conspicuous (mirrors the window rule's "most-expected") --
        # preferring a NON-caveated category first (module docstring).
        lead = _pick_lead(missing, caveated, key=lambda cands: min(cands, key=lambda c: reach[c]))
        caveated_missing = [c for c in missing if c in caveated]
        # `missing_expected` stays LAST -- see the matching note in
        # `compute_gaps`'s window branch.
        out.append((h, 0, pop, len(present), lead, reach[lead],
                    income, renter, income_class, lead in caveated,
                    ",".join(caveated_missing), ",".join(missing)))
    return out


def build_gaps(con, threshold: int = 10, min_present: int = 12,
               expected: float = 0.80, min_pop: float = 800.0,
               rule: str = "window", reach: dict[str, float] | None = None) -> tuple[int, dict]:
    """Writes the gap screen. `rule="window"` (default) writes to
    `analysis.hex_gaps`, unchanged, so nothing downstream (the webmap export,
    the ranking) is affected by this change. `rule="reach"` writes to the
    separate `analysis.hex_gaps_reach` table instead of touching hex_gaps —
    the two rules are never mixed in one table — and records the reach
    provenance (quantile, min_pop, hash) used for that run."""
    out, aux = compute_gaps(con, threshold, min_present, expected, min_pop,
                            rule=rule, reach=reach)
    import pandas as pd
    # Row-tuple order (see compute_gaps/_compute_gaps_reach) puts
    # `missing_expected` LAST so tests/test_gaps_monotonicity.py's
    # `_missing_set` helper (which unpacks `h, *_rest, missing = row`) keeps
    # working untouched. That is NOT the physical column order of either
    # table (missing_expected sits right after lead_prevalence/lead_reach_m
    # there, with the demand columns appended after it by ALTER TABLE), so
    # both INSERTs below map every column by NAME, never `SELECT *`.
    demand_cols = ["median_hh_income", "renter_share", "income_class",
                   "demand_caveat", "caveated_missing"]
    if rule == "window":
        con.execute("DELETE FROM analysis.hex_gaps WHERE threshold_min = ?", [threshold])
        df = pd.DataFrame(out, columns=["h3_index", "threshold_min", "population",
                                        "present_count", "lead_missing", "lead_prevalence",
                                        *demand_cols, "missing_expected"])
        con.register("_g", df)
        cols = ["h3_index", "threshold_min", "population", "present_count",
                "lead_missing", "lead_prevalence", "missing_expected", *demand_cols]
        con.execute(f"""INSERT INTO analysis.hex_gaps ({", ".join(cols)})
                       SELECT {", ".join(cols)} FROM _g""")
        con.unregister("_g")
    else:
        con.execute("DELETE FROM analysis.hex_gaps_reach")
        df = pd.DataFrame(out, columns=["h3_index", "threshold_min", "population",
                                        "present_count", "lead_missing", "lead_reach_m",
                                        *demand_cols, "missing_expected"])
        df["reach_quantile"] = aux.get("reach_quantile")
        df["reach_min_pop"] = aux.get("reach_min_pop")
        df["reach_hash"] = aux.get("reach_hash")
        con.register("_g", df)
        cols = ["h3_index", "population", "present_count", "lead_missing", "lead_reach_m",
                "missing_expected", *demand_cols, "reach_quantile", "reach_min_pop", "reach_hash"]
        con.execute(f"""INSERT INTO analysis.hex_gaps_reach ({", ".join(cols)})
                       SELECT {", ".join(cols)} FROM _g""")
        con.unregister("_g")
    return len(df), aux
