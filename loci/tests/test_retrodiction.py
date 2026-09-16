"""Retrodiction: cohort construction, supply-as-of-t leakage, censoring, and
the gate that refuses a hazard model with no events.

No network, no warehouse. Every case runs against a SYNTHETIC in-memory DuckDB
built row by row here, because the three things worth pinning are boundaries:

  * a competitor that opens AFTER t must not count toward the score at t
    (otherwise the "score at opening" already knows the openings it is meant to
    predict, and the entry model is regressing the outcome on itself);
  * a censored location — D79's 40% with no date at all — must be INCLUDED by
    default and EXCLUDED under --strict-dated, and the two must give different
    answers, or the sensitivity is decorative;
  * the survival gate must refuse when the observable-closure count is below
    the power floor, no matter how large the cohort is.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from loci.model import supply_asof
from loci import db as locidb
from loci.validation import retrodiction as rd


# ---------------------------------------------------------------------------
# a minimal warehouse: the two tables supply_as_of / build_cohort read
# ---------------------------------------------------------------------------
@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    # The open/closed predicate's as-of date is pinned in analysis.supply_asof
    # (owner ruling 2026-09-16): every SQL rendering of
    # model/poi_presence.poi_is_open binds that table by name, so a scratch
    # warehouse needs it exactly as db.init_schema creates it.
    supply_asof.ensure_table(c)
    c.execute("""CREATE TABLE analysis.poi_presence (
        location_key VARCHAR, category VARCHAR, display_name VARCHAR,
        lon DOUBLE, lat DOUBLE, borough VARCHAR,
        first_seen_kind VARCHAR, first_seen_src_field VARCHAR,
        first_seen_src_date DATE, poi_id_latest VARCHAR)""")
    c.execute("CREATE TABLE analysis.poi_supply (poi_id VARCHAR, in_principled BOOLEAN)")
    return c


def _add(con, key, cat, lon, lat, kind, date, principled=True,
         borough="Brooklyn", field="opened_on"):
    con.execute("INSERT INTO analysis.poi_presence VALUES (?,?,?,?,?,?,?,?,?,?)",
                [key, cat, key, lon, lat, borough, kind, field, date, f"poi:{key}"])
    con.execute("INSERT INTO analysis.poi_supply VALUES (?, ?)",
                [f"poi:{key}", principled])


#: Gowanus-ish. At this latitude 0.001 deg of longitude is ~84 m, so the
#: offsets below are comfortably inside and outside a 400 m radius.
LON, LAT = -73.990, 40.675


# ===========================================================================
# supply as of t — the leakage rule
# ===========================================================================
def test_a_competitor_that_opens_after_t_does_not_count(con):
    """THE LEAKAGE TEST. This is the one that matters."""
    _add(con, "before", "restaurant", LON + 0.001, LAT, "source_date", dt.date(2022, 6, 1))
    _add(con, "after", "restaurant", LON + 0.0011, LAT, "source_date", dt.date(2023, 6, 1))

    pts = pd.DataFrame({"point_id": ["p"], "lon": [LON], "lat": [LAT]})
    at_t0 = rd.supply_as_of(con, pts, asof=dt.date(2023, 1, 1),
                            categories=("restaurant",), include_censored=False)
    later = rd.supply_as_of(con, pts, asof=dt.date(2024, 1, 1),
                            categories=("restaurant",), include_censored=False)

    assert int(at_t0["supply"].iloc[0]) == 1, "the 2023-06 opening leaked into 2023-01"
    assert int(later["supply"].iloc[0]) == 2


def test_censored_locations_are_included_by_default_and_dropped_under_strict(con):
    """D79's undated 40% are a CHOICE, and the choice has to move the number."""
    _add(con, "dated", "restaurant", LON + 0.001, LAT, "source_date", dt.date(2020, 1, 1))
    _add(con, "undated", "restaurant", LON + 0.0012, LAT, "backfill_censored", None)

    pts = pd.DataFrame({"point_id": ["p"], "lon": [LON], "lat": [LAT]})
    lenient = rd.supply_as_of(con, pts, asof=dt.date(2023, 1, 1),
                              categories=("restaurant",), include_censored=True)
    strict = rd.supply_as_of(con, pts, asof=dt.date(2023, 1, 1),
                             categories=("restaurant",), include_censored=False)
    assert int(lenient["supply"].iloc[0]) == 2
    assert int(strict["supply"].iloc[0]) == 1


def test_supply_respects_the_radius_and_the_principled_set(con):
    _add(con, "near", "restaurant", LON + 0.001, LAT, "source_date", dt.date(2020, 1, 1))
    _add(con, "far", "restaurant", LON + 0.010, LAT, "source_date", dt.date(2020, 1, 1))
    _add(con, "unprincipled", "restaurant", LON + 0.0009, LAT, "source_date",
         dt.date(2020, 1, 1), principled=False)

    pts = pd.DataFrame({"point_id": ["p"], "lon": [LON], "lat": [LAT]})
    got = rd.supply_as_of(con, pts, asof=dt.date(2023, 1, 1),
                          categories=("restaurant",), include_censored=False)
    assert int(got["supply"].iloc[0]) == 1, "radius or principled filter leaked"


def test_a_different_category_is_not_own_category_supply(con):
    _add(con, "cafe", "cafe_bakery", LON + 0.001, LAT, "source_date", dt.date(2020, 1, 1))
    pts = pd.DataFrame({"point_id": ["p"], "lon": [LON], "lat": [LAT]})
    got = rd.supply_as_of(con, pts, asof=dt.date(2023, 1, 1),
                          categories=("restaurant", "cafe_bakery"),
                          include_censored=False)
    assert set(got["category"]) == {"cafe_bakery"}
    assert "restaurant" not in set(got["category"])


# ===========================================================================
# cohort construction
# ===========================================================================
def test_cohort_takes_only_dated_kinds_inside_the_window_and_the_boroughs(con):
    _add(con, "in_window", "restaurant", LON, LAT, "source_date", dt.date(2023, 5, 1))
    _add(con, "gov", "bar", LON, LAT, "gov_filing", dt.date(2024, 12, 31))
    _add(con, "too_early", "restaurant", LON, LAT, "source_date", dt.date(2022, 12, 31))
    _add(con, "too_late", "restaurant", LON, LAT, "source_date", dt.date(2025, 1, 1))
    _add(con, "censored", "restaurant", LON, LAT, "backfill_censored", None)
    _add(con, "queens", "restaurant", LON, LAT, "source_date", dt.date(2023, 5, 1),
         borough="Queens")

    coh = rd.build_cohort(con, dt.date(2023, 1, 1), dt.date(2024, 12, 31))
    assert set(coh["location_key"]) == {"in_window", "gov"}


def test_cohort_carries_exposure_not_an_outcome(con):
    """Exposure is a DURATION, and it differs by opening month. It is not
    evidence of survival — the snapshot censors every row identically."""
    _add(con, "jan23", "restaurant", LON, LAT, "source_date", dt.date(2023, 1, 1))
    _add(con, "dec24", "restaurant", LON, LAT, "source_date", dt.date(2024, 12, 1))
    coh = rd.build_cohort(con).set_index("location_key")

    jan = coh.loc["jan23", "exposure_days"]
    dec = coh.loc["dec24", "exposure_days"]
    assert jan > dec
    assert jan == (rd.SNAPSHOT - dt.date(2023, 1, 1)).days
    assert "event" not in coh.columns, "the cohort must not carry an outcome it cannot observe"


# ===========================================================================
# censoring and the gate
# ===========================================================================
def test_survival_gate_refuses_below_the_power_floor():
    cohort = pd.DataFrame({"exposure_days": np.full(50_000, 600.0)})
    gate = rd.survival_gate(cohort, n_events=0)
    assert gate["identified"] is False
    assert gate["verdict"].startswith("NOT IDENTIFIED")
    assert gate["min_events_required"] == rd.MIN_EVENTS_FOR_HAZARD
    assert "second snapshot" in gate["what_a_second_snapshot_adds"].lower() or \
           "snapshot" in gate["what_a_second_snapshot_adds"].lower()


def test_survival_gate_opens_once_there_are_enough_events():
    cohort = pd.DataFrame({"exposure_days": np.full(1_000, 600.0)})
    gate = rd.survival_gate(cohort, n_events=rd.MIN_EVENTS_FOR_HAZARD)
    assert gate["identified"] is True


def test_a_cohort_with_no_events_yields_a_flat_survival_curve():
    """Not a finding — an artefact. Pinned so nobody quotes S(24) = 1.0 as
    'a 100% two-year survival rate in New York'."""
    km = rd.kaplan_meier(np.full(100, 40.0), np.zeros(100))
    assert km["s_12m"] == 1.0 and km["s_24m"] == 1.0
    assert km["events"] == 0


def test_kaplan_meier_matches_a_hand_computed_example():
    """Five units. Closures at 10 and 20 months, one censored at 15.
    S(12) = 1 - 1/5 = 0.8;  S(24) = 0.8 * (1 - 1/3) = 0.5333..."""
    d = np.array([10.0, 15.0, 20.0, 30.0, 30.0])
    e = np.array([1, 0, 1, 0, 0])
    km = rd.kaplan_meier(d, e)
    assert km["s_12m"] == pytest.approx(0.8)
    assert km["s_24m"] == pytest.approx(0.8 * (2 / 3))


# ===========================================================================
# the AUC helper — a metric that is wrong is worse than no metric
# ===========================================================================
def test_auc_is_one_for_a_perfect_ranking_and_a_half_for_a_constant():
    y = np.array([0, 0, 1, 1])
    assert rd._auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    assert rd._auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == pytest.approx(0.0)
    assert rd._auc(y, np.array([0.5, 0.5, 0.5, 0.5])) == pytest.approx(0.5)


def test_observable_closures_excludes_closures_of_other_industries():
    """A surrendered pedicab licence is a real closure and not an observation
    of whether a café survived. It is reported in the audit and counted at zero
    in the outcome."""
    audit = [
        rd.ClosureInstrument("dcwp_licenses.license_status", True, 114, ""),
        rd.ClosureInstrument("poi_presence.last_seen_month", False, 0, ""),
        rd.ClosureInstrument("foursquare.date_closed", False, 0, ""),
    ]
    assert rd.observable_closures(audit) == 0


# ===========================================================================
# cohort_closure_events -- the shared open/closed/unknown predicate
# (model.poi_presence.poi_is_open, GTM-153) replaces the old ad hoc
# `closed_on IS NOT NULL` check. 'unknown' must never be an event (D79).
# ===========================================================================
@pytest.fixture()
def poi_con():
    """A minimal warehouse for `cohort_closure_events`: `analysis.poi_presence`
    with `closed_on` (sql/027) and `staging.poi` (for the predicate's
    attrs-based branches), joined on `poi_id_latest`."""
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS staging")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    # The open/closed predicate's as-of date is pinned in analysis.supply_asof
    # (owner ruling 2026-09-16): every SQL rendering of
    # model/poi_presence.poi_is_open binds that table by name, so a scratch
    # warehouse needs it exactly as db.init_schema creates it.
    supply_asof.ensure_table(c)
    c.execute("""CREATE TABLE analysis.poi_presence (
        location_key VARCHAR, category VARCHAR, borough VARCHAR,
        first_seen_kind VARCHAR, first_seen_src_date DATE,
        poi_id_latest VARCHAR, closed_on DATE)""")
    c.execute("""CREATE TABLE staging.poi (
        poi_id VARCHAR, source_id VARCHAR, category VARCHAR,
        observed_on DATE, attrs JSON)""")
    return c


def _pp(con, key, cat, kind, date, poi_id=None, closed_on=None, borough="Brooklyn"):
    con.execute(
        "INSERT INTO analysis.poi_presence "
        "(location_key, category, borough, first_seen_kind, first_seen_src_date, "
        "poi_id_latest, closed_on) VALUES (?,?,?,?,?,?,?)",
        [key, cat, borough, kind, date, poi_id, closed_on])


def _spoi(con, poi_id, source_id, cat, attrs=None, observed_on=None):
    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, category, observed_on, attrs) "
        "VALUES (?, ?, ?, ?, CAST(? AS JSON))",
        [poi_id, source_id, cat, observed_on, json.dumps(attrs or {})])


def test_cohort_events_closed_via_ledger_closed_on(poi_con):
    """A Foursquare ledger closure (`closed_on` set) is 'closed' regardless of
    whether `poi_id_latest` still joins to a live `staging.poi` row -- the
    predicate's first branch never needs the join for this case (D79: a
    closed location routinely has its `poi_id_latest` nulled by `snapshot()`
    the month it stops appearing)."""
    _pp(poi_con, "k1", "restaurant", "source_date", dt.date(2023, 3, 1),
        poi_id=None, closed_on=dt.date(2024, 1, 1))
    counts = rd.cohort_closure_events(poi_con, dt.date(2023, 1, 1), dt.date(2024, 12, 31))
    assert counts["n_cohort"] == 1
    assert counts["n_cohort_events"] == 1
    assert counts["n_predicate_closed_total"] == 1


def test_cohort_events_closed_via_dcwp_basis_with_no_closed_on(poi_con):
    """DCWP's 'out_of_business' is a published closure with NO `closed_on` on
    the ledger row at all. The OLD `closed_on IS NOT NULL` check would have
    missed this event entirely; the predicate does not."""
    _spoi(poi_con, "dcwp:1", "nyc_dcwp_inspections", "laundry",
          {"active": False, "active_basis": "out_of_business"})
    _pp(poi_con, "k2", "laundry", "gov_filing", dt.date(2023, 6, 1),
        poi_id="dcwp:1", closed_on=None)
    counts = rd.cohort_closure_events(poi_con, dt.date(2023, 1, 1), dt.date(2024, 12, 31))
    assert counts["n_cohort_events"] == 1


def test_cohort_events_unknown_is_never_an_event(poi_con):
    """No published evidence either way -- 'unknown' -- must NOT be counted:
    D79 says absence of evidence is not evidence of closure."""
    _spoi(poi_con, "ovt:1", "overture_places", "cafe_bakery", {})
    _pp(poi_con, "k3", "cafe_bakery", "source_date", dt.date(2023, 4, 1),
        poi_id="ovt:1", closed_on=None)
    counts = rd.cohort_closure_events(poi_con, dt.date(2023, 1, 1), dt.date(2024, 12, 31))
    assert counts["n_cohort"] == 1
    assert counts["n_cohort_events"] == 0


def test_cohort_events_open_poi_is_never_an_event(poi_con):
    """A positively-open POI (a fresh DOHMH inspection) is not an event."""
    _spoi(poi_con, "doh:1", "nyc_dohmh_restaurants", "restaurant",
          {"active": True, "active_basis": "inspected_10d_ago",
           "last_inspection_date": dt.date(2026, 8, 1).isoformat()})
    _pp(poi_con, "k4", "restaurant", "source_date", dt.date(2023, 2, 1),
        poi_id="doh:1", closed_on=None)
    counts = rd.cohort_closure_events(poi_con, dt.date(2023, 1, 1), dt.date(2024, 12, 31),
                                      boroughs=("Brooklyn",))
    assert counts["n_cohort_events"] == 0


def test_cohort_events_scoped_to_window_and_boroughs(poi_con):
    """A closed POI outside the window, or outside the requested boroughs,
    does not count toward the COHORT event total, even though it still counts
    toward the warehouse-wide predicate total."""
    _pp(poi_con, "out_of_window", "restaurant", "source_date", dt.date(2020, 1, 1),
        closed_on=dt.date(2020, 6, 1))
    _pp(poi_con, "wrong_borough", "restaurant", "source_date", dt.date(2023, 3, 1),
        closed_on=dt.date(2023, 6, 1), borough="Queens")
    _pp(poi_con, "in_scope", "restaurant", "source_date", dt.date(2023, 3, 1),
        closed_on=dt.date(2023, 6, 1))
    counts = rd.cohort_closure_events(poi_con, dt.date(2023, 1, 1), dt.date(2024, 12, 31))
    assert counts["n_cohort_events"] == 1
    assert counts["n_predicate_closed_total"] == 3


# ===========================================================================
# LL157 go-dark: the panel construction, and the two boundaries that decide
# whether the outcome means anything
# ===========================================================================
@pytest.fixture()
def gd_con(con):
    """The premises-year panel plus the lot register the score is built on."""
    con.execute("""CREATE TABLE analysis.storefront (
        storefront_id VARCHAR, premises_id VARCHAR, reporting_year INTEGER,
        vacant_1231 BOOLEAN, construction_reported BOOLEAN, bbl VARCHAR,
        nta_code VARCHAR, borough VARCHAR, primary_business_activity VARCHAR,
        -- sql/041. The retrodiction panel spans 2019-2026 and so spans
        -- DOF's 2024 recode; it reads the canonical column.
        activity_canonical VARCHAR,
        geom GEOMETRY)""")
    con.execute("""CREATE TABLE analysis.address (
        address_id VARCHAR, frame VARCHAR, borough VARCHAR, lon DOUBLE,
        lat DOUBLE, units_capped DOUBLE, nta_code VARCHAR)""")
    con.execute("""CREATE TABLE analysis.address_character (
        address_id VARCHAR, retail_index DOUBLE)""")
    for i in range(40):                      # homes, so homes_t0 > 0 everywhere
        con.execute("INSERT INTO analysis.address VALUES (?,?,?,?,?,?,?)",
                    [f"a{i}", "lot", "BK", LON + 0.0001 * i, LAT, 50.0, "BK99"])
        con.execute("INSERT INTO analysis.address_character VALUES (?, ?)",
                    [f"a{i}", 0.5])
    return con


def _premises(con, pid, year, vacant, activity="RETAIL", constr=False, jitter=0.0):
    con.execute(
        "INSERT INTO analysis.storefront VALUES (?,?,?,?,?,?,?,?,?,?,ST_Point(?,?))",
        [f"{pid}#{year}", pid, year, vacant, constr, "3000010001", "BK99", "BK",
         # raw, then canonical: this fixture predates the recode era, so the
         # two agree. Present because the panel binds to the canonical column.
         activity, activity, LON + jitter, LAT])


def test_a_premises_already_vacant_at_base_year_is_not_at_risk(gd_con):
    """THE BOUNDARY THAT MATTERS. A landlord already dark in 2022 is not a
    failure of a screen frozen in January 2023 — counting them would manufacture
    events out of pre-existing vacancy."""
    _premises(gd_con, "already_dark", 2022, True)
    _premises(gd_con, "already_dark", 2024, True)
    _premises(gd_con, "went_dark", 2022, False)
    _premises(gd_con, "went_dark", 2024, True)
    _premises(gd_con, "stayed", 2022, False)
    _premises(gd_con, "stayed", 2024, False)

    p = rd.go_dark_panel(gd_con, attrition_is_event=False)
    assert set(p["premises_id"]) == {"went_dark", "stayed"}
    assert int(p.set_index("premises_id").loc["went_dark", "event"]) == 1
    assert int(p.set_index("premises_id").loc["stayed", "event"]) == 0


def test_attrition_is_handled_both_ways_and_the_two_disagree(gd_con):
    """"Stopped filing" is either a censored observation or a distressed exit,
    and nothing inside LL157 can say which. Both must be runnable, and the two
    must give different N — a switch that changes nothing is decoration."""
    _premises(gd_con, "quiet", 2022, False)          # no 2024 row at all
    _premises(gd_con, "stayed", 2022, False)
    _premises(gd_con, "stayed", 2024, False)

    strict = rd.go_dark_panel(gd_con, attrition_is_event=False)
    attr = rd.go_dark_panel(gd_con, attrition_is_event=True)

    assert set(strict["premises_id"]) == {"stayed"}
    assert set(attr["premises_id"]) == {"stayed", "quiet"}
    assert int(attr.set_index("premises_id").loc["quiet", "event"]) == 1
    assert len(attr) > len(strict)


def test_any_unit_vacant_makes_the_premises_dark(gd_con):
    """`bool_or` within a premises-year is the documented definition: a building
    counts as going dark when ANY reported unit does. Pinned so the grain
    cannot drift to 'all units' without a test failing."""
    gd_con.execute(
        "INSERT INTO analysis.storefront VALUES "
        "('m#2022a','mixed',2022,FALSE,FALSE,'3000010001','BK99','BK','RETAIL','RETAIL',"
        " ST_Point(?,?))", [LON, LAT])
    gd_con.execute(
        "INSERT INTO analysis.storefront VALUES "
        "('m#2022b','mixed',2022,FALSE,FALSE,'3000010001','BK99','BK','RETAIL','RETAIL',"
        " ST_Point(?,?))", [LON, LAT])
    _premises(gd_con, "mixed", 2024, False)
    gd_con.execute(
        "INSERT INTO analysis.storefront VALUES "
        "('m#2024b','mixed',2024,TRUE,FALSE,'3000010001','BK99','BK','RETAIL','RETAIL',"
        " ST_Point(?,?))", [LON, LAT])

    p = rd.go_dark_panel(gd_con, attrition_is_event=False)
    assert int(p.set_index("premises_id").loc["mixed", "event"]) == 1


def test_the_score_counts_only_what_existed_at_t0(gd_con):
    """The same leakage rule as the entry model, at the premises grain."""
    _premises(gd_con, "p1", 2022, False)
    _premises(gd_con, "p1", 2024, False)
    _add(gd_con, "old", "restaurant", LON + 0.001, LAT, "source_date", dt.date(2021, 1, 1))
    _add(gd_con, "new", "restaurant", LON + 0.0011, LAT, "source_date", dt.date(2024, 1, 1))

    p = rd.go_dark_panel(gd_con, attrition_is_event=False, include_censored=False)
    assert float(p["supply_all_t0"].iloc[0]) == 1.0


def test_activity_groups_are_the_three_ll157_publishes():
    assert rd._activity_group("FOOD SERVICES") == "food"
    assert rd._activity_group("RETAIL") == "retail"
    assert rd._activity_group("HEALTH CARE or SOCIAL ASSISTANCE") == "other"
    assert rd._activity_group(None) == "other"
