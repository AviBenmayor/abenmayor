"""The D63 supply-revealed age multiplier (model/age_fit.py,
docs/bar_age_nyc.md).

Seven things under test, and the first is the one that matters most.

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
    FIT_PATH,
    FITTED_CATEGORIES,
    FORMULA,
    MULTIPLIER_BOUNDS,
    AgeFitGateFailure,
    apply_age_fit,
    failed_gates,
    load_fit,
    multiplier,
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
            renter_share, under_18_share, age_18_34_share, age_65_plus_share,
            age_18_34_share_moe, age_65_plus_share_moe)
           VALUES (?, ?, ?, 2023, 3000, 80000.0, 0.6, ?, ?, ?, ?, ?)""",
        [address_id, address_id, f"T{address_id}",
         None if age is None else age["under_18"],
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
    assert FITTED_CATEGORIES == ("bar",)
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
    monkeypatch.setattr(af, "fit_bar_curve", lambda *a, **k: (_ for _ in ()).throw(
        AgeFitGateFailure("F2 (Brooklyn Conley CI [0.980, 1.620] includes 1.0)")))
    result = CliRunner().invoke(cli.app, ["age-fit", "fit"])
    assert result.exit_code == 1
    assert "GATE FAILED" in result.stdout and "F2" in result.stdout
