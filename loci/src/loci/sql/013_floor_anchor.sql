-- ---------------------------------------------------------------------------
-- 013_floor_anchor.sql -- the FLOOR-ANCHOR exception to the D52 supply-set
-- principle (owner ruling D69, 2026-09-11).
--
-- 006_principled_supply.sql is NOT edited (migrations are append-only). This
-- file adds ONE column to analysis.category_anchor and CREATE OR REPLACEs
-- analysis.poi_supply, restating 006's SELECT verbatim with exactly one extra
-- disjunct in `in_principled`. 006's header remains the reference for
-- has_registry_member / is_anchored_category and for the fail-open rule.
--
-- WHAT CHANGED AND WHY. D52's veto assumes that a registry dense enough to
-- account for most of the Census count would have LISTED a real business, so
-- its silence is evidence. For `childcare` that assumption is false by
-- construction: the DOHMH roster (gy3q-4tzp) covers GROUP settings only --
-- Health Code Article 47 centres and Article 43 school-based programmes --
-- while home-based Family and Group Family Day Care is licensed by NYS OCFS
-- and appears in NO NYC feed. The registry therefore CANNOT corroborate a
-- home-based provider however real it is, and the veto deleted supply exactly
-- where home-based care dominates: childcare's in_principled fell 6,066 ->
-- 2,657 the moment the anchor qualified (coverage 0.85). score/supply.py's own
-- note says a category landing in 0.5-0.9 is the signal to load a BETTER
-- anchor rather than to move the threshold -- but no better anchor exists,
-- because the missing half is not published by anyone.
--
-- SEMANTICS, DELIBERATELY NARROW. `anchor_is_floor` changes ONE thing: the
-- lone-aggregator record is RETAINED for that category. The anchor still ranks
-- first for canonical geometry and name (score/dedup.source_rank), still feeds
-- anchor_coverage, and still qualifies. For a floor category in_principled
-- therefore equals in_all; every other category is untouched, and the nesting
-- CORROBORATED subset PRINCIPLED subset ALL still holds by construction
-- because the change only ADDS rows to the middle set.
--
-- The flag is declared per category in src/loci/categories.yaml (read by
-- score/supply.floor_anchor_categories) and PERSISTED here by
-- build_category_anchor, for the same reason is_anchored_category is a
-- measured column rather than a constant: the view must stay self-contained
-- SQL, and a written row must say which rule produced the supply it describes.
-- A flag on a category with no registry anchor loaded is meaningless and
-- score/supply.check_floor_anchors refuses it before anything is written.
-- ---------------------------------------------------------------------------

-- Nullable and without a DEFAULT because DuckDB refuses ADD COLUMN with any
-- constraint ("Adding columns with constraints not yet supported"). The
-- backfill below gives every pre-D69 row an explicit FALSE, and the view
-- COALESCEs anyway, so a NULL can never read as "this anchor is a floor".
ALTER TABLE analysis.category_anchor
    ADD COLUMN IF NOT EXISTS anchor_is_floor BOOLEAN;

UPDATE analysis.category_anchor SET anchor_is_floor = FALSE
 WHERE anchor_is_floor IS NULL;

CREATE OR REPLACE VIEW analysis.poi_supply AS
WITH cluster_sources AS (
    -- distinct feeds across EVERY member of the cluster, not just the
    -- canonical row -- that is what "another feed corroborates it" means.
    SELECT d.cluster_id,
           count(DISTINCT p.source_id) AS n_cluster_sources,
           -- the aggregator list is the negation of
           -- score/supply.AGGREGATOR_SOURCES and is repeated here (not
           -- parameterised) so the view is self-contained SQL;
           -- tests/test_supply_sets.py::test_aggregator_list_matches_the_sql_view
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
    -- ---- D69 addition: the floor-anchor exception ----
    COALESCE(a.anchor_is_floor, FALSE)                        AS anchor_is_floor,
    (NOT COALESCE(a.qualifies, FALSE)                         -- unanchored: keep everything
     OR COALESCE(a.anchor_is_floor, FALSE)                    -- anchored, but the roster is a FLOOR
     OR cs.has_registry_member                                -- a registry saw it
     OR cs.n_cluster_sources >= 2)                            AS in_principled
FROM staging.poi p
JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id
JOIN cluster_sources cs   ON cs.cluster_id = d.cluster_id
LEFT JOIN analysis.category_anchor a ON a.category = p.category
WHERE d.is_canonical;
