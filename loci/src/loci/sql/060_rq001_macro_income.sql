-- ---------------------------------------------------------------------------
-- 060_rq001_macro_income.sql -- RQ-001 (regime durability) macro backdrop
-- (FRED) and IRS SOI ZIP-code income panel. Applied from
-- docs/research/RQ-001-regime-durability/drafts/macro.sql.draft and
-- irs_soi.sql.draft (GTM-224); DDL only here, loaded from parquet by
-- loci.sources.rq001_load.
--
-- SOURCE: src/loci/sources/macro.py (FRED) and
-- src/loci/sources/irs_soi_history.py (IRS SOI). Parquet:
--     data/interim/rq001/macro/macro_monthly.parquet   (9,322 rows, 2026-09-22 pull)
--     data/interim/rq001/macro/macro_annual.parquet    (804 rows, 2026-09-22 pull)
--     data/interim/rq001/irs_soi/irs_zip_income_panel.parquet (17,453 rows, 2026-09-22 pull)
--
-- WHY `raw`, NOT `staging.poi`. Neither source is a point-of-interest feed --
-- FRED is a national/metro time series, IRS SOI is a ZIP-level tax-filing
-- aggregate. Neither has lon/lat, an address, or an opened/closed date, so
-- neither goes through the staging.poi normalized contract (CONTEXT.md §10).
-- Both land in `raw` (declared empty in 002_schema.sql); score/model must
-- never read these columns directly -- any join into analysis.nta_trajectory
-- or an RQ-001 hazard table happens through explicit code in model/.
--
-- GRAIN.
--   raw.fred_macro_monthly: one row per (series_id, date), date = first of
--     month. MORTGAGE30US is published weekly upstream and resampled to a
--     monthly mean in macro.py's build_monthly() -- no weekly-native rows.
--   raw.fred_macro_annual: one row per (series_id, year). rollup states how
--     that year's value was derived: 'mean' for every rate/index series,
--     'max' for USREC (one recession month makes the year a recession year
--     for a hazard-driver join -- a mean would understate a one-month
--     2020-04-style spike to near zero).
--   raw.irs_zip_income_panel: one row per (zip, tax_year, agi_stub).
--     agi_stub NULL = legacy year (1998-2010, no bracket detail, only the
--     ZIP total); 0 = synthetic total row this adapter computes for modern
--     years (2011-2022) by summing brackets 1-6 (NOT published by IRS
--     directly as agi_stub=0 -- IRS's own agi_stub=0 rows are STATE totals
--     under zipcode='00000' and are dropped entirely, never landed here);
--     1-6 = IRS's own published AGI brackets, modern era only.
--
-- CAVEATS THE DATABASE CANNOT ENFORCE
--   1. NOT a claim about NYC specifically for every FRED row. NYUR is NY
--      STATE; NEWY636URN and SMU36935617072200001 are the NY-Newark-Jersey
--      City NY-NJ-PA MSA, not the five boroughs; UNRATE/FEDFUNDS/GS10/
--      CUSR0000SEFV/CES7072200001/USREC are US-NATIONAL. Never join one of
--      these to a ZIP-level row and imply it is that ZIP's own value -- it
--      is the shared macro backdrop, identical across every trade area in a
--      given year (METHOD.md §5).
--   2. `covid_window` (FRED tables) is a modeling-convenience BOOLEAN
--      (2020-03-01..2021-12-31), not a claim about when COVID's economic
--      effects began or ended (METHOD.md §5).
--   3. CUURA101SA0 (NY-metro CPI, all items) stands in for a NY-metro
--      food-away-from-home series that does not exist under any FRED id
--      probed -- a cost-of-living proxy, not food-specific.
--   4. FRED `units` is a free-text label, not enforced by CHECK; a blank
--      FRED observation is DROPPED upstream (macro.py's tidy_series()),
--      never coerced to 0. A missing (series_id, date) row means "FRED had
--      no observation," not "the value was zero."
--   5. IRS SUPPRESSION IS NULL, NEVER ZERO. Any legacy-year cell IRS marked
--      '*'/'**' decodes to NULL in n1/agi/n_wages/a_wages, and
--      `any_suppressed` is set true. The modern (2011-2022) CSV era
--      publishes 0 directly for small cells rather than a suppression
--      marker -- `any_suppressed` is always false there; this asymmetry is
--      real, not an adapter bug.
--   6. IRS ZIP universe drift is real (208 ZIPs in 1998 -> 183 by 2018-2022)
--      -- IRS periodically merges/retires low-filing ZIPs; a ZIP vanishing
--      from this panel is not evidence the neighborhood emptied out.
--   7. IRS AGI brackets are NOT comparable across the legacy/modern seam
--      (bucket counts changed release to release before settling at 6 in
--      2011); only the ZIP-total row is comparable across the full 1998-2022
--      span. `agi`/`a_wages` are already converted to plain USD (source's
--      "$ thousands" convention) -- do not re-multiply by 1000.
--   8. IRS zip is a USPS ZIP, not a Census ZCTA -- no crosswalk exists yet
--      to join against raw.acs_zcta_panel or analysis.nta_trajectory.
--   9. 2008 IRS rows have NO wage-return count (n_wages NULL by source
--      design, not a parse failure).
--   10. lon/lat: N/A for every table here -- no geometry, EPSG or otherwise.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.fred_macro_monthly (
    series_id     VARCHAR NOT NULL,   -- FRED series id, e.g. 'UNRATE', 'NEWY636URN'
    date          DATE NOT NULL,      -- first of month; MORTGAGE30US resampled from weekly
    value         DOUBLE NOT NULL,    -- never a coerced 0 for a blank observation (dropped instead)
    freq          VARCHAR NOT NULL,   -- 'monthly' for every row (see grain note above)
    units         VARCHAR NOT NULL,   -- 'percent' | 'index_1982_84_100' | 'thousands' | 'binary'
    title         VARCHAR NOT NULL,   -- FRED's series title, for provenance in a chart legend
    covid_window  BOOLEAN NOT NULL,   -- 2020-03-01..2021-12-31, modeling convenience only (see caveat 2)
    loaded_at     TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (series_id, date)
);

CREATE TABLE IF NOT EXISTS raw.fred_macro_annual (
    series_id     VARCHAR NOT NULL,
    year          INTEGER NOT NULL,
    value         DOUBLE NOT NULL,
    units         VARCHAR NOT NULL,
    title         VARCHAR NOT NULL,
    rollup        VARCHAR NOT NULL CHECK (rollup IN ('mean', 'max')),  -- 'max' only for USREC
    covid_window  BOOLEAN NOT NULL,   -- true if ANY month of the year falls in the COVID window
    loaded_at     TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (series_id, year)
);

CREATE TABLE IF NOT EXISTS raw.irs_zip_income_panel (
    zip             VARCHAR NOT NULL,        -- USPS ZIP, zero-padded to 5 digits -- NOT a ZCTA (see caveat 8)
    tax_year        INTEGER NOT NULL,
    agi_stub        INTEGER,                 -- NULL = legacy year (1998-2010, no bracket detail);
                                              -- 0 = ZIP total (all years); 1-6 = modern-era bracket (2011-2022 only)
    n1              DOUBLE,                  -- number of returns; NULL = suppressed (legacy years only, see caveat 5)
    agi             DOUBLE,                  -- adjusted gross income, USD (converted from source's $ thousands)
    n_wages         DOUBLE,                  -- number of returns reporting wages; NULL where not published (2008) or suppressed
    a_wages         DOUBLE,                  -- salaries & wages in AGI, USD (converted from source's $ thousands)
    any_suppressed  BOOLEAN NOT NULL,        -- true if any of n1/agi/n_wages/a_wages was an IRS '*'/'**' suppression marker
    loaded_at       TIMESTAMP NOT NULL DEFAULT current_timestamp,
    -- UNIQUE, not PRIMARY KEY: agi_stub is NULL for every legacy-year row
    -- (1998-2010, see GRAIN above), and DuckDB's PRIMARY KEY -- unlike
    -- UNIQUE -- silently requires every key column NOT NULL (verified live,
    -- 2026-09-22: an INSERT of a NULL agi_stub against a PRIMARY KEY on this
    -- column raised "NOT NULL constraint failed" despite agi_stub itself
    -- never being declared NOT NULL). The original draft assumed DuckDB
    -- treats PRIMARY KEY like UNIQUE for NULLs; it does not. UNIQUE gives
    -- the same "no duplicate row" intent for the modern-era rows while
    -- actually accepting the legacy rows' NULL agi_stub -- true dedup of the
    -- legacy (zip, tax_year, NULL) rows is by construction of
    -- irs_soi_history.py's legacy parser (one total row per zip per year,
    -- never repeated), not separately enforced here, same as before.
    UNIQUE (zip, tax_year, agi_stub)
);
