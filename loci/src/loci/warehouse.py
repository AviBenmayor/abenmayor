"""Render docs/WAREHOUSE.md -- the human-readable mirror of the LIVE catalog.

WHY THIS EXISTS
---------------
The 2026-09-16 audit counted 81 objects where D61 had consolidated to 26, and
found that for five of them -- `storefront`, `staging.poi_closure`,
`bike_od_leakage`, `poi_key_map`, `zip_establishments` -- the GRAIN WAS STATED
NOWHERE. Not in the DDL, not in a docstring, not in a ticket. A table whose
grain is unwritten is a table whose next reader invents one, and two of this
project's worst bugs (the pooled storefront filings, the 3.7x poi_closure
fan-out) are exactly that mistake made twice.

So the grain moves INTO THE CATALOG. Every object carries a
`COMMENT ON TABLE`/`COMMENT ON VIEW` of the form

    layer=<layer>; grain=<one line>; key=<columns or ->[; note=<one line>]

written to the catalog from `CLASSIFICATION` below by `apply_classification`,
read back by `catalog()`, and rendered to docs/WAREHOUSE.md by `render()`.
`CLASSIFICATION` is the single declaration; an object present in the database
but absent from it is a FAILURE, not a blank row. That is the "inventory before
adding a table" rule (owner, 2026-09-09) made mechanical.

Same contract as SOURCES.md / PAID-SOURCES.md / PORTABILITY.md: one definition
emits the document, the document is never hand-edited, and `loci
check-warehouse` fails if it is not a byte-identical render.

TWO CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------
1. `CREATE OR REPLACE VIEW` DROPS a view's comment (verified, DuckDB 1.5.5).
   `db.init_schema` re-renders many views on EVERY session, so a comment
   written once does not stay written: `apply_classification` has to run AFTER
   the migration sweep, which is why it is a step and not a .sql file.
2. Three `staging.poi_*_pending` tables are created by INGEST CODE
   (sources/cities/nyc/dcwp.py and siblings), not by any migration. A
   `COMMENT ON` for them inside a .sql file fails outright on a from-scratch
   build -- measured, not guessed. `apply_classification` skips objects that do
   not exist yet and still reports a declared-but-absent object, which a SQL
   file cannot do.

Exposed as `loci gen-warehouse`, `loci check-warehouse` and
`loci migrate-warehouse --step classify`.
"""
from __future__ import annotations

import ast
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parent
ROOT = PKG.parents[1]
DOC_PATH = ROOT / "docs" / "WAREHOUSE.md"

#: The four layers, plus `calib`. Rendering order is this order.
#:
#: `calib` is the honest name for the retired hex grid. "No more hexes" (owner,
#: 2026-09-05) was a ruling about OUTPUTS, and the audit confirmed the layer is
#: not dead: `reach.py:135,138` and `model/gaps.py:105,399` read
#: `analysis.hex_poi_distance` for reach-tier calibration. Calling it retired
#: while shipping code reads it is how a 241 MiB layer survives three
#: consolidations. It is an INPUT to calibration and never a deliverable, and
#: the layer label is where that is said out loud.
LAYERS = {
    "staging": "Staging — source records as ingested, one row per source record",
    "measure": "Measure — derived facts at a stated grain",
    "score":   "Score — the screen's outputs",
    "ledger":  "Ledger — append-only events and provenance",
    "calib":   "Calibration inputs — NOT deliverables (see 'no more hexes', D-2026-09-05)",
}

#: Every warehouse object's layer, grain and key. THE declaration.
#:
#: Applied to the catalog as COMMENT ON by `apply_classification`, read back
#: by `catalog()`, rendered by `render()`. It lives in Python and not in a
#: .sql migration for one concrete reason: three staging.poi_*_pending tables
#: are created by INGEST CODE (sources/.../dcwp.py and siblings), not by any
#: migration, so a COMMENT ON in a .sql file fails outright on a from-scratch
#: build -- verified 2026-09-16. A dict can skip what does not exist yet and
#: still report it as undeclared; a SQL file cannot.
CLASSIFICATION: dict[str, str] = {
    'staging.poi':
        'layer=staging; grain=one source record for one POI, pre-dedup; key=poi_id; note=308,366 rows over all sources; analysis.poi_dedup resolves it to locations',
    'staging.poi_closure':
        'layer=staging; grain=one Foursquare venue with a closure date; key=fsq_place_id; note=location_key is NOT unique (61,837 values over 61,518 distinct) and joining on it fans out 3.7x -- aggregate first',
    'staging.poi_stale':
        'layer=staging; grain=one POI absent from the current release; key=poi_id',
    'staging.poi_dcwp_pending':
        'layer=staging; grain=one DCWP licence row awaiting promotion to staging.poi; key=-',
    'staging.poi_dohmh_childcare_pending':
        'layer=staging; grain=one DOHMH childcare record awaiting promotion; key=-',
    'staging.poi_nys_medicaid_pharmacy_pending':
        'layer=staging; grain=one NYS Medicaid pharmacy record awaiting promotion; key=-',
    'staging.storefront_filing':
        'layer=staging; grain=one filing-feed record; key=filing_id; note=989,174 rows over eight feeds, all five boroughs, no date clip (D119)',
    'staging.alcohol_licences':
        'layer=staging; grain=one NYS SLA licence; key=licence_id; note=STATEWIDE as ingested -- reaches lon -78.87/lat 43.21, Buffalo. Not clipped to NYC. Audit finding 6',
    'staging.listings':
        'layer=staging; grain=one scraped listing URL; key=listing_url',
    'staging.listings_fetch_log':
        'layer=staging; grain=one fetch attempt within a run; key=run_id,seq; note=the resume number lives here (listings.py:139); audit finding 6 wired the read back up',
    'staging.ll84_laundry':
        'layer=staging; grain=one LL84 benchmarking filing for one BBL and year; key=bbl,filed_year',
    'staging.citibike_station':
        'layer=staging; grain=one Citi Bike station, current GBFS; key=-',
    'staging.citibike_station_legacy':
        'layer=staging; grain=one retired Citi Bike station; key=-',
    'staging.citibike_station_crosswalk':
        'layer=staging; grain=one legacy-to-current station id mapping; key=-',
    'staging.citibike_station_month':
        'layer=staging; grain=station x month x day-type x daypart; key=-; note=1,911,066 rows and NO declared key -- a re-ingest can double it',
    'staging.dot_camera':
        'layer=staging; grain=one DOT traffic camera; key=camera_id',
    'staging.dot_pedestrian_count':
        'layer=staging; grain=count point x round x period; key=point_id,round,period; note=borough is spelled long-form here, matching the source. Staging keeps the source vocabulary',
    'staging.poi_stale_census':
        'layer=staging; grain=one source x staleness bucket; key=-; note=a census OVER staging.poi_stale, not a second copy of it',
    'analysis.address':
        'layer=measure; grain=one address, 142 columns; key=borough,address_id; note=332,041 rows = 281,842 frame=lot + 50,199 frame=street. THE most-read object in the warehouse (90 references)',
    'analysis.address_demographics':
        'layer=measure; grain=one address x ACS vintage, 20 measures + 20 MOEs; key=address_id,acs_year; note=ACS 2023 sits on 2020 TRACT GEOGRAPHY -- aggregating a different vintage through these tract ids is a silent error the database cannot catch',
    'analysis.address_transit_profile':
        'layer=measure; grain=address x day-type x daypart; key=-; note=1,980,525 rows, no declared key',
    'analysis.address_entrance':
        'layer=measure; grain=address x subway entrance within reach; key=-',
    'analysis.address_bike_station':
        'layer=measure; grain=address x Citi Bike station within reach; key=-',
    'analysis.address_bike_growth':
        'layer=measure; grain=address x growth window; key=-',
    'analysis.address_laundry_evidence':
        'layer=measure; grain=one BBL x evidence source; key=bbl,source',
    'analysis.address_observation':
        'layer=ledger; grain=one field observation of one address; key=observation_id',
    'analysis.poi_dedup':
        'layer=measure; grain=one staging.poi row with its resolved cluster; key=poi_id; note=1:1 with staging.poi. Its `category` disagrees with staging.poi on 10,551 rows -- audit finding 3 drops that column',
    'analysis.poi_presence':
        'layer=measure; grain=one deduplicated business LOCATION, month-tracked; key=location_key; note=the first-seen/last-seen ledger. Carries all five boroughs ON PURPOSE -- reach is spatial and crosses borough lines; filtering it would manufacture gaps',
    'analysis.licence_interval':
        'layer=measure; grain=one DCWP licence with its status interval; key=licence_number; note=NO status-change date is published: surrender and revocation are bounds, only expiry is observed',
    'analysis.storefront':
        'layer=measure; grain=ONE FILING for one storefront -- NOT one storefront; key=storefront_id,filing_due_date; note=storefront_id RENUMBERS between filings. Group by reporting_year and you pool a full filing with a vacant_only supplement: use analysis.storefront_year',
    'analysis.storefront_pipeline':
        'layer=measure; grain=one pipeline record for one premises; key=pipeline_id',
    'analysis.dev_pipeline':
        'layer=measure; grain=one DOB job; key=job_number',
    'analysis.sidewalk_count':
        'layer=measure; grain=camera x frame x model x model version; key=camera_id,frame_hash,model,model_version',
    'analysis.bike_od_leakage':
        'layer=measure; grain=month x daypart x origin station x destination station; key=-; note=5,237,804 rows and no declared key; O and D are station ids, not addresses',
    'analysis.category_anchor':
        'layer=measure; grain=one category with its anchored floor; key=category; note=`boroughs` is a PARAMETER RECORD of the run scope, not a borough dimension, and it spells the long form because it filtered analysis.hex (calib), which does too',
    'analysis.zip_establishments':
        'layer=measure; grain=year x zipcode x NAICS x employment-size band -- the name understates it; key=year,zipcode,naics,emp_size_band',
    'analysis.zip_category_establishments':
        'layer=measure; grain=year x zipcode x Loci category; key=year,zipcode,category',
    'analysis.zip_coverage_check':
        'layer=measure; grain=year x zipcode x category, POI count vs ZBP establishments; key=year,zipcode,category; note=built FIRST and deliberately a base table, not a view over zip_coverage_by_source -- see model/zbp_compare.py:228-232',
    'analysis.zip_coverage_by_source':
        'layer=measure; grain=year x zipcode x category x source; key=year,zipcode,category,source',
    'analysis.coverage_validation':
        'layer=measure; grain=h3 cell x category -- a STALE HEX grain in an address-era table; key=-; note=8,603 rows over 2,984 distinct (h3_index,category)',
    'analysis.supply_asof':
        'layer=measure; grain=exactly one row, the pinned supply as-of date; key=pin; note=read this, never current_date, for any row-status decision',
    'analysis.borough':
        'layer=measure; grain=one NYC borough; key=borough_code; note=the ONE borough vocabulary. in_screen mirrors sources/cities/nyc/addresses.SCREEN_BOROUGHS for SQL consumers',
    'analysis.address_character':
        'layer=measure; grain=one address with its character labels; key=-; note=a VIEW so the label thresholds have one definition (model/address_character.py), never a CASE copied into DDL',
    'analysis.nta_character':
        'layer=measure; grain=one NTA with its character labels; key=-',
    'analysis.address_legality':
        'layer=measure; grain=one address with its zoning verdict; key=-',
    'analysis.address_transit_profile_wide':
        'layer=measure; grain=one address, transit profile pivoted wide; key=-; note=the PIVOT of analysis.address_transit_profile. A view, never a table',
    'analysis.address_observation_miss':
        'layer=measure; grain=one address the screen named that field work did not confirm; key=-; note=a CANDIDATE LIST, not a miss count',
    'analysis.bike_od_leakage_evening':
        'layer=measure; grain=the evening daypart slice of bike_od_leakage; key=-',
    'analysis.poi_supply':
        'layer=measure; grain=one open business location counted as supply; key=-',
    'analysis.poi_supply_status':
        'layer=measure; grain=one location with its open/closed/unknown verdict; key=-; note=reads analysis.supply_asof, not current_date',
    'analysis.poi_colocation':
        'layer=measure; grain=one address hosting 2+ POIs; key=-; note=two POIs at one address means resolve which is still open before counting -- never count both (D94)',
    'analysis.poi_first_seen':
        'layer=measure; grain=one location with its first-seen month and provenance; key=-',
    'analysis.licence_interval_poi':
        'layer=measure; grain=one licence joined to its POI; key=-; note=the identity join matches 0.9% -- licences carry the legal entity, the ledger the awning name',
    'analysis.storefront_latest':
        'layer=measure; grain=one PREMISES with its latest observation; key=premises_id; note=keyed on premises_id because storefront_id renumbers between filings',
    'analysis.storefront_year':
        'layer=measure; grain=one premises x reporting year, ONE filing per cell (full wins); key=premises_id,reporting_year; note=the fix for the pooled full/vacant_only double count. A vacant_only-only year has no denominator: read `universe` before computing a rate',
    'analysis.storefront_pipeline_lead':
        'layer=measure; grain=one premises with its leading pipeline stage; key=-',
    'analysis.storefront_screen':
        'layer=measure; grain=analysis.storefront restricted to MN+BK, NULL borough kept and labelled; key=storefront_id,filing_due_date',
    'analysis.storefront_pipeline_screen':
        'layer=measure; grain=analysis.storefront_pipeline restricted to MN+BK, NULL borough kept and labelled; key=pipeline_id',
    'staging.storefront_filing_screen':
        'layer=staging; grain=staging.storefront_filing restricted to MN+BK, NULL borough kept and labelled; key=filing_id',
    'analysis.address_category':
        'layer=score; grain=address x category; key=borough,address_id,category; note=4,980,615 rows = 332,041 addresses x 15 categories',
    'analysis.forecast':
        'layer=score; grain=address x category x issued_month x model_version -- one frozen prediction; key=issued_month,model_version,address_id,category; note=EVERY vintage is kept (owner 2026-09-16). The frozen vintage is the point: a query-time view cannot replace it',
    'analysis.forecast_run':
        'layer=score; grain=one fit -- issued_month x model_version; key=issued_month,model_version; note=the FIT, not the predictions',
    'analysis.recommendation':
        'layer=score; grain=one issued recommendation card; key=rec_id',
    'analysis.address_gaps':
        'layer=score; grain=one address with its per-category gap measures; key=-; note=GENERATED from loci.categories.CATEGORIES by model/address_gaps.address_gaps_view_sql, not static DDL. A new analysis.address column will never reach it silently',
    'analysis.forecast_latest':
        'layer=score; grain=address x category, newest shipped vintage; key=-; note=orders by frozen_at DESC then model_version DESC. Ordering by the git hash alone picks the wrong vintage -- five same-month vintages are live and they genuinely disagree',
    'analysis.forecast_surprise_nta':
        'layer=score; grain=NTA x category for one scored vintage; key=-; note=an NTA with no expected value is NOT emitted, and a NULL z_clustered is never backfilled from z_naive',
    'analysis.recommendation_latest':
        'layer=score; grain=one recommendation, latest status; key=rec_id',
    'analysis.recommendation_category_summary':
        'layer=score; grain=one category with its recommendation counts; key=-',
    'analysis.forecast_outcome':
        'layer=ledger; grain=one forecast x scored_month; key=issued_month,model_version,address_id,category,scored_month; note=append-only realized join. Never prune it to match a forecast retention rule',
    'analysis.recommendation_outcome':
        'layer=ledger; grain=one recommendation x snapshot month; key=rec_id,snapshot_month',
    'analysis.poi_key_map':
        'layer=ledger; grain=one planned key rewrite; key=old_key,planned_at; note=append-only log: 12,011 rows over 8,134 distinct poi_id, which is correct for a log and wrong for a lookup',
    'analysis.poi_closure_evidence':
        'layer=ledger; grain=one piece of evidence for one closure; key=evidence_id',
    'analysis.spend_ledger':
        'layer=ledger; grain=one paid-source spend event; key=-',
    # ---- 2026-09-17: the four calculations (licence label, triangulation,
    # ---- frozen snapshots, tenure). Declared in the same edit that created
    # ---- them, per the rule this dict exists to enforce.
    'analysis.licence_event':
        'layer=measure; grain=one NYS SLA licence with the pre-registered non-renewal label under BOTH arms; key=licence_number; note=restaurant/bar/grocery/pharmacy only; DCWP rows stay in licence_interval. A licence end is an UPPER BOUND on a business end -- P5 decides whether it may be called survival; until then it is "licence non-renewal", context not grade. event_* is NULL (not FALSE) when bbl is NULL',
    'analysis.licence_event_baseline':
        'layer=measure; grain=category x borough x licence-class rollup of licence_event; key=-; note=a VIEW; the class = NULL row is the borough rate the card quotes; rates exclude unchecked (bbl NULL) rows from BOTH numerator and denominator',
    'analysis.closure_triangulation':
        'layer=measure; grain=one stale Foursquare venue CORROBORATED by >= 1 independent premises signal; key=stale_poi_id; note=STAGED, never promoted here: not evidence, not poi_status. n_kinds >= 2 is a CHECK (D79). Read flip_shared_by before counting closures -- one LL157 flip can corroborate several stale venues within 30 m',
    'analysis.supply_snapshot':
        'layer=measure; grain=one principled supply location present at t0, per t0; key=t0,location_key; note=retrodiction.supply_as_of_sql materialised, hash-stamped. NO closure filter (status_at_t0 flags it). Pre-2023 t0 sets are 40-49% backfill-censored: read supply_snapshot_census before quoting a count',
    'analysis.supply_snapshot_census':
        'layer=measure; grain=t0 x category census of supply_snapshot, with the censored share; key=-; note=a VIEW; the category = NULL row is the whole t0 set',
    'analysis.storefront_tenure':
        'layer=measure; grain=one LL157 premises with its occupancy runs and turnovers 2019-2024; key=premises_id; note=runs are interval-censored at 12 months (observations one 12/31 apart) and a same-class tenant swap is invisible: turnover undercounts, tenure overcounts. All five boroughs on disk',
    'analysis.nta_tenure':
        'layer=measure; grain=borough x NTA rollup of storefront_tenure; key=-; note=a VIEW; the NTA descriptive table',
    # ---- 2026-09-17: the aerial items (scope memo §5 items 3-5, owner's pick)
    # ---- and the citywide footprints they hang on. Each measure is CARD
    # ---- CONTEXT ONLY and UNGATED until the owner has checked its review
    # ---- page under data/aerial/ (memo §5 "gate before a grade" column).
    'staging.building_footprint':
        'layer=staging; grain=one building footprint (BIN), citywide; key=bin; note=1,083,030 rows over 818,190 base_bbl -- a lot carries MANY BINs, union by bbl before joining. height_roof_ft is FEET (2017 LiDAR, maintained from imagery); construction_year before 2017 is RPAD not imagery. Demolition rows are KEPT',
    'analysis.lot_aerial_change':
        'layer=measure; grain=one permitted lot x (ortho_from, ortho_to); key=bbl,ortho_from,ortho_to; note=UNGATED: OWNER REVIEW PENDING (memo §5 row 3: agreement >= 0.8 vs DOB status on 100 hand-checked lots; data/aerial/gowanus_change_review.html). change_class is a heuristic on brightness change + 2024 edge density; sheds, tarps, trucks and shadows read as change. A two-year bin dates nothing. Card context only',
    'analysis.building_awning':
        'layer=measure; grain=one building (BIN) x ortho year, its street faces; key=bin,ortho_year; note=UNGATED: OWNER REVIEW PENDING (memo §5 row 4: precision >= 0.8 vs LL157 occupied premises on 100 hand-checked faces; data/aerial/awning_review.html). First run restricted to the twelve D82 corridors; a colour/texture heuristic on the 3 m sidewalk band -- sheds and box trucks are the known false positives. Card context only',
    'analysis.lot_convertible':
        'layer=measure; grain=one lot that is one-storey / garage / parking / vacant with a >= 500 m2 floorplate; key=bbl; note=UNGATED: OWNER REVIEW PENDING (memo §5 row 5: hand-check the top 30; data/aerial/convertible_review.html). height_m is footprint height_roof (2017 LiDAR) -- no 2021 NYC LiDAR is published (verified 2026-09-17). score is a SORT KEY, not a measure. Card context only',
    'chains.brand_snapshot':
        'layer=ledger; grain=brand x snapshot month; key=snapshot_month,brand_key',
    'chains.brand_location':
        'layer=ledger; grain=brand x location x snapshot month; key=snapshot_month,brand_key,location_key; note=borough is spelled long-form; resolve through analysis.borough. Carries all five boroughs on purpose -- a chain crossing into Queens is still a competitor',
    'chains.press_hits':
        'layer=ledger; grain=one press mention of one brand; key=brand_key,url',
    'chains.brand_latest':
        'layer=ledger; grain=one brand, latest snapshot; key=brand_key',
    'analysis.hex':
        'layer=calib; grain=one h3 res-9 cell; key=h3_index; note=borough is spelled long-form here. THE ONE remaining long-form carrier in analysis.*; a follow-up moves this layer to a calib schema',
    'analysis.hex_access':
        'layer=calib; grain=h3 cell x category x threshold; key=h3_index,category,threshold_min',
    'analysis.hex_controls':
        'layer=calib; grain=one h3 cell with its controls; key=h3_index',
    'analysis.hex_demographics':
        'layer=calib; grain=h3 cell x ACS vintage; key=h3_index,acs_year; note=the same 20 ACS measures as address_demographics, at a second grain',
    'analysis.hex_panel':
        'layer=calib; grain=h3 cell x year x NAICS; key=h3_index,year,naics',
    'analysis.hex_poi_distance':
        'layer=calib; grain=h3 cell x POI -- NOT cell x category; key=-; note=10,645,460 rows, 225 MiB, no declared key. Read by reach.py and model/gaps.py for reach-tier calibration',
}


#: Parsed out of the catalog comment.
_FIELD_RE = re.compile(r"(?P<k>layer|grain|key|note)\s*=\s*(?P<v>[^;]*)")

#: A module-level constant that names a warehouse object, e.g.
#:     TABLE = "analysis.poi_closure"
#:     FORECAST_SURPRISE_VIEW = ("analysis", "forecast_surprise_nta")
#: The audit's note on why this matters: "many objects are read only through
#: module-level `TABLE = 'schema.obj'` constants interpolated into f-strings, so
#: literal grep badly undercounts". A reader count that undercounts is worse
#: than none -- it is what makes a live object look droppable.
_QUALIFIED = re.compile(r"^(analysis|staging|chains|calib)\.[a-z_][a-z0-9_]*$")


class Object:
    """One warehouse object, as the catalog describes it."""

    __slots__ = ("schema", "name", "kind", "layer", "grain", "key", "note", "rows")

    def __init__(self, schema, name, kind, layer, grain, key, note, rows):
        self.schema, self.name, self.kind = schema, name, kind
        self.layer, self.grain, self.key, self.note = layer, grain, key, note
        self.rows = rows

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"


def _parse_comment(comment: str | None) -> dict[str, str]:
    """`layer=..; grain=..; key=..[; note=..]` -> dict. {} when unclassified."""
    if not comment:
        return {}
    found = {m.group("k"): " ".join(m.group("v").split())
             for m in _FIELD_RE.finditer(comment)}
    return found if {"layer", "grain", "key"} <= set(found) else {}


def catalog(con) -> list[Object]:
    """Every non-internal table and view, with its classification comment.

    `estimated_size` is DuckDB's own row estimate and is NOT rendered into the
    document: it moves on every ingest, and a document that changes whenever a
    row lands is a document whose drift check gets switched off. Row counts
    belong in the audit, not in the inventory.
    """
    # `NOT temporary`: a session's own TEMP tables (a builder's scratch
    # `_tri_stale`, retrodiction's `_rd_sup`) are visible in duckdb_tables()
    # on the connection that made them and are NOT warehouse objects. Without
    # the filter a `gen-warehouse` run from a build session renders them as
    # UNCLASSIFIED (happened 2026-09-17).
    rows = con.execute("""
        SELECT schema_name, table_name, 'table' AS kind, comment, estimated_size
        FROM duckdb_tables() WHERE NOT internal AND NOT temporary
        UNION ALL
        SELECT schema_name, view_name, 'view', comment, NULL
        FROM duckdb_views() WHERE NOT internal AND NOT temporary
        ORDER BY 1, 2
    """).fetchall()
    out = []
    for schema, name, kind, comment, size in rows:
        f = _parse_comment(comment)
        out.append(Object(schema, name, kind,
                          f.get("layer"), f.get("grain"), f.get("key"),
                          f.get("note"), size))
    return out


# ------------------------------------------------------------------ readers

def _aliases(tree: ast.AST) -> dict[str, str]:
    """Module-level NAME -> 'schema.object' bindings.

    Handles the two shapes the codebase actually uses: a qualified string, and
    a (schema, name) tuple. Anything else is ignored rather than guessed at --
    a wrong alias inflates a reader count, and an inflated count is what keeps
    a dead object alive.
    """
    found: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            if _QUALIFIED.match(value.value):
                found[target.id] = value.value
        elif isinstance(value, ast.Tuple) and len(value.elts) == 2:
            parts = [e.value for e in value.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(parts) == 2 and _QUALIFIED.match(f"{parts[0]}.{parts[1]}"):
                found[target.id] = f"{parts[0]}.{parts[1]}"
    return found


def readers(objects: list[Object], src: pathlib.Path | None = None) -> dict[str, int]:
    """How many times each object is referenced in src/loci, DDL excluded.

    Counts BOTH the literal `schema.object` and every use of a module-level
    constant bound to it (minus the binding itself). `src/loci/sql/` is not
    scanned: a migration that creates an object is not a reader of it, and
    counting DDL would make every object look alive.
    """
    src = src or PKG
    names = {o.qualified for o in objects}
    counts = {q: 0 for q in names}
    for path in sorted(src.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for q in names:
            # A bare substring count is WRONG here: `staging.citibike_station`
            # is a prefix of `_crosswalk`, `_legacy` and `_month`, and counting
            # it that way reported 86 readers for an object with 12. The
            # trailing boundary is what separates a name from a longer name
            # that starts with it.
            counts[q] += len(re.findall(rf"{re.escape(q)}(?![\w])", text))
        try:
            alias = _aliases(ast.parse(text))
        except SyntaxError:
            continue
        for alias_name, q in alias.items():
            if q not in counts:
                continue
            # every mention of the constant, less its own assignment line
            uses = len(re.findall(rf"\b{re.escape(alias_name)}\b", text)) - 1
            counts[q] += max(uses, 0)
    return counts


# ------------------------------------------------------------------- render

def _cell(text: str | None) -> str:
    """One table cell: single-line, pipes escaped, never empty."""
    if text is None or not str(text).strip():
        return "—"
    return " ".join(str(text).split()).replace("|", r"\|")


def render(objects: list[Object], reader_counts: dict[str, int]) -> str:
    """docs/WAREHOUSE.md, deterministically, from the catalog."""
    classified = [o for o in objects if o.layer]
    lines: list[str] = []
    w = lines.append
    w("# Loci warehouse inventory")
    w("")
    w("**GENERATED — do not hand-edit.** `loci gen-warehouse` renders this file")
    w("from the live DuckDB catalog; `loci check-warehouse` fails if it is not a")
    w("byte-identical render. Every object's layer, grain and key come from its")
    w("`COMMENT ON` in the catalog, written there from")
    w("`warehouse.CLASSIFICATION` by `loci migrate-warehouse --step classify`.")
    w("")
    w("An object with no classification comment is a FAILURE, not a blank row:")
    w("that is the \"inventory before adding a table\" rule (owner, 2026-09-09)")
    w("made mechanical. If you added a table, declare it in the same edit.")
    w("")
    w("Re-run `--step classify` after any session that re-renders a view:")
    w("`CREATE OR REPLACE VIEW` drops a view's comment, and `init_schema`")
    w("re-renders views every session.")
    w("")
    w("`Rd` counts references to the name in `src/loci`, DDL excluded, resolving")
    w("module-level `TABLE = \"schema.object\"` constants (a literal grep misses")
    w("those, and an undercount is what makes a live object look droppable).")
    w("It counts prose in docstrings too, so treat it as an UPPER BOUND — the")
    w("only load-bearing value in this column is **0**, which is what the")
    w("2026-09-16 audit's six zero-reader objects looked like. Confirm a zero by")
    w("hand before dropping anything: three of that audit's six turned out to")
    w("have readers in `tests/`, which this scan does not see.")
    w("")
    w(f"**{len(objects)} objects** — "
      + ", ".join(f"{sum(1 for o in classified if o.layer == k)} {k}" for k in LAYERS)
      + ".")
    w("")
    for layer, heading in LAYERS.items():
        rows = [o for o in classified if o.layer == layer]
        if not rows:
            continue
        w(f"## {heading}")
        w("")
        w("| Object | Kind | Grain | Key | Rd |")
        w("|---|---|---|---|---|")
        for o in sorted(rows, key=lambda x: x.qualified):
            note = f" _{_cell(o.note)}_" if o.note else ""
            w(f"| `{o.qualified}` | {o.kind} | {_cell(o.grain)}{note} "
              f"| {_cell(o.key)} | {reader_counts.get(o.qualified, 0)} |")
        w("")
    unclassified = [o for o in objects if not o.layer]
    if unclassified:
        w("## UNCLASSIFIED — these fail `loci check-warehouse`")
        w("")
        for o in sorted(unclassified, key=lambda x: x.qualified):
            w(f"- `{o.qualified}` ({o.kind}) — no `layer=…; grain=…; key=…` comment")
        w("")
    return "\n".join(lines).rstrip("\n") + "\n"


def generate(con) -> int:
    """Write docs/WAREHOUSE.md from the live catalog. Returns object count."""
    objects = catalog(con)
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(render(objects, readers(objects)), encoding="utf-8")
    return len(objects)


def apply_classification(con) -> tuple[int, list[str], list[str]]:
    """Write CLASSIFICATION into the catalog as COMMENT ON.

    THIS WRITES TO THE DATABASE. It is the one part of the inventory machinery
    that does, which is why it is a `migrate-warehouse` step rather than
    something `init_schema` does behind your back during Phase A.

    Returns (n_applied, declared_but_absent, present_but_undeclared). A
    declared object that does not exist is NOT an error on its own -- the three
    `staging.poi_*_pending` tables genuinely do not exist until their ingest has
    run once -- but it is reported, because a typo in a key and an ingest that
    has never run look identical from here and only one of them is fine.
    """
    kinds = {f"{s}.{n}": k for s, n, k in con.execute("""
        SELECT schema_name, table_name, 'TABLE' FROM duckdb_tables()
        WHERE NOT internal AND NOT temporary
        UNION ALL
        SELECT schema_name, view_name, 'VIEW' FROM duckdb_views()
        WHERE NOT internal AND NOT temporary
    """).fetchall()}
    applied = 0
    for qualified, text in CLASSIFICATION.items():
        kind = kinds.get(qualified)
        if kind is None:
            continue
        # COMMENT ON takes no bind parameter (DuckDB 1.5.5 parser), so the
        # literal is inlined with its quotes doubled. CLASSIFICATION is a
        # module constant, never user input, but the escape is here anyway --
        # a string-built statement without one is a habit, not an exception.
        literal = text.replace("'", "''")
        con.execute(f"COMMENT ON {kind} {qualified} IS '{literal}'")
        applied += 1
    absent = sorted(set(CLASSIFICATION) - set(kinds))
    undeclared = sorted(set(kinds) - set(CLASSIFICATION))
    return applied, absent, undeclared


def drift(con) -> list[str]:
    """Every reason `loci check-warehouse` should fail. Empty list = clean."""
    errors: list[str] = []
    objects = catalog(con)

    for o in sorted(objects, key=lambda x: x.qualified):
        if not o.layer:
            declared = o.qualified in CLASSIFICATION
            errors.append(
                f"{o.qualified} ({o.kind}) carries no "
                f"'layer=…; grain=…; key=…' comment — "
                + ("it IS declared in warehouse.CLASSIFICATION, so the catalog "
                   "is stale: run `loci migrate-warehouse --step classify` "
                   "(a CREATE OR REPLACE VIEW drops comments)"
                   if declared else
                   "add it to warehouse.CLASSIFICATION in the same edit that "
                   "created the object (inventory-before-adding, owner "
                   "2026-09-09)"))
        elif o.layer not in LAYERS:
            errors.append(f"{o.qualified} has layer={o.layer!r}; "
                          f"expected one of {sorted(LAYERS)}")

    expected = render(objects, readers(objects))
    if not DOC_PATH.exists():
        errors.append(f"{DOC_PATH} is missing — run `loci gen-warehouse`")
    else:
        actual = DOC_PATH.read_text(encoding="utf-8")
        if actual != expected:
            errors.append(
                f"{DOC_PATH} is not a byte-identical render of the catalog "
                f"({len(actual)} bytes on disk, {len(expected)} expected) — "
                f"run `loci gen-warehouse`")
    return errors
