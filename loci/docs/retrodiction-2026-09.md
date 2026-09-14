# Retrodiction — does the screen's score at opening predict what happened next?

**2026-09-14 · GTM-158 (Urgent) · QUESTIONS T11 · gates D87**
Run: `loci retrodiction run` → `data/retrodiction/summary.json`, rendered by
`loci retrodiction report`. Code: `src/loci/validation/retrodiction.py`.
Tests: `tests/test_retrodiction.py`.

---

## 1. The question, and why it gates the GTM memo

`docs/GTM.md` (D87) claims Loci lowers an operator's **cost of search**. The
contrarian red-team refused to let it claim **decision value** until one attack
was answered:

> *"Loci measures supply thinness, not site quality — an address with no
> competitors may have none because the market said no."*

That is D1's reverse-causality error wearing a new costume. The test: take
storefronts that opened at a **known date**, score them with the screen **as it
would have read on that date**, and look at what happened.

Two things could be true and both would sink the claim. Either the score has no
relationship to outcomes, or it has one **with the wrong sign** — high-gap sites
doing worse, because the gap was the market's verdict rather than an opening.

---

## 2. Design, written before the run

**Cohort.** `analysis.poi_presence` rows with
`first_seen_kind ∈ (source_date, gov_filing)` and `first_seen_src_date` in
2023-01-01 … 2024-12-31, Manhattan + Brooklyn (D78).

**Score at *t*.** Per address × category, rebuild supply from the ledger as of
t₀ = 2023-01-01: a location counts when `first_seen_src_date ≤ t₀` **or**
`first_seen_kind = 'backfill_censored'` (D79's 40% with no date at all). From
that: `supply_per_1k` → `supply_ratio_t0` against the sample's own per-category
median, plus an **own-category-gap flag** (zero same-category competitors within
400 m at t₀), plus homes, jobs, transit entries and `retail_index` (D82).

**Outcome, as designed.** Survival: still open at the 2026-09 snapshot vs closed,
with Kaplan-Meier at 12/24 months by score tercile and a Cox model with category
fixed effects clustered on NTA, because exposure differs (a 2023-01 opening has
44 months, a 2024-12 opening 21).

**Failure criterion, fixed in advance.** Fewer than **48** observable closures
and no hazard model is fitted at all — Schoenfeld,
`(z₀.₉₇₅ + z₀.₈)² / ln(1.5)² = 47.7` events for 80% power against HR 1.5 per SD.
For the entry test: the score must clear a homes-only baseline **and** the 95th
percentile of a within-category permutation null, out of sample, or it adds
nothing.

**Distance.** Straight-line 400 m in EPSG:32618 for every measure in this
memo — supply, homes, baseline and outcome radius alike. The persisted Dijkstra
artefacts hold nearest-distance for one frozen supply set and cannot be replayed
at a historical date. D85's rule (never compare a network measure to a
straight-line one) is respected by never mixing: **nothing here is comparable to
`analysis.address_category.supply_ratio_vs_base`.**

---

## 3. The cohort

**12,572 dated openings** in MN+BK, **10,274** of them in the principled supply
set (D52/D59). **81.5% are restaurant, café or bar.**

| category | in cohort | dated share of category | censored (no date at all) |
|---|---|---|---|
| restaurant | 6,986 | 67% | 13,131 |
| cafe_bakery | 2,129 | 79% | 2,098 |
| bar | 1,134 | 76% | 1,793 |
| nails_beauty | 981 | 57% | 4,250 |
| hair_barber | 386 | 64% | 2,253 |
| fitness | 290 | 58% | 2,004 |
| grocery | 201 | 41% | 3,602 |
| convenience | 107 | 48% | 1,468 |
| clinic | 103 | 59% | 1,405 |
| pharmacy | 100 | 76% | 684 |
| laundry | 47 | 42% | 2,092 |
| bank | 32 | 45% | 1,057 |
| tailor_repair | 30 | 59% | 242 |
| childcare | 29 | 24% | 1,950 |
| hardware | 17 | 58% | 448 |

By source of the date: `storefront_pipeline.opened_on` (D80 government filings)
7,026 · Foursquare `date_created` 4,501 · DCWP `license_issue_date` 979 ·
Medicaid `enrollment_begin_date` 66.

**The selection, stated plainly.** Only businesses that must announce themselves
to somebody get a date. A restaurant is inspected by DOHMH, licensed by DCWP and
indexed by Foursquare; a hardware store declares nothing to anyone. So the
cohort is food, and every result below is a food result with a thin tail. The
17 dated hardware openings are not a sample of hardware openings.

**And `first_seen_src_date` is not an opening date.** For the Foursquare rows it
is when Foursquare minted the record. For the `gov_filing` rows it is a licence
or first inspection, which D80 measures at a 221–259 day lead from fitout. This
is non-classical measurement error in the timing variable and it is the largest
single caveat on the cohort.

---

## 4. Closures: which survival outcome is identified?

**Business-level survival for the 12,572-POI cohort is not identified.
Premises-level go-dark is** (§7), and a Foursquare closure panel now exists but
ascertains only a sliver (§8). The POI-cohort audit below stands: every
POI-linked instrument in the warehouse at the time of the first run was a
**current-state extract**.

| instrument | usable | closures | why |
|---|---|---|---|
| `poi_presence.last_seen_month` | no | 0 | One snapshot month (2026-09). All 227,548 locations have `n_months_seen = 1`. A location can only fall behind if there is a later month to fall behind of. |
| `storefront_pipeline.is_open` | no | 0 | `opened_on` non-null 56,571 = `is_open` 56,571. The pipeline's own `validate()` enforces `is_open ⇔ (opened_on IS NOT NULL)`. `is_open` means **ever opened**, not open today — using it as survival returns 100% by construction. |
| `dcwp_licenses.license_status` | yes | **114** | Real closures, wrong businesses. Top non-Active categories in the window: pedicab driver, ticket seller, stoop line stand, sightseeing guide, secondhand dealer. Essentially no overlap with the fifteen daily-needs categories. |
| `foursquare.date_closed` | no | 0 | 0 of 821,397 cached NYC rows carry it. The **column exists**; the fetch filtered to open venues. Upstream OS Places publishes closures. |
| `dohmh_restaurants` | no | 0 | 43nn-pn8j publishes establishments "in an active status as of the date of the data pull". A restaurant that closed is **absent**, not stale. Survivorship by publication policy. |
| `dof_storefront_registry.vacant_1231` | **as an OUTCOME, yes — see §9** | **1,080** | *Corrected 2026-09-14.* Premises grain with no business identity is a fatal objection to **attributing** a closure to a cohort POI. It is **not** an objection to the outcome itself. Keyed on `premises_id`, MN+BK: 1,080 premises occupied at 2022-12-31 were **vacant** at 2024-12-31 (plus 3,510 that stopped filing). 22× the 48-event floor, in the exact window, with no new data. |

So **the POI cohort** is ~100% survivors by construction: no business-level
survival outcome exists for those 12,572 storefronts. That is a statement about
the cohort, not about New York — §7 tests the premises-level outcome that *is*
identified, and it is the one that carries the decision.

**Kaplan-Meier on the POI cohort is therefore refused, not reported.** If it were
run it would print S(12) = S(24) = 1.000 on n = 12,572 with 0 events, and that
number is a picture of the extract, not of New York. `survival_gate()` returns
**NOT IDENTIFIED** for the POI cohort and no Cox model is fitted. `lifelines` was
deliberately not added to `pyproject.toml`: a dependency bought for a model that
cannot be fitted is a dependency bought with no observation behind it.

Exposure, for the record, is real and varies (p25/p50/p75 = 26.2 / 31.9 / 38.2
months). The **censoring indicator does not vary at all** — it is 1 everywhere.

### What unlocks it, precisely

* **One more `loci poi-snapshot`** makes `last_seen_month` a variable, and the
  first location present in 2026-09 and absent in 2026-10 is the first closure
  this project has ever observed. But a snapshot only sees closures **from that
  month forward**: the 2023-24 cohort's exits between 2023 and 2026 are
  permanently invisible (D79 — an observation cannot be reconstructed after the
  fact). Twelve forward months at the ledger's dated volume would plausibly
  yield 600–1,500 exits, far past the 48-event floor — **in 2027-09.**
* **To retrodict *this* cohort you need a historical panel, not a future one.**
  Two routes, in cost order:
  1. **Re-pull Foursquare OS Places without the open-only filter.** The
     `date_closed` column is already in the schema of the file on disk. Free,
     no new vendor, no licence rider. This is the cheapest unlock in the
     project and it should be done before anything on the paid wishlist.
  2. **Google Places Insights** monthly POI snapshots back to 2024-01 (D86 P1,
     GTM-159) — which would also un-censor part of D79's 47.7%.

---

## 5. Entry retrodiction — where did the 2023-24 openings actually land?

If the screen's gaps are *unviable* rather than *underserved*, operators — who
know the street — will avoid them. So: does the frozen t₀ score predict **where
the 2023-24 openings actually landed**?

Panel: 12,000 deterministically sampled lot-frame addresses × 6 categories =
72,000 rows, 103 NTAs, opening rate 58.0%. Logit with category fixed effects,
standard errors clustered on NTA, out-of-sample AUC with **whole NTAs held out**
(a random split would put the same 400 m disc on both sides and report a leak as
skill), bootstrap CI resampling NTAs rather than rows.

| measure | censored counted present at t₀ | `--strict-dated` |
|---|---|---|
| blocked-CV AUC (full) | **0.8663** [0.851, 0.881] | 0.8637 [0.848, 0.879] |
| **blocked-CV AUC, same model WITHOUT the score** | **0.8537** | 0.8535 |
| **HEADLINE LIFT** | **+0.0126** | +0.0102 |
| blocked-CV AUC (homes only) — *not the fair comparator* | 0.8182 | 0.8182 |
| lift over homes-only (superseded) | +0.048 | +0.046 |
| permutation null, p95 / max (200 draws) | 0.85366 / 0.85368 (cleared) | 0.85355 / 0.85356 (cleared) |
| **spatially structured placebo, p95 (40 draws)** | **0.8545** (cleared by +0.0118) | — |
| CD-blocked (36 CDs) full / no-score / lift | 0.8632 / 0.8496 / **+0.0136** | — |
| Brier score, full vs no-score | 0.1479 vs 0.1544 | — |
| AUC on the harder outcome (openings above the category's 75th percentile, 18.9% positive) | 0.903 vs homes-only 0.813 | 0.898 vs 0.813 |

**Correction, 2026-09-14 (statistician).** The first draft headlined **+0.048
against a homes-only baseline**. That comparator flatters the result: density +
`retail_index` + category fixed effects alone reach **0.854**. The module's own
permutation null already measured this — it refits the *full* model with only the
score permuted, so its mean (0.85364, spread 4e-5) **is** the no-score AUC, and a
direct no-score refit confirms **0.8537**. The honest marginal contribution of the
screen's score is **+0.0126**, and it survives coarser (CD) blocking at +0.0136
and a spatially structured placebo that preserves within-NTA smoothness while
destroying geography (p95 0.8545).

**Calibration** (out-of-sample deciles) is monotone; max |predicted − observed| =
6.2 pp (decile 5: 0.676 predicted vs 0.614 observed). Base rate 58%, so the AUC
is not imbalance-distorted — but the deliverable is a *ranking*, so calibration
travels beside it.

*Provenance.* The CD-blocked run, the spatially structured placebo, the Moran's I
statistics, the Brier scores and the NTA-FE / other-category specifications below
were produced by the statistician's review against the saved
`data/retrodiction/entry_panel.parquet`, not by `loci retrodiction run`. Every
other number in this memo comes from the command in §10.

Pooled coefficients (cluster-robust on NTA):

| term | coef | 95% CI | p |
|---|---|---|---|
| `log(1 + supply_ratio_t0)` | **+1.540** | [+1.269, +1.811] | 8e-29 |
| own-category-gap flag (zero competitors at t₀) | +0.081 | [−0.268, +0.430] | 0.65 |
| `log(homes)` | +1.472 | [+1.206, +1.739] | 3e-27 |
| `retail_index` (D82) | +0.818 | [+0.400, +1.235] | 0.0001 |

`log(jobs_400m)` (+0.114 [0.003, 0.224]) and `log(transit_entries_400m)` (+0.022
[0.003, 0.040]) **are withheld**. Moran's I on out-of-sample residuals (k = 8,
199 permutations) is **0.635 restaurant / 0.722 cafe_bakery / 0.766 grocery**
(E[I] ≈ 0, sd ≈ 0.004, p < 0.005). NTA-blocked CV protects the *AUC* from
optimism; it does not fix *inference*, because cluster-robust SEs on 103 NTAs
assume independence **across** NTAs. `log_score` and `log_homes` survive that
easily; two coefficients whose intervals barely clear zero do not, so they are
not reported as findings.

By category (lenient run; `own-gap` is the flag's own coefficient):

| category | opening rate | t₀ supply-ratio coef (95% CI) | own-gap coef (95% CI) | AUC | AUC homes-only |
|---|---|---|---|---|---|
| restaurant | 90.7% | +5.20 [+3.60, +6.80] | **−0.89 [−1.44, −0.33]** | 0.912 | 0.783 |
| cafe_bakery | 66.3% | +2.33 [+1.79, +2.87] | +0.23 [−0.29, +0.75] | 0.862 | 0.782 |
| nails_beauty | 65.0% | +2.45 [+1.96, +2.93] | +0.71 [+0.16, +1.25] | 0.841 | 0.773 |
| bar | 45.3% | +1.66 [+1.10, +2.22] | +0.79 [+0.03, +1.55] | 0.856 | 0.792 |
| hair_barber | 47.4% | +1.29 [+0.73, +1.86] | −0.06 [−1.12, +1.00] | 0.752 | 0.734 |
| grocery | 33.4% | +2.05 [+1.31, +2.79] | −0.65 [−1.65, +0.35] | 0.752 | 0.724 |

Pharmacy, laundry, convenience, clinic, bank, childcare, tailor and hardware are
**not reported**: 17–107 dated openings each is not a sample.

**Multiple testing.** Twelve uncorrected tests (6 categories × 2 coefficients).
At Bonferroni α = 0.05/12 = **0.0042**: restaurant's own-gap coefficient
−0.89 (z = −3.12, **p = 0.0018**) **survives**; bar's +0.79 (p = 0.043) and
nails' +0.71 (p = 0.011) **do not** and must not be quoted as findings. Every
`log_score` coefficient survives at any correction.

### The D1 sign check

**POSITIVE, in every category, with every confidence interval clear of zero.**
Openings in 2023-24 went **where supply was already thick**, conditional on
homes, jobs, transit and character — not where it was thin. The own-category-gap
flag is **indistinguishable from zero pooled** (+0.08, CI [−0.27, +0.43]) and
**significantly negative for restaurants** (−0.89, CI [−1.44, −0.33]): an
address with zero restaurants within 400 m in January 2023 was *less* likely to
get a restaurant over the next two years than an otherwise identical address
with some.

This is D87's attack **surviving**, not the screen being validated. It is also
the same result D81 found from the other direction — the fitted competition
elasticity γ was *agglomerative* for 7 of 10 categories at ZIP grain, and
incumbents proxy "is this a retail street".

### Is it just "retail streets"? Two conditioning steps say no

| specification | `log_score` coefficient | 95% CI |
|---|---|---|
| baseline (category FE) | +1.540 | [+1.269, +1.811] |
| **+ NTA fixed effects** (within-neighborhood) | +1.344 | [+1.067, +1.620] |
| **+ other-category t₀ supply in the same disc** | +1.214 | [+0.927, +1.501] |
| **both** | **+1.168** | **[+0.865, +1.472]** |

Conditioning on other-category supply — a direct "is this a retail street"
measure — leaves `log_supply_other` at +0.783 [+0.587, +0.979] and collapses
`retail_index` to +0.191 [−0.198, +0.580]. So **own-category thickness predicts
own-category entry within a neighborhood and net of general retail density.**
It is not reducible to "retail streets". It still cannot separate agglomeration
from herding — only a survival outcome can — but the *unmet-demand* reading is
dead either way.

This is not a repetition of D1. D1 put retail on the right-hand side predicting
growth; here openings are the **left-hand side** and the sign is measured rather
than assumed. That is D1 resolved, not restated.

---

## 6. Threats this memo does not escape

* **Entry is not survival.** This says where capital went, never whether it was
  right to go there. A positive entry coefficient is consistent with
  agglomeration economies being real, *and* with herding into saturated
  corridors. Only a survival outcome separates them — §7 tests the one the city
  publishes and it returns a null, so the two readings remain unseparated.
* **Reverse causality inside the entry test.** A 2023 opening is itself part of
  the thick supply that attracts the 2024 openings. The coefficient is a
  descriptive statement about co-location, not a causal one.
* **Anachronistic controls.** Homes are present-day PLUTO `UnitsRes`; jobs are
  LODES 2023; transit is 2026 ridership; `retail_index` is present-day. All
  enter as controls, never as the tested variable. Crediting 2023-24
  construction to 2023 biases *against* this memo's headline, not for it.
* **Straight-line, not network.** Internally consistent, and not comparable to
  any published Loci ratio.
* **Sample of 12,000 addresses.** The lot frame is 281,842 and their discs
  overlap; NTA clustering and NTA-blocked folds are the defence, but 103 NTAs is
  the real degrees of freedom, not 72,000 rows.
* **The permutation null is high (0.854) because that IS the no-score model.**
  It permutes only the score and leaves homes, character and the category fixed
  effects intact, so it measures the score's *marginal* contribution — and it is
  therefore the headline comparator, not a placebo to be cleared and forgotten.
  Its spread across 200 draws is 4e-5, so the +0.0126 is repeatable rather than
  lucky. A second, harder placebo (donating each NTA's scores from a randomly
  matched NTA by within-NTA rank, preserving smoothness and destroying geography)
  reaches p95 0.8545 and is also cleared.
* **Spatial autocorrelation is severe** (Moran's I 0.64–0.77 on OOS residuals)
  and is the reason two small coefficients are withheld rather than reported.

---

## 7. LL157 go-dark — the outcome that *is* identified

*Added 2026-09-14 after statistician review corrected §4.* `analysis.storefront`
is a **premises × reporting-year** panel carrying `vacant_1231`. Keyed on
`premises_id` with `bool_or` inside a year, MN+BK:

| 2022-12-31 → 2024-12-31 | n |
|---|---|
| occupied → **vacant** | **1,080** |
| occupied → occupied | 11,641 |
| occupied → *no 2024 filing* | 3,510 |
| vacant → occupied | 1,050 |

Predictor: the **frozen 2023-01-01 score** at the premises — total principled
daily-needs supply within 400 m per 1,000 homes, relative to the sample median —
plus `log(homes)` and `retail_index`. NTA fixed effects, SEs clustered on NTA,
out-of-sample folds on **28 spatial blocks coarser than NTAs** (a quantile tiling
of projected NTA centroids, so a fold never splits a neighbourhood). Both
attrition variants, split on `construction_reported`. Command:
`loci retrodiction go-dark`.

A premises already vacant in 2022 is **not at risk** and cannot be an event —
pinned by test. After dropping premises with zero homes or no NTA, n = 12,713
with **1,074 events** (8.4%); the attrition variant is n = 16,163 with **4,524
events** (28.0%).

| | strict (vacancy only) | attrition counted as an event |
|---|---|---|
| n / events | 12,713 / 1,074 (8.4%) | 16,163 / 4,524 (28.0%) |
| `log_score` coef, **with NTA FE** | −0.068 [−0.425, +0.290], p = 0.71 | **−0.254 [−0.430, −0.077]**, p = 0.005 |
| `log_score` coef, **no NTA FE** | **+0.419 [+0.232, +0.605]**, p = 1e-05 | **−0.196 [−0.290, −0.102]**, p = 5e-05 |
| block-held-out AUC, no NTA FE (with / without score) | 0.5485 / 0.5346 | 0.5440 / 0.5391 |
| lift | **+0.0139** | **+0.0050** |
| calibration, max \|pred − obs\| | 0.7 pp | 1.9 pp |

By LL157 activity group, strict definition (Bonferroni α = 0.05/3 = 0.0167):

| group | n | events | rate | `log_score` coef (95% CI) | p | survives |
|---|---|---|---|---|---|---|
| retail | 3,549 | 230 | 6.5% | **+0.628 [+0.323, +0.934]** | 4e-05 | **yes** |
| other | 4,932 | 455 | 9.2% | **+0.509 [+0.120, +0.898]** | 0.010 | **yes** |
| food | 4,232 | 389 | 9.2% | +0.218 [−0.022, +0.458] | 0.075 | no |

Under the attrition definition **no group survives** Bonferroni and every sign
flips negative (food −0.171, other −0.217, retail −0.148).

### What this shows, and what it does not

**The score does not usefully predict going dark in either direction.** AUC is
**0.55 against 0.54** without it — a lift of +0.005 to +0.014 on an outcome with
1,074 events. Calibration is near-perfect, which on a near-chance model means
only that the model reproduces the base rate.

**And the sign is determined by the outcome definition, not by the data.** Count
only reported vacancy and *thick* supply predicts going dark (+0.42), which reads
as churn concentrated on retail streets. Count "stopped filing" as an exit and
*thin* supply predicts going dark (−0.20), which reads as D87's attack landing.
Nothing inside LL157 can adjudicate between them: the 3,510 non-filers are
plausibly the distressed, and they are also plausibly small landlords who simply
stopped complying. **A test whose sign flips with a definitional choice settles
nothing**, and it is reported here as a null, not as support for either reading.

Three further limits: LL157 is **landlord self-report** with a selected filing
universe; a premises is a **building, not a shop** (`bool_or` — any reported unit
going dark counts); and the `construction_reported` split is **unusable** — only
19 of 12,713 strict-panel premises carry the flag, so vacancy-for-renovation
cannot be separated out at all.

The NTA-fixed-effects AUC is *below* 0.5 (0.456) because held-out blocks contain
NTAs whose dummies were never estimated; the FE specification is reported for its
coefficient, and the no-FE specification for its AUC. Neither rescues the result.

---

## 8. The Foursquare closure panel — events exist, ascertainment does not

*Added 2026-09-14.* The `AND date_closed IS NULL` filter at
`sources/universal/foursquare_places.py:182` has been removed and the feed
re-pulled: `staging.poi_closure` now holds **228,455 NYC closures**, of which
**13,643 match ledger rows**. For the 12,572-opening cohort that is **109 events**
(restaurant 83, café 18, bar 5) after excluding 67 rows whose `closed_on`
precedes their `opened_on` — above the 48-event floor.

**No Kaplan-Meier or Cox model is reported on it, and none should be.** 109
events on 12,572 openings implies S(24) ≈ 0.994. The true two-year survival rate
for NYC food service is near 0.75–0.80, so Foursquare ascertains on the order of
**3% of closures** — and not at random: a bar closing is announced, a tailor
closing is not. Any hazard ratio fitted on this panel is a statement about
Foursquare's editorial pipeline, not about New York's storefronts.

What it *is* good for: **54,190 mapped closures have no ledger row at all** —
they opened and closed before the 2026-09 snapshot. That is a genuine historical
panel, and a future retrodiction can use it **once the ascertainment model is
built** (closure detection probability by category, brand status and recency).
Until then it is a lead, not an outcome.

---

## 9. Verdict, in plain words

**The sentence the decision log may record, verbatim from the statistician:**

> The frozen 2023-01-01 screen predicts where 2023-24 openings landed out of sample
> (NTA-blocked AUC 0.866 vs 0.854 for the same model without the score, and above a
> spatially structured placebo at p95 0.8545), with a positive supply coefficient that
> survives NTA fixed effects and conditioning on other-category density (+1.17
> [0.87, 1.47]) — so the screen ranks retail streets, not unserved demand, and Loci may
> claim cost of search only; decision value remains unclaimed because no survival or
> failure-rate outcome has been tested, not because none exists.

**Unchanged by the go-dark test.** A survival-adjacent outcome *does* exist and
has now been tested (§7): 1,074 premises that went dark between 2022 and 2024.
The frozen score does not predict it — AUC 0.55 against 0.54 without it — and the
*sign* flips from +0.42 to −0.20 depending on whether "stopped filing" counts as
an exit. So the verdict sentence stands with one clause sharpened: decision value
remains unclaimed because the one survival-adjacent outcome we can test returns a
**null**, and the business-level outcome remains untested rather than absent.

**On the entry margin the screen's own logic points the wrong way.** Openings
clustered where supply per resident was already high, in every category tested,
and an address with no same-category competitor at all was, for restaurants,
*less* likely to get one (−0.89, the only per-category coefficient to survive
Bonferroni). The score carries real but modest out-of-sample information —
**+0.0126 AUC over the same model without it**, not the +0.048 against a
homes-only straw man — and that information runs in the direction of "this is a
retail street", not "this is an unserved opportunity".

**What a skeptical allocator may now be told**, and nothing more:

> Loci ranks addresses by how thin daily-needs supply is per resident, and that
> ranking is real, reproducible and cheaper than a broker walk-through. In a
> two-year backtest it predicted where New York's operators actually opened, out
> of sample, slightly better than the same model without it — but with the sign
> reversed from our pitch: they opened into *thick* supply, not thin, and that
> holds within a neighborhood and net of general retail density. We also tested
> the one failure-adjacent outcome the city publishes — 1,074 storefronts that
> went dark between 2022 and 2024 — and our score does not predict it in either
> direction. We therefore claim **cost of search and nothing else**. We do not
> claim the gaps we surface are viable sites, and we do not claim a survival or
> failure-rate benefit. The business-level survival test is still untested, not
> impossible; the data to run it is now partly in hand and its ascertainment
> problem is the next thing we will solve.

---

## 10. Reproduce

```bash
uv run loci retrodiction run --window 2023-01:2024-12 --radius-m 400 \
    --sample-n 12000 --permutations 200
uv run loci retrodiction report
uv run loci retrodiction go-dark --base-year 2022 --outcome-year 2024
uv run loci retrodiction go-dark-report
uv run pytest tests/test_retrodiction.py -q
```

Outputs: `data/retrodiction/cohort.parquet`, `entry_panel.parquet`,
`summary.json`, `go_dark_strict.parquet`, `go_dark_attrition_as_event.parquet`,
`go_dark.json`, `go_dark_no_nta_fe.json`. The run is read-only on the warehouse and retries the lock, so
it is safe beside a session rebuilding `analysis.address_category`. Sampling is
by `hash(address_id)` and every random draw is seeded (20260914), so a rerun is
a rerun.
