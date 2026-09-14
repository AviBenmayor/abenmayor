# Carrying capacity: how many small businesses do N people support?

**2026-09-14.** Owner's question: *"how many small businesses can a certain amount of
people support? density vs revenue model. what can other cities learn from NYC?"*

Built as `src/loci/model/carrying_capacity.py` + `src/loci/model/carrying_capacity.yaml`
(generated) + `loci capacity`. Nothing here writes to the warehouse.

---

## 0. The answer, before the method

At the **median Manhattan-or-Brooklyn doorway** — a 400 m walkshed of 0.268 km² holding
about 5,900 residents — there are **81 daily-needs businesses within a 400 m walk**, across
the 15 categories. Double the people **in that same walkshed** and you get **not 162 but
about 184**: supply grows *faster* than population in 7 of 15 categories, slower in 2, and
one-for-one in 6. (Spread the same 10,000 people over a *larger* shed instead and the count
rises further still, to ~233 — frontage counts as well as customers; see §3.)

The three words this is **not**:

* **Not a maximum.** Loci has no viability outcome at all (D88: the one survival-adjacent
  test returned a null; Foursquare closures are ~3% ascertained). "5,900 people support 81
  shops" means *5,900 people are observed alongside 81 shops*, never *5,900 people can
  profitably sustain 81 shops*. Nothing here says one more would fail.
* **Not causal.** Density and retail are jointly determined. A zoning line, a subway stop
  and a 1920s streetcar route are in both.
* **Not a growth predictor.** Retail is the **dependent** variable on every line. Reading
  thick retail as a signal that people are coming is the rejected D1 thesis, and D88 found
  the arrow running the other way.

---

## 1. Method

### 1.1 Two grains, and why they cannot be one

| | Part 1 — NYC | Part 2 — national |
|---|---|---|
| Unit | address (lot frame), 400 m **network** walkshed | ZCTA |
| Geometry | **overlapping** catchments | **partition** of land |
| Supply | Loci principled POIs (D52/D59) | CBP payroll establishments |
| Universe | 281,842 MN+BK lot rows, 111 NTAs | 10,197 ZCTAs, 107 metros ≥500k, 226M people |
| Answers | "what is within a 400 m walk of this doorway" | "how many shops does this land hold per resident" |

Part 1's counts can never be compared to a partition count: one shop is counted by every
address within 400 m of it. So "is NYC above or below the national curve" is asked **at
NYC's own ZCTAs inside the national frame**, where both sides are CBP and the units match.
The bridge between the two parts is the CBP-to-POI ratio (§4), measured on the same NYC ZIP
partition — and that ratio is itself a portability parameter, not an annoyance to divide
away.

### 1.2 Functional form, chosen by out-of-sample fit

Candidates, all fitted by the Poisson log-likelihood (the target is a count; 7–70% of
address×category cells are zero, so the outcome cannot be logged, and least squares would
let one Midtown block outweigh ten thousand Brooklyn doorways):

| form | μ | params |
|---|---|---|
| `proportional` | `a·N` | 1 — **the baseline** |
| `power` | `a·N^b` | 2 |
| `michaelis_menten` | `Emax·N/(K+N)` | 2 |
| `hill` | `Emax·N^b/(K^b+N^b)` | 3 |
| `hill_density` | hill × `(D/D_ref)^c` | 4 |

**The gate.** A curved form ships only if it beats `proportional` on **≥4 of 5 NTA-blocked
folds** *and* cuts mean held-out deviance by **≥2%**. Among passing forms the **simplest**
within 1% of the best wins — without that tie-break the Hill wins by riding the ridge where
`Emax→∞` with `Emax/K^b` fixed (i.e. by *being* a power law) and then reports an `Emax`
pinned to its own bound. Failing the gate is recorded as `form: proportional` with **no
flattening density at all** — 6 of 15 categories land there, which is the evidence that the
gate is a gate.

**Blocking is not style.** Two addresses 80 m apart share almost the same catchment, so a
random split puts the same shops on both sides and every form scores beautifully. Folds are
GroupKFold on `nta_code`; the effective n is **111 NTAs, not 281,842 addresses**, and every
interval is an NTA block bootstrap (200 draws) of the **prediction**, not of the parameters.

### 1.3 What the NYC curve cannot resolve

Inside a **fixed** 400 m walkshed, resident count and density are nearly the same variable:
density = residents / shed area, and the shed area varies only 0.195–0.312 km² p10–p90
(D83) against a ~10× range in population. **N and D are collinear by construction at this
grain.** `hill_density` exists to measure how little the residual area variation buys, and
it reports the honest decomposition instead of a raw exponent:

* **e(residents | area fixed)** — add people to the same block. 1.00 is constant per
  capita; below 1 is saturation; above 1 means each extra 1,000 residents buys *more* shops
  than the last.
* **e(area | residents fixed)** — grow the walkshed at constant population. Positive means
  shops scale with **land** (street frontage, corner lots) and not only with customers.

A query whose residents/density imply a walkshed outside [0.15, 0.40] km² is flagged as out
of support rather than silently extrapolated — which is exactly the suburban case, and
exactly why the national curve ships beside it.

---

## 2. The NYC curve

Persons per home: **2.06** MN+BK aggregate, applied by NTA (ACS tract population ÷ PLUTO
`UnitsRes`). Median walkshed 0.268 km²; median catchment 5,915 residents.

| category | form | shape | e(res\|area) p10→p90 | e(area\|res) | per 1k res @p50 | per $1M spend | flattens at | OOS gain | D70 regime |
|---|---|---|---|---|---|---|---|---|---|
| grocery | hill | **saturating** | 1.66 → **0.66** | 0.00 | 1.68 | 0.56 | 16,104 res (60,124/km²) | +3.1% | saturating |
| convenience | hill_density | **saturating** | 1.48 → **0.15** | +0.61 | 0.60 | 2.21 | 8,490 res (31,697/km²) | +6.7% | no_signal |
| laundry | power | accelerating | 1.45 → 1.45 | 0.00 | 0.58 | 13.92 | — | +6.7% | saturating |
| hair_barber | hill_density | accelerating | 1.31 → 1.21 | +0.93 | 1.39 | 15.24 | — | +5.4% | saturating |
| nails_beauty | hill_density | accelerating | 1.20 → 1.18 | +0.88 | 1.00 | 14.39 | — | +4.0% | saturating |
| tailor_repair | hill_density | accelerating | 1.51 → 1.51 | +1.10 | 0.09 | 8.54 | — | +3.3% | saturating |
| restaurant | hill_density | accelerating | 1.39 → 1.35 | +1.36 | 3.85 | 6.49 | — | +7.5% | no_signal |
| cafe_bakery | hill_density | accelerating | 1.39 → 1.32 | +1.42 | 0.89 | 7.64 | — | +5.9% | no_signal |
| fitness | hill_density | accelerating | 1.43 → 1.42 | +0.93 | 0.73 | 3.81 | — | +4.5% | saturating |
| pharmacy | proportional | proportional | 1.00 | 0.00 | 0.43 | 1.61 | — | gate refused | no_signal |
| bar | proportional | proportional | 1.00 | 0.00 | 0.68 | 3.00 | — | gate refused | no_signal |
| childcare | proportional | proportional | 1.00 | 0.00 | 0.65 | 2.26 | — | gate refused | saturating |
| clinic | proportional | proportional | 1.00 | 0.00 | 0.58 | 4.70 | — | gate refused | saturating |
| bank | proportional | proportional | 1.00 | 0.00 | 0.32 | 7.90 | — | gate refused | saturating |
| hardware | proportional | proportional | 1.00 | 0.00 | 0.25 | 3.07 | — | gate refused | no_signal |

Fitted parameters live in `carrying_capacity.yaml`. The ones worth reading:

* `grocery`: Emax 25.4, K 7,465 residents, b 1.90 — a real ceiling inside the observed
  range, and the only category with one.
* `convenience`: Emax 16.1, K 7,670, b 2.28, **c −0.61**.
* `restaurant`: Emax 19,240, K 45,991, b 2.76, **c −1.36** — Emax and K both far outside the
  observed range, i.e. a power law in Hill clothing, which is why no flattening point is
  reported.
* `nails_beauty`, `tailor_repair`, `fitness` carry `params_at_bound: [emax]` — Emax is
  pinned to its box constraint. That is the optimiser saying "further, please"; those
  Emax values are **not** ceilings and must not be quoted as such.

### 2.1 Two categories flatten; seven accelerate

**Only `grocery` and `convenience` saturate inside the observed range.** Grocery's marginal
rate halves at 16,100 residents in a 400 m walkshed (about 60,000 residents/km², roughly
Manhattan's 95th percentile) — there is a real ceiling on how many supermarkets one walk
can hold. Convenience flattens harder and earlier (8,490 residents) and its density term is
negative (c = −0.61): bodegas scale with *people*, and squeezing the same people into less
land does not add more of them.

**Seven categories accelerate**, and three of those — restaurant (c = −1.36), cafe_bakery
(−1.42), tailor_repair (−1.10) — have an **area elasticity above 1**: at a fixed population,
a walkshed with more land in it carries proportionally more of them. That is frontage, not
customers. A restaurant needs a storefront on a street; a pharmacy needs a catchment.

The honest caveat on the acceleration: **a 400 m walkshed is not a closed catchment.** A
commercial corridor's restaurants serve people from far beyond the ring, while the
denominator counts only the residents inside it, so some of the superlinearity is the
corridor's non-resident trade (workers, transit riders, visitors) being divided by a local
population. It is not *only* that — the same density gradient reappears at ZCTA grain
nationally (§5), on a land partition, where the artifact is far weaker — but the magnitude
at 400 m is inflated by it, and no number in the restaurant/café rows should be read as
"residents alone buy this".

### 2.2 Reconciliation with D70 and D81/D91 — three different "saturations"

These are **three different estimands** and they are not supposed to agree.

| | this module | D70 | D81/D91 |
|---|---|---|---|
| What | level of supply vs level of population | **growth** 2013→23 vs 2013 supply-per-resident | physical retail floor area |
| Grain | address, 400 m | ZIP | lot |
| Mechanism | demand | catch-up / mean reversion | **space** |

Agreement is **2 of 15**. D70 called 8 categories saturating; of those, only `grocery`
saturates here too, while `laundry`, `hair_barber`, `nails_beauty`, `tailor_repair` and
`fitness` come back *accelerating*, and `childcare`, `clinic`, `bank` come back flat.
`convenience` saturates here and was `no_signal` in D70.

That is coherent, not contradictory: D70's finding is that a ZIP which already had many
laundromats per resident in 2013 **added fewer of them by 2023** — mean reversion in a
*change*. This module's finding is that a denser walkshed **holds more of them per
resident today** — a *level*. A category can be at a high level and growing slowly. The two
results together say the dense places got there first, not that density has a low ceiling.

D91's `capacity_bound` is the third mechanism and it is only computed for `restaurant`, the
one category the revenue model ships. It binds on **7%** of MN+BK lot rows against 62% in
Manhattan alone (D91) — so demand saturation and floor-area saturation are genuinely
separate, and restaurant is nowhere near its demand ceiling while a majority of Manhattan
lots are already at their *space* one. **Manhattan's constraint is square feet, not
customers.** That is the single most transportable finding in this document.

---

## 3. `loci capacity` — how many can N people support

```
loci capacity --residents 10000 --density 22583
loci capacity --residents 10000 --density 38636 --category grocery
loci capacity --fit          # re-estimate; reads the warehouse read-only, writes no table
loci capacity --show         # the fitted parameters, the gate's verdict, both reconciliations
```

**10,000 residents at NYC's median walkshed density (22,583/km²)** — note that this implies
a 0.443 km² catchment, *outside* the 400 m band, and the CLI says so:

| category | NYC expected | 90% CI | per 1k res | per $1M spend | national per 1k | NYC/national |
|---|---|---|---|---|---|---|
| restaurant | 93.0 | 61.4 – 144.1 | 9.30 | 6.49 | 2.291 | 0.98× |
| hair_barber | 25.3 | 19.9 – 31.7 | 2.53 | 15.24 | 0.315 | 1.52× |
| cafe_bakery | 21.9 | 14.3 – 33.3 | 2.19 | 7.64 | 0.567 | 0.99× |
| nails_beauty | 17.1 | 13.9 – 20.9 | 1.71 | 14.39 | 0.120 | 2.15× |
| grocery | 16.1 | 14.8 – 17.7 | 1.61 | 0.56 | 0.404 | 1.60× |
| fitness | 14.5 | 11.0 – 20.6 | 1.45 | 3.81 | 0.134 | 0.94× |
| laundry | 7.4 | 6.8 – 8.1 | 0.74 | 13.92 | 0.077 | 3.40× |
| bar | 6.8 | 5.4 – 8.3 | 0.68 | 3.00 | 0.313 | 0.60× |
| childcare | 6.5 | 5.9 – 7.0 | 0.65 | 2.26 | 0.290 | 1.25× |
| convenience | 6.3 | 5.4 – 7.3 | 0.63 | 2.21 | 0.241 | 1.27× |
| clinic | 5.8 | 4.9 – 6.7 | 0.58 | 4.70 | 0.808 | 1.00× |
| pharmacy | 4.3 | 3.9 – 4.8 | 0.43 | 1.61 | 0.128 | 1.91× |
| bank | 3.2 | 2.7 – 3.7 | 0.32 | 7.90 | 0.224 | 0.87× |
| hardware | 2.5 | 2.3 – 2.7 | 0.25 | 3.07 | 0.012 | 1.62× |
| tailor_repair | 2.1 | 1.3 – 3.1 | 0.21 | 8.54 | 0.0001 | 11.34× |
| **total** | **232.8** | | | | | |

**10,000 residents at p90 density (38,636/km², implied shed 0.259 km² — in support):**
total **148.1**, restaurant 44.7 [38.5–52.8], hair_barber 15.4, grocery 16.1, cafe_bakery
10.2, nails_beauty 10.6, fitness 8.8, laundry 7.4, bar 6.8, childcare 6.5, clinic 5.8,
convenience 4.6, pharmacy 4.3, bank 3.2, hardware 2.5, tailor_repair 1.2.

The totals differ because **the same 10,000 people spread over more land support more
shops** (e(area) > 0 for the frontage categories) — the p50 query is asking about a
0.44 km² catchment and the p90 query about a 0.26 km² one.

The `per $1M spend` column is a *transformation*, not a second fit: it re-expresses the
fitted per-1,000-resident rate against CEX annual category spend per household from
`spend.yaml` (the same table D81's revenue model uses), at 2.45 persons per household. It
adds an assumption without adding a degree of freedom, and it is `null` for any category
`spend.yaml` does not carry rather than a guessed denominator.

---

## 4. The CBP-to-POI bridge — the portability parameter

Loci counts POIs; CBP counts **payroll establishments**. On the same NYC ZIP partition, the
principled supply set against CBP 2023:

| category | Loci POIs | CBP estab | aggregate ratio | median ZIP ratio | ZIPs |
|---|---|---|---|---|---|
| fitness | 4,457 | 601 | **7.42×** | 6.54× | 61 |
| tailor_repair | 97 | 25 | 3.88× | 3.67× | 5 |
| nails_beauty | 4,223 | 1,128 | 3.74× | 3.67× | 71 |
| hardware | 789 | 212 | 3.72× | 3.75× | 47 |
| bar | 3,172 | 1,173 | 2.70× | 2.91× | 63 |
| hair_barber | 6,156 | 2,363 | 2.61× | 2.69× | 76 |
| grocery | 6,050 | 2,837 | 2.13× | 2.14× | 77 |
| bank | 1,868 | 932 | 2.00× | 2.15× | 66 |
| restaurant | 20,418 | 11,059 | 1.85× | 1.76× | 81 |
| cafe_bakery | 4,597 | 2,669 | 1.72× | 1.62× | 76 |
| laundry | 2,452 | 1,475 | 1.66× | 1.84× | 74 |
| childcare | 2,533 | 1,609 | 1.57× | 1.56× | 79 |
| convenience | 1,772 | 1,171 | 1.51× | 1.45× | 75 |
| pharmacy | 1,718 | 1,330 | 1.29× | 1.21× | 76 |
| clinic | 3,401 | 3,626 | **0.94×** | 1.00× | 79 |

Read it as three things at once, and the three cannot be separated with what is here:
**sole proprietors CBP never sees** (a one-chair barber, a family tailor), **the D47 dedup
residual** in the licence-anchored categories, and **Loci coverage** where the ratio is
below 1 (clinic, the only category Loci undercounts against the payroll census).

`fitness` at 7.42× is the outlier and is most likely a definition mismatch rather than
coverage: Overture and Foursquare label yoga studios, martial-arts schools, personal-training
rooms and building gyms as fitness, and CBP's 713940 counts payroll establishments only.

**Why this is a parameter and not a nuisance.** These ratios are the price of NYC's licence
rosters. A second city with no DOHMH, no SLA and no NYS DOS will measure its own POI supply
against a different, mostly *lower* multiple of CBP — so a NYC-fitted per-1,000 rate in POI
units cannot be carried to Phoenix without knowing that city's own ratio. **The rate that
travels is the CBP rate in §5. The POI rate does not travel.**

---

## 5. NYC against the national curve

The national model is the same question on a partition:

```
mu = (population / 1000) × rate(density)
```

a Poisson fit with `log(population/1000)` as an offset, so the parameters describe the
**rate** and nothing else. Baseline: `rate(D) = r0`, density irrelevant. Folds blocked by
**CBSA**. NYC (CBSA 35620) is **held out of the fit**, so its position is an out-of-sample
statement rather than a residual from a curve it helped draw — it is the densest and one of
the largest metros in the country and would otherwise pull the curve toward itself.

Universe: 10,197 ZCTAs in 107 MSAs ≥500k, 226M residents, CBP 2023, ACS 2023 5-year, 2023
Gazetteer land area. An absent (ZCTA, NAICS) row is read as a **zero**; the strict
alternative (drop the 1,775 ZCTAs with no CBP presence in any of the 15 categories, 8,422
remaining) is run as a sensitivity and moves every NYC ratio by **less than 0.14×** (largest: childcare 0.135, tailor_repair 0.119, laundry 0.098).

| category | form | national per 1k @ p10 / p50 / p90 density | NYC observed/1k | NYC predicted/1k | **NYC/national** | strict |
|---|---|---|---|---|---|---|
| tailor_repair | rate_hill | 0.000 / 0.000 / 0.0001 | 0.0013 | 0.0001 | **11.34×** | 11.22× |
| laundry | rate_hill | 0.002 / 0.032 / 0.064 | 0.212 | 0.062 | **3.40×** | 3.30× |
| nails_beauty | rate_hill | 0.006 / 0.100 / 0.118 | 0.245 | 0.114 | **2.15×** | 2.12× |
| pharmacy | rate_hill | 0.027 / 0.085 / 0.112 | 0.215 | 0.113 | **1.91×** | 1.83× |
| hardware | constant_rate | 0.012 flat | 0.019 | 0.012 | 1.62× | 1.57× |
| grocery | rate_power | 0.048 / 0.120 / 0.204 | 0.419 | 0.262 | 1.60× | 1.63× |
| hair_barber | rate_hill | 0.032 / 0.281 / 0.311 | 0.462 | 0.303 | 1.52× | 1.50× |
| convenience | rate_power | 0.026 / 0.069 / 0.119 | 0.197 | 0.155 | 1.27× | 1.30× |
| childcare | rate_hill | 0.085 / 0.223 / 0.269 | 0.334 | 0.267 | 1.25× | 1.12× |
| clinic | rate_hill | 0.111 / 0.665 / 0.785 | 0.765 | 0.764 | 1.00× | 0.99× |
| cafe_bakery | rate_power | 0.103 / 0.216 / 0.329 | 0.390 | 0.396 | 0.99× | 1.01× |
| restaurant | rate_hill | 0.829 / 1.457 / 1.845 | 1.898 | 1.935 | 0.98× | 0.95× |
| fitness | rate_hill | 0.007 / 0.128 / 0.133 | 0.123 | 0.131 | 0.94× | 0.93× |
| bank | rate_hill | 0.089 / 0.203 / 0.220 | 0.189 | 0.217 | 0.87× | 0.91× |
| bar | rate_power | 0.019 / 0.064 / 0.128 | 0.110 | 0.184 | **0.60×** | 0.60× |

**Density is the master variable, nationally.** 14 of 15 categories beat a
density-independent baseline; only `hardware` does not, and it ships `constant_rate` — the
one genuinely density-blind daily-needs trade in America. The rest run 2× to 30× denser per
resident at the 90th density percentile than at the 10th, which is the same gradient Part 1
finds at 400 m, on a land partition where the overlapping-catchment artifact does not exist.

**What is NYC-specific.** Four categories sit clearly above what NYC's density alone
predicts: **tailor/repair (11×)**, **laundromats (3.4×)**, **nail salons (2.2×)** and
**pharmacies (1.9×)**, with grocery, hair and hardware at 1.5–1.6×. This is the
apartment-living bundle — no in-unit washer, no garage, no car to drive to a strip-mall
pharmacy — plus an immigrant-entrepreneur service economy. Tailor/repair at 11× is real but
its national denominator is almost zero (0.0001 per 1,000), so treat it as "a trade that
essentially only exists in NYC" rather than as a calibrated multiple.

**What follows the national curve exactly.** **Restaurants (0.98×), cafés (0.99×), clinics
(1.00×) and fitness (0.94×)** land on the curve. New York has enormously more restaurants
per square kilometre than Houston — and *exactly the number its density predicts*. That is
the strongest transportable result in this document: **restaurant density is a function of
residential density and nothing New York does is special about it.**

**And one below.** **Bars at 0.60×** — NYC has 40% fewer bars per resident than its density
predicts. Candidate explanations not distinguished here: SLA licensing and the 500-foot
rule, restaurants holding on-premises licences and filing under 7225 instead of 7224, and
rent. A liquor-licence-driven artifact is the most likely of the three and it is *exactly*
the kind of thing that does not travel to a second city.

### 5.1 Nearest metros — candidates for city #2

Three readings, because they disagree and the disagreement is the finding.

| ranking | 1 | 2 | 3 |
|---|---|---|---|
| **Retail mix + density, equal weight** | Houston (1,304/km²) | Atlanta (805) | San Antonio (1,045) |
| **Density weighted ×8** | **Los Angeles** (3,536) | **San Francisco** (3,346) | **Chicago** (2,736) |
| **Dense population** ≥5,000/km² | **Los Angeles** 2.54M (19.6%) | **Chicago** 1.67M (17.9%) | **Philadelphia** 1.18M (19.0%) |

The first row is a warning, not an answer: density is one column against fifteen mix
columns, so at equal weight it contributes a sixteenth of the distance and the "nearest"
metros come back as whichever sit near the middle of the mix cloud — at a **seventh** of New
York's density. Houston is not a candidate for city #2 in any sense that matters.

The third row is the screen that answers the question actually asked. NYC has **9.46M people
(48.2%) living in ZCTAs at ≥5,000/km²**. The next five metros: Los Angeles 2.54M, Chicago
1.67M, Philadelphia 1.18M, San Francisco 1.04M, Boston 0.96M. **Los Angeles, Chicago and
Philadelphia** are the three with enough dense population for a NYC-fitted walkshed model to
have anywhere to stand; SF and Boston have the highest dense *shares* (22.3% and 19.5%) but
a third of the absolute population.

---

## 6. What travels, and what does not

**Travels.**
1. **Restaurants, cafés, clinics and fitness follow density with no New York premium.** A
   density → per-capita-rate curve fitted nationally predicts NYC's own rate within 6%.
2. **Density is the master variable** for 14 of 15 categories, on a land partition, across
   107 metros.
3. **The Manhattan constraint is floor area, not customers** (D91's capacity ceiling binds
   62% of Manhattan lot rows while restaurant demand is nowhere near flat). Any city
   planning for walkable retail should be counting ground-floor square feet.
4. **Grocery is the one category with a real demand ceiling** — about 16,100 residents per
   400 m walkshed — and it is a format constraint (supermarkets need catchment), so it
   should reappear anywhere.

**Does not travel.**
1. **The POI rate.** It is in units of Loci's licence-anchored POI census, which is 0.94× to
   7.4× CBP depending on category (§4). Only the CBP rate is portable.
2. **The apartment bundle** — laundromats, nail salons, tailors, pharmacies at 1.9–11× the
   national curve. These are NYC housing stock and NYC demography, not NYC density.
3. **Bars at 0.60×**, almost certainly a state-licensing artifact.
4. **The 400 m walkshed itself**, below about 5,000 residents/km². The NYC curve was
   estimated on catchments of 2,300–26,000 people in 0.195–0.312 km²; a suburban query is
   out of support and the CLI flags it rather than extrapolating.

---

## 7. Limitations

1. **No viability outcome anywhere.** Stated three times in this document because it is the
   one that would be most costly to forget. Every number is an observed equilibrium.
2. **Establishment counts are two different things.** CBP is payroll-only; Loci is a POI
   census. §4 reconciles them for NYC and reports the ratio per category; nothing here
   reconciles them for any other metro, so NYC's POI column is not comparable to anything
   outside NYC.
3. **The 400 m walkshed is not a closed catchment.** Some of the superlinearity in
   restaurant/café/fitness is non-resident trade divided by a resident denominator. The
   national ZCTA replication limits but does not eliminate this.
4. **Effective n is 111 NTAs**, not 281,842 addresses. Intervals are NTA block bootstraps;
   the address count is never used as a sample size anywhere in the module.
5. **Persons-per-home is an NTA ratio** (ACS population ÷ PLUTO units), right on average
   within an NTA and wrong for any single building.
6. **Absent CBP rows are read as zeros.** Establishment counts are not suppression-flagged
   in the CBP response, but the strict universe is run as a sensitivity (§5) and moves NYC's
    ratios by <0.14×.
7. **Density is a LAND density** from the Gazetteer. Every metro comparison uses a
   population-weighted density for this reason — a simple pop/area figure ranks metros by
   how much desert their counties enclose.
8. **Three Emax values are pinned to their bound** (`nails_beauty`, `tailor_repair`,
   `fitness`). Those are not ceilings; `params_at_bound` names them in the YAML.
9. **NAICS is self-classified and bleeds** between adjacent formats (D42). Bar vs restaurant
   is the worst case and is likely part of the 0.60× bar result.
10. **Everything is cross-sectional 2023–26.** No time dimension, so nothing here says where
    a rate is heading.

---

## 8. Reproduce

```bash
loci capacity --fit                    # ~4 min NYC + ~25 s national; reads the DB read-only
loci capacity --show
loci capacity --residents 10000 --density 22583
pytest tests/test_carrying_capacity.py
```

Artifacts: `src/loci/model/carrying_capacity.yaml` (generated, hash-stamped),
`data/raw/cbp/` and `data/raw/zbp/` (Census caches). Registry entry `census_cbp`;
CONTEXT.md §3.3 row. **No warehouse table is created or updated** — the fit is 15 rows of
parameters, not a new grain.
