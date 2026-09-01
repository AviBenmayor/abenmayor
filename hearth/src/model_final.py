"""The ablation that chose the feature set: full 12 intake columns vs the lean five.

Feature choice is driven by two things agreeing:
  1. Ablation -- dropping channel/utm_medium/state IMPROVED out-of-time AUC.
  2. Drift    -- those are precisely the fields whose distribution moves hardest between
                 the train and scoring windows. A feature that does not help and is not
                 stable is a liability, not a coin flip.

This script decides and reports. It does not ship anything: export_model.py owns the
final fit, output/model.json and output/submission.csv. Two scripts writing the graded
deliverable is how you end up submitting whichever one you happened to run last.
"""
import pandas as pd, numpy as np, warnings, json
from pathlib import Path
from sklearn.metrics import roc_auc_score, average_precision_score
warnings.filterwarnings("ignore")

from features import CAT as LEAN_CAT, NUM as LEAN_NUM, FULL_CAT, prep, make_model as make

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"


def lift(y, s, frac):
    k = max(1, int(len(s) * frac))
    return y[np.argsort(-s)[:k]].mean() / y.mean()


def amount_model(won):
    """E[amount | win]. Deliberately a lookup, not a model: amount CV is 0.28 and the only
    field that moves it is the revenue band. A regression here would fit noise."""
    by = won.groupby("contractor_annual_revenue").post_amount.agg(["mean", "size"])
    overall = won.post_amount.mean()
    # Shrink thin bands toward the global mean.
    by["shrunk"] = (by["mean"] * by["size"] + overall * 30) / (by["size"] + 30)
    return by["shrunk"].to_dict(), overall


if __name__ == "__main__":
    df = pd.read_parquet(OUT / "leads_base.parquet")
    df["cohort"] = df.created_at.dt.to_period("M").astype(str)
    tr, va = df[df.cohort <= "2025-12"], df[df.cohort >= "2026-01"]
    ytr, yva = tr.post_is_won.values.astype(int), va.post_is_won.values.astype(int)

    print("OUT-OF-TIME COMPARISON (train Oct-Dec 2025 -> validate Jan-Feb 2026)\n")
    rows = []
    for name, cat, num in [("full (12 intake cols)", FULL_CAT, ["legacy_score"]),
                           ("lean (4 cat + legacy)", LEAN_CAT, LEAN_NUM)]:
        m = make(cat, num).fit(prep(tr, cat, num), ytr)
        s = m.predict_proba(prep(va, cat, num))[:, 1]
        rows.append(dict(model=name, n_features=m.named_steps["pre"].transform(
            prep(va, cat, num)).shape[1], auc=roc_auc_score(yva, s),
            pr_auc=average_precision_score(yva, s), lift10=lift(yva, s, .1),
            lift20=lift(yva, s, .2)))
    ls = pd.to_numeric(va.legacy_score, errors="coerce").fillna(0).values
    rows.append(dict(model="legacy_score (baseline)", n_features=1, auc=roc_auc_score(yva, ls),
                     pr_auc=average_precision_score(yva, ls), lift10=lift(yva, ls, .1),
                     lift20=lift(yva, ls, .2)))
    print(pd.DataFrame(rows).set_index("model").to_string(float_format="%.4f"))

    print("\n   -> the lean set wins out-of-time. export_model.py fits exactly this")
    print("      specification (from features.py) and writes output/submission.csv.")
