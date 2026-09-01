"""P(win) model on intake-only features, validated out-of-time.

Why out-of-time and not a random split: win rate rises monotonically across the train
cohorts (12.3% Oct -> 20.1% Feb) and the marketing mix shifts hard into the scoring
window. A random split would score itself on a period it has already seen and report a
number that will not survive contact with Mar-May.
"""
import pandas as pd, numpy as np, warnings
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

# zip3 is deliberately excluded: 696 levels, median 4 rows each, and only 79.5% of the
# scoring rows fall on a level seen in training. It is noise that looks like signal.
CAT = ["channel", "utm_medium", "contractor_annual_revenue", "icp_category",
       "state", "time_zone", "campaign_ref"]
NUM = ["legacy_score", "intake_hour", "intake_dow"]
BIN = ["intake_is_weekend"]
FEATURES = CAT + NUM + BIN


def prep(df):
    X = df.copy()
    for c in CAT:
        X[c] = X[c].fillna("__NA__").replace("", "__NA__").astype(str)
    X["intake_hour"] = X.created_at.dt.hour
    X["intake_dow"] = X.created_at.dt.dayofweek
    X["intake_is_weekend"] = X.intake_dow.ge(5).astype(int)
    X["legacy_score"] = pd.to_numeric(X.legacy_score, errors="coerce")
    return X[FEATURES]


def make(kind):
    ohe = OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=25,
                        sparse_output=False)
    pre = ColumnTransformer([
        ("cat", ohe, CAT),
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                          ("sc", StandardScaler())]), NUM),
        ("bin", "passthrough", BIN)])
    if kind == "lr":
        return Pipeline([("pre", pre), ("m", LogisticRegression(max_iter=3000, C=0.5))])
    return Pipeline([("pre", pre), ("m", HistGradientBoostingClassifier(
        max_depth=4, learning_rate=0.06, max_iter=300, min_samples_leaf=40,
        l2_regularization=1.0, random_state=0))])


def lift(y, s, frac):
    k = max(1, int(len(s) * frac))
    top = np.argsort(-s)[:k]
    return y[top].mean() / y.mean()


def report(name, y, s):
    return dict(model=name, auc=roc_auc_score(y, s), pr_auc=average_precision_score(y, s),
                lift_top10=lift(y, s, .10), lift_top20=lift(y, s, .20),
                lift_top50=lift(y, s, .50),
                capture_top20=y[np.argsort(-s)[:int(len(s)*.2)]].sum() / y.sum() * 100)


if __name__ == "__main__":
    df = pd.read_parquet(OUT / "leads_base.parquet")
    df["cohort"] = df.created_at.dt.to_period("M").astype(str)
    tr = df[df.cohort <= "2025-12"]
    va = df[df.cohort >= "2026-01"]
    print(f"train Oct-Dec 2025 : {len(tr):5d} leads, win rate {tr.post_is_won.mean()*100:.1f}%")
    print(f"valid Jan-Feb 2026 : {len(va):5d} leads, win rate {va.post_is_won.mean()*100:.1f}%")
    print(f"  (base rate is already drifting upward between the two -- see memo)\n")

    ytr, yva = tr.post_is_won.values.astype(int), va.post_is_won.values.astype(int)
    Xtr, Xva = prep(tr), prep(va)

    rows = []
    # Baseline 1: the legacy CRM score nobody trusts. Plausibly what they benchmark against.
    rows.append(report("legacy_score (baseline)", yva,
                       pd.to_numeric(va.legacy_score, errors="coerce").fillna(0).values))
    # Baseline 2: icp_category, the human-assigned segment.
    icp_rate = tr.groupby("icp_category").post_is_won.mean()
    rows.append(report("icp_category (baseline)", yva,
                       va.icp_category.map(icp_rate).fillna(icp_rate.mean()).values))
    for kind, label in [("lr", "logistic regression"), ("gbm", "gradient boosting")]:
        m = make(kind).fit(Xtr, ytr)
        rows.append(report(label, yva, m.predict_proba(Xva)[:, 1]))

    res = pd.DataFrame(rows).set_index("model")
    print("OUT-OF-TIME VALIDATION (train Oct-Dec -> score Jan-Feb)")
    print(res.to_string(float_format="%.3f"))
    print("\n  lift_topN = win rate of the top N% by score, / overall win rate")
    print("  capture_top20 = % of all wins that land in the top 20% by score")

    # Calibration of the chosen model
    m = make("gbm").fit(Xtr, ytr)
    p = m.predict_proba(Xva)[:, 1]
    print(f"\nCALIBRATION (gbm on Jan-Feb): mean pred {p.mean():.3f} vs actual {yva.mean():.3f}"
          f"   Brier {brier_score_loss(yva, p):.4f}")
    dec = pd.DataFrame({"p": p, "y": yva})
    dec["d"] = pd.qcut(dec.p, 10, labels=False, duplicates="drop")
    g = dec.groupby("d").agg(n=("y", "size"), pred=("p", "mean"), actual=("y", "mean"))
    g[["pred", "actual"]] *= 100
    print(g.to_string(float_format="%.1f"))
    print("\n  -> Model trained on a 15% base rate scoring a 19% period will under-predict")
    print("     in level. Ranking is unaffected; that is why the submission is a ranking.")
