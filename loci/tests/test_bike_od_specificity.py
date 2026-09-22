"""D43 — the category-specificity placebo for `bike_od_supplied_share`.

`placebo()` (tested in test_bike_od.py) compares LEVELS: is a destination above
the grocery median. Nine times in ten a destination above the grocery median is
above every median, so that test cannot tell a genuinely grocery-specific flow
from one riding destination attractiveness with a different loading. D43 replaces
the level with a RESIDUAL — log1p(density_c) regressed on log1p(the other
fourteen), ranked across destinations — and asks whether a neighbourhood's riders
go somewhere unusually well supplied with c GIVEN everything else.

The bug classes this file guards, which are the ones a permutation test of a
trip-weighted rank is most likely to get wrong:

  * a rank vector that does NOT average 0.5, putting a silent +1/2n on every
    origin and turning "spreads evenly" into a positive finding;
  * a permutation that leaks across strata, so a rank lands on a three-dock
    destination the flow could never have produced and the test rejects against
    an impossibility;
  * a statistic that fires on TOTAL destination density — the exact confound the
    residual exists to remove, and the reason for the kill rule;
  * BH applied per-p instead of step-up, which silently drops a true rejection
    sitting above its own line;
  * NULL used as a synonym for "not significant", which would let the re-sweep
    delete a column on an inconclusive or underpowered run;
  * a re-sweep hook that writes on a dry run, or that touches anything other
    than a literal NULL verdict.

Every synthetic world below is built in this file. Nothing here opens the real
warehouse: the thresholds were ratified blind on 2026-09-16 and a test that
peeked at the data would be the one thing the blinding forbids.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest

from loci.categories import CATEGORIES
from loci.model import bike_od as bo

CATS = sorted(CATEGORIES)


# ----------------------------------------------------------- synthetic worlds

def _density_frame(dens: np.ndarray, dests: list[str],
                   npois: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame([
        {"nta_code": d, "category": c, "n_pois": int(npois[i, j]),
         "n_addresses": 900, "n_units": 2000.0,
         "poi_per_1k_units": float(dens[i, j])}
        for i, d in enumerate(dests) for j, c in enumerate(CATS)])


def _world(n_dest: int = 90, n_origin: int = 12, seed: int = 7,
           target: str = "total", trips_per_origin: float = 3000.0):
    """A destination supply matrix, a dock roster and a flow that points at
    `target`.

    `target` is the whole experiment. "total" sends riders in proportion to a
    destination's TOTAL supply — the confound — and every category's W must come
    out at zero. "cat:<c>" sends them in proportion to one category's density and
    that category's W must come out positive. "pair:<a>,<b>" points at two
    categories' idiosyncratic components at once, which is how the kill rule is
    made to fire on demand.
    """
    rng = np.random.default_rng(seed)
    n_cd = 9
    dests = [f"BK{(i % n_cd) + 1:02d}{i // n_cd:02d}" for i in range(n_dest)]
    assert len(set(dests)) == n_dest
    origins = [f"MN{(i % 4) + 1:02d}{i // 4:02d}" for i in range(n_origin)]

    base = np.exp(rng.normal(0.0, 0.6, n_dest))              # busyness
    logm = rng.normal(0.0, 0.9, (n_dest, len(CATS)))         # idiosyncratic
    dens = base[:, None] * np.exp(logm) * 2.0
    npois = np.maximum(3, np.round(dens * 1.5)).astype("int64")
    docks = pd.Series(rng.integers(2, 40, n_dest).astype("float64"), index=dests)
    centroids = pd.DataFrame({
        "nta_code": dests,
        "lon": -73.99 + rng.random(n_dest) * 0.25,
        "lat": 40.65 + rng.random(n_dest) * 0.20})

    if target == "total":
        tw = dens.sum(axis=1)
    elif target.startswith("cat:"):
        tw = dens[:, CATS.index(target[4:])]
    elif target.startswith("pair:"):
        a, b = target[5:].split(",")
        z = (logm - logm.mean(axis=0)) / logm.std(axis=0)
        tw = np.exp(2.0 * z[:, CATS.index(a)] + 2.0 * z[:, CATS.index(b)])
    else:                                                    # pragma: no cover
        raise ValueError(target)

    rows = []
    for o in origins:
        w = tw * np.exp(rng.normal(0.0, 0.4, n_dest))
        w = w / w.sum() * trips_per_origin
        for d, t in zip(dests, w):
            rows.append({"origin_nta": o, "destination_nta": d,
                         "trips": float(t)})
    flow_df = pd.DataFrame(rows)
    return _density_frame(dens, dests, npois), flow_df, docks, centroids


def _run(target: str = "total", n_dest: int = 90, seed: int = 7, **kw):
    density, flow_df, docks, centroids = _world(n_dest=n_dest, target=target,
                                                seed=seed)
    kw.setdefault("n_perm", 500)
    kw.setdefault("n_boot", 300)
    return bo.specificity_from_frames(flow_df, density, docks=docks,
                                      centroids=centroids, window="synthetic",
                                      **kw)


# ------------------------------------------------------------ the rank itself

def test_residual_ranks_average_exactly_one_half():
    """`W_c(o) = sum_d w_od r_c(d) - 0.5` is only centred if the ranks are. With
    `rank/n` instead of `(rank - 0.5)/n` every origin would carry a silent
    +1/2n and an origin whose riders spread evenly would read positive."""
    density, _, _, _ = _world()
    ranks, aux = bo.destination_residual_rank(density)
    means = ranks.groupby("category")["r"].mean()
    assert len(means) == 17
  # 17, not 16: family widened to seventeen by owner ruling 2026-09-22 (D137, brewery)
    assert np.allclose(means.to_numpy(), 0.5, atol=1e-12)
    assert set(aux) == set(CATS)
    # the auxiliary R2 is the POWER of the test, not a diagnostic afterthought
    assert all(0.0 <= v < 1.0 for v in aux.values())


def test_an_evenly_spread_origin_reads_exactly_zero():
    density, _, _, _ = _world(n_dest=30)
    ranks, _ = bo.destination_residual_rank(density)
    dests = sorted(ranks["destination_nta"].unique())
    flat = pd.DataFrame({"origin_nta": "MN0101", "destination_nta": dests,
                         "trips": 100.0})
    w = bo.trip_weighted_rank(flat, ranks, min_trips=200)
    assert np.allclose(w["w_rank"].to_numpy(), 0.0, atol=1e-12)


def test_an_origin_under_the_trip_floor_is_null_never_zero():
    """The module's standing convention. A 0.0 here would assert that a
    neighbourhood's riders go nowhere in particular, which is a claim about the
    dock network wearing the costume of a claim about the street."""
    density, _, _, _ = _world(n_dest=30)
    ranks, _ = bo.destination_residual_rank(density)
    dests = sorted(ranks["destination_nta"].unique())
    thin = pd.DataFrame({"origin_nta": "MN0101", "destination_nta": dests,
                         "trips": 1.0})
    w = bo.trip_weighted_rank(thin, ranks, min_trips=200)
    assert len(w) == 17
  # 17, not 16: family widened to seventeen by owner ruling 2026-09-22 (D137, brewery)
    assert w["w_rank"].isna().all()


# ------------------------------------------------------------- the null model

def test_the_permutation_never_leaves_its_stratum():
    """Strata are quintile of other-category density x tercile of dock count. A
    permutation that crossed them would move a rank onto a destination with a
    tenth of the docks — a flow the network could not produce — and the test
    would then reject against an impossibility."""
    r = np.arange(12, dtype="float64")
    strata = np.asarray(list("aaaabbbbcccc"), dtype=object)
    out = bo.permute_within_strata(r, strata, rng=np.random.default_rng(1),
                                   n_draws=50)
    assert out.shape == (50, 12)
    for draw in out:
        for code in ("a", "b", "c"):
            idx = np.flatnonzero(strata == code)
            assert sorted(draw[idx]) == sorted(r[idx])
    assert not np.allclose(out, r)          # and it does actually shuffle
    # a singleton stratum is fixed by construction, not by accident
    single = bo.permute_within_strata(r, np.asarray(list("abcdefghijkl"),
                                                    dtype=object),
                                      rng=np.random.default_rng(2), n_draws=5)
    assert np.allclose(single, r)


def test_the_same_random_draws_are_reused_across_categories():
    """P1. The same B index sets for all fifteen categories preserves the
    cross-category dependence a max-T check would need. The strata differ per
    category, so the shared object is the uniform matrix, not the indices."""
    rng = np.random.default_rng(3)
    U = rng.random((7, 8))
    r = np.arange(8, dtype="float64")
    s = np.asarray(list("aabbccdd"), dtype=object)
    a = bo.permute_within_strata(r, s, randoms=U, n_draws=7)
    b = bo.permute_within_strata(r, s, randoms=U, n_draws=7)
    assert np.array_equal(a, b)


# ------------------------------------------------------------ multiple testing

def test_benjamini_hochberg_is_step_up_not_per_p():
    """The classic off-by-one: comparing each p to its OWN q i/m drops a true
    rejection that sits above its line but below a larger passing one."""
    p = np.array([0.001, 0.045, 0.049])
    assert bo.benjamini_hochberg(p, 0.05).tolist() == [True, True, True]
    p2 = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205,
                   0.212, 0.216])
    assert bo.benjamini_hochberg(p2, 0.05).tolist() == \
        [True, True] + [False] * 8
    assert bo.benjamini_hochberg(p2, 0.20).tolist() == \
        [True] * 7 + [False] * 3
    # a statistic that does not exist is not a test that was run
    assert bo.benjamini_hochberg(np.array([np.nan, 0.001]), 0.05).tolist() == \
        [False, True]
    assert not bo.benjamini_hochberg(np.array([np.nan, np.nan]), 0.05).any()


def test_there_is_one_family_of_sixteen_and_no_structural_exclusion():
    """P8. The five weekday-business-hours categories are FLAGGED as a built-in
    negative control, never dropped: excluding them would remove the only
    categories that can make the kill rule fire."""
    assert isinstance(bo.EXPECTED_UNINFORMATIVE, frozenset)
    assert bo.EXPECTED_UNINFORMATIVE == frozenset(
        {"childcare", "clinic", "bank", "tailor_repair", "hardware"})
    assert bo.EXPECTED_UNINFORMATIVE <= set(CATEGORIES)
    assert not hasattr(bo, "EXCLUDED_WEEKDAY_HOURS")
    rep = _run("total", n_perm=120, n_boot=120)
    assert len(rep["per_category"]) == 17
  # 17, not 16: family widened to seventeen by owner ruling 2026-09-22 (D137, brewery)
    assert set(rep["per_category"]["category"]) == set(CATS)
    assert rep["per_category"]["expected_uninformative"].sum() == 5


# ------------------------------------------------------- does it detect, and
# ------------------------------------------------------- does it stay quiet

def test_trips_following_one_category_are_detected():
    """The measure's reason to exist. Riders sent in proportion to grocery
    density must produce a positive median W for grocery and a small p."""
    rep = _run("cat:grocery")
    row = rep["per_category"].set_index("category").loc["grocery"]
    assert row["median_W"] > 0.05
    assert row["p_perm"] < 0.05
    assert row["ci_lo"] > 0
    assert row["verdict"] == "PASS"
    assert "grocery" in rep["gate"]["passing"]


def test_trips_following_total_density_move_no_category():
    """The confound, and the whole reason the statistic is a residual. Riders
    sent in proportion to a destination's TOTAL supply must move nothing: under
    the old level-based placebo this is exactly the flow that would have made
    all fifteen categories look supplied."""
    rep = _run("total")
    w = rep["per_category"].set_index("category")["median_W"]
    assert len(w) == 17
  # 17, not 16: family widened to seventeen by owner ruling 2026-09-22 (D137, brewery)
    assert w.abs().max() < 0.10, w.sort_values()
    assert not rep["kill_rule"]["fired"]


def test_the_kill_rule_fires_when_the_negative_controls_pass():
    """P8. Two of the five expected-uninformative categories passing positive
    means the residual did NOT remove destination attractiveness, and no
    category may carry a stored number — not even the ones that passed."""
    # seed 9: the synthetic world draws a (n_dest x len(CATS)) matrix, so the
    # sixteenth category (owner ruling 2026-09-17) shifted every draw under
    # seed 7 and clinic's W fell to 0.17 -- a fixture artefact, not a family
    # effect. Seeds 9, 10, 12, 13 all fire at sixteen; 9 is the first.
    rep = _run("pair:bank,clinic", seed=9)
    per = rep["per_category"].set_index("category")
    assert per.loc["bank", "median_W"] > 0
    assert per.loc["clinic", "median_W"] > 0
    assert rep["kill_rule"]["fired"] is True
    assert set(rep["kill_rule"]["passing_flagged"]) >= {"bank", "clinic"}
    assert set(rep["per_category"]["verdict"]) == {"NO_STORED_NUMBER"}
    assert rep["gate"]["passes"] is False
    assert rep["gate"]["confounded"] is True
    assert bo.KILL_RULE_MESSAGE in rep["gate"]["message"]
    assert rep["gate"]["failing"] == []      # nothing is a NULL: it is confounded


# ------------------------------------------------------------- the verdicts

def test_null_is_reserved_and_inconclusive_is_not_a_null():
    """P7. NULL is a positive claim — all three gates non-rejecting — and it is
    the ONLY verdict the re-sweep acts on. One gate holding is INCONCLUSIVE:
    both numbers are printed, nothing is stored, and turning that into a null
    would convert 'we could not tell' into 'we established there is nothing'."""
    v = bo.specificity_verdict
    assert v(True, True, True, False, False) == "PASS"
    assert v(False, False, False, False, False) == "NULL"
    assert v(True, False, True, False, False) == "INCONCLUSIVE"
    assert v(False, True, False, False, False) == "INCONCLUSIVE"
    assert v(True, True, False, False, False) == "INCONCLUSIVE"   # floor unmet
    assert v(True, True, True, True, False) == "LOW_POWER"
    assert v(False, False, False, True, False) == "LOW_POWER"


def test_an_underpowered_run_cannot_resolve_rather_than_declaring_a_null():
    """P3. When MDE = 2.8·σ̂₀ exceeds the floor the run cannot detect an effect
    of 0.05, so 'we found nothing' is not a finding. The state becomes
    CANNOT_RESOLVE and the printed word is 'cannot resolve' for every non-PASS,
    whatever the underlying state was."""
    from loci.cli import _od_spec_verdict

    v = bo.specificity_verdict
    assert v(False, False, False, False, True) == "CANNOT_RESOLVE"
    assert v(True, True, True, False, True) == "PASS"      # power only binds down
    assert "cannot resolve" in _od_spec_verdict("CANNOT_RESOLVE", True)
    assert "cannot resolve" in _od_spec_verdict("INCONCLUSIVE", True)
    assert "cannot resolve" in _od_spec_verdict("LOW_POWER", True)
    assert "cannot resolve" not in _od_spec_verdict("PASS", True)
    assert "cannot resolve" not in _od_spec_verdict("INCONCLUSIVE", False)
    rep = _run("total")
    assert rep["diagnostics"]["mde_median"] == pytest.approx(
        bo.SPECIFICITY_MDE_Z * rep["diagnostics"]["sigma0_median"], rel=1e-9)
    assert "NULL" not in set(rep["per_category"]["verdict"]) or \
        not rep["underpowered"]


def test_low_power_is_declared_in_advance_and_still_counted_in_the_family():
    """P4. A category the other fourteen already explain has a residual made of
    noise; ranking it is a coin flip. It is reported, it stays in the BH family,
    and it may never carry a stored number."""
    rep = _run("total", n_perm=120, n_boot=120, aux_r2_cutoff=0.0)
    per = rep["per_category"]
    assert (per["verdict"] == "LOW_POWER").all()
    assert per["p_primary"].notna().all()       # still tested, still in the family
    assert rep["gate"]["failing"] == []


# ------------------------------------------------------------- diagnostics

def test_the_strata_collapse_when_the_five_by_three_grid_runs_thin():
    """Declared in advance (open item 2): under a median stratum size of four the
    5x3 grid is re-declared as tercile x median-split, automatically and in the
    printed diagnostics — never silently."""
    thin = _run("total", n_dest=30, n_perm=120, n_boot=120)["diagnostics"]
    assert thin["strata_collapsed"] is True
    assert thin["strata_grid"] == "3x2"
    wide = _run("total", n_dest=90, n_perm=120, n_boot=120)["diagnostics"]
    assert wide["strata_collapsed"] is False
    assert wide["strata_grid"] == "5x3"
    assert wide["median_stratum_size"] >= bo.SPECIFICITY_MIN_STRATUM_MEDIAN


def test_the_diagnostics_say_the_effective_sample_is_destinations():
    """One permutation per draw is applied to EVERY origin, so 12 origins are
    not 12 independent readings. Every number here exists to keep that in front
    of the reader."""
    dg = _run("total", n_perm=120, n_boot=120)["diagnostics"]
    for k in ("sum_w2_p50", "sum_w2_mean_vector", "n_eff_mean_vector",
              "distinct_weight_vectors", "median_pairwise_cosine",
              "median_stratum_size", "morans_i", "moran_flagged",
              "sigma0_median", "mde_median"):
        assert k in dg
    assert 0.0 < dg["sum_w2_p50"] <= 1.0
    assert dg["distinct_weight_vectors"] == dg["n_origins"] == 12
    assert -1.0 <= dg["median_pairwise_cosine"] <= 1.0
    assert set(dg["morans_i"]) == set(CATS)
    assert dg["moran_k"] == 6 and dg["moran_permutations"] == 199


def test_the_robustness_columns_are_reported_and_are_not_gates():
    rep = _run("cat:grocery", n_perm=200, n_boot=200)
    rob = rep["robustness"].set_index("category")
    for c in ("median_W_per_dock", "median_W_unweighted", "weighted_lift",
              "median_W_unresidualised", "p_unresidualised",
              "p_label_permutation", "p_spatial_block"):
        assert c in rob.columns
    assert rob.loc["grocery", "weighted_lift"] == pytest.approx(
        rob.loc["grocery", "median_W"] - rob.loc["grocery",
                                                 "median_W_unweighted"])
    # the LEVEL statistic the old placebo tested fires on this flow too; the
    # residual one is the gate, and only the residual one is in per_category
    assert rob.loc["grocery", "median_W_unresidualised"] > 0
    assert "p_unresidualised" not in rep["per_category"].columns


# ------------------------------------------------------------ reproducibility

def test_the_same_seed_gives_the_same_answer():
    a = _run("cat:grocery", n_perm=200, n_boot=200, seed=0)
    b = _run("cat:grocery", n_perm=200, n_boot=200, seed=0)
    for col in ("median_W", "p_perm", "ci_lo", "ci_hi", "cd_ci_lo"):
        assert np.allclose(a["per_category"][col].to_numpy(),
                           b["per_category"][col].to_numpy(), equal_nan=True)
    assert a["verdicts"] == b["verdicts"]
    c = _run("cat:grocery", n_perm=200, n_boot=200, seed=11)
    assert not np.allclose(a["per_category"]["p_perm"].to_numpy(),
                           c["per_category"]["p_perm"].to_numpy())


def test_the_bars_are_arguments_not_edits():
    """Every threshold is a keyword argument with the ratified default, so
    re-running under a different bar is an argument change and shows up in the
    report's own `bars` block rather than in a diff."""
    rep = _run("total", n_perm=120, n_boot=120)
    assert rep["bars"]["bh_q"] == bo.SPECIFICITY_BH_Q == 0.10
    assert rep["bars"]["min_effect"] == bo.SPECIFICITY_MIN_EFFECT == 0.05
    assert rep["bars"]["aux_r2_cutoff"] == bo.SPECIFICITY_AUX_R2_CUTOFF == 0.75
    assert bo.SPECIFICITY_N_PERM == 10_000 and bo.SPECIFICITY_N_BOOT == 2_000
    assert bo.THRESHOLDS_PENDING is False
    strict = _run("total", n_perm=120, n_boot=120, min_effect=0.9)
    assert strict["bars"]["min_effect"] == 0.9
    assert not strict["per_category"]["effect_pass"].any()


# ------------------------------------------------------------ the re-sweep hook

@pytest.fixture
def swept(tmp_path):
    """A warehouse holding only what the hook touches."""
    con = duckdb.connect(str(tmp_path / "sweep.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    con.execute("""
        CREATE TABLE analysis.address_category (
            address_id VARCHAR, category VARCHAR, bike_od_supplied_share DOUBLE)""")
    con.executemany(
        "INSERT INTO analysis.address_category VALUES (?, ?, ?)",
        [(f"a{i}", c, 0.5) for c in CATS for i in range(3)])
    return con


def _filled(con) -> dict:
    return dict(con.execute(
        "SELECT category, count(bike_od_supplied_share) FROM "
        "analysis.address_category GROUP BY 1").fetchall())


def test_the_resweep_dry_run_writes_nothing(swept):
    verdicts = {c: "NULL" for c in CATS}
    rep = bo.resweep_failing_categories(swept, verdicts)
    assert rep["dry_run"] is True
    assert rep["rows_nulled"] == 0
    assert rep["rows_matched"] == 51   # 3 x 17 (family of seventeen, owner ruling 2026-09-22, D137)
    assert all(v == 3 for v in _filled(swept).values())


def test_the_resweep_nulls_only_the_null_verdicts(swept):
    """INCONCLUSIVE, LOW_POWER and CANNOT_RESOLVE all store nothing, but none of
    them is a finding that the category is not specific. Deleting a stored
    number on one of them would convert 'we could not tell' into 'we
    established there is nothing'."""
    verdicts = {c: "PASS" for c in CATS}
    verdicts["grocery"] = "NULL"
    verdicts["pharmacy"] = "NULL"
    verdicts["bar"] = "INCONCLUSIVE"
    verdicts["cafe_bakery"] = "LOW_POWER"
    verdicts["fitness"] = "CANNOT_RESOLVE"
    rep = bo.resweep_failing_categories(swept, verdicts, dry_run=False)
    assert rep["categories"] == ["grocery", "pharmacy"]
    assert rep["rows_nulled"] == 6
    filled = _filled(swept)
    assert filled["grocery"] == 0 and filled["pharmacy"] == 0
    for c in ("bar", "cafe_bakery", "fitness", "restaurant"):
        assert filled[c] == 3


def test_the_resweep_refuses_a_confounded_run_unless_told(swept):
    report = {"verdicts": {c: "NO_STORED_NUMBER" for c in CATS},
              "kill_rule": {"fired": True}}
    with pytest.raises(RuntimeError, match="kill rule"):
        bo.resweep_failing_categories(swept, report, dry_run=False)
    rep = bo.resweep_failing_categories(swept, report, dry_run=False,
                                        confounded=True)
    assert rep["categories"] == CATS
    assert rep["rows_nulled"] == 51    # 3 x 17 (family of seventeen, owner ruling 2026-09-22, D137)
    assert all(v == 0 for v in _filled(swept).values())


def test_the_resweep_refuses_while_the_thresholds_are_pending(swept, monkeypatch):
    monkeypatch.setattr(bo, "THRESHOLDS_PENDING", True)
    with pytest.raises(RuntimeError, match="THRESHOLDS_PENDING"):
        bo.resweep_failing_categories(swept, {c: "NULL" for c in CATS})
    assert all(v == 3 for v in _filled(swept).values())


def test_a_pending_run_stores_nothing_and_says_why(monkeypatch):
    monkeypatch.setattr(bo, "THRESHOLDS_PENDING", True)
    rep = _run("cat:grocery", n_perm=120, n_boot=120)
    assert set(rep["per_category"]["verdict"]) == {"PENDING"}
    assert rep["gate"]["pending"] is True
    assert rep["gate"]["passes"] is False
    assert rep["gate"]["message"] == bo.THRESHOLDS_PENDING_MESSAGE


# ----------------------------------------------------- the gate the DOT half
# ----------------------------------------------------- reads

def test_dot_validation_reads_the_new_verdicts_not_the_null_excess():
    """The level-based placebo is DEMOTED to a description; `placebo_passes` is
    the D43 gate. The two are reported side by side so a reader can see that
    they disagree."""
    import inspect

    src = inspect.getsource(bo.dot_validation)
    assert "category_specificity" in src
    assert 'gate["passes"]' in src
    assert "placebo_null_excess_failing" in src


# ------------------------------------------------------------ the printed page

class _Shim:
    """`bod` as `_od_print_specificity` sees it: one report, no warehouse.

    The printer is where a `{value:+.3f}` meets a NaN and raises, or a column
    header outnumbers its row, and neither shows up until someone has run the
    command against the live warehouse for twenty minutes first. Rendering the
    report here costs nothing and catches both.
    """

    THRESHOLDS_PENDING_MESSAGE = bo.THRESHOLDS_PENDING_MESSAGE

    def __init__(self, report):
        self._report = report

    def category_specificity(self, con, window, **kw):
        return self._report


def _render(report) -> str:
    from rich.console import Console

    from loci import cli

    buf = Console(record=True, width=240, force_terminal=False, no_color=True)
    old = cli.console
    cli.console = buf
    try:
        cli._od_print_specificity(_Shim(report), None, None, 0, 0, 0, False)
    finally:
        cli.console = old
    return buf.export_text()


def test_the_printed_page_leads_with_the_diagnostics():
    """Pre-registration ordering, not a style choice: a reader who sees the
    verdict table first has already formed a view by the time the MDE tells them
    the run could not resolve the floor."""
    out = _render(_run("cat:grocery", n_perm=200, n_boot=200))
    assert out.index("diagnostics") < out.index("per-category verdicts")
    assert "Moran" in out and "cosine" in out
    assert "robustness" in out
    assert "ONE family of 17" in out   # seventeen since the owner ruling of 2026-09-22 (D137, brewery)
    assert "expected uninformative" in out
    assert "D43 gate" in out


def test_the_printed_page_survives_a_confounded_run_and_a_missing_statistic():
    killed = _render(_run("pair:bank,clinic", seed=9, n_perm=200, n_boot=200))   # seed: see the kill-rule test
    assert "KILL RULE FIRED" in killed
    assert bo.KILL_RULE_MESSAGE in killed
    empty = {"window": "synthetic",
             "bars": _run("total", n_perm=120, n_boot=120)["bars"],
             "thresholds_pending": False, "n_origin_ntas": 0,
             "n_destination_ntas": 0, "per_category": pd.DataFrame(),
             "diagnostics": {},
             "gate": {"passes": False, "pending": False,
                      "message": "the statistic does not exist"}}
    assert "does not exist" in _render(empty)
