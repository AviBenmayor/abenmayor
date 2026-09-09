-- ---------------------------------------------------------------------------
-- 009_retire_split_tables.sql -- physical cleanup for databases built before
-- the D38/D52/D56/D57/D58 refactors landed. Every table dropped here has
-- already had its CREATE TABLE removed from 002_schema.sql (or never had
-- one) -- a fresh database this migration runs against never had these
-- tables to begin with, so every statement below is a no-op there and a
-- real cleanup on data/loci.duckdb, which was built incrementally across
-- those sessions and still carries the old shapes physically on disk.
--
-- DROP TABLE IF EXISTS is idempotent and safe to re-run; nothing here is
-- gated behind a flag because keeping the OLD and NEW shape of the same
-- fact side by side is exactly the hazard CLAUDE.md warns about (a merge
-- fusing distinct things, or two tables quietly answering the same question
-- differently) -- "old and new do not coexist" is the point of this file.
--
--   analysis.hex_gaps / hex_gaps_reach  -- RETIRED under D38 (002_schema.sql
--     line ~297): the per-hex gap screen. Superseded by
--     analysis.address / address_category (this file's own VIEW,
--     analysis.address_gaps, reassembles the wide shape).
--   analysis.hex_dnci                   -- RETIRED under D38: the E3
--     causal-supply-model input: the SCOPE CORRECTION made the growth
--     question out of scope, and D38 moved the geography off the hex.
--   analysis.hex_outcomes               -- RETIRED under D38: the E3
--     regression's dependent-variable table. Never had a writer; 0 rows for
--     the life of the project.
--   analysis.address_demand             -- SUPERSEDED under D58: the D57
--     sibling table folded into analysis.address_category's own demand
--     annotation columns (see 002_schema.sql's GTM-110 region header).
--   analysis.address_convenience        -- SUPERSEDED under D58: a 200-row
--     prototype duplicating address_category's own nearest_m under a
--     different name. `loci conveniences` is now a read-only report over
--     analysis.address_category (model/conveniences.py).
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS analysis.hex_gaps;
DROP TABLE IF EXISTS analysis.hex_gaps_reach;
DROP TABLE IF EXISTS analysis.hex_dnci;
DROP TABLE IF EXISTS analysis.hex_outcomes;
DROP TABLE IF EXISTS analysis.address_demand;
DROP TABLE IF EXISTS analysis.address_convenience;
