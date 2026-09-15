"""THE 30-DAY REPORT CACHE (D100, AC-19). A disk cache, not a table: the
report's warehouse read is already cheap (evidence.py, no paid call); the
thing worth caching is the PAID work (`enrich.py` + `prose.py`) and the
rendered file, so a second `loci report <same address>` within 30 days makes
ZERO paid calls and returns instantly.

Keyed on `(address_id, evidence_hash)`, NOT on address_id alone -- if the
warehouse's own view of the address changes underneath (a closure verdict
lands, a forecast reissues, a grade flips), `EvidencePack.hash()` changes and
the old cache entry is simply never looked up again; it is not invalidated,
it goes stale and unread, which is the cheaper failure mode for a 30-day TTL.
`--no-cache` bypasses `get()` entirely (never even checks) and always
`put()`s a fresh entry, exactly as a `--force` flag does elsewhere in this
codebase (e.g. `loci forecast --force`, ce68d53).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib

from loci.db import REPO_ROOT

CACHE_DIR = REPO_ROOT / "data" / "interim" / "report_cache"
TTL_DAYS = 30


@dataclasses.dataclass
class CachedReport:
    address_id: str
    evidence_hash: str
    markdown: str
    path: str
    total_usd: float
    cached_at: dt.datetime
    run_id: str


def key(address_id: str, evidence_hash: str) -> str:
    """The cache filename stem. Includes both halves of the key so a stale
    file for the SAME address but a DIFFERENT evidence hash never collides
    with (or is mistaken for) the current one."""
    return f"{address_id}__{evidence_hash[:16]}"


def _path(address_id: str, evidence_hash: str) -> pathlib.Path:
    return CACHE_DIR / f"{key(address_id, evidence_hash)}.json"


def get(address_id: str, evidence_hash: str, *,
        ttl_days: int = TTL_DAYS, now: dt.datetime | None = None) -> CachedReport | None:
    """The cached entry, or `None` if there isn't one or it is older than
    `ttl_days`. Never raises on a missing/corrupt file -- a cache miss is
    always safe; only `put()` needs to succeed."""
    p = _path(address_id, evidence_hash)
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    cached_at = dt.datetime.fromisoformat(doc["cached_at"])
    now = now or dt.datetime.now()
    if (now - cached_at) > dt.timedelta(days=ttl_days):
        return None
    return CachedReport(
        address_id=doc["address_id"], evidence_hash=doc["evidence_hash"],
        markdown=doc["markdown"], path=doc["path"], total_usd=doc["total_usd"],
        cached_at=cached_at, run_id=doc["run_id"])


def put(address_id: str, evidence_hash: str, *, markdown: str, path: str,
        total_usd: float, run_id: str, now: dt.datetime | None = None) -> CachedReport:
    """Write (or overwrite) the cache entry for `(address_id, evidence_hash)`.
    Called on EVERY run that produces a fresh markdown file, including a
    `--no-cache` one -- `--no-cache` only means `get()` was skipped, not that
    the result should be un-cacheable for the NEXT run."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    now = now or dt.datetime.now()
    entry = CachedReport(address_id=address_id, evidence_hash=evidence_hash,
                         markdown=markdown, path=path, total_usd=total_usd,
                         cached_at=now, run_id=run_id)
    doc = {**dataclasses.asdict(entry), "cached_at": now.isoformat()}
    _path(address_id, evidence_hash).write_text(json.dumps(doc))
    return entry
