"""NYS DOS Active Appearance Enhancement and Barber Business and Area Renter
Licensees (GTM-19). Dataset y3u4-jbgh on NY State Open Data (Socrata).

**SURVIVORSHIP BIAS — SNAPSHOT ENRICHMENT ONLY.** This dataset lists only
CURRENTLY ACTIVE licenses; closed salons and barbershops are absent entirely
(CONTEXT.md §7.5). There is no way to distinguish "never existed" from
"existed and closed" in this data, so it must NEVER be used to construct an
openings/closings time series, growth panel, or anything else that compares
counts across time. Every record is stamped `observed_on=today` and
`opened_on`/`closed_on` are never populated, by construction, to make that
misuse structurally impossible rather than merely documented. Use this
adapter only to enrich the present-day nail/hair snapshot alongside DOHMH
(food) and OSM (everything else).

Schema (verified by fetching $limit=5 on 2026-09-01):
    license_number, license_type, license_holder_name, licensed_state,
    license_issue_date, license_cur_effective_term, license_expiration_date,
    business_name, business_address_1, business_address_2, business_city,
    business_state, business_zip, related_business_uid, georeference
        (GeoJSON Point: {"type": "Point", "coordinates": [lon, lat]})

license_type is the field that distinguishes barber vs appearance-enhancement
licensees (statewide distinct values, verified via $group):
    DOSAEBUSINESS    22842  -- Appearance Enhancement business (nail/spa/
                                cosmetology/esthetics) -> nails_beauty
    DOSAERENTER       4811  -- Appearance Enhancement area renter -> nails_beauty
    DOSBARSHOPOWNER   4325  -- Barbershop owner -> hair_barber
    DOSBARRENTER       182  -- Barber area renter -> hair_barber

The dataset is statewide and carries no county/borough column (only opaque
`:@computed_region_*` ids), so NYC scoping uses `georeference` coordinates
against the same NYC bbox used by osm_overpass.py, rather than county name
matching.
"""
from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

ENDPOINT = "https://data.ny.gov/resource/y3u4-jbgh.json"
PAGE = 50_000

# NYC bounding box: south, west, north, east (matches osm_overpass.py BBOX).
BBOX_SOUTH, BBOX_WEST, BBOX_NORTH, BBOX_EAST = 40.4, -74.3, 41.0, -73.6

# license_type -> Loci category slug.
LICENSE_TYPE_CATEGORY: dict[str, str] = {
    "DOSAEBUSINESS": "nails_beauty",
    "DOSAERENTER": "nails_beauty",
    "DOSBARSHOPOWNER": "hair_barber",
    "DOSBARRENTER": "hair_barber",
}


def classify(license_type: str | None) -> str | None:
    return LICENSE_TYPE_CATEGORY.get((license_type or "").strip().upper())


def in_nyc_bbox(lon: float, lat: float) -> bool:
    return BBOX_WEST <= lon <= BBOX_EAST and BBOX_SOUTH <= lat <= BBOX_NORTH


class NysDosAdapter(SourceAdapter):
    """NYS DOS appearance-enhancement/barber licensees. SNAPSHOT ONLY --
    see module docstring. Never emits opened_on/closed_on."""

    source_id = "nys_dos_appearance_enhancement"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        select = ("license_number,license_type,business_name,"
                  "business_city,business_zip,georeference")
        offset, seen = 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            params = {"$select": select, "$order": "license_number",
                      "$limit": page, "$offset": offset}
            resp = session.get(ENDPOINT, params=params, headers=headers, timeout=120)
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                break
            yield from rows
            seen += len(rows)
            offset += len(rows)
            if len(rows) < page or (limit is not None and seen >= limit):
                break

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        today = dt.date.today()
        seen: set[str] = set()
        for r in rows:
            license_number = r.get("license_number")
            if not license_number or license_number in seen:
                continue

            category = classify(r.get("license_type"))
            if category is None:
                continue

            geo = r.get("georeference") or {}
            coords = geo.get("coordinates") or []
            if len(coords) != 2:
                continue
            try:
                lonf, latf = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                continue
            if not in_nyc_bbox(lonf, latf):
                continue

            seen.add(license_number)
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=license_number,
                category=category,
                name=(r.get("business_name") or "").strip().title() or None,
                lon=lonf, lat=latf,
                observed_on=today,   # snapshot only -- see module docstring
                # opened_on / closed_on intentionally never set: this source
                # is active-license-only and survivorship-biased (§7.5).
                confidence=0.85,
                attrs={"license_type": r.get("license_type"),
                       "business_city": r.get("business_city"),
                       "business_zip": r.get("business_zip")},
            )
