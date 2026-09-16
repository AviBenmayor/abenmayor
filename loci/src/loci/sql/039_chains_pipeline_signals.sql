-- ---------------------------------------------------------------------------
-- 039_chains_pipeline_signals.sql -- the three DERIVED signals D109/GTM-189
-- puts on the brand grain: how many government filings name this brand, whether
-- a filing count means anything for its category at all, and how much press it
-- drew. Written by `loci chains detect` in the same DELETE+INSERT that writes
-- the month's snapshot.
--
-- ---------------------------------------------------------------------------
-- WHY THREE COLUMNS AND NOT A TABLE (the D61 / feedback_table_proliferation
-- inventory rule, run before adding anything)
-- ---------------------------------------------------------------------------
-- The grain of all three is (snapshot_month, brand_key) -- exactly
-- chains.brand_snapshot's grain. D61: a new MEASURE at an existing grain
-- extends the grain; only a new GRAIN earns a table. A
-- chains.brand_pipeline_signal table would be a second row per brand per month
-- that could only ever be joined 1:1 back to this one.
--
-- Nothing else holds them. analysis.storefront_pipeline is
-- (bbl x business_name_key) -- lot grain, no brand roll-up and no month;
-- chains.press_hits is (brand_key, url) -- one row per article, no month;
-- chains.brand_location is one row per storefront. Each can produce the count,
-- none can STORE it against the snapshot it was measured with, which is the
-- whole point: `pipeline_filings_12m` read live next March is a different
-- number from the one that admitted the brand last September.
--
-- ---------------------------------------------------------------------------
-- pipeline_coverage -- THE COLUMN THAT STOPS A ZERO FROM LYING
-- ---------------------------------------------------------------------------
-- NYC filing feeds can only see five of the fifteen daily-needs categories:
-- restaurant, bar, cafe_bakery, grocery and pharmacy. The other ten (laundry,
-- hair_barber, nails_beauty, childcare, clinic, fitness, bank, hardware,
-- convenience, tailor_repair) are licensed by NYS DOS, NYS Education or NYS
-- OCFS, or are not licensed at all, and no DOB feed carries a trade field that
-- would attribute a filing to them (GTM-152, D80).
--
-- So `pipeline_filings_12m = 0` means two completely different things
-- depending on the brand, and a reader cannot tell which from the number:
--
--   'real'             the channel CAN see this category and saw nothing.
--                      Zero is a measurement.
--   'structural_zero'  the channel is blind to this category. Zero is not a
--                      measurement and must never be rendered as one --
--                      render.py prints "no filing coverage for this
--                      category" instead of the digit.
--   NULL               the brand has no `loci_category`, so which regime
--                      applies is UNKNOWN. Writing 'structural_zero' here
--                      would assert a blind spot nobody established; NULL is
--                      the project's standing "not measured" (D79).
--
-- The five-category set is NOT written down here or in detect.py. It is
-- derived at run time from model/filing_categories.yaml -- the file that
-- decides, per feed, which licence types map to which Loci category -- by
-- `detect.filing_real_categories()`. A hand-copied list in a second place is
-- how the two quietly disagree the first time a feed is added.
--
-- ---------------------------------------------------------------------------
-- WINDOWS
-- ---------------------------------------------------------------------------
-- Both 12-month counts are the TWELVE CALENDAR MONTHS ENDING WITH
-- `snapshot_month`, not a rolling 365 days off the day the command ran: the
-- snapshot is the unit of idempotence, and a re-run of 2026-09 next March must
-- produce the same number it did in September.
--
--   pipeline_filings_12m  rows of analysis.storefront_pipeline whose
--                         `business_name_key` equals the brand key -- exact,
--                         not approximate: model/storefront_pipeline.py
--                         imports chains.normalize.brand_key -- with
--                         `entry_date` inside the window. ALL filings, open
--                         and not-yet-open alike; this is a measure of how
--                         much paperwork the brand generated, NOT the
--                         candidate predicate's `pipeline_open`, which counts
--                         only NOT-yet-open rows because an open filing is a
--                         store detect has already counted.
--   press_hits_12m        rows of chains.press_hits for the key with
--                         `published_on` inside the window. A FLOOR while the
--                         table holds only a 45-day live queue (D110).
--
-- A missing optional table leaves the column NULL -- never 0. "We did not
-- measure that channel" and "that channel saw nothing" are different facts and
-- this is the only place the difference can be recorded.
--
-- ---------------------------------------------------------------------------
-- WHY THE VIEW IS RE-CREATED BELOW
-- ---------------------------------------------------------------------------
-- chains.brand_latest (sql/015) is `SELECT s.* ...` and DuckDB binds a view's
-- column list AT CREATE TIME. Without the CREATE OR REPLACE at the foot of
-- this file the view would keep the fifteen columns it was created with and
-- every reader of brand_latest -- candidates.py chief among them -- would see
-- the new signals as missing rather than as NULL.
--
-- ---------------------------------------------------------------------------
-- SHARED-TREE NOTE (D105/D106). `db.init_schema` applies every
-- src/loci/sql/*.sql on the next WRITE connection, so this file goes live on
-- whichever session writes first, not on a scheduled apply. That is safe here
-- and it was not for sql/037/038: this migration adds three NULLABLE columns
-- to one chains table and re-binds one chains view. It creates nothing, drops
-- nothing, rewrites no row, and touches no object the supply hash is computed
-- over. The one positional `INSERT INTO chains.brand_snapshot SELECT *` in the
-- codebase (chains/detect.py `_write`) was changed to name its columns in the
-- same commit, so a wider table cannot break a write.
-- ---------------------------------------------------------------------------

ALTER TABLE chains.brand_snapshot
    ADD COLUMN IF NOT EXISTS pipeline_filings_12m INTEGER;

ALTER TABLE chains.brand_snapshot
    ADD COLUMN IF NOT EXISTS pipeline_coverage VARCHAR;   -- 'real' | 'structural_zero' | NULL

ALTER TABLE chains.brand_snapshot
    ADD COLUMN IF NOT EXISTS press_hits_12m INTEGER;

-- Re-bind the view onto the widened table (see the note above).
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
