"""Carrying capacity: how many establishments of a category coexist with N
people, and how that changes with density -- in NYC, and against every large US
metro (owner, 2026-09-14: "how many small businesses can a certain amount of
people support? density vs revenue model. what can other cities learn from
NYC?").

WHAT THIS IS, AND THE THREE WORDS IT IS NOT
===========================================================================
It is an OBSERVED EQUILIBRIUM. For a given resident count it reports how many
shops New York actually has, today, with an interval. It is NOT:

  * a MAXIMUM -- nothing here says another shop would fail. Loci has no
    viability outcome at all (D88: the one survival-adjacent test, LL157
    go-dark, returned a null, and Foursquare closures are ~3% ascertained), so
    "N people support K shops" always means "N people are observed alongside K
    shops", never "N people can profitably sustain K shops".
  * CAUSAL. Density and retail are jointly determined; a zoning line, a subway
    stop and a 1920s streetcar route are in both. This is a conditional mean.
  * a PREDICTOR OF GROWTH. Retail is the DEPENDENT variable on every line of
    this module. Reading a thick retail street as a signal that more people are
    coming is the rejected D1 thesis, and the D88 retrodiction confirmed the
    sign runs the other way (own-category thickness predicts own-category
    ENTRY, i.e. agglomeration).

TWO GRAINS, AND WHY THEY CANNOT BE THE SAME ONE
===========================================================================
Part 1 (NYC) is at the ADDRESS grain on a 400 m walkshed: "how many shops are
within a 400 m walk of a doorway with H homes around it". That is the
site-selection question, and it is the grain every other Loci measure lives on.
Its catchments OVERLAP -- one shop is counted by every address within 400 m of
it -- so those counts can never be compared to an area-partition count.

Part 2 (national) is at the ZCTA grain on CBP payroll establishments: a
PARTITION of land, each shop counted once. NYC's own ZCTAs sit in that national
frame with no special casing, which is what makes "is NYC above or below the
national curve" a real question rather than a units mismatch.

The bridge between the two is the CBP-to-POI ratio per category, measured on
the SAME NYC ZIP partition (analysis.zip_coverage_check, D40/D47). That ratio is
not an annoyance to be divided away: it is a portability parameter. A city
without NYC's licence rosters will measure its POI supply differently, and the
ratio says by how much.

THE FUNCTIONAL FORM, AND WHY NOT A LINE
===========================================================================
Candidate forms, all fitted by the POISSON LOG-LIKELIHOOD (the target is a
count, its variance grows with its mean, and 7-70% of address-category cells are
zero -- so logging the outcome is not available, and least squares on a count
would let a single Midtown block with 300 restaurants outweigh ten thousand
Brooklyn doorways). The reported loss is `nll2` = the Poisson deviance with its
parameter-free saturated term dropped; see `poisson_nll2` for why that term
cannot survive the collapsing step and is therefore dropped everywhere rather
than sometimes.

  proportional      mu = a*H                 THE BASELINE. Constant shops per
                                             home: no saturation whatsoever.
  power             mu = a*H^b               b < 1 is sublinear growth
  michaelis_menten  mu = Emax*H/(K+H)        a hard asymptote
  hill              mu = Emax*H^b/(K^b+H^b)  nests MM (b=1), behaves like the
                                             power form while H << K
  hill_density      hill * (D/Dref)^c        the density shifter

A saturating form SHIPS ONLY IF IT BEATS `proportional` OUT OF SAMPLE. That is
the whole gate, and it is the reason this module cannot manufacture a
saturation story: the null is "shops scale one-for-one with people", the
alternative has to earn the difference on held-out neighborhoods, and when it
does not, the category is recorded as `proportional` with NO flattening density
at all rather than a fitted curve nobody checked.

VALIDATION IS NTA-BLOCKED, AND THE REASON IS NOT STYLE
===========================================================================
Two addresses 80 m apart share almost the same 400 m catchment and therefore
almost the same y. A random train/test split puts the same shops on both sides
and every form scores beautifully. Folds are therefore GroupKFold on
`nta_code`: a whole neighborhood is held out at once. For the same reason the
effective sample size is the number of NTAs (111), not the number of addresses
(281,842), so every interval in this module is an NTA BLOCK BOOTSTRAP and the
address count is never used as an n.

WHAT THE CURVE CANNOT RESOLVE (state it before anyone asks)
===========================================================================
Inside a fixed 400 m walkshed, resident count and residential density are
nearly the same variable: density = residents / shed area, and the shed area
varies only 0.195-0.312 km2 p10-p90 (D83) against a ~10x range in homes. So N
and D are collinear by construction at this grain and the model CANNOT
separately identify them; `hill_density` exists to measure how little the
residual area variation buys, and ships only if the gate says it buys
something. A query at a density implying a walkshed far outside [0.15, 0.40]
km2 is OUT OF SUPPORT and is flagged, not silently extrapolated -- which is
exactly the suburban case, and exactly why the national ZCTA curve ships beside
the NYC one.

RECONCILIATION WITH THE EXISTING SATURATION RESULTS
===========================================================================
D70 (density_elasticity.yaml) fitted a DYNAMIC saturation: 2013-23 growth in
establishments against 2013 establishments-per-resident, at ZIP grain, and
found eight daily-needs categories saturating. This module fits a STATIC one:
the level of supply against the level of population, at address grain, today.
They can disagree honestly -- a category can be sublinear in levels and still
grow anywhere (or vice versa) -- so the fit report carries D70's regime beside
its own and the doc reads the overlap rather than assuming it.

D81/D91's `capacity_bound` is a THIRD and different thing: a physical ceiling
from PLUTO retail floor area, which binds on 62% of Manhattan lot rows. Demand
saturation and floor-area saturation are separate mechanisms, and a category
can hit either first; the fit report carries the capacity-bound share too.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import pathlib
import time

import numpy as np
import pandas as pd
import yaml

from loci.categories import CATEGORIES

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
YAML_PATH = PKG_ROOT / "model" / "carrying_capacity.yaml"
DENSITY_YAML = PKG_ROOT / "model" / "density_elasticity.yaml"

BOROUGHS = ("MN", "BK")
# `analysis.hex.borough` spells boroughs out; `analysis.address.borough` uses the
# two-letter code. Anything crossing the hex-ZIP crosswalk must translate.
BOROUGH_NAMES = {"MN": "Manhattan", "BK": "Brooklyn", "QN": "Queens",
                 "BX": "Bronx", "SI": "Staten Island"}
FRAME = "lot"
RADIUS_M = 400.0

# --- the gate -------------------------------------------------------------
N_FOLDS = 5
MIN_FOLDS_BEATEN = 4          # of N_FOLDS, a saturating form must win this many
MIN_DEVIANCE_GAIN = 0.02      # ...and cut mean OOS deviance by at least 2%
BOOTSTRAP_B = 200             # NTA block bootstrap draws
BOOTSTRAP_ALPHA = 0.10        # -> 90% intervals
MIN_NONZERO = 1_000           # a category with fewer non-zero cells is not fitted
PARSIMONY_TOL = 0.01          # a simpler passing form wins if within 1% of the best

# The walkshed-area band the NYC curve was estimated on (D83: measured median
# 0.267 km2, p10 0.195, p90 0.312). A query whose residents/density imply an
# area outside this is extrapolation and is flagged as such.
SHED_KM2_SUPPORT = (0.15, 0.40)

RNG_SEED = 20260914

# How long to keep trying for the warehouse when a peer session holds the write
# lock. Concurrent writers are the normal state of this project, so the wait is
# long and the failure mode is a clear message rather than a stack trace.
LOCK_RETRIES = 40
LOCK_WAIT_S = 45.0


def connect_read_only_retry(retries: int = LOCK_RETRIES, wait_s: float = LOCK_WAIT_S):
    """Open the warehouse READ ONLY, retrying the lock another session holds.

    Same contract as `model.density_elasticity.connect_read_only` and for the
    same reason, but routed through `loci.db.connect` so `LOCI_DB` is honoured
    and the extension bootstrap runs. Never kills anything: a peer mid-write is
    normal, and this module only ever reads.
    """
    from loci.db import connect

    last = None
    for i in range(retries):
        try:
            return connect(read_only=True)
        except Exception as exc:
            last = exc
            if "lock" not in str(exc).lower():
                raise
            if i < retries - 1:
                time.sleep(wait_s)
    raise RuntimeError(
        f"warehouse still locked after {retries} tries "
        f"({retries * wait_s / 60:.0f} min): {last}")


# ===========================================================================
# functional forms
# ===========================================================================

D_REF = 10_000.0   # residents per km2; the scale `hill_density` is centred on
EXP_CLIP = 700.0   # log(float64 max) is ~709; every exponent is clipped here

# Every form is evaluated through `_safe_exp` on a LOG scale rather than by
# raising arrays to a power directly. The naive spelling of the Hill function,
# `emax * h**b / (k**b + h**b)`, overflows to inf/inf = nan the moment the
# optimiser tries b = 40 on a catchment of 20,000 -- which it will, because
# nothing stops it -- and a nan objective silently ends the search wherever it
# happened to be standing. The algebraically identical `emax / (1 + exp(b*(log k
# - log h)))` cannot overflow once the exponent is clipped.


def _safe_exp(z):
    return np.exp(np.clip(z, -EXP_CLIP, EXP_CLIP))


def _mu_proportional(p, h, d):
    return _safe_exp(p[0]) * h


def _mu_power(p, h, d):
    return _safe_exp(p[0] + p[1] * np.log(np.maximum(h, 1.0)))


def _mu_mm(p, h, d):
    emax, k = _safe_exp(p[0]), _safe_exp(p[1])
    return emax * h / (k + h)


def _mu_hill(p, h, d):
    logit = p[2] * (p[1] - np.log(np.maximum(h, 1.0)))
    return _safe_exp(p[0]) / (1.0 + _safe_exp(logit))


def _mu_hill_density(p, h, d):
    shift = p[3] * (np.log(np.maximum(d, 1.0)) - math.log(D_REF))
    return _mu_hill(p[:3], h, d) * _safe_exp(shift)


@dataclasses.dataclass(frozen=True)
class Form:
    name: str
    params: tuple[str, ...]
    mu: object
    saturating: bool     # can this form bend away from proportionality at all?

    @property
    def k(self) -> int:
        return len(self.params)


FORMS: dict[str, Form] = {
    f.name: f for f in (
        Form("proportional", ("log_a",), _mu_proportional, False),
        Form("power", ("log_a", "b"), _mu_power, True),
        Form("michaelis_menten", ("log_emax", "log_k"), _mu_mm, True),
        Form("hill", ("log_emax", "log_k", "b"), _mu_hill, True),
        Form("hill_density", ("log_emax", "log_k", "b", "c"), _mu_hill_density, True),
    )
}
BASELINE_FORM = "proportional"
CANDIDATE_FORMS = ("power", "michaelis_menten", "hill", "hill_density")


def _exp_scalar(v: float) -> float:
    """`math.exp` that cannot raise. An optimiser coordinate pushed against the
    clip inside `_safe_exp` is a finite prediction but an infinite parameter,
    and the whole run should not die while writing the report about it."""
    return float(math.exp(min(max(v, -EXP_CLIP), EXP_CLIP)))


def unpack(form: str, params: list[float]) -> dict[str, float]:
    """Raw optimiser coordinates -> named, human-readable parameters. The
    optimiser works in logs so scale parameters stay positive; nobody should
    ever read `log_emax` off a report."""
    f = FORMS[form]
    out: dict[str, float] = {}
    for name, v in zip(f.params, params, strict=True):
        if name.startswith("log_"):
            out[name[4:]] = _exp_scalar(v)
        else:
            out[name] = float(v)
    return out


def predict(form: str, params: list[float], homes, density):
    """mu for a form at its fitted coordinates."""
    h = np.asarray(homes, dtype=float)
    d = np.asarray(density, dtype=float)
    return np.maximum(FORMS[form].mu(np.asarray(params, dtype=float), h, d), 1e-9)


# ===========================================================================
# loss
# ===========================================================================

def poisson_deviance(y: np.ndarray, mu: np.ndarray) -> float:
    """2 * sum[ y*log(y/mu) - (y - mu) ], with the y=0 term taken as its limit.

    Deviance and not squared error because the outcome is a count whose
    variance grows with its mean: on squared error a single Midtown block with
    300 restaurants outweighs ten thousand Brooklyn doorways, and the fitted
    curve stops describing the typical address entirely.
    """
    mu = np.maximum(mu, 1e-9)
    term = np.where(y > 0, y * np.log(np.maximum(y, 1e-12) / mu), 0.0)
    return float(2.0 * np.sum(term - (y - mu)))


N_X_BINS = 300
N_D_BINS = 24


def collapse(h, d, y, n_x: int = N_X_BINS, n_d: int = N_D_BINS):
    """Collapse (residents, density, count) rows onto a log-spaced grid, giving
    (h_cell, d_cell, n_cell, y_sum_cell).

    Why this is legitimate and not a shortcut: the Poisson log-likelihood is
    `sum_i [ y_i*log(mu_i) - mu_i ]`, and mu depends on the row ONLY through
    (h, d). Rows that share a cell therefore share a mu, and their contribution
    is exactly `y_sum*log(mu) - n*mu`. The only approximation is evaluating mu at
    the cell's MEAN (h, d) rather than at each row's own, which on a 300 x 24
    log grid moves h by well under a percent inside a cell.

    It matters because it is the difference between a two-minute fit and a
    two-hour one: 281,842 rows collapse to a few thousand cells, and the fit
    runs 26 times per category between cross-validation and the bootstrap.
    """
    h = np.asarray(h, float)
    d = np.asarray(d, float)
    y = np.asarray(y, float)
    hb = np.digitize(np.log(np.maximum(h, 1e-6)),
                     np.linspace(np.log(max(h.min(), 1e-6)),
                                 np.log(max(h.max(), 1e-6) + 1e-9), n_x))
    db = np.digitize(np.log(np.maximum(d, 1e-6)),
                     np.linspace(np.log(max(d.min(), 1e-6)),
                                 np.log(max(d.max(), 1e-6) + 1e-9), n_d))
    key = hb.astype(np.int64) * (n_d + 2) + db
    order = np.argsort(key, kind="stable")
    key_s, h_s, d_s, y_s = key[order], h[order], d[order], y[order]
    starts = np.flatnonzero(np.r_[True, key_s[1:] != key_s[:-1]])
    n_cell = np.diff(np.r_[starts, len(key_s)]).astype(float)
    h_cell = np.add.reduceat(h_s, starts) / n_cell
    d_cell = np.add.reduceat(d_s, starts) / n_cell
    y_cell = np.add.reduceat(y_s, starts)
    return h_cell, d_cell, n_cell, y_cell


def poisson_nll2(y_sum, n, mu) -> float:
    """2 * sum[ n*mu - y_sum*log(mu) ] -- the Poisson deviance with its
    saturated term dropped.

    The dropped term (2*sum[y*log y - y]) does not depend on the parameters, so
    it changes nothing about which form wins, which fold beats which, or where
    the optimiser lands. It IS dropped rather than carried because it cannot be
    recovered from collapsed cells (sum of y*log y is not a function of sum y),
    and carrying a term that is only sometimes computable is how two numbers in
    the same report end up on two different scales. Everything reported out of
    this module is therefore labelled `nll2`, never `deviance`.
    """
    mu = np.maximum(np.asarray(mu, float), 1e-12)
    return float(2.0 * np.sum(n * mu - y_sum * np.log(mu)))


def _bounds(form: str, h, y) -> list[tuple[float, float]]:
    """Box constraints in optimiser coordinates.

    These are not cosmetic. Left free, the Hill form walks off to Emax = 1e303
    and K = 1e139 -- a perfectly good fit, because in that limit Emax/K^b is
    finite and the Hill IS a power law, so the likelihood is flat along the
    ridge. The prediction is fine and the printed parameters are nonsense, which
    is the worst combination: a report nobody can sanity-check. This is the same
    degeneracy D91 caught in the revenue model's elasticity grid, and the fix is
    the same: if the data want a power law, the `power` form is on the menu and
    can win on its own two parameters.

    Emax is capped at 50x the largest count actually observed, K inside the
    observed catchment range widened 100x either way, the Hill exponent in
    [0.05, 4], and the density shift in [-3, 3].
    """
    ymax = max(float(np.max(y)), 1.0)
    hlo = math.log(max(float(np.min(h)), 1.0))
    hhi = math.log(max(float(np.max(h)), 10.0))
    emax_hi = math.log(50.0 * ymax)
    k_lo, k_hi = hlo - math.log(100.0), hhi + math.log(100.0)
    if form == "proportional":
        return [(-30.0, 10.0)]
    if form == "power":
        return [(-60.0, 20.0), (0.05, 4.0)]
    if form == "michaelis_menten":
        return [(-5.0, emax_hi), (k_lo, k_hi)]
    if form == "hill":
        return [(-5.0, emax_hi), (k_lo, k_hi), (0.05, 4.0)]
    if form == "hill_density":
        return [(-5.0, emax_hi), (k_lo, k_hi), (0.05, 4.0), (-3.0, 3.0)]
    raise KeyError(form)


def _objective(form: str, h, d, n, ysum, bounds):
    f = FORMS[form]
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])

    def obj(p):
        p = np.asarray(p, float)
        if np.any(p < lo) or np.any(p > hi) or not np.all(np.isfinite(p)):
            return 1e18          # hard barrier: Nelder-Mead simply reflects away
        mu = np.maximum(f.mu(p, h, d), 1e-12)
        if not np.all(np.isfinite(mu)):
            return 1e18
        return poisson_nll2(ysum, n, mu)
    return obj


def _init(form: str, h, d, y) -> list[list[float]]:
    """Starting points. Several per form, because a Hill surface has a long
    flat valley in (Emax, K) and a single start lands in it."""
    ybar = max(float(np.mean(y)), 1e-6)
    hbar = max(float(np.mean(h)), 1.0)
    a0 = math.log(ybar / hbar)
    emax0 = math.log(max(float(np.quantile(y, 0.995)), 1.0))
    k0 = math.log(max(float(np.median(h)), 1.0))
    if form == "proportional":
        return [[a0]]
    if form == "power":
        return [[a0, 1.0], [a0 - 2, 0.7], [a0 + 2, 0.4]]
    if form == "michaelis_menten":
        return [[emax0, k0], [emax0 + 1, k0 + 1], [emax0 + 2, k0 + 2]]
    if form == "hill":
        return [[emax0, k0, 1.0], [emax0 + 1, k0 + 1, 0.8], [emax0 + 2, k0 + 2, 1.2]]
    if form == "hill_density":
        return [[emax0, k0, 1.0, 0.0], [emax0 + 1, k0 + 1, 0.8, 0.2],
                [emax0 + 2, k0 + 2, 1.2, -0.2]]
    raise KeyError(form)


def fit_form(form: str, homes, density, y) -> tuple[list[float], float]:
    """(params, in-sample nll2). Multi-start Nelder-Mead on the collapsed grid;
    the surfaces are at most four-dimensional and an analytic gradient would be
    one more place for the formula and the code to disagree."""
    from scipy.optimize import minimize

    h = np.asarray(homes, dtype=float)
    d = np.asarray(density, dtype=float)
    yy = np.asarray(y, dtype=float)
    hc, dc, nc, yc = collapse(h, d, yy)
    bounds = _bounds(form, h, yy)
    obj = _objective(form, hc, dc, nc, yc, bounds)
    best, best_val = None, np.inf
    for p0 in _init(form, h, d, yy):
        p0 = [min(max(v, lo), hi) for v, (lo, hi) in zip(p0, bounds, strict=True)]
        res = minimize(obj, np.asarray(p0, dtype=float), method="Nelder-Mead",
                       options={"maxiter": 3000, "xatol": 1e-6, "fatol": 1e-6})
        if res.fun < best_val:
            best, best_val = list(map(float, res.x)), float(res.fun)
    return best, best_val


# ===========================================================================
# NTA-blocked cross-validation
# ===========================================================================

def nta_folds(nta: np.ndarray, n_folds: int = N_FOLDS,
              seed: int = RNG_SEED) -> list[np.ndarray]:
    """Assign each row a fold by its NTA, balancing fold SIZE not fold count --
    NTAs differ 100-fold in address count and a naive round-robin puts most of
    Brooklyn in one fold."""
    codes, inv = np.unique(nta, return_inverse=True)
    sizes = np.bincount(inv)
    order = np.argsort(-sizes)
    load = np.zeros(n_folds)
    fold_of_nta = np.zeros(len(codes), dtype=int)
    for i in order:
        f = int(np.argmin(load))
        fold_of_nta[i] = f
        load[f] += sizes[i]
    fold = fold_of_nta[inv]
    return [np.flatnonzero(fold == f) for f in range(n_folds)]


def cv_score(form: str, homes, density, y, folds) -> list[float]:
    """Mean held-out Poisson DEVIANCE per observation, one value per fold.

    The FIT runs on the collapsed grid under `nll2`; the SCORE is the true
    deviance on the raw held-out rows. Both halves of that sentence matter. Raw
    rows, because no binning choice should be able to flatter a form on the test
    side. True deviance, because it is bounded below by zero and a RELATIVE
    improvement over the baseline is therefore meaningful -- `nll2` is freely
    negative, and a percentage gain measured against a negative denominator
    silently inverts the gate's sign, passing the forms that lost.
    """
    h = np.asarray(homes, dtype=float)
    d = np.asarray(density, dtype=float)
    yy = np.asarray(y, dtype=float)
    out = []
    for test in folds:
        mask = np.ones(len(yy), dtype=bool)
        mask[test] = False
        params, _ = fit_form(form, h[mask], d[mask], yy[mask])
        mu = predict(form, params, h[test], d[test])
        out.append(poisson_deviance(yy[test], mu) / max(len(test), 1))
    return out


def local_elasticities(form: str, params: list[float], residents: float,
                       shed_km2: float, eps: float = 0.02) -> dict[str, float]:
    """Two log-log slopes at one point on the fitted surface, by finite
    difference:

      residents_fixed_area -- d log(establishments) / d log(residents) with the
          walkshed's AREA held fixed, so density moves with the population. 1.0
          is constant-per-capita; below 1 is saturation.
      area_fixed_residents -- d log(establishments) / d log(area) with the
          population held fixed, so density falls as the shed grows. Positive
          means shops scale with LAND (street frontage, corner lots) and not
          only with customers -- which is the whole content of a density term at
          this grain, and is worth reporting in those words rather than as a
          raw exponent on a ratio nobody can picture.

    Reported at a point rather than as a parameter because the shipped form may
    be a Hill, whose slope changes along the curve; a single global exponent
    would only be honest for the power form.
    """
    def mu_at(n, area):
        return float(predict(form, params, [n], [n / max(area, 1e-9)])[0])

    def slope(f, lo, hi, x_lo, x_hi):
        if f(lo) <= 0 or f(hi) <= 0:
            return float("nan")
        return (math.log(f(hi)) - math.log(f(lo))) / (math.log(x_hi) - math.log(x_lo))

    n_lo, n_hi = residents * (1 - eps), residents * (1 + eps)
    a_lo, a_hi = shed_km2 * (1 - eps), shed_km2 * (1 + eps)
    return {
        "residents_fixed_area": slope(lambda n: mu_at(n, shed_km2), n_lo, n_hi,
                                      n_lo, n_hi),
        "area_fixed_residents": slope(lambda a: mu_at(residents, a), a_lo, a_hi,
                                      a_lo, a_hi),
    }


# ===========================================================================
# the shape of the fitted curve
# ===========================================================================

def marginal(form: str, params: list[float], residents, shed_km2: float,
             step: float = 1.0):
    """dE/d(resident) by central difference, holding the WALKSHED'S AREA fixed.

    Area fixed, not density fixed. The owner's question is "how many more shops
    does one more person buy you", and one more person on the same block raises
    density -- it does not hold it constant. Holding density constant instead
    would quietly grow the shed as the population grows, which answers a
    question about annexing land, not about filling buildings, and in testing it
    reported grocery as still accelerating at the 90th percentile while the
    fixed-area elasticity there had already fallen to 0.61.
    """
    n = np.asarray(residents, dtype=float)
    up = predict(form, params, n + step, (n + step) / shed_km2)
    dn = predict(form, params, np.maximum(n - step, 1.0),
                 np.maximum(n - step, 1.0) / shed_km2)
    return (up - dn) / (2.0 * step)


def flattening_point(form: str, params: list[float], n_lo: float, n_hi: float,
                     shed_km2: float, ratio: float = 0.5) -> float | None:
    """The catchment population at which the marginal establishments-per-resident
    rate has fallen to `ratio` of its value at `n_lo`, in a walkshed of fixed
    area.

    Returns None when the curve never flattens that far inside the OBSERVED
    range. That is the honest answer for a category still accelerating at the
    densest block in Manhattan, and it is reported as "does not flatten in
    support" rather than as a number found by running the fitted curve out past
    the last data point.
    """
    m_lo = float(marginal(form, params, [n_lo], shed_km2)[0])
    if m_lo <= 0:
        return None
    grid = np.geomspace(max(n_lo, 1.0), max(n_hi, n_lo * 1.01), 400)
    m = marginal(form, params, grid, shed_km2)
    hit = np.flatnonzero(m <= ratio * m_lo)
    if len(hit) == 0:
        return None
    return float(grid[hit[0]])


# ===========================================================================
# the panel
# ===========================================================================

PANEL_SQL = """
SELECT a.address_id,
       a.nta_code,
       a.borough,
       a.homes_400m::DOUBLE            AS homes,
       a.walkshed_km2_400m::DOUBLE     AS shed_km2,
       a.density_400m::DOUBLE          AS homes_km2,
       d.median_hh_income::DOUBLE      AS income,
       d.avg_hh_size::DOUBLE           AS avg_hh_size,
       d.population::DOUBLE            AS tract_pop,
       d.households::DOUBLE            AS tract_hh
FROM analysis.address a
LEFT JOIN analysis.address_demographics d USING (address_id)
WHERE a.frame = ?
  AND a.borough IN ({boroughs})
  AND a.homes_400m IS NOT NULL
  AND a.walkshed_km2_400m > 0
"""

SUPPLY_SQL = """
SELECT c.address_id, c.category, c.supply_400m::DOUBLE AS supply,
       c.capacity_bound
FROM analysis.address_category c
JOIN analysis.address a USING (address_id)
WHERE a.frame = ?
  AND a.borough IN ({boroughs})
  AND c.supply_400m IS NOT NULL
"""


def persons_per_home(con, boroughs=BOROUGHS) -> tuple[pd.DataFrame, float]:
    """Residents per PLUTO residential unit, by NTA, and the MN+BK aggregate.

    The warehouse measures `homes_400m` (PLUTO `UnitsRes`, a register count) but
    the owner's question is in PEOPLE. There is no persons-within-400 m column
    and computing one would mean a second Dijkstra sweep over 39k nodes, so the
    conversion is an explicit, published RATIO rather than a hidden constant:
    ACS tract population summed over the NTA, divided by PLUTO units summed over
    the same NTA's addresses.

    What it buys and what it costs: it is right on average within an NTA and
    wrong for any single building (a 400-unit studio tower and a Bay Ridge
    two-family do not house the same people per unit). Because the 400 m shed
    spans several tracts anyway, the NTA ratio is the right grain -- the focal
    address's own tract would be a more precise answer to a question nobody
    asked. Vacancy is inside the ratio by construction: ACS counts people, PLUTO
    counts units, so an NTA with empty units gets a lower ratio, correctly.
    """
    bl = ",".join(f"'{b}'" for b in boroughs)
    # Tract population is MAX, not SUM: `address_demographics` repeats the tract
    # figure once per address in the tract, so summing it would multiply the
    # population of every tract by its own address count. Units are SUM, because
    # a unit really does belong to exactly one address.
    tracts = con.execute(f"""
        SELECT d.tract_geoid,
               MAX(d.population) AS pop,
               MAX(a.nta_code)   AS nta_code,
               SUM(a.units)      AS units
        FROM analysis.address a
        JOIN analysis.address_demographics d USING (address_id)
        WHERE a.frame = 'lot' AND a.borough IN ({bl})
        GROUP BY 1
    """).df()
    by_nta = (tracts.groupby("nta_code")[["pop", "units"]].sum().reset_index())
    by_nta["pph"] = by_nta["pop"] / by_nta["units"].replace(0, np.nan)
    overall = float(tracts["pop"].sum() / max(tracts["units"].sum(), 1.0))
    # An NTA whose ratio is absurd (all-institutional, or a tract boundary
    # mismatch) falls back to the borough-wide ratio rather than propagating a
    # 40-persons-per-unit multiplier into every query that touches it.
    bad = (~np.isfinite(by_nta["pph"])) | (by_nta["pph"] < 0.5) | (by_nta["pph"] > 6.0)
    by_nta.loc[bad, "pph"] = overall
    by_nta["fallback"] = bad.values

    return by_nta[["nta_code", "pph", "fallback", "pop", "units"]], overall


def load_panel(con, boroughs=BOROUGHS, frame: str = FRAME) -> dict:
    """The MN+BK lot-frame panel: one row per address, plus a {category: array}
    of supply counts aligned to it."""
    bl = ",".join(f"'{b}'" for b in boroughs)
    addr = con.execute(PANEL_SQL.format(boroughs=bl), [frame]).df()
    sup = con.execute(SUPPLY_SQL.format(boroughs=bl), [frame]).df()

    pph, overall_pph = persons_per_home(con, boroughs)
    addr = addr.merge(pph[["nta_code", "pph"]], on="nta_code", how="left")
    addr["pph"] = addr["pph"].fillna(overall_pph)
    addr["residents"] = addr["homes"] * addr["pph"]
    addr["residents_km2"] = addr["residents"] / addr["shed_km2"]

    addr = addr.reset_index(drop=True)
    idx = pd.Series(addr.index.values, index=addr["address_id"].values)

    supply: dict[str, np.ndarray] = {}
    bound: dict[str, float] = {}
    for cat, g in sup.groupby("category"):
        arr = np.zeros(len(addr))
        pos = idx.reindex(g["address_id"].values).values
        keep = ~pd.isna(pos)
        arr[pos[keep].astype(int)] = g["supply"].values[keep]
        supply[cat] = arr
        cb = g["capacity_bound"]
        bound[cat] = float(np.nanmean(cb.astype(float))) if cb.notna().any() else float("nan")

    return {"addr": addr, "supply": supply, "capacity_bound_share": bound,
            "overall_pph": float(overall_pph)}


# ===========================================================================
# the per-category fit
# ===========================================================================

ACCELERATING_ABOVE = 1.05
SATURATING_BELOW = 0.95


def curve_shape(elasticities: dict) -> str:
    """Which way the fitted curve bends where the data is, in one word.

    Read off the elasticity at the 90th percentile of catchment population --
    the top of the observed range, which is where "does it flatten" is actually
    a question -- and NOT off the functional form's name. A Hill curve fitted to
    an accelerating cloud is still accelerating; the form is a vocabulary, the
    elasticity is the finding.

      saturating    e(p90) < 0.95  -- each extra 1,000 residents buys fewer
                                      shops than the last
      accelerating  e(p90) > 1.05  -- each extra 1,000 buys MORE
      proportional  in between     -- constant shops per resident
    """
    e90 = elasticities["p90"]["residents_fixed_area"]
    if not np.isfinite(e90):
        return "undetermined"
    if e90 < SATURATING_BELOW:
        return "saturating"
    if e90 > ACCELERATING_ABOVE:
        return "accelerating"
    return "proportional"


def _params_at_bound(form: str, params, h, y, tol: float = 1e-3) -> list[str]:
    """Which fitted parameters are sitting on their box constraint.

    A parameter pinned to its bound is not an estimate -- it is the optimiser
    saying "further, please", and the printed value is an artifact of where the
    fence was put. Reported by name so a reader can discount it instead of
    quoting it as a ceiling.
    """
    out = []
    for name, v, (lo, hi) in zip(FORMS[form].params, params,
                                 _bounds(form, h, y), strict=True):
        span = max(hi - lo, 1e-9)
        if abs(v - lo) / span < tol or abs(v - hi) / span < tol:
            out.append(name.removeprefix("log_"))
    return out


def fit_category(cat: str, addr: pd.DataFrame, y: np.ndarray,
                 folds=None, bootstrap: int = BOOTSTRAP_B,
                 seed: int = RNG_SEED) -> dict:
    """Fit every form for one category, run the gate, and describe the winner.

    The returned dict is what lands in carrying_capacity.yaml, so it carries
    the REFUSALS as loudly as the acceptances: which forms were tried, what the
    baseline scored, how many folds the winner actually won, and -- when the
    gate refuses -- `form: proportional` with a null flattening density.
    """
    x = addr["residents"].to_numpy(float)
    d = addr["residents_km2"].to_numpy(float)
    nta = addr["nta_code"].to_numpy()
    keep = np.isfinite(x) & np.isfinite(d) & (x > 0)
    x, d, yv, nta = x[keep], d[keep], np.asarray(y, float)[keep], nta[keep]

    n_nonzero = int((yv > 0).sum())
    if n_nonzero < MIN_NONZERO:
        return {"category": cat, "fitted": False,
                "reason": f"only {n_nonzero} non-zero cells (< {MIN_NONZERO})"}

    folds = folds if folds is not None else nta_folds(nta, seed=seed)

    scores: dict[str, dict] = {}
    base_cv = cv_score(BASELINE_FORM, x, d, yv, folds)
    base_mean = float(np.mean(base_cv))
    scores[BASELINE_FORM] = {"cv_folds": [float(v) for v in base_cv],
                             "cv_mean": base_mean}

    passing: list[str] = []
    for form in CANDIDATE_FORMS:
        cv = cv_score(form, x, d, yv, folds)
        mean = float(np.mean(cv))
        wins = int(sum(1 for a, b in zip(cv, base_cv, strict=True) if a < b))
        gain = (base_mean - mean) / base_mean if base_mean > 0 else 0.0
        passes = wins >= MIN_FOLDS_BEATEN and gain >= MIN_DEVIANCE_GAIN
        scores[form] = {"cv_folds": [float(v) for v in cv], "cv_mean": mean,
                        "folds_beating_baseline": wins,
                        "deviance_gain_vs_baseline": float(gain),
                        "passes_gate": bool(passes)}
        if passes:
            passing.append(form)

    # Among the forms that PASS, ship the SIMPLEST one that is within
    # PARSIMONY_TOL of the best -- not simply the best. The Hill and the power
    # law share a ridge (Emax -> inf with Emax/K^b fixed makes the Hill a power
    # law exactly), so on data with no real asymptote the three-parameter Hill
    # scores a hair better than the two-parameter power form by fitting the
    # ridge, and then reports an "Emax" pinned against its own bound. Parsimony
    # resolves the tie toward the form whose parameters mean something.
    best_name = None
    if passing:
        best_cv = min(scores[f]["cv_mean"] for f in passing)
        near = [f for f in passing
                if scores[f]["cv_mean"] <= best_cv * (1 + PARSIMONY_TOL)
                or scores[f]["cv_mean"] - best_cv <= abs(best_cv) * PARSIMONY_TOL]
        best_name = min(near, key=lambda f: (FORMS[f].k, scores[f]["cv_mean"]))

    shipped = best_name or BASELINE_FORM
    params, dev_in = fit_form(shipped, x, d, yv)

    # --- the shape, reported only over the range actually observed -----------
    x_lo, x_hi = float(np.quantile(x, 0.01)), float(np.quantile(x, 0.99))
    shed_med = float(np.median(addr["shed_km2"]))
    p10, p50, p90 = (float(np.quantile(d, q)) for q in (0.10, 0.50, 0.90))
    x_at = {q: float(np.quantile(x, q)) for q in (0.10, 0.50, 0.90)}

    marg = {f"p{int(q*100)}": float(marginal(shipped, params, [x_at[q]], shed_med)[0] * 1000.0)
            for q in (0.10, 0.50, 0.90)}
    h_flat = (flattening_point(shipped, params, x_lo, x_hi, shed_med)
              if FORMS[shipped].saturating else None)
    at_bound = _params_at_bound(shipped, params, x, yv)

    # --- NTA block bootstrap -------------------------------------------------
    ci = _block_bootstrap(shipped, x, d, yv, nta, bootstrap, seed)

    elas = {f"p{int(q*100)}": local_elasticities(shipped, params, x_at[q], shed_med)
            for q in (0.10, 0.50, 0.90)}
    shape = curve_shape(elas)

    out = {
        "category": cat,
        "fitted": True,
        "n_addresses": len(x),
        "n_ntas": len(np.unique(nta)),
        "n_nonzero_cells": n_nonzero,
        "form": shipped,
        # Three separate facts that are easy to conflate, so they are three
        # separate fields:
        #   beats_proportional -- did any curved form clear the gate at all
        #   shape              -- which way it curves where the data actually is
        #   saturates          -- shape == "saturating", i.e. the marginal shop
        #                         per resident is FALLING by the 90th percentile
        # A category can beat the proportional baseline by ACCELERATING; calling
        # that "saturating" because a non-linear form won would invert the
        # headline.
        "beats_proportional": bool(best_name is not None),
        "shape": shape,
        "saturates": shape == "saturating",
        "params": unpack(shipped, params),
        "params_at_bound": at_bound,
        # `params_ci90` is each parameter's own marginal interval -- useful for
        # reading (is b bounded away from 1?) and NEVER for building a
        # prediction interval. `bootstrap.draws` is what predictions use.
        "params_ci90": (ci or {}).get("marginal", {}),
        "bootstrap": ci,
        "in_sample_nll2_per_obs": float(dev_in / len(x)),
        "baseline_cv_mean": base_mean,
        "cv": scores,
        "residents_p01": x_lo, "residents_p99": x_hi,
        "residents_p10": x_at[0.10], "residents_p50": x_at[0.50],
        "residents_p90": x_at[0.90],
        "density_p10": p10, "density_p50": p50, "density_p90": p90,
        "marginal_estab_per_1000_residents": marg,
        "flatten_residents": h_flat,
        "flatten_density_residents_km2": (None if h_flat is None
                                          else float(h_flat / shed_med)),
        "walkshed_km2_median": shed_med,
        "estab_per_1000_residents_at": {
            f"p{int(q*100)}": float(predict(shipped, params, [x_at[q]],
                                            [x_at[q] / shed_med])[0]
                                    / x_at[q] * 1000.0)
            for q in (0.10, 0.50, 0.90)},
        "elasticity_at": elas,
    }
    return out


def _block_bootstrap(form: str, x, d, y, nta, b: int, seed: int) -> dict:
    """Resample NTAs with replacement, refit, and KEEP EVERY DRAW.

    Blocks, not addresses: two doorways on one block are one observation of one
    catchment, and bootstrapping them independently would report an interval an
    order of magnitude too tight.

    The draws themselves are returned and shipped, not just each parameter's
    marginal quantiles, because a prediction interval built by evaluating the
    curve at the componentwise parameter bounds IS NOT AN INTERVAL. The
    parameters are strongly correlated -- in a power law a larger exponent
    always comes with a smaller coefficient -- so the "lower" corner of the box
    is a curve the data never supported. The first run of this module reported
    hair_barber at 25.3 establishments with a 90% interval of [5.2, 22.7], a
    point estimate outside its own interval, which is what that mistake looks
    like. `capacity()` now takes the quantiles of the PREDICTIONS across draws.
    """
    if b <= 0:
        return {}
    rng = np.random.default_rng(seed)
    codes, inv = np.unique(nta, return_inverse=True)
    by_code = [np.flatnonzero(inv == i) for i in range(len(codes))]
    draws: list[list[float]] = []
    for _ in range(b):
        pick = rng.integers(0, len(codes), len(codes))
        idx = np.concatenate([by_code[i] for i in pick])
        try:
            p, _ = fit_form(form, x[idx], d[idx], y[idx])
            draws.append(p)
        except Exception:  # noqa: BLE001,S112 - a degenerate resample is dropped, and counted
            continue
    if not draws:
        return {}
    arr = np.asarray(draws)
    lo = np.quantile(arr, BOOTSTRAP_ALPHA / 2, axis=0)
    hi = np.quantile(arr, 1 - BOOTSTRAP_ALPHA / 2, axis=0)
    names = FORMS[form].params
    marginal: dict[str, list[float]] = {}
    for i, name in enumerate(names):
        a, bb = float(lo[i]), float(hi[i])
        if name.startswith("log_"):
            marginal[name.removeprefix("log_")] = [_exp_scalar(a), _exp_scalar(bb)]
        else:
            marginal[name] = [a, bb]
    return {"marginal": marginal, "n_draws": len(draws),
            "draws": [[round(float(v), 8) for v in row] for row in arr]}


# ===========================================================================
# the query -- "how many can N people support"
# ===========================================================================

CAVEAT = (
    "Observed equilibrium in NYC 2024-26: what the market HAS at this density, "
    "not what it could hold. Loci has no viability outcome (D88), so no number "
    "here says another shop would succeed or fail."
)


def load_fit(path: pathlib.Path | None = None) -> dict:
    p = path or YAML_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"{p} does not exist -- run `loci capacity --fit` first. The query "
            "refuses to fall back on a default curve, because a silently "
            "defaulted parameter is indistinguishable from a fitted one.")
    return yaml.safe_load(p.read_text())


def capacity(residents: float, density: float, category: str | None = None,
             fit: dict | None = None) -> list[dict]:
    """Expected establishments within a 400 m walk for a catchment of
    `residents` people at `density` residents/km2, per category.

    `density` is used two ways and both are reported: it implies the catchment
    AREA (residents/density), which is checked against the walkshed band the
    curve was estimated on, and it enters the fitted curve directly for any
    category whose gate accepted the `hill_density` form.
    """
    fit = fit or load_fit()
    cats = [category] if category else list(CATEGORIES)
    shed_km2 = residents / density if density > 0 else float("nan")
    in_support_shed = SHED_KM2_SUPPORT[0] <= shed_km2 <= SHED_KM2_SUPPORT[1]

    rows = []
    for cat in cats:
        rec = fit["categories"].get(cat)
        if rec is None or not rec.get("fitted"):
            rows.append({"category": cat, "fitted": False,
                         "reason": (rec or {}).get("reason", "not in the fitted file")})
            continue
        form = rec["form"]
        params = _repack(form, rec["params"])
        mu = float(predict(form, params, [residents], [density])[0])
        # The interval is the 5th-95th percentile of the PREDICTION across the
        # NTA block-bootstrap draws -- refit the curve on a resampled set of
        # neighborhoods, ask each refit this same question, and report the
        # spread of the answers. See `_block_bootstrap` for why the parameters'
        # own marginal bounds cannot be used for this.
        lo = hi = None
        draws = (rec.get("bootstrap") or {}).get("draws") or []
        if draws:
            preds = np.array([float(predict(form, p, [residents], [density])[0])
                              for p in draws])
            lo = float(np.quantile(preds, BOOTSTRAP_ALPHA / 2))
            hi = float(np.quantile(preds, 1 - BOOTSTRAP_ALPHA / 2))
        rows.append({
            "category": cat,
            "fitted": True,
            "form": form,
            "shape": rec.get("shape", "undetermined"),
            "saturates": rec.get("saturates", False),
            "expected": mu,
            "ci90": [lo, hi] if lo is not None else None,
            "per_1000_residents": mu / residents * 1000.0 if residents > 0 else None,
            "in_support_residents": bool(rec["residents_p01"] <= residents
                                         <= rec["residents_p99"]),
            "observed_range_residents": [rec["residents_p01"], rec["residents_p99"]],
            # The national figure is evaluated at the QUERY's density, not at
            # New York's -- that is the whole point of having it beside the NYC
            # number, and reading a stored NYC-density value here would print
            # "the national curve at NYC density" under a column headed
            # "national".
            "national_per_1000_residents": national_at(fit, cat, density),
            "national_form": ((fit.get("national") or {}).get(cat) or {}).get("form"),
            "nyc_vs_national_ratio": (
                ((fit.get("national") or {}).get(cat) or {})
                .get("held_out_metro", {}).get("ratio_observed_over_predicted")),
            "cbp_per_poi_ratio": (fit.get("cbp_poi_ratio", {}).get(cat) or {}).get(
                "ratio_aggregate"),
        })
    return [{"residents": residents, "density_residents_km2": density,
             "implied_walkshed_km2": shed_km2,
             "in_support_walkshed": in_support_shed,
             "caveat": CAVEAT}] + rows


def _repack(form: str, named: dict[str, float]) -> list[float]:
    """Named parameters -> optimiser coordinates (the inverse of `unpack`)."""
    out = []
    for p in FORMS[form].params:
        if p.startswith("log_"):
            out.append(math.log(float(named[p[4:]])))
        else:
            out.append(float(named[p]))
    return out


# ===========================================================================
# writing the fitted file
# ===========================================================================

def d70_regimes(path: pathlib.Path | None = None) -> dict[str, str]:
    """D70's per-category regime (saturating / clustering / no_signal), read
    from the shipped density_elasticity.yaml so the two results can be compared
    without re-deriving either."""
    p = path or DENSITY_YAML
    if not p.exists():
        return {}
    doc = yaml.safe_load(p.read_text()) or {}
    cats = doc.get("categories", {})
    out = {}
    for k, v in cats.items():
        if isinstance(v, dict):
            out[k] = v.get("regime") or v.get("classification")
    return out


def fit_hash(doc: dict) -> str:
    blob = yaml.safe_dump(doc.get("categories", {}), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


HEADER = """\
# Carrying capacity -- FITTED OUTPUT, generated by `loci capacity --fit`.
# Do not hand-edit: every number below is a fit result and a hand edit makes the
# file a claim nobody checked.
#
# READ THIS BEFORE QUOTING ANY NUMBER
# -----------------------------------------------------------------------
# `expected` is the OBSERVED EQUILIBRIUM: how many establishments of a category
# are within a 400 m walk of the typical MN+BK doorway with this many people
# around it, in NYC in 2024-26. It is NOT a maximum, NOT causal, and NOT a
# forecast. Loci has no viability outcome (D88), so nothing here can say whether
# one more shop would survive.
#
# `form: proportional` means THE GATE REFUSED SATURATION for that category: the
# saturating candidates did not beat a constant-shops-per-resident baseline on
# held-out neighborhoods, so no flattening density is reported and none should
# be quoted.
#
# Intervals are NTA BLOCK bootstraps. The address count is not a sample size --
# 400 m catchments overlap, so the effective n is the NTA count.
"""


def plain(obj):
    """Recursively convert numpy scalars/arrays and pandas NA to plain Python.

    PyYAML refuses to represent `np.float64`, and half of this document comes
    out of pandas aggregations that produce exactly that. Coerced here, once, on
    the way to disk -- rather than by sprinkling `float(...)` through twenty
    dict literals and finding the twenty-first in a traceback.
    """
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return [plain(v) for v in obj.tolist()]
    if obj is pd.NA or (isinstance(obj, float) and not np.isfinite(obj)):
        return None
    return obj


def write_fit(doc: dict, path: pathlib.Path | None = None) -> pathlib.Path:
    p = path or YAML_PATH
    doc = plain(doc)
    doc = {**doc, "fit_hash": fit_hash(doc)}
    p.write_text(HEADER + yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
    return p


def run_fit(con, boroughs=BOROUGHS, bootstrap: int = BOOTSTRAP_B,
            categories=None, progress=None) -> dict:
    """Fit every category on the NYC address panel. `run_all` adds the national
    half; this half is separable so a NYC-only refit does not re-pull Census."""
    panel = load_panel(con, boroughs)
    addr = panel["addr"]
    folds = nta_folds(addr["nta_code"].to_numpy())
    regimes = d70_regimes()

    cats = list(categories) if categories else list(CATEGORIES)
    out: dict[str, dict] = {}
    for i, cat in enumerate(cats, 1):
        y = panel["supply"].get(cat)
        if y is None:
            out[cat] = {"category": cat, "fitted": False,
                        "reason": "no supply_400m rows"}
            continue
        t0 = time.time()
        rec = fit_category(cat, addr, y, folds=folds, bootstrap=bootstrap)
        rec["d70_regime"] = regimes.get(cat)
        rec["capacity_bound_share"] = panel["capacity_bound_share"].get(cat)
        rec["fit_seconds"] = round(time.time() - t0, 1)
        out[cat] = rec
        if progress:
            progress(i, len(cats), cat, rec)

    return {
        "version": 1,
        "computed_on": time.strftime("%Y-%m-%d"),
        "grain": "address (lot frame), 400 m network walkshed, MN+BK",
        "supply_set": "analysis.poi_supply WHERE in_principled (D52/D59)",
        "target": "supply_400m -- POI count, NOT CBP payroll establishments",
        "n_addresses": len(addr),
        "n_ntas": int(addr["nta_code"].nunique()),
        "persons_per_home_overall": panel["overall_pph"],
        "walkshed_km2_median": float(addr["shed_km2"].median()),
        "gate": {"baseline": BASELINE_FORM, "min_folds_beaten": MIN_FOLDS_BEATEN,
                 "min_deviance_gain": MIN_DEVIANCE_GAIN, "n_folds": N_FOLDS,
                 "blocking": "GroupKFold on nta_code"},
        "categories": out,
    }


# ===========================================================================
# PART 2 -- the national curve (CBP/ZBP, ZCTA grain, every metro >= 500k)
# ===========================================================================
#
# A DIFFERENT MODEL, ON PURPOSE. Part 1 asks "how many shops are within a 400 m
# walk", on catchments that overlap and at a radius fixed by construction, so
# resident count and density there are one variable (see the module header).
# A ZCTA is a PARTITION: each establishment belongs to exactly one, population
# and land area are both measured on it, and so "establishments per 1,000
# residents as a function of density" is separately identified. That is the
# curve other cities can actually be placed on, so it is the one the national
# half fits:
#
#     mu = (population / 1000) * rate(density)
#
# fitted as a Poisson model with log(population/1000) as an OFFSET, so the
# parameters describe the RATE and nothing else. The baseline the saturating
# forms must beat is `rate(D) = r0` -- a constant per-capita rate, density
# irrelevant. Folds are blocked by CBSA: two ZCTAs in the same metro share a
# retail culture, a state licensing regime and a chain footprint.

SQMI_TO_KM2 = 2.589988110336
NYC_CBSA = "35620"          # New York-Newark-Jersey City, NY-NJ
MIN_METRO_POP = 500_000
MIN_ZCTA_POP = 1_000        # matches zbp_compare.LOW_POP_CUTOFF
N_FOLDS_NATIONAL = 5


def _rate_const(p, d):
    return _safe_exp(p[0]) * np.ones_like(d)


def _rate_power(p, d):
    return _safe_exp(p[0] + p[1] * (np.log(np.maximum(d, 1.0)) - math.log(D_REF)))


def _rate_hill(p, d):
    # Same overflow-proof spelling as `_mu_hill`; see the note beside it.
    logit = p[2] * (p[1] - np.log(np.maximum(d, 1.0)))
    return _safe_exp(p[0]) / (1.0 + _safe_exp(logit))


NATIONAL_FORMS = {
    "constant_rate": (("log_r0",), _rate_const, False),
    "rate_power": (("log_r0", "b"), _rate_power, True),
    "rate_hill": (("log_rmax", "log_k", "b"), _rate_hill, True),
}
NATIONAL_BASELINE = "constant_rate"


def national_rate(form: str, params, density):
    d = np.asarray(density, dtype=float)
    return np.maximum(NATIONAL_FORMS[form][1](np.asarray(params, dtype=float), d), 1e-12)


def _national_init(form: str, rate0: float) -> list[list[float]]:
    r = math.log(max(rate0, 1e-6))
    if form == "constant_rate":
        return [[r]]
    if form == "rate_power":
        return [[r, 0.0], [r, 0.2], [r, -0.2]]
    return [[r + 1, math.log(D_REF), 1.0], [r + 2, math.log(D_REF * 3), 0.7],
            [r + 0.5, math.log(D_REF / 3), 1.3]]


def _national_bounds(form: str, d) -> list[tuple[float, float]]:
    """Box constraints for the national rate forms.

    Without them `rate_hill` walks the same degenerate ridge the NYC Hill does
    (log_rmax and log_k both to infinity with the ratio fixed), which is a valid
    fit, an unreadable parameter, and -- as of the first run -- an OverflowError
    the moment the report tries to exponentiate it. rmax is capped at 1,000 per
    1,000 residents (every shop in the ZCTA being one category), K inside the
    observed density range widened 1,000x, and the exponent in [0.02, 6].
    """
    lo = math.log(max(float(np.min(d)), 1e-3))
    hi = math.log(max(float(np.max(d)), 1.0))
    wide = math.log(1_000.0)
    if form == "constant_rate":
        return [(-20.0, math.log(1_000.0))]
    if form == "rate_power":
        return [(-20.0, math.log(1_000.0)), (-6.0, 6.0)]
    return [(-20.0, math.log(1_000.0)), (lo - wide, hi + wide), (0.02, 6.0)]


def fit_national_form(form: str, pop, density, estab) -> tuple[list[float], float]:
    from scipy.optimize import minimize
    pop = np.asarray(pop, dtype=float)
    d = np.asarray(density, dtype=float)
    y = np.asarray(estab, dtype=float)
    offset = pop / 1000.0
    rate0 = float(np.sum(y) / max(np.sum(offset), 1e-9))
    bounds = _national_bounds(form, d)
    blo = np.array([b[0] for b in bounds])
    bhi = np.array([b[1] for b in bounds])

    def obj(p):
        p = np.asarray(p, float)
        if np.any(p < blo) or np.any(p > bhi) or not np.all(np.isfinite(p)):
            return 1e18
        mu = np.maximum(offset * national_rate(form, p, d), 1e-9)
        if not np.all(np.isfinite(mu)):
            return 1e18
        return poisson_nll2(y, 1.0, mu)

    best, best_val = None, np.inf
    for p0 in _national_init(form, rate0):
        p0 = [min(max(v, lo), hi) for v, (lo, hi) in zip(p0, bounds, strict=True)]
        res = minimize(obj, np.asarray(p0, float), method="Nelder-Mead",
                       options={"maxiter": 3000, "xatol": 1e-7, "fatol": 1e-7})
        if res.fun < best_val:
            best, best_val = list(map(float, res.x)), float(res.fun)
    return best, best_val


def build_national_zcta(year: int = 2023, acs_year: int = 2023,
                        require_cbp_presence: bool = False) -> pd.DataFrame:
    """One row per (ZCTA, category) inside a metropolitan statistical area of at
    least 500k residents: population, land area, density, CBP establishments.

    ABSENCE SEMANTICS -- this choice decides the answer, so it is a parameter
    and not a hard-coded assumption. CBP omits a (ZCTA, NAICS) row when the cell
    is zero, and the census_zbp probe found no ESTAB suppression flag ever set
    (Census suppresses employment and payroll, not establishment counts), so the
    default reads an absent row as a TRUE ZERO and keeps every ZCTA with at
    least 1,000 residents: 10,197 ZCTAs, 226M people.

    `require_cbp_presence=True` is the sensitivity: it drops the 1,775 ZCTAs
    (7.7M people, 3.4% of the universe) that have no establishment in ANY of
    the 15 categories. That is the defensible-but-conservative universe, and it
    moves the answer in a known direction -- dropping low-density true zeros
    raises the fitted rate at low density, flattens the density slope, and
    therefore UNDER-states how far above the national curve NYC sits. Both are
    run and both are reported.
    """
    from loci.sources.universal import census_cbp_national as C

    zbp = C.fetch_zbp_zcta(year)
    acs = C.fetch_acs_zcta(acs_year)
    land = C.fetch_zcta_land_area(year)
    z2c = C.zcta_county_crosswalk()
    xw = C.fetch_cbsa_crosswalk(year)
    msa = C.fetch_acs_msa(acs_year)

    metros = msa[(msa["population"] >= MIN_METRO_POP)][["cbsa", "cbsa_name", "population"]]
    xw = xw[xw["metro_micro"] == "Metropolitan Statistical Area"]
    geo = (z2c.merge(xw[["county_fips", "cbsa"]], on="county_fips", how="inner")
              .merge(metros[["cbsa", "cbsa_name"]], on="cbsa", how="inner"))

    base = (geo.merge(acs, on="zipcode", how="inner")
               .merge(land, on="zipcode", how="inner"))
    base = base[(base["population"] >= MIN_ZCTA_POP) & (base["land_sqmi"] > 0)].copy()
    base["land_km2"] = base["land_sqmi"] * SQMI_TO_KM2
    base["density"] = base["population"] / base["land_km2"]

    est = (zbp.groupby(["zipcode", "category"], as_index=False)["estab"].sum())
    if require_cbp_presence:
        base = base[base["zipcode"].isin(set(est["zipcode"].unique()))].copy()

    grid = base.assign(key=1).merge(
        pd.DataFrame({"category": list(CATEGORIES), "key": 1}), on="key").drop(columns="key")
    out = grid.merge(est, on=["zipcode", "category"], how="left")
    out["estab"] = out["estab"].fillna(0.0)
    return out[["zipcode", "cbsa", "cbsa_name", "county_fips", "population",
                "households", "median_hh_income", "land_km2", "density",
                "category", "estab"]]


def fit_national(panel: pd.DataFrame, hold_out_cbsa: str = NYC_CBSA,
                 seed: int = RNG_SEED) -> dict:
    """Per category: fit rate(density) on every large metro EXCEPT `hold_out_cbsa`,
    then score the held-out metro against it.

    NYC is excluded from its own comparator on purpose. It is the single
    densest and one of the largest metros in the country; leaving it in lets it
    pull the curve toward itself and then reports the shrunken residual as
    "NYC is normal". Held out, "NYC sits 2.3x above the national curve for
    laundromats" is an out-of-sample statement.
    """
    out: dict[str, dict] = {}
    train_all = panel[panel["cbsa"] != hold_out_cbsa]
    for cat in CATEGORIES:
        tr = train_all[train_all["category"] == cat]
        ho = panel[(panel["cbsa"] == hold_out_cbsa) & (panel["category"] == cat)]
        if len(tr) < 500:
            out[cat] = {"fitted": False, "reason": f"only {len(tr)} training ZCTAs"}
            continue
        pop, d, y = (tr["population"].to_numpy(float), tr["density"].to_numpy(float),
                     tr["estab"].to_numpy(float))
        folds = nta_folds(tr["cbsa"].to_numpy(), n_folds=N_FOLDS_NATIONAL, seed=seed)

        scores, base_cv = {}, None
        for form in NATIONAL_FORMS:
            cv = []
            for test in folds:
                mask = np.ones(len(y), dtype=bool)
                mask[test] = False
                p, _ = fit_national_form(form, pop[mask], d[mask], y[mask])
                mu = (pop[test] / 1000.0) * national_rate(form, p, d[test])
                cv.append(poisson_deviance(y[test], np.maximum(mu, 1e-9)) / max(len(test), 1))
            scores[form] = {"cv_folds": [float(v) for v in cv],
                            "cv_mean": float(np.mean(cv))}
            if form == NATIONAL_BASELINE:
                base_cv = cv
        base_mean = scores[NATIONAL_BASELINE]["cv_mean"]
        best, best_gain = NATIONAL_BASELINE, 0.0
        for form in NATIONAL_FORMS:
            if form == NATIONAL_BASELINE:
                continue
            cv = scores[form]["cv_folds"]
            wins = int(sum(1 for a, b in zip(cv, base_cv, strict=True) if a < b))
            gain = (base_mean - scores[form]["cv_mean"]) / base_mean if base_mean > 0 else 0.0
            scores[form].update(folds_beating_baseline=wins,
                                deviance_gain_vs_baseline=float(gain),
                                passes_gate=bool(wins >= MIN_FOLDS_BEATEN
                                                 and gain >= MIN_DEVIANCE_GAIN))
            if scores[form]["passes_gate"] and gain > best_gain:
                best, best_gain = form, gain

        params, _ = fit_national_form(best, pop, d, y)
        q = {f"p{int(v*100)}": float(np.quantile(d, v)) for v in (0.1, 0.5, 0.9, 0.99)}
        rec = {
            "fitted": True, "form": best,
            "density_responsive": best != NATIONAL_BASELINE,
            "params": unpack_named(NATIONAL_FORMS[best][0], params),
            "n_zctas": len(tr), "n_metros": int(tr["cbsa"].nunique()),
            "cv": scores,
            "density_quantiles": q,
            "rate_per_1000_at": {k: float(national_rate(best, params, [v])[0])
                                 for k, v in q.items()},
        }
        if len(ho):
            obs = float(ho["estab"].sum())
            pred = float(np.sum(ho["population"].to_numpy(float) / 1000.0
                                * national_rate(best, params, ho["density"].to_numpy(float))))
            rec["held_out_metro"] = {
                "cbsa": hold_out_cbsa,
                "observed_estab": obs,
                "predicted_estab": pred,
                "ratio_observed_over_predicted": obs / pred if pred > 0 else None,
                "observed_per_1000": obs / (ho["population"].sum() / 1000.0),
                "predicted_per_1000": pred / (ho["population"].sum() / 1000.0),
                "n_zctas": len(ho),
            }
        out[cat] = rec
    return out


def unpack_named(names: tuple[str, ...], params) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, v in zip(names, params, strict=True):
        out[name.removeprefix("log_")] = (
            float(math.exp(v)) if name.startswith("log_") else float(v))
    return out


def metro_table(panel: pd.DataFrame) -> pd.DataFrame:
    """One row per metro: population, population-weighted density, and
    establishments per 1,000 residents for each category.

    Population-WEIGHTED density (sum(pop_i * dens_i) / sum(pop_i) over the
    metro's ZCTAs), never land-area density: the Phoenix MSA includes desert and
    the Riverside MSA includes Joshua Tree, and a simple pop/area figure ranks
    metros by how much empty land their counties happen to enclose rather than
    by how densely their residents actually live.
    """
    z = panel.drop_duplicates(["zipcode"])[["zipcode", "cbsa", "cbsa_name",
                                            "population", "density"]]
    agg = z.groupby(["cbsa", "cbsa_name"]).apply(
        lambda g: pd.Series({
            "population": g["population"].sum(),
            "weighted_density": float(np.average(g["density"], weights=g["population"])),
            "n_zctas": len(g),
        }), include_groups=False).reset_index()
    est = (panel.groupby(["cbsa", "category"], as_index=False)["estab"].sum()
                .pivot(index="cbsa", columns="category", values="estab").fillna(0.0))
    out = agg.merge(est, on="cbsa", how="left")
    for cat in CATEGORIES:
        if cat in out.columns:
            out[f"{cat}_per_1000"] = out[cat] / (out["population"] / 1000.0)
    return out


DENSE_SUPPORT_KM2 = 5_000.0     # roughly the 10th percentile of MN+BK walksheds


def metro_dense_support(panel: pd.DataFrame,
                        threshold: float = DENSE_SUPPORT_KM2) -> pd.DataFrame:
    """Per metro: the share of residents living in ZCTAs at or above `threshold`
    residents per km2, and how many people that is.

    THIS IS THE CITY-TWO SCREEN, and it is a different question from "which
    metro looks most like New York on average". The NYC curve was estimated on
    400 m walksheds holding 2,300-26,000 people; a metro whose every ZCTA sits
    at 600/km2 has NO territory where that curve is even in support, however
    similar its retail mix happens to look in aggregate. A metro with a small
    but genuinely dense core -- Chicago's North Side, Boston, San Francisco --
    has somewhere to start, and the honest answer to "what can other cities
    learn from NYC" begins with how much of the city is on the same axis at all.
    """
    z = panel.drop_duplicates(["zipcode"])[["cbsa", "cbsa_name", "population",
                                            "density"]]
    out = []
    for (cbsa, name), g in z.groupby(["cbsa", "cbsa_name"]):
        dense = g[g["density"] >= threshold]
        out.append({"cbsa": cbsa, "cbsa_name": name,
                    "population": float(g["population"].sum()),
                    "dense_population": float(dense["population"].sum()),
                    "dense_share": float(dense["population"].sum()
                                         / max(g["population"].sum(), 1.0)),
                    "n_dense_zctas": len(dense)})
    return pd.DataFrame(out).sort_values("dense_population", ascending=False)


def nearest_metros(metros: pd.DataFrame, target: str = NYC_CBSA,
                   k: int = 5, density_weight: float = 1.0) -> pd.DataFrame:
    """The metros most like NYC on the carrying-capacity surface.

    The feature vector is log density plus the log per-1,000 rate of all 15
    categories, z-scored across metros, so a metro is "near" NYC when its RETAIL
    MIX AND its density both look like NYC's -- not merely when it is big. Every
    feature is logged first because the rates span two orders of magnitude and a
    raw Euclidean distance would be the restaurant rate and nothing else.
    """
    cols = ["weighted_density"] + [f"{c}_per_1000" for c in CATEGORIES
                                   if f"{c}_per_1000" in metros.columns]
    X = np.log(np.maximum(metros[cols].to_numpy(float), 1e-6))
    X = (X - X.mean(axis=0)) / np.maximum(X.std(axis=0), 1e-9)
    # Density is ONE column against fifteen mix columns, so at equal weight it
    # contributes 1/16th of the distance and the "nearest" metros come back as
    # whichever ones sit near the middle of the mix cloud -- Houston, Atlanta,
    # San Antonio -- at a seventh of New York's density. `density_weight` scales
    # that column so the ranking can be read either way, and the doc reports
    # both rather than picking one and calling it the answer.
    w = np.ones(X.shape[1])
    w[0] = density_weight
    dist = np.sqrt((((X - X[np.flatnonzero(metros["cbsa"].values == target)[0]])
                     * w) ** 2).sum(axis=1))
    out = metros.assign(distance_to_target=dist).sort_values("distance_to_target")
    return out[out["cbsa"] != target].head(k)[
        ["cbsa", "cbsa_name", "population", "weighted_density", "distance_to_target"]]


def cbp_poi_ratio(con, boroughs=BOROUGHS) -> dict[str, dict]:
    """POI count / CBP establishments per category on the NYC ZIP partition --
    the conversion between Part 1's units and Part 2's, and a portability
    parameter in its own right.

    Reuses `model.zbp_compare.build_coverage_check` in its write=False mode on
    the PRINCIPLED supply set, so the numerator is exactly the set the NYC curve
    was fitted on. A city without New York's licence rosters will not reproduce
    this ratio, and how far it misses is how far its POI census differs from a
    payroll census.
    """
    from loci.model import zbp_compare

    # `zbp_compare._zip_boroughs` labels a ZIP with the FULL borough name off
    # `analysis.hex.borough` ("Manhattan"), while everything at the address grain
    # uses the two-letter code ("MN"). Passing the codes straight through
    # silently matched zero ZIPs and returned an empty bridge -- which looked
    # exactly like "no overlap between Loci and CBP" rather than like a join bug.
    zbp_compare.build_coverage_check(con, None, supply_set="principled",
                                     boroughs=tuple(BOROUGH_NAMES[b] for b in boroughs),
                                     write=False)
    df = con.execute("SELECT * FROM _zcc_last").df()
    out: dict[str, dict] = {}
    for cat, g in df.groupby("category"):
        poi, cbp = float(g["poi_count"].sum()), float(g["zbp_estab"].sum())
        med = g["ratio"].replace([np.inf, -np.inf], np.nan).dropna()
        out[cat] = {
            "poi_principled": poi,
            "cbp_estab": cbp,
            "ratio_aggregate": poi / cbp if cbp > 0 else None,
            "ratio_median_zip": float(med.median()) if len(med) else None,
            "n_zips": int(g["zipcode"].nunique()),
        }
    return out


# ===========================================================================
# the whole document
# ===========================================================================

def run_all(con, boroughs=BOROUGHS, bootstrap: int = BOOTSTRAP_B,
            categories=None, progress=None, year: int = 2023) -> dict:
    """The NYC fit, the national fit, the metro table, NYC's nearest metros and
    the CBP-to-POI bridge, assembled into the document `loci capacity` reads.

    Order matters only in one place: the national half is fitted with NYC HELD
    OUT, so `national[cat]['held_out_metro']` is an out-of-sample statement
    about New York rather than a residual from a curve New York helped draw.
    """
    doc = run_fit(con, boroughs, bootstrap, categories, progress)

    panel = build_national_zcta(year, require_cbp_presence=False)
    strict = build_national_zcta(year, require_cbp_presence=True)
    nat = fit_national(panel)
    nat_strict = fit_national(strict)
    metros = metro_table(panel)
    near = nearest_metros(metros, NYC_CBSA, k=5)

    ratios = cbp_poi_ratio(con, boroughs)

    nyc_row = metros[metros["cbsa"] == NYC_CBSA]
    nyc_density = float(nyc_row["weighted_density"].iloc[0]) if len(nyc_row) else None
    for cat, rec in nat.items():
        if rec.get("fitted") and nyc_density:
            rec["per_1000_at_density"] = float(
                national_rate(rec["form"], _repack_national(rec["form"], rec["params"]),
                              [nyc_density])[0])
        s = nat_strict.get(cat, {})
        if rec.get("fitted") and s.get("fitted") and s.get("held_out_metro"):
            rec["sensitivity_cbp_presence_only"] = {
                "form": s["form"],
                "nyc_ratio_observed_over_predicted":
                    s["held_out_metro"]["ratio_observed_over_predicted"],
                "n_zctas": s["n_zctas"],
            }

    doc["national"] = nat
    doc["national_universe"] = {
        "year": year, "grain": "ZCTA inside an MSA of >= 500k residents",
        "source": "Census CBP 2023 (ESTAB) + ACS 2023 5-year + 2023 Gazetteer",
        "n_zctas": int(panel["zipcode"].nunique()),
        "n_metros": int(panel["cbsa"].nunique()),
        "population": float(panel.drop_duplicates("zipcode")["population"].sum()),
        "held_out_metro": NYC_CBSA,
        "absent_cbp_row_read_as": "zero",
        "n_zctas_strict": int(strict["zipcode"].nunique()),
    }
    doc["nearest_metros"] = near.to_dict(orient="records")
    doc["cbp_poi_ratio"] = ratios
    return doc


def _repack_national(form: str, named: dict[str, float]) -> list[float]:
    out = []
    for p in NATIONAL_FORMS[form][0]:
        out.append(math.log(float(named[p[4:]])) if p.startswith("log_")
                   else float(named[p]))
    return out


def national_at(fit: dict, category: str, density: float) -> float | None:
    """Establishments per 1,000 residents the national curve expects at this
    density -- the number that sits beside NYC's in `loci capacity`."""
    rec = (fit.get("national") or {}).get(category)
    if not rec or not rec.get("fitted"):
        return None
    return float(national_rate(rec["form"], _repack_national(rec["form"], rec["params"]),
                               [density])[0])


# ===========================================================================
# the third denominator: establishments per $1M of resident spend
# ===========================================================================

def spend_per_1000_residents(category: str, persons_per_household: float,
                             income_index: float = 1.0) -> dict | None:
    """Annual category spend, in dollars, generated by 1,000 residents.

    A THIRD denominator beside residents and homes, and the one an operator
    actually thinks in: 1,000 people in Bay Ridge and 1,000 people in Tribeca do
    not buy the same amount of anything. It is a TRANSFORMATION of the fitted
    per-1,000-resident rate, not a separate fit -- the curve is estimated once,
    on counts, and re-expressed here -- so it adds an assumption (the CEX
    household figure) without adding a degree of freedom.

    Reads `src/loci/spend.yaml`, which model/revenue.py already owns: annual
    spend per HOUSEHOLD by category, scaled by `income_elasticity` against the
    quintile income index exactly as D81's `spend_vector` does. Households are
    residents / persons-per-household.

    Returns None for a category spend.yaml does not carry, rather than a
    guessed figure -- a fabricated denominator would silently rescale the whole
    column.
    """
    doc = yaml.safe_load((PKG_ROOT / "spend.yaml").read_text())
    cat = (doc.get("categories") or {}).get(category)
    if not cat or cat.get("annual_spend") is None:
        return None
    base = float(cat["annual_spend"])
    eta = float(cat.get("income_elasticity", 0.0))
    per_hh = base * (1.0 + eta * (income_index - 1.0))
    households = 1000.0 / max(persons_per_household, 0.1)
    return {"annual_spend_per_household": per_hh,
            "households_per_1000_residents": households,
            "spend_per_1000_residents": per_hh * households,
            "source": cat.get("source"),
            "reliable": bool(cat.get("reliable", False))}


def per_million_spend(estab_per_1000_residents: float, category: str,
                      persons_per_household: float,
                      income_index: float = 1.0) -> float | None:
    """Establishments per $1M of annual resident spend on that category."""
    s = spend_per_1000_residents(category, persons_per_household, income_index)
    if not s or s["spend_per_1000_residents"] <= 0:
        return None
    return estab_per_1000_residents / (s["spend_per_1000_residents"] / 1e6)
