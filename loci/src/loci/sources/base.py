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

    def load(self, con, *, limit: int | None = None, dry_run: bool = False) -> list[POIRecord]:
        """fetch → normalize → replace this source's rows in staging.poi.
        Idempotent: deletes prior rows for source_id before inserting."""
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
        } for r in records])

        con.execute("DELETE FROM staging.poi WHERE source_id = ?", [self.source_id])
        if len(df):
            con.register("_stg_df", df)
            con.execute("""
                INSERT INTO staging.poi
                    (poi_id, source_id, source_record_id, category, tier, name, geom,
                     observed_on, opened_on, closed_on, confidence, attrs)
                SELECT poi_id, source_id, source_record_id, category, tier, name,
                       ST_Point(lon, lat),
                       CAST(observed_on AS DATE), CAST(opened_on AS DATE),
                       CAST(closed_on AS DATE), confidence, CAST(attrs AS JSON)
                FROM _stg_df
            """)
            con.unregister("_stg_df")
        return records
