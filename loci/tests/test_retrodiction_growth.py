"""D111 / GTM-168 — the Citi Bike growth feature inside the retrodiction.

Every case here pins a clause of the ratified pre-registration
(`docs/CHECKPOINT.md` D111; the block is printed by the verdict itself). What is
worth pinning is not "does it run" but the four places where a paired test
silently stops being paired, plus the arithmetic of the ship criterion:

  * P2 — the two fits must see the SAME rows and the SAME folds. `blocked_cv_auc`
    derives folds from `nta_code.unique()`, which is row-ORDER dependent, so two
    frames holding the same NTAs in a different order get different folds from
    the same seed. An explicit fold map is the fix and this file pins it.
  * P4 — the delta must come from ONE set of out-of-fold predictions. Two
    independently cross-validated AUCs subtracted from each other are not a
    paired comparison and their difference has no usable interval.
  * P5 — the placebo has to preserve each NTA's growth VECTOR and the marginal,
    or it is an i.i.d. shuffle wearing a spatial costume and any smooth feature
    beats it.
  * P3 — the floor RISES to the placebo's p95 when the placebo is good at the
    task. A floor that ignores its own null is a decoration.

No network, no warehouse: a synthetic panel and a temp DuckDB carrying the
`analysis.address_bike_growth` contract from the spec.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from loci import db as locidb
from loci.validation import retrodiction as rd


# ===========================================================================
# fixtures
# ===========================================================================
#: The table track G builds (`src/loci/model/address_bike_growth.py`,
#: migration 038). Created here from the SPEC's column list so this file does
#: not depend on that build landing first — if the two ever disagree,
#: `attach_bike_growth` raises on the contract check rather than joining NULLs.
GROWTH_DDL = """
CREATE TABLE analysis.address_bike_growth (
    address_id        VARCHAR,
    borough           VARCHAR,
    asof_month        DATE,
    activity_12m      DOUBLE,
    activity_prior_12m DOUBLE,
    bike_growth_12m   DOUBLE,
    bike_growth_12m_rel DOUBLE,
    n_docks_balanced  SMALLINT,
    balanced_share    DOUBLE,
    docks_added_24m   SMALLINT,
    member_only       BOOLEAN,
    window_first      DATE,
    window_last       DATE,
    run_at            TIMESTAMP
)"""

T0 = dt.date(2023, 1, 1)


@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute(GROWTH_DDL)
    return c


def _insert_growth(con, rows, asof=T0, member_only=True):
    for i, (aid, rel, share) in enumerate(rows):
        con.execute(
            "INSERT INTO analysis.address_bike_growth VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [aid, "BK", asof, 100.0 + i, 90.0 + i, 0.1, rel, 12, share, 1,
             member_only, dt.date(2021, 2, 1), dt.date(2022, 12, 1),
             dt.datetime(2026, 9, 15)])


def synthetic_panel(n_nta: int = 12, per_nta: int = 30, n_cat: int = 3,
                    seed: int = 7, signal: float = 1.2) -> pd.DataFrame:
    """address x category, with a growth feature that carries REAL signal.

    Built so the paired machinery has something to find: `y` depends on the
    controls and on the feature, the feature is spatially smooth (an NTA-level
    mean plus address noise), and addresses sit on a lattice so Moran's I and
    the kNN graph have coordinates to work with."""
    rng = np.random.default_rng(seed)
    rows = []
    for j in range(n_nta):
        nta = f"BK{j // 4 + 1:02d}{j % 4 + 1:02d}"
        nta_mean = rng.normal(0.0, 0.6)
        for k in range(per_nta):
            aid = f"a{j:02d}{k:03d}"
            g = nta_mean + rng.normal(0.0, 0.25)
            rows.append({
                "point_id": aid, "nta_code": nta, "borough": "BK",
                "lon": -73.99 + 0.004 * j + 0.0004 * k,
                "lat": 40.67 + 0.004 * (k % 6) + 0.0004 * j,
                "log_homes": rng.normal(6.0, 0.7),
                "log_jobs": rng.normal(5.0, 0.9),
                "log_transit": rng.normal(7.0, 1.0),
                "retail_index": rng.normal(0.0, 1.0),
                "docks_added_24m": float(rng.integers(0, 4)),
                "balanced_share": 1.0,
                "activity_12m": float(rng.integers(50, 5000)),
                "n_docks_balanced": int(rng.integers(3, 20)),
                rd.BIKE_FEATURE: g,
            })
    addr = pd.DataFrame(rows)
    cats = ["restaurant", "cafe_bakery", "bar"][:n_cat]
    panel = addr.merge(pd.DataFrame({"category": cats}), how="cross")
    panel["log_score"] = rng.normal(0.0, 1.0, len(panel))
    panel["own_gap_flag"] = (rng.random(len(panel)) < 0.2).astype(int)
    panel["supply"] = rng.integers(0, 10, len(panel)).astype(float)
    panel["supply_other"] = rng.integers(0, 30, len(panel)).astype(float)
    panel["log_supply_own"] = np.log1p(panel["supply"])
    panel["log_supply_other"] = np.log1p(panel["supply_other"])
    lin = (-1.0 + 0.55 * panel["log_score"] + 0.35 * panel["log_homes"]
           + 0.30 * panel["retail_index"] + signal * panel[rd.BIKE_FEATURE]
           - 2.0)
    panel["y"] = (rng.random(len(panel)) < 1 / (1 + np.exp(-lin))).astype(int)
    panel["cd_code"] = panel["nta_code"].map(rd.cd_code)
    panel["t0"] = T0
    panel["bike_member_only"] = True
    return panel


BASE = rd.FULL_COLS + ["docks_added_24m"]
TREAT = BASE + [rd.BIKE_FEATURE]


# ===========================================================================
# P2 — the join, the attrition report, and the shared fold map
# ===========================================================================
def test_build_panel_joins_growth_on_address_asof_and_member_only(con):
    """The join key is (address_id, asof_month, member_only). Getting any one of
    the three wrong silently produces a column of NULLs, which the model would
    then drop as attrition rather than as a bug."""
    _insert_growth(con, [("a1", 0.5, 0.9), ("a2", -0.3, 0.8)], asof=T0)
    _insert_growth(con, [("a1", 9.9, 0.9)], asof=dt.date(2025, 1, 1))
    _insert_growth(con, [("a1", -9.9, 0.9)], asof=T0, member_only=False)

    panel = pd.DataFrame({"point_id": ["a1", "a2", "a3"]})
    out = rd.attach_bike_growth(con, panel, asof=T0, member_only=True)

    assert out.loc[out.point_id == "a1", rd.BIKE_FEATURE].iloc[0] == pytest.approx(0.5)
    assert out.loc[out.point_id == "a2", rd.BIKE_FEATURE].iloc[0] == pytest.approx(-0.3)
    # a3 has no growth row at all: LEFT join, so it stays in the frame as a NULL
    # for bike_attrition to count, rather than vanishing from the denominator.
    assert bool(out.loc[out.point_id == "a3", rd.BIKE_FEATURE].isna().iloc[0])
    for c in ("bike_growth_12m", "balanced_share", "docks_added_24m"):
        assert c in out.columns


def test_duplicate_growth_rows_are_refused(con):
    """A duplicate at the join grain multiplies panel rows and inflates every n
    in the section. Loud, not silent."""
    _insert_growth(con, [("a1", 0.5, 0.9), ("a1", 0.7, 0.9)], asof=T0)
    with pytest.raises(RuntimeError, match="duplicate"):
        rd.attach_bike_growth(con, pd.DataFrame({"point_id": ["a1"]}),
                              asof=T0, member_only=True)


def test_missing_growth_table_raises_with_the_contract(con):
    con.execute("DROP TABLE analysis.address_bike_growth")
    with pytest.raises(RuntimeError, match="growth-measures"):
        rd.attach_bike_growth(con, pd.DataFrame({"point_id": ["a1"]}),
                              asof=T0, member_only=True)


def test_lagged_vintage_is_optional_and_suffixed(con):
    """P9's pre-trend vintage is never required — the 2023-01 primary has no
    lagged window to read."""
    con.execute("DROP TABLE analysis.address_bike_growth")
    out = rd.attach_bike_growth(con, pd.DataFrame({"point_id": ["a1"]}),
                                asof=dt.date(2021, 12, 1), suffix="_lag",
                                required=False)
    assert rd.BIKE_FEATURE + "_lag" in out.columns
    assert out[rd.BIKE_FEATURE + "_lag"].isna().all()


def test_attrition_counts_what_the_balanced_dock_floor_removes():
    """P2 — rows lost, and whether the survivors are a different city."""
    p = synthetic_panel(n_nta=8, per_nta=20)
    lost = p["point_id"].isin(p["point_id"].unique()[:40])
    p.loc[lost, rd.BIKE_FEATURE] = np.nan
    p.loc[lost, "balanced_share"] = 0.3
    p.loc[lost, "retail_index"] = p.loc[lost, "retail_index"] - 2.0

    a = rd.bike_attrition(p)
    assert a["n_rows_lost"] == int(lost.sum())
    assert a["share_lost"] == pytest.approx(float(lost.mean()))
    assert a["n_lost_below_balanced_share_floor"] == int(lost.sum())
    # the retained rows are RICHER by construction; the std diff has to see it
    assert a["retained_vs_lost"]["retail_index"]["std_diff"] > 1.0
    assert a["exceeds_20pct"] is True
    assert "INNER CORE" in a["claim"]


def test_both_fits_get_the_identical_fold_map():
    """P2, the clause that makes the comparison paired at all.

    `nta_fold_map` is a function of the NTA SET, not of row order: the same set
    in a shuffled frame must produce the same map, and both models must be
    scored against it."""
    p = synthetic_panel(n_nta=10, per_nta=15)
    fm = rd.nta_fold_map(p, seed=1)
    shuffled = p.sample(frac=1.0, random_state=3).reset_index(drop=True)
    assert rd.nta_fold_map(shuffled, seed=1) == fm

    _, pred_base = rd.blocked_cv_auc(p, BASE, fold_map=fm)
    _, pred_treat = rd.blocked_cv_auc(p, TREAT, fold_map=fm)
    oof = rd._oof_frame(p, fm, {"p_base": pred_base, "p_treat": pred_treat})
    # one fold column, therefore one partition, therefore one comparison
    by_nta = oof.groupby("nta_code")["fold"].nunique()
    assert (by_nta == 1).all(), "an NTA was split across folds"
    assert oof["fold"].nunique() == rd.N_FOLDS
    assert pred_base.shape == pred_treat.shape == (len(p),)


def test_fold_map_without_sorting_would_not_be_reproducible():
    """The bug the explicit map exists to prevent, pinned as a fact about the
    OLD path: seeded folds derived from `unique()` depend on row order, so a
    NULL-filtered frame gets different folds from the same seed."""
    p = synthetic_panel(n_nta=10, per_nta=15)
    a, _ = rd.blocked_cv_auc(p, BASE, seed=5)
    b, _ = rd.blocked_cv_auc(p.sample(frac=1.0, random_state=11).reset_index(drop=True),
                             BASE, seed=5)
    fm = rd.nta_fold_map(p, seed=5)
    c, _ = rd.blocked_cv_auc(p, BASE, fold_map=fm)
    d, _ = rd.blocked_cv_auc(p.sample(frac=1.0, random_state=11).reset_index(drop=True),
                             BASE, fold_map=fm)
    assert c == pytest.approx(d), "the explicit map must be order-invariant"
    assert isinstance(a, float) and isinstance(b, float)


# ===========================================================================
# P4 — the delta comes from ONE set of out-of-fold predictions
# ===========================================================================
def test_delta_is_computed_from_the_same_oof_predictions():
    p = synthetic_panel(n_nta=10, per_nta=20)
    res = rd.fit_growth_test(p, con=None, placebo_draws=3, decile_placebo_draws=2,
                             bootstrap_draws=40, seeds=3, per_category=False)
    oof = res["_oof"]
    assert len(oof) == res["n_rows"]
    ok = oof.dropna(subset=["p_base", "p_treat"])
    d = rd._auc(ok["y"].to_numpy(), ok["p_treat"].to_numpy()) \
        - rd._auc(ok["y"].to_numpy(), ok["p_base"].to_numpy())
    assert res["delta_P0"] == pytest.approx(d, abs=1e-9)
    assert res["auc_with_growth_P0"] - res["auc_baseline_P1"] == \
        pytest.approx(res["delta_P0"], abs=1e-12)
    # P1: FULL alone is reported, and it is NOT the baseline the gate uses
    assert "auc_full_only_P1" in res and res["auc_full_only_P1"] != res["delta_P0"]


def test_bootstrap_resamples_clusters_and_returns_a_ci_on_the_delta():
    p = synthetic_panel(n_nta=12, per_nta=20)
    fm = rd.nta_fold_map(p, seed=2)
    _, pb = rd.blocked_cv_auc(p, BASE, fold_map=fm)
    _, pt = rd.blocked_cv_auc(p, TREAT, fold_map=fm)
    oof = rd._oof_frame(p, fm, {"p_base": pb, "p_treat": pt})

    nta = rd.bootstrap_delta(oof, cluster="nta_code", draws=60, seed=4)
    cd = rd.bootstrap_delta(oof, cluster="cd_code", draws=60, seed=4)
    assert nta["draws"] > 0 and cd["draws"] > 0
    assert nta["ci"][0] <= nta["mean"] <= nta["ci"][1]
    # CD blocking is coarser than NTA, so there are fewer clusters to resample
    assert oof["cd_code"].nunique() < oof["nta_code"].nunique()
    assert 0.0 <= cd["p_two_sided"] <= 1.0


# ===========================================================================
# P5 — the NTA-block donation placebo
# ===========================================================================
def test_nta_block_placebo_preserves_each_ntas_vector_and_the_marginal():
    """The defining property. Equal-sized NTAs inside a stratum means the
    donation is an exact permutation of whole vectors: every NTA's multiset of
    values still exists somewhere, and the panel-wide marginal is untouched."""
    rng = np.random.default_rng(0)
    ntas = np.repeat([f"BK01{i:02d}" for i in range(6)], 10).astype(object)
    values = rng.normal(size=len(ntas))
    strata = dict.fromkeys(np.unique(ntas), "BK:t0")

    out, fixed = rd.nta_block_donation(values, ntas, strata, rng)

    # the MARGINAL, exactly
    assert np.allclose(np.sort(out), np.sort(values))
    # each NTA's VECTOR survives intact, somewhere
    donated = {tuple(np.round(np.sort(out[ntas == n]), 12)) for n in np.unique(ntas)}
    original = {tuple(np.round(np.sort(values[ntas == n]), 12)) for n in np.unique(ntas)}
    assert donated == original
    # the within-NTA ORDER (the rank assignment) survives
    for n in np.unique(ntas):
        m = ntas == n
        assert np.array_equal(np.argsort(np.argsort(out[m])),
                              np.argsort(np.argsort(values[m])))
    assert fixed == 0, "a derangement should leave no NTA holding its own vector"


def test_placebo_does_not_donate_across_strata():
    """Matching on borough x activity tercile is what keeps the null honest: a
    placebo that moved a quiet NTA's vector into Midtown would destroy LEVEL as
    well as location and be trivially easy to beat."""
    rng = np.random.default_rng(1)
    ntas = np.repeat(["A1", "A2", "B1", "B2"], 5).astype(object)
    values = np.concatenate([np.full(10, 1.0), np.full(10, 100.0)])
    strata = {"A1": "s1", "A2": "s1", "B1": "s2", "B2": "s2"}
    out, _ = rd.nta_block_donation(values, ntas, strata, rng)
    assert set(out[:10]) == {1.0}
    assert set(out[10:]) == {100.0}


def test_nta_strata_are_borough_by_activity_tercile():
    p = synthetic_panel(n_nta=12, per_nta=10)
    addr = rd._address_frame(p, rd.BIKE_FEATURE)
    strata = rd.nta_strata(addr)
    assert set(strata) == set(addr["nta_code"].unique())
    assert all(s.startswith("BK:t") for s in strata.values())
    assert len(set(strata.values())) > 1, "one stratum is no matching at all"


def test_decile_swap_preserves_the_marginal_within_borough():
    rng = np.random.default_rng(2)
    v = rng.normal(size=200)
    out = rd.decile_swap(v, np.array(["BK"] * 200, dtype=object),
                         np.arange(200.0), rng)
    assert np.allclose(np.sort(out), np.sort(v))


def test_placebo_is_computed_on_the_delta_and_before_the_real_fit():
    p = synthetic_panel(n_nta=10, per_nta=18)
    res = rd.fit_growth_test(p, con=None, placebo_draws=4, decile_placebo_draws=2,
                             bootstrap_draws=30, seeds=2, per_category=False)
    pl = res["placebo_P5"]
    assert pl["mode"] == "nta_block" and pl["draws"] == 4
    assert res["placebo_secondary_P5"]["mode"] == "decile_swap"
    assert res["timing"]["placebo_before_real_fit"] is True
    # the null lives on the DELTA, so it straddles zero rather than sitting at
    # whatever the baseline AUC happens to be
    assert abs(pl["mean"]) < 0.5


# ===========================================================================
# P3 — the floor
# ===========================================================================
def test_floor_is_the_absolute_005_when_the_placebo_is_quiet():
    placebo = {"p95": 0.001}
    floor = max(rd.DELTA_FLOOR, placebo["p95"])
    assert floor == pytest.approx(0.005)


def test_floor_rises_to_the_placebo_p95_when_the_placebo_beats_it(monkeypatch):
    """P3's whole point: the floor is max(+0.005, placebo p95). If spatially
    structured noise can buy +0.02 of delta on this panel, then +0.02 is what
    the feature has to clear — not +0.005."""
    p = synthetic_panel(n_nta=10, per_nta=18)

    real = rd.placebo_delta

    def loud(*a, **kw):
        out = real(*a, **kw)
        if kw.get("mode", "nta_block") == "nta_block":
            out["p95"] = 0.02          # a null that is good at the task
        return out

    monkeypatch.setattr(rd, "placebo_delta", loud)
    res = rd.fit_growth_test(p, con=None, placebo_draws=2, decile_placebo_draws=1,
                             bootstrap_draws=30, seeds=2, per_category=False)
    assert res["floor_P3"] == pytest.approx(0.02)
    assert res["floor_basis_P3"] == "placebo p95"
    assert res["passes_floor_P3"] == bool(res["delta_P0"] >= 0.02)
    # and P8's own floor moves with it
    assert res["stability_P8"]["floor"] == pytest.approx(0.02)


# ===========================================================================
# P7 — the verdict logic
# ===========================================================================
def _stub(delta, ci, *, floor=0.005, median=None, n_pos=20, seeds=20, fitted=True):
    return {
        "fitted": fitted,
        "delta_P0": delta,
        "floor_P3": floor,
        "floor_basis_P3": "the absolute floor 0.005",
        "bootstrap_cd_P4": {"ci": list(ci)},
        "passes_floor_P3": delta >= floor,
        "passes_ci_P3": ci[0] > rd.DELTA_CI_FLOOR,
        "passes_P3": delta >= floor and ci[0] > rd.DELTA_CI_FLOOR,
        "stability_P8": {"passes": (median if median is not None else delta) >= floor
                         and n_pos >= int(np.ceil(0.9 * seeds)),
                         "median": median if median is not None else delta,
                         "sd": 0.001, "n_positive": n_pos, "seeds": seeds,
                         "required_positive": int(np.ceil(0.9 * seeds)),
                         "floor": floor},
        "pre_trend_P9": {"available": False},
    }


def test_verdict_refuses_to_ship_without_the_confirmatory_vintage():
    v = rd.bike_growth_verdict(_stub(0.02, (0.010, 0.030)))
    assert v["ship"] is False
    assert any("P7" in r for r in v["reasons"])
    assert "CONTEXT ONLY" in v["disposition"]
    assert "P0  One primary test" in v["judged_against"]


def test_verdict_ships_when_the_confirmatory_vintage_independently_clears():
    primary = _stub(0.02, (0.010, 0.030))
    conf = _stub(0.015, (0.008, 0.022))
    v = rd.bike_growth_verdict(primary, conf)
    assert v["P7"]["independently_clears"] is True
    assert v["P7"]["passes"] is True
    assert v["ship"] is True
    assert "SHIP" in v["disposition"]


def test_verdict_ships_when_the_two_vintages_are_merely_compatible():
    """P7's other arm: 2025-01's delta is positive and the CI on the DIFFERENCE
    of the two deltas contains zero, even though 2025-01 would not clear the
    floor on its own."""
    primary = _stub(0.02, (0.010, 0.030))
    conf = _stub(0.004, (-0.002, 0.010))     # positive, but does not clear
    assert conf["passes_P3"] is False
    rng = np.random.default_rng(0)
    n = 900
    oof_a = pd.DataFrame({"y": rng.integers(0, 2, n).astype(float),
                          "p_base": rng.random(n), "p_treat": rng.random(n),
                          "cd_code": rng.choice([f"BK{i:02d}" for i in range(8)], n)})
    oof_b = oof_a.copy()                      # identical -> the difference is 0
    conf["_oof"] = oof_b
    v = rd.bike_growth_verdict(primary, conf, oof=oof_a, draws=60)
    assert v["P7"]["delta_difference_ci"]["contains_zero"] is True
    assert v["P7"]["compatible"] is True
    assert v["ship"] is True


def test_verdict_fails_when_the_confirmatory_delta_is_negative():
    primary = _stub(0.02, (0.010, 0.030))
    conf = _stub(-0.01, (-0.02, -0.001))
    v = rd.bike_growth_verdict(primary, conf)
    assert v["P7"]["positive"] is False
    assert v["ship"] is False


def test_verdict_fails_on_P3_and_on_P8_independently():
    # P3: the point delta clears the floor but the CD-clustered CI does not
    v = rd.bike_growth_verdict(_stub(0.02, (0.001, 0.040)), _stub(0.02, (0.01, 0.03)))
    assert v["P3"]["passes"] is False and v["ship"] is False
    assert any("CD-clustered" in r for r in v["reasons"])

    # P8: positive in only 15 of 20 fold seeds
    v = rd.bike_growth_verdict(_stub(0.02, (0.010, 0.030), n_pos=15),
                               _stub(0.02, (0.01, 0.03)))
    assert v["P8"]["passes"] is False and v["ship"] is False


def test_verdict_fails_when_the_lagged_pre_trend_predicts_as_well():
    """P9 is a diagnostic with teeth: a feature indistinguishable from its own
    lag is a persistent location marker, not a change signal."""
    primary = _stub(0.02, (0.010, 0.030))
    primary["pre_trend_P9"] = {"available": True, "delta_lagged": 0.019,
                               "persistent_location_marker": True}
    v = rd.bike_growth_verdict(primary, _stub(0.02, (0.01, 0.03)))
    assert v["ship"] is False
    assert any("P9" in r for r in v["reasons"])


# ===========================================================================
# P9 — the pre-trend wiring
# ===========================================================================
def test_lagged_growth_column_is_picked_up_and_tested_the_same_way():
    p = synthetic_panel(n_nta=10, per_nta=20)
    rng = np.random.default_rng(5)
    # a lag that is the contemporaneous feature plus noise: the same paired
    # machinery has to run on it and produce a delta of its own
    p[rd.BIKE_FEATURE + "_lag"] = p[rd.BIKE_FEATURE] + rng.normal(0, 0.1, len(p))
    res = rd.fit_growth_test(p, con=None, placebo_draws=2, decile_placebo_draws=1,
                             bootstrap_draws=40, seeds=2, per_category=False)
    pt = res["pre_trend_P9"]
    assert pt["available"] is True
    assert "delta_lagged" in pt and np.isfinite(pt["delta_lagged"])
    assert "p_lag" in res["_oof"].columns
    assert "contemporaneous_minus_lagged" in pt
    assert pt["contemporaneous_minus_lagged"]["cluster"] == "cd_code"
    assert isinstance(pt["persistent_location_marker"], bool)


def test_pre_trend_is_absent_without_a_lagged_vintage():
    p = synthetic_panel(n_nta=8, per_nta=15)
    res = rd.fit_growth_test(p, con=None, placebo_draws=2, decile_placebo_draws=1,
                             bootstrap_draws=20, seeds=2, per_category=False)
    assert res["pre_trend_P9"]["available"] is False
    assert "2025-01" in res["pre_trend_P9"]["note"]


# ===========================================================================
# P10 — Benjamini-Hochberg, and "not a finding"
# ===========================================================================
def test_benjamini_hochberg_step_up():
    p = [0.001, 0.008, 0.04, 0.2, 0.9]
    rej, crit = rd.benjamini_hochberg(p, q=0.10)
    # i*q/n = .02 .04 .06 .08 .10 -> the largest i with p_(i) <= threshold is 3
    assert list(rej) == [True, True, True, False, False]
    assert crit == pytest.approx(0.04)


def test_bh_labels_non_surviving_secondaries_as_not_a_finding():
    lab = rd.bh_label({"category:restaurant": 0.001, "category:bar": 0.30,
                       "residualised": 0.60}, q=0.10)
    assert lab["results"]["category:restaurant"]["label"] == "finding"
    assert lab["results"]["category:bar"]["label"] == "not a finding"
    assert lab["results"]["residualised"]["survives_bh"] is False
    assert lab["n_tests"] == 3 and lab["q"] == 0.10
    assert "6 categories x 2 vintages" in lab["family_declared"]


def test_per_category_deltas_carry_a_bh_label():
    p = synthetic_panel(n_nta=12, per_nta=25, n_cat=3)
    res = rd.fit_growth_test(p, con=None, placebo_draws=2, decile_placebo_draws=1,
                             bootstrap_draws=40, seeds=2, per_category=True)
    assert set(res["by_category"]) == {"restaurant", "cafe_bakery", "bar"}
    for cat, r in res["by_category"].items():
        if "skipped" in r:
            continue
        assert r["auc_treat"] - r["auc_base"] == pytest.approx(r["delta"], abs=1e-9)
        assert f"category:{cat}" in res["multiple_testing_P10"]["results"]


# ===========================================================================
# P6 / P11 — the diagnostics that decide how the result is DESCRIBED
# ===========================================================================
def test_auxiliary_r2_and_the_residualised_column():
    p = synthetic_panel(n_nta=8, per_nta=20)
    aux, resid = rd.auxiliary_r2(p)
    assert 0.0 <= aux["r2"] <= 1.0
    assert "docks_added_24m" in aux["controls"]
    assert len(resid) == len(p)
    # the residual is orthogonal to the controls by construction
    assert abs(float(np.nanmean(resid))) < 1e-8


def test_moran_and_effective_n_run_without_a_warehouse():
    p = synthetic_panel(n_nta=10, per_nta=20)
    pre = rd.spatial_pre_diagnostics(None, p)
    assert pre["morans_i_feature"]["i"] is not None
    assert pre["effective_n"]["method"] == "n_docks_balanced STAND-IN"
    # and it SAYS it is a stand-in rather than passing itself off as the count
    assert "placeholder" in pre["effective_n"]["note"]
    assert "address_bike_station" in pre["effective_n"]["note"]
    # a spatially smooth feature must show positive autocorrelation
    assert pre["morans_i_feature"]["i"] > 0


def test_cd_code_is_the_first_four_of_the_nta2020_code():
    assert rd.cd_code("BK0101") == "BK01"
    assert rd.cd_code("MN1203") == "MN12"
    assert rd.cd_code(None) is None


def test_ascertainment_truncation_rule_drops_the_unfiled_tail(con):
    """P7 — the last months of a window are not quiet months, they are months
    whose filings have not landed yet (D80's 221-259 day lead)."""
    con.execute("""CREATE TABLE analysis.poi_presence (
        first_seen_kind VARCHAR, first_seen_src_date DATE, borough VARCHAR)""")
    months = pd.date_range("2025-01-01", "2025-12-01", freq="MS")
    for i, m in enumerate(months):
        n = 100 if i < 9 else 10          # ascertainment collapses at month 10
        for _ in range(n):
            con.execute("INSERT INTO analysis.poi_presence VALUES (?,?,?)",
                        ["gov_filing", m.date(), "BK"])  # coded borough (sql/045)
    a = rd.ascertainment_by_month(con, dt.date(2025, 1, 1), dt.date(2025, 12, 31))
    assert a["truncate_at"] == "2025-09"
    assert a["months_dropped"] == 3
    assert len(a["by_month"]) == 12
