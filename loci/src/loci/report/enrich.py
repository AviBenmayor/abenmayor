"""THE PAID READ LAYER (D100, AC-17, AC-18) -- everything a report spends
money on besides the one prose call: three Tavily searches (rents, leases,
news) and on-demand closure checks for every 'unknown' POI in the catchment,
nearest first, each preceded by a `ledger.Budget.charge()`.

Closure verdicts are written through `model.poi_evidence.insert_evidence` --
THE SAME function `loci verify-closures` uses (design-closure-evidence.md
section 1: "the allocator report's on-demand checks (D100) both call this,
so a closure verdict is provenanced identically regardless of which caller
found it"). That function already landed in this session's window (it did
not need a local TODO stub, unlike the original worry in this session's
brief) -- `tests/test_report_enrich.py` imports it directly.

ORDER, per the design: the three searches first (cheap, always useful even
if the cap turns out too small for any closure checks), THEN closure checks
nearest-first. A `CapExceeded` anywhere stops the WHOLE enrichment pass
(remaining searches and remaining checks alike) rather than skipping just
the one call that failed -- once the cap is gone, the honest thing is to
stop spending, not to keep trying cheaper things.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from loci.report import evidence as ev
from loci.report.ledger import PRICES, CapExceeded

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 5


@dataclass
class Enrichment:
    rents: list = field(default_factory=list)     # list[Hit]
    leases: list = field(default_factory=list)    # list[Hit]
    news: list = field(default_factory=list)       # list[Hit]
    closure_checks: list = field(default_factory=list)  # POI ids attempted
    cap_hit: bool = False
    checks_planned: int = 0
    checks_done: int = 0
    closure_checks_disabled: bool = False


def _locality(pack) -> str:
    a = pack.address
    return (a.get("street_name") or pack.context.get("neighborhood")
            or pack.context.get("borough") or "")


def _rents_query(pack) -> str:
    return f'"{_locality(pack)}" NYC retail rent per square foot asking 2026'.strip()


def _leases_query(pack) -> str:
    return f'"{_locality(pack)}" NYC storefront for lease available'.strip()


def _news_query(pack) -> str:
    return f'"{_locality(pack)}" NYC retail news'.strip()


def _closure_query(pack, poi) -> str:
    loc = _locality(pack)
    borough = pack.context.get("borough") or ""
    return f'"{poi.name}" "{loc}" {borough} closed OR sold OR "permanently closed"'.strip()


def _search(web, budget, query: str, tag: str) -> list:
    """One Tavily search, charged before the call. Returns `[]` (and sets
    nothing on the caller's `cap_hit`) if `web` is `None` -- no web client
    configured is "no enrichment", not an error -- OR if `budget.dry_run`
    (the charge only records a plan entry; AC-20 requires the real client
    is NEVER touched on a dry run). Re-raises `CapExceeded` so the caller
    can stop the whole pass."""
    if web is None:
        return []
    budget.charge("tavily", PRICES["tavily"], detail=f"search:{tag}")
    if budget.dry_run:
        return []
    return list(web.search(query, max_results=MAX_SEARCH_RESULTS))


def _check_one(con, pack, poi, budget, places, web, now: dt.datetime) -> bool:
    """Attempt to resolve ONE unknown POI: Places first (cheaper AND usually
    conclusive), web only if Places was unavailable or inconclusive. Returns
    True iff an evidence row was WRITTEN (conclusive or not -- a stored
    inconclusive attempt still counts as "checked", so a later
    `--recheck-days` window does not immediately re-buy it). Raises
    `CapExceeded` if a charge would exceed the budget; a row already written
    before that charge stays written (see module docstring). Under
    `budget.dry_run`, every `charge()` below only plans -- the real
    `places`/`web` client is never called, and this returns `False` (no row
    written, so `enrich()`'s `checks_done` correctly stays 0 on a dry run)."""
    from loci.model.poi_evidence import EvidenceRow, insert_evidence

    wrote = False
    conclusive = False
    if places is not None:
        budget.charge("places", PRICES["places"], poi_id=poi.poi_id,
                      detail="closure_check:places")
        if budget.dry_run:
            return False
        result = places.business_status(poi.name, poi.lat, poi.lon)
        row = EvidenceRow(
            poi_id=poi.poi_id, verdict=result.verdict, source="places",
            source_name=result.source_name or "Google Places",
            url=result.url or "https://www.google.com/maps/",
            evidence_date=result.evidence_date or now.date(), dated_by=result.dated_by,
            retrieved_at=now, query="places:searchText", raw=result.raw,
            reason=result.reason)
        insert_evidence(con, row)
        wrote = True
        conclusive = row.verdict is not None

    if web is not None and not conclusive:
        from loci.evidence.web_rules import PoiContext, classify

        query = _closure_query(pack, poi)
        budget.charge("tavily", PRICES["tavily"], poi_id=poi.poi_id,
                      detail="closure_check:web")
        if budget.dry_run:
            return wrote
        hits = web.search(query, max_results=MAX_SEARCH_RESULTS)
        ctx = PoiContext(poi_id=poi.poi_id, name=poi.name, street=_locality(pack))
        best = None
        for h in hits:
            r = classify(h, ctx, query=query, retrieved_at=now)
            if r.verdict == "closed":
                best = r
                break
            best = best or r
        if best is not None:
            insert_evidence(con, best)
            wrote = True

    return wrote


def enrich(pack, budget, places, web, *, closure_checks: bool = True) -> Enrichment:
    """The paid enrichment pass for one `EvidencePack`. Mutates `pack.supply`
    in place (via `evidence.refresh_supply`) when any closure check wrote a
    row, so `render.py` sees the UPDATED statuses without re-assembling the
    whole pack.

    `closure_checks=False` (the CLI's `--no-closure-checks`) skips the
    per-POI closure pass ENTIRELY -- no Places call, no web closure-fallback
    call, no `poi_evidence` row, no `poi_status` change. `checks_planned`
    reports 0 (not `len(unknown_pois(pack))`) so a caller reading the
    `Enrichment` alone sees "nothing was planned", not "planned and skipped".
    The three general searches (rents/leases/news) are unaffected -- they are
    not closure checks and still run."""
    con = budget.con
    now = dt.datetime.now()
    rents: list = []
    leases: list = []
    news: list = []
    unknown = ev.unknown_pois(pack) if closure_checks else []
    checks_planned = len(unknown)
    checks_done = 0
    cap_hit = False
    try:
        rents = _search(web, budget, _rents_query(pack), "rents")
        leases = _search(web, budget, _leases_query(pack), "leases")
        news = _search(web, budget, _news_query(pack), "news")
        if closure_checks and (places is not None or web is not None):
            for poi in unknown:
                if _check_one(con, pack, poi, budget, places, web, now):
                    checks_done += 1
    except CapExceeded as exc:
        cap_hit = True
        logger.warning("enrich: budget cap hit for run_id=%s after %d/%d closure "
                       "checks (%s)", budget.run_id, checks_done, checks_planned, exc)

    if checks_done:
        ev.refresh_supply(pack, con)

    return Enrichment(rents=rents, leases=leases, news=news, cap_hit=cap_hit,
                      checks_planned=checks_planned, checks_done=checks_done,
                      closure_checks_disabled=not closure_checks)
