-- 040_supply_asof.sql -- THE PINNED AS-OF DATE FOR THE OPEN/CLOSED PREDICATE
-- ===========================================================================
-- Owner ruling 2026-09-16: "the supply hash and poi open status must take an
-- explicit as-of date stored with the baseline, so the hash moves only on real
-- evidence writes; advancing the date becomes a named step in the canonical
-- order."
--
-- WHY THIS TABLE EXISTS
-- ---------------------
-- model/poi_presence.poi_is_open() has two branches that are functions of the
-- current date: a licence whose `expires` is in the past reads CLOSED, and
-- evidence older than OPEN_EVIDENCE_MAX_AGE_DAYS (731) can no longer support
-- an OPEN verdict.  Both were rendered with SQL's `current_date`, and
-- sql/029_poi_colocation.sql baked that into analysis.poi_supply_status.  A
-- DuckDB view evaluates `current_date` at QUERY time, so the view answered a
-- different question every midnight and score/supply.supply_hash -- which
-- hashes that view's per-category counts -- moved with it.
--
-- MEASURED, read-only, on the 2026-09-16 build:
--
--     supply_hash at asof 2026-09-15  =  ba944e18c57b   (the D112 baseline)
--     supply_hash at asof 2026-09-16  =  18eb5ab24629   (the drift)
--
--     status_before  status_after  reason                          n  leaves supply
--     open           closed        licence expiry lapsed           9              9
--     open           unknown       evidence aged past 731 days     3              0
--
-- The nine are NYS DOS appearance-enhancement licences whose `expires` is
-- exactly 2026-09-15 (seven nails_beauty, two hair_barber); the three are
-- DOHMH restaurants that crossed 724 -> 732 days since inspection.  Nothing
-- was ingested, verified or written.  A hash that moves without a write
-- destroys the signal the D96/D106 freeze protocol rests on.
--
-- WHAT IT HOLDS
-- -------------
-- ONE row.  `pin` is a constant PRIMARY KEY -- that is how "exactly one row"
-- is said in DDL; it is not a real key.  Every SQL rendering of the predicate
-- reads the date as the scalar subquery (SELECT asof_date FROM
-- analysis.supply_asof), so advancing the date is an UPDATE, not a
-- CREATE OR REPLACE VIEW (a view re-render is itself a hash-moving event --
-- D105/D106).
--
-- ORDERING CAVEAT THE DATABASE CANNOT ENFORCE
-- -------------------------------------------
-- sql/029's views BIND this table by name at CREATE VIEW time, and 029 sorts
-- before 040.  db.init_schema therefore calls
-- model/supply_asof.ensure_table(con) BEFORE the migration sweep; this file is
-- the human-readable form of that DDL and the way an ALREADY-BUILT warehouse
-- gets the table.  Both are CREATE ... IF NOT EXISTS, so applying both is a
-- no-op.  If you renumber or reorder migrations, the table must still exist
-- before 029.
--
-- SEEDING
-- -------
-- The seed is NOT `current_date`.  model/supply_asof.ensure_table reads
-- `supply_asof:` (else the older `asof:`) from model/supply_baseline.yaml, so
-- a warehouse adopting this change lands on the date its baseline was fitted
-- at -- 2026-09-15 for ba944e18c57b, which reproduces that hash exactly and
-- means the YAML does NOT need re-stamping.  The INSERT below is the
-- equivalent for a hand-applied migration; change the literal if your baseline
-- was fitted at another date, and check with `loci supply-asof show`.
--
-- ADVANCING IS A NAMED STEP, NOT A REFRESH
-- ----------------------------------------
-- `loci supply-asof advance [--to YYYY-MM-DD] [--dry-run]` runs BEFORE step 01
-- of the canonical order and must be announced to every peer session exactly
-- like a poi_status write: it moves the shared supply hash, so every stamped
-- artefact (baseline, address_gaps, revenue, forecast vintage, webmap
-- meta.json) is a vintage behind until the order is re-run.  It refuses while
-- a freeze marker is set.
-- ===========================================================================

CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS analysis.supply_asof (
    pin        VARCHAR PRIMARY KEY DEFAULT 'the',
    -- NOT `asof`: ASOF is a reserved word in DuckDB (ASOF JOIN) and an
    -- unquoted `SELECT asof FROM ...` is a parser error, so the scalar
    -- subquery every view embeds would not even bind.
    asof_date  DATE    NOT NULL,
    set_at     TIMESTAMP NOT NULL DEFAULT current_timestamp,
    set_by     VARCHAR,
    reason     VARCHAR
);

-- Seed only if empty.  NEVER overwrites a pin that is already set: re-applying
-- a migration must not silently move the supply set.
INSERT INTO analysis.supply_asof (pin, asof_date, set_by, reason)
SELECT 'the', DATE '2026-09-15', 'sql/040',
       'seeded to the asof of baseline ba944e18c57b (D112 re-baseline)'
WHERE NOT EXISTS (SELECT 1 FROM analysis.supply_asof);
