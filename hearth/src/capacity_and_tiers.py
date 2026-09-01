"""Turn the score into a routing decision: how many leads get worked, how hard, and what
happens to everything below the line.

No cost or capacity data was supplied, on purpose. Rather than assume a number, this
derives the constraint from the client's own activity log -- the same derivation as
capacity.py, which is memo Q4 -- and states it explicitly so it can be argued with:

  supply  touches the floor actually makes: median per rep per working day, times the
          median reps working on a weekday. 98% of rep activity is Mon-Fri (50,445 calls
          on weekdays against 957 at weekends), so weekend days are excluded from the
          medians rather than allowed to drag them down.
  cost    a worked lead absorbs a median 22 touches. That is the unit price of "worked".
  demand  the Mar-May window's arrivals over the same business days.

Both sides are counted in the same unit, which is the part that is easy to get wrong.
Measuring supply in dials (50,445 of them) while pricing a lead in touches (calls, email
and SMS together) understates capacity by a third; quoting supply per working day against
arrivals per calendar day then overstates coverage by a third in the other direction. The
two errors nearly cancel, which is how a wrong derivation survives a sanity check.

Tiers are the memo's: 10/20/30/40. The A+B line at the top 30% is a capacity decision,
not a probability threshold, and the cutoffs themselves are the fixed expected-dollar
thresholds frozen into output/model.json -- so tier A means the same thing in this file,
in submission.csv and in the browser tool, for any batch of leads.

This script does not write output/submission.csv. export_model.py owns that.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT, APP = ROOT / "data", ROOT / "output", ROOT / "output" / "app_data"

# Intensity ladder. The point of a score is not only to cut the tail -- it is to spend
# more on the top than the flat ~22 touches every worked lead gets today. The rungs are
# set so the whole policy costs what the floor actually has: see the utilisation line in
# section 2, which lands within a couple of points of 100% by construction, not by luck.
TIERS = [
    ("A", "Call now", 0.10, 30, "Dial within the hour, 3 dials day one, multi-channel, 30-touch cadence."),
    ("B", "Work",     0.20, 22, "Standard cadence: dial same business day, 22 touches over 30 days."),
    ("C", "Light",    0.30,  4, "Email sequence, no dial. Dial only if they reply."),
    ("D", "Nurture",  0.40,  0, "No rep touch. Marketing automation, re-scores if they engage."),
]


def observed_capacity():
    """Derived from activities.csv, not assumed. Every touch a rep owns, weekdays only,
    priced against the touches a worked lead actually absorbs."""
    act = pd.read_csv(DATA / "activities.csv", dtype=str)
    act["created_at"] = pd.to_datetime(act.created_at, errors="coerce")
    act = act[act.created_at.between("2025-10-01", "2026-03-01")]
    rep = act[act.owner_id.str.startswith("rep_", na=False)].copy()
    rep["day"] = rep.created_at.dt.date
    wd = rep[rep.created_at.dt.dayofweek < 5]
    per = wd.groupby(["owner_id", "day"]).size()
    busy = wd.groupby("day").owner_id.nunique()
    base = pd.read_parquet(OUT / "leads_base.parquet")
    return {"distinct_reps": int(rep.owner_id.nunique()),
            "weekend_share": float((rep.created_at.dt.dayofweek >= 5).mean()),
            "touches_per_rep_day": float(per.median()),
            "concurrent_reps": float(busy.median()),
            "touch_cost": float(base.loc[base.post_touched, "post_n_touches"].median())}


def main():
    s = pd.read_parquet(APP / "scores_raw.parquet")
    metrics = json.load(open(APP / "model_metrics.json"))
    model = json.load(open(OUT / "model.json"))
    n = len(s)

    cap = observed_capacity()
    touches_per_day = cap["touches_per_rep_day"] * cap["concurrent_reps"]
    touch_cost = cap["touch_cost"]
    leads_per_day = touches_per_day / touch_cost

    lts = pd.read_csv(DATA / "leads_to_score.csv", dtype=str)
    lts["created_at"] = pd.to_datetime(lts.created_at)
    span_days = (lts.created_at.max() - lts.created_at.min()).days
    business_days = int(np.busday_count(lts.created_at.min().date(), lts.created_at.max().date()))
    arriving_per_bday = n / business_days

    supply = int(round(touches_per_day * business_days))
    demand_flat = int(round(n * touch_cost))

    print("=" * 78)
    print("1. THE CONSTRAINT (derived from their activity log, not assumed)")
    print("=" * 78)
    print(f"   {cap['distinct_reps']} reps logged activity in the train window; "
          f"{cap['weekend_share']*100:.0f}% of it falls at a weekend, so the")
    print(f"   medians below are weekdays only: {cap['concurrent_reps']:.0f} reps working "
          f"on a typical weekday, median")
    print(f"   {cap['touches_per_rep_day']:.0f} touches each -> "
          f"{touches_per_day:.0f} touches/day across the floor.")
    print(f"   A worked lead absorbs a median {touch_cost:.0f} touches, so the floor can")
    print(f"   properly work {leads_per_day:.0f} new leads/day.")
    print(f"\n   Mar-May: {n:,} leads over {span_days} calendar days "
          f"({business_days} business days)")
    print(f"     arrivals  {n/span_days:.0f}/calendar day   {arriving_per_bday:.0f}/business day")
    print(f"     capacity  {leads_per_day:.0f}/business day worked properly "
          f"= {leads_per_day/arriving_per_bday*100:.0f}% of arrivals")
    print(f"   touch supply {supply:,} vs {demand_flat:,} to work all {n:,} at "
          f"{touch_cost:.0f} touches -> coverage {supply/demand_flat*100:.0f}%")
    print(f"\n   -> They cannot work everything well. About "
          f"{100 - leads_per_day/arriving_per_bday*100:.0f}% of what marketing buys is")
    print("      triage no matter how good the score is. That is the whole argument for")
    print("      ranking, and it is measured rather than assumed.")

    print("\n" + "=" * 78)
    print("2. TIERS -- fixed expected-dollar cutoffs from output/model.json")
    print("=" * 78)
    s = s.sort_values("score", ascending=False).reset_index(drop=True)
    s["pct_rank"] = (np.arange(n) + 0.5) / n

    cut = model["tier_cutoffs"]
    s["tier"] = np.select([s.score >= cut["A"], s.score >= cut["B"], s.score >= cut["C"]],
                          ["A", "B", "C"], default="D")
    budget = {c: t for c, _, _, t, _ in TIERS}
    s["planned_touches"] = s.tier.map(budget)
    print("   thresholds on expected dollars: " +
          "  ".join(f"{k} >= {v:.2f}" for k, v in cut.items()))
    print("   Frozen into the model, not percentiles of this batch -- a rep who loads 50")
    print("   leads must not get 5 'tier A' that are only the best of a bad file.")

    # Expected wins uses only the model's calibrated P(win). It answers "if we work the
    # top X%, what share of the wins that happen today do we still get to?" -- it does
    # NOT claim that touching a lead harder raises its probability. Effort in the
    # training data is endogenous: engaged leads get called more, not the reverse.
    # That causal claim is what the 30-day holdout in section 4 is for.
    tot_p = s.p_win.sum()
    rows = []
    for code, name, share, touches, _ in TIERS:
        d = s[s.tier.eq(code)]
        rows.append({"tier": code, "action": name, "leads": len(d),
                     "share": len(d) / n * 100,
                     "mean_p_win": d.p_win.mean() * 100,
                     "exp_wins": d.p_win.sum(),
                     "pct_of_wins": d.p_win.sum() / tot_p * 100,
                     "touches_ea": touches,
                     "touch_budget": len(d) * touches})
    t = pd.DataFrame(rows)
    print()
    print(t.to_string(index=False, float_format="%.1f"))
    used = int(t.touch_budget.sum())
    print(f"\n   planned spend {used:,} touches vs supply {supply:,} "
          f"({used / supply * 100:.0f}% utilisation)")
    ab = t[t.tier.isin(["A", "B"])]
    print(f"   A+B = {ab.share.sum():.0f}% of leads carry {ab.pct_of_wins.sum():.0f}% "
          "of expected wins.")
    print(f"   D   = {t[t.tier.eq('D')].share.sum():.0f}% of leads carry "
          f"{t[t.tier.eq('D')].pct_of_wins.sum():.0f}% -- this is what we stop dialling.")

    print("\n" + "=" * 78)
    print("3. WHERE THE CUTOFF SITS AND WHY THERE")
    print("=" * 78)
    marginal = s[s.tier.isin(["A", "B"])].p_win.min()
    print(f"   The dial line falls at the top {ab.share.sum():.0f}% -- expected dollars "
          f">= {cut['B']:.0f},")
    print(f"   where the marginal lead wins {marginal*100:.1f}%.")
    print("   The justification is capacity, not a probability threshold. The floor can")
    print(f"   work {leads_per_day:.0f} leads properly per business day against "
          f"{arriving_per_bday:.0f} arriving; the top 30% is")
    print(f"   {n*0.30/business_days:.0f}/day, and the intensity ladder spends the rest of the "
          "headroom on tier A")
    print("   rather than on more leads. Working 39% at a flat cadence and working 30%")
    print("   with a real ladder cost the same; the second is worth more.")
    print("   Nothing below the line is discarded -- C is an email sequence and D is")
    print(f"   nurture with a monthly re-score. The bottom 70% still holds "
          f"{t[t.tier.isin(['C','D'])].pct_of_wins.sum():.0f}% of winnable deals.")
    print("   If the capacity estimate is wrong the line moves and the model does not.")

    print("\n" + "=" * 78)
    print("4. HOW WE KNOW IN 30 DAYS WHETHER THIS WORKED")
    print("=" * 78)
    hold = int(len(s[s.tier.eq("D")]) * 0.10)
    print(f"   Hold out a random 10% of tier D ({hold} leads) and work them exactly as today.")
    print("   That control is the only way to learn what the cutoff actually costs, and it")
    print("   converts an assumption into a measurement inside one cycle. Read at 30 days:")
    print("     - win rate, tier D held-out control vs tier D suppressed")
    print("     - win rate in tier A vs the same decile in the Mar-May baseline")
    print("     - touches per won deal (the efficiency claim)")
    print("     - rep override rate: how often a rep works a C/D anyway, and were they right")

    # The dashboard's tier must be the tier in the file we submit, for every lead.
    sub = pd.read_csv(OUT / "submission.csv").set_index("lead_id").tier
    mismatch = int((s.set_index("lead_id").tier != sub.reindex(s.lead_id.values).values).sum())
    print(f"\n   PARITY vs output/submission.csv: {mismatch} of {n:,} tiers disagree")
    assert mismatch == 0, ("the dashboard would route leads differently from the file we "
                           "submit. Re-run export_model.py, or reconcile the thresholds.")

    s.to_parquet(APP / "scored_leads.parquet", index=False)
    json.dump({"supply": supply, "demand_flat": demand_flat,
               "core_reps": int(cap["concurrent_reps"]),
               "touches_per_rep_day": int(cap["touches_per_rep_day"]),
               "business_days": business_days, "span_days": int(span_days),
               "distinct_reps": cap["distinct_reps"],
               "touch_cost": int(touch_cost), "leads": int(n),
               "leads_per_day": float(leads_per_day),
               "arriving_per_bday": float(arriving_per_bday),
               "arriving_per_day": float(n / span_days),
               "workable_share": float(leads_per_day / arriving_per_bday),
               "cut_p": float(marginal), "cut_score": float(cut["B"]),
               "utilisation": float(used / supply),
               "tiers": t.to_dict("records"), "thresholds": cut,
               "tier_defs": [{"code": c, "action": a, "share": sh, "touches": tt, "play": p}
                             for c, a, sh, tt, p in TIERS]},
              open(APP / "capacity.json", "w"), indent=2)
    print(f"\n   -> app_data/scored_leads.parquet, capacity.json")
    print("   tier counts:", s.tier.value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main()
