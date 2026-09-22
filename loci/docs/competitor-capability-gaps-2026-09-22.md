# Competitor capability benchmark and sourcing gaps — 2026-09-22

Research pass, not a decision. Benchmarks 15 location-intelligence / retail
site-selection competitors' own marketing claims against what Loci's 50
active + 36 wishlist sources actually cover. Existing registry entries are
cited by id, never re-priced. New candidates below are ones nothing in
`registry.yaml` (active or wishlist) already addresses.

---

## 1. Top line — what to add, public first

1. **FEMA / NYC Flood Hazard Mapper (free, public).** Closes a capability
   gap none of the wishlist's 36 entries touch: flood/climate risk, which
   GrowthFactor markets as a named feature ("Climate Intelligence"). NYC
   Open Data + FEMA National Flood Hazard Layer, zero cost, no licence
   friction. Smallest lift on this list.
2. **REBNY / Cushman & Wakefield / CBRE corridor rent reports (free,
   already identified, not yet ingested).** Already flagged in
   `docs/PAID-SOURCES.md` ("Free, or already ours" appendix) as a $0 win
   scoped exactly to MN+BK, but it is not in `registry.yaml` yet. This is
   the cheapest fix to gap (c) — rent — and should ship before any paid
   rent vendor (CompStak, Crexi) is considered.
3. **Data Axle Business API ($8–12k/yr, verified, already wishlist #6).**
   Not new, but it is the single highest-leverage paid line on the
   existing wishlist: it's the only verified-price source with real
   open/close dates for the ten categories (laundry, hair, nails,
   childcare, clinic, fitness, bank, hardware, convenience, tailor)
   structurally invisible to government filings — closing gap (d), which
   every competitor surveyed here claims to solve with a national business
   database Loci does not yet have.
4. **Esri ArcGIS Business Analyst Advanced ($5,200/yr, verified, already
   wishlist #10).** Cheapest way to answer the single most common
   competitor claim in this survey — demographic/psychographic targeting
   (Esri Tapestry, Spatial.ai PersonaLive, CARTO+Mastercard) — with an
   independent second opinion on the ACS residual Loci already computes.
5. **Placer.ai or Advan Patterns Plus (foot traffic, $8–10k/yr, already
   wishlist #1–2).** This is the capability every single competitor in
   this survey leads with, and it's the one gap Loci's own GTM memo names
   as unresolved: 65% of Brooklyn addresses read zero on the current
   transit-entries proxy (D76). Not urgent to buy today, but it is the
   capability gap most visible to a buyer who has seen a competitor demo.

Items 3–5 are not new discoveries — they restate the wishlist's own P1
ranking. The genuinely new findings from this pass are #1 (flood/climate,
nothing in the wishlist touches it) and #2 (a free fix already identified
but not shipped).

**Notion reconciliation (2026-09-22):** cross-checking the owner's 13
additional Notion Competitors DB entries (§4) against this ranking did not
change it. CenterCheck (§3) is the only new sourcing candidate the
reconciliation raised, and its own limitation — card-panel coverage skews
to ~600 major chains and is "weak on independents" per the owner's own
Notion note — keeps it below the five items above rather than promoting it
into them, since Loci's daily-needs categories are mostly independents.

---

## 2. Capability matrix

**Have** = in production today, address-grain, all/most of 15 categories.
**Partial** = exists but degraded (coarser grain, subset of categories, no
out-of-sample validation, or a free source identified but not yet
ingested). **Missing** = nothing in the active pipeline addresses it.

| Capability | Claimed by | Loci status | Evidence |
|---|---|---|---|
| Trade area / walk catchment analysis | all 15 | **Have** — Loci's core differentiator | Network-distance walksheds at 4 tracked radii, address-grain, all 15 categories, city-wide MN+BK (`docs/CONTEXT.md` §4.2, D132). GTM.md: "competitors deliver block-group rings or one subject property" |
| Supply gap / void / whitespace analysis | Placer.ai (Void Analysis), GrowthFactor (Void.AI) | **Have**, differently shaped | `supply-ratio` command, address-level, all 15 categories, continuous (no eligibility filter, D75). Placer's Void Analysis needs a branded panel signature and is effectively chain-level with no dataset SKU (GTM.md §2) |
| Development / opening-closing pipeline tracking | GrowthFactor (PlannedDev), most enterprise platforms | **Have** — Loci's other differentiator | 232,667 filings across 7 agency feeds reconciled to 135,912 business-at-BBL pipelines (D80, GTM.md) |
| Chain expansion / competitor tracking | RetailStat, Coresight, most platforms | **Partial** | 902-brand chains watchlist with per-brand expansion signals (`chains/` module) exists; no vendor feed, one detect snapshot so far (registry wishlist #23 RetailStat, #24 Coresight, gap f) |
| Foot traffic / visit counts | Placer.ai, Unacast, Pass_by, Azira, Advan, GrowthFactor (TrafficRX) — the single most common claim in this survey | **Partial** | `transit_entries_400m` + DOT camera counts (114 points) + Citibike are card context only, never a grade input (D76: 65% of Brooklyn addresses read zero). Registry wishlist #1–2 (Advan, Placer.ai), gap (a). Notion DB reconciliation (2026-09-22) adds three more claimants — PiinPoint (mobile location/traffic data), MyTraffic (10 m-accurate footfall, 18 countries + US), Geod (foot traffic as a portfolio-scenario input) — reinforcing this as the survey's most-claimed capability |
| Sales forecasting | SiteZeus, Kalibrate, Tango, GrowthFactor, Placer (implied via visits) | **Partial** | `revenue.py`: restaurant is the only category that passes its backtest (grade C); 9 of 15 categories shipped "not modelled" (D81). Notion DB reconciliation adds PiinPoint ("Marketmatch"), Locate.ai ("outperform the market by 15%," unverified), and Plotr ("Pulse Price") as further claimants; none of the three publishes a backtest |
| Cannibalization modeling | SiteZeus, Tango, Placer.ai, GrowthFactor | **Missing** | Not a Loci concept — Loci screens address-level daily-needs *supply*, not a single brand's store network; no per-brand portfolio model exists or is planned. Notion DB reconciliation adds PiinPoint (network simulations for expansion/renewal/closure) and Geod (portfolio-wide open/close/convert scenario modeling), both selling this explicitly as a multi-store network product, not a single-site feature — reinforcing that it's a different product surface than Loci's single-address screen |
| Consumer spend | SafeGraph Spend, Mastercard/CARTO, Earnest Analytics | **Missing** | Economics grade is D for 9/15 categories; only national CEX quintiles back the revenue model, no purchased or observed spend (gap b, registry wishlist #3, #15, #16). Notion DB reconciliation adds CenterCheck (card-transaction sales estimates) as a new paid candidate not yet in `registry.yaml` — see §3 |
| Demographics / psychographic segmentation | Esri Tapestry, Spatial.ai (PersonaLive), CARTO+Mastercard | **Partial** | ACS 5-yr tract estimates interpolated to address (income, age); no behavioral/lifestyle segments (gap h, registry wishlist #10 Esri, #27 Spatial.ai). Notion DB reconciliation: SiteSeer names its demographic/behavioral backbone as AGS, Environics Analytics, MRI-Simmons and PlaceIQ — none of the four are in `registry.yaml` |
| Rent comps / asking rent | CoStar, CompStak, Crexi, Kalibrate | **Missing** | No rent number in the active pipeline at all; feasibility gate "reasons about rent without a rent number" (`PAID-SOURCES.md` gap c). Free fix identified (REBNY/Cushman/CBRE corridor PDFs) but not yet in `registry.yaml`. Notion DB reconciliation adds three more competitors monetizing a rent number Loci lacks: RestaurantSiteFinder's rent calculator (revenue needed to hold rent <8%), Plotr's "Pulse Price" dynamic real-estate pricing model, and Accruent Lucernex's lease-administration platform |
| Property ownership / vacancy | CoStar, Reonomy, PropertyShark, CARTO | **Partial** | Free PLUTO/ACRIS ingested (ownership, no debt/contact); LL157 storefront registry is annual and self-reported, non-filing is invisible (gap g, registry wishlist #25 Reonomy) |
| POI truth / open-closed verification | LiveXYZ (implicit ground truth), most panel vendors | **Partial** | Multi-source corroboration + dedup (D101); closure ascertainment only ~3% via Foursquare; supervised `ground-truth` module exists but is verification-only, never a screen feature (gap e, registry wishlist #7 LiveXYZ). Notion DB reconciliation: Plotr's Enterprise-tier "store closure prediction" is a meaningfully different claim — Plotr claims to *predict* closures, Loci's module only *verifies/corroborates* status after the fact (D101) |
| Visitor origin | Placer.ai, Unacast (trade area), Azira | **Missing** | No mobile panel. LEHD LODES (`lodes_wac`, active) gives workplace commute flows, not shopping-trip origin — a workday proxy, not a substitute |
| Drive-time trade areas | Esri, Alteryx, CARTO, Kalibrate, Tango | **Missing by design** | Loci is walk-network only (NYC daily-needs framing); no drive-time isochrone capability exists or is planned — a deliberate scope choice, not an oversight. Notion DB reconciliation adds Maptive (Drive Time Polygons) and Geod (drive-time trade areas with traffic-pattern weighting) as further claimants — does not change the scope decision |
| Climate / flood risk overlay | GrowthFactor ("Climate Intelligence") | **Missing** | Nothing in `registry.yaml` (active or wishlist) touches flood zones; free FEMA/NYC layer identified in this pass (§3 below) |
| Co-tenancy / tenant-mix fit recommendation | Placer.ai (Void Analysis ranking), CARTO | **Missing** | Chain watchlist tracks who is expanding, not who fits next to whom; no recommendation-engine layer exists |

**Rough count:** 3 Have (trade area, void/gap, pipeline — Loci's genuine
differentiators, and both flagged explicitly in GTM.md as the
provable-today claims), 6 Partial, 6 Missing, of 15 capabilities checked.

---

## 3. New sourcing candidates (not already in `registry.yaml`)

Public/free checked first per capability; paid only where no free option
exists.

### Flood / climate risk (new gap — nothing in the wishlist addresses it)

- **NYC Flood Hazard Mapper** (NYC Department of City Planning) —
  free, public, interactive. Coastal flood hazard + FEMA layers for NYC
  specifically. https://www.lisresilience.org/resource/nyc-flood-hazard-mapper
  · grain: parcel/area polygon · NYC coverage: full · freshness: periodic
  DCP updates · licence: public agency data, no redistribution
  restriction found.
- **FEMA Flood Map Service Center (National Flood Hazard Layer)** —
  free, federal, authoritative source of record. https://msc.fema.gov ·
  grain: flood zone polygon · coverage: national, NYC included ·
  freshness: FEMA map revision cycle (years, not real-time) · licence:
  public domain federal data.
- **nyc-flood-data (GitHub, mebauer)** — a maintained aggregation of NYC
  Open Data flood-related datasets (hurricane evacuation zones, etc.) if a
  single ingest point is preferred over hitting FEMA/DCP separately.
  https://github.com/mebauer/nyc-flood-data · unofficial but sourced
  entirely from NYC Open Data, so licence follows the underlying NYC Open
  Data terms.

No paid alternative was searched — this is exactly the kind of capability
a free federal/city layer already answers fully; a paid climate-risk
vendor (e.g. First Street Foundation, not evaluated in depth here) would
only be worth it if property-level insurance-grade risk scoring is later
needed, which is out of scope for a retail-gap screen.

### Rent comps (gap c) — free option already found, just not shipped

No new candidate — `docs/PAID-SOURCES.md`'s own appendix already names
REBNY Manhattan/Brooklyn Retail Reports and Cushman & Wakefield MarketBeat
Manhattan Retail as free, scoped exactly to MN+BK, and explicitly says
"take these regardless of the raise." They are not yet in `registry.yaml`.
This is a shipping gap, not a research gap — flagged in §1 above rather
than re-researched here.

### Co-tenancy / tenant-mix recommendation and cannibalization modeling

No data-source candidate applies — both are modeling capabilities built on
data Loci already has (canonical POI supply, chains watchlist, address
gap scores), not missing data. Out of scope for a sourcing search; would
be a `data-scientist` / product design question, not a registry addition.

### Visitor origin

No free substitute found beyond LODES (already active, workplace-commute
only, not shopping-trip origin). Every source that measures actual visitor
origin (Placer.ai, Unacast, Azira, Veraset) is a paid mobile panel already
surveyed and ranked in the wishlist (gap a). Not re-litigated here.

### Consumer spend / sales estimates (gap b) — new candidate from the Notion reconciliation

- **CenterCheck** — paid, verified pricing: \$4K/yr single state, \$600/mo
  regional, \$1,250/mo national per seat. Store-level sales estimates from
  anonymized Visa/Mastercard/Discover/Amex card-transaction data (not a
  modeled proxy), plus customer-origin and demographics.
  https://centercheck.com · not in `registry.yaml` (checked: no
  `centercheck` id, active or wishlist). The owner's own Notion note calls
  it "~600 chains, weak on independents" and flags it as a "possible data
  partnership" rather than a straight buy — Loci's daily-needs categories
  skew heavily independent, so this only partially closes gap (b). Worth a
  conversation, not a P1 purchase; not promoted into §1's top line for that
  reason.

---

## 4. Competitor claims, with URLs

| Competitor | Claimed capabilities | Source |
|---|---|---|
| **Placer.ai** | Void Analysis (tenant-in, ranked by demographic fit / cannibalization risk / visits), trade-area cannibalization overlap, visitor origin, foot-traffic panel | [placer.ai/guides/void-analysis](https://www.placer.ai/guides/void-analysis), [placer.ai/guides/site-selection-guide](https://www.placer.ai/guides/site-selection-guide) |
| **SiteZeus (relaunched as "Atlas", ~May 2026)** | Predictive site selection, sales forecasting, cannibalization modeling, conversational-AI site evaluation, national-scale analysis across 30,000+ US ZIPs | [prnewswire.com — Atlas launch](https://www.prnewswire.com/news-releases/sitezeus-reinvents-site-selection-software-with-atlas-launch-302769074.html), [mytraffic.io — top 5 AI site selection tools](https://www.mytraffic.io/en/post/5-ai-site-selection-tools) |
| **Buxton (rebranded Audiense In-Person, July 2025 — unified with Elevar and the original Audiense)** | Location intelligence, consumer analytics, "risk reduction and site optimization" | [audiense.com/products/audiense-in-person](https://www.audiense.com/products/audiense-in-person) |
| **Kalibrate** | Site selection and network planning (fuel/c-store led), transparent proprietary forecasting model, analyst-verified outputs; acquired Trade Area Systems for retail network planning | [kalibrate.com/fuel-site-analysis-data](https://kalibrate.com/fuel-site-analysis-data), [cspdailynews.com — TAS acquisition](https://cspdailynews.com/fuels/kalibrate-technologies-acquires-trade-area-systems) |
| **GrowthFactor** | Full product suite under one platform: TrafficRX (foot traffic), AccuSite.AI (site scoring), Mobilytics, Globe.AI, Void.AI (whitespace), PlannedDev (development pipeline), competitor intelligence, flood-zone/wetlands and "Climate Intelligence" layers | [mapzot.ai — retail site selection software roundup, quoting GrowthFactor's own product list](https://www.mapzot.ai/resources/blog/retail-site-selection-software), [growthfactor.ai — site selection analysis guide](https://www.growthfactor.ai/resources/blog/retail-site-selection-analysis) |
| **Esri ArcGIS Business Analyst** | Demographic mapping, Tapestry psychographic segmentation ("behaviors category" — social media use, online shopping habits, charitable giving), trade-area optimization, target-market identification | [esri.com/en-us/arcgis/products/arcgis-business-analyst/overview](https://www.esri.com/en-us/arcgis/products/arcgis-business-analyst/overview), [esri.com/arcgis-blog — Tapestry target marketing](https://www.esri.com/arcgis-blog/products/bus-analyst/analytics/arcgis-tapestry-in-arcgis-business-analyst-pro-identify-target-markets) |
| **Unacast** | Foot-traffic and trade-area analytics, "gaps in trade areas based on how far people travel to a location" (visitor origin), site-selection data platform | [unacast.com/solutions/business-site-selection](https://www.unacast.com/solutions/business-site-selection), [unacast.com/post/trade-area-analytics](https://www.unacast.com/post/trade-area-analytics) |
| **Pass_by (PassBy)** | Foot traffic as one input alongside demographics, competitive analysis, and cannibalization modeling; positions itself as broader "site selection software" vs. foot-traffic-only tools | [passby.com/blog/retail-site-selection-software](https://passby.com/blog/retail-site-selection-software) |
| **Azira (formerly Near, went through Chapter 11 in Dec 2023, now trading under Azira)** | Site selection driven by consumer behavior, demographics, economic conditions, competitive landscape and "community insights"; audience curation and footfall attribution | [business.azira.com/how-to-guide-site-selection](https://business.azira.com/how-to-guide-site-selection) |
| **Spatial.ai (PersonaLive)** | Geosocial behavioral segmentation combined with Esri Tapestry — 17 groups / 80 segments built from transaction, mobile-visit and social-media data, used to rank retail sites within a submarket | [esri.com/about/newsroom/arcnews — geosocial consumer behavior](https://www.esri.com/about/newsroom/arcnews/startup-uses-geosocial-data-to-analyze-consumer-behavior) |
| **Tango Analytics** | Predictive analytics module (part of a broader real-estate lifecycle/lease-admin platform, 650+ enterprise clients): sales forecasting, cannibalization evaluation within a trade area | [tangoanalytics.com/solutions/site-selection-software](https://tangoanalytics.com/solutions/site-selection-software), [tangoanalytics.com/blog/location-analytics](https://tangoanalytics.com/blog/location-analytics) |
| **CARTO** | Spatial analytics for site selection, natural-language "Site Selection AI Agent" (built on Google Gemini Enterprise), Mastercard-delivered spend/location data, global Spatial Data Catalog enrichment | [carto.com/blog — Site Selection AI Agent](https://carto.com/blog/introducing-carto-site-selection-ai-agent-for-gemini-enterprise), [carto.com/solutions/site-selection](https://carto.com/solutions/site-selection) |
| **Alteryx** | Spatial + demographic + performance data unified for drive-time catchments, competitive-landscape analysis, predictive location-potential models, no-code workflows | [alteryx.com — site selection solution brief (PDF)](https://www.alteryx.com/wp-content/uploads/media/solution-brief/solutions-brief-site-selection.pdf) |
| **CoStar** | Property/lease listings, comps, market analytics for CRE brokers and lenders (already in Loci's own price map, GTM.md §3) | GTM.md internal citation; [pricelevel.com/vendors/costar](https://www.pricelevel.com/vendors/costar/pricing) |
| **SizeUp / LocalIntel** | Free, EDO-white-labelled market analysis for small businesses — competitive benchmarks, customer/supplier/competitor identification, "where to locate" guidance | [company.sizeup.com — small business PDF](http://company.sizeup.com/wp-content/uploads/2019/09/SizeUpLBI-Utilities-Digital.pdf), [selectmesa.com/small-businesses-startups/tools/mesa-sizeup](https://selectmesa.com/small-businesses-startups/tools/mesa-sizeup) |
| **PiinPoint** | Site-selection + network-planning platform: "Sitematch" automated site scoring/submission, "Marketmatch" predictive sales forecasting, mobile-location traffic/customer-origin data, demographic insights, trade-area mapping, cannibalization modeling, network simulations for expansion/renewal/closure decisions | [piinpoint.com](https://www.piinpoint.com) |
| **Atlas** | AI-native GIS ("Navi" conversational map-building assistant) with live-synced data connectors, automated buffer/exclusion spatial analysis, portfolio dashboards, site selection/screening — positions itself as GIS for non-specialists | [atlas.co](https://atlas.co) |
| **Maptive** | Spreadsheet-to-map GIS with 60+ features: Territory Manager, Heat Mapping, Drive Time Polygons, US/Canada census demographic overlay, retail site-selection and CRE trade-area support | [maptive.com](https://www.maptive.com) |
| **RestaurantSiteFinder** | Concept+address → 1–10 opportunity score and GO/NO-GO verdict; competitor map from Google Places + review sentiment; 3 suggested concepts; rent calculator (revenue needed to hold rent <8%); Premium adds hourly foot traffic, PDF export, site comparison. Direct site fetch returned only the page title (thin/gated content) — capability claims below are from the owner's own Notion notes | Notion DB; [restaurantsitefinder.com](https://restaurantsitefinder.com) |
| **Locate.ai** | "Portfolio Intelligence" scoring 1,100+ variables/site, "Market Roadmap" ranking all US markets, revenue forecasting, cannibalization-risk assessment, site pipeline management, lease-execution advisory; claims sites picked via the platform "outperform the market by 15%" (unverified) | [locate.ai](https://locate.ai) |
| **Plotr** (formerly IdealSpot) | Location data + "real-time consumer trends" for site and pricing decisions; Notion adds a "Pulse Price" dynamic real-estate pricing model and store-closure prediction at the Enterprise tier — notably *predictive*, where Loci's ground-truth module is verification-only | [plotr.com](https://plotr.com) |
| **Accruent Lucernex** | Real-estate lifecycle software for lease administration and site/construction planning; Notion adds "predictive store performance" as a claimed capability (site fetch surfaced no elaboration) | [accruent.com](https://www.accruent.com) |
| **MyTraffic** | "Gini" AI geospatial assistant analyzing footfall, competitive density, demographics; DataLibrary, AudienceLabs (digital-to-store conversion), SmartMonitor (shopping-center analytics); claims 10M locations at 10 m accuracy across 18 European countries + US; clients include Carrefour, Five Guys | [mytraffic.io](https://www.mytraffic.io) |
| **CenterCheck** | Store-level sales estimates from anonymized Visa/Mastercard/Discover/Amex card-transaction data ("not proxies"), customer-origin/demographics, client-ready reporting; covers ~600 major chains (Target, Chick-fil-A, Whole Foods, etc.). New sourcing candidate — see §3 | [centercheck.com](https://centercheck.com) |
| **MapZot.AI** | Site claims AccuSite.AI, TrafficRX, Mobilytics, Globe.AI, Void.AI, PlannedDev — **identical named features to GrowthFactor's own product suite** (row above). Likely the same underlying product, a reseller/white-label relationship, or shared marketing copy rather than an independent capability set; not counted as a distinct new capability source | [mapzot.ai](https://www.mapzot.ai) |
| **SiteSeer** | Demographic Reports, Void Analysis, Territory Planning, Heat Maps, custom dashboards; powered by third-party panels AGS, Environics Analytics, MRI-Simmons, PlaceIQ (none in `registry.yaml`) | [siteseer.com](https://www.siteseer.com) |
| **Geod** | Network-scenario software: simulate openings/closings/conversions and measure portfolio-wide impact, not single-site; drive-time trade areas, Census+POI demographics, competition weighting by brand substitutability, per-store cannibalization, and — notably — decomposable scoring that "reconciles predictions against actual outcomes," i.e. a competitor explicitly claiming to backtest itself | [geod.app](https://www.geod.app) |
| **Sitewise** | No public URL in the owner's Notion row (Website field blank). Owner's own notes: "market-planning specialist," category Decision tool (chains), status "Not yet researched" — no capability claim to evaluate yet | Notion DB only, no URL |

### Owner-recorded notes on already-covered competitors (Notion reconciliation)

The owner's Notion rows for the 10 competitors already in the table above
add pricing, funding, and risk-framing detail this memo didn't have. None
contradicts a capability claim; all are additive.

- **GrowthFactor** — Notion adds funding/scale detail absent from this
  memo: \$5.2M seed (Mar 2026), ~\$1M ARR, 30+ customers, owner's Threat
  rating "High." Its Labs Discovery tier is priced at \$5K/30 days but
  gated behind 40+ mature stores of the buyer's own — a bar most Loci
  prospects (single-location or early-stage) will not clear.
- **Placer.ai** — Notion adds \$1.5B valuation / ~\$100M ARR (2024) and a
  verified price band (~\$12K–50K/yr, freemium tier exists); owner rates
  it Threat "Medium," not "High," despite foot traffic being the survey's
  most-claimed capability (§1 #5) — the owner's own risk read is more
  measured than the capability gap alone would suggest.
- **Esri ArcGIS Business Analyst** — Notion prices the base product at
  ~\$2,500/user/yr, materially below the \$5,200/yr `registry.yaml`
  wishlist #10 price for "Business Analyst Advanced" — likely different
  SKUs (base vs. Advanced tier), not a contradiction, but worth confirming
  before purchase.
- **SizeUp** — Notion adds a GTM-relevant detail this memo lacks: SizeUp's
  distribution is through SBA lenders, banks, and econ-dev orgs — the same
  lender channel Loci is targeting. A potential channel conflict or
  partnership angle, not just a capability competitor.
- **Buxton** — Notion's framing ("consultative, slow, expensive," Threat
  "Low") is consistent with the memo's "legacy, analyst-led" read; adds a
  price point (~\$20K+/yr).
- **Unacast** — Notion rates Threat "Low" despite claiming visitor origin
  (a Missing capability for Loci) — the owner reads it as more of a data
  vendor than a decision-tool threat, consistent with the memo's
  "borderline data vendor" framing.
- **SiteZeus, CARTO, Kalibrate, Tango** — Notion's notes (enterprise
  pricing, consulting-led, vertical-specific) are consistent with the
  memo; no new capability claim or contradiction.

### Claims that look like marketing no data could actually back

- **"Predict store performance with impeccable accuracy"** (Tango
  Analytics) and **SiteZeus's "explainable AI... faster, more confident
  expansion decisions"** — sales forecasting from a national panel or
  comps model, generalized across arbitrary retail categories and
  markets, is exactly the claim Loci's own retrodiction *rejected* for
  itself even with fifteen years of NYC-specific filings data (entry AUC
  lift of only +0.013, no decision-value claim survives the test — GTM.md
  §1). A vendor claiming category-general "accurate" sales forecasts with
  no published backtest, no city-specific calibration, and no stated
  category exclusions should be read skeptically — Loci's own experience
  is that only one of fifteen categories (restaurant) clears even a
  grade-C bar.
- **Azira / Near's "actionable recommendations for business growth"**
  from a mobile-device panel — panel-based visit and audience data can
  describe *where people already are*, but "recommendation" language
  implies causal site-quality guidance the underlying data (a device
  panel with undisclosed NYC share) cannot support any more than Loci's
  own supply-ratio score can (GTM.md is explicit that Loci "measures
  supply thinness, not site quality" for the same structural reason).
- **CARTO's "Site Selection AI Agent... turning complex spatial analytics
  into simple, natural-language conversations"** — a chat interface over
  spatial data does not change what the underlying data can support;
  this is a UX claim dressed as a capability claim.
- **GrowthFactor's "Climate Intelligence"** is the one claim in this
  survey backed by something genuinely free and simple (FEMA/NYC flood
  layers, §3 above) — not marketing puffery, just a capability Loci
  hasn't bothered to add yet because it's cheap and unglamorous.

---

## Method note

Stage 1–2 competitor names were seeded by grepping `docs/GTM.md` (price map,
§2–3) and `docs/PAID-SOURCES.md` (P1–P3 wishlist, "competing products, not
data sources" note in the corrections appendix). `docs/reach_sources.md`
turned out to be a walk-distance-threshold bibliography (D8), not a
competitor list, and contributed nothing to this survey. Capability claims
were pulled from each vendor's own marketing/docs pages via web search
2026-09-22; prices were not re-verified here — `PAID-SOURCES.md` already
carries dated, sourced pricing for every vendor that is also a Loci
wishlist entry. Reconciled against the owner's Notion Competitors database
on 2026-09-22 (23 rows; 13 added).
