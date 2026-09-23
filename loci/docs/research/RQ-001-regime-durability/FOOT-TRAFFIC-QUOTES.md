# RQ-001 — paid historical foot-traffic sources: quote comparison

**Scope.** GTM-227. Compare paid HISTORICAL foot-traffic sources for NYC at
address/near-address grain, reaching back toward 2010, as a candidate demand
pillar for RQ-001's regime-durability spells (which run from 2010 forward).
**QUOTE ONLY.** Nothing here was purchased, signed up for, or submitted as a
contact/sales form. Every price and history-start figure below is either a
published number, a public procurement record, or explicitly marked
`unverified` where only an AI-generated search summary made the claim and no
primary source backed it.

**Method.** Built on `docs/PAID-SOURCES.md` (rendered 2026-09-13 from
`src/loci/registry.yaml`) and `docs/competitor-capability-gaps-2026-09-22.md`
— both already carry deep foot-traffic vendor research; this note does not
duplicate their grain/NYC-coverage/licence findings, only adds the one
dimension neither document asked: **what calendar year does each vendor's
data actually start**, checked against primary vendor pages, university
library guides, Snowflake/Dewey marketplace listings and signed procurement
records. Searched via Tavily, 2026-09-23.

**Headline finding.** Every device-panel foot-traffic vendor checked —
without exception — has its earliest verifiable POI-level visit data
starting **January 2017 at the very earliest**, most commonly 2018–2019.
Several AI-generated search summaries claimed 2009–2014 starts (Foursquare,
Azira, PlaceIQ, a "Datarade" comparison); every one of those, checked against
its own cited source, conflated **company founding date** or **check-in
data** (a structurally different, self-selected dataset) with **modelled
visit-panel history**, and is flagged `unverified — likely hallucination`
below. No source, free or paid, was found with real device-panel or
card-panel visit history reaching to 2010.

---

## Comparison table

| Source | Grain | NYC coverage | History start (verified) | Refresh | Licence fit | Price status | RQ-001 fit |
|---|---|---|---|---|---|---|---|
| **Placer.ai** | POI (address) | National panel, no NYC share published; suppresses <~50 devices | **Jan 2017** (Snowflake Marketplace listing; Princeton library guide) | ~2-day lag, weekly Wed delivery | Bars redistribution/resale of data or derived data, bars AI/ML training — already flagged P1 in registry | $8,000–$31,000/yr on signed public contracts (verified); ToS quote-gated | Address grain matches; earliest verified start of any commercial vendor; still 7 yrs short of 2010 |
| **Advan Patterns Plus** (bought SafeGraph Patterns, 2023) | POI (address) | National, no NYC panel share published | **Jan 2017** raw weekly patterns per Dewey's partner page; Advan's own docs say Weekly Patterns+ "available starting Jan 1, 2018" — **discrepancy, unresolved**, ask on any call | ~1–2 day lag | CRE/site-selection a marketed vertical; already P1 in registry | Enterprise: quote-only, ~$10k+/yr floor. **Academic route: $3,600/yr** Dewey Researcher subscription (see below) | Same earliest-start tier as Placer; academic tier is cheap but likely research/publication-only, not a commercial-product feed |
| **Dewey Data** (academic reseller for Advan + SafeGraph + 28 other panels) | Passes through each partner's native grain | Passes through partner coverage | Passes through partner history (Advan Jan 2017 raw / Jan 2018 Weekly Patterns+) | Passes through | **Already P3-disqualified in `registry.yaml`** ("Dewey Data (Advan/SafeGraph reseller channel)" — $3,600/yr verified, "DISQUALIFIED" per the registry's own P3 table) — re-confirmed here, not relitigated | $3,600/yr Researcher; $25k–50k/yr institutional; a free 2-yr Research Data Grant exists but is a competitive annual award (5 teams/yr from 120+ university applicants in 2025), not a reliable procurement path | Cheapest way to *see* Advan/SafeGraph history, but the registry's existing disqualification (academic/publication terms, not a commercial-use channel) stands |
| **SafeGraph Patterns** (now sold to Advan; SafeGraph itself still sells Places + Spend) | POI (address) | Same panel as Advan post-2023 | **Jan 2018** launch of Patterns collection (SafeGraph's own Dec-2020 backfill release notes: "restates foot traffic activity from January 1st 2018 – present"); some public derivatives (Delphi Epidata) start Jan 2019 | — | Same product as Advan today; see above | N/A — product now sold under Advan's name | Confirms the Advan Jan-2018 figure independently; do not treat as a separate purchasable source |
| **StreetLight InSight (Bike-Ped)** | Census tract (coarser than address) | National by tract/segment; already P2 in registry at $42,888/yr verified | **Jan 2014** claimed by one AI search summary sourced from generic StreetLight marketing pages, not a dated primary statement — `unverified`, confirm on a call | — | Retail vertical marketed; already in registry | $42,888/yr verified (public contract) | Tract grain too coarse for address work regardless of history depth; not pursued further here |
| **Unacast** (merged into Gravy Analytics, Apr 2024; brand still active) | POI, trade-area | National; no NYC panel share | Panel collection **"began 2018"** per company blog summary; but a live Datarade SKU for the flagship trade-area product states **"3 years of historical coverage,"** i.e. a rolling window, not a fixed 2018 archive — the two facts do not describe the same deliverable | Product-dependent | Not yet in `registry.yaml` — **new candidate** | Not published; Datarade SKU implies enterprise-tier, no figure found | Even if the underlying panel reaches 2018, the sellable product may only ship a trailing 3-year window — verify which is actually quoted |
| **Veraset Visits / Movement** | POI (Visits) / raw device ping (Movement) | Already P2 in registry, $10k floor, no history previously recorded | One search summary describes panel build-up through 2018 with the **"official coverage window ... from the start of 2019"** — treat the 2019 start as the operative figure, the 2018 mention as ramp-up, not usable data | — | Real Estate solutions page markets site-selection use; already in registry | Least transparent price of anything surveyed — no converging figure | 2019 start, one year worse than Placer/Advan; raw-ping product carries the heaviest privacy/licence exposure already noted in the registry |
| **Pass_by (PassBy)** | POI (address) | Not NYC-specific; global, 1.5M+ store locations claimed | **2019** for Retail Store Visits, per Dewey's own partner page ("back to 2019"); PassBy's own blog separately claims "over five years" as of 2026, i.e. ~2021 — **the two PassBy-controlled sources disagree by two years**, flag for the call | Daily granularity added Feb 2026 | Not yet in `registry.yaml` — **new candidate**; ToS not fully checked, no discoverable resale prohibition (absence of evidence ≠ permission) | Not published; three-tier (Essential/Premium/Ultimate) with a "Test & Learn" 90-day trial mentioned | Weaker history than Placer/Advan even under its own best claim |
| **Near / Azira** (Near Intelligence → Ch. 11 Dec 2023 → relaunched as Azira) | POI, trade-area | 44 countries, 43M POIs claimed; no NYC figure | One AI summary claims panel "assembled in 2017" drawing on "a historical mobility-signal archive that extends back to roughly 2010" for "13T location signals" — the 2010 figure is **unverified — likely hallucination**; no primary Azira page states a data-start year | — | Already noted in registry Appendix as a name-change (Near→Azira), not yet priced | Not published | Do not rely on the 2010 claim; if pursued, the vendor must state a real data-start date in writing before any figure from Azira is used |
| **Gravy Analytics** (acquired Unacast Apr 2024; company founded 2011) | POI, trade-area | National | Foot-traffic *trend-report* product traces to **~2019** per one summary; company founding (2011) is unrelated to when visit-panel collection began — flag the same founding-date-vs-data-start confusion | Quarterly published trend reports | Not yet in `registry.yaml` — new candidate, largely superseded by the Unacast merger entry above | Not published | Same ~2018–2019 tier as everything else; the 2011 founding date is not a data-history claim |
| **Foursquare Visits (Movements)** | POI x period | Already P2 in registry, $10k floor | One summary claims "continuous coverage beginning in 2010" — **unverified, likely hallucination**: Foursquare's own Wikipedia timeline shows enterprise location products (Pinpoint) launching **April 2015** and the Movement/Pilgrim SDK in **2016**; 2010-era Foursquare data is **check-in data**, a self-selected, structurally different signal from a modelled visit panel, and the registry already flags this exact bias | — | Already in registry | Places API verified at $15/1,000 calls; Visits pricing unpublished | Do not use the 2010 claim; realistic start is ~2015–2016 at best, and that is check-in-adjacent, not a clean visit panel |
| **PlaceIQ (now Precisely)** | Movement data, various grains | National | One summary conflates PlaceIQ's **2010 founding** with "12+ years of continuous movement data" — **unverified, likely hallucination**. The one dated primary artifact found (COVID Exposure Indices, built on PlaceIQ data) covers **Jan 2020 – Aug 2021** only | Quarterly-updated per one page | Not in registry | Not published | Same founding-date-vs-data-start confusion as Azira/Gravy/Foursquare; no evidence of pre-2020 usable history |
| **Cuebiq / Spectus "Data for Good"** (academic route) | Device-level, aggregated for research | Global | Program itself running **since 2016**; specific mobility datasets referenced from **2017 onward** (Hurricane Laura evacuation study, 2017) | Ongoing | Academic/humanitarian-research licence only, via a data clean room — explicitly not a commercial redistribution channel | Free for accepted academic/humanitarian projects; competitive, application-based | Same ~2017 tier as Advan/Placer; free but the access model is a research grant, not a purchasable feed, and outputs are typically publication-bound |

---

## Per-source notes (evidence)

**Placer.ai** — already P1 in `registry.yaml` (`paid_placer_ai`) with full
grain/licence/price detail; this pass adds the history-start figure only.
- Data history: "Starting January 2017" — Snowflake Marketplace listing:
  https://app.snowflake.com/marketplace/listing/GZ2FQZJ4RYC/placer-ai-foot-traffic-patterns-data-united-states-retail
  (accessed 2026-09-23)
- Corroborating: Princeton University Library FAQ, "Historical data is
  available back to 2017" (for the sibling Advan product, cited for
  cross-check): https://faq.library.princeton.edu/econ/faq/423099 (accessed
  2026-09-23)

**Advan Patterns Plus / SafeGraph Patterns** — already P1 in `registry.yaml`
(`paid_advan_research_patterns_plus`).
- Advan's own docs: "Weekly Patterns+ are available starting from January
  1st, 2018." https://docs.advanresearch.com (accessed 2026-09-23)
- Dewey's partner page (Advan is the data owner, Dewey the distributor):
  "Weekly Patterns Plus reports ... with history back to January 2017."
  https://www.deweydata.io/data-partners/advan (accessed 2026-09-23)
- SafeGraph's own December 2020 backfill release notes (pre-Advan
  acquisition, same underlying dataset): "restates foot traffic activity
  from January 1st 2018 – present."
  https://docs.safegraph.com/changelog/december-2020-release-notes (accessed
  2026-09-23)
- These three primary/near-primary sources do not agree on Jan-2017 vs
  Jan-2018 for the *same* product across its ownership history — resolve
  with the vendor before relying on either date for a graduation test.

**Dewey Data** — already P3 in `registry.yaml`
(`paid_dewey_data` — check exact id in registry), booked
$3,600/yr verified and marked DISQUALIFIED. This survey does not overturn
that; it confirms the $3,600/yr Researcher-tier figure independently via
Dewey's own pricing page (https://www.deweydata.io/pricing, accessed
2026-09-23) and adds that a **free** Research Data Grant program exists
(https://www.deweydata.io/2025-research-data-grant-program, accessed
2026-09-23) — but it is a competitive annual award (5 teams selected from
120+ university applicants in 2025), not something to plan around.

**StreetLight InSight (Bike-Ped)** — already P2 in `registry.yaml`
(`paid_streetlight_active_transportation`). The Jan-2014 history claim came from one
Tavily AI-generated answer citing StreetLight's general marketing pages, not
a dated statement; StreetLight's core Metrics product is known to be
telematics/GPS-panel-derived and the multimodal bike-ped layer is a later
addition, so 2014 is plausible but **not confirmed** — ask directly if
pursued. Grain (census tract) is coarse enough that this is a low priority
regardless.

**Unacast / Gravy Analytics** — not currently in `registry.yaml`; new
candidates surfaced by this pass. Unacast merged into Gravy Analytics in
April 2024 (PR Newswire, https://www.prnewswire.com/news/gravy-analytics,
accessed 2026-09-23); the Unacast brand and site remain active in 2026. The
"2018 panel start" vs "3-year rolling window" SKU discrepancy is the key
open question — a Datarade-listed product
(https://datarade.ai/data-products/unacast-foot-traffic-data-trade-areas-data-where-consumer-unacast,
accessed 2026-09-23) explicitly states "3 years of historical coverage,"
which if literal caps usable history at ~2023-present regardless of when
the underlying panel began.

**Veraset Visits / Movement** — already P2 in `registry.yaml`
(`paid_veraset_visits`). History-start figure is new: one summary
describes 2018 as panel ramp-up with 2019 as the "official coverage window"
start (https://www.deweydata.io/blog/a-closer-look-at-veraset-visit-data,
accessed 2026-09-23, discusses methodology but does not itself state a
launch year cleanly — treat 2019 as the best available estimate, not a
verified fact).

**Pass_by (PassBy)** — not in `registry.yaml`; new candidate. Dewey's
partner page states Retail Store Visits go "back to 2019"
(https://www.deweydata.io/data-partners/pass-by, accessed 2026-09-23).
PassBy's own blog (a vendor-authored, non-Dewey source) instead claims "over
five years" of history as of a 2026 post
(https://passby.com/blog/foot-traffic-data, accessed 2026-09-23), which
implies a ~2021 start — two years later than Dewey's figure for the same
company. This internal contradiction should be resolved on any exploratory
call before quoting PassBy as a 2019-start source.

**Near / Azira, Gravy Analytics standalone, Foursquare Visits, PlaceIQ** —
see the `unverified — likely hallucination` flags in the table. In every
one of these four cases, a Tavily AI-generated answer produced a data-start
year (2010, 2011, 2010, 2010 respectively) that traced back — when the
underlying cited pages were actually read — to a **company founding date**
or a **structurally different data type** (Foursquare check-ins), not a
statement about when modelled visit-panel collection began. This is worth
recording explicitly: it is the exact failure mode ("a data gap wearing a
costume," per the project's contrarian-review standard) that would let a
future session cite "Azira has data back to 2010" and be wrong. No primary
Azira, Foursquare-Movements, or PlaceIQ page found in this pass states an
actual panel-collection start year; Foursquare's own Wikipedia-documented
enterprise-product timeline (Pinpoint April 2015, Movement/Pilgrim SDK 2016)
is the best real anchor available, two-plus years later than Advan/Placer.

**Cuebiq / Spectus** — not in `registry.yaml`; new academic-route candidate.
Data for Good program active since 2016
(https://cuebiq.com/blog/cuebiqs-data-for-good-program-where-weve-been,
accessed 2026-09-23); specific referenced datasets from 2017 onward. Access
is through a "data clean room" (Spectus) for approved academic/humanitarian
projects, not a commercial subscription — the closest thing to a free route
to 2017-era mobility data, but bound by research-use terms that would need
explicit confirmation before any output could support a paid product.

---

## Ranked recommendation

**Don't buy — for the stated purpose.** GTM-227 asks specifically for
history reaching **toward 2010**. Nothing surveyed here, free or paid,
academic or commercial, has verified device-panel or card-panel foot-traffic
history earlier than **January 2017** (Placer.ai, Advan/SafeGraph — tied for
earliest, both independently confirmed by primary or near-primary sources).
Every other candidate checked either starts later (2018–2019: Veraset,
Pass_by, SafeGraph's own backfill date, Unacast) or made an earlier claim
that did not survive a check against its own cited source (Azira,
Foursquare, PlaceIQ, Gravy standalone). RQ-001's spells run from 2010; no
purchase on this list moves that start date at all.

**If a purchase is wanted anyway**, for a different, narrower purpose —
calibrating or out-of-sample-testing the *post-2017* portion of whatever
demand pillar RQ-001 already builds from ACS/LODES/Zillow/IRS-income panels
(migrations 060–062, per the 2026-09-22 commit) — rank order would be:

1. **Advan Patterns Plus via Dewey's $3,600/yr academic Researcher tier** —
   cheapest way to see real POI-level visit data from the earliest verified
   start (Jan 2017/2018, contested). Already P3-disqualified in
   `registry.yaml`; that disqualification is about licence terms (research/
   publication-only), which matters less if the use is purely internal
   validation and never touches a customer-facing card — but that is a
   licence-terms judgment call for the owner, not a re-ranking made here.
2. **Placer.ai**, $8,000/yr verified floor — same 2017 start, real signed
   public-sector contracts exist, but the redistribution/derived-data ban
   already flagged in the registry means any RQ-001 output built on it stays
   internal-only by construction.
3. **Pass_by** — worth a from-scratch quote only if #1 and #2 are both
   ruled out; its own history claim is internally inconsistent (2019 vs
   ~2021) and needs resolving before it is worth more than a footnote.

**The honest bottom line, quantified.** RQ-001's regime-durability spells
span roughly 2010–2026 (16 years). No commercial or academic foot-traffic
panel reaches earlier than 2017. At best, a purchase buys the most recent
**~9 years (2017/2018–present), or roughly 55–60% of the study window** —
and only as a *validation/calibration* layer on the recent segment, never as
a way to extend or backtest the pre-2017 base rate the regime-durability
question is actually asking about. The pre-2017 two-thirds of the panel has
no paid-data substitute; Loci's existing free proxies for that era (MTA
subway ridership/turnstile entries, Citibike since 2013, the DOF/DOB filing
ledgers already in the warehouse) remain the only signal available for
2010–2017 and were not evaluated here (out of scope: this survey covers paid
sources only, per GTM-227).

---

## Five-question script for any sales call

1. **"What is the earliest calendar month your data actually has usable
   coverage for New York City — Manhattan and Brooklyn specifically — not
   your platform's global launch date? Is pre-2019 coverage full quality or
   backfilled/thin?"** (Targets the Jan-2017-vs-2018 discrepancy found for
   Advan/SafeGraph, and the fact that no NYC-specific panel share is
   published by any vendor surveyed.)
2. **"Has your underlying panel composition or methodology changed in a way
   that breaks comparability across years — the 2020–21 SDK/privacy changes
   in particular? Is there a documented correction factor for splicing
   pre- and post-change periods into one series?"**
3. **"What does a licence that permits INTERNAL research use only — never
   resold, never shown on a customer-facing product — cost and require,
   versus a redistribution/derived-data rider? Please quote both
   separately."** (Every vendor surveyed defaults to internal-use-only or
   explicitly bars derived-data redistribution; get the real number for
   each tier rather than assuming one covers both uses.)
4. **"For a location with fewer than your suppression floor (e.g., Placer's
   ~50-device minimum), what does the record look like — null, zero, or
   flagged? How does that floor behave differently in 2018 versus today, as
   your device panel has presumably grown?"** (Targets whether "no data"
   silently means "no traffic" versus "no panel," which the registry
   already flags as the single biggest interpretation risk in this
   category.)
5. **"What is the actual quoted price for Manhattan + Brooklyn POI-level
   coverage at our address grain — not a national enterprise platform
   licence — and does any academic or research pricing tier require
   publication, an NDA, or a restriction incompatible with a private
   internal deliverable?"**

---

## Sources not pursued further (scope note)

GapMaps, MyTraffic, PiinPoint, Locate.ai and Plotr (all named in the
2026-09-22 competitor-capability-gaps memo as claimants of foot-traffic
capability) were not re-surveyed for history depth here — they read as
platform/decision-tool vendors reselling or wrapping one of the panels
already compared above (most commonly Placer, Unacast, or an unnamed mobile
SDK aggregator), not as independent data sources with their own panel
history. If a future session wants their specific quoted price, that is a
separate, smaller lookup, not a new historical-depth finding.
