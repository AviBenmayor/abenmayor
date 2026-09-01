"""The scorer, in one pure-numpy place.

output/model.json is the shipped model: a per-value coefficient lookup that export_model.py
collapses the fitted sklearn pipeline into. Everything that produces a score for a lead
goes through this module -- the batch that writes submission.csv, the dashboard's live
/score and /api/score endpoints -- and src/test_parity.js holds the browser tool's
JavaScript against the same numbers.

That matters more than it looks. Fourteen leads in the Mar-May window sit on exactly the
tier-A threshold; when the dashboard scored them with its own sklearn fit instead, a
disagreement of 1e-13 was the difference between routing them to "call now" and routing
them to "work". One scorer, one answer.

Pure numpy on purpose: no sklearn, no pickle, nothing version-coupled on the serving path.
"""
import numpy as np
import pandas as pd


def score_from_export(exp, df):
    """Returns (p_win, expected_amount, expected_dollars).

        logit = intercept + SUM(coef[feature][value]) + ((legacy - mean)/scale) * coef

    There is no calibration layer, so this is a pure linear
    scorer. Unseen categories fall through to the same __INFREQUENT__ bucket sklearn
    would have used.
    """
    cat = exp["features"]["categorical"]
    na, infreq = exp["na_key"], exp["infrequent_key"]
    z = np.full(len(df), exp["intercept"], dtype=float)
    for c in cat:
        col = df[c] if c in df.columns else pd.Series([None] * len(df), index=df.index)
        vals = col.fillna(na).replace("", na).astype(str)
        lut = exp["categorical"][c]
        z += np.array([lut.get(v, lut[infreq]) for v in vals])
    n = exp["numeric"]["legacy_score"]
    x = pd.to_numeric(df.get("legacy_score"), errors="coerce").fillna(n["median"]).values
    z += (x - n["mean"]) / n["scale"] * n["coef"]
    p = 1 / (1 + np.exp(-z))
    band = df["contractor_annual_revenue"] if "contractor_annual_revenue" in df.columns \
        else pd.Series([None] * len(df), index=df.index)
    amt = band.fillna(na).replace("", na).astype(str) \
              .map(exp["amount"]["by_band"]).fillna(exp["amount"]["default"]).values
    return p, amt, p * amt


def unseen_levels(exp, df):
    """Values the training window never contained, per column. The score for such a row
    leans on its other columns -- a rep pasting a lead should be told that, not left to
    infer it from a number that looks as confident as any other."""
    out = {}
    for c in exp["features"]["categorical"]:
        if c not in df.columns:
            continue
        seen = set(exp["categorical"][c])
        vals = df[c].fillna(exp["na_key"]).replace("", exp["na_key"]).astype(str)
        gap = sorted(set(vals) - seen)
        if gap:
            out[c] = gap
    return out


def tier_of(exp, score):
    cut = exp["tier_cutoffs"]
    for code in ["A", "B", "C"]:
        if score >= cut[code]:
            return code
    return "D"
