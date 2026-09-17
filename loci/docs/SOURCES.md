# Loci — data source registry (live pipeline)

**GENERATED — do not edit.** Rendered by `loci gen-sources` from the non-wishlist entries in [`src/loci/registry.yaml`](../src/loci/registry.yaml). `loci check-sources` fails if this file differs from a fresh render, so a claim here is a claim in the registry with its dated evidence beside it.

Registry verified 2026-09-02. **46 sources** in or committed to the pipeline, grouped by role. The post-raise wishlist is generated separately into [`docs/PAID-SOURCES.md`](PAID-SOURCES.md); the per-source portability classing is generated into [`docs/PORTABILITY.md`](PORTABILITY.md).

## Business locations, present day

| Source | Dataset ID | Tier | Geography | Cost | Status | Known bias |
|---|---|---|---|---|---|---|
| **FDIC BankFind Locations (Summary of Deposits)** | - | universal | point | $0 | planned | FDIC-insured banks only; credit unions (NCUA) absent. Branch closures are dated, so this doubles as a panel. |
| **Foursquare Open Source Places** | - | universal | point | $0 | verified | Skews toward venues with consumer check-in history, i.e … |
| **NYC DCWP Inspections (Retail Laundry / Dry Cleaners)** | `jzhd-m6uv` | city | point | $0 | verified | Enforcement-driven, not a census: coverage begins 2023-07, so a retail laundry never inspected is absent and its absence is indistinguishable from a real gap … |
| **NYC DCWP Legally Operating Businesses** | `w7w3-xahh` | city | point | $0 | verified | Only DCWP-licensed categories (includes laundries, not groceries). |
| **Active NYC Health Code Regulated Child Care Programs** | `gy3q-4tzp` | city | point (lat/lon published; no geocoding needed) | $0 | verified | GROUP settings only — Health Code Article 47 (GCC) and Article 43 school-based (SBCC) … |
| **DOHMH New York City Restaurant Inspection Results** | `43nn-pn8j` | city | address + lat/lon | $0 | verified | Effectively unbiased -- every food establishment is inspected, so this is a near-census. The project's best data asset and the anchor for calibrating undercount in other sources. |
| **NYS Active Appearance Enhancement and Barber Business Licensees** | `y3u4-jbgh` | city | point | $0 | planned | SURVIVORSHIP-BIASED. Active licenses only; closed salons are absent entirely. Never use to construct openings/closings series. |
| **NYS Medicaid Enrolled Provider Listing — retail pharmacies** | `keti-qx5t` | city | point | $0 | verified | ANCHOR for the pharmacy category (was 0.000 coverage vs 1,330 MN+BK ZBP establishments) … |
| **NYS Liquor Authority Current Active Licenses** | `9s3h-dpkz` | city | point | $0 | verified | Active licenses only, BUT a companion inactive-licenses file (6dg3-2z7i) exists, so — unlike NYS DOS — closures are recoverable … |
| **OpenStreetMap (Overpass API)** | - | universal | point/polygon | $0 | planned | CRITICAL. Undercounts small business in lower-income and immigrant neighborhoods -- the same areas the thesis flags as underserved. See CONTEXT.md 7.1. |
| **Overture Maps Places** | - | universal | point | $0 | planned | Inherits OSM/Meta/Microsoft coverage gaps. Category schema is coarse for personal services (salons, laundromats). |
| **USDA SNAP Retailer Locator** | - | universal | point | $0 | verified | Near-census of stores that ACCEPT SNAP … |

## Longitudinal business panel

| Source | Dataset ID | Tier | Geography | Cost | Status | Known bias |
|---|---|---|---|---|---|---|
| **LEHD LODES Workplace Area Characteristics (LODES8)** | - | universal | census block | $0 | planned | Counts JOBS, not establishments. Census noise infusion at block level. Excludes most self-employed. See CONTEXT.md 7.4. |
| **NYS Liquor Authority Current Inactive Licenses** | `6dg3-2z7i` | city | point | $0 | verified | This is a CURRENT-inactives file, not an archive … |

## Outcome variables

| Source | Dataset ID | Tier | Geography | Cost | Status | Known bias |
|---|---|---|---|---|---|---|
| **Census American Community Survey, 5-year estimates** | - | universal | tract | $0 | planned | 5-year smoothing damps recent change. Tract-level MOEs are large and must be carried through interpolation, not discarded. |
| **HUD aggregated USPS vacancy data** | - | universal | tract | $0 | planned | Requires HUD user registration. "Vacant" is a carrier judgment; long-term vacancy definitions changed over time. |
| **NYC DCP Housing Database — Project-Level Files** | `br6q-ssj3` | city | point (building), with BBL and BIN | $0 | verified | Supply-side, and PUBLISHED SEMIANNUALLY: version 25Q4 carries data only to 2026-01-21, so every job filed or permitted since is absent … |
| **NYC DCWP License Applications** | `ptev-4hud` | city | point, with BBL, BIN and building number + street | $0 | verified | The APPLICATION side of w7w3-xahh, which publishes only issued licences … |
| **NYC DOB Certificates of Occupancy (BIS + DOB NOW)** | `bs8b-p36w`, `pkdm-hqz6` | city | point (building), with BBL and BIN | $0 | verified | FRESHNESS SUPPLEMENT to nyc_dcp_housing_db, joined on the DOB job number, not a standalone spine (it carries no filing or permit date and no net unit count) … |
| **DOB NOW: Build - Job Application Filings** | `w9ak-ipjd` | city | point (building), with BBL, BIN and house number + street | $0 | verified | THE FIT-OUT SIGNAL, and the noisiest of the seven … |
| **NYC DOB Permit Issuance + DOB NOW Approved Permits** | `ipu4-2q9a`, `rbx6-tga4` | city | point (building), with BBL and BIN | $0 | verified | ACTIVITY SUPPLEMENT to nyc_dcp_housing_db, joined on the DOB job number, never a spine (no unit count, no completion) … |
| **NYS SLA Current Pending Licenses** | `f8i8-k2gm` | city | point (georeference), premises address; NO BBL and NO BIN | $0 | verified | THE EARLIEST SIGNAL THE CITY PUBLISHES … |
| **Zillow Observed Rent Index / Home Value Index** | - | universal | zip | $0 | planned | ZORI covers ~8.4k ZIPs nationally (a third of ZHVI's). Asking-rent index, listing-density dependent. ZIP is much coarser than an H3 res-9 hex. |

## Controls and context

| Source | Dataset ID | Tier | Geography | Cost | Status | Known bias |
|---|---|---|---|---|---|---|
| **Citi Bike System Data (trip files)** | `citibike-tripdata` | city | point (dock) | $0 | verified | NOT A PEDESTRIAN COUNT, and this is the most important thing to say about anything built from it … |
| **MTA Bus GTFS static (stops)** | - | city | point | $0 | planned | Stop presence, not service frequency; frequency needs the schedule join. |
| **MTA Subway Entrances and Exits 2024** | `i9wp-a4ja` | city | point | $0 | verified | A 2024 SNAPSHOT: entrances close for construction and the file does not track it … |
| **MTA Subway Hourly Ridership 2020-2024** | `wujg-7c2s` | city | station complex | $0 | verified | Pandemic-era window; 2020-21 levels are not representative. |
| **MTA Subway Hourly Ridership: Beginning 2025** | `5wq4-mkjj` | city | station complex (point), split to entrances via i9wp-a4ja | $0 | verified | ENTRIES ARE NOT FOOTFALL, and this is the single most important thing to say about the column built from them … |
| **MTA Subway Stations** | `39hk-dx4f` | city | point | $0 | planned | Station centroid understates walk distance from far entrances. |
| **NYC borough boundaries, shoreline, and Neighborhood Tabulation Areas** | - | city | polygon | $0 | planned | none material |
| **NYC Street Centerline (CSCL)** | `inkn-q76z` | city | line | $0 | verified | shape_length is WEB MERCATOR metres (x1.32 at NYC latitude), NOT a length; segmentlength is US feet and disagrees with the geometry on a minority of rows (p05 0.30, p95 1.64 of … |
| **NYC DOE Demographic Snapshot (school-level enrollment + composition)** | `s52a-8aq6`, `c7ru-d68s`, `vmmu-wj3w`, `nie4-bv6q` | city | one row per school (DBN), no coordinates on the snapshot itself. The address join is NOT school-point proximity -- it is address-in-polygon against the DOE elementary school zone file (dataset cmjf-yawu, "School Zones 2024-2025 (Elementary School)": the_geom MultiPolygon + dbn, confirmed tabular and current), because enrollment is a school-ZONE-grain signal, not a school-POINT one (charter/private/out-of-zone leakage means a school's own address is not where its pupils live). wg9x-4ke6 ("2019-2020 School Locations", geocoded, lat/lon per DBN) is the fallback point join if a zone polygon is ever unavailable for a DBN; it is the newest tabular NYC Open Data school-location vintage found and is itself six years stale.
 | $0 | planned | ENROLLMENT IS NOT RESIDENT CHILDREN: charter, private and out-of-zone leakage all sit outside a zoned public school's roster … |
| **NYC DOF Storefronts Reported Vacant or Not (Local Law 157 of 2019)** | `92iy-9c3n` | city | point (storefront), with BBL, BIN, NTA and census tract | $0 | verified | SELF-REPORTED by property owners, and NON-FILING IS INVISIBLE: a landlord who does not file does not appear as vacant, they do not appear at all, and there is no non-response flag … |
| **NYC DOT Bi-Annual Pedestrian Counts** | `cqsj-cfgu` | city | point (screenline location) | $0 | verified | NOT A SAMPLE OF THE CITY … |
| **NYC DOT traffic cameras (NYCTMC public feed)** | - | city | point (signalised intersection) | $0 | verified | THE SITING IS THE BIAS … |
| **NYC Energy and Water Data Disclosure (Local Law 84 / LL133)** | `5zyy-y8am`, `7x5e-2fxh`, `usc3-8zwd`, `wcm8-aq5w`, `4tys-3tzj`, `4t62-jm4m`, `77q4-nkfh`, `r6ub-zhff` | city | tax lot | $0 | verified | COVERAGE IS A SIZE FILTER, NOT A SAMPLE … |
| **NYC MapPLUTO (Primary Land Use Tax Lot Output)** | - | city | tax lot | $0 | planned | Assessment-derived; ZoneDist reflects mapped zoning, not variances or overlays in effect. |
| **OSM pedestrian network via OSMnx** | - | universal | graph | $0 | planned | Sidewalk-level detail is uneven; most NYC walk routing runs on the centerline graph, which slightly understates crossing friction. |
| **StreetEasy listing pages (advertised in-building laundry, via Tavily)** | - | city | point | $0 | verified | ADVERTISING, NOT INSPECTION — "Laundry in building" is a claim made to let a lease; nobody verified it … |

## Validation

| Source | Dataset ID | Tier | Geography | Cost | Status | Known bias |
|---|---|---|---|---|---|---|
| **Census County Business Patterns (CBP), national -- counties, metros and ZIPs** | - | universal | county, metropolitan statistical area, zip | $0 | verified | PAYROLL establishments only … |
| **Census ZIP Code Business Patterns (ZBP), via the County Business Patterns (CBP) API** | - | universal | zip | $0 | verified | VALIDATION AND CALIBRATION ONLY -- must never feed the gap flag … |
| **Google Places API — Nearby Search** | - | universal | point | $32.0/per_1000_calls | planned | Ground truth for the stratified coverage-bias validation (prediction P3). |
| **NYC DOT VivaCity sidewalk sensors (data-sharing ask)** | - | city | point (sensor at an intersection) | $0 | planned | Sited by DOT for traffic engineering, so placement is DOT's operational priority, not a sample frame — but the 2026 expansion is the first NYC sidewalk-count program that … |
| **Strava Metro (street-segment activity counts)** | - | universal | line (street segment) | $0 | planned | Athletic and recreational trips, not errand walking — the wrong behaviour for a daily-needs screen, and the skew is toward younger, higher-income, app-owning users, i.e … |

## Excluded

| Source | Dataset ID | Tier | Geography | Cost | Status | Known bias |
|---|---|---|---|---|---|---|
| **IRS SOI county-to-county migration** | - | universal | county | $0 | excluded | Only 5 units in NYC. |
| **NYS Office of Professions — registered pharmacies** | - | city | address | $0 | excluded | Registered establishments; address-only, needs geocoding. |

