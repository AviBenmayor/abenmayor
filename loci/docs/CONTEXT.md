# Loci: Project Context

**Version:** 2.0
**Date:** 2026-09-16
**Supersedes:** CONTEXT.md v1 (2026-09-01), whose head stated a causal residential-growth thesis rejected in week one (D1). The v1 reasoning a later reader still needs is kept in the Superseded appendix, not deleted. **This charter also retires the SCOPE CORRECTION banner at the head of `docs/CHECKPOINT.md`**, which still describes hexes, an 80% prevalence rule, `analysis.hex_gaps` and "726 gap hexes". That banner is dead framing in the first file every session opens; delete it when this lands.
**Owner:** Avi Benmayor
**Scope:** New York City, Manhattan and Brooklyn only for the screen and its calibration (D48, D78). The data foundation covers five boroughs; `address-gaps` refuses any other borough.
**Status:** shipped instrument. 114 recorded decisions (ids run to D117) over 33 sessions. State lives in `docs/CHECKPOINT.md`, work in `docs/TICKETS.md`, research questions in `docs/QUESTIONS.md`.

---

## 1. Purpose

Loci shortlists addresses in New York where the market is most likely to act, and grades the evidence on each one. At the grain of a single address it measures what daily-needs retail is reachable on foot, how that supply compares to the Manhattan and Brooklyn baseline, what is filed with the city but not yet open, and, with a stated evidence grade, whether a candidate address is worth hand-diligence. It is a present-day instrument. It does not forecast appreciation, and a thin category is not evidence of unmet demand (§3).

Two modes, in order.

| Order | Mode | What it means | Status |
|---|---|---|---|
| **First** | **Take it** | The owner acts on a candidate address himself. | Primary. Owner ruling 2026-09-16. |
| Fallback | Help someone fill it | The owner sells or advises a third party into a candidate address. | Secondary, and the reason external customer work (AC-2) ranks below AC-1. |

Both modes use the same instrument and the same honesty. They differ in who carries the downside.

---

## 2. Who it is for

**First user: the owner, acting for himself.** Every delivery to date was to him or by him: the Lion's Milk and El Punto revenue pre-registrations (D91), the 379 Broome and Stone Street memos, the second El Punto site search (D117), the Gowanus cards and the first full allocator memo (D115). The instrument was built without a named external buyer.

The owner's own statement, 2026-09-16, governs this section:

> "I am not sure yet. Originally I built this without a customer in mind so I do need to do market research. I built this as a test to see if there is indeed a market opportunity that exists then to either go in to that myself or help someone else fill it. I think I need to reorient and validate this with a customer. In fact, almost model aside, I am very bullish on there needing to be a bathhouse in gowanus and I am not sure if I should try to tackle that myself."

**External segments are a market-research question, not an assumption.** `docs/GTM.md` §4 ranks four candidate buyers (tenant-rep brokers; lenders and feasibility shops; BID and SBS grant writers; 3 to 30-unit operators) and prices them against published competitor contracts. None of that rests on a conversation.

**The disclosure that governs §2:** no buyer has seen Loci and zero discovery calls have been held. `docs/GTM.md:7` (paraphrased) records that every price derives from a published competitor contract rather than a quote Loci has issued. GTM's own top risk names the fix: three discovery calls, one broker, one feasibility shop, one operator, one week (`docs/GTM.md:148`). That is AC-2, and under the take-it-first ruling it ranks below AC-1.

**Explicitly not a customer segment:** chains and franchisors. They buy models calibrated on their own store P&Ls, which Loci can never hold (`docs/GTM.md:72`). The 902-brand watchlist is a broker-facing lead list and a logo channel (D109, D113).

---

## 3. What Loci may claim today, and what it is for

**The claim earned today**, verbatim:

> "What we sell is cost of search, not better decisions." (`docs/GTM.md:17`)

Assembling fifteen categories, walk-network distances, borough baselines, seven filing feeds, zoning legality and character for one address takes an analyst days and takes Loci minutes, on auditable public data a buyer can re-derive.

**The guardrail**, verbatim, from the 2026-09-14 retrodiction (D88):

> "the screen ranks retail streets, not unmet demand" (`docs/GTM.md:19`)

Openings clustered where supply was already thick. Two results carry this, and the second is the sharper one:

| Result | Value | Reading |
|---|---|---|
| Own-category supply coefficient | +1.17 [0.87, 1.47] after NTA fixed effects **and conditioning on other-category supply** | Thickness predicts entry. Agglomeration or herding, not unmet demand |
| Restaurant own-category **gap** coefficient | **−0.89 [−1.44, −0.33], p = 0.0018, the only per-category coefficient to survive Bonferroni** | No restaurant within 400 m in 2023 predicted **fewer** restaurant openings. The strongest single piece of evidence against "thin equals opportunity" |

**The goal** is the owner's answer of 2026-09-16, verbatim: **"Decision value is the goal."** Cost of search is where the evidence stops. Decision value is what the project is trying to reach.

### 3.1 The gate, with dates

Loci may claim decision value only when it carries a survival or viability label that clears a pre-registered numeric floor on a named out-of-sample vintage, ratified by the `statistician` agent **before** the result is seen. This copies D111 exactly, where a Citi Bike growth feature was tested against a +0.005 delta-AUC floor set in advance and was recorded as a null.

**The source list is closed at four (source #4 admitted by D119 under its own floor and date, as the rule requires).**

| # | Source | What it is | Pre-registered floor | Date | Status |
|---|---|---|---|---|---|
| 1 | Foursquare pre-ledger closure panel | 54,190 venues that opened and closed before the snapshot (`docs/GTM.md:122`); raw ascertainment ~3% of closures, categorically non-random | An ascertainment-corrected survival label with out-of-sample AUC ≥ 0.65 against realized closures, the correction itself ratified before fitting | 2027-03-31 | Unbuilt |
| 2 | LL157 go-dark | The one survival-adjacent outcome the city publishes | ≥ +0.02 AUC over the same model without the score, sign stable across both outcome definitions | 2027-06-30 (one re-run, on the next full-universe filing) | **Failed once.** AUC 0.549 vs 0.535; sign flips (+0.42 / −0.20) |
| 3 | `analysis.address_observation` | The human ground-truth ledger. Per C5 it may **score** a label but may never be a feature in the screen, so it enters as a scoring and labelling source only | ≥ 200 observed storefronts across ≥ 60 anchors, and a pre-registered label reaching AUC ≥ 0.65 out of sample against observed closure | 2027-06-30 | 103 observations, 19 anchors (D107) |
| 4 | DCWP licence-status intervals (`w7w3-xahh`, full history; `analysis.licence_interval`) | Licence creation → first non-Active status, every status carried; the roster publishes no status-change date, so surrender/revocation are bounds and only expiry is observed; its vocabulary maps to one Loci category today (D119) | AUC ≥ 0.65 AND ΔAUC ≥ +0.02 over a category × borough hazard AND decile calibration gap ≤ 0.10 AND sign-stable across both closure definitions AND ≥ 200 events, 36 m, cohort-stacked 2016–2022 | 2027-06-30 | 72,451 intervals landed; identity join 0.9%; re-sourcing in wave two |

Pre-registration for the 2020→2023 rewind (entry ΔAUC ≥ +0.008 at 12/24 m with 2021-01-01 primary and 2020 as a declared pandemic regime arm; category-correctness +0.05 top-1, κ ≥ 0.10, eight licensed categories; time-to-close descriptive only) is recorded in D119; a pass on the 2020 cohort alone does not satisfy this gate.

**The stop rule, and it is revisitable.** If all three sources fail by their dates, then on **2027-07-01** Loci claims cost of search, and this charter amends itself on that date to say so. "Exhausted" means the dates passed, not that effort ran out. The rule reopens only when a **new** closure source is admitted to `src/loci/registry.yaml` by its own CHECKPOINT decision naming that source's floor and its date. A source added without a floor and a date does not reopen it.

**Survival and viability are therefore in scope as a gated commitment.** That is the owner's own label, 2026-09-16: "In scope as a gated commitment."

---

## 4. Method

### 4.1 The pipeline, present tense

Canonical order is in `docs/CHECKPOINT.md` under "How to resume". Every step is a `loci` subcommand; there are no loose scripts.

| # | Command | Module | What it does |
|---|---|---|---|
| 1 | `street-frame` | `geo/` | Refreshes the street-midpoint sampling frame from CSCL (D84) |
| 2 | `address-gaps` | `model/address_gaps.py` | Scores every MN+BK residential lot and street midpoint against per-category reach thresholds (D41). Continuous, no eligibility filter (D75) |
| 3 | `address-demand`, `pipeline`, `storefronts`, `age-fit apply` | `address_demand.py`, `dev_pipeline.py`, `storefronts.py`, `age_fit.py` | Demand class, development pipeline, storefront vacancy, age curves |
| 4 | `supply-ratio` | `supply_ratio.py` | Supply within 400 m network distance against the MN+BK baseline, per address and category (D73) |
| 5 | `address-access`, `transit-profile`, `citibike address-measures`, `dot-counts` | `address_access.py`, `address_transit_profile.py`, `address_bike.py`, `address_dot_context.py` | Movement context. Card context only, never a grade input and never the supply-ratio denominator (D76, D111) |
| 6 | `address-character build`, `address-legality build`, `storefront-pipeline openings` | `address_character.py`, `address_legality.py`, `storefront_pipeline.py` | Character label (D82); PLUTO zoning legality (D97, D104); filing lifecycle from seven feeds (D80) |
| 7 | `revenue` | `revenue.py` | Site-revenue model. Restaurant is the only category that passes its backtest (D91) |
| 8 | `recommend` | `recommend.py` | Evidence-graded card and allocator memo. Fail-closed: a card may not say *act* while any load-bearing claim is grade D (D74) |
| 9 | `forecast issue` / `forecast score` | `forecast.py` | Dated p_opening vintages and their realized outcomes (D92, D96) |
| 10 | `chains candidates / admit / auto-admit / render` | `chains/` | The 902-brand watchlist and its page (D109, D110, D113, D114) |
| 11 | `ground-truth` | `ground_truth.py` | Supervised browser verification at named anchors. Scores and verifies; never a screen feature (C5, D105) |
| 12 | `export-webmap` | `viz/webmap_export.py` | Publishes address state to the public map |

### 4.2 Definitions, and the three radii kept apart

**The daily-needs bundle** is fifteen categories defined in `src/loci/categories.yaml`, the single source of truth for OSM, Overture, NAICS and licence mappings. Two are demoted from headline claims by owner ruling (2026-09-14, D30 precedent): `tailor_repair`, whose measured true-coverage-hole rate is 37.5% [31.1 to 44.4] **and a floor**, and `hair_barber`. New categories enter only through the fail-closed expansion checklist (GTM-112).

Mirror: `docs/CATEGORIES.md`, generated by `loci gen-categories`, drift-checked by `tests/test_category_registry.py`.

**Walkable** is network distance along the pedestrian graph, never Euclidean. Straight-line buffers are wrong in NYC specifically: waterfronts, rail cuts, expressways and NYCHA superblocks create places where 300 m of separation is a 20-minute walk.

**Three different radii are in play and must never be conflated.**

| Radius | Where it applies | Source |
|---|---|---|
| **320 to 1200 m**, per category | The screen's reach thresholds and the gap flag. 400 m applies to 4 of the 15 categories | `src/loci/reach_tiers.yaml` (D41); candidate tier set 400 / 800 / 1200 |
| **400 m network** | The supply-ratio CLI default, and the catchment every card quotes | D73 |
| **649 m straight-line disc** | The Google coverage audit only. Google Nearby Search accepts a circle, so the disc radius is derived as the 800 m network threshold divided by NYC's measured 1.233 circuity | D53, `reach_tiers.yaml` validation block |

D90's 7.6% hole rate, the whole answer to §9.1, was measured at the 649 m disc approximating an **800 m** network threshold. It is not a validation of the 400 m readings the cards print. See §9.12.

**The spatial unit is the address**, a residential tax lot or a street midpoint. Hexes are frozen history (D38, D56). **The study period is the present**, plus the dated ledgers of §4.5's REALIZED layer. There is no growth panel in the live pipeline.

### 4.3 Access scoring

One multi-source Dijkstra per category on the walk graph, seeded from every POI in that category and cut off at the threshold. The persisted artifact is one row per (point, canonical business) pair within reach with its network distance, so walk-time, nearest-distance, spacing and coverage questions are queries, not recomputes. Fifteen traversals, not one isochrone per point. `src/loci/score/access.py`, `README.md:49`.

### 4.4 Cross-source dedup

The POI base unions several sources, so establishments recur, and overlap is denser where mapping is better. Dedup blocks candidates by cell and neighbours, then merges pairs within 40 m whose distinctive name tokens match, category-generic words and corporate suffixes stripped first. It is deliberately precision-first: in dense NYC blocks the nearest same-category POI is usually a different business next door, so proximity-only merging would manufacture fake retail gaps, the one error this instrument must never make. Cross-category dedup runs first as one global union-find, then per-category (D101: 12,928 merges, clusters down 3.7%). `src/loci/score/dedup.py`.

### 4.5 The four layers

*Carried unchanged from v1 §4.7. Approved by the owner 2026-09-14; decision D95.*

Four layers. Loci's claims sort into four layers, and every new claim should say which one it belongs to. MODELED: computed from public data, gap score, supply ratio, character, recommendations, the forecast ledger's p_opening. REALIZED: observed in the world, the first-seen ledger, closures, filings lifecycle, chain snapshots, DOT counts. SCORED: where modeled meets realized on a schedule, retrodiction, recommendation fill checks, forecast outcomes. LEARNED: what survived a test against realized data and travels, FINDINGS.md, carrying capacity, portability, planner verdicts. The scoreboard, not any single map, is the compounding asset.

### 4.6 Data sources

`src/loci/registry.yaml` is the machine-readable registry, drift-checked by `make check`: **44 sources classed**, universal 7, national 10, state 6, city open data 15, city-unique 6. Per-source geography, temporal coverage, refresh, cost, licence, portability and known bias live there, not here, so the drift check can catch an error. The post-raise wishlist generates separately into `docs/PAID-SOURCES.md` (D86: 35 sources, $301,565/yr, none of it spend today).

Mirror: `docs/SOURCES.md`, generated by `loci gen-sources`, drift-checked by `loci check-sources`.

Everything in the live set is free except Google Places. The call ledger stands at **8,963 of 9,113**; the D90 coverage validation alone was **5,985 calls, about $190**, against a stated budget of $100 to $500.

---

## 5. Binding constraints

Owner rulings and standing engineering rules. A session that wants to reverse one asks the owner; it does not reverse it in code.

| # | Constraint | Owner's words | Date | Decision |
|---|---|---|---|---|
| C1 | The unit of analysis is the address. No hex work. | "why do we keep talking about hexes?????" then "do it, no more hex work" | 2026-09-09 | D38, D56 |
| C2 | No eligibility gate. Every address stays in the universe. | "I 100% vehemently disagree with 'which addresses count at all'. If an address is truly in a super underdeveloped area, this would completely not count it." | 2026-09-13 | D75 |
| C3 | Two or more POIs at one address trigger a closure check before either is counted. | "any time we have 2 businesses in the same address, we should do a check if one of them closed down" | 2026-09-14 | D94 |
| C4 | The screen ranks retail streets, not unmet demand. No decision-value claim in any deliverable until §3.1's gate passes. A card may say *act* in the D74 sense of **worth hand-diligence**; it may never say an opening is likely to survive. | | 2026-09-14 | D88, D74 |
| C5 | `analysis.address_observation` verifies and scores. It may never be a feature in the screen. | | 2026-09-14 | D105 |
| C6 | Screen scope is Manhattan and Brooklyn. | | 2026-09-12 | D78 |
| C7 | Inventory before adding a table. Pivots and subsets are views; a new measure extends the grain. | | 2026-09-11 | D61 (34 objects to 26) |
| C8 | Spend budgets enforced in code, with call ledgers and a `--dry-run` path on anything that costs money or writes externally. | | 2026-09-13 | D86 |
| C9 | Supply-hash freeze discipline. A `poi_status`-changing write moves the shared hash; announce to peers first, and a declared "final" hash is a freeze. A new `sql/*.sql` is itself a hash-moving event. | | 2026-09-15 | D106 |
| C10 | The canonical order is re-baselined as one pass, currently on supply `ba944e18c57b`. | | 2026-09-15 | D112 |
| C11 | The supply hash proved clock-dependent and is pinned to a stored as-of in `analysis.supply_asof` (2026-09-15). `loci supply-asof advance` is itself a hash-moving event: announce it, then run the canonical order behind it. | | 2026-09-16 | D115 |
| C12 | Every question to the owner goes through buttons, not prose. | | 2026-09-14 | operating rule |

---

## 6. Validation gates and their latest results

"Licenses" is what the result permits Loci to say. "Does not license" is the sentence a reader will try to infer and must not.

| Gate | Test | Result | Licenses | Does not license | Decision |
|---|---|---|---|---|---|
| Coverage bias (P3) | Stratified Google Places sample on the address frame, 5,633 rows, 137 strata, 649 m disc, missing arm vs present control | 7.6% [6.5 to 8.8] of MN+BK MISSING flags are real coverage holes, about 40k of 523k; no income gradient distinguishable from zero | The gap is mostly real, not a data hole, **at an 800 m network threshold** | Bias-free measurement; validity at 400 m; `tailor_repair` and `hair_barber` demoted; fitness's apparent 35.6% hole rate was a type-map defect | D90 |
| Retrodiction, entry | Frozen 2023-01-01 screen ranking 12,572 dated 2023 to 2024 openings out of sample, NTA-blocked folds | AUC 0.866 [0.851, 0.881] vs 0.854 without the score; supply coefficient +1.17 [0.87, 1.47] after NTA fixed effects and conditioning on other-category supply | Cost of search | Decision value. The sign is agglomeration, not undersupply | D88 |
| Retrodiction, per category | Own-category **gap** coefficients, Bonferroni-corrected | Restaurant −0.89 [−1.44, −0.33], p = 0.0018, the only one to survive: no restaurant within 400 m predicted fewer restaurant openings | Nothing positive | Any reading of a thin category as latent demand | D88 |
| Legality vs herding | Planner's challenge that the lift is merely zoning | Legality sets the level (16% of addresses with no commercially zoned lot within 400 m saw a same-category opening vs 72% on a 20-lot commercial block) but absorbs 0.0002 of the +0.0126 AUC lift; other-category retail density absorbs about 48%. Own-category coefficient net of legality +1.18 [0.88, 1.49] | That the screen ranks inside the legal retail set | That its marginal information is unmet demand | D92 |
| Survival, LL157 go-dark | Registry go-dark, strict n = 12,713 / 1,074 events | AUC 0.549 vs 0.535; sign flips with the outcome definition | Nothing | Any survival or viability claim | D88 |
| Ground truth | Supervised browser check at recommendation anchors | 19 anchors: 12 supply_missed, 7 confirmed_gap, 103 observations, 5 warehouse POIs found permanently closed. Caveats: convenience at 410 m and laundry at 405 m sit inside measurement error of the 400 m cutoff, and 4 East 8th's 0.00x proved a status-coverage hole, not a gap | A P3 falsifier at named anchors | Catchment-wide validity at n = 19, or model integration | D107 |
| Age fit | F2 gate per category | bar and childcare carry curves; pharmacy was fitted and refused at every re-fit; **twelve categories have no curve at all** | Two demand curves | A demand curve anywhere else | D69, D71, D106, D112 |
| Revenue | Leave-one-ZIP-out backtest against baselines and a placebo | restaurant passes, ρ 0.82, v0.2 on supply `467cd5969200` at ε 0.6 → 0.4 (D91, commits 44fca62, e61c239); café passes only at ε = 0, which is the degenerate fit; nine categories fail placebo or baselines | A grade-C restaurant revenue band | Any revenue number outside restaurant. Economics is grade C restaurant, D elsewhere | D81, D91 |
| Forecast ledger | Dated p_opening vintages scored at 12 months | 2023-01 vintage AUC 0.899 vs 0.860 without the score | One scored data point | A track record. The 2026-09 live vintage scores 2027-09 | D92, D96 |
| Citi Bike activity growth | Pre-registered delta-AUC on two vintages against a +0.005 floor | −0.0004 (2023-01), +0.0000 (2025-01) | Context only | Any score, grade or ranking input | D111 |
| Operator prediction | Pre-registered rent and revenue bands sent to real operators | First scored datum 2026-09-16: El Punto rent $4,000/mo, a **hit** on the pre-registered $3,500 to $6,500 (central $4,800, log error 0.18). Sales, staff and orders still unanswered | One rent-band hit | A revenue result. The revenue half is unanswered | D91, D117 |

---

## 7. Acceptance criteria

Each states how it resolves and by when. Four of the six resolve on an outcome with a deadline (AC-1, AC-3, AC-5, AC-6).

### AC-1. The Gowanus bathhouse: admit the category, then pre-register the decision

The owner is bullish that Gowanus needs a bathhouse. Under the take-it-first ruling this is the project's first acceptance criterion. It is deliberately a case Loci cannot currently measure, and the first resolvable step is fixing that.

**Step 1, and the first checkpoint: admit `bathhouse_sauna` through the GTM-112 fail-closed category-expansion checklist.** Owner ruling 2026-09-16. The checklist's own pass or fail is the checkpoint: a named anchor source, a coverage-validation plan, a reach tier, and a Google type map. If the checklist fails, AC-1 resolves as "not measurable by Loci" and the question moves to hand analysis, which is a real resolution. A category that appears in `categories.yaml` without passing the checklist does not resolve anything.

**Why the warehouse holds nothing today.**

1. No bathhouse category exists. `day_spa` and `health_spa` appear only as Overture sub-tags inside `nails_beauty` (`src/loci/categories.yaml:169-170`), so a bathhouse that appears at all is counted as a nail or beauty POI.
2. The pipeline is structurally blind to it. GTM-192 found that of 40,691 one-or-two-location brand keys in MN+BK, all 22 with a not-yet-open filing enter at `liquor_application`: the pool is food-and-drink by construction, and **no gym, spa or padel club can appear in it at any threshold**.
3. The one bathhouse row in the repo is unchecked. `docs/CHAINS.md:355` carries the Bathhouse chain under `loci_category` restaurant, 5 locations, 2 new in 12 months, `sales_role: prospect`, `confidence: auto`, `decided_on` 2026-09-15. It sits under "Auto-admitted this snapshot (nobody has looked yet)". `decided_on` is not a verification date.
4. The D110 retrospective shows what the feeds can and cannot see for exactly this brand: Bathhouse's second site (Flatiron) was **invisible**, because every filing feed except DOHMH begins 2024-09-13 and press hits span 45 days; the third site (540 Atlantic Ave) **was** visible 86 days ahead through the SLA pending application, dated 2026-02-04 against a 2026-05-01 activation. The tier-3 `watch` row was designed for this case. Mink Padel, West Harlem, has zero rows anywhere.
5. A bathhouse is a destination amenity, not a daily need. The prevalence-gap screen works because daily needs are consumed often with near-zero willingness to travel. Applied to a category almost nowhere has, it flags the whole city. The right instrument is the trade-area method in Appendix A8.
6. C4 applies regardless. Even a correct thinness reading is not a viability statement.

**What Loci can say about Gowanus today**, from the card of record, `docs/recommendations/gowanus-core-2026-09-13.md`, 1,831 addresses, supply hash `767b28674e30`:

| Fact | Value |
|---|---|
| Categories at or above the MN+BK baseline | **8 of 15** (9 of 15 on the 2026-09-11 card; the difference is bank, see below) |
| Thinnest | pharmacy 0.00x, **tailor_repair 0.00x** (headline-demoted, 37.5% hole-rate floor, so read as unmeasured rather than thin), convenience 0.41x, hardware 0.78x |
| Verdict "do not act on this data" | 12 of 15, every one set by economics |
| Verdict "diligence" | 3: tailor_repair, hardware, restaurant |
| Homes within 400 m, median address | 3,646 |
| 18 to 34 share / renter share | 24.6% / 62.4% |

**Unreconciled, do not quote either value.** Bank reads **1.97x** on the 2026-09-11 card and **0.67x** on the 2026-09-13 card, on the same 1,831 addresses and the same supply hash `767b28674e30`; restaurant flips D to C in the same window and median household income moves 1.94x to 1.93x. No decision entry explains a three-fold move on a frozen hash. Both cards are cited; neither bank figure may be printed in a deliverable until a CHECKPOINT decision reconciles them.

**Step 2, at t0 plus two weeks: a hand-built trade-area sheet**, so the criterion says something to the owner now rather than in a year. Built by the Appendix A8 method, not the daily-needs screen: a stated travel-time catchment around one named Gowanus address, a hand enumeration of bathhouse, sauna and banya supply reachable inside it, a premium demand pool over that catchment, a floorplate and zoning feasibility gate from PLUTO, the ranking swept at 10 / 15 / 20 / 30 minutes, and the three A8 threats answered explicitly.

**Step 3: the pre-registration.** Registered in the recommendation ledger, dated and frozen before any lease or build decision.

| Field | Registered at t0 |
|---|---|
| Site | One named Gowanus address |
| Supply at t0 | Hand enumeration under `docs/ground-truth-protocol.md`, since no Loci layer holds it |
| Baseline | The citywide rate of new bathhouse, sauna and banya openings per catchment-year, enumerated by hand at t0. Every §6 row carries a "vs"; this is AC-1's |
| Prediction A | Number of new such venues opening inside the catchment within 12 months, and whether that **beats the baseline**. Predicting zero against a near-zero base rate resolves nothing |
| Prediction B | The owner's own operator diligence (rent, fit-out, licensing) confirms or contradicts the desk reading |

Rent comparables are hand-pulled. The restaurant revenue model is not used: §6 says it licenses no revenue number outside restaurant, and labelling an output an analogy does not make it a measurement.

**Resolution.** At t0 plus 12 months, re-enumerate under the same protocol, record it as an `address_observation` session, and write the outcome into the ledger whichever way it lands. AC-1 resolves on the **outcome against the baseline**, not on having filed the registration. **It does not decide whether the owner should build a bathhouse.** It decides whether Loci's method, extended to a category it does not currently carry, produces a statement that beats a base rate over twelve months.

### AC-2. External customer conversations, with written outcomes and a consequence

Three conversations: one tenant-rep broker, one lender or feasibility shop, one 3 to 30-unit operator (`docs/GTM.md:148`). Each produces a dated written record in `docs/` naming what was shown, what was asked, what price was named, and what the person said they would pay for. **Deadline 2026-12-31.** Secondary to AC-1 under the take-it-first ruling.

**Consequence branch, the twin of §3.1's stop rule.** If all three decline to pay at any price, the "help someone fill it" mode is closed for the segments tested, this charter records that, and `docs/GTM.md` §4's ICP ranking is retired rather than re-ranked. Three written no's is a result, not a null session.

### AC-3. A survival or viability label, or the stop rule fires

Either a label clears one of §3.1's three pre-registered floors on its named date, or on **2027-07-01** the stop rule fires and this charter amends itself to say Loci claims cost of search until a new closure source is admitted with its own floor and date. Both branches resolve AC-3; silence does not.

### AC-4. A card reaching *act* with economics above grade D

*Act* means **worth hand-diligence**, never *likely to survive* (C4). The governing rule is D74's fail-closed one: a card may not say *act* while any load-bearing claim is grade D.

The first full allocator memo already renders at **grade C**, on Gowanus-core hardware, `docs/recommendations/3004260001-2026-09-16.md` (D115, GTM-172 Done); the other three 2026-09-16 reports grade D with lead category convenience. So AC-4 is no longer "reach C"; it is **reach a state where economics is not the binding grade**. Today economics is grade C for restaurant only and D everywhere else, and the portability audit says an *act* grade needs a paid economics input in every city including NYC (D93).

Resolves when a card carries economics at C or better for a non-restaurant category, generated from a purchased or operator-supplied input rather than a model prior. **Deadline 2027-03-31**, tied to the P1 economics buy. The path from C to B is real P&Ls, collected under `docs/recommendations/predictions/`.

### AC-5. A forecast track record, and what it does not buy

Three consecutive scored vintages whose AUC beats the same model without the score. One is scored (2023-01, 0.899 vs 0.860); the 2026-09 live vintage scores 2027-09. Resolves 2027-09 at the earliest and fails if any of the three misses.

**Stated plainly: passing AC-5 alone re-proves D88.** Entry AUC measures where the market acted, not whether acting was right. AC-5 is a test of the instrument's ranking stability. It does not upgrade cost of search to decision value; only AC-3 can.

### AC-6. The operator predictions answered

The Lion's Milk and El Punto revenue pre-registrations (D91) resolve against the operators' real numbers. One datum is in: El Punto rent $4,000/mo, a hit on the pre-registered $3,500 to $6,500 (D117). Sales, staff and order counts are outstanding. **Deadline 2026-12-31**, after which unanswered questions resolve as **unanswered** and are recorded as such, which closes the criterion rather than leaving it open.

---

## 8. Non-identifications and closed dead ends

Do not relitigate these.

| Dead end | What was found | Decision |
|---|---|---|
| Retail gap causes residential growth | β = +0.069 (p = 4.7e-16), wrong-signed; pre-trend broken (β = +0.27); placebo clean | D1 |
| A thin category as latent demand | Restaurant own-category gap −0.89 [−1.44, −0.33], p = 0.0018, Bonferroni-surviving: no restaurant within 400 m predicted fewer openings | D88 |
| Business-level survival from open data | Not identified. Foursquare ascertains ~3% of closures; LL157 go-dark is a null; KM and Cox refused against a 48-event floor | D88 |
| Hexes as the spatial unit | Replaced by the address; hex tables are frozen history | D38, D56 |
| An eligibility gate on which addresses count | Removed by owner ruling | D75 |
| Citi Bike activity growth as a feature | delta-AUC null against a pre-registered +0.005 floor | D111 |
| Pharmacy age fit | Refused on its F2 gate at every re-fit | D69, D71, D106, D112 |
| Foot traffic and transit levels as a score input | Card context only; 65% of Brooklyn addresses read zero transit entries | D76 |
| DOT camera sidewalk counts screen-wide | Shortlist verification only | D85 |
| Headroom backtest | No predictive power | D68, superseded by D70 |
| Chains and franchisors as a paying segment | They buy models calibrated on their own P&Ls | `docs/GTM.md:72` |
| DNCI as the headline index | Superseded by the per-address reach ratio, supply ratio and graded cards | D41, D74 |
| Premium categories via government filings | All 22 not-yet-open filings enter at `liquor_application`; no gym, spa or padel club can appear at any threshold | GTM-192, D110 |

---

## 9. Threats to validity

### 9.1 POI measurement bias correlated with the finding
OSM and Overture undercount small businesses in lower-income and immigrant neighbourhoods, which are areas the screen flags. Now **tested rather than feared**: D90 puts the true-hole rate at 7.6% [6.5 to 8.8] with no detectable income gradient. Reduced, not removed, and measured at a different radius than the cards print (§9.12). The anchors that keep it reduced (DOHMH, NYS DOS, SNAP, DCWP laundry inspections, DOHMH child care, Medicaid pharmacy) are why it survived; any new category without an anchor reopens it.

### 9.2 Reverse causality
Supply thinness and site quality are confounded. Now **measured rather than assumed**: it is what D88 found, and it is why the claim stops at cost of search. §3.1 is the only route past it.

### 9.3 Revealed supply is not correct provision
The baseline is what NYC has. 1.0x is normal for this city, never correctly provisioned, and under-provision is correlated with race net of income (Meltzer and Schuetz). Every card carries this and must keep carrying it.

### 9.4 Self-reported and enforcement-driven sources
LL157 is self-reported and non-filing is invisible, so no vacancy near an address and nobody near it filing are the same observation; Tax Class 1 is 0.27% of MN+BK filings, so the rowhouse-base corner store is under-covered. DCWP laundry inspections are enforcement-driven, so a never-inspected establishment is indistinguishable from a real gap.

### 9.5 Survivorship in licence data
NYS DOS Appearance Enhancement is active-only; closed salons are absent entirely. Snapshot enrichment only, never a panel input.

### 9.6 Zoning artifacts
Mitigated by the address-level legality build from PLUTO (D97, D104), which replaced v1's manual top-20 inspection. If legality is wrong, the screen recommends sites that cannot legally host the use.

### 9.7 Co-located POIs double counted
Two POIs at one address may be one business and one closure. `poi_is_open` and `analysis.poi_colocation` remove evidenced-closed POIs (2,982, 2.13%) and flag unresolved pairs rather than collapsing them. Whether they should collapse is open (QUESTIONS D24).

### 9.8 Edge effects
Shoreline and borough-boundary addresses have artificially small reachable areas. The walk graph extends past the city boundary so out-of-city businesses are reachable where they genuinely are.

### 9.9 ACS margins of error
Wide at tract level and they propagate. Carried, not discarded. Share MOEs can exceed 1 on near-empty denominators, so gate on population before filtering on any MOE.

### 9.10 Redistribution and terms of service
StreetEasy content is internal-analysis-only. DOT camera frames, Google Places calls and Tavily enrichment were acquired under internal-use terms; Citi Bike carries attribution conditions. One pass over every redistribution clause before a paid deliverable leaves the building (`docs/GTM.md:138`).

### 9.11 Single-operator delivery
Every deliverable routes through one person's judgment and calendar. An asset and a concentration risk at once.

### 9.12 Radius choice is the live MAUP
v1 listed hex resolution as the modifiable-areal-unit threat. The hexes are gone; the radius replaced them. Three radii are in play (§4.2), the cards are read at 400 m, the coverage audit validated an 800 m network threshold through a 649 m disc, and **no 800 to 400 m sensitivity sweep has been run**. Two of D107's seven confirmed gaps sat at 405 m and 410 m, inside measurement error of the cutoff, which is what this threat looks like in practice. Until a sweep exists, treat any count that moves across 400 m as unverified.

---

## 10. Open questions

The full tiered set is in `docs/QUESTIONS.md`; these are the ones a session should know without opening it.

| # | Question | Tracked as |
|---|---|---|
| 1 | Does `bathhouse_sauna` pass the GTM-112 checklist, or is the owner's question outside Loci? | AC-1 |
| 2 | Why does Gowanus bank read 1.97x and 0.67x on the same hash two days apart? | AC-1, needs a decision entry |
| 3 | Which buyer segment pays first, at what price, and what if none do? | O11, AC-2 |
| 4 | What share of closures does each source ascertain, and is any survival curve recoverable? | M13, AC-3 |
| 5 | Does the 2026-09 forecast vintage keep its ranking power scored live in 2027-09? | T13, AC-5 |
| 6 | Does a radius sweep move the gap counts? No sweep exists. | §9.12 |
| 7 | Do planners confirm the legality-versus-herding decomposition, and does the 20-lot threshold survive? | T12, `docs/planner-packets-2026-09.md` |
| 8 | Should unresolved co-located POI pairs collapse or count as they are? | QUESTIONS D24 |
| 9 | Does the method generalise beyond NYC at a usable grade? Chicago, LA and Philadelphia reach D, C at best. | C3, `docs/PORTABILITY.md` |
| 10 | NYC TAM tops out under $1M. Consulting-funded, or a venture bet on city two? | `docs/GTM.md:132` |

---

## 11. Portability

NYC-first is a data decision, not a code decision.

- City-specific loaders live only in `src/loci/sources/cities/nyc/`, behind a common adapter interface, never referenced downstream of `staging`.
- Nationally available sources live in `src/loci/sources/universal/`.
- `src/loci/score/` and `src/loci/model/` contain no NYC-specific column names or assumptions.

Validated rather than asserted (D45, D46, D93). The registry carries `portability`, `feeds` and `degrades_to` on all 44 sources; `loci gen-portability` emits `docs/PORTABILITY.md` and `make check` fails on drift. Classes: universal 7, national 10, state 6, city open data 15, city-unique 6; 17 of the 44 are judgement calls and carry their uncertainty note. The most load-bearing portable input is the OSM pedestrian network, without which every network distance reverts to a straight line; the most load-bearing portable *signal* is a permit status date. Every calibrated constant is NYC-fitted, and an *act* grade needs a paid economics input in every city including this one.

The Citi Bike reader was proven portable by ingesting one real Chicago Divvy month (D111). That is the pattern: prove a reader on one month of a second city's data before designing around it.

---

## Appendix: Superseded

**A1. The causal growth thesis (v1 §0, §1.1 to §1.4).** The charter held that, conditional on density, income, transit and commercial zoning capacity, some places have materially less daily-needs retail than comparable places, and that this residual gap should predict subsequent residential growth. The residual was what made it an investment thesis rather than a description. Tested on 2013 to 2023 population growth it failed with the wrong sign, β = +0.069 (p = 4.7e-16): over-retailed places grew more. The placebo was a clean null, and the 2013 gap also predicted the prior decade's retail growth (β = +0.27), so parallel trends were broken and the gap marks neighbourhoods already in a development cycle. **The reasoning worth keeping:** retail follows rooftops, so any version of this project that ranks the bottom of a raw business-count distribution is producing a poverty map with extra steps. That is why the instrument grades rather than ranks, and why §9.2 exists. It is also why the D88 retrodiction was run at all: the same reverse causality reappeared in GTM clothing and was caught a second time.

**A2. Predictions P1 and P2 (v1 §1.4).** Both died with A1. P3 survived, was rewritten for the address frame, and is now §9.1 and the first row of §6.

**A3. Hexes (v1 §2.3, §4.1, §4.2).** H3 resolution 9, about 7,400 cells, ACS interpolated dasymetrically with PLUTO residential units. Chosen because hexes are uniform in area and city-agnostic. **The reasoning worth keeping:** the cost was that demographics had to be modelled onto them twice, tract to hex then hex to address, producing a step function at hex edges. A lot sits in exactly one tract, so there is nothing to apportion. Uniformity was not worth two layers of interpolation.

**A4. The DNCI (v1 §4.4).** A saturating per-category score combined by weighted geometric mean, tier weights 0.40 / 0.20 / 0.25 / 0.15. **The reasoning worth keeping, because it governs any composite:** an arithmetic mean lets a place with fifty restaurants and no grocery, pharmacy or laundromat score well, which is precisely the failure the project exists to detect. Only the geometric form punishes zeros. Retired as a headline because one composite hid which category was thin and on what evidence.

**A5. The supply model, the residual and the LODES panel (v1 §4.5, §4.6, §7.4).** Unused. LODES was never a good instrument here: it counts jobs not establishments, and LODES8 retro-allocated pre-2020 years into 2020 blocks at random in proportion to area, which places employment in parks and concentrates the error where development happened, that is, on the outcome.

**A6. The four-week phase plan and the deferred-decisions table (v1 §8, §9).** Obsolete after 33 sessions. Deferred decisions live in `docs/QUESTIONS.md`.

**A7. The v1 acceptance criteria (v1 §6).** Four blocks: A, a significant correctly signed growth coefficient surviving three robustness specs; B, a top-20 hex list with three genuine surprises and zero park edges; C, a working reusable tool; D, a communicable artifact. A died with the thesis, B was a hex artifact, C and D were substantially built and never formally accepted, which is why §7 states resolution conditions and dates instead of checkboxes.

**A8. Axis 3, the destination-amenity method (v1 §11), carried in full because AC-1 needs it.** Axis 4 (maturity curve and 2033 projection, v1 §12) is demoted; its one durable rule is that extrapolation from observed momentum is not the rejected causal claim, but it ships only if it passes a backtest, and its output is scenario bands rather than a point forecast.

Why the daily-needs screen must not be reused for a destination amenity:

| | Daily needs | Destination amenity |
|---|---|---|
| Trip frequency | daily or weekly | occasional |
| Willingness to travel | about an 800 m walk | 15 to 30 min drive or transit |
| Prevalence | common, the screen needs high prevalence | rare by nature |
| Right geography | walk catchment | travel-time catchment / trade area |
| Right screen | missing what peers have | demand pool minus supply, over the catchment |

The method, five steps:

1. **Bundle.** The named category and the destination-amenity family that shares its travel-for-it behaviour: spa and day spa, bathhouse and sauna, med-spa, padel, climbing, pilates and boutique fitness, golf and sports simulator. Each stays its own category, because catchment, demand target and site footprint all differ.
2. **Supply.** A POI layer outside the fifteen, plus Google and a manual web check. Ground truth is load-bearing here, not optional: these categories are new and open fast, so a "gap" is more likely a data gap than a daily-needs gap is.
3. **Demand.** A premium demand pool, not raw population: population weighted toward top income deciles, the category's target age band and college share, with the demographic match stated per category as the judgment it is.
4. **Catchment.** Drive-time union transit-time isochrones, default 15 minutes, **swept at 10 / 15 / 20 / 30** with every ranking reported under the sweep. Willingness to travel is assumed, not measured, so the sweep is the honesty.
5. **Feasibility.** Lot size, floorplate and a zoning district permitting commercial recreation or personal service, plus vacancy and industrial-conversion candidates. Without this the screen recommends sites that physically or legally cannot host the use, which is §9.6 in a new costume.

Deliverable: qualifying demand in catchment minus supply reachable in catchment, gated on a feasible site, ranked per amenity.

The three axis-specific threats, all of which AC-1 must answer:

- **Supply undercount is worse than §9.1** and concentrated in the newest categories. Every top site must survive a Google check plus a manual web check or it is presumed a data gap.
- **Willingness to travel is assumed.** The catchment radius is the single biggest lever; never report one radius.
- **Chain pipeline.** A gap may already be under LOI by a national operator. That is outside the data, and per GTM-192 the filings pool cannot see it for these categories at any threshold, so it is manual diligence per top pick.
