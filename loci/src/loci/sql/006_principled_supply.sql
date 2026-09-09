-- ---------------------------------------------------------------------------
-- 006_principled_supply.sql -- the PRINCIPLED supply set (owner decision D52,
-- 2026-09-08) and the measured anchor table it reads.
--
-- 003_supply_sets.sql is NOT edited (migrations are append-only). This file
-- CREATE OR REPLACEs analysis.poi_supply, restating 003's columns verbatim and
-- adding three: has_registry_member, is_anchored_category, in_principled.
-- 003's header remains the reference for the ALL / CORROBORATED / ACTIVE
-- definitions; only the two new booleans are documented here.
--
-- WHY A TABLE AND NOT A CONSTANT: "does this category have an anchor loaded"
-- is a MEASUREMENT (score/supply.py: registry-source coverage of the Census
-- ZBP count, threshold ANCHOR_COVERAGE_MIN), not a registry.yaml label. The
-- view joins analysis.category_anchor so the answer moves when the data moves.
--
-- FAIL-OPEN, DELIBERATELY: an EMPTY analysis.category_anchor makes
-- is_anchored_category FALSE everywhere, hence in_principled = in_all. A
-- forgotten `loci anchor-coverage` must degrade to counting everything, never
-- to silently deleting supply. The corresponding hazard -- a STALE anchor
-- table after a re-dedup -- is why `loci dedup` rebuilds it in the same
-- command and why address_gaps records supply_hash (which folds in the
-- qualifying-anchor set and the per-category counts).
--
-- NESTING, WHICH IS A PROPERTY AND NOT A COINCIDENCE:
--     CORROBORATED  subset of  PRINCIPLED  subset of  ALL
-- holds for every category by construction, because in_principled is a
-- DISJUNCTION that includes is_corroborated. A cluster seen by two aggregators
-- and no registry stays in PRINCIPLED: two independent feeds agreeing is
-- corroboration, and excluding it would make PRINCIPLED stricter than the set
-- it exists to relax. What PRINCIPLED removes is precisely the LONE aggregator
-- record in an anchored category -- one cluster, one source, that source an
-- aggregator, in a category whose registry is dense enough to have seen it.
-- For an UNANCHORED category PRINCIPLED = ALL exactly: nothing is dropped,
-- and loading the anchor is the fix.
-- ---------------------------------------------------------------------------

-- One row per Loci category: how much of the Census establishment count the
-- category's REGISTRY sources (score/supply.py AGGREGATOR_SOURCES negated)
-- account for, over the comparable ZIPs of `boroughs` in ZBP vintage `year`.
-- Written by score/supply.build_category_anchor; read by the view below.
-- anchor_coverage is a ratio of two imperfect counts (ZBP is NAICS
-- self-classification at ZIP grain) -- it is evidence the registry is dense
-- enough to veto, NOT an estimate of the licensed share of businesses.
CREATE TABLE IF NOT EXISTS analysis.category_anchor (
    category        VARCHAR NOT NULL,
    anchor_sources  VARCHAR,          -- comma-separated registry source_ids seen in this category
    anchor_poi      BIGINT,           -- canonical POIs whose cluster has >= 1 registry member
    zbp_estab       BIGINT,           -- Census establishments over the same comparable ZIPs
    n_zips          INTEGER,
    anchor_coverage DOUBLE,           -- anchor_poi / zbp_estab; NULL if zbp_estab = 0
    threshold       DOUBLE NOT NULL,  -- ANCHOR_COVERAGE_MIN in force for this measurement
    qualifies       BOOLEAN NOT NULL, -- anchor_coverage >= threshold
    year            INTEGER,
    boroughs        VARCHAR,          -- scope of the measurement, e.g. 'Manhattan,Brooklyn'
    run_at          TIMESTAMP NOT NULL,
    PRIMARY KEY (category)
);

CREATE OR REPLACE VIEW analysis.poi_supply AS
WITH cluster_sources AS (
    -- distinct feeds across EVERY member of the cluster, not just the
    -- canonical row -- that is what "another feed corroborates it" means.
    SELECT d.cluster_id,
           count(DISTINCT p.source_id) AS n_cluster_sources,
           -- did ANY member of this cluster come from a government registry
           -- rather than an aggregator? The aggregator list is the negation of
           -- score/supply.AGGREGATOR_SOURCES and is repeated here (not
           -- parameterised) so the view is self-contained SQL; the test
           -- tests/test_principled_supply.py::test_aggregator_list_matches_sql
           -- fails if the two ever drift.
           max(CASE WHEN p.source_id NOT IN
                    ('overture_places', 'osm_overpass', 'foursquare_os_places')
               THEN 1 ELSE 0 END) = 1 AS has_registry_member
    FROM analysis.poi_dedup d
    JOIN staging.poi p ON p.poi_id = d.poi_id
    GROUP BY 1
)
SELECT
    p.poi_id,
    p.source_id,
    p.category,
    p.tier,
    p.name,
    p.geom,                                   -- EPSG:4326 by convention (no SRID)
    d.cluster_id,
    cs.n_cluster_sources,
    (json_extract(p.attrs, '$.active') IS NOT NULL)          AS active_testable,
    TRUE                                                      AS in_all,
    (cs.n_cluster_sources >= 2)                               AS is_corroborated,
    COALESCE(CAST(json_extract(p.attrs, '$.active') AS BOOLEAN), TRUE) AS is_active,
    (COALESCE(CAST(json_extract(p.attrs, '$.active') AS BOOLEAN), TRUE)
     AND cs.n_cluster_sources >= 2)                           AS is_active_corroborated,
    json_extract_string(p.attrs, '$.active_basis')            AS active_basis,
    -- ---- D52 additions ----
    cs.has_registry_member                                    AS has_registry_member,
    COALESCE(a.qualifies, FALSE)                              AS is_anchored_category,
    (NOT COALESCE(a.qualifies, FALSE)                         -- unanchored: keep everything
     OR cs.has_registry_member                                -- a registry saw it
     OR cs.n_cluster_sources >= 2)                            AS in_principled
FROM staging.poi p
JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id
JOIN cluster_sources cs   ON cs.cluster_id = d.cluster_id
LEFT JOIN analysis.category_anchor a ON a.category = p.category
WHERE d.is_canonical;

-- Provenance on the address screen, the same reason reach_source/reach_hash/
-- graph_version already exist there: two runs that differ ONLY in which POIs
-- counted as supply are otherwise indistinguishable once written, and the
-- difference is large (D52 moves whole categories). Nullable rather than NOT
-- NULL because ALTER cannot retro-fill existing rows -- a NULL here means a
-- row written before D52, which is exactly the fact a reader needs.
ALTER TABLE analysis.address_gaps ADD COLUMN IF NOT EXISTS supply_set  VARCHAR;
ALTER TABLE analysis.address_gaps ADD COLUMN IF NOT EXISTS supply_hash VARCHAR;
