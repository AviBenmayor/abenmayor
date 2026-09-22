"""Offline tests for src/loci/sources/universal/census_decennial_zcta.py's
interpolation math and the outer-join "flag absent, don't drop" panel
assembly. No network access -- all inputs are small synthetic DataFrames
built to look like `build_long`'s own output shape."""
from __future__ import annotations

import pandas as pd

from loci.sources.universal import census_decennial_zcta as cdz


def _long_row(zcta, year, pop, present=True):
    return {"zcta": zcta, "decennial_year": year, "population": pop, "present": present}


def test_interpolate_population_three_anchors_kinks_at_2010():
    long_df = pd.DataFrame([
        _long_row("11222", 2000, 100.0),
        _long_row("11222", 2010, 200.0),
        _long_row("11222", 2020, 240.0),
    ])
    out = cdz.interpolate_population(long_df)
    row = out.set_index("year")
    # 2000-2010 segment: +10/year
    assert row.loc[2005, "pop"] == 150.0
    assert row.loc[2005, "method"] == "linear_interp"
    # 2010-2020 segment: +4/year (different slope -> real kink at 2010)
    assert row.loc[2015, "pop"] == 220.0
    assert row.loc[2010, "pop"] == 200.0
    assert bool(row.loc[2010, "is_anchor"]) is True
    assert bool(row.loc[2005, "is_anchor"]) is False
    assert len(out) == 21  # 2000..2020 inclusive


def test_interpolate_population_missing_2010_spans_full_gap():
    long_df = pd.DataFrame([
        _long_row("11111", 2000, 100.0),
        _long_row("11111", 2010, None, present=False),
        _long_row("11111", 2020, 300.0),
    ])
    out = cdz.interpolate_population(long_df)
    row = out.set_index("year")
    assert len(out) == 21
    assert row.loc[2010, "pop"] == 200.0
    assert row.loc[2010, "method"] == "linear_interp"
    assert bool(row.loc[2010, "is_anchor"]) is False


def test_interpolate_population_single_anchor_no_extrapolation():
    long_df = pd.DataFrame([
        _long_row("99999", 2000, 500.0),
        _long_row("99999", 2010, None, present=False),
        _long_row("99999", 2020, None, present=False),
    ])
    out = cdz.interpolate_population(long_df)
    assert len(out) == 1
    assert out.iloc[0]["year"] == 2000
    assert out.iloc[0]["method"] == "anchor"
    assert bool(out.iloc[0]["is_anchor"]) is True


def test_interpolate_population_output_schema_is_fixed():
    long_df = pd.DataFrame([_long_row("11222", 2000, 100.0), _long_row("11222", 2010, 200.0)])
    out = cdz.interpolate_population(long_df)
    assert list(out.columns) == ["zcta", "year", "pop", "method", "is_anchor"]


def test_build_long_flags_absence_instead_of_dropping():
    frames = {
        2000: pd.DataFrame([{"zcta": "11222", "decennial_year": 2000, "population": 100.0}]),
        2010: pd.DataFrame([{"zcta": "11222", "decennial_year": 2010, "population": 200.0}]),
        # 11222 absent from 2020's pull entirely; a second zcta only exists in 2020.
        2020: pd.DataFrame([{"zcta": "99999", "decennial_year": 2020, "population": 50.0}]),
    }
    out = cdz.build_long(frames)
    row = out.set_index(["zcta", "decennial_year"])
    assert bool(row.loc[("11222", 2020), "present"]) is False
    assert pd.isna(row.loc[("11222", 2020), "population"])
    assert bool(row.loc[("11222", 2000), "present"]) is True
    assert bool(row.loc[("99999", 2000), "present"]) is False
    # Every (zcta, year) combination is present as a ROW even when the
    # underlying vintage never returned that code.
    assert set(out["zcta"]) == {"11222", "99999"}
    assert len(out) == 2 * 3
