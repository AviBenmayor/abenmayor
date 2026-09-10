"""`age_fit`: SUPPLY-REVEALED age multipliers, one curve per fitted category,
estimated from New York's own composition of supply (D63 `bar`, D64 `childcare`,
D6x `pharmacy`).

WHAT THIS IS
--------------------------------------------------------------------------
The owner's request (2026-09-10): *"a bar gap in the Upper East Side where avg
age is 60+ vs a bar gap in the East Village where avg age is 25 -- the East
Village bar should score higher."*  This module answers it with curves fitted
to New York, not with a national budget survey.

`docs/age_demand_fit.md` tried the survey route (BLS CEX) and it failed on its
own terms: the CEX alcohol line peaks at reference-person age 45-54 -- the
household budget shape, not the drinker's -- averages over non-drinkers, is
under-reported, and publishes no age-by-metro cell, so the multiplier it
produced had a p10-p90 spread of 0.013 against a median MOE of 0.140 and would
have scored the UES ABOVE the East Village. `docs/bar_age_nyc.md` replaces it
with a market-revealed relationship measured on this warehouse's own data, and
recommends exactly ONE specification of the several it tested.

THE CURVE REGISTRY (D64)
--------------------------------------------------------------------------
D63 shipped `bar` alone and said, in as many words, that extending the curve to
another category is "a separate decision with its own gate, not a loop over
ALLCATS". D64 takes that decision for ONE more category (`childcare`, QUESTIONS
D15) and, rather than copying the estimator, turns the bar-shaped code into a
REGISTRY: `CURVES` maps a category to a `CategorySpec` carrying its outcome, its
age regressors, its contrast definition and its reach radius. Everything else --
the controls, the Conley SEs, the anchor, the delta-method MOE, the F2/F3 gate,
the UPDATE-only writer -- is shared, so a second category cannot quietly get a
weaker gate than the first.

The bar spec is byte-for-byte the D63 one: same outcome, same regressors, same
400 m radius, same fixed Carnegie-Hill -> East-Village contrast, same formula
STRING (the design columns are suffixed with the radius, and bar's radius is
400). `tests/test_age_fit.py` pins that the refit reproduces the committed
coefficients and that applying both curves leaves every bar value unchanged.

THE `bar` SPECIFICATION (`sla_composition_v1`, docs/bar_age_nyc.md §7)
--------------------------------------------------------------------------
Unit: census tract (the ACS grain), Manhattan + Brooklyn (D48), population
>= 100.  Centroid: the `units_capped`-weighted mean of the tract's ADDRESS
coordinates -- a residential centroid, because a geometric tract centroid can
land in Prospect Park.  Outcome:

    bar_share_400 = log(1 + bar-type on-premises licences within 400 m)
                  - log(1 + all on-premises licences within 400 m)

i.e. what FRACTION of the licensed venues near here are bar-type. A share, not
a count, and that is the whole reason this spec was chosen:

  * it is the only specification whose two age coefficients BOTH carry the
    owner's sign (+0.405 on the 18-34 adult share, -0.486 on 65+). Every count
    specification has w65 POSITIVE -- the UES is old, rich and dense -- which
    contradicts half the request;
  * it is the only specification that survives in BROOKLYN, where 98% of the
    bar-lead gap set actually lives (Conley t = +2.44 vs +1.38/+1.50 for the
    count specs, whose Brooklyn CIs graze 1.0);
  * a share nets commercial intensity out MECHANICALLY rather than through a
    control, which matters here because the only daytime controls available are
    two NAICS sectors, one of which (CNS18, accommodation and food services) IS
    the outcome in payroll form and must never be conditioned on.

THE `childcare` SPECIFICATION (`poi_composition_v1`, D64 / QUESTIONS D15)
--------------------------------------------------------------------------
The same shape, one radius and one regressor different, and one caveat MORE.

    childcare_share_640 = log(1 + canonical childcare POIs within 640 m)
                        - log(1 + ALL canonical POIs within 640 m)

640 m is the category's own reach tier (`reach_tiers.yaml`), not bar's 400 m --
the disc has to be the distance at which the category is actually consumed.
The composition form is chosen for the same mechanical reason as bar: the
denominator is every canonical storefront near the centroid, so "this is a
dense commercial strip" cancels out of numerator and denominator and what is
left is the MIX. The primary age regressor is `under_18_share` -- for childcare
the direct demand variable is the presence of CHILDREN, not the age of adults --
with bar's two adult shares kept alongside it so the placebo b(w18) stays
comparable to the docs/bar_age_nyc.md §5c table (childcare -0.574 there).

THE CAVEAT THAT IS SPECIFIC TO `childcare`, AND IS NOT SMALL
--------------------------------------------------------------------------
Bar's outcome is measured on NYS SLA licences -- a registry feed the address
screen does NOT read. Childcare has NO registry anchor loaded (see
`analysis.category_anchor`: `anchor_sources` is NULL and `anchor_coverage` is
0.00, so `in_principled` degrades to `in_all` and all 4,302 canonical childcare
POIs come from Overture and Foursquare alone). Its outcome is therefore built
from the SAME canonical supply the screen already reads. The composition form
blunts this -- the screen reads a per-category NETWORK DISTANCE to the nearest
childcare POI, not a 640 m share of all storefronts -- but it does not remove
it, and it is the tightest form of the D1 trap that D63's §7.2 test 8 pins for
bar. Loading a childcare registry anchor (DOHMH child-care-centre inspections,
`dsg6-ifza` -- NOT currently ingested, despite what `score/supply.py`'s prose
implies) is the fix; until then this column is weaker evidence than bar's.

THE `pharmacy` SPECIFICATION (`poi_composition_v1`, D6x / QUESTIONS D15)
--------------------------------------------------------------------------
The third registry entry, and the first whose gate PASSES.

    pharmacy_share_800 = log(1 + canonical pharmacy POIs within 800 m)
                       - log(1 + ALL canonical POIs within 800 m)

800 m is pharmacy's own reach tier -- Guadamuz et al.'s pharmacy-desert
distance for low-income, low-vehicle neighbourhoods, i.e. NYC. The primary
demand regressor is `age_65_plus_share`, the sign the §5c placebo (pharmacy
b(w18) = -0.846, the most negative of fifteen) and the CEX note independently
gave, with `age_18_34_share` beside it. BOTH bands enter UN-renormalized, as
shares of everybody, for childcare's reason: a pharmacy's demand is the count
of older residents, not the age of the adult population net of children -- and
`age_65_plus_share` and `w65` must never both be regressors, since one is the
other divided by (1 - under_18_share). A test refuses any spec that carries
both.

The gate passes, and the honest reading of HOW it passes is part of the
column. Pooled b(age_65_plus_share) is -0.300 (Conley se 0.319, t -0.94) --
insignificant and, on its face, the wrong sign; Brooklyn +0.264 (se 0.293,
t +0.90), Manhattan -0.424 (se 0.304, t -1.40). What carries the contrast is
the OTHER band: b(age_18_34_share) = -1.128 pooled (se 0.304, t -3.71),
Brooklyn -1.234 (t -3.02). F2 is a contrast over the whole age block, so the
Brooklyn ratio of 1.585 [1.236, 2.032] on Williamsburg -> UES-Carnegie Hill is
roughly five-sixths "fewer 18-34s" and one-sixth "more 65+". The curve is
therefore evidence that pharmacy composition falls where the young are, which
is a real and category-specific finding -- it is the mirror image of bar, on
the same tracts and the same controls -- but it is NOT evidence that pharmacy
composition rises where the old are. Anyone reading the column as "older
neighbourhood, more pharmacy demand" is reading a coefficient that is not
there.

Pharmacy has NO registry anchor loaded either (`analysis.category_anchor`:
anchor_sources NULL, anchor_coverage 0.000), so `in_principled` degrades to
`in_all` and the outcome is built from the same canonical supply the screen
reads -- the D1 trap in its tightest form, exactly as for childcare. 63.9% of
the 5,536 canonical pharmacy POIs are single-source (3,540 of 5,536; 1,996 are
corroborated, 0 have a registry member). The chains are well covered by the
aggregators, so the single-source tail is mostly independents, which is also
where a coverage hole would be. Loading the NYS Board of Pharmacy registry is
the fix, and it is a planned anchor, not a loaded one.

THE MULTIPLIER
--------------------------------------------------------------------------
    age_fit(tract) = exp[ sum_k b_k * (a_k - anchor_k) ]

over the spec's age terms `a_k`: "predicted composition at this tract's age mix
/ predicted at the MN+BK average age mix, every control at its own value" --
the controls cancel because they are identical in numerator and denominator.
The anchor is the unit-weighted MN+BK mix over the estimation sample.

`age_fit_moe` is a 90% MOE by the DELTA METHOD through exp(.): the linear
predictor's variance is the quadratic form of the age deltas against the Conley
coefficient covariance, PLUS each ACS share MOE converted to an SE at 1.645 and
added in quadrature; that variance is scaled by exp(.)^2 and re-inflated to 90%
at 1.645. The renormalizing denominator of the ADULT shares (1 -
under_18_share) is treated as fixed -- a second-order term, stated rather than
hidden.

NON-FILTERING, ENFORCED IN CODE (D48/D57/D61 pattern)
--------------------------------------------------------------------------
`apply_age_fit` issues ONLY `UPDATE ... SET <AGE_FIT_COLUMNS>` on
analysis.address_category and `UPDATE ... SET <ADDRESS_AGE_FIT_COLUMNS>` on
analysis.address. It never INSERTs, never DELETEs, and both SET lists are
asserted disjoint from the screen's own columns
(model/address_gaps.ADDRESS_CATEGORY_SCREEN_COLUMNS / ADDRESS_COLUMNS) -- the
identical mechanical guarantee model/address_demand.py and model/dev_pipeline.py
carry, pinned by tests/test_age_fit.py. `gap_score`, `ratio`, `nearest_m`,
`eligible`, `lead_category`, `n_missing` and `cluster_id` are never named. The
gap SET is bit-identical before and after; only `gap_score_fit`, a SECOND
ranking column that lives beside `gap_score` rather than replacing it, differs.
`age_fit` is always exp(.) and therefore strictly positive, so
`gap_score_fit = gap_score * age_fit_lead` is monotone in `gap_score` at fixed
address: it can reorder, it can never gate.

THE F2 GATE, ALSO IN CODE (docs/bar_age_nyc.md §7.1)
--------------------------------------------------------------------------
The note ships a column only while its failure criteria hold, and names F2 as
the one that binds -- it is the ONLY reason the composition spec is preferred
over the bar-POI count spec, and the test a re-run on a new supply set or ACS
vintage is most likely to fail. It is applied to EVERY category in the registry
WITHOUT relaxation (QUESTIONS D15: "two independent sources agreeing on a sign
is corroboration, not a licence to skip the gate"). So `fit_curve` refuses to
WRITE anything at all unless:

  F2  the BROOKLYN-ONLY Conley CI on the category's own low-age -> high-age
      contrast excludes 1.0, and the point estimate has the demanded SIGN; and
  F3  the dispersion gate passes: (p90 - p10 of the multiplier over the
      estimation tracts) / median(age_fit_moe) >= 1.0 -- the same derived gate
      `docs/age_demand_fit.md` §5 defined and the CEX multiplier failed at 0.10.

A curve that fails its own criterion must not reach the ranking, so the command
exits non-zero and leaves the previous fit JSON untouched rather than
half-writing a fit nobody may apply.

WHAT THE COLUMN MAY NOT BE READ AS (AGE_FIT_DISCLAIMER)
--------------------------------------------------------------------------
Three sentences, and all three are load-bearing. (i) SUPPLY-REVEALED: every
coefficient is fitted on where the supply ALREADY is, so it mixes demand with
residential sorting (young renters move to neighbourhoods that already have
bars at least as hard as bars open where young renters already live; families
move to neighbourhoods that already have daycare) and there is no instrument
here that separates them. (ii) A low value is NEVER evidence that a
neighbourhood does not deserve the service -- the D49/QUESTIONS-X6 hazard, in a
new costume. (iii) Resident age is a PROXY FOR A BUNDLE. Spatial-block CV says
age adds +3.2-3.6% out-of-sample over a density-only model in Brooklyn but ~0%
once income, renter share, walk-to-subway and retail jobs are already in, and
it transfers NEGATIVELY from Brooklyn to Manhattan. It carries real information
relative to what `gap_score` knows and almost none that is uniquely age.

Render the disclaimer untruncated, exactly as `demand_caveat_text` (D49/D57).

SCOPE
--------------------------------------------------------------------------
`CURVES` and nothing else. The placebo (docs/bar_age_nyc.md §5c) ran the bar
specification with all fifteen categories as the outcome: `bar` has the largest
positive b(w18) of the fifteen and `pharmacy` the most negative, which is what
rules out "b(w18) is a generic urbanity coefficient". Those are the two ENDS of
that table and they are the two entries whose gate passes; `childcare`, from
the middle of it, is refused. Every category NOT in `CURVES` keeps a NULL
`age_fit`, not 1.0. NULL means "no curve exists here"; 1.0 would mean "a curve
exists and says neutral", and the two must not be confused.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import pathlib

import numpy as np
import pandas as pd

from loci.model.address_gaps import (
    ADDRESS_CATEGORY_SCREEN_COLUMNS,
    ADDRESS_COLUMNS,
    INTERIM_DIR,
)
from loci.score.supply import (
    DEFAULT_SUPPLY_SET,
    supply_hash as live_supply_hash,
    supply_predicate,
)
from loci.sources.cities.nyc.nys_sla import BAR_DESCRIPTIONS

#: Identifier written into `age_fit_source` on every fitted `bar` row. Bump it
#: when the specification changes -- not when the coefficients are merely
#: re-fitted. Kept as a module constant because D63's CLI help and tests name it.
SPEC_VERSION = "sla_composition_v1"

#: D48 scope, and the sample every curve is estimated on. A coefficient fitted
#: in Manhattan+Brooklyn transfers NEGATIVELY to the other direction across the
#: East River (§6), so a multiplier is applied only where it was estimated.
FIT_BOROUGHS = ("MN", "BK")

ACS_YEAR = 2023            # matches model/address_demographics.py's pinned vintage
DISC_M = 400.0             # the bar reach tier; ~493 m of walking at D53's 1.233 circuity
CONLEY_CUTOFF_M = 2000.0   # Bartlett kernel cutoff; the more conservative of 1 km / 2 km
MIN_POPULATION = 100.0     # tracts below this are institutional/very-low-response noise
MIN_WALK_M = 25.0          # floor before log(walk_m_to_subway); a 0 m walk is a 0 m fiction
CI_Z = 1.96                # 95% CI on the age contrast (the F2 gate reads this)
MOE_Z = 1.645              # ACS 90% MOE <-> SE, both directions
RETAIL_NAICS = "CNS07"     # retail trade. NEVER CNS18: food-service payroll IS the outcome.

#: docs/bar_age_nyc.md §7.1 F3, inherited from docs/age_demand_fit.md §5: the
#: multiplier ships only where the signal it carries exceeds the ACS noise it is
#: built from. One derived number, recomputed every run, no owner prior.
DISPERSION_GATE_MIN = 1.0

#: §7.2 test 5: `gap_score * age_fit` is monotone in `gap_score` for any
#: positive multiplier, but a multiplier outside this band would be doing more
#: work than `gap_score` itself and is a sign the fit has gone wrong. Reported,
#: and pinned by a test, rather than silently clipped.
MULTIPLIER_BOUNDS = (0.5, 2.0)

#: The two NTAs of the owner's BAR example, resolved by NTA CODE rather than
#: name so a DCP label change cannot silently retarget the F2 gate.
CONTRAST_NTAS = {"from": "MN0802", "to": "MN0303"}   # UES-Carnegie Hill -> East Village

#: An NTA must carry at least this many in-scope addresses to be eligible as an
#: endpoint of a DERIVED contrast. A three-address NTA's age mix is noise, and a
#: gate evaluated on noise is not a gate.
CONTRAST_MIN_ADDRESSES = 500

#: The ONLY columns the address_category writer may name in a SET clause.
#: Disjoint from ADDRESS_CATEGORY_SCREEN_COLUMNS by construction; a test pins it.
AGE_FIT_COLUMNS = ["age_fit", "age_fit_moe", "age_fit_source"]

#: The ONLY columns the analysis.address writer may name in a SET clause.
#: Disjoint from ADDRESS_COLUMNS (the screen's own) by construction; pinned too.
ADDRESS_AGE_FIT_COLUMNS = ["age_fit_lead", "age_fit_lead_moe", "gap_score_fit"]

#: Render UNTRUNCATED, same rule as demand_caveat_text (D49/D57). All three
#: sentences; see the module docstring for why each one is load-bearing.
AGE_FIT_DISCLAIMER = (
    "Supply-revealed: this is where the New York market has historically put "
    "this category's supply relative to resident age -- demand and residential "
    "sorting together, not separated. A low value is never evidence that a "
    "neighbourhood does not want the service. Resident age here is a proxy for "
    "a bundle (young, renter, transit-rich, commercially active) and adds "
    "essentially nothing once those are measured directly, so it must not be "
    "read as an isolated age effect."
)

#: Each age regressor's published ACS 90% MOE column ON THE PANEL. `w18`/`w65`
#: are the ADULT-renormalized shares, so their MOEs are the published ones
#: divided by the same (1 - under_18_share); `under_18_share` uses its own MOE
#: as published. A term with no entry here would silently lose its ACS
#: uncertainty, so `_age_moe_columns` raises rather than defaulting.
AGE_MOE_COLUMNS = {
    "w18": "w18_moe",
    "w65": "w65_moe",
    "under_18_share": "under_18_share_moe",
    # D6x `pharmacy`: the UN-renormalized adult bands, as ACS publishes them.
    # A pharmacy's demand variable is "how many 65+ people live here", a share
    # of everybody, for the same reason childcare's is `under_18_share` -- and
    # `age_65_plus_share` and `w65` must never both be regressors, since one is
    # the other divided by (1 - under_18_share).
    "age_18_34_share": "age_18_34_share_moe",
    "age_65_plus_share": "age_65_plus_share_moe",
}


class AgeFitGateFailure(RuntimeError):
    """A fitted curve failed its own published failure criterion
    (docs/bar_age_nyc.md §7.1). Raised BEFORE anything is written: a curve that
    fails F2 or F3 must not reach the ranking, and half-writing it so a later
    `apply` can pick it up is exactly the failure mode the gate exists to
    prevent."""


class AgeFitStale(RuntimeError):
    """The stored curve was fitted against a different supply set or ACS
    vintage than the database now holds. A SUPPLY-revealed coefficient is only
    valid against the supply set it was revealed from (docs/bar_age_nyc.md §7.2
    test 7), so `apply_age_fit` refuses rather than multiplying today's gap set
    by yesterday's curve."""


# ------------------------------------------------------------ the registry

@dataclasses.dataclass(frozen=True)
class ContrastSpec:
    """How a category's F2 contrast endpoints are chosen.

    `kind="fixed"` pins two NTA codes (bar: the owner's own example, so the gate
    is evaluated on exactly the comparison that motivated the column).
    `kind="extreme"` DERIVES them from the panel as the NTAs with the lowest and
    highest unit-weighted `variable` among MN+BK NTAs carrying at least
    `min_addresses` addresses -- because for a category whose demand variable is
    not the owner's anecdote, hand-picking two neighbourhoods would be choosing
    the answer.
    """
    kind: str
    from_nta: str | None = None
    to_nta: str | None = None
    variable: str | None = None
    min_addresses: int = CONTRAST_MIN_ADDRESSES
    #: F2 requires the point estimate to have this sign as well as a CI that
    #: excludes 1.0. `+1` = the high-demand endpoint must have MORE of the
    #: category. A CI that excludes 1.0 from BELOW is a rejection of the
    #: hypothesis, not a confirmation of it.
    require_sign: int = 1


@dataclasses.dataclass(frozen=True)
class CategorySpec:
    """One category's curve: outcome, regressors, contrast, radius.

    Everything NOT here -- controls, Conley SEs, anchor, delta-method MOE,
    F2/F3 gate, UPDATE-only writer -- is shared across categories on purpose,
    so a second category cannot get a weaker gate than the first."""
    category: str
    spec_version: str
    radius_m: float
    #: the age regressors, in the order the coefficient vector and the Conley
    #: covariance block are stored in. The FIRST is the primary demand variable.
    age_terms: tuple[str, ...]
    contrast: ContrastSpec
    #: "sla" -> NYS SLA on-premises licences (bar-type / all on-premises);
    #: "poi" -> canonical supply (this category / all categories).
    overlay: str
    outcome_stem: str
    outcome_label: str
    #: extra outcomes fitted and REPORTED as robustness, never shipped.
    robustness_outcomes: tuple[str, ...] = ()

    @property
    def primary_age_term(self) -> str:
        return self.age_terms[0]

    @property
    def r(self) -> int:
        """The radius as a column suffix. Bar's is 400, so bar's design column
        names -- and therefore its FORMULA STRING -- are byte-identical to
        D63's."""
        return int(self.radius_m)

    @property
    def outcome_col(self) -> str:
        return f"{self.outcome_stem}_{self.r}"

    @property
    def fit_path(self) -> pathlib.Path:
        return INTERIM_DIR / f"age_fit_{self.category}.json"

    @property
    def formula(self) -> str:
        return f"{self.outcome_col} ~ {self.rhs()} + MN"

    def rhs(self) -> str:
        ages = " + ".join(self.age_terms)
        return (f"{ages} + lunits_{self.r} + lwalk + linc + renter_share "
                f"+ lretail_{self.r}")

    def formula_one_borough(self) -> str:
        """`MN` is dropped for a borough-internal fit: a constant fixed effect
        is not identified."""
        return f"{self.outcome_col} ~ {self.rhs()}"


def reach_m(category: str) -> float:
    """A category's reach tier, read from reach_tiers.yaml through the same
    `loci.reach.load_reach` the address screen uses -- never pinned here.

    The disc has to be the distance at which the category is actually consumed,
    and that number is owned by the reach table (D41/D53), not by this module.
    Read at import, so a change to the tier changes the design-column suffix and
    therefore the formula string, and the fit is invalidated loudly."""
    from loci.reach import load_reach

    return float(load_reach("tiers")[category])


CHILDCARE_M = reach_m("childcare")
PHARMACY_M = reach_m("pharmacy")

BAR_SPEC = CategorySpec(
    category="bar",
    spec_version=SPEC_VERSION,
    radius_m=DISC_M,
    age_terms=("w18", "w65"),
    contrast=ContrastSpec(kind="fixed", from_nta=CONTRAST_NTAS["from"],
                          to_nta=CONTRAST_NTAS["to"]),
    overlay="sla",
    outcome_stem="bar_share",
    outcome_label=("log(1 + bar-type on-premises licences within {r} m) "
                   "- log(1 + all on-premises licences within {r} m)"),
)

CHILDCARE_SPEC = CategorySpec(
    category="childcare",
    spec_version="poi_composition_v1",
    radius_m=CHILDCARE_M,
    # under_18_share FIRST: for childcare the direct demand variable is the
    # presence of children, not the age of adults. The two adult shares stay so
    # the placebo b(w18) remains comparable to docs/bar_age_nyc.md §5c.
    age_terms=("under_18_share", "w18", "w65"),
    contrast=ContrastSpec(kind="extreme", variable="under_18_share",
                          min_addresses=CONTRAST_MIN_ADDRESSES, require_sign=1),
    overlay="poi",
    outcome_stem="childcare_share",
    outcome_label=("log(1 + canonical childcare POIs within {r} m) "
                   "- log(1 + ALL canonical POIs within {r} m)"),
    # The plain count, reported so the composition choice is defended by a
    # number rather than by precedent. NEVER shipped without a decision.
    robustness_outcomes=("count", "under_5"),
)

PHARMACY_SPEC = CategorySpec(
    category="pharmacy",
    spec_version="poi_composition_v1",
    radius_m=PHARMACY_M,
    # age_65_plus_share FIRST: the placebo (docs/bar_age_nyc.md §5c) and the
    # CEX note independently give the same sign for pharmacy -- older, more
    # pharmacy -- and it is the ONE band whose consumption story is direct
    # (prescription volume rises steeply with age) rather than a lifestyle
    # proxy. Both bands enter UN-renormalized, as shares of everybody: mixing
    # a raw 65+ share with an adult-renormalized w65 in one regression would be
    # putting the same variable in twice.
    age_terms=("age_65_plus_share", "age_18_34_share"),
    contrast=ContrastSpec(kind="extreme", variable="age_65_plus_share",
                          min_addresses=CONTRAST_MIN_ADDRESSES, require_sign=1),
    overlay="poi",
    outcome_stem="pharmacy_share",
    outcome_label=("log(1 + canonical pharmacy POIs within {r} m) "
                   "- log(1 + ALL canonical POIs within {r} m)"),
    # `count` for the same reason childcare reports it: the composition choice
    # has to be defended by a number rather than by precedent, and a count spec
    # that disagrees is a finding, not a switch. `adult_shares` refits the
    # SHIPPED outcome on bar's own (w18, w65) pair so b(w18) is directly
    # comparable to the §5c placebo's -0.846 -- the raw age_18_34_share
    # coefficient is the same quantity rescaled by (1 - under_18_share) and is
    # therefore NOT the placebo's number.
    robustness_outcomes=("count", "adult_shares"),
)

#: The registry. A category absent from here has NO curve and keeps a NULL
#: `age_fit` -- never 1.0.
CURVES: dict[str, CategorySpec] = {
    s.category: s for s in (BAR_SPEC, CHILDCARE_SPEC, PHARMACY_SPEC)}

#: The ONLY categories a curve exists for. Derived from CURVES so the two can
#: never drift.
FITTED_CATEGORIES = tuple(CURVES)

#: Back-compat: D63's module-level bar names, still imported by tests and by the
#: negative pin (§7.2 test 8) that the outcome is the COMPOSITION one.
FORMULA = BAR_SPEC.formula
FORMULA_ONE_BOROUGH = BAR_SPEC.formula_one_borough()
FIT_PATH = BAR_SPEC.fit_path


def spec_for(category: str) -> CategorySpec:
    try:
        return CURVES[category]
    except KeyError:
        raise ValueError(
            f"no age-fit curve for {category!r}; fitted categories are "
            f"{', '.join(sorted(CURVES))}") from None


def _age_moe_columns(terms) -> list[str]:
    """The MOE column for each age term. Raises on an unknown term rather than
    defaulting to zero: a regressor that silently loses its ACS uncertainty
    would shrink `age_fit_moe` and make the F3 gate easier to pass, which is
    exactly backwards."""
    out = []
    for t in terms:
        if t not in AGE_MOE_COLUMNS:
            raise KeyError(
                f"age term {t!r} has no MOE column in AGE_MOE_COLUMNS; add one "
                "before using it as a regressor -- a term without its ACS "
                "margin would make the F3 dispersion gate easier to pass")
        out.append(AGE_MOE_COLUMNS[t])
    return out


# ------------------------------------------------------------ the tract panel

@dataclasses.dataclass(frozen=True)
class TractPanel:
    """The estimation frame plus everything downstream needs from it.

    `tracts` is one row per tract with `keep` marking the regression sample;
    `n_target` / `n_universe` and `supply_hash` are carried so the fit can stamp
    exactly which inputs produced it.

    `supply_hash` is the LIVE hash from `score.supply.supply_hash(con)` -- what
    the database's supply actually is right now, computed the same way both at
    fit time and at `check_fit_is_current` time so the two are comparable.
    `screen_supply_hash` is a SEPARATE, informational field: the stamp the last
    `loci address-gaps` run left on `analysis.address`. It is carried only so a
    reader can see when the screen and the curve have drifted apart; it is
    NEVER hashed into `inputs_hash` and never drives staleness -- an
    address-gaps run that does not change supply must not trip a false alarm
    on a category (e.g. bar) whose supply did not move."""
    tracts: pd.DataFrame
    n_universe: int
    n_target: int
    supply_hash: str | None
    screen_supply_hash: str | None
    acs_year: int


def _to_utm(lon, lat) -> np.ndarray:
    """(n, 2) EPSG:32618 metres. Every distance in this module is metric and
    planar; DuckDB GEOMETRY carries no SRID (see loci.db), so the projection is
    explicit here rather than assumed."""
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    x, y = tf.transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.column_stack([x, y])


def _disc_sums(centres: np.ndarray, points: np.ndarray, radius_m: float,
               weights: np.ndarray | None = None) -> np.ndarray:
    """For each centre, the count (or weighted sum) of `points` within
    `radius_m`. One cKDTree per call; the panel is ~1k centres against at most
    ~300k points, so this is milliseconds and needs no tiling."""
    from scipy.spatial import cKDTree

    if len(points) == 0:
        return np.zeros(len(centres))
    idx = cKDTree(points).query_ball_point(centres, r=radius_m)
    if weights is None:
        return np.array([len(i) for i in idx], dtype=float)
    w = np.asarray(weights, float)
    return np.array([w[i].sum() for i in idx], dtype=float)


def _addresses_sql(boroughs: list[str]) -> str:
    holes = ", ".join("?" for _ in boroughs)
    return f"""
        SELECT a.address_id, a.borough, a.lon, a.lat, a.units_capped,
               a.nta_code, a.neighborhood, a.eligible, a.gap_score, a.lead_category,
               d.tract_geoid, d.population, d.median_hh_income, d.renter_share,
               d.under_18_share, d.under_18_share_moe,
               d.age_18_34_share, d.age_65_plus_share,
               d.age_18_34_share_moe, d.age_65_plus_share_moe
        FROM analysis.address a
        JOIN analysis.address_demographics d USING (address_id)
        WHERE a.borough IN ({holes}) AND d.acs_year = ?
    """


def load_addresses(con, boroughs: list[str], acs_year: int = ACS_YEAR) -> pd.DataFrame:
    """Every in-scope address with its TRACT's demographics attached (D56: a
    PLUTO lot sits in exactly one 2020 tract, so this is a lookup, not an
    apportionment) and the adult-renormalized age shares already computed.
    READ-ONLY."""
    df = con.execute(_addresses_sql(boroughs), [*boroughs, acs_year]).fetchdf()
    df = df[df["tract_geoid"].notna()].copy()
    df["units_capped"] = df["units_capped"].fillna(0.0).clip(lower=0.0)
    # ADULT shares: the omitted band is 35-64, so a coefficient reads "relative
    # to a 35-64 adult" rather than "relative to a resident, children included".
    # `under_18_share` is NOT renormalized -- it is a share of everybody, which
    # is what makes it a clean demand variable for childcare and leaves it
    # linearly independent of the two adult shares.
    adult = 1.0 - df["under_18_share"]
    with np.errstate(divide="ignore", invalid="ignore"):
        df["w18"] = df["age_18_34_share"] / adult
        df["w65"] = df["age_65_plus_share"] / adult
        df["w18_moe"] = df["age_18_34_share_moe"] / adult
        df["w65_moe"] = df["age_65_plus_share_moe"] / adult
    return df


def _overlay_points(con, spec: CategorySpec, boroughs: list[str]
                    ) -> tuple[np.ndarray, np.ndarray, int, int]:
    """(target_xy, universe_xy, n_universe, n_target) for a spec's outcome.

    `sla`: bar-type on-premises licences against ALL on-premises licences. The
    bar vocabulary is nys_sla.BAR_DESCRIPTIONS -- the SAME set that decides what
    enters staging.poi as a `bar` -- imported rather than copied, so the overlay
    and the category can never drift apart. (There is no `Tavern` licence type
    in the NYC feed; `Additional Bar` is a RIDER on an existing premises, not a
    venue, and is deliberately not bar-type.)

    `poi`: this category's canonical POIs against ALL canonical POIs. Citywide,
    NOT borough-filtered: a 640 m disc near the East River legitimately sees
    Queens supply, and clipping it at the borough line would manufacture a
    composition cliff along the boundary.
    """
    if spec.overlay == "sla":
        holes = ", ".join("?" for _ in boroughs)
        lic = con.execute(f"""
            SELECT lower(trim(description)) AS description,
                   ST_X(geom) AS lon, ST_Y(geom) AS lat
            FROM staging.alcohol_licences
            WHERE active AND borough IN ({holes})
              AND classification = 'on_premises' AND geom IS NOT NULL
        """, boroughs).fetchdf()
        xy = _to_utm(lic["lon"], lic["lat"]) if len(lic) else np.zeros((0, 2))
        is_target = (lic["description"].isin(BAR_DESCRIPTIONS).to_numpy()
                     if len(lic) else np.zeros(0, bool))
        return xy[is_target], xy, len(lic), int(is_target.sum())

    if spec.overlay == "poi":
        pred = supply_predicate(DEFAULT_SUPPLY_SET)
        poi = con.execute(f"""
            SELECT s.category, ST_X(s.geom) AS lon, ST_Y(s.geom) AS lat
            FROM analysis.poi_supply s
            WHERE s.{pred} AND s.geom IS NOT NULL
        """).fetchdf()
        xy = _to_utm(poi["lon"], poi["lat"]) if len(poi) else np.zeros((0, 2))
        is_target = ((poi["category"] == spec.category).to_numpy()
                     if len(poi) else np.zeros(0, bool))
        return xy[is_target], xy, len(poi), int(is_target.sum())

    raise ValueError(f"unknown overlay {spec.overlay!r}")


def build_tract_panel(con, spec: CategorySpec = BAR_SPEC,
                      boroughs: list[str] = FIT_BOROUGHS,
                      acs_year: int = ACS_YEAR,
                      addresses: pd.DataFrame | None = None) -> TractPanel:
    """Aggregate addresses to tracts, hang the spec's disc measures off each
    tract's RESIDENTIAL centroid, and mark the regression sample. READ-ONLY:
    this function issues four SELECTs and no write of any kind (`supply_hash`
    itself only reads analysis.poi_supply / analysis.category_anchor).

    `addresses` is injectable so tests can drive the whole estimator off a
    synthetic frame without a warehouse.
    """
    boroughs = list(boroughs)
    r = spec.radius_m
    addr = load_addresses(con, boroughs, acs_year) if addresses is None else addresses.copy()
    xy = _to_utm(addr["lon"], addr["lat"])
    addr["x"], addr["y"] = xy[:, 0], xy[:, 1]

    # --- residential centroid: units_capped-weighted, NOT geometric ----------
    # A geometric tract centroid can land in a park, a rail yard or the middle
    # of Prospect Park. Where a tract has no capped units at all (pure-commercial
    # lots), fall back to the unweighted address mean rather than dividing by 0.
    g = addr.groupby("tract_geoid", sort=True)
    unit_sum = g["units_capped"].transform("sum")
    wt = np.where(unit_sum.to_numpy() > 0, addr["units_capped"].to_numpy(), 1.0)
    addr["_wt"] = wt
    wsum = addr.groupby("tract_geoid", sort=True)["_wt"].sum()
    tr = pd.DataFrame({
        "x": addr.assign(_v=addr["x"] * addr["_wt"]).groupby("tract_geoid", sort=True)["_v"].sum() / wsum,
        "y": addr.assign(_v=addr["y"] * addr["_wt"]).groupby("tract_geoid", sort=True)["_v"].sum() / wsum,
    })
    first = g.first()
    carry = ["borough", "population", "median_hh_income", "renter_share",
             "under_18_share", "under_18_share_moe", "w18", "w65",
             "w18_moe", "w65_moe",
             # the UN-renormalized adult bands, carried for `pharmacy` (and for
             # the adult-share robustness refit). Additive: no existing spec
             # names them, so nothing already fitted moves.
             "age_18_34_share", "age_65_plus_share",
             "age_18_34_share_moe", "age_65_plus_share_moe"]
    for c in carry:
        tr[c] = first[c]
    tr["units_tract"] = g["units_capped"].sum()
    tr["n_addr"] = g.size()
    tr = tr.reset_index()
    centres = tr[["x", "y"]].to_numpy()

    # --- the outcome overlay -------------------------------------------------
    target_xy, universe_xy, n_universe, n_target = _overlay_points(con, spec, boroughs)
    tr[f"universe_{spec.r}"] = _disc_sums(centres, universe_xy, r)
    tr[f"target_{spec.r}"] = _disc_sums(centres, target_xy, r)

    # --- exposure: units inside the SAME disc, not the tract's own count -----
    # A tract's units and a disc around its centroid are different geographies;
    # using the tract count as the denominator for a disc count would be a
    # units mismatch.
    tr[f"units_{spec.r}"] = _disc_sums(centres, addr[["x", "y"]].to_numpy(), r,
                                       addr["units_capped"].to_numpy())

    # --- daytime control: CNS07 retail jobs ----------------------------------
    jobs = con.execute(f"""
        SELECT p.jobs, ST_X(h.centroid) AS lon, ST_Y(h.centroid) AS lat
        FROM analysis.hex_panel p JOIN analysis.hex h USING (h3_index)
        WHERE p.naics = '{RETAIL_NAICS}'
          AND p.year = (SELECT max(year) FROM analysis.hex_panel)
    """).fetchdf()
    tr[f"retail_jobs_{spec.r}"] = _disc_sums(
        centres, _to_utm(jobs["lon"], jobs["lat"]) if len(jobs) else np.zeros((0, 2)),
        r, jobs["jobs"].to_numpy() if len(jobs) else None)

    # --- transit: nearest hex centroid that HAS a walk distance --------------
    # walk_m_to_subway is present on 5,845 of 8,321 hexes; a tract takes the
    # value of the nearest hex that has one rather than dropping out entirely.
    ctrl = con.execute("""
        SELECT c.walk_m_to_subway, ST_X(h.centroid) AS lon, ST_Y(h.centroid) AS lat
        FROM analysis.hex_controls c JOIN analysis.hex h USING (h3_index)
        WHERE c.walk_m_to_subway IS NOT NULL
    """).fetchdf()
    if len(ctrl):
        from scipy.spatial import cKDTree
        _, ni = cKDTree(_to_utm(ctrl["lon"], ctrl["lat"])).query(centres)
        tr["walk_m_to_subway"] = ctrl["walk_m_to_subway"].to_numpy()[ni]
    else:
        tr["walk_m_to_subway"] = np.nan

    # --- the estimation sample ----------------------------------------------
    # Ten MN+BK tracts with population >= 100 publish no median household income
    # (large-institution and very-low-response tracts); they drop out of the
    # REGRESSION but keep their multiplier, which needs only the age shares.
    keep = (
        (tr["population"] >= MIN_POPULATION)
        & tr["median_hh_income"].notna() & (tr["median_hh_income"] > 0)
        & tr["renter_share"].notna()
        & tr["walk_m_to_subway"].notna() & (tr[f"units_{spec.r}"] > 0)
    )
    for t in spec.age_terms:
        keep &= tr[t].notna()
    tr["keep"] = keep
    # LIVE hash of the supply as the database now holds it -- not the screen's
    # stamp. `analysis.address.supply_hash` is only ever as fresh as the last
    # `loci address-gaps` run; reading it here would date the curve's inputs
    # to that run instead of to the actual poi_supply/category_anchor state,
    # and would falsely flag a curve stale whenever address-gaps re-runs for
    # an unrelated reason.
    screen_rows = con.execute(
        "SELECT DISTINCT supply_hash FROM analysis.address WHERE supply_hash IS NOT NULL"
    ).fetchall()
    return TractPanel(
        tracts=tr,
        n_universe=n_universe,
        n_target=n_target,
        supply_hash=live_supply_hash(con),
        screen_supply_hash=screen_rows[0][0] if len(screen_rows) == 1 else None,
        acs_year=acs_year,
    )


# ---------------------------------------------------------------- estimation

def _design(tr: pd.DataFrame, spec: CategorySpec,
            extra: pd.DataFrame | None = None) -> pd.DataFrame:
    """The regression frame: the estimation sample with every transform the
    formula names already materialized, so the formula string is a literal
    reading of docs/bar_age_nyc.md §3 rather than a nest of calls.

    `extra` is an optional tract-indexed frame of ROBUSTNESS regressors (the
    under-5 share); it is merged but never enters the shipped formula."""
    d = tr[tr["keep"]].copy()
    r = spec.r
    d[spec.outcome_col] = np.log1p(d[f"target_{r}"]) - np.log1p(d[f"universe_{r}"])
    d[f"{spec.category}_count_{r}"] = np.log1p(d[f"target_{r}"])
    d[f"lunits_{r}"] = np.log(d[f"units_{r}"])
    d[f"lretail_{r}"] = np.log1p(d[f"retail_jobs_{r}"])
    d["lwalk"] = np.log(d["walk_m_to_subway"].clip(lower=MIN_WALK_M))
    d["linc"] = np.log(d["median_hh_income"])
    d["MN"] = (d["borough"] == "MN").astype(float)
    if extra is not None:
        d = d.merge(extra, on="tract_geoid", how="left")
    return d


def _conley_cov(model, xy: np.ndarray, cutoff_m: float = CONLEY_CUTOFF_M) -> np.ndarray:
    """Conley spatial-HAC covariance, Bartlett kernel, `cutoff_m` bandwidth.

    Standard sandwich with a distance-decayed meat: K_ij = max(0, 1 - d_ij/h).
    The finite-sample correction n/(n-k) matches statsmodels' HC0->HC1 step so
    the two are comparable. Needed because the residuals here have Moran's I
    ~= 0.42 -- neighbouring tracts share the same district and their discs
    physically overlap -- so the effective n is far below the row count and HC3
    would be badly optimistic.
    """
    from scipy.spatial import distance_matrix

    X = np.asarray(model.model.exog, float)
    e = np.asarray(model.resid, float)
    n, k = X.shape
    dist = distance_matrix(xy, xy)
    kern = np.where(dist <= cutoff_m, 1.0 - dist / cutoff_m, 0.0)
    xe = X * e[:, None]
    bread = np.linalg.inv(X.T @ X)
    return bread @ (xe.T @ kern @ xe) @ bread * (n / (n - k))


def _contrast(params: pd.Series, cov: np.ndarray, terms, deltas) -> dict:
    """A partial effect between two age mixes: the ratio of predicted outcome at
    the two mixes with EVERY control held fixed, plus its Conley CI. A linear
    contrast in the log-composition, exponentiated."""
    names = list(params.index)
    g = np.zeros(len(names))
    for t, dv in zip(terms, deltas):
        g[names.index(t)] = float(dv)
    delta = float(g @ params.to_numpy())
    se = float(np.sqrt(g @ cov @ g))
    return {
        "ratio": float(np.exp(delta)),
        "ci_low": float(np.exp(delta - CI_Z * se)),
        "ci_high": float(np.exp(delta + CI_Z * se)),
        "se_log": se,
    }


def _nta_age_mix(addr: pd.DataFrame, nta_code: str, terms) -> tuple[float, ...]:
    """The age mix of one NTA: the MEDIAN over its addresses, matching
    docs/bar_age_nyc.md §2.3's own convention.

    DERIVED from the panel rather than pinned as a literal, so the F2 gate
    re-computes honestly on a new ACS vintage instead of testing last year's
    numbers. The median, not a unit-weighted mean, for two reasons: it is the
    statistic the note's NTA table reports (Carnegie Hill w18 0.158 / w65 0.404,
    East Village 0.540 / 0.184) so the gate is evaluated on the same contrast
    that was published; and one 500-unit tower in an atypical tract must not
    move a neighbourhood's age mix, which is exactly what a unit-weighted mean
    lets it do (it pulls Carnegie Hill to w18 0.212 and shrinks the contrast by
    a third).
    """
    sub = addr[addr["nta_code"] == nta_code]
    if sub.empty:
        raise ValueError(f"NTA {nta_code!r} has no addresses in scope; F2 cannot be evaluated")
    return tuple(float(sub[t].median()) for t in terms)


def resolve_contrast_ntas(addr: pd.DataFrame, spec: CategorySpec) -> tuple[str, str, pd.DataFrame]:
    """(from_nta, to_nta, the ranking table). For a `fixed` contrast this is the
    pinned pair; for an `extreme` contrast the endpoints are DERIVED as the
    lowest and highest UNIT-WEIGHTED `variable` among NTAs with at least
    `min_addresses` in-scope addresses.

    Unit-weighted for the selection because the question "which neighbourhood
    has the most children" is about people, and an NTA of 3,000 one-family lots
    and an NTA of 3,000 studios are not the same neighbourhood. The MIX the
    contrast is then evaluated at is still the MEDIAN (`_nta_age_mix`), so the
    gate is computed the same way bar's was; the two statistics are reported
    side by side rather than one hidden inside the other.
    """
    c = spec.contrast
    ranked = pd.DataFrame(columns=["nta_code", "neighborhood", "n_addr",
                                   "units", "mean", "median", "weighted"])
    if c.kind == "fixed":
        return c.from_nta, c.to_nta, ranked
    if c.kind != "extreme":
        raise ValueError(f"unknown contrast kind {c.kind!r}")

    var = c.variable
    sub = addr[addr[var].notna() & addr["nta_code"].notna()].copy()
    sub["_u"] = sub["units_capped"].fillna(0.0).clip(lower=0.0)
    sub["_wv"] = sub["_u"] * sub[var]
    g = sub.groupby("nta_code", sort=True)
    agg = pd.DataFrame({
        "neighborhood": g["neighborhood"].first(),
        "n_addr": g.size(),
        "units": g["_u"].sum(),
        "_wv": g["_wv"].sum(),
        "mean": g[var].mean(),
        "median": g[var].median(),
    })
    # An NTA of pure-commercial lots has zero capped units; fall back to the
    # unweighted mean there rather than dividing by 0.
    agg["weighted"] = np.where(agg["units"] > 0, agg["_wv"] / agg["units"].replace(0, np.nan),
                               agg["mean"])
    ranked = agg.drop(columns=["_wv"]).reset_index()
    ranked = ranked[ranked["n_addr"] >= c.min_addresses].sort_values("weighted")
    if len(ranked) < 2:
        raise ValueError(
            f"fewer than two NTAs carry >= {c.min_addresses} addresses; the "
            f"{spec.category} contrast cannot be derived")
    return (str(ranked.iloc[0]["nta_code"]), str(ranked.iloc[-1]["nta_code"]), ranked)


def multiplier_terms(deltas: np.ndarray, coefs: np.ndarray) -> np.ndarray:
    """The general multiplier: exp(delta @ coefs) for an (n, k) delta matrix.

    exp(.) of a linear form in the age deltas: strictly positive for any finite
    input, which is what makes `gap_score * age_fit` non-filtering by
    construction rather than by assertion. The ONLY place the formula is
    written; `multiplier` below is the two-term bar wrapper over it."""
    d = np.atleast_2d(np.asarray(deltas, float))
    return np.exp(d @ np.asarray(coefs, float))


def multiplier(w18, w65, b18: float, b65: float,
               anchor_w18: float, anchor_w65: float) -> np.ndarray:
    """age_fit for a two-adult-share curve (bar). Kept as-is from D63 so the
    published closed form is still checkable against arithmetic."""
    a = np.asarray(w18, float) - anchor_w18
    b = np.asarray(w65, float) - anchor_w65
    return multiplier_terms(np.column_stack([np.atleast_1d(a), np.atleast_1d(b)]),
                            [b18, b65]).reshape(np.shape(a))


def multiplier_moe_terms(fit_value, deltas: np.ndarray, coefs: np.ndarray,
                         cov_age: np.ndarray, moes: np.ndarray) -> np.ndarray:
    """90% MOE on `multiplier_terms`, by the DELTA METHOD through exp(.).

    Var(log age_fit) has two independent parts, added in quadrature:
      * COEFFICIENT uncertainty -- the quadratic form of the age deltas against
        `cov_age`, the (k, k) block of the CONLEY covariance (never HC3; see the
        module docstring);
      * ACS SAMPLING uncertainty -- each published 90% share MOE converted to an
        SE at 1.645 and scaled by its own coefficient.
    Var(age_fit) ~= age_fit^2 * Var(log age_fit); the result is re-inflated to a
    90% MOE at 1.645 so it is directly comparable to the ACS MOEs it is built
    from. The renormalizing denominator of the ADULT shares (1 -
    under_18_share) is treated as fixed: second order, and stated rather than
    hidden."""
    d = np.atleast_2d(np.asarray(deltas, float))
    C = np.asarray(cov_age, float)
    b = np.asarray(coefs, float)
    var_coef = np.einsum("ij,jk,ik->i", d, C, d)
    var_acs = (((np.atleast_2d(np.asarray(moes, float)) * b) / MOE_Z) ** 2).sum(axis=1)
    return MOE_Z * np.asarray(fit_value, float) * np.sqrt(var_coef + var_acs)


def multiplier_moe(fit_value, w18, w65, b18: float, b65: float,
                   anchor_w18: float, anchor_w65: float,
                   cov_age: np.ndarray, w18_moe, w65_moe) -> np.ndarray:
    """The two-term bar wrapper over `multiplier_moe_terms`."""
    a = np.atleast_1d(np.asarray(w18, float) - anchor_w18)
    b = np.atleast_1d(np.asarray(w65, float) - anchor_w65)
    moes = np.column_stack([np.atleast_1d(np.asarray(w18_moe, float)),
                            np.atleast_1d(np.asarray(w65_moe, float))])
    return multiplier_moe_terms(fit_value, np.column_stack([a, b]),
                                [b18, b65], cov_age, moes)


def _deltas(frame: pd.DataFrame, terms, anchors) -> np.ndarray:
    return np.column_stack([frame[t].to_numpy(float) - float(a)
                            for t, a in zip(terms, anchors)])


def _fit_one(d: pd.DataFrame, spec: CategorySpec, outcome: str, terms,
             cutoff_m: float, mix_from, mix_to, extra_terms: tuple[str, ...] = ()
             ) -> dict:
    """One OLS + Conley fit on an already-built design, pooled and per borough.

    Shared by the SHIPPED specification and by every robustness variant, so a
    robustness number can never come from a slightly different sample or a
    slightly different SE than the one it is supposed to be compared against."""
    import statsmodels.formula.api as smf

    rhs = " + ".join([*terms, *extra_terms,
                      f"lunits_{spec.r}", "lwalk", "linc", "renter_share",
                      f"lretail_{spec.r}"])
    dd = d.dropna(subset=[outcome, *terms, *extra_terms]).copy()
    model = smf.ols(f"{outcome} ~ {rhs} + MN", data=dd).fit()
    cov = _conley_cov(model, dd[["x", "y"]].to_numpy(), cutoff_m)
    names = list(model.params.index)
    idx = [names.index(t) for t in terms]
    cov_age = np.array([[cov[i, j] for j in idx] for i in idx])
    deltas = [float(b) - float(a) for a, b in zip(mix_from, mix_to)]

    by_borough: dict[str, dict] = {}
    for boro in sorted(dd["borough"].unique()):
        sub = dd[dd["borough"] == boro]
        if len(sub) < 50:
            continue
        m_b = smf.ols(f"{outcome} ~ {rhs}", data=sub).fit()
        cov_b = _conley_cov(m_b, sub[["x", "y"]].to_numpy(), cutoff_m)
        nb = list(m_b.params.index)
        by_borough[boro] = {
            "n_tracts": int(m_b.nobs),
            "coefs": {t: float(m_b.params[t]) for t in terms},
            "se_conley": {t: float(np.sqrt(cov_b[nb.index(t), nb.index(t)]))
                          for t in terms},
            "t_conley": {t: float(m_b.params[t]
                                  / np.sqrt(cov_b[nb.index(t), nb.index(t)]))
                         for t in terms},
            "contrast": _contrast(m_b.params, cov_b, terms, deltas),
        }
    return {
        "outcome": outcome,
        "formula": f"{outcome} ~ {rhs} + MN",
        "n_tracts": int(model.nobs),
        "r_squared": float(model.rsquared),
        "coefs": {t: float(model.params[t]) for t in terms},
        "se_conley": {t: float(np.sqrt(cov[names.index(t), names.index(t)]))
                      for t in terms},
        "t_conley": {t: float(model.params[t]
                              / np.sqrt(cov[names.index(t), names.index(t)]))
                     for t in terms},
        "cov_age_conley": [[float(v) for v in row] for row in cov_age],
        "coefficients": {k: float(v) for k, v in model.params.items()},
        "contrast_pooled": _contrast(model.params, cov, terms, deltas),
        "by_borough": by_borough,
        "_model_params": model.params,
        "_cov": cov,
        "_design": dd,
    }


def under_5_share(acs_year: int = ACS_YEAR,
                  path: pathlib.Path | None = None) -> pd.DataFrame | None:
    """Tract-level under-5 share from the RAW ACS cache, for the D64 robustness
    check only. Returns None when the cache is absent.

    B01001_003 (male under 5) + B01001_027 (female under 5) over B01001_001,
    the table's OWN total -- the same denominator grid/acs.py uses for the three
    shipped bands, so this is directly comparable to `under_18_share`. It is
    DELIBERATELY not written to the warehouse in this pass: a fourth age column
    on analysis.address_demographics is an ACS ingest decision (D60), not a
    side-effect of an age-fit run.
    """
    p = pathlib.Path(path) if path else (
        pathlib.Path(__file__).resolve().parents[3] / "data" / "raw" / "acs"
        / f"tracts_{acs_year}.json")
    if not p.exists():
        return None
    doc = json.loads(p.read_text())
    rows = []
    for geoid, rec in doc.get("tracts", {}).items():
        try:
            tot = float(rec["B01001_001E"])
            n5 = float(rec["B01001_003E"]) + float(rec["B01001_027E"])
        except (KeyError, TypeError, ValueError):
            continue
        if tot <= 0:
            continue
        rows.append((str(geoid), n5 / tot))
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["tract_geoid", "under_5_share"])


def estimate_curve(panel: TractPanel, addr: pd.DataFrame,
                   spec: CategorySpec = BAR_SPEC,
                   cutoff_m: float = CONLEY_CUTOFF_M) -> dict:
    """Fit `spec` and return the provenance record, PURE of IO.

    Three fits on the shipped outcome, all on the same design: the pooled MN+BK
    model that supplies the shipped coefficients, and one borough-internal model
    each for Brooklyn (the F2 gate -- the curve has to hold where it will be
    used, not merely where it is best identified) and Manhattan (reported for
    contrast; §6.1's finding that the two boroughs run on different mechanisms
    is the reason pooling alone is not enough). Any `robustness_outcomes` are
    fitted the same way and REPORTED, never shipped.
    """
    terms = list(spec.age_terms)
    extra = under_5_share(panel.acs_year) if "under_5" in spec.robustness_outcomes else None
    d = _design(panel.tracts, spec, extra=extra)
    if len(d) < 50:
        raise ValueError(f"estimation sample is {len(d)} tracts; refusing to fit a curve on it")

    from_nta, to_nta, ranked = resolve_contrast_ntas(addr, spec)
    mix_from = _nta_age_mix(addr, from_nta, terms)
    mix_to = _nta_age_mix(addr, to_nta, terms)

    main = _fit_one(d, spec, spec.outcome_col, terms, cutoff_m, mix_from, mix_to)
    coefs = [main["coefs"][t] for t in terms]
    cov_age = np.asarray(main["cov_age_conley"], float)

    # --- the anchor: unit-weighted MN+BK mix over the estimation sample ------
    dd = main["_design"]
    wts = dd["units_tract"].to_numpy(float)
    if wts.sum() <= 0:
        wts = np.ones(len(dd))
    anchors = [float(np.average(dd[t], weights=wts)) for t in terms]

    # --- the multiplier over the estimation tracts, and its dispersion gate --
    tr = panel.tracts
    dl = _deltas(tr, terms, anchors)
    fit_all = multiplier_terms(dl, coefs)
    moe_all = multiplier_moe_terms(
        fit_all, dl, coefs, cov_age, tr[_age_moe_columns(terms)].to_numpy(float))
    in_sample = tr["keep"].to_numpy()
    fs = pd.Series(fit_all[in_sample]).dropna()
    ms = pd.Series(moe_all[in_sample]).dropna()
    p10, p50, p90 = (float(fs.quantile(q)) for q in (0.10, 0.50, 0.90))
    median_moe = float(ms.median())
    spread = p90 - p10

    # --- robustness variants, reported and never shipped ---------------------
    robustness: dict[str, dict] = {}
    if "count" in spec.robustness_outcomes:
        count_col = f"{spec.category}_count_{spec.r}"
        robustness["count"] = _strip(_fit_one(
            d, spec, count_col, terms, cutoff_m, mix_from, mix_to))
        robustness["count"]["outcome_label"] = (
            f"log(1 + canonical {spec.category} POIs within {spec.r} m) "
            "-- COUNT, no denominator")
    if "adult_shares" in spec.robustness_outcomes:
        # Same outcome, same sample, same SEs -- only the age pair changes, to
        # bar's own adult-renormalized (w18, w65). This is the ONLY fit whose
        # b(w18) is on the same variable as the docs/bar_age_nyc.md §5c placebo
        # table, so it is the number that column may be compared against.
        adult = ("w18", "w65")
        robustness["adult_shares"] = _strip(_fit_one(
            d, spec, spec.outcome_col, adult, cutoff_m,
            _nta_age_mix(addr, from_nta, adult), _nta_age_mix(addr, to_nta, adult)))
        robustness["adult_shares"]["outcome_label"] = (
            spec.outcome_label.format(r=spec.r)
            + " -- SHIPPED outcome on bar's (w18, w65) age pair, for placebo "
              "comparability only")
    if "under_5" in spec.robustness_outcomes and extra is not None:
        robustness["under_5"] = _strip(_fit_one(
            d, spec, spec.outcome_col, terms, cutoff_m, mix_from, mix_to,
            extra_terms=("under_5_share",)))
        m_u5 = robustness["under_5"]
        m_u5["under_5_share"] = {
            "coef": float(m_u5["coefficients"]["under_5_share"]),
            "n_tracts_with_value": int(d["under_5_share"].notna().sum()),
        }
    elif "under_5" in spec.robustness_outcomes:
        robustness["under_5"] = {"skipped": "data/raw/acs/tracts_*.json not present"}

    fit = {
        "category": spec.category,
        "spec": spec.spec_version,
        "outcome": spec.outcome_label.format(r=spec.r),
        "formula": main["formula"],
        "radius_m": spec.radius_m,
        "se": f"Conley spatial-HAC, Bartlett kernel, {cutoff_m:.0f} m cutoff",
        "boroughs": sorted(dd["borough"].unique().tolist()),
        "n_tracts": main["n_tracts"],
        "n_tracts_all": len(tr),
        "r_squared": main["r_squared"],
        "age_terms": terms,
        "primary_age_term": spec.primary_age_term,
        "coefs": main["coefs"],
        "se_conley": main["se_conley"],
        "t_conley": main["t_conley"],
        "anchors": {t: a for t, a in zip(terms, anchors)},
        "cov_age_conley": main["cov_age_conley"],
        "contrast": {
            "kind": spec.contrast.kind,
            "variable": spec.contrast.variable,
            "require_sign": spec.contrast.require_sign,
            "min_addresses": spec.contrast.min_addresses,
            "from_nta": from_nta, "to_nta": to_nta,
            "from_name": _nta_name(addr, from_nta),
            "to_name": _nta_name(addr, to_nta),
            "from_mix": {t: v for t, v in zip(terms, mix_from)},
            "to_mix": {t: v for t, v in zip(terms, mix_to)},
            "pooled": main["contrast_pooled"],
        },
        "by_borough": main["by_borough"],
        "coefficients": main["coefficients"],
        "multiplier": {
            "p10": p10, "p50": p50, "p90": p90,
            "spread": spread,
            "median_moe": median_moe,
            "dispersion_ratio": (spread / median_moe) if median_moe > 0 else float("inf"),
            "min": float(fs.min()), "max": float(fs.max()),
        },
        "robustness": robustness,
        "inputs": {
            "acs_year": panel.acs_year,
            "supply_hash": panel.supply_hash,
            # informational only -- never hashed, never checked for staleness.
            # See TractPanel's docstring for why.
            "screen_supply_hash": panel.screen_supply_hash,
            "n_universe": panel.n_universe,
            "n_target": panel.n_target,
            "hash": inputs_hash(panel.supply_hash, panel.acs_year, panel.n_target),
        },
        "disclaimer": AGE_FIT_DISCLAIMER,
        "fitted_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    if spec.contrast.kind == "extreme" and len(ranked):
        fit["contrast"]["ranking_extremes"] = {
            "lowest": ranked.head(3).to_dict("records"),
            "highest": ranked.tail(3).to_dict("records"),
            "n_ntas": len(ranked),
        }
    # --- back-compat keys for a two-adult-share curve ------------------------
    # D63's `age_fit_bar.json` schema, kept so an older reader (and the D63
    # tests' synthetic FIT dicts) still work unchanged.
    if terms == ["w18", "w65"]:
        fit.update({
            "b18": main["coefs"]["w18"], "b65": main["coefs"]["w65"],
            "b18_se_conley": main["se_conley"]["w18"],
            "b65_se_conley": main["se_conley"]["w65"],
            "b18_t_conley": main["t_conley"]["w18"],
            "b65_t_conley": main["t_conley"]["w65"],
            "anchor_w18": anchors[0], "anchor_w65": anchors[1],
        })
        fit["inputs"]["n_bar_licences"] = panel.n_target
        fit["inputs"]["n_onprem_licences"] = panel.n_universe
        for b in fit["by_borough"].values():
            b["b18"], b["b65"] = b["coefs"]["w18"], b["coefs"]["w65"]
            b["b18_se_conley"] = b["se_conley"]["w18"]
            b["b65_se_conley"] = b["se_conley"]["w65"]
        fit["contrast"].update({
            "from_w18": mix_from[0], "from_w65": mix_from[1],
            "to_w18": mix_to[0], "to_w65": mix_to[1],
        })
    return fit


def _strip(one: dict) -> dict:
    """Drop the non-serializable working objects a `_fit_one` result carries."""
    return {k: v for k, v in one.items() if not k.startswith("_")}


def _nta_name(addr: pd.DataFrame, nta_code: str) -> str | None:
    sub = addr.loc[addr["nta_code"] == nta_code, "neighborhood"]
    return None if sub.empty else str(sub.iloc[0])


def inputs_hash(supply_hash: str | None, acs_year: int, n_target: int) -> str:
    """The identity of the inputs a curve was revealed from. A supply-revealed
    coefficient is only valid against the supply set it was revealed from
    (docs/bar_age_nyc.md §7.2 test 7), so this triple is stamped on the fit and
    re-checked by `apply_age_fit` before the multiplier touches a ranking.

    `n_target` is the count of the OUTCOME's own numerator -- bar-type SLA
    licences for `bar`, canonical childcare POIs for `childcare` -- so a change
    that moves one category's evidence invalidates only that category's curve."""
    key = f"{supply_hash}|{acs_year}|{n_target}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# --------------------------------------------------------------- the F2 gate

def failed_gates(fit: dict) -> list[str]:
    """Which of the published failure criteria this curve fails. Empty == ship.

    Pure, so a test can hand it a synthetic curve. Applied identically to EVERY
    category in the registry -- QUESTIONS D15 is explicit that a second source
    agreeing on a sign is corroboration, not a licence to relax the gate. Two
    criteria are enforced here because they are the two that decide whether the
    multiplier may be APPLIED at all:

      F2  the Brooklyn-only Conley CI on the category's low-age -> high-age
          contrast must EXCLUDE 1.0, and (where the spec demands a sign) the
          point estimate must carry it. This is the criterion the note names as
          binding: it is the only reason the composition spec is preferred over
          the bar-POI count spec, whose Brooklyn CI grazes 1.0 at [1.011,
          2.178]. Brooklyn, not the pooled sample, because 98.2% of the
          bar-lead gap set is in Brooklyn -- calibrating where the signal is and
          shipping where it isn't is the failure this test exists to catch.
      F3  the dispersion gate: p90 - p10 of the multiplier must exceed its own
          median MOE. The CEX predecessor failed this at 0.10 and that failure
          is what retired it; a successor that cannot clear its own noise floor
          is not an improvement.

    The remaining criteria (F1 non-filtering, F4 the high > low ordering with
    MOEs, F5 the placebo ordering, F6 the Jaccard band, F7 Conley-not-HC3) are
    pinned by tests/test_age_fit.py and by the note, not re-derived on every fit.
    """
    bad: list[str] = []
    bk = (fit.get("by_borough") or {}).get("BK")
    if not bk:
        bad.append("F2 (no Brooklyn-only fit -- the gate cannot be evaluated)")
    else:
        lo, hi = bk["contrast"]["ci_low"], bk["contrast"]["ci_high"]
        if lo <= 1.0 <= hi:
            bad.append(f"F2 (Brooklyn Conley CI [{lo:.3f}, {hi:.3f}] includes 1.0)")
        else:
            want = int((fit.get("contrast") or {}).get("require_sign", 0))
            ratio = bk["contrast"]["ratio"]
            if want > 0 and ratio < 1.0:
                bad.append(
                    f"F2 (Brooklyn contrast {ratio:.3f} is the WRONG SIGN: the "
                    "high-demand endpoint has LESS of the category, so the CI "
                    "excludes 1.0 by rejecting the hypothesis, not confirming it)")
            if want < 0 and ratio > 1.0:
                bad.append(f"F2 (Brooklyn contrast {ratio:.3f} is the wrong sign)")
    ratio = fit["multiplier"]["dispersion_ratio"]
    if not (ratio >= DISPERSION_GATE_MIN):
        bad.append(f"F3 (dispersion spread/MOE = {ratio:.2f} < {DISPERSION_GATE_MIN})")
    return bad


def write_fit_if_gates_pass(fit: dict, path: pathlib.Path = FIT_PATH) -> pathlib.Path:
    """Persist the curve -- and ONLY if it passes its own failure criterion.

    The order matters and is the point: gates first, write second. A curve that
    fails F2 or F3 leaves the previous fit JSON exactly as it was, so a failed
    re-fit degrades to "yesterday's curve, explicitly stale" rather than to
    "today's curve, quietly invalid"."""
    bad = failed_gates(fit)
    if bad:
        raise AgeFitGateFailure(
            f"age_fit_{fit.get('category', 'bar')} failed its own failure criterion "
            "(docs/bar_age_nyc.md §7.1): " + "; ".join(bad)
            + ". Nothing written; the multiplier must not be applied "
            "from a curve that fails its own criterion.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fit, indent=2, sort_keys=True, default=float) + "\n")
    return path


def load_fit(path: pathlib.Path | None = None, category: str | None = None) -> dict:
    """One curve's JSON. `category` resolves the path from the registry."""
    if path is None:
        path = spec_for(category).fit_path if category else FIT_PATH
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found -- run `loci age-fit fit"
            + (f" --category {category}" if category else "")
            + "` before `loci age-fit apply`")
    return json.loads(p.read_text())


def load_fits(categories=None, missing_ok: bool = False) -> dict[str, dict]:
    """{category: fit} for every requested category.

    A category NAMED explicitly and never fitted RAISES -- an apply that
    silently skipped the one category the caller asked for would look like a
    success. Under `missing_ok` (the `--category all` path) a category with no
    JSON is SKIPPED instead, which is the state a category sits in when its
    curve is defined in the registry but failed its own F2/F3 gate and was
    therefore never written. The caller must still reset that category's rows,
    so `apply_age_fit` scopes the reset by what was REQUESTED, not by what was
    found."""
    cats = list(categories) if categories is not None else list(FITTED_CATEGORIES)
    out: dict[str, dict] = {}
    for c in cats:
        try:
            out[c] = load_fit(category=c)
        except FileNotFoundError:
            if not missing_ok:
                raise
    return out


def fit_curve(con, category: str = "bar", boroughs: list[str] = FIT_BOROUGHS,
              acs_year: int = ACS_YEAR, cutoff_m: float = CONLEY_CUTOFF_M,
              dry_run: bool = False,
              path: pathlib.Path | None = None) -> tuple[dict, pathlib.Path | None]:
    """Re-estimate one category's curve from the warehouse. READ-ONLY on the
    database in both modes; under `--dry-run` it also writes no JSON. Returns
    (fit, path-written-or-None) and RAISES `AgeFitGateFailure` before writing
    anything if the curve fails F2 or F3."""
    spec = spec_for(category)
    boroughs = list(boroughs)
    addr = load_addresses(con, boroughs, acs_year)
    panel = build_tract_panel(con, spec, boroughs, acs_year, addresses=addr)
    fit = estimate_curve(panel, addr, spec, cutoff_m=cutoff_m)
    if dry_run:
        bad = failed_gates(fit)
        if bad:
            raise AgeFitGateFailure(
                f"age_fit_{spec.category} failed its own failure criterion "
                "(docs/bar_age_nyc.md §7.1): " + "; ".join(bad))
        return fit, None
    return fit, write_fit_if_gates_pass(fit, path or spec.fit_path)


def fit_bar_curve(con, boroughs: list[str] = FIT_BOROUGHS, acs_year: int = ACS_YEAR,
                  cutoff_m: float = CONLEY_CUTOFF_M, dry_run: bool = False,
                  path: pathlib.Path = FIT_PATH) -> tuple[dict, pathlib.Path | None]:
    """D63's entry point, kept as a thin alias so an older caller does not
    break. New code calls `fit_curve(con, category=...)`."""
    return fit_curve(con, "bar", boroughs, acs_year, cutoff_m, dry_run, path)


# Back-compat alias: D63 named the estimator after its only category.
estimate_bar_curve = estimate_curve


# ------------------------------------------------------------- the apply side

def _fit_age_block(fit: dict) -> tuple[list[str], list[float], list[float], np.ndarray]:
    """(terms, coefs, anchors, cov_age) from a fit JSON, tolerant of D63's
    bar-only schema so an old file and the tests' synthetic curves still load."""
    cov = np.asarray(fit["cov_age_conley"], float)
    if "age_terms" in fit:
        terms = list(fit["age_terms"])
        return terms, [float(fit["coefs"][t]) for t in terms], \
            [float(fit["anchors"][t]) for t in terms], cov
    return (["w18", "w65"], [float(fit["b18"]), float(fit["b65"])],
            [float(fit["anchor_w18"]), float(fit["anchor_w65"])], cov)


def fit_category(fit: dict) -> str:
    """Which category a fit JSON belongs to. D63's file predates the field, and
    its only category was `bar`."""
    return str(fit.get("category", "bar"))


def compute_age_fit(con, boroughs: list[str], fits: dict[str, dict] | dict,
                    acs_year: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(category-grain frame, address-grain frame). READ-ONLY.

    The category frame carries one row per (address, fitted category) with THAT
    category's multiplier and MOE; the address frame carries `age_fit_lead`,
    `age_fit_lead_moe` and `gap_score_fit` for every in-scope address.

    `fits` is {category: fit}. A single fit dict is accepted too and is treated
    as that fit's own category (D63 compatibility).

    `age_fit_lead` is 1.0 -- the identity multiplier, so `gap_score_fit ==
    gap_score` exactly -- whenever the address's lead category has no fitted
    curve, or has one but no ACS age mix to evaluate it at. Its MOE is NULL
    there, not 0.0: "no curve" is not "a curve with no uncertainty".
    """
    if "cov_age_conley" in fits:                     # a single fit dict
        fits = {fit_category(fits): fits}
    years = {f["inputs"]["acs_year"] for f in fits.values()}
    if acs_year is None:
        if len(years) > 1:
            raise ValueError(f"curves disagree on the ACS vintage: {sorted(years)}")
        # No curves at all is a legitimate state -- every category's `age_fit`
        # is NULL and every `age_fit_lead` is 1.0 -- so it must produce frames,
        # not an exception, or the reset pass never runs.
        acs_year = years.pop() if years else ACS_YEAR
    addr = load_addresses(con, list(boroughs), acs_year)

    per_cat: dict[str, pd.DataFrame] = {}
    for cat, fit in fits.items():
        terms, coefs, anchors, cov_age = _fit_age_block(fit)
        moe_cols = _age_moe_columns(terms)
        dl = _deltas(addr, terms, anchors)
        value = multiplier_terms(dl, coefs)
        moe = multiplier_moe_terms(value, dl, coefs, cov_age,
                                   addr[moe_cols].to_numpy(float))
        # A tract with no published age share (or no MOE) gets no multiplier at
        # all. Failing closed to NULL is the only honest option: a silent 1.0
        # would be indistinguishable from "fitted, and neutral".
        ok = np.ones(len(addr), bool)
        for c in [*terms, *moe_cols]:
            ok &= addr[c].notna().to_numpy()
        part = pd.DataFrame({
            "address_id": addr["address_id"].to_numpy(),
            "borough": addr["borough"].to_numpy(),
            "category": cat,
            "age_fit": np.where(ok, value, np.nan),
            "age_fit_moe": np.where(ok, moe, np.nan),
            # The SPEC that produced the number, taken from the fit rather than
            # from the module constant: a row must say which curve it came from,
            # not which curve the code currently ships.
            "age_fit_source": fit.get("spec", SPEC_VERSION),
        })
        per_cat[cat] = part

    cat_df = (pd.concat([p[p["age_fit"].notna()] for p in per_cat.values()],
                        ignore_index=True) if per_cat
              else pd.DataFrame(columns=["address_id", "borough", "category",
                                         *AGE_FIT_COLUMNS]))
    cat_df = cat_df[["address_id", "borough", "category", *AGE_FIT_COLUMNS]]

    # --- the lead multiplier: whichever curve matches THIS address's lead ----
    lead = addr["lead_category"].to_numpy()
    lead_fit = np.full(len(addr), np.nan)
    lead_moe = np.full(len(addr), np.nan)
    for cat, part in per_cat.items():
        m = (lead == cat) & part["age_fit"].notna().to_numpy()
        lead_fit[m] = part["age_fit"].to_numpy()[m]
        lead_moe[m] = part["age_fit_moe"].to_numpy()[m]
    has_lead = addr["lead_category"].notna().to_numpy()
    lead_fit = np.where(has_lead & np.isnan(lead_fit), 1.0, lead_fit)

    addr_df = pd.DataFrame({
        "address_id": addr["address_id"],
        "borough": addr["borough"],
        "age_fit_lead": lead_fit,
        "age_fit_lead_moe": lead_moe,
    })
    addr_df["gap_score_fit"] = addr["gap_score"].to_numpy() * addr_df["age_fit_lead"]
    return cat_df, addr_df[["address_id", "borough", *ADDRESS_AGE_FIT_COLUMNS]]


def _assert_disjoint() -> None:
    """The D57/D61 mechanical guarantee, checked before every write rather than
    only in a test: neither SET list may name a column the screen owns."""
    for cols, owned, table in (
        (AGE_FIT_COLUMNS, ADDRESS_CATEGORY_SCREEN_COLUMNS, "analysis.address_category"),
        (ADDRESS_AGE_FIT_COLUMNS, ADDRESS_COLUMNS, "analysis.address"),
    ):
        overlap = sorted(set(cols) & set(owned))
        if overlap:
            raise RuntimeError(f"age_fit would clobber screen columns on {table}: {overlap}")


def write_age_fit(con, cat_df: pd.DataFrame, addr_df: pd.DataFrame,
                  boroughs: list[str],
                  categories: list[str] | None = None) -> tuple[int, int]:
    """UPDATE-only annotation of both tables. Never INSERT, never DELETE, and
    the two SET lists are built exclusively from AGE_FIT_COLUMNS and
    ADDRESS_AGE_FIT_COLUMNS.

    RESET-then-UPDATE on both, for the same reason address_demand.py does it: a
    row that carried a multiplier on the last run and falls out of scope on this
    one (a category that stopped being fitted, a tract that lost its ACS age
    mix) would otherwise keep last run's number forever, because UPDATE has no
    DELETE to fall back on. `boroughs` is passed explicitly rather than inferred
    from the frames so an empty-frame run still clears.

    `categories` SCOPES the reset. Applying the whole fitted set (the default)
    resets every row, which is what retires a category dropped from the
    registry. Applying a SUBSET resets only that subset's category rows and only
    the addresses whose lead is in it -- otherwise `apply --category bar` would
    silently blank childcare's multipliers and reset those addresses' lead to
    NULL, which reads on the map as "no curve" rather than "not re-run".
    """
    if not boroughs:
        return 0, 0
    _assert_disjoint()
    holes = ", ".join("?" for _ in boroughs)
    partial = categories is not None and set(categories) != set(FITTED_CATEGORIES)
    cat_nulls = ", ".join(f"{c} = NULL" for c in AGE_FIT_COLUMNS)
    addr_nulls = ", ".join(f"{c} = NULL" for c in ADDRESS_AGE_FIT_COLUMNS)
    if partial:
        cats = list(categories)
        choles = ", ".join("?" for _ in cats)
        con.execute(
            f"UPDATE analysis.address_category SET {cat_nulls} "
            f"WHERE borough IN ({holes}) AND category IN ({choles})",
            [*boroughs, *cats])
        con.execute(
            f"UPDATE analysis.address SET {addr_nulls} "
            f"WHERE borough IN ({holes}) AND lead_category IN ({choles})",
            [*boroughs, *cats])
    else:
        con.execute(f"UPDATE analysis.address_category SET {cat_nulls} "
                    f"WHERE borough IN ({holes})", list(boroughs))
        con.execute(f"UPDATE analysis.address SET {addr_nulls} "
                    f"WHERE borough IN ({holes})", list(boroughs))

    n_cat = 0
    if not cat_df.empty:
        con.register("_af_cat", cat_df)
        try:
            sets = ", ".join(f"{c} = _af_cat.{c}" for c in AGE_FIT_COLUMNS)
            con.execute(f"""
                UPDATE analysis.address_category AS ac
                SET {sets}
                FROM _af_cat
                WHERE ac.address_id = _af_cat.address_id
                  AND ac.borough = _af_cat.borough
                  AND ac.category = _af_cat.category
            """)
        finally:
            con.unregister("_af_cat")
        n_cat = len(cat_df)

    n_addr = 0
    if not addr_df.empty:
        con.register("_af_addr", addr_df)
        try:
            sets = ", ".join(f"{c} = _af_addr.{c}" for c in ADDRESS_AGE_FIT_COLUMNS)
            con.execute(f"""
                UPDATE analysis.address AS a
                SET {sets}
                FROM _af_addr
                WHERE a.address_id = _af_addr.address_id
                  AND a.borough = _af_addr.borough
            """)
        finally:
            con.unregister("_af_addr")
        n_addr = len(addr_df)
    return n_cat, n_addr


def live_target_count(con, spec: CategorySpec,
                      boroughs: list[str] = FIT_BOROUGHS) -> int:
    """The count of the OUTCOME's own numerator as the database now holds it --
    the third leg of the staleness hash."""
    if spec.overlay == "sla":
        return int(con.execute(f"""
            SELECT count(*) FROM staging.alcohol_licences
            WHERE active AND borough IN ({', '.join("?" for _ in boroughs)})
              AND classification = 'on_premises'
              AND lower(trim(description)) IN ({', '.join("?" for _ in BAR_DESCRIPTIONS)})
        """, [*boroughs, *sorted(BAR_DESCRIPTIONS)]).fetchone()[0])
    pred = supply_predicate(DEFAULT_SUPPLY_SET)
    return int(con.execute(
        f"SELECT count(*) FROM analysis.poi_supply s "
        f"WHERE s.{pred} AND s.geom IS NOT NULL AND s.category = ?",
        [spec.category]).fetchone()[0])


def check_fit_is_current(con, fit: dict) -> None:
    """Refuse a curve fitted against a different supply set / ACS vintage /
    outcome count than the database now holds (docs/bar_age_nyc.md §7.2 test 7).
    The supply set moved twice in one month (D52/D59); multiplying today's gap
    set by a curve revealed from a different one is exactly the silent error
    this check exists to make loud. Per CATEGORY, so re-ingesting one feed
    invalidates only the curve that reads it.

    Compares against the LIVE `score.supply.supply_hash(con)`, the same
    function `build_tract_panel` stamps at fit time -- never against
    `analysis.address.supply_hash`, which is only the last `loci
    address-gaps` run's stamp and can move (or not) for reasons unrelated to
    this category's actual supply. Using it here would raise a false
    AgeFitStale whenever address-gaps re-runs without this category's supply
    changing at all."""
    spec = spec_for(fit_category(fit))
    live_supply = live_supply_hash(con)
    n_target = live_target_count(con, spec)
    live = inputs_hash(live_supply, fit["inputs"]["acs_year"], n_target)
    if live != fit["inputs"]["hash"]:
        was = fit["inputs"].get("n_target", fit["inputs"].get("n_bar_licences"))
        raise AgeFitStale(
            f"age_fit_{spec.category}.json was fitted from inputs "
            f"{fit['inputs']['hash']} (supply {fit['inputs']['supply_hash']}, "
            f"{was:,} outcome records) but the database now holds {live} "
            f"(supply {live_supply}, {n_target:,}). "
            f"Re-run `loci age-fit fit --category {spec.category}`.")


def apply_age_fit(con, boroughs: list[str] = FIT_BOROUGHS,
                  fit: dict | None = None, fits: dict[str, dict] | None = None,
                  path: pathlib.Path | None = None, dry_run: bool = False,
                  check_current: bool = True,
                  categories: list[str] | None = None
                  ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """compute + write. A no-op on the database under `--dry-run`: the frames
    are computed and returned, and nothing is written.

    `fits` is the multi-category form ({category: fit}); `fit` is D63's single
    curve and is still accepted. `categories` is the RESET SCOPE -- what the
    caller asked to (re)compute, which can be wider than what was found: a
    category whose curve failed its gate has no JSON, and its rows must be
    cleared to NULL rather than keeping a previous run's multiplier."""
    if fits is None:
        if fit is not None:
            fits = {fit_category(fit): fit}
        elif path is not None:
            one = load_fit(path)
            fits = {fit_category(one): one}
        else:
            fits = load_fits(categories, missing_ok=categories is None)
    if check_current:
        for f in fits.values():
            check_fit_is_current(con, f)
    boroughs = list(boroughs)
    reset_scope = list(categories) if categories is not None else list(fits)
    cat_df, addr_df = compute_age_fit(con, boroughs, fits)
    report = summarize(cat_df, addr_df, fits)
    report["reset_categories"] = reset_scope
    report["missing_curves"] = sorted(set(reset_scope) - set(fits))
    if not dry_run:
        n_cat, n_addr = write_age_fit(con, cat_df, addr_df, boroughs,
                                      categories=reset_scope)
        report["written_category_rows"] = n_cat
        report["written_address_rows"] = n_addr
    return cat_df, addr_df, report


# ---------------------------------------------------------------- reporting

def summarize(cat_df: pd.DataFrame, addr_df: pd.DataFrame,
              fits: dict[str, dict] | dict) -> dict:
    """Pure, DB-free summary shared by --dry-run and the post-write report."""
    if "cov_age_conley" in fits:
        fits = {fit_category(fits): fits}
    fitted = cat_df["age_fit"].dropna() if len(cat_df) else pd.Series(dtype=float)
    lead = addr_df["age_fit_lead"].dropna() if len(addr_df) else pd.Series(dtype=float)
    per_category = {}
    for cat, f in sorted(fits.items()):
        sub = (cat_df.loc[cat_df["category"] == cat, "age_fit"].dropna()
               if len(cat_df) else pd.Series(dtype=float))
        terms, coefs, _, _ = _fit_age_block(f)
        per_category[cat] = {
            "spec": f.get("spec"),
            "n_rows": len(sub),
            "coefs": dict(zip(terms, coefs)),
            "primary_age_term": f.get("primary_age_term", terms[0]),
            "p10": float(sub.quantile(0.10)) if len(sub) else None,
            "p50": float(sub.quantile(0.50)) if len(sub) else None,
            "p90": float(sub.quantile(0.90)) if len(sub) else None,
        }
    one = next(iter(sorted(fits.items())))[1] if fits else {}
    return {
        "spec": one.get("spec"),
        "categories": sorted(fits),
        "per_category": per_category,
        # D63 keys, kept so the CLI's bar-only reporting path still reads.
        "b18": one.get("b18"), "b65": one.get("b65"),
        "n_category_rows": len(cat_df),
        "n_addresses": len(addr_df),
        "n_lead_multiplied": int((lead != 1.0).sum()),
        "fitted_p10": float(fitted.quantile(0.10)) if len(fitted) else None,
        "fitted_p50": float(fitted.quantile(0.50)) if len(fitted) else None,
        "fitted_p90": float(fitted.quantile(0.90)) if len(fitted) else None,
        "fitted_min": float(fitted.min()) if len(fitted) else None,
        "fitted_max": float(fitted.max()) if len(fitted) else None,
        "moe_median": float(cat_df["age_fit_moe"].median()) if len(cat_df) else None,
        "n_missing_moe": int(cat_df["age_fit"].notna().sum()
                             - cat_df["age_fit_moe"].notna().sum()) if len(cat_df) else 0,
    }
