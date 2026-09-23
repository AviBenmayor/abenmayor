# RQ-002 — Answer

Scaffolded 2026-09-22 by `loci research new`. Filled 2026-09-22 from the executed
`notebook.ipynb` (v1, D141) — every number below is copied from that notebook's
printed output, not recomputed or rounded differently here.

## Answer (v1, provisional)

**Owner's question, verbatim:** "in greenpoint, when the massive housing developments
went up, how did it change the retail landscape? when did businesses move in? who
came before the demand came? who came after? did the number of businesses in the area
increase? did rent increase and by how much? when did the towers go up? what was the
area like before?"

**Honest fallback line (repeated below wherever a number could be misread as
causal):** 11222 grew more than the control(s) over the same window; the towers'
share of that growth is not identified with one treated ZIP, and the 2005 rezoning
and the towers cannot be separated because the towers came out of the rezoning.
Every number below is **descriptive**, none is a causal estimate.

### 1. When did the towers go up? — MED

Section 4's tower timeline (selected by point-in-polygon on ZIP 11222, not
`dev_pipeline`'s own neighborhood label) reconciles against the urban-planner's known
tower list as follows:

| Tower | Known units | Known date | Warehouse net units | Warehouse first TCO/CO date |
|---|---|---|---|---|
| One Blue Slip | 359 | 2018-08 | 360 | 2018-07-27 |
| The Greenpoint / 21 India St | 382 | 2018 | **589** (two filings: 140 + 449) | 2018-07-31 |
| Two Blue Slip | 421 | 2020 | 421 | 2020-01-30 |
| Eagle+West | 745 | 2022-12 | 745 | **2022-04-11** |
| Tower 77 | (520, 554) | 2023 | 554 | 2023-07-07 |
| The Riverie | 834 | 2025-26 | 834 | 2025-12-23 |
| Greenpoint Landing next phase | — | pipeline | 1,023 | — |
| TF Cornerstone, 2 Noble St | ~1,060 | pre-application | 1,060 | — |

The first year 11222 delivered a large batch of units (>500 in a single year) is
**2018** (the "first big TCO year"), stable at both the 500-unit and 1,000-unit
version of that rule (Section 5 sensitivity); at a 250-unit bar it moves back to
2010, because several 100–250-unit buildings cleared that lower bar years earlier.
Across all 32 New-Building jobs at ≥100 units, 9,946 units were delivered in total
(13,578 units across every non-withdrawn New Building job of any size in the ZIP).

Two things do **not** reconcile cleanly and are flagged, not resolved: (a) 21 India
St shows 589 warehouse units against a known 382 — two separate DOB filings on the
same block, and neither filing nor their sum matches 382, so this looks like a
different unit-count convention for one phase of the site rather than a data error
(GTM-250, below); (b) Eagle+West's first TCO among its three job filings
(2022-04-11) is about eight months **earlier** than its known "Dec 2022" completion
date, which is closer to the *last* of the three filings — first-occupancy and
final-completion are genuinely different dates for a multi-building project. Also
note: this dataset selects and counts towers by **unit count only** — `dev_pipeline`
has no stories/height field, so "≥10 stories" (the seed definition) could not itself
be verified from the warehouse; unit count is a proxy for it.

### 2. What was the area like before? — MED

From the panel's own pre-2005 numbers: in 2000, ZIP 11222 had a population of
**39,360**, median gross rent of **$667/mo**, and median household income of
**$33,578** (2000 decennial). The 1998–2004 business mix (raw NAICS, all
establishments) was dominated by grocery stores (418), full-service restaurants
(350), plumbing/HVAC contractors (326), limited-service restaurants (306),
carpentry contractors (270), local trucking (254), gas stations (248), auto repair
(232), single-family construction (226), and bars (202) — a working-class mix of
trades, light industrial/wholesale, and everyday neighborhood retail, not yet a
dining/shopping destination.

That NAICS mix is the warehouse's own evidence; the wider "what was the waterfront
like" picture is the urban-planner's sourced background, not a notebook computation,
and is reported here as context rather than a warehouse number: the 2005
Greenpoint–Williamsburg rezoning covered roughly 175 blocks of what had been a
waterfront of warehouses, lumber yards, vacant/underused lots, and municipal
facilities; the Newtown Creek and Meeker Avenue Superfund sites (including the
long-documented Greenpoint oil spill) sit along that same waterfront; Greenpoint's
retail base pre-rezoning was substantially Polish, concentrated on Manhattan Avenue
and Nassau Avenue; and NYC DCP's own accounting attributes roughly 2,203 net new
residents to Greenpoint–Williamsburg between 2010 and 2020 (public reporting,
e.g. Gothamist, cited by the urban-planner review — none of these four figures are
notebook computations). PLUTO land use of the specific waterfront tower lots before
development is not reconstructable from this warehouse (no PLUTO vintage reaches
before 2009, let alone 2005) — that is why this sub-answer is MED, not HIGH.

### 3. When did businesses move in? — MED

Well before the towers. The corrected food/drink series (fixing v0's broken
NAICS-2012 crosswalk, Section 3) shows continuous, un-interrupted growth from 81
establishments in 2005 to 134 in 2012 to 206 by 2018 — no cliff, no gap. The pre-2005
NAICS mix (above) already includes 350 full-service restaurants and 202 drinking
places by 1998–2004. Per the urban-planner's sourced review (not a notebook number):
new-wave entrants began arriving on and around Franklin Street from roughly 2000 on,
and by 2007 Franklin Street was being described in the Brooklyn Paper as the
borough's "new hot spot" — i.e., a decade or more before the towers, and years before
even the rezoning had fully played out.

### 4. Who came before the demand (pioneers)? — MED

Hand-verified named pioneers (urban-planner review, web-verified, 2026-09-22),
defined as early **new-wave** entrants — not simply "old businesses" — with old,
pre-tracking Greenpoint institutions reported separately as incumbents:

- Pencil Factory — ~2000
- Cafe Grumpy — 2005
- Five Leaves — 2008
- Paulie Gee's — 2010
- Achilles Heel — 2012
- Glasserie — 2013

Rule-based interval count across all 734 tracked 11222 food/drink/bar POIs: **99
certain** dated pioneers (first-seen year ≤2013) — this is a **lower bound**, with
[99, 318] the honest lower-to-upper range if every undated/censored POI turned out
also to be pre-2014 (not asserted, just the ceiling). 219 of 734 POIs (30%) are
undated and excluded from any dated claim. Incumbents — old Greenpoint institutions
that predate Loci's own tracking, reported separately and never counted as
pioneers — include Murawski (undatable, not in either feed), Warsaw, and Thai Cafe
(the latter two share a suspect first-seen date that looks like a dataset-ingestion
artifact, not a real founding date).

### 5. Who came after (followers)? — HIGH

Hand-verified named followers: Oxomoco (2018), a wine bar in the former Laundromat
space (2021), House at 50 Norman (2022), Wenwen (2022). Rule-based count: **353
certain** dated NEW_WAVE-FOLLOWER POIs (first-seen 2018 or later) — more than three
times the 99 certain pioneers. The large majority of dated, non-incumbent
food/drink businesses in 11222 first appear at or after 2018.

### 6. Did the number of businesses increase? — HIGH

Yes, in both the Loci-category count and the wider all-storefront count, in both
fixed windows, for 11222 and both controls — but 11222 was already outgrowing both
controls **before** the towers delivered, and kept a broadly similar margin
afterward:

| Outcome | Unit | 2013→2017 (pre) | 2018→2023 (post) |
|---|---|---|---|
| Loci categories | 11222 | 310→358 (+15.5%) | 363→422 (+16.3%) |
| Loci categories | 11385 (primary control) | 556→603 (+8.5%) | 622→659 (+6.0%) |
| Loci categories | 11105 (secondary control) | 257→283 (+10.1%) | 289→278 (−3.8%) |
| All-storefront | 11222 | 405→434 (+7.2%) | 434→503 (+15.9%) |
| All-storefront | 11385 (primary control) | 702→752 (+7.1%) | 759→774 (+2.0%) |
| All-storefront | 11105 (secondary control) | 310→317 (+2.3%) | 319→309 (−3.1%) |

The event-study log-gap (11222 minus primary control) confirms this was already
widening in the 2012–2017 lead window (+0.0195/yr), i.e. before the towers
delivered. In the placebo-in-space ranking, 11222 ranks **3rd of 7** on excess
growth against the primary control — an unremarkable rank, not an outlier. Reading
these together: **Greenpoint was already growing faster than its controls before
the towers arrived, and kept a similar-sized edge afterward — the towers' specific
share of that growth is not identified** by this design (single treated ZIP,
rezoning and towers not separable).

### 7. Did rent increase, and by how much? — HIGH residential / LOW–WITHHELD commercial

Residential rent and value rose in 11222, by more than the primary control, but
**most of the increase happened before the towers delivered, not after**:

- **ZHVI** (home value): 11222 rose $664,388→$1,063,743 (+60.1%) in the pre-window
  (2013→2017), then $1,098,914→$1,296,020 (+17.9%) in the post-window (2018→2023).
  The primary control (11385) rose +47.2% pre and +12.6% post — same pattern
  (front-loaded), smaller magnitude.
- **ZORI** (asking rent, only available 2015+, so no pre-window figure): 11222 rose
  $2,992→$4,141/mo (+38.4%) 2018→2023; the primary control rose $2,363→$2,980/mo
  (+26.1%) over the same span.
- **ACS median gross rent** (non-overlapping 5-year releases, with margin of error):
  11222 went $1,436±48 (2013) → $1,966±45 (2018) → $2,595±81 (2023); the primary
  control went $1,247±17 → $1,477±22 → $1,959±42. For reference, 11222's 2000
  decennial median gross rent was $667.

Tower-stock composition (new, larger, amenity-rich units entering the ZIP-level
sample) mechanically pushes these medians up on its own, independent of any
same-unit price increase — the two are not separable with ZIP-level ACS/Zillow data.

**Commercial rent is withheld from this answer.** No free commercial-rent time
series exists. The only commercial figure in the warehouse is DOF's FY2010
assessed **value** (not rent) per square foot: ~$156/sq ft in 11222 vs. ~$136/sq ft
in 11385, for a single fiscal year only (appendix only in the notebook, never used
above) — a paid CoStar/REBNY series would be needed for a real commercial-rent
answer (GTM-248, below).

### 8. Bottom line for a buyer — descriptive only, no causal claim

In Greenpoint, the retail run-up and the rent run-up both came largely with the 2005
rezoning and the broader Williamsburg-waterfront spillover, and most of it happened
**before** the towers physically delivered — the towers arrived into a market that
was already hot (business-count growth was already outpacing both controls in
2013–2017; ZHVI's biggest percentage jump was also in that pre-tower window). For an
operator or investor, the practical read is that the window to get in ahead of
demand was roughly **2005–2015**, not "when the tower delivers." This is a
descriptive read of one ZIP against imperfect controls, not a causal claim — the
towers and the rezoning cannot be separated in this design, and 11222's growth
margin over its controls is real but unremarkable in the placebo ranking (3rd of 7),
so treat "get in early" as a plausible, not proven, lesson.

## Confidence

**Overall: MED-LOW.** Reasons:

- **One treated ZIP.** This is a single-ZIP (11222) comparison against N=1 primary
  and N=1 secondary control plus a 4-donor synthetic control — there is no
  defensible standard error on any comparison above, and no causal estimate is made.
- **Controls are not screened from warehouse data for Queens.** `dev_pipeline` has
  zero rows for any western-Queens ZIP (11101–11109, including both the primary
  control 11385 and the secondary control 11105) — so neither control could be
  confirmed clean of its own tower construction from the warehouse; that screen
  rests entirely on the urban-planner's own web review, not on data in this
  warehouse.
- **The placebo rank is unremarkable.** 11222 ranks 3rd of 7 comparable ZIPs on
  excess growth against the primary control — not an outlier result.
- **~30% of food/drink/bar POIs are undated** and excluded from every pioneer/
  follower claim, which is why the pioneer count is reported as a [99, 318] range,
  not a point estimate.
- **Synthetic control weights are concentrated and slightly counter-intuitive**:
  11103 gets weight 0.638 and 11105 gets 0.362, with 11385 and 11104 at 0 — the
  fitted synthetic control leans almost entirely on two of the four donor ZIPs.

## Validation

| Check | Status | Result / ticket |
|---|---|---|
| Statistician review of v0 | RUN | FAIL (NAICS-2012 break, non-fixed windows, uninspected control choice); amendments applied in this v1 notebook. |
| Contrarian review of v0 | RUN | FAIL (same issues, plus reverse-causality risk and D139 supply contamination); amendments applied in this v1 notebook. |
| Urban-planner review of v0 | RUN | AMEND (tower list verified against known developments; pioneer/incumbent definition redefined; control ZIP 11102 replaced/dropped); amendments applied in this v1 notebook. |
| Re-review of v1 by the same three (statistician + contrarian + urban-planner) | TICKETED | **GTM-241** — RQ-002 v1 re-review (statistician + contrarian + urban-planner pass on this v1 notebook). |
| Citywide staggered event study (Sun-Abraham / Callaway-Sant'Anna over all NYC ZIPs 2012–2023, tower-unit completions as dose, with placebos) | TICKETED | **GTM-242** — Citywide staggered event study (would let "towers" and "rezoning" be separated at all — not possible with this single-ZIP design; owner ruling, not run this session). |
| Operator/ground spot-check of named pioneers and followers | RUN | Done via the urban-planner's own web verification of each named business's opening date (Section 4 named list, "hand-verified 2026-09-22"), not via a fresh independent check in this pass. |

Each row above is either `RUN` (with the result inline) or `TICKETED` (with a
GTM id, per the "Gaps → tickets" section below) — never silently skipped.

## Gaps → tickets

Existing tickets (cited as-is, not duplicated):

- Zillow ZHVI/ZORI ingest — **GTM-219**.
- ACS ZCTA panel — **GTM-220**.
- PLUTO vintages — **GTM-223**.

New tickets, all filed under `src/loci/tickets.py` and pushed to Linear 2026-09-22
as children of the RQ-002 parent:

- **GTM-239: RQ-002 parent** — the Linear parent issue for this research
  question, under the "Research questions" milestone, with every ticket below filed
  as a child of it via `src/loci/tickets.py`.
- **GTM-242: Citywide staggered event study** (Sun-Abraham / Callaway-Sant'Anna,
  all NYC ZIPs, 2012–2023, tower-unit completions as the dose, with placebo checks) —
  the only design that could actually separate "towers" from "rezoning"; not run
  this session (owner ruling, 2026-09-22).
- **GTM-240: Fix `zbp_naics.yaml` pre-2012 restaurant codes** — the shared
  crosswalk only recognizes post-2012 food-service codes, which breaks
  `analysis.zip_category_establishments`'s own food_drink bucket for 1998–2011 (this
  notebook works around it locally, Fix A/B, but the shared crosswalk itself is still
  wrong). Fixing it changes a shared analysis table — check the supply hash before
  and after, and announce the timing to peer sessions before landing it.
- **GTM-243: `dev_pipeline` has no Queens rows** — a source gap, not a bug;
  every western-Queens ZIP (11101–11109) is unscreenable for its own tower
  construction from this table, which is why both controls' "clean of towers" status
  rests on the urban-planner's web review rather than warehouse data.
- **GTM-248: Commercial rent history** — no free source exists; a paid
  CoStar/REBNY quote has been scoped but nothing has been purchased. Blocks sub-answer
  7's commercial half.
- **GTM-245: DOF assessment-roll full pull + square-footage coverage** — only
  the FY2010 partition downloaded this session carries the gross-square-footage field
  needed for a $/sq ft figure; FY2011–2013 are present but sqft-less.
- **GTM-246: DOF assessment roll FY2020–2022** — no Socrata table covers these
  fiscal years; NYC published them only as archived fixed-width rolls on nyc.gov,
  a three-year hole spanning the pandemic-era commercial real estate shock.
- **GTM-247: Add a Socrata app token for NYC Open Data pulls** — this session's
  DOF pull ran unauthenticated, slowing the per-fiscal-year pull from ~5 minutes to
  ~65 minutes.
- **GTM-244: Load RQ-002 staged parquet into the warehouse** — migrations
  063/064 exist only as `.sql.draft` files in this RQ's `drafts/` folder; they still
  need to be reviewed, numbered for real, and landed.
- **GTM-249: Registry `feeds` labels for `census_tiger_zcta` and
  `nyc_dof_assessment_history`** — both were set to the placeholder value
  `validation` in the registry and need a real value.
- **GTM-241: RQ-002 v1 re-review** — the statistician, contrarian, and
  urban-planner review that would upgrade this from "this run's finding" to a fully
  reviewed answer has not happened for v1 (only v0 was reviewed; every v0 fix is
  applied here, but the fixes themselves are unreviewed).
- **GTM-250: Resolve 21 India St unit-count discrepancy** — 589 warehouse
  units (two DOB filings) vs. a known figure of 382; needs a primary-source
  (DOB BIS/Now) check, not resolvable from this warehouse alone.
