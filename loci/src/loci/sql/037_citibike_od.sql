-- ---------------------------------------------------------------------------
-- 037_citibike_od.sql -- Citi Bike ORIGIN-DESTINATION leakage: where the
-- riders who leave a neighbourhood's residential docks in the evening and at
-- weekends actually land. Citi Bike phase 2 (GTM-167).
--
-- Owner rulings, 2026-09-15 (R1/R2/R3):
--   R1  lambda in model/revenue.py stays UNTOUCHED. This is a stored table, a
--       view and card MEASURES. Nothing here is a Huff denominator.
--   R2  a dock's origin_type is a RATIO OF RATIOS on weekday peaks, per
--       station-month (see `origin_type` below), not an am/pm volume share.
--   R3  the NTA-grain card values are stamped on EVERY address in the NTA and
--       labelled neighbourhood-wide; NULL -- never 0 -- where the origin NTA
--       has no residential dock or too few trips in the window.
--
-- .draft SUFFIX, ON PURPOSE. `db.init_schema` applies every src/loci/sql/*.sql
-- on the next WRITE connection, including uncommitted ones, and three sessions
-- share this tree (D105/D106, GTM-179). An undrafted file here would go live on
-- a peer's write and move the shared supply hash. The lead renames it to .sql
-- after announcing the migration.
--
-- Written by:
--   analysis.bike_od_leakage          sources/cities/nyc/citibike_od.py
--                                     (`loci citibike od-ingest`)
--   analysis.address.bike_od_*        model/bike_od.py
--                                     (`loci citibike od-measures`), UPDATE-only
--   analysis.address_category.bike_od_supplied_share   same command
-- ---------------------------------------------------------------------------
-- THE D61 / feedback_table_proliferation INVENTORY, BEFORE ADDING ANYTHING
--
-- ONE new table, at a grain nothing in the warehouse holds:
--
--   analysis.bike_od_leakage  (origin NTA x destination NTA x month x day_type
--       x daypart x origin_type). staging.citibike_station_month is the
--       nearest thing and it CANNOT hold this: it is a MARGINAL -- a dock's
--       departures and a dock's arrivals, with the pairing thrown away. The
--       whole question here ("a rider left Bushwick on a Saturday: where did
--       they arrive?") lives in the joint distribution, which no marginal can
--       reconstruct. analysis.address_bike_station is address x dock walking
--       distance, a different object again.
--
-- ZERO new tables for the card values. Four numbers per address is a MEASURE at
-- an existing grain (analysis.address), and one number per address x category
-- is a measure at analysis.address_category's grain. They extend those tables,
-- exactly as bike_starts_400m and supply_ratio_vs_base do.
--
-- The `share` is NOT stored (D61: a derivation is a view). It is rendered by
-- analysis.bike_od_leakage_evening below.
-- ---------------------------------------------------------------------------
-- UNITS AND MEANING, because the column names cannot carry it
--
--   origin_nta / destination_nta
--                the dock's h3 res-9 cell -> analysis.hex.nta_code, THE SAME
--                RULE THE ADDRESSES USE (model/address_gaps.py, via the python
--                `h3` package; analysis.hex.h3_index is the 15-character STRING
--                form, so a DuckDB join must use h3_latlng_to_cell_string, not
--                h3_latlng_to_cell, which returns the BIGINT form and matches
--                nothing). Measured 2026-09-15: 2,611 docks, 0 unmapped, 133
--                distinct NTAs of 262. One rule for docks and addresses is what
--                bounds the h3 boundary-misassignment error: it is the same
--                misassignment on both sides of the join.
--
--   month        the FIRST DAY of the calendar month, as a DATE, and the UNIT
--                OF IDEMPOTENCE: `loci citibike od-ingest` DELETEs a month and
--                re-INSERTs it, so a re-run of March can never rewrite April.
--
--   day_type     'weekday' | 'saturday' | 'sunday'. Federal holidays are
--   daypart      EXCLUDED and belong to no day type; dayparts are the five
--                half-open intervals of 017/034, RENDERED from the same python
--                tuple. One clock for transit, bike and DOT counts.
--
--                BOTH ARE DATED BY `started_at`, the DEPARTURE -- unlike
--                `ends` in 034, which is dated by the arrival. A trip is ONE
--                event with two places, and the origin is the end this table
--                partitions on (origin_type, origin_nta, the share
--                denominator), so dating it by its origin is what makes an OD
--                cell reconcile to 034's `starts` for the same dock. The cost
--                is bounded and named: the median trip is ~13 minutes, so an
--                arrival falls in a later daypart than its departure only in
--                the last minutes of a window. It also makes the month clean --
--                the published file is KEYED on started_at, so there is no
--                month-boundary spill here at all.
--
--   origin_type  'residential' | 'mixed' | 'destination' | 'unknown', a
--                property of the ORIGIN DOCK IN THAT MONTH (R2):
--
--                    am_pm_share = (am_peak starts / am_peak ends)
--                                / (pm_peak starts / pm_peak ends)
--
--                weekday cells only. > 1.2 residential, < 0.8 destination,
--                otherwise mixed; under 200 weekday trips (starts + ends) in
--                the station-month it is 'unknown', as is a dock with a zero
--                in any denominator.
--
--                IT IS A RATIO OF RATIOS AND NOT AN AM/PM VOLUME SHARE for a
--                measured reason: the pm peak carries more volume than the am
--                peak at essentially every dock in the system, so the ticket's
--                literal "am share > pm share" test calls only 59 of 2,611
--                docks residential over the whole panel (64 of the 2,225 docks
--                active in 2024-08). That is not a neighbourhood typology, it
--                is the shape of the citywide diurnal curve. Dividing the am
--                start:end ratio by the pm one cancels the dock's overall
--                volume and leaves the DIRECTION of the peak flow, which is the
--                thing being asked about. Equivalent to the net-flow form
--                (am_s-am_e)/(am_s+am_e) - (pm_s-pm_e)/(pm_s+pm_e) > 0 at the
--                threshold 1 -- (x-1)/(x+1) is strictly increasing -- and that
--                identity is asserted in tests/test_citibike_od.py.
--
--                'unknown' is a real value and never a silent residential: a
--                quiet dock is a dock we cannot type, not a commuter dock.
--
--   trips        RAW COUNTS for the month, not rates. Dock-to-dock only: both
--   member_trips ends must be New York PUBLIC docks (the JC/HB and SYS/shop
--                exclusions of 034 apply unchanged) with published coordinates.
--                A dockless e-bike end has no dock to attribute and is excluded
--                and counted, never folded onto a nearby dock.
--
--   round_trips  trips whose origin DOCK is their destination DOCK (2.58%
--                measured). STORED SEPARATELY AND NEVER FOLDED IN: a round trip
--                carries no destination information at all -- the rider went
--                for a ride -- so leaving it inside `trips` would inflate every
--                origin NTA's own-NTA share and manufacture "this neighbourhood
--                keeps its riders". `trips` is the gross count INCLUDING them;
--                the view subtracts them.
--
--   n_origin_stations / n_dest_stations
--                distinct docks contributing to THIS ROW. They are counts of a
--                set, so they DO NOT SUM across rows: adding the origin-dock
--                counts of two dayparts double-counts every dock open in both.
--                Use max(), or re-count from the source. Present so a one-dock
--                NTA pair is visible as the thin evidence it is.
-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
--
-- 1. RIDERS ARE NOT RESIDENTS. Citi Bike mode share is low single digits and
--    skews young, male and higher-income. This is where CYCLISTS go. The card
--    wording says "riders", never "residents", and that is not a style rule.
-- 2. DOCKS ARE ENDOGENOUS TO RETAIL AND DENSITY. 133 of 262 NTAs have a dock at
--    all, and the operator builds where the trips will be. A destination NTA
--    that reads busy is partly a place with many docks, which is partly a place
--    with much retail -- reverse causality in a mobility costume, the D1 error
--    exactly. An NTA with no dock reads as no flow, which is a statement about
--    a capital plan, never about the sidewalk.
-- 3. THERE IS NO TRIP PURPOSE IN THE FEED. Evening-and-weekend is a PROXY for
--    non-commute, and it is the weakest joint in the chain.
-- 4. ROUND TRIPS (2.58%) CARRY NO DESTINATION. Stored separately; see above.
-- 5. EVENING IS LEISURE AND DAILY NEEDS ARE NOT. A pharmacy run happens at
--    18:30 on a Tuesday, inside the pm_peak this window deliberately excludes.
--    The measure is biased toward discretionary categories and must not be read
--    as evidence about a grocery or a laundromat.
-- 6. H3 BOUNDARY MISASSIGNMENT. A dock 20 m from an NTA line can land on the
--    wrong side. Mitigated, not removed, by using ONE rule for docks and
--    addresses so the error is common to both sides of the join.
-- 7. CAPACITY CENSORING AND REBALANCING, inherited from phase 1: a full dock
--    turns an arrival into an arrival somewhere else, and a rebalancing truck
--    is not a trip.
--
-- VERDICT: CONTEXT ONLY, on the D76 footing. Nothing built from this table
-- enters gap_score, supply_ratio_vs_base, any recommendation grade, or lambda.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.bike_od_leakage (
    origin_nta        VARCHAR,    -- dock -> h3 res-9 -> analysis.hex.nta_code
    destination_nta   VARCHAR,
    month             DATE,       -- first day of month; the unit of idempotence
    day_type          VARCHAR,    -- weekday | saturday | sunday (holidays excluded)
    daypart           VARCHAR,    -- early | am_peak | midday | pm_peak | evening
    origin_type       VARCHAR,    -- residential | mixed | destination | unknown
    trips             BIGINT,     -- gross, INCLUDING round_trips
    member_trips      BIGINT,
    round_trips       BIGINT,     -- origin dock = destination dock
    n_origin_stations SMALLINT,   -- set counts: do NOT sum across rows
    n_dest_stations   SMALLINT,
    ingested_at       TIMESTAMP
);

-- THE LEAKAGE WINDOW, IN ONE PLACE.
--
--     daypart = 'evening' OR day_type IN ('saturday', 'sunday')
--
-- It mirrors analysis.address.bike_evening_ends_share_400m (034) exactly, and
-- like that measure the union is counted ONCE -- a Saturday evening trip is one
-- trip, not two -- which is what keeps `share` a genuine share in [0, 1].
--
-- WEEKDAY pm_peak IS DELIBERATELY EXCLUDED. That is the commute home, the
-- single largest flow in the system, and it is the one flow that says nothing
-- about where a rider CHOSE to go. Including it would make every job centre the
-- top destination of every residential NTA, which is true and useless.
--
-- ROUND TRIPS ARE SUBTRACTED, not filtered: a round trip is inside `trips` at
-- the origin_nta = destination_nta cell, so the diagonal is netted rather than
-- dropped. Cells that are ENTIRELY round trips fall out (trips > round_trips).
--
-- `share` is partitioned by (origin_nta, month), not by origin_nta alone, so it
-- sums to 1 within an origin NTA within a month and a downstream window
-- (`WHERE month BETWEEN ...`) can be applied without invalidating it. This is
-- the one place this view departs from the ticket sketch.
CREATE OR REPLACE VIEW analysis.bike_od_leakage_evening AS
WITH f AS (
    SELECT origin_nta,
           destination_nta,
           month,
           sum(trips) - sum(round_trips)  AS trips,
           sum(member_trips)              AS member_trips,
           max(n_origin_stations)         AS max_origin_stations,
           max(n_dest_stations)           AS max_dest_stations
    FROM analysis.bike_od_leakage
    WHERE origin_type = 'residential'
      AND (daypart = 'evening' OR day_type IN ('saturday', 'sunday'))
    GROUP BY 1, 2, 3
)
SELECT origin_nta,
       destination_nta,
       month,
       trips,
       member_trips,
       trips::DOUBLE / nullif(sum(trips) OVER (PARTITION BY origin_nta, month), 0)
                                              AS share,
       destination_nta <> origin_nta          AS out_of_nta,
       max_origin_stations,
       max_dest_stations
FROM f
WHERE trips > 0;

-- ---------------------------------------------------------------------------
-- CARD MEASURES. NTA-grain values stamped on every address in the NTA (R3) --
-- the card must say "neighbourhood-wide", because it is not an address fact.
--
-- NULL, NEVER 0, where the origin NTA has no residential dock or too few trips
-- in the window. 0 would read as "riders here go nowhere"; the truth is "the
-- operator has not built a dock we can type here", which is caveat 2.
-- ---------------------------------------------------------------------------
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_od_top_nta       VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_od_top_nta_share DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_od_out_share     DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_od_window        VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_od_run_at        TIMESTAMP;
-- red-team 2026-09-15: the supplied-share denominator counts only trips landing in
-- measurable MN+BK NTAs; the dropped share is stored so the card can say so, and the
-- supply hash the measures were computed under is stamped so a closure sweep under an
-- unchanged window still triggers a rebuild.
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_od_outside_share DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_od_supply_hash   VARCHAR;

-- bike_od_supplied_share: of the outbound (non-round, out-of-NTA) evening and
-- weekend trips leaving residential docks in this address's NTA, the share that
-- land in NTAs where category c is present ABOVE the MN+BK median density (POIs
-- per address, from analysis.poi_supply_status with poi_status <> 'closed' --
-- the D94 gate). Computed only where c is MISSING at the address
-- (address_category.ratio > 1, D39); NULL everywhere else, and NULL where the
-- denominator is zero.
--
-- IT IS NOT EVIDENCE OF A GAP, and the pre-registered placebo says so: if the
-- value for category c tracks the OTHER categories' destination patterns as
-- well as its own, the measure is destination retail density wearing a mobility
-- costume and it ships as prose, not as a number.
ALTER TABLE analysis.address_category
    ADD COLUMN IF NOT EXISTS bike_od_supplied_share DOUBLE;

-- RE-APPLY AFTER EVERY SCREEN RE-RUN, exactly as 034's bike columns require:
-- `loci address-gaps` DELETEs and re-INSERTs analysis.address, which NULLs
-- every column above. `bike_od_run_at IS NULL` is the flag; the recovery is
-- `loci citibike od-measures --re-sweep`.
