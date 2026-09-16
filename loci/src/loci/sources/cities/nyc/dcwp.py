"""DCWP laundry POIs — the retail-laundry anchor (GTM-18, owner decision D55).

Two DCWP feeds live here, and the difference between them is the whole point.

--------------------------------------------------------------------------
WHY THE LICENSE-ROSTER INGEST WAS EMPTY
--------------------------------------------------------------------------
`DcwpAdapter` reads **w7w3-xahh** ("Issued Licenses", formerly "Legally
Operating Businesses") — the DCWP license roster. Probed live 2026-09-09:
49 distinct `business_category` values, 72,452 rows. The only laundry-ish
categories are

    Laundries                     6 rows, ALL `license_status = Expired`
    Industrial Laundry           64 rows (41 Active)  — B2B linen supply
    Industrial Laundry Delivery  48 rows (29 Active)  — B2B linen delivery

The six `Laundries` licenses were all created 2021-07 and all expired
2023-12-31; the category was never renewed. `Industrial Laundry*` is
uniform/linen supply (Cintas and friends), not a walk-in laundromat, and is
excluded on purpose. So after the Active filter the roster adapter emits
**zero** laundry POIs. That is not a bug in the adapter — it is the correct
reading of a roster that does not contain retail laundries.

**The retail laundries are real; they are simply not published in the
license roster.** DCWP inspects retail laundries under the `Retail Laundry`
business category — 6,785 inspections from 2023-07 to 2026-07, 3,106 of them
in 2025 alone — but `Retail Laundry` does not appear as a value of
`business_category` anywhere in w7w3-xahh, and `License Applications`
(ptev-4hud) carries only the Industrial variants. `dcwp_license_number` is
null on all but 66 of the 6,785 inspection rows, which is consistent with a
category DCWP inspects but does not publish licenses for.

The other place retail laundries appear is **m4ph-grrm ("Historical
Licenses"): 2,587 CURRENT `LAUNDRY` + 1,812 CURRENT `LAUNDRY JOBBER`.** Do
not use it. Its own description says it is the status of those licenses **as
of October 2013**, and every CURRENT row expires in 2013 or 2015. It is a
13-year-old frozen snapshot; scoring it as present-day supply would be the
purest form of the failure this project exists to avoid. It is a legitimate
*historical* layer and nothing else.

--------------------------------------------------------------------------
THE ANCHOR: DCWP INSPECTIONS (jzhd-m6uv)
--------------------------------------------------------------------------
`DcwpInspectionsAdapter` reads the inspections feed, which is shaped exactly
like DOHMH (GTM-17): one row per inspection, many rows per establishment,
so it is deduped to one POI per establishment. Clone that adapter's shape;
this is the same pattern.

  establishment key   `business_unique_id` (BA-nnnnnnn-YYYY). Verified
                      premises-level, not account-level: of 4,318 distinct
                      ids in the laundry slice, only 10 span more than one
                      (bbl, street) and only 9 carry more than one distinct
                      coordinate. `dcwp_license_number` is NOT usable — it
                      is null on 98% of Retail Laundry rows.
  geometry            `latitude`/`longitude`, decimal-degree strings,
                      EPSG:4326 by convention (DuckDB GEOMETRY carries no
                      SRID — see db.py). Fill is ~100%: 1,051 of 1,052
                      Brooklyn establishments, 1,038 of 1,038 Manhattan.

ACTIVE FILTER — and why it is better here than at DOHMH. DCWP records
business death directly: `inspection_status = 'Out of Business'` (1,217
rows). It is near-terminal — of 1,295 establishments whose latest inspection
says Out of Business, only 3 are ever inspected alive again. So the filter
reads an OBSERVATION, not a staleness proxy, and `active`/`active_basis`
follow the dohmh.py convention.

  dead markers    Out of Business, Unable to Locate, No Evidence of Activity
  live override   any live status on the SAME date wins, exactly as DOHMH's
                  same-day re-open does. `No Evidence of Activity` co-occurs
                  with `Pass`/`No Violation Issued` on 69 establishments'
                  latest date; a same-day Pass contradicts it.
  `Closed` is NOT a death marker. 98 of the 198 establishments that ever
  carry it are inspected again afterwards, so it reads as a case/premises
  closure that reverses, not a departure. Counting it as death would delete
  ~100 live laundromats and manufacture gaps.

**NO STALENESS CUT IS APPLIED, deliberately.** Unlike DOHMH's mandated
inspection cycle, DCWP laundry inspections are enforcement-driven (Patrol
and Scale), so "not inspected lately" carries no information about closure
and a time cut would invent absences. `days_since_last_inspection` is stored
in attrs so the sensitivity can be run without an edit.

CAVEATS THE DATABASE CANNOT ENFORCE
  1. The feed starts 2023-07. A retail laundry that has never been inspected
     is absent, and its absence is indistinguishable from a real gap. This
     is a coverage floor, not noise.
  2. `business_unique_id` is per business account. The 10 multi-address ids
     become one POI at their most recent address; the count is in
     attrs.n_addresses.
  3. An establishment last inspected in 2023 and since closed is still
     emitted as active. Point 3 and the no-staleness-cut decision are the
     same trade, chosen toward over-counting supply (conservative for a
     gap screen) rather than manufacturing gaps.

CATEGORIES MAPPED, AND WHAT WAS DELIBERATELY LEFT OUT — see
`KNOWN_LAUNDRY_CATEGORIES` and `NOT_MAPPED` below.
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
    "license_nbr,business_unique_id,business_name,dba_trade_name,"
    "business_category,license_type,license_status,license_creation_date,"
    "lic_expir_dd,latitude,longitude,address_borough"
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
        """Every roster row that maps onto a Loci category, EVERY STATUS.

        THE ACTIVE FILTER IS GONE (2026-09-16, owner rule: never limit a data
        pull). It used to `continue` on anything whose `license_status` was not
        'Active', which threw away the only dated ENDINGS this roster
        publishes -- and a survival clock needs the endings more than the
        beginnings. Measured on the live file: the laundry/pharmacy slice this
        adapter classifies is "Laundries" x 6 rows, ALL Expired, so the filter
        was emitting literally zero POIs and the licence_number rung of
        analysis.licence_interval_poi could never fire (see sql/043).

        THE OPEN PREDICATE IS UNCHANGED, and that is the point. Non-Active rows
        do not arrive as some new kind of open. They arrive carrying
        `license_expiration_date` (DCWP's `lic_expir_dd`), which
        model/poi_presence.poi_is_open ALREADY reads: an expiry in the past is
        'closed', an expiry in the future with active=true is 'open'. Only
        'Active' sets attrs.active = true, so nothing but an Active licence can
        reach the 'open' branch. No basis constant, no predicate branch and no
        supply-set rule was added for this change -- if the supply hash moves,
        it moves because a row EXISTS that did not before, never because the
        rule changed underneath the rows that were already there.
        """
        today = dt.date.today()
        seen: set[str] = set()
        for r in rows:
            license_nbr = r.get("license_nbr")
            if not license_nbr or license_nbr in seen:
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
            status = (r.get("license_status") or "").strip()
            expiry = _parse_iso_date(r.get("lic_expir_dd"))
            # ACTIVE is the publisher's word and the ONLY one that sets
            # attrs.active. Every other status ('Expired', 'Surrendered',
            # 'Revoked', 'Voided', 'Suspended', 'Failed to Renew', 'Ready for
            # Renewal', 'Out of Business', 'Close') is carried verbatim and
            # yields active=false, which poi_is_open reads as 'unknown' -- NOT
            # as a published closure. Only the EXPIRY DATE can produce
            # 'closed', because only it is dated. Inventing a closure date for
            # a surrendered licence (the pull date? the expiry? a midpoint?)
            # would hand a survival model a fabricated hazard shape.
            is_active = status.upper() == ACTIVE_STATUS.upper()
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=license_nbr,
                category=category,
                name=name,
                lon=lonf, lat=latf,
                observed_on=today,
                confidence=0.8,
                license_status=status or None,
                licence_number=license_nbr,
                business_unique_id=r.get("business_unique_id"),
                attrs={
                    "business_category": r.get("business_category"),
                    "license_type": r.get("license_type"),
                    "license_status": status or None,
                    "license_creation_date": r.get("license_creation_date"),
                    # The key poi_is_open coalesces for the expiry branch. Named
                    # to match EXPIRY_ATTR_KEYS, not DCWP's `lic_expir_dd`.
                    "license_expiration_date": (expiry.isoformat() if expiry
                                                else None),
                    "licence_number": license_nbr,
                    "business_unique_id": r.get("business_unique_id"),
                    "active": is_active,
                    "active_basis": ("valid_to_" + expiry.isoformat()
                                     if is_active and expiry
                                     else "no_expiration_date" if is_active
                                     else "license_status_"
                                          + (status.lower().replace(" ", "_")
                                             or "absent")),
                    "mapping_confidence": "high",   # exact category-value match
                    "borough": r.get("address_borough"),
                },
            )


# ==========================================================================
# DCWP Inspections (jzhd-m6uv) — the retail-laundry anchor (D55)
# ==========================================================================

INSPECTIONS_ENDPOINT = "https://data.cityofnewyork.us/resource/jzhd-m6uv.json"

#: The FROZEN vocabulary. Every `business_category` value in the inspections
#: feed that looks like laundry, as observed live on 2026-09-09, mapped to a
#: Loci category or explicitly to None. This is a CLOSED set on purpose: an
#: unseen laundry-like value must fail loudly (see `classify_inspection` and
#: tests/test_dcwp.py::test_laundry_vocabulary_is_closed) rather than be
#: silently dropped, because a silent drop is indistinguishable from a real
#: supply gap and this category is the one the ranking turns on.
KNOWN_LAUNDRY_CATEGORIES: dict[str, str | None] = {
    # --- mapped to `laundry` ------------------------------------------------
    # The walk-in laundromat / wash-and-fold category. 6,785 inspections,
    # 3,917 establishments citywide. NAICS 812310.
    "Retail Laundry": "laundry",
    # Legacy-coded (the "- NNN" suffix is DCWP's old business-code scheme) but
    # still actively inspected through 2026-07: 621 inspections, 526
    # establishments. NAICS 812320; categories.yaml calls the category
    # "Laundromat / dry cleaner", so drop-off dry cleaning belongs in it.
    "Dry Cleaners - 230": "laundry",
    # --- deliberately NOT mapped -------------------------------------------
    # B2B linen and uniform supply (Cintas and peers). Not neighbourhood-
    # serving, frequently in industrial zones; counting them would put false
    # laundry access where no resident can use it. Consistent with the
    # long-standing exclusion in `classify()` above.
    "Industrial Laundry": None,
    "Industrial Laundry Delivery": None,
}

#: Categories in this feed that DO map onto one of the 15 Loci categories but
#: are deliberately left for a later, separately measured pass. Recorded so the
#: omission is a decision on the record rather than an oversight:
#:   Grocery-Retail - 808 / Supermarket - 819  -> grocery
#:   Salons And Barbershop - 841               -> hair_barber
#:   Drug Store Retail - 810                   -> pharmacy
#:   Restaurant - 818                          -> restaurant
#: Reasons: (a) D55 scopes this work to laundry; (b) three of the four already
#: have a loaded anchor (DOHMH for restaurant, NYS DOS for hair_barber) and
#: adding a second registry source per category changes what
#: `registry_anchored` means, so each needs its own anchor-coverage
#: measurement first; (c) DCWP inspection coverage of those categories is
#: enforcement-driven, not a census, so it would understate supply.
#: Everything else DCWP inspects (Tobacco Retail Dealer, Electronic Cigarette
#: Dealer, Electronics Store, Secondhand Dealer, Home Improvement Contractor,
#: Locksmith, Tow Truck, Stoop Line Stand, Garage & Parking Lot, Pawnbroker,
#: Newsstand, ...) maps onto NONE of the 15 and is dropped.
NOT_MAPPED = (
    "grocery-retail", "supermarket", "salons and barbershop",
    "drug store retail", "restaurant",
)

#: Inspection outcomes that mean the establishment is gone.
DEAD_STATUSES = frozenset({"Out of Business", "Unable to Locate",
                           "No Evidence of Activity"})
#: Outcomes that mean an inspector found a going concern. `Closed` is here on
#: purpose — see the module docstring; it reverses on half the establishments
#: that carry it, so it is a case closure, not a departure.
LIVE_STATUSES = frozenset({"Pass", "No Violation Issued", "Violation Issued",
                           "Re-inspection", "Fail", "Warning",
                           "No Warning Issued", "NOH Withdrawn", "Closed"})

INSPECTION_SELECT = (
    "business_unique_id,dcwp_license_number,business_name,dba_trade_name,"
    "business_category,"
    "inspection_number,inspection_type,inspection_status,date_of_occurrence,"
    "borough,bbl,bin,nta,zip_code,building_no,street_1,latitude,longitude"
)
INSPECTION_WHERE = (
    "upper(business_category) like '%LAUNDR%' "
    "OR upper(business_category) like '%DRY CLEAN%'"
)


class UnknownLaundryCategory(ValueError):
    """A laundry-like `business_category` DCWP has not shown before.

    Raised rather than dropped: this source anchors the laundry category, and
    a value quietly falling through the mapping would shrink supply and
    manufacture exactly the gaps the project is looking for."""


def classify_inspection(business_category: str | None) -> str | None:
    """Map one inspections `business_category` onto a Loci category.

    Returns None for anything that is not laundry-like. Raises
    UnknownLaundryCategory for a laundry-like value absent from the frozen
    vocabulary — vocabulary drift must fail loud, not silently."""
    raw = (business_category or "").strip()
    if not raw:
        return None
    if raw in KNOWN_LAUNDRY_CATEGORIES:
        return KNOWN_LAUNDRY_CATEGORIES[raw]
    low = raw.lower()
    if any(k in low for k in LAUNDRY_KEYWORDS) or "launder" in low:
        raise UnknownLaundryCategory(
            f"DCWP inspections category {raw!r} looks like laundry but is not in "
            f"KNOWN_LAUNDRY_CATEGORIES. Classify it explicitly (map it or map it "
            f"to None) before ingesting; do not let it fall through."
        )
    return None


def inspection_active_state(statuses: Iterable[str],
                            ) -> tuple[bool, str]:
    """The ACTIVE verdict for one establishment, and why.

    `statuses` are the inspection outcomes recorded on the establishment's
    MOST RECENT inspection date. Inactive iff a dead marker is present and no
    live outcome contradicts it on that same date. Returns (active, basis),
    following the dohmh.py convention."""
    st = {s for s in statuses if s}
    if not st:
        return True, "no_status"
    dead = st & DEAD_STATUSES
    live = st & LIVE_STATUSES
    if dead and not live:
        return False, "_".join(sorted(dead)).lower().replace(" ", "_")
    if dead and live:
        return True, "dead_marker_overridden_same_day"
    return True, "inspected_" + "_".join(sorted(st)).lower().replace(" ", "_")


class DcwpInspectionsAdapter(SourceAdapter):
    """One POI per DCWP-inspected retail laundry / dry cleaner."""

    source_id = "nyc_dcwp_inspections"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        import time
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        offset, seen, pages = 0, 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            params = {"$select": INSPECTION_SELECT, "$where": INSPECTION_WHERE,
                      "$order": "inspection_number",
                      "$limit": page, "$offset": offset}
            # Retry, then RAISE. A partial fetch that returned quietly would
            # look exactly like a shrinking city -- and this source anchors
            # the category the whole ranking turns on.
            for attempt in range(4):
                try:
                    resp = session.get(INSPECTIONS_ENDPOINT, params=params,
                                       headers=headers, timeout=300)
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
            # Never ingest a silent zero: an empty live feed is a failure,
            # not an observation that NYC has no laundromats.
            raise RuntimeError(
                f"DCWP inspections feed returned no rows for {INSPECTION_WHERE!r}. "
                f"Refusing to ingest an empty laundry universe."
            )

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        today = dt.date.today()
        # business_unique_id -> aggregation state
        cats: dict[str, set[str]] = {}
        last: dict[str, str] = {}            # max date_of_occurrence (ISO str)
        last_rows: dict[str, list[dict]] = {}  # rows on that max date
        n_insp: dict[str, int] = {}
        addrs: dict[str, set] = {}
        licnos: dict[str, set[str]] = {}

        for r in rows:
            bid = r.get("business_unique_id")
            if not bid:
                continue
            category = classify_inspection(r.get("business_category"))
            if category is None:
                continue
            cats.setdefault(bid, set()).add(category)
            n_insp[bid] = n_insp.get(bid, 0) + 1
            addrs.setdefault(bid, set()).add((r.get("bbl"), r.get("building_no"),
                                              r.get("street_1")))
            lic = (r.get("dcwp_license_number") or "").strip()
            if lic:
                licnos.setdefault(bid, set()).add(lic)
            d = r.get("date_of_occurrence") or ""
            prev = last.get(bid)
            if prev is None or d > prev:
                last[bid], last_rows[bid] = d, [r]
            elif d == prev:
                last_rows[bid].append(r)

        for bid, category_set in cats.items():
            latest = last_rows[bid]
            # Identity and geometry come from the MOST RECENT inspection: the
            # current name and address, not a stale first sighting.
            ident = next((r for r in latest if r.get("latitude") and r.get("longitude")),
                         None)
            if ident is None:
                continue          # ungeocoded establishment: cannot be placed
            try:
                latf, lonf = float(ident["latitude"]), float(ident["longitude"])
            except (TypeError, ValueError):
                continue
            if not (NYC_LON_RANGE[0] <= lonf <= NYC_LON_RANGE[1]):
                continue
            if not (NYC_LAT_RANGE[0] <= latf <= NYC_LAT_RANGE[1]):
                continue

            active, basis = inspection_active_state(
                r.get("inspection_status") for r in latest)
            last_date = _parse_iso_date(last[bid])
            # The licence number, where DCWP published one on ANY inspection of
            # this establishment -- not only the latest. min() over the
            # non-null set so the value is deterministic across two runs; an
            # establishment with two licence numbers is a data question, not
            # something to pick arbitrarily.
            lic = sorted(licnos.get(bid) or ())
            licence_number = lic[0] if lic else None
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=bid,
                # Both mapped values are `laundry`; min() keeps it
                # deterministic if that ever stops being true.
                category=min(category_set),
                name=((ident.get("dba_trade_name") or ident.get("business_name") or "")
                      .strip().title() or None),
                lon=lonf, lat=latf,
                observed_on=today,
                # High but below DOHMH's 0.95: DCWP inspects retail laundries
                # broadly but the feed only starts 2023-07, so a never-
                # inspected laundry is invisible (docstring caveat 1).
                confidence=0.9,
                attrs={
                    "business_category": ident.get("business_category"),
                    "borough": ident.get("borough"),
                    "nta": ident.get("nta"),
                    "bbl": ident.get("bbl"),
                    "bin": ident.get("bin"),
                    "zip": ident.get("zip_code"),
                    "last_inspection_date": last_date.isoformat() if last_date else None,
                    "days_since_last_inspection": ((today - last_date).days
                                                   if last_date else None),
                    "latest_status": sorted({r.get("inspection_status")
                                             for r in latest if r.get("inspection_status")}),
                    "n_inspections": n_insp[bid],
                    "n_addresses": len(addrs[bid]),
                    "mapping_confidence": "high",   # exact category-value match
                    "licence_number": licence_number,
                    "business_unique_id": bid,
                    "active": active,
                    "active_basis": basis,
                },
                # sql/043. `dcwp_license_number` is NULL on 98% of Retail
                # Laundry rows -- DCWP inspects this category but does not
                # publish licences for it -- so this column is mostly NULL BY
                # CONSTRUCTION, not by a fetch failure. `business_unique_id` is
                # the key that actually crosses the two DCWP feeds and it is
                # populated on every row.
                license_status=None,
                licence_number=licence_number,
                business_unique_id=bid,
            )


def _parse_iso_date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


# ==========================================================================
# Pending / apply — staging that does not collide with the dedup pipeline
# ==========================================================================
#
# WHY A HOLDING TABLE. `loci dedup` reads staging.poi and writes
# analysis.poi_dedup. Landing a new source directly into staging.poi while
# that is running yields a half-deduped universe: the DB cannot detect it,
# and the symptom (a category whose supply jumps between steps) looks like a
# finding. So the ingest lands in a table with the IDENTICAL schema, and
# promotion is a separate, one-command, reviewable step.

PENDING_TABLE = "staging.poi_dcwp_pending"

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

    `LIMIT 0` clones column names and types — including GEOMETRY, which
    carries no SRID in DuckDB and is EPSG:4326 by this project's convention
    on both sides of the copy. Constraints are not cloned; the promotion step
    inserts into the real, constrained staging.poi, which is where they
    matter."""
    con.execute(f"CREATE TABLE IF NOT EXISTS {table} AS "
                f"SELECT * FROM staging.poi LIMIT 0")


def stage_pending(con, *, limit: int | None = None,
                  table: str = PENDING_TABLE) -> list[POIRecord]:
    """Fetch DCWP inspections and land them in the holding table. Idempotent."""
    ensure_pending_table(con, table)
    return DcwpInspectionsAdapter().load(con, limit=limit, table=table)


def apply_pending(con, table: str = PENDING_TABLE) -> tuple[int, int]:
    """Promote every row in the holding table into staging.poi.

    Replaces only the source_ids present in the holding table, so no other
    source is touched. Runs in one transaction: a half-promoted source would
    be a supply universe nobody could reason about. Returns
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
