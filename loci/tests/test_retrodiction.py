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

import numpy as np
import pandas as pd
import pytest

from loci import db as locidb
from loci.validation import retrodiction as rd


# ---------------------------------------------------------------------------
# a minimal warehouse: the two tables supply_as_of / build_cohort read
# ---------------------------------------------------------------------------
@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
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
