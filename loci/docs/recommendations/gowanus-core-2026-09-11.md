# Recommendation card — Gowanus core

1,831 eligible addresses · Carroll Gardens-Cobble Hill-Gowanus-Red Hook, Park Slope · boroughs BK · bbox `[40.67, -73.995, 40.682, -73.982]`

Generated 2026-09-11 · grading rules v1 (`src/loci/model/recommend_grades.yaml`) · supply hash `767b28674e30`

## Summary — area × category

| area | category | supply ratio | regime | grade | verdict | D sections |
|---|---|---:|---|:-:|---|---|
| Gowanus core | pharmacy | 0.00× | no_signal | **D** | do not act on this data | economics |
| Gowanus core | tailor_repair | 0.00× | saturating | **C** | diligence | — |
| Gowanus core | convenience | 0.40× | no_signal | **D** | do not act on this data | economics |
| Gowanus core | hardware | 0.72× | no_signal | **C** | diligence | — |
| Gowanus core | laundry | 0.94× | saturating | **D** | do not act on this data | economics |
| Gowanus core | childcare | 0.94× | saturating | **D** | do not act on this data | economics |
| Gowanus core | hair_barber | 0.98× | saturating | **D** | do not act on this data | economics |
| Gowanus core | grocery | 1.07× | saturating | **D** | do not act on this data | economics |
| Gowanus core | clinic | 1.33× | saturating | **D** | do not act on this data | economics |
| Gowanus core | nails_beauty | 1.75× | saturating | **D** | do not act on this data | economics |
| Gowanus core | restaurant | 1.84× | no_signal | **D** | do not act on this data | economics |
| Gowanus core | bank | 1.97× | saturating | **D** | do not act on this data | economics |
| Gowanus core | cafe_bakery | 2.89× | no_signal | **D** | do not act on this data | economics |
| Gowanus core | fitness | 3.39× | saturating | **D** | do not act on this data | economics |
| Gowanus core | bar | 5.58× | no_signal | **D** | do not act on this data | economics |

Grades: **A** measured with a margin from an enumerating source · **B** self-reported, prior-driven or coarser · **C** thin, or the right measurement on the wrong universe · **D** not evidence. The verdict is the WORST load-bearing grade (sections 2, 3, 4, 6, 7); sections 1 and 5 are context and cannot move it. A card may not say *act* while any load-bearing claim is at **D** (D72).

Caveats that travel with every number here: the supply baseline is REVEALED SUPPLY (D6) — 1.0× is normal for this city, never *correctly provisioned*, and under-provision is correlated with race net of income (Meltzer & Schuetz). Permit *activity* is a renewal, not a shovel. The storefront registry is self-reported and annual. No rent or square footage exists at address grain anywhere public.

---
## Pharmacy (`pharmacy`, tier 1)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 0.00× of the MN+BK baseline, regime `no_signal`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **0.00×** (0.000 per 1,000 homes vs baseline 0.756)
- Median supply within 400 m: 0 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `no_signal` — supply count is NOT evidence either way -- residents only (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 1, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 1** at `borough` level (Brooklyn)
- Expected revenue: — · **supportable rent $73,200/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **B** (load-bearing)
*registry anchor qualifies, coverage 0.90; no Google check for this area*

- Registry anchor qualifies: **True** (coverage 0.90, sources `nys_medicaid_pharmacies`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 1, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Tailor / repair (`tailor_repair`, tier 2)

**Verdict: DILIGENCE** — overall grade **C** (worst load-bearing section). Supply ratio 0.00× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **0.00×** (0.000 per 1,000 homes vs baseline 0.238)
- Median supply within 400 m: 0 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **C** (load-bearing)
*only 1 comps at citywide level*

- Comps: **n = 1** at `citywide` level ((all))
- Expected revenue: $220,000 · **supportable rent $45,600/yr** (source `listed`)
- Cushion: 229% (`cash_flow_vs_rent`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **C** (load-bearing)
*no qualifying registry anchor -- OSM/Overture only, so thin supply may be a coverage hole*

- Registry anchor qualifies: **False** (coverage 0.00, sources `nan`)
- Google validation cells in this area: 0

*No load-bearing section grades D.*


---

## Bodega / convenience (`convenience`, tier 1)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 0.40× of the MN+BK baseline, regime `no_signal`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **0.40×** (0.452 per 1,000 homes vs baseline 1.130)
- Median supply within 400 m: 2 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `no_signal` — supply count is NOT evidence either way -- residents only (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 2, no cash-flow data -- rent_source 'occupancy_ratio_fallback'*

- Comps: **n = 2** at `borough` level (Brooklyn)
- Expected revenue: $635,000 · **supportable rent $38,100/yr** (source `occupancy_ratio_fallback`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **B** (load-bearing)
*registry anchor qualifies, coverage 1.43; no Google check for this area*

- Registry anchor qualifies: **True** (coverage 1.43, sources `usda_snap_retailers`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 2, no cash-flow data -- rent_source 'occupancy_ratio_fallback'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Hardware / home supply (`hardware`, tier 4)

**Verdict: DILIGENCE** — overall grade **C** (worst load-bearing section). Supply ratio 0.72× of the MN+BK baseline, regime `no_signal`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **0.72×** (0.306 per 1,000 homes vs baseline 0.423)
- Median supply within 400 m: 1 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `no_signal` — supply count is NOT evidence either way -- residents only (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **C** (load-bearing)
*only 3 comps at citywide level*

- Comps: **n = 3** at `citywide` level ((all))
- Expected revenue: $320,000 · **supportable rent $92,370/yr** (source `listed`)
- Cushion: -7% (`cash_flow_vs_rent`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **C** (load-bearing)
*no qualifying registry anchor -- OSM/Overture only, so thin supply may be a coverage hole*

- Registry anchor qualifies: **False** (coverage 0.00, sources `nan`)
- Google validation cells in this area: 0

*No load-bearing section grades D.*


---

## Laundromat / dry cleaner (`laundry`, tier 1)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 0.94× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **0.94×** (1.155 per 1,000 homes vs baseline 1.228)
- Median supply within 400 m: 4 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **B** (load-bearing)
*in-home haircut is size-class PRIORS (laundry_haircut v1); building evidence covers only 3.1% of addresses*

- Homes within 400 m (median): **3,646**
- Addressable after the in-home haircut: **1,473** (39% of homes survive)
- Building-level laundry evidence covers 3.1% of addresses (haircut v1; the rest carry size-class priors)

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 1, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 1** at `borough` level (Brooklyn)
- Expected revenue: $140,000 · **supportable rent $54,000/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **B** (load-bearing)
*registry anchor qualifies, coverage 1.42; no Google check for this area*

- Registry anchor qualifies: **True** (coverage 1.42, sources `nyc_dcwp_inspections`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 1, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Childcare (`childcare`, tier 4)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 0.94× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **0.94×** (1.220 per 1,000 homes vs baseline 1.296)
- Median supply within 400 m: 4 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 2, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 2** at `borough` level (Brooklyn)
- Expected revenue: $803,620 · **supportable rent $90,000/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **B** (load-bearing)
*registry anchor qualifies, coverage 0.85; no Google check for this area*

- Registry anchor qualifies: **True** (coverage 0.85, sources `nyc_dohmh_childcare`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 2, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Hair / barber (`hair_barber`, tier 2)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 0.98× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **0.98×** (2.496 per 1,000 homes vs baseline 2.541)
- Median supply within 400 m: 8 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 1, no cash-flow data -- rent_source 'occupancy_ratio_fallback'*

- Comps: **n = 1** at `borough` level (Brooklyn)
- Expected revenue: $1,865,000 · **supportable rent $223,800/yr** (source `occupancy_ratio_fallback`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **C** (load-bearing)
*no qualifying registry anchor -- OSM/Overture only, so thin supply may be a coverage hole*

- Registry anchor qualifies: **False** (coverage 0.39, sources `nys_dos_appearance_enhancement`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 1, no cash-flow data -- rent_source 'occupancy_ratio_fallback'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Grocery / supermarket (`grocery`, tier 1)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 1.07× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **1.07×** (3.397 per 1,000 homes vs baseline 3.170)
- Median supply within 400 m: 10 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 5, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 5** at `borough` level (Brooklyn)
- Expected revenue: $2,097,748 · **supportable rent $120,000/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **C** (load-bearing)
*no qualifying registry anchor -- OSM/Overture only, so thin supply may be a coverage hole*

- Registry anchor qualifies: **False** (coverage 0.58, sources `usda_snap_retailers`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 5, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Clinic / urgent care (`clinic`, tier 4)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 1.33× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **1.33×** (1.030 per 1,000 homes vs baseline 0.775)
- Median supply within 400 m: 3 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 1, no cash-flow data -- rent_source 'occupancy_ratio_fallback'*

- Comps: **n = 1** at `borough` level (Brooklyn)
- Expected revenue: $721,178 · **supportable rent $57,694/yr** (source `occupancy_ratio_fallback`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **C** (load-bearing)
*no qualifying registry anchor -- OSM/Overture only, so thin supply may be a coverage hole*

- Registry anchor qualifies: **False** (coverage 0.00, sources `nan`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 1, no cash-flow data -- rent_source 'occupancy_ratio_fallback'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Nail / beauty (`nails_beauty`, tier 2)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 1.75× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **1.75×** (2.947 per 1,000 homes vs baseline 1.688)
- Median supply within 400 m: 9 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 3, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 3** at `citywide` level ((all))
- Expected revenue: $2,375,376 · **supportable rent $157,176/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **B** (load-bearing)
*registry anchor qualifies, coverage 3.04; no Google check for this area*

- Registry anchor qualifies: **True** (coverage 3.04, sources `nys_dos_appearance_enhancement`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 3, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Restaurant (`restaurant`, tier 3)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 1.84× of the MN+BK baseline, regime `no_signal`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **1.84×** (11.389 per 1,000 homes vs baseline 6.190)
- Median supply within 400 m: 39 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `no_signal` — supply count is NOT evidence either way -- residents only (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 3, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 3** at `borough` level (Brooklyn)
- Expected revenue: $1,012,650 · **supportable rent $72,000/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **B** (load-bearing)
*registry anchor qualifies, coverage 1.46; no Google check for this area*

- Registry anchor qualifies: **True** (coverage 1.46, sources `nyc_dohmh_restaurants`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 3, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Bank branch (`bank`, tier 4)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 1.97× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **1.97×** (0.476 per 1,000 homes vs baseline 0.241)
- Median supply within 400 m: 2 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 0, no cash-flow data -- rent_source 'no_data'*

- Comps: **n = 0** at `citywide` level ((all))
- Expected revenue: — · **supportable rent —** (source `no_data`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **C** (load-bearing)
*no qualifying registry anchor -- OSM/Overture only, so thin supply may be a coverage hole*

- Registry anchor qualifies: **False** (coverage 0.00, sources `nan`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 0, no cash-flow data -- rent_source 'no_data'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Cafe / bakery (`cafe_bakery`, tier 3)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 2.89× of the MN+BK baseline, regime `no_signal`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **2.89×** (3.743 per 1,000 homes vs baseline 1.297)
- Median supply within 400 m: 11 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `no_signal` — supply count is NOT evidence either way -- residents only (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 1, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 1** at `borough` level (Brooklyn)
- Expected revenue: $216,413 · **supportable rent $78,000/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **B** (load-bearing)
*registry anchor qualifies, coverage 1.23; no Google check for this area*

- Registry anchor qualifies: **True** (coverage 1.23, sources `nyc_dohmh_restaurants`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 1, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Fitness (`fitness`, tier 4)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 3.39× of the MN+BK baseline, regime `saturating`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **3.39×** (2.909 per 1,000 homes vs baseline 0.857)
- Median supply within 400 m: 11 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `saturating` — thin supply is a POSITIVE -- incumbents count against the site (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 1, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 1** at `borough` level (Brooklyn)
- Expected revenue: $1,445,463 · **supportable rent $360,000/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **C** (load-bearing)
*no qualifying registry anchor -- OSM/Overture only, so thin supply may be a coverage hole*

- Registry anchor qualifies: **False** (coverage 0.00, sources `nan`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 1, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.


---

## Bar / pub (`bar`, tier 3)

**Verdict: DO NOT ACT ON THIS DATA** — overall grade **D** (worst load-bearing section). Supply ratio 5.58× of the MN+BK baseline, regime `no_signal`.

### 1. Demand now — grade **B** (context)
*ACS 5-year + PLUTO units; income MOE 22% of the estimate (>= 20%) -- the level is soft*

- Homes within 400 m (median address): **3,646**
- Median household income: **$160,652** ± $35,726 (1.94× MN+BK)
- 18–34 share: **24.6%** · renter share 62.4%

### 2. Arriving homes — grade **C** (load-bearing)
*72% of permitted units active by exposure but the median address sees only 50% -- activity is concentrated, worse band taken; a renewal is not a shovel*

- Permitted units in the area's 400 m catchments, summed over addresses: **660,721** — catchments OVERLAP, so this is an exposure total, not a unit count
- Active (permit renewed ≤12 mo or expiring in future): **474,053** · stalled **169,456** · lapsed-or-unknown **17,212**
- Median address sees 59 permitted units, 50% of them active
- *Active means the permit was renewed, **not** that construction was observed — no NYC feed publishes a construction-start date (D72).*

### 3. Supply thinness — grade **A** (load-bearing)
*principled set, hash 767b28674e30, n = 1,831 addresses*

- Median `supply_ratio_vs_base`: **5.58×** (2.898 per 1,000 homes vs baseline 0.519)
- Median supply within 400 m: 9 POIs · n = 1,831 addresses
- Supply set `principled`, live hash `767b28674e30`, baseline hash `767b28674e30`
- Regime `no_signal` — supply count is NOT evidence either way -- residents only (D70)

### 4. Addressable demand — grade **C** (load-bearing)
*no category-specific haircut yet -- this is homes within reach, not households in the market*

- Homes within 400 m (median): **3,646**
- *No category-specific haircut yet: this is homes within reach, not households in the market.*

### 5. Space — grade **B** (context)
*DOF Storefront Registry, self-reported, annual snapshot 2024-12-31 -- a filing, never a listing; no rent or sqft exists*

- Addresses with ≥1 vacant storefront within 400 m: **81%**
- Median vacant storefronts nearby: 2 of 43 registered
- DOF Storefront Registry snapshot 2024-12-31 — self-reported, never a listing; no rent or sqft published.

### 6. Economics — grade **D** (load-bearing)
*n_comps = 1, no cash-flow data -- rent_source 'listed'*

- Comps: **n = 1** at `borough` level (Brooklyn)
- Expected revenue: — · **supportable rent $91,680/yr** (source `listed`)
- Cushion: — (`no_data`)
- *No expected profit is emitted, ever — expected profit is not a number this model has.*

### 7. Coverage — grade **B** (load-bearing)
*registry anchor qualifies, coverage 1.85; no Google check for this area*

- Registry anchor qualifies: **True** (coverage 1.85, sources `nys_sla_liquor_licenses`)
- Google validation cells in this area: 0

### What would change the verdict

- **Economics (D)** — n_comps = 1, no cash-flow data -- rent_source 'listed'. Cheapest check: 3-5 P&Ls (or broker setups) for the category in this borough.

