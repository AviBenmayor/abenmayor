-- ---------------------------------------------------------------------------
-- 034_citibike.sql -- Citi Bike trips as a two-directional, dock-grain movement
-- series, and the address-grain measures that hang off it.
--
-- Owner, 2026-09-14: Citi Bike phase 1 approved.
--
-- Written by:
--   staging.citibike_station_month   sources/cities/nyc/citibike.py
--                                    (`loci citibike ingest`)
--   staging.citibike_station         same command, derived from the above
--   analysis.address_bike_station    model/address_bike.py
--                                    (`loci citibike address-measures`)
--   analysis.address.bike_*          same command, UPDATE-only
-- ---------------------------------------------------------------------------
-- THE D61 / feedback_table_proliferation INVENTORY, BEFORE ADDING ANYTHING
--
-- TWO staging tables, both at grains nothing in the warehouse holds:
--
--   staging.citibike_station_month  (station x month x day_type x daypart).
--       The nearest thing is analysis.address_transit_profile, which is a
--       MODELLED address-grain allocation of subway ENTRIES for ONE three-month
--       window. This is an OBSERVED count of trips at a DOCK, over a multi-year
--       monthly panel, and it is two-directional (a start and an end are
--       different events at different times). Neither table can hold the other.
--
--   staging.citibike_station        (station). The dock roster with its life
--       span. Not derivable from the month table without a scan, read by the
--       map export and by every "is this dock new" question.
--
-- ONE analysis table, for the same reason analysis.address_entrance exists:
--
--   analysis.address_bike_station   (address x dock x network metres). The
--       expensive object here is the Dijkstra sweep over every address, not the
--       trip file. Persisting the reachable set makes a different window, a
--       different weighting or a distance-decay kernel a JOIN rather than
--       another hour of Dijkstra -- exactly the argument 017 records for
--       analysis.address_entrance.
--
-- ZERO new tables for the address-grain measures: four numbers per address is a
-- MEASURE at an existing grain, so they extend analysis.address as homes_400m,
-- transit_entries_400m and jobs_400m do. They are category-INDEPENDENT (the
-- same docks are within 400 m whether you are asking about pharmacies or bars),
-- so putting them on analysis.address_category would be fifteen identical
-- copies of one number.
--
-- DELIBERATELY NOT BUILT IN PHASE 1: a long address x day_type x daypart bike
-- profile. That grain ALREADY EXISTS -- it is analysis.address_transit_profile
-- -- so the correct home for a bike daypart shape is extra COLUMNS on that
-- table, not a second table beside it. It is not done here only because that
-- table is DELETE-then-INSERTed by `loci transit-profile`, and two builders
-- scoping their own DELETEs over one table needs a ruling, not a patch.
-- ---------------------------------------------------------------------------
-- UNITS AND MEANING, because the column names cannot carry it
--
--   month        the FIRST DAY of the calendar month, as a DATE. A date, not a
--                'YYYY-MM' string, so ordering, differencing and a BETWEEN
--                window are arithmetic rather than string surgery.
--
--   day_type     'weekday' | 'saturday' | 'sunday'. Federal holidays are
--                EXCLUDED from the panel entirely and belong to NO day type,
--                exactly as in 017. Every observed federal holiday is Mon-Fri,
--                so the exclusion touches the weekday cells only.
--
--   daypart      'early' 00-06 | 'am_peak' 06-10 | 'midday' 10-15 |
--                'pm_peak' 15-19 | 'evening' 19-24, half-open and partitioning
--                the day. THE SAME FIVE INTERVALS AS 017, rendered from the
--                same Python tuple (sources/.../citibike.daypart_case_sql), so
--                a bike cell, a subway cell and a DOT count window can appear
--                in one row of `loci validate-bike` without interpolation.
--
--   starts/ends  TRIPS, counted at the dock. A start is dated by `started_at`;
--                an end by `ENDED_AT`, because the arrival is the event -- a
--                00:40 arrival is an `early` fact, not a `pm_peak` one. These
--                are RAW COUNTS FOR THE MONTH, not rates: divide by
--                days_in_cell for a per-day number.
--
--   days_in_cell the number of non-holiday dates OF THAT DAY TYPE in that
--                month, FROM THE CALENDAR. Identical for all five dayparts of a
--                (station, month, day_type) and identical across stations. It
--                is the calendar and not the observed date count on purpose: a
--                dock that saw no Tuesday rides must not thereby earn a higher
--                daily average. A dock installed mid-month therefore reads LOW
--                that month, which is correct -- it was not there.
--
--   lon/lat      the MODAL published coordinate of that dock in that month,
--                EPSG:4326 (DuckDB GEOMETRY carries no SRID; the convention is
--                held in code). Modal and per-month because docks are moved a
--                few metres and occasionally around a corner.
--
--   NOTE the station_name/lon/lat repeat across the fifteen cells of a
--   station-month. That denormalisation is deliberate and cheap (~2,300
--   stations x 15): it makes a station-month's published position auditable
--   from the fact table alone, without a join to a roster that a later ingest
--   may have moved.
-- ---------------------------------------------------------------------------
-- WHAT THIS SOURCE IS NOT
--
-- NOT A PEDESTRIAN COUNT. It counts people who chose a bike, held a membership
-- or a card, and found a free dock. DOCK PLACEMENT is the dominant term in any
-- geographic comparison -- a neighbourhood with no docks reads zero because the
-- operator has not built there, not because nobody walks there -- and dock
-- placement is correlated with income. Dock capacity censors the count at
-- exactly the busiest station-hours (a full dock turns an arrival into an
-- arrival somewhere else). Rebalancing trucks move bikes and are not trips.
-- Read these numbers as RELATIVE busyness where there are docks. They are
-- CARD CONTEXT, on the same footing as transit_entries_400m under D76: nothing
-- here enters gap_score, supply_ratio_vs_base or any recommendation grade.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS staging.citibike_station_month (
    station_id     VARCHAR,     -- the 2021+ scheme, e.g. '5905.14'. Pre-2021 ids
                                -- are a DIFFERENT integer space and are refused,
                                -- never fused (see the source module).
    station_name   VARCHAR,     -- modal name in that month
    lon            DOUBLE,      -- EPSG:4326 by convention
    lat            DOUBLE,
    month          DATE,        -- first day of the calendar month
    day_type       VARCHAR,     -- weekday | saturday | sunday
    daypart        VARCHAR,     -- early | am_peak | midday | pm_peak | evening
    starts         BIGINT,      -- trips DEPARTING this dock in the cell
    ends           BIGINT,      -- trips ARRIVING at this dock in the cell
    member_starts  BIGINT,
    casual_starts  BIGINT,
    member_ends    BIGINT,
    casual_ends    BIGINT,
    days_in_cell   SMALLINT,    -- calendar days of that day type in that month
    ingested_at    TIMESTAMP
);

-- The dock roster. `lon`/`lat`/`name` are taken from the station's MOST RECENT
-- active month, not the modal month over its life: the address measures are a
-- present-day walk distance, so a dock that moved across the street in 2024
-- must be measured where it is now.
CREATE TABLE IF NOT EXISTS staging.citibike_station (
    station_id     VARCHAR,
    name           VARCHAR,
    lon            DOUBLE,
    lat            DOUBLE,
    first_month    DATE,
    last_month     DATE,
    months_active  INTEGER,     -- months with >= 1 trip; NOT last-first+1, so a
                                -- dock removed and reinstalled reads honestly
    ingested_at    TIMESTAMP
);

-- The persisted reachable set: which docks an address can WALK to, and how far.
-- Geometry-only, exactly like analysis.address_entrance -- no weights, because
-- the window, the day type and the member/casual split all move and the
-- distances must outlive all three.
CREATE TABLE IF NOT EXISTS analysis.address_bike_station (
    address_id     VARCHAR,
    borough        VARCHAR,     -- only so the rebuild's DELETE can be scoped
    station_id     VARCHAR,
    dist_m         DOUBLE,      -- NETWORK metres on the pedestrian walk graph
    radius_m       REAL,
    graph_version  VARCHAR,
    run_at         TIMESTAMP
);

-- bike_starts_400m / bike_ends_400m: trips DEPARTING / ARRIVING at docks within
-- 400 m NETWORK metres, per AVERAGE WEEKDAY, pooled over the window (total
-- weekday trips / total weekday days, NOT a mean of monthly means, so a month
-- is weighted by the days it actually has).
--
-- ZERO IS AN OBSERVATION, NULL IS NOT A THING HERE (owner rule 2026-09-13: no
-- eligibility gate). Every address in scope gets both numbers; 0 means "no dock
-- within a five-minute walk", which is a measurement about the OPERATOR'S
-- network, not about the sidewalk. NULL means the command has not been run.
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_starts_400m DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_ends_400m   DOUBLE;

-- bike_evening_ends_share_400m: (ends in `evening` on any day type, PLUS all
-- saturday/sunday ends) / all ends, over the window. A DESTINATION signal: a
-- commuter dock empties in the evening and fills in the morning, while a
-- nightlife or shopping corner takes its arrivals after work and at weekends.
-- The union is counted ONCE -- a Saturday evening arrival is one arrival, not
-- two -- so the value is a genuine share in [0, 1].
--
-- NULL, never 0, where the address has NO ends at all (no dock within 400 m, or
-- docks that nobody arrived at in the window). A ratio with no denominator does
-- not exist, and substituting 0 would invent a "pure commuter dock" reading.
-- Same rule as transit_am_pm_share_400m in 017.
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_evening_ends_share_400m DOUBLE;

-- bike_casual_share_400m: casual starts / all starts within 400 m, over the
-- window. NULL where there are no starts. A member is anyone with a
-- subscription and a casual rider anyone on a single ride or day pass, so this
-- is NOT resident-vs-visitor: it reads high in tourist geography and at
-- weekend-destination docks, and it is a mixture of both.
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_casual_share_400m DOUBLE;

-- Provenance the numbers cannot carry themselves.
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_window   VARCHAR;   -- '2025-09..2026-08'
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_radius_m REAL;      -- what the run used
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bike_run_at   TIMESTAMP; -- NULL = never run

-- RE-APPLY AFTER EVERY SCREEN RE-RUN. `loci address-gaps` DELETEs and
-- re-INSERTs analysis.address, which orphans analysis.address_bike_station and
-- NULLs the columns above. `bike_run_at IS NULL` is the flag; the recovery is
-- `loci citibike address-measures --re-sweep`.
