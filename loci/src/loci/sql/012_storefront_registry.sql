-- ---------------------------------------------------------------------------
-- 012_storefront_registry.sql -- the storefront-vacancy layer: which specific
-- ground floors near a gap address are empty, and whether the lease is up.
--
-- Owner's ask (2026-09-10): turn "this block is missing a bodega" into "and
-- this specific ground floor nearby is vacant, with its lease expired." The
-- gap screen says a category is absent within reach; it has never said where
-- the operator could actually put one. That is a SUPPLY-OF-SPACE question,
-- and NYC has exactly one citywide register of it.
--
-- SOURCE  NYC Department of Finance, "Storefronts Reported Vacant or Not",
--         Socrata `92iy-9c3n`, the Local Law 157 of 2019 registry. Owners of
--         property with ground-floor or second-floor commercial premises file
--         a registration statement with DOF; the file is the union of every
--         statement filed. 414,884 rows citywide, 11 filings, 2020-08-15
--         through 2026-02-15. Verified against /api/views/ on 2026-09-10.
--
-- ---------------------------------------------------------------------------
-- WHY THIS IS A NEW TABLE AND NOT A COLUMN SET (D61 inventory rule)
-- ---------------------------------------------------------------------------
-- `duckdb_tables()` before writing this file: 23 tables + 3 views = 26
-- objects. Nothing anywhere in the warehouse holds a vacancy, a lease, or a
-- commercial premises. staging.poi is the opposite universe -- it records
-- businesses that EXIST; this records the ground floors where one does not.
-- analysis.dev_pipeline is residential units, at DOB-job grain.
--
-- analysis.storefront is ONE ROW PER STOREFRONT PER FILING. That is a
-- genuinely new grain: a storefront is not a lot (one BBL carries up to 30 of
-- them), not an address (a gap address is a RESIDENTIAL lot), and not a
-- category. It cannot be expressed as a pivot or a subset of any existing
-- table, so D61's "pivots and subsets become views" does not apply.
--
-- The MEASURES derived from it -- how many vacant storefronts sit within a
-- walk of an address -- are address-grain, so they EXTEND analysis.address by
-- `UPDATE ... SET <STOREFRONT_COLUMNS>` (model/storefronts.py), exactly the
-- way model/dev_pipeline.py does. No second address table, no derived
-- per-storefront table: `latest_year`, `vacant_latest`,
-- `consecutive_vacant_years` and `lease_expired` are a VIEW
-- (analysis.storefront_latest, below) and a query, never stored rows.
--
-- ---------------------------------------------------------------------------
-- WHY ONE ROW PER FILING AND NOT ONE ROW PER STOREFRONT
-- ---------------------------------------------------------------------------
-- Because DOF ASSIGNS NO STOREFRONT IDENTIFIER, and the obvious keys fuse
-- distinct storefronts. Measured on the real file, 2026-09-10:
--
--     key                            distinct    rows that are not the
--                                    values      first of their key WITHIN
--                                                a single filing
--     BBL + unit                       50,829     217,576  (52.4%)
--     BBL + street address + unit     101,669     153,483  (37.0%)
--     BBL + number + street + unit     74,797     206,685  (49.8%)
--
-- Those "duplicates" are NOT duplicates. 350 EAST 54 STREET unit COM1 files
-- four rows in every filing -- two FOOD SERVICES and two OTHER -- because the
-- premises holds four storefronts and DOF's form has no field to tell them
-- apart. `unit` is blank on 87% of rows citywide. Collapsing on any of these
-- keys would fuse four real storefronts into one and, downstream, turn three
-- occupied ground floors into nothing at all -- the dedup-fusing-distinct-
-- storefronts bug CLAUDE.md names, in its natural habitat.
--
-- So the ingest is LOSSLESS at filing grain: one output row per source row,
-- no collapsing, ever. Identity is asserted only where the source supports it:
--
--     premises_id   = BBL || '|' || upper(trim(unit))        STABLE across
--                     filings. This is the addressable premises.
--     storefront_id = premises_id || '#' || seq              where seq is the
--                     row's deterministic ordinal within (premises_id,
--                     filing_due_date), ordered by primary_business_activity,
--                     lease_expiry, address, then source row order.
--
-- CAVEAT THE DATABASE CANNOT ENFORCE: `storefront_id` IS NOT STABLE ACROSS
-- FILINGS. A premises reporting four storefronts in 2023 and three in 2024
-- renumbers. Longitudinal questions -- "vacant in consecutive years" -- are
-- PREMISES-level (count vacant rows per premises_id per year), never
-- storefront_id-level. analysis.storefront_latest keys on premises_id for
-- exactly this reason.
--
-- ---------------------------------------------------------------------------
-- DEDUP RULE FOR DUPLICATE FILINGS IN THE SAME YEAR
-- ---------------------------------------------------------------------------
-- NONE IS APPLIED, AND THE REASON IS THE POINT. Two byte-identical rows in one
-- filing (20,338 groups, 50,970 rows citywide) are indistinguishable from two
-- identical storefronts, and the source cannot tell us which they are. The
-- table keeps both, and the address measures therefore count STOREFRONTS AS
-- FILED -- which is what Local Law 157 asks the owner to report. Where a
-- consumer wants the conservative reading, `COUNT(DISTINCT premises_id)`
-- gives premises rather than storefronts; the live run reported both.
--
-- What IS deduplicated is the FILING dimension: (storefront_id,
-- filing_due_date) is the primary key, so re-ingesting the same download
-- twice replaces rows instead of doubling them, and the borough-scoped
-- DELETE-then-INSERT in sources/.../storefront_registry.py makes a re-run
-- idempotent.
--
-- ---------------------------------------------------------------------------
-- THE FILING CALENDAR -- AND THE TRAP IN IT
-- ---------------------------------------------------------------------------
-- `Reporting Year` is a TEXT LABEL, not a year: its values are
-- '2019 and 2020', '2020 and 2021', '2021 and 2022', '2022 and 2023', '2023',
-- '2024', '2025'. The real key is `Filing Due Date`, and there are TWO KINDS
-- OF FILING in this one file:
--
--   due          label            rows      universe      observations
--   ----------   --------------   -------   -----------   ---------------------
--   2020-08-15   2019 and 2020    75,250    FULL          12/31/2019 + 6/30/2020
--   2021-08-15   2020 and 2021    75,540    FULL          12/31/2020 + 6/30/2021
--   2022-08-15   2021 and 2022    63,456    FULL          12/31/2021 + 6/30/2022
--   2023-08-15   2022 and 2023    64,092    FULL          12/31/2022 + 6/30/2023
--   2024-02-15   2023             2,496     VACANT ONLY   12/31/2023
--   2024-06-03   2023             62,923    FULL          12/31/2023
--   2024-08-15   2024             2,220     VACANT ONLY   6/30/2024
--   2025-02-15   2024             2,320     VACANT ONLY   12/31/2024
--   2025-06-03   2024             62,128    FULL          12/31/2024
--   2025-08-15   2025             2,175     VACANT ONLY   6/30/2025
--   2026-02-15   2025             2,284     VACANT ONLY   12/31/2025
--
-- THE TRAP: five of the eleven filings contain ONLY storefronts reported
-- vacant. Pool them with the full filings and the 2025 vacancy rate reads
-- 100%. `universe` carries the distinction and is DERIVED FROM THE DATA (a
-- filing with no reported-not-vacant row is 'vacant_only'), not hard-coded, so
-- a 2027 filing classifies itself.
--
-- The observation dates are derived the same way, per filing:
--     observed_1231 = make_date(year(filing_due) - 1, 12, 31)  when the filing
--                     reports the 12/31 field at all, else NULL
--     observed_0630 = make_date(year(filing_due),      6, 30)  when the filing
--                     reports the 6/30 field at all, else NULL
--     reporting_year = year(COALESCE(observed_1231, observed_0630))
-- Verified against every label above: 2020-08-15 -> 12/31/2019 + 6/30/2020,
-- label "2019 and 2020"; 2024-08-15 -> 6/30/2024 only, label "2024".
--
-- `vacant_6_30_or_date_sold` LOOKS like a mixed date/flag field. IT IS NOT, in
-- any released row: its only non-null value in all 414,884 rows is the literal
-- 'YES'. The sale date lives in its own `Sold Date` column. Both are ingested
-- separately and neither is coerced into the other.
--
-- ---------------------------------------------------------------------------
-- FIELD VOCABULARIES (exhaustive, citywide, 2026-09-10)
-- ---------------------------------------------------------------------------
--   vacant_on_12_31           NO 364,155 · YES 43,978 · NULL 4,431 · Y 2,320
--   vacant_6_30_or_date_sold  YES 15,286 · NULL 399,598
--   construction_reported     NULL 402,502 · N 5,397 · NO 5,275 · YES 1,527 · Y 183
-- The Y/YES and N/NO split is a form change between filings, not two meanings.
-- Parsed to BOOLEAN: {YES,Y} -> TRUE, {NO,N} -> FALSE, anything else -> NULL.
-- NULL is kept as NULL and never read as FALSE: on a vacant-only filing a NULL
-- 12/31 flag means "this filing did not ask", not "not vacant".
--
-- ---------------------------------------------------------------------------
-- GEOMETRY
-- ---------------------------------------------------------------------------
-- `geom` is POINT in EPSG:4326 BY CONVENTION -- DuckDB GEOMETRY carries no
-- SRID and will not catch a violation (loci/db.py). ST_Point(lon, lat), (x, y)
-- order. Every metric operation downstream is NETWORK distance on the walk
-- graph, never a planar-degree calculation.
--
-- POISON VALUE: 4,780 MN+BK rows carry latitude AND longitude of literal 0 --
-- a single point in the Gulf of Guinea, 8,600 km from Brooklyn. Nulled, never
-- ingested as a coordinate. Coordinates outside the five-borough bounding box
-- are nulled the same way.
--
-- FALLBACK CHAIN, recorded in `geom_source`:
--   'filing'          the row's own valid coordinate (99.94% of the 2025-06-03
--                     snapshot; 96.2% of all MN+BK rows)
--   'premises_carry'  a valid coordinate reported for the SAME premises_id in
--                     another filing (a premises has one distinct coordinate in
--                     28,659 of 31,797 MN+BK cases; where it has several the
--                     most recent filing's wins). This rescues almost all of
--                     the 2020-08-15 filing, which was geocoded later.
--   'pluto_lot'       the PLUTO tax-lot centroid for the BBL. Rescues only 3
--                     MN+BK rows and is kept only because it costs nothing:
--                     12.3% of MN+BK filings sit on CONDO unit BBLs (…1101,
--                     …1201) that PLUTO records under the billing lot, so a
--                     BBL join to PLUTO misses them by construction.
--   NULL              no coordinate anywhere. Kept in the table, dropped from
--                     the spatial measures EXPLICITLY and counted in the run
--                     report, never lost silently.
--
-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. SELF-REPORTED, AND NON-FILING IS INVISIBLE. Every field is the property
--    owner's own statement. A landlord who does not file does not appear as
--    vacant -- they do not appear at all. There is no non-response flag, so
--    "no vacant storefront within 400 m" and "nobody near here filed" are the
--    same observation. `storefronts_400m` is the denominator that makes the
--    difference readable; a rate over a tiny denominator is not a rate.
-- 2. TAX CLASS 1 IS ESSENTIALLY ABSENT. Joined to PLUTO `bldgclass`, only 679
--    of 253,519 MN+BK filings (0.27%) sit on a 1-3 family building -- 29 on
--    class A/B, 650 on C0-C3. LL157 targets larger commercial premises and
--    small owner-occupied buildings largely do not file. The corner store in
--    the base of a Brooklyn rowhouse is under-covered, and that is exactly the
--    typology a bodega gap sits in.
-- 3. ANNUAL SNAPSHOT, NOT A LIVE LISTING. The measure's default as-of is
--    2024-12-31 -- the latest FULL-universe observation, published 2025-06-03.
--    A storefront vacant on that date may have been leased eighteen months
--    ago. This layer sizes and locates vacancy; it does not price or confirm
--    availability. There is NO RENT FIELD anywhere in this dataset, and no
--    square footage.
-- 4. WHY 2024-12-31 AND NOT 2025-12-31. The 2026-02-15 filing is fresher but
--    is vacant-only (1,669 MN+BK rows) and clearly under-filed against the
--    5,388 citywide vacancies of a year earlier. Using it would give a
--    numerator with no denominator and a 60% undercount. It IS ingested and
--    queryable; it is simply not the snapshot the address measures run on.
--    `--asof` selects a different observation date.
-- 5. LEASE EXPIRY IS NOT AVAILABILITY, AND IT IS SPARSE WHERE IT MATTERS.
--    `expir_dt_of_most_recent_lease` first appears in the 2024-06-03 filing
--    (38,785 of 38,866 MN+BK rows) and DOF then STOPPED publishing it on the
--    annual file: the 2025-06-03 filing carries it on 71 of 38,318 rows.
--    The vacant-only supplements do carry it (54% fill). Consequence:
--    `nearest_vacant_lease_expired` is NULL for most addresses on the default
--    2024-12-31 snapshot, and `--asof 2023-12-31` is the lease-complete view.
--    A lease that has expired does not mean the space is on the market; a
--    lease running to 2032 does not mean the tenant is still trading.
--    Out-of-range values (before 1990 or after 2100 -- the file contains a
--    literal 1969-01-01) are DROPPED, never clamped: clamping a typo to today
--    would invent an expiry.
-- 6. CONSTRUCTION_REPORTED ROWS ARE VACANCY OF A DIFFERENT KIND. 1,710
--    citywide rows report construction. A ground floor empty because it is
--    being gut-renovated is not a leasable storefront this quarter. The flag
--    is ingested and is NOT excluded from the counts (an owner reporting both
--    vacant and under-construction has reported a vacancy); a consumer who
--    wants leasable-now must filter `construction_reported IS NOT TRUE`.
-- 7. STOREFRONT COUNTS ARE AS FILED. See the dedup-rule block above: identical
--    rows are kept because they are indistinguishable from identical
--    storefronts. Counts are therefore an upper bound on premises and a
--    faithful reading of the filings.
-- 7b. `primary_business_activity` ON A VACANT ROW IS NOT THE LAST TENANT. It
--    records the CURRENT activity, so a vacant storefront necessarily reports
--    'NO BUSINESS ACTIVITY IDENTIFIED' -- 3,770 of the 3,807 MN+BK vacancies
--    on 2024-12-31 do. `nearest_vacant_storefront_business` therefore carries
--    that constant for almost every address, and it is stored that way ON
--    PURPOSE: the row's own value, never a guess.
--    The PRIOR USE is recoverable at PREMISES level, and 2,314 of the 2,751
--    vacant MN+BK premises (84%) have one. It is a QUERY, not a column (D61),
--    and it is premises-level because storefront_id renumbers:
--
--      WITH v AS (SELECT DISTINCT premises_id FROM analysis.storefront
--                 WHERE filing_due_date = DATE '2025-06-03' AND vacant_1231)
--      SELECT s.premises_id,
--             ARG_MAX(s.primary_business_activity, s.filing_due_date) AS last_use
--      FROM analysis.storefront s JOIN v USING (premises_id)
--      WHERE s.primary_business_activity NOT IN ('NO BUSINESS ACTIVITY IDENTIFIED',
--                                                'NO BUSINESS ACTIVITY REPORTED')
--      GROUP BY 1;
--
--    Read it as "what this PREMISES last housed", not "what this storefront
--    last housed": a premises with four storefronts returns one answer for all
--    four, and pretending otherwise would be the fusion bug in a coalesce.
-- 8. A STOREFRONT IS NOT A CATEGORY. `primary_business_activity` has 19 values,
--    the widest being RETAIL (108,179) and FOOD SERVICES (55,446). It does NOT
--    map to the project's 15 categories and no mapping is attempted here: a
--    vacant storefront whose last use was RETAIL tells an operator the space
--    is retail-zoned ground floor, not that it was a pharmacy.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.storefront (
    storefront_id    VARCHAR NOT NULL,  -- premises_id || '#' || seq; NOT stable across filings
    premises_id      VARCHAR NOT NULL,  -- BBL || '|' || unit; STABLE across filings
    filing_due_date  DATE    NOT NULL,  -- the reporting event; the real key, not the label
    reporting_year   INTEGER NOT NULL,  -- year of COALESCE(observed_1231, observed_0630)
    reporting_period VARCHAR,           -- DOF's raw label, verbatim ('2019 and 2020')
    universe         VARCHAR NOT NULL,  -- 'full' | 'vacant_only'; derived, not hard-coded
    observed_1231    DATE,              -- the 12/31 vacant_1231 refers to
    observed_0630    DATE,              -- the 6/30  vacant_0630 refers to
    bbl              VARCHAR,
    bin              VARCHAR,
    borough          VARCHAR NOT NULL,  -- MN/BX/BK/QN/SI, matching analysis.address
    address          VARCHAR,           -- DOF's storefront address, verbatim
    street_number    VARCHAR,
    street_name      VARCHAR,
    unit             VARCHAR,
    zip              VARCHAR,
    nta_code         VARCHAR,           -- DOF's own NTA, not re-derived
    census_tract     VARCHAR,
    geom             GEOMETRY,          -- POINT, EPSG:4326 BY CONVENTION (no SRID in DuckDB)
    geom_source      VARCHAR,           -- 'filing'|'premises_carry'|'pluto_lot'|NULL
    vacant_1231      BOOLEAN,           -- NULL means the filing did not ask
    vacant_0630      BOOLEAN,
    construction_reported BOOLEAN,
    primary_business_activity VARCHAR,  -- DOF's 19-value vocabulary, verbatim
    -- The SAME label with DOF's 2024 recode undone and the HEALTH CARE or/OR
    -- case split normalised. DERIVED, never filed. Read THIS for any question
    -- that spans 2024-06-03; read the raw column above to quote what the
    -- landlord actually submitted. sql/012_activity_recode.yaml holds the
    -- crosswalk and its caveats; sql/041 ALTERs this column onto a warehouse
    -- that predates it, which is why every INSERT into this table names its
    -- columns rather than relying on their order.
    activity_canonical VARCHAR,
    lease_expiry     DATE,              -- most recent lease's expiry; sparse, see caveat 5
    sold_date        DATE,
    source           VARCHAR NOT NULL,  -- 'nyc_dof_storefront_registry'
    source_vintage   VARCHAR,           -- Socrata rowsUpdatedAt, ISO date
    provenance       VARCHAR,           -- dataset id + vintage + as-of, one string
    ingested_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (storefront_id, filing_due_date)
);

-- ---------------------------------------------------------------------------
-- The per-premises derived view. NOT a table (D61): every column here is a
-- window function over analysis.storefront and storing it would be a second
-- object saying nothing new.
--
--   latest_year               most recent reporting_year with a 12/31 observation
--   vacant_latest             any storefront at the premises vacant on that 12/31
--   consecutive_vacant_years  length of the unbroken run of 12/31 observations,
--                             counting back from latest_year, in which at least
--                             one storefront was vacant. A premises that skipped
--                             a year does not silently extend its run: the run
--                             stops at the first observed year that is not
--                             vacant OR is not observed at all.
--
-- ONE FILING PER (premises, year). Two filings can observe the same 12/31 -- the
-- 2025-06-03 annual and the 2025-02-15 supplement both observe 2024-12-31 --
-- and pooling them inflates `storefronts_latest` for every premises that filed
-- both. The FULL filing wins where one exists, exactly as
-- model/storefronts.snapshot_filing does for the address measures, so the two
-- consumers read the same rows.
--
-- CAVEAT: `vacant_latest` here is per-premises latest, which for many premises
-- is the 2025-12-31 supplement rather than the 2024-12-31 annual filing. It
-- answers "when last observed, was this premises vacant?" -- a DIFFERENT
-- question from the address measures' fixed snapshot, and it has no common
-- denominator. Do not divide one by the other.
--   lease_expired             the premises' latest reported lease expiry is in
--                             the past as of CURRENT_DATE. NULL when no lease
--                             was ever reported -- never FALSE.
--
-- Keyed on premises_id, not storefront_id, because storefront_id renumbers
-- between filings (see the identity block above).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW analysis.storefront_latest AS
WITH pick AS (
    -- one filing per (premises, year): the FULL one where it exists.
    SELECT premises_id, reporting_year,
           ARG_MAX(filing_due_date, (universe = 'full', filing_due_date)) AS filing_due_date
    FROM analysis.storefront
    WHERE observed_1231 IS NOT NULL
    GROUP BY premises_id, reporting_year
), obs AS (
    SELECT premises_id, borough,
           reporting_year AS yr,
           MAX(CASE WHEN vacant_1231 THEN 1 ELSE 0 END) AS any_vacant,
           COUNT(*)                                     AS storefronts,
           MAX(lease_expiry)                            AS lease_expiry,
           MAX(filing_due_date)                         AS filing_due_date,
           ANY_VALUE(address)                           AS address,
           ANY_VALUE(nta_code)                          AS nta_code
    FROM analysis.storefront
    JOIN pick USING (premises_id, reporting_year, filing_due_date)
    GROUP BY premises_id, borough, reporting_year
), ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY premises_id ORDER BY yr DESC) AS r,
           MAX(yr)      OVER (PARTITION BY premises_id)                  AS latest_year
    FROM obs
), runs AS (
    -- A year participates in the run only if it is contiguous with latest_year
    -- (yr = latest_year - (r - 1)) AND vacant. The first failure ends it.
    SELECT premises_id,
           MIN(CASE WHEN any_vacant = 0 OR yr <> latest_year - (r - 1) THEN r END) AS stop_at
    FROM ranked GROUP BY premises_id
)
SELECT l.premises_id,
       l.borough,
       l.address,
       l.nta_code,
       l.latest_year,
       l.filing_due_date              AS latest_filing_due_date,
       l.storefronts                  AS storefronts_latest,
       l.any_vacant = 1               AS vacant_latest,
       COALESCE(runs.stop_at - 1,
                (SELECT COUNT(*) FROM ranked k WHERE k.premises_id = l.premises_id))
                                      AS consecutive_vacant_years,
       le.lease_expiry,
       CASE WHEN le.lease_expiry IS NULL THEN NULL
            ELSE le.lease_expiry < CURRENT_DATE END AS lease_expired
FROM ranked l
LEFT JOIN runs USING (premises_id)
LEFT JOIN (SELECT premises_id, MAX(lease_expiry) AS lease_expiry
           FROM analysis.storefront GROUP BY premises_id) le USING (premises_id)
WHERE l.r = 1;

-- ---------------------------------------------------------------------------
-- The address-grain extension. Seven columns on analysis.address, written ONLY
-- by `UPDATE ... SET` from model/storefronts.STOREFRONT_COLUMNS, which a
-- pinned test asserts is disjoint from the screen's own columns, from D62's
-- PIPELINE_COLUMNS and from D63's age_fit columns. Nothing here can move
-- gap_score, lead_category, n_missing or eligible: a block with an empty
-- ground floor does not become a gap, and a gap block with no vacancy does not
-- stop being one. Vacancy is an ACTIONABILITY annotation on a graded screen
-- (D48), not a filter.
--
-- The ALTER statements live at the TAIL OF 002_schema.sql, not here, and they
-- have to: db.init_schema() builds the generated VIEW analysis.address_gaps
-- immediately after 002 and before 003..012, so a column added in 012 would
-- not exist when the view naming it is created, and every connection would
-- raise BinderException. Same class of bug as D61's and D62's.
--
-- Distances are NETWORK metres on the walk graph (score/access.py `_prune` /
-- `_to_csr` -- the same engine the gap screen's nearest_m and the pipeline's
-- catchments come from), NOT straight-line. 400 m is THRESHOLDS[5], the
-- project's 5-minute tier.
-- ---------------------------------------------------------------------------
