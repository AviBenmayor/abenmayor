# Age-of-resident demand fit — design note

**Status:** DESIGN AND VERIFY ONLY. Nothing implemented. No file under `src/` or `tests/`
was touched. Source verified and captured; the model is specified and evaluated on the
live DB; the recommendation is **do not ship it for `bar`**.

**Date:** 2026-09-09
**Owner request (verbatim, 2026-09-09):** *"age should inform the score of a particular
business in a particular location. if we have a gap in a bar existing in upper east side
where avg age is 60+ vs. bar in east village where avg age is 25, the east village bar
should score higher."*

**One-line answer:** the published source says the opposite. On BLS CEX 2024, per-consumer-unit
alcohol spending *rises* with reference-person age to a peak at 45–54 and the under-25 band is
the **lowest**-spending adult band; the resulting multiplier scores the Upper East Side
**above** the East Village on every normalization of the mapped line item. A different,
narrower line item (`Alcoholic beverages at restaurants, taverns`) gets the owner's sign but
only by 6–9%, which is inside the ACS margin of error. Meanwhile the same machinery produces a
large, correctly-signed, MOE-clearing effect for **pharmacy** and **childcare**. The
recommendation is therefore to build the multiplier, gate it on a derived dispersion test,
and let `bar` fail that gate — rather than tune the source until `bar` passes.

---

## 1. Source verification

### 1.1 What was fetched, and how

Plain `curl` and `urllib` against `www.bls.gov` return **HTTP 403** from this network, exactly
as `spend.yaml`'s provenance header records. Two things were established:

| Attempt | Result |
|---|---|
| `https://www.bls.gov/cex/tables/calendar-year/mean-item-share-average-standard-error/cu-age-2024.xlsx` | **404** with any User-Agent — the URL in the task brief does not exist |
| `www.bls.gov/...` any path, default UA | **403** (edge block, reproduces the D-note) |
| `download.bls.gov/pub/time.series/cx/*`, default UA | **403** |
| **`download.bls.gov/pub/time.series/cx/*` with a User-Agent carrying a contact address** | **200 — works** |
| `api.bls.gov/publicAPI/v2/timeseries/data/<series>` | **200 — works, no key needed** |

The unblocking fact is BLS's documented requirement that automated clients send a
User-Agent containing a contact email. `User-Agent: loci-research/1.0 (avibenmayor@gmail.com)`
returns 200 on the whole `download.bls.gov` tree. **This is a reusable finding for the
project: the BLS edge is not blocking us, it is refusing anonymous clients.**

### 1.2 What was used instead of the xlsx — and why it is better

Rather than the Table 1300 workbook, this note uses the **CEX LABSTAT time-series flat files**,
`https://download.bls.gov/pub/time.series/cx/`. These are the same published estimates that
populate the calendar-year tables, in machine-readable form, with standard errors attached:

- `cx.data.1.AllData` (115 MB) — the estimates
- `cx.aspect` (705 MB) — per-series **standard error**, relative standard error, expenditure
  share, aggregate expenditure
- `cx.series`, `cx.item`, `cx.demographics`, `cx.characteristics` — the lookups

Series key: `CXU` + *item_code* + *demographics_code* + *characteristics_code* + `M`.
`cx.demographics` code **`LB04` = "Age of reference person"**, and `cx.characteristics` gives
the seven published bands plus rollups — **exactly the Table 1300 stub**:

```
LB04 01  All Consumer Units          LB04 06  Reference person from age 55 to 64
LB04 02  Reference person under age 25   LB04 07  Reference person age 65 or over
LB04 03  Reference person from age 25 to 34  LB04 08  Reference person from age 65 to 74
LB04 04  Reference person from age 35 to 44  LB04 09  Reference person age 75 or over
LB04 05  Reference person from age 45 to 54
```

The `cx.aspect` aspect-type codes are undocumented in the flat files; they were **verified
against the API**, which returns the same aspects with labels:

```
GET api.bls.gov/publicAPI/v2/timeseries/data/CXUALCBEVGLB0405M?aspects=true
  → value 838, "Standard Error" 65.45, "Expenditure Share" 0.8,
    "Relative Standard Error" 7.81, "Aggregate Expenditure (in millions)" 18426
```

so `E` = standard error, `ES` = expenditure share (%), `R0` = RSE, `AG`/`AS` = aggregate.

### 1.3 Provenance cross-check against `spend.yaml` — passes exactly

The all-consumer-units column of every line item reproduces `spend.yaml`'s
`annual_spend_national` **to the dollar**:

| Line item | this extract, All CU 2024 | `spend.yaml` national |
|---|---|---|
| Food at home | 6,224 | 6,224 |
| Food away from home | 3,945 | 3,945 |
| Alcoholic beverages | 643 | 643 |
| Drugs | 658 | 658 |
| Other apparel products and services | 252 | 252 |
| Personal care products and services | 978 | 978 |
| Fees and admissions | 935 | 935 |
| Miscellaneous household equipment | 1,089 | 1,089 |

This is the identity check that matters: the age table and the income table are **the same
publication cut two ways**, so the age multiplier and `E_c(income)` are commensurable and no
new source is being introduced.

### 1.4 Artifacts written

- `data/raw/bls/table1300_2024_national.csv` — 108 rows, one per (item × 9 age bands):
  `item_code, item_text, age_band, series_id, mean_2024, standard_error,
  relative_standard_error, expenditure_share_pct`
- `data/raw/bls/cx_lb04_2024_raw.tsv` — the **verbatim** `cx.data` and `cx.aspect` lines
  behind every number above, so the parse can be re-checked without re-downloading 820 MB.

> **Correction to `spend.yaml` found on the way.** `spend.yaml`'s `bar` entry states *"CEX
> does not publish an at-home/away-from-home split for alcohol"* and therefore carries a
> 65.3% away-from-home share as an admitted unsourced assumption. **That is not true.**
> Item `790420`, *"Alcoholic beverages at restaurants, taverns"*, is published (2022–2024),
> All-CU 2024 = **$279**, i.e. a 43.4% away-from-home share, not 65.3%. Also published:
> `200511`–`200536` (beer/wine/spirits at fast-food, full-service, vending, catered) and
> `200900` (purchased on trips). This is a real, sourced correction to a documented free
> parameter and should be ticketed on its own — but it belongs to the *fair-value* engine,
> not to this design; changing `annual_spend` would move `E_c(income)`, which is out of
> scope here.

---

## 2. Crosswalk

Mappings are taken **verbatim from `spend.yaml`'s `cex_mapping`**, not re-derived. Allocation
constants (restaurant 0.75, cafe 0.15, hair 0.35, nails 0.25, bar 0.653) are **irrelevant to
this model** — a category's age profile is normalized by the citywide mix of the *same* profile,
so any scalar multiple cancels. That has a consequence stated plainly below.

| Loci category | CEX item | code | `spend.yaml` basis | note |
|---|---|---|---|---|
| grocery | Food at home | `FOODHOME` | Table 1101/3004 | clean |
| convenience | Food at home | `FOODHOME` | *blend, not a CEX line* | **shape proxy only**; `spend.yaml` calls this its weakest anchor |
| pharmacy | Drugs | `DRUGS` | Table 1101 | clean 1:1 |
| laundry | Other apparel products and services | `OTHAPPRL` | Table 1101 | shared line |
| tailor_repair | Other apparel products and services | `OTHAPPRL` | Table 1101 | shared line |
| hair_barber | Personal care products and services | `PERSCARE` | Table 1101/3004 | shared line |
| nails_beauty | Personal care products and services | `PERSCARE` | Table 1101/3004 | shared line |
| restaurant | Food away from home | `FOODAWAY` | Table 1101/3004 | shared line |
| cafe_bakery | Food away from home | `FOODAWAY` | Table 1101/3004 | shared line |
| bar | Alcoholic beverages | `ALCBEVG` | Table 1101/3004 | shared/total line |
| *(bar, sensitivity)* | *Alcoholic beverages at restaurants, taverns* | `790420` | **not in `spend.yaml`** | see §1.4 |
| childcare | Babysitting, childcare, daycare, preschool | `670320` | `national_unverified` | `spend.yaml` names `670310`, which has **no age series**; `670320` is the 2023+ successor line and does |
| fitness | Fees and admissions | `FEESADM` | Table 1101 | broader than gyms |
| hardware | Miscellaneous household equipment | `MISCHHEQ` | Table 1101 | much broader |
| **clinic** | — | — | insurance reimbursement, no household analogue | **excluded** (also D30) |
| **bank** | — | — | net interest margin, no household analogue | **excluded** |

**Consequence the note must state up front: 13 annotatable categories have only 7 distinct
age profiles.** `restaurant ≡ cafe_bakery`, `hair_barber ≡ nails_beauty`,
`laundry ≡ tailor_repair`, `grocery ≡ convenience`. The multiplier **cannot resolve** a cafe
from a restaurant, a nail salon from a barber, or a laundromat from a tailor. It resolves
*food-away-from-home vs drugs vs childcare*, nothing finer.

### 2.1 Band collapse

Seven CEX bands → the three adult ACS bands the address table carries, weighted within each
collapsed band by CEX's own published consumer-unit counts (`CONSUNIT`, thousands, 2024):

```
18_34  = <25 (6,700) + 25–34 (20,340)                        CU weight 19.9%
35_64  = 35–44 (24,275) + 45–54 (22,165) + 55–64 (23,911)    CU weight 51.8%
65_plus= 65–74 (22,577) + 75+ (15,792)                       CU weight 28.3%
```
(65+ uses the two sub-bands, not the `LB04 07` rollup, so the weighting is uniform.)

**Under-18 residents are excluded from the mix and the three adult shares are renormalized
over adults** (`w_b = share_b / (1 − under_18_share)`). Justification: CEX's unit is the
consumer unit and its age axis is the *reference person*, who is by construction an adult.
Children's consumption is already inside their household's per-CU figure; counting them as
their own band would double-count it.

---

## 3. The multiplier

### 3.1 Form

For category *c* at address *a*:

```
age_fit_c(a) = [ Σ_b  w_b(a) · σ_{c,b} ]  /  [ Σ_b  w_b(city) · σ_{c,b} ]
```

- `w_b(a)` — adult age-band share at *a*, tract-direct from `analysis.address_demographics`
  (ACS 2023 5-yr), renormalized over adults. `w_35_64` is the residual.
- `w_b(city)` — the same, unit-weighted (`units_capped`, D39 cap) over all addresses. Defines
  the 1.0 anchor.
- `σ_{c,b}` — see §3.2.

1.0 at the citywide adult mix, >1 where the local mix leans toward bands that spend more on *c*.

### 3.2 Choice of `σ` — budget share, not dollars. This is the load-bearing decision.

Three candidates, all one-source, all computable from the same extract:

| | definition | what it measures |
|---|---|---|
| **per-CU dollars** | CEX mean spend, band *b* | age effect **plus** the income and household-size effect |
| **per-capita dollars** | ÷ persons per CU (`980010`) | age effect plus income, household-size partly removed |
| **budget share** ✅ | 100 × spend ÷ `TOTALEXP`, band *b* | age effect **net of spending capacity** |

Reject per-CU dollars. CEX total average annual expenditure runs **$47,283 (<25) → $100,327
(45–54) → $55,834 (75+)**, and reference-person income runs $48,514 → $141,121 → $56,028. A
per-CU dollar profile is therefore *mostly an income profile wearing an age label* — which is
the same failure mode D49 named ("a free variable wearing a citation"), and it would
double-count income against `spend.yaml`'s `E_c(income)`. Budget share divides that out with
one published number and no free parameter.

**Recommended:** `σ_{c,b} = 100 × mean_spend(c,b) / TOTALEXP(b)`, CU-weighted within the
collapsed band.

Collapsed profiles (budget share, % of total expenditure):

| category | 18–34 | 35–64 | 65+ | range `D_c` |
|---|---|---|---|---|
| grocery / convenience | 8.0 | 7.7 | 8.5 | 1.11 |
| pharmacy | 0.4 | 0.7 | **1.5** | **3.93** |
| laundry / tailor_repair | 0.4 | 0.3 | 0.3 | 1.35 |
| hair_barber / nails_beauty | 1.2 | 1.2 | 1.3 | 1.05 |
| restaurant / cafe_bakery | 5.5 | 5.1 | 4.4 | 1.27 |
| **bar (`ALCBEVG`)** | **0.8** | **0.8** | **0.9** | **1.07** |
| *bar (`790420` tavern)* | *0.4* | *0.4* | *0.3* | *1.51* |
| childcare | 1.0 | 0.7 | 0.0 | **32.97** |
| fitness | 1.0 | 1.3 | 1.0 | 1.36 |
| hardware | 1.4 | 1.3 | 1.6 | 1.18 |

### 3.3 MOE propagation

`w_18_34` and `w_65_plus` carry `age_*_share_moe / (1 − under_18_share)`. The residual
`w_35_64` carries `RSS(under_18_share_moe, age_18_34_share_moe, age_65_plus_share_moe) /
(1 − under_18_share)` — the residual inherits every component's error, which is why it is the
noisiest band. The renormalizing denominator is treated as fixed (a second-order term; state
it, don't hide it).

```
age_fit_moe_c(a) = sqrt( Σ_b ( moe_w_b(a) · σ_{c,b} )² )  /  Σ_b w_b(city) · σ_{c,b}
```

The denominator is a citywide constant estimated from ~767k addresses; its own MOE is
negligible and is deliberately not propagated (documented, not forgotten).

### 3.4 Where it goes — and where it must not

Per the house rules and D39/D48/D57:

- `gap_score`, `lead_category`, `n_missing`, `eligible`, `ratio`, `nearest_m` — **unchanged**.
  The gap set is not filtered, reordered, or re-derived.
- New columns on `analysis.address_category` (D57/D61 pattern: written by `UPDATE`, SET-list
  disjoint from the screen's own columns): `age_fit`, `age_fit_moe`, `age_fit_source`.
- New columns on `analysis.address`: `age_fit_lead`, `age_fit_lead_moe`.
- New **ranking** column, never a gate: `gap_score_fit = gap_score × age_fit_lead`.
  Monotone in `gap_score` for fixed address, non-filtering by construction (`age_fit > 0`
  always), and the un-multiplied `gap_score` stays alongside it.

### 3.5 Should it fold in `E_c(income)`? **No.** One recommendation, one reason each.

1. **Double-counting.** With budget-share `σ` the income gradient is already divided out; with
   dollar `σ` it is *in* `age_fit`. Either way, multiplying by `E_c(income)` too counts income
   once or twice more.
2. **D49 forbids it.** The income annotation "must never feed a rank." `E_c(income)` is built
   on the same ACS median household income and the same MOE problem (D57: 45.6% of rows are
   income-indeterminate). Folding it into a ranking column launders the annotation into a rank
   through the back door, and drags the X6 disclaimer into a number that has no room to carry it.

Keep `age_fit` a pure age factor. If income is ever to enter a rank, it enters once, explicitly,
under its own decision, with its own disclaimer.

---

## 4. The owner's example, computed on the live DB

`analysis.address` ⋈ `analysis.address_demographics`, 767,326 addresses with age data
(11 NULL, never dropped), unit-weighted by `units_capped`.

### 4.1 The age contrast is real and large

| NTA | addrs | under-18 | **w 18–34** | **w 35–64** | **w 65+** |
|---|---|---|---|---|---|
| East Village | 1,927 | 5.8% | **0.486** | 0.344 | **0.170** |
| UES–Carnegie Hill | 2,251 | 16.0% | **0.212** | 0.437 | **0.351** |
| UES–Yorkville | 1,330 | 10.5% | 0.307 | 0.449 | 0.244 |
| UES–Lenox Hill–Roosevelt Is. | 1,221 | 15.3% | 0.350 | 0.423 | 0.227 |
| citywide (unit-wtd) | 767,326 | — | 0.316 | 0.478 | 0.206 |

The East Village is **2.3× more 18–34** and **half as 65+** as Carnegie Hill. If a resident-age
multiplier were going to move anything, this is the pair where it would.

### 4.2 `age_fit` — the result

Unit-weighted mean per NTA; `±` is the unit-weighted mean per-address MOE.

| category | norm | East Village | UES–Carnegie Hill | UES–Yorkville | UES–Lenox Hill | city p10 / p50 / p90 |
|---|---|---|---|---|---|---|
| **bar** (`ALCBEVG`) | per-CU | 0.959 ±0.168 | **0.984** ±0.149 | 0.988 | 0.982 | 0.978 / 1.006 / 1.030 |
| **bar** | per-capita | 0.969 ±0.162 | **1.036** ±0.147 | 1.011 | 0.999 | 0.980 / 1.007 / 1.034 |
| **bar** | **share** | 0.999 ±0.163 | **1.010** ±0.143 | 1.004 | 1.002 | 0.994 / 1.000 / 1.008 |
| *bar (tavern `790420`)* | per-CU | *0.987* ±0.173 | *0.932* ±0.149 | 0.971 | 0.978 | 0.951 / 1.000 / 1.042 |
| *bar (tavern)* | **share** | **1.033** ±0.169 | **0.948** ±0.141 | 0.983 | 0.998 | 0.955 / 0.993 / 1.028 |
| **pharmacy** | per-CU | **0.869** ±0.168 | **1.134** ±0.164 | 1.037 | 0.990 | 0.923 / 1.031 / 1.128 |
| **pharmacy** | **share** | **0.892** ±0.163 | **1.195** ±0.166 | 1.065 | 1.013 | 0.897 / 1.024 / 1.165 |
| restaurant / cafe | share | 1.018 | 0.969 | 0.990 | 0.998 | 0.974 / 0.996 / 1.017 |
| fitness | share | 0.958 | 0.988 | 0.990 | 0.983 | 0.980 / 1.007 / 1.030 |
| childcare | share | **1.104** ±0.193 | **0.798** ±0.151 | 0.931 | 0.983 | 0.832 / 0.978 / 1.105 |
| grocery / convenience | share | 1.003 | 1.013 | 1.005 | 1.004 | 0.992 / 1.000 / 1.009 |
| hair / nails | share | 0.994 | 1.007 | 1.002 | 1.000 | 0.996 / 1.001 / 1.006 |
| laundry / tailor | share | 1.030 | 0.963 | 0.989 | 1.001 | 0.966 / 0.993 / 1.021 |
| hardware | share | 1.001 | 1.022 | 1.009 | 1.006 | 0.987 / 1.000 / 1.016 |

MN+BK p10/p90 tracks citywide within ±0.01 for every row (bar share 0.994/1.008;
pharmacy share 0.863/1.158).

### 4.3 Reading it honestly

**The bar half of the owner's example fails, with the sign reversed.** On the line item
`spend.yaml` maps `bar` to, the Upper East Side scores **higher** than the East Village:
0.984 vs 0.959 (per-CU), 1.036 vs 0.969 (per-capita), 1.010 vs 0.999 (share). The cause is
not a bug, it is what BLS published. Per-consumer-unit alcohol spending by reference-person
age, 2024:

```
<25    25–34   35–44   45–54   55–64   65–74   75+     All CU
$382   $600    $727    $838    $657    $610    $422    $643
```

**The under-25 band is the lowest-spending adult band on alcohol, and the peak is 45–54.**
The tavern-only line `790420` has the same shape ($197 / $312 / $357 / **$396** / $254 / $182
/ $154). Only after dividing out total expenditure does the 18–34 band come out ahead, and
then only by 9%: EV 1.033 vs Carnegie Hill 0.948 — against a per-address MOE of ±0.14–0.17.
**The effect is a fifth of its own margin of error.**

**The pharmacy half works, strongly and in the right direction.** Carnegie Hill 1.195 vs East
Village 0.892 — a 34% spread on a genuinely steep gradient ($169 at <25 → $959 at 75+, a 5.7×
range). Childcare is comparable (1.104 vs 0.798).

**And the decisive fact about the example itself: neither neighbourhood has a bar gap.**

| NTA | median bar `nearest_m` | median `ratio` (reach 400 m) | addrs with ratio>1 | **bar-lead gaps** |
|---|---|---|---|---|
| East Village | **13 m** | 0.034 | 2 | **0** |
| UES–Carnegie Hill | **90 m** | 0.224 | 0 | **0** |
| UES–Yorkville | 80 m | 0.200 | 18 | 3 |
| UES–Lenox Hill–Roosevelt Is. | 89 m | 0.223 | 18 | 9 |

The screen already answers the owner's question, and answers it better than any multiplier
could: the median East Village address is **13 metres** from a bar and the median Carnegie
Hill address is 90 m — a 7× difference in revealed supply, both far inside the 400 m reach.
There is no bar gap in either place to re-rank. `nearest_m` and `ratio` carry the "the East
Village is where the bars are" signal directly, at address grain, with no demographic
inference at all.

### 4.4 How much does the ranking actually move?

MN+BK, `eligible ∧ gap_score > 1 ∧ lead_category = 'bar'` → **67,223 addresses in 82 clusters**
(none in Manhattan's East Village or the UES; the set is outer Brooklyn and East Harlem).
Cluster score = unit-weighted mean.

| `σ` used | **Jaccard @ top-50 clusters** | @25 | @100 | rank corr | max rank shift |
|---|---|---|---|---|---|
| `ALCBEVG` per-CU | **0.923** | 0.923 | 1.000 | 0.988 | 8 |
| `ALCBEVG` share | **1.000** | 1.000 | 1.000 | 0.999 | 3 |
| tavern `790420` per-CU | **0.961** | 0.923 | 1.000 | 0.980 | 12 |
| tavern `790420` share | **0.961** | 0.852 | 1.000 | 0.985 | 13 |

Address-level (67,223 rows), `ALCBEVG` share: Jaccard@100 = 0.905, @500 = 0.969, @1000 = 0.972,
Spearman = **0.9999**. Tavern share: @100 = 0.786, Spearman = 0.997.

Other lead categories move less or not at all: pharmacy (170 addrs, 2 clusters), fitness (136,
2), restaurant (100, 2) — all Jaccard 1.000. Childcare (2,498 addrs, 11 clusters) Jaccard 1.000,
rank corr 0.69.

**Interpretation.** `gap_score` in the MN+BK gap set spans p10 1.09 → p90 2.50, a spread of
**1.41**. `age_fit` for `bar` spans p10 0.994 → p90 1.008, a spread of **0.014** — one
hundredth of the quantity it multiplies. A rounding error cannot reorder a ranking, and it
doesn't: the top-50 is identical.

---

## 5. The dispersion gate — how to decide *per category*, without a prior

The whole result above collapses to one number per category. Define, entirely from published
data:

```
spread_c = p90(age_fit_c) − p10(age_fit_c)     over all addresses
moe_c    = median(age_fit_moe_c)
gate_c   = spread_c > moe_c
```

The multiplier is shown only where the signal it carries exceeds the ACS noise it is built
from. No owner judgement, one derived number, re-computable on every run.

| category | `D_c` | p10 | p90 | spread | median MOE | ratio | **gate** |
|---|---|---|---|---|---|---|---|
| childcare | 32.97 | 0.832 | 1.105 | 0.273 | 0.154 | 1.78 | **PASS** |
| pharmacy | 3.93 | 0.897 | 1.165 | 0.267 | 0.151 | 1.77 | **PASS** |
| *bar (tavern)* | 1.51 | 0.955 | 1.028 | 0.073 | 0.141 | 0.52 | fail |
| laundry / tailor | 1.35 | 0.966 | 1.021 | 0.055 | 0.140 | 0.39 | fail |
| fitness | 1.36 | 0.980 | 1.030 | 0.050 | 0.149 | 0.34 | fail |
| restaurant / cafe | 1.27 | 0.974 | 1.017 | 0.043 | 0.141 | 0.30 | fail |
| hardware | 1.18 | 0.987 | 1.016 | 0.029 | 0.140 | 0.21 | fail |
| grocery / convenience | 1.11 | 0.992 | 1.009 | 0.017 | 0.140 | 0.12 | fail |
| **bar (`ALCBEVG`)** | **1.07** | 0.994 | 1.008 | **0.013** | 0.140 | **0.10** | **fail** |
| hair / nails | 1.05 | 0.996 | 1.006 | 0.010 | 0.141 | 0.07 | fail |

**Two of thirteen categories pass, and `bar` fails by a factor of ten.** Note even the passers
clear only by ~1.8×; this is a weak effect everywhere, and the note must not oversell pharmacy
either.

---

## 6. What this multiplier can and cannot claim (X6 disclaimer logic)

**Can claim:** that the *resident* age composition within an address's tract differs from the
city's, and that BLS's national household budget survey shows the age bands over-represented
there devote a different share of their spending to this category. That is a statement about
published national budget shares crossed with local resident composition. Nothing more.

**Cannot claim:** (a) that anyone actually present at this location has that age; (b) that
demand is absent — the D49/X6 hazard applies here too: a low `age_fit` in a category is a
statement about the resident mix, never evidence that a neighbourhood does not deserve the
service; (c) that a category is differentiated from the categories sharing its CEX line;
(d) causality in either direction (see §7.2).

Age is less fraught than income or race, but it is not neutral: `age_fit < 1` for pharmacy in
a young, low-income neighbourhood, or `age_fit < 1` for childcare in a neighbourhood where
families were priced out, both restate a displacement outcome as a demand fact. The rendered
text must carry the same untruncated-disclaimer rule as `demand_caveat_text` (D49/D57).

---

## 7. Red team

### 7.1 Resident age vs who is actually there at night
Bars serve non-residents; a bar's catchment at 10pm is a subway map, not a tract. The East
Village's bar trade is regional. `age_fit` is built entirely on `analysis.address_demographics`,
i.e. **where people sleep**, and applies it to a category whose demand is maximally mobile.
`hex_panel` carries LODES daytime jobs, which fixes the lunch problem, not the night problem —
there is no nighttime-population source in this project. **Test that would settle it:** join the
NYS SLA alcohol overlay (already ingested) to resident 18–34 share at tract level and regress
licence density on resident-young share *controlling for subway-station proximity and
LODES jobs*; if resident age adds nothing once transit is in, the multiplier is measuring
accessibility, not demand. Cheap — every input is already in the DB.

### 7.2 Endogeneity — the multiplier partly re-scores existing supply
Young renters sort into neighbourhoods that already have bars; the causal arrow runs from
amenities to residents at least as strongly as the reverse (Zukin 2009; the project's own
H-L6). So a high `age_fit` for `bar` is partly a *lagged read of the bars that are already
there* — which is precisely the rejected D1 thesis (retail as a growth predictor) re-entering
through a demographic side door. The gap screen is supposed to find *latent* demand; a factor
that scores highest where the amenity already exists inverts that. **Test:** compute `age_fit`
from ACS 2013 5-yr and check whether it predicts 2013→2023 *change* in bar supply better than
2013 bar supply itself does (persistence baseline). If it does not beat persistence, it is
re-describing supply. Requires the multi-decade panel, which exists.

### 7.3 Collinearity with density, income and Manhattan
The 18–34 share is correlated with renter share, one-person households, income, and simply
being in Manhattan below 96th. `age_fit` may be a low-resolution Manhattan indicator. The
data here already hints at it: the MN+BK p10/p90 is within 0.01 of citywide for every category
— the multiplier barely distinguishes MN+BK from the outer boroughs, which is the opposite of
what a real neighbourhood-type signal would do. **Test:** regress `age_fit_bar` on
`renter_share`, `one_person_hh_share`, `median_hh_income` and a borough dummy; report partial
R². If R² > 0.8, drop the column and use the covariates directly rather than through a
CEX-flavoured wrapper.

### 7.4 ACS margin of error
The median per-address `age_fit_moe` is **±0.14–0.19** across every category, against a total
citywide p10–p90 spread of 0.013 (bar) to 0.27 (pharmacy). For `bar`, essentially **every
address's `age_fit` is statistically indistinguishable from 1.0**. This is the same fact that
retired the binary income badge in D49 (median income MOE 25.7% of estimate, 53% of addresses
within one MOE of the threshold), reproduced on the age axis. It is also why §5's gate is a
requirement and not a nicety. The MOEs shown are *per-address*; averaging within an NTA does
not shrink them by √n, because tract MOEs are spatially correlated and addresses within a
tract share one estimate exactly.

### 7.5 Does the 3-band collapse lose the signal?
The brief hypothesised that it would, because "the CEX <25 band is the alcohol peak."
**It is not — it is the alcohol minimum** ($382 vs $838 at 45–54), so collapsing <25 into
18–34 *raises* the young band rather than diluting a peak. The collapse costs little here:
the un-collapsed 7-band range for `ALCBEVG` is 2.19× (382→838), and the CU-weighted 3-band
range is 1.35× (546→738) in dollars, 1.07× in budget share. The loss is real but it is not
what makes `bar` fail — `bar` fails because the budget-share profile is flat by age at any
resolution. **Test:** rebuild `σ` on the 7 raw bands against a 7-band ACS age table
(B01001 supports it, one extra Census pull) and re-run §5. If `bar`'s ratio stays below 1.0,
the collapse is exonerated and the category is simply not age-sensitive.

### 7.6 CEX unit mismatch (found while designing; the biggest structural flaw)
CEX's axis is the **reference person** — one adult per household. The ACS shares in
`address_demographics` are **person** shares, counting every adult. Multiplying a person-share
by a per-consumer-unit dollar figure is dimensionally inconsistent: it implicitly assumes a
household's spending is attributable to each of its adults at their own age. That is why §3.2's
budget-share normalization matters twice over — a ratio of shares is at least unit-free.
**Fix if this is ever built:** pull ACS **B25007** (tenure by *age of householder*) and use
householder-age shares, which are the direct ACS analogue of the CEX reference person. One
Census call, and it removes the mismatch rather than papering over it.

---

## 8. Recommendation

**Do not ship a `bar` age multiplier.** The requested behaviour is not supported by the source
the project's house rules require, the effect has the wrong sign on the mapped line item, the
right sign only on a sensitivity line and then at a fifth of its own MOE, it moves the top-50
bar-gap clusters by a Jaccard of 0.92–1.00, and the two neighbourhoods in the owner's example
have no bar gap in the first place — the screen's own `nearest_m` (13 m vs 90 m) already
carries the answer more directly than any demographic inference.

**What to build instead, if anything:** `age_fit` as specified, budget-share normalized,
computed for all 13 annotatable categories, **displayed only where §5's dispersion gate
passes** — currently pharmacy and childcare. This satisfies the owner's actual principle
("age should inform the score of a particular business in a particular location") in the two
places the evidence supports it, and refuses it where the evidence doesn't, on a derived
number rather than a judgement call.

### Single recommended formula

```
σ_{c,b} = 100 · CEX_mean_spend(item(c), b) / CEX_total_expenditure(b)          # budget share
          collapsed 7→3 CEX bands, weighted by CONSUNIT

w_b(a)  = ACS_age_share_b(a) / (1 − under_18_share(a))                        # adult mix

age_fit_c(a)     = Σ_b w_b(a)·σ_{c,b}  /  Σ_b w_b(city)·σ_{c,b}
age_fit_moe_c(a) = sqrt( Σ_b (moe_w_b(a)·σ_{c,b})² ) / Σ_b w_b(city)·σ_{c,b}

gap_score_fit(a) = gap_score(a) × age_fit_{lead_category(a)}(a)
                   — shown only if  gate_{lead_category(a)}  is true, else = gap_score
```

No `E_c(income)` term (§3.5).

### Implementation plan

**Files to touch (none touched here):**

| File | Change |
|---|---|
| `src/loci/age_fit.yaml` *(new, package data)* | crosswalk `category → CEX item_code`, the 3×13 `σ` table with standard errors, `computed_on`, source URLs, the two excluded categories with reasons |
| `src/loci/model/address_age_fit.py` *(new)* | mirrors `address_demand.py` exactly: opens `address_gaps`/`address` read-only, writes to `address_category` by **`UPDATE` only**, keyed on `(reach_hash, supply_hash)` |
| `src/loci/sql/002_schema.sql` | `age_fit`, `age_fit_moe`, `age_fit_gated` on `address_category`; `age_fit_lead`, `age_fit_lead_moe`, `gap_score_fit` on `address` |
| `src/loci/cli.py` | `loci address-age-fit [--borough MNBK] [--dry-run]` |
| `src/loci/sources/bls/cex_age.py` *(new)* | fetcher pinned to the contact-UA requirement (§1.1), writes `data/raw/bls/` |
| `docs/CHECKPOINT.md` | decision entry: source, the reversed-sign finding, the gate, and that `bar` fails it |

**Do not touch:** `model/address_gaps.py`, `reach_tiers.yaml`, `model/gaps.py` (frozen, D61).

**Tests to pin:**

1. `test_gap_set_unchanged` — build with and without the age annotation; assert identical
   `address_gaps` row count and identical hash-sums of `gap_score`, `lead_category`,
   `n_missing`, `eligible` (the D57 proof, re-run).
2. `test_update_setlist_disjoint` — the module's SET-list is disjoint from the screen's own
   columns (the D61 mechanical guarantee).
3. `test_pharmacy_age_ordering` — `age_fit(pharmacy, UES-Carnegie Hill) > age_fit(pharmacy,
   East Village)`, both > 0, spread > 0.20. **This is the owner's example in the direction the
   data supports.**
4. `test_bar_age_ordering_is_null` — pin the *negative* result: `|age_fit(bar, EV) −
   age_fit(bar, UES-CH)| < median age_fit_moe`. The test exists so a future session cannot
   quietly re-introduce a bar multiplier without re-opening this note.
5. `test_moe_present` — every non-NULL `age_fit` has a non-NULL `age_fit_moe`; the residual
   band's MOE is the RSS of the other three.
6. `test_shared_line_categories_identical` — `restaurant == cafe_bakery`,
   `hair_barber == nails_beauty`, `laundry == tailor_repair`, `grocery == convenience`,
   to the float. Pins the §2 limitation as a fact, not a footnote.
7. `test_age_fit_drift` — every category in `categories.yaml` either has a Table 1300 line in
   `age_fit.yaml` or an explicit `excluded: <reason>`; the `σ` table's All-CU column still
   reproduces `spend.yaml`'s `annual_spend_national` to the dollar (§1.3), which is the
   cross-file check that catches a silently re-vintaged CEX pull.
8. `test_gate_is_derived` — the gate is recomputed from the run, not stored as a constant; a
   category's `age_fit_gated` flips iff `spread > median MOE`.
