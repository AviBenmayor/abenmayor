"""NYS Liquor Authority active licenses — ANCHOR for bars.

Dataset 9s3h-dpkz on data.ny.gov (Socrata), one row per license, with a
`georeference` point on 98.5% of NYC rows. This fills the one category the
DOHMH adapter deliberately leaves out: bars.

The mapping is CONSERVATIVE and the open question is tracked as QUESTIONS.md
H-D9. The `description` field is a premises/licence class, and none of them is
literally "bar":

    Food & Beverage Business, Summer Food & beverage business,
    Club, Cabaret, Bottle Club            -> bar
    Restaurant, Summer Restaurant         -> dropped — DOHMH is the anchor there
    Additional Bar*                       -> dropped — a rider on an existing
                                             premises, not a separate venue
    Grocery Store, Liquor Store, Drug Store, Wine Store,
    wholesale / producer / vessel / aircraft / venue types
                                          -> dropped — retail or not a storefront

Consequence: bars that hold a Restaurant licence are undercounted here. Say so.

Unlike NYS DOS, a companion INACTIVE file (6dg3-2z7i) exists, so closures are
recoverable — a candidate establishment panel for E5. This adapter reads the
active file only.
"""
from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

ENDPOINT = "https://data.ny.gov/resource/9s3h-dpkz.json"
PAGE = 50_000
NYC_COUNTIES = ("Kings", "Queens", "New York", "Bronx", "Richmond")

BAR_DESCRIPTIONS = {
    "food & beverage business",
    "summer food & beverage business",
    "club",
    "cabaret",
    "bottle club",
}


def _date(s: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


class NysSlaAdapter(SourceAdapter):
    source_id = "nys_sla_liquor_licenses"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        counties = ",".join(f"'{c}'" for c in NYC_COUNTIES)
        select = ("licensepermitid,dba,legalname,description,class,premisescounty,"
                  "actualaddressofpremises,city,zipcode,originalissuedate,"
                  "expirationdate,georeference")
        offset, seen = 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            params = {"$select": select,
                      "$where": f"premisescounty in({counties})",
                      "$order": "licensepermitid", "$limit": page, "$offset": offset}
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
            if (r.get("description") or "").strip().lower() not in BAR_DESCRIPTIONS:
                continue
            lid = r.get("licensepermitid")
            geo = r.get("georeference") or {}
            coords = geo.get("coordinates") if isinstance(geo, dict) else None
            if not lid or lid in seen or not coords or len(coords) != 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            if lon == 0.0 or lat == 0.0:
                continue
            seen.add(lid)
            name = (r.get("dba") or r.get("legalname") or "").strip().title() or None
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=lid,
                category="bar",
                name=name,
                lon=lon, lat=lat,
                observed_on=today,
                opened_on=_date(r.get("originalissuedate")),
                confidence=0.8,   # anchor within its licence classes; mapping is conservative (H-D9)
                attrs={"description": r.get("description"), "class": r.get("class"),
                       "county": r.get("premisescounty"), "address": r.get("actualaddressofpremises"),
                       "zip": r.get("zipcode"), "expires": (r.get("expirationdate") or "")[:10]},
            )
