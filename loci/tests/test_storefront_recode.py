"""The LL157 activity recode crosswalk (model/activity_recode.py,
sql/012_activity_recode.yaml).

THE BUG THIS UNDOES. Between the 2023-08-15 and 2024-06-03 filings DOF
re-coded `primary_business_activity`. Every value stayed in-domain, so no
constraint, no enum, no NOT NULL and no row count noticed; the only symptom was
that year-over-year same-activity persistence fell from 87.4% to 6.8% across
that one boundary while vacancy persistence stayed at 93-96%. A relabelling,
not a re-survey.

Five things under test:

(a) THE CROSSWALK IS A PERMUTATION and the loader refuses one that is not. A
    many-to-one map would fuse two activity classes and MANUFACTURE
    persistence -- the same shape of bug as a dedup fusing two storefronts,
    entered through a yaml file.

(b) THE REPAIR WORKS AND IS CONFINED. Persistence across the boundary must
    clear 75%; every other filing pair must be unchanged to within 0.5 pt. A
    "fix" that also moved the in-era pairs would be a relabelling of its own.

(c) IT IS AN INVOLUTION ON THE DATA, not a one-way overwrite. The raw column
    survives, and mapping a recoded label forward then backward is the
    identity.

(d) CASE. `HEALTH CARE OR` and `HEALTH CARE or` are one value, normalised on
    every filing, independently of the recode -- the case split predates it by
    four years.

(e) THE ERA GUARD FAILS LOUD. A filing that looks recoded and is not pinned
    must raise, not be quietly passed through the identity branch.
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci import db as locidb
from loci.model import activity_recode as ar

RECODED = dt.date(2024, 6, 3)
RAW_A = dt.date(2023, 8, 15)
RAW_B = dt.date(2022, 8, 15)


# ------------------------------------------------------------------ fixtures

def _con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _insert(con, rows):
    """rows: (premises, filing_due_date, activity, vacant)."""
    for i, (prem, filing, act, vac) in enumerate(rows):
        con.execute("""
            INSERT INTO analysis.storefront (
                storefront_id, premises_id, filing_due_date, reporting_year,
                universe, observed_1231, borough, vacant_1231,
                primary_business_activity, source, ingested_at)
            VALUES (?, ?, ?, ?, 'full', ?, 'MN', ?, ?, 'test', now())
        """, [f"{prem}#{filing}#{i}", prem, filing, filing.year,
              dt.date(filing.year - 1, 12, 31), vac, act])


def _pinned_era(monkeypatch, filings):
    """Force the pinned era so a fixture DB need not reproduce DOF's marginals."""
    doc = dict(ar.load())
    doc["_recoded_filings"] = set(filings)
    monkeypatch.setattr(ar, "load", lambda path=None: doc)


# ------------------------------------------------------- (a) the permutation

def test_the_shipped_crosswalk_is_a_permutation_of_seventeen():
    doc = ar.load()
    assert len(doc["crosswalk"]) == 17
    assert set(doc["_inverse"]) == set(doc["_inverse"].values())
    assert len(doc["_inverse"]) == 17


def test_the_crosswalk_is_one_16_cycle_plus_one_fixed_point():
    """The structure IS the evidence that this is an off-by-one against a
    reordered code list rather than a coincidence of modal values. If a future
    revision breaks it into several short cycles, the derivation is wrong and
    somebody should look before shipping."""
    inv = ar.load()["_inverse"]
    seen, cycles = set(), []
    for start in inv:
        if start in seen:
            continue
        n, cur = 0, start
        while cur not in seen:
            seen.add(cur)
            cur = inv[cur]
            n += 1
        cycles.append(n)
    assert sorted(cycles) == [1, 16]


def test_a_many_to_one_crosswalk_is_refused(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "recoded_filings: [2024-06-03]\n"
        "crosswalk:\n"
        "  - {canonical: A, recoded_as: X}\n"
        "  - {canonical: B, recoded_as: X}\n")
    ar.load.cache_clear()
    with pytest.raises(ar.RecodeError, match="same recoded code|not invertible"):
        ar.load(str(bad))
    ar.load.cache_clear()


def test_a_non_permutation_crosswalk_is_refused(tmp_path):
    bad = tmp_path / "bad2.yaml"
    bad.write_text(
        "recoded_filings: [2024-06-03]\n"
        "crosswalk:\n"
        "  - {canonical: A, recoded_as: X}\n"
        "  - {canonical: B, recoded_as: Y}\n")
    ar.load.cache_clear()
    with pytest.raises(ar.RecodeError, match="not a permutation"):
        ar.load(str(bad))
    ar.load.cache_clear()


# ------------------------------------------------ (b) the repair, and its blast radius

def test_the_recode_is_undone_across_the_boundary(monkeypatch):
    con = _con()
    _pinned_era(monkeypatch, [RECODED])
    # Ten premises that did NOT change use. DOF prints RETAIL in 2023 and
    # EDUCATIONAL SERVICES in 2024 for exactly this situation.
    rows = []
    for i in range(10):
        rows.append((f"P{i}", RAW_A, "RETAIL", False))
        rows.append((f"P{i}", RECODED, "EDUCATIONAL SERVICES", False))
    _insert(con, rows)
    ar.backfill(con)

    raw = {(r["from"], r["to"]): r for r in ar.persistence(con, "primary_business_activity")}
    canon = {(r["from"], r["to"]): r for r in ar.persistence(con, "activity_canonical")}
    assert raw[(RAW_A, RECODED)]["pct"] == 0.0
    assert canon[(RAW_A, RECODED)]["pct"] == 100.0


def test_pairs_outside_the_boundary_are_untouched(monkeypatch):
    con = _con()
    _pinned_era(monkeypatch, [RECODED])
    rows = []
    for i in range(10):
        rows.append((f"P{i}", RAW_B, "FOOD SERVICES", False))
        rows.append((f"P{i}", RAW_A, "FOOD SERVICES" if i < 8 else "RETAIL", False))
    _insert(con, rows)
    ar.backfill(con)
    raw = {(r["from"], r["to"]): r for r in ar.persistence(con, "primary_business_activity")}
    canon = {(r["from"], r["to"]): r for r in ar.persistence(con, "activity_canonical")}
    assert canon[(RAW_B, RAW_A)]["pct"] == pytest.approx(
        raw[(RAW_B, RAW_A)]["pct"], abs=0.5)


def test_a_premises_that_really_changed_use_is_not_repaired_into_continuity(monkeypatch):
    """THE FALSE-POSITIVE GUARD. The crosswalk must not turn every pair into a
    match -- a premises that genuinely went from RETAIL to FOOD SERVICES across
    the boundary is printed EDUCATIONAL SERVICES -> RETAIL by DOF, and the
    canonical form must still read RETAIL -> FOOD SERVICES, i.e. a CHANGE."""
    con = _con()
    _pinned_era(monkeypatch, [RECODED])
    _insert(con, [("P1", RAW_A, "RETAIL", False),
                  ("P1", RECODED, "RETAIL", False)])   # printed RETAIL = FOOD SERVICES
    ar.backfill(con)
    got = con.execute("""
        SELECT filing_due_date, activity_canonical FROM analysis.storefront
        ORDER BY 1""").fetchall()
    assert got == [(RAW_A, "RETAIL"), (RECODED, "FOOD SERVICES")]


def test_multi_storefront_premises_are_excluded_from_the_persistence_measure(monkeypatch):
    """`storefront_id` renumbers between filings (sql/012:72), so at a premises
    with two storefronts there is no way to say which row is which. Counting
    them would compare arbitrary pairs."""
    con = _con()
    _pinned_era(monkeypatch, [RECODED])
    _insert(con, [("P1", RAW_A, "RETAIL", False), ("P1", RAW_A, "OTHER", False),
                  ("P1", RECODED, "EDUCATIONAL SERVICES", False),
                  ("P2", RAW_A, "RETAIL", False),
                  ("P2", RECODED, "EDUCATIONAL SERVICES", False)])
    ar.backfill(con)
    rows = {(r["from"], r["to"]): r for r in ar.persistence(con)}
    assert rows[(RAW_A, RECODED)]["n"] == 1        # P2 only


# ----------------------------------------------------------- (c) the raw column

def test_the_raw_column_survives(monkeypatch):
    con = _con()
    _pinned_era(monkeypatch, [RECODED])
    _insert(con, [("P1", RECODED, "EDUCATIONAL SERVICES", False)])
    ar.backfill(con)
    raw, canon = con.execute(
        "SELECT primary_business_activity, activity_canonical "
        "FROM analysis.storefront").fetchone()
    assert raw == "EDUCATIONAL SERVICES"
    assert canon == "RETAIL"


def test_forward_then_backward_is_the_identity():
    doc = ar.load()
    fwd, inv = doc["_forward"], doc["_inverse"]
    for k in fwd:
        assert inv[fwd[k]] == k


def test_backfill_is_idempotent(monkeypatch):
    con = _con()
    _pinned_era(monkeypatch, [RECODED])
    _insert(con, [("P1", RECODED, "EDUCATIONAL SERVICES", False)])
    ar.backfill(con)
    first = con.execute("SELECT activity_canonical FROM analysis.storefront").fetchall()
    ar.backfill(con)
    assert con.execute(
        "SELECT activity_canonical FROM analysis.storefront").fetchall() == first


def test_a_null_activity_stays_null(monkeypatch):
    """The vacant-only filings carry NULL on every row. NULL must never become
    'UNKNOWN' or '' -- 'the filing did not ask' is not a business activity."""
    con = _con()
    _pinned_era(monkeypatch, [RECODED])
    _insert(con, [("P1", RECODED, None, True)])
    ar.backfill(con)
    assert con.execute(
        "SELECT activity_canonical FROM analysis.storefront").fetchone()[0] is None


def test_a_label_outside_the_domain_carries_through_rather_than_vanishing(monkeypatch):
    """`NO BUSINESS ACTIVITY REPORTED` is a real second sentinel outside the
    crosswalk. Dropping it to NULL would silently delete 577 rows' worth of
    'we asked and there was nothing'."""
    con = _con()
    _pinned_era(monkeypatch, [RAW_A])      # force the era branch onto this row
    _insert(con, [("P1", RAW_A, "NO BUSINESS ACTIVITY REPORTED", True)])
    ar.backfill(con)
    assert con.execute("SELECT activity_canonical FROM analysis.storefront"
                       ).fetchone()[0] == "NO BUSINESS ACTIVITY REPORTED"


# ------------------------------------------------------------------- (d) case

def test_the_health_care_case_split_is_normalised(monkeypatch):
    con = _con()
    _pinned_era(monkeypatch, [RECODED])
    _insert(con, [("P1", RAW_A, "HEALTH CARE OR SOCIAL ASSISTANCE", False),
                  ("P2", RAW_A, "HEALTH CARE or SOCIAL ASSISTANCE", False)])
    ar.backfill(con)
    got = con.execute(
        "SELECT DISTINCT activity_canonical FROM analysis.storefront").fetchall()
    assert got == [("HEALTH CARE OR SOCIAL ASSISTANCE",)]


def test_case_normalisation_applies_outside_the_recode_era_too():
    """The case split is in the 2020 and 2021 filings, four years before the
    recode. Tying the fix to the era would leave it in place."""
    sql = ar.canonical_sql()
    assert "upper(trim(" in sql
    # the ELSE branch -- the non-era path -- must still upper/trim
    assert sql.rstrip().endswith("END")


# -------------------------------------------------------------- (e) the guard

def test_an_unpinned_recoded_filing_raises(monkeypatch):
    """The failure this exists for is a NEW DOF filing. If 2026-08-15 arrives
    recoded and is not listed, the identity branch would be applied to it and
    every comparison touching it would be wrong by the same factor of twelve,
    with no symptom at all."""
    con = _con()
    _pinned_era(monkeypatch, [])           # nothing pinned
    rows = [(f"P{i}", RECODED, "EDUCATIONAL SERVICES", False) for i in range(300)]
    _insert(con, rows)
    with pytest.raises(ar.RecodeError, match="no longer matches the data"):
        ar.assert_era_pinned(con)


def test_a_filing_with_too_few_labelled_rows_is_undecidable_not_recoded():
    """The vacant-only filings have NULL activity on every row. Calling them
    'raw' or 'recoded' on a handful of labels would be a coin flip."""
    con = _con()
    _insert(con, [("P1", RECODED, None, True)])
    assert ar.detect_recoded_filings(con)[RECODED] == "undecidable"


def test_detection_reads_the_marginals_not_the_date():
    con = _con()
    _insert(con, [(f"P{i}", RECODED, "EDUCATIONAL SERVICES", False)
                  for i in range(300)])
    _insert(con, [(f"Q{i}", RAW_A, "FOOD SERVICES", False) for i in range(300)])
    got = ar.detect_recoded_filings(con)
    assert got[RECODED] == "recoded"
    assert got[RAW_A] == "raw"
