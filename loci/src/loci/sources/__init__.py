"""Source adapters.

Contract: every adapter, universal or city-specific, normalizes its source into
the common `staging.poi` schema (loci/sql/002_schema.sql). Nothing downstream of
staging may reference a raw source column.

    universal/   nationally available -> works for any US city
    cities/<c>/  city-specific -> best available data, not portable

Adapters self-register by subclassing SourceAdapter. `get_adapter(source_id)`
discovers them by import, so adding a new source is one new file — no shared
registry to edit and conflict on. See CONTEXT.md §10.
"""
from __future__ import annotations

import importlib
import pkgutil

from loci.sources.base import POIRecord, SourceAdapter

__all__ = ["SourceAdapter", "POIRecord", "get_adapter", "available_adapters"]


def _load_all_modules() -> None:
    from loci.sources import universal
    from loci.sources.cities import nyc
    for pkg in (universal, nyc):
        for mod in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
            importlib.import_module(mod.name)


def _all_subclasses(cls) -> set[type]:
    out = set(cls.__subclasses__())
    for c in list(out):
        out |= _all_subclasses(c)
    return out


def available_adapters() -> dict[str, type[SourceAdapter]]:
    _load_all_modules()
    return {c.source_id: c for c in _all_subclasses(SourceAdapter) if c.source_id}


def get_adapter(source_id: str) -> SourceAdapter | None:
    cls = available_adapters().get(source_id)
    return cls() if cls else None
