# Coverage validation — does the screen's MISSING flag mean a real hole? (P3)

**2026-09-14 · GTM-48 · CONTEXT §1.4/§7.1 (P3) · CHECKPOINT D29, D30, D50, D53, D58**
No `loci coverage-report` command exists yet (`cli.py`, `validation/*.py` checked) — turning
this into a subcommand is **GTM-50**. Everything below is an ad hoc read-only run:
`scratchpad/gtm48/analyze.py` / `chart.py` against the live warehouse, corrected by an
independent statistician pass in `scratchpad/gtm48/stat/` (`build.py`, `s1.py`–`s11.py`).
Sources: `results.md` (first pass) and `statistician-review.md` (correction), plus
`per_category.csv`, `per_decile_true_hole.csv`, `d29_style_split.csv`, `summary.json` — all
in `scratchpad/gtm48/`.

---

## 1. The question, and why it gates the finding

CONTEXT §7.1 states it plainly: OSM/Overture undercount small businesses in lower-income
neighborhoods — "precisely the areas the thesis flags as underserved." If that undercount
concentrates where the screen calls a gap, **the retail gap is a data gap wearing a costume**
(§1.4, P3, "would invalidate the entire finding"). CHECKPOINT D29 (2026-09-03) ran the first
version of this test at hex grain and found the raw survival rate mostly tracked how much
*wider* Google's type is than loci's category, not real coverage — hardware "not disproven"
(5%), fitness ~half geometry with a residual ~20% hole, clinic excluded pending re-anchor
(D30). GTM-48 re-runs it at the address frame (D58), the corrected 649 m radius (D53), and
the corrected type map (D50).

## 2. Design and run facts

Frame: `analysis.coverage_validation`, `address_id IS NOT NULL` (the D58 address frame) —
the 2,970 `h3_index` rows are the frozen pre-D38 hex frame and are never pooled with these
(D58). Stratified sample: income decile × missing/present arm × category, 20 per stratum,
seed **20260902**, 649 m straight-line radius (D53), MN 396 / BK 5,237 rows. **14 categories**
mapped; **clinic has no `GOOGLE_TYPES` entry** (GTM-105 #7, D30 untouched) and is skipped.

**5,633** (address × category) rows over 5,523 distinct addresses (`results.md` header,
`summary.json`), including **111 rows from a killed first attempt** (`run-attempt1.log`),
kept rather than discarded and flagged: trimming every stratum back to a strict
20-by-`address_id` drops 52 missing-arm rows (all convenience/grocery) and moves the pooled
naive rate from 10.49% to 10.69% — **+0.20 pp**, immaterial, but a real break of the
equal-allocation invariant unweighted pooling assumes (statistician-review.md §A4). Total
Google calls this session: **5,985** (`run-attempt1.log` 2,978→~3,441, `run.log`
3,441→8,963), **≈$190** beyond the free tier; ledger stands at **8,963/9,113**.

## 3. Headline: P3 survives, narrower than the first pass

`results.md`'s pooled true-coverage-hole rate is **10.5%** (2,774 missing-arm rows). The
statistician's review (`statistician-review.md` §A) found this both mis-weighted and
inflated by a type-map defect, and replaces it:

> **7.6% [6.5–8.8]** of MN+BK MISSING flags are coverage holes — **~40k of the 523,148**
> `*_ratio > 1.0` (address, category) pairs the screen actually emits. No income gradient is
> distinguishable from zero once standard errors respect the 137 (category × decile) design
> strata. Holes track **anchor absence**, not income: tailor_repair 37.5% (a floor),
> hair_barber 34.5% once its type map is narrowed, hardware 12.0% (a floor); every anchored
> category is ≤2%. Fitness's headline 35.6% was **entirely** `sports_club`/`marina` returns
> with zero `gym` or `fitness_center` hits — a type-map defect, not missing data.

Why the two pooled numbers disagree, in order of contribution:

1. **Equal-weight vs. design-weighted pooling.** Occupancy is exactly 20 per (category ×
   decile × arm) stratum by design, so naive pooling treats every category as equally
   prevalent in the "missing" population. It is not: bar is 22.5% of all real MN+BK missing
   flags, fitness 0.5%. Post-stratifying onto the real 523,148-pair population (same
   `frame='lot'` + `address_demographics` NTILE the sampler used) gives 7.9% vs. naive 10.5%
   — 10.5% is "the average category," not the screen's actual flags (statistician-review.md
   §A1).
2. **Type-map width for fitness and hair_barber.** Re-filtering ground truth to only the
   *requested* Google types (not the leaked response types) barely moves the pooled number
   (10.49%→10.27%) but flips two categories individually — see §4.
3. **Stratum-clustered inference** kills a reported income gradient a naive per-row test
   found significant — see §5.

Combining (1) and (2): pooled equal-allocation **7.5% [6.5–8.5]**; design-weighted **7.6%
[6.5–8.8]** (statistician-review.md, "Corrected headline").

## 4. Per-category table (corrected)

Wilson CIs and floors per `per_category.csv` / `d29_style_split.csv`; on-type recount and G9
grade per statistician-review.md §A2/§E (Wilson **upper** 95% bound, not the point estimate —
the bound is what makes a grade a promise).

| category | true-hole % [95CI], as requested | on-type recount | G9 grade (hi95 bound) |
|---|---|---|---|
| bank | 5.0 [2.7–9.0] | — (anchor exists) | **A** (9.0) |
| bar | 1.5 [0.5–4.3] | — | **A** (3.6) |
| cafe_bakery | 1.5 [0.5–4.3] | — | **A** (4.3) |
| childcare | 2.0 [0.8–5.1] | — | **A** (5.1) |
| convenience | 0.0 [0.0–1.5] | — | **A** (1.5) |
| fitness | 35.6 [28.9–42.8] | **0.6% (1/180)**, gym+fitness_center+yoga_studio only — sports_club/marina were the whole "hole" | **A** (3.1) |
| grocery | 5.6 [2.8–10.6] | — (no low-income arm, §5) | **B** (10.6) |
| hair_barber | 44.5 [37.8–51.4] | **34.5 [28.3–41.3]**, drop `beauty_salon` | **C** (41.3) |
| hardware | 12.0 [8.2–17.2] — **floor**, Google's type excludes `home_improvement_store` | — | **B** (17.2) |
| laundry | 1.5 [0.5–4.3] | — | **A** (4.3) |
| nails_beauty | 1.5 [0.5–4.3] | — | **A** (4.3) |
| pharmacy | 1.5 [0.5–4.3] | — | **A** (4.3) |
| restaurant | 1.0 [0.3–3.6] | — | **A** (3.6) |
| tailor_repair | 37.5 [31.1–44.4] — **floor**, Google offers only `tailor`, not shoe/clothes repair | — | **C** (44.4) |
| clinic | no data — no `GOOGLE_TYPES` entry (GTM-105 #7) | — | **C** (D30 untouched) |

Hardware and tailor_repair are **floors**: Google's own type is narrower than loci's category
in both, so the true hole is at least this large (statistician-review.md §A3; hole rows are
100% on-type: tailor 102/102, hardware 24/24, per `per_category.csv`).

## 5. Income analysis: naive vs. clustered

Naive row-level logistic on the true-hole outcome (n=2,774): slope **−0.064/decile
[−0.107, −0.021], p=0.0034** (`summary.json`, `results.md` §C) — reads as a real, significant
income gradient. The statistician rejects this as the wrong test (statistician-review.md §B):
**income decile is constant within a (category × decile) stratum**, varying over 137 cells,
not 2,774 rows.

| specification | b | se | p |
|---|---|---|---|
| naive, no FE (as reported) | −0.0639 | 0.0218 | 0.0034 |
| + category FE, naive SE | −0.0830 | 0.0256 | 0.0012 |
| + category FE, cluster by address (5,523) | −0.0830 | 0.0259 | 0.0014 |
| + category FE, **cluster by stratum (137)** | −0.0830 | 0.0485 | **0.087** |
| + category FE, **cluster by tract (484)** | −0.0830 | 0.0511 | **0.104** |
| + category FE, **permutation** (decile shuffled within category, 2,000 draws) | −0.0830 | — | **0.141** |

Every design-appropriate SE clears zero, and it is not a bundle effect: the 10 low-hole
categories alone give b=+0.009, p=0.88; the 4 high-hole categories alone give b=−0.104,
p=0.0004. Per-category low(1–5) vs high(6–10), Benjamini-Hochberg over 13 tests: only
**hardware** (21.0% vs 3.0%, q<0.0001) survives cleanly; **fitness** (45.0% vs 23.8%,
q=0.013) nominally survives but is §4's type-map artifact; hair_barber q=0.061; tailor_repair
q=0.66. **Verdict:** the point estimate is negative and stable (−0.06 to −0.08 log-odds/
decile) but its interval includes zero under every design-honest SE, and only hardware
survives multiple testing — "no demonstrated bundle-wide income gradient," which the
statistician calls a good result: the "data gap wearing a costume" failing to materialize
(statistician-review.md §B).

## 6. Power table

20/stratum gives n≈100 vs n≈100 per category per side. Two-sided α=0.05, 80% power minimum
detectable difference (MDD), by baseline rate (statistician-review.md §D):

| baseline rate | MDD (pp) |
|---|---|
| 2% (most anchored categories) | 9.1 |
| 5% (grocery, bank) | 11.9 |
| 24% (fitness, pre-correction) | 20.8 |
| 36% (hair_barber, tailor_repair) | 19.6 |

A 5%→10% doubling needs n=424 per half per category (21× today's design); 5%→15% needs 133.
**Every per-category income claim is underpowered except hardware (+18.0 pp observed) and
fitness (+21.3 pp, the type-map artifact)** — hair_barber's +17.0 pp sits below its own
19.6 pp MDD; tailor_repair's +3.0 pp is nowhere close. **Grocery has no low-income arm at
all**: deciles 1–3 hold n=1 each in the missing arm (`thin_strata.csv`), so 5.6% is a
decile-4–10 statistic only; design-weighted 10.1% [1.0–19.2] is the full precision available.
Fitness additionally has zero missing rows in decile 9.

## 7. Comparison to D29 (hex frame, 2026-09-03)

| category | D29 (hex, 800m) | GTM-48 (address, 649m) |
|---|---|---|
| hardware | 4/79 = 5% [2–12%] | **12.0% [8.2–17.2%]**, n=200, 0% geometry artifact — a higher, cleaner floor |
| fitness | 7/34 = 21% [10–37%], "~half geometry" | as-requested 35.6% [28.9–42.8%] but **type-corrected 0.6%** — no measured recall failure; **restored**, not demoted |
| clinic | 0/22 = 0% [0–15%], excluded (D30) | no data — still unmapped (GTM-105); D30 stands |

D53's radius fix collapsed the geometry-artifact share to 0% for hardware and 1.7% for
fitness (from D29's "~half"). What changed the fitness reading was not geometry but the type
map — D50 had widened it to `sports_club`, which D29's own lesson ("the survival rate tracks
how much wider Google's type is than loci's") predicted would happen (results.md §F;
statistician-review.md §A2/§C).

## 8. Data-quality notes

- **Type leakage, response side.** Fitness's query (gym/fitness_center/yoga_studio/
  sports_club) returned **30 `marina`** results inside its 64 "true holes" — never requested;
  hair_barber's query returned **163 `medical_clinic`** and **945 `nail_salon`** results,
  also never requested. `includedPrimaryTypes` is looser than its name implies (results.md,
  "Data-quality surprises" #2).
- **20-result cap censoring.** >10% of a category's rows hit Google's cap in the present arm:
  restaurant 66.2%, hair_barber 42.8%, cafe_bakery 37.0%, grocery 32.8%, laundry 21.2%,
  childcare 17.0%, bar 12.0% (`summary.json` `cap_flagged_over_10pct`). For these seven the
  Table B undercount-ratio sample is the **non-capped minority** — low-density-biased, not
  category-wide (results.md §B).
- **`n_osm = 0` is a schema fact, not a finding.** `staging.poi` has **no `osm_overpass`
  source at all** (overture 134k, foursquare 109k, DOHMH 30k, NYS DOS 13k, SNAP 9k, DCWP
  4.3k, SLA 3.2k, childcare 2.7k, Medicaid 2.4k). `results.md` read this as an OSM undercount
  result (#1); the statistician strikes it (statistician-review.md §C).

## 9. Decisions pending owner

1. **Demote `tailor_repair` and `hair_barber`** from headline categories on the D30 precedent:
   a 35–45% miss chance makes them undecidable at site level (statistician-review.md §C, §E).
2. **Adopt the numeric G9 ladder** — grade on the Wilson **upper 95%** bound: **A: hi95 ≤10% ·
   B: hi95 ≤25% · C: otherwise or no validation row** — in `recommend_grades.yaml`, replacing
   the presence-only rule (`docs/CATEGORY-EXPANSION.md` G9; statistician-review.md §E).
3. **Remove `sports_club` and `marina` from fitness in `GOOGLE_TYPES`** — validator-only, does
   not touch loci's own fitness category definition (statistician-review.md §A2, §C).

## 10. Reproduce

No `loci coverage-report` subcommand exists yet (GTM-50); the sample is reproducible via the
existing validator, the analysis below is ad hoc against the live warehouse:

```bash
# Draw/refresh the sample (D58's validator; already run 2026-09-14, seed 20260902):
uv run loci validate --per-stratum 20 --boroughs MN,BK --seed 20260902

# Recompute this memo's tables read-only (scratchpad/gtm48/):
python analyze.py     # per_category.csv, per_decile*.csv, d29_style_split.csv, summary.json
python chart.py        # coverage_bias_by_decile.png, false_gap_by_category.png
python stat/build.py   # design weights (poststrat.csv) for the statistician's corrections
python stat/s1.py … stat/s11.py   # the eleven checks behind statistician-review.md
```

Query pattern — **the frame boundary matters more than any other detail here**:

```sql
SELECT * FROM analysis.coverage_validation
WHERE address_id IS NOT NULL   -- D58 address frame
-- never pool with h3_index IS NOT NULL rows: those are the frozen pre-D38 hex frame,
-- a different unit, geometry and (pre-D53) radius (D58).
```

The two charts (`coverage_bias_by_decile.png`, `false_gap_by_category.png`) live only at
`scratchpad/gtm48/` — `docs/img/` does not exist yet, so nothing is copied in. Reproducible
from `chart.py` above, but ephemeral until GTM-50 makes this a `loci` subcommand with an
output path.
