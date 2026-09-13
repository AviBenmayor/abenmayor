"""NYC DOT traffic-camera REGISTRY -- where the cameras are, not what they see.

    staging.dot_camera   one row per public NYCTMC camera

THE CONTRACT THIS FILE EXISTS TO FIX
---------------------------------------------------------------------------
A sampler (frame fetch + person detection) is being built against this table.
That sampler needs one stable thing from the data layer: a keyed list of
cameras with a fetchable image URL and a position on the map. This module is
that list and nothing else. It does NOT fetch frames, does NOT count people,
and writes no sample rows -- `staging.dot_camera` is the REGISTRY grain (one
row per camera, refreshed in place), and any per-frame observation belongs in
its own table at its own grain (camera x timestamp), never as columns here.

THE FEED, VERIFIED 2026-09-13
---------------------------------------------------------------------------
    GET https://webcams.nyctmc.org/api/cameras  ->  200, application/json
    969 objects, keys exactly:
        id         uuid string, unique (0 duplicates)
        name       'Central Park West @ 86 St' -- intersection, unique
        latitude   float, EPSG:4326
        longitude  float, EPSG:4326
        area       Manhattan 376 / Queens 208 / Brooklyn 204 /
                   Staten Island 100 / Bronx 81
        isOnline   the STRING 'true' (not a bool), 969/969 at verification
        imageUrl   https://webcams.nyctmc.org/api/cameras/<id>/image

    No API key, no Referer check, no cookie: the image URL returns
    200 image/jpeg (~23 KB) to a bare request. `Cache-Control: no-store` and
    NO Last-Modified/ETag, and nine fetches five seconds apart returned nine
    DIFFERENT payloads -- so the endpoint serves a near-live frame per request
    and there is no published cadence to align a sampler to. Treat "how stale
    is this frame" as unknown-and-unknowable from the response, and let the
    sampler's own fetch time be the timestamp of record.

`isOnline` ARRIVING AS 'true' ON EVERY ROW IS A WARNING, NOT A GUARANTEE
---------------------------------------------------------------------------
969 of 969 online is not a plausible steady state for 969 outdoor cameras, so
the flag is more likely "published" than "currently returning frames". It is
stored as a BOOLEAN parsed from the string, and the sampler must still handle
a camera that 404s, times out, or returns a grey no-signal card while this
column says true. Never filter the universe on it and never report coverage
from it.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. THE SITING IS THE BIAS. These are traffic-management cameras at SIGNALISED
   INTERSECTIONS on ARTERIALS and at crossings, chosen to watch vehicle
   queues. They are not a sample of retail streets: a quiet residential block,
   a mid-block storefront, and most of the address universe have no camera and
   never will. Manhattan has 376 and the Bronx 81 -- the density gradient is
   DOT's operational one, not the city's.
2. EVERY CAMERA POINTS SOMEWHERE, AND NOWHERE SAYS WHERE. There is no bearing,
   no field of view, no height and no lens in the feed. Two cameras 20 m apart
   can see disjoint sidewalks; one may be aimed up a roadway with no sidewalk
   in frame at all. A person count from a frame is therefore a count on an
   UNKNOWN and NON-CONSTANT catchment -- not comparable between cameras
   without per-camera calibration, and not comparable over time at one camera
   if it is ever re-aimed (which happens and is not announced).
3. THE POSITION IS THE INTERSECTION, NOT THE VIEW. `latitude`/`longitude` is
   where the camera IS. What it watches is up to a few hundred metres away in
   an unknown direction, so a distance from an address to a camera is a
   distance to the pole, not to the observed sidewalk.
4. NIGHT, WEATHER, OCCLUSION. Low light, rain on the lens, a stopped truck and
   a scaffold all suppress detections without suppressing the camera. An
   absence of detected people is never evidence of an absence of people.
5. THE REGISTRY MOVES. Cameras are added, retired and re-sited with no
   changelog and no vintage in the feed, so `fetched_at` is stamped per row
   and a camera_id that vanishes from a later pull is simply gone -- there is
   no way to distinguish "retired" from "temporarily unpublished".
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import time

import requests

SOURCE_ID = "nyc_dot_traffic_cameras"
ENDPOINT = "https://webcams.nyctmc.org/api/cameras"
TIMEOUT = 60
RETRIES = 4

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
RAW_ROOT = REPO_ROOT / "data" / "raw" / SOURCE_ID

#: Fail-loud floor. 969 cameras at verification; a pull that returns a handful
#: is a broken endpoint, not a city that removed its cameras.
MIN_CAMERAS = 500

#: `area` -> the project's borough code. `analysis.address.borough` is the
#: two-letter code, so the join key has to be too. An unrecognised area maps to
#: NULL rather than to a guess -- the raw `area` string is kept beside it.
AREA_TO_BOROUGH = {
    "manhattan": "MN",
    "brooklyn": "BK",
    "queens": "QN",
    "bronx": "BX",
    "staten island": "SI",
}

COLUMNS = ["camera_id", "name", "lon", "lat", "image_url", "is_online",
           "area", "borough", "fetched_at"]


class CameraFeedError(RuntimeError):
    """A camera pull that must not be mistaken for a city with no cameras."""


def _get(url: str, *, timeout: int = TIMEOUT) -> requests.Response:
    last: object = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url, timeout=timeout,
                                headers={"User-Agent": "loci-dot-cameras"})
            if resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                time.sleep(2 + 3 * attempt)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:   # pragma: no cover - network
            last = exc
            time.sleep(2 + 3 * attempt)
    raise CameraFeedError(
        f"{url} failed after {RETRIES} attempts ({last}). Refusing to continue: "
        f"an empty camera registry would read downstream as 'no camera is near "
        f"any address', which is a confident wrong answer.")


def fetch_cameras(*, refresh: bool = False,
                  asof: dt.date | None = None) -> list[dict]:
    """The raw feed, cached under data/raw/<source>/cameras_<asof>.json.

    RAISES on a short pull. The feed is a single unpaged JSON array; there is
    no `$limit` and no cursor, so "fewer rows than expected" has no benign
    reading.
    """
    asof = asof or dt.date.today()
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    cache = RAW_ROOT / f"cameras_{asof.isoformat()}.json"
    if cache.exists() and not refresh:
        rows = json.loads(cache.read_text())
    else:
        rows = _get(ENDPOINT).json()
        cache.write_text(json.dumps(rows))
    if not isinstance(rows, list):
        raise CameraFeedError(
            f"{ENDPOINT} returned {type(rows).__name__}, not a JSON array. The "
            f"feed's shape has changed; re-derive the contract before ingesting.")
    if len(rows) < MIN_CAMERAS:
        raise CameraFeedError(
            f"{ENDPOINT} returned {len(rows)} cameras, fewer than the "
            f"{MIN_CAMERAS} floor. Refusing to ingest a truncated registry.")
    return rows


def _bool(value) -> bool | None:
    """'true' -> True. The feed sends the STRING, and bool('false') is True."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def normalise(rows: list[dict], *, fetched_at: dt.datetime | None = None
              ) -> tuple[list[dict], dict]:
    """([{camera_id, name, lon, lat, image_url, is_online, area, borough,
    fetched_at}], report).

    A row without an id, or without a usable lon/lat, is DROPPED and COUNTED --
    a camera with no position cannot be a nearest neighbour of anything, and a
    (0, 0) fallback would put it in the Gulf of Guinea and make it the nearest
    camera to nothing at all. Coordinates outside the NYC envelope are dropped
    the same way.
    """
    fetched_at = fetched_at or dt.datetime.now().replace(microsecond=0)
    out: list[dict] = []
    dropped_id = dropped_geom = dropped_bbox = 0
    unknown_area: set[str] = set()
    for r in rows:
        cid = (r.get("id") or "").strip()
        if not cid:
            dropped_id += 1
            continue
        try:
            lon = float(r["longitude"])
            lat = float(r["latitude"])
        except (KeyError, TypeError, ValueError):
            dropped_geom += 1
            continue
        # NYC envelope, generous. The feed is NYC-only today; a point outside
        # it is a data error, not a camera in New Jersey we should keep.
        if not (-74.30 <= lon <= -73.65 and 40.45 <= lat <= 40.95):
            dropped_bbox += 1
            continue
        area = (r.get("area") or "").strip() or None
        boro = AREA_TO_BOROUGH.get((area or "").lower())
        if area and boro is None:
            unknown_area.add(area)
        out.append({
            "camera_id": cid,
            "name": (r.get("name") or "").strip() or None,
            "lon": lon,
            "lat": lat,
            "image_url": (r.get("imageUrl") or "").strip() or None,
            "is_online": _bool(r.get("isOnline")),
            "area": area,
            "borough": boro,
            "fetched_at": fetched_at,
        })
    ids = [c["camera_id"] for c in out]
    if len(ids) != len(set(ids)):
        raise CameraFeedError(
            "the camera feed returned duplicate ids; `camera_id` is the "
            "sampler's key and must be unique.")
    by_boro: dict[str, int] = {}
    for c in out:
        by_boro[c["borough"] or "?"] = by_boro.get(c["borough"] or "?", 0) + 1
    report = {
        "endpoint": ENDPOINT,
        "rows_in_feed": len(rows),
        "cameras": len(out),
        "online": sum(1 for c in out if c["is_online"]),
        "offline": sum(1 for c in out if c["is_online"] is False),
        "online_unknown": sum(1 for c in out if c["is_online"] is None),
        "by_borough": dict(sorted(by_boro.items())),
        "dropped_without_id": dropped_id,
        "dropped_without_geometry": dropped_geom,
        "dropped_outside_nyc": dropped_bbox,
        "unknown_areas": sorted(unknown_area),
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
    }
    return out, report


def write_cameras(con, records: list[dict]) -> int:
    """Idempotent DELETE-then-INSERT of the whole registry.

    The feed is a full snapshot with no vintage, so an incremental merge would
    have to invent a retirement rule. Replacing the table is honest: the
    registry is what the feed says today, `fetched_at` says when today was.
    """
    if not records:
        raise CameraFeedError(
            "write_cameras got zero records -- that would empty the registry "
            "and make every address camera-less.")
    import pandas as pd

    df = pd.DataFrame(records)[COLUMNS]
    con.execute("DELETE FROM staging.dot_camera")
    con.register("_dot_cam", df)
    try:
        cols = ", ".join(COLUMNS)
        con.execute(f"INSERT INTO staging.dot_camera ({cols}) "
                    f"SELECT {cols} FROM _dot_cam")
    finally:
        con.unregister("_dot_cam")
    return len(df)


def ingest(con, *, refresh: bool = False, dry_run: bool = False
           ) -> tuple[list[dict], dict]:
    """fetch -> normalise -> write. Returns (records, report)."""
    rows = fetch_cameras(refresh=refresh)
    records, report = normalise(rows)
    report["written"] = 0 if dry_run else write_cameras(con, records)
    report["dry_run"] = bool(dry_run)
    return records, report


def probe_image(camera_id: str, image_url: str | None = None,
                *, gap_s: float = 5.0) -> dict:
    """Fetch one camera's frame TWICE `gap_s` apart and report whether the
    bytes changed. Diagnostic only -- writes nothing, stores no image.

    This is the check that told us the endpoint needs no auth and serves a
    per-request frame. It is kept as a command rather than a note so the claim
    can be re-verified when the sampler misbehaves, instead of being believed.
    """
    import hashlib

    url = image_url or f"{ENDPOINT}/{camera_id}/image"
    shots = []
    for i in range(2):
        if i:
            time.sleep(gap_s)
        resp = _get(url)
        shots.append({
            "status": resp.status_code,
            "content_type": resp.headers.get("Content-Type"),
            "bytes": len(resp.content),
            "sha1": hashlib.sha1(resp.content).hexdigest()[:12],
            "cache_control": resp.headers.get("Cache-Control"),
            "last_modified": resp.headers.get("Last-Modified"),
        })
    return {"camera_id": camera_id, "url": url, "gap_s": gap_s,
            "shots": shots, "changed": shots[0]["sha1"] != shots[1]["sha1"],
            "auth_required": False}
