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

INVESTOR REVIEW (GTM-172, 2026-09-14/15) -- two outlines, chosen by
`render.is_below_c(pack)`:
  * OUTLINE_FULL, ~700 words, for a graded-C-or-better address.
  * OUTLINE_NO_TRADE, ~250 words, four SHORT paragraphs, for a grade below C
    or no grade at all -- matches `render._render_no_trade`'s shape (no POI
    table, no web signals beyond news).
Both outlines carry three rules the old single OUTLINE did not:
  1. never state whether a falsification test exists, or quote one -- that
     line is rendered exactly once, from `pack.forecast`, by `render.py`
     itself (`render._scrub_falsification_claims` also deletes any sentence
     that tries, so this is belt-and-suspenders, not the only guard);
  2. never print an internal identifier -- run ids, spend amounts, model
     versions, supply hashes, source-provenance strings, decision-log
     citations like "(D88)" -- those belong in the report's own Provenance
     footer, which the model never sees or writes; `_jsonable` also drops
     `forecast.model_version` from the evidence JSON outright so there is
     nothing for the model to cite even if it tried;
  3. never cite a web hit that carries no `published` date.
"""
from __future__ import annotations

import json
import os
import re

from loci.report.render import GRADE_GATE_MIN, is_below_c

DEFAULT_MODEL = os.environ.get("LOCI_REPORT_MODEL", "claude-fable-5-1")
MAX_OUTPUT_TOKENS = 8000
MAX_PROSE_WORDS = 700
MAX_NO_TRADE_WORDS = 250

_SHARED_RULES = """RULES, followed exactly:
1. Cite NO number that is not present in the evidence JSON. If a figure is missing, \
say so plainly rather than estimating it.
2. Cite a web hit ONLY if its "published" field is non-null, and always carry that \
hit's URL AND its published date, inline, in markdown link form. Never cite an \
undated hit.
3. Never state whether a falsification test exists, and never quote one -- that \
line is rendered separately, from the evidence's own forecast field, above your \
text. Do not mention "falsification" at all.
4. Never print a run id, a spend amount, a model version string, a supply hash, a \
source-provenance code (e.g. "nyc_dcwp_licenses:out_of_business"), or a decision-log \
citation like "(D88)" -- write for a reader who has never seen this project's \
internal tickets or tables. Paraphrase evidence in plain English instead of quoting \
its internal fields verbatim."""

OUTLINE_FULL = f"""You are writing four short prose passages for a capital allocator's \
site-investment memo about ONE New York City address. You will be given an EVIDENCE \
JSON object containing everything you may cite -- warehouse facts, grades, a forecast, \
a supply list with open/closed/unknown status, demographic and revenue figures, a \
legality verdict, and (if present) web search hits for rents, leases and news.

{_SHARED_RULES}
5. Each of the four passages is at most {MAX_PROSE_WORDS} words TOTAL across all four \
combined -- keep each one to two or three tight paragraphs.
6. Write for a reader deciding whether to deploy capital here: state the trade, the \
risk, and (in passage 4) the exit.
7. Return ONLY a JSON object with exactly four string keys "1", "2", "3", "4" -- one \
prose passage per section below. No markdown fencing, no other keys, no preamble.

Section 1 — Category call: what category, what grade, and why. Do not discuss a \
falsification test (rule 3).
Section 2 — Supply: what is open, closed and unknown nearby, and what the on-demand \
checks this run did or did not resolve. Named vacant storefronts and pending filings \
are already rendered as tables above your text -- do not repeat them as a list, \
comment on what they mean instead.
Section 3 — Demand and catchment economics: who lives/works nearby and what the \
revenue band and underwriting numbers above your text imply for this address.
Section 4 — Legality, rents, risk and exit: the zoning/legality verdict, any \
web-sourced rent or lease evidence, the named risks, and a concrete exit read \
(lease term, sublet-ability, next tenant category)."""

OUTLINE_NO_TRADE = f"""You are writing four SHORT prose paragraphs for a one-page \
"no trade" note about ONE New York City address -- the lead category's grade is below \
{GRADE_GATE_MIN} (or ungraded), so this is NOT a full investment memo: no POI table, \
no rent or lease web signals, at most a news mention. You will be given an EVIDENCE \
JSON object containing everything you may cite.

{_SHARED_RULES}
5. Each of the four passages is at most {MAX_NO_TRADE_WORDS} words TOTAL across all \
four combined -- ONE short paragraph each, no sub-sections.
6. Write for a reader deciding whether this address is worth a second look at all -- \
the honest answer here is probably not; say why plainly.
7. Return ONLY a JSON object with exactly four string keys "1", "2", "3", "4" -- one \
short paragraph per section below. No markdown fencing, no other keys, no preamble.

Section 1 — Category call: category and grade, one sentence on why it does not clear \
the bar for a full memo.
Section 2 — Supply: one sentence on what is open/closed/unknown nearby.
Section 3 — Demand: one sentence on the catchment, no underwriting (there is none for \
a below-grade address).
Section 4 — Legality and risk: the verdict, and any news headline worth flagging."""


def _sanitized_forecast(fc: dict | None) -> dict | None:
    """Drop `model_version` before the forecast ever reaches the model --
    the cross-cutting jargon-leak complaint named `model 0.1.1+f1cb6628`
    verbatim; the cleanest fix is to never hand it over, not to rely on a
    prompt rule alone (rule 4 above still forbids it as a backstop for
    anything printed elsewhere in the JSON)."""
    if not fc:
        return fc
    return {k: v for k, v in fc.items() if k != "model_version"}


def _jsonable(pack, enrichment) -> dict:
    """The evidence JSON handed to the model. Deliberately assembled here
    (not `dataclasses.asdict(pack)`) so it stays small and stable even as
    `EvidencePack`/`Enrichment` grow fields the prose has no use for."""
    supply = [{"name": p.name, "category": p.category, "dist_m": p.dist_m,
              "status": p.status, "colocation": p.colocation}
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
        "forecast": _sanitized_forecast(pack.forecast),
        "supply": supply,
        "demand": pack.demand,
        "legality": pack.legality,
        "vacant_storefronts": [{"address": v.address, "dist_m": v.dist_m,
                                "last_use": v.last_use, "vacant_since": v.vacant_since}
                              for v in getattr(pack, "vacant_storefronts", [])],
        "pipeline": [{"business_name": p.business_name, "category": p.category,
                     "kind": p.kind, "dist_m": p.dist_m}
                    for p in getattr(pack, "pipeline", [])],
        "chains_watch": [{"display_name": c.display_name, "category": c.category,
                          "dist_m": c.dist_m, "locations_new_12m": c.locations_new_12m}
                        for c in getattr(pack, "chains_watch", [])],
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
    """(system, user) for the one prose call. Outline choice (item 2) follows
    `render.is_below_c(pack)` -- the SAME test `render.render` uses to pick
    `_render_full` vs `_render_no_trade`, so the prose asked for always
    matches the shape it will be dropped into."""
    outline = OUTLINE_NO_TRADE if is_below_c(pack) else OUTLINE_FULL
    user = json.dumps(_jsonable(pack, enrichment), sort_keys=True, default=str)
    return outline, user


#: A CLI-style reply (`clients.ClaudeCliProse`, GTM-172/183) is not
#: guaranteed to be bare JSON the way the metered API's reply is -- observed
#: to sometimes wrap the JSON object in a markdown code fence.
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.S)

#: Last-resort fallback when the model ignored the "return ONLY a JSON
#: object" instruction and answered in markdown instead: a line naming one
#: of the four sections -- "1.", "Section 2", "### 3 —", "**4)**" and
#: similar. Tolerant of the exact numbering style, not of anything fancier.
_HEADING_RE = re.compile(
    r"^\s*(?:#{1,4}\s*)?(?:\*\*)?(?:section\s*)?([1-4])(?:[.):]|\s*[-—])\s*(?:\*\*)?",
    re.I | re.M)


def _parse_json_object(text: str) -> dict | None:
    """Try, in order: `text` itself as JSON; the contents of the first
    fenced code block in `text`; the substring from the first `{` to the
    last `}` in `text` (strips a preamble sentence like "Here is the
    requested JSON:"). Returns the parsed dict from the first candidate that
    both parses and carries all four keys `"1".."4"`, else `None` -- these
    three shapes cover both the metered API (reliably bare JSON) and
    `ClaudeCliProse` (observed to fence the JSON and/or preface it with a
    sentence)."""
    candidates = [text]
    fence = _FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            doc = json.loads(candidate.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(doc, dict) and all(str(i) in doc for i in (1, 2, 3, 4)):
            return doc
    return None


def _split_by_headings(text: str) -> dict:
    """Last-resort fallback for a markdown reply (the model ignored the
    JSON-object instruction): split on lines that look like a numbered
    heading for one of the four sections. Fewer than two such headings found
    is not confidently splittable -- returns `{}` rather than guessing."""
    matches = list(_HEADING_RE.finditer(text))
    if len(matches) < 2:
        return {}
    out: dict[int, str] = {}
    for i, m in enumerate(matches):
        idx = int(m.group(1)) - 1
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            out[idx] = body
    return out


def _split_sections(text: str) -> tuple[dict, bool]:
    """Parse the model's reply into `({0: text, 1: text, 2: text, 3: text},
    parsed)` (0-indexed to match `render.render`'s `prose.get(i)` lookups).

    `parsed=False` means NOTHING usable could be recovered from `text` at
    all -- `write_prose` then keeps the raw text only for the provenance
    footer and never lets `render.py` treat it as narrative. This replaces
    the OLD fallback (`{0: text.strip()}`, dumping the whole malformed reply
    into section 0 as if it were real prose) -- that was the exact shape of
    the 2026-09-15 regression: a raw JSON-looking blob rendered as section
    1's narrative once the metered/CLI reply stopped being bare JSON.

    Two parse strategies before giving up: `_parse_json_object` (bare,
    fenced, or preamble-prefixed JSON) then `_split_by_headings` (the model
    answered in markdown instead)."""
    doc = _parse_json_object(text)
    if doc is not None:
        return {i: str(doc[str(i + 1)]) for i in range(4)}, True
    by_heading = _split_by_headings(text)
    if by_heading:
        return by_heading, True
    return {}, False


class ProseSections(dict):
    """`{0: text, 1: text, ...}` (whatever sections `_split_sections`
    recovered) plus enough about HOW it got that way for `render.py` to
    choose the right line for a missing section: `render.PROSE_UNAVAILABLE`
    ("ANTHROPIC_API_KEY unset") belongs ONLY to the case where no prose call
    was ever attempted; a call that DID happen but whose reply could not be
    parsed into a given section gets `render.PROSE_PARSE_FAILED` instead,
    with `raw_text` printed once in the provenance footer rather than risk
    landing in the body as if it were narrative.

    Subclasses `dict` so `sections == {0: "a", ...}` and `prose.get(i)`
    keep working exactly as before for every existing caller/test; `called`,
    `parsed` and `raw_text` are extra attributes plain-dict equality does
    not see."""

    def __init__(self, sections: dict | None = None, *, called: bool = False,
                parsed: bool = True, raw_text: str | None = None):
        super().__init__(sections or {})
        self.called = called
        self.parsed = parsed
        self.raw_text = raw_text


def write_prose(pack, enrichment, prose_client, budget, *,
                model: str = DEFAULT_MODEL,
                estimate_in_tokens: int = 14_000,
                estimate_out_tokens: int = 6_000) -> ProseSections:
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
            return ProseSections()
        result = prose_client.complete(system, user, model=model, max_tokens=MAX_OUTPUT_TOKENS)
        est_tokens = result.input_tokens + result.output_tokens
        budget.charge("anthropic", 0.0, detail=f"plan-billed, est {est_tokens} tokens")
        sections, parsed = _split_sections(result.text)
        return ProseSections(sections, called=True, parsed=parsed,
                             raw_text=None if parsed else result.text)

    estimate = budget.estimate_anthropic(estimate_in_tokens, estimate_out_tokens)
    budget.charge("anthropic", estimate, detail="prose")
    if budget.dry_run:
        return ProseSections()
    result = prose_client.complete(system, user, model=model, max_tokens=MAX_OUTPUT_TOKENS)
    actual = budget.estimate_anthropic(result.input_tokens, result.output_tokens)
    budget.true_up("anthropic", "prose", actual)
    sections, parsed = _split_sections(result.text)
    return ProseSections(sections, called=True, parsed=parsed,
                         raw_text=None if parsed else result.text)
