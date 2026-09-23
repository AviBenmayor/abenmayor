-- ---------------------------------------------------------------------------
-- 061_rq001_cost_landuse.sql -- RQ-001 (regime durability) COST (Zillow
-- ZHVI/ZORI) and land-use (PLUTO ZIP vintages) panels. Applied from
-- docs/research/RQ-001-regime-durability/drafts/zillow_acs.sql.draft (the
-- Zillow half) and lodes_pluto.sql.draft (the PLUTO half) (GTM-224); DDL
-- only here, loaded from parquet by loci.sources.rq001_load.
--
-- SOURCE: src/loci/sources/universal/zillow.py and
-- src/loci/sources/universal/pluto_vintages.py. Parquet:
--     data/interim/rq001/zillow/zillow_nyc_monthly.parquet  (66,176 rows)
--     data/interim/rq001/zillow/zillow_nyc_annual.parquet   (5,674 rows)
--     data/interim/rq001/pluto/pluto_zip_vintage.parquet    (3,688 rows)
--
-- WHY `raw`/`analysis`, NOT `staging.poi`. Zillow is a ZIP-level price/rent
-- index, PLUTO-vintage is a ZIP-level land-use rollup -- neither is a
-- point-of-interest feed (no lon/lat, no address, no opened/closed date), so
-- neither goes through the staging.poi normalized contract (CONTEXT.md §10).
-- Zillow lands in `raw` (declared empty in 002_schema.sql), matching
-- raw.fred_macro_* (sql/060) and raw.acs_zcta_panel (sql/062). The PLUTO
-- table is named analysis.rq001_* (not raw.*) to match the table names
-- already committed to and validated against in lodes_pluto.sql.draft --
-- kept as-is rather than renamed, since the draft's own validation queries
-- (row counts, dropped_no_zip aggregation) were written and run against
-- those exact names. Downstream reads join through explicit code in
-- model/, never by widening these tables or letting score/model read raw
-- source columns directly.
--
-- GRAIN.
--   raw.zillow_zip_monthly: one row per (zip, month, index). `index` is
--     'zhvi' or 'zori' -- both landed in ONE table because they share every
--     other column.
--   raw.zillow_zip_annual: one row per (zip, year, index). `value_mean` is
--     the plain mean of that year's available monthly observations;
--     `n_months` records how many fed it (< 12 for 2026's partial year, and
--     for any ZIP Zillow started/stopped covering mid-year) -- NEVER treat a
--     < 12 year as equivalent to a complete one without checking n_months.
--   analysis.rq001_pluto_zip_vintage: one row per (zipcode, year), one
--     canonical (latest-major-release) vintage per calendar year, 2009-2026.
--     2002-2008 requested but VERIFIED ABSENT at the NYC DCP archive CDN --
--     not silently dropped, just not obtainable from this source at this URL.
--
-- THE ZIP <-> ZCTA JOIN IS NOT BUILT HERE, ON PURPOSE (same as sql/062's
-- ACS panel and sql/060's IRS panel). Zillow's `zip` is a USPS ZIP; ACS's
-- `zcta` is a Census ZCTA5. METHOD.md §1 calls for exactly ONE FROZEN
-- ZIP<->ZCTA crosswalk, used for the whole panel -- that crosswalk is a
-- separate, not-yet-built artifact, out of this task's scope.
--
-- CAVEATS THE DATABASE CANNOT ENFORCE
--   1. Zillow ZIP is a POSTAL ZIP, not a Census ZCTA -- no FOREIGN KEY
--      exists or could exist between raw.zillow_zip_annual.zip and
--      raw.acs_zcta_panel.zcta until the frozen crosswalk is built.
--   2. Zillow's `value_mean` under `n_months < 12` is a PARTIAL-YEAR mean,
--      not comparable on equal footing to a full-year mean.
--   3. LODES aggregates to Census ZCTA (sql/062); PLUTO aggregates to postal
--      ZipCode (NYC DCP's own field) -- these two are DELIBERATELY NOT
--      unified to the same key here. Join through the frozen crosswalk when
--      it exists, never by a bare key-name coercion.
--   4. PLUTO GEOMETRY: this table carries no GEOMETRY column. Upstream
--      lat/lon (XCoord/YCoord) were NOT used for this rollup; ZipCode was
--      used directly as NYC DCP assigns it per tax lot. If a later stage
--      needs ZCTA/ZIP polygons, pull TIGER/Line boundaries explicitly and
--      reproject with ST_Transform -- the DB will not catch a missing SRID.
--   5. `assesstot_total` is NOMINAL dollars, NOT deflated. Deflate to real
--      dollars before any cross-year comparison (CONTEXT.md deflation
--      convention) -- the deflator choice belongs at panel-assembly, not
--      baked into this table.
--   6. `dropped_no_zip` is a CITYWIDE constant, broadcast onto every zipcode
--      row for that year (it counts lots city-wide, not per ZIP) --
--      aggregate with max()/first(), NEVER sum(), or it inflates by that
--      year's ZIP count. Runs 0.2-0.7% of that vintage's lots citywide in
--      every year except 2018 (2.4%, flagged, unexplained).
--   7. lon/lat: N/A for either table -- no geometry, EPSG or otherwise.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.zillow_zip_monthly (
    zip          VARCHAR NOT NULL,       -- USPS ZIP, e.g. '11201' -- NOT a ZCTA
    month        DATE NOT NULL,          -- month-end date, Zillow's own column label
    index        VARCHAR NOT NULL CHECK (index IN ('zhvi', 'zori')),
    value        DOUBLE NOT NULL,        -- $ level; ZHVI = smoothed/SA home value, ZORI = smoothed/SA asking rent
    county_name  VARCHAR NOT NULL,       -- Zillow's own CountyName, provenance only (e.g. 'Kings County')
    loaded_at    TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (zip, month, index)
);

CREATE TABLE IF NOT EXISTS raw.zillow_zip_annual (
    zip          VARCHAR NOT NULL,
    year         INTEGER NOT NULL,
    index        VARCHAR NOT NULL CHECK (index IN ('zhvi', 'zori')),
    value_mean   DOUBLE NOT NULL,        -- mean of that year's available monthly observations
    n_months     INTEGER NOT NULL CHECK (n_months BETWEEN 1 AND 12),
    loaded_at    TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (zip, year, index)
);

CREATE TABLE IF NOT EXISTS analysis.rq001_pluto_zip_vintage (
    zipcode             INTEGER  NOT NULL,  -- USPS ZIP as recorded in PLUTO's ZipCode field
    year                INTEGER  NOT NULL,  -- 2009-2026, one canonical vintage per year
    pluto_version       VARCHAR  NOT NULL,  -- e.g. '23v3' -- which major release this is,
                                             -- so a caller can tell two adjacent years apart
                                             -- from a mid-year minor release artifact
    n_lots              INTEGER,            -- tax lots with a valid (non-null, >0) ZipCode
    bldgarea_total      DOUBLE,             -- SUM(BldgArea), sq ft
    comarea_total       DOUBLE,             -- SUM(ComArea), sq ft
    retailarea_total    DOUBLE,             -- SUM(RetailArea), sq ft
    assesstot_total     DOUBLE,             -- SUM(AssessTot), NOMINAL dollars -- NOT deflated (see caveat 5)
    unitsres_total      DOUBLE,             -- SUM(UnitsRes), residential units
    n_lots_with_retail  INTEGER,            -- COUNT(*) WHERE RetailArea > 0
    dropped_no_zip      INTEGER  NOT NULL,  -- CITYWIDE total lots excluded from every aggregate
                                             -- above because ZipCode was NULL/0 in that
                                             -- vintage's raw file (see caveat 6) -- aggregate
                                             -- with max()/first() across a year, NEVER sum().
    PRIMARY KEY (zipcode, year)
);
