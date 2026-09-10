"""`age_fit_bar`: a SUPPLY-REVEALED age multiplier for the `bar` category,
estimated from New York's own licensed-venue composition (D63).

WHAT THIS IS
--------------------------------------------------------------------------
The owner's request (2026-09-10): *"a bar gap in the Upper East Side where avg
age is 60+ vs a bar gap in the East Village where avg age is 25 -- the East
Village bar should score higher."*  This module answers it with a curve fitted
to New York, not with a national budget survey.

`docs/age_demand_fit.md` tried the survey route (BLS CEX) and it failed on its
own terms: the CEX alcohol line peaks at reference-person age 45-54 -- the
household budget shape, not the drinker's -- averages over non-drinkers, is
under-reported, and publishes no age-by-metro cell, so the multiplier it
produced had a p10-p90 spread of 0.013 against a median MOE of 0.140 and would
have scored the UES ABOVE the East Village. `docs/bar_age_nyc.md` replaces it
with a market-revealed relationship measured on this warehouse's own data, and
recommends exactly ONE specification of the several it tested.

THE SPECIFICATION (`sla_composition_v1`, docs/bar_age_nyc.md §7)
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

Regressors: `w18` and `w65` (ADULT shares, renormalized by 1 - under_18_share,
so the omitted band is 35-64 and each coefficient reads relative to a 35-64
adult), log units within 400 m, log(1 + CNS07 retail jobs within 400 m),
log walk_m_to_subway, log median household income, renter share, and a
Manhattan fixed effect.  Standard errors are CONLEY spatial-HAC (Bartlett,
2 km): the residuals have Moran's I ~= 0.42 on KNN(8) weights -- adjacent tract
centroids are often < 400 m apart so their outcome discs physically overlap --
and HC3 is therefore unusable. Every interval this module reports is the Conley
one. Read them as optimistic: a spatial-error model would shrink the
coefficient itself, not merely widen the band.

THE MULTIPLIER
--------------------------------------------------------------------------
    age_fit_bar(tract) = exp[ b18*(w18 - w18_anchor) + b65*(w65 - w65_anchor) ]

which is "predicted bar composition at this tract's age mix / predicted at the
MN+BK average age mix, every control at its own value" -- the controls cancel
because they are identical in numerator and denominator. The anchor is the
unit-weighted MN+BK adult mix over the estimation sample.

`age_fit_moe` is a 90% MOE by the DELTA METHOD through exp(.): the linear
predictor's variance is the quadratic form of the two age deltas against the
Conley coefficient covariance, PLUS the two ACS share MOEs converted to SEs at
1.645 and added in quadrature; that variance is scaled by exp(.)^2 and
re-inflated to 90% at 1.645. The renormalizing denominator (1 - under_18_share)
is treated as fixed -- a second-order term, stated rather than hidden.

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
The note ships this column only while its failure criteria hold, and names F2
as the one that binds -- it is the ONLY reason the composition spec is preferred
over the bar-POI count spec, and the test a re-run on a new supply set or ACS
vintage is most likely to fail. So `fit_bar_curve` refuses to WRITE anything at
all unless:

  F2  the BROOKLYN-ONLY Conley CI on the Carnegie-Hill -> East-Village contrast
      excludes 1.0; and
  F3  the dispersion gate passes: (p90 - p10 of the multiplier over the
      estimation tracts) / median(age_fit_moe) >= 1.0 -- the same derived gate
      `docs/age_demand_fit.md` §5 defined and the CEX multiplier failed at 0.10.

A curve that fails its own criterion must not reach the ranking, so the command
exits non-zero and leaves the previous `age_fit_bar.json` untouched rather than
half-writing a fit nobody may apply.

WHAT THE COLUMN MAY NOT BE READ AS (AGE_FIT_DISCLAIMER)
--------------------------------------------------------------------------
Three sentences, and all three are load-bearing. (i) SUPPLY-REVEALED: every
coefficient is fitted on where bars ALREADY are, so it mixes demand with
residential sorting (young renters move to neighbourhoods that already have
bars at least as hard as bars open where young renters already live) and there
is no instrument here that separates them. (ii) A low value is NEVER evidence
that a neighbourhood does not deserve the service -- the D49/QUESTIONS-X6
hazard, in a new costume. (iii) Resident age is a PROXY FOR A BUNDLE -- young,
renter, transit-rich, commercially active. Spatial-block CV says age adds
+3.2-3.6% out-of-sample over a density-only model in Brooklyn but ~0% once
income, renter share, walk-to-subway and retail jobs are already in, and it
transfers NEGATIVELY from Brooklyn to Manhattan. It carries real information
relative to what `gap_score` knows and almost none that is uniquely age.

Render the disclaimer untruncated, exactly as `demand_caveat_text` (D49/D57).

SCOPE
--------------------------------------------------------------------------
`bar` only. The placebo (docs/bar_age_nyc.md §5c) ran this identical
specification with all fifteen categories as the outcome: `bar` has the largest
positive b(w18) of the fifteen and `pharmacy` the most negative, which is what
rules out "b(w18) is a generic urbanity coefficient". Extending the curve to
other categories is a separate decision with its own gate, not a loop over
ALLCATS -- so FITTED_CATEGORIES is a tuple of one and every other category's
`age_fit` is NULL, not 1.0. NULL means "no curve exists here"; 1.0 would mean
"a curve exists and says neutral", and the two must not be confused.
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
from loci.sources.cities.nyc.nys_sla import BAR_DESCRIPTIONS

#: Identifier written into `age_fit_source` on every fitted row, so a reader can
#: tell WHICH curve produced the number without opening the JSON. Bump it when
#: the specification changes -- not when the coefficients are merely re-fitted.
SPEC_VERSION = "sla_composition_v1"

#: The ONLY categories a curve exists for (docs/bar_age_nyc.md §7). See the
#: module docstring: every other category gets NULL, never 1.0.
FITTED_CATEGORIES = ("bar",)

#: D48 scope, and the sample the curve is estimated on. A coefficient fitted in
#: Manhattan+Brooklyn transfers NEGATIVELY to the other direction across the
#: East River (§6), so the multiplier is applied only where it was estimated.
FIT_BOROUGHS = ("MN", "BK")

ACS_YEAR = 2023            # matches model/address_demographics.py's pinned vintage
DISC_M = 400.0             # the bar reach tier; ~493 m of walking at D53's 1.233 circuity
CONLEY_CUTOFF_M = 2000.0   # Bartlett kernel cutoff; the more conservative of 1 km / 2 km
MIN_POPULATION = 100.0     # tracts below this are institutional/very-low-response noise
MIN_WALK_M = 25.0          # floor before log(walk_m_to_subway); a 0 m walk is a 0 m fiction
CI_Z = 1.96                # 95% CI on the CH -> EV contrast (the F2 gate reads this)
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

#: The two NTAs of the owner's example, resolved by NTA CODE rather than name so
#: a DCP label change cannot silently retarget the F2 gate.
CONTRAST_NTAS = {"from": "MN0802", "to": "MN0303"}   # UES-Carnegie Hill -> East Village

FIT_PATH = INTERIM_DIR / "age_fit_bar.json"

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
    "bar-type licences relative to resident age -- demand and residential "
    "sorting together, not separated. A low value is never evidence that a "
    "neighbourhood does not want the service. Resident age here is a proxy for "
    "a bundle (young, renter, transit-rich, commercially active) and adds "
    "essentially nothing once those are measured directly, so it must not be "
    "read as an isolated age effect."
)


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


# ------------------------------------------------------------ the tract panel

@dataclasses.dataclass(frozen=True)
class TractPanel:
    """The estimation frame plus everything downstream needs from it.

    `tracts` is one row per tract with `keep` marking the regression sample;
    `n_licences` and `supply_hash` are carried so the fit can stamp exactly
    which inputs produced it."""
    tracts: pd.DataFrame
    n_licences: int
    n_bar_licences: int
    supply_hash: str | None
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
               d.under_18_share, d.age_18_34_share, d.age_65_plus_share,
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
    adult = 1.0 - df["under_18_share"]
    with np.errstate(divide="ignore", invalid="ignore"):
        df["w18"] = df["age_18_34_share"] / adult
        df["w65"] = df["age_65_plus_share"] / adult
        df["w18_moe"] = df["age_18_34_share_moe"] / adult
        df["w65_moe"] = df["age_65_plus_share_moe"] / adult
    return df


def build_tract_panel(con, boroughs: list[str] = FIT_BOROUGHS,
                      acs_year: int = ACS_YEAR,
                      addresses: pd.DataFrame | None = None) -> TractPanel:
    """Aggregate addresses to tracts, hang the 400 m disc measures off each
    tract's RESIDENTIAL centroid, and mark the regression sample. READ-ONLY:
    this function issues four SELECTs and no write of any kind.

    `addresses` is injectable so tests can drive the whole estimator off a
    synthetic frame without a warehouse.
    """
    boroughs = list(boroughs)
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
    for c in ("borough", "population", "median_hh_income", "renter_share",
              "under_18_share", "w18", "w65", "w18_moe", "w65_moe"):
        tr[c] = first[c]
    tr["units_tract"] = g["units_capped"].sum()
    tr["n_addr"] = g.size()
    tr = tr.reset_index()
    centres = tr[["x", "y"]].to_numpy()

    # --- the licence overlay -------------------------------------------------
    holes = ", ".join("?" for _ in boroughs)
    lic = con.execute(f"""
        SELECT lower(trim(description)) AS description,
               ST_X(geom) AS lon, ST_Y(geom) AS lat
        FROM staging.alcohol_licences
        WHERE active AND borough IN ({holes})
          AND classification = 'on_premises' AND geom IS NOT NULL
    """, boroughs).fetchdf()
    # The bar vocabulary is nys_sla.BAR_DESCRIPTIONS -- the SAME set that decides
    # what enters staging.poi as a `bar` -- imported rather than copied, so the
    # overlay and the category can never drift apart. (There is no `Tavern`
    # licence type in the NYC feed; `Additional Bar` is a RIDER on an existing
    # premises, not a venue, and is deliberately not bar-type.)
    lic_xy = _to_utm(lic["lon"], lic["lat"]) if len(lic) else np.zeros((0, 2))
    is_bar = lic["description"].isin(BAR_DESCRIPTIONS).to_numpy() if len(lic) else np.zeros(0, bool)
    tr["onprem_400"] = _disc_sums(centres, lic_xy, DISC_M)
    tr["barlike_400"] = _disc_sums(centres, lic_xy[is_bar], DISC_M)

    # --- exposure: units inside the SAME disc, not the tract's own count -----
    # A tract's units and a 400 m disc around its centroid are different
    # geographies; using the tract count as the denominator for a disc count
    # would be a units mismatch.
    tr["units_400"] = _disc_sums(centres, addr[["x", "y"]].to_numpy(), DISC_M,
                                 addr["units_capped"].to_numpy())

    # --- daytime control: CNS07 retail jobs ----------------------------------
    jobs = con.execute(f"""
        SELECT p.jobs, ST_X(h.centroid) AS lon, ST_Y(h.centroid) AS lat
        FROM analysis.hex_panel p JOIN analysis.hex h USING (h3_index)
        WHERE p.naics = '{RETAIL_NAICS}'
          AND p.year = (SELECT max(year) FROM analysis.hex_panel)
    """).fetchdf()
    tr["retail_jobs_400"] = _disc_sums(
        centres, _to_utm(jobs["lon"], jobs["lat"]) if len(jobs) else np.zeros((0, 2)),
        DISC_M, jobs["jobs"].to_numpy() if len(jobs) else None)

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
    # REGRESSION but keep their multiplier, which needs only the two age shares.
    tr["keep"] = (
        (tr["population"] >= MIN_POPULATION)
        & tr["median_hh_income"].notna() & (tr["median_hh_income"] > 0)
        & tr["renter_share"].notna() & tr["w18"].notna() & tr["w65"].notna()
        & tr["walk_m_to_subway"].notna() & (tr["units_400"] > 0)
    )
    supply_hash = con.execute(
        "SELECT DISTINCT supply_hash FROM analysis.address WHERE supply_hash IS NOT NULL"
    ).fetchall()
    return TractPanel(
        tracts=tr,
        n_licences=len(lic),
        n_bar_licences=int(is_bar.sum()),
        supply_hash=supply_hash[0][0] if len(supply_hash) == 1 else None,
        acs_year=acs_year,
    )


# ---------------------------------------------------------------- estimation

def _design(tr: pd.DataFrame) -> pd.DataFrame:
    """The regression frame: the estimation sample with every transform the
    formula names already materialized, so the formula string below is a
    literal reading of docs/bar_age_nyc.md §3 rather than a nest of calls."""
    d = tr[tr["keep"]].copy()
    d["bar_share_400"] = np.log1p(d["barlike_400"]) - np.log1p(d["onprem_400"])
    d["lunits_400"] = np.log(d["units_400"])
    d["lretail_400"] = np.log1p(d["retail_jobs_400"])
    d["lwalk"] = np.log(d["walk_m_to_subway"].clip(lower=MIN_WALK_M))
    d["linc"] = np.log(d["median_hh_income"])
    d["MN"] = (d["borough"] == "MN").astype(float)
    return d


#: The composition specification, written once. `MN` is dropped for a
#: borough-internal fit (a constant fixed effect is not identified).
_RHS = "w18 + w65 + lunits_400 + lwalk + linc + renter_share + lretail_400"
FORMULA = f"bar_share_400 ~ {_RHS} + MN"
FORMULA_ONE_BOROUGH = f"bar_share_400 ~ {_RHS}"


def _conley_cov(model, xy: np.ndarray, cutoff_m: float = CONLEY_CUTOFF_M) -> np.ndarray:
    """Conley spatial-HAC covariance, Bartlett kernel, `cutoff_m` bandwidth.

    Standard sandwich with a distance-decayed meat: K_ij = max(0, 1 - d_ij/h).
    The finite-sample correction n/(n-k) matches statsmodels' HC0->HC1 step so
    the two are comparable. Needed because the residuals here have Moran's I
    ~= 0.42 -- neighbouring tracts share the same nightlife district and their
    400 m discs physically overlap, so the effective n is far below the row
    count and HC3 would be badly optimistic.
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


def _contrast(params: pd.Series, cov: np.ndarray, dw18: float, dw65: float) -> dict:
    """The Carnegie-Hill -> East-Village partial effect: the ratio of predicted
    composition at the two age mixes with EVERY control held fixed, plus its
    Conley CI. A linear contrast in the log-composition, exponentiated."""
    names = list(params.index)
    g = np.zeros(len(names))
    g[names.index("w18")] = dw18
    g[names.index("w65")] = dw65
    delta = float(g @ params.to_numpy())
    se = float(np.sqrt(g @ cov @ g))
    return {
        "ratio": float(np.exp(delta)),
        "ci_low": float(np.exp(delta - CI_Z * se)),
        "ci_high": float(np.exp(delta + CI_Z * se)),
        "se_log": se,
    }


def _nta_age_mix(addr: pd.DataFrame, nta_code: str) -> tuple[float, float]:
    """(w18, w65) for one NTA: the MEDIAN over its addresses, matching
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
    return float(sub["w18"].median()), float(sub["w65"].median())


def multiplier(w18, w65, b18: float, b65: float,
               anchor_w18: float, anchor_w65: float) -> np.ndarray:
    """age_fit_bar. Vectorized, and the ONLY place the formula is written.

    exp(.) of a linear form in the two age deltas: strictly positive for any
    finite input, which is what makes `gap_score * age_fit` non-filtering by
    construction rather than by assertion."""
    return np.exp(b18 * (np.asarray(w18, float) - anchor_w18)
                  + b65 * (np.asarray(w65, float) - anchor_w65))


def multiplier_moe(fit_value, w18, w65, b18: float, b65: float,
                   anchor_w18: float, anchor_w65: float,
                   cov_age: np.ndarray, w18_moe, w65_moe) -> np.ndarray:
    """90% MOE on `multiplier`, by the DELTA METHOD through exp(.).

    Var(log age_fit) has two independent parts, added in quadrature:
      * COEFFICIENT uncertainty -- the quadratic form of the two age deltas
        against `cov_age`, the 2x2 (w18, w65) block of the CONLEY covariance
        (never HC3; see the module docstring);
      * ACS SAMPLING uncertainty -- each published 90% share MOE converted to an
        SE at 1.645 and scaled by its own coefficient.
    Var(age_fit) ~= age_fit^2 * Var(log age_fit); the result is re-inflated to a
    90% MOE at 1.645 so it is directly comparable to the ACS MOEs it is built
    from. The renormalizing denominator (1 - under_18_share) is treated as
    fixed: second order, and stated rather than hidden."""
    a = np.asarray(w18, float) - anchor_w18
    b = np.asarray(w65, float) - anchor_w65
    var_coef = (a ** 2 * cov_age[0, 0] + b ** 2 * cov_age[1, 1]
                + 2.0 * a * b * cov_age[0, 1])
    var_acs = ((b18 * np.asarray(w18_moe, float) / MOE_Z) ** 2
               + (b65 * np.asarray(w65_moe, float) / MOE_Z) ** 2)
    return MOE_Z * np.asarray(fit_value, float) * np.sqrt(var_coef + var_acs)


def estimate_bar_curve(panel: TractPanel, addr: pd.DataFrame,
                       cutoff_m: float = CONLEY_CUTOFF_M) -> dict:
    """Fit `sla_composition_v1` and return the provenance record, PURE of IO.

    Three fits, all on the same design: the pooled MN+BK model that supplies the
    shipped coefficients, and one borough-internal model each for Brooklyn (the
    F2 gate -- 98% of the bar-lead gap set lives there, so the curve has to hold
    where it will be used, not merely where it is best identified) and Manhattan
    (reported for contrast; §6.1's finding that the two boroughs run on
    different mechanisms is the reason pooling alone is not enough).
    """
    import statsmodels.formula.api as smf

    d = _design(panel.tracts)
    if len(d) < 50:
        raise ValueError(f"estimation sample is {len(d)} tracts; refusing to fit a curve on it")
    xy = d[["x", "y"]].to_numpy()

    model = smf.ols(FORMULA, data=d).fit()
    cov = _conley_cov(model, xy, cutoff_m)
    names = list(model.params.index)
    i18, i65 = names.index("w18"), names.index("w65")
    cov_age = np.array([[cov[i18, i18], cov[i18, i65]],
                        [cov[i65, i18], cov[i65, i65]]])
    b18 = float(model.params["w18"])
    b65 = float(model.params["w65"])

    # --- the anchor: unit-weighted MN+BK adult mix over the estimation sample
    wts = d["units_tract"].to_numpy(float)
    if wts.sum() <= 0:
        wts = np.ones(len(d))
    anchor_w18 = float(np.average(d["w18"], weights=wts))
    anchor_w65 = float(np.average(d["w65"], weights=wts))

    # --- the owner's contrast, derived from the data, not pinned -------------
    ch18, ch65 = _nta_age_mix(addr, CONTRAST_NTAS["from"])
    ev18, ev65 = _nta_age_mix(addr, CONTRAST_NTAS["to"])
    dw18, dw65 = ev18 - ch18, ev65 - ch65
    pooled_contrast = _contrast(model.params, cov, dw18, dw65)

    by_borough: dict[str, dict] = {}
    for boro in sorted(d["borough"].unique()):
        sub = d[d["borough"] == boro]
        if len(sub) < 50:
            continue
        m_b = smf.ols(FORMULA_ONE_BOROUGH, data=sub).fit()
        cov_b = _conley_cov(m_b, sub[["x", "y"]].to_numpy(), cutoff_m)
        nb = list(m_b.params.index)
        j18, j65 = nb.index("w18"), nb.index("w65")
        by_borough[boro] = {
            "n_tracts": int(m_b.nobs),
            "b18": float(m_b.params["w18"]),
            "b18_se_conley": float(np.sqrt(cov_b[j18, j18])),
            "b65": float(m_b.params["w65"]),
            "b65_se_conley": float(np.sqrt(cov_b[j65, j65])),
            "contrast": _contrast(m_b.params, cov_b, dw18, dw65),
        }

    # --- the multiplier over the estimation tracts, and its dispersion gate --
    tr = panel.tracts
    fit_all = multiplier(tr["w18"], tr["w65"], b18, b65, anchor_w18, anchor_w65)
    moe_all = multiplier_moe(fit_all, tr["w18"], tr["w65"], b18, b65,
                             anchor_w18, anchor_w65, cov_age,
                             tr["w18_moe"], tr["w65_moe"])
    in_sample = tr["keep"].to_numpy()
    fs = pd.Series(fit_all[in_sample]).dropna()
    ms = pd.Series(moe_all[in_sample]).dropna()
    p10, p50, p90 = (float(fs.quantile(q)) for q in (0.10, 0.50, 0.90))
    median_moe = float(ms.median())
    spread = p90 - p10

    return {
        "spec": SPEC_VERSION,
        "outcome": "log(1 + bar-type on-premises licences within 400 m) "
                   "- log(1 + all on-premises licences within 400 m)",
        "formula": FORMULA,
        "se": f"Conley spatial-HAC, Bartlett kernel, {cutoff_m:.0f} m cutoff",
        "boroughs": sorted(d["borough"].unique().tolist()),
        "n_tracts": int(model.nobs),
        "n_tracts_all": len(tr),
        "r_squared": float(model.rsquared),
        "b18": b18,
        "b18_se_conley": float(np.sqrt(cov[i18, i18])),
        "b18_t_conley": b18 / float(np.sqrt(cov[i18, i18])),
        "b65": b65,
        "b65_se_conley": float(np.sqrt(cov[i65, i65])),
        "b65_t_conley": b65 / float(np.sqrt(cov[i65, i65])),
        "cov_age_conley": [[float(v) for v in row] for row in cov_age],
        "anchor_w18": anchor_w18,
        "anchor_w65": anchor_w65,
        "contrast": {
            "from_nta": CONTRAST_NTAS["from"], "to_nta": CONTRAST_NTAS["to"],
            "from_w18": ch18, "from_w65": ch65, "to_w18": ev18, "to_w65": ev65,
            "pooled": pooled_contrast,
        },
        "by_borough": by_borough,
        "coefficients": {k: float(v) for k, v in model.params.items()},
        "multiplier": {
            "p10": p10, "p50": p50, "p90": p90,
            "spread": spread,
            "median_moe": median_moe,
            "dispersion_ratio": (spread / median_moe) if median_moe > 0 else float("inf"),
            "min": float(fs.min()), "max": float(fs.max()),
        },
        "inputs": {
            "acs_year": panel.acs_year,
            "supply_hash": panel.supply_hash,
            "n_onprem_licences": panel.n_licences,
            "n_bar_licences": panel.n_bar_licences,
            "hash": inputs_hash(panel.supply_hash, panel.acs_year, panel.n_bar_licences),
        },
        "disclaimer": AGE_FIT_DISCLAIMER,
        "fitted_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


def inputs_hash(supply_hash: str | None, acs_year: int, n_bar_licences: int) -> str:
    """The identity of the inputs a curve was revealed from. A supply-revealed
    coefficient is only valid against the supply set it was revealed from
    (docs/bar_age_nyc.md §7.2 test 7), so this triple is stamped on the fit and
    re-checked by `apply_age_fit` before the multiplier touches a ranking."""
    key = f"{supply_hash}|{acs_year}|{n_bar_licences}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# --------------------------------------------------------------- the F2 gate

def failed_gates(fit: dict) -> list[str]:
    """Which of the published failure criteria this curve fails. Empty == ship.

    Pure, so a test can hand it a synthetic curve. Two criteria are enforced
    here because they are the two that decide whether the multiplier may be
    APPLIED at all:

      F2  the Brooklyn-only Conley CI on the Carnegie-Hill -> East-Village
          contrast must EXCLUDE 1.0. This is the criterion the note names as
          binding: it is the only reason the composition spec is preferred over
          the bar-POI count spec, whose Brooklyn CI grazes 1.0 at [1.011,
          2.178]. Brooklyn, not the pooled sample, because 98.2% of the
          bar-lead gap set is in Brooklyn -- calibrating where the signal is and
          shipping where it isn't is the failure this test exists to catch.
      F3  the dispersion gate: p90 - p10 of the multiplier must exceed its own
          median MOE. The CEX predecessor failed this at 0.10 and that failure
          is what retired it; a successor that cannot clear its own noise floor
          is not an improvement.

    The remaining criteria (F1 non-filtering, F4 the EV > CH ordering with MOEs,
    F5 the placebo ordering, F6 the Jaccard band, F7 Conley-not-HC3) are pinned
    by tests/test_age_fit.py and by the note, not re-derived on every fit.
    """
    bad: list[str] = []
    bk = (fit.get("by_borough") or {}).get("BK")
    if not bk:
        bad.append("F2 (no Brooklyn-only fit -- the gate cannot be evaluated)")
    else:
        lo, hi = bk["contrast"]["ci_low"], bk["contrast"]["ci_high"]
        if lo <= 1.0 <= hi:
            bad.append(f"F2 (Brooklyn Conley CI [{lo:.3f}, {hi:.3f}] includes 1.0)")
    ratio = fit["multiplier"]["dispersion_ratio"]
    if not (ratio >= DISPERSION_GATE_MIN):
        bad.append(f"F3 (dispersion spread/MOE = {ratio:.2f} < {DISPERSION_GATE_MIN})")
    return bad


def write_fit_if_gates_pass(fit: dict, path: pathlib.Path = FIT_PATH) -> pathlib.Path:
    """Persist the curve -- and ONLY if it passes its own failure criterion.

    The order matters and is the point: gates first, write second. A curve that
    fails F2 or F3 leaves the previous `age_fit_bar.json` exactly as it was, so
    a failed re-fit degrades to "yesterday's curve, explicitly stale" rather
    than to "today's curve, quietly invalid"."""
    bad = failed_gates(fit)
    if bad:
        raise AgeFitGateFailure(
            "age_fit_bar failed its own failure criterion (docs/bar_age_nyc.md §7.1): "
            + "; ".join(bad) + ". Nothing written; the multiplier must not be applied "
            "from a curve that fails its own criterion.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fit, indent=2, sort_keys=True) + "\n")
    return path


def load_fit(path: pathlib.Path = FIT_PATH) -> dict:
    if not pathlib.Path(path).exists():
        raise FileNotFoundError(
            f"{path} not found -- run `loci age-fit fit` before `loci age-fit apply`")
    return json.loads(pathlib.Path(path).read_text())


def fit_bar_curve(con, boroughs: list[str] = FIT_BOROUGHS, acs_year: int = ACS_YEAR,
                  cutoff_m: float = CONLEY_CUTOFF_M, dry_run: bool = False,
                  path: pathlib.Path = FIT_PATH) -> tuple[dict, pathlib.Path | None]:
    """Re-estimate the curve from the warehouse. READ-ONLY on the database in
    both modes; under `--dry-run` it also writes no JSON. Returns
    (fit, path-written-or-None) and RAISES `AgeFitGateFailure` before writing
    anything if the curve fails F2 or F3."""
    boroughs = list(boroughs)
    addr = load_addresses(con, boroughs, acs_year)
    panel = build_tract_panel(con, boroughs, acs_year, addresses=addr)
    fit = estimate_bar_curve(panel, addr, cutoff_m=cutoff_m)
    if dry_run:
        bad = failed_gates(fit)
        if bad:
            raise AgeFitGateFailure(
                "age_fit_bar failed its own failure criterion (docs/bar_age_nyc.md §7.1): "
                + "; ".join(bad))
        return fit, None
    return fit, write_fit_if_gates_pass(fit, path)


# ------------------------------------------------------------- the apply side

def compute_age_fit(con, boroughs: list[str], fit: dict,
                    acs_year: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(category-grain frame, address-grain frame). READ-ONLY.

    The category frame carries one row per (address, FITTED category) with its
    multiplier and MOE; the address frame carries `age_fit_lead`,
    `age_fit_lead_moe` and `gap_score_fit` for every in-scope address.

    `age_fit_lead` is 1.0 -- the identity multiplier, so `gap_score_fit ==
    gap_score` exactly -- whenever the address's lead category has no fitted
    curve, or has one but no ACS age mix to evaluate it at. Its MOE is NULL
    there, not 0.0: "no curve" is not "a curve with no uncertainty".
    """
    acs_year = fit["inputs"]["acs_year"] if acs_year is None else acs_year
    addr = load_addresses(con, list(boroughs), acs_year)
    b18, b65 = fit["b18"], fit["b65"]
    a18, a65 = fit["anchor_w18"], fit["anchor_w65"]
    cov_age = np.asarray(fit["cov_age_conley"], float)

    value = multiplier(addr["w18"], addr["w65"], b18, b65, a18, a65)
    moe = multiplier_moe(value, addr["w18"], addr["w65"], b18, b65, a18, a65,
                         cov_age, addr["w18_moe"], addr["w65_moe"])
    # A tract with no published age share (or no MOE) gets no multiplier at all.
    # Failing closed to NULL is the only honest option: a silent 1.0 would be
    # indistinguishable from "fitted, and neutral".
    ok = (addr["w18"].notna() & addr["w65"].notna()
          & addr["w18_moe"].notna() & addr["w65_moe"].notna()).to_numpy()
    addr["age_fit"] = np.where(ok, value, np.nan)
    addr["age_fit_moe"] = np.where(ok, moe, np.nan)

    cat_rows = []
    for cat in FITTED_CATEGORIES:
        part = addr.loc[addr["age_fit"].notna(),
                        ["address_id", "borough", "age_fit", "age_fit_moe"]].copy()
        part["category"] = cat
        # The SPEC that produced the number, taken from the fit rather than
        # from the module constant: a row must say which curve it came from,
        # not which curve the code currently ships.
        part["age_fit_source"] = fit.get("spec", SPEC_VERSION)
        cat_rows.append(part)
    cat_df = (pd.concat(cat_rows, ignore_index=True) if cat_rows
              else pd.DataFrame(columns=["address_id", "borough", "category",
                                         *AGE_FIT_COLUMNS]))
    cat_df = cat_df[["address_id", "borough", "category", *AGE_FIT_COLUMNS]]

    lead_is_fitted = addr["lead_category"].isin(FITTED_CATEGORIES) & addr["age_fit"].notna()
    addr_df = pd.DataFrame({
        "address_id": addr["address_id"],
        "borough": addr["borough"],
        "age_fit_lead": np.where(addr["lead_category"].isna(), np.nan,
                                 np.where(lead_is_fitted, addr["age_fit"], 1.0)),
        "age_fit_lead_moe": np.where(lead_is_fitted, addr["age_fit_moe"], np.nan),
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
                  boroughs: list[str]) -> tuple[int, int]:
    """UPDATE-only annotation of both tables. Never INSERT, never DELETE, and
    the two SET lists are built exclusively from AGE_FIT_COLUMNS and
    ADDRESS_AGE_FIT_COLUMNS.

    RESET-then-UPDATE on both, for the same reason address_demand.py does it: a
    row that carried a multiplier on the last run and falls out of scope on this
    one (a category that stopped being fitted, a tract that lost its ACS age
    mix) would otherwise keep last run's number forever, because UPDATE has no
    DELETE to fall back on. `boroughs` is passed explicitly rather than inferred
    from the frames so an empty-frame run still clears.
    """
    if not boroughs:
        return 0, 0
    _assert_disjoint()
    holes = ", ".join("?" for _ in boroughs)
    con.execute(
        f"UPDATE analysis.address_category SET "
        f"{', '.join(f'{c} = NULL' for c in AGE_FIT_COLUMNS)} WHERE borough IN ({holes})",
        list(boroughs))
    con.execute(
        f"UPDATE analysis.address SET "
        f"{', '.join(f'{c} = NULL' for c in ADDRESS_AGE_FIT_COLUMNS)} WHERE borough IN ({holes})",
        list(boroughs))

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


def check_fit_is_current(con, fit: dict) -> None:
    """Refuse a curve fitted against a different supply set / ACS vintage /
    licence count than the database now holds (docs/bar_age_nyc.md §7.2 test 7).
    The supply set moved twice in one month (D52/D59); multiplying today's gap
    set by a curve revealed from a different one is exactly the silent error
    this check exists to make loud."""
    rows = con.execute(
        "SELECT DISTINCT supply_hash FROM analysis.address WHERE supply_hash IS NOT NULL"
    ).fetchall()
    live_supply = rows[0][0] if len(rows) == 1 else None
    n_bar = con.execute(f"""
        SELECT count(*) FROM staging.alcohol_licences
        WHERE active AND borough IN ({', '.join("?" for _ in FIT_BOROUGHS)})
          AND classification = 'on_premises'
          AND lower(trim(description)) IN ({', '.join("?" for _ in BAR_DESCRIPTIONS)})
    """, [*FIT_BOROUGHS, *sorted(BAR_DESCRIPTIONS)]).fetchone()[0]
    live = inputs_hash(live_supply, fit["inputs"]["acs_year"], int(n_bar))
    if live != fit["inputs"]["hash"]:
        raise AgeFitStale(
            f"age_fit_bar.json was fitted from inputs {fit['inputs']['hash']} "
            f"(supply {fit['inputs']['supply_hash']}, "
            f"{fit['inputs']['n_bar_licences']:,} bar-type licences) but the database "
            f"now holds {live} (supply {live_supply}, {n_bar:,}). "
            "Re-run `loci age-fit fit`.")


def apply_age_fit(con, boroughs: list[str] = FIT_BOROUGHS, fit: dict | None = None,
                  path: pathlib.Path = FIT_PATH, dry_run: bool = False,
                  check_current: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """compute + write. A no-op on the database under `--dry-run`: the frames
    are computed and returned, and nothing is written."""
    fit = load_fit(path) if fit is None else fit
    if check_current:
        check_fit_is_current(con, fit)
    boroughs = list(boroughs)
    cat_df, addr_df = compute_age_fit(con, boroughs, fit)
    report = summarize(cat_df, addr_df, fit)
    if not dry_run:
        n_cat, n_addr = write_age_fit(con, cat_df, addr_df, boroughs)
        report["written_category_rows"] = n_cat
        report["written_address_rows"] = n_addr
    return cat_df, addr_df, report


# ---------------------------------------------------------------- reporting

def summarize(cat_df: pd.DataFrame, addr_df: pd.DataFrame, fit: dict) -> dict:
    """Pure, DB-free summary shared by --dry-run and the post-write report."""
    fitted = cat_df["age_fit"].dropna() if len(cat_df) else pd.Series(dtype=float)
    lead = addr_df["age_fit_lead"].dropna() if len(addr_df) else pd.Series(dtype=float)
    return {
        "spec": fit["spec"],
        "b18": fit["b18"], "b65": fit["b65"],
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
