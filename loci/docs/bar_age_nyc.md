# The New York bar–age relationship, derived from revealed supply

**Status:** ANALYSIS ONLY. Read-only against `data/loci.duckdb`. Nothing under `src/` or
`tests/` was touched, nothing committed. The recommendation is **build it, from one
specific specification, as a labelled non-filtering ranking column** — with the failure
criterion stated up front so a future session can re-run it and kill it.

**Date:** 2026-09-09
**Scope:** Manhattan + Brooklyn (D48).
**Owner request:** *"a bar gap in the Upper East Side where avg age is 60+ vs a bar gap in
the East Village where avg age is 25 — the East Village bar should score higher."*
**Predecessor:** `docs/age_demand_fit.md` (BLS CEX household spend) — rejected for `bar`;
the national household budget survey's alcohol profile peaks at 45–54 and produced a
multiplier with a p10–p90 spread of **0.013** against a median MOE of 0.140.

**One-line answer:** the market-revealed relationship exists, has the owner's sign, is
specific to `bar` (it is the largest of all fifteen categories, and `pharmacy` is the most
negative), survives spatial-HAC standard errors, and is **25× larger** than the CEX
multiplier it replaces — but only in one specification, and that specification is a
*composition* measure (what share of the licensed venues near here are bar-type), not a
count. The count specifications do not survive in Brooklyn, which is where 98% of the
bar-lead gap set actually lives.

---

## 1. Data and counts used

Everything is already in the warehouse. No new source, no network call.

| Input | Table | MN+BK count used |
|---|---|---|
| Residential addresses | `analysis.address` ⋈ `analysis.address_demographics` | **281,842** (all have a tract) |
| Census tracts | grouped from the above | 1,078 → **1,075** with population ≥ 100 → **1,065** in the regression |
| Active SLA licences | `staging.alcohol_licences` (`active`, MN+BK) | **16,126** |
| — `on_premises` | " | **10,757** |
| — **bar-type** (see §1.1) | " | **2,301** |
| — full-liquor class (03xx/04xx) | " | 8,222 |
| — restaurant-wine class (02xx) | " | 2,293 |
| Canonical `bar` POIs | `analysis.poi_supply`, `in_principled` | 5,011 (citywide) |
| Canonical `restaurant` POIs | " | 39,459 (citywide) |
| Bar reach / gap columns | `analysis.address_category` (`category='bar'`) | 767,337 rows citywide |

Ten tracts with population ≥ 100 are dropped from the regression because ACS publishes no
median household income for them (large-institution and very-low-response tracts, e.g.
36061001600 with population 7,040). They are **kept** in every descriptive table in §2.

### 1.1 A finer bar-vs-restaurant licence type does exist, and it is used

The task asked whether the raw SLA fields resolve bars from restaurants. They do, two ways,
and both are used:

1. **Description.** `nys_sla.py`'s own `BAR_DESCRIPTIONS` set — `food & beverage business`
   (+ summer/winter variants), `club`, `cabaret`, `bottle club`, `night club` — is the
   vocabulary that already decides what enters `staging.poi` as a `bar`. Applied to the
   overlay it isolates **2,301** of the 10,757 on-premises licences. The residual is
   dominated by `Restaurant` (5,858), `Additional Bar` (1,643 — a *rider* on an existing
   premises, per `alcohol_licences.yaml`) and `Hotel` (304). **There is no `Tavern` licence
   type in the NYC feed** (one row, `Summer - Tavern Miscellaneous`).
2. **Class code.** The SLA class prefix separates privilege level: `03xx`/`04xx` = the
   on-premises-liquor family (full liquor, plus cabaret/bottle-club/additional-bar riders),
   `02xx` = restaurant *wine* only, `01xx` = beer only. `Restaurant` appears under both
   0340 (4,168, full liquor) and 0240 (1,685, wine only) — so the description alone
   understates how many "restaurants" are licensed to run a bar.

Outcomes are therefore reported three ways throughout: **all on-premises** (the broad,
restaurant-dominated set the task named), **bar-type licences** (the 2,301), and
**canonical `bar` POIs** (what the screen actually counts). They do not agree, and the
disagreement is the finding.

### 1.2 Two controls the task asked for do not exist in this warehouse

- **`analysis.hex_controls.subway_riders_2024` is NULL on all 8,321 rows.** Station
  ridership cannot be used as a control. Stated rather than silently substituted.
- **`analysis.hex_panel` is not total LODES jobs.** It carries exactly two NAICS sectors:
  `CNS07` (retail trade, 303,835 jobs citywide 2023) and `CNS18` (accommodation and food
  services, 332,020). There is no total-employment daytime-population proxy in the DB.
  **`CNS18` must never be used as a control here** — accommodation-and-food-services payroll
  *is* the outcome measured in employees rather than storefronts, so conditioning on it is
  conditioning on the dependent variable. It is reported once (spec C) to show exactly how
  much of the age effect it absorbs, then set aside. `CNS07` retail jobs is the daytime
  control that is actually used.
- `walk_m_to_subway` is present on 5,845 of 8,321 hexes; a tract gets the value of the
  **nearest hex centroid that has one**.

### 1.3 Unit of analysis and geometry

- **Unit: census tract** (the ACS native grain — an address's demographics are its tract's,
  looked up by BBL under D56, with nothing apportioned).
- **Centroid: the `units_capped`-weighted mean of the tract's address coordinates**, i.e. a
  *residential* centroid, not the geometric one. A geometric tract centroid can land in a
  park, a rail yard or the middle of Prospect Park; the residential centroid is where the
  households are, which is the point.
- **Discs: 400 m straight-line** (the bar reach tier), plus 800 m as robustness. Straight
  line, not network: under D53's measured circuity of 1.233 a 400 m disc corresponds to
  roughly 493 m of walking. Distances are computed in EPSG:32618.
- **Exposure: `units_capped` inside the same 400 m disc**, not the tract's own unit count.
  A tract's units and a 400 m disc around its centroid are different geographies; using the
  tract count as the denominator for a disc count would be a units mismatch. (Both are in
  the panel; the disc version is what the regression uses.)

---

## 2. Descriptive: the gradient is real, large and monotone

### 2.1 By decile of adult 18–34 share

Adult shares are renormalized over adults (`w = share / (1 − under_18_share)`), the same
convention as `docs/age_demand_fit.md` §2.1. 1,075 tracts, population ≥ 100.

| decile | n | mean w18 | median age | median units 400 m | **median on-prem 400 m** | on-prem /1k units | **median bar-type 400 m** | bar-type /1k units | **median bar POIs 400 m** | bar POIs /1k units | median on-prem 800 m |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 (oldest) | 108 | 0.15 | 49.8 | 3,627 | 3.5 | 1.36 | 1.0 | 0.20 | 1.0 | 0.30 | 24.0 |
| 2 | 107 | 0.21 | 44.1 | 3,631 | 6.0 | 1.65 | 1.0 | 0.47 | 2.0 | 0.61 | 19.0 |
| 3 | 108 | 0.24 | 41.3 | 3,648 | 5.0 | 1.41 | 1.0 | 0.25 | 1.0 | 0.37 | 18.0 |
| 4 | 107 | 0.27 | 40.0 | 3,981 | 5.0 | 1.38 | 1.0 | 0.29 | 1.0 | 0.36 | 23.0 |
| 5 | 108 | 0.30 | 38.4 | 3,764 | 4.0 | 1.12 | 1.0 | 0.24 | 1.0 | 0.29 | 18.5 |
| 6 | 107 | 0.32 | 37.7 | 4,735 | 8.0 | 1.84 | 2.0 | 0.38 | 3.0 | 0.55 | 41.0 |
| 7 | 107 | 0.35 | 36.0 | 5,278 | 8.0 | 2.03 | 3.0 | 0.49 | 3.0 | 0.78 | 36.0 |
| 8 | 108 | 0.39 | 34.7 | 5,426 | 11.0 | 2.15 | 4.0 | 0.59 | 5.0 | 0.88 | 48.5 |
| 9 | 107 | 0.44 | 34.0 | 5,726 | 18.0 | 2.91 | 5.0 | 0.78 | 6.0 | 1.05 | 77.0 |
| **10 (youngest)** | 108 | **0.55** | **31.7** | 5,950 | **34.5** | **4.92** | **10.5** | **1.41** | **13.5** | **2.12** | **125.5** |

**Decile 1 → 10: median on-premises licences within 400 m go 3.5 → 34.5 (10×); per 1,000
housing units 1.36 → 4.92 (3.6×); bar-type licences 1 → 10.5; canonical bar POIs 1 → 13.5
(per 1k units 0.30 → 2.12, 7.1×).** Monotone from decile 5 upward, and the per-1k column
shows the gradient is not purely a density artifact.

### 2.2 By decile of adult 65+ share

| decile | n | mean w65 | median age | median units 400 m | median on-prem 400 m | on-prem /1k units | median bar-type 400 m | median bar POIs 400 m | bar POIs /1k units |
|---|---|---|---|---|---|---|---|---|---|
| 1 (fewest 65+) | 108 | 0.06 | 32.9 | 5,429 | **23.0** | 4.12 | 7.0 | 9.5 | 1.60 |
| 2 | 107 | 0.11 | 34.2 | 5,599 | 17.0 | 2.92 | 5.0 | 7.0 | 1.34 |
| 3 | 108 | 0.14 | 35.5 | 4,989 | 11.0 | 2.15 | 3.0 | 4.0 | 0.79 |
| 4 | 107 | 0.16 | 36.5 | 4,205 | 6.0 | 1.43 | 2.0 | 2.0 | 0.57 |
| 5 | 108 | 0.18 | 36.9 | 5,143 | 8.0 | 1.69 | 2.0 | 2.0 | 0.44 |
| 6 | 107 | 0.20 | 38.9 | 4,438 | 6.0 | 1.52 | 1.0 | 2.0 | 0.54 |
| 7 | 107 | 0.23 | 39.7 | 4,170 | 7.0 | 1.58 | 1.0 | 2.0 | 0.47 |
| 8 | 108 | 0.26 | 41.6 | 3,563 | 3.0 | 1.05 | 0.5 | 1.0 | 0.27 |
| 9 | 107 | 0.29 | 43.8 | 3,754 | 5.0 | 1.60 | 1.0 | 1.0 | 0.44 |
| **10 (most 65+)** | 108 | **0.39** | **49.9** | 3,708 | **5.0** | **1.50** | 1.0 | 1.0 | 0.40 |

Same gradient mirrored: 23 → 5 on-premises, 9.5 → 1 bar POIs. Note the two age variables are
correlated at **r = −0.67**, which is why §3's *conditional* coefficients tell a different
story from these marginal tables.

### 2.3 The four named NTAs

Address-level: for each address, licences and POIs within 400 m of **that address**; the
column is the median over the NTA's addresses.

| NTA | addrs | tracts | median age | w18 | w65 | median HH income | **on-prem 400 m** | **bar-type 400 m** | full-liquor 400 m | **bar POIs 400 m** | on-prem 800 m | bar `nearest_m` | bar `ratio` | bar-lead gaps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **East Village** | 1,927 | 19 | **33.6** | **0.540** | 0.184 | $92,434 | **197** | **55** | 127 | **87** | 603 | **13 m** | 0.034 | **0** |
| **UES–Carnegie Hill** | 2,251 | 24 | **52.4** | **0.158** | **0.404** | $199,167 | **49** | **11** | 36 | **14** | 214 | **90 m** | 0.224 | **0** |
| UES–Lenox Hill–Roosevelt Is. | 1,221 | 19 | 37.6 | 0.345 | 0.238 | $144,856 | 70 | 12 | 48 | 19 | 225 | 89 m | 0.223 | 9 |
| UES–Yorkville | 1,330 | 15 | 42.8 | 0.294 | 0.229 | $152,500 | 70 | 14 | 48 | 21 | 201 | 80 m | 0.200 | 3 |

**The median East Village address has 197 on-premises licences, 55 bar-type licences and 87
bar POIs within 400 m; the median Carnegie Hill address has 49, 11 and 14 — 4.0×, 5.0× and
6.2×.** The market has already answered the owner's question, at 6× magnitude, on the
category-specific measures.

And, unchanged from the CEX note: **neither neighbourhood has a bar gap.** Median bar
`nearest_m` is 13 m in the East Village and 90 m in Carnegie Hill, both deep inside the
400 m reach. There is nothing in either place for a multiplier to re-rank.

---

## 3. Regression

`log(1 + Y_400m) ~ w18 + w65 + log(units within 400 m) + log(1 + CNS07 retail jobs 400 m)
+ log(walk_m_to_subway) + log(median HH income) + renter_share + Manhattan FE`, n = 1,065.
`w18` and `w65` are adult shares; the omitted band is **35–64**, so both coefficients read
*relative to a 35–64 adult*.

Two standard errors are reported for every coefficient: HC3, and **Conley spatial-HAC**
(Bartlett kernel, 2,000 m cutoff). §3.3 explains why only the second one may be quoted.

### 3.1 Main table — MN+BK pooled

| outcome (400 m) | daytime ctrl | b(w18) | HC3 se | **Conley se** | **t (Conley)** | b(w65) | t (Conley) | R² |
|---|---|---|---|---|---|---|---|---|
| all on-premises | none | +1.168 | 0.398 | 0.635 | +1.84 | +1.116 | +1.43 | 0.641 |
| **all on-premises** | **CNS07** | **+0.757** | 0.356 | **0.565** | **+1.34** | +0.691 | +1.08 | 0.696 |
| all on-premises | CNS07 + CNS18† | +0.584 | 0.299 | — | — | +0.671 | — | 0.790 |
| bar-type licences | none | +1.370 | 0.360 | 0.594 | +2.31 | +0.421 | +0.64 | 0.557 |
| **bar-type licences** | **CNS07** | **+1.161** | 0.347 | **0.570** | **+2.04** | +0.205 | +0.35 | 0.581 |
| bar POIs | none | +1.500 | 0.386 | 0.632 | +2.37 | +0.497 | +0.72 | 0.579 |
| **bar POIs** | **CNS07** | **+1.256** | 0.365 | **0.596** | **+2.11** | +0.245 | +0.41 | 0.607 |
| **bar-type SHARE of on-prem**‡ | **CNS07** | **+0.405** | 0.163 | **0.203** | **+2.00** | **−0.486** | **−1.74** | 0.395 |
| all on-premises, **800 m** | CNS07 | +0.120 | 0.302 | — | +0.40 (HC3) | +0.414 | +0.80 | 0.756 |

† `CNS18` is accommodation-and-food-services employment — the outcome in payroll form.
Shown once to size the absorption (§5b), never used.
‡ Outcome `log(1+bar-type) − log(1+on-premises)`: what fraction of the licensed venues
near here are bar-type. Nets out commercial intensity mechanically.

**Poisson and negative-binomial check** (same RHS, count outcome = on-premises within
400 m, HC3): Poisson b(w18) = +1.405 (se 0.409, p = 0.0006), b(w65) = +1.917 (se 0.568).
Overdispersion α estimated at 0.339; NB2 gives b(w18) = +1.019 (se 0.425, p = 0.017),
b(w65) = +1.411 (se 0.714). The count models agree with OLS on sign and rough magnitude, so
the log(1+y) transform is not driving the result.

**Partial Spearman (the D54-style pre-test), net of log units within 400 m:**

| | ρ(w18) | p | ρ(w65) | p |
|---|---|---|---|---|
| on-premises 400 m | **+0.103** | 0.0008 | −0.146 | 1.6e−06 |
| bar-type 400 m | **+0.160** | 1.4e−07 | −0.210 | 3.9e−12 |
| bar POIs 400 m | **+0.159** | 1.8e−07 | −0.201 | 3.7e−11 |

Net of density and the full control set (income, walk-to-subway, Manhattan) the on-premises
partial is ρ = +0.114 (p = 0.0002). Small but robustly signed, and **larger on the
bar-specific outcomes than on the restaurant-dominated one** — the first sign that the
effect is about bars, not about commercial streets.

### 3.2 The owner's contrast, priced

Moving from the Carnegie Hill adult age mix (w18 = 0.158, w65 = 0.404) to the East Village
mix (w18 = 0.540, w65 = 0.184), **holding every control fixed**. Ratio of predicted
(1 + count); 95% CI from the Conley covariance.

| specification | ratio | 95% CI (HC3) | **95% CI (Conley 2 km)** |
|---|---|---|---|
| all on-premises, no daytime ctrl | 1.222 | [0.917, 1.628] | [0.849, 1.759] |
| all on-premises, + CNS07 | 1.147 | [0.890, 1.478] | [0.825, 1.593] |
| all on-premises, + CNS07 + CNS18 | 1.078 | [0.886, 1.313] | — |
| all on-premises, **800 m** | **0.956** | [0.773, 1.181] | — |
| **bar-type licences, + CNS07** | **1.490** | [1.181, 1.878] | **[1.063, 2.088]** |
| **bar POIs, + CNS07** | **1.531** | [1.200, 1.953] | **[1.075, 2.182]** |
| **bar-type share of on-prem** | **1.299** | [1.147, 1.470] | **[1.124, 1.501]** |
| median-age spec, 52.4 → 33.6 yrs (on-prem) | **0.723** | — | wrong sign |
| w18 only (w65 dropped) | 1.191 | [0.937, 1.514] | — |
| + college_share and one_person_hh_share | 1.252 | [0.995, 1.577] | — |
| Manhattan only | 1.219 | [0.858, 1.733] | — |
| Brooklyn only | 1.059 | [0.784, 1.429] | — |

Four things this table says that the headline gradient does not:

1. **On the broad on-premises outcome the effect is not significant** and, at 800 m, it
   reverses to 0.96. The age signal is a 400 m signal; at 800 m the discs overlap so much
   that the variation is smoothed away.
2. **On the bar-specific outcomes it is significant and large — 1.49 and 1.53 — and it
   survives Conley SEs.**
3. **The `median_age` specification has the owner's sign reversed** (+0.017 per year of
   median age on the on-premises count, so 52.4 → 33.6 gives 0.72). Conditional on income,
   density and Manhattan, an *older* tract has *more* licensed venues: the UES is old,
   rich and dense. If age is ever shipped, it must be shipped as the 18–34 share, never as
   median age.
4. **`w65` is positive on every count outcome.** Only the composition spec turns it
   negative (−0.486, t = −1.74). So "the 65+ half of the owner's claim" — old
   neighbourhood, fewer bars — **is not supported by the count models**; the marginal
   negative gradient in §2.2 is the −0.67 correlation with w18 doing the work. Only the
   composition spec supports both halves at once.

### 3.3 Spatial autocorrelation

KNN(k = 8) row-standardized weights on the tract residential centroids, `esda.Moran`:

| | Moran's I | z | p |
|---|---|---|---|
| raw `log(1+on-prem 400 m)` | **0.818** | — | — |
| raw `w18` | 0.458 | — | — |
| residual, no daytime control | **0.468** | 31.8 | 2e−222 |
| residual, + CNS07 | **0.415** | 28.2 | 9e−175 |
| residual, + CNS07 + CNS18 | 0.330 | 22.5 | 1e−111 |

**The residuals are massively spatially autocorrelated, so the HC3 standard errors are not
usable.** Neighbouring tracts share the same nightlife district, the same zoning, the same
400 m discs (adjacent tract centroids are often < 400 m apart, so their outcome discs
physically overlap and their errors are correlated by construction). The effective sample
size is far below 1,065 — closer to the number of distinct commercial districts.

Conley Bartlett-kernel SEs at 1,000 m and 2,000 m cutoffs inflate the age SEs by
**1.3–1.7×**. The conclusions above use the 2,000 m version, the more conservative. It is
still a lower bound: with I ≈ 0.4 after controls, a spatial-error or spatial-lag model would
be the honest next step, and it would shrink the coefficient itself, not just widen its
band. **Every CI in this note should be read as optimistic.**

---

## 4. The candidate multiplier

```
age_fit_bar(tract) = exp[ b18 · (w18_tract − w18_MNBK) + b65 · (w65_tract − w65_MNBK) ]
```

which is exactly "predicted bar density at this tract's age mix ÷ predicted at the MN+BK
average age mix, all controls at their own values". The anchor is the **unit-weighted**
MN+BK adult mix: w18 = 0.3386, w65 = 0.1972 (unweighted tract means 0.3226 / 0.2028).

MOE combines the Conley coefficient covariance with the ACS share MOEs
(`w_moe = share_moe / (1 − under_18_share)`, converted to SE at 1.645) and is re-inflated
to a 90% MOE.

### 4.1 Distribution and the dispersion gate

The gate is the one `docs/age_demand_fit.md` §5 defined: **spread(p90 − p10) > median MOE**.

| built from | b18 | b65 | tract p10 | p50 | p90 | **spread** | median MOE | **spread/MOE** | gate |
|---|---|---|---|---|---|---|---|---|---|
| bar POIs (spec F) | +1.256 | +0.245 | 0.846 | 0.969 | 1.164 | **0.318** | 0.124 | **2.57** | PASS |
| bar-type licences (spec E) | +1.161 | +0.205 | 0.855 | 0.970 | 1.152 | 0.297 | 0.117 | 2.53 | PASS |
| **bar-type share (spec G)** | **+0.405** | **−0.486** | 0.899 | 0.988 | 1.099 | **0.201** | **0.056** | **3.61** | **PASS** |
| *CEX `ALCBEVG` budget share (predecessor)* | — | — | 0.994 | 1.000 | 1.008 | *0.013* | *0.140* | *0.10* | *fail* |

**The supply-revealed multiplier clears the same gate the CEX one failed by a factor of ten,
and clears it by 2.5–3.6×.** Its p10–p90 spread is 15–25× wider.

Over addresses (all MN+BK, 281,842): spec F p10/p50/p90 = 0.845 / 0.956 / 1.134; spec G
0.900 / 0.983 / 1.083.

**The four NTAs** (unit-weighted mean over addresses):

| NTA | age_fit (bar POIs) | ±MOE | age_fit (bar-type) | **age_fit (share spec)** | ±MOE |
|---|---|---|---|---|---|
| **East Village** | **1.210** | 0.261 | 1.193 | **1.079** | 0.084 |
| UES–Lenox Hill–Roosevelt Is. | 1.022 | 0.139 | 1.020 | 0.990 | 0.059 |
| UES–Yorkville | 0.968 | 0.120 | 0.969 | 0.957 | 0.057 |
| **UES–Carnegie Hill** | **0.891** | 0.148 | 0.895 | **0.885** | 0.072 |

East Village / Carnegie Hill = **1.358** on the bar-POI spec, **1.219** on the share spec.
The owner's ordering is produced, and on the share spec the separation (0.194) exceeds each
NTA's own MOE (0.084, 0.072).

### 4.2 Over the current bar-lead gap set

`eligible ∧ gap_score > 1 ∧ lead_category = 'bar'` → **67,223 addresses in 82 clusters**
(one cluster has a null `gap_score`, leaving 81 rankable). **65,980 of them (98.2%) are in
Brooklyn** — Canarsie 8,458, Flatlands 6,134, Bensonhurst 5,284, Borough Park 4,309,
Sheepshead Bay 3,188, East Flatbush 3,140+2,495, Midwood 2,793. Manhattan contributes 1,243.
Neither the East Village nor any UES NTA is in the set.

| | p10 | p50 | p90 |
|---|---|---|---|
| `gap_score` in the set | 1.204 | 1.791 | 2.865 |
| `age_fit` spec F (bar POIs) | 0.838 | 0.939 | 1.057 |
| `age_fit` spec E (bar-type) | 0.850 | 0.943 | 1.053 |
| **`age_fit` spec G (share)** | **0.899** | **0.962** | **1.038** |

The gap set is systematically *older* than the MN+BK average — median `age_fit` 0.94–0.96 —
so the multiplier's main effect there is a mild uniform discount plus a real reshuffle.

### 4.3 How much the ranking actually moves

Cluster score = unit-weighted mean, matching the predecessor note's method.

| built from | **Jaccard @ top-50 clusters** | @25 | @100 | cluster Spearman | address Spearman | Jaccard addr @100 | @1,000 | max top-50 cluster rank shift |
|---|---|---|---|---|---|---|---|---|
| bar POIs (F) | **0.818** | 0.724 | 1.000 | 0.888 | 0.960 | 0.739 | 0.679 | **32** |
| bar-type licences (E) | 0.818 | 0.724 | 1.000 | 0.898 | 0.965 | 0.739 | 0.732 | 31 |
| **bar-type share (G)** | **0.923** | 0.786 | 1.000 | 0.953 | 0.983 | 0.786 | 0.799 | **22** |
| *CEX `ALCBEVG` share (predecessor)* | *1.000* | *1.000* | *1.000* | *0.999* | *0.9999* | — | — | *3* |

**Said honestly: this moves the ranking, and the CEX multiplier did not.** At the top-50
cluster level it swaps 9 of 50 clusters (spec F) or 4 of 50 (spec G), and it moves an
individual cluster by up to 32 ranks. At address grain the top-1,000 overlap is only 68–80%.
This is a real intervention on the output, not a cosmetic annotation — which is exactly why
the failure criterion in §7 has to bind.

---

## 5. Red team

**(a) Supply-revealed is endogenous, and that is the whole point — but it must be labelled.**
Every coefficient here is fitted on where bars *already are*. Young renters sort into
neighbourhoods that already have bars at least as strongly as bars open where young renters
already live (Zukin 2009; the project's own H-L6). So `b18` is a mixture of demand and
residential sorting, and there is no instrument here that separates them. For the question
the owner actually asked — *where does a bar succeed* — a demand-plus-sorting coefficient is
the right object: an operator inherits both. But it means `age_fit_bar` is partly a lagged
read of existing bar supply, which is the **rejected D1 thesis** (retail as a growth
predictor) trying to re-enter through a demographic side door. Three things keep it out.
First, the multiplier is built only from the two ACS age shares — no supply variable ever
enters the formula that touches an address, so it cannot carry a lagged bar count into the
rank arithmetically. Second, it must never gate, never filter, and never touch `gap_score`.
Third, the disclaimer must say *supply-revealed*: this is a statement about where the New
York market has historically put bars relative to resident age, not evidence that a
neighbourhood without one does not want one. The gap set is a *latent*-demand instrument by
design; a factor that scores highest where the amenity already exists inverts that, and the
only defence is that the factor is small relative to `gap_score` (spread 0.20 vs 1.66) and
visibly separate from it.

**(b) Resident age vs who is actually there at night — the controls are weaker than they
look.** The nighttime population is the right denominator for a bar and this warehouse has
no measure of it. Station ridership (`subway_riders_2024`) is NULL on every row.
`hex_panel` is not total employment; it is retail trade plus accommodation-and-food-services
only. Using `CNS07` retail jobs as the daytime control moves b(w18) on the on-premises count
from **+1.168 → +0.757** (−35%) and on bar POIs from **+1.500 → +1.256** (−16%): retail
employment absorbs a third of the "young share" effect on the broad measure but only a sixth
on the bar-specific one. Adding `CNS18` food-service jobs takes b(w18) to +0.584, but that
control is illegitimate — food-service payroll *is* the outcome — and it is reported only to
bound the absorption. The honest summary is that a real nighttime-population control does
not exist here and the age coefficient is therefore partly a proxy for "how much of the
evening economy is here", which is itself partly supply. The 800 m collapse (ratio 0.956) is
the same warning in another form: at the scale where a nightlife district is one unit rather
than several, the resident-age variation stops explaining anything.

**(c) Collinearity: the multiplier is not a low-resolution Manhattan indicator, and the
placebo proves it.** VIFs are unalarming — w18 2.09, w65 2.25, log units 2.83, log income
4.79, renter share 2.68, Manhattan 2.19, retail jobs 1.70 (college_share 5.05 is the worst,
which is why it is not in the main spec; it correlates 0.80 with log income). w18 correlates
0.46 with renter share, 0.29 with density and only **0.12 with Manhattan**. The decisive
test is the placebo: run the *identical* specification with every one of the fifteen
principled categories as the outcome. If b(w18) were a generic urbanity coefficient it would
be large and positive everywhere.

| category | n POI | **b(w18)** | Conley se | t | b(w65) |
|---|---|---|---|---|---|
| **bar** | 5,011 | **+1.256** | 0.596 | **+2.11** | +0.245 |
| tailor_repair | 966 | +1.080 | 0.345 | +3.13 | +1.671 |
| cafe_bakery | 8,038 | +0.664 | 0.386 | +1.72 | +0.497 |
| bank | 5,222 | +0.421 | 0.361 | +1.17 | +1.556 |
| hardware | 2,765 | +0.264 | 0.277 | +0.95 | −0.598 |
| clinic | 8,097 | +0.258 | 0.376 | +0.69 | +1.703 |
| restaurant | 39,459 | +0.176 | 0.421 | +0.42 | −0.356 |
| hair_barber | 15,601 | +0.144 | 0.501 | +0.29 | −0.660 |
| fitness | 10,416 | +0.138 | 0.416 | +0.33 | +0.368 |
| laundry | 4,979 | −0.463 | 0.376 | −1.23 | −0.714 |
| grocery | 15,504 | −0.516 | 0.267 | −1.94 | −1.739 |
| childcare | 4,302 | −0.574 | 0.307 | −1.87 | −0.816 |
| convenience | 4,740 | −0.619 | 0.405 | −1.53 | −2.208 |
| nails_beauty | 9,412 | −0.630 | 0.505 | −1.25 | −0.457 |
| **pharmacy** | 5,536 | **−0.846** | 0.316 | **−2.68** | −0.054 |

**`bar` has the largest positive coefficient of all fifteen and `pharmacy` the most
negative, with grocery, convenience and childcare also negative.** That ordering is
category-specific, interpretable, and — this is the striking part — it **independently
reproduces the CEX note's only two passing categories with the same signs** (pharmacy old,
childcare not-young) from a completely different source. A generic Manhattan/density factor
could not produce a −0.85 for pharmacy in the same regression that gives +1.26 for bar. The
one anomaly is `tailor_repair` (+1.08, t = 3.13 on only 966 POIs), which is almost certainly
the Garment District and dry-cleaner clustering rather than an age effect; it is a reminder
that a significant t on a thin category is not a finding.

---

## 6. The test the descriptive tables cannot pass: out-of-sample

A coefficient that is significant in-sample and adds nothing out-of-sample is a description,
not a model. Spatial-block 10-fold CV (KMeans on the tract centroids, so each held-out fold
is a contiguous chunk of the city and no fold can be predicted from its own neighbours),
RMSE of `log(1 + Y within 400 m)`:

| outcome | mean-only | density-only | full controls, no age | **+ age** | gain vs density-only | **gain vs full controls** |
|---|---|---|---|---|---|---|
| bar POIs | 1.345 | 1.021 | 0.854 | **0.852** | **+0.87%** | **+0.27%** |
| bar-type licences | 1.222 | 0.939 | 0.803 | 0.801 | +1.09% | +0.26% |
| all on-premises | 1.604 | 1.146 | 0.880 | 0.883 | −0.22% | **−0.33%** |

Cross-borough transfer:

| | with age | no age | gain |
|---|---|---|---|
| fit Brooklyn → predict Manhattan (bar POIs) | 1.096 | 1.084 | **−1.10%** |
| fit Manhattan → predict Brooklyn (bar POIs) | 0.980 | 0.991 | +1.14% |
| fit Brooklyn → predict Manhattan (bar-type) | 1.007 | 0.991 | **−1.66%** |
| fit Manhattan → predict Brooklyn (bar-type) | 0.916 | 0.925 | +1.00% |

Brooklyn-only spatial CV (the gap set's home):

| outcome | density-only → + age | full controls → + age |
|---|---|---|
| bar POIs | 0.925 → 0.895 (**+3.17%**) | 0.774 → 0.777 (−0.43%) |
| bar-type licences | 0.857 → 0.826 (**+3.60%**) | 0.731 → 0.732 (−0.12%) |

**Read this carefully, because it is the result that decides the design.** Age adds
**+3.2 to +3.6%** out-of-sample over a density-only model in Brooklyn — real, and the
relevant comparison, because `gap_score` knows about supply and reach and *nothing else*.
But it adds **≈ 0%** over a model that already has income, renter share, walk-to-subway and
retail employment, and it transfers *negatively* from Brooklyn to Manhattan. So:

> `age_fit_bar` carries genuine information relative to what the screen currently knows, and
> almost no information that is *uniquely age*. It is a compact proxy for a bundle —
> young-renter-dense-transit-rich-commercial — not an isolated age effect.

That has to be in the label, or the column will be over-read.

### 6.1 Where the specifications diverge — and why spec G wins

Split the pooled regression by borough (Conley 2 km SEs, borough-internal):

| | outcome | b(w18) | t | b(w65) | t | CH → EV ratio, Conley CI |
|---|---|---|---|---|---|---|
| **Brooklyn** (n = 770) | bar POIs | +0.894 | +1.38 | −0.242 | −0.38 | 1.484 [**1.011**, 2.178] |
| | bar-type licences | +0.955 | +1.50 | −0.296 | −0.45 | 1.537 [1.074, 2.201] |
| | **bar-type share** | **+0.596** | **+2.44** | **−0.662** | −1.71 | **1.452 [1.197, 1.763]** |
| | all on-premises | +0.360 | +0.53 | +0.366 | +0.49 | 1.059 [0.717, 1.564] |
| **Manhattan** (n = 295) | bar POIs | +1.688 | +1.82 | +1.091 | +1.25 | 1.499 [0.906, 2.480] |
| | bar-type licences | +1.371 | +1.55 | +0.942 | +1.18 | 1.372 [0.841, 2.239] |
| | bar-type share | +0.044 | +0.15 | −0.460 | −1.34 | 1.125 [0.951, 1.332] |

**In Brooklyn — where 98% of the bar-lead gap set lives — the count specifications are not
significant** (t = 1.38, 1.50; the bar-POI CI grazes 1 at 1.011). **The composition
specification is the only one that holds there**, at t = +2.44, with a tighter CI than the
pooled model, and with **both** age coefficients carrying the owner's expected sign
(+0.596 young, −0.662 old). In Manhattan the reverse: the counts carry the effect and the
composition spec is null. The two boroughs run on different mechanisms — Manhattan's bar
geography is a destination-district geography that resident age partly *labels*; Brooklyn's
is a neighbourhood-composition geography that resident age partly *drives* — and pooling
them produces a blend that is well identified in neither.

Calibrating a multiplier on the pooled sample and applying it to a Brooklyn gap set would be
fitting where the signal is and shipping where it isn't. The composition spec is the one
that is estimated where it will be used.

---

## 7. Recommendation

**Build `age_fit_bar`, from the composition specification (spec G), as a separate
non-filtering ranking column — and only that specification.**

It is the only candidate that satisfies all five requirements at once:

1. **It gets the owner's sign on both halves.** +0.405 on 18–34 and **−0.486** on 65+
   (pooled); +0.596 / −0.662 in Brooklyn. Every count specification has `w65` *positive*,
   which contradicts the "UES is old, so score it lower" half of the request.
2. **It holds where the gap set is.** Brooklyn-only t = +2.44 under Conley SEs, CI
   [1.197, 1.763] on the Carnegie-Hill → East-Village contrast. The count specs are
   insignificant in Brooklyn.
3. **It clears the derived dispersion gate by the widest margin** — spread/MOE = 3.61
   against the CEX `bar` multiplier's 0.10, a 36× improvement on the test that retired the
   predecessor.
4. **It is the least confounded with commercial intensity**, because a share of on-premises
   licences nets that out mechanically rather than through a control — which matters when
   the only available daytime controls are two NAICS sectors, one of which is the outcome.
5. **It moves the ranking least while still moving it**: Jaccard@50 = 0.923, address
   Spearman = 0.983, max cluster rank shift 22. Enough to answer the owner's question,
   little enough that `gap_score` still dominates (spread 1.66 vs 0.20).

**Ship it labelled `supply-revealed`,** with the disclaimer carrying three sentences, not
one: (i) this is where the New York market has historically put bar-type licences relative
to resident age, demand and residential sorting together; (ii) a low value is never evidence
that a neighbourhood does not deserve the service (the X6/D49 hazard); (iii) resident age is
a proxy for a bundle — young, renter, transit-rich, commercially active — and adds
essentially nothing once those are measured directly (§6), so it must never be read as an
isolated age effect. Same untruncated-render rule as `demand_caveat_text` (D49/D57).

**Do not** build it from `median_age` (sign reverses), from the all-on-premises count
(insignificant, and reverses at 800 m), or from the bar-POI count (insignificant in
Brooklyn, and its outcome is the same supply the screen already reads — the tightest version
of the D1 trap).

### 7.1 The concrete failure criterion

The column ships only while **all** of these hold on a re-run. Any one failing pulls it.

| # | test | current value | threshold |
|---|---|---|---|
| F1 | `gap_score`, `lead_category`, `n_missing`, `eligible` byte-identical with and without the annotation | — | exact |
| F2 | Brooklyn-only Conley-SE CI on the CH → EV contrast excludes 1.0 | [1.197, 1.763] | must exclude 1 |
| F3 | dispersion gate: p90−p10 > median MOE | 0.201 vs 0.056 (3.61×) | ratio > 1 |
| F4 | East Village `age_fit` − Carnegie Hill `age_fit` > each NTA's own MOE | 0.194 vs 0.084 / 0.072 | must exceed |
| F5 | placebo ordering: `bar` in the top 2 of 15 categories by b(w18), `pharmacy` in the bottom 2 | bar #1, pharmacy #15 | must hold |
| F6 | Jaccard @ top-50 clusters ∈ [0.80, 0.99] — moves something, does not rewrite the list | 0.923 | inside band |
| F7 | Moran's I of the residual reported, and the quoted CI is the Conley one, never HC3 | I = 0.415 | reported |

F2 is the one that binds: it is currently the *only* reason spec G is preferred over spec F,
and it is the test a future re-run on a new supply set or ACS vintage is most likely to fail.

### 7.2 Pinned tests, if it is built

1. `test_gap_set_unchanged` — the D57 proof re-run: identical row count and hash-sums of
   `gap_score`, `lead_category`, `n_missing`, `eligible` with and without the annotation.
2. `test_update_setlist_disjoint` — the D61 mechanical guarantee.
3. `test_east_village_beats_carnegie_hill` — `age_fit_bar(East Village) >
   age_fit_bar(UES–Carnegie Hill)` **and the difference exceeds each NTA's own MOE**
   (currently 0.194 > 0.084, 0.072). This is the owner's example, pinned with its
   uncertainty attached rather than as a bare inequality.
4. `test_gap_set_membership_unchanged` — the 67,223 bar-lead gap addresses and 82 clusters
   are identical before and after; only order changes.
5. `test_multiplier_is_positive_and_bounded` — `age_fit_bar ∈ (0.5, 2.0)` for every address,
   so `gap_score × age_fit` is monotone in `gap_score` and non-filtering by construction.
6. `test_dispersion_gate_is_derived` — the gate is recomputed from the run, not stored.
7. `test_coefficients_are_provenanced` — `age_fit_bar.yaml` carries `b18`, `b65`, their
   Conley SEs, the anchor mix, `n_tracts`, the outcome definition, the licence vocabulary
   version, `reach_hash`/`supply_hash` and `computed_on`; a test fails if the supply set or
   reach table has moved since the coefficients were fitted, because a supply-revealed
   coefficient is only valid against the supply set it was revealed from.
8. `test_bar_count_spec_not_used` — pins the *negative* finding: the module must not be
   wired to the bar-POI count outcome, so a future session cannot quietly swap in the
   specification that fails in Brooklyn without re-opening §6.1.

### 7.3 What this cannot do, and what would fix it

- It cannot say who is present at 10pm. There is no nighttime-population source in this
  project. **Fix:** LODES total employment (`hex_panel` currently carries only CNS07 and
  CNS18) or Safegraph-style dwell data would give a real daytime/nighttime control and would
  let the age coefficient be estimated net of it.
- It cannot separate demand from sorting. **Fix:** the multi-decade panel exists — fit
  `age_fit` on ACS 2013 and test whether it predicts the 2013 → 2023 *change* in bar supply
  better than 2013 bar supply itself does (a persistence baseline). If it does not beat
  persistence it is re-describing supply, and the D1 objection wins. That test is the single
  highest-value follow-up and every input for it is already in the warehouse.
- It cannot resolve MAUP. Tracts are the ACS grain, but a 400 m disc around a residential
  centroid is not a tract, and neither is a nightlife district. **Fix:** re-run at 200 m and
  600 m and confirm the coefficient is not a scale artifact — the 800 m collapse to 0.956
  already shows the effect is scale-dependent.
- It is estimated on one cross-section of a supply set that has moved twice this month
  (D52/D59). The coefficients are only valid against `supply_hash e2b7ef55e607`; test 7
  above is what enforces that.

---

## Appendix — artifacts

Scripts (scratchpad, not part of the package):
`build_panel.py` → `panel.py` → `analyze.py` / `nta.py` / `reg.py` / `reg2.py` /
`conley.py` / `mult.py` / `placebo.py` / `final.py` / `bk.py`, under
`/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor/e5f8e048-6e10-48a8-8f8f-a2e710bbc3c2/scratchpad/`.
Every number in this note is reproducible from the live DB opened `read_only=True`.
