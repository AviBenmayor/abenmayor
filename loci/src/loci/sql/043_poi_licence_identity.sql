-- 043: licence identity as COLUMNS on staging.poi, and the rung of
-- analysis.licence_interval_poi that was structurally empty because of it.
--
-- ---------------------------------------------------------------------------
-- WHY (the measurement that forced it)
-- ---------------------------------------------------------------------------
-- `loci rewind checks` P3 -- "MN+BK licences join the POI ledger" -- reported
-- 0.9% against a 50% floor. The reason is not a bad name-matching rule. It is
-- that the FIRST rung of analysis.licence_interval_poi (sql/041) joins
--
--     staging.poi WHERE source_id = 'nyc_dcwp_licenses'
--                   AND source_record_id = li.licence_number
--
-- and staging.poi held ZERO rows for `nyc_dcwp_licenses`. The roster adapter
-- (sources/cities/nyc/dcwp.py::DcwpAdapter) dropped every non-Active row, and
-- the only roster category that maps onto a Loci category -- "Laundries", 6
-- rows -- is 100% Expired. The rung could never fire. Everything therefore
-- fell through to `name_key_50m`, which is a name match and behaves like one.
--
-- ---------------------------------------------------------------------------
-- WHAT THIS FIXES, AND WHAT IT CANNOT FIX (measured live 2026-09-16)
-- ---------------------------------------------------------------------------
-- Removing the Active filter puts those 6 rows in staging.poi, so the rung
-- fires. It is 6 rows. The honest finding behind the low P3 rate is a
-- POPULATION MISMATCH, not an identity problem:
--
--   * the DCWP roster (w7w3-xahh) is 72,452 licences over 49 business
--     categories whose mass is Home Improvement Contractor (18,931), Tobacco
--     Retail Dealer (6,707), Secondhand Dealer (6,356), Sightseeing Guide
--     (3,974). EXACTLY ONE of the 49 maps onto one of Loci's 15 categories.
--   * the DCWP establishments Loci DOES carry as POIs are the 4,285 retail
--     laundries from the INSPECTIONS feed (jzhd-m6uv) -- and DCWP does not
--     publish licences for retail laundry at all.
--   * the overlap, measured on `business_unique_id` (the one key the two DCWP
--     feeds share): 41 of 4,285 laundry establishments hold ANY roster
--     licence; 43 of 72,452 roster rows belong to an establishment Loci holds
--     as a POI.
--
-- So no join rule can raise P3 materially. A licence-number rung that is
-- present and small is the correct state; a 50% floor on this pairing is
-- asking two disjoint populations to overlap.
--
-- ---------------------------------------------------------------------------
-- COLUMNS, NOT JSON KEYS
-- ---------------------------------------------------------------------------
-- `license_status`, `licence_number` and `business_unique_id` were already
-- carried inside staging.poi.attrs by the adapters that had them. A JSON key
-- is not a join key: it is unindexable in a join predicate and invisible to
-- anyone reading the schema. They are promoted to columns here and KEPT in
-- attrs, because model/poi_presence.poi_is_open reads attrs and its rule is
-- deliberately unchanged by this migration.
--
-- `license_status` IS THE PUBLISHER'S OWN STRING, VERBATIM, NEVER A VERDICT.
-- 'Active' does not mean open (a roster snapshot can be months stale) and
-- 'Expired' does not mean closed (a laundromat outlives its licence). The
-- open/closed verdict stays exactly where it was: poi_is_open, reading
-- attrs.active / attrs.active_basis / the expiry date.
--
-- CAVEAT THE DATABASE CANNOT ENFORCE: analysis.poi_supply (sql/032) selects an
-- EXPLICIT column list from staging.poi, not `s.*`, so these three columns do
-- NOT propagate to analysis.poi_supply_status. That is deliberate -- the
-- supply view's shape is pinned by tests and by `SELECT s.*` consumers
-- downstream of it. Anything that needs the licence identity joins
-- staging.poi by poi_id.
--
-- The pending holding tables are `CREATE TABLE ... AS SELECT * FROM
-- staging.poi LIMIT 0` clones (dcwp.ensure_pending_table and its two twins).
-- A clone made BEFORE this migration keeps the old shape, and the promotion
-- step inserts a NAMED column list that now includes these three -- so each
-- existing clone is altered here too. `ALTER TABLE IF EXISTS` because a fresh
-- warehouse has never created them.
-- ---------------------------------------------------------------------------

ALTER TABLE staging.poi ADD COLUMN IF NOT EXISTS license_status     VARCHAR;
ALTER TABLE staging.poi ADD COLUMN IF NOT EXISTS licence_number     VARCHAR;
ALTER TABLE staging.poi ADD COLUMN IF NOT EXISTS business_unique_id VARCHAR;

ALTER TABLE IF EXISTS staging.poi_dcwp_pending
    ADD COLUMN IF NOT EXISTS license_status     VARCHAR;
ALTER TABLE IF EXISTS staging.poi_dcwp_pending
    ADD COLUMN IF NOT EXISTS licence_number     VARCHAR;
ALTER TABLE IF EXISTS staging.poi_dcwp_pending
    ADD COLUMN IF NOT EXISTS business_unique_id VARCHAR;

ALTER TABLE IF EXISTS staging.poi_dohmh_childcare_pending
    ADD COLUMN IF NOT EXISTS license_status     VARCHAR;
ALTER TABLE IF EXISTS staging.poi_dohmh_childcare_pending
    ADD COLUMN IF NOT EXISTS licence_number     VARCHAR;
ALTER TABLE IF EXISTS staging.poi_dohmh_childcare_pending
    ADD COLUMN IF NOT EXISTS business_unique_id VARCHAR;

ALTER TABLE IF EXISTS staging.poi_nys_medicaid_pharmacy_pending
    ADD COLUMN IF NOT EXISTS license_status     VARCHAR;
ALTER TABLE IF EXISTS staging.poi_nys_medicaid_pharmacy_pending
    ADD COLUMN IF NOT EXISTS licence_number     VARCHAR;
ALTER TABLE IF EXISTS staging.poi_nys_medicaid_pharmacy_pending
    ADD COLUMN IF NOT EXISTS business_unique_id VARCHAR;

-- analysis.licence_interval gains the DCWP cross-feed key. sql/041's own
-- comment already warns that CREATE TABLE IF NOT EXISTS does not add a column
-- to an existing table, so every later column needs its own ALTER here.
ALTER TABLE analysis.licence_interval
    ADD COLUMN IF NOT EXISTS business_unique_id VARCHAR;

-- ---------------------------------------------------------------------------
-- The ledger join, re-rendered with THREE rungs instead of two.
-- ---------------------------------------------------------------------------
-- STATUS OF RUNG 2, STATED PLAINLY SO NOBODY READS MORE INTO IT THAN IS THERE:
-- it is structurally correct and CURRENTLY CONTRIBUTES ZERO ROWS, because
-- `analysis.licence_interval.business_unique_id` is NULL on every row today.
-- That column is populated from `staging.storefront_filing`, and the DCWP
-- licences feed (filing_feeds.fetch_dcwp_licenses) does not carry
-- business_unique_id -- staging.storefront_filing has no column for it, and
-- adding a network round-trip to a builder whose whole design is "read the
-- staging table, do not re-hit Socrata" is the wrong trade for the measured
-- payoff. THE MEASURED PAYOFF IS 43 ROWS out of 126,869 (see the overlap
-- figures above). The rung is here because it is the RIGHT identity rule and
-- because writing it down is how the 43-row ceiling stops being rediscovered;
-- it is not here because it moves the number.
--
-- Rung order is precedence order, strongest identity first:
--   1. licence_number  -- the licence IS the POI's source_record_id
--   2. business_unique_id -- the two DCWP feeds' shared premises key. The
--      roster licences a BUSINESS; the inspections feed inspects a PREMISES;
--      DCWP mints business_unique_id (BA-nnnnnnn-YYYY) for both. dcwp.py
--      verified it is premises-level, not account-level, on the laundry slice.
--   3. name_key_50m -- the fallback, unchanged from sql/041.
-- Rung 3's `unmatched` CTE must exclude everything rungs 1 AND 2 matched, or
-- a licence could be paired twice and a closure counted twice -- the
-- double-count bug this project keeps having to re-close.
--
-- EPSG NOTE, carried verbatim from sql/041 because it still applies: ST_Distance
-- on EPSG:4326 returns DEGREES and a degree is not a metre at this latitude
-- (1 deg lon ~ 84 km, 1 deg lat ~ 111 km). Both sides are reprojected to
-- EPSG:2263 (NY Long Island, US survey FEET) and the threshold is in feet.
-- DuckDB GEOMETRY carries no SRID; nothing but this comment and the explicit
-- ST_Transform enforces it.
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
by_business AS (
    SELECT li.licence_number,
           pres.location_key,
           'business_unique_id'                AS join_method,
           CAST(0.0 AS DOUBLE)                 AS metres
    FROM analysis.licence_interval li
    JOIN staging.poi sp
      ON sp.business_unique_id IS NOT NULL
     AND sp.business_unique_id = li.business_unique_id
    JOIN analysis.poi_dedup d   ON d.poi_id = sp.poi_id
    JOIN analysis.poi_dedup dc  ON dc.cluster_id = d.cluster_id
                               AND dc.is_canonical
    JOIN analysis.poi_presence pres ON pres.poi_id_latest = dc.poi_id
    WHERE li.business_unique_id IS NOT NULL
      AND li.licence_number NOT IN (SELECT licence_number FROM by_number)
),
unmatched AS (
    SELECT * FROM analysis.licence_interval
    WHERE licence_number NOT IN (SELECT licence_number FROM by_number)
      AND licence_number NOT IN (SELECT licence_number FROM by_business)
      AND geom IS NOT NULL
      AND poi_name_key IS NOT NULL
      AND poi_name_key <> ''
),
by_name AS (
    SELECT u.licence_number,
           pres.location_key,
           'name_key_50m'                      AS join_method,
           ST_Distance(ST_Transform(u.geom, 'EPSG:4326', 'EPSG:2263'),
                       ST_Transform(ST_Point(pres.lon, pres.lat),
                                    'EPSG:4326', 'EPSG:2263')) / 3.280839895
                                               AS metres
    FROM unmatched u
    JOIN analysis.poi_presence pres
      ON pres.name_key = u.poi_name_key      -- NOT business_name_key; see sql/041
    WHERE pres.lon IS NOT NULL AND pres.lat IS NOT NULL
      AND ST_DWithin(ST_Transform(u.geom, 'EPSG:4326', 'EPSG:2263'),
                     ST_Transform(ST_Point(pres.lon, pres.lat),
                                  'EPSG:4326', 'EPSG:2263'),
                     164.042)                  -- 50 m, in feet
)
SELECT licence_number, location_key, join_method, metres
FROM (SELECT * FROM by_number
      UNION ALL SELECT * FROM by_business
      UNION ALL SELECT * FROM by_name)
QUALIFY ROW_NUMBER() OVER (PARTITION BY licence_number
                           ORDER BY metres, location_key) = 1;
