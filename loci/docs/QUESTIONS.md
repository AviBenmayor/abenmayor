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
- **Answered by:** `Design stratified coverage validation sample` · `Run Google Places ground-truth enumeration` · `DOHMH-anchored undercount calibration` · `Coverage-bias chart` · `USDA SNAP retailer adapter (ANCHOR for grocery/convenience)`
- **Fails if:** the undercount rate by income decile is materially higher in hexes flagged as underserved than in their well-served peers.
- **Current answer:** Partly, and badly, for at least one category. 2026-09-02: adding the SNAP near-census cut bodega/convenience gap hexes from **166 to 16** — 90% of that gap type was an OSM/Overture coverage hole, not a missing business. Hardware, fitness and clinic gaps (the current top three) still rest on OSM/Overture only; the Google sample (`loci validate`) is aimed at those next. **2026-09-03 (CHECKPOINT D29/D30):** the raw Google survival rates (hardware 58%, fitness 29%, clinic 0%) turned out to measure the Google type map, not coverage — split each result into geometry-artifact vs true coverage hole. Corrected true-hole rates: hardware 5% [2–12] (not disproven — Google's type is an upper bound), fitness 21% [10–37] (real hole, needs an anchor, M7), clinic 0% [0–15] but unfalsifiable by construction (loci excludes doctor's offices, Google doesn't) — clinic dropped from headline claims pending a re-anchor to licensed urgent care (D30).

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
- **Current answer:** Known so far (2026-09-03, CHECKPOINT D29): hardware narrower, fitness wider, clinic maximally wider (`doctor` includes every solo physician practice, which loci's `foursquare_places.py` deliberately excludes). Not yet audited category-by-category for the other 12 categories.

### M7 — What anchor source would establish a true fitness coverage hole?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Fitness anchor source for the true coverage hole`
- **Fails if:** n/a — measurement/sourcing question. Needed because D29 found a real ~21% [10–37] true-coverage-hole rate for fitness after removing geometry artifacts, and OSM/Overture/Foursquare are the only sources feeding that category today — none is a near-census the way DOHMH is for food or SNAP is for grocery.
- **Current answer:** Open. Candidates to evaluate: NYS business registry, DOHMH (if it licenses fitness facilities), state gym/health-club licensing. None yet verified for NYC coverage or access.

### M8 — Should the validator compare against network distance rather than a straight-line radius?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Validator: network distance or circuity correction`
- **Fails if:** n/a — measurement. D29's GEOMETRY-artifact category exists precisely because the validator's straight-line radius and the screen's network-distance threshold disagree; a circuity correction or a direct network-distance comparison would remove the need to split results after the fact.
- **Current answer:** Open. Candidate approaches: reuse `analysis.hex_poi_distance` (already network-based) instead of a straight-line radius at validation time, or apply a circuity correction (~1.25–1.3 in NYC, so an 800m network threshold ≈ 620–640m straight-line).

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
- **Answered by:** `DNCI: weighted geometric mean + unit tests` · `Per-category radar small multiples`
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
- **Status:** open
- **Prediction:** —
- **Answered by:** `Per-category walk thresholds from revealed spacing`
- **Fails if:** n/a — descriptive/method question. Threat to validity: revealed spacing reflects historical supply, not demand — a systematically under-supplied category will look like it "naturally" spaces wide, so a threshold set purely from its own distribution can launder an existing coverage gap into a permissive threshold. Candidate rule: set each category's threshold from its 75th percentile of hex-to-nearest distance among populated hexes.
- **Current answer:** Open. Motivating case: D31 (Manhattan 5-min result flips the category mix — a single citywide walk window is not defensible).

### D7 — Should thresholds vary by density class or transit/car-dependence, not just by category?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Density-class / mode-dependent thresholds`
- **Fails if:** n/a — descriptive/method question. Lower Manhattan and car-dependent outer-borough areas should not share one walk window. Cheap proxy: scale the threshold by residential density class (no new data needed). Honest version: ACS vehicle ownership per tract (blocked on CENSUS_API_KEY). Note the interaction with D6: threshold(category, density_class) is one parameterization, not two independent sweeps — keep it small to avoid overfitting a matrix.
- **Current answer:** Open. Blocked on `CENSUS_API_KEY` for the honest (vehicle-ownership) version; the density-class proxy needs no new data and can proceed first.

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
- **Current answer:** Open, sketch only (2026-09-03). Nearest-store catchment assignment over hexes already exists; missing pieces are a category-specific minimum viable catchment population (candidate sources: County Business Patterns receipts per establishment, or SNAP redemption per store) and a rule — qualify a gap only if the new store's own catchment clears the minimum AND no neighbor drops below it after entry. Belongs in **Axis 1 investability**, not the gap screen itself. Flagged explicitly as a scope-creep risk; needs investor-agent review of the framing before any build.

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
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Unit of analysis, controls, findings on retail density vs. income and on churn. Is a residual thesis consistent with their results?)

### H-L3 — What thresholds and saturation forms do food-desert and 15-minute-city measurements use?
- **Status:** open
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (USDA Food Access Research Atlas; Moreno et al. on the 15-minute city. Precedent for k_c and the 800 m headline.)

### H-L4 — What does Walk Score's methodology do for distance decay and category weights?
- **Status:** open
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (Borrow the decay shape if defensible; avoid inheriting its category weights uncritically.)

### H-L5 — Spatial error or spatial lag on gridded urban data: which is the right default?
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Anselin's LM / robust LM tests; LeSage & Pace on when lag is theoretically motivated. Decide before W3 so the choice is not made by the result.)

### Data quirks

### H-D1 — Does LODES block-level noise infusion matter after hex aggregation?
- **Status:** open
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (LODES8 tech doc, noise model section.)

### H-D2 — Which of the 15 categories map cleanly onto Overture's taxonomy, and which are lossy?
- **Status:** open
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Read the Overture categories file before writing the adapter. Expect laundromat, nail and tailor to be the lossy ones; record mapping confidence.)

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
- **Current answer:** — (What is the effective "active" definition? A closed restaurant still in the window inflates the anchor.)

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
- **Current answer:** — (71k restaurant pairs sit within 25 m across sources with non-matching names, e.g. DOHMH "Bronx Burger Company" vs Overture "Peter Dorcas Ventures Inc". Some are food halls and shared addresses; some are legal-name vs trade-name for one establishment. Sample 50 by hand; if most are the same business, dedup needs an address-level merge for anchor sources, and every count-based result is inflated.)

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
