-- ---------------------------------------------------------------------------
-- 015_chains.sql -- the `chains` schema: retail/consumer brands expanding in NYC.
--
-- WHY A FOURTH SCHEMA, given the D61 inventory rule.
-- raw / staging / analysis are PIPELINE LAYERS for one grain: the location.
-- Everything in `analysis` is keyed on an address, a hex or a POI. A brand is a
-- DIFFERENT GRAIN -- one row per company, many locations, and a life outside
-- the warehouse (a sales list, a press record). Putting `brand_snapshot` into
-- `analysis` would put a company-grain table next to eleven location-grain ones
-- and invite exactly the joins that grain mismatch makes wrong.
--
-- The rule still bites, so this is THREE tables and ONE view, and every
-- brand-level pivot (flagged-only, by borough, by category) is a query, not a
-- table:
--
--   chains.brand_location   one row per (snapshot_month, brand_key, location)
--   chains.brand_snapshot   one row per (snapshot_month, brand_key)  <- history
--   chains.press_hits       one row per (brand_key, url)             <- research
--   chains.brand_latest     VIEW: brand_snapshot at its newest month
--
-- ---------------------------------------------------------------------------
-- WHY A MONTHLY SNAPSHOT AT ALL
-- ---------------------------------------------------------------------------
-- `locations_new_12m` is derived from whatever date each source happens to
-- carry (see chains/detect.py, FIRST_SEEN_FIELDS), and most sources carry
-- none: Overture, DOHMH restaurants, SNAP and DCWP all land with a NULL
-- first-seen. So the within-run growth number is a FLOOR computed on a
-- SUBSET, and it is honest only because `locations_dated` publishes that
-- subset's size beside it.
--
-- brand_snapshot is the fix that does not depend on any source's dates: take
-- the count every month, and from the second month on the growth measure is a
-- DIFFERENCE OF TWO COUNTS WE TOOK OURSELVES. `locations_delta_since` and
-- `months_observed` on chains.brand_latest are that measure. Until 12 months
-- of snapshots exist they are NULL, and the record-date estimate is all there
-- is. Do not silently blend them.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS chains;

-- ------------------------------------------------------- chains.brand_location
-- The audit trail: which locations produced a brand's count, so a suspicious
-- row can be read back to its POIs. Restricted to multi-location brands
-- (detect.MIN_LOCATIONS) -- one-off businesses are not chains and would make
-- this table the size of staging.poi.
--
-- `location_key` is analysis.poi_dedup.cluster_id as text: the DEDUPED
-- location, so a Starbucks carried by both Overture and Foursquare counts once.
CREATE TABLE IF NOT EXISTS chains.brand_location (
    snapshot_month VARCHAR NOT NULL,          -- 'YYYY-MM'
    brand_key      VARCHAR NOT NULL,
    location_key   VARCHAR NOT NULL,          -- poi_dedup.cluster_id
    poi_id         VARCHAR NOT NULL,          -- the canonical POI of that cluster
    category       VARCHAR NOT NULL,          -- one of the 15 loci categories
    borough        VARCHAR,                   -- via H3 res-9 -> analysis.hex
    lon            DOUBLE,
    lat            DOUBLE,
    first_seen_on  DATE,                      -- NULL where no source dated it
    first_seen_src VARCHAR,                   -- which field supplied it
    PRIMARY KEY (snapshot_month, brand_key, location_key)
);

-- ------------------------------------------------------- chains.brand_snapshot
-- One row per brand per month. Append-only in spirit; `loci chains detect`
-- DELETEs and re-INSERTs a single month so a re-run is idempotent and a
-- mid-month re-run corrects rather than duplicates.
CREATE TABLE IF NOT EXISTS chains.brand_snapshot (
    snapshot_month     VARCHAR NOT NULL,      -- 'YYYY-MM'
    brand_key          VARCHAR NOT NULL,
    display_name       VARCHAR,
    loci_category      VARCHAR,               -- modal category: the join key to
                                              -- analysis.address_category, and the
                                              -- reason a brand can ever become a
                                              -- recommendation signal
    locations_total    INTEGER NOT NULL,
    locations_dated    INTEGER NOT NULL,      -- of which carry a first_seen_on
    locations_new_12m  INTEGER NOT NULL,      -- FLOOR: dated subset only
    locations_new_3m   INTEGER NOT NULL,      -- FLOOR: dated subset only
    n_boroughs         INTEGER NOT NULL,
    boroughs           VARCHAR,               -- comma-separated, alphabetical
    categories         VARCHAR,               -- comma-separated, alphabetical
    n_sources          INTEGER NOT NULL,      -- distinct staging.poi source_ids
    flagged            BOOLEAN NOT NULL,      -- detect.FLAG_* rule fired
    flag_reason        VARCHAR,
    detected_at        TIMESTAMP NOT NULL,
    PRIMARY KEY (snapshot_month, brand_key)
);

-- ----------------------------------------------------------- chains.press_hits
-- `loci chains research` output. One row per (brand_key, url): re-running a
-- query that returns the same article updates it rather than duplicating it.
--
-- brand_key is '' for a DISCOVERY hit -- a result from a standing query that
-- has not been matched to any known brand. Those are the point of the
-- discovery queries: they are how a brand nobody has heard of reaches the list.
CREATE TABLE IF NOT EXISTS chains.press_hits (
    brand_key     VARCHAR NOT NULL,
    url           VARCHAR NOT NULL,
    title         VARCHAR,
    published_on  DATE,
    snippet       VARCHAR,
    score         DOUBLE,
    matched_query VARCHAR,
    query_kind    VARCHAR,                    -- 'brand' | 'discovery'
    fetched_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (brand_key, url)
);

-- ---------------------------------------------------------- chains.brand_latest
-- The newest snapshot per brand, with the cross-snapshot growth measure that
-- does not trust any source's dates. `locations_delta_since` is NULL until a
-- second snapshot exists -- NULL means "not yet measurable", never zero.
CREATE OR REPLACE VIEW chains.brand_latest AS
WITH newest AS (
    SELECT max(snapshot_month) AS m FROM chains.brand_snapshot
),
earliest AS (
    SELECT brand_key,
           min(snapshot_month)                                    AS first_month,
           count(DISTINCT snapshot_month)                         AS months_observed,
           arg_min(locations_total, snapshot_month)               AS locations_first
    FROM chains.brand_snapshot
    GROUP BY 1
)
SELECT s.*,
       e.first_month,
       e.months_observed,
       CASE WHEN e.months_observed >= 2
            THEN s.locations_total - e.locations_first END        AS locations_delta_since
FROM chains.brand_snapshot s
JOIN newest  n ON s.snapshot_month = n.m
JOIN earliest e ON e.brand_key = s.brand_key;
