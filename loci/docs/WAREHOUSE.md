# Loci warehouse inventory

**GENERATED — do not hand-edit.** `loci gen-warehouse` renders this file
from the live DuckDB catalog; `loci check-warehouse` fails if it is not a
byte-identical render. Every object's layer, grain and key come from its
`COMMENT ON` in the catalog, written there from
`warehouse.CLASSIFICATION` by `loci migrate-warehouse --step classify`.

An object with no classification comment is a FAILURE, not a blank row:
that is the "inventory before adding a table" rule (owner, 2026-09-09)
made mechanical. If you added a table, declare it in the same edit.

Re-run `--step classify` after any session that re-renders a view:
`CREATE OR REPLACE VIEW` drops a view's comment, and `init_schema`
re-renders views every session.

`Rd` counts references to the name in `src/loci`, DDL excluded, resolving
module-level `TABLE = "schema.object"` constants (a literal grep misses
those, and an undercount is what makes a live object look droppable).
It counts prose in docstrings too, so treat it as an UPPER BOUND — the
only load-bearing value in this column is **0**, which is what the
2026-09-16 audit's six zero-reader objects looked like. Confirm a zero by
hand before dropping anything: three of that audit's six turned out to
have readers in `tests/`, which this scan does not see.

**83 objects** — 19 staging, 39 measure, 9 score, 10 ledger, 6 calib.

## Staging — source records as ingested, one row per source record

| Object | Kind | Grain | Key | Rd |
|---|---|---|---|---|
| `staging.alcohol_licences` | table | one NYS SLA licence _STATEWIDE as ingested -- reaches lon -78.87/lat 43.21, Buffalo. Not clipped to NYC. Audit finding 6_ | licence_id | 22 |
| `staging.citibike_station` | table | one Citi Bike station, current GBFS | - | 21 |
| `staging.citibike_station_crosswalk` | table | one legacy-to-current station id mapping | - | 10 |
| `staging.citibike_station_legacy` | table | one retired Citi Bike station | - | 10 |
| `staging.citibike_station_month` | table | station x month x day-type x daypart _1,911,066 rows and NO declared key -- a re-ingest can double it_ | - | 46 |
| `staging.dot_camera` | table | one DOT traffic camera | camera_id | 28 |
| `staging.dot_pedestrian_count` | table | count point x round x period _borough is spelled long-form here, matching the source. Staging keeps the source vocabulary_ | point_id,round,period | 29 |
| `staging.listings` | table | one scraped listing URL | listing_url | 16 |
| `staging.listings_fetch_log` | table | one fetch attempt within a run _the resume number lives here (listings.py:139)_ | run_id,seq | 5 |
| `staging.ll84_laundry` | table | one LL84 benchmarking filing for one BBL and year | bbl,filed_year | 14 |
| `staging.poi` | table | one source record for one POI, pre-dedup _308,366 rows over all sources_ | poi_id | 143 |
| `staging.poi_closure` | table | one Foursquare venue with a closure date _location_key is NOT unique (61,837 values over 61,518 distinct) and joining on it fans out 3.7x -- aggregate first_ | fsq_place_id | 23 |
| `staging.poi_dcwp_pending` | table | one DCWP licence row awaiting promotion to staging.poi | - | 9 |
| `staging.poi_dohmh_childcare_pending` | table | one DOHMH childcare record awaiting promotion | - | 8 |
| `staging.poi_nys_medicaid_pharmacy_pending` | table | one NYS Medicaid pharmacy record awaiting promotion | - | 8 |
| `staging.poi_stale` | table | one POI absent from the current release | poi_id | 5 |
| `staging.poi_stale_census` | view | one source x staleness bucket _a census OVER staging.poi_stale, not a second copy of it_ | - | 1 |
| `staging.storefront_filing` | table | one filing-feed record _989,174 rows over eight feeds, all five boroughs, no date clip (D119)_ | filing_id | 64 |
| `staging.storefront_filing_screen` | view | staging.storefront_filing restricted to MN+BK, NULL borough kept and labelled | filing_id | 1 |

## Measure — derived facts at a stated grain

| Object | Kind | Grain | Key | Rd |
|---|---|---|---|---|
| `analysis.address` | table | one address, 124 columns _332,041 rows = 281,842 frame=lot + 50,199 frame=street. THE most-read object in the warehouse (90 references)_ | borough,address_id | 378 |
| `analysis.address_bike_growth` | table | address x growth window | - | 22 |
| `analysis.address_bike_station` | table | address x Citi Bike station within reach | - | 28 |
| `analysis.address_character` | view | one address with its character labels _a VIEW so the label thresholds have one definition (model/address_character.py), never a CASE copied into DDL_ | - | 31 |
| `analysis.address_demographics` | table | one address x ACS vintage, 20 measures + 20 MOEs _ACS 2023 sits on 2020 TRACT GEOGRAPHY -- aggregating a different vintage through these tract ids is a silent error the database cannot catch_ | address_id,acs_year | 60 |
| `analysis.address_entrance` | table | address x subway entrance within reach | - | 21 |
| `analysis.address_laundry_evidence` | table | one BBL x evidence source | bbl,source | 21 |
| `analysis.address_legality` | view | one address with its zoning verdict | - | 19 |
| `analysis.address_observation_miss` | view | one address the screen named that field work did not confirm _a CANDIDATE LIST, not a miss count_ | - | 8 |
| `analysis.address_transit_profile` | table | address x day-type x daypart _1,980,525 rows, no declared key_ | - | 10 |
| `analysis.address_transit_profile_wide` | view | one address, transit profile pivoted wide _the PIVOT of analysis.address_transit_profile. A view, never a table_ | - | 3 |
| `analysis.bike_od_leakage` | table | month x daypart x origin station x destination station _5,237,804 rows and no declared key_ | - | 26 |
| `analysis.bike_od_leakage_evening` | view | the evening daypart slice of bike_od_leakage | - | 4 |
| `analysis.borough` | table | one NYC borough _the ONE borough vocabulary. in_screen mirrors sources/cities/nyc/addresses.SCREEN_BOROUGHS for SQL consumers_ | borough_code | 3 |
| `analysis.category_anchor` | table | one category with its anchored floor _`boroughs` is a PARAMETER RECORD of the run scope, not a borough dimension, and it spells the long form because it filtered analysis.hex (calib), which does too_ | category | 21 |
| `analysis.coverage_validation` | table | h3 cell x category -- a STALE HEX grain in an address-era table _8,603 rows over 2,984 distinct (h3_index,category)_ | - | 24 |
| `analysis.dev_pipeline` | table | one DOB job | job_number | 43 |
| `analysis.licence_interval` | table | one DCWP licence with its status interval _NO status-change date is published: surrender and revocation are bounds, only expiry is observed_ | licence_number | 28 |
| `analysis.licence_interval_poi` | view | one licence joined to its POI _the identity join matches 0.9% -- licences carry the legal entity, the ledger the awning name_ | - | 6 |
| `analysis.nta_character` | view | one NTA with its character labels | - | 19 |
| `analysis.poi_colocation` | view | one address hosting 2+ POIs _two POIs at one address means resolve which is still open before counting -- never count both (D94)_ | - | 9 |
| `analysis.poi_dedup` | table | one staging.poi row with its resolved cluster _1:1 with staging.poi. Its `category` disagrees with staging.poi on 10,551 rows -- audit finding 3 drops that column_ | poi_id | 48 |
| `analysis.poi_first_seen` | view | one location with its first-seen month and provenance | - | 30 |
| `analysis.poi_presence` | table | one deduplicated business LOCATION, month-tracked _the first-seen/last-seen ledger. Carries all five boroughs ON PURPOSE -- reach is spatial and crosses borough lines_ | location_key | 105 |
| `analysis.poi_supply` | view | one open business location counted as supply | - | 46 |
| `analysis.poi_supply_status` | view | one location with its open/closed/unknown verdict _reads analysis.supply_asof, not current_date_ | - | 29 |
| `analysis.sidewalk_count` | table | camera x frame x model x model version | camera_id,frame_hash,model,model_version | 20 |
| `analysis.storefront` | table | ONE FILING for one storefront -- NOT one storefront _storefront_id RENUMBERS between filings. Group by reporting_year and you pool a full filing with a vacant_only supplement: use analysis.storefront_year_ | storefront_id,filing_due_date | 61 |
| `analysis.storefront_latest` | view | one PREMISES with its latest observation _keyed on premises_id because storefront_id renumbers between filings_ | premises_id | 5 |
| `analysis.storefront_pipeline` | table | one pipeline record for one premises | pipeline_id | 56 |
| `analysis.storefront_pipeline_lead` | view | one premises with its leading pipeline stage | - | 2 |
| `analysis.storefront_pipeline_screen` | view | analysis.storefront_pipeline restricted to MN+BK, NULL borough kept and labelled | pipeline_id | 1 |
| `analysis.storefront_screen` | view | analysis.storefront restricted to MN+BK, NULL borough kept and labelled | storefront_id,filing_due_date | 1 |
| `analysis.storefront_year` | view | one premises x reporting year, ONE filing per cell (full wins) _the fix for the pooled full/vacant_only double count. A vacant_only-only year has no denominator: read `universe` before computing a rate_ | premises_id,reporting_year | 5 |
| `analysis.supply_asof` | table | exactly one row, the pinned supply as-of date _read this, never current_date, for any row-status decision_ | pin | 25 |
| `analysis.zip_category_establishments` | table | year x zipcode x Loci category | year,zipcode,category | 17 |
| `analysis.zip_coverage_by_source` | table | year x zipcode x category x source | year,zipcode,category,source | 12 |
| `analysis.zip_coverage_check` | table | year x zipcode x category, POI count vs ZBP establishments _built FIRST and deliberately a base table, not a view over zip_coverage_by_source -- see model/zbp_compare.py:228-232_ | year,zipcode,category | 13 |
| `analysis.zip_establishments` | table | year x zipcode x NAICS x employment-size band -- the name understates it | year,zipcode,naics,emp_size_band | 12 |

## Score — the screen's outputs

| Object | Kind | Grain | Key | Rd |
|---|---|---|---|---|
| `analysis.address_category` | table | address x category _4,980,615 rows = 332,041 addresses x 15 categories_ | borough,address_id,category | 130 |
| `analysis.address_gaps` | view | one address with its per-category gap measures _GENERATED from loci.categories.CATEGORIES by model/address_gaps.address_gaps_view_sql, not static DDL. A new analysis.address column will never reach it silently_ | - | 74 |
| `analysis.forecast` | table | address x category x issued_month x model_version -- one frozen prediction _EVERY vintage is kept (owner 2026-09-16). The frozen vintage is the point: a query-time view cannot replace it_ | issued_month,model_version,address_id,category | 73 |
| `analysis.forecast_latest` | view | address x category, newest shipped vintage _orders by frozen_at DESC then model_version DESC. Ordering by the git hash alone picks the wrong vintage -- five same-month vintages are live and they genuinely disagree_ | - | 13 |
| `analysis.forecast_run` | table | one fit -- issued_month x model_version _the FIT, not the predictions_ | issued_month,model_version | 18 |
| `analysis.forecast_surprise_nta` | view | NTA x category for one scored vintage _an NTA with no expected value is NOT emitted, and a NULL z_clustered is never backfilled from z_naive_ | - | 11 |
| `analysis.recommendation` | table | one issued recommendation card | rec_id | 25 |
| `analysis.recommendation_category_summary` | view | one category with its recommendation counts | - | 3 |
| `analysis.recommendation_latest` | view | one recommendation, latest status | rec_id | 6 |

## Ledger — append-only events and provenance

| Object | Kind | Grain | Key | Rd |
|---|---|---|---|---|
| `analysis.address_observation` | table | one field observation of one address | observation_id | 12 |
| `analysis.forecast_outcome` | table | one forecast x scored_month _append-only realized join. Never prune it to match a forecast retention rule_ | issued_month,model_version,address_id,category,scored_month | 26 |
| `analysis.poi_closure_evidence` | table | one piece of evidence for one closure | evidence_id | 13 |
| `analysis.poi_key_map` | table | one planned key rewrite _append-only log: 12,011 rows over 8,134 distinct poi_id, which is correct for a log and wrong for a lookup_ | old_key,planned_at | 20 |
| `analysis.recommendation_outcome` | table | one recommendation x snapshot month | rec_id,snapshot_month | 7 |
| `analysis.spend_ledger` | table | one paid-source spend event | - | 19 |
| `chains.brand_latest` | view | one brand, latest snapshot | brand_key | 13 |
| `chains.brand_location` | table | brand x location x snapshot month _borough is spelled long-form_ | snapshot_month,brand_key,location_key | 28 |
| `chains.brand_snapshot` | table | brand x snapshot month | snapshot_month,brand_key | 23 |
| `chains.press_hits` | table | one press mention of one brand | brand_key,url | 16 |

## Calibration inputs — NOT deliverables (see 'no more hexes', D-2026-09-05)

| Object | Kind | Grain | Key | Rd |
|---|---|---|---|---|
| `analysis.hex` | table | one h3 res-9 cell _borough is spelled long-form here. THE ONE remaining long-form carrier in analysis.*_ | h3_index | 57 |
| `analysis.hex_access` | table | h3 cell x category x threshold | h3_index,category,threshold_min | 7 |
| `analysis.hex_controls` | table | one h3 cell with its controls | h3_index | 16 |
| `analysis.hex_demographics` | table | h3 cell x ACS vintage _the same 20 ACS measures as address_demographics, at a second grain_ | h3_index,acs_year | 20 |
| `analysis.hex_panel` | table | h3 cell x year x NAICS | h3_index,year,naics | 12 |
| `analysis.hex_poi_distance` | table | h3 cell x POI -- NOT cell x category _10,645,460 rows, 225 MiB, no declared key. Read by reach.py and model/gaps.py for reach-tier calibration_ | - | 18 |
