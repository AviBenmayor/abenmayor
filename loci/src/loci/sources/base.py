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
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from loci.categories import CATEGORIES, tier_of


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
