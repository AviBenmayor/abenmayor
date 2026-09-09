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

**Demand-side annotation (Meltzer & Schuetz 2012, `loci.demand`; rebuilt by
the GTM-109 contrarian review):** every gap row carries `median_hh_income`,
`renter_share`, `income_class`, `income_ratio`, `income_ratio_moe`,
`income_indeterminate`, `demand_caveat`, `caveated_missing` and
`demand_caveat_text`. All of it is CONTEXT, never a filter and never an input
to a rank or a score.

A missing DISCRETIONARY category in a confidently-low-income hex is plausibly
demand-following (the paper finds discretionary retail disproportionately
locates in higher-income areas even though necessity retail does not
undersupply low-income areas). Three things GTM-109 changed:

1. **The class is derived, not declared.** `loci.demand` computes
   necessity/discretionary from `spend.yaml`'s BLS CEX `income_elasticity` at a
   0.35 cut, which reproduces 7/7 of the paper's own rows. The eight former
   owner priors are gone; nails_beauty and tailor_repair flipped to necessity.
   clinic is excluded from the annotation entirely (CHECKPOINT D30).

2. **The denominator is the citywide MEAN household income** (ACS
   B19025/B11001, household-weighted, `loci.grid.acs`), not the
   population-weighted mean of tract medians this module used to compute.

3. **The statement is continuous and MOE-aware.** `income_ratio` is the hex's
   income as a share of that citywide mean; `income_ratio_moe` propagates the
   ACS MOE; `income_indeterminate` marks the ~55% of gap hexes whose income
   sits within one MOE of the cutoff and therefore CANNOT be classified better
   than a coin flip. A caveat is only asserted -- `demand_caveat_text` emitted,
   `caveated_missing` populated -- when the hex is CONFIDENTLY below the
   cutoff (`ratio + moe < cutoff`). Every emitted text carries the X6
   disclaimer (`loci.demand.X6_DISCLAIMER`).

`income_class` is retained as the point-estimate label for existing consumers
(and GTM-110's address port), but nothing keys off it alone: read it together
with `income_indeterminate`.

Both rules pick `lead` preferring a NON-caveated missing category (ties keep
each rule's existing ordering: highest prevalence for window, smallest reach
for reach) -- only when EVERY missing category at a hex is caveated does
`lead` fall back to one of them. That preference now uses the CONFIDENT caveat
set, so a coin-flip income classification can no longer move which category a
hex reports. The annotation never changes the set of gap hexes or the set of
(hex, category) missing pairs -- see tests/test_demand_caveat.py parts (c)/(d).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math

from loci.categories import CATEGORIES
from loci.demand import X6_DISCLAIMER, caveat_categories, load_demand, load_low_income_cutoff
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


@dataclasses.dataclass(frozen=True)
class IncomeContext:
    """Per-hex demand-side context. Purely additive annotation: nothing in this
    dataclass may gate eligibility, membership in the missing set, or any rank
    or score (tests/test_demand_caveat.py parts (c)/(d))."""
    median_hh_income: float | None
    renter_share: float | None
    income_class: str | None          # 'low' | 'mid_high' | None -- POINT estimate
    income_ratio: float | None        # median_hh_income / citywide mean
    income_ratio_moe: float | None    # 90%-confidence MOE on that ratio
    income_indeterminate: bool | None # cutoff sits within one MOE of the ratio
    confidently_low: bool             # ratio + moe < cutoff; the only caveat trigger


_NO_INCOME = IncomeContext(None, None, None, None, None, None, False)


def _citywide_income() -> tuple[float | None, float | None]:
    """(mean, MOE) of citywide household income, from
    `loci.grid.acs.load_citywide_mean_hh_income` (ACS B19025/B11001 over the
    five NYC counties, cached under data/interim/).

    Factored out as its own function so tests can pin it -- the value is a
    live ACS quantity behind a gitignored cache, and no unit test should depend
    on the network or on a machine's cache state. See tests/conftest.py."""
    from loci.grid.acs import load_citywide_mean_hh_income
    rec = load_citywide_mean_hh_income()
    return rec["mean_hh_income"], rec["mean_hh_income_moe"]


def _ratio_moe(x: float, x_moe: float | None, y: float, y_moe: float | None) -> float | None:
    """Standard ACS derived-RATIO margin of error (ACS General Handbook,
    "Calculating Margins of Error for Derived Ratios")::

        R = X / Y
        MOE(R) ~= (1 / Y) * sqrt( MOE(X)^2 + R^2 * MOE(Y)^2 )

    Here X is the hex's `median_hh_income` (MOE from
    `hex_demographics.median_hh_income_moe`, itself propagated onto the grid by
    `grid/acs.py`) and Y is the citywide mean household income (MOE from the
    county-level B19025/B11001 aggregates). Both inputs are published at 90%
    confidence, the Census convention, so the result is a 90% MOE too.

    Two stated approximations. (1) The formula is the RATIO form -- the terms
    ADD -- not the PROPORTION form, where X is a subset of Y and the second
    term is subtracted; a hex's median income is not a subset of a citywide
    mean. (2) It assumes X and Y independent. The hex contributes on the order
    of 1e-4 of the citywide aggregate, so the induced correlation is
    negligible; Y's own MOE is under 1% of Y regardless and the numerator term
    dominates by two orders of magnitude.

    Returns None if either MOE is unknown -- the caller must then treat the
    ratio as unclassifiable rather than as exact (fail closed).
    """
    if x_moe is None or y in (None, 0):
        return None
    r = x / y
    ym = y_moe or 0.0
    return math.sqrt(x_moe ** 2 + (r ** 2) * (ym ** 2)) / y


def _income_context(con, citywide: tuple[float | None, float | None] | None = None
                    ) -> tuple[float | None, dict[str, IncomeContext]]:
    """Demand-caveat inputs. Returns the citywide MEAN household income and, per
    hex, an `IncomeContext`.

    The denominator is the ACS citywide MEAN household income
    (`_citywide_income`), household-weighted -- Meltzer & Schuetz's own
    quantity. Before GTM-109 this function computed
    `sum(population * median_hh_income) / sum(population)` over hexes instead,
    which is a POPULATION-weighted mean of tract MEDIANS ($88,154 vs the true
    mean's $127,894). Three defects in one line: a mean-of-medians is not a
    mean in a right-skewed distribution, people are the wrong weight when the
    unit is the household, and the result was compared against a median. The
    net effect was a cutoff ~28% too low, i.e. a materially stricter and
    smaller "low income" population than the paper's.

    `income_class` is the POINT-estimate label ('low' if the hex's income is
    below `low_income_cutoff` x the citywide mean, else 'mid_high'; None if
    either side is unknown). `confidently_low` is the stricter test that
    actually drives the caveat: the ratio PLUS its MOE must still sit below the
    cutoff. `income_indeterminate` marks hexes whose income is within one MOE
    of the cutoff in either direction -- for those, `income_class` is a coin
    flip and must not be read on its own. A hex whose MOE is unknown gets
    `income_ratio_moe=None`, `income_indeterminate=None` and
    `confidently_low=False`: no MOE, no assertion.

    Read-only context -- never used to gate which hexes are eligible or which
    categories are missing.
    """
    cutoff = load_low_income_cutoff()
    citywide_mean, citywide_moe = citywide if citywide is not None else _citywide_income()
    rows = con.execute("""
        SELECT h3_index, median_hh_income, median_hh_income_moe, renter_share
        FROM analysis.hex_demographics WHERE acs_year = 2023
    """).fetchall()

    ctx: dict[str, IncomeContext] = {}
    for h, income, income_moe, renter in rows:
        if income is None or citywide_mean in (None, 0):
            ctx[h] = dataclasses.replace(_NO_INCOME, median_hh_income=income,
                                         renter_share=renter)
            continue
        ratio = income / citywide_mean
        moe = _ratio_moe(income, income_moe, citywide_mean, citywide_moe)
        ctx[h] = IncomeContext(
            median_hh_income=income,
            renter_share=renter,
            income_class="low" if ratio < cutoff else "mid_high",
            income_ratio=ratio,
            income_ratio_moe=moe,
            income_indeterminate=None if moe is None else abs(ratio - cutoff) <= moe,
            confidently_low=False if moe is None else (ratio + moe) < cutoff,
        )
    return citywide_mean, ctx


def _caveat_text(ic: IncomeContext, caveated: list[str], demand: dict[str, dict]) -> str | None:
    """The worded, continuous caveat -- emitted ONLY when the hex is
    confidently below the cutoff and at least one missing category is
    caveat-eligible. Replaces the old boolean badge, which more than half of
    gap hexes could not support (GTM-109 §2).

    Always ends with `loci.demand.X6_DISCLAIMER`: the same paper finds race
    predicts retail net of income, so an income-only annotation shown without
    that sentence can launder under-provision as "absent demand". Do not render
    the ratio without the disclaimer."""
    if not caveated or not ic.confidently_low or ic.income_ratio is None:
        return None
    pts = "" if ic.income_ratio_moe is None else f" (±{ic.income_ratio_moe * 100:.0f} pts)"
    cats = ", ".join(f"{c} {demand[c]['elasticity']:.2f}" for c in caveated)
    return (f"household income {ic.income_ratio * 100:.0f}% of citywide mean{pts}; "
            f"category income elasticity (BLS CEX): {cats}. {X6_DISCLAIMER}")


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

    demand = load_demand()
    eligible_for_caveat = caveat_categories()
    _citywide_mean, income_ctx = _income_context(con)

    out = []
    for h, (pop, pr) in _gate(presence, min_present).items():
        missing = [c for c in ALLCATS if c not in pr and prevalence[c] >= expected]
        if not missing:
            continue
        ic = income_ctx.get(h, _NO_INCOME)
        caveated = {c for c in missing if c in eligible_for_caveat and ic.confidently_low}
        lead = _pick_lead(missing, caveated, key=lambda cands: max(cands, key=lambda c: prevalence[c]))
        caveated_missing = [c for c in missing if c in caveated]
        # NOTE: `missing_expected` (the joined `missing` string) stays the LAST
        # element of the row tuple -- tests/test_gaps_monotonicity.py's
        # `_missing_set` helper unpacks rows as `h, *_rest, missing` and
        # depends on that position, and it must stay untouched (spec: keep
        # its existing tests passing). New GTM-109 columns are appended just
        # BEFORE it, so the historical indices 6..10 also stay put.
        # `build_gaps` maps every column by NAME (not position) into the DB,
        # so this ordering is free to differ from the tables' physical order.
        out.append((h, threshold, pop, len(pr), lead, prevalence[lead],
                    ic.median_hh_income, ic.renter_share, ic.income_class, lead in caveated,
                    ",".join(caveated_missing),
                    ic.income_ratio, ic.income_ratio_moe, ic.income_indeterminate,
                    _caveat_text(ic, caveated_missing, demand),
                    ",".join(missing)))
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

    demand = load_demand()
    eligible_for_caveat = caveat_categories()
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
        ic = income_ctx.get(h, _NO_INCOME)
        caveated = {c for c in missing if c in eligible_for_caveat and ic.confidently_low}
        # "Lead" = the missing category with the SMALLEST reach — the one
        # areas like this are expected to have closest, so its absence is
        # the most conspicuous (mirrors the window rule's "most-expected") --
        # preferring a NON-caveated category first (module docstring).
        lead = _pick_lead(missing, caveated, key=lambda cands: min(cands, key=lambda c: reach[c]))
        caveated_missing = [c for c in missing if c in caveated]
        # `missing_expected` stays LAST -- see the matching note in
        # `compute_gaps`'s window branch.
        out.append((h, 0, pop, len(present), lead, reach[lead],
                    ic.median_hh_income, ic.renter_share, ic.income_class, lead in caveated,
                    ",".join(caveated_missing),
                    ic.income_ratio, ic.income_ratio_moe, ic.income_indeterminate,
                    _caveat_text(ic, caveated_missing, demand),
                    ",".join(missing)))
    return out


# ---------------------------------------------------------------------------
# RETIRED UNDER D38 (2026-09-09). `build_gaps` -- the writer that persisted
# this screen to analysis.hex_gaps / analysis.hex_gaps_reach -- is DELETED, and
# so are both tables. D38 made the residential address the unit of analysis;
# model/address_gaps.py is the screen, and nothing on that path ever read
# either hex table. Keeping a writer for a table the deliverable does not read
# only invites a future session to re-run it and believe the output.
#
# What is deliberately KEPT in this module, and why:
#   * `compute_gaps` / `_compute_gaps_reach` / `_eligible_universe` -- the
#     monotonicity acceptance battery (tests/test_gaps_monotonicity.py) is the
#     evidence for D33/D34/D39 (the window rule violates monotonicity, the
#     reach rule does not). That evidence has to stay runnable.
#   * `_ratio_moe` / `_caveat_text` -- tests/test_demand_caveat.py pins them
#     character-for-character against loci.demand's shared implementations,
#     which is what stops the address annotation (D57) and this frozen hex
#     annotation from drifting into two different sentences.
# Both are PURE: they take a connection and return rows. Neither writes.
# ---------------------------------------------------------------------------
