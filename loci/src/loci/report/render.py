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


def _section1(pack, enrichment, prose_text: str | None) -> str:
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
        lines.append(f"p(opening) = **{fc['p_opening']:.3f}** "
                     f"(issued {issued}, model {fc.get('model_version')}, "
                     f"{horizon}-month horizon).")
        lines.append(f"**Falsification test:** this call is wrong if no "
                     f"{card['category_label'].lower()} is first-seen within 400 m "
                     f"by {end_s} (scored {issued}).")
    else:
        lines.append("")
        lines.append("No forecast is on file for this address x category "
                     "(nothing to falsify against yet).")
    lines.append("")
    lines.append("**Caveat (D88):** this call reads market entry, not viability — a "
                 "forecast that a category opens here is not a prediction that it "
                 "survives.")
    hole = (card.get("sections") and next(
        (s for s in card["sections"] if s.get("key") == "coverage"), None))
    if hole and hole.get("facts", {}).get("coverage_hole_rate") is not None:
        lines.append(f"Coverage-hole rate for this category: "
                     f"{_pct(hole['facts']['coverage_hole_rate'])}.")
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", PROSE_UNAVAILABLE]
    return "\n".join(lines)


def _status_counts(rows) -> dict:
    out = {"open": 0, "closed": 0, "unknown": 0}
    for p in rows:
        out[p.status] = out.get(p.status, 0) + 1
    return out


def _section2(pack, enrichment, prose_text: str | None) -> str:
    lines = [HEADINGS[1], ""]
    counts = _status_counts(pack.supply)
    lines.append(f"{len(pack.supply)} POI within {pack.context.get('catchment_m', 500):.0f} m "
                 f"— {counts['open']} open, {counts['closed']} closed, "
                 f"{counts['unknown']} unknown.")
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
    lines += ["", "| Name | Category | Distance (m) | Status | Basis |",
             "|---|---|---|---|---|"]
    for p in pack.supply:
        name = (p.name or "—").replace("|", "/")
        basis = (p.basis or "—").replace("|", "/")
        colo = f" (co-located: {p.colocation})" if p.colocation else ""
        lines.append(f"| {name} | {p.category} | {p.dist_m:.0f} | {p.status}{colo} | {basis} |")
    if not pack.supply:
        lines.append("| — | — | — | — | — |")
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", PROSE_UNAVAILABLE]
    return "\n".join(lines)


def _section3(pack, enrichment, prose_text: str | None) -> str:
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
    if enrichment is not None and enrichment.rents:
        lines += ["", "**Web-sourced rent/lease signals:**"]
        for h in enrichment.rents[:5]:
            lines.append(f"- [{h.title or h.url}]({h.url})"
                         + (f" ({h.published})" if h.published else ""))
    if prose_text:
        lines += ["", prose_text]
    else:
        lines += ["", PROSE_UNAVAILABLE]
    return "\n".join(lines)


def _section4(pack, enrichment, prose_text: str | None) -> str:
    lines = [HEADINGS[3], ""]
    leg = pack.legality
    lines.append(f"**Legality: {leg.get('legality') or 'unknown'}** — "
                 f"{leg.get('legality_basis') or 'no basis on file'}.")
    if leg.get("histdist") or leg.get("landmark"):
        lines.append(f"Fit-out cost warning: historic district = {leg.get('histdist') or '—'}, "
                     f"individual landmark = {leg.get('landmark') or '—'} "
                     "(label only — never a factor in the grade or legality verdict).")
    lines.append(f"Zoning: {leg.get('zonedist1') or '—'} "
                 f"(overlays {leg.get('overlay1') or '—'} / {leg.get('overlay2') or '—'}), "
                 f"land use {leg.get('landuse') or '—'}, owner type {leg.get('ownertype') or '—'}.")
    d = pack.demand
    if d.get("vacant_storefronts_400m") is not None:
        lines.append(f"Vacant storefronts within 400 m: {_n(d.get('vacant_storefronts_400m'))}.")
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
        lines += ["", PROSE_UNAVAILABLE]
    return "\n".join(lines)


def render(pack, enrichment, prose, *, run_id: str, total_usd: float,
          cached_note: str | None = None) -> str:
    """`prose` is either `None` (renders `PROSE_UNAVAILABLE` in every
    section) or a `dict` of {heading_index (0-3): text}` produced by
    `prose.write_prose` / `prose.split_sections`."""
    prose = prose or {}
    label = _address_label(pack)
    header = [
        f"# Allocator report — {label}",
        "",
        f"Generated {dt.date.today().isoformat()} · run `{run_id}` · "
        f"total spend ${total_usd:.4f} · address `{pack.address.get('address_id')}` · "
        f"lead category **{pack.lead_category or '—'}**.",
    ]
    if cached_note:
        header.append(f"*{cached_note}*")
    body = [
        _section1(pack, enrichment, prose.get(0)),
        _section2(pack, enrichment, prose.get(1)),
        _section3(pack, enrichment, prose.get(2)),
        _section4(pack, enrichment, prose.get(3)),
    ]
    return "\n\n".join(header) + "\n\n" + "\n\n".join(body) + "\n"
