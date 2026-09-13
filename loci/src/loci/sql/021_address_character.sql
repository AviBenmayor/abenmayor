-- ---------------------------------------------------------------------------
-- 021_address_character.sql -- NEIGHBOURHOOD CHARACTER at address grain:
-- is what is within a five-minute walk RETAIL-facing, DESK-facing, INDUSTRIAL
-- or RESIDENTIAL?  (owner request 2026-09-13, "give color to neighborhoods for
-- whether they are retail- or corporate-dominated".)
--
-- Written only by `UPDATE analysis.address SET <CHARACTER_COLUMNS>`
-- (model/address_character.py, `loci address-character build`). Never by the
-- screen, never by an INSERT.
-- ---------------------------------------------------------------------------
-- NO NEW TABLE (owner rule, D61 inventory): these are new MEASURES at an
-- existing grain -- one number per address -- so they extend analysis.address
-- exactly as homes_400m, jobs_400m and transit_entries_400m do. The SHARES and
-- the LABEL derived from them are pure arithmetic on these columns, so they are
-- a VIEW (analysis.address_character), not stored columns; the NTA roll-up is a
-- second VIEW (analysis.nta_character) over the first. Both views are created
-- by db.init_schema() straight after this file, from
-- model/address_character.address_character_view_sql() /
-- nta_character_view_sql(), so the label thresholds have ONE definition in the
-- codebase (Python constants) instead of two that can drift.
-- ---------------------------------------------------------------------------
-- UNITS AND MEANING, because the column names cannot carry it
--
--   retail_area_400m    SQUARE FEET of MapPLUTO RetailArea summed over every
--   office_area_400m    tax lot whose PLUTO point is within 400 m NETWORK
--   res_area_400m       metres on the pedestrian walk graph. OfficeArea,
--   factory_area_400m   ResArea and FactryArea likewise.
--   bldg_area_400m      BldgArea over the same lots -- the denominator that
--                       shows how much of the built floor area the four named
--                       uses actually account for (they do not sum to it:
--                       GarageArea, StrgeArea, OtherArea and unclassified
--                       floor area are the remainder, ~18% citywide).
--
--   THE LOT SET IS EVERY PLUTO LOT, NOT analysis.address's LOTS. This is the
--   one place where "reuse exactly what homes_400m uses" would have been
--   WRONG. analysis.address is `PLUTO lots WHERE UnitsRes > 0`
--   (sources/cities/nyc/addresses.py), so the homes_400m weight set contains
--   no pure-office, pure-retail and no industrial lot at all. Summing
--   OfficeArea over it would report One Bryant Park, 350 Park Avenue and
--   almost all of the Financial District as ZERO office floor area, and
--   Midtown East would come out "residential". The catchment ENGINE is
--   identical (same pruned graph, same CSR, same scipy Dijkstra sourced from
--   the query nodes, same 400 m); only the weight set is widened.
--
--   ONE DELIBERATE DIFFERENCE, AND NOT A BUG: homes_400m's weight set is
--   analysis.address, which since D78 holds MANHATTAN AND BROOKLYN ONLY, so it
--   carries a borough-boundary edge effect (a Bushwick address gets no credit
--   for Ridgewood's housing). These four area columns read PLUTO directly over
--   the padded scope bbox, Queens and the Bronx included, so they do NOT.
--   At the borough line res_area_400m and homes_400m disagree, the area column
--   being right and homes_400m truncated; never form a ratio of the two there.
--
--   jobs_retail_400m    LEHD LODES8 WAC jobs in 2020 census blocks whose
--   jobs_office_400m    CENTROID is within the same 400 m, split into three
--   jobs_other_400m     disjoint sector groups that SUM TO jobs_400m (C000).
--                       See RETAIL_FACING_SECTORS / OFFICE_FACING_SECTORS in
--                       model/address_character.py for the NAICS membership
--                       and the reasoning. `other` is a REMAINDER, not a
--                       category: health care and education are its two
--                       largest members in New York, and both are large
--                       daytime-population generators that are neither
--                       storefront retail nor desk work.
--
--   character_radius_m  the radius actually used. The COLUMN NAMES say 400.
--   character_pluto_version  MapPLUTO `version` (e.g. '24v4') -- the floor
--                       areas move with the assessment roll.
--   character_jobs_vintage   the LODES WAC year. LODES8 puts every year on
--                       2020 blocks, but pre-2020 years got there by
--                       area-proportional ALLOCATION, which is bias and not
--                       noise (CONTEXT.md 7.4b); 2023 is observed on its own
--                       blocks, which is why the present-day measure uses it.
--   character_run_at    NULL means `loci address-character build` has never
--                       run for this borough. It is also what the views key
--                       the label off: an unrun address gets a NULL label, not
--                       a fabricated 'residential'.
-- ---------------------------------------------------------------------------
-- ZERO IS AN OBSERVATION, NULL IS NOT A THING HERE (owner rule, D75: no
-- eligibility gate, never drop an address). A lot in a rail yard gets 0.0 sq ft
-- of office within 400 m, and that is a measurement. There is no censoring to
-- record either: a catchment SUM inside a hard 400 m radius has no ceiling the
-- way a right-censored `nearest_m` does.
-- ---------------------------------------------------------------------------
-- CAVEATS THE DATABASE CANNOT ENFORCE
--
-- 1. PLUTO FLOOR AREAS ARE AN ASSESSMENT ARTEFACT. `areasource` says whether a
--    lot's split came from DOF records, a DCP estimate or a sketch; a large
--    minority of lots carry an estimated split, and a mixed-use building's
--    ground-floor store is often folded into ComArea without ever reaching
--    RetailArea. RetailArea is therefore a FLOOR on storefront floor area, and
--    that bias is strongest exactly where it matters (old mixed-use rowhouse
--    retail strips). Never read retail_area_400m as "square feet of shops".
-- 2. LODES COUNTS PAYROLL JOBS AT A BLOCK CENTROID, not people on a sidewalk
--    (CONTEXT.md 7.4). Remote and hybrid workers are counted at an office they
--    may not enter -- which biases jobs_office_400m UP post-2020 relative to
--    actual daytime presence -- and most of the self-employed are not counted
--    at all.
-- 3. AREAS ARE STOCK, JOBS ARE FLOW-OF-PAYROLL, AND THE TWO DISAGREE. The
--    label rules take either as sufficient on purpose; where they disagree the
--    shares are both on the view, so a reader can see which one fired.
-- 4. THESE COLUMNS DO NOT ENTER gap_score, supply_ratio_vs_base, the revenue
--    model or any recommendation grade. They are context beside the screen.
-- 5. NEVER SUM A CATCHMENT COLUMN ACROSS ADDRESSES. A lot within 400 m of N
--    addresses is counted N times BY DESIGN; these are per-address catchments,
--    not a partition of the city.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- D82 ADDITIONS (urban-planner review of the first build). Four corrections,
-- three of which are new columns here:
--
--   office_area_400m  CHANGED MEANING, NOT NAME. It now EXCLUDES institutional
--                     lots -- PLUTO BldgClass starting I (health), M
--                     (religious), P (public assembly), W (educational), or
--                     LandUse 08 (public facilities & institutions). MapPLUTO
--                     books a hospital's floor area as OfficeArea, which is
--                     how the Brooklyn VA Medical Center gave Bay Ridge 47
--                     'corporate' addresses and Kings County / Kingsbrook gave
--                     East Flatbush-Rugby 134. A hospital campus is a large
--                     weekday population and is NOT a central business
--                     district. ANY QUERY WRITTEN AGAINST THIS COLUMN BEFORE
--                     D82 NOW MEANS SOMETHING DIFFERENT.
--   office_area_incl_inst_400m  the RAW OfficeArea sum over the same lots, so
--                     the size of the exclusion is visible rather than
--                     asserted. It is one more weight column in the SAME
--                     Dijkstra, so it costs nothing.
--   commercial_overlay_100m  COUNT of lots within 100 m NETWORK metres whose
--                     overlay1/overlay2 starts 'C1-' or 'C2-', or whose
--                     zonedist1 starts C1/C2/C4/C5/C6/C8. The ZONING witness:
--                     a C1/C2 commercial overlay is the instrument New York
--                     uses to permit ground-floor local retail on a
--                     residential street, and unlike RetailArea it cannot be
--                     under-reported by an assessor. >= 1 is an OR-route into
--                     'retail_mixed'.
--                     CAVEAT: this is a SECOND sweep of the same engine at a
--                     second radius; neither end's SNAP OFFSET is counted, so
--                     the effective radius is 100 m plus the lot's and the
--                     address's distance to their nearest graph nodes
--                     (typically 10-40 m on a dense grid). Read it as "on or
--                     beside this block", never as a metric buffer.
--   commercial_lots_400m / lots_400m  the numerator and denominator of
--                     commercial_overlay_share_400m, which is computed ON THE
--                     VIEW like every other share. Stored as counts so the
--                     share has no second definition.
--   character_near_radius_m  the radius the 100 m count actually used.
--
-- ALSO CHANGED, in Python constants and therefore in the VIEW, with no column
-- to alter: RETAIL_JOBS_FLOOR 1,000 -> 300 and RETAIL_JOBS_SHARE 0.40 -> 0.35
-- (a 1,000-job floor is a Manhattan number and erased 7th Ave Park Slope,
-- Cortelyou Rd and Pitkin Ave); CORPORATE_JOBS_FLOOR now guards BOTH corporate
-- routes; park/cemetery/airport NTAs and NTAs under 50 addresses get a NULL
-- label (`suppressed` on both views); and `retail_index` (0-1) is the
-- continuous retail measure the map should shade by.
-- ---------------------------------------------------------------------------

ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS retail_area_400m        DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS office_area_400m        DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS office_area_incl_inst_400m DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS res_area_400m           DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS factory_area_400m       DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS bldg_area_400m          DOUBLE;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS jobs_retail_400m        BIGINT;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS jobs_office_400m        BIGINT;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS jobs_other_400m         BIGINT;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS commercial_overlay_100m BIGINT;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS commercial_lots_400m    BIGINT;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS lots_400m               BIGINT;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS character_radius_m      REAL;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS character_near_radius_m REAL;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS character_pluto_version VARCHAR;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS character_jobs_vintage  SMALLINT;
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS character_run_at        TIMESTAMP;
