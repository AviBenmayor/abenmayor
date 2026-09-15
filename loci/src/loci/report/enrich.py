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

WEB-HIT QUALITY GATE (investor review item 5, GTM-172): every rents/leases/
news hit is run through `filter_hits` before it ever reaches `Enrichment` --
banned domains (Reddit, YouTube, Instagram, Facebook, TikTok, DNAinfo), tag/
archive/search-index URLs, a chamber-of-commerce homepage, and any hit whose
text never mentions the lot's own street or neighborhood (the geo-scope
check: a hit that never mentions Gowanus cannot be reporting a Court Street
comp by construction of what it DOES mention). `rents` hits additionally
require a real published date AND a dollar-per-square-foot figure with a
unit -- a price quoted with no unit ("$302.72", one of the review's own
examples) is exactly what this gate exists to catch. Rejected hits are kept
(with a reason) on `Enrichment.rejected_hits` for the report's provenance
footer -- dropped silently would make the filter unauditable.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from loci.report import evidence as ev
from loci.report.ledger import PRICES, CapExceeded

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 5

#: Domains never trusted for a rents/leases/news signal, however their
#: content reads (investor review item 5, cross-cutting complaint (b)).
BANNED_DOMAIN_FRAGMENTS: tuple[str, ...] = (
    "reddit.com", "youtube.com", "instagram.com", "facebook.com",
    "tiktok.com", "dnainfo.com",
)

#: A URL path that looks like a tag/category/archive/search index rather than
#: one article -- these rotate their listed content and will not show the
#: same figures tomorrow (the review's own complaint about the LoopNet/98
#: Graham Avenue citations).
_INDEX_URL_RE = re.compile(r"/(tag|tags|category|categories|archive|archives|search)(/|\?|$)",
                           re.I)

#: A dollar figure with an explicit per-square-foot unit -- "$302.72" alone
#: (the review's own example, "unit unstated") does not match this.
_RENT_FIGURE_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?\s*(?:/|\bper\b)\s*(?:sq\.?\s*ft\.?|square\s*foot|"
    r"square\s*feet|sf)\b", re.I)


@dataclass
class RejectedHit:
    """One web hit the quality gate refused, kept for the provenance footer
    (investor review item 5: "keep a rejected-hits list in the pack")."""
    url: str
    reason: str
    tag: str


def _is_banned_domain(domain: str | None) -> bool:
    d = (domain or "").lower()
    return any(frag in d for frag in BANNED_DOMAIN_FRAGMENTS)


def _is_index_or_archive_url(url: str) -> bool:
    return bool(_INDEX_URL_RE.search(url or ""))


def _is_chamber_homepage(url: str, domain: str | None) -> bool:
    if "chamber" not in (domain or "").lower():
        return False
    return urlparse(url or "").path.strip("/") == ""


def _mentions_locality(text: str, pack) -> bool:
    """The geo-scope check (item 5): the hit's own title/snippet must name
    the lot's own street or neighborhood. A positive requirement, not a
    denylist of other NYC corridor names -- a hit that never mentions this
    address's own locality cannot be reporting a different corridor's comp
    by construction of what it DOES mention (the review's own Gowanus/Court
    Street example)."""
    low = text.lower()
    for candidate in (pack.address.get("street_name"), pack.context.get("neighborhood")):
        if candidate and candidate.lower() in low:
            return True
    return False


def filter_hits(hits, pack, *, tag: str) -> tuple[list, list["RejectedHit"]]:
    """`(kept, rejected)` for one batch of Tavily hits. `tag` is
    "rents" | "leases" | "news" -- only "rents" hits are held to the
    dated-page + figure-with-a-unit bar (a lease listing or a news item does
    not necessarily quote a $/sq ft figure at all)."""
    kept: list = []
    rejected: list[RejectedHit] = []
    for h in hits:
        text = f"{h.title or ''} {h.snippet or ''}"
        if _is_banned_domain(h.domain):
            rejected.append(RejectedHit(h.url, "banned_domain", tag)); continue
        if _is_index_or_archive_url(h.url):
            rejected.append(RejectedHit(h.url, "index_or_archive_url", tag)); continue
        if _is_chamber_homepage(h.url, h.domain):
            rejected.append(RejectedHit(h.url, "chamber_homepage", tag)); continue
        if not _mentions_locality(text, pack):
            rejected.append(RejectedHit(h.url, "off_corridor", tag)); continue
        if tag == "rents":
            if not h.published:
                rejected.append(RejectedHit(h.url, "undated", tag)); continue
            if not _RENT_FIGURE_RE.search(text):
                rejected.append(RejectedHit(h.url, "no_rent_figure_with_unit", tag)); continue
        kept.append(h)
    return kept, rejected


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
    rejected_hits: list = field(default_factory=list)   # list[RejectedHit]


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


def enrich(pack, budget, places, web, *, closure_checks: bool = True,
          skip_rents_leases: bool = False) -> Enrichment:
    """The paid enrichment pass for one `EvidencePack`. Mutates `pack.supply`
    in place (via `evidence.refresh_supply`) when any closure check wrote a
    row, so `render.py` sees the UPDATED statuses without re-assembling the
    whole pack.

    `closure_checks=False` (the CLI's `--no-closure-checks`) skips the
    per-POI closure pass ENTIRELY -- no Places call, no web closure-fallback
    call, no `poi_evidence` row, no `poi_status` change. `checks_planned`
    reports 0 (not `len(unknown_pois(pack))`) so a caller reading the
    `Enrichment` alone sees "nothing was planned", not "planned and skipped".

    `skip_rents_leases=True` (investor review item 2, set by `run.generate`
    when `render.is_below_c(pack)` -- a below-C or ungraded address gets the
    one-page no-trade note, which carries "no web enrichment beyond news")
    skips the rents/leases Tavily searches entirely; the news search always
    runs regardless of grade. Every kept hit from all three searches has
    already passed `filter_hits` (geo-scope, banned domains, dated-page +
    unit checks) -- rejects land on `Enrichment.rejected_hits`, never
    silently dropped."""
    con = budget.con
    now = dt.datetime.now()
    rents: list = []
    leases: list = []
    news: list = []
    rejected: list = []
    unknown = ev.unknown_pois(pack) if closure_checks else []
    checks_planned = len(unknown)
    checks_done = 0
    cap_hit = False
    try:
        if not skip_rents_leases:
            rents_raw = _search(web, budget, _rents_query(pack), "rents")
            rents, rej = filter_hits(rents_raw, pack, tag="rents")
            rejected += rej
            leases_raw = _search(web, budget, _leases_query(pack), "leases")
            leases, rej = filter_hits(leases_raw, pack, tag="leases")
            rejected += rej
        news_raw = _search(web, budget, _news_query(pack), "news")
        news, rej = filter_hits(news_raw, pack, tag="news")
        rejected += rej
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
                      closure_checks_disabled=not closure_checks,
                      rejected_hits=rejected)
