-- Loci: schemas and the analysis-layer contract (DuckDB).
--
-- raw       : source data as landed, untransformed. Never edited in place.
-- staging   : normalized to the common schema. City adapters write here.
-- analysis  : the hex grid and everything joined to it. Model inputs live here.
--
-- staging.poi is what src/loci/score/ consumes. It contains NO city-specific
-- columns -- see docs/CONTEXT.md section 10.
--
-- DuckDB notes vs. the earlier PostGIS draft:
--   * GEOMETRY carries no SRID. Everything here is EPSG:4326 by convention;
--     metric work reprojects explicitly with ST_Transform. Enforce this in code,
--     because the database will not.
--   * Spatial indexes are RTREE, not GiST.
--   * JSON, not JSONB.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analysis;

-- ---------------------------------------------------------------- staging.poi
-- The single normalized POI table. Every source -- universal or city -- lands
-- here through an adapter. src/loci/score/ reads only this.
CREATE TABLE IF NOT EXISTS staging.poi (
    poi_id           VARCHAR PRIMARY KEY,
    source_id        VARCHAR  NOT NULL,   -- must match an id in loci/registry.yaml
    source_record_id VARCHAR,
    category         VARCHAR  NOT NULL,   -- one of the 15 categories, CONTEXT.md 2.1
    tier             SMALLINT NOT NULL CHECK (tier BETWEEN 1 AND 4),
    name             VARCHAR,
    geom             GEOMETRY NOT NULL,   -- EPSG:4326 by convention
    observed_on      DATE,                -- snapshot vintage
    opened_on        DATE,                -- null unless the source is dated
    closed_on        DATE,
    confidence       FLOAT CHECK (confidence BETWEEN 0 AND 1),
    attrs            JSON
);

-- ---------------------------------------------------------------- analysis.hex
-- H3 res 9 grid, shoreline-clipped. land_fraction normalizes edge hexes
-- (CONTEXT.md 7.7). h3_index is the 15-char string form.
CREATE TABLE IF NOT EXISTS analysis.hex (
    h3_index      VARCHAR PRIMARY KEY,
    resolution    SMALLINT NOT NULL DEFAULT 9,
    geom          GEOMETRY NOT NULL,
    centroid      GEOMETRY NOT NULL,
    land_fraction FLOAT NOT NULL CHECK (land_fraction > 0 AND land_fraction <= 1),
    borough       VARCHAR,
    nta_code      VARCHAR
);

-- Demographics dasymetrically interpolated from ACS tracts (CONTEXT.md 4.2).
-- MOEs are carried, not discarded.
CREATE TABLE IF NOT EXISTS analysis.hex_demographics (
    h3_index             VARCHAR REFERENCES analysis.hex(h3_index),
    acs_year             SMALLINT NOT NULL,
    population           FLOAT, population_moe       FLOAT,
    households           FLOAT, households_moe       FLOAT,
    median_hh_income     FLOAT, median_hh_income_moe FLOAT,
    renter_share         FLOAT,
    PRIMARY KEY (h3_index, acs_year)
);

-- Controls: zoning capacity, transit access, development headroom.
CREATE TABLE IF NOT EXISTS analysis.hex_controls (
    h3_index           VARCHAR PRIMARY KEY REFERENCES analysis.hex(h3_index),
    comm_far_capacity  FLOAT,   -- PLUTO CommFAR, area-weighted. REQUIRED control.
    resid_far          FLOAT,
    built_far          FLOAT,
    dev_headroom       FLOAT,   -- (ResidFAR - BuiltFAR) clipped at 0
    units_res          FLOAT,
    walk_m_to_subway   FLOAT,   -- network distance to nearest ENTRANCE, not centroid
    subway_routes      SMALLINT,
    subway_riders_2024 FLOAT
);

-- Every (hex, business) pair within a 30-minute walk, with the NETWORK distance
-- along the pedestrian graph (CONTEXT.md 4.3). This is the primary access artifact;
-- hex_access below is DERIVED from it by counting at each threshold, so any walk
-- time, nearest-distance or spacing question is a query here, not a recompute.
CREATE TABLE IF NOT EXISTS analysis.hex_poi_distance (
    h3_index   VARCHAR REFERENCES analysis.hex(h3_index),
    poi_id     VARCHAR NOT NULL,
    category   VARCHAR NOT NULL,
    network_m  REAL    NOT NULL CHECK (network_m >= 0),
    PRIMARY KEY (h3_index, poi_id)
);

-- Per-category access at each walk threshold (CONTEXT.md 4.3).
CREATE TABLE IF NOT EXISTS analysis.hex_access (
    h3_index      VARCHAR REFERENCES analysis.hex(h3_index),
    category      VARCHAR  NOT NULL,
    threshold_min SMALLINT NOT NULL CHECK (threshold_min IN (5, 10, 15)),
    n_reachable   INTEGER  NOT NULL,
    served_share  FLOAT    NOT NULL CHECK (served_share BETWEEN 0 AND 1),
    PRIMARY KEY (h3_index, category, threshold_min)
);

-- The index, the supply-model fit, and the residual (CONTEXT.md 4.4-4.5).
CREATE TABLE IF NOT EXISTS analysis.hex_dnci (
    h3_index       VARCHAR REFERENCES analysis.hex(h3_index),
    threshold_min  SMALLINT NOT NULL,
    dnci           FLOAT NOT NULL CHECK (dnci BETWEEN 0 AND 1),
    dnci_predicted FLOAT,
    residual       FLOAT,   -- the signal. negative = underserved vs. peers.
    opportunity    FLOAT,
    model_version  VARCHAR NOT NULL,
    PRIMARY KEY (h3_index, threshold_min, model_version)
);

-- LODES WAC annual panel, block -> hex (CONTEXT.md 4.6). Jobs, not
-- establishments -- see threat 7.4.
CREATE TABLE IF NOT EXISTS analysis.hex_panel (
    h3_index VARCHAR REFERENCES analysis.hex(h3_index),
    year     SMALLINT NOT NULL CHECK (year BETWEEN 2002 AND 2023),
    naics    VARCHAR  NOT NULL,
    jobs     FLOAT    NOT NULL,
    PRIMARY KEY (h3_index, year, naics)
);

-- Outcomes for the growth regression.
CREATE TABLE IF NOT EXISTS analysis.hex_outcomes (
    h3_index         VARCHAR REFERENCES analysis.hex(h3_index),
    period_start     SMALLINT NOT NULL,
    period_end       SMALLINT NOT NULL,
    d_log_population FLOAT,
    d_log_households FLOAT,
    d_log_zori       FLOAT,
    permitted_units  FLOAT,
    PRIMARY KEY (h3_index, period_start, period_end)
);

-- Ground-truth enumeration for the coverage-bias test (CONTEXT.md 7.1 / P3).
-- This table is the evidence for the prediction most likely to kill the project.
CREATE TABLE IF NOT EXISTS analysis.coverage_validation (
    h3_index       VARCHAR REFERENCES analysis.hex(h3_index),
    category       VARCHAR NOT NULL,
    income_decile  SMALLINT NOT NULL CHECK (income_decile BETWEEN 1 AND 10),
    n_ground_truth INTEGER NOT NULL,   -- Google Places enumeration
    n_overture     INTEGER NOT NULL,
    n_osm          INTEGER NOT NULL,
    n_city_source  INTEGER,            -- DOHMH/DCWP where the category has one
    sampled_on     DATE NOT NULL,
    PRIMARY KEY (h3_index, category)
);

-- Cross-source entity resolution (GTM-20). Maps each staging.poi row to a
-- cluster of duplicates across sources; is_canonical marks the one kept for
-- scoring. Without this the DNCI inflates wherever source coverage overlaps,
-- and overlap is geographically biased, so the error is not random.
CREATE TABLE IF NOT EXISTS analysis.poi_dedup (
    poi_id       VARCHAR PRIMARY KEY,
    cluster_id   BIGINT  NOT NULL,
    is_canonical BOOLEAN NOT NULL,
    category     VARCHAR NOT NULL
);

-- Per-hex investment screen (present-day): a walkable, populated hex missing an
-- "expected" daily-needs business — one that areas like it normally have, so its
-- absence is conspicuous. The missing business IS the opportunity. Ranked (for
-- now) by resident population; "people affected" = walking-catchment population
-- is a later refinement.
CREATE TABLE IF NOT EXISTS analysis.hex_gaps (
    h3_index          VARCHAR NOT NULL,
    threshold_min     SMALLINT NOT NULL,
    population        REAL,
    present_count     SMALLINT NOT NULL,
    lead_missing      VARCHAR,      -- the most-expected missing business
    lead_prevalence   REAL,         -- share of areas that have it
    missing_expected  VARCHAR,      -- all conspicuously-missing businesses (comma-sep)
    PRIMARY KEY (h3_index, threshold_min)
);
