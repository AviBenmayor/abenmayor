# Loci — portability: what a second city has to publish

**GENERATED — do not edit.** Rendered by `loci gen-portability` from the `portability:` blocks in [`src/loci/registry.yaml`](../src/loci/registry.yaml) and the grade config in [`src/loci/model/recommend_grades.yaml`](../src/loci/model/recommend_grades.yaml). `loci check-sources` fails if this file differs from a fresh render.

Owner ask, 2026-09-14: *"what are the critical inputs necessary to be able to expand the model to new cities."* This is the machine-checked answer. Nothing below has been ingested for any city other than New York — §6 is a portal survey dated 2026-09-14, not a pipeline.

---

## 1. The registry by portability class

`class` answers *where can a second city get this*, and it is deliberately not the same question as `tier`. A `city`-tier source is usually **not** unique to the city: another city publishes the same fact under a different schema. Only 6 rows in the registry have no equivalent anywhere else.

| Class | n | What it means for a second city |
|---|---|---|
| **universal** | 7 | Works on day one, anywhere on earth. Nothing to procure. |
| **national (US federal)** | 10 | Works on day one in any US city. Carries its own portable bias. |
| **state** | 6 | Re-plumbed per state. Publication quality varies enormously; expect some states to publish nothing usable. |
| **city open data (different schema)** | 15 | An equivalent exists but the schema is different. This is the real cost of a second city: an adapter per source. |
| **city-unique (no equivalent exists)** | 6 | No equivalent exists. The stage degrades, permanently — see §4. |

**44 sources classed.** 17 of them (39%) need no per-city work at all.

**17 of the 44 classifications are judgement calls** (`confidence: med` or `low`) and carry a note saying what the uncertainty is. They are listed with their notes in §6.

---

## 2. By pipeline stage

A source's `feeds` list is the set of stages that stop working without it. Rows are ordered most-portable class first, so the bottom of each table is the part a second city has to solve.

### `universe`

The sampling frame. `analysis.address` is *PLUTO lots where UnitsRes > 0*, plus the D84
street-midpoint frame. Nothing downstream exists without it.

| Source | Class | Without it |
|---|---|---|
| NYC borough boundaries, shoreline, and Neighborhood Tabulation Areas | city open data (different schema) | No human-legible reporting geography and no shoreline clip; Census places and tracts substitute, at the cost of NTA-grain reporting. |
| NYC Street Centerline (CSCL) | city open data (different schema) | The D84 street frame is lost and the universe reverts to residential lots only, so commercial corridors with no housing above them stop being sampled. |
| NYC MapPLUTO (Primary Land Use Tax Lot Output) | city-unique (no equivalent exists) *(med conf.)* | The screen has no sampling frame. analysis.address IS 'PLUTO lots WHERE UnitsRes > 0', so without it there is no universe, no dasymetric ancillary, no commercial zoning capacity control (required by CONTEXT 1.3), and no retail floor area for D82 character or the D91 capacity ceiling. |

**Stage `universe` depends on 1 city-unique source** — NYC MapPLUTO (Primary Land Use Tax Lot Output). It cannot be reproduced at full strength anywhere else.

### `walk_graph`

The OSM walk network. Every distance in Loci — the 800 m category threshold, every 400 m
catchment, the measured 1.233 circuity behind D53's validation radius — is a network
distance on this graph.

| Source | Class | Without it |
|---|---|---|
| OSM pedestrian network via OSMnx | universal | Everything reverts to straight-line radii: the 800 m network threshold, the measured 1.233 circuity used to set the D53 validation radius, and every 400 m catchment stop being walk distances. This is the most load-bearing portable input in the registry. |
| NYC Street Centerline (CSCL) | city open data (different schema) | The D84 street frame is lost and the universe reverts to residential lots only, so commercial corridors with no housing above them stop being sampled. |

### `poi_supply`

`staging.poi` → dedup → the D52/D59 principled supply set. The count the whole screen is
about.

| Source | Class | Without it |
|---|---|---|
| Foursquare Open Source Places | universal | Loses the second independent aggregator, so D11's corroborated-only supply set collapses to single-source and single-source inflation stops being detectable. |
| Google Places API — Nearby Search | universal | No independent ground truth: the CONTEXT 7.1 coverage-bias audit cannot be run and the card's coverage section can never reach A (recommend_grades validated_grade). |
| OpenStreetMap (Overpass API) | universal | Loses the third POI opinion and the tag vocabulary of record; category mapping has to be rebuilt against whatever taxonomy the surviving vendor uses. |
| Overture Maps Places | universal | No global POI base layer: supply counts rest on city registries alone, and the six bundle categories with no qualifying registry anchor go dark entirely. |
| FDIC BankFind Locations (Summary of Deposits) | national (US federal) | Bank branch counts revert to aggregators, and dated closures -- the only closure series Loci has for any category -- are lost. |
| USDA SNAP Retailer Locator | national (US federal) | Grocery and bodega/convenience lose their near-census anchor -- the tier-1 weight 0.40 categories -- and the screen's most load-bearing counts become aggregator counts. |
| Active NYC Health Code Regulated Child Care Programs | state *(med conf.)* | Childcare returns to the pre-D65 state: coverage 0.85 -> ~0.00, and Borough Park-type aggregator blind spots read as deserts rather than as under- coverage. |
| NYS Active Appearance Enhancement and Barber Business Licensees | state | Hair/barber and nail/beauty lose their state roster and fall back to aggregators, which is where the 7.1 immigrant-neighbourhood undercount bites hardest. |
| NYS Medicaid Enrolled Provider Listing — retail pharmacies | state *(low conf.)* | Pharmacy coverage falls 0.90 -> 0.00 and pharmacy gaps become unmeasurable -- the single largest coverage cliff in the registry. |
| NYS Office of Professions — registered pharmacies | state | Nothing. Bulk access was verified absent 2026-09-11; the entry exists so the exclusion is not relitigated. |
| NYS Liquor Authority Current Active Licenses | state | Bar loses its anchor and the alcohol map overlay disappears; bar supply reverts to aggregators, which over-count bars relative to every other category. |
| NYC DCWP Inspections (Retail Laundry / Dry Cleaners) | city open data (different schema) *(med conf.)* | Laundry loses its only anchor and reverts to aggregator coverage -- the weakest category in POI data, because a laundromat has no check-in history. |
| NYC DCWP Legally Operating Businesses | city open data (different schema) | Loses the E5 licence-history panel. No effect on the bundle count -- D55 found it contributes essentially nothing to the fifteen categories. |
| DOHMH New York City Restaurant Inspection Results | city open data (different schema) | Restaurant, cafe and bar lose their near-census anchor: those three categories revert to aggregator coverage and the CONTEXT 7.1 undercount becomes unmeasurable. |

### `demand`

Who is here and who is arriving: ACS, LODES jobs, PLUTO units, and the residential
development pipeline.

| Source | Class | Without it |
|---|---|---|
| Census American Community Survey, 5-year estimates | national (US federal) | No income, tenure, age or household size: the supply baseline loses its controls, so a thin count can no longer be separated from a poor one, and demand_now is ungraded. |
| Citi Bike System Data (trip files) | national (US federal) *(med conf.)* | The only two-directional movement series in the registry is lost: demand keeps subway ENTRIES, which publish the morning tap-in and never the evening arrival, and which read zero for 65% of Brooklyn addresses -- so `bike_ends_400m`, the only arrival-side measure Loci has, cannot be built and the destination-versus- commuter reading of a corner goes back to being an assumption. |
| HUD aggregated USPS vacancy data | national (US federal) | No independent residential vacancy series, so the residential half of vacancy rests on ACS 5-year smoothing alone. |
| IRS SOI county-to-county migration | national (US federal) | Nothing. Five units citywide is too coarse for any stage; recorded so the exclusion stays deliberate. |
| LEHD LODES Workplace Area Characteristics (LODES8) | national (US federal) | jobs_400m disappears: the daytime half of demand is gone and the character model loses one of its three witnesses for corporate vs retail. |
| Zillow Observed Rent Index / Home Value Index | national (US federal) | No rent index, so affordability context on the card is asserted rather than measured. ZIP grain means it was never load-bearing. |
| NYC DCP Housing Database — Project-Level Files | city open data (different schema) *(med conf.)* | The arriving-homes spine is gone, so recommend_grades' null_grade fires: arriving_homes grades D and, being load-bearing, the whole card reads 'do not act'. |
| NYC DOB Certificates of Occupancy (BIS + DOB NOW) | city open data (different schema) *(med conf.)* | The pipeline loses its freshness supplement: 11,407 MN+BK net units that already hold a CO keep reading 'permitted', overstating the forward pipeline. |
| NYC DOB Permit Issuance + DOB NOW Approved Permits | city open data (different schema) *(med conf.)* | The construction-activity axis collapses: active / lapsed / stalled cannot be computed, arriving_homes falls to its null_grade D, and every card reads 'do not act'. |
| NYC Energy and Water Data Disclosure (Local Law 84 / LL133) | city open data (different schema) *(med conf.)* | In-building laundry evidence is lost, so the laundry haircut falls back to priors: addressable_demand drops from A to its prior_grade B for the one category that has a haircut at all. |
| NYC MapPLUTO (Primary Land Use Tax Lot Output) | city-unique (no equivalent exists) *(med conf.)* | The screen has no sampling frame. analysis.address IS 'PLUTO lots WHERE UnitsRes > 0', so without it there is no universe, no dasymetric ancillary, no commercial zoning capacity control (required by CONTEXT 1.3), and no retail floor area for D82 character or the D91 capacity ceiling. |
| StreetEasy listing pages (advertised in-building laundry, via Tavily) | city-unique (no equivalent exists) *(med conf.)* | Laundry evidence coverage drops below recommend_grades' evidence_coverage_a of 0.50, so addressable_demand for laundry falls from A to the prior_grade B. |

**Stage `demand` depends on 2 city-unique sources** — NYC MapPLUTO (Primary Land Use Tax Lot Output), StreetEasy listing pages (advertised in-building laundry, via Tavily). It cannot be reproduced at full strength anywhere else.

### `lifecycle`

The D80 storefront filing stages — liquor application, fit-out filing, licence
application, first inspection — rolled up per address.

| Source | Class | Without it |
|---|---|---|
| NYS SLA Current Pending Licenses | state *(med conf.)* | The earliest go-live signal is lost: the pipeline starts at fit-out filing instead of at the signed lease, costing roughly a quarter of forward visibility for bars. |
| NYS Liquor Authority Current Active Licenses | state | Bar loses its anchor and the alcohol map overlay disappears; bar supply reverts to aggregators, which over-count bars relative to every other category. |
| NYC DCWP License Applications | city open data (different schema) *(med conf.)* | Loses the best name-bearing early signal for the non-alcohol trades -- the fit-out feed names the landlord, not the operator, so nothing replaces it. |
| NYC DCWP Legally Operating Businesses | city open data (different schema) | Loses the E5 licence-history panel. No effect on the bundle count -- D55 found it contributes essentially nothing to the fifteen categories. |
| DOB NOW: Build - Job Application Filings | city open data (different schema) *(med conf.)* | The fit-out stage disappears from the storefront pipeline, which is the only stage that sees the ten filing-blind categories at all before they open. |
| NYC DOB Permit Issuance + DOB NOW Approved Permits | city open data (different schema) *(med conf.)* | The construction-activity axis collapses: active / lapsed / stalled cannot be computed, arriving_homes falls to its null_grade D, and every card reads 'do not act'. |
| DOHMH New York City Restaurant Inspection Results | city open data (different schema) | Restaurant, cafe and bar lose their near-census anchor: those three categories revert to aggregator coverage and the CONTEXT 7.1 undercount becomes unmeasurable. |
| NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019) | city-unique (no equivalent exists) | No storefront-vacancy layer: the card's space section grades D everywhere, the 'and this ground floor 120 m away is empty' sentence disappears, and the D88 go-dark retrodiction has no outcome variable at all. |

**Stage `lifecycle` depends on 1 city-unique source** — NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019). It cannot be reproduced at full strength anywhere else.

### `ledger`

`analysis.poi_presence` (D79): the month Loci first and last SAW each storefront,
independent of whether any source publishes an open date.

| Source | Class | Without it |
|---|---|---|
| Foursquare Open Source Places | universal | Loses the second independent aggregator, so D11's corroborated-only supply set collapses to single-source and single-source inflation stops being detectable. |
| OpenStreetMap (Overpass API) | universal | Loses the third POI opinion and the tag vocabulary of record; category mapping has to be rebuilt against whatever taxonomy the surviving vendor uses. |
| Overture Maps Places | universal | No global POI base layer: supply counts rest on city registries alone, and the six bundle categories with no qualifying registry anchor go dark entirely. |
| USDA SNAP Retailer Locator | national (US federal) | Grocery and bodega/convenience lose their near-census anchor -- the tier-1 weight 0.40 categories -- and the screen's most load-bearing counts become aggregator counts. |
| Active NYC Health Code Regulated Child Care Programs | state *(med conf.)* | Childcare returns to the pre-D65 state: coverage 0.85 -> ~0.00, and Borough Park-type aggregator blind spots read as deserts rather than as under- coverage. |
| NYS Medicaid Enrolled Provider Listing — retail pharmacies | state *(low conf.)* | Pharmacy coverage falls 0.90 -> 0.00 and pharmacy gaps become unmeasurable -- the single largest coverage cliff in the registry. |
| NYS Liquor Authority Current Active Licenses | state | Bar loses its anchor and the alcohol map overlay disappears; bar supply reverts to aggregators, which over-count bars relative to every other category. |
| NYC DCWP Inspections (Retail Laundry / Dry Cleaners) | city open data (different schema) *(med conf.)* | Laundry loses its only anchor and reverts to aggregator coverage -- the weakest category in POI data, because a laundromat has no check-in history. |
| DOHMH New York City Restaurant Inspection Results | city open data (different schema) | Restaurant, cafe and bar lose their near-census anchor: those three categories revert to aggregator coverage and the CONTEXT 7.1 undercount becomes unmeasurable. |

### `character`

D82 — retail vs corporate vs industrial vs residential, as an upper envelope of three
witnesses (PLUTO floor area, jobs, POI mix).

| Source | Class | Without it |
|---|---|---|
| LEHD LODES Workplace Area Characteristics (LODES8) | national (US federal) | jobs_400m disappears: the daytime half of demand is gone and the character model loses one of its three witnesses for corporate vs retail. |
| NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019) | city-unique (no equivalent exists) | No storefront-vacancy layer: the card's space section grades D everywhere, the 'and this ground floor 120 m away is empty' sentence disappears, and the D88 go-dark retrodiction has no outcome variable at all. |
| NYC MapPLUTO (Primary Land Use Tax Lot Output) | city-unique (no equivalent exists) *(med conf.)* | The screen has no sampling frame. analysis.address IS 'PLUTO lots WHERE UnitsRes > 0', so without it there is no universe, no dasymetric ancillary, no commercial zoning capacity control (required by CONTEXT 1.3), and no retail floor area for D82 character or the D91 capacity ceiling. |

**Stage `character` depends on 2 city-unique sources** — NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019), NYC MapPLUTO (Primary Land Use Tax Lot Output). It cannot be reproduced at full strength anywhere else.

### `transit`

Stations, entrances and ridership. D76's `transit_entries_400m` is the only foot-traffic
proxy in the free registry.

| Source | Class | Without it |
|---|---|---|
| MTA Bus GTFS static (stops) | universal | Transit access is subway-only. In NYC that is survivable; in a city where the bus IS the network it would make the transit stage meaningless. |
| MTA Subway Entrances and Exits 2024 | city open data (different schema) *(low conf.)* | Walk distance is measured to the station CENTROID instead of the entrance, which overstates access at large complexes by up to a 400 m walk -- the exact error the entrance file exists to remove. |
| MTA Subway Stations | city open data (different schema) | Station points come from GTFS stops instead -- a clean substitution, since GTFS is the universal fallback and carries the same geometry. |
| MTA Subway Hourly Ridership 2020-2024 | city-unique (no equivalent exists) | Transit becomes PRESENCE rather than QUALITY: a twelve-route complex and a one-route stop score identically. |
| MTA Subway Hourly Ridership: Beginning 2025 | city-unique (no equivalent exists) | transit_entries_400m cannot be built, which removes the only foot-traffic proxy in the whole registry (D76) and leaves the card with no daypart signal. |

**Stage `transit` depends on 2 city-unique sources** — MTA Subway Hourly Ridership 2020-2024, MTA Subway Hourly Ridership: Beginning 2025. It cannot be reproduced at full strength anywhere else.

### `validation`

Is the measured gap real or a coverage artefact (CONTEXT §7.1)? Google ground truth, ZBP
establishment counts, DOT sidewalk counts, the D88 retrodiction.

| Source | Class | Without it |
|---|---|---|
| Google Places API — Nearby Search | universal | No independent ground truth: the CONTEXT 7.1 coverage-bias audit cannot be run and the card's coverage section can never reach A (recommend_grades validated_grade). |
| Strava Metro (street-segment activity counts) | universal | Loses a crowd-sourced movement second opinion. Never load-bearing -- it is cycling- and fitness-selected, and access is gated on an application. |
| Census County Business Patterns (CBP), national -- counties, metros and ZIPs | national (US federal) | The carrying-capacity comparison loses its only external frame: NYC's establishments-per-resident can still be measured but not placed against any other metro, so "is this rate high" has no answer and no second city can be chosen on evidence. |
| Census ZIP Code Business Patterns (ZBP), via the County Business Patterns (CBP) API | national (US federal) | No external establishment-count benchmark, so anchor coverage ratios (the 0.85 / 0.90 numbers that justified the childcare and pharmacy anchors) cannot be computed. |
| Citi Bike System Data (trip files) | national (US federal) *(med conf.)* | The only two-directional movement series in the registry is lost: demand keeps subway ENTRIES, which publish the morning tap-in and never the evening arrival, and which read zero for 65% of Brooklyn addresses -- so `bike_ends_400m`, the only arrival-side measure Loci has, cannot be built and the destination-versus- commuter reading of a corner goes back to being an assumption. |
| HUD aggregated USPS vacancy data | national (US federal) | No independent residential vacancy series, so the residential half of vacancy rests on ACS 5-year smoothing alone. |
| DOHMH New York City Restaurant Inspection Results | city open data (different schema) | Restaurant, cafe and bar lose their near-census anchor: those three categories revert to aggregator coverage and the CONTEXT 7.1 undercount becomes unmeasurable. |
| NYC DOT Bi-Annual Pedestrian Counts | city open data (different schema) *(med conf.)* | The access proxies (transit_entries_400m, jobs_400m, homes_400m) lose their only external check, so the D76 rank correlation cannot be computed and the proxy stays an assumption. |
| NYC DOT traffic cameras (NYCTMC public feed) | city open data (different schema) *(med conf.)* | The frame-sampler route to a measured footfall number closes; nothing else in the free registry can produce a person count. |
| NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019) | city-unique (no equivalent exists) | No storefront-vacancy layer: the card's space section grades D everywhere, the 'and this ground floor 120 m away is empty' sentence disappears, and the D88 go-dark retrodiction has no outcome variable at all. |
| NYC DOT VivaCity sidewalk sensors (data-sharing ask) | city-unique (no equivalent exists) *(med conf.)* | No continuous sidewalk sensor, so counts stay biannual seven-hour snapshots and no daypart validation is possible. |

**Stage `validation` depends on 2 city-unique sources** — NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019), NYC DOT VivaCity sidewalk sensors (data-sharing ask). It cannot be reproduced at full strength anywhere else.

### `chains`

The D77 growing-chain watchlist — whether somebody is already moving toward the gap.

| Source | Class | Without it |
|---|---|---|
| Foursquare Open Source Places | universal | Loses the second independent aggregator, so D11's corroborated-only supply set collapses to single-source and single-source inflation stops being detectable. |
| Overture Maps Places | universal | No global POI base layer: supply counts rest on city registries alone, and the six bundle categories with no qualifying registry anchor go dark entirely. |

---

## 3. The minimum input set, by evidence grade

`recommend_grades.yaml` grades each claim on its own evidence and the verdict is the
MINIMUM over the load-bearing sections — a chain is as strong as its weakest link. So
the question "what does a second city need" only has an answer once you say *to reach
what verdict*. Load-bearing sections: `arriving_homes`, `supply_thinness`,
`addressable_demand`, `economics`, `coverage`. Context sections (`demand_now`, `space`)
describe the site and can never block a verdict.

### Grade B — verdict *"act"*

**Not reachable on open data — in any city, New York included.** `economics` can only
reach grade B through a PAID input (see docs/PAID-SOURCES.md). This is not a portability
problem: it is the same wall NYC is standing at today, and no second city changes it.

| Section | Ceiling | What buys it |
|---|---|---|
| `arriving_homes` | B | NYC DCP Housing Database — Project-Level Files; NYC DOB Permit Issuance + DOB NOW Approved Permits; NYC DOB Certificates of Occupancy (BIS + DOB NOW) |
| `supply_thinness` | A | NYC MapPLUTO (Primary Land Use Tax Lot Output); NYC Street Centerline (CSCL); OSM pedestrian network via OSMnx; Overture Maps Places; Foursquare Open Source Places; OpenStreetMap (Overpass API) |
| `addressable_demand` | B | NYC MapPLUTO (Primary Land Use Tax Lot Output) |
| `economics` | B | ≥5 same-category business-sale comps at borough grain, WITH cash flow |
| `coverage` | B | DOHMH New York City Restaurant Inspection Results; USDA SNAP Retailer Locator; NYS Liquor Authority Current Active Licenses; NYC DCWP Inspections (Retail Laundry / Dry Cleaners); Active NYC Health Code Regulated Child Care Programs; NYS Medicaid Enrolled Provider Listing — retail pharmacies; NYS Active Appearance Enhancement and Barber Business Licensees |

**Minimum set for grade B: 16 sources plus 1 non-registry requirement.**

- `foursquare_os_places` — Foursquare Open Source Places (universal)
- `nyc_cscl` — NYC Street Centerline (CSCL) (city open data (different schema))
- `nyc_dcp_housing_db` — NYC DCP Housing Database — Project-Level Files (city open data (different schema))
- `nyc_dcwp_inspections` — NYC DCWP Inspections (Retail Laundry / Dry Cleaners) (city open data (different schema))
- `nyc_dob_certificates_of_occupancy` — NYC DOB Certificates of Occupancy (BIS + DOB NOW) (city open data (different schema))
- `nyc_dob_permit_issuance` — NYC DOB Permit Issuance + DOB NOW Approved Permits (city open data (different schema))
- `nyc_dohmh_childcare` — Active NYC Health Code Regulated Child Care Programs (state)
- `nyc_dohmh_restaurants` — DOHMH New York City Restaurant Inspection Results (city open data (different schema))
- `nyc_pluto` — NYC MapPLUTO (Primary Land Use Tax Lot Output) (city-unique (no equivalent exists))
- `nys_dos_appearance_enhancement` — NYS Active Appearance Enhancement and Barber Business Licensees (state)
- `nys_medicaid_pharmacies` — NYS Medicaid Enrolled Provider Listing — retail pharmacies (state)
- `nys_sla_liquor_licenses` — NYS Liquor Authority Current Active Licenses (state)
- `osm_overpass` — OpenStreetMap (Overpass API) (universal)
- `osm_walk_network` — OSM pedestrian network via OSMnx (universal)
- `overture_places` — Overture Maps Places (universal)
- `usda_snap_retailers` — USDA SNAP Retailer Locator (national (US federal))
- *(not a registry source)* ≥5 same-category business-sale comps at borough grain, WITH cash flow

Of those 16, **11 need per-city or per-state work**; the rest work on day one.

### Grade C — verdict *"diligence"*

| Section | Ceiling | What buys it |
|---|---|---|
| `arriving_homes` | B | NYC DCP Housing Database — Project-Level Files; NYC DOB Permit Issuance + DOB NOW Approved Permits; NYC DOB Certificates of Occupancy (BIS + DOB NOW) |
| `supply_thinness` | A | NYC MapPLUTO (Primary Land Use Tax Lot Output); NYC Street Centerline (CSCL); OSM pedestrian network via OSMnx; Overture Maps Places; Foursquare Open Source Places; OpenStreetMap (Overpass API) |
| `addressable_demand` | C | NYC MapPLUTO (Primary Land Use Tax Lot Output) |
| `economics` | C | a SHIPPED, GATED site-revenue calibration for the category (BLS CEX spend pool × fitted capture share, leakage anchored to Census CBP, capacity ceiling from parcel retail floor area) |
| `coverage` | C | Overture Maps Places; Foursquare Open Source Places; OpenStreetMap (Overpass API) |

**Minimum set for grade C: 9 sources plus 1 non-registry requirement.**

- `foursquare_os_places` — Foursquare Open Source Places (universal)
- `nyc_cscl` — NYC Street Centerline (CSCL) (city open data (different schema))
- `nyc_dcp_housing_db` — NYC DCP Housing Database — Project-Level Files (city open data (different schema))
- `nyc_dob_certificates_of_occupancy` — NYC DOB Certificates of Occupancy (BIS + DOB NOW) (city open data (different schema))
- `nyc_dob_permit_issuance` — NYC DOB Permit Issuance + DOB NOW Approved Permits (city open data (different schema))
- `nyc_pluto` — NYC MapPLUTO (Primary Land Use Tax Lot Output) (city-unique (no equivalent exists))
- `osm_overpass` — OpenStreetMap (Overpass API) (universal)
- `osm_walk_network` — OSM pedestrian network via OSMnx (universal)
- `overture_places` — Overture Maps Places (universal)
- *(not a registry source)* a SHIPPED, GATED site-revenue calibration for the category (BLS CEX spend pool × fitted capture share, leakage anchored to Census CBP, capacity ceiling from parcel retail floor area)

Of those 9, **5 need per-city or per-state work**; the rest work on day one.

### Grade D — verdict *"do not act on this data"*

| Section | Ceiling | What buys it |
|---|---|---|
| `arriving_homes` | D | nothing further |
| `supply_thinness` | A | NYC MapPLUTO (Primary Land Use Tax Lot Output); NYC Street Centerline (CSCL); OSM pedestrian network via OSMnx; Overture Maps Places; Foursquare Open Source Places; OpenStreetMap (Overpass API) |
| `addressable_demand` | C | NYC MapPLUTO (Primary Land Use Tax Lot Output) |
| `economics` | D | nothing further |
| `coverage` | C | Overture Maps Places; Foursquare Open Source Places; OpenStreetMap (Overpass API) |

**Minimum set for grade D: 6 sources.**

- `foursquare_os_places` — Foursquare Open Source Places (universal)
- `nyc_cscl` — NYC Street Centerline (CSCL) (city open data (different schema))
- `nyc_pluto` — NYC MapPLUTO (Primary Land Use Tax Lot Output) (city-unique (no equivalent exists))
- `osm_overpass` — OpenStreetMap (Overpass API) (universal)
- `osm_walk_network` — OSM pedestrian network via OSMnx (universal)
- `overture_places` — Overture Maps Places (universal)

Of those 6, **2 need per-city or per-state work**; the rest work on day one.

**The headline, and it is not about data portability at all.** `economics` cannot reach
B without cash-flow comps, which no city publishes, and `addressable_demand` defaults to
`no_haircut_grade: C` for fourteen of the fifteen categories. So the verdict *act* is
out of reach in New York today, and a second city inherits that ceiling unchanged. What
a second city can reach is `diligence` — and what decides whether it reaches even that
is the one column in §3's grade-C table that most portals omit: a permit renewal or
status date.

---

## 4. The city-unique sources, and what is lost without each

6 rows have no equivalent anywhere else. These are the permanent degradations — not an
adapter to write, a capability a second city does not have.

### MTA Subway Hourly Ridership 2020-2024

*Feeds:* `transit` · *Class confidence:* high

**Lost without it.** Transit becomes PRESENCE rather than QUALITY: a twelve-route
complex and a one-route stop score identically.

**Why nothing replaces it.** Hourly per-station ridership is published by almost no
other transit agency. NTD gives annual system- and route-level totals, which cannot be
assigned to a station.

### MTA Subway Hourly Ridership: Beginning 2025

*Feeds:* `transit` · *Class confidence:* high

**Lost without it.** transit_entries_400m cannot be built, which removes the only foot-
traffic proxy in the whole registry (D76) and leaves the card with no daypart signal.

### NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019)

*Feeds:* `lifecycle`, `validation`, `character` · *Class confidence:* high

**Lost without it.** No storefront-vacancy layer: the card's space section grades D
everywhere, the 'and this ground floor 120 m away is empty' sentence disappears, and the
D88 go-dark retrodiction has no outcome variable at all.

**Why nothing replaces it.** Local Law 157 of 2019 has no counterpart anywhere in the
United States. The nearest substitutes are commercial (LiveXYZ, CoStar) or a BID
storefront survey.

### NYC DOT VivaCity sidewalk sensors (data-sharing ask)

*Feeds:* `validation` · *Class confidence:* med

**Lost without it.** No continuous sidewalk sensor, so counts stay biannual seven-hour
snapshots and no daypart validation is possible.

**Why nothing replaces it.** The vendor sells everywhere; the DEPLOYMENT is a specific
NYC DOT procurement, and the data are not published as open data anywhere Loci has
found.

### NYC MapPLUTO (Primary Land Use Tax Lot Output)

*Feeds:* `universe`, `demand`, `character` · *Class confidence:* med

**Lost without it.** The screen has no sampling frame. analysis.address IS 'PLUTO lots
WHERE UnitsRes > 0', so without it there is no universe, no dasymetric ancillary, no
commercial zoning capacity control (required by CONTEXT 1.3), and no retail floor area
for D82 character or the D91 capacity ceiling.

**Why nothing replaces it.** A parcel file with residential units exists in nearly every
US county assessor. What is NYC-specific is the bundle: UnitsRes +
BldgArea/RetailArea/OfficeArea + ResidFAR/BuiltFAR + BldgClass + LandUse on one row,
citywide, free, twice a year. Expect to rebuild floor area and zoning capacity from two
or three separate files.

### StreetEasy listing pages (advertised in-building laundry, via Tavily)

*Feeds:* `demand` · *Class confidence:* med

**Lost without it.** Laundry evidence coverage drops below recommend_grades'
evidence_coverage_a of 0.50, so addressable_demand for laundry falls from A to the
prior_grade B.

**Why nothing replaces it.** StreetEasy is NYC-only, but the FUNCTION -- a dominant
listings portal whose pages advertise in-building amenities -- exists in most metros
under another brand.

---

## 5. What a new city must publish

Generic name first, because the NYC dataset is an example of the requirement and not the
requirement itself. Dataset ids are pulled from the registry, so they cannot drift from
what is actually ingested.

| Requirement | Tier | NYC example | What to check for |
|---|---|---|---|
| **Parcel file with residential units AND floor area** | MINIMUM | NYC MapPLUTO (Primary Land Use Tax Lot Output) | One row per lot, citywide, carrying: residential unit count (the universe and the dasymetric ancillary), building/retail/office floor area (D82 character, D91 capacity ceiling), zoning or FAR (the CONTEXT §1.3 commercial-capacity control), and a use or building class. In most US metros this is a COUNTY ASSESSOR file and the zoning half lives separately — budget for a two- or three-file join, and check that units are a real count and not a category code. |
| **Street centrelines, or OSM ways as the fallback** | MINIMUM | NYC Street Centerline (CSCL) (`inkn-q76z`) | The D84 second sampling frame: street midpoints, so a commercial corridor with no housing above it is still sampled. OSM substitutes, weakly — the keep rule leans on status and paper-street flags OSM does not carry. |
| **Walk network graph** | MINIMUM | OSM pedestrian network via OSMnx | Universal and free. The single most portable load-bearing input Loci has. |
| **POI base layers (at least two, independent)** | MINIMUM | Overture Maps Places<br>Foursquare Open Source Places<br>OpenStreetMap (Overpass API) | Two is the minimum, not a nicety: D11's corroborated-only supply set is what keeps single-source inflation out of the count. |
| **Census demographics, jobs and establishment counts** | MINIMUM | Census American Community Survey, 5-year estimates<br>LEHD LODES Workplace Area Characteristics (LODES8)<br>Census ZIP Code Business Patterns (ZBP), via the County Business Patterns (CBP) API | National and identical in every US city. Carries its own portable bias: LODES is 2020 blocks for all years and pre-2020 is area-retro-allocated. |
| **Building permits with job type, address and a renewal-or-status date** | MINIMUM | NYC DOB Permit Issuance + DOB NOW Approved Permits<br>DOB NOW: Build - Job Application Filings (`w9ak-ipjd`) | **The most commonly missing minimum input.** Many portals publish permit ISSUANCE only. Without a renewal or status date there is no active/lapsed/stalled split, `arriving_homes` falls to its null grade D, and — because that section is load-bearing — every card in the city reads *do not act*. |
| **Residential development pipeline with NET units** | MINIMUM | NYC DCP Housing Database — Project-Level Files (`br6q-ssj3`)<br>NYC DOB Certificates of Occupancy (BIS + DOB NOW) | NYC's DCP file is already QA'd, geocoded and net-unit-recoded. Elsewhere the net-unit recode has to be rebuilt from raw permits, which is exactly where unit double-counting enters. |
| **Food-service inspections with establishment NAMES** | anchor | DOHMH New York City Restaurant Inspection Results (`43nn-pn8j`) | The near-census that anchors restaurant, café and bar — three of fifteen categories and the whole T3 tier. Widely published, schema always different. Check it carries coordinates and not just an address string. |
| **Business licences with issue dates** | anchor | NYC DCWP Legally Operating Businesses (`w7w3-xahh`)<br>NYC DCWP Inspections (Retail Laundry / Dry Cleaners) (`jzhd-m6uv`)<br>NYC DCWP License Applications (`ptev-4hud`) | Two different jobs: the issued roster is a supply anchor for whatever trades the city licenses (laundry is the one that matters — no aggregator sees laundromats), and the APPLICATIONS feed is the lifecycle lead time. The applications half is the rarer one. |
| **Liquor licences (state), active and inactive** | anchor | NYS Liquor Authority Current Active Licenses (`9s3h-dpkz`)<br>NYS SLA Current Pending Licenses (`f8i8-k2gm`) | Every state has an ABC authority; far fewer publish a georeferenced active file, fewer still the inactive companion that makes closures recoverable, and fewest of all the PENDING queue that is the earliest go-live signal. |
| **Cosmetology / salon roster (state)** | anchor | NYS Active Appearance Enhancement and Barber Business Licensees (`y3u4-jbgh`) | Anchors hair and nail — the two categories where the §7.1 undercount is worst. Active-only almost everywhere, so survivorship-biased by construction: snapshot enrichment, never a panel. |
| **Childcare roster (state in most places, city in NYC)** | anchor | Active NYC Health Code Regulated Child Care Programs (`gy3q-4tzp`) | D65: without it, aggregator blind spots read as deserts. Home-based family day care is missing from every roster Loci has found, so the anchor is a supply FLOOR wherever it is built. |
| **Pharmacy roster** | anchor | NYS Medicaid Enrolled Provider Listing — retail pharmacies (`keti-qx5t`) | **The least portable anchor.** The NYC route works only because New York's NYRx carve-out routes every Medicaid member's pharmacy benefit through fee-for-service; in a managed-care state the same file is a fraction of the pharmacies. Expect to find a state Board of Pharmacy register instead, and expect it to have no bulk export. |
| **SNAP retailer locator (national)** | anchor | USDA SNAP Retailer Locator | Free, national, and the anchor for the two tier-1 weight-0.40 categories. Nothing to procure — it works in every US city on day one. |
| **GTFS, plus ridership by station or stop** | enrichment | MTA Subway Stations (`39hk-dx4f`)<br>MTA Subway Entrances and Exits 2024 (`i9wp-a4ja`)<br>MTA Subway Hourly Ridership: Beginning 2025 (`5wq4-mkjj`)<br>MTA Bus GTFS static (stops) | GTFS itself is universal. RIDERSHIP at station grain is not — NTD publishes annual system and route totals that cannot be assigned to a station. Without it, transit is presence, not quality. Entrance geometry (`pathways.txt`) is patchy outside NYC and its absence costs up to a 400 m walk of error at a large complex. |
| **Pedestrian counts** | enrichment | NYC DOT Bi-Annual Pedestrian Counts (`cqsj-cfgu`)<br>NYC DOT traffic cameras (NYCTMC public feed)<br>NYC DOT VivaCity sidewalk sensors (data-sharing ask) | Validation only — never an input to a score. Every city that publishes counts inherits the same restricted-range problem: the points were sited for traffic engineering on busy commercial corridors, which is not where the access proxy needs testing. |
| **Energy benchmarking with in-building laundry columns** | enrichment | NYC Energy and Water Data Disclosure (Local Law 84 / LL133) | ~40 US cities have a benchmarking ordinance; the laundry-hookup columns are a New York reporting artefact, not part of the standard template. |
| **The dominant residential listings portal** | enrichment | StreetEasy listing pages (advertised in-building laundry, via Tavily) | The brand is NYC-only; the FUNCTION — pages that advertise in-building amenities — exists in every metro. Advertising, not inspection: silence is not absence. |
| **Storefront / commercial-vacancy registry** | not obtainable | NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019) (`92iy-9c3n`) | **No second city has one.** A vacant-BUILDING registry is not the same thing: it records abandoned structures, not an empty ground floor under an occupied building, which is the exact object the screen is pointing at. |

---

## 6. Second-city readiness

Portal survey, 2026-09-14. **Research only — nothing has been ingested for any of these
cities and no adapter exists.** `partial` means the fact is published but not in the
form the pipeline needs; the note says which half is missing.

| Input | Chicago | Los Angeles | Philadelphia |
|---|---|---|---|
| Parcels with units + floor area | partial | yes | partial |
| Building permits with status/renewal | yes | yes | yes |
| Food-service inspections with names | yes | partial | no |
| Business licences with issue dates | partial | yes | partial |
| Liquor licences (state) | partial | partial | partial |
| Transit ridership by station/stop | partial | no | yes |
| Pedestrian counts | no | partial | yes |
| Storefront / vacancy registry | no | no | no |
| **grade on day one** | **D** | **D** | **D** |
| **ceiling after a local refit** | **C** | **C** | **C** |

**Why every city reads D on day one, and why that is not a verdict on the city.**
`economics` grades D until a site-revenue calibration for the category has been refitted
locally and passed its own leave-one-ZIP-out backtest — which is true in New York today
for fourteen of the fifteen categories. So the day-one grade is D everywhere, the
ceiling is C everywhere, and what the rows above actually decide is HOW MANY CATEGORIES
reach the ceiling and how defective the universe underneath them is.

### Chicago

**Day one: D. Ceiling after a local refit: C.** The same ceiling as New York, bounded by
the same section (`economics`) and not by anything Chicago fails to publish. Every
grade-C minimum input exists — including the permit status column that most portals omit
— but the parcel layer has to be assembled from four Cook County Assessor files with
different coverage, and unit counts are absent for large multifamily, which biases
`homes_400m` downward exactly where density is highest.

| Input | Status | Dataset | Note |
|---|---|---|---|
| Parcels with units + floor area | partial | [nj4t-kc8j + x54s-btds + csik-bsws + 3r7i-mrz4](https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Parcel-Universe/nj4t-kc8j) | No single row-per-lot file carries both. Parcel Universe has geometry and tax joins but zero building characteristics; units and building sq ft live in the improvement-characteristics file, which is capped at residential parcels under 7 units; larger multifamily units and floor area appear only in Commercial Valuation, 2021+ and income-valued properties only. Zoning is a fifth file (`7cve-jgbp`), district boundaries only — FAR is not a per-parcel attribute and has to be derived from the ordinance table. |
| Building permits with status/renewal | yes | [ydr8-5enu](https://data.cityofchicago.org/Buildings/Building-Permits/ydr8-5enu) | The good surprise. 4.47M rows carrying `permit_status`, `permit_milestone`, `application_start_date`, `issue_date`, `processing_time` and `work_type`. Chicago permits do not renew the way NYC's do, so `active_share` has to be redefined on milestone rather than on a renewal fee — a modelling change, not a missing column. |
| Food-service inspections with names | yes | [4ijn-s7e5](https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5) | Daily, since 2010, with DBA/AKA names and lat/lon. A direct analogue of DOHMH `43nn-pn8j` and it anchors the same three categories. |
| Business licences with issue dates | partial | [r5kz-chrr](https://data.cityofchicago.org/Community-Economic-Development/Business-Licenses/r5kz-chrr) | Historical since 2002 with lat/lon, `date_issued`, `license_status` and `license_status_change_date` — richer than NYC's issued roster. But **laundromats and salons are not distinct licence types**, so the two anchors NYC uses for laundry and for hair/nail do not exist here; childcare types do. |
| Liquor licences (state) | partial | [nrmj-3kcf (city) / ILCC portal (state)](https://data.cityofchicago.org/Community-Economic-Development/Business-Licenses-Current-Liquor-and-Public-Places/nrmj-3kcf) | City-level is stronger than NYC's: the historical licence file already carries status, so closures are recoverable without a separate inactive companion. State-level ILCC moved to a new portal in 2026 and ceased/expired licences come out of a date-range search plus CSV export, not a stable bulk URL. |
| Transit ridership by station/stop | partial | [5neh-572f](https://data.cityofchicago.org/Transportation/CTA-Ridership-L-Station-Entries-Daily-Totals/5neh-572f) | Per-station DAILY entries back to 2001 — transit quality survives, the D76 daypart signal does not. CTA's GTFS carries no `pathways.txt` or `levels.txt`, so there is no entrance geometry and walk distance is to the station point. Bus is route-level monthly, never per stop. |
| Pedestrian counts | no | — | Nothing on the city, county or state portal. The only citywide counts are vehicle ADT taken roughly once a decade (`pfsx-4n4m`); Loop Alliance counts are third-party. The access proxy would ship unvalidated. |
| Storefront / vacancy registry | no | [u7si-yh3t (nearest substitute)](https://data.cityofchicago.org/Buildings/Vacant-Building-Violations/u7si-yh3t) | Chicago has the LEGAL analogue — the Vacant Building and Vacant Storefront Registration — but it is queryable one property at a time behind a login, never published in bulk. Vacant Building Violations is enforcement records, not a current-status registry, and conflates a vacant building with an empty ground floor under an occupied one. |

**Has that NYC does not.** Cook County pre-joins CMAP walkability scores,
TIF/enterprise-zone flags and FEMA flood flags onto every parcel, and the Commercial
Valuation file exposes NOI, cap rate and occupancy for income properties — underwriting
detail with no NYC public equivalent, and a plausible free substitute for part of paid-
sources gap (c).

**The strongest of the three.** The two hard gaps are pedestrian counts (nothing
published, so the access proxy ships unvalidated) and the storefront registry (legally
exists, operationally locked). Neither blocks a grade-C card. The real work is the
parcel join, and the real risk is the missing unit counts on large multifamily.

### Los Angeles

**Day one: D. Ceiling after a local refit: C.** C on the data — and the number would
still not mean anything. LA is driving-dominant; every distance in Loci is an 800 m WALK
on an OSM graph, calibrated on Manhattan and Brooklyn under D48. That is not a
miscalibration to correct, it is the wrong instrument, and it has to be replaced with a
drive-time kernel before the data ceiling is worth reaching.

| Input | Status | Dataset | Note |
|---|---|---|---|
| Parcels with units + floor area | yes | [LA County Assessor Parcel Data (rolls 2021–present)](https://data.lacounty.gov/datasets/785f54236d1644dc975a55af19b3dd70/about) | The cleanest parcel layer of the three: number of units, main square footage, year built, 4-digit use code and lat/lon on one row. Grain is roll-year × AIN, so filter to the latest roll. Zoning is city-only and separate (ZIMAS / GeoHub), and covers neither unincorporated county nor the 87 other cities. |
| Building permits with status/renewal | yes | [pi9x-tg5x](https://data.lacity.org/City-Infrastructure-Service-Requests/Building-and-Safety-Building-Permits-Issued-from-2/pi9x-tg5x) | Carries `status_desc` AND `status_date` alongside `permit_type`, `use_code`, address and lat/lon — a genuine activity axis in one file. LA City only; 2020-present, with a 2010–2019 companion. Use this, not the simpler `hbkd-qubn`, which has no status date. |
| Food-service inspections with names | partial | [LA County DPH Restaurant & Market Inspections](https://data.lacounty.gov/datasets/19b6607ac82c4512b10811870975dbdc/about) | **Recently restricted.** The county's own page states that inspections conducted on or after 2025-08-25 must be requested through a CPRA request. Whether the portal extract is frozen at that date is unverified and must be checked against the file before relying on it. This is the anchor for three of the fifteen categories. |
| Business licences with issue dates | yes | [6rrh-rzua](https://data.lacity.org/Administration-Finance/Listing-of-Active-Businesses/6rrh-rzua) | Better keyed than NYC's: a real NAICS code, so laundromats (812320), salons (812112) and childcare (624410) are identifiable rather than absent. ACTIVE only, so it is survivorship-biased exactly like the NYS salon file — snapshot enrichment, never a panel. |
| Liquor licences (state) | partial | [CA ABC daily data export (not Socrata)](https://www.abc.ca.gov/licensing/licensing-reports) | A daily CSV covers all pending and active licences — which means the PENDING queue, NYC's earliest go-live signal, exists here too. Closures do not: surrendered licences come out as a monthly report, so a closure history has to be accumulated from snapshots rather than downloaded. |
| Transit ridership by station/stop | no | https://opa.metro.net/MetroRidership/ | Metro publishes LINE-level ridership through a dashboard, one query at a time, not in bulk. Station-level figures have circulated only through a public-records request. The rail GTFS was downloaded and confirmed to contain no `pathways.txt` or `levels.txt`. Transit would be presence, not quality, and there would be no foot-traffic proxy at all. |
| Pedestrian counts | partial | [6ux4-qj74 (2023), m6qi-ifup (2019)](https://data.lacity.org/Transportation/2023-Walk-Bike-Count-Data/6ux4-qj74) | Real bulk CSVs, odd years since 2019: ~100 locations, 79 temporary 8-hour manual counts plus 21 permanent counters. Sparser and more project-driven than DOT's 114 fixed points, and it inherits the same restricted-range problem. |
| Storefront / vacancy registry | no | — | No analogue and no near-analogue. The Foreclosure Registry covers residential foreclosure only; the LAMC vacant-structure penalty is complaint-driven with no published registry. No ground-floor-commercial reporting duty exists in city or county. |

**Has that NYC does not.** Business licences carry NAICS, which NYC's DCWP roster does
not — the filing-blind categories of GTM-152 are partly visible here for free.

**The city/county split is a structural seam, not a nuisance.** Parcels and food
inspections are LA County; permits, licences, zoning and pedestrian counts are LA City;
none of the county layers are clipped to the city, and the county contains 87 other
incorporated cities. Two platforms, two geographies, two refresh cadences — and then the
walk-distance problem on top.

### Philadelphia

**Day one: D. Ceiling after a local refit: C.** Reaches the ceiling for fewer CATEGORIES
than the other two. There is no bulk food-inspection feed at all -- only a one-record
web lookup -- so restaurant, cafe and bar lose the anchor that is the cheapest win in
every other city, and laundromats, salons and barbers hide inside an ADDRESSLESS
commercial-activity licence table. Worse for the universe: the OPA parcel file has floor
area but **no unit count**, so `homes_400m` -- an input to a load-bearing section -- has
to be modelled from ACS households apportioned by livable area rather than read off the
parcel.

| Input | Status | Dataset | Note |
|---|---|---|---|
| Parcels with units + floor area | partial | [opa_properties_public (Carto)](https://opendataphilly.org/datasets/philadelphia-properties-and-assessment-history/) | 90 fields verified against the Carto API. `total_livable_area` and `total_area` are present; there is no UnitsTotal analogue -- the `unit` column holds per-condo designators ('8D', 'G', '314'), not a count. `zoning` sits on the row and again as a citywide polygon layer; `building_code` and `category_code` stand in for land use. |
| Building permits with status/renewal | yes | [permits (Carto)](https://opendataphilly.org/datasets/licenses-and-inspections-building-and-zoning-permits/) | The best of the three. 48 fields verified: `permittype`, `typeofwork`, `address`, `permitissuedate`, `status`, `mostrecentinsp`, `permitcompleteddate`, `certificateofoccupancydate` and -- uniquely -- `numberofunits` on the permit itself, which is the net-unit recode NYC needs a separate DCP file for. |
| Food-service inspections with names | no | https://www.phila.gov/services/permits-violations-licenses/get-a-license/business-licenses/food-businesses/look-up-a-food-safety-inspection-report/ | **The one clean miss that costs real categories.** A per-establishment web lookup only; no bulk CSV, no API, nothing in OpenDataPhilly's Food or Health categories. Restaurant, cafe and bar fall to `unanchored_grade: C` on aggregators alone, which is where CONTEXT 7.1 bites. |
| Business licences with issue dates | partial | [business_licenses (Carto)](https://opendataphilly.org/datasets/licenses-and-inspections-business-licenses/) | 48 fields verified, with `initialissuedate`, `mostrecentissuedate` and geocoded coordinates. All 53 `licensetype` values were enumerated: Child Care Facility is there; **laundromats, salons and barbershops are not**, and fall into the generic Commercial Activity License table (`com_act_licenses`), which carries no address or coordinate field at all. |
| Liquor licences (state) | partial | [PLCB+ License Search (not a catalogued table)](https://plcbplus.pa.gov/pub/Default.aspx?PossePresentation=LicenseSearch) | A search UI with a bulk CSV export filterable by status -- active, expired, pending, transfers, safekeeping, suspended -- so closures ARE retained, better than the NYS split active/inactive pair. Address completeness in the export is unverified; it is a UI export, not a documented schema, so there is no stable endpoint to automate against. |
| Transit ridership by station/stop | yes | [SEPTA Ridership Statistics + SEPTA GTFS](https://opendataphilly.org/datasets/septa-ridership-statistics/) | Average daily ridership per stop/station, but as periodic SNAPSHOTS (seasonal 2014-2025, monthly by mode/route, regional-rail station summaries 2017-2024 with 2020-21 missing) -- not a continuous series, so no daypart signal. The live GTFS was downloaded: the bus/trolley feed DOES carry `pathways.txt` and `levels.txt`; the rail feed does not. |
| Pedestrian counts | yes | [DVRPC Pedestrian Count Locations](https://catalog.dvrpc.org/dataset/dvrpc-pedestrian-count-locations) | The only one of the three with a real bulk-downloadable pedestrian count layer (CSV / shapefile / GeoJSON), run regionally by DVRPC rather than by the city. The access proxy could be validated here on day one. |
| Storefront / vacancy registry | no | [Vacant Property Indicators (substitute)](https://opendataphilly.org/datasets/vacant-property-indicators/) | No landlord self-report registry. The substitute is a MODELLED administrative 'likely vacant' flag -- not reported, not ground-floor-specific. A second, weaker proxy: the 'Vacant Commercial Property' licence type in `business_licenses`, which is compliance-based and so has the same invisible-non-filing problem as LL157, without the storefront grain. |

**Has that NYC does not.** Two that matter. **Commercial Corridors of Philadelphia** is
a citywide GIS layer of designated retail-corridor boundaries -- Loci infers corridors
from POI density and floor area (D82/D84); here they are published. And **Real Estate
Transfers**, a fully open deed-level sales feed sitting next to the parcels table, is an
ACRIS analogue with no NYC open equivalent. Also Storefront Improvement Program grants
(a positive-investment signal per corridor) and large-building energy benchmarking.

**Best permits, worst anchors.** The permit file alone would save weeks -- status,
completion, CO date and net units on one row. But a screen with no food-inspection
census and no laundry or salon licence type runs five of the fifteen categories on
aggregator coverage alone, which is the exact failure mode CONTEXT 7.1 says would
invalidate the finding.

---

## 7. Classifications that are judgement calls

Every row here is a `class` the author is not certain of, with the reason. Recorded so a
second-city plan starts from the doubt rather than rediscovering it.

| Source | Class | Conf. | The uncertainty |
|---|---|---|---|
| MTA Subway Entrances and Exits 2024 | city open data (different schema) | low | GTFS pathways.txt can carry entrances and a growing minority of agencies publish them, but coverage is patchy and unverified outside NYC. |
| NYS Medicaid Enrolled Provider Listing — retail pharmacies | state | low | NOT reliably portable. This roster works as a pharmacy census only because New York's NYRx carve-out (2023-04-01) routes every Medicaid member's pharmacy benefit through fee-for-service. In a managed-care state the same file is a fraction of the pharmacies. Treat the CLASS as state and the METHOD as NY- specific. |
| Citi Bike System Data (trip files) | national (US federal) | med | Classed `national` because the SCHEMA, not the operator, is the portable thing: every Lyft-run US system (Divvy Chicago, Bay Wheels SF, Capital Bikeshare DC, Bluebikes Boston, Citi Bike NYC) publishes the same thirteen columns in the same monthly-zip convention, so the parser and every derived measure port with a changed bucket URL. Confidence is `med` and not `high` because that covers roughly a dozen cities and no more: a non-Lyft system (Indego, a BCycle city) publishes a different schema or no trip file at all, and a city with no bikeshare has no equivalent at any price. Dock placement is also an operator's capital plan, so coverage in a second city is whatever that operator built. |
| NYC DCP Housing Database — Project-Level Files | city open data (different schema) | med | Every city publishes permits; almost none publish a QA'd, geocoded, NET-UNIT- RECODED project file. Elsewhere the net-unit recode has to be rebuilt from raw permits, which is where unit double-counting enters. |
| NYC DCWP Inspections (Retail Laundry / Dry Cleaners) | city open data (different schema) | med | Most cities license laundromats inside a general business-licence file rather than inspecting them; the equivalent exists but is a licence roster, not an inspection feed, so opening dates come through weaker. |
| NYC DCWP License Applications | city open data (different schema) | med | An APPLICATIONS feed (as distinct from the issued-licence roster) is the rarer half of the pair. Where a city publishes only issued licences the stage still works, but the lead time collapses from months to zero. |
| NYC DOB Certificates of Occupancy (BIS + DOB NOW) | city open data (different schema) | med | Certificates of occupancy are a universal building-code artefact; whether they are published as an open dataset is not universal. |
| DOB NOW: Build - Job Application Filings | city open data (different schema) | med | Permit-application feeds are common; a work-type breakdown fine enough to isolate a sign permit or a place of assembly is not. |
| NYC DOB Permit Issuance + DOB NOW Approved Permits | city open data (different schema) | med | The generic requirement is a permit file carrying a RENEWAL or status date, not just an issue date. Many permit datasets publish issuance only, which is exactly the column that makes this stage work. |
| Active NYC Health Code Regulated Child Care Programs | state | med | NYC is unusual in that the CITY licenses group child care (Art. 47); in most states the roster is a state agency file. Portable, but from a different publisher. |
| NYC DOT Bi-Annual Pedestrian Counts | city open data (different schema) | med | Many cities publish some pedestrian counts; a 37-round, 19-year biannual panel at fixed points is rare, and the restricted-range problem (counts sited on busy commercial corridors) travels to every city that has one. |
| NYC DOT traffic cameras (NYCTMC public feed) | city open data (different schema) | med | Public traffic-camera APIs exist in many cities; unpublished bearing and field of view make any count a count on an unknown catchment, wherever it is done. |
| NYC DOT VivaCity sidewalk sensors (data-sharing ask) | city-unique (no equivalent exists) | med | The vendor sells everywhere; the DEPLOYMENT is a specific NYC DOT procurement, and the data are not published as open data anywhere Loci has found. |
| NYC Energy and Water Data Disclosure (Local Law 84 / LL133) | city open data (different schema) | med | Roughly 40 US cities have a benchmarking ordinance, but the laundry-hookup columns are a New York reporting artefact, not part of the standard template. |
| NYC MapPLUTO (Primary Land Use Tax Lot Output) | city-unique (no equivalent exists) | med | A parcel file with residential units exists in nearly every US county assessor. What is NYC-specific is the bundle: UnitsRes + BldgArea/RetailArea/OfficeArea + ResidFAR/BuiltFAR + BldgClass + LandUse on one row, citywide, free, twice a year. Expect to rebuild floor area and zoning capacity from two or three separate files. |
| NYS SLA Current Pending Licenses | state | med | A pending/applications queue is far rarer than the active-licence file; most ABC authorities publish only what has issued. |
| StreetEasy listing pages (advertised in-building laundry, via Tavily) | city-unique (no equivalent exists) | med | StreetEasy is NYC-only, but the FUNCTION -- a dominant listings portal whose pages advertise in-building amenities -- exists in most metros under another brand. |

---

**One caveat no check can enforce.** Every distance in Loci is a WALK distance on an OSM
graph, and the whole screen is calibrated on Manhattan and Brooklyn — dense, walking-
dominant, chosen for that reason in D48. The 800 m threshold, the saturating DNCI
constants `k_c`, the 1.233 circuity, the density elasticities in
`density_elasticity.yaml` and the D91 revenue calibration are all NYC-fitted parameters.
A city that reads green on every row of §6 still needs those refitted before a single
number it produces means anything, and in a driving-dominant city the 800 m walk
threshold is not a mild miscalibration — it is the wrong instrument.
