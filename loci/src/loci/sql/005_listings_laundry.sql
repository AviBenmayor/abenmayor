-- ---------------------------------------------------------------------------
-- 005_listings_laundry.sql -- ADVERTISED in-building laundry from rental/sale
-- listing pages, keyed by BBL (D51(d)). Complement to 004_ll84_laundry.sql.
--
-- LL84 (004) is a MEASUREMENT of plumbing, and it structurally cannot see
-- buildings under 25,000 sq ft. Listing sites can, in principle, see any unit
-- that was ever advertised online. This file lands what the listings say.
--
-- Source of truth for the fetch: sources/cities/nyc/listings.py. Probed live
-- 2026-09-08 via the Tavily extract API against StreetEasy, Zillow, RentHop
-- and Apartments.com; only StreetEasy renders an amenity block plus a street
-- address. See the module docstring for the per-site probe table.
--
-- NOTHING IN score/ OR model/ READS THESE TABLES. Adopting advertised laundry
-- as supply changes gap_score, and that is an owner decision, not this file's.
--
-- ---------------------------------------------------------------------------
-- CAVEAT ZERO -- THE ONE THAT DICTATES THE SCHEMA
-- ---------------------------------------------------------------------------
-- A listing's amenity list is BROKER-ENTERED AND SYSTEMATICALLY INCOMPLETE.
-- Measured directly during the probe: 42 Carlton Avenue, Brooklyn has four
-- StreetEasy unit listings. Unit 4A lists "Laundry in building". Units 1R, 3L
-- and 4R list "Doorman" and "Live-in super" under the SAME "Services and
-- facilities" heading and omit laundry entirely. Same building. Same laundry
-- room. Three of four listings do not mention it.
--
-- Therefore SILENCE IS NOT ABSENCE, and this schema refuses to let a caller
-- pretend otherwise:
--
--   * `laundry_in_building` and `laundry_in_unit` are TRUE or NULL. They are
--     NEVER set FALSE by the absence of a phrase.
--   * `laundry_none` is set only by an EXPLICIT negative phrase in the page
--     ("No laundry", "Laundry: None"). "No info on building amenities" is a
--     NULL, not a FALSE -- it means StreetEasy has no amenity record at all.
--   * The BBL rollup exposes `any_laundry_advertised` as TRUE-or-NULL for the
--     same reason. There is no `no_laundry_advertised` column, because the
--     data cannot support one, and a column that exists WILL eventually be
--     read as if it meant something.
--
-- Aggregating an "n_none" from listings that merely omit laundry would
-- manufacture fake laundry gaps in buildings that demonstrably have laundry
-- rooms -- the exact double-count/false-gap failure this project has been
-- bitten by before. `n_silent` records how many listings were silent, so the
-- size of the unusable stratum is visible rather than laundered into a zero.
--
-- ---------------------------------------------------------------------------
-- OTHER CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. COVERAGE IS THE BINDING CONSTRAINT, NOT PARSING. Measured 2026-09-08 on
--    Brooklyn laundry-lead addresses: 1 of 10 randomly sampled lots with >=6
--    residential units had ANY StreetEasy listing, and 0 of 10 carried a
--    laundry answer. 0 of 7 head-of-ranking lots (by gap_score) had one. A
--    StreetEasy building page EXISTS for essentially every NYC address --
--    they are auto-generated from city parcel data -- so "the page rendered"
--    is not evidence of anything. `amenities_present` is the real denominator.
-- 2. SELECTION. Only units that were advertised online appear. That skews to
--    market-rate rentals in larger buildings and away from rent-stabilized
--    walk-ups, owner-occupied houses, and word-of-mouth lettings -- which are
--    precisely the stock that dominates the laundry gap ranking.
-- 3. RECENCY. A listing describes the building as of its listing date, not
--    today. `latest_listed` is the vintage of the newest evidence; there is no
--    guarantee the laundry room still operates. Pre-2015 evidence is weak.
-- 4. ADVERTISING, NOT INSPECTION. "Laundry in building" is a claim made to
--    sell a lease. Nobody verified it. LL84 counts plumbing; this counts
--    marketing copy. The two must not be pooled into one "has laundry" field.
-- 5. UNIT-LEVEL vs BUILDING-LEVEL. StreetEasy's "Home features: Washer/dryer"
--    is a property of ONE unit. It is recorded as `laundry_in_unit` on that
--    listing and MUST NOT be read as "this building's units have W/D".
-- 6. BBL ATTRIBUTION. A listing is attached to a BBL by street address, and a
--    single street address can span several tax lots (and one lot can carry
--    several addresses). `match_method` / `match_confidence` carry how the
--    attribution was made; anything below 'slug_exact' is a guess.
-- ---------------------------------------------------------------------------

-- One row per listing page fetched. Idempotent on listing_url: a re-fetch
-- replaces the row (the page's own content is the record, not the fetch).
CREATE TABLE IF NOT EXISTS staging.listings (
    listing_url         VARCHAR  NOT NULL,   -- canonical page URL, the primary key
    site                VARCHAR  NOT NULL,   -- 'streeteasy' | 'zillow' | ...
    bbl                 VARCHAR,             -- 10-digit, NULL when unmatched
    address_raw         VARCHAR,             -- address as the PAGE states it, not as we asked
    unit                VARCHAR,             -- unit designator from the URL path, NULL for building pages
    borough             VARCHAR,
    listing_type        VARCHAR,             -- 'rental' | 'sale' | NULL when the page does not say
    status              VARCHAR,             -- 'active' | 'past' | 'no_listing'
    listed_date         DATE,                -- most recent Listed/Rented/Sold event on the page
    -- TRUE or NULL only. See CAVEAT ZERO. Never written FALSE by omission.
    laundry_in_unit     BOOLEAN,
    laundry_in_building BOOLEAN,
    laundry_none        BOOLEAN,             -- only an EXPLICIT negative phrase sets this
    amenities_present   BOOLEAN  NOT NULL,   -- did the page carry a broker amenity list at all?
    raw_amenities       VARCHAR,             -- verbatim amenity text, for re-parsing without re-fetching
    page_lon            DOUBLE,              -- EPSG:4326, from the page's own static map
    page_lat            DOUBLE,              -- EPSG:4326
    match_method        VARCHAR,             -- 'slug_exact' | 'search' | 'unmatched'
    match_confidence    DOUBLE,              -- 0..1; see listings.py::_confidence
    match_offset_m      DOUBLE,              -- metres between page point and PLUTO point, EPSG:32118
    fetched_at          TIMESTAMP NOT NULL,
    PRIMARY KEY (listing_url)
);

-- Every Tavily call, with its credit cost. The spend record is a table, not a
-- log line, so `loci ingest-listings` can enforce a budget across runs and so
-- the projected cost of a full MN+BK sweep is arithmetic on real numbers
-- rather than a guess.
CREATE TABLE IF NOT EXISTS staging.listings_fetch_log (
    run_id       VARCHAR   NOT NULL,
    seq          INTEGER   NOT NULL,
    called_at    TIMESTAMP NOT NULL,
    endpoint     VARCHAR   NOT NULL,   -- 'search' | 'extract'
    n_urls       INTEGER   NOT NULL,   -- URLs in the request (extract batches up to 20)
    credits      DOUBLE,               -- from the API's include_usage; NULL if not returned
    http_status  INTEGER,
    n_ok         INTEGER,
    n_failed     INTEGER,
    note         VARCHAR,
    PRIMARY KEY (run_id, seq)
);

-- One row per BBL. Positive-only: `any_laundry_advertised` is TRUE or NULL.
CREATE TABLE IF NOT EXISTS analysis.address_listing_laundry (
    bbl                    VARCHAR  NOT NULL,
    n_listings             INTEGER  NOT NULL,   -- pages fetched for this BBL
    n_with_amenities       INTEGER  NOT NULL,   -- pages that carried a broker amenity list
    n_in_unit              INTEGER  NOT NULL,
    n_in_building          INTEGER  NOT NULL,
    n_none                 INTEGER  NOT NULL,   -- EXPLICIT negatives only (expected: ~0)
    n_silent               INTEGER  NOT NULL,   -- amenity list present, laundry not mentioned.
                                                -- NOT evidence of absence -- see CAVEAT ZERO.
    latest_listed          DATE,
    any_laundry_advertised BOOLEAN,             -- TRUE or NULL. Never FALSE.
    best_match_confidence  DOUBLE,
    sites                  VARCHAR,             -- comma-separated, provenance
    built_at               TIMESTAMP NOT NULL,
    PRIMARY KEY (bbl)
);

-- Join to the address screen, mirroring analysis.address_laundry_gaps. Kept a
-- VIEW for the same reason: address_gaps is rebuilt by `loci address-gaps`,
-- and an owner-undecided supply input must not become a column on the scored
-- table.
--
-- `listing_laundry_status` is deliberately THREE-valued, not four. There is no
-- 'no_laundry' state, because a listing that omits laundry is not evidence of
-- its absence.
CREATE OR REPLACE VIEW analysis.address_listing_laundry_gaps AS
SELECT
    g.address_id,
    g.bbl,
    g.borough,
    g.neighborhood,
    g.units,
    g.eligible,
    g.gap_score,
    g.lead_category,
    g.laundry_ratio,
    l.n_listings,
    l.n_with_amenities,
    l.n_in_unit,
    l.n_in_building,
    l.n_silent,
    l.latest_listed,
    l.any_laundry_advertised,
    l.best_match_confidence,
    CASE
        WHEN l.bbl IS NULL              THEN 'not_fetched'
        WHEN l.n_with_amenities = 0     THEN 'no_amenity_data'
        WHEN l.any_laundry_advertised   THEN 'laundry_advertised'
        ELSE 'amenities_silent'
    END AS listing_laundry_status
FROM analysis.address_gaps g
LEFT JOIN analysis.address_listing_laundry l ON l.bbl = g.bbl;
