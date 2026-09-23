# RQ-001 — Answer

Executed 2026-09-23. **v0.2, provisional, ZIP-tier only.**

This is the GTM-230 close-out pass, scoped to exactly three items left open by v0.1
(commit `412e826`): (1) implement the statistician's two-part AR(1) null for the
B-tenant composite (v0.1 got 0/200 valid sims with a single Gaussian AR(1)); (2) fix
the demand gate so its pass share is actually "free to vary" (v0.1's gate passed
almost exactly 50.0% of unit-years every year by construction — a fixed-share
percentile wearing a gate costume); (3) leave-one-episode-out robustness for the 3
macro terms. `regime_durability.py` gained `rank_churn_null_tenant_two_part`,
`macro_leave_one_episode_out`, and a fixed-anchor `demand_gate` (see METHOD.md /
GTM-230 items 1–3 for the design and `git log` for the diff). Composite A does not
depend on the demand gate and is **untouched by every change in this pass** — every
number below for composite A is byte-identical to v0.1, which is itself a useful
internal-consistency check.

**Headline result of this pass, stated up front because it changes the honest
framing more than the three items alone suggest: the demand-gate fix worked exactly
as specified (pass rate now moves 26.0%–39.3% by year, not frozen at ~50.0%), but it
did NOT rehabilitate either amended composite.** B-owner's near-zero churn got
*more* extreme, not less (implied duration 220.6y → 1023.0y), and B-tenant's
already-thin completed-exit sample **collapsed to zero** (6 completed incident exits
in v0.1 → 0 in v0.2), which is why its two-part null — now technically computable,
per item 1 — lands on a degenerate, information-free result. Neither outcome is a
bug in the fix; both are documented and diagnosed below, not hidden.

## What v0.2 can and cannot say

**Can say:** composite A is unaffected by anything in this pass and its one
positive result stands exactly as in v0.1 — its 2013 value carries a real,
statistically significant ranking signal (beats persistence and a same-model
placebo at both 5y and 9y), while still failing its own discovery-vs-favorability
falsifier (63.2% of completed exits are cost-led, unchanged). The demand gate is now
a genuine fixed-anchor LEVEL threshold whose pass share moves with real aggregate
demand (26.0% in 2000 rising to 38–39% by 2021–23) instead of being mechanically
pinned near 50% — amendment 1's stated intent is now actually implemented. The
macro leave-one-episode-out check (new this pass) shows all three pre-specified
exposure×macro terms keep the same sign when each of the three episodes is dropped
in turn, though none was Holm-significant to begin with, so "sign-stable" is a weak
claim here, not a discovery.

**Cannot yet say:** a calibrated duration number for any composite. The gate fix
increased the *incident* (datable-onset) sample for the amended composites
substantially (B-owner 2→13 spells, B-tenant 9→11 spells) but drove *completed*
incident exits to **zero for both** (B-owner already had 0; B-tenant fell from 6 to
0). B-tenant's sensitivity grid, run across all 12 band×persistence cells, now
returns an undefined median in **every single cell** — a stronger version of v0.1's
"the grid is the answer" finding, now applying with no exceptions. The two-part
tenant null (item 1) is now computable (200/200 valid sims, up from 0/200) but is
diagnostically uninformative — see Confidence #2. No composite clears the closure-
GLM kill criterion (unchanged), and the specific composite showing a significantly
wrong-signed within-ZIP coefficient **flipped from B-owner (v0.1) to B-tenant
(v0.2)** — itself evidence that these coefficients are not stable at this sample
size, not just that they fail.

## GTM-230 item 2: the demand-gate fix, in detail

The broken gate (v0.1) was `demand_pillar_A >= this year's median(demand_pillar_A)`.
Because `demand_pillar_A` is itself a within-year percentile rank, "this year's
median of a percentile rank" is ≈0.500 by definition, every year, regardless of what
demand actually did — a fixed-share-percentile gate, not a level gate. The fix
(`compute_pillar_percentiles` in `regime_durability.py`) standardizes income,
population density and worker density against a **fixed 2000–02 base-period**
mean/SD (the panel's own first three years; mirrors the fixed-anchor convention
already used for the macro exposures), averages the three z-scores into
`demand_level_z`, and gates on `demand_level_z >= 0` — the same absolute-level bar
in 2023 as in 2000.

**Result: the pass rate now genuinely moves.**

| Year | 2000 | 2005 | 2010 | 2015 | 2018 | 2020 | 2023 |
|---|---|---|---|---|---|---|---|
| Gate pass rate | 27.3% | 27.3% | 26.7% | 31.3% | 34.0% | 34.7% | 38.0% |

Full range 26.0%–39.3% (min 2012, max 2022), std 4.2% across 24 years — not pinned.
Overall average pass rate is **30.1%**, not 50%: because the anchor is the base
period's **mean** (not median) and income/density are right-skewed, "at or above
the mean" admits fewer than half of units even in the base years themselves. This is
a real, if secondary, consequence worth flagging for any future work that assumed
the gate would split the panel roughly in half (GTM-226 address-tier calibration,
in particular) — it now selects a smaller, more persistently-affluent top slice.

**This did not rehabilitate either amended composite; if anything it made both more
extreme.** See the headline hazard table and KM bullets below for the numbers.
The mechanism is coherent, not a new bug: a fixed "above the base-period mean"
bar selects a smaller, more structurally-elite, more persistently-ranked subset of
ZIPs than a within-year median split does — fewer marginal ZIPs hovering near a
cutoff means less observed churn in the gate itself, which propagates into even
less churn in the gated composites.

## Headline: annual exit hazard (the fallback headline, per the owner ruling)

The completed-incident-exit count gate (≥60 exits, ≥40 distinct units) **still
fails for all three composites, now more decisively for the amended composites**:
1 / 0 / 0 completed incident exits (A / B-owner / B-tenant), against 150 units.
Composite A is unchanged from v0.1. Per statistician condition 2 (S6), the stated
number remains the **piecewise annual exit hazard by spell-age band**, with a
cluster-robust (unit-block bootstrap, 1,000 reps) CI.

| Composite | Spell-age band | n spells | n events | spell-years | hazard/yr | 95% CI (unit bootstrap) |
|---|---|---|---|---|---|---|
| A | unknown (prevalent) | 69 | 18 | 1,166 | **1.54%** | 0.94% – 2.30% |
| A | 0–5 (incident) | 3 | 1 | 14 | 7.14% | 0% – 16.7% (n too small to trust) |
| B-owner | unknown (prevalent) | 42 | 1 | 933 | **0.11%** | 0% – 0.36% |
| B-owner | 0–5 (incident) | 13 | 0 | 62 | 0% | 0% – 0% |
| B-owner | 6–10 (incident) | 8 | 0 | 19 | 0% | 0% – 0% |
| B-tenant | unknown (prevalent) | 41 | 1 | 806 | **0.12%** | 0% – 0.44% |
| B-tenant | 0–5 (incident) | 11 | 0 | 53 | 0% | 0% – 0% |
| B-tenant | 6–10 (incident) | 7 | 0 | 17 | 0% | 0% – 0% |

Composite A is byte-identical to v0.1 (confirms the gate fix touched only the
amended composites, as designed). B-owner's prevalent hazard **fell** from 0.45%/yr
(v0.1) to 0.11%/yr — the opposite of what "fixing an artifact" would predict if the
artifact were suppressing real churn; instead the corrected, genuinely-varying gate
selects an even stickier subpopulation (see item 2 discussion above and Confidence
#3). B-tenant's prevalent hazard fell similarly, 1.87%/yr → 0.12%/yr, and its
previously-observed incident-band hazards (14.7%/yr at 0–5, 33.3%/yr at 6–10 in
v0.1) are now **exactly zero at both bands** — 0 events across 70 incident
spell-years. Stock-flow identity (mean favorable stock ÷ exits/yr): A 57.8y
(unchanged), **B-owner 1023.0y** (was 220.6y), **B-tenant 902.0y** (was 38.6y) — both
amended composites now imply multi-century durations from the stock-flow identity,
which is itself the diagnostic finding (Confidence #3), not evidence of real
stickiness.

The KM median/RMST is still reported **anyway, flagged**, per the owner ruling —
every one carries the same three flags as v0.1: **LOW-SAMPLE**, its relationship to
the rank-churn null, and that it is descriptive/ZIP-scale/relative, not a forecast.

- **(A) ORIGINAL** — unchanged from v0.1 in every figure: `n=3` incident spells, `1`
  completed exit, `3` distinct ZIPs. Median **6.0y**; RMST (truncated at **6y**) =
  **6.00y** (spatial-block bootstrap 95% CI **[6.00, 6.00]**, 490 valid / 10 dropped
  of 500 reps). **LOW-SAMPLE. Rank-churn null: NOT REJECTED** (observed 6.00 sits at
  the top edge of the null band [3.87, 6.00], 15/200 valid sims) — **withheld as a
  duration estimate**. A also still fails its own discovery-vs-favorability
  falsifier (Confidence #1).
- **(B-owner) AMENDED, demand-gated, no cost term** — `n=13` incident spells (up
  from 2), **still 0 completed exits**. Median undefined; RMST (truncated at 3y) =
  3.00y (CI [3.00, 3.00], 497/500 valid). **Rank-churn null: NOT REJECTED** (observed
  3.00 sits at the top edge of the null band [2.67, 3.00], 176/200 valid sims, up
  from 168/200 in v0.1). Per item 2's explicit question — **the ~0.45%/yr v0.1
  hazard was partly an artifact of the broken gate's mechanical near-stasis, but
  fixing the gate did not "reveal" more churn underneath it; it revealed even less**
  (0.11%/yr, implied duration 1023y). The null still cannot distinguish this from
  pure AR(1) rank persistence of the composite's now-smaller, more static eligible
  pool. **Conclusion: this remains not a finding about owner stickiness, now for a
  cleaner reason** — it is no longer explainable by "the gate was mechanically
  broken," and is better read as "a fixed-anchor top-~30%-by-demand-level slice of
  NYC ZIPs is, empirically, extremely rank-stable over 24 years" — which is closer
  to "rich ZIPs stay rich" than to any restaurant-relevant claim.
- **(B-tenant) AMENDED, demand-gated + 3-year cost-change term** — `n=11` incident
  spells (up from 9), **0 completed exits (down from 6 in v0.1)**. Median now
  **undefined** (was 5.0y). RMST (truncated at **2y**, down from 8y — truncation is
  the largest age with ≥10 units still at risk, and that age shrank along with the
  completed-exit sample) = **2.00y** (spatial-block bootstrap 95% CI **[2.00,
  2.00]**, 497/500 valid). **Two-part AR(1) null (GTM-230 item 1, new this pass):
  now COMPUTABLE — 200/200 valid sims** (v0.1: 0/200). Null RMST 95% band = **[2.00,
  2.00]** — observed RMST (2.00) is trivially "inside" this band, but the band
  itself is a single point equal to the truncation ceiling. **Diagnosis (as
  instructed, not forced): this is a sample-size degeneracy, not the v0.1
  simulation-degeneracy.** The two-part null's *mechanism* works — confirmed
  separately in a synthetic-data test (`tests/test_regime_durability.py`) where it
  produces a proper, non-degenerate band — but real B-tenant now has zero completed
  incident exits, so at 2-year truncation essentially every simulated AR(1) panel
  *also* shows no exit within 2 years, collapsing both the observed value and the
  null to the same floor. **This is an absence of information, not evidence of
  either stickiness or noise.** Do not quote this as a duration estimate or as a
  confirmed null result — it is neither.

**Sensitivity**: composite A's grid is unchanged from v0.1 — several cells never
cross 0.5, headline cell median 6.0y, **grid is the answer, not a number**.
Composite B-tenant's grid (all 12 band×persistence cells, run again this pass) now
returns **median = undefined (KM never crosses 0.5) in every single cell** — a
stronger version of v0.1's "240% move, grid is the answer" finding: there is no
longer even a single grid cell that produces a completed-exit-based median for
B-tenant.

**Common-tau comparison** (statistician correction 8: compare composites at a
shared, fixed truncation instead of each one's own native tau). The smallest common
tau across all three composites is now **2y** (B-tenant's own native truncation,
down from B-owner's 3y in v0.1): RMST(2y) = **2.00y for A, B-owner, AND B-tenant —
identically**. This is a starker version of the v0.1 finding ("the data cannot
resolve a horizon longer than ~3 years for any construction"): at the current
sample size, **no construction can currently resolve any duration signal beyond 2
years**, full stop.

## What ends spells (accounting, not cause)

Unchanged from v0.1 (composite A only, unaffected by this pass): across composite
A's 19 completed exits, cost moved most adversely in **63.2%** (12/19), supply in
26.3% (5/19), demand in 10.5% (2/19) — still confirms the discovery-falsifier leg
(≥60% cost-led). None of the discrete-time hazard coefficients were Holm-significant
(cost p_holm=0.738, demand p_holm=1.0, supply p_holm=1.0), though the full model
still beats a momentum-only comparator on log-likelihood (−81.1 vs −84.9) — byte-
identical to v0.1. **D1 guardrail holds throughout.**

**Macro leave-one-episode-out (GTM-230 item 3, new this pass).** For each of the 3
pre-specified exposure×macro terms (restaurant-employment exposure × NY-metro
unemployment change; non-retail/non-food job share × COVID; ZHVI-percentile
exposure × mortgage rate), refit with each of the three episodes (2001–03, 2008–10,
2020–22) dropped in turn:

| Term | coef (full) | p_holm (full) | coef (drop 2001-03) | coef (drop 2008-10) | coef (drop 2020-22) | sign stable |
|---|---|---|---|---|---|---|
| e1 (restaurant × unemployment) | +0.235 | 0.090 | +0.220 | +0.173 | +0.339 | **yes** |
| e2 (non-retail/food × COVID) | +0.533 | 0.497 | +0.478 | +0.533 | **0.000** | yes* |
| e3 (ZHVI × mortgage) | +0.103 | 0.230 | +0.112 | +0.132 | +0.134 | **yes** |

All three keep the same sign across every drop, but **none was Holm-significant in
the full sample to begin with** (p_holm 0.090 / 0.497 / 0.230, unchanged from v0.1 —
this pass adds robustness evidence, not a new discovery). Per S8's wording, sign
stability is necessary but not sufficient to call a term a driver, and none of
these three clears the Holm bar, so **no macro term is certified**. *Caveat on e2:
its "drop 2020-22" coefficient is exactly 0.000 because `covid_dummy` (the exposure
interaction's only source of variation) is 1 **only** in 2021–22 — dropping that
episode removes all variation in the term, so this particular leave-one-out check is
mechanically uninformative for e2, not real evidence of robustness. e2's two
*meaningful* drops (2001-03, 2008-10) do both keep the same sign as the full sample,
which is the real (still non-significant) evidence.* Convergence warnings
(`ConvergenceWarning`, `HessianInversionWarning`) were raised on at least one of the
four fits underlying this table — a pre-existing quality issue with this small-
sample logit (present in v0.1's full-sample fit too, not introduced by this pass),
now more visible because there are more refits. Coefficients should be read as
approximate.

**Regime model vs threshold rule (AC-9)**: unchanged from v0.1 (composite A only) —
k-means(k=4)+Markov implies mean favorable sojourn **1/(1−p_ff) ≈ 29.3y**
(p_ff=0.966). Composite A's RMST is still bounded at 6y by its own truncation, so
this comparison remains dominated by truncation and **inconclusive**, exactly as in
v0.1.

**Owner vs tenant**: v0.2 produces no quantitatively grounded duration expectation
for either — B-owner's non-finding is now cleaner (not attributable to a construction
bug) and B-tenant's is now thinner (0 completed exits vs 6 in v0.1, its rank-churn
null now runs but is uninformative rather than absent). Falsifier 4 from the
contrarian's pre-results verdict (owner vs tenant medians differ by <20%, meaning the
split is cosmetic) still cannot be evaluated, since neither has a real median.

## The two corrected validation checks (updated with the fixed-gate composites)

### 1. Ranking backtest (statistician correction 12 / contrarian post-results verdict)

Composite A is byte-identical to v0.1. B-owner and B-tenant are re-scored against
their (now differently-constructed) composite values.

| Composite | h | n at risk | Brier: logit / persist / const / placebo | diff vs persist (95% CI) | sig. | diff vs placebo (95% CI) | sig. |
|---|---|---|---|---|---|---|---|
| A | 5y | 53 | 0.086 / 0.245 / 0.208 / 0.224 | +0.159 (0.072, 0.258) | **yes** | +0.138 (0.064, 0.219) | **yes** |
| A | 9y | 53 | 0.143 / 0.264 / 0.204 / 0.264 | +0.121 (0.017, 0.216) | **yes** | +0.121 (0.029, 0.218) | **yes** |
| B-owner | 5y | 40 | 0.051 / 0.050 / 0.049 / 0.057 | −0.001 (−0.023, 0.032) | no | +0.007 (−0.002, 0.018) | no |
| B-owner | 9y | 40 | 0.144 / 0.175 / 0.167 / 0.160 | +0.031 (0.008, 0.059) | **yes** | +0.017 (−0.003, 0.042) | no |
| B-tenant | 5y | 40 | 0.066 / 0.075 / 0.072 / 0.070 | +0.009 (−0.002, 0.023) | no | +0.005 (0.0002, 0.010) | **yes (barely)** |
| B-tenant | 9y | 40 | 0.097 / 0.100 / 0.096 / 0.096 | +0.003 (−0.005, 0.013) | no | −0.001 (−0.012, 0.011) | no |

**The most important change in this pass, item-by-item:**
- **A is unaffected** and remains the only composite with a real ranking signal
  (significant vs both comparators, both horizons) — genuinely unchanged, not just
  similar.
- **B-tenant's v0.1 signal did NOT survive the gate fix.** In v0.1, B-tenant beat
  persistence significantly at 5y (+0.058) and marginally missed at 9y, and beat the
  placebo significantly at 5y (+0.053). In v0.2, it no longer beats persistence at
  either horizon, and its win vs placebo at 5y survives only barely (CI
  (0.0002, 0.010), an order of magnitude smaller effect than v0.1's +0.053). **This
  is evidence the v0.1 B-tenant ranking signal was substantially an artifact of the
  specific (broken) gate construction, not a robust property of the tenant reading**
  — exactly the kind of instability the gate fix was chartered to expose.
- **B-owner gains one new, narrow, and likely-fragile win** (significant vs
  persistence at 9y only, still not significant vs the stronger placebo test at
  either horizon) — not evidence of real signal; 1 of 4 tests, and the weaker
  comparator.

### 2. Closure criterion validity (statistician correction 11)

Unchanged methodology; composite A identical to v0.1.

| Composite | n ZIP-years | year+borough FE coef (p) | unit-FE (within-ZIP) coef (p) | kill criterion (unit-FE coef<0, p<.05) |
|---|---|---|---|---|
| A | 2,085 | −1.135 (p=3.4e-9) | +0.025 (p=0.872) | **FAIL** (unchanged) |
| B-owner | 2,085 | +0.863 (p=1.3e-6) | +0.107 (p=0.088) | **FAIL (wrong sign, no longer significant)** |
| B-tenant | 2,085 | +0.811 (p=4.8e-6) | **+0.229 (p=0.0016)** | **FAIL (wrong sign, NOW significant)** |

**No composite clears the kill criterion in either version — that headline
conclusion is unchanged.** But the *specific* composite whose within-ZIP coefficient
is significantly wrong-signed **flipped from B-owner (v0.1, p=6.6e-4) to B-tenant
(v0.2, p=0.0016)**. A single input-construction change (the gate) flipping which
composite fails "significantly" rather than "non-significantly" is itself evidence
that these within-ZIP coefficients are not robustly estimated at this sample
size/composite construction — another reason not to lean on either composite's
criterion-validity reading, beyond the fact that both still fail.

## Confidence

**Low, and this is the headline, not a caveat appended to a confident number.**

1. **Contrarian's discovery-vs-favorability falsifier (composite A): CONFIRMED,
   unchanged.** ≥60% of completed exits are cost-led (63.2%). Composite A also
   still carries a real ranking signal — not in tension, a composite can
   consistently rank a discovery-driven quantity.
2. **Rank-churn null: NOT REJECTED for A (unchanged) and B-owner (unchanged
   conclusion, updated band).** The B-tenant two-part null (item 1) is now
   computable (200/200 valid sims, up from 0/200) but lands on a **degenerate,
   single-point band [2.00, 2.00]** driven by B-tenant's zero completed incident
   exits — this should be read as "no information," not as "confirmed
   indistinguishable from noise" and not as "confirmed sticky."
3. **Count gate: FAILS for all three composites, and worse for B-tenant than in
   v0.1** (0 completed incident exits, down from 6) — a direct, documented
   consequence of the demand-gate fix tightening eligibility to a smaller
   (~30%, not ~50%), more static top slice. This is the expected cost of fixing a
   real bug, not new data and not a regression in the code.
4. **Named-neighborhood check: FAIL, unchanged** (5/14 hit, need ≥9) — composite A
   only, unaffected by this pass.
5. **Ranking backtest (corrected): A unchanged and still the only real signal.**
   **B-tenant's v0.1 signal did not survive the gate fix** (see table above) — read
   as evidence the earlier signal was gate-construction-dependent, not robust.
   B-owner gains one narrow, non-placebo-clearing win, not meaningful.
6. **Criterion validity (corrected): FAILS the kill criterion for all three
   composites, unchanged headline.** The specific significantly-wrong-signed
   composite flipped from B-owner to B-tenant across the gate fix — instability,
   not just failure.
7. **Macro leave-one-episode-out (new): all 3 terms sign-stable across all 3
   episode drops, but none Holm-significant to begin with** — robustness evidence
   for a null result, not a new finding. e2's 2020-22 drop is mechanically
   uninformative (see caveat above).

**Net**: v0.2 fixed the two chartered construction issues (the demand gate, the
tenant null) and added the macro robustness check. **None of this overturns v0.1's
central conclusion — it sharpens it.** No composite has a validated duration
estimate; no composite clears the closure-GLM kill criterion; and the one place
v0.1 reported a second (narrower) positive result — B-tenant's ranking-backtest
signal — did not survive the corrected gate, which is direct evidence that signal
was an artifact of the earlier broken construction rather than a real property of
"tenant favorability." Composite A's single positive result (a real ranking signal
that measures discovery, not favorability, by its own falsifier) is untouched and
remains the only thing this project has that survived its own correction twice now.
Before building the address-tier calibration (GTM-226) on any of these composites,
a composite still needs to clear the closure-GLM kill criterion, which none do.

## Validation

| Check | Status | Result |
|---|---|---|
| Annual exit hazard by spell-age band, cluster-robust CI (S6 fallback headline) | RUN | A unchanged. B-owner 0.11% prevalent (0–0.36%, down from 0.45%). B-tenant 0.12% prevalent (0–0.44%, down from 1.87%); incident-band hazards now exactly 0% at both bands (were 14.7%/33.3%). |
| Demand-gate fix (GTM-230 item 2) | RUN | Pass rate now moves 26.0%–39.3% by year (was pinned ~50.0%). Did not rehabilitate B-owner/B-tenant — both got more, not less, persistent. |
| Rank-churn null, composite A / B-owner / B-tenant (two-part, GTM-230 item 1) | RUN | A: NOT REJECTED (unchanged). B-owner: NOT REJECTED (3.00 in [2.67, 3.00], 176/200 valid). B-tenant: two-part null now computable (200/200 valid) but degenerate ([2.00, 2.00], driven by 0 completed exits) — no information, not a pass or fail. |
| Macro leave-one-episode-out (GTM-230 item 3) | RUN | All 3 terms sign-stable across all 3 drops; none Holm-significant. e2's COVID-episode drop mechanically uninformative (caveat). |
| Out-of-time backtest (2013 origin, age-only predictor, kept for comparison) | RUN | A unchanged (ties persistence exactly). B-owner/B-tenant KM now undefined at risk (nan Brier) — even the flawed age-only predictor can no longer compute, consistent with the collapsed completed-exit sample. |
| Ranking backtest (2013 origin, composite-value predictor) | RUN | A unchanged (significant vs both, both horizons). **B-tenant's v0.1 signal (significant vs both at 5y) did not survive the gate fix** — no longer significant vs persistence at either horizon. B-owner gains one narrow win vs persistence at 9y only. |
| Sensitivity grid + break-year detection, composite A AND B-tenant | RUN | A unchanged (grid is the answer). B-tenant: median now undefined in **all 12** grid cells (was 2–17y range) — stronger version of the v0.1 finding. No break-year flags for either. |
| Named-neighborhood check (`PREREGISTRATION.md`, urban-planner, blind) | RUN | FAIL, unchanged (5/14 hit; composite A only, unaffected). |
| Restaurant-closure criterion validity, lagged + clustered GLM + unit-FE, A/B-owner/B-tenant | RUN | Kill criterion FAILS for all three, unchanged headline. The significantly-wrong-signed composite flipped from B-owner (v0.1) to B-tenant (v0.2). |
| k-means(k=4)+Markov vs threshold-hysteresis (AC-9) | RUN | Unchanged, composite A only — inconclusive (truncation-dominated). |
| Contrarian + statistician post-results review, GTM-230 items 1–3 | APPLIED | This document, `regime_durability.py`, `test_regime_durability.py`; see METHOD.md. |
| Episode leave-one-out robustness for the 3 macro terms (statistician S8) | **RUN (this pass)** | See macro table above; GTM-230 item 3 closed. |
| B-tenant rank-churn null as a two-part gate/AR(1) process (statistician correction 13) | **RUN (this pass)** | GTM-230 item 1 closed; result is degenerate/uninformative, diagnosed above, not forced. |
| Demand-gate "free to vary" fix | **DONE (this pass)** | GTM-230 item 2 closed; pass rate verified free-to-vary; did not rehabilitate either amended composite. |
| Two-way (PUMA × year) clustered SEs / Moran's I spatial-error re-estimation (S7) | NOT RUN | GTM-228, out of this session's scope. |
| PUMA bootstrap (only spatial-block ran) | NOT RUN | GTM-226 (address-tier crosswalk work), out of scope. |
| Multi-origin backtest pooling (2011/2013/2015) | NOT RUN | GTM-228, out of scope. |
| Address-tier calibration | TICKETED | GTM-226. Should not proceed until a composite clears the closure-GLM kill criterion — still true after this pass. |

## Gaps → tickets

- **No composite has a validated duration estimate — unchanged headline, now on a
  cleaner basis.** B-owner's non-finding is no longer attributable to a gate
  construction bug (it survives the fix, more extreme). B-tenant's is now thinner
  (0 completed exits, undefined median in every sensitivity-grid cell). Parent:
  GTM-216; this analysis: GTM-225.
- **No composite clears the closure-GLM kill criterion** (GTM-232), unchanged. The
  significantly-wrong-signed composite flipped from B-owner to B-tenant across the
  gate fix — added evidence these within-ZIP coefficients are not stable at this
  sample size, beyond simply failing.
- **B-tenant's ranking-backtest signal from v0.1 did not survive the gate fix** —
  worth a note for anyone who might have started treating v0.1's B-tenant 5y result
  as usable; it was likely gate-construction-dependent. No new ticket; folded into
  GTM-225/GTM-232's "no validated composite" conclusion.
- **The corrected demand gate selects ~30% of unit-years, not ~50%**, because it
  gates on a fixed-period *mean* (not median) of a right-skewed distribution. Any
  future work assuming a roughly-half split (in particular GTM-226's address-tier
  calibration) should re-derive the eligible share explicitly rather than assume
  parity with the ~⅓ favorable-tercile convention used elsewhere in this project.
  No new ticket; noted for GTM-226.
- **Macro leave-one-episode-out's e2 term has a mechanically-uninformative
  2020-22 drop** (its only source of variation is zeroed by dropping the COVID
  years). Documented in `macro_leave_one_episode_out`'s docstring and above; no
  ticket needed.
- **Two-way (PUMA × year) clustered SEs, wild-cluster bootstrap on year, Moran's I
  / spatial-error re-estimation (statistician S7)** — not implemented, unchanged.
  GTM-228.
- **PUMA bootstrap was not run** — no ZIP/ZCTA-to-PUMA crosswalk file exists in
  this repo; only the spatial-block bootstrap runs. GTM-226.
- **Multi-origin backtest pooling (2011/2013/2015, statistician correction 12's
  secondary robustness check)** — not run this pass either. GTM-228.
- **DOHMH restaurant closure rollup is still ad hoc** (spatial-joined to static
  2020 ZCTA polygons; the coverage control is a log-density proxy, not real
  inspection-frequency data). GTM-232.
- **No 1994-99 pre-window exists in this warehouse**; headline window is
  2000-2023. GTM-233.
- **ZIP treated as ZCTA** — no USPS crosswalk file available. GTM-224.
- **Segment-level analysis** was built but not run through the full pipeline in
  this pass either. No existing ticket; flag for a future RQ-001 session.
