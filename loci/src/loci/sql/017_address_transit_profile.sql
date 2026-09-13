-- ---------------------------------------------------------------------------
-- 017_address_transit_profile.sql -- walkable subway entries at address grain
-- BY DAY TYPE AND TIME OF DAY, plus the persisted reachable-entrance set that
-- makes every future variant a join instead of an hour of Dijkstra.
--
-- Written only by model/address_transit_profile.py (`loci transit-profile`).
-- Never by the screen. Nothing here enters gap_score, supply_ratio_vs_base or
-- any recommendation grade.
-- ---------------------------------------------------------------------------
-- WHY TWO NEW TABLES AND NOT MORE COLUMNS (owner rule, D61 inventory)
--
-- The rule is: a PIVOT of an existing grain is a view, a new MEASURE at an
-- existing grain extends that grain, and only a genuinely new grain earns a
-- table. `address x day_type x daypart` is a grain the warehouse does not
-- have -- analysis.address is one row per address, analysis.address_category
-- one row per address per category -- and folding fifteen cells into
-- analysis.address would be fifteen columns, which is exactly the
-- pivot-shaped duplication D61 removed, wearing a wider hat. So: ONE long
-- table, and analysis.address_transit_profile_wide is the view for the pivot.
--
-- `transit_am_pm_share_400m` IS one number per address, so it extends
-- analysis.address, by the same rule.
-- ---------------------------------------------------------------------------
-- UNITS AND MEANING
--
--   day_type   'weekday' | 'saturday' | 'sunday'. Federal holidays are
--              EXCLUDED from the window entirely and belong to no day type --
--              Thanksgiving is not a Thursday observation. Every holiday in
--              the exclusion list is an OBSERVED date and therefore Mon-Fri,
--              so the exclusion touches the weekday mean only.
--
--   daypart    'early' 00-06 | 'am_peak' 06-10 | 'midday' 10-15 |
--              'pm_peak' 15-19 | 'evening' 19-24. Half-open [start, end), and
--              they PARTITION the 24-hour day, which is what makes the
--              conservation check meaningful: the five weekday cells re-sum to
--              analysis.address.transit_entries_400m exactly.
--
--              The edges are chosen so each NYC DOT bi-annual count window
--              falls strictly inside one daypart -- AM 07-09 c am_peak,
--              MD 12-14 c midday, PM 16-19 c pm_peak -- so
--              `loci validate-pedestrian` can compare a counted window to a
--              measured one without interpolating. They are WIDER than DOT's
--              windows deliberately: a ridership peak genuinely runs four
--              hours, and narrowing to a hand count's two would push plainly
--              peak hours into 'early' and 'evening'.
--
--   transit_entries_400m   people entering the subway on an AVERAGE DAY OF
--              THAT TYPE, during that daypart, at entrances within 400 m
--              NETWORK metres. Same units, same radius, same entrance set and
--              same even split as the scalar column of the same name on
--              analysis.address -- this is that number cut fifteen ways, not a
--              different measure. ENTRIES, never footfall, and still only the
--              tap-IN direction: splitting by hour does NOT recover the
--              evening ARRIVAL flow, which is published nowhere per station.
--
--   dist_m     network walking metres from the address to that entrance. Not
--              read by anything today; carried because it is free at sweep
--              time and is the only thing that makes a distance-decay kernel
--              possible later without re-sweeping.
--
--   n.b. analysis.address_entrance stores GEOMETRY-ONLY facts (which doors an
--   address can walk to, how far). It deliberately does NOT store a weight:
--   the window, the daypart boundaries and the even-split convention all move,
--   and the persisted geometry must outlive all three.
-- ---------------------------------------------------------------------------
-- SPARSE, AND WHY THAT IS NOT AN ELIGIBILITY GATE (D75, owner ruling)
--
-- Rows exist only for addresses with at least one reachable entrance. An
-- address ABSENT from these tables has 0.0 in all fifteen cells: a REAL
-- observation ("no station within a five-minute walk"), the same convention
-- analysis.address.transit_entries_400m already uses. Materialising the zeros
-- would be ~11.5M rows to restate an absence, for a measure that is zero on
-- 65% of Brooklyn.
--
-- The universe is NOT reduced. analysis.address_transit_profile_wide LEFT
-- JOINs analysis.address and COALESCEs to 0.0, so every address appears there
-- with a value, and nothing is ever ranked or filtered by presence in the long
-- table. Read the VIEW for the universe; read the TABLE for the rows that
-- carry signal. The validation query in model/address_transit_profile.py
-- asserts that every address absent from the long table has a stored
-- transit_entries_400m of 0.
-- ---------------------------------------------------------------------------
-- RE-APPLY AFTER EVERY SCREEN RE-RUN. `loci address-gaps` DELETEs and
-- re-INSERTs analysis.address, which orphans every row here and NULLs the two
-- columns below. `transit_profile_run_at IS NULL` is the flag. Run
-- `loci address-access` FIRST (this build asserts against the column it
-- writes) and `loci transit-profile` after it.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.address_entrance (
    address_id     VARCHAR,
    borough        VARCHAR,       -- only so the rebuild's DELETE can be scoped
    entrance_id    VARCHAR,       -- '<complex_id>@<lon>,<lat>' | 'complex:<id>'
    complex_id     VARCHAR,
    dist_m         DOUBLE,        -- NETWORK metres on the pedestrian walk graph
    radius_m       REAL,          -- the cap the sweep actually used
    graph_version  VARCHAR,       -- which walk graph produced these distances
    run_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis.address_transit_profile (
    address_id             VARCHAR,
    borough                VARCHAR,
    day_type               VARCHAR,   -- weekday | saturday | sunday
    daypart                VARCHAR,   -- early | am_peak | midday | pm_peak | evening
    transit_entries_400m   DOUBLE,    -- entries per AVERAGE day of that type
    radius_m               REAL,
    transit_entries_window VARCHAR,   -- e.g. '2026-06-01..2026-08-31'
    transit_entries_snap   VARCHAR,   -- 'entrances' | 'complex'
    profile_run_at         TIMESTAMP
);

-- AM/PM share: weekday am_peak entries / weekday pm_peak entries, summed over
-- the address's reachable entrances (so it is ENTRIES-WEIGHTED by
-- construction, not a mean of per-station ratios).
--   > 1  more people tap IN in the morning  -> RESIDENTIAL catchment
--   < 1  the evening is bigger              -> JOB-CENTRE catchment
-- NULL, never 0 and never infinity, where pm_peak is 0 -- including every
-- address with no station within 400 m. A station with no evening entries has
-- no ratio, and substituting a number would invent one.
-- It is a CLASSIFIER OF TYPE, not a level, and must never be summed, averaged
-- unweighted across addresses, or fed to a score.
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS transit_am_pm_share_400m DOUBLE;
-- NULL means `loci transit-profile` has never run for this borough (or a
-- screen re-run has destroyed the rows). NOT NULL with a NULL share means the
-- run happened and the ratio does not exist for that address.
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS transit_profile_run_at   TIMESTAMP;

-- The pivot, as a VIEW (D61: a pivot of an existing grain is never a table).
-- LEFT JOIN + COALESCE, so EVERY address in analysis.address appears exactly
-- once with a value, including the 65% of Brooklyn whose value is zero.
CREATE OR REPLACE VIEW analysis.address_transit_profile_wide AS
WITH p AS (
    SELECT address_id,
           sum(transit_entries_400m) FILTER (day_type='weekday'  AND daypart='early')    AS weekday_early,
           sum(transit_entries_400m) FILTER (day_type='weekday'  AND daypart='am_peak')  AS weekday_am_peak,
           sum(transit_entries_400m) FILTER (day_type='weekday'  AND daypart='midday')   AS weekday_midday,
           sum(transit_entries_400m) FILTER (day_type='weekday'  AND daypart='pm_peak')  AS weekday_pm_peak,
           sum(transit_entries_400m) FILTER (day_type='weekday'  AND daypart='evening')  AS weekday_evening,
           sum(transit_entries_400m) FILTER (day_type='saturday' AND daypart='early')    AS saturday_early,
           sum(transit_entries_400m) FILTER (day_type='saturday' AND daypart='am_peak')  AS saturday_am_peak,
           sum(transit_entries_400m) FILTER (day_type='saturday' AND daypart='midday')   AS saturday_midday,
           sum(transit_entries_400m) FILTER (day_type='saturday' AND daypart='pm_peak')  AS saturday_pm_peak,
           sum(transit_entries_400m) FILTER (day_type='saturday' AND daypart='evening')  AS saturday_evening,
           sum(transit_entries_400m) FILTER (day_type='sunday'   AND daypart='early')    AS sunday_early,
           sum(transit_entries_400m) FILTER (day_type='sunday'   AND daypart='am_peak')  AS sunday_am_peak,
           sum(transit_entries_400m) FILTER (day_type='sunday'   AND daypart='midday')   AS sunday_midday,
           sum(transit_entries_400m) FILTER (day_type='sunday'   AND daypart='pm_peak')  AS sunday_pm_peak,
           sum(transit_entries_400m) FILTER (day_type='sunday'   AND daypart='evening')  AS sunday_evening,
           max(transit_entries_window) AS transit_entries_window,
           max(transit_entries_snap)   AS transit_entries_snap
    FROM analysis.address_transit_profile
    GROUP BY 1
)
SELECT a.address_id,
       a.borough,
       -- the scalar column, unchanged; weekday_* below must re-sum to it
       a.transit_entries_400m                  AS weekday_all_day,
       COALESCE(p.weekday_early,    0.0)       AS weekday_early,
       COALESCE(p.weekday_am_peak,  0.0)       AS weekday_am_peak,
       COALESCE(p.weekday_midday,   0.0)       AS weekday_midday,
       COALESCE(p.weekday_pm_peak,  0.0)       AS weekday_pm_peak,
       COALESCE(p.weekday_evening,  0.0)       AS weekday_evening,
       COALESCE(p.saturday_early,   0.0) + COALESCE(p.saturday_am_peak, 0.0)
         + COALESCE(p.saturday_midday, 0.0) + COALESCE(p.saturday_pm_peak, 0.0)
         + COALESCE(p.saturday_evening, 0.0)   AS saturday_all_day,
       COALESCE(p.saturday_early,   0.0)       AS saturday_early,
       COALESCE(p.saturday_am_peak, 0.0)       AS saturday_am_peak,
       COALESCE(p.saturday_midday,  0.0)       AS saturday_midday,
       COALESCE(p.saturday_pm_peak, 0.0)       AS saturday_pm_peak,
       COALESCE(p.saturday_evening, 0.0)       AS saturday_evening,
       COALESCE(p.sunday_early,     0.0) + COALESCE(p.sunday_am_peak, 0.0)
         + COALESCE(p.sunday_midday, 0.0) + COALESCE(p.sunday_pm_peak, 0.0)
         + COALESCE(p.sunday_evening, 0.0)     AS sunday_all_day,
       COALESCE(p.sunday_early,     0.0)       AS sunday_early,
       COALESCE(p.sunday_am_peak,   0.0)       AS sunday_am_peak,
       COALESCE(p.sunday_midday,    0.0)       AS sunday_midday,
       COALESCE(p.sunday_pm_peak,   0.0)       AS sunday_pm_peak,
       COALESCE(p.sunday_evening,   0.0)       AS sunday_evening,
       a.transit_am_pm_share_400m,
       p.transit_entries_window,
       p.transit_entries_snap,
       a.transit_profile_run_at
FROM analysis.address a
LEFT JOIN p USING (address_id);
