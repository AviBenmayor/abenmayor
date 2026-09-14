"""THE FORECAST LEDGER — the modelled layer, issued as dated, scoreable claims.

Owner's ask (2026-09-14): "almost feels like we are building multiple layers
here: predicted/modeled (not what the world reflects but what it could) vs
realized/actual. worth building this out further."

The screen (`analysis.address_category`) is the REALIZED layer: what the data
reads at a doorway today. This module is the MODELLED one, and the whole
difference between a model and an opinion is that a model is frozen on a date
and scored afterwards. So: `analysis.forecast` (what we said, when, with which
model, off which frozen inputs), `analysis.forecast_outcome` (what happened),
and a track record that includes the vintages that did badly.

Schema and the long-form reasoning: `src/loci/sql/028_forecast.sql`.

===========================================================================
THE SPEC, WRITTEN BEFORE THE FIT
===========================================================================

TARGET.  y[a, c, t] = 1 if at least one same-category storefront in the
principled supply set has a first-seen date (source_date | gov_filing) inside
[t, t + 12 months) within 400 m STRAIGHT-LINE of address a.  A disc-level
BINARY, not a count — see sql/028 "THE UNIT" for why a Poisson rate on the
count would multiply-count one storefront across hundreds of overlapping discs
and would make the NTA residual sum meaningless.

    expected_openings = p_opening x 1.

FEATURES, all frozen at the first day of the issue month, all straight-line
400 m in EPSG:32618, all reconstructed from the first-seen ledger so that
NOTHING DATED ON OR AFTER THE ISSUE MONTH CAN ENTER:

    log_score      log1p(supply_ratio_t0), where supply_ratio_t0 is own-category
                   principled supply per 1,000 homes divided by the frame's own
                   per-category median at t0 (the ANCHOR, below)
    own_gap_flag   1 if zero same-category competitors within 400 m at t0
    log_homes      log(1 + PLUTO units_capped within 400 m straight-line)
    retail_index   D82 neighbourhood character at the address
    category       fixed effect (pooled model) / the model's own scope (fitted)

WITHHELD ON PURPOSE: log_jobs and log_transit. The retrodiction fitted them at
+0.114 [0.003, 0.224] and +0.022 [0.003, 0.040] — intervals that barely clear
zero — against out-of-sample residual Moran's I of 0.64-0.77. Cluster-robust
standard errors on 103 NTAs assume independence ACROSS NTAs and that assumption
is visibly false, so two coefficients whose significance depends on it are not
shipped into a forecast.

FORM.  Logistic. Not linear (a probability must saturate, and the outcome rate
runs from 1% to 91% across categories), not a gradient-booster (100 NTAs is the
real degrees of freedom, a four-feature logit cannot memorise them, and the
coefficient IS the deliverable). Two stages, exactly as the retrodiction
reported it:

    POOLED   one logit over all fifteen categories with category fixed effects.
    FITTED   for each category clearing SUPPORT_FLOOR dated openings in the fit
             window, its own logit on its own rows.

A category with its own model is marked `support='fitted'`; the rest are
predicted by the pooled model and marked `support='pooled'`. Per-category
slopes are NOT a refinement, they are a necessity: the retrodiction measured
+5.20 for restaurant against +1.29 for hair_barber, and a single pooled slope
would be wrong for both.

FIT WINDOW — one rule, every vintage, walk-forward:

    for a vintage issued at month M with horizon H = 12,
    fit on TWO stacked folds with t0 in {M - 24 months, M - 12 months},
    each fold carrying features frozen at ITS OWN t0 and the outcome observed
    over ITS OWN following 12 months.

Every observation that enters a fit therefore has a source date strictly BEFORE
M. That is the leakage contract; `tests/test_forecast.py` pins it against a
synthetic ledger row dated after M. Two folds rather than one because a single
12-month outcome window is thin in the thin categories, and non-overlapping
rather than a rolling window because overlapping outcome windows would count
the same opening twice on the same address.

THE ANCHOR.  `base_median[c, t0]` — the denominator that turns a supply count
into a ratio — is computed on ONE deterministic 12,000-address hash sample of
the lot frame, at every t0, for fit rows and prediction rows alike. Computing
it on the fit sample and then applying it to the full frame would shift the
feature between fitting and predicting; that is the quiet version of leakage
and it is the failure mode that looks like skill.

WHY 12,000 ADDRESSES FOR THE FIT AND 281,842 FOR THE PREDICTION. The retrodiction's
reasoning, unchanged: the lot frame's 400 m discs overlap almost completely, so
the marginal information in address 12,001 is close to zero while the join cost
is not. Prediction is cheap per row and must cover every doorway (owner,
2026-09-13: no eligibility gate — every street is represented), so it runs on
the whole frame.

===========================================================================
THE BASELINES IT MUST BEAT, AND THE FAILURE CRITERION
===========================================================================

Three baselines, on the same NTA-blocked folds:

    NO-SCORE      the same two-stage design with log_score and own_gap_flag
                  removed — log_homes + retail_index + category. THIS IS THE
                  BAR. The retrodiction's first draft headlined +0.048 against
                  a homes-only comparator; the statistician's correction showed
                  density + character + category FE alone reach 0.854, so the
                  honest marginal contribution was +0.013. The flattering
                  comparator is not used again.
    PERSISTENCE   rank by whether the disc got a same-category opening in the
                  TWELVE MONTHS BEFORE t0. Available at issue time, free, and
                  the thing a sceptic would actually do. Openings cluster in
                  space and in time, so this is a real bar, not a straw man.
    HOMES-ONLY    reported for continuity with the retrodiction memo. Never the
                  bar.

FAILURE CRITERION, fixed before any vintage was issued. A run is stamped
`ships = false` if ANY of:

    (a) blocked-CV AUC <= the NO-SCORE baseline;
    (b) blocked-CV AUC <= the PERSISTENCE baseline;
    (c) out-of-sample calibration max decile gap > 15 percentage points.

A failing vintage is STILL WRITTEN, still dated and still scored. Deleting a
vintage that failed is how a track record becomes a highlight reel, and the
whole point of a ledger is that it cannot be edited into flattery.

===========================================================================
THE HONESTY GUARDRAILS (D1 and D88), both kept
===========================================================================

D1: retail is the DEPENDENT read, never a predictor of growth. Openings are the
left-hand side here; nothing is regressed on future retail.

D88: this forecasts ENTRY, not VIABILITY. `p_opening` is the probability the
MARKET acts near this doorway, and the retrodiction showed entry going where
supply was ALREADY THICK — consistent with agglomeration economies being real
and equally consistent with herding into saturated corridors. Business-level
survival is not identified in Loci's data, and the one premises-level outcome
that is (LL157 go-dark) returns a null whose sign flips with the definition of
attrition. A high p_opening therefore says "likely to happen", never "likely to
work", and `loci forecast report` prints that sentence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib

import numpy as np
import pandas as pd

from loci.categories import CATEGORIES

PKG = pathlib.Path(__file__).resolve().parents[1]
SQL_028 = PKG / "sql" / "028_forecast.sql"

#: Semantic version of the FORM. Bump the minor when the functional form or the
#: fit-window rule changes; the feature hash below catches everything else.
MODEL_SEMVER = "0.1.0"

#: The forecast horizon, in months. Twelve, and the reason is measurement, not
#: taste: `first_seen_src_date` is a licence, an inspection or a Foursquare
#: minting date, which D80 puts 221-259 days away from fitout. A 3- or 6-month
#: horizon would be dominated by error in the DATING of the outcome rather than
#: by anything about the place. Twelve months is long relative to that error and
#: short enough that a vintage can be scored inside a project's lifetime.
HORIZON_MONTHS = 12

#: Straight-line, EPSG:32618, everywhere — features, anchor and outcome alike.
#: sql/028 states the sign of the bias this buys.
RADIUS_M = 400.0
CRS_METRIC = "EPSG:32618"

FRAME = "lot"
BOROUGHS_CODE = ("MN", "BK")
BOROUGHS_FULL = ("Manhattan", "Brooklyn")

ALL_CATEGORIES: tuple[str, ...] = tuple(CATEGORIES)

#: Addresses in the deterministic fit sample AND in the anchor sample. See the
#: module docstring. Ordered by hash(address_id), never by RANDOM().
FIT_SAMPLE_N = 12_000

#: A category gets its OWN logit when it has at least this many dated openings
#: in the fit window. Four free parameters at the conventional ten-events-per-
#: parameter floor is 40 events on the rarer side of the outcome; 150 openings
#: is where that holds with room, given that the binary is on the DISC and the
#: rarer side is whichever of open/not-open is smaller.
SUPPORT_FLOOR = 150

#: Pre-declared failure criterion. See the module docstring.
MAX_CALIBRATION_GAP = 0.15

N_FOLDS = 5
RNG_SEED = 20260914

#: The variance cluster for the NTA surprise z: a grid square twice the
#: catchment radius, so two addresses in different cells cannot share a 400 m
#: disc except across a boundary.
SURPRISE_CELL_M = 800.0

FEATURE_LIST: tuple[str, ...] = ("log_score", "own_gap_flag", "log_homes",
                                 "retail_index")
NO_SCORE_FEATURES: tuple[str, ...] = ("log_homes", "retail_index")
HOMES_ONLY_FEATURES: tuple[str, ...] = ("log_homes",)

FIT_WINDOW_RULE = (
    "two stacked folds, t0 in {issued_month - 24 months, issued_month - 12 "
    "months}; each fold's features frozen at its own t0 and its outcome "
    "observed over its own following 12 months. Nothing dated on or after "
    "issued_month enters the fit.")


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------
def model_version(semver: str = MODEL_SEMVER, *,
                  features: tuple[str, ...] = FEATURE_LIST,
                  horizon: int = HORIZON_MONTHS,
                  radius_m: float = RADIUS_M,
                  support_floor: int = SUPPORT_FLOOR) -> str:
    """`<semver>+<8 hex>`, the hex over everything that defines the model.

    Two runs that share a version share a model. The database cannot check
    that, so it is made true by construction: the hash covers the exact feature
    list IN ORDER, the fit-window rule, the horizon, the radius and the support
    floor. Change any of them and the version changes without anyone
    remembering to bump it — which is the only version discipline that
    survives contact with a hurried session.
    """
    payload = json.dumps({
        "semver": semver,
        "features": list(features),
        "fit_window_rule": FIT_WINDOW_RULE,
        "horizon_months": int(horizon),
        "radius_m": float(radius_m),
        "support_floor": int(support_floor),
        "form": "two-stage logit: pooled with category FE, per-category above "
                "the support floor",
        "target": "1{>=1 same-category dated first-seen within radius in the "
                  "horizon}",
    }, sort_keys=True)
    return f"{semver}+{hashlib.sha256(payload.encode()).hexdigest()[:8]}"


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------
def ensure_schema(con) -> None:
    """Apply sql/028_forecast.sql. Idempotent, and WRITE-ONLY — DuckDB refuses
    CREATE TABLE IF NOT EXISTS on a read-only handle, so the read paths call
    `require_schema` instead."""
    con.execute(SQL_028.read_text())


def require_schema(con) -> None:
    try:
        con.execute("SELECT 1 FROM analysis.forecast LIMIT 1")
    except Exception as exc:            # noqa: BLE001 -- duckdb raises several
        raise RuntimeError(
            "analysis.forecast does not exist yet. Run "
            "`loci forecast issue --month YYYY-MM`, which applies "
            "sql/028_forecast.sql.") from exc


#: A peer session holding the warehouse write lock is the NORMAL state of this
#: project (D69), not an error, and a forecast vintage is precisely the kind of
#: thing that must not be written to a throwaway copy. 45 minutes of patience,
#: polled every 45 s: long enough to outlast a validation run or a warehouse
#: rebuild, and it fails loudly rather than quietly working somewhere that gets
#: discarded.
WRITE_RETRIES = 60
WRITE_WAIT_S = 45.0


def connect_write(path=None, retries: int = WRITE_RETRIES,
                  wait_s: float = WRITE_WAIT_S):
    """Re-exported from model/poi_presence rather than re-implemented: a second
    copy of the retry policy is how the two eventually disagree about how long
    to wait, and a ledger that gives up early is a ledger with a hole in it.

    The DEFAULTS are longer here than poi_presence's ten minutes because the
    expensive half of `issue` (the fit and the four-million-row prediction) runs
    BEFORE the first write — so by the time this is called there is a finished
    vintage in memory and abandoning it costs the whole run."""
    from loci.model.poi_presence import connect_write as _cw

    return _cw(path, retries=retries, wait_s=wait_s)


def connect_read(read_only: bool = True, retries: int = WRITE_RETRIES,
                 wait_s: float = WRITE_WAIT_S):
    """A patient READ handle.

    DuckDB's single-file lock is exclusive: while a peer session holds the
    warehouse for writing, a read_only connection is refused too — the lock is
    on the FILE, not on the transaction. `retrodiction.connect` gives up after
    six short attempts, which is right for an interactive research command and
    wrong for a job that is going to run for ten minutes anyway. So this waits
    the same 45 minutes the write handle does.

    Copying the file and reading the copy is NOT an option and the reason is
    not tidiness: a peer mid-write produces a torn snapshot, and a vintage
    fitted on a torn snapshot is frozen, dated, and wrong forever."""
    import time

    from loci import db as locidb

    last = None
    for i in range(retries):
        try:
            return locidb.connect(read_only=read_only)
        except Exception as exc:            # noqa: BLE001 -- duckdb raises several
            last = exc
            if i < retries - 1:
                time.sleep(wait_s)
    raise RuntimeError(
        f"the warehouse stayed locked for {retries * wait_s / 60:.0f} minutes "
        f"({last}). A peer session is holding it.")


def validate_month(month: str) -> None:
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"month must be YYYY-MM, got {month!r}") from exc


def month_first(month: str) -> dt.date:
    """The FIRST day of the month. Features are frozen here — not the last day,
    because 'issued in 2026-09' must not have seen anything that happened
    during 2026-09."""
    validate_month(month)
    y, m = (int(p) for p in month.split("-"))
    return dt.date(y, m, 1)


def add_months(d: dt.date, n: int) -> dt.date:
    total = (d.year * 12 + d.month - 1) + n
    return dt.date(total // 12, total % 12 + 1, 1)


def month_str(d: dt.date) -> str:
    return d.strftime("%Y-%m")


def fit_t0s(issued_month: str, horizon: int = HORIZON_MONTHS) -> list[dt.date]:
    """The two training fold origins. See FIT_WINDOW_RULE."""
    m0 = month_first(issued_month)
    return [add_months(m0, -2 * horizon), add_months(m0, -horizon)]


def current_month(today: dt.date | None = None) -> str:
    return (today or dt.date.today()).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# 1. the frames
# ---------------------------------------------------------------------------
POINTS_SQL = """
SELECT a.address_id AS point_id, a.lon, a.lat, a.nta_code, a.borough,
       c.retail_index
FROM analysis.address a
LEFT JOIN analysis.address_character c USING (address_id)
WHERE a.frame = '{frame}'
  AND a.borough IN ({boroughs})
  AND a.lon IS NOT NULL AND a.lat IS NOT NULL
ORDER BY hash(a.address_id)
{limit}
"""


def load_points(con, *, limit: int | None = None, frame: str = FRAME) -> pd.DataFrame:
    """The lot frame, hash-ordered so `limit` is a DETERMINISTIC sample.

    `ORDER BY hash(address_id)` and never `RANDOM()`: the 12,000-address fit
    sample and the 12,000-address anchor sample must be the SAME 12,000
    addresses on every run, or the base median moves under the model between
    the fit and the prediction."""
    sql = POINTS_SQL.format(
        frame=frame,
        boroughs=", ".join(f"'{b}'" for b in BOROUGHS_CODE),
        limit=f"LIMIT {int(limit)}" if limit else "")
    return con.execute(sql).fetchdf()


def homes_within(con, points: pd.DataFrame, radius_m: float = RADIUS_M,
                 frame: str = FRAME) -> pd.DataFrame:
    """PLUTO residential units within `radius_m` STRAIGHT-LINE of each point.

    ANACHRONISM, STATED: `units_capped` is present-day PLUTO, so a building
    completed in 2024 is credited to a 2023 vintage. It enters as a CONTROL and
    never as the tested variable, and the direction of the bias is toward the
    growth areas — i.e. it flatters the no-score baseline, not the score."""
    from loci.validation import retrodiction as rd

    src = con.execute(f"""
        SELECT lon, lat, units_capped AS weight FROM analysis.address
        WHERE frame = '{frame}'
          AND borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_CODE)})
          AND units_capped > 0 AND lon IS NOT NULL
    """).fetchdf()
    got = rd.count_within(con, points[["point_id", "lon", "lat"]], src,
                          radius_m=radius_m, by="")
    return got.rename(columns={"wsum": "homes"})[["point_id", "homes"]]


def openings_between(con, points: pd.DataFrame, start: dt.date, end: dt.date,
                     radius_m: float = RADIUS_M,
                     categories: tuple[str, ...] = ALL_CATEGORIES) -> pd.DataFrame:
    """Same-category dated first-seens within the disc, in [start, end).

    THE OUTCOME, and also the persistence baseline when called on the twelve
    months BEFORE t0. One definition, one radius, one projection, used for
    both — so the model and the thing it is scored against cannot drift apart.

    `backfill_censored` rows carry no date and can never be an opening. That is
    right (they are not openings) and it makes the realized rate a uniform
    LOWER BOUND on real entry; sql/028 caveat states the consequence."""
    from loci.validation import retrodiction as rd

    cats = ", ".join(f"'{c}'" for c in categories)
    tgt = con.execute(f"""
        SELECT p.lon, p.lat, p.category
        FROM analysis.poi_presence p
        JOIN analysis.poi_supply s
          ON s.poi_id = p.poi_id_latest AND s.in_principled
        WHERE p.borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_FULL)})
          AND p.category IN ({cats})
          AND p.first_seen_kind IN ('source_date', 'gov_filing')
          AND p.first_seen_src_date >= DATE '{start.isoformat()}'
          AND p.first_seen_src_date <  DATE '{end.isoformat()}'
    """).fetchdf()
    if tgt.empty:
        return pd.DataFrame(columns=["point_id", "category", "n"])
    got = rd.count_within(con, points[["point_id", "lon", "lat"]], tgt,
                          radius_m=radius_m)
    return got[["point_id", "category", "n"]]


def dated_openings_by_category(con, start: dt.date, end: dt.date) -> dict[str, int]:
    """How many dated openings each category actually contributes to a fit
    window. This is the SUPPORT number — the one that decides whether a
    category gets its own model — and it is a count of DECLARATIONS, not of
    openings: a restaurant is inspected by DOHMH and licensed by DCWP, a
    hardware store declares nothing to anybody."""
    rows = con.execute(f"""
        SELECT p.category, count(*) AS n
        FROM analysis.poi_presence p
        JOIN analysis.poi_supply s
          ON s.poi_id = p.poi_id_latest AND s.in_principled
        WHERE p.borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_FULL)})
          AND p.first_seen_kind IN ('source_date', 'gov_filing')
          AND p.first_seen_src_date >= DATE '{start.isoformat()}'
          AND p.first_seen_src_date <  DATE '{end.isoformat()}'
        GROUP BY 1
    """).fetchall()
    return {c: int(n) for c, n in rows}


# ---------------------------------------------------------------------------
# 2. the frozen feature block
# ---------------------------------------------------------------------------
def base_medians(con, anchor: pd.DataFrame, t0: dt.date, *,
                 radius_m: float = RADIUS_M,
                 categories: tuple[str, ...] = ALL_CATEGORIES,
                 include_censored: bool = True) -> dict[str, float]:
    """The per-category supply-per-1k median on the ANCHOR SAMPLE at t0.

    ONE anchor rule for fit rows and prediction rows. If the fit used the fit
    sample's median and the prediction used the whole frame's, `log_score`
    would not mean the same thing on the two sides of the model — the quiet
    kind of leakage, the kind that looks like skill."""
    from loci.validation import retrodiction as rd

    sup = rd.supply_as_of(con, anchor[["point_id", "lon", "lat"]], asof=t0,
                          radius_m=radius_m, include_censored=include_censored,
                          categories=categories)
    homes = homes_within(con, anchor, radius_m=radius_m)
    grid = (anchor[["point_id"]]
            .merge(pd.DataFrame({"category": list(categories)}), how="cross")
            .merge(sup, on=["point_id", "category"], how="left")
            .merge(homes, on="point_id", how="left"))
    grid["supply"] = grid["supply"].fillna(0.0)
    grid = grid[grid["homes"] > 0]
    grid["per_1k"] = grid["supply"] / grid["homes"] * 1000.0
    med = grid.groupby("category")["per_1k"].median().to_dict()
    return {c: float(med.get(c, 0.0)) for c in categories}


def frozen_features(con, points: pd.DataFrame, t0: dt.date, *,
                    anchors: dict[str, float],
                    radius_m: float = RADIUS_M,
                    categories: tuple[str, ...] = ALL_CATEGORIES,
                    include_censored: bool = True,
                    homes: pd.DataFrame | None = None) -> pd.DataFrame:
    """address x category, scored AS OF t0 and knowing nothing after it.

    The leakage rule lives in `retrodiction.supply_as_of`, which is CALLED here
    rather than re-implemented — a second copy of "a competitor whose
    first_seen_src_date is after t0 must not count" is a second place for it to
    be got wrong, and that rule is the one the whole exercise rests on.
    `tests/test_forecast.py` pins it again at this level anyway, because the
    thing being asserted is a property of THIS panel, not of that helper.
    """
    from loci.validation import retrodiction as rd

    sup = rd.supply_as_of(con, points[["point_id", "lon", "lat"]], asof=t0,
                          radius_m=radius_m, include_censored=include_censored,
                          categories=categories)
    if homes is None:
        homes = homes_within(con, points, radius_m=radius_m)

    panel = (points[["point_id"]]
             .merge(pd.DataFrame({"category": list(categories)}), how="cross")
             .merge(sup, on=["point_id", "category"], how="left")
             .merge(homes, on="point_id", how="left")
             .merge(points.drop(columns=["lon", "lat"]), on="point_id", how="left"))
    panel["supply"] = panel["supply"].fillna(0.0)
    panel["homes"] = panel["homes"].fillna(0.0)
    panel["base_median"] = panel["category"].map(anchors).astype(float)

    panel["supply_per_1k"] = np.where(
        panel["homes"] > 0, panel["supply"] / panel["homes"].replace(0, np.nan) * 1000.0, 0.0)
    # A category whose anchor is 0 has no scale to divide by. The ratio is set
    # to 0 rather than to an infinity or a NULL: with a zero median the whole
    # category is empty at t0, every address is equally empty, and log1p(0) = 0
    # correctly says "no information in the ratio here". The `own_gap_flag`
    # still carries the presence/absence, and `support_json` records that the
    # anchor was degenerate so the reader is not left to infer it.
    panel["supply_ratio"] = np.where(
        panel["base_median"] > 0,
        panel["supply_per_1k"] / panel["base_median"].replace(0, np.nan), 0.0)
    panel["supply_ratio"] = panel["supply_ratio"].fillna(0.0)

    panel["log_score"] = np.log1p(panel["supply_ratio"])
    panel["own_gap_flag"] = (panel["supply"] == 0).astype(float)
    panel["log_homes"] = np.log1p(panel["homes"])
    med_ri = panel["retail_index"].median()
    panel["retail_index"] = panel["retail_index"].fillna(
        0.0 if pd.isna(med_ri) else med_ri)
    panel["t0"] = t0
    return panel


def with_surprise_cell(points: pd.DataFrame,
                       cell_m: float = SURPRISE_CELL_M) -> pd.DataFrame:
    """The variance cluster for the NTA z: an 800 m grid square in EPSG:32618.

    Twice the catchment radius, so two addresses in different cells cannot
    share a 400 m disc except across a boundary — which is what makes the
    cluster-robust sandwich in `analysis.forecast_surprise_nta` an honest
    standard error rather than a decorative one."""
    from loci.validation.retrodiction import _project

    x, y = _project(points["lon"].to_numpy(), points["lat"].to_numpy())
    cx = np.floor(np.asarray(x) / cell_m).astype(int)
    cy = np.floor(np.asarray(y) / cell_m).astype(int)
    return points.assign(surprise_cell=[f"{a}:{b}" for a, b in zip(cx, cy)])


# ---------------------------------------------------------------------------
# 3. the fit
# ---------------------------------------------------------------------------
def _design(panel: pd.DataFrame, cols: list[str], cat_levels: list[str]) -> np.ndarray:
    """Design matrix with a FIXED dummy ordering.

    `cat_levels` is passed in rather than inferred from the frame, because
    `pd.get_dummies` on a prediction frame that happens to be missing a
    category would silently produce a different column order and the
    coefficients would be applied to the wrong variables. The fitted level list
    travels with the fit."""
    X = panel[cols].astype(float).to_numpy()
    parts = [np.ones((len(panel), 1)), X]
    if len(cat_levels) > 1:
        cat = panel["category"].to_numpy()
        for lvl in cat_levels[1:]:
            parts.append((cat == lvl).astype(float).reshape(-1, 1))
    return np.hstack(parts)


def _names(cols: list[str], cat_levels: list[str]) -> list[str]:
    return ["const", *cols, *[f"cat_{c}" for c in cat_levels[1:]]]


def _fit_logit(panel: pd.DataFrame, cols: list[str], cat_levels: list[str]):
    import statsmodels.api as sm

    X = _design(panel, cols, cat_levels)
    y = panel["y"].to_numpy(dtype=float)
    return sm.Logit(y, X).fit(disp=0, maxiter=200)


def _fit_logit_clustered(panel: pd.DataFrame, cols: list[str],
                         cat_levels: list[str], cluster: str = "nta_code"):
    """Coefficients with NTA-clustered standard errors.

    Clustered because 12,000 overlapping discs are nothing like 12,000
    independent observations. This does NOT fix inference — the retrodiction
    measured out-of-sample residual Moran's I at 0.64-0.77, and cluster-robust
    SEs still assume independence ACROSS clusters — which is exactly why the
    two marginal coefficients (jobs, transit) are not in the model at all."""
    import statsmodels.api as sm

    X = _design(panel, cols, cat_levels)
    y = panel["y"].to_numpy(dtype=float)
    groups = panel[cluster].fillna("NA").to_numpy()
    return sm.Logit(y, X).fit(disp=0, maxiter=200, cov_type="cluster",
                              cov_kwds={"groups": groups, "use_correction": True})


def _nta_folds(panel: pd.DataFrame, n_folds: int = N_FOLDS,
               seed: int = RNG_SEED) -> list[np.ndarray]:
    """WHOLE NTAs held out. A random k-fold split would put the same 400 m disc
    on both sides of the split and report the leak as skill."""
    rng = np.random.default_rng(seed)
    ntas = np.asarray(panel["nta_code"].fillna("NA").unique(), dtype=object)
    rng.shuffle(ntas)
    # Never more folds than NTAs: array_split would emit empty folds, every
    # empty fold is a silently skipped one, and a "5-fold" CV that actually ran
    # two is a diagnostic lying about its own denominator.
    k = max(2, min(n_folds, len(ntas)))
    return [np.asarray(f, dtype=object) for f in np.array_split(ntas, k)]


def blocked_oos_predictions(panel: pd.DataFrame, cols: list[str], *,
                            per_category: dict[str, bool] | None = None,
                            n_folds: int = N_FOLDS,
                            seed: int = RNG_SEED) -> np.ndarray:
    """Out-of-sample p for every row, produced by the SAME two-stage structure
    the shipped model uses.

    A diagnostic that evaluates a different model from the one that ships is
    not a diagnostic. So when `per_category[c]` is True, fold-held-out rows of
    category c are predicted by a logit refitted on category c's TRAINING rows
    only; otherwise by the pooled logit refitted on all training rows.
    """
    idx = panel.reset_index(drop=True)
    per_category = per_category or {}
    cat_levels = sorted(idx["category"].unique())
    preds = np.full(len(idx), np.nan)
    nta = idx["nta_code"].fillna("NA")

    for fold in _nta_folds(idx, n_folds=n_folds, seed=seed):
        te = nta.isin(fold).to_numpy()
        tr = ~te
        if te.sum() == 0 or idx.loc[tr, "y"].nunique() < 2:
            continue
        try:
            pooled = _fit_logit(idx[tr], cols, cat_levels)
        except Exception:    # noqa: S112, BLE001 -- separation in a fold is
            continue         # expected; the fold is skipped, not the run
        te_idx = np.flatnonzero(te)
        preds[te_idx] = pooled.predict(_design(idx.iloc[te_idx], cols, cat_levels))

        for cat, own in per_category.items():
            if not own:
                continue
            sub_tr = tr & (idx["category"] == cat).to_numpy()
            sub_te = np.flatnonzero(te & (idx["category"] == cat).to_numpy())
            if len(sub_te) == 0 or idx.loc[sub_tr, "y"].nunique() < 2:
                continue
            try:
                m = _fit_logit(idx[sub_tr], cols, [cat])
                preds[sub_te] = m.predict(_design(idx.iloc[sub_te], cols, [cat]))
            except Exception:    # noqa: S112, BLE001 -- as above, per category
                continue
    return preds


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def _log_loss(y: np.ndarray, p: np.ndarray, eps: float = 1e-9) -> float:
    p = np.clip(np.asarray(p, dtype=float), eps, 1 - eps)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Deciles of predicted probability against the observed rate.

    A ranking deliverable still needs calibration beside it: an AUC says the
    order is right, and says nothing about whether a 0.30 means thirty
    percent."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    ok = ~np.isnan(p)
    y, p = y[ok], p[ok]
    if len(p) == 0:
        return []
    q = pd.qcut(pd.Series(p).rank(method="first"), bins, labels=False,
                duplicates="drop")
    out = []
    for d in sorted(pd.unique(q)):
        m = (q == d).to_numpy()
        out.append({"decile": int(d) + 1, "n": int(m.sum()),
                    "predicted": float(p[m].mean()),
                    "observed": float(y[m].mean())})
    return out


def calibration_max_gap(cal: list[dict]) -> float:
    if not cal:
        return float("nan")
    return float(max(abs(c["predicted"] - c["observed"]) for c in cal))


def fit(panel: pd.DataFrame, *, support: dict[str, int],
        support_floor: int = SUPPORT_FLOOR) -> dict:
    """The two-stage fit plus every baseline and the pre-declared verdict.

    Returns a dict carrying the pooled coefficients, one per-category model for
    each supported category, the blocked-CV diagnostics, and `ships` /
    `ships_reason` evaluated against the failure criterion fixed in the module
    docstring — NOT re-judged afterwards.
    """
    from loci.validation.retrodiction import _auc

    p = panel.dropna(subset=["log_score", "y"]).copy()
    cat_levels = sorted(p["category"].unique())
    cols = list(FEATURE_LIST)

    fitted_cats = {
        c: bool(support.get(c, 0) >= support_floor
                and (p["category"] == c).sum() >= 500
                and p.loc[p["category"] == c, "y"].nunique() == 2)
        for c in cat_levels}

    pooled = _fit_logit_clustered(p, cols, cat_levels)
    pooled_names = _names(cols, cat_levels)
    coefs = {"pooled": {
        n: {"coef": float(pooled.params[i]), "se": float(pooled.bse[i]),
            "z": float(pooled.tvalues[i]), "p": float(pooled.pvalues[i]),
            "ci_lo": float(pooled.conf_int()[i][0]),
            "ci_hi": float(pooled.conf_int()[i][1])}
        for i, n in enumerate(pooled_names)}}

    per_cat_models: dict[str, dict] = {}
    for cat, own in fitted_cats.items():
        if not own:
            continue
        g = p[p["category"] == cat]
        try:
            m = _fit_logit_clustered(g, cols, [cat])
        except Exception as exc:                       # noqa: BLE001
            fitted_cats[cat] = False
            per_cat_models[cat] = {"skipped": str(exc)[:160]}
            continue
        nm = _names(cols, [cat])
        per_cat_models[cat] = {
            "n": int(len(g)), "positive_rate": float(g["y"].mean()),
            "params": [float(v) for v in m.params],
            "names": nm,
            "coefficients": {
                n: {"coef": float(m.params[i]),
                    "ci_lo": float(m.conf_int()[i][0]),
                    "ci_hi": float(m.conf_int()[i][1]),
                    "p": float(m.pvalues[i])}
                for i, n in enumerate(nm)}}
    coefs["by_category"] = per_cat_models
    coefs["pooled_params"] = [float(v) for v in pooled.params]
    coefs["pooled_names"] = pooled_names
    coefs["cat_levels"] = cat_levels

    y = p["y"].to_numpy(dtype=float)
    oos_full = blocked_oos_predictions(p, cols, per_category=fitted_cats)
    oos_nos = blocked_oos_predictions(p, list(NO_SCORE_FEATURES),
                                      per_category=fitted_cats)
    oos_homes = blocked_oos_predictions(p, list(HOMES_ONLY_FEATURES),
                                        per_category=fitted_cats)
    ok = ~np.isnan(oos_full)

    def _safe_auc(mask, pred) -> float:
        """NaN, never a number, when there is nothing to score.

        Every fold can be skipped — separation, an NTA with no variance, a
        panel with fewer NTAs than folds — and an AUC computed on an empty
        array is not a small AUC, it is an absent one. Returning NaN makes the
        failure criterion below refuse to ship, which is the correct answer to
        "we could not measure it"."""
        yy, pp = y[mask], np.asarray(pred)[mask]
        if len(yy) == 0 or len(set(yy.tolist())) < 2:
            return float("nan")
        return float(_auc(yy, pp))

    auc_full = _safe_auc(ok, oos_full)
    auc_nos = _safe_auc(ok & ~np.isnan(oos_nos), oos_nos)
    auc_homes = _safe_auc(ok & ~np.isnan(oos_homes), oos_homes)
    auc_persist = (_safe_auc(np.ones(len(p), dtype=bool), p["y_prev"].to_numpy(dtype=float))
                   if "y_prev" in p and p["y_prev"].nunique() > 1 else float("nan"))

    cal = calibration(y[ok], oos_full[ok])
    gap = calibration_max_gap(cal)

    reasons = []
    if np.isnan(auc_full):
        reasons.append(
            "the NTA-blocked folds produced no scoreable out-of-sample "
            "predictions (too few NTAs, no outcome variance, or separation in "
            "every fold) — the model is unmeasured, not good")
    elif not (auc_full > auc_nos):
        reasons.append(f"AUC {auc_full:.4f} does not beat the no-score "
                       f"baseline {auc_nos:.4f}")
    if not np.isnan(auc_full) and not (np.isnan(auc_persist)
                                       or auc_full > auc_persist):
        reasons.append(f"AUC {auc_full:.4f} does not beat persistence "
                       f"{auc_persist:.4f}")
    if not (gap <= MAX_CALIBRATION_GAP):
        reasons.append(f"calibration max decile gap {gap:.3f} exceeds "
                       f"{MAX_CALIBRATION_GAP:.2f}"
                       if not np.isnan(gap) else
                       "calibration could not be computed out of sample")
    ships = not reasons

    per_cat_auc = {}
    for cat in cat_levels:
        m = (p["category"] == cat).to_numpy() & ok
        if m.sum() < 100 or len(set(y[m])) < 2:
            per_cat_auc[cat] = {"n": int(m.sum()), "skipped": "no variance or n < 100"}
            continue
        per_cat_auc[cat] = {
            "n": int(m.sum()), "positive_rate": float(y[m].mean()),
            "auc": _safe_auc(m, oos_full),
            "brier": _brier(y[m], oos_full[m]),
            "support_openings": int(support.get(cat, 0)),
            "model": "fitted" if fitted_cats.get(cat) else "pooled"}

    return {
        "n_rows": int(len(p)),
        "n_addresses": int(p["point_id"].nunique()),
        "n_ntas": int(p["nta_code"].nunique()),
        "positive_rate": float(y.mean()),
        "fitted_categories": {k: bool(v) for k, v in fitted_cats.items()},
        "coefficients": coefs,
        "auc_blocked": float(auc_full),
        "auc_no_score": float(auc_nos),
        "auc_persistence": float(auc_persist),
        "auc_homes_only": float(auc_homes),
        "auc_lift_vs_no_score": float(auc_full - auc_nos),
        "brier": _brier(y[ok], oos_full[ok]),
        "log_loss": _log_loss(y[ok], oos_full[ok]),
        "calibration": cal,
        "calibration_max_gap": gap,
        "by_category": per_cat_auc,
        "ships": bool(ships),
        "ships_reason": ("passes: beats the no-score and persistence baselines, "
                         "calibration within tolerance" if ships
                         else "; ".join(reasons)),
    }


def predict(fit_result: dict, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Apply the fitted two-stage model. Returns (p, is_fitted_model).

    The per-category model owns its rows; everything else is the pooled model.
    Column order comes from the FIT (`cat_levels`, `names`), never from the
    prediction frame."""
    coefs = fit_result["coefficients"]
    cat_levels = list(coefs["cat_levels"])
    cols = list(FEATURE_LIST)
    out = np.full(len(panel), np.nan)
    fitted = np.zeros(len(panel), dtype=bool)

    # CHUNKED. The prediction frame is 281,842 addresses x 15 categories, and a
    # single design matrix over it is 4.2M x 19 float64 -- 640 MB, doubled
    # during the hstack. Chunking costs nothing and keeps the run off swap.
    beta = np.asarray(coefs["pooled_params"], dtype=float)
    step = 500_000
    for lo in range(0, len(panel), step):
        hi = min(lo + step, len(panel))
        X = _design(panel.iloc[lo:hi], cols, cat_levels)
        out[lo:hi] = 1.0 / (1.0 + np.exp(-(X @ beta)))

    cat = panel["category"].to_numpy()
    for c, m in coefs["by_category"].items():
        if "params" not in m:
            continue
        sel = np.flatnonzero(cat == c)
        if len(sel) == 0:
            continue
        b = np.asarray(m["params"], dtype=float)
        Xc = _design(panel.iloc[sel], cols, [c])
        out[sel] = 1.0 / (1.0 + np.exp(-(Xc @ b)))
        fitted[sel] = True
    return out, fitted


# ---------------------------------------------------------------------------
# 4. issue
# ---------------------------------------------------------------------------
def build_fit_panel(con, issued_month: str, *, radius_m: float = RADIUS_M,
                    horizon: int = HORIZON_MONTHS,
                    sample_n: int = FIT_SAMPLE_N,
                    categories: tuple[str, ...] = ALL_CATEGORIES,
                    anchor: pd.DataFrame | None = None,
                    points: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """The stacked training folds. NOTHING dated on or after `issued_month`.

    Returns (panel, support) where support is the per-category dated-opening
    count over the union of the fold outcome windows."""
    m0 = month_first(issued_month)
    if points is None:
        points = load_points(con, limit=sample_n)
    if anchor is None:
        anchor = points
    homes = homes_within(con, points, radius_m=radius_m)

    frames = []
    for t0 in fit_t0s(issued_month, horizon):
        end = add_months(t0, horizon)
        if end > m0:
            raise ValueError(
                f"fold outcome window {t0}..{end} runs past the issue month "
                f"{m0} — that is leakage, not a fit window")
        anchors = base_medians(con, anchor, t0, radius_m=radius_m,
                               categories=categories)
        f = frozen_features(con, points, t0, anchors=anchors, radius_m=radius_m,
                            categories=categories, homes=homes)
        outc = openings_between(con, points, t0, end, radius_m=radius_m,
                                categories=categories)
        prev = openings_between(con, points, add_months(t0, -horizon), t0,
                                radius_m=radius_m, categories=categories)
        f = (f.merge(outc.rename(columns={"n": "openings"}),
                     on=["point_id", "category"], how="left")
               .merge(prev.rename(columns={"n": "openings_prev"}),
                      on=["point_id", "category"], how="left"))
        f["openings"] = f["openings"].fillna(0)
        f["openings_prev"] = f["openings_prev"].fillna(0)
        f["y"] = (f["openings"] > 0).astype(int)
        f["y_prev"] = (f["openings_prev"] > 0).astype(int)
        f["fold_t0"] = t0
        frames.append(f)

    panel = pd.concat(frames, ignore_index=True)
    panel = panel[panel["homes"] > 0].copy()

    lo = min(fit_t0s(issued_month, horizon))
    support = dated_openings_by_category(con, lo, m0)
    return panel, support


def issue(con, month: str, *, version: str | None = None,
          radius_m: float = RADIUS_M, horizon: int = HORIZON_MONTHS,
          sample_n: int = FIT_SAMPLE_N,
          categories: tuple[str, ...] = ALL_CATEGORIES,
          limit_points: int | None = None,
          dry_run: bool = False, progress=None, write_con=None) -> dict:
    """Fit on data available at `month`, predict every lot address x category,
    and write the vintage.

    IDEMPOTENT PER (issued_month, model_version) by DELETE-then-INSERT. Running
    the same model on the same month twice reproduces that month's answer;
    running a DIFFERENT model writes a different version ALONGSIDE, never over.
    Re-issuing a past vintage with a newer model is the one thing this ledger
    exists to make impossible, and the unique index on
    (issued_month, model_version, address_id, category) is what makes an
    accidental double-write an error rather than a duplicate.

    `con` may be READ-ONLY. Every expensive step — the two fit folds, the
    blocked CV, the four-million-row prediction — reads only, and the first
    write happens on `write_con` at the very end.

    DuckDB refuses two connections to one file with different configurations in
    one process, so `issue_managed` is the entry point that handles the
    read-then-write dance (open read, compute, CLOSE, open write, commit). This
    function is the single-handle form: it is what the tests use, and what a
    caller who already holds a writable handle wants."""
    validate_month(month)
    ver = version or model_version(horizon=horizon, radius_m=radius_m)
    m0 = month_first(month)
    say = progress or (lambda *_: None)

    say(f"1/5 frames — fit sample {sample_n:,}, anchor = the same sample")
    fit_points = load_points(con, limit=sample_n)
    say("2/5 fit panel (two folds, both ending before the issue month)")
    panel, support = build_fit_panel(con, month, radius_m=radius_m,
                                     horizon=horizon, sample_n=sample_n,
                                     categories=categories,
                                     anchor=fit_points, points=fit_points)
    say(f"3/5 fit — {len(panel):,} rows, {panel['nta_code'].nunique()} NTAs")
    res = fit(panel, support=support)

    say("4/5 prediction frame — every lot address in MN+BK x 15 categories")
    pred_points = load_points(con, limit=limit_points)
    pred_points = with_surprise_cell(pred_points)
    anchors = base_medians(con, fit_points, m0, radius_m=radius_m,
                           categories=categories)
    # `surprise_cell` rides in on `pred_points` through frozen_features' own
    # merge of the point attributes; re-merging it here would collide.
    pred = frozen_features(con, pred_points, m0, anchors=anchors,
                           radius_m=radius_m, categories=categories)
    pred = pred[pred["homes"] > 0].copy()

    p, is_fitted = predict(res, pred)
    pred["p_opening"] = np.clip(p, 1e-9, 1 - 1e-9)
    pred["support"] = np.where(is_fitted, "fitted", "pooled")

    say(f"5/5 write — {len(pred):,} rows, vintage {month} / {ver}")
    n_written = 0
    if not dry_run:
        w = write_con if write_con is not None else con
        ensure_schema(w)
        n_written = _write_vintage(w, pred, month=month, version=ver,
                                   horizon=horizon, t0=m0)
        _write_run(w, month=month, version=ver, horizon=horizon,
                   radius_m=radius_m, res=res, support=support,
                   n_rows=n_written, anchors=anchors)

    return {"issued_month": month, "model_version": ver,
            "horizon_months": horizon, "radius_m": radius_m,
            "fit": res, "support": support, "anchors": anchors,
            "n_rows_issued": int(n_written), "n_rows_predicted": int(len(pred)),
            "dry_run": bool(dry_run), "_pred": pred, "_t0": m0}


def issue_managed(month: str, *, progress=None, **kw) -> dict:
    """`issue`, holding ONE warehouse handle at a time.

    DuckDB will not open a second connection to the same file with a different
    configuration inside one process ("Can't open a connection to same database
    file with a different configuration"), and read_only=True versus False is
    exactly such a difference. So: open READ, do the fit and the four-million-row
    prediction, CLOSE, open WRITE, commit.

    The ordering is also what makes a peer session's lock cheap. All the
    expensive work happens while the peer is still busy; the write handle is
    asked for once, with a finished vintage already in memory, and waits up to
    45 minutes for it."""
    say = progress or (lambda *_: None)
    con = connect_read()
    try:
        try:
            con.execute("SET threads=6")
        except Exception:                   # noqa: BLE001 -- not fatal
            pass
        rep = issue(con, month, dry_run=True, progress=say, **kw)
    finally:
        con.close()

    pred, m0 = rep.pop("_pred"), rep.pop("_t0")
    say("opening the write handle (waits out a peer lock)…")
    w = connect_write()
    try:
        ensure_schema(w)
        n = _write_vintage(w, pred, month=rep["issued_month"],
                           version=rep["model_version"],
                           horizon=rep["horizon_months"], t0=m0)
        _write_run(w, month=rep["issued_month"], version=rep["model_version"],
                   horizon=rep["horizon_months"], radius_m=rep["radius_m"],
                   res=rep["fit"], support=rep["support"], n_rows=n,
                   anchors=rep["anchors"])
    finally:
        w.close()
    rep["n_rows_issued"] = int(n)
    rep["dry_run"] = False
    return rep


def score_managed(issued_month: str | None = None, *, as_of: str | None = None,
                  version: str | None = None, radius_m: float = RADIUS_M,
                  progress=None) -> list[dict]:
    """`score`, same one-handle-at-a-time discipline as `issue_managed`.

    The spatial join that produces the realized counts runs on the READ handle;
    the outcome rows and the score statistics are then computed on the WRITE
    handle, which can read `analysis.forecast` perfectly well."""
    say = progress or (lambda *_: None)
    con = connect_read()
    try:
        targets = ([(issued_month, version, as_of)] if issued_month
                   else [(a, b, c) for a, b, c in due_for_scoring(con)])
        prepared = []
        for issued, ver, asof in targets:
            prepared.append(_score_prepare(con, issued, as_of=asof, version=ver,
                                           radius_m=radius_m, progress=say))
    finally:
        con.close()
    if not prepared:
        return []

    say("opening the write handle (waits out a peer lock)…")
    w = connect_write()
    out = []
    try:
        for prep in prepared:
            out.append(_score_commit(w, prep, progress=say))
    finally:
        w.close()
    return out


#: The feature block frozen onto every row. Compact on purpose: this is four
#: million rows per vintage, and a pretty-printed JSON would be a gigabyte of
#: whitespace. Keys: supply ratio, own-gap flag, homes, retail index, raw
#: supply count, the anchor median, and the freeze date.
#: `%(t0)s` and not `{t0}`: the JSON braces in this literal are not format
#: placeholders, and `str.format` cannot be told the difference.
_FEATURES_JSON_SQL = (
    """'{"sr":' || CAST(round(supply_ratio, 5) AS VARCHAR)"""
    """ || ',"g":' || CAST(CAST(own_gap_flag AS INTEGER) AS VARCHAR)"""
    """ || ',"h":' || CAST(round(homes, 1) AS VARCHAR)"""
    """ || ',"ri":' || CAST(round(retail_index, 5) AS VARCHAR)"""
    """ || ',"sup":' || CAST(CAST(supply AS INTEGER) AS VARCHAR)"""
    """ || ',"bm":' || CAST(round(base_median, 6) AS VARCHAR)"""
    """ || ',"t0":"%(t0)s"}'""")


def _features_json_sql(t0: dt.date) -> str:
    return _FEATURES_JSON_SQL % {"t0": t0.isoformat()}


def _write_vintage(con, pred: pd.DataFrame, *, month: str, version: str,
                   horizon: int, t0: dt.date) -> int:
    frame = pred[["point_id", "category", "borough", "nta_code", "surprise_cell",
                  "p_opening", "support", "supply_ratio", "own_gap_flag",
                  "homes", "retail_index", "supply", "base_median"]]
    con.register("_fc_pred", frame)
    con.execute("DELETE FROM analysis.forecast "
                "WHERE issued_month = ? AND model_version = ?", [month, version])
    con.execute(f"""
        INSERT INTO analysis.forecast
        -- THE NATURAL KEY, NOT A HASH OF IT. The first cut used
        -- substr(md5(address || '|' || category), 1, 10) -- 40 bits over 4.2
        -- million rows, which the birthday bound puts at
        --     4.23e6^2 / (2 * 2^40) ~= 8 expected collisions,
        -- and it duly collided on the very first vintage. A ledger's primary
        -- key must be collision-free BY CONSTRUCTION, not with high
        -- probability, so the id carries the address (a 10-character BBL) and
        -- the category verbatim. It is longer and it is readable, and neither
        -- of those is the point: the point is that two different doorways can
        -- never be the same row.
        SELECT 'f-' || replace('{month}', '-', '') || '-'
               || substr('{version}', position('+' IN '{version}') + 1) || '-'
               || point_id || '-' || category                       AS forecast_id,
               '{month}'                                            AS issued_month,
               {int(horizon)}                                       AS horizon_months,
               '{version}'                                          AS model_version,
               point_id                                             AS address_id,
               category,
               '{FRAME}'                                            AS frame,
               borough,
               nta_code,
               surprise_cell,
               p_opening,
               p_opening                                            AS expected_openings,
               support,
               {_features_json_sql(t0)}                             AS features_json,
               now()                                                AS frozen_at
        FROM _fc_pred
    """)
    n = con.execute("SELECT count(*) FROM analysis.forecast "
                    "WHERE issued_month = ? AND model_version = ?",
                    [month, version]).fetchone()[0]
    con.unregister("_fc_pred")
    return int(n)


def _write_run(con, *, month: str, version: str, horizon: int, radius_m: float,
               res: dict, support: dict, n_rows: int, anchors: dict) -> None:
    con.execute("DELETE FROM analysis.forecast_run "
                "WHERE issued_month = ? AND model_version = ?", [month, version])
    support_json = json.dumps({
        "dated_openings_in_fit_window": support,
        "anchor_base_median_at_issue": anchors,
        "fitted_categories": res["fitted_categories"],
        "support_floor": SUPPORT_FLOOR,
        "by_category_oos": res["by_category"]}, sort_keys=True, default=str)
    con.execute("""
        INSERT INTO analysis.forecast_run VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [month, version, horizon, radius_m,
          json.dumps([str(d) for d in fit_t0s(month, horizon)]),
          FIT_WINDOW_RULE, json.dumps(list(FEATURE_LIST)),
          res["n_rows"], res["n_addresses"], res["n_ntas"],
          res["positive_rate"], res["auc_blocked"], res["auc_no_score"],
          res["auc_persistence"], res["auc_homes_only"], res["brier"],
          json.dumps(res["calibration"]),
          json.dumps(res["coefficients"], default=str),
          support_json, res["ships"], res["ships_reason"], n_rows,
          dt.datetime.now()])


# ---------------------------------------------------------------------------
# 5. score
# ---------------------------------------------------------------------------
def _score_prepare(con, issued_month: str, *, as_of: str | None = None,
                   version: str | None = None, radius_m: float = RADIUS_M,
                   progress=None) -> dict:
    """The READ half of scoring: resolve the vintage, the window, and the
    realized counts. Touches nothing.

    THE WINDOW, and its boundaries are pinned by test:
        realized = a same-category dated first-seen in
        [first day of issued_month, first day of issued_month + elapsed months)
        within `radius_m` STRAIGHT-LINE.

    `--as-of` sets the right edge. Scoring 2023-01 as of 2024-01 is the twelve-
    month score; as of 2025-01 is the twenty-four-month score, which is a
    DIFFERENT ROW on the same forecasts, not a correction of the first. The
    horizon the forecast was issued for is 12; a 24-month score is reported for
    what it is — the same probability judged against a longer window, which it
    will look better on for a trivial reason and which is labelled accordingly.
    """
    require_schema(con)
    validate_month(issued_month)
    say = progress or (lambda *_: None)

    vers = [r[0] for r in con.execute(
        "SELECT DISTINCT model_version FROM analysis.forecast "
        "WHERE issued_month = ? ORDER BY 1", [issued_month]).fetchall()]
    if version:
        vers = [v for v in vers if v == version]
    if not vers:
        raise RuntimeError(f"no forecast vintage for {issued_month}"
                           + (f" / {version}" if version else ""))

    m0 = month_first(issued_month)
    horizon = int(con.execute(
        "SELECT max(horizon_months) FROM analysis.forecast WHERE issued_month = ?",
        [issued_month]).fetchone()[0])
    scored_month = as_of or month_str(add_months(m0, horizon))
    validate_month(scored_month)
    end = month_first(scored_month)
    elapsed = (end.year * 12 + end.month) - (m0.year * 12 + m0.month)
    if elapsed <= 0:
        raise ValueError(f"--as-of {scored_month} is not after the issue month "
                         f"{issued_month}; there is no window to score")

    prep = {"issued_month": issued_month, "scored_month": scored_month,
            "horizon_elapsed": elapsed, "horizon_months": horizon,
            "radius_m": radius_m, "realized": {}}

    for ver in vers:
        say(f"scoring {issued_month} / {ver} as of {scored_month} "
            f"({elapsed} months elapsed)")
        # The realized counts are computed in pandas (the spatial join lives
        # there) but the 4.2-million-row JOIN TO THE VINTAGE is done in DuckDB.
        # Pulling every forecast_id into a frame would be a gigabyte of 30-byte
        # strings for a column that is only ever used as a join key.
        pts = con.execute(f"""
            SELECT DISTINCT a.address_id AS point_id, a.lon, a.lat
            FROM analysis.address a
            JOIN analysis.forecast f ON f.address_id = a.address_id
            WHERE f.issued_month = '{issued_month}' AND f.model_version = '{ver}'
        """).fetchdf()
        realized = openings_between(con, pts, m0, end, radius_m=radius_m)
        prep["realized"][ver] = realized.rename(
            columns={"point_id": "address_id", "n": "realized_openings"})
        say(f"  {len(prep['realized'][ver]):,} address x category discs saw at "
            f"least one same-category opening in the window")
    return prep


def _score_commit(con, prep: dict, *, dry_run: bool = False,
                  progress=None) -> dict:
    """Write the outcome rows and compute the score. See `_score_prepare`."""
    say = progress or (lambda *_: None)
    out = {k: prep[k] for k in ("issued_month", "scored_month",
                                "horizon_elapsed", "horizon_months")}
    out["versions"] = {}
    for ver, realized in prep["realized"].items():
        if not dry_run:
            say(f"  writing outcomes for {prep['issued_month']} / {ver}")
            _write_outcomes(con, realized, issued_month=prep["issued_month"],
                            version=ver, scored_month=prep["scored_month"],
                            elapsed=prep["horizon_elapsed"])
        out["versions"][ver] = _score_stats(
            _scored_frame(con, realized, issued_month=prep["issued_month"],
                          version=ver),
            elapsed=prep["horizon_elapsed"])
    return out


def score(con, issued_month: str, *, as_of: str | None = None,
          version: str | None = None, radius_m: float = RADIUS_M,
          dry_run: bool = False, progress=None, write_con=None) -> dict:
    """Prepare and commit on ONE handle. `score_managed` is the two-handle form.

    Kept as a single function because the tests and any caller that already
    holds a writable connection want the whole thing in one call."""
    prep = _score_prepare(con, issued_month, as_of=as_of, version=version,
                          radius_m=radius_m, progress=progress)
    return _score_commit(write_con if write_con is not None else con, prep,
                         dry_run=dry_run, progress=progress)


def _scored_frame(con, realized: pd.DataFrame, *, issued_month: str,
                  version: str) -> pd.DataFrame:
    """(category, support, p_opening, realized_flag) for every row of a vintage.

    Small dtypes only — no forecast_id, no address_id. AUC and Brier need the
    full (p, y) vectors and nothing else, and at 4.2M rows the difference
    between carrying the keys and not is a gigabyte."""
    con.register("_fc_real", realized[["address_id", "category",
                                       "realized_openings"]])
    df = con.execute("""
        SELECT f.category, f.support, f.p_opening,
               COALESCE(r.realized_openings, 0)      AS realized_openings,
               COALESCE(r.realized_openings, 0) > 0  AS realized_flag
        FROM analysis.forecast f
        LEFT JOIN _fc_real r
               ON r.address_id = f.address_id AND r.category = f.category
        WHERE f.issued_month = ? AND f.model_version = ?
    """, [issued_month, version]).fetchdf()
    con.unregister("_fc_real")
    return df


def _write_outcomes(con, realized: pd.DataFrame, *, issued_month: str,
                    version: str, scored_month: str, elapsed: int) -> None:
    """DELETE + INSERT for this (vintage, model, scoring date).

    ZERO IS A REAL OBSERVATION: the LEFT JOIN writes a row for every forecast in
    the vintage, not only the ones that saw an opening. A scoring pass that
    stored only the hits would produce a calibration curve with no denominator.

    `con` must be WRITABLE, and it reads `analysis.forecast` itself — a
    writable handle can read, and DuckDB will not give one process a second
    connection to the same file with a different configuration anyway."""
    ensure_schema(con)
    con.register("_fc_real", realized[["address_id", "category",
                                       "realized_openings"]])
    con.execute("""
        DELETE FROM analysis.forecast_outcome
        WHERE scored_month = ?
          AND forecast_id IN (SELECT forecast_id FROM analysis.forecast
                              WHERE issued_month = ? AND model_version = ?)
    """, [scored_month, issued_month, version])
    con.execute(f"""
        INSERT INTO analysis.forecast_outcome
        SELECT f.forecast_id, '{scored_month}', {int(elapsed)},
               COALESCE(r.realized_openings, 0),
               COALESCE(r.realized_openings, 0) > 0, now()
        FROM analysis.forecast f
        LEFT JOIN _fc_real r
               ON r.address_id = f.address_id AND r.category = f.category
        WHERE f.issued_month = ? AND f.model_version = ?
    """, [issued_month, version])
    con.unregister("_fc_real")


def _score_stats(rows: pd.DataFrame, *, elapsed: int) -> dict:
    from loci.validation.retrodiction import _auc

    y = rows["realized_flag"].to_numpy(dtype=float)
    p = rows["p_opening"].to_numpy(dtype=float)
    cal = calibration(y, p)
    per_cat = {}
    for cat, g in rows.groupby("category"):
        yy = g["realized_flag"].to_numpy(dtype=float)
        pp = g["p_opening"].to_numpy(dtype=float)
        c = calibration(yy, pp)
        per_cat[cat] = {
            "n": int(len(g)), "realized_rate": float(yy.mean()),
            "mean_p": float(pp.mean()),
            "auc": float(_auc(yy, pp)) if len(set(yy)) > 1 else float("nan"),
            "brier": _brier(yy, pp), "log_loss": _log_loss(yy, pp),
            "calibration_max_gap": calibration_max_gap(c),
            "support": str(g["support"].iloc[0])}
    return {
        "n": int(len(rows)), "horizon_elapsed": elapsed,
        "realized_rate": float(y.mean()), "mean_p": float(p.mean()),
        "auc": float(_auc(y, p)) if len(set(y)) > 1 else float("nan"),
        "brier": _brier(y, p), "log_loss": _log_loss(y, p),
        "calibration": cal, "calibration_max_gap": calibration_max_gap(cal),
        "by_category": per_cat,
    }


# ---------------------------------------------------------------------------
# 6. report
# ---------------------------------------------------------------------------
def track_record(con) -> list[dict]:
    """One row per (vintage, model, scoring date). The whole record, failures
    included."""
    require_schema(con)
    return con.execute("""
        SELECT f.issued_month, f.model_version, o.scored_month,
               o.horizon_elapsed, count(*) AS n,
               avg(CASE WHEN o.realized_flag THEN 1.0 ELSE 0.0 END) AS realized_rate,
               avg(f.p_opening)                                     AS mean_p
        FROM analysis.forecast f
        JOIN analysis.forecast_outcome o ON o.forecast_id = f.forecast_id
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3
    """).fetchdf().to_dict("records")


def vintage_scores(con, issued_month: str, scored_month: str,
                   version: str | None = None) -> dict:
    """Recompute AUC / Brier / calibration from the LEDGER, not from a cached
    JSON, so the printed track record is always a read of the stored rows."""
    require_schema(con)
    sql = """
        SELECT f.model_version, f.category, f.support, f.p_opening,
               o.realized_flag, o.horizon_elapsed
        FROM analysis.forecast f
        JOIN analysis.forecast_outcome o ON o.forecast_id = f.forecast_id
        WHERE f.issued_month = ? AND o.scored_month = ?
    """
    args = [issued_month, scored_month]
    if version:
        sql += " AND f.model_version = ?"
        args.append(version)
    df = con.execute(sql, args).fetchdf()
    if df.empty:
        return {}
    out = {}
    for ver, g in df.groupby("model_version"):
        g = g.rename(columns={"realized_flag": "realized_flag"})
        g = g.assign(realized_openings=g["realized_flag"].astype(int))
        out[ver] = _score_stats(g, elapsed=int(g["horizon_elapsed"].iloc[0]))
    return out


def surprise_nta(con, issued_month: str, scored_month: str, *,
                 category: str = "(all)", version: str | None = None,
                 limit: int = 10, min_addresses: int = 200) -> pd.DataFrame:
    """Top and bottom NTAs by the cluster-robust surprise z.

    `min_addresses` exists because a residual sum over forty doorways is not a
    neighbourhood-level statement about anything."""
    require_schema(con)
    sql = """
        SELECT * FROM analysis.forecast_surprise_nta
        WHERE issued_month = ? AND scored_month = ? AND category = ?
          AND n_addresses >= ? AND z_clustered IS NOT NULL
    """
    args = [issued_month, scored_month, category, int(min_addresses)]
    if version:
        sql += " AND model_version = ?"
        args.append(version)
    df = con.execute(sql, args).fetchdf()
    if df.empty:
        return df
    df = df.sort_values("z_clustered", ascending=False)
    return pd.concat([df.head(limit), df.tail(limit)]).drop_duplicates()


def p_distribution(con, issued_month: str, version: str | None = None) -> pd.DataFrame:
    """p_opening quantiles per category for one vintage — what the modelled
    layer actually SAYS, before anything is known about whether it was right."""
    require_schema(con)
    sql = """
        SELECT category, support, count(*) AS n,
               quantile_cont(p_opening, 0.10) AS p10,
               quantile_cont(p_opening, 0.50) AS p50,
               quantile_cont(p_opening, 0.90) AS p90,
               max(p_opening)                 AS pmax
        FROM analysis.forecast
        WHERE issued_month = ?
    """
    args = [issued_month]
    if version:
        sql += " AND model_version = ?"
        args.append(version)
    sql += " GROUP BY 1, 2 ORDER BY p50 DESC"
    return con.execute(sql, args).fetchdf()


def runs(con) -> pd.DataFrame:
    require_schema(con)
    return con.execute("""
        SELECT issued_month, model_version, horizon_months, n_fit_rows, n_fit_ntas,
               fit_positive_rate, auc_blocked, auc_no_score, auc_persistence,
               auc_homes_only, brier_fit, ships, ships_reason, n_rows_issued,
               calibration_json, issued_at
        FROM analysis.forecast_run ORDER BY issued_month, model_version
    """).fetchdf()


def due_for_scoring(con, today: dt.date | None = None) -> list[tuple[str, str, str]]:
    """(issued_month, model_version, as_of) for every vintage whose horizon has
    elapsed and which has no outcome row at that horizon yet.

    This is what the monthly job calls. A vintage is scored WHEN ITS HORIZON
    ELAPSES, not when someone remembers."""
    require_schema(con)
    today = today or dt.date.today()
    rows = con.execute("""
        SELECT f.issued_month, f.model_version, max(f.horizon_months) AS h,
               (SELECT count(*) FROM analysis.forecast_outcome o
                 JOIN analysis.forecast g ON g.forecast_id = o.forecast_id
                WHERE g.issued_month = f.issued_month
                  AND g.model_version = f.model_version
                  AND o.horizon_elapsed >= max(f.horizon_months)) AS scored
        FROM analysis.forecast f
        GROUP BY 1, 2
    """).fetchall()
    due = []
    for issued, ver, h, scored in rows:
        target = add_months(month_first(issued), int(h))
        if target <= today.replace(day=1) and not scored:
            due.append((issued, ver, month_str(target)))
    return due
