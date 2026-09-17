-- ---------------------------------------------------------------------------
-- 028_forecast.sql -- THE FORECAST LEDGER: the MODELLED layer, issued as dated,
-- scoreable predictions, so that "what the world could be" can be checked
-- against "what the world did" instead of asserted beside it.
--
-- Owner's ask (2026-09-14): "almost feels like we are building multiple layers
-- here: predicted/modeled (not what the world reflects but what it could) vs
-- realized/actual. worth building this out further."
--
-- A prediction that is not DATED, FROZEN and SCORED is not a prediction; it is
-- a description of the present tense with the verb changed. These four objects
-- exist to make the difference enforceable rather than rhetorical.
--
-- ---------------------------------------------------------------------------
-- WHAT IS FORECAST, AND WHAT IS NOT (the D88 guardrail, restated)
-- ---------------------------------------------------------------------------
-- `p_opening` is the probability that the MARKET puts a same-category
-- storefront within 400 m of this doorway in the next twelve months. It is
-- ENTRY, not VIABILITY. The retrodiction (docs/retrodiction-2026-09.md, D88)
-- established both halves of that sentence:
--
--   * entry is predictable out of sample -- NTA-blocked AUC 0.866 against a
--     no-score baseline of 0.854, calibration monotone, permutation and
--     spatially-structured placebos both cleared;
--   * survival is NOT. Every business-level closure instrument in the
--     warehouse is a current-state extract, and the one premises-level outcome
--     that IS identified (LL157 go-dark) returns a null whose SIGN FLIPS with
--     the definition of attrition.
--
-- So a high `p_opening` says "the market is likely to act here", never "a shop
-- here will work". Nothing in this file, and nothing that reads it, may be
-- phrased the second way.
--
-- And the older guardrail (D1) holds unchanged: retail is the DEPENDENT read.
-- Openings are the left-hand side here. No forecast regresses anything on
-- future retail.
--
-- ---------------------------------------------------------------------------
-- WHY FOUR OBJECTS AND NOT ONE (the 2026-09-09 inventory rule)
-- ---------------------------------------------------------------------------
-- Inventory first, as the rule requires. What exists that is close:
--
--   analysis.address_category   address x category, the SCREEN. Present tense,
--       no issue date, no model version, and DELETEd and re-INSERTed by every
--       `loci address-gaps` run. A forecast stored there would be erased by
--       the next screen rebuild and could never be scored.
--
--   analysis.recommendation     (sql/026) a CLAIM WE MADE about a handful of
--       anchors, with a proposed solution and a grade. Human-authored, tens of
--       rows, and its outcome asks "did the gap fill". A forecast is issued by
--       a FITTED MODEL over the entire frame, carries no proposal, and its
--       outcome asks "was the probability right". Same shape, different grain,
--       different question -- and mixing them would let a hand-written card
--       contaminate a calibration curve.
--
--   analysis.poi_presence       (sql/018) the first-seen ledger. It is the
--       EVIDENCE this file is scored against, and it knows nothing about what
--       anybody predicted.
--
--   data/retrodiction/summary.json  a one-off research artefact on a 12,000
--       address SAMPLE, with no issue date and no address-grain output.
--
-- A FORECAST VINTAGE IS A NEW GRAIN: (which model, on which date, said what
-- about which doorway). Nothing in the warehouse carries a model version or an
-- issue month, so this is a table.
--
-- The OUTCOME is a second grain -- one row per forecast per scoring date -- for
-- the same reason chains.brand_snapshot is not a column on chains.brand_latest:
-- a time series of observations cannot be a column on the thing observed. The
-- 2023-01 vintage is scored at 12 months AND at 24; both rows are kept.
--
-- The RUN is a third grain -- one row per (issued_month, model_version) -- and
-- it exists to keep the fit diagnostics OFF the 4.2 million prediction rows.
-- The coefficient vector, the fit window, the blocked-CV AUC, the baselines
-- and the ships/does-not-ship verdict are properties of the FIT, not of any
-- one doorway, and repeating them per row would be four million copies of the
-- same two kilobytes and four million chances for them to disagree.
--
-- Everything else IS a pivot and is therefore a VIEW, per the rule:
--   analysis.forecast_latest         newest p beside newest realized outcome
--   analysis.forecast_surprise_nta   the residual sum per NTA, with its z
--
-- ---------------------------------------------------------------------------
-- THE VINTAGE DISCIPLINE -- the one rule that makes a track record a track
-- record
-- ---------------------------------------------------------------------------
-- A PAST VINTAGE IS NEVER RE-ISSUED WITH A NEWER MODEL. `loci forecast issue`
-- is idempotent per (issued_month, model_version) by DELETE-then-INSERT, which
-- means re-running the SAME model on the SAME month reproduces that month's
-- answer -- and running a DIFFERENT model writes a DIFFERENT version alongside,
-- never over. Both then get scored, and the comparison between them is the
-- only honest way to say a model improved.
--
-- The temptation this forbids is precise and it is the one every forecasting
-- shop loses to: re-issuing 2023-01 with the 2026 model, scoring it well, and
-- calling that a track record. It would be a measurement of hindsight.
--
-- `model_version` is `<semver>+<8 hex>` where the hex is a hash of the exact
-- feature list, the fit-window rule, the radius and the horizon. Change any of
-- them and the version changes by construction, so two runs that share a
-- version share a model -- the database cannot check this, model/forecast.py's
-- `model_version()` is the single place it is computed, and a test pins that
-- changing the feature list changes the hash.
--
-- ---------------------------------------------------------------------------
-- DISTANCE IS A STRAIGHT LINE, EVERYWHERE IN THIS FILE
-- ---------------------------------------------------------------------------
-- 400 m straight-line in EPSG:32618 for the supply reconstruction, the homes
-- denominator, the baseline median AND the outcome radius -- exactly as
-- docs/retrodiction-2026-09.md §2 fixed it, and for the same reason: the
-- persisted Dijkstra artefacts are nearest-distance for ONE frozen supply set
-- and cannot be replayed at a historical date.
--
-- D85's rule (never compare a network measure to a straight-line one) is kept
-- by never mixing. NOTHING HERE IS COMPARABLE TO
-- `analysis.address_category.supply_ratio_vs_base`, which is a network measure,
-- and `analysis.address.homes_400m`, which is also a network measure, is NOT
-- the `homes_400m` frozen in the features (now witnessed by `features_hash`).
--
-- The bias has a known sign: a straight-line disc strictly CONTAINS the network
-- catchment, so both the frozen supply and the realized outcome are
-- OVER-inclusive. Over-inclusive supply shrinks the measured gap (against the
-- screen); over-inclusive outcomes raise the realized rate (toward the model,
-- since the model was fitted on the same over-inclusive outcome). The two do
-- not cancel and neither is hidden.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS analysis;

-- ------------------------------------------------------------ analysis.forecast
-- One row per address x category per issue month per model version.
--
-- MN+BK, frame='lot' ONLY. Street rows are excluded and the exclusion is not
-- trivial: D84's street midpoints have no residents, so the homes denominator
-- of `supply_ratio` would be structurally zero and `p_opening` would be a
-- division artefact rather than a forecast. `frame` is stored anyway so that a
-- later street-frame model is a new set of rows and not a silent redefinition
-- of these.
--
-- NOTE ON THE NO-ELIGIBILITY-GATE RULE (owner, 2026-09-13): every lot-frame
-- address in MN+BK gets a row in every category. Nothing is dropped for being
-- unpromising -- a p_opening of 0.004 is a forecast, and it is the rows at the
-- bottom of the distribution that make the calibration curve mean anything.
-- ---------------------------------------------------------------------------
-- RESHAPED 2026-09-16 (warehouse audit, owner ruling (1)).
--
-- GONE: `forecast_id` and `features_json`. `forecast_id` was
-- 'f-'||issued_month||'-'||githash||'-'||address_id||'-'||category -- a pure
-- restatement of the four-column key that already carried a UNIQUE index, for
-- 257 MiB. `features_json` was a 7-key VARCHAR blob repeated 4.2M times per
-- vintage, 526 MiB, and is the model INPUT: re-derivable, and read by nothing.
--
-- `features_hash` replaces it: the first 16 chars of md5 over the SAME string
-- `model/forecast._features_json_sql` builds, so two vintages can still be
-- asked "were these fitted on the same inputs?" -- the one question the blob
-- was ever good for. It is a 64-bit equality WITNESS, not an identity; identity
-- is the four key columns.
--
-- EVERY VINTAGE IS KEPT. The audit proposed one shipped vintage per
-- issued_month; the owner overruled it on 2026-09-16. The frozen vintage is the
-- point of this table and a query-time view cannot replace it.
--
-- An EXISTING warehouse is reshaped by `loci migrate-warehouse --step
-- forecast_outcome_rekey --step forecast_slim`, NOT by a migration file:
-- DuckDB has no `ALTER TABLE ... ADD CONSTRAINT` (verified 1.5.5, "No support
-- for that ALTER TABLE option yet"), so moving the primary key means a full
-- CREATE-INSERT-DROP-RENAME, which must not re-run on every session.
-- `model/forecast.schema_is_reshaped(con)` asks the CATALOGUE, not the
-- filesystem, so code can branch on it either way.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis.forecast (
    issued_month      VARCHAR NOT NULL,      -- 'YYYY-MM'; features frozen at its FIRST day
    horizon_months    INTEGER NOT NULL,      -- 12
    model_version     VARCHAR NOT NULL,      -- '<semver>+<8 hex>'
    address_id        VARCHAR NOT NULL,
    category          VARCHAR NOT NULL,      -- one of the 15 loci slugs
    frame             VARCHAR NOT NULL DEFAULT 'lot',  -- 'lot' | 'street' (D84,
                                             --   owner ruling 4 2026-09-16).
                                             --   The FIT is lot-only; street
                                             --   points are SCORED by it.
    borough           VARCHAR,
    nta_code          VARCHAR,
    surprise_cell     VARCHAR,               -- 800 m grid cell id; the variance
                                             --   cluster for the NTA z (see below)
    p_opening         DOUBLE  NOT NULL,      -- P(>=1 same-category opening within
                                             --   400 m in the horizon)
    expected_openings DOUBLE  NOT NULL,      -- = p_opening. See THE UNIT, below.
    -- 'street_no_homes' marks a street midpoint with ZERO lot-frame homes in
    -- its 400 m disc (1,169 of 50,199). Its p_opening is a real number and an
    -- EXTRAPOLATION: every lot row that trains the model has homes > 0. The row
    -- is written rather than dropped (no eligibility gate, owner 2026-09-13)
    -- and rather than coalesced to zero (that manufactures a gap), and this
    -- label is the only thing that says so.
    support           VARCHAR NOT NULL
        CHECK (support IN ('fitted', 'pooled', 'street_no_homes')),
    features_hash     VARCHAR NOT NULL,      -- substr(md5(<frozen inputs>), 1, 16)
    frozen_at         TIMESTAMP NOT NULL,
    PRIMARY KEY (issued_month, model_version, address_id, category)
);
CREATE INDEX IF NOT EXISTS forecast_vintage
    ON analysis.forecast (issued_month, model_version);
CREATE INDEX IF NOT EXISTS forecast_addr
    ON analysis.forecast (address_id, category);

-- ---------------------------------------------------------------------------
-- THE UNIT: expected_openings = p_opening x 1, AND WHY NOT A POISSON RATE
-- ---------------------------------------------------------------------------
-- The choice was between a logistic on "did at least one same-category
-- storefront appear in this disc" and a Poisson on the COUNT in the disc. The
-- logistic wins on three grounds and the third is decisive:
--
-- 1. IT IS WHAT WAS VALIDATED. The retrodiction's 0.866 blocked-CV AUC, its
--    monotone calibration, its permutation null and its placebo were all run
--    on the binary disc outcome. Shipping a Poisson would ship an unvalidated
--    functional form under a validated headline.
--
-- 2. THE COUNT IS NOT A COUNT OF INDEPENDENT EVENTS. Discs overlap almost
--    completely at this grain -- two addresses 150 m apart share most of their
--    400 m catchment -- so ONE storefront opening is counted inside hundreds of
--    discs. A Poisson lambda summed across addresses in an NTA would report
--    hundreds of expected openings for one actual shop. Overdispersion is not
--    a nuisance here, it is the whole structure.
--
-- 3. THE RESIDUAL HAS TO BE WELL DEFINED. The NTA surprise below is
--    sum(realized - expected) over addresses. That is only a residual if the
--    two sides share a unit. `realized_flag` is a disc-level indicator; so,
--    therefore, must the expectation be. With expected_openings = p_opening
--    the surprise is a sum of Bernoulli residuals and its variance is
--    computable; with a Poisson rate it would be the difference of two
--    quantities that count different things.
--
-- So `expected_openings` is the expected number of DISCS-WITH-AN-OPENING
-- contributed by this row, which is p, and it is NOT an expected number of
-- storefronts. Summing it over an NTA gives the expected number of doorways
-- that will see an opening nearby, not the expected number of openings. The
-- column is named `expected_openings` because the spec asked for that name;
-- this comment is the correction to the name, and `loci forecast report`
-- prints the same correction in plain words.
--
-- `realized_openings` IS stored on the outcome as a raw count, for diagnostics
-- and for a future count model -- but the SCORE is computed on `realized_flag`.

-- -------------------------------------------------------- analysis.forecast_run
-- One row per (issued_month, model_version). The FIT, not the predictions.
--
-- `ships` is the pre-declared failure criterion, evaluated at fit time and
-- STORED, not re-judged later:
--     blocked-CV AUC must exceed the NO-SCORE baseline (same design, same
--     NTA-blocked folds, same category fixed effects, log_homes + retail_index
--     only) AND exceed the PERSISTENCE baseline (rank by whether the disc got a
--     same-category opening in the twelve months BEFORE t0) AND have a
--     calibration decile gap at or under 15 points.
-- A vintage that fails is still WRITTEN -- it is issued, dated and scoreable --
-- and `ships=false` travels with it. Deleting a failed vintage is how a track
-- record becomes a highlight reel.
CREATE TABLE IF NOT EXISTS analysis.forecast_run (
    issued_month        VARCHAR NOT NULL,
    model_version       VARCHAR NOT NULL,
    horizon_months      INTEGER NOT NULL,
    radius_m            DOUBLE  NOT NULL,
    fit_t0s             VARCHAR NOT NULL,   -- JSON list of the training fold t0s
    fit_window_rule     VARCHAR NOT NULL,   -- prose: how fit_t0s are derived from
                                            --   issued_month, so a later reader can
                                            --   reproduce it without the code
    feature_list        VARCHAR NOT NULL,   -- JSON list, hashed into model_version
    n_fit_rows          BIGINT,
    n_fit_addresses     BIGINT,
    n_fit_ntas          INTEGER,
    fit_positive_rate   DOUBLE,
    auc_blocked         DOUBLE,             -- NTA-blocked CV, full model
    auc_no_score        DOUBLE,             -- the honest baseline (NOT homes-only)
    auc_persistence     DOUBLE,             -- did-it-happen-last-year
    auc_homes_only      DOUBLE,             -- reported, never used as the bar
    brier_fit           DOUBLE,
    calibration_json    VARCHAR,            -- out-of-sample deciles at fit time
    coefficients_json   VARCHAR,
    support_json        VARCHAR,            -- per category: dated openings in the fit
                                            --   window, and fitted vs pooled slope
    ships               BOOLEAN NOT NULL,
    ships_reason        VARCHAR NOT NULL,
    n_rows_issued       BIGINT,
    issued_at           TIMESTAMP NOT NULL,
    PRIMARY KEY (issued_month, model_version)
);

-- ---------------------------------------------------- analysis.forecast_outcome
-- One row per forecast per scoring date. DELETE+INSERT per
-- (issued_month, model_version, scored_month), the same idempotency contract
-- `loci poi-snapshot` and `loci recommendations check` hold.
--
-- ZERO IS A REAL OBSERVATION and is stored. A scoring pass that wrote only the
-- hits would produce a calibration curve with no denominator.
--
-- THE OUTCOME, precisely: a location in `analysis.poi_presence` of the SAME
-- category, in the principled supply set, whose `first_seen_kind` is
-- 'source_date' or 'gov_filing' and whose `first_seen_src_date` falls in
-- [first day of issued_month, first day of issued_month + horizon_months),
-- within 400 m STRAIGHT-LINE of the address. Same rule, same radius, same
-- projection as the features -- stated here so the two can never drift apart.
--
-- WHAT THE OUTCOME CANNOT SEE, and it is the largest caveat on every score
-- below: `first_seen_src_date` is not an opening date. For Foursquare rows it
-- is when Foursquare minted the record; for `gov_filing` rows it is a licence
-- or a first inspection, which D80 measures at a 221-259 day lead from fitout.
-- Non-classical measurement error in the timing variable, at both ends of the
-- horizon. A 12-month window is chosen partly BECAUSE it is long relative to
-- that error; a 3-month window would be mostly noise in the dating.
--
-- And the backfill-censored rows (D79, ~40% of the ledger, no date at all) can
-- NEVER be a realized opening. That is correct -- they are not openings, they
-- are locations that already existed -- but it means the realized rate is a
-- LOWER BOUND on real entry, uniformly, in every vintage. Because the model is
-- fitted on the same censored-blind outcome, the bias is shared by both sides
-- of the score and does not by itself distort calibration; it does mean the
-- absolute levels are not entry rates for New York.
CREATE TABLE IF NOT EXISTS analysis.forecast_outcome (
    -- Keyed on the forecast's NATURAL key, not on the dropped `forecast_id`.
    -- `model_version` is load-bearing in that key and in every join to
    -- analysis.forecast: without it a scored vintage fans out across all five
    -- same-month 2026-09 re-issues.
    issued_month       VARCHAR NOT NULL,
    model_version      VARCHAR NOT NULL,
    address_id         VARCHAR NOT NULL,
    category           VARCHAR NOT NULL,
    scored_month       VARCHAR NOT NULL,    -- 'YYYY-MM', the AS-OF date of the score
    horizon_elapsed    INTEGER NOT NULL,    -- months from issued_month to scored_month
    realized_openings  INTEGER NOT NULL,    -- raw count in the disc; diagnostics only
    realized_flag      BOOLEAN NOT NULL,    -- the SCORED outcome
    scored_at          TIMESTAMP NOT NULL,
    PRIMARY KEY (issued_month, model_version, address_id, category, scored_month)
);

CREATE INDEX IF NOT EXISTS forecast_outcome_month
    ON analysis.forecast_outcome (scored_month);

-- --------------------------------------------------------- analysis.forecast_latest
-- Per address x category, the NEWEST issued probability and the NEWEST scored
-- outcome, so a card or a map can print MODELLED and REALIZED side by side.
-- A VIEW: it is a pivot of the two tables above, and the rule says a pivot does
-- not get to be a third table.
--
-- `p_opening` and `realized_flag` here may come from DIFFERENT vintages --
-- the newest forecast is typically unscoreable (its horizon has not elapsed)
-- while the newest scored outcome belongs to an older one. `issued_month` and
-- `scored_vintage_month` are both carried so the reader can see that, and
-- `is_scoreable_now` marks whether the newest forecast could be scored yet.
CREATE OR REPLACE VIEW analysis.forecast_latest AS
WITH newest_fc AS (
    SELECT address_id, category, max(issued_month) AS issued_month
    FROM analysis.forecast
    GROUP BY 1, 2
),
fc AS (
    SELECT f.*
    FROM analysis.forecast f
    JOIN newest_fc n
      ON n.address_id = f.address_id AND n.category = f.category
     AND n.issued_month = f.issued_month
    -- TIE-BREAK BY WHEN IT WAS ISSUED, NOT BY HOW ITS VERSION STRING SORTS
    -- (2026-09-15 fix). `model_version` is '<semver>+<8 hex git-ish hash>';
    -- DESC on that string orders two same-month vintages by the HEX, which is
    -- arbitrary -- '0.1.1+f1cb6628' (2026-09-14 23:26) beat D112's re-issued
    -- '0.1.1+51bab17f' (2026-09-15 17:53) purely on 'f' > '5', so the newest
    -- re-baseline lost to a stale one and every card and report stamped the
    -- wrong model version. `frozen_at` is the actual issue time of the
    -- vintage (analysis.forecast, NOT NULL); the version string stays as the
    -- deterministic second key so the pick is stable if two vintages were
    -- frozen in the same microsecond.
    QUALIFY row_number() OVER (
        PARTITION BY f.address_id, f.category
        ORDER BY f.frozen_at DESC, f.model_version DESC) = 1
),
scored AS (
    SELECT f.address_id, f.category, f.issued_month AS scored_vintage_month,
           f.model_version AS scored_model_version,
           o.scored_month, o.horizon_elapsed, o.realized_openings, o.realized_flag,
           f.p_opening AS p_at_that_vintage
    FROM analysis.forecast f
    JOIN analysis.forecast_outcome o
      ON  o.issued_month  = f.issued_month
      AND o.model_version = f.model_version
      AND o.address_id    = f.address_id
      AND o.category      = f.category
    QUALIFY row_number() OVER (
        PARTITION BY f.address_id, f.category
        ORDER BY o.scored_month DESC, o.horizon_elapsed DESC) = 1
)
SELECT fc.address_id,
       fc.category,
       fc.frame,
       fc.borough,
       fc.nta_code,
       fc.issued_month,
       fc.model_version,
       fc.horizon_months,
       fc.p_opening,
       fc.expected_openings,
       fc.support,
       fc.features_hash,
       s.scored_vintage_month,
       s.scored_model_version,
       s.scored_month,
       s.horizon_elapsed,
       s.realized_openings,
       s.realized_flag,
       s.p_at_that_vintage,
       -- can the NEWEST forecast be scored yet? (horizon elapsed against today)
       (date_diff('month',
                  strptime(fc.issued_month || '-01', '%Y-%m-%d')::DATE,
                  current_date) >= fc.horizon_months)          AS is_scoreable_now
FROM fc
LEFT JOIN scored s
       ON s.address_id = fc.address_id AND s.category = fc.category;

-- ----------------------------------------------------- analysis.forecast_surprise_nta
-- WHERE DID THE MARKET DO MORE (or less) THAN THE MODEL EXPECTED?
--
--   surprise = sum over addresses of (realized_flag - p_opening)
--
-- Positive = more doorways saw an opening than the frozen model said they
-- would. That is a statement about the MODEL's error in that neighbourhood,
-- and it is interesting in exactly one direction: a model fitted on the whole
-- city, frozen before the fact, that systematically under-predicts one NTA, is
-- pointing at something the four features do not carry.
--
-- ---------------------------------------------------------------------------
-- THE Z-SCORE, AND WHY THE OBVIOUS ONE IS WRONG
-- ---------------------------------------------------------------------------
-- The naive variance of the residual sum is sum(p(1-p)) -- Poisson-binomial,
-- assuming the addresses are independent Bernoulli draws. THEY ARE NOT, and the
-- violation is not mild: two addresses 150 m apart share nearly their whole
-- 400 m disc, so their outcomes are nearly the SAME observation. A z built on
-- sum(p(1-p)) over 3,000 addresses in an NTA would divide by a standard error
-- perhaps an order of magnitude too small and declare every NTA in the city
-- significant.
--
-- So the headline z is CLUSTER-ROBUST, with the cluster a 800 m grid square
-- (`surprise_cell`, assigned at issue time in EPSG:32618). 800 m is twice the
-- catchment radius, so two addresses in different cells cannot share a disc
-- except across a cell boundary -- the residual dependence is within-cell by
-- construction, and the sandwich estimator
--
--     Var(sum r) = sum over cells of (sum of r within the cell)^2
--
-- absorbs it without assuming any particular correlation structure. It is the
-- same defence the retrodiction used with NTA clusters; the finer cluster is
-- used here because the NTA is the unit being TESTED and cannot also be the
-- unit the variance is estimated across.
--
-- `z_naive` is published beside it precisely so the gap between them is
-- visible: it is typically 3-5x, and that ratio is the design effect.
--
-- FEWER THAN 5 CELLS AND THE Z IS NULL, not small. A sandwich variance from
-- three clusters is not an estimate.
--
-- MULTIPLE TESTING: this view computes ~100 NTAs x 16 rows each. A "top 10 by
-- z" list is a maximum over hundreds of statistics and will contain
-- |z| > 2 values under the pure null. `loci forecast report` prints the
-- Bonferroni threshold beside the table and labels anything short of it as
-- descriptive. The view itself does no correction -- it publishes the n so the
-- correction can be applied by whoever reads it.
--
-- `category = '(all)'` is the roll-up across all fifteen categories, emitted by
-- the UNION below rather than by a second view.
CREATE OR REPLACE VIEW analysis.forecast_surprise_nta AS
WITH scored AS (
    SELECT f.issued_month,
           f.model_version,
           o.scored_month,
           o.horizon_elapsed,
           f.nta_code,
           f.category,
           f.surprise_cell,
           (CASE WHEN o.realized_flag THEN 1.0 ELSE 0.0 END) - f.p_opening AS r,
           f.p_opening AS p,
           (CASE WHEN o.realized_flag THEN 1 ELSE 0 END)                   AS y
    FROM analysis.forecast f
    JOIN analysis.forecast_outcome o
      ON  o.issued_month  = f.issued_month
      AND o.model_version = f.model_version
      AND o.address_id    = f.address_id
      AND o.category      = f.category
    WHERE f.nta_code IS NOT NULL
),
by_cat AS (
    SELECT issued_month, model_version, scored_month, horizon_elapsed,
           nta_code, category, surprise_cell,
           sum(r) AS cell_r, sum(p * (1 - p)) AS cell_v, count(*) AS n,
           sum(y) AS y, sum(p) AS e
    FROM scored
    GROUP BY 1, 2, 3, 4, 5, 6, 7
),
all_cat AS (
    SELECT issued_month, model_version, scored_month, horizon_elapsed,
           nta_code, '(all)' AS category, surprise_cell,
           sum(r) AS cell_r, sum(p * (1 - p)) AS cell_v, count(*) AS n,
           sum(y) AS y, sum(p) AS e
    FROM scored
    GROUP BY 1, 2, 3, 4, 5, 7
),
cells AS (SELECT * FROM by_cat UNION ALL SELECT * FROM all_cat)
SELECT issued_month,
       model_version,
       scored_month,
       horizon_elapsed,
       nta_code,
       category,
       sum(n)                       AS n_addresses,
       count(*)                     AS n_cells,
       sum(y)                       AS realized,
       sum(e)                       AS expected,
       sum(cell_r)                  AS surprise,
       CASE WHEN sum(cell_v) > 0
            THEN sum(cell_r) / sqrt(sum(cell_v)) END          AS z_naive,
       CASE WHEN count(*) >= 5 AND sum(cell_r * cell_r) > 0
            THEN sum(cell_r) / sqrt(sum(cell_r * cell_r)) END AS z_clustered
FROM cells
GROUP BY 1, 2, 3, 4, 5, 6;

-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
-- ---------------------------------------------------------------------------
-- 1. ENTRY IS NOT VIABILITY (D88). Repeated here because it is the one a
--    reader will forget. `p_opening` is a forecast of what the MARKET will do,
--    and the market is not a validator -- the retrodiction found openings
--    going where supply was ALREADY THICK, which is consistent with
--    agglomeration economies being real AND with herding into saturated
--    corridors. Nothing in this ledger separates them.
--
-- 2. A FORECAST IS NOT A RECOMMENDATION. `analysis.recommendation` is where a
--    claim with a proposed solution lives. A high p_opening is a statement
--    about base rates on this block, not advice.
--
-- 3. THE 2023-01 VINTAGE IS A BACKTEST AND IS LABELLED ONE. It is issued in
--    2026 with features frozen at 2023-01-01 and a model fitted only on
--    outcomes dated before 2023-01. That makes it leakage-free in the timing
--    sense -- and it does NOT make it a real-time forecast, because the
--    FEATURE SET and the FUNCTIONAL FORM were chosen in 2026 after seeing the
--    2023-24 retrodiction. That is specification-search leakage, it cannot be
--    undone retroactively, and it is the reason the 2026-09 vintage -- whose
--    outcome nobody has seen -- is the one that will eventually carry weight.
--
-- 4. THE CONTROLS ARE ANACHRONISTIC. `homes` is present-day PLUTO UnitsRes and
--    `retail_index` is present-day (D82); neither is a 2023 reading. They enter
--    as controls, never as the tested variable, and crediting 2023-24
--    construction to 2023 biases toward the growth areas.
--
-- 5. THE COHORT THAT CAN BE OBSERVED IS FOOD. Only businesses that must
--    announce themselves to somebody get a date: 81.5% of the dated ledger is
--    restaurant, cafe or bar. The per-category scores for the thin categories
--    are computed and reported, and they are not samples of those categories'
--    openings -- they are samples of the openings those categories happen to
--    declare.
-- ---------------------------------------------------------------------------
