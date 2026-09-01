"""DCWP Legally Operating Businesses — NYC license roster (GTM-18).

Dataset w7w3-xahh on NYC Open Data (Socrata). One row per DCA license; the
dataset spans licenses issued back to 2000, both active and lapsed, so it is
a **license roster, not a presence census** — the opposite of DOHMH's
near-census (GTM-17). Every row is filtered to `license_status == "Active"`
in `normalize()` to approximate current presence; see the scope decision
below for why that filter matters a lot here.

Schema verified live 2026-09-01 ($limit=5 sample + `$select=count(*)
&$group=business_category`, 49 distinct values total). Relevant columns:
`license_nbr` (the DCA number, e.g. "0016371-DCA"), `business_name`,
`dba_trade_name` (present on some rows), `business_category` (the industry
field — there is no separate "industry" column), `license_status`,
`license_creation_date` (the issue date), `latitude`/`longitude` (present as
decimal-degree strings on in-NYC addresses; absent on out-of-state rows),
and `address_borough` (one of the five NYC boroughs, "Outside NYC", or
blank).

Freshness (checked 2026-09-01): `GET
https://data.cityofnewyork.us/api/views/w7w3-xahh.json` reports
`rowsUpdatedAt` = 2026-08-20 — under two weeks old, i.e. NOT stale. The
CONTEXT.md open question ("portal has shown a stale refresh date") does not
hold at the metadata level today; this adapter's freshness caveat is
category-specific instead (see below), not a portal-refresh problem.

Category mapping:
- **laundry**: `business_category` containing "laundr" or "dry clean".
  DCWP licenses exactly three such categories, and they split sharply:
    - "Laundries" (the walk-in laundromat/dry-cleaner category, e.g. "167
      Laundry Mart Inc.", "WJS Cleaners Inc / J'S Cleaners") — **all 6 rows
      in the dataset are `license_status = Expired`, none Active.** DCWP
      appears to have stopped issuing/renewing this license category; it
      contributes **zero** active laundromats today.
    - "Industrial Laundry" / "Industrial Laundry Delivery" — B2B linen and
      uniform-supply services (Cintas, hotel linen suppliers), not
      neighborhood-serving walk-in laundry. Many are headquartered outside
      NYC (`address_borough = "Outside NYC"`, no lat/lon). These do have
      active licenses (~70 combined) but are not the daily-needs
      laundromat the DNCI category is meant to capture.
  Net effect: mapping DCWP's "laundr" categories onto `laundry` after an
  active-only filter yields **industrial linen suppliers, not laundromats**
  — a real coverage gap, documented rather than hidden. This is exactly the
  kind of finding CONTEXT.md's open question anticipated; it argues for
  DCWP as, at best, a thin snapshot supplement to OSM/Overture for this
  category, not a primary source.
- **pharmacy**: `business_category` containing "pharmac". None of the 49
  distinct DCWP business categories match — DCWP does not license
  pharmacies (that's NYS/DOH, not DCA). This branch is kept for schema
  completeness per the ticket but is a no-op on current data.
- Every other DCWP category (Tobacco Retail Dealer, Locksmith, Tow Truck
  Company, Home Improvement Contractor, ...) does not map onto any of the
  15 Loci categories and is dropped in `normalize()`.

Scope decision (recorded): rows are kept only when `license_status ==
"Active"` — the dataset is a license roster spanning 2000–present, and
without this filter `normalize()` would emit long-expired/surrendered
licenses as if they were live businesses. Rows are further dropped when
`address_borough == "Outside NYC"` or lat/lon is missing/non-finite, since
DCWP licenses out-of-state B2B vendors (uniform suppliers, delivery
services) that have no NYC location to score.
"""
from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

ENDPOINT = "https://data.cityofnewyork.us/resource/w7w3-xahh.json"
PAGE = 50_000

LAUNDRY_KEYWORDS = ("laundr", "dry clean")
PHARMACY_KEYWORDS = ("pharmac",)

ACTIVE_STATUS = "Active"

# NYC bbox per docs/EXECUTION.md definition of done.
NYC_LON_RANGE = (-74.3, -73.6)
NYC_LAT_RANGE = (40.4, 41.0)

SELECT = (
    "license_nbr,business_name,dba_trade_name,business_category,"
    "license_status,license_creation_date,latitude,longitude,address_borough"
)
WHERE = (
    "upper(business_category) like '%LAUNDR%' "
    "OR upper(business_category) like '%DRY CLEAN%' "
    "OR upper(business_category) like '%PHARMAC%'"
)


def classify(business_category: str | None) -> str | None:
    c = (business_category or "").lower()
    if any(k in c for k in LAUNDRY_KEYWORDS):
        # Industrial Laundry = B2B linen/uniform suppliers, NOT walkable
        # laundromats. Excluding them keeps false laundry access out of
        # industrial zones. Consumer "Laundries" has zero active licenses, so
        # DCWP contributes ~nothing to the daily-needs bundle (see docstring).
        if "industrial" in c:
            return None
        return "laundry"
    if any(k in c for k in PHARMACY_KEYWORDS):
        return "pharmacy"
    return None


class DcwpAdapter(SourceAdapter):
    source_id = "nyc_dcwp_licenses"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        offset, seen = 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            params = {"$select": SELECT, "$where": WHERE, "$order": "license_nbr",
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
            license_nbr = r.get("license_nbr")
            if not license_nbr or license_nbr in seen:
                continue
            if r.get("license_status") != ACTIVE_STATUS:
                continue
            if r.get("address_borough") == "Outside NYC":
                continue
            category = classify(r.get("business_category"))
            if category is None:
                continue
            lat, lon = r.get("latitude"), r.get("longitude")
            if not lat or not lon:
                continue
            try:
                latf, lonf = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            if not (NYC_LON_RANGE[0] <= lonf <= NYC_LON_RANGE[1]):
                continue
            if not (NYC_LAT_RANGE[0] <= latf <= NYC_LAT_RANGE[1]):
                continue
            seen.add(license_nbr)
            name = (r.get("dba_trade_name") or r.get("business_name") or "").strip().title() or None
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=license_nbr,
                category=category,
                name=name,
                lon=lonf, lat=latf,
                observed_on=today,
                confidence=0.8,
                attrs={
                    "business_category": r.get("business_category"),
                    "license_status": r.get("license_status"),
                    "license_creation_date": r.get("license_creation_date"),
                    "borough": r.get("address_borough"),
                },
            )
