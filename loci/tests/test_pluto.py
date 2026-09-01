import duckdb
import pandas as pd
import pytest

from loci.grid.pluto import _aggregate


def _make_con():
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.hex (h3_index VARCHAR PRIMARY KEY)")
    con.execute("INSERT INTO analysis.hex VALUES ('hexA'), ('hexB')")
    return con


def test_aggregate_area_weighted_means_and_units_sum():
    con = _make_con()
    lots = pd.DataFrame([
        # two lots in hexA with known lotarea/commfar/residfar/builtfar/unitsres
        {"h3_index": "hexA", "lotarea": 1000.0, "commfar": 2.0, "residfar": 3.0, "builtfar": 1.0, "unitsres": 10.0},
        {"h3_index": "hexA", "lotarea": 3000.0, "commfar": 0.0, "residfar": 1.0, "builtfar": 1.0, "unitsres": 5.0},
    ])
    con.register("_pluto_lots", lots)
    agg = _aggregate(con)
    con.unregister("_pluto_lots")

    assert len(agg) == 1
    row = agg.set_index("h3_index").loc["hexA"]

    total_area = 1000.0 + 3000.0
    assert row["comm_far_capacity"] == pytest.approx((2.0 * 1000.0 + 0.0 * 3000.0) / total_area)
    assert row["resid_far"] == pytest.approx((3.0 * 1000.0 + 1.0 * 3000.0) / total_area)
    assert row["built_far"] == pytest.approx((1.0 * 1000.0 + 1.0 * 3000.0) / total_area)
    # dev_headroom = GREATEST(residfar - builtfar, 0) area-weighted:
    #   lot 1: max(3-1, 0) = 2 ; lot 2: max(1-1, 0) = 0
    assert row["dev_headroom"] == pytest.approx((2.0 * 1000.0 + 0.0 * 3000.0) / total_area)
    # units_res is a count -> SUM, not a mean
    assert row["units_res"] == pytest.approx(15.0)


def test_aggregate_excludes_lots_outside_analysis_hex():
    con = _make_con()
    lots = pd.DataFrame([
        {"h3_index": "hexA", "lotarea": 500.0, "commfar": 5.0, "residfar": 5.0, "builtfar": 0.0, "unitsres": 1.0},
        {"h3_index": "not_in_grid", "lotarea": 999.0, "commfar": 9.0, "residfar": 9.0, "builtfar": 9.0, "unitsres": 99.0},
    ])
    con.register("_pluto_lots", lots)
    agg = _aggregate(con)
    con.unregister("_pluto_lots")

    assert set(agg["h3_index"]) == {"hexA"}


def test_aggregate_handles_zero_far_lots():
    """A lot with zero FAR everywhere (e.g. a park edge) should pull the
    area-weighted mean toward zero, not be dropped or treated as missing."""
    con = _make_con()
    lots = pd.DataFrame([
        {"h3_index": "hexB", "lotarea": 1000.0, "commfar": 0.0, "residfar": 0.0, "builtfar": 0.0, "unitsres": 0.0},
        {"h3_index": "hexB", "lotarea": 1000.0, "commfar": 4.0, "residfar": 4.0, "builtfar": 2.0, "unitsres": 20.0},
    ])
    con.register("_pluto_lots", lots)
    agg = _aggregate(con)
    con.unregister("_pluto_lots")

    row = agg.set_index("h3_index").loc["hexB"]
    assert row["comm_far_capacity"] == pytest.approx(2.0)
    assert row["units_res"] == pytest.approx(20.0)
