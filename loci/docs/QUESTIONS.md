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
- **Status:** open
- **Prediction:** P3
- **Answered by:** `Design stratified coverage validation sample` · `Run Google Places ground-truth enumeration` · `DOHMH-anchored undercount calibration` · `Coverage-bias chart`
- **Fails if:** the undercount rate by income decile is materially higher in hexes flagged as underserved than in their well-served peers.
- **Current answer:** —

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
- **Status:** open
- **Prediction:** —
- **Answered by:** `Cross-source POI dedup / entity resolution`
- **Fails if:** disagreement is concentrated by geography or by category (laundromats, salons) rather than spread randomly — then source choice is itself a bias.
- **Current answer:** —

### M5 — Do ACS margins of error leave hex-level income and population usable as controls?
- **Status:** open
- **Prediction:** —
- **Answered by:** `ACS ingest + dasymetric interpolation onto hexes`
- **Fails if:** propagated MOEs on hex median income are wide enough that the income control cannot distinguish neighbouring hexes.
- **Current answer:** —

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
- **Status:** open
- **Prediction:** —
- **Answered by:** `Run 5/10/15-minute threshold sweep` · `Tier-weight sensitivity analysis`
- **Fails if:** the bottom decile of hexes reshuffles substantially between 5/10/15 minutes or across plausible reweightings — then "underserved" is an artifact of parameter choice.
- **Current answer:** —

### D4 — Where do transit-rich and daily-needs-poor hexes overlap?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Bivariate transit × residual map` · `MTA transit access control`
- **Fails if:** n/a — descriptive. This is the thesis stated as one image.
- **Current answer:** —

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

---

## Part B — Homework: things to research before building

Each item names the epic it unblocks. Record the answer inline when found; do not open a
ticket unless the answer turns into work.

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
