-- ---------------------------------------------------------------------------
-- 052_closure_triangulation.sql -- went-dark venues CORROBORATED by an
-- independent premises signal, staged and NOT promoted.
--
-- THE PROBLEM. staging.poi_stale holds 79,182 Foursquare venues nobody has
-- refreshed since 2023 (sql/050). A stale venue is an ABSENCE OF EVIDENCE and
-- D79 forbids reading absence as a closure. Two other things in the
-- warehouse watch the same premises without asking Foursquare:
--
--   * LL157 (analysis.storefront_year): a premises within 30 m that was
--     OCCUPIED on one 12/31 and VACANT on the next -- a dated flip the
--     landlord self-reported;
--   * the SLA licence label (analysis.licence_event): a licence of the same
--     category and name key within 30 m that ended with NO successor at the
--     BBL (the premises arm, the stricter one).
--
-- A stale venue that one of those agrees with is a corroborated closure with
-- a DATE BOUND. A stale venue that neither agrees with stays "unrefreshed"
-- and is NOT in this table -- the D79 rule made a CHECK: n_kinds >= 2, and
-- `kinds` always names 'stale' plus at least one independent kind.
--
-- WHY A STAGING TABLE AND NOT analysis.poi_closure_evidence ROWS. Writing
-- these as evidence would change poi_status on every matched location and
-- move `supply_hash` -- an announced, priced step (model/supply_asof.py). The
-- rows sit here with the poi_presence match and `would_flip` precomputed so
-- the executive can rule on the promotion knowing exactly what moves.
-- Promotion also needs sql/033's CHECK (source IN ('places','web')) widened
-- to admit 'triangulation', which is a CREATE-INSERT-DROP-RENAME on the
-- evidence ledger (DuckDB cannot ALTER a CHECK).
--
-- WHAT THE DATES MEAN. `closed_before` is the earliest upper bound the
-- agreeing kinds give (the first vacant 12/31, or the licence's last valid
-- day); `closed_after` is the last 12/31 the premises was seen occupied, when
-- LL157 is one of the kinds. Neither is a closure DATE; a reader that quotes
-- `closed_before` as "closed on" has invented a day.
--
-- CAVEATS THE DATABASE CANNOT ENFORCE
--  1. `date_refreshed` is when Foursquare last TOUCHED the record, not when
--     the business was last seen trading. The flip/licence end is only
--     required to fall on or after (date_refreshed - 365 d).
--  2. LL157 activity classes are coarse; a FOOD SERVICES premises flipping
--     vacant 20 m from a stale cafe may be the cafe or its neighbour. The
--     30 m radius is the same one the licence ladder uses and is stated, not
--     tuned.
--  3. ONE FLIP CAN CORROBORATE SEVERAL STALE VENUES. Five stale venues 20 m
--     from one premises that went vacant all get the same flip. That is a
--     fan-out, not a fusion -- each row is still one venue -- but a reader
--     counting "corroborated closures" must read `flip_shared_by` and not
--     quote five closures for one vacancy.
--  4. `geom` EPSG:4326 by convention.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.closure_triangulation (
    stale_poi_id        VARCHAR PRIMARY KEY,
    source_id           VARCHAR NOT NULL,
    category            VARCHAR NOT NULL,
    name                VARCHAR,
    name_key            VARCHAR,
    lon                 DOUBLE NOT NULL,
    lat                 DOUBLE NOT NULL,
    geom                GEOMETRY NOT NULL,
    date_refreshed      DATE,
    opened_on           DATE,
    kinds               VARCHAR NOT NULL,            -- 'stale,ll157_vacancy_flip[,licence_end]'
    n_kinds             SMALLINT NOT NULL CHECK (n_kinds BETWEEN 2 AND 3),
    -- LL157 kind
    flip_premises_id    VARCHAR,
    flip_activity       VARCHAR,                     -- activity_canonical in the last occupied year
    flip_last_occupied_on DATE,
    flip_first_vacant_on  DATE,
    flip_m              DOUBLE,
    flip_shared_by      SMALLINT,                    -- stale venues this same premises flip corroborates (1 = only this one)
    -- licence kind
    licence_number      VARCHAR,
    licence_end_on      DATE,
    licence_m           DOUBLE,
    -- the bound
    closed_after        DATE,
    closed_before       DATE NOT NULL,
    -- what promotion would touch
    matched_location_key VARCHAR,
    matched_poi_id      VARCHAR,
    matched_status_now  VARCHAR,                     -- open | closed | unknown | NULL (no match)
    would_flip          BOOLEAN NOT NULL,            -- matched AND status_now <> 'closed'
    asof_date           DATE NOT NULL,
    built_at            TIMESTAMP NOT NULL
);
