# RQ-001 — Answer

Executed 2026-09-22. **v0.1, provisional, ZIP-tier only.**

This is the post-results AMEND pass: the contrarian and statistician's post-results
verdicts (bottom of `METHOD.md`) found that v0's two remaining positive claims — the
2013-origin backtest "win" and the restaurant-closure criterion-validity "pass" —
did not test what they were cited for. Both are fixed and re-run below
(`ranking_backtest_2013`, `closure_validity_glm` in `regime_durability.py`). The
bootstrap's fixed-truncation bug is fixed (a tau is now required and held constant
across every resample; dropped resamples are counted and reported, not silently
discarded), the rank-churn null now runs for all three composites including B-owner
(never run before), the tenant composite's `fillna(0.5)` definition break is removed
(it is now undefined, not imputed, before its 3-year cost-change term exists), and
spell onset now requires an unambiguous prior-year signal (statistician correction 9).
**That last fix is the biggest single change in this pass** — it collapses the
"incident" (datable-onset) sample from 29/10/37 to 3/2/9 spells across A/B-owner/
B-tenant, because most 2000s-era onsets turn out to be preceded by an *ambiguous*
year (inside the 0.60–0.70 band), not a clearly-unfavorable one. This is not a bug;
it is what a correctly-applied incident-dating rule finds in this panel, and it makes
this run's numbers honest in a way the pre-results run's were not — but it also
means duration estimates are now even thinner than before.

## What v0.1 can and cannot say

**Can say:** the annual exit hazard for ZIPs that have already been favorable a
while (the "prevalent" pool, the best-populated part of the sample, ~1,000+
spell-years per composite) is low and fairly precisely bounded (well under 3%/yr for
all three composites). Newly-entered spells exit much faster in their first five
years, though that estimate is thin. Composite A — the one that structurally
rewards being cheap and under-restauranted — carries a real, statistically
significant ranking signal in the corrected backtest (see below): its 2013 value
predicts which ZIPs stay in their 2013 state better than persistence *and* better
than a placebo with the same values shuffled across ZIPs. That is genuine, if
narrow, evidence.

**Cannot yet say:** a calibrated duration number for any composite (rank-churn null
not rejected for A or B-owner; not computable at all for B-tenant at this sample
size — see Confidence #2), that any composite passes its own criterion-validity
check (the corrected, lagged, clustered, within-ZIP GLM — the only version immune to
a detection-coverage confound — finds **no composite** where being favorable
predicts fewer closures within the same ZIP over time; B-owner's within-ZIP
coefficient is *significantly positive*, the wrong sign), or that composite A's
ranking signal means what an operator would want it to mean (A still fails its own
discovery-vs-favorability falsifier — see Confidence #1 — so "A ranks ZIPs" may
mean "A ranks how long a ZIP stays cheap and undiscovered," not "how long conditions
stay good for a new restaurant").

## Headline: annual exit hazard (the fallback headline, per the owner ruling)

The completed-incident-exit count gate (≥60 exits, ≥40 distinct units) **fails for
all three composites, by a wide margin** (1 / 0 / 6 completed incident exits out of
150 units). Per statistician condition 2 (S6), the stated number is therefore the
**piecewise annual exit hazard by spell-age band, with a cluster-robust (unit-block
bootstrap, 1,000 reps) CI** — not a median or RMST. This is the real v0.1 headline.

| Composite | Spell-age band | n spells | n events | spell-years | hazard/yr | 95% CI (unit bootstrap) |
|---|---|---|---|---|---|---|
| A | unknown (prevalent, age undatable) | 69 | 18 | 1,166 | **1.54%** | 0.94% – 2.30% |
| A | 0–5 (incident) | 3 | 1 | 14 | 7.14% | 0% – 16.7% (n too small to trust) |
| B-owner | unknown (prevalent) | 54 | 5 | 1,115 | **0.45%** | 0.09% – 0.87% |
| B-owner | 0–5 (incident) | 2 | 0 | 4 | 0% | 0% – 0% (n too small to trust) |
| B-tenant | unknown (prevalent) | 70 | 19 | 1,014 | **1.87%** | 1.07% – 2.80% |
| B-tenant | 0–5 (incident) | 9 | 5 | 34 | 14.7% | 4.75% – 30.0% (thin) |
| B-tenant | 6–10 (incident) | 2 | 1 | 3 | 33.3% | 0% – 100% (uninformative, 3 spell-years) |

Reading: a ZIP that has *already* been favorable a while has roughly a 0.5–2%/yr
chance of dropping out, best-populated and most trustworthy for B-owner (stickiest)
and A/B-tenant (broadly similar, ~1.5–1.9%/yr). Newly-entered spells (age 0–5) exit
several times faster — consistent with ordinary mover-stayer heterogeneity — but that
estimate rests on 3–9 spells and should not be quoted as precise. The stock-flow
identity (mean favorable stock ÷ exits/yr) gives implied mean durations of 57.8y (A),
220.6y (B-owner) and 38.6y (B-tenant), broadly consistent in order of magnitude with
inverting the prevalent hazards (≈65y, ≈220y, ≈53y) — an internal-consistency check
that passes, even though none of these are the duration estimates below.

The KM median/RMST is still reported **anyway, flagged**, per the owner ruling that
a number should be shown even below the count-gate bar — but every one carries three
flags in the same sentence below: **LOW-SAMPLE**, its relationship to the rank-churn
null, and that it is descriptive/ZIP-scale/relative, not a forecast.

- **(A) ORIGINAL** — `n=3` incident spells, `1` completed exit, `3` distinct ZIPs.
  Median **6.0y**; RMST (truncated at **6y**, its own native truncation — the
  largest age with ≥10 units still at risk, driven down by the thin incident sample)
  = **6.00y** (spatial-block bootstrap 95% CI **[6.00, 6.00]**, 490 valid / 10
  dropped of 500 reps, all drops "no incident spells in that resample"). **LOW-SAMPLE.
  Rank-churn null: NOT REJECTED** (observed 6.00 sits at the top edge of the null band
  [3.87, 6.00], only 15/200 null sims valid) — **this figure is withheld as a
  duration estimate**, shown only because the owner ruling asked for display. A also
  fails its own pre-registered discovery-vs-favorability falsifier (Confidence #1).
- **(B-owner) AMENDED, demand-gated, no cost term** — `n=2` incident spells, **0
  completed exits**. Median undefined; RMST (truncated at 3y) = 3.00y (CI
  [3.00, 3.00], 447/500 valid). This is **not a finding about owner stickiness**:
  the demand gate passes exactly ~50% of unit-years every year by construction (it
  is `>= the year's median`, mechanically ~50/50, not "free to vary" as originally
  intended), and its inputs (interpolated population, back-filled workers,
  interpolated income) barely change rank year to year. Near-zero exits is what
  smooth, slow-moving inputs produce, independent of what is happening on the
  ground. **Rank-churn null: NOT REJECTED** (observed 3.00 sits at the top edge of
  the null band [2.43, 3.00], 168/200 valid sims) — confirms the composite's
  near-stasis is statistically consistent with pure rank persistence of smoothed
  inputs, not evidence of real stickiness.
- **(B-tenant) AMENDED, demand-gated + 3-year cost-change term** — `n=9` incident
  spells, `6` completed exits, `9` distinct ZIPs (the best-populated of the three,
  still far below the count-gate bar). The tenant composite is now undefined (not
  `fillna(0.5)`-imputed) for 2000–02, so its effective window begins in 2003.
  Median **5.0y**; RMST (truncated at **8y**) = **4.81y** (spatial-block bootstrap
  95% CI **[2.50, 6.50]**, 500/500 valid). **Rank-churn null: NOT COMPUTABLE at
  this sample size** — 0 of 200 null simulations produced enough incident spells to
  fit a KM curve at this truncation (a known, documented gap: the tenant
  composite's AR(1) null mis-fits its point-mass-at-zero for gate-failing years —
  statistician correction 13's proposed two-part gate/AR(1) null was not
  implemented this session; GTM-230). Because the null cannot be evaluated, this
  figure **cannot be certified as distinguishable from rank noise either** — absence
  of rejection is not the same as passing. **Do not quote this as an expectation.**

**Sensitivity**: composite A's grid median ranges from 6y up to "undefined" across
the 12 cells (several cells never cross 0.5) — an effectively infinite move, so
**the grid is the answer, not a number**. Composite B-tenant's grid (run for the
first time this pass, per the statistician's explicit instruction) ranges 2–17y, a
240% move from its own headline cell — also **the grid is the answer**. Both
composites fail the 50% stability bar badly.

**Common-tau comparison** (statistician correction 8: A's native truncation (6y),
B-owner's (3y) and B-tenant's (8y) are not directly comparable to each other). At the
smallest common tau available across all three (**3y**, B-owner's own native
truncation): RMST(3y) = **3.00y (A)**, **3.00y (B-owner)**, **2.75y (B-tenant)** —
all three composites converge to roughly the same ~3-year figure once truncation is
held fixed. This is itself informative: it says the data cannot currently resolve a
horizon longer than about 3 years across *any* of the three constructions, and the
apparent 6y/8y differences at each composite's own native truncation are mostly an
artifact of how much incident data each happens to have, not a real difference in
how long favorable conditions last.

## What ends spells (accounting, not cause)

Across composite A's completed exits (all 19, incident + prevalent pooled — cause
attribution does not require incident dating), the pillar that moved most adversely
was **cost in 63.2%** (12/19), supply in 26.3% (5/19), demand in 10.5% (2/19). This
still confirms leg (i) of the contrarian's discovery falsifier (≥60% cost-led).
Under the tenant composite, a cost-led attribution is **structural, not a finding**:
the tenant exit rule differences the cost percentile directly into the composite, so
attributing an exit to "cost" there partly restates the construction. None of the
discrete-time hazard coefficients (duration, lag-2-to-4 pillar changes, borough FE;
n=1,070 person-years, 17 events) were Holm-significant (cost p_holm=0.74, demand
p_holm=1.0, supply p_holm=1.0), though the full model beats a momentum-only
comparator on log-likelihood (−81.1 vs −84.9) — some signal exists, not enough to
certify a specific ranked driver. **D1 guardrail holds throughout**: nothing here
reads a supply/retail-density change as predicting a demand-led exit.

**Macro**: an underpowered association test, not a finding either way. Three
pre-specified exposure × macro interactions (restaurant-employment exposure × NY-
metro unemployment change; non-retail/non-food job share × COVID; ZHVI-percentile
exposure × mortgage rate), year FE, Holm-corrected — none survive correction
(p_holm = 0.090, 0.497, 0.230). With ~3 usable macro episodes in 24 years, this null
is a power statement, not evidence of no effect.

**Regime model vs threshold rule (AC-9)**: the k-means(k=4)+Markov model (fit ≤2013,
unaffected by the incident-dating fix since it uses continuous state persistence,
not spell labels) implies a mean favorable sojourn of **1/(1−p_ff) ≈ 29.3y**
(p_ff=0.966). Composite A's RMST is now bounded at just **6y** (its own truncation),
so a "Markov vs RMST" comparison is even more clearly dominated by truncation than
in the pre-results run — RMST(6) cannot exceed 6 by construction, so it says nothing
about whether the true process is memoryless. Notably, the comparison also
*flipped direction* from the pre-results run (where Markov's 29y looked "roughly
double" the RMST's ~15–17y): the stock-flow-implied duration (≈58y) and the
prevalent-band hazard-implied duration (≈65y) are now both *larger* than the Markov
figure, not smaller. Given every one of these figures moved substantially after a
single dating-rule fix while the Markov model itself did not change, **none of this
should be read as evidence for or against memorylessness — AC-9 remains
inconclusive**, more clearly so than before.

**Owner vs tenant**: v0.1 produces no quantitatively grounded duration expectation
for either. The owner figure is not a finding (see above); the tenant figure cannot
be certified against the null (not computable) and rests on 6 completed exits.

## The two corrected validation checks

### 1. Ranking backtest (statistician correction 12 / contrarian post-results verdict)

Unlike the original `backtest_2013` (prediction depends only on spell age via the
training KM curve, never the composite's value — kept below for comparison, and its
"beats persistence" claim from the pre-results run does **not** survive: with the
incident sample now down to 1–6 completed exits, A's age-only prediction is an
**exact tie** with persistence, 0.2453 = 0.2453, at both horizons), this trains a
logistic on the composite's VALUE and spell age, pooled over pre-2013 spell-years
(all active-spell years, incident and prevalent), and scores it at the true 2013
origin against persistence, a constant base rate, and a ZIP-shuffled placebo (a null
of "no ranking information"), with a unit-block bootstrap CI (500 reps) and an
approximate MDE (normal approximation, two-sided α=.05, 80% power).

| Composite | h | n at risk | Brier: logit / persist / const / placebo | diff vs persist (95% CI) | sig. | diff vs placebo (95% CI) | sig. |
|---|---|---|---|---|---|---|---|
| A | 5y | 53 | 0.086 / 0.245 / 0.208 / 0.224 | +0.159 (0.072, 0.258) | **yes** | +0.138 (0.064, 0.219) | **yes** |
| A | 9y | 53 | 0.143 / 0.264 / 0.204 / 0.264 | +0.121 (0.017, 0.216) | **yes** | +0.121 (0.029, 0.218) | **yes** |
| B-owner | 5y | 48 | 0.141 / 0.125 / 0.120 / 0.223 | −0.016 (−0.124, 0.093) | no | +0.081 (−0.030, 0.198) | no |
| B-owner | 9y | 48 | 0.096 / 0.125 / 0.116 / 0.168 | +0.029 (−0.063, 0.132) | no | +0.072 (0.013, 0.136) | marginal |
| B-tenant | 5y | 55 | 0.197 / 0.255 / 0.202 / 0.250 | +0.058 (0.010, 0.119) | **yes** | +0.053 (0.005, 0.117) | **yes** |
| B-tenant | 9y | 55 | 0.252 / 0.291 / 0.232 / 0.256 | +0.039 (0.018, 0.063) | **yes** | +0.003 (−0.028, 0.030) | no |

**Composite A carries a real, statistically significant ranking signal** — it beats
both persistence and a same-model placebo with shuffled composite values, at both
horizons, with observed differences well above the approximate MDE. Composite
B-tenant shows a smaller but still significant signal at 5y (beats both
comparators) that does not clear the placebo bar at 9y. Composite B-owner shows no
signal against persistence at either horizon (worse than persistence at 5y) and only
a marginal, likely noise, win against placebo at 9y (1 of 4 tests). **This is the
first methodologically sound positive evidence this project has produced that a
composite's value — not just its age — carries forward information.** It does not
rehabilitate composite A as a favorability measure, though: A still fails its own
discovery-vs-favorability falsifier below, so what A's value is predicting may be
"stays cheap and undiscovered a while longer," not "stays good for a restaurant."
That A ranks something consistently, and that what it ranks is discovery not
favorability, are not contradictory claims.

### 2. Closure criterion validity (statistician correction 11)

The pre-results check was a raw Welch t-test on 2,085 autocorrelated ZIP-years
(pseudo-replication — effective n closer to ~150 units), read favorable status
*contemporaneously* with closures rather than preceding them, and never applied the
borough conditioning its own docstring promised. The fixed version: closures LAGGED
one year behind favorable status, a clustered (unit-robust) binomial GLM with
year+borough FE, a second within-ZIP (unit FE) specification (the only one immune to
a static DOHMH-detection-coverage confound), and a coverage-proxy control
(log restaurant count, standing in for inspections-per-POI, which this warehouse
does not have).

| Composite | n ZIP-years | year+borough FE coef (p) | unit-FE (within-ZIP) coef (p) | kill criterion (unit-FE coef<0, p<.05) |
|---|---|---|---|---|
| A | 2,085 | **−1.135 (p=3.4e-9)** | +0.025 (p=0.872) | **FAIL** |
| B-owner | 2,085 | **+0.746 (p=4.0e-4)** | **+0.428 (p=6.6e-4)** | **FAIL (wrong sign)** |
| B-tenant | 2,085 | **+0.706 (p=1.6e-5)** | −0.040 (p=0.652) | **FAIL** |

The original "PASSES" result for composite A does not survive within-ZIP
conditioning: the strong between-ZIP association (favorable ZIPs close less)
collapses to a coefficient indistinguishable from zero once each ZIP is compared
only to itself over time — exactly the pattern a static detection-coverage
confound (rich/dense/well-inspected ZIPs both "score favorable" more and get more
DOHMH attention) would produce. B-owner's between- and within-ZIP coefficients are
both *significantly positive* — being B-owner-favorable predicts **more** closures
the following year, the opposite of what criterion validity requires. **No
composite clears the kill criterion. Criterion validity is not established for any
composite in this run.**

## Confidence

**Low, and this is the headline, not a caveat appended to a confident number.**

1. **Contrarian's discovery-vs-favorability falsifier (composite A): CONFIRMED.**
   ≥60% of completed exits are cost-led (63.2%, unchanged by the dating fix since
   attribution runs on all completed exits, not just incident). Composite A also
   carries a real ranking signal (above) — these are not in tension: a composite can
   consistently rank a discovery-driven quantity.
2. **Rank-churn null: NOT REJECTED for A or B-owner; NOT COMPUTABLE for B-tenant**
   at this sample size (0/200 valid null sims — a documented gap, GTM-230). None of
   the three duration figures above can be certified as distinguishable from pure
   rank persistence of noisy inputs.
3. **Count gate: FAILS badly for all three composites** — 1 / 0 / 6 completed
   incident exits, against a ≥60-exit bar. This collapse (from 6/0/20 in the
   pre-results run) is the direct, expected consequence of the statistician's
   correction 9 (unambiguous prior-year requirement), not new data. The annual
   exit hazard (headline, above) is what is actually reportable.
4. **Named-neighborhood check: FAIL by the pre-registered rule** (5/14 hit, need
   ≥9; unchanged by this pass since named-ZIP scoring reads onset/exit years, not
   the incident flag). Hard gate (10128) passed; non-template subset cleared its
   numeric bar (4/6) but **two of those four (11215, 10128) are pinned out by
   construction per PREREGISTRATION §0.3** (ZHVI already top-decile / no realistic
   demand score reaches 0.70) and are not evidence the model discriminates. The
   11211/10002 "both MISS, likely because..." explanations in the pre-results run
   were speculative and are labeled **unverified**, not retained as findings.
5. **Ranking backtest (corrected): A and, partially, B-tenant show a real signal;
   B-owner does not.** See the table above — this is the first check in this
   project to survive its own correction and still show something.
6. **Criterion validity (corrected): FAILS the kill criterion for all three
   composites**; A's previously-reported "PASS" does not survive within-ZIP
   conditioning, and B-owner's within-ZIP coefficient is wrong-signed and
   significant.

**Net**: v0.1 has **no validated duration estimate for any composite** and **no
validated criterion-validity result for any composite**. It has **one narrow,
methodologically sound positive result**: composite A's 2013 value carries real
forward information about which ZIPs stay in their state, beating both persistence
and a placebo. That result does not establish A as a favorability measure — A still
measures discovery by its own falsifier — so it licenses "A ranks something
persistent" and nothing stronger. Before building the address-tier calibration
(GTM-226) on any of these composites, the tenant rank-churn null needs to actually
run (GTM-230), and a composite needs to clear the closure-GLM kill criterion, which
none currently do.

## Validation

| Check | Status | Result |
|---|---|---|
| Annual exit hazard by spell-age band, cluster-robust CI (S6 fallback headline) | RUN | See headline table. Prevalent-band hazards: A 1.54% (0.94–2.30), B-owner 0.45% (0.09–0.87), B-tenant 1.87% (1.07–2.80). Incident-band hazards are directionally higher but too thin (3–9 spells) to trust precisely. |
| Out-of-time backtest (2013 origin, age-only predictor, kept for comparison) | RUN | Not evidence of ranking — predictor never uses the composite value. A now ties persistence exactly (0.2453=0.2453); B-tenant still nominally "beats" it (0.218 vs 0.255, 5y) but this is the flawed predictor per the contrarian's post-results critique. |
| Ranking backtest (2013 origin, composite-value predictor, vs persistence/const/placebo, bootstrap CI + MDE) | RUN | A: significant vs both comparators at 5y and 9y. B-tenant: significant at 5y, not at 9y vs placebo. B-owner: not significant. |
| Rank-churn null, composite A / B-tenant / B-owner | RUN | A: NOT REJECTED (6.00 in [3.87, 6.00], 15/200 valid). B-owner: NOT REJECTED (3.00 in [2.43, 3.00], 168/200 valid) — run for the first time this pass. B-tenant: NOT COMPUTABLE (0/200 valid sims; GTM-230). |
| Sensitivity grid + break-year detection, composite A AND B-tenant | RUN | A: grid moves to "undefined" (>50%). B-tenant (run for the first time this pass): 2–17y range, 240% move. No break-year flags for either (0/23 years flagged). |
| Named-neighborhood check (`PREREGISTRATION.md`, urban-planner, blind) | RUN | FAIL (5/14 hit, need ≥9); hard gate (10128) passed; non-template subset (4/6) technically cleared its bar but 2 of 4 hits are pinned out by construction; speculative 11211/10002 explanations labeled unverified. |
| Restaurant-closure criterion validity, lagged + clustered GLM + unit-FE, A/B-owner/B-tenant | RUN | Kill criterion FAILS for all three. A's pre-results "PASS" does not survive within-ZIP conditioning. B-owner's within-ZIP coefficient is significantly wrong-signed. |
| k-means(k=4)+Markov vs threshold-hysteresis (AC-9) | RUN | Inconclusive — comparison direction flipped after the dating fix (Markov 29.3y vs. hazard/stock-flow-implied ≈58–65y); RMST truncation (6–8y) makes any "double/half" claim a truncation artifact either way. |
| Macro as a hazard driver (H2, Holm-corrected) | RUN | No term Holm-significant (p_holm 0.090 / 0.497 / 0.230). Underpowered, not null. |
| Contrarian + statistician post-results review: 9 wording edits + corrections 1–13 | APPLIED | This document and `regime_durability.py`; see `METHOD.md`. Corrections not fully implementable this session are listed below with tickets. |
| Episode leave-one-out robustness for the 3 macro terms (statistician S8) | NOT RUN | GTM-230. |
| Two-way (PUMA × year) clustered SEs / Moran's I spatial-error re-estimation (S7) | NOT RUN | GTM-228. |
| PUMA bootstrap (only spatial-block ran; METHOD asks for the wider of the two) | NOT RUN | GTM-226 (address-tier crosswalk work). |
| B-tenant rank-churn null as a two-part gate/AR(1) process (statistician correction 13) | NOT RUN | GTM-230 — needed to make the B-tenant null computable at all. |
| Demand-gate "free to vary" fix (currently mechanically ~50% every year) | NOT DONE | Flagged by both reviewers pre-results; out of this session's explicit fix list. GTM-230. |
| Address-tier calibration | TICKETED | GTM-226. Should not proceed until a composite clears the closure-GLM kill criterion. |

## Gaps → tickets

- **No composite has a validated duration estimate.** The count-gate collapse (to
  1/0/6 completed incident exits) after the incident-dating fix means the annual
  exit hazard, not a median/RMST, is the only defensible headline number at v0.1.
  Parent: GTM-216; this analysis: GTM-225.
- **No composite clears the closure-GLM kill criterion** (GTM-232). A's
  between-ZIP association does not survive within-ZIP conditioning; B-owner's
  within-ZIP coefficient is significantly wrong-signed. This needs either a real
  DOHMH-inspection-frequency table (the current coverage control is a density
  proxy) or acceptance that criterion validity is not established for v0.1's
  composites.
- **B-tenant's rank-churn null could not be computed** (0/200 valid sims at
  truncation 8y). Statistician correction 13's proposed fix (model the gate as a
  two-part AR(1) process rather than fitting a single Gaussian AR(1) to a
  composite with a point mass at 0) was not implemented this session. GTM-230.
- **The demand gate passes almost exactly 50% of unit-years every year by
  construction** (`>= the year's median`), which both reviewers flagged
  pre-results as mechanically defeating amendment 1's intent ("free to vary").
  Not fixed this session (not on the explicit fix list); flagged again here.
  GTM-230.
- **Episode leave-one-out robustness for the 3 macro terms (statistician S8)**
  was not run this session. GTM-230.
- **Two-way (PUMA × year) clustered SEs, wild-cluster bootstrap on year, Moran's I
  / spatial-error re-estimation (statistician S7)** were not implemented — the
  hazard model still uses borough-proxy-clustered SEs only. GTM-228.
- **PUMA bootstrap was not run** — no ZIP/ZCTA-to-PUMA crosswalk file exists in
  this repo; only the spatial-block bootstrap runs. GTM-226.
- **Multi-origin backtest pooling (2011/2013/2015, statistician correction 12's
  secondary robustness check)** was not run this session — only the single 2013
  origin. GTM-228.
- **DOHMH restaurant closure rollup is still ad hoc** (spatial-joined to static
  2020 ZCTA polygons; the coverage control is a log-density proxy, not real
  inspection-frequency data). GTM-232.
- **No 1994-99 pre-window exists in this warehouse**; headline window is
  2000-2023. GTM-233.
- **ZIP treated as ZCTA** — no USPS crosswalk file available. GTM-224.
- **Segment-level analysis** was built but not run through the full pipeline this
  session either. No existing ticket; flag for a future RQ-001 session.
- **A real bug was fixed this session**: the spatial-block bootstrap previously
  computed each replicate's own RMST truncation instead of a fixed tau, which let
  a reported upper CI bound (17.21) exceed its own truncation point (17) —
  impossible for a correctly-bounded RMST. Fixed (`spatial_block_bootstrap_median`
  now requires a fixed `rmst_trunc` and reports dropped-replicate counts/reasons
  instead of silently discarding them). No ticket needed, noted for the record.
