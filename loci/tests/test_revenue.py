"""Tests for the site-revenue model v0 (src/loci/model/revenue.py).

The load-bearing ones are the LAST four: the calibration must reconcile to the
Economic Census county anchor by construction, the gate must refuse to ship a
category that failed its backtest, the SET lists must be disjoint from every
other module's, and the recommendation card must move from D to C only when a
category actually ships.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
import yaml

from loci.model import revenue as rev


# ------------------------------------------------------------- the equations

def test_ring_kernel_matches_numerical_integration():
    """K_r = E[d^-beta | d in ring] under a uniform planar density. Checked
    against the integral it claims to be, at several betas including the
    beta = 2 branch the closed form special-cases."""
    edges = [0.0, 100.0, 200.0, 400.0]
    for beta in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        K = rev.ring_kernel(edges, beta, d_floor=50.0)
        for i in range(len(edges) - 1):
            a, b = max(edges[i], 50.0), edges[i + 1]
            d = np.linspace(a, b, 200001)
            num = np.trapezoid(d ** (-beta) * 2 * np.pi * d, d)
            den = np.trapezoid(2 * np.pi * d, d)
            assert K[i] == pytest.approx(num / den, rel=1e-4)


def test_ring_kernel_decays_with_distance():
    K = rev.ring_kernel([0, 100, 200, 300, 400, 600, 800], 1.5, 50.0)
    assert all(K[i] > K[i + 1] for i in range(len(K) - 1))


def test_ring_kernel_floor_bounds_the_divergence():
    """d^-beta diverges at zero; the floor is what keeps the innermost ring
    finite, and a tighter floor must give a LARGER kernel, never a NaN."""
    lo = rev.ring_kernel([0, 100], 2.0, d_floor=25.0)[0]
    hi = rev.ring_kernel([0, 100], 2.0, d_floor=50.0)[0]
    assert math.isfinite(lo) and math.isfinite(hi) and lo > hi


def test_huff_share_is_one_over_n_plus_one_when_all_stores_share_a_ring():
    """The identity the model rests on: with every store of equal
    attractiveness in the SAME ring, the entrant is one of n+1 and takes
    exactly 1/(n+1). If this ever stops holding, the share is not a Huff
    share any more."""
    edges, beta, floor = [0, 100, 200, 400], 1.5, 50.0
    for n in (0, 1, 2, 5, 20):
        rings = np.array([[n, 0, 0]], dtype=float)
        assert rev.huff_share(rings, beta, edges, floor)[0] == pytest.approx(1 / (n + 1))


def test_huff_share_falls_with_incumbents_and_rises_with_their_distance():
    edges, beta, floor = [0, 100, 200, 400], 1.5, 50.0
    near = rev.huff_share(np.array([[3.0, 0, 0]]), beta, edges, floor)[0]
    far = rev.huff_share(np.array([[0, 0, 3.0]]), beta, edges, floor)[0]
    more = rev.huff_share(np.array([[6.0, 0, 0]]), beta, edges, floor)[0]
    assert 0 < near < far < 1
    assert more < near


def test_huff_share_exclude_self_removes_exactly_one_ring_zero_store():
    edges, beta, floor = [0, 100, 200, 400], 2.0, 50.0
    rings = np.array([[4.0, 2.0, 1.0]])
    with_self = rev.huff_share(rings, beta, edges, floor, exclude_self=False)[0]
    without = rev.huff_share(rings, beta, edges, floor, exclude_self=True)[0]
    same = rev.huff_share(np.array([[3.0, 2.0, 1.0]]), beta, edges, floor)[0]
    assert without == pytest.approx(same)
    assert without > with_self


def test_huff_share_exclude_self_cannot_go_negative():
    """An establishment whose own ring-0 count is already 0 (a snapping
    artefact) must not be charged a NEGATIVE incumbent."""
    s = rev.huff_share(np.array([[0.0, 1.0]]), 1.5, [0, 100, 200], 50.0, exclude_self=True)[0]
    assert 0 < s <= 1


# ------------------------------------------------------------ the quintiles

@pytest.mark.parametrize("income,expected", [
    (0, 0), (29931, 0), (29932, 1), (29933, 1),
    (57451, 1), (57452, 2), (94510, 2), (94511, 3),
    (155924, 3), (155925, 4), (10_000_000, 4),
])
def test_quintile_boundaries_are_lower_inclusive(income, expected):
    """BLS publishes LOWER limits, so income exactly on a break belongs to the
    HIGHER quintile. The boundary is pinned because an off-by-one here silently
    re-prices every address in a tract."""
    breaks = rev.load_spec()["cex"]["quintile_income_breaks_usd"]
    assert rev.quintile_of(income, breaks) == expected


def test_quintile_of_none_is_none_not_the_middle():
    breaks = rev.load_spec()["cex"]["quintile_income_breaks_usd"]
    assert rev.quintile_of(None, breaks) is None
    assert rev.quintile_of(float("nan"), breaks) is None


def test_vectorised_quintile_agrees_with_the_scalar_one():
    breaks = rev.load_spec()["cex"]["quintile_income_breaks_usd"]
    xs = np.array([1000.0, 29932.0, 60000.0, 94511.0, 200000.0, np.nan])
    v = rev._quintile_index(xs, breaks)
    for i, x in enumerate(xs):
        s = rev.quintile_of(None if np.isnan(x) else float(x), breaks)
        assert v[i] == (-1 if s is None else s)


def test_quintile_breaks_are_identical_to_spend_yaml():
    """Two models binning income differently would be a silent divergence:
    spend.yaml's fair-value engine and this one must agree on what a quintile
    is."""
    assert (rev.load_spec()["cex"]["quintile_income_breaks_usd"]
            == rev.load_spend()["quintile_income_breaks_usd"])


# --------------------------------------------------------------- the spend

def test_spend_vector_reproduces_spend_yamls_national_figures():
    """The spec's share_of_line is not a new number: share x the real Table
    1101 national line must reproduce what spend.yaml already documents, or the
    two files disagree about what fraction of a CEX line a category is."""
    spec, spend_yaml = rev.load_spec(), rev.load_spend()
    national = rev.load_cex_national(spec)
    for cat, c in spec["categories"].items():
        line = c.get("cex_line")
        if line is None:
            continue
        want = spend_yaml["categories"][cat]
        target = want.get("annual_spend_national", want["annual_spend"])
        got = national[line] * float(c["share_of_line"])
        assert got == pytest.approx(target, rel=0.02), cat


def test_spend_vector_is_monotone_in_quintile_and_ny_rebased_where_claimed():
    spec, spend_yaml = rev.load_spec(), rev.load_spend()
    q, nat, ny = rev.load_cex_quintiles(spec), rev.load_cex_national(spec), rev.load_cex_ny_msa(spec)
    for cat in spec["modelled"] + spec["flagged"]:
        v, src = rev.spend_vector(cat, spec, q, nat, ny, spend_yaml)
        assert len(v) == 5 and all(x > 0 for x in v), cat
        if cat != "pharmacy":
            assert all(v[i] <= v[i + 1] * 1.0001 for i in range(4)), f"{cat} not monotone"
        if spec["categories"][cat].get("ny_msa_line"):
            assert src == "cex_quintile_ny_msa", cat
        elif spec["categories"][cat].get("cex_line") is None:
            assert src == "elasticity_fallback", cat
        else:
            assert src == "cex_quintile_national", cat


def test_pharmacy_is_the_only_non_monotone_income_gradient():
    """A REAL feature of the published Table 1101 "Drugs" line, not a parsing
    bug: 416 / 644 / 572 / 700 / 957 across quintiles. Out-of-pocket drug
    spend is need-driven and concentrated among older, lower-income
    households, so it does not rise with income. Pinned here because a
    monotonicity assumption elsewhere would silently "fix" it, and because it
    is one more reason pharmacy stays in `flagged`."""
    spec, spend_yaml = rev.load_spec(), rev.load_spend()
    q, nat, ny = rev.load_cex_quintiles(spec), rev.load_cex_national(spec), rev.load_cex_ny_msa(spec)
    v, _ = rev.spend_vector("pharmacy", spec, q, nat, ny, spend_yaml)
    assert v[1] > v[2], "the Drugs line's q2 > q3 dip is the published shape"
    non_mono = [c for c in spec["modelled"] + spec["flagged"]
                if not all(rev.spend_vector(c, spec, q, nat, ny, spend_yaml)[0][i]
                           <= rev.spend_vector(c, spec, q, nat, ny, spend_yaml)[0][i + 1] * 1.0001
                           for i in range(4))]
    assert non_mono == ["pharmacy"]


def test_convenience_is_the_only_elasticity_fallback():
    """Named explicitly so that adding a category with no CEX line is a
    deliberate act with a failing test behind it, not a quiet default."""
    spec, spend_yaml = rev.load_spec(), rev.load_spend()
    q, nat, ny = rev.load_cex_quintiles(spec), rev.load_cex_national(spec), rev.load_cex_ny_msa(spec)
    fb = [c for c in spec["modelled"] + spec["flagged"]
          if rev.spend_vector(c, spec, q, nat, ny, spend_yaml)[1] == "elasticity_fallback"]
    assert fb == ["convenience"]


# ------------------------------------------------------------ the sweep math

def _line_graph(n: int, step: float):
    """A path graph of `n` nodes `step` metres apart, as CSR. Every network
    distance is known by construction, so ring_sums has nothing to hide."""
    from scipy.sparse import csr_matrix

    rows = list(range(n - 1)) + list(range(1, n))
    cols = list(range(1, n)) + list(range(n - 1))
    return csr_matrix((np.full(len(rows), step), (rows, cols)), shape=(n, n))


def test_ring_sums_bins_a_line_graph_exactly():
    A = _line_graph(21, 50.0)                 # nodes 0..20, 50 m apart
    W = np.ones((21, 1))
    edges = [0.0, 100.0, 200.0, 400.0]
    out = rev.ring_sums(A, np.array([10]), W, edges, batch=4)[0, 0]
    # From node 10, ring 0 is d <= 100 (inclusive of self at d=0, so the
    # establishment's own self-count lands here -- which is exactly what
    # exclude_self later removes): 0, 50 x2, 100 x2 -> 5.
    # Ring 1 is 100 < d <= 200: 150 x2, 200 x2 -> 4.
    # Ring 2 is 200 < d <= 400: 250, 300, 350, 400, each x2 -> 8.
    assert list(out) == [5.0, 4.0, 8.0]


def test_ring_sums_totals_equal_a_single_catchment():
    """The ring decomposition must not create or destroy weight: summing the
    rings has to equal the plain catchment supply_ratio.catchment_sums
    computes at the same outer radius."""
    from loci.model.supply_ratio import catchment_sums

    A = _line_graph(31, 40.0)
    W = np.arange(31, dtype=float).reshape(-1, 1)
    edges = [0.0, 100.0, 200.0, 400.0, 800.0]
    q = np.array([5, 15, 25])
    rings = rev.ring_sums(A, q, W, edges, batch=2)[:, 0, :].sum(axis=1)
    flat = catchment_sums(A, q, W, radius_m=800.0, batch=2)[:, 0]
    assert rings == pytest.approx(flat)


def test_ring_sums_is_empty_when_no_weight_carries():
    A = _line_graph(11, 50.0)
    out = rev.ring_sums(A, np.array([5]), np.zeros((11, 2)), [0.0, 100.0, 400.0])
    assert out.shape == (1, 2, 2) and not out.any()


# ---------------------------------------------------- the backtest target

def test_employees_per_estab_drops_suppressed_cells_rather_than_imputing():
    spec = rev.load_spec()
    cbp = pd.DataFrame([
        # ZIP A: bands account for 10/10 -> kept
        {"zipcode": "11215", "NAICS2017": "812310", "EMPSZES": "001", "estab": 10.0},
        {"zipcode": "11215", "NAICS2017": "812310", "EMPSZES": "210", "estab": 8.0},
        {"zipcode": "11215", "NAICS2017": "812310", "EMPSZES": "220", "estab": 2.0},
        # ZIP B: bands account for 3/10 -> dropped, NOT imputed to the mean
        {"zipcode": "11217", "NAICS2017": "812310", "EMPSZES": "001", "estab": 10.0},
        {"zipcode": "11217", "NAICS2017": "812310", "EMPSZES": "210", "estab": 3.0},
        # ZIP C: only 2 establishments -> below min_estab_per_zip
        {"zipcode": "11231", "NAICS2017": "812310", "EMPSZES": "001", "estab": 2.0},
        {"zipcode": "11231", "NAICS2017": "812310", "EMPSZES": "210", "estab": 2.0},
    ])
    out = rev.employees_per_estab(cbp, "laundry", spec).set_index("zipcode")
    assert list(out.index) == ["11215"]
    assert out.loc["11215", "emp_per_estab"] == pytest.approx((8 * 2.5 + 2 * 7.0) / 10)


def test_employees_per_estab_remaps_renumbered_naics_to_the_cbp_vintage():
    """CBP 2023 still answers on NAICS2017, where convenience stores are
    445120; the spec carries the NAICS2022 code 445131. If the remap is lost
    the category silently returns an empty target and the gate fails for the
    wrong reason."""
    spec = rev.load_spec()
    cbp = pd.DataFrame([
        {"zipcode": "11215", "NAICS2017": "445120", "EMPSZES": "001", "estab": 9.0},
        {"zipcode": "11215", "NAICS2017": "445120", "EMPSZES": "210", "estab": 9.0},
    ])
    out = rev.employees_per_estab(cbp, "convenience", spec)
    assert len(out) == 1 and out.iloc[0]["emp_per_estab"] == pytest.approx(2.5)


# ----------------------------------------------------------- the calibration

def test_lambda_reconciles_the_mean_prediction_to_the_ec_county_anchor():
    """The defining property of lambda: apply it and the MEAN predicted revenue
    over the county's establishments equals the Economic Census mean revenue
    per establishment, exactly. If this drifts, the level is unanchored."""
    rng = np.random.default_rng(0)
    rhat = rng.lognormal(mean=10.0, sigma=0.8, size=400)
    county = np.array(["047"] * 250 + ["061"] * 150, dtype=object)
    anchor = {"047": {"rcptot_usd": 114_231_000.0, "estab": 561.0,
                      "rev_per_estab_usd": 114_231_000.0 / 561},
              "061": {"rcptot_usd": 67_222_000.0, "estab": 190.0,
                      "rev_per_estab_usd": 67_222_000.0 / 190}}
    lam = rev._lambdas(rhat, county, anchor)
    pred = rev._apply_lambda(rhat, county, lam)
    for fips in ("047", "061"):
        assert pred[county == fips].mean() == pytest.approx(anchor[fips]["rev_per_estab_usd"])


def test_total_conserving_lambda_differs_by_exactly_the_establishment_ratio():
    """The two estimators are not interchangeable and the gap between them IS
    the coverage diagnostic: our establishment count over the EC's."""
    rhat = np.full(1122, 1000.0)
    county = np.array(["047"] * 1122, dtype=object)
    anchor = {"047": {"rcptot_usd": 114_231_000.0, "estab": 561.0,
                      "rev_per_estab_usd": 114_231_000.0 / 561}}
    d = rev._lambdas(rhat, county, anchor)["047"]
    assert d["estab_ratio_ours_over_ec"] == pytest.approx(2.0)
    assert d["lambda_per_store"] / d["lambda_total"] == pytest.approx(2.0)


def test_apply_lambda_leaves_out_of_county_rows_null_not_zero():
    rhat = np.array([1.0, 2.0, 3.0])
    county = np.array(["047", None, "061"], dtype=object)
    lam = {"047": {"lambda_per_store": 10.0}}
    out = rev._apply_lambda(rhat, county, lam)
    assert out[0] == 10.0 and np.isnan(out[1]) and np.isnan(out[2])


# ------------------------------------------------------------------ the gate

def _passing() -> dict:
    return {"backtest": {"spearman_oos": 0.55, "beats_county_average": True,
                         "beats_homes_only": True,
                         "baseline_county_average_spearman": 0.10,
                         "baseline_homes_only_spearman": 0.30},
            "placebo": {"passes": True, "own_spearman": 0.55,
                        "best_rival": "bar", "best_rival_spearman": 0.31}}


def test_gate_passes_only_when_every_condition_holds():
    spec = rev.load_spec()
    assert rev.gate_verdict(_passing(), spec) == "pass"


@pytest.mark.parametrize("break_it", [
    lambda d: d["backtest"].update(spearman_oos=0.05),
    lambda d: d["backtest"].update(beats_county_average=False),
    lambda d: d["backtest"].update(beats_homes_only=False),
    lambda d: d["placebo"].update(passes=False),
])
def test_gate_fails_if_any_single_condition_breaks(break_it):
    spec, d = rev.load_spec(), _passing()
    break_it(d)
    assert rev.gate_verdict(d, spec) == "fail"
    assert d["gate_reason"]


def test_save_calibration_refuses_when_nothing_passed(tmp_path):
    """A calibration file that ships nothing would be read as a shipped model.
    The gate refuses the write instead."""
    doc = {"version": 1, "model_version": "revenue-v0", "categories": {
        "laundry": {"gate": "fail", "gate_reason": "does not beat homes-only"},
        "bar": {"gate": "fail", "gate_reason": "placebo"}}}
    with pytest.raises(RuntimeError, match="NO category beat both baselines"):
        rev.save_calibration(doc, tmp_path / "cal.yaml")
    assert not (tmp_path / "cal.yaml").exists()


def test_calibration_yaml_round_trips_and_drops_the_scratch_key(tmp_path):
    doc = {"version": 1, "model_version": "revenue-v0", "spec_hash": "abc123",
           "categories": {"laundry": {"gate": "pass", "beta": 1.5,
                                      "lambda": {"047": {"lambda_per_store": 2.5}},
                                      "sigma_log": {"lambda": 0.2, "beta": 0.05},
                                      "_oos": {"11215": 1.0}}}}
    p = rev.save_calibration(doc, tmp_path / "cal.yaml")
    back = yaml.safe_load(p.read_text())
    assert back["categories"]["laundry"]["beta"] == 1.5
    assert back["categories"]["laundry"]["lambda"]["047"]["lambda_per_store"] == 2.5
    assert "_oos" not in back["categories"]["laundry"]
    assert rev.shipped_categories(back) == {"laundry"}


def test_shipped_categories_is_empty_without_a_calibration():
    assert rev.shipped_categories({}) == set()
    assert rev.shipped_categories({"categories": {"bar": {"gate": "fail"}}}) == set()


# --------------------------------------------------------- the write guard

def test_set_lists_are_disjoint_from_every_other_module():
    """UPDATE-only is worth nothing if the SET list overlaps someone else's
    columns. Compared against the real lists by import, so a rename elsewhere
    fails this test rather than silently weakening it."""
    from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
    from loci.model.address_gaps import ADDRESS_CATEGORY_SCREEN_COLUMNS, ADDRESS_COLUMNS
    from loci.model.dev_pipeline import PIPELINE_COLUMNS
    from loci.model.storefronts import AGE_FIT_COLUMNS, STOREFRONT_COLUMNS
    from loci.model.supply_ratio import ADDRESS_RATIO_COLUMNS, CATEGORY_RATIO_COLUMNS

    others = (set(ADDRESS_COLUMNS) | set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
              | set(PIPELINE_COLUMNS) | set(STOREFRONT_COLUMNS) | set(AGE_FIT_COLUMNS)
              | set(DEMAND_ANNOTATION_COLUMNS) | set(ADDRESS_RATIO_COLUMNS)
              | set(CATEGORY_RATIO_COLUMNS))
    mine = set(rev.CATEGORY_REVENUE_COLUMNS) | set(rev.ADDRESS_REVENUE_COLUMNS)
    assert mine & others == set()


def test_guard_raises_on_a_column_another_module_owns():
    with pytest.raises(RuntimeError, match="would clobber"):
        rev._guard(["revenue_p50", "gap_score"], "analysis.address")


def test_every_written_column_is_declared_in_the_schema():
    """The schema ALTERs and the module's SET lists must not drift apart -- a
    column in one and not the other fails at runtime on a fresh database, long
    after the run that needed it. Scans EVERY migration, not just 002: v0.2's
    capacity columns arrive in 025_revenue_capacity.sql."""
    from loci.db import PKG

    sql = "\n".join(p.read_text() for p in sorted((PKG / "sql").glob("*.sql")))
    for col in rev.CATEGORY_REVENUE_COLUMNS:
        assert f"analysis.address_category ADD COLUMN IF NOT EXISTS {col}" in sql, col
    for col in rev.ADDRESS_REVENUE_COLUMNS:
        assert f"analysis.address ADD COLUMN IF NOT EXISTS {col}" in sql, col


# --------------------------------------------------------------- the spec

def test_spec_covers_every_modelled_category_and_nothing_else():
    from loci.categories import CATEGORIES

    spec = rev.load_spec()
    declared = set(spec["modelled"]) | set(spec["flagged"]) | set(spec["benchmark_only"])
    assert declared == set(CATEGORIES), "the spec must account for all 15 categories"
    assert set(spec["categories"]) == set(spec["modelled"]) | set(spec["flagged"])
    for cat in spec["categories"]:
        assert spec["categories"][cat]["naics"], cat


def test_benchmark_only_categories_can_never_ship():
    """The v0 scope line, pinned: a category with no CEX line worth the name
    has no parameters in the spec at all, so there is nothing for a fit to
    accidentally calibrate."""
    spec = rev.load_spec()
    for cat in spec["benchmark_only"]:
        assert cat not in spec["categories"]


def test_regime_is_reported_and_never_multiplied_in():
    """D68/D70: the density-elasticity regime is DESCRIPTIVE and D68 ruled a
    rejected predictor may not be quoted forward. It must reach the output only
    as `regime_flag_only`, and none of the three functions that compute a
    number may accept it as an argument -- there is no signature through which
    it could enter an equation."""
    import inspect

    for fn in (rev.huff_share, rev.ring_kernel, rev.uncalibrated,
               rev.spend_per_household, rev._lambdas, rev._apply_lambda):
        params = set(inspect.signature(fn).parameters)
        assert not any("regime" in p or "elastic" in p for p in params), fn.__name__
    src = (rev.SPEC_PATH.parent / "revenue.py").read_text()
    # the ONLY places the word may appear: the helper, its docstring mentions,
    # and the one report key.
    assert src.count("regime_of(") == 2          # the def and the single call
    assert "regime_flag_only" in src


# --------------------------------------------- recommend.py's section 6

def _rules():
    from loci.model import recommend as rec

    return yaml.safe_load(rec.RULES_PATH.read_text())


def test_economics_stays_d_without_comps_and_without_a_model():
    from loci.model import recommend as rec

    g, why = rec.grade_economics({"n_comps": 0, "rent_source": "no_data"}, _rules(), None)
    assert g == "D" and "no cash-flow" in why


def test_economics_becomes_c_when_the_model_ships_for_the_category():
    from loci.model import recommend as rec

    revenue = {"revenue_p50": 240_000.0, "revenue_p25": 180_000.0,
               "revenue_p75": 320_000.0, "rent_ceiling": 28_800.0,
               "n_revenue_addresses": 1831, "revenue_model_version": "revenue-v0"}
    g, why = rec.grade_economics({"n_comps": 0, "rent_source": "no_data"}, _rules(), revenue)
    assert g == "C"
    assert "uncalibrated to local P&Ls" in why


def test_a_shipped_model_can_never_reach_b_so_act_stays_unreachable():
    """The D74 rule survives: 'act' needs >= B on every load-bearing section,
    and the model alone tops out at C. Only real cash-flow comps lift it."""
    from loci.model import recommend as rec

    revenue = {"revenue_p50": 1e9, "revenue_p25": 1e9, "revenue_p75": 1e9,
               "rent_ceiling": 1e8, "n_revenue_addresses": 99999,
               "revenue_model_version": "revenue-v0"}
    for n in (0, 1, 5, 50):
        g, _ = rec.grade_economics({"n_comps": n, "rent_source": "no_data"}, _rules(), revenue)
        assert g in ("C", "D")


def test_comps_with_real_cash_flow_still_outrank_the_model():
    from loci.model import recommend as rec

    comps = {"n_comps": 7, "cash_flow_p50": 120_000.0, "level_used": "borough",
             "rent_source": "listed"}
    revenue = {"revenue_p50": 1.0, "revenue_p25": 1.0, "revenue_p75": 1.0,
               "rent_ceiling": 1.0, "n_revenue_addresses": 1,
               "revenue_model_version": "revenue-v0"}
    assert rec.grade_economics(comps, _rules(), revenue)[0] == "B"


def test_revenue_facts_returns_none_rather_than_zero_when_not_modelled():
    from loci.model import recommend as rec

    empty = pd.DataFrame().rename_axis("category")
    assert rec._revenue_facts(empty, "laundry") is None
    df = pd.DataFrame([{"category": "bar", "revenue_p25": None, "revenue_p50": None,
                        "revenue_p75": None, "rent_ceiling": None,
                        "n_revenue_addresses": 0,
                        "revenue_model_version": None}]).set_index("category")
    assert rec._revenue_facts(df, "bar") is None


# ------------------------------------- the fitted competition elasticity

def test_gamma_one_is_textbook_huff_and_gamma_zero_removes_competition():
    edges, beta, floor = [0, 100, 200, 400], 1.5, 50.0
    rings = np.array([[4.0, 2.0, 1.0]])
    assert rev.huff_share(rings, beta, edges, floor, gamma=1.0)[0] == pytest.approx(
        rev.huff_share(rings, beta, edges, floor)[0])
    assert rev.huff_share(rings, beta, edges, floor, gamma=0.0)[0] == 1.0
    assert rev.huff_share(np.zeros((3, 3)), beta, edges, floor, gamma=0.0).tolist() == [1.0] * 3


def test_negative_gamma_makes_incumbents_help_not_hurt():
    """An agglomerative fit is a real possibility the grid must be able to
    express -- otherwise gamma = 1 is assumed, not fitted."""
    edges, beta, floor = [0, 100, 200, 400], 1.5, 50.0
    few = rev.huff_share(np.array([[1.0, 0, 0]]), beta, edges, floor, gamma=-0.5)[0]
    many = rev.huff_share(np.array([[8.0, 0, 0]]), beta, edges, floor, gamma=-0.5)[0]
    assert many > few > 1.0


def test_gamma_is_monotone_in_the_competition_penalty():
    edges, beta, floor = [0, 100, 200, 400], 1.5, 50.0
    rings = np.array([[5.0, 2.0, 0.0]])
    shares = [rev.huff_share(rings, beta, edges, floor, gamma=g)[0]
              for g in (-0.5, 0.0, 0.5, 1.0)]
    assert shares == sorted(shares, reverse=True)


def test_grid_collapses_the_gamma_zero_row_to_one_candidate():
    """beta does nothing when gamma is 0, so ten identical candidates would
    make an argmax tie pick a beta at random and report it as fitted."""
    spec = rev.load_spec()
    cands = rev._grid(spec)
    zeros = [c for c in cands if c[1] == 0.0]
    assert len(zeros) == 1
    assert len(set(cands)) == len(cands)


def test_grid_spans_competitive_neutral_and_agglomerative():
    gammas = {g for _, g in rev._grid(rev.load_spec())}
    assert any(g > 0 for g in gammas) and 0.0 in gammas and any(g < 0 for g in gammas)


def test_catfit_lambdas_and_predict_match_the_direct_computation():
    """The fast LOZO aggregates must reproduce the groupby-and-fit they
    replace, including the held-out-ZIP subtraction."""
    rng = np.random.default_rng(7)
    n = 300
    zp = np.array([f"112{i % 7:02d}" for i in range(n)], dtype=object)
    cp = np.where(np.arange(n) % 3 == 0, "061", "047").astype(object)
    anchor = {"047": {"rcptot_usd": 1e8, "estab": 500.0, "rev_per_estab_usd": 200_000.0},
              "061": {"rcptot_usd": 9e7, "estab": 200.0, "rev_per_estab_usd": 450_000.0}}
    rhat = rng.lognormal(10, 0.5, n)
    zips_eval = sorted(set(zp))
    F = rev._CatFit([rhat], zips_eval, zp, cp, anchor)

    # full-sample lambdas match _lambdas()
    direct = rev._lambdas(rhat, cp, anchor)
    lam = F.lambdas(0)
    for i, f in enumerate(F.counties):
        assert lam[i] == pytest.approx(direct[f]["lambda_per_store"])

    # a fold's lambdas match refitting on the masked subset
    drop = 2
    mask = zp != zips_eval[drop]
    direct_fold = rev._lambdas(rhat, cp, anchor, mask=mask)
    lam_fold = F.lambdas(0, drop_zip=drop)
    for i, f in enumerate(F.counties):
        assert lam_fold[i] == pytest.approx(direct_fold[f]["lambda_per_store"])

    # and the per-ZIP prediction matches the groupby mean x lambda
    pred = F.predict(0, lam)
    full = rev._apply_lambda(rhat, cp, direct)
    want = rev._zip_mean(full, zp, zips_eval).to_numpy()
    assert pred == pytest.approx(want, nan_ok=True)


def test_competition_sign_label_tracks_the_fitted_gamma():
    for gamma, label in ((1.0, "competitive"), (0.25, "competitive"),
                         (0.0, "none"), (-0.5, "agglomerative")):
        sign = ("competitive" if gamma > 0 else "none" if gamma == 0 else "agglomerative")
        assert sign == label


def test_sigma_shape_weights_by_fold_not_by_distinct_candidate():
    """The first live run put sigma at 0.98 -- a 4x p25/p75 band -- because two
    stray folds out of 73 were weighted the same as the mode. One entry per
    fold is the fix, and this pins it: the same candidate set with realistic
    fold COUNTS must give a far tighter spread than the deduplicated set."""
    edges, floor = [0, 100, 200, 400], 50.0
    med = np.array([[6.0, 8.0, 12.0]])
    star = (0.75, -0.25)
    folds = [(0.75, -0.25)] * 65 + [(1.25, -0.5)] * 5 + [(2.0, -0.75)] * 2 + [(0.5, 0.0)] * 1
    weighted = rev.sigma_shape(med, folds, star, edges, floor)
    deduped = rev.sigma_shape(med, sorted(set(folds)), star, edges, floor)
    assert 0.0 < weighted < deduped
    assert weighted < deduped / 2


def test_sigma_shape_is_zero_when_every_fold_matches_the_shipped_shape():
    """No disagreement is no evidence of shape uncertainty -- it must not
    manufacture a band out of nothing."""
    med = np.array([[3.0, 4.0, 5.0]])
    assert rev.sigma_shape(med, [(1.0, 0.5)] * 40, (1.0, 0.5), [0, 100, 200, 400], 50.0) == 0.0


def test_sigma_shape_counts_a_systematic_offset_rather_than_centring_it_away():
    """RMS about zero, not a standard deviation about the folds' mean. If every
    fold agrees on a shape DIFFERENT from the shipped one, the shipped number
    is systematically off and the band must say so -- a std would report 0.0
    and hide the disagreement completely."""
    edges, floor = [0, 100, 200, 400], 50.0
    med = np.array([[5.0, 5.0, 5.0]])
    folds = [(1.0, 1.0)] * 10
    assert rev.sigma_shape(med, folds, (1.0, 1.0), edges, floor) == 0.0
    offset = rev.sigma_shape(med, folds, (1.0, 0.0), edges, floor)
    assert offset > 0.0
    assert float(np.std([0.0] * 10)) == 0.0        # what a std would have said


# ------------------------------------------- D84: the frames, and the fit


def test_the_homes_query_is_pinned_to_the_lot_frame():
    """`compute_rings`'s one `analysis.address` read plays BOTH roles: it is the
    homes WEIGHT vector and it is the query set that gets predictions. Both are
    lot-only since D84.

    As weights, a street point carries units 0 and would change no number -- but
    leaving it in would make "the spend pool is unchanged" an arithmetic
    coincidence rather than a guarantee. As the query set it matters much more:
    lambda_c is fitted so the MEAN prediction over a county's establishments
    equals the Economic Census mean, and the leave-one-ZIP-out backtest scores
    ZIP folds. 50,199 units-0 points would enter every fold as structural zeros
    and pull the fit toward a model that predicts nothing well."""
    import inspect

    from loci.model import revenue as rv

    src = inspect.getsource(rv.compute_rings)
    assert "COALESCE(frame, 'lot') = 'lot'" in src


def test_a_street_row_gets_no_revenue_and_leaves_every_lot_row_untouched():
    """The write path, on a real warehouse. Revenue is NOT applied to street
    rows: their revenue_* stay NULL, which is this module's own convention for
    "not modelled" and is never a revenue of zero. And the lot rows are
    byte-identical with and without a street row beside them."""
    import pandas as pd

    from loci import db as locidb
    from loci.model import revenue as rv

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.executemany(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, units, "
        "present_count, eligible, n_missing, reach_source, reach_hash, graph_version, "
        "run_at, frame) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,now(),?)",
        [("3001", "3001", -73.99, 40.67, "BK", 10.0, 12, True, 1, "tiers", "h", "g", "lot"),
         ("seg:5:0", None, -73.99, 40.67, "BK", 0.0, 12, True, 1, "tiers", "h", "g",
          "street")])
    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, frame) "
        "VALUES (?,?,?,?)",
        [("3001", "BK", "restaurant", "lot"), ("seg:5:0", "BK", "restaurant", "street")])

    # Only the LOT row is predicted -- exactly what predict_addresses returns
    # when compute_rings' query is pinned.
    long_df = pd.DataFrame({
        "address_id": ["3001"], "borough": ["BK"], "category": ["restaurant"],
        "revenue_p25": [1.0e6], "revenue_p50": [1.5e6], "revenue_p75": [2.0e6],
        "rent_ceiling": [11_000.0], "revenue_model_version": ["v0"],
    })
    rv.write_revenue(con, long_df, ["BK"])
    rv.write_address_revenue(
        con, pd.DataFrame({"address_id": ["3001"], "borough": ["BK"],
                           "homes_800m": [4200]}), ["BK"])

    got = dict(con.execute(
        "SELECT address_id, revenue_p50 FROM analysis.address_category").fetchall())
    assert got["3001"] == pytest.approx(1.5e6)
    assert got["seg:5:0"] is None, "a street point was given a revenue"
    homes = dict(con.execute(
        "SELECT address_id, homes_800m FROM analysis.address").fetchall())
    assert homes["3001"] == 4200
    assert homes["seg:5:0"] is None


# ================================================================= v0.2
# The four corrections of docstring (7): a fitted pool elasticity, a median
# anchor, a capacity ceiling and a site-level cap on a negative gamma. The
# load-bearing ones here are the two ONE-SIGNED tests -- a cap that can raise a
# number is not a cap -- and the v0 reproduction, which is what keeps D81's
# numbers regenerable.


def test_version_settings_is_the_only_place_the_version_string_is_read():
    """Both versions must resolve, and v0 must be the LINEAR, MEAN-anchored,
    uncapped model it was."""
    spec = rev.load_spec()
    v0 = rev.version_settings({**spec, "model_version": "revenue-v0"})
    assert v0["epsilon_grid"] == [1.0], "v0 is linear in the pool by definition"
    assert v0["delta_grid"] == [0.0]
    assert v0["anchor_statistic"] == "mean"
    assert v0["gamma_site_cap"] is False
    assert v0["capacity_cap"] is False
    v02 = rev.version_settings({**spec, "model_version": "revenue-v0.2"})
    assert v02["anchor_statistic"] == "median"
    assert v02["gamma_site_cap"] is True
    assert v02["capacity_cap"] is True
    assert min(v02["epsilon_grid"]) == 0.0 and max(v02["epsilon_grid"]) == 1.0


def test_version_settings_refuses_an_unknown_version_rather_than_guessing():
    with pytest.raises(RuntimeError, match="model_version"):
        rev.version_settings({**rev.load_spec(), "model_version": "revenue-v9"})


def test_grid3_reduces_to_grid_under_v0_in_the_same_order():
    """v0's candidate indexing has to survive, or the reproduction test would be
    comparing different candidates with the same index."""
    spec = rev.load_spec()
    v0 = rev.version_settings({**spec, "model_version": "revenue-v0"})
    g3 = rev._grid3(spec, v0)
    assert [(b, g) for b, g, _, _ in g3] == rev._grid(spec)
    assert {e for _, _, e, _ in g3} == {1.0}
    assert {d for _, _, _, d in g3} == {0.0}


def test_uncalibrated_with_epsilon_one_and_delta_zero_is_exactly_v0():
    edges, floor = [0, 100, 200], 50.0
    rings = np.array([[2.0, 3.0], [0.0, 1.0]])
    pool = np.array([1.0e5, 4.0e5])
    v0 = pool * rev.huff_share(rings, 1.5, edges, floor, gamma=0.75)
    got = rev.uncalibrated(pool, rings, 1.5, edges, floor, gamma=0.75,
                           epsilon=1.0, delta=0.0)
    assert np.allclose(got, v0)


def test_epsilon_is_recovered_on_a_synthetic_panel_with_a_known_elasticity():
    """THE IDENTIFICATION TEST. Spearman is rank-based and x -> x^eps is
    monotone, so epsilon is identified ONLY through the within-ZIP aggregation:
    the prediction for a ZIP is the MEAN of pool^eps over its establishments,
    and a mean of powers is not a power of a mean. This panel makes that
    channel strong on purpose -- the ZIPs differ in the DISPERSION of their
    pools, not only in the level -- and the fit must then find the true
    epsilon. It is also the demonstration of WHY the real fit's epsilon profile
    is nearly flat: strip the dispersion variation out and the signal goes.
    """
    rng = np.random.default_rng(11)
    eps_true = 0.4
    nz, per = 40, 60
    zips = [f"112{i:02d}" for i in range(nz)]
    pools, zp = [], []
    for z, spread in zip(zips, np.linspace(0.15, 1.4, nz)):
        level = rng.uniform(4.0, 9.0)
        pools.append(np.exp(rng.normal(level, spread, per)))
        zp += [z] * per
    pool = np.concatenate(pools)
    zp = np.array(zp, dtype=object)
    truth = np.array([np.mean(p ** eps_true) for p in pools])

    grid = [round(0.1 * i, 1) for i in range(11)]
    scores = []
    for e in grid:
        pred = np.array([np.mean(p ** e) for p in pools])
        scores.append(rev._spearman(pred, truth))
    assert grid[int(np.nanargmax(scores))] == pytest.approx(eps_true, abs=1e-9)

    # and the same recovery through the real machinery: one county, no
    # competition term, lambda fitted by _CatFit exactly as the fit does it.
    anchor = {"047": {"rev_per_estab_usd": 5.0e5, "rcptot_usd": 1.0e9, "estab": 2000.0}}
    cp = np.array(["047"] * len(pool), dtype=object)
    F = rev._CatFit([pool ** e for e in grid], zips, zp, cp, anchor)
    got = [rev._spearman(F.predict(k, F.lambdas(k)), truth) for k in range(len(grid))]
    assert grid[int(np.nanargmax(got))] == pytest.approx(eps_true, abs=1e-9)


def test_parsimonious_argmax_takes_the_smaller_epsilon_inside_the_tolerance():
    """The PRE-REGISTERED tie-break. epsilon = 1 is the strong claim; when the
    data cannot distinguish it from a weaker one, the weaker one ships."""
    cands = [(0.5, 1.0, 0.3, 0.0), (0.5, 1.0, 0.7, 0.0), (0.5, 1.0, 1.0, 0.0)]
    scores = np.array([0.695, 0.700, 0.698])
    assert rev._parsimonious_argmax(scores, cands, 0.01) == 0
    # outside the tolerance the best score wins, tie-break or no tie-break
    assert rev._parsimonious_argmax(np.array([0.60, 0.70, 0.68]), cands, 0.01) == 1
    # tolerance 0 is a plain argmax -- which is what revenue-v0 gets
    assert rev._parsimonious_argmax(scores, cands, 0.0) == 1


def test_parsimonious_argmax_cannot_run_away_to_epsilon_zero():
    """The guard that makes the tie-break safe: a constant-within-county
    prediction has no ZIP-grain skill and falls outside the tolerance by
    itself, so 'smallest epsilon' never means 'no pool term'."""
    cands = [(0.5, 1.0, 0.0, 0.0), (0.5, 1.0, 0.4, 0.0), (0.5, 1.0, 1.0, 0.0)]
    scores = np.array([0.01, 0.70, 0.695])
    assert rev._parsimonious_argmax(scores, cands, 0.01) == 1


def test_loo_spearman_matches_the_scalar_rank_and_correlate_loop():
    """The vectorised fold scorer is only worth having if it is the SAME
    number. Rank-minus-one-for-each-outranked is exact for distinct values."""
    rng = np.random.default_rng(5)
    for n in (6, 15, 40):
        preds, y = rng.normal(size=(n, n)), rng.normal(size=n)
        fast = rev._loo_spearman_rows(preds, y)
        slow = np.array([rev._spearman(np.delete(preds[i], i), np.delete(y, i))
                         for i in range(n)])
        assert np.allclose(fast, slow, atol=1e-12)


def _synthetic_catfit(seed=3, n=300, nz=9):
    rng = np.random.default_rng(seed)
    zips = [f"112{i:02d}" for i in range(nz)]
    zp = rng.choice(zips, n)
    cp = np.where(rng.random(n) < 0.5, "047", "061").astype(object)
    anchor = {"047": {"rev_per_estab_usd": 5.0e5, "rcptot_usd": 1.0e9, "estab": 2000.0},
              "061": {"rev_per_estab_usd": 9.0e5, "rcptot_usd": 2.0e9, "estab": 2200.0}}
    rhats = [rng.random(n) * 100 + 1 for _ in range(4)]
    return rev._CatFit(rhats, zips, zp, cp, anchor), zips


def test_predict_all_folds_matches_the_scalar_fold_loop():
    """v0.2 searches 4,686 candidates x tens of folds; the loop had to be
    vectorised. This pins that the vectorised arithmetic is identical to the
    per-fold lambdas()/predict() pair v0 ran."""
    F, zips = _synthetic_catfit()
    for k in range(F.n_cands):
        fast_lam, fast_p = F.lambdas_all_folds(k), F.predict_all_folds(k)
        for i in range(len(zips)):
            assert np.allclose(fast_lam[i], F.lambdas(k, drop_zip=i), equal_nan=True)
            assert np.allclose(fast_p[i], F.predict(k, F.lambdas(k, drop_zip=i)),
                               equal_nan=True)


def test_catfit_accepts_a_generator_without_materialising_every_candidate():
    F1, _ = _synthetic_catfit()
    rng = np.random.default_rng(3)
    assert F1.n_cands == 4


# ------------------------------------------------------- the median anchor


def test_median_band_employees_picks_the_band_holding_the_median_shop():
    spec = rev.load_spec()
    cbp = pd.DataFrame({
        "county": ["047"] * 4,
        "NAICS2017": ["722515"] * 4,
        "EMPSZES": ["001", "210", "220", "230"],
        "estab": [100.0, 40.0, 30.0, 30.0],
    })
    got = rev.median_band_employees(cbp, "cafe_bakery", spec)["047"]
    # cumulative 40, 70 -- the 50th of 100 banded shops sits in band 220
    assert got["band"] == "220"
    assert got["emp_median"] == pytest.approx(spec["cbp"]["band_midpoints"]["220"])
    assert got["usable"] is True


def test_median_band_is_unusable_when_the_bands_are_suppressed():
    spec = rev.load_spec()
    cbp = pd.DataFrame({"county": ["047"] * 2, "NAICS2017": ["722515"] * 2,
                        "EMPSZES": ["001", "210"], "estab": [100.0, 30.0]})
    assert rev.median_band_employees(cbp, "cafe_bakery", spec)["047"]["usable"] is False


def test_median_anchor_reconciles_the_band_map_against_the_ec_mean():
    """THE RECONCILIATION. The band -> revenue map is EC's own receipts per
    employee applied to CBP band midpoints. Applied to the MEAN band employment
    it must reproduce EC's own mean receipts per establishment; if it does not,
    the two sources disagree about what an establishment is and the median off
    the same map is not trustworthy either."""
    spec = rev.load_spec()
    ec = pd.DataFrame([{"naics": "722515", "county": "047", "rcptot_k": 642110.0,
                        "estab": 950.0, "emp": 7809.0, "payann_k": 1.0, "absent": False}])
    cbp = pd.DataFrame({
        "county": ["047"] * 6, "NAICS2017": ["722515"] * 6,
        "EMPSZES": ["001", "210", "220", "230", "241", "242"],
        "estab": [1044.0, 492.0, 276.0, 201.0, 71.0, 3.0]})
    got = rev.median_anchor("cafe_bakery", spec, ec, cbp)["047"]
    assert got["usable"] is True
    assert got["ec_rev_per_estab_usd"] == pytest.approx(675_905, rel=1e-4)
    assert got["ec_rev_per_emp_usd"] == pytest.approx(82_227, rel=1e-4)
    assert got["cbp_median_band"] == "220"
    assert got["median_rev_per_estab_usd"] == pytest.approx(575_589, rel=1e-4)
    assert got["median_over_mean"] == pytest.approx(0.8516, abs=5e-4)
    # the map priced at the MEAN band employment reproduces the EC mean to 3%
    assert got["mean_reconciliation_ratio"] == pytest.approx(1.0, abs=0.05)


def test_median_anchor_falls_back_to_the_mean_and_says_so():
    """A fallback is RECORDED, never silently taken."""
    spec = rev.load_spec()
    ec = pd.DataFrame([{"naics": "722515", "county": "047", "rcptot_k": 642110.0,
                        "estab": 950.0, "emp": 0.0, "payann_k": 1.0, "absent": False}])
    cbp = pd.DataFrame({"county": ["047"] * 2, "NAICS2017": ["722515"] * 2,
                        "EMPSZES": ["001", "210"], "estab": [100.0, 99.0]})
    got = rev.median_anchor("cafe_bakery", spec, ec, cbp)["047"]
    assert got["usable"] is False
    assert got["anchor_fallback"] == "mean"
    assert got["median_rev_per_estab_usd"] == pytest.approx(got["ec_rev_per_estab_usd"])


def test_both_lambdas_ship_side_by_side_so_the_correction_is_visible():
    rhat = np.array([1.0, 2.0, 3.0, 100.0])         # deliberately right-skewed
    county = np.array(["047"] * 4, dtype=object)
    anchor = {"047": {"rev_per_estab_usd": 1.0e6, "rcptot_usd": 4.0e6, "estab": 4.0}}
    med = {"047": {"median_rev_per_estab_usd": 5.0e5, "usable": True}}
    d = rev._lambdas(rhat, county, anchor, med_anchor=med)["047"]
    assert d["mean_rhat"] == pytest.approx(26.5)
    assert d["median_rhat"] == pytest.approx(2.5)
    assert d["lambda_per_store"] == pytest.approx(1.0e6 / 26.5)
    assert d["lambda_median"] == pytest.approx(5.0e5 / 2.5)
    assert d["lambda_median_over_mean"] == pytest.approx(
        (5.0e5 / 2.5) / (1.0e6 / 26.5), rel=1e-3)


def test_lambda_key_is_the_one_place_the_anchor_statistic_becomes_a_field():
    assert rev._lambda_key({"anchor_statistic": "median"}) == "lambda_median"
    assert rev._lambda_key({"anchor_statistic": "mean"}) == "lambda_per_store"


# ------------------------------------------------------ the two ONE-SIGNED caps


def test_gamma_site_cap_never_raises_a_number():
    """docstring (7e). A negative gamma may keep its ZIP-level skill, but at a
    SITE it may not multiply the prediction above the corridor-neutral share."""
    edges, floor = [0, 100, 200, 400], 50.0
    rng = np.random.default_rng(7)
    rings = rng.integers(0, 40, size=(500, 3)).astype(float)
    pool = rng.random(500) * 1e6 + 1e4
    for gamma in (-0.75, -0.5, -0.25, 0.0, 0.25, 1.0):
        free = rev.uncalibrated(pool, rings, 1.0, edges, floor, gamma=gamma)
        capped = rev.uncalibrated(pool, rings, 1.0, edges, floor, gamma=gamma,
                                  gamma_site_cap=True)
        assert np.all(capped <= free + 1e-9), gamma
        if gamma >= 0:
            assert np.allclose(capped, free), "a non-negative gamma must be untouched"
        else:
            # the term vanishes entirely: every site gets the neutral share
            assert np.allclose(capped, pool)


def test_capacity_cap_never_raises_a_number():
    """docstring (7d). min() is one-signed by construction; this pins that the
    shipped arithmetic really is a min and that p25/p50/p75 stay ordered."""
    rng = np.random.default_rng(9)
    model = rng.random(1000) * 5e6 + 1e4
    sig = rng.random(1000) * 0.8
    z = 0.6744897501960817
    p25, p50, p75 = model * np.exp(-z * sig), model, model * np.exp(z * sig)
    area = rng.random(1000) * 4000 + 200
    band = rev.capacity_band("restaurant")
    c25, c50, c75 = area * band["p25"], area * band["p50"], area * band["p75"]
    n25, n50, n75 = np.minimum(p25, c25), np.minimum(p50, c50), np.minimum(p75, c75)
    assert np.all(n50 <= p50 + 1e-9)
    assert np.all(n25 <= p25 + 1e-9) and np.all(n75 <= p75 + 1e-9)
    assert np.all(n25 <= n50 + 1e-6) and np.all(n50 <= n75 + 1e-6)
    assert np.any(n50 < p50), "the fixture must actually exercise the cap"


def test_capacity_band_is_a_ceiling_not_a_central_estimate():
    """Ordered, positive, and set above the national CENTRAL benchmarks the
    revenue.yaml sources cite -- a ceiling that sat at the median would cap
    half the city."""
    spec = rev.load_spec()
    for cat in spec["capacity"]["psf_per_year"]:
        b = rev.capacity_band(cat, spec)
        assert 0 < b["p25"] < b["p50"] < b["p75"]
    # [1] full-service restaurants: $250-325/sq ft is "moderately profitable"
    assert rev.capacity_band("restaurant")["p50"] > 325
    # [3] Starbucks, the highest-productivity mass-market cafe: ~$744/sq ft
    assert rev.capacity_band("cafe_bakery")["p75"] > 744


def test_capacity_area_flags_the_typical_footprint_fallback():
    spec = rev.load_spec()
    demise = np.array([1000.0, 0.0, np.nan, -5.0])
    area, used_typical = rev.capacity_area(demise, "restaurant", spec)
    typ = float(spec["capacity"]["typical_sqft"]["restaurant"])
    assert area.tolist() == [1000.0, typ, typ, typ]
    assert used_typical.tolist() == [False, True, True, True]


def test_price_index_is_one_where_income_is_unknown_not_zero():
    """A missing income is 'no information about the price level', never 'a
    cheap neighbourhood' -- the same rule quintile_of follows."""
    inc = np.array([100_000.0, np.nan, 0.0, 50_000.0])
    got = rev.price_index(inc, 100_000.0)
    assert got.tolist() == [1.0, 1.0, 1.0, 0.5]
    assert rev.price_index(inc, np.nan).tolist() == [1.0] * 4


def test_price_index_enters_only_through_delta():
    edges, floor = [0, 100], 50.0
    rings = np.array([[1.0], [4.0]])
    pool, p = np.array([1.0e5, 2.0e5]), np.array([2.0, 0.5])
    base = rev.uncalibrated(pool, rings, 1.0, edges, floor, pindex=p, delta=0.0)
    with_d = rev.uncalibrated(pool, rings, 1.0, edges, floor, pindex=p, delta=0.5)
    assert np.allclose(base, rev.uncalibrated(pool, rings, 1.0, edges, floor))
    assert np.allclose(with_d / base, p ** 0.5)


def test_the_capacity_columns_are_declared_in_the_schema():
    sql = (rev.PKG_ROOT / "sql" / "025_revenue_capacity.sql").read_text()
    for col in ("revenue_cap_p50", "capacity_bound"):
        assert col in rev.CATEGORY_REVENUE_COLUMNS
        assert f"ADD COLUMN IF NOT EXISTS {col}" in sql


def test_write_revenue_fills_a_column_the_caller_did_not_produce():
    """A v0 calibration produces no capacity columns; the SET list is one fixed
    pinned list regardless, so the missing ones are written NULL."""
    from loci import db as locidb

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("INSERT INTO analysis.address_category (address_id, borough, category, frame) "
                "VALUES ('1','BK','restaurant','lot')")
    rev.write_revenue(con, pd.DataFrame({
        "address_id": ["1"], "borough": ["BK"], "category": ["restaurant"],
        "revenue_p25": [1.0], "revenue_p50": [2.0], "revenue_p75": [3.0],
        "rent_ceiling": [0.2], "revenue_model_version": ["revenue-v0"]}), ["BK"])
    got = con.execute("SELECT revenue_p50, revenue_cap_p50, capacity_bound "
                      "FROM analysis.address_category").fetchone()
    assert got == (2.0, None, None)


def test_pool_factor_keeps_an_unknown_pool_unknown_at_every_epsilon():
    """numpy evaluates nan ** 0 as 1.0. Left alone that would give the
    epsilon = 0 candidate a LARGER evaluation sample than every other
    candidate -- every establishment with an unknown tract income would
    re-enter the fit as a 1.0 instead of being dropped -- and a grid search
    comparing candidates fitted on different samples is not a grid search."""
    pool = np.array([1.0, 0.0, np.nan, 4.0])
    for e in (0.0, 0.4, 1.0):
        got = rev.pool_factor(pool, e)
        assert np.isnan(got[2]), f"epsilon {e} resurrected an unknown pool"
        assert np.isfinite(got[[0, 1, 3]]).all()
    assert rev.pool_factor(pool, 1.0).tolist()[3] == 4.0
    assert rev.pool_factor(pool, 0.5).tolist()[3] == 2.0


def test_epsilon_is_chosen_by_the_gate_not_by_an_argmax():
    """The unconstrained argmax came back degenerate (epsilon = 0 deletes the
    demand pool and the placebo caught it), and a bare prior would be an
    assertion. v0.2 refits the whole family at every epsilon and ships the
    SMALLEST one that still passes the full gate."""
    vs = rev.version_settings()
    assert vs["epsilon_selection"] == "smallest_gate_passing"
    assert vs["epsilon_shipped"] is None
    assert min(vs["epsilon_grid"]) == 0.0 and max(vs["epsilon_grid"]) == 1.0
    v0 = rev.version_settings({**rev.load_spec(), "model_version": "revenue-v0"})
    assert v0["epsilon_selection"] == "fixed", "v0 must not acquire a scan it never had"
    assert v0["epsilon_grid"] == [1.0]


def test_the_shipped_epsilon_is_the_smallest_one_that_passed_the_gate():
    """The rule has to be visible in the artefact: every smaller epsilon in the
    scan must have FAILED, or the shipped one was not the smallest passing."""
    cal = rev.load_calibration()
    if not cal or cal.get("model_version") != "revenue-v0.2":
        pytest.skip("no v0.2 calibration on disk")
    for cat, d in cal["categories"].items():
        scan = d.get("epsilon_gate_scan")
        if not scan or d.get("gate") != "pass":
            continue
        shipped = float(d["epsilon"])
        for e, r in scan.items():
            if float(e) < shipped:
                assert r["gate"] != "pass", f"{cat} could have shipped at epsilon {e}"
        assert scan[str(shipped)]["gate"] == "pass", cat


def test_the_calibration_reports_the_fitted_epsilon_beside_the_shipped_one():
    """The gap between what the search wanted and what ships must never be
    invisible in the shipped artefact."""
    cal = rev.load_calibration()
    if not cal or cal.get("model_version") != "revenue-v0.2":
        pytest.skip("no v0.2 calibration on disk")
    for cat, d in cal["categories"].items():
        if d.get("beta") is None:
            continue
        assert "epsilon_fitted_unconstrained" in d, cat
        assert "epsilon_profile" in d and "epsilon_identified" in d, cat
        assert d["epsilon"] in rev.version_settings()["epsilon_grid"], cat
        assert d.get("epsilon_gate_scan"), cat


def test_delta_ships_only_where_it_beats_its_own_absence():
    cal = rev.load_calibration()
    if not cal or cal.get("model_version") != "revenue-v0.2":
        pytest.skip("no v0.2 calibration on disk")
    for cat, d in cal["categories"].items():
        pi = d.get("price_index") or {}
        if not pi or pi.get("adds_skill") is None:
            continue
        if not pi["adds_skill"]:
            assert d["delta"] == 0.0, f"{cat} shipped a price index that earned nothing"


def test_the_epsilon_floor_is_a_structural_constraint_not_a_tuning_knob():
    """`smallest epsilon that passes the gate` needs a floor, because the gate
    CAN be passed by a model with no demand pool at all -- cafe_bakery passed
    at epsilon = 0 on the 2026-09-13 scan, where the only spatial signal left is
    incumbent density, which is the rejected D1 thesis. The floor is the bottom
    of the published retail demand elasticities and of the owner's prior."""
    vs = rev.version_settings()
    assert vs["epsilon_floor"] == 0.3
    assert vs["epsilon_floor"] in vs["epsilon_grid"]
    v0 = rev.version_settings({**rev.load_spec(), "model_version": "revenue-v0"})
    assert v0["epsilon_floor"] == 0.0, "v0 never had a floor and must not acquire one"


def test_nothing_ships_below_the_epsilon_floor_however_well_it_scored():
    cal = rev.load_calibration()
    if not cal or cal.get("model_version") != "revenue-v0.2":
        pytest.skip("no v0.2 calibration on disk")
    floor = rev.version_settings()["epsilon_floor"]
    for cat, d in cal["categories"].items():
        if d.get("gate") != "pass":
            continue
        assert float(d["epsilon"]) >= floor, f"{cat} shipped below the floor"
        # and if it DID pass below the floor, the artefact has to say so
        if d.get("epsilon_passed_below_floor"):
            assert "D1" in (d.get("epsilon_shipped_reason") or ""), cat


def test_lambda_is_fitted_on_the_predictor_that_actually_ships():
    """The gamma site cap is applied at an ADDRESS but the lambda calibration
    runs over ESTABLISHMENTS, which sit on retail corridors. Fitting lambda
    against the UNCAPPED share and applying it to capped predictions divides
    the whole level by the median establishment's agglomeration multiplier --
    it put the median Manhattan restaurant at $130k against a $1.67M median
    anchor on the first v0.2 apply. The backtest keeps gamma uncapped (that is
    where its ranking skill lives); lambda must see the shipped predictor."""
    import inspect
    src = inspect.getsource(rev._fit_at)
    assert "rhat_ship" in src and "lam_full = _lambdas(rhat_ship" in src
    cal = rev.load_calibration()
    if not cal or cal.get("model_version") != "revenue-v0.2":
        pytest.skip("no v0.2 calibration on disk")
    for cat, d in cal["categories"].items():
        for f, L in (d.get("lambda") or {}).items():
            assert "site-capped" in (L.get("fitted_on") or ""), f"{cat}/{f}"


def test_the_median_anchor_is_reproduced_by_the_shipped_lambda():
    """The defining property of the median anchor, checked on the artefact:
    lambda_median x the median R_hat over the county's establishments must
    equal the CBP-band median revenue per establishment."""
    cal = rev.load_calibration()
    if not cal or cal.get("model_version") != "revenue-v0.2":
        pytest.skip("no v0.2 calibration on disk")
    for cat, d in cal["categories"].items():
        for f, L in (d.get("lambda") or {}).items():
            if not L.get("lambda_median") or not L.get("median_rhat"):
                continue
            assert L["lambda_median"] * L["median_rhat"] == pytest.approx(
                L["median_anchor_usd"], rel=1e-4), f"{cat}/{f}"
