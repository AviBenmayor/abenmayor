"""Turn the call data into rep coaching.

Calls cannot be scoring features (zero coverage on the leads we score), but objections
join back to intake fields through lead_id -- so we CAN say, for a lead we have never
seen, which objection its segment tends to raise and which rebuttal actually resolves it.
"""
import pandas as pd, numpy as np, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

lh = pd.read_csv(ROOT / "data" / "leads_history.csv", dtype=str)
co = pd.read_csv(ROOT / "data" / "call_objections.csv", dtype=str)
ce = pd.read_csv(ROOT / "data" / "call_extractions.csv", dtype=str)
base = pd.read_parquet(ROOT / "output" / "leads_base.parquet")

co["resolved"] = co.resolved.eq("True")
co["rebuttal_attempted"] = co.rebuttal_attempted.eq("True")
n_before = len(co)
co = co.drop_duplicates(subset=["call_ref", "type", "product", "rebuttal_type"])
print(f"dropped {n_before - len(co)} duplicate objection rows -> {len(co)}\n")

print("=" * 78)
print("WHICH REBUTTAL ACTUALLY RESOLVES EACH OBJECTION")
print("=" * 78)
att = co[co.rebuttal_attempted]
tab = att.groupby(["type", "rebuttal_type"]).agg(n=("resolved", "size"),
                                                 resolve_rate=("resolved", "mean"))
tab["resolve_rate"] *= 100
best = {}
for t in co.type.value_counts().head(8).index:
    sub = tab.loc[t].sort_values("resolve_rate", ascending=False)
    sub = sub[sub.n >= 25]
    if not len(sub):
        continue
    overall = co[co.type.eq(t)].resolved.mean() * 100
    none_rate = co[co.type.eq(t) & ~co.rebuttal_attempted].resolved.mean() * 100
    print(f"\n  {t.upper():18s}  n={co.type.eq(t).sum():5d}   "
          f"resolved overall {overall:.1f}%   no rebuttal attempted -> {none_rate:.1f}%")
    print(sub.head(5).to_string(float_format="%.1f"))
    best[t] = dict(best_rebuttal=sub.index[0], best_rate=round(float(sub.resolve_rate.iloc[0]), 1),
                   worst_rebuttal=sub.index[-1], worst_rate=round(float(sub.resolve_rate.iloc[-1]), 1),
                   overall_rate=round(float(overall), 1), n=int(co.type.eq(t).sum()))

print("\n" + "=" * 78)
print("DOES RESOLVING AN OBJECTION ACTUALLY MOVE THE OUTCOME?")
print("=" * 78)
lead_obj = co.groupby("lead_id").agg(n_obj=("type", "size"), n_resolved=("resolved", "sum"),
                                     n_attempted=("rebuttal_attempted", "sum"))
b = base.set_index("lead_id").join(lead_obj)
has = b[b.n_obj.notna()]
print(f"\n  leads with >=1 logged objection: {len(has)}   win rate {has.post_is_won.mean()*100:.1f}%")
print(f"  leads with call data, no objection: "
      f"{(~base.lead_id.isin(co.lead_id) & base.lead_id.isin(ce.lead_id)).sum()}")
print("\n  win rate by share of objections resolved:")
has = has.copy()
has["share"] = has.n_resolved / has.n_obj
bins = pd.cut(has.share, [-.01, 0, .33, .66, 1.0], labels=["none", "<1/3", "1/3-2/3", ">2/3"])
g = has.groupby(bins, observed=True).agg(n=("post_is_won", "size"), win=("post_is_won", "mean"),
                                         mean_obj=("n_obj", "mean"))
g["win"] *= 100
print(g.to_string(float_format="%.1f"))
print("\n  CAUTION: resolving objections and winning are both downstream of an engaged")
print("  prospect. This is an association, not a lever. It belongs in coaching, not scoring.")

print("\n" + "=" * 78)
print("WHICH OBJECTION DOES EACH INTAKE SEGMENT RAISE? (this is what the tool can predict)")
print("=" * 78)
j = co.merge(lh[["lead_id", "icp_category", "contractor_annual_revenue", "channel"]], on="lead_id")
for col in ["icp_category", "contractor_annual_revenue"]:
    share = pd.crosstab(j[col], j.type, normalize="index") * 100
    keep = [c for c in ["timing", "price", "partner_dm", "no_need", "competitor", "product_gap", "trust"]
            if c in share.columns]
    print(f"\n  top objection mix by {col} (% of that segment's objections):")
    print(share[keep].to_string(float_format="%.1f"))

seg_top = {}
for seg, sub in j.groupby("icp_category"):
    vc = sub.type.value_counts(normalize=True) * 100
    seg_top[seg] = [(t, round(float(v), 1)) for t, v in vc.head(3).items()]
for seg, sub in j.groupby("contractor_annual_revenue"):
    if len(sub) < 100:
        continue
    vc = sub.type.value_counts(normalize=True) * 100
    seg_top[f"rev::{seg}"] = [(t, round(float(v), 1)) for t, v in vc.head(3).items()]

out = dict(best_rebuttal_by_objection=best, objection_mix_by_segment=seg_top)
(ROOT / "output").mkdir(exist_ok=True)
(ROOT / "output" / "coaching.json").write_text(json.dumps(out, indent=2))
print(f"\n  wrote output/coaching.json")
