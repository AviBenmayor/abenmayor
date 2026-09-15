"""WIRE EVERYTHING TOGETHER (D100, AC-16, AC-19, AC-20) -- `generate()` is
what the CLI's `loci report` command (owned by a peer session; this module
does not touch `cli.py` itself) and the webmap's async job both call.

CACHE FIRST, THEN SPEND. `evidence.assemble()` is a pure warehouse read (no
paid call) so it always runs; its `EvidencePack.hash()` is the cache key
alongside `address_id`. A cache hit means zero paid calls and a re-written
file with a "cached from ..." footer (AC-19); a miss (or `--no-cache`) runs
the full paid pipeline: `enrich()` (Tavily + on-demand closure checks) then
`prose.write_prose()` (the one Claude call), sharing ONE `ledger.Budget` for
the whole run so the $1.00 default cap governs both.

THE PROSE RESERVATION. `enrich()` can spend the WHOLE cap on closure checks
if the reservation is not in place first -- `budget.reserve(PROSE_RESERVE_USD)`
before `enrich()` runs sets aside headroom for the one prose call regardless
of how many unknown POIs the catchment turns up; `release_reserve()` after
`enrich()` returns hands that headroom back so `write_prose`'s own charge is
checked against the REAL remaining cap, not against cap-minus-reservation-
minus-itself.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from loci.report import cache, evidence
from loci.report import enrich as enrich_mod
from loci.report import prose as prose_mod
from loci.report import render
from loci.report.ledger import PROSE_RESERVE_USD, Budget

logger = logging.getLogger(__name__)

DEFAULT_CAP_USD = 1.00


@dataclass
class ReportResult:
    path: str | None
    markdown: str
    total_usd: float
    cached: bool
    plan: list = field(default_factory=list)
    run_id: str = ""


def _new_run_id() -> str:
    return f"report-{uuid.uuid4().hex[:12]}"


def generate(con, address_id: str, *, cap_usd: float = DEFAULT_CAP_USD,
            dry_run: bool = False, no_cache: bool = False,
            out: str | Path | None = None, clients=None,
            closure_checks: bool = True) -> ReportResult:
    """Generate (or fetch from cache) the allocator report for one Loci
    `address_id`. `clients`, when given, is `(places, web, prose)` -- ALWAYS
    the injected fakes in a test; `None` calls `report.clients.default_clients()`
    for a real run.

    `closure_checks=False` (the CLI's `--no-closure-checks`) is threaded
    straight through to `enrich()`: zero Places calls, zero closure-evidence
    writes, `poi_status` untouched. The web searches for rents/leases/news
    and the one prose call are unaffected -- this flag governs the per-POI
    closure pass only."""
    pack = evidence.assemble(con, address_id)
    evidence_hash = pack.hash()
    path = Path(out) if out else render.out_path(pack)

    if not no_cache:
        cached = cache.get(address_id, evidence_hash)
        if cached is not None:
            note = f"cached from {cached.cached_at.isoformat()}"
            markdown = cached.markdown
            if note not in markdown:
                markdown = f"{cached.markdown.rstrip()}\n\n*{note}*\n"
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(markdown)
            return ReportResult(path=str(path), markdown=markdown,
                                total_usd=0.0, cached=True, plan=[],
                                run_id=cached.run_id)

    run_id = _new_run_id()
    budget = Budget(run_id=run_id, cap_usd=cap_usd, con=con, kind="report",
                    dry_run=dry_run)

    if clients is None:
        from loci.report.clients import default_clients

        places, web, prose_client = default_clients()
    else:
        places, web, prose_client = clients

    budget.reserve(PROSE_RESERVE_USD)
    enrichment = enrich_mod.enrich(pack, budget, places, web,
                                   closure_checks=closure_checks,
                                   skip_rents_leases=render.is_below_c(pack))
    budget.release_reserve(PROSE_RESERVE_USD)

    prose_sections: dict = {}
    if prose_client is not None:
        try:
            prose_sections = prose_mod.write_prose(pack, enrichment, prose_client, budget)
        except Exception as exc:      # noqa: BLE001 -- ledger.CapExceeded, or a client error
            logger.warning("prose call failed/aborted for run_id=%s: %s", run_id, exc)
            prose_sections = {}

    total_usd = budget.plan_total() if dry_run else budget.spent()
    markdown = render.render(pack, enrichment, prose_sections, run_id=run_id,
                             total_usd=total_usd)

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown)
        # Written to cache regardless of `--no-cache` (that flag only skips
        # the READ -- see cache.py's own docstring: the NEXT run should
        # still benefit from this one).
        cache.put(address_id, evidence_hash, markdown=markdown, path=str(path),
                 total_usd=total_usd, run_id=run_id)

    return ReportResult(path=(None if dry_run else str(path)), markdown=markdown,
                        total_usd=total_usd, cached=False, plan=list(budget.plan),
                        run_id=run_id)
