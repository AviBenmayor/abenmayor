-- ---------------------------------------------------------------------------
-- 026_recommendation.sql -- THE RECOMMENDATION LEDGER and its monthly outcome.
--
-- Owner's ask (2026-09-14): "start to track recommendations so that we can see
-- how long it takes for the free market to fill those gaps and if they do it
-- well (with our proposed solution)."
--
-- Two questions, and they are not the same question:
--   1. IS THE GAP STILL THERE?  -> time-to-fill, right-censored.
--   2. DID THEY DO IT WELL?     -> solution_match_score, and it is a WEAK
--                                 measure that must never pretend otherwise.
--
-- ---------------------------------------------------------------------------
-- WHY TWO NEW TABLES (the D61 / 2026-09-09 inventory rule)
-- ---------------------------------------------------------------------------
-- Inventory before writing, as the rule requires. What exists that is close:
--
--   analysis.address_category   address x category, the SCREEN. It says what
--       the data currently reads at a doorway. It has no notion of a claim
--       having been MADE on a date, no issuer, no proposed solution, and it is
--       DELETEd and re-INSERTed by every `loci address-gaps` run -- so a
--       recommendation stored there would be erased by the next screen
--       rebuild, which is the one thing a ledger may never do.
--
--   analysis.poi_presence       the first-seen ledger (sql/018). One row per
--       deduped LOCATION. It is half of the evidence this file consumes, and
--       it knows nothing about what anybody recommended.
--
--   analysis.storefront_pipeline  one row per business attempting to open at a
--       lot (sql/020). The other half of the evidence. Same remark.
--
--   docs/recommendations/*.md   the CARDS. Prose. A human artefact, not a
--       queryable claim, and the D74 card was regenerated on 2026-09-13 with a
--       different grade for restaurant than the 2026-09-11 original -- which is
--       exactly the drift a ledger exists to pin.
--
-- A RECOMMENDATION IS A NEW GRAIN: (who said what, about where, on which date).
-- Nothing in the warehouse carries an issuer or an issue date, so this is a
-- table and not a pivot. The OUTCOME is a second grain -- one row per
-- recommendation per monthly observation -- for the same reason
-- chains.brand_snapshot is not a column on chains.brand_latest: a time series
-- of observations cannot be a column on the thing being observed.
--
-- Everything else IS a pivot and is therefore a view, per the rule:
--   analysis.recommendation_latest            one row per rec + its newest outcome
--   analysis.recommendation_category_summary  the per-category roll-up
--
-- ---------------------------------------------------------------------------
-- APPEND-ONLY EXCEPT STATUS -- and why the database cannot enforce it
-- ---------------------------------------------------------------------------
-- DuckDB has no triggers and no column-level grants, so "append-only" here is
-- a CODE invariant, not a constraint. It is held in exactly one place:
-- model/recommendation_ledger.MUTABLE_COLUMNS, which is the only column set any
-- UPDATE in this project may name, and tests/test_recommendation.py asserts
--
--   * MUTABLE_COLUMNS | IMMUTABLE_COLUMNS == every column of this table, so a
--     column added later must be classified before the suite goes green; and
--   * the module emits no UPDATE naming anything outside MUTABLE_COLUMNS.
--
-- The reason it matters: a recommendation whose grade or supply ratio can be
-- edited after the fact is not a record of what we said, it is a record of
-- what we now wish we had said, and every retrodiction built on it is
-- circular. The 2026-09-11 Gowanus card graded restaurant D; the 2026-09-13
-- regeneration graded it C. BOTH are true of their own date. Overwriting the
-- first with the second would destroy the only evidence that the model moved.
--
-- A MISTAKE IS WITHDRAWN, NOT DELETED. `status = 'withdrawn'` plus
-- `status_reason` is how the D73 laundry lead is recorded: issued 2026-09-10,
-- withdrawn 2026-09-11 when the supply ratio came back 0.94x (normal, not
-- thin). Deleting it would leave a ledger of only the leads that survived,
-- which is the survivorship bias this whole exercise is meant to defeat.
--
-- ---------------------------------------------------------------------------
-- WHAT A ROW IS NOT
-- ---------------------------------------------------------------------------
-- A row is an ASSESSMENT WE MADE AND DATED, not necessarily an instruction to
-- open a store. Most of the first rows here grade D and say "do not act on
-- this data". Those rows are the CONTROL GROUP and they are the most valuable
-- rows in the table: if the market fills the D areas at the same rate as the
-- C areas, the screen carries no information, and nothing else in this project
-- would have told us.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS analysis.recommendation (
    rec_id                 VARCHAR PRIMARY KEY,   -- r-YYYYMMDD-<area>-<category>-<hash6>
    issued_on              DATE    NOT NULL,      -- the date the claim was MADE
    issued_by              VARCHAR NOT NULL,      -- 'loci recommend v1' | 'hand:<who>' | 'D73 lead'
    area_kind              VARCHAR NOT NULL CHECK (area_kind IN ('nta', 'address', 'bbox')),
    area_id                VARCHAR NOT NULL,      -- NTA code | address_id | 'lat0,lon0,lat1,lon1'
    area_label             VARCHAR,               -- the human name ('Gowanus core')
    anchor_address_id      VARCHAR,               -- NULL for a bbox/NTA area
    anchor_lon             DOUBLE,                -- the point the match radius is drawn from,
    anchor_lat             DOUBLE,                --   EPSG:4326 by convention (no SRID)
    category               VARCHAR NOT NULL,      -- one of the 15 loci categories
    proposed_solution      TEXT,                  -- what we said should open, in words
    format_hint            VARCHAR,               -- the operating format, if the proposal names
                                                  --   one ('24/7 staffed laundromat'). NULL means
                                                  --   we named none -- NOT that any format counts.
    grade                  VARCHAR CHECK (grade IS NULL OR grade IN ('A', 'B', 'C', 'D')),
    supply_ratio_at_issue  DOUBLE,                -- frozen. Never recomputed.
    homes_400m_at_issue    DOUBLE,
    gap_score_at_issue     DOUBLE,
    evidence_json          VARCHAR,               -- the card's own numbers, as issued
    status                 VARCHAR NOT NULL CHECK (status IN (
                               'open', 'filled', 'withdrawn', 'expired')),
    status_reason          VARCHAR,               -- REQUIRED for withdrawn/expired, by code
    status_changed_on      DATE,
    status_changed_at      TIMESTAMP,
    card_hash              VARCHAR NOT NULL,      -- content hash; the idempotency key
    created_at             TIMESTAMP NOT NULL
);

-- The idempotency key. Re-running `loci recommend --record` on an unchanged
-- card must add nothing; re-running it on a card whose grade or ratio MOVED
-- must add a new row, because that is a new claim on a new date.
CREATE UNIQUE INDEX IF NOT EXISTS recommendation_card_hash
    ON analysis.recommendation (card_hash);
CREATE INDEX IF NOT EXISTS recommendation_open
    ON analysis.recommendation (status, category);

-- ------------------------------------------- analysis.recommendation_outcome
-- ONE ROW PER RECOMMENDATION PER MONTHLY SNAPSHOT. Written DELETE + INSERT for
-- the month, so a re-run of 2026-09 replaces 2026-09 and touches no other
-- month -- the same idempotency contract `loci poi-snapshot` holds.
--
-- 'none' IS A REAL OBSERVATION and is stored, not skipped. A month with no
-- rows would be indistinguishable from a month the job did not run, and the
-- whole measure is a duration: the months in which nothing happened ARE the
-- measurement.
--
-- TIME-TO-FILL IS RIGHT-CENSORED. An open recommendation has no days_to_fill,
-- and its elapsed days are a LOWER BOUND on the eventual fill time. Taking a
-- median over the filled rows alone is the classic survivorship error -- it
-- answers "among gaps that filled, how fast", never "how fast do gaps fill".
-- The summary view publishes the open count beside the median so the omission
-- is always in view; a Kaplan-Meier estimate is the honest version and is not
-- built yet (there is no exposure to build it on).
CREATE TABLE IF NOT EXISTS analysis.recommendation_outcome (
    rec_id                VARCHAR NOT NULL,
    snapshot_month        VARCHAR NOT NULL,      -- 'YYYY-MM'
    matched_location_key  VARCHAR,               -- analysis.poi_presence.location_key
    matched_pipeline_key  VARCHAR,               -- analysis.storefront_pipeline.pipeline_id
    match_kind            VARCHAR NOT NULL CHECK (match_kind IN (
                              'opened', 'in_pipeline', 'none')),
    opened_on             DATE,                  -- the fill date, when match_kind='opened'
    entry_stage           VARCHAR,               -- pipeline stage, when in_pipeline
    entry_date            DATE,                  -- pipeline entry, when in_pipeline
    days_to_fill          INTEGER,               -- issued_on -> opened_on, OR -> entry_date;
                                                 --   quality_json.days_basis says WHICH
    distance_m            DOUBLE,                -- anchor -> match, STRAIGHT LINE (see below)
    same_category         BOOLEAN,               -- always TRUE when matched; stored to make
                                                 --   the requirement auditable, not inferred
    solution_match_score  DOUBLE,                -- 0..1, the rubric. See the module docstring.
    still_open            BOOLEAN,               -- the matched location was seen in the
                                                 --   newest ledger month
    quality_json          VARCHAR NOT NULL,      -- per-component earned / unavailable + why
    snapshot_at           TIMESTAMP NOT NULL,
    PRIMARY KEY (rec_id, snapshot_month)
);

CREATE INDEX IF NOT EXISTS recommendation_outcome_month
    ON analysis.recommendation_outcome (snapshot_month);

-- ---------------------------------------------------------------------------
-- THE RADIUS IS A STRAIGHT LINE, AND THAT IS A DELIBERATE DOWNGRADE
-- ---------------------------------------------------------------------------
-- Everywhere else in this project "within reach" means 400 m NETWORK distance
-- on the pruned walk graph (score/access.THRESHOLDS[5]). The check does NOT
-- use it, because there is no persisted address->POI pair set to read: a
-- network radius from an arbitrary anchor means loading the graph pickle and
-- running a bounded Dijkstra, which is minutes of work for a monthly job whose
-- whole job is a handful of anchors.
--
-- THE BIAS HAS A KNOWN SIGN. Network distance >= straight-line distance
-- always, so a straight-line 400 m disc STRICTLY CONTAINS the 400 m network
-- catchment. The check is therefore OVER-INCLUSIVE: it can credit the market
-- with filling a gap that is a 600 m walk away. That errs toward "the gap
-- filled" and against "our recommendation is still live", which is the
-- direction that makes us look WORSE, not better -- the right direction for a
-- self-scoring ledger. `distance_m` is stored on every match so the radius can
-- be re-cut after the fact, and `loci recommendations check --radius-m` takes
-- a tighter one.
-- ---------------------------------------------------------------------------

-- ------------------------------------------- analysis.recommendation_latest
-- One row per recommendation with its NEWEST outcome. A VIEW: it is a pivot of
-- the two tables above and D61 says a pivot does not get to be a third table.
--
-- `days_open` is elapsed days to the fill, or to today for anything still
-- open. For an open row it is a LOWER BOUND, which `is_censored` marks.
CREATE OR REPLACE VIEW analysis.recommendation_latest AS
WITH newest AS (
    SELECT rec_id, max(snapshot_month) AS snapshot_month
    FROM analysis.recommendation_outcome
    GROUP BY rec_id
)
SELECT r.rec_id,
       r.issued_on,
       r.issued_by,
       r.area_kind,
       r.area_id,
       r.area_label,
       r.category,
       r.grade,
       r.proposed_solution,
       r.format_hint,
       r.supply_ratio_at_issue,
       r.homes_400m_at_issue,
       r.status,
       r.status_reason,
       r.status_changed_on,
       o.snapshot_month                                   AS latest_month,
       o.match_kind,
       o.matched_location_key,
       o.matched_pipeline_key,
       o.opened_on,
       o.entry_stage,
       o.entry_date,
       o.distance_m,
       o.solution_match_score,
       o.still_open,
       o.quality_json,
       CASE WHEN o.opened_on IS NOT NULL
            THEN date_diff('day', r.issued_on, o.opened_on)
            ELSE date_diff('day', r.issued_on, current_date) END   AS days_open,
       (o.opened_on IS NULL)                                       AS is_censored
FROM analysis.recommendation r
LEFT JOIN newest n ON n.rec_id = r.rec_id
LEFT JOIN analysis.recommendation_outcome o
       ON o.rec_id = n.rec_id AND o.snapshot_month = n.snapshot_month;

-- ------------------------------ analysis.recommendation_category_summary
-- The per-category roll-up. Also a view, same rule.
--
-- `median_days_to_fill` IS OVER THE FILLED ROWS ONLY and is therefore biased
-- DOWNWARD -- fast fills are over-represented because slow ones have not
-- happened yet. `n_open` is published beside it precisely so the omission
-- cannot be read past.
--
-- `share_still_open_12m` is NULL, never 0, when nothing has been filled long
-- enough to have a twelve-month anniversary. 0 would say "everything we
-- recommended closed within a year"; NULL says "no exposure yet", which is the
-- truth for at least the next twelve months.
CREATE OR REPLACE VIEW analysis.recommendation_category_summary AS
WITH l AS (SELECT * FROM analysis.recommendation_latest)
SELECT category,
       count(*)                                                AS n_recommendations,
       count(*) FILTER (WHERE status = 'open')                 AS n_open,
       count(*) FILTER (WHERE status = 'filled')               AS n_filled,
       count(*) FILTER (WHERE status = 'withdrawn')            AS n_withdrawn,
       count(*) FILTER (WHERE status = 'expired')              AS n_expired,
       count(*) FILTER (WHERE match_kind = 'in_pipeline')      AS n_in_pipeline,
       median(days_open) FILTER (WHERE status = 'filled')      AS median_days_to_fill,
       min(days_open)    FILTER (WHERE status = 'filled')      AS min_days_to_fill,
       max(days_open)    FILTER (WHERE status = 'filled')      AS max_days_to_fill,
       median(days_open) FILTER (WHERE status = 'open')        AS median_days_open_censored,
       avg(solution_match_score) FILTER (WHERE match_kind = 'opened')
                                                               AS mean_solution_match,
       -- exposure: filled AND at least 365 days have passed since the fill
       count(*) FILTER (WHERE status = 'filled'
                          AND opened_on IS NOT NULL
                          AND date_diff('day', opened_on, current_date) >= 365)
                                                               AS n_exposed_12m,
       CASE WHEN count(*) FILTER (WHERE status = 'filled'
                                    AND opened_on IS NOT NULL
                                    AND date_diff('day', opened_on, current_date) >= 365) = 0
            THEN NULL
            ELSE count(*) FILTER (WHERE status = 'filled'
                                    AND opened_on IS NOT NULL
                                    AND date_diff('day', opened_on, current_date) >= 365
                                    AND still_open)::DOUBLE
               / count(*) FILTER (WHERE status = 'filled'
                                    AND opened_on IS NOT NULL
                                    AND date_diff('day', opened_on, current_date) >= 365)
       END                                                     AS share_still_open_12m
FROM l
GROUP BY category;

-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. A MATCH IS NOT A CAUSAL EFFECT. Nobody read our card. A filled gap says
--    the market moved, not that we moved it. The value of the ledger is
--    CALIBRATION -- did the thing we called a gap turn out to be one -- and
--    any causal reading of it is D1's reverse-causality error again (D87).
--
-- 2. THE FIRST-SEEN LEDGER IS LEFT-CENSORED until 2026-10. Every location that
--    existed when it started carries a NULL first-seen, so the check cannot
--    see it as an opening -- which is right (it is not one) but means the only
--    'opened' matches available before 2026-10 come from a SOURCE DATE or a
--    government filing, never from observation. Expect 'none' everywhere in
--    the first months, and read it as "the instrument is not warm yet".
--
-- 3. A PIPELINE ENTRY IS AN INTENTION. 'in_pipeline' means somebody filed, not
--    that anything will open. Roughly a third of DOB job filings never reach a
--    permit at all. days_to_fill on such a row is days to the FILING, and
--    quality_json.days_basis says so.
--
-- 4. solution_match_score IS NOT A QUALITY RATING. It is "how much of what we
--    proposed can we confirm from open data", which tops out at what the feeds
--    carry: a name, sometimes a cuisine or a licence class, and a source
--    count. It cannot see hours, staffing, price, or whether the place is any
--    good. A 0.5 means "right category, nothing else checkable", and the
--    per-component JSON names every component that was unavailable and why.
--
-- 5. AN AREA-LEVEL RECOMMENDATION HAS NO STOREFRONT. A bbox card's anchor is
--    the box centroid, so `distance_m` is measured from a point nobody chose.
--    An address-grain recommendation is the one whose distance means something.
-- ---------------------------------------------------------------------------
