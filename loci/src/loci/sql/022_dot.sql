-- ---------------------------------------------------------------------------
-- 022_dot.sql -- NYC DOT: the bi-annual pedestrian counts as an INGESTED
-- source, the traffic-camera REGISTRY, and the address-grain context columns
-- that hang off both.
--
-- Owner, 2026-09-13: "we need NYC DOT data, both the bi-annual and the camera
-- data."
--
-- Written by:
--   staging.dot_pedestrian_count   sources/cities/nyc/dot_pedestrian.py
--                                  (`loci dot-counts ingest`)
--   staging.dot_camera             sources/cities/nyc/dot_cameras.py
--                                  (`loci dot-cameras ingest`)
--   analysis.address.dot_*         model/address_dot_context.py
--                                  (`loci dot-counts address-context`)
-- ---------------------------------------------------------------------------
-- THE D61 / feedback_table_proliferation INVENTORY, BEFORE ADDING ANYTHING
--
-- Two new TABLES, both at genuinely new grains that no existing object holds:
--
--   staging.dot_pedestrian_count   (point x round x period). Nothing in the
--       warehouse holds an observed pedestrian count. staging.poi is an
--       establishment; analysis.address_transit_profile is MTA turnstile
--       ENTRIES at a station complex mapped to addresses -- a different
--       quantity (taps into the subway), a different geography (complexes),
--       and a modelled one. This is a person counted on a sidewalk by a human
--       being. It is also a TIME SERIES, 37 rounds deep, which no address- or
--       hex-grain table can carry as columns.
--
--   staging.dot_camera             (camera). One row per public NYCTMC
--       camera. No existing table holds a sensor. The frame-level samples the
--       sampler will produce are camera x timestamp, a third grain, and must
--       get their own table -- NOT columns here, and NOT a second copy of the
--       registry.
--
-- Zero new tables for the ADDRESS-GRAIN context. "Which count point / camera
-- is nearest, and how far" is one value per address, which is a MEASURE at an
-- existing grain, so it extends analysis.address exactly as homes_400m,
-- transit_entries_400m and walkshed_km2_400m do. A separate
-- analysis.address_dot_nearest table would be 295k rows restating the key of
-- a table that already has 295k rows.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS staging;

-- ---------------------------------------------------------------------------
-- staging.dot_pedestrian_count -- LONG form, one row per counted cell.
--
-- The feed is WIDE: one row per point, three new COLUMNS per round, named
-- inconsistently ('may_07_am', 'may_22_p_m', 'oct24_md', 'may26_pm'). The
-- column names are PARSED, never typed -- see dot_pedestrian.parse_round.
--
--   point_id      DOT's own `loc`. 1-100 are on-street, 101-114 are bridge
--                 midpoints. Stable across rounds; it is the point identity.
--   round         'YYYY-MM' of the count round ('2026-05'). Sorts
--                 chronologically as a string, so MAX(round) is the latest.
--                 The rounds are NOT evenly spaced: no September 2019 round,
--                 no May 2020 round (COVID), and 2024's spring round is JUNE.
--   period        'am' (07:00-09:00) | 'md' (12:00-14:00) | 'pm' (16:00-19:00).
--                 PM IS THREE HOURS AND THE OTHER TWO ARE TWO. The three are
--                 not interchangeable units and must never be averaged as if
--                 they were; summing them gives "people observed in the
--                 round's seven counted hours", which is the only whole-round
--                 quantity that means anything.
--   count         people crossing the screenline in that window, counted by
--                 hand. NOT scaled to a day: DOT publishes no expansion
--                 factor and none should be invented.
--   lon, lat      EPSG:4326 by convention -- DuckDB GEOMETRY carries no SRID
--                 and these are plain DOUBLEs, so the convention is held in
--                 code or not at all.
--   is_bridge     point_id > 100. Bridge midpoints are INGESTED and excluded
--                 by consumers, not dropped at the door.
--   loc_type      'on_street' | 'east_river_bridge' | 'harlem_river_bridge',
--                 derived from `loc` and the borough label together (DOT
--                 publishes no location type); 'bridge_disputed' if the two
--                 signals ever disagree.
--   is_index      the feed's own `iex` Y/N flag, carried verbatim and
--                 uninterpreted (DOT's dictionary does not define it; it
--                 partitions the points 50/64).
--   source_field  the ORIGINAL column name this cell came from. Provenance,
--                 and the seam that lets validation/pedestrian_counts.py
--                 reconstruct the feed's wide shape from the warehouse and
--                 keep its output byte-identical.
--
-- A NULL cell produces NO ROW (Socrata omits the key; 342 of 12,654 possible
-- cells are absent, and a point added in 2020 has no 2007 row). A ZERO count
-- produces a row -- twelve exist and they are observations, not gaps.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.dot_pedestrian_count (
    point_id      INTEGER   NOT NULL,
    round         VARCHAR   NOT NULL,     -- 'YYYY-MM'
    period        VARCHAR   NOT NULL,     -- am | md | pm
    count         INTEGER   NOT NULL,     -- 0 is a count, not a gap
    lon           DOUBLE,
    lat           DOUBLE,
    borough       VARCHAR,
    street        VARCHAR,
    from_street   VARCHAR,
    to_street     VARCHAR,
    is_bridge     BOOLEAN,
    loc_type      VARCHAR,
    is_index      BOOLEAN,
    source_field  VARCHAR,
    ingested_at   TIMESTAMP,
    PRIMARY KEY (point_id, round, period)
);

-- ---------------------------------------------------------------------------
-- staging.dot_camera -- the NYCTMC public camera registry.
--
-- THE SAMPLER'S CONTRACT. A separate build fetches frames and detects people
-- against exactly these columns; camera_id is its key and image_url is what it
-- fetches (no auth, 200 image/jpeg, Cache-Control: no-store, a different
-- payload on every request -- verified 2026-09-13).
--
--   is_online   parsed from the feed's STRING 'true'/'false'. 969/969 read
--               true at verification, which is not a plausible steady state
--               for 969 outdoor cameras -- treat it as "published", not as
--               "returning frames", and never filter a universe on it.
--   lon, lat    EPSG:4326, the POLE's position. What the camera SEES is an
--               unknown distance away in an unknown direction: the feed
--               publishes no bearing, field of view, height or lens.
--   borough     the project's two-letter code, mapped from `area`, so this
--               joins analysis.address.borough. NULL (never a guess) if the
--               area string is unrecognised; `area` keeps the raw value.
--   fetched_at  when this snapshot was taken. The feed carries no vintage and
--               no changelog; a camera_id that disappears from a later pull
--               is simply gone and cannot be told from one temporarily
--               unpublished.
--
-- Per-frame observations are camera x timestamp and belong in their own
-- table. Do not add a `last_person_count` column here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.dot_camera (
    camera_id   VARCHAR PRIMARY KEY,
    name        VARCHAR,
    lon         DOUBLE,
    lat         DOUBLE,
    image_url   VARCHAR,
    is_online   BOOLEAN,
    area        VARCHAR,
    borough     VARCHAR,
    fetched_at  TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- analysis.address -- the DOT context columns. UPDATE-only, never a filter.
--
-- STRAIGHT-LINE DISTANCE, AND THIS IS THE ONE PLACE IN THE PROJECT WHERE THAT
-- IS TRUE. homes_400m, transit_entries_400m, jobs_400m, storefronts_400m and
-- supply_ratio are all NETWORK distance on the pedestrian walk graph, because
-- a straight-line 400 m in Manhattan can cross an avenue that takes 600 m of
-- walking to get around. These two columns are EUCLIDEAN metres in EPSG:32618
-- (UTM 18N), i.e. as the crow flies, and are therefore a LOWER BOUND on the
-- walk: dot_point_m = 180 can be a 300 m walk, and across a rail cut or a
-- highway it can be much worse. They are deliberately not network distances --
-- 114 points and 969 cameras do not justify a 40-minute Dijkstra, and the
-- question these answer ("is there an observation anywhere near here") is not
-- a catchment question. Do not compare these numbers to a *_400m column.
--
--   dot_point_id      nearest ON-STREET count point (bridge midpoints are
--                     excluded: the middle of the Williamsburg Bridge is
--                     nobody's nearest sidewalk observation).
--   dot_point_m       straight-line metres to it. UNCAPPED -- most of the
--                     city is kilometres from any count point and the honest
--                     number is large, not NULL.
--   dot_latest_round  the latest round at THAT POINT carrying all three
--                     periods, which is not necessarily the feed's latest
--                     round (points enter and leave the programme).
--   dot_latest_am/md/pm  that round's three counts.
--   camera_id         nearest camera, camera_m its straight-line metres.
--   dot_context_run_at   NULL means the command has never run for this row.
--
-- CONTEXT, NOT A SIGNAL. Nothing here enters gap_score, supply_ratio_vs_base,
-- a grade or a rank. An address does not become a gap because DOT counts
-- pedestrians 80 m away, and being 3 km from the nearest count point is a
-- fact about DOT's programme, not about the address.
-- ---------------------------------------------------------------------------
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS dot_point_id       INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS dot_point_m        REAL;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS dot_latest_round   VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS dot_latest_am      INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS dot_latest_md      INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS dot_latest_pm      INTEGER;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS camera_id          VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS camera_m           REAL;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS dot_context_run_at TIMESTAMP;
