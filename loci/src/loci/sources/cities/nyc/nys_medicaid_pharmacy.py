"""NYS Medicaid enrolled pharmacies — the ANCHOR for the `pharmacy` category.

Until this source landed, `pharmacy` had NO registry anchor at all:
`analysis.category_anchor.anchor_coverage` was 0.000 against 1,330 ZBP
establishments over 76 MN+BK ZIPs, and all 5,536 canonical POIs came from two
aggregators (Overture 4,328 + Foursquare 3,257), 3,540 of them single-source.
D66 recorded that as the reason pharmacy's age-fit result could not be read,
and D69 refused the curve outright; both name the same fix — "the NYS Board of
Pharmacy registry, not a relaxed gate".

--------------------------------------------------------------------------
THE BOARD OF PHARMACY REGISTRY IS NOT OBTAINABLE IN BULK. THIS IS THE PROXY.
--------------------------------------------------------------------------
`registry.yaml` planned this source as `nys_pharmacy_registrations` against
https://www.op.nysed.gov/professions/pharmacy with the honest note "Bulk access
NOT verified — the site is a licence-verification lookup". Probed 2026-09-11
and the note was right, in the strongest sense:

  * NYSED Office of the Professions publishes establishment registration status
    ONLY through https://eservices.nysed.gov/professions/verification-search,
    a one-record-at-a-time form. No export, no API, no bulk file.
  * There is no `/data` endpoint (op.nysed.gov/data -> 404), no pharmacy
    establishment dataset on data.ny.gov, and none on health.data.ny.gov.
    The full Socrata catalogue for both portals was searched on "pharmacy",
    "pharmacies", "board of pharmacy", "license verification" and "drug
    retail"; the only pharmacy-titled assets are a formulary file, the
    All-Payer Claims prescription tables and a medication-take-back-box list.

Two real bulk candidates remained; both were probed, and the loser is recorded
here so nobody re-probes it:

  (A) CMS NPPES, taxonomy 3336C0003X "Pharmacy, Community/Retail Pharmacy".
      REJECTED. It is address-only (no coordinates — a geocoding pass this
      project has no budget for), the Registry API caps enumeration at 1,200
      records per query so BROOKLYN alone truncates, and above all it is a
      LIFETIME enumeration, not an active roster: an NPI is essentially never
      deactivated when a store closes. Probed 2026-09-11: Brooklyn returns the
      full 1,200-record cap and Bronx 752 against a Medicaid active count of
      760 and 397 — i.e. ~1.6x-2x, which is the D52/D47 stale-licence trap
      wearing a federal badge. `status` is "A" on 100% of returned records,
      so the file carries no usable liveness signal at all.

  (B) NYS Medicaid Enrolled Provider Listing `keti-qx5t` on
      health.data.ny.gov. CHOSEN — this file. Probed live 2026-09-11:

        rows (NYC, any *PHARM* profession)  6,758
          SUPERVISING PHARMACIST            2,911   individuals, excluded
          PHARMACY                          2,424   <- the category
          HOSPITAL PHARMACY                 1,270   institutional, excluded
          CLINIC PHARMACY                     142   institutional, excluded
          SPECIALTY PHARMACY                   11   infusion/mail, excluded
        latitude/longitude present          2,424 of 2,424 (100%)
          ... of which (0.000000, 0.000000)     8   dropped, see below
        FILE DATE (`updated`)               2026-09-07 on every row
        boroughs   KINGS 756  QUEENS 719  NEW YORK 448  BRONX 397  RICHMOND 95
                   (after dropping the 8 ungeocodable)

Geometry needs NO geocoding pass: the State publishes lat/lon it geocoded
itself. Coordinates are decimal degrees with a leading-zero string format
("040.706600"), EPSG:4326 by this project's convention (DuckDB GEOMETRY carries
no SRID — see db.py).

--------------------------------------------------------------------------
WHY A MEDICAID ENROLMENT FILE IS A DEFENSIBLE PHARMACY REGISTRY IN NEW YORK
--------------------------------------------------------------------------
It would be a weak proxy in most states. It is a strong one here because of
NYRx: on 2023-04-01 New York carved the pharmacy benefit OUT of Medicaid
managed care and back into fee-for-service, so a pharmacy that wants to fill a
prescription for ANY of the state's ~7M Medicaid members — managed-care
enrollees included — must be an enrolled FFS provider. That is why every row in
the extract is `medicaid_type = FFS` and why the file behaves like a roster
rather than like a plan network. Enrolment also requires a current NYSED
establishment registration, so presence here implies presence in the Board of
Pharmacy registry this file is standing in for.

CAVEAT THE DATABASE CANNOT ENFORCE — THE ONE DIRECTION IT MISSES. A retail
pharmacy that serves no Medicaid patient at all is absent by construction: a
concierge/compounding/boutique pharmacy, or a brand-new store that has not
finished enrolling. That is a PARTIAL UNIVERSE in exactly the sense D69's
`anchor_is_floor` exists for, and the argument for flagging it is written out
in the report rather than acted on here — **the flag is deliberately NOT set**,
because unlike childcare's OCFS home-based half (published by nobody, a whole
regulatory universe) the missing slice here is small, skews AFFLUENT (the
opposite of the bias that makes a veto dangerous), and the true roster does
exist at NYSED and is merely not downloadable. Setting the flag is the owner's
call, not this adapter's.

--------------------------------------------------------------------------
ACTIVE FILTER — applied AT SOURCE, like DOHMH childcare, not a staleness proxy
--------------------------------------------------------------------------
The publisher's own description: "This is a list of active Medicaid
fee-for-service (FFS), Managed Care Only and Ordering, Prescribing, Referring,
Attending (OPRA) providers." Presence IS the active observation, refreshed
weekly (`updated` = 2026-09-07 across the whole extract, four days before this
adapter was written). No D36/D47 "not inspected in 24 months" inference is
needed or possible — there is no termination date column, only
`enrollment_begin_date`.

So `active` is True on every emitted record with
`active_basis = "published_active_medicaid_ffs_roster"`, and no staleness cut
is applied; inventing one would manufacture gaps.

CAVEAT THE DATABASE CANNOT ENFORCE: the refresh cadence is the publisher's, and
a store that closed since the last file date is still emitted. The trade is
chosen toward over-counting supply, the conservative direction for a GAP
screen.

--------------------------------------------------------------------------
THE RECORD KEY IS COMPOSITE, BECAUSE mmis_id IS NOT 1:1 WITH A STOREFRONT
--------------------------------------------------------------------------
This was found the hard way and is the single most dangerous thing in the
feed. `mmis_id` (the Medicaid Provider ID) looks like a per-store key — 2,423
distinct values over 2,424 PHARMACY rows — but it is a per-PROVIDER key, and a
provider may enrol more than one service location under it:

    03574081  IDEAL CARE PHARMACY INC  1621 AVENUE U  (40.59907, -73.95502)
    03574081  IDEAL CARE PHARMACY INC   811 AVENUE U  (40.59821, -73.96286)

Those are two real storefronts ~670 m apart in Sheepshead Bay / Gravesend.
Keying on `mmis_id` alone would silently DROP one of them — a deleted business
in a screen whose entire output is "which addresses have no pharmacy nearby",
i.e. a manufactured gap of exactly the kind CONTEXT.md §7 exists to prevent.
The key is therefore `mmis_id@<slugified service_address>`, which is stable
across refreshes (the enrolled service address is what the row is about) and
legible in `analysis.poi_dedup` when someone audits a cluster.

Today the composite changes the count by exactly one record. It is here for the
next refresh, not for this one.

--------------------------------------------------------------------------
THE (0, 0) NULL ISLAND — 8 rows, dropped, never ingested
--------------------------------------------------------------------------
Eight PHARMACY rows carry latitude "000.000000" and longitude "000.000000"
(V L S ALLEON DRUGS, LENOX TERRACE PHARMCY, SURYA PHARMACY, PRIME HEALTH,
QUENTIN ROAD PHARMACY, MEA PHARMACY, ...). They have real addresses; the
State's geocoder simply failed. They are DROPPED, not ingested and not
geocoded from the address string, for two reasons: a point in the Gulf of
Guinea is a silent data corruption that no downstream check would catch, and a
guessed point in a walk-distance screen is worse than a missing one (the same
rule dohmh_childcare.py applies to its 12 nulls). The drop is counted and
surfaced by the CLI so it can never become invisible.

--------------------------------------------------------------------------
ONE POI PER ENROLMENT, COLLAPSED BY THE SHARED DEDUP — not by a private rule
--------------------------------------------------------------------------
Identical stance to dohmh_childcare.py: this adapter emits one POIRecord per
enrolment and lets `score/dedup.py` do every collapse, because a second private
dedup rule is a second place for the fake-gap bug to live.

Measured with dedup.py's own `names_match` + 40 m rule on the live extract
(2026-09-11): only **6** within-source pairs union at all, out of 2,416
records. Inspected by hand, they are two Montefiore departments at one hospital
door, two CVS enrolments on West 125th St, "DOWNTOWN PHARMACY INC" vs
"DOWNTOWN PHARMACY" at the same 165 William St, two Walgreens enrolments on
Jerome Ave, CEDRA PHARMACY vs CEDRA HEALTHCARE at one corner, and ROOSEVELT
PHARMACY INC (13355) vs ROOSEVELT RX INC (13357 Roosevelt Ave). The last is the
only one that could be two genuinely distinct storefronts. No change to
`_GENERIC` or `MATCH_METERS` was needed and none was made — "pharmacy" and
"drugs" are already generic tokens, which is why the number is 6 and not 600.

--------------------------------------------------------------------------
THE BIG CAVEAT: LEGAL NAME vs TRADE NAME, AND THE RESIDUAL DOUBLE COUNT
--------------------------------------------------------------------------
`mmis_name` is the ENROLLED LEGAL ENTITY name ("PRIME HEALTH INC", "CVS ALBANY
LLC", "MIL RUE CHEMISTS INC"); the aggregators carry the TRADE name on the
awning. Where they differ, dedup.py's name rule correctly refuses to fuse two
records that are in fact one storefront.

Measured against the live staging table before building (2026-09-11): of 2,415
registry records, 1,762 (73%) sit within 40 m of an existing canonical pharmacy
POI, but only 837 actually union with an aggregator cluster. So ~925 records
are the same door as an aggregator record and stay separate.

That is survivable, and mostly self-correcting, because D52's veto deletes the
lone-aggregator half of those pairs. What it does NOT correct is the
corroborated half: **421 clusters that two aggregators both saw sit within
40 m of a registry cluster and remain counted twice** in `in_principled`
(~11% of the post-anchor principled set). This is a genuine over-count of
pharmacy supply, in the direction of UNDER-stating pharmacy gaps, and it is
recorded rather than fixed because the fix is not a dedup tweak: it is a
trade-name field. NPPES `other_names` carries the DBA for most of these NPIs
(the file's `npi` column joins to it 1:1) and is the obvious follow-up.

--------------------------------------------------------------------------
CATEGORY MAPPING
--------------------------------------------------------------------------
`profession_or_service = 'PHARMACY'` maps 1:1 to `pharmacy` (NAICS 2022 456110,
categories.yaml). Nothing is inferred from a name. Every other *PHARM* value in
the feed is an explicit, tested exclusion; a sixth value must fail loud, because
a new enrolment category changes what the anchor COVERS and is a decision for a
human, not a fall-through.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import time
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

ENDPOINT = "https://health.data.ny.gov/resource/keti-qx5t.json"
DATASET_ID = "keti-qx5t"
PAGE = 25_000

#: NYC bbox, identical to the other NYC adapters.
NYC_LON_RANGE = (-74.3, -73.6)
NYC_LAT_RANGE = (40.4, 41.0)

#: The five NYC counties as this feed spells them. Applied at source (the file
#: is statewide, ~200k rows) and re-checked by the bbox in normalize(), which
#: is the real geometry guard.
NYC_COUNTIES = ("KINGS", "QUEENS", "NEW YORK", "BRONX", "RICHMOND")

COUNTY_ABBR = {
    "NEW YORK": "MN", "KINGS": "BK", "QUEENS": "QN",
    "BRONX": "BX", "RICHMOND": "SI",
}

#: The CLOSED set of pharmacy-related enrolment categories this feed publishes,
#: observed live 2026-09-11, each mapped to whether it is RETAIL pharmacy
#: supply — i.e. a storefront a resident walks to, which is the only thing this
#: project's reach tiers mean.
#:
#: The exclusions are deliberate, not incidental:
#:   HOSPITAL PHARMACY (1,270 NYC rows) — an inpatient/outpatient dispensary
#:       inside an Article 28 hospital. Its address is the hospital's, 629 of
#:       the 1,270 rows share a coordinate with another, and it is not a
#:       daily-needs destination in the CONTEXT.md §2 sense.
#:   CLINIC PHARMACY (142) — the in-house dispensary of a diagnostic &
#:       treatment centre; dispenses to that clinic's patients.
#:   SPECIALTY PHARMACY (11) — limited-distribution / infusion, and in this
#:       extract almost entirely hospital-owned (Montefiore, Mount Sinai,
#:       Lenox Hill, MSKCC) or mail-order (OPTUM PHARMACY 706). No walk-in
#:       counter, so counting it would close gaps that are real.
#:   SUPERVISING PHARMACIST (2,911) — an INDIVIDUAL practitioner enrolment,
#:       not an establishment. Including it would put a second point on top of
#:       almost every store in the file, which is the booth-renter failure
#:       (dedup.py BOOTH_SOURCES) in a source that has no booth-renter pass.
#:
#: A value outside this set must raise: a new enrolment category changes what
#: the pharmacy anchor covers, and therefore what every surviving pharmacy gap
#: means.
KNOWN_SERVICES: dict[str, bool] = {
    "PHARMACY": True,
    "HOSPITAL PHARMACY": False,
    "CLINIC PHARMACY": False,
    "SPECIALTY PHARMACY": False,
    "SUPERVISING PHARMACIST": False,
}

SELECT = ("mmis_id,npi,mmis_name,medicaid_type,profession_or_service,"
          "service_address,city,state,zip_code,county,"
          "latitude,longitude,enrollment_begin_date,updated")

#: Fetched by substring so that a NEW pharmacy-ish enrolment category arrives
#: and trips KNOWN_SERVICES instead of being filtered away upstream where
#: nobody would see it.
#:
#: CAVEAT THE DATABASE CANNOT ENFORCE: a future retail-pharmacy category whose
#: label contains no "PHARM" substring (a hypothetical "DRUG STORE") would
#: never reach the vocabulary check and would be silently absent. The
#: alternative — pulling every NYC Medicaid provider of every profession — is
#: ~200k rows per run for a 3% yield, so the substring filter stands and the
#: blind spot is written down.
SERVICE_FILTER = "%PHARM%"


class UnknownPharmacyService(ValueError):
    """A `profession_or_service` this feed has not published before.

    Raised rather than dropped or silently kept. This source is the pharmacy
    ANCHOR: which enrolment categories it covers decides both the supply count
    and the reading of every surviving pharmacy gap (and, via D52, whether a
    lone aggregator record is deleted), so a new category is a decision for a
    human."""


def service_included(profession_or_service: str | None) -> bool:
    """Is this enrolment category RETAIL pharmacy supply?

    Pure, so the rule is testable without a network call or a database. Unlike
    dohmh_childcare's `facility_included`, a BLANK value is NOT waved through:
    there, every row in the file was a child care programme by construction and
    the field only said which regulatory article; here the field is the only
    thing separating a storefront from a hospital dispensary and from an
    individual pharmacist, so a blank is unclassifiable and must raise."""
    raw = (profession_or_service or "").strip().upper()
    if raw not in KNOWN_SERVICES:
        raise UnknownPharmacyService(
            f"NYS Medicaid profession_or_service {raw!r} is not in "
            f"KNOWN_SERVICES ({sorted(KNOWN_SERVICES)}). Classify it explicitly "
            f"before ingesting — a new enrolment category changes what the "
            f"pharmacy anchor covers, and therefore what every surviving "
            f"pharmacy gap means."
        )
    return KNOWN_SERVICES[raw]


def address_slug(address: str | None) -> str:
    """`1621 AVENUE U` -> `1621-AVENUE-U`. Part of the record key (see the
    docstring): `mmis_id` is per-PROVIDER, not per-storefront."""
    return re.sub(r"[^A-Z0-9]+", "-", (address or "").strip().upper()).strip("-")


def record_key(mmis_id: str, service_address: str | None) -> str:
    """The stable per-storefront key. Composite BECAUSE mmis_id is not one."""
    slug = address_slug(service_address)
    return f"{mmis_id}@{slug}" if slug else mmis_id


class NysMedicaidPharmacyAdapter(SourceAdapter):
    """One POI per active NYS Medicaid retail-pharmacy enrolment (see docstring).

    `dropped` counts what normalize() refused and why, so the CLI can surface
    it. A drop that nobody can see is how a silent zero gets ingested."""

    source_id = "nys_medicaid_pharmacies"

    def __init__(self) -> None:
        self.dropped: dict[str, int] = {}

    def _drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        counties = ", ".join(f"'{c}'" for c in NYC_COUNTIES)
        where = (f"upper(profession_or_service) like '{SERVICE_FILTER}' "
                 f"AND county in ({counties})")
        offset, seen, pages = 0, 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            params = {"$select": SELECT, "$where": where,
                      # Deterministic paging AND a deterministic tie-break for
                      # the composite key: mmis_id alone does not order the
                      # two-storefront providers.
                      "$order": "mmis_id, service_address, profession_or_service",
                      "$limit": page, "$offset": offset}
            # Retry, then RAISE. A partial fetch returning quietly would look
            # exactly like a city with fewer pharmacies -- and this source is
            # the anchor the whole D66/D69 pharmacy question turns on.
            for attempt in range(4):
                try:
                    resp = session.get(ENDPOINT, params=params, headers=headers,
                                       timeout=300)
                    resp.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt == 3:
                        raise
                    time.sleep(5 * 2 ** attempt)
            rows = resp.json()
            if not rows:
                break
            pages += 1
            yield from rows
            seen += len(rows)
            offset += len(rows)
            if len(rows) < page or (limit is not None and seen >= limit):
                break
        if pages == 0 and limit is None:
            # Never ingest a silent zero: an empty live feed is a failure, not
            # an observation that NYC has no pharmacies.
            raise RuntimeError(
                f"NYS Medicaid provider feed {ENDPOINT} ({DATASET_ID}) returned "
                f"no rows. Refusing to ingest an empty pharmacy universe."
            )

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        today = dt.date.today()
        seen: set[str] = set()
        for r in rows:
            # Vocabulary first, so an unknown category raises even if the row
            # would have been dropped for some other reason afterwards.
            if not service_included(r.get("profession_or_service")):
                self._drop("not_retail_pharmacy")
                continue
            mmis = (r.get("mmis_id") or "").strip()
            if not mmis:
                self._drop("no_mmis_id")
                continue
            key = record_key(mmis, r.get("service_address"))
            if key in seen:
                self._drop("duplicate_key")
                continue
            lat, lon = r.get("latitude"), r.get("longitude")
            if lat in (None, "") or lon in (None, ""):
                self._drop("no_coordinates")
                continue
            try:
                latf, lonf = float(lat), float(lon)
            except (TypeError, ValueError):
                self._drop("unparseable_coordinates")
                continue
            # NULL ISLAND. 8 rows citywide carry (0, 0) from a failed State
            # geocode. Dropped explicitly and BEFORE the bbox test so the
            # reason is legible in the counter -- see the docstring.
            if latf == 0.0 and lonf == 0.0:
                self._drop("null_island")
                continue
            if not (NYC_LON_RANGE[0] <= lonf <= NYC_LON_RANGE[1]
                    and NYC_LAT_RANGE[0] <= latf <= NYC_LAT_RANGE[1]):
                self._drop("outside_nyc_bbox")
                continue
            seen.add(key)
            county = (r.get("county") or "").strip().upper()
            name = (r.get("mmis_name") or "").strip().title() or None
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=key,
                category="pharmacy",
                name=name,
                lon=lonf, lat=latf,
                observed_on=today,
                # Anchor source, same level as DOHMH childcare and DOHMH
                # restaurants: a government roster whose rows exist because
                # someone filed an enrolment (which itself requires a current
                # NYSED establishment registration). The confidence is about
                # the RECORD being a real business, not about the universe
                # being complete -- non-Medicaid pharmacies are missing
                # (docstring) and that is a coverage caveat, not a per-record
                # doubt.
                confidence=0.95,
                attrs={
                    "mmis_id": mmis,
                    # Joins 1:1 to NPPES; the route to the DBA/trade name that
                    # would fix the legal-name dedup miss (see docstring).
                    "npi": r.get("npi"),
                    "profession_or_service": r.get("profession_or_service"),
                    "medicaid_type": r.get("medicaid_type"),
                    "address": r.get("service_address"),
                    "city": r.get("city"),
                    "borough": COUNTY_ABBR.get(county, county or None),
                    "county": county or None,
                    "zip": (r.get("zip_code") or "")[:5] or None,
                    "enrollment_begin_date": r.get("enrollment_begin_date"),
                    "file_date": r.get("updated"),
                    # profession_or_service == 'PHARMACY' -> NAICS 456110
                    # exactly; nothing is inferred from the name.
                    "mapping_confidence": "high",
                    # See the ACTIVE FILTER section of the module docstring:
                    # the publisher's file IS the active roster, refreshed
                    # weekly, so presence is the observation.
                    "active": True,
                    "active_basis": "published_active_medicaid_ffs_roster",
                },
            )


# ==========================================================================
# Pending / apply — staging that does not collide with the dedup pipeline
# ==========================================================================
#
# Identical rationale to dcwp.py and dohmh_childcare.py: `loci dedup` reads
# staging.poi and writes analysis.poi_dedup, so landing a new source directly
# into staging.poi while that runs yields a half-deduped universe the database
# cannot detect. The ingest lands in a table with the IDENTICAL schema;
# promotion is a separate, one-command, reviewable step.

PENDING_TABLE = "staging.poi_nys_medicaid_pharmacy_pending"

POI_COLUMNS = ("poi_id, source_id, source_record_id, category, tier, name, geom, "
               "observed_on, opened_on, closed_on, confidence, attrs, "
               # sql/043. NAMED, never positional: two column orders
               # exist in the wild depending on how a warehouse was
               # built (the bug commit 70cbd55 fixed on
               # analysis.storefront), and the pending table is a
               # `SELECT * ... LIMIT 0` clone whose shape follows
               # staging.poi.
               "license_status, licence_number, business_unique_id")


def ensure_pending_table(con, table: str = PENDING_TABLE) -> None:
    """Create the holding table as an exact structural copy of staging.poi.

    `LIMIT 0` clones column names and types — including GEOMETRY, which carries
    no SRID in DuckDB and is EPSG:4326 by this project's convention on both
    sides of the copy."""
    con.execute(f"CREATE TABLE IF NOT EXISTS {table} AS "
                f"SELECT * FROM staging.poi LIMIT 0")


def stage_pending(con, *, limit: int | None = None,
                  table: str = PENDING_TABLE,
                  adapter: NysMedicaidPharmacyAdapter | None = None
                  ) -> tuple[list[POIRecord], dict[str, int]]:
    """Fetch the active pharmacy roster and land it in the holding table.

    Returns (records, drop counts) — the drop counts so the CLI can print what
    was refused and why; a drop nobody can see is how a silent zero gets in.
    Idempotent: `load` deletes this source_id's prior rows first."""
    ensure_pending_table(con, table)
    ad = adapter or NysMedicaidPharmacyAdapter()
    recs = ad.load(con, limit=limit, table=table)
    return recs, dict(ad.dropped)


def apply_pending(con, table: str = PENDING_TABLE) -> tuple[int, int]:
    """Promote every row in the holding table into staging.poi.

    Replaces only the source_ids present in the holding table, so no other
    source is touched. One transaction: a half-promoted anchor would be a
    supply universe nobody could reason about. Returns
    (rows_deleted, rows_inserted)."""
    ensure_pending_table(con, table)
    src = [r[0] for r in con.execute(
        f"SELECT DISTINCT source_id FROM {table}").fetchall()]
    if not src:
        return (0, 0)
    placeholders = ", ".join("?" for _ in src)
    con.execute("BEGIN")
    try:
        deleted = con.execute(
            f"SELECT count(*) FROM staging.poi WHERE source_id IN ({placeholders})",
            src).fetchone()[0]
        con.execute(
            f"DELETE FROM staging.poi WHERE source_id IN ({placeholders})", src)
        con.execute(f"INSERT INTO staging.poi ({POI_COLUMNS}) "
                    f"SELECT {POI_COLUMNS} FROM {table}")
        inserted = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return (deleted, inserted)
