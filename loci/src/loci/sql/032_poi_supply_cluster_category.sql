-- ---------------------------------------------------------------------------
-- 032_poi_supply_cluster_category.sql -- analysis.poi_supply reads the
-- CLUSTER's category, not the canonical row's source category (owner ruling
-- 2026-09-14, verbatim "go with B"; GTM-153).
--
-- 003/006/013 are NOT edited (migrations are append-only). This file
-- CREATE OR REPLACEs analysis.poi_supply, restating 013's SELECT verbatim with
-- exactly two substitutions, and it is the LAST redefinition of that view in
-- filename order, so db.init_schema leaves this one standing.
--
-- WHY IT IS NEEDED, and why it was invisible until now. score/dedup.py now
-- runs a CROSS-CATEGORY pass: one business that two feeds filed under two
-- categories becomes ONE cluster (Lion's Milk at 104 Roebling is
-- nyc_dohmh_restaurants:50043137 `restaurant` + overture_places:41c0fc63...
-- `cafe_bakery`, 12 m apart, both open, counted twice in the supply pool until
-- this ruling). A cluster spanning two categories has to carry ONE label, and
-- `analysis.poi_dedup.category` is where build_dedup writes it.
--
-- Under the rejected variant A that label was always the canonical member's
-- own category, so `staging.poi.category` read off the canonical row EQUALLED
-- the cluster label by construction and these views were accidentally correct.
-- Under ruling B they diverge on purpose: DOHMH files every permitted food
-- service as a `restaurant` because that is a permit class, not a retail
-- category, so where the cluster also holds a `cafe_bakery` or `bar` member
-- the FINER category wins the label while the registry row stays canonical for
-- geometry, name and existence. Lion's Milk is therefore a cafe_bakery whose
-- canonical row is the DOHMH permit.
--
-- Leaving the view on p.category would make that ruling a no-op everywhere it
-- matters: the gap screen, supply_ratio, category_anchor coverage, the DNCI
-- and the revenue model all count categories through analysis.poi_supply, and
-- they would keep reading DOHMH's permit class while poi_dedup said otherwise
-- -- two disagreeing answers to "what category is this location", which is the
-- exact failure a single normalized contract exists to prevent.
--
-- THE TWO SUBSTITUTIONS, both required, neither cosmetic:
--   1. `p.category` -> `d.category` in the projection.
--   2. the category_anchor join keys on `d.category` too. The D52 veto asks
--      "is THIS category anchored"; joining the anchor row for the source's
--      label while reporting the cluster's label would apply cafe_bakery's
--      supply rule to a row counted as a restaurant.
--
-- WHAT THIS FILE DOES NOT CHANGE. The cluster_sources CTE still counts
-- distinct feeds over EVERY member (corroboration is a property of the
-- cluster, unchanged); is_active / active_basis still come from the canonical
-- row's own attrs, because activity is a fact about the record that was
-- observed, not about the label; `p.tier`, `p.name` and `p.geom` still come
-- from the canonical row, which is the whole point of source_rank. The
-- aggregator list is still spelled out here for the same reason 006 and 013
-- spell it out -- the view must be self-contained SQL, and
-- tests/test_supply_sets.py::test_aggregator_list_matches_the_sql_view fails
-- if it drifts from score/supply.AGGREGATOR_SOURCES.
--
-- DOWNSTREAM, FOR FREE. analysis.poi_supply_status (sql/029, re-rendered by
-- db.init_schema from model/poi_presence.colocation_view_sql) selects `s.*`
-- off this view and builds its colocation_key from `s.category`, and
-- analysis.poi_colocation reads that -- so both follow the cluster label with
-- no edit. That is deliberate: two members of ONE cluster must never land in
-- two different colocation groups.
--
-- The column LIST is otherwise byte-identical to 013's -- deliberately, so
-- that `SELECT s.*` consumers (analysis.poi_supply_status) and any positional
-- read see the same shape they saw yesterday. The source's own label is one
-- join away in staging.poi and is NOT duplicated onto this view.
--
-- CAVEAT THE DATABASE CANNOT ENFORCE: staging.poi.category keeps the source's
-- own label on every row, including the canonical one, and it is still the
-- right column for "what did this feed call it". Any NEW query that wants the
-- category Loci counts must read analysis.poi_supply / analysis.poi_dedup. A
-- query that joins staging.poi directly and groups by its category will
-- silently disagree with the screen for the 15k-odd rows a cross-category
-- merge relabelled.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW analysis.poi_supply AS
WITH cluster_sources AS (
    -- distinct feeds across EVERY member of the cluster, not just the
    -- canonical row -- that is what "another feed corroborates it" means.
    SELECT d.cluster_id,
           count(DISTINCT p.source_id) AS n_cluster_sources,
           -- did ANY member of this cluster come from a government registry
           -- rather than an aggregator? The aggregator list is the negation of
           -- score/supply.AGGREGATOR_SOURCES and is repeated here (not
           -- parameterised) so the view is self-contained SQL.
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
    d.category,                               -- THE CLUSTER's label (ruling B)
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
LEFT JOIN analysis.category_anchor a ON a.category = d.category
WHERE d.is_canonical;
