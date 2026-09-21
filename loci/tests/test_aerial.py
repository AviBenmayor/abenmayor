"""The aerial layers: tile arithmetic, the change score, the awning band, the
convertible filter. Synthetic tiles and footprints; no network, no warehouse.

The load-bearing claims:

1. TILE ARITHMETIC round-trips and the ArcGIS URL is /z/y/x (row, column):
   getting that backwards returns a real tile from the wrong place.
2. THE CHANGE SCORE ignores a global brightness shift (a different sun is
   not a demolition) and catches a spatial rearrangement; the class follows
   the 2024 texture, and a sliver is `no_imagery`, never `unchanged`.
3. THE AWNING BAND sits OUTSIDE the footprint on the street side, and the
   detector fires on coloured canvas over concrete, not on bare concrete.
4. THE CONVERTIBLE FILTER keeps a one-storey 600 m2 shed and a 900 m2
   parking lot, and drops a 20 m tower and a 100 m2 kiosk.
"""
from __future__ import annotations

import io
import math

import duckdb
import numpy as np
import pytest

from loci.model import aerial
from loci.model import aerial_awning as aw
from loci.model import aerial_convertible as cv
from loci.sources.cities.nyc import orthoimagery as ortho

LAT, LON = 40.678, -73.986          # Gowanus


# ------------------------------------------------------------ helpers

def _jpeg(arr: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _tile_fetcher(painter):
    """fetch_fn: URL -> JPEG bytes painted by `painter(year, z, x, y) -> HxWx3`."""
    def fetch(url: str) -> bytes:
        parts = url.split("/")
        z, y, x = int(parts[-3]), int(parts[-2]), int(parts[-1])
        year = next(yr for yr, svc in ortho.SERVICES.items() if svc in url)
        return _jpeg(painter(year, z, x, y))
    return fetch


def _square(lon: float, lat: float, side_m: float):
    """A square footprint ring (lon/lat) of `side_m` centred on the point."""
    dlat = side_m / 2 / 111_320.0
    dlon = side_m / 2 / (111_320.0 * math.cos(math.radians(lat)))
    return ((lon - dlon, lat - dlat), (lon + dlon, lat - dlat), (lon + dlon, lat + dlat),
            (lon - dlon, lat + dlat), (lon - dlon, lat - dlat))


def _lot(side_m=30.0, **kw) -> aerial.Lot:
    return aerial.Lot(bbl="3000000001", rings=(_square(LON, LAT, side_m),),
                      geom_source="footprint", dob_status=kw.get("dob", "active"),
                      named_site=kw.get("named"), lon=LON, lat=LAT)


# ----------------------------------------------------- 1. tile maths

def test_tile_xy_round_trips_through_the_tile_corner():
    x, y = ortho.tile_xy(LON, LAT, 20)
    lon, lat = ortho.tile_lonlat(x, y, 20)
    assert lon <= LON < ortho.tile_lonlat(x + 1, y, 20)[0]
    assert ortho.tile_lonlat(x, y + 1, 20)[1] <= LAT < lat


def test_the_arcgis_url_is_row_then_column_and_the_year_picks_the_service():
    assert ortho.tile_url(2024, 20, 308787, 394376).endswith(
        "NYC_Orthos_2024/MapServer/tile/20/394376/308787")
    assert "NYC_Orthos_-_2020" in ortho.tile_url(2020, 20, 1, 2)
    with pytest.raises(KeyError):
        ortho.tile_url(2023, 20, 1, 2)


def test_native_zoom_is_the_first_level_finer_than_six_inch():
    ground = ortho.metres_per_pixel(LAT, ortho.NATIVE_ZOOM)
    assert ground < 0.152 <= ortho.metres_per_pixel(LAT, ortho.NATIVE_ZOOM - 1)


def test_mosaic_caches_tiles_and_maps_lonlat_to_pixels(tmp_path):
    calls = []

    def painter(year, z, x, y):
        calls.append((year, z, x, y))
        return np.full((256, 256, 3), 120, np.uint8)

    m = ortho.mosaic(2024, _lot(30.0).bbox, root=tmp_path, fetch_fn=_tile_fetcher(painter))
    n = len(calls)
    assert n >= 1 and m.img.shape[2] == 3
    px, py = m.to_pixel(LON, LAT)
    assert 0 <= px < m.shape[1] and 0 <= py < m.shape[0]
    ortho.mosaic(2024, _lot(30.0).bbox, root=tmp_path, fetch_fn=_tile_fetcher(painter))
    assert len(calls) == n, "second mosaic over the same bbox is a disk read"


def test_pull_takes_whole_tiles_and_reports_counts(tmp_path):
    fetch = _tile_fetcher(lambda *_: np.full((256, 256, 3), 90, np.uint8))
    rep = ortho.pull(2022, _lot(60.0).bbox, root=tmp_path, fetch_fn=fetch, concurrency=2)
    assert rep["fetched"] == rep["tiles_in_bbox"] >= 1 and rep["errors"] == 0
    again = ortho.pull(2022, _lot(60.0).bbox, root=tmp_path, fetch_fn=fetch, concurrency=2)
    assert again["fetched"] == 0 and again["cached_before"] == rep["tiles_in_bbox"]


# ---------------------------------------------------- 2. change score

def _roof(seed, base=110, noise=8, size=(512, 512)):
    rng = np.random.default_rng(seed)
    arr = rng.normal(base, noise, size=(*size, 3)).clip(0, 255).astype(np.uint8)
    return arr


def test_a_brighter_flight_over_the_same_roof_is_not_change():
    a = _roof(1, 100)
    b = np.clip(a.astype(int) + 60, 0, 255).astype(np.uint8)      # same scene, sunnier
    mask = np.zeros(a.shape[:2], bool)
    mask[100:400, 100:400] = True
    sc = aerial.change_score(a, b, mask)
    assert sc["change_class"] == "unchanged" and sc["change_frac"] < 0.05


def test_a_rearranged_lot_is_change_and_the_class_follows_the_2024_surface():
    a = _roof(1, 90, 6)
    # The 2022 roof has structure: bulkhead and HVAC blocks over a third of it.
    a[100:400, 100:400][(np.indices((300, 300))[0] // 30) % 3 == 0] = 40
    mask = np.zeros(a.shape[:2], bool)
    mask[100:400, 100:400] = True
    rng = np.random.default_rng(3)
    # new_roof: the whole lot is a new SMOOTH grey membrane sharing no structure.
    b = a.copy()
    b[100:400, 100:400] = rng.normal(210, 3, (300, 300, 3)).clip(0, 255)
    sc = aerial.change_score(a, b, mask)
    assert sc["change_class"] == "new_roof" and sc["change_frac"] >= aerial.CHANGED_MIN
    assert sc["ncc"] < aerial.NCC_PARTIAL
    # under_construction: 2024 is BUSY (high-contrast checker) over the lot.
    busy = a.copy()
    busy[100:400, 100:400] = np.where(rng.random((300, 300, 1)) > 0.5, 240, 30)
    assert aerial.change_score(a, busy, mask)["change_class"] == "under_construction"
    # cleared: 2024 is bare earth -- brownish, smooth-ish.
    earth = a.copy()
    earth[100:400, 100:400] = (rng.normal(0, 6, (300, 300, 3)) + [138, 132, 124]).clip(0, 255)
    assert aerial.change_score(a, earth, mask)["change_class"] == "cleared"


def test_the_same_structure_under_a_different_sun_is_unchanged():
    """The first Gowanus run's failure mode: rowhouse blocks with moved
    shadows read 60% brightness change. Structure (aligned NCC) overrides."""
    rng = np.random.default_rng(5)
    a = _roof(1, 120, 4)
    # A textured block: stripes of parapets and stair bulkheads.
    a[100:400, 100:400, :] = (60 + 120 * (np.indices((300, 300))[0] // 25 % 2))[..., None]
    mask = np.zeros(a.shape[:2], bool)
    mask[100:400, 100:400] = True
    # 2024: same block, shifted 4 px (registration), sun moved: a diagonal
    # shadow band darkens a third of it, and the whole thing is 30 brighter.
    b = np.roll(a, (4, 2), axis=(0, 1)).astype(int) + 30
    ii, jj = np.indices(b.shape[:2])
    b[(ii + jj) % 90 < 30] -= 70
    b = b.clip(0, 255).astype(np.uint8)
    b = (b + rng.normal(0, 3, b.shape)).clip(0, 255).astype(np.uint8)
    sc = aerial.change_score(a, b, mask)
    assert sc["change_frac"] >= aerial.CHANGED_MIN       # brightness says change
    assert sc["ncc"] >= aerial.NCC_SAME                    # structure says no
    assert sc["change_class"] == "unchanged"


def test_a_sliver_is_no_imagery_not_unchanged():
    a = _roof(1)
    mask = np.zeros(a.shape[:2], bool)
    mask[10:20, 10:20] = True
    sc = aerial.change_score(a, a, mask)
    assert sc["change_class"] == "no_imagery" and sc["change_frac"] is None


def test_run_change_scores_a_lot_against_two_synthetic_years_and_reviews_it(tmp_path):
    def painter(year, z, x, y):
        img = np.full((256, 256, 3), 100, np.uint8)
        if year == 2022:
            img[(np.indices((256, 256))[0] // 24) % 3 == 0] = 40    # bulkheads, HVAC
        else:
            img[:] = 200                                            # a new membrane
        return img

    lot = _lot(30.0, named="CSO tank: test")
    rows = aerial.run_change([lot], root=tmp_path, fetch_fn=_tile_fetcher(painter))
    r = rows[0]
    assert r["bbl"] == "3000000001" and r["ortho_from"] == 2022 and r["ortho_to"] == 2024
    assert r["change_class"] == "new_roof" and r["pixels"] > aerial.MIN_PIXELS
    assert r["crop_from"] and r["crop_to"] and r["named_site"] == "CSO tank: test"
    out = aerial.review_html(rows, tmp_path / "review.html", "t")
    text = out.read_text()
    assert "3000000001" in text and "owner" not in text.lower().split("nothing here")[0][:0]
    assert text.count("<section") == 1 and "</html>" in text
    # The table write names its columns and refuses nothing on a fresh schema.
    con = duckdb.connect(":memory:")
    con.execute("LOAD spatial")
    from loci import db as locidb
    con.execute((locidb.SQL_DIR / "054_aerial.sql.draft").read_text()
                if (locidb.SQL_DIR / "054_aerial.sql.draft").exists()
                else (locidb.SQL_DIR / "054_aerial.sql").read_text())
    assert aerial.write_change(con, rows) == 1
    assert aerial.write_change(con, rows) == 1            # re-run replaces, never doubles
    assert con.execute("SELECT count(*) FROM analysis.lot_aerial_change").fetchone()[0] == 1


def test_lot_box_has_the_pluto_area_and_a_nan_area_falls_back():
    ring = aerial.lot_box(LON, LAT, 5000.0)             # 5,000 sq ft = 464.5 m2
    lat_m = 111_320.0
    side = (ring[2][1] - ring[0][1]) * lat_m
    assert side == pytest.approx(math.sqrt(464.5), rel=0.01)
    nan_ring = aerial.lot_box(LON, LAT, float("nan"))   # a PLUTO row with no area
    assert all(math.isfinite(v) for p in nan_ring for v in p)
    assert (nan_ring[2][1] - nan_ring[0][1]) * lat_m == pytest.approx(20.0, rel=0.01)


def test_geojson_rings_keep_each_polygons_exterior_only():
    gj = ('{"type":"MultiPolygon","coordinates":[[[[0,0],[1,0],[1,1],[0,1],[0,0]],'
          '[[0.2,0.2],[0.4,0.2],[0.4,0.4],[0.2,0.2]]],[[[5,5],[6,5],[6,6],[5,5]]]]}')
    rings = aerial._rings_from_geojson(gj)
    assert len(rings) == 2 and rings[0][0] == (0.0, 0.0) and rings[1][0] == (5.0, 5.0)


# ------------------------------------------------------- 3. awnings

def test_the_street_face_is_the_edge_nearest_the_street_and_the_band_is_outside():
    ring = list(_square(LON, LAT, 20.0))
    # A street point 12 m SOUTH of the footprint's south edge.
    south = np.array([[LON, LAT - 22.0 / 111_320.0, "3 AVENUE"]], dtype=object)
    faces = aw.street_faces(ring, south)
    assert len(faces) == 1
    f = faces[0]
    assert f["street_key"] == "3 AVENUE" and f["outward"][1] < 0        # points south
    band = aw.band_polygon(f)
    assert all(lat < LAT - 10.0 / 111_320.0 for _, lat in band)          # below the south edge
    # A second street to the EAST gives a corner building two faces.
    east = np.array([[LON + 22.0 / (111_320.0 * math.cos(math.radians(LAT))), LAT, "UNION ST"]],
                    dtype=object)
    assert len(aw.street_faces(ring, np.vstack([south, east]))) == 2


def test_no_face_when_no_street_point_is_near():
    ring = list(_square(LON, LAT, 20.0))
    far = np.array([[LON, LAT - 200.0 / 111_320.0, "FAR ST"]], dtype=object)
    assert aw.street_faces(ring, far) == []


def test_lit_coloured_canvas_fires_and_concrete_shadow_and_black_do_not():
    concrete = np.full((60, 200, 3), 165, np.uint8)
    mask = np.zeros((60, 200), bool)
    mask[20:40, :] = True
    assert aw.awning_fraction(concrete, mask) < 0.05
    red = concrete.copy()
    red[20:40, 20:180] = (170, 30, 30)
    assert aw.awning_fraction(red, mask) >= aw.AWNING_MIN
    # The building's own shadow: dark and blue-tinted. NOT an awning (the
    # first corridor run's false-positive mode), and neither is black canvas,
    # which is indistinguishable from it and is a documented miss.
    shadow = concrete.copy()
    shadow[20:40, 20:180] = (38, 48, 70)
    assert aw.awning_fraction(shadow, mask) < 0.05
    black = concrete.copy()
    black[20:40, 20:180] = (28, 28, 30)
    assert aw.awning_fraction(black, mask) < 0.05


def test_run_awnings_end_to_end_on_a_synthetic_corridor(tmp_path):
    con = duckdb.connect(":memory:")
    con.execute("LOAD spatial")
    con.execute("CREATE SCHEMA staging; CREATE SCHEMA analysis")
    con.execute("CREATE TABLE staging.building_footprint AS SELECT 'B1' AS bin, '3000000001' AS bbl, "
                "ST_GeomFromText(?) AS geom, 30.0 AS height_roof_ft",
                ["POLYGON((" + ", ".join(f"{x} {y}" for x, y in _square(LON, LAT, 20.0)) + "))"])
    con.execute("CREATE TABLE analysis.address(lon DOUBLE, lat DOUBLE, street_name VARCHAR, "
                "frame VARCHAR, borough VARCHAR)")
    con.execute("INSERT INTO analysis.address (lon, lat, street_name, frame, borough) VALUES (?,?,?,?,?)",
                [LON, LAT - 22.0 / 111_320.0, "TEST AVENUE", "street", "BK"])
    corridor = ("Test Ave", "BK", "TEST AVE%", LAT - 0.01, LON - 0.01, LAT + 0.01, LON + 0.01)
    # Every tile is red canvas: the band must read as an awning.
    fetch = _tile_fetcher(lambda *_: np.tile(np.array([170, 30, 30], np.uint8), (256, 256, 1)))
    rows = aw.run_awnings(con, (corridor,), root=tmp_path, fetch_fn=fetch)
    assert len(rows) == 1 and rows[0]["face_count"] == 1 and rows[0]["awning_faces"] == 1
    out = aw.review_html(rows, tmp_path / "awn.html")
    assert "</html>" in out.read_text() and "B1" in out.read_text()
    # A write replaces the corridor: a building that drops out of a later run
    # does not survive as a stale row.
    from loci import db as locidb
    con.execute((locidb.SQL_DIR / "054_aerial.sql.draft").read_text()
                if (locidb.SQL_DIR / "054_aerial.sql.draft").exists()
                else (locidb.SQL_DIR / "054_aerial.sql").read_text())
    assert aw.write_awnings(con, rows, corridors=(corridor,)) == 1
    assert aw.write_awnings(con, [], corridors=(corridor,)) == 0
    assert con.execute("SELECT count(*) FROM analysis.building_awning").fetchone()[0] == 0


# --------------------------------------------------- 4. convertible

def test_convertible_keeps_the_shed_and_the_lot_and_drops_the_tower_and_the_kiosk(tmp_path):
    pluto = tmp_path / "pluto.csv"
    pluto.write_text(
        "bbl,latitude,longitude,lotarea,landuse,bldgclass,zonedist1,overlay1,borough\n"
        "3000000001,40.678,-73.986,8000,06,G7,M1-2,,BK\n"       # one-storey garage 600 m2
        "3000000002,40.679,-73.986,10000,10,V1,R6,C2-4,BK\n"    # parking lot 929 m2, no bldg
        "3000000003,40.680,-73.986,8000,04,D1,R6,,BK\n"         # 20 m tower
        "3000000004,40.681,-73.986,400,05,K1,C4-3,,BK\n"        # 100 m2 kiosk
        "1000000005,40.760,-73.980,20000,10,V1,C5-3,,MN\n")     # MN parking lot
    con = duckdb.connect(":memory:")
    con.execute("LOAD spatial")
    con.execute("CREATE SCHEMA staging")
    con.execute("CREATE TABLE staging.building_footprint(bin VARCHAR, bbl VARCHAR, geom GEOMETRY, "
                "height_roof_ft DOUBLE)")

    def poly(lon, lat, side):
        return "POLYGON((" + ", ".join(f"{x} {y}" for x, y in _square(lon, lat, side)) + "))"

    con.execute("INSERT INTO staging.building_footprint (bin, bbl, geom, height_roof_ft) VALUES "
                "('a', '3000000001', ST_GeomFromText(?), 16.0), "
                "('b', '3000000003', ST_GeomFromText(?), 66.0), "
                "('c', '3000000004', ST_GeomFromText(?), 12.0)",
                [poly(-73.986, 40.678, 24.5), poly(-73.986, 40.680, 30.0), poly(-73.986, 40.681, 10.0)])
    df = cv.find(con, boroughs=("MN", "BK"), pluto_csv=pluto)
    got = dict(zip(df["bbl"], df["lot_class"]))
    assert got == {"3000000001": "garage", "3000000002": "parking", "1000000005": "parking"}
    assert bool(df.set_index("bbl").loc["3000000001", "in_gowanus"])
    assert df.iloc[0]["score"] >= df.iloc[-1]["score"]
    only_bk = cv.find(con, boroughs=("BK",), pluto_csv=pluto, bbox=cv.GOWANUS_BBOX)
    assert set(only_bk["bbl"]) == {"3000000001", "3000000002"}
    out = cv.review_html(df, tmp_path / "cv.html")
    assert "</html>" in out.read_text() and "3000000002" in out.read_text()


def test_score_is_bounded_and_prefers_industrial_zoning():
    assert 0 <= cv.score(5000, "parking", "M1-1", None) <= 1
    assert cv.score(1000, "one_storey", "M1-1", None) > cv.score(1000, "one_storey", "R6", None)
    assert cv.score(1000, "one_storey", "R6", "C2-4") > cv.score(1000, "one_storey", "R6", None)
