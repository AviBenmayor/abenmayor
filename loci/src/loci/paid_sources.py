"""Render docs/PAID-SOURCES.md from the registry's `wishlist` entries.

Same contract as `loci gen-tickets`: one definition (here, `registry.yaml`)
emits the document, the document is never hand-edited, and `loci check-sources`
asserts byte-identity against a fresh render. That is what stops the paid-source
list from drifting into a pitch deck — a price on the page is a price in the
registry, with the dated evidence sitting next to it.

The only prose held here rather than in the registry is the material that is
about the LIST, not about any one source: the gap questions each purchase
graduates, the three allocation scenarios, and the appendix of things the
2026-09-13 survey found free or defunct. Per-source facts live in the registry.

Exposed as `loci gen-paid-sources`.
"""
from __future__ import annotations

import pathlib
import textwrap

from loci import registry

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC_PATH = ROOT / "docs" / "PAID-SOURCES.md"
SURVEY_DATE = "2026-09-13"

# The nine named holes. Each carries the Loci question a purchase GRADUATES --
# not "we would have more data" but "this specific claim stops being an
# assumption". A gap with no question behind it does not belong on this list.
GAPS: list[tuple[str, str, str]] = [
    ("a", "Foot traffic", (
        "Can `transit_entries_400m` stop being card context and become a grade input, or "
        "the supply-ratio denominator? D76 / GTM-147 says no until it is validated OFF a "
        "commercial corridor, and every sidewalk count NYC publishes — all 114 DOT points "
        "— sits ON one. A measured visit count per storefront is the non-corridor "
        "validation set that does not otherwise exist.")),
    ("b", "Spend and the economics grade", (
        "D81 ships nine of fifteen categories as \"not modelled\" because nothing in the "
        "free data says what a storefront takes in. Address- or block-grain spend is what "
        "moves the economics grade off D and gives the capture-share parameter lambda its "
        "first out-of-sample test.")),
    ("c", "Rent per square foot", (
        "The feasibility gate currently reasons about rent without a rent number. A real "
        "asking-rent-per-sf series per corridor is what turns \"this gap is fillable\" from "
        "a judgement into an arithmetic one.")),
    ("d", "Openings, closings and the tenant pipeline", (
        "Two questions at once. GTM-152 / QUESTIONS T10: ten of the fifteen categories "
        "(laundry, hair, nails, childcare, clinic, fitness, bank, hardware, convenience, "
        "tailor) are structurally invisible to government filings, so the pipeline sees "
        "nothing for them. And D79's first-seen ledger is 47.7% `backfill_censored` — "
        "Google Places Insights publishes MONTHLY SNAPSHOTS BACK TO 2024-01, which would "
        "un-censor that ledger two years retrospectively rather than starting the clock "
        "today.")),
    ("e", "POI truth", (
        "CONTEXT §7.1, the threat most likely to kill the project: is the measured retail "
        "gap real, or is it a POI-coverage artifact? QUESTIONS M1. An independent supply "
        "count per category per walkshed is the direct instrument — and D11's "
        "corroborated-only supply set needs a third opinion before single-source inflation "
        "can be ruled out.")),
    ("f", "Chain expansion", (
        "The chains watchlist infers expansion pressure from press and first-seen dates. A "
        "real store-location file per brand says whether a chain is actually moving toward "
        "a corridor, which is the difference between a gap and a gap someone is already "
        "filling.")),
    ("g", "Ownership and vacancy", (
        "The DOF storefront registry is self-reported and non-filing is invisible. A "
        "BBL-keyed ownership file says WHO to call about the empty ground floor 120 m from "
        "the gap, which is the step between a screen and a deal.")),
    ("h", "Demographics beyond ACS", (
        "D12 asks for a demand control that is not income. ACS tract estimates are "
        "5-year-smoothed with large MOEs and are interpolated down to the address; "
        "block-group spend potential and behavioural segments are the independent second "
        "opinion on the residual Loci computes for itself.")),
    ("i", "Sidewalk counts", (
        "The same restricted-range problem as (a), from the supply side: DOT's 114 points "
        "were chosen for traffic engineering on busy commercial streets, so a rank "
        "correlation against them is fitted on the busy tail. Counts on quiet residential "
        "blocks are what would make the access proxy testable where it matters.")),
]

ALLOCATION: list[tuple[str, str]] = [
    ("$25k a year", (
        "Buy nothing that requires a sales call. Spend it on the four verified-price items "
        "that each close a different named gap and can be live inside a sprint: Data Axle's "
        "Business API for the ten filing-blind categories (~$8–12k/yr at MN+BK refresh "
        "depth, the single highest-value line in the list because GTM-152 is the ticket "
        "that most limits the screen's credibility); Google Places Details Pro plus the "
        "Aggregate API for POI truth and the §7.1 coverage-bias audit (~$3–5k/yr, and the "
        "Aggregate SKU is largely inside its 5,000-call free tier); Esri Business Analyst "
        "Advanced at **$5,200/yr** for block-group Consumer Spending and Retail "
        "MarketPlace, the cheapest independent second opinion on the residual Loci computes "
        "itself; and Reonomy at **$4,800/yr** for BBL-keyed ownership. Then take the free "
        "wins nobody has taken: REBNY and Cushman corridor rents, the NYC Eco-Counter feed, "
        "the BID pedestrian PDFs. That is roughly $23k and it graduates gap (d) outright, "
        "moves (e) from argument to measurement, and gives (c) a real benchmark for the "
        "first time.")),
    ("$100k a year", (
        "Add the one thing money cannot substitute for. Put $40–60k against foot traffic — "
        "Advan first (it owns the former SafeGraph Patterns business and its POI-visit "
        "schema drops cleanly into DuckDB), Placer.ai second (real government contracts run "
        "$8–27.5k/yr, but its ban on redistributing derived data must be renegotiated "
        "before a Placer number appears on a card sold to anyone). Run a $2–3k BestTime.app "
        "pilot in parallel, purely to test whether an hourly busyness curve discriminates "
        "dayparts where the transit levels demonstrably do not. Spend $20–30k on LiveXYZ, "
        "the only true NYC storefront ground truth in existence; the route in is the NYC "
        "DCP and SBS relationships it already has. Reserve $10k for CompStak Enterprise or "
        "Crexi so the rent line on the card stops resting on a single comp.")),
    ("$250k a year", (
        "The binding constraint stops being money and becomes licence terms, so budget for "
        "lawyers as a line item. Add SafeGraph Spend or Mastercard Retail Location Insights "
        "($50–120k) — address-grain and census-block-grain spend respectively — because "
        "that is what takes the economics grade off D for the nine categories D81 ships as "
        "\"not modelled\", and gives lambda its first out-of-sample test. Add Spatial.ai "
        "PersonaLive ($16–18k) for the non-income demand control D12 asks for. Fund a "
        "standing **$15–25k/yr retainer for redistribution riders** on Placer, Data Axle, "
        "Esri and whichever spend vendor wins — every one of them grants internal-use-only "
        "by default, and the whole list is worthless in a product that is sold. Keep $20k "
        "unspent against the LiveXYZ and DOT sensor conversations, which are "
        "relationship-priced and will not quote before a real meeting.")),
]

# The one line item that is not a data source. It sits outside the ranked table
# on purpose: no vendor sells it, and leaving it implicit is how a list like
# this gets bought and then cannot be used.
LICENSE_RIDER = (
    "**Redistribution riders — $15,000–$25,000/yr, legal retainer, not a data purchase.** "
    "Every commercial source in the table above grants an INTERNAL-USE-ONLY licence by "
    "default. Placer.ai explicitly prohibits reselling, redistributing or sublicensing its "
    "data *or derived data*, and prohibits training models on it. Data Axle's public T&Cs "
    "grant a non-sublicensable internal licence and need an OEM rider before a record "
    "reaches a sold product. Claritas bars distributing \"Licensed Materials or "
    "derivatives\" outright. CoStar has thirty-plus suits on record. Budget the rider "
    "alongside the subscription or the number cannot go on a card a customer sees — which "
    "is the whole point of buying it."
)

APPENDIX_FREE = [
    ("REBNY Manhattan Retail Report (First Half 2026, 16 corridors) and the separate "
     "Brooklyn Retail Report", "free PDFs, asking rent per sf, scoped exactly to the D78 "
     "MN+BK screen. Shortlisted as paid; it is not."),
    ("Cushman & Wakefield MarketBeat Manhattan Retail (Q2 2026, 12 corridors) and CBRE "
     "Manhattan Retail Figures (Q2 2026, 16-corridor blended)", "free, quarterly. Colliers "
     "and Newmark were checked and publish no NYC retail corridor report — a Newmark "
     "national $54.60/sf figure is not an NYC number."),
    ("NYC Bicycle and Pedestrian Counts (`ct66-47at` / `6up2-gnw8`)", "free Socrata API, "
     "Eco-Counter sensors at 15-minute resolution, last modified 2026-09-13. Only 4 "
     "pedestrian-capable locations, all greenway/park/bridge — but it is the only NYC "
     "source with real time-of-day resolution and Loci is not using it."),
    ("NYC BID pedestrian reports", "Grand Central Partnership publishes monthly count PDFs "
     "(verified through Feb 2026, some months broken out by location); Times Square "
     "Alliance publishes weekly and monthly counts from 27 cameras at 33 locations; "
     "Flatiron/NoMad publishes quarterly. Manhattan core only, PDF parsing required."),
    ("NYC SBS Commercial District Needs Assessments", "free per-corridor reports built from "
     "door-to-door merchant surveys and a storefront/retail-mix inventory. Real ground "
     "truth, PDF-only, corridor-by-corridor, dated."),
    ("NYC DOT Pedestrian Mobility Plan demand map", "free citywide ordinal classification of "
     "every street into five pedestrian-volume categories. Not a volume estimate, but a "
     "coarse prior for exactly the quiet blocks the 114 DOT points cannot reach."),
    ("Overture Maps / Foursquare OS Places", "already ingested. Licence confirmed: "
     "Foursquare-sourced records Apache-2.0, most others CDLA-Permissive-2.0, AllThePlaces "
     "CC0. Meta contributes the plurality (~58M of ~74M), not Foursquare."),
    ("Indeed Hiring Lab", "CC BY 4.0, the only unambiguously resale-friendly licence in the "
     "whole survey, and the coarsest grain (country/city index)."),
]

APPENDIX_DEFUNCT = [
    ("Placemeter", "acquired by NETGEAR, closed 2016-11-30 for $9.6M, folded into Arlo "
     "camera analytics. Gone."),
    ("PlanetRetail RNG", "Ascential → Flywheel Digital → sold to Omnicom (~$835M, Q1 2024). "
     "Domain no longer resolves."),
    ("Localize.city / Nestio", "Localize shut US operations August 2024 and was never a "
     "storefront vendor anyway; Nestio was absorbed into Funnel Leasing."),
    ("Near Intelligence", "Chapter 11 on 2023-12-08; assets sold and now operating as "
     "**Azira**, actively shipping in 2026. Buyable again, under a different name."),
    ("Creditntell", "merged into **RetailStat** in 2023; creditntell.com redirects. One "
     "vendor, not two options."),
    ("eSite Analytics / Buxton / Springboard", "eSite acquired by Kalibrate (2021); Buxton "
     "is now \"Audiense In-Person powered by Buxton\" and buxtonco.com redirects; "
     "Springboard was acquired by MRI Software (2022), now MRI OnLocation, with a verified "
     "£3,600/yr per external counter on UK G-Cloud."),
    ("Numina", "Brooklyn-based and the obvious NYC choice, but it never secured an NYC "
     "procurement contract and its NYC pilot data does not persist anywhere. NYC DOT's "
     "actual sensor vendor is VivaCity — registered here as `nyc_dot_vivacity_sensors`."),
    ("Replica", "the `/private-sector` page now 404s and the site brands itself for public "
     "agencies; one WA sole-source notice values a statewide subscription at $250,000. It "
     "may not sell to Loci at all."),
    ("Apple Mobility Trends / Google COVID-19 Community Mobility", "discontinued 2022-04-14 "
     "and 2022 respectively. Google Environmental Insights Explorer is alive but is a "
     "building-energy and emissions tool, not foot traffic."),
]

APPENDIX_CORRECTIONS = [
    "**SafeGraph did not shut down.** It sold the *Patterns* foot-traffic line to Advan "
    "(2023–24) and still sells Places and Spend in 2026. Spend is address/POI-grain — the "
    "finest of any spend product surveyed.",
    "**Bloomberg Second Measure is still operating**, not shut down — but it is "
    "Terminal-gated with no standalone path.",
    "**Mastercard SpendingPulse is national/state/DMA/county only.** There is no ZIP, tract "
    "or address grain and redistribution is expressly barred; it cannot do what it was "
    "shortlisted for. (Retail Location Insights, in the table above, is the block-grain "
    "product.)",
    "**Visa has no equivalent product for an outside buyer** — its three adjacent offerings "
    "are restricted to Visa's own issuer, acquirer and commercial-card clients.",
    "**Environics Analytics DemoStats is Canada-only** at its core.",
    "**Google popular-times is still not in the official Places API** in 2026, and the "
    "$200/month Maps credit is gone, replaced in March 2025 by per-SKU free-call caps.",
    "**Yelp has no ongoing free production tier** — only a 5,000-call/30-day trial — and "
    "its API documents no opening dates, closure dates or review velocity, which is what it "
    "was shortlisted for.",
    "**Placekey is not simply free** at production volume: $3,000/yr Silver, $15,000/yr "
    "Gold, $40,000/yr Enterprise above the 10k/day free tier.",
    "**Buxton, Kalibrate, SiteZeus and Tango are competing products, not data sources.** "
    "SiteZeus (relaunched as \"Atlas\", ~May 2026) is architecturally the closest analogue "
    "to what Loci does internally and is the nearest true competitor for the raise "
    "narrative.",
]

TIER_LABEL = {
    "under_1k_yr": "<$1k/yr",
    "1k_10k_yr": "$1–10k/yr",
    "10k_50k_yr": "$10–50k/yr",
    "quote_only": "quote only",
    "hardware": "hardware/compute",
}
BASIS_LABEL = {
    "verified": "verified",
    "reported": "reported",
    "quote_only": "tier floor — no price published",
}
CATEGORY_LABEL = {
    "foot_traffic": "foot traffic", "poi": "POI", "pipeline": "pipeline",
    "rent": "rent", "sidewalk": "sidewalk", "spend": "spend",
    "demographics": "demographics", "chains": "chains", "property": "property",
}


def wishlist() -> list[dict]:
    """Wishlist entries in ranked order: P1 first, then gap letter, then cost."""
    rows = [s for s in registry.load()["sources"] if s.get("status") == "wishlist"]
    return sorted(rows, key=lambda s: (s["priority"], gap_letter(s), -s["cost"]["amount"]))


def gap_letter(s: dict) -> str:
    return s["closes_gap"][1]


def _flat(text: str) -> str:
    """Collapse a folded YAML block back to one line for table cells and prose."""
    return " ".join(str(text).split())


def _one_liner(text: str, limit: int = 150, floor: int = 70) -> str:
    """Opening sentences of a note, for the table's licence column.

    Truncates rather than paraphrases: the full note is printed below, so the
    cell never has to carry the whole constraint. Takes a second sentence when
    the first is a bare verdict ("Unpublished.", "DISQUALIFIED.") — a one-word
    cell tells the reader nothing about WHY.
    """
    flat = _flat(text)
    parts = [s.strip().rstrip(".") for s in flat.split(". ")]
    out, truncated = "", True
    for i, part in enumerate(parts):
        nxt = (out + " " if out else "") + part + "."
        if out and len(nxt) > limit:
            break
        out = nxt
        if len(out) >= floor or i == len(parts) - 1:
            truncated = i < len(parts) - 1
            break
    if len(out) > limit:
        out, truncated = out[: limit - 1].rsplit(" ", 1)[0], True
    return (out.rstrip(".") + " …") if truncated else out


def price_cell(s: dict) -> str:
    amount = s["cost"]["amount"]
    basis = s["cost_basis"]
    money = f"${amount:,}/yr"
    return f"**{money}** ({BASIS_LABEL[basis]})" if basis == "verified" \
        else f"{money} ({BASIS_LABEL[basis]})"


def totals(rows: list[dict]) -> tuple[int, int, int]:
    """(booked, tier-floor, verified-only) annual totals in USD."""
    booked = sum(s["cost"]["amount"] for s in rows)
    floor = sum(registry.PRICE_TIER_FLOOR[s["price_tier"]] for s in rows)
    verified = sum(s["cost"]["amount"] for s in rows if s["cost_basis"] == "verified")
    return booked, floor, verified


def render() -> str:
    rows = wishlist()
    booked, floor, verified = totals(rows)
    by_prio = {p: [s for s in rows if s["priority"] == p] for p in ("P1", "P2", "P3")}

    md = [
        "# Loci — paid data sources to integrate post-raise",
        "",
        "**GENERATED — do not edit.** Rendered by `loci gen-paid-sources` from the "
        "`status: wishlist` entries in [`src/loci/registry.yaml`](../src/loci/registry.yaml). "
        "`loci check-sources` fails if this file differs from a fresh render, so a price "
        "here is a price in the registry with its dated evidence beside it.",
        "",
        f"Surveyed {SURVEY_DATE} against vendor pricing pages, published terms, public "
        "procurement records and 2025–2026 press. "
        f"**{len(rows)} candidates** — {len(by_prio['P1'])} P1, {len(by_prio['P2'])} P2, "
        f"{len(by_prio['P3'])} P3.",
        "",
        "**Gap letters** map to the named holes in `docs/CONTEXT.md` and "
        "`docs/CHECKPOINT.md`: "
        + " · ".join(f"({ltr}) {name}" for ltr, name, _ in GAPS) + ".",
        "",
        "**What the price column means.** `verified` is a vendor list price or a signed "
        "contract. `reported` is a third-party or derived annual figure. `tier floor` means "
        "the vendor publishes nothing and the entry books the floor of its price band — so "
        "every total below is a **lower bound**, not a forecast.",
        "",
        "| | Annual USD |",
        "|---|---|",
        f"| Whole wishlist, as booked (verified price where one exists, tier floor "
        f"otherwise) | **${booked:,}** |",
        f"| Whole wishlist, every entry at its tier floor | ${floor:,} |",
        f"| The subset with a VERIFIED price ({sum(1 for s in rows if s['cost_basis'] == 'verified')} "
        f"of {len(rows)} entries) | ${verified:,} |",
        f"| P1 only, as booked | ${totals(by_prio['P1'])[0]:,} |",
        "",
        "---",
        "",
        "## Ranked",
        "",
        "| # | Pri | Source | Category | Gap | Price tier | Price | Licence constraint | "
        "Effort | Conf. |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(rows, 1):
        md.append(
            f"| {i} | {s['priority']} | **{s['name']}** — {s['vendor']} "
            f"| {CATEGORY_LABEL[s['category']]} | {gap_letter(s)} "
            f"| {TIER_LABEL[s['price_tier']]} | {price_cell(s)} "
            f"| {_one_liner(s['license_note'])} "
            f"| {s['integration_effort']} | {s['confidence']} |"
        )

    md += ["", "---", "", "## By gap — what each purchase graduates", "",
           "P1 and P2 only. P3 items are recorded in the ranked table above and in the "
           "registry so they are not relitigated; they are not bought.", ""]
    for letter, name, question in GAPS:
        sel = [s for s in rows if gap_letter(s) == letter and s["priority"] in ("P1", "P2")]
        md += [f"### ({letter}) {name}", "",
               "\n".join(textwrap.wrap(f"**The question this graduates.** {question}",
                                       width=88)), ""]
        if not sel:
            md += ["*No P1 or P2 candidate — see the P3 rows in the ranked table.*", ""]
            continue
        for s in sel:
            md += [f"**{s['priority']} · {s['name']}** ({s['vendor']}) — {price_cell(s)}, "
                   f"{s['integration_effort']} effort, {s['confidence']} confidence",
                   "",
                   f"- *Closes:* {_flat(s['closes_gap'])}",
                   f"- *Why this rank:* {_flat(s['priority_reason'])}",
                   f"- *Grain:* {_flat(s['grain'])}",
                   f"- *NYC coverage:* {_flat(s['nyc_coverage'])}",
                   f"- *Cannot see:* {_flat(s['bias'])}",
                   f"- *Price:* {_flat(s['price_note'])}",
                   f"- *Licence:* {_flat(s['license_note'])}"]
            if s.get("notes"):
                md.append(f"- *Note:* {_flat(s['notes'])}")
            md.append("- *Evidence:* " + " · ".join(
                f"[{e['url']}]({e['url']}) ({e['date']})" for e in s["evidence"]))
            md.append("")

    md += ["---", "", "## P3 — checked and rejected, recorded so it is not relitigated", "",
           "Each of these was a plausible buy until something specific killed it. The reason "
           "is kept so a later session does not spend the survey again.", "",
           "| Source | Gap | Price | Why it is P3 |", "|---|---|---|---|"]
    for s in by_prio["P3"]:
        md.append(f"| **{s['name']}** — {s['vendor']} | {gap_letter(s)} | {price_cell(s)} "
                  f"| {_flat(s['priority_reason'])} {_one_liner(s['license_note'], limit=220)} |")
    md += ["", "---", "", "## If we had $25k / $100k / $250k a year", ""]
    for label, para in ALLOCATION:
        md += [f"**At {label}.** " + para, ""]
    md += ["### The line item that is not a data source", "", LICENSE_RIDER, ""]

    md += ["---", "", "## Appendix — not on the list, and why", "",
           "### Free, or already ours", "",
           "Shortlisted as paid, found to cost nothing. Deliberately NOT registry wishlist "
           "entries: a wishlist entry is a line item with a price, and a $0 line item "
           "vanishes from every total. Take these regardless of the raise.", ""]
    for name, why in APPENDIX_FREE:
        md.append(f"- **{name}** — {why}")
    md += ["", "### Defunct, renamed, or not what the name implies", ""]
    for name, why in APPENDIX_DEFUNCT:
        md.append(f"- **{name}** — {why}")
    md += ["", "### Corrections to assumptions worth recording", ""]
    for line in APPENDIX_CORRECTIONS:
        md.append(f"- {line}")

    md += ["", "### Free but eligibility-gated, and the one ask",
           "",
           "Registered in `registry.yaml` at `status: planned`, cost 0, because neither is "
           "a purchase:",
           "",
           "- **NYC DOT VivaCity sidewalk sensors** (`nyc_dot_vivacity_sensors`) — an ASK, "
           "not a buy. DOT piloted 20 intersections in 2023 and announced expansion to ~100 "
           "locations citywide on 2026-06-04, **explicitly including residential "
           "neighborhoods**. That roster is the non-corridor validation set gap (a) and "
           "D76 / GTM-147 need, and the route in is a data-sharing request. Buying our own "
           "is the fallback the UK G-Cloud 14 benchmark of £4,095/unit/yr prices.",
           "- **Strava Metro** (`strava_metro`) — free, and **Loci does not qualify**. "
           "Eligibility in 2026 covers public agencies, an Academic Researchers Program and "
           "trail/advocacy nonprofits; consultants get in only under contract with an "
           "agency that already has access. No path exists for a private venture-backed "
           "startup, and the terms forbid commercial exploitation of the raw data. Kept at "
           "`planned` rather than `excluded` only because it opens if Loci ever works under "
           "a DOT or MPO contract — and the activity skew (athletic and recreational trips, "
           "not errand walking) makes it the wrong behaviour for a daily-needs screen "
           "anyway.",
           ""]
    return "\n".join(md) + "\n"


def generate() -> tuple[int, int]:
    """Write docs/PAID-SOURCES.md. Returns (entries, booked annual USD)."""
    rows = wishlist()
    DOC_PATH.write_text(render())
    return len(rows), totals(rows)[0]
