"""Which target? P(win), expected dollars, or P(win this month).

They rank leads differently only if amount / time-to-close vary AND are predictable
from intake. Test both before picking.
"""
import pandas as pd, numpy as np
from pathlib import Path
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_parquet(ROOT / "output" / "leads_base.parquet")
won = df[df.post_is_won].copy()

print("=" * 78)
print("A. DOES DEAL SIZE VARY ENOUGH TO RE-RANK ANYTHING?")
print("=" * 78)
a = won.post_amount
print(f"\n  n={len(a)}  mean {a.mean():.0f}  sd {a.std():.0f}  cv {a.std()/a.mean():.2f}")
print(f"  min {a.min():.0f}  p10 {a.quantile(.1):.0f}  p50 {a.median():.0f} "
      f" p90 {a.quantile(.9):.0f}  max {a.max():.0f}")
print(f"  p90/p10 ratio = {a.quantile(.9)/max(a.quantile(.1),1):.2f}x")
print(f"  zero-amount won deals: {(a==0).sum()}")

print("\n  Mean won amount by contractor_annual_revenue (the obvious size proxy):")
g = won.groupby("contractor_annual_revenue").post_amount.agg(["size", "mean", "median"])
print(g.sort_values("mean", ascending=False).to_string(float_format="%.0f"))
grp = [x.post_amount.values for _, x in won.groupby("contractor_annual_revenue") if len(x) >= 10]
print(f"\n  Kruskal-Wallis across revenue bands: p={stats.kruskal(*grp).pvalue:.3f}")

print("\n  Mean won amount by icp_category:")
print(won.groupby("icp_category").post_amount.agg(["size", "mean", "median"]).to_string(float_format="%.0f"))

print("\n" + "=" * 78)
print("B. IF WE RANKED BY EXPECTED DOLLARS INSTEAD OF P(WIN), WOULD ORDER CHANGE?")
print("=" * 78)
seg = df.groupby("icp_category").agg(
    n=("post_is_won", "size"), win=("post_is_won", "mean"),
    mean_amt_if_won=("post_amount", "mean"))
seg["exp_dollars"] = seg.win * seg.mean_amt_if_won
seg["win"] *= 100
seg["rank_by_pwin"] = seg.win.rank(ascending=False)
seg["rank_by_ev"] = seg.exp_dollars.rank(ascending=False)
print()
print(seg.to_string(float_format="%.1f"))
print("\n  -> If these two rank columns agree, the targets are the same decision.")

print("\n" + "=" * 78)
print("C. P(WIN THIS MONTH): how fast do wins actually close?")
print("=" * 78)
dtc = won.post_days_to_close.dropna()
print(f"\n  days lead_created -> close_date:  n={len(dtc)}")
for q in [.1, .25, .5, .75, .9, .95]:
    print(f"    p{int(q*100):02d}  {dtc.quantile(q):6.0f} days")
print(f"    max  {dtc.max():.0f} days   negative: {(dtc<0).sum()}")
print(f"\n  closed within 30 days: {(dtc<=30).mean()*100:.1f}%")
print(f"  closed within 60 days: {(dtc<=60).mean()*100:.1f}%")
print(f"  closed within 90 days: {(dtc<=90).mean()*100:.1f}%")

print("\n  Speed-to-close by segment (does any segment close notably faster?):")
sp = won.groupby("icp_category").post_days_to_close.agg(["size", "median", "mean"])
print(sp.to_string(float_format="%.1f"))
sp2 = won.groupby("channel").post_days_to_close.agg(["size", "median"])
print()
print(sp2[sp2["size"] >= 20].to_string(float_format="%.1f"))

print("\n" + "=" * 78)
print("D. CENSORING CHECK: are late-arriving leads still open?")
print("=" * 78)
df["cohort"] = df.created_at.dt.to_period("M").astype(str)
c = df.groupby("cohort").agg(n=("post_is_won", "size"), win=("post_is_won", "mean"),
                             open_status=("status", lambda s: s.isin(
                                 ["New Lead", "Hold", "Building Interest", "Contacted",
                                  "Not Contacted", "Demo Set", "Nurture"]).mean()))
c["win"] *= 100; c["open_status"] *= 100
print()
print(c.to_string(float_format="%.1f"))
print("\n  Outcomes are as of early Aug 2026; the newest train cohort had ~5 months to mature.")
print("  The SCORING window (Mar-May 2026) had 3-5 months. Comparable, but if a target needs")
print("  a long horizon the newest cohorts are censored and the label is optimistic-biased.")
