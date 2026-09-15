"""Address search: NYC Planning Labs GeoSearch, snapped to the Loci address
frame (D99, GTM-171; seed constraint "Search rule").

FREE AND KEYLESS -- unlike Places/Tavily/Anthropic, this endpoint costs
nothing, so there is no budget/ledger here. What it needs instead is a
REFUSAL, not a degraded answer: the seed's own words are "Out-of-universe
addresses are refused with a clear message; no degraded report." `snap()`
raises `NotInCoverage` rather than returning the nearest address regardless
of distance, and callers (the webmap search box, `loci report`) must let that
propagate rather than catching it and rendering something anyway.

TWO-STEP RESOLUTION, BBL FIRST. `analysis.address.bbl` is the join key PLUTO
already uses (sql/031_address_legality.sql) and, for a lot-frame row,
`address_id` IS the BBL string (design-allocator-report.md §0) -- so a
GeoSearch hit that carries a BBL resolves EXACTLY, with no distance
tolerance. Only when no BBL is available (GeoSearch returned none, or it does
not match a Loci row -- e.g. a BBL PLUTO carries but Loci's address frame
does not, or a D84 street-midpoint point with no lot) does `snap()` fall back
to the nearest address row within `max_m`.
"""
from __future__ import annotations

from dataclasses import dataclass

from loci.db import METRES_SQL

GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
DEFAULT_TIMEOUT_S = 10
DEFAULT_MAX_M = 50.0


class NotInCoverage(ValueError):
    """Raised by `snap()`/`resolve()` for an address GeoSearch could locate
    but that has no Loci address row within `max_m` -- or that GeoSearch
    itself could not locate at all. Always carries the user-facing message
    'not in Loci coverage' (the seed's exact wording) as `args[0]`, so a
    caller can display it directly."""

    def __init__(self, message: str = "not in Loci coverage"):
        super().__init__(message)


@dataclass
class GeoHit:
    label: str
    lat: float
    lon: float
    bbl: str | None = None


def _get(session, url: str, params: dict, timeout: int):
    if session is not None:
        return session.get(url, params=params, timeout=timeout)
    import requests
    return requests.get(url, params=params, timeout=timeout)


def geocode(text: str, *, session=None, size: int = 1,
           timeout: int = DEFAULT_TIMEOUT_S) -> GeoHit | None:
    """The top GeoSearch match for free-text `text`, or None if GeoSearch
    found nothing. `session` is injectable (any object with a `.get(url,
    params=, timeout=)` -> response with `.json()`) so tests never make a
    real HTTP call."""
    text = (text or "").strip()
    if not text:
        return None
    resp = _get(session, GEOSEARCH, {"text": text, "size": size}, timeout)
    resp.raise_for_status()
    body = resp.json()
    features = body.get("features") or []
    if not features:
        return None
    feat = features[0]
    coords = (feat.get("geometry") or {}).get("coordinates") or [None, None]
    lon, lat = coords[0], coords[1]
    if lon is None or lat is None:
        return None
    props = feat.get("properties") or {}
    label = props.get("label") or text
    bbl = (
        props.get("bbl")
        or (props.get("addendum") or {}).get("pad", {}).get("bbl")
    )
    bbl = str(bbl) if bbl else None
    return GeoHit(label=label, lat=float(lat), lon=float(lon), bbl=bbl)


def _by_bbl(con, bbl: str) -> str | None:
    row = con.execute(
        "SELECT address_id FROM analysis.address WHERE bbl = ? LIMIT 1", [bbl]).fetchone()
    return row[0] if row else None


def _nearest(con, lon: float, lat: float, max_m: float) -> tuple[str | None, float | None]:
    # analysis.address stores lon/lat DOUBLE columns, not a GEOMETRY -- unlike
    # staging.poi, there is no `geom` to flip; ST_Point(lon, lat) built here
    # is EPSG:4326 degrees by the same repo-wide convention (db.py's own
    # caveat), so METRES_SQL's coordinate flip still applies to both sides.
    metres = METRES_SQL.format(a="ST_Point(lon, lat)", b="ST_Point(?, ?)")
    row = con.execute(f"""
        SELECT address_id, {metres} AS dist_m
        FROM analysis.address
        ORDER BY dist_m ASC
        LIMIT 1
    """, [lon, lat]).fetchone()
    if not row:
        return None, None
    address_id, dist_m = row
    if dist_m is None or dist_m > max_m:
        return None, dist_m
    return address_id, dist_m


def snap(con, hit: GeoHit, max_m: float = DEFAULT_MAX_M) -> str:
    """`hit` -> a Loci `address_id`, BBL match first, else the nearest
    address row within `max_m` metres. Raises `NotInCoverage` if neither
    finds one -- see the module docstring; this must never return a distant
    "closest we've got" address."""
    if hit.bbl:
        address_id = _by_bbl(con, hit.bbl)
        if address_id is not None:
            return address_id
    address_id, _dist_m = _nearest(con, hit.lon, hit.lat, max_m)
    if address_id is None:
        raise NotInCoverage()
    return address_id


def resolve(con, query: str, *, session=None, max_m: float = DEFAULT_MAX_M) -> str:
    """`query` -> a Loci `address_id`. PASSTHROUGH if `query` already IS a
    valid `address_id` (so a caller can pipe an address_id straight through
    without a wasted geocode round-trip); otherwise geocodes `query` and
    snaps the result. Raises `NotInCoverage` if `query` neither names an
    existing address_id nor geocodes to one within coverage."""
    row = con.execute(
        "SELECT 1 FROM analysis.address WHERE address_id = ? LIMIT 1", [query]).fetchone()
    if row:
        return query
    hit = geocode(query, session=session)
    if hit is None:
        raise NotInCoverage()
    return snap(con, hit, max_m)
