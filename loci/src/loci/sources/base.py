"""The source-adapter contract.

Every source — universal or city-specific — subclasses SourceAdapter and
normalizes its raw records into the common staging.poi schema
(loci/sql/002_schema.sql). Nothing downstream of staging ever sees a raw source
column. See CONTEXT.md §10.

The DOHMH adapter (the anchor source, GTM-17) is the reference implementation.
Clone its shape; do not re-invent the contract.
"""
from __future__ import annotations

import abc
import datetime as dt
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from loci.categories import CATEGORIES, tier_of

#: The bathhouse_sauna NAME-TERM RULE (GTM-198/199, 2026-09-17). Real NYC
#: bathhouses are tagged as generic spas by Overture (`spas`/`health_spa`/
#: `day_spa`) and Foursquare ("Spa"), the population `nails_beauty` carries, so
#: the narrow definition can only be applied inside those sub-tags by name.
#: The pattern is PINNED in src/loci/categories.yaml (`name_terms`, drift-
#: tested by tests/test_bathhouse_name_terms.py) and applied ONLY to the
#: sub-tags listed there (`name_terms_apply_to`); outside them "bath" is a
#: shop and "sauna" a gym room. It is a FLOOR: brand names with no bathing
#: word (QC NY, The Altar, cityWell, The Spa Club) need the hand list.
BATHHOUSE_NAME_TERMS = '(?i)\\b(bath ?house|baths?\\b(?!\\s*(?:&|and)\\s*body)|bathing|banya|sauna|jjimjilbang|hammam|onsen|schvitz|shvitz|spa castle|world spa|othership|qc ny|mermaid spa|juvenex|great jones spa|fountain of youth)'
BATHHOUSE_NAME_RE = re.compile(BATHHOUSE_NAME_TERMS)
#: What the definition does NOT count even when the include terms match:
#: private-suite / infrared sauna studios (Perspire, HigherDOSE, beem, Akari,
#: Kove -- "listed, NOT counted", GTM-199 web note §1c), gym and residential
#: sauna rooms, massage-only, and the "Bath & Body" retail false positive.
#: Applied to every name-term hit AND to the native sauna/onsen/"Bath House"
#: tags, so a HigherDOSE tagged `sauna` is excluded the same way a HigherDOSE
#: tagged `spas` is. Flagged venues live in the hand list, not in supply.
BATHHOUSE_NAME_EXCLUDE = '(?i)(infrared|light sauna|sauna studio|sauna lounge|sauna suites?|perspire|higherdose|beem\\b|sw3at|akari|kove\\b|nlighten|n°lighten|mobile sauna|sauna barrels|bath co\\b|bath (?:&|and) body|bathing area|remodel|contractor|construction|east side club|equinox|crunch|gym|fitness|condominium|condo\\b|tower|residence|apartments?|massage)'
BATHHOUSE_NAME_EXCLUDE_RE = re.compile(BATHHOUSE_NAME_EXCLUDE)
#: Native sub-tags the include rule may be applied to, per source.
BATHHOUSE_NAME_SUBTAGS: dict[str, frozenset[str]] = {
    "overture": frozenset({"spas", "health_spa", "day_spa"}),
    "foursquare": frozenset({"spa"}),
}


def bathhouse_name_excluded(name: str | None) -> bool:
    """True when the NAME marks a venue the definition does not count."""
    return bool(name) and BATHHOUSE_NAME_EXCLUDE_RE.search(name) is not None


def bathhouse_by_name(source: str, subtag: str | None, name: str | None) -> bool:
    """True when a spa-sub-tagged record's NAME says it is a bathhouse (and
    is not on the exclusion list)."""
    if not name or subtag not in BATHHOUSE_NAME_SUBTAGS.get(source, ()):
        return False
    return BATHHOUSE_NAME_RE.search(name) is not None and not bathhouse_name_excluded(name)


@dataclass
class POIRecord:
    """One normalized point of interest. tier is derived from category."""
    source_id: str
    source_record_id: str | None
    category: str
    name: str | None
    lon: float
    lat: float
    observed_on: dt.date | None = None
    opened_on: dt.date | None = None
    closed_on: dt.date | None = None
    confidence: float | None = None
    attrs: dict = field(default_factory=dict)
    # --- IDENTITY AND STATUS AS COLUMNS (2026-09-16, sql/043) --------------
    # These three were already carried in `attrs` by the adapters that have
    # them. They are promoted to COLUMNS because a JSON key is not a join key:
    # the licence->POI rung of analysis.licence_interval_poi has to match a
    # licence number against a POI, and `json_extract_string(attrs, ...)` in a
    # join predicate is both unindexable and invisible to anyone reading the
    # schema. attrs KEEPS them too -- model/poi_presence.poi_is_open reads
    # attrs and its rule is deliberately unchanged by this promotion.
    #
    # `license_status` is the PUBLISHER'S OWN STATUS STRING, verbatim, never a
    # Loci verdict. 'Active' is not a synonym for open (a roster snapshot can
    # be months stale) and 'Expired' is not a synonym for closed (a laundromat
    # outlives its licence). The verdict is poi_is_open's, and it reads
    # attrs.active / attrs.active_basis / the expiry, exactly as before.
    license_status: str | None = None
    licence_number: str | None = None
    business_unique_id: str | None = None

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}")

    @property
    def tier(self) -> int:
        return tier_of(self.category)

    @property
    def poi_id(self) -> str:
        return f"{self.source_id}:{self.source_record_id}"


class SourceAdapter(abc.ABC):
    """Base class. Subclasses set `source_id` (matching registry.yaml) and
    implement fetch() + normalize(). load() is shared and idempotent."""

    source_id: str = ""

    @abc.abstractmethod
    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        """Yield raw source records (dicts), untransformed."""

    @abc.abstractmethod
    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        """Map raw records onto POIRecords. Drop what doesn't belong."""

    def load(self, con, *, limit: int | None = None, dry_run: bool = False,
             table: str = "staging.poi") -> list[POIRecord]:
        """fetch → normalize → replace this source's rows in `table`.
        Idempotent: deletes prior rows for source_id before inserting.

        `table` exists so an adapter can be staged into a holding table with
        the identical schema (e.g. staging.poi_dcwp_pending) and promoted in a
        separate, reviewable step, instead of writing into staging.poi while
        the dedup pipeline is reading it. It is a code-supplied identifier,
        never user input."""
        records = list(self.normalize(self.fetch(limit=limit)))
        if dry_run:
            return records

        import pandas as pd

        df = pd.DataFrame([{
            "poi_id": r.poi_id, "source_id": r.source_id,
            "source_record_id": r.source_record_id, "category": r.category,
            "tier": r.tier, "name": r.name, "lon": r.lon, "lat": r.lat,
            "observed_on": r.observed_on.isoformat() if r.observed_on else None,
            "opened_on": r.opened_on.isoformat() if r.opened_on else None,
            "closed_on": r.closed_on.isoformat() if r.closed_on else None,
            "confidence": r.confidence, "attrs": json.dumps(r.attrs or {}),
            "license_status": r.license_status,
            "licence_number": r.licence_number,
            "business_unique_id": r.business_unique_id,
        } for r in records])

        con.execute(f"DELETE FROM {table} WHERE source_id = ?", [self.source_id])
        if len(df):
            con.register("_stg_df", df)
            con.execute(f"""
                INSERT INTO {table}
                    (poi_id, source_id, source_record_id, category, tier, name, geom,
                     observed_on, opened_on, closed_on, confidence, attrs,
                     license_status, licence_number, business_unique_id)
                SELECT poi_id, source_id, source_record_id, category, tier, name,
                       ST_Point(lon, lat),
                       CAST(observed_on AS DATE), CAST(opened_on AS DATE),
                       CAST(closed_on AS DATE), confidence, CAST(attrs AS JSON),
                       license_status, licence_number, business_unique_id
                FROM _stg_df
            """)
            con.unregister("_stg_df")
        return records
