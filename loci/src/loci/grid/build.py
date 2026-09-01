"""Build the H3 res-9 grid, shoreline-clipped, with per-cell land_fraction.

CONTEXT.md §2.3, §4.1. ~7,400 cells over NYC's ~778 km2 of land. Water-only
cells are dropped; partial edge cells are kept with a land_fraction so densities
can be normalized (threat §7.7).

Areas are computed in EPSG:2263 (NY State Plane, feet) — an equal-area-enough
projected CRS — never in degrees. DuckDB GEOMETRY carries no SRID, so the hex
polygons are stored in EPSG:4326 by convention (CONTEXT.md §4.1 caveat).
"""
from __future__ import annotations

import pathlib

import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import Polygon
from shapely.ops import unary_union

from loci import db as locidb

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
BOUNDARY = REPO_ROOT / "data" / "raw" / "boundaries" / "nyc_nta2020.geojson"
PROJ = 2263  # NY State Plane Long Island (feet)


def _cell_polygon(cell: str) -> Polygon:
    """H3 cell boundary as a lon/lat shapely Polygon (h3 returns lat/lng)."""
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)])


def _candidate_cells(land, res: int) -> set[str]:
    """Cells whose center is on land, plus a boundary ring to catch edge cells."""
    cells: set[str] = set()
    # slightly buffer so partial coastal/边 cells are included, then filter by land_fraction
    geoms = [land, land.buffer(0.004)]  # ~440 m at NYC latitude
    for g in geoms:
        parts = g.geoms if g.geom_type == "MultiPolygon" else [g]
        for poly in parts:
            outer = [(lat, lng) for lng, lat in poly.exterior.coords]
            holes = [[(lat, lng) for lng, lat in r.coords] for r in poly.interiors]
            cells |= set(h3.polygon_to_cells(h3.LatLngPoly(outer, *holes), res))
    return cells


def build_grid(con, res: int = 9, min_land_fraction: float = 0.001) -> int:
    ntas = gpd.read_file(BOUNDARY).to_crs(4326)
    ntas["geometry"] = ntas.geometry.buffer(0)  # fix ring orientation / validity
    land = unary_union(ntas.geometry.values)

    cells = _candidate_cells(land, res)
    cell_gdf = gpd.GeoDataFrame(
        {"h3_index": list(cells)},
        geometry=[_cell_polygon(c) for c in cells],
        crs=4326,
    )

    # land_fraction in a projected CRS
    proj = cell_gdf.to_crs(PROJ)
    land_proj = gpd.GeoSeries([land], crs=4326).to_crs(PROJ).iloc[0]
    cell_area = proj.geometry.area
    inter_area = proj.geometry.intersection(land_proj).area
    cell_gdf["land_fraction"] = (inter_area / cell_area).clip(upper=1.0).values
    cell_gdf = cell_gdf[cell_gdf["land_fraction"] > min_land_fraction].copy()

    latlng = [h3.cell_to_latlng(c) for c in cell_gdf["h3_index"]]
    cell_gdf["lat"] = [p[0] for p in latlng]
    cell_gdf["lon"] = [p[1] for p in latlng]

    # Label each cell by the NTA it overlaps MOST (not by centroid) so coastal
    # cells whose centroid falls in water still get a borough/NTA.
    cells_proj = cell_gdf[["h3_index", "geometry"]].to_crs(PROJ)
    ntas_proj = ntas[["boroname", "nta2020", "geometry"]].to_crs(PROJ)
    ov = gpd.overlay(cells_proj, ntas_proj, how="intersection")
    ov["a"] = ov.geometry.area
    ov = ov.sort_values("a").drop_duplicates("h3_index", keep="last").set_index("h3_index")
    cell_gdf["borough"] = cell_gdf["h3_index"].map(ov["boroname"])
    cell_gdf["nta_code"] = cell_gdf["h3_index"].map(ov["nta2020"])

    df = pd.DataFrame({
        "h3_index": cell_gdf["h3_index"],
        "wkt": cell_gdf.geometry.to_wkt(),
        "lon": cell_gdf["lon"], "lat": cell_gdf["lat"],
        "land_fraction": cell_gdf["land_fraction"],
        "borough": cell_gdf["borough"],
        "nta_code": cell_gdf["nta_code"],
    })

    con.execute("DELETE FROM analysis.hex")
    con.register("_hex_df", df)
    con.execute(f"""
        INSERT INTO analysis.hex (h3_index, resolution, geom, centroid, land_fraction, borough, nta_code)
        SELECT h3_index, {res}, ST_GeomFromText(wkt), ST_Point(lon, lat),
               land_fraction, borough, nta_code
        FROM _hex_df
    """)
    con.unregister("_hex_df")
    return con.execute("SELECT count(*) FROM analysis.hex").fetchone()[0]


def main() -> None:
    con = locidb.connect()
    locidb.init_schema(con)
    n = build_grid(con)
    print(f"built {n} hexes")
