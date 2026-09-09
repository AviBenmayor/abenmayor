-- ---------------------------------------------------------------------------
-- 003_supply_sets.sql -- labelled supply sets for the D47 / M9 comparison.
--
-- A contrarian re-run showed the address screen's output changes ~6x between
-- the all-POI supply set and a corroborated-only one (act band 25k -> 154k
-- pairs, Spearman 0.19). Choosing between them needs the sets side by side,
-- not three rival tables that can drift apart. So this is ONE VIEW over the
-- existing canonical join, carrying one boolean per set. `analysis.poi_dedup`
-- and `staging.poi` remain the single source of truth; nothing here is
-- materialised, so the view can never go stale relative to them.
--
-- VALIDATION / SELECTION AID. Nothing in score/ or model/ reads this view yet;
-- adopting a supply set is an owner decision (D49 ordering), not this file's.
--
-- Set definitions, one column each:
--
--   in_all           every canonical POI. The current production set.
--
--   is_corroborated  the dedup cluster carries >= 2 DISTINCT source_ids among
--                    ALL its members, canonical or not -- i.e. some second
--                    independent feed saw this establishment. Same definition
--                    as analysis.zip_coverage_by_source.poi_count_single_source
--                    (negated), so the two agree by construction.
--
--   is_active        the record's ANCHORING source says it is still trading.
--                    Sources publish this in staging.poi.attrs->>'active'
--                    (see sources/cities/nyc/dohmh.py and nys_dos.py for each
--                    filter's derivation and its N). A record whose source
--                    publishes NO activity signal is ACTIVE by default and
--                    flagged active_testable = FALSE -- absence of evidence is
--                    not evidence of closure, and defaulting the other way
--                    would delete every Overture/Foursquare-only category
--                    outright.
--
--   is_active_corroborated   is_active AND is_corroborated. The tightest set.
--
-- ACTIVE IS NOT TESTABLE EVERYWHERE, AND THAT IS NOT A BUG IN THIS VIEW.
-- Only DOHMH (restaurant, cafe_bakery), NYS SLA (bar) and NYS DOS
-- (hair_barber, nails_beauty) publish anything dateable. fitness and hardware
-- -- the two categories D47 singled out -- are Overture+Foursquare only and
-- have NO licence anchor at all, so is_active is vacuously TRUE for every one
-- of their rows. Reading a fitness ACTIVE count as "verified open" would be
-- reading a default as a finding. `active_testable` exists so that mistake is
-- visible in the data rather than only in this comment.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW analysis.poi_supply AS
WITH cluster_sources AS (
    -- distinct feeds across EVERY member of the cluster, not just the
    -- canonical row -- that is what "another feed corroborates it" means.
    SELECT d.cluster_id, count(DISTINCT p.source_id) AS n_cluster_sources
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
    -- does this row's own source publish an activity signal at all?
    (json_extract(p.attrs, '$.active') IS NOT NULL)          AS active_testable,
    TRUE                                                      AS in_all,
    (cs.n_cluster_sources >= 2)                               AS is_corroborated,
    -- NULL (untestable) counts as active; only an explicit false excludes.
    COALESCE(CAST(json_extract(p.attrs, '$.active') AS BOOLEAN), TRUE) AS is_active,
    (COALESCE(CAST(json_extract(p.attrs, '$.active') AS BOOLEAN), TRUE)
     AND cs.n_cluster_sources >= 2)                           AS is_active_corroborated,
    json_extract_string(p.attrs, '$.active_basis')            AS active_basis
FROM staging.poi p
JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id
JOIN cluster_sources cs   ON cs.cluster_id = d.cluster_id
WHERE d.is_canonical;
