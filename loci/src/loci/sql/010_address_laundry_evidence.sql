-- ---------------------------------------------------------------------------
-- 010_address_laundry_evidence.sql -- merge the two in-building-laundry
-- evidence tables (D51(d)) into ONE, source-tagged table (owner
-- consolidation, 2026-09-09).
--
-- analysis.address_laundry (004_ll84_laundry.sql, LL84/LL133 plumbing
-- hookups) and analysis.address_listing_laundry (005_listings_laundry.sql,
-- StreetEasy advertised amenities) were two BBL-keyed tables answering the
-- SAME question -- "does this building have laundry?" -- from two different
-- kinds of evidence, with two near-identical VIEWs joining each to
-- analysis.address_gaps. Keeping them separate bought nothing: nothing in
-- score/ or model/ reads either (both are owner-undecided supply inputs,
-- same as before), and a reader who wants "what evidence exists for this
-- BBL" had to know to check two tables and reconcile two `_status` columns
-- by hand.
--
-- analysis.address_laundry_evidence is the UNION of both tables' fields,
-- keyed by (bbl, source) with source IN ('ll84', 'listing'). A field that
-- only one source measures is simply NULL on the other source's rows -- the
-- two kinds of evidence are still never pooled into one column (LL84 counts
-- plumbing, StreetEasy counts marketing copy; CAVEAT ZERO in the old
-- 005_listings_laundry.sql header still applies verbatim to the listing
-- rows), they just live in one table instead of two.
--
-- analysis.address_laundry_gaps replaces BOTH old _gaps views (address_
-- laundry_gaps and address_listing_laundry_gaps), joining analysis.address_
-- gaps to two filtered reads of the merged table (source = 'll84',
-- source = 'listing') so a caller sees both statuses in one row per address
-- instead of choosing which of two views to query.
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS analysis.address_laundry_gaps;
DROP VIEW IF EXISTS analysis.address_listing_laundry_gaps;
DROP TABLE IF EXISTS analysis.address_laundry;
DROP TABLE IF EXISTS analysis.address_listing_laundry;

CREATE TABLE IF NOT EXISTS analysis.address_laundry_evidence (
    bbl                     VARCHAR  NOT NULL,
    source                  VARCHAR  NOT NULL CHECK (source IN ('ll84', 'listing')),
    -- ---- LL84 fields (analysis.address_laundry, 004) -- NULL on 'listing' rows ----
    has_common_laundry      BOOLEAN,             -- NULL = never answered this field
    has_in_unit_laundry     BOOLEAN,             -- NULL = never answered this field
    laundry_measured        BOOLEAN,             -- at least one non-null answer, either field
    latest_vintage          SMALLINT,            -- vintage the winning answer came from
    n_vintages              SMALLINT,            -- vintages this BBL appears in at all
    n_vintages_disagree     SMALLINT,            -- vintages whose yes/no verdict differs from the winner
    common_area_hookups     INTEGER,             -- winning vintage's raw count
    in_unit_hookups         INTEGER,
    units_reported          INTEGER,             -- LL84 self-reported residential living units
    any_multi_bbl           BOOLEAN,             -- any contributing filing listed several BBLs
    -- ---- listings fields (analysis.address_listing_laundry, 005) -- NULL on 'll84' rows ----
    n_listings              INTEGER,             -- pages fetched for this BBL
    n_with_amenities        INTEGER,             -- pages that carried a broker amenity list
    n_in_unit               INTEGER,
    n_in_building           INTEGER,
    n_none                  INTEGER,             -- EXPLICIT negatives only (expected: ~0)
    n_silent                INTEGER,             -- amenity list present, laundry not mentioned
    latest_listed           DATE,
    any_laundry_advertised  BOOLEAN,             -- TRUE or NULL. Never FALSE. See CAVEAT ZERO (005).
    best_match_confidence   DOUBLE,
    sites                   VARCHAR,             -- comma-separated, provenance
    built_at                TIMESTAMP NOT NULL,
    PRIMARY KEY (bbl, source)
);

-- Join to the address screen, replacing BOTH analysis.address_laundry_gaps
-- and analysis.address_listing_laundry_gaps. Kept a VIEW for the reason both
-- predecessors were: address_gaps is rebuilt by `loci address-gaps`, and an
-- owner-undecided supply input must not become a column on the scored
-- table. `laundry_status` (LL84) and `listing_laundry_status` (StreetEasy)
-- are the two four/three-way answers each source's own view used to expose;
-- both survive unchanged, side by side, on the one merged view.
CREATE OR REPLACE VIEW analysis.address_laundry_gaps AS
SELECT
    g.address_id,
    g.bbl,
    g.borough,
    g.neighborhood,
    g.units,
    g.eligible,
    g.gap_score,
    g.lead_category,
    g.laundry_ratio,
    ll.has_common_laundry,
    ll.has_in_unit_laundry,
    ll.laundry_measured,
    ll.latest_vintage,
    ll.n_vintages_disagree,
    ll.units_reported                          AS ll84_units_reported,
    CASE
        WHEN ll.bbl IS NULL                                THEN 'no_ll84_record'
        WHEN NOT ll.laundry_measured                       THEN 'll84_blank'
        WHEN ll.has_common_laundry OR ll.has_in_unit_laundry THEN 'has_laundry'
        ELSE 'no_laundry'
    END                                         AS laundry_status,
    lst.n_listings,
    lst.n_with_amenities,
    lst.n_in_unit                               AS listing_n_in_unit,
    lst.n_in_building,
    lst.n_silent,
    lst.latest_listed,
    lst.any_laundry_advertised,
    lst.best_match_confidence,
    -- THREE-valued deliberately, not four: a listing that omits laundry is
    -- not evidence of its absence, so there is no 'no_laundry' state here
    -- (mirrors the old address_listing_laundry_gaps exactly).
    CASE
        WHEN lst.bbl IS NULL            THEN 'not_fetched'
        WHEN lst.n_with_amenities = 0   THEN 'no_amenity_data'
        WHEN lst.any_laundry_advertised THEN 'laundry_advertised'
        ELSE 'amenities_silent'
    END                                         AS listing_laundry_status
FROM analysis.address_gaps g
LEFT JOIN analysis.address_laundry_evidence ll
       ON ll.bbl = g.bbl AND ll.source = 'll84'
LEFT JOIN analysis.address_laundry_evidence lst
       ON lst.bbl = g.bbl AND lst.source = 'listing';
