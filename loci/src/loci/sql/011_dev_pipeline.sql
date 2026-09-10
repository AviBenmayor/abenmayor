-- ---------------------------------------------------------------------------
-- 011_dev_pipeline.sql -- the residential development pipeline: which addresses
-- are about to gain hundreds of neighbours, and which already did.
--
-- Owner's ask (2026-09-09): "build the pipeline layer with DOB permits and CO
-- dates". The operator question underneath it is a LEASE-TIMING question --
-- sign before the block fills -- so the layer has to carry both directions of
-- time: units permitted but not yet occupied (the next ~18 months) and units
-- that received a certificate of occupancy in the last 24/60 months (the
-- residents who have already arrived and are not yet in ACS).
--
-- ---------------------------------------------------------------------------
-- WHY THIS IS A NEW TABLE AND NOT A COLUMN SET (D61 inventory rule)
-- ---------------------------------------------------------------------------
-- `SHOW ALL TABLES` before writing this file: 26 objects, none of them at DOB
-- job grain, and nothing anywhere in the warehouse holding a permit or a CO.
-- (model/ignition.py's "198k geocoded DOB new-building filings" were never
-- persisted -- they lived in a scratchpad JSON, `NB_PATH`, in a session
-- directory that no longer exists. There is nothing to reuse.)
--
-- analysis.dev_pipeline is ONE ROW PER DOB JOB. That is a genuinely new grain:
-- a job is not an address, not a lot (one BBL can carry several jobs across
-- fifteen years), and not a category. It cannot be expressed as a pivot or a
-- subset of analysis.address / analysis.address_category, so D61's "pivots and
-- subsets become views" does not apply.
--
-- The MEASURES derived from it -- how many pipeline units sit within a walk of
-- an address -- are address-grain, so they EXTEND analysis.address by
-- `UPDATE ... SET <PIPELINE_COLUMNS>` (model/dev_pipeline.py), exactly the way
-- model/address_demand.py extends analysis.address_category. No second address
-- table. Provenance for the run is stamped once, on the parent's
-- `pipeline_asof` column.
--
-- ---------------------------------------------------------------------------
-- SOURCES AND THE DEDUP RULE
-- ---------------------------------------------------------------------------
-- SPINE  DCP Housing Database, Project-Level Files, `br6q-ssj3` (version 25Q4,
--        data as of 2026-01-21, published 2026-03-16, semiannual). One row per
--        DOB job that adds or removes Class A units since 2010-01-01, already
--        geocoded, QA'd and unit-recoded by City Planning. 109,076 rows,
--        109,076 DISTINCT job_number -- verified, so the spine cannot fan out.
--
-- FRESHNESS SUPPLEMENT
--        `bs8b-p36w`  DOB Certificate of Occupancy      (BIS jobs, 2012-07-)
--        `pkdm-hqz6`  DOB NOW: Certificate of Occupancy (DOB NOW jobs, 2021-03-)
--        Both refresh DAILY (rowsUpdatedAt 2026-09-09 when this was built).
--        DCP is up to eight months stale by the end of its release cycle: 436
--        MN+BK jobs carrying 11,407 net units are still "3. Permitted for
--        Construction" in 25Q4 but already have a CO issued after DCP's
--        2026-01-21 cutoff. On a lease-timing question that is the difference
--        between "coming" and "already here", so the CO feeds are joined in.
--
-- JOIN KEY  the DOB job number. DCP `job_number`, DOB CO `job_number`, DOB NOW
--        CO `job_filing_name` all carry the SAME two shapes -- a 9-digit BIS
--        number (`321590532`) or a DOB NOW number (`B00680917`, borough letter
--        + 8 digits) -- so one uppercased, whitespace-stripped string joins all
--        three. Verified: 11,361 of 13,543 completed MN+BK jobs match a CO row.
--
-- DEDUP RULE  A JOB HAS MANY CO ROWS AND THEY MUST NEVER BE SUMMED.
--        A single building generates an initial TCO plus a renewal every 90
--        days until the final CO: 24,579 of pkdm-hqz6's rows are
--        "Renewal Without Change". The same physical CO can also appear in BOTH
--        feeds (65,677 of pkdm-hqz6's rows carry BIS-shaped job numbers).
--        Therefore the two feeds are UNIONed and then collapsed to ONE ROW PER
--        job_number by min()/max() BEFORE they touch the DCP spine:
--            date_complete   = min(co_date)          earliest TCO or final CO
--            co_type         = 'final' if any final CO exists else 'temporary'
--            units_complete  = max(dwelling units)   NEVER sum
--        min/max are idempotent under duplication; a sum is not. Summing here
--        would multiply a 300-unit tower by its renewal count and manufacture
--        a pipeline that does not exist -- the CLAUDE.md double-count bug in
--        its natural habitat.
--        Rows with a CO date in the future or before 2010 are DROPPED, not
--        clamped: bs8b-p36w contains a `2105-11-05` typo.
--
-- ---------------------------------------------------------------------------
-- STAGE VOCABULARY -- and the one the owner asked for that is NOT emitted
-- ---------------------------------------------------------------------------
--   filed              DCP "1. Filed Application" or "2. Approved Application"
--   permitted          DCP "3. Permitted for Construction"
--   partially_complete DCP "4. Partially Completed Construction"
--   complete           DCP "5. Completed Construction", OR any CO issued
--   withdrawn          DCP "9. Withdrawn"
--
-- `under_construction` IS DELIBERATELY NOT EMITTED. Nothing ingested here
-- distinguishes "permit issued, shovel not in the ground" from "topped out":
-- that needs DOB Permit Issuance's `job_start_date` (`ipu4-2q9a`), and the
-- probe found DCP's own permit date present on 454 of 457 MN+BK new-building
-- jobs of >=10 units in the permitted stage, so there was no reason to ingest a
-- second permit feed. Inventing the split from "permit older than N months"
-- would be a modelling assumption wearing a status label. `permitted` therefore
-- means "permitted or under construction, not complete", which is exactly the
-- set units_permitted_400m counts.
--
-- CO PRECEDENCE. A CO overrides DCP stages 1/2/3 only (DCP is stale; the CO
-- feed is a day old). It does NOT override 4, 5 or 9 -- DCP's own QA is better
-- than ours on a partially-completed or withdrawn job, and `9. Withdrawn` with
-- a CO (5 MN+BK jobs, 37 units) is a genuine source conflict, left visible as
-- stage='withdrawn' with a non-null date_complete rather than silently resolved.
--
-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. VINTAGE LAG. DCP publishes semiannually. Everything about jobs FILED or
--    PERMITTED since 2026-01-21 is missing -- the CO supplement only fixes the
--    completion side. The forward pipeline is therefore a floor, never a
--    ceiling, and it is most wrong exactly where the owner cares most (the
--    newest filings). `source_vintage` carries the DCP version string so the
--    staleness is readable off the row.
-- 2. TCO vs FINAL CO. A temporary CO is legal occupancy -- residents move in --
--    so a TCO counts as `complete` for the residents question. It is NOT a
--    finished building: `co_type` = 'temporary' is the flag, and a consumer who
--    wants only finished buildings must filter on it. 61,656 of 143,140
--    bs8b-p36w rows are Temporary.
-- 3. WITHDRAWN AFTER PERMIT. 259 MN+BK jobs (4,338 net units) were permitted
--    and then withdrawn. They are KEPT with stage='withdrawn' so the attrition
--    is measurable, and every pipeline measure excludes them. A permitted unit
--    is not a delivered unit.
-- 4. NEGATIVE net_units ARE REAL AND ARE KEPT OUT. 5,044 MN+BK demolition jobs
--    (-16,398 units) and 6,539 alteration jobs (-19,508 units) remove housing:
--    an A1 conversion of a rooming house into fewer, larger apartments has
--    classanet < 0. This table INGESTS all of them (the ledger has to balance)
--    but model/dev_pipeline.py's measures count only net_units >= 1, because
--    "units arriving near this address" is not a net-of-demolition quantity --
--    a demolition three blocks away does not cancel a tower next door on the
--    timescale of a lease. The >= 50 "large project" threshold is a QUERY
--    filter, never an ingest filter.
-- 5. units_complete IS GROSS, net_units IS NET. Across completed MN+BK jobs
--    DCP's own Units_CO sums to 300,453 against classanet's 252,362: the CO
--    counts every Class A unit in the finished building, including ones that
--    already existed. Never subtract or ratio the two.
-- 6. GEOMETRY CARRIES NO SRID. `geom` is EPSG:4326 by project convention
--    (loci/db.py). DCP's Latitude/Longitude are used directly; every metric
--    operation downstream is NETWORK distance on the walk graph, not a
--    planar-degree calculation.
-- 7. DCP'S OWN KNOWN ISSUES, carried through unchanged: jobs are geocoded to a
--    BUILDING, so a multi-building project appears as several jobs at several
--    points (Greenpoint Landing, Pacific Park) and no project-level roll-up is
--    attempted here -- `nearest_large_project_id` names a JOB, not a
--    masterplan. DCP recodes unit counts from DOB filings that are themselves
--    self-reported, and DCP restates prior versions, so a job's net_units can
--    change between releases; only the current release is stored (one run, per
--    D61 -- comparing vintages means a parquet snapshot, never a second table).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.dev_pipeline (
    job_number      VARCHAR NOT NULL,   -- DOB job number; BIS 9-digit or DOB NOW letter+8
    bbl             VARCHAR,
    bin             VARCHAR,
    geom            GEOMETRY,           -- POINT, EPSG:4326 BY CONVENTION (no SRID in DuckDB)
    borough         VARCHAR NOT NULL,   -- MN/BX/BK/QN/SI, matching analysis.address
    nta_code        VARCHAR,            -- DCP NTA2020 (its own, not re-derived here)
    neighborhood    VARCHAR,            -- DCP NTAName20
    job_type        VARCHAR NOT NULL,   -- New Building / Alteration / Demolition
    net_units       INTEGER NOT NULL,   -- DCP ClassANet: proposed minus existing Class A units
    units_init      INTEGER,            -- ClassAInit  (existing before the job)
    units_prop      INTEGER,            -- ClassAProp  (proposed after the job)
    stage           VARCHAR NOT NULL,   -- filed/permitted/partially_complete/complete/withdrawn
    dcp_status      VARCHAR NOT NULL,   -- DCP's raw Job_Status, kept verbatim
    date_filed      DATE,
    date_permitted  DATE,
    date_complete   DATE,               -- earliest TCO or final CO (DCP's own if no CO row)
    co_type         VARCHAR,            -- 'final' | 'temporary' | NULL (no CO evidence)
    co_source       VARCHAR,            -- 'dob_bis_co' | 'dob_now_co' | 'both' | 'dcp' | NULL
    units_complete  INTEGER,            -- GROSS Class A units on the CO; see caveat 5
    source          VARCHAR NOT NULL,   -- 'nyc_dcp_housing_db'
    source_vintage  VARCHAR,            -- DCP Version, e.g. '25Q4'
    provenance      VARCHAR,            -- dataset ids + as-of dates, one string
    ingested_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (job_number)
);

-- ---------------------------------------------------------------------------
-- The address-grain extension. Twelve columns on analysis.address, written
-- ONLY by `UPDATE ... SET` from model/dev_pipeline.PIPELINE_COLUMNS, which a
-- pinned test asserts is disjoint from the screen's own column set (mirroring
-- model/address_demand.py's DEMAND_ANNOTATION_COLUMNS). Nothing here can move
-- gap_score, lead_category, n_missing or eligible.
--
-- These are additive on a table that already exists on the live database, so
-- they are ALTER ... ADD COLUMN IF NOT EXISTS here AND part of 002_schema.sql's
-- CREATE for a fresh database. Both paths must agree; tests/test_dev_pipeline.py
-- checks a fresh init_schema() has all twelve.
--
-- Distances are NETWORK metres on the walk graph (score/access.py's `_to_csr` /
-- `_prune`, the same engine the gap screen's nearest_m comes from), NOT
-- straight-line. 400 m is the project's 5-minute tier (THRESHOLDS[5]); 800 m is
-- the 10-minute tier. Both are computed in one Dijkstra pass.
-- ---------------------------------------------------------------------------
-- The twelve ALTER ... ADD COLUMN statements that belong here live at the END
-- OF 002_schema.sql instead, and they have to. db.init_schema() creates the
-- generated VIEW analysis.address_gaps immediately after 002 runs -- before
-- 003..011 -- because 004/005/006 reference that view by name and DuckDB
-- resolves a view's query at CREATE time. On a database built before this
-- landed, analysis.address already exists, so 002's CREATE TABLE IF NOT EXISTS
-- is a no-op and the new columns would not arrive until 011: the view would be
-- rebuilt naming twelve columns that do not exist yet, and init_schema() would
-- fail with a BinderException on every connection. Putting the idempotent
-- ALTERs at the tail of 002 keeps ONE file responsible for the shape of
-- analysis.address and gets the ordering right for legacy and fresh databases
-- alike. (This is the same class of bug D61 found and fixed in the view's own
-- wiring; it bites the moment a column is added to that table.)
