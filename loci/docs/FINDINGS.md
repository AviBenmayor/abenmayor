Findings register — maintained by hand; every claim cites its decision id and states its evidence grade. Regenerate the Notion mirror when this changes.

# What the model has learned so far — and what travels

*2026-09-14 · Manhattan + Brooklyn (D48, D78) · 281,842 scored points, two frames (D84)*

---

## 1. How to read this

**Four layers; a claim belongs to one.** *Modeled* — computed from public data. *Realized* — observed in the world. *Scored* — what the screen publishes. *Learned* — what survived a test against realized data. The learned column is short on purpose.

**Grades A–D are the recommend card's (D74).** A = validated against ground truth; B = anchored to a near-census registry; C = modelled, thin, or uncalibrated to local truth; D = no data exists at this grain. A verdict cannot say "act" while any load-bearing claim is D.

**Portable vs NYC-specific is about mechanism, not number.** Portable = a sign, an ordering or a design rule that should reappear in another dense city; NYC-specific = resting on a local dataset, statute or built form.

---

## 2. Findings

**F1 · Every address is in the universe; there is no eligibility gate.** All 173,407 addresses the ≥12-of-15 presence gate excluded were genuine gaps, none a served address it had mislabelled. Identity exact: count{ratio>1} = 3,012,430 = Σ n_missing, against 1,398,892 gated; gap addresses 452,491 → 626,145; the excluded set skewed outer-borough (QN 74,050 / SI 69,887 / MN 4), and the MN+BK top-50 clusters barely moved (Jaccard 0.926).
**D75 · B** (identity plus monotonicity) · **Portable** — *a screen for underdevelopment must not exclude the underdeveloped* · **Overturned by** the 143,973 cap-censored pairs distorting rather than bounding the ranking.

**F2 · Supply ratio vs baseline, not gap count — and laundry was withdrawn.** "Is there a gap" is the wrong statistic for a category present but thin. Gowanus core (1,831 addresses, median 3,646 homes within 400 m network): pharmacy 0.00×, convenience 0.40×, hardware 0.72×, **laundry 0.94×**, bar 5.58×. The red-team's laundry 0.28× reproduces only on the laundry-*gap* subset — circular, being selected on laundry's absence — so the lead was withdrawn.
**D73 · B** ratio, **C** haircut · **Portable** with its caveat: the baseline is revealed supply, so 1.0× means "normal for this city", never "correctly provisioned" · **Overturned by** the median-vs-aggregate estimator choice (15–50% apart).

**F3 · Eight daily-needs categories saturate; nothing clusters.** On 79 MN+BK ZIPs (Conley 3 km SEs, leave-one-ZIP-out sign stability ≥ 0.90, cross-category placebo), 2013 incumbent density predicts *fewer* net additions 2013→2023: childcare β −14.73 (t −2.10), clinic −13.57 (−4.77), laundry −10.82, grocery −8.79, plus tailor, fitness, nails, bank. Eight show no signal, café included (+6.20, t +4.83, but **fails the placebo**: restaurant density predicts café growth better than café's own).
**D70 · C** (ZIP grain; ZBP employer-only) · **Portable in design, not coefficients**: the unanimous-sign rule killed the log form — all 16 βs negative, the transform measuring itself · **Overturned by** a sub-ZIP panel.

**F4 · The economics are grade D, and the revenue model only partly fixes it.** The first real card said "do not act on this data" for 14 of 15 categories, all on economics — no cash-flow comps exist at any grain we can buy or scrape. Revenue v0 passed restaurant alone at C (ρ_oos 0.763, competition elasticity γ −0.25, *agglomerative*); nine categories are honestly "not modelled". v0.2 raised skill to ρ_oos 0.819 and cut every level 3–5× — Gowanus restaurant p50 $1,673,663 → $453,650, rent ceiling $11,158 → $3,024/mo — of which the median anchor alone is 0.41×, because census MEAN receipts are pulled up by large operators (Kings: mean $925,896 vs CBP median $262,924).
**D74/D81/D91 · D** as a class; C is a modelled category's ceiling · **Portable**: the grade architecture and the median-anchor correction · **Overturned by** three to five local P&Ls. Unconstrained, the elasticity fit went degenerate at ε = 0 in seven of nine categories: retail predicting retail, D1 again.

**F5 · Foot traffic is context, never a grade, never a denominator.** Against 99 DOT corridor points the headline is good — transit ρ +0.793, jobs +0.790, homes_400m +0.372 — and dies under stratification: Brooklyn-only transit is +0.561, CI [0.14, 0.83]; in the lowest tercile homes_400m (+0.686) beats transit; a binary any-station flag alone gets +0.547; 65% of Brooklyn addresses read zero. The disqualifier is endogeneity: ρ(transit, supply_400m) runs +0.536 to +0.236. By daypart, the AM count is ranked better by pm_peak than by am_peak — every window is ranked by station size.
**D76 · C**, context only, with a stated graduation test (≥100 non-corridor points, Brooklyn ρ ≥ 0.6) · **Portable** as stratification discipline · **Overturned by** DOT's VivaCity rollout.

**F6 · The first-seen ledger, and the 47.7% we must not pretend to know.** The dedup `cluster_id` is an input-order artefact — **0.00% of ids survive a byte-identical row shuffle** — so the ledger keys on a content hash of name, rounded coordinates and category. Backfill 2026-09: 227,548 locations, 52.3% with a real source date, **47.7% `backfill_censored`**, 0 observed; D80's `'gov_filing'` kind later cut censored 108,605 → 91,031.
**D79 · A** mechanism, **D** first-seen for the censored half · **Portable entirely**: censored rows return NULL, a skipped month is a permanent hole, a lagging last-seen is not closure · **Overturned by** nothing methodological — but Places Insights sells snapshots back to 2024-01, so the ledger is no moat.

**F7 · Government filings date a storefront eight months before it opens — for five categories.** Lease signings are private (ACRIS records ~400 leases/yr against 52,700 deeds), so the lifecycle is the filing chain: 232,667 filings across 7 feeds and 8 stages, reconciled to 135,912 business-at-BBL pipelines. Fit-out → first inspection **strict N=67, median 259 d**; **reconciled N=741, median 221 d**, but 92% of reconciled pairs are sole-pair-in-BBL so strict is the reference. **Liquor application → first inspection N=22, median 73 d.** Same-agency clocks are excluded: they measure the agency, not the store. Real for restaurant, bar, café, grocery and pharmacy; **structurally zero for the other 10**.
**D80 · C** — strict and reconciled side by side so the number cannot outrun its evidence · **Portable in structure, NYC in duration** · **Overturned by** wider coverage; until then a zero means "not tracked", never "nothing coming".

**F8 · Neighborhood character needed a planner before it was true.** A floor-area-and-payroll-jobs definition of "retail neighborhood" read ~0 retail_mixed for Brighton Beach Ave, Cortelyou, Graham Ave, Fulton St, Church Ave and Pitkin Ave — prewar ground-floor retail is not PLUTO `RetailArea`, and small-shop strips carry few payroll jobs. The revision added a zoning-overlay route at ≥20 commercially zoned lots within 100 m. Final: BK 34.7% retail_mixed; MN 58.2 with 15.5% corporate.
**D82 · C** — map colour and card context only · **Portable as a lesson**: a built-form proxy calibrated on modern construction erases prewar retail · **Overturned by** the threshold tested against a held-out corridor list.

**F9 · Chains: food and drink is the expansion, pharmacy is the contraction.** 121 curated brands, 2026-09 snapshot. **Food/drink ≈ 80% of confirmed openings.** Pharmacy chains net **−42** locations (Rite Aid alone −35), and the vacated boxes go to discount grocers, gyms and **LaundryBee** (~20 outer-borough laundromats on 20-year leases) — a contraction, not like-for-like replacement. Vital Climbing Gym has 4 locations and 0 net new, two acquired in 2021: a sales prospect, not a growth signal.
**D77 · C** curated, **D** detected (only ~60% carry any date) · **Portable**: never read a re-inspection date as a first-seen date; never conflate expanding with acquired-and-static · **Overturned by** the 2026-10 snapshot delta.

**F10 · DOT counts are calibration; cameras are a shortlist instrument.** 114 count points × 37 irregular rounds (2007–2026) × am/md/pm = 12,312 rows, so trends must use decimal years. Of 969 cameras, `isOnline` is the string "true" on all of them — it means published, not live. Median distance to the nearest count point is MN 739 m / BK 1,416 m, and within 400 m of a camera MN 79.9% but BK 22.1%: camera density is DOT's arterial geography, not footfall. Validation reads **N=0** — the first 183 frames were a Sunday evening against weekday counts.
**D85 · B** counts, **D** sidewalk sampling · **Portable**: the detector runs locally, counts only, no image leaves the machine; a camera is stock, not flow · **Overturned by** weekday sampling at the 15 cameras near a count point.

**F11 · The retrodiction: the screen ranks retail streets — and that closes the D1 arc.** Frozen at 2023-01-01 and scored against 2023–24 openings (12,000 lot addresses × 6 categories; logit, category FE, NTA-clustered SEs, NTA-blocked folds): **entry AUC 0.866 [0.851, 0.881] vs 0.854** for the same model without the score — an honest lift of **+0.0126**, with a spatially structured placebo at p95 0.8545 cleared. The supply coefficient runs +1.540 baseline → **+1.17 [0.87, 1.47]** with NTA FE *and* other-category supply, positive in every category; restaurant's own-category-gap flag is **−0.89 [−1.44, −0.33]**, surviving Bonferroni. The **LL157 go-dark test is a null**: AUC 0.549 vs 0.535 (12,713 rows / 1,074 events), the sign flipping with the outcome definition. Business-level survival is not identified: 228,455 Foursquare closures yield only 109 in-cohort events, implied S(24) 0.994 against a true ~0.75–0.80 → **~3% ascertainment, non-random by category**.
**Legality addendum (2026-09-14, D92).** Own-category supply predicts own-category entry at **+1.18 [0.88, 1.49]** after NTA FE, other-category supply **and present-day legal-capacity controls**, and at **+1.40 [1.05, 1.75]** inside the legal retail set alone. Legality sets the level — **16%** of addresses with no commercially zoned lot within 400 m saw a same-category opening against **72%** on a ≥20-lot commercial block — but absorbs only **0.0002** of the +0.0126 AUC lift, while **other-category supply absorbs ~48%**. Reading: *the screen ranks sites inside the legal retail set; it does not merely rediscover where retail is legal, and it still measures co-location, never unmet demand.* Caveats: `retail_area_400m` is partly post-treatment and the legality variables are present-day PLUTO. The live threat is explicit — half the score's marginal information is general retail density.
**The D1 arc.** D1 predicted residential growth from retail and was rejected (β = +0.069, p = 4.7e-16, wrong sign; pre-trends broken at β = +0.27). D88 puts openings on the *left* and measures the sign rather than assuming it: **+1.17**, **+1.18** net of legality. D1 resolved, not restated.
**D88 + D92 · A** entry design, **D** survival — untested, not absent · **Portable**: the sign, and more so the test design · **Overturned by** a survival outcome; the coefficient fits agglomeration and herding equally.

**F12 · Licence terms, not price, are what block paid data.** 35 wishlist registry entries, $301,565/yr booked (tier floors $213,200; verified subset $86,457). Dewey/Advan is **academic-only at any price**; Claritas forbids derivatives; Placer forbids redistribution; Data Axle and Esri are internal-use by default — riders are a line item, not a rounding error. This supersedes CONTEXT §3.5's $200–400 foot-traffic budget: every credible vendor is quote-gated.
**D86 · B** · **Portable in full**, the vendor landscape being national · **Overturned by** a negotiated rider.

**F13 · Nobody sells address-level gap logic, and the canonical metric was discontinued.** **Esri Retail MarketPlace is discontinued** — only 2017 data on 2010 geography survives, because e-commerce broke the local-sales model — so the industry's canonical retail-gap metric is unreplaced. Placer.ai has a **$31k signed public contract** (civic band $8–27.5k); Buxton is $35k build + $15k/yr; NYC SBS already sources its 24,900-storefront count from LiveXYZ. **Google Places Insights sells monthly POI snapshots back to 2024-01 at ~€3,300/mo** — 32 months older than our ledger, and the substitute to name before a buyer does.
**D87 · B** — every figure from a published contract or list price; no buyer has seen Loci · **Portable** · **Overturned by** the first three customer conversations.

**F14 · Two frames, and rank by density.** A screen built from residents cannot see a street nobody lives on yet. The street frame scores 50,199 midpoints at L = 100 m (the smallest round value at or above the 81.9 m median block face); within 50 m of a lot it reproduces that lot's lead **93.1%** of the time. But **4,874 points (9.7%) have no lot within 100 m** and are a different population — median gap_score 2.18 vs 1.27, 55% led by laundry. Separately, ranking by `homes_400m ÷ walkshed_km²` (the measured shed being **0.53× the nominal disc**) flips the top-50 almost completely (Jaccard 0.087) while the gap set stays byte-identical.
**D84/D83 · B** — both proved non-filtering by md5 · **Portable**: dividing by the nominal π·r² disc just ranks by `homes_400m` renamed · **Overturned by** the unset minimum member count.

---

## 3. What does not hold — the rejections are findings too

| What was tried | What happened | Decision |
|---|---|---|
| **Retail gap predicts residential growth** (the founding thesis) | Rejected, wrong sign (β = +0.069, p = 4.7e-16); pre-trends broken (β = +0.27): the gap marks neighborhoods already in a development cycle. | D1 |
| **Headroom predicts entry** | No out-of-sample skill: 1 of 14 categories beat persistence, and that one is a NAICS reclassification artefact. Headroom recombines population and count, adding nothing. | D68 |
| **Laundry as the Gowanus lead** | Withdrawn a day after issue at 0.94× baseline; the 0.28× behind it reproduces only on a subset selected on laundry's absence. | D73, D89 |
| **The first character pass** | Rejected by the planner before shipping: eleven named retail corridors read ~0 retail_mixed because prewar retail is not PLUTO `RetailArea`. | D82 |
| **The $2,500 site report** | Neither free (like a broker's study) nor SBA-accepted (like the $4,900 one), and 6–15% of a commission on a deal that may not close. | D87 |
| **The $-per-avoided-bad-site math** | D1's reverse causality in percentage clothing: Loci measures supply thinness, not site quality, and cannot separate "underserved" from "unviable". | D87, D88 |
| **p80 reach calibration and store-to-store spacing** | p80 fixes the gap rate at 20% per category by construction; spacing measures clustering, not service radius; any binary list is a knife-edge (±10% reach → Jaccard 0.41–0.58). | D34, D35, D39 |
| **The 2033 projection as a point forecast** | Failed its 10-year backtest: damped MAE 8.25 vs naive 9.35, beating naive on 56% of NTAs, with a −7.75 bias damping does not fix. | D25 |

---

## 4. What other cities can learn from New York

**Portable — take these.**

| Rule | Why it travels | Source |
|---|---|---|
| **The agglomeration sign is positive** | Openings go where same-category supply is already thick, within a neighborhood and net of general retail density (+1.17 [0.87, 1.47]; +1.18 net of legality). | D88, D92, D81 |
| **The legality-vs-herding test** | Check the screen is not rediscovering where retail is legal: condition on zoning capacity, then decompose the AUC lift. In NYC legality is a 40× *level* effect (16% vs 72% opening rates) yet absorbs 0.0002 of the lift; other-category supply absorbs ~48%. | D92 |
| **Lead-time structure of filings** | Fit-out → licence → first inspection is an ordering every permitting regime shares; durations are local. Exclude same-agency clocks. | D80 |
| **Ledger design** | Content-hash key, never a dedup cluster id; censored rows return NULL; a skipped month is a permanent hole; absence of a last-seen is not closure. | D79 |
| **The honesty-grade design** | A–D per section, verdict = min over load-bearing sections, "act" unreachable with any D — brute-forced so the property is proved, not asserted. | D74 |
| **The D61 warehouse rules** | Inventory before adding a table; pivots become views; new measures extend the grain; the warehouse holds exactly ONE run. | D61 |
| **Test-design rules** | Compare against the same model *without* the score; block folds by neighborhood; reject a unanimous-sign form; run a cross-category placebo. | D70, D81, D88 |
| **Vendor and licence map** | National, not local: Esri Retail MarketPlace discontinued, Placer $31k, Dewey/Advan academic-only. | D86, D87 |

**NYC-only — do not port these.** *Subway-shed demand*: the transit column splits MTA ridership evenly across entrances, and 59.7% of entries land where that split is least defensible (D76). *LL157*: a New York statute, and the only survival-adjacent outcome tested here — a second city loses the instrument that produced the honest null (D67, D88). *PLUTO floor area*: it drives the character index, capacity ceiling, density ranking and legality controls, and carries F8's modern-construction bias. *Bodega and laundromat density*: eight of fifteen reach values are owner-set norms, while Manhattan's revealed standard is 3–7× tighter (D41, D43).

**Anchor loss is the real second-city cost.** Seven of fifteen categories lose a near-census anchor (DOHMH, SLA, NYS DOS, SNAP) outside New York and fall back to raw Overture/OSM — and those anchors inflate NYC counts 2.8–8.0× against ZBP, so city #2 may be *closer to truth in count and worse in coverage* (D40, D45; verified on a live London bbox).

**The two questions a second city would answer.** (1) **Does the agglomeration coefficient replicate?** If a second dense city returns +1.18's sign at roughly its magnitude, the finding is about urban retail; if it reverses, it was about New York. It cannot be run here. (2) **Do lead times differ by permitting regime?** 259 d and 73 d are NYC agency latencies. If the *ordering* holds while durations move, F7's structure is portable and the durations become a per-city calibration.

---

## 5. Open research questions, ranked by what they would change

| # | Question | Would change | Pointer |
|---|---|---|---|
| 1 | **Closure ascertainment per source** — can a weighted hazard recover a survival curve from ~3%, non-random ascertainment? | Everything: survival is the only outcome separating agglomeration from herding. | **M13**, GTM-161 |
| 2 | **How much of the score's lift is own-category thickness rather than general retail density?** | Whether the screen's marginal information is category-specific at all — the legality test's live threat. | D92, **T11** |
| 3 | **Does transit stop being binary in Brooklyn?** | Whether foot traffic ever enters a grade section; VivaCity is the likely unlock. | **M12**, GTM-147 |
| 4 | **Which feeds make the 10 filing-blind categories visible?** | Until they land, a zero pipeline reads as "nothing coming" when it means "not tracked". | **T10**, GTM-152 |
| 5 | **Do recommendations get filled, and filled well?** First check: 15 × 'none' — the instrument, not the market. | The only prospective test the project owns. | D89, GTM-162 |
| 6 | **Is the AM/PM entry share a usable segmentation?** | Whether residential-vs-destination catchment becomes a screen axis or stays map colour. | **X7** |
| 7 | **Is character a control or a colour?** | Whether D82 graduates; D88 already collapsed `retail_index` to +0.191 [−0.198, +0.580]. | **X8**, GTM-154 |
| 8 | **Does a chain opening nearby belong on the card?** | The most legible single fact available, and the mistake D76 exists to prevent. | **D19**, GTM-148 |

Known defect carried in the open: a café with a DOHMH permit is counted twice — category assignment must precede per-category dedup (**GTM-153**).
