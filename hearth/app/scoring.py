"""Score records the model has never seen.

This is the path the session will actually exercise -- they said they would run the code
on records we have not seen. It goes through src/scorer.py against output/model.json, so
a lead pasted into the web form at 4pm gets the identical number it would get from
submission.csv or from the browser tool. It accepts a partial row and is explicit about
what it filled in rather than silently imputing.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from features import INTAKE  # noqa: E402
from scorer import score_from_export, tier_of, unseen_levels  # noqa: E402

from . import data  # noqa: E402


def score_frame(raw: pd.DataFrame):
    """Returns (scored rows, list of warnings). Never raises on a malformed row --
    a rep pasting a lead at 4pm should get an answer or a readable reason, not a 500."""
    warn = []
    df = raw.copy()
    df.columns = [c.strip() for c in df.columns]
    exp = data.model_json()
    used = exp["features"]["categorical"] + exp["features"]["numeric"]

    missing = [c for c in used if c not in df.columns]
    for c in missing:
        df[c] = pd.NA
    if missing:
        warn.append(f"Missing column(s) filled as unknown: {', '.join(missing)}. "
                    f"The model treats an absent level as its own category, it does not "
                    f"impute the mode.")

    # Columns that exist at intake but are not model features. Saying so is worth a line:
    # a rep who pasted a channel and got no credit for it should know the model does not
    # read that column, rather than assume the score ignored their lead.
    extra = [c for c in INTAKE if c in df.columns and c not in used and c != "lead_id"]
    if extra:
        warn.append(f"Ignored (not model features): {', '.join(extra)}. Dropping "
                    f"channel, utm_medium and state improved out-of-time AUC and they "
                    f"are the fields that drift hardest -- see the model card.")

    for c, vals in unseen_levels(exp, df).items():
        warn.append(f"{c}: value(s) not seen in training -- {', '.join(vals[:4])}"
                    f"{'...' if len(vals) > 4 else ''}. Scored on the remaining columns.")

    p, amt, ev = score_from_export(exp, df)
    out = pd.DataFrame({
        "lead_id": df.lead_id.fillna("(no id)").astype(str).values
                   if "lead_id" in df.columns else [f"(row {i+1})" for i in range(len(df))],
        "p_win": p,
        "expected_amount": np.round(amt, 0),
        "score": np.round(ev, 2),
        "tier": [tier_of(exp, v) for v in ev],
    })
    return out, warn
