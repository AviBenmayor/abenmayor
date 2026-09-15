"""EXACTLY ONE CLAUDE CALL (D100, AC-21). `write_prose` charges the budget
with an ESTIMATE before the call (so a report that cannot afford even the
minimum prose call never makes it) and true-ups the ledger row's amount
after, from the real token counts the API returns — the same
estimate-before/true-up-after shape `enrich.py` uses for Places/Tavily,
except prose has only one call to true up rather than N.

The outline is FIXED (seed's Report rule: "Prose: one Claude API call against
a fixed outline") — `build_prompt` hands the model the evidence JSON and asks
for exactly four prose blocks, one per `render.HEADINGS` entry, as a JSON
object so `write_prose` can split it deterministically rather than parsing
markdown headers out of free text.
"""
from __future__ import annotations

import json
import os

DEFAULT_MODEL = os.environ.get("LOCI_REPORT_MODEL", "claude-fable-5-1")
MAX_OUTPUT_TOKENS = 8000
MAX_PROSE_WORDS = 900

OUTLINE = """You are writing four short prose passages for a capital allocator's \
site-investment memo about ONE New York City address. You will be given an EVIDENCE \
JSON object containing everything you may cite -- warehouse facts, grades, a forecast, \
a supply list with open/closed/unknown status, demographic and revenue figures, a \
legality verdict, and (if present) web search hits for rents, leases and news.

RULES, followed exactly:
1. Cite NO number that is not present in the evidence JSON. If a figure is missing, \
say so plainly rather than estimating it.
2. Every claim drawn from a web hit must carry that hit's URL, inline, in markdown \
link form.
3. Each of the four passages is at most 900 words TOTAL across all four combined \
-- keep each one to two or three tight paragraphs.
4. Write for a reader deciding whether to deploy capital here: state the trade, the \
risk, and (in passage 4) the exit.
5. Return ONLY a JSON object with exactly four string keys "1", "2", "3", "4" -- one \
prose passage per section below. No markdown fencing, no other keys, no preamble.

Section 1 — Category call: what category, what grade, and why; state the \
falsification test from the evidence verbatim if present.
Section 2 — Supply: what is open, closed and unknown nearby, and what the on-demand \
checks this run did or did not resolve.
Section 3 — Demand and catchment economics: who lives/works nearby and what the \
revenue band implies for achievable rent.
Section 4 — Legality, rents, risk and exit: the zoning/legality verdict, any \
web-sourced rent or lease evidence, the named risks, and a concrete exit read \
(lease term, sublet-ability, next tenant category)."""


def _jsonable(pack, enrichment) -> dict:
    """The evidence JSON handed to the model. Deliberately assembled here
    (not `dataclasses.asdict(pack)`) so it stays small and stable even as
    `EvidencePack`/`Enrichment` grow fields the prose has no use for."""
    supply = [{"name": p.name, "category": p.category, "dist_m": p.dist_m,
              "status": p.status, "basis": p.basis, "colocation": p.colocation}
             for p in pack.supply]

    def hit(h):
        return {"url": h.url, "title": h.title, "snippet": h.snippet, "published": h.published}

    return {
        "address_id": pack.address.get("address_id"),
        "neighborhood": pack.context.get("neighborhood"),
        "lead_category": pack.lead_category,
        "grades": [{"category": g["category"], "overall_grade": g["overall_grade"],
                    "verdict": g["verdict"], "supply_ratio_vs_base": g.get("supply_ratio_vs_base")}
                  for g in pack.grades],
        "forecast": pack.forecast,
        "supply": supply,
        "demand": pack.demand,
        "legality": pack.legality,
        "enrichment": None if enrichment is None else {
            "checks_planned": enrichment.checks_planned,
            "checks_done": enrichment.checks_done,
            "cap_hit": enrichment.cap_hit,
            "rents": [hit(h) for h in enrichment.rents],
            "leases": [hit(h) for h in enrichment.leases],
            "news": [hit(h) for h in enrichment.news],
        },
    }


def build_prompt(pack, enrichment) -> tuple[str, str]:
    """(system, user) for the one prose call."""
    user = json.dumps(_jsonable(pack, enrichment), sort_keys=True, default=str)
    return OUTLINE, user


def _split_sections(text: str) -> dict:
    """Parse the model's JSON reply into `{0: text, 1: text, 2: text, 3: text}`
    (0-indexed to match `render.render`'s `prose.get(i)` lookups). Falls back
    to putting the WHOLE reply in section 0 if the model did not return valid
    JSON with the four expected keys -- a malformed reply should still render
    SOMETHING rather than crash the report."""
    try:
        doc = json.loads(text)
        if isinstance(doc, dict) and all(str(i) in doc for i in (1, 2, 3, 4)):
            return {i: str(doc[str(i + 1)]) for i in range(4)}
    except (json.JSONDecodeError, TypeError):
        pass
    return {0: text.strip()}


def write_prose(pack, enrichment, prose_client, budget, *,
                model: str = DEFAULT_MODEL,
                estimate_in_tokens: int = 14_000,
                estimate_out_tokens: int = 6_000) -> dict:
    """Exactly ONE call to `prose_client.complete`, and exactly ONE
    `analysis.spend_ledger` row for it (AC-21): `budget.charge()` writes the
    ESTIMATE before the call (so `CapExceeded` can abort before any money
    moves, or -- under `dry_run` -- only ever appends a plan entry and the
    real client is never touched, below); `budget.true_up()` then corrects
    THAT SAME ROW to the real token counts the response reports, once they
    are known.

    Returns `{0: .., 1: .., 2: .., 3: ..}` ready for `render.render`. Under
    `dry_run`, no call is made at all and this returns `{}` -- `render`'s
    `prose.get(i)` lookups fall back to `PROSE_UNAVAILABLE` exactly as the
    no-API-key case does, which is the correct reading of "planned, not
    spent" for a dry run.

    A PLAN-BILLED client (`clients.ClaudeCliProse`, GTM-172 -- billed to the
    owner's Claude subscription via the CLI, not metered per-token) skips
    the estimate-before/true-up-after dance entirely: there is nothing to
    true up (the CLI reports no usage), and the real cost is known to be
    $0.00 against THIS ledger before the call is even made, so `charge()` is
    called once, after the call, with the real (zero) amount -- still
    exactly one `analysis.spend_ledger` row (AC-21). PROVIDER stays
    `"anthropic"` (the DB CHECK constraint on that column does not admit a
    `"claude_cli"` value yet -- see `ledger.PROSE_RESERVE_USD`'s docstring);
    `detail` is what actually marks the row plan-billed, e.g. "plan-billed,
    est 1234 tokens".
    """
    system, user = build_prompt(pack, enrichment)

    if getattr(prose_client, "plan_billed", False):
        if budget.dry_run:
            budget.charge("anthropic", 0.0, detail="prose (plan-billed)")
            return {}
        result = prose_client.complete(system, user, model=model, max_tokens=MAX_OUTPUT_TOKENS)
        est_tokens = result.input_tokens + result.output_tokens
        budget.charge("anthropic", 0.0, detail=f"plan-billed, est {est_tokens} tokens")
        return _split_sections(result.text)

    estimate = budget.estimate_anthropic(estimate_in_tokens, estimate_out_tokens)
    budget.charge("anthropic", estimate, detail="prose")
    if budget.dry_run:
        return {}
    result = prose_client.complete(system, user, model=model, max_tokens=MAX_OUTPUT_TOKENS)
    actual = budget.estimate_anthropic(result.input_tokens, result.output_tokens)
    budget.true_up("anthropic", "prose", actual)
    return _split_sections(result.text)
