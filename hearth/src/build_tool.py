"""Generate tool/lead_queue.html -- a single self-contained file with the model inlined.

Generated, not hand-written, so the browser scorer can never drift from the Python model:
rebuild after any model change and the parity test re-runs.
"""
import json, pandas as pd, numpy as np
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
OUT, TOOL = ROOT / "output", ROOT / "tool"
TOOL.mkdir(exist_ok=True)

model = json.loads((OUT / "model.json").read_text())
coach = json.loads((OUT / "coaching.json").read_text())
parity = json.loads((OUT / "parity_expected.json").read_text())

# Validation numbers shown in the tool's "how good is this" panel. Hard-coded from the
# out-of-time run in model_final.py so the rep sees the honest number, not a fitted one.
VALIDATION = dict(auc=0.737, lift_top10=2.36, lift_top20=2.14,
                  baseline_auc=0.645, baseline_lift20=1.60,
                  train_n=5507, val_window="Jan-Feb 2026", base_rate=19.0)

# Observed win rate per segment, for the rep-facing "why". A model coefficient is
# CONDITIONAL -- icp_category=High Value carries a negative weight once revenue band is
# known, which is correct arithmetic and indefensible in front of a rep who knows High
# Value is their best segment. The brief leads with what actually happened to leads like
# this one, and keeps the coefficient as a secondary, labelled number.
import pandas as pd
base = pd.read_parquet(OUT / "leads_base.parquet")
from features import training_population
pop = training_population(base)
segments = {}
for col in ["icp_category", "contractor_annual_revenue"]:
    g = pop.groupby(col).post_is_won.agg(["size", "mean"])
    g = g[g["size"] >= 40]
    segments[col] = {str(k): dict(n=int(r["size"]), win=round(float(r["mean"]) * 100, 1))
                     for k, r in g.iterrows()}
segments["_overall"] = dict(n=int(len(pop)), win=round(float(pop.post_is_won.mean()) * 100, 1))

PAYLOAD = dict(model=model, coaching=coach, validation=VALIDATION, parity=parity,
               segments=segments)

HTML = (ROOT / "src" / "tool_template.html").read_text()
HTML = HTML.replace("/*__PAYLOAD__*/null", json.dumps(PAYLOAD))
(TOOL / "lead_queue.html").write_text(HTML)
kb = (TOOL / "lead_queue.html").stat().st_size / 1024
print(f"wrote tool/lead_queue.html  ({kb:.0f} KB, self-contained)")
