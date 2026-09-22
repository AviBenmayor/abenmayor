# RQ-001 — Method (v0 decisions)

Judgment memo by the data-scientist agent, 2026-09-22, written against `SEED.yaml`. Design only. Nothing here has been run.
Naming follows CONTEXT.md §4.2. "Baseline" and "tier" are overloaded there, so this memo says **comparator** and **panel tier**.

## 1. Pillars, standardization, weights

**Universe.** A fixed, balanced set of ZIPs: residential population ≥ 2,000 and present in every year. Rank terciles over a universe that changes size produce fake entries and exits. Postal ZIPs (ZBP) and ZCTAs (ACS) are joined through one frozen crosswalk. PO-box and single-building ZIPs are dropped.

| Pillar | ZIP panel tier (headline window **2000→latest**) | Available from |
|---|---|---|
| Demand | ZBP total employment per km² (workers); ACS median household income (real dollars) plus population per km² (residents) | ZBP 1994, ACS 2009 vintage |
| Supply | Restaurant saturation = ZBP 722 establishments ÷ (residents + workers). **Lower is favorable** | 1998 (NAICS); SIC 5812 before that |
| Cost | ZHVI level. **Lower is favorable** (entry-cost reading; see §6 for the owner reading) | 2000 |

- **Missing early pillars.** Missing cost before 2000 means the headline window starts in 2000. Cost is not imputed, because it is the pillar the tenant reading depends on. Missing ACS before 2009: demand for 2000–08 uses employment plus decennial-2000 population held fixed. The pillar is re-based at the 2009 join, and a pre/post agreement check on overlapping years must show rank ρ ≥ 0.8. **1994–1999** (demand and supply only) is not a headline. Its one job is to date the onset of spells already running in 2000 (see §3).
- **ZORI (2015+)** is not a composite input: a definition that changes mid-panel creates exits. It is a check only, and its rank correlation with ZHVI is reported.
- **Standardization.** Each component becomes its within-year percentile rank. A pillar is the mean of its component percentiles, re-ranked. Ranks absorb citywide level shifts and are robust to outliers.
- **Weights: equal (⅓ each), fixed over time.** PCA is rejected: its first component loads on the demand–cost co-movement, which is the wealth axis, and that makes the output a static wealth map. PCA weights would also drift by year. Outcome-based weights are circular, because the outcome (spell exit) is defined from the composite. Sensitivity is tested by leaving one pillar out. With demand high and cost and saturation low, "favorable" means *demand outrunning cost*. That is the intended margin reading, and in practice it is the emerging window, not the rich core.
- **Address panel tier (2010+, calibration only, not v0).** Demand: LODES WAC plus ACS block-group data inside the travel-time trade area, with DOT pedestrian counts and MTA ridership where present. Supply: DOHMH and SLA restaurant counts. Cost: ZORI/ZHVI **of the containing ZIP**, because there is no address-level rent. Say so on every output.

## 2. Favorable spell (hysteresis is load-bearing)

A raw ⅔ cutoff counts rank noise as regime shifts. The v0 rule, applied to the composite percentile *c*:

- **Enter** when *c* ≥ 0.70 for 2 consecutive years. Onset is the first of those years.
- **Exit** when *c* < 0.60 for 2 consecutive years. The exit year is the first of those years. A single-year dip below 0.60 does not end a spell.
- The minimum spell length is therefore 2 years.

The sensitivity grid is bands {raw 0.667, 0.63/0.70, 0.60/0.70, 0.57/0.73} × persistence {1, 2, 3}. **If the headline median moves more than 50% across the grid, the answer is the grid, not a number.** A diagnostic reports the year-on-year |Δ*c*| distribution, and the band half-width must be at least its median.

ACS vintages are dated to their **end year**, meaning what an operator could have known then. This carries a lag of about 2 years, which is stated.

## 3. Duration estimator

- **Kaplan–Meier on spell-years** (discrete time), right-censored at the last panel year. Ongoing spells are never dropped.
- **Spells already running in 2000.** Where the 1994–99 demand+supply panel dates the onset, the spell enters the risk set in 2000 at age 2000 − onset (**left truncation, delayed entry**). Where the onset is undatable, the spell is excluded from the headline KM and reported as a separate "already ≥ *k* years" lower-bound group. Dropping these spells silently would bias durations short (length bias).
- **If censoring exceeds 50% at the median**, report "median > *X*" plus the **restricted mean survival time to 20 years**. Never extrapolate the tail.
- **Stock–flow sanity check.** The favorable stock is about N/3 by construction, so mean duration ≈ (N/3) ÷ annual exits. The KM result must agree with this identity to within its CI.
- **Confidence intervals** come from a cluster bootstrap, resampling **PUMAs** (about 55 clusters; each ZIP is assigned to the PUMA holding most of its population, and all of its spells move together), 2,000 reps. Borough clusters (5) are too few and are shown only as a wide bound. Caveat: rank definitions make exits zero-sum across ZIPs, which no resampling scheme reproduces. The intervals are approximate.

## 4. Regime model (v0): k-means + Markov, HMM deferred to v1

- **Features.** Per ZIP-year: the three pillar percentiles plus each pillar's 3-year change. That is level plus rate, so the states are not a wealth map.
- **Fit.** k-means with k = 4 on pooled years **≤ 2013** only. Later years are assigned to the frozen centroids. A state is "favorable" if its centroid composite sits in the top tercile.
- **Transitions.** The first-order Markov matrix is counted on state sequences filtered by the same 2-year persistence rule, so the model and the rule measure the same object.
- **Why not HMM for v0.** An HMM has label switching and sensitivity to initialization, and with about 180 series it will spend states on vintage breaks.
- **Implied mean sojourn = 1/(1 − p_ff).** This assumes a geometric (memoryless) duration. Comparing it with the KM median is the AC-9 test of that assumption. If the KM hazard **falls with spell age** (older spells are stickier), the Markov figure understates long tenure, and the KM figure governs.

## 5. Drivers: discrete-time hazard

The model is a logit of P(exit in year *t* | at risk) on:

- a duration spline;
- the pillar percentile changes over *t*−4→*t*−2 (**lags of at least 2 years**; contemporaneous changes are the definition of exit, an accounting identity);
- borough fixed effects.

Standard errors are clustered by PUMA. Drivers are ranked by standardized coefficient.

A separate table decomposes each exit into which pillar fell most. It is labeled **accounting, not cause**. Saturation appearing as a driver is part of the composite's own accounting. It is not a claim that retail predicts neighborhood change, so the D1 guardrail holds.

**Macro. What can and cannot be identified:**

- **Level macro cannot move relative favorability.** Terciles are relative and the favorable share is fixed at about ⅓, so a shock that moves everyone changes no ranks. A macro main effect on the *aggregate* exit rate is therefore close to mechanically null.
- **Year FE and NYC-wide macro series are perfectly collinear.** Each series has one value per year. Include one or the other, never both.
- **Testable hypothesis H1: macro raises churn.** Regress the year-level exit rate on the macro series. The effective n is about 24 years and about 3 episodes (2001, 2008–09, COVID). This is **descriptive only**, with no significance claim.
- **Testable hypothesis H2: macro reorders ranks.** Model exit hazard with **year FE plus macro × exposure interactions**, identified cross-sectionally. Examples: recession × the ZIP's restaurant share of employment; COVID × office-job share (LODES CNS codes); rates × ZHVI level.
- **Not identifiable:** a causal pillar effect; separating COVID from the 2020 ACS collection anomaly.

**Macro series.** If the FRED/BLS ingest is absent, macro is marked BLOCKED with its ticket id. Not fabricated.

## 6. Owner vs tenant (one spell set, two readings)

The same spell set is read two ways by attributing a **cause** to each exit (the pillar with the largest adverse percentile move over the exit window) and computing cause-specific cumulative incidence (Aalen–Johansen):

- **Tenant.** The reading is conditional survival over the lease, S(*a*+10)/S(*a*) at spell age *a*, from all-cause exits. Alongside it: **the cumulative incidence of cost-led exits before year 10 (renewal)**, plus a "rent-reset flag" (cost percentile up by ≥ 0.15 over the term), which is reported even when the spell survives.
- **Owner.** A cost-led exit is appreciation, a gain. It is reported as an "appreciation exit", not as a loss. Owner risk is the cumulative incidence of **demand- or supply-led** exits. Property return is not modeled, and the memo says so.

## 7. Segments (ZIP panel tier)

- **Codes.** 722511 full-service, 722513 limited, 722515 snack/coffee, 722410 bars. Before 2012 they are crosswalked: 722110→722511; 722211 (+ 722212 cafeterias)→722513/722514; 722213→722515.
- **Supply only.** ZBP detail gives **establishment counts by size class only**, with no employment by NAICS, so a segment changes only the supply pillar.
- **Minimum size.** A segment is run only where the median ZIP count is ≥ 10. Bars will likely fail this and be pooled with limited-service.
- **Correlation.** Segment spells are highly correlated with all-restaurant spells by construction. Report the difference, not four independent answers.
- **Noise.** CBP noise infusion (2007+) adds noise to small counts, which widens flicker. The hysteresis grid must be re-run per segment.

## 8. Validation

- **Out-of-time backtest.** Freeze everything on data ≤ 2013: the hysteresis rule, the centroids, the transition matrix, the hazard coefficients, and the ZHVI-only cost pillar. Score spells at risk at the 2013 origin: P(still favorable in 2018) and P(still favorable in 2023).
- **Comparators.** (a) **The median-for-all comparator**: the unconditional training KM curve, with spell-age conditioning only. (b) Naive persistence (P = 1).
- **Metrics.** IPCW Brier score at 5 and 10 years; Uno's C; decile calibration. All are reported **separately for emerging spells (age ≤ 3 at origin)** and mature spells.
- **Failure criterion.** The hazard model ships only if its 10-year Brier beats comparator (a), with a PUMA-bootstrap CI excluding 0, **and** it is not worse on emerging spells. Otherwise the per-address function is the conditional KM alone.
- **Named-neighborhood check.** The urban-planner **pre-registers**, blind to outputs, expected onset and end years for about 10 ZIPs: 11211/11249, 11237/11206, 10002, 10026/10027, 11101, 11215, 11216/11225, 11102/11103, 11372, plus 11207/11208 as a late or never case. A hit is an onset within ±3 years.
- **Operator-site spot check.** Read the regime state and trajectory of the ZIPs of Lion's Milk, El Punto, Stone Street, Deux Luxe and Fazenda at each site's opening year.
- **Review.** Contrarian and statistician verdicts on §2 and §5 before ANSWER.md.

## 9. Top threats: what makes v0's number untrustworthy

1. **Measurement breaks masquerading as exits.** Candidates: the ACS 5-year overlap, the 2020 ZCTA redraw, the 2012 NAICS recode, ZHVI revisions, and the 2020 ACS collection anomaly. Any of these reshuffles ranks and produces synchronized fake exits; separately, the overlapping ACS windows inflate persistence. **Untrustworthy if** the exit count in a break year exceeds 2× the adjacent-year mean.
2. **Cutoff noise.** Durations are a function of the hysteresis band. **Untrustworthy if** the §2 grid moves the median by more than 50%, or if fewer than about 60 completed spells exist.
3. **Proxy and scale gap.** ZHVI is residential value, not commercial rent. A ZIP averages 20k–100k people, so a favorable corridor can sit inside an unfavorable ZIP. The answer is "how long you stay in the top third", which is relative, not absolute conditions. **Untrustworthy for a site** until the address-tier calibration shows agreement between address and ZIP spells (κ ≥ 0.4).

## v0 recipe (notebook, ZIP panel tier)

1. Build the balanced ZIP universe and the frozen ZIP↔ZCTA↔PUMA crosswalk. Assert that the ZIP count is constant across 1994–latest.
2. Pull the components from the warehouse (ZBP employment and 722 counts, ACS income and population, decennial 2000 population, ZHVI). Deflate income. Apply the NAICS 2012 crosswalk.
3. Compute within-year percentile ranks, then pillars (mean, re-ranked), then the equal-weight composite *c* (re-ranked). Keep the 2-pillar composite for 1994–99.
4. Apply the §2 hysteresis rule to derive spells: onset, exit, censored flag, and datable-onset or left-truncation entry age. Write the spell table.
5. Run KM with delayed entry (lifelines `entry=`). Report the median or RMST₂₀, IQR, censored share, the PUMA cluster-bootstrap CI, and the stock–flow check.
6. Run the hysteresis grid and leave-one-pillar-out. Print the table of medians and flag any movement over 50%. Chart exit counts by year, marking break years.
7. Fit k-means (k = 4) on data ≤ 2013 using levels plus 3-year changes. Assign all years, persistence-filter, and build the Markov matrix. Report 1/(1 − p_ff) against the KM median (AC-9).
8. Fit the discrete-time hazard (duration spline, lag-2 to lag-4 pillar changes, borough FE, PUMA-clustered SEs). Add year FE plus macro × exposure if the macro data exist, else mark BLOCKED. Chart year-level churn against macro (descriptive). Produce the ranked driver table and the accounting decomposition.
9. Attribute a cause to each exit, then run Aalen–Johansen incidence for the tenant reading (10-year conditional survival, cost-led incidence, rent-reset flag) and the owner reading (demand/supply-led incidence, appreciation exits). Run segments where the median count is ≥ 10.
10. Run the 2013-origin backtest against the median-for-all comparator and persistence: IPCW Brier at 5 and 10 years and Uno's C, split into emerging and mature. Apply the §8 failure criterion and print PASS or FAIL. Emit the named-ZIP and operator-site tables for the review stage.

## Contrarian verdict (2026-09-22)

**Verdict: AMEND.** The owner reading is close to REJECT as written. Read only QUESTION.md, this memo, PREREGISTRATION.md and the DATA-AUDIT "v0 feasibility" section; no data queried.

**Most likely way v0 is wrong: it answers "how long does a ZIP stay undiscovered", not "how long does a buyer's storefront enjoy good conditions".** Two of three equal-weight terms reward being cheap and under-restauranted. A spell therefore *ends* at the moment demand and prices arrive, which is when an operator actually buys. The buyer's decision point sits at or after the exit of the spell that supposedly describes them, so the headline duration describes the years *before* the buyer shows up. The pre-registration predicts this outcome in advance: 9 of 14 named ZIPs are "running in 2000, cost-led exit", and 11208 is favorable 2000–08 because demand has no income term. **Confirming data:** in the v0 run, (i) ≥60% of completed exits are attributed to cost; (ii) median ZIP real income or employment density in the favorable tercile sits *below* the citywide median; (iii) 11208 shows a spell covering 2000–08. Any two of these mean the composite measures discovery, not favorability.

**Second most likely: the headline is a supply-only rank-churn number presented as a three-pillar regime.** Per DATA-AUDIT, ZHVI/ZORI was never ingested, ACS is a single 2023 vintage, and LODES has no table. The audit's own fallback design uses a static 2023 demand level repeated across years plus cost only from 2019. Under that design, demand *cannot* change rank, so it cannot cause an exit. Cost switching on in 2019 is a definition break that produces synchronized fake exits (§9 threat 1, self-inflicted). The §5 driver table would then rank supply first by construction. Because the favorable share is fixed at about ⅓, mean duration ≈ stock ÷ exits is set by how fast ZIPs swap ranks. That swap rate includes CBP noise infusion (2007+) on small 722 counts. The duration is then partly a property of the measurement noise.

**Rulings on the four questions:**
- **(a) Demand must be a gate.** Compensatory averaging is exactly what lets "cheap + empty" substitute for "customers with money". It is not a weighting detail.
- **(b) Yes, build two composites.** "One spell set, two readings" (§6) is incoherent for the owner. Once a cost-led exit closes the spell, the owner is dropped from the risk set. A demand collapse that follows later is never observed, so owner durations are biased short, and they are relabeled "appreciation" to cover it. For an owner, cost is paid once at entry. It is an entry condition, not a state variable.
- **(c) Yes, the rank design manufactures durations.** A fixed ~⅓ share makes exits zero-sum, so one ZIP's entry forces another's exit. Citywide improvement or deterioration is invisible (§5 already concedes that level macro is mechanically null). Without a null model, the KM median cannot be told apart from the rank persistence of noisy, smoothed inputs. The ACS 5-year overlap and ZHVI smoothing *inflate* duration, and CBP noise *deflates* it.
- **(d) Other failure modes:**
  - **No criterion validity.** Nothing checks that "favorable" predicts any outcome a restaurant experiences.
  - **Left truncation defeats the headline.** Most gentrifying spells start before 2000. The 1994–99 panel is 2-pillar, a different object, so it cannot date a 3-pillar onset. The KM is then carried by the few mid-window entries, which are the ones most likely to be noise.
  - **Lagged-momentum driver.** Lagged pillar changes predicting exit (§5) is largely the momentum of the same series. It needs a momentum-only comparator before any driver is called a driver.
  - **D1 guardrail.** Lagged *supply* change must never be read as predicting *demand-led* exits. That reading would be the rejected retail→growth thesis coming back in.

**Required amendments (implementable as written):**
1. **Demand gate.** A ZIP-year is eligible for favorable only if the demand pillar percentile is ≥ 0.50. The composite is computed on eligible ZIP-years only. Report the favorable share per year, which is now free to vary, and the gate's pass rate.
2. **Spending-based saturation.** Redefine saturation as 722 establishments ÷ aggregate spending power, (resident population × real median household income) + (workers × a fixed real per-worker constant, stated). The head-count version is kept as sensitivity only. Pre-2009 income comes from linear interpolation between decennial 2000 (SF3, ZCTA) and the ACS 2005–09 vintage (midpoint 2007). If SF3 income is unavailable, the headline window starts at 2009, stated.
3. **Two spell sets.** OWNER composite = gated demand + spending-based saturation, with **no cost term in the state or the exit rule**. Cost enters only as an entry-price covariate: ZHVI percentile at onset, reported with each spell. TENANT composite = gated demand + saturation + cost, with cost measured as the **3-year change in the cost percentile** (renewal shock), not the level. Run KM, the grid and the backtest separately for each. Delete the §6 "appreciation exit" relabeling.
4. **Absolute check alongside the rank check.** For every spell, also report whether real demand growth ≥ real cost growth over the spell (a levels ratio, not ranks). Report the share of rank-favorable spell-years that fail it.
5. **Rank-churn null (placebo).** For each ZIP, simulate the three pillar series as AR(1) processes in percentile space using that ZIP's own estimated year-on-year autocorrelation and innovation variance, with no regime structure (1,000 sims). Apply the identical hysteresis rule and compute the KM median. Report the observed median against the null 95% band. **If the observed median is inside the band, the headline is withheld** and the answer is "durations are indistinguishable from rank persistence".
6. **Criterion validity against outcomes outside the composite.** Test whether favorable ZIP-years have lower subsequent restaurant closure hazard (DOHMH/SLA open→closed, 2010+) and higher growth in mean employees per 722 establishment (ZBP size classes) than non-favorable ZIP-years, conditional on borough. Neither outcome may appear in any pillar. No advantage means no headline.
7. **No composite until all three pillar panels exist.** If ZHVI, multi-year ACS or LODES are still not ingested, v0 must be titled "supply-density persistence", with no favorable-regime language, no owner/tenant split and no driver ranking. A cost pillar that switches on mid-panel is prohibited.
8. **Momentum comparator for §5.** Add a model with only the lagged change of the composite itself. A pillar counts as a driver only if it improves out-of-time Brier over that model. Add a rule to the notebook: supply-change coefficients are never reported against demand-led exits.
9. **Left-truncated spells are not dated with the 2-pillar panel.** Treat pre-2000 onsets as undatable, so they go to the lower-bound group. Report the headline KM **and** its share of all spell-years. If the headline covers < 40% of favorable spell-years, lead with the lower-bound group.

**What falsifies v0 (any one):**
- The observed KM median falls inside the amendment-5 null band.
- Favorable ZIP-years show no lower closure hazard than others (amendment 6).
- 11208 is favorable 2000–08 **and** ≥60% of exits are cost-led, which confirms that "favorable" means "undiscovered".
- The owner and tenant medians differ by < 20% after amendment 3. The split would then be cosmetic, and the question has one answer, not two.

## Statistician verdict (2026-09-22)

**Verdict: AMEND.** Read only this memo (including the contrarian verdict above), PREREGISTRATION.md and DATA-AUDIT.md, plus the data facts supplied on 2026-09-22: ZBP 722 by ZIP 1998–2023, ZHVI 2000→, ZORI ~2015→, ACS 5-yr ZCTA 2011→ (possibly 2009/10), LODES WAC 2002→ on 2020 blocks, FRED annual macro with no borough series, about 180 ZIPs. No data was queried. I endorse contrarian amendments 1, 3, 5, 7, 8 and 9. Where the two verdicts conflict, amendment S4 below settles it.

**Tier of claim.** The v0 headline is **descriptive**: the survival of a relative rank position at ZIP scale. The §5 hazard is **explanatory (conditional association)**. The §8 backtest is the only **predictive** evidence. Nothing in v0 is **causal**. The macro terms are conditional associations identified from about 3 episodes.

**Findings on the seven review points**

1. **Completed spells.** The favorable stock is about 55–70 units, a little above N/3 because the 0.60/0.70 band holds spells longer. ZIP ranks on ZHVI and density are very sticky (year-on-year ρ is plausibly 0.95 or higher). Plausible exit rates are therefore 2–6% of the stock per year. Exits confirmable over 2001–2021 come to about **30–85 in total**. The pre-registration expects most spells to be running in 2000, and the audit shows pre-2000 ZBP is only 1998–99. Only **~10–40 of those exits come from incident spells**, the spells with a datable onset. **Expect the ≥60 bar to fail for incident spells.** The bar must count completed incident exits in distinct units, after break-censoring (S5). Otherwise the rule is too easy to pass.
2. **KM with delayed entry.** `lifelines entry=` is correct only under quasi-independent truncation, and only if the entry age is measured on the same object as the duration. A 2-pillar onset dated from 1998–99 is a different object. (I agree with contrarian amendment 9.) Excluding undatable prevalent spells does **not** bias an incident-cohort KM. It changes the estimand: the headline becomes "spells that began 2001+". State that. Two further defects: (a) an exit needs 2 years below 0.60, so the last year that can be classified is **T−1 = 2022**, and a 2023 value below 0.60 is censored, not an exit; (b) KM on annual data has heavy ties, so use the discrete life-table hazard h_a = d_a / n_a, which agrees with KM, and report n_a at every age.
3. **PUMA bootstrap.** About 3 ZIPs per PUMA is too fine a cluster. Gentrification waves span adjacent PUMAs (North Brooklyn, Upper Manhattan), and break years hit every ZIP at once. PUMA clustering alone understates the width. Freeze one PUMA vintage (2010).
4. **Break years.** The §1 check (balanced universe, constant ZIP count) cannot see a *territorial* change: 11211 is present every year but loses 11249 in 2011. The "2× adjacent-year exits" test has almost no power at 2–6 exits a year. The ρ ≥ 0.8 re-basing check allows enough rank reshuffle near the threshold to create fake exits. The ACS 5-year overlap also inflates persistence. The fix is an identical definition over the whole window (S3, S4), plus a rank-shuffle test that needs no exits (S5).
5. **Macro.** §5's diagnosis is right: rank terciles null out level effects, and year FE are collinear with any NYC-wide series. The only identified object is **heterogeneous sensitivity**: exposure × macro, with year FE. It rests on about 3 episodes, so v0 may claim only a conditional association that is stable across leave-one-episode-out. It is not an effect and not a forecast input: the 2033 macro path is unknown, so any macro term is scenario-conditional. Timing note: CBP counts the pay period that includes 12 March, so the **2020 ZBP is pre-COVID** and COVID first appears in the 2021 data.
6. **Multiple testing.** The grid is robustness, not hypothesis testing. The risk is cell-picking. The hazard driver table and the macro interactions are real test families and need an adjustment (S9).
7. **Backtest.** At the 2013 origin: (a) the 10-year horizon (2023) cannot be classified; the maximum is 2022 (9 years). (b) Incident spells have a training age of 12 or less, so the training KM cannot supply S(a+10)/S(a) for a > 2 without extrapolation. (c) Censoring is purely administrative and ends before the horizon, so IPCW adds nothing. Use plain Brier. (d) About 60 spells and 10–25 events at 5 years means a Brier-difference CI excluding 0 is unlikely. **Pre-state that FAIL is the expected result, and that FAIL is not evidence the drivers are null.** Decile calibration cannot be computed on 60 spells.

**Required amendments (implementable as written)**

- **S1. Fixed unit geography.** Build `units`: every ZIP that appears in, or disappears from, ZBP or ZHVI inside 1998–2023 is merged with the ZIP(s) it split from, by areal overlap, for the whole window. At minimum these are 11211+11249, 10021+10065+10075 (kept, not dropped) and 11101+11109; the list is found automatically, not only from these. Sum counts. Take a household-weighted mean of ZHVI (single-ZIP ZHVI before the split). Detection assert: for each unit, flag any year with |Δlog(total ZBP establishments)| or |Δlog(ZHVI)| above 4 robust SD (MAD) of that unit's own series. Every flag must be explained or merged before spells are built. Report which units lack ZHVI in 2000 and are therefore dropped. If fewer than 150 units remain, say so in the headline.
- **S2. Headline cohort = incident spells.** A spell counts only if it began in 2001 or later with a non-favorable year observed before its onset (entry age 0). Spells running in 2000 are **not** dated from the 2-pillar panel. They go to a prevalent group, which is reported as annual exit hazard per spell-year, since age is unknown. Run the life-table KM with n_a printed. The last classifiable year is 2022, and 2023 is censoring only. Test the independence of onset year and duration with a conditional Kendall's τ (Tsai 1990). If |τ| is significant at 0.05, report the KM by onset period (2001–08, 2009–15, 2016+).
- **S3. Every pillar defined identically across the headline window.** Population comes from decennial 2000/2010/2020 on NHGIS 2010-standardized blocks, aggregated to units and linearly interpolated **for every year** (2021–23 carried forward). Do not use ACS population and do not hold 2000 population fixed. Workers: ZBP total employment for the whole window. LODES (2002→) is a sensitivity only. Cost: a single frozen ZHVI download, with its date recorded. Zillow revises its history, so this is also a stated leakage in the backtest. Supply: all-restaurant uses the **722 total**, which does not change at the 2012 recode. The crosswalk applies to segments only.
- **S4. Income: one construction over the whole window, or none.** ACS income starts in 2011. Interpolating backward from it to decennial 2000 (contrarian amendment 2) gives a hindsight-smoothed series before 2011 and a sampled, overlapping one after, which is a break by construction. Resolve it in this order:
  - (a) **Preferred.** Pre-flight and ingest the IRS SOI ZIP mean AGI per return, real (published annually for most years 1998→; confirm which years exist). Interpolate only the missing single years. Use it for the contrarian gate and for spending-based saturation over 2000→.
  - (b) Otherwise, **headline demand has no income** (population plus employment density). The gate and spending-saturation are then run on **2011→ only**, as a secondary headline labeled with its own window.
  - (c) Any ACS use (the secondary headline, the tenant composite) takes **non-overlapping vintages only**, dated to their release year and carried forward, never interpolated with future vintages. MOE is propagated with 200 draws of income ~ N(est, (MOE/1.645)²): recompute ranks and spells for each draw and report the share of exits that flip. More than 20% flipping means income is noise at ZCTA grain.
- **S5. Break-year detection and handling.** For each adjacent year pair, compute the rank shuffle 1 − Spearman ρ(c_{t−1}, c_t), per pillar and for the composite. Flag year b if its shuffle exceeds the maximum of the non-candidate pairs. Candidates: 2007 (CBP noise infusion), 2011 (11249 split, ACS entry), 2012 (NAICS), 2020/21 (COVID, ZCTA redraw), each ZHVI methodology year and every S1 flag. Keep the §9 exit-count test as secondary, recast as a Poisson test against the mean of the other years (p < 0.01). In the **break-censored sensitivity**, a spell whose 2-year exit window contains a flagged year is censored at b rather than exited. If the headline moves more than 25% under break-censoring, lead with the break-censored number and say why.
- **S6. Count gate (replaces "~60 completed spells").** A median may be stated only with **≥ 60 completed incident exits from ≥ 40 distinct units**, after S5 censoring, with the KM crossing 0.5 inside observed ages. Otherwise the headline is the **piecewise-constant annual exit hazard**, pooled over incident and prevalent spell-years in age bands ≤ 5, 6–10, > 10, and unknown (prevalent). It carries a Poisson/bootstrap CI and **no implied median**. RMST₂₀ is not allowed when the maximum incident age is below 20 (2022 − 2001 = 21 is the ceiling), so use RMST to the largest age with n_a ≥ 10. The stock–flow check compares the **observed** stock with RMST or the mean, never with the median.
- **S7. Spatial dependence.** Primary CI: a **spatial-block bootstrap** with 15–20 contiguous blocks (k-means on unit centroids, constrained to one borough), 2,000 reps. PUMA bootstrap is a secondary. Report both, and the headline uses the **wider**. Hazard model: SEs two-way clustered by PUMA and year, with a wild-cluster bootstrap on year (about 22 clusters). Moran's I (queen contiguity, 999 permutations) on per-unit (observed − expected) exits from the hazard model. If p < 0.05, re-estimate that unit-level cross-section as a spatial error model (PySAL `spreg.ML_Error`) and report both coefficient sets.
- **S8. Macro specification (H2).** A discrete-time logit on at-risk unit-years:
  - logit P(exit_{i,t}) = α_t + f(age) + β′Δpillars_{t−4→t−2} + Σ_k [δ_k E_{k,i} + θ_k E_{k,i}·t + γ_k E_{k,i}·M_{k,t−1}].
  - Exposures E are **fixed at 2000–02** and standardized: restaurant share of ZBP employment; office-type LODES share (2002–04); ZHVI percentile.
  - The **three pre-specified pairs** are E₁×(NY-MSA UR change), E₂×(COVID dummy, 2021–22 ZBP years), E₃×(MORTGAGE30US real change).
  - The E·t trend is mandatory. Without it, γ absorbs secular divergence, because the rate series trend down.
  - A γ may be reported only if it (i) survives Holm across the 3 tests and (ii) keeps its sign when each episode (2001–03, 2008–10, 2020–22) is dropped in turn.
  - Wording: "units with higher E exited more in years of higher M, conditional on year effects". Never "M causes exits".
  - H1 (year-level churn against macro) is a chart with no p-values. It uses NY-MSA series only; national series duplicate them.
- **S9. Multiplicity.** The headline cell (0.60/0.70, persistence 2, equal weights, incident spells) is **fixed now** and never re-chosen. Every grid cell is reported, and the >50% rule is max over cells |m_cell/m_head − 1|. Test families, each Holm-adjusted: the pillar-driver coefficients; the 3 macro γ; the 4 segment-vs-all differences. A pillar is called a "driver" only if it is Holm-significant, has the same sign in ≥ 9 of 12 grid cells, **and** passes contrarian amendment 8 (the momentum comparator).
- **S10. Backtest.** The origin is 2013 and the horizons are **5 years (2018, primary) and 9 years (2022)**. Use plain Brier, since there is no censoring before the horizon. Score only spells whose training KM supports age a + h, and list the excluded spells. For calibration, use the logistic calibration intercept and slope, not deciles. Uno's C gets a bootstrap CI. **Persistence (P = 1) is the floor every model must beat, the conditional KM included.** If the KM does not beat persistence, the per-address function is "no durability information beyond the current state". A secondary run pools origins 2011, 2013 and 2015 at the 5-year horizon, clustered by unit. Report the minimum detectable Brier difference, so a FAIL reads as "underpowered" or "null" and not as proof.

**Minimum conditions for stating v0's headline number (all must hold)**

1. S1 geography is frozen and every S1 flag is resolved. Pillars are identical across the window (S3, S4).
2. The S6 count gate is met. If it is not, the stated number is the annual exit hazard with its CI, not a median.
3. The contrarian rank-churn null (amendment 5) is rejected. Simulate latent AR(1) series and **re-rank every year**, so the null keeps the zero-sum tercile constraint.
4. The grid (S9) and break-censoring (S5) move the headline by no more than 50% and 25% respectively. Otherwise the grid or the break-censored figure is the answer.
5. The CI comes from the wider of the spatial-block and PUMA bootstraps (S7).
6. The wording carries its scope in the same sentence: *"Among NYC ZIP units that entered the top ~⅓ of a demand/saturation/cost rank composite in 2001–2021, the median [or annual exit hazard] was X (95% CI a–b). This is relative position, at ZIP scale, with residential-value cost. It is descriptive, not a forecast."* It is called predictive only if S10 beats persistence at 5 years.
