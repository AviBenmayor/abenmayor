"""Memo Q4: where does the cutoff go?

They withheld cost and capacity on purpose. Rather than invent a number, derive the
capacity that is actually observable in activities.csv, state it as the assumption, and
show how the answer moves if it is wrong.
"""
import pandas as pd, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

act = pd.read_csv(ROOT / "data" / "activities.csv", dtype=str)
act["created_at"] = pd.to_datetime(act.created_at, errors="coerce")
act = act[act.created_at.between("2025-10-01", "2026-03-01")]
df = pd.read_parquet(ROOT / "output" / "leads_base.parquet")
scored = pd.read_csv(ROOT / "output" / "scored_leads_full.csv")

print("=" * 78)
print("1. OBSERVED CAPACITY (derived, not assumed)")
print("=" * 78)
# Every touch a rep owns, not just dials: a lead's cost below is measured in touches
# (calls, email and SMS together), so the supply has to be too. Counting supply in dials
# while pricing a lead in touches understates capacity by about a third.
rep = act[act.owner_id.str.startswith("rep_", na=False)].copy()
rep["day"] = rep.created_at.dt.date
weekend = float((rep.created_at.dt.dayofweek >= 5).mean())
# 98% of rep activity falls Mon-Fri. Weekend days are a skeleton crew and would drag
# every median down, so the floor is measured on the days it actually operates.
wd = rep[rep.created_at.dt.dayofweek < 5]
per = wd.groupby(["owner_id", "day"]).size()
print(f"\n  distinct reps logging activity: {rep.owner_id.nunique()}")
print(f"  share of activity at a weekend: {weekend*100:.0f}%  (weekdays only below)")
print(f"  distinct rep-days          : {len(per)}")
print(f"  touches per rep per working day: median {per.median():.0f}  mean {per.mean():.1f} "
      f" p25 {per.quantile(.25):.0f}  p75 {per.quantile(.75):.0f}  p90 {per.quantile(.9):.0f}")
active = wd.groupby("owner_id").day.nunique()
print(f"  working days per rep       : median {active.median():.0f} over the 5-month window")
busy = wd.groupby("day").owner_id.nunique()
print(f"  reps working on a weekday  : median {busy.median():.0f}")

DAILY_TOUCHES = float(per.median())
CONCURRENT_REPS = float(busy.median())
FLOOR_CAPACITY = DAILY_TOUCHES * CONCURRENT_REPS

print("\n" + "=" * 78)
print("2. DEMAND vs CAPACITY")
print("=" * 78)
lts = pd.read_csv(ROOT / "data" / "leads_to_score.csv", dtype=str)
lts["created_at"] = pd.to_datetime(lts.created_at)
days = (lts.created_at.max() - lts.created_at.min()).days
bdays = int(np.busday_count(lts.created_at.min().date(), lts.created_at.max().date()))
# Arrivals per BUSINESS day, to match a supply measured per working day. Dividing by
# calendar days here instead would overstate coverage by about a third.
arrival = len(lts) / bdays
print(f"\n  scoring window: {len(lts)} leads over {days} calendar days / {bdays} business")
print(f"                  days = {arrival:.0f} new leads per business day")
print(f"  observed touch capacity     : {FLOOR_CAPACITY:.0f} touches/day across the floor")
touches_per_lead = df.loc[df.post_touched, "post_n_touches"].median()
print(f"  median touches a worked lead receives: {touches_per_lead:.0f}")
print(f"  -> capacity in NEW leads/day = {FLOOR_CAPACITY:.0f} / {touches_per_lead:.0f} "
      f"= {FLOOR_CAPACITY/touches_per_lead:.0f} leads/day")
cap_leads = FLOOR_CAPACITY / touches_per_lead
print(f"\n  {arrival:.0f} arriving vs {cap_leads:.0f} workable = "
      f"{cap_leads/arrival*100:.0f}% of inbound can get the full treatment.")
print("  This is the whole problem in one line: the floor can properly work roughly")
print(f"  {cap_leads/arrival*100:.0f}% of what marketing buys, so {100-cap_leads/arrival*100:.0f}% "
      "of it is triage no matter how good the score is.")

print("\n" + "=" * 78)
print("3. WHERE THE LINE GOES")
print("=" * 78)
s = scored.sort_values("score", ascending=False).reset_index(drop=True)
s["cum_wins"] = s.p_win.cumsum()
total = s.p_win.sum()
print(f"\n  Total expected wins in the 4,255: {total:.0f}\n")
print(f"  {'work top':>9s} {'leads':>6s} {'exp wins':>9s} {'% of all wins':>14s} "
      f"{'win rate':>9s} {'marginal':>9s}")
prev = 0
for frac in [.05, .10, .20, .30, .40, .50, .60, .80, 1.0]:
    k = int(len(s) * frac)
    w = s.cum_wins.iloc[k - 1]
    marg = s.p_win.iloc[max(0, k - 200):k].mean()
    print(f"  {frac*100:8.0f}% {k:6d} {w:9.0f} {w/total*100:13.0f}% "
          f"{w/k*100:8.1f}% {marg*100:8.1f}%")
    prev = w

# Business days on both sides, as above.
cut_frac = cap_leads * bdays / len(lts)
k = int(len(s) * cut_frac)
print(f"\n  Capacity-implied cutoff: work the top {cut_frac*100:.0f}% "
      f"({k} of {len(s)} leads)")
print(f"    -> captures {s.cum_wins.iloc[k-1]:.0f} of {total:.0f} expected wins "
      f"({s.cum_wins.iloc[k-1]/total*100:.0f}%)")
print(f"    -> marginal lead at that line has p(win) = {s.p_win.iloc[k-1]*100:.1f}%")
print(f"    -> tier at the line: {s.tier.iloc[k-1]}")

print("\n" + "=" * 78)
print("4. WHAT THE CUTOFF IS WORTH vs TODAY")
print("=" * 78)
n_work = k
rng = np.random.default_rng(0)
rand = np.array([s.p_win.sample(n_work, random_state=i).sum() for i in range(200)])
print(f"\n  Working {n_work} leads chosen at random (today's de facto policy):")
print(f"    expected wins {rand.mean():.0f}  (sd {rand.std():.0f})")
print(f"  Working the top {n_work} by score:")
print(f"    expected wins {s.cum_wins.iloc[n_work-1]:.0f}")
gain = s.cum_wins.iloc[n_work - 1] - rand.mean()
print(f"\n  Difference: +{gain:.0f} wins per {days}-day window "
      f"(+{gain/rand.mean()*100:.0f}%)")
amt = df[df.post_is_won].post_amount.mean()
print(f"  At the mean won amount of ${amt:.0f}, that is ~${gain*amt:,.0f} per quarter")
print(f"  from re-ordering work that is already being done.")
print("\n  NOTE: this assumes the same leads convert at the same rate regardless of who")
print("  works them and in what order. It is an upper bound on the reordering gain.")

print("\n" + "=" * 78)
print("5. WHAT HAPPENS BELOW THE LINE")
print("=" * 78)
below = s.iloc[k:]
print(f"\n  {len(below)} leads below the cutoff hold {below.p_win.sum():.0f} expected wins "
      f"({below.p_win.sum()/total*100:.0f}% of the total).")
print("  Throwing them away costs real money, so the recommendation is not 'discard':")
print(f"    - tier C ({(s.tier=='C').sum()} leads): automated email sequence, no dial. "
      "No rep time at all.")
print(f"    - tier D ({(s.tier=='D').sum()} leads): nurture list + a monthly re-score. "
      "Leads that")
print("      improve on re-score (new campaign, revenue band filled in) re-enter the queue.")
bad_like = df[df.status.eq("Bad Data")]
print(f"\n  Separately: {len(bad_like)} train leads ({len(bad_like)/len(df)*100:.0f}%) were "
      f"'Bad Data' and won 0% -- yet {bad_like.post_touched.mean()*100:.0f}% still got touched.")
print("  That is pure waste and it is visible at intake (tiktok 31% bad vs google 10%).")

print("\n" + "=" * 78)
print("6. HONEST INCREMENTAL: model vs legacy score vs random, on ACTUAL Jan-Feb outcomes")
print("=" * 78)
import sys; sys.path.insert(0, str(ROOT / "src"))
from export_model import make, prep
df2 = df.copy()
df2["cohort"] = df2.created_at.dt.to_period("M").astype(str)
tr, va = df2[df2.cohort <= "2025-12"], df2[df2.cohort >= "2026-01"]
m = make().fit(prep(tr), tr.post_is_won.values.astype(int))
va = va.copy()
va["p"] = m.predict_proba(prep(va))[:, 1]
va["ls"] = pd.to_numeric(va.legacy_score, errors="coerce").fillna(0)
y = va.post_is_won.values

print(f"\n  Validation window: {len(va)} leads, {y.sum()} actual wins ({y.mean()*100:.1f}%)\n")
print(f"  {'policy':34s} {'wins caught':>12s} {'% of wins':>10s} {'win rate':>9s}")
for frac in [.30]:
    k = int(len(va) * frac)
    for name, order in [("work top 30% by MODEL", va.p.values),
                        ("work top 30% by legacy_score", va.ls.values),
                        ("work top 30% by icp=Ideal/High", va.icp_category.isin(
                            ["Ideal", "High Value"]).astype(float).values
                            + va.ls.values / 1e6)]:
        idx = np.argsort(-order)[:k]
        print(f"  {name:34s} {y[idx].sum():12.0f} {y[idx].sum()/y.sum()*100:9.0f}% "
              f"{y[idx].mean()*100:8.1f}%")
    rnd = np.array([y[np.random.default_rng(i).choice(len(y), k, replace=False)].sum()
                    for i in range(400)])
    print(f"  {'work 30% at random':34s} {rnd.mean():12.0f} {rnd.mean()/y.sum()*100:9.0f}% "
          f"{rnd.mean()/k*100:8.1f}%")

k = int(len(va) * .30)
mi = np.argsort(-va.p.values)[:k]; li = np.argsort(-va.ls.values)[:k]
print(f"\n  Model vs legacy at the same 30% cut: "
      f"+{y[mi].sum() - y[li].sum():.0f} wins ({(y[mi].sum()/y[li].sum()-1)*100:+.0f}%)")
print(f"  Model vs random at the same cut     : "
      f"+{y[mi].sum() - rnd.mean():.0f} wins ({(y[mi].sum()/rnd.mean()-1)*100:+.0f}%)")
print("\n  The honest number to quote is the first one. Reps are not currently working")
print("  leads at random -- the legacy score exists and ICP labels exist, so the real")
print("  competition is those, not a coin flip.")
