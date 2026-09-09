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
import functools
import os
import pathlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import requests
import yaml

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
            # ACTIVE filter (D47): SLA already fetched `expirationdate`; this
            # only surfaces the verdict under the shared attrs keys `active` /
            # `active_basis` that analysis.poi_supply reads, so `bar` is a
            # TESTABLE category rather than a silent default-true. D47 found 0
            # of 3,199 bar licences expired before 2024, so this is expected to
            # remove ~nothing; the point is that the zero is measured.
            expires = _date(r.get("expirationdate"))
            active = True if expires is None else expires >= today
            basis = ("no_expiration_date" if expires is None
                     else (f"valid_to_{expires.isoformat()}" if active
                           else f"expired_{expires.isoformat()}"))
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
                       "zip": r.get("zipcode"), "expires": (r.get("expirationdate") or "")[:10],
                       "active": active, "active_basis": basis},
            )


# ---------------------------------------------------------------------------
# ALCOHOL OVERLAY (owner decision 2026-09-08)
#
# A second, independent read of the SAME feed. The adapter above emits five
# bar-type licence classes into staging.poi and that is unchanged; this section
# writes EVERY licence into staging.alcohol_licences (sql/007), classified
# on-premises vs off-premises, for a standalone map layer. Nothing here feeds
# score/, model/ or the gap flag — see the header of sql/007 for why.
# ---------------------------------------------------------------------------

CLASSIFICATION_PATH = pathlib.Path(__file__).resolve().parent / "alcohol_licences.yaml"

#: Every value `classify()` may return. The map yaml is checked against it.
CLASSIFICATIONS = ("on_premises", "off_premises_liquor", "off_premises_beer",
                   "other", "unknown")

#: SLA publishes the county; the rest of the project speaks two-letter borough
#: codes (analysis.address_gaps, viz/webmap_export.BOROUGH_NAMES).
COUNTY_BOROUGH = {"new york": "MN", "kings": "BK", "queens": "QN",
                  "bronx": "BX", "richmond": "SI"}


@functools.lru_cache(maxsize=1)
def load_classification() -> dict:
    """Parse alcohol_licences.yaml and check it against CLASSIFICATIONS.

    Fails loudly on an unknown classification value: a typo'd class would
    otherwise reach the map as a legend entry nobody defined.
    """
    doc = yaml.safe_load(CLASSIFICATION_PATH.read_text())
    descriptions = {str(k).strip().lower(): v for k, v in doc["descriptions"].items()}
    bad = {v for v in descriptions.values()} - set(CLASSIFICATIONS)
    if bad:
        raise ValueError(f"{CLASSIFICATION_PATH.name}: unknown classification(s) {sorted(bad)}")
    return {"descriptions": descriptions, "labels": doc["labels"],
            "version": doc.get("version")}


def classify(description: str | None) -> str:
    """Licence `description` -> overlay classification.

    A description the yaml does not name becomes 'unknown' rather than being
    dropped: an unseen licence type is a visible dot with an honest label, and
    tests/test_alcohol_licences.py fails so the map gets updated.
    """
    key = (description or "").strip().lower()
    return load_classification()["descriptions"].get(key, "unknown")


def unmapped_descriptions(descriptions: Iterable[str | None]) -> set[str]:
    """The licence types in `descriptions` that alcohol_licences.yaml does not
    name, as published (not lowercased) so the yaml can be pasted from this.

    The DRIFT CHECK. SLA adds licence classes; `classify()` degrades those to
    'unknown' so the map still draws them, which means nothing would ever fail
    on its own. This is what fails instead:
    tests/test_alcohol_licences.py runs it over the captured NYC vocabulary.
    """
    known = load_classification()["descriptions"]
    return {d.strip() for d in descriptions
            if d and d.strip() and d.strip().lower() not in known}


@dataclass
class AlcoholLicence:
    """One row of staging.alcohol_licences. Deliberately NOT a POIRecord —
    these never enter staging.poi."""
    licence_id: str
    description: str
    licence_class: str | None
    classification: str
    name: str | None
    address: str | None
    zip: str | None
    borough: str | None
    lon: float
    lat: float
    expires_on: dt.date | None
    active: bool
    observed_on: dt.date


def normalize_licences(rows: Iterable[dict],
                       today: dt.date | None = None) -> Iterator[AlcoholLicence]:
    """Raw SLA rows -> AlcoholLicence, one per licence id.

    Drops only what cannot be drawn: a row with no georeference, the (0, 0)
    sentinel, or a duplicate licence id. Every licence TYPE survives — that is
    the difference between this and the bar adapter above.
    """
    today = today or dt.date.today()
    seen: set[str] = set()
    for r in rows:
        lid = r.get("licensepermitid")
        geo = r.get("georeference") or {}
        coords = geo.get("coordinates") if isinstance(geo, dict) else None
        if not lid or lid in seen or not coords or len(coords) != 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        if lon == 0.0 or lat == 0.0:
            continue
        seen.add(lid)
        expires = _date(r.get("expirationdate"))
        yield AlcoholLicence(
            licence_id=lid,
            description=(r.get("description") or "").strip(),
            licence_class=r.get("class"),
            classification=classify(r.get("description")),
            name=(r.get("dba") or r.get("legalname") or "").strip().title() or None,
            address=(r.get("actualaddressofpremises") or "").strip().title() or None,
            zip=(r.get("zipcode") or "").strip()[:5] or None,
            borough=COUNTY_BOROUGH.get((r.get("premisescounty") or "").strip().lower()),
            lon=lon, lat=lat,
            expires_on=expires,
            active=True if expires is None else expires >= today,
            observed_on=today,
        )


def load_alcohol_licences(con, *, limit: int | None = None,
                          dry_run: bool = False) -> list[AlcoholLicence]:
    """fetch -> normalize -> replace staging.alcohol_licences.

    `dry_run=True` fetches and classifies but writes nothing and never touches
    `con`, so the CLI can count first and write second off ONE fetch.
    """
    records = list(normalize_licences(NysSlaAdapter().fetch(limit=limit)))
    if not dry_run:
        write_licences(con, records)
    return records


def write_licences(con, records: list[AlcoholLicence]) -> int:
    """Replace staging.alcohol_licences with `records`. Idempotent, like
    SourceAdapter.load(): the table is emptied before the insert, so a re-run
    cannot double-count."""
    import pandas as pd

    df = pd.DataFrame([{
        "licence_id": r.licence_id, "description": r.description,
        "licence_class": r.licence_class, "classification": r.classification,
        "name": r.name, "address": r.address, "zip": r.zip, "borough": r.borough,
        "lon": r.lon, "lat": r.lat,
        "expires_on": r.expires_on.isoformat() if r.expires_on else None,
        "active": r.active,
        "observed_on": r.observed_on.isoformat(),
    } for r in records])
    con.register("_alc", df)
    con.execute("DELETE FROM staging.alcohol_licences")
    con.execute("""
        INSERT INTO staging.alcohol_licences
        SELECT licence_id, description, licence_class, classification, name,
               address, zip, borough, ST_Point(lon, lat),
               CAST(expires_on AS DATE), active, CAST(observed_on AS DATE)
        FROM _alc
    """)
    con.unregister("_alc")
    return len(records)
