-- ---------------------------------------------------------------------------
-- 051_storefront_tenure.sql -- the premises TENURE prior from LL157, and the
-- category-BLIND filing counts at the address grain.
--
-- (a) analysis.storefront_tenure -- ONE ROW PER PREMISES, built from
--     analysis.storefront_year (six filings, 2019-2024, activity_canonical).
--     LL157 has so far been read as a vacancy COUNT (the latest filing only:
--     model/storefronts.py). The same panel is a six-year occupancy history:
--     how long tenants stay, how often a unit turns over. That is the prior
--     the card wants ("this block's storefronts turn over every X years") and
--     later a survival covariate.
--
--     OCCUPANCY RUNS. Consecutive observed years with the same
--     `activity_canonical` and `vacant = FALSE` form one run. A run is
--     INTERVAL-CENSORED at 12 months by construction -- observations are one
--     12/31 apart -- so `run_years` is a count of observed years, a lower bound
--     on the tenure it measures. A run touching the first observed year is
--     left-censored (the tenant was already there); one touching the last is
--     right-censored (still there). A missing year does NOT end a run when the
--     class matches on both sides (the unit was almost certainly occupied
--     through the gap); it does when the class differs (a turnover happened
--     somewhere in the gap, dated to the gap's end).
--
--     TURNOVER = a change of occupant: occupied -> vacant, vacant -> occupied,
--     or class A -> class B between consecutive observed years. A same-class
--     tenant swap (one restaurant replaced by another) is INVISIBLE here --
--     `activity_canonical` is ~12 coarse classes and LL157 carries no tenant
--     name -- so turnover is an UNDERCOUNT and tenure an OVERCOUNT. Stated on
--     the card as such.
--
-- (b) analysis.address: three tenure columns and twelve category-blind filing
--     counts, all CONTEXT and never a grade. The filing counts exist because
--     `openings_pipeline_400m` reads only the five categories that have a
--     licensing feed and the other ten read as structural zero -- silence that
--     looks like "nothing is opening". Sign permits, DOB fit-outs, permits
--     issued and liquor applications within 400 m at 6/12/24 months say
--     something is happening whatever the trade.
--
--     THE D88 COSTUME RISK, stated here and in the module docstring: filings
--     cluster where retail is already thick. As a forecast feature these
--     counts would re-prove herding; they are card context and nothing else.
--
-- GRAIN of storefront_tenure: premises_id (= BBL|unit; sql/045). All five
-- boroughs on disk; the screen filters at query time. `nta_tenure` is a
-- VIEW over it, the NTA descriptive table the owner asked for -- a pivot,
-- not a second table.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.storefront_tenure (
    premises_id             VARCHAR PRIMARY KEY,
    borough                 VARCHAR,
    bbl                     VARCHAR,
    nta_code                VARCHAR,
    lon                     DOUBLE,
    lat                     DOUBLE,
    first_year              INTEGER NOT NULL,
    last_year               INTEGER NOT NULL,
    n_years_observed        INTEGER NOT NULL,      -- years with a vacant verdict (vacant IS NOT NULL)
    n_years_occupied        INTEGER NOT NULL,
    n_years_vacant          INTEGER NOT NULL,
    n_runs                  INTEGER NOT NULL,      -- occupancy runs
    n_turnovers             INTEGER NOT NULL,      -- occupant changes between consecutive observed years
    mean_run_years          DOUBLE,                -- over occupancy runs; NULL when none
    max_run_years           INTEGER,
    current_run_years       INTEGER,               -- the run touching last_year, 0 if vacant then
    current_activity        VARCHAR,
    current_vacant          BOOLEAN,
    left_censored           BOOLEAN NOT NULL,      -- an occupancy run touches first_year
    right_censored          BOOLEAN NOT NULL,      -- an occupancy run touches last_year
    runs_json               JSON,                  -- [{activity, from, to, years, left, right}]
    built_at                TIMESTAMP NOT NULL
);

CREATE OR REPLACE VIEW analysis.nta_tenure AS
SELECT borough,
       nta_code,
       count(*)                                             AS n_premises,
       sum(n_years_observed)                                AS premises_years,
       sum(n_turnovers)                                     AS n_turnovers,
       CASE WHEN sum(n_years_observed) > 0
            THEN sum(n_turnovers)::DOUBLE / sum(n_years_observed) END
                                                            AS turnover_per_premises_year,
       median(mean_run_years)                               AS median_mean_run_years,
       avg(mean_run_years)                                  AS mean_run_years,
       count(*) FILTER (WHERE current_vacant)               AS n_vacant_latest,
       count(*) FILTER (WHERE right_censored)               AS n_right_censored,
       max(built_at)                                        AS built_at
FROM analysis.storefront_tenure
GROUP BY ROLLUP (borough, nta_code);

ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS n_premises_400m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS premises_turnover_400m DOUBLE;   -- turnovers per premises-year
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS median_tenure_years_400m DOUBLE; -- run-weighted median run length
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS tenure_run_at TIMESTAMP;

ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS fitout_400m_6m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS fitout_400m_12m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS fitout_400m_24m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS sign_permit_400m_6m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS sign_permit_400m_12m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS sign_permit_400m_24m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS permit_issued_400m_6m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS permit_issued_400m_12m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS permit_issued_400m_24m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS liquor_application_400m_6m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS liquor_application_400m_12m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS liquor_application_400m_24m INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS filings_blind_asof DATE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS filings_blind_run_at TIMESTAMP;
