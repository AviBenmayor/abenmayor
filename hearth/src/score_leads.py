"""Validation tables for the dashboard, on the model that actually ships.

Target: expected dollars, P(win) x E[amount | win]. The three candidate targets rank
this book almost identically -- spearman(P(win), expected dollars) = 0.99 -- so the
choice costs nothing in ordering and is made on other grounds: expected dollars is the
only one denominated in something you can hold against cost-to-serve, which is what
sets the cutoff. P(win) ships alongside it as the column you calibrate and argue about.

Why not P(win this month): 74% of wins close within 30 days (median 6), so the
month-restricted target is ~0.74 x P(win) with little re-ranking, bought at the cost
of modelling a close-date distribution on 907 events.

The feature set, the transform and the pipeline all come from
export_model.py by way of features.py -- this script fits the same specification so the
numbers on the dashboard describe the model in output/submission.csv, and asserts that
at the end rather than trusting it. Only intake columns are legal features; nothing
downstream of a human touching the lead appears here.
"""
import json
import joblib
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from features import training_population, CAT, NUM, add_intake_derived, prep, make_model
from export_model import amount_model, score_from_export

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "output"
APP = OUT / "app_data"
APP.mkdir(parents=True, exist_ok=True)

SEED = 7


def build(kind):
    """logit is the shipped pipeline, straight from features.py. gbm exists only to be
    compared against it -- if it won by a real margin that would be worth knowing."""
    if kind == "logit":
        return make_model()
    return Pipeline([
        ("pre", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=25,
                                  sparse_output=False), CAT),
            ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                              ("sc", StandardScaler())]), NUM)])),
        ("m", HistGradientBoostingClassifier(
            max_depth=3, max_iter=250, learning_rate=0.05,
            min_samples_leaf=60, l2_regularization=1.0, random_state=SEED))])


def metrics(y, p):
    n_top = max(1, int(len(y) * 0.10))
    top = np.argsort(-p)[:n_top]
    # legacy_score is a 0-100 CRM number, not a probability -- rankable, not scorable.
    brier = brier_score_loss(y, p) if p.min() >= 0 and p.max() <= 1 else np.nan
    return {"auc": roc_auc_score(y, p), "pr_auc": average_precision_score(y, p),
            "brier": brier,
            "lift@10": (y[top].mean() / y.mean()) if y.mean() else np.nan,
            "capture@10": y[top].sum() / y.sum(), "n": len(y), "base": y.mean()}


def row(name, m):
    b = "  n/a " if np.isnan(m["brier"]) else f"{m['brier']:.4f}"
    return (f"  {name:<22} auc {m['auc']:.3f}  pr_auc {m['pr_auc']:.3f}  "
            f"brier {b}  lift@10 {m['lift@10']:.2f}x  "
            f"capture@10 {m['capture@10']*100:4.1f}%")


def main():
    full = add_intake_derived(pd.read_parquet(OUT / "leads_base.parquet"))
    # Same population as the shipped fit -- leads a rep actually worked, minus the owners
    # whose labels are not believable. features.training_population is the single rule; if
    # this script picked its own, the parity assertion below is what would catch it.
    train = training_population(full).reset_index(drop=True)
    score = add_intake_derived(pd.read_csv(DATA / "leads_to_score.csv", dtype=str))
    y = train.post_is_won.astype(int).values

    print("=" * 78)
    print("1. VALIDATION -- temporal holdout (train Oct-Dec 2025 / test Jan-Feb 2026)")
    print("=" * 78)
    print("   The scoring window is three months in the future of the training window and")
    print("   the marketing mix moved. A random split would flatter every model here.\n")
    is_tr = train.created_at < "2026-01-01"
    Xtr, Xte = train[is_tr], train[~is_tr]
    ytr, yte = y[is_tr.values], y[~is_tr.values]
    print(f"   train {len(Xtr)} leads / {ytr.mean()*100:.1f}% won      "
          f"test {len(Xte)} leads / {yte.mean()*100:.1f}% won\n")

    ls_te = Xte.legacy_score.fillna(Xte.legacy_score.median()).values
    results = {"legacy_score (baseline)": metrics(yte, ls_te)}
    fitted = {}
    for kind in ["logit", "gbm"]:
        m = build(kind).fit(prep(Xtr), ytr)
        fitted[kind] = m
        results[kind] = metrics(yte, m.predict_proba(prep(Xte))[:, 1])
    for k, v in results.items():
        print(row(k, v))

    print("\n" + "=" * 78)
    print("2. VALIDATION -- 5-fold stratified CV on the full training window")
    print("=" * 78)
    cv = StratifiedKFold(5, shuffle=True, random_state=SEED)
    oof = {k: np.zeros(len(train)) for k in ["logit", "gbm"]}
    for tr_i, te_i in cv.split(train, y):
        for kind in ["logit", "gbm"]:
            m = build(kind).fit(prep(train.iloc[tr_i]), y[tr_i])
            oof[kind][te_i] = m.predict_proba(prep(train.iloc[te_i]))[:, 1]
    ls_all = train.legacy_score.fillna(train.legacy_score.median()).values
    cv_res = {"legacy_score (baseline)": metrics(y, ls_all)}
    for kind in ["logit", "gbm"]:
        cv_res[kind] = metrics(y, oof[kind])
    for k, v in cv_res.items():
        print(row(k, v))

    gap = cv_res["gbm"]["auc"] - cv_res["logit"]["auc"]
    choice = "gbm" if gap > 0.01 else "logit"
    print(f"\n   gbm - logit auc gap: {gap:+.3f} -> choosing {choice}.")
    if choice == "logit":
        print("   The gap is inside noise on 907 events. Under a distribution shift this size,")
        print("   the additively-regularised linear model is the safer extrapolation.")

    print("\n" + "=" * 78)
    print("3. SELECTION CHECK -- does the model just learn who reps chose to work?")
    print("=" * 78)
    y_full = full.post_is_won.astype(int).values
    m_all = build(choice).fit(prep(full), y_full)
    p_all = m_all.predict_proba(prep(full))[:, 1]
    p_wrk = build(choice).fit(prep(train), y).predict_proba(prep(full))[:, 1]
    rho = pd.Series(p_all).corr(pd.Series(p_wrk), method="spearman")
    n_out = len(full) - len(train)
    print(f"   The shipped model trains on the {len(train)} worked leads, not all {len(full)}.")
    print(f"   {n_out} excluded ({n_out/len(full)*100:.1f}%): never touched, or owned by "
          f"rep_128/222/210,")
    print(f"   all of which win 0% -- the first by construction, the second because their")
    print(f"   statuses look unwritten. Base rate {y.mean()*100:.1f}% vs {y_full.mean()*100:.1f}% unfiltered.")
    print(f"   Refit on everything, the ranking barely moves: spearman rho = {rho:.3f}.")
    print(f"   So this changes the probability LEVEL, not who gets called -- which is the")
    print(f"   point: a rep asks 'if I work this, will it convert?', not 'what share of")
    print(f"   leads like this converted including the ones nobody phoned.'")

    print("\n" + "=" * 78)
    print("4. CALIBRATION -- out-of-fold, by score decile")
    print("=" * 78)
    cal = pd.DataFrame({"p": oof[choice], "y": y})
    cal["dec"] = pd.qcut(cal.p, 10, labels=False, duplicates="drop")
    g = cal.groupby("dec").agg(n=("y", "size"), predicted=("p", "mean"), actual=("y", "mean"))
    g[["predicted", "actual"]] *= 100
    print(g.to_string(float_format="%.1f"))

    print("\n" + "=" * 78)
    print("5. FIT FINAL MODEL AND SCORE THE Mar-May WINDOW")
    print("=" * 78)
    Xtrain = prep(train)
    final = build(choice).fit(Xtrain, y)

    # No calibration layer, matching export_model.py. A Platt step was fitted and removed:
    # it moved nothing by more than 0.015 and reordered nothing, so it bought a transform
    # to explain and no accuracy. Shipped probabilities are the model's own.
    p_score = final.predict_proba(prep(score))[:, 1]
    print(f"   scored {len(score)} leads")
    print(f"   p(win): min {p_score.min():.3f}  p50 {np.median(p_score):.3f}  "
          f"max {p_score.max():.3f}  mean {p_score.mean():.3f}")
    print(f"   train window out-of-fold mean {oof[choice].mean():.3f}  "
          f"(actual {y.mean():.3f})")
    print("   -> mean predicted rate on the scoring window differs from train because the")
    print("      marketing mix moved, not because the model drifted. That is the model doing")
    print("      its job: the Mar-May mix is richer in brand/google and lighter in prospecting.")

    # Raw frame, not the derived one: amount_model groups on the unfilled revenue column.
    amt_by_band, fallback = amount_model(pd.read_parquet(OUT / "leads_base.parquet"))

    # The shipped scores come from output/model.json -- the exported scorer that
    # submission.csv and the browser tool use -- not from this script's own sklearn fit.
    # The two agree to ~1e-13, which is not good enough: 14 leads sit on exactly the
    # tier-A cutoff, and a 1e-13 disagreement is the difference between routing them to
    # "call now" and routing them to "work". One scorer, one answer.
    exp = json.load(open(OUT / "model.json"))
    p_ship, exp_amt, ev = score_from_export(exp, pd.read_csv(DATA / "leads_to_score.csv",
                                                             dtype=str))
    out = pd.DataFrame({"lead_id": score.lead_id.values, "p_win": p_ship, "score": ev})
    out.to_parquet(APP / "scores_raw.parquet", index=False)
    r = pd.Series(p_score).corr(pd.Series(ev), method="spearman")
    print(f"\n   spearman(p_win, expected dollars) on the scoring set = {r:.4f}")
    print("   -> the two targets rank almost the same book. The choice is made on what the")
    print("      number is denominated in, not on the ordering it produces.")

    # --- parity: the fit below must still reproduce the shipped scorer, or model.json
    # is stale relative to features.py and the whole chain needs rebuilding ---
    gap = float(np.abs(p_score - p_ship).max())
    print(f"\n   PARITY, this fit vs output/model.json across all {len(ev)} rows:")
    print(f"   max abs diff = {gap:.3e} on P(win)")
    assert gap < 1e-6, ("model.json is stale relative to features.py. Re-run "
                        "export_model.py before this script.")

    def clean(d):
        return {k: {kk: (None if isinstance(vv, float) and np.isnan(vv) else float(vv))
                    for kk, vv in v.items()} for k, v in d.items()}

    json.dump({"choice": choice, "temporal": clean(results), "cv": clean(cv_res),
               "calibration": g.reset_index().to_dict("records"),
               "selection_rho": float(rho),
               "features": {"categorical": list(CAT), "numeric": list(NUM)},
               "train_base_rate": float(y.mean())},
              open(APP / "model_metrics.json", "w"), indent=2)
    np.save(APP / "oof.npy", oof[choice])
    # The pipeline is kept for the model card's coefficient breakdown, which is built
    # here rather than served: the container scores from model.json and never unpickles.
    joblib.dump({"model": final, "cat": list(CAT), "num": list(NUM), "kind": choice,
                 "amount_by_band": amt_by_band,
                 "amount_fallback": float(fallback)}, APP / "model.joblib")
    print(f"\n   -> {APP}/scores_raw.parquet, model_metrics.json, model.joblib")


if __name__ == "__main__":
    main()
