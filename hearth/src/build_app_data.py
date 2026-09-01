"""Bake everything the dashboard serves into output/app_data/.

The app itself does no analysis and never reads the raw pack -- it renders artifacts.
That keeps the deployed container holding only the scoring window's intake columns plus
derived aggregates, and keeps a live demo from doing 30 seconds of pandas per page load.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT, APP = ROOT / "data", ROOT / "output", ROOT / "output" / "app_data"

LABEL = {"channel": "Channel", "utm_medium": "UTM medium", "icp_category": "ICP",
         "contractor_annual_revenue": "Contractor revenue", "time_zone": "Time zone",
         "campaign_ref": "Campaign", "state": "State", "legacy_score": "Legacy score",
         "intake_hour": "Arrival hour", "intake_dow": "Arrival weekday",
         "intake_is_weekend": "Weekend arrival"}


EVIDENCE_FIELDS = ["icp_category", "contractor_annual_revenue", "channel", "utm_medium"]


def segment_evidence(train, X):
    """Rep-facing 'why'. Deliberately NOT the model's coefficients.

    The fitted model is conditional: with campaign_ref and state in the design matrix,
    channel = google carries a negative coefficient even though google leads win 25.2%
    against a 16.5% book -- the campaign dummies have already absorbed the credit. That
    is correct arithmetic and indefensible on a sales floor. What a rep gets instead is
    the marginal fact: this segment's observed win rate in the train window against the
    book average, with the support behind it. Both views ship; see model_contributions
    for the conditional one and the model-card note that explains the difference.
    """
    base = train.post_is_won.mean()
    tbl = {}
    for f in EVIDENCE_FIELDS:
        g = train.groupby(f).post_is_won.agg(["size", "mean"])
        tbl[f] = {str(i): (int(r["size"]), float(r["mean"])) for i, r in g.iterrows()}
    ls = train.dropna(subset=["legacy_score"]).copy()
    ls["d"] = pd.qcut(ls.legacy_score, 5, labels=False, duplicates="drop")
    cuts = list(pd.qcut(ls.legacy_score, 5, retbins=True, duplicates="drop")[1])
    ls_rate = ls.groupby("d").post_is_won.agg(["size", "mean"])

    out = []
    for _, r in X.iterrows():
        items = []
        for f in EVIDENCE_FIELDS:
            hit = tbl[f].get(str(r[f]))
            if hit is None or hit[0] < 20:
                items.append({"field": LABEL[f], "value": str(r[f]), "rate": None, "n": hit[0] if hit else 0,
                             "lift": None, "dir": "flat",
                             "note": "too little history to judge" if hit else "not seen in the train window"})
                continue
            n, rate = hit
            items.append({"field": LABEL[f], "value": str(r[f]), "rate": rate * 100, "n": n,
                          "lift": rate / base,
                          "dir": "up" if rate > base * 1.15 else ("down" if rate < base * 0.85 else "flat"),
                          "note": None})
        v = r["legacy_score"]
        if pd.notna(v):
            d = int(np.clip(np.searchsorted(cuts, v, side="right") - 1, 0, len(ls_rate) - 1))
            n, rate = int(ls_rate.loc[d, "size"]), float(ls_rate.loc[d, "mean"])
            items.append({"field": "Legacy score", "value": f"{v:.1f} (quintile {d+1}/5)",
                          "rate": rate * 100, "n": n, "lift": rate / base,
                          "dir": "up" if rate > base * 1.15 else ("down" if rate < base * 0.85 else "flat"),
                          "note": None})
        items.sort(key=lambda x: -(abs(np.log(x["lift"])) if x["lift"] else 0))
        out.append(items)
    return out, base * 100


def model_contributions(bundle, X, top=5):
    """The conditional view: signed contribution to the log-odds, grouped back to the
    intake column it came from. Kept for the model card and for the question a sharp rep
    will ask -- why does the model discount a channel that wins more than average."""
    model, cat = bundle["model"], bundle["cat"]
    pre, clf = model.named_steps["pre"], model.named_steps["m"]
    Z = pre.transform(X)
    names = pre.get_feature_names_out()
    contrib = Z * clf.coef_[0]
    src, val = [], []
    for nm in names:
        body = nm.split("__", 1)[1]
        for c in cat:
            if body.startswith(c + "_"):
                src.append(c); val.append(body[len(c) + 1:]); break
        else:
            src.append(body); val.append(None)
    out = []
    for i in range(len(X)):
        agg = {}
        for j, c in enumerate(src):
            if abs(contrib[i, j]) < 1e-9:
                continue
            shown = val[j] if val[j] is not None else str(X.iloc[i][c])
            agg[c] = (contrib[i, j], shown)
        ranked = sorted(agg.items(), key=lambda kv: -abs(kv[1][0]))[:top]
        out.append([{"field": LABEL.get(c, c), "value": str(v), "effect": round(float(w), 3),
                     "dir": "up" if w > 0 else "down"} for c, (w, v) in ranked])
    return out


def speed_tables(df):
    B = [-np.inf, 5, 30, 60, 240, 1440, 4320, np.inf]
    L = ["<5m", "5-30m", "30-60m", "1-4h", "4-24h", "1-3d", ">3d"]
    d = df[df.post_touched & df.post_response_min.ge(0)].copy()
    d["bucket"] = pd.cut(d.post_response_min, B, labels=L)
    d["ls_decile"] = pd.qcut(d.legacy_score, 10, labels=False, duplicates="drop")

    raw = []
    w_all = d.ls_decile.value_counts(normalize=True)
    for b in L:
        sub = d[d.bucket.eq(b)]
        if not len(sub):
            continue
        n, won = len(sub), int(sub.post_is_won.sum())
        lo, hi = stats.beta.interval(.95, won + .5, n - won + .5)
        per = sub.groupby("ls_decile").post_is_won.agg(["mean", "size"])
        per = per[per["size"] >= 5]
        ww = w_all.reindex(per.index).fillna(0); ww = ww / ww.sum()
        raw.append({"bucket": b, "n": n, "won": won, "win": won / n * 100,
                    "lo": lo * 100, "hi": hi * 100,
                    "adj": float((per["mean"] * ww).sum() * 100) if len(per) else None,
                    "touches": float(sub.post_n_touches.mean()),
                    "mean_legacy": float(sub.legacy_score.mean()),
                    "pct_lowvalue": float(sub.icp_category.eq("Low Value").mean() * 100)})

    d["eff"] = pd.qcut(d.post_n_touches, 3, labels=["low", "mid", "high"], duplicates="drop")
    piv = (d.pivot_table(index="bucket", columns="eff", values="post_is_won",
                         aggfunc="mean", observed=True) * 100).round(1)
    cnt = d.pivot_table(index="bucket", columns="eff", values="post_is_won",
                        aggfunc="size", observed=True)
    eff = [{"bucket": b, **{f"{c}_win": (None if pd.isna(piv.loc[b, c]) else float(piv.loc[b, c]))
                            for c in piv.columns},
            **{f"{c}_n": int(cnt.loc[b, c]) for c in cnt.columns}}
           for b in piv.index]

    fast, slow = d[d.post_response_min.le(60)], d[d.post_response_min.gt(60)]
    chi = stats.chi2_contingency(pd.crosstab(d.post_response_min.le(60), d.post_is_won))
    return {"buckets": raw, "by_effort": eff,
            "headline": {"fast_win": float(fast.post_is_won.mean() * 100), "fast_n": len(fast),
                         "slow_win": float(slow.post_is_won.mean() * 100), "slow_n": len(slow),
                         "p": float(chi.pvalue)},
            "n_analysis": len(d),
            "n_untouched": int((~df.post_touched).sum()),
            "untouched_win": 0.0}


def objection_prep(df):
    """What a rep should expect to hear, by ICP. call_objections already carries lead_id,
    so it joins straight to the lead. Exact-duplicate rows (same call_ref+type+product) are
    dropped -- ~4.7% of the table -- because a naive count overstates every call."""
    obj = pd.read_csv(DATA / "call_objections.csv", dtype=str)
    obj = obj.drop_duplicates(subset=["call_ref", "type", "product"])
    o = obj.merge(df[["lead_id", "icp_category"]], on="lead_id", how="inner")
    o["resolved"] = o.resolved.eq("True")
    o["attempted"] = o.rebuttal_attempted.eq("True")
    out = {}
    for icp, g in o.groupby("icp_category"):
        t = g.groupby("type").agg(n=("type", "size"), resolved=("resolved", "mean"),
                                  attempted=("attempted", "mean"))
        t = t.sort_values("n", ascending=False).head(5)
        out[icp] = [{"type": i, "n": int(r.n), "share": float(r.n / len(g) * 100),
                     "resolved": float(r.resolved * 100), "attempted": float(r.attempted * 100)}
                    for i, r in t.iterrows()]
    overall = o.groupby("type").agg(n=("type", "size"), resolved=("resolved", "mean")).sort_values("n", ascending=False).head(8)
    out["__overall__"] = [{"type": i, "n": int(r.n), "share": float(r.n / len(o) * 100),
                           "resolved": float(r.resolved * 100)} for i, r in overall.iterrows()]
    out["__n_dropped_dupes__"] = int(len(pd.read_csv(DATA / "call_objections.csv", dtype=str)) - len(obj))
    return out


def shift_table(train, score):
    rows = []
    for col in ["channel", "utm_medium", "icp_category", "contractor_annual_revenue"]:
        a = train[col].value_counts(normalize=True) * 100
        b = score[col].value_counts(normalize=True) * 100
        for lvl in sorted(set(a.index) | set(b.index), key=lambda x: -(b.get(x, 0) + a.get(x, 0))):
            ta, tb = float(a.get(lvl, 0)), float(b.get(lvl, 0))
            if max(ta, tb) < 1.0:
                continue
            rows.append({"field": LABEL[col], "level": lvl, "train": ta, "score": tb,
                         "delta": tb - ta,
                         "win": float(train[train[col].eq(lvl)].post_is_won.mean() * 100)})
    return rows


def main():
    import shutil
    import joblib
    from features import add_intake_derived, prep as model_prep

    bundle = joblib.load(APP / "model.joblib")
    train = add_intake_derived(pd.read_parquet(OUT / "leads_base.parquet"))
    raw_score = pd.read_csv(DATA / "leads_to_score.csv", dtype=str)
    score = add_intake_derived(raw_score)
    tiers = pd.read_parquet(APP / "scored_leads.parquet")

    leads = score.merge(tiers, on="lead_id", how="left")
    leads["why"], book_rate = segment_evidence(train, score)
    leads["model_why"] = model_contributions(bundle, model_prep(raw_score))
    leads["created_date"] = leads.created_at.dt.date.astype(str)
    keep = ["lead_id", "created_at", "created_date", "channel", "campaign_ref", "utm_medium",
            "contractor_annual_revenue", "icp_category", "state", "zip3", "time_zone",
            "legacy_score", "p_win", "score", "tier", "pct_rank",
            "planned_touches", "why", "model_why"]
    leads[keep].to_parquet(APP / "leads.parquet", index=False)
    print(f"leads.parquet: {len(leads)} rows")

    # The scorer the container serves is the exported one, byte for byte the same file
    # the browser tool and submission.csv were built from.
    shutil.copyfile(OUT / "model.json", APP / "model.json")

    funnel = {"leads": len(train), "touched": int(train.post_touched.sum()),
              "opp": int(train.post_has_opp.sum()), "won": int(train.post_is_won.sum()),
              "status": train.status.value_counts().head(8).to_dict(),
              "median_amount": float(train[train.post_is_won].post_amount.median()),
              "mean_amount": float(train[train.post_is_won].post_amount.mean())}

    analytics = {
        "funnel": funnel,
        "book_rate": book_rate,
        "speed": speed_tables(train),
        "shift": shift_table(train, score),
        "objections": objection_prep(train),
        "model": json.load(open(APP / "model_metrics.json")),
        "capacity": json.load(open(APP / "capacity.json")),
        "window": {"train_from": str(train.created_at.min().date()),
                   "train_to": str(train.created_at.max().date()),
                   "score_from": str(score.created_at.min().date()),
                   "score_to": str(score.created_at.max().date())},
        "notes": [
            {"t": "Three different 'won' counts",
             "d": "980 leads carry status Closed Won, 954 have an opportunity, 907 of those "
                  "have is_won = True. I scored against is_won because it is the only one "
                  "tied to a dollar amount. Which is the system of record is a question for you."},
            {"t": "activities.who_id is bimodal",
             "d": "Pre-conversion activity attaches to the lead (L...), post-conversion to the "
                  "contact (C...). Joining on lead_id alone silently truncates the history of "
                  "every won lead -- exactly the population you are learning from. The union "
                  "runs through converted_contact_id."},
            {"t": "enrichment_status is a dead column",
             "d": "~100% 'Not Enriched' in both windows. Dropped from the feature set. If "
                  "enrichment is supposed to be running, it is not."},
            {"t": "~15% of paid inbound is junk on arrival",
             "d": "status = Bad Data on 14.7% of the train window. If that is detectable at "
                  "intake it is a shippable win independent of any score, and I would rather "
                  "have that answer than another point of AUC."},
            {"t": "387 duplicate objection rows",
             "d": "353 groups share call_ref + type + product, ~4.7% of the table. Deduped "
                  "before every count on this dashboard. Not every repeat is a dupe -- the same "
                  "type can legitimately recur against different products."},
            {"t": "sal_at == mql_at on 77% of rows",
             "d": "3,797 of 4,957 leads with both stamps. For three quarters of the book these "
                  "are not distinct stages, so any MQL-to-SAL duration is zero by construction."},
            {"t": "Marketing mix moved hard between windows",
             "d": "tiktok 6.3% -> 0.4%, prospecting 28.2% -> 11.5%, icp Unknown 0.3% -> 4.7%. "
                  "The model extrapolates on channel levels it barely saw. This is the largest "
                  "single risk to the ranking and the reason I chose the regularised linear "
                  "model over the boosted one."},
            {"t": "Call data cannot be a feature",
             "d": "Extractions cover 48.7% of train leads and 0 of the 4,255 scoring leads, and "
                  "coverage reflects when an internal job ran, not anything about the lead. It "
                  "shapes what the tool tells a rep to say. It cannot shape the score."},
        ],
    }
    json.dump(analytics, open(APP / "analytics.json", "w"), indent=2, default=str)
    print("analytics.json written:", ", ".join(analytics.keys()))


if __name__ == "__main__":
    main()
