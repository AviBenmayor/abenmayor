-- ---------------------------------------------------------------------------
-- 029_poi_colocation.sql -- TWO BUSINESSES AT ONE ADDRESS, AND WHETHER ONE OF
-- THEM CLOSED.  Owner ask, 2026-09-14: "any time we have 2 businesses in the
-- same address, we should do a check if one of them closed down."
--
-- GENERATED FILE.  Every statement below is the rendering of
-- model/poi_presence.colocation_view_sql().  Regenerate with
--     loci colocation --emit-sql > src/loci/sql/029_poi_colocation.sql
-- and never hand-edit: the open/closed rule (poi_presence.poi_is_open) would
-- then exist twice and drift.  tests/test_poi_colocation.py fails if it does.
--
-- ---------------------------------------------------------------------------
-- THE DEFECT (GTM-153, cause D36 / GTM-121)
-- ---------------------------------------------------------------------------
-- A cafe was counted TWICE in the revenue supply pool.  score/dedup.py merges
-- only NAME-MATCHED points within MATCH_METERS (40 m).  A departed tenant and
-- its successor share one building coordinate but have DIFFERENT names, so the
-- dedup correctly refuses to merge them -- and both then survive as canonical
-- supply.  Widening the dedup is the wrong fix: it would fuse genuinely
-- distinct neighbouring storefronts and manufacture the fake retail gaps this
-- project exists to avoid.  The right fix is to ask, per co-located pair,
-- whether a SOURCE has published that one of them closed.
--
-- ---------------------------------------------------------------------------
-- "SAME ADDRESS" IS AN EXACT-COORDINATE GROUP, AND WHY
-- ---------------------------------------------------------------------------
-- staging.poi carries NO address_id and NO bbl -- the normalized contract has
-- no address key at all (DESCRIBE staging.poi: poi_id, source_id,
-- source_record_id, category, tier, name, geom, observed_on, opened_on,
-- closed_on, confidence, attrs).  So "same address" is expressed as an
-- EXACT-COORDINATE group: coordinates rounded to poi_presence.COORD_DP = 5
-- decimal places (~1.1 m N-S, ~0.85 m E-W at NYC's latitude), PER CATEGORY.
-- That works because DOHMH, SLA, DCWP and the childcare roster all geocode to
-- the BUILDING (rooftop/parcel centroid), so two tenants of one building land
-- on one IDENTICAL point rather than on two nearby ones.
--
-- PER CATEGORY, deliberately: a bar above a nail salon at one address is two
-- different markets and neither is evidence about the other.  Only same-category
-- co-location can be the GTM-153 double count.
--
-- Caveats the database cannot enforce:
--   * IT IS A GRID, NOT A RADIUS.  Two points 0.3 m apart can straddle a cell
--     boundary and fail to group (false negative -- the safe direction); two
--     1.4 m apart inside one cell do group.  Same trade as
--     poi_presence.KEY_PRECISION, one decimal finer.
--   * GEOMETRY CARRIES NO SRID.  ST_X/ST_Y here are EPSG:4326 degrees by
--     convention and nothing reprojects, because degrees are what is rounded.
--     The database will not catch a violation of that convention.
--   * A LARGE BUILDING LEGITIMATELY HOLDS TWO RESTAURANTS.  A co-located pair
--     is a QUESTION, not a defect, which is why 'unresolved' groups are
--     counted AS-IS in supply and the collapse is off by default
--     (score/supply.COLLAPSE_UNRESOLVED) pending an owner ruling.
--   * BIG GROUPS ARE GEOCODE SINKS, NOT BUILDINGS.  The five largest
--     'unresolved' groups on the 2026-09-14 build hold 72 / 39 / 38 / 36 / 36
--     restaurants at ONE coordinate, at Penn Station, JFK and Port Authority:
--     a whole terminal's food hall published at a single building point.  They
--     are the reason the collapse must never simply be switched on.
--   * GROUPS ARE FORMED OVER ALL CANONICAL POIs, independent of supply set.
--     A group's size is a property of the data, not of the set the screen
--     happens to be running; `in_principled` filtering happens downstream.
--
-- AS-OF DATE (owner ruling 2026-09-16).  The predicate's licence-expiry and
-- freshness branches used to read `current_date`, which a DuckDB view
-- evaluates at QUERY time -- so this view answered a different question every
-- midnight and score/supply.supply_hash moved with no write to the warehouse
-- (ba944e18c57b -> 18eb5ab24629 on the 2026-09-16 roll: 12 POIs flipped, 9 of
-- them out of supply, nothing ingested).  They now read the one-row table
-- analysis.supply_asof (sql/040_supply_asof.sql), which db.init_schema creates
-- BEFORE this file runs because DuckDB binds a view's query at CREATE time.
-- Moving the date is an UPDATE on that table and a NAMED, ANNOUNCED step --
-- `loci supply-asof advance` -- never a side effect of the clock.  The
-- rationale, the measured cost of one day and the freeze rule are in
-- model/supply_asof.py.
--
-- ---------------------------------------------------------------------------
-- THE TWO VIEWS
-- ---------------------------------------------------------------------------
-- analysis.poi_supply_status  every column of analysis.poi_supply, PLUS
--                             poi_status ('open'|'closed'|'unknown'),
--                             poi_status_basis (which source key decided),
--                             ledger_closed_on / ledger_closed_src,
--                             colocation_key / colocation_n /
--                             colocation_resolution / is_colocated_unresolved.
--                             NOT filtered -- it is the measurement surface.
--                             score/supply.canonical_poi_sql applies the gate.
-- analysis.poi_colocation     one row per (coordinate group, category) with
--                             >= 2 canonical POIs: counts by status, the
--                             resolution, and an `evidence` JSON naming the
--                             source key behind each member's verdict.
--
-- D79 IS NOT RELAXED HERE.  Absence from a snapshot is never a closure; only a
-- source-published date or status is evidence, and closures are read through
-- the VIEW analysis.poi_first_seen.  A DOHMH record missing from the current
-- pull is NOT a closure (DOHMH publishes active establishments only), and
-- `last_inspection_date` is read ONLY as a freshness stamp on an OPEN verdict,
-- never as a first-seen date.  Nothing here deletes or mutates a ledger row:
-- a closed location stays in analysis.poi_first_seen with closed_on/closed_src
-- set, and exclusion happens only in the supply set.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW analysis.poi_supply_status AS
WITH ledger AS (
    -- ONE row per poi_id. analysis.poi_first_seen is the D79 surface for
    -- closures (never the base table); two ledger rows could in principle
    -- point at one poi_id_latest, and a fan-out here would DOUBLE a supply
    -- row -- the double-count bug this whole exercise exists to remove. min()
    -- also matches sql/027's closure_precedence: the EARLIEST closure wins.
    SELECT poi_id_latest AS poi_id,
           min(closed_on)  AS closed_on,
           min(closed_src) AS closed_src
    FROM analysis.poi_first_seen
    WHERE poi_id_latest IS NOT NULL
    GROUP BY 1
),
base AS (
    SELECT s.*,
           (s.category || '@' || printf('%.5f,%.5f', round(ST_X(s.geom), 5), round(ST_Y(s.geom), 5))) AS colocation_key,
           f.closed_on  AS ledger_closed_on,
           f.closed_src AS ledger_closed_src,
           CASE
    WHEN f.closed_on IS NOT NULL THEN 'closed'
    WHEN json_extract_string(p.attrs, '$.active_basis') IN ('closed_at_last_inspection', 'no_evidence_of_activity', 'out_of_business', 'unable_to_locate') THEN 'closed'
    WHEN coalesce(try_cast(json_extract_string(p.attrs, '$.expires') AS DATE), try_cast(json_extract_string(p.attrs, '$.license_expiration_date') AS DATE)) IS NOT NULL AND coalesce(try_cast(json_extract_string(p.attrs, '$.expires') AS DATE), try_cast(json_extract_string(p.attrs, '$.license_expiration_date') AS DATE)) < (SELECT asof_date FROM analysis.supply_asof) THEN 'closed'
    WHEN json_extract_string(p.attrs, '$.active_basis') LIKE 'stale_%' THEN 'unknown'
    WHEN NOT coalesce(lower(json_extract_string(p.attrs, '$.active')) = 'true', FALSE) THEN 'unknown'
    WHEN json_extract_string(p.attrs, '$.active_basis') IN ('never_inspected', 'no_expiration_date', 'no_status') THEN 'unknown'
    WHEN coalesce(try_cast(json_extract_string(p.attrs, '$.expires') AS DATE), try_cast(json_extract_string(p.attrs, '$.license_expiration_date') AS DATE)) IS NOT NULL THEN 'open'
    WHEN (json_extract_string(p.attrs, '$.active_basis') LIKE 'inspected_%' OR json_extract_string(p.attrs, '$.active_basis') LIKE 'inspected%' OR json_extract_string(p.attrs, '$.active_basis') IN ('dead_marker_overridden_same_day')) THEN
        CASE WHEN try_cast(json_extract_string(p.attrs, '$.last_inspection_date') AS DATE) IS NOT NULL
              AND date_diff('day', try_cast(json_extract_string(p.attrs, '$.last_inspection_date') AS DATE), (SELECT asof_date FROM analysis.supply_asof)) <= 731
             THEN 'open' ELSE 'unknown' END
    WHEN json_extract_string(p.attrs, '$.active_basis') IN ('published_active_medicaid_ffs_roster', 'published_active_roster') THEN
        CASE WHEN try_cast(p.observed_on AS DATE) IS NOT NULL
              AND date_diff('day', try_cast(p.observed_on AS DATE), (SELECT asof_date FROM analysis.supply_asof)) <= 731
             THEN 'open' ELSE 'unknown' END
    ELSE 'unknown'
END AS poi_status,
           CASE
    WHEN f.closed_on IS NOT NULL
        THEN 'ledger:closed_on_' || strftime(f.closed_on, '%Y-%m-%d')
    WHEN json_extract_string(p.attrs, '$.active_basis') IN ('closed_at_last_inspection', 'no_evidence_of_activity', 'out_of_business', 'unable_to_locate') THEN p.source_id || ':' || json_extract_string(p.attrs, '$.active_basis')
    WHEN coalesce(try_cast(json_extract_string(p.attrs, '$.expires') AS DATE), try_cast(json_extract_string(p.attrs, '$.license_expiration_date') AS DATE)) IS NOT NULL AND coalesce(try_cast(json_extract_string(p.attrs, '$.expires') AS DATE), try_cast(json_extract_string(p.attrs, '$.license_expiration_date') AS DATE)) < (SELECT asof_date FROM analysis.supply_asof)
        THEN p.source_id || ':expired_' || strftime(coalesce(try_cast(json_extract_string(p.attrs, '$.expires') AS DATE), try_cast(json_extract_string(p.attrs, '$.license_expiration_date') AS DATE)), '%Y-%m-%d')
    WHEN json_extract_string(p.attrs, '$.active_basis') LIKE 'stale_%' THEN p.source_id || ':' || json_extract_string(p.attrs, '$.active_basis') || ':absence_derived_not_a_closure'
    WHEN NOT coalesce(lower(json_extract_string(p.attrs, '$.active')) = 'true', FALSE)
        THEN p.source_id || ':' || coalesce(json_extract_string(p.attrs, '$.active_basis'), 'no_status_field')
    WHEN json_extract_string(p.attrs, '$.active_basis') IN ('never_inspected', 'no_expiration_date', 'no_status')
        THEN p.source_id || ':' || json_extract_string(p.attrs, '$.active_basis') || ':default_not_evidence'
    WHEN coalesce(try_cast(json_extract_string(p.attrs, '$.expires') AS DATE), try_cast(json_extract_string(p.attrs, '$.license_expiration_date') AS DATE)) IS NOT NULL THEN p.source_id || ':valid_to_' || strftime(coalesce(try_cast(json_extract_string(p.attrs, '$.expires') AS DATE), try_cast(json_extract_string(p.attrs, '$.license_expiration_date') AS DATE)), '%Y-%m-%d')
    WHEN (json_extract_string(p.attrs, '$.active_basis') LIKE 'inspected_%' OR json_extract_string(p.attrs, '$.active_basis') LIKE 'inspected%' OR json_extract_string(p.attrs, '$.active_basis') IN ('dead_marker_overridden_same_day')) THEN
        CASE WHEN try_cast(json_extract_string(p.attrs, '$.last_inspection_date') AS DATE) IS NOT NULL
              AND date_diff('day', try_cast(json_extract_string(p.attrs, '$.last_inspection_date') AS DATE), (SELECT asof_date FROM analysis.supply_asof)) <= 731
             THEN p.source_id || ':' || json_extract_string(p.attrs, '$.active_basis')
             ELSE p.source_id || ':' || json_extract_string(p.attrs, '$.active_basis') || ':evidence_older_than_731d' END
    WHEN json_extract_string(p.attrs, '$.active_basis') IN ('published_active_medicaid_ffs_roster', 'published_active_roster') THEN
        CASE WHEN try_cast(p.observed_on AS DATE) IS NOT NULL
              AND date_diff('day', try_cast(p.observed_on AS DATE), (SELECT asof_date FROM analysis.supply_asof)) <= 731
             THEN p.source_id || ':' || json_extract_string(p.attrs, '$.active_basis')
             ELSE p.source_id || ':' || json_extract_string(p.attrs, '$.active_basis') || ':evidence_older_than_731d' END
    ELSE p.source_id || ':' || coalesce(json_extract_string(p.attrs, '$.active_basis'), 'no_status_field')
END AS poi_status_basis
    FROM analysis.poi_supply s
    JOIN staging.poi p ON p.poi_id = s.poi_id
    LEFT JOIN ledger f ON f.poi_id = s.poi_id
),
g AS (
    SELECT colocation_key,
           count(*)                                      AS n_poi,
           count(*) FILTER (WHERE poi_status = 'closed')  AS n_closed,
           count(*) FILTER (WHERE poi_status = 'open')    AS n_open,
           count(*) FILTER (WHERE poi_status = 'unknown') AS n_unknown
    FROM base GROUP BY 1
)
SELECT base.*,
       g.n_poi                                   AS colocation_n,
       CASE WHEN g.n_closed = g.n_poi THEN 'all_closed' WHEN g.n_closed > 0 THEN 'one_closed' WHEN g.n_open = g.n_poi THEN 'both_open' ELSE 'unresolved' END                                     AS colocation_resolution,
       (g.n_poi >= 2 AND CASE WHEN g.n_closed = g.n_poi THEN 'all_closed' WHEN g.n_closed > 0 THEN 'one_closed' WHEN g.n_open = g.n_poi THEN 'both_open' ELSE 'unresolved' END = 'unresolved')   AS is_colocated_unresolved,
       (base.poi_status = 'closed')              AS is_evidenced_closed
FROM base JOIN g USING (colocation_key);

CREATE OR REPLACE VIEW analysis.poi_colocation AS
SELECT
    colocation_key                                  AS group_key,
    any_value(category)                             AS category,
    round(any_value(ST_X(geom)), 5)        AS lon,
    round(any_value(ST_Y(geom)), 5)        AS lat,
    count(*)                                        AS n_poi,
    list(poi_id ORDER BY poi_id)                    AS poi_ids,
    count(*) FILTER (WHERE poi_status = 'closed')   AS n_closed,
    count(*) FILTER (WHERE poi_status = 'open')     AS n_open,
    count(*) FILTER (WHERE poi_status = 'unknown')  AS n_unknown,
    CASE WHEN count(*) FILTER (WHERE poi_status = 'closed') = count(*) THEN 'all_closed' WHEN count(*) FILTER (WHERE poi_status = 'closed') > 0 THEN 'one_closed' WHEN count(*) FILTER (WHERE poi_status = 'open') = count(*) THEN 'both_open' ELSE 'unresolved' END                                       AS resolution,
    to_json(list(struct_pack(
        poi_id     := poi_id,
        source_id  := source_id,
        name       := name,
        status     := poi_status,
        basis      := poi_status_basis,
        closed_on  := ledger_closed_on,
        closed_src := ledger_closed_src
    ) ORDER BY poi_id))                             AS evidence
FROM analysis.poi_supply_status
GROUP BY colocation_key
HAVING count(*) >= 2;
