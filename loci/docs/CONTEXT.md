# Loci — Project Context

**Status:** charter / pre-implementation
**Created:** 2026-09-01
**Scope:** New York City, five boroughs
**Owner:** Avi Benmayor

Loci measures how completely the *daily-needs bundle* of small businesses is reachable on
foot across New York City, identifies places that have materially less of it than
comparable places, and tests whether that gap predicts subsequent residential growth.

This document is the single source of truth for the thesis, the data, the method, and the
things that could make the whole thing wrong. Read it before writing code.

---

## 0. Headline finding (2026-09-01)

**The causal thesis is not supported by the data.** The descriptive tool works — it measures
walkable daily-needs retail completeness and, via the residual, identifies where retail is thin
relative to comparable places (top-20: Jamaica, the Rockaways, East New York, and a surprise at
UES-Lenox Hill). But the investment claim — that these gaps represent latent demand that will
*drive future residents* — fails its test:

- **P2 (underserved → subsequent growth): REJECTED, wrong sign.** Regressing 2013→2023 population
  growth on the 2013 retail gap gives β = **+0.069 (p=4.7e-16)** — over-retailed hexes grew MORE,
  under-retailed hexes grew LESS. The placebo is a clean null, so the reversal is real.
- **Pre-trend test: parallel trends BROKEN.** The 2013 gap also predicts *prior* (2002→2013) retail
  growth (β=+0.27), so the gap marks neighborhoods already in a development cycle. Retail and
  residents co-move; the gap does not identify latent opportunity.

This is the endogeneity §7.2 and the whole residual design were built to detect, and the rigor
(residualization + temporal ordering + pre-trend + placebo) is what caught it rather than
shipping a confident-but-wrong thesis. **Loci is a valid descriptive instrument; its investment
inference is not confirmed.** The honest product is the map + the method + this null.

---

## 1. Thesis

### 1.1 The naive hypothesis

> Parts of New York are highly walkable — laundromats, nail salons, restaurants and
> grocery stores all within a few blocks. Other parts lack these core small businesses.
> Where transit access already exists, that missing retail infrastructure is a barrier to
> attracting new residents.

### 1.2 Why the naive version fails

The naive hypothesis is **endogenous**. Retail follows rooftops. Laundromats, salons and
bodegas locate where there are already enough residents with enough disposable income to
support them. Tested as stated, this project would produce the finding:

> *Dense, higher-income neighborhoods have more small businesses.*

Which is true, already known, and commercially worthless. Worse, it would invert the
causal arrow the thesis depends on: the correlation would be read as "build the shops and
the residents come," when the data generating process is "the residents came, so the shops
opened."

Any version of this project that scores hexes on **raw business counts** and ranks the
bottom of that distribution is producing a poverty map with extra steps.

### 1.3 The refined thesis

The defensible reformulation replaces the raw count with a **residual**:

> **Conditional on population density, household income, transit access, and commercial
> zoning capacity, some NYC hexes have materially less daily-needs retail than otherwise
> comparable hexes. That residual gap — not the raw count — is the opportunity signal, and
> it should predict subsequent residential growth.**

The residual is what makes this an investment thesis rather than a description. A hex with
few businesses because it is a low-density industrial zone is *explained*. A hex with few
businesses despite matching density, income, transit and zoning of well-served peers is
**unexplained**, and unexplained undersupply is where a market opportunity can live.

### 1.4 Falsifiable predictions

The thesis generates three predictions. Each can fail.

| # | Prediction | Fails if |
|---|---|---|
| **P1** | The residual has meaningful spread after controls — i.e. retail supply is *not* fully determined by density, income, transit and zoning. | R² of the supply model is so high (>0.9) that nothing is left to explain. The thesis has no room to be true. |
| **P2** | A negative residual at t0 predicts above-average growth in population, households, rents and permitted units over t0→t1, with controls and borough fixed effects. | Coefficient is null, or signed the wrong way (gaps persist because they reflect durable demand suppression, not latent opportunity). |
| **P3** | The measured gap is real, not an artifact of data coverage — the ranked underserved list survives validation against ground truth. | Google Places validation shows the POI undercount is concentrated in exactly the hexes flagged as underserved. **This would invalidate the entire finding.** See §7.1. |

P3 is not a robustness check bolted on at the end. It is the load-bearing one, and it is
scheduled in Week 4 with budget attached.

---

## 2. Definitions

### 2.1 The daily-needs bundle

Fifteen categories in four weighted tiers. Tier weights are judgment calls, stated
explicitly so a reader can disagree with them precisely (see §9).

| Tier | w | # | Category | OSM tags | NAICS |
|---|---|---|---|---|---|
| **T1 Necessities** | **0.40** | 1 | Grocery / supermarket | `shop=supermarket\|greengrocer\|grocery` | 4451 |
| | | 2 | Bodega / convenience | `shop=convenience` | 445131 |
| | | 3 | Pharmacy | `amenity=pharmacy`, `shop=chemist` | 4461 |
| | | 4 | Laundromat / dry cleaner | `shop=laundry\|dry_cleaning` | 8123 |
| **T2 Personal services** | **0.20** | 5 | Hair / barber | `shop=hairdresser` | 8121 |
| | | 6 | Nail / beauty | `shop=beauty`, `beauty=nails` | 8121 |
| | | 7 | Tailor / repair | `shop=tailor\|shoe_repair\|clothes_repair` | 8114 |
| **T3 Food & gathering** | **0.25** | 8 | Restaurant | `amenity=restaurant\|fast_food` | 7225 |
| | | 9 | Cafe / bakery | `amenity=cafe`, `shop=bakery` | 7225, 311811 |
| | | 10 | Bar / pub | `amenity=bar\|pub` | 7224 |
| **T4 Civic & wellness** | **0.15** | 11 | Childcare | `amenity=kindergarten\|childcare` | 6244 |
| | | 12 | Clinic / urgent care | `amenity=clinic\|doctors` | 6211, 6214 |
| | | 13 | Fitness | `leisure=fitness_centre` | 713940 |
| | | 14 | Bank branch | `amenity=bank` | 5221 |
| | | 15 | Hardware / home supply | `shop=hardware\|doityourself` | 4441 |

**Deliberate exclusion.** Libraries and parks were considered for T4 and are **excluded
from the DNCI**. They are public goods, not small businesses, and including them would
dilute the index away from the thesis. They are carried as separate **context layers** —
rendered on the map, available as model controls, never scored into the bundle.

### 2.2 Walkable

**Network distance along the pedestrian graph**, never Euclidean. Straight-line buffers
are wrong in NYC specifically: waterfronts, rail cuts, expressways, and superblock NYCHA
campuses all create places where 300 m of separation is a 20-minute walk.

Walking speed **4.8 km/h (80 m/min)**. Three thresholds:

| Threshold | Network distance | Role |
|---|---|---|
| 5 min | 400 m | "on my block" — sensitivity check |
| **10 min** | **800 m** | **primary** — the headline DNCI |
| 15 min | 1200 m | "15-minute city" comparability with the literature |

### 2.3 Spatial unit

**H3 resolution 9** hexagons (~174 m edge, ~0.105 km² each), clipped to the NYC shoreline.
NYC's ~778 km² of land yields **≈7,400 cells**.

Hexes over tracts because they are uniform in area (tracts vary ~100× in NYC, so "per
tract" means something different in Midtown than in Tottenville) and because they are
city-agnostic, which serves the eventual second-city goal. The cost is that ACS
demographics must be interpolated onto them — see §4.2.

### 2.4 Study period

- **Cross-section:** 2026 (current Overture / DOHMH / DCWP snapshots).
- **Panel:** 2002–2023 annual (LODES WAC availability).
- **Main growth spec:** t0 = 2013 → t1 = 2023.

---

## 3. Data source registry

Costs verified 2026-09-01; SNAP and SLA sources verified 2026-09-02. Machine-readable mirror: [`src/loci/registry.yaml`](../src/loci/registry.yaml).

### 3.1 Business locations — present day

| Source | Geography | Temporal | Refresh | Cost | Known bias |
|---|---|---|---|---|---|
| **Overture Maps Places** — GeoParquet on S3, `overturemaps-py` | point | 2023– | monthly | **$0** (CDLA-Permissive-2.0) | Inherits OSM/Meta/Microsoft coverage gaps; category schema is coarse for personal services |
| **Foursquare OS Places** — 100M+ POI | point | 2024– | monthly | **$0** (Apache-2.0) | Skews toward venues with consumer check-in history — i.e. away from laundromats. **Access is gated since 2025-10** (Hugging Face terms + `HF_TOKEN`; public S3 retired). Loaded 2026-09-02. **Ghost venues:** rows last refreshed before 2019 are corroborated <10% of the time, so the adapter keeps only rows refreshed since 2024 (109k of 191k mapped) |
| **OpenStreetMap** via Overpass | point/poly | live | continuous | **$0** (ODbL) | **Undercounts small business in lower-income and immigrant neighborhoods.** The project's most dangerous bias — see §7.1 |
| **NYC DOHMH Restaurant Inspections** `43nn-pn8j` | address + lat/lon | 3-yr rolling | daily | **$0** | **Near-census of food service** — every establishment is inspected. Effectively unbiased. The project's best asset. |
| **NYC DCWP Legally Operating Businesses** `w7w3-xahh` | point | issuance-dated | daily (rowsUpdatedAt 2026-08-20 — **not stale**) | **$0** | **Contributes ~nothing to the daily-needs bundle:** consumer "Laundries" has *zero* active licenses (all active laundry licenses are industrial B2B linen suppliers, excluded). No pharmacies licensed. Retained only for the E5 license-history panel. |
| **NYS DOS Appearance Enhancement & Barber** `y3u4-jbgh` | address | **active only** | periodic | **$0** | **Survivorship-biased** — closed salons absent entirely. Snapshot enrichment only, never panel input |
| **USDA SNAP Retailer Locator** — ArcGIS feature service | point | current | snapshot | **$0** | **Near-census of stores that accept SNAP** — anchor for grocery/convenience (tier 1). Misses non-SNAP stores, which skews *toward* affluent areas, the opposite of OSM's bias. Verified 2026-09-02 |
| **NYS Liquor Authority Active Licenses** `9s3h-dpkz` | point (98.5% georef.) | current | snapshot | **$0** | **Anchor for bars.** Companion inactive file `6dg3-2z7i` makes closures recoverable. License descriptions don't say "bar"; mapped conservatively (QUESTIONS.md H-D9). Verified 2026-09-02 |
| *Planned:* **NYC DOHMH Child Care Center Inspections** `dsg6-ifza` | address | rolling | — | **$0** | Near-census of childcare by the restaurant-inspection logic. 3,014 centers. Build after the W2 map |
| *Planned:* **FDIC BankFind locations** | point | annual 1994– | — | **$0** | Census of bank branches; closures dated. Tier 4, low priority |
| *Planned:* **NYS registered pharmacies** | address | current | — | **$0** | Bulk access **unverified** — lookup site only. Check data.ny.gov before ticketing |
| **Google Places Nearby Search** | point | current | live | **~$32/1k** (Pro SKU); 5k/mo free | Ground truth for validation. **Budgeted: 3–5k calls ≈ $0–100** |

### 3.2 Longitudinal business panel

| Source | Geography | Temporal | Cost | Known bias |
|---|---|---|---|---|
| **LEHD LODES WAC** (LODES8) | **census block** | **annual 2002–2023** | **$0** | Counts *jobs*, not establishments. Census-applied noise infusion at block level. Excludes most self-employed |

This is the panel backbone. Target NAICS groups:
`4451` grocery · `4461` pharmacy · `7224` bars · `7225` restaurants · `8121` personal care ·
`8123` laundry/dry cleaning · `4441` hardware · `6244` childcare.

Two other panel routes were evaluated and **rejected**:
- *Overture / Foursquare historical* — snapshots only from ~2023. No backfill exists.
- *NYS DOS license reconstruction* — active-only file, so any "opening" series built from
  it is survivorship-biased by construction.

A third route, **DCWP license issue/expiry reconstruction**, is viable but expensive and is
deferred to Phase 5.

### 3.3 Outcome variables

| Source | Geography | Temporal | Cost | Known bias |
|---|---|---|---|---|
| **Census ACS 5-year** — population, households, income, tenure | tract | 2013–2024 | **$0** | 5-year smoothing damps recent change; tract-level MOEs are large and must be carried |
| **Zillow ZORI / ZHVI** | **ZIP** | monthly 2000– | **$0** | ZORI covers ~8.4k ZIPs nationally (a third of ZHVI's) — asking-rent index, listing-density dependent. ZIP is coarser than hex; requires crosswalk (§9) |
| **NYC DOB job filings + HPD Housing DB** | tax lot | annual | **$0** | Supply-side; responds to zoning changes more than to amenities. Permits ≠ completions |
| **IRS SOI county migration** | **county** | annual | **$0** | Only 5 units in NYC. **Too coarse — documented and dropped.** Recorded here so the exclusion is deliberate, not an oversight |
| *Planned:* **HUD aggregated USPS vacancy** | tract | quarterly 2005– | **$0** (registration) | Faster-moving than ACS 5-year, cleaner than permits. Candidate fifth outcome |

### 3.4 Controls and context

| Source | Purpose | Cost |
|---|---|---|
| **NYC MapPLUTO 26v1/26v2** | **Commercial zoning capacity — required control (§1.3).** Also `ResidFAR`/`BuiltFAR` for development capacity, `UnitsRes` as dasymetric ancillary, `YearBuilt` | **$0** |
| **MTA Subway Stations** `39hk-dx4f` / **Entrances & Exits** `68hr-j2j7` | Transit access. Entrances matter more than station centroids — a station can be 400 m of walking from its own far entrance | **$0** |
| **MTA Subway Hourly Ridership 2020–2024** `wujg-7c2s` | Transit *quality*, not mere presence. A station with 12 routes ≠ a station with one | **$0** |
| **OSM walk network** via OSMnx | Isochrone routing graph | **$0** |
| *Planned:* **MTA Bus GTFS stops** | Transit access beyond the subway — matters most in outer-borough hexes | **$0** |
| **NYC NTAs / Community Districts** | Human-legible reporting geography | **$0** |
| **NYC shoreline / borough boundaries** | Grid clipping | **$0** |

### 3.5 Budget

| | |
|---|---|
| Projected spend | **$0–100** |
| Stated budget | $100–500 |
| **Headroom** | **~$400** |

Everything except the Google validation sample is free. If the headroom is spent, spend it
in this order:

1. **Enlarge the Google validation sample** ($100–200). Directly strengthens P3, the
   prediction most likely to kill the project. Highest marginal value.
2. **Foot-traffic data** (SafeGraph/Placekey-class, $200–400). Would let the outcome shift
   from "did people move here" to "did people start going here," strengthening the causal
   half. Nice-to-have, not load-bearing.

---

## 4. Method

### 4.1 Grid construction

Engine: **DuckDB** with the `spatial` and community `h3` extensions, applied per
connection via `src/loci/sql/001_bootstrap.sql`. One caveat that matters for correctness: DuckDB
`GEOMETRY` carries **no SRID**. Everything stored is EPSG:4326 by convention and metric
work reprojects explicitly — the database will not catch a violation, so the convention
must be held in code.

H3 res 9 over the NYC boundary, clipped to shoreline. Water-only hexes dropped; partial
hexes retained with a `land_fraction` column used to normalize densities.

### 4.2 Demographics onto hexes

ACS tract variables → hexes via `tobler`, using **dasymetric** interpolation with PLUTO
`UnitsRes` (residential units per tax lot) as the ancillary surface. Plain areal weighting
would spread a tract's population uniformly across parks, rail yards and cemeteries; PLUTO
tells us where the housing actually is. This is strictly better and cheap, because PLUTO is
already being loaded for the zoning control.

Extensive variables (counts) apportioned; intensive variables (median income) assigned by
dominant-source weighting. ACS margins of error carried through, not discarded.

### 4.3 Access scoring — the performance-critical decision

**Do not compute ~7,400 isochrones.** For each of the 15 categories, run **one
multi-source Dijkstra** on the OSMnx walk graph, seeded simultaneously from every POI in
that category, cut off at the threshold distance. Every graph node within cutoff is
"served" by that category.

```
for category in 15 categories:
    dist = multi_source_dijkstra(walk_graph, sources=pois[category], cutoff=800m)
    served_nodes[category] = set(dist.keys())
```

A hex's category access is then (a) the population-weighted share of its graph nodes that
are served, and (b) the count of distinct POIs reachable from the hex's weighted centroid.

**15 graph traversals instead of 7,400 isochrone computations.** Minutes, not hours, and
it makes the 5/10/15-minute sensitivity sweep affordable (45 traversals total).

### 4.4 Daily Needs Completeness Index (DNCI)

Per category, a **saturating** score — the twelfth bodega is worth far less than the first:

```
s_c = 1 - exp(-n_c / k_c)
```

`k_c` is calibrated per category so that the first reachable establishment scores ≈0.55.
Essentials get `k ≈ 1.25` (one grocery is nearly sufficient); restaurants get a higher `k`
(one restaurant within a 10-minute walk is thin, not complete).

Categories combine by **weighted geometric mean**, not arithmetic:

```
DNCI = Π (s_c + ε)^(w_c)        ε = 0.01
```

**This is the methodological crux of the project.** An arithmetic mean lets a hex with
fifty restaurants and no grocery store, pharmacy or laundromat score well — which is
precisely the failure mode the thesis exists to detect. Only the geometric form punishes
zeros. A missing essential category should drag the whole index down, because in lived
experience it does.

`ε` prevents `log(0)` from annihilating the score entirely while preserving a severe
penalty.

### 4.4b Cross-source dedup (precision-first)

The POI base unions several sources, so the same establishment recurs (a salon in
Overture + NYS DOS + OSM). Counting duplicates inflates the DNCI wherever coverage
overlaps — and overlap is denser in richer/better-mapped areas, so it biases the residual.

Dedup runs **per category**: block candidates by H3 res-11 cell + neighbors, then merge any
pair within 40 m whose **distinctive** name tokens match (category-generic words like
"restaurant"/"pizza"/"nails" and corporate suffixes are stripped first — this both finds
true twins named differently across sources and keeps "Kennedy Fried Chicken" apart from
"Crown Fried Chicken"). One canonical per cluster, preferring the near-census anchor
(DOHMH for food, NYS DOS for salons).

**Deliberately precision-first.** In dense NYC blocks the *nearest* same-category POI is
usually a genuinely different business next door, so proximity-only merging would fuse
distinct establishments and **manufacture fake retail gaps — the one error this thesis must
never make**. Merging therefore requires a name match; the cost is some missed true
duplicates in dense areas, which the saturating DNCI (`1-exp(-n/k)`) largely absorbs — gaps,
where the finding lives, are where sources agree and dedup matters least. Measured collapse:
177,783 → 161,092 (9.4%); a spot-check of merged multi-source clusters showed no false merges.

### 4.5 The supply model and the residual

```
DNCI_h = f(pop_density, median_hh_income, transit_access,
           commercial_zoning_capacity, land_fraction, borough_FE) + u_h
```

`u_h` — the residual — is the signal. Strongly negative = **underserved relative to
comparable places**.

Commercial zoning capacity is non-negotiable in this specification. Without it, the
bottom of the residual distribution fills with park edges, industrial zones and
cemetery-adjacent blocks — places with no retail because retail is *not legal there* — and
the top-20 list becomes indefensible on first inspection.

**Spatial autocorrelation must be tested, not assumed away.** Compute Moran's I on `u_h`.
If significant (it almost certainly will be), re-estimate with a spatial error/lag model
(`pysal.spreg`) and report both. OLS standard errors on gridded urban data are otherwise
wrong.

**Opportunity Score** combines the residual with the capacity to act on it:

```
opportunity = (-u_h)⁺  ×  transit_access  ×  (ResidFAR - BuiltFAR)⁺
```

A hex must be underserved **and** transit-connected **and** have room to build.

### 4.6 The panel test

From LODES WAC, build annual per-hex retail employment 2002–2023 (block → hex via areal
apportionment). Main specification:

```
Δy_{h, t0→t1} = β·u_{h,t0} + γ'X_{h,t0} + α_borough + ε_h
```

with `y ∈ {log population, log households, log ZORI, permitted residential units}`,
t0 = 2013, t1 = 2023. **P2 predicts β < 0** (more negative residual → more growth).

Three checks the result must survive:

1. **Pre-trend test.** Estimate the same spec on 2003→2013. If `u_2013` also "predicts"
   the *prior* decade's growth, the parallel-trends assumption is broken and the causal
   reading is unavailable. Report it either way.
2. **Placebo outcome.** An outcome with no plausible mechanism (e.g. change in share of
   population aged 65+) should return a null. If it doesn't, the specification is picking
   up something generic about neighborhood trajectory.
3. **MAUP sweep.** Re-run at H3 res 8 and res 10. Report coefficient stability.

---

## 5. Visualization plan

Every view answers one named question. No chart without a question.

| View | Question | Encoding | Tech |
|---|---|---|---|
| H3 choropleth — **DNCI** | Where is the daily-needs bundle complete? | Sequential palette | MapLibre GL + **PMTiles** (static hosting, no server) |
| H3 choropleth — **residual** | Where is it *worse than it should be*? | **Diverging** — zero is meaningful | same tileset, layer toggle |
| **Bivariate: transit × residual** | Where do transit-rich and underserved overlap? | 3×3 bivariate palette | MapLibre |
| **Top-20 opportunity table** | Which specific places? | ranked, linked to map | HTML, map-linked |
| **Per-category radar, small multiples** | *What* is missing here — grocery, or salons? | 15-spoke radar per top hex | static SVG |
| **Scatter: residual@t0 vs. growth t0→t1** | Does P2 hold? | fitted line + CI, borough-colored | static |
| **Coverage-bias chart** | Does P3 hold? | POI undercount rate by income decile | static |
| **4–6 neighborhood evidence cards** | Does the mechanism look real on the ground? | narrative + inset map + photo | HTML |

**Palette rules:** sequential for DNCI; **diverging for the residual** (a zero residual is
a real midpoint, not an arbitrary one); bivariate for the overlap map. Load the `dataviz`
skill before writing any chart code.

The coverage-bias chart is not optional and not an appendix item. If the finding survives
it, that chart is the most persuasive thing in the deck.

---

## 6. Acceptance criteria

The project succeeds if **all four** hold.

**A. Statistically significant finding**
- [ ] `β` in the §4.6 main spec is signed as P2 predicts, `p < 0.05`
- [ ] Survives ≥3 robustness specifications (spatial error model, res 8/10, alternate t0)
- [ ] Placebo outcome returns a null
- [ ] Pre-trend test reported, and its implications stated honestly

**B. Named, checkable predictions**
- [ ] A top-20 ranked list of transit-rich, underserved hexes
- [ ] It passes the owner's own local-knowledge gut check
- [ ] It contains ≥3 genuine surprises — places not nameable in advance
- [ ] It contains **zero** park edges, industrial zones or cemetery blocks (a zoning-control failure)
- [ ] Each entry has a one-paragraph evidence card

**C. Working reusable tool**
- [ ] Fresh clone → `make nyc` → outputs in <30 min on a laptop
- [ ] `src/loci/score/` contains no NYC-specific column names or assumptions
- [ ] Pinned dependencies, documented data lineage, tests on the index math

**D. Communicable artifact**
- [ ] Public interactive map
- [ ] Methodology memo a skeptic can attack and the owner can defend
- [ ] 4–6 neighborhood evidence cards

---

## 7. Threats to validity

Ordered by how badly each could damage the finding. Do not soften these; the audience for
this project is an investment reader, and an unlisted threat found by the reader is worth
far less than a listed one.

### 7.1 POI measurement bias correlated with the outcome — **CRITICAL**

OSM and Overture undercount small businesses in lower-income and immigrant neighborhoods.
Those are **precisely the areas the thesis flags as underserved**. If the undercount is
strong there and weak in Park Slope, the project will *manufacture* its own finding: the
"retail gap" will be a data gap wearing a costume.

This single threat can invalidate everything. It is prediction P3.

**Mitigation:**
1. Stratified **Google Places validation sample** across income deciles — draw hexes at
   random within each decile, enumerate ground truth, measure the undercount rate per
   stratum. Budgeted, scheduled Week 4.
2. Use **DOHMH restaurant inspections as an unbiased anchor.** It is a near-census of food
   establishments, so within the food tier the true count is known. Calibrate the other
   tiers' expected undercount against the OSM-vs-DOHMH discrepancy per hex.
3. Report the undercount curve as a published chart (§5), whichever way it comes out.

### 7.2 Reverse causality and endogeneity
The residual formulation and temporal ordering *reduce* this; they do not eliminate it.
Unobserved neighborhood trajectory could drive both retail supply and residential growth.
No instrument is proposed within the 4-week scope (see §9). **State this plainly in the
memo rather than implying a cleaner identification than exists.**

### 7.3 Modifiable Areal Unit Problem (MAUP)
Results can shift with hex resolution and grid offset. *Mitigation:* re-run at res 8 and
res 10; report coefficient stability. If conclusions flip, say so.

### 7.4 LODES is jobs, not establishments — and pre-2020 years are retro-allocated
Two distinct problems, the second discovered 2026-09-01 and more serious than expected.

**(a) Jobs, not storefronts.** Ten-employee supermarkets and one-employee laundromats are
not comparable units. Census also applies noise infusion at block level. *Mitigation:*
document the proxy explicitly; validate the 2023 LODES cross-section against 2023
establishment counts from DOHMH/DCWP and report the correlation.

**(b) Pre-2020 years were stochastically re-allocated into 2020 blocks.** LODES8 puts every
year on 2020 blocks, which is convenient — but historical data got there by allocation, not
by observation. Per the Census OnTheMap 2020 Geography method: when a 2010 block splits,
each job is assigned to a child block **at random, with probability proportional to AREA
share** — *"Fractional job counts are not allowed"* — and the doc states plainly that
*"the allocation is a statistical process and may not result in a distribution of jobs that
exactly matches the areal distribution."*

Area-proportional allocation is a poor assumption in New York. A block that splits into a
park half and a commercial-strip half has its jobs spread by area, placing employment in
the park.

**Why this is bias and not merely noise:** the error is concentrated where blocks were
split, and blocks get split where development happened — which is the outcome variable.
The measurement error is therefore correlated with the thing being predicted.

*Mitigation:* H3 res 9 cells (~0.105 km²) are larger than most NYC census blocks, so
aggregation absorbs much of the within-neighborhood allocation error. That is an argument,
not a measurement — quantify the residual leakage across hex boundaries before trusting
pre-2020 panel values, and consider restricting the strongest claims to 2020+ observed data
with the earlier years as supporting evidence only.

### 7.5 Survivorship bias in license data
NYS DOS Appearance Enhancement is active-only. Never use it to construct openings/closings.
Snapshot enrichment only.

### 7.6 Zoning artifacts
Mitigated by the PLUTO commercial-capacity control. **Verification:** manually inspect the
top-20 list for park edges, industrial zones and cemeteries. Their presence means the
control failed.

### 7.7 Edge effects
Hexes on the shoreline and at borough boundaries have artificially small reachable areas —
half their walkshed is water. *Mitigation:* `land_fraction` normalization; extend the walk
graph beyond the city boundary so New Jersey and Westchester businesses are reachable where
they genuinely are.

### 7.8 ACS margins of error
Tract-level ACS estimates have wide MOEs, and they propagate through interpolation. Carry
them; do not silently treat point estimates as exact.

---

## 8. Phase plan

Four weeks, focused. Each week ends in something demoable — the schedule is designed so
that abandoning the project at any week boundary still leaves a usable artifact.

| Week | Work | Ships |
|---|---|---|
| **W1 — Ingest + grid** | DuckDB initialized; Overture, FSQ, DOHMH, DCWP, DOS loaded; H3 grid built and clipped; ACS dasymetrically interpolated; PLUTO + MTA loaded | Queryable database; first crude POI-density map |
| **W2 — Access engine** | OSMnx walk graph; multi-source Dijkstra scoring; `k_c` calibration; DNCI at 5/10/15 min | **The DNCI map** — first genuinely interesting artifact |
| **W3 — Residual + panel** | Zoning/transit controls; supply model; Moran's I + spatial model; LODES annual panel 2002–2023; growth regression; pre-trend and placebo | The empirical result and the top-20 list |
| **W4 — Artifact** | Google validation sample and coverage-bias chart; PMTiles export; charts; evidence cards; methodology memo; packaging | **The public artifact** |

**Phase 5 — deferred (post-week-4)**
- DCWP license issue/expiry establishment-level panel reconstruction
- Second-city generalization: extract `sources/universal/` behind a stable interface,
  run `loci run --city chicago`
- Foot-traffic outcome, if budget headroom is spent

---

## 9. Open questions and deferred decisions

> This table holds *decisions* still to be made. The project's **research questions** — what
> it is trying to find out, tiered by rigor and mapped to tickets — live in
> [`docs/QUESTIONS.md`](QUESTIONS.md), together with the pre-build homework list.

| # | Question | Current position | Decide by |
|---|---|---|---|
| 1 | **Tier weights** (0.40 / 0.20 / 0.25 / 0.15) are judgment, not derived. | Stated explicitly so a reader can disagree precisely. Run sensitivity across plausible weightings and report whether the top-20 is stable. | W3 |
| 2 | **`k_c` calibration** per category | Anchor at "first establishment ≈ 0.55", tune essentials tighter than food. Revisit against observed count distributions. | W2 |
| 3 | **Staten Island inclusion.** Low density and car-oriented; may act as leverage in the supply model. | Include, but check Cook's distance; report with and without. | W1 |
| 4 | **ZORI ZIP → hex crosswalk.** ZIP is much coarser than hex. | Population-weighted apportionment; treat rent as the weakest of the four outcomes and say so. | W3 |
| 5 | **LODES block vintage.** | **RESOLVED 2026-09-01 — no crosswalk needed.** LODES8 tech doc §Geography Vintage: *"The data are enumerated with 2020 census blocks. LODES Version 7 and 6 used 2010 census blocks."* All 22 NY vintages (2002–2023) confirmed present. Corroborated empirically: 5,328 of 5,334 tracts present in the 2002 file are also in 2023. **But see the new caveat in §7.4 — historical years were retro-allocated, and that allocation is not innocent.** | settled |
| 6 | **DCWP dataset freshness.** | **RESOLVED 2026-09-01 — not stale** (rowsUpdatedAt 2026-08-20). But a bigger problem surfaced: DCWP has no consumer laundromats at all (active "Laundries" = 0; only industrial linen suppliers), so it contributes nothing to the bundle regardless of freshness. Laundromats come from OSM/Overture. | settled |
| 7 | **No instrument for §7.2.** | Out of scope at 4 weeks. Candidate for Phase 5: historic zoning changes or L-train-shutdown-style shocks as quasi-experimental variation. | Phase 5 |
| 8 | **PostGIS vs. DuckDB.** At ~7,400 hexes and ~400k POIs the workload fits comfortably in DuckDB. | **Settled: DuckDB.** Originally PostGIS for a hypothetical service path, but the only available image ran emulated (amd64 on arm64) and the service path is speculative. DuckDB removes the container, the daemon and the emulation penalty, and its `spatial` + community `h3` extensions cover every operation the method needs. Revisit only if Loci genuinely becomes a service. | settled 2026-09-01 |

---

## 10. Architecture note — portability

The project is **NYC-first**: NYC-only sources (DOHMH, DCWP, NYS DOS, PLUTO, MTA) are used
because they are the best data available and defensibility is the priority.

But "NYC-first" is a data decision, not a code decision. To keep the v2 generalization
reachable:

- City-specific loaders live **only** in `src/loci/sources/cities/nyc/` behind a common
  adapter interface.
- Nationally-available sources live in `src/loci/sources/universal/` (Overture, LODES, ACS,
  OSM network, GTFS, Zillow).
- **`src/loci/score/` and `src/loci/model/` contain no NYC-specific column names or assumptions.**
  They consume the normalized schema, not raw source columns.

This costs roughly half a day now. Without it, the "generalize later" refactor is the one
that never happens.

---

## 11. Premium amenities — the destination-amenity axis (Axis 3)

*Added 2026-09-02 at the owner's request. This is a third analytical axis, parallel to
Axis 1 (Investability, `model/invest.py`) and Axis 2 (Rising trajectory, `model/rising.py`),
and like them it is **not** a return to the rejected residual-growth thesis (§0 / D1).*

### 11.1 The question

Where in NYC could a **premium, destination amenity** open and be underserved today —
starting with **padel courts** and **spa / wellness studios**? The owner's premise: people
will travel materially longer for these than for daily needs, *and there is still
opportunity* — i.e. real catchments of qualifying demand with no nearby supply.

### 11.2 Why this inverts the daily-needs gap screen (do not reuse it)

The daily-needs bundle (§2.1) and the present-day gap screen work because those are
**convenience goods**: consumed often, near-zero willingness to travel, so the relevant
geography is the 800 m walk and a category counts as a conspicuous gap when it is present in
≥80% of walkable peers yet absent here. Premium amenities behave oppositely on both axes:

| | Daily needs | Premium amenities |
|---|---|---|
| Trip frequency | daily / weekly | occasional |
| Willingness to travel | ~800 m walk | 15–30 min drive or transit |
| Prevalence | common (the screen needs ≥80%) | **rare by nature** |
| Right geography | walkable hex | **travel-time catchment / trade area** |
| Right screen | missing what peers have | **demand pool minus supply, over the catchment** |

A prevalence-gap screen applied to padel would flag almost the whole city and mean nothing,
because almost nowhere has one. So Axis 3 uses a **classic trade-area / gravity
site-selection model** instead: find a travel-time catchment with enough *qualifying premium
demand* but little or no supply reachable inside it, and a feasible large-format site.

### 11.3 Method sketch

1. **Bundle** (judgment, tunable — a `PREMIUM` dict mirroring `invest.py`'s `ECON`): padel and
   spa/day-spa as the named anchors, extended to the destination-amenity family that shares
   the travel-for-it behavior — med-spa, pilates/reformer, boutique fitness/boxing, climbing
   gym, bathhouse/sauna, golf & sports simulator. Each kept as its own category (catchment,
   demand target and site footprint all differ).
2. **Supply** — a new POI layer outside the 15: OSM (`sport=padel`, `leisure=spa`,
   `sport=climbing`…), Foursquare leaves (Spa, Pilates Studio, Climbing Gym…), Google for
   ground truth. **Google validation is load-bearing here, not optional** — padel barely
   existed before 2022 and studios open fast, so the snapshot undercount is severe and
   uneven; a padel "gap" is more likely a data gap than a daily-needs gap is (§7.1, worse).
3. **Demand** — a *premium demand pool*, not raw population: population weighted toward top
   income deciles, the category's target age band, and college share (already computed in
   `model/momentum.py`, corr 0.72 with income — D20). Per-category demand target.
4. **Catchment** — per-amenity **drive-time ∪ transit-time isochrones** (default 15 min),
   the load-bearing choice. Willingness-to-travel is assumed, not measured, so sweep
   10/15/20/30 min and report how the ranking moves — the sensitivity is the honesty.
5. **Feasibility** — the `invest.py` gate re-tuned for large formats: lot size + floorplate +
   a zoning district permitting commercial recreation / personal-service, plus
   vacancy/industrial-conversion candidates. A padel court needs ~1,000+ m² and height, not a
   ground-floor retail bay. Without this the screen recommends sites that physically or
   legally cannot host the use — the §7.6 zoning-artifact failure in a new costume.
6. **Deliverable** — `opportunity = qualifying demand in catchment − supply reachable in
   catchment`, gated on a feasible site, ranked per amenity; and a map layer **"Where could a
   padel court / spa go?"** — catchments shaded by unmet premium demand, feasible sites pinned.

### 11.4 Axis-specific threats

- **Supply undercount is worse than §7.1**, and concentrated in the newest categories. Every
  top site must survive Google + a manual web check or it is presumed a data gap.
- **Willingness-to-travel is assumed.** The catchment radius is the biggest single lever;
  report every ranking under the travel-time sweep, never a single radius.
- **Demand ≠ income alone.** Matching the demographic to the specific amenity (padel: affluent,
  athletic, 25–44; med-spa: affluent women 30–55) is judgment and must be stated per category.
- **Chain pipeline.** A "gap" may already be under LOI by a national operator (Life Time,
  Equinox, Padel Haus…). Outside the data; flagged as manual diligence per top pick.

---

## 12. Maturity curve and 2033 projection (Axis 4)

*Added 2026-09-02 at the owner's request: (1) where is each neighborhood on its maturity curve,
and (2) where could growth get to by 2033, and how would we project it. This is the **forward
extension of Axis 2 (Rising)**.*

### 12.1 Reconcile with §0 first — this is not the rejected thesis

The project's central result (§0 / D1) is that **"the retail gap at t0 predicts subsequent
residential growth"** failed: β was wrong-signed (+0.069), and the pre-trend test broke parallel
trends. That causal arrow — *retail undersupply causes growth* — stays **dead**, and this axis
never uses the retail residual as a growth predictor.

What is being asked is a **different** thing, and it is legitimate:

- **Maturity (descriptive).** Locate each neighborhood on a development S-curve *from its own
  observed multi-metric history* — income, college share, rent, permits, jobs. This is a
  positioning statement about the present, not a causal claim.
- **Projection (extrapolative).** Extend that trajectory to 2033. The very pre-trend finding that
  sank the causal thesis — *these neighborhoods are on a development cycle* — is what **licenses
  extrapolation**: a place already moving along the frontier tends to keep moving. That is
  forecasting from momentum, not inferring causation from a gap.

The discipline that keeps this honest is threefold: (a) the retail signal is the **dependent**
read, re-scored against projected demand at the very end, never an input to the projection; (b) the
output is **scenario bands**, never a point forecast, because trajectories bend (D21 already caught
East New York rents cooling to +1.9%/yr post-2022); (c) it ships as a forecast **only if it passes
a backtest** (§12.4).

### 12.2 The maturity curve

Stage is defined by **level *and* rate *and* acceleration** (1st and 2nd derivative) of the panel
metrics — not level alone. That distinction is the whole point: it is what separates a maturity
model from a static wealth map. A high-income but *decelerating* neighborhood is *maturing*;
high-income and still *accelerating* is *rising*.

| Stage | Signature | NYC exemplar (from D20/D21) |
|---|---|---|
| Pre-frontier / dormant | low level, flat momentum, no pipeline | deep outer-borough |
| **Emerging** | income accelerating, college still low, first permits | **East New York** (+42% income, college only 9→14%) |
| **Rising** | income + college both climbing fast, rent + permit boom | Crown Heights / Ocean Hill recently |
| **Maturing** | high level, growth decelerating | Williamsburg now |
| **Mature / saturated** | high level, flat or declining | the 5 rich Manhattan NTAs in real decline |

Spatial adjacency to the already-risen frontier is a feature — gentrification diffuses to
neighbors, which is also the mechanism behind the projection.

### 12.3 Projecting to 2033

Three complementary reads, reported together:

1. **Frontier diffusion (spatial, most communicable).** The frontier is a datable wave —
   Williamsburg → Bed-Stuy → Bushwick → Crown Heights → Ocean Hill → East New York (D20). Measure
   its pace (blocks/decade); the not-yet-risen neighborhoods adjacent to today's rising edge are
   the mechanistic next steps, and the pace sets how far it reaches by 2033.
2. **Per-metric logistic extrapolation.** Fit each metric's trajectory with a **logistic
   (saturating)** form, not linear — a neighborhood cannot gentrify past 100%, and linearly
   extrapolating a hot decade is the classic forecasting error.
3. **Stage-transition (Markov) roll-forward.** Estimate P(stage→stage per decade) from the
   historical panel, advance each NTA one step to 2033, giving a probabilistic stage.

Plus an **analogue read** for interpretability: for each emerging NTA, the already-matured NTA it
most resembles at the same stage (is 2023 East New York ≈ 2011 Bushwick?), and that analogue's
realized path as a concrete forecast. Everything is reported as **continued-diffusion / stall /
reversal** scenario bands.

### 12.4 The load-bearing check — backtest, or it is astrology

Fit the classifier and projection on data **through 2013 only**, project 2013→2023, and compare to
what actually happened. If the model cannot retrodict the Bushwick / Crown Heights / East New York
arc, it cannot forecast 2033, and the memo says so. Report out-of-sample error by stage (emerging
neighborhoods are the hardest and the most important). This is the Axis-4 analogue of E3's
pre-trend/placebo rigor, and it gates whether the 2033 numbers ship as a forecast or only as a
scenario illustration.

### 12.5 Data

momentum.py (D20) pulled only two time points. This axis needs a real per-NTA time series:
decennial 2000/2010 + ACS 5-yr 2009/2013/2018/2023 (real income, college, tenure, age), LODES
2002–2023 (in hand), Zillow 2000– (D21), DOB/HPD permits by year — all deflated to real dollars and
aggregated to 2020 NTAs. Assembled once as `analysis.nta_trajectory`, feeding both the classifier
and the projection.
