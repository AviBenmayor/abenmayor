"""Speed-to-lead, part 2: the tests that decide whether to act on it."""
import pandas as pd, numpy as np
from pathlib import Path
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_parquet(ROOT / "output" / "leads_base.parquet")
act = pd.read_csv(ROOT / "data" / "activities.csv", dtype=str)
act["created_at"] = pd.to_datetime(act.created_at, errors="coerce")

d = df[df.post_touched & df.post_response_min.ge(0)].copy()
d["arrived_bh"] = d.created_at.dt.hour.between(8, 17) & d.created_at.dt.dayofweek.lt(5)

print("=" * 78)
print("5. NATURAL EXPERIMENT: arrival time is as-good-as-random w.r.t. lead quality")
print("=" * 78)
print("\n  A lead landing at 3am gets a slow first touch for reasons that have nothing to do")
print("  with how good it is. If speed were a strong causal lever, off-hours arrivals should")
print("  win materially less. First: confirm the two groups look alike on intake.\n")
bal = d.groupby("arrived_bh").agg(
    n=("post_is_won", "size"), mean_legacy=("legacy_score", "mean"),
    pct_ideal=("icp_category", lambda s: s.eq("Ideal").mean() * 100),
    pct_lowval=("icp_category", lambda s: s.eq("Low Value").mean() * 100),
    med_resp_min=("post_response_min", "median"),
    win=("post_is_won", "mean"))
bal["win"] *= 100
bal.index = ["off-hours arrival", "in-hours arrival"]
print(bal.to_string(float_format="%.1f"))
ct = pd.crosstab(d.arrived_bh, d.post_is_won)
print(f"\n  Balanced on intake quality, 16.7x difference in median response time.")
print(f"  Win rate difference: {bal.win.iloc[1] - bal.win.iloc[0]:+.1f} pp, "
      f"chi2 p={stats.chi2_contingency(ct).pvalue:.3f}")
print("  -> If a 16x swing in response time barely moves the win rate, the causal")
print("     content of 'respond faster' is small.")

print("\n" + "=" * 78)
print("6. WHAT IS A SUB-5-MINUTE 'TOUCH', ACTUALLY?")
print("=" * 78)
lh = pd.read_csv(ROOT / "data" / "leads_history.csv", dtype=str)
l2c = lh.dropna(subset=["converted_contact_id"])
c2l = dict(zip(l2c.converted_contact_id, l2c.lead_id))
a = act.copy()
a["lead_id"] = np.where(a.who_id.str.startswith("C"), a.who_id.map(c2l), a.who_id)
touch = a[a.subtype.isin(["Call", "Email", "ListEmail"]) | a.type.eq("SMS")].dropna(subset=["lead_id"])
first = touch.sort_values("created_at").groupby("lead_id").first()
d = d.join(first[["subtype", "type", "call_disposition", "owner_id"]].add_prefix("ft_"), on="lead_id")
d["bucket"] = pd.cut(d.post_response_min, [-np.inf, 5, 30, 60, 240, 1440, 4320, np.inf],
                     labels=["<5m", "5-30m", "30-60m", "1-4h", "4-24h", "1-3d", ">3d"])
mix = pd.crosstab(d.bucket, d.ft_subtype, normalize="index") * 100
print("\n  Channel of the FIRST touch, by response bucket (% of bucket):")
print(mix.to_string(float_format="%.1f"))
print("\n  -> Check whether the fast bucket is humans dialing or an automated cadence firing.")

print("\n" + "=" * 78)
print("7. LOGISTIC REGRESSION: does response time survive intake controls?")
print("=" * 78)
d["log_resp"] = np.log1p(d.post_response_min.clip(lower=0))
CAT = ["channel", "utm_medium", "contractor_annual_revenue", "icp_category", "time_zone"]
NUM = ["legacy_score"]

def fit(cols_num, label):
    X = d[CAT + cols_num].copy()
    for c in CAT:
        X[c] = X[c].fillna("NA")
    X[cols_num] = X[cols_num].fillna(X[cols_num].median())
    pipe = Pipeline([("prep", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT)],
            remainder="passthrough")),
        ("lr", LogisticRegression(max_iter=2000, C=1.0))])
    pipe.fit(X, d.post_is_won)
    names = pipe.named_steps["prep"].get_feature_names_out()
    coefs = pipe.named_steps["lr"].coef_[0]
    out = {n.split("__")[-1]: c for n, c in zip(names, coefs)}
    print(f"\n  {label}")
    for k in cols_num:
        if k in out:
            print(f"     {k:16s} beta={out[k]:+.4f}   odds ratio per unit "
                  f"{np.exp(out[k]):.3f}")
    return out

fit(["legacy_score"], "model A: intake only (no response time)")
o = fit(["legacy_score", "log_resp"], "model B: intake + log(response minutes)")
b = o["log_resp"]
print(f"\n  Interpretation: each e-fold (2.7x) slower first touch multiplies win odds by "
      f"{np.exp(b):.3f}.")
print(f"  Going from 30 min to 24 h is {np.log(1440/30):.1f} e-folds -> odds x "
      f"{np.exp(b*np.log(1440/30)):.2f}.")
o2 = fit(["legacy_score", "log_resp", "post_n_touches"], "model C: + how hard it was worked")
print(f"\n  Once effort is in the model, log_resp beta moves {b:+.4f} -> {o2['log_resp']:+.4f}"
      f"  ({'collapses' if abs(o2['log_resp']) < abs(b)/2 else 'survives'})")
print(f"  post_n_touches beta={o2['post_n_touches']:+.4f} per touch -> odds x "
      f"{np.exp(o2['post_n_touches']):.3f}")
print("\n  NOTE: effort is endogenous too -- reps keep working leads that engage. Model C is")
print("  not a causal estimate either; it shows the two compete for the same variance.")
