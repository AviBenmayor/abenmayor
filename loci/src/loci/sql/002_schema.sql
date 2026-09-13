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

-- D54 (GTM-78 D7 pre-test, session 13): renter_share was the only ACS field
-- carried without a propagated MOE (B25003_001M/_003M were never fetched),
-- and the D7 density-class pre-test on renter_share came back negative --
-- it proxies population density (rho=0.62 citywide, 0.09 within Manhattan),
-- not travel mode. This adds the ACS vehicle-ownership measures (B08201
-- household-level zero-vehicle share; B25044 tenure-split cross-check) that
-- the pre-test recommended, plus the missing renter_share MOE. See
-- src/loci/grid/acs.py::build_acs for the tract->hex propagation and the
-- ACS-handbook proportion-MOE formula.
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS renter_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS zero_vehicle_hh_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS zero_vehicle_hh_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS zero_vehicle_owner_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS zero_vehicle_owner_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS zero_vehicle_renter_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS zero_vehicle_renter_share_moe FLOAT;

-- 2026-09-09 AGE / RACE / EDUCATION / HOUSEHOLD-SIZE extension (owner request).
-- Four demographic groups the grid never carried, every one of them MOE-carried
-- like the D54 block above, and every one of them joined onto the ADDRESS output
-- (analysis.address_gaps) rather than stopping at the hex grid -- a column that
-- lands only here is not delivered.
--   * median_age            B01002_001. INTENSIVE: unit-share-weighted mean of
--                           tract medians, the same approximation (and the same
--                           caveat -- a mean of medians is not a median) that
--                           median_hh_income above already carries.
--   * under_18/18_34/65_plus_share  B01001 (sex by age), male + female cells
--                           summed per band over the table's OWN total
--                           B01001_001. 35-64 is intentionally absent: it is
--                           1 - (the three) and a fourth column would read as
--                           independent when it is not.
--   * white_nh/black_nh/asian_nh/hispanic_share  B03002 _003/_004/_006 (not
--                           Hispanic, single race) and _012 (Hispanic, any
--                           race) over _001. They sum to <= 1; the remainder is
--                           the small non-Hispanic AIAN/NHPI/other/multiracial
--                           categories, not carried.
--   * college_share         B15003 (_022+_023+_024+_025)/_001 -- bachelor's and
--                           above over the population 25 AND OVER, which is the
--                           table's own universe. Associate's (_021) excluded,
--                           matching model/momentum.py's existing use of B15003.
--   * avg_hh_size           B25010_001. INTENSIVE, same treatment as median_age.
--   * one_person_hh_share   B11016 _010/_001. _010 is the only 1-person cell in
--                           the table (a family household is 2+ by definition);
--                           the denominator is ALL households, not nonfamily.
-- Cell indices verified against api.census.gov/data/2023/acs/acs5/variables.json
-- on 2026-09-09; src/loci/grid/acs.py::build_acs additionally cross-checks
-- B01001_001E against B01003_001E per tract and RAISES on a material mismatch.
-- CAVEAT THE DATABASE CANNOT ENFORCE (same as D54): a proportion MOE on a hex
-- with a near-zero apportioned denominator can exceed 1. Anything that sorts or
-- filters on a *_moe column must also gate on a minimum apportioned denominator
-- (population for the age/race/education shares, households for the
-- one-person-household share).
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS median_age FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS median_age_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS avg_hh_size FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS avg_hh_size_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS under_18_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS under_18_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS age_18_34_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS age_18_34_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS age_65_plus_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS age_65_plus_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS white_nh_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS white_nh_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS black_nh_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS black_nh_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS asian_nh_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS asian_nh_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS hispanic_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS hispanic_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS college_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS college_share_moe FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS one_person_hh_share FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS one_person_hh_share_moe FLOAT;

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

-- RETIRED UNDER D38 (2026-09-09): analysis.hex_dnci is DROPPED. It held the
-- Daily-Needs Convenience Index per hex per walk threshold, plus the E3 supply
-- model's fitted value and residual. Two reasons it is gone, not frozen:
-- (a) the SCOPE CORRECTION at the top of CHECKPOINT.md records that the E3
--     residual/growth framing answered the wrong question -- the deliverable is
--     a present-day screen, not a causal growth thesis; and
-- (b) D38 moved the unit of analysis off the hex, so nothing the owner looks at
--     could read it even if the model were right.
-- score/dnci.py keeps `dnci_from_counts` / `category_score` (pure, no DB) so
-- tests/test_dnci.py can still pin the geometric-mean and saturation properties.
-- model/supply.py, the only reader, is deleted.

-- LODES WAC annual panel, block -> hex (CONTEXT.md 4.6). Jobs, not
-- establishments -- see threat 7.4.
CREATE TABLE IF NOT EXISTS analysis.hex_panel (
    h3_index VARCHAR REFERENCES analysis.hex(h3_index),
    year     SMALLINT NOT NULL CHECK (year BETWEEN 2002 AND 2023),
    naics    VARCHAR  NOT NULL,
    jobs     FLOAT    NOT NULL,
    PRIMARY KEY (h3_index, year, naics)
);

-- RETIRED UNDER D38 (2026-09-09): analysis.hex_outcomes is DROPPED. It was the
-- dependent-variable table for the E3 growth regression and never had a writer
-- at all -- it held 0 rows for the life of the project. Dead DDL for a question
-- the SCOPE CORRECTION says Loci is not asking.

-- Ground-truth enumeration for the coverage-bias test (CONTEXT.md 7.1 / P3).
-- This table is the evidence for the prediction most likely to kill the project.
--
-- TWO FRAMES LIVE HERE AND MUST NEVER BE POOLED (CHECKPOINT D38 / D58):
--   * h3_index IS NOT NULL  -> the PRE-D38 HEX frame: 2,970 rows sampled at
--     hex centroids on 2026-09-02/03, every one measured at the legacy
--     straight-line disc (radius_m NULL, i.e. 800 m). Frozen; kept for the
--     D29 hardware/fitness/clinic split, usable only against each other.
--   * address_id IS NOT NULL (h3_index NULL) -> the ADDRESS frame (GTM-48):
--     residential PLUTO lots drawn from analysis.address_gaps, MN+BK (D48),
--     stratified income-decile × missing-this-category, measured at the
--     lot's own lon/lat and the D53 circuity-corrected radius.
-- The unit, the geometry and the radius all differ, so any statistic that
-- mixes the two frames is meaningless -- always filter on one of them.
--
-- There is deliberately NO primary key: the hex-era PRIMARY KEY
-- (h3_index, category) made h3_index implicitly NOT NULL, which physically
-- forbids an address row, and DuckDB has no ALTER TABLE DROP CONSTRAINT.
-- loci.validation.sample.ensure_address_frame() migrates a database still
-- carrying that key (rename -> re-apply this file -> copy rows back), and
-- sample.run() maintains uniqueness itself by deleting the row's own key
-- (h3_index+category, or address_id+category) before inserting.
CREATE TABLE IF NOT EXISTS analysis.coverage_validation (
    h3_index       VARCHAR REFERENCES analysis.hex(h3_index),  -- pre-D38 hex frame only; NULL on address rows
    category       VARCHAR NOT NULL,
    income_decile  SMALLINT NOT NULL CHECK (income_decile BETWEEN 1 AND 10),
    n_ground_truth INTEGER NOT NULL,   -- Google Places enumeration
    n_overture     INTEGER NOT NULL,
    n_osm          INTEGER NOT NULL,
    n_city_source  INTEGER,            -- DOHMH/DCWP where the category has one
    sampled_on     DATE NOT NULL
);

-- GTM-48 / CHECKPOINT D58: the address frame. address_id is the sampled
-- residential lot (analysis.address_gaps.address_id, which is the BBL), and
-- borough is carried beside it because address_gaps is keyed
-- (borough, address_id) and because the MN/BK contrast (D48, QUESTIONS M1)
-- is read straight off this table. Both are nullable: every pre-D38 hex row
-- reads NULL, and a row with a NULL address_id is a hex-frame row, not an
-- address row missing its id.
ALTER TABLE analysis.coverage_validation ADD COLUMN IF NOT EXISTS address_id VARCHAR;
ALTER TABLE analysis.coverage_validation ADD COLUMN IF NOT EXISTS borough    VARCHAR;

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

-- GTM-105 findings B/C/G. n_ground_truth_at_cap: Nearby Search (New) caps
-- maxResultCount at 20 with no nextPageToken, so n_ground_truth == 20 is
-- right-censored, not necessarily the true count. Nullable BOOLEAN: existing
-- rows read NULL ("cap status unknown/not recorded") rather than a
-- misleading default of false; only rows written after this change carry a
-- real true/false. ground_truth_types: per-call histogram of the Google
-- primaryType field (JSON object, primaryType -> count), read off fields
-- already in the field mask at zero extra API spend. Stored as VARCHAR
-- (DuckDB JSON text), same nullable/backward-compat rule -- existing rows
-- read NULL until a future re-run backfills them; nothing here re-spends the
-- Google budget.
ALTER TABLE analysis.coverage_validation ADD COLUMN IF NOT EXISTS n_ground_truth_at_cap BOOLEAN;
ALTER TABLE analysis.coverage_validation ADD COLUMN IF NOT EXISTS ground_truth_types VARCHAR;

-- QUESTIONS M8 / CHECKPOINT D53 (GTM-105 finding D). radius_m: the
-- straight-line radius, in metres, that BOTH sides of this row were measured
-- at -- the Google Nearby Search circle and the local counts. A count is
-- meaningless without it, and the value changed: rows written before D53 used
-- 800 m straight-line, which was the gap screen's 800 m NETWORK threshold
-- misapplied as a straight-line radius, so the validator's disc reached ~1.23x
-- further than the screen it was validating (D29's GEOMETRY-artifact branch).
-- Runs after D53 use the circuity-corrected radius derived in
-- loci.reach.validation_radius_m from src/loci/reach_tiers.yaml. Nullable:
-- existing rows read NULL, meaning "not recorded, historically 800 m"; only
-- rows written after this change carry a real radius. Never pool NULL rows
-- with non-NULL rows in a count statistic.
ALTER TABLE analysis.coverage_validation ADD COLUMN IF NOT EXISTS radius_m INTEGER;

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

-- RETIRED UNDER D38 (2026-09-09): analysis.hex_gaps and analysis.hex_gaps_reach
-- are DROPPED. They were the per-HEX gap screen -- the window rule (726 hexes)
-- and the reach rule (1,966 rows) -- together with the D37/D49 demand
-- annotation columns bolted onto both. D38 made the residential PLUTO lot the
-- unit of analysis and the address screen never read either table; leaving them
-- in place only invited a future session to re-run a screen the owner does not
-- look at and believe the numbers.
--
-- Where each thing went:
--   * the screen itself      -> analysis.address / analysis.address_category,
--                               surfaced wide as the analysis.address_gaps VIEW
--   * the demand annotation  -> the annotation columns on
--                               analysis.address_category (D57), computed from
--                               analysis.address_demographics' tract-direct
--                               income, not a hex-interpolated one
--   * the monotonicity proof -> model/gaps.py's compute functions, which are
--                               kept (pure, no writer) so
--                               tests/test_gaps_monotonicity.py still runs
--   * the caveat wording     -> loci/demand.py, pinned against model/gaps.py's
--                               private copy by tests/test_demand_caveat.py
-- The hex tables the ADDRESS pipeline still reads -- hex, hex_controls,
-- hex_demographics, hex_access, hex_poi_distance, hex_panel -- are untouched.
-- They are a crosswalk and a distance cache, not a geography of record.

-- FOLDED INTO THE GAP TABLES (2026-09-09): analysis.address_convenience is
-- DROPPED. It was a 200-row prototype holding, per address, the same 15
-- per-category network distances the gap screen already computes -- under
-- `<category>_distance_m` instead of `<category>_nearest_m` -- plus a
-- `<category>_satisfied` boolean that is nothing more than
-- `distance_m <= conveniences.yaml[category]`.
--
-- Two per-address distance tables built by two Dijkstra passes over the same
-- graph and the same supply set is a divergence waiting to happen, and the
-- prototype had already diverged: 200 rows against the screen's 767,337.
-- `loci conveniences` survives as a READ-ONLY report that applies
-- conveniences.yaml's owner-set norm to analysis.address_category's
-- `nearest_m` -- the question ("is category c within the OWNER'S norm of this
-- address?") is unchanged, it is simply asked of the distances that already
-- exist rather than re-measured. model/conveniences.py keeps
-- `compute_address_convenience` (pure, graph in / rows out) as the reference
-- Dijkstra implementation that tests/test_conveniences.py pins and
-- model/address_gaps.py's `_dijkstra_per_category` mirrors.

-- ==========================================================================
-- THE ADDRESS SCREEN, in its principled shape: one narrow row per address,
-- one row per (address, category), and a VIEW that reassembles the wide table
-- every existing consumer was written against.
--
-- WHY THE SPLIT. analysis.address_gaps was a single 90-column table carrying
-- three unrelated things at three different grains: facts about the address
-- (identity, units, eligibility, its winning gap), facts about (address,
-- category) pairs smeared across 30 pivoted columns, and a per-address
-- provenance stamp. Adding a 16th category meant an ALTER for two more
-- columns in the DDL, two more entries in every SELECT list, and a migration;
-- the demand annotation could not live there at all and had to become a
-- sibling table (D57). One row per pair makes all three problems go away, and
-- the wide shape is regenerated mechanically, so it can never drift from
-- categories.yaml.
--
-- WHAT MOVED WHERE, exactly:
--   analysis.address           identity + the summary of the screen + ONE set
--                              of provenance stamps
--   analysis.address_category  nearest_m / ratio per pair, plus the D57 demand
--                              annotation (which was analysis.address_demand,
--                              now dropped)
--   analysis.address_gaps      a VIEW: analysis.address joined to a pivot of
--                              analysis.address_category, in the old column
--                              order, so viz/webmap_export.py, the laundry
--                              views and the CLI queries are unchanged
--
-- THE SCREEN (D33/D38/D39/D41, gate retired 2026-09-13 by D75). Per
-- residential PLUTO lot (UnitsRes > 0): `gap_score` = max over categories of
-- nearest_m / reach_m is a CONTINUOUS ranking (D39), never a binary "exactly
-- one missing" list. `lead_category` / `lead_excess_m` name the worst
-- (max-ratio) category, ties going to the larger raw nearest_m (the more
-- conspicuous absence). `n_missing` counts categories with ratio > 1.
-- `units_capped` clips units at 500/lot for unit-weighted ranking (D39: Co-op
-- City-scale lots would otherwise dominate); raw `units` is kept beside it.
-- `cluster_id` groups gap_score > 1 addresses sharing a lead_category within
-- ~200 m (single-linkage, eps=200 m) -- the action signal is a CLUSTER missing
-- the same business, not one lot.
--
-- `eligible` IS RETIRED AND IS ALWAYS TRUE (D75, 2026-09-13, owner ruling).
-- Until then it was a FIXED, reach-independent walkability gate (>= 12 of 15
-- categories within 800 m, mirroring model/gaps.py's `_eligible_universe`),
-- and every summary column above was NULL/0 outside it. The owner's ruling:
-- "I 100% vehemently disagree with 'which addresses count at all'. If an
-- address is truly in a super underdeveloped area, this would completely not
-- count it." Every address is now in the universe; the column stays, always
-- TRUE, so that stored data, this DDL and every query written against the
-- pre-D75 shape keep working. It is NOT a filter any reader should apply, and
-- `WHERE eligible` in new code is a bug. The monotonicity D39 needed it for is
-- now trivial: with no gate, the gap set is `ratio > 1` read off each
-- address's own nearest_m against a fixed reach, so tightening a reach can
-- only ADD pairs. `present_count` survives as the descriptive count it always
-- was (categories within 800 m) and is a candidate RANKING feature; the
-- feasibility question the gate was reaching for lives in model/invest.py's
-- PLUTO CommFAR / RetailArea build-or-lease test, and nothing from the gate
-- was folded into it.
--
-- NO DEMOGRAPHICS HERE (D56). Join analysis.address_demographics on
-- address_id: it holds the lot's own census tract's ACS figures, taken
-- directly. The hex-interpolated copy sql/008 briefly put on address_gaps is
-- gone -- one address had two different median_hh_income values.
--
-- PROVENANCE lives on analysis.address and nowhere else: reach_source /
-- reach_hash (which reach table, D41), graph_version (which walk graph),
-- supply_set / supply_hash (which POIs counted as supply, D52) and run_at.
-- CAVEAT THE DATABASE CANNOT ENFORCE: because the provenance stamp sits on
-- analysis.address and address_category has no run key of its own, this pair
-- of tables holds exactly ONE run at a time. analysis.address_demand could
-- hold two supply sets side by side keyed by (reach_hash, supply_hash); this
-- shape cannot. The delete-then-insert in model/address_gaps.py is per
-- borough and rewrites BOTH tables together, so they cannot fall out of step
-- -- but comparing two supply sets now means snapshotting to parquet
-- (data/interim/) between runs, the way D59 did, not keeping both in the
-- warehouse.
CREATE TABLE IF NOT EXISTS analysis.address (
    address_id        VARCHAR NOT NULL,
    bbl               VARCHAR,
    lon               DOUBLE  NOT NULL,
    lat               DOUBLE  NOT NULL,
    units             REAL,
    units_capped      REAL,                -- clipped at 500/lot for unit-weighted ranking (D39)
    nta_code          VARCHAR,
    neighborhood      VARCHAR,
    borough           VARCHAR NOT NULL,
    h3_index          VARCHAR,             -- res-9 cell CONTAINING the lot: the borough/NTA
                                           -- join key and the roll-up-to-grid key. Geometry,
                                           -- not demography -- nothing demographic rides on it.
    present_count     SMALLINT NOT NULL,   -- categories within 800 m; DESCRIPTIVE since D75, not a gate
    eligible          BOOLEAN NOT NULL,    -- RETIRED D75 (2026-09-13): always TRUE; never filter on it
    gap_score         REAL,                -- max(nearest_m / reach_m); populated for every address (D75)
    lead_category     VARCHAR,             -- argmax ratio, ties -> larger nearest_m
    lead_excess_m     REAL,                -- nearest_m - reach_m at lead_category
    n_missing         SMALLINT NOT NULL,   -- count of categories with ratio > 1
    cluster_id        VARCHAR,             -- "{borough}:{lead_category}:{local_id}"; NULL unless gap_score > 1
    reach_source      VARCHAR NOT NULL CHECK (reach_source IN ('tiers', 'p80')),
    reach_hash        VARCHAR NOT NULL,
    graph_version     VARCHAR NOT NULL,
    supply_set        VARCHAR,             -- D52; NULL only on a pre-D52 row
    supply_hash       VARCHAR,
    run_at            TIMESTAMP NOT NULL,
    -- THE DEVELOPMENT-PIPELINE EXTENSION (sql/011_dev_pipeline.sql, model/
    -- dev_pipeline.py). Written ONLY by `UPDATE ... SET PIPELINE_COLUMNS`,
    -- never by the screen; a test pins that SET-list disjoint from the screen's
    -- own columns, exactly as address_demand.py's annotation is on
    -- address_category. Units are NETWORK-metre catchment sums over
    -- analysis.dev_pipeline (one row per DOB job); `pipeline_asof` is the run
    -- date the 24/60-month completion windows are measured back from, so a
    -- stale row is readable rather than silently re-interpreted. 011 carries
    -- the same twelve columns as ALTER ... ADD COLUMN IF NOT EXISTS for
    -- databases built before this landed; the two paths must stay in step.
    units_permitted_400m        INTEGER,
    units_permitted_800m        INTEGER,
    units_completed_24mo_400m   INTEGER,
    units_completed_24mo_800m   INTEGER,
    units_completed_60mo_400m   INTEGER,
    units_completed_60mo_800m   INTEGER,
    nearest_large_project_id    VARCHAR,   -- job_number of the nearest net_units >= 50 job
    nearest_large_project_m     REAL,      -- network metres, right-censored at DIST_LIMIT
    nearest_large_project_units INTEGER,
    nearest_large_project_stage VARCHAR,
    nearest_large_project_date  DATE,      -- its date_complete, else date_permitted, else date_filed
    pipeline_asof               DATE,
    PRIMARY KEY (borough, address_id)
);

-- One row per (address, category) -- 15 rows per address, every category,
-- present or missing. `nearest_m` is censored at the 30-minute network cap
-- (analysis.hex_poi_distance's convention) when nothing of that category is
-- reachable; `ratio` = nearest_m / reach_m is still finite there (cap / reach),
-- which is why the ranking is continuous and the censoring has to be read off
-- nearest_m, not inferred from a NULL.
--
-- THE DEMAND ANNOTATION (D49 at address grain, D57) lives in the second half of
-- this table rather than in a sibling. What that costs and how it is repaid:
-- D57 made analysis.address_demand a separate table precisely so that the
-- non-filtering guarantee was MECHANICAL -- model/address_demand.py had no
-- write path to the screen at all. Folding the columns in gives that up, so it
-- is replaced by two things that must both hold:
--   1. model/address_demand.py issues ONLY `UPDATE ... SET <annotation columns>`,
--      built from its DEMAND_ANNOTATION_COLUMNS constant. It never INSERTs,
--      never DELETEs, and never names nearest_m, ratio, is_lead or eligible.
--      A test asserts that constant is disjoint from the screen's own columns.
--   2. tests/test_address_demand.py still re-runs the D57 proof on real shape:
--      hash-sum checksums of gap_score, lead_category, n_missing, eligible,
--      nearest_m and ratio are byte-identical before and after the annotation.
-- The annotation may never change WHICH (address, category) pairs are gaps, or
-- their order (D48: the output is graded, never filtered). An annotation that
-- reorders leads has become a filter wearing a costume.
--
-- `is_lead`, `eligible` and `censored` are written by the SCREEN, not by the
-- annotation -- they are copies of analysis.address.lead_category = category,
-- analysis.address.eligible (retired D75, always TRUE) and the D75 censoring
-- flag, denormalised so a reader can slice the long table without a join. The
-- annotation reads them; it does not set them.
--
-- demand_class is DERIVED from spend.yaml's BLS CEX income elasticity at
-- demand.yaml's 0.35 cut (D49), never hand-coded; `elasticity` is the CEX
-- number the class came from, carried so a reader can see the derivation.
-- income_ratio is the address's TRACT median household income (from
-- analysis.address_demographics -- the least-modelled input) over the citywide
-- MEAN household income (B19025/B11001, Meltzer & Schuetz's own denominator).
-- income_indeterminate is a THIRD state and must never be folded into "not
-- low": that would resolve every uncertain case in the direction that keeps the
-- gap looking clean. demand_caveat fires only on the MOE-confident test
-- (income_ratio + income_ratio_moe < 0.80) AND a discretionary, annotatable
-- category; unknown MOE means no assertion. Clinic rows exist but can never be
-- caveated (D30: loci's clinic layer excludes doctors' offices and no source
-- reproduces that exclusion).
--
-- RENDERERS MUST NOT TRUNCATE demand_caveat_text. The QUESTIONS-X6 disclaimer
-- is the TAIL of the string, and it is the sentence that keeps the annotation
-- from laundering under-provision as absent demand (the same paper finds race
-- predicts retail NET of income). Clipping keeps the income claim and drops the
-- warning -- exactly backwards.
CREATE TABLE IF NOT EXISTS analysis.address_category (
    address_id           VARCHAR NOT NULL,
    borough              VARCHAR NOT NULL,
    category             VARCHAR NOT NULL,
    nearest_m            REAL,               -- censored at the 30-minute network cap; see `censored`
    ratio                REAL,               -- nearest_m / reach_m; > 1 means "missing" (D39)
    is_lead              BOOLEAN,            -- written by the screen: this is the address's lead_category
    eligible             BOOLEAN,            -- RETIRED D75: always TRUE; a copy of analysis.address.eligible
    -- ---- demand annotation, written ONLY by model/address_demand.py ----
    demand_class         VARCHAR CHECK (demand_class IS NULL
                                        OR demand_class IN ('necessity', 'discretionary')),
    elasticity           REAL,               -- spend.yaml BLS CEX income elasticity
    income_ratio         REAL,               -- tract median hh income / citywide MEAN
    income_ratio_moe     REAL,               -- NULL when the ACS MOE is unknown
    income_indeterminate BOOLEAN,            -- cutoff within one MOE; do not read the class alone
    demand_caveat        BOOLEAN,            -- the MOE-confident test; never a filter
    demand_caveat_text   VARCHAR,            -- render UNTRUNCATED (X6 disclaimer is the tail)
    acs_year             SMALLINT,           -- vintage of the income the annotation used
    PRIMARY KEY (borough, address_id, category)
);

-- analysis.address_gaps is a VIEW over the two tables above, created by
-- model/address_gaps.address_gaps_view_sql() and applied by db.init_schema()
-- after every .sql migration. It is NOT defined here because its 30 pivoted
-- columns are GENERATED from categories.yaml -- writing them out by hand is
-- exactly the drift this refactor removes.

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
--
-- CONSIDERED AND REJECTED (2026-09-09, owner consolidation pass): replacing
-- this table with a VIEW that sums analysis.zip_coverage_by_source's
-- poi_count per (year, zipcode, category). Measured on the live database:
-- zip_coverage_by_source is built by INNER-joining onto the canonical POI
-- layer (model/zbp_compare._poi_counts_by_zip_category_source), so a
-- (zipcode, category) with ZERO canonical POIs has NO source rows to sum --
-- it would not appear in the view at all, not appear with poi_count=0. Of
-- this table's 2,034 rows, 12 have poi_count = 0: exactly the "Census counts
-- establishments here, Loci found none" rows -- arguably the single
-- strongest undercoverage signal the whole comparison exists to surface.
-- Collapsing to a view would silently drop them, which is the "never ingest
-- a silent zero" failure mode CLAUDE.md warns about, not a refactor. This
-- table stays a base table, built directly by build_coverage_check (LEFT
-- JOIN against the POI side, poi_count defaulting to 0), independently of
-- whether analysis.zip_coverage_by_source is also built.
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

-- Address-level ACS demographics (D38/D56): under D38 the unit of analysis
-- is the residential address, not the hex, so the demographic carrier for
-- the address screen must also be address-grained. This table REPLACES
-- analysis.hex_demographics as that carrier -- hex_demographics is FROZEN
-- HISTORY (D38: no new features read from hex_* tables) and is left as-is
-- for anything that still needs the old hex-level panel.
--
-- One row per address_id (the universe sources/cities/nyc/addresses.py
-- writes, unioned across all five boroughs -- 767,337 residential PLUTO
-- lots as of 2026-09-09), keyed by (address_id, acs_year). Unlike
-- hex_demographics, these values are NOT apportioned: a PLUTO tax lot sits
-- in exactly one 2020 census tract (tract_geoid), so every field below is
-- that tract's own ACS 2023 5-year E/M cell, taken directly. Tract
-- assignment is a BBL lookup against PLUTO's own `bct2020` column, not a
-- spatial join -- see model/address_demographics.py's module docstring for
-- the coverage measurement (99.9992% of addresses get a tract; the rest get
-- NULL demographics here, never dropped from the table).
-- median_hh_income (B19013), renter_share (B25003, ACS-handbook proportion
-- MOE via grid/acs.py's `_moe_proportion`), zero_vehicle_hh_share (B08201,
-- the primary vehicle-ownership measure), and zero_vehicle_owner_share /
-- zero_vehicle_renter_share (B25044, tenure-split cross-check) all carry
-- their MOE, per CONTEXT.md's rule that ACS margins of error are propagated,
-- never discarded. population/households (B01003/B11001) are carried for
-- reference alongside their MOEs.
--
-- CAVEAT the schema cannot enforce: population/households are the tract's
-- FULL count, repeated on every address in that tract (a lookup, not an
-- apportionment) -- summing them across addresses is an N-times overcount.
-- Rates (median_hh_income, renter_share, zero_vehicle_*_share) are safe to
-- read per-address since they are the tract's rate/median verbatim. For an
-- apportioned population total at some aggregate, use
-- analysis.hex_demographics instead.
CREATE TABLE IF NOT EXISTS analysis.address_demographics (
    address_id                    VARCHAR NOT NULL,
    bbl                            VARCHAR,
    tract_geoid                   VARCHAR,    -- 2020 census tract GEOID; NULL if unassigned
    acs_year                      SMALLINT NOT NULL,
    population                    FLOAT, population_moe                FLOAT,
    households                    FLOAT, households_moe                FLOAT,
    median_hh_income               FLOAT, median_hh_income_moe          FLOAT,
    renter_share                  FLOAT, renter_share_moe               FLOAT,
    zero_vehicle_hh_share          FLOAT, zero_vehicle_hh_share_moe      FLOAT,
    zero_vehicle_owner_share       FLOAT, zero_vehicle_owner_share_moe   FLOAT,
    zero_vehicle_renter_share      FLOAT, zero_vehicle_renter_share_moe  FLOAT,
    PRIMARY KEY (address_id, acs_year)
);

-- ==========================================================================
-- GTM-110 region (address-level demand annotation). Appended by the GTM-110
-- session; keep edits inside this delimited block.
-- ==========================================================================

-- SUPERSEDED 2026-09-09 (D58, folded into the address/address_category split
-- above). analysis.address_demand was a SIBLING table, keyed by
-- (address_id, category, reach_hash, supply_hash), that D57 built precisely
-- so the non-filtering guarantee was MECHANICAL: model/address_demand.py had
-- no write path to the screen at all. That guarantee is now enforced a
-- different way -- the demand annotation columns (demand_class, elasticity,
-- income_ratio, income_ratio_moe, income_indeterminate, demand_caveat,
-- demand_caveat_text, acs_year) live directly on analysis.address_category
-- (see its own header above), and model/address_demand.py is restricted by
-- CODE, not by table boundary, to issuing UPDATE ... SET <those columns
-- only> -- it never INSERTs, never DELETEs, and never names
-- nearest_m/ratio/is_lead/eligible (DEMAND_ANNOTATION_COLUMNS in
-- model/address_demand.py, and a test asserting it is disjoint from the
-- screen's own columns). A sibling table could hold two supply sets side by
-- side keyed by (reach_hash, supply_hash); folding the columns in gives that
-- up -- comparing two supply sets now means snapshotting to parquet between
-- runs, same as analysis.address/address_category already require, not
-- keeping both in the warehouse. sql/009_retire_split_tables.sql drops the
-- physical table from any database built before this change.


-- ==========================================================================
-- DEVELOPMENT-PIPELINE COLUMNS on analysis.address (sql/011_dev_pipeline.sql,
-- model/dev_pipeline.py). Idempotent, and they MUST run here rather than in
-- 011: db.init_schema() creates the generated VIEW analysis.address_gaps
-- immediately after this file, and that view names these columns. On a
-- database built before they existed, the CREATE TABLE IF NOT EXISTS above is
-- a no-op, so without these ALTERs the view would bind against a table that
-- has no such columns and every connection would raise. The CREATE above
-- carries the same twelve columns for a fresh database; the two must stay in
-- step, and tests/test_dev_pipeline.py pins that.
-- ==========================================================================
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS units_permitted_400m       INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS units_permitted_800m       INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS units_completed_24mo_400m  INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS units_completed_24mo_800m  INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS units_completed_60mo_400m  INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS units_completed_60mo_800m  INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_large_project_id    VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_large_project_m     REAL;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_large_project_units INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_large_project_stage VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_large_project_date  DATE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS pipeline_asof               DATE;


-- ==========================================================================
-- AGE-FIT COLUMNS (D63, 2026-09-10; model/age_fit.py, docs/bar_age_nyc.md).
-- `age_fit_bar` is a SUPPLY-REVEALED age multiplier for the `bar` category,
-- estimated from New York's own licensed-venue composition rather than from a
-- national household budget survey (the BLS CEX predecessor in
-- docs/age_demand_fit.md was rejected for `bar`: its alcohol line peaks at
-- reference-person age 45-54 and would have scored the UES ABOVE the East
-- Village). It is a SECOND ranking column that lives BESIDE gap_score, never a
-- gate: age_fit is exp(.) of a linear form in two ACS age shares and therefore
-- strictly positive, so gap_score_fit = gap_score * age_fit_lead is monotone in
-- gap_score at fixed address. It can reorder; it cannot filter.
--
-- Written ONLY by `UPDATE ... SET AGE_FIT_COLUMNS` (address_category) and
-- `UPDATE ... SET ADDRESS_AGE_FIT_COLUMNS` (address); both SET lists are
-- asserted disjoint from the screen's own columns in code and pinned by
-- tests/test_age_fit.py -- the same mechanical guarantee the D57 demand
-- annotation and the D62 pipeline annotation carry.
--
-- NULL vs 1.0 is a real distinction and must not be collapsed. age_fit is NULL
-- on every category except `bar` because no curve exists for them; a 1.0 would
-- claim a curve that says "neutral". age_fit_lead IS 1.0 (the identity
-- multiplier, so gap_score_fit == gap_score exactly) when the address's lead
-- category has no fitted curve -- there the MOE is NULL, because "no curve" is
-- not "a curve with no uncertainty".
--
-- These ALTERs must run HERE rather than in a later migration: db.init_schema()
-- creates the generated VIEW analysis.address_gaps immediately after this file
-- and that view names age_fit_lead / age_fit_lead_moe / gap_score_fit, so on a
-- database built before they existed the view would bind against columns that
-- do not exist and every connection would raise (the same class of bug as D61
-- and D62).
--
-- CAVEAT the database cannot enforce: age_fit is supply-revealed, so it is a
-- statement about where the New York market has historically put bar-type
-- licences relative to resident age -- demand and residential sorting together.
-- A low value is NEVER evidence a neighbourhood does not want the service (the
-- D49/X6 hazard), and resident age here is a proxy for a bundle (young, renter,
-- transit-rich, commercially active) that adds ~0% out-of-sample once those are
-- measured directly. model/age_fit.AGE_FIT_DISCLAIMER carries the sentences;
-- render them untruncated, exactly as demand_caveat_text.
-- ==========================================================================
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS age_fit         REAL;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS age_fit_moe     REAL;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS age_fit_source  VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS age_fit_lead     REAL;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS age_fit_lead_moe REAL;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS gap_score_fit    REAL;


-- ==========================================================================
-- STOREFRONT VACANCY (2026-09-10; sql/012_storefront_registry.sql,
-- model/storefronts.py). Seven address-grain columns from the NYC DOF
-- Storefront Registry (Local Law 157, Socrata 92iy-9c3n), written ONLY by
-- `UPDATE ... SET` from model/storefronts.STOREFRONT_COLUMNS.
--
-- They live HERE and not in 012 for the reason D62's twelve pipeline columns
-- do: db.init_schema() creates the generated VIEW analysis.address_gaps
-- immediately after 002 and before 003..012, and DuckDB resolves a view's
-- query at CREATE time. On a database built before this landed,
-- analysis.address already exists so 002's CREATE TABLE IF NOT EXISTS is a
-- no-op; a column added in 012 would not exist when the view naming it is
-- created, and every connection would raise BinderException. ONE file stays
-- responsible for the shape of analysis.address.
--
-- CAVEATS THE SCHEMA CANNOT ENFORCE (full list in sql/012's header):
--   * `vacant_storefronts_400m` is a SUBSET of `storefronts_400m`. Never add
--     them; the pair is a rate, and a rate over a tiny denominator is not one.
--   * The registry is SELF-REPORTED and non-filing is invisible, so 0 vacant
--     within 400 m and "nobody near here filed" are the same observation --
--     `storefronts_400m` is what tells them apart.
--   * `storefront_asof` is an ANNUAL observation date (default 2024-12-31),
--     not a live listing. There is no rent and no square footage anywhere in
--     the source.
--   * `nearest_vacant_lease_expired` is NULL when no lease was reported --
--     never FALSE -- and DOF stopped publishing the lease field on the annual
--     file after the 2024-06-03 release, so it is mostly NULL on the default
--     snapshot.
-- ==========================================================================
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS vacant_storefronts_400m            INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS storefronts_400m                   INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_vacant_storefront_m        DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_vacant_storefront_id       VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_vacant_storefront_business VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS nearest_vacant_lease_expired       BOOLEAN;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS storefront_asof                    DATE;


-- ==========================================================================
-- UNDER-5 SHARE (D65, 2026-09-10; grid/acs.py SHARE_SPECS, GTM-134 follow-up).
-- B01001_003E/M (male, under 5) + B01001_027E/M (female, under 5) over
-- B01001_001 (the same table's own total population), estimates summed and
-- MOEs root-sum-squared within the tract, then the ACS handbook derived-
-- proportion MOE -- identical arithmetic to every other SHARE_SPECS column,
-- because it IS driven by the same dict.
--
-- Why now: D64 fitted the childcare age curve with under-5 as a robustness
-- regressor computed ad hoc from the raw ACS cache. It entered at +0.783 and
-- pushed b(under_18_share) more negative (Brooklyn -0.975, contrast ratio
-- 0.708 [0.513, 0.978]) -- under-5s raise childcare composition, 5-17s lower
-- it, and the net under-18 coefficient hides that. A regressor that changes
-- the reading of the gate cannot live in a scratch script.
--
-- No new Census API call was needed: B01001_003E/M and _027E/M are ALREADY in
-- GETVARS (they are members of the under_18 age band), so data/raw/acs/
-- tracts_2023.json is unchanged and still valid. Adding this column does not
-- move the cache's `vars` fingerprint.
--
-- CAVEAT THE SCHEMA CANNOT ENFORCE: under_5_share is a STRICT SUBSET of
-- under_18_share (cells 003/027 are inside the under_18 band 003-006 +
-- 027-030). The four age-share columns do NOT partition the population and
-- must never be summed. "5 to 17" is under_18_share - under_5_share, and its
-- MOE is NOT the difference of the two MOEs.
--
-- Appended rather than grouped with the other age columns because ALTER can
-- only append and the ordered drift test compares physical ordinal position
-- against grid/acs.py's SHARE_SPECS order.
--
-- THE ADDRESS TWIN IS NOT HERE. analysis.address_demographics' D60 measure
-- columns are added by sql/008_address_demographics.sql, which db.init_schema
-- applies AFTER this file. Adding the address twin here would place it at
-- ordinal position 17-18 -- ahead of median_age and every share -- on a
-- freshly built database, while ADDRESS_DEMOGRAPHICS_COLUMNS puts it last;
-- tests/test_address_demographics.py compares those two by ordinal position,
-- so the twin ALTER lives at the END of 008. Both tables' columns still come
-- from the one SHARE_SPECS entry.
-- ==========================================================================
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS under_5_share     FLOAT;
ALTER TABLE analysis.hex_demographics ADD COLUMN IF NOT EXISTS under_5_share_moe FLOAT;


-- ==========================================================================
-- CONSTRUCTION-PROGRESS EXPOSURE on analysis.address
-- (sql/014_dev_pipeline_activity.sql, sources/cities/nyc/dob_permits.py,
--  model/dev_pipeline.PIPELINE_COLUMNS). D62 caveats 3 and 9.
--
-- `units_permitted_400m` counts every permitted-not-occupied unit within a
-- 5-minute network walk. D62 caveat 3 then says 23% of permitted units
-- citywide are behind permits older than five years that never produced a CO,
-- so that one number silently mixes "800 neighbours arriving in 18 months"
-- with "800 neighbours who have not arrived since 2017". These two split it by
-- the permit-renewal record:
--   units_active_400m   permitted-not-complete AND activity_status='active'
--   units_stalled_400m  permitted-not-complete AND activity_status='stalled'
--
-- NOT A PARTITION. active + stalled <= permitted, always -- `lapsed` (expired
-- 0-12 months) and `n/a` (no permit evidence) units are in the permitted total
-- and in neither column. Never add the three; the remainder is the unclassified
-- share and it is a real quantity, not a rounding error.
--
-- NULL, NOT ZERO, when the evidence is missing. Until `loci pipeline-activity`
-- has run, analysis.dev_pipeline.activity_status is NULL on every row and
-- model/dev_pipeline.py writes NULL into both columns rather than 0 -- "no
-- permit evidence yet" and "every nearby building is abandoned" must not be
-- the same value on the screen.
--
-- Added here rather than in 014 for 011's reason: db.init_schema() rebuilds
-- the generated VIEW analysis.address_gaps immediately after this file, DuckDB
-- resolves a view's query at CREATE time, and on an existing database
-- CREATE TABLE IF NOT EXISTS analysis.address is a no-op -- so a column added
-- at 014 would not exist when the view naming it is created, and every
-- connection would fail with a BinderException.
-- ==========================================================================
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS units_active_400m  INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS units_stalled_400m INTEGER;


-- ==========================================================================
-- SUPPLY INTENSITY (model/supply_ratio.py, 2026-09-11 red-team findings 1-3).
--
-- "Is there a gap" is a statement about the NEAREST business. It is silent
-- about a category that is PRESENT but THIN -- one pharmacy 380 m away clears
-- the reach test and stops being a gap, while the same walk in Park Slope
-- passes eight. These columns measure the other thing: how much supply is
-- within a 5-minute walk PER 1,000 HOMES within the same walk, and how that
-- compares with the MN+BK norm.
--
-- SPLIT ACROSS TWO TABLES ON PURPOSE (D61).
--   analysis.address           homes_400m, addressable_homes_400m_laundry
--                              + the run stamps. CATEGORY-INDEPENDENT: the
--                              same homes are within 400 m whether the
--                              question is pharmacies or bars. Putting them on
--                              address_category would write fifteen identical
--                              copies -- 11.5M rows to say 767k things, the
--                              pivot-shaped duplication D61 removed. Same
--                              reasoning that put storefronts_400m and
--                              units_permitted_400m here.
--   analysis.address_category  supply_400m, supply_per_1k,
--                              supply_ratio_vs_base. Genuinely per category.
--
-- COUNTS COME FROM THE PRINCIPLED SET, ALWAYS (red-team finding 1).
-- analysis.poi_supply WHERE in_principled, never in_all -- the two differ by
-- more than 2x in bar, nails_beauty and laundry. analysis.poi_supply is a
-- VIEW, so the set moves when dedup is re-run or an anchor lands; that is why
-- supply_ratio_supply_hash is stamped on every row and why the baseline YAML
-- carries the hash it was fitted on. A ratio and a baseline from different
-- hashes are not comparable.
--
-- NULL IS NOT ZERO, in three places:
--   * supply_per_1k and supply_ratio_vs_base are NULL where homes_400m = 0.
--     A block of warehouses with no pharmacy is a block with no denominator,
--     not an under-served block.
--   * supply_ratio_vs_base is NULL for a category whose baseline is 0 or
--     absent from the YAML. 0/0 is not 1.0.
--   * every column is NULL until `loci supply-ratio` has run for the borough.
--
-- addressable_homes_400m_laundry IS A SUBSET of homes_400m and is DOUBLE, not
-- integer: it is homes_400m less a per-building haircut for in-unit and
-- in-building laundry (model/laundry_haircut.yaml; NYCHVS 2023 for the 1- and
-- 2-unit shares, owner-adjustable priors above that, and a positive
-- analysis.address_laundry_evidence assertion overriding the prior to 1.0).
-- Never add it to homes_400m, and never quote homes_400m as laundry demand:
-- 59% of the homes near a laundry-lead gap address sit in 51+-unit buildings.
--
-- NON-FILTERING (D48). Nothing here can move gap_score, lead_category,
-- n_missing, eligible, ratio or nearest_m; model/supply_ratio.py issues UPDATE
-- only on these column lists and tests/test_supply_ratio.py pins them disjoint
-- from every other module's.
--
-- Added at the TAIL of 002 for 011/014's reason: db.init_schema() rebuilds the
-- generated VIEW analysis.address_gaps immediately after this file and DuckDB
-- resolves a view's query at CREATE time, so a column added in a later
-- migration would not exist when the view naming it is created and every
-- connection would fail with a BinderException.
-- ==========================================================================
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS homes_400m                     BIGINT;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS addressable_homes_400m_laundry DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS supply_ratio_radius_m          DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS supply_ratio_supply_hash       VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS supply_ratio_run_at            TIMESTAMP;

ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS supply_400m          BIGINT;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS supply_per_1k        DOUBLE;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS supply_ratio_vs_base DOUBLE;

-- ==========================================================================
-- D75 (2026-09-13) -- THE RIGHT-CENSORING FLAGS.
--
-- `nearest_m` is the output of a walk-network Dijkstra run with
-- `limit = score/access.DIST_LIMIT` (2,400 m, a 30-minute walk). A category
-- with NOTHING inside that limit is recorded AT the limit. So a stored
-- nearest_m of 2,400 has two readings that the number alone cannot separate:
-- "the nearest one is 2,400 m away" and "there isn't one within 2,400 m, and
-- nobody measured how much further it is". The second is the common case.
--
-- D51 found this and noted the derived ceiling it puts on gap_score
-- (max attainable ratio = 2400 / reach, so a max-ratio ranking partly sorts
-- the reach table). The eligibility gate was accidentally hiding most of it:
-- an address with several unreachable categories usually failed
-- `present_count >= 12` and was dropped. D75 retired the gate, so the
-- artifact is now fully exposed and has to be handled in the open.
--
-- THE HANDLING IS A FLAG, NOT A RULE. `gap_score` is unchanged and `cap_m` is
-- unchanged. A censored ratio is still the SMALLEST value that ratio could
-- take, so leaving it in the score keeps the ranking monotone, continuous and
-- conservative -- inventing an extrapolated distance would be a new model
-- nobody has calibrated, and dropping the pair would re-introduce a gate by
-- the back door. Instead the fact travels with the number:
--
--   analysis.address_category.censored  TRUE iff nearest_m >= 2,400 -- this
--       pair's nearest_m and ratio are FLOORS, not measurements.
--   analysis.address.lead_censored      TRUE iff the LEAD category is
--       censored -- i.e. this address's gap_score is a floor. This is the one
--       a ranking, a recommendation card or a map popup must read: the honest
--       rendering is "nearest X beyond 2,400 m -- distance not measured",
--       never "2,400 m".
--
-- Both are written by the SCREEN (model/address_gaps.py's
-- ADDRESS_COLUMNS / ADDRESS_CATEGORY_SCREEN_COLUMNS) and by nothing else, so
-- they are covered by the same disjointness tests as every other screen
-- column. Both are surfaced on the generated view analysis.address_gaps
-- (`lead_censored` plus the fifteen `{cat}_censored`).
--
-- Added at the TAIL of 002 for the same reason as the supply-intensity block
-- above: db.init_schema() rebuilds the generated VIEW analysis.address_gaps
-- immediately after this file, and DuckDB resolves a view's query at CREATE
-- time, so a column added in a later migration would not exist when the view
-- naming it is created.
-- ==========================================================================
ALTER TABLE analysis.address          ADD COLUMN IF NOT EXISTS lead_censored BOOLEAN;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS censored      BOOLEAN;

-- ==========================================================================
-- SITE-REVENUE MODEL v0 (2026-09-13) -- what a typical new store could take.
--
-- WHY THESE COLUMNS AND NOT A NEW TABLE. Revenue varies by category, so the
-- three percentiles, the rent ceiling and the model version extend
-- analysis.address_category (per-category grain). `homes_800m` does NOT vary
-- by category -- the same homes are within 800 m whether the question is bars
-- or pharmacies -- so it extends analysis.address, exactly as homes_400m,
-- storefronts_400m and units_permitted_400m do, and for the same D61 reason:
-- putting it on address_category would write fifteen identical copies of one
-- number.
--
-- WHAT THE NUMBERS ARE. revenue_p50 = lambda_c * homes_400m * annual CEX spend
-- per household for the address's income quintile * a Huff capture share
-- against the principled incumbents within 800 m network metres. lambda_c is
-- fitted per COUNTY so that the mean prediction over that county's existing
-- establishments equals the Economic Census mean revenue per establishment, so
-- the LEVEL is calibrated by construction and only the cross-sectional
-- variation is a claim. Full equations: src/loci/model/revenue.py's docstring.
--
-- WHAT p25/p75 ARE NOT. They are a PARAMETER band (lambda disagreement between
-- the two counties, the tract income MOE moving the address across a quintile
-- boundary, and the spread of the leave-one-ZIP-out beta refits). They say
-- nothing about how far a real store's takings sit from the model -- that
-- dispersion needs P&Ls and is exactly why the recommendation card caps this
-- evidence at grade C.
--
-- NULL MEANS NOT MODELLED. A category that failed the out-of-sample gate
-- (`gate: fail` in src/loci/model/revenue_calibration.yaml) is left NULL on
-- purpose and keeps grade D. NULL is never a revenue of zero.
--
-- Written ONLY by model/revenue.py's CATEGORY_REVENUE_COLUMNS /
-- ADDRESS_REVENUE_COLUMNS, by UPDATE, with the SET lists pinned disjoint from
-- the screen, demand, pipeline, storefront, age-fit and supply-ratio columns by
-- tests/test_revenue.py. Re-apply: `uv run loci revenue --boroughs MN,BK`,
-- AFTER `loci supply-ratio` in the canonical order.
--
-- At the TAIL of 002 for the same reason as the two blocks above: db.init_schema()
-- rebuilds the generated VIEW analysis.address_gaps immediately after this file.
-- ==========================================================================
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS homes_800m BIGINT;

ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS revenue_p25           DOUBLE;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS revenue_p50           DOUBLE;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS revenue_p75           DOUBLE;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS rent_ceiling          DOUBLE;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS revenue_model_version VARCHAR;

-- ==========================================================================
-- THE WALK-SHED DENSITY EXTENSION (model/supply_ratio.py; owner ruling
-- 2026-09-13, "rank by density"). Two more category-INDEPENDENT columns on
-- analysis.address, written by the SAME sweep and the SAME Dijkstra rows that
-- produce homes_400m, so numerator and denominator can never be measured over
-- different reachable sets.
--
--   walkshed_km2_400m  area of the convex hull of the graph nodes within 400 m
--                      NETWORK metres of the address's own node, in km2,
--                      projected in EPSG:32618 and floored at 0.00785 km2
--                      (a 50 m disc) so a degenerate two-node hull cannot
--                      produce an infinite density.
--   density_400m       homes_400m / walkshed_km2_400m -- residential UNITS per
--                      km2 of reachable walk.
--
-- NOT pi*0.4^2. A nominal disc is a constant, and dividing by a constant ranks
-- by homes_400m under another name; the measured shed is under half the
-- nominal disc at the median and the difference IS the permeability signal.
-- Convex and not concave because a concave hull needs an alpha knob that
-- silently moves every area, and because the convex hull's error runs the
-- conservative way: it spans holes (water, parks, rail cuts), overstating the
-- shed and understating the density.
--
-- MOE-FREE, AND NOT A HOUSEHOLD DENSITY. The numerator is PLUTO UnitsRes, a
-- register count with no margin of error to propagate and no occupancy
-- adjustment. It must never be compared like-for-like with an ACS households
-- per km2, which is a survey estimate that does carry one.
--
-- NON-FILTERING, exactly as the rest of the supply-ratio block: written by
-- UPDATE only, on ADDRESS_RATIO_COLUMNS, and pinned disjoint from the screen's
-- own columns by tests/test_supply_ratio.py. Nothing here moves gap_score,
-- lead_category, n_missing, ratio or nearest_m; it changes the ORDER clusters
-- are listed in, never which addresses are in the gap set.
--
-- At the TAIL of 002 for the same reason as every block above it.
-- ==========================================================================
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS walkshed_km2_400m DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS density_400m      DOUBLE;
