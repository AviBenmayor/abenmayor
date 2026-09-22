"""Tests for the carrying-capacity model (src/loci/model/carrying_capacity.py).

Three things are pinned here, and they are the three that would be expensive to
discover from a report:

  1. THE NAICS MAPPING IS REUSED, NOT RE-DERIVED (D42). The national puller must
     read `src/loci/zbp_naics.yaml` through `loci.zbp` and nothing else; a second
     crosswalk anywhere would let the NYC and national halves of the same table
     be counting different businesses.
  2. THE GATE ACTUALLY REFUSES. On synthetic data generated from a proportional
     law, no saturating form may ship; on data generated from a known Hill
     curve, the fit must recover it. A gate that only ever accepts is not a gate.
  3. THE CLI OUTPUT CONTRACT. `capacity()` returns a header row plus one row per
     category with a fixed key set, refuses to invent a curve when the fitted
     file is absent, and flags an out-of-support query rather than extrapolating
     silently.
"""
from __future__ import annotations

import math
import pathlib

import numpy as np
import pytest
import yaml

from loci.categories import CATEGORIES
from loci.model import carrying_capacity as cc
from loci.sources.universal import census_cbp_national as national
from loci.zbp import load_zbp_naics

RNG = np.random.default_rng(7)


# ---------------------------------------------------------------------------
# 1. the NAICS mapping is REUSED (D42)
# ---------------------------------------------------------------------------

def test_national_puller_reuses_the_one_naics_crosswalk():
    """`naics_codes()` must be exactly the flattened zbp_naics.yaml -- same
    codes, same category assignment, nothing added and nothing dropped."""
    expected = {str(e["naics"]): cat
                for cat, entries in load_zbp_naics().items()
                for e in entries}
    assert national.naics_codes() == expected
    assert set(national.naics_codes().values()) <= set(CATEGORIES)


def test_no_second_naics_mapping_is_defined_in_the_module():
    """A literal 6-digit NAICS code in the national puller would be a second
    crosswalk in the making. The only ones allowed are inside the docstring,
    where they are probe evidence rather than a mapping."""
    import inspect
    import re

    src = inspect.getsource(national)
    body = src.split('"""', 2)[2] if src.count('"""') >= 2 else src
    # strip nested docstrings/comments before looking for bare codes
    body = re.sub(r'""".*?"""', "", body, flags=re.DOTALL)
    body = re.sub(r"#.*", "", body)
    literals = re.findall(r"[\"'](\d{6})[\"']", body)
    assert literals == [], (
        f"6-digit NAICS literals in census_cbp_national.py: {literals}. "
        "The crosswalk lives in src/loci/zbp_naics.yaml (D42) and is read "
        "through loci.zbp.load_zbp_naics().")


def test_every_category_reaches_the_national_side():
    """A category silently missing from the crosswalk would come back as zero
    establishments in every metro, which is indistinguishable from a real
    finding that nobody in America runs one."""
    covered = set(national.naics_codes().values())
    assert covered == set(CATEGORIES), f"missing: {set(CATEGORIES) - covered}"


# ---------------------------------------------------------------------------
# 2. the forms, the loss and the gate
# ---------------------------------------------------------------------------

def test_hill_is_numerically_safe_at_absurd_parameters():
    """The naive `emax*h**b/(k**b+h**b)` overflows to nan here; the shipped
    spelling must return finite numbers so the optimiser cannot be silently
    stopped by a nan objective."""
    h = np.array([1.0, 1e3, 2.6e4])
    for p in ([700.0, 300.0, 40.0], [-700.0, -300.0, 0.01]):
        mu = cc.predict("hill", p, h, h / 0.27)
        assert np.all(np.isfinite(mu)) and np.all(mu > 0)


def test_hill_reduces_to_michaelis_menten_at_b_equals_one():
    h = np.geomspace(10, 20_000, 50)
    emax, k = 40.0, 5_000.0
    hill = cc.predict("hill", [math.log(emax), math.log(k), 1.0], h, h)
    mm = cc.predict("michaelis_menten", [math.log(emax), math.log(k)], h, h)
    assert np.allclose(hill, mm, rtol=1e-9)


def test_collapse_preserves_the_counts_it_is_weighting():
    h = RNG.uniform(500, 20_000, 40_000)
    d = h / 0.27
    y = RNG.poisson(h * 0.002).astype(float)
    hc, dc, nc, yc = cc.collapse(h, d, y)
    assert nc.sum() == len(h)
    assert yc.sum() == pytest.approx(y.sum())
    assert len(hc) < len(h) / 5          # it actually collapsed
    assert np.all(np.isfinite(hc)) and np.all(np.isfinite(dc))


def test_collapsed_fit_matches_the_uncollapsed_one():
    """The collapsing is an efficiency device, not a modelling choice: the
    parameters it recovers must match a fit on the raw rows."""
    h = RNG.uniform(500, 20_000, 20_000)
    d = h / 0.27
    y = RNG.poisson(0.0015 * h).astype(float)
    p_collapsed, _ = cc.fit_form("proportional", h, d, y)
    # closed form for the proportional Poisson MLE: a = sum(y)/sum(h)
    a_exact = y.sum() / h.sum()
    assert math.exp(p_collapsed[0]) == pytest.approx(a_exact, rel=5e-3)


def test_poisson_nll2_is_minimised_at_the_truth():
    y = np.array([3.0, 5.0, 8.0])
    n = np.ones(3)
    truth = np.array([3.0, 5.0, 8.0])
    best = cc.poisson_nll2(y, n, truth)
    for off in (0.5, 1.5, 2.0):
        assert cc.poisson_nll2(y, n, truth * off) > best


def _synthetic(mu_fn, n_ntas=40, per_nta=400):
    """A panel with real NTA blocks, so the fold machinery is exercised."""
    nta = np.repeat([f"NTA{i:03d}" for i in range(n_ntas)], per_nta)
    shed = 0.27
    residents = RNG.uniform(1_000, 20_000, n_ntas * per_nta)
    density = residents / shed
    mu = mu_fn(residents)
    y = RNG.poisson(mu).astype(float)
    return residents, density, y, nta


def test_gate_refuses_saturation_when_the_truth_is_proportional():
    """THE LOAD-BEARING TEST. Data generated with a constant per-capita rate
    must not produce a saturating curve -- otherwise every category in the
    report 'saturates' and the word means nothing."""
    import pandas as pd

    x, d, y, nta = _synthetic(lambda r: 0.0015 * r)
    addr = pd.DataFrame({"residents": x, "residents_km2": d, "nta_code": nta,
                         "shed_km2": 0.27})
    rec = cc.fit_category("synthetic", addr, y, bootstrap=0)
    assert rec["fitted"]
    assert rec["form"] == "proportional", rec["cv"]
    assert rec["saturates"] is False
    assert rec["flatten_residents"] is None
    e = rec["elasticity_at"]["p50"]["residents_fixed_area"]
    assert e == pytest.approx(1.0, abs=0.02)


def test_gate_accepts_and_recovers_a_real_saturating_curve():
    import pandas as pd

    emax, k, b = 30.0, 6_000.0, 1.0

    def mu(r):
        return emax * r ** b / (k ** b + r ** b)

    x, d, y, nta = _synthetic(mu)
    addr = pd.DataFrame({"residents": x, "residents_km2": d, "nta_code": nta,
                         "shed_km2": 0.27})
    rec = cc.fit_category("synthetic", addr, y, bootstrap=0)
    assert rec["saturates"] is True
    assert rec["form"] in ("michaelis_menten", "hill", "hill_density")
    # the elasticity must FALL as the catchment grows -- that is what saturation
    # means, and it is the claim the report makes
    e = rec["elasticity_at"]
    assert e["p10"]["residents_fixed_area"] > e["p90"]["residents_fixed_area"]
    assert e["p90"]["residents_fixed_area"] < 0.9


def test_relative_gain_is_measured_on_a_positive_scale():
    """A regression pin. The gate compares forms by relative improvement, so the
    score must be the true deviance (>= 0) and not the freely-negative nll2 --
    a negative denominator inverts the comparison and passes the losers."""
    x, d, y, nta = _synthetic(lambda r: 0.0015 * r)
    folds = cc.nta_folds(nta)
    scores = cc.cv_score("proportional", x, d, y, folds)
    assert all(v >= 0 for v in scores), scores


def test_nta_folds_never_split_a_neighborhood():
    nta = np.repeat([f"N{i}" for i in range(23)], 50)
    folds = cc.nta_folds(nta, n_folds=5)
    assert sum(len(f) for f in folds) == len(nta)
    seen: dict[str, int] = {}
    for i, idx in enumerate(folds):
        for code in np.unique(nta[idx]):
            assert seen.setdefault(code, i) == i, f"{code} appears in two folds"


def test_marginal_holds_area_fixed_not_density():
    """Pinned because the two give different answers and only one answers the
    owner's question: one more person on the same block RAISES density."""
    params = [math.log(30.0), math.log(6_000.0), 1.0]
    m = cc.marginal("hill", params, [5_000.0], 0.27)
    up = cc.predict("hill", params, [5_001.0], [5_001.0 / 0.27])[0]
    dn = cc.predict("hill", params, [4_999.0], [4_999.0 / 0.27])[0]
    assert m[0] == pytest.approx((up - dn) / 2.0)


def test_params_at_bound_names_a_pinned_parameter():
    h = np.array([1_000.0, 10_000.0])
    y = np.array([1.0, 4.0])
    bounds = cc._bounds("hill", h, y)
    pinned = [bounds[0][1], bounds[1][0], 1.0]      # log_emax sits on its ceiling
    assert "emax" in cc._params_at_bound("hill", pinned, h, y)
    assert cc._params_at_bound("proportional", [-5.0], h, y) == []


# ---------------------------------------------------------------------------
# 3. the national half
# ---------------------------------------------------------------------------

def test_national_rate_forms_are_finite_at_extremes():
    d = np.array([1.0, 1e3, 7e4])
    for form, p in (("constant_rate", [-3.0]), ("rate_power", [-3.0, 3.0]),
                    ("rate_hill", [800.0, 400.0, 50.0])):
        r = cc.national_rate(form, p, d)
        assert np.all(np.isfinite(r)) and np.all(r > 0)


def test_metro_table_uses_population_weighted_density():
    """Two ZCTAs, one tiny-and-dense and one huge-and-empty. A land-area density
    would call the metro sparse; the population-weighted one must not, because
    almost everybody lives in the dense ZCTA."""
    import pandas as pd

    rows = []
    for zipc, pop, area in (("11211", 90_000, 3.0), ("11999", 10_000, 900.0)):
        for cat in ("grocery", "bar"):
            rows.append({"zipcode": zipc, "cbsa": "99999", "cbsa_name": "Test",
                         "county_fips": "36047", "population": pop,
                         "households": pop / 2.5, "median_hh_income": 60_000,
                         "land_km2": area, "density": pop / area,
                         "category": cat, "estab": 10.0})
    mt = cc.metro_table(pd.DataFrame(rows))
    naive = 100_000 / 903.0
    assert mt["weighted_density"].iloc[0] > 20 * naive
    # 10 groceries in each of the two ZCTAs, 100,000 residents between them
    assert mt["grocery_per_1000"].iloc[0] == pytest.approx(20.0 / 100.0)


def test_nearest_metros_excludes_the_target_and_ranks_by_distance():
    import pandas as pd

    metros = pd.DataFrame({
        "cbsa": ["35620", "A", "B"],
        "cbsa_name": ["New York", "Near", "Far"],
        "population": [19e6, 5e6, 2e6],
        "weighted_density": [9_500.0, 9_000.0, 400.0],
        **{f"{c}_per_1000": [1.0, 1.05, 0.2] for c in CATEGORIES},
    })
    out = cc.nearest_metros(metros, "35620", k=2)
    assert list(out["cbsa"]) == ["A", "B"]
    assert "35620" not in set(out["cbsa"])


# ---------------------------------------------------------------------------
# 4. the CLI output contract
# ---------------------------------------------------------------------------

def _tiny_fit() -> dict:
    return {
        "version": 1,
        "categories": {
            "grocery": {
                "category": "grocery", "fitted": True, "form": "power",
                "saturates": True,
                "params": {"a": 1e-4, "b": 1.2},
                "params_ci90": {"a": [8e-5, 1.2e-4], "b": [1.1, 1.3]},
                # three NTA block-bootstrap draws in optimiser coordinates
                "bootstrap": {"n_draws": 3, "draws": [
                    [math.log(9e-5), 1.18], [math.log(1e-4), 1.20],
                    [math.log(1.1e-4), 1.22]]},
                "residents_p01": 1_000.0, "residents_p99": 20_000.0,
            },
            "bar": {"category": "bar", "fitted": False, "reason": "too few"},
        },
        "national": {"grocery": {"fitted": True, "form": "rate_power",
                                 "params": {"r0": 0.12, "b": 0.35},
                                 "held_out_metro": {
                                     "ratio_observed_over_predicted": 1.6}}},
        "cbp_poi_ratio": {"grocery": {"ratio_aggregate": 1.9}},
    }


def test_capacity_row_contract():
    rows = cc.capacity(10_000, 22_500, fit=_tiny_fit())
    head, body = rows[0], rows[1:]
    assert set(head) >= {"residents", "density_residents_km2",
                         "implied_walkshed_km2", "in_support_walkshed", "caveat"}
    assert "not a maximum" in head["caveat"].lower() or "not what" in head["caveat"].lower()
    g = next(r for r in body if r["category"] == "grocery")
    assert set(g) >= {"expected", "ci90", "per_1000_residents",
                      "national_per_1000_residents", "nyc_vs_national_ratio",
                      "cbp_per_poi_ratio", "in_support_residents", "form"}
    assert g["expected"] > 0
    # the point estimate must lie INSIDE its own interval -- the regression this
    # pins is a prediction interval built from componentwise parameter bounds,
    # which put hair_barber's 25.3 outside [5.2, 22.7] on the first run
    assert g["ci90"][0] <= g["expected"] <= g["ci90"][1]
    assert g["per_1000_residents"] == pytest.approx(g["expected"] / 10.0)
    assert g["national_per_1000_residents"] == pytest.approx(
        0.12 * (22_500 / cc.D_REF) ** 0.35)
    b = next(r for r in body if r["category"] == "bar")
    assert b["fitted"] is False and "reason" in b


def test_capacity_flags_an_out_of_support_query_rather_than_extrapolating():
    """A suburban density implies a walkshed of several square kilometres, which
    is not a 400 m walk. The number still prints -- refusing outright would be
    unhelpful -- but it must be labelled."""
    suburban = cc.capacity(10_000, 700, fit=_tiny_fit())
    assert suburban[0]["in_support_walkshed"] is False
    assert suburban[0]["implied_walkshed_km2"] > cc.SHED_KM2_SUPPORT[1]
    urban = cc.capacity(10_000, 37_000, fit=_tiny_fit())
    assert urban[0]["in_support_walkshed"] is True
    far = cc.capacity(400_000, 37_000, fit=_tiny_fit())
    assert next(r for r in far[1:]
                if r["category"] == "grocery")["in_support_residents"] is False


def test_capacity_refuses_to_default_when_the_fit_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        cc.load_fit(tmp_path / "nope.yaml")
    assert "--fit" in str(exc.value)


def test_repack_is_the_inverse_of_unpack():
    for form in cc.FORMS:
        raw = [0.3 * (i + 1) for i in range(len(cc.FORMS[form].params))]
        assert cc._repack(form, cc.unpack(form, raw)) == pytest.approx(raw)


# ---------------------------------------------------------------------------
# 5. the shipped fitted file, when it exists
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not cc.YAML_PATH.exists(),
                    reason="carrying_capacity.yaml not fitted in this checkout")
def test_shipped_fit_is_internally_consistent():
    doc = yaml.safe_load(cc.YAML_PATH.read_text())
    # GTM-198 (owner 2026-09-17): bathhouse_sauna has no capacity fit until the
    # first ingest on the announced hash; the file carries a fit_hash, so a
    # hand row is impossible by construction. Exact unfitted set, on purpose.
    # brewery joins the set D137 (2026-09-22), same reason.
    assert set(CATEGORIES) - set(doc["categories"]) == {"bathhouse_sauna", "brewery"}
    assert set(doc["categories"]) <= set(CATEGORIES)
    assert doc["fit_hash"] == cc.fit_hash(doc)
    for cat, rec in doc["categories"].items():
        if not rec.get("fitted"):
            assert rec.get("reason"), f"{cat}: refused without a reason"
            continue
        assert rec["form"] in cc.FORMS
        assert set(rec["params"]) == {
            p.removeprefix("log_") for p in cc.FORMS[rec["form"]].params}
        # a category the gate refused ENTIRELY must be the straight line
        if not rec["beats_proportional"]:
            assert rec["form"] == cc.BASELINE_FORM
        # ...and a category not CALLED saturating must carry no flattening claim.
        # These are two different conditions: a curved form can win the gate by
        # ACCELERATING, which is a real finding and not a saturation.
        if not rec["saturates"]:
            assert rec["flatten_residents"] is None
        assert rec["shape"] in ("saturating", "accelerating", "proportional",
                                "undetermined")


@pytest.mark.skipif(not cc.YAML_PATH.exists(),
                    reason="carrying_capacity.yaml not fitted in this checkout")
def test_shipped_fit_header_warns_before_the_numbers():
    text = pathlib.Path(cc.YAML_PATH).read_text()
    assert text.startswith("#")
    head = text.split("version:")[0].lower()
    for phrase in ("not a maximum", "proportional", "block"):
        assert phrase in head, f"the generated header stopped saying {phrase!r}"
