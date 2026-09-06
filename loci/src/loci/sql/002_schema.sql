-- Loci: schemas and the analysis-layer contract (DuckDB).
--
-- raw       : source data as landed, untransformed. Never edited in place.
-- staging   : normalized to the common schema. City adapters write here.
-- analysis  : the hex grid and everything joined to it. Model inputs live here.
--
-- staging.poi is what src/loci/score/ consumes. It contains NO city-specific
-- columns -- see docs/CONTEXT.md section 10.
--
-- DuckDB notes vs. the earlier PostGIS draft:
--   * GEOMETRY carries no SRID. Everything here is EPSG:4326 by convention;
--     metric work reprojects explicitly with ST_Transform. Enforce this in code,
--     because the database will not.
--   * Spatial indexes are RTREE, not GiST.
--   * JSON, not JSONB.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analysis;

-- ---------------------------------------------------------------- staging.poi
-- The single normalized POI table. Every source -- universal or city -- lands
-- here through an adapter. src/loci/score/ reads only this.
CREATE TABLE IF NOT EXISTS staging.poi (
    poi_id           VARCHAR PRIMARY KEY,
    source_id        VARCHAR  NOT NULL,   -- must match an id in loci/registry.yaml
    source_record_id VARCHAR,
    category         VARCHAR  NOT NULL,   -- one of the 15 categories, CONTEXT.md 2.1
    tier             SMALLINT NOT NULL CHECK (tier BETWEEN 1 AND 4),
    name             VARCHAR,
    geom             GEOMETRY NOT NULL,   -- EPSG:4326 by convention
    observed_on      DATE,                -- snapshot vintage
    opened_on        DATE,                -- null unless the source is dated
    closed_on        DATE,
    confidence       FLOAT CHECK (confidence BETWEEN 0 AND 1),
    attrs            JSON
);

-- ---------------------------------------------------------------- analysis.hex
-- H3 res 9 grid, shoreline-clipped. land_fraction normalizes edge hexes
-- (CONTEXT.md 7.7). h3_index is the 15-char string form.
CREATE TABLE IF NOT EXISTS analysis.hex (
    h3_index      VARCHAR PRIMARY KEY,
    resolution    SMALLINT NOT NULL DEFAULT 9,
    geom          GEOMETRY NOT NULL,
    centroid      GEOMETRY NOT NULL,
    land_fraction FLOAT NOT NULL CHECK (land_fraction > 0 AND land_fraction <= 1),
    borough       VARCHAR,
    nta_code      VARCHAR
);

-- Demographics dasymetrically interpolated from ACS tracts (CONTEXT.md 4.2).
-- MOEs are carried, not discarded.
CREATE TABLE IF NOT EXISTS analysis.hex_demographics (
    h3_index             VARCHAR REFERENCES analysis.hex(h3_index),
    acs_year             SMALLINT NOT NULL,
    population           FLOAT, population_moe       FLOAT,
    households           FLOAT, households_moe       FLOAT,
    median_hh_income     FLOAT, median_hh_income_moe FLOAT,
    renter_share         FLOAT,
    PRIMARY KEY (h3_index, acs_year)
);

-- Controls: zoning capacity, transit access, development headroom.
CREATE TABLE IF NOT EXISTS analysis.hex_controls (
    h3_index           VARCHAR PRIMARY KEY REFERENCES analysis.hex(h3_index),
    comm_far_capacity  FLOAT,   -- PLUTO CommFAR, area-weighted. REQUIRED control.
    resid_far          FLOAT,
    built_far          FLOAT,
    dev_headroom       FLOAT,   -- (ResidFAR - BuiltFAR) clipped at 0
    units_res          FLOAT,
    walk_m_to_subway   FLOAT,   -- network distance to nearest ENTRANCE, not centroid
    subway_routes      SMALLINT,
    subway_riders_2024 FLOAT
);

-- Every (hex, business) pair within a 30-minute walk, with the NETWORK distance
-- along the pedestrian graph (CONTEXT.md 4.3). This is the primary access artifact;
-- hex_access below is DERIVED from it by counting at each threshold, so any walk
-- time, nearest-distance or spacing question is a query here, not a recompute.
-- No primary key ON PURPOSE: (h3_index, poi_id) is unique by construction (one
-- Dijkstra row per hex node, expanded per POI), and DuckDB's ART index on two
-- VARCHARs for 16M rows tripled the file (533 MB -> 1.6 GB) and slowed the load 7x.
CREATE TABLE IF NOT EXISTS analysis.hex_poi_distance (
    h3_index   VARCHAR NOT NULL,
    poi_id     VARCHAR NOT NULL,
    category   VARCHAR NOT NULL,
    network_m  REAL    NOT NULL CHECK (network_m >= 0)
);

-- Per-category access at each walk threshold (CONTEXT.md 4.3).
CREATE TABLE IF NOT EXISTS analysis.hex_access (
    h3_index      VARCHAR REFERENCES analysis.hex(h3_index),
    category      VARCHAR  NOT NULL,
    threshold_min SMALLINT NOT NULL CHECK (threshold_min IN (5, 10, 15)),
    n_reachable   INTEGER  NOT NULL,
    served_share  FLOAT    NOT NULL CHECK (served_share BETWEEN 0 AND 1),
    PRIMARY KEY (h3_index, category, threshold_min)
);

-- The index, the supply-model fit, and the residual (CONTEXT.md 4.4-4.5).
CREATE TABLE IF NOT EXISTS analysis.hex_dnci (
    h3_index       VARCHAR REFERENCES analysis.hex(h3_index),
    threshold_min  SMALLINT NOT NULL,
    dnci           FLOAT NOT NULL CHECK (dnci BETWEEN 0 AND 1),
    dnci_predicted FLOAT,
    residual       FLOAT,   -- the signal. negative = underserved vs. peers.
    opportunity    FLOAT,
    model_version  VARCHAR NOT NULL,
    PRIMARY KEY (h3_index, threshold_min, model_version)
);

-- LODES WAC annual panel, block -> hex (CONTEXT.md 4.6). Jobs, not
-- establishments -- see threat 7.4.
CREATE TABLE IF NOT EXISTS analysis.hex_panel (
    h3_index VARCHAR REFERENCES analysis.hex(h3_index),
    year     SMALLINT NOT NULL CHECK (year BETWEEN 2002 AND 2023),
    naics    VARCHAR  NOT NULL,
    jobs     FLOAT    NOT NULL,
    PRIMARY KEY (h3_index, year, naics)
);

-- Outcomes for the growth regression.
CREATE TABLE IF NOT EXISTS analysis.hex_outcomes (
    h3_index         VARCHAR REFERENCES analysis.hex(h3_index),
    period_start     SMALLINT NOT NULL,
    period_end       SMALLINT NOT NULL,
    d_log_population FLOAT,
    d_log_households FLOAT,
    d_log_zori       FLOAT,
    permitted_units  FLOAT,
    PRIMARY KEY (h3_index, period_start, period_end)
);

-- Ground-truth enumeration for the coverage-bias test (CONTEXT.md 7.1 / P3).
-- This table is the evidence for the prediction most likely to kill the project.
CREATE TABLE IF NOT EXISTS analysis.coverage_validation (
    h3_index       VARCHAR REFERENCES analysis.hex(h3_index),
    category       VARCHAR NOT NULL,
    income_decile  SMALLINT NOT NULL CHECK (income_decile BETWEEN 1 AND 10),
    n_ground_truth INTEGER NOT NULL,   -- Google Places enumeration
    n_overture     INTEGER NOT NULL,
    n_osm          INTEGER NOT NULL,
    n_city_source  INTEGER,            -- DOHMH/DCWP where the category has one
    sampled_on     DATE NOT NULL,
    PRIMARY KEY (h3_index, category)
);

-- n_overture/n_osm/n_city_source above are read straight off staging.poi (raw,
-- un-deduped) and, before this fix, only ever unpacked two of the three+ source
-- ids actually ingested -- see loci.validation.sample._local_counts. Neither
-- defect touches the gap screen itself (analysis.hex_gaps is built from the
-- deduped canonical layer via hex_poi_distance), but it made every row in this
-- table compare Google's enumeration against a partial, non-canonical inventory
-- of loci's own coverage. n_local_canonical is the corrected total: canonical
-- (is_canonical) POIs of the category, across ALL ingested sources, within the
-- same straight-line RADIUS_M used for n_ground_truth. Nullable so historical
-- rows read NULL until `loci validate --recount-local` backfills them.
ALTER TABLE analysis.coverage_validation ADD COLUMN IF NOT EXISTS n_local_canonical INTEGER;

-- Cross-source entity resolution (GTM-20). Maps each staging.poi row to a
-- cluster of duplicates across sources; is_canonical marks the one kept for
-- scoring. Without this the DNCI inflates wherever source coverage overlaps,
-- and overlap is geographically biased, so the error is not random.
CREATE TABLE IF NOT EXISTS analysis.poi_dedup (
    poi_id       VARCHAR PRIMARY KEY,
    cluster_id   BIGINT  NOT NULL,
    is_canonical BOOLEAN NOT NULL,
    category     VARCHAR NOT NULL
);

-- Per-hex investment screen (present-day): a walkable, populated hex missing an
-- "expected" daily-needs business — one that areas like it normally have, so its
-- absence is conspicuous. The missing business IS the opportunity. Ranked (for
-- now) by resident population; "people affected" = walking-catchment population
-- is a later refinement.
CREATE TABLE IF NOT EXISTS analysis.hex_gaps (
    h3_index          VARCHAR NOT NULL,
    threshold_min     SMALLINT NOT NULL,
    population        REAL,
    present_count     SMALLINT NOT NULL,
    lead_missing      VARCHAR,      -- the most-expected missing business
    lead_prevalence   REAL,         -- share of areas that have it
    missing_expected  VARCHAR,      -- all conspicuously-missing businesses (comma-sep)
    PRIMARY KEY (h3_index, threshold_min)
);

-- Demand-side context (CHECKPOINT demand-caveat ticket; Meltzer & Schuetz 2012,
-- src/loci/demand.yaml): ANNOTATES each gap row, never filters -- the set of gap
-- hexes and the set of (hex, category) missing pairs are unaffected by these
-- columns (tests/test_demand_caveat.py part (c)). median_hh_income/renter_share
-- come from analysis.hex_demographics at the same acs_year the rest of the gap
-- screen uses (2023). income_class is 'low' if median_hh_income < the
-- demand.yaml `low_income_cutoff` times the citywide population-weighted mean
-- household income (over hexes with population > 0), else 'mid_high'; NULL if
-- income is NULL. demand_caveat flags the LEAD missing category (model/gaps.py
-- prefers a non-caveated category for lead; falls back only if every missing
-- category is caveated) as discretionary in a low-income hex -- per the paper,
-- plausibly demand-following rather than a conspicuous supply gap.
-- caveated_missing lists every caveated category among missing_expected, not
-- just the lead.
ALTER TABLE analysis.hex_gaps ADD COLUMN IF NOT EXISTS median_hh_income REAL;
ALTER TABLE analysis.hex_gaps ADD COLUMN IF NOT EXISTS renter_share REAL;
ALTER TABLE analysis.hex_gaps ADD COLUMN IF NOT EXISTS income_class VARCHAR;
ALTER TABLE analysis.hex_gaps ADD COLUMN IF NOT EXISTS demand_caveat BOOLEAN;
ALTER TABLE analysis.hex_gaps ADD COLUMN IF NOT EXISTS caveated_missing VARCHAR;

-- Same screen, REACH-based rule (QUESTIONS D6, CHECKPOINT D33): each category
-- gets a fixed reach distance (src/loci/reach.yaml) instead of one shared walk
-- window, so tightening a reach can only add gaps, never remove them (the
-- monotonicity property analysis.hex_gaps' window rule violates). Kept in its
-- own table, never mixed with hex_gaps, so `loci gaps --rule window` (the
-- default, and everything downstream that reads hex_gaps) is unaffected.
CREATE TABLE IF NOT EXISTS analysis.hex_gaps_reach (
    h3_index          VARCHAR NOT NULL,
    population        REAL,
    present_count     SMALLINT NOT NULL,
    lead_missing      VARCHAR,      -- missing category with the smallest reach
    lead_reach_m      REAL,         -- reach(lead), metres — not a 0-1 share
    missing_expected  VARCHAR,      -- all categories missing beyond their reach (comma-sep)
    PRIMARY KEY (h3_index)
);

-- Provenance (defect review item 4): without these, two runs of `loci gaps
-- --rule reach` at different --quantile values (or after editing reach.yaml)
-- are indistinguishable once written, because the table is fully replaced
-- each run. reach_quantile/reach_min_pop are reach.yaml's own `quantile` and
-- `min_pop` fields (NULL when a caller passed an explicit reach dict, e.g.
-- tests, bypassing the file); reach_hash is a hash of the actual
-- {category: reach_m} used for the run, so it is always populated and lets
-- two runs be compared even when the quantile/min_pop are unknown.
ALTER TABLE analysis.hex_gaps_reach ADD COLUMN IF NOT EXISTS reach_quantile REAL;
ALTER TABLE analysis.hex_gaps_reach ADD COLUMN IF NOT EXISTS reach_min_pop REAL;
ALTER TABLE analysis.hex_gaps_reach ADD COLUMN IF NOT EXISTS reach_hash VARCHAR;

-- Demand-side context, same definition and rationale as analysis.hex_gaps'
-- identically-named columns above (CHECKPOINT demand-caveat ticket).
ALTER TABLE analysis.hex_gaps_reach ADD COLUMN IF NOT EXISTS median_hh_income REAL;
ALTER TABLE analysis.hex_gaps_reach ADD COLUMN IF NOT EXISTS renter_share REAL;
ALTER TABLE analysis.hex_gaps_reach ADD COLUMN IF NOT EXISTS income_class VARCHAR;
ALTER TABLE analysis.hex_gaps_reach ADD COLUMN IF NOT EXISTS demand_caveat BOOLEAN;
ALTER TABLE analysis.hex_gaps_reach ADD COLUMN IF NOT EXISTS caveated_missing VARCHAR;

-- Address-level convenience check (docs/CHECKPOINT.md D-conveniences): for
-- every residential address, per-category network distance to the nearest
-- canonical business and whether it clears the OWNER-SET norm in
-- src/loci/conveniences.yaml (not a data-derived threshold -- see that
-- file's header). Distinct from hex_gaps/hex_gaps_reach: this is an
-- absolute per-address question, not a relative per-hex one, and the two
-- are never read together. One row per (borough, address); address_id is
-- the PLUTO BBL where available (see sources/cities/nyc/addresses.py), so
-- unique per tax lot without a borough qualifier in practice, but the
-- borough is still part of the key to keep a per-borough rebuild
-- (`loci conveniences build --borough X`) from ever colliding with another
-- borough's fallback row-index ids.
CREATE TABLE IF NOT EXISTS analysis.address_convenience (
    address_id             VARCHAR NOT NULL,
    bbl                     VARCHAR,
    lon                     DOUBLE  NOT NULL,
    lat                     DOUBLE  NOT NULL,
    units                   REAL,
    nta_code                VARCHAR,
    neighborhood            VARCHAR,
    -- one {category}_distance_m / {category}_satisfied pair per Loci category
    -- (categories.py order). distance_m is NULL beyond the 30-minute network
    -- cap (hex_poi_distance's convention) -- always unsatisfied in that case.
    grocery_distance_m       REAL, grocery_satisfied       BOOLEAN,
    convenience_distance_m   REAL, convenience_satisfied   BOOLEAN,
    pharmacy_distance_m      REAL, pharmacy_satisfied      BOOLEAN,
    laundry_distance_m       REAL, laundry_satisfied       BOOLEAN,
    hair_barber_distance_m   REAL, hair_barber_satisfied   BOOLEAN,
    nails_beauty_distance_m  REAL, nails_beauty_satisfied  BOOLEAN,
    tailor_repair_distance_m REAL, tailor_repair_satisfied BOOLEAN,
    restaurant_distance_m    REAL, restaurant_satisfied    BOOLEAN,
    cafe_bakery_distance_m   REAL, cafe_bakery_satisfied   BOOLEAN,
    bar_distance_m           REAL, bar_satisfied           BOOLEAN,
    childcare_distance_m     REAL, childcare_satisfied     BOOLEAN,
    clinic_distance_m        REAL, clinic_satisfied        BOOLEAN,
    fitness_distance_m       REAL, fitness_satisfied       BOOLEAN,
    bank_distance_m          REAL, bank_satisfied          BOOLEAN,
    hardware_distance_m      REAL, hardware_satisfied      BOOLEAN,
    n_unsatisfied           SMALLINT NOT NULL CHECK (n_unsatisfied BETWEEN 0 AND 15),
    -- provenance: which conveniences.yaml, which walk graph, and when this
    -- row was computed, so two runs (after editing either input) are
    -- distinguishable once written -- same rationale as hex_gaps_reach above.
    conveniences_hash        VARCHAR NOT NULL,
    graph_version             VARCHAR NOT NULL,
    run_at                     TIMESTAMP NOT NULL,
    borough                    VARCHAR NOT NULL,
    PRIMARY KEY (borough, address_id)
);

-- Address-level GAP screen (CHECKPOINT D33/D38/D39/D41) -- REPLACES the old
-- 800m/>=80%-prevalence rule that once lived in model/address_gaps.py.
-- Per residential PLUTO lot (UnitsRes > 0, D38): a FIXED, reach-independent
-- walkability gate (`eligible` -- present within 800 m for >= 12 of the 15
-- categories, mirroring model/gaps.py's `_eligible_universe` at address
-- grain) decides which addresses are in scope at all; among eligible
-- addresses, `gap_score` = max over categories of nearest_m/reach_m is a
-- CONTINUOUS ranking (D39), not a binary "exactly one missing" list --
-- gap_score > 1 means at least one category sits beyond its reach.
-- `lead_category`/`lead_excess_m` name the worst (max-ratio) category;
-- ties go to the larger raw nearest_m (the more conspicuous absence).
-- `n_missing` counts categories with ratio > 1. All four are NULL/0 for an
-- ineligible address -- out of scope, like a hex that fails the window gate.
-- `units_capped` clips units at 500/lot for unit-weighted ranking (D39 found
-- Co-op City-scale lots with ~10k units dominate an uncapped rank); raw
-- `units` is kept alongside it. `cluster_id` groups eligible, gap_score > 1
-- addresses that share a lead_category and sit within ~200 m of each other
-- (single-linkage/DBSCAN-like, eps=200m) -- the action signal is a CLUSTER of
-- addresses missing the same business, not one address. reach_source/
-- reach_hash/graph_version/run_at are provenance, same rationale as
-- hex_gaps_reach/address_convenience above: two runs (tiers vs p80 reach, or
-- after a graph rebuild) must be distinguishable once written.
CREATE TABLE IF NOT EXISTS analysis.address_gaps (
    address_id        VARCHAR NOT NULL,
    bbl               VARCHAR,
    lon               DOUBLE  NOT NULL,
    lat               DOUBLE  NOT NULL,
    units             REAL,
    units_capped      REAL,
    nta_code          VARCHAR,
    neighborhood      VARCHAR,
    borough           VARCHAR NOT NULL,
    present_count     SMALLINT NOT NULL,   -- categories present within 800m (the fixed gate's own count)
    eligible          BOOLEAN NOT NULL,    -- present_count >= 12; reach-independent by construction
    gap_score         REAL,                -- max(nearest_m / reach_m); NULL if not eligible
    lead_category     VARCHAR,             -- argmax ratio, ties -> larger nearest_m; NULL if not eligible
    lead_excess_m     REAL,                -- nearest_m - reach_m at lead_category; NULL if not eligible
    n_missing         SMALLINT NOT NULL,   -- count of categories with ratio > 1; 0 if not eligible
    cluster_id        VARCHAR,             -- "{borough}:{lead_category}:{local_id}"; NULL unless gap_score > 1
    -- one {category}_nearest_m / {category}_ratio pair per Loci category
    -- (categories.py order). nearest_m is censored at the 30-minute network
    -- cap (hex_poi_distance's convention) for a category with nothing
    -- reachable -- ratio is still finite (cap / reach) in that case.
    grocery_nearest_m       REAL, grocery_ratio       REAL,
    convenience_nearest_m   REAL, convenience_ratio   REAL,
    pharmacy_nearest_m      REAL, pharmacy_ratio      REAL,
    laundry_nearest_m       REAL, laundry_ratio       REAL,
    hair_barber_nearest_m   REAL, hair_barber_ratio   REAL,
    nails_beauty_nearest_m  REAL, nails_beauty_ratio  REAL,
    tailor_repair_nearest_m REAL, tailor_repair_ratio REAL,
    restaurant_nearest_m    REAL, restaurant_ratio    REAL,
    cafe_bakery_nearest_m   REAL, cafe_bakery_ratio   REAL,
    bar_nearest_m           REAL, bar_ratio           REAL,
    childcare_nearest_m     REAL, childcare_ratio     REAL,
    clinic_nearest_m        REAL, clinic_ratio        REAL,
    fitness_nearest_m       REAL, fitness_ratio       REAL,
    bank_nearest_m          REAL, bank_ratio          REAL,
    hardware_nearest_m      REAL, hardware_ratio      REAL,
    reach_source      VARCHAR NOT NULL CHECK (reach_source IN ('tiers', 'p80')),
    reach_hash        VARCHAR NOT NULL,
    graph_version     VARCHAR NOT NULL,
    run_at            TIMESTAMP NOT NULL,
    PRIMARY KEY (borough, address_id)
);

-- Census ZIP Business Patterns (ZBP), via the County Business Patterns (CBP)
-- API (registry.yaml `census_zbp`; docs/CHECKPOINT.md ZBP-validation ticket).
-- VALIDATION AND CALIBRATION ONLY -- an external, ZIP-level, establishment-
-- count check on Loci's POI coverage. NEVER read by score/ or model/, and
-- never joined into staging.poi or any hex_* table: ZIP is far coarser than
-- Loci's geography of record and NAICS self-classification bleeds between
-- adjacent categories (see src/loci/zbp_naics.yaml header).
--
-- One row per (year, zipcode, naics, emp_size_band) at the FINEST NAICS level
-- CBP returns (6-digit); coarser 2-5 digit rollups the API also returns are
-- NOT stored here (they are a sum over these rows and storing both would
-- risk a double-count if ever queried without an explicit length filter).
-- ALL NAICS codes are kept, not just the 15 mapped categories, because the
-- mixed-format check (loci zbp-compare) needs the full distribution to see
-- what a POI actually got misclassified into.
--
-- A (year, zipcode, naics, emp_size_band) cell ABSENT from this table is not
-- necessarily zero -- Census cell-suppresses small counts and the CBP API
-- simply omits the row rather than returning a flagged zero. Never read a
-- missing row as "0 establishments" without checking estab_total (band
-- 'All establishments') is itself present for that (zipcode, naics).
CREATE TABLE IF NOT EXISTS analysis.zip_establishments (
    year          SMALLINT NOT NULL,
    zipcode       VARCHAR  NOT NULL,
    naics         VARCHAR  NOT NULL,   -- 6-digit NAICS 2017 code
    naics_label   VARCHAR,
    emp_size_band VARCHAR  NOT NULL,   -- CBP EMPSZES_LABEL text, e.g.
                                        -- 'All establishments',
                                        -- 'Establishments with less than 5 employees'
    estab         INTEGER  NOT NULL CHECK (estab >= 0),
    PRIMARY KEY (year, zipcode, naics, emp_size_band)
);

-- Per-category rollup of the above via src/loci/zbp_naics.yaml, for the 15
-- Loci categories only. estab_total is the EMPSZES='001' ('All
-- establishments') band, summed across every NAICS code mapped to the
-- category; the four size bands are EMPSZES 210 / 220 / 230 / (241+242+251+
-- 252+254+260) respectively, per src/loci/sources/universal/census_zbp.py.
-- Built by `loci ingest-zbp`, never hand-edited.
CREATE TABLE IF NOT EXISTS analysis.zip_category_establishments (
    year             SMALLINT NOT NULL,
    zipcode          VARCHAR  NOT NULL,
    category         VARCHAR  NOT NULL,
    estab_total      INTEGER,   -- EMPSZES 001, 'All establishments'
    estab_small_1_4  INTEGER,   -- EMPSZES 210, '... less than 5 employees'
    estab_5_9        INTEGER,   -- EMPSZES 220
    estab_10_19      INTEGER,   -- EMPSZES 230
    estab_20_plus    INTEGER,   -- EMPSZES 241+242+251+252+254+260 combined
    PRIMARY KEY (year, zipcode, category)
);

-- ZIP-level comparison of Loci's deduped POI count against the ZBP
-- establishment count, per category and year (`loci zbp-compare`). ratio =
-- poi_count / NULLIF(zbp_estab, 0); ratio << 1 suggests Loci POI
-- undercoverage in that ZIP/category, ratio >> 1 suggests POI overcount /
-- a dedup miss / NAICS bleed inflating the ZBP side. VALIDATION ONLY -- never
-- feeds analysis.hex_gaps or analysis.hex_gaps_reach.
CREATE TABLE IF NOT EXISTS analysis.zip_coverage_check (
    year      SMALLINT NOT NULL,
    zipcode   VARCHAR  NOT NULL,
    category  VARCHAR  NOT NULL,
    poi_count INTEGER  NOT NULL,
    zbp_estab INTEGER,
    ratio     DOUBLE,
    PRIMARY KEY (year, zipcode, category)
);

-- Per-SOURCE rollup of the row above (`loci zbp-compare --by-source`,
-- QUESTIONS.md M9 follow-up): which feed's canonical POIs drive each
-- category's overcount vs ZBP. `source` is the canonical POI's own
-- source_id -- analysis.poi_dedup.is_canonical always marks the cluster's
-- highest-ranked member per score/dedup.py source_rank(), so "the canonical
-- record's source" and "the highest-ranked member source" are the same
-- thing here; there is no separate member-source list to choose between.
-- poi_count_single_source counts canonical POIs whose ENTIRE dedup cluster
-- (every member row, not just the canonical one) draws from exactly one
-- distinct source_id -- a record no other feed corroborates. Built by
-- inner-joining onto analysis.zip_coverage_check's already-filtered
-- (year, zipcode, category) rows, so summing poi_count over source for a
-- given (year, zipcode, category) reproduces zip_coverage_check.poi_count
-- exactly, and a (zipcode, category) with poi_count 0 in the base table
-- contributes no rows here (nothing to attribute). Same population >= 1,000
-- and suppressed-cell exclusions as zip_coverage_check. VALIDATION ONLY --
-- same caveats as zip_coverage_check; never feeds analysis.hex_gaps or
-- analysis.hex_gaps_reach.
CREATE TABLE IF NOT EXISTS analysis.zip_coverage_by_source (
    year                    SMALLINT NOT NULL,
    zipcode                 VARCHAR  NOT NULL,
    category                VARCHAR  NOT NULL,
    source                  VARCHAR  NOT NULL,
    poi_count               INTEGER  NOT NULL,
    poi_count_single_source INTEGER  NOT NULL,
    zbp_estab               INTEGER,
    ratio                   DOUBLE,
    PRIMARY KEY (year, zipcode, category, source)
);
