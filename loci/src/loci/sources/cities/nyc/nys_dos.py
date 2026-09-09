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

--------------------------------------------------------------------------
ACTIVE FILTER (D47 follow-up) — STRUCTURALLY A NO-OP, AND THAT IS THE FINDING
--------------------------------------------------------------------------
D47 could not test whether stale licences drive the nails/hair POI-vs-ZBP
overcount, because this adapter documented `license_expiration_date` but never
fetched it. It does now. The verdict, from the live dataset on 2026-09-08:

    count(*)                       32,178
    count(license_expiration_date) 32,178   (100% fill)
    min(license_expiration_date)   2026-09-08   <- today
    rows expiring before today              0

**There is not one expired licence in the file, statewide.** The dataset is a
true active-only snapshot — DOS drops a licence from it the day it lapses,
which is the same fact the SURVIVORSHIP note above describes from the other
direction. So an "expired licence" filter removes zero rows, and licence
staleness is RULED OUT as an explanation for the nails_beauty and hair_barber
overcount. The residual must be dedup misses or genuinely distinct licensees
(a booth renter and the shop that hosts them are two licences at one address).

The filter is still implemented rather than skipped, for two reasons: it makes
the finding reproducible instead of a note in a doc, and `assert_active_only`
FAILS LOUD if DOS ever starts publishing lapsed rows — a silent change in that
direction would quietly inflate every salon count.

`license_issue_date` is a TEXT column in MM/DD/YYYY form while
`license_cur_effective_term` and `license_expiration_date` are proper
calendar_date columns; only the latter two are parsed as dates.

CAVEAT THE DATABASE CANNOT ENFORCE: "licence not expired" is not "storefront
open". A licence runs 4 years (the probed row: issued 2024-12-11, expires
2028-12-11), so a salon that closed in year one still holds a live licence for
three more. This filter can only catch lapsed paper, and there is none.
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


def _parse_date(raw) -> dt.date | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def active_state(expiration: dt.date | None, *, today: dt.date) -> tuple[bool, str]:
    """The ACTIVE verdict for one licence, and why.

    Inactive iff the licence expired before `today`. A missing expiration date
    is ACTIVE with basis `no_expiration_date` — it must not be read as expired,
    because a null here is a publishing gap, not evidence of lapse, and
    treating it as inactive would silently delete supply (fill rate is 100% on
    the probed extract, so this branch should never fire; if it starts firing,
    that is news). Returns (active, basis)."""
    if expiration is None:
        return True, "no_expiration_date"
    if expiration < today:
        return False, f"expired_{expiration.isoformat()}"
    return True, f"valid_to_{expiration.isoformat()}"


def assert_active_only(records, *, today: dt.date | None = None) -> int:
    """Fail loud if the 'active licences only' assumption stops holding.

    Returns the number of expired records found (always 0 on the dataset as
    published, verified 2026-09-08). Raises when the share of expired rows
    exceeds 1%, which would mean DOS changed what it publishes and the
    survivorship reasoning in the module docstring — and every downstream
    salon count — needs revisiting. A silent drift here inflates supply."""
    today = today or dt.date.today()
    recs = list(records)
    if not recs:
        return 0
    n_expired = sum(1 for r in recs if r.attrs.get("license_active") is False)
    if n_expired > 0.01 * len(recs):
        raise RuntimeError(
            f"nys_dos: {n_expired}/{len(recs)} ({n_expired / len(recs):.1%}) licences "
            "are expired. This dataset has always been active-only (0 expired, "
            "statewide, 2026-09-08), so the survivorship assumption in the module "
            "docstring no longer holds -- do not ingest until it is re-derived."
        )
    return n_expired


class NysDosAdapter(SourceAdapter):
    """NYS DOS appearance-enhancement/barber licensees. SNAPSHOT ONLY --
    see module docstring. Never emits opened_on/closed_on."""

    source_id = "nys_dos_appearance_enhancement"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        # Expiry/term dates added for the ACTIVE filter (D47). license_issue_date
        # is text (MM/DD/YYYY) and is carried through unparsed for provenance.
        select = ("license_number,license_type,business_name,"
                  "business_city,business_zip,georeference,"
                  "license_issue_date,license_cur_effective_term,"
                  "license_expiration_date")
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
        """Materializes before yielding so `assert_active_only` can fail LOUD
        on the whole batch BEFORE any row reaches staging.poi -- a check that
        ran after the insert would leave a table nobody should trust."""
        recs = list(self._normalize(rows))
        assert_active_only(recs)
        yield from recs

    def _normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
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
            expires = _parse_date(r.get("license_expiration_date"))
            term = _parse_date(r.get("license_cur_effective_term"))
            active, basis = active_state(expires, today=today)
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
                       "business_zip": r.get("business_zip"),
                       "license_issue_date": r.get("license_issue_date"),
                       "license_effective_term": (
                           term.isoformat() if term else None),
                       "license_expiration_date": expires.isoformat() if expires else None,
                       "license_active": active,
                       "active": active,
                       "active_basis": basis},
            )
