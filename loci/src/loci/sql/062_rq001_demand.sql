-- ---------------------------------------------------------------------------
-- 062_rq001_demand.sql -- RQ-001 (regime durability) DEMAND panels: ACS
-- 5-year ZCTA panel and LODES8 WAC ZCTA jobs panel. Applied from
-- docs/research/RQ-001-regime-durability/drafts/zillow_acs.sql.draft (the
-- ACS half) and lodes_pluto.sql.draft (the LODES half) (GTM-224); DDL only
-- here, loaded from parquet by loci.sources.rq001_load.
--
-- SOURCE: src/loci/sources/universal/acs_zcta_panel.py and
-- src/loci/sources/universal/lodes_wac_zcta.py. Parquet:
--     data/interim/rq001/acs_zcta/acs_zcta_panel.parquet    (2,934 rows, 14 vintages)
--     data/interim/rq001/lodes/lodes_wac_zcta.parquet       (4,704 rows)
--
-- WHY `raw`/`analysis`, NOT `staging.poi`. ACS ZCTA is a ZCTA-level
-- demographic panel, LODES WAC is a ZCTA-level jobs panel -- neither is a
-- point-of-interest feed (no lon/lat, no address, no opened/closed date), so
-- neither goes through the staging.poi normalized contract (CONTEXT.md §10).
-- ACS lands in `raw` (declared empty in 002_schema.sql), matching
-- raw.fred_macro_* (sql/060) and raw.zillow_zip_* (sql/061). LODES is named
-- analysis.rq001_lodes_wac_zcta to match lodes_pluto.sql.draft's committed
-- name and its already-run validation queries (row counts, total-jobs
-- sanity check). Downstream reads join through explicit code in model/,
-- never by widening these tables or letting score/model read raw source
-- columns directly.
--
-- GRAIN.
--   raw.acs_zcta_panel: one row per (zcta, acs_year). acs_year is the
--     5-year window's END year (METHOD.md §2's "dated to their end year"
--     convention). `zcta_geography_vintage` (2010 for acs_year 2011-2019,
--     2020 for acs_year 2020-2024) is the boundary vintage the estimate was
--     published on -- NOT a crosswalk; a ZCTA code numerically identical
--     across that boundary is not guaranteed to cover the same land area.
--   analysis.rq001_lodes_wac_zcta: one row per (zcta, year), 2002-2023, 5
--     NYC counties only (36005 Bronx, 36047 Kings, 36061 New York, 36081
--     Queens, 36085 Richmond). LODES8 WAC (S000/JT00), block -> ZCTA via the
--     LEHD-native crosswalk. `block_geography` states whether that
--     (zcta, year) is OBSERVED (2020-2023, native 2020-vintage blocks) or
--     AREA-RETRO-ALLOCATED from the 2000/2010 block geography (2002-2019,
--     per CONTEXT.md §7.4b) -- a BIAS, not noise: correlated with where
--     block boundaries moved, which correlates with growth. Any query
--     spanning the 2019/2020 boundary must carry this column through.
--
-- THE ZIP <-> ZCTA JOIN IS NOT BUILT HERE, ON PURPOSE. ACS's `zcta` is a
-- Census ZCTA5; Zillow's (sql/061) and IRS SOI's (sql/060) `zip` are USPS
-- ZIPs. LODES also keys on ZCTA (native), but is deliberately kept as a
-- separate table from PLUTO (sql/061, keyed on ZIP) rather than unified to
-- one key -- METHOD.md §1 calls for exactly ONE FROZEN ZIP<->ZCTA crosswalk
-- mediating every cross-source join, used for the whole panel; building it
-- is out of this task's scope. The commented example below (from
-- zillow_acs.sql.draft) shows the SHAPE that join takes once the crosswalk
-- table exists -- it is not runnable as-is:
--
--   -- SELECT z.zip, z.year, z.value_mean, a.zcta, a.acs_year, a.median_hh_income_e
--   -- FROM raw.zillow_zip_annual z
--   -- JOIN raw.zip_zcta_crosswalk xw ON xw.zip = z.zip
--   -- JOIN raw.acs_zcta_panel a ON a.zcta = xw.zcta
--   --   AND a.acs_year = (SELECT MIN(acs_year) FROM raw.acs_zcta_panel
--   --                      WHERE acs_year >= z.year)  -- nearest vintage AT OR AFTER, not interpolated
--
-- CAVEATS THE DATABASE CANNOT ENFORCE
--   1. ACS 5-year estimates are OVERLAPPING WINDOWS (e.g. acs_year=2015 is
--      the 2011-2015 average). Adjacent vintages share 4 of 5 years of
--      underlying sample -- apparent year-over-year change understates the
--      true change and apparent persistence overstates it (METHOD.md §9).
--   2. A NULL ACS estimate column means the Census API returned a
--      suppressed/not-computable cell (typically a near-zero-population
--      ZCTA) -- NEVER substitute 0.
--   3. `education_table` ('B15002' for acs_year=2011 only, 'B15003' for
--      2012-2024) flags a TABLE RENUMBERING, not a definition change --
--      verified independently against the Census variables API, not
--      guaranteed sample-identical.
--   4. Every *_share column's numerator is a strict subset of its
--      denominator by construction, but *_share_m (MOE) uses the ACS
--      handbook's approximate proportion formula (assumes independence) --
--      treat as a conservative upper-bound approximation, never exact.
--   5. workers_16plus_e (ACS B08301) is BY PLACE OF RESIDENCE -- not
--      comparable to LODES WAC's place-of-work jobs count without knowing
--      which side of the commute you want.
--   6. LODES area-retro-allocation (2002-2019) is a bias correlated with
--      growth, not random noise -- see block_geography above and
--      CONTEXT.md §7.4b. Never aggregate 2002-2019 and 2020-2023 rows as if
--      they were measured the same way without carrying block_geography.
--   7. lon/lat: N/A for either table -- ZCTA is an attribute key, not a
--      geometry, in this schema.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.acs_zcta_panel (
    zcta                       VARCHAR NOT NULL,   -- Census ZCTA5, NOT a USPS ZIP
    acs_year                   INTEGER NOT NULL,   -- 5-year window's END year (operator-knowable date)
    zcta_geography_vintage     INTEGER NOT NULL CHECK (zcta_geography_vintage IN (2010, 2020)),
    education_table            VARCHAR NOT NULL CHECK (education_table IN ('B15002', 'B15003')),

    population_e               DOUBLE,             -- B01003_001E; NULL = suppressed, never 0
    population_m               DOUBLE,
    median_hh_income_e         DOUBLE,             -- B19013_001E
    median_hh_income_m         DOUBLE,
    per_capita_income_e        DOUBLE,             -- B19301_001E
    per_capita_income_m        DOUBLE,
    workers_16plus_e           DOUBLE,             -- B08301_001E, BY PLACE OF RESIDENCE (not LODES WAC's place-of-work)
    workers_16plus_m           DOUBLE,
    occupied_housing_units_e   DOUBLE,             -- B25003_001E
    occupied_housing_units_m   DOUBLE,
    median_gross_rent_e        DOUBLE,             -- B25064_001E
    median_gross_rent_m        DOUBLE,

    age_20_34_e                DOUBLE,             -- B01001 cells 008-012 + 032-036 (sum rule)
    age_20_34_m                DOUBLE,
    age_20_34_share            DOUBLE,             -- age_20_34_e / B01001_001E
    age_20_34_share_m          DOUBLE,             -- ACS handbook proportion-MOE formula

    bachelors_plus_denom_e     DOUBLE,             -- B15003_001E (2012+) or B15002_001E (2011)
    bachelors_plus_denom_m     DOUBLE,
    bachelors_plus_e           DOUBLE,             -- bachelor's-and-above numerator, table per education_table
    bachelors_plus_m           DOUBLE,
    bachelors_plus_share       DOUBLE,
    bachelors_plus_share_m     DOUBLE,

    loaded_at                  TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (zcta, acs_year)
);

CREATE TABLE IF NOT EXISTS analysis.rq001_lodes_wac_zcta (
    zcta            VARCHAR  NOT NULL,  -- 5-digit ZCTA (string, not int: leading zeros)
    year            INTEGER  NOT NULL,  -- 2002-2023
    c000            BIGINT,             -- total jobs, WAC C000 (all workers, JT00)
    cns07           BIGINT,             -- Retail Trade jobs (NAICS sectors 44-45)
    cns18           BIGINT,             -- Accommodation & Food Services jobs (NAICS 72)
    n_blocks        INTEGER  NOT NULL,  -- census blocks contributing to this (zcta, year)
    block_geography VARCHAR  NOT NULL,  -- provenance string: 'OBSERVED' (2020-2023) vs
                                         -- 'AREA-RETRO-ALLOCATED from the 2000/2010 block
                                         -- geography' (2002-2019) -- CONTEXT.md 7.4b. A BIAS,
                                         -- not noise: correlated with where block boundaries
                                         -- moved, which correlates with growth. Any query
                                         -- spanning the 2019/2020 boundary must carry this
                                         -- column through, not drop it.
    PRIMARY KEY (zcta, year)
);
