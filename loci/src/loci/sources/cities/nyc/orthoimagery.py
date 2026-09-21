"""NYC orthoimagery (OTI) -- the biennial 6-inch true-ortho, as Web Mercator tiles.

    fetch_tile(year, z, x, y)        one 256x256 JPEG, cached under data/raw/
    mosaic(year, bbox, z)            the tiles covering a lon/lat bbox, stitched
    pull(year, bbox, z)              every tile over a bbox, into the cache

THE ENDPOINT, VERIFIED 2026-09-17
---------------------------------------------------------------------------
The scope memo cites WMTS at https://maps.nyc.gov/tiles. That host's TMS
(https://maps.nyc.gov/tms/1.0.0/photo/<year>/) serves 1924, 1951, 1996,
2001-2, 2004 ... 2018 only; /photo/2022 and /photo/2024 redirect to
www.nyc.gov and return 403. The 2020, 2022 and 2024 orthos are published by
OTI on its ArcGIS Online tile cache instead:

    https://tiles.arcgis.com/tiles/yG5s3afENB5iO9fj/arcgis/rest/services/
        NYC_Orthos_<year>/MapServer/tile/{z}/{y}/{x}

    services listed: NYC_Orthos_2024, _2022, _2020 (named "NYC_Orthos_-_2020"),
    _2018, _2016, _2014, _2012, _2010, _2008, _2006, NYC_Ortho_2004,
    NYC_Orthos_2001_2, NYC_Orthos_1951, Ortho_1996_Mosaic, Ortho_1924_Mosaic.
    tileInfo: 256x256, format MIXED (JPEG bytes in practice), EPSG:3857,
    origin (-20037508.342787, 20037508.342787) = the standard XYZ grid, LODs
    to level 23; level 20 is 0.149 m/px projected = 0.113 m/px on the ground
    at 40.7 N, the first level finer than the native 6-inch product.
    copyrightText "NYC OTI". Licence: CC BY 4.0 per the OTI metadata
    (https://github.com/CityOfNewYork/nyc-geo-metadata/blob/master/Metadata/
    Metadata_AerialImagery.md); bulk GeoTIFFs at https://gis.ny.gov/orthoimagery.

    ArcGIS tile order is /tile/{z}/{y}/{x} -- ROW then COLUMN -- the reverse
    of the TMS/XYZ convention. Getting that backwards returns HTTP 200 for a
    tile somewhere else in the city, which is why the first probe here looked
    at Queens while asking for Gowanus.

WHAT A TILE IS AND IS NOT
---------------------------------------------------------------------------
Nadir, leaf-off (flown mid-March), true-ortho (building lean removed). A
facade is invisible; an awning is a strip 0.6-1.2 m wide seen from above; a
sidewalk shed is a plywood roof the same colour as a tar roof. Two-year bins
date nothing finer than "between the two flights". Every consumer of these
pixels states that on its output.

THE PULL RULE. The owner's rule is "never limit data pulls": `pull()` takes
whole tiles over a bbox and never crops a request to a footprint. Tiles are
cached by (year, z, x, y); a second run over the same bbox is a disk read.
The only budget here is the politeness one -- `CONCURRENCY` parallel
requests and a retry backoff -- because the endpoint is a public cache, not
a rate-limited API.
"""
from __future__ import annotations

import concurrent.futures
import io
import math
import os
import pathlib
import threading
import time

import numpy as np
import requests

SOURCE_ID = "nyc_orthoimagery"
SERVICE = ("https://tiles.arcgis.com/tiles/yG5s3afENB5iO9fj/arcgis/rest/services/"
           "{service}/MapServer/tile/{z}/{y}/{x}")
#: Year -> ArcGIS service name. 2020 is the odd one out in OTI's naming.
SERVICES: dict[int, str] = {
    2024: "NYC_Orthos_2024", 2022: "NYC_Orthos_2022", 2020: "NYC_Orthos_-_2020",
    2018: "NYC_Orthos_2018", 2016: "NYC_Orthos_2016", 2014: "NYC_Orthos_2014",
    2012: "NYC_Orthos_2012", 2010: "NYC_Orthos_2010", 2008: "NYC_Orthos_2008",
    2006: "NYC_Orthos_2006", 2004: "NYC_Ortho_2004", 2001: "NYC_Orthos_2001_2",
    1996: "Ortho_1996_Mosaic", 1951: "NYC_Orthos_1951", 1924: "Ortho_1924_Mosaic",
}
#: Level 20 is 0.149 m/px in PROJECTED metres (the LOD table's number) and
#: 0.113 m/px on the ground at NYC's latitude (x cos 40.7 deg): the first
#: level finer than the 6-inch (0.152 m) product, so nothing is lost to
#: resampling. Level 19 (0.227 m ground) would throw away a third of it.
NATIVE_ZOOM = 20
TILE_PX = 256
EARTH_R = 6378137.0

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
CACHE_ROOT = REPO_ROOT / "data" / "raw" / SOURCE_ID

TIMEOUT = 60
RETRIES = 4
CONCURRENCY = 8
#: A tile under this many bytes is a blank/"no data" card, not imagery.
MIN_TILE_BYTES = 500


class OrthoUnavailable(RuntimeError):
    """A tile that could not be fetched after retries. Never a blank image."""


# ---------------------------------------------------------------------------
# tile arithmetic (standard XYZ / EPSG:3857)
# ---------------------------------------------------------------------------

def tile_xy(lon: float, lat: float, z: int = NATIVE_ZOOM) -> tuple[int, int]:
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def tile_lonlat(x: float, y: float, z: int) -> tuple[float, float]:
    """The NW corner of tile (x, y); fractional x/y give any point."""
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def metres_per_pixel(lat: float, z: int = NATIVE_ZOOM) -> float:
    return 2 * math.pi * EARTH_R * math.cos(math.radians(lat)) / (TILE_PX * 2 ** z)


def tile_range(bbox: tuple[float, float, float, float], z: int = NATIVE_ZOOM
               ) -> tuple[int, int, int, int]:
    """bbox = (min_lat, min_lon, max_lat, max_lon) -> (x0, y0, x1, y1) inclusive."""
    min_lat, min_lon, max_lat, max_lon = bbox
    x0, y1 = tile_xy(min_lon, min_lat, z)
    x1, y0 = tile_xy(max_lon, max_lat, z)
    return x0, y0, x1, y1


# ---------------------------------------------------------------------------
# fetch + cache
# ---------------------------------------------------------------------------

def tile_url(year: int, z: int, x: int, y: int) -> str:
    if year not in SERVICES:
        raise KeyError(f"no ortho service for {year}; have {sorted(SERVICES)}")
    return SERVICE.format(service=SERVICES[year], z=z, y=y, x=x)


def cache_path(year: int, z: int, x: int, y: int, root: pathlib.Path = CACHE_ROOT) -> pathlib.Path:
    return root / str(year) / str(z) / str(x) / f"{y}.jpg"


def _get(session: requests.Session, url: str) -> bytes:
    last: str = ""
    for attempt in range(RETRIES):
        try:
            r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": "loci-aerial"})
        except requests.RequestException as exc:
            last = str(exc)
            time.sleep(1 + 2 * attempt)
            continue
        if r.status_code == 200 and len(r.content) >= MIN_TILE_BYTES:
            return r.content
        last = f"HTTP {r.status_code}, {len(r.content)} bytes"
        if r.status_code in (404, 422):
            break
        time.sleep(1 + 2 * attempt)
    raise OrthoUnavailable(f"{url}: {last}")


def fetch_tile(year: int, z: int, x: int, y: int, *, session: requests.Session | None = None,
               root: pathlib.Path = CACHE_ROOT, fetch_fn=None) -> bytes:
    """Bytes of one tile, from the cache or the service (then cached)."""
    p = cache_path(year, z, x, y, root)
    if p.exists():
        return p.read_bytes()
    body = (fetch_fn or (lambda u: _get(session or requests.Session(), u)))(tile_url(year, z, x, y))
    p.parent.mkdir(parents=True, exist_ok=True)
    # Unique per writer: a `pull` and a `change` run over the same bbox at the
    # same time both write this tile, and a shared .tmp name races (seen
    # 2026-09-17). Whoever lands second finds the .jpg in place and is done.
    tmp = p.with_name(f"{p.stem}.{os.getpid()}-{threading.get_ident()}.tmp")
    tmp.write_bytes(body)
    try:
        tmp.replace(p)
    except FileNotFoundError:
        if not p.exists():
            raise
    return body


def decode(body: bytes) -> np.ndarray:
    from PIL import Image

    with Image.open(io.BytesIO(body)) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def pull(year: int, bbox: tuple[float, float, float, float], z: int = NATIVE_ZOOM, *,
         root: pathlib.Path = CACHE_ROOT, fetch_fn=None, concurrency: int = CONCURRENCY,
         log=None) -> dict:
    """Every tile over `bbox` into the cache. Whole tiles, no clipping."""
    x0, y0, x1, y1 = tile_range(bbox, z)
    todo = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
            if not cache_path(year, z, x, y, root).exists()]
    total = (x1 - x0 + 1) * (y1 - y0 + 1)
    session = requests.Session()
    ok = err = 0

    def one(xy):
        x, y = xy
        try:
            fetch_tile(year, z, x, y, session=session, root=root, fetch_fn=fetch_fn)
            return True
        except OrthoUnavailable:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        for i, good in enumerate(pool.map(one, todo), 1):
            ok += good
            err += (not good)
            if log and i % 500 == 0:
                log(f"{year} z{z}: {i}/{len(todo)} fetched, {err} errors")
    return {"year": year, "zoom": z, "tiles_in_bbox": total, "cached_before": total - len(todo),
            "fetched": ok, "errors": err}


# ---------------------------------------------------------------------------
# mosaic -- the raster a consumer actually reads
# ---------------------------------------------------------------------------

class Mosaic:
    """Stitched tiles with the arithmetic to go lon/lat -> pixel.

    `img` is HxWx3 uint8; pixel (row, col) 0,0 is the NW corner of tile
    (x0, y0). `to_pixel` is exact for Web Mercator (tiles are square in
    projected metres), so a polygon rasterised through it lands where the
    orthophoto put the building.
    """

    def __init__(self, img: np.ndarray, x0: int, y0: int, z: int):
        self.img, self.x0, self.y0, self.z = img, x0, y0, z

    def to_pixel(self, lon: float, lat: float) -> tuple[float, float]:
        n = 2 ** self.z
        fx = (lon + 180.0) / 360.0 * n
        lat_r = math.radians(lat)
        fy = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
        return (fx - self.x0) * TILE_PX, (fy - self.y0) * TILE_PX

    @property
    def shape(self) -> tuple[int, int]:
        return self.img.shape[0], self.img.shape[1]


def mosaic(year: int, bbox: tuple[float, float, float, float], z: int = NATIVE_ZOOM, *,
           root: pathlib.Path = CACHE_ROOT, fetch_fn=None,
           session: requests.Session | None = None) -> Mosaic:
    x0, y0, x1, y1 = tile_range(bbox, z)
    h, w = (y1 - y0 + 1) * TILE_PX, (x1 - x0 + 1) * TILE_PX
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    session = session or requests.Session()
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            tile = decode(fetch_tile(year, z, x, y, session=session, root=root, fetch_fn=fetch_fn))
            r, c = (y - y0) * TILE_PX, (x - x0) * TILE_PX
            th, tw = tile.shape[:2]
            canvas[r:r + th, c:c + tw] = tile[:TILE_PX, :TILE_PX]
    return Mosaic(canvas, x0, y0, z)
