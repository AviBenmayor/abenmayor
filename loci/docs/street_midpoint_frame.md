# The street-midpoint sampling frame

**Status:** VERIFY-AND-DESIGN pass, 2026-09-13. Nothing in `src/`, `tests/` or the warehouse
was changed to produce this; every number below is from live probes of NYC Open Data and
read-only queries against `data/loci.duckdb` and the persisted walk graph.

**Owner direction (2026-09-13):** *"for addresses, we should be sampling an address near the
middle of every known street in the borough."*

**Confirmed reading:** one scored point at the midpoint of every street **segment**
(intersection-to-intersection stretch), scored by exactly the same engine as an address, so an
undeveloped street with no residential lots appears on the map instead of being invisible
because nobody lives there yet. Same motive as D75 (the eligibility gate removal): underdeveloped
areas must count.

*(The literal reading — one point per **named street** — is wrong for this purpose. MN+BK has
2,400 distinct `full_street_name` values against 32,291 segments; one point on Broadway is not a
retail screen.)*

Scope: **MN + BK only (D78).**

---

## 1. Step 1 — the source, verified

### 1.1 Dataset facts (probed live, 2026-09-13)

| Fact | Value |
|---|---|
| Dataset | **NYC Street Centerline (CSCL)**, titled *"Centerline"* on NYC Open Data |
| Socrata id | **`inkn-q76z`** — confirmed, the candidate id in the brief is correct |
| Publisher / originator | Office of Technology and Innovation (OTI); originator DCP (Centerline Maintenance Group) |
| Update | Automated, **weekly** (metadata `rowsUpdatedAt` 2026-09-11) |
| Geometry type | `MultiLineString` |
| CRS from the SODA API | **WGS84 lon/lat (EPSG:4326)** — the *shapefile* distribution is EPSG:2263 (NAD83 / NY Long Island, **US survey feet**) |
| Columns | 64 |
| Rows citywide | **122,310** |
| Rows MN (`boroughcode='1'`) | **14,106** |
| Rows BK (`boroughcode='3'`) | **27,678** |
| Rows MN+BK | **41,784** |
| Data dictionary | `Centerline.pdf`, attachment `4cff63bb-aeb0-4ca3-adb5-d6027dc133d5` on the dataset (covers the shapefile field set; `STATUS`, `NONPED`, `SEGMENT_TYPE` are **not** documented there) |

**Fields that matter:** `physicalid`, `the_geom`, `rw_type`, `status`, `nonped`, `trafdir`,
`boroughcode`, `segmentlength`, `shape_length`, `full_street_name`, `street_name`, `streetwidth`,
`from_level_code`, `to_level_code`, `l_low_hn`/`l_high_hn`/`r_low_hn`/`r_high_hn`,
`l_zip`/`r_zip`, `l_blockfaceid`/`r_blockfaceid`, `posted_speed`, `created_date`,
`modified_date`, `globalid`.

**`segment_type` / `segment_type_value` are 100% NULL** in MN+BK (41,784 of 41,784). They exist as
columns and would look like a usable feature-type vocabulary to anyone reading the column list.
They are not. **Use `rw_type`.**

`physicalid` is "a unique ID assigned to intersection-to-intersection stretches of a street"
(data dictionary) — it is *near*-unique, not unique: **3 duplicated ids in MN+BK** (180347,
186403, 207001), all three outside the kept set. The id generator must not assume uniqueness
without asserting it.

### 1.2 Two length traps (neither of which the database can catch)

`data/loci.duckdb` uses DuckDB `GEOMETRY`, which **carries no SRID**. Every length below has to be
derived deliberately.

| Column | What it actually is | Evidence |
|---|---|---|
| `shape_length` | **Web Mercator metres** — inflated by the Mercator scale factor 1/cos φ. **Not a length.** | median(`shape_length` / geodesic m) = **1.3211** over 41,784 MN+BK rows, p05 1.318 / p95 1.324; 1/cos(40.7°) = **1.3190** |
| `segmentlength` | **US feet**, but unreliable on a minority of rows | median(`segmentlength`×0.3048 / geodesic m) = **1.0011**, but **p05 0.302, p95 1.637** |
| `ST_Length(geom)` on the ingested 4326 geometry | **degrees** — a meaningless number that will not error | 0.00107 for a 91 m segment |

**Rule: compute every length from the geometry, reprojected explicitly.** Verified in DuckDB
(spatial `eb1e57c`) on a real Laight St segment — all three agree to 0.1 m:

```sql
-- 91.10 m.  always_xy := true is REQUIRED; EPSG:2263 is US survey FEET.
ST_Length(ST_Transform(geom, 'EPSG:4326', 'EPSG:2263', always_xy := true)) * 0.3048006096012192
```
(geodesic reference 91.0 m; `segmentlength` 298.897 ft = 91.10 m; `shape_length` 120.05 → wrong by
+32%.)

### 1.3 The feature-type vocabulary, MN+BK

`rw_type` (data dictionary, p. 8–9), with the length each type contributes:

| `rw_type` | Label | n (MN+BK) | km | median len (m) | Keep? |
|---:|---|---:|---:|---:|:--|
| 1 | **Street** | 32,762 | 3,508.4 | 81.7 | **YES** |
| 2 | Highway | 1,299 | 185.8 | 80.8 | no |
| 3 | Bridge | 1,698 | 106.8 | 34.2 | no |
| 4 | Tunnel | 149 | 13.4 | 40.5 | no |
| 5 | Boardwalk | 27 | 4.8 | 119.2 | no |
| 6 | Path/Trail | 2,602 | 268.4 | 58.8 | no |
| 7 | StepStreet | 79 | 2.9 | 27.3 | no |
| 8 | Driveway | 177 | 16.4 | 62.0 | no |
| 9 | Ramp | 1,187 | 100.7 | 56.1 | no |
| 10 | Alley | 1,333 | 99.5 | 53.2 | no |
| 11 | Unknown | 0 | — | — | — |
| 12 | **Non-Physical Street Segment** (the paper streets) | 2 | 0.0 | 8.0 | no |
| 13 | U Turn | 63 | 1.1 | 13.4 | no |
| 14 | Ferry Route | 406 | 237.1 | 153.6 | no |

`status`: **2 = Constructed** is essentially everything (citywide 122,272 of 122,310; MN+BK 41,767).
The other two values are rare and unlabelled in the dictionary but read cleanly off the data:
`status='4'` (5 rows citywide) is *proposed* — "URBAN VILLAGE DR", "INNOVATION WAY E",
"INSPIRATION LN", street names that do not exist yet; `status='5'` (33 rows) is a mix of demapped
and re-mapped stretches (Murray Hulbert Ave, N 9/10/11 St).

`nonped`: `V` = **vehicles only, pedestrians prohibited** (3,485 rows MN+BK — Brooklyn Bridge
roadway, Shore Pkwy, the Hugh L Carey and Lincoln tunnel approaches, DSNY marine-transfer ramps).
`D` (1,653) is *not* a pedestrian prohibition — it covers the Central Park and Prospect Park
drives, the 65/86 St transverses, **and** Manhattan Beach Promenade and the Williamsburg Bridge
pedestrian path. `D` is undocumented and self-contradictory as a pedestrian flag; **do not use it.**

### 1.4 The "known street" rule

```
status      = '2'     -- Constructed
rw_type     = 1       -- Street  (the only type that carries house-number ranges
                      --  and can front a storefront)
nonped     <> 'V'     -- pedestrians are not prohibited
from_level_code = '13' AND to_level_code = '13'   -- at grade
```

Deliberately **kept** even though they look excludable: `trafdir='NV'` on a Street (161 rows) — these
are pedestrian malls and plazas (Fulton Mall, Dyckman St, Pierrepont/Montague/Clark St ped-ways).
They are real retail streets.

Deliberately **excluded** and why: highways/ramps/tunnels/bridges (no storefront frontage, and a
midpoint on a bridge is not a site); Path/Trail (2,602 park and greenway paths — the "private
drives inside parks" case, all of them); Boardwalk, StepStreet, Driveway, Alley, U-Turn, Ferry
Route; `rw_type=12` **Non-Physical Street Segment** is CSCL's own name for the paper streets, and
there are exactly **2** of them in MN+BK; above/below-grade duplicates of a street footprint.

**The ladder — what each clause costs:**

| Step | Rows | Δ | km |
|---|---:|---:|---:|
| all MN+BK rows | 41,784 | | 4,545.3 |
| `+ status='2'` | 41,767 | −17 | 4,542.7 |
| `+ rw_type=1` | 32,745 | −9,022 | 3,505.8 |
| `+ nonped<>'V'` | 32,427 | −318 | 3,487.5 |
| `+ at grade (13/13)` | **32,291** | −136 | **3,476.8** |

**Kept: 32,291 segments — MN 9,043 (876.9 km), BK 23,248 (2,600.0 km).** 2,400 distinct street
names; 0 rows with a NULL `full_street_name` (54 are literally named `UNNAMED ST`).

### 1.5 Length distribution of the kept set, and L

| stat | m |
|---|---:|
| min | 1.4 |
| p05 | 12.8 |
| p25 | 66.3 |
| **median** | **81.9** |
| p75 | 143.4 |
| p90 | 237.0 |
| p95 | 252.6 |
| p99 | 293.9 |
| max | 2,502.4 |
| mean | 107.7 |

MN median 79.9 / p99 302.7 / max 1,088.1. BK median 82.3 / p99 289.8 / max 2,502.4.
Segments over 400 m: 74. Over 800 m: 9. Over 1,600 m: 1. Under 20 m: 2,945.

**The median segment is 81.9 m — the NYC block face.** So "one midpoint per segment" already means
"one point per block face" for the great majority, and L only decides how the long tail is handled.

Splitting rule: `k = ceil(len / L)` points at arclength fractions `(2i−1)/2k`, `i = 1..k` — evenly
spaced, no point on an endpoint, so two adjacent segments never put two points on the same corner.

| L (m) | points | MN | BK | orphans (no lot ≤100 m) | orphan % | max realised spacing |
|---:|---:|---:|---:|---:|---:|---:|
| 80 | 58,825 | 15,122 | 43,703 | 5,244 | 8.9% | 80 |
| **100** | **48,969** | **12,774** | **36,195** | **4,507** | **9.2%** | **100** |
| 120 | 44,536 | 11,917 | 32,619 | 4,147 | 9.3% | 120 |
| 160 | 39,277 | 10,261 | 29,016 | 3,651 | 9.3% | 160 |
| 200 | 37,357 | 9,926 | 27,431 | 3,407 | 9.1% | 200 |
| 250 | 33,983 | 9,478 | 24,505 | 3,245 | 9.5% | 250 |
| none (1/segment) | 32,291 | 9,043 | 23,248 | 3,015 | 9.3% | 2,502 |

**How much information a coarser L loses** — measured, not assumed. On the L=160 prototype run,
6,797 segments got ≥2 points; comparing the points *within* a segment:

| realised spacing | segments | median `gap_score` spread | p90 | segments whose points disagree on `lead_category` |
|---|---:|---:|---:|---:|
| 60–90 m | 1,123 | 0.183 | 0.394 | 24.6% |
| 90–120 m | 3,531 | 0.236 | 0.543 | 34.5% |
| 120–160 m | 2,143 | 0.286 | 0.622 | 39.7% |

The curve is monotone with **no plateau**: the screen genuinely varies at the block scale — the
same instability D39 found in the "exactly one missing" list, reappearing spatially. There is no
"safe" L; there is only a choice of resolution.

**Recommended L = 100 m** — the smallest round value at or above the median MN+BK block face
(81.9 m). Every street point then stands for at most **one block face**, the same spatial unit a
PLUTO lot frontage occupies, so the street frame is no coarser than the lot frame it sits beside.
That gives **48,969 points** on 32,291 segments. Because the marginal compute is ~13 s (§5), the
tighter L costs essentially nothing; the only real cost of a fine L is map clutter, and §4 handles
that with a `frame` column rather than with a coarser sample.

The orphan **share** is flat at ~9.3% across every L — a property of the geography, not of the
sampling.

**Multipart geometries:** 565 of the 32,291 kept segments are multipart. The prototype used the
longest part only, which drops **33.4 km (0.96%)** of kept length. The production builder must
allocate `k_p = ceil(len_p / L)` points **per part**.

---

## 2. Step 2 — prototype (read-only, nothing persisted)

**Run:** L=160, all 39,277 MN+BK street points, live DB, `reach_source='tiers'`
(`reach_hash f6339bf9d842`), `supply_set='principled'` (`supply_hash 767b28674e30`), walk graph
`walk_graph.pkl:1788298912:306836099`, pruned to **N = 605,130** nodes, per-node distance matrix
read from the **existing cache** `data/interim/node_nearest_m_1b4ab8a0ffec7ef7.parquet`. Points
were snapped with the same `ox.distance.nearest_nodes` call the address frame uses and scored with
`compute_gap_metrics` unmodified.

### 2.1 The owner's case, quantified

| no residential lot within | points | share | MN | BK |
|---:|---:|---:|---:|---:|
| 50 m | 8,162 | 20.8% | 3,131 | 5,031 |
| **100 m** | **3,651** | **9.3%** | **1,555** | **2,096** |
| 200 m | 1,452 | 3.7% | 652 | 800 |
| 400 m | 701 | 1.8% | 431 | 270 |

**3,651 street points (9.3%) sit where the screen currently has nothing at all** — at L=100 that
becomes 4,507. These are the places the owner says must not be invisible.

### 2.2 Their gap profile vs the addresses nearby

| frame | n | median `gap_score` | p90 | mean `n_missing` | mean `present_count` | `gap_score>1` | `lead_censored` |
|---|---:|---:|---:|---:|---:|---:|---:|
| **orphan street points** (no lot ≤100 m) | 3,651 | **2.07** | **7.50** | **5.75** | 10.9 | **90.6%** | **19.1%** |
| street points with lots ≤100 m | 35,626 | 1.24 | 2.50 | 1.82 | 14.1 | 65.2% | 4.6% |
| **lots** (live `analysis.address`) | 281,842 | 1.27 | 2.50 | 1.89 | 14.1 | 67.8% | 4.2% |

Lead-category mix (%):

| lead | orphan street | street w/ lots | lots |
|---|---:|---:|---:|
| laundry | **51.9** | 21.4 | 19.0 |
| bar | 18.8 | 26.1 | 29.9 |
| convenience | 13.3 | 16.0 | 11.2 |
| tailor_repair | 7.5 | 18.2 | 20.1 |
| bank | 4.2 | 10.1 | 11.3 |
| cafe_bakery | 3.5 | 4.8 | 4.9 |

The orphan points are a **different population**, not more of the same: three times the missing
categories, three fewer present, and half of them led by laundry.

### 2.3 Consistency check — the frame is the same measurement

Where a street point lies within 50 m of an existing lot (**n = 31,115**):

* same `lead_category`: **93.1%**
* `gap_score` difference: **median +0.000**, p05 −0.14 / p95 +0.15, |diff| > 0.25 on **2.9%**

The street frame is not a second screen producing a second answer. It is the same screen at a
different set of points. *(This is the single strongest argument for design option (a) below.)*

### 2.4 The 701 that are not sites — and why no gate is needed

The orphans split cleanly on how many lots sit inside a 400 m radius:

| lots within 400 m | n | median `gap_score` | censored lead | top lead |
|---|---:|---:|---:|---|
| **0** | **701** | **7.50** | **78%** | laundry |
| 1–50 | 971 | 2.05 | 1% | laundry |
| 51–200 | 1,215 | 1.55 | 3% | laundry |
| 201+ | 764 | 1.76 | 13% | laundry |

The 701 with **zero** lots in 400 m are, by NTA: **Randall's/Wards Island** (MN1191, 284 points —
Bronx Shore Rd, Central Rd, Rivers Edge Rd, Wards Meadow Loop), **Floyd Bennett Field / Gateway
NRA** (BK5691, 133 — Aviation Rd, Ranger Rd), **Governors Island** (MN0191, 123 — Craig Rd N),
plus Central Park, Prospect Park, Marine Park and Fort Hamilton. Their median `gap_score` of
**7.50 is exactly `CAP_M/reach(laundry)` = 2400/320** — i.e. it is the censoring cap, not a
measurement, and **78% of them have a censored lead**.

**These would top an unfiltered `gap_score` ranking for a purely mechanical reason.** But they do
not need a gate — reintroducing one would be D75 in reverse. `homes_400m` (D73) is already on
`analysis.address`, is computed from `units`, and is **0** for every one of these points, so the
owner's other direction — **rank by density** (`--rank-by density`, already shipped) — removes
them automatically and for a stated reason. That is the mechanism; nothing new is required.

### 2.5 The two prototype NTAs the brief asked for, plus neighbours

| NTA | | street pts | lots | orphans | orphan % | median `gap_score` (street / orphan) | orphan lead |
|---|---|---:|---:|---:|---:|---|---|
| BK0261 | **Brooklyn Navy Yard** (industrial) | 176 | 47 | 128 | **72.7%** | 2.35 / **2.44** | laundry |
| BK0104 | **East Williamsburg** (industrial) | 846 | 3,677 | 175 | 20.7% | 1.21 / **2.54** | laundry |
| BK0601 | Carroll Gdns–Cobble Hill–Gowanus–**Red Hook** | 997 | 5,733 | 154 | 15.4% | 1.14 / 1.86 | laundry |
| BK0702 | **Sunset Park (West)** (industrial) | 839 | 4,418 | 110 | 13.1% | 0.99 / 1.76 | laundry |
| MN0302 | Lower East Side | 372 | 735 | 85 | 22.8% | 0.73 / 1.77 | bar |
| BK0402 | **Bushwick (East)** (dense) | 495 | 5,981 | **4** | **0.8%** | 1.29 / 2.18 | tailor_repair |

The contrast is the whole finding. In dense Bushwick (East) the street frame adds **4** points the
lot frame did not already cover — it is pure redundancy there. In the Navy Yard it adds **128 of
176**, and they score worse than anything the screen currently sees.

Selection was by lowest lots-per-km of kept street: Navy Yard 3.6, Spring Creek–Starrett City 27.0,
Downtown BK–DUMBO–Boerum Hill 34.4, Coney Island–Sea Gate 49.6, East Williamsburg 50.4 … Park Slope
150.4, Sunset Park (Central) 150.4.

### 2.6 Clustering — the result that decides §4's second question

Gap rows (`gap_score > 1`): **190,973 lots, 26,544 street points.** The live screen has **571**
lot clusters. Re-running `_cluster_gap_addresses` (eps 200 m, grouped by borough × lead) over the
**union**:

| | count |
|---|---:|
| clusters, lots only (today) | **571** |
| clusters, joint | **559** |
| … containing ≥1 lot | 454 |
| … containing ≥1 street point | 534 |
| … mixed | **429** |
| **street-only clusters** (the new signal) | **105** |

Joint clustering produces **fewer** clusters, not more — street points bridge gaps between
previously separate lot clusters and **fuse** them. BK `bar` alone goes 57 → 44. And **429 of the
571 existing clusters change membership and id.**

---

## 3. Step 3a — design comparison

### Option (a) — extend the existing grain (RECOMMENDED)

`analysis.address` gains a `frame` column (`'lot' | 'street'`). Street points become rows with
`address_id = 'seg:<physicalid>[:<k>]'`, `bbl` NULL, `units` 0, `units_capped` 0, `lon`/`lat` at the
sampled point, `borough` from CSCL `boroughcode`, `nta_code`/`neighborhood`/`h3_index` by the same
res-9 `analysis.hex` lookup the lot frame already uses. `analysis.address_category` gets their 15
rows each. `analysis.address_gaps` (the view) gains `frame`.

### Option (b) — a sibling table `analysis.street_point` + a union view

### Recommendation: **(a)**

1. **The measurement is identical.** §2.3: within 50 m of a lot, a street point reproduces that
   lot's lead 93.1% of the time with a median `gap_score` difference of exactly 0.000. A sibling
   table would assert a distinction the data says is not there.
2. **One screen-point grain.** The map, the density ranking, the cluster list and every
   `UPDATE`-only layer (D62/D67/D73/D76/D81) are keyed on `analysis.address` rows by
   `(borough, address_id)`. Option (b) means a second code path in each of those, or a union view
   that no `UPDATE` can write through.
3. **The no-proliferation rule (D61) says so.** The owner's standing rule: *pivots and subsets
   become views, new measures extend the existing grain, a genuinely new grain may be a table.*
   A street midpoint is not a new grain — it is the same grain (a scored point with a lon/lat)
   sampled a different way. `frame` is the discriminator, and every "street only" or "lot only"
   consumer is a `WHERE frame = …` view.

**What (a) costs, and the guard:** every consumer that previously could assume
"row ⇒ residential tax lot with a BBL and units > 0" now needs a stated position. §3b is that list,
and §4 is the set of invariants that make the change *non-filtering* for the lot frame — the same
proof pattern D57/D61 used for the demand annotation.

### 3a.1 Clustering: street points must cluster **separately**

**Recommendation: cluster within `frame`** — group by `(borough, frame, lead_category)`, not by
`(borough, lead_category)`.

Why, from §2.6:

* Joint clustering **changes the id and membership of 429 of the 571 existing clusters** and
  **merges 12 net** (BK bar 57 → 44). The project's whole method of showing that a change is safe
  is "the top-50 cluster list has member Jaccard 0.926 against the previous run" (D75). Joint
  clustering destroys that continuity for a reason that has nothing to do with retail.
* A street point has **no residents**. Letting one fuse two lot clusters that the screen previously
  called distinct opportunities is a merge bug in the same family as the dedup failures this
  project has already been bitten by — a point with zero demand silently becoming the bridge that
  makes two markets look like one.
* Separate clustering still yields the new signal cleanly: **105 street-only clusters**, in their
  own namespace `"{borough}:street:{lead}:{k}"`, which is exactly what "an undeveloped street shows
  up on the map" means.

The adjacency the owner will want ("this street cluster is next to that lot cluster") is a
**derived, non-mutating** column — `adjacent_lot_cluster_id`, the nearest lot cluster with the same
lead within 200 m — or a view. Never a shared id.

### 3a.2 Density ranking

`--rank-by density` (`cluster_density_400m` from `homes_400m` / walk-shed area, in flight from the
other agent) works for street points **as-is**: `homes_400m` is a catchment sum over `units` of
*other* rows, so a units-0 street point still gets a real, non-zero density wherever homes are
nearby — and exactly 0 on Randall's Island. No change needed. This is also the mechanism that
retires §2.4's 701 non-sites without a gate.

---

## 3b. Per-layer compatibility

`✓` works unchanged · `⚠` needs a guard · `✗` must skip street rows

| Layer | Driver | Verdict | Note |
|---|---|:--:|---|
| `address-gaps` screen (`model/address_gaps.py`) | lon/lat → node cache | ✓ | `units_capped`=0; `present_count`, `gap_score`, `n_missing`, `censored` all well-defined |
| clustering (same module) | lon/lat + lead | ⚠ | **group by `(borough, frame, lead)`** (§3a.1) |
| `address-demand` (`model/address_demand.py`) | `LEFT JOIN address_demographics` | ✓ | no demographics ⇒ `income_ratio` NULL ⇒ **fails closed**: street rows are never demand-caveated. Correct default; state it in the card. |
| `address-demographics` (`model/address_demographics.py`) | merge on `bbl` vs PLUTO | ✗ | its grain **is** the tax lot (D56). Guard `bbl IS NOT NULL` so a NULL-bbl row cannot merge. |
| `pipeline` / `pipeline-activity` (`model/dev_pipeline.py`) | lon/lat catchment over `analysis.dev_pipeline` | ✓ | permitted units near an industrial street is a *useful* number |
| `storefronts` (`model/storefronts.py`) | `SELECT address_id, borough, lon, lat` | ✓ | |
| `age-fit` (`model/age_fit.py`) | `JOIN address_demographics USING (address_id)` (**inner**) | ✓ | street rows drop out; `age_fit_lead`/`gap_score_fit` stay NULL. Its NTA aggregation weights by capped units, which is 0 anyway. |
| `supply-ratio` — `homes_400m` (`model/supply_ratio.py`) | every `analysis.address` row, `COALESCE(units,0)` | ⚠ | street rows add **0** to every lot's `homes_400m` (exact), and *receive* a real `homes_400m`. **GUARD: `supply_baseline.yaml`'s fit universe must stay `frame='lot'`** — it was re-fit under D75 on n=281,842 "all addresses with `homes_400m` > 0"; letting street rows in moves the baseline every `supply_ratio_vs_base` is measured against. |
| `supply-ratio` — `addressable_homes_400m_laundry` | per-lot units × haircut | ✓ | units 0 ⇒ 0 |
| `address-access` (`model/address_access.py`) | `SELECT address_id, borough, lon, lat` | ✓ | |
| `transit-profile` (`model/address_transit_profile.py`) | same | ✓ | |
| `revenue` (`model/revenue.py`) | `analysis.address` as *both* scored points and the `homes` weight, `COALESCE(units,0)` | ⚠ | weights unchanged (exact). **GUARD: the calibration / leave-one-ZIP-out backtest folds must filter `frame='lot'`** — a units-0 point is not an observation of realised receipts. |
| `address_character` (view) / `invest` | PLUTO by `bbl` | ✗ | no lot ⇒ no CommFAR / RetailArea. A street cluster's card must say "no tax lot; feasibility not assessed". |
| `recommend` (`model/recommend.py`) | `FROM analysis.address a`, uses `a.bbl` | ⚠ | evidence-coverage and laundry-evidence stats divide by BBL count — must use lot rows only, or report 0/0 honestly |
| `validate` (`validation/sample.py`) | `NTILE(10)` over `address_demographics.median_hh_income` | ✗ | street rows have no decile ⇒ **filter `frame='lot'`**, else a NULL stratum silently appears and the Google budget plan changes |
| `conveniences` report (`model/conveniences.py`) | unit-weighted shares + a per-**address** distribution | ⚠ | unit-weighted shares are **exactly unchanged** (denominator is `sum(units)`); the per-address `n_unsatisfied` distribution would move — **filter `frame='lot'`** there |
| `export-webmap` (`viz/webmap_export.py`) | `FROM analysis.address_gaps WHERE {cat}_ratio > 1` | ⚠ | street rows appear **automatically** — 26,544 extra dots. Must carry `frame` into the tiles and give the map a toggle (default: street layer off, or on only where `homes_400m > 0`). |
| `sql/004–006` laundry views, `address_laundry_evidence` | join on `bbl` | ✓ | street rows have NULL bbl and drop out |
| `poi_presence`, `storefront_pipeline`, `chains`, `zbp-compare`, `comps` | keyed on POIs / bbl / hex | ✓ | do not read `analysis.address` at the row grain |

---

## 4. Invariants and tests to pin

The load-bearing claim is: **adding street rows changes nothing about the lot rows.** This is the
same non-filtering proof D57/D61 ran for the demand annotation; run it again.

1. **Lot checksums byte-identical.** `hash-sum` of `gap_score`, `lead_category`, `n_missing`,
   `eligible`, `present_count`, `cluster_id` on `analysis.address WHERE frame='lot'`, and of
   `nearest_m`, `ratio`, `is_lead`, `censored` on `analysis.address_category WHERE frame='lot'`,
   before and after. (`cluster_id` is in the list only because §3a.1's within-frame clustering
   makes it survivable — if it moves, joint clustering has crept back in.)
2. **Σ units unchanged.** `sum(units)` and `sum(units_capped)` over the whole table equal their
   pre-change values exactly; street rows are 0, not NULL, so `homes_400m` arithmetic is unaffected.
3. **Row counts.** `count(*) WHERE frame='lot'` = 281,842 (MN 32,390 / BK 249,452);
   `count(*) WHERE frame='street'` = the builder's point count;
   `count(analysis.address_category)` = 15 × `count(analysis.address)`, exactly.
4. **Non-filtering identity, extended.** `count{ratio > 1}` = `sum(n_missing)` over the whole
   table **and** within each frame separately.
5. **Monotonicity (D75 part b) re-run over the union**: reach × 0.8 removes exactly **zero** pairs.
6. **`address_id` namespaces are disjoint.** `'seg:'`-prefixed ids cannot collide with a BBL
   (10-digit numeric); assert `count(*) WHERE frame='street' AND address_id NOT LIKE 'seg:%' = 0`
   and the converse, and assert `point_id` uniqueness at build time (the 3 duplicate `physicalid`s
   in MN+BK are the reason this is not a comment).
7. **`supply_baseline.yaml` universe pinned** at n = 281,842 / `universe: "all LOT addresses with
   homes_400m > 0"`, and the fit refuses to run on a frame-mixed universe.
8. **D78 scope.** Street rows carry `borough` from CSCL `boroughcode`; `prune_out_of_scope`
   deletes them on the same rule with no special case. (The res-9 hex lookup disagrees with CSCL
   `boroughcode` on 120 of 39,277 points at river edges — **use CSCL's borough, not the hex's**,
   and use the hex only for `nta_code`.)
9. **Provenance stamped once**, on `analysis.address`: street rows carry the identical
   `reach_source` / `reach_hash` / `graph_version` / `supply_set` / `supply_hash` / `run_at` as the
   lot rows of the same run, plus two new columns — `frame_source` (`'nyc_cscl'`) and
   `frame_vintage` (the CSCL extract date) — NULL on lot rows.
10. **`frame` is `NOT NULL` with `CHECK (frame IN ('lot','street'))`** and `DEFAULT 'lot'` on the
    `ALTER`, so every pre-existing row is correct without a backfill pass.
11. **`shape_length` appears nowhere.** A grep test, and a build-time assertion that computed
    length / `segmentlength`×0.3048 has median within 1% of 1.0.

---

## 5. Step 4 — cost

**Dijkstra: zero additional.** The per-node distance matrix is cached on
`(graph_version, supply_set, supply_hash, n_poi)` — it never mentions addresses. The prototype read
the **live** cache (`node_nearest_m_1b4ab8a0ffec7ef7.parquet`, supply_hash `767b28674e30`,
605,130 nodes) unchanged. D39's "767k addresses in 158 s" was the cost of *building* that matrix;
street points do not rebuild it.

Measured, end to end (L=160, 39,277 points):

| phase | time | already paid by `address-gaps`? |
|---|---:|---|
| load `walk_graph.pkl` | 9.6 s | yes |
| `_prune` + `_to_csr` | 33.0 s | yes |
| **snap 39,277 points** (`nearest_nodes`) | **10.3 s** | **no — the marginal cost** |
| gather + `compute_gap_metrics` | <1 s | no |
| whole script, wall | 98 s | |

**Extrapolated to L=100 (48,969 points): ≈ 13 s of snapping.** The marginal cost of the street
frame is **under 15 seconds**.

**Rows** (at L=100):

| table | today | + street | Δ |
|---|---:|---:|---:|
| `analysis.address` | 281,842 | 330,811 | **+17.4%** |
| `analysis.address_category` | 4,227,630 | 4,962,165 | **+17.4%** |

**Storage:** +17.4% of those two tables. (A direct `pragma_storage_info` measurement was blocked
for the length of this session by the other agent's write lock; estimating from column widths —
~60 mostly-numeric columns on `address`, ~25 on `address_category` — the delta is on the order of
**30–45 MB** against a 1.53 GB database, i.e. ~2–3%. Re-measure before building.)

**Re-apply order.** `loci street-frame` must run **before** `address-gaps`, because `address-gaps`
does `DELETE FROM analysis.address WHERE borough = ?` and would drop the street rows. The cleanest
shape is for `address-gaps` to *consume* the street frame, not to run after it:

```bash
uv run loci street-frame --refresh          # fetch CSCL, rebuild data/interim/street_points.parquet
uv run loci address-gaps                    # default MNBK; now scores lots + street points together
uv run loci address-demand --borough MNBK
uv run loci pipeline && uv run loci storefronts && uv run loci age-fit apply --category all
uv run loci supply-ratio --boroughs MN,BK   # NO --fit-baseline (universe stays frame='lot')
uv run loci address-access --boroughs MN,BK
uv run loci transit-profile --boroughs MN,BK
uv run loci revenue --boroughs MN,BK
uv run loci export-webmap
```

Every `RE-APPLY AFTER EVERY SCREEN RE-RUN` warning in `cli.py` is unchanged in meaning — the
`UPDATE`-only layers simply now touch 17% more rows.

---

## 6. Implementation plan

**New files**

* `src/loci/sources/cities/nyc/street_centerline.py` — the only place CSCL column names live.
  `load_street_segments(borough)` applies §1.4's rule and returns
  `(segment_id, lon_line, borough, length_m, street_name, width_ft)`; `street_midpoints(segments, L)`
  returns plain `(point_id, lon, lat, borough, frontage_m, street_name)` tuples — no CSCL column
  name crosses into `model/` or `score/`, exactly as `addresses.py` keeps BBL and `borocode` local.
  Live-API: **raise on total failure**, never ingest a silent zero; assert MN+BK segment count is
  within ±10% of 32,291 and fail loudly otherwise (the source updates weekly).
* `src/loci/sql/022_street_frame.sql` — the `ALTER`s (below), idempotent
  `ADD COLUMN IF NOT EXISTS`.
* `tests/test_street_frame.py` — §4's invariants, plus a pure-geometry test of the split
  (`k = ceil(len/L)`, fractions `(2i−1)/2k`, per-part allocation, no point on an endpoint).

**Registry** — add to `src/loci/registry.yaml` (and mirror into `CONTEXT.md` §3, which
`loci check-sources` enforces):

```yaml
  - id: nyc_cscl
    name: NYC Street Centerline (CSCL)
    tier: city
    city: nyc
    role: control
    status: verified
    url: https://data.cityofnewyork.us/City-Government/NYC-Street-Centerline-CSCL-/exts8-4k5w
    dataset_id: inkn-q76z
    geography: line
    temporal: {start: 2013, end: current, grain: weekly}
    cost: {amount: 0, unit: total}
    fields: [physicalid, the_geom, rw_type, status, nonped, trafdir, boroughcode,
             segmentlength, full_street_name, from_level_code, to_level_code, streetwidth]
    bias: >
      shape_length is WEB MERCATOR metres (x1.32 at NYC latitude), NOT a length;
      segmentlength is US feet and disagrees with the geometry on a minority of
      rows (p05 0.30, p95 1.64 of geodesic). Compute length from the geometry,
      reprojected to EPSG:2263. segment_type / segment_type_value are 100% NULL.
      physicalid is near-unique, not unique (3 duplicates in MN+BK).
    notes: >
      THE STREET SAMPLING FRAME (docs/street_midpoint_frame.md). rw_type=1 AND
      status='2' AND nonped<>'V' AND at-grade keeps 32,291 of 41,784 MN+BK rows
      (3,476.8 km). Not a POI source; never joined into staging.poi.
```

**New columns**

```sql
-- 022_street_frame.sql
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS frame         VARCHAR DEFAULT 'lot';
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS frontage_m    DOUBLE;   -- street rows only
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS street_name   VARCHAR;  -- street rows only
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS frame_source  VARCHAR;  -- 'nyc_cscl'
ALTER TABLE analysis.address ADD COLUMN IF NOT EXISTS frame_vintage DATE;
ALTER TABLE analysis.address_category ADD COLUMN IF NOT EXISTS frame VARCHAR DEFAULT 'lot';
-- CHECK is added in 002's CREATE TABLE for a fresh DB; DuckDB cannot ALTER-ADD
-- a CHECK to an existing table, so the constraint is asserted by the test suite
-- on an existing warehouse and by the DDL on a new one.
```

`frame` is denormalised onto `address_category` for the same reason `is_lead`/`eligible`/`censored`
are (D61): a reader must be able to slice the long table without a join.

**Files to touch**

| File | Change |
|---|---|
| `sources/cities/nyc/street_centerline.py` | new (above) |
| `sql/002_schema.sql` | `frame` in both `CREATE TABLE`s with the `CHECK`; header prose explaining the two frames |
| `sql/022_street_frame.sql` | new |
| `model/address_gaps.py` | `ADDRESS_COLUMNS` += `frame, frontage_m, street_name, frame_source, frame_vintage`; `ADDRESS_CATEGORY_SCREEN_COLUMNS` += `frame`; `_split_wide` carries it; `_cluster_gap_addresses` caller groups by `(borough, frame, lead)`; `address_gaps_view_sql()` selects `a.frame` |
| `model/supply_ratio.py` | baseline-fit universe → `WHERE frame='lot'`; `supply_baseline.yaml` `universe` string updated |
| `model/revenue.py` | calibration / backtest folds → `WHERE frame='lot'` |
| `model/address_demographics.py` | guard `bbl IS NOT NULL` |
| `model/conveniences.py` | per-address distribution → `WHERE frame='lot'` |
| `validation/sample.py` | draw → `WHERE frame='lot'` |
| `viz/webmap_export.py` | carry `frame` into the gap layer; separate street layer, default off |
| `model/recommend.py` | BBL-denominated stats over lot rows only; street-cluster card says "no tax lot" |
| `cli.py` | new `loci street-frame`; `address-gaps` reads the street frame and unions it into `addresses_df` |

**CLI**

```
loci street-frame [--borough MNBK|MN|BK] [--spacing-m 100] [--refresh] [--dry-run]
```
Fetches CSCL (cached under `data/raw/nyc_cscl/`), applies §1.4, emits
`data/interim/street_points.parquet` and prints the §1.4 ladder plus the L table so the filter is
auditable on every rebuild. `--dry-run` writes nothing. `address-gaps` then reads that parquet and
unions it into the frame it already builds from PLUTO — one screen run, one provenance stamp, one
`frame` column.

---

## 7. Caveats the database cannot enforce

1. **`GEOMETRY` carries no SRID.** Every CSCL length must be reprojected explicitly
   (`ST_Transform(..., 'EPSG:2263', always_xy := true)` × 0.3048006096012192, or a geodesic
   computation). `ST_Length` on the 4326 geometry returns **degrees** and will not error.
   `shape_length` is Web Mercator metres and is wrong by **+32%** at NYC latitude.
2. **The street frame is not a demand frame.** A street point has zero residents. Any statistic
   that reads as "people affected" must weight by `units` (which is 0) or by `homes_400m` (which is
   a catchment over *other* rows). Counting street rows as addresses would inflate every
   "N addresses have a gap" headline by 17%.
3. **19% of the orphan points have a censored lead** and their median `gap_score` of 7.50 is
   literally `CAP_M / reach(laundry)`. A censored score is a **floor**, not a measurement. Any
   ranking that pools street and lot rows on raw `gap_score` will be topped by Randall's Island.
   `lead_censored` and `homes_400m` both already exist to prevent this; they must actually be used.
4. **The screen varies at the block scale.** Adjacent points 120–160 m apart disagree on
   `lead_category` **39.7%** of the time (§1.5). A single midpoint is a *sample* of its segment,
   not a summary of it. `frontage_m` is carried so a reader can see how much street each point is
   standing in for.
5. **Street points have no demographics and never will via BBL.** `address_demographics` is defined
   as the lot's own tract by BBL lookup (D56). If demand annotation on street points is ever wanted,
   the right fix is a **census-tract polygon ingest + point-in-polygon**, not copying the nearest
   lot's tract — that would make an industrial street inherit the income of the one apartment
   building 300 m away, and the caveat machinery would then assert something about a population
   that does not live there.
6. **CSCL updates weekly.** Segment counts will drift. `frame_vintage` records the extract date;
   the ±10% count assertion catches a silent schema or filter break.
7. **The res-9 hex NTA lookup disagrees with CSCL's own borough on 120 of 39,277 points** at river
   edges (BK→QN 60, MN→BX 51, BK→MN 9). Take `borough` from CSCL; take `nta_code` from the hex.
8. **This pair of tables still holds exactly ONE run** (D61). Comparing a with-street run against a
   without-street run means a parquet snapshot between runs, never two copies in the warehouse.

---

## Appendix — reproducing the probe

Scratch work (not in the repo):
`/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor/e5f8e048-6e10-48a8-8f8f-a2e710bbc3c2/scratchpad/`
— `analyze.py` (feature-type rule + length distribution), `midpoints.py` (the splitter),
`proto.py` (snap + score against the live node cache), `cscl_mnbk.json` (41,784 rows with
geometry), `street_points_scored.parquet` (39,277 scored points).

```bash
curl -G "https://data.cityofnewyork.us/resource/inkn-q76z.json" \
  --data-urlencode "\$select=physicalid,the_geom,rw_type,status,nonped,trafdir,boroughcode,segmentlength,shape_length,full_street_name,streetwidth,from_level_code,to_level_code" \
  --data-urlencode "\$where=boroughcode in('1','3')" \
  --data-urlencode '$limit=60000' -o cscl_mnbk.json      # ~7.5 s, 21.8 MB
```
