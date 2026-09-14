-- ---------------------------------------------------------------------------
-- 027_poi_closure.sql -- THE CLOSURE LEDGER: a source-published date on which a
-- storefront stopped trading, and the two columns on analysis.poi_presence that
-- carry it.
--
-- WHY THIS EXISTS (docs/retrodiction-2026-09.md §4)
-- ---------------------------------------------------------------------------
-- The 2026-09 retrodiction could not fit a survival model because it found
-- ZERO observable closures. Not few -- zero, across 12,572 dated openings. The
-- reason was not that New York does not close restaurants. It was that every
-- closure instrument in the warehouse is a CURRENT-STATE EXTRACT:
--
--   poi_presence.last_seen_month   one snapshot month; nothing to fall behind of
--   storefront_pipeline.is_open    means EVER opened; 100% survival by construction
--   dohmh_restaurants              a closed restaurant is ABSENT, not stale
--   dof_storefront_registry        premises grain, no business identity
--   foursquare.date_closed         0 of 821,397 cached rows -- THE COLUMN EXISTS,
--                                  the fetch filtered `date_closed IS NULL`
--
-- The last line is the cheapest unlock in the project and this file is it.
-- sources/universal/foursquare_places.ensure_closed_cache re-pulls the same
-- release and the same bbox with NO open-only filter, into its OWN file
-- (data/raw/foursquare_closed/), and model/poi_closure loads the closed rows
-- here.
--
-- ---------------------------------------------------------------------------
-- THE SUPPLY SET IS NOT TOUCHED, AND THAT IS LOAD-BEARING
-- ---------------------------------------------------------------------------
-- A closed venue must NEVER reach staging.poi, analysis.poi_dedup or
-- analysis.poi_supply. The screen answers "what is open here today"; a shut
-- laundromat counted as supply would erase the very gap the screen exists to
-- find. So:
--   * `FoursquarePlacesAdapter.fetch()` still reads the OPEN cache
--     (data/raw/fsq_places_nyc.parquet) and `normalize()` still `continue`s on
--     any row with a `date_closed`. Neither was changed.
--   * this table lives in `staging` but is NOT a `staging.poi` extension: it
--     has no `poi_id`, is never unioned into it, and nothing in score/ or
--     model/ reads it except the two ledger columns below.
-- tests/test_poi_closure.py asserts the first bullet against the real adapter.
--
-- ---------------------------------------------------------------------------
-- IDENTITY: location_key, MINTED BY THE LEDGER'S OWN RULE
-- ---------------------------------------------------------------------------
-- `location_key` here is `model/poi_presence.mint_key(category,
-- name_key_of(name), lon, lat)` -- THE SAME FUNCTION, not a reimplementation,
-- so a closure hashes exactly as the open location did. Matching is then
-- two-pass, in the ledger's own order of confidence (poi_presence.KINDS /
-- link_to_ledger):
--   1. exact `location_key`                      -> closed_src 'foursquare:key'
--   2. norm_tokens + names_match within
--      score.dedup.MATCH_METERS (40 m), same category
--                                                -> closed_src 'foursquare:link'
-- Pass 2 is the dedup's own rule, so the closure link can never be LOOSER than
-- the rule that formed the cluster. Widening it would attach one storefront's
-- closure to its neighbour -- the fusing-distinct-storefronts bug, which here
-- would manufacture a closure that never happened.
--
-- A NAMELESS CLOSURE CANNOT MATCH AT ALL, by construction and on purpose.
-- `mint_key` folds the canonical `poi_id` into the hash when the normalized
-- name is empty (sql/018, caveat 6) and a closure has no poi_id, so pass 1
-- cannot fire; `names_match` refuses an empty token set, so pass 2 cannot
-- either. Such rows are still LOADED -- they are counted, and their absence
-- from the join is visible rather than silent.
--
-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. ABSENCE IS STILL NOT A CLOSURE (D79). `closed_on` is filled ONLY from a
--    source-published `date_closed`. A location that stops appearing in a
--    snapshot gets NOTHING here: `last_seen_month` falling behind is a prompt
--    to look, and a source outage, a geocode shift past 40 m or a rename past
--    the name rule all produce it just as readily as a shutter. `poi-snapshot`
--    fills these columns FROM THIS TABLE and never from the absence of a row.
--
-- 2. FOURSQUARE'S date_closed IS RIGHT-BIASED AND INCOMPLETE. OS Places marks a
--    venue closed when its pipeline learns of it, which for a check-in-derived
--    base is late and, for the categories nobody checks in at, often never.
--    The registry note on the source already says it: closed venues are rarely
--    marked closed, they just stop being refreshed (that is what MIN_REFRESHED
--    exists for). So a NULL `closed_on` is "no closure observed", NEVER "still
--    open", and any survival estimate built on it is an UPPER BOUND on
--    survival. The bias is also categorical -- a bar's closure is announced,
--    a tailor's is not -- so it does not cancel across categories.
--
-- 3. THE DATE IS A PUBLICATION DATE, not a shutter date. It is the analogue of
--    the cohort's `first_seen_src_date` problem (retrodiction §3) at the other
--    end of the spell: non-classical measurement error in the timing variable,
--    in the direction of LATE.
--
-- 4. A RE-TENANTED ADDRESS CAN MATCH THE WRONG TENANT only if both tenants
--    share a normalized name within 40 m, which is the same tolerance the
--    dedup already accepts. `closure_precedence` never overwrites an earlier
--    `closed_on` with a later one, so where two closures land on one key the
--    EARLIEST survives -- the conservative direction for survival analysis.
--
-- 5. ONE RELEASE, ONE SNAPSHOT. `fetched_at` and the release in the raw
--    filename are the provenance. A later release will carry MORE closures for
--    the same venues; re-running the ingest replaces the table wholesale, which
--    is why `closed_on` is re-derived from it on every `poi-snapshot` rather
--    than accumulated.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.poi_closure (
    fsq_place_id  VARCHAR PRIMARY KEY,  -- the source's own id; one row per venue
    location_key  VARCHAR,              -- ledger key MINTED by poi_presence.mint_key;
                                        --   NULL-able only in the sense that a
                                        --   nameless row's key can never match
    category      VARCHAR,              -- Loci slug via foursquare_places.map_leaf;
                                        --   NULL = closed, but not one of our 15
    name          VARCHAR,
    lon           DOUBLE,               -- EPSG:4326 by convention (DuckDB carries
    lat           DOUBLE,               --   no SRID); reproject for metric work
    date_created  DATE,
    date_closed   DATE NOT NULL,        -- the whole point; a row without one is
                                        --   not a closure and is never loaded
    source        VARCHAR NOT NULL,     -- 'foursquare'
    fetched_at    TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS poi_closure_key ON staging.poi_closure (location_key);
CREATE INDEX IF NOT EXISTS poi_closure_link ON staging.poi_closure (category, name);

-- ------------------------------------------------- analysis.poi_presence + 2
-- The ledger gains the other end of the spell. Both are NULL for every row no
-- source has published a closure for, and NULL means "no closure observed",
-- never "still open" (caveat 2).
ALTER TABLE analysis.poi_presence ADD COLUMN IF NOT EXISTS closed_on DATE;
ALTER TABLE analysis.poi_presence ADD COLUMN IF NOT EXISTS closed_src VARCHAR;

-- ------------------------------------------------------ analysis.poi_first_seen
-- REPLACES the view last replaced by sql/020 (which itself replaced sql/018's).
-- Identical to 020's apart from the two closure columns and `is_closed`.
-- `model/poi_presence.ensure_schema` applies 018 AND THEN THIS FILE for exactly
-- this reason: running 018 alone would silently revert the view to the
-- source_date-only `first_seen_on` and drop `closed_on` off the reporting
-- surface altogether.
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
    closed_on,                       -- a SOURCE-published closing date, or NULL
    closed_src,                      -- 'foursquare:key' | 'foursquare:link'
    (closed_on IS NOT NULL)                               AS is_closed,
    cluster_id_latest,
    poi_id_latest,
    last_snapshot_at
FROM analysis.poi_presence;
