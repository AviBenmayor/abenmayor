-- ---------------------------------------------------------------------------
-- 031_address_legality.sql -- COMMERCIAL LEGALITY at address grain (D82).
--
-- Seed 2026-09-14, deliverable 1: "Make the Loci map honest about commercial
-- legality." A gap dot on a Washington Square rowhouse zoned pure residential
-- reads as investable to an allocator unless the map says so. Zoning fields
-- label and filter RECOMMENDATION OUTPUTS ONLY -- they never enter gap_score,
-- supply_ratio, the revenue model, or any grade (D82).
--
-- THIRTEEN NEW COLUMNS ON analysis.address, NO NEW TABLE (the D61 inventory
-- rule). `retailarea` and `bldgclass` added 2026-09-14 (D97 item 3,
-- contrarian review) for the PLUTO-retail-evidence half of the
-- grandfathering test -- the column set is model/address_legality.py's; see
-- that module for the ALTER list it owns (PLUTO_LEGALITY_COLUMNS).
--   zonedist1, overlay1, overlay2, landuse, ownertype, histdist, landmark,
--   retailarea, bldgclass
--       raw MapPLUTO fields, joined by BBL.
--   has_open_commercial_poi, legality, legality_basis
--       DERIVED, but STORED rather than computed by a live view -- see
--       model/address_legality.py's module docstring for the measurement
--       that forced this (an exact-coordinate POI match found 62 of 44,002
--       open commercial POIs; the real distance-based match that works costs
--       ~1 s over MN+BK since the grid-bucketed join of 2026-09-15 (GTM-169);
--       it was a 178 s nested loop before, and either way it is a stored pass, not a view).
--
-- Same shape as address_character's twelve floor-area/jobs columns: STORED
-- because they are either read from a file or expensive to compute, and
-- RE-APPLIED after every `loci address-gaps` rebuild (D78 DELETE-then-INSERT
-- nulls them out, exactly like character_run_at) by
-- `loci address-legality build` (model/address_legality.build_legality_columns).
-- legality_run_at IS NULL is the "not yet re-applied since the last
-- address-gaps run" flag, the same contract character_run_at uses.
--
-- `analysis.address_legality` is a CHEAP PASSTHROUGH view over the three
-- derived columns -- a stable read name for consumers (the webmap export,
-- the recommendation-ledger gate, `address-legality stats`) that does not
-- care whether the columns are computed live or stored. GENERATED from
-- model/address_legality.passthrough_view_sql(); do not hand-edit.
--
-- Not gated: every row of analysis.address gets a value here, including rows
-- with no BBL (D84 street-frame points) -- those read
-- `has_open_commercial_poi = NULL` until a build runs, then FALSE, and
-- `legality = 'commercial'` (the zoning test is false when every PLUTO field
-- is NULL) with `legality_basis = 'no PLUTO zoning record (no BBL match)'`.
-- D75: nothing is ever excluded from the universe by this file.
-- ---------------------------------------------------------------------------

ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS zonedist1 VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS overlay1  VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS overlay2  VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS landuse   VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS ownertype VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS histdist  VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS landmark  VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS retailarea VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bldgclass VARCHAR;
-- spdist1 added 2026-09-15 (investor review, GTM-172 item 6): PLUTO's primary
-- Special Purpose District, e.g. the Special Gowanus Mixed Use District --
-- LABEL ONLY for the allocator report's legality section, never a branch of
-- model/address_legality.py's legality_case_sql().
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS spdist1 VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS has_open_commercial_poi BOOLEAN;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS legality VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS legality_basis VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS legality_run_at TIMESTAMP;

-- GENERATED -- model/address_legality.passthrough_view_sql(). Do not
-- hand-edit; see test_sql_file_matches_generator.

CREATE OR REPLACE VIEW analysis.address_legality AS
SELECT address_id, has_open_commercial_poi, legality, legality_basis
FROM analysis.address
