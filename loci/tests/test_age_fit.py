"""The D63/D64 supply-revealed age multipliers (model/age_fit.py,
docs/bar_age_nyc.md).

Eight things under test, and the first is the one that matters most.

(a) NON-FILTERING, PROVED ON REAL SHAPE. `age_fit` is a SECOND ranking column,
    never a gate (D48: the output is graded, never filtered). Build the screen
    fixture, snapshot every screen-owned quantity -- gap_score, eligible,
    lead_category, n_missing, cluster_id, and the exact SET of (address,
    category) pairs with ratio > 1 -- apply the multiplier, and assert all of it
    is bit-identical. This is the D57 proof re-run for D63, and it is what
    stops the "ranking signal" from quietly becoming a screen.

(b) THE MECHANICAL GUARANTEE (D61). Both SET lists are disjoint from the
    screen's own columns on their respective tables, so the writer CANNOT
    clobber the screen even by accident. Pinned directly rather than trusted to
    a reviewer noticing a future rename.

(c) BAR ONLY, AND NULL != 1.0. Every non-bar category's age_fit is NULL because
    no curve exists for it; age_fit_lead is exactly 1.0 (so gap_score_fit ==
    gap_score) wherever the lead category has no fitted curve. Collapsing those
    two states would turn "we do not know" into "we checked, and it is neutral".

(d) THE OWNER'S EXAMPLE, ON THE LIVE FITTED CURVE (F4). Median age_fit over East
    Village addresses must exceed Carnegie Hill's by MORE than the larger of the
    two median MOEs -- the inequality with its uncertainty attached, not a bare
    one. Integration test: skips when data/interim/age_fit_bar.json is absent.

(e) THE F2 GATE (docs/bar_age_nyc.md §7.1). A curve whose BROOKLYN-only Conley
    CI on the Carnegie-Hill -> East-Village contrast includes 1.0 must be
    REFUSED, and must leave no file behind. F2 is the criterion that binds: it
    is the only reason the composition spec is preferred over the bar-POI count
    spec, and Brooklyn is where 98% of the bar-lead gap set lives.

(f) MOEs TRAVEL. Every fitted row carries a non-NULL age_fit_moe. A multiplier
    without its margin invites exactly the over-reading the note warns about.

(g) VIEW DRIFT. analysis.address_gaps exposes age_fit_lead and gap_score_fit,
    so the webmap and the query app can rank on the annotated score without a
    join they would have to remember to write.

(h) THE D64 REGISTRY. `bar` was shipped first and `childcare` second, so the
    load-bearing risk is that generalizing the estimator moved bar. Two pins:
    the refitted bar coefficients still match the committed
    data/interim/age_fit_bar.json to 3 decimals (integration, skips without the
    warehouse), and applying BOTH curves leaves every bar row bit-identical to
    applying bar alone. Plus the gate applies to the second category exactly as
    to the first -- a childcare curve whose Brooklyn CI includes 1.0, or whose
    point estimate has the WRONG SIGN, is refused and writes nothing. The wrong
    sign matters here because childcare's own count specification has a Brooklyn
    CI that EXCLUDES 1.0 from BELOW (0.542 [0.396, 0.741]): more children, fewer
    childcare POIs. A CI that excludes 1.0 by rejecting the hypothesis is not a
    pass, and without the sign test it would have read as one.

Plus the NEGATIVE pin (§7.2 test 8): the specification is the COMPOSITION one.
A future session must not quietly swap in the bar-POI count outcome, which is
insignificant in Brooklyn and whose outcome is the same supply the screen
already reads.
"""
from __future__ import annotations

import datetime
import json

import pytest

from loci import db as locidb
from loci.model.address_gaps import ADDRESS_CATEGORY_SCREEN_COLUMNS, ADDRESS_COLUMNS
from loci.model.age_fit import (
    ADDRESS_AGE_FIT_COLUMNS,
    AGE_FIT_COLUMNS,
    CURVES,
    FIT_PATH,
    FITTED_CATEGORIES,
    FORMULA,
    MULTIPLIER_BOUNDS,
    AgeFitGateFailure,
    apply_age_fit,
    failed_gates,
    load_fit,
    multiplier,
    spec_for,
    write_fit_if_gates_pass,
)
from loci.model.conveniences import ALLCATS

REACH_HASH, SUPPLY_HASH = "reach0000", "supply0000"

# --- a synthetic curve ------------------------------------------------------
#
# Deliberately NOT the live coefficients: these tests are about the plumbing --
# what gets written, what does not, and what is refused -- and pinning them to a
# fitted number would make them fail every time the curve is honestly re-fitted.
# The live coefficients are exercised by (d) and by the fit command itself.
#
# b18 = +0.4, b65 = -0.5 around a (0.30, 0.20) anchor, so a young tract lands
# above 1.0 and an old tract below it, which is the owner's ordering.
FIT = {
    "spec": "test_curve_v0",
    "b18": 0.4, "b65": -0.5,
    "anchor_w18": 0.30, "anchor_w65": 0.20,
    "cov_age_conley": [[0.040, 0.005], [0.005, 0.080]],
    "by_borough": {"BK": {"n_tracts": 770, "b18": 0.6, "b65": -0.7,
                          "contrast": {"ratio": 1.45, "ci_low": 1.20,
                                       "ci_high": 1.76, "se_log": 0.10}}},
    "multiplier": {"p10": 0.90, "p50": 0.99, "p90": 1.10, "spread": 0.20,
                   "median_moe": 0.055, "dispersion_ratio": 3.61,
                   "min": 0.73, "max": 1.34},
    "inputs": {"acs_year": 2023, "supply_hash": SUPPLY_HASH,
               "n_bar_licences": 0, "n_onprem_licences": 0, "hash": "deadbeef0000"},
}

YOUNG = {"under_18": 0.10, "w18_raw": 0.50, "w65_raw": 0.08}   # w18 .556 w65 .089
OLD = {"under_18": 0.12, "w18_raw": 0.14, "w65_raw": 0.36}     # w18 .159 w65 .409


def _fresh_con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _insert_address(con, address_id: str, *, lead: str, ratios: dict[str, float],
                    nta_code: str, age: dict | None,
                    eligible: bool = True) -> None:
    """One analysis.address row + its 15 analysis.address_category rows + its
    analysis.address_demographics row. `age=None` means the tract publishes no
    age shares -- the fail-closed branch."""
    con.execute(
        """INSERT INTO analysis.address
           (address_id, bbl, lon, lat, units, units_capped, borough, nta_code,
            neighborhood, present_count, eligible, gap_score, lead_category,
            lead_excess_m, n_missing, cluster_id, reach_source, reach_hash,
            graph_version, run_at, supply_set, supply_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [address_id, address_id, -73.98, 40.72, 10.0, 10.0, "BK", nta_code,
         nta_code, 15, eligible, max(ratios.values()) if ratios else 0.5, lead,
         100.0, sum(1 for r in ratios.values() if r > 1.0), f"BK:{lead}:1",
         "tiers", REACH_HASH, "g1", datetime.datetime(2026, 9, 10),
         "principled", SUPPLY_HASH])
    for c in ALLCATS:
        r = ratios.get(c, 0.5)
        con.execute(
            """INSERT INTO analysis.address_category
               (address_id, borough, category, nearest_m, ratio, is_lead, eligible)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [address_id, "BK", c, r * 400.0, r, c == lead, eligible])
    con.execute(
        """INSERT INTO analysis.address_demographics
           (address_id, bbl, tract_geoid, acs_year, population, median_hh_income,
            renter_share, under_18_share, under_18_share_moe,
            age_18_34_share, age_65_plus_share,
            age_18_34_share_moe, age_65_plus_share_moe)
           VALUES (?, ?, ?, 2023, 3000, 80000.0, 0.6, ?, ?, ?, ?, ?, ?)""",
        [address_id, address_id, f"T{address_id}",
         None if age is None else age["under_18"],
         None if age is None else 0.02,
         None if age is None else age["w18_raw"],
         None if age is None else age["w65_raw"],
         None if age is None else 0.03,
         None if age is None else 0.03])


def _seed(con) -> None:
    gaps = {"bar": 2.4, "grocery": 1.6, "laundry": 1.2}
    _insert_address(con, "A_young_bar", lead="bar", ratios=gaps,
                    nta_code="MN0303", age=YOUNG)
    _insert_address(con, "A_old_bar", lead="bar", ratios=gaps,
                    nta_code="MN0802", age=OLD)
    _insert_address(con, "A_grocery_lead", lead="grocery",
                    ratios={"grocery": 3.0, "bar": 1.1}, nta_code="MN0303", age=YOUNG)
    _insert_address(con, "A_no_age", lead="bar", ratios=gaps,
                    nta_code="MN0303", age=None)
    _insert_address(con, "A_not_eligible", lead="bar", ratios=gaps,
                    nta_code="MN0303", age=YOUNG, eligible=False)


def _apply(con, dry_run: bool = False):
    return apply_age_fit(con, ["BK"], fit=FIT, dry_run=dry_run, check_current=False)


# --- (a) non-filtering ------------------------------------------------------

def _screen_fingerprint(con):
    """Every screen-owned quantity the note's F1 names, plus the exact missing
    SET -- so a single flipped value, a reordering, or one pair entering or
    leaving the gap set all fail."""
    addr = con.execute(
        "SELECT address_id, gap_score, eligible, lead_category, n_missing, cluster_id "
        "FROM analysis.address_gaps ORDER BY address_id").fetchall()
    cat = con.execute(
        "SELECT address_id, category, nearest_m, ratio, is_lead, eligible "
        "FROM analysis.address_category ORDER BY address_id, category").fetchall()
    missing = frozenset(con.execute(
        "SELECT address_id, category FROM analysis.address_category "
        "WHERE ratio > 1.0").fetchall())
    return tuple(addr), tuple(cat), missing


def test_the_screen_is_bit_identical_before_and_after_the_multiplier():
    con = _fresh_con()
    _seed(con)
    before = _screen_fingerprint(con)
    cat_df, addr_df, _ = _apply(con)
    assert len(cat_df) > 0 and len(addr_df) > 0
    assert _screen_fingerprint(con) == before


def test_dry_run_writes_nothing_at_all():
    """Not merely "the screen survives": under --dry-run not one age-fit column
    is populated either, so a dry run can never be mistaken for a real one."""
    con = _fresh_con()
    _seed(con)
    before = _screen_fingerprint(con)
    cat_df, _, _ = _apply(con, dry_run=True)
    assert len(cat_df) > 0
    assert _screen_fingerprint(con) == before
    assert con.execute(
        "SELECT count(*) FROM analysis.address_category WHERE age_fit IS NOT NULL"
    ).fetchone()[0] == 0
    assert con.execute(
        "SELECT count(*) FROM analysis.address WHERE gap_score_fit IS NOT NULL"
    ).fetchone()[0] == 0


def test_gap_score_fit_is_gap_score_times_the_lead_multiplier():
    """The ranking column is exactly that product -- so `gap_score` stays
    recoverable from the pair and the multiplier is auditable per address."""
    con = _fresh_con()
    _seed(con)
    _apply(con)
    rows = con.execute(
        "SELECT gap_score, age_fit_lead, gap_score_fit FROM analysis.address "
        "WHERE gap_score_fit IS NOT NULL").fetchall()
    assert rows
    for gs, lead, fit in rows:
        assert fit == pytest.approx(gs * lead, rel=1e-5)


def test_the_multiplier_is_positive_and_bounded():
    """§7.2 test 5: age_fit is exp(.) so it is strictly positive, which is what
    makes gap_score * age_fit monotone in gap_score -- non-filtering by
    construction, not by assertion. A value outside (0.5, 2.0) would mean the
    multiplier is doing more work than the score it multiplies."""
    con = _fresh_con()
    _seed(con)
    _apply(con)
    lo, hi = con.execute(
        "SELECT min(age_fit), max(age_fit) FROM analysis.address_category "
        "WHERE age_fit IS NOT NULL").fetchone()
    assert 0.0 < lo and lo > MULTIPLIER_BOUNDS[0]
    assert hi < MULTIPLIER_BOUNDS[1]


# --- (b) the mechanical guarantee ------------------------------------------

def test_age_fit_columns_are_disjoint_from_the_screens_own():
    """Both writers build their SET clause exclusively from these lists, so
    disjointness IS the non-filtering guarantee (D57/D61)."""
    assert set(AGE_FIT_COLUMNS).isdisjoint(ADDRESS_CATEGORY_SCREEN_COLUMNS)
    assert set(ADDRESS_AGE_FIT_COLUMNS).isdisjoint(ADDRESS_COLUMNS)
    for forbidden in ("gap_score", "ratio", "nearest_m", "eligible",
                      "lead_category", "n_missing", "cluster_id"):
        assert forbidden not in AGE_FIT_COLUMNS
        assert forbidden not in ADDRESS_AGE_FIT_COLUMNS


def test_every_written_column_exists_on_its_table():
    con = _fresh_con()

    def cols(table):
        return {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'analysis' AND table_name = ?", [table]).fetchall()}

    assert set(AGE_FIT_COLUMNS) <= cols("address_category")
    assert set(ADDRESS_AGE_FIT_COLUMNS) <= cols("address")


# --- (c) bar only, and NULL is not 1.0 --------------------------------------

def test_age_fit_is_null_on_every_category_without_a_curve():
    con = _fresh_con()
    _seed(con)
    _apply(con)
    # D64: the registry holds more than one category, but only the curves
    # actually PASSED to apply may write. Everything else stays NULL -- and
    # "in the registry" is not "has a curve": `childcare` is defined here and
    # its D64 fit failed F2, so it ships nothing.
    assert "bar" in FITTED_CATEGORIES and "childcare" in FITTED_CATEGORIES
    assert set(FITTED_CATEGORIES) == set(CURVES)
    stray = con.execute(
        "SELECT count(*) FROM analysis.address_category "
        "WHERE category <> 'bar' AND (age_fit IS NOT NULL OR age_fit_moe IS NOT NULL "
        "OR age_fit_source IS NOT NULL)").fetchone()[0]
    assert stray == 0
    assert con.execute(
        "SELECT count(*) FROM analysis.address_category "
        "WHERE category = 'bar' AND age_fit IS NOT NULL").fetchone()[0] > 0


def test_a_lead_without_a_curve_gets_exactly_one_point_zero():
    """1.0, not the bar multiplier and not NULL: gap_score_fit == gap_score for
    that address, which is the honest reading of "no curve for this lead"."""
    con = _fresh_con()
    _seed(con)
    _apply(con)
    lead, moe, gs, gsf = con.execute(
        "SELECT age_fit_lead, age_fit_lead_moe, gap_score, gap_score_fit "
        "FROM analysis.address WHERE address_id = 'A_grocery_lead'").fetchone()
    assert lead == 1.0
    assert moe is None          # "no curve" is not "a curve with no uncertainty"
    assert gsf == pytest.approx(gs, rel=1e-6)

    # ...and the same for a BAR lead whose tract publishes no age shares.
    lead, moe = con.execute(
        "SELECT age_fit_lead, age_fit_lead_moe FROM analysis.address "
        "WHERE address_id = 'A_no_age'").fetchone()
    assert lead == 1.0 and moe is None
    assert con.execute(
        "SELECT age_fit FROM analysis.address_category "
        "WHERE address_id = 'A_no_age' AND category = 'bar'").fetchone()[0] is None


def test_the_young_tract_outranks_the_old_one_at_equal_gap_score():
    """The owner's request in miniature: two addresses with an identical bar gap
    and opposite age mixes must come apart, in the requested direction."""
    con = _fresh_con()
    _seed(con)
    _apply(con)
    young, old = (con.execute(
        "SELECT gap_score_fit FROM analysis.address WHERE address_id = ?",
        [a]).fetchone()[0] for a in ("A_young_bar", "A_old_bar"))
    assert young > old


def test_a_row_that_leaves_the_fitted_set_has_its_stale_multiplier_cleared():
    """RESET-then-UPDATE: UPDATE has no DELETE to fall back on, so a row that
    carried a multiplier last run and falls out of scope this run would keep it
    forever without the reset pass."""
    con = _fresh_con()
    _seed(con)
    _apply(con)
    assert con.execute("SELECT age_fit FROM analysis.address_category "
                       "WHERE address_id = 'A_young_bar' AND category = 'bar'"
                       ).fetchone()[0] is not None
    con.execute("UPDATE analysis.address_demographics "
                "SET age_18_34_share = NULL WHERE address_id = 'A_young_bar'")
    _apply(con)
    assert con.execute("SELECT age_fit, age_fit_moe, age_fit_source "
                       "FROM analysis.address_category "
                       "WHERE address_id = 'A_young_bar' AND category = 'bar'"
                       ).fetchone() == (None, None, None)


# --- (e) the F2 gate --------------------------------------------------------

def test_a_brooklyn_ci_that_includes_one_is_refused_and_writes_nothing(tmp_path):
    """F2, the criterion the note names as binding. A Brooklyn CI straddling 1.0
    means the effect is not established WHERE THE GAP SET IS, and a multiplier
    fitted where the signal is but shipped where it isn't is precisely the
    failure this gate exists to stop."""
    bad = json.loads(json.dumps(FIT))
    bad["by_borough"]["BK"]["contrast"].update({"ci_low": 0.98, "ci_high": 1.62})
    out = tmp_path / "age_fit_bar.json"

    assert any(g.startswith("F2") for g in failed_gates(bad))
    with pytest.raises(AgeFitGateFailure, match="F2"):
        write_fit_if_gates_pass(bad, out)
    assert not out.exists(), "a curve that fails its own criterion must leave no file"


def test_a_dispersion_ratio_below_one_is_refused(tmp_path):
    """F3, inherited from the CEX predecessor that failed it at 0.10: a
    multiplier whose spread does not clear its own median MOE is noise wearing a
    coefficient."""
    bad = json.loads(json.dumps(FIT))
    bad["multiplier"].update({"spread": 0.02, "median_moe": 0.14,
                              "dispersion_ratio": 0.02 / 0.14})
    out = tmp_path / "age_fit_bar.json"
    assert any(g.startswith("F3") for g in failed_gates(bad))
    with pytest.raises(AgeFitGateFailure, match="F3"):
        write_fit_if_gates_pass(bad, out)
    assert not out.exists()


def test_a_passing_curve_is_written(tmp_path):
    out = tmp_path / "age_fit_bar.json"
    assert failed_gates(FIT) == []
    assert write_fit_if_gates_pass(FIT, out) == out
    assert json.loads(out.read_text())["b18"] == FIT["b18"]


# --- (f) MOEs travel --------------------------------------------------------

def test_every_fitted_row_carries_its_moe():
    con = _fresh_con()
    _seed(con)
    _apply(con)
    orphan = con.execute(
        "SELECT count(*) FROM analysis.address_category "
        "WHERE age_fit IS NOT NULL AND age_fit_moe IS NULL").fetchone()[0]
    assert orphan == 0
    assert con.execute(
        "SELECT count(*) FROM analysis.address_category "
        "WHERE age_fit IS NOT NULL AND age_fit_moe <= 0").fetchone()[0] == 0


def test_the_moe_grows_with_the_acs_share_moe():
    """The MOE is not decorative: doubling the published ACS share MOE must
    widen it, or the delta method has been wired up wrong."""
    con = _fresh_con()
    _seed(con)
    _apply(con)
    tight = con.execute("SELECT age_fit_moe FROM analysis.address_category "
                        "WHERE address_id = 'A_young_bar' AND category = 'bar'"
                        ).fetchone()[0]
    con.execute("UPDATE analysis.address_demographics SET age_18_34_share_moe = 0.12, "
                "age_65_plus_share_moe = 0.12 WHERE address_id = 'A_young_bar'")
    _apply(con)
    wide = con.execute("SELECT age_fit_moe FROM analysis.address_category "
                       "WHERE address_id = 'A_young_bar' AND category = 'bar'"
                       ).fetchone()[0]
    assert wide > tight


# --- (g) view drift ---------------------------------------------------------

def test_the_view_exposes_the_ranking_columns():
    """analysis.address_gaps is GENERATED (address_gaps_view_sql), so a column
    added to analysis.address does not reach the view unless someone adds it to
    the SELECT list. This is that drift check."""
    con = _fresh_con()
    _seed(con)
    _apply(con)
    cols = [d[0] for d in con.execute(
        "SELECT * FROM analysis.address_gaps LIMIT 0").description]
    for c in ADDRESS_AGE_FIT_COLUMNS:
        assert c in cols
    # ...and the older column order is untouched: the new columns are APPENDED.
    assert cols.index("gap_score") < cols.index("gap_score_fit")
    row = con.execute("SELECT gap_score, gap_score_fit FROM analysis.address_gaps "
                      "WHERE address_id = 'A_young_bar'").fetchone()
    assert row[1] > row[0]


# --- the negative pin -------------------------------------------------------

def test_the_specification_is_the_composition_one():
    """§7.2 test 8, pinning a NEGATIVE finding: the outcome is the bar-type
    SHARE of on-premises licences, not a bar count. The count specifications are
    insignificant in Brooklyn -- where 98% of the bar-lead gap set lives -- and
    the bar-POI count's outcome is the same supply the screen already reads,
    which is the tightest form of the rejected D1 trap. A future session must
    re-open §6.1 to change this, not edit a string."""
    assert FORMULA.split("~")[0].strip() == "bar_share_400"
    assert "w18" in FORMULA and "w65" in FORMULA
    assert "median_age" not in FORMULA       # the median-age spec has the sign REVERSED
    assert "lretail_400" in FORMULA          # CNS07 retail jobs, the daytime control
    assert "lfood" not in FORMULA            # CNS18 food-service payroll IS the outcome


def test_the_multiplier_formula_is_the_anchored_exponential():
    """One closed form, checked against arithmetic rather than against itself."""
    import numpy as np
    got = multiplier(0.5, 0.1, b18=0.4, b65=-0.5, anchor_w18=0.3, anchor_w65=0.2)
    assert float(got) == pytest.approx(np.exp(0.4 * 0.2 + (-0.5) * (-0.1)))
    assert float(multiplier(0.3, 0.2, 0.4, -0.5, 0.3, 0.2)) == pytest.approx(1.0)


# --- (d) the owner's example, on the LIVE curve -----------------------------

@pytest.mark.skipif(not FIT_PATH.exists(),
                    reason="no fitted curve; run `loci age-fit fit` first")
def test_east_village_beats_carnegie_hill_by_more_than_its_own_moe():
    """F4, on the live fitted curve and the live warehouse. The owner's example,
    pinned WITH its uncertainty attached rather than as a bare inequality: a
    separation smaller than the MOEs it is built from is not a finding.

    Integration test -- it reads data/loci.duckdb, which is gitignored, so it
    skips on a fresh clone rather than failing there.
    """
    fit = load_fit()
    con = locidb.connect(read_only=True)
    rows: dict[str, tuple] = {}
    for nta in ("MN0303", "MN0802"):
        got = con.execute("""
            SELECT median(c.age_fit), median(c.age_fit_moe), count(*)
            FROM analysis.address a
            JOIN analysis.address_category c
              ON c.address_id = a.address_id AND c.borough = a.borough
            WHERE c.category = 'bar' AND a.nta_code = ? AND c.age_fit IS NOT NULL
        """, [nta]).fetchone()
        if not got or got[2] == 0:
            pytest.skip("age_fit has not been applied to Manhattan; "
                        "run `loci age-fit apply`")
        rows[nta] = got

    ev, ev_moe, _ = rows["MN0303"]
    ch, ch_moe, _ = rows["MN0802"]
    assert ev > ch, f"East Village {ev:.3f} should exceed Carnegie Hill {ch:.3f}"
    assert ev - ch > max(ev_moe, ch_moe), (
        f"separation {ev - ch:.3f} must exceed the larger median MOE "
        f"{max(ev_moe, ch_moe):.3f}")
    # ...and the shipped curve is the one whose gates were checked.
    assert fit["spec"] == "sla_composition_v1"
    assert failed_gates(fit) == []


def test_the_fit_command_exits_non_zero_when_the_gate_fails(monkeypatch):
    """The gate has to be visible to a SHELL, not only to a caller: `make`, a
    cron, or a future pipeline step must be able to stop on it. Pins the exit
    code rather than the message."""
    from typer.testing import CliRunner

    from loci import cli
    from loci.model import age_fit as af

    monkeypatch.setattr(cli.locidb, "connect", lambda *a, **k: None)
    monkeypatch.setattr(af, "fit_curve", lambda *a, **k: (_ for _ in ()).throw(
        AgeFitGateFailure("F2 (Brooklyn Conley CI [0.980, 1.620] includes 1.0)")))
    result = CliRunner().invoke(cli.app, ["age-fit", "fit", "--category", "bar"])
    assert result.exit_code == 1
    assert "GATE FAILED" in result.stdout and "F2" in result.stdout


def test_a_failed_category_still_fails_the_whole_fit_command(monkeypatch):
    """`--category all` must not exit 0 because ONE curve passed. A pipeline
    that stops on the exit code would otherwise sail past a refused curve."""
    from typer.testing import CliRunner

    from loci import cli
    from loci.model import age_fit as af

    def _one_ok_one_gate(con, category, *a, **k):
        if category == "bar":
            return dict(FIT, category="bar", age_terms=["w18", "w65"],
                        coefs={"w18": 0.4, "w65": -0.5},
                        anchors={"w18": 0.3, "w65": 0.2},
                        primary_age_term="w18", n_tracts=1065, r_squared=0.4,
                        radius_m=400.0, se_conley={"w18": 0.2, "w65": 0.28},
                        t_conley={"w18": 2.0, "w65": -1.7},
                        contrast=dict(CC_FIT["contrast"], pooled=FIT["by_borough"]["BK"]["contrast"],
                                      from_name="a", to_name="b"),
                        by_borough={"BK": {"n_tracts": 770, "coefs": {"w18": 0.6, "w65": -0.7},
                                           "se_conley": {"w18": 0.24, "w65": 0.39},
                                           "contrast": FIT["by_borough"]["BK"]["contrast"]}},
                        robustness={},
                        inputs={**FIT["inputs"], "n_target": 1, "n_universe": 2}), None
        raise AgeFitGateFailure("F2 (Brooklyn Conley CI [0.545, 1.078] includes 1.0)")

    monkeypatch.setattr(cli.locidb, "connect", lambda *a, **k: None)
    monkeypatch.setattr(af, "fit_curve", _one_ok_one_gate)
    result = CliRunner().invoke(cli.app, ["age-fit", "fit", "--category", "all"])
    assert result.exit_code == 1
    assert "GATE FAILED" in result.stdout


# --- (h) THE D64 REGISTRY ---------------------------------------------------
#
# A synthetic CHILDCARE curve. Same reason as FIT above: these tests are about
# the plumbing, not the coefficients. `under_18_share` is the primary demand
# variable and enters POSITIVE here, which is the shape the owner's hypothesis
# predicted -- so a test that refuses this curve is refusing something that
# LOOKS right, which is the only kind of gate worth having.
CC_FIT = {
    "category": "childcare",
    "spec": "test_childcare_v0",
    "age_terms": ["under_18_share", "w18", "w65"],
    "primary_age_term": "under_18_share",
    "coefs": {"under_18_share": 0.80, "w18": -0.10, "w65": -0.20},
    "anchors": {"under_18_share": 0.20, "w18": 0.30, "w65": 0.20},
    "cov_age_conley": [[0.050, 0.000, 0.000],
                       [0.000, 0.040, 0.005],
                       [0.000, 0.005, 0.080]],
    "contrast": {"kind": "extreme", "variable": "under_18_share",
                 "require_sign": 1, "min_addresses": 500,
                 "from_nta": "MN0303", "to_nta": "BK1202"},
    "by_borough": {"BK": {"n_tracts": 770,
                          "coefs": {"under_18_share": 0.9, "w18": -0.1, "w65": -0.2},
                          "contrast": {"ratio": 1.60, "ci_low": 1.25,
                                       "ci_high": 2.05, "se_log": 0.12}}},
    "multiplier": {"p10": 0.93, "p50": 1.00, "p90": 1.09, "spread": 0.16,
                   "median_moe": 0.078, "dispersion_ratio": 2.05,
                   "min": 0.80, "max": 1.20},
    "inputs": {"acs_year": 2023, "supply_hash": SUPPLY_HASH,
               "n_target": 0, "n_universe": 0, "hash": "cafe00000000"},
}


def _apply_both(con, dry_run: bool = False):
    return apply_age_fit(con, ["BK"], fits={"bar": FIT, "childcare": CC_FIT},
                         dry_run=dry_run, check_current=False)


def _bar_rows(con):
    return con.execute(
        "SELECT address_id, age_fit, age_fit_moe, age_fit_source "
        "FROM analysis.address_category WHERE category = 'bar' "
        "ORDER BY address_id").fetchall()


def test_adding_a_second_curve_does_not_move_a_single_bar_value():
    """THE D64 REGRESSION PROOF. `bar` shipped first; the whole risk of turning
    a bar-only estimator into a registry is that bar moves. Apply bar alone,
    snapshot every bar row, apply bar AND childcare, and require the bar rows to
    be bit-identical -- not close, identical."""
    con = _fresh_con()
    _seed(con)
    _apply(con)
    before = _bar_rows(con)
    assert any(r[1] is not None for r in before)

    _apply_both(con)
    assert _bar_rows(con) == before

    # ...and childcare now carries its own, DIFFERENT multiplier on the same
    # addresses: two curves, not one curve written twice.
    pairs = con.execute(
        "SELECT b.age_fit, c.age_fit FROM analysis.address_category b "
        "JOIN analysis.address_category c USING (address_id) "
        "WHERE b.category = 'bar' AND c.category = 'childcare' "
        "AND b.age_fit IS NOT NULL").fetchall()
    assert pairs and any(abs(a - b) > 1e-9 for a, b in pairs)


def test_the_lead_multiplier_follows_the_lead_category_not_the_first_curve():
    """With two curves live, `age_fit_lead` must be the multiplier of THIS
    address's own lead. Getting this wrong is invisible in a bar-only world and
    silently wrong the moment a second category ships."""
    con = _fresh_con()
    _insert_address(con, "A_cc_lead", lead="childcare",
                    ratios={"childcare": 2.2, "bar": 1.1},
                    nta_code="BK1202", age=YOUNG)
    _seed(con)
    _apply_both(con)
    lead, moe = con.execute(
        "SELECT age_fit_lead, age_fit_lead_moe FROM analysis.address "
        "WHERE address_id = 'A_cc_lead'").fetchone()
    cc = con.execute(
        "SELECT age_fit, age_fit_moe FROM analysis.address_category "
        "WHERE address_id = 'A_cc_lead' AND category = 'childcare'").fetchone()
    bar = con.execute(
        "SELECT age_fit FROM analysis.address_category "
        "WHERE address_id = 'A_cc_lead' AND category = 'bar'").fetchone()[0]
    assert lead == pytest.approx(cc[0], rel=1e-9)
    assert moe == pytest.approx(cc[1], rel=1e-9)
    assert lead != pytest.approx(bar, rel=1e-9)


def test_the_screen_survives_both_curves_too():
    """(a) re-run for D64: two multipliers cannot do together what neither can
    do alone."""
    con = _fresh_con()
    _seed(con)
    before = _screen_fingerprint(con)
    cat_df, addr_df, _ = _apply_both(con)
    assert len(cat_df) > 0 and len(addr_df) > 0
    assert _screen_fingerprint(con) == before


def test_every_childcare_row_carries_its_moe_too():
    con = _fresh_con()
    _seed(con)
    _apply_both(con)
    n, orphan = con.execute(
        "SELECT count(*) FILTER (WHERE age_fit IS NOT NULL), "
        "count(*) FILTER (WHERE age_fit IS NOT NULL AND age_fit_moe IS NULL) "
        "FROM analysis.address_category WHERE category = 'childcare'").fetchone()
    assert n > 0 and orphan == 0
    # The childcare MOE must actually respond to under_18_share_moe -- its
    # primary regressor -- or the delta method has lost a term.
    tight = con.execute("SELECT age_fit_moe FROM analysis.address_category "
                        "WHERE address_id = 'A_young_bar' AND category = 'childcare'"
                        ).fetchone()[0]
    con.execute("UPDATE analysis.address_demographics SET under_18_share_moe = 0.15 "
                "WHERE address_id = 'A_young_bar'")
    _apply_both(con)
    wide = con.execute("SELECT age_fit_moe FROM analysis.address_category "
                       "WHERE address_id = 'A_young_bar' AND category = 'childcare'"
                       ).fetchone()[0]
    assert wide > tight


def test_a_childcare_curve_whose_brooklyn_ci_straddles_one_is_refused(tmp_path):
    """The D64 gate, unrelaxed (QUESTIONS D15). This is the curve the LIVE fit
    actually produced: Brooklyn [0.545, 1.078]."""
    bad = json.loads(json.dumps(CC_FIT))
    bad["by_borough"]["BK"]["contrast"].update(
        {"ratio": 0.767, "ci_low": 0.545, "ci_high": 1.078})
    out = tmp_path / "age_fit_childcare.json"
    assert any(g.startswith("F2") for g in failed_gates(bad))
    with pytest.raises(AgeFitGateFailure, match="F2"):
        write_fit_if_gates_pass(bad, out)
    assert not out.exists(), "a curve that fails its own criterion must leave no file"


def test_a_significant_contrast_in_the_wrong_direction_is_still_a_failure(tmp_path):
    """The trap D64 walked into and the reason F2 tests the SIGN as well as the
    interval. Childcare's COUNT specification has a Brooklyn CI that excludes
    1.0 -- from BELOW, at 0.542 [0.396, 0.741]: the neighbourhoods with the most
    children have the FEWEST childcare POIs. Read as "the CI excludes 1.0" that
    is a pass; read honestly it is a rejection of the hypothesis, and shipping
    it would rank the neighbourhoods with the most children DOWN."""
    bad = json.loads(json.dumps(CC_FIT))
    bad["by_borough"]["BK"]["contrast"].update(
        {"ratio": 0.542, "ci_low": 0.396, "ci_high": 0.741})
    out = tmp_path / "age_fit_childcare.json"
    gates = failed_gates(bad)
    assert any("WRONG SIGN" in g for g in gates), gates
    with pytest.raises(AgeFitGateFailure, match="F2"):
        write_fit_if_gates_pass(bad, out)
    assert not out.exists()


def test_a_passing_childcare_curve_would_be_written(tmp_path):
    """The gate is a gate, not a veto: the same code writes a curve that clears
    it. Without this, "childcare failed" and "childcare can never pass" are
    indistinguishable."""
    out = tmp_path / "age_fit_childcare.json"
    assert failed_gates(CC_FIT) == []
    assert write_fit_if_gates_pass(CC_FIT, out) == out
    assert json.loads(out.read_text())["coefs"]["under_18_share"] == 0.80


def test_every_registry_curve_declares_its_contrast():
    """DRIFT CHECK. A `CategorySpec` without a resolvable contrast has no F2
    gate, and a curve with no F2 gate is exactly the thing D63 refused to ship.
    Also pins that each category's disc is its OWN reach tier and that every age
    regressor has an ACS MOE column, since a term without its margin would make
    the F3 dispersion gate easier to pass."""
    from loci.model.age_fit import AGE_MOE_COLUMNS, reach_m

    assert set(CURVES) == set(FITTED_CATEGORIES)
    for cat, spec in CURVES.items():
        assert spec.category == cat
        assert spec.age_terms, f"{cat} has no age regressors"
        assert spec.primary_age_term in spec.age_terms
        for t in spec.age_terms:
            assert t in AGE_MOE_COLUMNS, f"{cat}: {t} has no ACS MOE column"
        c = spec.contrast
        assert c.kind in ("fixed", "extreme")
        if c.kind == "fixed":
            assert c.from_nta and c.to_nta
        else:
            assert c.variable in spec.age_terms
            assert c.min_addresses > 0
        assert c.require_sign in (-1, 0, 1)
        assert spec.radius_m == reach_m(cat), (
            f"{cat}'s disc must be its own reach tier, not a copied constant")
        assert spec.fit_path.name == f"age_fit_{cat}.json"
        # the formula names the radius, so changing the tier invalidates the fit
        assert f"_{spec.r}" in spec.formula
        # ...and any curve ALREADY on disk carries the fields the gate reads.
        # A fit JSON without them would make failed_gates() silently vacuous,
        # which is the one way a refused curve could reach the ranking.
        if not spec.fit_path.exists():
            continue
        on_disk = load_fit(category=cat)
        assert on_disk["category"] == cat
        for field in ("kind", "from_nta", "to_nta", "require_sign", "pooled"):
            assert field in on_disk["contrast"], f"{cat}: contrast.{field} missing"
        assert "BK" in on_disk["by_borough"], f"{cat}: no Brooklyn fit, F2 is vacuous"
        for field in ("ratio", "ci_low", "ci_high"):
            assert field in on_disk["by_borough"]["BK"]["contrast"]
        assert "dispersion_ratio" in on_disk["multiplier"]
        assert set(on_disk["age_terms"]) == set(spec.age_terms)


def test_the_childcare_specification_is_the_composition_one():
    """The D64 negative pin, the childcare twin of §7.2 test 8. The shipped
    outcome is the childcare SHARE of all canonical POIs, not a childcare count:
    the count specification's Brooklyn effect is significantly NEGATIVE, and
    swapping it in would rank family neighbourhoods down."""
    spec = spec_for("childcare")
    assert spec.formula.split("~")[0].strip() == "childcare_share_640"
    assert spec.primary_age_term == "under_18_share"
    assert "w18" in spec.formula and "w65" in spec.formula   # placebo comparability
    assert "lretail_640" in spec.formula                     # CNS07, the daytime control
    assert "median_age" not in spec.formula
    assert "count" in spec.robustness_outcomes               # reported, never shipped


# --- (h) the live curves ----------------------------------------------------

@pytest.mark.skipif(not FIT_PATH.exists(),
                    reason="no fitted bar curve; run `loci age-fit fit` first")
def test_the_refitted_bar_curve_reproduces_the_committed_one():
    """D64's load-bearing integration test: after the registry refactor,
    re-fitting `bar` must reproduce the committed data/interim/age_fit_bar.json
    to 3 decimals. Three decimals rather than exactly, because the fit is
    re-estimated from the live warehouse rather than replayed -- but the
    specification, the sample and the SEs must be the same ones."""
    from loci.model import age_fit as af

    committed = load_fit()
    con = locidb.connect(read_only=True)
    fit, path = af.fit_curve(con, "bar", dry_run=True)
    assert path is None                     # dry run writes nothing
    assert fit["formula"] == committed["formula"]
    assert fit["n_tracts"] == committed["n_tracts"]
    for k in ("b18", "b65", "b18_se_conley", "b65_se_conley",
              "anchor_w18", "anchor_w65"):
        assert fit[k] == pytest.approx(committed[k], abs=5e-4), k
    for k in ("ratio", "ci_low", "ci_high"):
        assert fit["by_borough"]["BK"]["contrast"][k] == pytest.approx(
            committed["by_borough"]["BK"]["contrast"][k], abs=5e-4), k
    assert fit["inputs"]["hash"] == committed["inputs"]["hash"]
    assert failed_gates(fit) == []


@pytest.mark.skipif(not spec_for("childcare").fit_path.exists(),
                    reason="childcare has no fitted curve (D64: it failed F2)")
def test_the_childcare_ordering_on_the_live_curve():
    """F4 for childcare, the twin of the East-Village test. IF a childcare curve
    is ever written, the NTA with the most children must carry a HIGHER median
    multiplier than the NTA with the fewest, by more than the larger of the two
    median MOEs.

    This test SKIPS today, and that is the finding, not an omission: the D64 fit
    failed F2 (Brooklyn 0.767 [0.545, 1.078]) so no curve exists to test. It is
    written now so that a future re-fit -- a childcare registry anchor, a new
    ACS vintage -- cannot ship without clearing it.
    """
    fit = load_fit(category="childcare")
    con = locidb.connect(read_only=True)
    rows: dict[str, tuple] = {}
    for nta in (fit["contrast"]["to_nta"], fit["contrast"]["from_nta"]):
        got = con.execute("""
            SELECT median(c.age_fit), median(c.age_fit_moe), count(*)
            FROM analysis.address a
            JOIN analysis.address_category c
              ON c.address_id = a.address_id AND c.borough = a.borough
            WHERE c.category = 'childcare' AND a.nta_code = ?
              AND c.age_fit IS NOT NULL
        """, [nta]).fetchone()
        if not got or got[2] == 0:
            pytest.skip("age_fit has not been applied to childcare; "
                        "run `loci age-fit apply`")
        rows[nta] = got

    hi, hi_moe, _ = rows[fit["contrast"]["to_nta"]]
    lo, lo_moe, _ = rows[fit["contrast"]["from_nta"]]
    assert hi > lo, (f"{fit['contrast']['to_name']} {hi:.3f} should exceed "
                     f"{fit['contrast']['from_name']} {lo:.3f}")
    assert hi - lo > max(hi_moe, lo_moe), (
        f"separation {hi - lo:.3f} must exceed the larger median MOE "
        f"{max(hi_moe, lo_moe):.3f}")
    assert failed_gates(fit) == []
