"""The residential development-pipeline layer (sql/011_dev_pipeline.sql,
sources/cities/nyc/dcp_housing.py, model/dev_pipeline.py).

Five things under test:

(a) THE DEDUP RULE. A job with an initial TCO plus three renewals plus the
    same CO echoed in both feeds must collapse to ONE row with the EARLIEST
    date and the MAX unit count -- never a sum. This is the double-count bug
    CLAUDE.md warns about in its natural habitat: summing here multiplies a
    300-unit tower by its renewal count and manufactures a pipeline that does
    not exist.

(b) THE STAGE MAPPING, including CO precedence. A CO overrides DCP's stale
    "Permitted" and "Filed", and does NOT override "Completed", "Partially
    Completed" or "Withdrawn". An unmapped DCP status RAISES rather than
    landing as NULL -- a silently-NULL stage drops those units out of
    units_permitted, and nothing downstream could tell.

(c) FAIL LOUD. An empty fetch raises; a missing required column raises; a
    duplicated job_number in the spine raises. A pipeline layer that silently
    ingested nothing reads downstream as "no new residents are coming to any
    gap address" -- the most confident possible way to be wrong.

(d) NON-FILTERING, pinned the way tests/test_address_demand.py pins the demand
    annotation: PIPELINE_COLUMNS is disjoint from analysis.address's screen
    columns, and a real build leaves gap_score / lead_category / n_missing /
    eligible byte-identical.

(e) THE CATCHMENT MATHS on a synthetic line graph, where every network
    distance is known by construction: sums are over JOBS (two jobs at the
    same node both count), 24mo is a strict subset of 60mo, withdrawn and
    negative-unit jobs are excluded, and the nearest large project is the
    nearest job of >= 50 units, not the nearest job.
"""
from __future__ import annotations

import datetime as dt

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from loci import db as locidb
from loci.model.address_gaps import ADDRESS_COLUMNS
from loci.model.dev_pipeline import (
    ADDRESS_SCREEN_COLUMNS,
    LARGE_UNITS,
    PIPELINE_COLUMNS,
    _months_before,
    load_projects,
    node_pipeline_matrix,
    weight_matrix,
    write_pipeline,
)
from loci.sources.cities.nyc.dcp_housing import (
    BORO_CODE,
    STAGE_FROM_DCP,
    build_rows,
    co_evidence,
    normalize_job_number,
    write_dev_pipeline,
)

ASOF = dt.date(2026, 9, 9)


# --------------------------------------------------------------- fixtures

def _line_graph(n=13):
    """n nodes on a W-E line ~100 m apart at NYC latitude -- the same fixture
    shape as tests/test_address_gaps.py and tests/test_conveniences.py, so the
    pipeline's distances are read on the same ruler as the gap screen's."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    dx = 100 / 84400.0
    for i in range(n):
        G.add_node(i, x=-73.98 + i * dx, y=40.75)
    for i in range(n - 1):
        G.add_edge(i, i + 1, length=100.0)
        G.add_edge(i + 1, i, length=100.0)
    return G


def _dcp_row(job_number, status, net=10, boro="3", job_type="New Building",
             filed="2020-01-01", permit=None, complt=None, units_co=None, lon=-73.98):
    return {
        "job_number": job_number, "job_type": job_type, "job_status": status,
        "boro": boro, "bbl": "3000010001", "bin": "3000001",
        "classanet": net, "classainit": 0, "classaprop": net, "units_co": units_co,
        "datefiled": filed, "datepermit": permit, "datecomplt": complt,
        "latitude": 40.75, "longitude": lon,
        "nta2020": "BK0101", "ntaname20": "Testville", "version": "25Q4",
    }


# ------------------------------------------------- (a) the dedup rule

def test_co_evidence_collapses_renewals_to_one_row_never_summing():
    """One job, one initial TCO + three renewals + a final CO, and the same CO
    echoed in the BIS feed. Nine raw rows, ONE output row."""
    now = pd.DataFrame([
        {"job_filing_name": "B00000001", "c_of_o_status": "CO Issued",
         "c_of_o_filing_type": "Initial", "c_of_o_issuance_date": "03/04/24 10:00:00 AM",
         "number_of_dwelling_units": "300"},
        *[{"job_filing_name": "B00000001", "c_of_o_status": "CO Issued",
           "c_of_o_filing_type": "Renewal Without Change",
           "c_of_o_issuance_date": d, "number_of_dwelling_units": "300"}
          for d in ("06/04/24 10:00:00 AM", "09/04/24 10:00:00 AM", "12/04/24 10:00:00 AM")],
        {"job_filing_name": "B00000001", "c_of_o_status": "CO Issued",
         "c_of_o_filing_type": "Final", "c_of_o_issuance_date": "04/01/25 10:00:00 AM",
         "number_of_dwelling_units": "300"},
        # a NON-issued row must not count as occupancy at all
        {"job_filing_name": "B00000002", "c_of_o_status": "In Process",
         "c_of_o_filing_type": "Initial", "c_of_o_issuance_date": "01/02/26 10:00:00 AM",
         "number_of_dwelling_units": "50"},
    ])
    bis = pd.DataFrame([
        {"job_number": "B00000001", "issue_type": "Temporary",
         "c_o_issue_date": "2024-03-04T00:00:00.000", "pr_dwelling_unit": "300"},
        {"job_number": "B00000001", "issue_type": "Final",
         "c_o_issue_date": "2025-04-01T00:00:00.000", "pr_dwelling_unit": "300"},
        # out-of-range typo (bs8b-p36w really contains 2105-11-05): DROPPED
        {"job_number": "B00000003", "issue_type": "Final",
         "c_o_issue_date": "2105-11-05T00:00:00.000", "pr_dwelling_unit": "9"},
    ])
    co = co_evidence(bis, now, asof=ASOF)

    assert list(co["job_number"]) == ["B00000001"], "non-issued and typo rows must not survive"
    row = co.iloc[0]
    assert row["co_first_date"] == dt.date(2024, 3, 4), "earliest TCO, not the final CO"
    assert row["co_units"] == 300, "MAX, not SUM -- 9 rows of 300 is still 300 units"
    assert row["co_type"] == "final", "a final CO anywhere in the job wins"
    assert row["co_source"] == "both"


def test_co_evidence_temporary_only_job_is_flagged_temporary():
    now = pd.DataFrame([
        {"job_filing_name": "M00000009", "c_of_o_status": "CO Issued",
         "c_of_o_filing_type": "Initial", "c_of_o_issuance_date": "05/01/26 10:00:00 AM",
         "number_of_dwelling_units": "120"}])
    co = co_evidence(pd.DataFrame(), now, asof=ASOF)
    assert co.iloc[0]["co_type"] == "temporary"
    assert co.iloc[0]["co_source"] == "dob_now_co"


def test_normalize_job_number_does_not_reformat_across_namespaces():
    assert normalize_job_number(" b00680917 ") == "B00680917"
    assert normalize_job_number("321590532") == "321590532"
    assert normalize_job_number("") is None
    # a BIS number must never acquire a borough letter, nor lose one
    assert normalize_job_number("321590532") != "B21590532"


# ------------------------------------------- (b) stage mapping + precedence

def test_co_overrides_stale_dcp_stages_only():
    dcp = pd.DataFrame([
        _dcp_row("J1", "3. Permitted for Construction", net=200, permit="2022-01-01"),
        _dcp_row("J2", "1. Filed Application", net=30),
        _dcp_row("J3", "5. Completed Construction", net=40, complt="2019-05-05"),
        _dcp_row("J4", "4. Partially Completed Construction", net=60, permit="2021-01-01"),
        _dcp_row("J5", "9. Withdrawn", net=25, permit="2021-01-01"),
        _dcp_row("J6", "3. Permitted for Construction", net=80, permit="2024-06-01"),
    ])
    co = pd.DataFrame([
        {"job_number": j, "co_first_date": dt.date(2026, 5, 1), "co_type": "temporary",
         "co_units": 1, "co_source": "dob_now_co"}
        for j in ("J1", "J2", "J3", "J4", "J5")
    ])
    out = build_rows(dcp, co, ("BK",), asof=ASOF).set_index("job_number")

    assert out.loc["J1", "stage"] == "complete", "stale DCP 'Permitted' loses to a CO"
    assert out.loc["J2", "stage"] == "complete", "stale DCP 'Filed' loses to a CO"
    assert out.loc["J3", "stage"] == "complete"
    assert out.loc["J4", "stage"] == "partially_complete", "DCP's own QA wins on stage 4"
    assert out.loc["J5", "stage"] == "withdrawn", "a withdrawn job stays withdrawn"
    assert out.loc["J6", "stage"] == "permitted", "no CO, no override"
    # earliest of DCP's date and the CO's
    assert out.loc["J3", "date_complete"] == dt.date(2019, 5, 5)
    assert out.loc["J1", "date_complete"] == dt.date(2026, 5, 1)
    assert out.loc["J6", "date_complete"] is None or pd.isna(out.loc["J6", "date_complete"])


def test_unmapped_dcp_status_raises_rather_than_nulling_the_stage():
    dcp = pd.DataFrame([_dcp_row("J9", "7. Some New Status DCP Invented")])
    with pytest.raises(RuntimeError, match="unmapped DCP Job_Status"):
        build_rows(dcp, pd.DataFrame(columns=["job_number", "co_first_date", "co_type",
                                              "co_units", "co_source"]), ("BK",), asof=ASOF)


def test_stage_vocabulary_has_no_under_construction():
    """sql/011 states plainly that `under_construction` is NOT emitted, because
    nothing ingested distinguishes 'permit issued' from 'topped out'. If a
    future change adds it, that header is wrong and this test says so."""
    assert set(STAGE_FROM_DCP.values()) == {
        "filed", "permitted", "partially_complete", "complete", "withdrawn"}


def test_boroughs_are_filtered_and_recoded():
    dcp = pd.DataFrame([_dcp_row("A", "5. Completed Construction", boro="1"),
                        _dcp_row("B", "5. Completed Construction", boro="4")])
    empty = pd.DataFrame(columns=["job_number", "co_first_date", "co_type",
                                  "co_units", "co_source"])
    out = build_rows(dcp, empty, ("MN", "BK"), asof=ASOF)
    assert list(out["borough"]) == ["MN"], "Queens must not survive an MN+BK run"
    assert BORO_CODE == {"1": "MN", "2": "BX", "3": "BK", "4": "QN", "5": "SI"}


# --------------------------------------------------------- (c) fail loud

def test_duplicate_job_number_in_the_spine_raises():
    dcp = pd.DataFrame([_dcp_row("DUP", "5. Completed Construction"),
                        _dcp_row("DUP", "5. Completed Construction")])
    empty = pd.DataFrame(columns=["job_number", "co_first_date", "co_type",
                                  "co_units", "co_source"])
    with pytest.raises(RuntimeError, match="duplicate job_number"):
        build_rows(dcp, empty, ("BK",), asof=ASOF)


def test_no_rows_in_scope_raises():
    dcp = pd.DataFrame([_dcp_row("A", "5. Completed Construction", boro="4")])
    empty = pd.DataFrame(columns=["job_number", "co_first_date", "co_type",
                                  "co_units", "co_source"])
    with pytest.raises(RuntimeError, match="no DCP rows"):
        build_rows(dcp, empty, ("MN", "BK"), asof=ASOF)


# ------------------------------------------------------ (d) non-filtering

def test_pipeline_columns_are_disjoint_from_the_screens_own_columns():
    """The D57/D58 guarantee, at the analysis.address grain: model/
    dev_pipeline.py may never name a column the gap screen owns, so a plain
    re-run of the pipeline cannot move gap_score, lead_category, n_missing or
    eligible. ADDRESS_SCREEN_COLUMNS is also pinned against the writer's own
    list in model/address_gaps.py, so the two cannot drift apart silently."""
    assert ADDRESS_SCREEN_COLUMNS == ADDRESS_COLUMNS
    assert not (set(PIPELINE_COLUMNS) & set(ADDRESS_SCREEN_COLUMNS))
    assert len(set(PIPELINE_COLUMNS)) == len(PIPELINE_COLUMNS) == 14


def test_write_pipeline_is_update_only_and_leaves_the_screen_byte_identical():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("""
        INSERT INTO analysis.address
          (address_id, bbl, lon, lat, units, units_capped, nta_code, neighborhood,
           borough, h3_index, present_count, eligible, gap_score, lead_category,
           lead_excess_m, n_missing, cluster_id, reach_source, reach_hash,
           graph_version, supply_set, supply_hash, run_at)
        VALUES ('A1','1','-73.98',40.75,10,10,'MN01','X','MN','h',13,TRUE,2.5,'laundry',
                300,3,'c','tiers','abc','g','principled','h1', now()),
               ('A2','2','-73.97',40.75,10,10,'MN01','X','MN','h',13,TRUE,1.1,'cafe_bakery',
                20,1,NULL,'tiers','abc','g','principled','h1', now())
    """)
    before = con.execute("SELECT address_id, gap_score, lead_category, n_missing, eligible "
                         "FROM analysis.address ORDER BY address_id").fetchall()

    df = pd.DataFrame([{
        "address_id": "A1", "borough": "MN",
        "units_permitted_400m": 500, "units_permitted_800m": 900,
        "units_completed_24mo_400m": 10, "units_completed_24mo_800m": 20,
        "units_completed_60mo_400m": 40, "units_completed_60mo_800m": 80,
        "nearest_large_project_id": "B1", "nearest_large_project_m": 120.0,
        "nearest_large_project_units": 300, "nearest_large_project_stage": "permitted",
        "nearest_large_project_date": dt.date(2025, 1, 1), "pipeline_asof": ASOF,
        # sql/014: written NULL, not 0, when no permit-activity evidence
        # has been ingested -- "we have not looked" is not "abandoned".
        "units_active_400m": pd.NA, "units_stalled_400m": pd.NA,
    }])
    assert write_pipeline(con, df, ["MN"]) == 1

    after = con.execute("SELECT address_id, gap_score, lead_category, n_missing, eligible "
                        "FROM analysis.address ORDER BY address_id").fetchall()
    assert after == before, "the pipeline annotation moved a screen column"
    assert con.execute("SELECT count(*) FROM analysis.address").fetchone()[0] == 2, \
        "UPDATE-only: no row may be inserted or deleted"
    assert con.execute("SELECT units_permitted_400m FROM analysis.address "
                       "WHERE address_id='A1'").fetchone()[0] == 500
    assert con.execute("SELECT units_permitted_400m FROM analysis.address "
                       "WHERE address_id='A2'").fetchone()[0] is None
    assert con.execute("SELECT units_active_400m FROM analysis.address "
                       "WHERE address_id='A1'").fetchone()[0] is None, \
        "no activity evidence must land as NULL, never as 0"

    # the RESET pass: an address that had exposure and no longer does must go
    # back to NULL, not keep last run's number
    assert write_pipeline(con, df.iloc[0:0], ["MN"]) == 0
    assert con.execute("SELECT units_permitted_400m FROM analysis.address "
                       "WHERE address_id='A1'").fetchone()[0] is None


def test_fresh_schema_carries_all_fourteen_pipeline_columns_on_analysis_address():
    """002_schema.sql's CREATE and the 011/014 ALTERs must agree, or a fresh
    test database and the live database diverge. Fourteen since
    sql/014_dev_pipeline_activity.sql added units_active_400m /
    units_stalled_400m."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='analysis' AND table_name='address'").fetchall()}
    assert set(PIPELINE_COLUMNS) <= cols
    view = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='analysis' AND table_name='address_gaps'").fetchall()}
    assert set(PIPELINE_COLUMNS) <= view, "the address_gaps view must expose the annotation"


# ------------------------------------------------------- (e) the maths

def _project(job, node, units, stage, complete=None, boro="MN"):
    dx = 100 / 84400.0
    return {"job_number": job, "borough": boro, "stage": stage, "net_units": units,
            "date_filed": dt.date(2020, 1, 1), "date_permitted": dt.date(2021, 1, 1),
            "date_complete": complete, "co_type": None, "neighborhood": "X",
            "lon": -73.98 + node * dx, "lat": 40.75}


def test_weight_matrix_windows_are_nested_not_disjoint():
    projects = pd.DataFrame([
        _project("P", 0, 100, "permitted"),
        _project("C1", 1, 200, "complete", dt.date(2025, 6, 1)),   # inside 24mo
        _project("C2", 2, 300, "complete", dt.date(2022, 6, 1)),   # inside 60mo only
        _project("C3", 3, 400, "complete", dt.date(2015, 1, 1)),   # outside both
    ])
    W, labels = weight_matrix(projects, ASOF)
    assert labels == ["permitted", "completed_24mo", "completed_60mo"]
    assert W[0].sum() == 100
    assert W[1].sum() == 200
    assert W[2].sum() == 500, "60mo CONTAINS 24mo -- the two must never be added"
    assert _months_before(dt.date(2026, 9, 9), 24) == dt.date(2024, 9, 9)
    assert _months_before(dt.date(2026, 1, 31), 1) == dt.date(2025, 12, 31)


def test_catchment_sums_and_nearest_large_project_on_a_known_graph():
    """Line graph, node i at i*100 m. Address at node 6.
      node 2  (400 m)  permitted  60 units   <- inside 400 m
      node 4  (200 m)  permitted  10 units   <- inside 400 m, too small to be "large"
      node 4  (200 m)  permitted  25 units   <- SECOND job on the SAME node
      node 12 (600 m)  permitted 500 units   <- 800 m only
      node 5  (100 m)  complete   80 units, CO 2025-06-01  <- inside the 24mo window
      node 5  (100 m)  complete   90 units, CO 2022-06-01  <- 60mo only
    """
    G = _line_graph()
    projects = pd.DataFrame([
        _project("BIG400", 2, 60, "permitted"),
        _project("SMALL", 4, 10, "permitted"),
        _project("SMALL2", 4, 25, "permitted"),
        _project("BIG800", 12, 500, "permitted"),
        _project("DONE24", 5, 80, "complete", dt.date(2025, 6, 1)),
        _project("DONE60", 5, 90, "complete", dt.date(2022, 6, 1)),
    ])
    W, _ = weight_matrix(projects, ASOF)
    idx, acc, (near_d, near_p) = node_pipeline_matrix(G, projects, W, radii=(400.0, 800.0),
                                                      min_component=0)
    n6 = idx[6]

    assert acc[400.0][0][n6] == pytest.approx(95.0), \
        "60 + 10 + 25; two jobs on one node both count, the 600 m job does not"
    assert acc[800.0][0][n6] == pytest.approx(595.0)
    assert acc[400.0][1][n6] == pytest.approx(80.0), "24mo window"
    assert acc[400.0][2][n6] == pytest.approx(170.0), "60mo window CONTAINS the 24mo one"

    # The nearest LARGE project spans EVERY stage -- a finished 90-unit
    # building next door is as real a fact about the block as a permitted one.
    # Node 5 (100 m) hosts DONE24 (80) and DONE60 (90); the node-sharing tie is
    # resolved to the LARGER job, as node_pipeline_matrix documents. SMALL and
    # SMALL2, closer at 200 m, are below the 50-unit bar and must not win.
    assert projects.iloc[near_p[n6]]["job_number"] == "DONE60"
    assert near_d[n6] == pytest.approx(100.0)
    assert LARGE_UNITS == 50

    # An address at node 0 has BIG400 (60 units, 200 m) as its nearest large
    # project -- the completed pair at node 5 is 500 m away.
    n0 = idx[0]
    assert projects.iloc[near_p[n0]]["job_number"] == "BIG400"
    assert near_d[n0] == pytest.approx(200.0)


def test_withdrawn_and_negative_unit_jobs_never_reach_the_measures():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    dcp = pd.DataFrame([
        _dcp_row("KEEP", "3. Permitted for Construction", net=120, permit="2024-01-01"),
        _dcp_row("GONE", "9. Withdrawn", net=400, permit="2023-01-01"),
        _dcp_row("DEMO", "5. Completed Construction", net=-30, job_type="Demolition",
                 complt="2025-01-01"),
    ])
    empty = pd.DataFrame(columns=["job_number", "co_first_date", "co_type",
                                  "co_units", "co_source"])
    rows = build_rows(dcp, empty, ("BK",), asof=ASOF)
    assert write_dev_pipeline(con, rows, ("BK",)) == 3, \
        "the TABLE keeps every job -- the ledger has to balance"

    got = load_projects(con, ["BK"])
    assert list(got["job_number"]) == ["KEEP"], \
        "the MEASURES drop withdrawn jobs and net_units < 1"

    # idempotent: a second write for the same borough replaces, never appends
    write_dev_pipeline(con, rows, ("BK",))
    assert con.execute("SELECT count(*) FROM analysis.dev_pipeline").fetchone()[0] == 3


def test_geometry_is_lon_lat_and_survives_the_round_trip():
    """DuckDB GEOMETRY carries no SRID; EPSG:4326 is a convention this project
    holds in code (db.py). ST_Point(lon, lat) is (x, y) -- getting it backwards
    puts every Brooklyn job in Antarctica and no constraint would catch it."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    dcp = pd.DataFrame([_dcp_row("G1", "5. Completed Construction", complt="2025-01-01")])
    empty = pd.DataFrame(columns=["job_number", "co_first_date", "co_type",
                                  "co_units", "co_source"])
    write_dev_pipeline(con, build_rows(dcp, empty, ("BK",), asof=ASOF), ("BK",))
    lon, lat = con.execute(
        "SELECT ST_X(geom), ST_Y(geom) FROM analysis.dev_pipeline").fetchone()
    assert lon == pytest.approx(-73.98) and lat == pytest.approx(40.75)
    assert -75 < lon < -73 and 40 < lat < 41


def test_units_complete_is_gross_and_net_units_is_net():
    """DCP's Units_CO counts every Class A unit on the CO, including ones that
    already existed; ClassANet is the change. Across completed MN+BK jobs the
    two differ by ~48k units. They must never be subtracted or ratioed."""
    dcp = pd.DataFrame([_dcp_row("X", "5. Completed Construction", net=12,
                                 complt="2025-01-01", units_co=40)])
    empty = pd.DataFrame(columns=["job_number", "co_first_date", "co_type",
                                  "co_units", "co_source"])
    row = build_rows(dcp, empty, ("BK",), asof=ASOF).iloc[0]
    assert row["net_units"] == 12 and row["units_complete"] == 40
    assert np.isnan(row["co_type"]) if isinstance(row["co_type"], float) else row["co_type"] is None
