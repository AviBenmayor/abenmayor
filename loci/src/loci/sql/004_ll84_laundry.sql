-- ---------------------------------------------------------------------------
-- 004_ll84_laundry.sql -- in-building laundry as SUPPLY, keyed by BBL (D51(d)).
--
-- Owner decision D51(d): in-building laundry is a laundry-category supply
-- input. The only MEASURED address-level source that exists for it is the
-- LL84/LL133 energy-benchmarking disclosure, where ENERGY STAR Portfolio
-- Manager asks multifamily filers for two integers:
--
--   "Multifamily Housing - Number of Laundry Hookups in Common Area(s)"  -> a laundry room
--   "Multifamily Housing - Number of Laundry Hookups in All Units"       -> in-unit W/D
--
-- Both are republished by NYC keyed to BBL (+BIN) across eight annual Socrata
-- datasets, 2013-2024. See sources/cities/nyc/ll84_laundry.py for the field
-- resolution and the reason it MUST be by human-readable name.
--
-- NOTHING IN score/ OR model/ READS THESE TABLES. Adopting in-building laundry
-- as supply changes gap_score, and that is an owner decision, not this file's.
-- This lands the measurement so the decision can be made on numbers.
--
-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. "Hookups" is PLUMBING, not machines, and not usage. A common-area count
--    says the room is plumbed. An in-unit count says the units are plumbed,
--    not that tenants own washers. NYCHVS measures ownership; the two
--    quantities are different and must never be pooled.
-- 2. LL84 is a >25,000 sq ft law. It structurally cannot see the walk-ups that
--    dominate the laundry gap ranking -- 65 of 58,182 <6-unit laundry-lead
--    addresses match. A blank here is "not covered by the law", not "no
--    laundry", which is why `laundry_measured` is a first-class column rather
--    than a NULL to be guessed at.
-- 3. Self-reported and NON-RANDOMLY blank. Thousands of matched lots file an
--    LL84 record with the amenity fields empty. Owners who skip amenity fields
--    are not a random sample of owners.
-- 4. `latest non-null wins` is right for a durable installation and wrong for a
--    decommissioned laundry room. `n_vintages_disagree` exposes exactly the
--    rows where that choice is load-bearing; it is not noise, it is the set of
--    buildings whose answer changed.
-- 5. Multi-BBL campus filings are EXPLODED (one filing -> every BBL it lists),
--    so a NYCHA or Mitchell-Lama campus attributes its laundry room to every
--    lot in the campus. That over-attributes as surely as keeping only the
--    first BBL under-attributes; `bbl_multi` marks every such row.
-- ---------------------------------------------------------------------------

-- One row per BBL x filing vintage. Vintage is the LL84 REPORT year (the
-- calendar year the energy data covers + 1), taken from `Year Ending`.
-- Where one lot carries several filings in one vintage (several property_ids
-- on one tax lot), the hookup counts are collapsed with max() -- an
-- affirmative answer from any filing on the lot beats a 0 or a blank -- and
-- `n_filings` records that the collapse happened.
CREATE TABLE IF NOT EXISTS staging.ll84_laundry (
    bbl                  VARCHAR  NOT NULL,   -- 10-digit zero-padded, borough+block(5)+lot(4)
    filed_year           SMALLINT NOT NULL,   -- LL84 report year
    dataset_id           VARCHAR  NOT NULL,   -- Socrata 4x4, provenance
    common_area_hookups  INTEGER,             -- NULL = "Not Available"; 0 is an affirmative NONE
    in_unit_hookups      INTEGER,             -- NULL = "Not Available"; 0 is an affirmative NONE
    units_reported       INTEGER,             -- self-reported residential living units
    n_filings            SMALLINT NOT NULL,   -- filings collapsed into this row (>1 = multi-property lot)
    any_multi_bbl        BOOLEAN  NOT NULL,   -- any contributing filing listed several BBLs
    ingested_at          TIMESTAMP NOT NULL,
    PRIMARY KEY (bbl, filed_year)
);

-- One row per BBL, pooled across vintages. LATEST NON-NULL ANSWER WINS, per
-- field independently: a building that answered common-area in 2024 and
-- in-unit only in 2018 keeps both answers, from their own vintages.
CREATE TABLE IF NOT EXISTS analysis.address_laundry (
    bbl                  VARCHAR  NOT NULL,
    has_common_laundry   BOOLEAN,             -- NULL = never answered this field
    has_in_unit_laundry  BOOLEAN,             -- NULL = never answered this field
    laundry_measured     BOOLEAN  NOT NULL,   -- at least one non-null answer, either field
    latest_vintage       SMALLINT,            -- vintage the winning answer came from
    n_vintages           SMALLINT NOT NULL,   -- vintages this BBL appears in at all
    n_vintages_disagree  SMALLINT NOT NULL,   -- vintages whose yes/no verdict differs from the winner
    common_area_hookups  INTEGER,             -- winning vintage's raw count
    in_unit_hookups      INTEGER,
    units_reported       INTEGER,             -- latest non-null
    any_multi_bbl        BOOLEAN  NOT NULL,
    built_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (bbl)
);

-- Join to the address screen. Kept as its own VIEW rather than columns on
-- analysis.address_gaps: address_gaps is rebuilt by `loci address-gaps` and
-- adding columns there would couple an owner-undecided supply input to the
-- scored table. `laundry_status` is the four-way answer the screen needs.
CREATE OR REPLACE VIEW analysis.address_laundry_gaps AS
SELECT
    g.address_id,
    g.bbl,
    g.borough,
    g.units,
    g.eligible,
    g.gap_score,
    g.lead_category,
    g.laundry_ratio,
    l.has_common_laundry,
    l.has_in_unit_laundry,
    l.laundry_measured,
    l.latest_vintage,
    l.n_vintages_disagree,
    l.units_reported                          AS ll84_units_reported,
    CASE
        WHEN l.bbl IS NULL                             THEN 'no_ll84_record'
        WHEN NOT l.laundry_measured                    THEN 'll84_blank'
        WHEN l.has_common_laundry OR l.has_in_unit_laundry THEN 'has_laundry'
        ELSE 'no_laundry'
    END                                       AS laundry_status
FROM analysis.address_gaps g
LEFT JOIN analysis.address_laundry l ON l.bbl = g.bbl;
