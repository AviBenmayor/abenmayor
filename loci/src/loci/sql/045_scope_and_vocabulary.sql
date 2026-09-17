-- ---------------------------------------------------------------------------
-- 045_scope_and_vocabulary.sql -- ONE borough vocabulary, and a screen the
-- database can enforce.
--
-- DRAFT. This file carries the `.sql.draft` suffix on purpose: `db.init_schema`
-- applies EVERY *.sql in src/loci/sql on EVERY session, and a shared warehouse
-- with a wave-two ingest running is not a place to land untested DDL by
-- accident. Rename to `045_scope_and_vocabulary.sql` only at the Phase B go.
--
-- ---------------------------------------------------------------------------
-- WHY (audit 2026-09-16, findings 4, 5 and 18)
-- ---------------------------------------------------------------------------
-- MN+BK is a PYTHON DEFAULT threaded through recommend.py:648,678,
-- dcp_housing.py:64, dob_permits.py:520, validation/sample.py:90,
-- revenue.py:1835 and listings.py:745. NOTHING IN THE SCHEMA ENFORCES IT, and
-- validation/retrodiction.py:486 proved the consequence: a vacancy narrative
-- that silently spanned five boroughs because one query forgot the predicate a
-- sibling query 800 lines away remembered.
--
-- Borough is also encoded TWO WAYS with no FK -- 'MN'/'BK' across the address
-- family, 'Manhattan'/'Brooklyn' in analysis.poi_presence, analysis.hex and
-- chains.brand_location. Two vocabularies for one dimension is how a join
-- silently returns nothing.
--
-- ---------------------------------------------------------------------------
-- THE DISTINCTION THIS FILE TURNS ON, AND IT IS THE WHOLE DESIGN
-- ---------------------------------------------------------------------------
-- Owner's ruling (2026-09-16): enforce the scope in the schema on SCREEN and
-- REPORT tables; INGEST tables keep all five boroughs. Separately and
-- standing: "never ever ever limit data pulls".
--
-- Those two rules are not in tension, because SUPPLY IS NOT A SCREEN.
--
--   A SCREEN/REPORT table produces a number that lands in the deliverable --
--   a vacancy rate, a stage count, an opening forecast. A Queens row in one of
--   those is a WRONG NUMBER. These get a CHECK (borough IN ('MN','BK')) or a
--   `_screen` view, and they are listed below.
--
--   A SUPPLY/CONTEXT table answers "what is near this address". Reach is
--   SPATIAL and crosses borough lines: a pharmacy 200 m from a Bushwick
--   address may sit in Queens, and an operator does not care. FILTERING SUPPLY
--   BY BOROUGH WOULD DELETE THAT PHARMACY AND MANUFACTURE A GAP -- the exact
--   "data gap wearing a costume" this project exists to avoid. So
--   analysis.poi_presence, chains.brand_location, analysis.licence_interval
--   and staging.alcohol_licences keep all five boroughs AND get no screen
--   filter. The audit's own note that "most readers are saved incidentally by
--   a <=500 m spatial filter" describes the correct behaviour, not a lucky
--   escape.
--
-- A `scope` COLUMN IS NOT STORED. The brief offered "a `scope` column plus a
-- view"; a stored column whose every value is `borough IN ('MN','BK')` is a
-- duplicated measure of exactly the kind D61 removed and the audit flags again
-- under "Duplicated measures, not views". The `_screen` views below compute it.
-- One measure, one home.
--
-- CAVEAT THE DATABASE CANNOT ENFORCE: a NULL borough is NOT out of scope, it is
-- UNKNOWN. analysis.storefront_pipeline has 17,532 NULL-borough rows and
-- analysis.poi_presence 63,872. The `_screen` views below KEEP the NULLs and
-- flag them, because dropping an unknown is indistinguishable from asserting
-- it is in Queens, and a screen that quietly discards 17,532 rows is worse
-- than one that reports them.
-- ---------------------------------------------------------------------------


-- ------------------------------------------------- the one borough vocabulary
-- The crosswalk both spellings resolve through. Five rows, seeded here, never
-- ingested: NYC's boroughs are not a feed.
--
-- `in_screen` is the scope itself, in data rather than in a Python tuple, so a
-- SQL consumer can ask the question without importing
-- sources/cities/nyc/addresses.SCREEN_BOROUGHS. The Python constant stays the
-- authority for CODE (it is NYC-specific and `model/`/`score/` take the scope
-- as an argument so they name no borough); this table mirrors it for SQL, and
-- tests/test_warehouse_scope.py pins the two together so they cannot drift.
CREATE TABLE IF NOT EXISTS analysis.borough (
    borough_code  VARCHAR PRIMARY KEY,   -- 'MN'; the project's canonical form
    borough_name  VARCHAR NOT NULL,      -- 'Manhattan'; the source spelling
    borocode      VARCHAR NOT NULL,      -- '1'; PLUTO/BBL leading digit
    county_fips   VARCHAR NOT NULL,      -- '061'; ACS/LODES geography
    in_screen     BOOLEAN NOT NULL       -- D48/D78: the MN+BK screen
);

DELETE FROM analysis.borough;
INSERT INTO analysis.borough
       (borough_code, borough_name, borocode, county_fips, in_screen) VALUES
    ('MN', 'Manhattan',     '1', '061', TRUE),
    ('BX', 'Bronx',         '2', '005', FALSE),
    ('BK', 'Brooklyn',      '3', '047', TRUE),
    ('QN', 'Queens',        '4', '081', FALSE),
    ('SI', 'Staten Island', '5', '085', FALSE);


-- --------------------------------------------------------- the screen views
-- What a report or a narrative reads. Each is `WHERE borough IN ('MN','BK')`
-- plus the NULL-borough rows, kept and labelled.
--
-- `scope` is COMPUTED here, never stored (see the header).

CREATE OR REPLACE VIEW analysis.storefront_screen AS
SELECT s.*,
       CASE WHEN s.borough IS NULL THEN 'unknown' ELSE 'screen' END AS scope
FROM analysis.storefront s
WHERE s.borough IN ('MN', 'BK') OR s.borough IS NULL;

CREATE OR REPLACE VIEW analysis.storefront_pipeline_screen AS
SELECT p.*,
       CASE WHEN p.borough IS NULL THEN 'unknown' ELSE 'screen' END AS scope
FROM analysis.storefront_pipeline p
WHERE p.borough IN ('MN', 'BK') OR p.borough IS NULL;

CREATE OR REPLACE VIEW staging.storefront_filing_screen AS
SELECT f.*,
       CASE WHEN f.borough IS NULL THEN 'unknown' ELSE 'screen' END AS scope
FROM staging.storefront_filing f
WHERE f.borough IN ('MN', 'BK') OR f.borough IS NULL;


-- ------------------------------------------------- analysis.storefront_year
-- ONE ROW PER (premises_id, reporting_year). Audit finding 1.
--
-- analysis.storefront's key is (storefront_id, filing_due_date) and is CLEAN at
-- 414,884 rows. The defect is not the table, it is every consumer that groups
-- by `reporting_year`: DOF files TWICE in some years -- a `full` annual filing
-- and a `vacant_only` supplement -- and pooling them leaves 5,534 duplicate
-- groups / 6,354 excess rows (1.5% high on counts) and a FAR worse error on
-- rates. Measured on the live file 2026-09-16:
--
--   year  full rows / vacant   vacant_only rows / vacant   pooled rate  true rate
--   2023  62,923 / 5,552       2,496 / 2,496               12.30%       8.82%
--   2024  62,128 / 5,388       4,540 / 2,320               12.02%       8.67%
--   2025  (none)               4,459 / 2,284               51.22%       n/a
--
-- The pooled 2023 number is not noise, it is 3.5 points of invented vacancy,
-- and it looks entirely plausible. `model/storefronts.snapshot_filing` and
-- `analysis.storefront_latest` already apply the right rule for their own
-- questions; this view is that rule for the BY-YEAR question, so the three
-- consumers finally read the same rows.
--
-- THE RULE: within a (premises_id, reporting_year), the `full` filing wins;
-- where only a supplement exists, it is used and `universe` says so. A
-- 2025-style supplement-only year has a NUMERATOR WITH NO DENOMINATOR -- read
-- `universe = 'vacant_only'` and refuse to compute a rate. The view cannot stop
-- you; it can only label it.
--
-- Keyed on premises_id, not storefront_id: storefront_id RENUMBERS between
-- filings (sql/012's identity block), so any longitudinal question is
-- premises-level by construction. NOTE premises_id = BBL || '|' || unit, so two
-- units in one building are two premises, not one -- that is the point, and it
-- is why the fusion bug sql/012 describes does not recur here.
--
-- NO `observed_1231 IS NOT NULL` FILTER, and this is deliberate.
-- analysis.storefront_latest (sql/012:338) carries one, because its question is
-- "when last OBSERVED on a 12/31, was this premises vacant?". Copying it here
-- would drop 702 MN+BK premises-years (122,844 instead of 123,546) whose only
-- filing reports 6/30 -- measured 2026-09-16. Dropping a premises-year because
-- the landlord filed in August is an ELIGIBILITY GATE, and the standing rule
-- (owner, 2026-09-13) is that there is no eligibility gate: the row exists and
-- states its absence.
--
-- The consequence, and a reader MUST handle it: `vacant` is `bool_or(
-- vacant_1231)` and is NULL when the picked filing carries no 12/31
-- observation. NULL is NOT FALSE. `observed_1231` is exposed so the two are
-- distinguishable -- "observed, not vacant" and "never observed" are different
-- facts and a COALESCE to FALSE would merge them into a fake occupancy.
-- The full filing still wins wherever one exists: ARG_MAX orders on
-- (universe = 'full', filing_due_date), so a 6/30 supplement is only ever
-- picked when it is the only filing for that premises-year.
CREATE OR REPLACE VIEW analysis.storefront_year AS
WITH pick AS (
    SELECT premises_id,
           reporting_year,
           ARG_MAX(filing_due_date, (universe = 'full', filing_due_date))
               AS filing_due_date
    FROM analysis.storefront
    GROUP BY premises_id, reporting_year
)
SELECT s.premises_id,
       s.reporting_year,
       s.filing_due_date,
       any_value(s.universe)                                  AS universe,
       any_value(s.observed_1231)                             AS observed_1231,
       any_value(s.borough)                                   AS borough,
       any_value(s.bbl)                                       AS bbl,
       any_value(s.nta_code)                                  AS nta_code,
       -- canonical, never raw: a by-year panel spans DOF's 2024 recode
       -- (sql/012_activity_recode.yaml), and the raw label is wrong by a
       -- factor of twelve across that boundary.
       any_value(s.activity_canonical)                        AS activity_canonical,
       avg(ST_X(s.geom))                                      AS lon,
       avg(ST_Y(s.geom))                                      AS lat,
       bool_or(s.vacant_1231)                                 AS vacant,
       bool_or(COALESCE(s.construction_reported, FALSE))      AS constr,
       count(*)                                               AS n_storefronts
FROM analysis.storefront s
JOIN pick p
  ON p.premises_id     = s.premises_id
 AND p.reporting_year  = s.reporting_year
 AND p.filing_due_date = s.filing_due_date
GROUP BY s.premises_id, s.reporting_year, s.filing_due_date;
