"""Build the historical demo bundle the deployed tool can load behind auth.

The default posture is that the confidential pack stays off the host (see app/data.py).
This is a deliberate, narrowed exception so the Historical tab is demonstrable in the
interview without the reviewer needing local files:

  * Served ONLY behind the dashboard's HTTP Basic auth, which fails closed.
  * Columns the tool cannot use are dropped -- owner_id, mql_at, sal_at, converted_at
    and converted_contact_id never leave the machine.
  * activities.csv (9.5 MB of raw dispositions) is excluded entirely. Call extractions
    already carry the timeline, so the biggest file buys the demo nothing.
  * Delete the Railway service when the process concludes, per the brief.
"""
import gzip, json
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, APP = ROOT / "data", ROOT / "output" / "app_data"

KEEP = ["lead_id", "created_at", "channel", "campaign_ref", "utm_medium",
        "contractor_annual_revenue", "icp_category", "state", "zip3", "time_zone",
        "enrichment_status", "legacy_score", "status", "converted_opp_id"]

def rows(path, cols=None):
    df = pd.read_csv(path, dtype=str).fillna("")
    if cols:
        df = df[[c for c in cols if c in df.columns]]
    return df.to_dict("records")

bundle = {
    "leads":      rows(DATA / "leads_history.csv", KEEP),
    "opps":       rows(DATA / "opps.csv"),
    "calls":      rows(DATA / "call_extractions.csv"),
    "objections": rows(DATA / "call_objections.csv"),
}
out = APP / "historical.json.gz"
out.write_bytes(gzip.compress(json.dumps(bundle, separators=(",", ":")).encode(), 9))
print(f"wrote {out.relative_to(ROOT)}  ({out.stat().st_size/1e6:.1f} MB gzipped)")
for k, v in bundle.items():
    print(f"   {k:11s} {len(v):>6,} rows")
print("\n   excluded on purpose: activities.csv (9.5 MB), and the 5 lead columns the tool")
print("   cannot use (owner_id, mql_at, sal_at, converted_at, converted_contact_id).")
