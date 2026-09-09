-- 007 — staging.alcohol_licences
--
-- The ALCOHOL OVERLAY (owner decision 2026-09-08): every ACTIVE NYS Liquor
-- Authority licence in the city as its own map layer, classified on-premises
-- vs off-premises. It is deliberately NOT a 16th category and NOT part of
-- staging.poi:
--
--   * staging.poi is the normalized supply the score/ and model/ packages
--     consume. Dropping 24,780 licences into it would silently move every
--     DNCI, gap and reach number, and 8,253 of those rows are restaurants
--     DOHMH already anchors — the double count D47 exists to prevent.
--   * The overlay answers a different question ("where is alcohol licensed?"),
--     so it gets a different table and a different map layer.
--
-- nys_sla.py keeps emitting bar-class licences into staging.poi unchanged.
-- This table is written alongside it by `loci ingest-alcohol`.
--
-- One row per licencepermitid. `classification` comes from
-- sources/cities/nyc/alcohol_licences.yaml; 'unknown' means the licence type
-- is real but does not say on- or off-premises — never a silent drop.

CREATE TABLE IF NOT EXISTS staging.alcohol_licences (
    licence_id     VARCHAR PRIMARY KEY,   -- SLA licensepermitid
    description    VARCHAR NOT NULL,      -- raw licence type, as published
    licence_class  VARCHAR,               -- SLA numeric class code ("0340")
    classification VARCHAR NOT NULL        -- on_premises | off_premises_liquor |
                                           -- off_premises_beer | other | unknown
        CHECK (classification IN ('on_premises', 'off_premises_liquor',
                                  'off_premises_beer', 'other', 'unknown')),
    name           VARCHAR,               -- dba, falling back to legal name
    address        VARCHAR,
    zip            VARCHAR,
    borough        VARCHAR,               -- two-letter code, from premisescounty
    geom           GEOMETRY NOT NULL,     -- EPSG:4326 by convention (see db.py)
    expires_on     DATE,
    active         BOOLEAN NOT NULL,      -- expires_on >= today, or no expiry given
    observed_on    DATE
);
