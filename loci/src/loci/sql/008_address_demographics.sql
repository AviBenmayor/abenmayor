-- ---------------------------------------------------------------------------
-- 008_address_demographics.sql -- the 2026-09-09 age / race / education /
-- household-size block, at ADDRESS grain.
--
-- HISTORY (read this before wondering where the address_gaps columns went).
-- The first version of this migration copied all 36 analysis.hex_demographics
-- measure columns onto analysis.address_gaps by CONTAINING HEX. That is
-- superseded: analysis.address_demographics (D56) is the single canonical
-- address-grain demographic carrier, and it takes each value DIRECTLY from the
-- lot's own 2020 census tract via PLUTO's bct2020 (a BBL lookup, not a spatial
-- join, not an apportionment). Two reasons the hex-containment copy had to go:
--   1. It was doubly modelled -- tract -> hex by PLUTO-residential-unit
--      dasymetric apportionment, then hex -> address by containment. Neither
--      step adds information about the address, and the second is a step
--      function: two addresses either side of one hex boundary got different
--      demographics.
--   2. It gave the project TWO median_hh_income columns with different values
--      for the same address, and D57's demand annotation had to say in prose
--      which one it meant. One number, one place.
-- The address_gaps ALTER ... ADD COLUMN statements that were here are deleted,
-- not commented out; the columns themselves disappear with the table, which is
-- now a VIEW over analysis.address + analysis.address_category.
--
-- WHAT THESE VALUES ARE. Every column below is the address's own census
-- tract's published ACS 2023 5-year figure, unmodified:
--   * INTENSIVE (median_age B01002, avg_hh_size B25010): the tract's own
--     median/average and its own MOE, verbatim. The "a unit-weighted mean of
--     tract medians is not a median" approximation the hex table has to carry
--     does not arise at address grain -- an address sits in one tract.
--   * SHARES (age bands B01001, race/ethnicity B03002, college B15003,
--     one-person households B11016): numerator cells summed within the tract
--     by the ACS handbook sum rule, over the SAME table's own denominator, with
--     the handbook derived-proportion MOE. Computed by
--     model/address_demographics.py from grid/acs.py's own SHARE_SPECS /
--     INTENSIVE_SPECS dicts -- the hex table and this table cannot define a
--     measure differently, because they read one definition.
--
-- MOEs TRAVEL WITH THE ESTIMATES -- every measure has its `_moe` twin, per
-- CONTEXT.md's rule that ACS margins of error are propagated, never dropped.
-- Two caveats the database cannot enforce:
--   (a) these are TRACT figures repeated on every address in the tract. The
--       MOEs of two addresses in the same tract are perfectly correlated (they
--       are literally one number), so averaging *_moe across addresses is not
--       an average over ~767k independent draws -- it is an average over ~2,225
--       tracts, weighted by lot count.
--   (b) a share whose tract denominator is tiny can carry a proportion MOE
--       larger than the share itself. Gate on population/households before
--       sorting or filtering on any *_moe.
-- Nullable because ALTER cannot retro-fill: a NULL on a row written before
-- 2026-09-09 means "not populated by this run", NOT a demographic zero.
-- ---------------------------------------------------------------------------

-- intensive: the tract's own median / average, taken as-is
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS median_age FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS median_age_moe FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS avg_hh_size FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS avg_hh_size_moe FLOAT;

-- age bands (B01001, both sexes, over B01001_001 -- the table's own universe)
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS under_18_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS under_18_share_moe FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS age_18_34_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS age_18_34_share_moe FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS age_65_plus_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS age_65_plus_share_moe FLOAT;

-- race / ethnicity (B03002; the four cells are mutually exclusive and sum to <= 1)
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS white_nh_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS white_nh_share_moe FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS black_nh_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS black_nh_share_moe FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS asian_nh_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS asian_nh_share_moe FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS hispanic_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS hispanic_share_moe FLOAT;

-- education (B15003, bachelor's and above over the 25+ universe; associate's
-- deliberately excluded, matching model/momentum.py's convention)
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS college_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS college_share_moe FLOAT;

-- household composition (B11016_010 over B11016_001 -- a share of ALL households)
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS one_person_hh_share FLOAT;
ALTER TABLE analysis.address_demographics ADD COLUMN IF NOT EXISTS one_person_hh_share_moe FLOAT;
