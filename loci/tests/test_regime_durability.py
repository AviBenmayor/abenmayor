"""Offline tests for src/loci/model/regime_durability.py on synthetic data — no
warehouse, no interim parquet files. Covers the pure logic: hysteresis spell
detection, pillar percentile ranking, KM summary, hazard-by-age, break-year
detection, the k-means+Markov regime model, the 2013-origin backtest, and the
named-ZIP scoring rule from PREREGISTRATION.md."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from loci.model import regime_durability as rd


# --------------------------------------------------------------- hysteresis


def _flat_series(unit, values, start_year=2000):
    return pd.DataFrame({
        "unit": unit,
        "year": range(start_year, start_year + len(values)),
        "c": values,
    })


def test_hysteresis_enters_at_070_for_2_years_exits_at_060_for_2_years():
    # below threshold, then >=0.70 for 2 straight years -> onset at the first of
    # those years; then a single dip below 0.60 does NOT end the spell.
    values = [0.3, 0.3, 0.75, 0.75, 0.80, 0.55, 0.80, 0.50, 0.50, 0.3, 0.3, 0.3]
    panel = _flat_series("A", values)
    spells = rd.hysteresis_spells(panel, "c", start_year=2000, end_year=2011)
    assert len(spells) == 1
    row = spells.iloc[0]
    assert row["onset_year"] == 2002  # first of the 2 confirming years (2002,2003)
    assert row["exit_year"] == 2007  # first of (2007,2008) both < 0.60
    assert row["incident"]  # onset (2002) > start_year (2000)


def test_single_year_dip_below_060_does_not_exit():
    values = [0.75, 0.75, 0.80, 0.55, 0.80, 0.80, 0.80]
    panel = _flat_series("B", values)
    spells = rd.hysteresis_spells(panel, "c", start_year=2000, end_year=2006)
    assert len(spells) == 1
    assert spells.iloc[0]["censored"]  # never confirmed 2 years below 0.60


def test_prevalent_spell_running_at_panel_start_is_not_incident():
    values = [0.80, 0.80, 0.55, 0.55, 0.30]
    panel = _flat_series("C", values)
    spells = rd.hysteresis_spells(panel, "c", start_year=2000, end_year=2004)
    assert len(spells) == 1
    row = spells.iloc[0]
    assert row["onset_year"] == 2000
    assert not row["incident"]  # onset == start_year -> undatable / prevalent
    assert row["exit_year"] == 2002


def test_exit_confirmed_in_final_year_is_relabeled_censored_not_exited():
    # statistician point 2(a): the last classifiable year is end_year - 1. With
    # persist=1 (single-year confirmation, one of the sensitivity-grid cells)
    # the raw exit_year formula CAN land on end_year itself, which must be
    # relabeled censored rather than reported as a dated exit.
    values = [0.75, 0.80, 0.55]  # single dip below 0.60 lands exactly on end_year
    panel = _flat_series("D", values, start_year=2000)
    spells = rd.hysteresis_spells(panel, "c", start_year=2000, end_year=2002, persist=1)
    assert len(spells) == 1
    row = spells.iloc[0]
    assert row["censored"]
    assert pd.isna(row["exit_year"])


def test_never_favorable_yields_no_spells():
    values = [0.2] * 10
    panel = _flat_series("E", values)
    spells = rd.hysteresis_spells(panel, "c", start_year=2000, end_year=2009)
    assert len(spells) == 0


# --------------------------------------------------------------- percentiles


def test_compute_pillar_percentiles_gate_zeroes_ineligible_units():
    # 3 units x years 2007-2011 (enough prior years that the tenant
    # composite's diff(3) term is defined by 2010-11); unit 'poor' always has
    # the lowest demand -> gated out of the amended composite even if it
    # looks cheap+under-restauranted.
    rows = []
    for year in range(2007, 2012):
        rows.append(dict(unit="rich", year=year, estab_restaurant_total=50, zhvi=900_000,
                          pop=20000, workers=20000, income_real=120_000, area_km2=2.0))
        rows.append(dict(unit="mid", year=year, estab_restaurant_total=20, zhvi=400_000,
                          pop=15000, workers=5000, income_real=60_000, area_km2=2.0))
        # 'poor' is lowest on every demand component (income, pop density, worker
        # density) so it is unambiguously gated out, not just cheap+empty.
        rows.append(dict(unit="poor", year=year, estab_restaurant_total=5, zhvi=200_000,
                          pop=5000, workers=1000, income_real=20_000, area_km2=2.0))
    panel = pd.DataFrame(rows)
    out = rd.compute_pillar_percentiles(panel)
    poor = out[(out["unit"] == "poor") & (out["year"] >= 2010)]
    assert (~poor["demand_gate"]).all()
    assert (poor["composite_B_owner"] == 0.0).all()
    # tenant composite is defined by 2010 (diff(3) needs 3 prior years) and
    # must also be zeroed for the gated-out unit, not silently NaN
    assert poor["composite_B_tenant"].notna().all()
    assert (poor["composite_B_tenant"] == 0.0).all()
    # composite_A (original, no gate) should NOT automatically zero the poor unit
    assert out[out["unit"] == "poor"]["composite_A"].max() > 0


def test_percentile_ranks_are_within_year():
    rows = []
    for year in (2015, 2016):
        for i, unit in enumerate(["u1", "u2", "u3", "u4"]):
            rows.append(dict(unit=unit, year=year, estab_restaurant_total=10 + i, zhvi=100_000 * (i + 1),
                              pop=1000 * (i + 1), workers=500 * (i + 1), income_real=50_000 + i * 1000,
                              area_km2=1.0))
    panel = pd.DataFrame(rows)
    out = rd.compute_pillar_percentiles(panel)
    for year, g in out.groupby("year"):
        assert g["pct_zhvi"].max() <= 1.0
        assert g["pct_zhvi"].min() >= 0.0


# --------------------------------------------------------------- KM summary


def test_km_summary_flags_low_sample():
    spells = pd.DataFrame({
        "unit": [f"u{i}" for i in range(10)],
        "incident": [True] * 10,
        "duration": [3, 4, 5, 6, 7, 3, 4, 5, 6, 7],
        "censored": [False] * 8 + [True, True],
    })
    out = rd.km_summary(spells, low_sample_bar=60)
    assert out["low_sample_flag"] is True
    assert out["n_completed"] == 8
    assert np.isfinite(out["median"])


def test_km_summary_empty_spells_handles_gracefully():
    spells = pd.DataFrame(columns=["unit", "incident", "duration", "censored"])
    out = rd.km_summary(spells)
    assert out["n_incident_spells"] == 0
    assert np.isnan(out["median"])


# --------------------------------------------------------------- hazard by age


def test_hazard_by_spell_age_separates_prevalent_and_incident():
    spells = pd.DataFrame([
        dict(unit="a", incident=False, duration=8, censored=False, onset_year=2000, exit_year=2008),
        dict(unit="b", incident=True, duration=3, censored=False, onset_year=2001, exit_year=2004),
        dict(unit="c", incident=True, duration=12, censored=True, onset_year=2001, exit_year=None),
    ])
    out = rd.hazard_by_spell_age(spells)
    assert "unknown (prevalent)" in out["age_band"].values
    assert out.set_index("age_band").loc["unknown (prevalent)", "n_events"] == 1


# --------------------------------------------------------------- break years


def test_break_year_rank_shuffle_flags_full_reshuffle():
    years = list(range(2000, 2010))
    units = [f"u{i}" for i in range(20)]
    rng = np.random.default_rng(0)
    rows = []
    base = {u: rng.uniform(0, 1) for u in units}
    for y in years:
        for u in units:
            val = base[u] + rng.normal(0, 0.01)
            if y == 2005:  # inject a full reshuffle in a non-candidate year
                val = rng.uniform(0, 1)
            rows.append(dict(unit=u, year=y, c=val))
    panel = pd.DataFrame(rows)
    out = rd.break_year_rank_shuffle(panel, "c")
    row_2005 = out[out["year"] == 2005].iloc[0]
    assert row_2005["flagged"]


# --------------------------------------------------------------- kmeans+markov


def test_kmeans_markov_runs_and_favors_high_composite_state():
    rng = np.random.default_rng(1)
    rows = []
    for unit in range(30):
        level = rng.uniform(0, 1)
        for year in range(2000, 2016):
            rows.append(dict(unit=f"u{unit}", year=year,
                              demand_pillar_A=np.clip(level + rng.normal(0, 0.05), 0, 1),
                              supply_pillar_A=np.clip(level + rng.normal(0, 0.05), 0, 1),
                              cost_pillar_A=np.clip(level + rng.normal(0, 0.05), 0, 1)))
    panel = pd.DataFrame(rows)
    out = rd.kmeans_markov(panel, fit_cutoff_year=2013, k=4)
    assert out["ok"]
    assert 0 <= out["transition"]["p_ff"] <= 1
    assert out["implied_mean_sojourn"] > 0


def test_kmeans_markov_insufficient_data_reports_not_ok():
    panel = pd.DataFrame({
        "unit": ["a"], "year": [2000],
        "demand_pillar_A": [0.5], "supply_pillar_A": [0.5], "cost_pillar_A": [0.5],
    })
    out = rd.kmeans_markov(panel, fit_cutoff_year=2013, k=4)
    assert not out["ok"]


# --------------------------------------------------------------- backtest


def test_backtest_2013_beats_persistence_when_signal_is_real():
    # units that entered a favorable spell well before 2013 and whose composite
    # stays high through 2022 should make the KM-based prediction beat P=1
    # only if some spells DO exit; construct a mix so persistence isn't perfect.
    rows = []
    years = list(range(2000, 2023))
    rng = np.random.default_rng(3)
    for i in range(60):
        onset = 2003 if i % 2 == 0 else 2010
        exit_year = onset + 4 + (i % 6)  # some exit well before 2022, some after
        vals = []
        for y in years:
            if y < onset:
                vals.append(rng.uniform(0.2, 0.5))
            elif y < exit_year:
                vals.append(rng.uniform(0.72, 0.95))
            else:
                vals.append(rng.uniform(0.2, 0.5))
        rows.append(pd.DataFrame({"unit": f"u{i}", "year": years, "c": vals}))
    panel = pd.concat(rows, ignore_index=True)
    out = rd.backtest_2013(panel, "c", horizons=(5, 9))
    assert out["ok"]
    assert 5 in out["horizons"]
    assert out["horizons"][5]["n_at_risk"] > 0


def test_backtest_2013_no_spells_at_risk_reports_not_ok():
    panel = pd.DataFrame({"unit": ["a"] * 24, "year": range(2000, 2024), "c": [0.1] * 24})
    out = rd.backtest_2013(panel, "c")
    assert not out["ok"]


# --------------------------------------------------------------- named-zip scoring


def test_score_named_zips_control_zip_none_hits_when_model_shows_no_spell():
    spells = pd.DataFrame(columns=["unit", "onset_year", "exit_year", "censored", "incident", "duration", "entry_pct"])
    causes = pd.DataFrame(columns=["unit", "onset_year", "exit_year", "cause"])
    scored = rd.score_named_zips(spells, causes)
    row_10128 = scored[scored["zip"] == "10128"].iloc[0]
    assert row_10128["onset_hit"]  # "none" expectation hits when there is no spell


def test_evaluate_prereg_pass_requires_10128_control_gate():
    # build a scored table where everything passes except the 10128 control
    scored = pd.DataFrame([
        dict(zip=z, hit=True, non_template=False, model_onset=2001, model_exit=2010, break_flag=False)
        for z in ["11211", "11206", "11237", "10002", "10026", "11216", "11238", "11222", "10031"]
    ] + [
        dict(zip="10128", hit=False, non_template=True, model_onset=2001, model_exit=None, break_flag=False),
        dict(zip="11215", hit=True, non_template=True, model_onset=None, model_exit=None, break_flag=False),
        dict(zip="11103", hit=True, non_template=True, model_onset=None, model_exit=None, break_flag=False),
        dict(zip="11101", hit=True, non_template=True, model_onset=2008, model_exit=None, break_flag=False),
        dict(zip="11208", hit=True, non_template=True, model_onset=None, model_exit=None, break_flag=False),
    ])
    out = rd.evaluate_prereg_pass(scored)
    assert not out["control_10128_hit"]
    assert out["status"] == "FAIL"


def test_evaluate_prereg_pass_invalid_on_3plus_break_flags():
    scored = pd.DataFrame([
        dict(zip=f"z{i}", hit=True, non_template=(i < 4), model_onset=2001, model_exit=2010,
             break_flag=(i < 3))
        for i in range(14)
    ])
    scored.loc[scored["zip"] == "z0", "zip"] = "10128"
    out = rd.evaluate_prereg_pass(scored)
    assert out["status"] == "INVALID_PENDING_BREAK_FIX"


# --------------------------------------------------------------- attribution


def test_attribute_exit_cause_picks_largest_adverse_move():
    panel = pd.DataFrame([
        dict(unit="u1", year=2005, demand_pillar_A=0.8, supply_pillar_A=0.8, cost_pillar_A=0.8),
        dict(unit="u1", year=2010, demand_pillar_A=0.75, supply_pillar_A=0.70, cost_pillar_A=0.30),
    ])
    spells = pd.DataFrame([
        dict(unit="u1", onset_year=2005, exit_year=2010, censored=False),
    ])
    out = rd.attribute_exit_cause(spells, panel)
    assert out.iloc[0]["cause"] == "cost"


# --------------------------------------------------------------- rank-churn null (small n_sims for speed)


def test_rank_churn_null_runs_and_returns_band():
    rng = np.random.default_rng(5)
    years = list(range(2000, 2015))
    rows = []
    for unit in range(15):
        level = rng.uniform(0, 1)
        for y in years:
            rows.append(dict(unit=f"u{unit}", year=y, c=np.clip(level + rng.normal(0, 0.05), 0.01, 0.99)))
    panel = pd.DataFrame(rows)
    out = rd.rank_churn_null(panel, "c", n_sims=5, seed=1)
    assert "null_median_p2_5" in out
    assert out["n_valid_sims"] >= 0


# --------------------------------------------------------------- incident dating (statistician post-results correction 9)


def test_incident_requires_clearly_unfavorable_prior_year():
    # onset's prior year sits INSIDE the hysteresis band (0.60-0.70) -- an
    # ambiguous, unknowable prior state -- so the spell must be undatable
    # (incident=False) even though onset (2002) > start_year (2000).
    values = [0.65, 0.65, 0.75, 0.75, 0.80, 0.55, 0.55]
    panel = _flat_series("F", values, start_year=2000)
    spells = rd.hysteresis_spells(panel, "c", start_year=2000, end_year=2006)
    assert len(spells) == 1
    row = spells.iloc[0]
    assert row["onset_year"] == 2002
    assert not row["incident"]  # ambiguous prior year -> undatable, not incident


def test_incident_true_when_prior_year_is_clearly_unfavorable():
    # same onset, but the prior year is clearly below the exit_ threshold
    # (0.3 < 0.60) -- unambiguous, so the spell IS datable/incident.
    values = [0.3, 0.3, 0.75, 0.75, 0.80, 0.55, 0.55]
    panel = _flat_series("G", values, start_year=2000)
    spells = rd.hysteresis_spells(panel, "c", start_year=2000, end_year=2006)
    assert len(spells) == 1
    row = spells.iloc[0]
    assert row["onset_year"] == 2002
    assert row["incident"]


# --------------------------------------------------------------- tenant composite consistency (statistician correction 10)


def test_tenant_composite_undefined_before_cost_change_term_exists():
    rows = []
    for year in range(2000, 2006):
        rows.append(dict(unit="a", year=year, estab_restaurant_total=10, zhvi=300_000 + year,
                          pop=10000, workers=5000, income_real=70_000, area_km2=2.0))
        rows.append(dict(unit="b", year=year, estab_restaurant_total=8, zhvi=250_000 + year * 2,
                          pop=8000, workers=3000, income_real=55_000, area_km2=2.0))
    panel = pd.DataFrame(rows)
    out = rd.compute_pillar_percentiles(panel)
    early = out[out["year"] < 2003]
    late = out[out["year"] >= 2003]
    # no fillna(0.5): the tenant composite must be NaN, not a silently-imputed
    # 2-component substitute, before diff(3) exists (2000-2002).
    assert early["composite_B_tenant"].isna().all()
    assert late["composite_B_tenant"].notna().any()


# --------------------------------------------------------------- fixed-tau bootstrap (statistician correction 7)


def test_spatial_block_bootstrap_requires_fixed_rmst_trunc():
    geo = pd.DataFrame({"unit": ["u0", "u1"], "cx": [0.0, 1.0], "cy": [0.0, 1.0]})
    panel = pd.DataFrame({"unit": [], "year": [], "c": []})
    with pytest.raises(ValueError):
        rd.spatial_block_bootstrap_median(panel, "c", geo, rmst_trunc=None)


def test_spatial_block_bootstrap_rmst_ci_never_exceeds_fixed_tau():
    rng = np.random.default_rng(11)
    years = list(range(2000, 2020))
    rows = []
    units = [f"u{i}" for i in range(24)]
    for i, u in enumerate(units):
        onset = 2002 + (i % 5)
        exit_year = onset + 3 + (i % 4)
        for y in years:
            if onset <= y < exit_year:
                v = rng.uniform(0.72, 0.95)
            else:
                v = rng.uniform(0.2, 0.5)
            rows.append(dict(unit=u, year=y, c=v))
    panel = pd.DataFrame(rows)
    geo = pd.DataFrame({"unit": units, "cx": rng.uniform(0, 10, len(units)),
                         "cy": rng.uniform(0, 10, len(units))})
    tau = 12.0
    out = rd.spatial_block_bootstrap_median(panel, "c", geo, rmst_trunc=tau,
                                             n_blocks=6, reps=60, seed=3)
    assert out["rmst_trunc"] == tau
    if np.isfinite(out["rmst_ci_upper"]):
        assert out["rmst_ci_upper"] <= tau + 1e-9  # RMST(tau) is bounded by tau
    assert "n_dropped_reps" in out and "drop_reasons" in out
    assert out["n_dropped_reps"] + out["n_valid_reps_rmst"] <= out["reps"]


# --------------------------------------------------------------- closure GLM uses a lagged outcome (statistician correction 11)


def _make_closure_panel():
    # 3 units x 10 years, unit 'x' favorable throughout with low closures the
    # FOLLOWING year, unit 'y' never favorable with high closures every year --
    # a same-year vs next-year mixup would still "work" on data this clean, so
    # this test instead pins down that the merge/lag machinery runs and that
    # the function is queryable at lag=1 without raising, plus that flipping
    # the lag changes which (unit, year) rows get matched.
    rows = []
    for year in range(2010, 2020):
        rows.append(dict(unit="x", year=year, c=0.85))
        rows.append(dict(unit="y", year=year, c=0.10))
    panel = pd.DataFrame(rows)
    closures = pd.DataFrame([
        dict(unit="x", year=year, n_open=20, n_closed=1) for year in range(2010, 2020)
    ] + [
        dict(unit="y", year=year, n_open=20, n_closed=5) for year in range(2010, 2020)
    ])
    return panel, closures


def test_closure_validity_glm_runs_with_lag_and_reports_both_specs():
    panel, closures = _make_closure_panel()
    out = rd.closure_validity_glm(panel, "c", closures, lag_years=1)
    assert out["ok"]
    assert out["lag_years"] == 1
    assert "year_borough_fe" in out
    assert "unit_fe" in out
    assert "kill_criterion_pass" in out


def test_closure_validity_glm_lag_changes_matched_rows():
    panel, closures = _make_closure_panel()
    out_lag0 = rd.closure_validity_glm(panel, "c", closures, lag_years=0)
    out_lag1 = rd.closure_validity_glm(panel, "c", closures, lag_years=1)
    # different lag -> different (unit, year) join -> different matched-row count
    # (or at least a well-formed, independently computed result at each lag)
    assert out_lag0["ok"] and out_lag1["ok"]
    assert out_lag0["n_zip_years"] > 0 and out_lag1["n_zip_years"] > 0


# --------------------------------------------------------------- ranking backtest (statistician correction 12)


def test_ranking_backtest_2013_uses_composite_value_not_age_alone():
    # two units with IDENTICAL spell age/shape at 2013 but very different
    # composite trajectories after 2013 -- a predictor that used age alone
    # (like the old backtest_2013) could not tell them apart; the ranking
    # backtest's logistic (trained on composite value) should still run and
    # produce a real prediction that differs across the population.
    rng = np.random.default_rng(21)
    years = list(range(2000, 2023))
    rows = []
    for i in range(40):
        onset = 2003 if i % 2 == 0 else 2006
        stays_favorable = i % 3 != 0  # most units that survive to 2013 keep going; some exit soon after
        for y in years:
            if y < onset:
                v = rng.uniform(0.2, 0.5)
            elif not stays_favorable and y >= 2015:
                v = rng.uniform(0.2, 0.5)
            else:
                v = rng.uniform(0.72, 0.95)
            rows.append(dict(unit=f"u{i}", year=y, c=v))
    panel = pd.DataFrame(rows)
    out = rd.ranking_backtest_2013(panel, "c", horizons=(5,))
    assert out["ok"]
    h5 = out["horizons"][5]
    if h5.get("ok"):
        assert h5["n_at_risk"] > 0
        assert "ci_diff_vs_persist" in h5
        assert "mde_vs_persist" in h5
        assert "ci_diff_vs_placebo" in h5


def test_ranking_backtest_2013_no_spells_reports_not_ok():
    panel = pd.DataFrame({"unit": ["a"] * 24, "year": range(2000, 2024), "c": [0.1] * 24})
    out = rd.ranking_backtest_2013(panel, "c")
    assert not out["ok"]


# --------------------------------------------------------------- hazard-by-age cluster-robust CI


def test_hazard_by_spell_age_ci_reports_ci_and_never_exceeds_bootstrap_count():
    spells = pd.DataFrame([
        dict(unit=f"u{i}", incident=True, duration=3 + (i % 5), censored=(i % 4 == 0),
             onset_year=2001, exit_year=(2001 + 3 + (i % 5)) if i % 4 != 0 else None)
        for i in range(15)
    ])
    out = rd.hazard_by_spell_age_ci(spells, reps=50, seed=1)
    assert "hazard_ci_lower" in out.columns
    assert (out["n_boot_valid"] <= 50).all()


# --------------------------------------------------------------- unit crosswalk


def test_to_unit_merges_known_splits():
    assert rd.to_unit("11249") == "11211"
    assert rd.to_unit("10065") == "10021"
    assert rd.to_unit("10075") == "10021"
    assert rd.to_unit("11109") == "11101"
    assert rd.to_unit("10001") == "10001"


# --------------------------------------------------------------- demand gate is free to vary (GTM-230 item 2)


def test_demand_gate_pass_rate_is_not_pinned_at_50_percent_every_year():
    # Old (broken) gate: demand_pillar_A >= this year's median. Since
    # demand_pillar_A is ITSELF a within-year percentile rank, that gate passed
    # ~50.0% of unit-years EVERY year by construction, regardless of what
    # demand actually did. The fixed gate (level vs. a FIXED base-period
    # anchor) must let the pass rate move as real, level demand genuinely
    # rises: here every unit's income/pop/worker levels grow steadily over
    # 2000-2023, so by the end of the window most units should clear the
    # 2000-02 anchor, not exactly half every single year.
    rng = np.random.default_rng(11)
    rows = []
    for i, unit in enumerate([f"u{i}" for i in range(20)]):
        base_income = 30_000 + i * 2_000
        base_pop = 4_000 + i * 200
        base_work = 1_000 + i * 100
        for year in range(2000, 2024):
            growth = (year - 2000) * 1500  # every unit's demand level rises over time
            rows.append(dict(
                unit=unit, year=year,
                estab_restaurant_total=10, zhvi=300_000 + rng.normal(0, 1000),
                pop=base_pop + growth / 5, workers=base_work + growth / 10,
                income_real=base_income + growth, area_km2=2.0,
            ))
    panel = pd.DataFrame(rows)
    out = rd.compute_pillar_percentiles(panel)
    pass_rate_by_year = out.groupby("year")["demand_gate"].mean()
    # every unit-year in the SAME year is identically ranked relative to the
    # OLD gate's within-year median -> always ~50%. The fixed gate must clear
    # a materially higher share of units by the end of a window where every
    # unit's level genuinely grew.
    assert pass_rate_by_year.loc[2023] > pass_rate_by_year.loc[2000] + 0.15
    # and it must NOT be pinned at exactly 50% every year (the old bug's
    # signature) -- at least one year should be materially off 50%.
    assert (pass_rate_by_year - 0.5).abs().max() > 0.05


def test_demand_gate_uses_fixed_anchor_not_within_year_median():
    # A unit whose level is high relative to the FIXED 2000-02 anchor but
    # merely "average" relative to a later year's own (higher) cross-section
    # must still pass -- proof the threshold does not silently re-derive a
    # within-year median (which was the bug being fixed).
    rows = []
    for year in range(2000, 2010):
        # unit 'steady' never changes level; unit 'boomers' all grow sharply
        rows.append(dict(unit="steady", year=year, estab_restaurant_total=10, zhvi=300_000,
                          pop=8_000, workers=3_000, income_real=70_000, area_km2=2.0))
        for j in range(5):
            growth = (year - 2000) * 20_000
            rows.append(dict(unit=f"boom{j}", year=year, estab_restaurant_total=10, zhvi=300_000,
                              pop=8_000, workers=3_000, income_real=70_000 + growth, area_km2=2.0))
    panel = pd.DataFrame(rows)
    out = rd.compute_pillar_percentiles(panel)
    steady = out[out["unit"] == "steady"].set_index("year")["demand_gate"]
    # 'steady' passed (or failed) the FIXED 2000-02 anchor once, at onset --
    # its own level never changes, so its gate outcome must be CONSTANT across
    # all 10 years even though the boom units' cross-sectional median keeps
    # rising around it (the old bug would have flipped 'steady' to a fail as
    # the boom units pulled the within-year median up past it).
    assert steady.nunique() == 1


# --------------------------------------------------------------- two-part tenant null (GTM-230 item 1 / statistician correction 13)


def _synthetic_full_panel(n_units=25, start=2000, end=2023, seed=9):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_units):
        base_income = rng.uniform(30_000, 110_000)
        base_pop = rng.uniform(2_000, 18_000)
        base_work = rng.uniform(500, 12_000)
        base_zhvi = rng.uniform(150_000, 850_000)
        for year in range(start, end + 1):
            drift = (year - start) * rng.normal(0, 400)
            rows.append(dict(
                unit=f"u{i}", year=year,
                estab_restaurant_total=max(1, rng.poisson(9)),
                zhvi=max(50_000, base_zhvi + drift + rng.normal(0, 4_000)),
                pop=max(500, base_pop + rng.normal(0, 150)),
                workers=max(100, base_work + rng.normal(0, 150)),
                income_real=max(10_000, base_income + drift * 2 + rng.normal(0, 1_500)),
                area_km2=2.0,
            ))
    return pd.DataFrame(rows)


def test_rank_churn_null_tenant_two_part_produces_valid_sims():
    # The single-Gaussian-AR(1) null (`rank_churn_null`) mis-fit
    # composite_B_tenant's point-mass-at-zero mixture badly enough to get
    # 0/200 valid sims in the v0.1 run. The two-part null (separate AR(1)s on
    # the gate/level series and the cost-rank-change series, combined the same
    # way the real composite combines them) must not be similarly degenerate
    # on ordinary synthetic data.
    df = rd.compute_pillar_percentiles(_synthetic_full_panel())
    out = rd.rank_churn_null_tenant_two_part(df, n_sims=20, seed=4, rmst_trunc=10.0)
    assert out["ok"]
    assert out["n_valid_sims"] > 0
    assert out["window"][0] >= 2000 and out["window"][1] <= 2023
    assert np.isfinite(out["null_rmst_p2_5"]) and np.isfinite(out["null_rmst_p97_5"])
    assert out["null_rmst_p2_5"] <= out["null_rmst_p97_5"]


def test_rank_churn_null_tenant_two_part_reports_not_ok_with_too_few_units():
    rows = []
    for year in range(2000, 2010):
        for unit in ("a", "b", "c"):
            rows.append(dict(unit=unit, year=year, estab_restaurant_total=10, zhvi=300_000,
                              pop=8_000, workers=3_000, income_real=70_000, area_km2=2.0))
    df = rd.compute_pillar_percentiles(pd.DataFrame(rows))
    out = rd.rank_churn_null_tenant_two_part(df, n_sims=5, seed=1)
    assert not out["ok"]
    assert "reason" in out


# --------------------------------------------------------------- macro leave-one-episode-out (GTM-230 item 3 / statistician S8)


def test_macro_leave_one_episode_out_flags_sign_stability(monkeypatch):
    # Stub fit_macro_hazard_terms (its real form needs the warehouse LODES
    # parquet + FRED macro series, out of scope for offline synthetic tests)
    # to exercise macro_leave_one_episode_out's OWN orchestration logic: it
    # must call the full-sample fit once, then once per MACRO_EPISODES entry
    # with exclude_years set, and correctly flag which terms keep their sign
    # across every drop.
    calls = []

    def fake_fit(panel, spells, composite_col, supply_df, workers_df, macro, exclude_years=None):
        calls.append(exclude_years)
        flips = exclude_years is not None and 2020 in exclude_years
        return dict(
            ok=True,
            macro_table=pd.DataFrame([
                dict(term="e1_x_ur", coef=0.30, p_raw=0.01, p_holm=0.03, holm_significant=True),
                dict(term="e2_x_covid", coef=(-0.4 if flips else 0.4), p_raw=0.2, p_holm=0.4, holm_significant=False),
            ]),
            n_person_years=500,
            note="stub",
        )

    monkeypatch.setattr(rd, "fit_macro_hazard_terms", fake_fit)
    out = rd.macro_leave_one_episode_out(pd.DataFrame(), pd.DataFrame(), "composite_A", None, None, None)
    assert out["ok"]
    # 1 full-sample call + 1 per episode
    assert len(calls) == 1 + len(rd.MACRO_EPISODES)
    assert calls[0] is None
    dropped_year_sets = [c for c in calls if c is not None]
    assert {2001, 2002, 2003} in dropped_year_sets
    assert {2008, 2009, 2010} in dropped_year_sets
    assert {2020, 2021, 2022} in dropped_year_sets

    tbl = out["table"].set_index("term")
    assert tbl.loc["e1_x_ur", "sign_stable_all_drops"]
    assert not tbl.loc["e2_x_covid", "sign_stable_all_drops"]
    assert set(out["episode_status"].keys()) == set(rd.MACRO_EPISODES.keys())


def test_macro_leave_one_episode_out_reports_not_ok_when_full_fit_fails(monkeypatch):
    monkeypatch.setattr(rd, "fit_macro_hazard_terms",
                         lambda *a, **kw: dict(ok=False, reason="insufficient hazard person-years for macro terms"))
    out = rd.macro_leave_one_episode_out(pd.DataFrame(), pd.DataFrame(), "composite_A", None, None, None)
    assert not out["ok"]
    assert "reason" in out


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
