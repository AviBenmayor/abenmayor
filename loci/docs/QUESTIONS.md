# Loci — Research Questions

**The build compass.** Two lists, kept separate:

- **Part A — questions the project answers.** Tiered by how much each can honestly claim:
  Measurement → Descriptive → Explanatory → Predictive → Causal. The charter's three
  falsifiable predictions (CONTEXT.md §1.4, P1–P3) are *evidence* for questions here, not
  questions themselves.
- **Part B — homework.** Things the owner must read up on or probe before building. Most are
  30-minute checks; they are deliberately **not** Linear tickets.

This file changes faster than `CONTEXT.md` (the charter) and slower than `CHECKPOINT.md`
(the state). Decisions still go in CONTEXT.md §9 and the CHECKPOINT decision log — this file
holds *questions* and their current answers only.

**Machine-checked.** `loci check-questions` asserts every ticket title cited in *Answered by*
exists in `src/loci/tickets.py`, every epic cited in *Unblocks* exists, every status is in the
vocabulary, and each of P1, P2, P3 is claimed by at least one question. Run it with
`make check`.

**Status vocabulary:** `open` · `in-progress` · `answered` · `deferred` · `dropped`.

## Stopping rule

**None.** A defensible DNCI map plus residual map ships regardless of how P1, P2 and P3 come
out — a null on the growth test is a real answer and still a publishable map.

One condition attached. If **M1** fails — the POI undercount concentrates in the very hexes
flagged as underserved — the *descriptive* map is contaminated in the same hexes, not just
the predictive claims. What survives is the food tier (DOHMH is a near-census) and any stratum
the Google sample validates. In that case the map ships restricted to those, and says so.

---

## Part A — Questions the project answers

### Tier M · Measurement — is the instrument sound?

These gate every tier below. A "no" here does not narrow a claim; it removes the ground the
claim stands on.

### M1 — Is the measured retail gap real, or a POI-coverage artifact?
- **Status:** in-progress
- **Prediction:** P3
- **Answered by:** `Design stratified coverage validation sample` · `Run Google Places ground-truth enumeration on sampled gap addresses` · `DOHMH-anchored undercount calibration (address level)` · `Coverage-bias chart` · `USDA SNAP retailer adapter (ANCHOR for grocery/convenience)`
- **Fails if:** the undercount rate by income decile is materially higher in hexes flagged as underserved than in their well-served peers.
- **Current answer:** Partly, and badly, for at least one category. 2026-09-02: adding the SNAP near-census cut bodega/convenience gap hexes from **166 to 16** — 90% of that gap type was an OSM/Overture coverage hole, not a missing business. Hardware, fitness and clinic gaps (the current top three) still rest on OSM/Overture only; the Google sample (`loci validate`) is aimed at those next. **2026-09-03 (CHECKPOINT D29/D30):** the raw Google survival rates (hardware 58%, fitness 29%, clinic 0%) turned out to measure the Google type map, not coverage — split each result into geometry-artifact vs true coverage hole. Corrected true-hole rates: hardware 5% [2–12] (not disproven — Google's type is an upper bound), fitness 21% [10–37] (real hole, needs an anchor, M7), clinic 0% [0–15] but unfalsifiable by construction (loci excludes doctor's offices, Google doesn't) — clinic dropped from headline claims pending a re-anchor to licensed urgent care (D30). 2026-09-09 (D58): the validator's sampling frame is now gap ADDRESSES stratified income decile × missing/present per category, both sides measured at the lot's point at 649 m; the 2,970 hex-frame rows are frozen and never pooled. GTM-48 still needs a budget approval to run.

### M2 — How well do LODES *jobs* proxy *establishments*?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Validate LODES 2023 against establishment counts`
- **Fails if:** the per-hex correlation between 2023 LODES retail employment and 2023 DOHMH/DCWP establishment counts is weak enough that the panel is measuring payroll, not storefronts.
- **Current answer:** —

### M3 — How much pre-2020 LODES allocation error leaks across res-9 hex boundaries?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Quantify pre-2020 LODES allocation bias`
- **Fails if:** the area-proportional retro-allocation moves a material share of jobs across hex boundaries in split blocks, so pre-2020 panel values cannot be treated as observed (CONTEXT.md §7.4b).
- **Current answer:** —

### M4 — Do Overture, Foursquare and OSM agree on presence, and where do they disagree?
- **Status:** in-progress
- **Prediction:** —
- **Answered by:** `Cross-source POI dedup / entity resolution` · `Foursquare OS Places adapter`
- **Fails if:** disagreement is concentrated by geography or by category (laundromats, salons) rather than spread randomly — then source choice is itself a bias.
- **Current answer:** Loaded 2026-09-02. Dedup on six sources collapses 25% of rows (299,029 → 224,370 canonical). **Foursquare's disagreement is mostly staleness, not geography:** rows last refreshed before 2019 are corroborated by any other source <10% of the time, 2026-refreshed rows 55%. With a 2024 freshness gate it adds 54k canonical POIs, concentrated in bars, gyms, cafes and salons. Its effect on the gap screen is modest (hardware 270→245, fitness 154→138) — the ungated version had erased far more, all ghosts. Also observed: adding any source can push a category's prevalence over the 80% 'expected' line and turn its absences into gaps (bank did, 0→285 hexes). That is a screen-design sensitivity, filed for the owner.

### M5 — Do ACS margins of error leave hex-level income and population usable as controls?
- **Status:** open
- **Prediction:** —
- **Answered by:** `ACS ingest + dasymetric interpolation onto hexes`
- **Fails if:** propagated MOEs on hex median income are wide enough that the income control cannot distinguish neighbouring hexes.
- **Current answer:** —

### M6 — For each loci category, are Google's included types narrower or wider than loci's definition?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Google type-map audit per category`
- **Fails if:** n/a — measurement. But any Google-validation survival rate is uninterpretable until this is aligned; D29 already found hardware narrower (excludes home_improvement_store) and fitness wider (gym/fitness_center sweeps in hotel/building gyms loci excludes) by inspection, not by a systematic audit.
- **Current answer:** Answered 2026-09-08 (GTM-105, D50). Both, per category: wider for restaurant/bar/grocery/convenience/hair/nails (any-type matching, now fixed to primary type), narrower for cafe_bakery (Google lacked donut/bagel/ice-cream/juice/dessert/tea that loci's own DOHMH keywords include) and fitness (missing yoga/sports_club). Structural: the 20-result cap right-censored counts (clinic 87.6% of sampled hexes, fitness 15.3%, hardware 0%), so D29's clinic and fitness numbers are not usable; hardware's survive. clinic and tailor_repair have no Google equivalent. Type histograms are now persisted per call, so the next run answers this empirically. Remaining open here: none — follow-ups are M8 (radius) and the anchor contradictions logged in CHECKPOINT next action 7.

### M7 — What anchor source would establish a true fitness coverage hole?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Fitness anchor source for the ~20% true coverage hole`
- **Fails if:** n/a — measurement/sourcing question. Needed because D29 found a real ~21% [10–37] true-coverage-hole rate for fitness after removing geometry artifacts, and OSM/Overture/Foursquare are the only sources feeding that category today — none is a near-census the way DOHMH is for food or SNAP is for grocery.
- **Current answer:** Open. Candidates to evaluate: NYS business registry, DOHMH (if it licenses fitness facilities), state gym/health-club licensing. None yet verified for NYC coverage or access.

### M8 — Should the validator compare against network distance rather than a straight-line radius?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Validator: network distance or circuity correction`
- **Fails if:** n/a — measurement. D29's GEOMETRY-artifact category exists precisely because the validator's straight-line radius and the screen's network-distance threshold disagree; a circuity correction or a direct network-distance comparison would remove the need to split results after the fact.
- **Current answer:** Answered 2026-09-08 (D53): circuity correction, not network re-measurement — Google Nearby Search only accepts a disc, so the fix is to make loci's disc match the network-800 set. Circuity measured on analysis.hex_poi_distance at 1.233 (borough spread 1.226–1.279; the four dense boroughs within 1%), giving 649 m; radius is config in reach_tiers.yaml, derived in code, stamped per row, and never pooled across radii. Closed.

### M9 — How do Loci's deduped POI counts compare with Census ZIP Business Patterns establishment counts, per category and ZIP?
- **Status:** in-progress
- **Prediction:** —
- **Answered by:** (not ticketed yet — Linear cleanup 2026-09-05 adds one) — CLI subcommands ingest-zbp and zbp-compare; table analysis.zip_coverage_check; CHECKPOINT D40
- **Fails if:** ratios are far above 1 in categories that are NOT sole-proprietor-heavy — that would mean the POI feeds overcount supply (stale or duplicate records), which tightens every reach value and hides gaps.
- **Current answer:** Expectation (not a P1–P3 prediction): Ratios near 1 for employer-heavy categories (pharmacy, bank, grocery, hardware); above 1 for sole-proprietor-heavy categories (nails, barber, tailor) because CBP/ZBP counts only establishments with paid employees. First run (2026-09-05, ZIPs with population ≥1,000; ratio = Loci POIs / ZBP establishments): median ratio by category — childcare 0.85, clinic 0.95, laundry 1.33, pharmacy 1.48, grocery 2.06, bank 2.17, convenience 2.31, hair_barber 2.79, restaurant 3.16, hardware 3.21, cafe_bakery 3.51, fitness 5.92, bar 6.00, nails_beauty 7.96. Share of ZIPs above 2× is 94–98% for restaurant, cafe_bakery, fitness, bar, nails. Pattern: the categories closest to 1 are the OSM/Overture-only ones (childcare, clinic, laundry, pharmacy); the largest overcounts are exactly the license-registry-anchored categories (DOHMH → restaurant/cafe, NYS DOS → hair/nails, SLA → bar) plus fitness. Consistent with D36 (DOHMH turnover duplication) and suggests SLA and NYS DOS anchors also carry closed or non-storefront licensees. Bank at 2.17 and hardware at 3.21 are not explained by the employer-only bias and point to POI duplication or ZIP assignment error. Caveats: POI→ZIP uses a majority-vote hex→ZIP crosswalk from PLUTO lots (no ZCTA polygons in the DB); ZIP population is summed dasymetric hex population; CBP excludes non-employers and noise-infuses cells from 2017 on; NAICS self-classification bleeds between adjacent formats (Meltzer & Schuetz). Next: (a) rerun per SOURCE (which feed drives each overcount), (b) ZCTA polygons for a proper ZIP join, (c) use `analysis.zip_category_establishments` size bands for D9 and establishments-per-resident for O6.
 UPDATE (per-source run, CHECKPOINT D47): the overcount is mostly uncorroborated single-source records — dropping them gives restaurant 1.09, cafe 1.12, hardware 0.86, hair 0.65, but bar 1.54, fitness 1.74, nails 1.77 remain; fitness and hardware have NO license anchor (Overture+Foursquare only), so the "license-anchored" framing above applies to restaurant/cafe/hair/nails/bar only. Staleness untestable for DOHMH and DOS because the adapters do not fetch date fields; SLA 0% expired. Residual hypothesis: dedup misses (registry name vs storefront name).

### M10 — Which MN+BK addresses have laundry in the basement or in unit, and from what source?
- **Status:** in-progress
- **Answered by:** (not ticketed) — loci ingest-ll84, loci ingest-listings pilot, DCWP laundry anchor (D55, owner request 2026-09-08)
- **Why it matters:** An address with in-building laundry does not experience a laundromat gap, so the laundry category's supply is under-counted wherever such buildings cluster; laundry currently owns the top of the ratio ranking.
- **Current answer:** None; research agent probing DOB certificates of occupancy, DOB job filings, HPD registrations, and listing-site amenity data.

### M11 — What is the co-location structure of the 15 categories net of density, and how should 'expected presence given neighbors' enter the grade?
- **Status:** answered
- **Answered by:** (not ticketed) — scratchpad colocation.md, coloc_*.csv, session 13 (2026-09-08)
- **Tag:** *method / grading*
- **Why it matters:** Each category's grade needs to account for which neighbors' presence should be predictive of this one. Partial correlations sorted by R² inform which categories are supply-independent (stand-alone risk) vs demand-dependent (predictable from peers).
- **Current answer:** Manhattan is saturated (8/15 categories at 100% presence), structure is identified off Brooklyn; hair↔nails partial r 0.65; food block (restaurant/cafe/bodega/bar); hardware↔grocery 0.50; bank↔tailor pair alone; laundry↔bodega/cafe; zero significant negative pairs. The five categories with most absences (laundry, bar, tailor, bank, bodega) are worst-predicted (pseudo-R² 0.18–0.39) — their absence is not conspicuous given neighbors; hardware (R² 0.53) and cafe (0.39) best-conditioned. Use as a grade input (expected presence), not a finder; re-run once the supply set is settled.

### Tier D · Descriptive — what is where

### D1 — How complete is the daily-needs bundle within a 10-minute walk across NYC, and how is completeness distributed?
- **Status:** open
- **Prediction:** —
- **Answered by:** `DNCI: weighted geometric mean + unit tests` · `SHIP W2: the DNCI map`
- **Fails if:** n/a — descriptive. Report the distribution by borough and the share of hexes below 0.5.
- **Current answer:** —

### D2 — Which category drives the gap?
- **Status:** open
- **Prediction:** —
- **Answered by:** `DNCI: weighted geometric mean + unit tests` · `Per-category radar small multiples for top gap clusters`
- **Fails if:** n/a — descriptive. The question: in low-DNCI hexes, is the missing piece essentials (grocery, pharmacy, laundry) or food & gathering, and does gap composition cluster into recognisable types? Changes what an "opportunity" means.
- **Current answer:** —

### D3 — How sensitive is the completeness picture to walk threshold and tier weights?
- **Status:** in-progress
- **Prediction:** —
- **Answered by:** `Run 5/10/15-minute threshold sweep` · `Tier-weight sensitivity analysis`
- **Fails if:** the bottom decile of hexes reshuffles substantially between 5/10/15 minutes or across plausible reweightings — then "underserved" is an artifact of parameter choice.
- **Current answer:** **Partially answered — Manhattan only.** 2026-09-03 (`d3_manhattan_walk_threshold.py`, read-only; CHECKPOINT D31). It fails: not just a reshuffle but a category-mix flip.

  | Walk window | Eligible hexes | Gap hexes | Lead categories |
  |---|---|---|---|
  | 10 min (gate fixed) | 419 | 9 | mixed, no single dominant type |
  | 5 min (gate recomputed) | 371 | 19 | convenience (16), hair_barber (3) |
  | 5 min (gate held fixed) | 419 | 53 | upper bound, noisier |

  At 5 minutes, hardware/pharmacy/clinic/bank vanish as gap types (their 400m prevalence drops below
  the 0.80 expected bar) and convenience/hair_barber dominate instead, concentrated in
  superblock/institutional footprints (FiDi, Lincoln Square, Morningside Heights, Turtle Bay). Not
  yet run for Brooklyn/Queens/Bronx/Staten Island or the 15-minute end of the sweep. Motivates D6/D7
  (per-category, density-class thresholds) as the next-session focus.

  **2026-09-03:** this 10-vs-5 comparison is what revealed that the "missing" rule itself violates
  monotonicity (a gap at 10 min must survive at 5 min, and here it didn't) — see D6, now rewritten
  around that finding, and CHECKPOINT D33. D3 is superseded in spirit by D6: the open question is no
  longer "how sensitive is completeness to one shared threshold" but "the shared threshold was never
  well-defined." Status left as-is below pending the reach-based rebuild.

### D4 — Where do transit-rich and daily-needs-poor hexes overlap?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Bivariate transit × residual map` · `MTA transit access control`
- **Fails if:** n/a — descriptive. This is the thesis stated as one image.
- **Current answer:** —

### D5 — How far apart do same-type businesses sit, and how far is the nearest missing business from a gap hex?
- **Status:** answered
- **Prediction:** —
- **Answered by:** `Spacing and nearest-missing distance diagnostics` · `Cross-source POI dedup / entity resolution`
- **Fails if:** n/a — descriptive. Bears on what a "gap" means: a hex 900 m from a hardware store is a marginal ten-minute gap; 3 km is a hole.
- **Current answer:** (2026-09-02, **walk-network metres**, five boroughs, canonical POIs, same graph as `hex_access`) **Same-type spacing is tight.** Median network distance to the nearest other business of the same type: 0 m for nails and restaurants (same address), 13–32 m for bars, cafes, salons, groceries, clinics, gyms, 65–113 m for banks, pharmacies, bodegas, laundromats, ~200 m for childcare and hardware. Share with no competitor within a 10-minute walk: hardware 11%, tailors 16%, childcare 6%, everything else under 4%. **Gap hexes are a 10-to-17-minute band, not holes.** The nearest missing business is a median 860–1,030 m on foot from the hex (p90 1,100–1,400 m); only 26 of 726 hexes are beyond 1.5 km and none beyond 4 km. Run `loci spacing` (2 min). Straight-line numbers quoted earlier were superseded; D16 records the distance bug found on the way. Dedup lead in H-D11.

### D6 — What is the empirical distribution of hex-to-nearest-business network distance per category, and should each category's "missing" threshold be set from it?
- **Status:** answered
- **Prediction:** —
- **Answered by:** `Redefine 'missing' via per-category reach (monotonicity fix)`
- **Fails if:** n/a — descriptive/method question. **Finding (2026-09-03, owner-identified):** the current "missing" rule violates monotonicity. A hex is a gap for category c at window w iff (no c within w) AND (c is present within w for ≥80% of walkable hexes). Anything absent within 800m is absent within 400m, so a gap at 10 min must survive at 5 min — but D3's Manhattan sweep (D31) shows hardware gaps at 10 min vanishing at 5 min, because hardware's 400m prevalence drops to 51% and the 80% bar simply stops expecting it. The rule fuses two questions that must be separated: (a) how far people normally go for category c — a property of the category; (b) whether this hex is anomalous relative to that norm — a property of the hex. Reusing one window for both means the window silently decides which categories are eligible to be missing, so the 10-min and 5-min lists are two different screens, not two views of one.
  **Definition (supersedes the single citywide window):** each category gets a fixed REACH, set once from revealed spacing (e.g. the distance within which ≥80% of populated hexes already have one — the 80% bar survives only as the quantile that sets reach, never again as an eligibility filter). A hex is a gap for c iff its nearest c is beyond reach(c); no global window remains. The "walkable" eligibility gate (currently ≥12/15 categories present within the window) gets the same treatment: walkable iff within reach of most categories, each at its own reach.
  **Acceptance test — MONOTONICITY:** tightening any distance parameter may only add gaps, never remove them. The current screen fails this; the reach-based redefinition must pass it as a unit test.
  **Caveat to carry:** revealed spacing reflects historical supply, not demand — a category the whole city under-supplies will look like it "naturally" spaces wide and its gaps vanish. Contrarian review required before trusting the reach values. See D3 (the Manhattan sweep that exposed this), D7 (density-class scaling of reach), CHECKPOINT D33.
- **Current answer:** Built and verified 2026-09-05 (CHECKPOINT D34): fixed per-category reach, `loci gaps --rule reach`, monotone on real data. But reach = p80 of the hex-to-nearest distribution fixes the gap rate at ~20% per category by construction, so per-category counts are flat and the exactly-one list is a quantile artifact (p80∩p90 = 95/468). The architecture stands; the calibration statistic and the lead rule do not. Continues as D8.

### D7 — Should thresholds vary by density class or transit/car-dependence, not just by category?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Density-class / mode-dependent thresholds`
- **Fails if:** n/a — descriptive/method question. Lower Manhattan and car-dependent outer-borough areas should not share one walk window. Cheap proxy: scale the threshold by residential density class (no new data needed). Honest version: ACS vehicle ownership per tract (needs an ACS vehicle-ownership ingest; key is set). Note the interaction with D6: threshold(category, density_class) is one parameterization, not two independent sweeps — keep it small to avoid overfitting a matrix.
- **Current answer:** Open; still needs the ACS vehicle-ownership ingest for the mode/car-dependence threshold (key is set). 2026-09-05 (CHECKPOINT D43): mature Manhattan's complete areas reveal amenity distances 3–7× tighter than the adopted citywide tiers — a single reach is either too loose for Manhattan or too tight for Queens. Proposed: reach(c) per density class from complete addresses in that class, floored by reach_tiers.yaml's cited values. See docs/market_reach_manhattan.md.

### D8 — What statistic sets reach(c) without fixing the per-category gap rate, and how should the lead category be ranked?
- **Status:** answered
- **Prediction:** —
- **Answered by:** `Redefine 'missing' via per-category reach (monotonicity fix)`
- **Fails if:** every candidate calibration statistic still yields flat per-category gap counts, or the exactly-one list overlaps <80% across reasonable calibration variants — in which case "the one missing business" is not identifiable from spacing alone and needs an external norm (walk-time tiers per category, D7 density classes). Candidates to compare: (a) median same-type nearest-neighbour spacing; (b) external per-category walk-time norms (H-L3, H-L4); (c) p80 restricted to the gated universe (shrinks reach 8–25%). Acceptance battery is in CHECKPOINT D34: monotonicity, non-flat category counts, ≥80% list stability, lead excess ≥100 m, coverage split on the lowest POI-density decile. Also carry: corr(n_missing, log local POI count) = −0.67 — any calibration must be checked against M1's coverage question before a gap count is quoted.
- **Current answer:** Compared 2026-09-05 (CHECKPOINT D35). Same-type store-to-store spacing measures clustering (median 0–218 m) and is unusable; p80 on any universe pins the gap rate (CV 0.003–0.063). External walk-time tiers (400/800/1,200 m by trip frequency) are the only calibration whose per-category counts carry information (CV 1.07) and the most stable under ±10% perturbation (Jaccard 0.54); lead by max nearest/reach ratio. Not adopted: the tier assignment is now the load-bearing judgment and must be pinned to H-L3/H-L4 or to conveniences.yaml's owner norms. The −0.6 to −0.7 correlation with local POI density survives every calibration — that is M1, not D8. Address-level re-run 2026-09-05 (CHECKPOINT D39) confirms: external tiers are the only non-tautological calibration, the tier assignment is load-bearing, and the exactly-one list is unstable under every calibration — publish a continuous ranking, not a binary list. The eligibility gate must be reach-independent or monotonicity fails. Tier sources researched 2026-09-05: 4/15 categories have a citable walk threshold (grocery 800 m — USDA FARA 0.5 mi urban, NYC FRESH, Portland 20-min; pharmacy 800 m — Guadamuz/Qato 2021 low-income/low-vehicle threshold; restaurant and cafe_bakery 400 m — Walk Score full-credit radius), 3 are analogs (convenience 400, bar 400 weak, fitness 1200 vs CDC's 1 mi), 8 have no walk-scale literature (laundry, hair_barber, nails_beauty, tailor_repair, childcare, clinic, bank, hardware — clinic and bank standards are drive-based). Literature runs ~25% wider than conveniences.yaml where both exist. Walk Score uses continuous decay, not tiers. Proposed table: src/loci/reach_tiers.yaml; sources: docs/reach_sources.md. Recommendation pending owner: cited values where they exist, owner norms elsewhere, continuous ranking. ADOPTED 2026-09-05 (CHECKPOINT D41): reach_tiers.yaml (cited where available, owner norms elsewhere) + continuous max nearest/reach ranking; tier edges set only the flag, not the order. Shipped at address level 2026-09-05 (CHECKPOINT D44); ranking is dominated by tailor_repair and laundry, so a lead-viability rule is the next decision.

### D9 — Is a count/distance-based gap flag missing quality gaps that a size or diversity measure would catch?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not ticketed) — needs an establishment-size proxy (employment band, floor area from PLUTO retail sqft, or chain identity) per POI
- **Fails if:** size/diversity metrics are highly correlated with count-based presence (paper reports 0.70–0.90 correlation among density metrics but weak correlation to size/diversity — so expect this NOT to fail).
- **Current answer:** Expectation (not a P1–P3 prediction): Some hexes that pass the reach test for grocery are served only by small-format stores (bodega-scale), which Meltzer & Schuetz show is the actual low-income pattern. — (Source: Meltzer & Schuetz 2012 Table 4 and the Herfindahl index over NAICS subsectors.)

### D10 — Is a max nearest/reach ratio comparable across categories with different reaches, and what does a graded recommendation look like?
- **Status:** open
- **Answered by:** (not ticketed) — session-13 grade proposal and contrarian review (scratchpad grade_proposal.md, grade_contrarian.md; D48/D51, 2026-09-08)
- **Why it matters:** The ranking sorts every address by its single worst ratio across 15 categories. The category with the tightest reach (laundry, 320 m) mechanically produces the largest ratios, so it owns the top of any ranking regardless of whether its gaps matter most. A grade needs to combine the ratio with absolute excess meters (D44 candidate b, sound as an input) and residential density, and to define the band above which the recommendation is "act, at a fair price."
- **Current answer:** None. Session-13 description on MN+BK and a data-scientist proposal are in progress; contrarian to attack whatever the proposal picks.

### D11 — Which supply set is real: all POIs, corroborated-only (≥2 sources), or active-licensed?
- **Status:** in-progress
- **Answered by:** (not ticketed yet) — D52 supply-set principle: loci anchor-coverage, loci zbp-compare --supply-sets, view analysis.poi_supply (2026-09-08)
- **Why it matters:** The contrarian's re-run showed the act band moves 6× and rank-correlates at 0.19 between the all-POI and corroborated-only sets; nothing else in the grade matters until this is settled.
- **Current answer:** None; D36/D47 plumbing in progress (fetch DOHMH/NYS DOS date fields, active-establishment filter).

### D12 — Where does absent supply reflect revealed demand rather than a gap (bars in Midwood/Borough Park), and what non-income demand control catches it?
- **Status:** open
- **Answered by:** (not ticketed) — needs a non-income demand control before discretionary categories are published (D51, 2026-09-08)
- **Why it matters:** The largest cell in the drafted grade's act band is ~9,800 bar gaps in high-income south-central Brooklyn where the income caveat is silent; publishing it would repeat the D1 error.
- **Current answer:** None; candidates to probe are religious-institution density, SLA license application counts, and household composition from ACS.

### D13 — Which additional daily-needs categories belong in the screen, in what order, and which are too discretionary or too car-dependent to include?
- **Status:** open
- **Answered by:** (not ticketed in Linear yet) — milestone E10 Category Expansion generated 2026-09-09 via loci gen-tickets, pending owner review (D55)
- **Tag:** *scope / categories*
- **Why it matters:** The 15 categories were chosen before the address screen existed; the co-location regression shows hair↔nails behave as one amenity, while liquor stores, dentists, vets, shipping, specialty food and dollar stores are absent from the list yet common on walkable blocks. Expanding the bundle affects the gap prevalence thresholds and resets every supply-set validation.
- **Current answer:** Planning agent's proposal (scratchpad category_expansion_plan.md) and tickets under a new milestone, pending owner review.

### D14 — Does nails_beauty's DOS registry anchor over-count (≈3× ZBP), and what is the right supply set for a category whose anchor itself is inflated?
- **Status:** open
- **Answered by:** (not ticketed) — D59 caveat; candidates: tighten booth-renter radius, exclude non-salon appearance-enhancement licence types, or cap anchor coverage at ZBP parity
- **Tag:** *data / supply*
- **Why it matters:** anchor qualifies for the wrong reason; PRINCIPLED nails still 3.74× ZBP, flagged OVER; what to do about it?
- **Current answer:** None.

### Tier X · Explanatory — conditional structure, no temporal claim

### X1 — How much DNCI variation is explained by density, income, transit and commercial zoning capacity?
- **Status:** open
- **Prediction:** P1
- **Answered by:** `Fit the supply model`
- **Fails if:** R² > 0.9. Retail supply is fully determined by the controls and there is nothing left to explain.
- **Current answer:** —

### X2 — After controls, where is retail materially undersupplied relative to comparable hexes, and is the residual spatially clustered?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Residual extraction + opportunity score` · `Moran's I + spatial error/lag model`
- **Fails if:** Moran's I on the residual is significant and the spatial-error re-estimate changes which hexes sit in the tail. Report both models either way.
- **Current answer:** —

### X3 — Does the residual behave differently by borough or in high-foreign-born hexes, and is that real or coverage bias?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Fit the supply model` · `Design stratified coverage validation sample` · `Coverage-bias chart`
- **Fails if:** a borough or foreign-born contrast in the residual disappears once the stratum's measured undercount is applied — then it was M1 wearing a costume. The validation sample is stratified by foreign-born share as well as income so this can be separated.
- **Current answer:** —

### X4 — Is the top-20 underserved list free of zoning artifacts, and does it contain genuine surprises?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Top-20 list + zoning-artifact audit`
- **Fails if:** any park edge, industrial zone or cemetery block appears (the zoning control failed), or fewer than three entries are places not nameable in advance (the residual is not doing any work).
- **Current answer:** —

### X5 — Is Staten Island a high-leverage outlier that distorts the supply model?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Staten Island leverage check`
- **Fails if:** Cook's distance flags Staten Island hexes and coefficients move materially with them excluded. Report with and without.
- **Current answer:** —

### X6 — Does race/ethnicity predict gap incidence net of income and density, and in which direction?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not ticketed)
- **Fails if:** gap incidence by race is fully explained by income_class + population density.
- **Current answer:** Expectation (not a P1–P3 prediction): Per Meltzer & Schuetz, predominantly Black hexes show more gaps than income alone predicts; predominantly Hispanic hexes fewer (more small-format supply). Loci has NO race/ethnicity column today; needs an ACS B03002 ingest. — (Descriptive only; this is the "retail redlining" question. Investor lens: a gap that exists for supply-side reasons in a high-demand area is the strongest kind of opportunity; a gap that reflects thin demand is not. The demand_caveat flag is the first, crude version of that distinction.)

### Tier T · Predictive — temporal ordering, no identification claim

### T1 — Does a negative residual in 2013 predict above-average growth 2013→2023?
- **Status:** open
- **Prediction:** P2
- **Answered by:** `Main growth regression (prediction P2)` · `Assemble outcome variables`
- **Fails if:** β is null or positive across population, households, rents and permitted units. Gaps then persist because they reflect durable demand suppression, not latent opportunity.
- **Current answer:** —

### T2 — Does the 2013 residual also "predict" the prior decade?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Pre-trend test (2003→2013)`
- **Fails if:** u_2013 predicts 2003→2013 growth with the same sign. Parallel trends is broken and the causal reading is unavailable. Report it either way.
- **Current answer:** —

### T3 — Does a placebo outcome with no mechanism return a null?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Placebo outcome`
- **Fails if:** change in share of population aged 65+ is "predicted" by the residual — the specification is picking up generic neighbourhood trajectory.
- **Current answer:** —

### T4 — Do the results survive MAUP and a spatial error specification?
- **Status:** open
- **Prediction:** —
- **Answered by:** `MAUP sweep at res 8 and res 10` · `Moran's I + spatial error/lag model`
- **Fails if:** the sign or significance of β flips between res 8, 9 and 10, or under the spatial error model.
- **Current answer:** —

### T5 — Does the gap close on its own?
- **Status:** open
- **Prediction:** —
- **Answered by:** `LODES WAC annual panel loader 2002–2023` · `LODES block → hex apportionment` · `Residual convergence test`
- **Fails if:** n/a — exploratory. The question: over 2002–2023, do negative-residual hexes converge toward their peers? If yes, the market already corrects and the opportunity is *timing*, not location. The memo must say which.
- **Current answer:** —

### T6 — Does retail lead or lag rooftops?
- **Status:** open
- **Prediction:** —
- **Answered by:** `LODES WAC annual panel loader 2002–2023` · `Retail lead/lag timing test`
- **Fails if:** n/a — exploratory. Directly interrogates "retail follows rooftops", the assumption the residual design rests on. Caveat: ACS 5-year smoothing limits timing resolution to roughly half-decades; LODES is annual but is jobs, not storefronts (M2).
- **Current answer:** —

### T7 — How do nearby storefronts respond to a residential density shock (new units / occupancy), on what lag, and at which construction stage is the signal actionable?
- **Status:** open (proposed 2026-09-09)
- **Prediction:** —
- **Answered by:** `Ingest DOB Certificates of Occupancy + PLUTO vintage archive` · `Stacked matched event study around ≥50-unit completions`
- **Fails if:** Q5 not separating from Q1 beyond bootstrap CI; separation already present at τ=−4; not beating persistence baseline; **KILL CHECK (verified 2026-09-09):** no storefront opening/closing time series exists in Loci. Only foursquare_os_places has opened_on (109k rows; 2010 spike is Foursquare's launch, not storefronts). nys_sla_liquor_licenses has opened_on only for recent licences (3,205 rows, 2023-09→2026-09). overture, dohmh, dos, snap, dcwp_inspections have no opened_on. No source has closed_on. Conclusion: Loci has no storefront opening/closing time series; the one-session MVA cannot run until inactive/expired DCWP licences, full historical SLA licences, and raw DOHMH history are ingested (Increment-2 work, not an MVA).
- **Current answer:** Exploratory only, pending full historical licensing ingest (see *Fails if* above). T5 (gap closure over 2002–2023) and T6 (retail vs rooftop lead/lag) map longer horizons. Timing catalysts from O5: catalyst→construction ~5–9 yr, catalyst→demographic ~10–20 yr (market-rate only). LODES panel issue: registry.yaml describes lodes_wac as annual 2002–2023, but analysis.hex_panel holds only three vintages (2002, 2013, 2023; ~11.5k hex rows each); cannot resolve a 1–3 year lag. Registry mismatch flagged for docs/CHECKPOINT decision log. Literature synthesis: Li 2022 JEG (effects within ~500 ft, 1–3 yr, modest), Asquith/Mast/Reed 2023 REStat (amenity effect too small to offset rent), Glaeser/Luca/Moszkowski 2023 (gentrifying tracts show faster entry AND exit), HR&A 2024 + NYC Comptroller 2024 (churn > net growth; post-COVID glut). **Contrarian caveats to carry (2026-09-09, Opus review):** (a) survivor truncation in opened_on series manufactures clean event-time separation under the null (gentrifying hexes have higher exit rates); (b) licence date ≠ opening date, lag longer for new construction, biasing estimated lag toward zero where treatment is; (c) "flat count, more profitable" unfalsifiable with survival/LODES/ZBP proxies — needs lease comps, taxable sales, or foot-traffic panel; (d) stage rule (permit→open by CO+18 mo) asserted, not estimated — needs issued-permit→CO survival curve + out-of-sample horse race (stage-s pipeline at t predicting openings at t+k, ≤2016 train / 2017–23 test, vs baselines, by category); (e) hex-year panel conflicts with address-level directive; narrowest charter-consistent framings are a demand-pool covariate (units under construction / recently CO'd within reach) or a timing annotation on ranked gap addresses. **Provisional planner heuristic (unvalidated):** permit issued → underwrite for daily-needs; operating by CO+18 mo → demand arrives; 50–60% leased across ≥2 buildings → signal for restaurants/fitness. Subsumes T6's focus on magnitude, lag, and pipeline-stage forecast skill.

### Tier C · Causal — deferred; requires identification

### C1 — Does adding daily-needs retail to a transit-rich, underserved hex *cause* residential growth?
- **Status:** deferred
- **Prediction:** —
- **Answered by:** `Identification strategy: quasi-experimental variation`
- **Fails if:** no plausibly exogenous source of variation in retail supply can be found (candidates: historic rezonings, the L-train shutdown). Without one the project makes no causal claim, and the memo says so (CONTEXT.md §7.2).
- **Current answer:** Out of scope at four weeks. Phase 5.

### C2 — Does the effect appear in behaviour before it appears in residence?
- **Status:** deferred
- **Prediction:** —
- **Answered by:** `Foot-traffic outcome`
- **Fails if:** foot-traffic data is unaffordable within the ~$400 headroom after the validation sample is enlarged, which has priority.
- **Current answer:** Phase 5, budget-dependent.

### C3 — Does the pattern generalize beyond NYC?
- **Status:** deferred
- **Prediction:** —
- **Answered by:** `Extract universal interface; run a second city`
- **Fails if:** the universal-source-only run on a second city produces a residual distribution with no usable spread, or the NYC-only controls (PLUTO zoning) turn out to be load-bearing with no national analogue.
- **Current answer:** Phase 5.

### Tier O · Opportunity axes — the present-day investment screens (Axes 3–4)

Added 2026-09-02. These belong to the **re-scoped product** (CHECKPOINT scope-correction banner):
present-day screens for *where to act today*, not the residual/growth program above. Axis 3 =
premium/destination amenities (CONTEXT §11, milestone E6); Axis 4 = maturity + 2033 projection
(CONTEXT §12, milestone E7). Axes 1–2 (`invest.py`, `rising.py`) are not yet written up as
questions here — a smaller remaining gap.

### O1 — Where is there unmet demand for a premium destination amenity (padel, spa)? · *predictive screen*
- **Status:** open
- **Prediction:** —
- **Answered by:** `Premium opportunity score + ranked site list` · `Travel-time catchment engine (drive + transit isochrones)` · `Premium demand pool per catchment`
- **Fails if:** the ranked site list reshuffles materially across 10/15/20/30-minute catchments — then "opportunity" is an artifact of the willingness-to-travel assumption, which is the load-bearing parameter of the whole axis (it inverts the walkable gap screen precisely because people travel for these). Report the ranking under the catchment sweep, never a single radius.
- **Current answer:** —

### O2 — Is a premium-amenity "gap" real, or a supply-coverage artifact (worse than M1)? · *measurement*
- **Status:** in-progress
- **Prediction:** —
- **Answered by:** `Ingest premium-amenity supply + Google-validate (mandatory here)`
- **Fails if:** Google + a manual web check finds the amenity already present within the candidate's catchment. This threat is *sharper* than M1: padel barely existed before 2022 and boutique studios open fast, so OSM/Foursquare snapshots undercount them severely and unevenly — a padel "gap" is more likely a data hole than a daily-needs gap is.
- **Current answer:** **Confirmed, and for padel it's total.** 2026-09-02 Google validation (8 budget-charged calls, `src/loci/validation/google_places.py`): **PADEL — Foursquare 0 vs Google 22 real named venues** (Padel Haus Williamsburg/Greenpoint/Dumbo, Reserve Padel Hudson Yards/UES, Court 16 LIC) — a 100% coverage artifact, so padel CANNOT be screened from OSM/Foursquare and its supply must come from Google/manual. The existing venues cluster in the exact high-demand NTAs the model flagged, so the demand model validates but the top cores are already served — the real padel opportunity is the demand-rich + buildable + not-yet-served set (e.g. Sunnyside: 241 large-format sites, no venue found). SPA and PILATES: Google returns ≥20 (API cap) at every top candidate, so those are NOT coverage holes and the Foursquare counts are trustworthy there. Next: subtract the Google-found padel venues from the padel opportunity map (feeds GTM-75); run the stratified premium validation before publishing any site list.

### O3 — Where does each neighborhood sit on its development maturity curve today? · *descriptive*
- **Status:** in-progress
- **Prediction:** —
- **Answered by:** `Neighborhood maturity-stage classifier` · `Assemble the multi-decade neighborhood trajectory panel`
- **Fails if:** n/a — descriptive. But the stage must be defined by **level + rate + acceleration** (1st and 2nd derivative), or it collapses into a static wealth map that just re-labels rich = mature.
- **Current answer:** First cut, 2026-09-02. A momentum maturity index (0.45·real income + 0.55·college, fixed anchors, 2013→2023) places all 145 3-borough NTAs; the frontier reads East New York / Ridgewood / Bed-Stuy East (emerging) → Bushwick (just arrived) → Williamsburg / UES-UWS / Tribeca (saturated at the $250k cap). This is level+rate only — no acceleration term yet, and a single 2-point momentum, so it is not the full classifier.

### O4 — Where could each neighborhood reach by 2033, and does the projection survive a backtest? · *predictive*
- **Status:** in-progress
- **Prediction:** —
- **Answered by:** `2033 trajectory projection with scenario bands` · `Backtest the projection (fit 2000→2013, predict 2013→2023)` · `Assemble the multi-decade neighborhood trajectory panel`
- **Fails if:** the backtest — fit through 2013, predict 2013→2023 — cannot retrodict the Bushwick / Crown Heights / East New York arc, or fails to beat a naive persistence baseline. Then the 2033 numbers ship only as scenario illustration, not forecast. Hard honesty guardrail: the retail residual is never an input to this projection (that is the rejected D1 thesis); retail is the dependent read.
- **Current answer:** Pre-backtest projection, 2026-09-02: damped-momentum extrapolation projects the arriving-now set (Bed-Stuy East 44→56, Bushwick 49→64) into the premium-boutique tier by 2033; only 3 of 145 cross the top-end/Equinox line (Astoria Central, Fort Greene, UWS-Manhattan Valley). **First backtest (2026-09-02, 5-yr proxy: fit 2013→2018, predict 2023):** the method **beats a naive persistence baseline** — MAE 4.0 vs 5.1, median |err| 2.95 vs 4.09, better on **65%** of the 145 NTAs — with the largest gain exactly where it matters, the **emerging cohort** (MAE 3.4 vs 5.1). It directionally retrodicts the arc (Bushwick 21/35→pred 44 vs actual 49; Williamsburg 49/66→pred 72 vs actual 81). **But it systematically UNDER-predicts (bias −2.7):** real 2013→2023 gentrification outran a damped extrapolation, so the damping is too aggressive and the 2033 arrows are, if anything, **conservative**. **Full 10-yr backtest done overnight 2026-09-02** (multi-decade panel built — ACS 2009 via the B15002→B15003 college crosswalk + 2013/2018/2023, per-vintage tract centroids; `nta_trajectory.json`, 611 rows / 4 years / 155 NTAs). Verdict at the 10-year horizon (fit 2009→2013, predict 2023): the method **largely FAILS as a point forecast.** Damped MAE 8.25 vs naive persistence 9.35 (only ~12% better, beats naive on just 56% of NTAs); severe under-prediction bias −7.75; damping-gain tuning under LOO-CV barely helps (8.17). The neighborhoods that mattered were flat 2009→2013 then surged — Bed-Stuy East 20/23→pred 27 vs actual 44; Ridgewood 23/23→pred 24 vs actual 41; Williamsburg 39/49→pred 62 vs actual 81 — so **momentum does not anticipate ignition at a 10-yr horizon** (the flat-then-surge S-curve defeats it; 2009–13 was also an anomalously flat post-crisis base). Contrast the 5-yr proxy above, which worked because the surge was already visible by 2013–18: **the method's skill decays sharply with horizon.** What survives is **rank order** (corr 0.96) — it sorts neighborhoods by trajectory well. **Rubric verdict: the 2033 numbers ship as ranking + scenario illustration, NOT as a point forecast** — mirroring §0, another confident-looking extrapolation caught by its own backtest. The **acceleration (2nd-derivative) term was tested and REJECTED** (2026-09-02): it carries no systematic signal for the next-period jump (R²≈0.03, wrong-signed/negative coefficient, corr≈−0.08) and adding it *worsens* forecast MAE (4.0→5.3→7.5, shrinking bias only by overshooting). Even the flat-then-surge winners aren't separable ex-ante by acceleration — plenty of NTAs accelerated then reverted. **Conclusion: ignition is not in the demographic trajectory at all** (not level, slope, or acceleration); it's driven by exogenous shocks (rezonings, adjacency spillover, macro cycles) the trajectory doesn't encode — so the decennial-2000 pull for a strict as-of-2013 test is not worth it. **O4 is settled: the 2033 numbers are ranking + scenario, never a point forecast.** Remaining (unlikely to overturn): logistic/Markov forms, a placebo/pre-trend pass.

### O5 — Where does the next neighborhood ignite — and is that predictable? · *explanatory / predictive*
- **Status:** in-progress
- **Prediction:** —
- **Answered by:** `Frontier-diffusion map: where the edge moved, where it goes next`
- **Fails if:** neither adjacency to an already-risen NTA nor a committed exogenous catalyst predicts which neighborhoods rise next.
- **Current answer:** 2026-09-02. Reframed after O4: since ignition is **not** in a neighborhood's own trajectory (level/slope/acceleration all fail the backtest, D25), the predictive signal must be **exogenous**. Built `src/loci/model/ignition.py` + `loci ignition` (Axis 4b): a hand-curated **catalyst layer** (17 real committed/planned projects — SAS Phase 2, Interborough Express, DCP neighborhood rezonings, Willets Point) screened against low-mid maturity + a light urban-density floor. Key finding: a **naive PLUTO development-headroom score fails** (it floats low-density suburbs — Fresh Meadows, Bath Beach); **requiring a real catalyst is the actual suburb-filter**, and the density floor must stay LOW or it wrongly drops the low-rise-but-catalyzed frontiers (East New York) that are the whole point. 42 catalyst-anchored candidates; the committed tier is defensible and converges with the independent trajectory work — **East Harlem N (mat 29, SAS Ph2 Q-train + '17 rezoning)** is the flagship; the Atlantic-Ave-rezoning cluster (Ocean Hill, Crown Heights, Bed-Stuy) and the East New York cluster (2016 rezoning) follow. The screen's "dropped, no catalyst" list (Chinatown-Two Bridges, Harlem-125th, Washington Heights) is honest QA — real urban candidates whose catalysts the curated layer is still MISSING. Catalyst layer expanded to 28 dated projects (forward + historical). **DOB corroboration added** (`loci ignition` NB18-23 column, from 198k geocoded new-building filings): confirms heavy building in East New York (253), Crown Heights (215), Ocean Hill (151), East Harlem (118) — and flags stalled ones (Two Bridges 14). **Two-clock lag finding** (`loci ignition --lag`): catalyst→**construction** ~5–9 yr (permit surge, peak ~6–11 yr); catalyst→**demographic/human-behavior change** 10–20 yr, sustained, and **only if the rezoning is market-rate** — East New York (affordable-dominated, 2016) built the most but gentrified *below* the citywide drift, i.e. densified without tipping (confirms D21). So the construction/land play is this cycle; the appreciation play is a 2030s–40s horizon, conditional on catalyst type. Reports: ignition_lag_findings.md, nb_by_nta_year.json. Remaining: union DOB NOW (`w9ak-ipjd`) to fix the post-2016 undercount; a proper diff-in-diff to move from timing to causation; validate adjacency-diffusion as a distinct channel.

### O6 — Will a new store in a gap hex push both itself and its nearest neighbor below break-even? · *risk / feasibility*
- **Status:** open
- **Prediction:** —
- **Answered by:** — (not yet ticketed; scope decision pending owner + investor-agent review before it enters Axis 1 investability)
- **Fails if:** n/a — risk/feasibility question, not a screen result to validate. The concern: filling a gap hex could cannibalize a neighboring store rather than create net new viable retail.
- **Current answer:** Open, sketch only (2026-09-03). Nearest-store catchment assignment over hexes already exists; missing pieces are a category-specific minimum viable catchment population (candidate sources: County Business Patterns receipts per establishment, or SNAP redemption per store) and a rule — qualify a gap only if the new store's own catchment clears the minimum AND no neighbor drops below it after entry. Belongs in **Axis 1 investability**, not the gap screen itself. Flagged explicitly as a scope-creep risk; needs investor-agent review of the framing before any build. 2026-09-05: the address screen's leads are dominated by the thinnest category (tailor); a supply-floor or viability filter on lead eligibility is now needed for the screen itself, not only for Axis 1 (CHECKPOINT D44).

### O7 — Fair-value rent for a storefront at a given site. · *pricing / feasibility*
- **Status:** open
- **Prediction:** —
- **Answered by:** — (not yet ticketed; scope decision pending owner + investor-agent review before it enters Axis 1 investability)
- **Fails if:** n/a — pricing/feasibility question, not a screen result to validate.
- **Current answer:** Open, sketch only (2026-09-03). Given a site (hex + category), what rent can a new store of that category bear, and how does it compare to asking rent? Sketch: bearable rent = expected revenue × a category-specific sustainable occupancy-cost ratio (retail rule of thumb ~6–10% of sales, restaurants ~8–12%), minus amortized startup cost. Expected revenue comes from O6 (catchment population × per-capita category spend), so O6 is a prerequisite. Fair-value spread = bearable rent − asking rent; positive spread is the opportunity signal. Data candidates: NYC Storefront Registry (DOF, Local Law 157 of 2019 — vacant storefront filings, public), Manhattan Commercial Rent Tax filings (below 96th St only), listing scrapes (LoopNet/StreetEasy commercial; thin and biased). Threats to validity: asking rents are observed mostly on vacant storefronts, which are vacant for a reason (selection bias); occupancy-cost ratios are national rules of thumb, not NYC-calibrated; startup cost varies more by operator than by site. Belongs to **Axis 1 investability** (cross-ref O6). Scope-creep risk flagged: this is a pricing model, not a gap screen — keep it a downstream gate on already-flagged sites, never a citywide ranking. Investor-agent review of framing required before any build.

### O8 — Buy versus build: acquire an existing business or open a new one, and where is the inflection point? · *strategy / feasibility*
- **Status:** open
- **Prediction:** —
- **Answered by:** — (not yet ticketed; scope decision pending investor-agent review before it enters Axis 1 investability)
- **Fails if:** n/a — strategy/feasibility question, not a screen result to validate.
- **Current answer:** Open, sketch only (2026-09-03). For a category and area, is it cheaper (risk-adjusted) to acquire an existing store than to open one, and what saturation level flips the answer? Sketch: acquisition cost ≈ multiple of seller's discretionary earnings (small retail typically 2–3×; category-dependent — bodega goodwill low, restaurant higher) vs. build cost = startup cost + ramp-period losses + failure risk. Inflection = the catchment-saturation level at which the acquisition premium falls below the ramp-plus-risk cost. Key structural link to the core screen: in a true gap hex there is nothing to acquire by definition, so buy-vs-build applies to the NON-gap, saturated areas — the gap screen says "build here," O8 says "elsewhere, buy instead." Data candidates: BizBuySell / BizQuest listings (asking price, revenue, cash flow — public but self-reported), SBA 7(a) loan data (public; flags business-acquisition loans by NAICS and location), the O6 catchment model. Threats: listing prices are asks, not closes; survivorship (only businesses worth selling get listed); ramp curves are category folklore. Depends on O6 and O7 (cross-ref O6, Axis 1). Scope-creep risk flagged: this is a second product (an acquisition screen), not a refinement of the first. Investor-agent review required before any build.

### O9 — Should the three parallel uncommitted streams (comps, conveniences, spend.yaml) be kept, parked, or deleted? · *governance / scope*
- **Status:** answered
- **Prediction:** —
- **Answered by:** owner decision with investor-agent review (as O6–O8 already require)
- **Fails if:** n/a — governance. Found 2026-09-05: model/comps.py + benchmarks.yaml + tests/test_comps.py (O7/O8 comps; zero real listings, listing sites 403, one failing test); model/conveniences.py + conveniences.yaml + sources/cities/nyc/addresses.py (address-level owner-set-norm check citing a nonexistent CHECKPOINT decision); spend.yaml (fair-value parameters for an `analysis.site_fairvalue` model that does not exist in this tree). All build toward O6–O8 without the review those entries require. Until decided: no further work, no tickets.
- **Current answer:** Owner directed 2026-09-05 that all streams be picked back up. Conveniences: wired as `loci conveniences` with tests. Spend: grounded in real BLS tables (CHECKPOINT Session 10) but no model reads it and the cited fair-value spec/model do not exist. Comps: 59 BizQuest NYC listings via owner-approved human-paced browser session (commit fe59eb2); fill rates thin with cash_flow_sde ~14% (hidden behind sign-in on most listings), and only restaurant meets benchmarks.yaml's ≥8-row bar for fair-value modeling; scripted fetches remain 403.
- **Demand annotation (2026-09-08, D49):** contrarian review found the eight `assumed` rows contradicted spend.yaml's BLS CEX elasticities and the 0.80 cutoff used the wrong denominator; both fixed, annotation now continuous and MOE-gated. See CHECKPOINT D49. Open follow-ups: GTM-110 port; renderers must not truncate `demand_caveat_text`; `hex_gaps_reach` had drifted from reach.yaml and was rebuilt (1,966 hexes / 5,053 pairs); checked 2026-09-08 — no published number cited the stale table (all citations are dated log entries D34/D37; the address screen reads reach_tiers.yaml), so nothing re-tabulated.

### O10 — Within the cities that are trying to become walkable (H-L13), which neighborhoods have the most opportunity? · *predictive screen*
- **Status:** open
- **Prediction:** —
- **Answered by:** `Extract universal interface; run a second city`
- **Fails if:** the screen run on universal sources only (CONTEXT.md §10) produces a gap distribution with no usable spread in the second city, or its top-ranked neighborhoods are the ones with no policy tailwind — in which case "trying to become walkable" added nothing over the plain screen and H-L13's premise is wrong.
- **Current answer:** — (Owner question, 2026-09-09, follow-up to H-L13. Depends on H-L13 producing a ranked city list first. The intent is that the second-city screen is joined to the policy signal: a neighborhood scores highest when it is both under-supplied on daily needs *and* inside the footprint of an adopted walkability program (upzoning, parking-minimum repeal, bike/pedestrian capital), since that is where a present-day gap is about to become an actionable one. This is C3's generalization test with an investment reading attached; it inherits C3's `deferred` risk and the NYC-only-controls threat (PLUTO has no national analogue). Investor-agent review before any build, as O6–O8 require.)

---

## Part B — Homework: things to research before building

Each item names the epic it unblocks. Record the answer inline when found; do not open a
ticket unless the answer turns into work.

Links for every reading live in Notion: **Projects → LOCI → Loci Reading List**
(https://app.notion.com/p/3cf48af1331b8108bfb3d2bd483b45fb).

### Literature

### H-L1 — What did "Consumer City" and "Urban Revival" find about amenities and residential demand?
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Glaeser, Kolko & Saiz 2001; Couture & Handbury 2020. Would T1 replicate or contradict them? What controls did they use?)

### H-L2 — What have Meltzer & Schuetz, and Meltzer & Capperis, already established about NYC neighbourhood retail?
- **Status:** answered
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** Meltzer & Schuetz 2012 (EDQ 26(1):73–94; full text https://www.rachelmeltzer.com/uploads/1/4/5/3/14532900/appendix_23_retail_edq.pdf). Unit: 208 NYC ZIPs, ZBP 1998–2007 averaged over ten years to suppress year noise, Census 2000 income/race, PLUTO/DoF for corridors and transit, CUF 2009 chain list. Findings that bind Loci: (a) NECESSITY vs DISCRETIONARY split — low-income ZIPs (<80% of citywide mean HH income) have MORE grocery establishments per acre (0.051 vs 0.036) but smaller ones (7.5 vs 14.6 emp/est), and small drugstore gaps; food service, gyms (0.29 vs 1.04/ZIP), and upscale chains concentrate in higher-income ZIPs. So a missing restaurant/cafe/gym in a low-income hex is plausibly demand-following, a missing grocery/pharmacy is a real gap. Implemented 2026-09-05 as `demand.yaml` + `demand_caveat` annotation in gaps.py (annotates, never filters). (b) Transit and retail space per building do NOT explain the income disparity — low-income ZIPs have more of both — so subway access is not a valid "expected supply" covariate for the screen. (c) Density, size, diversity (Herfindahl over NAICS subsectors) and corridor proximity are weakly inter-correlated; count-based reach alone is one-dimensional (see D9). (d) Race predicts retail net of income in opposite directions: predominantly Black ZIPs have less retail and less corridor proximity than White despite more transit; predominantly Hispanic ZIPs have more diverse retail and closer access despite less transit (see X6). (e) Method bits to reuse: 80%-of-mean income cutoff; exclude-Manhattan / exclude-tiny-units / alternate-cutoff robustness battery; symmetric growth rate g=(x1−x0)/(0.5(x1+x0)); within-stratum difference-in-differences for growth comparisons. A residual thesis is NOT what they test; they are explicitly descriptive.

### H-L3 — What thresholds and saturation forms do food-desert and 15-minute-city measurements use?
- **Status:** open
- **Unblocks:** E2 · Access Engine
- **Current answer:** (USDA Food Access Research Atlas; Moreno et al. on the 15-minute city. Precedent for k_c and the 800 m headline. Full research: docs/reach_sources.md.)

### H-L4 — What does Walk Score's methodology do for distance decay and category weights?
- **Status:** open
- **Unblocks:** E2 · Access Engine
- **Current answer:** (Borrow the decay shape if defensible; avoid inheriting its category weights uncritically. Full research: docs/reach_sources.md.)

### H-L5 — Spatial error or spatial lag on gridded urban data: which is the right default?
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Anselin's LM / robust LM tests; LeSage & Pace on when lag is theoretically motivated. Decide before W3 so the choice is not made by the result.)

### H-L6 — What does Zukin et al. (2009) say about which retail categories signal gentrification, and does that contaminate the gap screen?
- **Status:** open
- **Unblocks:** E7 · Maturity and 2033 Projection
- **Current answer:** [was: Axis 2 (Rising) · D9] — (Zukin, Trujillo, Frase, Jackson, Recuber & Walker, "New Retail Capital and Neighborhood Change: Boutiques and Gentrification in NYC", City & Community 8:47–64. Harlem/Williamsburg: gentrification arrives as independent boutique retail. Question for Loci: a cafe "gap" closing may be a trajectory signal, not a need being met — should discretionary-category arrivals feed rising.py rather than gaps?)

### H-L7 — What covariates does Schuetz, Kolko & Meltzer (2010, 58 metros) find for retail density, and can they make the screen city-agnostic?
- **Status:** open
- **Unblocks:** E8 · Second-City Feasibility
- **Current answer:** [was: D7] — (SSRN 1681734. Density + with population density, − with distance to CBD and with owner-occupancy share; establishment size + with income for all types. Loci stores renter_share already; test it as a density-class covariate before ACS vehicle ownership.) 2026-09-08 (D54): tested within MN+BK — replicates citywide, dissolves under a density control (partials 0.02–0.16, sign flips in Manhattan); renter_share is a density proxy, not a mode variable. Closed for the D7 purpose; keep as a demand covariate.

### H-L8 — Does Waldfogel (2008) "median consumer" logic mean "comparable areas" must be defined on composition, not income alone?
- **Status:** open
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** [was: X6 · D8] — (J. Urban Econ. 63:567–582. Local private goods follow the locally dominant group's preferences. If true, a citywide reach per category is mis-specified for categories whose demand is composition-driven.)

### H-L9 — What does Zenk et al. (2005) establish about supermarket access by race net of poverty, and which access metric did they use?
- **Status:** open
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** [was: X6 · M-tier access metric choice] — (Detroit tracts, GIS distance to nearest supermarket; segregation, not poverty alone, drives access. Precedent for a distance-based rather than count-based "missing".)

### H-L10 — Does Powell et al. (2007) national ZIP-level food-store availability by race/SES replicate Meltzer & Schuetz's NYC pattern, and is its establishment-count method close enough to Loci's to borrow?
- **Status:** open
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** [was: X6] — (Preventive Medicine 44:189–195. National ZIP counts by store type; count-based, so a useful contrast with Zenk's distance-based access.)

### H-L11 — Do Haltiwanger, Jarmin & Krizan (2010) give a usable displacement/complementarity estimate for the minimum-viable-catchment check?
- **Status:** open
- **Unblocks:** E5 · Deferred
- **Current answer:** [was: O6] — (J. Urban Econ. 67:116–134, big-box entry vs mom-and-pop exit.)

### H-L12 — Chapple & Jacobus (2009): where does gap-filling retail actually succeed, and does that argue for an income floor in Axis 1?
- **Status:** open
- **Unblocks:** E5 · Deferred
- **Current answer:** [was: Axis 1 (invest.py)] — (Bay Area; revitalization gains concentrate in middle-income, not poorest, neighborhoods.)

### H-L13 — Which cities are actively trying to become walkable, and which of them could be Loci's second city?
- **Status:** open
- **Unblocks:** E8 · Second-City Feasibility
- **Current answer:** — (Owner question, 2026-09-09. Candidate signals: adopted 15-minute-city or complete-neighborhoods plans (Paris, Melbourne, Portland), parking-minimum repeal and upzoning (Minneapolis, Austin, Buffalo), pedestrianisation and bike-network capital programs, walkability targets in a comprehensive plan. A city *trying* to become walkable is the interesting second-city case: its retail gaps are the ones policy is about to make actionable, whereas an already-walkable city just replicates NYC. Output should be a short ranked list with the policy citation per city and whether the universal sources in CONTEXT.md §10 cover it.)

### H-L14 — Do retail agglomeration effects concentrate around new residential construction, and how long is the lag?
- **Status:** open
- **Unblocks:** T7 · Density-shock MVA
- **Current answer:** (Li 2022 JEG, within ~500 ft, 1–3 yr lag. Precedent for the matched-event-study design and effect sizes; review which categories showed demand response vs supply-driven agglomeration.)

### H-L15 — When new housing enters a low-income neighbourhood, what types of retail follow or decline?
- **Status:** open
- **Unblocks:** T7 · Density-shock MVA
- **Current answer:** (Asquith/Mast/Reed 2023 REStat. Amenity effects exist but are too small to offset rent increases; separates which categories are demand-elastic vs gentrification-driven.)

### H-L16 — Do entry and exit rates in retail rise together in gentrifying tracts, and what does that tell us about supply-vs-demand mechanisms?
- **Status:** open
- **Unblocks:** T7 · Density-shock MVA · O5 · Frontier Diffusion
- **Current answer:** (Glaeser/Luca/Moszkowski 2023 JEG. Gentrifying tracts show faster entry AND exit; reframes the null from "supply shifts" to "category churn without net growth." Key for understanding survivor truncation bias in T7.)

### H-L17 — What do NYC Comptroller vacancy reports and HR&A 2024 say about post-COVID retail churn vs net growth?
- **Status:** open
- **Unblocks:** T7 · Density-shock MVA
- **Current answer:** (NYC Comptroller 2024, Comptroller 2019 baseline, HR&A 2024 "The Retail Reckoning". Quantifies churn patterns and structural change; benchmarks expectations for entry rates around new residential supply.)

### H-L18 — Should address demographics be catchment-weighted (aggregated over the address's walk-shed) rather than the lot's own tract?
- **Status:** open
- **Unblocks:** E7 · Market Reach
- **Current answer:** — (Today (D60) each address carries its tract's ACS values 1:1. A retail thesis about who is within reach of a gap wants the demographics of the walk-shed, which is far larger than a tract in Manhattan and smaller than one in eastern Queens. Unblocks: investor-grade catchment reads on gap clusters. Fails if: tract-direct and catchment-weighted rank the same top-50 clusters, in which case the extra modelling buys nothing.)

### Data quirks

### H-D1 — Does LODES block-level noise infusion matter after hex aggregation?
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (LODES8 tech doc, noise model section.)

### H-D2 — Which of the 15 categories map cleanly onto Overture's taxonomy, and which are lossy?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Read the Overture categories file before writing the adapter. Expect laundromat, nail and tailor to be the lossy ones; record mapping confidence.)
- **Touched 2026-09-05 (D42, `src/loci/categories.yaml`):** the current per-slug Overture `categories.primary` lists are now recorded in one place (`sources.overture` per slug) alongside each slug's NAICS 2022 anchor, but lossiness/confidence per mapping is still not scored — this question stays open.

### H-D3 — Does Google Nearby Search's 60-result cap bias enumeration in dense hexes?
- **Status:** open
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** — (20 results per page, 3 pages max, radius semantics. If dense hexes saturate, the sample design needs smaller radii or per-type queries — decide before spending calls.)

### H-D4 — How many NYC ZIPs have ZORI coverage in both 2013 and 2023?
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Count before committing rent as an outcome. CONTEXT.md already labels it the weakest of the four.)

### H-D5 — How does DOHMH represent closed establishments within the 3-year rolling window?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (What is the effective "active" definition? A closed restaurant still in the window inflates the anchor.) Finding 2026-09-05 (CHECKPOINT D36): the adapter dedupes by CAMIS but never drops closed establishments, so successive tenants at one address survive as separate canonical points — the source of the 13–14% exact-coordinate same-type share in restaurant/nails_beauty/clinic. Fix: active-establishment filter before dedup.

### H-D6 — ACS tract vintages: 2009–13 is on 2010 tracts, 2019–23 on 2020 tracts. Crosswalk, or interpolate per vintage?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (LODES needs no crosswalk; ACS does — unless dasymetric interpolation onto hexes is run separately per vintage, which sidesteps it. Decide.)

### H-D7 — Do the MTA entrances and hourly ridership datasets cover the Staten Island Railway?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (If not, Staten Island's transit control is systematically understated, which interacts with X5.)

### H-D8 — Which DCWP license categories are in scope beyond laundries?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Freshness is already a ticket; this is about coverage of the 15 categories.)

### H-D9 — Which NYS Liquor Authority license descriptions denote a bar?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (The active-licenses file `9s3h-dpkz` has no "bar" type. The adapter currently emits `bar` for Food & Beverage Business, Club, Cabaret and Bottle Club, skips Restaurant (DOHMH anchors it) and skips "Additional Bar" riders (they attach to an existing premises). Confirm against the SLA licence-class guide whether Food & Beverage Business is the tavern class, and whether a material share of bars hold a Restaurant licence.)

### H-D10 — Is a Foursquare "Medical Center" a neighbourhood clinic, and is a Foursquare "Gym and Studio" a gym?
- **Status:** open
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** — (Medical Center is 6,971 of the 10,579 Foursquare clinic rows before the freshness gate and looks like a catch-all; Gym and Studio is a level-2 label used as a leaf on ~4k rows. Both are exactly what the Google sample on clinic/fitness should test — run `loci validate --categories clinic,fitness` and compare undercount by source.)

### H-D11 — Are same-category cross-source pairs within 25 m the same business under two names?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (71k restaurant pairs sit within 25 m across sources with non-matching names, e.g. DOHMH "Bronx Burger Company" vs Overture "Peter Dorcas Ventures Inc". Some are food halls and shared addresses; some are legal-name vs trade-name for one establishment. Sample 50 by hand; if most are the same business, dedup needs an address-level merge for anchor sources, and every count-based result is inflated.) 2026-09-05: of 24,908 restaurant pairs within 15 m, 0.09% share a normalized name; cross-source naming is not the dominant duplication driver (see H-D5, CHECKPOINT D36).

### Methods & stats

### H-M1 — Does `tobler` carry or drop ACS margins of error through dasymetric interpolation?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (If dropped, propagate by simulation: draw tract values from their MOE, interpolate, repeat. M5 depends on this.)

### H-M2 — How should k_c be calibrated from observed count distributions rather than by judgment?
- **Status:** open
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (CONTEXT.md §9 #2. A defensible procedure, not a number.)

### H-M3 — What does "prior decade" mean per outcome when t0 outcomes are ACS 5-year?
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (ACS 5-year begins 2005–09. A "2003" population needs Census 2000 / 2010 on 2010 geography. Define the pre-trend window per outcome before W3, or T2 is undefined.)

### H-M4 — Memory, runtime and served-node weighting for multi-source Dijkstra on the NYC walk graph
- **Status:** open
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (`nx.multi_source_dijkstra_path_length` with cutoff; how to compute population-weighted served-node shares per hex.)

### H-M5 — How sensitive is the DNCI ranking to ε in the geometric mean?
- **Status:** open
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (ε = 0.01 is stated. Sweep 0.001–0.05 and confirm the bottom decile is stable.)

### H-M6 — `pysal.spreg` GM vs ML estimation with borough fixed effects at ~7,400 observations
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Runtime, and how to interpret the spatial parameter alongside borough FE.)

### Tooling

### H-T1 — PMTiles pipeline: tippecanoe → pmtiles → static hosting → MapLibre
- **Status:** open
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** — (Confirm the `pmtiles://` protocol handler and a zero-server hosting path.)

### H-T2 — OSMnx graph for NYC plus the NJ / Westchester / Nassau fringe
- **Status:** open
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (Download size, simplification, `network_type='walk'` filter. Threat §7.7 requires the fringe.)

### H-T3 — DuckDB `h3` extension: polyfill functions and behaviour on the NYC boundary
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Which polyfill function, and does it behave at res 8/9/10 on a multipolygon with holes.)

### H-T4 — Moving geometry between DuckDB (no SRID) and geopandas / tobler without CRS confusion
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Convention is EPSG:4326 in the database; metric work reprojects explicitly. Where does the CRS get re-attached on the way out?)
