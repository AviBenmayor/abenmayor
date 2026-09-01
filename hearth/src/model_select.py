"""Feature ablation, coefficients, and the expected-value-vs-P(win) test."""
import pandas as pd, numpy as np, warnings
from pathlib import Path
from scipy.stats import spearmanr, kendalltau
from sklearn.metrics import roc_auc_score
import model as M
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_parquet(ROOT / "output" / "leads_base.parquet")
df["cohort"] = df.created_at.dt.to_period("M").astype(str)
tr, va = df[df.cohort <= "2025-12"], df[df.cohort >= "2026-01"]
ytr, yva = tr.post_is_won.values.astype(int), va.post_is_won.values.astype(int)

print("=" * 78)
print("FEATURE ABLATION (logistic, out-of-time AUC / lift@20%)")
print("=" * 78)
base = M.CAT + M.NUM + M.BIN
rows = []
for drop in [None] + base:
    feats = [f for f in base if f != drop]
    M.CAT, M.NUM, M.BIN = ([f for f in M.CAT if f in feats], [f for f in M.NUM if f in feats],
                           [f for f in M.BIN if f in feats])
    M.FEATURES = feats
    try:
        m = M.make("lr").fit(M.prep(tr), ytr)
        s = m.predict_proba(M.prep(va))[:, 1]
        rows.append((drop or "(all features)", roc_auc_score(yva, s), M.lift(yva, s, .20)))
    except Exception as e:
        rows.append((drop or "all", np.nan, np.nan))
    M.CAT = ["channel", "utm_medium", "contractor_annual_revenue", "icp_category",
             "state", "time_zone", "campaign_ref"]
    M.NUM = ["legacy_score", "intake_hour", "intake_dow"]
    M.BIN = ["intake_is_weekend"]
    M.FEATURES = M.CAT + M.NUM + M.BIN
ab = pd.DataFrame(rows, columns=["dropped", "auc", "lift@20"])
ab["auc_delta"] = ab.auc - ab.auc.iloc[0]
print(ab.to_string(index=False, float_format="%.4f"))
print("\n  Negative auc_delta = dropping it hurt. Positive = the feature was noise.")

print("\n" + "=" * 78)
print("COEFFICIENTS (what the model actually believes)")
print("=" * 78)
m = M.make("lr").fit(M.prep(tr), ytr)
names = m.named_steps["pre"].get_feature_names_out()
co = pd.Series(m.named_steps["m"].coef_[0], index=[n.split("__", 1)[-1] for n in names])
print("\n  Strongest positive (raises P(win)):")
print(co.sort_values(ascending=False).head(12).to_string(float_format="%+.3f"))
print("\n  Strongest negative (lowers P(win)):")
print(co.sort_values().head(12).to_string(float_format="%+.3f"))

print("\n" + "=" * 78)
print("TARGET TEST: does ranking by EXPECTED DOLLARS reorder anything?")
print("=" * 78)
won = df[df.post_is_won]
amt_by = won.groupby("contractor_annual_revenue").post_amount.mean()
overall = won.post_amount.mean()
p = m.predict_proba(M.prep(va))[:, 1]
amt_hat = va.contractor_annual_revenue.map(amt_by).fillna(overall).values
ev = p * amt_hat
print(f"\n  predicted amount range across revenue bands: "
      f"{amt_by.min():.0f} - {amt_by.max():.0f}  ({amt_by.max()/amt_by.min():.2f}x)")
print(f"  predicted P(win) range (p1-p99):              "
      f"{np.percentile(p,1):.3f} - {np.percentile(p,99):.3f}  ({np.percentile(p,99)/np.percentile(p,1):.1f}x)")
print(f"\n  Spearman rho(P(win), EV) = {spearmanr(p, ev).statistic:.4f}")
print(f"  Kendall  tau(P(win), EV) = {kendalltau(p, ev).statistic:.4f}")
for frac in [.10, .20, .30]:
    k = int(len(p) * frac)
    a, b = set(np.argsort(-p)[:k]), set(np.argsort(-ev)[:k])
    print(f"  top {int(frac*100):2d}% overlap: {len(a & b)}/{k} = {len(a&b)/k*100:.1f}%")
print(f"\n  AUC of EV ranking vs P(win) ranking on the win label: "
      f"{roc_auc_score(yva, ev):.3f} vs {roc_auc_score(yva, p):.3f}")
print("\n  -> Deal size varies 1.5x across bands while P(win) varies ~20x. Amount is also")
print("     POSITIVELY correlated with P(win) (bigger contractors both convert more and pay")
print("     more), so EV is close to a monotone transform of P(win). The brief's premise that")
print("     the targets 'rank leads differently' does not hold in this data.")

print("\n" + "=" * 78)
print("TARGET TEST 2: P(win THIS MONTH)")
print("=" * 78)
d30 = (df.post_close_date.dt.normalize() - df.created_at.dt.normalize()).dt.days
df["_w30"] = df.post_is_won & d30.le(30)
va2 = df.loc[va.index]
print(f"\n  P(win) label vs P(win within 30d) label agree on "
      f"{(df.post_is_won == df._w30).mean()*100:.1f}% of leads")
print(f"  {df._w30.sum()} of {df.post_is_won.sum()} wins ({df._w30.sum()/df.post_is_won.sum()*100:.1f}%) "
      f"close within 30 days")
m30 = M.make("lr").fit(M.prep(tr), df.loc[tr.index, "_w30"].values.astype(int))
p30 = m30.predict_proba(M.prep(va))[:, 1]
print(f"  Spearman rho(P(win), P(win<=30d)) = {spearmanr(p, p30).statistic:.4f}")
k = int(len(p) * .2)
print(f"  top 20% overlap: {len(set(np.argsort(-p)[:k]) & set(np.argsort(-p30)[:k]))}/{k}")
print("\n  -> Median win closes in 7 days and 74% close inside 30. 'This month' is almost")
print("     the same event as 'ever'. Third target collapses into the first too.")
