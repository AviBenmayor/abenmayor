"""RENDER THE FOUR-HEADING MEMO (D100, AC-16). Deterministic tables built by
code under each heading; prose (one Anthropic call, `prose.py`) inserted per
section when available. `prose is None` -- no `ANTHROPIC_API_KEY` -- still
produces a complete file: every heading gets its tables plus one line
("*prose unavailable: ANTHROPIC_API_KEY unset*") instead of narrative, which
is what lets AC-16's "four headings, all non-empty" pass with no key
configured (seed constraint, this session's own instruction).

DEVIATION FROM THE DESIGN'S SLUG EXAMPLE: `design-allocator-report.md` names
"graham-ave-376" as the slug for 376 Graham Ave, but `analysis.address`
carries no house-number/full-address text column (`street_name` only, e.g.
"Graham Avenue"; `address_id` on a lot-frame row is the BBL string --
design's own fact 0). `slug()` here uses `street_name` when present, the
`address_id` otherwise, and NEVER a value only the original free-text geocode
query would know (`run.generate` takes an already-resolved `address_id`, no
label parameter, matching the design's own signature) -- so a human housenumber
does not appear in the filename unless a future caller threads one through.

-----------------------------------------------------------------------------
INVESTOR REVIEW (GTM-172, 2026-09-14/15), SIX CHANGES LANDED HERE
-----------------------------------------------------------------------------
1. The falsification sentence is rendered from `pack.forecast` in EXACTLY ONE
   place (`_section1_full`, below); `_scrub_falsification_claims` deletes any
   sentence in the PROSE text that mentions a falsification test at all -- the
   model is never allowed to affirm OR deny one, so the two can never
   disagree. `prose.py`'s outline tells the model not to try.
2. `is_below_c` gates the whole render: a lead-category grade below C (or no
   grade at all) renders `_render_no_trade` -- four short paragraphs, no POI
   table, no web signals beyond news -- instead of the full memo.
3. `_underwriting_lines` (full memo, section 3 only): catchment homes vs the
   D18 `ECON` minimum-viable-catchment table (`loci.model.invest`), rent
   ceiling as a share of modelled p50 revenue, and a downside case at p25.
   Every number in it is read off `pack`; nothing here is invented.
4. Vacant DOF storefronts, SLA-pending/DOB-fit-out filings and the chains
   watchlist are each rendered as NAMED ROWS (`_vacant_storefront_table`,
   `_pipeline_table`, `_chains_watch_table`) in sections 2/4. The raw
   POI-by-POI supply table moves to `_appendix_supply_table` -- an appendix
   after the four headings, never inside them.
5. Web hits are pre-filtered by `enrich.py` before they ever reach this
   module (geo-scope, banned domains, dated-page + unit checks) -- this
   module only renders what survived, plus (in the provenance footer) how
   many hits were rejected and why.
6. Section 4 states a planner's verdict: legality + basis, special district
   (`spdist1`, or "not loaded"), historic-district/landmark as a FIT-OUT COST
   note, the SLA 500-foot rule when the lead category is bar/restaurant, and
   the flood/environmental "not loaded" line. The same-BBL consistency check
   (`evidence._same_bbl_consistency`) surfaces in the PROVENANCE FOOTER, not
   the body -- it's a same-day cross-check for the analyst, not a claim for
   the reader.

Internal identifiers (run id, total spend, model version, supply hash) move
out of the top header into `_provenance_footer` at the very end of the
document -- the cross-cutting jargon-leak complaint from the review.
"""
from __future__ import annotations

import datetime as dt
import re

from loci.db import REPO_ROOT

OUT_DIR = REPO_ROOT / "docs" / "recommendations"

HEADINGS = (
    "## 1. Category call",
    "## 2. Supply",
    "## 3. Demand and catchment economics",
    "## 4. Legality, rents, risk and exit",
)

PROSE_UNAVAILABLE = "*prose unavailable: ANTHROPIC_API_KEY unset*"

#: Distinct from `PROSE_UNAVAILABLE` (2026-09-15 fix, GTM-183 regression): a
#: prose call DID happen -- `analysis.spend_ledger` carries an `anthropic`
#: row for it -- but this section's text could not be recovered from the
#: reply (`prose._split_sections` failed to parse it as JSON or as headinged
#: markdown). Printing `PROSE_UNAVAILABLE` in that case would be a lie (the
#: key was not unset; a call ran and was billed) -- see `_prose_note` below.
PROSE_PARSE_FAILED = "*prose could not be parsed; raw output in provenance footer*"

#: `model.recommend.GRADES = ("A", "B", "C", "D")` -- worst is D, there is no
#: F. "Below C" (investor review item 2) means D, or no grade at all.
GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
GRADE_GATE_MIN = "C"

#: A sentence containing any of these (case-insensitive substring) is never
#: allowed to survive into rendered prose -- item 1: the falsification
#: sentence is rendered from `pack.forecast` in exactly one place below, and
#: prose text is never allowed to affirm OR deny that one exists.
_FALSIFICATION_MENTION_RE = re.compile(r"falsification test", re.I)


def slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (label or "").strip().lower()).strip("-")
    return s or "address"


def _address_label(pack) -> str:
    a = pack.address
    return a.get("street_name") or a.get("bbl") or a.get("address_id") or "address"


def out_path(pack, *, today: dt.date | None = None) -> "pathlib.Path":
    today = today or dt.date.today()
    return OUT_DIR / f"{slug(_address_label(pack))}-{today.isoformat()}.md"


def _n(v, fmt="{:,.0f}", dash="—"):
    return dash if v is None else fmt.format(v)


def _pct(v, dash="—"):
    return dash if v is None else f"{v * 100:.1f}%"


def _usd(v, dash="—"):
    return dash if v is None else f"${v:,.0f}"


def _lead_grade(pack) -> str | None:
    if not pack.grades:
        return None
    g = pack.grades[0].get("overall_grade")
    return str(g).upper() if g else None


def is_below_c(pack) -> bool:
    """Investor review item 2: no grade, or a grade ranked below
    `GRADE_GATE_MIN` ("C"), routes the whole render to the one-page no-trade
    note. `prose.py` reads this too (a different outline/word budget for the
    note), so it is a public, no-argument-surprise function rather than a
    private one -- see that module's own `build_prompt`."""
    grade = _lead_grade(pack)
    if grade is None:
        return True
    return GRADE_RANK.get(grade, 0) < GRADE_RANK[GRADE_GATE_MIN]


def _split_sentences(text: str) -> list[str]:
    # Deliberately simple: split on ". " / "! " / "? " followed by a
    # capital/quote/markdown-bold marker, or on blank lines -- good enough
    # for scrubbing model-generated prose, not a general sentence tokenizer.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9*\[])|\n\s*\n", text.strip())
    return [p for p in parts if p.strip()]


def _scrub_falsification_claims(text: str | None) -> str | None:
    """Remove any sentence mentioning a falsification test at all (item 1).
    The deterministic line in `_section1_full` is the ONLY place this report
    ever states whether one exists -- a model that says "no falsification
    test is present" while `pack.forecast` carries one (or invents one that
    isn't there) can never reach the rendered file."""
    if not text:
        return text
    kept = [s for s in _split_sentences(text) if not _FALSIFICATION_MENTION_RE.search(s)]
    out = " ".join(kept).strip()
    return out or None


def _status_counts(rows) -> dict:
    out = {"open": 0, "closed": 0, "unknown": 0}
    for p in rows:
        out[p.status] = out.get(p.status, 0) + 1
    return out


def _fmt_date(v) -> str:
    if v is None:
        return "—"
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _prose_note(prose, i: int) -> str:
    """The line to print in place of section `i`'s narrative when
    `prose.get(i)` has no text: `PROSE_UNAVAILABLE` when no call was ever
    attempted (`prose` is `None`/`{}`, e.g. no client configured, or a
    dry run) -- `getattr(prose, "called", False)` is `False` in exactly that
    case, since only `prose.write_prose`'s two real-call branches build a
    `ProseSections` with `called=True`. `PROSE_PARSE_FAILED` when a call DID
    happen (`called=True`) but this section's text could not be recovered
    from the reply -- the raw reply is in the provenance footer instead
    (`_provenance_footer`), never silently treated as narrative here."""
    return PROSE_PARSE_FAILED if getattr(prose, "called", False) else PROSE_UNAVAILABLE


# --------------------------------------------------------- named-row tables

def _vacant_storefront_table(rows) -> list[str]:
    if not rows:
        return []
    lines = ["", "**Vacant storefronts on file (DOF Storefront Registry):**", "",
            "| Address | Distance (m) | Floor area (sq ft) | Last use | Vacant since |",
            "|---|---|---|---|---|"]
    for v in rows:
        area = _n(v.floor_area_sqft, dash="not on file")
        last_use = (v.last_use or "—").replace("|", "/")
        since = v.vacant_since if v.vacant_since is not None else "—"
        lines.append(f"| {v.address or '—'} | {v.dist_m:.0f} | {area} | {last_use} | {since} |")
    return lines


def _pipeline_table(rows) -> list[str]:
    if not rows:
        return []
    lines = ["", "**SLA-pending and DOB fit-out filings (in the works, D80):**", "",
            "| Business | Category | Kind | Filed | Distance (m) |",
            "|---|---|---|---|---|"]
    for p in rows:
        name = (p.business_name or "—").replace("|", "/")
        cat = p.category or "uncategorised"
        lines.append(f"| {name} | {cat} | {p.kind} | {_fmt_date(p.entry_date)} | "
                     f"{p.dist_m:.0f} |")
    return lines


def _chains_watch_table(rows) -> list[str]:
    if not rows:
        return []
    lines = ["", "**Chains watchlist within 800 m (D77, expanding brands):**", "",
            "| Chain | Category | Distance (m) | New locations (12 mo) | Total locations |",
            "|---|---|---|---|---|"]
    for c in rows:
        lines.append(f"| {c.display_name} | {c.category or '—'} | {c.dist_m:.0f} | "
                     f"{_n(c.locations_new_12m)} | {_n(c.locations_total)} |")
    return lines


def _appendix_supply_table(pack) -> str:
    """The full POI-by-POI supply table, moved out of the body (investor
    review item 4: "the raw POI table moves to an appendix"). Still no
    internal identifiers (poi_id, source_id) in the table itself -- those
    stay out of the rendered file entirely; the provenance footer carries
    only the run-level identifiers (run id, model version, supply hash), not
    a per-POI id list."""
    lines = ["## Appendix — supply detail", "",
            "Every POI the supply screen counted within the catchment, including closed "
            "and unresolved ('unknown') records. This is reference detail, not the memo's "
            "argument -- see section 2 for what it means.", "",
            "| Name | Category | Distance (m) | Status | Basis |",
            "|---|---|---|---|---|"]
    for p in pack.supply:
        name = (p.name or "—").replace("|", "/")
        basis = (p.basis or "—").replace("|", "/")
        colo = f" (co-located: {p.colocation})" if p.colocation else ""
        lines.append(f"| {name} | {p.category} | {p.dist_m:.0f} | {p.status}{colo} | {basis} |")
    if not pack.supply:
        lines.append("| — | — | — | — | — |")
    return "\n".join(lines)


def _underwriting_lines(pack) -> list[str]:
    """Investor review item 3: catchment homes vs the D18 ECON minimum for
    the lead category, rent ceiling as a share of modelled p50 revenue, a
    payback line, and a downside case at p25. Every number is read off
    `pack.demand` / `pack.lead_category` -- nothing here is invented, and
    where the pack does not carry a number this says so plainly rather than
    estimating one (the report's own rule 1, applied to itself)."""
    from loci.model.invest import ECON      # lazy: keeps h3/numpy off this module's import path

    d = pack.demand
    cat = pack.lead_category
    lines = ["", "**Underwriting**", ""]

    homes = d.get("homes_400m")
    if cat in ECON:
        min_homes, driver = ECON[cat]
        if homes is not None:
            verdict = "clears" if homes >= min_homes else "is BELOW"
            lines.append(f"- Catchment homes (400 m): {_n(homes)} vs the D18 minimum-viable "
                        f"**{min_homes:,}** for {cat} (primary driver: {driver}) — "
                        f"{verdict} the threshold.")
        else:
            lines.append(f"- D18 minimum-viable catchment for {cat}: **{min_homes:,}** homes "
                        f"(primary driver: {driver}); catchment homes are not on file for "
                        "this address.")
    else:
        lines.append(f"- No D18 minimum-viable-catchment threshold is defined for "
                    f"{cat or 'this category'} (the D18 table covers "
                    f"{', '.join(sorted(ECON))} only).")

    p50, p25, rent = d.get("revenue_p50"), d.get("revenue_p25"), d.get("rent_ceiling")
    if p50 and rent:
        ocr_p50 = (rent * 12) / p50
        lines.append(f"- Rent ceiling {_usd(rent)}/mo ({_usd(rent * 12)}/yr) is "
                    f"**{ocr_p50 * 100:.1f}%** of modelled p50 revenue ({_usd(p50)}).")
    else:
        lines.append("- Rent-to-revenue ratio: not computable (rent ceiling or p50 revenue "
                    "absent from the pack).")

    lines.append("- Payback: the pack carries no capex or fixed-cost figures, so a capital "
                "payback period cannot be computed from it; the rent-to-revenue ratio above "
                "is the only occupancy-cost read available.")

    if p25 and rent:
        ocr_p25 = (rent * 12) / p25
        lines.append(f"- Downside case at p25 revenue ({_usd(p25)}): rent ceiling would be "
                    f"**{ocr_p25 * 100:.1f}%** of revenue at that level.")
    else:
        lines.append("- Downside case: not computable (p25 revenue or rent ceiling absent "
                    "from the pack).")
    return lines


# ---------------------------------------------------------------- full memo

def _section1_full(pack, enrichment, prose_text: str | None,
                   note: str = PROSE_UNAVAILABLE) -> str:
    lines = [HEADINGS[0], ""]
    card = pack.grades[0] if pack.grades else None
    if card is None:
        lines.append("No category could be graded for this address (no supply-ratio "
                     "measurement in any of the 15 categories).")
        return "\n".join(lines)
    lines.append(f"**Lead category: {card['category_label']}** — "
                 f"overall grade **{card['overall_grade']}** ({card['verdict']}).")
    fc = pack.forecast
    if fc and fc.get("p_opening") is not None:
        issued = fc.get("issued_month")
        horizon = fc.get("horizon_months") or 12
        try:
            y, m = (int(x) for x in str(issued).split("-"))
            end = dt.date(y + (m + horizon - 1) // 12, (m + horizon - 1) % 12 + 1, 1)
            end_s = end.strftime("%Y-%m")
        except Exception:      # noqa: BLE001 -- malformed issued_month, fall back
            end_s = "the forecast horizon"
        lines.append("")
        lines.append(f"p(opening) = **{fc['p_opening']:.3f}** (issued {issued}, "
                     f"{horizon}-month horizon).")
        lines.append(f"**Falsification test:** this call is wrong if no "
                     f"{card['category_label'].lower()} is first-seen within 400 m "
                     f"by {end_s} (scored {issued}).")
    else:
        lines.append("")
        lines.append("No forecast is on file for this address x category "
                     "(nothing to falsify against yet).")
    lines.append("")
    lines.append("**Caveat:** this call reads market entry, not viability — a forecast "
                 "that a category opens here is not a prediction that it survives.")
    hole = (card.get("sections") and next(
        (s for s in card["sections"] if s.get("key") == "coverage"), None))
    if hole and hole.get("facts", {}).get("coverage_hole_rate") is not None:
        lines.append(f"Coverage-hole rate for this category: "
                     f"{_pct(hole['facts']['coverage_hole_rate'])}.")
    prose_text = _scrub_falsification_claims(prose_text)
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", note]
    return "\n".join(lines)


def _section2_full(pack, enrichment, prose_text: str | None,
                   note: str = PROSE_UNAVAILABLE) -> str:
    lines = [HEADINGS[1], ""]
    counts = _status_counts(pack.supply)
    lines.append(f"{len(pack.supply)} POI within {pack.context.get('catchment_m', 500):.0f} m "
                 f"— {counts['open']} open, {counts['closed']} closed, "
                 f"{counts['unknown']} unknown (full list in the appendix).")
    if enrichment is not None:
        if getattr(enrichment, "closure_checks_disabled", False):
            lines.append("Closure checks disabled for this run (status shown as of "
                         f"{pack.provenance.get('supply_hash')}).")
        else:
            lines.append(f"On-demand checks this run: **{enrichment.checks_done}** of "
                         f"**{enrichment.checks_planned}** unknown POIs "
                         f"({'cap hit — stopped early' if enrichment.cap_hit else 'cap not hit'}).")
    unresolved = [p for p in pack.supply if p.colocation == "unresolved"]
    if unresolved:
        lines.append(f"{len(unresolved)} unresolved co-located pair(s) at this catchment "
                     "(two POIs at one coordinate the evidence cannot yet split).")
    lines += _vacant_storefront_table(pack.vacant_storefronts)
    lines += _pipeline_table(pack.pipeline)
    if not pack.vacant_storefronts and not pack.pipeline:
        lines += ["", "No vacant DOF storefronts and no SLA-pending/DOB fit-out filings "
                 "on file within the catchment."]
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", note]
    return "\n".join(lines)


def _section3_full(pack, enrichment, prose_text: str | None,
                   note: str = PROSE_UNAVAILABLE) -> str:
    lines = [HEADINGS[2], ""]
    d = pack.demand
    lines += [
        "| Measure | Value |", "|---|---|",
        f"| Homes within 400 m | {_n(d.get('homes_400m'))} |",
        f"| Median household income ± MOE | {_usd(d.get('median_hh_income'))} "
        f"± {_usd(d.get('median_hh_income_moe'))} |",
        f"| Renter share | {_pct(d.get('renter_share'))} |",
        f"| 18–34 share | {_pct(d.get('age_18_34_share'))} |",
        f"| Transit entries within 400 m | {_n(d.get('transit_entries_400m'))} |",
        f"| Jobs within 400 m | {_n(d.get('jobs_400m'))} |",
        f"| Units permitted within 400 m | {_n(d.get('units_permitted_400m'))} |",
        f"| Units completed (24 mo) within 400 m | {_n(d.get('units_completed_24mo_400m'))} |",
        f"| Revenue p25 / p50 / p75 | {_usd(d.get('revenue_p25'))} / "
        f"{_usd(d.get('revenue_p50'))} / {_usd(d.get('revenue_p75'))} |",
        f"| Rent ceiling (monthly) | {_usd(d.get('rent_ceiling'))} |",
    ]
    if d.get("demand_caveat_text"):
        lines += ["", f"**Demand caveat:** {d['demand_caveat_text']}"]
    lines += _underwriting_lines(pack)
    if enrichment is not None and enrichment.rents:
        lines += ["", "**Web-sourced rent/lease signals:**"]
        for h in enrichment.rents[:5]:
            lines.append(f"- [{h.title or h.url}]({h.url})"
                         + (f" ({h.published})" if h.published else ""))
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", note]
    return "\n".join(lines)


def _section4_full(pack, enrichment, prose_text: str | None,
                   note: str = PROSE_UNAVAILABLE) -> str:
    lines = [HEADINGS[3], ""]
    leg = pack.legality
    lines.append(f"**Legality: {leg.get('legality') or 'unknown'}** — "
                 f"{leg.get('legality_basis') or 'no basis on file'}.")
    lines.append(f"Special district: {leg.get('spdist1') or 'not loaded'}.")
    if leg.get("histdist") or leg.get("landmark"):
        lines.append(f"Fit-out cost warning: historic district = {leg.get('histdist') or '—'}, "
                     f"individual landmark = {leg.get('landmark') or '—'} — budget for LPC "
                     "storefront review time before a build-out (label only — never a factor "
                     "in the grade or legality verdict).")
    lines.append(f"Zoning: {leg.get('zonedist1') or '—'} "
                 f"(overlays {leg.get('overlay1') or '—'} / {leg.get('overlay2') or '—'}), "
                 f"land use {leg.get('landuse') or '—'}, owner type {leg.get('ownertype') or '—'}.")
    sla = pack.provenance.get("sla_500ft")
    if sla is not None:
        if sla["triggers_hearing"]:
            lines.append(f"**SLA 500-foot rule:** {sla['n_on_premises_licenses']} active "
                         "on-premises licences within 500 ft — a new full liquor licence "
                         "application here draws a mandatory public-interest hearing.")
        else:
            lines.append(f"SLA 500-foot rule: {sla['n_on_premises_licenses']} active "
                         "on-premises licences within 500 ft — below the 3-licence hearing "
                         "trigger.")
    lines.append(pack.provenance.get("flood_environmental")
                or "flood/environmental overlays: not loaded")
    d = pack.demand
    if d.get("vacant_storefronts_400m") is not None:
        lines.append(f"Vacant storefronts within 400 m (screen count): "
                     f"{_n(d.get('vacant_storefronts_400m'))} — named list in section 2.")
    lines += _chains_watch_table(pack.chains_watch)
    if enrichment is not None and enrichment.leases:
        lines += ["", "**Web-sourced lease/availability signals:**"]
        for h in enrichment.leases[:5]:
            lines.append(f"- [{h.title or h.url}]({h.url})"
                         + (f" ({h.published})" if h.published else ""))
    if enrichment is not None and enrichment.news:
        lines += ["", "**News:**"]
        for h in enrichment.news[:5]:
            lines.append(f"- [{h.title or h.url}]({h.url})"
                         + (f" ({h.published})" if h.published else ""))
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", note]
    return "\n".join(lines)


# ------------------------------------------------------------- no-trade note

def _section1_no_trade(pack, prose_text: str | None,
                       note: str = PROSE_UNAVAILABLE) -> str:
    lines = [HEADINGS[0], ""]
    card = pack.grades[0] if pack.grades else None
    if card is None:
        lines.append("No category could be graded for this address.")
    else:
        lines.append(f"Lead category **{card['category_label']}**, overall grade "
                     f"**{card['overall_grade']}** ({card['verdict']}) — below the "
                     f"{GRADE_GATE_MIN} threshold for a full memo.")
        fc = pack.forecast
        if fc and fc.get("p_opening") is not None:
            lines.append(f" p(opening) = **{fc['p_opening']:.3f}** "
                         f"(issued {fc.get('issued_month')}).")
    prose_text = _scrub_falsification_claims(prose_text)
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", note]
    return "\n".join(lines)


def _section2_no_trade(pack, prose_text: str | None,
                       note: str = PROSE_UNAVAILABLE) -> str:
    lines = [HEADINGS[1], ""]
    counts = _status_counts(pack.supply)
    lines.append(f"{len(pack.supply)} POI within "
                 f"{pack.context.get('catchment_m', 500):.0f} m — {counts['open']} open, "
                 f"{counts['closed']} closed, {counts['unknown']} unknown. No POI table or "
                 "named pipeline in a no-trade note.")
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", note]
    return "\n".join(lines)


def _section3_no_trade(pack, prose_text: str | None,
                       note: str = PROSE_UNAVAILABLE) -> str:
    lines = [HEADINGS[2], ""]
    d = pack.demand
    lines.append(f"Homes within 400 m: {_n(d.get('homes_400m'))}. Median household income: "
                 f"{_usd(d.get('median_hh_income'))}. Full underwriting is not built for a "
                 "grade below C.")
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", note]
    return "\n".join(lines)


def _section4_no_trade(pack, enrichment, prose_text: str | None,
                       note: str = PROSE_UNAVAILABLE) -> str:
    lines = [HEADINGS[3], ""]
    leg = pack.legality
    lines.append(f"**Legality: {leg.get('legality') or 'unknown'}** — "
                 f"{leg.get('legality_basis') or 'no basis on file'}.")
    if enrichment is not None and enrichment.news:
        lines += ["", "**News:**"]
        for h in enrichment.news[:3]:
            lines.append(f"- [{h.title or h.url}]({h.url})"
                         + (f" ({h.published})" if h.published else ""))
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", note]
    return "\n".join(lines)


# --------------------------------------------------------------- provenance

def _provenance_footer(pack, enrichment, prose, *, run_id: str, total_usd: float,
                       cached_note: str | None) -> str:
    """Internal identifiers (run id, spend, model version, supply hash), the
    same-BBL consistency check, and the web quality-gate's rejected-hits list
    live HERE, at the very end of the document -- never in the reader-facing
    body (investor review's cross-cutting jargon-leak complaint, item 5's
    rejected-hits list, and item 6's same-BBL check).

    2026-09-15 fix (GTM-183 regression): when a prose call happened but its
    reply could not be parsed into any section (`prose.called and not
    prose.parsed`), the raw reply is printed HERE, once, instead of ever
    landing in the body disguised as narrative -- `_prose_note` is what
    points the reader here (`PROSE_PARSE_FAILED`)."""
    lines = ["## Provenance", "",
            f"run `{run_id}` · total spend ${total_usd:.4f} · "
            f"address `{pack.address.get('address_id')}` · "
            f"supply hash `{pack.provenance.get('supply_hash')}` · "
            f"asof {pack.provenance.get('asof')}."]
    fc = pack.forecast
    if fc and fc.get("model_version"):
        lines.append(f"Forecast model version: `{fc['model_version']}`.")
    if cached_note:
        lines.append(f"*{cached_note}*")
    if getattr(prose, "called", False) and not getattr(prose, "parsed", True):
        raw = getattr(prose, "raw_text", None)
        if raw:
            lines += ["", "**Prose call ran but its reply could not be parsed into "
                     "sections -- raw model output:**", "", "```", raw.strip(), "```"]
    conflicts = pack.provenance.get("same_bbl_conflicts") or []
    if conflicts:
        lines += ["", "**Same-BBL consistency check** (other `docs/recommendations/*.md` "
                 "files from the last 7 days mentioning this BBL):"]
        for c in conflicts:
            lines.append(f"- {c}")
    rejected = getattr(enrichment, "rejected_hits", None) or []
    if rejected:
        lines += ["", f"**Web hits rejected by the quality gate:** {len(rejected)}."]
        for r in rejected[:20]:
            lines.append(f"- {r.tag}: {r.reason} — {r.url}")
    return "\n".join(lines)


# ------------------------------------------------------------------ render

def _render_full(pack, enrichment, prose: dict, *, run_id: str, total_usd: float,
                 cached_note: str | None) -> str:
    label = _address_label(pack)
    header = [
        f"# Allocator report — {label}",
        "",
        f"Generated {dt.date.today().isoformat()} · lead category "
        f"**{pack.lead_category or '—'}** · grade **{_lead_grade(pack) or '—'}**.",
    ]
    body = [
        _section1_full(pack, enrichment, prose.get(0), _prose_note(prose, 0)),
        _section2_full(pack, enrichment, prose.get(1), _prose_note(prose, 1)),
        _section3_full(pack, enrichment, prose.get(2), _prose_note(prose, 2)),
        _section4_full(pack, enrichment, prose.get(3), _prose_note(prose, 3)),
    ]
    appendix = _appendix_supply_table(pack)
    footer = _provenance_footer(pack, enrichment, prose, run_id=run_id, total_usd=total_usd,
                                cached_note=cached_note)
    return ("\n\n".join(header) + "\n\n" + "\n\n".join(body) + "\n\n"
           + appendix + "\n\n" + footer + "\n")


def _render_no_trade(pack, enrichment, prose: dict, *, run_id: str, total_usd: float,
                     cached_note: str | None) -> str:
    label = _address_label(pack)
    header = [
        f"# Allocator report — {label}",
        "",
        f"Generated {dt.date.today().isoformat()} · lead category "
        f"**{pack.lead_category or '—'}** · grade **{_lead_grade(pack) or '—'}**.",
        "",
        f"**NO TRADE.** Grade is below {GRADE_GATE_MIN} (or ungraded) — this is a one-page "
        "note, not a full memo. No POI table, no rent/lease web signals.",
    ]
    body = [
        _section1_no_trade(pack, prose.get(0), _prose_note(prose, 0)),
        _section2_no_trade(pack, prose.get(1), _prose_note(prose, 1)),
        _section3_no_trade(pack, prose.get(2), _prose_note(prose, 2)),
        _section4_no_trade(pack, enrichment, prose.get(3), _prose_note(prose, 3)),
    ]
    footer = _provenance_footer(pack, enrichment, prose, run_id=run_id, total_usd=total_usd,
                                cached_note=cached_note)
    return "\n\n".join(header) + "\n\n" + "\n\n".join(body) + "\n\n" + footer + "\n"


def render(pack, enrichment, prose, *, run_id: str, total_usd: float,
          cached_note: str | None = None) -> str:
    """`prose` is either `None` (renders `PROSE_UNAVAILABLE` in every
    section -- no call was ever attempted) or a `dict`-like of
    `{heading_index (0-3): text}` produced by `prose.write_prose` (a
    `prose.ProseSections`, in a real run) / `prose._split_sections`.

    `prose is not None else {}`, NOT `prose or {}` (2026-09-15 fix): a
    `ProseSections` whose reply could not be parsed into ANY section is a
    legitimate, `called=True` value that happens to be an empty dict --
    `or {}` would silently discard it (dict falsiness) and lose the
    `called`/`raw_text` info `_prose_note`/`_provenance_footer` need to print
    the honest `PROSE_PARSE_FAILED` line instead of the misleading
    `PROSE_UNAVAILABLE` one.

    Dispatches on `is_below_c(pack)` (investor review item 2): a lead-category
    grade below C, or no grade at all, renders the one-page no-trade note
    (`_render_no_trade`) instead of the full four-section memo
    (`_render_full`). Both paths still produce all four `HEADINGS`,
    non-empty -- AC-16 does not distinguish the two shapes."""
    prose = prose if prose is not None else {}
    if is_below_c(pack):
        return _render_no_trade(pack, enrichment, prose, run_id=run_id,
                                total_usd=total_usd, cached_note=cached_note)
    return _render_full(pack, enrichment, prose, run_id=run_id, total_usd=total_usd,
                        cached_note=cached_note)
