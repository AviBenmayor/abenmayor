"""The challenger: `src/loci/model/forecast_challenge.py`, one test per item
in the design memo's build checklist (§8). No network, no live warehouse --
items 1, 7 and 8 build a synthetic DuckDB row by row (or a temp on-disk file,
for items 7/8, to exercise a literal `read_only=True` handle); items 2-6 need
no database at all, since `fold_index`, `intersection_auc`, `evaluate_verdict`
and the reused `retrodiction.bootstrap_delta` / `residual_morans_i` are pure
functions of arrays and frames.

Every item's acceptance test, verbatim from the memo:

  1. augment() -- a ledger row dated >= the issue month changes none of the
     new t0-true features.
  2. blocked_oos_predictions_gbm's fold assignment is the SAME `_nta_folds`
     partition the logit's own OOF routine uses -- pinned on the array, not
     on a downstream AUC.
  3. the intersection mask -- a NaN in one model's OOF drops that row from
     BOTH AUC computations, counts matching.
  4. the verdict -- six synthetic dicts, each failing exactly one criterion.
  5. the paired bootstrap on identical predictions: CI contains 0, mean ~ 0,
     seed-reproducible.
  6. residual Moran's I: a spatially shuffled residual ~ 0, the real one > 0.3.
  7. the CLI's orchestrator never writes to analysis.forecast* and the JSON
     carries the declared key set.
  8. the JSON carries all three rungs and both anachronistic arms; rung 1
     reproduces fit()['auc_blocked'] to 1e-9.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from loci.model import supply_asof
from loci import db as locidb
from loci.model import forecast as fc
from loci.model import forecast_challenge as fchal
from loci.validation import retrodiction as rd

#: Same fixture location as tests/test_forecast.py -- Gowanus-ish, 0.001 deg
#: of longitude is ~84 m at this latitude.
LON, LAT = -73.990, 40.675


# ===========================================================================
# a minimal warehouse -- the five tables `augment()` and `build_fit_panel`
# read, `analysis.address` carrying the two anachronistic columns
# ===========================================================================
def _create_schema(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    # The open/closed predicate's as-of date is pinned in analysis.supply_asof
    # (owner ruling 2026-09-16): every SQL rendering of
    # model/poi_presence.poi_is_open binds that table by name, so a scratch
    # warehouse needs it exactly as db.init_schema creates it.
    supply_asof.ensure_table(con)
    con.execute("""CREATE TABLE analysis.address (
        address_id VARCHAR, lon DOUBLE, lat DOUBLE, nta_code VARCHAR,
        borough VARCHAR, frame VARCHAR, units_capped DOUBLE,
        jobs_400m DOUBLE, transit_entries_400m DOUBLE)""")
    con.execute("""CREATE TABLE analysis.address_character (
        address_id VARCHAR, retail_index DOUBLE)""")
    con.execute("""CREATE TABLE analysis.poi_presence (
        location_key VARCHAR, category VARCHAR, display_name VARCHAR,
        lon DOUBLE, lat DOUBLE, borough VARCHAR,
        first_seen_kind VARCHAR, first_seen_src_field VARCHAR,
        first_seen_src_date DATE, poi_id_latest VARCHAR)""")
    con.execute("CREATE TABLE analysis.poi_supply (poi_id VARCHAR, in_principled BOOLEAN)")


def add_address(con, aid, lon, lat, *, nta="BK0101", units=100.0, ri=0.4,
                frame="lot", borough="BK", jobs=0.0, transit=0.0):
    con.execute("INSERT INTO analysis.address VALUES (?,?,?,?,?,?,?,?,?)",
                [aid, lon, lat, nta, borough, frame, units, jobs, transit])
    con.execute("INSERT INTO analysis.address_character VALUES (?,?)", [aid, ri])


def add_poi(con, key, cat, lon, lat, kind, date, *, principled=True,
            borough="BK"):
    con.execute("INSERT INTO analysis.poi_presence VALUES (?,?,?,?,?,?,?,?,?,?)",
                [key, cat, key, lon, lat, borough, kind, "opened_on", date,
                 f"poi:{key}"])
    con.execute("INSERT INTO analysis.poi_supply VALUES (?,?)",
                [f"poi:{key}", principled])


@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    _create_schema(c)
    return c


# ===========================================================================
# 1. augment() -- the leakage check (checklist item 1)
# ===========================================================================
def test_augment_ignores_a_competitor_dated_on_or_after_the_issue_month(con):
    """A competitor dated on-or-after the ISSUE MONTH is dated on-or-after
    BOTH fold t0s (2023-01 and 2024-01 for a 2025-01 vintage) -- so it must
    change none of `log_supply_other`, `log_openings_prev_own` or
    `log_openings_prev_other`. The same assertion `tests/test_forecast.py`
    already makes for `log_score`, made here for the three NEW features."""
    for i in range(4):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    add_poi(con, "old_cafe", "cafe", LON + 0.0005, LAT, "source_date",
            dt.date(2020, 1, 1))
    add_poi(con, "old_rest", "restaurant", LON + 0.0006, LAT, "source_date",
            dt.date(2022, 6, 1))
    cats = ("restaurant", "cafe")

    points = fc.load_points(con, limit=4)
    cols = ["point_id", "category", "fold_t0", "log_supply_other",
            "log_openings_prev_own", "log_openings_prev_other"]

    panel1, _ = fc.build_fit_panel(con, "2025-01", categories=cats, sample_n=4,
                                   anchor=points, points=points)
    before = (fchal.augment(con, panel1, points, categories=cats)[cols]
             .sort_values(["point_id", "category", "fold_t0"])
             .reset_index(drop=True))

    add_poi(con, "future_cafe", "cafe", LON + 0.0007, LAT, "source_date",
            dt.date(2025, 1, 1))
    add_poi(con, "future_rest", "restaurant", LON + 0.0008, LAT, "source_date",
            dt.date(2026, 3, 1))
    panel2, _ = fc.build_fit_panel(con, "2025-01", categories=cats, sample_n=4,
                                   anchor=points, points=points)
    after = (fchal.augment(con, panel2, points, categories=cats)[cols]
            .sort_values(["point_id", "category", "fold_t0"])
            .reset_index(drop=True))

    pd.testing.assert_frame_equal(before, after)
    # sanity: the fixture is not vacuously equal because nothing was ever
    # counted -- log_supply_other is nonzero somewhere (the old cafe/restaurant
    # cross-category supply), so the leakage check has something to leak.
    assert (before["log_supply_other"] > 0).any()


# ===========================================================================
# 2. blocked_oos_predictions_gbm's fold assignment (checklist item 2)
# ===========================================================================
def test_fold_index_matches_the_nta_folds_the_logits_oof_routine_uses():
    """`fold_index` must assign each row to the same fold `forecast._nta_folds`
    itself would -- checked against the array directly, not a downstream AUC.

    `_nta_folds` shuffles `panel["nta_code"].unique()`, and pandas `.unique()`
    is ORDER-OF-APPEARANCE, not sorted (unlike `retrodiction.nta_fold_map`,
    which sorts first for exactly this reason -- its own docstring says so).
    So the fold partition is a function of ROW ORDER, not just the NTA set: a
    differently-ordered frame with the identical NTAs can land in different
    folds. `fold_index` must reproduce `_nta_folds`'s actual (order-sensitive)
    behaviour on the SAME frame, which is the only guarantee
    `blocked_oos_predictions_gbm` needs -- see the row-order-preservation test
    below, which is what actually keeps rung 1 and rungs 2/3 comparable."""
    panel = pd.DataFrame({"nta_code": [f"N{i % 5}" for i in range(60)]})
    got = fchal.fold_index(panel, n_folds=4, seed=fc.RNG_SEED)

    ref = np.full(len(panel), -1, dtype=int)
    nta = panel["nta_code"]
    for i, fold in enumerate(fc._nta_folds(panel.reset_index(drop=True),
                                           n_folds=4, seed=fc.RNG_SEED)):
        ref[nta.isin(fold).to_numpy()] = i
    np.testing.assert_array_equal(got, ref)
    assert (got >= 0).all(), "every row must land in some fold"

    # a DIFFERENT row order is a DIFFERENT (still internally consistent)
    # partition -- `fold_index` must track `_nta_folds` either way, not
    # silently apply the original order's assignment to reordered rows.
    shuffled = panel.sample(frac=1.0, random_state=7).reset_index(drop=True)
    got_shuf = fchal.fold_index(shuffled, n_folds=4, seed=fc.RNG_SEED)
    ref_shuf = np.full(len(shuffled), -1, dtype=int)
    nta_shuf = shuffled["nta_code"]
    for i, fold in enumerate(fc._nta_folds(shuffled, n_folds=4, seed=fc.RNG_SEED)):
        ref_shuf[nta_shuf.isin(fold).to_numpy()] = i
    np.testing.assert_array_equal(got_shuf, ref_shuf)


def test_augment_preserves_row_order_so_rung1_and_rungs23_share_one_fold_map(con):
    """The apples-to-apples rule (memo §2) rests on rung 1's panel (`p`, pre-
    `augment()`) and rungs 2/3's panel (`p_aug`, post-`augment()`) producing
    the IDENTICAL `_nta_folds` partition -- which, given the order-sensitivity
    just pinned above, requires `augment()` to preserve `p`'s row order
    exactly. `augment()` groups by `fold_t0` with `sort=False`
    (order-of-first-appearance) over a panel `build_fit_panel` already emits
    fold-major (fold 1's rows, then fold 2's), so the regrouping is a no-op on
    order -- asserted here rather than trusted."""
    for i in range(6):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 3}")
    add_poi(con, "r1", "restaurant", LON + 0.0005, LAT, "source_date",
            dt.date(2022, 6, 1))
    add_poi(con, "r2", "restaurant", LON + 0.0125, LAT, "source_date",
            dt.date(2023, 6, 1))

    points = fc.load_points(con, limit=6)
    panel, _ = fc.build_fit_panel(con, "2025-01", categories=("restaurant",),
                                  sample_n=6, anchor=points, points=points)
    p = panel.dropna(subset=["log_score", "y"]).reset_index(drop=True)
    p_aug = fchal.augment(con, p, points, categories=("restaurant",))

    pd.testing.assert_series_equal(
        p["point_id"].reset_index(drop=True),
        p_aug["point_id"].reset_index(drop=True),
        check_names=False)
    pd.testing.assert_series_equal(
        p["nta_code"].reset_index(drop=True),
        p_aug["nta_code"].reset_index(drop=True),
        check_names=False)

    folds_p = fchal.fold_index(p, seed=fc.RNG_SEED)
    folds_p_aug = fchal.fold_index(p_aug, seed=fc.RNG_SEED)
    np.testing.assert_array_equal(folds_p, folds_p_aug)


# ===========================================================================
# 3. the intersection mask (checklist item 3)
# ===========================================================================
def test_intersection_auc_drops_a_nan_row_from_both_computations():
    rng = np.random.default_rng(0)
    n = 200
    y = rng.integers(0, 2, n).astype(float)
    p_a = np.clip(y * 0.6 + rng.normal(0, 0.2, n) + 0.2, 0.01, 0.99)
    p_b = np.clip(y * 0.5 + rng.normal(0, 0.25, n) + 0.25, 0.01, 0.99)

    p_a_holed = p_a.copy()
    p_a_holed[[5, 17]] = np.nan

    got = fchal.intersection_auc(y, p_a_holed, p_b)
    assert got["n"] == n - 2
    assert int(got["ok"].sum()) == n - 2
    assert not got["ok"][5] and not got["ok"][17]
    assert got["auc_a"] == got["auc_a"] and got["auc_b"] == got["auc_b"], (
        "both AUCs must still be computable on the shared mask")

    full = fchal.intersection_auc(y, p_a, p_b)
    assert full["n"] == n, "no NaNs, no rows dropped"


# ===========================================================================
# 4. the verdict, six criteria (checklist item 4)
# ===========================================================================
def _category_table(n_improved: int, n_hard_regressed: int = 0) -> list[dict]:
    cats = []
    for i in range(n_improved):
        cats.append({"category": f"imp{i}", "n": 600, "both_classes": True,
                    "delta_auc": 0.01})
    for i in range(n_hard_regressed):
        cats.append({"category": f"reg{i}", "n": 600, "both_classes": True,
                    "delta_auc": -0.03})
    remaining = 15 - n_improved - n_hard_regressed
    for i in range(max(remaining, 0)):
        cats.append({"category": f"flat{i}", "n": 600, "both_classes": True,
                    "delta_auc": -0.005})
    return cats


BASE_RESULT = dict(
    delta_auc=0.02, ci_nta=(0.005, 0.035),
    brier_gbm=0.10, brier_logit=0.12,
    log_loss_gbm=0.30, log_loss_logit=0.35,
    calibration_gap_gbm=0.05,
    category_table=_category_table(10),
    moran_gbm=0.30, moran_logit=0.35)

FAILING_VARIANTS = {
    "W1": {**BASE_RESULT, "delta_auc": 0.005},
    "W2": {**BASE_RESULT, "ci_nta": (-0.001, 0.02)},
    "W3": {**BASE_RESULT, "brier_gbm": 0.13},
    "W4": {**BASE_RESULT, "calibration_gap_gbm": 0.20},
    "W5": {**BASE_RESULT, "category_table": _category_table(5)},
    "W6": {**BASE_RESULT, "moran_gbm": 0.50},
}


@pytest.mark.parametrize("label", sorted(FAILING_VARIANTS))
def test_evaluate_verdict_fails_exactly_the_named_criterion(label):
    got = fchal.evaluate_verdict(FAILING_VARIANTS[label])
    assert got["wins"] is False
    assert label in got["verdict_reason"], got["verdict_reason"]
    assert got["criteria"][label] is False
    others = {k: v for k, v in got["criteria"].items() if k != label}
    assert all(others.values()), f"{label} case also failed {others}"


def test_evaluate_verdict_wins_when_all_six_criteria_hold():
    got = fchal.evaluate_verdict(BASE_RESULT)
    assert got["wins"] is True
    assert got["status"] == "wins"
    assert all(got["criteria"].values())
    assert "WINS" in got["verdict_reason"]


# ===========================================================================
# 5. the paired bootstrap (checklist item 5) -- the REUSED retrodiction
#    function, wired the way `_build_comparison` calls it
# ===========================================================================
def test_bootstrap_delta_on_identical_predictions_is_null_and_seed_reproducible():
    rng = np.random.default_rng(1)
    n = 300
    oof = pd.DataFrame({
        "nta_code": [f"N{i % 15}" for i in range(n)],
        "y": rng.integers(0, 2, n).astype(float),
        "p_treat": np.clip(rng.uniform(0.1, 0.9, n), 0.01, 0.99)})
    oof["p_base"] = oof["p_treat"]          # IDENTICAL predictions

    a = rd.bootstrap_delta(oof, treat="p_treat", base="p_base",
                           cluster="nta_code", draws=400, seed=fc.RNG_SEED)
    b = rd.bootstrap_delta(oof, treat="p_treat", base="p_base",
                           cluster="nta_code", draws=400, seed=fc.RNG_SEED)

    assert a["draws"] == b["draws"] == 400
    assert a["mean"] == pytest.approx(0.0, abs=1e-9)
    assert a["ci"][0] <= 0.0 <= a["ci"][1]
    assert a["ci"] == b["ci"], "same seed, same draws must reproduce the CI"


# ===========================================================================
# 6. residual Moran's I (checklist item 6) -- the REUSED retrodiction function
# ===========================================================================
def test_residual_morans_i_separates_shuffled_from_spatially_structured_residuals():
    rng = np.random.default_rng(2)
    n = 400
    xs = rng.uniform(0, 1200, n)
    ys = rng.uniform(0, 1200, n)
    # a smooth spatial field, wavelength long relative to point spacing, so
    # nearby points share phase -- STRUCTURED.
    field = np.sin(xs / 300.0) + np.cos(ys / 300.0)
    resid_structured = field + rng.normal(0, 0.05, n)
    resid_shuffled = rng.permutation(resid_structured)

    lon = -73.9 + xs / 111_000.0
    lat = 40.7 + ys / 111_000.0
    point_id = [f"p{i}" for i in range(n)]
    panel = pd.DataFrame({"point_id": point_id, "lon": lon, "lat": lat})

    def _oof(residual):
        # residual_morans_i measures y - p_base; p_base=0 makes the residual
        # exactly the vector under test.
        return pd.DataFrame({"point_id": point_id, "category": "restaurant",
                             "y": residual, "p_base": 0.0, "p_treat": 0.0})

    structured = rd.residual_morans_i(panel, _oof(resid_structured))
    shuffled = rd.residual_morans_i(panel, _oof(resid_shuffled))

    assert structured["mean_base"] > 0.3, structured
    assert abs(shuffled["mean_base"]) < 0.15, shuffled


# ===========================================================================
# 7/8. the CLI orchestrator -- a bigger synthetic panel, computed ONCE and
# shared by both items since the GBM fits are the expensive part
# ===========================================================================
def _populate_big_panel(con) -> None:
    """24 addresses over 6 NTAs, 4 addresses per NTA, category='restaurant'.
    Openings are placed by `rep` (0-3, an address's position WITHIN its NTA),
    never by NTA alone, so every NTA carries both outcome classes in both
    fit folds -- any held-out NTA still leaves training data with y variance."""
    counter = 0
    for nta_i in range(6):
        for rep in range(4):
            aid = f"a{nta_i}_{rep}"
            # 0.0055 deg (~460 m here) keeps every address's own 400 m disc
            # from ever reaching a NEIGHBOUR's POIs -- a 0.004 deg (~336 m)
            # step let adjacent addresses' discs overlap, so a `rep == 3`
            # address (which never gets a POI of its own, by the rule below)
            # still picked up its neighbour's, and `own_gap_flag` came out
            # constant across the whole panel -- a zero-variance column is a
            # singular design matrix, not a thin one.
            base_lon = LON + 0.0055 * counter
            base_lat = LAT + 0.0011 * (counter % 3)
            # units/retail_index vary by row -- a perfectly regular grid with
            # constant units and a constant retail_index gives `log_homes`
            # and `retail_index` almost no independent variation, which is a
            # singular design matrix for the clustered logit, not a
            # meaningfully thin one.
            add_address(con, aid, base_lon, base_lat, nta=f"BK01{nta_i:02d}",
                       units=60.0 + 15.0 * (counter % 5),
                       ri=0.2 + 0.08 * (counter % 6))
            if rep in (0, 2):        # fold 1's PREV window [2022-01, 2023-01)
                add_poi(con, f"prev1_{aid}", "restaurant", base_lon + 0.0005,
                       base_lat, "source_date", dt.date(2022, 6, 1))
            if rep in (0, 1):        # fold 1's OUTCOME / fold 2's PREV window
                add_poi(con, f"mid_{aid}", "restaurant", base_lon + 0.0006,
                       base_lat, "source_date", dt.date(2023, 6, 1))
            if rep in (1, 2):        # fold 2's OUTCOME window [2024-01, 2025-01)
                add_poi(con, f"out2_{aid}", "restaurant", base_lon + 0.0007,
                       base_lat, "source_date", dt.date(2024, 6, 1))
            counter += 1


@pytest.fixture(scope="module")
def challenge_result(tmp_path_factory):
    """Runs `run_challenge` ONCE, against a temp on-disk DuckDB opened
    `read_only=True` -- the literal contract the CLI hands this function, and
    proof by construction that nothing here can write: a write attempt on a
    read-only DuckDB handle raises, which would fail this fixture, not the
    assertions below."""
    path = tmp_path_factory.mktemp("forecast_challenge") / "warehouse.duckdb"
    setup = locidb.connect(str(path))
    _create_schema(setup)
    _populate_big_panel(setup)
    setup.close()

    con = locidb.connect(str(path), read_only=True)
    try:
        rep = fchal.run_challenge(con, month="2025-01", sample_n=24,
                                  categories=("restaurant",), progress=None)
    finally:
        con.close()
    return rep


def test_run_challenge_never_writes_to_forecast_tables_and_json_has_declared_keys(
        challenge_result):
    """Checklist item 7: row counts before/after are identical (there are no
    forecast* tables on this synthetic warehouse at all, which is itself an
    unchanged count -- None == None), and the payload validates against the
    declared key set."""
    rep = challenge_result
    assert rep["forecast_row_counts_before"] == rep["forecast_row_counts_after"]
    assert rep["row_counts_unchanged"] is True
    missing = set(fchal.REQUIRED_KEYS) - set(rep.keys())
    assert not missing, f"payload is missing declared keys: {missing}"


def test_run_challenge_carries_three_rungs_and_both_anachronistic_arms(
        challenge_result):
    """Checklist item 8: rung 1/2/3 AUCs and both `--no-anachronistic` arms
    are all in the JSON, and rung 1 reproduces `fit()['auc_blocked']` to 1e-9
    -- it is the SAME `blocked_oos_predictions` call on the SAME dropna'd
    panel `fit()` uses internally."""
    rep = challenge_result
    assert set(rep["rungs"]) == {"rung1_logit_baseline",
                                 "rung2_logit_plus_t0_true_features"}
    assert rep["rungs"]["rung1_logit_baseline"]["matches_fit_auc_blocked"] is True
    assert set(rep["both_arms"]) == {"without_anachronistic", "with_anachronistic"}
    for arm_name, arm in rep["both_arms"].items():
        assert "auc_gbm" in arm and "verdict" in arm, arm_name
        assert "wins" in arm["verdict"] and "verdict_reason" in arm["verdict"]
    assert rep["headline_arm"] in rep["both_arms"]
    assert rep["wins"] == rep["both_arms"][rep["headline_arm"]]["verdict"]["wins"]
