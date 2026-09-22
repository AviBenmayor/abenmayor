"""Export the MapLibre webmap's two point layers from the database.

Replaces the ad-hoc scratchpad script that produced `webmap/gap_buildings.json`
(commit e1784b6) -- per the repo standard, loose scripts become CLI
subcommands: `loci export-webmap`.

TWO LAYERS, ONE CATEGORY FILTER. The map answers one question -- "where is
business X missing, and where does X actually exist?" -- so both layers are
sliced the same way:

  gaps/<category>.json   addresses from `analysis.address_gaps` whose
                         `<category>_ratio > 1` (the model's own definition of
                         a missing category: see model/address_gaps.py, D41).
                         EVERY address -- the eligibility gate is retired
                         (D75) -- each carrying the D75 censoring flags.
  pois/<category>.json   every canonical business location for that category,
                         read through `analysis.poi_supply` (sql/003 + sql/006).

THE MAP MUST SHOW THE SUPPLY THE GAPS WERE MEASURED AGAINST (D52). Until this
module read `analysis.poi_dedup.is_canonical` directly, so the map drew 100,213
"known locations" for MN+BK while `analysis.address_gaps` had been computed
against the PRINCIPLED supply set. The owner's whole validation move -- eyeball
a gap next to the laundromats around it -- was therefore being made against a
supply the model never saw. Both layers now come from one place:
`analysis.poi_supply`, filtered by `score/supply.supply_predicate(...)`, the
same function `model/address_gaps.py` uses. `--supply-set` selects the set and
is CHECKED against the `supply_set` recorded in address_gaps provenance; a
disagreement is printed loudly and written into meta.json rather than silently
producing a map whose two layers disagree.

EXCLUDED POINTS ARE EXPORTED, NOT DELETED. A record the set drops -- under
PRINCIPLED, a lone aggregator record in an anchored category, with no licence
and no second feed -- still ships in the same file, flagged `in_set = 0`, and
the UI draws it as a grey x it can toggle on. D52 removes ~81k MN+BK records
citywide; a filter that large has to be inspectable by eye, and a supply
decision the owner cannot see is a supply decision he cannot overrule. The
sidebar/legend "known locations" count is the IN-SET count only, so the number
on screen is the number the gaps were measured against.

Per-category files, not one big file: the UI only ever draws one category at a
time, so the browser should only ever fetch one category. The largest single
file (Brooklyn laundry gaps) is ~1 MB uncompressed and the server gzips it;
nothing here needs a tile pipeline.

CORROBORATION (CHECKPOINT D47). D47 found that single-source POI records
inflate apparent supply -- an uncorroborated Overture row can erase a real gap.
`analysis.poi_dedup` records source membership only as `cluster_id`, so the
flag is derived: a cluster backed by 2+ DISTINCT `staging.poi.source_id` values
is corroborated. Two rows from the SAME source in one cluster are NOT
corroboration -- that is one source double-listing a place, which is exactly
the failure mode dedup exists to collapse. The UI draws single-source points
hollow so the owner can see, per point, whether the supply that closes a gap is
actually attested twice.

RESTAURANT DETAIL. DOHMH's inspection file is the only source here with
per-record attributes worth showing (cuisine, letter grade, inspection date,
and a derived active flag), and it covers exactly two categories -- restaurant
and cafe_bakery -- so `DETAIL_CATS` is READ FROM THE DB rather than hardcoded:
if DOHMH ever stops covering cafes, the export follows without an edit. Detail
is attached per dedup CLUSTER: a canonical Overture row and the DOHMH row that
dedup collapsed into it are the same restaurant, so the grade belongs to the
canonical point. Where a cluster has several DOHMH members the most recently
inspected one wins. Where it has none the DOHMH fields stay null and cuisine
falls back to Overture's `primary_category` / Foursquare's `labels` leaf,
LABELLED WITH ITS SOURCE -- an Overture "pizza_restaurant" is a taxonomy
string, not a health-department cuisine code, and the popup says so.

The detail rides in dictionary-encoded parallel arrays (`layer["detail"]`,
indexed by point) rather than per-feature objects: restaurant.json holds 40k
points, and a repeated `{"cuisine": "Coffee/Tea", ...}` per point would roughly
triple the file. Only DETAIL_CATS files carry a `detail` block at all, so the
other thirteen categories are byte-identical to before.

ALCOHOL OVERLAY (owner decision 2026-09-08). A THIRD file,
`alcohol.json`, holds every active NYS SLA licence in the exported boroughs,
classified on-premises / off-premises-liquor / off-premises-beer / other /
unknown by sources/cities/nyc/alcohol_licences.yaml. It is deliberately
separate from both layers above and from all 15 categories: the overlay
answers "where is alcohol licensed?", not "what is missing?", and 8,253 of
those NYC licences are restaurants DOHMH already anchors. Mixing it into a
category file would double-count supply. The table it reads
(`staging.alcohol_licences`, sql/007) is OPTIONAL -- an export run before
`loci ingest-alcohol` writes an empty layer and says so, rather than failing
the whole export.

ALL OPPORTUNITIES, ONE NEIGHBORHOOD (owner request 2026-09-09). A FOURTH set
of files, `nta/<nta_code>.json` plus `nta/index.json`, answers the inverse of
the question above: not "where is laundry missing" but "what is missing HERE".
One file per NTA holds every address in it that is beyond reach of at
least one category, with the whole missing list per address, and its own
known-location block for all fifteen categories. It is a PRESENTATION layer
over the same `analysis.address_gaps` rows -- same `ratio > 1` test, same
supply set, same provenance -- scoped to a neighborhood because 177k MN+BK
addresses drawn at once is not a question anyone asked. See the block above
`NTA_DIR` for the packing.

DEVELOPMENT PIPELINE (owner request 2026-09-09). A FIFTH file,
`pipeline.json`, holds one point per DOB job of >= 50 net units from
`analysis.dev_pipeline` (sql/011). Like alcohol it is an OVERLAY, not a 16th
category: the business selector never touches it and switching it on cannot
move a gap dot. Unlike alcohol it is also the source of an ANNOTATION on the
gap layer -- `units_permitted_400m`, `units_completed_24mo_400m` and the
nearest large project ride in every gap layer, because pipeline exposure is
what turns "this block is short a laundromat" into "this block is short a
laundromat and 600 homes are being framed two streets away".

  >= 50 units is a QUERY filter, never an ingest filter (sql/011 caveat 4):
  analysis.dev_pipeline holds every job with a unit change, including the
  demolitions and the 3-unit conversions, and the map draws the ones a leasing
  decision would be made against.

  FILED AND WITHDRAWN ARE NOT DRAWN. A filing is a developer's wish, not a
  pipeline, and 259 MN+BK jobs were permitted and then withdrawn. The overlay
  therefore carries `permitted`, `partially_complete`, and `complete` WITH A CO
  IN THE LAST 60 MONTHS -- coming, and recently arrived. A 2013 completion is
  neither.

  The nearest-large-project columns on the gap layer are model output and CAN
  name a filed job (54k MN+BK addresses have one), so the popup labels the
  stage and says when the project it names is not on the overlay. Silently
  showing a job the map refuses to draw is how a filing becomes a tower in
  someone's head.

VACANT STOREFRONTS (owner request 2026-09-10). A SIXTH file,
`storefronts.json`, holds one point per PREMISES reported vacant in the
storefront-registry snapshot (`analysis.storefront`, sql/012). Like alcohol and
the pipeline it is an OVERLAY, never a 16th category, and like the pipeline it
also annotates the gap layer -- `vacant_storefronts_400m`, its denominator
`storefronts_400m`, and the nearest vacant storefront ride in every gap layer,
because an empty ground floor 120 m from a laundry gap is the difference
between "a category is missing here" and "here is the door".

  ONE FILING, NEVER POOLED. Five of the eleven DOF filings contain ONLY
  storefronts reported vacant, and two filings can observe the same 12/31 (the
  2025-06-03 annual and the 2025-02-15 supplement both observe 2024-12-31).
  Selecting on the observation date alone counts those storefronts twice and
  lifts the MN+BK vacancy rate from 9.94% to 13.79%. The overlay therefore
  reads the SINGLE filing `model/storefronts.snapshot_filing` picks -- the same
  function the address measures use, imported rather than restated, so the map
  and the model cannot disagree about which rows exist.

  ONE POINT PER PREMISES, NOT PER STOREFRONT. `storefront_id` renumbers between
  filings (sql/012's identity block); `premises_id` does not. A premises with
  four vacant storefronts is ONE empty building on a map, and drawing four
  coincident marks would read as four buildings. The count of vacant
  storefronts at the premises rides in the popup instead.

  THE DENOMINATOR IS PART OF THE LAYER. "No vacant storefront near here" and
  "nobody near here filed" are the same observation in a self-reported registry
  (sql/012 caveat 1), so every count ships beside the registered-storefront
  total for the same filing and the legend prints both. A rate over a tiny
  denominator is not a rate.

  PRIOR USE IS A PREMISES-LEVEL QUERY, NOT THE ROW'S OWN COLUMN.
  `primary_business_activity` on a vacant row is necessarily
  "NO BUSINESS ACTIVITY IDENTIFIED" (caveat 7b), so the model column of that
  name is deliberately NOT exported; the popup shows the ARG_MAX over earlier
  filings at premises level that sql/012's header documents, and says "unknown"
  for the 16% with none.

AGE FIT (D63/D64/D69, close-out 2026-09-11). NO NEW FILE -- a SECOND RANKING
COLUMN on the gap layer. `gap_score` is the screen's own output; `gap_score_fit
= gap_score * age_fit_lead` sits BESIDE it, and the map offers a toggle between
the two orderings for the categories that have a live curve. It is never a
filter: the same addresses are drawn either way, in a different order.

  NULL IS A VALUE HERE, AND SO IS 1.0. Eleven of the fifteen categories have no
  curve. `age_fit_lead IS NULL` means "never applied"; `1.0` with a NULL MOE
  and a NULL source means "applied, but this address's LEAD category has no
  curve, so the identity multiplier was used". Neither is "fitted, and neutral"
  -- a claim the model never made. The block therefore rides in parallel arrays
  where JSON `null` survives, not in `pts`, it carries the lead category's
  `age_fit_source` as the discriminator, and the UI draws a point with no
  fitted curve as UNRANKED rather than as mid-scale.

  THE MULTIPLIER NEVER RENDERS WITHOUT ITS MOE. Childcare's F4 band is three
  times bar's (Borough Park 2.306 +/- 0.811 against East Village 0.718 +/-
  0.120, D69), so `age_fit_lead_moe` travels with the value everywhere, and the
  popup prints the +/- whenever the value is non-null.

  THE CAVEAT IS CARRIED VERBATIM, NOT PARAPHRASED. `age_fit_caveat()` returns
  model/age_fit.AGE_FIT_DISCLAIMER unchanged and meta.json carries it; the UI
  renders it UNTRUNCATED behind a one-line "supply-revealed; see caveat"
  expander -- the same rule `demand_caveat_text` carries (D49/D57). The curve is
  fitted on where the category's supply ALREADY is, so a low multiplier is
  never evidence that a neighbourhood does not want the service.

  LIVE MEANS A FILE ON DISK. `data/interim/age_fit_<category>.json` is written
  only by a fit that passed its own F2/F3 gate, and D69 retired pharmacy's by
  MOVING the stale JSON out of that directory. The meta block lists exactly the
  categories with a file, each one's fit timestamp and the supply hash it was
  estimated on, and warns when that hash disagrees with the gaps'.

BOROUGH. `analysis.address_gaps.borough` carries two-letter codes ("MN");
`analysis.hex.borough` carries full names ("Manhattan"). POIs have no borough
column at all, so they are labelled the same way the address layer labels
`nta_code`: H3 res-9 cell -> `analysis.hex`. `BOROUGH_NAMES` below is the only
bridge between the two vocabularies.
"""
from __future__ import annotations

import datetime
import json
import pathlib

from loci.categories import CATEGORIES
from loci.reach import load_reach
from loci.score.access import DIST_LIMIT
from loci.score.supply import DEFAULT_SUPPLY_SET, SUPPLY_SETS, SUPPLY_VIEW, supply_predicate

ALLCATS: list[str] = list(CATEGORIES)

# The only NYC-specific table in this module. address_gaps speaks codes,
# analysis.hex speaks names; the CLI takes codes.
BOROUGH_NAMES = {"MN": "Manhattan", "BX": "Bronx", "BK": "Brooklyn",
                 "QN": "Queens", "SI": "Staten Island"}

# Same palette the hex exporter and index.html already use -- kept in sync by
# hand in exactly these two places (viz/export_webmap.py and here).
COLORS = {"hardware": "#b5541f", "convenience": "#2f7d5c", "clinic": "#3d6fb4",
          "fitness": "#c69a1e", "childcare": "#9350a6", "laundry": "#1f9aa1",
          "pharmacy": "#cc4b63", "hair_barber": "#6d8b3a", "cafe_bakery": "#8a6d4b",
          "grocery": "#417a2f", "nails_beauty": "#b3689a", "bar": "#7a5cc0",
          "bank": "#4a7a8c", "tailor_repair": "#996a3a", "restaurant": "#a8443c",
          # bathhouse_sauna (GTM-198): chosen as the hex with the largest
          # minimum Lab distance from the other 15 (dE76 27.2, nearest
          # childcare); re-validate the pair set in dark mode before publishing.
          "bathhouse_sauna": "#c02f8f",
          # brewery (D137, 2026-09-22): chosen the same way -- largest minimum
          # Lab distance from the other 16 (dE76 33.7, nearest fitness);
          # re-validate in dark mode before publishing. webmap/index.html
          # carries the SAME palette by hand (this module's own header note)
          # and needs this entry added too -- NOT done here, a peer session
          # holds that file uncommitted.
          "brewery": "#abc431"}

H3_RES = 9
COORD_DP = 5  # ~1 m at NYC latitude; halves the JSON size vs full float repr

# The alcohol overlay's own table and its draw order (legend order too). The
# classification vocabulary and its labels live with the adapter that produces
# them, so the map legend cannot drift from the ingest.
ALCOHOL_TABLE = ("staging", "alcohol_licences")

# ------------------------------------------------------- development pipeline
# The overlay's table and the three thresholds that define what it draws. All
# three are QUERY filters (sql/011 caveat 4) -- the table itself holds every
# job, demolitions included, and narrowing here is reversible by editing one
# constant rather than re-ingesting.
PIPELINE_TABLE = ("analysis", "dev_pipeline")
PIPELINE_MIN_UNITS = 50           # "large project", same threshold as model/dev_pipeline.LARGE_UNITS
PIPELINE_COMPLETE_MONTHS = 60     # a CO older than this is history, not pipeline
#: Drawn stages. `filed` is a developer's wish and `withdrawn` is attrition;
#: neither is a home anyone will live in, so neither reaches the map.
PIPELINE_MAP_STAGES = ("permitted", "partially_complete", "complete")
PIPELINE_STAGE_LABELS = {
    "permitted": "Permitted / under construction",
    "partially_complete": "Partially complete",
    "complete": f"Completed (last {PIPELINE_COMPLETE_MONTHS // 12} years)",
}
#: Size bands, as (low, high) with an open top. Stored in the file so the UI
#: sizes its marks from the SAME edges the dry-run counts against.
PIPELINE_BANDS = ((PIPELINE_MIN_UNITS, 99), (100, 299), (300, None))
PIPELINE_BAND_LABELS = ("50–99 homes", "100–299 homes", "300+ homes")
#: Certificate-of-occupancy state, drawn as fill vs hollow ring. `none` is a
#: job with no CO evidence at all, which for a permitted job is the norm --
#: it is NOT "temporary", and the two must not share a mark.
PIPELINE_CO = ("final", "temporary", "none")

#: The pipeline columns (model/dev_pipeline.PIPELINE_COLUMNS) this export
#: carries onto EVERY gap layer, per address.
PIPELINE_GAP_COLUMNS = [
    "units_permitted_400m", "units_completed_24mo_400m",
    "nearest_large_project_id", "nearest_large_project_m",
    "nearest_large_project_units", "nearest_large_project_stage",
    "nearest_large_project_date",
]
#: ...and the ones deliberately left out, each with the reason. Together with
#: PIPELINE_GAP_COLUMNS these must EXACTLY cover PIPELINE_COLUMNS -- the drift
#: test in tests/test_webmap_export.py pins it, so a thirteenth column added to
#: the model forces a decision here instead of quietly never shipping.
PIPELINE_NOT_EXPORTED = {
    "units_permitted_800m": "the map's pipeline reading is the 5-minute tier; "
                            "a second radius per address doubles the bytes to answer "
                            "the same question less sharply",
    "units_completed_24mo_800m": "same reason as units_permitted_800m",
    "units_completed_60mo_400m": "the 24mo window is the one that is not yet in ACS; "
                                 "60mo is on the overlay as drawn completions instead",
    "units_completed_60mo_800m": "same reason as units_completed_60mo_400m",
    "pipeline_asof": "one date for the whole run -- carried once in meta.json and "
                     "once per layer, never 267k times",
    "units_active_400m": "NOT YET DECIDED, deliberately deferred. The construction-"
                         "progress split (sql/014) belongs on the PIPELINE OVERLAY, "
                         "not on the gap layer: the useful map change is colouring "
                         "the existing dev_pipeline dots by activity_status so a "
                         "permitted-and-stalled tower reads differently from a "
                         "permitted-and-building one, which costs one extra packed "
                         "field on that layer and nothing on the 267k gap addresses. "
                         "Landing it here instead would ship the number without the "
                         "picture that makes it legible.",
    "units_stalled_400m": "same reason as units_active_400m -- style the overlay by "
                          "activity_status first, then decide whether the gap layer "
                          "needs the per-address totals at all",
}

# ----------------------------------------------------------- vacant storefronts
# The overlay's table and the bands the symbol encodes. Both are QUERY choices
# over analysis.storefront (sql/012), which keeps every filing: narrowing here
# is one constant, not a re-ingest.
STOREFRONT_TABLE = ("analysis", "storefront")
#: Consecutive 12/31 observations, counting back from the snapshot year, in
#: which at least one storefront at the premises was reported vacant. Two bands
#: because the map draws two: a first-year vacancy is churn, a second is a
#: building that is not letting. Open top, same (lo, hi) shape as
#: PIPELINE_BANDS so the UI reads its edges out of the file.
STOREFRONT_YEAR_BANDS = ((1, 1), (2, None))
STOREFRONT_YEAR_LABELS = ("Vacant at the last count", "Vacant 2+ consecutive years")
#: DOF's own two ways of saying "nothing trades here". Both are the ABSENCE of
#: a prior use, and neither is a prior use -- the popup says "unknown".
NO_ACTIVITY = ("NO BUSINESS ACTIVITY IDENTIFIED", "NO BUSINESS ACTIVITY REPORTED")

#: The storefront columns (model/storefronts.STOREFRONT_COLUMNS) this export
#: carries onto EVERY gap layer, per address.
STOREFRONT_GAP_COLUMNS = [
    "vacant_storefronts_400m", "storefronts_400m",
    "nearest_vacant_storefront_m", "nearest_vacant_storefront_id",
    "nearest_vacant_lease_expired",
]
#: ...and the ones deliberately left out, each with the reason. Together with
#: STOREFRONT_GAP_COLUMNS these must EXACTLY cover STOREFRONT_COLUMNS -- the
#: drift test in tests/test_webmap_export.py pins it, so an eighth column added
#: to the model forces a decision here instead of quietly never shipping.
STOREFRONT_NOT_EXPORTED = {
    "nearest_vacant_storefront_business":
        "on a VACANT row this column is the constant 'NO BUSINESS ACTIVITY "
        "IDENTIFIED' (sql/012 caveat 7b), so shipping it per address would print "
        "that phrase 280k times and say nothing; the popup shows the PREMISES-level "
        "prior use from sql/012's documented ARG_MAX instead, carried once per "
        "referenced storefront in each layer's `vacants` dictionary",
    "storefront_asof":
        "one observation date for the whole run -- carried once in meta.json and "
        "once per layer, never 267k times",
}
#: The catchment the `*_400m` columns were computed over. Written here rather
#: than imported because loci.score.access pulls in osmnx and scipy and this
#: module must stay importable without them; a test pins it to THRESHOLDS[5] so
#: the two cannot drift. Only a legend label -- nothing here recomputes it.
STOREFRONT_RADIUS_M = 400
#: Network metres to the nearest vacant storefront, rounded like NEAR_M_ROUND.
#: Held separately only so a later decision to draw this one finer does not
#: silently re-scale the pipeline's distances too.
VACANT_M_ROUND = 10

# ---------------------------------------------------------------- age fit
# D63/D64/D69. `age_fit_lead` is a SUPPLY-REVEALED multiplier on the LEAD
# category's gap score, fitted on where that category's supply already sits
# relative to resident age. It is a SEPARATE RANKING COLUMN and NEVER a filter:
# `gap_score` is still the screen's own output, `gap_score_fit = gap_score *
# age_fit_lead` sits beside it, and no address is added to or removed from the
# gap layer by either number.
#
# THREE THINGS THIS EXPORT MUST NOT DO, each of which was a live risk:
#
#  (a) TURN NULL INTO 1.0. Eleven of the fifteen categories have no curve at
#      all, and `age_fit_lead IS NULL` means "this category was never fitted".
#      1.0 means "fitted, and the curve says neutral" -- a claim the model
#      never made. So these ride in their OWN arrays, parallel to `pts`, where
#      a JSON `null` survives; a stride slot cannot carry one, because every
#      reader of `pts` expects a number and would coerce it to zero.
#
#  (b) RENDER A MULTIPLIER WITHOUT ITS MOE. Childcare's F4 ordering clears with
#      a band THREE TIMES bar's (Borough Park 2.306 +/- 0.811 against East
#      Village 0.718 +/- 0.120), so `age_fit_lead_moe` travels with
#      `age_fit_lead` in the file and in the popup, always (D69).
#
#  (c) SHIP THE NUMBER WITHOUT THE CAVEAT. `age_fit_caveat()` is
#      model/age_fit.AGE_FIT_DISCLAIMER verbatim, carried once in meta.json and
#      rendered UNTRUNCATED by the UI -- the same rule `demand_caveat_text`
#      already carries (D49/D57).
#
#: The analysis.address columns model/age_fit.py writes, in its own order. A
#: drift test pins this to age_fit.ADDRESS_AGE_FIT_COLUMNS, so a fourth column
#: added there forces a decision here instead of quietly never shipping.
AGE_FIT_GAP_COLUMNS = ["age_fit_lead", "age_fit_lead_moe", "gap_score_fit"]

#: What a street-frame dot means, in the UI's own words. Rendered on every
#: street point's popup and in the layer toggle's help, because the one thing a
#: reader must not do is read a street dot as an address: it has no residents,
#: no tax lot and therefore no feasibility reading, and its rank score is a
#: statement about what is within a walk of a piece of street, not about anyone
#: who lives there.
STREET_FRAME_CAVEAT = (
    "Street point — no residential lot here. This dot is a sample of the street "
    "itself (one point every 100 m of centerline), not a building: nobody lives at "
    "it, it has no tax lot, and no floor-area or feasibility reading. It is on the "
    "map because a street with no residents yet would otherwise be invisible to a "
    "screen built from residents."
)


#: The D75 right-censoring flags on analysis.address_gaps. The first is
#: per-CATEGORY and its name depends on the layer (`{cat}_censored`), so this
#: list names only the address-grain one; `_gap_sql` builds the pair.
CENSORED_GAP_COLUMNS = ["lead_censored"]
#: The Dijkstra cap those flags mean, in metres. Imported from score/access
#: (which model/address_gaps re-exports as CAP_M), never re-declared, so the
#: map and the screen can never disagree about what "beyond" means.
GAP_CAP_M = DIST_LIMIT
#: `age_fit_source` is PER CATEGORY (analysis.address_category), not per
#: address, so the lead category's value is joined in rather than read off the
#: address_gaps view -- which deliberately does not pivot 30 mostly-NULL
#: per-category columns. A database with no address_category (or one predating
#: the column) exports `null` and the meta block says the join was skipped.
AGE_FIT_SOURCE_TABLE = ("analysis", "address_category")
AGE_FIT_SOURCE_COLUMN = "age_fit_source"
#: Where `loci age-fit fit` writes its curves. Held as a literal rather than
#: imported because model/age_fit.py pulls in osmnx (via model/address_gaps)
#: and this module must stay importable without it; a drift test pins the two.
AGE_FIT_DIR = pathlib.Path(__file__).resolve().parents[3] / "data" / "interim"
AGE_FIT_GLOB = "age_fit_*.json"
#: The multiplier and its MOE both sit in roughly [0.5, 2.0] and the popup
#: prints two decimals, so three is one more than anything is read at.
AGE_FIT_DP = 3
#: gap_score / gap_score_fit rounding on the gap layer. Deliberately identical
#: to the all-opportunities layer's SCORE_DP -- one score, two views, and a
#: test pins them equal so a change in one cannot quietly rescale the other.
GAP_SCORE_DP = 3

# DOHMH is the detail source; the two cuisine-ish fallbacks each store their
# taxonomy under a different attrs key, so the extraction is per source.
DOHMH_SOURCE = "nyc_dohmh_restaurants"
CUISINE_FALLBACK = {  # source_id -> JSON path, in preference order
    "overture_places": "$.primary_category",
    "foursquare_os_places": "$.labels[0]",
}


# ------------------------------------------------------------------ queries

def detail_cats(con) -> list[str]:
    """The categories DOHMH actually covers, read from the data (restaurant +
    cafe_bakery today). Only these get a `detail` block."""
    rows = con.execute(
        "SELECT DISTINCT category FROM staging.poi WHERE source_id = ?",
        [DOHMH_SOURCE]).fetchall()
    return [c for c in ALLCATS if c in {r[0] for r in rows}]


def _poi_sql(boroughs: list[str], dcats: list[str],
             supply_set: str = DEFAULT_SUPPLY_SET) -> tuple[str, list]:
    """Canonical POIs in `boroughs` (two-letter codes) with a derived source
    list. `list_sort(list(DISTINCT ...))` gives a stable source ordering so a
    re-export of unchanged data is byte-identical.

    Rows come from `SUPPLY_VIEW` (`analysis.poi_supply_status`, D98/GTM-170 --
    `analysis.poi_supply` plus the closure-evidence-gated `poi_status`/
    `poi_status_basis` columns; it already filters `is_canonical`, exactly as
    `analysis.poi_supply` did), and the named supply set rides along as
    `in_set` rather than being applied as a WHERE clause: the excluded points
    are drawn as their own class, so the export needs them. `supply_predicate`
    is the same function model/address_gaps.py uses, so the map and the model
    cannot drift apart over what "a business exists here" means.

    An EVIDENCED closure (`poi_status = 'closed'`) is excluded outright --
    never `= 'open'`, because `poi_status` is TRI-STATE and 'unknown' (most of
    the universe; Overture/OSM/Foursquare's open cache/USDA SNAP publish no
    status at all) must still be drawn (score/supply.py's GATE_CLOSED
    caveat). `poi_status`/`poi_status_basis` ride along in the SELECT so a
    caller can see WHY a still-drawn point reads open/unknown.

    The two detail CTEs are restricted to `dcats` on purpose: every Overture
    row has a `primary_category`, so an unrestricted cuisine fallback would
    hang "Grocery Store" off every grocery point and bloat all 15 files.
    """
    pred = supply_predicate(supply_set)
    names = [BOROUGH_NAMES[b] for b in boroughs]
    placeholders = ", ".join("?" for _ in names)
    dcat_ph = ", ".join("?" for _ in dcats) or "NULL"
    fb_when = "\n".join(
        f"WHEN '{sid}' THEN json_extract_string(p.attrs, '{path}')"
        for sid, path in CUISINE_FALLBACK.items())
    fb_rank = "\n".join(
        f"WHEN '{sid}' THEN {i}" for i, sid in enumerate(CUISINE_FALLBACK))
    sql = f"""
        WITH src AS (
            SELECT d.cluster_id,
                   list_sort(list(DISTINCT p.source_id)) AS sources
            FROM analysis.poi_dedup d
            JOIN staging.poi p ON p.poi_id = d.poi_id
            GROUP BY 1
        ),
        dohmh AS (
            SELECT * EXCLUDE (rn) FROM (
                SELECT d.cluster_id,
                       p.source_record_id AS camis,
                       json_extract_string(p.attrs, '$.cuisine') AS cuisine,
                       json_extract_string(p.attrs, '$.grade') AS grade,
                       json_extract_string(p.attrs, '$.grade_date') AS grade_date,
                       json_extract_string(p.attrs, '$.last_inspection_date') AS inspected_on,
                       json_extract_string(p.attrs, '$.active') AS active,
                       json_extract_string(p.attrs, '$.active_basis') AS active_basis,
                       row_number() OVER (
                           PARTITION BY d.cluster_id
                           ORDER BY json_extract_string(p.attrs, '$.last_inspection_date')
                                    DESC NULLS LAST, p.source_record_id) AS rn
                FROM analysis.poi_dedup d
                JOIN staging.poi p ON p.poi_id = d.poi_id
                WHERE p.source_id = '{DOHMH_SOURCE}'
                  AND d.category IN ({dcat_ph})
            ) WHERE rn = 1
        ),
        fb AS (
            SELECT * EXCLUDE (rn) FROM (
                SELECT cluster_id, fb_cuisine, fb_source,
                       row_number() OVER (PARTITION BY cluster_id
                                          ORDER BY pref, poi_id) AS rn
                FROM (
                    SELECT d.cluster_id, p.poi_id, p.source_id AS fb_source,
                           CASE p.source_id
                               {fb_when}
                           END AS fb_cuisine,
                           CASE p.source_id
                               {fb_rank}
                           END AS pref
                    FROM analysis.poi_dedup d
                    JOIN staging.poi p ON p.poi_id = d.poi_id
                    WHERE d.category IN ({dcat_ph})
                )
                WHERE fb_cuisine IS NOT NULL
            ) WHERE rn = 1
        )
        SELECT v.poi_id,
               v.category,
               v.name,
               round(ST_X(v.geom), {COORD_DP}) AS lon,
               round(ST_Y(v.geom), {COORD_DP}) AS lat,
               h.borough AS borough_name,
               s.sources,
               dh.camis, dh.cuisine, dh.grade, dh.grade_date, dh.inspected_on,
               dh.active, dh.active_basis,
               f.fb_cuisine, f.fb_source,
               v.{pred} AS in_set,
               v.poi_status, v.poi_status_basis
        FROM {SUPPLY_VIEW} v
        JOIN src s ON s.cluster_id = v.cluster_id
        LEFT JOIN dohmh dh ON dh.cluster_id = v.cluster_id
        LEFT JOIN fb f ON f.cluster_id = v.cluster_id
        JOIN analysis.hex h
          ON h.h3_index = h3_latlng_to_cell_string(ST_Y(v.geom), ST_X(v.geom), {H3_RES})
        WHERE h.borough IN ({placeholders})
          AND v.category IN ({", ".join("?" for _ in ALLCATS)})
          AND v.poi_status <> 'closed'
        ORDER BY v.category, v.poi_id
    """
    return sql, list(dcats) + list(dcats) + names + ALLCATS


def _gap_sql(cat: str, boroughs: list[str], pipeline: bool = True,
             storefront: bool = True, age_fit: bool = True,
             age_source: bool = True, censoring: bool = True,
             frame: bool = True) -> tuple[str, list]:
    """Addresses whose `cat` is beyond its reach tier (ratio > 1) --
    model/address_gaps.py's own `n_missing` definition, one category at a
    time. NO eligibility filter: the gate is retired (D75, owner ruling) and
    every address is in the universe, so `WHERE g.eligible` is gone rather
    than left in as a no-op that a future reader would take for a rule.

    `pipeline` selects the seven PIPELINE_GAP_COLUMNS, `storefront` the five
    STOREFRONT_GAP_COLUMNS and `age_fit` the three AGE_FIT_GAP_COLUMNS. All
    three are NULL-safe here on purpose: a database whose `loci pipeline`,
    `loci storefronts` or `loci age-fit apply` has not run still exports, it
    just exports zeros and no nearest project or vacancy, and no multiplier,
    and the UI hides the reading rather than printing a confident "0 homes
    coming" / "no empty storefront anywhere" / a neutral 1.0 age fit.

    `age_source` adds the LEFT JOIN that fetches the lead category's
    `age_fit_source`; it is skipped when analysis.address_category does not
    carry the column, and the meta block records that it was.

    `censoring` adds the two D75 flags, APPENDED after the ranking block:
    this layer's own `{cat}_censored` and the address's `lead_censored`. They
    are what lets the popup say "beyond 2,400 m -- distance not measured"
    rather than printing the Dijkstra cap as if it were a measured walk. Same
    NULL-safe contract as the blocks above: a database written before D75
    exports NULLs and the UI says nothing."""
    placeholders = ", ".join("?" for _ in boroughs)
    pipe = (", " + ", ".join(f"g.{c}" for c in PIPELINE_GAP_COLUMNS)) if pipeline else \
           ", " + ", ".join("NULL" for _ in PIPELINE_GAP_COLUMNS)
    # APPENDED after the pipeline block, never inserted: every tail is read by
    # position from its own end.
    shop = (", " + ", ".join(f"g.{c}" for c in STOREFRONT_GAP_COLUMNS)) if storefront else \
           ", " + ", ".join("NULL" for _ in STOREFRONT_GAP_COLUMNS)
    # ...and the D63/D69 ranking tail after that, in the same appended spirit.
    # `gap_score` and `lead_category` lead it because the age-fit reading is
    # meaningless without them: gap_score is what the multiplier multiplies,
    # and lead_category is WHOSE curve it is -- in `gaps/laundry.json` an
    # address's age_fit_lead can belong to `bar`, and a popup that did not say
    # so would attribute one category's curve to another.
    age = (", " + ", ".join(f"g.{c}" for c in AGE_FIT_GAP_COLUMNS)) if age_fit else \
          ", " + ", ".join("NULL" for _ in AGE_FIT_GAP_COLUMNS)
    src = f", ac.{AGE_FIT_SOURCE_COLUMN}" if age_source else ", NULL"
    cens = (f", g.{cat}_censored, g.lead_censored") if censoring else ", NULL, NULL"
    # D84: the SAMPLING FRAME, APPENDED after the censoring pair, same rule as
    # every block above -- every tail is read by position from its own end. A
    # 'street' row is a point on a street with NO residential lot under it: no
    # residents, no BBL, no feasibility reading, units 0. The map must be able
    # to say so, and must be able to hide the 26k of them by default, or the
    # gap layer silently grows 17% of dots that mean something different from
    # every other dot on it.
    join = f"""
        LEFT JOIN {'.'.join(AGE_FIT_SOURCE_TABLE)} ac
               ON ac.address_id = g.address_id
              AND ac.borough = g.borough
              AND ac.category = g.lead_category
    """ if age_source else ""
    frm = (", COALESCE(g.frame, 'lot') AS frame, g.frontage_m, g.street_name"
           if frame else ", 'lot' AS frame, NULL, NULL")
    sql = f"""
        SELECT g.address_id,
               round(g.lon, {COORD_DP}) AS lon,
               round(g.lat, {COORD_DP}) AS lat,
               g.borough,
               g.units_capped,
               g.{cat}_ratio AS ratio,
               g.{cat}_nearest_m AS nearest_m,
               g.neighborhood
               {pipe}
               {shop}
               , g.gap_score, g.lead_category {age} {src} {cens}
               {frm}
               , g.nta_code
        FROM analysis.address_gaps g
        {join}
        WHERE g.borough IN ({placeholders})
          AND g.{cat}_ratio > 1
        ORDER BY g.address_id
    """
    return sql, list(boroughs)


# ------------------------------------------------------------------ packing

def normalize_cuisine(value: str | None, source: str) -> str | None:
    """Reduce a fallback taxonomy string to something that reads like a
    cuisine, so it can share a dropdown with DOHMH's vocabulary.

    Overture: `pizza_restaurant` -> `Pizza`. Foursquare:
    `Dining and Drinking > Restaurant > Indian Restaurant` -> `Indian`.
    A bare `restaurant` / `Restaurant` carries no cuisine and becomes None --
    better an honest blank than a category named after itself.
    """
    if value is None or source == DOHMH_SOURCE:
        return value or None
    text = value.split(">")[-1].strip().replace("_", " ")
    for tail in (" restaurant", " place", " shop", " store"):
        if text.lower().endswith(tail):
            text = text[: -len(tail)]
    text = text.strip()
    if not text or text.lower() in {"restaurant", "dining and drinking", "food and beverage"}:
        return None
    return text.title() if text.islower() else text


class _Vocab:
    """Dictionary encoder: a repeated string becomes one small integer."""

    def __init__(self) -> None:
        self.items: list[str] = []
        self._idx: dict[str, int] = {}

    def index(self, value: str | None) -> int:
        if value is None or value == "":
            return -1
        i = self._idx.get(value)
        if i is None:
            i = self._idx[value] = len(self.items)
            self.items.append(value)
        return i


def pack_pois(rows, boroughs: list[str], sources: list[str],
              dcats: list[str] | None = None,
              supply_set: str = DEFAULT_SUPPLY_SET) -> dict[str, dict]:
    """rows -> {category: layer dict}. `pts` is a flat array of stride 5:
    lon, lat, borough index, source bitmask, in_set. Names and ids ride in
    parallel arrays so the numeric part stays a dense list of numbers.

    A point is corroborated iff popcount(source bitmask) >= 2 (D47).

    `in_set` is 1 when the point belongs to the named supply set and 0 when it
    was EXCLUDED from it (D52). It is a fifth slot in the same flat array
    rather than a parallel array so there is exactly one place a reader can
    get a point's numbers wrong; the UI reads `layer["stride"]`, never a
    literal 4.

    For `dcats` (the DOHMH-covered categories) each layer also gets `detail`:
    dictionary-encoded parallel arrays, one entry per point, holding cuisine,
    letter grade, grade date, last inspection date, the active flag and its
    basis, and the DOHMH CAMIS id so a point can be traced back to the
    inspection file. `active` is 1/0/-1 -- and -1 (no DOHMH member in the
    cluster) is NOT "inactive": the UI must not hide it as one.
    """
    dcats = list(dcats or [])
    bidx = {b: i for i, b in enumerate(boroughs)}
    sidx = {s: i for i, s in enumerate(sources)}
    out = {c: {"category": c, "label": CATEGORIES[c].label, "stride": 5,
               "supplySet": supply_set, "pts": [], "names": [], "ids": []}
           for c in ALLCATS}
    vocabs = {c: {k: _Vocab() for k in ("cuisine", "grade", "basis", "date", "src")}
              for c in dcats}
    for c in dcats:
        out[c]["detail"] = {k: [] for k in ("cuisine", "cuisineSrc", "grade",
                                            "gradeDate", "inspected", "active",
                                            "basis", "camis")}
    for (poi_id, cat, name, lon, lat, boro_name, srcs, camis, cuisine, grade,
         grade_date, inspected_on, active, active_basis, fb_cuisine, fb_source,
         in_set, _poi_status, _poi_status_basis) in rows:
        # poi_status/poi_status_basis (D98/GTM-170) ride along in `_poi_sql`'s
        # SELECT for provenance and for the exclusion WHERE clause upstream --
        # a row reaching here has already survived `poi_status <> 'closed'`,
        # so the packed layer itself carries no new column yet (AC-14's search
        # card is the first consumer that will need it).
        layer = out.get(cat)
        if layer is None or lon is None or lat is None:
            continue
        code = _code_for(boro_name)
        if code not in bidx:
            continue
        mask = 0
        for s in srcs or []:
            mask |= 1 << sidx[s]
        layer["pts"].extend([lon, lat, bidx[code], mask, int(bool(in_set))])
        layer["names"].append(name or "")
        layer["ids"].append(poi_id)
        if cat not in vocabs:
            continue
        v, det = vocabs[cat], layer["detail"]
        # DOHMH's cuisine code wins; the taxonomy fallback fills the blanks and
        # is always labelled with the source it came from.
        cui_src = DOHMH_SOURCE if cuisine else (fb_source if fb_cuisine else None)
        cui = normalize_cuisine(cuisine or fb_cuisine, cui_src or DOHMH_SOURCE)
        det["cuisine"].append(v["cuisine"].index(cui))
        det["cuisineSrc"].append(v["src"].index(cui_src if cui else None))
        det["grade"].append(v["grade"].index(grade))
        det["gradeDate"].append(v["date"].index(grade_date))
        det["inspected"].append(v["date"].index(inspected_on))
        det["active"].append(-1 if active is None else int(active == "true"))
        det["basis"].append(v["basis"].index(active_basis))
        det["camis"].append(camis or "")
    for cat, v in vocabs.items():
        out[cat]["detail"]["vocab"] = {k: vv.items for k, vv in v.items()}
    for layer in out.values():
        layer["n"] = len(layer["names"])
        flags = layer["pts"][4::5]
        layer["nSet"] = sum(flags)              # the "known locations" count
        layer["nExcluded"] = len(flags) - layer["nSet"]
    return out


class _Projects:
    """Dictionary encoder for the nearest large project (D62).

    ~1,400 distinct DOB jobs stand behind 267k MN+BK addresses, so a project's
    id, units, stage and date are stored ONCE per file and each address stores
    a small integer. Written per-file rather than once globally because a gap
    file for one category references only the projects its own addresses are
    nearest to -- the vocabulary is then a few hundred entries, not 1,400.
    """

    def __init__(self) -> None:
        self.ids: list[str] = []
        self.units: list[int] = []
        self.stage: list[str] = []
        self.date: list[str] = []
        self._idx: dict[str, int] = {}

    def index(self, job_id, units, stage, date) -> int:
        if job_id is None or job_id == "":
            return -1
        i = self._idx.get(job_id)
        if i is None:
            i = self._idx[job_id] = len(self.ids)
            self.ids.append(job_id)
            self.units.append(int(units or 0))
            self.stage.append(stage or "")
            self.date.append("" if date is None else str(date)[:10])
        return i

    def pack(self) -> dict:
        return {"ids": self.ids, "units": self.units,
                "stage": self.stage, "date": self.date}


#: Network metres to the nearest large project, rounded. 10 m is finer than any
#: decision made off this map and saves two bytes on every address in every
#: gap file.
NEAR_M_ROUND = 10


def pipe_slots(projects: _Projects, tail) -> list[int]:
    """The four numbers every gap point carries, from a row's
    PIPELINE_GAP_COLUMNS tail: units permitted within 400 m, units completed in
    the last 24 months within 400 m, the nearest large project's index in
    `projects` (-1 = none), and the network metres to it (-1 = none).

    A NULL is packed as 0 units / -1 project, never as a missing slot: the flat
    array's stride has to hold whatever the model wrote, including nothing."""
    up, d24, pid, pm, punits, pstage, pdate = tail
    idx = projects.index(pid, punits, pstage, pdate)
    dist = -1 if (idx < 0 or pm is None) else int(round(float(pm) / NEAR_M_ROUND) * NEAR_M_ROUND)
    return [int(up or 0), int(d24 or 0), idx, dist]


class _Vacants:
    """Dictionary encoder for the nearest VACANT STOREFRONT (owner request 2026-09-10).

    Same trick as `_Projects` and for the same reason: ~2,750 vacant MN+BK
    premises stand behind 282k addresses, so a storefront's id, street address,
    prior use and lease state are stored ONCE per file and each address stores a
    small integer.

    Three of those four are properties of the STOREFRONT, not of the address,
    which is why `nearest_vacant_lease_expired` lives here rather than in a
    per-address slot: every address whose nearest vacancy is this storefront
    reads the same lease. It is 1 / 0 / -1 -- and -1 (the filing reported no
    lease, which is most of them on the 2024-12-31 snapshot, sql/012 caveat 5)
    is NOT "still running": the UI must not print it as one.
    """

    def __init__(self, detail: dict[str, tuple] | None = None) -> None:
        self.detail = detail or {}
        self.ids: list[str] = []
        self.addr: list[str] = []
        self.business: list[str] = []
        self.lease: list[int] = []
        self._idx: dict[str, int] = {}

    def index(self, storefront_id, lease_expired) -> int:
        if storefront_id is None or storefront_id == "":
            return -1
        i = self._idx.get(storefront_id)
        if i is None:
            addr, prior = self.detail.get(storefront_id, (None, None))
            i = self._idx[storefront_id] = len(self.ids)
            self.ids.append(storefront_id)
            self.addr.append(addr or "")
            # "" means the premises has no prior use anywhere in the file; the
            # UI prints "unknown", never a guessed category.
            self.business.append(prior or "")
            self.lease.append(-1 if lease_expired is None else int(bool(lease_expired)))
        return i

    def pack(self) -> dict:
        return {"ids": self.ids, "addr": self.addr,
                "business": self.business, "lease": self.lease}


def sf_slots(vacants: _Vacants, tail) -> list[int]:
    """The four numbers every gap point carries, from a row's
    STOREFRONT_GAP_COLUMNS tail: vacant storefronts within 400 m, EVERY
    registered storefront within 400 m (the denominator, without which zero
    vacancies and zero filings are the same number), the nearest vacant
    storefront's index in `vacants` (-1 = none) and the network metres to it
    (-1 = none).

    A NULL is packed as 0 / -1, never as a missing slot -- and 0 vacant beside 0
    registered is exactly the "nobody near here filed" state the denominator
    exists to make visible."""
    vac, total, near_m, near_id, lease = tail
    idx = vacants.index(near_id, lease)
    dist = -1 if (idx < 0 or near_m is None) else int(
        round(float(near_m) / VACANT_M_ROUND) * VACANT_M_ROUND)
    return [int(vac or 0), int(total or 0), idx, dist]


def _num(value, dp: int):
    """`round(value, dp)` that keeps NULL as None. The whole age-fit block
    turns on this: a missing multiplier is not 1.0 and a missing score is not
    0, and `float(None or 0)` is exactly how that distinction gets lost."""
    return None if value is None else round(float(value), dp)


class _AgeFit:
    """The D63/D69 age-fit ranking block for one gap layer.

    PARALLEL ARRAYS, NOT STRIDE SLOTS. `pts` is a flat numeric array whose
    every reader indexes by position and treats as numbers; a NULL multiplier
    dropped into it would arrive in the browser as 0 or 1 depending on who
    coerced it. These six arrays are indexed by the same point number and carry
    a literal JSON `null` where the model wrote nothing. They are null-dense
    for the eleven categories with no curve, which costs five bytes a point
    uncompressed and essentially nothing over the server's gzip -- a cheaper
    price than a sentinel that reads as a real value. On the largest file
    (gaps/bar.json, 105k points, every one of them fitted) the whole block
    costs 947 KB -> 1,089 KB over the wire.

    `source` is dictionary-encoded against `sources` because there is one
    `age_fit_source` per CURVE (`sla_composition_v1`, `poi_composition_v1`),
    not one per address.

    THREE STATES, AND THE UI MUST TELL THEM APART (sql/002's D63 block):

      value NULL                     nothing was ever applied -- a database
                                     predating `loci age-fit apply`.
      value 1.0, moe and source NULL the IDENTITY multiplier: the address's
                                     lead category has no fitted curve, so
                                     gap_score_fit == gap_score exactly. "No
                                     curve" is not "a curve with no
                                     uncertainty", which is why the MOE stays
                                     NULL here.
      value set, source set          a real curve. `moe` is then the band D69
                                     requires beside every rendered value.

    `source` is therefore the discriminator the UI keys on, and the reason this
    export joins address_category at all: a 1.0 with no source must never be
    drawn as "the age curve says this block is exactly average".
    """

    def __init__(self) -> None:
        self.score: list = []
        self.value: list = []
        self.moe: list = []
        self.score_fit: list = []
        self.lead: list = []
        self.source: list = []
        self.sources: list[str] = []
        self._idx: dict[str, int] = {}

    def add(self, tail) -> None:
        """One row's ranking tail: gap_score, lead_category, then the three
        AGE_FIT_GAP_COLUMNS in order, then the lead category's
        age_fit_source."""
        score, lead, value, moe, score_fit, source = tail
        self.score.append(_num(score, GAP_SCORE_DP))
        self.value.append(_num(value, AGE_FIT_DP))
        self.moe.append(_num(moe, AGE_FIT_DP))
        self.score_fit.append(_num(score_fit, GAP_SCORE_DP))
        # A lead category outside the fifteen is not a category this map can
        # name, so it reads as "no lead" rather than as a bad index.
        self.lead.append(ALLCATS.index(lead) if lead in CATEGORIES else None)
        self.source.append(None if not source else self._src(source))

    def _src(self, source: str) -> int:
        i = self._idx.get(source)
        if i is None:
            i = self._idx[source] = len(self.sources)
            self.sources.append(source)
        return i

    def pack(self) -> dict:
        return {"score": self.score, "value": self.value, "moe": self.moe,
                "scoreFit": self.score_fit, "lead": self.lead,
                "source": self.source, "sources": self.sources}


def pack_gaps(rows, boroughs: list[str], cat: str,
              vacant_detail: dict[str, tuple] | None = None,
              character_detail: dict[str, tuple] | None = None,
              legality_detail: dict[str, tuple] | None = None) -> dict:
    """rows -> one layer dict. `pts` stride 12: lon, lat, borough index,
    capped units, then the four pipeline slots (`pipe_slots`) and the four
    storefront slots (`sf_slots`). `ratio` is dropped from the payload
    deliberately -- the map shows presence/absence, and the continuous score is
    the model's output, not the map's.

    Both slot blocks are APPENDED, never inserted: every reader indexes 0..3 by
    position and a reordering here would silently relabel every dot.

    The D63/D69 ranking block does NOT ride in `pts` and does not move the
    stride -- see `_AgeFit` for why a NULL multiplier cannot live in a numeric
    stride slot. Nor does the D75 censoring block, for the same reason: its
    third state is "this file predates D75 and cannot say", which is a null,
    not a 0. It rides in `censoring` as two parallel arrays of 1/0/null --
    `cat`, this layer's category, and `lead`, the address's lead category --
    plus `capM`, the metres the flag means, so the UI never hard-codes 2400.

    The neighbourhood-character tint rides in `character` on the same terms and
    for the same reason (see `_Character`): an address the character build
    never reached has no label, and that null must survive the trip to the
    browser as a null.

    `nta` rides along the same way, one more parallel array and NOT a stride
    slot (owner 2026-09-16): single-business mode has no per-category
    neighbourhood scope of its own -- only "all opportunities" reads
    `nta/<code>.json` -- so `selectNta` on the per-category map was flying the
    camera and drawing every borough's dots regardless of the picked
    neighbourhood. `idx` is dictionary-encoded against `vocab` (NTA codes, the
    same key `ntaSel` holds in the JS and `META.neighborhoods` maps a picked
    name onto) rather than the name, because code is the honest 1:1 key and
    name<->code parity is only a comment's promise. A street-frame point (D84)
    gets its NTA the same way every lot does -- both are joined onto
    `analysis.hex` by the point's own H3 cell in model/address_gaps.py, not by
    frame -- but a row shorter than this column (a file built before this
    change) or an address whose cell never resolved to an NTA encodes `null`,
    and a null must stay drawn when a neighbourhood is picked, never vanish.
    """
    bidx = {b: i for i, b in enumerate(boroughs)}
    projects = _Projects()
    vacants = _Vacants(vacant_detail)
    fit = _AgeFit()
    character = _Character(character_detail)
    legality = _Legality(legality_detail)
    npipe, nshop = len(PIPELINE_GAP_COLUMNS), len(STOREFRONT_GAP_COLUMNS)
    tail = 8 + npipe + nshop        # where the ranking block starts in a row
    cens_at = tail + 6              # ...and where the D75 censoring pair starts
    frame_at = cens_at + 2          # ...and the D84 frame triple after that
    nta_at = frame_at + 3           # ...and the NTA code appended after that
    pts, ids = [], []
    cens_cat, cens_lead = [], []
    frames, frontages, streets = [], [], []
    nta_idx: list[int | None] = []
    nta_vocab: list[str] = []
    nta_lookup: dict[str, int] = {}
    for row in rows:
        address_id, lon, lat, boro, units = row[:5]
        if lon is None or lat is None or boro not in bidx:
            continue
        pts.extend([lon, lat, bidx[boro], round(float(units or 0))])
        pts.extend(pipe_slots(projects, row[8:8 + npipe]))
        pts.extend(sf_slots(vacants, row[8 + npipe:tail]))
        fit.add(row[tail:tail + 6])
        c_cat, c_lead = row[cens_at:cens_at + 2]
        cens_cat.append(None if c_cat is None else int(bool(c_cat)))
        cens_lead.append(None if c_lead is None else int(bool(c_lead)))
        # D84: 1 = street frame, 0 = lot. A parallel array and NOT a stride
        # slot, for the same reason `censoring` is one: the map must be able to
        # index it per point without every existing reader's fixed offsets
        # moving, and a file written before D84 has no answer at all.
        # A row shorter than the frame block is a caller that predates D84 --
        # one frame, every dot a lot, which is exactly what it was.
        fr, frontage, street = (tuple(row[frame_at:frame_at + 3]) + (None, None, None))[:3]
        frames.append(1 if fr == "street" else 0)
        frontages.append(_num(frontage, 0))
        streets.append(street)
        character.add(address_id)
        legality.add(address_id)
        ids.append(address_id)
        code = row[nta_at] if len(row) > nta_at else None
        if code is None:
            nta_idx.append(None)
        else:
            i = nta_lookup.get(code)
            if i is None:
                i = nta_lookup[code] = len(nta_vocab)
                nta_vocab.append(code)
            nta_idx.append(i)
    return {"category": cat, "label": CATEGORIES[cat].label, "stride": 12,
            "pts": pts, "ids": ids, "n": len(ids),
            "projects": projects.pack(),
            "pipelineColumns": list(PIPELINE_GAP_COLUMNS),
            "vacants": vacants.pack(),
            "storefrontColumns": list(STOREFRONT_GAP_COLUMNS),
            "ageFit": fit.pack(),
            "ageFitColumns": list(AGE_FIT_GAP_COLUMNS),
            "censoring": {"cat": cens_cat, "lead": cens_lead, "capM": GAP_CAP_M},
            "frame": {"street": frames, "frontageM": frontages, "streetName": streets,
                      "n_street": sum(frames), "caveat": STREET_FRAME_CAVEAT},
            "character": character.pack(),
            "legality": legality.pack(),
            "nta": {"idx": nta_idx, "vocab": nta_vocab}}


def _code_for(borough_name: str | None) -> str | None:
    for code, name in BOROUGH_NAMES.items():
        if name == borough_name:
            return code
    return None


def alcohol_vocab() -> tuple[list[str], dict[str, str]]:
    """The overlay's classes and their human labels, read from the adapter's
    yaml. Imported lazily: viz/ must not require the NYC source package at
    import time, so a missing adapter degrades to no overlay, not an
    ImportError in the middle of an export."""
    from loci.sources.cities.nyc.nys_sla import CLASSIFICATIONS, load_classification
    return list(CLASSIFICATIONS), dict(load_classification()["labels"])


def has_alcohol(con) -> bool:
    """staging.alcohol_licences is optional -- `loci ingest-alcohol` may not
    have run yet, and an export must not fail because of that."""
    schema, table = ALCOHOL_TABLE
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, table]).fetchone()[0])


def _alcohol_sql(boroughs: list[str]) -> tuple[str, list]:
    """Active licences only, in `boroughs` (two-letter codes). The table
    already stores the borough code, so unlike the POI layer this needs no H3
    join -- SLA publishes the county on every row."""
    ph = ", ".join("?" for _ in boroughs)
    sql = f"""
        SELECT licence_id, classification, description, name, address,
               borough,
               round(ST_X(geom), {COORD_DP}) AS lon,
               round(ST_Y(geom), {COORD_DP}) AS lat,
               CAST(expires_on AS VARCHAR) AS expires
        FROM {'.'.join(ALCOHOL_TABLE)}
        WHERE active AND borough IN ({ph})
        ORDER BY licence_id
    """
    return sql, list(boroughs)


def pack_alcohol(rows, boroughs: list[str], classes: list[str],
                 labels: dict[str, str]) -> dict:
    """rows -> one overlay layer. `pts` is stride 4: lon, lat, class index,
    borough index. Name, address, description and expiry ride in parallel
    arrays; description and expiry are dictionary-encoded (55 licence types
    and a few hundred distinct dates across ~15k points) while name and
    address are nearly unique per row and stay literal.

    A row whose classification is not in `classes` is counted as `unknown`
    rather than dropped -- an unmapped licence type must be visible on the map,
    not silently absent from it.
    """
    cidx = {c: i for i, c in enumerate(classes)}
    bidx = {b: i for i, b in enumerate(boroughs)}
    unknown = cidx.get("unknown", len(classes) - 1)
    desc_v, exp_v = _Vocab(), _Vocab()
    pts, names, addrs, descs, exps, ids = [], [], [], [], [], []
    counts = {c: {b: 0 for b in boroughs} for c in classes}
    for licence_id, cls, desc, name, addr, boro, lon, lat, expires in rows:
        if lon is None or lat is None or boro not in bidx:
            continue
        ci = cidx.get(cls, unknown)
        pts.extend([lon, lat, ci, bidx[boro]])
        names.append(name or "")
        addrs.append(addr or "")
        descs.append(desc_v.index(desc))
        exps.append(exp_v.index(expires))
        ids.append(licence_id)
        counts[classes[ci]][boro] += 1
    return {"stride": 4, "pts": pts, "names": names, "addr": addrs,
            "desc": descs, "expires": exps, "ids": ids,
            "vocab": {"desc": desc_v.items, "expires": exp_v.items},
            "classes": classes, "classLabels": [labels.get(c, c) for c in classes],
            "boroughs": boroughs, "counts": counts, "n": len(ids)}


def empty_alcohol(boroughs: list[str]) -> dict:
    """The shape `pack_alcohol` returns, with nothing in it -- what an export
    writes when the ingest has not been run. The UI can then say "not loaded"
    instead of 404ing."""
    try:
        classes, labels = alcohol_vocab()
    except Exception:                     # adapter or yaml unavailable
        classes, labels = ["unknown"], {"unknown": "Unclassified"}
    return pack_alcohol([], boroughs, classes, labels)


def collect_alcohol(con, boroughs: list[str]) -> dict:
    """Read the alcohol overlay. Pure read, and never raises for a missing
    table -- see `has_alcohol`."""
    if not has_alcohol(con):
        layer = empty_alcohol(boroughs)
        layer["available"] = False
        return layer
    classes, labels = alcohol_vocab()
    sql, params = _alcohol_sql(boroughs)
    layer = pack_alcohol(con.execute(sql, params).fetchall(), boroughs, classes, labels)
    layer["available"] = True
    return layer


# ------------------------------------------------- development pipeline layer
#
# One point per DOB job of >= PIPELINE_MIN_UNITS net units, in the drawn
# stages. Small enough (589 jobs across MN+BK) that nothing here is
# dictionary-encoded except the NTA name and the three dates: at this size the
# encoder would cost more in code than it saves in bytes.
#
# THE VINTAGE HAS TO RIDE WITH THE DATA. DCP publishes semiannually and 25Q4
# carries filings and permits only to its own cutoff, so a map that says
# "40,587 units coming" without saying as-of-when is a map that quietly ages
# into a lie. `asof` (the run date the 24/60-month windows count back from),
# `vintage` and `cutoff` are all read from the database, never hardcoded, and
# the UI is required to print them in the legend.


def has_pipeline(con) -> bool:
    """analysis.dev_pipeline is optional -- `loci ingest-dcp-housing` may not
    have run, and an export must not fail because of that (same contract as
    `has_alcohol`)."""
    schema, table = PIPELINE_TABLE
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, table]).fetchone()[0])


def pipeline_asof(con) -> str | None:
    """The date the address-grain windows were computed against, read from
    `analysis.address.pipeline_asof` (model/dev_pipeline stamps it once per
    run). None when `loci pipeline` has never run -- in which case the map's
    completion window has no anchor and the overlay says so rather than
    inventing today."""
    have = con.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'address' "
        "AND column_name = 'pipeline_asof'").fetchone()[0]
    if not have:
        return None
    row = con.execute("SELECT max(pipeline_asof) FROM analysis.address").fetchone()
    return None if not row or row[0] is None else str(row[0])[:10]


def pipeline_vintage(con) -> dict:
    """DCP's own release string and the newest FORWARD date it carries.

    `cutoff` is derived -- the newest filing or permit date in the table --
    rather than transcribed from the release notes, so it cannot drift from the
    rows actually loaded. It is the honest answer to "how stale is the coming
    side of this layer?": everything filed or permitted after it is missing,
    which makes the forward pipeline a floor and never a ceiling (sql/011
    caveat 1)."""
    schema, table = PIPELINE_TABLE
    row = con.execute(
        f"""SELECT max(source_vintage),
                   max(greatest(coalesce(date_filed, DATE '1900-01-01'),
                                coalesce(date_permitted, DATE '1900-01-01'))),
                   max(source), max(provenance)
            FROM {schema}.{table}""").fetchone()
    vintage, cutoff, source, provenance = row if row else (None, None, None, None)
    return {"vintage": vintage,
            "cutoff": None if cutoff is None else str(cutoff)[:10],
            "source": source, "provenance": provenance}


def _pipeline_sql(boroughs: list[str], asof: str) -> tuple[str, list]:
    """Large jobs in the drawn stages. The completion window is evaluated in
    SQL against `asof` so the month arithmetic lives in one place and cannot
    disagree with model/dev_pipeline's own windows."""
    schema, table = PIPELINE_TABLE
    ph = ", ".join("?" for _ in boroughs)
    stage_ph = ", ".join("?" for _ in PIPELINE_MAP_STAGES)
    sql = f"""
        SELECT job_number, bbl, borough, neighborhood, nta_code, job_type,
               net_units, stage, co_type,
               CAST(date_filed AS VARCHAR)     AS filed,
               CAST(date_permitted AS VARCHAR) AS permitted,
               CAST(date_complete AS VARCHAR)  AS complete,
               round(ST_X(geom), {COORD_DP}) AS lon,
               round(ST_Y(geom), {COORD_DP}) AS lat
        FROM {schema}.{table}
        WHERE borough IN ({ph})
          AND net_units >= ?
          AND geom IS NOT NULL
          AND stage IN ({stage_ph})
          AND (stage <> 'complete'
               OR (date_complete IS NOT NULL
                   AND date_complete >= CAST(? AS DATE) - INTERVAL {PIPELINE_COMPLETE_MONTHS} MONTH))
        ORDER BY job_number
    """
    return sql, [*boroughs, PIPELINE_MIN_UNITS, *PIPELINE_MAP_STAGES, asof]


def pipeline_band(units: int) -> int:
    """Index into PIPELINE_BANDS, or -1 below the floor. Python owns the edges;
    the UI reads them out of the file, so the mark drawn and the count printed
    come from one definition."""
    for i, (lo, hi) in enumerate(PIPELINE_BANDS):
        if units >= lo and (hi is None or units <= hi):
            return i
    return -1


def pack_pipeline(rows, boroughs: list[str]) -> dict:
    """rows -> one overlay layer. `pts` is stride 6: lon, lat, borough index,
    stage index, CO index, net units. The band is NOT a slot -- it is a
    function of net units and storing it would let a re-banding leave stale
    numbers behind.

    A row outside PIPELINE_MAP_STAGES or below PIPELINE_MIN_UNITS is DROPPED
    here as well as in SQL. That is deliberate belt-and-braces: the two filters
    have to agree, and a test asserts the packed layer holds no filed,
    withdrawn or sub-50 job whatever the query did."""
    bidx = {b: i for i, b in enumerate(boroughs)}
    sidx = {s: i for i, s in enumerate(PIPELINE_MAP_STAGES)}
    cidx = {c: i for i, c in enumerate(PIPELINE_CO)}
    nta_v, date_v, type_v = _Vocab(), _Vocab(), _Vocab()
    pts, ids, bbls, ntas, types = [], [], [], [], []
    filed, permitted, complete = [], [], []
    counts = {s: {b: 0 for b in boroughs} for s in PIPELINE_MAP_STAGES}
    units_by_stage = {s: {b: 0 for b in boroughs} for s in PIPELINE_MAP_STAGES}
    bands = {lab: {b: 0 for b in boroughs} for lab in PIPELINE_BAND_LABELS}
    for (job, bbl, boro, nbhd, nta, jtype, net_units, stage, co_type,
         d_filed, d_perm, d_comp, lon, lat) in rows:
        if lon is None or lat is None or boro not in bidx or stage not in sidx:
            continue
        units = int(net_units or 0)
        band = pipeline_band(units)
        if band < 0:
            continue
        pts.extend([lon, lat, bidx[boro], sidx[stage],
                    cidx.get(co_type or "none", cidx["none"]), units])
        ids.append(job)
        bbls.append(bbl or "")
        ntas.append(nta_v.index(nbhd or nta))
        types.append(type_v.index(jtype))
        filed.append(date_v.index(d_filed))
        permitted.append(date_v.index(d_perm))
        complete.append(date_v.index(d_comp))
        counts[stage][boro] += 1
        units_by_stage[stage][boro] += units
        bands[PIPELINE_BAND_LABELS[band]][boro] += 1
    return {"stride": 6, "pts": pts, "ids": ids, "bbl": bbls,
            "nta": ntas, "type": types,
            "filed": filed, "permitted": permitted, "complete": complete,
            "vocab": {"nta": nta_v.items, "type": type_v.items, "date": date_v.items},
            "stages": list(PIPELINE_MAP_STAGES),
            "stageLabels": [PIPELINE_STAGE_LABELS[s] for s in PIPELINE_MAP_STAGES],
            "co": list(PIPELINE_CO),
            "bands": [[lo, hi] for lo, hi in PIPELINE_BANDS],
            "bandLabels": list(PIPELINE_BAND_LABELS),
            "minUnits": PIPELINE_MIN_UNITS,
            "completeMonths": PIPELINE_COMPLETE_MONTHS,
            "boroughs": boroughs, "counts": counts, "units": units_by_stage,
            "bandCounts": bands, "n": len(ids)}


def empty_pipeline(boroughs: list[str]) -> dict:
    """The shape `pack_pipeline` returns, with nothing in it -- what an export
    writes when the ingest has not been run."""
    return pack_pipeline([], boroughs)


def collect_pipeline(con, boroughs: list[str]) -> dict:
    """Read the development-pipeline overlay. Pure read, and never raises for a
    missing table or a missing `loci pipeline` run."""
    if not has_pipeline(con):
        layer = empty_pipeline(boroughs)
        layer.update({"available": False, "asof": None, "vintage": None,
                      "cutoff": None, "source": None, "provenance": None})
        return layer
    vint = pipeline_vintage(con)
    # No `loci pipeline` run means no anchor for the 60-month window. Falling
    # back to the newest CO in the table is the honest choice -- it is a date
    # the data can defend -- and `asofSource` says which one was used.
    asof = pipeline_asof(con)
    asof_source = "analysis.address.pipeline_asof"
    if asof is None:
        schema, table = PIPELINE_TABLE
        row = con.execute(f"SELECT max(date_complete) FROM {schema}.{table}").fetchone()
        asof = None if not row or row[0] is None else str(row[0])[:10]
        asof_source = "max(analysis.dev_pipeline.date_complete)"
    if asof is None:
        layer = empty_pipeline(boroughs)
        layer.update({"available": False, "asof": None, "asofSource": None, **vint})
        return layer
    sql, params = _pipeline_sql(boroughs, asof)
    layer = pack_pipeline(con.execute(sql, params).fetchall(), boroughs)
    layer.update({"available": True, "asof": asof, "asofSource": asof_source, **vint})
    return layer


# ---------------------------------------------------- vacant storefront layer
#
# One point per PREMISES reported vacant in the snapshot filing. Small enough
# (2,751 across MN+BK) that only the prior use and the two dates are
# dictionary-encoded; the street address is nearly unique per point and stays
# literal, exactly as the alcohol overlay's is.
#
# THE SNAPSHOT IS ONE FILING AND THE DATES HAVE TO RIDE WITH IT. DOF publishes
# annually, the latest FULL-universe observation is 2024-12-31 (filed
# 2025-06-03), and five of the eleven filings hold vacant rows only. A map that
# says "2,751 empty storefronts" without saying as-of-when, filed-when, and out
# of how many registered, is a map that ages into a lie inside a year. `asof`,
# `filingDate`, `universe`, `vintage` and the per-borough denominators are all
# read from the database, never hardcoded, and the UI is required to print them.


def has_storefront(con) -> bool:
    """analysis.storefront is optional -- `loci ingest-storefronts` may not have
    run, and an export must not fail because of that (same contract as
    `has_alcohol` and `has_pipeline`)."""
    schema, table = STOREFRONT_TABLE
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, table]).fetchone()[0])


def storefront_asof(con, boroughs: list[str]):
    """The observation date the address measures were computed at, read from
    `analysis.address.storefront_asof` (model/storefronts stamps it once per
    run). Falls back to the newest FULL-universe 12/31 in the table when
    `loci storefronts` has never run -- a date the data can defend -- and the
    caller stamps which one was used.

    Never falls back to the newest observation of ANY universe: the freshest
    filings are vacant-only supplements, and taking one as the snapshot gives a
    numerator with no denominator (sql/012 caveat 4)."""
    have = con.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'address' "
        "AND column_name = 'storefront_asof'").fetchone()[0]
    if have:
        row = con.execute("SELECT max(storefront_asof) FROM analysis.address").fetchone()
        if row and row[0] is not None:
            return str(row[0])[:10], "analysis.address.storefront_asof"
    schema, table = STOREFRONT_TABLE
    ph = ", ".join("?" for _ in boroughs)
    row = con.execute(
        f"SELECT max(observed_1231) FROM {schema}.{table} "
        f"WHERE universe = 'full' AND borough IN ({ph})", list(boroughs)).fetchone()
    if not row or row[0] is None:
        return None, None
    return str(row[0])[:10], f"max(full-universe {schema}.{table}.observed_1231)"


def storefront_vintage(con) -> dict:
    """DOF's Socrata `rowsUpdatedAt` and the provenance string, straight off the
    rows actually loaded rather than transcribed from a release note."""
    schema, table = STOREFRONT_TABLE
    row = con.execute(
        f"SELECT max(source_vintage), max(source), max(provenance) "
        f"FROM {schema}.{table}").fetchone()
    vintage, source, provenance = row if row else (None, None, None)
    return {"vintage": vintage, "source": source, "provenance": provenance}


def snapshot_filing(con, boroughs: list[str], asof):
    """(filing_due_date, universe) for the ONE filing the overlay reads.

    Delegated to model/storefronts rather than restated here: the map must draw
    the same rows the address columns were computed from, and two copies of
    "which filing is the snapshot" is exactly how a map ends up showing 3,800
    vacancies beside an address measure built on 5,500."""
    import datetime as _dt

    from loci.model.storefronts import snapshot_filing as _pick
    if isinstance(asof, str):
        asof = _dt.date.fromisoformat(asof)
    return _pick(con, boroughs, asof)


def _prior_use_cte(boroughs: list[str]) -> str:
    """sql/012 caveat 7b's documented query, verbatim in shape: what this
    PREMISES last housed, ARG_MAX over every filing. Premises-level because
    `storefront_id` renumbers between filings -- a premises with four
    storefronts returns one answer for all four, and pretending otherwise would
    be the fusion bug wearing a coalesce."""
    schema, table = STOREFRONT_TABLE
    ph = ", ".join("?" for _ in boroughs)
    no_act = ", ".join(f"'{v}'" for v in NO_ACTIVITY)
    return f"""
        SELECT premises_id,
               -- activity_canonical, NOT primary_business_activity: ARG_MAX
               -- picks the NEWEST filing, and the newest filings are the ones
               -- DOF recoded in 2024. Reading the raw column here made the
               -- card's prior-use line say EDUCATIONAL SERVICES where the
               -- premises had been RETAIL. sql/012_activity_recode.yaml.
               ARG_MAX(activity_canonical, filing_due_date) AS last_use
        FROM {schema}.{table}
        WHERE borough IN ({ph})
          AND activity_canonical NOT IN ({no_act})
        GROUP BY 1
    """


def _storefront_sql(boroughs: list[str], filing, snap_year: int) -> tuple[str, list]:
    """One row per vacant PREMISES in the snapshot filing, with its run of
    consecutive vacant years and its prior use.

    The run is anchored at the SNAPSHOT year, not at the premises' own latest
    observation. analysis.storefront_latest anchors at the latter and its own
    header says so: for many premises that is the 2025-12-31 vacant-only
    supplement, which answers "when last observed, was this vacant?" -- a
    different question with no common denominator. The map's number has to be
    commensurable with the map's denominator, so the walk-back starts where the
    snapshot does.

    `pick` reproduces the view's one-filing-per-(premises, year) rule (FULL
    wins) because pooling a supplement with the annual filing double-counts the
    premises that filed both.
    """
    schema, table = STOREFRONT_TABLE
    ph = ", ".join("?" for _ in boroughs)
    sql = f"""
        WITH pick AS (
            SELECT premises_id, reporting_year,
                   ARG_MAX(filing_due_date, (universe = 'full', filing_due_date))
                       AS filing_due_date
            FROM {schema}.{table}
            WHERE borough IN ({ph}) AND observed_1231 IS NOT NULL
            GROUP BY 1, 2
        ), obs AS (
            SELECT s.premises_id, s.reporting_year AS yr,
                   MAX(CASE WHEN s.vacant_1231 THEN 1 ELSE 0 END) AS any_vacant
            FROM {schema}.{table} s
            JOIN pick p USING (premises_id, reporting_year, filing_due_date)
            WHERE s.reporting_year <= ?
            GROUP BY 1, 2
        ), ranked AS (
            SELECT premises_id, yr, any_vacant,
                   ROW_NUMBER() OVER (PARTITION BY premises_id ORDER BY yr DESC) AS r
            FROM obs
        ), runs AS (
            -- A year joins the run only if it is contiguous with the snapshot
            -- year AND vacant. A skipped year does not silently extend it.
            SELECT premises_id,
                   MIN(CASE WHEN any_vacant = 0 OR yr <> ? - (r - 1) THEN r END) AS stop_at,
                   COUNT(*) AS n_obs
            FROM ranked GROUP BY premises_id
        ), prior AS ({_prior_use_cte(boroughs)}
        ), snap AS (
            -- ONE row per premises. Several vacant storefronts at one premises
            -- are one empty building on a map; the count rides in the popup.
            SELECT premises_id, borough,
                   ARG_MIN(address, storefront_id)                        AS address,
                   ARG_MIN(round(ST_X(geom), {COORD_DP}), storefront_id)  AS lon,
                   ARG_MIN(round(ST_Y(geom), {COORD_DP}), storefront_id)  AS lat,
                   MAX(CASE WHEN construction_reported THEN 1 ELSE 0 END) AS construction,
                   MAX(lease_expiry)                                      AS lease_expiry,
                   COUNT(*)                                               AS vacant_storefronts
            FROM {schema}.{table}
            WHERE filing_due_date = ? AND borough IN ({ph})
              AND vacant_1231 AND geom IS NOT NULL
            GROUP BY 1, 2
        )
        SELECT s.premises_id, s.borough, s.address, s.lon, s.lat,
               s.construction, s.vacant_storefronts,
               CAST(s.lease_expiry AS VARCHAR) AS lease_expiry,
               GREATEST(COALESCE(runs.stop_at - 1, runs.n_obs, 1), 1)
                   AS consecutive_vacant_years,
               p.last_use
        FROM snap s
        LEFT JOIN runs USING (premises_id)
        LEFT JOIN prior p USING (premises_id)
        ORDER BY s.premises_id
    """
    return sql, [*boroughs, snap_year, snap_year, *boroughs, filing, *boroughs]


def _storefront_totals_sql(boroughs: list[str], filing) -> tuple[str, list]:
    """The denominator, per borough, off the SAME filing. `no_geom` is the
    honest count of vacancies the overlay cannot draw -- dropped explicitly and
    reported, never lost silently."""
    schema, table = STOREFRONT_TABLE
    ph = ", ".join("?" for _ in boroughs)
    sql = f"""
        SELECT borough,
               count(*)                        AS storefronts,
               count(DISTINCT premises_id)     AS premises,
               sum(CASE WHEN vacant_1231 THEN 1 ELSE 0 END) AS vacant_storefronts,
               count(DISTINCT CASE WHEN vacant_1231 THEN premises_id END)
                   AS vacant_premises,
               count(DISTINCT CASE WHEN vacant_1231 AND geom IS NULL
                                   THEN premises_id END) AS no_geom
        FROM {schema}.{table}
        WHERE filing_due_date = ? AND borough IN ({ph})
        GROUP BY 1
    """
    return sql, [filing, *boroughs]


def vacant_detail(con, boroughs: list[str], filing) -> dict[str, tuple]:
    """{storefront_id: (street address, prior use)} for every vacant storefront
    in the snapshot -- what the gap layers' `vacants` dictionary hangs off the
    model's `nearest_vacant_storefront_id`. ~3,800 MN+BK rows.

    Read here rather than joined into the gap query because fifteen category
    files would otherwise re-fetch the same 3,800 rows fifteen times."""
    schema, table = STOREFRONT_TABLE
    ph = ", ".join("?" for _ in boroughs)
    sql = f"""
        WITH prior AS ({_prior_use_cte(boroughs)})
        SELECT s.storefront_id, s.address, p.last_use
        FROM {schema}.{table} s
        LEFT JOIN prior p USING (premises_id)
        WHERE s.filing_due_date = ? AND s.borough IN ({ph}) AND s.vacant_1231
    """
    rows = con.execute(sql, [*boroughs, filing, *boroughs]).fetchall()
    return {sid: (addr, prior) for sid, addr, prior in rows}


def storefront_band(years: int) -> int:
    """Index into STOREFRONT_YEAR_BANDS, or -1 below the floor. Python owns the
    edges; the UI reads them out of the file, so the mark drawn and the count
    printed come from one definition."""
    for i, (lo, hi) in enumerate(STOREFRONT_YEAR_BANDS):
        if years >= lo and (hi is None or years <= hi):
            return i
    return -1


def pack_storefronts(rows, boroughs: list[str], totals: dict | None = None,
                     asof: str | None = None) -> dict:
    """rows -> one overlay layer. `pts` is stride 5: lon, lat, borough index,
    year-band index, construction flag. The band is a function of the year
    count, which rides in its own parallel array so the popup can print the
    number the band was derived from.

    A premises with fewer than one vacant observation is DROPPED here as well as
    in SQL -- belt and braces, the same contract `pack_pipeline` keeps: a test
    asserts the packed layer holds no non-vacant premises whatever the query
    did.

    `since` is DERIVED, not stored: the first year of the run is
    (snapshot year - (consecutive - 1)), rendered as that year's 12/31. Storing
    it would let a re-banding leave a stale date behind.
    """
    bidx = {b: i for i, b in enumerate(boroughs)}
    year = int(asof[:4]) if asof else None
    biz_v, date_v = _Vocab(), _Vocab()
    pts, ids, addrs, years, counts_at = [], [], [], [], []
    biz, since, lease = [], [], []
    counts = {lab: {b: 0 for b in boroughs} for lab in STOREFRONT_YEAR_LABELS}
    construction = {b: 0 for b in boroughs}
    for (pid, boro, addr, lon, lat, constr, n_vacant, lease_expiry,
         yrs, last_use) in rows:
        if lon is None or lat is None or boro not in bidx:
            continue
        yrs = int(yrs or 0)
        band = storefront_band(yrs)
        if band < 0:
            continue
        pts.extend([lon, lat, bidx[boro], band, int(bool(constr))])
        ids.append(pid)
        addrs.append(addr or "")
        years.append(yrs)
        counts_at.append(int(n_vacant or 1))
        biz.append(biz_v.index(last_use))
        since.append(date_v.index(
            None if year is None else f"{year - (yrs - 1)}-12-31"))
        lease.append(date_v.index(lease_expiry))
        counts[STOREFRONT_YEAR_LABELS[band]][boro] += 1
        construction[boro] += int(bool(constr))
    return {"stride": 5, "pts": pts, "ids": ids, "addr": addrs,
            "years": years, "storefronts": counts_at,
            "business": biz, "since": since, "lease": lease,
            "vocab": {"business": biz_v.items, "date": date_v.items},
            "bands": [[lo, hi] for lo, hi in STOREFRONT_YEAR_BANDS],
            "bandLabels": list(STOREFRONT_YEAR_LABELS),
            "boroughs": boroughs, "counts": counts,
            "construction": construction,
            "totals": totals or {b: {} for b in boroughs},
            "n": len(ids)}


def empty_storefronts(boroughs: list[str]) -> dict:
    """The shape `pack_storefronts` returns, with nothing in it -- what an
    export writes when the ingest has not been run. The UI can then say "not
    loaded" instead of 404ing."""
    return pack_storefronts([], boroughs)


def collect_storefronts(con, boroughs: list[str]) -> dict:
    """Read the vacant-storefront overlay. Pure read, and never raises for a
    missing table, a missing `loci storefronts` run, or an observation date
    with no filing behind it."""
    def _blank(**extra):
        layer = empty_storefronts(boroughs)
        layer.update({"available": False, "asof": None, "asofSource": None,
                      "filingDate": None, "universe": None,
                      "vintage": None, "source": None, "provenance": None})
        layer.update(extra)
        return layer

    if not has_storefront(con):
        return _blank()
    asof, asof_source = storefront_asof(con, boroughs)
    vint = storefront_vintage(con)
    if asof is None:
        return _blank(**vint)
    pick = snapshot_filing(con, boroughs, asof)
    if pick is None:
        return _blank(asof=asof, asofSource=asof_source, **vint)
    filing, universe = pick
    tsql, tparams = _storefront_totals_sql(boroughs, filing)
    totals = {b: {"storefronts": int(s), "premises": int(p),
                  "vacantStorefronts": int(vs), "vacantPremises": int(vp),
                  "noGeom": int(ng)}
              for b, s, p, vs, vp, ng in con.execute(tsql, tparams).fetchall()}
    for b in boroughs:
        totals.setdefault(b, {"storefronts": 0, "premises": 0,
                              "vacantStorefronts": 0, "vacantPremises": 0,
                              "noGeom": 0})
    sql, params = _storefront_sql(boroughs, filing, int(asof[:4]))
    layer = pack_storefronts(con.execute(sql, params).fetchall(), boroughs,
                             totals, asof)
    layer.update({"available": True, "asof": asof, "asofSource": asof_source,
                  "filingDate": str(filing)[:10], "universe": universe, **vint})
    return layer


# ---------------------------------------------------- neighbourhood character
#
# THE OWNER'S QUESTION (2026-09-13): "give color to neighborhoods for whether
# they are retail- or corporate-dominated." Every other layer on this map is a
# point; this one is an AREA, because "what kind of place is this" is not a
# property of a doorway. It reads `analysis.address_character` (label and
# intensity per address) and `analysis.nta_character` (the address-weighted
# roll-up), both VIEWS generated from model/address_character.py's own
# constants (sql/021) -- which is why the legend below states its thresholds by
# FORMATTING those constants rather than by repeating their values. A retyped
# "office floor area over 35%" outlives the constant it was copied from by
# exactly one retune.
#
# A SIXTH OVERLAY, NOT A SIXTEENTH BUSINESS. Switching it on cannot move a gap
# dot, cannot change a score and cannot filter the universe -- sql/021 caveat 4
# says these columns enter no score, no supply ratio and no grade, and the map
# has to keep that promise. It tints; it never selects.
#
# THE POLYGONS ARE DERIVED, NOT INGESTED. There is no NTA boundary file in this
# project and there should not be one: `analysis.hex` already carries
# `nta_code`, so the neighbourhood outline drawn here is the DISSOLVED H3 res-9
# cover of it, simplified to ~40 m. The drawn edge is then exactly the edge the
# rest of the warehouse means by "this NTA"; a shapefile from DCP would draw a
# prettier boundary around a different set of addresses.
#
# NULL IS A CLASS. An address whose `loci address-character build` has not run
# for its borough has no label (the view is explicit about this), and it is
# drawn in the no-data grey with the popup saying so -- never as `residential`,
# which is what any "default to the commonest class" shortcut produces and
# which would be a data gap wearing a costume.

#: The model module. OPTIONAL exactly the way `staging.alcohol_licences` is: a
#: checkout predating sql/021 writes an empty layer and says why, rather than
#: failing the whole export on an import error.
try:                                             # pragma: no cover - import guard
    from loci.model import address_character as character_model
except Exception:                                # pragma: no cover
    character_model = None

try:                                             # pragma: no cover - import guard
    from loci.model import address_legality as legality_model
except Exception:                                # pragma: no cover
    legality_model = None

CHARACTER_ADDRESS_VIEW = ("analysis", "address_character")
CHARACTER_NTA_VIEW = ("analysis", "nta_character")

#: D82/seed 2026-09-14: legality is a card label and a recommendation filter,
#: never a score. LEGALITY_VIEW is the cheap passthrough
#: `analysis.address_legality` (sql/031); LEGALITY_VALUES mirrors
#: `address_legality.LEGALITY_VALUES` so the export still has an order even
#: when the model import guard above trips (same fallback contract
#: CHARACTER_LABELS_FALLBACK uses just below).
LEGALITY_VIEW = ("analysis", "address_legality")
LEGALITY_VALUES = (legality_model.LEGALITY_VALUES if legality_model
                   else ("commercial", "grandfathered", "ineligible"))

#: Fallback legend order, used ONLY when the model is not importable. The live
#: order is `character_labels()`, which reads the model's own LABEL_ORDER.
CHARACTER_LABELS_FALLBACK = ("corporate", "industrial", "retail_mixed", "residential")

#: Four-class categorical palette. VALIDATED (dataviz skill,
#: scripts/validate_palette.js) against this page's surface #f3f0ea on the
#: ALL-PAIRS pairlist a choropleth requires, not the weaker adjacent list:
#:   lightness band pass; chroma floor pass;
#:   worst-pair CVD dE 16.5 (target >= 8); worst-pair normal-vision dE 16.5
#:   (floor 15); all four >= 3:1 against the surface, so no relief rule applies.
#: The hues follow the zoning-map convention a New York planner already reads
#: (R yellow, C red, M purple) with desk work as the blue. They are deliberately
#: NOT steps of `COLORS`: those fifteen category dots are drawn ON TOP of these
#: areas. With fifteen hues already spanning the wheel, distance in hue alone
#: cannot separate the two palettes, so the separation is carried by MARK TYPE
#: as well -- a translucent area fill under saturated points -- and the nearest
#: `COLORS` neighbour to any of these four is 6.5 dE away.
CHARACTER_COLORS = {
    "residential":  "#a08920",   # ochre
    "retail_mixed": "#9e231e",   # brick red
    "corporate":    "#6288da",   # steel blue
    "industrial":   "#783583",   # plum
}
#: The SAME four hues stepped for a dark surface (#17181a), not a second
#: palette: validated all-pairs in dark mode -- worst-pair CVD dE 13.8, worst
#: normal-vision dE 16.9, all four >= 3:1. The page is light-only today, so
#: these are unreachable until it gains a dark theme; they ship anyway because
#: the alternative is a future dark mode inventing its own colours. The UI
#: selects between the two sets by reading the page's OWN background token, not
#: by trusting `prefers-color-scheme` -- an OS preference the page does not
#: honour must not repaint the map (see `charColors` in webmap/index.html).
CHARACTER_COLORS_DARK = {
    "residential":  "#ab9017",
    "retail_mixed": "#a64e3d",
    "corporate":    "#4886fe",
    "industrial":   "#9346a4",
}
#: THE DEFAULT VIEW IS THE RAMP, NOT THE FOUR CLASSES (urban-planner review,
#: 2026-09-13). Under the labels Brooklyn is ~90% `residential`, so a
#: four-colour choropleth of MN+BK is very nearly a monochrome -- it answers
#: "which class won here" when the owner's question was "how retail is this
#: street". `retail_index` is continuous, so the fill is SEQUENTIAL: one hue,
#: light -> dark, which is the only legal encoding for magnitude.
#:
#: The hue is the retail_mixed categorical hue (OKLCH H 27.9 deg), so "retail"
#: means one colour everywhere on this map. Six stops, monotone in L with every
#: adjacent gap >= 0.06, hue spread 1 deg (dataviz `--ordinal` report). The
#: lightest stop sits at 1.09:1 on the page surface, below the ORDINAL 2:1
#: floor and deliberately so: this is a SEQUENTIAL encoding on a choropleth,
#: where the skill's palette reference allows the lightest step to recede
#: toward the surface because it means "near zero". No-data is 25.9 dE from
#: that stop AND carries its own dashed outline, so "no retail here" and "we
#: did not measure here" never read as the same polygon.
CHARACTER_RAMP = ("#ffe0db", "#fabfb6", "#f29c90", "#e57669", "#cf4e43", "#a52a24")
#: The same ramp re-stepped for a dark surface: the anchor flips, so the
#: LIGHTEST end is the one that recedes toward #17181a.
CHARACTER_RAMP_DARK = ("#3a1a17", "#5c241e", "#7f3128", "#a54135", "#c65a4b", "#e58676")

#: The two classes the ramp CANNOT carry, drawn as sparse categorical overlays
#: on top of it: a distinct hue each plus a 45 deg / 135 deg hatch, which is
#: the texture channel the dataviz skill reserves for exactly this. They are
#: sparse by construction -- 9 corporate and 0 industrial NTAs in MN+BK -- so
#: they read as annotations on the ramp rather than as a second choropleth.
#: Validated all-pairs against the ramp's mid and dark stops on the page
#: surface: worst pair #a52a24 <-> #783583, CVD dE 16.1, normal-vision dE 16.7.
CHARACTER_OVERLAY_LABELS = ("corporate", "industrial")
#: The no-data class. Grey, and a LEGEND KEY of its own rather than an absence.
CHARACTER_NODATA_COLOR = "#9b968a"
CHARACTER_NODATA_COLOR_DARK = "#7f7b71"

#: Legend display names. The rule text beside each is built from the model's
#: thresholds by `character_rules`.
CHARACTER_LABEL_TEXT = {
    "residential":  "Residential",
    "retail_mixed": "Retail / mixed",
    "corporate":    "Corporate",
    "industrial":   "Industrial",
}

#: `analysis.nta_character` columns, by the key they take in the payload. One
#: dict, so a rename in the view is one edit here and `character_missing`
#: reports the drift instead of the export raising halfway through a run.
CHARACTER_NTA_COLUMNS = {"n": "addresses", "dom": "dominant_character",
                         "intensity": "mean_intensity",
                         "ampm": "am_pm_share_median", "nAmPm": "n_am_pm"}
#: ...the per-label ADDRESS shares (what fraction of the NTA carries the label).
CHARACTER_SHARE_COLUMNS = {"corporate": "share_corporate",
                           "industrial": "share_industrial",
                           "retail_mixed": "share_retail_mixed",
                           "residential": "share_residential"}
#: ...the mean per-address FLOOR-AREA shares, over the four named uses.
CHARACTER_AREA_COLUMNS = {"res": "mean_res_area_share",
                          "retail": "mean_retail_area_share",
                          "office": "mean_office_area_share",
                          "factory": "mean_factory_area_share"}
#: ...and the mean per-address JOB shares, which sum to 1 by construction.
CHARACTER_JOBS_COLUMNS = {"retail": "mean_jobs_retail_share",
                          "office": "mean_jobs_office_share",
                          "other": "mean_jobs_other_share"}
#: `analysis.address_character` columns the per-address tint reads.
CHARACTER_ADDRESS_COLUMNS = ("character", "character_intensity")
#: ...and the continuous measure the ramp is drawn from, plus the two
#: commercial-overlay readings the popup prints. OPTIONAL: a database carrying
#: the labels but not yet `retail_index` still exports a working layer, it just
#: exports `ramp: false` and the UI falls back to the four-class fill. A
#: half-shipped upstream must degrade, not take the map down.
CHARACTER_RETAIL_ADDRESS_COLUMNS = ("retail_index", "commercial_overlay_100m",
                                    "commercial_overlay_share_400m")
#: The NTA roll-up's ramp columns, by payload key. Same one-dict-to-rename
#: contract as the blocks above, and the same optionality.
#: `ri` is the MEAN, not the median, and that is a map decision with a reason.
#: `retail_index` is per address a CAPPED MAX over three witnesses, so at the
#: NTA median 52% of live MN+BK neighbourhoods saturate at exactly 1.00 and a
#: light-to-dark ramp on it is a dark monochrome -- the same failure the
#: four-class map had, at the other end of the scale. The MEAN of the same
#: per-address index keeps the spread (17% at the cap, deciles 0.44 -> 1.00)
#: because the addresses clearing no threshold pull it down. The median still
#: ships, as `riMed`, and the popup prints both: where they disagree, one
#: avenue is carrying the neighbourhood.
CHARACTER_RETAIL_NTA_COLUMNS = {"ri": "mean_retail_index",
                                "riMed": "med_retail_index",
                                "sup": "suppressed",
                                "ovlBlock": "share_on_commercial_block",
                                "ovlShare": "mean_overlay_share"}

CHARACTER_SHARE_DP = 2        # "48%" -- more precision than that is not a map fact
#: Douglas-Peucker tolerance for the dissolved NTA outline, in degrees. ~40 m
#: at this latitude, which is shorter than an H3 res-9 edge: the result is the
#: hex cover's shape with its staircase taken off, not a different polygon.
CHARACTER_SIMPLIFY_DEG = 0.0004


def character_labels() -> tuple[str, ...]:
    """The four labels in the model's own rule order (corporate first, because
    that is the order the CASE tests them in). Read from the model so a fifth
    class added upstream reaches the legend, rather than being silently dropped
    by a tuple in the presentation layer."""
    if character_model is None:
        return CHARACTER_LABELS_FALLBACK
    return tuple(getattr(character_model, "LABEL_ORDER", None)
                 or CHARACTER_LABELS_FALLBACK)


def character_label_drift() -> str | None:
    """`None` when every label the model emits has a colour and a display name
    here, else a one-line description of the drift. The repo standard's
    "machine-check the docs against the code" applied to a palette: a class the
    model learned to emit but this file has no colour for must disable the
    layer, not be drawn in somebody else's colour."""
    if character_model is None:
        return "model/address_character.py is not importable"
    labels = set(character_labels())
    unpainted = sorted(labels - set(CHARACTER_COLORS))
    unshared = sorted(labels - set(CHARACTER_SHARE_COLUMNS))
    if unpainted:
        return f"model emits {unpainted} which webmap_export has no colour for"
    if unshared:
        return f"model emits {unpainted or unshared} which nta_character has no share column for"
    return None


def _pct(value: float) -> str:
    return f"{round(float(value) * 100)}%"


def character_rules() -> dict[str, str]:
    """`{label: the one line that says when it fires}`, BUILT FROM THE MODEL'S
    THRESHOLDS. Nothing here restates a number: every percentage in the text is
    a format of the constant the view's CASE expression was generated from, so
    the legend cannot claim a threshold the label was not computed with.

    The wording mirrors model/address_character.py's own reasoning -- corporate
    and industrial before retail because an IBZ edge with a brewery taproom is
    still East Williamsburg -- because a legend that lists four independent
    tests hides that the rules are an ORDERED chain."""
    m = character_model
    if m is None:
        return {}
    rules = {
        "corporate": (
            f"office is {_pct(m.CORPORATE_OFFICE_AREA_SHARE)}+ of the floor area "
            f"within 400 m, or {_pct(m.CORPORATE_JOBS_OFFICE_SHARE)}+ of "
            f"{m.CORPORATE_JOBS_FLOOR:,}+ jobs are desk jobs"),
        "industrial": (
            f"otherwise: factory floor area is "
            f"{_pct(m.INDUSTRIAL_FACTORY_AREA_SHARE)}+ of the floor area within 400 m"),
        "retail_mixed": (
            f"otherwise: retail is {_pct(m.RETAIL_AREA_SHARE)}+ of the floor area, "
            f"or {_pct(m.RETAIL_JOBS_SHARE)}+ of the jobs are shops and services"),
        "residential": "otherwise: nothing within 400 m reaches any of the lines above",
    }
    return {lab: rules[lab] for lab in character_labels() if lab in rules}


def character_copy() -> dict[str, dict]:
    """`{label: {"text": what to CALL it, "caveat": the sentence beside it}}`,
    READ FROM THE MODEL (`CHARACTER_COPY`).

    It exists because `corporate` is the label the rules compute and NOT the
    thing a reader should be told: the rule fires on office floor area and
    desk-job share within a five-minute walk, which is a WEEKDAY-DAYTIME
    catchment, not a claim about who owns the block or what trades there at
    seven in the evening. The model owns that wording; this module only renders
    it, and falls back to the plain display name when the constant is absent so
    a checkout without it still draws a legend.

    Accepts either shape the model may use -- `{label: "text"}` or
    `{label: {"text": ..., "caveat": ...}}` -- because a legend that crashed on
    a constant's shape would be a worse failure than one that read a bare
    string."""
    raw = getattr(character_model, "CHARACTER_COPY", None) or {}
    cav = getattr(character_model, "CHARACTER_CAVEAT", None) or {}
    out: dict[str, dict] = {}
    for lab in character_labels():
        entry, caveat = raw.get(lab), cav.get(lab)
        if isinstance(entry, dict):
            text = str(entry.get("text") or entry.get("label")
                       or CHARACTER_LABEL_TEXT.get(lab, lab))
            caveat = entry.get("caveat") or caveat
        elif isinstance(entry, str):
            text = entry
        else:
            text = CHARACTER_LABEL_TEXT.get(lab, lab)
        # Title case for the legend, because the model writes the copy as a
        # phrase ("weekday-office catchment") meant to sit mid-sentence too.
        out[lab] = {"text": text, "title": text[:1].upper() + text[1:],
                    "caveat": str(caveat) if caveat else None}
    return out


def character_caveat() -> str:
    """The sentence the page is REQUIRED to print wherever a floor-area share
    appears (sql/021 caveats 1-3). Rendered untruncated, same rule the age-fit
    caveat already lives under."""
    return (
        "PLUTO RetailArea is a FLOOR on storefront floor area, not a measurement: a "
        "mixed-use building's ground-floor store is often folded into ComArea and never "
        "reaches RetailArea, and the under-count is worst on exactly the old rowhouse "
        "retail strips this layer is asked about. LODES counts payroll jobs at a block "
        "centroid, so remote and hybrid workers are counted at an office they may not "
        "enter and most of the self-employed are not counted at all. Floor area is a "
        "stock and jobs are a flow of payroll; where the two disagree, both shares are "
        "in the popup so a reader can see which rule fired. None of this enters "
        "gap_score, the supply ratio, the revenue model or any recommendation grade."
    )


def _character_columns(con, view: tuple[str, str]) -> set[str]:
    schema, name = view
    return {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ?", [schema, name]).fetchall()}


def character_missing(con) -> list[str]:
    """Every named column the layer needs that this database does not have.
    An empty list means the layer can be exported."""
    addr = _character_columns(con, CHARACTER_ADDRESS_VIEW)
    nta = _character_columns(con, CHARACTER_NTA_VIEW)
    want = (list(CHARACTER_NTA_COLUMNS.values())
            + [CHARACTER_SHARE_COLUMNS[lab] for lab in character_labels()
               if lab in CHARACTER_SHARE_COLUMNS]
            + list(CHARACTER_AREA_COLUMNS.values())
            + list(CHARACTER_JOBS_COLUMNS.values()))
    miss: list[str] = []
    an, nn = ".".join(CHARACTER_ADDRESS_VIEW), ".".join(CHARACTER_NTA_VIEW)
    if not addr:
        miss.append(f"{an} (view absent)")
    else:
        miss += [f"{an}.{c}" for c in CHARACTER_ADDRESS_COLUMNS if c not in addr]
    if not nta:
        miss.append(f"{nn} (view absent)")
    else:
        miss += [f"{nn}.{c}" for c in want if c not in nta]
    return miss


def character_ramp_missing(con) -> list[str]:
    """Every RAMP column absent from this database. The ramp is the default
    view, but it is not a precondition for the layer: the labels shipped first,
    `retail_index` follows, and between those two exports the map draws the
    four-class fill and says so rather than going dark."""
    addr = _character_columns(con, CHARACTER_ADDRESS_VIEW)
    nta = _character_columns(con, CHARACTER_NTA_VIEW)
    an, nn = ".".join(CHARACTER_ADDRESS_VIEW), ".".join(CHARACTER_NTA_VIEW)
    miss = [f"{an}.{c}" for c in CHARACTER_RETAIL_ADDRESS_COLUMNS if c not in addr]
    miss += [f"{nn}.{c}" for c in CHARACTER_RETAIL_NTA_COLUMNS.values() if c not in nta]
    return miss


def has_character_ramp(con) -> bool:
    return not character_ramp_missing(con)


def has_character(con) -> bool:
    """True when both views exist carrying every column the layer names. A
    database predating sql/021 exports an empty character layer and the UI
    hides the toggle -- the same contract alcohol, pipeline and storefronts
    already have."""
    return not character_missing(con)


def _character_detail_sql(boroughs: list[str], ramp: bool = True) -> tuple[str, list]:
    """`(address_id, label, intensity)` for the exported boroughs.

    BOROUGH CODES, not names. `analysis.address_character` is a view over
    `analysis.address`, whose `borough` holds 'MN'/'BK' -- the same convention
    `_gap_sql` uses and the OPPOSITE of `analysis.hex`, whose `borough` holds
    'Manhattan'/'Brooklyn'. Both conventions appear in this section (the NTA
    outlines come from hex), so each query says which one it is on.

    Read ONCE
    for all sixteen gap files and all 111 neighbourhood files -- the same rows
    stand behind every one of them, exactly like `collect_vacant_detail`."""
    ph = ", ".join("?" for _ in boroughs)
    label, intensity = CHARACTER_ADDRESS_COLUMNS
    # `retail_index` rides as a fourth column when the view has it; NULL when
    # it does not, so `pack` has one row shape to read either way.
    ri = CHARACTER_RETAIL_ADDRESS_COLUMNS[0] if ramp else "NULL"
    return (f"""
        SELECT address_id, {label}, {intensity}, {ri}
        FROM {'.'.join(CHARACTER_ADDRESS_VIEW)}
        WHERE borough IN ({ph}) AND {label} IS NOT NULL
    """, list(boroughs))


def collect_character_detail(con, boroughs: list[str]) -> dict[str, tuple]:
    """`{address_id: (label index, intensity percent)}`, or `{}` when the views
    are not there. Never raises, for the same reason `collect_vacant_detail`
    does not: an absent optional layer must not take the export down with it.

    An address MISSING from this dict is the no-data case, and that is the
    point of building it from `character IS NOT NULL` rows only -- membership
    is the test, so no sentinel label can leak into a file.

    Intensity is carried as an INTEGER PERCENT rather than a float. Two
    decimals on a 0-1 scale is all a tint can honestly show, and `81` costs
    three bytes a point where `0.81` costs five -- across the sixteen gap files
    that is the difference between +1.6 MB and +2.6 MB of payload."""
    if not has_character(con):
        return {}
    sql, params = _character_detail_sql(boroughs, has_character_ramp(con))
    idx = {lab: i for i, lab in enumerate(character_labels())}
    out: dict[str, tuple] = {}
    for address_id, label, intensity, retail in con.execute(sql, params).fetchall():
        i = idx.get(label)
        if i is None:
            continue          # a class this map has no colour for: no data
        out[address_id] = (i,
                           None if intensity is None else round(float(intensity) * 100),
                           None if retail is None else round(float(retail) * 100))
    return out


class _Character:
    """The per-address character tint for one layer, as PARALLEL ARRAYS.

    Not stride slots, and for the reason `_AgeFit` spells out: "no label" is a
    third state, and a null dropped into a numeric stride arrives in the
    browser as 0 -- which here would read as the FIRST label at zero intensity,
    a class the address was never assigned. These two arrays carry a literal
    JSON `null` instead, and the browser draws that in the no-data grey. Keeping
    them out of `pts` also leaves every existing stride and every offset into it
    untouched, so a reader written against the old files still reads the new
    ones.

    `label` indexes `labels` (the model's own order); `pct` is
    character_intensity x 100 and `ri` is retail_index x 100, both rounded (see
    `collect_character_detail`). `ri` is what the dots are TINTED by once the
    ramp is the default view; `label` stays in the payload because the
    recommendation card reads the four-class label, not the index."""

    def __init__(self, detail: dict[str, tuple] | None = None) -> None:
        self.detail = detail or {}
        self.label: list = []
        self.pct: list = []
        self.ri: list = []

    def add(self, address_id) -> None:
        i, pct, ri = self.detail.get(address_id, (None, None, None))
        self.label.append(i)
        self.pct.append(pct)
        self.ri.append(ri)

    def pack(self) -> dict:
        return {"label": self.label, "pct": self.pct, "ri": self.ri,
                "labels": list(character_labels())}


# --------------------------------------------------------------- legality (D82)

def has_legality(con) -> bool:
    """True when `analysis.address_legality` exists AND carries at least one
    populated row. A database predating sql/031, or one on which
    `loci address-legality build` has not run yet, exports an EMPTY legality
    block and the UI leaves every marker un-greyed -- the same
    degrade-gracefully contract `has_character` / `has_alcohol` /
    `has_pipeline` already follow; AC-5 must never fail closed into hiding
    gap markers, only into not labelling them."""
    schema, table = LEGALITY_VIEW
    exists = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, table]).fetchone()[0]
    if not exists:
        return False
    n = con.execute(
        f"SELECT count(*) FROM {'.'.join(LEGALITY_VIEW)} "
        "WHERE legality IS NOT NULL").fetchone()[0]
    return bool(n)


def _legality_detail_sql(boroughs: list[str]) -> tuple[str, list]:
    """`(address_id, legality, histdist, landmark)` for the exported
    boroughs. histdist/landmark come from `analysis.address` directly (they
    are card labels, D82 -- not part of the legality verdict at all, see
    `address_legality.legality_case_sql`'s own test that neither is read by
    any branch of the predicate) -- reading them here is a SEPARATE join, not
    evidence they influence `legality`.

    Read ONCE for all sixteen gap files, the same "read once, reuse across
    every category" contract `collect_character_detail` and
    `collect_vacant_detail` already follow."""
    ph = ", ".join("?" for _ in boroughs)
    return (f"""
        SELECT l.address_id, l.legality, a.histdist, a.landmark
        FROM {'.'.join(LEGALITY_VIEW)} l
        JOIN analysis.address a ON a.address_id = l.address_id
        WHERE a.borough IN ({ph}) AND l.legality IS NOT NULL
    """, list(boroughs))


def collect_legality_detail(con, boroughs: list[str]) -> dict[str, tuple]:
    """`{address_id: (legality index, histdist bool, landmark bool)}`, or
    `{}` when `has_legality` is false. Same never-raises, membership-is-the-
    test contract as `collect_character_detail`: an address absent from this
    dict has no legality reading, and the UI must draw that as "no data",
    never as a silent 'commercial'."""
    if not has_legality(con):
        return {}
    sql, params = _legality_detail_sql(boroughs)
    idx = {v: i for i, v in enumerate(LEGALITY_VALUES)}
    out: dict[str, tuple] = {}
    for address_id, legality, histdist, landmark in con.execute(sql, params).fetchall():
        i = idx.get(legality)
        if i is None:
            continue          # a value this map export does not know: no data
        out[address_id] = (i, bool(histdist), bool(landmark))
    return out


class _Legality:
    """The per-address legality reading for one gap layer, as PARALLEL
    ARRAYS -- same rationale as `_Character` / `_AgeFit`: "no data" is a
    third state a numeric stride slot cannot represent, and these ride
    outside `pts` so no existing stride or offset moves.

    `legality` indexes `values` (commercial | grandfathered | ineligible);
    `histdist` / `landmark` are 1/0/null card-label flags, independent of
    `legality` -- D82: they never move the verdict, they only add a fit-out
    caveat to the card."""

    def __init__(self, detail: dict[str, tuple] | None = None) -> None:
        self.detail = detail or {}
        self.legality: list = []
        self.histdist: list = []
        self.landmark: list = []

    def add(self, address_id) -> None:
        leg, hd, lm = self.detail.get(address_id, (None, None, None))
        self.legality.append(leg)
        self.histdist.append(None if hd is None else int(bool(hd)))
        self.landmark.append(None if lm is None else int(bool(lm)))

    def pack(self) -> dict:
        return {"legality": self.legality, "histdist": self.histdist,
                "landmark": self.landmark, "values": list(LEGALITY_VALUES)}


def _nta_character_sql(boroughs: list[str], ramp: bool = True) -> tuple[str, list]:
    """One row per NTA out of `analysis.nta_character`, restricted to the
    exported boroughs. Column NAMES come from the four dicts above, so a rename
    upstream is one edit rather than a scavenger hunt through a format string.

    Borough CODES again: this view groups `analysis.address_character`."""
    ph = ", ".join("?" for _ in boroughs)
    labels = [lab for lab in character_labels() if lab in CHARACTER_SHARE_COLUMNS]
    cols = ([CHARACTER_NTA_COLUMNS[k] for k in ("n", "dom", "intensity", "ampm", "nAmPm")]
            + [CHARACTER_SHARE_COLUMNS[lab] for lab in labels]
            + [CHARACTER_AREA_COLUMNS[k] for k in ("res", "retail", "office", "factory")]
            + [CHARACTER_JOBS_COLUMNS[k] for k in ("retail", "office", "other")])
    # APPENDED, never inserted -- `character_block` reads the head by position
    # and the ramp tail off its own end, so a database without the ramp
    # columns produces the same row shape filled with NULL.
    cols += [(CHARACTER_RETAIL_NTA_COLUMNS[k] if ramp else "NULL")
             for k in ("ri", "riMed", "sup", "ovlBlock", "ovlShare")]
    return (f"""
        SELECT nta_code, {", ".join(cols)}
        FROM {'.'.join(CHARACTER_NTA_VIEW)}
        WHERE borough IN ({ph}) AND nta_code IS NOT NULL
        ORDER BY nta_code
    """, list(boroughs))


def _nta_shapes_sql(boroughs: list[str]) -> tuple[str, list]:
    """The dissolved H3 cover of each NTA, simplified. Read from
    `analysis.hex`, the only place in this warehouse that knows which ground
    belongs to which neighbourhood -- and the one table in this section whose
    `borough` holds the full NAME rather than the code."""
    ph = ", ".join("?" for _ in boroughs)
    return (f"""
        SELECT nta_code,
               ST_AsGeoJSON(ST_Simplify(ST_Union_Agg(geom), {CHARACTER_SIMPLIFY_DEG}))
        FROM analysis.hex
        WHERE borough IN ({ph}) AND nta_code IS NOT NULL
        GROUP BY nta_code
        ORDER BY nta_code
    """, [BOROUGH_NAMES[b] for b in boroughs])


def _share_num(value):
    return _num(value, CHARACTER_SHARE_DP)


def character_block(row) -> dict:
    """One `_nta_character_sql` row -> the small dict that rides in every NTA
    file AND in the overlay. Short keys, two decimals; ~290 bytes, which is
    what lets it ship in all 111 neighbourhood files instead of being a second
    fetch the sidebar has to wait on.

    `domShare` is NOT read from a column -- `analysis.nta_character` has none.
    It is the dominant label's own share out of the same `shares` dict the
    popup prints, so the headline number and the breakdown cannot disagree."""
    labels = [lab for lab in character_labels() if lab in CHARACTER_SHARE_COLUMNS]
    n, dom, intensity, ampm, n_ampm = row[1:6]
    at = 6
    shares = {lab: _share_num(v) for lab, v in zip(labels, row[at:at + len(labels)])}
    at += len(labels)
    area = row[at:at + 4]
    jobs = row[at + 4:at + 7]
    ri, ri_med, suppressed, ovl_block, ovl_share = row[at + 7:at + 12]
    # A dominant label this map has no colour for is not a class it can draw,
    # so it reads as no data rather than as a bad index.
    dom = dom if dom in CHARACTER_COLORS else None
    return {
        "n": int(n or 0),
        "dom": dom,
        "domShare": None if dom is None else shares.get(dom),
        "shares": shares,
        "area": dict(zip(("res", "retail", "office", "factory"), map(_share_num, area))),
        "jobs": dict(zip(("retail", "office", "other"), map(_share_num, jobs))),
        "intensity": _share_num(intensity),
        # THE DEFAULT FILL: the MEAN retail_index across the NTA's addresses.
        # See CHARACTER_RETAIL_NTA_COLUMNS for why the mean and not the
        # median. `riMed` rides along so the popup can show the two
        # disagreeing -- a median of 1.00 under a mean of 0.55 is a
        # neighbourhood whose avenues are retail and whose side streets are
        # not, which is a different place from one that is uniformly 0.55.
        "ri": _share_num(ri),
        "riMed": _share_num(ri_med),
        # Parks, cemeteries and NTAs under the model's address floor. Drawn as
        # no-data, because a retail index computed over eleven addresses in
        # Green-Wood Cemetery is a number, not a reading.
        "sup": bool(suppressed) if suppressed is not None else False,
        # Commercial-overlay context, printed beside the index: what share of
        # the NTA's addresses sit on a C1/C2 block at all, and what share of
        # the 400 m catchment is under an overlay. Zoning is what PERMITS a
        # storefront; the index is what one IS, and the two disagreeing is the
        # whole point of printing both -- a street allowed to have shops and
        # not having them is a different lead from one that is not allowed.
        "ovlBlock": _share_num(ovl_block),
        "ovlShare": _share_num(ovl_share),
        # Median AM/PM entry share (D76 addendum), CORROBORATION from a
        # different source: high means people leave in the morning (a
        # residential catchment), low means they arrive (a destination). NULL
        # where no profiled station is within 400 m -- most of Brooklyn -- and
        # `nAmPm` is how many addresses the median rests on, so the popup can
        # decline to print a median that rests on eleven of them.
        "ampm": _share_num(ampm),
        "nAmPm": int(n_ampm or 0),
    }


def quantile_stops(values: list[float], n: int) -> list[float]:
    """`n` breakpoints placed at evenly-spaced QUANTILES of `values`, strictly
    increasing.

    A LINEAR ramp on `retail_index` is nearly as useless as the four-class map
    it replaces, and for the mirror-image reason. The index is a capped MAX
    over three witnesses, so it saturates: Manhattan below 96th St sits at a
    p50 of 1.0 and Brooklyn at 0.68, which on a linear scale spends most of the
    ramp's resolution on a range almost nothing occupies and crushes the
    0.5-1.0 band where the whole city actually lives. Stretching the stops over
    the observed distribution puts the colour resolution where the
    neighbourhoods are.

    THE COST, AND WHY THE LEGEND HAS TO CARRY IT: a quantile-stretched ramp
    encodes RANK, not magnitude -- two neighbourhoods one shade apart differ by
    a decile, not by a fixed amount of retail. That is a real weakening of a
    sequential scale and the map must say so, which is why the legend bar
    places each colour at its VALUE (so the compression is visible) and prints
    the stop values rather than a smooth 0-1 axis.

    Ties are nudged apart by a hair because MapLibre's `interpolate` requires
    strictly increasing stops and a saturated tail produces plenty of them."""
    if not values or n < 2:
        return []
    xs = sorted(values)
    out: list[float] = []
    for i in range(n):
        j = i * (len(xs) - 1) / (n - 1)
        lo, frac = int(j), j - int(j)
        v = xs[lo] if frac == 0 else xs[lo] + (xs[lo + 1] - xs[lo]) * frac
        v = round(float(v), 4)
        if out and v <= out[-1]:
            v = out[-1] + 1e-4
        out.append(round(v, 4))
    return out


def pack_character(char_rows, shape_rows, provenance: dict | None = None,
                   ramp: bool = True, ramp_reason: str | None = None) -> dict:
    """rows -> the `character.json` overlay: one block per NTA plus the
    dissolved outlines as a GeoJSON FeatureCollection whose properties carry
    only what the FILL needs (`nta`, `dom`, `domShare`). Everything the popup
    shows is looked up by `nta` out of `ntas`, so the geometry is not also a
    second copy of the table."""
    blocks = {row[0]: character_block(row) for row in char_rows if row[0]}
    feats = []
    for code, geojson in shape_rows:
        block = blocks.get(code)
        if not code or not geojson or block is None:
            continue
        # Only what the FILL and the two overlays need. `ri` drives the ramp,
        # `sup` routes the polygon to no-data, `dom` picks the hatch. Every
        # other number the popup prints is looked up by `nta` out of `ntas`.
        feats.append({"type": "Feature",
                      "properties": {"nta": code, "dom": block["dom"],
                                     "domShare": block["domShare"],
                                     "ri": None if block["sup"] else block.get("ri"),
                                     "sup": int(bool(block["sup"]))},
                      "geometry": json.loads(geojson)})
    counts = {lab: 0 for lab in character_labels()}
    counts["none"] = 0
    for block in blocks.values():
        counts[block["dom"] or "none"] += 1
    ri_vals = [b["ri"] for b in blocks.values() if b.get("ri") is not None and not b["sup"]]
    return {"available": True, "reason": None,
            # The ramp is the DEFAULT view; `ramp: false` means the database
            # carries the labels but not `retail_index` yet, and the UI falls
            # back to the four-class fill rather than drawing a blank one.
            "ramp": bool(ramp and ri_vals),
            "rampReason": ramp_reason,
            "rampColors": list(CHARACTER_RAMP),
            "rampColorsDark": list(CHARACTER_RAMP_DARK),
            "overlayLabels": [lab for lab in CHARACTER_OVERLAY_LABELS
                              if lab in character_labels()],
            # The domain the ramp is stretched over, so the legend's end labels
            # are the data's ends and not a hard-coded 0..1 that would make
            # every neighbourhood look pale if the index never reaches 1.
            "riRange": [min(ri_vals), max(ri_vals)] if ri_vals else [0.0, 1.0],
            # ...and WHERE each colour sits inside that domain. Quantiles, not
            # even spacing -- see `quantile_stops` for why, and for the honesty
            # cost the legend is required to carry.
            "riStops": quantile_stops(ri_vals, len(CHARACTER_RAMP)),
            "riScale": "quantile",
            "suppressed": sum(1 for b in blocks.values() if b["sup"]),
            "copy": character_copy(),
            "labels": list(character_labels()),
            "labelText": {lab: CHARACTER_LABEL_TEXT.get(lab, lab)
                          for lab in character_labels()},
            "colors": {lab: CHARACTER_COLORS[lab] for lab in character_labels()
                       if lab in CHARACTER_COLORS},
            "colorsDark": {lab: CHARACTER_COLORS_DARK[lab] for lab in character_labels()
                           if lab in CHARACTER_COLORS_DARK},
            "noDataColor": CHARACTER_NODATA_COLOR,
            "noDataColorDark": CHARACTER_NODATA_COLOR_DARK,
            "rules": character_rules(), "caveat": character_caveat(),
            "counts": counts, "n": len(blocks), "nShapes": len(feats),
            "provenance": provenance or {},
            "ntas": blocks,
            "shapes": {"type": "FeatureCollection", "features": feats}}


def empty_character(reason: str | None = None) -> dict:
    """What the export writes when sql/021 has not run. `available: false` plus
    a REASON naming the missing column -- the UI hides the toggle and the
    terminal says what to run, rather than the map drawing a confident empty
    choropleth."""
    return {"available": False, "reason": reason,
            "ramp": False, "rampReason": reason,
            "rampColors": list(CHARACTER_RAMP),
            "rampColorsDark": list(CHARACTER_RAMP_DARK),
            "overlayLabels": [lab for lab in CHARACTER_OVERLAY_LABELS
                              if lab in character_labels()],
            "riRange": [0.0, 1.0], "riStops": [], "riScale": "quantile",
            "suppressed": 0, "copy": character_copy(),
            "labels": list(character_labels()),
            "labelText": {lab: CHARACTER_LABEL_TEXT.get(lab, lab)
                          for lab in character_labels()},
            "colors": {lab: CHARACTER_COLORS[lab] for lab in character_labels()
                       if lab in CHARACTER_COLORS},
            "colorsDark": {lab: CHARACTER_COLORS_DARK[lab] for lab in character_labels()
                           if lab in CHARACTER_COLORS_DARK},
            "noDataColor": CHARACTER_NODATA_COLOR,
            "noDataColorDark": CHARACTER_NODATA_COLOR_DARK,
            "rules": character_rules(), "caveat": character_caveat(),
            "counts": {}, "n": 0, "nShapes": 0, "provenance": {}, "ntas": {},
            "shapes": {"type": "FeatureCollection", "features": []}}


def character_provenance(con, boroughs: list[str]) -> dict:
    """The facts the legend is REQUIRED to print beside a floor-area reading:
    the radius the catchment used, the MapPLUTO version the areas came off, the
    LODES year the jobs came from, and how many addresses the build never
    reached. A floor-area share with no assessment-roll vintage ages into a lie
    exactly the way the pipeline overlay's `cutoff` does."""
    ph = ", ".join("?" for _ in boroughs)
    try:
        row = con.execute(f"""
            SELECT max(character_radius_m), max(character_pluto_version),
                   max(character_jobs_vintage), max(character_run_at),
                   count(*) FILTER (WHERE character_run_at IS NULL)
            FROM analysis.address WHERE borough IN ({ph})
        """, list(boroughs)).fetchone()
    except Exception:
        return {}
    radius, pluto, jobs, run_at, unrun = row
    return {"radiusM": None if radius is None else round(float(radius)),
            "plutoVersion": pluto, "jobsVintage": jobs,
            "runAt": None if run_at is None else str(run_at)[:19],
            "unrunAddresses": int(unrun or 0)}


def collect_character(con, boroughs: list[str]) -> dict:
    """Read the character overlay. Pure read; degrades to `empty_character`
    with a reason rather than raising, so `loci export-webmap` still produces a
    working map on a database where `loci address-character build` has not
    run."""
    missing = character_missing(con)
    if missing:
        return empty_character("missing: " + ", ".join(missing))
    drift = character_label_drift()
    if drift:
        return empty_character(drift)
    ramp_missing = character_ramp_missing(con)
    csql, cparams = _nta_character_sql(boroughs, not ramp_missing)
    char_rows = con.execute(csql, cparams).fetchall()
    ssql, sparams = _nta_shapes_sql(boroughs)
    try:
        shape_rows = con.execute(ssql, sparams).fetchall()
    except Exception:
        # No spatial extension, no outlines. Legend, popups and the per-address
        # tint all still work; only the fill is absent, and `nShapes` says so
        # rather than leaving the UI to guess why the map is blank.
        shape_rows = []
    return pack_character(char_rows, shape_rows, character_provenance(con, boroughs),
                          ramp=not ramp_missing,
                          ramp_reason=("missing: " + ", ".join(ramp_missing))
                          if ramp_missing else None)


# --------------------------------------------------- all opportunities (NTA)
#
# THE OWNER'S QUESTION (2026-09-09): "when I zoom in on one neighborhood, can
# we show all the opportunities?" The fifteen per-category files answer "where
# is business X missing"; nobody can answer "what is missing HERE" by clicking
# through fifteen of them and holding the union in their head.
#
# So: one file per NTA carrying every address in it that is missing at
# least one category, with the whole missing LIST per address. This is a
# PRESENTATION layer over exactly the same `analysis.address_gaps` rows the
# per-category files read -- no new score, no new threshold. `ratio > 1` is
# still the model's own definition of missing (D41), and an address that
# appears in `gaps/laundry.json` appears in its NTA file with `laundry` in its
# missing list, always.
#
# SCOPED BY NTA, NEVER CITYWIDE. 177k MN+BK addresses are missing something;
# drawing them all at once is neither a map nor a question. The mode requires a
# neighborhood, and the browser fetches exactly one file.
#
# PACKING. `pts` is stride 6 (lon, lat, capped units, lead-category index,
# gap_score, n_missing) and the missing lists ride in ONE flat `miss` array of
# (category index, ratio) pairs, walked with a running cursor: point j consumes
# the next `pts[j*6+5]` pairs. No offsets array, because `n_missing` already
# is the offset table -- and `n_missing` here is `len(missing)`, DERIVED rather
# than read from the column of the same name, so the number that walks the
# array and the number in the popup cannot disagree.
#
# KNOWN LOCATIONS RIDE ALONG. In this mode the map wants all fifteen
# categories' supply, and fetching fifteen POI files (10 MB) to draw the ~1%
# of them inside one NTA would be absurd. Each NTA file carries its own POI
# block instead, read through `analysis.poi_supply` under the SAME supply set
# and carrying the same corroborated / in-set flags, so the D47 and D52
# distinctions survive into this view rather than being flattened to "a dot".

NTA_DIR = "nta"
RATIO_DP = 2      # "2.14x" -- more precision than that is not a map fact
SCORE_DP = 3


def _nta_gap_sql(boroughs: list[str], pipeline: bool = True,
                 storefront: bool = True, lot_only: bool = False) -> tuple[str, list]:
    """Every address in `boroughs` with its fifteen ratios (no eligibility
    filter -- the gate is retired, D75).

    `lot_only` is the D84 pin, and it is TRUE wherever the column exists. This
    is the NEIGHBOURHOOD roll-up: its numbers are "how many addresses in this
    neighbourhood are missing X" and its dots are read as buildings. A street
    midpoint is neither, so the street frame rides in the per-category gap
    layers -- which carry a frame flag and a toggle -- and not here. The
    missing LIST is assembled in Python rather than by an UNPIVOT: one pass
    over 267k rows beats fifteen self-joins, and the same `ratio > 1` test then
    lives in exactly one place for both the count and the payload."""
    ph = ", ".join("?" for _ in boroughs)
    ratios = ", ".join(f"{c}_ratio" for c in ALLCATS)
    # The seven pipeline columns and the five storefront columns sit BETWEEN
    # the head and the ratios so every slice stays fixed-width from its own
    # end: pack_nta reads the head by position and the ratios by "everything
    # after the annotation blocks".
    pipe = ", ".join(PIPELINE_GAP_COLUMNS if pipeline
                     else ["NULL"] * len(PIPELINE_GAP_COLUMNS))
    shop = ", ".join(STOREFRONT_GAP_COLUMNS if storefront
                     else ["NULL"] * len(STOREFRONT_GAP_COLUMNS))
    frm = "AND COALESCE(frame, 'lot') = 'lot'" if lot_only else ""
    sql = f"""
        SELECT nta_code, neighborhood, borough, address_id,
               round(lon, {COORD_DP}) AS lon, round(lat, {COORD_DP}) AS lat,
               units_capped, gap_score, lead_category, {pipe}, {shop}, {ratios}
        FROM analysis.address_gaps
        WHERE borough IN ({ph}) AND nta_code IS NOT NULL
          {frm}
        ORDER BY nta_code, address_id
    """
    return sql, list(boroughs)


def _nta_poi_sql(boroughs: list[str],
                 supply_set: str = DEFAULT_SUPPLY_SET) -> tuple[str, list]:
    """Known locations grouped by NTA, all fifteen categories at once.

    Deliberately thinner than `_poi_sql`: no DOHMH detail, no source bitmask --
    only whether the record is corroborated (2+ distinct sources, D47) and
    whether the supply set kept it (D52). This layer is context for a gap, not
    the restaurant inspector, and the extra columns would triple the file.

    Reads `SUPPLY_VIEW` and excludes an EVIDENCED closure (`poi_status =
    'closed'`), same as `_poi_sql` -- see that docstring for why never
    `= 'open'`.
    """
    pred = supply_predicate(supply_set)
    names = [BOROUGH_NAMES[b] for b in boroughs]
    ph = ", ".join("?" for _ in names)
    sql = f"""
        WITH src AS (
            SELECT d.cluster_id, count(DISTINCT p.source_id) AS n_src
            FROM analysis.poi_dedup d
            JOIN staging.poi p ON p.poi_id = d.poi_id
            GROUP BY 1
        )
        SELECT h.nta_code,
               v.category,
               v.name,
               round(ST_X(v.geom), {COORD_DP}) AS lon,
               round(ST_Y(v.geom), {COORD_DP}) AS lat,
               s.n_src >= 2 AS corroborated,
               v.{pred} AS in_set,
               v.poi_status, v.poi_status_basis
        FROM {SUPPLY_VIEW} v
        JOIN src s ON s.cluster_id = v.cluster_id
        JOIN analysis.hex h
          ON h.h3_index = h3_latlng_to_cell_string(ST_Y(v.geom), ST_X(v.geom), {H3_RES})
        WHERE h.borough IN ({ph})
          AND h.nta_code IS NOT NULL
          AND v.category IN ({", ".join("?" for _ in ALLCATS)})
          AND v.poi_status <> 'closed'
        ORDER BY h.nta_code, v.category, v.poi_id
    """
    return sql, names + ALLCATS


def missing_list(ratios) -> list[tuple[int, float]]:
    """(category index, ratio) for every category beyond its reach tier, worst
    first. A NULL ratio is NOT missing -- it is unmeasured, and inventing a gap
    out of a null is exactly the "data gap wearing a costume" this project
    exists to avoid."""
    out = [(i, float(r)) for i, r in enumerate(ratios) if r is not None and r > 1]
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def pack_nta(gap_rows, poi_rows, supply_set: str = DEFAULT_SUPPLY_SET,
             supply_hash: str | None = None,
             vacant_detail: dict[str, tuple] | None = None,
             character_detail: dict[str, tuple] | None = None,
             character_ntas: dict[str, dict] | None = None) -> dict[str, dict]:
    """rows -> {nta_code: layer}. Only NTAs with at least one gap address get a
    layer: an "all opportunities" file for a neighborhood with no opportunity
    is a file the picker must never offer. POI rows for such an NTA are
    dropped with it."""
    out: dict[str, dict] = {}
    projects: dict[str, _Projects] = {}
    vacants: dict[str, _Vacants] = {}
    characters: dict[str, _Character] = {}
    character_ntas = character_ntas or {}
    head = 9
    npipe, nshop = len(PIPELINE_GAP_COLUMNS), len(STOREFRONT_GAP_COLUMNS)
    for row in gap_rows:
        code, name, boro, address_id, lon, lat, units, score, lead = row[:head]
        if lon is None or lat is None:
            continue
        missing = missing_list(row[head + npipe + nshop:])
        if not missing:
            continue
        layer = out.get(code)
        if layer is None:
            projects[code] = _Projects()
            vacants[code] = _Vacants(vacant_detail)
            characters[code] = _Character(character_detail)
            layer = out[code] = {
                "nta": code, "name": name, "boro": boro,
                "supplySet": supply_set, "supplyHash": supply_hash,
                "stride": 14, "pts": [], "ids": [], "miss": [],
                "gapCounts": {c: 0 for c in ALLCATS},
                "bounds": [lon, lat, lon, lat], "units": 0,
                "pois": {"stride": 5, "pts": [], "names": [], "n": 0, "nSet": 0},
                "pipelineColumns": list(PIPELINE_GAP_COLUMNS),
                "storefrontColumns": list(STOREFRONT_GAP_COLUMNS),
                # The neighbourhood's OWN character reading, ~290 bytes, so
                # the sidebar can answer "what kind of place is this?" from the
                # file it already fetched rather than waiting on the overlay.
                # `None` where the character build has not reached this NTA.
                "character": character_ntas.get(code),
            }
        u = round(float(units or 0))
        # Slots 0..5 are UNCHANGED and must stay so: the browser walks the
        # `miss` array off slot 5 (n_missing) and reads lead/score by position.
        layer["pts"].extend([lon, lat, u,
                             ALLCATS.index(lead) if lead in CATEGORIES else -1,
                             round(float(score or 0), SCORE_DP), len(missing)])
        layer["pts"].extend(pipe_slots(projects[code], row[head:head + npipe]))
        layer["pts"].extend(sf_slots(vacants[code],
                                     row[head + npipe:head + npipe + nshop]))
        characters[code].add(address_id)
        layer["ids"].append(address_id)
        layer["units"] += u
        for i, ratio in missing:
            layer["miss"].extend([i, round(ratio, RATIO_DP)])
            layer["gapCounts"][ALLCATS[i]] += 1
        b = layer["bounds"]
        layer["bounds"] = [min(b[0], lon), min(b[1], lat), max(b[2], lon), max(b[3], lat)]

    for code, cat, name, lon, lat, corroborated, in_set, _poi_status, _poi_status_basis in poi_rows:
        layer = out.get(code)
        if layer is None or lon is None or lat is None or cat not in CATEGORIES:
            continue
        p = layer["pois"]
        p["pts"].extend([lon, lat, ALLCATS.index(cat),
                         int(bool(corroborated)), int(bool(in_set))])
        p["names"].append(name or "")

    for code, layer in out.items():
        layer["n"] = len(layer["ids"])
        layer["projects"] = projects[code].pack()
        layer["vacants"] = vacants[code].pack()
        layer["addressCharacter"] = characters[code].pack()
        p = layer["pois"]
        p["n"] = len(p["names"])
        p["nSet"] = sum(p["pts"][4::5])
        # A centre for the sidebar label; the bbox is what the map flies to.
        pts, st = layer["pts"], layer["stride"]
        layer["center"] = [round(sum(pts[0::st]) / layer["n"], COORD_DP),
                           round(sum(pts[1::st]) / layer["n"], COORD_DP)]
    return out


#: How the map says a list is ordered. Mirrors model/address_gaps.RANK_BY so
#: the file and the screen can never disagree about what "density" means.
RANK_LABELS = {
    "density": "walk-shed density (residential units per km²)",
    "units": "capped residential units",
}

#: Rendered UNTRUNCATED wherever a density appears, for the same reason the
#: age-fit caveat is: the number is a PLUTO register count over a measured
#: walk-shed, and a reader who takes it for an ACS household density will
#: compare it with figures that carry a margin of error when this one cannot.
DENSITY_CAVEAT = (
    "Walk-shed density is residential UNITS (PLUTO UnitsRes) per km² of the area "
    "reachable within a 400 m walk — the convex hull of the reachable street nodes, "
    "not a πr² disc. It is a register count with NO margin of error and no occupancy "
    "adjustment, so it is not an ACS households-per-km² figure and must not be "
    "compared with one like for like."
)

#: Columns of clusters.json's `rows`, in order. Declared once so the file and
#: any reader of it are generated from the same list.
CLUSTER_COLUMNS = ["cluster_id", "borough", "lead_category", "nta_code",
                   "cluster_density_400m", "cluster_density_mean_400m",
                   "units_capped", "n_addresses", "median_lead_excess_m",
                   # D84, APPENDED and never inserted -- this list is read
                   # POSITIONALLY by clusters.json's consumers, so a new column
                   # goes on the end. 'lot' or 'street': a street cluster has no
                   # residents and no tax lot, so its density is a catchment
                   # over OTHER rows' homes and its feasibility is not assessed.
                   "frame"]


def _fnum(value, dp: int = 0):
    """`_num` plus the NaN guard this block needs. A weighted median over a
    cluster whose densities are all NULL is NaN, and `json.dumps` writes NaN
    as the bare token `NaN`, which every browser's JSON.parse rejects -- one
    such cluster would 404 the whole file. NaN is missing, so it is None."""
    if value is None:
        return None
    v = float(value)
    return None if v != v else round(v, dp)


def nta_index(layers: dict[str, dict], boroughs: list[str],
              supply_set: str, supply_hash: str | None,
              densities: dict[str, float] | None = None,
              rank_by: str = "density") -> dict:
    """The small file the sidebar reads: one row per neighborhood with its
    address count, its per-category gap counts and its bounds.

    ORDER (owner ruling 2026-09-13, "rank by density"): by the neighborhood's
    walk-shed density, `n` as the tiebreak, with `n` and `units` still on every
    row -- "how dense" and "how many" are different questions and the picker
    shows both. `densities=None` (a database where `loci supply-ratio` has not
    run) falls back to the old size order and says so in `rankBy`, rather than
    labelling a size order as a density one.
    """
    densities = densities or {}
    rows = [{"nta": code, "name": L["name"], "boro": L["boro"], "n": L["n"],
             "units": L["units"], "pois": L["pois"]["n"], "nSet": L["pois"]["nSet"],
             "gapCounts": L["gapCounts"], "bounds": L["bounds"], "center": L["center"],
             # Dominant label only -- the index is the SMALL file the picker
             # reads, and the four shares belong in the file it opens next.
             "char": (L.get("character") or {}).get("dom"),
             "charShare": (L.get("character") or {}).get("domShare"),
             # APPENDED (owner ruling 2026-09-13): the units_capped-weighted
             # MEDIAN of this neighborhood's gap addresses' own density_400m.
             # None where supply-ratio has not run for the borough.
             "density": _fnum(densities.get(code))}
            for code, L in layers.items()]
    ranked = rank_by == "density" and any(r["density"] is not None for r in rows)
    if ranked:
        rows.sort(key=lambda r: (-(r["density"] if r["density"] is not None else -1),
                                 -r["n"], r["nta"]))
    else:
        rows.sort(key=lambda r: (-r["n"], r["nta"]))
    return {"boroughs": boroughs, "cats": ALLCATS,
            "catLabels": [CATEGORIES[c].label for c in ALLCATS],
            "supplySet": supply_set, "supplyHash": supply_hash,
            "rankBy": "density" if ranked else "units",
            "rankLabel": RANK_LABELS["density" if ranked else "units"],
            "n": sum(r["n"] for r in rows), "ntas": rows}


def nta_densities(con, boroughs: list[str]) -> dict[str, float]:
    """{nta_code: units_capped-weighted median of `density_400m`} over the
    GAP addresses of each neighborhood -- the same statistic and the same
    weighting `model/address_gaps.cluster_table` uses for a cluster, so a
    neighborhood and a cluster inside it are read on one ruler.

    Read in its own small query and NOT appended to `_nta_gap_sql`'s row: that
    row is consumed positionally by `pack_nta`, and a column added to it would
    be a silent reindex of every field after it.
    """
    from loci.model.address_gaps import weighted_median

    if not has_density_columns(con):
        return {}
    ph = ", ".join("?" for _ in boroughs)
    df = con.execute(
        f"""SELECT nta_code, density_400m, units_capped FROM analysis.address
            WHERE borough IN ({ph}) AND nta_code IS NOT NULL
              AND density_400m IS NOT NULL AND gap_score > 1""", list(boroughs)).fetchdf()
    if df.empty:
        return {}
    return {code: weighted_median(g["density_400m"].to_numpy(), g["units_capped"].to_numpy())
            for code, g in df.groupby("nta_code", sort=False)}


def collect_clusters(con, boroughs: list[str], rank_by: str = "density") -> dict:
    """The ranked cluster list, as its own small file.

    This is the ONE list on the map that is a cluster list, so it is the one
    the owner's "rank by density" ruling lands on directly: ordered by
    `cluster_density_400m` (the units_capped-weighted median of the members'
    own `density_400m`), with `units_capped` as the tiebreak and printed
    beside it. `available` false means `loci supply-ratio` has not run, and the
    map says so instead of showing a size order under a density label."""
    from loci.model.address_gaps import RANK_BY, cluster_table

    if rank_by not in RANK_BY:
        raise ValueError(f"unknown rank_by {rank_by!r}; expected one of {RANK_BY}")
    unavailable = {"available": False, "rankBy": "units", "rankLabel": RANK_LABELS["units"],
                   "caveat": DENSITY_CAVEAT, "cols": CLUSTER_COLUMNS, "rows": [], "n": 0}
    if not has_density_columns(con):
        return unavailable
    ph = ", ".join("?" for _ in boroughs)
    df = con.execute(
        f"""SELECT address_id, borough, frame, cluster_id, units_capped, lead_category,
                   lead_excess_m, nta_code, density_400m
            FROM analysis.address
            WHERE cluster_id IS NOT NULL AND borough IN ({ph})""", list(boroughs)).fetchdf()
    if df.empty:
        return unavailable
    available = True
    try:
        table = cluster_table(df, rank_by=rank_by)
    except ValueError:
        # The column is there but every value is NULL -- supply-ratio ran for
        # a different borough. Ship the list ordered by size and SAY so; an
        # empty file would lose the clusters, and a density label over a size
        # order is the failure the ruling corrects.
        if rank_by != "density":
            raise
        rank_by, available = "units", False
        table = cluster_table(df, rank_by="units")
    rows = [[r["cluster_id"], r["borough"], r["lead_category"], r.get("nta_code"),
             _fnum(r["cluster_density_400m"]), _fnum(r["cluster_density_mean_400m"]),
             _fnum(r["units_capped"]), int(r["n_addresses"]),
             _fnum(r["median_lead_excess_m"]), r.get("frame") or "lot"]
            for r in table.to_dict("records")]
    return {"available": available, "rankBy": rank_by, "rankLabel": RANK_LABELS[rank_by],
            "caveat": DENSITY_CAVEAT, "cols": CLUSTER_COLUMNS,
            "rows": rows, "n": len(rows)}


def collect_nta(con, boroughs: list[str], supply_set: str = DEFAULT_SUPPLY_SET,
                supply_hash: str | None = None,
                vacants: dict[str, tuple] | None = None,
                characters: dict[str, tuple] | None = None,
                character_ntas: dict[str, dict] | None = None) -> dict[str, dict]:
    """Read the all-opportunities layers. Pure read, same two tables the
    per-category layers come from.

    `characters` and `character_ntas` are PASSED IN rather than read here, for
    the same reason `vacants` is: the same address-level labels and the same
    111 NTA blocks stand behind the sixteen gap files too, and reading them
    twice would be two chances to disagree."""
    gsql, gparams = _nta_gap_sql(boroughs, has_pipeline_columns(con),
                                 has_storefront_columns(con),
                                 lot_only=has_frame_columns(con))
    psql, pparams = _nta_poi_sql(boroughs, supply_set)
    return pack_nta(con.execute(gsql, gparams).fetchall(),
                    con.execute(psql, pparams).fetchall(),
                    supply_set, supply_hash,
                    vacants if vacants is not None else collect_vacant_detail(con, boroughs),
                    characters if characters is not None
                    else collect_character_detail(con, boroughs),
                    character_ntas)


# ------------------------------------- MODELED / REALIZED / SURPRISE (D92)
#
# THE OWNER'S FRAMING (2026-09-14): this product has a MODELED layer (what
# could be -- the screen, the forecast), a REALIZED layer (what happened --
# the first-seen ledger, the closure ledger, the filings pipeline), and the
# difference between them is where the new information is. A map that only
# drew the model would be a map of our own assumptions; a map that only drew
# the ledger would be a history. SURPRISE is the only one of the three that is
# not already somewhere else on this page.
#
# ONE FILE, THREE BLOCKS, ONE LAZY FETCH. `forecast.json` is fetched the first
# time the mode is switched off "Off", exactly like character.json and
# dot.json. It is deliberately NOT part of any gap file: a viewer who never
# opens the mode pays nothing, and the 90-second full export is not the price
# of a fresh forecast vintage (`loci forecast-export` rewrites this one file).
#
# THE THREE BLOCKS ARE INDEPENDENTLY AVAILABLE. `modeled` needs the forecast
# tables, `realized` needs only the ledgers this repo has had since D79/D88,
# and `surprise` needs BOTH plus a scored outcome. Each carries its own
# `available` + `reason`, because "the model has not been fitted for grocery"
# and "nothing has been scored yet" are different sentences and neither of
# them is zero.
#
# WHAT THE MODEL FORECASTS, AND THE LINE THAT MUST TRAVEL WITH IT (D88): the
# retrodiction found the screen ranks retail streets out of sample and the
# go-dark test was null. So `p_opening` is a probability of ENTRY -- somebody
# opens here -- and NOT a probability that the business survives, is viable,
# or is a good investment. Every legend and popup that shows a p prints that.
FORECAST_FILE = "forecast.json"

#: The data-scientist thread's contract (2026-09-14). Read through the two
#: VIEWS where they exist, because the views are where "newest vintage" and
#: "newest scored outcome" are already resolved; the base tables are the
#: fallback so an export can still run between their migration and their view.
FORECAST_TABLE = ("analysis", "forecast")
FORECAST_OUTCOME_TABLE = ("analysis", "forecast_outcome")
FORECAST_LATEST_VIEW = ("analysis", "forecast_latest")
FORECAST_SURPRISE_VIEW = ("analysis", "forecast_surprise_nta")
#: One row per issued vintage, carrying `issued_at` -- the ONLY real timestamp
#: reachable from `forecast_surprise_nta`, which publishes `issued_month` and
#: `model_version` and no clock of its own. See `_vintage_clock`.
FORECAST_RUN_TABLE = ("analysis", "forecast_run")

#: The columns each relation must carry for its block to be exported. Named
#: here once so `forecast_missing` can say WHICH column is absent rather than
#: reporting a bare "not available".
FORECAST_LATEST_COLUMNS = ("address_id", "category", "p_opening")
FORECAST_VINTAGE_COLUMNS = ("issued_month", "model_version", "horizon_months")
#: sql/028's own column names. `z_clustered` is the HEADLINE z and `z_naive`
#: ships beside it so the popup can show the design effect between them.
FORECAST_SURPRISE_COLUMNS = ("nta_code", "category", "expected", "realized",
                             "surprise", "z_clustered")
#: sql/028's surprise view emits a synthetic '(all)' category row alongside the
#: real ones. It is not a business category on this map and is dropped here --
#: the map's own all-opportunities mode is a different union (lead category per
#: address), and painting one under the other's name would be a quiet lie.
SURPRISE_POOLED_CATEGORY = "(all)"
#: The packed row, by name. `z` is the CLUSTER-ROBUST z and is the only one
#: the fill reads; `zNaive` is carried so the popup can show the design
#: effect between the two rather than leaving the reader to trust one number.
SURPRISE_COLS = ("nta", "expected", "realized", "surprise", "z", "zNaive",
                 "nAddresses", "nCells")

#: The realized ledgers. Both already exist (sql/018 + sql/027 for presence and
#: closure, sql/020 for the filings pipeline), so the REALIZED block works on a
#: database that has never seen a forecast.
PRESENCE_VIEW = ("analysis", "poi_first_seen")
FILING_PIPELINE_TABLE = ("analysis", "storefront_pipeline")

#: Only these two `first_seen_kind`s carry a real date. 'observed' means "we
#: first saw it in this month's snapshot" and 'backfill_censored' means "it was
#: already there when the ledger opened" -- drawing either as an OPENING would
#: turn our own snapshot cadence into a market event.
DATED_FIRST_SEEN_KINDS = ("source_date", "gov_filing")
REALIZED_MONTHS = 12

#: p is shipped as an INTEGER PERMILLE. 0.0 - 1.0 at 3 decimal places is the
#: most precision a forecast of this kind can carry honestly, and an integer
#: costs three characters where "0.137" costs five across ~645k slots.
P_SCALE = 1000
Z_DP = 2
#: Ramp stops are permille too, so the browser never mixes the two scales.
FORECAST_RAMP_STOPS = 5

#: MODELED -- a SEQUENTIAL single hue, light -> dark, because p is a magnitude.
#: Violet, and violet specifically: red is spent on the character ramp, blue on
#: the DOT count points, and those two are the overlays that can be on screen
#: at the same time as this one. Five stops (not the character ramp's six) so
#: that every step can clear the ORDINAL 2:1 floor against the page surface --
#: these are DOTS, not polygons, and a dot that recedes into the background is
#: not "near zero", it is invisible.
#: dataviz validator, `--ordinal --mode light --surface #f3f0ea`: monotone L,
#: every adjacent gap >= 0.06, light end 2.19:1, hue spread 6 deg. ALL PASS.
FORECAST_RAMP = ("#aa9bdc", "#8d7bcb", "#7060b2", "#534493", "#382674")
#: The same hue re-stepped for a dark surface (#17181a), not a second palette:
#: `--ordinal --mode dark`, light end 2.02:1, hue spread 2 deg. ALL PASS. The
#: page is light-only today; this ships so a future dark mode does not invent
#: its own colours, and the UI selects between the two by reading the page's
#: OWN background token (charDark), never `prefers-color-scheme`.
FORECAST_RAMP_DARK = ("#4f4083", "#66549f", "#7e6cba", "#9787d2", "#b3a6e8")
#: An address the model did not forecast. Grey, a legend key of its own, and
#: NEVER the pale end of the ramp -- on a light-to-dark scale the palest dot is
#: the most confident "almost certainly nothing opens here", which is the exact
#: opposite of "the model has nothing to say about this address".
FORECAST_NODATA_COLOR = CHARACTER_NODATA_COLOR
FORECAST_NODATA_COLOR_DARK = CHARACTER_NODATA_COLOR_DARK

#: SURPRISE -- DIVERGING: two poles and a NEUTRAL GREY midpoint, which is the
#: only legal encoding for a signed quantity. Warm = the market did MORE than
#: the model expected, cool = LESS, grey = about what was expected. The sign
#: convention is printed in the legend because a diverging ramp whose direction
#: is left to the reader is a coin flip.
#: dataviz validator on the four arms, `--pairs all --mode light --surface
#: #f3f0ea`: lightness band PASS, chroma floor PASS, worst all-pairs CVD dE
#: 15.6 (protan), worst normal-vision dE 21.1. The two mild steps sit at
#: 2.0-2.2:1 and take the documented RELIEF: every key is labelled with its
#: sign and its z range, and the popup prints expected, realized and z as
#: numbers, so identity is never colour-alone.
SURPRISE_COLORS = ("#1c5cab", "#6da7ec", "#eae7e0", "#ef8f80", "#c0392b")
#: Re-stepped for the dark surface: poles dE 20.1 CVD / 26.6 normal, mild steps
#: dE 17.4 / 22.5, every step >= 3:1. ALL PASS.
SURPRISE_COLORS_DARK = ("#2d6fbd", "#5793df", "#383835", "#d07a69", "#b8483a")
#: The z breaks between those five classes. +-0.5 is "indistinguishable from
#: the model" and +-2 is the two-sigma edge; a finer scale would be a precision
#: claim an entry model measured on one 12-month window cannot support.
SURPRISE_STOPS = (-2.0, -0.5, 0.5, 2.0)
SURPRISE_LABELS = (
    "far below the model", "below the model", "about as modeled",
    "above the model", "far above the model",
)
#: An NTA with NO EXPECTED VALUE IS NOT DRAWN. Not grey, not zero, not the
#: neutral midpoint -- no fill at all, and a dashed outline plus its own legend
#: key. "The model was never asked about this neighborhood" and "the model was
#: asked and the market matched it" are the two readings a neutral-grey polygon
#: would fuse, and fusing them is the single way this layer can lie.
SURPRISE_NODATA_COLOR = CHARACTER_NODATA_COLOR
SURPRISE_NODATA_COLOR_DARK = CHARACTER_NODATA_COLOR_DARK

#: Rendered UNTRUNCATED wherever the mode is on, same contract the character
#: and age-fit caveats live under.
FORECAST_CAVEATS = {
    "modeled": (
        "This is a forecast of ENTRY, not of viability. The D88 retrodiction found the "
        "screen ranks retail streets out of sample and the go-dark test was null, so a "
        "high probability here means 'somebody is likely to open a business of this kind "
        "at this address in the next 12 months' and says nothing about whether that "
        "business survives, earns, or is worth financing. It is not a recommendation and "
        "it does not enter gap_score, the supply ratio or any recommendation grade."
    ),
    "realized": (
        "Openings are FIRST-SEEN dates on the presence ledger, not licence dates: only "
        "the two dated kinds (a source-published open date and a government filing) are "
        "drawn, because 'observed' means we first saw it in that month's snapshot and "
        "'backfill_censored' means it was already there when the ledger opened. Closures "
        "are roughly 3% ascertained -- they come from source-published closure records "
        "(Foursquare), so ABSENCE IS NOT A CLOSURE and the closed marks are a floor, "
        "never a rate. Pipeline entries are filings that have not yet produced an "
        "inspection, a licence or an active liquor record; many never will."
    ),
    "surprise": (
        "Surprise is RELATIVE TO AN ENTRY MODEL, not to the market. It is realized "
        "openings minus what this model expected, standardised -- so a neighborhood can "
        "read 'far above the model' because the market moved OR because the model is "
        "poorly specified there, and this map cannot tell you which. Realized counts "
        "inherit the ledger's own coverage: a neighborhood our sources cover thinly will "
        "look like it under-performed. Read it as a pointer at where to look, never as a "
        "measurement of performance."
    ),
}


def permille(value) -> int | None:
    """A probability as an integer permille, or None. None survives as JSON
    null all the way to the browser: an address the model did not score is not
    an address it scored at zero, and packing the two the same way is how a
    map starts inventing forecasts."""
    if value is None:
        return None
    v = float(value)
    if v != v:                                  # NaN
        return None
    return int(round(max(0.0, min(1.0, v)) * P_SCALE))


def _relation_columns(con, rel: tuple[str, str]) -> set[str]:
    schema, name = rel
    return {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ?", [schema, name]).fetchall()}


def _first_present(cols: set[str], *names: str) -> str | None:
    """The first of `names` this relation actually has. The data-scientist
    thread owns those tables, so a column it renames must degrade to a stated
    reason here, never to a KeyError halfway through an export."""
    for n in names:
        if n in cols:
            return n
    return None


def forecast_missing(con) -> list[str]:
    """Every named relation/column the MODELED block needs and this database
    does not have. Empty means the block can be exported."""
    latest = _relation_columns(con, FORECAST_LATEST_VIEW)
    base = _relation_columns(con, FORECAST_TABLE)
    src, cols = (FORECAST_LATEST_VIEW, latest) if latest else (FORECAST_TABLE, base)
    name = ".".join(src)
    if not cols:
        return [f"{'.'.join(FORECAST_LATEST_VIEW)} / {'.'.join(FORECAST_TABLE)} (absent)"]
    return [f"{name}.{c}" for c in FORECAST_LATEST_COLUMNS if c not in cols]


def has_forecast(con) -> bool:
    return not forecast_missing(con)


def surprise_missing(con) -> list[str]:
    """Every named column the SURPRISE block needs and `analysis.
    forecast_surprise_nta` does not have. `_first_present` is used for the two
    columns the data-scientist thread may spell differently; everything else is
    named exactly."""
    cols = _relation_columns(con, FORECAST_SURPRISE_VIEW)
    name = ".".join(FORECAST_SURPRISE_VIEW)
    if not cols:
        return [f"{name} (absent)"]
    miss = []
    for c in FORECAST_SURPRISE_COLUMNS:
        if c == "z_clustered":
            if not _first_present(cols, "z_clustered", "z", "z_score"):
                miss.append(f"{name}.z_clustered")
        elif c == "expected":
            if not _first_present(cols, "expected", "expected_openings"):
                miss.append(f"{name}.expected")
        elif c == "realized":
            if not _first_present(cols, "realized", "realized_openings"):
                miss.append(f"{name}.realized")
        elif c not in cols:
            miss.append(f"{name}.{c}")
    return miss


def forecast_vintage(con) -> dict:
    """The issued month, the model version and the horizon of the NEWEST
    vintage, plus the newest month anything has been scored in. The header is
    required to print the first two: a probability with no vintage ages into a
    lie exactly the way the pipeline overlay's `cutoff` does."""
    out = {"issuedMonth": None, "modelVersion": None, "horizonMonths": None,
           "scoredMonth": None, "nVintages": 0}
    cols = _relation_columns(con, FORECAST_TABLE)
    if cols and "issued_month" in cols:
        sel = ["max(issued_month)"]
        sel.append("count(DISTINCT issued_month)")
        row = con.execute(
            f"SELECT {', '.join(sel)} FROM {'.'.join(FORECAST_TABLE)}").fetchone()
        out["issuedMonth"] = None if row[0] is None else str(row[0])
        out["nVintages"] = int(row[1] or 0)
        if out["issuedMonth"]:
            # AUDIT FINDING 8, SECOND SITE. `max(model_version)` inside the
            # newest issued_month is the same git-hash sort as surprise_vintage
            # had, and unlike that one it MANIFESTS TODAY: over the five live
            # 2026-09 vintages it returns '0.1.1+f1cb6628' (issued 09-14 23:27)
            # instead of '0.1.1+51bab17f' (09-15 17:53), so every exported map
            # header stamped the wrong model version. Pick by the real clock --
            # `frozen_at` on this table, the same column sql/028's
            # `forecast_latest` was fixed to use -- and keep the version string
            # only as the deterministic tiebreak.
            extra = [c for c in ("model_version", "horizon_months") if c in cols]
            if extra:
                if "model_version" in extra and "frozen_at" in cols:
                    mv = con.execute(
                        f"SELECT model_version FROM {'.'.join(FORECAST_TABLE)} "
                        f"WHERE issued_month = ? "
                        f"ORDER BY frozen_at DESC, model_version DESC LIMIT 1",
                        [out["issuedMonth"]]).fetchone()
                    out["modelVersion"] = (None if not mv or mv[0] is None
                                           else str(mv[0]))
                    extra = [c for c in extra if c != "model_version"]
            if extra:
                r = con.execute(
                    f"SELECT {', '.join('max(' + c + ')' for c in extra)} "
                    f"FROM {'.'.join(FORECAST_TABLE)} WHERE issued_month = ?",
                    [out["issuedMonth"]]).fetchone()
                for key, val in zip(extra, r):
                    if key == "model_version":
                        out["modelVersion"] = None if val is None else str(val)
                    else:
                        out["horizonMonths"] = None if val is None else int(val)
    ocols = _relation_columns(con, FORECAST_OUTCOME_TABLE)
    if ocols and "scored_month" in ocols:
        r = con.execute(
            f"SELECT max(scored_month) FROM {'.'.join(FORECAST_OUTCOME_TABLE)}").fetchone()
        out["scoredMonth"] = None if r[0] is None else str(r[0])
    return out


def gap_id_order(con, boroughs: list[str]) -> dict[str, list[str]]:
    """The address order of every `gaps/<cat>.json` this export writes, WITHOUT
    building the layers.

    This is what lets `loci forecast-export` rewrite one small file in seconds
    instead of paying the 90-second full export for a new forecast vintage.
    The predicate is `_gap_sql`'s, plus `pack_gaps`'s own lon/lat drop, stated
    here rather than inferred -- if the two ever diverge the p values would be
    silently attached to the wrong doorways, which is the single worst thing
    this layer could do."""
    ph = ", ".join("?" for _ in boroughs)
    order: dict[str, list[str]] = {}
    for cat in ALLCATS:
        order[cat] = [r[0] for r in con.execute(f"""
            SELECT g.address_id
            FROM analysis.address_gaps g
            WHERE g.borough IN ({ph})
              AND g.{cat}_ratio > 1
              AND g.lon IS NOT NULL AND g.lat IS NOT NULL
            ORDER BY g.address_id
        """, list(boroughs)).fetchall()]
    return order


def pack_modeled(p_by_cat: dict[str, dict[str, float]],
                 order: dict[str, list[str]]) -> dict[str, dict]:
    """{category: {address_id: p}} + the gap files' address order -> the
    per-category payload the browser paints with.

    SPARSE OR DENSE, WHICHEVER IS SMALLER, and the block says which. `idx` +
    `p` costs two numbers per scored address; a dense `p` with nulls costs one
    slot per address in the file whether it was scored or not. At full coverage
    dense is half the size; at 5% coverage sparse is a twentieth. The browser
    reads `encoding` rather than guessing from the array lengths."""
    out: dict[str, dict] = {}
    for cat, ids in order.items():
        scores = p_by_cat.get(cat) or {}
        if not scores:
            continue
        idx, vals = [], []
        for j, aid in enumerate(ids):
            pm = permille(scores.get(aid))
            if pm is None:
                continue
            idx.append(j)
            vals.append(pm)
        if not vals:
            continue
        dense = len(idx) * 2 > len(ids)
        block = {"n": len(ids), "nForecast": len(vals),
                 "encoding": "dense" if dense else "sparse",
                 "pMin": min(vals), "pMax": max(vals),
                 "stops": quantile_stops([float(v) for v in vals], FORECAST_RAMP_STOPS)}
        block["stops"] = [int(round(s)) for s in block["stops"]]
        # Strictly increasing after the integer round, because MapLibre's
        # `interpolate` rejects a repeated stop and a saturated forecast
        # produces plenty of them.
        for i in range(1, len(block["stops"])):
            if block["stops"][i] <= block["stops"][i - 1]:
                block["stops"][i] = block["stops"][i - 1] + 1
        if dense:
            slots: list[int | None] = [None] * len(ids)
            for j, v in zip(idx, vals):
                slots[j] = v
            block["p"] = slots
        else:
            block["idx"] = idx
            block["p"] = vals
        out[cat] = block
    return out


def _months_back(month: str, n: int) -> list[str]:
    """`n` consecutive 'YYYY-MM' strings ENDING at `month`, oldest first."""
    y, m = int(month[:4]), int(month[5:7])
    out = []
    for k in range(n - 1, -1, -1):
        yy, mm = divmod((y * 12 + (m - 1)) - k, 12)
        out.append(f"{yy:04d}-{mm + 1:02d}")
    return out


def realized_asof(con) -> str | None:
    """The newest month either ledger has anything dated in. The window is
    counted back from the DATA, not from today's clock: a map built on a
    six-month-old snapshot must say so rather than drawing six empty months."""
    try:
        row = con.execute(f"""
            SELECT max(greatest(coalesce(first_seen_on, DATE '1900-01-01'),
                                coalesce(closed_on,     DATE '1900-01-01')))
            FROM {'.'.join(PRESENCE_VIEW)}
        """).fetchone()
    except Exception:
        return None
    if not row or row[0] is None or str(row[0])[:4] == "1900":
        return None
    return str(row[0])[:7]


def _realized_sql(boroughs: list[str], start: str) -> tuple[str, list]:
    """Openings and closures for the window, one row per ledger location.
    `kind` is 'open' or 'closed' so a single pass produces both marks.

    `analysis.poi_first_seen` stores the borough NAME, not the code every other
    layer here uses, so the filter is built from BOROUGH_NAMES rather than from
    the codes -- a hard-coded 'MN' would silently export nothing.

    The closed branch gates on `model.poi_presence.poi_is_open` -- the ONE
    shared open/closed/unknown predicate (owner rule, GTM-153) -- rather than
    a bare `closed_on IS NOT NULL`, so this map and the recommendation
    ledger's `still_open` component (model/recommendation_ledger.py) read the
    SAME closure verdict. `closed_on` still supplies the DATE: no other
    closed basis in the predicate carries one, so a location that reads
    'closed' only via a DCWP/DOHMH/SLA/DOS basis has no month to bucket into
    and does not appear on this dated timeline -- unchanged from before,
    since `closed_on` was already the only closure evidence this query used."""
    from loci.model.poi_presence import poi_is_open

    names = [BOROUGH_NAMES[b] for b in boroughs]
    ph = ", ".join("?" for _ in names)
    kinds = ", ".join("?" for _ in DATED_FIRST_SEEN_KINDS)
    status = poi_is_open("p", "f.closed_on")
    sql = f"""
        SELECT 'open' AS kind, category, lon, lat, display_name,
               strftime(first_seen_on, '%Y-%m') AS month, first_seen_kind AS src
        FROM {'.'.join(PRESENCE_VIEW)}
        WHERE borough IN ({ph})
          AND first_seen_kind IN ({kinds})
          AND first_seen_on IS NOT NULL
          AND strftime(first_seen_on, '%Y-%m') >= ?
          AND lon IS NOT NULL AND lat IS NOT NULL
        UNION ALL
        SELECT 'closed', f.category, f.lon, f.lat, f.display_name,
               strftime(f.closed_on, '%Y-%m'), f.closed_src
        FROM {'.'.join(PRESENCE_VIEW)} f
        LEFT JOIN staging.poi p ON p.poi_id = f.poi_id_latest
        WHERE f.borough IN ({ph})
          AND {status} = 'closed'
          AND strftime(f.closed_on, '%Y-%m') >= ?
          AND f.lon IS NOT NULL AND f.lat IS NOT NULL
    """
    params = names + list(DATED_FIRST_SEEN_KINDS) + [start] + names + [start]
    return sql, params


def _pipeline_entry_sql(boroughs: list[str], start: str) -> tuple[str, list]:
    """Filings that have ENTERED the pipeline in the window and have not opened.
    `is_open` false is the whole point of the mark: this is a business someone
    has committed money to and that no regulator has yet seen operating."""
    ph = ", ".join("?" for _ in boroughs)
    sql = f"""
        SELECT loci_category, lon, lat, business_name,
               strftime(entry_date, '%Y-%m') AS month, entry_stage
        FROM {'.'.join(FILING_PIPELINE_TABLE)}
        WHERE borough IN ({ph})
          AND is_open = FALSE
          AND loci_category IS NOT NULL
          AND entry_date IS NOT NULL
          AND strftime(entry_date, '%Y-%m') >= ?
          AND lon IS NOT NULL AND lat IS NOT NULL
        ORDER BY entry_date
    """
    return sql, list(boroughs) + [start]


class _Marks:
    """One category's three realized mark sets, dictionary-encoded.

    Parallel arrays and not a numeric stride, for the reason every other block
    here uses them: a name is a string and a month is a small vocabulary, and a
    stride slot can hold neither without either bloating the file or inventing
    a sentinel."""

    def __init__(self, months: list[str]):
        self.month_at = {m: i for i, m in enumerate(months)}
        self.names: list[str] = []
        self._name_at: dict[str, int] = {}
        self.stages: list[str] = []
        self._stage_at: dict[str, int] = {}
        self.open = {"lon": [], "lat": [], "m": [], "nm": []}
        self.closed = {"lon": [], "lat": [], "m": [], "nm": []}
        self.pipe = {"lon": [], "lat": [], "m": [], "nm": [], "st": []}

    def _name(self, value) -> int:
        key = (value or "").strip()
        if key not in self._name_at:
            self._name_at[key] = len(self.names)
            self.names.append(key)
        return self._name_at[key]

    def _stage(self, value) -> int:
        key = (value or "").strip() or "unknown"
        if key not in self._stage_at:
            self._stage_at[key] = len(self.stages)
            self.stages.append(key)
        return self._stage_at[key]

    def add(self, bucket: str, lon, lat, name, month, stage=None) -> None:
        mi = self.month_at.get(month)
        if mi is None or lon is None or lat is None:
            return
        b = getattr(self, bucket)
        b["lon"].append(round(float(lon), COORD_DP))
        b["lat"].append(round(float(lat), COORD_DP))
        b["m"].append(mi)
        b["nm"].append(self._name(name))
        if stage is not None:
            b["st"].append(self._stage(stage))

    def n(self) -> int:
        return len(self.open["m"]) + len(self.closed["m"]) + len(self.pipe["m"])

    def pack(self) -> dict:
        out = {"names": self.names, "stages": self.stages}
        for key in ("open", "closed", "pipe"):
            b = dict(getattr(self, key))
            b["n"] = len(b["m"])
            out[key] = b
        return out


def collect_realized(con, boroughs: list[str]) -> dict:
    """The REALIZED block: openings, closures and un-opened pipeline entries
    for the last `REALIZED_MONTHS` months, per category.

    Degrades to an unavailable block with a reason rather than raising -- the
    presence ledger is `loci poi-snapshot`'s output and a fresh clone has not
    run it."""
    asof = realized_asof(con)
    if asof is None:
        return {"available": False,
                "reason": f"{'.'.join(PRESENCE_VIEW)} has no dated row — "
                          "run `loci poi-snapshot`",
                "months": [], "cats": [], "byCat": {}}
    months = _months_back(asof, REALIZED_MONTHS)
    marks: dict[str, _Marks] = {c: _Marks(months) for c in ALLCATS}
    sql, params = _realized_sql(boroughs, months[0])
    for kind, cat, lon, lat, name, month, _src in con.execute(sql, params).fetchall():
        if cat in marks:
            marks[cat].add("open" if kind == "open" else "closed", lon, lat, name, month)
    try:
        psql, pparams = _pipeline_entry_sql(boroughs, months[0])
        pipe_rows = con.execute(psql, pparams).fetchall()
    except Exception:
        # No sql/020 in this database. The two ledgers still draw; the legend
        # says the third mark is not in this export rather than showing none.
        pipe_rows = []
    for cat, lon, lat, name, month, stage in pipe_rows:
        if cat in marks:
            marks[cat].add("pipe", lon, lat, name, month, stage)
    by_cat = {c: m.pack() for c, m in marks.items() if m.n()}
    return {"available": True, "reason": None,
            "asof": asof, "from": months[0], "to": months[-1],
            "months": months, "monthsBack": REALIZED_MONTHS,
            "cats": sorted(by_cat), "byCat": by_cat,
            "n": sum(m.n() for m in marks.values()),
            "pipelineAvailable": bool(pipe_rows)}


#: AUDIT FINDING 8 -- LATEST-BY-STRING-SORT.
#: `model_version` is '<semver>+<8 hex git-ish hash>'. `ORDER BY model_version
#: DESC` therefore orders two vintages issued in the SAME `issued_month` by the
#: HEX, which is arbitrary. Live on 2026-09-16 five 2026-09 vintages exist and
#: their true issue order (`analysis.forecast_run.issued_at`) is
#:
#:   0.1.0+f7d190df  2026-09-14 11:53
#:   0.1.1+3cd0e269  2026-09-14 22:51
#:   0.1.1+f1cb6628  2026-09-14 23:27
#:   0.1.1+ae3eadb3  2026-09-15 08:54
#:   0.1.1+51bab17f  2026-09-15 17:53   <- the newest
#:
#: while the lexicographic maximum is `0.1.1+f1cb6628`, purely on 'f' > '5'.
#: sql/028:330 fixed `analysis.forecast_latest` this way (frozen_at DESC first,
#: model_version DESC only as a deterministic tiebreak); this is the same fix
#: applied to the two picks webmap_export makes for itself.
def _vintage_clock(con) -> tuple[str, str] | None:
    """(join clause, timestamp expression) that puts a REAL issue time beside a
    relation carrying `issued_month` + `model_version`, or None.

    Preference order, and why: `analysis.forecast_run` holds one row per issued
    vintage and is six rows wide, so joining it costs nothing;
    `analysis.forecast.frozen_at` is the same clock seventeen seconds earlier
    but lives on 25M rows and has to be grouped. Neither is invented here --
    both are objects sql/028 already creates. When NEITHER is present (an older
    database) the caller degrades to the version-string order rather than
    raising, which is the behaviour that shipped before this fix."""
    run = _relation_columns(con, FORECAST_RUN_TABLE)
    if run and {"issued_month", "model_version", "issued_at"} <= run:
        return (f"LEFT JOIN {'.'.join(FORECAST_RUN_TABLE)} r "
                f"USING (issued_month, model_version)", "r.issued_at")
    base = _relation_columns(con, FORECAST_TABLE)
    if base and {"issued_month", "model_version", "frozen_at"} <= base:
        return (f"LEFT JOIN (SELECT issued_month, model_version, "
                f"max(frozen_at) AS frozen_at FROM {'.'.join(FORECAST_TABLE)} "
                f"GROUP BY 1, 2) r USING (issued_month, model_version)",
                "r.frozen_at")
    return None


def surprise_vintage(con) -> dict | None:
    """WHICH scored vintage the surprise layer draws. The newest `scored_month`
    first, then the newest `issued_month` scored in it -- so a 2023-01 vintage
    scored last month beats a 2026-09 vintage that nothing has scored yet, which
    is the right answer: an unscored forecast has no surprise.

    One triple, filtered on explicitly. Pooling two vintages would average a
    model against its own successor and call the difference a market."""
    cols = _relation_columns(con, FORECAST_SURPRISE_VIEW)
    if not cols or "scored_month" not in cols:
        return None
    # AUDIT FINDING 8: the newest vintage is the one ISSUED last, not the one
    # whose git hash sorts highest. `_vintage_clock` brings that timestamp into
    # scope; `model_version DESC` survives only as the deterministic tiebreak
    # for two vintages issued in the same microsecond.
    clock = _vintage_clock(con)
    join, ts = clock if clock else ("", None)
    order = ("scored_month DESC, issued_month DESC, model_version DESC"
             if ts is None else
             f"v.scored_month DESC, max({ts}) DESC NULLS LAST, "
             f"v.issued_month DESC, v.model_version DESC")
    row = con.execute(f"""
        SELECT v.scored_month, v.issued_month, v.model_version,
               max(v.horizon_elapsed)
        FROM {'.'.join(FORECAST_SURPRISE_VIEW)} v
        {join}
        WHERE v.scored_month IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY {order}
        LIMIT 1
    """).fetchone()
    if not row:
        return None
    return {"scoredMonth": str(row[0]), "issuedMonth": str(row[1]),
            "modelVersion": str(row[2]),
            "horizonElapsed": None if row[3] is None else int(row[3])}


def collect_surprise(con, boroughs: list[str]) -> dict:
    """The SURPRISE block: one row per NTA x category for ONE scored vintage,
    cols/rows packed the way clusters.json and dot.json already are.

    TWO THINGS THIS BLOCK REFUSES TO DO, and they are the whole reason it is
    written out rather than selected straight into the browser:

      (a) AN NTA WITH NO EXPECTED VALUE IS NOT EMITTED AT ALL. Not with a null
          expected, not with a zero -- the row does not exist, so nothing
          downstream can paint it even by accident.

      (b) A NULL `z_clustered` IS NOT REPLACED BY `z_naive`. sql/028 returns
          NULL below five clusters because "a sandwich variance from three
          clusters is not an estimate", and substituting the naive z -- which
          that same header says is 3-5x too confident -- would be this map
          drawing exactly the significance the SQL declined to claim. The row
          still ships (its counts are real); it is drawn as NOT MEASURED, and
          `zNaive` rides along so the popup can show the design effect.
    """
    missing = surprise_missing(con)
    if missing:
        return {"available": False, "reason": "missing: " + ", ".join(missing),
                "cols": list(SURPRISE_COLS), "byCat": {}, "cats": [], "n": 0,
                "vintage": None, "nNoZ": 0}
    cols = _relation_columns(con, FORECAST_SURPRISE_VIEW)
    exp = _first_present(cols, "expected", "expected_openings")
    real = _first_present(cols, "realized", "realized_openings")
    zc = _first_present(cols, "z_clustered", "z", "z_score")
    zn = _first_present(cols, "z_naive")
    naddr = _first_present(cols, "n_addresses")
    ncell = _first_present(cols, "n_cells")
    surp = _first_present(cols, "surprise")
    vintage = surprise_vintage(con)
    where, params = "", []
    if vintage:
        where = "WHERE scored_month = ? AND issued_month = ? AND model_version = ?"
        params = [vintage["scoredMonth"], vintage["issuedMonth"], vintage["modelVersion"]]
    # The view carries no borough of its own; the NTA code's two-letter prefix
    # is the borough, and that is what the filter is built on -- the same codes
    # every other layer here uses.
    prefixes = tuple(boroughs)
    rows = con.execute(f"""
        SELECT nta_code, category, {exp}, {real},
               {surp or 'NULL'}, {zc}, {zn or 'NULL'},
               {naddr or 'NULL'}, {ncell or 'NULL'}
        FROM {'.'.join(FORECAST_SURPRISE_VIEW)}
        {where}
        ORDER BY category, nta_code
    """, params).fetchall()
    by_cat: dict[str, list] = {}
    no_z = 0
    for nta, cat, expected, realized, surprise, z_cl, z_nv, n_addr, n_cell in rows:
        if not nta or cat == SURPRISE_POOLED_CATEGORY or cat not in CATEGORIES:
            continue
        if not str(nta)[:2] in prefixes:
            continue
        # (a): no expectation, no row.
        if expected is None:
            continue
        if z_cl is None:
            no_z += 1
        by_cat.setdefault(cat, []).append([
            nta,
            _num(expected, 2),
            None if realized is None else int(realized),
            _num(surprise, 2),
            None if z_cl is None else round(float(z_cl), Z_DP),
            None if z_nv is None else round(float(z_nv), Z_DP),
            None if n_addr is None else int(n_addr),
            None if n_cell is None else int(n_cell),
        ])
    return {"available": bool(by_cat),
            "reason": None if by_cat else
                      "no scored outcome yet — run `loci forecast score`",
            "cols": list(SURPRISE_COLS),
            "vintage": vintage,
            "byCat": by_cat, "cats": sorted(by_cat),
            "n": sum(len(v) for v in by_cat.values()),
            "nNoZ": no_z,
            "zKind": "clustered" if zc in ("z_clustered",) else zc}


def empty_forecast(reason: str | None = None) -> dict:
    """The shape the browser gets when nothing has been forecast. Every key the
    UI reads is present and empty, so the mode renders a stated not-measured
    state instead of throwing on a missing block."""
    return {
        "available": False, "reason": reason or "no forecast in this database",
        "issuedMonth": None, "modelVersion": None, "horizonMonths": None,
        "scoredMonth": None, "pScale": P_SCALE, "cats": [],
        "modeled": {"available": False, "reason": reason or "not built",
                    "byCat": {}, "cats": []},
        "realized": {"available": False, "reason": "not read",
                     "months": [], "cats": [], "byCat": {}},
        "surprise": {"available": False, "reason": "not read",
                     "cols": list(SURPRISE_COLS), "vintage": None,
                     "byCat": {}, "cats": [], "n": 0, "nNoZ": 0},
        "caveats": dict(FORECAST_CAVEATS),
    }


def collect_forecast(con, boroughs: list[str],
                     gap_ids: dict[str, list[str]] | None = None) -> dict:
    """Read all three blocks. Pure read -- `--dry-run` and a real write share
    this one code path and cannot disagree about the counts.

    `gap_ids` is the address order of the gap files. `collect()` passes the
    layers it just built; `loci forecast-export` re-derives it with
    `gap_id_order`, which is the whole reason this file can be rewritten
    without the 90-second export."""
    for b in boroughs:
        if b not in BOROUGH_NAMES:
            raise ValueError(f"unknown borough {b!r}; expected one of {sorted(BOROUGH_NAMES)}")
    vintage = forecast_vintage(con)
    missing = forecast_missing(con)
    if missing:
        modeled = {"available": False, "reason": "missing: " + ", ".join(missing),
                   "byCat": {}, "cats": []}
    else:
        latest = _relation_columns(con, FORECAST_LATEST_VIEW)
        src = FORECAST_LATEST_VIEW if latest else FORECAST_TABLE
        cols = latest or _relation_columns(con, FORECAST_TABLE)
        where, params = "", []
        # The base table holds every vintage; the view holds only the newest.
        # Reading the base table without this filter would average a September
        # forecast against a January one and call it "the model".
        if not latest and "issued_month" in cols and vintage["issuedMonth"]:
            where = "WHERE issued_month = ?"
            params = [vintage["issuedMonth"]]
        rows = con.execute(f"""
            SELECT address_id, category, p_opening
            FROM {'.'.join(src)} {where}
        """, params).fetchall()
        # The table exists but is empty -- `loci forecast issue` has not run.
        # Short-circuit BEFORE `gap_id_order`, which is fifteen scans of
        # analysis.address_gaps that would buy nothing.
        if not rows:
            return _forecast_bundle(
                con, boroughs, vintage,
                {"available": False,
                 "reason": f"{'.'.join(src)} is empty — run `loci forecast issue`",
                 "source": ".".join(src), "cats": [], "byCat": {}, "n": 0})
        if gap_ids is None:
            gap_ids = gap_id_order(con, boroughs)
        p_by_cat: dict[str, dict[str, float]] = {}
        for aid, cat, p in rows:
            if cat in CATEGORIES and aid is not None and p is not None:
                p_by_cat.setdefault(cat, {})[str(aid)] = p
        by_cat = pack_modeled(p_by_cat, gap_ids)
        modeled = {
            "available": bool(by_cat),
            "reason": None if by_cat else
                      "the forecast table holds no row for any address in this export",
            "source": ".".join(src), "cats": sorted(by_cat), "byCat": by_cat,
            "n": sum(b["nForecast"] for b in by_cat.values()),
        }
    return _forecast_bundle(con, boroughs, vintage, modeled)


def _forecast_bundle(con, boroughs: list[str], vintage: dict, modeled: dict) -> dict:
    """The three blocks assembled into the file. Split out so the "no forecast
    issued yet" path and the full path assemble the SAME shape -- a not-measured
    state that is missing keys is a not-measured state the UI will crash on."""
    realized = collect_realized(con, boroughs)
    surprise = collect_surprise(con, boroughs)
    cats = sorted(set(modeled.get("cats") or [])
                  | set(realized.get("cats") or [])
                  | set(surprise.get("cats") or []))
    return {
        "available": bool(cats),
        "reason": None if cats else "no forecast, no ledger and no scored outcome",
        "boroughs": list(boroughs),
        "issuedMonth": vintage["issuedMonth"], "modelVersion": vintage["modelVersion"],
        "horizonMonths": vintage["horizonMonths"], "scoredMonth": vintage["scoredMonth"],
        "nVintages": vintage["nVintages"],
        "pScale": P_SCALE, "cats": cats,
        "modeled": modeled, "realized": realized, "surprise": surprise,
        "caveats": dict(FORECAST_CAVEATS),
    }


def forecast_meta(fc: dict | None) -> dict:
    """The DATA-FREE half of the block: what the sidebar needs to draw the
    segmented control, the two ramps and the legends. The 645k probabilities,
    the marks and the NTA table stay in forecast.json and are fetched only when
    the mode is switched on."""
    fc = fc or empty_forecast()
    return {
        "available": bool(fc.get("available")),
        "reason": fc.get("reason"),
        "file": FORECAST_FILE,
        "issuedMonth": fc.get("issuedMonth"),
        "modelVersion": fc.get("modelVersion"),
        "horizonMonths": fc.get("horizonMonths"),
        "scoredMonth": fc.get("scoredMonth"),
        "pScale": P_SCALE,
        "cats": fc.get("cats") or [],
        "modeledCats": (fc.get("modeled") or {}).get("cats") or [],
        "realizedCats": (fc.get("realized") or {}).get("cats") or [],
        "surpriseCats": (fc.get("surprise") or {}).get("cats") or [],
        "monthsBack": REALIZED_MONTHS,
        "rampColors": list(FORECAST_RAMP),
        "rampColorsDark": list(FORECAST_RAMP_DARK),
        "noDataColor": FORECAST_NODATA_COLOR,
        "noDataColorDark": FORECAST_NODATA_COLOR_DARK,
        "surpriseColors": list(SURPRISE_COLORS),
        "surpriseColorsDark": list(SURPRISE_COLORS_DARK),
        "surpriseStops": list(SURPRISE_STOPS),
        "surpriseLabels": list(SURPRISE_LABELS),
        "surpriseNoDataColor": SURPRISE_NODATA_COLOR,
        "surpriseNoDataColorDark": SURPRISE_NODATA_COLOR_DARK,
        "caveats": dict(FORECAST_CAVEATS),
    }


def write_forecast(fc: dict, out_dir: pathlib.Path) -> dict[str, int]:
    """Write forecast.json ALONE. `loci forecast-export` calls this; the full
    export calls it through `write`. One writer, so the two can never produce a
    different file."""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(fc, separators=(",", ":"))
    (out_dir / FORECAST_FILE).write_text(text)
    return {FORECAST_FILE: len(text.encode())}


def patch_meta_forecast(fc: dict, out_dir: pathlib.Path) -> bool:
    """Refresh meta.json's `forecast` block in place, and ONLY that block.

    The sidebar section is gated on `META.forecast` (the same contract the
    character, pipeline and storefront sections have), so a new vintage written
    by `loci forecast-export` alone would otherwise be invisible until someone
    paid the 90-second full export. `forecast_meta` is the single writer of
    that block in both commands, so the two cannot drift; everything else in
    meta.json is read and written back byte-identical.

    Returns False when there is no meta.json to patch -- `loci export-webmap`
    has not run, and the map has bigger problems than a stale legend."""
    out_dir = pathlib.Path(out_dir)
    path = out_dir / "meta.json"
    if not path.exists():
        return False
    meta = json.loads(path.read_text())
    meta["forecast"] = forecast_meta(fc)
    path.write_text(json.dumps(meta, separators=(",", ":")))
    return True


def forecast_summary(fc: dict | None) -> dict:
    """What `--dry-run` prints. Read off the PACKED block, never re-queried, so
    a dry run cannot report a count the real file does not carry."""
    fc = fc or empty_forecast()
    m, r, s = fc.get("modeled") or {}, fc.get("realized") or {}, fc.get("surprise") or {}
    return {
        "issuedMonth": fc.get("issuedMonth"), "modelVersion": fc.get("modelVersion"),
        "scoredMonth": fc.get("scoredMonth"),
        "modeled": {c: b["nForecast"] for c, b in (m.get("byCat") or {}).items()},
        "modeledAvailable": bool(m.get("available")), "modeledReason": m.get("reason"),
        "realized": {c: {k: b[k]["n"] for k in ("open", "closed", "pipe")}
                     for c, b in (r.get("byCat") or {}).items()},
        "realizedWindow": [r.get("from"), r.get("to")],
        "realizedAvailable": bool(r.get("available")), "realizedReason": r.get("reason"),
        "surprise": {c: len(v) for c, v in (s.get("byCat") or {}).items()},
        "surpriseAvailable": bool(s.get("available")), "surpriseReason": s.get("reason"),
    }


# ------------------------------------------------------------------- export

def _gaps_columns(con) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'address_gaps'").fetchall()}


def has_pipeline_columns(con) -> bool:
    """True when analysis.address_gaps exposes all seven PIPELINE_GAP_COLUMNS.
    A database predating `loci pipeline` exports the slots as nulls rather than
    failing -- the map degrades to "no pipeline reading", never to a 500."""
    return set(PIPELINE_GAP_COLUMNS) <= _gaps_columns(con)


def has_storefront_columns(con) -> bool:
    """True when analysis.address_gaps exposes all five STOREFRONT_GAP_COLUMNS.
    A database predating `loci storefronts` exports the slots as nulls rather
    than failing -- the map degrades to "no vacancy reading", never to a 500."""
    return set(STOREFRONT_GAP_COLUMNS) <= _gaps_columns(con)


def has_density_columns(con) -> bool:
    """True when analysis.address_gaps exposes both walk-shed density columns.
    A database predating `loci supply-ratio`'s density sweep exports the
    cluster list unranked-by-density rather than failing -- the map degrades to
    "ordered by size", labelled as such, never to a size order wearing a
    density label."""
    return {"walkshed_km2_400m", "density_400m"} <= _gaps_columns(con)


def has_age_fit_columns(con) -> bool:
    """True when analysis.address_gaps exposes all three AGE_FIT_GAP_COLUMNS.
    A database predating `loci age-fit apply` exports them as nulls rather than
    failing -- the map degrades to "no age-adjusted score", never to a 500 and
    never to a neutral 1.0."""
    return set(AGE_FIT_GAP_COLUMNS) <= _gaps_columns(con)


def has_censoring_columns(con) -> bool:
    """True when analysis.address_gaps exposes the D75 censoring flags -- the
    address-grain `lead_censored` and all fifteen `{cat}_censored`. A database
    written before D75 exports them as nulls rather than failing, and the UI
    then says nothing about censoring instead of asserting "measured" (same
    degrade-don't-lie contract as the three blocks above)."""
    cols = _gaps_columns(con)
    return set(CENSORED_GAP_COLUMNS) <= cols and all(f"{c}_censored" in cols for c in ALLCATS)


def has_frame_columns(con) -> bool:
    """True when analysis.address_gaps exposes the D84 sampling-frame columns.
    A database written before D84 holds one frame and exports every dot as a
    lot, which is exactly what it was -- the same degrade-don't-lie contract as
    the blocks above."""
    return {"frame", "frontage_m", "street_name"} <= _gaps_columns(con)


def has_age_fit_source(con) -> bool:
    """True when analysis.address_category exists AND carries
    `age_fit_source`. False is the state of a database that has never run the
    per-category age-fit writer, and of the fixtures that do not build the
    table at all; the join is then skipped and `ageFit.sourceJoined` in
    meta.json says so, rather than the export failing on a missing table."""
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ?",
        list(AGE_FIT_SOURCE_TABLE)).fetchall()
    return AGE_FIT_SOURCE_COLUMN in {r[0] for r in rows}


def age_fit_caveat() -> str:
    """model/age_fit.AGE_FIT_DISCLAIMER, VERBATIM.

    Imported lazily because that module pulls in osmnx (via
    model/address_gaps) and this one must stay importable without it. One
    source of truth on purpose: a map carrying a paraphrase of a caveat the
    model owns is how a caveat quietly gets softer than the finding it guards.
    """
    from loci.model.age_fit import AGE_FIT_DISCLAIMER

    return AGE_FIT_DISCLAIMER


def age_fit_curves(curve_dir: pathlib.Path | None = None) -> dict[str, dict]:
    """{category: summary} for every curve `loci age-fit fit` has left on disk.

    A curve file on disk is the definition of LIVE: a fit that fails its own
    F2/F3 gate is never written, and D69 retired pharmacy's by MOVING the stale
    JSON out of this directory. So the presence of the file -- not a registry
    entry, not a non-null column -- is what the map may say it has a curve for.

    Never raises on a malformed or unreadable file: a curve this function
    cannot parse is simply not live, which is the safe direction."""
    out: dict[str, dict] = {}
    d = AGE_FIT_DIR if curve_dir is None else pathlib.Path(curve_dir)
    if not d.is_dir():
        return out
    for p in sorted(d.glob(AGE_FIT_GLOB)):
        try:
            fit = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(fit, dict):
            continue
        cat = fit.get("category") or p.stem.replace("age_fit_", "")
        inputs = fit.get("inputs") or {}
        mult = fit.get("multiplier") or {}
        out[cat] = {
            "spec": fit.get("spec"),
            "fittedAt": fit.get("fitted_at"),
            "supplyHash": inputs.get("supply_hash"),
            "screenSupplyHash": inputs.get("screen_supply_hash"),
            "acsYear": inputs.get("acs_year"),
            "nTarget": inputs.get("n_target"),
            "radiusM": fit.get("radius_m"),
            "primaryAgeTerm": fit.get("primary_age_term"),
            # The band, carried because D69 requires the multiplier never to
            # render without its MOE -- childcare's is three times bar's, and a
            # legend that cannot say so invites the reader to compare them.
            "medianMoe": mult.get("median_moe"),
            "p10": mult.get("p10"), "p50": mult.get("p50"), "p90": mult.get("p90"),
        }
    return out


def age_fit_meta(prov: dict | None = None, curve_dir: pathlib.Path | None = None,
                 source_joined: bool = True, columns_present: bool = True) -> dict:
    """The `ageFit` block meta.json carries: which categories have a LIVE
    curve, what each was fitted on and when, and the caveat verbatim.

    `stale` is the same check `supply_warning` makes for the supply set: a
    curve fitted against one supply and applied to gaps measured against
    another is a multiplier the model never estimated on these addresses. It is
    reported rather than enforced here -- `model/age_fit.check_fit_is_current`
    is the gate; this is the map saying on its own face what it is drawing."""
    curves = age_fit_curves(curve_dir)
    gaps_hash = (prov or {}).get("supply_hash")
    stale = sorted(c for c, v in curves.items()
                   if gaps_hash and v["supplyHash"] and v["supplyHash"] != gaps_hash)
    warning = None
    if stale:
        warning = (
            f"AGE-FIT SUPPLY MISMATCH: {', '.join(stale)} "
            f"{'curves were' if len(stale) > 1 else 'curve was'} fitted against a "
            f"different supply than the gaps on this map (gaps {gaps_hash}). The "
            f"age-adjusted ranking is a multiplier estimated on a supply these "
            f"addresses were not screened against. Re-run `loci age-fit fit` then "
            f"`loci age-fit apply`.")
    return {
        "available": bool(curves) and columns_present,
        "categories": sorted(curves),
        "curves": curves,
        "columns": list(AGE_FIT_GAP_COLUMNS),
        # False here means the three columns are absent from address_gaps
        # entirely: every multiplier in every gap file is null because nothing
        # was ever applied, NOT because the curves say neutral.
        "columnsPresent": bool(columns_present),
        "sourceJoined": bool(source_joined),
        "gapsSupplyHash": gaps_hash,
        "stale": stale,
        "warning": warning,
        # Rendered UNTRUNCATED by the UI, same rule as demand_caveat_text
        # (D49/D57). Three sentences; dropping the third is dropping the one
        # that says resident age is a proxy for a bundle.
        "caveat": age_fit_caveat(),
    }


def collect_vacant_detail(con, boroughs: list[str]) -> dict[str, tuple]:
    """The {storefront_id: (address, prior use)} lookup the gap layers' vacancy
    popups hang off, or {} when there is no snapshot to read. Never raises: a
    database with no storefront registry exports gap files whose `vacants`
    dictionary is simply empty."""
    if not has_storefront(con):
        return {}
    asof, _src = storefront_asof(con, boroughs)
    if asof is None:
        return {}
    pick = snapshot_filing(con, boroughs, asof)
    return {} if pick is None else vacant_detail(con, boroughs, pick[0])


def gap_provenance(con, boroughs: list[str]) -> dict:
    """The supply set the EXPORTED gap rows were actually measured against,
    read from `analysis.address_gaps.supply_set/supply_hash` (sql/006).

    Restricted to the exported boroughs on purpose: the citywide table can hold
    pre-D52 NULL rows for boroughs this map never draws, and those must not
    raise a false alarm about the two it does.

    Returns supply_set/supply_hash of the DOMINANT variant plus every variant
    seen, and never raises: a database whose address_gaps predates the D52
    columns reports `supply_set=None`, which is itself the finding.
    """
    cols = _gaps_columns(con)
    if not {"supply_set", "supply_hash"} <= cols:
        return {"supply_set": None, "supply_hash": None, "variants": [], "mixed": False}
    ph = ", ".join("?" for _ in boroughs)
    rows = con.execute(
        f"""SELECT supply_set, supply_hash, count(*) AS n
            FROM analysis.address_gaps
            WHERE borough IN ({ph})
            GROUP BY 1, 2 ORDER BY n DESC, 1, 2""", list(boroughs)).fetchall()
    variants = [{"supply_set": s, "supply_hash": h, "n": int(n)} for s, h, n in rows]
    top = variants[0] if variants else {"supply_set": None, "supply_hash": None}
    return {"supply_set": top["supply_set"], "supply_hash": top["supply_hash"],
            "variants": variants, "mixed": len(variants) > 1}


def supply_warning(supply_set: str, prov: dict) -> str | None:
    """None when the export's supply set matches what the gaps were measured
    against; otherwise the sentence to shout in the terminal AND to carry in
    meta.json so the map itself says it.

    This is the whole point of the D52 fix: a map whose gap layer was measured
    against one supply and whose known-location layer draws another is not a
    validation surface, it is a way to talk yourself out of a real gap."""
    got = prov.get("supply_set")
    if prov.get("mixed"):
        seen = ", ".join(f"{v['supply_set'] or 'unrecorded'} ({v['n']:,} rows)"
                         for v in prov["variants"])
        return (f"MIXED SUPPLY PROVENANCE: analysis.address_gaps holds more than one "
                f"supply set for these boroughs -- {seen}. The gap layers on this map "
                f"were not all measured against the same supply. Re-run "
                f"`loci address-gaps --supply-set {supply_set}` for every borough here.")
    if got is None:
        return (f"NO SUPPLY PROVENANCE: analysis.address_gaps records no supply_set for "
                f"these boroughs (rows written before D52). This export draws known "
                f"locations from the {supply_set!r} set, but what the gaps were measured "
                f"against is unrecorded -- the two layers may disagree and nothing here "
                f"can tell. Re-run `loci address-gaps --supply-set {supply_set}`.")
    if got != supply_set:
        return (f"SUPPLY-SET MISMATCH: the gaps in analysis.address_gaps were measured "
                f"against {got!r} (supply_hash {prov.get('supply_hash')}), but this export "
                f"draws known locations from {supply_set!r}. Every gap on the map would be "
                f"checked by eye against a supply the model never used. Either export with "
                f"--supply-set {got}, or re-run `loci address-gaps --supply-set {supply_set}`.")
    return None


def collect(con, boroughs: list[str], supply_set: str = DEFAULT_SUPPLY_SET,
            curve_dir: pathlib.Path | None = None) -> dict:
    """Read both layers out of the database. Pure read -- writes nothing, so
    `--dry-run` and a real export share this one code path and can never
    disagree about the counts."""
    for b in boroughs:
        if b not in BOROUGH_NAMES:
            raise ValueError(f"unknown borough {b!r}; expected one of {sorted(BOROUGH_NAMES)}")
    supply_predicate(supply_set)      # raises on a typo, before any query runs

    sources = [r[0] for r in con.execute(
        "SELECT DISTINCT source_id FROM staging.poi ORDER BY 1").fetchall()]
    dcats = detail_cats(con)
    sql, params = _poi_sql(boroughs, dcats, supply_set)
    poi_layers = pack_pois(con.execute(sql, params).fetchall(), boroughs, sources,
                           dcats, supply_set)

    # A database built before the pipeline columns landed still exports; the
    # gap layers then carry the same slots filled with nothing, so the browser
    # never has to branch on which vintage of file it fetched.
    pipe_cols = has_pipeline_columns(con)
    shop_cols = has_storefront_columns(con)
    # Same contract for the D63/D69 ranking columns and for the per-category
    # `age_fit_source` they are labelled with.
    age_cols = has_age_fit_columns(con)
    age_src = has_age_fit_source(con)
    # Same contract again for the D75 censoring flags.
    cens_cols = has_censoring_columns(con)
    # ...and for the D84 sampling frame.
    frame_cols = has_frame_columns(con)
    # One read of the vacant-storefront lookup for all sixteen gap files: the
    # same ~3,800 rows stand behind every category.
    vacants = collect_vacant_detail(con, boroughs)
    # One read of the character views for all sixteen gap files AND all 111
    # neighbourhood files. `{}` when sql/021 has not run, which packs as a
    # column of nulls the UI draws as "no data".
    characters = collect_character_detail(con, boroughs)
    character = collect_character(con, boroughs)
    # Same one-read-for-all-sixteen-files contract, for D82 legality (AC-5):
    # `{}` when `loci address-legality build` has not run, which packs as a
    # column of nulls -- markers stay drawn (D75), just unlabelled.
    legalities = collect_legality_detail(con, boroughs)
    gap_layers = {}
    for cat in ALLCATS:
        sql, params = _gap_sql(cat, boroughs, pipe_cols, shop_cols, age_cols, age_src,
                               cens_cols, frame_cols)
        gap_layers[cat] = pack_gaps(con.execute(sql, params).fetchall(), boroughs,
                                    cat, vacants, characters, legalities)

    # Navigation bounds, derived from the addresses themselves rather than a
    # separate boundary file -- a neighborhood the export cannot show is a
    # neighborhood the picker must not offer.
    ph = ", ".join("?" for _ in boroughs)
    # `nta` rides along so the all-opportunities mode can turn a name the user
    # typed into the file it has to fetch. min() rather than any_value() only
    # for determinism -- name and NTA code are 1:1 across MN+BK.
    nbhd = [
        {"name": n, "boro": b, "nta": nta,
         "bounds": [round(v, COORD_DP) for v in (x0, y0, x1, y1)]}
        for n, b, nta, x0, y0, x1, y1 in con.execute(
            f"""SELECT neighborhood, borough, min(nta_code),
                       min(lon), min(lat), max(lon), max(lat)
                FROM analysis.address_gaps
                WHERE borough IN ({ph}) AND neighborhood IS NOT NULL
                GROUP BY 1, 2 ORDER BY 1""", list(boroughs)).fetchall()
    ]
    boro_bounds = {}
    for row in nbhd:
        b = row["boro"]
        cur = boro_bounds.get(b)
        x0, y0, x1, y1 = row["bounds"]
        boro_bounds[b] = [x0, y0, x1, y1] if cur is None else [
            min(cur[0], x0), min(cur[1], y0), max(cur[2], x1), max(cur[3], y1)]

    prov = gap_provenance(con, boroughs)
    # The all-opportunities layers carry the SAME supply provenance as the
    # per-category ones -- they are the same rows, sliced by neighborhood
    # instead of by category, and a view that could not say what supply it was
    # measured against would be the one place on this map D52 did not reach.
    nta = collect_nta(con, boroughs, supply_set, prov.get("supply_hash"), vacants,
                      characters, character.get("ntas") or {})
    # D92 modeled/realized/surprise. The gap layers were just built, so their
    # address order is free here -- `collect_forecast` re-derives it with
    # `gap_id_order` only when `loci forecast-export` rewrites the one file.
    forecast = collect_forecast(
        con, boroughs, {c: gap_layers[c]["ids"] for c in ALLCATS})
    return {"boroughs": boroughs, "sources": sources, "detailCats": dcats,
            "pois": poi_layers, "gaps": gap_layers, "neighborhoods": nbhd,
            "boroBounds": boro_bounds, "alcohol": collect_alcohol(con, boroughs),
            "pipeline": collect_pipeline(con, boroughs),
            "storefronts": collect_storefronts(con, boroughs),
            "character": character,
            "forecast": forecast,
            "nta": nta,
            # The owner's 2026-09-13 ranking ruling, as data the map reads
            # rather than an order baked into a sort call: the ranked cluster
            # list, and the per-neighborhood density the picker orders by.
            "clusters": collect_clusters(con, boroughs),
            "ntaDensities": nta_densities(con, boroughs),
            "supplySet": supply_set, "supplyProvenance": prov,
            "supplyWarning": supply_warning(supply_set, prov),
            "ageFit": age_fit_meta(prov, curve_dir, source_joined=age_src,
                                   columns_present=age_cols)}


def summarize(bundle: dict) -> dict:
    """Counts per category per borough. This is what `--dry-run` prints and
    what the UI reads out of meta.json.

    `poi` counts ONLY points in the selected supply set -- that is what the
    sidebar calls "known locations", and it has to be the same number the gap
    layer was measured against. The dropped records are counted separately in
    `excluded` rather than as a fourth key inside `poi`, so no reader can add
    them into a supply total by accident."""
    boroughs = bundle["boroughs"]
    poi_counts, gap_counts, exc_counts = {}, {}, {}
    for cat in ALLCATS:
        layer = bundle["pois"][cat]
        det = layer.get("detail")
        stride = layer["stride"]
        per = {b: {"all": 0, "corroborated": 0, "single": 0} for b in boroughs}
        xper = {b: 0 for b in boroughs}
        if det:
            for v in per.values():
                # `graded`/`cuisine` count points with DOHMH detail; `active`
                # counts those DOHMH calls open. Points with no DOHMH member
                # are counted in neither -- unknown is not inactive.
                v.update({"dohmh": 0, "active": 0, "inactive": 0, "cuisine": 0})
        pts = layer["pts"]
        for i in range(0, len(pts), stride):
            b = boroughs[int(pts[i + 2])]
            if not pts[i + 4]:
                xper[b] += 1
                continue
            corroborated = bin(int(pts[i + 3])).count("1") >= 2
            per[b]["all"] += 1
            per[b]["corroborated" if corroborated else "single"] += 1
            if det:
                j = i // stride
                act = det["active"][j]
                per[b]["dohmh"] += int(act != -1)
                per[b]["active"] += int(act == 1)
                per[b]["inactive"] += int(act == 0)
                per[b]["cuisine"] += int(det["cuisine"][j] != -1)
        poi_counts[cat] = per
        exc_counts[cat] = xper
        glayer = bundle["gaps"][cat]
        gpts, gst = glayer["pts"], glayer["stride"]
        gper = {b: 0 for b in boroughs}
        for i in range(0, len(gpts), gst):
            gper[boroughs[int(gpts[i + 2])]] += 1
        gap_counts[cat] = gper
    return {"poi": poi_counts, "gap": gap_counts, "excluded": exc_counts,
            "pipeline": pipeline_summary(bundle.get("pipeline"), boroughs),
            "storefront": storefront_summary(bundle.get("storefronts"), boroughs),
            "character": character_summary(bundle.get("character"),
                                           bundle.get("gaps")),
            "forecast": forecast_summary(bundle.get("forecast"))}


def character_summary(layer: dict | None, gaps: dict | None = None) -> dict:
    """Neighbourhoods per dominant label, and how many gap ADDRESSES carry no
    label at all -- what `--dry-run` prints. Counted off the PACKED layer
    rather than re-queried, so the numbers on the terminal are the numbers in
    the files.

    The unlabelled count is the one that matters before shipping: it is the
    size of the grey class, and a large one means `loci address-character
    build` has not finished, not that the city has no character."""
    if not layer:
        layer = empty_character("no character layer in this bundle")
    labelled = unlabelled = 0
    for glayer in (gaps or {}).values():
        block = glayer.get("character") or {}
        for i in block.get("label", []):
            if i is None:
                unlabelled += 1
            else:
                labelled += 1
    return {"available": bool(layer.get("available")),
            "reason": layer.get("reason"),
            "ramp": bool(layer.get("ramp")),
            "rampReason": layer.get("rampReason"),
            "suppressed": layer.get("suppressed", 0),
            "labels": layer.get("labels", []),
            "counts": layer.get("counts", {}),
            "n": layer.get("n", 0), "nShapes": layer.get("nShapes", 0),
            "provenance": layer.get("provenance", {}),
            "gapAddressesLabelled": labelled,
            "gapAddressesUnlabelled": unlabelled}


def storefront_summary(layer: dict | None, boroughs: list[str]) -> dict:
    """Vacant premises per borough, per consecutive-years band, and how many
    report construction -- what `--dry-run` prints. Counted off the PACKED
    layer rather than re-queried, so the numbers on the terminal are the
    numbers in the file.

    The registered totals ride alongside because a vacancy count without its
    denominator is not a vacancy rate; the CLI prints both or neither."""
    if not layer:
        layer = empty_storefronts(boroughs)
    per_band = {lab: {b: 0 for b in boroughs} for lab in layer["bandLabels"]}
    constr = {b: 0 for b in boroughs}
    pts, st = layer["pts"], layer["stride"]
    for i in range(0, len(pts), st):
        b = boroughs[int(pts[i + 2])]
        per_band[layer["bandLabels"][int(pts[i + 3])]][b] += 1
        constr[b] += int(pts[i + 4])
    totals = layer.get("totals") or {}
    return {"available": bool(layer.get("available")),
            "asof": layer.get("asof"), "filingDate": layer.get("filingDate"),
            "universe": layer.get("universe"), "vintage": layer.get("vintage"),
            "bandLabels": layer["bandLabels"], "bands": per_band,
            "construction": constr,
            "totals": {b: totals.get(b, {}) for b in boroughs},
            "n": layer["n"]}


def pipeline_summary(layer: dict | None, boroughs: list[str]) -> dict:
    """Jobs and units per stage and per size band, per borough -- what
    `--dry-run` prints. Counted off the PACKED layer rather than re-queried, so
    the numbers on the terminal are the numbers in the file."""
    if not layer:
        layer = empty_pipeline(boroughs)
    per_band = {lab: {b: 0 for b in boroughs} for lab in layer["bandLabels"]}
    per_band_units = {lab: 0 for lab in layer["bandLabels"]}
    co = {c: 0 for c in layer["co"]}
    pts, st = layer["pts"], layer["stride"]
    for i in range(0, len(pts), st):
        b = boroughs[int(pts[i + 2])]
        units = int(pts[i + 5])
        lab = layer["bandLabels"][pipeline_band(units)]
        per_band[lab][b] += 1
        per_band_units[lab] += units
        co[layer["co"][int(pts[i + 4])]] += 1
    return {"available": bool(layer.get("available")),
            "asof": layer.get("asof"), "vintage": layer.get("vintage"),
            "cutoff": layer.get("cutoff"),
            "stages": layer["stages"], "stageLabels": layer["stageLabels"],
            "counts": layer["counts"], "units": layer["units"],
            "bandLabels": layer["bandLabels"], "bands": per_band,
            "bandUnits": per_band_units, "co": co, "n": layer["n"]}


def write(bundle: dict, out_dir: pathlib.Path) -> dict[str, int]:
    """Write meta.json + gaps/<cat>.json + pois/<cat>.json. Returns
    {relative path: bytes} so the caller can report file sizes without
    re-statting."""
    out_dir = pathlib.Path(out_dir)
    (out_dir / "pois").mkdir(parents=True, exist_ok=True)
    (out_dir / "gaps").mkdir(parents=True, exist_ok=True)
    counts = summarize(bundle)
    written: dict[str, int] = {}

    def _dump(rel: str, obj) -> None:
        p = out_dir / rel
        text = json.dumps(obj, separators=(",", ":"))
        p.write_text(text)
        written[rel] = len(text.encode())

    for cat in ALLCATS:
        _dump(f"pois/{cat}.json", bundle["pois"][cat])
        _dump(f"gaps/{cat}.json", bundle["gaps"][cat])

    # Its own file, fetched only when the overlay is switched on.
    alcohol = bundle.get("alcohol") or empty_alcohol(bundle["boroughs"])
    _dump("alcohol.json", alcohol)

    # Same contract for the development-pipeline overlay: one small file,
    # fetched only when the toggle is switched on.
    pipeline = bundle.get("pipeline") or empty_pipeline(bundle["boroughs"])
    _dump("pipeline.json", pipeline)

    # Same contract for the vacant-storefront overlay.
    shops = bundle.get("storefronts") or empty_storefronts(bundle["boroughs"])
    _dump("storefronts.json", shops)

    # ...and for the neighbourhood-character overlay, which carries its own
    # dissolved NTA outlines. One file, fetched only when the toggle is
    # switched on, so the single-business view costs exactly what it did
    # before this existed.
    character = bundle.get("character") or empty_character("no character layer")
    _dump("character.json", character)

    # ...and for the D92 modeled/realized/surprise mode. Same lazy contract:
    # one file, fetched only when the mode leaves "Off", so the single-business
    # view costs exactly what it did before this existed. Written through
    # `write_forecast` rather than `_dump` so that `loci forecast-export` and
    # `loci export-webmap` cannot produce two different files.
    forecast = bundle.get("forecast") or empty_forecast("no forecast layer")
    written.update(write_forecast(forecast, out_dir))

    # One file per neighborhood plus a small index. Both are fetched only when
    # the all-opportunities mode is entered, so the single-business view costs
    # exactly what it did before this existed.
    nta_layers = bundle.get("nta") or {}
    if nta_layers:
        (out_dir / NTA_DIR).mkdir(parents=True, exist_ok=True)
        for code in sorted(nta_layers):
            _dump(f"{NTA_DIR}/{code}.json", nta_layers[code])
        _dump(f"{NTA_DIR}/index.json",
              nta_index(nta_layers, bundle["boroughs"],
                        bundle.get("supplySet", DEFAULT_SUPPLY_SET),
                        (bundle.get("supplyProvenance") or {}).get("supply_hash"),
                        bundle.get("ntaDensities"),
                        (bundle.get("clusters") or {}).get("rankBy", "density")))

    # The ranked cluster list. Its own file, fetched only by a view that wants
    # the ordering -- the single-business view costs exactly what it did.
    clusters = bundle.get("clusters") or {
        "available": False, "rankBy": "units", "rankLabel": RANK_LABELS["units"],
        "caveat": DENSITY_CAVEAT, "cols": CLUSTER_COLUMNS, "rows": [], "n": 0}
    _dump("clusters.json", clusters)

    meta = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "boroughs": bundle["boroughs"],
        "boroughNames": {b: BOROUGH_NAMES[b] for b in bundle["boroughs"]},
        "sources": bundle["sources"],
        "detailCats": bundle.get("detailCats", []),
        "detailSource": DOHMH_SOURCE,
        "cats": ALLCATS,
        "catLabels": [CATEGORIES[c].label for c in ALLCATS],
        "colors": {c: COLORS[c] for c in ALLCATS},
        "reach_m": load_reach("tiers"),
        "poiCounts": counts["poi"],
        "gapCounts": counts["gap"],
        "excludedCounts": counts["excluded"],
        # D52 provenance. `set` is what THIS export drew; `gapsSet`/`gapsHash`
        # are what analysis.address_gaps says the gap layer was measured
        # against. `warning` is non-null exactly when the map must say on its
        # own face that its two layers disagree.
        "supply": {
            "set": bundle.get("supplySet", DEFAULT_SUPPLY_SET),
            "sets": sorted(SUPPLY_SETS),
            "gapsSet": (bundle.get("supplyProvenance") or {}).get("supply_set"),
            "gapsHash": (bundle.get("supplyProvenance") or {}).get("supply_hash"),
            "mixed": bool((bundle.get("supplyProvenance") or {}).get("mixed")),
            "warning": bundle.get("supplyWarning"),
        },
        # The overlay's legend and totals. `available` false means
        # `loci ingest-alcohol` has not run -- the UI says so rather than
        # showing a confident zero.
        "alcohol": {"available": bool(alcohol.get("available")),
                    "classes": alcohol["classes"],
                    "classLabels": alcohol["classLabels"],
                    "counts": alcohol["counts"],
                    "n": alcohol["n"]},
        # The development-pipeline overlay's legend, its counts, and — the part
        # the UI is REQUIRED to print — the two dates that bound what it knows:
        # `asof` (the run the completion window counts back from) and `cutoff`
        # (the newest filing/permit DCP's release carries). Everything filed or
        # permitted after `cutoff` is absent, so the coming-units number is a
        # floor. A legend without those dates ages into a lie.
        "pipeline": {"available": bool(pipeline.get("available")),
                     "asof": pipeline.get("asof"),
                     "asofSource": pipeline.get("asofSource"),
                     "vintage": pipeline.get("vintage"),
                     "cutoff": pipeline.get("cutoff"),
                     "source": pipeline.get("source"),
                     "provenance": pipeline.get("provenance"),
                     "minUnits": pipeline["minUnits"],
                     "completeMonths": pipeline["completeMonths"],
                     "stages": pipeline["stages"],
                     "stageLabels": pipeline["stageLabels"],
                     "bands": pipeline["bands"],
                     "bandLabels": pipeline["bandLabels"],
                     "counts": pipeline["counts"],
                     "units": pipeline["units"],
                     "bandCounts": pipeline["bandCounts"],
                     "gapColumns": list(PIPELINE_GAP_COLUMNS),
                     "n": pipeline["n"]},
        # The vacant-storefront overlay's legend, its counts, and the three
        # facts without which the layer misleads: `asof` (the observation date
        # the snapshot is taken at), `filingDate` (when owners filed it), and
        # `totals` (every REGISTERED storefront in the same filing, per
        # borough). The vacancy rate on this map is only readable because the
        # denominator ships with the numerator -- a self-reported registry
        # cannot tell "nothing is empty here" from "nobody here filed".
        "storefront": {"available": bool(shops.get("available")),
                       "asof": shops.get("asof"),
                       "asofSource": shops.get("asofSource"),
                       "filingDate": shops.get("filingDate"),
                       "universe": shops.get("universe"),
                       "vintage": shops.get("vintage"),
                       "source": shops.get("source"),
                       "provenance": shops.get("provenance"),
                       "radiusM": STOREFRONT_RADIUS_M,
                       "bands": shops["bands"],
                       "bandLabels": shops["bandLabels"],
                       "counts": shops["counts"],
                       "construction": shops["construction"],
                       "totals": shops["totals"],
                       "gapColumns": list(STOREFRONT_GAP_COLUMNS),
                       "n": shops["n"]},
        # The D63/D69 age-fit ranking signal. `categories` is what the map may
        # offer the age-adjusted ranking for -- a category with no live curve
        # gets a disabled toggle, never a silent fallback to gap_score under an
        # age-adjusted label. `caveat` is rendered UNTRUNCATED wherever a
        # multiplier appears, and every multiplier shows its MOE (D69).
        "ageFit": bundle.get("ageFit") or age_fit_meta(
            bundle.get("supplyProvenance"), source_joined=False,
            columns_present=False),
        # The neighbourhood-character legend (owner request 2026-09-13).
        # DATA-FREE on purpose: the 111 blocks and the outlines live in
        # character.json, and this is only what the sidebar needs to draw the
        # toggle, the four keys and the rule beside each. `rules` and the
        # thresholds inside them are FORMATTED FROM model/address_character.py's
        # constants (see `character_rules`), never retyped, so a retuned
        # threshold reaches this legend on the next export. `available` false
        # means sql/021 or `loci address-character build` has not run, and
        # `reason` names the missing column.
        "character": {"available": bool(character.get("available")),
                      "reason": character.get("reason"),
                      "file": "character.json",
                      "labels": character["labels"],
                      "labelText": character["labelText"],
                      # The DEFAULT view: a sequential ramp on retail_index.
                      # `ramp: false` means `retail_index` has not shipped yet
                      # and the UI draws the four-class fill instead.
                      "ramp": character["ramp"],
                      "rampReason": character["rampReason"],
                      "rampColors": character["rampColors"],
                      "rampColorsDark": character["rampColorsDark"],
                      "riRange": character["riRange"],
                      "riStops": character["riStops"],
                      "riScale": character["riScale"],
                      "overlayLabels": character["overlayLabels"],
                      "suppressed": character["suppressed"],
                      "copy": character["copy"],
                      "colors": character["colors"],
                      "colorsDark": character["colorsDark"],
                      "noDataColor": character["noDataColor"],
                      "noDataColorDark": character["noDataColorDark"],
                      "rules": character["rules"],
                      "caveat": character["caveat"],
                      "counts": character["counts"],
                      "provenance": character["provenance"],
                      "n": character["n"], "nShapes": character["nShapes"],
                      "labelled": counts["character"]["gapAddressesLabelled"],
                      "unlabelled": counts["character"]["gapAddressesUnlabelled"]},
        # The D92 modeled/realized/surprise legend. DATA-FREE on purpose (see
        # `forecast_meta`): the probabilities, the marks and the NTA surprise
        # table live in forecast.json, and this is only what the sidebar needs
        # to draw the segmented control and its two ramps. The three
        # `*Cats` lists are what the mode may be offered FOR -- a category with
        # no forecast gets an explicit "not modeled", never a map of zeros.
        "forecast": forecast_meta(forecast),
        "neighborhoods": bundle["neighborhoods"],
        "boroBounds": bundle["boroBounds"],
        # The all-opportunities mode. `available` false means this export
        # wrote no per-NTA files, and the UI hides the mode rather than
        # offering a button that 404s.
        "nta": {"available": bool(nta_layers),
                "dir": NTA_DIR,
                "n": len(nta_layers),
                "addresses": sum(L["n"] for L in nta_layers.values())},
        # THE ORDERING, ON THE FACE OF THE MAP (owner ruling 2026-09-13, "rank
        # by density"). `rankBy` is what every ranked list in this export is
        # actually sorted by -- it reads "units" when supply-ratio has not run,
        # so the UI labels a size order as a size order instead of calling it
        # density. `caveat` is rendered UNTRUNCATED wherever a density appears.
        "rankBy": clusters["rankBy"],
        "rankLabel": clusters["rankLabel"],
        "densityCaveat": DENSITY_CAVEAT,
        "clusters": {"available": bool(clusters.get("available")),
                     "file": "clusters.json",
                     "cols": clusters["cols"],
                     "n": clusters["n"]},
    }
    _dump("meta.json", meta)
    return written


def write_address_index(con, boroughs: list[str], out_dir: pathlib.Path) -> int:
    """`webmap/data/address_index.json` -- `{"values": [...], "idx": {bbl:
    [address_id, legality_idx, histdist, landmark]}}` for every LOT-FRAME
    address in `boroughs` (D99/GTM-171, extended D104-followup/GTM-169 so a
    searched address that is NOT a gap for the selected category still gets
    a legality line instead of a bare "Address found" card).

    The browser search box resolves a GeoSearch hit's BBL to a Loci
    `address_id` locally, without a round trip, by the same bbl-first rule
    `loci.geo.geosearch.snap()` uses server-side (design-allocator-report.md
    S4/S5) -- so a hit this file cannot resolve still gets the fallback
    `/api/snap?lat&lon` route, never a wrong address. That server-side
    fallback carries no legality reading, same as before this change.

    `values` is `LEGALITY_VALUES` (the same order `legAt()`/`legHTML()`
    already read out of every `gaps/<cat>.json`, D82) -- `legality_idx`
    indexes into it, or is `null` when `collect_legality_detail` has no
    reading for the address (no `loci address-legality build` yet, or the
    address predates it). `histdist`/`landmark` are 1/0/null card-label
    flags, same contract `_Legality.add` uses -- kept as small ints, never
    re-spelled as strings per row, so the file stays cheap to ship even
    though every LOT-FRAME address now carries four values instead of one.

    LOT-FRAME ONLY: street-midpoint rows (D84, `frame = 'street'`) have no
    BBL to key on -- PLUTO's lot ownership means nothing at a street
    midpoint -- so they are absent from this file by construction, not
    filtered out after the fact. `bbl IS NOT NULL` is belt and braces for the
    same reason.

    Plain (uncompressed) JSON, like every other file `write()` produces --
    `webmap/server.js` already gzips any static file over 2 KB on the way
    out (module docstring, "the server gzips it"), so a second,
    pre-compressed copy would just be a second file to keep in sync.
    """
    rows = con.execute(
        f"""
        SELECT bbl, address_id
        FROM analysis.address
        WHERE borough IN ({', '.join('?' for _ in boroughs)})
          AND COALESCE(frame, 'lot') = 'lot'
          AND bbl IS NOT NULL
        """,
        list(boroughs),
    ).fetchall()
    detail = collect_legality_detail(con, boroughs)  # {} when has_legality() is false
    idx: dict[str, list] = {}
    for bbl, address_id in rows:
        leg = detail.get(address_id)
        if leg is None:
            idx[bbl] = [address_id, None, None, None]
        else:
            legality_i, histdist, landmark = leg
            idx[bbl] = [address_id, legality_i, int(histdist), int(landmark)]
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"values": list(LEGALITY_VALUES), "idx": idx}
    text = json.dumps(payload, separators=(",", ":"))
    (out_dir / "address_index.json").write_text(text)
    return len(text.encode())
