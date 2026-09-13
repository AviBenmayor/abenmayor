# Pre-registered revenue prediction — Lion's Milk, 104 Roebling St, Brooklyn

**Written:** 2026-09-13, 17:05 ET, **before** any figure was obtained from the owner.
**Purpose:** score the Loci site-revenue model against one real P&L. The numbers below are
frozen. Nothing in this file may be revised after the owner answers; a correction goes in a
new dated file that links back to this one.

---

## 1. The subject

| | |
|---|---|
| Business | Lion's Milk — modern Turkish café (böreks, simit, Turkish coffee; Devoción coffee, Balthazar pastries delivered daily) |
| Address | 104 Roebling St, Brooklyn NY 11211 (Williamsburg, NTA BK0102) |
| Opened | 2015 (≈11 years trading) |
| Hours (public) | Mon–Fri 07:30–16:30, Sat–Sun 08:30–17:00 ≈ **62 h/week**, daytime only, no dinner service |
| Second location | **None found.** Web search returns only 104 Roebling; `staging.poi` holds no other "Lion's Milk" row. To be confirmed with the owner. |
| Space (PLUTO, BBL 3023290030) | bldgclass **S1** (residential w/ one store), `retailarea` **1,000 sq ft**, `comarea` 1,000, 3 floors, 1 residential unit, built 1899, lot 1,100 sq ft. Plus a private outdoor patio (not in `retailarea`). |

### How Loci classified it

| poi_id | source | category | in principled set? | notes |
|---|---|---|---|---|
| `overture_places:41c0fc63-…` | Overture Places | **cafe_bakery** | **yes** (cluster 22286, 2 sources) | corroborated by `foursquare_os_places:5661eb12…` (labels: Coffee Shop / Organic Grocery / Sandwich Spot) |
| `nyc_dohmh_restaurants:50043137` | DOHMH | **restaurant** | **yes** (cluster 216924, 1 source) | cuisine "Turkish", grade A 2025-09-22, `active_basis: inspected_351d_ago` |
| `nyc_dohmh_restaurants:50185551` | DOHMH | restaurant | *not in supply set* | same lat/lon, 6 inspection rows, last 2026-08-31, no grade yet — looks like a **re-issued permit**; worth asking about |

**Loci double-counts this business**: once as `cafe_bakery` (Overture/Foursquare cluster) and once
as `restaurant` (DOHMH cluster). The two clusters did not merge — a dedup finding worth a ticket,
independent of this prediction.

## 2. Inputs (address 3023290030 = 104 Roebling St, BBL 3023290030)

Reproducible from `data/loci.duckdb` at `supply_hash 767b28674e30`, spec_hash `943bee403cb1`,
calibration `revenue-v0` asof `2026-09-13T15:37:06`.

| Input | Value |
|---|---|
| ZIP / county | 11211 / Kings (047) |
| `homes_400m` / `homes_800m` | **3,982** / 17,976 |
| ACS 2023 tract 36047051900 median HH income | **$212,881 ± $28,506** (MOE 90%) → SE $17,329 |
| Income quintile assigned | **q5** (top; breaks 29,932 / 57,452 / 94,511 / 155,925). q5 at ±1 SE → still q5, so **σ_income = 0** |
| Café spend per household (CEX 1101 shape × 3004 NY-MSA level, 15% of food-away-from-home) | **$1,361.36/yr** |
| `supply_400m` cafe_bakery / restaurant | **28** / **104** |
| network rings cafe_bakery [0-100,…,600-800] | 1, 2, 8, 17, 36, 37 |
| network rings restaurant | 1, 7, 31, 65, 158, 120 |
| `supply_ratio_vs_base` cafe_bakery / restaurant | **5.85** / **4.42** |
| `units_permitted_400m` / active / stalled | 143 / 143 / 0 |
| `vacant_storefronts_400m` / `storefronts_400m` | 6 / 79 |
| Shipped **restaurant** row on this address | p25 **$1,605,592** · p50 **$2,494,887** · p75 **$3,876,741** · `rent_ceiling` $199,591/yr (at restaurant OCR 0.08) |
| EC 2022 Kings NAICS 722515 | RCPTOT $642,110,000 · 950 estab · 7,809 emp → **$675,905/estab**, **$82,227/employee** |
| CBP 2023 ZIP 11211 NAICS 722515 | 56 establishments, 8.12 emp/estab (band coverage 0.98) |

**Café model parameters (ungated, full-sample best):** β = 1.25, γ = **−0.75** (agglomerative),
λ_Kings = 0.054522, σ_λ = 0.4664, σ_β = 0.1896 → σ_log = 0.5035.
I re-ran `loci.model.revenue.fit(con, ("MN","BK"))` in the scratchpad on a fresh sweep
(281,842 addresses + 55,740 establishments → 46,765 nodes, identical `supply_hash`) and it
reproduced the shipped calibration **exactly** for both `cafe_bakery` and `restaurant` — same
β, γ, λ, σ, and every backtest field. No YAML was written.

## 3. The four predictions

All four are **annual gross revenue** for the single 104 Roebling location.
`rent/mo` is the implied ceiling at `benchmarks.yaml` café `occupancy_cost_ratio = 0.10`.
`$/sqft` divides p50 by PLUTO's 1,000 sq ft `retailarea` — a reality check the model never sees.

| | Prediction | p25 | **p50** | p75 | rent/mo @10% | $/sqft | Basis |
|---|---|---|---|---|---|---|---|
| **a** | Restaurant model — *corridor read, wrong category* | $1,605,592 | **$2,494,887** | $3,876,741 | $20,791 | $2,495 | Shipped, gate-passed restaurant params (β 0.5, γ −0.25, λ_Kings 0.026087) on this address. It is the only gated number Loci actually ships here, and it is for the wrong category. |
| **b** | Café model, **UNGATED** — *failed the cross-category placebo; treat as a commercial-intensity read* | $1,414,252 | **$1,986,120** | $2,789,229 | $16,551 | $1,986 | Pool $5,420,926 (3,982 homes × $1,361.36) × capture 6.72 × λ_Kings 0.054522. Band = lognormal, σ_log 0.5035. |
| **c** | EC Kings café average scaled by spend-pool ratio | $1,292,152 | **$1,769,844** | $2,424,131 | $14,749 | $1,770 | R = $675,905 × (Pool_site / median Pool over the 1,787 Kings café establishments) = $675,905 × ($5,420,926 / $2,070,258) = $675,905 × **2.618**. Band from σ_λ = 0.4664 only (no β term — there is no geometry in this form). |
| **d** | **Baseline** — unscaled EC Kings café average | $205,567 | **$675,905** | $575,588 | $5,633 | $676 | EC 2022 Kings 722515 receipts ÷ establishments. Band is the CBP-2023 Kings size-band revenue IQR (see §4) — it does **not** contain its own p50, which is the point. |

Sanity floor/ceiling for (c): the raw Kings average is $675,905; (c) says this site is 2.6× the
median Kings café's demand pool, and multiplies the borough mean by that.

**Self-exclusion sensitivity.** λ was fitted on establishment rings with `exclude_self=True`, but
`predict_addresses` predicts with `exclude_self=False`. With γ<0 that is not neutral: (b) falls
from $1,986,120 to **$1,867,454** (−6.0%) on the apples-to-apples form; (a) moves −0.2%. The
table uses the shipped convention.

## 4. Scoring rule (frozen)

Truth `T` = the owner's **trailing-twelve-month gross revenue** for 104 Roebling only
(exclude any second location; state whether it is net of sales tax and whether third-party
delivery is gross or net of commission).

1. **Primary score:** `e_k = ln(p50_k / T)` for each of a, b, c, d. Lowest |e| wins. Sign is
   reported: a positive `e` is an over-prediction, which is the failure mode I expect.
2. **Interval hit:** model *k* "hits" iff `p25_k ≤ T ≤ p75_k`. Note these are **parameter
   bands, not prediction intervals** (`revenue.yaml`, §uncertainty) — they say nothing about
   real-store dispersion, so a miss is weak evidence and a hit is weaker.
3. **Independent band check:** does `T` fall inside the **CBP-2023 ZIP-11211 size-band
   interquartile band for NAICS 722515**? Built from 56 establishments (23 at <5 emp, 18 at
   5–9, 11 at 10–19, 3 at 20–49), each band midpoint × EC-Kings revenue-per-employee $82,227:

   | | p25 | p50 | p75 | implied mean |
   |---|---|---|---|---|
   | **ZIP 11211** | **$205,567** | **$575,588** | **$1,192,290** | $667,533 |
   | Kings 112xx (993 banded / 1,040 estab) | $205,567 | $575,588 | $575,588 | $620,345 |

   This band uses no Loci model at all. It is the closest thing to an outside view available,
   and it is coarse (four midpoints, an assumed-constant revenue/employee, a 2022 EC ratio on
   2023 CBP counts).

### Pre-registered directional claims — these are what actually make this falsifiable

- **(i) I predict all three model p50s (a, b, c) are HIGH.** Specifically `T < $1,292,152`
  (= c's p25), which would make a, b and c all miss their intervals simultaneously.
- **(ii) I predict the |log error| ordering will be `d < c < b < a`** — the parameter-free
  borough average beats every model that adds site information.
- **(iii) Crossover, stated in advance:** (c) beats (d) iff `T > $1,093,731` (their geometric
  mean). (b) beats (d) iff `T > $1,158,632`. (a) beats (d) iff `T > $1,298,579`. If truth lands
  above $1.3M every model beats the baseline and claim (ii) is dead.

## 5. What we are betting on, and why

**Primary bet: (c), the spend-pool-scaled EC benchmark** — it is the only one of the three model
forms whose functional form I would defend in front of the statistician. It uses the two things
the ZIP backtest actually licenses (the income gradient and the spatial distribution of
households) and discards the one thing the backtest does not license here: the fitted γ = −0.75
competition term, which at 28 nearby cafés turns the "capture share" into **6.72** — a site that
captures 6.7× the annual café spend of every household inside its own 400 m walk-shed. That is
no longer a Huff share; it is a corridor-intensity multiplier wearing a share's clothing, and it
is precisely why `cafe_bakery` failed the placebo (restaurant's model predicts café employment
better, 0.6865 vs 0.6653) and did not ship.

**But I expect (c) to lose to (d), and I am saying so first.** Three independent reasons:

1. **Capacity.** PLUTO gives 1,000 sq ft of retail. (c)'s p50 is **$1,770/sq ft**; (b)'s is
   $1,986; (a)'s is $2,495. A very strong NYC independent café runs $900–1,400/sq ft. A
   daytime-only, 62 h/week shop with a patio does not run $1,770. **The model has no capacity
   term at all** — no seats, no square feet, no hours, no ticket size. Revenue is linear in the
   demand pool with elasticity 1 and no ceiling, which is exactly the "never linearly
   extrapolate" error, committed in the cross-section instead of over time.
2. **Mean vs. typical.** λ is fitted so the *mean* prediction over Kings cafés equals the EC
   *mean* per establishment, $675,905. The CBP size bands say the *median* Kings café is at
   ~$575,588 and half of them sit at the <5-employee midpoint ~$205,567. The distribution is
   hard right-skewed; a mean-anchored model applied to a median-ish shop over-predicts by
   construction. This is visible in the table: (d)'s own band does not contain (d)'s own p50.
3. **Rent triangulates lower.** At the 10% occupancy ratio, (c) supports $14,749/mo on 1,000
   sq ft = $177/sq ft/yr, above Williamsburg side-street asking rents. Back-solving instead
   from a plausible $8k–$12k/mo gives **$960k–$1.44M** — straddling the c-vs-d crossover at
   $1,093,731. This is the honest reason the bet is close to a coin flip rather than rigged:
   the rent-implied range contains the decision boundary.

If truth comes in near **$1.1M**, (c) and (d) tie and we learn almost nothing. Near **$700k**,
the model is 2.5× high and the "no capacity term" diagnosis is confirmed. Above **$1.8M**, my
directional claims are all wrong and the agglomeration term is doing real work — which would be
the most interesting outcome of the four.

## 6. Caveats — read these before treating any number above as a forecast

- **`cafe_bakery` is not a shipped Loci product.** Its gate verdict is `fail`
  (`gate_reason: placebo: restaurant's model predicts this category's employment better,
  0.6865 vs 0.6653`). It does beat both baselines out of sample (Spearman 0.651 vs 0.600
  county-average and 0.519 homes-only, R²_oos 0.271) — but failing the placebo means it is
  tracking generic commercial intensity, not coffee. Read (b) as a commercial-intensity read.
- **ZIP 11211 was inside the training data for the parameters used in (b).** Confirmed by
  re-running the fit: 11211 is one of the 65 `cafe_bakery` LOZO ZIPs, and **102 of the 1,791
  Kings café establishments (5.7%) sit in 11211**. LOZO removes 11211 only in its own fold; the
  **full-sample β, γ and λ_Kings that (b) and (c) use all saw 11211.** This is therefore an
  in-sample prediction at the parameter level, and its error will be optimistic relative to the
  0.651 out-of-sample Spearman.
- **The level was never validated anywhere, at any grain.** λ is fitted to the EC county mean by
  construction; no public source publishes retail receipts below county grain. Only the
  *ranking* of sites has ever been tested. This exercise tests the level for the first time, on
  n = 1.
- **One observation cannot validate a model. It can only embarrass it.** A hit proves nothing —
  σ_log 0.50 makes the p25–p75 band a factor of ~2 wide, and real single-store dispersion is
  wider still. A large miss in the predicted direction is informative because it was predicted
  in advance.
- **Concept quality is invisible to the model.** A Turkish-breakfast concept with a strong
  Instagram following, a patio, and a private-events business draws customers from far outside
  a 400 m walk-shed and sells a check the CEX food-away-from-home line does not describe. The
  model sees 3,982 households and 28 competitors. It cannot see that this is a destination.
- **Williamsburg is not the model's hard case.** Top income quintile, dense, 143 permitted units
  within 400 m, only 6 vacant storefronts. If the model is going to be right anywhere it is
  here — so a miss here is worse news than a miss in East New York.
- The double-count in §1 means Lion's Milk contributes to *both* the café and the restaurant
  incumbent counts around its own address, mildly inflating both capture shares.

## 7. Questions for the owner

Ask in this order; 1–3 are the ones that decide the score.

1. **Trailing-twelve-month gross revenue** for 104 Roebling (approximate is fine; a range is
   fine). Is that figure **net of sales tax**? Does it include third-party delivery at **gross
   or net of commission**?
2. **Monthly base rent**, and **years remaining on the lease**. Any percentage-rent clause,
   and who pays taxes/CAM?
3. **Square feet** of the leased space (PLUTO says 1,000 sq ft of retail — is that right?),
   **number of indoor seats**, and whether the **patio** is included in the lease.
4. **Hours per week** actually open, and roughly what share of revenue lands on Sat–Sun.
5. **Years open at this address**, and whether ownership or the operating entity has changed
   (DOHMH shows a second permit, CAMIS 50185551, first inspected 2026-08-31 — what is that?).
6. **Share of revenue from delivery/third-party apps**, and share from **private events /
   venue rental**.
7. **Is there a second location, or one planned?** If yes, is it inside the figure in Q1?
8. Optional but valuable: average ticket, and transactions per day on a typical weekday.

---

**Files.** Scratchpad (not committed):
`/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor/773ef68e-4fb0-488b-aeba-d4ff98f84218/scratchpad/lions_milk/`
— `step1_rings.py` (sweep), `step2_fit.py` (fit reproduction + 11211 membership),
`step3_predict.py` (a–c), `step4_bands.py` (CBP size bands), `step5_selfsens.py`,
`step6_table.py`, `predictions.json` (every number above).
No warehouse table, calibration YAML, CHECKPOINT entry or ticket was modified.

---

## Revision, 2026-09-13 evening — the judgment estimate (recorded before any answer from the owner)

The owner asked: "why would we send him something we know is wrong?" The primary bet above ((c), $1.29M–$2.42M) was a bet on the most defensible *model form*, while the same document said the truth is expected below $1.29M. That is incoherent: a pre-registered bet should be the number we believe.

**Judgment estimate (our actual belief): $650k – $1.25M, central $900k.** Basis, all already stated above: (1) capacity — 1,000 sq ft of retail floor plus a patio, ~62 h/wk, daytime menu; strong-corridor NYC cafés run roughly $500–900 per sq ft; (2) the borough *median* café ($575,588 from the CBP size bands) rather than the EC mean, which large operators pull up; (3) the rent back-solve for a Roebling St café at a normal occupancy ratio, $960k–$1.44M, taken as the upper half of the range because the block is exceptional on income and density.

**Scoring, revised.** Two records are kept and both are scored against the owner's trailing-12-month gross: the model's primary (c) as written above, and this judgment estimate. The question the answer settles is not only "was the model right" but "does human adjustment of the model beat the model" — hit if truth within $650k–$1.25M; log error of $900k.

The memo sent to the owner now leads with the judgment estimate and shows the raw model number beneath it, labelled as the thing being tested.

**Rent prediction (added the same evening, before any answer).** Monthly base rent at 104 Roebling: **$8,000 – $12,000, central $9,500** ($96–$144 per sq ft per year on PLUTO's 1,000 sq ft), from Williamsburg side-street asking levels — not from the model, which only produces a rent *ceiling* (revenue × occupancy ratio: $7,500/mo at 10% of the $900k judgment estimate; $14,749/mo at 10% of the raw model's $1.77M). Implication recorded now: at the judgment estimate, a rent of $9,500 is a 12.7% occupancy cost — the upper edge of what a café sustains — so if the owner's rent was ≥ $10k/mo the business was rent-squeezed at that revenue. Scored as a hit if the owner's base rent falls within $8k–$12k.

---

## Bottom-up estimate (recorded before the owner's answer)

**Written:** 2026-09-13, 17:55 ET. Built from menu prices and a transaction model only — no
Loci warehouse input, no CEX/EC/CBP anchor. All parameters below were fixed before section 3
and the evening revision were re-read. **Anchoring disclosure:** the dispatching brief quoted
the top-down ranges to me, so this is not a blind replication; I set every parameter from
menu and traffic evidence and did not tune toward those numbers, but a reader should discount
the independence claim accordingly.

All figures are **gross, ex-tax**. NYC combined sales tax 8.875% is excluded throughout
(menu prices are pre-tax; the reviewer quote "just over $8" for an oat iced latte is
tax-inclusive and was deflated before use).

### Sources for the menu and prices

| Source | URL | What it gave | Vintage |
|---|---|---|---|
| Own site menu PDF | `lionsmilkbk.com/_files/ugd/787e9c_1c834e1e7f374123ad2bbb6a9037386e.pdf` | **Item list, no prices** (prices are images) | current |
| Own site homepage | `lionsmilkbk.com` | "coffee during the day, wine and beer in the afternoon"; Mon–Fri 7.30–16.30, Sat–Sun 8.30–17.00 | current |
| SinglePlatform / Tripadvisor | `places.singleplatform.com/lions-milk/menu` | Full priced list (latte $5.50/6.00, spinach borek $9.00, Istanbul sandwich $11.50) | **stale**, pre-2022 |
| Uber Eats store page | `ubereats.com/store/lions-milk/wxdXAAk5WxWnMLU5oT5Q_w` | Potato borek **$12.50**, mini feta borek **$4.50**; section list (no plates) | current |
| Yelp review quote | `yelp.com/biz/lions-milk-brooklyn-2` | "iced latte with oat milk ran me just over $8 before tip"; "~$8 is a bit steep for a latte" | ~1 yr |
| Corner review quote | `corner.inc/place/17438` | "$8 for a latte. like a regular ass latte"; seating/patio/laptop detail | ~1 yr |
| Tripadvisor review quote | Tripadvisor d8836593 | "almost 6 dollars for a tinny cookie" | recent |
| joe.coffee listing | `joe.coffee/locations/ny/brooklyn/lion-s-milk-brooklyn` | **4.5★, 571 reviews**; "counter-serve"; "limited seating indoors" | current |
| Mato venue page | `ma.to/venue/lionsmilkbrooklyn` | private events, weddings, pop-ups; wine and beer | current |

**Material structural finding — there is no Turkish breakfast (kahvaltı) service.** The
current menu is croissants, boreks, simit, muffin, koulouri, banana bread, baklava, three
sandwiches, and drinks. No menemen, no eggs, no plates; gozleme has been dropped since the
SinglePlatform vintage. Uber Eats' own section list (Pastries, Sandwiches, Gluten Free, Hot
Drinks, Iced Espresso, Matcha, Coffee Beans, Soft Beverages) confirms it. **This is a
counter-serve coffee-and-pastry café with an afternoon wine licence, not a Turkish-breakfast
destination.** The brief's assumption of a high-ticket plate daypart is wrong, and the
midday/weekend tickets below are set accordingly lower.

**Reconstructed current in-store price list** (stale SinglePlatform list × **1.30**, the
factor that reconciles it to the two independent current anchors — Uber Eats potato borek
$12.50 vs $9.50, and the reviewed ~$7.00–7.25 base iced latte vs $5.50–6.00):

| Group | Items | Est. current price |
|---|---|---|
| Brewed coffee | drip S/L, iced coffee | $5.00 / $5.50, $6.25 |
| Espresso | espresso $5.00, americano $5.25, cortado $6.25, cappuccino $6.50 | $5.00–6.50 |
| Latte | small / large | **$7.00 / $7.75** (+$1.00 oat, ~35% take) |
| Turkish coffee | with Turkish delight | $6.50 |
| Specialty | matcha $7.50, chai/salep $7.00, flavoured latte $8.00, tea $5.00 | $5.00–8.00 |
| Small pastry | baklava $4.00, mini feta borek $4.50, croissant $5.25, simit $5.50 | $4.00–5.50 |
| Large pastry | banana bread / muffin / cookie $5.00–6.00 | $5.50 |
| Borek | spinach & feta $11.50, potato **$12.50** | $11.50–12.50 |
| Sandwiches | Istanbul / Bosphorus / Izmir | $13.00–15.00 |
| Wine / beer (PM) | glass / can | $13.00 / $8.00 |

*Guessed:* the 1.30 factor itself, and whether Uber Eats carries a platform markup. If Uber
Eats is marked up the usual 15%, every in-store price above is ~13% high. This is carried as
the `price_level` factor, tri(0.85, 1.00, 1.08).

### Ticket table (per TRANSACTION, ex-tax, blended dine-in + takeout party size)

Item mix per person, then multiplied by the blended party size for that daypart.

| Daypart | Item mix assumed | Blended party | p25 | **p50** | p75 |
|---|---|---|---|---|---|
| Weekday morning (07:30–11:00) | 1.0 drink @ $6.60 avg (45% latte/capp, 25% drip/americano, 8% Turkish, 22% specialty) + 0.55 food @ $6.30 | 1.10 | $9.00 | **$11.00** | $13.50 |
| Weekday midday (11:00–14:00) | 0.75 drink + 0.85 food @ $11.00 (sandwich/large borek) | 1.25 | $14.00 | **$17.50** | $22.00 |
| Weekday afternoon (14:00–16:30) | 0.95 drink @ $6.80 (10% wine/beer) + 0.35 food @ $5.50 | 1.15 | $8.00 | **$9.75** | $12.50 |
| Weekend morning (08:30–11:00) | 1.0 drink + 0.75 food @ $7.50 | 1.35 | $12.50 | **$15.50** | $19.50 |
| Weekend midday (11:00–14:00) | 0.90 drink + 0.95 food @ $10.50 | 1.50 | $19.00 | **$24.00** | $30.00 |
| Weekend afternoon (14:00–17:00) | 1.0 drink @ $7.30 (more wine) + 0.45 food @ $6.00 | 1.35 | $11.00 | **$13.50** | $17.00 |

Weekday blended ticket **$12.70**; weekend **$18.46**. For reference, independent coffee-shop
ticket benchmarks run $6.80–$9.00 and specialty $9.00–$14.00 (Dataintelo 2025); Lion's Milk
sits above both because of the $11.50–15.00 borek/sandwich attach.

**Delivery:** Uber Eats is the only platform found, and was showing "Delivery unavailable" at
time of check. Share of gross tri(2%, **4%**, 8%); merchant nets 0.88 of an equivalent in-store
dollar (≈28% commission against a ≈1.20 menu markup). Net effect on annual revenue −0.5%.

### Transaction table (transactions/day)

Two independent routes, which agreed to within ~7%; the Monte Carlo range spans both.

**(a) Capacity route.** *Seats guessed at 40 total* — 20 indoor, 14 back patio, 6 front/sidewalk.
Basis: PLUTO `retailarea` 1,000 sq ft less counter/espresso bar/prep/bathroom/storage leaves
~450–550 sq ft of seating at 16–20 sq ft/seat; reviews split between "limited seating indoors"
/ "small but mighty" (joe.coffee, Yelp) and "surprisingly spacious inside with a backyard patio
and front seating" (Corner). Range carried 30–52.

| | Occupied seat-hours | Party | Dwell | Dine-in txn | + re-order | Takeout/counter | **Total** |
|---|---|---|---|---|---|---|---|
| Weekday (9.0 h) | 40 × 9 × 0.50 = 180 | 1.25 | 75 min (laptop campers) | 115 | ×1.30 = 150 | 2 peak h @ 26/h + 7 h @ 11/h = 129 | **279** |
| Weekend (8.5 h) | 40 × 8.5 × 0.78 = 265 | 1.65 | 50 min (no laptops) | 194 | ×1.15 = 223 | 3 h @ 22/h + 5.5 h @ 12/h = 132 | **355** |

*Guessed:* occupancy (0.50 weekday / 0.78 weekend), dwell, the re-order multipliers, and the
single-register takeout throughput (26/h weekday peak, 22/h weekend peak — deliberately below
the 35–45/h a register can physically clear, because Roebling is one block off Bedford, not on it).
The long weekday dwell is the defining structural fact: this is a laptop café with a documented
no-laptops-on-weekends rule, so weekday seat-hours convert to few transactions.

**(b) Benchmark route.** Specialty-café benchmarks run 250–500/day. Lion's Milk is an
11-year-old 4.5★/571-review neighbourhood fixture, but a camper-heavy one with a single
register and no dinner — so below the middle of that band on weekdays. Weekday **300**
(210–420), weekend **380** (260–520). Weekend lines are reported in reviews, which is direct
evidence the weekend is capacity-bound at the register, not demand-bound.

**Daypart transaction shares** (*guessed*, coffee trailing off after 14:00 per the brief):
weekday 50% / 30% / 20% (am/mid/pm); weekend 38% / 40% / 22%.

**Parameters carried into the simulation:** `txn_wd` tri(180, **275**, 400),
`txn_we` tri(230, **350**, 500), `season` tri(0.90, **0.95**, 0.98) for holidays + winter
patio loss + slow weeks, `events` tri($0, **$25k**, $70k) for private hire / pop-ups /
wine-bar evenings (Mato documents weddings, birthdays, vintage pop-ups).

**Two correlated model-level factors**, because 16 independent triangulars diversify away
uncertainty that is in fact systematic: `price_level` tri(0.85, 1.00, 1.08) — the whole price
list rests on one 1.30 repricing factor — and `traffic_level` tri(0.72, 1.00, 1.22) — the whole
transaction count rests on one seat/throughput mental model. These, not the individual
tickets, are where the real uncertainty lives.

### Monte Carlo — 10,000 draws, independent triangular

Script: `scratchpad/lions_milk/bottom_up/bottom_up_mc.py`.
Revenue = Σ_daypart Σ_daytype (transactions × ticket) × 52 × seasonality × price_level,
net of the delivery drag, plus events.

| | Annual gross ex-tax |
|---|---|
| p5 | $1,140,920 |
| **p25** | **$1,349,970** |
| **p50** | **$1,508,175** |
| **p75** | **$1,686,421** |
| p95 | $1,961,547 |
| mean / sd / CV | $1,525,818 / $249,843 / **0.164** |

Implied: weekday day $3,580 · weekend day $6,505 · **week $31,127**.

### Sensitivity (one-at-a-time, each parameter swept over its full range, others at mode; base $1,518,790)

| Parameter | At min | At max | Swing | % of base |
|---|---|---|---|---|
| **`traffic_level`** | $1,100,528 | $1,847,423 | $746,895 | **49.2%** |
| **`txn_wd`** | $1,222,214 | $1,909,020 | $686,805 | **45.2%** |
| **`txn_we`** | $1,300,978 | $1,791,054 | $490,075 | **32.3%** |
| `price_level` | $1,294,721 | $1,638,293 | $343,572 | 22.6% |
| `tkt_wd_mid` | $1,447,811 | $1,610,048 | $162,238 | 10.7% |
| `tkt_wd_am` | $1,451,191 | $1,603,288 | $152,098 | 10.0% |
| `tkt_we_mid` | $1,449,961 | $1,601,383 | $151,422 | 10.0% |
| `season` | $1,440,169 | $1,565,962 | $125,793 | 8.3% |
| `tkt_we_am` | $1,479,558 | $1,571,099 | $91,541 | 6.0% |
| `events` | $1,493,790 | $1,563,790 | $70,000 | 4.6% |
| `tkt_wd_pm` | $1,495,130 | $1,555,969 | $60,839 | 4.0% |
| `sh_wd_am` | $1,545,153 | $1,492,426 | $52,727 | 3.5% |
| `sh_wd_pm` | $1,544,984 | $1,492,595 | $52,389 | 3.4% |
| `tkt_we_pm` | $1,499,862 | $1,545,288 | $45,427 | 3.0% |
| `sh_we_pm` | $1,533,243 | $1,500,722 | $32,521 | 2.1% |
| `sh_we_am` | $1,533,415 | $1,504,164 | $29,252 | 1.9% |
| `deliv_share` | $1,522,392 | $1,511,585 | $10,807 | 0.7% |

**Every one of the top four is a traffic or price-level parameter. Not one ticket parameter
moves the answer more than 11%.** The estimate is a traffic bet, not a ticket bet — which is
also where it disagrees with the top-down judgment figure.

### Capacity sanity line

| | p25 | p50 | p75 |
|---|---|---|---|
| $/sq ft/yr (1,000 sq ft `retailarea`) | $1,350 | **$1,508** | $1,686 |
| $/sq ft/yr (1,400 sq ft incl. ~400 sq ft patio) | $964 | **$1,077** | $1,205 |
| $/seat-hour (40 seats × 4,060 open-hours × 0.95) | $11.02 | **$12.31** | $13.77 |

**$/seat-hour of $12.31 is plausible** for a café with a strong takeout stream (the metric
credits takeout revenue to seats it never used). **$/sq ft is the diagnostic that fails.**
Independent restaurants run $210–$365/sq ft; high-volume small-footprint NYC specialty cafés
reach perhaps $700–$1,200/sq ft. $1,508/sq ft on the retail footprint is above that ceiling,
and $1,077/sq ft counting the patio is at its top edge.

**Independent rent cross-check** (the rent range in this file's earlier section, $8k–$12k/mo
= $96k–$144k/yr): my p50 implies an occupancy-cost ratio of **6.4%–9.5%**, against a typical
café OCR of 8–12%. A café paying only 6.4% of sales in rent in Williamsburg would be an
outlier. Both diagnostics point the same way: **the bottom-up p50 is too high, and the
suspect parameter is weekday transactions.**

**Diagnostic-adjusted variant, reported but NOT scored** (`bottom_up_mc_wide.py`, identical
except `traffic_level` widened downward to tri(0.58, 1.00, 1.22) to reflect that I have zero
observed traffic data and both cross-checks pull down): p25 **$1,261,944** · p50
**$1,439,767** · p75 **$1,634,203**. Widening the downside moves the p50 only 5% — the
diagnostics say the central estimate is wrong, but the parameter ranges as specified cannot
reach a figure low enough to satisfy them. That gap is itself the finding.

### Comparison to the top-down estimates in this file

*Read only after every parameter above was fixed.*

| Method | p25 | p50 / central | p75 |
|---|---|---|---|
| Loci raw model (§3) | $1,605,592 | $2,494,887 | $3,876,741 |
| Top-down judgment (§ revision), as quoted to me | $650,000 | **$900,000** | $1,250,000 |
| **Bottom-up (this section)** | **$1,349,970** | **$1,508,175** | **$1,686,421** |

1. **Bottom-up lands between the two, closer to the raw model.** Its p75 ($1.69M) sits just
   above the raw model's p25 ($1.61M) — the two overlap in the $1.6–1.7M band. Its p25
   ($1.35M) sits *above* the judgment estimate's p75 ($1.25M). **Bottom-up and the judgment
   estimate do not overlap at all.** Exactly one of them is wrong.

2. **The disagreement is traffic, not ticket.** To reach the $900k judgment central with my
   ticket table, weekday transactions must fall to ~165/day and weekend to ~210/day — about
   19 transactions/hour all day, one customer every three minutes, at a 40-seat 4.5★ café
   with documented weekend lines. To reach $900k with my transaction counts, the weekday
   blended ticket must fall to **$7.60** — less than the price of one latte, in a shop where
   a reviewer paid $8 for one. The ticket side is anchored to observed prices and is hard to
   move; the traffic side is anchored to nothing observed and is where I am exposed.

3. **The judgment estimate implies an OCR of 10.7%–16.0%** at $96k–$144k rent; mine implies
   6.4%–9.5%. Normal is 8–12%. On that one metric the truth would sit near **$1.1M–$1.3M** —
   between the two, and below my p25. I am recording that observation without moving my
   pre-registered number.

4. **Where I think I am wrong, stated in advance:** the weekday takeout stream (129/day) and
   the 0.50 weekday occupancy. If the owner's answer comes in near $1.0–1.2M, the cause will
   be that a laptop café one block off Bedford does ~200 weekday transactions, not 280 — and
   the lesson is that seat-hours in a camper café convert to transactions at a much worse
   rate than my 75-minute dwell assumed.

5. **Where the raw model and the bottom-up agree, and why that matters:** the raw model reaches
   ~$1.6M+ through a household-spend catchment with an agglomeration term; the bottom-up reaches
   ~$1.5M through prices and seats. The two share no inputs. Their overlap in the $1.5–1.7M band
   is the single strongest reason not to simply defer to the $900k judgment figure.

### Scoring rule (frozen)

Scored against **annual gross revenue ex-sales-tax, single location, most recent full year**,
including delivery (at merchant net) and private-event income.

- **Hit** if truth ∈ [**$1,349,970**, **$1,686,421**] (the bottom-up p25–p75).
- **Log error** = |ln(truth / **$1,508,175**)|. Reported to three decimals.
- **Also reported, not scored:** whether truth falls inside the diagnostic-adjusted p25–p75
  [$1,261,944, $1,634,203]; and which of the three methods (raw model / judgment / bottom-up)
  has the smallest log error, since that is the comparison the whole exercise exists to make.
- **Falsifier for the mechanism, not just the number:** if truth is below $1.2M, the model is
  wrong *on traffic* and the owner's transaction count should come in under ~220/weekday. If
  truth is below $1.2M **and** the owner reports 270+ weekday transactions, the model is wrong
  *on ticket* instead, and the 1.30 repricing factor is the thing that failed.

---

## Bottom-up cost model and P&L (recorded before the owner's answer)

**Written:** 2026-09-13, 18:40 ET. Cost side only — revenue is an *input* at the three
scenarios already in this file. Scripts: `scratchpad/lions_milk/costs/cogs_model.py`,
`pnl_mc.py`, `addendum.py`. All figures annual, **ex-sales-tax** (8.875% is pass-through
and excluded throughout). 40,000-draw Monte Carlo, triangular priors, two **correlated**
model-level factors on each side (`cost_level`, `price_level` on COGS; `staffing_level`,
`offbar` on labour) because independent triangulars diversify away uncertainty that is in
fact systematic — the same error this file's revenue section called out.

### Baking: in-house or bought in?

Evidence says **hybrid**, and it is carried as the base case. A 2019-vintage listing
(shootnewyorkcity.com) reads: "pastries from Balthazar which they receive daily **and they
also have freshly made sweet and savory Turkish food**." Western pastry is bought; the
Turkish savouries (börek, simit, koulouri) are made on site. All three scenarios are run.
*Note, flagged not resolved:* that same page carries "**Update** - they are no longer open,"
and this file's §1 records a re-issued DOHMH permit (CAMIS 50185551, first inspected
2026-08-31). Both are consistent with an ownership change; neither is confirmed.

### 1. Labour

Staffing plan from the posted hours (Mon–Fri 07:30–16:30 = 9.0 h; Sat–Sun 08:30–17:00 =
8.5 h), with 45 min open prep and 45 min close on each side.

| | Shifts | h/day |
|---|---|---|
| Weekday | opener 06:45–15:15 (8.5) · peak 07:30–14:00 (6.5) · closer 10:00–17:15 (7.25) | 22.25 |
| Weekend | opener 07:45–15:45 (8.0) · peak 09:00–16:00 (7.0) · closer 10:00–17:45 (7.75) · peak extra 10:00–15:00 (5.0) | 27.75 |

Counter = 5×22.25 + 2×27.75 = **166.75 h/wk**, of which 40 are a shift lead. Plus a baker
40 h/wk (hybrid/in-house) and prep/dish/porter 28 h/wk. Plus an **off-bar multiplier**
tri(1.06, **1.12**, 1.20) for ordering, inventory, scheduling, training, deep clean and
sickness cover — labour the rota does not contain — and a correlated `staffing_level`
tri(0.90, **1.05**, 1.25). Hours scale with revenue at elasticity tri(0.30, **0.45**, 0.60):
labour is semi-fixed, you cannot staff below the minimum needed to open the door.

Wages (base, **no tip credit taken**): lead $25–32, barista $18–22, baker $21–28, prep
$17–20.

| Revenue | h/wk | employees | fully-burdened labour p25 / **p50** / p75 | % of revenue |
|---|---|---|---|---|
| $900,000 | 269 | 10.4 | $333,359 / **$351,915** / $371,766 | **39.1%** |
| $1,200,000 | 292 | 11.3 | $362,375 / **$382,302** / $403,962 | **31.9%** |
| $1,500,000 | 315 | 12.1 | $390,614 / **$412,440** / $435,637 | **27.5%** |

**Employer burden 13.5% of gross wages**, decomposed: FICA 7.65% · FUTA 0.14% · NY SUI
2.58% · workers' comp 2.58% · DBL 0.48%. PFL is employee-paid (0.432% in 2026), so it is
**not** an employer cost. Wages additionally carry ×1.028 for overtime + NY spread-of-hours
and ×1.016 for NYC ESSTA paid sick leave actually used.

*Sources.* NYC minimum wage **$16.50 (2025) → $17.00 (2026)**, CPI-indexed from 2027:
[dol.ny.gov](https://dol.ny.gov/history-minimum-wage-new-york-state). Tip credit —
NY Hospitality Wage Order Part 146; "food service worker" is defined by **function** (primarily
serves food/beverages, regularly receives tips), not by table service, so a counter barista
**can** qualify; 2026 NYC food-service cash wage $11.35 + $5.65 credit; an employer not taking
the credit must pay the full minimum: [12 NYCRR 146-3.4](https://www.law.cornell.edu/regulations/new-york/12-NYCRR-146-3.4),
[DOL CR146](https://dol.ny.gov/system/files/documents/2024/12/cr146.pdf). FUTA 0.6% on first
$7,000, **no NY credit reduction for 2025**: [irs.gov](https://www.irs.gov/businesses/small-businesses-self-employed/futa-credit-reduction).
NY SUI taxable wage base **$12,800 (2025) → $17,600 (2026)**, experienced band 1.7–9.5%:
[dol.ny.gov](https://dol.ny.gov/unemployment-insurance-rate-information). Workers' comp —
NYCIRB restaurant classes, $1.50–$4.00 per $100 payroll: [nycirb.org](https://www.nycirb.org/filings/2024/2024_Loss_Cost_Filing.pdf).
ESSTA 1 h per 30 h, 40 h cap at 5–99 employees ≈ 1.9% of payroll:
[nyc.gov DCWP](https://www.nyc.gov/site/dca/about/paid-sick-leave-FAQs.page). Spread of hours
(+1 h at minimum wage above a 10-h spread, applies regardless of pay rate):
[12 NYCRR 146-1.6](https://www.law.cornell.edu/regulations/new-york/12-NYCRR-146-1.6).
**NYC Fair Workweek does not cover an independent café** (30+ location fast-food chains only).
Brooklyn barista wages $16–$24, avg $18.51: [Indeed](https://www.indeed.com/career/barista/salaries/Brooklyn--NY).

**The tip credit is the single largest discretionary labour lever: taking it would cut
labour by $62k–$74k/yr** (labour 31.9% → 26.2% at $1.2M). The base case assumes it is *not*
taken, which is the norm at NYC specialty cafés. This is checkable and it is the most
consequential thing this model guesses about.

### 2. Cost of goods

Item-level, then weighted by the **same daypart item mix** the revenue section used, so the
COGS blend and the revenue blend cannot drift apart. Unit costs: espresso shot 18 g of a
specialty wholesale bean at $15–19/lb → $0.60–0.75; milk 9 oz at 65% dairy ($0.37) / 35% oat
(Oatly Barista $0.10/oz → $0.91) → $0.56; cup+lid $0.14–0.15 all-in-one; wholesale croissant
$1.83–2.38/unit; wine 20–25% pour cost at 5 pours/750 ml. Waste/spoilage/comps/staff drinks/
espresso dial-in carried as a multiplier, **higher where fresh pastry is delivered daily**.

| Scenario | p25 | **p50** | p75 | beverage COGS | food COGS |
|---|---|---|---|---|---|
| In-house | 22.3% | **23.7%** | 25.2% | 21.1% of bev rev | 26.6% of food rev |
| **Hybrid (base)** | **24.6%** | **26.2%** | **27.9%** | 21.4% | 31.6% |
| All purchased | 30.2% | **32.1%** | 34.2% | 21.8% | 43.8% |

Revenue mix falls out at **53% beverage / 47% food**, alcohol only 3.4%. Benchmark for a café
with a real food menu is 25–35% ([Bzz](https://www.bzz-app.com/industry-cost-benchmarks/coffee-shop),
[Bellwether](https://bellwethercoffee.com/blog/coffee-shop-profit-margins)); the hybrid p50
sits at the low end, which is correct for in-house production — **baking in-house trades COGS
for a baker's wages**. Sources: [Oatly Barista case](https://www.webstaurantstore.com/oatly-barista-edition-oat-milk-32-fl-oz-case/110OTBAROAT.html),
[12 oz cup+lid](https://www.webstaurantstore.com/sofi-12-oz-allinone-paper-hot-cup-and-lid-case/500SHCUP12.html),
[whole milk $5.28/gal Jul-2025](https://pos.toasttab.com/blog/on-the-line/milk-prices),
[Devoción](https://www.devocion.com), [wholesale pastry pricelist](https://www.breadalone.com/wholesale-pricelist).

### 3. Occupancy and fixed (annual, p25 / p50 / p75)

| Line | p25 | **p50** | p75 |
|---|---|---|---|
| Rent (central $9,500/mo) | $114,000 | **$114,000** | $114,000 |
| **NYC Commercial Rent Tax** | **$0** | **$0** | **$0** |
| RE tax / CAM escalation | $3,180 | $4,536 | $6,110 |
| Electric | $8,844 | $10,062 | $11,502 |
| Gas | $4,466 | $5,363 | $6,417 |
| Water / sewer | $1,933 | $2,258 | $2,652 |
| Internet / phone | $1,660 | $1,853 | $2,071 |
| Insurance (BOP + liquor liability) | $4,503 | $5,181 | $6,014 |
| Licences (DOHMH, SLA wine, outdoor) | $2,267 | $2,780 | $3,426 |
| POS / payroll software | $3,863 | $4,518 | $5,292 |
| Repairs & maintenance | $11,212 | $12,900 | $14,996 |
| Waste / linen / cleaning | $9,172 | $10,534 | $12,112 |
| Accounting / legal | $5,911 | $6,915 | $8,122 |
| Smallwares / music / misc | $3,224 | $3,762 | $4,408 |
| Bank / admin | $1,118 | $1,358 | $1,665 |
| **TOTAL FIXED** | **$183,784** | **$187,227** | **$190,785** |

**NYC Commercial Rent Tax does not apply**: it is levied only on premises in **Manhattan
south of 96th Street** ([nyc.gov/finance](https://www.nyc.gov/site/finance/business/business-commercial-rent-tax-crt.page)).
Electric uses Con Ed SC-2 all-in ≈ **$0.338/kWh**
([Con Ed](https://www.coned.com/-/media/files/coned/documents/save-energy-money/using-private-generation/historical-average-full-service-electric-rates.pdf));
DOHMH food-service permit **$280/yr** ([nyc-business](https://nyc-business.nyc.gov/nycbusiness/description/food-service-establishment-permit));
waste is under DSNY Commercial Waste Zones ([nyc.gov/dsny](https://www.nyc.gov/site/dsny/businesses/commercial-waste-zones.page)).

Variable-with-revenue lines at $1.2M: **card processing $38,784 (3.23%)**, delivery
commission $14,131 (1.18%), marketing $12,090 (1.01%).

**Finding on card processing.** At Square's card-present **2.6% + $0.15**
([Square](https://squareup.com/us/en/the-bottom-line/managing-your-finances/credit-card-processing-fees-and-rates)),
the fixed $0.15 on a **$14.40 ticket is 1.04 points on its own**, so the effective rate is
~3.2% of total revenue, not the 2.6% headline. A low-ticket café pays a materially worse rate
than the quoted number. Delivery: NYC's 15%+5% cap is **no longer the binding ceiling** —
Int 762-B (May 2025) plus the litigation settlement let platforms add an optional 20%
"enhanced services" fee plus 3% card fee ([NYC Admin Code §20-563.3](https://codelibrary.amlegal.com/codes/newyorkcity/latest/NYCadmin/0-0-0-134617),
[Restaurant Business](https://restaurantbusinessonline.com/technology/new-york-city-council-votes-lift-cap-delivery-fees)),
so effective commission is carried at tri(15%, **26%**, 38%).

### 4. P&L at the three revenue scenarios

Hybrid baking, rent $9,500/mo, no tip credit. Operating profit is **before owner draw and
before debt service**; D&A and any capex reserve are excluded.

| | $900,000 | | | $1,200,000 | | | $1,500,000 | | |
|---|---|---|---|---|---|---|---|---|---|
| | p25 | **p50** | p75 | p25 | **p50** | p75 | p25 | **p50** | p75 |
| COGS | $221,496 | **$235,539** | $250,766 | $295,321 | **$313,975** | $334,305 | $369,411 | **$393,121** | $417,955 |
| Labour (burdened) | $333,359 | **$351,915** | $371,766 | $362,375 | **$382,302** | $403,962 | $390,614 | **$412,440** | $435,637 |
| Fixed + occupancy | $183,822 | **$187,297** | $190,824 | $183,772 | **$187,222** | $190,771 | $183,800 | **$187,245** | $190,828 |
| Card / delivery / marketing | $46,075 | **$49,233** | $52,682 | $61,378 | **$65,573** | $70,173 | $76,763 | **$82,055** | $87,769 |
| **OPERATING PROFIT** | **$49,507** | **$74,274** | **$98,113** | **$219,753** | **$248,879** | **$276,706** | **$389,154** | **$422,943** | **$455,561** |
| *after $90k owner draw* | −$40,493 | **−$15,726** | $8,113 | $129,753 | **$158,879** | $186,706 | $299,154 | **$332,943** | $365,561 |
| Prime cost % | 62.8% | **65.4%** | 68.1% | 55.9% | **58.2%** | 60.5% | 51.7% | **53.8%** | 56.0% |
| Occupancy % | 13.0% | **13.2%** | 13.3% | 9.8% | **9.9%** | 10.0% | 7.8% | **7.9%** | 8.0% |
| Operating margin % | 5.5% | **8.3%** | 10.9% | 18.3% | **20.7%** | 23.1% | 25.9% | **28.2%** | 30.4% |
| **P(clears a $90k owner income)** | | **33%** | | | **100%** | | | **100%** | |

Benchmarks: prime cost 58–62% ([Toast](https://pos.toasttab.com/blog/on-the-line/restaurant-prime-cost)),
labour 32–38% for a food-led café, café **net margin 10–15%**
([Bellwether](https://bellwethercoffee.com/blog/coffee-shop-profit-margins)). The $1.2M column
sits on benchmark; **the $1.5M column does not** — 28% operating margin is a figure cafés do
not post.

**The baking question barely matters.** In-house vs all-purchased moves operating profit by
−0.8% to +2.0% of revenue: in-house trades ~6 points of COGS for a baker's wages and the two
nearly cancel. It is worth asking the owner, but it is not load-bearing.

### 5. Break-even and sensitivity

| | p25 | **p50** | p75 |
|---|---|---|---|
| Variable cost % | 44.3% | **46.1%** | 47.9% |
| Fixed $ (incl. fixed labour) | $386,029 | **$397,531** | $409,905 |
| **Break-even revenue** | $700,979 | **$738,761** | $779,412 |
| **Break-even incl. $90k owner draw** | $863,194 | **$905,892** | $951,690 |

Sensitivity, effect on operating profit of a 10% **adverse** move, from a $1.2M base
(op profit $249,088):

| Line | Operating profit | Δ |
|---|---|---|
| **Price level −10%** (units unchanged) | $135,516 | **−$113,572** |
| **Traffic −10%** (revenue and COGS both fall) | $178,872 | **−$70,216** |
| Labour +10% | $210,224 | −$38,864 |
| COGS +10% | $217,089 | −$31,999 |
| **Rent +10%** ($950/mo) | $237,650 | **−$11,439** |

**Rent is the least important of the four**, by an order of magnitude. A 10% rent rise costs
$11.4k; a 10% price cut costs $113.6k. Pricing power is the whole business.

### 6. The struggle diagnostic

**Inverting the cost model gives an independent, cost-side read on revenue.** Holding the cost
structure fixed and sweeping revenue, the operating margin passes through the benchmark café
band (10–15%) at:

> **Cost-side revenue read: $933,326 – $1,042,040.**

This is a **fourth estimate of revenue**, and it shares no inputs with the other three: it uses
no demand pool, no EC/CBP anchor, and no transaction count — only wage law, wholesale prices
and NYC fixed costs. It lands **below the bottom-up p25 ($1,349,970)** and **inside the top-down
judgment range ($650k–$1.25M, central $900k)**, close to its upper half.

At rent $9,500/mo:

| Question | Answer |
|---|---|
| Does $900k clear a $90k owner income? | **No.** Op profit p50 $74,274; P(clears) = **33%** |
| Does $1.2M? | Yes, comfortably — $248,879, P = 100% |
| Does $1.5M? | Yes — $422,943. **An owner clearing $423k does not sell.** |
| Minimum revenue that clears $90k | **$950,000** ≈ **172 weekday** / 218 weekend transactions/day |
| Rent at which $1.2M stops clearing $90k | **$22,750/mo** (22.8% occupancy) — i.e. **rent cannot explain a struggle at $1.2M** |
| Revenue at which $1.5M's staffing stops clearing $90k | below **$925,000** ≈ **167 weekday** transactions/day |

**The model's read on "struggling and sold" — stated as the model's inference, not as a fact
about the owner.** The combination most consistent with it is **revenue $800k–$950k, rent
$9,500–$12,500/mo, labour at the full-wage (no tip credit) level**. In that cell operating
profit is $9k–$74k before any owner draw, prime cost is 65–69%, and occupancy is 12–14% — a
business that pays its staff and its landlord and leaves the operator below a Brooklyn living
income. **Rent is not the cause in any cell**; under-scale revenue on a high fixed base is.

This is the cost model's sharpest disagreement with this file's own bottom-up revenue section:
**$1.5M is not merely a high revenue estimate, it is an estimate that contradicts the premise
of the sale.** If revenue were $1.5M the model says the owner cleared >$400k/yr.

### 7. What the owner's answers falsify

| Checkable | Prediction | Falsifier |
|---|---|---|
| **Monthly base rent** | $8,000–$12,000, central $9,500 (pre-registered above) | Outside $8k–$12k |
| **Headcount on payroll** | **10–12** at $1.2M-scale revenue (p50 11.3) | Fewer than 8, or more than 15 |
| **Labour hours/week** | **~292 h/wk** incl. off-bar (269 at $900k) | Below 210 or above 370 |
| **Wage level** | Barista base **$18–22**, lead $25–32 | Base below $17 or above $24 |
| **Tip credit taken?** | **No** — full minimum paid, tips on top | If taken, labour is ~$68k/yr lower and the $900k column clears $90k after all |
| **Bakes in-house?** | **Hybrid** — Turkish savouries in-house, western pastry bought | Either pure case; but this moves op profit <2% of revenue, so it is a weak test |
| **Delivery share** | **4%** of gross (tri 2–8%) | Above 12% — would make platform commission a first-order cost line |
| **Blended COGS %** | **26.2%** (hybrid) | Outside 22–34% |
| **Labour % of revenue** | **31.9%** at $1.2M | Outside 26–40% |
| **Cost-side revenue read** | **$933k–$1.04M** | Truth outside that band means the *cost* structure is wrong, not just the revenue model — and the line most likely wrong is labour hours |

**The strongest single falsifier**: if the owner reports revenue **above $1.3M** *and*
describes the business as having struggled, then the cost model is wrong somewhere large —
most likely labour hours (a 1,000 sq ft café may simply carry far more staff than 292 h/wk),
or an unmodelled cost the P&L has no line for (debt service on a build-out loan, a percentage-
rent clause, a partner buy-out, or back taxes). In that case the finding is that **operating
profit was never the binding constraint**, and a cost model built from wage law and wholesale
prices cannot see what actually broke.

---

## Owner evidence log (after the predictions; dated)

- **2026-09-13, via the owner's contact:** "during covid he made more money." Qualitative; no figure. Model read: consistent with a labour-fixed-cost-bound café — in 2020–21 the fixed base fell (shortened hours, takeout-only, 1–2 staff instead of three shifts), the patio/outdoor-dining program added seats at zero rent, PPP/RRF grants and rent relief added cash, competitors closed, and Williamsburg's work-from-home residents became all-day customers for a café that lives on its 400 m shed. Post-2022 every one of those reversed: full 62-hour rota at $16.50 → $17.00 minimum wage with the SUI base tripling, weekday daytime thinned by return-to-office, delivery commissions uncapped in 2025, competitors back. Nothing in this datum distinguishes the $900k and $1.5M revenue camps; it does favour the cost model's mechanism (profit driven by the labour base and local daytime demand, not by rent).
