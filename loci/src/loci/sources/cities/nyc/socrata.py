"""A shared Socrata reader for the filing feeds: page, retry, cache, fail loud.

Every NYC/NYS adapter in this package had its own copy of the same loop. The
filing lifecycle needs SEVEN feeds across two Socrata domains, so the loop is
factored out here rather than pasted seven more times. Existing adapters are
NOT retrofitted onto it in this pass -- rewriting a working ingest to share a
helper is a gratuitous risk.

THE THREE RULES THIS ENFORCES
-----------------------------
1. **$select and $where are server-side, always.** These datasets run to
   millions of rows; pulling them whole and filtering in pandas would be slow,
   rude to the portal, and would put a 300 MB file on disk for 60k useful rows.

2. **Exhausting the retries RAISES.** A partial fetch that returned quietly is
   the single most dangerous failure mode in this project: it looks exactly
   like a neighbourhood where nobody is opening anything. Same posture as
   dob_permits._get and dohmh.fetch.

3. **A total-zero result RAISES unless the caller says a zero is expected.**
   A `$where` clause that stops matching -- because a column was renamed, or a
   date format changed -- returns `[]` with HTTP 200. That is indistinguishable
   from "no business filed anything in New York for two years", and it must not
   be ingested as such.

RAW CACHE. Every pull is written to `data/raw/<source_id>/<dataset>_<asof>.json`
before normalisation, so a normalisation bug can be fixed without re-hitting the
portal and so the exact bytes behind a row count can be re-read later. The cache
is keyed on the request, not just the dataset: two different $where clauses
against the same dataset write two different files.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import time

import requests

#: <repo>/src/loci/sources/cities/nyc/socrata.py -> six levels up is the
#: repo root (nyc, cities, sources, loci, src, <repo>).
REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
RAW_ROOT = REPO_ROOT / "data" / "raw"

NYC_DOMAIN = "https://data.cityofnewyork.us"
NYS_DOMAIN = "https://data.ny.gov"

PAGE = 50_000
TIMEOUT = 300
RETRIES = 5


class SocrataError(RuntimeError):
    """A fetch that must not be mistaken for an empty city."""


def _headers() -> dict:
    token = os.environ.get("SOCRATA_APP_TOKEN")
    return {"X-App-Token": token} if token else {}


def columns(domain: str, dataset: str,
            session: requests.Session | None = None) -> list[str]:
    """The dataset's published field names, from /api/views/."""
    sess = session or requests.Session()
    resp = sess.get(f"{domain}/api/views/{dataset}.json",
                    headers=_headers(), timeout=TIMEOUT)
    resp.raise_for_status()
    return [c.get("fieldName") for c in resp.json().get("columns", [])]


def assert_fields(domain: str, dataset: str, required: tuple[str, ...],
                  session: requests.Session | None = None) -> None:
    """Fail before the pull if the feed no longer publishes what we read.

    A renamed column comes back as a missing key, which normalises to NULL,
    which reads downstream as 'this filing has no date' -- a confident wrong
    answer. Checking costs one request."""
    present = columns(domain, dataset, session=session)
    missing = [f for f in required if f not in present]
    if missing:
        raise SocrataError(
            f"socrata: dataset {dataset} no longer exposes {missing}. "
            f"Re-derive the column names from {domain}/api/views/{dataset}.json "
            f"before ingesting."
        )


def _get(session: requests.Session, url: str, params: dict) -> list[dict]:
    last: object = None
    for attempt in range(RETRIES):
        try:
            resp = session.get(url, params=params, headers=_headers(),
                               timeout=TIMEOUT)
            if resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                time.sleep(3 + 4 * attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:   # pragma: no cover - network
            last = exc
            time.sleep(3 + 4 * attempt)
    raise SocrataError(
        f"socrata: {url} failed after {RETRIES} attempts ({last}). Refusing to "
        f"continue -- a dropped page would read downstream as a stretch of the "
        f"city where nobody filed anything."
    )


def _cache_path(source_id: str, dataset: str, params: dict,
                asof: dt.date) -> pathlib.Path:
    sig = hashlib.sha1(
        json.dumps({k: v for k, v in sorted(params.items())},
                   sort_keys=True).encode()
    ).hexdigest()[:10]
    d = RAW_ROOT / source_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{dataset}_{asof.isoformat()}_{sig}.json"


def fetch(source_id: str, domain: str, dataset: str, *,
          select: str, where: str | None = None, order: str = ":id",
          group: str | None = None, limit: int | None = None,
          allow_empty: bool = False, asof: dt.date | None = None,
          use_cache: bool = True,
          session: requests.Session | None = None) -> list[dict]:
    """Paged Socrata read -> list of raw dicts, cached under data/raw/<source>/.

    `order` defaults to `:id`, Socrata's stable internal row id. Paging without
    a deterministic order silently repeats and skips rows; ordering on a data
    column that ties (every row of a day sharing a filing_date) does the same.
    A GROUPED query cannot order on `:id`, so pass `order` explicitly there.
    """
    asof = asof or dt.date.today()
    sess = session or requests.Session()
    url = f"{domain}/resource/{dataset}.json"

    base = {"$select": select, "$order": order}
    if where:
        base["$where"] = where
    if group:
        base["$group"] = group

    cache = _cache_path(source_id, dataset, base, asof)
    if use_cache and cache.exists():
        return json.loads(cache.read_text())

    rows: list[dict] = []
    offset = 0
    while True:
        page = PAGE if limit is None else min(PAGE, limit - len(rows))
        if page <= 0:
            break
        batch = _get(sess, url, {**base, "$limit": page, "$offset": offset})
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += len(batch)
        if limit is not None and len(rows) >= limit:
            break

    if not rows and not allow_empty:
        raise SocrataError(
            f"socrata: {dataset} returned ZERO rows for $where={where!r}. That is "
            f"not a city where nobody filed anything -- it is a renamed column, a "
            f"changed date format, or a retired dataset. Refusing to ingest a "
            f"silent zero."
        )

    cache.write_text(json.dumps(rows))
    return rows
