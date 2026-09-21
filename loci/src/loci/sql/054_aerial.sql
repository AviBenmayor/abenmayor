-- ---------------------------------------------------------------------------
-- 054_aerial.sql -- what the free aerial sources yield at the BBL grain
-- (scope memo 2026-09-17 §2, §4, §5 items 3-5; owner rulings the same day).
--
-- Four objects. One staging table for the source everything else joins on,
-- three analysis measures at the lot / building grain. ALL THREE MEASURES
-- ARE CARD CONTEXT ONLY: nothing here enters gap_score, supply_ratio_vs_base
-- or any recommendation grade, and each carries its memo §5 gate in its
-- catalog comment ("ungated: owner review pending") until the owner has
-- checked the review page the builder produced.
--
-- staging.building_footprint    NYC Building Footprints (5zhs-2jue), citywide,
--                               one row per BIN. height_roof is FEET.
-- analysis.lot_aerial_change    ortho 2022 -> 2024 ground change on a lot:
--                               fraction of the lot's pixels that changed
--                               after histogram matching, and a coarse class.
--                               Grain: one BBL x (ortho_from, ortho_to).
-- analysis.building_awning      projecting awnings on a building's street
--                               face(s) in the 2024 ortho. Grain: one BIN.
-- analysis.lot_convertible      one-storey, big-footprint, parking/vacant lots
--                               (the A8 step-5 floorplates). Grain: one BBL.
--
-- WHY BBL/BIN AND NOT address_id. These are facts about a LOT or a BUILDING
-- (a footprint has no address_id; a permitted lot is a BBL in
-- analysis.dev_pipeline). analysis.address carries bbl for its lot frame, so
-- the join to the address grain is one equality and no new grain is
-- invented (D61: measures extend the address grain; subsets are views).
--
-- THE TWO-YEAR BIN DATES NOTHING. "changed between the March 2022 and March
-- 2024 flights" is the whole of what change_frac can say. A shed, a shadow,
-- a parked truck and a tarpaulin all change pixels; the class is a heuristic
-- and the review page exists because of that.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS staging.building_footprint (
    bin               VARCHAR,             -- Building Identification Number
    bbl               VARCHAR,             -- base_bbl: the PLUTO join key
    mappluto_bbl      VARCHAR,
    geom              GEOMETRY,            -- MultiPolygon, EPSG:4326
    height_roof_ft    DOUBLE,              -- FEET, highest roof point above ground
    ground_elev_ft    DOUBLE,
    construction_year INTEGER,             -- pre-2017 is RPAD, not imagery
    feature_code      VARCHAR,             -- 2100 building | 5100 garage | 5110 shed | ...
    last_status       VARCHAR,             -- Constructed | Demolition | Alteration | ...
    last_edited       TIMESTAMP,
    geom_source       VARCHAR,
    shape_area_sqft   DOUBLE,
    doitt_id          VARCHAR,
    ingested_at       TIMESTAMP
);
CREATE INDEX IF NOT EXISTS building_footprint_bbl ON staging.building_footprint (bbl);

CREATE TABLE IF NOT EXISTS analysis.lot_aerial_change (
    bbl               VARCHAR NOT NULL,
    ortho_from        INTEGER NOT NULL,    -- 2022
    ortho_to          INTEGER NOT NULL,    -- 2024
    change_frac       DOUBLE,              -- share of lot pixels changed above threshold
    change_class      VARCHAR,             -- unchanged | cleared | under_construction | new_roof | no_imagery
    geom_source       VARCHAR,             -- footprint | lot_box
    pixels            INTEGER,             -- lot pixels compared
    dob_status        VARCHAR,             -- activity_status of the D72 permit (active|lapsed|stalled), or the named-site tag
    named_site        VARCHAR,             -- memo §4 site label where one applies
    zoom              INTEGER,
    computed_on       DATE NOT NULL,
    PRIMARY KEY (bbl, ortho_from, ortho_to)
);

CREATE TABLE IF NOT EXISTS analysis.building_awning (
    bin               VARCHAR NOT NULL,
    bbl               VARCHAR,
    corridor          VARCHAR,             -- the D82 corridor the run was restricted to
    awning_faces      INTEGER,             -- street faces with a detected awning strip
    face_count        INTEGER,             -- street faces examined (1-2)
    awning_frac       DOUBLE,              -- best face: share of band pixels awning-like
    ortho_year        INTEGER,
    computed_on       DATE NOT NULL,
    PRIMARY KEY (bin, ortho_year)
);

CREATE TABLE IF NOT EXISTS analysis.lot_convertible (
    bbl               VARCHAR NOT NULL,
    height_m          DOUBLE,              -- max height_roof over the lot's footprints, metres
    footprint_m2      DOUBLE,              -- sum of footprint area on the lot
    lot_m2            DOUBLE,              -- PLUTO lotarea
    lot_class         VARCHAR,             -- parking | vacant | garage | one_storey
    landuse           VARCHAR,
    bldgclass         VARCHAR,
    zoning            VARCHAR,             -- PLUTO zonedist1
    borough           VARCHAR,
    in_gowanus        BOOLEAN,
    score             DOUBLE,              -- rank helper: floorplate x class x zoning, 0-1
    lon               DOUBLE,
    lat               DOUBLE,
    computed_on       DATE NOT NULL,
    PRIMARY KEY (bbl)
);
