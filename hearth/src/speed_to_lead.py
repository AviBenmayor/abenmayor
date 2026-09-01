"""Memo Q3: does responding faster predict a higher win rate?

Three passes, deliberately: the raw cut anyone would run, then the two controls that
decide whether the raw cut means anything.
"""
import pandas as pd, numpy as np
from pathlib import Path
from scipy import stats

OUT = Path(__file__).resolve().parent.parent / "output"
df = pd.read_parquet(OUT / "leads_base.parquet")

BUCKETS = [-np.inf, 5, 30, 60, 240, 1440, 4320, np.inf]
LABELS = ["<5m", "5-30m", "30-60m", "1-4h", "4-24h", "1-3d", ">3d"]

def rate_table(d, by, label):
    g = d.groupby(by, observed=True).agg(n=("post_is_won", "size"), won=("post_is_won", "sum"))
    g["win_rate"] = g.won / g.n * 100
    lo, hi = zip(*[stats.beta.interval(.95, w + .5, n - w + .5) if n else (np.nan, np.nan)
                   for w, n in zip(g.won, g.n)])
    g["ci95"] = [f"[{l*100:4.1f},{h*100:5.1f}]" for l, h in zip(lo, hi)]
    print(f"\n{label}")
    print(g.to_string(formatters={"win_rate": "{:.1f}%".format}))
    return g

print("=" * 78)
print("0. THE SELECTION PROBLEM")
print("=" * 78)
print(f"  never touched : {(~df.post_touched).sum():4d} leads, win rate "
      f"{df.loc[~df.post_touched,'post_is_won'].mean()*100:.1f}%")
print(f"  touched       : {df.post_touched.sum():4d} leads, win rate "
      f"{df.loc[df.post_touched,'post_is_won'].mean()*100:.1f}%")
print("  -> Untouched leads win 0% by construction. Including them makes 'fast is better'")
print("     trivially true and measures whether a lead was worked at all, not how fast.")

d = df[df.post_touched & df.post_response_min.ge(0)].copy()
print(f"\n  Also dropping {(df.post_touched & df.post_response_min.lt(0)).sum()} leads with a "
      f"touch logged BEFORE lead creation (data error).")
print(f"  Analysis set: {len(d)} touched leads.")
d["bucket"] = pd.cut(d.post_response_min, BUCKETS, labels=LABELS)

print("\n" + "=" * 78)
print("1. RAW: win rate by time to first touch")
print("=" * 78)
raw = rate_table(d, "bucket", "raw win rate by response bucket")
fast, slow = d[d.post_response_min <= 60], d[d.post_response_min > 60]
print(f"\n  <=1h {fast.post_is_won.mean()*100:.1f}% (n={len(fast)})  vs  "
      f">1h {slow.post_is_won.mean()*100:.1f}% (n={len(slow)})")
chi = stats.chi2_contingency(pd.crosstab(d.post_response_min.le(60), d.post_is_won))
print(f"  chi2 p={chi.pvalue:.2e}  -> the raw association is large and significant.")

print("\n" + "=" * 78)
print("2. CONTROL A: is it just that reps call the good leads first?")
print("=" * 78)
d["ls_decile"] = pd.qcut(d.legacy_score, 10, labels=False, duplicates="drop")
print("\n  Mean legacy_score and ICP mix by response bucket:")
mix = d.groupby("bucket", observed=True).agg(
    n=("post_is_won", "size"), mean_legacy=("legacy_score", "mean"),
    pct_ideal=("icp_category", lambda s: s.eq("Ideal").mean() * 100),
    pct_lowvalue=("icp_category", lambda s: s.eq("Low Value").mean() * 100))
print(mix.to_string(float_format="%.1f"))

print("\n  Win rate by response bucket, WITHIN legacy_score decile (pooled, decile-adjusted):")
adj = []
for b in LABELS:
    sub = d[d.bucket.eq(b)]
    if not len(sub):
        continue
    # Reweight each bucket to the overall decile distribution -> removes triage-by-score.
    w = d.ls_decile.value_counts(normalize=True)
    per = sub.groupby("ls_decile").post_is_won.agg(["mean", "size"])
    per = per[per["size"] >= 5]
    if not len(per):
        continue
    ww = w.reindex(per.index).fillna(0); ww = ww / ww.sum()
    adj.append((b, len(sub), sub.post_is_won.mean() * 100, float((per["mean"] * ww).sum() * 100)))
print(pd.DataFrame(adj, columns=["bucket", "n", "raw_win%", "decile_adj_win%"]).to_string(
    index=False, float_format="%.1f"))

print("\n" + "=" * 78)
print("3. CONTROL B: the mechanical confound -- when did the lead arrive?")
print("=" * 78)
d["arrived_bh"] = d.created_at.dt.hour.between(8, 17) & d.created_at.dt.dayofweek.lt(5)
print(f"\n  Leads arriving in business hours : {d.arrived_bh.mean()*100:.1f}%")
print(f"  median response | in-hours  {d[d.arrived_bh].post_response_min.median():7.0f} min")
print(f"  median response | off-hours {d[~d.arrived_bh].post_response_min.median():7.0f} min")
print("  -> An off-hours lead cannot be answered fast. Slow response partly encodes 'arrived at 3am'.")
for flag, name in [(True, "arrived IN business hours"), (False, "arrived OFF hours")]:
    rate_table(d[d.arrived_bh.eq(flag)], "bucket", f"win rate by bucket | {name}")

print("\n" + "=" * 78)
print("4. THE DECOMPOSITION THAT ACTUALLY MATTERS")
print("=" * 78)
print("\n  Response time vs how hard the lead was worked afterwards:")
eff = d.groupby("bucket", observed=True).agg(
    n=("post_is_won", "size"), mean_touches=("post_n_touches", "mean"),
    mean_connects=("post_n_connects", "mean"), win=("post_is_won", "mean"))
eff["win"] *= 100
print(eff.to_string(float_format="%.1f"))
print("\n  Win rate by response bucket, holding effort roughly fixed (touch-count tercile):")
d["eff_t"] = pd.qcut(d.post_n_touches, 3, labels=["low", "mid", "high"], duplicates="drop")
piv = d.pivot_table(index="bucket", columns="eff_t", values="post_is_won",
                    aggfunc="mean", observed=True) * 100
cnt = d.pivot_table(index="bucket", columns="eff_t", values="post_is_won",
                    aggfunc="size", observed=True)
print(piv.to_string(float_format="%.1f"))
print("\n  (cell counts)")
print(cnt.to_string())
