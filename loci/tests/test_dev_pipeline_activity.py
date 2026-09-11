"""The construction-progress axis (sql/014_dev_pipeline_activity.sql,
sources/cities/nyc/dob_permits.py, model/dev_pipeline.activity_weights).

What is under test, and why each one is load-bearing:

(a) THE RULE'S BOUNDARIES, to the day. `active` / `lapsed` / `stalled` are
    separated by two constants (12 months, 5 years) and the owner is about to
    read a Gowanus job list off them. A job one day inside the window and a
    job one day outside must land on opposite sides, and the five-year zombie
    branch must fire ONLY where no expiry is known -- a five-year-old job that
    renewed last month is active, not a zombie.

(b) ABSENCE OF EVIDENCE IS NOT EVIDENCE OF ABANDONMENT. A job with no permit
    row and no old DCP date lands 'n/a', never 'stalled'. Getting this wrong
    turns a coverage hole into a claim that a block was abandoned.

(c) DISJOINTNESS AND THE NON-PARTITION. Every job gets exactly one status; and
    units_active_400m + units_stalled_400m <= units_permitted_400m, never ==,
    because `lapsed` and `n/a` units are in the permitted total and neither
    column. The test pins the inequality so nobody later "fixes" the gap by
    adding the three.

(d) THE DEDUP RULE, one dataset over from sql/011's. A DOB NOW job has one
    permit row per work type plus a row per renewal, and ipu4-2q9a contains
    byte-identical duplicate rows; every aggregate must be min()/max(), which
    is idempotent under duplication. Summing would not show up here as a wrong
    date -- it would show up downstream as a pipeline that does not exist.

(e) THE NULL PATH. `loci pipeline` must run before, after or without `loci
    pipeline-activity`. With no evidence the two address columns are NULL, not
    0: "we have not looked" and "every nearby building is abandoned" are
    different claims.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from loci import db as locidb
from loci.model.dev_pipeline import (
    PIPELINE_COLUMNS,
    TIGHT_ONLY_LABELS,
    activity_weights,
    weight_matrix,
)
from loci.sources.cities.nyc.dob_permits import (
    ACTIVE_MONTHS,
    ACTIVITY_STAGES,
    ACTIVITY_STATUSES,
    ZOMBIE_YEARS,
    _to_date_mixed,
    build_activity,
    classify_activity,
    permit_evidence,
    write_activity,
)

ASOF = dt.date(2026, 9, 11)


def _job(job_number="J1", stage="permitted", issued=None, expires=None,
         permitted=dt.date(2022, 6, 1), complete=None, net_units=100):
    return {"job_number": job_number, "borough": "BK", "stage": stage,
            "net_units": net_units, "date_permitted": permitted,
            "date_complete": complete, "last_permit_issued": issued,
            "last_permit_expires": expires}


def _status(**kw) -> str:
    return classify_activity(pd.DataFrame([_job(**kw)]), asof=ASOF).iloc[0]


# ------------------------------------------------------ (a) the boundaries

def test_twelve_month_issuance_boundary_is_exact():
    """asof - 12 months is INSIDE `active`; one day earlier is not. The whole
    Gowanus reading turns on this edge, so it is pinned to the day."""
    assert _status(issued=dt.date(2025, 9, 11), expires=dt.date(2026, 9, 10)) == "active"
    assert _status(issued=dt.date(2025, 9, 10), expires=dt.date(2026, 9, 10)) == "lapsed"


def test_a_live_expiry_is_active_even_with_an_old_issuance():
    """Either limb of the OR suffices: a permit issued three years ago but
    running until next year is a live authorisation to build."""
    assert _status(issued=dt.date(2023, 1, 1), expires=dt.date(2027, 1, 1)) == "active"
    assert _status(issued=dt.date(2023, 1, 1), expires=ASOF) == "active", \
        "expiry ON asof has not expired yet"


def test_expired_zero_to_twelve_months_is_lapsed_and_beyond_is_stalled():
    assert _status(issued=dt.date(2024, 1, 1), expires=dt.date(2026, 9, 10)) == "lapsed"
    assert _status(issued=dt.date(2024, 1, 1), expires=dt.date(2025, 9, 11)) == "lapsed"
    assert _status(issued=dt.date(2024, 1, 1), expires=dt.date(2025, 9, 10)) == "stalled"


def test_the_five_year_zombie_branch_fires_only_when_no_expiry_is_known():
    """D62 caveat 3's zombie permit. Where an expiry EXISTS it already decides;
    the five-year branch is the fallback for a job whose only date is DCP's
    own permit date, or whose permit rows carry no usable expiry."""
    assert _status(issued=None, expires=None, permitted=dt.date(2019, 1, 1)) == "stalled"
    assert _status(issued=None, expires=None, permitted=dt.date(2024, 1, 1)) == "n/a"
    # five years old but renewed last month -> active, NOT a zombie
    assert _status(issued=dt.date(2026, 8, 1), expires=None,
                   permitted=dt.date(2018, 1, 1)) == "active"
    # the boundary itself
    zombie_edge = dt.date(ASOF.year - ZOMBIE_YEARS, ASOF.month, min(ASOF.day, 28))
    assert _status(issued=None, expires=None,
                   permitted=zombie_edge - dt.timedelta(days=1)) == "stalled"
    assert _status(issued=None, expires=None, permitted=zombie_edge) == "n/a"


def test_a_completed_job_is_complete_whatever_its_permits_say():
    assert _status(stage="complete", issued=dt.date(2015, 1, 1),
                   expires=dt.date(2016, 1, 1)) == "complete"
    # partially_complete WITH a CO: the CO wins, permit activity is history
    assert _status(stage="partially_complete", complete=dt.date(2024, 3, 1),
                   expires=dt.date(2016, 1, 1)) == "complete"
    # partially_complete with NO CO still gets a real activity verdict
    assert _status(stage="partially_complete", issued=dt.date(2026, 5, 1),
                   expires=dt.date(2027, 5, 1)) == "active"


def test_filed_and_withdrawn_are_not_on_this_axis():
    assert _status(stage="filed", permitted=None) == "n/a"
    assert _status(stage="withdrawn", expires=dt.date(2015, 1, 1)) == "n/a", \
        "a withdrawn job is not a stalled job -- nobody is going to finish it"


# ---------------------------------------- (b) no evidence != abandonment

def test_no_permit_evidence_on_a_recent_job_is_na_not_stalled():
    """ipu4-2q9a does not cover every legacy permit. A DCP-permitted job we
    simply could not match must land 'n/a'; calling it 'stalled' would turn a
    coverage hole into a claim that the block was abandoned."""
    assert _status(issued=None, expires=None, permitted=dt.date(2025, 1, 1)) == "n/a"
    assert _status(issued=None, expires=None, permitted=None) == "n/a"


# ------------------------------------- (c) disjointness / non-partition

def test_every_job_gets_exactly_one_known_status():
    jobs = pd.DataFrame([
        _job("A", issued=dt.date(2026, 8, 1)),
        _job("B", expires=dt.date(2026, 3, 1), issued=dt.date(2024, 1, 1)),
        _job("C", expires=dt.date(2020, 1, 1), issued=dt.date(2019, 1, 1)),
        _job("D", stage="complete"),
        _job("E", stage="filed", permitted=None),
    ])
    status = classify_activity(jobs, asof=ASOF)
    assert len(status) == len(jobs)
    assert status.notna().all()
    assert set(status) <= set(ACTIVITY_STATUSES)
    assert list(status) == ["active", "lapsed", "stalled", "complete", "n/a"]


def test_activity_weights_are_subsets_of_permitted_and_do_not_partition_it():
    """active + stalled <= permitted, strictly less whenever a `lapsed` or
    `n/a` job is present. Pinned so nobody later closes the gap by adding the
    three columns together."""
    projects = pd.DataFrame([
        {"stage": "permitted", "net_units": 100, "activity_status": "active",
         "date_complete": None},
        {"stage": "permitted", "net_units": 50, "activity_status": "stalled",
         "date_complete": None},
        {"stage": "permitted", "net_units": 25, "activity_status": "lapsed",
         "date_complete": None},
        {"stage": "permitted", "net_units": 10, "activity_status": "n/a",
         "date_complete": None},
        {"stage": "complete", "net_units": 900, "activity_status": "complete",
         "date_complete": dt.date(2025, 1, 1)},
        # a stalled job that DCP no longer calls permitted contributes nothing
        {"stage": "withdrawn", "net_units": 400, "activity_status": "stalled",
         "date_complete": None},
    ])
    projects["date_complete"] = pd.to_datetime(projects["date_complete"])
    W, labels = weight_matrix(projects, ASOF)
    Wa, alabels = activity_weights(projects)
    assert alabels == list(TIGHT_ONLY_LABELS) == ["active", "stalled"]
    permitted = W[labels.index("permitted")].sum()
    assert permitted == 185                      # 100 + 50 + 25 + 10
    assert Wa[0].sum() == 100
    assert Wa[1].sum() == 50, "the withdrawn 400-unit job must not be counted"
    assert Wa[0].sum() + Wa[1].sum() < permitted, "active + stalled != permitted"


def test_the_two_activity_columns_are_tight_radius_only():
    """No `_800m` twin: two more columns on 767k rows for a question that is a
    5-minute-walk question is the pivot-shaped duplication D61 removed."""
    assert "units_active_400m" in PIPELINE_COLUMNS
    assert "units_stalled_400m" in PIPELINE_COLUMNS
    assert "units_active_800m" not in PIPELINE_COLUMNS
    assert "units_stalled_800m" not in PIPELINE_COLUMNS


# --------------------------------------------------- (d) the dedup rule

def test_permit_evidence_collapses_renewals_and_work_types_without_summing():
    """One DOB NOW job, four work types, several renewals, plus a BIS job that
    the feed reports twice byte-identically. min/max are idempotent under
    duplication; a sum would not be."""
    now = pd.DataFrame([
        {"job_filing_number": "M00528469-I1", "issued_date": "2022-02-15T00:00:00.000",
         "expired_date": "2023-02-15T05:00:00.000"},
        {"job_filing_number": "M00528469-I1", "issued_date": "2026-01-08T00:00:00.000",
         "expired_date": "2027-01-08T05:00:00.000"},
        {"job_filing_number": "M00528469-S3", "issued_date": "2025-12-15T00:00:00.000",
         "expired_date": "2026-12-15T05:00:00.000"},
    ])
    bis = pd.DataFrame([
        {"job__": "321590532", "issuance_date": "05/11/2022", "expiration_date": "05/01/2023"},
        {"job__": "321590532", "issuance_date": "05/11/2022", "expiration_date": "05/01/2023"},
        {"job__": "321590532", "issuance_date": "2023-06-01", "expiration_date": "2024-06-01"},
    ])
    ev = permit_evidence(bis, now, asof=ASOF).set_index("job_number")

    assert set(ev.index) == {"M00528469", "321590532"}, \
        "the -I1/-S3 work-type suffix must be stripped to the 9-char job number"
    assert ev.loc["M00528469", "last_permit_issued"] == dt.date(2026, 1, 8)
    assert ev.loc["M00528469", "first_permit_issued"] == dt.date(2022, 2, 15)
    assert ev.loc["M00528469", "last_permit_expires"] == dt.date(2027, 1, 8)
    assert ev.loc["M00528469", "permit_evidence_source"] == "dob_now_permits"
    # the duplicated BIS row cannot move a date
    assert ev.loc["321590532", "last_permit_issued"] == dt.date(2023, 6, 1)
    assert ev.loc["321590532", "last_permit_expires"] == dt.date(2024, 6, 1)
    assert ev.loc["321590532", "permit_evidence_source"] == "dob_bis_permits"


def test_bis_dates_parse_in_both_published_formats():
    """ipu4-2q9a holds `2014-09-09` and `09/30/2013` in the SAME text column."""
    parsed = _to_date_mixed(pd.Series(["2014-09-09", "09/30/2013", "", "junk"]))
    assert parsed.iloc[0] == pd.Timestamp("2014-09-09")
    assert parsed.iloc[1] == pd.Timestamp("2013-09-30")
    assert pd.isna(parsed.iloc[2]) and pd.isna(parsed.iloc[3])


def test_out_of_range_permit_dates_are_dropped_not_clamped():
    """An issuance in the future is a typo; keeping it would make a dead job
    look renewed. A 2125 expiry would make a zombie permanently active."""
    bis = pd.DataFrame([
        {"job__": "111111111", "issuance_date": "01/01/2099", "expiration_date": "01/01/2125"},
        {"job__": "111111111", "issuance_date": "01/01/2020", "expiration_date": "01/01/2021"},
    ])
    ev = permit_evidence(bis, pd.DataFrame(), asof=ASOF).set_index("job_number")
    assert ev.loc["111111111", "last_permit_issued"] == dt.date(2020, 1, 1)
    assert ev.loc["111111111", "last_permit_expires"] == dt.date(2021, 1, 1)


def test_build_activity_refuses_a_fanned_out_join():
    jobs = pd.DataFrame([_job("J1")])[["job_number", "stage", "net_units",
                                       "date_permitted", "date_complete"]]
    doubled = pd.DataFrame([
        {"job_number": "J1", "last_permit_issued": dt.date(2026, 1, 1),
         "last_permit_expires": dt.date(2027, 1, 1), "permit_evidence_source": "x"},
        {"job_number": "J1", "last_permit_issued": dt.date(2020, 1, 1),
         "last_permit_expires": dt.date(2021, 1, 1), "permit_evidence_source": "x"},
    ])
    with pytest.raises(RuntimeError, match="fanned out"):
        build_activity(jobs, doubled, asof=ASOF)


# ------------------------------------------------------- (e) the NULL path

def test_activity_weights_returns_none_when_no_evidence_has_been_ingested():
    projects = pd.DataFrame([
        {"stage": "permitted", "net_units": 100, "activity_status": None},
        {"stage": "permitted", "net_units": 50, "activity_status": None},
    ])
    Wa, alabels = activity_weights(projects)
    assert Wa is None and alabels == []
    assert activity_weights(projects.drop(columns=["activity_status"])) == (None, [])


def test_write_activity_is_update_only_and_never_touches_stage():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("""
        INSERT INTO analysis.dev_pipeline
          (job_number, borough, job_type, net_units, stage, dcp_status,
           date_permitted, source, provenance, ingested_at)
        VALUES ('J1','BK','New Building',300,'permitted','3. Permitted for Construction',
                DATE '2022-06-01','nyc_dcp_housing_db','br6q-ssj3@25Q4', now()),
               ('J2','BK','New Building',100,'permitted','3. Permitted for Construction',
                DATE '2019-01-01','nyc_dcp_housing_db','br6q-ssj3@25Q4', now()),
               ('J3','MN','New Building',500,'complete','5. Completed Construction',
                DATE '2015-01-01','nyc_dcp_housing_db','br6q-ssj3@25Q4', now())
    """)
    before = con.execute("SELECT job_number, stage, net_units, dcp_status "
                         "FROM analysis.dev_pipeline ORDER BY job_number").fetchall()

    jobs = con.execute("SELECT job_number, stage, net_units, date_permitted, date_complete "
                       "FROM analysis.dev_pipeline WHERE borough='BK' "
                       "ORDER BY job_number").fetchdf()
    evidence = pd.DataFrame([{"job_number": "J1",
                              "last_permit_issued": dt.date(2026, 6, 1),
                              "last_permit_expires": dt.date(2027, 6, 1),
                              "permit_evidence_source": "dob_now_permits"}])
    out = build_activity(jobs, evidence, asof=ASOF)
    out["permit_activity_asof"] = ASOF
    assert write_activity(con, out, ("BK",)) == 2

    after = con.execute("SELECT job_number, stage, net_units, dcp_status "
                        "FROM analysis.dev_pipeline ORDER BY job_number").fetchall()
    assert after == before, "the activity annotation moved a DCP-derived column"
    assert con.execute("SELECT count(*) FROM analysis.dev_pipeline").fetchone()[0] == 3

    got = dict(con.execute("SELECT job_number, activity_status FROM analysis.dev_pipeline "
                           "ORDER BY job_number").fetchall())
    assert got == {"J1": "active", "J2": "stalled", "J3": None}, \
        "MN was out of scope and must keep a NULL status, not inherit BK's"
    prov = con.execute("SELECT provenance FROM analysis.dev_pipeline "
                       "WHERE job_number='J1'").fetchone()[0]
    assert prov.startswith("br6q-ssj3@25Q4 + ipu4-2q9a")

    # idempotent: a second write must not append the provenance string twice
    write_activity(con, out, ("BK",))
    assert con.execute("SELECT provenance FROM analysis.dev_pipeline "
                       "WHERE job_number='J1'").fetchone()[0] == prov

    # the RESET pass: an empty frame clears the axis rather than leaving a
    # stale verdict behind
    assert write_activity(con, out.iloc[0:0], ("BK",)) == 0
    assert con.execute("SELECT count(*) FROM analysis.dev_pipeline "
                       "WHERE activity_status IS NOT NULL").fetchone()[0] == 0


def test_fresh_schema_carries_the_activity_columns_on_both_tables():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)

    def cols(table):
        return {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='analysis' AND table_name=?", [table]).fetchall()}

    assert {"last_permit_issued", "last_permit_expires", "permit_evidence_source",
            "activity_status", "permit_activity_asof"} <= cols("dev_pipeline")
    assert {"units_active_400m", "units_stalled_400m"} <= cols("address")
    assert {"units_active_400m", "units_stalled_400m"} <= cols("address_gaps"), \
        "the address_gaps view must expose the annotation"


def test_the_activity_stages_are_the_ones_the_axis_is_about():
    assert ACTIVITY_STAGES == ("permitted", "partially_complete")
    assert ACTIVE_MONTHS == 12 and ZOMBIE_YEARS == 5
    assert np.isfinite(ACTIVE_MONTHS)
