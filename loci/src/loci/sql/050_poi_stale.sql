-- 050: staging.poi_stale — the rows an adapter observed and DELIBERATELY did
-- not put in the supply set, kept instead of thrown away.
--
-- ---------------------------------------------------------------------------
-- THE CONFLICT THIS RESOLVES
-- ---------------------------------------------------------------------------
-- Two owner rules collide on the Foursquare staleness gate.
--
--   RULE A (2026-09-16): "never ever ever limit data pulls". The Foursquare
--   adapter drops every venue whose `date_refreshed` predates MIN_REFRESHED
--   (2024-01-01). Measured on the 2026-08-11 release: 483,269 of 821,397
--   cached NYC venues, of which 79,182 map onto one of the fifteen Loci
--   categories. That is 42% of the mapped Foursquare universe discarded at
--   normalize() and never written anywhere.
--
--   RULE B: the supply set and `score/supply.supply_hash` may not move without
--   an announced, priced step (model/supply_asof.py, D119's freeze).
--
-- THE TWO CANNOT BOTH BE SATISFIED INSIDE staging.poi. The closure gate in
-- score/supply.canonical_poi_sql is `poi_status <> 'closed'` — TRI-STATE, and
-- 'unknown' SURVIVES it, deliberately (an unknown is not a closure; D79).
-- Foursquare publishes no status field, so a stale venue landing in
-- staging.poi resolves to 'unknown' and is therefore COUNTED AS SUPPLY. There
-- is no attrs value that avoids this: `active=false` yields 'unknown',
-- `active_basis='stale_NNNd'` is absence-derived and also yields 'unknown',
-- and only a PUBLISHED closure may yield 'closed' — which Foursquare has not
-- published for these rows, or they would be in the closed partition already.
--
-- Promoting them would roughly double laundry (3,954 -> ~9,200 before dedup)
-- on the strength of check-in records nobody has touched since 2023. That is a
-- supply-set decision, not a plumbing decision, and it needs an owner ruling.
--
-- SO THE ROWS ARE KEPT HERE. Same schema as staging.poi, plus why they were
-- held back and the freshness stamp that decided it. Nothing reads this table
-- into supply; `analysis.poi_supply` (sql/032) selects from staging.poi by
-- name and cannot see it. The data is no longer thrown away and the hash
-- cannot move because of it.
--
-- ---------------------------------------------------------------------------
-- WHAT THIS TABLE IS NOT
-- ---------------------------------------------------------------------------
-- It is NOT a closure ledger. A stale venue is an ABSENCE OF EVIDENCE, and D79
-- forbids reading absence as a closure. The closure ledger is
-- staging.poi_closure, which carries Foursquare's own published `date_closed`
-- on 228,455 NYC venues and is already complete — the closed partition
-- (sources/universal/foursquare_places.CLOSED_DIR) re-pulls the same release
-- with no open-only filter precisely so no closure is lost. Cap 3(a) was
-- therefore already satisfied before this file existed; only the staleness
-- drop was real data loss.
--
-- It is NOT a second supply set either. It has no dedup, no cluster, no
-- canonical row and no location_key, and it must not grow one without a
-- ruling: minting keys for 79,182 venues would give every one of them
-- `first_seen_month = <the month someone ran it>`, and the first-seen ledger
-- is write-once. To the chains detector and the forecast ledger that reads as
-- 79,182 businesses opening in one month. See the `poi-keys guard` comment in
-- the Makefile's chains-refresh target for the same hazard at 1/100th the
-- scale.
--
-- CAVEAT THE DATABASE CANNOT ENFORCE: `geom` is EPSG:4326 by convention.
-- DuckDB GEOMETRY carries no SRID and will not catch a violation; metric work
-- reprojects explicitly (db.METRES_SQL, or ST_Transform to EPSG:2263).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS staging.poi_stale (
    poi_id           VARCHAR PRIMARY KEY,
    source_id        VARCHAR  NOT NULL,
    source_record_id VARCHAR,
    category         VARCHAR  NOT NULL,   -- one of the 15; the mapping ran
    tier             SMALLINT NOT NULL CHECK (tier BETWEEN 1 AND 4),
    name             VARCHAR,
    geom             GEOMETRY NOT NULL,   -- EPSG:4326 by convention
    observed_on      DATE,
    opened_on        DATE,
    closed_on        DATE,
    confidence       FLOAT CHECK (confidence BETWEEN 0 AND 1),
    attrs            JSON,
    license_status   VARCHAR,
    licence_number   VARCHAR,
    business_unique_id VARCHAR,
    -- WHY the row is here rather than in staging.poi. A controlled string, so
    -- a later reader can tell a staleness hold-back from any other kind the
    -- table may come to carry. Never 'closed' — a closure belongs in
    -- staging.poi_closure.
    stale_reason     VARCHAR NOT NULL CHECK (stale_reason IN (
                         'refreshed_before_min', 'no_refresh_date')),
    -- The source's own freshness stamp, as a DATE, so the hold-back threshold
    -- can be re-run at another cut-off without re-fetching 50 MB of parquet.
    date_refreshed   DATE,
    ingested_at      TIMESTAMP
);

-- The census, for `loci ingest --source foursquare_os_places` to print and for
-- anyone pricing the promotion. A VIEW: it is a pivot of the grain above.
CREATE OR REPLACE VIEW staging.poi_stale_census AS
SELECT source_id, category, stale_reason,
       count(*)            AS n,
       min(date_refreshed) AS oldest_refresh,
       max(date_refreshed) AS newest_refresh
FROM staging.poi_stale
GROUP BY 1, 2, 3;
