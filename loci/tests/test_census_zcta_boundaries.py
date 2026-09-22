"""Offline tests for src/loci/sources/universal/census_zcta_boundaries.py.
No network access: `assign_zcta`/`assign_zcta_df` are exercised against a
tiny synthetic polygon fixture (NOT the real national TIGER file), written
straight into the module's on-disk cache location and cleared from the
in-memory STRtree cache before and after each test.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
import shapely

from loci.sources.universal import census_zcta_boundaries as czb

# A point in Greenpoint (Manhattan Ave & Greenpoint Ave), per the task brief.
GREENPOINT_LON, GREENPOINT_LAT = -73.9543, 40.7302


def _fixture_gdf() -> gpd.GeoDataFrame:
    """Two adjacent, non-overlapping squares standing in for real ZCTA
    polygons: 11222 covers the Greenpoint point; 11211 is a disjoint
    neighbor. A third, far-away polygon (60601) makes sure the tree isn't
    just returning "whatever's first"."""
    zcta_11222 = shapely.box(-73.96, 40.72, -73.94, 40.74)
    zcta_11211 = shapely.box(-73.94, 40.70, -73.92, 40.72)
    zcta_60601 = shapely.box(-87.65, 41.87, -87.60, 41.90)
    return gpd.GeoDataFrame(
        {"zcta": ["11222", "11211", "60601"], "vintage": [2020, 2020, 2020]},
        geometry=[zcta_11222, zcta_11211, zcta_60601], crs="EPSG:4326")


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(czb, "INTERIM_DIR", tmp_path)
    czb._TREE_CACHE.clear()
    _fixture_gdf().to_parquet(tmp_path / "zcta_2020.parquet")
    yield
    czb._TREE_CACHE.clear()


def test_assign_zcta_greenpoint_point_maps_to_11222():
    assert czb.assign_zcta(GREENPOINT_LON, GREENPOINT_LAT, vintage=2020) == "11222"


def test_assign_zcta_returns_none_outside_any_polygon():
    assert czb.assign_zcta(0.0, 0.0, vintage=2020) is None


def test_assign_zcta_unknown_vintage_raises():
    with pytest.raises(ValueError):
        czb.assign_zcta(GREENPOINT_LON, GREENPOINT_LAT, vintage=1999)


def test_assign_zcta_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(czb, "INTERIM_DIR", tmp_path)
    czb._TREE_CACHE.clear()
    with pytest.raises(RuntimeError, match="does not exist"):
        czb.assign_zcta(GREENPOINT_LON, GREENPOINT_LAT, vintage=2010)


def test_assign_zcta_df_vectorized_matches_scalar():
    df = pd.DataFrame({
        "lon": [GREENPOINT_LON, -73.93, -87.62, 0.0],
        "lat": [GREENPOINT_LAT, 40.71, 41.88, 0.0],
    })
    result = czb.assign_zcta_df(df, vintage=2020)
    assert result.tolist() == ["11222", "11211", "60601", None]


def test_assign_zcta_df_preserves_input_index():
    df = pd.DataFrame(
        {"lon": [GREENPOINT_LON, 0.0], "lat": [GREENPOINT_LAT, 0.0]},
        index=[7, 42])
    result = czb.assign_zcta_df(df, vintage=2020)
    assert list(result.index) == [7, 42]
    assert result.loc[7] == "11222"
    assert result.loc[42] is None
