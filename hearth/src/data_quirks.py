"""Chase down the two anomalies from target analysis before they contaminate the model."""
import pandas as pd, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
df = pd.read_parquet(ROOT / "output" / "leads_base.parquet")
won = df[df.post_is_won].copy()

print("=" * 78)
print("QUIRK 1: 144 wins with 'negative' days-to-close")
print("=" * 78)
won["gap_h"] = (won.post_close_date - won.created_at).dt.total_seconds() / 3600
neg = won[won.gap_h < 0]
print(f"\n  close_date time-of-day values: {won.post_close_date.dt.time.value_counts().head(3).to_dict()}")
print(f"  -> close_date is DATE-ONLY (midnight). created_at has a real timestamp.")
print(f"\n  wins with gap < 0 hours : {(won.gap_h < 0).sum()}")
print(f"  of those, same calendar day as lead creation: "
      f"{(won.loc[won.gap_h < 0, 'post_close_date'].dt.date == won.loc[won.gap_h < 0, 'created_at'].dt.date).sum()}")
print(f"  genuinely closed on an EARLIER calendar day  : "
      f"{(won.post_close_date.dt.date < won.created_at.dt.date).sum()}")
print("\n  -> Artifact of date truncation, not a broken record. Use calendar-day difference.")
won["days_cal"] = (won.post_close_date.dt.normalize() - won.created_at.dt.normalize()).dt.days
print(f"\n  Corrected days-to-close: p25 {won.days_cal.quantile(.25):.0f}  "
      f"median {won.days_cal.median():.0f}  p75 {won.days_cal.quantile(.75):.0f}  "
      f"p90 {won.days_cal.quantile(.9):.0f}")
print(f"  same-day closes: {(won.days_cal == 0).sum()} ({(won.days_cal==0).mean()*100:.1f}% of wins)")
print(f"  within 30d {(won.days_cal<=30).mean()*100:.1f}%   within 90d {(won.days_cal<=90).mean()*100:.1f}%")

print("\n" + "=" * 78)
print("QUIRK 2: win rate RISES across cohorts (12.3% Oct -> 20.1% Feb) despite less time")
print("=" * 78)
df["cohort"] = df.created_at.dt.to_period("M").astype(str)
print("\n  Is it lead mix, or is it how leads were worked?\n")
c = df.groupby("cohort").agg(
    n=("post_is_won", "size"),
    win=("post_is_won", "mean"),
    pct_touched=("post_touched", "mean"),
    med_touches=("post_n_touches", "median"),
    med_resp_min=("post_response_min", "median"),
    mean_legacy=("legacy_score", "mean"),
    pct_ideal_or_high=("icp_category", lambda s: s.isin(["Ideal", "High Value"]).mean()),
    pct_baddata=("status", lambda s: s.eq("Bad Data").mean()))
for col in ["win", "pct_touched", "pct_ideal_or_high", "pct_baddata"]:
    c[col] *= 100
print(c.to_string(float_format="%.1f"))

print("\n  Same table, restricted to wins closing within 30 days (removes maturation entirely):")
won30 = df.post_is_won & (df.post_close_date.dt.normalize() - df.created_at.dt.normalize()).dt.days.le(30)
df["_w30"] = won30
c2 = df.groupby("cohort").agg(n=("_w30", "size"), win30=("_w30", "mean"))
c2["win30"] *= 100
print()
print(c2.to_string(float_format="%.1f"))
print("\n  -> If win30 rises too, maturation is NOT the explanation and something real changed.")

print("\n" + "=" * 78)
print("QUIRK 3: what IS 'Bad Data', and is it visible at intake?")
print("=" * 78)
bd = df.status.eq("Bad Data")
print(f"\n  Bad Data leads: {bd.sum()} ({bd.mean()*100:.1f}%), win rate {df[bd].post_is_won.mean()*100:.1f}%")
print(f"  touched: {df[bd].post_touched.mean()*100:.1f}%   median touches {df[bd].post_n_touches.median():.0f}")
print("\n  Bad Data rate by intake field (looking for something predictable):")
for col in ["channel", "utm_medium", "icp_category", "contractor_annual_revenue", "enrichment_status"]:
    t = df.groupby(col).agg(n=("status", "size"), bad_rate=("status", lambda s: s.eq("Bad Data").mean() * 100))
    t = t[t.n >= 40].sort_values("bad_rate", ascending=False)
    print(f"\n  {col}:")
    print(t.head(6).to_string(float_format="%.1f"))
