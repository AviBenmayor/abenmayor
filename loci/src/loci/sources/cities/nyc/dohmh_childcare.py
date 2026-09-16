"""DOHMH child care programs — the ANCHOR for the `childcare` category (D65).

Until this source landed, `childcare` had NO registry anchor at all:
`analysis.category_anchor.anchor_coverage` was 0.000 and all 4,302 canonical
POIs came from Overture (3,422) + Foursquare (1,446). D64 refused the childcare
age-fit curve partly because that made the Borough Park result unreadable —
"375 m from the nearest childcare" could be a real desert or aggregator
under-coverage of Hasidic daycare, and with no registry feed there was no way
to tell. This source is the way to tell.

--------------------------------------------------------------------------
THE DATASET THE REGISTRY NAMED IS A FROZEN SNAPSHOT. DO NOT USE IT.
--------------------------------------------------------------------------
`registry.yaml` planned this source on **dsg6-ifza**, "DOHMH Childcare Center
Inspections". Probed live 2026-09-10:

    name            "DOHMH Childcare Center Inspections (HISTORICAL)"
    rows            27,828 inspection rows, 3,014 distinct `dc_id`
    max inspection  2023-04-24
    portal note     "Due to an ongoing upgrade, this dataset reflects data as
                     of 5/14/2019. We will resume publishing updated data when
                     the upgrade is completed."

It is a 2019-vintage extract republished once in 2023 and dead since. Scoring
it as present-day supply is exactly the failure D55 refused for DCWP's 2013
"Historical Licences" snapshot (see dcwp.py). It is a legitimate *historical*
layer and nothing else, and it carries no coordinates — only building/street.

--------------------------------------------------------------------------
THE LIVE SOURCE: gy3q-4tzp
--------------------------------------------------------------------------
"Active NYC Health Code Regulated Child Care Programs", the Health
Department's own current roster, created 2023-11-02, **rowsUpdatedAt
2026-09-09** (the day before this adapter was written). Probed live
2026-09-10:

    rows                    2,755          one row per PROGRAM
    distinct `dcid`         2,755          1:1 with rows -> the record key
    distinct `permit_number` 2,306         NOT usable: 450 rows carry "N/A"
    latitude/longitude      2,743 filled (99.56%); the 12 nulls also have
                            null bbl/borough and are dropped, not geocoded
    bbl / bin / nta_code / census_tract  present on the same 2,743
    boroughs                BK 1,167  MN 583  QN 551  BX 322  SI 131  (+1 null)

Geometry therefore needs NO geocoding pass at all — unlike the historical
dataset the registry planned against, this one publishes lat/lon that DOHMH
geocoded itself. Coordinates are decimal degrees, EPSG:4326 by this project's
convention (DuckDB GEOMETRY carries no SRID — see db.py).

--------------------------------------------------------------------------
WHAT IT COVERS, AND THE ONE THING IT DOES NOT — the Borough Park question
--------------------------------------------------------------------------
Two regulatory universes, both group settings:

    GCC   2,305 rows   NYC Health Code Article 47, Group Child Care
    SBCC    450 rows   NYC Health Code Article 43, School-Based Child Care

SBCC is kept. A UPK or nursery class inside a yeshiva or parochial school is a
real childcare destination a parent walks to, it is NAICS 624410 work, and it
is precisely the supply D64 hypothesised the aggregators were missing in
Borough Park and South Williamsburg. `facility_type` is stamped in `attrs` so
a GCC-only sensitivity is one query away and needs no re-ingest.

**HOME-BASED / FAMILY DAY CARE IS ABSENT, AND THAT IS NOT FIXABLE HERE.**
Family Day Care (FDC, up to 6 children) and Group Family Day Care (GFDC, up to
12) in a provider's own apartment are licensed by **NYS OCFS**, not by DOHMH,
and appear in NO NYC Open Data feed. The dataset's own description is explicit
that it lists Article 47 and Article 43 programs only. In neighbourhoods where
informal and home-based care carries a large share of the market — Borough
Park is the standing example — this source is a FLOOR on childcare supply, not
a census of it. So:

  * a childcare gap that SURVIVES this anchor is still not proof of a desert;
  * but the anchor can only ADD supply, so a gap that this anchor CLOSES is
    settled — it was aggregator under-coverage.

That asymmetry is the whole reason to load it before re-testing the D64 curve.

--------------------------------------------------------------------------
ACTIVE FILTER — applied AT SOURCE, which is stronger than D36/D47's proxy
--------------------------------------------------------------------------
DOHMH restaurants (dohmh.py) has no status column, so D36/D47 had to infer
death from "not inspected in 24 months" — a proxy, with the caveat that it
keeps a closed restaurant whose successor has not opened. THIS feed needs no
proxy: the publisher states that programs with a 'preliminary', 'suspended' or
'closed' status are **not included**. Presence in the file IS an observation of
active permitted status, refreshed daily, the same class of evidence DCWP's
`inspection_status` gives (D55) rather than the staleness inference.

So `active` is True for every emitted record, with
`active_basis = "published_active_roster"`, and NO staleness cut is applied —
there is no inspection date in this feed to cut on, and inventing one would
manufacture gaps. The `active` / `active_basis` keys are still written so the
attrs contract matches dohmh.py and dcwp.py and a future filter has somewhere
to land.

CAVEAT THE DATABASE CANNOT ENFORCE: the refresh cadence is the publisher's. A
programme that closed since the last refresh is still emitted. Unlike DOHMH
restaurants there is no permit-expiry column here (the historical dataset had
`permitexp`; this one does not), so no independent staleness test is available
at all. The trade is chosen toward over-counting supply, which is the
conservative direction for a GAP screen.

--------------------------------------------------------------------------
ONE POI PER PROGRAM, COLLAPSED BY THE SHARED DEDUP — not by a private rule
--------------------------------------------------------------------------
`dcid` identifies a PROGRAM, not a storefront: one centre running an INFANT
TODDLER and a PRESCHOOL programme is two rows at one door. 574 coordinate
clusters hold more than one programme (1,169 rows), and 414 of those clusters
carry a single distinct `program_name`.

This adapter deliberately does NOT collapse them itself. It emits one
POIRecord per `dcid` and lets `score/dedup.py` — the one entity-resolution
rule this project has — do the collapse, for two reasons: a second private
dedup rule is a second place for the "fake gap" bug to live, and every `dcid`
stays recoverable in `analysis.poi_dedup` as a survivorship record.

Measured on the live extract with dedup.py's own `names_match` + 40 m rule
(2026-09-10): 518 within-source pairs union at the SAME bbl (the infant /
preschool split, correctly fused) and 47 union across DIFFERENT bbls. Those 47
were inspected by hand and are the same operator at an adjacent building
number — 245 vs 247 86th Street, 224 vs 232-26 East 47th Street, 1353 vs 1363
50th Street — i.e. correct fuses, not distinct storefronts being erased. No
change to `_GENERIC` or `MATCH_METERS` was needed, and none was made.

CAVEAT THE DATABASE CANNOT ENFORCE: two genuinely unrelated centres sharing a
building AND a similar name within 40 m would be fused. 160 coordinate
clusters carry more than one distinct name; the ones that survive the name
rule (e.g. Tolentine Zeiser vs Saint Dominic's at one address) stay separate,
which is the intended behaviour.

--------------------------------------------------------------------------
CATEGORY MAPPING
--------------------------------------------------------------------------
Every row in this feed is `childcare` (NAICS 624410, categories.yaml). There is
no vocabulary to drift, so there is no frozen-vocabulary guard of the kind
dcwp.py needs — but `facility_type` IS checked against a closed set, because a
new regulatory universe appearing in this feed (e.g. an OCFS home-based
merge) would change what the anchor MEANS and must be a decision, not a
silent ingest.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

ENDPOINT = "https://data.cityofnewyork.us/resource/gy3q-4tzp.json"
PAGE = 50_000

#: NYC bbox, identical to the other NYC adapters.
NYC_LON_RANGE = (-74.3, -73.6)
NYC_LAT_RANGE = (40.4, 41.0)

#: The CLOSED set of regulatory universes this feed publishes, as observed
#: live 2026-09-10, each mapped to whether it counts as childcare supply.
#: A value outside this set must fail loud (`UnknownFacilityType`): it would
#: mean DOHMH started publishing a universe this adapter has never reasoned
#: about — most consequentially an OCFS home-based merge, which is the single
#: change that would most alter what this anchor covers (see the docstring).
KNOWN_FACILITY_TYPES: dict[str, bool] = {
    # Article 47 group child care — the core of the category.
    "GCC": True,
    # Article 43 school-based child care (UPK / nursery inside a school,
    # including yeshivas and parochial schools). Kept: a real walkable
    # childcare destination and the supply D64 suspected was missing.
    "SBCC": True,
}

#: Borough spellings this feed uses -> the two-letter codes the rest of the
#: project reports in. Unknown boroughs are kept (the bbox is the real filter);
#: this map only exists so the CLI summary reads like the other ingests'.
BOROUGH_ABBR = {
    "MANHATTAN": "MN", "BROOKLYN": "BK", "QUEENS": "QN",
    "BRONX": "BX", "STATEN ISLAND": "SI",
}

SELECT = ("dcid,permit_number,program_name,facility_type,program_type,address,"
          "borough,zipcode,age_range,capacity,bin,bbl,nta_code,census_tract,"
          "community_board,latitude,longitude")


class UnknownFacilityType(ValueError):
    """A `facility_type` DOHMH has not published before.

    Raised rather than dropped or silently kept. This source is the childcare
    ANCHOR: what universes it covers decides both the supply count and the
    reading of every surviving childcare gap, so a new universe is a decision
    for a human, not a fall-through."""


def facility_included(facility_type: str | None) -> bool:
    """Does this regulatory universe count as childcare supply?

    Pure, so the rule is testable without a network call or a database."""
    raw = (facility_type or "").strip().upper()
    if not raw:
        # A blank facility_type is not a new universe, just a blank field; the
        # row is still an active permitted child care program in this file.
        return True
    if raw not in KNOWN_FACILITY_TYPES:
        raise UnknownFacilityType(
            f"DOHMH childcare facility_type {raw!r} is not in "
            f"KNOWN_FACILITY_TYPES ({sorted(KNOWN_FACILITY_TYPES)}). Classify it "
            f"explicitly before ingesting — a new regulatory universe changes "
            f"what the childcare anchor covers."
        )
    return KNOWN_FACILITY_TYPES[raw]


class DohmhChildcareAdapter(SourceAdapter):
    """One POI per active DOHMH-permitted child care PROGRAM (see docstring)."""

    source_id = "nyc_dohmh_childcare"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        offset, seen, pages = 0, 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            params = {"$select": SELECT, "$order": "dcid",
                      "$limit": page, "$offset": offset}
            # Retry, then RAISE. A partial fetch returning quietly would look
            # exactly like a city with fewer daycares -- and this source is the
            # anchor the childcare re-test turns on.
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
            # an observation that NYC has no child care.
            raise RuntimeError(
                f"DOHMH childcare feed {ENDPOINT} returned no rows. Refusing to "
                f"ingest an empty childcare universe."
            )

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        today = dt.date.today()
        seen: set[str] = set()
        for r in rows:
            dcid = (r.get("dcid") or "").strip()
            if not dcid or dcid in seen:
                continue
            if not facility_included(r.get("facility_type")):
                continue
            lat, lon = r.get("latitude"), r.get("longitude")
            if lat in (None, "") or lon in (None, ""):
                continue          # 12 rows citywide; also lack bbl/borough
            try:
                latf, lonf = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            if not (NYC_LON_RANGE[0] <= lonf <= NYC_LON_RANGE[1]):
                continue
            if not (NYC_LAT_RANGE[0] <= latf <= NYC_LAT_RANGE[1]):
                continue
            seen.add(dcid)
            boro = (r.get("borough") or "").strip().upper()
            name = (r.get("program_name") or "").strip().title() or None
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=dcid,
                category="childcare",
                name=name,
                lon=lonf, lat=latf,
                observed_on=today,
                # Anchor source, same level as DOHMH restaurants: a government
                # permit roster refreshed daily. The confidence is about the
                # RECORD being a real business, not about the universe being
                # complete -- home-based care is missing (docstring) and that
                # is a coverage caveat, not a per-record doubt.
                confidence=0.95,
                attrs={
                    "permit_number": r.get("permit_number"),
                    "facility_type": r.get("facility_type"),
                    "program_type": r.get("program_type"),
                    "age_range": r.get("age_range"),
                    "capacity": r.get("capacity"),
                    "address": r.get("address"),
                    "borough": BOROUGH_ABBR.get(boro, boro or None),
                    "zip": r.get("zipcode"),
                    "bbl": r.get("bbl"),
                    "bin": r.get("bin"),
                    "nta_code": r.get("nta_code"),
                    "census_tract": r.get("census_tract"),
                    "community_board": r.get("community_board"),
                    # exact 1:1 category mapping -- every row in this feed is
                    # NAICS 624410 child care; nothing is inferred from a name.
                    "mapping_confidence": "high",
                    # See the ACTIVE FILTER section of the module docstring:
                    # the publisher excludes preliminary / suspended / closed
                    # programs, so presence IS the active observation.
                    "active": True,
                    "active_basis": "published_active_roster",
                },
            )


# ==========================================================================
# Pending / apply — staging that does not collide with the dedup pipeline
# ==========================================================================
#
# Identical rationale to dcwp.py: `loci dedup` reads staging.poi and writes
# analysis.poi_dedup, so landing a new source directly into staging.poi while
# that runs yields a half-deduped universe the database cannot detect. The
# ingest lands in a table with the IDENTICAL schema; promotion is a separate,
# one-command, reviewable step.

PENDING_TABLE = "staging.poi_dohmh_childcare_pending"

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
                  table: str = PENDING_TABLE) -> list[POIRecord]:
    """Fetch the active childcare roster and land it in the holding table.
    Idempotent: `load` deletes this source_id's prior rows first."""
    ensure_pending_table(con, table)
    return DohmhChildcareAdapter().load(con, limit=limit, table=table)


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
