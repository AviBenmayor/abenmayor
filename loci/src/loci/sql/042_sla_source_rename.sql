-- 042: the one-letter source-name defect in staging.storefront_filing.
--
-- THE DEFECT. `src/loci/sources/cities/nyc/filing_feeds.py` keyed the SLA
-- active-licence feed as `nyc_sla_liquor_licenses`. `registry.yaml` calls the
-- SAME dataset (9s3h-dpkz) `nys_sla_liquor_licenses` -- NYS, not NYC, because
-- the State Liquor Authority is a STATE agency and the file is served from
-- data.ny.gov, not data.cityofnewyork.us. Two names one letter apart meaning
-- the same thing is exactly the failure CLAUDE.md's naming rule exists to
-- prevent, and it had already put 24,850 rows in staging.storefront_filing
-- under a `source` value that matches NO registry id -- an untraceable
-- provenance stamp. tests/test_filing_backfill.py pinned it as a known
-- exception rather than fixing it; this migration fixes it.
--
-- WHY AN UPDATE AND NOT A DELETE-AND-REINGEST. The exception comment in that
-- test anticipated "a data migration with a DELETE-by-source in it". A DELETE
-- would discard 24,850 rows and make the fix depend on a live Socrata pull
-- succeeding, which is a worse trade than a deterministic in-place rewrite:
-- nothing about the ROWS is wrong, only their label. Both `source` and
-- `filing_id` carry the name (`filing_id` = '<source>:<stage>:<raw_id>', the
-- table's PRIMARY KEY), so both are rewritten in one statement pair. The
-- replacement is ANCHORED to the leading segment -- a bare replace() would
-- also rewrite the string if it appeared inside a raw_id.
--
-- IDEMPOTENT. Both statements are predicated on the OLD spelling, so a second
-- application matches zero rows. That matters: db.init_schema() re-applies
-- every migration on every connection.
--
-- NO PRIMARY-KEY COLLISION IS POSSIBLE. `nys_sla_liquor_licenses` has never
-- been written to this table by any code path (the FEEDS key was the only
-- writer and it used the NYC spelling), so no target filing_id already exists.
-- If a future warehouse ever violates that, the PRIMARY KEY raises -- which is
-- the correct outcome, not something to code around.
--
-- WHAT THIS MIGRATION DOES NOT DO. It does not touch `staging.poi`, where the
-- SLA POI adapter (sources/cities/nyc/nys_sla.py) has always used the correct
-- `nys_sla_liquor_licenses` spelling. The supply set is unaffected and the
-- supply hash cannot move because of this file.
-- ---------------------------------------------------------------------------

UPDATE staging.storefront_filing
   SET filing_id = 'nys_sla_liquor_licenses'
                   || substr(filing_id, length('nyc_sla_liquor_licenses') + 1)
 WHERE source = 'nyc_sla_liquor_licenses'
   AND starts_with(filing_id, 'nyc_sla_liquor_licenses:');

UPDATE staging.storefront_filing
   SET source = 'nys_sla_liquor_licenses'
 WHERE source = 'nyc_sla_liquor_licenses';
