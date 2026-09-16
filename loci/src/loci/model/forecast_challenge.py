"""THE CHALLENGER — a report-only contest between the shipped two-stage logit
and a pooled gradient booster, on the SAME NTA-blocked out-of-sample folds.

Design memo: `challenger-design.md` (2026-09-16). This module never issues a
vintage. It has no write path to `analysis.forecast*` at all -- not behind a
flag, not under `--force` -- and every warehouse handle it opens is
`forecast.connect_read(read_only=True)`. A WIN opens a decision about shipping
a black box; it does not execute one (memo §7 item 6).

===========================================================================
THE QUESTION, PRE-DECLARED (memo §3)
===========================================================================

Does a pooled `HistGradientBoostingClassifier`, given the incumbent's four
frozen features PLUS three more t0-true ones the incumbent doesn't use
(`log_supply_other`, `log_openings_prev_own`, `log_openings_prev_other`), beat
the shipped two-stage logit by enough, and honestly enough, to be worth the
loss of the coefficient-as-deliverable?

Records **WINS** only if all six hold, on the intersection of rows both
models could score:

    W1  ΔAUC (GBM - logit) >= +0.010
    W2  95% NTA-clustered paired bootstrap CI on ΔAUC excludes 0 (400 draws)
    W3  Brier AND log loss both lower for the GBM
    W4  GBM calibration max decile gap <= MAX_CALIBRATION_GAP (0.15) -- the
        SAME tolerance the incumbent must pass
    W5  no category with >=500 OOS rows and both classes loses >0.02 AUC, and
        >=8 of 15 categories improve
    W6  OOF residual Moran's I is NOT HIGHER for the GBM than for the logit

Anything short of all six is REPORT ONLY. A negative delta, a CI containing
zero, or >=2 categories regressing >0.02 AUC is recorded as FAILS -- a null,
the way D111's Citi Bike test was, not silently dropped.

===========================================================================
WHAT IS REUSED, WHAT IS NEW (memo §6)
===========================================================================

Reused by IMPORT, never copied: `forecast.build_fit_panel`, `load_points`,
`homes_within`, `openings_between`, `base_medians`, `frozen_features`,
`_nta_folds`, `blocked_oos_predictions`, `fit`, `_brier`, `_log_loss`,
`calibration`, `calibration_max_gap`, `connect_read`, `model_version`,
`live_supply_hash`; `retrodiction._auc`, `nta_fold_map`, `_oof_frame`,
`bootstrap_delta`, `residual_morans_i`, `cd_code`.

NOT touched, ever, by this module: `forecast.issue`, `issue_managed`,
`predict`, `_write_vintage`, `_write_run`, `score`/`_score_commit`,
`_write_outcomes`, `prune`, `FEATURE_LIST`, `MODEL_SEMVER`. The incumbent's
frozen contract is exactly that -- frozen -- and a challenger that quietly
mutated it would not be a challenger, it would be a second incumbent.

NEW here: `augment()` (the three t0-true features, joined onto the panel
`build_fit_panel` already produced, per its own `fold_t0`), the anachronistic
present-day jobs/transit controls (withheld from the logit, run as a SEPARATE
arm here — memo §1, §7 item 3), `blocked_oos_predictions_gbm` (the GBM
analogue of the logit's own out-of-fold routine, on the IDENTICAL NTA
partition), `evaluate_verdict` (the six criteria), and `run_challenge` (the
orchestrator the CLI calls).

===========================================================================
THREATS A CONTRARIAN WILL RAISE (memo §7), and how this module answers them
===========================================================================

1. "Six features and a non-linear learner at once -- you can't say which
   won." Three rungs, same folds: rung 1 = the shipped logit@4 (byte-
   identical to `fit()['auc_blocked']`); rung 2 = the SAME two-stage logit
   form, given the three new t0-true features; rung 3 = the pooled GBM on the
   rung-2 feature set. Features = rung2 - rung1; form = rung3 - rung2.
2. "The win is boundary leakage." W6, plus the CD-clustered bootstrap
   reported alongside the NTA-clustered one.
3. "Anachronistic jobs/transit let a 2023 fit know 2026." Both arms always
   run; `--no-anachronistic` forces the headline to the arm without them, and
   the stricter arm is forced to the headline whenever the two disagree on
   `wins`, flag or no flag.
4. "360k rows, ~103 real degrees of freedom." The bar is +0.010, the CI is
   NTA-clustered (and CD-clustered alongside), and there are NO per-category
   GBM refits -- one pooled model, `category` as a native categorical split.
5. "`openings_prev` makes beating persistence trivial." Persistence is a
   reported baseline inside `fit()`, never the bar here; rung 2 gives the
   logit the identical feature, so the GBM is not credited for something the
   logit was denied.
6. "A win pressures you to ship a black box." This subcommand cannot issue.
7. "A tree's p_opening will be read as viability." D88 printed verbatim by
   the CLI, exactly as `forecast issue` prints it.
8. "The fit-sample size is itself a bias." Same `--sample-n` default
   (`forecast.FIT_SAMPLE_N`), same anchor rule (`base_medians`), as the
   incumbent -- a challenge on a different sample is not a challenge.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import numpy as np
import pandas as pd

from loci.model import forecast as fc
from loci.validation import retrodiction as rd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
#: `data/forecast_challenge/<month>.json`. Never committed -- see .gitignore.
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "forecast_challenge"

#: The three t0-true features `augment()` adds beyond `forecast.FEATURE_LIST`.
#: `log_supply_other` is the highest-value omission (D88 addendum: other-
#: category supply absorbs ~48% of the live vintage's score-block lift).
#: `log_openings_prev_own` makes persistence a NESTED special case of rung 2 —
#: deliberate: the challenger must dominate a baseline it contains.
RUNG2_EXTRA: tuple[str, ...] = ("log_supply_other", "log_openings_prev_own",
                                "log_openings_prev_other")

#: Present-day values applied to a past t0 (memo §1). Withheld from the
#: logit's own FEATURE_LIST for coefficient inference; run here as a SEPARATE
#: arm because a purely predictive contest has no standard error to
#: invalidate.
ANACHRONISTIC_FEATURES: tuple[str, ...] = ("log_jobs", "log_transit")

#: W1 -- the pre-declared floor. The live vintage's whole score block is worth
#: +0.026; the retrodiction's honest marginal was +0.013. Less than +0.010 is
#: trading the coefficient-as-deliverable for noise (memo §3).
AUC_FLOOR = 0.010

#: memo §4 -- fixed grid of 8, engaged only by `--tune`, only if the untuned
#: default fails W1. `l2_regularization`/`max_bins`/`max_iter`/
#: `categorical_features`/`random_state` are FIXED across the grid.
GBM_GRID: tuple[dict, ...] = tuple(
    {"learning_rate": lr, "max_leaf_nodes": leaves, "min_samples_leaf": msl,
     "l2_regularization": 1.0, "max_bins": 128, "max_iter": 500,
     "random_state": fc.RNG_SEED}
    for lr in (0.05, 0.1)
    for leaves in (15, 31)
    for msl in (200, 1000))

#: memo §4 -- the untuned default path: ONE honest number, no search.
#: `early_stopping=False` on purpose -- sklearn's own early stopping uses a
#: RANDOM validation split, which would put the same 400 m disc on both sides
#: and stop too late. If early stopping is ever wired in, it must use an
#: explicit NTA-block validation set, never `validation_fraction`.
DEFAULT_GBM_PARAMS: dict = {"learning_rate": 0.05, "max_leaf_nodes": 31,
                            "min_samples_leaf": 1000, "max_iter": 300,
                            "early_stopping": False, "l2_regularization": 1.0,
                            "max_bins": 128, "random_state": fc.RNG_SEED}

#: The declared JSON keys (memo §6) a caller can rely on. Not exhaustive --
#: the payload carries more -- but these must always be present.
REQUIRED_KEYS: tuple[str, ...] = (
    "issued_month", "supply_hash", "model_version_compared", "sample_n",
    "n_rows", "n_addresses", "n_ntas", "feature_list_rung1",
    "feature_list_rung2", "feature_list_rung3", "anachronistic_features",
    "hyperparameter_grid", "tune_requested", "rungs", "headline_arm",
    "arms_agree", "both_arms", "wins", "verdict_reason", "verdict_status",
    "forecast_row_counts_before", "forecast_row_counts_after",
    "row_counts_unchanged")


# ---------------------------------------------------------------------------
# 1. augment() — the three t0-true features (checklist item 1)
# ---------------------------------------------------------------------------
def _as_date(v) -> dt.date:
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v
    return pd.Timestamp(v).date()


def augment(con, panel: pd.DataFrame, points: pd.DataFrame, *,
           radius_m: float = fc.RADIUS_M,
           categories: tuple[str, ...] = fc.ALL_CATEGORIES,
           horizon: int = fc.HORIZON_MONTHS,
           include_censored: bool = True) -> pd.DataFrame:
    """Join `log_supply_other`, `log_openings_prev_own`, `log_openings_prev_other`,
    `log_jobs` and `log_transit` onto a fit panel `build_fit_panel` already
    produced -- ONE per-fold pass, each computed AT THAT FOLD'S OWN t0, so
    nothing dated on or after that t0 can enter (the same leakage rule
    `frozen_features` already enforces via `retrodiction.supply_as_of`, called
    here again for the SAME reason: a second copy of the panel's own t0-safe
    query, not a second copy of the leakage rule itself).

    `log_supply_other`: total principled supply within `radius_m` at the
    fold's t0, across ALL `categories`, minus the row's OWN category supply
    (already sitting in `panel['supply']` from `frozen_features`).

    `log_openings_prev_own`/`_other`: `panel['openings_prev']` (already
    computed by `build_fit_panel` over [t0-horizon, t0)) IS the own-category
    count; the other-category total comes from one extra `openings_between`
    call over the SAME window, pivoted the same way.

    `log_jobs`/`log_transit`: present-day (`analysis.address.jobs_400m`,
    `.transit_entries_400m`) -- an ANACHRONISM, stated, exactly as
    `homes_within`'s present-day PLUTO units are. Run as a separate arm by the
    caller, never folded silently into the default feature set.
    """
    if "openings_prev" not in panel.columns:
        raise ValueError(
            "augment() expects build_fit_panel's own 'openings_prev' column "
            "-- log_openings_prev_own rides on it rather than recomputing "
            "the window a second, possibly different, way.")
    t0_col = "fold_t0" if "fold_t0" in panel.columns else "t0"
    pts = points[["point_id", "lon", "lat"]]

    parts = []
    for t0_raw, grp in panel.groupby(t0_col, sort=False):
        t0 = _as_date(t0_raw)
        sup = rd.supply_as_of(con, pts, asof=t0, radius_m=radius_m,
                              include_censored=include_censored,
                              categories=categories)
        total_sup = (sup.groupby("point_id")["supply"].sum()
                    .rename("supply_total").reset_index()
                    if not sup.empty else
                    pd.DataFrame({"point_id": pd.Series([], dtype=object),
                                 "supply_total": pd.Series([], dtype=float)}))
        g = grp.merge(total_sup, on="point_id", how="left")
        # EXPLICIT float casts throughout: an empty-fold merge (no supply, no
        # prior openings anywhere in the window -- a real possibility on a
        # thin category or a short fixture) otherwise leaves the joined column
        # `object` dtype, and `np.log1p` on an object Series raises rather than
        # vectorising, on a real warehouse as much as on a test fixture.
        g["supply_total"] = g["supply_total"].fillna(0.0).astype(float)
        g["supply"] = g["supply"].astype(float)
        g["supply_other"] = (g["supply_total"] - g["supply"]).clip(lower=0.0)
        g["log_supply_other"] = np.log1p(g["supply_other"].astype(float))

        start = fc.add_months(t0, -horizon)
        prev = fc.openings_between(con, pts, start, t0, radius_m=radius_m,
                                   categories=categories)
        total_prev = (prev.groupby("point_id")["n"].sum()
                     .rename("openings_prev_total").reset_index()
                     if not prev.empty else
                     pd.DataFrame({"point_id": pd.Series([], dtype=object),
                                  "openings_prev_total": pd.Series([], dtype=float)}))
        g = g.merge(total_prev, on="point_id", how="left")
        g["openings_prev_total"] = g["openings_prev_total"].fillna(0.0).astype(float)
        g["openings_prev"] = g["openings_prev"].astype(float)
        g["openings_prev_other"] = (
            g["openings_prev_total"] - g["openings_prev"]).clip(lower=0.0)
        g["log_openings_prev_other"] = np.log1p(g["openings_prev_other"].astype(float))
        g["log_openings_prev_own"] = np.log1p(g["openings_prev"])
        g = g.drop(columns=["supply_total", "openings_prev_total"])
        parts.append(g)

    out = pd.concat(parts, ignore_index=True)

    addr = con.execute(f"""
        SELECT address_id AS point_id, jobs_400m, transit_entries_400m
        FROM analysis.address
        WHERE frame = '{fc.FRAME}'
    """).fetchdf()
    out = out.merge(addr, on="point_id", how="left")
    out["log_jobs"] = np.log1p(out["jobs_400m"].fillna(0.0))
    out["log_transit"] = np.log1p(out["transit_entries_400m"].fillna(0.0))
    return out


# ---------------------------------------------------------------------------
# 2. the GBM's own blocked out-of-sample routine (checklist item 2)
# ---------------------------------------------------------------------------
def fold_index(panel: pd.DataFrame, n_folds: int = fc.N_FOLDS,
              seed: int = fc.RNG_SEED) -> np.ndarray:
    """Per-row fold id (0..n_folds-1), from `forecast._nta_folds` -- the
    IDENTICAL partition `blocked_oos_predictions` uses internally, exposed as
    a plain array so the apples-to-apples rule (memo §2) can be pinned by a
    test on the fold assignment itself, not trusted via a downstream AUC."""
    idx = panel.reset_index(drop=True)
    nta = idx["nta_code"].fillna("NA")
    out = np.full(len(idx), -1, dtype=int)
    for i, fold in enumerate(fc._nta_folds(idx, n_folds=n_folds, seed=seed)):
        out[nta.isin(fold).to_numpy()] = i
    return out


def _prep_gbm_X(df: pd.DataFrame, cols: list[str], categorical_col: str) -> pd.DataFrame:
    X = df[list(cols) + [categorical_col]].copy()
    for c in cols:
        X[c] = X[c].astype(float)
    X[categorical_col] = X[categorical_col].astype("category")
    return X


def _fit_gbm(train_df: pd.DataFrame, cols: list[str], categorical_col: str,
            params: dict):
    from sklearn.ensemble import HistGradientBoostingClassifier

    X = _prep_gbm_X(train_df, cols, categorical_col)
    y = train_df["y"].to_numpy(dtype=float)
    model = HistGradientBoostingClassifier(categorical_features=[categorical_col],
                                           **params)
    model.fit(X, y)
    return model


def _tune_inner_params(train_rows: pd.DataFrame, cols: list[str],
                       categorical_col: str, seed: int) -> dict:
    """memo §4 -- the grid search inside ONE outer fold's training NTAs: a
    3-fold NTA-blocked inner CV (`_nta_folds(train_rows, n_folds=3,
    seed=RNG_SEED+1)`), picked by mean inner AUC, refit on the full outer-
    training rows by the caller."""
    idx = train_rows.reset_index(drop=True)
    nta = idx["nta_code"].fillna("NA")
    inner_folds = fc._nta_folds(idx, n_folds=3, seed=seed)
    best_params, best_score = dict(DEFAULT_GBM_PARAMS), float("-inf")
    for params in GBM_GRID:
        scores = []
        for fold in inner_folds:
            te = nta.isin(fold).to_numpy()
            tr = ~te
            if (te.sum() == 0 or idx.loc[tr, "y"].nunique() < 2
                    or idx.loc[te, "y"].nunique() < 2):
                continue
            m = _fit_gbm(idx[tr], cols, categorical_col, params)
            p = m.predict_proba(_prep_gbm_X(idx[te], cols, categorical_col))[:, 1]
            a = rd._auc(idx.loc[te, "y"].to_numpy(dtype=float), p)
            if not np.isnan(a):
                scores.append(a)
        mean_score = float(np.mean(scores)) if scores else float("-inf")
        if mean_score > best_score:
            best_score, best_params = mean_score, params
    return dict(best_params)


def blocked_oos_predictions_gbm(panel: pd.DataFrame, cols: list[str], *,
                                categorical_col: str = "category",
                                n_folds: int = fc.N_FOLDS,
                                seed: int = fc.RNG_SEED,
                                tune: bool = False) -> np.ndarray:
    """The challenger's out-of-sample p for every row, on the SAME NTA
    partition `forecast.blocked_oos_predictions` uses -- ONE pooled model per
    fold, NO per-category refits (memo §2: fifteen boosted refits on thin
    categories is where the overfit lives; if the GBM loses on a thin
    category that is reported, not hidden)."""
    idx = panel.reset_index(drop=True)
    nta = idx["nta_code"].fillna("NA")
    preds = np.full(len(idx), np.nan)
    Xall = _prep_gbm_X(idx, cols, categorical_col)

    from sklearn.ensemble import HistGradientBoostingClassifier

    for fold in fc._nta_folds(idx, n_folds=n_folds, seed=seed):
        te = nta.isin(fold).to_numpy()
        tr = ~te
        if te.sum() == 0 or idx.loc[tr, "y"].nunique() < 2:
            continue
        params = (_tune_inner_params(idx[tr], cols, categorical_col, seed + 1)
                  if tune else DEFAULT_GBM_PARAMS)
        model = HistGradientBoostingClassifier(
            categorical_features=[categorical_col], **params)
        model.fit(Xall[tr], idx.loc[tr, "y"].to_numpy(dtype=float))
        preds[np.flatnonzero(te)] = model.predict_proba(Xall[te])[:, 1]
    return preds


# ---------------------------------------------------------------------------
# 3. intersection mask (checklist item 3)
# ---------------------------------------------------------------------------
def intersection_auc(y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray) -> dict:
    """AUC for both `p_a` (the logit) and `p_b` (the GBM), computed on the
    SAME mask: a fold either model skipped (separation in the logit, no
    variance in a GBM training fold) drops that row from BOTH computations,
    or the challenger is credited on rows the incumbent was never asked
    (memo §2)."""
    y = np.asarray(y, dtype=float)
    p_a = np.asarray(p_a, dtype=float)
    p_b = np.asarray(p_b, dtype=float)
    ok = ~np.isnan(p_a) & ~np.isnan(p_b)
    n = int(ok.sum())
    scoreable = n > 0 and len(set(y[ok].tolist())) > 1
    return {"ok": ok, "n": n,
            "auc_a": float(rd._auc(y[ok], p_a[ok])) if scoreable else float("nan"),
            "auc_b": float(rd._auc(y[ok], p_b[ok])) if scoreable else float("nan")}


# ---------------------------------------------------------------------------
# 4. the verdict — six criteria (checklist item 4)
# ---------------------------------------------------------------------------
def evaluate_verdict(result: dict, *, auc_floor: float = AUC_FLOOR,
                     max_gap: float = fc.MAX_CALIBRATION_GAP) -> dict:
    """W1-W6, pre-declared in memo §3. `result` carries:

        delta_auc, ci_nta (2-tuple), brier_gbm, brier_logit, log_loss_gbm,
        log_loss_logit, calibration_gap_gbm, category_table (list of
        {category, n, both_classes, delta_auc}), moran_gbm, moran_logit.

    Returns `wins` (True only if all six hold), `verdict_reason` (naming
    every criterion that failed), and `status` in {"wins", "fails",
    "report_only"} -- FAILS is the harder of the two non-win outcomes
    (negative delta, a CI containing zero, or >=2 hard category regressions;
    memo §3), recorded as a null rather than hidden, the way D111's Citi Bike
    test was."""
    reasons: list[str] = []

    delta = result["delta_auc"]
    w1_ok = bool(delta == delta and delta >= auc_floor)
    if not w1_ok:
        reasons.append(f"W1 (+{auc_floor:.3f} AUC floor) failed: "
                       f"delta AUC {delta:.4f} < {auc_floor:.3f}")

    lo, hi = result["ci_nta"]
    contains_zero = not (lo == lo and hi == hi) or (lo <= 0.0 <= hi)
    if contains_zero:
        reasons.append("W2 (bootstrap CI excludes 0) failed: NTA-clustered "
                       f"95% CI [{lo:.4f}, {hi:.4f}] contains 0")

    w3_ok = bool(result["brier_gbm"] < result["brier_logit"]
                and result["log_loss_gbm"] < result["log_loss_logit"])
    if not w3_ok:
        reasons.append(
            "W3 (Brier and log loss both lower) failed: Brier "
            f"{result['brier_gbm']:.4f} vs {result['brier_logit']:.4f}, log "
            f"loss {result['log_loss_gbm']:.4f} vs {result['log_loss_logit']:.4f}")

    gap = result["calibration_gap_gbm"]
    w4_ok = bool(gap == gap and gap <= max_gap)
    if not w4_ok:
        reasons.append(f"W4 (calibration max decile gap <= {max_gap:.2f}) "
                       f"failed: gap {gap:.3f}")

    cats = result["category_table"]
    regressed = [c for c in cats if c.get("n", 0) >= 500 and c.get("both_classes")
                and c.get("delta_auc") is not None and c["delta_auc"] < -0.02]
    improved = [c for c in cats
               if c.get("delta_auc") is not None and c["delta_auc"] > 0]
    w5_ok = not regressed and len(improved) >= 8
    if not w5_ok:
        bits = []
        if regressed:
            names = ", ".join(c["category"] for c in regressed)
            bits.append(f"{len(regressed)} category(ies) regressed >0.02 AUC "
                       f"({names})")
        if len(improved) < 8:
            bits.append(f"only {len(improved)}/{len(cats)} categories "
                       "improved (need >= 8)")
        reasons.append("W5 (per-category no-regression) failed: "
                       + "; ".join(bits))

    mg, ml = result["moran_gbm"], result["moran_logit"]
    w6_ok = bool(mg == mg and ml == ml and mg <= ml)
    if not w6_ok:
        reasons.append("W6 (residual Moran's I not higher than the logit's) "
                       f"failed: GBM {mg:.4f} vs logit {ml:.4f}")

    wins = not reasons
    fails_hard = (bool(delta == delta and delta < 0) or contains_zero
                 or len(regressed) >= 2)
    status = "wins" if wins else ("fails" if fails_hard else "report_only")
    reason = ("WINS: all six criteria (W1-W6) hold" if wins
             else "; ".join(reasons))
    return {"wins": wins, "verdict_reason": reason, "status": status,
            "criteria": {"W1": w1_ok, "W2": not contains_zero, "W3": w3_ok,
                        "W4": w4_ok, "W5": w5_ok, "W6": w6_ok}}


# ---------------------------------------------------------------------------
# 5/6. bootstrap + Moran's I wiring, per arm (checklist items 5, 6)
# ---------------------------------------------------------------------------
def _build_comparison(panel: pd.DataFrame, points: pd.DataFrame, y: np.ndarray,
                      oos_logit: np.ndarray, oos_gbm: np.ndarray, inter: dict,
                      *, tuned: bool, cols_gbm: list[str]) -> dict:
    ok = inter["ok"]
    auc_logit, auc_gbm = inter["auc_a"], inter["auc_b"]
    delta = ((auc_gbm - auc_logit) if (auc_gbm == auc_gbm and auc_logit == auc_logit)
             else float("nan"))

    cal_gbm = fc.calibration(y[ok], oos_gbm[ok])
    gap_gbm = fc.calibration_max_gap(cal_gbm)
    brier_logit = fc._brier(y[ok], oos_logit[ok])
    brier_gbm = fc._brier(y[ok], oos_gbm[ok])
    ll_logit = fc._log_loss(y[ok], oos_logit[ok])
    ll_gbm = fc._log_loss(y[ok], oos_gbm[ok])

    fold_map = rd.nta_fold_map(panel)
    oof = rd._oof_frame(panel, fold_map, {"p_base": oos_logit, "p_treat": oos_gbm})
    ci_nta = rd.bootstrap_delta(oof, treat="p_treat", base="p_base",
                                cluster="nta_code")
    ci_cd = rd.bootstrap_delta(oof, treat="p_treat", base="p_base",
                               cluster="cd_code")

    panel_ll = panel.merge(points[["point_id", "lon", "lat"]], on="point_id",
                           how="left")
    moran = rd.residual_morans_i(panel_ll, oof, pred_cols=("p_base", "p_treat"))
    moran_logit, moran_gbm = moran.get("mean_base"), moran.get("mean_treat")

    cat_arr = panel["category"].to_numpy()
    category_table = []
    for c in sorted(panel["category"].unique()):
        m = ok & (cat_arr == c)
        n = int(m.sum())
        both = bool(n and len(set(y[m].tolist())) > 1)
        a_l = float(rd._auc(y[m], oos_logit[m])) if both else float("nan")
        a_g = float(rd._auc(y[m], oos_gbm[m])) if both else float("nan")
        d = (a_g - a_l) if (a_g == a_g and a_l == a_l) else None
        category_table.append({"category": str(c), "n": n, "both_classes": both,
                               "auc_logit": a_l, "auc_gbm": a_g, "delta_auc": d})

    verdict = evaluate_verdict({
        "delta_auc": delta, "ci_nta": tuple(ci_nta["ci"]),
        "brier_gbm": brier_gbm, "brier_logit": brier_logit,
        "log_loss_gbm": ll_gbm, "log_loss_logit": ll_logit,
        "calibration_gap_gbm": gap_gbm, "category_table": category_table,
        "moran_gbm": moran_gbm if moran_gbm is not None else float("nan"),
        "moran_logit": moran_logit if moran_logit is not None else float("nan")})

    return {"n_scored": inter["n"], "auc_logit": auc_logit, "auc_gbm": auc_gbm,
            "delta_auc": delta, "brier_logit": brier_logit, "brier_gbm": brier_gbm,
            "log_loss_logit": ll_logit, "log_loss_gbm": ll_gbm,
            "calibration_gbm": cal_gbm, "calibration_gap_gbm": gap_gbm,
            "bootstrap_ci_nta": ci_nta, "bootstrap_ci_cd": ci_cd,
            "moran_logit": moran_logit, "moran_gbm": moran_gbm,
            "residual_morans_i": moran, "category_table": category_table,
            "tuned": bool(tuned), "feature_list_gbm": list(cols_gbm),
            "verdict": verdict}


# ---------------------------------------------------------------------------
# 7/8. the CLI orchestrator (checklist items 7, 8)
# ---------------------------------------------------------------------------
def _row_counts(con) -> dict:
    out = {}
    for t in ("forecast", "forecast_run", "forecast_outcome"):
        try:
            out[t] = int(con.execute(
                f"SELECT count(*) FROM analysis.{t}").fetchone()[0])
        except Exception:                   # noqa: BLE001 -- table absent yet
            out[t] = None
    return out


def run_challenge(con, *, month: str, sample_n: int = fc.FIT_SAMPLE_N,
                  radius_m: float = fc.RADIUS_M,
                  horizon: int = fc.HORIZON_MONTHS,
                  categories: tuple[str, ...] = fc.ALL_CATEGORIES,
                  no_anachronistic: bool = False, tune: bool = False,
                  out_dir: pathlib.Path | str | None = None,
                  progress=None) -> dict:
    """The three-rung ablation (memo §7 item 1) plus both anachronistic arms
    (memo §7 item 3), against `con` -- which the CLI opens
    `connect_read(read_only=True)`. Never writes to `analysis.forecast*`;
    `_row_counts` before and after are asserted equal by the caller's test,
    not merely hoped equal.

    `con` should be a READ handle. This function opens no write handle at
    all -- there is nothing here for one to be missing from."""
    say = progress or (lambda *_: None)
    fc.validate_month(month)
    ver, shash = fc.resolve_version(con, horizon=horizon, radius_m=radius_m)
    n_before = _row_counts(con)

    say(f"supply hash this challenge measures against: {shash}")
    say("1/7 fit panel — build_fit_panel, the incumbent's own two stacked folds")
    points = fc.load_points(con, limit=sample_n)
    panel_raw, support = fc.build_fit_panel(
        con, month, radius_m=radius_m, horizon=horizon, sample_n=sample_n,
        categories=categories, anchor=points, points=points)

    say("2/7 rung 1 — the shipped two-stage logit, via fit() unmodified")
    res1 = fc.fit(panel_raw, support=support)
    fitted_cats = res1["fitted_categories"]
    p = panel_raw.dropna(subset=["log_score", "y"]).copy()
    y = p["y"].to_numpy(dtype=float)
    oos_rung1 = fc.blocked_oos_predictions(p, list(fc.FEATURE_LIST),
                                           per_category=fitted_cats)
    ok1 = ~np.isnan(oos_rung1)
    auc_rung1 = (float(rd._auc(y[ok1], oos_rung1[ok1]))
                if ok1.sum() and len(set(y[ok1].tolist())) > 1 else float("nan"))

    say("3/7 augment() — the three t0-true features, per fold's own t0")
    p_aug = augment(con, p, points, radius_m=radius_m, categories=categories,
                    horizon=horizon)

    say("4/7 rung 2 — same two-stage logit form, given the new features")
    cols_rung2 = list(fc.FEATURE_LIST) + list(RUNG2_EXTRA)
    oos_rung2 = fc.blocked_oos_predictions(p_aug, cols_rung2,
                                           per_category=fitted_cats)
    ok2 = ~np.isnan(oos_rung2)
    auc_rung2 = (float(rd._auc(y[ok2], oos_rung2[ok2]))
                if ok2.sum() and len(set(y[ok2].tolist())) > 1 else float("nan"))

    say("5/7 rung 3 — pooled GBM, both anachronistic arms")
    cols_gbm_base = list(cols_rung2)
    cols_gbm_with = cols_gbm_base + list(ANACHRONISTIC_FEATURES)

    def _run_arm(cols_gbm: list[str], label: str) -> dict:
        say(f"   {label}: untuned default")
        oos_gbm = blocked_oos_predictions_gbm(p_aug, cols_gbm)
        inter = intersection_auc(y, oos_rung1, oos_gbm)
        tuned = False
        default_delta = (inter["auc_b"] - inter["auc_a"]
                         if (inter["auc_b"] == inter["auc_b"]
                             and inter["auc_a"] == inter["auc_a"]) else float("nan"))
        if tune and not (default_delta == default_delta
                        and default_delta >= AUC_FLOOR):
            say(f"   {label}: default missed the +{AUC_FLOOR:.3f} floor -- "
               "--tune requested, running the 8-point grid per outer fold")
            oos_gbm = blocked_oos_predictions_gbm(p_aug, cols_gbm, tune=True)
            inter = intersection_auc(y, oos_rung1, oos_gbm)
            tuned = True
        return _build_comparison(p_aug, points, y, oos_rung1, oos_gbm, inter,
                                 tuned=tuned, cols_gbm=cols_gbm)

    arm_without = _run_arm(cols_gbm_base, "without anachronistic controls")
    arm_with = _run_arm(cols_gbm_with, "with anachronistic jobs/transit controls")

    say("6/7 verdict — the stricter arm is the headline whenever they disagree")
    arms_agree = bool(arm_without["verdict"]["wins"] == arm_with["verdict"]["wins"])
    headline_key = ("without_anachronistic"
                    if (no_anachronistic or not arms_agree)
                    else "with_anachronistic")
    both_arms = {"without_anachronistic": arm_without, "with_anachronistic": arm_with}
    headline = both_arms[headline_key]

    say("7/7 write — data/forecast_challenge/<month>.json, nothing to analysis.forecast*")
    n_after = _row_counts(con)

    payload = {
        "issued_month": month,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model_version_compared": ver,
        "supply_hash": shash,
        "sample_n": int(sample_n),
        "radius_m": float(radius_m),
        "horizon_months": int(horizon),
        "n_rows": res1["n_rows"], "n_addresses": res1["n_addresses"],
        "n_ntas": res1["n_ntas"],
        "feature_list_rung1": list(fc.FEATURE_LIST),
        "feature_list_rung2": cols_rung2,
        "feature_list_rung3": cols_gbm_base,
        "anachronistic_features": list(ANACHRONISTIC_FEATURES),
        "default_gbm_params": DEFAULT_GBM_PARAMS,
        "hyperparameter_grid": [dict(g) for g in GBM_GRID],
        "tune_requested": bool(tune),
        "rungs": {
            "rung1_logit_baseline": {
                "auc": auc_rung1, "n_scored": int(ok1.sum()),
                "matches_fit_auc_blocked": bool(
                    auc_rung1 == auc_rung1 and res1["auc_blocked"] == res1["auc_blocked"]
                    and abs(auc_rung1 - res1["auc_blocked"]) < 1e-9)},
            "rung2_logit_plus_t0_true_features": {
                "auc": auc_rung2, "n_scored": int(ok2.sum())},
        },
        "headline_arm": headline_key,
        "arms_agree": arms_agree,
        "both_arms": both_arms,
        "wins": headline["verdict"]["wins"],
        "verdict_reason": headline["verdict"]["verdict_reason"],
        "verdict_status": headline["verdict"]["status"],
        "forecast_row_counts_before": n_before,
        "forecast_row_counts_after": n_after,
        "row_counts_unchanged": bool(n_before == n_after),
    }

    out_path = pathlib.Path(out_dir) if out_dir else DEFAULT_OUT_DIR
    out_path.mkdir(parents=True, exist_ok=True)
    dest = out_path / f"{month}.json"
    dest.write_text(json.dumps(payload, indent=2, default=str))
    payload["_out_path"] = str(dest)
    return payload
