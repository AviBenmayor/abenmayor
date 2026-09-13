-- ---------------------------------------------------------------------------
-- 019_storefront_filing.sql -- staging.storefront_filing: one row per
-- GOVERNMENT FILING EVENT on a commercial premises.
--
-- Owner's ask (2026-09-13): "find when stores go live via what they must
-- declare to the government -- not just for chains." `loci chains` finds new
-- locations of brands somebody already named. This finds the independent
-- operator who tells nobody except the City of New York, and it finds them
-- BEFORE the door opens, which is the whole point: a POI source records a
-- business that already exists.
--
-- ---------------------------------------------------------------------------
-- WHY A NEW TABLE (the D61 / feedback_table_proliferation inventory rule)
-- ---------------------------------------------------------------------------
-- `duckdb_tables()` before writing this file: staging.poi, staging.listings,
-- staging.listings_fetch_log, staging.ll84_laundry, staging.alcohol_licences,
-- analysis.{hex*, poi_dedup, poi_presence, address, address_category,
-- address_demographics, address_laundry*, address_entrance,
-- address_transit_profile, dev_pipeline, storefront, category_anchor, zip_*},
-- chains.{brand_location, brand_snapshot, press_hits}.
--
-- NONE of them holds a filing event.
--
--   staging.poi            a business that EXISTS, observed once. No filing, no
--                          application, no dated regulatory step.
--   analysis.poi_presence  the first MONTH a deduped location was observed by a
--                          POI source -- i.e. the first month somebody with a
--                          camera or a crawler noticed. Always LATER than the
--                          filing, and never carries why.
--   analysis.dev_pipeline  DOB-job grain, RESIDENTIAL units, one row per job.
--                          A storefront fit-out has no net units and is not in
--                          it.
--   analysis.storefront    one row per storefront per DOF filing -- the SPACE,
--                          and specifically the EMPTY space. This table is the
--                          opposite: the tenant arriving.
--   chains.brand_location  brand x location, derived from poi_dedup. Chains
--                          only, and again post-hoc.
--
-- The grain -- (source, raw_id) = one dated regulatory event -- is genuinely
-- new, is not a pivot or a subset of anything above, and cannot be expressed
-- as columns on an existing table (a premises has MANY filings, at many dates,
-- at many stages). So the rule's "pivots and subsets become views; new
-- measures extend the grain" does not apply, and a new staging table is
-- warranted. Stage two's analysis.storefront_pipeline (bbl x
-- business_name_key) is a ROLL-UP of this and must be a view or a derived
-- table over it -- never a second copy of the events.
--
-- ---------------------------------------------------------------------------
-- THE STAGE VOCABULARY
-- ---------------------------------------------------------------------------
-- Defined ONCE, in src/loci/filing_stages.py, with the full derivation and
-- caveats. Mirrored in the CHECK constraint below so the database rejects a
-- typo'd stage. The order in that module is the claim (earlier stage = earlier
-- in real time); the CHECK constraint is only a vocabulary, it does NOT encode
-- the order, because SQL has no ordered enum and an integer rank stored here
-- would renumber the day `outdoor_dining` lands.
--
--   liquor_application | fitout_filing | license_application | permit_issued |
--   sign_permit | license_issued | liquor_active | first_inspection |
--   outdoor_dining
--
-- ---------------------------------------------------------------------------
-- THE KEY, AND WHY IT IS NOT THE SOURCE'S OWN ID
-- ---------------------------------------------------------------------------
-- `filing_id` = '<source>:<stage>:<raw_id>'. THREE parts, not two, because one
-- source row can legitimately produce TWO stages: rbx6-tga4 emits
-- `permit_issued` for a General Construction permit and `sign_permit` for a
-- Sign permit, and the same job_filing_number prefix carries both. Keying on
-- (source, raw_id) alone would make those two events collide and one would be
-- silently lost.
--
-- `raw_id` is the source's own identifier VERBATIM -- application_id,
-- job_filing_number (WITH its work-type suffix), licence number, CAMIS -- so a
-- row can always be traced back to the published record.
--
-- NOTHING IS EVER DEDUPLICATED HERE. Two applications at the same address by
-- the same name are two applications: a withdrawn first attempt and a
-- successful second one is exactly the history this table exists to show, and
-- fusing them would manufacture the clean single-filing story that is not what
-- happened. Roll-ups collapse; the event log does not.
--
-- ---------------------------------------------------------------------------
-- GEOCODING AND `match_method`
-- ---------------------------------------------------------------------------
-- Every feed publishes a different subset of {BBL, BIN, house+street, lat/lon}.
-- The resolution ladder (model/storefront_filing.py), best first:
--
--   feed_bbl             the feed's own BBL, present in PLUTO 26v2. Trusted.
--   feed_bbl_unverified  a well-formed 10-digit BBL that PLUTO does not carry.
--                        KEPT, and flagged: PLUTO is a 2026 snapshot and a
--                        newly subdivided lot, a condo unit BBL, or a merged
--                        lot legitimately misses. Dropping it would delete the
--                        newest construction, which is the target population.
--   pluto_address        house number + street + borough, normalised, matching
--                        EXACTLY ONE PLUTO lot. An ambiguous match (the same
--                        normalised address on several lots) is NOT taken --
--                        it would attach a filing to an arbitrary neighbour.
--   pluto_nearest_30m    the published point, to the nearest PLUTO lot centroid
--                        within 30 m, computed with ST_Distance_Sphere on
--                        FLIPPED coordinates (db.METRES_SQL, D16) -- our
--                        geometry is (lon, lat) and the function reads
--                        (lat, lon).
--   unmatched            no BBL. The row is KEPT. A filing we cannot place is
--                        still evidence the filing happened, and the owner's
--                        standing ruling (D75, no eligibility gate) is that
--                        rows are flagged, not dropped.
--
-- CAVEAT THE DATABASE CANNOT ENFORCE: `pluto_nearest_30m` matches a LOT
-- CENTROID, not a storefront. On a 200 m Manhattan block front the centroid of
-- the correct lot can be further than 30 m from the door, so this method
-- under-matches on large lots rather than mis-matching -- the safe direction,
-- but it means BBL coverage is lower on exactly the big mixed-use lots where
-- ground-floor retail concentrates.
--
-- ANOTHER: DuckDB GEOMETRY carries NO SRID. `geom` here is EPSG:4326 by
-- convention, like everything else in this warehouse. Metric work reprojects
-- or uses METRES_SQL explicitly.
--
-- ---------------------------------------------------------------------------
-- WHAT THIS TABLE IS NOT
-- ---------------------------------------------------------------------------
-- It is not an opening-date table. `first_inspection` is the closest thing the
-- city publishes to one and it exists only for FOOD. For everything else the
-- terminal stage is `license_issued`, which is a licence date, not a door date.
-- And a filing that never became a business is indistinguishable from one that
-- did until a later stage appears -- the churn is the signal, not noise.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS staging.storefront_filing (
    filing_id          VARCHAR NOT NULL,   -- '<source>:<stage>:<raw_id>'
    source             VARCHAR NOT NULL,   -- registry.yaml source id
    stage              VARCHAR NOT NULL CHECK (stage IN (
                           'liquor_application', 'fitout_filing',
                           'license_application', 'permit_issued',
                           'sign_permit', 'license_issued', 'liquor_active',
                           'first_inspection', 'outdoor_dining')),
    business_name      VARCHAR,            -- the DBA/trade name as published
    business_name_key  VARCHAR,            -- chains.normalize.brand_key(business_name);
                                           -- NULL when the name is junk (an email,
                                           -- 'N/A', a bare number)
    bbl                VARCHAR,            -- 10-digit; NULL when unmatched
    bin                VARCHAR,            -- published only by some feeds
    house_number       VARCHAR,
    street_name        VARCHAR,
    borough            VARCHAR,            -- MN|BX|BK|QN|SI, the project's codes
    lon                DOUBLE,
    lat                DOUBLE,
    geom               GEOMETRY,           -- EPSG:4326 by convention (no SRID)
    filed_on           DATE,               -- the EVENT date for this stage
    status             VARCHAR,            -- the feed's own status text, verbatim
    status_date        DATE,               -- when the status was last set
    category_hint      VARCHAR,            -- the feed's own business/licence/work
                                           -- class, VERBATIM. Deliberately NOT
                                           -- mapped onto loci.categories: three
                                           -- feeds, three incompatible
                                           -- vocabularies, and a premature
                                           -- mapping would bury the mismatch.
    license_type       VARCHAR,            -- feed-specific licence/permit type
    match_method       VARCHAR NOT NULL CHECK (match_method IN (
                           'feed_bbl', 'feed_bbl_unverified', 'pluto_address',
                           'pluto_nearest_30m', 'unmatched')),
    raw_id             VARCHAR NOT NULL,   -- the source's own id, verbatim
    ingested_at        TIMESTAMP NOT NULL,
    provenance         VARCHAR NOT NULL,   -- dataset id + window + asof
    PRIMARY KEY (filing_id)
);

-- The stage x source census, for `loci filings stats` and for any consumer that
-- wants to see the lifecycle without knowing the feed names. A VIEW, not a
-- table: it is a pivot of the grain above, which is exactly what D61 says must
-- not become a second table.
CREATE OR REPLACE VIEW staging.storefront_filing_census AS
SELECT source,
       stage,
       count(*)                                          AS n_filings,
       count(DISTINCT business_name_key)                 AS n_name_keys,
       count(DISTINCT bbl)                               AS n_bbl,
       sum(CASE WHEN bbl IS NOT NULL THEN 1 ELSE 0 END)  AS n_matched,
       min(filed_on)                                     AS first_filed_on,
       max(filed_on)                                     AS last_filed_on
FROM staging.storefront_filing
GROUP BY source, stage;
