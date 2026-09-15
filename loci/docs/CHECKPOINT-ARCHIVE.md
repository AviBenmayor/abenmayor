# CHECKPOINT ARCHIVE — Loci

**Append-only. Not read at session start.**

This file holds the **full, unchanged original text** of decision-log entries that were collapsed
out of `docs/CHECKPOINT.md` on 2026-09-15, so that CHECKPOINT.md stays short enough to be read in
full at the start of every session. Nothing here was rewritten, summarised or deleted — the entries
below are byte-for-byte what CHECKPOINT.md held, in their original order, under their original
D-id headings.

**Rules for this file**

- **Append-only.** Never edit or delete an entry. When a later decision reverses one of these,
  record that in CHECKPOINT.md's decision log; do not touch the text here.
- **The session-start briefing agent does NOT read this file.** `docs/CHECKPOINT.md` remains the
  single file read at the start of every session. Open this one on demand: when a stub in
  CHECKPOINT.md points here, when a cross-reference from `docs/QUESTIONS.md`, Linear or
  `src/loci/tickets.py` resolves to one of these D-ids, or when an old decision is about to be
  relitigated.
- **Every collapsed entry left a stub behind** in CHECKPOINT.md of the form
  `**Dnn — <summary>** *(date)* → archive`, so the D-id still resolves there and
  `loci check-tickets` still sees it.
- **Collapse rule applied:** dated on or before 2026-09-11 (more than five sessions back), five
  lines or longer, and not stating a rule, threshold or scope constraint the current phase must
  still obey. Entries dated 2026-09-13 or later were not touched.

---

**D1 — The thesis is a residual, not a raw count.** *(2026-09-01)*
Raw counts are endogenous: retail follows rooftops, so ranking the bottom of a count
distribution just reproduces a poverty map. The finding would be "dense rich places have
more shops" — true, known, worthless, and it inverts the causal arrow. We model DNCI on
density/income/transit/zoning and treat the **residual** as the signal.
**Do not let the project drift back to counting shops.**

**D2 — LODES WAC is the panel backbone.** *(2026-09-01)*
The obvious longitudinal sources fail: NYS DOS salon licenses are active-only (survivorship
bias by construction); Overture/Foursquare have no history before ~2023. LODES WAC gives
census-block job counts by 4-digit NAICS, annually 2002–2023, free. This is what made "full
annual panel" compatible with a 4-week timeline — the expensive part was never LODES, it
was license-date reconstruction (deferred to E5).

**D3 — Commercial zoning capacity is a required control.** *(2026-09-01)*
Without PLUTO `CommFAR`/`ZoneDist` in the supply model, the underserved tail fills with
park edges, industrial zones and cemetery blocks — places with no retail because retail
isn't legal there. Hard audit gate on this in E3.

**D4 — Access is multi-source Dijkstra, not per-hex isochrones.** *(2026-09-01)*
One Dijkstra per category seeded from all its POIs at once: 15 traversals instead of
~7,400 isochrones. Also: H3 res 9 over NYC is **~7,400 hexes**, not the ~15k estimated
early in the interview.

**D5 — Docker CLI linked at user level.** *(2026-09-01)*
Symlinked `docker` + credential helpers into `/opt/homebrew/bin`, compose/buildx into
`~/.docker/cli-plugins`. Avoids the sudo prompt. **Consequence:** if Docker Desktop ever
self-repairs its `/usr/local/bin` links there will be two `docker` on PATH — check
`which -a docker` if behavior gets strange. Now moot for Loci (D9) but the machine is
configured this way.

**D8 — h3-pg is not a dependency.** *(2026-09-01, superseded by D9)*
Was: h3-pg isn't in the stock PostGIS image, so H3 indexing runs in Python. Now moot —
DuckDB's community `h3` extension provides it natively. The `CHAR(15)`/VARCHAR cell-id
design survived the migration unchanged.

**D10 — Three root directories, named by audience.** *(2026-09-01)*
First attempt used `conf/ docs/ src/ db/ ops/ data/` — six directories where `db` vs `data`
differed by one letter and meant unrelated things, `conf/` held a single file, and `ops/`
was a junk drawer. Collapsed to three, each named for *who or what consumes it*:
`docs/` (humans) · `src/` (the code) · `data/` (machine-generated, gitignored).
The registry and SQL moved **into the package** as package data, and the loose scripts
became CLI subcommands — `loci check-sources`, `loci gen-tickets` — which is better than
`python ops/whatever.py` regardless of the folder count.

**D11 — Linear label taxonomy collapsed 32 → 14.** *(2026-09-01)*
The raw ticket tags produced 32 distinct labels, which is noise for a single project.
Collapsed via `LABEL_MAP` in `src/loci/tickets.py` so the mapping stays generated rather
than hand-patched. `critical` and `rigor` are deliberately kept distinct: `critical` is the
P3 coverage-bias chain that can invalidate the finding; `rigor` is the checks that decide
whether a result is defensible. Issues live on team **Go To Market**, matching the team the
project was already attached to.

**D12 — LODES panel proceeds without a crosswalk, with a stated caveat.** *(2026-09-01)*
GTM-12 resolved: LODES8 enumerates every year 2002–2023 on **2020 census blocks** (tech doc
§Geography Vintage, corroborated by 5,328/5,334 tract overlap between the 2002 and 2023 NY
files). No crosswalk, Week-3 estimate stands.

But historical years were **retro-allocated**, not observed: a job in a splitting 2010 block
is assigned to a child at random with probability proportional to **area**. That assumption
is poor in NYC, and the resulting error is *correlated with development activity* — which is
the outcome variable. Filed as GTM-63 and CONTEXT.md §7.4(b). Do not treat pre-2020 panel
values as observed data until GTM-63 sizes the leakage.

**D13 — DCWP contributes nothing to the daily-needs bundle.** *(2026-09-01)*
DCWP is current (rowsUpdatedAt 2026-08-20, not stale). But its consumer "Laundries" category
has ZERO active licenses — every active laundry license is *Industrial Laundry* (B2B linen
suppliers), and it licenses no pharmacies. Industrial laundry is excluded from the mapping so
it can't fake laundromat access in industrial zones. Net: DCWP emits 0 bundle POIs.
**Laundromats come from OSM/Overture.** DCWP is retained only for the deferred E5 license panel.

**D13 — `docs/QUESTIONS.md` is a sanctioned fourth document.** *(2026-09-01)*
The trio had no home for *research questions*: CONTEXT.md §1.4 holds predictions and §9
holds decisions, but neither says what the project is trying to find out, at what level of
rigor, or which ticket answers it. QUESTIONS.md changes faster than the charter (answers
land per session) and slower than the checkpoint (questions rarely change), so it earns its
own lifetime. Two lists, kept separate: what the project answers, and the owner's pre-build
homework. Homework stays out of Linear — most items are 30-minute checks and ticketing them
is overhead. Cross-references are machine-checked (`loci check-questions`) per the standard
that any human table mirroring a machine file gets a drift check.

**Stopping rule recorded there: none.** The map ships whatever P1–P3 return. With one
condition: if the coverage-bias test (M1 / P3) fails, the descriptive map is contaminated in
the same hexes as the predictive claim, and ships restricted to the food tier and validated
strata. Do not let "the map stands alone" be read as immunity from P3.

A Measurement tier was added ahead of Descriptive because measurement questions gate every
other tier and fit none of them.

**D14 — Grid boundary is the 2020 NTA file; cells labelled by max areal overlap.** *(2026-09-01)*
The first boundary tried (an ArcGIS "borough boundary") was a coarse cartoon — 47 points per
borough, truncated extent — and polyfilled to only 20 cells. Replaced with the detailed NYC
2020 NTA boundary (782.6 km², ~146 pts/polygon), which also supplies `nta_code` for free.
Cells are labelled by the NTA they overlap MOST, not by centroid, so coastal cells whose
centroid sits in water still get a borough. Result: 8,321 cells (7,414 land + coastal slivers
carried with land_fraction). ALWAYS sanity-check a boundary's point density and extent before
building on it.

**D16 — SNAP + SLA are the coverage anchors for the bottom-bias tiers.** *(2026-09-02)*
Overture/OSM undercount food retail and bars in exactly the low-income outer-borough areas
the screen flags — the #1 threat. USDA SNAP (near-census of stores that accept SNAP:
8,975 grocery/convenience POIs) and NYS SLA active liquor licenses (3,199 bars) are
independent, oppositely-biased anchors. After ingest + dedup + re-run, building-level
prevalence rose materially: convenience 76%→94%, bar 73%→87%, grocery 91%→96%; convenience,
bar, and clinic are now **expected** categories on their own merit rather than forced. This
shrinks false "gaps" that were really data holes. SLA `--limit` caps *before* the NYC/bar
filter, so smoke-tests must run unlimited.

**D17 — Manhattan has no validated gaps; the opportunity is Brooklyn/Queens only.** *(2026-09-02)*
Full 15-category Manhattan sweep on refreshed data: only 111 of 579,412 residential
buildings flag any conspicuous gap, and Google validation confirms **every** flagged cluster
has that business within an 800m walk. Manhattan is saturated. Stop looking there; the screen
is an outer-borough instrument. (3-borough residential base is 579,412, not the earlier stale
767k which was a 5-borough run.)

**D18 — "Best investment" = a feasibility-gated Investability Index, not homes-affected.** *(2026-09-02)*
Raw reach misranks: the biggest-home clusters (Bay Terrace, Whitestone, Glen Oaks, Canarsie)
have **zero commercial-zoned frontage** — you can't legally open a storefront, so the "gap" is
a zoning artifact (the D3 threat, now enforced in code). `src/loci/model/invest.py` gates each
validated gap on feasibility (PLUTO CommFAR>0 to build OR RetailArea>0 to lease) AND a
category minimum-viable catchment (ECON table — a pharmacy/gym needs ~2000 homes, a bodega
~300), then scores survivors on catchment / competition-ring / demand-driver / spending /
transit. 10 of 23 validated gaps pass. Category-min thresholds are judgment calls, tunable.

**D19 — Trajectory ("Rising") is a SECOND axis the user added, kept separate from D1.** *(2026-09-02)*
The user asked how to tell if an area will attract higher-income people over time (the
Williamsburg question). This is NOT a return to the rejected "gaps predict growth" thesis (D1) —
it's an independent gentrification-trajectory score layered on top of the present-day screen.
`src/loci/model/rising.py` v1 uses only in-hand data: frontier value-gap (income surface,
weight .40 — the strongest predictor), LODES job growth 2013→2023 (.25), gentrifiable/renter
stock (.20), transit (.15). Combined into a 2×2 buy list (invest × rising): PRIZE = Murray
Hill-Flushing & Howard Beach bodegas; RISING bets = East New York fitness (active 2016 rezoning
zone, buildable); SERVE-TODAY = affluent stable Queens. Strengthening layer (NOT yet built,
priority order): ACS 2013→2023 resident income + college-share Δ, Zillow ZORI rent momentum,
DOB permit pipeline, upzoning events. Deliverables: buy list https://claude.ai/code/artifact/9544cb27-fb86-48db-acf0-135c6eee19cf
· validated shortlist https://claude.ai/code/artifact/26a6e851-120f-46db-b210-944c80d00bbf

**D20 — Real ACS income momentum replaces the LODES job-growth proxy in Rising.** *(2026-09-02)*
`src/loci/model/momentum.py` pulls ACS 5-yr 2013 & 2023 (3 boroughs) for aggregate HH income
(B19025/B11001 → mean, comparable across tract vintages) and college share (B15003), deflated
to 2023 $ (CPI ×1.308), aggregated to 2020 NTA via each year's tract centroids (Census
gazetteer). Two bugs fixed: null-suppressed income counted as $0 faked poverty crashes (now
drop nulls per-metric); must deflate or nominal +30% inflation masks everything. Findings:
3-boro real income +22.4%; **Brooklyn +34.6% vs Manhattan +20.6% vs Queens +17.5%**; corr(income,
college)=0.72 but corr(income, pop)=0.09 → gentrification-by-resident-swap, not growth; only 5
of 145 NTAs saw real decline (all already-rich Manhattan plateauing). The frontier marched
Williamsburg→Bed-Stuy→Bushwick→Crown Heights→Ocean Hill→**East New York** (now the edge:
+42% income but college only 9→14%, early stage). Rising v2 = .35 real-income + .20 college +
.20 frontier + .10 renter + .15 transit. **Corrections vs proxy:** East New York confirmed (top
rising bet), Glen Oaks promoted to PRIZE (+31%), Murray Hill-Flushing demoted (+9%, below city
avg). Story artifact: https://claude.ai/code/artifact/2f296aba-a0e3-4b86-8219-6389a2aaae03
Not yet built (strengthening layer continues): Zillow ZORI rent momentum, DOB permits, upzoning.

**D21 — East New York sized & written up as the recommendation (rooftops play).** *(2026-09-02)*
Forward check on ENY: Zillow rents cooled to +1.9%/yr (below borough) since 2022 though up 46%
since 2019; ZHVI still +4%/yr while Brooklyn went flat/negative; HPD pipeline booming (23k+
affordable units, 6,924 started 2018 post-rezoning, 3,454 in 2024). Reframe: ENY is densifying
faster than gentrifying — a **rooftops/volume play, not an income-escalator play** → a value-format
gym, not boutique. Network demand (800m walk of Pitkin core, real OSM graph): 7,778 homes /
~21,168 residents today + 2,253 pipeline units (~6,132 residents) = ~27,300, ~3,300 value-gym
members @12%. Sites: 209 commercial lots / 1.9M SF headroom; proposed 2016 & 1970 Pitkin Ave,
189 Pennsylvania Ave (warehouse conversions), 117 Georgia Ave (vacant), lease 626 Sutter/390
Liberty. New modules: model/momentum.py, model/invest.py, model/rising.py; ENY analysis scripts
in scratchpad. Capstone memo: https://claude.ai/code/artifact/33111940-da6b-47bf-99bc-236fa0a7021c

**D22 — Premium/destination amenities are a THIRD axis with an inverted method (Axis 3).** *(2026-09-02)*
The owner added a new question: where could a *premium* amenity open — **padel courts, spa
studios** first — given that people will travel much longer for these but opportunity remains.
This is NOT the daily-needs gap screen and must not reuse it: daily needs are convenience goods
(walk 800 m; gap = missing what ≥80% of walkable peers have), premium amenities are **destination
goods** (15–30 min drive/transit; **rare by nature**, so a prevalence-gap screen flags everywhere
and means nothing). Axis 3 therefore inverts to a **trade-area / gravity site-selection model**: a
travel-time catchment with enough *qualifying premium demand* but little/no supply reachable inside
it, plus a feasible **large-format** site. Parallel to Axis 1 (`invest.py`) and Axis 2 (`rising.py`),
and like them **not** a return to the rejected residual-growth thesis (D1). Written up as CONTEXT
§11. Ticketed as milestone **E6 · Premium Amenities** (8 issues, +36 pts → 71 issues / 261 pts) via
`tickets.py` → `loci gen-tickets`; pushed to Linear. Load-bearing design points captured in the
tickets: catchment travel time is the biggest lever (sweep 10/15/20/30 min); supply undercount is
WORSE than §7.1 for these new categories so Google validation is mandatory per top site; feasibility
gate re-tuned for large formats (padel ≈ 1,000+ m² + height, not a retail bay); demand pool is
income-decile/age/education-weighted, not raw homes. Bundle beyond the two anchors (med-spa, pilates,
boutique fitness, climbing, sauna, golf-sim) is judgment and tunable, like the tier weights and the
`invest.py` ECON minimums. **Not built yet — scope + tickets only this session.**

**D22 — Hosted read-only query app for sharing the dataset.** *(2026-09-02)*
Colleague-facing query service so others can ask the data directly. `queryapp/` (Flask +
DuckDB, built + verified end-to-end, then **taken down — not live yet** by user decision; tracked as Linear **GTM-85** (Backlog). Redeploy recipe in the ticket. Railway service loci-query was deleted.)
Purpose-built `loci_query.duckdb` (7.4MB, 3 self-describing tables: buildings 203,792 · neighborhoods
145 · pois 158,374) — clean names because the schema IS the NL→SQL interface. Three modes: English
(LLM→SQL, needs OPENAI_API_KEY env — not yet set), Filters, raw SQL. Guardrails: read_only connection +
SELECT/WITH-only + single-statement + table whitelist + forced/clamped LIMIT + 20s timeout. Password
gate via LOCI_QUERY_PASSWORD (set to loci-eny-2026; rotate as needed). Rebuild the DB to refresh
(it's a snapshot). `!queryapp/loci_query.duckdb` added to .gitignore so `railway up` ships it.

**D23 — Maturity curve + 2033 projection are Axis 4, the forward extension of Rising — NOT a revival of D1.** *(2026-09-02)*
The owner added two linked questions: where is each neighborhood on its maturity curve, and where
could growth get to by 2033 / how do we project it. The trap: the project's central result (§0/D1)
is that the causal "retail gap → growth" thesis FAILED (β=+0.069 wrong sign, pre-trends broken), so
"project future growth" must not smuggle that back. The reconciliation, written as CONTEXT §12: this
axis is **descriptive maturity staging + extrapolative projection from a neighborhood's OWN
multi-metric history** (income, college, rent, permits, jobs), never from the retail residual. The
pre-trend finding — these places are on a development cycle — is exactly what LICENSES momentum
extrapolation; it is forecasting from trajectory, not causation from a gap. Three honesty guardrails
baked into the tickets: (a) retail is the DEPENDENT read, re-scored against projected demand only at
the end (Bridge ticket), never a projection input; (b) output is scenario bands (continued/stall/
reversal), never a point forecast — trajectories bend, and D21 already caught ENY rents cooling to
+1.9%/yr; (c) ships as a forecast ONLY if it passes the backtest (fit through 2013, predict
2013→2023, must retrodict the Bushwick/Crown Heights/ENY arc) — the Axis-4 analogue of E3's
pre-trend/placebo rigor. Maturity STAGE is defined by level + rate + ACCELERATION (2nd derivative),
which is what separates it from a static wealth map: high-income-but-decelerating = maturing,
high-income-still-accelerating = rising. Projection methods: frontier diffusion (spatial, most
communicable — the Williamsburg→…→ENY wave, extrapolate the edge), logistic (saturating) per-metric
extrapolation, Markov stage-transition, plus an analogue read (2023 ENY ≈ 2011 Bushwick?). Needs a
new multi-decade `analysis.nta_trajectory` panel (momentum.py only pulled 2 points). Ticketed as
milestone **E7 · Maturity and 2033 Projection** (8 issues, GTM-77…84, +42 pts). **Not built yet —
scope + tickets only.**

**D23 — Gym/ENY recommendation OVERTURNED; gaps need category-radius + walkability-demand gating.** *(2026-09-02)*
Three end-of-session checks reversed D21's ENY value-gym call. (1) At a gym's real catchment,
ENY is served: 0 gyms @0.5mi walk but a Planet Fitness @1mi and ~20 gyms @2mi (Google) — the
800m "gap" was an artifact. (2) The uniform 800m threshold manufactures gaps for destination
categories (gym/supermarket/hardware — people travel for these; re-test at 1.4-2.4km) AND in
car-oriented neighborhoods; conditioning on category-appropriate radius + car-free share (ACS
B25044) dissolves nearly the whole buy list. (4) ENY new housing (3,224 units 2018-24 +2,111
pipeline, DCP kyz5-72x5) is affordable-dominated — no market-rate boom, confirming
densifying-not-gentrifying. **Corrected rule:** a gap counts only if it's a WALK-category
(bodega/laundry/cafe/hair/restaurant, ~800m) in a WALK-DEPENDENT nbhd (car-free ≥~50%).
**Revised candidates (need Google validation): East New York-City Line (bodega, already
validated; 60% car-free), Coney Island-Sea Gate (laundromat, 1,104 bldgs, 58%), Spring Creek
(laundry), Brownsville (cafe), Elmhurst (bodega, $92k).** Supersedes the gym thesis in D21.
Next: (a) bake category-radius + car-free gate into invest.py/rising.py; (b) Google-validate the
laundromat/cafe candidates (coverage-bias risk). Scripts: scratchpad/catchment_retest.json, /tmp/carfree.json.

**D25 — The 2033 maturity projection FAILS its 10-year backtest as a point forecast; it ships as ranking + scenario only.** *(2026-09-02, overnight — numbered D25 because a parallel session already used D22/D23 above)*
O4/GTM-82. Built the multi-decade panel (`nta_trajectory.json`: ACS 2009 via the B15002→B15003
college crosswalk + 2013/2018/2023, per-vintage tract centroids; 611 rows, 4 years, 155 NTAs). Fit
on ≤2013 (2009→2013 momentum), predict 2023, compare to actual: damped MAE **8.25** vs
naive-persistence **9.35** — only ~12% better, beats naive on just **56%** of NTAs — with a severe
**−7.75** under-prediction bias that LOO-CV damping-tuning does not fix. The neighborhoods that
mattered were flat 2009→2013 then surged (Bed-Stuy East 23→pred 27 vs actual 44; Ridgewood 23→pred
24 vs 41; Williamsburg 49→pred 62 vs 81), so **own-trajectory momentum does not anticipate ignition
at a 10-year horizon** — the flat-then-surge S-curve defeats it, and 2009–13 was an anomalously flat
post-crisis base. The 5-yr proxy worked only because the surge was already visible by 2013–18: skill
decays sharply with horizon. **What survives is rank order (corr 0.96).** Consequence: the
Arrival-Curve 2033 arrows and any "where growth reaches by 2033" claim are **ranking + scenario
illustration, not point forecasts** — the honest verdict, a direct echo of §0. Does NOT reinstate D1
(retail never entered the projection). Overnight-agent note: the data-engineer subagent built the
panel correctly before the stream watchdog killed it (600s stall); the statistician/data-scientist/
contrarian stages stalled too, so the backtest + verdict were finished in the main session. Remaining:
logistic/Markov forms, placebo/pre-trend, an accelerating-regime term — none likely to overturn the
horizon-decay finding. Report: scratchpad/O4_backtest_findings.md.

**D26 — Ignition is exogenous: the predictive model is a curated CATALYST layer, not zoning or trajectory (Axis 4b).** *(2026-09-02)*
Follows D25. Since a neighborhood's own trajectory does not predict ignition (D25) AND a naive PLUTO
development-headroom score just surfaces low-density suburbs (Fresh Meadows, Bath Beach — headroom
only because they're zoned/built low, no catalyst), the ignition signal comes from the **exogenous
project pipeline**: committed transit (SAS Phase 2 → East Harlem; proposed Interborough Express), DCP
neighborhood rezonings (East New York '16, East Harlem '17, Inwood '18, Gowanus '21, Atlantic Ave
'24), megaprojects (Willets Point). Built `src/loci/model/ignition.py` + `loci ignition`: a curated
17-project catalyst layer screened against low-mid maturity + a **deliberately LOW** density floor
(built_far≥0.6). Two design lessons: (1) **requiring a real catalyst IS the suburb-filter** — a
headroom gate is redundant and, set high, wrongly drops the low-rise-but-catalyzed frontiers (East
New York, built ~0.8) that are exactly the "underdeveloped, ripe for rezoning" case; (2) the screen's
"no-catalyst" reject list (Chinatown-Two Bridges, Harlem-125th, Washington Heights) is honest QA for
catalysts the layer is still missing. 42 candidates; the committed tier is defensible and CONVERGES
with the independent trajectory work — **East Harlem N (mat 29 + Q-train + rezoning) is the flagship**,
then the Atlantic-Ave cluster (Ocean Hill / Crown Heights / Bed-Stuy) and the ENY cluster. Does NOT
reinstate D1 (retail never enters). Recorded as O5. Remaining: expand the layer from DCP ZAP / MTA
capital / EDC, add DOB large-permit corroboration, productionize the layer as package data.
Report: scratchpad/ignition_shortlist.json.

**D27 — Catalysts run on TWO clocks: construction ~5–9y, demographic tip 10–20y and only if market-rate.** *(2026-09-02)*
Extends D26. Expanded the catalyst layer to 28 dated projects (forward + historical), pulled **198,514
DOB new-building filings** geocoded to NTA×year (2000–2023; `nb_by_nta_year.json`), and ran an event
study (`loci ignition --lag`) of dated past catalysts against NB permits and the maturity panel.
Finding: (1) **catalyst → construction** — new-building permits surge ~4–9 yr after a rezoning, peak
~6–11 yr (clean on the 2003–2009 catalysts: Williamsburg '05, Downtown Bklyn '04, LIC '08, Atlantic
Yards '06). (2) **catalyst → human-behavior/demographic change** — much longer and sustained:
neighborhoods catalyzed 2003–2008 were still gentrifying +8 to +13 pts ABOVE the +9.3 citywide drift
in 2013→2023, i.e. 15–20 yr later. (3) **Type matters** — East New York (affordable-dominated, 2016)
built the MOST (253 NB filings) yet gentrified *below* baseline: it densified without tipping
(confirms D21). Product consequence: the construction/land bet is this cycle; the appreciation bet is
a 2030s–40s horizon, conditional on the rezoning being market-rate. DOB corroboration column added to
the screen (`loci ignition`). Recorded in O5. Caveats: DOB classic (`ic3t-wcy2`) undercounts post-2016
(DOB NOW migration — union `w9ak-ipjd` to fix); descriptive event study, not diff-in-diff; catalysts
cluster in already-rising areas (the §0 endogeneity) so read lags as TIMING, not causation.
Reports: ignition_lag_findings.md, ignition_shortlist.json.

**D28 — Axis 3 (premium amenities) v1 built; padel is a data hole; premium demand must be steeply top-weighted.** *(2026-09-02)*
Started building E6. `src/loci/model/premium.py` + `loci premium`: the demand-vs-supply catchment
inversion of the daily-needs screen (CONTEXT §11). Supply from the cached Foursquare extract (fresh
rows, clean leaves: spa = `Health and Beauty Service > Spa` ~3.1k; boutique fitness = Pilates/Yoga/
Boxing/Climbing studios ~1.3k). **PADEL = 0 supply rows** — it barely existed before 2022, so it
cannot be screened from OSM/Foursquare at all (the charter's "undercount worse than §7.1" made
concrete); padel demand is scored but its supply needs Google/manual. **Modeling lesson (caught and
fixed):** a flat income×education demand weight × population surfaced populous *moderate*-income SE
Queens (Baisley Park, St. Albans) — wrong market. Premium consumers concentrate HARD at the top, so
demand is now population × maturity-CUBED, and opportunity = unmet demand (pool − PER×supply), not a
ratio that explodes at zero supply. Result is defensible: spa → East Harlem S, UWS-Manhattan Valley,
Fort Greene, Park Slope, Gowanus, Prospect Heights, Clinton Hill; boutique fitness → UES/UWS core +
LIC/Astoria (young-professional Queens, demand outrunning studios); padel → the affluent core
(Greenpoint, Gramercy, LES, West Village). Advances GTM-69 (bundle), GTM-70 (supply, minus Google
validation), GTM-72 (demand pool), GTM-75 (v1 opportunity score). Remaining E6: GTM-71 drive-time/
transit isochrones (v1 is straight-line), GTM-73 large-format feasibility gate, GTM-70 Google
validation (mandatory before shipping a site list — padel especially), GTM-74 ship map. Report:
premium_shortlist.json.

**D28 — Scope arc: one corrected pivot, then deliberate expansion toward a where/what/when investment dataset.** *(2026-09-02)*
A meta-entry recording how the project's scope has moved, so a later session reads the drift as
intentional rather than as accumulated creep. Owner framing that governs it: **we are still looking
for the diamond in the rough, and the axes are being assembled into one dataset that answers where to
invest, what to invest in, and when.** That through-line is the thing to protect; the axes are not
five unrelated projects, they are the columns of one investment question.

The movement, in four parts:
1. **The pivot (a correction, not creep).** The project began (D1) as a *causal* thesis — the retail
   gap/residual predicts subsequent residential growth. That was the assistant's reframing, not the
   owner's hypothesis, and it also **empirically failed** (β wrong-signed +0.069, broken pre-trends).
   Session 7 re-scoped to a **present-day investment screen** — walkable, populated hexes missing one
   obvious daily-needs business. The E3 causal apparatus survives only as honest negative science
   (see the SCOPE CORRECTION banner). This drift made the project *better*: it caught a misread that
   the data had already contradicted.
2. **Axis expansion → the where/what/when dataset (owner-driven).** One screen became a set of axes,
   each a column of the investment question: **WHERE** = Axis 1 Investability (D18) + Axis 2 Rising
   (D19–D21); **WHAT** = the gap screen itself (which business is missing) + Axis 3 Premium/
   destination amenities (D22, inverted method); **WHEN** = Axis 4 Maturity/2033 (D23, D25) + Axis 4b
   Catalyst/ignition (D26, D27). This is expansion, and it is coherent under the where/what/when
   frame — but two honesty flags stay attached: **Axis 4 failed its own 10-year backtest** (D25) and
   ships as ranking + scenario only, and every forward axis is explicitly fenced from reviving D1
   (retail is never a growth predictor).
3. **Deliverable drift: finding → tool.** From a public map + methodology memo (an argument you
   defend) to a hosted read-only query app + toggleable layers (D24-app) — from "here is the finding"
   to "here is a dataset you can interrogate." Consistent with the dataset framing above.
4. **Geographic drift both directions.** Manhattan cut once it had no validated gaps (D17), narrowing
   to Brooklyn/Queens — then E8 (GTM-87…94) expands the other way, NYC → a portable multi-city
   feasibility framework.

The failure mode to watch, stated so a later session can check against it: the sharp question
("areas missing an obvious business") must not quietly dissolve into "a general-purpose NYC
opportunity platform." Focus is what made the original finding defensible. Each new axis earns its
place only by serving where/what/when for the diamond-in-the-rough hunt — not by being interesting on
its own. Does NOT reinstate D1.

**D29 — Google validation "found ≥1" is NOT evidence of a coverage hole by itself.** *(2026-09-03)*
Every validation result must be split into (i) Google found nothing → gap survives; (ii) Google found
it AND loci's canonical deduplicated layer also has it within the same straight-line radius →
GEOMETRY artifact (nearest business is >800m by street network but inside the 800m straight-line
circle; median network distance for these hexes is ~850m, IQR 830–930); (iii) Google found it AND
loci has nothing → TRUE coverage hole. Why: the raw survival rates (hardware 58%, fitness 29%,
clinic 0%) were shown by red-team review to track how much wider Google's type is than loci's
category, not coverage. Corrected true-coverage-hole rates among sampled gap hexes: hardware
4/79 = 5% [95% CI 2–12], fitness 7/34 = 21% [10–37], clinic 0/22 = 0% [0–15]. Hardware verdict: "not
disproven" (never "real" — Google's hardware_store type excludes home_improvement_store so the 58%
is an upper bound). Fitness: ~half geometry, but a real ~20% coverage hole remains; needs an anchor
source.

**D31 — The walk threshold is not one citywide constant.** *(2026-09-03)*
Why: Manhattan at 5 min (gate recomputed) yields 19 gap hexes vs 9 at 10 min, and the category mix
flips entirely — hardware/pharmacy/clinic/bank vanish (their prevalence at 400m drops below the 0.80
expected bar) and convenience (16) and hair_barber (3) dominate, in superblock/institutional
footprints (FiDi, Lincoln Square, Morningside Heights, Turtle Bay). The 5-min Manhattan list rests on
near-census anchors (SNAP, DOHMH) and reads as an opportunity list; the gate-held-fixed variant
(53 hexes) is an upper bound and noisier. Next session's focus: per-category thresholds derived from
revealed spacing (typical hex-to-nearest distance per category), then density-class scaling.
*Refined by D33 (2026-09-03): the flip isn't a tuning problem, it's a monotonicity violation — see
below. Next session's focus is now the reach-based redefinition, not a parameter sweep.*

**D32 — Validator bug fixed (commit 877d162).** *(2026-09-03)*
`_local_counts` read un-deduplicated staging.poi and looked up only 'overture_places' and a
never-ingested 'osm_overpass', silently dropping foursquare_os_places (the dominant source for
hardware/fitness/clinic). New column n_local_canonical (canonical deduplicated, all sources);
`loci validate --recount-local` backfills without Google spend. Also: CLI now loads loci/.env via
python-dotenv (override=False) — previously GOOGLE_PLACES_KEY in .env was invisible and `--run`
failed.

**D33 — The "missing" rule is definitionally broken, not mistuned.** *(2026-09-03)*
Why: the current rule — a hex is a gap for category c at window w iff (no c within w) AND (c is
present within w for ≥80% of walkable hexes) — violates a basic invariant. Anything absent within
800m is absent within 400m, so a gap at 10 min must survive at 5 min. D31's Manhattan sweep shows the
opposite: hardware gaps at 10 min vanish at 5 min because hardware's prevalence at 400m drops to 51%
and the 80% bar simply stops expecting it. The rule fuses two questions that must be separated: (a)
how far people normally go for category c — a property of the category; (b) whether this hex is
anomalous relative to that norm — a property of the hex. Reusing one window for both means the window
silently decides which categories are eligible to be missing, so the 10-min and 5-min Manhattan lists
are two different screens, not two views of one. Redefinition (QUESTIONS D6): each category gets a
fixed REACH set once from revealed spacing (the distance within which ≥80% of populated hexes already
have one — the 80% bar survives only as the quantile that sets reach, never again as an eligibility
filter); a hex is a gap for c iff its nearest c is beyond reach(c), and the "walkable" eligibility gate
gets the same per-category-reach treatment. Acceptance test: MONOTONICITY — tightening any distance
parameter may only add gaps, never remove them; the current screen fails this and the new one must
pass it as a unit test. Caveat: revealed spacing reflects historical supply, not demand — a category
the whole city under-supplies will look like it "naturally" spaces wide and its gaps vanish; contrarian
review of the reach values is required before trusting them. Next session's focus is this redefinition,
not a parameter sweep.

**D34 — Reach rule lands the monotonicity fix but the p80 calibration is rejected; not publishable.** *(2026-09-05)*
What was built (uncommitted at session start, from 2026-09-04): `rule="reach"` in model/gaps.py
(`_compute_gaps_reach`, shared `_eligible_universe` gate), `reach.py` + `reach.yaml` (per-category
reach = p80 of hex-to-nearest-c network distance over populated hexes), `loci gaps --rule reach`
writing `analysis.hex_gaps_reach` (window rule and `analysis.hex_gaps` untouched), `loci reach-table`,
and tests/test_gaps_monotonicity.py. Verified this session: 61 tests pass (the one failure is in
test_comps.py, unrelated); `loci reach-table` reproduces reach.yaml exactly; the reach rule runs on
data/loci.duckdb (1,707 gap hexes / 6,189 hex-category pairs vs 726 hexes under the window rule);
scaling every reach by 0.8 yields a strict superset (2,251 hexes / 10,783 pairs) — monotonicity holds
on production data, not just the unit test. The censoring argument in reach.yaml also holds.
Why it is still not publishable (contrarian review, ranked): (1) reach(c) = p80 of the hex-to-nearest
distribution makes ~20% of eligible hexes a gap for EVERY category by construction — per-category
counts over 3,041 eligible hexes are flat (childcare 460, tailor 446, grocery 433, restaurant 427,
hardware 368, bank 367), so the rule cannot say which business NYC is short of; 56% of eligible hexes
are gaps and only 468 (15%) miss exactly one category, while 888 miss three or more — those are
under-retailed areas, not "otherwise complete" ones. (2) The exactly-one list is a quantile artifact:
its size is stable across p70/p80/p90 (463/468/471) but membership is not — p80∩p70 = 152/468,
p80∩p90 = 95/468; 373 of the 468 p80 hexes have zero missing categories at p90. The 0.80 is inherited
from the old prevalence bar and is load-bearing for ~80% of the list. (3) The lead rule
(`lead = min(missing, key=reach)`) is a fixed global priority list: restaurant (275 m, the smallest
reach) is lead in 427 hexes with a restaurant at median 352 m, max 730 m — not an opportunity — while
hardware gaps (median nearest 858 m, max 2,266 m) are outranked wherever restaurant also trips.
(4) The gap flag is largely a coverage flag: corr(n_missing, log POI count within 800 m) = −0.67;
gap hexes have median 186 canonical POIs within 800 m vs 526 for non-gap hexes; fitness (429) and
clinic (401) sit near the top of the gap counts despite D29/D30. (5) Reach is fit on all 3,436
populated hexes but applied to the 3,041 gated ones; refitting on the gated set shrinks every reach
8–25%, gaps go 1,708 → 2,107, top-50 overlap 35/50. Monotonicity is necessary but nowhere near
sufficient: it is silent on the quantile, calibration population, gate, lead rule and MAUP.
Decision: keep the reach ARCHITECTURE (fixed per-category distance, no global window, monotone) and
the monotonicity test; reject the p80 quantile as the calibration statistic and the min-reach lead
rule. Recommended replacement, to be decided next session (QUESTIONS D8): calibrate reach(c) from
same-type store-to-store spacing (D5 / `loci spacing` already computes it), which is a property of how
the category tiles the city and does not pin the gap rate; rank the lead category by excess over reach
(nearest_m − reach_m, or the ratio), never by reach itself. Extended acceptance battery, all
required before publication: monotonicity (unit test + production superset check); per-category gap
counts must NOT be flat across categories; the exactly-one list must be stable (≥80% overlap) across
reasonable calibration variants; every lead must exceed reach by ≥100 m; a D29-style three-way
coverage split on a stratified sample of gap hexes in the lowest POI-density decile. Also fixed:
build_gaps return annotation (was `-> int`, returns a tuple).

**D35 — Reach calibration comparison: spacing and p80 variants rejected; external walk-time tiers recommended, pending owner.** *(2026-09-05)*
Why (data-scientist run over the 3,041 eligible hexes, all candidates through the unchanged
`compute_gaps(rule="reach")`; scratch outputs kept outside the repo): (a) same-type store-to-store
spacing is dead on arrival — NYC same-type nearest-neighbour spacing is 0–218 m at the median
(restaurant 0, nails 0, grocery 22, hardware 218) because a trade's stores share a block; it measures
clustering, not a service radius, and yields 3,041/3,041 gap hexes with one exactly-one hex. (b) p80
on all populated hexes (the D34 baseline) and (c) p80 refit on the gated universe are the tautology:
per-category gap-count coefficient of variation 0.063 and 0.003 (every category 605–612 under c,
exactly 20%); ±10% reach nudge keeps only 60%/54% of the exactly-one list; 59% of (b)'s exactly-one
leads sit within 100 m of reach. (d) external tiers by trip frequency — 400 m grocery/convenience/
pharmacy/cafe_bakery/restaurant/childcare, 800 m laundry/bar/fitness/hair_barber/nails_beauty,
1,200 m bank/clinic/hardware/tailor_repair — is the only candidate whose per-category counts carry
information (CV 1.07, range 0–771), the most stable under perturbation (Jaccard 0.54, 70% of the list
kept at ±10%), with the least marginal leads (median excess 125 m). Totals: (d) 1,689 gap hexes, 730
exactly-one. Lead rule: min-reach must go (under (b) it hands restaurant 426 leads with a restaurant
352 m away; under any tiered reach it ties on 42% of hexes and is decided by dict order); max-ratio
(nearest_m / reach_m) beats max-excess because raw metres reward whichever category has the widest
reach. Monotonicity holds for every candidate (reach×0.8 removes 0 pairs) — it is the rule's
property, not the calibration's. What no calibration fixes: corr(n_missing, log POI count within
800 m) stays −0.62 to −0.70 for all of them, so "missing" is still largely "low retail density"
(M1's question, not D8's). What is now load-bearing: the tier assignment — moving pharmacy 400→800
drops it 763→21 gaps, childcare 771→60; a variant with two tiers reassigned overlaps the exactly-one
list only 347/988. tailor_repair takes 30–38% of leads under any excess rule because it is the
thinnest category (872 canonical POIs vs 75,795 restaurants); a lead needs a downstream viability
filter. Decision: recommend (d) + max-ratio, NOT adopted yet. Before adoption the owner must pin the
tiers to a citable external source (H-L3 food-desert / 15-minute-city thresholds, H-L4 Walk Score)
or explicitly to the owner-set norms already in `src/loci/conveniences.yaml` — note that doing the
latter makes the hex gap screen and the address conveniences check the same normative claim at two
geographies, which conveniences.py's docstring currently says they are not.

**D36 — 0 m same-type spacing is mostly a snapping artifact; the real duplication is DOHMH turnover.** *(2026-09-05)*
Why: the D35 spacing run found restaurant and nails_beauty at a median 0 m same-type network
distance, which would bias every nearest-distance in the screen low if it were duplication. Data-
engineer check on straight-line distance: 74.5% of restaurants share a walk-graph node with another
restaurant, but within those "0 m network" pairs the straight-line distance is median 16.4 m (p90
47 m, max 134 m) — ~86% of the 0 m result is graph nodes being coarser than storefront spacing, not
data. The residual true-zero share (13–14% of restaurant, nails_beauty and clinic canonical POIs at
exactly the same coordinate) traces to `sources/cities/nyc/dohmh.py`: it dedupes by CAMIS but never
filters closed establishments out of DOHMH's 3-year rolling window, so a closed tenant and its
successor at one address both survive as canonical points. Only 0.09% of ≤15 m restaurant pairs share
a normalized name, so H-D11 (cross-source legal-vs-trade names) is not the dominant driver. Impact on
the gap screen is minimal (duplicates share coordinate and category, so nearest-distance is
unaffected); the exposure is inflated raw counts feeding the DNCI saturating term in well-served
food/beauty hexes. Also found: `score/dedup.py` docstring says 25 m but `MATCH_METERS = 40.0` — a
doc/code drift to reconcile. Decision: filter the DOHMH adapter to currently-active establishments
before dedup (next action), reconcile MATCH_METERS, and treat network-0 m spacing as
uninformative for calibration. No change to the name-matching dedup logic.

**D39 — Address-level reach screen: fixed gate required for monotonicity; the exactly-one list
is a knife-edge at any geography.** *(2026-09-05)*
Why (Sonnet run over 767,337 residential addresses / 3,735,269 units, all five boroughs, per-address
nearest distance for all 15 categories from the conveniences Dijkstra engine in 158 s; scratch
outputs outside the repo): (1) The literal port — eligible iff within reach of ≥12/15 categories,
gap iff nearest beyond reach — VIOLATES monotonicity for every candidate: reach×0.8 removes
209k–232k gap pairs because addresses fall out of eligibility faster than they gain gaps. That is
the D33 defect re-introduced. Gating on a FIXED, reach-independent presence test (≤800 m for ≥12/15,
as gaps.py's `_eligible_universe` already does) restores it: 0 pairs removed for all candidates.
Rule: the eligibility gate must never depend on the reach table. (2) Fixed gate: 607,245 eligible
addresses (79.1% of addresses, 90.7% of units). External tiers (d) remain the only calibration whose
category counts carry information (unit-weighted CV 1.09 vs 0.04–0.21 for p80 variants, which are
the tautology D34 described — flat counts are the failure, not the pass). But on addresses (d)'s
counts are dominated by childcare and tailor_repair with nails_beauty and clinic near zero: the tier
assignment is doing all the work (D35's warning, now quantified). (3) The "exactly one missing"
list is unstable everywhere: ±10% reach → Jaccard 0.41–0.58 for every candidate, against the D34
bar of ≥80%, at address level as at hex level. This is a structural property of a binary knife-edge
classification, not of any calibration. Decision: the deliverable ranks addresses by a continuous
statistic (max nearest/reach ratio, or the lead's excess over reach), possibly averaged over a
reach band, and does NOT publish a binary exactly-one list. (4) Coverage correlation persists
(−0.58 to −0.65) — M1, unchanged. (5) Clustering artifact: top clusters by units are single
mega-lots (Co-op City towers, 10,914 and 9,669 units on one PLUTO lot); clustering must be by
building/lot group with a unit cap, or the ranking is a housing-density list. (6) Overlap with the
legacy address_gaps.py output (800 m/80% rule, MN/BK/QN): Jaccard 0.24 — expected, different rule
and geography; the legacy output is superseded. Overlap with hex_gaps_reach leads on the same cell:
8.8% — the two lead rules differ; not comparable. Next: port to address_gaps.py with the fixed gate
and a continuous ranking; the D8 tier source decision is now the whole game.

**D43 — The adopted tiers are a floor standard; mature Manhattan's market standard is 3–7× tighter and density-dependent (owner question).** *(2026-09-05)*
Why: owner asked what the free market dictates in developed, zero-gap Manhattan areas (West
Village, East Village and the like). Over the 27,302 Manhattan addresses (768,847 units, 80.2% of
the borough) with 0/15 gaps under reach_tiers.yaml, the unit-weighted p80 nearest distance is far
inside the adopted reach for every category: restaurant 80 m vs 400 (0.20), grocery 156 vs 800
(0.20), pharmacy 216 vs 800 (0.27), fitness 167 vs 1,200 (0.14), clinic 223 vs 960 (0.23), hardware
334 vs 960 (0.35), tailor 449 vs 960 (0.47), convenience 223 vs 400 (0.56), laundry 188 vs 320
(0.59); full table in docs/market_reach_manhattan.md. Not an artifact of the completeness filter:
over all Manhattan addresses every category is still 16–74% of the adopted tier. Not dominated by a
few NTAs (top 10 = 49% of complete units; 36 of ~40 NTAs) and no lot-size bias. Consequences: (1)
under the adopted tiers Manhattan almost never gaps, so the screen's discriminating power is in the
outer boroughs — the tiers are a floor ("nobody should be beyond this"), not the market standard.
(2) "What the free market dictates" is density-dependent — Manhattan's distances are short because
its density is 19–30k units/km²; adopting them citywide would flag most of Queens. (3) Therefore
the right refinement is D7 (density-class reach): set reach(c) per density class from complete
areas within that class, so a gap means "short of what places like this one actually have." That is
a modeling decision for the owner; the adopted D41 table stands until it is made. Carry: the
complete-area p80s are supply-revealed and inherit D33's caveat (a citywide under-supplied category
looks "naturally" wide); pairing them with the cited floors from D41 bounds reach from both sides.

**D44 — Address-level reach screen shipped citywide; the ratio ranking is dominated by tailor_repair and laundry, so a lead-viability rule is the next decision.** *(2026-09-05)*
Why: developer agent rewrote `model/address_gaps.py` per D38/D39/D41 — old 800 m/80% rule deleted;
one shared per-category Dijkstra (`_dijkstra_per_category`) with a parquet node-distance cache under
data/interim/; fixed reach-independent gate (≤800 m for ≥12/15); continuous ratio = nearest/reach,
gap_score = max ratio, lead = argmax (ties → larger nearest), n_missing = count(ratio > 1); units
capped at 500/lot; DBSCAN-like clustering (200 m) by (borough, lead). New table
`analysis.address_gaps` (provenance: reach_source, reach_hash, graph_version, run_at); new
`loci address-gaps --borough --reach tiers|p80 --limit --dry-run`; `reach.load_reach(source)`;
tests/test_address_gaps.py (8 tests). Suite 93/94 (the one failure is test_comps, known). Citywide
run: 767,337 addresses / 3,735,269 units in 2m06s; eligible 607,245 (79.1% of addresses, 90.7% of
units); 1,383 clusters. Per-category gap counts (addresses): tailor_repair 256,535, laundry 247,229,
bar 202,974, bank 152,213, cafe_bakery 128,826, convenience 119,085, childcare 58,241, restaurant
42,433, hardware 42,141, hair_barber 15,685, clinic 10,414, pharmacy 8,273, nails_beauty 4,983,
fitness 3,794, grocery 1,353. Lead distribution: tailor_repair 156,273, laundry 117,530, bar 66,214,
bank 47,776, convenience 18,390, cafe_bakery 12,567, childcare 11,375, hardware 4,554, all others
< 500 each. Top clusters by capped units are almost all tailor_repair (BK 76,856 units, BX 48,609, QN
43,145 …). Finding: the ratio ranking hands the lead to the thinnest category (tailor, 872 canonical
POIs) and to the tightest reach (laundry, 320 m owner norm) — D35's warning realized at scale. "The
one obvious missing business" cannot be a tailor for a fifth of the city. Decision needed (owner):
a lead-viability rule — candidates: (a) exclude categories whose citywide supply is below a floor
from lead eligibility (tailor), (b) require the lead's excess over reach to exceed a category-specific
minimum, (c) per-density-class reach (D7/D43) so laundry's 320 m is not applied to Staten Island.
Until decided, analysis.address_gaps is a scored table, not a published list. Also: `load_reach`'s
default is now "tiers", which silently switches `loci gaps --rule reach` (hex, history) from p80 to
tiers — intentional under D41 but hex outputs are no longer comparable to D34's numbers. Bug found:
conveniences.py's hex_lookup `dict(...3-column fetchall)` raises ValueError in the write path; fixed
the same session (line 177, now a dict comprehension).

**D51 — Trust factor dropped from the grade; the supply set is the next deliverable; all of Brooklyn is in scope; in-building laundry becomes a supply input.** *(2026-09-08, owner)*
Context: a data-scientist proposal for the graded recommendation (D48) was drafted on MN+BK — G = 100 · S · D · M · C with S a geometric combination of the reach ratio and absolute excess meters, D a units-within-800 m catchment term, M the demand.yaml modifier, and C a confidence factor (reach-basis provenance × POI/ZBP coverage) — with action bands at G ≥ 50 act / 25–50 watch / <25 none. A contrarian review (scratchpad grade_contrarian.md, session 13) returned: (1) C FAILS on arithmetic: C(tailor) = 0.49 caps tailor's maximum grade at 49 against a 50 cutpoint, which is the hard supply filter D48 rejected, written as a coefficient; with C ≡ 1 the act band goes 25,269 → 83,137 pairs and tailor returns as the largest category. (2) The supply set dominates every other parameter and was never settled: re-running the screen on corroborated-only POIs (≥2 sources) grows the act band 6× (→154,104), Jaccard 0.11, Spearman 0.19 against the all-POI run; two defensible supply sets give two different cities. (3) Per-density-class reach calibrated from revealed spacing reintroduces D34 (Manhattan p80 pins the gap rate at 20.9%, per-category CV 0.14); the honest alternative is a one-constant theoretical form reach ∝ sqrt(U_half/ρ) fit on the four cited categories. (4) The coverage-bias attack FAILS: partial correlation of feed thinness with the act band, controlling density, is −0.02 (p = 0.84); half the band is in registry-anchored categories. (5) An unraised demand confound: the largest cell is ~9,800 bar gaps in Midwood, Borough Park, Flatlands, Dyker Heights, high-income so M is silent, where absent bars are revealed demand, not opportunity — the D1 trap (absent supply read as latent demand); a demand control that is not income is required before any discretionary recommendation is published. (6) Bands are arbitrary until audited; 40% of the act band sits in G ∈ [48, 52); audit ≈210 addresses stratified by category × NTA and anchored flag, not by G decile. Also found: nearest_m is right-censored at 2,400 m (cap_m), so the max attainable ratio is 2400/reach and the D44 max-ratio ranking partly sorted the reach table; the fixed 800 m/12-of-15 gate does no work inside MN+BK (100% MN, 95% BK eligible).
Owner rulings: (a) drop C from the grade product; carry reach provenance and POI/ZBP coverage as annotations and as a discount in the O7/O8 fair-price hand-off. (b) The supply set is the next deliverable, ahead of any grade adoption: fetch DOHMH/NYS DOS date fields and filter to active establishments (D36/D47), attack the bar/fitness/nails dedup residual, and compare all-POI vs corroborated-only vs active supply sets against ZBP per category. (c) All of Brooklyn stays in the calibration set, not just the denser terciles. (d) In-building laundry (basement or in-unit) is a supply-side input for the laundry category — addresses that have it do not experience a laundromat gap — and a source for it is to be found and probed before the laundry screen is re-run.
Why: the grade's shape (gradient, both ratio and excess must fire, density, demand modifier, monotone in reach) survives; what does not survive is any chosen coefficient that can close a band to a category, and any calibration done before the set of real businesses is settled.

**D59 — Supply-set principle applied and re-run; laundry anchored via DCWP inspections; alcohol overlay shipped; liquor stays an overlay; StreetEasy sweep approved at full scope.** *(2026-09-09, owner)*

Results of the D52 re-run (MN+BK, <5 min end to end): anchor coverage qualifies nails_beauty 3.04, bar 1.85, restaurant 1.46, convenience 1.43 (SNAP), cafe_bakery 1.23; grocery 0.58 and hair_barber 0.39 are too thin; eight categories have no anchor loaded. PRINCIPLED dropped lone aggregator records only in the five anchored categories (restaurant 40,191→20,476, cafe 10,059→4,638, nails 9,810→4,308, bar 7,505→3,304, convenience 2,850→1,779; 36% overall); the ten unanchored categories are bit-identical. Share of eligible addresses beyond reach rose only in those five (bar 25→39%, cafe 10→21%, convenience 9→15%, restaurant 3→5%); lead_category changed for 23% of eligible MN+BK addresses. Snapshot of the prior screen kept as analysis.address_gaps_prev and data/interim/address_gaps_prev.parquet. Provenance now records supply_set + supply_hash. A NULL-name crash in the booth-renter code was fixed. Caveat: nails qualifies as anchored because the DOS registry itself runs ~3× ZBP (residual booth renters, non-salon licences) — it clears the bar for the wrong reason (QUESTIONS follow-up, D14). Caveat: the webmap POI layer read poi_dedup.is_canonical directly and showed 100,213 known locations while gaps were measured against 64,303 — being fixed to read analysis.poi_supply and to draw excluded records distinctly.
Laundry anchor: the DCWP licence roster (w7w3-xahh) has NO retail-laundry category (6 'Laundries' licences, all expired 2023) — that is why the adapter emitted nothing. Retail laundries exist only in DCWP Inspections (jzhd-m6uv, business_category 'Retail Laundry' and 'Dry Cleaners - 230'; industrial laundry excluded). The historical-licences file (m4ph-grrm) shows 2,587 CURRENT LAUNDRY rows but is a frozen October-2013 snapshot — not used, recorded so nobody takes the bait. Staged 2,277 MN+BK establishments (99.9% geocoded), 1,561 active (out_of_business 1,289 inactive); anchor_coverage 1,561/1,475 ZBP = 1.06 → laundry QUALIFIES; 1,015 within 40 m of an existing canonical laundry, 546 new. Merge = `loci ingest-dcwp --no-stage --apply && loci dedup`, then score/address-gaps/export (queued after the webmap fix). No staleness cut (inspections are enforcement-driven); feed starts 2023-07 so a never-inspected laundry is indistinguishable from a gap.
Alcohol overlay (D52c) shipped: every active SLA licence in MN+BK as a toggleable layer with symbol classes on_premises 10,757 / off_premises_liquor 863 / off_premises_beer 3,438 / other 451 / unclassified 617 (16,126); drift test on the 55-value vocabulary; verified not to touch the gap or POI layers.
Category expansion (D55): planning agent's proposal (scratchpad category_expansion_plan.md) → milestone E10 with dentist (NPPES anchor verified), specialty_food (NYS Ag&Markets retail food stores 9a8c-vfzj), eye_care (NPPES half), dollar_variety (no anchor), vet_pet (no bulk anchor exists), plus a mechanics ticket (TIER_WEIGHTS re-partition, MIN_PRESENT 12-of-15 re-derivation, max-ratio monotone in category count). Dropped: dry cleaners (already inside laundry 812310+812320), shipping & mail (no anchor, NAICS 491110 is government so no ZBP check), florist/books/phone repair (three unrelated codes, tiny counts), auto & gas (drive-time trade area in a pedestrian screen). **Owner 2026-09-09: liquor stays a MAP OVERLAY and is dropped from E10** — D52(c) stands. Tickets regenerated (115 issues / 11 milestones); pushed to Linear as GTM-112 (mechanics, Urgent), GTM-113 (dentist), GTM-114 (specialty_food), GTM-115 (eye_care), GTM-116 (dollar_variety), GTM-117 (vet_pet).
Listings: only StreetEasy unit pages expose amenities + address + past listings via Tavily (Zillow/RentHop render without amenities, Apartments.com refuses). Bay Ridge pilot: 222 listings / 52 BBLs, 173 in-building, 23 in-unit, 0 explicit none (silence is never absence); 41 of 98 ≥6-unit laundry leads annotated (2.2% of all Bay Ridge leads); address→BBL matches within 5 m from the page's own coordinates. Coverage is size-selected (median 38 units where found vs 14.5 where not) and archival (213/222 past). **Owner approved the FULL sweep of all MN+BK laundry leads (~34k calls / ~37k credits / ~$294), ≥6-unit addresses first,** paced, parquet sink, one short merge at the end.
Why: the supply set was the gate before any grade (D51); it is now measured per category, laundry has a real anchor, and the two laundry demand inputs (LL84, listings) are on disk so the grade design can consume them.

Post-merge result (2026-09-09 13:19, supply_hash e2b7ef55e607, commit 4b5a9e2): laundry anchor_coverage 1.42 (2,099 anchored canonical vs 1,475 ZBP; 4,285 DCWP inspection rows citywide merged). On the 266,871 eligible MN+BK addresses present in both runs, the laundry-gap share moved 26.8% → 27.4% (p50 ratio 0.68 → 0.68, p90 1.46 → 1.51): 18,297 addresses were CLEARED by the 546 new DCWP locations and 19,763 became NEW laundry gaps because anchoring drops lone-aggregator laundromats — the anchor reshuffles which addresses are laundry gaps rather than shrinking the count; lead_category = laundry share 17.0% → 18.3%. Cleared addresses concentrate in Flatlands 1,320, Canarsie 1,253, Bensonhurst 878, Sunset Park (Central) 830, Bedford-Stuyvesant (East) 827, Borough Park 777. Baseline kept at data/interim/address_gaps_d52_mnbk_before_dcwp.parquet. Webmap re-exported against the same hash. StreetEasy sweep relaunched detached (run dir data/interim/listings_sweep/2026-09-09-mnbk, launch.sh, run.pid; first two attempts died — one on the API session limit, one on macOS OSError 49 'Can't assign requested address'); land with `loci ingest-listings --merge <dir>` when done.
