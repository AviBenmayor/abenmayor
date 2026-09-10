"""Export the MapLibre webmap's two point layers from the database.

Replaces the ad-hoc scratchpad script that produced `webmap/gap_buildings.json`
(commit e1784b6) -- per the repo standard, loose scripts become CLI
subcommands: `loci export-webmap`.

TWO LAYERS, ONE CATEGORY FILTER. The map answers one question -- "where is
business X missing, and where does X actually exist?" -- so both layers are
sliced the same way:

  gaps/<category>.json   addresses from `analysis.address_gaps` whose
                         `<category>_ratio > 1` (the model's own definition of
                         a missing category: see model/address_gaps.py, D41),
                         restricted to eligible addresses.
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
One file per NTA holds every eligible address in it that is beyond reach of at
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
from loci.score.supply import DEFAULT_SUPPLY_SET, SUPPLY_SETS, supply_predicate

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
          "bank": "#4a7a8c", "tailor_repair": "#996a3a", "restaurant": "#a8443c"}

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

    Rows come from `analysis.poi_supply` (which already filters
    `is_canonical`), and the named supply set rides along as `in_set` rather
    than being applied as a WHERE clause: the excluded points are drawn as
    their own class, so the export needs them. `supply_predicate` is the same
    function model/address_gaps.py uses, so the map and the model cannot drift
    apart over what "a business exists here" means.

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
               v.{pred} AS in_set
        FROM analysis.poi_supply v
        JOIN src s ON s.cluster_id = v.cluster_id
        LEFT JOIN dohmh dh ON dh.cluster_id = v.cluster_id
        LEFT JOIN fb f ON f.cluster_id = v.cluster_id
        JOIN analysis.hex h
          ON h.h3_index = h3_latlng_to_cell_string(ST_Y(v.geom), ST_X(v.geom), {H3_RES})
        WHERE h.borough IN ({placeholders})
          AND v.category IN ({", ".join("?" for _ in ALLCATS)})
        ORDER BY v.category, v.poi_id
    """
    return sql, list(dcats) + list(dcats) + names + ALLCATS


def _gap_sql(cat: str, boroughs: list[str], pipeline: bool = True,
             storefront: bool = True) -> tuple[str, list]:
    """Eligible addresses whose `cat` is beyond its reach tier (ratio > 1) --
    model/address_gaps.py's own `n_missing` definition, one category at a
    time.

    `pipeline` selects the seven PIPELINE_GAP_COLUMNS and `storefront` the five
    STOREFRONT_GAP_COLUMNS. Both are NULL-safe here on purpose: a database
    whose `loci pipeline` or `loci storefronts` has not run still exports, it
    just exports zeros and no nearest project or vacancy, and the UI hides the
    reading rather than printing a confident "0 homes coming" / "no empty
    storefront anywhere"."""
    placeholders = ", ".join("?" for _ in boroughs)
    pipe = (", " + ", ".join(PIPELINE_GAP_COLUMNS)) if pipeline else \
           ", " + ", ".join("NULL" for _ in PIPELINE_GAP_COLUMNS)
    # APPENDED after the pipeline block, never inserted: both tails are read by
    # position from their own end.
    shop = (", " + ", ".join(STOREFRONT_GAP_COLUMNS)) if storefront else \
           ", " + ", ".join("NULL" for _ in STOREFRONT_GAP_COLUMNS)
    sql = f"""
        SELECT address_id,
               round(lon, {COORD_DP}) AS lon,
               round(lat, {COORD_DP}) AS lat,
               borough,
               units_capped,
               {cat}_ratio AS ratio,
               {cat}_nearest_m AS nearest_m,
               neighborhood
               {pipe}
               {shop}
        FROM analysis.address_gaps
        WHERE eligible
          AND borough IN ({placeholders})
          AND {cat}_ratio > 1
        ORDER BY address_id
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
         in_set) in rows:
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


def pack_gaps(rows, boroughs: list[str], cat: str,
              vacant_detail: dict[str, tuple] | None = None) -> dict:
    """rows -> one layer dict. `pts` stride 12: lon, lat, borough index,
    capped units, then the four pipeline slots (`pipe_slots`) and the four
    storefront slots (`sf_slots`). `ratio` is dropped from the payload
    deliberately -- the map shows presence/absence, and the continuous score is
    the model's output, not the map's.

    Both slot blocks are APPENDED, never inserted: every reader indexes 0..3 by
    position and a reordering here would silently relabel every dot.
    """
    bidx = {b: i for i, b in enumerate(boroughs)}
    projects = _Projects()
    vacants = _Vacants(vacant_detail)
    npipe, nshop = len(PIPELINE_GAP_COLUMNS), len(STOREFRONT_GAP_COLUMNS)
    pts, ids = [], []
    for row in rows:
        address_id, lon, lat, boro, units = row[:5]
        if lon is None or lat is None or boro not in bidx:
            continue
        pts.extend([lon, lat, bidx[boro], round(float(units or 0))])
        pts.extend(pipe_slots(projects, row[8:8 + npipe]))
        pts.extend(sf_slots(vacants, row[8 + npipe:8 + npipe + nshop]))
        ids.append(address_id)
    return {"category": cat, "label": CATEGORIES[cat].label, "stride": 12,
            "pts": pts, "ids": ids, "n": len(ids),
            "projects": projects.pack(),
            "pipelineColumns": list(PIPELINE_GAP_COLUMNS),
            "vacants": vacants.pack(),
            "storefrontColumns": list(STOREFRONT_GAP_COLUMNS)}


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
               ARG_MAX(primary_business_activity, filing_due_date) AS last_use
        FROM {schema}.{table}
        WHERE borough IN ({ph})
          AND primary_business_activity NOT IN ({no_act})
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


# --------------------------------------------------- all opportunities (NTA)
#
# THE OWNER'S QUESTION (2026-09-09): "when I zoom in on one neighborhood, can
# we show all the opportunities?" The fifteen per-category files answer "where
# is business X missing"; nobody can answer "what is missing HERE" by clicking
# through fifteen of them and holding the union in their head.
#
# So: one file per NTA carrying every eligible address in it that is missing at
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
                 storefront: bool = True) -> tuple[str, list]:
    """Every eligible address in `boroughs` with its fifteen ratios. The
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
    sql = f"""
        SELECT nta_code, neighborhood, borough, address_id,
               round(lon, {COORD_DP}) AS lon, round(lat, {COORD_DP}) AS lat,
               units_capped, gap_score, lead_category, {pipe}, {shop}, {ratios}
        FROM analysis.address_gaps
        WHERE eligible AND borough IN ({ph}) AND nta_code IS NOT NULL
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
               v.{pred} AS in_set
        FROM analysis.poi_supply v
        JOIN src s ON s.cluster_id = v.cluster_id
        JOIN analysis.hex h
          ON h.h3_index = h3_latlng_to_cell_string(ST_Y(v.geom), ST_X(v.geom), {H3_RES})
        WHERE h.borough IN ({ph})
          AND h.nta_code IS NOT NULL
          AND v.category IN ({", ".join("?" for _ in ALLCATS)})
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
             vacant_detail: dict[str, tuple] | None = None) -> dict[str, dict]:
    """rows -> {nta_code: layer}. Only NTAs with at least one gap address get a
    layer: an "all opportunities" file for a neighborhood with no opportunity
    is a file the picker must never offer. POI rows for such an NTA are
    dropped with it."""
    out: dict[str, dict] = {}
    projects: dict[str, _Projects] = {}
    vacants: dict[str, _Vacants] = {}
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
            layer = out[code] = {
                "nta": code, "name": name, "boro": boro,
                "supplySet": supply_set, "supplyHash": supply_hash,
                "stride": 14, "pts": [], "ids": [], "miss": [],
                "gapCounts": {c: 0 for c in ALLCATS},
                "bounds": [lon, lat, lon, lat], "units": 0,
                "pois": {"stride": 5, "pts": [], "names": [], "n": 0, "nSet": 0},
                "pipelineColumns": list(PIPELINE_GAP_COLUMNS),
                "storefrontColumns": list(STOREFRONT_GAP_COLUMNS),
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
        layer["ids"].append(address_id)
        layer["units"] += u
        for i, ratio in missing:
            layer["miss"].extend([i, round(ratio, RATIO_DP)])
            layer["gapCounts"][ALLCATS[i]] += 1
        b = layer["bounds"]
        layer["bounds"] = [min(b[0], lon), min(b[1], lat), max(b[2], lon), max(b[3], lat)]

    for code, cat, name, lon, lat, corroborated, in_set in poi_rows:
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
        p = layer["pois"]
        p["n"] = len(p["names"])
        p["nSet"] = sum(p["pts"][4::5])
        # A centre for the sidebar label; the bbox is what the map flies to.
        pts, st = layer["pts"], layer["stride"]
        layer["center"] = [round(sum(pts[0::st]) / layer["n"], COORD_DP),
                           round(sum(pts[1::st]) / layer["n"], COORD_DP)]
    return out


def nta_index(layers: dict[str, dict], boroughs: list[str],
              supply_set: str, supply_hash: str | None) -> dict:
    """The small file the sidebar reads: one row per neighborhood with its
    address count, its per-category gap counts and its bounds, sorted by size.
    It exists so the picker can show "Canarsie — 9,939 addresses" without
    fetching a 500 kB NTA file to count them."""
    rows = [{"nta": code, "name": L["name"], "boro": L["boro"], "n": L["n"],
             "units": L["units"], "pois": L["pois"]["n"], "nSet": L["pois"]["nSet"],
             "gapCounts": L["gapCounts"], "bounds": L["bounds"], "center": L["center"]}
            for code, L in layers.items()]
    rows.sort(key=lambda r: (-r["n"], r["nta"]))
    return {"boroughs": boroughs, "cats": ALLCATS,
            "catLabels": [CATEGORIES[c].label for c in ALLCATS],
            "supplySet": supply_set, "supplyHash": supply_hash,
            "n": sum(r["n"] for r in rows), "ntas": rows}


def collect_nta(con, boroughs: list[str], supply_set: str = DEFAULT_SUPPLY_SET,
                supply_hash: str | None = None,
                vacants: dict[str, tuple] | None = None) -> dict[str, dict]:
    """Read the all-opportunities layers. Pure read, same two tables the
    per-category layers come from."""
    gsql, gparams = _nta_gap_sql(boroughs, has_pipeline_columns(con),
                                 has_storefront_columns(con))
    psql, pparams = _nta_poi_sql(boroughs, supply_set)
    return pack_nta(con.execute(gsql, gparams).fetchall(),
                    con.execute(psql, pparams).fetchall(),
                    supply_set, supply_hash,
                    vacants if vacants is not None else collect_vacant_detail(con, boroughs))


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


def collect(con, boroughs: list[str], supply_set: str = DEFAULT_SUPPLY_SET) -> dict:
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
    # One read of the vacant-storefront lookup for all sixteen gap files: the
    # same ~3,800 rows stand behind every category.
    vacants = collect_vacant_detail(con, boroughs)
    gap_layers = {}
    for cat in ALLCATS:
        sql, params = _gap_sql(cat, boroughs, pipe_cols, shop_cols)
        gap_layers[cat] = pack_gaps(con.execute(sql, params).fetchall(), boroughs,
                                    cat, vacants)

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
    nta = collect_nta(con, boroughs, supply_set, prov.get("supply_hash"), vacants)
    return {"boroughs": boroughs, "sources": sources, "detailCats": dcats,
            "pois": poi_layers, "gaps": gap_layers, "neighborhoods": nbhd,
            "boroBounds": boro_bounds, "alcohol": collect_alcohol(con, boroughs),
            "pipeline": collect_pipeline(con, boroughs),
            "storefronts": collect_storefronts(con, boroughs),
            "nta": nta,
            "supplySet": supply_set, "supplyProvenance": prov,
            "supplyWarning": supply_warning(supply_set, prov)}


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
            "storefront": storefront_summary(bundle.get("storefronts"), boroughs)}


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
                        (bundle.get("supplyProvenance") or {}).get("supply_hash")))

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
        "neighborhoods": bundle["neighborhoods"],
        "boroBounds": bundle["boroBounds"],
        # The all-opportunities mode. `available` false means this export
        # wrote no per-NTA files, and the UI hides the mode rather than
        # offering a button that 404s.
        "nta": {"available": bool(nta_layers),
                "dir": NTA_DIR,
                "n": len(nta_layers),
                "addresses": sum(L["n"] for L in nta_layers.values())},
    }
    _dump("meta.json", meta)
    return written
