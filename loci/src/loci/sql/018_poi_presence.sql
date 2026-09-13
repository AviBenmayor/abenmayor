-- ---------------------------------------------------------------------------
-- 018_poi_presence.sql -- the FIRST-SEEN LEDGER: when Loci itself first and
-- last observed each deduplicated storefront location.
--
-- Owner's ask (2026-09-13): "make sure moving forward we have dates on which
-- month data was first seen for storefronts." Independent of whether any
-- source publishes an open date, Loci must keep its OWN observation history.
--
-- ---------------------------------------------------------------------------
-- WHY A NEW TABLE (the D61 / 2026-09-09 inventory rule)
-- ---------------------------------------------------------------------------
-- Inventory before writing, as the rule requires. What already carries a date:
--
--   chains.brand_location    (snapshot_month, brand_key, location_key)
--       A monthly snapshot DOES exist -- but only for brands with >= 2
--       locations (detect.MIN_LOCATIONS). Roughly 6% of deduped locations.
--       The other 94% -- every single-site bodega, laundromat and clinic the
--       gap screen is actually about -- has no observation history anywhere.
--       Its grain is also (month, BRAND, location): a location that changes
--       brand, or that is co-branded, appears under two keys. It is an audit
--       trail for a brand count, not a registry of places.
--
--   analysis.storefront      (storefront_id, filing_due_date)
--       DOF Local Law 157 filings. A different universe: COMMERCIAL PREMISES
--       (ground floors, occupied or not), not businesses. It already carries
--       its own observation history in `filing_due_date` (11 filings,
--       2020-08-15 .. 2026-02-15), so "when did we first see this premises"
--       is `min(filing_due_date) GROUP BY premises_id` -- a query, not a row.
--       Deliberately OUT OF SCOPE here; see the note at the foot of this file.
--
--   staging.poi.observed_on / opened_on
--       Per SOURCE RECORD, and overwritten on every re-ingest: a source that
--       drops and re-adds a row loses its history. Not a ledger.
--
-- So this is a genuinely new grain -- one row per DEDUPLICATED LOCATION, for
-- ALL locations, persisting across ingests -- and it is ONE table plus ONE
-- view. Every pivot of it (new-this-month, censored-only, by category) is a
-- query.
--
-- ---------------------------------------------------------------------------
-- WHY location_key IS NOT analysis.poi_dedup.cluster_id
-- ---------------------------------------------------------------------------
-- CLUSTER_ID IS NOT STABLE ACROSS RE-RUNS, and nothing in the database says
-- so. score/dedup.build_dedup assigns it as `enumerate(clusters.values())`
-- plus a running per-category `offset`:
--
--   * the enumeration order is the order rows came back from an UNORDERED
--     `SELECT ... FROM staging.poi WHERE category = ?`, so two runs over
--     byte-identical data can number the same partition differently; and
--   * `offset` is the cumulative cluster count of the categories already
--     processed, so ONE new POI forming ONE new cluster in the first category
--     shifts every cluster_id in all fourteen later categories by one.
--
-- Joining a September ledger row to an October cluster_id would therefore not
-- merely lose a location, it would silently attach one storefront's history to
-- a DIFFERENT storefront. That is the fusing-distinct-storefronts bug this
-- project has already been bitten by, wearing an integer.
--
-- `cluster_id_latest` is kept as a CONVENIENCE JOIN KEY and is valid ONLY for
-- rows whose `last_seen_month` equals the newest snapshot month. Every other
-- row has it NULLed by `loci poi-snapshot`, so a stale join fails loudly
-- (no rows) instead of quietly matching the wrong place.
--
-- MEASURED, on the live warehouse (227,548 deduped locations, 2026-09-13):
-- re-running score/dedup on BYTE-IDENTICAL DATA in a shuffled row order
-- reproduces the partition exactly -- 100% identical clusters, 100% identical
-- canonical picks -- and yet 0.00% of POIs keep their cluster_id. The
-- partition is deterministic; the NUMBERING is pure input-order artefact.
--
-- Identity is instead carried by, in order:
--   1. an exact match on `location_key`, a content hash of
--      category | normalized-name tokens | lon,lat rounded to 4 dp, PLUS the
--      canonical poi_id when the normalized name is empty (see below); then
--   2. a NAME + DISTANCE link (score/dedup.norm_tokens + names_match, within
--      dedup.MATCH_METERS = 40 m, H3 res-11 blocked) against ledger rows not
--      already claimed -- the SAME rule that formed the cluster, so the link
--      cannot be looser than the dedup itself; then
--   3. minting a new key.
-- Step 2 is what absorbs a canonical-member change that nudges the coordinate
-- across a rounding boundary, which step 1 alone cannot survive.
--
-- THE NAMELESS CLAUSE IN STEP 1, and the bug that produced it. Of 227,548 live
-- clusters, 118 (0.052%) collided on category | name | lon,lat. EVERY ONE of
-- them had an empty normalized name: CJK and Arabic shopfront names, which
-- score/dedup.norm_tokens strips to nothing because it keeps only [a-z0-9],
-- plus all-generic names ("Chicken Kitchen", "Mexican Grocery & Deli") whose
-- every token is a stopword -- typically stacked on one fallback geocode.
-- The first implementation disambiguated those with a positional '-2' suffix.
-- That suffix depended on which collider was processed first, so the SECOND
-- snapshot minted 63 duplicate rows for locations the ledger already held and
-- two rows ended up claiming one cluster. `loci check-presence` caught it,
-- which is the whole reason its one-row-per-cluster assertion exists. Hashing
-- the canonical poi_id instead is stable, because the canonical pick is a
-- deterministic function of cluster membership (measured: 100% reproducible
-- under input reordering). The residual cost is real and stated in caveat 6.
--
-- ---------------------------------------------------------------------------
-- THE THREE KINDS OF FIRST-SEEN -- and the one that must never be reported
--
-- (A FOURTH, 'gov_filing', was added later by sql/020_storefront_pipeline.sql,
-- which also REPLACES the reporting view at the foot of this file so that
-- `first_seen_on` covers both dated kinds. Read 020's ledger section for it.
-- Nothing in this file is wrong; it is simply no longer the whole vocabulary,
-- which is why model/poi_presence.KINDS and not this comment is the list any
-- code should branch on.)
-- ---------------------------------------------------------------------------
--   'source_date'        a source gave an open / licence / enrolment date that
--                        is EARLIER than (or in the same month as) the month we
--                        first observed it. `first_seen_src_date` is that date
--                        and `first_seen_src_field` names the field.
--   'observed'           no usable source date; `first_seen_month` is the month
--                        Loci first saw it, and because the ledger was already
--                        running that month, it is a real appearance.
--   'backfill_censored'  the location already existed when the ledger started
--                        (2026-09) and no source dates it. Its true opening
--                        date is UNKNOWN and unbounded below. LEFT-CENSORED.
--
-- A censored row still stores `first_seen_month = '2026-09'` because the table
-- needs a non-null anchor for the last-seen arithmetic. THAT VALUE IS NOT AN
-- OPENING DATE. Reporting "161k storefronts opened in September 2026" is the
-- exact failure this comment exists to prevent, so the reporting surface is
-- the VIEW below, which returns NULL for a censored first_seen_month, and
-- consumers (chains/detect.py) read the view, never the table.
--
-- The first month in which "new" means anything at all is 2026-10: the first
-- month with a prior snapshot to be new relative to.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS analysis.poi_presence (
    location_key         VARCHAR PRIMARY KEY,  -- stable across ingests; see above
    category             VARCHAR NOT NULL,     -- one of the 15 loci categories
    name_key             VARCHAR,              -- sorted norm_tokens, the link key
    display_name         VARCHAR,              -- last observed canonical name
    lon                  DOUBLE,               -- last observed canonical position,
    lat                  DOUBLE,               --   EPSG:4326 by convention (no SRID)
    borough              VARCHAR,              -- via H3 res-9 -> analysis.hex
    first_seen_month     VARCHAR NOT NULL,     -- 'YYYY-MM'. WRITE ONCE, NEVER UPDATED.
    last_seen_month      VARCHAR NOT NULL,     -- 'YYYY-MM' of the newest snapshot
                                               --   that still saw this location
    first_seen_kind      VARCHAR NOT NULL,     -- source_date | observed | backfill_censored
    first_seen_src_date  DATE,                 -- non-NULL iff kind = 'source_date'
    first_seen_src_field VARCHAR,              -- which FIRST_SEEN_FIELDS entry won
    n_months_seen        INTEGER NOT NULL,     -- snapshots that saw it; see caveat
    cluster_id_latest    BIGINT,               -- poi_dedup.cluster_id THIS run only,
                                               --   NULL unless last_seen_month is newest
    poi_id_latest        VARCHAR,              -- canonical staging.poi id, same caveat
    ledger_started_month VARCHAR NOT NULL,     -- '2026-09' for every backfilled row
    last_snapshot_at     TIMESTAMP NOT NULL
);

-- Coverage and link lookups; the snapshot reads the whole table anyway, but
-- `check-presence` and the detect join both hit these.
CREATE INDEX IF NOT EXISTS poi_presence_cluster
    ON analysis.poi_presence (cluster_id_latest);
CREATE INDEX IF NOT EXISTS poi_presence_link
    ON analysis.poi_presence (category, name_key);

-- ------------------------------------------------------ analysis.poi_first_seen
-- THE REPORTING SURFACE. Read this, not the table, whenever the question is
-- "when did this open" -- it is the guard that a left-censored row can never
-- be counted as a September 2026 opening.
--
--   first_seen_month   NULL for a censored row. "We do not know."
--   first_seen_on      a DATE, and only ever a source's own date.
--   ledger_first_month always populated; the month the LEDGER starts for this
--                      row. An observation fact, NOT an opening date.
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
    CASE WHEN first_seen_kind = 'source_date'
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

-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. LEFT CENSORING IS THE MAJORITY, and will be for a year. Every backfilled
--    row that no source dates is 'backfill_censored'. Any "openings per month"
--    series built from this table must either exclude censored rows from the
--    numerator AND say so, or start at 2026-10.
--
-- 2. `n_months_seen` assumes snapshots are taken in non-decreasing month
--    order, which the monthly cron guarantees. It increments only when a
--    snapshot's month is strictly newer than the row's `last_seen_month`, so
--    re-running a month is a no-op (that is what makes the command
--    idempotent) -- but BACKFILLING an older month after a newer one has run
--    will not increment it, and will not move `last_seen_month` backwards.
--    The span (first_seen_month .. last_seen_month) minus n_months_seen is
--    therefore "months with a gap OR months snapshotted out of order", not
--    purely the former.
--
-- 3. A DISAPPEARANCE IS NOT A CLOSURE. `last_seen_month` falling behind the
--    newest snapshot means the deduped location stopped appearing -- which a
--    source outage, a geocode shift beyond 40 m, or a rename past the name
--    rule all produce just as readily as a shutter. Treat it as a prompt to
--    look, never as a closing date.
--
-- 4. A RE-TENANTING IS INVISIBLE. "Joe's Deli" becoming "Ana's Deli" at the
--    same address fails the name link and mints a NEW location_key, so the
--    new tenant reads as 'observed' in its first month -- which is right for
--    the storefront-turnover question and wrong for the premises question.
--    The premises question belongs to analysis.storefront, not here.
--
-- 6. NAMELESS LOCATIONS HAVE A WEAKER IDENTITY GUARANTEE than the rest. Their
--    key hashes the canonical poi_id (see above), so it moves if the canonical
--    member changes -- a feed dropping the winning row re-mints the key, and
--    the location reads as new. The name+distance link cannot rescue them
--    either: `names_match` refuses an empty token set by design. That is
--    ~0.05% of locations, and they are the ones we know least about anyway;
--    the alternative was fusing genuinely distinct storefronts, which is
--    strictly worse. Any "openings" spike concentrated in rows whose
--    `name_key` is '' should be read as a canonical-member churn artefact
--    before it is read as retail turnover.
--
-- 7. STOREFRONT REGISTRY (analysis.storefront) IS OUT OF SCOPE, for a reason
--    that is not laziness: it inventories SPACE, not businesses, its rows are
--    filings rather than observations, and sql/012 already establishes that
--    `storefront_id` is NOT stable across filings while `premises_id` is. Its
--    first-seen is therefore already available and already honest:
--        SELECT premises_id, min(filing_due_date) AS first_filed,
--               max(filing_due_date) AS last_filed
--        FROM analysis.storefront GROUP BY 1;
--    Copying that into this ledger would put two grains -- a business and a
--    ground floor -- under one primary key, which is the join mistake sql/015
--    created a separate schema to avoid.
-- ---------------------------------------------------------------------------
