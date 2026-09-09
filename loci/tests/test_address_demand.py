"""The D49 demand annotation at the D38 address grain (GTM-110,
model/address_demand.py + analysis.address_demand).

Four things under test:

(a) NON-FILTERING BY CONSTRUCTION. analysis.address_gaps' `gap_score` and
    `lead_category` are byte-identical before and after a build, and the
    ratio > 1 rows of address_demand are EXACTLY address_gaps' own missing
    set -- no pair invented, none dropped. The only rows beyond that set are
    lead rows with ratio <= 1 (an eligible address with no gap still gets its
    headline category annotated), and the test asserts that is the only
    excess. This is D48's "graded, never filtered" made mechanical.

(b) THE MOE GATE, on a tiny synthetic fixture. Confidently below the line ->
    caveat. Within one MOE of the line -> income_indeterminate, no caveat.
    MOE missing entirely -> no MOE, no assertion, no caveat (fails closed).
    This is the whole reason D49 retired the binary badge, so it is pinned
    directly rather than inferred from a production run.

(c) The class gate: a necessity is never caveated however poor the address,
    and clinic is never caveated at all (D30) even though it is missing like
    anything else.

(d) DRIFT against the frozen hex implementation. model/gaps.py is frozen
    history under D38 and keeps its own private copies of the ratio-MOE
    formula and the caveat wording; while both exist they must agree, so
    `loci.demand.ratio_moe` is pinned against `gaps._ratio_moe` and the
    address caveat string against `gaps._caveat_text` for the same inputs.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from loci import db as locidb
from loci.demand import X6_DISCLAIMER, load_demand, ratio_moe
from loci.model.address_demand import (
    ADDRESS_DEMAND_COLUMNS,
    build_address_demand,
    caveat_text,
    compute_address_demand,
    income_context,
)
from loci.model.conveniences import ALLCATS

# tests/ has no __init__.py, so conftest is a plain top-level module here.
from conftest import TEST_CITYWIDE_MEAN_HH_INCOME as CITYWIDE
from conftest import TEST_CITYWIDE_MEAN_HH_INCOME_MOE as CITYWIDE_MOE

CITYWIDE_PAIR = (CITYWIDE, CITYWIDE_MOE)
CUTOFF = 0.80

# --- the synthetic fixture --------------------------------------------------
#
# Four addresses in one borough, chosen so each exercises exactly one branch
# of the MOE gate against the pinned citywide mean ($127,894, cutoff
# $102,315). `restaurant` is discretionary (caveat-eligible), `grocery` is a
# necessity, `clinic` is discretionary-excluded... in fact clinic is derived
# as a necessity AND carries annotate:false, so it is doubly excluded (D30).
#
#   A_low   $30,000 +/- $6,000   ratio 0.235 +/- 0.047 -> confidently low
#   A_edge  $102,000 +/- $20,000 ratio 0.798 +/- 0.157 -> straddles the line
#   A_nomoe $30,000, MOE NULL                          -> unknown MOE
#   A_high  $200,000 +/- $6,000  ratio 1.564 +/- 0.047 -> confidently high
LOW, LOW_MOE = 30_000.0, 6_000.0
EDGE, EDGE_MOE = 102_000.0, 20_000.0
HIGH, HIGH_MOE = 200_000.0, 6_000.0

REACH_HASH, SUPPLY_HASH = "reach0000", "supply0000"


def _fresh_con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _insert_address(con, address_id: str, *, ratios: dict[str, float],
                    lead: str | None, eligible: bool = True,
                    income: float | None, income_moe: float | None) -> None:
    """One analysis.address_gaps row + its analysis.address_demographics row.
    `ratios` names the categories with ratio > 1 (their nearest_m is set to
    ratio * 400 m, an arbitrary but consistent reach); every other category
    gets ratio 0.5."""
    cols = ["address_id", "bbl", "lon", "lat", "units", "units_capped", "borough",
            "present_count", "eligible", "gap_score", "lead_category",
            "lead_excess_m", "n_missing", "reach_source", "reach_hash",
            "graph_version", "run_at", "supply_set", "supply_hash"]
    vals = [address_id, address_id, -73.98, 40.75, 10.0, 10.0, "BK",
            15, eligible,
            max(ratios.values()) if ratios else 0.5,
            lead, 100.0, len(ratios), "tiers", REACH_HASH,
            "g1", datetime.datetime(2026, 9, 9), "principled", SUPPLY_HASH]
    for c in ALLCATS:
        r = ratios.get(c, 0.5)
        cols += [f"{c}_ratio", f"{c}_nearest_m"]
        vals += [r, r * 400.0]
    holes = ", ".join("?" for _ in vals)
    con.execute(f"INSERT INTO analysis.address_gaps ({', '.join(cols)}) VALUES ({holes})", vals)
    con.execute(
        "INSERT INTO analysis.address_demographics "
        "(address_id, bbl, tract_geoid, acs_year, median_hh_income, median_hh_income_moe) "
        "VALUES (?, ?, 'T1', 2023, ?, ?)", [address_id, address_id, income, income_moe])


def _seed(con) -> None:
    common = {"restaurant": 2.0, "grocery": 1.5, "clinic": 3.0}
    _insert_address(con, "A_low", ratios=common, lead="clinic",
                    income=LOW, income_moe=LOW_MOE)
    _insert_address(con, "A_edge", ratios=common, lead="clinic",
                    income=EDGE, income_moe=EDGE_MOE)
    _insert_address(con, "A_nomoe", ratios=common, lead="clinic",
                    income=LOW, income_moe=None)
    _insert_address(con, "A_high", ratios=common, lead="clinic",
                    income=HIGH, income_moe=HIGH_MOE)


def _build(con):
    return compute_address_demand(con, ["BK"], citywide=CITYWIDE_PAIR, cutoff=CUTOFF)


def _isna(v) -> bool:
    """pandas NA-aware "is null". The nullable annotation columns come back as
    NaN rather than None once pandas has typed the column (float64 for the
    ratios, the string dtype for the text) -- DuckDB maps both to SQL NULL on
    insert, verified by the DDL round-trip, so the assertion that matters is
    "is missing", not "is the None object"."""
    return bool(pd.isna(v))


def _row(df, address_id, category):
    m = df[(df["address_id"] == address_id) & (df["category"] == category)]
    assert len(m) == 1, f"expected exactly one ({address_id}, {category}) row, got {len(m)}"
    return m.iloc[0]


# --- (a) non-filtering ------------------------------------------------------

def test_address_gaps_is_byte_identical_before_and_after_the_build():
    """The annotation is a SIBLING table (D48: graded, never filtered). Build
    it against a live DB and assert address_gaps' row count, gap_score and
    lead_category are untouched -- a checksum over the ordered pairs, so a
    reordering or a single flipped value both fail."""
    con = _fresh_con()
    _seed(con)

    def fingerprint():
        rows = con.execute(
            "SELECT address_id, gap_score, lead_category, n_missing, eligible "
            "FROM analysis.address_gaps ORDER BY address_id").fetchall()
        return len(rows), tuple(rows)

    before = fingerprint()
    n, df = build_address_demand(con, ["BK"], citywide=CITYWIDE_PAIR, cutoff=CUTOFF)
    assert n == len(df) > 0
    assert fingerprint() == before


def test_rows_above_ratio_one_are_exactly_the_missing_set():
    """No (address, category) pair invented and none dropped. The ONLY rows
    beyond address_gaps' own missing set are lead rows whose ratio is <= 1 --
    the "always annotate the lead" clause -- and nothing else may be there."""
    con = _fresh_con()
    _seed(con)
    df = _build(con)

    missing = set()
    for cat in ALLCATS:
        for (aid,) in con.execute(
            f"SELECT address_id FROM analysis.address_gaps WHERE {cat}_ratio > 1.0"
        ).fetchall():
            missing.add((aid, cat))

    got = {(r.address_id, r.category) for r in df.itertuples()}
    above = {(r.address_id, r.category) for r in df.itertuples() if r.ratio > 1.0}
    assert above == missing

    extra = got - missing
    for aid, cat in extra:
        assert bool(_row(df, aid, cat)["is_lead"]), (aid, cat)
    # ... and therefore the annotation can never exceed the missing set by
    # more than one lead row per address.
    assert len(got) <= len(missing) + df["address_id"].nunique()


def test_columns_match_the_ddl():
    """Drift check: the frame's column list is the table's column list."""
    con = _fresh_con()
    _seed(con)
    df = _build(con)
    assert list(df.columns) == ADDRESS_DEMAND_COLUMNS
    cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'address_demand' ORDER BY ordinal_position").fetchall()]
    assert cols == ADDRESS_DEMAND_COLUMNS


# --- (b) the MOE gate -------------------------------------------------------

def test_confidently_below_the_cutoff_is_caveated():
    con = _fresh_con()
    _seed(con)
    df = _build(con)
    r = _row(df, "A_low", "restaurant")
    assert r["demand_class"] == "discretionary"
    assert r["income_ratio"] == pytest.approx(LOW / CITYWIDE)
    assert r["income_ratio_moe"] == pytest.approx(
        ratio_moe(LOW, LOW_MOE, CITYWIDE, CITYWIDE_MOE))
    assert r["income_ratio"] + r["income_ratio_moe"] < CUTOFF
    assert r["income_indeterminate"] is False
    assert bool(r["demand_caveat"]) is True
    assert r["demand_caveat_text"] and r["demand_caveat_text"].endswith(X6_DISCLAIMER)


def test_within_one_moe_is_indeterminate_and_never_caveated():
    """The defect D49 fixed: an address whose income sits inside its own
    margin of the cutoff is a coin flip, and a coin flip must not produce an
    assertion about demand."""
    con = _fresh_con()
    _seed(con)
    df = _build(con)
    r = _row(df, "A_edge", "restaurant")
    assert r["income_indeterminate"] is True
    assert bool(r["demand_caveat"]) is False
    assert _isna(r["demand_caveat_text"])


def test_missing_moe_fails_closed():
    """No MOE, no assertion. income_ratio is still reported (it is a fact),
    but income_ratio_moe and income_indeterminate are NULL and no caveat is
    emitted -- even though the POINT estimate is far below the cutoff."""
    con = _fresh_con()
    _seed(con)
    df = _build(con)
    r = _row(df, "A_nomoe", "restaurant")
    assert r["income_ratio"] == pytest.approx(LOW / CITYWIDE)
    assert r["income_ratio"] < CUTOFF, "the point estimate alone would have caveated"
    assert _isna(r["income_ratio_moe"])
    assert r["income_indeterminate"] is None
    assert bool(r["demand_caveat"]) is False
    assert _isna(r["demand_caveat_text"])


def test_confidently_above_the_cutoff_is_not_caveated():
    con = _fresh_con()
    _seed(con)
    df = _build(con)
    r = _row(df, "A_high", "restaurant")
    assert r["income_indeterminate"] is False
    assert bool(r["demand_caveat"]) is False
    assert _isna(r["demand_caveat_text"])


def test_income_context_branches_directly():
    """The same three branches on the scalar helper the production path calls
    once per distinct (income, MOE) pair -- no second implementation exists."""
    low = income_context(LOW, LOW_MOE, CITYWIDE, CITYWIDE_MOE, CUTOFF)
    assert low.confidently_low is True and low.income_indeterminate is False

    edge = income_context(EDGE, EDGE_MOE, CITYWIDE, CITYWIDE_MOE, CUTOFF)
    assert edge.confidently_low is False and edge.income_indeterminate is True

    nomoe = income_context(LOW, None, CITYWIDE, CITYWIDE_MOE, CUTOFF)
    assert nomoe.confidently_low is False
    assert nomoe.income_ratio_moe is None and nomoe.income_indeterminate is None

    none = income_context(None, None, CITYWIDE, CITYWIDE_MOE, CUTOFF)
    assert none.income_ratio is None and none.confidently_low is False


# --- (c) the class gate -----------------------------------------------------

def test_necessity_is_never_caveated_however_low_the_income():
    con = _fresh_con()
    _seed(con)
    df = _build(con)
    r = _row(df, "A_low", "grocery")
    assert r["demand_class"] == "necessity"
    assert bool(r["demand_caveat"]) is False
    assert _isna(r["demand_caveat_text"])


def test_clinic_is_annotated_but_never_caveated():
    """D30: clinic is missing like anything else and gets a row, but loci's
    clinic layer is not trusted enough to assert a demand explanation on."""
    con = _fresh_con()
    _seed(con)
    df = _build(con)
    r = _row(df, "A_low", "clinic")
    assert bool(r["is_lead"]) is True
    assert bool(r["demand_caveat"]) is False
    assert _isna(r["demand_caveat_text"])


# --- (d) drift against the frozen hex implementation ------------------------

def test_shared_ratio_moe_matches_the_frozen_gaps_copy():
    """gaps.py is frozen under D38 and keeps its own private `_ratio_moe`.
    While both exist they must be the same formula."""
    from loci.model.gaps import _ratio_moe as frozen
    cases = [(LOW, LOW_MOE), (EDGE, EDGE_MOE), (HIGH, HIGH_MOE), (LOW, None)]
    for x, x_moe in cases:
        assert ratio_moe(x, x_moe, CITYWIDE, CITYWIDE_MOE) == frozen(
            x, x_moe, CITYWIDE, CITYWIDE_MOE)


def test_caveat_wording_mirrors_the_frozen_gaps_copy():
    """Same sentence, same numbers, same X6 tail -- so the address annotation
    and the frozen hex annotation cannot say different things about the same
    income and category."""
    import dataclasses

    from loci.model.gaps import IncomeContext, _caveat_text

    demand = load_demand()
    ic = income_context(LOW, LOW_MOE, CITYWIDE, CITYWIDE_MOE, CUTOFF)
    hex_ic = IncomeContext(
        median_hh_income=LOW, renter_share=0.5, income_class="low",
        income_ratio=ic.income_ratio, income_ratio_moe=ic.income_ratio_moe,
        income_indeterminate=ic.income_indeterminate,
        confidently_low=ic.confidently_low,
    )
    assert caveat_text(ic, "restaurant", demand) == _caveat_text(
        hex_ic, ["restaurant"], demand)

    # ...and it fails closed the same way when the address is not confidently low.
    not_low = dataclasses.replace(ic, confidently_low=False)
    assert caveat_text(not_low, "restaurant", demand) is None
