# A second El Punto Cubano Express — site search across Manhattan + Brooklyn

**Written 2026-09-16.** Companion to `docs/recommendations/graham-ave-376-2026-09-13.md`
(pre-registered revenue, owner evidence log) and
`docs/recommendations/graham-ave-376-neighborhood-2026-09-14.md` (shed demographics,
dayparts, cuisine gap). Warehouse read-only at `data/loci.duckdb`, `frame='lot'`,
`revenue-v0.2`. Scripts in the session scratchpad
(`.../scratchpad/elpunto2/step1_candidates.py` … `step5_top.py`). No warehouse table,
YAML, CHECKPOINT entry or ticket was modified; nothing committed.

**What this search does and does not do.** It finds blocks *like* 376 Graham Avenue on
the demand features the neighborhood memo tied to the concept, that have a storefront
market, a commuter-origin subway stop at the door, an evening trade, and no incumbent
Cuban/Caribbean/Latin counter. It does **not** find blocks that *need* Cuban food — there
is no demand instrument for cuisine. Read the ranking as "another Graham", and read §4 for
which of the top three is instead a different bet.

---

## 0. Two corrections to the earlier memos, made before anything below was computed

Both are material and both are in the earlier *scratchpad scripts*, not in the warehouse —
`src/loci/db.py` has carried the correct `METRES_SQL` since decision **D16**.

**(a) The 2026-09-13/14 memos' "within 400 m" straight-line figures were computed on a
distorted ellipse.** `graham/neighborhood/shed.py` and the alcohol query called
`ST_Distance_Sphere(ST_Point(lon, lat), …)` raw. DuckDB's `ST_Distance_Sphere` reads
`ST_Point(x, y)` as **(latitude, longitude)**; passing (lon, lat) computes distance on a
region stretched ~1.32× east–west and compressed to 0.277× north–south. A nominal "400 m
disc" is in fact a **1.44 km × 0.30 km north–south sliver** of about 2.7× the correct area.
Verified: Graham → Roebling is 976 m with the flip and 1,287 m without.

Consequences for the numbers that were quoted to the owner:

| figure, 376 Graham | as published | corrected (true 400 m) |
|---|---:|---:|
| on-premises licences within 400 m | **92** | **39** (92 is the *600 m* count) |
| Caribbean venues within 400 m (DOHMH point) | 1 (Los Primos "132 m") | **0** (Los Primos is 456 m straight-line) |
| Cuban/Caribbean/LatAm/Spanish venues within 400 m | ~7 | **2** (Claudia's 327 m, Palenque 337 m) |
| nearest vacant FOOD-SERVICES storefront | 318 Graham, "77 m" | 318 Graham, **240 m** |

The *direction* of every published conclusion survives — Graham is still a
restaurants-that-serve-drinks corridor rather than a bar corridor, and the Cuban slot is
still empty — but the levels do not, and the on-premises band in this brief had to be
re-anchored (§1, F6).

**(b) The neighborhood memo's §1 shed demographics describe a ~1.4 km north–south
corridor, not a 5-minute walk.** Recomputed on a true 400 m disc, unit-weighted over PLUTO
lots exactly as that memo describes (7 tracts, own tract carries 34.1% of weight, 5,934
residential units):

| 400 m shed, 376 Graham | published §1 | corrected |
|---|---:|---:|
| under 18 | 16.2% | **13.6%** |
| 18–34 | 35.4% | **42.9%** |
| Spanish at home | 22.0% | **13.9%** |
| worked from home | 25.2% | **30.4%** |
| HH under $50k | 31.4% | **21.4%** |
| HH over $200k | 19.4% | **31.2%** |
| avg HH size | 2.11 | **2.06** |

The corrected shed is the one that memo's own MAUP paragraph predicted ("the tighter the
shed, the richer it gets"); its 216 m-equivalent column — Spanish 13.4%, under-18 13.9%,
sub-$50k 21.2% — is within a point of these figures on every line. **The five-minute walk
around 376 Graham is younger, richer and less Spanish-speaking than the memo said.** This
is the reference vector used throughout below, and it weakens menu levers 4 (Spanish
signage) and 3 (low-price anchor tier) in that memo, without touching levers 1, 2 or 6.

---

## 1. The screen

Universe: every `analysis.address` lot row in MN+BK (`frame='lot'`), 213,813 with a
storefront market (`storefronts_400m ≥ 10`).

| # | Filter | Rule | Survivors |
|---|---|---|---|
| F1 | storefront market | `storefronts_400m ≥ 10` | 213,813 |
| F2 | a space can appear | `vacant_storefronts_400m ≥ 1` **or** a vacant FOOD-SERVICES storefront ≤ 150 m | 178,133 |
| F3 | cannibalisation | > 1.5 km from 376 Graham | 205,794 |
| F4 | at the train | subway entrance ≤ 250 m | 51,221 |
| F5 | AM outflow | `transit_am_pm_share_400m > 1.2` (D76 commuter-origin) | 63,606 |
| | all of F1–F5 | | **25,201** |
| | 150 m grid clustering (one block = one row) | | **1,294** |
| F6 | evening trade, not a bar street | on-premises licences 400 m in **17–64** | 62 |
| F7 | no incumbent of the cuisine | see below | 267 / 537 |
| | **F6 + F7 strict** | | **47** |
| | **F6 + F7 parity** | | **88** |

**F6 is re-anchored.** The brief's band 40–150 was 0.43×–1.63× of the published "Graham =
92". Graham's *true* 400 m count is 39, so the band is 17–64. The brief's band as written
excludes 376 Graham itself.

**F7, the cuisine exclusion.** The brief names Cuban, Caribbean, Jamaican, Latin American,
Dominican, Puerto Rican, Spanish. DOHMH's self-reported `cuisine` field has **no Cuban,
Jamaican, Dominican or Puerto Rican label anywhere in MN+BK**; the only labels in that
family that exist are **Caribbean (362), Latin American (409), Spanish (204),
Chinese/Cuban (12)** — 987 active venues. Two rules are run:

- **STRICT** — zero of those four labels within 400 m.
- **PARITY** — no more than 376 Graham itself has: ≤ 2 in total and **zero**
  Caribbean/Chinese-Cuban. (Under the corrected distances Graham has 0 Caribbean and 2
  Latin/Spanish at 327 m and 337 m, so parity is only slightly looser than strict. Under
  the *published* distances the two would have been far apart, and Graham would have
  failed its own strict filter — the coordinate bug was hiding that.)

Parity is the headline ranking; the strict column is carried in the table and §5 shows the
two lists agree on the top two.

**Similarity.** Nine concepts, each weight 1: catchment scale (log `homes_400m`), family
(avg HH size + under-18 share, ½ each), Spanish at home, WFH, income (share <$50k + share
>$200k, ½ each), 18–34 share, transit shape (`am_pm_share` + log `transit_entries_400m`, ½
each), evening trade (on-premises 400 m). Score = weighted RMS z-distance to 376 Graham,
standardised on the SD of the eligible pool — *"how many pool standard deviations from
Graham"*, 0 = identical. Demand features are the corrected 400 m unit-weighted shed of §0(b);
transit, storefront and pipeline features are warehouse columns.

**Blocks are de-duplicated twice:** a 150 m grid for the candidate set, then a greedy
≥ 400 m separation for the reported rows, so no two rows are the same block.

---

## 2. Top 10

Demand features are the 400 m unit-weighted shed. **Graham reference:** homes 4,003 ·
HH 2.06 · u18 13.6% · Spanish 13.9% · WFH 30.4% · <$50k 21.4% · >$200k 31.2% ·
18–34 42.9% · am/pm 1.41 · evening entries 1,039 · on-prem 39 · restaurant ratio 1.28× ·
vacant storefronts 4 · active units 83.

| # | Anchor block | NTA | sim | homes | HH | u18 | Span | WFH | <50k | >200k | 18–34 | am/pm | eve | on-prem | rest ratio | vac s/f | active u | card |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | **570 Franklin Ave** ⚑ | Bed-Stuy (W) | **0.63** | 4,109 | 2.14 | 16.1% | 10.5% | 27.8% | 25.0% | 22.7% | 35.4% | 1.30 | 1,154 | 21 | 1.48× | 7 | 99 | **C / diligence** |
| 2 | **106 Clifton Pl** ⚑ | Clinton Hill | **0.68** | 4,385 | 2.31 | 18.5% | 8.5% | 25.2% | 26.8% | 25.4% | 37.5% | 1.35 | 462 | 21 | 0.67× | 1 | 17 | **C / diligence** |
| 3 | **444A Greene Ave** | Bed-Stuy (W) | 0.89 | 3,549 | 2.32 | 16.8% | 10.4% | 21.7% | 33.8% | 23.9% | 34.0% | 1.69 | 381 | 25 | 1.11× | 5 | 22 | **D / do not act** |
| 4 | 203 20th St | Sunset Pk (W) | 1.03 | 2,989 | 2.40 | 20.5% | 19.6% | 23.6% | 15.3% | 29.2% | 28.6% | 1.27 | 475 | 23 | 1.38× | 7 | 192 | C / diligence |
| 5 | 177 15th St | S. Slope | 1.04 | 3,812 | 2.44 | 19.9% | 17.4% | 26.3% | 14.7% | 36.4% | 26.1% | 1.27 | 475 | 31 | 1.24× | 10 | 18 | C / diligence |
| 6 | 345 E 94th St ⚑ | UES-Yorkville | 1.15 | 8,299 | 2.04 | 13.6% | 10.6% | 20.9% | 25.2% | 30.5% | 28.7% | 1.21 | 1,525 | 20 | 0.78× | 16 | 0 | not run |
| 7 | 413 16th St ⚑ | S. Slope | 1.22 | 3,675 | 2.30 | 19.1% | 9.6% | 33.1% | 14.4% | 39.9% | 21.8% | 1.40 | 599 | 30 | 2.51× | 2 | 17 | not run |
| 8 | 7910 4th Ave | Bay Ridge | 1.34 | 3,187 | 2.54 | 21.2% | 12.9% | 24.9% | 27.8% | 18.5% | 23.1% | 2.23 | 314 | 28 | 1.67× | 3 | 0 | not run |
| 9 | 1316 Halsey St | Bushwick (E) | 1.42 | 2,586 | 2.85 | 16.4% | **48.7%** | 16.3% | 35.8% | 11.1% | 37.9% | 2.03 | 585 | 22 | 0.76× | 1 | 15 | not run |
| 10 | 350 74th St | Bay Ridge | 1.47 | 3,066 | 2.58 | 22.1% | 17.6% | 21.1% | 32.3% | 14.3% | 22.2% | 2.16 | 485 | 27 | 3.97× | 5 | 1 | not run |

⚑ = also passes the **STRICT** cuisine rule (zero Caribbean/LatAm/Spanish/Chinese-Cuban
within 400 m). "eve" = weekday evening transit entries within 400 m. "card" = `loci
recommend --category restaurant` on a 200 m box at that lot (D74); the reference card for
376 Graham is also **C / diligence** at ratio 1.28×, so C is parity, not a demotion.

Space anchors, nearest incumbent of the cuisine, and the model's rent ceiling:

| # | Anchor lot | Nearest vacant storefront (DOF) | Nearest vacant FOOD-SERVICES storefront | Nearest Cuban/Carib/LatAm/Spanish venue | v0.2 rev p50 | v0.2 rent ceiling @8% |
|---|---|---|---|---|---:|---:|
| 1 | 570 Franklin Ave | 1108 Fulton St, 225 m | **1000 Dean St, 208 m** | La Mode BK (Caribbean) 448 m | $339,746 | $2,265/mo |
| 2 | 106 Clifton Pl | 435 DeKalb Ave, 278 m | 1000 Dean St, 1,171 m | Punta Cana (LatAm) 423 m | $424,409 | $2,829/mo |
| 3 | 444A Greene Ave | **1055 Bedford Ave, 0 m** | 1000 Dean St, 1,213 m | Espinal Deli (Spanish) 281 m | $320,407 | $2,136/mo |
| 4 | 203 20th St | 181 18th St CU3, 158 m | **599 4th Ave, 229 m** | El Continental (LatAm) 137 m | $299,137 | $1,994/mo |
| 5 | 177 15th St | 584 4th Ave, 230 m | 599 4th Ave, 306 m | El Nuevo Sabor Latino 332 m | $329,701 | $2,198/mo |
| 6 | 345 E 94th St | 1841 1st Ave, 124 m | **305 E 92nd St, 218 m** | Piacere Mio (Spanish) 601 m | $1,842,635 | $12,284/mo |
| 7 | 413 16th St | 211 Prospect Park W, 237 m | 599 4th Ave, 1,020 m | Stella's (Caribbean) 867 m | $324,910 | $2,166/mo |
| 8 | 7910 4th Ave | 7910 3rd Ave, 239 m | 8606 5th Ave, 707 m | Puertas (LatAm) 390 m | $306,911 | $2,046/mo |
| 9 | 1316 Halsey St | 784 Knickerbocker Ave, 220 m | 895 Broadway, 2,577 m | Pollos A La Brasa 351 m | $244,754 | $1,632/mo |
| 10 | 350 74th St | 7402 5th Ave, 251 m | 8606 5th Ave, 1,136 m | Sabor De Colombia 2 341 m | $302,196 | $2,176/mo |

**Rent bands — every rent here is a band and none of them is this space.** No asking rent
exists at address grain in any public source (D67). Three reference points:

- **Revealed:** the owner pays **$4,000/mo on ~690 sq ft = $70/sq ft/yr** at 376 Graham and
  calls it the shop's biggest advantage.
- **Corridor asks:** the Brooklyn ground-floor band the 09-13 memo assembled,
  **$37.50–$80/sq ft/yr** (Graham Avenue BID listings at $45). On 690 sq ft that is
  **$2,160–$4,600/mo**, and the owner's actual rent sits inside it.
- **Model ceiling:** `revenue-v0.2` at OCR 0.08 gives **$1,600–$2,830/mo** for all nine
  Brooklyn rows — *below* the rent the owner already pays and calls cheap. D91 states v0.2
  is a floor for an above-typical operator; this is that statement in dollars, and it is
  the reason economics cannot grade above **C** anywhere in this memo.

Working band for rows 1–5 and 7–10, a secondary Brooklyn corridor on ~690 sq ft:
**$2,200–$4,600/mo**, and the brief's target band of $3,000–$6,500 is achievable at all of
them. **Row 6 (UES-Yorkville) is not transferable** — Manhattan ground-floor asks are
multiples of the Brooklyn band, the v0.2 ceiling there is $12,284/mo because the model is
reading an $8,299-home catchment, and no Manhattan corridor ask was obtained. Treat row 6's
economics as unpriced.

---

## 3. Placebo — does the metric find Graham?

Re-run with F3 (the 1.5 km cannibalisation ring) removed, everything else identical, and
376 Graham forced into its own 150 m cell. Eligible pool = 98 blocks.

| rank | block | similarity | distance from 376 Graham |
|---|---|---:|---:|
| **1** | **376 Graham Ave** | **0.000** | 0 m |
| 2 | 3027550013 (same block) | 0.041 | 22 m |
| 3 | 3027450036 (Graham Ave) | 0.145 | 148 m |
| 4 | 3027450004 (Graham Ave) | 0.162 | 146 m |
| 5 | 3027420001 (Graham Ave) | 0.579 | 445 m |
| 6 | 570 Franklin Ave | 0.589 | 4,202 m |

**Pass, and informatively so.** 376 Graham ranks 1 of 98 under both weightings — trivially,
since it is the reference — but the next four blocks in the *entire* MN+BK eligible universe
are all within 445 m of its own door, and the first block that is not East Williamsburg is
the #1 recommendation. The metric is locally coherent and the gap between "the same street"
(0.04–0.58) and "the best other block in two boroughs" (0.59) is the honest measure of how
far a second site has to travel.

## 4. Stability under the 2× transit-and-family weighting

Doubling the weight on family (HH size, under-18) and transit (am/pm share, entries):

| rank | equal weights | 2× transit + family |
|---|---|---|
| 1 | 570 Franklin Ave (0.63) | **570 Franklin Ave (0.58)** |
| 2 | 106 Clifton Pl (0.68) | **Clinton Hill (0.68)** |
| 3 | 444A Greene Ave (0.89) | **444A Greene Ave (0.87)** |
| 4 | 203 20th St (1.03) | 203 20th St (0.99) |
| 5 | 177 15th St (1.04) | 177 15th St (1.00) |

The top five are identical in identity and order; only the Clinton Hill representative lot
moves 80 m (3019527502 → 3019667509, the same block face). Under the **strict** cuisine rule
the top two are unchanged and 345 E 94th St replaces 444A Greene at #3. **The ranking is not
an artifact of the weighting or of the cuisine rule.**

---

## 5. The top three

### 1 — 570 Franklin Avenue, Bedford-Stuyvesant (West) — *another Graham*
Similarity 0.63, the closest block in two boroughs. It matches Graham on the three things
that actually carry the concept: **4,109 households against 4,003**, a **commuter-origin
station** (am/pm 1.30; **Franklin Av C/S, entrance 225 m**) with **1,154 weekday evening entries against
Graham's 1,039 — the only Brooklyn row that beats Graham on the evening number**, and an
evening trade of **21 on-premises licences** that is thinner than Graham's 39 but far above
a dead street. It is closer to Graham's income shape than any other row (25.0% under $50k /
22.7% over $200k against 21.4% / 31.2%) and it is **more, not less, family**: HH 2.14, under-18
16.1%. The space signal is the strongest in the table: **seven vacant storefronts within
400 m and a vacant FOOD-SERVICES storefront at 1000 Dean St, 208 m** — the same distance as
318 Graham is from El Punto's own door. **99 active pipeline units** within 400 m against
six stalled, the cleanest pipeline of any row (Graham's is 83 active / 75 stalled). Zero
Cuban, Caribbean, Latin American or Spanish venues within 400 m; nearest is La Mode BK at
448 m. Card: **C / diligence**, restaurant ratio 1.48× — the same grade the reference card
gives 376 Graham. *What's missing:* Spanish at home is 10.5% against Graham's 13.9%, so the
Spanish-language counter lever is weaker, and Bed-Stuy's Caribbean layer is dense just
beyond 400 m — the exclusion holds at the walk-shed, not at the neighborhood.

### 2 — 106 Clifton Place, Clinton Hill — *another Graham, richer*
Similarity 0.68. The **largest catchment among the Brooklyn rows (4,385 homes)**, the same
commuter-origin shape (am/pm 1.35; **Classon Av G, entrance 82 m — closer to the door than Graham's own 142 m**), and the **thinnest restaurant supply in the
table at 0.67× the MN+BK baseline** — though D70 rates restaurant `no_signal`, so that number
is a thinness measure and must not be read as headroom. It is the most *family* of the two
Bed-Stuy/Clinton Hill rows (HH 2.31, under-18 18.5%) and carries the highest modelled revenue
of any Brooklyn row ($424k p50). Zero of the excluded cuisines within 400 m; nearest is Punta
Cana at 423 m. *What's missing:* **one vacant storefront within 400 m and the nearest vacant
food storefront is 1.17 km away** — the demand is there and the space is not. Evening entries
462 against Graham's 1,039, and `nta_character` is `residential`, not `retail_mixed`: this is
a residential block with a shop on it, which suits a delivery-heavy counter and does not suit
walk-in volume.

### 3 — 444A Greene Avenue, Bedford-Stuyvesant (West) — *a different bet, and the card says wait*
Similarity 0.89, and the **only row with a vacant storefront at the lot itself (1055 Bedford
Ave, 0 m)**. The strongest AM outflow in the near set (am/pm **1.69** against Graham's 1.41; Bedford–Nostrand Avs G, entrance 166 m),
which is the single feature the owner's stated plan — Cuban coffee and breakfast burritos
from a warmer for the morning commute — depends on. But it is a **different bet**, not another
Graham: **33.8% of households are under $50k against Graham's 21.4%**, evening entries are 381
(37% of Graham's), and the D74 card returns **D on arriving homes → "do not act on this data"**
(41 stalled units against 22 active). One Spanish-labelled venue sits 281 m away. This is the
cheapest space in the top three and the weakest evidence; it belongs on the walk list, not on
a lease.

**The cheapest single check per site — one visit each, no data purchase.**

| site | the one check |
|---|---|
| 570 Franklin Ave | Stand at Franklin & Fulton at **08:00 and 18:00 on a weekday** and count. The whole case is 1,154 evening entries meeting 4,109 households; if the 18:00 street is thinner than Graham's, the ranking is wrong. |
| 106 Clifton Pl | **Confirm a space exists at all.** Walk DeKalb between Classon and Franklin and ask three landlords whether anything ≤ 900 sq ft is available under $4,500/mo. One vacant storefront within 400 m is the binding constraint, not demand. |
| 444A Greene Ave | **Confirm 1055 Bedford Ave is genuinely available and food-legal** (the registry is an annual self-reported filing, not a listing) — and walk Bedford for the Caribbean and Spanish counters DOHMH's self-reported labels miss. |

Do all three in one day; Franklin → Classon → Bedford is a 25-minute walk end to end.

---

## 6. Caveats

- **No revenue truth from the operator.** Sales, staff, weekday orders and average ticket
  are all still pending. **Economics grades C at best everywhere in this memo**, and the
  v0.2 rent ceiling is below the rent the owner already pays and calls cheap.
- **DOHMH `cuisine` is self-reported, and the label this search most needs does not exist.**
  There is no Cuban, Jamaican, Dominican or Puerto Rican value in MN+BK; El Punto's own row
  is `cuisine: null` (never inspected). "Zero Cuban within 400 m" is partly a labelling fact.
  Geocoding compounds it: Los Primos's DOHMH point is 456 m from 376 Graham while
  `analysis.poi_supply` puts it at 132 m network. **A block can pass F7 and still have a
  jerk counter on it.** This is the check that has to be walked.
- **MAUP is severe and is now measured, not asserted.** §0(b) shows the same site moving
  8 points of Spanish-at-home and 10 points of sub-$50k between a 400 m disc and a ~1.4 km
  corridor. The 400 m disc is itself a choice; the neighborhood memo's 216 m re-weighting
  gives materially different shares again. Every demand feature here is a ring average over
  a gradient, weighted by PLUTO residential units, with ACS tract MOEs **not propagated into
  the similarity score**.
- **Rent bands are corridor asks, not this space.** No public source carries asking rent at
  address grain. The Manhattan row is unpriced.
- **The screen finds blocks like Graham, not blocks that need Cuban food.** Rows 1, 2 and 6
  are "another Graham"; rows 3 and 9 are different bets (3 is poorer with a stronger AM peak;
  9, Bushwick East, is 48.7% Spanish-speaking — three and a half times Graham — and is the
  only row where the Spanish-language counter lever is *stronger* than at Graham, at the cost
  of the smallest catchment and the weakest income).
- **D70 holds.** `restaurant` is `no_signal`: the supply ratio column is a thinness measure
  and enters the grade in neither direction. Do not read 0.67× at Clinton Hill as headroom.
- **Retail is the dependent read.** Every column here describes a present-day catchment.
  Nothing in this memo forecasts neighborhood growth from retail (the rejected D1 thesis).
- **Pipeline (D72).** `units_active` vs `units_stalled` separates abandonment from arrival;
  a renewed permit is still not a shovel.
- **`loci recommend` warns of supply-hash drift** (baseline fitted on `ba944e18c57b`, live
  set `18eb5ab24629`), which caps section 3 at grade C on every card above.

- **2026-09-16:** owner-facing pages corrected and republished after the D16 lat/lon flip was found (El Punto: licence row 92/211 → 39/112, 1 bar; Graham Avenue: shed demographics restated as shares on the true 400 m disc, distances corrected, levers 7 and 9 demoted, sureness section rewritten to disclose the correction). Fourth page "A second El Punto" (artifact pending id) published: 570 Franklin Ave / Fulton (another Graham), 106 Clifton Pl (richer, no space), 444A Greene Ave (morning-outflow bet, stalled pipeline); revenue deliberately omitted (no owner sales figure → model is typical-operator only).
