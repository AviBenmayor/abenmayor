-- ---------------------------------------------------------------------------
-- 033_poi_closure_evidence.sql -- CLOSURE EVIDENCE FROM THE WEB AND GOOGLE
-- PLACES (D98, GTM-170), plus the shared spend ledger (D98/D100 reconciled).
--
-- sql/029_poi_colocation.sql answers "is this POI open, closed or unknown"
-- from the LOADED SOURCES alone -- DOHMH, DCWP, SLA, DOS, the Foursquare
-- closure ledger. Most of the universe (Overture, OSM, the Foursquare open
-- cache, USDA SNAP) publishes no status field at all and reads 'unknown'
-- forever. This table is the THIRD evidence channel: a paid, budget-capped
-- lookup (Google Places business_status, or a web search classified by
-- model/evidence/web_rules.classify) that a human or `loci verify-closures`
-- runs ON DEMAND for a specific POI, never citywide and never unbudgeted.
--
-- D79 STILL APPLIES, IN FULL. A row here is written ONLY when a source
-- (Google Places' businessStatus field, or a first-party/news web page)
-- POSITIVELY states a status. There is no "not found" -> closed inference:
-- an inconclusive lookup writes `verdict IS NULL` (a stored, spent attempt,
-- so `loci verify-closures --recheck-days` does not re-buy it immediately)
-- and changes nothing. Web evidence NEVER produces 'open' (model/evidence/
-- web_rules.py) -- a page not saying "closed" is not evidence the business
-- is trading, only evidence nobody wrote a closure notice.
--
-- PRECEDENCE IS BY DATE, NOT BY SOURCE TYPE (the constraint's own words:
-- "newest evidence date wins, regardless of source type"). model/
-- poi_evidence.py is the ONE place that rule is written, in two renderings
-- (`resolve()` in Python, `wrap_status_sql`/`wrap_basis_sql` in SQL) exactly
-- as model/poi_presence.poi_status()/poi_is_open() already are for the base
-- predicate -- two copies of a precedence rule is how a rule drifts.
--
-- `evidence_id` is `sha1(poi_id|source|url)`: the same (poi, source, url)
-- lookup re-run on a later day REPLACES its row rather than accumulating
-- duplicates, so a re-check after --recheck-days is a refresh, not a new
-- history entry. `dated_by` distinguishes a page's own published date
-- ('published') from "we only know when WE looked" ('retrieval', the only
-- option for Google Places, which publishes no date at all) from no date at
-- all ('none', an undated web hit -- stored for the record, but per
-- model/poi_evidence.resolve it can only ever overturn an 'unknown' base,
-- never a dated 'open' or 'closed' one).
--
-- `location_key` / `cluster_id` are INFORMATIONAL ONLY, carried for
-- debugging and for the report's supply table -- identity for matching is
-- `poi_id`, exactly as everywhere else in this codebase (poi_presence.py's
-- own caveat: cluster_id is an input-order artefact, not stable identity).
--
-- ---------------------------------------------------------------------------
-- THE VIEW WIRING (analysis.poi_supply_status)
-- ---------------------------------------------------------------------------
-- DuckDB binds a VIEW's query at CREATE time, so sql/029's
-- analysis.poi_supply_status -- created before this file exists -- cannot
-- reference analysis.poi_closure_evidence. Exactly the 021_address_character
-- pattern: db.init_schema re-renders analysis.poi_supply_status (and
-- analysis.poi_colocation, which reads it) with
-- model/poi_presence.colocation_view_sql(evidence=True) immediately AFTER
-- this file applies. sql/029_poi_colocation.sql itself is UNCHANGED and
-- stays the byte-identical rendering of colocation_view_sql(evidence=False)
-- -- that default is what tests/test_poi_colocation.py's
-- test_sql_file_matches_generator pins, and it is what a warehouse with no
-- closure-evidence table (033 not yet applied) still gets.
--
-- CAVEAT: supply_hash (score/supply.py) changes the moment ANY evidence row
-- lands, because poi_status can now flip on a row it used to read 'unknown'.
-- A forecast issued before a verify-closures run and scored after one will
-- show a model_version change with no re-fit -- documented in ce68d53's
-- model_version carrying the supply hash; this is the same mechanism firing
-- for a new reason.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analysis.poi_closure_evidence (
    evidence_id     VARCHAR PRIMARY KEY,  -- sha1(poi_id|source|url); re-check REPLACES
    poi_id          VARCHAR NOT NULL,
    location_key    VARCHAR,              -- informational only; identity is poi_id
    cluster_id      BIGINT,               -- informational only (unstable across dedup re-runs)
    verdict         VARCHAR CHECK (verdict IN ('open', 'closed')),  -- NULL = stored, inconclusive
    source          VARCHAR NOT NULL CHECK (source IN ('places', 'web')),
    source_name     VARCHAR NOT NULL,     -- e.g. 'Google Places', 'Eater NY', 'nypost.com'
    domain_class    VARCHAR,              -- first_party | news | aggregator | other (web only)
    url             VARCHAR NOT NULL,
    evidence_date   DATE NOT NULL,        -- the date the precedence rule compares on
    dated_by        VARCHAR NOT NULL CHECK (dated_by IN ('published', 'retrieval', 'none')),
    retrieved_at    TIMESTAMP NOT NULL,
    query           VARCHAR NOT NULL,     -- the exact search query, or 'places:searchText'
    reason          VARCHAR,              -- why an inconclusive lookup stored nothing (web_rules)
    successor_name  VARCHAR,              -- "now X" / "replaced by X" reading, never a new POI
    raw             JSON,                 -- the source response/hit, for audit
    run_id          VARCHAR               -- ties the row to a spend_ledger run
);
CREATE INDEX IF NOT EXISTS poi_closure_evidence_poi ON analysis.poi_closure_evidence (poi_id);

-- ---------------------------------------------------------------------------
-- THE SPEND LEDGER (shared with deliverable 4's allocator report, D100 --
-- reconciled 2026-09-14: ONE table, ONE set of columns, so a $1.00 report cap
-- and a --budget verify-closures run draw against the same enforcement code
-- path rather than two that could disagree). `kind` distinguishes the two
-- callers; `provider` the three paid APIs either can use. `poi_id` and
-- `detail` are NULL for a report's per-address prose call (there is no single
-- POI or query string to name) and populated for a per-POI closure check.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis.spend_ledger (
    run_id      VARCHAR NOT NULL,
    kind        VARCHAR NOT NULL CHECK (kind IN ('report', 'verify')),
    provider    VARCHAR NOT NULL CHECK (provider IN ('places', 'tavily', 'anthropic')),
    usd         DECIMAL(10, 6) NOT NULL,
    ts          TIMESTAMP NOT NULL,
    poi_id      VARCHAR,
    detail      VARCHAR
);
CREATE INDEX IF NOT EXISTS spend_ledger_run ON analysis.spend_ledger (run_id);
