"""Premises tenure prior (model/storefront_tenure.py, sql/051).

`runs_of` is pure and is where the definitions live: interval-censored runs,
turnovers as occupant changes, bridging a missing year only on a matching
class, edge censoring flags. The table build is pinned to conserve
premises-years, and the address measure's median is checked against a
histogram whose answer is known by construction.
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci import db as locidb
from loci.model import storefront_tenure as st

LON, LAT = -73.95, 40.68


def test_a_single_tenant_for_six_years_is_one_run_censored_both_ends():
    r = st.runs_of([2019, 2020, 2021, 2022, 2023, 2024], [False] * 6, ["RETAIL"] * 6)
    assert r["n_runs"] == 1 and r["n_turnovers"] == 0
    assert r["runs"][0]["years"] == 6
    assert r["left_censored"] and r["right_censored"]
    assert r["mean_run_years"] == 6 and r["current_run_years"] == 6


def test_a_class_change_is_a_turnover_and_two_runs():
    r = st.runs_of([2019, 2020, 2021, 2022], [False] * 4,
                   ["FOOD SERVICES", "FOOD SERVICES", "RETAIL", "RETAIL"])
    assert r["n_runs"] == 2 and r["n_turnovers"] == 1
    assert [x["years"] for x in r["runs"]] == [2, 2]
    assert r["runs"][0]["left"] and not r["runs"][0]["right"]
    assert r["runs"][1]["right"] and not r["runs"][1]["left"]


def test_vacancy_in_the_middle_is_two_turnovers_and_the_run_breaks():
    r = st.runs_of([2019, 2020, 2021], [False, True, False],
                   ["RETAIL", "NO BUSINESS ACTIVITY IDENTIFIED", "RETAIL"])
    assert r["n_turnovers"] == 2 and r["n_runs"] == 2
    assert r["n_years_vacant"] == 1 and r["n_years_occupied"] == 2


def test_a_missing_year_bridges_when_the_class_matches_and_breaks_when_it_does_not():
    same = st.runs_of([2019, 2021], [False, False], ["RETAIL", "RETAIL"])
    assert same["n_runs"] == 1 and same["runs"][0]["years"] == 2   # observed years only
    diff = st.runs_of([2019, 2021], [False, False], ["RETAIL", "FOOD SERVICES"])
    assert diff["n_runs"] == 2 and diff["n_turnovers"] == 1


def test_unobserved_years_are_dropped_not_read_as_vacant():
    r = st.runs_of([2019, 2020, 2021], [False, None, False], ["RETAIL", None, "RETAIL"])
    assert r["n_years_observed"] == 2 and r["n_runs"] == 1 and r["n_turnovers"] == 0


def test_currently_vacant_premises_has_zero_current_run():
    r = st.runs_of([2022, 2023, 2024], [False, False, True], ["RETAIL", "RETAIL", None])
    assert r["current_vacant"] is True and r["current_run_years"] == 0
    assert r["current_activity"] is None and not r["right_censored"]


# ------------------------------------------------------------- the table

def _con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _sf(con, premises, year, vacant, activity, *, universe="full", borough="BK",
        lon=LON, lat=LAT, observed=True):
    con.execute("""
        INSERT INTO analysis.storefront (storefront_id, premises_id, filing_due_date,
            reporting_year, universe, observed_1231, borough, bbl, nta_code, geom,
            vacant_1231, activity_canonical, source, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, '3000010001', 'BK0101', ST_Point(?, ?), ?, ?,
                'test', now())""",
                [f"{premises}-{year}-{universe}", premises,
                 dt.date(year + 1, 6, 30) if universe == "full" else dt.date(year + 1, 1, 31), year,
                 universe, dt.date(year, 12, 31) if observed else None, borough, lon, lat,
                 vacant, activity])


def test_build_conserves_premises_years_and_reads_storefront_year_not_storefront():
    con = _con()
    for y, v, a in [(2019, False, "RETAIL"), (2020, False, "RETAIL"), (2021, True, None),
                    (2022, False, "FOOD SERVICES")]:
        _sf(con, "P1", y, v, a)
    # a vacant_only supplement in a year that also has a full filing must NOT
    # add a premises-year (the pooled double count sql/045 fixed)
    _sf(con, "P1", 2022, True, None, universe="vacant_only")
    _sf(con, "P2", 2023, False, "OTHER")
    _sf(con, "P3", 2023, None, None, observed=False)          # never observed -> not in table
    _df, rep = st.build(con)
    assert rep["_problems"] == []
    assert rep["premises"] == 2 and rep["premises_years"] == 5
    row = con.execute("SELECT n_runs, n_turnovers, n_years_vacant, current_activity, "
                      "mean_run_years FROM analysis.storefront_tenure WHERE premises_id = 'P1'"
                      ).fetchone()
    assert row == (2, 2, 1, "FOOD SERVICES", 1.5)
    nta = con.execute("SELECT n_premises, n_turnovers, turnover_per_premises_year "
                      "FROM analysis.nta_tenure WHERE nta_code = 'BK0101'").fetchone()
    assert nta[0] == 2 and nta[1] == 2 and nta[2] == pytest.approx(2 / 5)


def test_empty_panel_raises():
    with pytest.raises(RuntimeError, match="empty"):
        st.compute(_con())


# ------------------------------------------------------ the address measure

def test_measure_median_is_run_weighted_and_columns_are_guarded(monkeypatch):
    con = _con()
    # P1: runs of 1 and 4 years; P2: run of 2 years -> run lengths {1, 2, 4}, median 2
    for y, v, a in [(2019, False, "RETAIL"), (2020, True, None), (2021, False, "RETAIL"),
                    (2022, False, "RETAIL"), (2023, False, "RETAIL"), (2024, False, "RETAIL")]:
        _sf(con, "P1", y, v, a)
    for y, v, a in [(2023, False, "OTHER"), (2024, False, "OTHER")]:
        _sf(con, "P2", y, v, a)
    st.build(con)
    con.execute("""
        INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, frame, present_count,
            eligible, n_missing, reach_source, reach_hash, graph_version, run_at)
        VALUES ('A1', '3000010001', ?, ?, 'BK', 'lot', 0, TRUE, 0, 'tiers', 'h', 'g', now())""",
                [LON, LAT])

    def fake_sums(points, weight_cols, addresses, **kw):
        out = addresses[["address_id", "borough"]].copy()
        for c in weight_cols:
            out[c] = float(points[c].sum())
        return out, {"radius_m": 400.0, "graph_version": "stub", "points": len(points),
                     "points_without_coordinates": 0, "addresses": len(addresses),
                     "query_nodes": 1}
    monkeypatch.setattr("loci.model.walk_catchment.network_sums", fake_sums)
    _df, rep = st.build_measure(con, ["BK"])
    assert rep["_problems"] == []
    n, turn, med = con.execute("SELECT n_premises_400m, premises_turnover_400m, "
                               "median_tenure_years_400m FROM analysis.address").fetchone()
    assert n == 2 and med == 2.0
    assert turn == pytest.approx(2 / 8)          # P1: 2 turnovers over 6 y; P2: 0 over 2 y
    from loci.model.address_gaps import ADDRESS_COLUMNS
    assert not set(st.ADDRESS_COLUMNS) & set(ADDRESS_COLUMNS)
