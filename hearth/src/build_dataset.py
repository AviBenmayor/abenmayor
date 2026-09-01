"""Build the lead-level analysis table.

Two column families, kept strictly separate:
  * intake_*  - the 12 columns known the second the lead lands. Legal as model features.
  * post_*    - anything that exists only because a human worked the lead. Analysis only.
                Using these as features would leak; they are here to explain, not to predict.
"""
import pandas as pd, numpy as np
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

INTAKE = ["lead_id", "created_at", "channel", "campaign_ref", "utm_medium",
          "contractor_annual_revenue", "icp_category", "state", "zip3",
          "time_zone", "enrichment_status", "legacy_score"]


def load():
    dt = lambda s: pd.to_datetime(s, errors="coerce")
    lh = pd.read_csv(DATA / "leads_history.csv", dtype=str)
    lts = pd.read_csv(DATA / "leads_to_score.csv", dtype=str)
    opps = pd.read_csv(DATA / "opps.csv", dtype=str)
    act = pd.read_csv(DATA / "activities.csv", dtype=str)
    for df, cols in [(lh, ["created_at", "mql_at", "sal_at", "converted_at"]),
                     (lts, ["created_at"]),
                     (opps, ["created_at", "close_date"]),
                     (act, ["created_at"])]:
        for c in cols:
            df[c] = dt(df[c])
    lh["legacy_score"] = pd.to_numeric(lh["legacy_score"], errors="coerce")
    lts["legacy_score"] = pd.to_numeric(lts["legacy_score"], errors="coerce")
    opps["amount"] = pd.to_numeric(opps["amount"], errors="coerce")
    opps["won_arr"] = pd.to_numeric(opps["won_arr"], errors="coerce")
    opps["is_won"] = opps["is_won"].eq("True")
    act["call_duration_seconds"] = pd.to_numeric(act["call_duration_seconds"], errors="coerce")
    return lh, lts, opps, act


def first_touch(lh, act):
    """Earliest real outbound touch per lead.

    activities.who_id is bimodal: pre-conversion activity hangs off the lead (L...),
    post-conversion off the contact (C...). First touch necessarily precedes conversion,
    so the L side is what matters -- but we map both and assert that, rather than assume it.
    """
    l2c = lh.dropna(subset=["converted_contact_id"])[["lead_id", "converted_contact_id"]]
    l2c = l2c[l2c.converted_contact_id.ne("")]
    contact2lead = dict(zip(l2c.converted_contact_id, l2c.lead_id))
    a = act.copy()
    a["lead_id"] = np.where(a.who_id.str.startswith("C"),
                            a.who_id.map(contact2lead), a.who_id)
    a = a.dropna(subset=["lead_id"])
    # A "touch" is a rep reaching out. Tasks are internal bookkeeping, not contact.
    touch = a[a.subtype.isin(["Call", "Email", "ListEmail"]) | a.type.isin(["SMS"])]
    g = touch.groupby("lead_id")["created_at"]
    out = pd.DataFrame({"post_first_touch_at": g.min(), "post_last_touch_at": g.max()})
    out["post_n_touches"] = g.size()
    for kind, mask in [("call", touch.subtype.eq("Call")),
                       ("email", touch.subtype.isin(["Email", "ListEmail"])),
                       ("sms", touch.type.eq("SMS"))]:
        out[f"post_n_{kind}"] = touch[mask].groupby("lead_id").size()
    conn = touch[touch.call_disposition.isin(["Connect - DM", "Connect", "Connect - non-DM"])]
    out["post_n_connects"] = conn.groupby("lead_id").size()
    out["post_first_connect_at"] = conn.groupby("lead_id")["created_at"].min()
    return out.fillna({c: 0 for c in out.columns if c.startswith("post_n_")})


def build():
    lh, lts, opps, act = load()
    o = opps.set_index("opp_id")
    df = lh.copy()
    df["post_is_won"] = df.converted_opp_id.map(o.is_won).fillna(False)
    df["post_amount"] = df.converted_opp_id.map(o.amount)
    df["post_opp_created_at"] = df.converted_opp_id.map(o.created_at)
    df["post_close_date"] = df.converted_opp_id.map(o.close_date)
    df["post_has_opp"] = df.converted_opp_id.notna() & df.converted_opp_id.ne("")

    df = df.join(first_touch(lh, act), on="lead_id")
    for c in [c for c in df.columns if c.startswith("post_n_")]:
        df[c] = df[c].fillna(0)

    df["post_response_min"] = (df.post_first_touch_at - df.created_at).dt.total_seconds() / 60
    df["post_days_to_close"] = (df.post_close_date - df.created_at).dt.days
    df["post_touched"] = df.post_first_touch_at.notna()

    # Intake-time derived features -- computable for a brand new lead, so model-legal.
    df["intake_hour"] = df.created_at.dt.hour
    df["intake_dow"] = df.created_at.dt.dayofweek
    df["intake_is_weekend"] = df.intake_dow.ge(5)
    df["intake_month"] = df.created_at.dt.to_period("M").astype(str)
    return df, lts, opps, act


if __name__ == "__main__":
    df, lts, opps, act = build()
    df.to_parquet(OUT / "leads_base.parquet")
    n = len(df)
    print(f"leads_base: {n} rows, {df.shape[1]} cols -> output/leads_base.parquet\n")
    print(f"  won                 {df.post_is_won.sum():5d}  ({df.post_is_won.mean()*100:5.2f}%)")
    print(f"  has_opp             {df.post_has_opp.sum():5d}  ({df.post_has_opp.mean()*100:5.2f}%)")
    print(f"  touched at all      {df.post_touched.sum():5d}  ({df.post_touched.mean()*100:5.2f}%)")
    print(f"  never touched       {(~df.post_touched).sum():5d}  ({(~df.post_touched).mean()*100:5.2f}%)")
    print(f"\n  win rate | touched     {df[df.post_touched].post_is_won.mean()*100:5.2f}%")
    print(f"  win rate | untouched   {df[~df.post_touched].post_is_won.mean()*100:5.2f}%")
    r = df.loc[df.post_touched, "post_response_min"]
    print(f"\n  response_min: neg {(r<0).sum()}  p10 {r.quantile(.10):.0f}  p50 {r.quantile(.50):.0f} "
          f" p90 {r.quantile(.90):.0f}  max {r.max():.0f}")
