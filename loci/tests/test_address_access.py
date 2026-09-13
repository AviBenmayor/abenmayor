"""transit_entries_400m + jobs_400m (GTM-146).

The distance maths is already covered by tests/test_supply_ratio.py (the same
`catchment_sums` on the same synthetic line graph), so what is tested here is
what is NEW: the ridership window, the entrance split, the column contract, and
the refusal to write a partial or filtering update.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from loci.model.address_access import ACCESS_COLUMNS, _guard, write_access
from loci.sources.cities.nyc.mta_ridership import (
    HOLIDAYS,
    entry_points,
    latest_full_months,
    month_bounds,
    weekday_dates,
)
from loci.validation.pedestrian_counts import (
    MAX_ON_STREET_LOC,
    latest_round,
    on_street_counts,
    parse_round,
    spearman,
)

# ------------------------------------------------------------- the window

def test_latest_full_months_excludes_the_month_the_feed_stops_inside():
    # Feed stops 2026-09-02: September is INCOMPLETE, so the window is Jun-Aug.
    # Averaging two days of September in would be a silent partial month.
    assert latest_full_months(dt.date(2026, 9, 2), 3) == [(2026, 6), (2026, 7), (2026, 8)]


def test_latest_full_months_includes_a_month_that_ended_exactly_on_asof():
    assert latest_full_months(dt.date(2026, 8, 31), 3) == [(2026, 6), (2026, 7), (2026, 8)]


def test_latest_full_months_crosses_the_year_boundary():
    assert latest_full_months(dt.date(2026, 2, 28), 3) == [(2025, 12), (2026, 1), (2026, 2)]


def test_weekday_dates_drops_weekends_and_federal_holidays():
    first, last = month_bounds(2026, 7)
    days = weekday_dates(first, last)
    assert all(d.weekday() < 5 for d in days)
    assert dt.date(2026, 7, 3) in HOLIDAYS          # July 4th observed
    assert dt.date(2026, 7, 3) not in days
    assert len(days) == 22                          # 23 weekdays less the holiday


# ------------------------------------------------------- the entrance split

def _entries():
    return {"A": {"entries_per_weekday": 1000.0, "name": "A", "lon": -73.9, "lat": 40.7},
            "B": {"entries_per_weekday": 500.0, "name": "B", "lon": -73.8, "lat": 40.6}}


def _entrances():
    return [
        {"complex_id": "A", "entry_allowed": "YES", "entrance_longitude": "-73.901",
         "entrance_latitude": "40.701"},
        {"complex_id": "A", "entry_allowed": "YES", "entrance_longitude": "-73.899",
         "entrance_latitude": "40.699"},
        # exit-only: not a way INTO the system, so it must carry no entries
        {"complex_id": "A", "entry_allowed": "NO", "entrance_longitude": "-73.905",
         "entrance_latitude": "40.705"},
        {"complex_id": "B", "entry_allowed": "YES", "entrance_longitude": "-73.801",
         "entrance_latitude": "40.601"},
    ]


def test_entry_points_splits_evenly_and_conserves_the_total():
    pts, rep = entry_points(_entries(), _entrances())
    assert rep["snap"] == "entrances"
    assert rep["weight_points"] == 3            # two for A, one for B; exit-only dropped
    assert rep["total_weight"] == pytest.approx(1500.0)
    a = [p[3] for p in pts if p[0] == "A"]
    assert a == pytest.approx([500.0, 500.0])   # 1000 over two entry-allowed doors
    assert [p[3] for p in pts if p[0] == "B"] == pytest.approx([500.0])


def test_entry_points_falls_back_to_the_complex_point_rather_than_dropping():
    """A complex with no entrance row must never vanish: a dropped complex reads
    downstream as 'no subway here', a confident false negative."""
    ent = [e for e in _entrances() if e["complex_id"] == "A"]
    pts, rep = entry_points(_entries(), ent, min_match_share=0.0)
    assert rep["complexes_without_entrances"] == 1
    assert rep["total_weight"] == pytest.approx(1500.0)
    b = [p for p in pts if p[0] == "B"]
    assert len(b) == 1 and b[0][1:3] == (-73.8, 40.6)


def test_entry_points_raises_when_the_two_feeds_id_spaces_diverge():
    bad = [{"complex_id": "ZZZ", "entry_allowed": "YES",
            "entrance_longitude": "-73.9", "entrance_latitude": "40.7"}]
    with pytest.raises(RuntimeError, match="diverged"):
        entry_points(_entries(), bad)


def test_entry_points_without_entrances_puts_the_whole_complex_on_its_point():
    pts, rep = entry_points(_entries(), None)
    assert rep["snap"] == "complex"
    assert len(pts) == 2
    assert rep["total_weight"] == pytest.approx(1500.0)


def test_entry_points_ignores_null_island_entrances():
    ent = _entrances() + [{"complex_id": "B", "entry_allowed": "YES",
                           "entrance_longitude": "0", "entrance_latitude": "0"}]
    pts, rep = entry_points(_entries(), ent)
    assert rep["total_weight"] == pytest.approx(1500.0)
    assert all(not (p[1] == 0.0 and p[2] == 0.0) for p in pts)


# ------------------------------------------------------- the column contract

def test_access_columns_are_disjoint_from_every_sibling_annotation():
    """These two are a reading BESIDE the screen, never a filter on it. A SET
    list that touched gap_score, eligible, nearest_m, supply_ratio_vs_base or
    any pipeline/storefront/age-fit column would be an annotation that had
    become a filter wearing a costume."""
    from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
    from loci.model.address_gaps import (
        ADDRESS_CATEGORY_SCREEN_COLUMNS,
        ADDRESS_COLUMNS,
    )
    from loci.model.dev_pipeline import PIPELINE_COLUMNS
    from loci.model.storefronts import AGE_FIT_COLUMNS, STOREFRONT_COLUMNS
    from loci.model.supply_ratio import ADDRESS_RATIO_COLUMNS, CATEGORY_RATIO_COLUMNS

    others = (set(ADDRESS_COLUMNS) | set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
              | set(PIPELINE_COLUMNS) | set(STOREFRONT_COLUMNS) | set(AGE_FIT_COLUMNS)
              | set(DEMAND_ANNOTATION_COLUMNS) | set(ADDRESS_RATIO_COLUMNS)
              | set(CATEGORY_RATIO_COLUMNS))
    assert set(ACCESS_COLUMNS) & others == set()
    _guard(ACCESS_COLUMNS)                          # the runtime guard agrees


def test_guard_raises_on_a_column_another_module_owns():
    with pytest.raises(RuntimeError, match="clobber"):
        _guard([*ACCESS_COLUMNS, "gap_score"])


def test_access_columns_carry_their_own_provenance():
    """A reader must be able to tell which window and which LODES vintage
    produced the number without going back to the run log."""
    for c in ("access_radius_m", "transit_entries_window", "transit_entries_snap",
              "jobs_vintage", "access_run_at"):
        assert c in ACCESS_COLUMNS


def test_write_access_refuses_a_partial_frame():
    """Every column in ACCESS_COLUMNS is RESET to NULL before the update, so a
    frame missing one would blank it permanently rather than leave it alone."""
    df = pd.DataFrame({"address_id": ["a"], "borough": ["BK"],
                       "transit_entries_400m": [1.0]})
    with pytest.raises(RuntimeError, match="missing"):
        write_access(object(), df, ["BK"])


def test_sql_migration_declares_exactly_the_access_columns():
    import pathlib

    sql = (pathlib.Path(__file__).resolve().parents[1] / "src" / "loci" / "sql"
           / "016_address_access.sql").read_text()
    alters = [ln.strip() for ln in sql.splitlines()
              if ln.strip().upper().startswith("ALTER TABLE")]
    declared = {ln.split("ADD COLUMN IF NOT EXISTS")[1].split()[0] for ln in alters}
    assert declared == set(ACCESS_COLUMNS)
    # Category-INDEPENDENT (D61 inventory rule): fifteen identical copies of one
    # number on address_category would be 11.5M rows to say 767k things.
    assert all("analysis.address " in ln for ln in alters)


# ------------------------------------------------- the DOT validation harness

def test_parse_round_handles_every_naming_shape_the_feed_uses():
    assert parse_round("may_07_am") == (2007, 5, "am")
    assert parse_round("sept_13_pm") == (2013, 9, "pm")
    assert parse_round("may_22_p_m") == (2022, 5, "pm")   # the sic spelling
    assert parse_round("oct24_am") == (2024, 10, "am")
    assert parse_round("june_24_md") == (2024, 6, "md")
    assert parse_round("may26_pm") == (2026, 5, "pm")
    assert parse_round("borough") is None
    assert parse_round("objectid") is None


def test_latest_round_ignores_a_round_missing_a_period():
    rows = [{"may25_am": "1", "may25_md": "1", "may25_pm": "1", "may26_am": "1"}]
    assert latest_round(rows) == (2025, 5)


def test_on_street_counts_excludes_bridge_points_and_sums_the_three_periods():
    rows = [
        {"loc": "1", "borough": "Bronx", "street_nam": "Broadway",
         "the_geom": {"type": "Point", "coordinates": [-73.9, 40.87]},
         "may26_am": "100", "may26_md": "200", "may26_pm": "300"},
        {"loc": "101", "borough": "East River Bridges", "street_nam": "Brooklyn Bridge",
         "the_geom": {"type": "Point", "coordinates": [-73.99, 40.70]},
         "may26_am": "1", "may26_md": "2", "may26_pm": "3"},
        {"loc": "26", "borough": "Manhattan", "street_nam": "x",
         "the_geom": {"type": "Point", "coordinates": [-73.98, 40.75]},
         "may26_md": "5", "may26_pm": "6"},                     # missing AM
    ]
    pts, rep = on_street_counts(rows, 2026, 5)
    assert [p["loc"] for p in pts] == [1]
    assert pts[0]["count"] == 600.0
    assert rep["dropped_bridge_points"] == 1
    assert rep["dropped_missing_count"] == 1
    assert MAX_ON_STREET_LOC == 100


def test_spearman_is_rank_based_and_ignores_non_finite_pairs():
    rho, n = spearman([1, 2, 3, 4], [10, 100, 1000, 10000])
    assert rho == pytest.approx(1.0) and n == 4
    rho, n = spearman([1, 2, 3, float("nan")], [3, 2, 1, 0])
    assert rho == pytest.approx(-1.0) and n == 3
