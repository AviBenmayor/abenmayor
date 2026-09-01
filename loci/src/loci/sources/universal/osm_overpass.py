"""OpenStreetMap via Overpass — the richest source, and the only one covering
all 15 categories (CONTEXT.md §2.1), including bars, which DOHMH deliberately
leaves out (see `sources/cities/nyc/dohmh.py`).

Also the project's most dangerous bias (CONTEXT.md §7.1): OSM undercounts
small business in lower-income and immigrant neighborhoods — precisely the
areas the thesis flags as underserved. Every record from this adapter carries
a reduced confidence to reflect that, never the DOHMH-anchor-level 0.95.

Scope decision (recorded): one query PER OSM KEY (`shop`, `amenity`, `leisure`),
using a regex value-alternation filter, rather than one query per tag value or
one giant unfiltered query for the whole bbox. A first pass at one query per
tag value (26 round trips) reliably stalled — the public Overpass instance
appears to black-hole a client making many rapid sequential requests rather
than cleanly 429ing it, so a request can hang well past any read timeout
because the TCP handshake itself never completes. Three grouped queries is a
better balance: few enough round trips to avoid tripping that behavior, small
enough per-query result sets to avoid the timeouts/504s Overpass gives on
truly unbounded whole-city queries. `[out:json]` + `out center;` so ways
return a centroid without asking Overpass to walk full way geometry. A short
courtesy delay separates requests, and a short *connect* timeout (separate
from the read timeout) makes a black-holed connection attempt fail fast
enough for the retry/backoff loop to actually kick in.
"""
from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

ENDPOINTS = [
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Overpass's frontend 406-rejects the default `python-requests/X.X` User-Agent
# (silently, as an anti-bot rule) — any descriptive one works, and setting one
# is standard Overpass API etiquette anyway.
USER_AGENT = "loci-osm-overpass-adapter/1.0 (https://github.com/AviBenmayor/loci)"

# NYC bounding box: south, west, north, east
BBOX = (40.4, -74.3, 41.0, -73.6)

# (osm_key, osm_value) -> category slug. One tag maps to exactly one category.
TAG_CATEGORY: dict[tuple[str, str], str] = {
    ("shop", "supermarket"): "grocery",
    ("shop", "greengrocer"): "grocery",
    ("shop", "grocery"): "grocery",
    ("shop", "convenience"): "convenience",
    ("amenity", "pharmacy"): "pharmacy",
    ("shop", "chemist"): "pharmacy",
    ("shop", "laundry"): "laundry",
    ("shop", "dry_cleaning"): "laundry",
    ("shop", "hairdresser"): "hair_barber",
    ("shop", "beauty"): "nails_beauty",
    ("shop", "tailor"): "tailor_repair",
    ("shop", "shoe_repair"): "tailor_repair",
    ("shop", "clothes_repair"): "tailor_repair",
    ("amenity", "restaurant"): "restaurant",
    ("amenity", "fast_food"): "restaurant",
    ("amenity", "cafe"): "cafe_bakery",
    ("shop", "bakery"): "cafe_bakery",
    ("amenity", "bar"): "bar",
    ("amenity", "pub"): "bar",
    ("amenity", "kindergarten"): "childcare",
    ("amenity", "childcare"): "childcare",
    ("amenity", "clinic"): "clinic",
    ("amenity", "doctors"): "clinic",
    ("leisure", "fitness_centre"): "fitness",
    ("amenity", "bank"): "bank",
    ("shop", "hardware"): "hardware",
    ("shop", "doityourself"): "hardware",
}

# Group tag lookups by OSM key so one Overpass query (with a regex value
# alternation) covers every tag value sharing that key.
_KEYS_IN_ORDER: list[str] = []
_VALUES_BY_KEY: dict[str, list[str]] = {}
for _key, _value in TAG_CATEGORY:
    if _key not in _VALUES_BY_KEY:
        _VALUES_BY_KEY[_key] = []
        _KEYS_IN_ORDER.append(_key)
    _VALUES_BY_KEY[_key].append(_value)

MAX_RETRIES = 3
BACKOFF_SECONDS = 5
CONNECT_TIMEOUT = 10   # seconds — fail fast on a black-holed connection
READ_TIMEOUT = 90
INTER_QUERY_DELAY = 2  # seconds — be a courteous client of a shared public API


class OsmOverpassAdapter(SourceAdapter):
    source_id = "osm_overpass"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        seen = 0
        for i, key in enumerate(_KEYS_IN_ORDER):
            if limit is not None and seen >= limit:
                break
            if i > 0:
                time.sleep(INTER_QUERY_DELAY)
            remaining = None if limit is None else max(limit - seen, 0)
            query = self._query_for_key(key, _VALUES_BY_KEY[key], cap=remaining)
            elements = self._run_query(session, query)
            for el in elements:
                # Stamp the matched tag so normalize() knows which mapping
                # produced this element without re-deriving it.
                value = (el.get("tags") or {}).get(key)
                el["_matched_tag"] = f"{key}={value}" if value else None
                yield el
                seen += 1
                if limit is not None and seen >= limit:
                    break

    @staticmethod
    def _query_for_key(key: str, values: list[str], cap: int | None) -> str:
        s, w, n, e = BBOX
        bbox_str = f"{s},{w},{n},{e}"
        alt = "|".join(values)
        value_filter = f'["{key}"~"^({alt})$"]'
        out_clause = f"out center {cap};" if cap else "out center;"
        return (
            f"[out:json][timeout:{READ_TIMEOUT}];"
            f"("
            f"node{value_filter}({bbox_str});"
            f"way{value_filter}({bbox_str});"
            f");"
            f"{out_clause}"
        )

    def _run_query(self, session: requests.Session, query: str) -> list[dict]:
        """Try each mirror, with retries. Raise if every mirror is unavailable —
        a silent 0-row ingest for a core source is worse than a loud failure."""
        for attempt in range(MAX_RETRIES):
            for endpoint in ENDPOINTS:
                try:
                    resp = session.post(
                        endpoint, data={"data": query},
                        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT + 30),
                    )
                    if resp.status_code in (429, 502, 503, 504):
                        continue  # this mirror is busy; try the next
                    resp.raise_for_status()
                    return resp.json().get("elements", [])
                except requests.RequestException:
                    continue
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
        raise RuntimeError(
            "Overpass unavailable across all mirrors after "
            f"{MAX_RETRIES} rounds; refusing to ingest a silent 0 rows. "
            "Retry later — public Overpass 504s are transient."
        )

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        today = dt.date.today()
        seen: set[str] = set()
        for el in rows:
            el_type = el.get("type")
            el_id = el.get("id")
            if not el_type or el_id is None:
                continue

            record_id = f"{el_type}/{el_id}"
            if record_id in seen:
                continue

            if el_type == "node":
                lat, lon = el.get("lat"), el.get("lon")
            elif el_type == "way":
                center = el.get("center") or {}
                lat, lon = center.get("lat"), center.get("lon")
            else:
                continue

            if lat is None or lon is None:
                continue
            try:
                latf, lonf = float(lat), float(lon)
            except (TypeError, ValueError):
                continue

            matched_tag = el.get("_matched_tag")
            category = self._category_for(el, matched_tag)
            if category is None:
                continue

            seen.add(record_id)

            tags = el.get("tags") or {}
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=record_id,
                category=category,
                name=(tags.get("name") or "").strip() or None,
                lon=lonf, lat=latf,
                observed_on=today,
                confidence=0.6,  # OSM undercounts small business in lower-income
                                 # areas — the project's most dangerous bias
                                 # (CONTEXT.md §7.1). Marked accordingly.
                attrs={"matched_tag": matched_tag},
            )

    @staticmethod
    def _category_for(el: dict, matched_tag: str | None) -> str | None:
        if matched_tag:
            key, _, value = matched_tag.partition("=")
            cat = TAG_CATEGORY.get((key, value))
            if cat:
                return cat
        # Fallback for elements fed in without the internal stamp (e.g. in
        # tests): scan the element's own tags for any known mapping.
        tags = el.get("tags") or {}
        for (key, value), cat in TAG_CATEGORY.items():
            if tags.get(key) == value:
                return cat
        return None
