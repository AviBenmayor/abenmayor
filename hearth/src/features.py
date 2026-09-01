"""The intake feature surface and the model's shape, in one place.

Imported by every script that fits or scores: model_final (the ablation), export_model
(the shipped fit), score_leads (the dashboard's metrics), and the dashboard's live
scoring endpoint. A lead scored through the web form goes through exactly the transform
the model was fitted on. Duplicating this is how a scoring service quietly drifts from
its model -- and for a while this file held the *full* spec while export_model held the
lean one, which is precisely how the deployed dashboard ended up ranking leads by a
model the memo argues against.

The lean set is the shipped one. Two independent reasons agreed:
  1. Ablation -- dropping channel/utm_medium/state IMPROVED out-of-time AUC,
     0.737 vs 0.731 (train Oct-Dec 2025 -> test Jan-Feb 2026, legacy baseline 0.645).
  2. Drift -- those are precisely the fields whose distribution moves hardest between
     the two windows. A feature that does not help and is not stable is a liability.
"""
import pandas as pd

# The 12 columns that exist the second a lead hits the CRM. Nothing else is legal as a
# feature -- everything downstream of a human touching the lead is leakage.
INTAKE = ["lead_id", "created_at", "channel", "campaign_ref", "utm_medium",
          "contractor_annual_revenue", "icp_category", "state", "zip3",
          "time_zone", "enrichment_status", "legacy_score"]

# --- the shipped model ---
# Two business-legible fields plus the CRM score. Deliberately smaller than the set that
# maximises AUC, chosen on stability and defensibility rather than on the last decimal:
#
#   contractor_annual_revenue  strongest feature (-0.0213 AUC if dropped) and stable
#                              across periods (pearson +0.933, p=0.007 over 6 levels).
#   icp_category               perfectly stable ordering period to period (spearman 1.000).
#   legacy_score               second strongest (-0.0127). Awkward -- it is the score
#                              nobody trusts -- but it carries real signal (mean 47.7 on
#                              won vs 37.6 on lost) and excluding it to make a point would
#                              cost accuracy for rhetoric.
#
# Dropped, and why, given each was individually defensible on AUC alone:
#   campaign_ref   stable in-sample (pearson +0.846, p=0.002) but campaign IDs churn:
#                  19.4% of the scoring window lands on a campaign never seen in training.
#                  Worth +0.014 AUC; not worth a feature that decays between retrains.
#   time_zone      weakest by a distance. Only 4 testable levels, effect not significant
#                  (p=0.141), win rate spans just 14.2%-20.0%, and no business mechanism
#                  -- it is not even a proxy for lead mix, which would at least explain it.
#   zip3           best single AUC gain available (+0.023, consistent over three time
#                  splits) but unverifiable: only ONE zip has >=40 leads in both periods,
#                  so the stability test that cleared the others cannot be run on it, and
#                  60% of the scoring window pools into __INFREQUENT__ anyway.
#   channel / utm_medium / state   dropping them IMPROVED out-of-time AUC, and they are
#                  the fields whose distribution moves hardest between the two windows.
#   enrichment_status  ~100% one level in both windows -- a dead column.
#
# The cost of this choice, out-of-time (Oct-Dec 2025 -> Jan-Feb 2026): AUC 0.724 against
# 0.746 for the best defensible alternative and 0.760 for the kitchen sink. But lift at
# the 30% cutoff -- the number that actually sets routing -- is 1.82, which MATCHES the
# richer four-feature model's 1.81. Nearly all of the AUC we gave up was ranking inside
# the bottom of the book, where nobody is making calls.
CAT = ["contractor_annual_revenue", "icp_category"]
NUM = ["legacy_score"]
C = 0.5

# --- rejected supersets, kept so the ablation in model_final.py stays runnable ---
FULL_CAT = ["channel", "utm_medium", "contractor_annual_revenue", "icp_category",
            "state", "time_zone", "campaign_ref"]
# The previous shipped set, and the best-AUC set, retained for the ablation table.
PREV_CAT = ["contractor_annual_revenue", "icp_category", "campaign_ref", "time_zone"]
BEST_AUC_CAT = PREV_CAT + ["zip3"]

NA = "__NA__"
INFREQ = "__INFREQUENT__"

# Categorical intake columns normalised for display and for the segment-evidence tables,
# whether or not they are model features. Kept wider than CAT on purpose: the rep-facing
# "why this lead" panel reports marginal win rates by channel and utm_medium, which are
# honest facts about a segment even though the model does not condition on them.
DISPLAY_CAT = sorted(set(FULL_CAT) | set(CAT))


def prep(df, cat=CAT, num=NUM):
    """The model matrix. Missing and empty both become their own level -- never imputed
    to the mode, because 'we do not know this lead's revenue band' is itself predictive."""
    X = df.copy()
    for c in cat:
        if c not in X.columns:
            X[c] = pd.NA
        X[c] = X[c].fillna(NA).replace("", NA).astype(str)
    X["legacy_score"] = pd.to_numeric(X.legacy_score, errors="coerce")
    return X[list(cat) + list(num)]


def make_model(cat=CAT, num=NUM, C=C):
    """scikit-learn is imported here rather than at module scope so that the serving
    path -- features.INTAKE and prep(), plus scorer.py -- needs nothing but pandas and
    numpy. The deployed container fits nothing and unpickles nothing."""
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    return Pipeline([
        ("pre", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=25,
                                  sparse_output=False), cat),
            ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                              ("sc", StandardScaler())]), num)])),
        ("m", LogisticRegression(max_iter=3000, C=C))])


def add_intake_derived(df):
    """Display and analysis columns. Arrival hour and weekday are computed here because
    the speed-to-lead analysis needs them; they are deliberately NOT model features --
    see the ablation note above."""
    df = df.copy()
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["legacy_score"] = pd.to_numeric(df["legacy_score"], errors="coerce")
    df["intake_hour"] = df.created_at.dt.hour
    df["intake_dow"] = df.created_at.dt.dayofweek
    df["intake_is_weekend"] = df.intake_dow.ge(5).astype(int)
    for c in DISPLAY_CAT:
        if c not in df.columns:
            df[c] = pd.NA
        df[c] = df[c].astype("string").fillna(NA)
    return df


# Owners whose leads are all still sitting in "New Lead" at 100% touched and a median of
# 25-30 touches each, with zero wins on leads of entirely normal quality. Either their
# statuses are not being written back -- in which case these labels are wrong -- or they
# are routing sinks. Either way the label cannot be trusted, so they do not train.
SUSPECT_OWNERS = ["rep_128", "rep_222", "rep_210"]


def training_population(df):
    """The rows the model learns from: leads a rep actually worked, minus the owners whose
    outcome labels are not believable.

    This is a decision about WHICH QUESTION the score answers, not a data-cleaning step.

      all 5,507 leads  ->  P(win | this lead arrives), base rate 16.5%
      4,574 worked     ->  P(win | a rep actually works it), base rate 19.8%

    The second is the question a rep is holding when they look at the queue: "if I call
    this, will it convert?" -- not "what share of leads like this converted, including the
    ones nobody phoned." A third of the raw file is leads that were never touched, parked
    on a queue, or sat with a suspect owner; none of them could have won, and training on
    them drags every displayed probability down by ~3 points.

    Ranking is almost unaffected (spearman 0.998 against the unfiltered fit, 97% overlap in
    the top 30%), so this changes the number on the screen, not the order of the book.

    The honest cost: this conditions on a rep having chosen to work the lead, so whatever
    bias sits in that choice is inherited. It is the reason the memo reports the +15% lift
    against the legacy score on the FULL validation window rather than this filtered one.
    """
    own = df["owner_id"].fillna("")
    return df[df["post_touched"] & ~own.isin(SUSPECT_OWNERS)]
