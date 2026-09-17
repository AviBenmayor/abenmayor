-- ---------------------------------------------------------------------------
-- 049_supply_snapshot.sql -- the supply set FROZEN as of each rewind t0.
--
-- WHY. Every backtest rung reconstructs "what existed at t0" at query time
-- (validation/retrodiction.supply_as_of, forecast._FEATURES_JSON_SQL), and
-- that reconstruction moves with every key migration (D103) and every gate
-- change (D96): the same t0 gives a different set on a different day, and no
-- number in a rewind is reproducible. This table materialises the set ONCE
-- per t0 through the one leakage-safe rule (`retrodiction.supply_as_of_sql`)
-- and stamps the supply hash it was cut under.
--
-- THE RULE, unchanged: a location is in the t0 set when its
-- `first_seen_src_date <= t0` OR it is `backfill_censored` (no date at all;
-- D79's conservative reading counts it as present). NO closure check: a
-- location the ledger says closed before t0 is STILL in the set, flagged
-- `status_at_t0 = 'closed'`, because the rule that the backtests already
-- read does not check it either (survivorship, pre-registration threat 8).
-- Filter on that column if you want the aggressive reading; the row is
-- there so the choice is visible.
--
-- THE NUMBER EVERY SNAPSHOT MUST CARRY. Pre-2023 t0 sets are ~47.7%
-- backfill-censored (D79): nearly half the "supply at 2016-01-01" is there
-- because nobody knows when it opened, not because it was seen in 2015.
-- analysis.supply_snapshot_census stamps that share per (t0, category); a
-- snapshot quoted without it lies.
--
-- GRAIN: (t0, location_key). Built by `loci rewind snapshot --t0`; rebuilding
-- a t0 replaces its rows. Existing read paths are NOT rewired to this table
-- in the build that created it (2026-09-17); that is a later, separate step.
--
-- CAVEATS THE DATABASE CANNOT ENFORCE
--  1. `bbl` is the nearest lot-frame analysis.address within 30 m, NULL
--     beyond -- a proximity assignment, not a deed.
--  2. `supply_hash` is the LIVE hash at build time. A snapshot whose hash is
--     not the current one was cut under a different supply set; compare it
--     to `analysis.address.supply_hash` before reading the two together.
--  3. lon/lat EPSG:4326 by convention.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.supply_snapshot (
    t0                  DATE NOT NULL,
    location_key        VARCHAR NOT NULL,
    category            VARCHAR NOT NULL,
    borough             VARCHAR NOT NULL CHECK (borough IN ('MN', 'BK')),
    bbl                 VARCHAR,
    bbl_m               DOUBLE,
    lon                 DOUBLE NOT NULL,
    lat                 DOUBLE NOT NULL,
    status_at_t0        VARCHAR NOT NULL CHECK (status_at_t0 IN ('open', 'closed')),
    first_seen_kind     VARCHAR NOT NULL,
    first_seen_src_date DATE,
    closed_on           DATE,
    censored            BOOLEAN NOT NULL,          -- first_seen_kind = 'backfill_censored'
    supply_hash         VARCHAR NOT NULL,
    built_at            TIMESTAMP NOT NULL,
    PRIMARY KEY (t0, location_key)
);

CREATE OR REPLACE VIEW analysis.supply_snapshot_census AS
SELECT t0,
       category,
       count(*)                                          AS n,
       count(*) FILTER (WHERE censored)                  AS n_censored,
       count(*) FILTER (WHERE censored)::DOUBLE / count(*) AS censored_share,
       count(*) FILTER (WHERE status_at_t0 = 'closed')   AS n_closed_before_t0,
       count(*) FILTER (WHERE bbl IS NULL)               AS n_without_bbl,
       any_value(supply_hash)                            AS supply_hash,
       count(DISTINCT supply_hash)                       AS n_hashes,
       max(built_at)                                     AS built_at
FROM analysis.supply_snapshot
GROUP BY ROLLUP (t0, category);
