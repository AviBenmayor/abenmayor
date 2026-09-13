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
