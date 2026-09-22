# RQ-001 Data Audit — regime-durability inputs

Read-only audit of `src/loci/registry.yaml` and `data/loci.duckdb` against the SEED.yaml
pillars (DEMAND / SUPPLY / COST / MACRO) for both tiers: ZIP panel 1994→present and
address-trade-area panel ~2010→present. Warehouse opened `read_only=True`; nothing
written. Probed 2026-09-22.

## Input table

| Pillar | Input | Source (registry id) | Publisher | History in warehouse (years) | Grain | Status | Gap to close |
|---|---|---|---|---|---|---|---|
| SUPPLY | Restaurant establishment counts by NAICS (722511/722513/722514/722515/722410) | `census_zbp` / `census_cbp` | Census ZBP/CBP | **1998–2023 (26 yr)**, `analysis.zip_establishments` (8.2M rows) | ZIP | present | 1994–1997 upstream-served but SIC-only, deliberately skipped (no SIC→NAICS crosswalk, D42) |
| SUPPLY | Restaurant/bar establishment counts, Loci category rollup | derived from `census_zbp` | Census ZBP/CBP | **1998–2023 (26 yr)**, `analysis.zip_category_establishments` (16 categories incl. `restaurant`, `bar`) | ZIP | present | none for v0 |
| SUPPLY | POI-level restaurant openings (near-census) | `nyc_dohmh_restaurants` | NYC DOHMH | 2022–current only in registry `temporal`; `analysis.poi_first_seen` actually spans **1978–2026** (219,458 rows, all POI types pooled) | address / point | present, but not restaurant-filtered or ZIP-rolled up | needs filter to restaurant categories + ZIP aggregation for address tier |
| SUPPLY | Bar openings/closings (dated spells) | `nys_sla_liquor_licenses` + `nys_sla_inactive_licenses` | NYS Liquor Authority | active file issue dates 2017–2026; inactive/closure file 1981–2026; `analysis.licence_interval` (24,850 + 29,568 rows), `analysis.licence_event` (18,312 + 25,551 rows) | address (BBL-matched) | present | bar-only; not restaurant-broad; usable for address-tier hazard covariates and as a closure ground-truth check |
| DEMAND | Foot traffic (pedestrian counts) | `nyc_dot_pedestrian_counts` | NYC DOT | **2007–2026, 37 biannual rounds**, `staging.dot_pedestrian_count` (12,312 rows) | 114 fixed points citywide (not ZIP, not a sample) | present but structurally unsuited to a ZIP panel | role is `control`/validation only per registry; restricted-range, corridor-biased; unusable as a ZIP-tier demand pillar input without heavy imputation |
| DEMAND | Transit ridership / foot-traffic proxy | `mta_subway_ridership` (2020–2024) + `mta_subway_ridership_2025` (2025–current) | MTA | 2020–current, station-complex grain, not yet aggregated to ZIP in a stored table (`analysis.address_transit_profile` exists at address grain) | station complex / address | present, address tier only | too short (5–6 yr) for the long ZIP base rate; only covers the address tier |
| DEMAND | Bike trips (secondary mobility proxy) | `citibike_tripdata` | Citi Bike / Lyft | registry temporal 2013–current, but `staging.citibike_station_month` actually loaded **2021-02–2026-08** only | dock / address | partial | pre-2021 annual archives (2013–2020) not ingested; also too short for 1994 base rate |
| DEMAND | Residents, workers, income, age, tenure | `acs_5yr` | Census ACS 5yr | registry temporal 2013–2024 (sliding 5yr windows), but warehouse holds **exactly one vintage: acs_year = 2023** in `analysis.address_demographics` (332,041 rows) and `analysis.hex_demographics` | tract → address / hex | **partial — single cross-section, not a panel** | this is the biggest DEMAND gap: no multi-year ACS series loaded despite the source supporting one back to ~2009 (5yr windows) |
| DEMAND | Daytime workers (jobs near address) | `lodes_wac` | LEHD LODES8 | registry temporal 2002–2023, `status: planned` — **no `staging`/`analysis` table found in the warehouse** | census block | **missing** (not ingested despite registry marking it verified-servable) | needs `loci ingest-lodes` run; would give a real 22-year annual jobs panel once loaded |
| DEMAND (long, low-freq) | Neighborhood-level income/demographic covariates, cross-sectional | `irs_zip_income` / `tract_covariates` / `tract_outcomes` (Opportunity Insights) | IRS SOI / Opportunity Insights (Chetty et al.) | single-year snapshots — IRS 2022 (`staging.public_irs_zip_income`, 9,222 rows / 1,537 ZIPs), Opportunity Atlas tract covariates/outcomes are historical-composite, not annual | ZIP / tract | present but **NOT in registry.yaml at all** (ingested via `src/loci/sources/public_signals.py`, ungoverned) | needs a registry.yaml entry (or explicit "excluded, ungoverned" note) before RQ-001 can cite it; not a time series either way |
| COST | Rent index (ZORI) / home value index (ZHVI) | `zillow_zori_zhvi` | Zillow Research | registry temporal 2000–current, monthly, `status: planned` — **no table in warehouse** (`grep`'d every table name for zori/zhvi/rent: zero hits) | ZIP | **missing** | needs an ingest adapter; this is the single most direct COST-pillar input the project could use, and it is entirely unbuilt |
| COST | Storefront vacancy (proxy for cost/oversupply pressure) | `nyc_dof_storefront_registry` | NYC DOF (Local Law 157) | **2019–2025** (7 yr), `analysis.storefront_year` (192,973 rows) | address (BBL/lot) | present | short window (post-2019 only); no rent level, self-reported, non-filing invisible |
| COST | Property value / assessed value proxy | `nyc_pluto` | NYC DCP | registry temporal 2002–2026 semiannual, `status: planned` — **no `analysis`/`staging` PLUTO table found**; `analysis.address` appears to be derived from PLUTO but PLUTO's own attribute history is not a stored panel | tax lot | present (as universe), not as a time series | PLUTO gives one current vintage per address, not year-over-year assessed value; would need archived annual PLUTO releases for a real cost panel |
| MACRO | NYC unemployment rate | none | BLS LAUS (via FRED) | — | — | **NOT REGISTERED** | no entry anywhere in `registry.yaml`; grep for fred/bls/unemployment/cpi/recession/qcew returns zero matches |
| MACRO | Restaurant-sector employment (NYC) | none | BLS QCEW / CES | — | — | **NOT REGISTERED** | same — nothing ingested or registered |
| MACRO | Interest rates (Fed funds / mortgage) | none | FRED | — | — | **NOT REGISTERED** | same |
| MACRO | CPI food-away-from-home | none | BLS CPI | — | — | **NOT REGISTERED** | same |
| MACRO | NBER recession dates | none | NBER | — | — | **NOT REGISTERED** | trivial to hand-code (public, static, ~12 rows since 1994) but not present as data or code anywhere in the repo |
| MACRO | COVID window flag | none | — | — | — | **NOT REGISTERED** | same as NBER — trivial to define (e.g. NYC PAUSE 2020-03 to reopening milestones) but not yet encoded |

## v0 feasibility

**A ZIP-tier panel combining DEMAND + SUPPLY + COST for ≥15 years can be built from data
already loaded, but only partially, and the DEMAND and COST pillars are far weaker than
SUPPLY.**

- **SUPPLY is solid**: `analysis.zip_establishments` / `analysis.zip_category_establishments`
  give a real 26-year (1998–2023) ZIP × NAICS/category annual panel with restaurant and bar
  counts. This alone clears the ≥15-year bar and is enough to build spells (favorable-tercile
  supply-side entries/exits) for the SUPPLY half of the composite.
- **COST is the weakest pillar and effectively absent at ZIP grain**: ZORI/ZHVI is
  registered but never ingested (zero tables), PLUTO is not stored as a multi-year panel, and
  the only cost-adjacent ZIP/address data (DOF storefront vacancy) only starts in 2019 — 7
  years, well short of 15. **v0 cannot build a real COST pillar for the long ZIP tier without
  first ingesting ZORI/ZHVI.** A rent-share-of-income or vacancy-only proxy could patch a
  post-2019 window but not the 1998–2018 stretch.
  - **DEMAND is single-cross-section, not a panel**: ACS is loaded as exactly one vintage
  (2023) rather than the multi-year 5yr-window series the registry claims is servable back to
  ~2009 (and, via non-overlapping 1-year ACS or decennial census, could reach further back for
  population alone). LODES (jobs) is registered `verified`/servable 2002–2023 but has **no
  table in the warehouse at all** — it was never actually ingested. Foot traffic (DOT
  pedestrian counts) exists 2007–2026 but at 114 fixed points, not ZIP grain, and is
  registry-scoped as validation/control, not a score input. **v0's DEMAND pillar at ZIP tier
  would have to run on a single repeated 2023 ACS cross-section (a level, not a trend) unless
  LODES is ingested and/or a multi-year ACS pull is added** — both are same-shape, bounded
  ingest jobs against sources already marked `verified`/servable in the registry.
- **MACRO is completely absent** — not one FRED/BLS/QCEW series or NBER/COVID flag exists
  anywhere in the registry or the warehouse. AC-10 ("test macro as a hazard driver... or
  states explicitly it is blocked") will have to be marked **BLOCKED** for this session unless
  a macro-ingest ticket is picked up first; these are free public series and a small lift.
- **Net verdict**: a defensible v0 **SUPPLY-led** ZIP-tier survival analysis (Kaplan–Meier on
  restaurant/bar density terciles, 1998–2023, 26 years, AC-8/AC-9 satisfiable) is buildable
  today from data already in the warehouse. A full three-pillar composite regime label
  (demand+supply+cost) is not achievable today without new ingests — COST is the binding
  constraint (nothing usable before 2019), with DEMAND close behind (one cross-section
  instead of a trend). Recommend v0 proceed as: build the composite on the years/ZIPs where
  data allows (post-2019 for cost, single 2023 income/demo level repeated across years as a
  static covariate for demand), state that compromise explicitly, and treat 1998–2018 as
  SUPPLY-only base-rate evidence pending the ZORI/LODES/multi-year-ACS ingests.

## Missing inputs → proposed tickets

- **RQ001-macro-ingest** — pull FRED/BLS series (NYC/NY metro unemployment, QCEW restaurant
  employment, effective fed funds or 10yr Treasury, CPI food-away-from-home) plus hand-coded
  NBER recession and COVID-window flags; blocks AC-10 entirely without it.
- **RQ001-zori-zhvi-ingest** — build the adapter for `zillow_zori_zhvi` (registered,
  `status: planned`, zero rows loaded); this is the single highest-value ticket for the COST
  pillar and the only source that can push COST back to 2000.
- **RQ001-lodes-ingest** — run `loci ingest-lodes` against `lodes_wac` (registered
  `verified`-servable 2002–2023, but no warehouse table exists); adds a real 22-year jobs/demand
  panel at block grain, aggregable to ZIP.
- **RQ001-acs-panel-backfill** — pull ACS 5yr estimates for multiple vintages (not just 2023)
  to turn `analysis.address_demographics`/`hex_demographics` from a single cross-section into
  an actual demand trend; registry already claims 2013–2024 coverage is servable.
- **RQ001-zbp-sic-decision** — explicit ruling on whether to attempt a hand SIC→NAICS
  crosswalk to recover 1994–1997 ZBP restaurant counts (would extend the SUPPLY panel from 26
  to 30 years) or formally cap the ZIP tier at 1998; currently an implicit skip (D42), not a
  decision scoped to this question.
- **RQ001-pluto-vintage-panel** — evaluate whether archived semiannual PLUTO releases can be
  assembled into a multi-year assessed-value/FAR panel as a second COST proxy alongside ZORI.
- **RQ001-dohmh-restaurant-zip-rollup** — filter `analysis.poi_first_seen` to restaurant/bar
  categories and roll up to ZIP-year to cross-validate the CBP/ZBP-derived SUPPLY panel with an
  independent near-census opening/closing series (available back to the DOHMH feed's real
  history, not just the registry's stated 2022–current).
- **RQ001-public-signals-registry-entry** — `irs_zip_income`/`tract_covariates`/
  `tract_outcomes` (Opportunity Insights) are ingested via `src/loci/sources/public_signals.py`
  but have no `registry.yaml` entry; register them (even as single-year/excluded) so
  `loci check-sources`-style governance covers them and RQ-001 can cite them without a
  registry gap.
- **RQ001-dot-pedcount-zip-feasibility** — assess (don't assume) whether the 114-point DOT
  pedestrian count series can contribute anything to a ZIP-tier demand signal (e.g. as a
  sparse validation check on whichever ZIPs happen to contain a count point) or should stay
  strictly out of the composite as the registry's `control`/validation-only role implies.
