-- ---------------------------------------------------------------------------
-- 044_citibike_legacy.sql -- the pre-2021 Citi Bike era, and the legacy -> modern
-- station crosswalk that is allowed to stay INCOMPLETE.
--
-- Owner rule, 2026-09-16, verbatim: "your goal is to have AS MUCH AS DATA AS
-- POSSIBLE" / "never ever ever limit data pulls". `citibike.py` carried two
-- caps: a default start of 2023-01 and a 2021-02 floor that RAISED on any
-- earlier month. Both are gone. The bucket publishes 2013-06 onward and all of
-- it is now ingestable.
--
-- Written by:
--   staging.citibike_station_month.station_id_legacy / .era
--                                     sources/cities/nyc/citibike.py
--                                     (`loci citibike ingest`)
--   staging.citibike_station_legacy   `loci citibike crosswalk`
--   staging.citibike_station_crosswalk  same command
--
-- MIGRATION NUMBERS 042 and 043 ARE CLAIMED BY ANOTHER SESSION (2026-09-16).
-- ---------------------------------------------------------------------------
-- WHY THE LEGACY ID GETS ITS OWN COLUMN, AND NEVER station_id
--
-- The pre-2021 files key on SMALL INTEGERS (`3002`, `444`). The 2021+ files key
-- on the Lyft scheme (`5905.14`, and also plain integers). The two spaces
-- OVERLAP AND MEAN DIFFERENT THINGS: legacy `3002` is South End Ave & Liberty
-- St; modern `3002` is a different dock entirely. There is no published
-- crosswalk.
--
-- Putting both in `station_id` would do exactly one of two things, both fatal
-- and both silent:
--   * split one dock into two rows -- inventing a dock that "opened" in
--     2021-02 and a gap in front of it; or
--   * fuse two distinct docks -- inventing a doubling.
-- That is the dedup-fuses-distinct-storefronts bug (D72) in its purest form, so
-- the eras are kept in separate columns and joined only through an EVIDENCED
-- crosswalk row.
--
--   era = 'lyft'    station_id populated, station_id_legacy NULL
--   era = 'legacy'  station_id_legacy populated; station_id populated ONLY
--                   where the crosswalk matched, NULL otherwise
--
-- `era` is added with DEFAULT 'lyft' so the 2021+ rows already in the table get
-- the right value ONCE, at the ALTER, and not on every connection. Everything
-- here is IF NOT EXISTS: db.init_schema re-applies every migration on every
-- write connection, so a migration that rewrote rows would rewrite them on
-- every open.
-- ---------------------------------------------------------------------------
-- WHAT THE PANEL IS AFTER THIS, AND WHAT IT IS NOT
--
-- staging.citibike_station (the roster) and every address measure built from it
-- STILL READ THE LYFT ERA ONLY. That is deliberate and it is not timidity:
--   * the address measures are a present-day walk distance over the LATEST 12
--     months (034), which never touches 2013-2020;
--   * model/address_bike_growth.py gates on `first_month <= M-23`, so silently
--     extending first_month to 2013 would change which docks are eligible for
--     a measure that is already built and published.
-- The legacy era is therefore LANDED IN FULL and read explicitly, by anything
-- that asks for it, rather than leaking into a measure that was defined on a
-- different panel. `staging.citibike_station_legacy` carries the legacy roster
-- and its life span.
-- ---------------------------------------------------------------------------

ALTER TABLE staging.citibike_station_month
    ADD COLUMN IF NOT EXISTS station_id_legacy VARCHAR;
ALTER TABLE staging.citibike_station_month
    ADD COLUMN IF NOT EXISTS era VARCHAR DEFAULT 'lyft';

-- The LEGACY dock roster, derived wholly from the legacy rows of the month
-- table. Same shape and same rule as staging.citibike_station: name and
-- position come from the dock's MOST RECENT ACTIVE legacy month, because a dock
-- that moved must be described where it last stood.
CREATE TABLE IF NOT EXISTS staging.citibike_station_legacy (
    station_id_legacy VARCHAR,
    name              VARCHAR,
    lon               DOUBLE,     -- EPSG:4326 by convention (no SRID in DuckDB)
    lat               DOUBLE,
    first_month       DATE,
    last_month        DATE,
    months_active     INTEGER,    -- months with >= 1 trip
    trips             BIGINT,     -- starts + ends over the legacy era
    ingested_at       TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- THE CROSSWALK. It is allowed to be INCOMPLETE and it is NOT allowed to guess.
--
-- The join is station NAME plus COORDINATES, which is precisely the kind of
-- join that has fused distinct records in this project before. So it is
-- conservative by construction and every row carries the evidence for itself:
--
--   method = 'name_and_position'   normalised names EQUAL and the two points
--                                  within XW_STRICT_M (35 m). confidence 1.00.
--   method = 'position_only'       names differ but the points are within
--                                  XW_STRICT_M and the match is MUTUALLY
--                                  NEAREST. confidence 0.60. A dock really was
--                                  renamed ("W 52 St & 11 Ave" -> "W 52 St &
--                                  11 Av") and a rename is not a new dock.
--   method = 'name_only'           normalised names EQUAL, points 35..150 m
--                                  apart, and the name is UNIQUE on both sides.
--                                  confidence 0.50. A dock moved across the
--                                  street; the corner did not.
--
-- THE THREE RULES THAT KEEP IT FROM FUSING DISTINCT DOCKS:
--   1. ONE-TO-ONE, ENFORCED. A legacy id maps to at most one modern id and a
--      modern id is claimed by at most one legacy id. Ambiguous candidates are
--      dropped, not arbitrated: `loci citibike crosswalk` reports them.
--   2. MUTUAL NEAREST for any position-based match. "The nearest modern dock to
--      this legacy dock" is not enough -- two legacy docks on one corner would
--      both claim it.
--   3. A HARD DISTANCE CEILING. Nothing beyond XW_MAX_M (150 m) is ever a
--      match, at any confidence. Two docks 200 m apart are two docks.
--
-- distance_m IS COMPUTED IN METRES, EXPLICITLY REPROJECTED. DuckDB GEOMETRY
-- carries NO SRID, everything stored is EPSG:4326 by convention, and
-- ST_Distance_Sphere reads POINT(x, y) as (LATITUDE, LONGITUDE) -- our points
-- are (lon, lat). Both sides must be flipped or every distance is computed at
-- the equator (1 degree of longitude reads 111 km instead of 84 km at New York,
-- a 32% understatement of every east-west gap). That is decision D16 and the
-- one legal spelling is `loci.db.METRES_SQL`; see
-- sources/cities/nyc/citibike_crosswalk.py.
--
-- AN UNMATCHED LEGACY DOCK IS NOT AN ERROR AND NEVER DROPS A MONTH. If the
-- match rate is under 90% the legacy months are landed anyway, with
-- station_id_legacy populated and station_id NULL. A missing crosswalk row
-- costs a join; a dropped month costs the data.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.citibike_station_crosswalk (
    station_id_legacy VARCHAR,   -- pre-2021 integer id
    station_id        VARCHAR,   -- 2021+ Lyft id, NULL where nothing matched
    name_legacy       VARCHAR,
    name_modern       VARCHAR,
    lon_legacy        DOUBLE,    -- EPSG:4326
    lat_legacy        DOUBLE,
    lon_modern        DOUBLE,
    lat_modern        DOUBLE,
    distance_m        DOUBLE,    -- METRES, via loci.db.METRES_SQL (D16)
    name_match        BOOLEAN,   -- normalised names equal
    method            VARCHAR,   -- name_and_position | position_only | name_only
                                 -- | unmatched_* (why it did not match)
    confidence        DOUBLE,    -- 1.00 / 0.60 / 0.50; 0.0 for an unmatched row
    legacy_trips      BIGINT,    -- starts+ends behind this legacy dock, so the
                                 -- match rate can be weighted by volume and not
                                 -- only by dock count
    run_at            TIMESTAMP
);
