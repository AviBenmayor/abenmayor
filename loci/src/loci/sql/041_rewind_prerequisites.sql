-- 041_rewind_prerequisites.sql -- data prerequisites for the 2020->2023 rewind
-- ===========================================================================
-- Two objects, one purpose. Both are PREREQUISITES named in the rewind
-- pre-registration (P1 and P3); neither is a finding, and nothing here scores
-- anything.
--
--   1. analysis.storefront.activity_canonical
--        LL157's business-activity label with DOF's 2024 recode undone and the
--        HEALTH CARE or/OR case split normalised. Derived; the raw column
--        stays exactly as filed.
--
--   2. analysis.licence_interval
--        One row per DCWP licence number: creation date, expiry, status, and
--        an explicitly-typed interval end. The open->closed clock the
--        warehouse has never had.
--
-- IDEMPOTENT. Every statement is CREATE/ALTER ... IF NOT EXISTS; the two
-- builders that populate them (model/activity_recode.backfill and
-- model/licence_interval.build) are DELETE-then-INSERT or full UPDATE, so
-- re-running the migration and the build is a no-op on a warehouse that
-- already has them.
--
-- ===========================================================================
-- 1. activity_canonical
-- ===========================================================================
-- WHY A SECOND COLUMN AND NOT A FIX IN PLACE. `primary_business_activity` is
-- what the landlord filed. Overwriting it would destroy the only evidence that
-- the recode happened and would make the repair unauditable -- and the repair
-- is MODAL (sql/012_activity_recode.yaml caveat 1), so it is an opinion about
-- a label, not a correction of a fact. Consumers asking a LONGITUDINAL
-- question read `activity_canonical`; consumers quoting what DOF published
-- read `primary_business_activity`; nobody has to know the difference exists
-- to get the right answer, which is the point.
--
-- NULL MEANS THE FILING DID NOT ASK. The vacant-only filings (2024-02-15,
-- 2024-08-15, 2025-02-15) carry NULL on every row of the activity column, and
-- this column is NULL there too. It is never 'UNKNOWN' and never ''.

ALTER TABLE analysis.storefront
    ADD COLUMN IF NOT EXISTS activity_canonical VARCHAR;

-- ===========================================================================
-- 2. analysis.licence_interval
-- ===========================================================================
-- ONE ROW PER DCWP LICENCE NUMBER, built from the full-history pull of
-- w7w3-xahh that now lands in staging.storefront_filing (source
-- `nyc_dcwp_licenses`, stage `license_issued`). 72,452 licences, creation
-- dates 1997-2026.
--
-- WHAT THIS TABLE DELIBERATELY DOES NOT DECIDE
-- --------------------------------------------
-- IT DOES NOT SAY WHICH STATUSES ARE CLOSURES. Every status DCWP publishes is
-- carried, verbatim, with its own row count intact: Active, Expired,
-- Surrendered, Revoked, Failed to Renew, Out of Business, Suspended, Voided,
-- Ready for Renewal, Close. The rewind pre-registration assigns each of them
-- to event / competing-risk / censored / dropped, and it does so differently
-- under its primary and strict definitions -- so a table that pre-judged them
-- would silently pick one of the two arms of a check whose whole purpose is
-- to be run both ways.
--
-- THE MISSING COLUMN, AND WHY `interval_end` IS TYPED
-- ---------------------------------------------------
-- w7w3-xahh PUBLISHES NO STATUS-CHANGE DATE. There is `license_creation_date`
-- and `lic_expir_dd`, and that is all. So for a licence reading `Surrendered`
-- the warehouse knows THAT it ended and not WHEN. Inventing a date -- the
-- expiry, the pull date, the midpoint -- would put a fabricated event time
-- into a survival model and the model would report a confident hazard shape
-- computed from an artefact.
--
-- Instead `end_kind` names exactly what is known, and a consumer that wants a
-- point-in-time event must choose its own rule and say so:
--
--   'active_censored'       status Active; right-censored at `pulled_asof`. The
--                           licence was alive when the file was pulled.
--   'expiry_observed'       non-Active status and an expiry on or before
--                           `pulled_asof`. The interval closes at the expiry: the
--                           licence is known to have been dead by then, and
--                           the expiry is a real published date.
--   'expiry_future'         non-Active status but an expiry AFTER `pulled_asof`. The
--                           status changed early -- surrendered, revoked,
--                           closed mid-term -- and the end date is UNKNOWN,
--                           bounded only by (creation, pulled_asof]. `interval_end`
--                           is set to `pulled_asof` and this kind marks it as a
--                           bound, NOT an observation. Do not treat it as an
--                           event time without an interval-censored estimator.
--   'no_expiry'             non-Active status and no expiry published at all.
--                           Same bound, same warning.
--
-- `interval_end` is therefore always <= `pulled_asof` and always >= the creation
-- date, and `end_kind` says whether it is a measurement or a ceiling.
--
-- OTHER CAVEATS THE DATABASE CANNOT ENFORCE
-- -----------------------------------------
--  * A LICENCE IS NOT A BUSINESS. DCWP re-creates a record on some renewals
--    (sql/019's note, carried from fetch_dcwp_licenses), so one continuously
--    trading shop can hold several licence numbers in sequence, and each one's
--    "end" is a paperwork event. `business_name_key` + BBL is how a consumer
--    stitches them; this table does not stitch them, because stitching is a
--    modelling choice about what counts as the same firm.
--  * A LICENCE TRANSFERS ON SALE. The premises trades on and the record
--    closes -- a false closure -- and the reverse also happens. Unmeasurable
--    here.
--  * COVERAGE IS BY LICENCE TYPE, NOT BY TRADE. DCWP licenses laundries,
--    garages, newsstands, sidewalk cafes, second-hand dealers and home
--    improvement contractors. It does NOT license restaurants, groceries or
--    pharmacies as such, so `loci_category` is NULL on the large majority of
--    rows and a category-level survival statement is only available for the
--    trades DCWP actually licenses.
--  * THE ADDRESS MAY BE A MAILING ADDRESS. Home Improvement Contractors are
--    licensed where the contractor lives, frequently outside the city.
--    `match_method` (carried from staging.storefront_filing) is the flag.

CREATE TABLE IF NOT EXISTS analysis.licence_interval (
    licence_number     VARCHAR NOT NULL,  -- w7w3-xahh license_nbr; the key
    business_name_key  VARCHAR,           -- chains.normalize.brand_key(); joins the
                                          --   CHAINS table. NOT the POI ledger's key.
    -- THE POI LEDGER'S OWN KEY, and a separate column because the project has
    -- TWO name normalisers and they do not agree:
    --   chains.normalize.brand_key  'DUANE READE #14' -> 'duane reade'
    --   poi_presence.name_key_of    'DUANE READE #14' -> '14 duane reade'
    -- brand_key strips store numbers and legal suffixes to find a BRAND;
    -- name_key_of sorts normalised tokens to find a STOREFRONT. Joining one
    -- against the other is not a low match rate, it is a category error, and
    -- it measured 0.1% before this column existed.
    poi_name_key       VARCHAR,           -- poi_presence.name_key_of(business_name)
    business_name      VARCHAR,           -- as published, for a human reading a row
    bbl                VARCHAR,           -- resolved by model/storefront_filing.match_bbl
    match_method       VARCHAR,           -- how the BBL was resolved; NULL = unresolved
    borough            VARCHAR,           -- MN/BX/BK/QN/SI
    address            VARCHAR,           -- house number + street, as published
    lon                DOUBLE,
    lat                DOUBLE,
    geom               GEOMETRY,          -- POINT, EPSG:4326 BY CONVENTION (no SRID)
    business_category  VARCHAR,           -- DCWP's own 49-value vocabulary, verbatim
    licence_type       VARCHAR,           -- Business / Individual / Premises
    loci_category      VARCHAR,           -- one of the 15, or NULL where none maps
    category_confidence VARCHAR,          -- 'high' (exact vocabulary match) | NULL
    licence_creation_date DATE NOT NULL,  -- the clock's start
    expiration_date    DATE,              -- lic_expir_dd; may be in the future
    status             VARCHAR,           -- DCWP's status, verbatim, NEVER recoded
    status_date        DATE,              -- ALWAYS NULL: the feed publishes none
    interval_end       DATE NOT NULL,     -- see end_kind; always <= asof
    end_kind           VARCHAR NOT NULL,  -- active_censored|expiry_observed|
                                          -- expiry_future|no_expiry
    days_observed      INTEGER,           -- interval_end - licence_creation_date
    -- NOT named `asof`: ASOF is a DuckDB keyword (ASOF JOIN) and an unquoted
    -- column of that name is a parser error in the CREATE TABLE.
    pulled_asof        DATE NOT NULL,     -- the pull's as-of; the censoring date
    source             VARCHAR NOT NULL,  -- 'nyc_dcwp_licenses'
    provenance         VARCHAR,
    ingested_at        TIMESTAMP NOT NULL,
    PRIMARY KEY (licence_number)
);

-- CREATE TABLE IF NOT EXISTS does NOT add a column to a table that already
-- exists, so a warehouse built from an earlier revision of this file keeps its
-- old shape and the view below then fails to bind. Every column added to the
-- table after its first release needs its own ALTER here, and every INSERT
-- into it names its columns.
ALTER TABLE analysis.licence_interval
    ADD COLUMN IF NOT EXISTS poi_name_key VARCHAR;

-- The join to the POI ledger. A VIEW, not a table (D61): every column is a
-- lookup over two tables that already exist, and storing it would be a second
-- object saying nothing new -- and would go stale the moment either side is
-- rebuilt.
--
-- TWO LADDER RUNGS, IN ORDER, NEVER UNIONED BLIND:
--   1. LICENCE NUMBER. staging.poi rows from `nyc_dcwp_licenses` carry the
--      licence number in `source_record_id`, so this rung is exact. The POI is
--      then followed through analysis.poi_dedup to its CLUSTER and from the
--      cluster to the ledger row -- because the DCWP record is usually the
--      non-canonical member of a cluster a Foursquare or DOHMH record leads,
--      and joining on `poi_presence.poi_id_latest` alone would silently miss
--      every one of those.
--   2. NAME KEY + 50 m. Only for licences rung 1 did not match. 50 m is
--      deliberately WIDER than the 40 m dedup radius: this is a REPORT of
--      reachability, not a merge. Nothing here writes to poi_presence and no
--      match here fuses two storefronts.
--
-- QUALIFY keeps ONE ledger row per licence -- the nearest, ties broken on the
-- key. Without it a licence on a corner lot with three same-name POIs appears
-- three times and every match rate computed from this view exceeds 100%: the
-- double-count bug in a different costume.
CREATE OR REPLACE VIEW analysis.licence_interval_poi AS
WITH by_number AS (
    SELECT li.licence_number,
           pres.location_key,
           'licence_number'                    AS join_method,
           CAST(0.0 AS DOUBLE)                 AS metres
    FROM analysis.licence_interval li
    JOIN staging.poi sp
      ON sp.source_id = 'nyc_dcwp_licenses'
     AND sp.source_record_id = li.licence_number
    JOIN analysis.poi_dedup d   ON d.poi_id = sp.poi_id
    JOIN analysis.poi_dedup dc  ON dc.cluster_id = d.cluster_id
                               AND dc.is_canonical
    JOIN analysis.poi_presence pres ON pres.poi_id_latest = dc.poi_id
),
unmatched AS (
    SELECT * FROM analysis.licence_interval
    WHERE licence_number NOT IN (SELECT licence_number FROM by_number)
      AND geom IS NOT NULL
      AND poi_name_key IS NOT NULL
      AND poi_name_key <> ''
),
by_name AS (
    -- ST_Distance on EPSG:4326 returns DEGREES and a degree is not a metre at
    -- this latitude (1 deg lon ~ 84 km, 1 deg lat ~ 111 km). Both sides are
    -- reprojected to EPSG:2263 (NY Long Island, US survey FEET) and the
    -- threshold is expressed in feet. DuckDB's GEOMETRY carries no SRID, so
    -- nothing but this comment and the explicit ST_Transform enforces it.
    SELECT u.licence_number,
           pres.location_key,
           'name_key_50m'                      AS join_method,
           ST_Distance(ST_Transform(u.geom, 'EPSG:4326', 'EPSG:2263'),
                       ST_Transform(ST_Point(pres.lon, pres.lat),
                                    'EPSG:4326', 'EPSG:2263')) / 3.280839895
                                               AS metres
    FROM unmatched u
    JOIN analysis.poi_presence pres
      ON pres.name_key = u.poi_name_key      -- NOT business_name_key; see the DDL
    WHERE pres.lon IS NOT NULL AND pres.lat IS NOT NULL
      AND ST_DWithin(ST_Transform(u.geom, 'EPSG:4326', 'EPSG:2263'),
                     ST_Transform(ST_Point(pres.lon, pres.lat),
                                  'EPSG:4326', 'EPSG:2263'),
                     164.042)                  -- 50 m, in feet
)
SELECT licence_number, location_key, join_method, metres
FROM (SELECT * FROM by_number UNION ALL SELECT * FROM by_name)
QUALIFY ROW_NUMBER() OVER (PARTITION BY licence_number
                           ORDER BY metres, location_key) = 1;
