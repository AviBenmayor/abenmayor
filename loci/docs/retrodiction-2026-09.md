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

## 4. Closures: how many can actually be observed?

**Zero.** Not "few" — zero, and for a structural reason. Every closure
instrument in the warehouse is a **current-state extract**.

| instrument | usable | closures | why |
|---|---|---|---|
| `poi_presence.last_seen_month` | no | 0 | One snapshot month (2026-09). All 227,548 locations have `n_months_seen = 1`. A location can only fall behind if there is a later month to fall behind of. |
| `storefront_pipeline.is_open` | no | 0 | `opened_on` non-null 56,571 = `is_open` 56,571. The pipeline's own `validate()` enforces `is_open ⇔ (opened_on IS NOT NULL)`. `is_open` means **ever opened**, not open today — using it as survival returns 100% by construction. |
| `dcwp_licenses.license_status` | yes | **114** | Real closures, wrong businesses. Top non-Active categories in the window: pedicab driver, ticket seller, stoop line stand, sightseeing guide, secondhand dealer. Essentially no overlap with the fifteen daily-needs categories. |
| `foursquare.date_closed` | no | 0 | 0 of 821,397 cached NYC rows carry it. The **column exists**; the fetch filtered to open venues. Upstream OS Places publishes closures. |
| `dohmh_restaurants` | no | 0 | 43nn-pn8j publishes establishments "in an active status as of the date of the data pull". A restaurant that closed is **absent**, not stale. Survivorship by publication policy. |
| `dof_storefront_registry.vacant_1231` | no | 0 | LL157 vacancy runs to 2024 in earnest (41,749 rows; only 3,223 filed for 2025), and it is **premises grain with no business identity** — a cohort POI sits within 30 m of tens of registry units, and "some storefront in this building is vacant" is not "this business closed". |

So the cohort is **~100% survivors by construction**. The outcome variable has no
variance.

**Kaplan-Meier is therefore refused, not reported.** If it were run it would
print S(12) = S(24) = 1.000 on n = 12,572 with 0 events, and that number is a
picture of the extract, not of New York. `survival_gate()` returns
**NOT IDENTIFIED** and no Cox model is fitted. `lifelines` was deliberately not
added to `pyproject.toml`: a dependency bought for a model that cannot be fitted
is a dependency bought with no observation behind it.

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

## 5. The test that *is* identifiable today: entry retrodiction

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
| blocked-CV AUC (full) | **0.866** [0.851, 0.881] | 0.864 [0.848, 0.879] |
| blocked-CV AUC (homes only) | 0.818 [0.798, 0.837] | 0.818 [0.798, 0.837] |
| lift over baseline | **+0.048** (beats baseline) | +0.046 (beats baseline) |
| permutation null, p95 / max (200 draws) | 0.85366 / 0.85368 (beats placebo) | 0.85355 / 0.85356 (beats placebo) |
| AUC on the harder outcome (openings above the category's 75th percentile, 18.9% positive) | **0.903** vs homes-only 0.813 | 0.898 vs 0.813 |

Pooled coefficients (cluster-robust on NTA):

| term | coef | 95% CI | p |
|---|---|---|---|
| `log(1 + supply_ratio_t0)` | **+1.540** | [+1.269, +1.811] | 8e-29 |
| own-category-gap flag (zero competitors at t₀) | +0.081 | [−0.268, +0.430] | 0.65 |
| `log(homes)` | +1.472 | [+1.206, +1.739] | 3e-27 |
| `log(jobs_400m)` | +0.114 | [+0.003, +0.224] | 0.043 |
| `log(transit_entries_400m)` | +0.022 | [+0.003, +0.040] | 0.021 |
| `retail_index` (D82) | +0.818 | [+0.400, +1.235] | 0.0001 |

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

---

## 6. Threats this memo does not escape

* **Entry is not survival.** This says where capital went, never whether it was
  right to go there. A positive entry coefficient is consistent with
  agglomeration economies being real, *and* with herding into saturated
  corridors. Only the survival test separates them, and it is unidentified.
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
* **The permutation null is high (0.854) by design** — it permutes only the
  score and leaves homes, jobs, transit, character and the category fixed
  effects intact, so it measures the score's *marginal* contribution. Its spread
  across 200 draws is tiny, which is itself informative: the score moves the CV
  AUC by a repeatable +0.012 over that null, not by luck.

---

## 7. Verdict, in plain words

**The screen's score does not predict survival, because Loci cannot observe
survival at all today.** Every source it holds is a snapshot of what is open
now, so the 12,572 storefronts that opened in 2023-24 and are still in the
ledger are the ones that lived — there is no comparison group, and any survival
curve drawn from this data would say 100% and mean nothing. That is a data
finding, not a modelling failure, and the fix is specific: re-pull Foursquare OS
Places with `date_closed`, or buy Google Places Insights' monthly history. Until
one of those lands, no survival claim of any kind may appear in `docs/GTM.md`.

**What can be said today is worse for the thesis, not better.** On the one
margin that *is* measurable — where operators actually opened — the screen's own
logic points the wrong way. Openings clustered where supply per resident was
already high, in every category tested, and an address with no same-category
competitor at all was, for restaurants, *less* likely to get one. The gap score
does carry real out-of-sample information (AUC 0.866 vs 0.818 for a
homes-only baseline, and 0.903 vs 0.813 on the harder concentration outcome,
both beyond the placebo) — but the information runs in the direction of
"this is a retail street", not "this is an unserved opportunity".

**What a skeptical allocator may now be told**, and nothing more:

> Loci ranks addresses by how thin daily-needs supply is per resident, and that
> ranking is real, reproducible and cheaper than a broker walk-through. In a
> two-year backtest it predicted where New York's operators actually opened
> better than a population-density baseline — but with the sign reversed from
> our pitch: they opened into *thick* supply, not thin. We therefore claim cost
> of search and nothing else. We do not claim the gaps we surface are viable
> sites, we do not claim a survival or failure-rate benefit, and we cannot test
> either until we hold a closure panel. The cheapest one is free and is the next
> thing we will do.

---

## 8. Reproduce

```bash
uv run loci retrodiction run --window 2023-01:2024-12 --radius-m 400 \
    --sample-n 12000 --permutations 200
uv run loci retrodiction report
uv run pytest tests/test_retrodiction.py -q
```

Outputs: `data/retrodiction/cohort.parquet`, `entry_panel.parquet`,
`summary.json`. The run is read-only on the warehouse and retries the lock, so
it is safe beside a session rebuilding `analysis.address_category`. Sampling is
by `hash(address_id)` and every random draw is seeded (20260914), so a rerun is
a rerun.
