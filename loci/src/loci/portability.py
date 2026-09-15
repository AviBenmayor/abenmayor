"""Render docs/PORTABILITY.md — what a second city has to publish before Loci runs.

Owner ask, 2026-09-14: *"would love to learn what are the critical inputs
necessary to be able to expand the model to new cities."*

Same contract as `loci gen-paid-sources` and `loci gen-tickets`: one definition
emits the document, the document is never hand-edited, and `loci check-sources`
asserts byte-identity against a fresh render. The reason it matters more here
than anywhere else: a readiness matrix that can be hand-edited is a readiness
matrix that *will* be hand-edited into optimism, and "we could just do Chicago
next" is precisely the claim nobody wants to have to re-derive under pressure.

WHAT IS DERIVED AND WHAT IS ASSERTED
---------------------------------------------------------------------------
Derived from `registry.yaml` (so it cannot drift): every source's portability
class, the stages it feeds, and what each stage degrades to without it.

Derived from `model/recommend_grades.yaml` (so it cannot drift either): which
card sections are load-bearing, and what verdict each grade produces. The
minimum-input-set arithmetic below is a MINIMUM OVER THE LOAD-BEARING SECTIONS,
exactly as `recommend.py` computes a verdict — so if the grade config changes,
this document's answer changes with it.

Asserted here, with a date: SECTION_INPUTS (which sources each card section
needs to reach each grade) and CITY_PROBE (the second-city portal survey).
Those are judgements about the world, not facts in the registry, so they are
held in one place with the evidence beside them.

Exposed as `loci gen-portability`.
"""
from __future__ import annotations

import pathlib
import textwrap

import yaml

from loci import registry

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC_PATH = ROOT / "docs" / "PORTABILITY.md"
GRADES_PATH = pathlib.Path(__file__).resolve().parent / "model" / "recommend_grades.yaml"

PROBE_DATE = "2026-09-14"

#: Grade order, best first. `_at_least` compares against this.
GRADE_ORDER = ("A", "B", "C", "D")

CLASS_LABEL = {
    "universal": "universal",
    "national": "national (US federal)",
    "state": "state",
    "city_open_data": "city open data (different schema)",
    "city_unique": "city-unique (no equivalent exists)",
}
#: How hard each class is to obtain in a new city. Drives the ordering in the
#: per-stage tables: the portable rows first, the unportable ones last, because
#: the last rows are the ones that cost a second city real work.
CLASS_ORDER = ("universal", "national", "state", "city_open_data", "city_unique")

STAGE_BLURB = {
    "universe": "The sampling frame. `analysis.address` is *PLUTO lots where UnitsRes > 0*, "
                "plus the D84 street-midpoint frame. Nothing downstream exists without it.",
    "walk_graph": "The OSM walk network. Every distance in Loci — the 800 m category "
                  "threshold, every 400 m catchment, the measured 1.233 circuity behind "
                  "D53's validation radius — is a network distance on this graph.",
    "poi_supply": "`staging.poi` → dedup → the D52/D59 principled supply set. The count "
                  "the whole screen is about.",
    "demand": "Who is here and who is arriving: ACS, LODES jobs, PLUTO units, and the "
              "residential development pipeline.",
    "lifecycle": "The D80 storefront filing stages — liquor application, fit-out filing, "
                 "licence application, first inspection — rolled up per address.",
    "ledger": "`analysis.poi_presence` (D79): the month Loci first and last SAW each "
              "storefront, independent of whether any source publishes an open date.",
    "character": "D82 — retail vs corporate vs industrial vs residential, as an upper "
                 "envelope of three witnesses (PLUTO floor area, jobs, POI mix).",
    "transit": "Stations, entrances and ridership. D76's `transit_entries_400m` is the "
               "only foot-traffic proxy in the free registry.",
    "validation": "Is the measured gap real or a coverage artefact (CONTEXT §7.1)? "
                  "Google ground truth, ZBP establishment counts, DOT sidewalk counts, "
                  "the D88 retrodiction.",
    "chains": "The D77 growing-chain watchlist — whether somebody is already moving "
              "toward the gap.",
}

# ---------------------------------------------------------------------------
# WHAT EACH CARD SECTION NEEDS TO REACH EACH GRADE
#
# Read `model/recommend_grades.yaml` next to this. Each section lists the grade
# CEILING a given set of inputs buys — the best that section can reach anywhere
# in the city with those inputs in hand. Whether a particular address reaches
# the ceiling is a data question; whether the city can reach it at all is this
# question, and it is the one a second-city decision turns on.
#
# `sources` are registry ids. `also` are requirements that are not registry
# rows (a fitted model, a paid comps feed) and are printed verbatim.
# ---------------------------------------------------------------------------
SECTION_INPUTS: dict[str, list[dict]] = {
    "arriving_homes": [
        {"grade": "B",
         "sources": ["nyc_dcp_housing_db", "nyc_dob_permit_issuance",
                     "nyc_dob_certificates_of_occupancy"],
         "why": "A permit file carrying NET UNITS *and* a renewal-or-status date. The "
                "renewal date is the load-bearing column, not the issue date: "
                "`active_share` is the share of permitted units whose permit was "
                "renewed, and a feed that publishes issuance only cannot compute it."},
        {"grade": "D",
         "sources": [],
         "why": "`null_grade: D` — no permit evidence at all is not \"no news\". Because "
                "the section is load-bearing, a city with no usable permit file "
                "produces a card that reads *do not act on this data* everywhere, no "
                "matter how good the rest of the inputs are."},
    ],
    "supply_thinness": [
        {"grade": "A",
         "sources": ["nyc_pluto", "nyc_cscl", "osm_walk_network", "overture_places",
                     "foursquare_os_places", "osm_overpass"],
         "why": "`n_addresses_a: 200` — a parcel universe, a walk graph and a deduped "
                "POI set, with a baseline fitted on the SAME supply hash. This is the "
                "floor of the whole system: without these four there is no ratio, no "
                "card, and nothing to grade."},
    ],
    "addressable_demand": [
        {"grade": "A",
         "sources": ["nyc_pluto", "nyc_ll84_benchmarking", "streeteasy_listings"],
         "why": "`evidence_coverage_a: 0.50` — a per-building evidence source for the "
                "category's haircut, covering more than half the buildings in the box. "
                "Today only laundry has a haircut at all."},
        {"grade": "B",
         "sources": ["nyc_pluto"],
         "why": "`prior_grade: B` — a haircut built on priors rather than evidence. "
                "Still only laundry."},
        {"grade": "C",
         "sources": ["nyc_pluto"],
         "why": "`no_haircut_grade: C` — raw `homes_400m`, unadjusted. **This is the "
                "default for fourteen of the fifteen categories, in NYC as much as "
                "anywhere**, so the verdict is already capped at *diligence* before a "
                "single portability question is asked."},
    ],
    "economics": [
        {"grade": "A", "sources": [], "paid": True,
         "also": ["≥5 same-category business-sale comps at neighbourhood grain, WITH "
                  "cash flow"],
         "why": "`a_level: neighborhood` + `n_comps_min: 5` + cash flow. No free source "
                "publishes this in any city."},
        {"grade": "B", "sources": [], "paid": True,
         "also": ["≥5 same-category business-sale comps at borough grain, WITH cash flow"],
         "why": "`b_level: borough`. Also paid-only — BizBuySell-class listings. The "
                "collection 403'd, which is why every NYC card grades D here today."},
        {"grade": "C", "sources": [],
         "also": ["a SHIPPED, GATED site-revenue calibration for the category "
                  "(BLS CEX spend pool × fitted capture share, leakage anchored to "
                  "Census CBP, capacity ceiling from parcel retail floor area)"],
         "why": "`modelled_grade: C` (D76/D81/D91). The *inputs* are national and "
                "therefore fully portable — but the calibration has to be REFITTED per "
                "city and must pass its own leave-one-ZIP-out backtest. Today exactly "
                "one category (restaurant) passes, in NYC."},
        {"grade": "D", "sources": [],
         "why": "`no_cash_flow_grade: D` — nothing. Where the card sits in New York "
                "today for fourteen of the fifteen categories."},
    ],
    "coverage": [
        {"grade": "A", "sources": ["google_places"],
         "why": "`validated_grade: A` — live ground-truth rows for the box. The API is "
                "global, so this rung is the same price in every city."},
        {"grade": "B",
         "sources": ["nyc_dohmh_restaurants", "usda_snap_retailers",
                     "nys_sla_liquor_licenses", "nyc_dcwp_inspections",
                     "nyc_dohmh_childcare", "nys_medicaid_pharmacies",
                     "nys_dos_appearance_enhancement"],
         "why": "`anchored_grade: B` — at least one QUALIFYING registry anchor for the "
                "category (D52). Any one of these buys B for the categories it anchors; "
                "the list is per-category, not all-or-nothing."},
        {"grade": "C",
         "sources": ["overture_places", "foursquare_os_places", "osm_overpass"],
         "why": "`unanchored_grade: C` — aggregators only. Always reachable, and always "
                "the rung where CONTEXT §7.1 (the immigrant-neighbourhood undercount) "
                "is doing damage nobody has measured."},
    ],
    # Context sections. Their grade can never block or unblock a verdict, so
    # they are not part of the minimum-input-set arithmetic — but a second city
    # still has to decide whether to build them.
    "demand_now": [
        {"grade": "A", "sources": ["acs_5yr", "nyc_pluto"],
         "why": "`moe_share_max: 0.20` — ACS 5-year income with a margin of error under "
                "a fifth of the estimate, plus parcel units. Fully national."},
    ],
    "space": [
        {"grade": "B", "sources": ["nyc_dof_storefront_registry"],
         "why": "`base_grade: B` — a storefront registry. `no_registry_grade: D`, and "
                "**no second city has one**: Local Law 157 of 2019 has no counterpart "
                "anywhere in the United States."},
    ],
}

# ---------------------------------------------------------------------------
# WHAT A NEW CITY MUST PUBLISH
#
# The generic name of each input, the NYC source that plays the role (dataset
# ids are pulled from the registry, so they cannot drift), and whether the
# input is in the MINIMUM set or is an enrichment.
# ---------------------------------------------------------------------------
REQUIREMENTS: list[dict] = [
    {"generic": "Parcel file with residential units AND floor area",
     "nyc": ["nyc_pluto"], "tier": "minimum",
     "note": "One row per lot, citywide, carrying: residential unit count (the universe "
             "and the dasymetric ancillary), building/retail/office floor area (D82 "
             "character, D91 capacity ceiling), zoning or FAR (the CONTEXT §1.3 "
             "commercial-capacity control), and a use or building class. In most US "
             "metros this is a COUNTY ASSESSOR file and the zoning half lives "
             "separately — budget for a two- or three-file join, and check that units "
             "are a real count and not a category code."},
    {"generic": "Street centrelines, or OSM ways as the fallback",
     "nyc": ["nyc_cscl"], "tier": "minimum",
     "note": "The D84 second sampling frame: street midpoints, so a commercial corridor "
             "with no housing above it is still sampled. OSM substitutes, weakly — the "
             "keep rule leans on status and paper-street flags OSM does not carry."},
    {"generic": "Walk network graph",
     "nyc": ["osm_walk_network"], "tier": "minimum",
     "note": "Universal and free. The single most portable load-bearing input Loci has."},
    {"generic": "POI base layers (at least two, independent)",
     "nyc": ["overture_places", "foursquare_os_places", "osm_overpass"], "tier": "minimum",
     "note": "Two is the minimum, not a nicety: D11's corroborated-only supply set is "
             "what keeps single-source inflation out of the count."},
    {"generic": "Census demographics, jobs and establishment counts",
     "nyc": ["acs_5yr", "lodes_wac", "census_zbp"], "tier": "minimum",
     "note": "National and identical in every US city. Carries its own portable bias: "
             "LODES is 2020 blocks for all years and pre-2020 is area-retro-allocated."},
    {"generic": "Building permits with job type, address and a renewal-or-status date",
     "nyc": ["nyc_dob_permit_issuance", "nyc_dob_now_job_filings"], "tier": "minimum",
     "note": "**The most commonly missing minimum input.** Many portals publish permit "
             "ISSUANCE only. Without a renewal or status date there is no active/lapsed/"
             "stalled split, `arriving_homes` falls to its null grade D, and — because "
             "that section is load-bearing — every card in the city reads *do not act*."},
    {"generic": "Residential development pipeline with NET units",
     "nyc": ["nyc_dcp_housing_db", "nyc_dob_certificates_of_occupancy"], "tier": "minimum",
     "note": "NYC's DCP file is already QA'd, geocoded and net-unit-recoded. Elsewhere "
             "the net-unit recode has to be rebuilt from raw permits, which is exactly "
             "where unit double-counting enters."},
    {"generic": "Food-service inspections with establishment NAMES",
     "nyc": ["nyc_dohmh_restaurants"], "tier": "anchor",
     "note": "The near-census that anchors restaurant, café and bar — three of fifteen "
             "categories and the whole T3 tier. Widely published, schema always "
             "different. Check it carries coordinates and not just an address string."},
    {"generic": "Business licences with issue dates",
     "nyc": ["nyc_dcwp_licenses", "nyc_dcwp_inspections", "nyc_dcwp_license_applications"],
     "tier": "anchor",
     "note": "Two different jobs: the issued roster is a supply anchor for whatever "
             "trades the city licenses (laundry is the one that matters — no aggregator "
             "sees laundromats), and the APPLICATIONS feed is the lifecycle lead time. "
             "The applications half is the rarer one."},
    {"generic": "Liquor licences (state), active and inactive",
     "nyc": ["nys_sla_liquor_licenses", "nyc_sla_pending_licenses"], "tier": "anchor",
     "note": "Every state has an ABC authority; far fewer publish a georeferenced active "
             "file, fewer still the inactive companion that makes closures recoverable, "
             "and fewest of all the PENDING queue that is the earliest go-live signal."},
    {"generic": "Cosmetology / salon roster (state)",
     "nyc": ["nys_dos_appearance_enhancement"], "tier": "anchor",
     "note": "Anchors hair and nail — the two categories where the §7.1 undercount is "
             "worst. Active-only almost everywhere, so survivorship-biased by "
             "construction: snapshot enrichment, never a panel."},
    {"generic": "Childcare roster (state in most places, city in NYC)",
     "nyc": ["nyc_dohmh_childcare"], "tier": "anchor",
     "note": "D65: without it, aggregator blind spots read as deserts. Home-based family "
             "day care is missing from every roster Loci has found, so the anchor is a "
             "supply FLOOR wherever it is built."},
    {"generic": "Pharmacy roster",
     "nyc": ["nys_medicaid_pharmacies"], "tier": "anchor",
     "note": "**The least portable anchor.** The NYC route works only because New "
             "York's NYRx carve-out routes every Medicaid member's pharmacy benefit "
             "through fee-for-service; in a managed-care state the same file is a "
             "fraction of the pharmacies. Expect to find a state Board of Pharmacy "
             "register instead, and expect it to have no bulk export."},
    {"generic": "SNAP retailer locator (national)",
     "nyc": ["usda_snap_retailers"], "tier": "anchor",
     "note": "Free, national, and the anchor for the two tier-1 weight-0.40 categories. "
             "Nothing to procure — it works in every US city on day one."},
    {"generic": "GTFS, plus ridership by station or stop",
     "nyc": ["mta_subway_stations", "mta_subway_entrances", "mta_subway_ridership_2025",
             "mta_bus_gtfs"], "tier": "enrichment",
     "note": "GTFS itself is universal. RIDERSHIP at station grain is not — NTD "
             "publishes annual system and route totals that cannot be assigned to a "
             "station. Without it, transit is presence, not quality. Entrance geometry "
             "(`pathways.txt`) is patchy outside NYC and its absence costs up to a "
             "400 m walk of error at a large complex."},
    {"generic": "Pedestrian counts",
     "nyc": ["nyc_dot_pedestrian_counts", "nyc_dot_traffic_cameras",
             "nyc_dot_vivacity_sensors"], "tier": "enrichment",
     "note": "Validation only — never an input to a score. Every city that publishes "
             "counts inherits the same restricted-range problem: the points were sited "
             "for traffic engineering on busy commercial corridors, which is not where "
             "the access proxy needs testing."},
    {"generic": "Energy benchmarking with in-building laundry columns",
     "nyc": ["nyc_ll84_benchmarking"], "tier": "enrichment",
     "note": "~40 US cities have a benchmarking ordinance; the laundry-hookup columns "
             "are a New York reporting artefact, not part of the standard template."},
    {"generic": "The dominant residential listings portal",
     "nyc": ["streeteasy_listings"], "tier": "enrichment",
     "note": "The brand is NYC-only; the FUNCTION — pages that advertise in-building "
             "amenities — exists in every metro. Advertising, not inspection: silence "
             "is not absence."},
    {"generic": "Storefront / commercial-vacancy registry",
     "nyc": ["nyc_dof_storefront_registry"], "tier": "unobtainable",
     "note": "**No second city has one.** A vacant-BUILDING registry is not the same "
             "thing: it records abandoned structures, not an empty ground floor under "
             "an occupied building, which is the exact object the screen is pointing at."},
]
REQ_TIER_LABEL = {
    "minimum": "MINIMUM",
    "anchor": "anchor",
    "enrichment": "enrichment",
    "unobtainable": "not obtainable",
}

# ---------------------------------------------------------------------------
# SECOND-CITY PROBE — research only, nothing ingested.
#
# Portals checked on PROBE_DATE. `status` is one of exists / partial / missing.
# A dataset id of "unverified" means the dataset was described in documentation
# but the id could not be confirmed against the portal; it is recorded as
# unverified rather than dropped, because "we could not confirm it" and "it is
# not there" are different facts and only one of them is a blocker.
# ---------------------------------------------------------------------------
PROBE_INPUTS = [
    "Parcels with units + floor area",
    "Building permits with status/renewal",
    "Food-service inspections with names",
    "Business licences with issue dates",
    "Liquor licences (state)",
    "Transit ridership by station/stop",
    "Pedestrian counts",
    "Storefront / vacancy registry",
]
STATUS_MARK = {"exists": "yes", "partial": "partial", "missing": "no",
               "unverified": "unverified"}

CITY_PROBE: list[dict] = [
    {
        "city": "Chicago",
        "grade_today": "D",
        "grade_ceiling": "C",
        "grade_reason": (
            "The same ceiling as New York, bounded by the same section (`economics`) "
            "and not by anything Chicago fails to publish. Every grade-C minimum input "
            "exists — including the permit status column that most portals omit — but "
            "the parcel layer has to be assembled from four Cook County Assessor files "
            "with different coverage, and unit counts are absent for large multifamily, "
            "which biases `homes_400m` downward exactly where density is highest."),
        "inputs": {
            "Parcels with units + floor area": {
                "status": "partial",
                "dataset": "nj4t-kc8j + x54s-btds + csik-bsws + 3r7i-mrz4",
                "url": "https://datacatalog.cookcountyil.gov/Property-Taxation/"
                       "Assessor-Parcel-Universe/nj4t-kc8j",
                "note": "No single row-per-lot file carries both. Parcel Universe has "
                        "geometry and tax joins but zero building characteristics; "
                        "units and building sq ft live in the improvement-"
                        "characteristics file, which is capped at residential parcels "
                        "under 7 units; larger multifamily units and floor area appear "
                        "only in Commercial Valuation, 2021+ and income-valued "
                        "properties only. Zoning is a fifth file (`7cve-jgbp`), "
                        "district boundaries only — FAR is not a per-parcel attribute "
                        "and has to be derived from the ordinance table."},
            "Building permits with status/renewal": {
                "status": "exists", "dataset": "ydr8-5enu",
                "url": "https://data.cityofchicago.org/Buildings/Building-Permits/"
                       "ydr8-5enu",
                "note": "The good surprise. 4.47M rows carrying `permit_status`, "
                        "`permit_milestone`, `application_start_date`, `issue_date`, "
                        "`processing_time` and `work_type`. Chicago permits do not "
                        "renew the way NYC's do, so `active_share` has to be redefined "
                        "on milestone rather than on a renewal fee — a modelling "
                        "change, not a missing column."},
            "Food-service inspections with names": {
                "status": "exists", "dataset": "4ijn-s7e5",
                "url": "https://data.cityofchicago.org/Health-Human-Services/"
                       "Food-Inspections/4ijn-s7e5",
                "note": "Daily, since 2010, with DBA/AKA names and lat/lon. A direct "
                        "analogue of DOHMH `43nn-pn8j` and it anchors the same three "
                        "categories."},
            "Business licences with issue dates": {
                "status": "partial", "dataset": "r5kz-chrr",
                "url": "https://data.cityofchicago.org/Community-Economic-Development/"
                       "Business-Licenses/r5kz-chrr",
                "note": "Historical since 2002 with lat/lon, `date_issued`, "
                        "`license_status` and `license_status_change_date` — richer "
                        "than NYC's issued roster. But **laundromats and salons are "
                        "not distinct licence types**, so the two anchors NYC uses for "
                        "laundry and for hair/nail do not exist here; childcare types "
                        "do."},
            "Liquor licences (state)": {
                "status": "partial", "dataset": "nrmj-3kcf (city) / ILCC portal (state)",
                "url": "https://data.cityofchicago.org/Community-Economic-Development/"
                       "Business-Licenses-Current-Liquor-and-Public-Places/nrmj-3kcf",
                "note": "City-level is stronger than NYC's: the historical licence file "
                        "already carries status, so closures are recoverable without a "
                        "separate inactive companion. State-level ILCC moved to a new "
                        "portal in 2026 and ceased/expired licences come out of a "
                        "date-range search plus CSV export, not a stable bulk URL."},
            "Transit ridership by station/stop": {
                "status": "partial", "dataset": "5neh-572f",
                "url": "https://data.cityofchicago.org/Transportation/"
                       "CTA-Ridership-L-Station-Entries-Daily-Totals/5neh-572f",
                "note": "Per-station DAILY entries back to 2001 — transit quality "
                        "survives, the D76 daypart signal does not. CTA's GTFS carries "
                        "no `pathways.txt` or `levels.txt`, so there is no entrance "
                        "geometry and walk distance is to the station point. Bus is "
                        "route-level monthly, never per stop."},
            "Pedestrian counts": {
                "status": "missing", "dataset": "",
                "url": "",
                "note": "Nothing on the city, county or state portal. The only citywide "
                        "counts are vehicle ADT taken roughly once a decade "
                        "(`pfsx-4n4m`); Loop Alliance counts are third-party. The "
                        "access proxy would ship unvalidated."},
            "Storefront / vacancy registry": {
                "status": "missing", "dataset": "u7si-yh3t (nearest substitute)",
                "url": "https://data.cityofchicago.org/Buildings/"
                       "Vacant-Building-Violations/u7si-yh3t",
                "note": "Chicago has the LEGAL analogue — the Vacant Building and "
                        "Vacant Storefront Registration — but it is queryable one "
                        "property at a time behind a login, never published in bulk. "
                        "Vacant Building Violations is enforcement records, not a "
                        "current-status registry, and conflates a vacant building with "
                        "an empty ground floor under an occupied one."},
        },
        "extras": (
            "Cook County pre-joins CMAP walkability scores, TIF/enterprise-zone flags "
            "and FEMA flood flags onto every parcel, and the Commercial Valuation file "
            "exposes NOI, cap rate and occupancy for income properties — underwriting "
            "detail with no NYC public equivalent, and a plausible free substitute for "
            "part of paid-sources gap (c)."),
        "verdict": (
            "**The strongest of the three.** The two hard gaps are pedestrian counts "
            "(nothing published, so the access proxy ships unvalidated) and the "
            "storefront registry (legally exists, operationally locked). Neither blocks "
            "a grade-C card. The real work is the parcel join, and the real risk is the "
            "missing unit counts on large multifamily."),
    },
    {
        "city": "Los Angeles",
        "grade_today": "D",
        "grade_ceiling": "C",
        "grade_reason": (
            "C on the data — and the number would still not mean anything. LA is "
            "driving-dominant; every distance in Loci is an 800 m WALK on an OSM graph, "
            "calibrated on Manhattan and Brooklyn under D48. That is not a "
            "miscalibration to correct, it is the wrong instrument, and it has to be "
            "replaced with a drive-time kernel before the data ceiling is worth "
            "reaching."),
        "inputs": {
            "Parcels with units + floor area": {
                "status": "exists",
                "dataset": "LA County Assessor Parcel Data (rolls 2021–present)",
                "url": "https://data.lacounty.gov/datasets/"
                       "785f54236d1644dc975a55af19b3dd70/about",
                "note": "The cleanest parcel layer of the three: number of units, main "
                        "square footage, year built, 4-digit use code and lat/lon on "
                        "one row. Grain is roll-year × AIN, so filter to the latest "
                        "roll. Zoning is city-only and separate (ZIMAS / GeoHub), and "
                        "covers neither unincorporated county nor the 87 other cities."},
            "Building permits with status/renewal": {
                "status": "exists", "dataset": "pi9x-tg5x",
                "url": "https://data.lacity.org/City-Infrastructure-Service-Requests/"
                       "Building-and-Safety-Building-Permits-Issued-from-2/pi9x-tg5x",
                "note": "Carries `status_desc` AND `status_date` alongside "
                        "`permit_type`, `use_code`, address and lat/lon — a genuine "
                        "activity axis in one file. LA City only; 2020-present, with a "
                        "2010–2019 companion. Use this, not the simpler `hbkd-qubn`, "
                        "which has no status date."},
            "Food-service inspections with names": {
                "status": "partial",
                "dataset": "LA County DPH Restaurant & Market Inspections",
                "url": "https://data.lacounty.gov/datasets/"
                       "19b6607ac82c4512b10811870975dbdc/about",
                "note": "**Recently restricted.** The county's own page states that "
                        "inspections conducted on or after 2025-08-25 must be requested "
                        "through a CPRA request. Whether the portal extract is frozen "
                        "at that date is unverified and must be checked against the "
                        "file before relying on it. This is the anchor for three of the "
                        "fifteen categories."},
            "Business licences with issue dates": {
                "status": "exists", "dataset": "6rrh-rzua",
                "url": "https://data.lacity.org/Administration-Finance/"
                       "Listing-of-Active-Businesses/6rrh-rzua",
                "note": "Better keyed than NYC's: a real NAICS code, so laundromats "
                        "(812320), salons (812112) and childcare (624410) are "
                        "identifiable rather than absent. ACTIVE only, so it is "
                        "survivorship-biased exactly like the NYS salon file — snapshot "
                        "enrichment, never a panel."},
            "Liquor licences (state)": {
                "status": "partial", "dataset": "CA ABC daily data export (not Socrata)",
                "url": "https://www.abc.ca.gov/licensing/licensing-reports",
                "note": "A daily CSV covers all pending and active licences — which "
                        "means the PENDING queue, NYC's earliest go-live signal, exists "
                        "here too. Closures do not: surrendered licences come out as a "
                        "monthly report, so a closure history has to be accumulated "
                        "from snapshots rather than downloaded."},
            "Transit ridership by station/stop": {
                "status": "missing", "dataset": "",
                "url": "https://opa.metro.net/MetroRidership/",
                "note": "Metro publishes LINE-level ridership through a dashboard, one "
                        "query at a time, not in bulk. Station-level figures have "
                        "circulated only through a public-records request. The rail "
                        "GTFS was downloaded and confirmed to contain no `pathways.txt` "
                        "or `levels.txt`. Transit would be presence, not quality, and "
                        "there would be no foot-traffic proxy at all."},
            "Pedestrian counts": {
                "status": "partial", "dataset": "6ux4-qj74 (2023), m6qi-ifup (2019)",
                "url": "https://data.lacity.org/Transportation/"
                       "2023-Walk-Bike-Count-Data/6ux4-qj74",
                "note": "Real bulk CSVs, odd years since 2019: ~100 locations, 79 "
                        "temporary 8-hour manual counts plus 21 permanent counters. "
                        "Sparser and more project-driven than DOT's 114 fixed points, "
                        "and it inherits the same restricted-range problem."},
            "Storefront / vacancy registry": {
                "status": "missing", "dataset": "",
                "url": "",
                "note": "No analogue and no near-analogue. The Foreclosure Registry "
                        "covers residential foreclosure only; the LAMC vacant-structure "
                        "penalty is complaint-driven with no published registry. No "
                        "ground-floor-commercial reporting duty exists in city or "
                        "county."},
        },
        "extras": (
            "Business licences carry NAICS, which NYC's DCWP roster does not — the "
            "filing-blind categories of GTM-152 are partly visible here for free."),
        "verdict": (
            "**The city/county split is a structural seam, not a nuisance.** Parcels "
            "and food inspections are LA County; permits, licences, zoning and "
            "pedestrian counts are LA City; none of the county layers are clipped to "
            "the city, and the county contains 87 other incorporated cities. Two "
            "platforms, two geographies, two refresh cadences — and then the walk-"
            "distance problem on top."),
    },
    {
        "city": "Philadelphia",
        "grade_today": "D",
        "grade_ceiling": "C",
        "grade_reason": (
            "Reaches the ceiling for fewer CATEGORIES than the other two. There is no "
            "bulk food-inspection feed at all -- only a one-record web lookup -- so "
            "restaurant, cafe and bar lose the anchor that is the cheapest win in every "
            "other city, and laundromats, salons and barbers hide inside an ADDRESSLESS "
            "commercial-activity licence table. Worse for the universe: the OPA parcel "
            "file has floor area but **no unit count**, so `homes_400m` -- an input to a "
            "load-bearing section -- has to be modelled from ACS households apportioned "
            "by livable area rather than read off the parcel."),
        "inputs": {
            "Parcels with units + floor area": {
                "status": "partial", "dataset": "opa_properties_public (Carto)",
                "url": "https://opendataphilly.org/datasets/"
                       "philadelphia-properties-and-assessment-history/",
                "note": "90 fields verified against the Carto API. "
                        "`total_livable_area` and `total_area` are present; there is no "
                        "UnitsTotal analogue -- the `unit` column holds per-condo "
                        "designators ('8D', 'G', '314'), not a count. `zoning` sits on "
                        "the row and again as a citywide polygon layer; `building_code` "
                        "and `category_code` stand in for land use."},
            "Building permits with status/renewal": {
                "status": "exists", "dataset": "permits (Carto)",
                "url": "https://opendataphilly.org/datasets/"
                       "licenses-and-inspections-building-and-zoning-permits/",
                "note": "The best of the three. 48 fields verified: `permittype`, "
                        "`typeofwork`, `address`, `permitissuedate`, `status`, "
                        "`mostrecentinsp`, `permitcompleteddate`, "
                        "`certificateofoccupancydate` and -- uniquely -- "
                        "`numberofunits` on the permit itself, which is the net-unit "
                        "recode NYC needs a separate DCP file for."},
            "Food-service inspections with names": {
                "status": "missing", "dataset": "",
                "url": "https://www.phila.gov/services/permits-violations-licenses/"
                       "get-a-license/business-licenses/food-businesses/"
                       "look-up-a-food-safety-inspection-report/",
                "note": "**The one clean miss that costs real categories.** A "
                        "per-establishment web lookup only; no bulk CSV, no API, "
                        "nothing in OpenDataPhilly's Food or Health categories. "
                        "Restaurant, cafe and bar fall to `unanchored_grade: C` on "
                        "aggregators alone, which is where CONTEXT 7.1 bites."},
            "Business licences with issue dates": {
                "status": "partial", "dataset": "business_licenses (Carto)",
                "url": "https://opendataphilly.org/datasets/"
                       "licenses-and-inspections-business-licenses/",
                "note": "48 fields verified, with `initialissuedate`, "
                        "`mostrecentissuedate` and geocoded coordinates. All 53 "
                        "`licensetype` values were enumerated: Child Care Facility is "
                        "there; **laundromats, salons and barbershops are not**, and "
                        "fall into the generic Commercial Activity License table "
                        "(`com_act_licenses`), which carries no address or coordinate "
                        "field at all."},
            "Liquor licences (state)": {
                "status": "partial",
                "dataset": "PLCB+ License Search (not a catalogued table)",
                "url": "https://plcbplus.pa.gov/pub/Default.aspx"
                       "?PossePresentation=LicenseSearch",
                "note": "A search UI with a bulk CSV export filterable by status -- "
                        "active, expired, pending, transfers, safekeeping, suspended -- "
                        "so closures ARE retained, better than the NYS split "
                        "active/inactive pair. Address completeness in the export is "
                        "unverified; it is a UI export, not a documented schema, so "
                        "there is no stable endpoint to automate against."},
            "Transit ridership by station/stop": {
                "status": "exists", "dataset": "SEPTA Ridership Statistics + SEPTA GTFS",
                "url": "https://opendataphilly.org/datasets/septa-ridership-statistics/",
                "note": "Average daily ridership per stop/station, but as periodic "
                        "SNAPSHOTS (seasonal 2014-2025, monthly by mode/route, "
                        "regional-rail station summaries 2017-2024 with 2020-21 "
                        "missing) -- not a continuous series, so no daypart signal. The "
                        "live GTFS was downloaded: the bus/trolley feed DOES carry "
                        "`pathways.txt` and `levels.txt`; the rail feed does not."},
            "Pedestrian counts": {
                "status": "exists", "dataset": "DVRPC Pedestrian Count Locations",
                "url": "https://catalog.dvrpc.org/dataset/"
                       "dvrpc-pedestrian-count-locations",
                "note": "The only one of the three with a real bulk-downloadable "
                        "pedestrian count layer (CSV / shapefile / GeoJSON), run "
                        "regionally by DVRPC rather than by the city. The access proxy "
                        "could be validated here on day one."},
            "Storefront / vacancy registry": {
                "status": "missing", "dataset": "Vacant Property Indicators (substitute)",
                "url": "https://opendataphilly.org/datasets/vacant-property-indicators/",
                "note": "No landlord self-report registry. The substitute is a MODELLED "
                        "administrative 'likely vacant' flag -- not reported, not "
                        "ground-floor-specific. A second, weaker proxy: the 'Vacant "
                        "Commercial Property' licence type in `business_licenses`, "
                        "which is compliance-based and so has the same invisible-"
                        "non-filing problem as LL157, without the storefront grain."},
        },
        "extras": (
            "Two that matter. **Commercial Corridors of Philadelphia** is a citywide "
            "GIS layer of designated retail-corridor boundaries -- Loci infers corridors "
            "from POI density and floor area (D82/D84); here they are published. And "
            "**Real Estate Transfers**, a fully open deed-level sales feed sitting next "
            "to the parcels table, is an ACRIS analogue with no NYC open equivalent. "
            "Also Storefront Improvement Program grants (a positive-investment signal "
            "per corridor) and large-building energy benchmarking."),
        "verdict": (
            "**Best permits, worst anchors.** The permit file alone would save weeks -- "
            "status, completion, CO date and net units on one row. But a screen with no "
            "food-inspection census and no laundry or salon licence type runs five of "
            "the fifteen categories on aggregator coverage alone, which is the exact "
            "failure mode CONTEXT 7.1 says would invalidate the finding."),
    },
]


def _load_grades() -> dict:
    return yaml.safe_load(GRADES_PATH.read_text())


def sources_by_id() -> dict[str, dict]:
    return {s["id"]: s for s in registry.load()["sources"]}


def pipeline_sources() -> list[dict]:
    """Every source carrying a portability block, sorted by id."""
    return sorted((s for s in registry.load()["sources"] if s.get("portability")),
                  key=lambda s: s["id"])


def by_class() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {c: [] for c in CLASS_ORDER}
    for s in pipeline_sources():
        out[s["portability"]["class"]].append(s)
    return out


def by_stage() -> dict[str, list[dict]]:
    """stage -> sources feeding it, ordered most-portable-class first then by id."""
    out: dict[str, list[dict]] = {st: [] for st in registry.PIPELINE_STAGES}
    for s in pipeline_sources():
        for stage in s["portability"]["feeds"]:
            out[stage].append(s)
    for stage in out:
        out[stage].sort(key=lambda s: (CLASS_ORDER.index(s["portability"]["class"]),
                                       s["id"]))
    return out


def _at_least(grade: str, target: str) -> bool:
    return GRADE_ORDER.index(grade) <= GRADE_ORDER.index(target)


def minimum_input_set(target: str) -> dict:
    """The smallest set of inputs that lets the VERDICT reach `target`.

    The verdict is the minimum over the load-bearing sections (recommend_grades
    §"WHY GRADES AND NOT A SCORE"), so reaching a target verdict means EVERY
    load-bearing section reaching it. For each, take the cheapest tier that
    does — cheapest meaning the lowest grade that still clears the bar, since a
    higher grade always costs strictly more inputs.

    Returns {sources, also, per_section, blocked_by}. `blocked_by` names the
    sections that cannot reach the target at all; when it is non-empty the
    target verdict is UNREACHABLE and the source list is not a plan.
    """
    grades = _load_grades()
    sources: set[str] = set()
    also: list[str] = []
    per_section: dict[str, dict | None] = {}
    blocked: list[str] = []
    paid: list[str] = []

    for section in grades["load_bearing"]:
        tiers = SECTION_INPUTS[section]
        # Lowest grade that still clears the bar = last qualifying tier, since
        # SECTION_INPUTS is written best-grade-first.
        qualifying = [t for t in tiers if _at_least(t["grade"], target)]
        if not qualifying:
            blocked.append(section)
            per_section[section] = None
            continue
        tier = qualifying[-1]
        per_section[section] = tier
        if tier.get("paid"):
            paid.append(section)
        sources |= set(tier["sources"])
        for extra in tier.get("also", []):
            if extra not in also:
                also.append(extra)

    return {"sources": sorted(sources), "also": also, "paid_sections": paid,
            "per_section": per_section, "blocked_by": blocked,
            "verdict": grades["verdict"]["by_grade"][target]}


def _flat(text: str) -> str:
    return " ".join(str(text).split())


def _wrap(text: str, width: int = 88) -> str:
    return "\n".join(textwrap.wrap(_flat(text), width=width))


def _nyc_example(sid: str, byid: dict[str, dict]) -> str:
    """`Name` plus its dataset id, pulled from the registry so it cannot drift."""
    s = byid[sid]
    did = s.get("dataset_id")
    return f"{s['name']}" + (f" (`{did}`)" if did else "")


def render() -> str:
    reg_sources = pipeline_sources()
    byid = sources_by_id()
    grades = _load_grades()
    cls = by_class()
    stages = by_stage()

    md: list[str] = [
        "# Loci — portability: what a second city has to publish",
        "",
        "**GENERATED — do not edit.** Rendered by `loci gen-portability` from the "
        "`portability:` blocks in [`src/loci/registry.yaml`](../src/loci/registry.yaml) "
        "and the grade config in "
        "[`src/loci/model/recommend_grades.yaml`](../src/loci/model/recommend_grades.yaml). "
        "`loci check-sources` fails if this file differs from a fresh render.",
        "",
        "Owner ask, 2026-09-14: *\"what are the critical inputs necessary to be able to "
        "expand the model to new cities.\"* This is the machine-checked answer. Nothing "
        "below has been ingested for any city other than New York — §6 is a portal "
        f"survey dated {PROBE_DATE}, not a pipeline.",
        "",
        "---",
        "",
        "## 1. The registry by portability class",
        "",
        "`class` answers *where can a second city get this*, and it is deliberately not "
        "the same question as `tier`. A `city`-tier source is usually **not** unique to "
        "the city: another city publishes the same fact under a different schema. Only "
        f"{len(cls['city_unique'])} rows in the registry have no equivalent "
        "anywhere else.",
        "",
        "| Class | n | What it means for a second city |",
        "|---|---|---|",
    ]
    class_meaning = {
        "universal": "Works on day one, anywhere on earth. Nothing to procure.",
        "national": "Works on day one in any US city. Carries its own portable bias.",
        "state": "Re-plumbed per state. Publication quality varies enormously; expect "
                 "some states to publish nothing usable.",
        "city_open_data": "An equivalent exists but the schema is different. This is the "
                          "real cost of a second city: an adapter per source.",
        "city_unique": "No equivalent exists. The stage degrades, permanently — see §4.",
    }
    for c in CLASS_ORDER:
        md.append(f"| **{CLASS_LABEL[c]}** | {len(cls[c])} | {class_meaning[c]} |")
    md += ["", f"**{len(reg_sources)} sources classed.** "
               f"{len(cls['universal']) + len(cls['national'])} of them "
               f"({(len(cls['universal']) + len(cls['national'])) / len(reg_sources):.0%}) "
               "need no per-city work at all.", ""]

    # Confidence caveats.
    shaky = [s for s in reg_sources
             if s["portability"].get("confidence") in {"low", "med"}]
    md += [f"**{len(shaky)} of the {len(reg_sources)} classifications are judgement "
           "calls** (`confidence: med` or `low`) and carry a note saying what the "
           "uncertainty is. They are listed with their notes in §6.", "",
           "---", "", "## 2. By pipeline stage", "",
           "A source's `feeds` list is the set of stages that stop working without it. "
           "Rows are ordered most-portable class first, so the bottom of each table is "
           "the part a second city has to solve.", ""]

    for stage in registry.PIPELINE_STAGES:
        rows = stages[stage]
        md += [f"### `{stage}`", "", _wrap(STAGE_BLURB[stage]), "",
               "| Source | Class | Without it |", "|---|---|---|"]
        for s in rows:
            p = s["portability"]
            conf = "" if p.get("confidence") == "high" else \
                f" *({p.get('confidence')} conf.)*"
            md.append(f"| {s['name']} | {CLASS_LABEL[p['class']]}{conf} "
                      f"| {_flat(p['degrades_to'])} |")
        md.append("")
        unique = [s for s in rows if s["portability"]["class"] == "city_unique"]
        if unique:
            md += [f"**Stage `{stage}` depends on "
                   f"{len(unique)} city-unique source"
                   f"{'s' if len(unique) > 1 else ''}** — "
                   + ", ".join(s["name"] for s in unique)
                   + ". It cannot be reproduced at full strength anywhere else.", ""]

    # ---------------------------------------------------------------- minimum set
    md += ["---", "", "## 3. The minimum input set, by evidence grade", "",
           _wrap(
               "`recommend_grades.yaml` grades each claim on its own evidence and the "
               "verdict is the MINIMUM over the load-bearing sections — a chain is as "
               "strong as its weakest link. So the question \"what does a second city "
               "need\" only has an answer once you say *to reach what verdict*. Load-"
               "bearing sections: "
               + ", ".join(f"`{s}`" for s in grades["load_bearing"])
               + ". Context sections (`"
               + "`, `".join(grades["context"])
               + "`) describe the site and can never block a verdict."),
           ""]

    for target in ("B", "C", "D"):
        req = minimum_input_set(target)
        verdict = grades["verdict"]["by_grade"][target]
        md += [f"### Grade {target} — verdict *\"{verdict}\"*", ""]
        if req["paid_sections"] and not req["blocked_by"]:
            md += [_wrap(
                "**Not reachable on open data — in any city, New York included.** "
                + " and ".join(f"`{s}`" for s in req["paid_sections"])
                + " can only reach grade " + target + " through a PAID input (see "
                "docs/PAID-SOURCES.md). This is not a portability problem: it is the "
                "same wall NYC is standing at today, and no second city changes it."),
                ""]
        if req["blocked_by"]:
            md += [_wrap(
                f"**UNREACHABLE — in any city, New York included.** Blocked by "
                + " and ".join(f"`{b}`" for b in req["blocked_by"])
                + ", which cannot reach grade "
                + target
                + " on any open data that exists. This is not a portability problem: "
                  "it is the same wall NYC is standing at today, and no second city "
                  "changes it."), ""]
        md += ["| Section | Ceiling | What buys it |", "|---|---|---|"]
        for section in grades["load_bearing"]:
            tier = req["per_section"][section]
            if tier is None:
                md.append(f"| `{section}` | — | **cannot reach {target}.** "
                          f"{_flat(SECTION_INPUTS[section][0]['why'])} |")
                continue
            names = [byid[sid]["name"] for sid in tier["sources"]]
            bought = "; ".join(names) if names else ""
            extra = "; ".join(tier.get("also", []))
            cell = " — ".join(x for x in (bought, extra) if x) or "nothing further"
            md.append(f"| `{section}` | {tier['grade']} | {cell} |")
        md.append("")
        if not req["blocked_by"]:
            md += [f"**Minimum set for grade {target}: "
                   f"{len(req['sources'])} source"
                   f"{'s' if len(req['sources']) != 1 else ''}"
                   + (f" plus {len(req['also'])} non-registry requirement"
                      f"{'s' if len(req['also']) != 1 else ''}" if req["also"] else "")
                   + ".**", ""]
            for sid in req["sources"]:
                s = byid[sid]
                md.append(f"- `{sid}` — {s['name']} "
                          f"({CLASS_LABEL[s['portability']['class']]})")
            for extra in req["also"]:
                md.append(f"- *(not a registry source)* {extra}")
            md.append("")
            classes = [byid[sid]["portability"]["class"] for sid in req["sources"]]
            per_city = sum(1 for c in classes
                           if c in {"state", "city_open_data", "city_unique"})
            md += [f"Of those {len(req['sources'])}, **{per_city} need per-city or "
                   f"per-state work**; the rest work on day one.", ""]

    md += [_wrap(
        "**The headline, and it is not about data portability at all.** `economics` "
        "cannot reach B without cash-flow comps, which no city publishes, and "
        "`addressable_demand` defaults to `no_haircut_grade: C` for fourteen of the "
        "fifteen categories. So the verdict *act* is out of reach in New York today, "
        "and a second city inherits that ceiling unchanged. What a second city can "
        "reach is `diligence` — and what decides whether it reaches even that is the "
        "one column in §3's grade-C table that most portals omit: a permit renewal or "
        "status date."), "",
        "---", "", "## 4. The city-unique sources, and what is lost without each", "",
        _wrap(f"{len(cls['city_unique'])} rows have no equivalent anywhere else. "
              "These are the permanent degradations — not an adapter to write, a "
              "capability a second city does not have."), ""]
    for s in cls["city_unique"]:
        p = s["portability"]
        md += [f"### {s['name']}",
               "",
               f"*Feeds:* " + ", ".join(f"`{f}`" for f in p["feeds"])
               + f" · *Class confidence:* {p.get('confidence', 'high')}",
               "",
               _wrap(f"**Lost without it.** {_flat(p['degrades_to'])}"),
               ""]
        if p.get("note"):
            md += [_wrap(f"**Why nothing replaces it.** {_flat(p['note'])}"), ""]

    md += ["---", "", "## 5. What a new city must publish", "",
           _wrap("Generic name first, because the NYC dataset is an example of the "
                 "requirement and not the requirement itself. Dataset ids are pulled "
                 "from the registry, so they cannot drift from what is actually "
                 "ingested."),
           "",
           "| Requirement | Tier | NYC example | What to check for |",
           "|---|---|---|---|"]
    for r in REQUIREMENTS:
        examples = "<br>".join(_nyc_example(sid, byid) for sid in r["nyc"])
        md.append(f"| **{r['generic']}** | {REQ_TIER_LABEL[r['tier']]} | {examples} "
                  f"| {_flat(r['note'])} |")
    md.append("")

    # ------------------------------------------------------------- second city
    md += ["---", "", "## 6. Second-city readiness", "",
           _wrap(f"Portal survey, {PROBE_DATE}. **Research only — nothing has been "
                 "ingested for any of these cities and no adapter exists.** `partial` "
                 "means the fact is published but not in the form the pipeline needs; "
                 "the note says which half is missing."),
           ""]
    if not CITY_PROBE:
        md += ["*No probe recorded.*", ""]
    else:
        md += ["| Input | " + " | ".join(c["city"] for c in CITY_PROBE) + " |",
               "|---|" + "---|" * len(CITY_PROBE)]
        for inp in PROBE_INPUTS:
            cells = []
            for c in CITY_PROBE:
                row = c["inputs"][inp]
                cells.append(STATUS_MARK[row["status"]])
            md.append(f"| {inp} | " + " | ".join(cells) + " |")
        md += ["| **grade on day one** | "
               + " | ".join(f"**{c['grade_today']}**" for c in CITY_PROBE) + " |",
               "| **ceiling after a local refit** | "
               + " | ".join(f"**{c['grade_ceiling']}**" for c in CITY_PROBE) + " |",
               "",
               _wrap(
                   "**Why every city reads D on day one, and why that is not a verdict "
                   "on the city.** `economics` grades D until a site-revenue "
                   "calibration for the category has been refitted locally and passed "
                   "its own leave-one-ZIP-out backtest — which is true in New York "
                   "today for fourteen of the fifteen categories. So the day-one grade "
                   "is D everywhere, the ceiling is C everywhere, and what the rows "
                   "above actually decide is HOW MANY CATEGORIES reach the ceiling and "
                   "how defective the universe underneath them is."),
               ""]
        for c in CITY_PROBE:
            md += [f"### {c['city']}", "",
                   _wrap(f"**Day one: {c['grade_today']}. Ceiling after a local refit: "
                         f"{c['grade_ceiling']}.** {c['grade_reason']}"),
                   "",
                   "| Input | Status | Dataset | Note |", "|---|---|---|---|"]
            for inp in PROBE_INPUTS:
                row = c["inputs"][inp]
                ds = row.get("dataset", "")
                url = row.get("url", "")
                cell = f"[{ds}]({url})" if url and ds else (ds or url or "—")
                md.append(f"| {inp} | {STATUS_MARK[row['status']]} | {cell} "
                          f"| {_flat(row['note'])} |")
            md.append("")
            if c.get("extras"):
                md += [_wrap(f"**Has that NYC does not.** {_flat(c['extras'])}"), ""]
            if c.get("verdict"):
                md += [_wrap(c["verdict"]), ""]

    # ------------------------------------------------------- confidence appendix
    md += ["---", "", "## 7. Classifications that are judgement calls", "",
           _wrap("Every row here is a `class` the author is not certain of, with the "
                 "reason. Recorded so a second-city plan starts from the doubt rather "
                 "than rediscovering it."),
           "",
           "| Source | Class | Conf. | The uncertainty |", "|---|---|---|---|"]
    for s in sorted(shaky, key=lambda s: (s["portability"]["confidence"], s["id"])):
        p = s["portability"]
        md.append(f"| {s['name']} | {CLASS_LABEL[p['class']]} | {p['confidence']} "
                  f"| {_flat(p.get('note', ''))} |")
    # ------------------------------------------------- the one working adapter
    md += ["",
           "---",
           "",
           "## 8. The one adapter that has actually been run: Citi Bike → Divvy",
           "",
           _wrap(
               "Everything above §7 is a survey. This section is the single place "
               "where a second city's data has actually been READ, and it is here to "
               "bound the claim rather than to widen it. `loci citibike divvy-probe "
               "--month 2025-06` (GTM-168 track P, D111) put one Chicago month "
               "through the same reader that builds New York's bike panel: "
               "`src/loci/sources/cities/lyft_bikeshare.py` holds a `SYSTEMS` dict — "
               "bucket URL, month-key and legacy-key regexes, bounding box, dock-id "
               "pattern, sibling-system prefix, twin-fusion suffix, dockless-end "
               "policy and every threshold — and `sources/cities/nyc/citibike.py` is "
               "now one entry in it (`nyc_citibike`), byte-identical in the SQL it "
               "emits."),
           "",
           _wrap(
               "**What PORTABLE means here: the trip-file reader and the "
               "station-month grain travel.** Divvy's 2025-06 file (678,904 trips) "
               "landed as 13,600 `station × month × day_type × daypart` rows over "
               "1,397 docks, on the same five dayparts and the same calendar "
               "divisor, with every excluded trip named: 507,039 counted, 150,904 "
               "starting off-dock, 20,794 on Juneteenth, 167 outside the month — an "
               "identity with the file's own row count, not a reconciliation."),
           "",
           _wrap(
               "**What it does NOT mean: Loci does not run in Chicago.** There is no "
               "address frame there (no PLUTO, §4), no walk graph built, no supply "
               "set, no anchor sources — so nothing in that table becomes an address "
               "measure, nothing feeds the growth feature, and NOTHING here supports "
               "any claim about Chicago retail. A station-month table is the end of "
               "the line for a second city, and it is a table about bicycles. The "
               "day-one grade for Chicago in §6 is unchanged by this probe."),
           "",
           _wrap(
               "**What the probe taught that the survey could not.** Two per-system "
               "facts only appear when a file is actually read. (1) Divvy permits a "
               "trip to end off-dock: 23.1% of 2025-06 ends carry no station id, "
               "against New York's rounding error. Those rides leave the station "
               "grain because there is no dock to attribute them to, and the share "
               "is REPORTED — the threshold that would refuse a month is a `System` "
               "field, because New York's sub-1% intuition applied to Chicago would "
               "refuse every good month. (2) Divvy ships CRLF and Citi Bike ships "
               "LF; phase 1's header rewrite dropped the carriage return, which made "
               "DuckDB's sniffer read zero columns out of a 136 MB file. A line "
               "ending is the kind of thing a portability audit cannot predict and a "
               "probe finds in a minute."),
           ""]

    md += ["",
           "---",
           "",
           _wrap("**One caveat no check can enforce.** Every distance in Loci is a "
                 "WALK distance on an OSM graph, and the whole screen is calibrated on "
                 "Manhattan and Brooklyn — dense, walking-dominant, chosen for that "
                 "reason in D48. The 800 m threshold, the saturating DNCI constants "
                 "`k_c`, the 1.233 circuity, the density elasticities in "
                 "`density_elasticity.yaml` and the D91 revenue calibration are all "
                 "NYC-fitted parameters. A city that reads green on every row of §6 "
                 "still needs those refitted before a single number it produces means "
                 "anything, and in a driving-dominant city the 800 m walk threshold is "
                 "not a mild miscalibration — it is the wrong instrument."),
           ""]
    return "\n".join(md)


def generate() -> tuple[int, int]:
    """Write docs/PORTABILITY.md. Returns (n_sources_classed, n_city_unique)."""
    DOC_PATH.write_text(render())
    rows = pipeline_sources()
    return len(rows), sum(1 for s in rows
                          if s["portability"]["class"] == "city_unique")
