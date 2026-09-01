"""Load the baked artifacts once at import.

The container never sees leads_history, activities, the call tables or the transcripts.
It holds the scoring window's intake columns, the exported model, and precomputed
aggregates -- which is the smallest thing that can answer every question the dashboard
asks, and keeps the confidential pack off the deployed host.
"""
import json
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd

APP_DATA = Path(os.getenv("APP_DATA_DIR", Path(__file__).resolve().parent.parent / "output" / "app_data"))

TIER_META = {
    "A": {"name": "Call now", "cls": "a", "sla": "Dial within 60 minutes"},
    "B": {"name": "Work", "cls": "b", "sla": "Dial same business day"},
    "C": {"name": "Light", "cls": "c", "sla": "Email cadence, no dial"},
    "D": {"name": "Nurture", "cls": "d", "sla": "No rep touch"},
}


@lru_cache(maxsize=1)
def leads():
    df = pd.read_parquet(APP_DATA / "leads.parquet")
    df["created_at"] = pd.to_datetime(df["created_at"])
    # Ranked by the score itself -- expected dollars -- not by P(win). They agree to
    # spearman 0.997, but the queue must be in the order the tiers were cut in. lead_id
    # breaks ties so this ordering matches output/submission.csv exactly.
    return df.sort_values(["score", "lead_id"], ascending=[False, True]).reset_index(drop=True)


@lru_cache(maxsize=1)
def analytics():
    return json.load(open(APP_DATA / "analytics.json"))


@lru_cache(maxsize=1)
def model_json():
    """The shipped scorer: a coefficient lookup, not a pickle. Nothing on the serving
    path is version-coupled to the scikit-learn that fitted it."""
    return json.load(open(APP_DATA / "model.json"))


@lru_cache(maxsize=1)
def day_index():
    d = leads().groupby("created_date").size()
    return [{"date": k, "n": int(v)} for k, v in d.items()]


def tier_of(score):
    """Fixed expected-dollar thresholds frozen into the model, not percentiles of
    whatever batch happens to be in front of us."""
    th = model_json()["tier_cutoffs"]
    for code in ["A", "B", "C"]:
        if score >= th[code]:
            return code
    return "D"


def play_for(tier):
    defs = {d["code"]: d for d in analytics()["capacity"]["tier_defs"]}
    return defs.get(tier, {})
