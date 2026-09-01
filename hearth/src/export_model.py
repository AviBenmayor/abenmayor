"""Fit the final model and export it as plain JSON the browser can score with.

Rather than reimplementing sklearn's one-hot + infrequent-category logic in JavaScript,
we collapse the fitted linear model into a per-value coefficient lookup. For a linear
model on one-hot features that is exact, not an approximation:

    logit = intercept + SUM(coef[feature][value]) + ((legacy - mean)/scale) * coef_legacy

Unseen categories fall through to the same __INFREQUENT__ bucket sklearn would use.
"""
import pandas as pd, numpy as np, json, warnings
from pathlib import Path
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict
from sklearn.metrics import roc_auc_score
warnings.filterwarnings("ignore")

# The feature set, the transform and the pipeline all come from features.py so that the
# shipped fit, the ablation, the dashboard's metrics and the live scoring endpoint cannot
# disagree about what the model is.
from features import CAT, NUM, INFREQ, NA, prep, make_model as make, training_population
from scorer import score_from_export

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"


def export(pipe, amount_map, overall_amt, cutoffs, legacy_range):
    pre = pipe.named_steps["pre"]
    ohe = pre.named_transformers_["cat"]
    num_pipe = pre.named_transformers_["num"]
    coefs = pipe.named_steps["m"].coef_[0]
    names = pre.get_feature_names_out()
    lut = {c: {} for c in CAT}
    n_cat = sum(len(c) for c in ohe.categories_)  # pre-infrequent count, unused directly
    for name, w in zip(names, coefs):
        kind, rest = name.split("__", 1)
        if kind == "cat":
            for c in sorted(CAT, key=len, reverse=True):
                if rest.startswith(c + "_"):
                    val = rest[len(c) + 1:]
                    lut[c][INFREQ if val == "infrequent_sklearn" else val] = float(w)
                    break
    # Any training value sklearn folded into the infrequent bucket must resolve there too.
    for i, c in enumerate(CAT):
        inf = ohe.infrequent_categories_[i]
        if inf is not None:
            for v in inf:
                lut[c][str(v)] = lut[c].get(INFREQ, 0.0)
        lut[c].setdefault(INFREQ, 0.0)
    return dict(
        intercept=float(pipe.named_steps["m"].intercept_[0]),
        categorical=lut,
        numeric=dict(legacy_score=dict(
            median=float(num_pipe.named_steps["imp"].statistics_[0]),
            mean=float(num_pipe.named_steps["sc"].mean_[0]),
            scale=float(num_pipe.named_steps["sc"].scale_[0]),
            coef=float(coefs[list(names).index("num__legacy_score")]),
            lo=float(legacy_range[0]), hi=float(legacy_range[1]))),
        amount=dict(by_band={str(k): float(v) for k, v in amount_map.items()},
                    default=float(overall_amt)),
        tier_cutoffs=cutoffs,
        infrequent_key=INFREQ, na_key=NA, features=dict(categorical=CAT, numeric=NUM))


def amount_model(df, trim=0.10, min_n=10):
    """E[amount | win] per revenue band: a trimmed mean, not a shrunk one.

    Trimming and shrinkage fix different problems, and shrinkage was the wrong one here.
    Shrinkage corrects a mean that is noisy from a small sample. But within-band variance
    is low (CV 0.28), so even the n=18 band has a standard error of ~$115 -- shrinking it
    toward the global mean moved it 3.1 SE, correcting a problem it did not have and
    biasing the two bands where the dollars are largest.

    Skew is mild (1.61; only 0.6% of wins sit above 2x the median), so a 10% trimmed mean
    lands within ~1% of the raw mean while staying robust to the one zero-amount win and
    the handful of extreme deals. It changes the ranking barely (rho 0.999 vs shrunk) but
    it is defensible, which "pseudo-count of 30" was not.

    Bands with fewer than min_n wins cannot support either estimator, so they fall back to
    the global trimmed mean EXPLICITLY rather than to a shrunk value that looks
    band-specific but is really the global mean wearing a band's name. Personal Loan
    Inquiry has exactly one win; it should not get its own number.

    Grouped on the raw column, so a lead whose revenue band is missing falls through to
    the global mean rather than joining a "__NA__" band of its own. This is the one the
    exported model.json and the browser tool encode, and score_leads calls this function
    rather than rebuilding it so the dashboard cannot pick the other.
    """
    won = df[df.post_is_won]
    # Trim the global fallback too -- a trimmed per-band estimate backed by an untrimmed
    # global mean would be inconsistent at exactly the bands we trust least.
    overall = float(stats.trim_mean(won.post_amount.dropna().values, trim))
    out = {}
    for band, g in won.groupby("contractor_annual_revenue"):
        v = g.post_amount.dropna().values
        out[band] = float(stats.trim_mean(v, trim)) if len(v) >= min_n else overall
    return out, overall


def oof_predictions(X, y):
    """Out-of-fold predicted probabilities, for honest in-sample reporting.

    No calibration layer is applied to the shipped model. A Platt step was fitted and
    removed: on this model it moved no prediction by more than 0.015, changed no
    ranking (it is monotone by construction), and added a transform that has to be
    explained before anyone can trust the number underneath it. The probabilities the
    tool shows are the model's own.

    What calibration would NOT have fixed is the real level problem: the model trains on
    a 16.5% base rate and scores a window whose rate has risen every month, so displayed
    probabilities run low. That is documented in the memo rather than papered over with a
    correction fitted to a period we are not scoring.
    """
    return cross_val_predict(make(), X, y, cv=5, method="predict_proba")[:, 1]


if __name__ == "__main__":
    full = pd.read_parquet(OUT / "leads_base.parquet")
    # Train on leads a rep actually worked -- see features.training_population for why this
    # is a choice about which question the score answers, not a cleaning step.
    df = training_population(full)
    print(f"training population: {len(df)} of {len(full)} leads "
          f"({len(df)/len(full)*100:.0f}%), base rate {df.post_is_won.mean()*100:.1f}% "
          f"(vs {full.post_is_won.mean()*100:.1f}% unfiltered)")
    y = df.post_is_won.values.astype(int)
    X = prep(df)

    pipe = make().fit(X, y)
    oof = oof_predictions(X, y)
    print(f"in-sample AUC {roc_auc_score(y, pipe.predict_proba(X)[:,1]):.4f}   "
          f"5-fold OOF AUC {roc_auc_score(y, oof):.4f}")
    print("no calibration layer: shipped probabilities are the model's own")

    amount_map, overall = amount_model(df)

    lts = pd.read_csv(ROOT / "data" / "leads_to_score.csv", dtype=str)
    # Legacy-score clamp range spans everything we might ever score, not just the
    # training rows, so a valid score outside the trained range is clamped, not rejected.
    ls_all = pd.to_numeric(full.legacy_score, errors="coerce")
    exp = export(pipe, amount_map, overall, {}, (ls_all.min(), ls_all.max()))
    _, _, ev = score_from_export(exp, lts)
    q = pd.Series(ev).rank(pct=True)
    exp["tier_cutoffs"] = {t: float(np.quantile(ev, c)) for t, c in
                           [("A", .90), ("B", .70), ("C", .40)]}

    # --- parity check: sklearn pipeline vs the exported lookup ---
    p_sk = pipe.predict_proba(prep(lts))[:, 1]
    p_ex, amt, ev = score_from_export(exp, lts)
    print(f"\nPARITY sklearn vs export on all {len(lts)} scoring rows: "
          f"max abs diff = {np.abs(p_sk - p_ex).max():.3e}")
    assert np.abs(p_sk - p_ex).max() < 1e-9, "export does not reproduce the pipeline"

    (OUT / "model.json").write_text(json.dumps(exp, indent=1))
    print(f"wrote output/model.json  ({(OUT/'model.json').stat().st_size/1024:.0f} KB)")

    # Tiers come from fixed score cutoffs, not from percentile rank within the batch.
    # A rep who loads 50 leads must not get 5 "tier A" that are really mediocre -- tier has
    # to mean the same thing in every file, so the cutoffs are frozen into the model.
    cut = exp["tier_cutoffs"]
    tier = np.select([ev >= cut["A"], ev >= cut["B"], ev >= cut["C"]],
                     ["A", "B", "C"], default="D")
    sub = pd.DataFrame({"lead_id": lts.lead_id, "p_win": p_ex.round(4),
                        "exp_amount": amt.round(0), "score": ev.round(2), "tier": tier,
                        "exact": ev})
    # lead_id breaks ties deterministically. 14 leads share a score to the last bit, and
    # without a tiebreak their order depends on input order -- which is enough to make
    # this file and the dashboard's /submission.csv differ for no reason at all.
    sub = sub.sort_values(["exact", "lead_id"], ascending=[False, True])
    sub.drop(columns="exact").to_csv(OUT / "scored_leads_full.csv", index=False)
    sub[["lead_id", "score", "tier"]].to_csv(OUT / "submission.csv", index=False)
    print(f"\npredicted win rate on scoring window: {p_ex.mean()*100:.1f}%")
    print(sub.groupby("tier").agg(n=("score", "size"), mean_p=("p_win", "mean"),
                                  min_score=("score", "min")).to_string(float_format="%.3f"))
    # Reference vector for the JS test harness.
    # Unrounded on purpose: this is the vector the JS scorer is held against, so any
    # rounding here would show up as a phantom parity failure.
    (OUT / "parity_expected.json").write_text(json.dumps(
        {r.lead_id: float(r.exact) for r in sub.head(500).itertuples()}))
    print("wrote output/parity_expected.json (500-row JS test vector, unrounded)")
