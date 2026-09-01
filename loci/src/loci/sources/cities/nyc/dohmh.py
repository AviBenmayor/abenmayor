"""DOHMH restaurant inspections — the ANCHOR source (GTM-17).

Dataset 43nn-pn8j on NYC Open Data (Socrata). One row per violation, so many
rows per establishment; CAMIS is the unique establishment id. This is a
near-census of food service — every food establishment is inspected — which is
why it anchors the coverage-bias calibration (CONTEXT.md §7.1). Treat its counts
as ground truth for the food tier.

Scope decision (recorded): DOHMH cleanly identifies restaurant vs cafe/bakery by
cuisine, but does NOT reliably separate bars. Bars are left to OSM (amenity=bar),
which tags them explicitly. So this adapter emits `restaurant` and `cafe_bakery`
only, never `bar`. Documenting rather than guessing.
"""
from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

ENDPOINT = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
PAGE = 50_000

CAFE_KEYWORDS = ("coffee", "tea", "bakery", "donut", "doughnut", "dessert",
                 "juice", "ice cream", "bagel", "café", "cafe")


def classify(cuisine: str | None) -> str:
    c = (cuisine or "").lower()
    return "cafe_bakery" if any(k in c for k in CAFE_KEYWORDS) else "restaurant"


class DohmhAdapter(SourceAdapter):
    source_id = "nyc_dohmh_restaurants"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        select = "camis,dba,cuisine_description,latitude,longitude,boro"
        offset, seen = 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            params = {"$select": select, "$order": "camis",
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
            camis = r.get("camis")
            lat, lon = r.get("latitude"), r.get("longitude")
            if not camis or camis in seen or not lat or not lon:
                continue
            try:
                latf, lonf = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            if latf == 0.0 or lonf == 0.0:   # DOHMH uses (0,0) for un-geocoded
                continue
            seen.add(camis)
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=camis,
                category=classify(r.get("cuisine_description")),
                name=(r.get("dba") or "").strip().title() or None,
                lon=lonf, lat=latf,
                observed_on=today,
                confidence=0.95,   # anchor source: high confidence
                attrs={"cuisine": r.get("cuisine_description"), "boro": r.get("boro")},
            )
