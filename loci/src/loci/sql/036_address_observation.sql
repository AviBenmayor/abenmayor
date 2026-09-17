-- ---------------------------------------------------------------------------
-- 036_address_observation.sql -- GROUND TRUTH AT THE RECOMMENDATION ANCHORS
-- (D105). What a human, driving a real browser on Google Maps and Street
-- View, could actually see standing at each anchor in analysis.recommendation.
--
-- Every other instrument in this warehouse reads a FEED. analysis.poi_presence
-- knows what Overture, OSM, Foursquare, SNAP, DOHMH, DCWP, SLA and DOS
-- published; analysis.address_category turns that into "nothing of this
-- category within reach"; analysis.recommendation turns THAT into a dated
-- claim. Nothing in the chain has ever looked at the doorway. This table is
-- the channel that does.
--
-- ---------------------------------------------------------------------------
-- WHY A NEW TABLE (the D61 / 2026-09-09 inventory rule)
-- ---------------------------------------------------------------------------
-- Inventory before writing, as the rule requires. What exists that is close:
--
--   analysis.poi_presence (sql/018)  one row per DEDUPED LOCATION, assembled
--       from feeds. An observation is not a location -- it is a dated LOOK at
--       a point, by a named observer, which may see two storefronts, or none.
--       Writing an observation here would mint a POI out of a sighting, which
--       is exactly the fabrication D79 exists to prevent.
--
--   analysis.poi_closure_evidence (sql/033)  one row per (poi, source, url)
--       lookup. It is keyed on poi_id, so it cannot hold the load-bearing
--       observation here: a storefront that is NOT in the warehouse has no
--       poi_id to key on, and those are precisely the rows the screen got
--       wrong. `record()` DOES write into it, for the subset that matched.
--
--   analysis.recommendation_outcome (sql/026)  one row per rec per MONTH,
--       derived from feeds by `loci recommendations check`. Same feeds, same
--       blind spot; and its grain is a monthly re-derivation, not a look.
--
-- So this is a genuinely new grain -- (which anchor, looked at when, by whom,
-- and what stood there) -- and it is ONE table plus ONE view. Every pivot of
-- it (per category, per verdict, per observer) is a query.
--
-- ---------------------------------------------------------------------------
-- A NULL storefront_name IS THE POINT, NOT A MISSING VALUE
-- ---------------------------------------------------------------------------
-- An observation session that saw nothing at an anchor writes ONE row with
-- storefront_name NULL and status 'vacant'. D79 in full: absence OBSERVED is
-- recorded; absence is never INFERRED. A rec with no row at all still reads
-- "nobody has looked yet", and the two states are different facts that this
-- table can tell apart. A design that skipped the empty record would silently
-- collapse them, and the confirmed gaps -- the good news for the screen --
-- would be the rows that vanished.
--
-- ---------------------------------------------------------------------------
-- WHAT THIS FILE DELIBERATELY DOES NOT DO: widen sql/033's source CHECK
-- ---------------------------------------------------------------------------
-- The original design gave the ground-truth evidence rows source='maps_ui'.
-- That is not implementable safely here, for two independent reasons:
--
--   1. DuckDB 1.5.5 implements neither `ALTER TABLE ... DROP CONSTRAINT` nor
--      `ADD CONSTRAINT` (probed 2026-09-14: "No support for that ALTER TABLE
--      option yet"), so a CHECK cannot be widened in place at all.
--   2. The only alternative -- create a new table, copy, drop, rename -- is a
--      destructive rewrite of a table other sessions are writing. db.init_schema
--      applies EVERY .sql file on disk, uncommitted ones included, so that
--      swap would fire inside a peer's session at a moment nobody chose.
--
-- So this file names analysis.poi_closure_evidence nowhere, and
-- model/ground_truth.py writes its evidence with source='web' and
-- domain_class='maps_ui' -- `domain_class` being exactly the field sql/033
-- reserves for "which KIND of web source". No provenance is lost:
-- poi_evidence.EvidenceRow.basis() renders it 'web_evidence:<verdict>:maps_ui:
-- <date>:<url>', and every such row carries query = 'ground-truth <rec_id>'.
-- tests/test_ground_truth.py::test_sql_036_touches_no_object_sql_033_created
-- pins that this file stays hands-off.
--
-- ONE RULE CHANGES SHAPE, DELIBERATELY. evidence/web_rules.py refuses to ever
-- emit 'open', because a page that does not say "closed" is not evidence a
-- business is trading. That is a statement about SEARCH HITS. A person looking
-- at a storefront and reading "Open" off its Maps card is a positive
-- observation of the thing itself and may say 'open'. What stays forbidden is
-- the inference this channel never makes: 'vacant' and 'unknown' write no
-- evidence row at all.
--
-- DEPENDENCIES: analysis.recommendation (sql/026) for rec_id, and
-- analysis.poi_presence (sql/018) for the miss view. db.init_schema applies
-- both before this file by filename order; model/ground_truth.ensure_schema
-- applies them explicitly for a bare warehouse.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS analysis.address_observation (
    observation_id  VARCHAR PRIMARY KEY,   -- sha1(rec_id|observed_at|storefront_name)
    rec_id          VARCHAR NOT NULL,      -- analysis.recommendation.rec_id
    anchor_address_id VARCHAR,             -- copied from the rec; NULL for a bbox/NTA card
    anchor_lon      DOUBLE,                -- the point the observer stood at,
    anchor_lat      DOUBLE,                --   EPSG:4326 by convention (no SRID)
    category        VARCHAR NOT NULL,      -- the RECOMMENDED category, frozen from the rec
    observed_at     TIMESTAMP NOT NULL,    -- when the look happened; part of the PK payload
    observer        VARCHAR,               -- who supervised the session
    maps_url        VARCHAR,               -- the exact URLs opened, so the look is repeatable
    streetview_url  VARCHAR,
    streetview_capture_date VARCHAR,       -- Google's imagery month, 'YYYY-MM'. NULLABLE and
                                           --   it matters: an observation is only as current
                                           --   as the panorama it was read off.
    screenshot_path VARCHAR,               -- local evidence file, if one was kept
    storefront_name VARCHAR,               -- NULL == nothing observed. See the header.
    name_key        VARCHAR,               -- model/poi_presence.name_key_of(storefront_name)
    category_guess  VARCHAR CHECK (category_guess IS NULL OR category_guess IN (
                        'grocery', 'convenience', 'pharmacy', 'laundry',
                        'hair_barber', 'nails_beauty', 'tailor_repair',
                        'restaurant', 'cafe_bakery', 'bar',
                        'childcare', 'clinic', 'fitness', 'bank', 'hardware',
                        'bathhouse_sauna')),   -- 16th slug, GTM-198 (2026-09-17).
                                           --   This literal only reaches a FRESH
                                           --   warehouse (CREATE IF NOT EXISTS);
                                           --   an existing one is rebuilt by
                                           --   `loci migrate-warehouse --step
                                           --   observation_category_check --apply`
                                           --   (migrate.py), at the ingest step,
                                           --   never by a session's init_schema.
    status          VARCHAR NOT NULL CHECK (status IN (
                        'open', 'closed', 'vacant', 'unknown')),
    maps_status_label VARCHAR,             -- the RAW label, e.g. 'Permanently closed'.
                                           --   Stored beside `status` so a re-reading of
                                           --   the observer's mapping is possible later.
    price_label     VARCHAR,               -- Maps' price token, VERBATIM ('$', '$$',
                                           --   '$10-20', ...), copied not parsed. NULL
                                           --   means Maps showed none (D105 2026-09-15:
                                           --   the free price channel; see
                                           --   model/ground_truth.py's docstring).
    matched_poi_id  VARCHAR,               -- analysis.poi_presence.poi_id_latest, ANY category
    match_distance_m DOUBLE,               -- anchor -> matched location, straight line
    gap_verdict     VARCHAR CHECK (gap_verdict IN (
                        'confirmed_gap', 'supply_missed', 'closure_missed',
                        'inconclusive')),  -- the observer's call FOR THE ANCHOR, copied onto
                                           --   every row of the session so a single row is
                                           --   self-describing
    notes           VARCHAR,
    raw             JSON,                  -- the storefront record as ingested, for audit
    run_id          VARCHAR,
    created_at      TIMESTAMP NOT NULL
);

-- D105 2026-09-15 (price channel): the shared warehouse already has this table
-- from 036's first application, and db.init_schema re-applies every *.sql on
-- each write connection -- CREATE TABLE IF NOT EXISTS above is therefore a
-- no-op there and never adds the column a fresh DB gets from the literal
-- above. This ALTER is the one place price_label actually lands on an
-- existing table; it is idempotent (IF NOT EXISTS) and touches no row.
ALTER TABLE analysis.address_observation ADD COLUMN IF NOT EXISTS price_label VARCHAR;

CREATE INDEX IF NOT EXISTS address_observation_rec
    ON analysis.address_observation (rec_id);
CREATE INDEX IF NOT EXISTS address_observation_link
    ON analysis.address_observation (category, name_key);

-- ------------------------------------- analysis.address_observation_miss
-- THE LOAD-BEARING OUTPUT. An OPEN storefront, of the RECOMMENDED category,
-- that analysis.poi_presence does not hold within 400 m of the anchor -- the
-- SAME catchment radius the gap score itself uses: a MEASURED false positive
-- of the gap screen, at one of the fifteen places this project actually
-- staked a claim on. D90 had to estimate this quantity by design-weighted
-- sampling; here it is observed.
--
-- D105 2026-09-15: this was originally 40 m ("is this the same doorway, not
-- is this within walking distance"). But the protocol's FIRST read is a
-- category-nearby search centered on the anchor (nearby_url), whose results
-- legitimately range across the whole 400 m catchment the gap score uses --
-- under the 40 m rule, a real, same-name POI 120 m from the anchor read as a
-- "miss," which is wrong: it is the business the observer was looking at
-- (the first real `ground-truth record` run landed 63 near-total-false rows
-- here under the old radius). A same-name match anywhere in the catchment is
-- now treated as the same business. "At the anchor" (<= 40 m) is still
-- answerable downstream from the stored `match_distance_m` column; this view
-- does not need a second radius to answer it. The literal below is
-- model/ground_truth.MATCH_RADIUS_M and tests/test_ground_truth.py pins them
-- together.
--
-- A row with an EMPTY name_key is excluded, not counted as a miss. norm_tokens
-- keeps only [a-z0-9], so a CJK or Arabic shopfront name normalizes to nothing
-- and CANNOT be matched by name -- calling that a miss would report the
-- tokenizer's blind spot as the supply model's (poi_presence.mint_key carries
-- the measurement: every one of the 118 hash collisions had an empty name_key).
--
-- D16: DuckDB's ST_Distance_Sphere reads POINT(x, y) as (LATITUDE, LONGITUDE)
-- and our geometry is (lon, lat), so BOTH sides are flipped. Never use the raw
-- function.
CREATE OR REPLACE VIEW analysis.address_observation_miss AS
SELECT o.*
FROM analysis.address_observation o
WHERE o.status = 'open'
  AND o.storefront_name IS NOT NULL
  AND o.name_key IS NOT NULL AND o.name_key <> ''
  AND o.category_guess IS NOT NULL
  AND o.category_guess = o.category
  AND NOT EXISTS (
      SELECT 1
      FROM analysis.poi_presence p
      WHERE p.name_key = o.name_key
        AND p.category = o.category
        AND p.lon IS NOT NULL AND p.lat IS NOT NULL
        AND ST_Distance_Sphere(
                ST_FlipCoordinates(ST_Point(p.lon, p.lat)),
                ST_FlipCoordinates(ST_Point(o.anchor_lon, o.anchor_lat))) <= 400.0
  );

-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. AN OBSERVATION IS AS OLD AS THE IMAGERY. Street View panoramas in NYC run
--    months to years behind. `streetview_capture_date` is the only thing that
--    says how stale, it is entered by hand, and a NULL there means the
--    observer did not record it -- NOT that the imagery is current.
--
-- 2. A MISS IS NOT AUTOMATICALLY A SCREEN ERROR. The observed storefront may
--    have opened AFTER the recommendation was issued, in which case the screen
--    was right on its own date and the market moved. `observed_at` and the
--    rec's `issued_on` are both stored so that can be separated; nothing here
--    separates them for you.
--
-- 3. THE MATCH IS BY NAME, AND NAMES ARE NOISY. `name_key` is sorted
--    normalized tokens, so "Sudsy Wash Laundromat" and "Sudsy Wash" do NOT
--    match. A false MISS (we hold the place under a different name) is
--    therefore possible, and it errs toward making the screen look WORSE than
--    it is -- the right direction for a self-scoring instrument.
--
-- 4. FIFTEEN ANCHORS IS NOT A SAMPLE. These are the places the project chose
--    to recommend, not a random draw from the frame. A miss RATE computed off
--    this table describes the recommendations, not the screen, and D90's
--    design-weighted estimate remains the one that generalizes.
-- ---------------------------------------------------------------------------
