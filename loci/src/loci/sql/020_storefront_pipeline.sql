-- ---------------------------------------------------------------------------
-- 020_storefront_pipeline.sql -- analysis.storefront_pipeline: one row per
-- BUSINESS ATTEMPTING TO OPEN AT A LOT, rolled up from the filing event log.
--
-- Stage two of the owner's 2026-09-13 ask ("find when stores go live via
-- government filings -- not just for chains"). Stage one built the event log,
-- staging.storefront_filing (sql/019): 232,667 dated regulatory events across
-- seven feeds. This is the roll-up sql/019's own header promised --
--
--     "Stage two's analysis.storefront_pipeline (bbl x business_name_key) is
--      a ROLL-UP of this and must be a view or a derived table over it --
--      never a second copy of the events."
--
-- -- and it is a derived TABLE rather than a view for one reason: the
-- cross-agency reconciliation (below) is a greedy one-to-one matching that
-- SQL cannot express as a view, and re-running it inside every query would
-- make two reads of the same "view" disagree. The table is fully derived,
-- rebuilt by one DELETE + INSERT, and carries no fact that is not recomputable
-- from staging.storefront_filing plus model/filing_categories.yaml.
--
-- ---------------------------------------------------------------------------
-- THE GRAIN, AND THE TWO D75 CARRY RULES
-- ---------------------------------------------------------------------------
-- Nominally (bbl, business_name_key): one business, one lot, every filing it
-- made on the way to opening. But 13,470 DCWP applications have no BBL and
-- 2,463 filings have no usable name key, and the owner's standing ruling (D75,
-- no eligibility gate) is that such rows are CARRIED WITH A FLAG, never
-- dropped. So:
--
--   group_kind = 'bbl_name'   both keys present. The real grain.
--   group_kind = 'filing'     either key is NULL. The group is the SINGLE
--                             FILING, and `bbl_missing` / `name_key_missing`
--                             say which key was absent.
--
-- WHY A NULL-BBL ROW IS NOT GROUPED BY NAME ALONE. "joes pizza" is a hundred
-- different businesses in New York. model/storefront_filing.lead_times()
-- already refuses a citywide name join for exactly this reason -- it would
-- pair a Bronx application with a Brooklyn inspection and call the difference
-- a lead time. Collapsing NULL-BBL rows on the name key would do the same
-- thing one step earlier and would also fuse distinct storefronts, the bug
-- score/dedup.py's comments are about. One filing, one row, flagged.
--
-- WHY A NULL-NAME-KEY ROW IS NOT GROUPED BY BBL ALONE. A mixed-use lot has
-- many storefronts. Grouping every unnamed filing on 3004710200 together would
-- fuse the laundromat, the deli and the nail salon into one "business" with an
-- eleven-year lifecycle. One filing, one row, flagged.
--
-- Both flags are therefore an ADMISSION OF IGNORANCE, not a category: a
-- `filing`-kind row is a lifecycle we could not assemble, and counting it as a
-- distinct business over-counts the pipeline. `loci storefront-pipeline stats`
-- prints the split so the over-count is always in view.
--
-- ---------------------------------------------------------------------------
-- furthest_stage: A STRING, COMPUTED FROM A RANK, NEVER A STORED RANK
-- ---------------------------------------------------------------------------
-- filing_stages.py caveat 3: `outdoor_dining` is declared and not yet
-- ingested, and inserting a stage in the MIDDLE later would renumber every
-- stored rank. So the rank is materialised at BUILD time from
-- filing_stages.STAGES (model/storefront_pipeline.stage_rank_sql() emits a
-- VALUES join) and only the STAGE STRING is stored. Nothing in this table is
-- an integer position in a vocabulary that can change.
--
-- `furthest_stage` is max(RANK), not max(date): the lifecycle question is how
-- far along the business got, and a sign permit issued after the first
-- inspection does not un-open the door. `furthest_date` is that stage's own
-- earliest date, so the pair is always internally consistent.
--
-- ---------------------------------------------------------------------------
-- is_open / opened_on -- AND THE ONE THING THAT COULD MAKE THEM LIE
-- ---------------------------------------------------------------------------
-- `is_open` is true when the row has a `first_inspection`, a `license_issued`
-- or a `liquor_active` filing: three different regulators having seen a
-- business that exists. `opened_on` is the earliest of those, and
-- `opened_on_stage` names which one produced it.
--
-- THE CAVEAT, and it is the reason `opened_on_stage` is stored at all:
-- `liquor_active.filed_on` is SLA's `originalissuedate`, which for a RENEWED
-- licence is the date the FIRST licence issued at that premises -- possibly
-- decades ago. filing_stages.OPEN_STAGES deliberately excludes liquor_active
-- for this reason. It is included HERE, at the owner's instruction, and it is
-- safe today only because sources/cities/nyc/filing_feeds.fetch_sla_active
-- WINDOWS the fetch on `originalissuedate >= asof - 24 months`: every
-- liquor_active row in the table was originally issued inside the window, so
-- no decades-old renewal is present (measured: min(filed_on) = 2024-09-13).
-- WIDEN THAT WINDOW AND THIS COLUMN STARTS LYING. Any consumer that needs the
-- conservative reading filters `opened_on_stage <> 'liquor_active'`, and the
-- ledger writer (model/storefront_pipeline.apply_gov_filing) refuses a
-- liquor_active-derived date that predates the row's own earliest filing.
--
-- `lead_days` is NULL, never 0, when `entry_stage` is already a terminal
-- stage. A restaurant whose first appearance in the table is its DOHMH
-- inspection has no measured lead time; zero would be a claim that it opened
-- the day it filed.
--
-- ---------------------------------------------------------------------------
-- THE RECONCILIATION COLUMNS (link_*)
-- ---------------------------------------------------------------------------
-- The lead-time N is small -- 73 fitout->inspection pairs out of 67,220 fitout
-- filings -- because the same store files under DIFFERENT NAMES at different
-- agencies: 11,813 BBLs carry both an early and a terminal stage under name
-- keys that do not match. The link pass (model/storefront_pipeline.reconcile)
-- pairs an unopened early row with an opened row ON THE SAME BBL when their
-- dates are within LINK_WINDOW_DAYS and either
--
--   (a) their name keys share a RARE token (document idf over the whole name
--       vocabulary >= RARE_TOKEN_MIN_IDF), or
--   (b) the BBL has EXACTLY ONE early and EXACTLY ONE terminal candidate in
--       the window -- no ambiguity to resolve.
--
-- It is ONE-TO-ONE by construction, greedy on the shortest gap. A many-to-many
-- link would multiply a single build-out into several lead times and inflate
-- every median; a fused pair would manufacture a storefront that never
-- existed. Both failures are the double-count/merge bugs this project has
-- already been bitten by, so `link_partner_id` is unique on both sides and
-- tests/test_storefront_pipeline.py pins it.
--
-- THE RECONCILED NUMBERS ARE NOT THE REFERENCE. `link_method` is stored on
-- every linked row so a reader can drop back to the strict (same-name-key)
-- population at any time, and `loci storefront-pipeline stats` prints strict
-- and reconciled side by side, never pooled. A link is an inference; a shared
-- name key is an observation.
--
-- ---------------------------------------------------------------------------
-- WHY THIS IS ONE TABLE AND TWO VIEWS (D61 inventory rule)
-- ---------------------------------------------------------------------------
-- `duckdb_tables()` before writing this file: staging.{poi, listings,
-- listings_fetch_log, ll84_laundry, alcohol_licences, storefront_filing,
-- poi_*_pending}, analysis.{address, address_category, address_demographics,
-- address_entrance, address_laundry_evidence, address_transit_profile,
-- category_anchor, coverage_validation, dev_pipeline, hex*, poi_dedup,
-- poi_presence, storefront, zip_*}, chains.{brand_location, brand_snapshot,
-- press_hits}.
--
-- Nothing holds a BUSINESS LIFECYCLE. staging.storefront_filing holds events;
-- analysis.dev_pipeline is DOB jobs with RESIDENTIAL units; analysis.storefront
-- is the SPACE (a ground floor, occupied or not); analysis.poi_presence is a
-- deduped location Loci OBSERVED, always after the fact. The grain here --
-- (lot, business) with a start, a furthest point and maybe an opening -- is
-- new and is not a pivot of any of them.
--
-- The two views ARE pivots and are therefore views, per the rule:
--   analysis.storefront_pipeline_census   stage x open-state counts
--   analysis.storefront_pipeline_lead     the reconciled lead-time pair list
--
-- The address measures (`openings_pipeline_400m`, `openings_recent_400m`) are
-- new MEASURES at an existing grain, so they extend analysis.address_category
-- by ALTER, exactly as supply_400m does -- no third table.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS analysis.storefront_pipeline (
    pipeline_id         VARCHAR NOT NULL,   -- 'bbl:<bbl>|name:<key>' | 'filing:<filing_id>'
    group_kind          VARCHAR NOT NULL CHECK (group_kind IN ('bbl_name', 'filing')),
    bbl                 VARCHAR,            -- NULL is carried, never dropped (D75)
    business_name_key   VARCHAR,            -- chains.normalize.brand_key; NULL carried
    business_name       VARCHAR,            -- most common raw spelling in the group
    borough             VARCHAR,            -- MN|BX|BK|QN|SI
    lon                 DOUBLE,             -- representative point,
    lat                 DOUBLE,             --   EPSG:4326 by convention (no SRID)
    geom                GEOMETRY,
    point_source        VARCHAR CHECK (point_source IS NULL OR point_source IN (
                            'filing', 'pluto_lot')),
    entry_stage         VARCHAR,            -- stage of the EARLIEST filing
    entry_date          DATE,               -- min(filed_on) over the group
    furthest_stage      VARCHAR,            -- max STAGE RANK, stored as the string
    furthest_date       DATE,               -- earliest filed_on at furthest_stage
    n_filings           INTEGER NOT NULL,
    n_sources           INTEGER NOT NULL,
    sources             VARCHAR,            -- sorted, comma-joined
    stages              VARCHAR,            -- sorted by rank, comma-joined
    loci_category       VARCHAR,            -- model/filing_categories.yaml; NULL = unmapped
    category_confidence VARCHAR CHECK (category_confidence IN (
                            'high', 'medium', 'unmapped')),
    category_hint       VARCHAR,            -- the hint that produced loci_category
    is_open             BOOLEAN NOT NULL,   -- first_inspection | license_issued | liquor_active
    opened_on           DATE,               -- earliest of those; see the caveat above
    opened_on_stage     VARCHAR,            -- WHICH of the three. Read it.
    lead_days           INTEGER,            -- entry_date -> opened_on, NULL if entry is terminal
    bbl_missing         BOOLEAN NOT NULL,   -- D75 flag
    name_key_missing    BOOLEAN NOT NULL,   -- D75 flag
    link_group_id       VARCHAR,            -- shared by the two rows of one link
    link_method         VARCHAR CHECK (link_method IS NULL OR link_method IN (
                            'rare_token', 'sole_pair_in_bbl')),
    link_partner_id     VARCHAR,            -- the other row's pipeline_id; UNIQUE both ways
    link_lead_days      INTEGER,            -- early.entry_date -> partner.opened_on
    asof_date           DATE NOT NULL,      -- the run date the windows count back from
                                            --   ('asof' alone is reserved: ASOF JOIN)
    built_at            TIMESTAMP NOT NULL,
    PRIMARY KEY (pipeline_id)
);

CREATE INDEX IF NOT EXISTS storefront_pipeline_bbl
    ON analysis.storefront_pipeline (bbl);
CREATE INDEX IF NOT EXISTS storefront_pipeline_name
    ON analysis.storefront_pipeline (business_name_key);
CREATE INDEX IF NOT EXISTS storefront_pipeline_cat
    ON analysis.storefront_pipeline (loci_category);

-- ---------------------------------------------------- analysis.storefront_pipeline_census
-- The stage x open-state pivot. A VIEW: it is a pivot of the grain above,
-- which is exactly what D61 says must not become a second table.
CREATE OR REPLACE VIEW analysis.storefront_pipeline_census AS
SELECT group_kind,
       entry_stage,
       furthest_stage,
       is_open,
       count(*)                                             AS n_rows,
       sum(n_filings)                                       AS n_filings,
       count(*) FILTER (WHERE loci_category IS NOT NULL)     AS n_categorised,
       count(*) FILTER (WHERE link_method IS NOT NULL)       AS n_linked,
       min(entry_date)                                      AS first_entry,
       max(entry_date)                                      AS last_entry,
       median(lead_days)                                    AS median_lead_days
FROM analysis.storefront_pipeline
GROUP BY 1, 2, 3, 4;

-- ------------------------------------------------------ analysis.storefront_pipeline_lead
-- Every (early stage -> terminal stage) pair the table supports, with HOW the
-- pair was made. `match` is the column that must never be averaged away:
--
--   'strict'      the early and terminal filings shared a business_name_key
--                 on one BBL. An OBSERVATION.
--   'rare_token'  \ the reconciliation linked two DIFFERENT name keys on one
--   'sole_pair_in_bbl'/ BBL. An INFERENCE. See the header.
--
-- Pooling them reports one median for two populations of different quality.
-- `loci storefront-pipeline stats` prints them side by side.
CREATE OR REPLACE VIEW analysis.storefront_pipeline_lead AS
-- strict: one pipeline row that carries both an early entry and an open signal
SELECT pipeline_id         AS early_id,
       pipeline_id         AS open_id,
       'strict'            AS match_kind,
       bbl,
       entry_stage         AS first_stage,
       opened_on_stage     AS open_stage,
       entry_date          AS first_filed,
       opened_on,
       lead_days,
       loci_category
FROM analysis.storefront_pipeline
WHERE lead_days IS NOT NULL
UNION ALL
-- reconciled: two pipeline rows on one BBL, linked across agencies
SELECT e.pipeline_id,
       o.pipeline_id,
       e.link_method,
       e.bbl,
       e.entry_stage,
       o.opened_on_stage,
       e.entry_date,
       o.opened_on,
       e.link_lead_days,
       coalesce(o.loci_category, e.loci_category)
FROM analysis.storefront_pipeline e
JOIN analysis.storefront_pipeline o ON o.pipeline_id = e.link_partner_id
WHERE e.link_method IS NOT NULL
  AND NOT e.is_open AND o.is_open
  AND e.link_lead_days IS NOT NULL;

-- ---------------------------------------------------------------------------
-- THE ADDRESS MEASURES -- analysis.address_category, by ALTER
-- ---------------------------------------------------------------------------
-- CONTEXT ONLY. Written exclusively by
-- `UPDATE analysis.address_category SET <OPENINGS_COLUMNS>`
-- (model/storefront_pipeline.write_openings, `loci storefront-pipeline
-- openings`). They do NOT enter gap_score, supply_ratio_vs_base, supply_400m
-- or any recommendation grade, and model/storefront_pipeline._guard asserts
-- the SET list is disjoint from every column another module owns, exactly as
-- model/address_access._guard does.
--
--   openings_pipeline_400m  pipeline rows of THIS category whose `entry_date`
--                           is within OPENINGS_PIPELINE_MONTHS (18) of `asof`
--                           and which are NOT YET OPEN, within 400 m NETWORK
--                           metres. "Somebody is spending money to open a
--                           <category> within a five-minute walk and the door
--                           is not open yet."
--
--   openings_recent_400m    pipeline rows of this category whose `opened_on`
--                           is within OPENINGS_RECENT_MONTHS (12), same
--                           radius. "A <category> opened within a five-minute
--                           walk in the last year."
--
-- THE TWO ARE DISJOINT BY CONSTRUCTION (`NOT is_open` versus `opened_on IS NOT
-- NULL`), so they may be added -- but adding them answers no question anybody
-- asked, and a row can move from the first column to the second between runs.
--
-- EVERY IN-SCOPE ADDRESS x CATEGORY GETS A NUMBER, and 0 IS A VALUE (owner
-- rule, 2026-09-13: no eligibility gate; every street represented). A block
-- with nothing coming gets 0, which is a real observation -- "nothing filed
-- within a five-minute walk" -- not a missing value. NULL means the command
-- has not been run for that borough since the last screen rebuild;
-- `openings_run_at IS NULL` is that flag.
--
-- 400 m is THRESHOLDS[5], the project's one definition of "within reach",
-- measured on the same pruned walk graph and the same bounded Dijkstra as
-- homes_400m / jobs_400m / supply_400m. No straight lines: a straight-line
-- 400 m in Manhattan crosses an avenue that takes 600 m of walking to get
-- around.
--
-- RE-APPLY AFTER EVERY SCREEN RE-RUN. `loci address-gaps` DELETEs and
-- re-INSERTs analysis.address_category, which destroys these columns along
-- with every other UPDATE-only annotation.
--
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- 1. A FILING IS NOT A STORE. Applications are withdrawn, permits lapse, and
--    a sign permit can be pulled for a tenant who never signs. These columns
--    count INTENT, and the churn is the signal, not noise.
-- 2. THE CATEGORY IS THE FILING'S, AND MOST FILINGS HAVE NONE. Both DOB feeds
--    publish free text, not a trade (model/filing_categories.yaml), so a row
--    whose only filings are DOB rows contributes to no category at all. The
--    measure is an UNDER-COUNT, thinnest at the earliest stages.
-- 3. THE POINT IS A LOT, NOT A DOOR. Where a feed published no coordinate the
--    row sits on its PLUTO lot centroid (`point_source`), which on a 200 m
--    Manhattan block front can be 100 m from the storefront.
-- 4. NOT A PARTITION OF ANYTHING. A pipeline row within 400 m of N addresses
--    is counted N times, BY DESIGN -- these are per-address catchments, not a
--    partition of the city. Never sum the column across addresses.
-- ---------------------------------------------------------------------------
ALTER TABLE analysis.address_category
    ADD COLUMN IF NOT EXISTS openings_pipeline_400m INTEGER;
ALTER TABLE analysis.address_category
    ADD COLUMN IF NOT EXISTS openings_recent_400m   INTEGER;
ALTER TABLE analysis.address_category
    ADD COLUMN IF NOT EXISTS openings_radius_m      REAL;
ALTER TABLE analysis.address_category
    ADD COLUMN IF NOT EXISTS openings_asof          DATE;
ALTER TABLE analysis.address_category
    ADD COLUMN IF NOT EXISTS openings_run_at        TIMESTAMP;

-- ---------------------------------------------------------------------------
-- THE FIRST-SEEN LEDGER GAINS A FOURTH KIND: 'gov_filing'
-- ---------------------------------------------------------------------------
-- sql/018 defined three kinds. A fourth is added here rather than in 018 so
-- that migration stays the historical record of what the ledger was when it
-- started, and because the kind only becomes possible once this table exists.
--
--   'gov_filing'  a government filing dated the opening EARLIER than anything
--                 a POI source could say -- or dated a LEFT-CENSORED row at
--                 all. `first_seen_src_date` is `storefront_pipeline.opened_on`
--                 and `first_seen_src_field` says so.
--
-- ONLY AN OPEN SIGNAL MAY SET A FIRST-SEEN. Never an application date, never
-- a permit, never a fit-out filing: those are dates on which somebody INTENDED
-- to open, and using one would date a storefront to a year before it existed.
-- `apply_gov_filing` reads `opened_on` and nothing else, and refuses a
-- liquor_active-derived date that precedes the row's own earliest filing (the
-- renewed-licence artefact described above).
--
-- IT CAN ONLY EVER MOVE A DATE EARLIER. The writer's WHERE clause requires
-- either `first_seen_kind = 'backfill_censored'` (the date was unknown and
-- unbounded below) or a strictly earlier date than the one held. That strict
-- inequality is what makes the command idempotent: after the first run the
-- condition is false for every row it already wrote.
--
-- THE REPORTING VIEW IS REPLACED, not edited in place in 018, for the same
-- reason. Two changes, both load-bearing:
--   * `first_seen_on` now returns a date for 'gov_filing' as well as
--     'source_date'. Without this the ledger would hold a real opening date
--     and the view -- which chains/detect.py reads, and which exists precisely
--     so a censored row can never be counted as an opening -- would report
--     NULL, i.e. undated, for the rows we finally managed to date.
--   * `is_left_censored` is unchanged: a gov_filing row is NOT censored.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW analysis.poi_first_seen AS
SELECT
    location_key,
    category,
    name_key,
    display_name,
    lon,
    lat,
    borough,
    first_seen_kind,
    CASE WHEN first_seen_kind = 'backfill_censored'
         THEN NULL ELSE first_seen_month END              AS first_seen_month,
    CASE WHEN first_seen_kind IN ('source_date', 'gov_filing')
         THEN first_seen_src_date END                     AS first_seen_on,
    first_seen_src_field,
    first_seen_month                                      AS ledger_first_month,
    (first_seen_kind = 'backfill_censored')               AS is_left_censored,
    last_seen_month,
    n_months_seen,
    cluster_id_latest,
    poi_id_latest,
    last_snapshot_at
FROM analysis.poi_presence;
