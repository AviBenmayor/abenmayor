"""Tests for the density-elasticity coefficient (D68 -> GTM-138).

The load-bearing ones are the recovery tests (a synthetic panel with a KNOWN
positive and a KNOWN negative beta must come back with those signs) and the
placebo gate (a beta that sits inside its own placebo distribution must be
refused, never rounded up to a regime). Everything else pins the contract the
grade will read.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from loci.model import density_elasticity as de

REPO = de.REPO_ROOT


# ------------------------------------------------------------------ fixtures

def synthetic_panel(betas: dict[str, float], n_zips: int = 90, seed: int = 7,
                    noise: float = 0.05) -> pd.DataFrame:
    """A ZIP x category panel whose true log-form coefficient is `betas[cat]`.

    Built forward: draw a 2013 count and population, set 2023 so that
    log growth = beta * log(density_2013) + controls + noise. The controls are
    given real variance so the design is not singular, and the ZIPs are laid
    out on a grid so the Conley kernel and Moran's I have a geometry to run on.
    """
    rng = np.random.default_rng(seed)
    side = int(np.ceil(np.sqrt(n_zips)))
    lon = -73.99 + 0.02 * (np.arange(n_zips) % side)
    lat = 40.68 + 0.02 * (np.arange(n_zips) // side)
    pop13 = rng.uniform(8_000, 90_000, n_zips)
    pop23 = pop13 * rng.uniform(0.95, 1.35, n_zips)
    inc13 = rng.uniform(35_000, 160_000, n_zips)
    inc23 = inc13 * rng.uniform(0.9, 1.6, n_zips)
    boro = np.where(np.arange(n_zips) % 2 == 0, "MN", "BK")
    zips = [f"1{i:04d}" for i in range(n_zips)]

    rows = []
    for cat, beta in betas.items():
        e13 = rng.integers(1, 120, n_zips).astype(float)
        dens = 1000.0 * (e13 + 1.0) / pop13
        g = (beta * np.log(dens) + 0.3 * np.log(pop23 / pop13)
             + rng.normal(0, noise, n_zips))
        e23 = np.maximum(0.0, np.round((e13 + 1.0) * np.exp(g) - 1.0))
        rows.append(pd.DataFrame({
            "zipcode": zips, "borough": boro, "lon": lon, "lat": lat,
            "pop13": pop13, "inc13": inc13, "pop23": pop23, "inc23": inc23,
            "category": cat, "estab13": e13, "estab23": e23}))
    panel = pd.concat(rows, ignore_index=True)
    panel["d_estab"] = panel.estab23 - panel.estab13
    panel["g_log"] = np.log((panel.estab23 + 1.0) / (panel.estab13 + 1.0))
    panel["dens13"] = 1000.0 * (panel.estab13 + 1.0) / panel.pop13
    panel["log_dens13"] = np.log(panel.dens13)
    panel["dens13_level"] = 1000.0 * panel.estab13 / panel.pop13
    panel["dlog_pop"] = np.log(panel.pop23 / panel.pop13)
    panel["log_pop13"] = np.log(panel.pop13)
    panel["log_inc13"] = np.log(panel.inc13)
    panel["dlog_inc"] = np.log(panel.inc23 / panel.inc13)
    panel["bk"] = (panel.borough == "BK").astype(float)
    return panel


@pytest.fixture(scope="module")
def recovered() -> dict:
    """One estimate of the log form on a panel with known signs."""
    panel = synthetic_panel({"clusterer": +0.40, "saturator": -0.40, "flat": 0.0})
    cats = de.estimate_form(panel, ["clusterer", "saturator", "flat"], "log",
                            de.CONLEY_BANDWIDTH_M)
    return {"panel": panel, "cats": cats}


# ----------------------------------------------------- sign recovery (core)

def test_recovers_known_positive_beta(recovered):
    v = recovered["cats"]["clusterer"]
    assert v["beta"] > 0, "a panel built with beta = +0.40 came back negative"
    assert v["beta"] == pytest.approx(0.40, abs=0.10)
    assert v["t_conley"] > de.T_GATE


def test_recovers_known_negative_beta(recovered):
    v = recovered["cats"]["saturator"]
    assert v["beta"] < 0, "a panel built with beta = -0.40 came back positive"
    assert v["beta"] == pytest.approx(-0.40, abs=0.10)
    assert v["t_conley"] < -de.T_GATE


def test_known_signs_become_the_two_regimes(recovered):
    assert recovered["cats"]["clusterer"]["regime"] == "clustering"
    assert recovered["cats"]["saturator"]["regime"] == "saturating"


def test_flat_category_is_not_forced_into_a_sign(recovered):
    """A category built with beta = 0 must land in `no_signal`. The failure
    this guards is the one the ticket names: never force a sign."""
    assert recovered["cats"]["flat"]["regime"] == "no_signal"
    assert recovered["cats"]["flat"]["not_classified_because"]


def test_level_form_recovers_the_same_signs():
    panel = synthetic_panel({"clusterer": +0.40, "saturator": -0.40})
    cats = de.estimate_form(panel, ["clusterer", "saturator"], "level",
                            de.CONLEY_BANDWIDTH_M)
    assert cats["clusterer"]["beta"] > 0
    assert cats["saturator"]["beta"] < 0


# ------------------------------------------------------------- placebo gate

def test_placebo_gate_refuses_a_beta_inside_the_placebo_distribution():
    """The whole point of T3. A beta that is no larger than what OTHER
    categories' 2013 density delivers is generic ZIP growth, and must be
    classified `no_signal` however clean its own t-statistic is."""
    regime, fails = de.classify(beta=0.30, t_conley=9.9, lozo_stability=1.0,
                                placebo_p90=0.55)
    assert regime == "no_signal"
    assert any(f.startswith("T3") for f in fails)


def test_placebo_gate_admits_a_beta_that_beats_the_distribution():
    regime, fails = de.classify(beta=0.60, t_conley=3.0, lozo_stability=1.0,
                                placebo_p90=0.55)
    assert (regime, fails) == ("clustering", [])


def test_classify_refuses_when_the_placebo_never_ran():
    regime, fails = de.classify(beta=9.0, t_conley=99.0, lozo_stability=1.0,
                                placebo_p90=None)
    assert regime == "no_signal"
    assert any("placebo did not run" in f for f in fails)


def test_classify_reads_the_conley_t_not_the_hc3_one():
    """A coefficient that is significant only on the optimistic SE is not
    classified. HC3 is reported; the gate never reads it."""
    assert de.classify(1.0, t_conley=1.2, lozo_stability=1.0,
                       placebo_p90=0.1)[0] == "no_signal"


def test_classify_refuses_an_unstable_sign():
    regime, fails = de.classify(0.9, t_conley=5.0, lozo_stability=0.70,
                                placebo_p90=0.1)
    assert regime == "no_signal"
    assert any(f.startswith("T2") for f in fails)


def test_placebo_is_compared_on_standardized_coefficients():
    """Raw betas are not comparable across placebo categories in the level
    form (the units are the placebo category's own density scale), so T3 reads
    beta_std. A raw comparison would be passed here and a standardized one
    failed -- the test pins which one runs."""
    regime, _ = de.classify(beta=100.0, t_conley=9.0, lozo_stability=1.0,
                            placebo_p90=2.0, beta_std=0.5)
    assert regime == "no_signal"


# --------------------------------------------------------- the shipping gate

def _fake_cats(regimes: dict[str, str]) -> dict:
    """Betas alternate in sign so the unanimity criterion (d) is not what these
    fixtures are testing -- each test isolates one criterion."""
    return {c: {"regime": r, "placebo": {"p90": 0.1, "n": 14},
                "beta": 1.0 if i % 2 == 0 else -1.0}
            for i, (c, r) in enumerate(regimes.items())}


def test_form_gate_does_not_require_a_clustering_verdict():
    """Relaxed 2026-09-11. Demanding a `clustering` category forced a sign at
    the portfolio level -- the exact failure the per-category placebo exists to
    prevent -- and on the real panel it discarded eight sound saturating
    verdicts because no category clusters. This test pins the relaxation so it
    cannot be silently reverted."""
    assert de.form_gate_failures(
        _fake_cats({"a": "saturating", "b": "no_signal", "c": "no_signal"})) == []


def test_form_gate_passes_with_all_three_regimes():
    assert de.form_gate_failures(_fake_cats(
        {"a": "clustering", "b": "saturating", "c": "no_signal"})) == []


def test_form_gate_refuses_an_all_null_table():
    """Everything `no_signal` is a null result, not a coefficient table."""
    bad = de.form_gate_failures(_fake_cats({"a": "no_signal", "b": "no_signal"}))
    assert any("signal regime" in f for f in bad)


def test_form_gate_refuses_a_unanimous_sign_symmetrically():
    """The diagnostic that actually demotes the log form. It is symmetric: an
    all-POSITIVE table is refused exactly as an all-negative one is, so it
    forces no sign and is not a disguised requirement for a clustering
    verdict."""
    allneg = {c: {"regime": r, "placebo": {"p90": 0.1, "n": 14}, "beta": -1.0}
              for c, r in {"a": "saturating", "b": "no_signal",
                           "c": "saturating"}.items()}
    allpos = {c: {**v, "beta": +1.0} for c, v in allneg.items()}
    for cats in (allneg, allpos):
        assert any("cannot all reward" in f for f in de.form_gate_failures(cats))
    mixed = {**allneg, "d": {"regime": "clustering", "beta": +1.0,
                             "placebo": {"p90": 0.1, "n": 14}}}
    assert de.form_gate_failures(mixed) == []


def test_form_gate_refuses_a_regime_outside_the_allowed_set():
    cats = _fake_cats({"a": "saturating", "b": "no_signal"})
    cats["b"]["regime"] = "probably_clustering"
    assert any("outside" in f for f in de.form_gate_failures(cats))


def test_form_gate_requires_the_placebo_to_have_run():
    cats = _fake_cats({"a": "clustering", "b": "saturating", "c": "no_signal"})
    cats["a"]["placebo"] = {"p90": None, "n": 0}
    assert any("placebo did not run" in f for f in de.form_gate_failures(cats))


def test_log_form_is_preferred_and_level_is_the_fallback():
    """The preference order is pre-stated, so promoting the level form is
    auditable rather than form-shopping after the fact."""
    assert de.FORM_ORDER == ("log", "level")
    ok = _fake_cats({"a": "clustering", "b": "saturating", "c": "no_signal"})
    bad = _fake_cats({"a": "no_signal", "b": "no_signal"})
    assert de.choose_form({"log": {"categories": ok}, "level": {"categories": bad}})[0] \
        == "log"
    assert de.choose_form({"log": {"categories": bad}, "level": {"categories": ok}})[0] \
        == "level"
    assert de.choose_form({"log": {"categories": bad}, "level": {"categories": bad}})[0] \
        is None


def test_write_is_refused_when_no_form_is_admissible(tmp_path):
    """Gates first, write second: a failed re-fit must leave the previous YAML
    exactly as it was."""
    out = tmp_path / "density_elasticity.yaml"
    out.write_text("categories: {previous: {regime: clustering}}\n")
    result = {"adopted_form": None,
              "form_gate": {"log": ["no category classified `clustering`"],
                            "level": ["no category classified `clustering`"]},
              "forms": {}, "categories": {}}
    with pytest.raises(de.DensityElasticityGateFailure):
        de.write_if_gate_passes({}, result, path=out)
    assert yaml.safe_load(out.read_text())["categories"]["previous"]["regime"] \
        == "clustering"


# --------------------------------------------------------------- round trip

def _document(panel: pd.DataFrame) -> dict:
    result = de.estimate(panel, de.CONLEY_BANDWIDTH_M)
    return de.to_document(result, panel, {2013: {"path": "x"}, 2023: {"path": "y"}}), result


def test_yaml_round_trip(tmp_path):
    # six categories, not three: the gate requires the placebo to have run on
    # at least three comparisons, and each category's placebo set is every
    # OTHER category.
    panel = synthetic_panel({"clusterer": +0.40, "saturator": -0.40, "flat": 0.0,
                             "flat2": 0.0, "flat3": 0.0, "flat4": 0.0})
    doc, result = _document(panel)
    assert result["adopted_form"] == "log"
    out = de.write_if_gate_passes(doc, result, path=tmp_path / "de.yaml")
    back = de.load(out)
    assert back["adopted_form"] == "log"
    assert de.regime("clusterer", back) == "clustering"
    assert de.regime("saturator", back) == "saturating"
    assert de.regime("flat", back) == "no_signal"
    assert back["categories"]["clusterer"]["beta"] == pytest.approx(
        doc["categories"]["clusterer"]["beta"])
    # the header explaining what this is NOT must survive the write
    text = out.read_text()
    assert "NOT A FORECAST" in text and "ZIP GRAIN" in text
    assert "fitted_on" in back["categories"]["clusterer"]


def test_regime_raises_on_unknown_category():
    doc = {"categories": {"bar": {"regime": "clustering"}}}
    assert de.regime("bar", doc) == "clustering"
    with pytest.raises(ValueError, match="no density-elasticity entry"):
        de.regime("definitely_not_a_category", doc)


def test_zip_universe_hash_is_order_independent_and_content_sensitive():
    assert de.zip_universe_hash(["11211", "10003"]) == \
        de.zip_universe_hash(["10003", "11211"])
    assert de.zip_universe_hash(["11211", "10003"]) != de.zip_universe_hash(["11211"])


# --------------------------------------------------------------- drift tests

def _slugs() -> list[str]:
    return sorted(yaml.safe_load(
        (de.PKG_ROOT / "categories.yaml").read_text())["categories"])


def test_every_category_slug_gets_an_entry_or_an_explicit_reason():
    """Drift guard, on the MECHANISM rather than on a fitted file: every slug
    in categories.yaml must come out of `to_document` either with a coefficient
    or with a `not_fitted_because` string. A slug that silently vanishes from
    the document is the GTM-109 defect -- a caller cannot tell "no coefficient"
    from "typo"."""
    slugs = _slugs()
    panel = synthetic_panel({s: (+0.4 if i == 0 else -0.4 if i == 1 else 0.0)
                             for i, s in enumerate(slugs)}, n_zips=60)
    # starve one slug of base-year presence so the not-fitted branch is exercised
    starved = slugs[-1]
    panel.loc[panel.category == starved, "estab13"] = 0.0
    panel.loc[panel.category == starved, "dens13_level"] = 0.0
    doc, _ = _document(panel)
    for slug in slugs:
        assert slug in doc["categories"], f"{slug} vanished from the document"
        entry = doc["categories"][slug]
        assert entry["regime"] in {"clustering", "saturating", "no_signal", "not_fitted"}
        if entry["regime"] == "not_fitted":
            assert entry["not_fitted_because"], f"{slug} not fitted without a reason"
    assert doc["categories"][starved]["regime"] == "not_fitted"


def test_shipped_yaml_covers_every_category_slug():
    doc = de.load()
    for slug in _slugs():
        assert slug in doc["categories"], f"{slug} has no density-elasticity entry"
        entry = doc["categories"][slug]
        if entry["regime"] == "not_fitted":
            assert entry.get("not_fitted_because")
        else:
            assert entry["n_zips"] >= de.MIN_ZIPS
            assert entry["regime"] in {"clustering", "saturating", "no_signal"}


def test_shipped_yaml_records_the_d68_supersession_and_the_gate_relaxation():
    """The header has to carry both, or a later reader re-litigates D68."""
    text = de.YAML_PATH.read_text()
    assert "SUPERSEDES D68" in text
    assert "GATE HISTORY" in text
    assert "NOT A FORECAST" in text


def test_shipped_yaml_is_the_level_form_with_a_recorded_reason():
    """The log form is the stated primary; it is demoted only by failing its
    own gate, and the reason must be in the file."""
    doc = de.load()
    assert doc["adopted_form"] in de.FORM_ORDER
    if doc["adopted_form"] == "level":
        assert doc["forms_rejected"]["log"], "the log form was demoted without a reason"


def test_combined_food_retail_series_is_declared():
    """The 2017 NAICS 445110->445120 recode moves bodegas between grocery and
    convenience across the two vintages, so the combined series must exist."""
    assert de.COMBINED_SERIES["food_retail"] == ("grocery", "convenience")


def test_controls_include_both_population_terms_and_borough_fe():
    assert set(de.CONTROLS) == {"dlog_pop", "log_pop13", "log_inc13", "dlog_inc", "bk"}


# ------------------------------------------------------------------- Moran's I

def test_morans_i_detects_a_spatially_clustered_residual():
    rng = np.random.default_rng(3)
    n = 64
    lon = -73.99 + 0.02 * (np.arange(n) % 8)
    lat = 40.68 + 0.02 * (np.arange(n) // 8)
    xy = de._to_utm(lon, lat)
    clustered = lat * 100 + rng.normal(0, 0.01, n)
    noise = rng.normal(0, 1, n)
    assert de.morans_i(clustered, xy, permutations=199)["i"] > 0.3
    assert de.morans_i(noise, xy, permutations=199)["p_perm"] > 0.05
