"""THE FORECAST LEDGER — the modelled layer, issued as dated, scoreable claims.

Owner's ask (2026-09-14): "almost feels like we are building multiple layers
here: predicted/modeled (not what the world reflects but what it could) vs
realized/actual. worth building this out further."

The screen (`analysis.address_category`) is the REALIZED layer: what the data
reads at a doorway today. This module is the MODELLED one, and the whole
difference between a model and an opinion is that a model is frozen on a date
and scored afterwards. So: `analysis.forecast` (what we said, when, with which
model, off which frozen inputs), `analysis.forecast_outcome` (what happened),
and a track record that includes the vintages that did badly.

Schema and the long-form reasoning: `src/loci/sql/028_forecast.sql`.

===========================================================================
THE SPEC, WRITTEN BEFORE THE FIT
===========================================================================

TARGET.  y[a, c, t] = 1 if at least one same-category storefront in the
principled supply set has a first-seen date (source_date | gov_filing) inside
[t, t + 12 months) within 400 m STRAIGHT-LINE of address a.  A disc-level
BINARY, not a count — see sql/028 "THE UNIT" for why a Poisson rate on the
count would multiply-count one storefront across hundreds of overlapping discs
and would make the NTA residual sum meaningless.

    expected_openings = p_opening x 1.

FEATURES, all frozen at the first day of the issue month, all straight-line
400 m in EPSG:32618, all reconstructed from the first-seen ledger so that
NOTHING DATED ON OR AFTER THE ISSUE MONTH CAN ENTER:

    log_score      log1p(supply_ratio_t0), where supply_ratio_t0 is own-category
                   principled supply per 1,000 homes divided by the frame's own
                   per-category median at t0 (the ANCHOR, below)
    own_gap_flag   1 if zero same-category competitors within 400 m at t0
    log_homes      log(1 + PLUTO units_capped within 400 m straight-line)
    retail_index   D82 neighbourhood character at the address
    category       fixed effect (pooled model) / the model's own scope (fitted)

WITHHELD ON PURPOSE: log_jobs and log_transit. The retrodiction fitted them at
+0.114 [0.003, 0.224] and +0.022 [0.003, 0.040] — intervals that barely clear
zero — against out-of-sample residual Moran's I of 0.64-0.77. Cluster-robust
standard errors on 103 NTAs assume independence ACROSS NTAs and that assumption
is visibly false, so two coefficients whose significance depends on it are not
shipped into a forecast.

FORM.  Logistic. Not linear (a probability must saturate, and the outcome rate
runs from 1% to 91% across categories), not a gradient-booster (100 NTAs is the
real degrees of freedom, a four-feature logit cannot memorise them, and the
coefficient IS the deliverable). Two stages, exactly as the retrodiction
reported it:

    POOLED   one logit over all fifteen categories with category fixed effects.
    FITTED   for each category clearing SUPPORT_FLOOR dated openings in the fit
             window, its own logit on its own rows.

A category with its own model is marked `support='fitted'`; the rest are
predicted by the pooled model and marked `support='pooled'`. Per-category
slopes are NOT a refinement, they are a necessity: the retrodiction measured
+5.20 for restaurant against +1.29 for hair_barber, and a single pooled slope
would be wrong for both.

FIT WINDOW — one rule, every vintage, walk-forward:

    for a vintage issued at month M with horizon H = 12,
    fit on TWO stacked folds with t0 in {M - 24 months, M - 12 months},
    each fold carrying features frozen at ITS OWN t0 and the outcome observed
    over ITS OWN following 12 months.

Every observation that enters a fit therefore has a source date strictly BEFORE
M. That is the leakage contract; `tests/test_forecast.py` pins it against a
synthetic ledger row dated after M. Two folds rather than one because a single
12-month outcome window is thin in the thin categories, and non-overlapping
rather than a rolling window because overlapping outcome windows would count
the same opening twice on the same address.

THE ANCHOR.  `base_median[c, t0]` — the denominator that turns a supply count
into a ratio — is computed on ONE deterministic 12,000-address hash sample of
the lot frame, at every t0, for fit rows and prediction rows alike. Computing
it on the fit sample and then applying it to the full frame would shift the
feature between fitting and predicting; that is the quiet version of leakage
and it is the failure mode that looks like skill.

WHY 12,000 ADDRESSES FOR THE FIT AND 332,041 FOR THE PREDICTION. The retrodiction's
reasoning, unchanged: the lot frame's 400 m discs overlap almost completely, so
the marginal information in address 12,001 is close to zero while the join cost
is not. Prediction is cheap per row and must cover every doorway (owner,
2026-09-13: no eligibility gate — every street is represented), so it runs on
the whole universe.

THE FIT FRAME AND THE SCORED FRAMES ARE NOT THE SAME SET (2026-09-16). The fit
is `frame='lot'`, 12,000 hash-ordered addresses, exactly as before. The SCORE
covers `frame='lot'` (281,842) AND `frame='street'` (50,199) — owner ruling (4),
"street points get everything the lot frame has, including a forecast" — which
is 332,041 x 15 = 4,980,615 rows per vintage, the row count of
`analysis.address_category` and a free cross-check on every issue.

A street midpoint is scored by the lot-fitted model, never admitted to the fit:
it has no PLUTO lot of its own, `units_capped = 0` on all 50,199 of them, and
its feature vector is assembled differently. All four features are nonetheless
honestly derivable AT a street midpoint, because all four are properties of the
400 m DISC around the point rather than of the parcel under it — `log_score` and
`own_gap_flag` from `supply_as_of`, `log_homes` from PLUTO units on the
surrounding LOT-frame addresses, `retail_index` from D82 character, which is
100% populated on the street frame. The one real deficiency is the 1,169 street
midpoints (2.3%) with zero residential units anywhere in their disc; those rows
are written with `support = 'street_no_homes'` rather than dropped or
silently given a p derived from a zero that means "nothing there".

===========================================================================
THE BASELINES IT MUST BEAT, AND THE FAILURE CRITERION
===========================================================================

Three baselines, on the same NTA-blocked folds:

    NO-SCORE      the same two-stage design with log_score and own_gap_flag
                  removed — log_homes + retail_index + category. THIS IS THE
                  BAR. The retrodiction's first draft headlined +0.048 against
                  a homes-only comparator; the statistician's correction showed
                  density + character + category FE alone reach 0.854, so the
                  honest marginal contribution was +0.013. The flattering
                  comparator is not used again.
    PERSISTENCE   rank by whether the disc got a same-category opening in the
                  TWELVE MONTHS BEFORE t0. Available at issue time, free, and
                  the thing a sceptic would actually do. Openings cluster in
                  space and in time, so this is a real bar, not a straw man.
    HOMES-ONLY    reported for continuity with the retrodiction memo. Never the
                  bar.

FAILURE CRITERION, fixed before any vintage was issued. A run is stamped
`ships = false` if ANY of:

    (a) blocked-CV AUC <= the NO-SCORE baseline;
    (b) blocked-CV AUC <= the PERSISTENCE baseline;
    (c) out-of-sample calibration max decile gap > 15 percentage points.

A failing vintage is STILL WRITTEN, still dated and still scored. Deleting a
vintage that failed is how a track record becomes a highlight reel, and the
whole point of a ledger is that it cannot be edited into flattery.

===========================================================================
THE HONESTY GUARDRAILS (D1 and D88), both kept
===========================================================================

D1: retail is the DEPENDENT read, never a predictor of growth. Openings are the
left-hand side here; nothing is regressed on future retail.

D88: this forecasts ENTRY, not VIABILITY. `p_opening` is the probability the
MARKET acts near this doorway, and the retrodiction showed entry going where
supply was ALREADY THICK — consistent with agglomeration economies being real
and equally consistent with herding into saturated corridors. Business-level
survival is not identified in Loci's data, and the one premises-level outcome
that is (LL157 go-dark) returns a null whose sign flips with the definition of
attrition. A high p_opening therefore says "likely to happen", never "likely to
work", and `loci forecast report` prints that sentence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib

import numpy as np
import pandas as pd

from loci.categories import CATEGORIES

PKG = pathlib.Path(__file__).resolve().parents[1]
SQL_028 = PKG / "sql" / "028_forecast.sql"
#: The supply-hash column on analysis.forecast_run (D96, GTM-163 addendum).
#: Applied by `ensure_schema` alongside 028 so this module stays
#: self-sufficient on a warehouse that has not run `loci init-db` since this
#: landed -- see sql/030 for why a version now has to say what it was FIT ON,
#: not only what it IS.
SQL_030 = PKG / "sql" / "030_forecast_supply_hash.sql"
#: The PHASE A reshape (2026-09-16): `analysis.forecast` loses `forecast_id`
#: (257 MiB, a pure restatement of the four-column natural key that already
#: carried a UNIQUE index) and `features_json` (526 MiB, the model INPUT,
#: repeated 4.2M times per vintage) and gains `features_hash`;
#: `analysis.forecast_outcome` loses `forecast_id` for the same four columns.
#: NO VINTAGE IS DELETED — the owner overruled the audit's retention proposal
#: on 2026-09-16 (1); this drops redundant COLUMNS and nothing else.
#:
#: Applied only IF PRESENT. This module is not the owner of any migration file
#: and must run both before and after that file lands: `schema_is_reshaped`
#: below is what the code actually branches on, never the file's existence.
SQL_045 = PKG / "sql" / "045_forecast_natural_key.sql"

#: Semantic version of the FORM. Bump the minor when the functional form or the
#: fit-window rule changes; the feature hash below catches everything else.
#: 0.1.1 (2026-09-14, D96): the hash now also covers the SUPPLY-SET identity
#: (score.supply.supply_hash) and the closure-gate flag -- see model_version()
#: and sql/030_forecast_supply_hash.sql. Bumped because two runs on the same
#: FORM but different supply sets must not read as the same model_version to
#: a reader who has not opened the hash payload.
MODEL_SEMVER = "0.1.1"

#: The forecast horizon, in months. Twelve, and the reason is measurement, not
#: taste: `first_seen_src_date` is a licence, an inspection or a Foursquare
#: minting date, which D80 puts 221-259 days away from fitout. A 3- or 6-month
#: horizon would be dominated by error in the DATING of the outcome rather than
#: by anything about the place. Twelve months is long relative to that error and
#: short enough that a vintage can be scored inside a project's lifetime.
HORIZON_MONTHS = 12

#: Straight-line, EPSG:32618, everywhere — features, anchor and outcome alike.
#: sql/028 states the sign of the bias this buys.
RADIUS_M = 400.0
CRS_METRIC = "EPSG:32618"

#: THE FIT FRAME, and it is not negotiable. Every coefficient in this module is
#: estimated on `frame='lot'` rows and nothing else. A street midpoint (D84) has
#: no PLUTO lot of its own and `units_capped = 0` on all 50,199 of them, so it
#: contributes nothing to the homes denominator it is measured against; letting
#: one into the fit would move every coefficient for a reason that is an
#: artefact of how the point was constructed rather than anything about the
#: block. `build_fit_panel` calls `load_points` with this frame, always.
FRAME = "lot"
FIT_FRAME = FRAME

#: THE SCORING FRAMES. The fitted model is APPLIED to both frames (owner ruling
#: 2026-09-16 (4): "frame='street' points get everything the lot frame has,
#: including a forecast"). This is a strictly larger PREDICTION set, not a
#: larger training set -- see `issue` and `street_frame_readiness`.
#:
#: sql/028's original header said street rows were excluded because "street
#: midpoints have no residents, so the homes denominator of supply_ratio would
#: be structurally zero". That reason does not survive reading `homes_within`:
#: the homes denominator is PLUTO units within 400 m of the point, drawn from
#: the LOT frame only (`WHERE frame = 'lot' AND units_capped > 0`). A street
#: midpoint's own zero units never entered anybody's denominator, including its
#: own; what it gets is the units on the lots around it, which is exactly the
#: quantity the feature means. The exclusion was over-cautious, not wrong-signed.
SCORE_FRAMES: tuple[str, ...] = ("lot", "street")

#: `analysis.forecast.support` vocabulary. 'fitted'/'pooled' say WHICH model
#: produced the row. 'street_no_homes' says the row is a placeholder and not a
#: forecast: a street midpoint with zero PLUTO residential units inside its
#: 400 m disc, where `log_homes` and `supply_ratio` both collapse to their
#: zero-information value and the logit would be extrapolating outside the
#: entire fit support (every lot row that trains the model has homes > 0).
#: The row is still WRITTEN -- dropping it would be an eligibility gate, which
#: the owner forbade on 2026-09-13 -- and it is labelled so that nothing
#: downstream can mistake the number for a prediction.
SUPPORT_FITTED = "fitted"
SUPPORT_POOLED = "pooled"
SUPPORT_STREET_NO_HOMES = "street_no_homes"
SUPPORT_VALUES: tuple[str, ...] = (SUPPORT_FITTED, SUPPORT_POOLED,
                                   SUPPORT_STREET_NO_HOMES)

#: Characters of the md5 kept in `analysis.forecast.features_hash`. 16 hex
#: characters = 64 bits. This is an EQUALITY WITNESS for a feature vector, not
#: a primary key: the birthday bound over 5.0M rows is ~7e-7, and a collision
#: costs a wrong "these two vintages saw the same inputs" answer on one row,
#: never a wrong row identity -- the identity is the four natural-key columns.
FEATURES_HASH_CHARS = 16

#: Above this many fit rows, a constant outcome or a constant regressor is a
#: broken upstream join rather than a small sample, and `fit` refuses instead of
#: handing statsmodels a singular Hessian. Fixtures sit in the tens of rows; a
#: real fold-stack is 360,000.
DEGENERATE_PANEL_MIN = 1_000

BOROUGHS_CODE = ("MN", "BK")
#: `analysis.poi_presence.borough` WAS spelled 'Manhattan'/'Brooklyn' and is now
#: CODES ('MN'/'BK'), rewritten by `loci migrate-warehouse --step
#: poi_presence_vocab` on 2026-09-16 so the warehouse has ONE borough
#: vocabulary. This constant kept its name and changed its values.
#:
#: THIS IS THE FAILURE IT CAUSED, and it is why the guard below exists: the
#: rewrite landed while these readers still filtered on the long form, so
#: `WHERE p.borough IN ('Manhattan','Brooklyn')` matched ZERO rows. Nothing
#: raised. The forecast fit panel came back with 360,000 rows, `own_gap_flag`
#: TRUE everywhere, `log_score` 0.0 everywhere and ZERO positives in all 15
#: categories -- every address in New York reading as a total gap. It was
#: caught only because a design matrix with no variation made the logit's
#: Hessian singular; had one category held a single opening, a fitted,
#: plausible, entirely wrong vintage would have been issued and frozen.
#:
#: A wrong borough vocabulary does not error. It returns nothing.
BOROUGHS_FULL = ("MN", "BK")

ALL_CATEGORIES: tuple[str, ...] = tuple(CATEGORIES)

#: Addresses in the deterministic fit sample AND in the anchor sample. See the
#: module docstring. Ordered by hash(address_id), never by RANDOM().
FIT_SAMPLE_N = 12_000

#: A category gets its OWN logit when it has at least this many dated openings
#: in the fit window. Four free parameters at the conventional ten-events-per-
#: parameter floor is 40 events on the rarer side of the outcome; 150 openings
#: is where that holds with room, given that the binary is on the DISC and the
#: rarer side is whichever of open/not-open is smaller.
SUPPORT_FLOOR = 150

#: Pre-declared failure criterion. See the module docstring.
MAX_CALIBRATION_GAP = 0.15

N_FOLDS = 5
RNG_SEED = 20260914

#: The variance cluster for the NTA surprise z: a grid square twice the
#: catchment radius, so two addresses in different cells cannot share a 400 m
#: disc except across a boundary.
SURPRISE_CELL_M = 800.0

FEATURE_LIST: tuple[str, ...] = ("log_score", "own_gap_flag", "log_homes",
                                 "retail_index")
NO_SCORE_FEATURES: tuple[str, ...] = ("log_homes", "retail_index")
HOMES_ONLY_FEATURES: tuple[str, ...] = ("log_homes",)

FIT_WINDOW_RULE = (
    "two stacked folds, t0 in {issued_month - 24 months, issued_month - 12 "
    "months}; each fold's features frozen at its own t0 and its outcome "
    "observed over its own following 12 months. Nothing dated on or after "
    "issued_month enters the fit.")


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------
def model_version(semver: str = MODEL_SEMVER, *,
                  features: tuple[str, ...] = FEATURE_LIST,
                  horizon: int = HORIZON_MONTHS,
                  radius_m: float = RADIUS_M,
                  support_floor: int = SUPPORT_FLOOR,
                  supply_hash: str = "",
                  gate_closed: bool | None = None) -> str:
    """`<semver>+<8 hex>`, the hex over everything that defines the model.

    Two runs that share a version share a model. The database cannot check
    that, so it is made true by construction: the hash covers the exact feature
    list IN ORDER, the fit-window rule, the horizon, the radius and the support
    floor. Change any of them and the version changes without anyone
    remembering to bump it — which is the only version discipline that
    survives contact with a hurried session.

    AS OF 0.1.1 (D96, GTM-163 addendum), the hash also covers `supply_hash` --
    `score.supply.supply_hash(con)`, the identity of the canonical POI set the
    2026-09 vintage's features were read off -- and `gate_closed`
    (score.supply.GATE_CLOSED). The FORM inputs above describe what the model
    IS; supply_hash and gate_closed describe what it was FIT ON, and the two
    can move independently: a peer re-fitting the baseline (owner ruling
    2026-09-14, supply_hash 767b28674e30 -> 9a11a2f5...) changes nothing about
    the feature list or the fit-window rule, and MUST still change the
    version, or a reader would see one model_version standing for two
    different supply sets. `gate_closed` is redundant with `supply_hash`
    itself (score.supply.supply_hash already folds GATE_CLOSED into its own
    hash) -- it is hashed again here, explicitly, so a reader of THIS
    payload does not have to trust that supply_hash's internals cover it.

    Callers that never pass `supply_hash` (an old caller, a test against a
    warehouse with no supply-set machinery) get the empty string, which is
    hashed like any other value -- NOT skipped -- so "supply unmeasured" is
    itself a distinct, stable version rather than silently degrading to the
    pre-0.1.1 hash.
    """
    if gate_closed is None:
        from loci.score.supply import GATE_CLOSED as gate_closed        # noqa: PLC0415
    payload = json.dumps({
        "semver": semver,
        "features": list(features),
        "fit_window_rule": FIT_WINDOW_RULE,
        "horizon_months": int(horizon),
        "radius_m": float(radius_m),
        "support_floor": int(support_floor),
        "supply_hash": str(supply_hash),
        "gate_closed": bool(gate_closed),
        "form": "two-stage logit: pooled with category FE, per-category above "
                "the support floor",
        "target": "1{>=1 same-category dated first-seen within radius in the "
                  "horizon}",
    }, sort_keys=True)
    return f"{semver}+{hashlib.sha256(payload.encode()).hexdigest()[:8]}"


class AlreadyIssuedError(RuntimeError):
    """`loci forecast issue` would silently overwrite an existing
    (issued_month, model_version) vintage without --force. See `guard_reissue`."""


class StreetFrameNotReadyError(RuntimeError):
    """`issue` was asked to score `frame='street'` rows on a warehouse that
    cannot yet supply what a street row needs.

    RAISED RATHER THAN COALESCED, and that is the whole point. The alternative
    -- fill the missing feature with a zero or a median and write the row -- is
    the bug class this project has been bitten by twice: a zero in a feature
    that means "none here" is indistinguishable from a zero that means "we did
    not look", and the second one manufactures a gap the map then draws.
    """


def live_supply_hash(con, supply_set: str | None = None) -> str:
    """`score.supply.supply_hash(con)`, called from ONE place so `issue` and
    the CLI's refuse-without-force check can never compute two different
    answers for the same warehouse.

    Falls back to the literal string `'unmeasured'` -- never a real 12-hex
    supply hash, so a reader can always tell the two apart -- when the
    supply-set machinery is not present to query (a synthetic test fixture, a
    warehouse that has not run `dedup`/`build_category_anchor` yet). Soft
    failure here matches `score.supply._cats`' own convention (a measurement
    that cannot be taken must not crash a caller that has nothing to do with
    supply sets) rather than the FAIL-OPEN-IS-DANGEROUS posture used inside
    the supply-set principle itself: `p_opening` is not gated by supply
    measurement the way `in_principled` is, so there is nothing here for a
    silent 'unmeasured' to wrongly include or exclude.
    """
    from loci.score.supply import DEFAULT_SUPPLY_SET, supply_hash as _live_hash  # noqa: PLC0415

    sset = supply_set or DEFAULT_SUPPLY_SET
    try:
        return _live_hash(con, sset)
    except Exception:                   # noqa: BLE001 -- supply-set tables absent
        return "unmeasured"


def resolve_version(con, *, version: str | None = None,
                    horizon: int = HORIZON_MONTHS, radius_m: float = RADIUS_M,
                    support_floor: int = SUPPORT_FLOOR,
                    supply_set: str | None = None) -> tuple[str, str]:
    """(model_version, supply_hash) for this fit configuration, on THIS
    warehouse, right now.

    The single place `issue`, `issue_managed` and the CLI's pre-flight
    refuse-without-force check all call, so they can never disagree about
    what a run "would" version itself as. `version`, if given, overrides the
    computed one (reproducing an old vintage under `--model-version`) but the
    supply hash is still measured and returned -- it is what gets printed and
    what gets stamped onto `analysis.forecast_run.supply_hash` either way.
    """
    shash = live_supply_hash(con, supply_set)
    ver = version or model_version(horizon=horizon, radius_m=radius_m,
                                   support_floor=support_floor,
                                   supply_hash=shash)
    return ver, shash


def already_issued(con, month: str, version: str) -> bool:
    """Does (issued_month, model_version) already have a row in
    analysis.forecast_run?

    False, never an exception, on a warehouse that has never written a
    forecast_run -- "no schema yet" and "no rows yet" are the same answer to
    this question."""
    try:
        n = con.execute(
            "SELECT count(*) FROM analysis.forecast_run "
            "WHERE issued_month = ? AND model_version = ?",
            [month, version]).fetchone()[0]
    except Exception:                   # noqa: BLE001 -- table not created yet
        return False
    return bool(n)


def guard_reissue(con, month: str, version: str, *, force: bool = False) -> None:
    """Refuse to reuse an existing (issued_month, model_version) unless
    `force`. Raises `AlreadyIssuedError`, never silently returns False, so a
    caller that forgets to check a boolean does not walk straight into the
    overwrite this exists to stop.

    THIS IS NOT THE VINTAGE-IDEMPOTENCE CONTRACT. `issue` re-running the SAME
    (month, version) is still DELETE+INSERT and still reproduces that
    vintage's answer byte for byte -- that discipline is unchanged and is
    what makes a scheduled `loci forecast issue` safe to re-run. What this
    adds is a REFUSAL to do that BLINDLY from the command line: the owner
    ruling that put this in place (2026-09-14, D96) is precisely the case
    where a version could look unchanged while the supply set underneath it
    moved (a peer's baseline re-fit, 767b28674e30 -> 9a11a2f5...) -- except it
    now CAN'T look unchanged, because supply_hash is hashed into the version
    (see `model_version`). So this guard mostly protects against a different,
    cheaper mistake: running `issue` twice for the same month by hand and not
    noticing the second run silently replaced the first."""
    if force:
        return
    if already_issued(con, month, version):
        raise AlreadyIssuedError(
            f"{month} / {version} already exists in analysis.forecast_run. "
            "Pass --force to re-issue it.")


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------
def ensure_schema(con) -> None:
    """Apply sql/028_forecast.sql then sql/030_forecast_supply_hash.sql.
    Idempotent, and WRITE-ONLY — DuckDB refuses CREATE TABLE / ALTER TABLE ADD
    COLUMN IF NOT EXISTS on a read-only handle, so the read paths call
    `require_schema` instead.

    030 runs AFTER 028 unconditionally, not only on a fresh database: a
    warehouse that already has analysis.forecast_run from before 0.1.1 needs
    the ALTER applied too, and `loci init-db` is not guaranteed to have run
    again since 030 landed.

    045 runs after both, and only if the file exists — this module is written
    to the reshaped contract but does not own the migration that performs the
    reshape, and a warehouse whose sql/ predates it must still open."""
    con.execute(SQL_028.read_text())
    con.execute(SQL_030.read_text())
    if SQL_045.exists():
        con.execute(SQL_045.read_text())


def schema_is_reshaped(con) -> bool:
    """True once `analysis.forecast` is on the natural-key contract: no
    `forecast_id`, and a `features_hash`.

    ASKED OF THE CATALOGUE, NOT OF THE FILESYSTEM. Whether sql/045 exists in
    this checkout says nothing about whether it has been APPLIED to the
    warehouse in front of us, and a peer session's database is the case that
    matters. Callers that must not half-write use this; `_write_vintage` does
    not, because a named-column INSERT against the old table fails loudly on
    its own (`forecast_id` is NOT NULL with no default) and a loud failure is
    the correct outcome there."""
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'forecast'").fetchall()}
    return bool(cols) and "forecast_id" not in cols and "features_hash" in cols


def require_schema(con) -> None:
    try:
        con.execute("SELECT 1 FROM analysis.forecast LIMIT 1")
    except Exception as exc:            # noqa: BLE001 -- duckdb raises several
        raise RuntimeError(
            "analysis.forecast does not exist yet. Run "
            "`loci forecast issue --month YYYY-MM`, which applies "
            "sql/028_forecast.sql.") from exc


#: A peer session holding the warehouse write lock is the NORMAL state of this
#: project (D69), not an error, and a forecast vintage is precisely the kind of
#: thing that must not be written to a throwaway copy. 45 minutes of patience,
#: polled every 45 s: long enough to outlast a validation run or a warehouse
#: rebuild, and it fails loudly rather than quietly working somewhere that gets
#: discarded.
WRITE_RETRIES = 60
WRITE_WAIT_S = 45.0


def connect_write(path=None, retries: int = WRITE_RETRIES,
                  wait_s: float = WRITE_WAIT_S):
    """Re-exported from model/poi_presence rather than re-implemented: a second
    copy of the retry policy is how the two eventually disagree about how long
    to wait, and a ledger that gives up early is a ledger with a hole in it.

    The DEFAULTS are longer here than poi_presence's ten minutes because the
    expensive half of `issue` (the fit and the four-million-row prediction) runs
    BEFORE the first write — so by the time this is called there is a finished
    vintage in memory and abandoning it costs the whole run."""
    from loci.model.poi_presence import connect_write as _cw

    return _cw(path, retries=retries, wait_s=wait_s)


def connect_read(read_only: bool = True, retries: int = WRITE_RETRIES,
                 wait_s: float = WRITE_WAIT_S):
    """A patient READ handle.

    DuckDB's single-file lock is exclusive: while a peer session holds the
    warehouse for writing, a read_only connection is refused too — the lock is
    on the FILE, not on the transaction. `retrodiction.connect` gives up after
    six short attempts, which is right for an interactive research command and
    wrong for a job that is going to run for ten minutes anyway. So this waits
    the same 45 minutes the write handle does.

    Copying the file and reading the copy is NOT an option and the reason is
    not tidiness: a peer mid-write produces a torn snapshot, and a vintage
    fitted on a torn snapshot is frozen, dated, and wrong forever."""
    import time

    from loci import db as locidb

    last = None
    for i in range(retries):
        try:
            return locidb.connect(read_only=read_only)
        except Exception as exc:            # noqa: BLE001 -- duckdb raises several
            last = exc
            if i < retries - 1:
                time.sleep(wait_s)
    raise RuntimeError(
        f"the warehouse stayed locked for {retries * wait_s / 60:.0f} minutes "
        f"({last}). A peer session is holding it.")


def validate_month(month: str) -> None:
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"month must be YYYY-MM, got {month!r}") from exc


def month_first(month: str) -> dt.date:
    """The FIRST day of the month. Features are frozen here — not the last day,
    because 'issued in 2026-09' must not have seen anything that happened
    during 2026-09."""
    validate_month(month)
    y, m = (int(p) for p in month.split("-"))
    return dt.date(y, m, 1)


def add_months(d: dt.date, n: int) -> dt.date:
    total = (d.year * 12 + d.month - 1) + n
    return dt.date(total // 12, total % 12 + 1, 1)


def month_str(d: dt.date) -> str:
    return d.strftime("%Y-%m")


def fit_t0s(issued_month: str, horizon: int = HORIZON_MONTHS) -> list[dt.date]:
    """The two training fold origins. See FIT_WINDOW_RULE."""
    m0 = month_first(issued_month)
    return [add_months(m0, -2 * horizon), add_months(m0, -horizon)]


def current_month(today: dt.date | None = None) -> str:
    return (today or dt.date.today()).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# 1. the frames
# ---------------------------------------------------------------------------
POINTS_SQL = """
SELECT a.address_id AS point_id, a.lon, a.lat, a.nta_code, a.borough,
       c.retail_index
FROM analysis.address a
LEFT JOIN analysis.address_character c USING (address_id)
WHERE a.frame = '{frame}'
  AND a.borough IN ({boroughs})
  AND a.lon IS NOT NULL AND a.lat IS NOT NULL
ORDER BY hash(a.address_id)
{limit}
"""


def load_points(con, *, limit: int | None = None, frame: str = FRAME) -> pd.DataFrame:
    """The lot frame, hash-ordered so `limit` is a DETERMINISTIC sample.

    `ORDER BY hash(address_id)` and never `RANDOM()`: the 12,000-address fit
    sample and the 12,000-address anchor sample must be the SAME 12,000
    addresses on every run, or the base median moves under the model between
    the fit and the prediction."""
    sql = POINTS_SQL.format(
        frame=frame,
        boroughs=", ".join(f"'{b}'" for b in BOROUGHS_CODE),
        limit=f"LIMIT {int(limit)}" if limit else "")
    return con.execute(sql).fetchdf()


def homes_within(con, points: pd.DataFrame, radius_m: float = RADIUS_M,
                 frame: str = FRAME) -> pd.DataFrame:
    """PLUTO residential units within `radius_m` STRAIGHT-LINE of each point.

    ANACHRONISM, STATED: `units_capped` is present-day PLUTO, so a building
    completed in 2024 is credited to a 2023 vintage. It enters as a CONTROL and
    never as the tested variable, and the direction of the bias is toward the
    growth areas — i.e. it flatters the no-score baseline, not the score."""
    from loci.validation import retrodiction as rd

    src = con.execute(f"""
        SELECT lon, lat, units_capped AS weight FROM analysis.address
        WHERE frame = '{frame}'
          AND borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_CODE)})
          AND units_capped > 0 AND lon IS NOT NULL
    """).fetchdf()
    got = rd.count_within(con, points[["point_id", "lon", "lat"]], src,
                          radius_m=radius_m, by="")
    return got.rename(columns={"wsum": "homes"})[["point_id", "homes"]]


def openings_between(con, points: pd.DataFrame, start: dt.date, end: dt.date,
                     radius_m: float = RADIUS_M,
                     categories: tuple[str, ...] = ALL_CATEGORIES) -> pd.DataFrame:
    """Same-category dated first-seens within the disc, in [start, end).

    THE OUTCOME, and also the persistence baseline when called on the twelve
    months BEFORE t0. One definition, one radius, one projection, used for
    both — so the model and the thing it is scored against cannot drift apart.

    `backfill_censored` rows carry no date and can never be an opening. That is
    right (they are not openings) and it makes the realized rate a uniform
    LOWER BOUND on real entry; sql/028 caveat states the consequence."""
    from loci.validation import retrodiction as rd

    cats = ", ".join(f"'{c}'" for c in categories)
    tgt = con.execute(f"""
        SELECT p.lon, p.lat, p.category
        FROM analysis.poi_presence p
        JOIN analysis.poi_supply s
          ON s.poi_id = p.poi_id_latest AND s.in_principled
        WHERE p.borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_FULL)})
          AND p.category IN ({cats})
          AND p.first_seen_kind IN ('source_date', 'gov_filing')
          AND p.first_seen_src_date >= DATE '{start.isoformat()}'
          AND p.first_seen_src_date <  DATE '{end.isoformat()}'
    """).fetchdf()
    if tgt.empty:
        return pd.DataFrame(columns=["point_id", "category", "n"])
    got = rd.count_within(con, points[["point_id", "lon", "lat"]], tgt,
                          radius_m=radius_m)
    return got[["point_id", "category", "n"]]


def dated_openings_by_category(con, start: dt.date, end: dt.date) -> dict[str, int]:
    """How many dated openings each category actually contributes to a fit
    window. This is the SUPPORT number — the one that decides whether a
    category gets its own model — and it is a count of DECLARATIONS, not of
    openings: a restaurant is inspected by DOHMH and licensed by DCWP, a
    hardware store declares nothing to anybody."""
    rows = con.execute(f"""
        SELECT p.category, count(*) AS n
        FROM analysis.poi_presence p
        JOIN analysis.poi_supply s
          ON s.poi_id = p.poi_id_latest AND s.in_principled
        WHERE p.borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_FULL)})
          AND p.first_seen_kind IN ('source_date', 'gov_filing')
          AND p.first_seen_src_date >= DATE '{start.isoformat()}'
          AND p.first_seen_src_date <  DATE '{end.isoformat()}'
        GROUP BY 1
    """).fetchall()
    return {c: int(n) for c, n in rows}


# ---------------------------------------------------------------------------
# 2. the frozen feature block
# ---------------------------------------------------------------------------
def base_medians(con, anchor: pd.DataFrame, t0: dt.date, *,
                 radius_m: float = RADIUS_M,
                 categories: tuple[str, ...] = ALL_CATEGORIES,
                 include_censored: bool = True) -> dict[str, float]:
    """The per-category supply-per-1k median on the ANCHOR SAMPLE at t0.

    ONE anchor rule for fit rows and prediction rows. If the fit used the fit
    sample's median and the prediction used the whole frame's, `log_score`
    would not mean the same thing on the two sides of the model — the quiet
    kind of leakage, the kind that looks like skill."""
    from loci.validation import retrodiction as rd

    sup = rd.supply_as_of(con, anchor[["point_id", "lon", "lat"]], asof=t0,
                          radius_m=radius_m, include_censored=include_censored,
                          categories=categories)
    homes = homes_within(con, anchor, radius_m=radius_m)
    grid = (anchor[["point_id"]]
            .merge(pd.DataFrame({"category": list(categories)}), how="cross")
            .merge(sup, on=["point_id", "category"], how="left")
            .merge(homes, on="point_id", how="left"))
    grid["supply"] = grid["supply"].fillna(0.0)
    grid = grid[grid["homes"] > 0]
    grid["per_1k"] = grid["supply"] / grid["homes"] * 1000.0
    med = grid.groupby("category")["per_1k"].median().to_dict()
    return {c: float(med.get(c, 0.0)) for c in categories}


def frozen_features(con, points: pd.DataFrame, t0: dt.date, *,
                    anchors: dict[str, float],
                    radius_m: float = RADIUS_M,
                    categories: tuple[str, ...] = ALL_CATEGORIES,
                    include_censored: bool = True,
                    homes: pd.DataFrame | None = None) -> pd.DataFrame:
    """address x category, scored AS OF t0 and knowing nothing after it.

    The leakage rule lives in `retrodiction.supply_as_of`, which is CALLED here
    rather than re-implemented — a second copy of "a competitor whose
    first_seen_src_date is after t0 must not count" is a second place for it to
    be got wrong, and that rule is the one the whole exercise rests on.
    `tests/test_forecast.py` pins it again at this level anyway, because the
    thing being asserted is a property of THIS panel, not of that helper.
    """
    from loci.validation import retrodiction as rd

    sup = rd.supply_as_of(con, points[["point_id", "lon", "lat"]], asof=t0,
                          radius_m=radius_m, include_censored=include_censored,
                          categories=categories)
    if homes is None:
        homes = homes_within(con, points, radius_m=radius_m)

    panel = (points[["point_id"]]
             .merge(pd.DataFrame({"category": list(categories)}), how="cross")
             .merge(sup, on=["point_id", "category"], how="left")
             .merge(homes, on="point_id", how="left")
             .merge(points.drop(columns=["lon", "lat"]), on="point_id", how="left"))
    panel["supply"] = panel["supply"].fillna(0.0)
    panel["homes"] = panel["homes"].fillna(0.0)
    panel["base_median"] = panel["category"].map(anchors).astype(float)

    panel["supply_per_1k"] = np.where(
        panel["homes"] > 0, panel["supply"] / panel["homes"].replace(0, np.nan) * 1000.0, 0.0)
    # A category whose anchor is 0 has no scale to divide by. The ratio is set
    # to 0 rather than to an infinity or a NULL: with a zero median the whole
    # category is empty at t0, every address is equally empty, and log1p(0) = 0
    # correctly says "no information in the ratio here". The `own_gap_flag`
    # still carries the presence/absence, and `support_json` records that the
    # anchor was degenerate so the reader is not left to infer it.
    panel["supply_ratio"] = np.where(
        panel["base_median"] > 0,
        panel["supply_per_1k"] / panel["base_median"].replace(0, np.nan), 0.0)
    panel["supply_ratio"] = panel["supply_ratio"].fillna(0.0)

    panel["log_score"] = np.log1p(panel["supply_ratio"])
    panel["own_gap_flag"] = (panel["supply"] == 0).astype(float)
    panel["log_homes"] = np.log1p(panel["homes"])
    med_ri = panel["retail_index"].median()
    panel["retail_index"] = panel["retail_index"].fillna(
        0.0 if pd.isna(med_ri) else med_ri)
    panel["t0"] = t0
    return panel


def with_surprise_cell(points: pd.DataFrame,
                       cell_m: float = SURPRISE_CELL_M) -> pd.DataFrame:
    """The variance cluster for the NTA z: an 800 m grid square in EPSG:32618.

    Twice the catchment radius, so two addresses in different cells cannot
    share a 400 m disc except across a boundary — which is what makes the
    cluster-robust sandwich in `analysis.forecast_surprise_nta` an honest
    standard error rather than a decorative one."""
    from loci.validation.retrodiction import _project

    x, y = _project(points["lon"].to_numpy(), points["lat"].to_numpy())
    cx = np.floor(np.asarray(x) / cell_m).astype(int)
    cy = np.floor(np.asarray(y) / cell_m).astype(int)
    return points.assign(surprise_cell=[f"{a}:{b}" for a, b in zip(cx, cy)])


# ---------------------------------------------------------------------------
# 3. the fit
# ---------------------------------------------------------------------------
def _design(panel: pd.DataFrame, cols: list[str], cat_levels: list[str]) -> np.ndarray:
    """Design matrix with a FIXED dummy ordering.

    `cat_levels` is passed in rather than inferred from the frame, because
    `pd.get_dummies` on a prediction frame that happens to be missing a
    category would silently produce a different column order and the
    coefficients would be applied to the wrong variables. The fitted level list
    travels with the fit."""
    X = panel[cols].astype(float).to_numpy()
    parts = [np.ones((len(panel), 1)), X]
    if len(cat_levels) > 1:
        cat = panel["category"].to_numpy()
        for lvl in cat_levels[1:]:
            parts.append((cat == lvl).astype(float).reshape(-1, 1))
    return np.hstack(parts)


def _names(cols: list[str], cat_levels: list[str]) -> list[str]:
    return ["const", *cols, *[f"cat_{c}" for c in cat_levels[1:]]]


def _fit_logit(panel: pd.DataFrame, cols: list[str], cat_levels: list[str]):
    import statsmodels.api as sm

    X = _design(panel, cols, cat_levels)
    y = panel["y"].to_numpy(dtype=float)
    return sm.Logit(y, X).fit(disp=0, maxiter=200)


def _fit_logit_clustered(panel: pd.DataFrame, cols: list[str],
                         cat_levels: list[str], cluster: str = "nta_code"):
    """Coefficients with NTA-clustered standard errors.

    Clustered because 12,000 overlapping discs are nothing like 12,000
    independent observations. This does NOT fix inference — the retrodiction
    measured out-of-sample residual Moran's I at 0.64-0.77, and cluster-robust
    SEs still assume independence ACROSS clusters — which is exactly why the
    two marginal coefficients (jobs, transit) are not in the model at all."""
    import statsmodels.api as sm

    X = _design(panel, cols, cat_levels)
    y = panel["y"].to_numpy(dtype=float)
    groups = panel[cluster].fillna("NA").to_numpy()
    return sm.Logit(y, X).fit(disp=0, maxiter=200, cov_type="cluster",
                              cov_kwds={"groups": groups, "use_correction": True})


def _nta_folds(panel: pd.DataFrame, n_folds: int = N_FOLDS,
               seed: int = RNG_SEED) -> list[np.ndarray]:
    """WHOLE NTAs held out. A random k-fold split would put the same 400 m disc
    on both sides of the split and report the leak as skill."""
    rng = np.random.default_rng(seed)
    ntas = np.asarray(panel["nta_code"].fillna("NA").unique(), dtype=object)
    rng.shuffle(ntas)
    # Never more folds than NTAs: array_split would emit empty folds, every
    # empty fold is a silently skipped one, and a "5-fold" CV that actually ran
    # two is a diagnostic lying about its own denominator.
    k = max(2, min(n_folds, len(ntas)))
    return [np.asarray(f, dtype=object) for f in np.array_split(ntas, k)]


def blocked_oos_predictions(panel: pd.DataFrame, cols: list[str], *,
                            per_category: dict[str, bool] | None = None,
                            n_folds: int = N_FOLDS,
                            seed: int = RNG_SEED) -> np.ndarray:
    """Out-of-sample p for every row, produced by the SAME two-stage structure
    the shipped model uses.

    A diagnostic that evaluates a different model from the one that ships is
    not a diagnostic. So when `per_category[c]` is True, fold-held-out rows of
    category c are predicted by a logit refitted on category c's TRAINING rows
    only; otherwise by the pooled logit refitted on all training rows.
    """
    idx = panel.reset_index(drop=True)
    per_category = per_category or {}
    cat_levels = sorted(idx["category"].unique())
    preds = np.full(len(idx), np.nan)
    nta = idx["nta_code"].fillna("NA")

    for fold in _nta_folds(idx, n_folds=n_folds, seed=seed):
        te = nta.isin(fold).to_numpy()
        tr = ~te
        if te.sum() == 0 or idx.loc[tr, "y"].nunique() < 2:
            continue
        try:
            pooled = _fit_logit(idx[tr], cols, cat_levels)
        except Exception:    # noqa: S112, BLE001 -- separation in a fold is
            continue         # expected; the fold is skipped, not the run
        te_idx = np.flatnonzero(te)
        preds[te_idx] = pooled.predict(_design(idx.iloc[te_idx], cols, cat_levels))

        for cat, own in per_category.items():
            if not own:
                continue
            sub_tr = tr & (idx["category"] == cat).to_numpy()
            sub_te = np.flatnonzero(te & (idx["category"] == cat).to_numpy())
            if len(sub_te) == 0 or idx.loc[sub_tr, "y"].nunique() < 2:
                continue
            try:
                m = _fit_logit(idx[sub_tr], cols, [cat])
                preds[sub_te] = m.predict(_design(idx.iloc[sub_te], cols, [cat]))
            except Exception:    # noqa: S112, BLE001 -- as above, per category
                continue
    return preds


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def _log_loss(y: np.ndarray, p: np.ndarray, eps: float = 1e-9) -> float:
    p = np.clip(np.asarray(p, dtype=float), eps, 1 - eps)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Deciles of predicted probability against the observed rate.

    A ranking deliverable still needs calibration beside it: an AUC says the
    order is right, and says nothing about whether a 0.30 means thirty
    percent."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    ok = ~np.isnan(p)
    y, p = y[ok], p[ok]
    if len(p) == 0:
        return []
    q = pd.qcut(pd.Series(p).rank(method="first"), bins, labels=False,
                duplicates="drop")
    out = []
    for d in sorted(pd.unique(q)):
        m = (q == d).to_numpy()
        out.append({"decile": int(d) + 1, "n": int(m.sum()),
                    "predicted": float(p[m].mean()),
                    "observed": float(y[m].mean())})
    return out


def calibration_max_gap(cal: list[dict]) -> float:
    if not cal:
        return float("nan")
    return float(max(abs(c["predicted"] - c["observed"]) for c in cal))


def fit(panel: pd.DataFrame, *, support: dict[str, int],
        support_floor: int = SUPPORT_FLOOR) -> dict:
    """The two-stage fit plus every baseline and the pre-declared verdict.

    Returns a dict carrying the pooled coefficients, one per-category model for
    each supported category, the blocked-CV diagnostics, and `ships` /
    `ships_reason` evaluated against the failure criterion fixed in the module
    docstring — NOT re-judged afterwards.
    """
    from loci.validation.retrodiction import _auc

    p = panel.dropna(subset=["log_score", "y"]).copy()
    cat_levels = sorted(p["category"].unique())
    cols = list(FEATURE_LIST)

    fitted_cats = {
        c: bool(support.get(c, 0) >= support_floor
                and (p["category"] == c).sum() >= 500
                and p.loc[p["category"] == c, "y"].nunique() == 2)
        for c in cat_levels}

    # REFUSE A DEGENERATE PANEL RATHER THAN FIT ONE.
    #
    # On 2026-09-16 the borough-vocabulary rewrite left these readers filtering
    # `poi_presence.borough` on the OLD long-form spelling, so the supply lookup
    # matched zero rows. The panel arrived with 360,000 rows, `own_gap_flag`
    # TRUE everywhere, `log_score` 0.0 everywhere and ZERO positives in all 15
    # categories -- every address in New York reading as a total gap -- and the
    # only reason a wrong vintage was not issued and FROZEN is that a design
    # matrix with no variation happened to make the logit's Hessian singular.
    # `LinAlgError: Singular matrix` is not a diagnosis; these checks are.
    #
    # Each names the quantity that is degenerate, because "the fit failed" sends
    # the reader to statsmodels and "the outcome is constant" sends them to the
    # supply join, which is where the bug actually was.
    # The checks apply only to a panel big enough for their premise to hold. A
    # 12-row fixture with no openings is a test exercising the SCORING path; a
    # 360,000-row panel with no openings is a broken join. DEGENERATE_PANEL_MIN
    # sits far above any fixture and far below a real fold-stack (360,000).
    n_pos = int(p["y"].sum())
    if len(p) >= DEGENERATE_PANEL_MIN and n_pos == 0:
        raise RuntimeError(
            f"fit panel has {len(p):,} rows and ZERO positive outcomes across "
            f"{len(cat_levels)} categories. The model cannot be fitted, and the "
            f"cause is upstream of the fit: an opening-side join returning "
            f"nothing. Check that the supply lookup's borough predicate matches "
            f"`analysis.poi_presence.borough`'s CURRENT vocabulary (codes since "
            f"2026-09-16) -- a wrong vocabulary returns no rows and never raises.")
    degenerate = ([c for c in cols if p[c].nunique(dropna=True) <= 1]
                  if len(p) >= DEGENERATE_PANEL_MIN else [])
    if degenerate:
        raise RuntimeError(
            f"fit panel features {degenerate} are constant over {len(p):,} rows. "
            f"A constant regressor cannot be identified, and a feature that is "
            f"constant across all of New York is a broken input, not a finding. "
            f"log_score = 0 and own_gap_flag = 1 everywhere means the supply "
            f"lookup returned zero POIs.")

    pooled = _fit_logit_clustered(p, cols, cat_levels)
    pooled_names = _names(cols, cat_levels)
    coefs = {"pooled": {
        n: {"coef": float(pooled.params[i]), "se": float(pooled.bse[i]),
            "z": float(pooled.tvalues[i]), "p": float(pooled.pvalues[i]),
            "ci_lo": float(pooled.conf_int()[i][0]),
            "ci_hi": float(pooled.conf_int()[i][1])}
        for i, n in enumerate(pooled_names)}}

    per_cat_models: dict[str, dict] = {}
    for cat, own in fitted_cats.items():
        if not own:
            continue
        g = p[p["category"] == cat]
        try:
            m = _fit_logit_clustered(g, cols, [cat])
        except Exception as exc:                       # noqa: BLE001
            fitted_cats[cat] = False
            per_cat_models[cat] = {"skipped": str(exc)[:160]}
            continue
        nm = _names(cols, [cat])
        per_cat_models[cat] = {
            "n": int(len(g)), "positive_rate": float(g["y"].mean()),
            "params": [float(v) for v in m.params],
            "names": nm,
            "coefficients": {
                n: {"coef": float(m.params[i]),
                    "ci_lo": float(m.conf_int()[i][0]),
                    "ci_hi": float(m.conf_int()[i][1]),
                    "p": float(m.pvalues[i])}
                for i, n in enumerate(nm)}}
    coefs["by_category"] = per_cat_models
    coefs["pooled_params"] = [float(v) for v in pooled.params]
    coefs["pooled_names"] = pooled_names
    coefs["cat_levels"] = cat_levels

    y = p["y"].to_numpy(dtype=float)
    oos_full = blocked_oos_predictions(p, cols, per_category=fitted_cats)
    oos_nos = blocked_oos_predictions(p, list(NO_SCORE_FEATURES),
                                      per_category=fitted_cats)
    oos_homes = blocked_oos_predictions(p, list(HOMES_ONLY_FEATURES),
                                        per_category=fitted_cats)
    ok = ~np.isnan(oos_full)

    def _safe_auc(mask, pred) -> float:
        """NaN, never a number, when there is nothing to score.

        Every fold can be skipped — separation, an NTA with no variance, a
        panel with fewer NTAs than folds — and an AUC computed on an empty
        array is not a small AUC, it is an absent one. Returning NaN makes the
        failure criterion below refuse to ship, which is the correct answer to
        "we could not measure it"."""
        yy, pp = y[mask], np.asarray(pred)[mask]
        if len(yy) == 0 or len(set(yy.tolist())) < 2:
            return float("nan")
        return float(_auc(yy, pp))

    auc_full = _safe_auc(ok, oos_full)
    auc_nos = _safe_auc(ok & ~np.isnan(oos_nos), oos_nos)
    auc_homes = _safe_auc(ok & ~np.isnan(oos_homes), oos_homes)
    auc_persist = (_safe_auc(np.ones(len(p), dtype=bool), p["y_prev"].to_numpy(dtype=float))
                   if "y_prev" in p and p["y_prev"].nunique() > 1 else float("nan"))

    cal = calibration(y[ok], oos_full[ok])
    gap = calibration_max_gap(cal)

    reasons = []
    if np.isnan(auc_full):
        reasons.append(
            "the NTA-blocked folds produced no scoreable out-of-sample "
            "predictions (too few NTAs, no outcome variance, or separation in "
            "every fold) — the model is unmeasured, not good")
    elif not (auc_full > auc_nos):
        reasons.append(f"AUC {auc_full:.4f} does not beat the no-score "
                       f"baseline {auc_nos:.4f}")
    if not np.isnan(auc_full) and not (np.isnan(auc_persist)
                                       or auc_full > auc_persist):
        reasons.append(f"AUC {auc_full:.4f} does not beat persistence "
                       f"{auc_persist:.4f}")
    if not (gap <= MAX_CALIBRATION_GAP):
        reasons.append(f"calibration max decile gap {gap:.3f} exceeds "
                       f"{MAX_CALIBRATION_GAP:.2f}"
                       if not np.isnan(gap) else
                       "calibration could not be computed out of sample")
    ships = not reasons

    per_cat_auc = {}
    for cat in cat_levels:
        m = (p["category"] == cat).to_numpy() & ok
        if m.sum() < 100 or len(set(y[m])) < 2:
            per_cat_auc[cat] = {"n": int(m.sum()), "skipped": "no variance or n < 100"}
            continue
        per_cat_auc[cat] = {
            "n": int(m.sum()), "positive_rate": float(y[m].mean()),
            "auc": _safe_auc(m, oos_full),
            "brier": _brier(y[m], oos_full[m]),
            "support_openings": int(support.get(cat, 0)),
            "model": "fitted" if fitted_cats.get(cat) else "pooled"}

    return {
        "n_rows": int(len(p)),
        "n_addresses": int(p["point_id"].nunique()),
        "n_ntas": int(p["nta_code"].nunique()),
        "positive_rate": float(y.mean()),
        "fitted_categories": {k: bool(v) for k, v in fitted_cats.items()},
        "coefficients": coefs,
        "auc_blocked": float(auc_full),
        "auc_no_score": float(auc_nos),
        "auc_persistence": float(auc_persist),
        "auc_homes_only": float(auc_homes),
        "auc_lift_vs_no_score": float(auc_full - auc_nos),
        "brier": _brier(y[ok], oos_full[ok]),
        "log_loss": _log_loss(y[ok], oos_full[ok]),
        "calibration": cal,
        "calibration_max_gap": gap,
        "by_category": per_cat_auc,
        "ships": bool(ships),
        "ships_reason": ("passes: beats the no-score and persistence baselines, "
                         "calibration within tolerance" if ships
                         else "; ".join(reasons)),
    }


def predict(fit_result: dict, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Apply the fitted two-stage model. Returns (p, is_fitted_model).

    The per-category model owns its rows; everything else is the pooled model.
    Column order comes from the FIT (`cat_levels`, `names`), never from the
    prediction frame."""
    coefs = fit_result["coefficients"]
    cat_levels = list(coefs["cat_levels"])
    cols = list(FEATURE_LIST)
    out = np.full(len(panel), np.nan)
    fitted = np.zeros(len(panel), dtype=bool)

    # CHUNKED. The prediction frame is 281,842 addresses x 15 categories, and a
    # single design matrix over it is 4.2M x 19 float64 -- 640 MB, doubled
    # during the hstack. Chunking costs nothing and keeps the run off swap.
    beta = np.asarray(coefs["pooled_params"], dtype=float)
    step = 500_000
    for lo in range(0, len(panel), step):
        hi = min(lo + step, len(panel))
        X = _design(panel.iloc[lo:hi], cols, cat_levels)
        out[lo:hi] = 1.0 / (1.0 + np.exp(-(X @ beta)))

    cat = panel["category"].to_numpy()
    for c, m in coefs["by_category"].items():
        if "params" not in m:
            continue
        sel = np.flatnonzero(cat == c)
        if len(sel) == 0:
            continue
        b = np.asarray(m["params"], dtype=float)
        Xc = _design(panel.iloc[sel], cols, [c])
        out[sel] = 1.0 / (1.0 + np.exp(-(Xc @ b)))
        fitted[sel] = True
    return out, fitted


# ---------------------------------------------------------------------------
# 4. issue
# ---------------------------------------------------------------------------
#: Tables a `frame='street'` scoring pass declares a dependency on, beyond what
#: `frame='lot'` already needs. `address_demographics` is NOT read by any of the
#: four features (see FEATURE_LIST) -- it is declared here anyway, and a missing
#: one is FATAL, for a provenance reason rather than an arithmetic one: a
#: vintage is a frozen claim about a warehouse state, and issuing the first
#: street rows against a warehouse where half the street-frame measures do not
#: exist yet produces a vintage nobody can re-derive once the sibling build
#: lands. The 50,199 street rows have zero demographics rows as of 2026-09-16.
STREET_PREREQUISITE_TABLES: tuple[tuple[str, str], ...] = (
    ("analysis", "address_demographics"),
)


def _relation_exists(con, schema: str, name: str) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?",
        [schema, name]).fetchone()[0])


def street_frame_readiness(con, *, boroughs: tuple[str, ...] = BOROUGHS_CODE,
                           require_demographics: bool = True) -> dict:
    """Can this warehouse score `frame='street'` HONESTLY? A pure read.

    Returns counts plus `blockers` -- the reasons `issue` must refuse. Two
    kinds of thing are checked and they are not the same kind:

      A MODEL FEATURE THAT IS MISSING is always a blocker. `retail_index`
      (D82 character, `analysis.address_character`) is the only one of the four
      that is read off the address rather than computed from the point's
      coordinates, so it is the only one that CAN be missing. A NULL there
      today is filled with the panel median by `frozen_features`; that fill is
      harmless on the lot frame where the column is 100% populated and would be
      a fabricated feature on a frame where it is not, so this refuses first.

      A DECLARED PREREQUISITE THAT IS MISSING is a blocker by policy, not by
      arithmetic -- see STREET_PREREQUISITE_TABLES.

    NOT a blocker: `homes = 0`. That is a real, measured property of the
    midpoint (no PLUTO residential units inside its 400 m disc), not an
    absence of measurement, and its rows are written with
    `support = 'street_no_homes'` rather than refused -- see SUPPORT_VALUES.
    """
    bor = ", ".join(f"'{b}'" for b in boroughs)
    row = con.execute(f"""
        SELECT count(*)                                            AS n_street,
               count(*) FILTER (WHERE a.lon IS NULL OR a.lat IS NULL) AS n_no_coords,
               count(*) FILTER (WHERE c.retail_index IS NULL)      AS n_no_retail_index,
               count(*) FILTER (WHERE a.nta_code IS NULL)          AS n_no_nta
        FROM analysis.address a
        LEFT JOIN analysis.address_character c USING (address_id)
        WHERE a.frame = 'street' AND a.borough IN ({bor})
    """).fetchone()
    out = {"n_street": int(row[0]), "n_no_coords": int(row[1]),
           "n_no_retail_index": int(row[2]), "n_no_nta": int(row[3]),
           "prerequisites": {}, "blockers": []}

    # AN EMPTY FRAME IS NOT A BLOCKER. A warehouse with no street rows at all
    # -- a second city, a scratch fixture -- has nothing to score on that frame
    # and nothing to get wrong. Refusing there would make the street frame a
    # requirement rather than an addition, and `score/` and `model/` are meant
    # to be city-agnostic.
    if out["n_street"] == 0:
        out["ready"] = True
        return out
    if out["n_no_retail_index"]:
        out["blockers"].append(
            f"{out['n_no_retail_index']:,} of {out['n_street']:,} street "
            "addresses have a NULL analysis.address_character.retail_index, "
            "which is a MODEL FEATURE (FEATURE_LIST). Refusing rather than "
            "median-filling it: a filled feature is a fabricated one.")

    for schema, name in STREET_PREREQUISITE_TABLES:
        rel = f"{schema}.{name}"
        if not _relation_exists(con, schema, name):
            out["prerequisites"][rel] = None
            if require_demographics:
                out["blockers"].append(
                    f"{rel} does not exist; the street frame declares it as a "
                    "prerequisite (STREET_PREREQUISITE_TABLES)")
            continue
        covered = int(con.execute(f"""
            SELECT count(*) FROM analysis.address a
            JOIN {rel} d USING (address_id)
            WHERE a.frame = 'street' AND a.borough IN ({bor})
        """).fetchone()[0])
        out["prerequisites"][rel] = covered
        if covered < out["n_street"] and require_demographics:
            out["blockers"].append(
                f"{rel} covers {covered:,} of {out['n_street']:,} street "
                "addresses; the street frame declares it as a prerequisite "
                "(STREET_PREREQUISITE_TABLES)")

    out["ready"] = not out["blockers"]
    return out


def require_street_frame_ready(con, *, boroughs: tuple[str, ...] = BOROUGHS_CODE,
                               require_demographics: bool = True) -> dict:
    """`street_frame_readiness`, raising `StreetFrameNotReadyError` when it is
    not. Called by `issue` BEFORE the fit, so a warehouse that cannot support
    the street frame costs a query rather than forty minutes."""
    rep = street_frame_readiness(con, boroughs=boroughs,
                                 require_demographics=require_demographics)
    if rep["blockers"]:
        raise StreetFrameNotReadyError(
            "cannot score frame='street' on this warehouse:\n  - "
            + "\n  - ".join(rep["blockers"])
            + "\n(pass score_frames=('lot',) to issue the lot frame alone)")
    return rep


def build_fit_panel(con, issued_month: str, *, radius_m: float = RADIUS_M,
                    horizon: int = HORIZON_MONTHS,
                    sample_n: int = FIT_SAMPLE_N,
                    categories: tuple[str, ...] = ALL_CATEGORIES,
                    anchor: pd.DataFrame | None = None,
                    points: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """The stacked training folds. NOTHING dated on or after `issued_month`.

    THE FIT UNIVERSE IS `FIT_FRAME` ONLY, and the 2026-09-16 street-frame work
    did not touch it. `load_points` is called here with `frame=FIT_FRAME`
    explicitly rather than by default, so that a later session widening the
    SCORING frames cannot widen this one by editing one default. A street
    midpoint in the fit would move every coefficient.

    Returns (panel, support) where support is the per-category dated-opening
    count over the union of the fold outcome windows."""
    m0 = month_first(issued_month)
    if points is None:
        points = load_points(con, limit=sample_n, frame=FIT_FRAME)
    if anchor is None:
        anchor = points
    homes = homes_within(con, points, radius_m=radius_m)

    frames = []
    for t0 in fit_t0s(issued_month, horizon):
        end = add_months(t0, horizon)
        if end > m0:
            raise ValueError(
                f"fold outcome window {t0}..{end} runs past the issue month "
                f"{m0} — that is leakage, not a fit window")
        anchors = base_medians(con, anchor, t0, radius_m=radius_m,
                               categories=categories)
        f = frozen_features(con, points, t0, anchors=anchors, radius_m=radius_m,
                            categories=categories, homes=homes)
        outc = openings_between(con, points, t0, end, radius_m=radius_m,
                                categories=categories)
        prev = openings_between(con, points, add_months(t0, -horizon), t0,
                                radius_m=radius_m, categories=categories)
        f = (f.merge(outc.rename(columns={"n": "openings"}),
                     on=["point_id", "category"], how="left")
               .merge(prev.rename(columns={"n": "openings_prev"}),
                      on=["point_id", "category"], how="left"))
        f["openings"] = f["openings"].fillna(0)
        f["openings_prev"] = f["openings_prev"].fillna(0)
        f["y"] = (f["openings"] > 0).astype(int)
        f["y_prev"] = (f["openings_prev"] > 0).astype(int)
        f["fold_t0"] = t0
        frames.append(f)

    panel = pd.concat(frames, ignore_index=True)
    panel = panel[panel["homes"] > 0].copy()

    lo = min(fit_t0s(issued_month, horizon))
    support = dated_openings_by_category(con, lo, m0)
    return panel, support


def issue(con, month: str, *, version: str | None = None,
          radius_m: float = RADIUS_M, horizon: int = HORIZON_MONTHS,
          sample_n: int = FIT_SAMPLE_N,
          categories: tuple[str, ...] = ALL_CATEGORIES,
          limit_points: int | None = None,
          supply_set: str | None = None,
          score_frames: tuple[str, ...] = SCORE_FRAMES,
          require_street_demographics: bool = True,
          dry_run: bool = False, progress=None, write_con=None) -> dict:
    """Fit on the LOT frame, predict every address x category in
    `score_frames`, and write the vintage.

    ONE UNIVERSE FITS, TWO ARE SCORED, and the asymmetry is the point.
    `build_fit_panel` is called with `FIT_FRAME` and nothing else, so every
    coefficient in `res` is estimated on lot rows exactly as it was before
    2026-09-16. `score_frames` changes which rows that ALREADY-FITTED model is
    applied to (owner ruling (4): street points get everything the lot frame
    has, including a forecast). Adding 'street' cannot move a coefficient; it
    can only add rows.

    A street row is refused outright, before the fit, if the warehouse cannot
    feed it honestly -- see `require_street_frame_ready`. It is written with
    `support = 'street_no_homes'` when its 400 m disc holds no PLUTO
    residential units: a measured deficiency, labelled, never a silent zero
    and never a dropped address.

    IDEMPOTENT PER (issued_month, model_version) by DELETE-then-INSERT. Running
    the same model on the same month twice reproduces that month's answer;
    running a DIFFERENT model writes a different version ALONGSIDE, never over.
    Re-issuing a past vintage with a newer model is the one thing this ledger
    exists to make impossible, and the unique index on
    (issued_month, model_version, address_id, category) is what makes an
    accidental double-write an error rather than a duplicate.

    `con` may be READ-ONLY. Every expensive step — the two fit folds, the
    blocked CV, the four-million-row prediction — reads only, and the first
    write happens on `write_con` at the very end.

    DuckDB refuses two connections to one file with different configurations in
    one process, so `issue_managed` is the entry point that handles the
    read-then-write dance (open read, compute, CLOSE, open write, commit). This
    function is the single-handle form: it is what the tests use, and what a
    caller who already holds a writable handle wants."""
    validate_month(month)
    frames = tuple(score_frames)
    unknown = [f for f in frames if f not in SCORE_FRAMES]
    if unknown:
        raise ValueError(f"unknown score frame(s) {unknown}; "
                         f"expected a subset of {list(SCORE_FRAMES)}")
    if FIT_FRAME not in frames:
        raise ValueError(
            f"score_frames={list(frames)} omits the fit frame {FIT_FRAME!r}. "
            "A vintage that scores the street frame and not the lot frame "
            "would be a model applied only where it was never fitted.")
    ver, shash = resolve_version(con, version=version, horizon=horizon,
                                 radius_m=radius_m, supply_set=supply_set)
    m0 = month_first(month)
    say = progress or (lambda *_: None)
    say(f"supply hash this vintage fits on: {shash}")

    # BEFORE THE FIT, not after it. The refusal costs four queries; discovering
    # it after the forty-minute prediction pass costs the pass.
    street_ready = None
    if "street" in frames:
        street_ready = require_street_frame_ready(
            con, require_demographics=require_street_demographics)

    say(f"1/5 frames — fit sample {sample_n:,}, anchor = the same sample")
    fit_points = load_points(con, limit=sample_n, frame=FIT_FRAME)
    say("2/5 fit panel (two folds, both ending before the issue month)")
    panel, support = build_fit_panel(con, month, radius_m=radius_m,
                                     horizon=horizon, sample_n=sample_n,
                                     categories=categories,
                                     anchor=fit_points, points=fit_points)
    say(f"3/5 fit — {len(panel):,} rows, {panel['nta_code'].nunique()} NTAs")
    res = fit(panel, support=support)

    # ONE ANCHOR, COMPUTED ONCE, ON THE LOT FIT SAMPLE — for every scored
    # frame. A street-specific base median would make `log_score` mean a
    # different thing on the two frames and the pooled coefficient would be
    # multiplying two different quantities.
    anchors = base_medians(con, fit_points, m0, radius_m=radius_m,
                           categories=categories)

    say(f"4/5 prediction frames — {', '.join(frames)} in MN+BK x "
        f"{len(categories)} categories")
    blocks, by_frame = [], {}
    for frame in frames:
        block = _predict_frame(con, res, frame=frame, t0=m0, anchors=anchors,
                               radius_m=radius_m, categories=categories,
                               limit_points=limit_points, progress=say)
        by_frame[frame] = {
            "n_rows": int(len(block)),
            "n_addresses": int(block["point_id"].nunique()) if len(block) else 0,
            "n_street_no_homes": int(
                (block["support"] == SUPPORT_STREET_NO_HOMES).sum()),
        }
        # An empty block is DROPPED rather than concatenated. `pd.concat` on a
        # frame with a subset of the columns fills the rest with NaN, and a NaN
        # in `retail_index` is exactly the silent hole `_write_vintage` refuses
        # -- it would turn "this frame has no rows" into "this frame has rows
        # with no features".
        if len(block):
            blocks.append(block)
    if not blocks:
        raise RuntimeError(
            f"no prediction rows on any of {list(frames)} — refusing to write "
            "an empty vintage")
    pred = pd.concat(blocks, ignore_index=True) if len(blocks) > 1 else blocks[0]

    say(f"5/5 write — {len(pred):,} rows, vintage {month} / {ver}")
    n_written = 0
    if not dry_run:
        w = write_con if write_con is not None else con
        ensure_schema(w)
        n_written = _write_vintage(w, pred, month=month, version=ver,
                                   horizon=horizon, t0=m0)
        _write_run(w, month=month, version=ver, horizon=horizon,
                   radius_m=radius_m, res=res, support=support,
                   n_rows=n_written, anchors=anchors, supply_hash=shash,
                   by_frame=by_frame)

    return {"issued_month": month, "model_version": ver, "supply_hash": shash,
            "horizon_months": horizon, "radius_m": radius_m,
            "fit": res, "support": support, "anchors": anchors,
            "score_frames": list(frames), "by_frame": by_frame,
            "street_readiness": street_ready,
            "n_rows_issued": int(n_written), "n_rows_predicted": int(len(pred)),
            "dry_run": bool(dry_run), "_pred": pred, "_t0": m0}


def _predict_frame(con, res: dict, *, frame: str, t0: dt.date,
                   anchors: dict, radius_m: float,
                   categories: tuple[str, ...],
                   limit_points: int | None = None,
                   progress=None) -> pd.DataFrame:
    """Score ONE frame with the ALREADY-FITTED `res`. Returns the prediction
    block with `frame`, `p_opening` and `support` attached.

    The two frames are scored in SEPARATE calls rather than in one concatenated
    panel on purpose. `frozen_features` fills a NULL `retail_index` with the
    PANEL median; pooling the frames would make the lot frame's fill depend on
    the street frame's distribution, so lot output would stop being
    reproducible from a lot-only run. Separate calls keep the lot block
    byte-identical to what this module produced before the street frame existed.
    """
    say = progress or (lambda *_: None)
    points = load_points(con, limit=limit_points, frame=frame)
    if points.empty:
        return pd.DataFrame(columns=["point_id", "category", "frame",
                                     "p_opening", "support"])
    # THE REFUSAL, AT THE ROW LEVEL. `require_street_frame_ready` checks the
    # whole frame up front; this catches the case where `limit_points` or a
    # concurrent write moved the set under us. Not coalesced -- raised.
    n_null_ri = int(points["retail_index"].isna().sum())
    if n_null_ri and frame != FIT_FRAME:
        raise StreetFrameNotReadyError(
            f"{n_null_ri:,} of {len(points):,} frame={frame!r} points have a "
            "NULL retail_index, which is a model feature. `frozen_features` "
            "would fill it with the panel median; a fabricated feature is not "
            "a forecast.")
    points = with_surprise_cell(points)
    # `surprise_cell` rides in on `points` through frozen_features' own merge
    # of the point attributes; re-merging it here would collide.
    block = frozen_features(con, points, t0, anchors=anchors,
                            radius_m=radius_m, categories=categories)

    if frame == FIT_FRAME:
        # UNCHANGED FROM THE PRE-STREET CODE. A lot address with no homes in
        # its own 400 m disc is dropped, as it always has been; every vintage
        # in the ledger was written under this rule and changing it would make
        # the 2026-09 re-issue incomparable to its five predecessors.
        block = block[block["homes"] > 0].copy()
        no_homes = np.zeros(len(block), dtype=bool)
    else:
        # THE STREET FRAME KEEPS ITS ZERO-HOMES ROWS AND LABELS THEM. Dropping
        # them would be an eligibility gate (owner, 2026-09-13). 1,169 of the
        # 50,199 street midpoints are in this state as of 2026-09-16 -- parks,
        # water edges, industrial strips.
        block = block.copy()
        no_homes = (block["homes"] <= 0).to_numpy()

    p, is_fitted = predict(res, block)
    block["p_opening"] = np.clip(p, 1e-9, 1 - 1e-9)
    support = np.where(is_fitted, SUPPORT_FITTED, SUPPORT_POOLED)
    block["support"] = np.where(no_homes, SUPPORT_STREET_NO_HOMES, support)
    block["frame"] = frame
    n_flag = int(no_homes.sum())
    say(f"  {frame}: {len(block):,} rows"
        + (f", {n_flag:,} flagged {SUPPORT_STREET_NO_HOMES}" if n_flag else ""))
    return block


def issue_managed(month: str, *, progress=None, **kw) -> dict:
    """`issue`, holding ONE warehouse handle at a time.

    DuckDB will not open a second connection to the same file with a different
    configuration inside one process ("Can't open a connection to same database
    file with a different configuration"), and read_only=True versus False is
    exactly such a difference. So: open READ, do the fit and the four-million-row
    prediction, CLOSE, open WRITE, commit.

    The ordering is also what makes a peer session's lock cheap. All the
    expensive work happens while the peer is still busy; the write handle is
    asked for once, with a finished vintage already in memory, and waits up to
    45 minutes for it."""
    say = progress or (lambda *_: None)
    con = connect_read()
    try:
        try:
            con.execute("SET threads=6")
        except Exception:                   # noqa: BLE001 -- not fatal
            pass
        rep = issue(con, month, dry_run=True, progress=say, **kw)
    finally:
        con.close()

    pred, m0 = rep.pop("_pred"), rep.pop("_t0")
    say("opening the write handle (waits out a peer lock)…")
    w = connect_write()
    try:
        ensure_schema(w)
        n = _write_vintage(w, pred, month=rep["issued_month"],
                           version=rep["model_version"],
                           horizon=rep["horizon_months"], t0=m0)
        _write_run(w, month=rep["issued_month"], version=rep["model_version"],
                   horizon=rep["horizon_months"], radius_m=rep["radius_m"],
                   res=rep["fit"], support=rep["support"], n_rows=n,
                   anchors=rep["anchors"], supply_hash=rep["supply_hash"],
                   by_frame=rep.get("by_frame"))
    finally:
        w.close()
    rep["n_rows_issued"] = int(n)
    rep["dry_run"] = False
    return rep


def score_managed(issued_month: str | None = None, *, as_of: str | None = None,
                  version: str | None = None, radius_m: float = RADIUS_M,
                  progress=None) -> list[dict]:
    """`score`, same one-handle-at-a-time discipline as `issue_managed`.

    The spatial join that produces the realized counts runs on the READ handle;
    the outcome rows and the score statistics are then computed on the WRITE
    handle, which can read `analysis.forecast` perfectly well."""
    say = progress or (lambda *_: None)
    con = connect_read()
    try:
        targets = ([(issued_month, version, as_of)] if issued_month
                   else [(a, b, c) for a, b, c in due_for_scoring(con)])
        prepared = []
        for issued, ver, asof in targets:
            prepared.append(_score_prepare(con, issued, as_of=asof, version=ver,
                                           radius_m=radius_m, progress=say))
    finally:
        con.close()
    if not prepared:
        return []

    say("opening the write handle (waits out a peer lock)…")
    w = connect_write()
    out = []
    try:
        for prep in prepared:
            out.append(_score_commit(w, prep, progress=say))
    finally:
        w.close()
    return out


#: The feature block frozen onto every row. Compact on purpose: this is four
#: million rows per vintage, and a pretty-printed JSON would be a gigabyte of
#: whitespace. Keys: supply ratio, own-gap flag, homes, retail index, raw
#: supply count, the anchor median, and the freeze date.
#: `%(t0)s` and not `{t0}`: the JSON braces in this literal are not format
#: placeholders, and `str.format` cannot be told the difference.
_FEATURES_JSON_SQL = (
    """'{"sr":' || CAST(round(supply_ratio, 5) AS VARCHAR)"""
    """ || ',"g":' || CAST(CAST(own_gap_flag AS INTEGER) AS VARCHAR)"""
    """ || ',"h":' || CAST(round(homes, 1) AS VARCHAR)"""
    """ || ',"ri":' || CAST(round(retail_index, 5) AS VARCHAR)"""
    """ || ',"sup":' || CAST(CAST(supply AS INTEGER) AS VARCHAR)"""
    """ || ',"bm":' || CAST(round(base_median, 6) AS VARCHAR)"""
    """ || ',"t0":"%(t0)s"}'""")


def _features_json_sql(t0: dt.date) -> str:
    """THE single definition of the frozen-feature string. Nothing stores it
    any more (sql/045 dropped `analysis.forecast.features_json`, 526 MiB of a
    1,292 MiB table); it survives as the pre-image of `features_hash` and as
    the thing a reader reconstructs when they need the VALUES back."""
    return _FEATURES_JSON_SQL % {"t0": t0.isoformat()}


def _features_hash_sql(t0: dt.date, chars: int = FEATURES_HASH_CHARS) -> str:
    """`features_hash`: the first `chars` characters of lower(md5(the string
    above)), computed IN SQL over the same expression.

    HASHED IN SQL, NOT IN PANDAS, and that is load-bearing. The pre-image is
    built by DuckDB's own `round()` and `CAST(... AS VARCHAR)`; rebuilding it
    in Python would reproduce those two formatting rules by eye, and the first
    float that formatted differently would make two identical feature vectors
    hash differently -- a false "the inputs changed" on a table whose entire
    purpose is to answer that question truthfully.

    WHAT IT CAN AND CANNOT ANSWER. Two rows with the same hash saw the same
    seven-key feature block. Two rows with DIFFERENT hashes saw different
    blocks -- but the block includes `"t0"`, the freeze date, so two vintages
    of DIFFERENT issue months can never match even on identical features. The
    comparison it is built for is the one the ledger actually has: the five
    same-month 2026-09 re-issues, which share a t0.
    """
    return (f"substr(lower(md5({_features_json_sql(t0)})), 1, {int(chars)})")


#: The columns `_write_vintage` INSERTs, in the order its SELECT emits them.
#: Named, not positional: DuckDB binds an `INSERT ... SELECT` BY POSITION and
#: ignores the aliases entirely, so the pre-2026-09-16 form here would have
#: shifted every value one column left the first time sql/045 reordered the
#: table, silently, with `borough` landing in `frame`. This is audit §4b's
#: forecast.py:1261. The pair below is also what makes the sql/045 column drop
#: a compile error rather than a data corruption.
FORECAST_INSERT_COLUMNS: tuple[str, ...] = (
    "issued_month", "horizon_months", "model_version", "address_id",
    "category", "frame", "borough", "nta_code", "surprise_cell", "p_opening",
    "expected_openings", "support", "features_hash", "frozen_at")

#: Likewise for analysis.forecast_outcome. Its first four columns ARE the
#: forecast's natural key -- `forecast_id` is gone from both tables and the
#: join is on these, which is what it always restated.
FORECAST_OUTCOME_INSERT_COLUMNS: tuple[str, ...] = (
    "issued_month", "model_version", "address_id", "category", "scored_month",
    "horizon_elapsed", "realized_openings", "realized_flag", "scored_at")

#: The four columns that identify a forecast row, and the ONLY join key
#: between analysis.forecast and analysis.forecast_outcome.
FORECAST_KEY: tuple[str, ...] = ("issued_month", "model_version",
                                 "address_id", "category")


def _key_join(left: str, right: str, keys: tuple[str, ...] = FORECAST_KEY) -> str:
    """`a.k = b.k AND ...` over the natural key. One definition, so a join that
    forgets `model_version` -- which would fan a scored vintage out across
    every other version of the same month -- cannot be written by hand."""
    return " AND ".join(f"{left}.{k} = {right}.{k}" for k in keys)


def _write_vintage(con, pred: pd.DataFrame, *, month: str, version: str,
                   horizon: int, t0: dt.date) -> int:
    """DELETE + INSERT one vintage. NAMED COLUMNS on both statements.

    `frame` comes off the prediction block, not off a module constant: the
    block is the concatenation of one `_predict_frame` call per scored frame
    and each one stamped its own. A literal here would have relabelled every
    street row 'lot' the moment the street frame landed.
    """
    cols = ["point_id", "category", "frame", "borough", "nta_code",
            "surprise_cell", "p_opening", "support", "supply_ratio",
            "own_gap_flag", "homes", "retail_index", "supply", "base_median"]
    missing = [c for c in cols if c not in pred.columns]
    if missing:
        raise ValueError(f"prediction block is missing {missing}; "
                         "_predict_frame is the only thing that should build it")
    frame = pred[cols]
    # NO SILENT NULL INTO A NOT NULL COLUMN. The features_json pre-image is a
    # concatenation, and one NULL term in a `||` chain makes the WHOLE string
    # NULL, so a NULL retail_index would arrive as features_hash = NULL and be
    # rejected by the DDL with a message that names the wrong thing. Say it
    # here, where the cause is in scope.
    bad = {c: int(frame[c].isna().sum())
           for c in ("supply_ratio", "own_gap_flag", "homes", "retail_index",
                     "supply", "base_median", "p_opening", "support", "frame")
           if int(frame[c].isna().sum())}
    if bad:
        raise ValueError(
            f"refusing to write a vintage with NULLs in {bad} — every one of "
            "these feeds features_hash or a NOT NULL column, and a NULL here "
            "means a feature was never measured, not that it is zero")
    unknown_support = sorted(set(frame["support"].unique()) - set(SUPPORT_VALUES))
    if unknown_support:
        raise ValueError(f"support values {unknown_support} are outside "
                         f"{list(SUPPORT_VALUES)}, which the DDL CHECKs")

    con.register("_fc_pred", frame)
    con.execute("DELETE FROM analysis.forecast "
                "WHERE issued_month = ? AND model_version = ?", [month, version])
    con.execute(f"""
        INSERT INTO analysis.forecast ({', '.join(FORECAST_INSERT_COLUMNS)})
        -- THE NATURAL KEY, AND NOTHING RESTATING IT. Until sql/045 this table
        -- also carried `forecast_id` -- 'f-<YYYYMM>-<hash>-<address>-<cat>',
        -- 257 MiB across 25.4M rows -- which was a pure concatenation of the
        -- four columns below and of the PK they now form. Two earlier ideas
        -- are worth not re-having: a 10-character md5 of (address, category)
        -- is 40 bits over 4.2M rows, which the birthday bound puts at ~8
        -- expected collisions and which duly collided on the first vintage;
        -- and the readable concatenation that replaced it was correct but
        -- stored the key twice. A ledger's identity must be collision-free BY
        -- CONSTRUCTION, and the columns themselves are.
        SELECT '{month}'                                            AS issued_month,
               {int(horizon)}                                       AS horizon_months,
               '{version}'                                          AS model_version,
               point_id                                             AS address_id,
               category                                             AS category,
               frame                                                AS frame,
               borough                                              AS borough,
               nta_code                                             AS nta_code,
               surprise_cell                                        AS surprise_cell,
               p_opening                                            AS p_opening,
               p_opening                                            AS expected_openings,
               support                                              AS support,
               {_features_hash_sql(t0)}                             AS features_hash,
               now()                                                AS frozen_at
        FROM _fc_pred
    """)
    n = con.execute("SELECT count(*) FROM analysis.forecast "
                    "WHERE issued_month = ? AND model_version = ?",
                    [month, version]).fetchone()[0]
    con.unregister("_fc_pred")
    return int(n)


def _write_run(con, *, month: str, version: str, horizon: int, radius_m: float,
               res: dict, support: dict, n_rows: int, anchors: dict,
               supply_hash: str | None = None,
               by_frame: dict | None = None) -> None:
    con.execute("DELETE FROM analysis.forecast_run "
                "WHERE issued_month = ? AND model_version = ?", [month, version])
    # `scored_frames` / `fit_frame` ride inside support_json rather than in new
    # columns: the run table already carries every other "what was this fit"
    # fact as JSON, and one vintage-level dict is not worth a migration. It is
    # the only place the fit/score asymmetry is written down per vintage --
    # `analysis.forecast.frame` says which frame a ROW is, and nothing else
    # would say that the street rows were scored by a lot-fitted model.
    support_json = json.dumps({
        "dated_openings_in_fit_window": support,
        "anchor_base_median_at_issue": anchors,
        "fitted_categories": res["fitted_categories"],
        "support_floor": SUPPORT_FLOOR,
        "fit_frame": FIT_FRAME,
        "scored_frames": sorted(by_frame) if by_frame else [FIT_FRAME],
        "rows_by_frame": by_frame or {},
        "by_category_oos": res["by_category"]}, sort_keys=True, default=str)
    # EXPLICIT COLUMN LIST, not positional VALUES (?,?,...): `supply_hash`
    # (sql/030) was ADDed after this table's original CREATE, so it is the
    # LAST physical column, and a caller on a warehouse from before the
    # migration landed would otherwise have to remember to grow its
    # placeholder count by one. Naming the columns makes that impossible to
    # get wrong silently.
    con.execute("""
        INSERT INTO analysis.forecast_run
        (issued_month, model_version, horizon_months, radius_m, fit_t0s,
         fit_window_rule, feature_list, n_fit_rows, n_fit_addresses,
         n_fit_ntas, fit_positive_rate, auc_blocked, auc_no_score,
         auc_persistence, auc_homes_only, brier_fit, calibration_json,
         coefficients_json, support_json, ships, ships_reason, n_rows_issued,
         issued_at, supply_hash)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [month, version, horizon, radius_m,
          json.dumps([str(d) for d in fit_t0s(month, horizon)]),
          FIT_WINDOW_RULE, json.dumps(list(FEATURE_LIST)),
          res["n_rows"], res["n_addresses"], res["n_ntas"],
          res["positive_rate"], res["auc_blocked"], res["auc_no_score"],
          res["auc_persistence"], res["auc_homes_only"], res["brier"],
          json.dumps(res["calibration"]),
          json.dumps(res["coefficients"], default=str),
          support_json, res["ships"], res["ships_reason"], n_rows,
          dt.datetime.now(), supply_hash])


# ---------------------------------------------------------------------------
# 5. score
# ---------------------------------------------------------------------------
def _score_prepare(con, issued_month: str, *, as_of: str | None = None,
                   version: str | None = None, radius_m: float = RADIUS_M,
                   progress=None) -> dict:
    """The READ half of scoring: resolve the vintage, the window, and the
    realized counts. Touches nothing.

    THE WINDOW, and its boundaries are pinned by test:
        realized = a same-category dated first-seen in
        [first day of issued_month, first day of issued_month + elapsed months)
        within `radius_m` STRAIGHT-LINE.

    `--as-of` sets the right edge. Scoring 2023-01 as of 2024-01 is the twelve-
    month score; as of 2025-01 is the twenty-four-month score, which is a
    DIFFERENT ROW on the same forecasts, not a correction of the first. The
    horizon the forecast was issued for is 12; a 24-month score is reported for
    what it is — the same probability judged against a longer window, which it
    will look better on for a trivial reason and which is labelled accordingly.
    """
    require_schema(con)
    validate_month(issued_month)
    say = progress or (lambda *_: None)

    vers = [r[0] for r in con.execute(
        "SELECT DISTINCT model_version FROM analysis.forecast "
        "WHERE issued_month = ? ORDER BY 1", [issued_month]).fetchall()]
    if version:
        vers = [v for v in vers if v == version]
    if not vers:
        raise RuntimeError(f"no forecast vintage for {issued_month}"
                           + (f" / {version}" if version else ""))

    m0 = month_first(issued_month)
    horizon = int(con.execute(
        "SELECT max(horizon_months) FROM analysis.forecast WHERE issued_month = ?",
        [issued_month]).fetchone()[0])
    scored_month = as_of or month_str(add_months(m0, horizon))
    validate_month(scored_month)
    end = month_first(scored_month)
    elapsed = (end.year * 12 + end.month) - (m0.year * 12 + m0.month)
    if elapsed <= 0:
        raise ValueError(f"--as-of {scored_month} is not after the issue month "
                         f"{issued_month}; there is no window to score")

    prep = {"issued_month": issued_month, "scored_month": scored_month,
            "horizon_elapsed": elapsed, "horizon_months": horizon,
            "radius_m": radius_m, "realized": {}}

    for ver in vers:
        say(f"scoring {issued_month} / {ver} as of {scored_month} "
            f"({elapsed} months elapsed)")
        # The realized counts are computed in pandas (the spatial join lives
        # there) but the 4.2-million-row JOIN TO THE VINTAGE is done in DuckDB.
        # Pulling the whole vintage into a frame would be four million rows of
        # key columns for something that is only ever used as a join key.
        pts = con.execute(f"""
            SELECT DISTINCT a.address_id AS point_id, a.lon, a.lat
            FROM analysis.address a
            JOIN analysis.forecast f ON f.address_id = a.address_id
            WHERE f.issued_month = '{issued_month}' AND f.model_version = '{ver}'
        """).fetchdf()
        realized = openings_between(con, pts, m0, end, radius_m=radius_m)
        prep["realized"][ver] = realized.rename(
            columns={"point_id": "address_id", "n": "realized_openings"})
        say(f"  {len(prep['realized'][ver]):,} address x category discs saw at "
            f"least one same-category opening in the window")
    return prep


def _score_commit(con, prep: dict, *, dry_run: bool = False,
                  progress=None) -> dict:
    """Write the outcome rows and compute the score. See `_score_prepare`."""
    say = progress or (lambda *_: None)
    out = {k: prep[k] for k in ("issued_month", "scored_month",
                                "horizon_elapsed", "horizon_months")}
    out["versions"] = {}
    for ver, realized in prep["realized"].items():
        if not dry_run:
            say(f"  writing outcomes for {prep['issued_month']} / {ver}")
            _write_outcomes(con, realized, issued_month=prep["issued_month"],
                            version=ver, scored_month=prep["scored_month"],
                            elapsed=prep["horizon_elapsed"])
        out["versions"][ver] = _score_stats(
            _scored_frame(con, realized, issued_month=prep["issued_month"],
                          version=ver),
            elapsed=prep["horizon_elapsed"])
    return out


def score(con, issued_month: str, *, as_of: str | None = None,
          version: str | None = None, radius_m: float = RADIUS_M,
          dry_run: bool = False, progress=None, write_con=None) -> dict:
    """Prepare and commit on ONE handle. `score_managed` is the two-handle form.

    Kept as a single function because the tests and any caller that already
    holds a writable connection want the whole thing in one call."""
    prep = _score_prepare(con, issued_month, as_of=as_of, version=version,
                          radius_m=radius_m, progress=progress)
    return _score_commit(write_con if write_con is not None else con, prep,
                         dry_run=dry_run, progress=progress)


def _scored_frame(con, realized: pd.DataFrame, *, issued_month: str,
                  version: str) -> pd.DataFrame:
    """(category, support, p_opening, realized_flag) for every row of a vintage.

    Small dtypes only — none of the four key columns come back. AUC and Brier
    need the full (p, y) vectors and nothing else, and at 4.2M rows the
    difference between carrying the keys and not is a gigabyte."""
    con.register("_fc_real", realized[["address_id", "category",
                                       "realized_openings"]])
    df = con.execute("""
        SELECT f.category, f.support, f.p_opening,
               COALESCE(r.realized_openings, 0)      AS realized_openings,
               COALESCE(r.realized_openings, 0) > 0  AS realized_flag
        FROM analysis.forecast f
        LEFT JOIN _fc_real r
               ON r.address_id = f.address_id AND r.category = f.category
        WHERE f.issued_month = ? AND f.model_version = ?
    """, [issued_month, version]).fetchdf()
    con.unregister("_fc_real")
    return df


def _write_outcomes(con, realized: pd.DataFrame, *, issued_month: str,
                    version: str, scored_month: str, elapsed: int) -> None:
    """DELETE + INSERT for this (vintage, model, scoring date).

    ZERO IS A REAL OBSERVATION: the LEFT JOIN writes a row for every forecast in
    the vintage, not only the ones that saw an opening. A scoring pass that
    stored only the hits would produce a calibration curve with no denominator.

    THE DELETE IS NOW A PREDICATE, NOT A SUBQUERY. It used to read
    `forecast_id IN (SELECT forecast_id FROM analysis.forecast WHERE ...)` — a
    scan of the 25M-row table to rediscover an (issued_month, model_version)
    that this function was handed as an argument. Those two columns are on
    `forecast_outcome` itself now, so the delete names them directly.

    `con` must be WRITABLE, and it reads `analysis.forecast` itself — a
    writable handle can read, and DuckDB will not give one process a second
    connection to the same file with a different configuration anyway."""
    ensure_schema(con)
    con.register("_fc_real", realized[["address_id", "category",
                                       "realized_openings"]])
    con.execute("""
        DELETE FROM analysis.forecast_outcome
        WHERE scored_month = ? AND issued_month = ? AND model_version = ?
    """, [scored_month, issued_month, version])
    con.execute(f"""
        INSERT INTO analysis.forecast_outcome
               ({', '.join(FORECAST_OUTCOME_INSERT_COLUMNS)})
        SELECT f.issued_month                        AS issued_month,
               f.model_version                       AS model_version,
               f.address_id                          AS address_id,
               f.category                            AS category,
               '{scored_month}'                      AS scored_month,
               {int(elapsed)}                        AS horizon_elapsed,
               COALESCE(r.realized_openings, 0)      AS realized_openings,
               COALESCE(r.realized_openings, 0) > 0  AS realized_flag,
               now()                                 AS scored_at
        FROM analysis.forecast f
        LEFT JOIN _fc_real r
               ON r.address_id = f.address_id AND r.category = f.category
        WHERE f.issued_month = ? AND f.model_version = ?
    """, [issued_month, version])
    con.unregister("_fc_real")


def _score_stats(rows: pd.DataFrame, *, elapsed: int) -> dict:
    from loci.validation.retrodiction import _auc

    y = rows["realized_flag"].to_numpy(dtype=float)
    p = rows["p_opening"].to_numpy(dtype=float)
    cal = calibration(y, p)
    per_cat = {}
    for cat, g in rows.groupby("category"):
        yy = g["realized_flag"].to_numpy(dtype=float)
        pp = g["p_opening"].to_numpy(dtype=float)
        c = calibration(yy, pp)
        per_cat[cat] = {
            "n": int(len(g)), "realized_rate": float(yy.mean()),
            "mean_p": float(pp.mean()),
            "auc": float(_auc(yy, pp)) if len(set(yy)) > 1 else float("nan"),
            "brier": _brier(yy, pp), "log_loss": _log_loss(yy, pp),
            "calibration_max_gap": calibration_max_gap(c),
            "support": str(g["support"].iloc[0])}
    return {
        "n": int(len(rows)), "horizon_elapsed": elapsed,
        "realized_rate": float(y.mean()), "mean_p": float(p.mean()),
        "auc": float(_auc(y, p)) if len(set(y)) > 1 else float("nan"),
        "brier": _brier(y, p), "log_loss": _log_loss(y, p),
        "calibration": cal, "calibration_max_gap": calibration_max_gap(cal),
        "by_category": per_cat,
    }


# ---------------------------------------------------------------------------
# 6. report
# ---------------------------------------------------------------------------
def track_record(con) -> list[dict]:
    """One row per (vintage, model, scoring date). The whole record, failures
    included."""
    require_schema(con)
    return con.execute("""
        SELECT f.issued_month, f.model_version, o.scored_month,
               o.horizon_elapsed, count(*) AS n,
               avg(CASE WHEN o.realized_flag THEN 1.0 ELSE 0.0 END) AS realized_rate,
               avg(f.p_opening)                                     AS mean_p
        FROM analysis.forecast f
        JOIN analysis.forecast_outcome o
          ON o.issued_month  = f.issued_month
         AND o.model_version = f.model_version
         AND o.address_id    = f.address_id
         AND o.category      = f.category
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3
    """).fetchdf().to_dict("records")


def vintage_scores(con, issued_month: str, scored_month: str,
                   version: str | None = None) -> dict:
    """Recompute AUC / Brier / calibration from the LEDGER, not from a cached
    JSON, so the printed track record is always a read of the stored rows."""
    require_schema(con)
    sql = """
        SELECT f.model_version, f.category, f.support, f.p_opening,
               o.realized_flag, o.horizon_elapsed
        FROM analysis.forecast f
        JOIN analysis.forecast_outcome o
          ON o.issued_month  = f.issued_month
         AND o.model_version = f.model_version
         AND o.address_id    = f.address_id
         AND o.category      = f.category
        WHERE f.issued_month = ? AND o.scored_month = ?
    """
    args = [issued_month, scored_month]
    if version:
        sql += " AND f.model_version = ?"
        args.append(version)
    df = con.execute(sql, args).fetchdf()
    if df.empty:
        return {}
    out = {}
    for ver, g in df.groupby("model_version"):
        g = g.rename(columns={"realized_flag": "realized_flag"})
        g = g.assign(realized_openings=g["realized_flag"].astype(int))
        out[ver] = _score_stats(g, elapsed=int(g["horizon_elapsed"].iloc[0]))
    return out


def surprise_nta(con, issued_month: str, scored_month: str, *,
                 category: str = "(all)", version: str | None = None,
                 limit: int = 10, min_addresses: int = 200) -> pd.DataFrame:
    """Top and bottom NTAs by the cluster-robust surprise z.

    `min_addresses` exists because a residual sum over forty doorways is not a
    neighbourhood-level statement about anything."""
    require_schema(con)
    sql = """
        SELECT * FROM analysis.forecast_surprise_nta
        WHERE issued_month = ? AND scored_month = ? AND category = ?
          AND n_addresses >= ? AND z_clustered IS NOT NULL
    """
    args = [issued_month, scored_month, category, int(min_addresses)]
    if version:
        sql += " AND model_version = ?"
        args.append(version)
    df = con.execute(sql, args).fetchdf()
    if df.empty:
        return df
    df = df.sort_values("z_clustered", ascending=False)
    return pd.concat([df.head(limit), df.tail(limit)]).drop_duplicates()


def p_distribution(con, issued_month: str, version: str | None = None) -> pd.DataFrame:
    """p_opening quantiles per category for one vintage — what the modelled
    layer actually SAYS, before anything is known about whether it was right."""
    require_schema(con)
    sql = """
        SELECT category, support, count(*) AS n,
               quantile_cont(p_opening, 0.10) AS p10,
               quantile_cont(p_opening, 0.50) AS p50,
               quantile_cont(p_opening, 0.90) AS p90,
               max(p_opening)                 AS pmax
        FROM analysis.forecast
        WHERE issued_month = ?
    """
    args = [issued_month]
    if version:
        sql += " AND model_version = ?"
        args.append(version)
    sql += " GROUP BY 1, 2 ORDER BY p50 DESC"
    return con.execute(sql, args).fetchdf()


def runs(con) -> pd.DataFrame:
    require_schema(con)
    return con.execute("""
        SELECT issued_month, model_version, horizon_months, n_fit_rows, n_fit_ntas,
               fit_positive_rate, auc_blocked, auc_no_score, auc_persistence,
               auc_homes_only, brier_fit, ships, ships_reason, n_rows_issued,
               calibration_json, issued_at
        FROM analysis.forecast_run ORDER BY issued_month, model_version
    """).fetchdf()


def due_for_scoring(con, today: dt.date | None = None) -> list[tuple[str, str, str]]:
    """(issued_month, model_version, as_of) for every vintage whose horizon has
    elapsed and which has no outcome row at that horizon yet.

    This is what the monthly job calls. A vintage is scored WHEN ITS HORIZON
    ELAPSES, not when someone remembers."""
    require_schema(con)
    today = today or dt.date.today()
    # The subquery used to re-join analysis.forecast to recover the vintage a
    # forecast_id belonged to. `forecast_outcome` carries issued_month and
    # model_version itself now, so the 25M-row table is out of this plan
    # entirely — same answer, one scan instead of two.
    rows = con.execute("""
        SELECT f.issued_month, f.model_version, max(f.horizon_months) AS h,
               (SELECT count(*) FROM analysis.forecast_outcome o
                WHERE o.issued_month  = f.issued_month
                  AND o.model_version = f.model_version
                  AND o.horizon_elapsed >= max(f.horizon_months)) AS scored
        FROM analysis.forecast f
        GROUP BY 1, 2
    """).fetchall()
    due = []
    for issued, ver, h, scored in rows:
        target = add_months(month_first(issued), int(h))
        if target <= today.replace(day=1) and not scored:
            due.append((issued, ver, month_str(target)))
    return due


# ---------------------------------------------------------------------------
# 7. retention (GTM-163) — nothing bounded analysis.forecast's growth until
# this. One issue+score cycle added ~1.4 GB (DB 1.8 -> 4.6 GB, D92) and every
# `make chains-refresh` writes another vintage of ~4.2M rows.
# ---------------------------------------------------------------------------

#: Newest vintages PER MODEL VERSION whose prediction rows survive a prune.
#: Per version, not globally, because two versions coexisting is the whole
#: point of the vintage discipline (see the module docstring) and a global
#: cutoff would let a newer version's vintages silently crowd the older
#: version's out of the retained set.
DEFAULT_KEEP_VINTAGES = 3


def prunable_vintages(con, *, keep_vintages: int = DEFAULT_KEEP_VINTAGES,
                      today: dt.date | None = None) -> pd.DataFrame:
    """Every (issued_month, model_version) in analysis.forecast, with the
    columns `prune` needs to decide what to drop.

    `horizon_open` -- issued_month + horizon_months is still in the future --
    is the literal GTM-163 protection: a vintage whose horizon has not
    elapsed CANNOT have been scored yet, so its prediction rows must survive
    regardless of rank. `has_outcome` is a second, stricter guard beyond what
    the ticket's date test alone would catch: a vintage whose horizon HAS
    elapsed but was never actually scored (a failed `forecast score` run, a
    manual `prune` invoked out of the normal `make chains-refresh` order)
    is protected too -- the contract is "never touching a vintage until it
    is scored," and the date is the common-case proxy for that, not a
    substitute for checking when scoring might have lagged.

    `keep` is true (never pruned) when the vintage ranks among the newest
    `keep_vintages` for its model_version, OR its horizon is still open, OR
    it has not been scored at all."""
    require_schema(con)
    today = today or dt.date.today()
    # A DOUBLE-COUNT FIXED ON THE WAY PAST, and it was live. This used to
    # aggregate over `analysis.forecast LEFT JOIN analysis.forecast_outcome`,
    # so `count(*) AS n_rows` counted (forecast row x scored_month) pairs, not
    # forecast rows. `forecast_outcome`'s key is (vintage, address, category,
    # scored_month): the moment a vintage is scored at BOTH its 12-month and a
    # 24-month as-of — which `--as-of` exists to do, and which sql/028 calls a
    # different row rather than a correction — `n_rows` doubled and `prune`
    # reported twice the rows it was about to delete. It never deleted the
    # wrong rows (the DELETE is by vintage), but the number a human reads
    # before authorising a prune was wrong, and it would have gone on being
    # wrong silently. The vintage size is a property of `forecast` alone, so
    # it is counted there alone; whether anything scored it is an EXISTS.
    df = con.execute("""
        SELECT f.issued_month,
               f.model_version,
               max(f.horizon_months)               AS horizon_months,
               count(*)                            AS n_rows,
               EXISTS (SELECT 1 FROM analysis.forecast_outcome o
                        WHERE o.issued_month  = f.issued_month
                          AND o.model_version = f.model_version)
                                                   AS has_outcome
        FROM analysis.forecast f
        GROUP BY 1, 2
    """).fetchdf()
    cols = ["issued_month", "model_version", "horizon_months", "n_rows",
            "has_outcome", "horizon_open", "within_keep", "keep"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    df["horizon_open"] = [
        add_months(month_first(m), int(h)) > today
        for m, h in zip(df["issued_month"], df["horizon_months"])]
    # rank 0 = newest issued_month, WITHIN each model_version. Computed on a
    # sort_values copy and assigned back by index -- pandas aligns on the
    # index automatically, so the row order of `df` itself never has to
    # match the sort.
    rank = (df.sort_values("issued_month", ascending=False)
              .groupby("model_version").cumcount())
    df["within_keep"] = rank < int(keep_vintages)
    df["keep"] = df["within_keep"] | df["horizon_open"] | df["has_outcome"].eq(False)
    return df[cols].sort_values(["model_version", "issued_month"]).reset_index(drop=True)


def _estimate_forecast_row_bytes(con, sample: int = 5000) -> float:
    """A rough per-row byte estimate for analysis.forecast, from a sample of
    the variable-width columns plus a fixed allowance for the rest.

    DuckDB does not expose an exact per-row disk footprint over SQL, and
    getting one exactly right is not the point: `prune` prints this so a
    human can judge whether running it is worth the 45-minute write-lock
    wait, not so a script can budget disk to the byte.

    IT MEASURES WHAT THE TABLE HAS. Until sql/045 this summed `forecast_id`
    (257 MiB live) and `features_json` (526 MiB live), which together were
    61% of the number it reported and are now not columns at all. A self-report
    that keeps measuring dropped columns does not merely go stale — on DuckDB
    it raises `Binder Error: Referenced column ... not found`, which is the
    better of the two failure modes and still not one to ship. The list below
    is derived from FORECAST_INSERT_COLUMNS so the two cannot drift again.
    """
    varchar_cols = ("issued_month", "model_version", "address_id", "category",
                    "frame", "borough", "nta_code", "surprise_cell", "support",
                    "features_hash")
    assert set(varchar_cols) <= set(FORECAST_INSERT_COLUMNS), varchar_cols
    # borough / nta_code / surprise_cell are the nullable three; the rest are
    # NOT NULL in sql/045, and `coalesce` on them would only hide a violation.
    nullable = {"borough", "nta_code", "surprise_cell"}
    terms = " + ".join(
        f"coalesce(length({c}), 0)" if c in nullable else f"length({c})"
        for c in varchar_cols)
    row = con.execute(f"""
        SELECT avg({terms}) AS avg_varchar_len
        FROM (SELECT {', '.join(varchar_cols)}
              FROM analysis.forecast USING SAMPLE {int(sample)} ROWS)
    """).fetchone()
    avg_varchar = float(row[0]) if row and row[0] is not None else 120.0
    # + ~36 bytes: two DOUBLEs, an INTEGER, a TIMESTAMP, and DuckDB's per-string
    # length prefix on the ten VARCHAR columns already summed above.
    return avg_varchar + 36.0


def prune(con, *, keep_vintages: int = DEFAULT_KEEP_VINTAGES,
         dry_run: bool = True, today: dt.date | None = None,
         progress=None) -> dict:
    """Delete analysis.forecast PREDICTION rows for vintages older than the
    newest `keep_vintages` per model_version (GTM-163).

    NEVER touches analysis.forecast_run (the fit diagnostics) or
    analysis.forecast_outcome (the scored track record) — only DELETE
    statements against analysis.forecast appear below. NEVER a vintage whose
    horizon has not elapsed, or that has not been scored yet, however old its
    rank — see `prunable_vintages`.

    DRY RUN BY DEFAULT. This deletes rows from the ledger's largest table on
    a schedule (`make chains-refresh`); `dry_run=True` computes and prints
    the candidate set and deletes nothing, which is also what makes this
    function safe to call on a READ-ONLY connection. `dry_run=False` deletes,
    then runs CHECKPOINT and (best-effort) VACUUM — see the return dict and
    the CLI command's docstring for what those actually do to the .duckdb
    FILE, which is less than their names suggest.
    """
    say = progress or (lambda *_: None)
    cands = prunable_vintages(con, keep_vintages=keep_vintages, today=today)
    drop = cands[~cands["keep"]]
    kept_open = cands[(~cands["within_keep"])
                      & (cands["horizon_open"] | ~cands["has_outcome"])]

    n_rows = int(drop["n_rows"].sum()) if len(drop) else 0
    est_bytes = (_estimate_forecast_row_bytes(con) * n_rows) if n_rows else 0.0

    out = {
        "keep_vintages": int(keep_vintages),
        "candidates": drop[["issued_month", "model_version", "n_rows"]].to_dict("records"),
        "kept_open_horizon": kept_open[["issued_month", "model_version",
                                        "n_rows"]].to_dict("records"),
        "n_rows": n_rows,
        "estimated_bytes_freed": int(est_bytes),
        "dry_run": bool(dry_run),
        "checkpointed": False,
        "vacuumed": False,
    }
    if n_rows == 0:
        say("nothing to prune")
        return out
    if dry_run:
        say(f"[dry run] would delete {n_rows:,} rows across {len(drop)} "
            f"vintage(s), ~{est_bytes / 1e6:.1f} MB estimated — nothing deleted")
        return out

    for _, r in drop.iterrows():
        con.execute("DELETE FROM analysis.forecast "
                    "WHERE issued_month = ? AND model_version = ?",
                    [r["issued_month"], r["model_version"]])
        say(f"  deleted {r['issued_month']} / {r['model_version']} "
            f"({int(r['n_rows']):,} rows)")

    # CHECKPOINT flushes the WAL into the main file and updates DuckDB's
    # internal free-block bookkeeping so future INSERTs can reuse the space
    # this DELETE just freed. VACUUM (best-effort — some DuckDB builds refuse
    # it inside a larger transaction) recomputes table statistics. NEITHER
    # SHRINKS THE .duckdb FILE ON DISK: verified empirically against this
    # DuckDB build (delete 90% of a table, CHECKPOINT, VACUUM, CHECKPOINT
    # again — file size unchanged throughout). The freed blocks are reused
    # internally, not returned to the OS; actually shrinking the file needs a
    # full rebuild (`EXPORT DATABASE` to a fresh file, or `ATTACH` a new file
    # and `COPY FROM DATABASE current`). This function does not do that
    # automatically — it is an offline, whole-database operation orders of
    # magnitude slower than a prune, and is out of scope here.
    con.execute("CHECKPOINT")
    out["checkpointed"] = True
    try:
        con.execute("VACUUM")
        out["vacuumed"] = True
    except Exception:                   # noqa: BLE001 -- best-effort only
        pass
    return out
