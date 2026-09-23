# RQ-003 — Data audit

Probed 2026-09-23, read-only (`duckdb.connect("data/loci.duckdb", read_only=True)`,
retried on lock conflicts from a concurrent peer session). Every input SEED.yaml's
constraints need, whether already in the warehouse or not. Warehouse row counts as of
this probe; `analysis.poi_first_seen` asof/current snapshot per its own
`last_snapshot_at`.

## Input table

| Pillar | Input | Source | Publisher | History | Grain | Status | Gap → ticket |
|---|---|---|---|---|---|---|---|
| OUTCOME (open/close) | Restaurant POI ledger — opening + closure lifecycle | `nyc_dohmh_restaurants` (anchor) + Foursquare closure signal, merged | NYC DOHMH / Foursquare | `analysis.poi_first_seen`, category=`restaurant`: 82,085 rows, `first_seen_on` 2003–2026 | address / point | **present but the closure column is severely under-detecting — see Q8 gate below** | GTM-232 (filter+ZIP rollup, existing) covers the rollup, not the detection gap; the detection gap itself is **RQ003-dohmh-closure-signal-wiring** (new) |
| OUTCOME (open/close, secondary lens) | SLA liquor-license intervals for restaurant-category licensees | `nys_sla_liquor_licenses` (active) + `nys_sla_inactive_licenses` (lapsed) | NYS Liquor Authority | `analysis.licence_interval` + `analysis.licence_event`, loci_category/category=`restaurant`: 22,306 / 21,755 rows | address (BBL-matched) | **present, but a naive expiry-window read is unusable as-is** — SLA licence terms run ~2 years, so `end_kind='expiry_observed'` fires on the licence's own renewal cycle regardless of whether the restaurant is still open (probed this session: naive 3/5-yr "closure" rate came back 83–86%, an obvious term-length artifact, not a real hazard). `licence_event` carries purpose-built `at_risk_5y`/`event_5y_business` fields (successor-checked) that are the correct path but were not re-verified this session (warehouse write-lock held by a concurrent peer ingest blocked a retry) | **RQ003-licence-hazard-cohort-build** (new) — build the cohort survival off `at_risk_5y`/`event_5y_business`, not raw `end_kind` |
| OUTCOME (open/close, tertiary lens) | DCWP legally-operating-business licence intervals, restaurant-adjacent categories | `nyc_dcwp_licenses` | NYC DCWP | `analysis.licence_interval`, source=`nyc_dcwp_licenses`: 72,451 rows total, loci_category=`restaurant` subset within the 22,306 above is mixed with SLA — **not currently separable by source AND category in one column read** | address | partial — present, same expiry-vs-closure caveat as SLA, and DCWP licensing only covers specific regulated activities (not every restaurant needs a DCWP licence), so this is not a restaurant census | folded into **RQ003-licence-hazard-cohort-build** |
| REPLACEMENT | Successor at the same storefront after a closure | POI ledger self-join (no source pull needed) | — | `analysis.poi_first_seen` has no direct BBL/premises key — only `location_key`, `lon`, `lat` | address / point | **missing the join, not the data** | **RQ003-replacement-join-build** (new) — spatial join `poi_first_seen` closures to the next-opening POI within a small radius at the same address, or to `analysis.storefront_tenure`'s next run |
| REPLACEMENT | Storefront activity-turnover ledger (LL157) | `nyc_dof_storefront_registry` | NYC DOF (Local Law 157) | `analysis.storefront_year` (414,884 filing-year rows) + `analysis.storefront_tenure` (50,565 premises, one row per premises with a full `runs_json` activity-run history, `n_turnovers`, `current_activity`) | address (BBL/premises) | **present and already does most of the hard work** (turnover counts, run-length, censoring flags) — D67/D119 built this for a different purpose (vacancy exposure) but it is directly reusable here | Grain caveat, not a gap: `activity_canonical` is DOF's coarse business-activity taxonomy (`FOOD SERVICES`, `RETAIL`, `EDUCATIONAL SERVICES`, …), not Loci's restaurant/bar/cafe categories — a "replacement" reads as "still food service" vs "other use" vs "vacant," never "still a restaurant specifically." Also **2019+ only** — cannot date a replacement for any pre-2019 exit |
| REGIME EXIT (spells + cause) | RQ-001 favorable spells, composite A and B-tenant, with dated onset/exit | RQ-001 v0.1 (`regime_durability.py`) | Loci (derived) | ZIP tier, 2000–2023 headline panel; completed incident exits: **A = 1, B-owner = 0 (excluded per SEED), B-tenant = 6**, out of 150 ZIP-units | ZIP (ZCTA-derived) | present for definition A; **B-tenant exit-cause attribution was never run** — RQ-001's executed notebook calls `attribute_exit_cause(spells_A, df)` only (`notebook.ipynb` cells 1290/1696), never on `spells_B_tenant` | **RQ003-b-tenant-exit-cause-attribution** (new) — one function call, already generic over `composite_col`, just never invoked for B-tenant |
| TENURE PROXY | Lot ownership signal (owner-occupied vs. tenant, approximate) | PLUTO `OwnerName`/`OwnerType`; DOF assessment-history owner fields | NYC DCP / DOF | **not ingested anywhere.** `analysis.address.ownertype` exists (327,308 of 332,041 addresses NULL; non-null values are DCP's public/private-ownership code — City/Mixed/Public-Authority/Other — not landlord-vs-owner-occupant) and comes from `pluto_vintages.py`, whose docstring states it reads only "the 8 columns this module reads" — `OwnerName` is not one of them. `nyc_dof_assessment_history` (registry `status: planned`, fields list in `registry.yaml`) also carries **no owner-name field** | tax lot | **missing** — the seed's "tenure inferred approximately from PLUTO/DOF lot ownership" input does not exist in any ingested source today | **RQ003-tenure-proxy-ingest** (new) — add `OwnerName` to the 8-column PLUTO read (cheap, same source already parsed) and land it in `analysis.address`; the proxy rule itself (e.g. OwnerName token-matches the operating business name → owner-occupied-likely) is a modeling decision for the notebook stage, not this ticket |
| SUPPORT | DOF Property Assessment Roll (assessed/market value, FY2010–2027, gap FY2020–22) | `nyc_dof_assessment_history` | NYC DOF | registry `status: planned`; staged parquet under `data/interim/rq002/dof_assessment/`, **not yet loaded into the warehouse** (no staging/analysis table) | tax lot | present as staged data, missing as a queryable table | **GTM-244** (existing — draft migrations 063/064 held pending peer-conflict confirmation) |
| DEPENDENCY | Address-tier trade-area calibration | — | Loci (derived) | not built | address | **missing — the hard blocker.** RQ-001's ZIP tier has too few completed exits (1/0/6) to support a DiD split by cause × definition × horizon; SEED.yaml explicitly defers the notebook to this | **GTM-226** (existing) |

## The Q8 gate — closure-detection completeness

**Verdict: FAIL, citywide and in every borough, by a wide margin.** Recorded closure
rates from the POI ledger (the primary, DOHMH-anchored source) are 15–90x below
every published benchmark at every horizon. RQ-003 cannot run on today's closure
signal in any borough.

### Recorded rates (this warehouse)

Cohort = restaurants first observed (`first_seen_on`) 2010–2021 (so a 5-year window is
fully observable against the current `2026-09` snapshot); `closed_on` within N years of
`first_seen_on` counts as closed; everything else is right-censored (`is_closed=False`
or closed later). Query: `analysis.poi_first_seen`, category=`restaurant`.

| Borough | n (2010–21 cohort) | 1-yr closure | n (2010–23) | 3-yr closure | n (2010–21) | 5-yr closure |
|---|---|---|---|---|---|---|
| Manhattan | 12,476 | 0.76% | 9,330 | 1.00% | 6,556 | 0.98% |
| Brooklyn | 8,221 | 0.62% | 6,295 | 1.03% | 4,781 | 0.63% |
| Queens | 8,420 | 0.63% | 6,159 | 0.88% | 4,580 | 0.41% |
| Bronx | 3,314 | 0.54% | 2,617 | 0.61% | 2,103 | 0.14% |
| Staten Island | 1,395 | 0.72% | 1,097 | 0.82% | 802 | 0.37% |
| (borough NULL, 28% of the citywide cohort) | 13,079 | 0.18% | 11,588 | 0.26% | 10,486 | 0.24% |
| **Citywide (named boroughs only)** | 33,826 | 0.66% | 25,498 | 0.92% | 18,822 | 0.61% |

### Benchmarks (published)

| Benchmark | Horizon | Rate | Source |
|---|---|---|---|
| BLS Business Employment Dynamics, "Survival of private-sector establishments by opening year" (accommodation & food services) | 1-yr | 14–17% closure (83–86% survive) | U.S. Bureau of Labor Statistics, Business Employment Dynamics, Table 7. Cited via secondary compilation: [Restaurant Failure Rate 2026 — DirectOrders](https://www.directorders.com/blog/restaurant-failure-rate), accessed 2026-09-23 |
| Luo & Stark, "Only the Bad Die Young: Restaurant Mortality in the Western US" (UC Berkeley) | 1-yr | ~17% closure (83% survive) | health-department permit data, San Francisco Bay Area, ~81,000 restaurants. [arXiv:1410.8603](https://arxiv.org/pdf/1410.8603), accessed 2026-09-23. **Closest methodological analog to Loci's own DOHMH-anchored approach** — both use health-inspection/permit rosters, not survey or POS-panel data |
| Parsa, Self, Njite & King (2005), "Why Restaurants Fail," Cornell Hotel & Restaurant Administration Quarterly | 1-yr / 3-yr cumulative | 26% / 57–61% closure | Columbus, OH cohort, 1996–1999 open dates, tracked through ~2003. [Ohio State News release](https://news.osu.edu/restaurant-failure-rate-much-lower-than-commonly-assumed-study-finds/), [journal abstract](https://journals.sagepub.com/doi/abs/10.1177/0010880405275598), [secondary summary](https://www.restaurantowner.com/public/Restaurant-Failure-Rates-Recounted-Where-Do-They-Get-Those-Numbers.cfm), accessed 2026-09-23 |
| BLS Business Employment Dynamics | 5-yr | 45–49% closure (51–55% survive) | Same BLS series as above, via DirectOrders compilation, accessed 2026-09-23 |

**Comparability caveats, stated per the SEED requirement:**
- None of these benchmarks is NYC-specific. Parsa is a single mid-size Midwestern
  city in the late 1990s; BLS BED is nationwide and covers the whole "Accommodation &
  Food Services" supersector (includes hotels, unlike Loci's `restaurant` category);
  Luo & Stark is Bay Area. A search for a NYC-specific published attrition series
  (NYC Comptroller/OSC, NYC EDC, DOHMH itself) did not surface one this session — the
  one candidate found (NY State Comptroller, "nyc-restaurant-industry-final.pdf")
  could not be read as text via the tools available this session (image/binary-heavy
  PDF) and was not pursued further given the session's data-audit-only scope; **worth
  a dedicated attempt in the notebook stage**, since an in-city benchmark would be
  the best comparison.
- Secondary-source aggregation (DirectOrders) was used for the BLS BED numbers rather
  than pulling BLS's own Table 7 directly, because this session is data-audit-only,
  not a full literature build; the specific 1-yr and 5-yr figures are corroborated
  across two independent BLS-citing compilations plus the independent Luo & Stark
  academic paper, which is why they are used as-is here.
- Even taking the **most conservative (lowest) published number** — 14% at 1 year —
  Loci's recorded 1-year rate (0.66% citywide, 0.18–0.76% by borough) is off by
  **18–78x**. The ±25% gate is not a close call in any borough or at any horizon.

### Verdict per borough

| Borough | 1-yr vs. 14–17% benchmark | 3-yr vs. ~39–61% benchmark | 5-yr vs. 45–49% benchmark | Verdict |
|---|---|---|---|---|
| Manhattan | 0.76% (18–22x low) | 1.00% (39–61x low) | 0.98% (46–50x low) | **FAIL** |
| Brooklyn | 0.62% (23–27x low) | 1.03% (38–59x low) | 0.63% (71–78x low) | **FAIL** |
| Queens | 0.63% (22–27x low) | 0.88% (44–69x low) | 0.41% (110–120x low) | **FAIL** |
| Bronx | 0.54% (26–31x low) | 0.61% (64–100x low) | 0.14% (321–350x low) | **FAIL** |
| Staten Island | 0.72% (19–24x low) | 0.82% (48–74x low) | 0.37% (122–132x low) | **FAIL** |
| **Overall** | 0.66% | 0.92% | 0.61% | **FAIL** — RQ-003 is out of scope everywhere until the detection gap is closed |

### Root cause: a real ~10x-too-low RQ-001 finding, refined here to a much larger, fully explained gap

RQ-001's `closure_validity_glm` (v0.1 ANSWER.md / METHOD.md) found ZIP-year restaurant
closure rates of **0.56% and 2.34%/yr** — about 10x below real attrition — and flagged
"closure-*detection* coverage" as the likely cause without pinning it down further.
This session traced the mechanism exactly:

**`analysis.poi_first_seen.closed_src` is populated 100% by Foursquare
(`foursquare:link`/`foursquare:key`) for `category='restaurant'` — 0% from DOHMH.**
Verified directly: every one of the 9,679 recorded restaurant closures in the ledger
carries `closed_src` in `{foursquare:link, foursquare:key}`; none carries a
DOHMH-sourced value.

This is not a missing source — it is an unwired one. `src/loci/sources/cities/nyc/
dohmh.py` already computes a well-reasoned closure proxy: DOHMH publishes no
open/closed status field at all (only a regulatory "closed by DOHMH" action, usually a
temporary health-code closure followed by re-open within days), so the adapter instead
flags an establishment `inactive` when its most recent inspection is more than 24
months old (`STALE_MONTHS`, derived from the empirical p90 inter-inspection gap x1.4)
— i.e., it has silently dropped off DOHMH's own rolling inspection cycle. That
`active`/`active_basis` verdict feeds the POI candidate-set / anchor-coverage
calculation (CONTEXT.md §7.1) but is **never surfaced as a dated closure event into
`poi_first_seen.closed_on`/`closed_src`**. Foursquare's delisting signal is sparser and
almost certainly itself understates restaurant closures (Foursquare's own restaurant
coverage and update cadence in NYC is not a census), which is why the *cohort-based*
rate computed this session (0.18–1.03%, 18–350x below benchmark) is dramatically lower
than RQ-001's *ZIP-year* rate (0.56–2.34%, ~10x below) — cohort framing is the
stricter, more apples-to-apples comparison against the academic/BLS benchmarks (which
are themselves cohort-based), and it exposes a bigger gap than RQ-001's
composite-conditioned ZIP-year framing did. **This is a detection-completeness
problem, not a real-world finding** — it says nothing about how often NYC restaurants
actually close, only that this warehouse is not yet observing it. It is concentrated
in the restaurant/food POI pipeline specifically (DOHMH is the anchor source for
`restaurant`/`cafe_bakery` only); other categories with different closure-detection
plumbing were not checked this session and should not be assumed to share the same
gap or the same fix.

**Fix path (not built this session):** wire `dohmh.py`'s `active_basis` verdict (or a
next-inspection-cycle-aware version of it) into `poi_first_seen` as a dated,
DOHMH-sourced closure event alongside the existing Foursquare one, so `closed_src` can
actually be `dohmh:stale_inspection` for restaurants. Given the 24-month staleness
window, this would date a closure to within roughly two years of the true event, not
exactly — state that resolution limit wherever the fixed rate is used. Tracked as
**RQ003-dohmh-closure-signal-wiring**; this is also the ticket SEED.yaml's AC-4 names
as blocking the RQ-003 parent alongside GTM-226.

## Status is one of `present`, `partial`, `missing`

Summary: **present** — replacement source (LL157 storefront tenure), RQ-001 spells for
definition A. **partial** — POI-ledger closures (present but failing Q8), SLA/DCWP
licence intervals (present but term-artifact-broken as read), replacement join
(data present, join not built), B-tenant exit-cause attribution (function exists,
not invoked), DOF assessment history (staged, not warehouse-loaded). **missing** —
tenure proxy (no source ingested at all), address tier (GTM-226).
