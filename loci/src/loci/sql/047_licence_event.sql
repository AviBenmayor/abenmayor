-- ---------------------------------------------------------------------------
-- 047_licence_event.sql -- the SLA licence NON-RENEWAL label (rewind
-- pre-registration v2 §1.2) and its 400 m address-grain descriptive baseline.
--
-- WHAT THIS IS
-- ------------
-- analysis.licence_interval (sql/041) carries every DCWP and NYS SLA licence
-- with its dated interval and REFUSES to say which ends are events. This
-- table is where the pre-registration's event definition is applied, once,
-- for the four categories the SLA vocabulary maps onto (restaurant, bar,
-- grocery, pharmacy). DCWP rows are NOT here -- the roster maps onto one Loci
-- category (laundry, 6 rows) and publishes no status-change date; they stay
-- in licence_interval untouched.
--
-- THE LABEL, in the pre-registration's words:
--   event   = `expiry_observed` on an INACTIVE row with NO successor SLA
--             licence at the same BBL within 180 days
--   business arm: a successor with a MATERIALLY DIFFERENT name key still
--             counts as an event (transfer on sale: the business ended)
--   premises arm: ANY successor at the BBL means no event
--   dropped = `expiry_future` (inactive for a reason SLA does not publish),
--             `no_expiry`, and any 1900-12-31 sentinel creation date
--   censored = every row in the ACTIVE file, at the pull date
--
-- WHAT THIS IS NOT. It is NOT survival. A licence end is an UPPER BOUND on a
-- business end -- tight for a bar (the SLA licence is the licence to trade),
-- loose for a grocery (SLA "Grocery Store" is the beer-only off-premises
-- class; dropping it is a margin decision). Until P5 (model/licence_event.py
-- `p5_ppv`) says otherwise the outcome is called "licence non-renewal" and
-- it is CONTEXT, not a grade. No hazard is fit here; the fit is a separate,
-- later, pre-registered run.
--
-- GRAIN: one row per SLA licence (licence_number is unique in
-- licence_interval by construction). Both event arms sit on the same row so
-- the sign-stability check reads one table.
--
-- CAVEATS THE DATABASE CANNOT ENFORCE
--  1. `bbl IS NULL` (~10% of NYC SLA rows) means the successor screen COULD
--     NOT RUN. `successor_checkable` is FALSE and both event flags are NULL --
--     not TRUE, not FALSE. Every rate in this file and its measures excludes
--     those rows from numerator AND denominator; a reader that COALESCEs them
--     to FALSE invents renewals.
--  2. `issue_date` is SLA `original_issue_date`, the FIRST licence date at
--     the premises under that serial. `days_since_issue` is therefore a
--     premises tenure, not a licence-term clock; the term boundary lives in
--     `licence_class` and is why the pre-registered baseline is category x
--     borough x class + time-since-issue.
--  3. SLA publishes full dates; `interval_censored_month` is carried FALSE on
--     every row so a city whose licence file publishes a month can set it and
--     downstream code already reads it.
--  4. `geom` is EPSG:4326 by convention; DuckDB GEOMETRY carries no SRID.
--  5. `at_risk_5y` / `event_5y_*` are stamped against `label_asof` at build time so
--     the address measure and the baseline view read ONE window definition.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.licence_event (
    licence_number          VARCHAR PRIMARY KEY,
    source                  VARCHAR NOT NULL,          -- nys_sla_liquor_licenses | nys_sla_inactive_licenses
    category                VARCHAR NOT NULL,          -- restaurant | bar | grocery | pharmacy
    category_confidence     VARCHAR,
    licence_type            VARCHAR,                   -- verbatim "type N class NNN"
    licence_class           INTEGER,                   -- the SLA class number, zero-padding stripped
    business_name           VARCHAR,
    name_key                VARCHAR,                   -- poi_presence.name_key_of(business_name)
    bbl                     VARCHAR,
    match_method            VARCHAR,
    borough                 VARCHAR,                   -- MN|BK|QN|BX|SI code, or NULL
    lon                     DOUBLE,
    lat                     DOUBLE,
    geom                    GEOMETRY,
    issue_date              DATE NOT NULL,
    end_date                DATE,                      -- expiration_date on an ended row; NULL when censored
    censor_date             DATE,                      -- pulled_asof when censored; NULL when ended
    interval_end            DATE NOT NULL,             -- coalesce(end_date, censor_date)
    interval_censored_month BOOLEAN NOT NULL DEFAULT FALSE,
    ended                   BOOLEAN NOT NULL,          -- expiry_observed
    days_since_issue        INTEGER NOT NULL,
    successor_checkable     BOOLEAN NOT NULL,          -- bbl IS NOT NULL
    successor_licence_number VARCHAR,
    successor_issue_date    DATE,
    successor_gap_days      INTEGER,                   -- successor issue - end (negative = overlapped)
    successor_same_name     BOOLEAN,                   -- NULL when either name key is missing
    event_business          BOOLEAN,                   -- NULL when not checkable
    event_premises          BOOLEAN,                   -- NULL when not checkable
    at_risk_5y              BOOLEAN NOT NULL,          -- interval overlaps [asof - 5y, asof]
    event_5y_business       BOOLEAN,                   -- event_business AND end_date in window
    event_5y_premises       BOOLEAN,
    label_asof              DATE NOT NULL,
    pulled_asof             DATE,
    built_at                TIMESTAMP NOT NULL
);

-- The category x borough x licence-class baseline. A VIEW: it is a pivot of
-- the grain above, and the card's "vs the borough rate" reads the class = NULL
-- rollup row. Rates are over CHECKABLE rows only (caveat 1).
CREATE OR REPLACE VIEW analysis.licence_event_baseline AS
SELECT category,
       borough,
       licence_class,
       count(*)                                                    AS n_licences,
       count(*) FILTER (WHERE successor_checkable)                 AS n_checkable,
       count(*) FILTER (WHERE ended)                               AS n_ended,
       count(*) FILTER (WHERE event_business)                      AS n_event_business,
       count(*) FILTER (WHERE event_premises)                      AS n_event_premises,
       count(*) FILTER (WHERE at_risk_5y AND successor_checkable)  AS n_at_risk_5y,
       count(*) FILTER (WHERE event_5y_business)                   AS n_event_5y_business,
       count(*) FILTER (WHERE event_5y_premises)                   AS n_event_5y_premises,
       CASE WHEN count(*) FILTER (WHERE at_risk_5y AND successor_checkable) > 0
            THEN count(*) FILTER (WHERE event_5y_business)::DOUBLE
                 / count(*) FILTER (WHERE at_risk_5y AND successor_checkable) END
                                                                   AS nonrenewal_rate_5y_business,
       CASE WHEN count(*) FILTER (WHERE at_risk_5y AND successor_checkable) > 0
            THEN count(*) FILTER (WHERE event_5y_premises)::DOUBLE
                 / count(*) FILTER (WHERE at_risk_5y AND successor_checkable) END
                                                                   AS nonrenewal_rate_5y_premises,
       median(days_since_issue) FILTER (WHERE event_business)      AS median_days_to_event_business,
       median(days_since_issue) FILTER (WHERE NOT ended)           AS median_days_censored
FROM analysis.licence_event
GROUP BY ROLLUP (category, borough, licence_class);

-- The address-grain measure, on the existing address x category grain
-- (owner rule: a new measure extends the grain, never forks it). NULL on the
-- eleven categories with no SLA vocabulary and on every row before the first
-- run; 0 is a value on the four that have one.
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS n_licences_400m INTEGER;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS n_nonrenewed_400m INTEGER;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS nonrenewal_rate_5y_400m DOUBLE;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS licence_asof DATE;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS licence_run_at TIMESTAMP;
