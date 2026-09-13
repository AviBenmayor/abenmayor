# Loci — paid data sources to integrate post-raise

**GENERATED — do not edit.** Rendered by `loci gen-paid-sources` from the `status: wishlist` entries in [`src/loci/registry.yaml`](../src/loci/registry.yaml). `loci check-sources` fails if this file differs from a fresh render, so a price here is a price in the registry with its dated evidence beside it.

Surveyed 2026-09-13 against vendor pricing pages, published terms, public procurement records and 2025–2026 press. **35 candidates** — 10 P1, 18 P2, 7 P3.

**Gap letters** map to the named holes in `docs/CONTEXT.md` and `docs/CHECKPOINT.md`: (a) Foot traffic · (b) Spend and the economics grade · (c) Rent per square foot · (d) Openings, closings and the tenant pipeline · (e) POI truth · (f) Chain expansion · (g) Ownership and vacancy · (h) Demographics beyond ACS · (i) Sidewalk counts.

**What the price column means.** `verified` is a vendor list price or a signed contract. `reported` is a third-party or derived annual figure. `tier floor` means the vendor publishes nothing and the entry books the floor of its price band — so every total below is a **lower bound**, not a forecast.

| | Annual USD |
|---|---|
| Whole wishlist, as booked (verified price where one exists, tier floor otherwise) | **$301,565** |
| Whole wishlist, every entry at its tier floor | $213,200 |
| The subset with a VERIFIED price (13 of 35 entries) | $86,457 |
| P1 only, as booked | $74,300 |

---

## Ranked

| # | Pri | Source | Category | Gap | Price tier | Price | Licence constraint | Effort | Conf. |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P1 | **Patterns Plus (POI visits)** — Advan Research | foot traffic | a | quote only | $10,000/yr (tier floor — no price published) | CRE/site-selection is one of four marketed verticals, so commercial use is very likely permitted directly … | low | med |
| 2 | P1 | **Placer.ai** — Placer Labs Inc. | foot traffic | a | $10–50k/yr | **$8,000/yr** (verified) | ToS requires vetting as an incorporated business with brick-and-mortar interest (site selection qualifies) but EXPLICITLY prohibits reselling, … | low | med |
| 3 | P1 | **SafeGraph Spend** — SafeGraph | spend | b | quote only | $10,000/yr (tier floor — no price published) | Commercial licence configurable by usage rights; resale/redistribution typically requires an add-on licence. | low | med |
| 4 | P1 | **CompStak Enterprise (lease comps)** — CompStak | rent | c | quote only | $10,000/yr (tier floor — no price published) | Unpublished; Enterprise terms would need an explicit clause permitting derived rent figures to appear on a card sold to a third party. | med | med |
| 5 | P1 | **Places Insights in BigQuery** — Google Maps Platform | pipeline | d | quote only | $10,000/yr (tier floor — no price published) | Documentation cites CC BY 4.0 on the underlying listing with no explicit storage or redistribution restriction stated — materially looser on paper … | med | med |
| 6 | P1 | **Business Database API + Changes API** — Data Axle (formerly Infogroup) | pipeline | d | $1–10k/yr | $8,000/yr (reported) | Commercial product use is the intended use case for the API, BUT Data Axle's public T&Cs grant a limited, non-transferable, non-sublicensable … | low | high |
| 7 | P1 | **LiveXYZ NYC storefront census** — LiveXYZ | POI | e | quote only | $10,000/yr (tier floor — no price published) | Unpublished. Agency use is precedented; commercial redistribution inside a sold product would need explicit terms. | high | med |
| 8 | P1 | **Places API (New) — Place Details Pro** — Google Maps Platform | POI | e | $1–10k/yr | $3,000/yr (reported) | Only place_id may be cached indefinitely … | low | high |
| 9 | P1 | **Places Aggregate API** — Google Maps Platform | POI | e | <$1k/yr | $100/yr (reported) | Standard Maps Platform terms … | low | high |
| 10 | P1 | **ArcGIS Business Analyst Web App (incl. Tapestry + Consumer Spending)** — Esri | demographics | h | $1–10k/yr | **$5,200/yr** (verified) | Esri's master agreement restricts sublicensing and redistributing underlying data; a standard seat licence does NOT clearly permit backing a paid … | med | high |
| 11 | P2 | **StreetLight InSight — Active Transportation / Bike-Ped** — StreetLight Data (Jacobs) | foot traffic | a | $10–50k/yr | **$42,888/yr** (verified) | A retail vertical is explicitly marketed ('select sites, forecast sales'), so commercial site-selection use is a stated permitted use … | med | high |
| 12 | P2 | **Foursquare Visits (enterprise)** — Foursquare | foot traffic | a | quote only | $10,000/yr (tier floor — no price published) | Commercial site-selection use is explicitly marketed (Yum! Brands case study via AWS Data Exchange) … | low | med |
| 13 | P2 | **Veraset Visits / Movement** — Veraset | foot traffic | a | quote only | $10,000/yr (tier floor — no price published) | A dedicated Real Estate solutions page makes commercial site-selection an intended use … | high | med |
| 14 | P2 | **BestTime.app busyness API** — BestTime.app | foot traffic | a | $1–10k/yr | **$1,152/yr** (verified) | The ToS could not be fully extracted and contains no discoverable resale prohibition — but absence of evidence is not permission … | low | high |
| 15 | P2 | **Earnest Analytics (Vela / Orion), incl. ZIP-level in-store spend** — Earnest Analytics (acquired by Consumer Edge, April 2025) | spend | b | quote only | $10,000/yr (tier floor — no price published) | RED FLAG — the Dash terms restrict use to an 'investment/financial services firm or internal business analysis' and bar assembling a database from … | med | med |
| 16 | P2 | **Mastercard Retail Location Insights** — Mastercard Data & Services (delivered with CARTO) | spend | b | quote only | $10,000/yr (tier floor — no price published) | Terms page blocked automated access; unconfirmed … | high | med |
| 17 | P2 | **Crexi Intelligence** — Crexi | rent | c | $1–10k/yr | $2,988/yr (reported) | No litigation history found against it and a materially more permissive posture than CoStar, but terms for embedding in a sold product are unverified. | med | med |
| 18 | P2 | **PincusCo NYC real-estate deal tracking** — PincusCo Media | pipeline | d | $1–10k/yr | **$1,500/yr** (verified) | Editorial subscription; systematic extraction into a sold product would need permission. | high | high |
| 19 | P2 | **Placekey** — Placekey (SafeGraph-originated open standard) | POI | e | $1–10k/yr | **$3,000/yr** (verified) | Open standard, partners include SafeGraph, Veraset, CARTO, Esri, Cuebiq, Regrid … | low | high |
| 20 | P2 | **Yelp Places API (formerly Fusion)** — Yelp | POI | e | $1–10k/yr | **$2,748/yr** (verified) | Standard API terms with caching limits; opening dates, closure dates and review-velocity fields are NOT documented and are likely absent, which is … | low | high |
| 21 | P2 | **Outscraper Google Maps extraction** — Outscraper | POI | e | <$1k/yr | $300/yr (reported) | MATERIAL RISK — scraping Google Maps breaches Google's terms (a contract issue, not a CFAA crime per case law), and Outscraper's marketing grants no … | low | high |
| 22 | P2 | **Google Maps Businesses dataset** — Bright Data | POI | e | $1–10k/yr | **$250/yr** (verified) | Same Google-terms exposure as Outscraper; no explicit resale licence granted … | low | high |
| 23 | P2 | **RetailStat Location (incl. former Creditntell)** — RetailStat | chains | f | quote only | $10,000/yr (tier floor — no price published) | Unpublished. | high | med |
| 24 | P2 | **Coresight US Store Openings/Closures Tracker** — Coresight Research | chains | f | quote only | $10,000/yr (tier floor — no price published) | Research subscription; republication restricted. | high | med |
| 25 | P2 | **Reonomy** — Altus Group | property | g | $1–10k/yr | **$4,800/yr** (verified) | Self-serve seat is for internal use; bulk/derived redistribution requires the enterprise feed and separate terms. | med | high |
| 26 | P2 | **PropertyShark** — Yardi | property | g | $1–10k/yr | **$719/yr** (verified) | UI-only by design; bulk or automated extraction is restricted. Most of the underlying content is already free in PLUTO/ACRIS, which Loci ingests. | high | high |
| 27 | P2 | **PersonaLive segmentation** — Spatial.ai | demographics | h | $10–50k/yr | **$5,100/yr** (verified) | Redistribution terms for a resold product are not published and need direct confirmation. | med | med |
| 28 | P2 | **Computer vision on NYC DOT traffic camera frames (BUILD, not buy)** — self-built on NYCTMC feeds | sidewalk | i | hardware/compute | $4,320/yr (reported) | MATERIAL RISK — no published, versioned terms-of-use text is retrievable (the site is a JS SPA and the terms link is client-side routed), but NYC … | high | med |
| 29 | P3 | **Dewey Data (Advan/SafeGraph reseller channel)** — Dewey Data | foot traffic | a | $1–10k/yr | **$3,600/yr** (verified) | DISQUALIFIED … | low | high |
| 30 | P3 | **CE Vision** — Consumer Edge | spend | b | quote only | $10,000/yr (tier floor — no price published) | Public terms of use bar reselling, redistributing or creating derivative commercial products without written consent. | med | med |
| 31 | P3 | **CoStar Retail** — CoStar Group | rent | c | $10–50k/yr | $15,000/yr (reported) | NON-STARTER as written. CoStar is the most litigious vendor in this space, with 30+ copyright and trade-secret suits on record (CoStar v … | high | high |
| 32 | P3 | **D&B Data Blocks / Direct+ / Hoovers** — Dun & Bradstreet | pipeline | d | $10–50k/yr | $41,400/yr (reported) | Enterprise licences are per-use-case; redistribution requires specific terms. | med | med |
| 33 | P3 | **Firefly (US foodservice operator database)** — Datassential | chains | d | quote only | $10,000/yr (tier floor — no price published) | Datassential's published Additional Product Terms explicitly bar embedding their data or reports into a third-party product for resale … | high | high |
| 34 | P3 | **Lightcast job postings + LMI** — Lightcast (formerly Emsi Burning Glass) | pipeline | d | $10–50k/yr | **$7,500/yr** (verified) | Terms explicitly bar redistributing the dataset to third parties on an on-demand or standalone basis — usable as an internal signal only. | med | high |
| 35 | P3 | **PRIZM Premier / Claritas 360** — Claritas | demographics | h | quote only | $10,000/yr (tier floor — no price published) | Sharpest licence restriction found in the entire survey … | med | high |

---

## By gap — what each purchase graduates

P1 and P2 only. P3 items are recorded in the ranked table above and in the registry so they are not relitigated; they are not bought.

### (a) Foot traffic

**The question this graduates.** Can `transit_entries_400m` stop being card context and
become a grade input, or the supply-ratio denominator? D76 / GTM-147 says no until it is
validated OFF a commercial corridor, and every sidewalk count NYC publishes — all 114
DOT points — sits ON one. A measured visit count per storefront is the non-corridor
validation set that does not otherwise exist.

**P1 · Patterns Plus (POI visits)** (Advan Research) — $10,000/yr (tier floor — no price published), low effort, med confidence

- *Closes:* (a) Foot traffic — gives an actual measured visit count per storefront, which is the variable D76's graduation test (QUESTIONS M12) demands before transit_entries_400m can stop being card context and become a grade input or the supply-ratio denominator.
- *Why this rank:* Advan now owns the former SafeGraph Patterns business, so it is the single most direct replacement for the proxy the contrarian rejected.
- *Grain:* POI x day/week/month visit aggregates; visitor-origin at census block group.
- *NYC coverage:* National panel, ~45M US devices / 150M+ locations claimed; no NYC or borough-level panel share published.
- *Cannot see:* A modelled panel, not a count. No NYC or borough panel share is published, so the device-share denominator on any given Brooklyn block is unknown and unauditable. Opt-in GPS panels skew toward smartphone-heavy, app-consenting populations; an errand walk of two blocks may not register as a trip at all.
- *Price:* No published price anywhere; entirely demo-gated. No G2/Vendr/Reddit figure found. Comparable-product reported figures put this plausibly at 10k-50k/yr but that is inference, not a quote.
- *Licence:* CRE/site-selection is one of four marketed verticals, so commercial use is very likely permitted directly. Redistribution of derived metrics to Loci's own customers is unconfirmed and must be negotiated explicitly.
- *Evidence:* [https://advanresearch.com/advan-news](https://advanresearch.com/advan-news) (2026-09-13) · [https://docs.advanresearch.com](https://docs.advanresearch.com) (2026-09-13) · [https://www.youtube.com/watch?v=Pms4YexzV8I](https://www.youtube.com/watch?v=Pms4YexzV8I) (2026-07-14)

**P1 · Placer.ai** (Placer Labs Inc.) — **$8,000/yr** (verified), low effort, med confidence

- *Closes:* (a) Foot traffic — same graduation test as Advan (M12/D76), and its trade-area polygons would also replace the Huff capture-share assumption fitted in D81.
- *Why this rank:* Most site-selection-native product with a real public price floor, but the derived-data redistribution ban must be negotiated before it can touch a customer-facing card.
- *Grain:* POI-level visits; data is suppressed or degraded below roughly 50 unique devices at a location.
- *NYC coverage:* 'Tens of millions of devices' nationally; no NYC-specific panel share published. The <50-device floor is a real risk on quiet Brooklyn blocks, which is exactly where Loci's proxy already fails.
- *Cannot see:* Suppresses or degrades a location below roughly 50 unique devices -- the quiet blocks where Loci's transit proxy already fails are exactly the blocks Placer will return empty, so its silence reads as low traffic when it means low panel. Same national-panel share problem as Advan.
- *Price:* Quote-only officially. Signed public-sector order forms show $8,000-$27,500/yr (Utah PMN 1249759; Bloomington IN 23-767 packet; CivicIQ 2026). Third-party commercial estimates span $5k-$50k+/yr (softwarefinder.com, growthfactor.ai 2026-08-20) and do not converge.
- *Licence:* ToS requires vetting as an incorporated business with brick-and-mortar interest (site selection qualifies) but EXPLICITLY prohibits reselling, redistributing or sublicensing Placer data or derived data, and prohibits using it to train AI models. That ban is a direct conflict with exposing Placer-derived numbers on a Loci card sold to a third party.
- *Note:* Cost books $8,000 -- the low end of the signed public-sector order forms -- which is below the 10k_50k_yr band floor. The band is the vendor's asking range; the contract is the number that was actually paid.
- *Evidence:* [https://www.placer.ai/terms-of-service](https://www.placer.ai/terms-of-service) (2026-09-13) · [https://docs.placer.ai/docs/delivery-details](https://docs.placer.ai/docs/delivery-details) (2026-09-13) · [https://www.utah.gov/pmn/files/1249759.pdf](https://www.utah.gov/pmn/files/1249759.pdf) (2026-09-13) · [https://www.growthfactor.ai/resources/blog/placer-ai-alternatives](https://www.growthfactor.ai/resources/blog/placer-ai-alternatives) (2026-08-20)

**P2 · StreetLight InSight — Active Transportation / Bike-Ped** (StreetLight Data (Jacobs)) — **$42,888/yr** (verified), med effort, high confidence

- *Closes:* (a) Foot traffic — but note it is MODELLED, not sensed, so it would compound rather than resolve the 'no ground truth on quiet blocks' problem and cannot on its own clear the M12 graduation test.
- *Why this rank:* Best-verified pricing of any mobility vendor, but tract grain and modelled origin make it a validation cross-check rather than a grade input.
- *Grain:* Census tract for pedestrian volumes; road segment for vehicle metrics. Coarser than Loci's address grain.
- *NYC coverage:* National by tract and segment; NYC included.
- *Cannot see:* Census tract for pedestrian volumes -- two orders of magnitude coarser than the address grain, so it cannot separate a busy corner from the quiet block behind it. Modelled from a mobility panel, and the published figures are 2020-21 vintage.
- *Price:* Real public-agency contracts: Ames IA $64,900/yr base, $105,667/yr multimodal (2021 council packet); Teton County WY $42,888 for one year; San Mateo C/CAG tiers at $99,000/agency single-domain and $440,000 regional, with pay-per-use ~$24,000 for a 50-zone study. 2020-21 figures; current rates likely higher.
- *Licence:* A retail vertical is explicitly marketed ('select sites, forecast sales'), so commercial site-selection use is a stated permitted use. Public-agency contracts restrict to internal agency use; a commercial licence is negotiated separately.
- *Evidence:* [https://www.streetlightdata.com/pricing/](https://www.streetlightdata.com/pricing/) (2026-09-13) · [https://vault.amesnews.net/gov/city/CouncilPackets/2021/081021CouncilAgenda/20.pdf](https://vault.amesnews.net/gov/city/CouncilPackets/2021/081021CouncilAgenda/20.pdf) (2021-08-10) · [https://ccag.ca.gov/wp-content/uploads/2020/04/6.3_StreetLight-Presentation.pdf](https://ccag.ca.gov/wp-content/uploads/2020/04/6.3_StreetLight-Presentation.pdf) (2020-04)

**P2 · Foursquare Visits (enterprise)** (Foursquare) — $10,000/yr (tier floor — no price published), low effort, med confidence

- *Closes:* (a) Foot traffic — same M12/D76 test as Advan and Placer, and the marketplace route means no sales cycle is strictly required.
- *Why this rank:* Cleanest procurement path (AWS/Snowflake, no sales call) but the panel's check-in bias is the one Loci has already documented as dangerous.
- *Grain:* POI x period aggregates.
- *NYC coverage:* Not disclosed; Foursquare's panel historically skews toward check-in-heavy venues, i.e. away from laundromats — the same bias CONTEXT §3.1 already flags for OS Places.
- *Cannot see:* Inherits the check-in-derived venue skew CONTEXT §3.1 already flags for OS Places: away from laundromats, tailors and dry cleaners, i.e. away from the daily-needs bundle. No panel share disclosed.
- *Price:* Visits pricing is not published. For contrast, the Places API IS verified at $15.00/1,000 calls (Pro, 501-100k tier, effective 2026-06-01) down to $9.00/1,000 at 500k+ — but that is POI attributes, largely redundant with the free OS Places Loci already ingests.
- *Licence:* Commercial site-selection use is explicitly marketed (Yum! Brands case study via AWS Data Exchange). Redistribution terms not public.
- *Evidence:* [https://foursquare.com/pricing](https://foursquare.com/pricing) (2026-09-13) · [https://location.foursquare.com/products/visits/](https://location.foursquare.com/products/visits/) (2026-09-13)

**P2 · Veraset Visits / Movement** (Veraset) — $10,000/yr (tier floor — no price published), high effort, med confidence

- *Closes:* (a) Foot traffic — raw Movement pings are the only product that would let Loci geofence its OWN address polygons rather than accept a vendor's POI attribution, which matters because Loci's supply set is deduped differently from any vendor's.
- *Why this rank:* Highest ceiling and highest effort; only worth it if vendor POI attribution proves incompatible with Loci's cluster grain.
- *Grain:* Visits = POI-level. Movement = device-level raw pings (finest grain available anywhere).
- *NYC coverage:* No NYC-specific figures published. A Datarade listing citing ~768M devices is almost certainly a mislabelled cumulative figure — treat sceptically.
- *Cannot see:* The least transparent vendor surveyed -- no published panel share, no NYC figures, and a Datarade device count that is almost certainly a mislabelled cumulative. Raw device pings carry the heaviest privacy and licence exposure of anything on the list.
- *Price:* Least transparent vendor checked — not even a converging rumour. One AI-search-derived claim of '$40,000 starting' could not be traced to a live primary page and should not be relied on.
- *Licence:* A dedicated Real Estate solutions page makes commercial site-selection an intended use. Raw pings carry a materially higher privacy/compliance burden (CCPA pass-through) than pre-aggregated products.
- *Evidence:* [https://www.veraset.com/products/product-comparison](https://www.veraset.com/products/product-comparison) (2026-09-13) · [https://www.veraset.com/solutions/real-estate](https://www.veraset.com/solutions/real-estate) (2026-09-13)

**P2 · BestTime.app busyness API** (BestTime.app) — **$1,152/yr** (verified), low effort, high confidence

- *Closes:* (a) Foot traffic — the only sub-$1k/month way to get an hourly busyness curve per storefront, which is the day-part discrimination the D76 addendum found the transit levels do NOT carry (the AM count is ranked better by pm_peak than by am_peak).
- *Why this rank:* Cheapest credible pilot in the whole foot-traffic category, but relative-not-absolute values and the small-business coverage hole cap what it can grade.
- *Grain:* Per venue, per hour, per day of week.
- *NYC coverage:* Global, but explicitly requires 'sufficient visitor volume for reliable forecasts' — small independent NYC storefronts with thin Google signal will simply have no forecast. That is a coverage bias pointing the same direction as OSM's, i.e. toward the areas Loci flags as underserved.
- *Cannot see:* Requires 'sufficient visitor volume for reliable forecasts', so a small independent with thin Google signal simply has no curve. That absence points the same direction as the OSM undercount -- toward the underserved areas the screen exists to find -- and a busyness index is a shape, not a count.
- *Price:* VERIFIED published pricing: Basic metered $0.04/credit with $29/mo minimum; Pro metered $0.009/credit falling to $0.006 above 10k and $0.001 above 100k, plus $99/mo base; Pro fixed package $96/mo; Basic fixed package $299/mo; Enterprise 'from $2K+/month'. Free credits for students and non-profits.
- *Licence:* The ToS could not be fully extracted and contains no discoverable resale prohibition — but absence of evidence is not permission. Because the forecasts are Google-derived, there is plausible indirect exposure to Google's own terms. Get written confirmation of derived-analytics and resale rights before shipping.
- *Note:* Cost books the Pro fixed package at $96/mo = $1,152/yr. The allocation paragraph budgets $2-3k for a pilot, which includes metered credits on top.
- *Evidence:* [https://besttime.app/subscription/pricing](https://besttime.app/subscription/pricing) (2026-09-13) · [https://documentation.besttime.app](https://documentation.besttime.app) (2026-09-13)

### (b) Spend and the economics grade

**The question this graduates.** D81 ships nine of fifteen categories as "not modelled"
because nothing in the free data says what a storefront takes in. Address- or block-
grain spend is what moves the economics grade off D and gives the capture-share
parameter lambda its first out-of-sample test.

**P1 · SafeGraph Spend** (SafeGraph) — $10,000/yr (tier floor — no price published), low effort, med confidence

- *Closes:* (b) Demand/spend — real observed dollars per storefront would replace the CEX-quintile spend pool in D81 and give an out-of-sample test for the leakage parameter lambda, which today is 'right by construction and has NO out-of-sample test'; it is the route from a C grade on restaurant alone to a real grade on the nine categories shipped as 'not modelled'.
- *Why this rank:* Only spend product whose grain matches the address key; everything else in this category is ZIP or coarser.
- *Grain:* POI / address level — the finest grain of any spend product surveyed, and it matches Loci's existing address key directly.
- *NYC coverage:* National; NYC included. Low-volume small independents are suppressed, which bites at exactly the grain Loci cares about.
- *Cannot see:* Card-panel share is unpublished and low-volume independents are suppressed, so the categories with the weakest economics grade are the ones most likely to come back blank. A card panel cannot see cash, which is a large share of exactly the bodega/laundry/barber trades in question.
- *Price:* No Spend-specific price published. A general SafeGraph suite range of '$0.10 per purchase to $30,000/yr' appears in SafeGraph's own marketing and is not confirmed to apply to Spend. IMPORTANT correction to a common assumption: SafeGraph did NOT shut down — it sold the Patterns foot-traffic line to Advan and still sells Places and Spend in 2026.
- *Licence:* Commercial licence configurable by usage rights; resale/redistribution typically requires an add-on licence.
- *Evidence:* [https://www.safegraph.com/products](https://www.safegraph.com/products) (2026-09-13) · [https://www.safegraph.com/free-data](https://www.safegraph.com/free-data) (2026-09-13)

**P2 · Earnest Analytics (Vela / Orion), incl. ZIP-level in-store spend** (Earnest Analytics (acquired by Consumer Edge, April 2025)) — $10,000/yr (tier floor — no price published), med effort, med confidence

- *Closes:* (b) Spend — ZIP-grain observed spend is the out-of-sample test D81's leakage parameter lambda currently has none of; lambda_Kings and lambda_NY already disagree by 1.4-2.6x per category with no way to adjudicate.
- *Why this rank:* Finest non-SafeGraph spend grain found, but the terms as published would block the product Loci is raising money to sell.
- *Grain:* ZIP code via a merchant_location_zip table; custom trade areas on request. Coarser than Loci's address grain but finer than county.
- *NYC coverage:* National panel; NYC ZIPs included.
- *Cannot see:* ZIP grain, which in NYC pools radically different blocks into one number and is coarser than the walkshed the whole screen is built on. Card panel, so cash is invisible and panel share is undisclosed.
- *Price:* No price published and no Vendr benchmark exists for this vendor.
- *Licence:* RED FLAG — the Dash terms restrict use to an 'investment/financial services firm or internal business analysis' and bar assembling a database from the output. As written this is internal-use-only and incompatible with backing a resold product without a bespoke agreement.
- *Evidence:* [https://www.earnestanalytics.com](https://www.earnestanalytics.com) (2026-09-13)

**P2 · Mastercard Retail Location Insights** (Mastercard Data & Services (delivered with CARTO)) — $10,000/yr (tier floor — no price published), high effort, med confidence

- *Closes:* (b) Spend — block-grain spend would let D81 drop the county-level Economic Census anchor that currently 'blurs Park Slope with Gowanus', the caveat the revenue model says it cannot escape.
- *Why this rank:* Finest published grain in the category and it targets D81's named weakness, but zero price transparency and a likely six-figure entry point.
- *Grain:* CENSUS BLOCK — the finest grain of any card-panel product surveyed.
- *NYC coverage:* Plausible from a national panel but not explicitly confirmed for NYC.
- *Cannot see:* Census-block grain is fine, but the panel is card transactions: cash-heavy trades are systematically understated, NYC coverage is not explicitly confirmed, and redistribution is barred, so it can inform a grade it may never display.
- *Price:* No price found anywhere — Vendr, G2 and press are all blank. A Vendr '$100-125k' Mastercard entry could not be attributed to this specific product.
- *Licence:* Terms page blocked automated access; unconfirmed. Mastercard's adjacent SpendingPulse product explicitly bars redistribution, which is a signal about house style.
- *Evidence:* [https://carto.com/solutions/mastercard/](https://carto.com/solutions/mastercard/) (2026-09-13)

### (c) Rent per square foot

**The question this graduates.** The feasibility gate currently reasons about rent
without a rent number. A real asking-rent-per-sf series per corridor is what turns "this
gap is fillable" from a judgement into an arithmetic one.

**P1 · CompStak Enterprise (lease comps)** (CompStak) — $10,000/yr (tier floor — no price published), med effort, med confidence

- *Closes:* (c) Rent — replaces D81's rent_ceiling, which today is a modelled revenue times a generic 8% occupancy ratio checked against exactly ONE local comp, and is the reason the D74 card cannot grade feasibility above D on economics.
- *Why this rank:* Only lease-level comp source that is not legally hostile; rent is the single line that turns a gap into an investable site.
- *Grain:* Individual lease at a building address; deal alerts on new signings in a market.
- *NYC coverage:* NYC is CompStak's deepest market; retail comps exist but the file is office-weighted, so per-corridor retail depth should be tested before signing.
- *Cannot see:* Contribution-gated and office-weighted. A comp exists only because a broker uploaded it, so thin-brokerage retail corridors -- the outer-Brooklyn blocks the screen flags -- are structurally under-covered, and an effective rent net of concessions is not the asking rent a tenant plans against.
- *Price:* No published price at Enterprise tier. The free Exchange tier is contribution-gated — a firm with no comps of its own gets market dashboards but not comp-level data, so Loci cannot bootstrap for free. A DIFFERENT CompStak product, Prospect, does publish $199.99/mo individual and $499.99/mo team.
- *Licence:* Unpublished; Enterprise terms would need an explicit clause permitting derived rent figures to appear on a card sold to a third party.
- *Evidence:* [https://compstak.com](https://compstak.com) (2026-09-13) · [https://compstak.com/exchange](https://compstak.com/exchange) (2026-09-13)

**P2 · Crexi Intelligence** (Crexi) — $2,988/yr (reported), med effort, med confidence

- *Closes:* (c) Rent — asking rents on active retail listings, which is a leading indicator the LL157 annual snapshot cannot provide (CONTEXT §3.3 notes an annual 12/31 snapshot is not an availability listing).
- *Why this rank:* Only affordable listing-level rent option; validate NYC retail depth on a trial before committing.
- *Grain:* Property and listing level; claims 153M+ property records and 46M+ sales comps (unverified for NYC retail specifically).
- *NYC coverage:* National coverage; NYC retail depth unverified.
- *Cannot see:* Listing-derived: it sees space that was marketed, not space that was leased, and NYC retail depth is unverified. Asking rent on an active listing is a landlord's number.
- *Price:* Third-party pricing pages report ~$249/user/month (~$2,988/yr); NOT confirmed on Crexi's own site.
- *Licence:* No litigation history found against it and a materially more permissive posture than CoStar, but terms for embedding in a sold product are unverified.
- *Evidence:* [https://www.crexi.com/intelligence](https://www.crexi.com/intelligence) (2026-09-13)

### (d) Openings, closings and the tenant pipeline

**The question this graduates.** Two questions at once. GTM-152 / QUESTIONS T10: ten of
the fifteen categories (laundry, hair, nails, childcare, clinic, fitness, bank,
hardware, convenience, tailor) are structurally invisible to government filings, so the
pipeline sees nothing for them. And D79's first-seen ledger is 47.7% `backfill_censored`
— Google Places Insights publishes MONTHLY SNAPSHOTS BACK TO 2024-01, which would un-
censor that ledger two years retrospectively rather than starting the clock today.

**P1 · Places Insights in BigQuery** (Google Maps Platform) — $10,000/yr (tier floor — no price published), med effort, med confidence

- *Closes:* (d) Openings/closings — monthly snapshots since Jan 2024 are a ready-made openings and closings panel across ALL 15 categories, which is exactly what D79's first-seen ledger cannot reconstruct (47.7% of its rows are backfill_censored) and what T10 asks for.
- *Why this rank:* The only source found that offers a retrospective monthly storefront panel rather than starting the clock today; it would un-censor the D79 ledger back two years.
- *Grain:* H3 hex cells at selectable resolution, or custom point-radius / polygon geometries; up to 250 place_ids returned per row; counts of 0-4 suppressed.
- *NYC coverage:* Full Google coverage of NYC at any H3 resolution Loci already uses.
- *Cannot see:* Counts of 0-4 are suppressed, which is precisely the regime a daily-needs gap lives in: a walkshed with two bodegas and a walkshed with none may both return blank. Snapshots start 2024-01, so it cannot reach the 2013-2023 panel window.
- *Price:* GA since 2025-09-30. No price published on either the product or documentation page; access is via a contact form plus BigQuery compute. Treat as quote_only until a Google Maps Platform rep gives a figure.
- *Licence:* Documentation cites CC BY 4.0 on the underlying listing with no explicit storage or redistribution restriction stated — materially looser on paper than the Places API caching policy, but confirm in writing before relying on it.
- *Evidence:* [https://developers.google.com/maps/documentation/placesinsights/overview](https://developers.google.com/maps/documentation/placesinsights/overview) (2026-09-13) · [https://mapsplatform.google.com/resources/blog/places-insights-in-bigquery-is-now-generally-available/](https://mapsplatform.google.com/resources/blog/places-insights-in-bigquery-is-now-generally-available/) (2025-09-30)

**P1 · Business Database API + Changes API** (Data Axle (formerly Infogroup)) — $8,000/yr (reported), low effort, high confidence

- *Closes:* (d) Openings/closings — this is the only verified-price source with real open and close DATES for the 10 categories that are structurally invisible to government filings (laundry, hair, nails, childcare, clinic, fitness, bank, hardware, convenience, tailor), the coverage hole ticketed as GTM-152 and asked as QUESTIONS T10.
- *Why this rank:* Cheapest verified price of anything that fixes the filing-blind-category problem, and it is the gap that most limits the screen's credibility.
- *Grain:* One record per business establishment, geocoded, with SIC/NAICS.
- *NYC coverage:* National file; NYC included. Phone-verified records, so coverage of small independents is better than press-derived sources.
- *Cannot see:* Phone-verified compilation, so a business with no listed phone or a mobile-only operator is thin or absent; the close date is a compiler's observation, not a filing. Compiled files historically lag immigrant-owned and cash-business independents -- the same direction as the §7.1 OSM bias.
- *Price:* VERIFIED $50-75 per 1,000 records per month on the vendor's own API page. At Loci's MN+BK universe this is a low-four-figure to low-five-figure annual line depending on refresh depth.
- *Licence:* Commercial product use is the intended use case for the API, BUT Data Axle's public T&Cs grant a limited, non-transferable, non-sublicensable licence for INTERNAL purposes only — an OEM/redistribution rider is needed before records appear in a sold product. Separately, their Historical Business Database is licensed only through university libraries for non-commercial research and is therefore disqualified.
- *Note:* Annual cost books the low end of the allocation estimate ($8-12k/yr at MN+BK refresh depth); the per-record price is verified, the annualisation is not.
- *Evidence:* [https://www.data-axle.com/data-solutions/apis/](https://www.data-axle.com/data-solutions/apis/) (2026-09-13) · [https://www.data-axle.com/terms-conditions/](https://www.data-axle.com/terms-conditions/) (2026-09-13)

**P2 · PincusCo NYC real-estate deal tracking** (PincusCo Media) — **$1,500/yr** (verified), high effort, high confidence

- *Closes:* (d) Pipeline and (g) property — cheapest NYC-native early signal on ownership and financing changes, which often precede a ground-floor re-tenanting by months and are invisible to the DOB/DCWP/SLA feeds D80 already ingests.
- *Why this rank:* Under $1,500/yr and NYC-specific; low integration value but high analyst value while the filing-blind categories remain unfixed.
- *Grain:* Deal / property level, NYC only.
- *NYC coverage:* NYC-native by construction — the most NYC-specific product in this list.
- *Cannot see:* Deal-and-filing journalism: it covers what is newsworthy, which means larger transactions and institutional owners. A small walk-up lease change is below its threshold. No API, so ingest is scraping a paywalled site.
- *Price:* VERIFIED published tiers: $10/mo (Posts) up to $125/mo (~$1,500/yr, Professional).
- *Licence:* Editorial subscription; systematic extraction into a sold product would need permission.
- *Evidence:* [https://pincusco.com/subscribe/](https://pincusco.com/subscribe/) (2026-09-13)

### (e) POI truth

**The question this graduates.** CONTEXT §7.1, the threat most likely to kill the
project: is the measured retail gap real, or is it a POI-coverage artifact? QUESTIONS
M1. An independent supply count per category per walkshed is the direct instrument — and
D11's corroborated-only supply set needs a third opinion before single-source inflation
can be ruled out.

**P1 · LiveXYZ NYC storefront census** (LiveXYZ) — $10,000/yr (tier floor — no price published), high effort, med confidence

- *Closes:* (e) POI truth and (g) vacancy — the only source that would let Loci measure its own undercount directly rather than infer it, answering M1 outright and replacing the LL157 registry whose Tax Class 1 coverage is 0.27% (the rowhouse corner store, exactly the bodega-gap typology).
- *Why this rank:* No substitute exists; if the raise funds one relationship-driven purchase, this is the one that makes the whole screen defensible in NYC.
- *Grain:* Individual storefront at street address; ~150,000+ NYC storefronts.
- *NYC coverage:* NYC-native and the most complete storefront ground truth that exists; full re-walk roughly every 90 days, daily map updates.
- *Cannot see:* A ~90-day re-walk means a storefront that opened and closed inside a quarter never existed. Field-survey coverage is what a surveyor could see from the sidewalk: upper-floor and rear-of-lot uses are invisible, and the re-walk cadence is likely denser on commercial corridors than on residential blocks.
- *Price:* No public rate card found. Used by NYC DCP for its 2019 and 2024 storefront-vacancy studies and by NYC SBS under the 'Shop Your City' partnership since Nov 2023 — those agency relationships are the realistic route to a price. Note: a DIFFERENT company, Live Data Technologies, is a name collision, not the same firm.
- *Licence:* Unpublished. Agency use is precedented; commercial redistribution inside a sold product would need explicit terms.
- *Evidence:* [https://www.live.xyz](https://www.live.xyz) (2026-09-13) · [https://www.nyc.gov/site/planning/data-maps/storefront-vacancy.page](https://www.nyc.gov/site/planning/data-maps/storefront-vacancy.page) (2026-09-13)

**P1 · Places API (New) — Place Details Pro** (Google Maps Platform) — $3,000/yr (reported), low effort, high confidence

- *Closes:* (e) POI truth — turns the single-source inflation problem into a measured one and is the direct instrument for QUESTIONS M1 (is the measured retail gap real or a POI-coverage artifact), the load-bearing P3 prediction in CONTEXT §7.1.
- *Why this rank:* Only source that can confirm a storefront is actually open, at a price small enough to run repeatedly rather than once.
- *Grain:* One record per Google place_id.
- *NYC coverage:* Effectively a census of consumer-facing NYC businesses; the ground truth Loci already budgeted for P3 validation.
- *Cannot see:* Consumer-facing bias: a business nobody searches for is thin in Google. `business_status` is Google's belief, not an inspection. Caching terms bar warehousing anything but place_id, so the record cannot be re-audited later -- only re-bought.
- *Price:* VERIFIED list price: Place Details Pro $17.00/1,000 (0-100k tier), 5,000 free calls/month; Essentials $5.00/1,000 with 10,000 free; Enterprise $20.00/1,000; Nearby Search Pro and Text Search Pro $32.00/1,000. The old $200/month credit is CONFIRMED GONE, replaced March 2025 by per-SKU free-call caps.
- *Licence:* Only place_id may be cached indefinitely. Name, hours and geometry have no general caching exception, so Loci can persist place_id plus point-in-time status snapshots but cannot warehouse full Google records. Popular-times is confirmed NOT in the API in 2026.
- *Note:* Annual cost books the low end of the $3-5k/yr allocation estimate for Details Pro plus the Aggregate API; the per-call price is verified, the call volume is an assumption.
- *Evidence:* [https://developers.google.com/maps/billing-and-pricing/pricing](https://developers.google.com/maps/billing-and-pricing/pricing) (2026-09-13) · [https://developers.google.com/maps/documentation/places/web-service/policies](https://developers.google.com/maps/documentation/places/web-service/policies) (2026-09-13)

**P1 · Places Aggregate API** (Google Maps Platform) — $100/yr (reported), low effort, high confidence

- *Closes:* (e) POI truth — an independent supply count per category per walkshed, which is precisely the corroboration D11 asks for (all POIs vs corroborated-only vs active-licensed) without the cost of enumerating every record.
- *Why this rank:* The cheapest verified way to audit Loci's supply counts against Google's, and it is a direct check on the §7.1 threat at essentially no cost.
- *Grain:* Aggregate count per query geometry; minimum search area 40m x 40m.
- *NYC coverage:* Full Google Places coverage of NYC.
- *Cannot see:* Returns a count with no records behind it, so a wrong count cannot be debugged. Minimum 40 m x 40 m search area, and it inherits every Google category-assignment quirk without exposing which place produced it.
- *Price:* VERIFIED $10.00/1,000 calls (0-100k tier) with 5,000 free calls/month, falling to $8.00 above 100k. One call per address x category x radius; a targeted MN+BK sweep of a few thousand cluster centroids is inside the free tier or a few hundred dollars.
- *Licence:* Standard Maps Platform terms. Because the response is an aggregate count rather than place records, it sidesteps most of the per-record caching restriction that limits Place Details.
- *Note:* Annual cost books $100 because a targeted MN+BK sweep of a few thousand cluster centroids sits inside or just above the 5,000-call/month free tier.
- *Evidence:* [https://developers.google.com/maps/billing-and-pricing/pricing](https://developers.google.com/maps/billing-and-pricing/pricing) (2026-09-13) · [https://developers.google.com/maps/documentation/places-aggregate/usage-and-billing](https://developers.google.com/maps/documentation/places-aggregate/usage-and-billing) (2026-09-13)

**P2 · Placekey** (Placekey (SafeGraph-originated open standard)) — **$3,000/yr** (verified), low effort, high confidence

- *Closes:* (e) POI truth — D79 found the dedup cluster_id is an input-order artefact (0.00% survive a row-order shuffle) and had to fall back on a content hash; Placekey is the industry-standard fix and makes every vendor file above joinable to Loci's ledger without rebuilding the dedup.
- *Why this rank:* The plumbing that makes every other purchase on this list cheaper to integrate; free tier probably suffices for MN+BK.
- *Grain:* One key per place (address + POI components).
- *NYC coverage:* Full.
- *Cannot see:* Not a data source -- a join key. It cannot add a POI Loci does not already have, and an address that geocodes wrongly gets a confidently wrong key.
- *Price:* VERIFIED: free tier 10,000 lookups/day; Silver $3,000/yr (6M lookups); Gold $15,000/yr (30M); Enterprise from $40,000/yr. Correcting a common assumption — it is NOT simply free at production volume.
- *Licence:* Open standard, partners include SafeGraph, Veraset, CARTO, Esri, Cuebiq, Regrid. Keys are designed to be shared.
- *Evidence:* [https://www.placekey.io/pricing](https://www.placekey.io/pricing) (2026-09-13)

**P2 · Yelp Places API (formerly Fusion)** (Yelp) — **$2,748/yr** (verified), low effort, high confidence

- *Closes:* (e) POI truth — a third corroborating source for D11's corroborated-only supply set, but it does not deliver the openings/closings signal it was shortlisted for.
- *Why this rank:* Verified price but the review-velocity and opening-date fields that justified it do not appear to exist — buy only as a corroboration layer.
- *Grain:* One record per Yelp business.
- *NYC coverage:* Dense in NYC for consumer-facing categories; thin for laundromats and tailors, the same bias as every consumer-review source.
- *Cannot see:* Review-platform coverage: dense for restaurants and bars, thin for laundromats and tailors. The opening date, closure date and review-velocity fields that justified the shortlist are not documented and are probably absent.
- *Price:* VERIFIED: Base $229/mo + $5.91/1,000 extra calls; Enhanced $299/mo + $6.57/1,000; Premium $643/mo + $14.13/1,000. There is NO ongoing free production tier in 2026 — only a 5,000-call/30-day trial. Above 150k calls/mo goes to a sales quote. 'Yelp Knowledge' appears to have been renamed/absorbed into the quote-only Yelp Insights API.
- *Licence:* Standard API terms with caching limits; opening dates, closure dates and review-velocity fields are NOT documented and are likely absent, which is the thing Loci actually wanted.
- *Evidence:* [https://business.yelp.com/data/products/places-api/](https://business.yelp.com/data/products/places-api/) (2026-09-13)

**P2 · Outscraper Google Maps extraction** (Outscraper) — $300/yr (reported), low effort, high confidence

- *Closes:* (e) POI truth — 10-20x cheaper per record than the official API and it can return popular-times, which the official API cannot; the price of that is contractual exposure.
- *Why this rank:* Cheapest possible POI corroboration and the only route to popular-times at scale, but it should be a one-off research audit rather than a product dependency.
- *Grain:* One record per Google place.
- *NYC coverage:* As complete as Google Maps.
- *Cannot see:* A scrape of Google, so it inherits every Google bias with none of Google's guarantees, and the record is a point-in-time capture with no provenance. Contractual exposure, not data quality, is the binding limit.
- *Price:* VERIFIED: first 500 records free, then $3.00/1,000 (501-100k) and $1.00/1,000 above 100k. An MN+BK sweep of ~230k locations is roughly $300-400.
- *Licence:* MATERIAL RISK — scraping Google Maps breaches Google's terms (a contract issue, not a CFAA crime per case law), and Outscraper's marketing grants no explicit redistribution or resale licence for the records. Legal sign-off required before any scraped record appears in a sold product. This is the cheap-but-dirty path; Places Aggregate API is the clean one.
- *Note:* Cost books the low end of the $300-400 estimate for a ~230k-location MN+BK sweep.
- *Evidence:* [https://outscraper.com/pricing/](https://outscraper.com/pricing/) (2026-09-13)

**P2 · Google Maps Businesses dataset** (Bright Data) — **$250/yr** (verified), low effort, high confidence

- *Closes:* (e) POI truth — a monthly-refreshed scraped panel is the cheapest possible substitute for Places Insights' snapshot history, at the cost of the same contractual risk.
- *Why this rank:* Lowest per-record cost anywhere; carries the same legal caveat as Outscraper.
- *Grain:* One record per business.
- *NYC coverage:* Filterable to NYC.
- *Cannot see:* Same Google-derived coverage and the same terms exposure as Outscraper, plus a delivery lag: a dataset snapshot cannot answer 'is it open today'.
- *Price:* VERIFIED: $250 minimum for 100,000 records (~$0.0025/record) one-time; Scraper API from $0.75/1,000 with a free tier.
- *Licence:* Same Google-terms exposure as Outscraper; no explicit resale licence granted. Legal review required.
- *Note:* Cost books the $250 one-time 100k-record minimum, not a subscription.
- *Evidence:* [https://brightdata.com/products/datasets](https://brightdata.com/products/datasets) (2026-09-13)

### (f) Chain expansion

**The question this graduates.** The chains watchlist infers expansion pressure from
press and first-seen dates. A real store-location file per brand says whether a chain is
actually moving toward a corridor, which is the difference between a gap and a gap
someone is already filling.

**P2 · RetailStat Location (incl. former Creditntell)** (RetailStat) — $10,000/yr (tier floor — no price published), high effort, med confidence

- *Closes:* (f) Chain expansion — D77's watchlist is 121 brands assembled from press with only one detect snapshot so far; a vendor feed replaces press-scraping and makes QUESTIONS T8 (do chain pipelines lead category gap closure) answerable without waiting a year for a second snapshot.
- *Why this rank:* Best-fit product for the chains gap on paper, but fully quote-gated and chain-only in a city dominated by independents.
- *Grain:* Brand and individual store location.
- *NYC coverage:* National chains operating in NYC; independent operators are out of scope by construction.
- *Cannot see:* Chains only, by construction. Independent operators -- the majority of the NYC daily-needs bundle -- are out of scope, so it can never speak to the gap itself, only to who might fill it.
- *Price:* No public pricing anywhere, no G2/Capterra listing to triangulate. Note Creditntell merged into RetailStat in 2023 and creditntell.com now redirects — they are one vendor, not two options.
- *Licence:* Unpublished.
- *Evidence:* [https://www.retailstat.com](https://www.retailstat.com) (2026-09-13)

**P2 · Coresight US Store Openings/Closures Tracker** (Coresight Research) — $10,000/yr (tier floor — no price published), high effort, med confidence

- *Closes:* (f) Chain expansion — the closest professional analogue to Loci's press-based watchlist, but at national brand grain it would inform the watchlist rather than replace it.
- *Why this rank:* Useful editorial input, wrong grain to feed a screen; buy only if a human analyst is curating the watchlist.
- *Grain:* Brand-level, national counts; not address-level.
- *NYC coverage:* National only — NYC store-by-store detail is not the product.
- *Cannot see:* Brand-level national counts. It cannot place a closure at a BBL, a corridor, or even a borough, so it is trend context and never an address-level input.
- *Price:* Quote-only across all membership tiers and even single-report purchase; no dollar figure published anywhere.
- *Licence:* Research subscription; republication restricted.
- *Evidence:* [https://coresight.com](https://coresight.com) (2026-09-13)

### (g) Ownership and vacancy

**The question this graduates.** The DOF storefront registry is self-reported and non-
filing is invisible. A BBL-keyed ownership file says WHO to call about the empty ground
floor 120 m from the gap, which is the step between a screen and a deal.

**P2 · Reonomy** (Altus Group) — **$4,800/yr** (verified), med effort, high confidence

- *Closes:* (g) Property — landlord identity and debt position per BBL, which decides whether a flagged vacancy is actually leasable; the LL157 registry is annual, self-reported, and non-filing is invisible (CONTEXT §3.3).
- *Why this rank:* Verified sub-$5k price and a BBL key that drops straight into Loci's schema.
- *Grain:* Parcel / building, keyed to APN (BBL in NYC).
- *NYC coverage:* Strong — Reonomy started as an NYC product.
- *Cannot see:* Ownership and debt, not occupancy -- it knows who owns the building and nothing about whether the ground floor is trading. Contact data is the product; the retail-tenancy field is thin.
- *Price:* VERIFIED self-serve: $500/mo month-to-month, or $400/mo ($4,800/yr) annual. API/bulk feed pricing unpublished.
- *Licence:* Self-serve seat is for internal use; bulk/derived redistribution requires the enterprise feed and separate terms.
- *Evidence:* [https://www.reonomy.com/pricing](https://www.reonomy.com/pricing) (2026-09-13)

**P2 · PropertyShark** (Yardi) — **$719/yr** (verified), high effort, high confidence

- *Closes:* (g) Property — a manual per-site due-diligence tool for the recommendation cards, not a pipeline input.
- *Why this rank:* Cheap analyst tool for card-by-card verification; adds little the free PLUTO/ACRIS stack does not already have.
- *Grain:* BBL / building.
- *NYC coverage:* NYC-native and deep.
- *Cannot see:* Derived from the same NYC public records Loci already ingests (PLUTO, ACRIS, DOB), so most of its value is convenience rather than new information. Web UI only, no API, so any bulk use is manual or a terms breach.
- *Price:* VERIFIED published: Pro $59.95/mo, Elite $79.95/mo, Platinum $169.95/mo.
- *Licence:* UI-only by design; bulk or automated extraction is restricted. Most of the underlying content is already free in PLUTO/ACRIS, which Loci ingests.
- *Note:* Cost books Pro at $59.95/mo = $719/yr, below the band floor; the band reflects the Platinum tier at $169.95/mo ($2,039/yr).
- *Evidence:* [https://www.propertyshark.com/mason/Subscriptions](https://www.propertyshark.com/mason/Subscriptions) (2026-09-13)

### (h) Demographics beyond ACS

**The question this graduates.** D12 asks for a demand control that is not income. ACS
tract estimates are 5-year-smoothed with large MOEs and are interpolated down to the
address; block-group spend potential and behavioural segments are the independent second
opinion on the residual Loci computes for itself.

**P1 · ArcGIS Business Analyst Web App (incl. Tapestry + Consumer Spending)** (Esri) — **$5,200/yr** (verified), med effort, high confidence

- *Closes:* (h) Demographics — Retail MarketPlace supply/demand gap by block group is an independent second opinion on the residual Loci computes itself, and Consumer Spending at block group replaces D81's national CEX quintiles, one of the caveats the model 'cannot escape'.
- *Why this rank:* $700-$5,200/yr is the best verified price-to-value in the whole list, and it is the cheapest way to sanity-check the gap measure against an independent commercial estimate.
- *Grain:* Census block group, aggregable to any trade-area ring or drive/walk time.
- *NYC coverage:* Full; block-group grain is finer than the tract grain Loci interpolates from ACS today.
- *Cannot see:* Modelled block-group estimates built on the same ACS backbone Loci already uses, so it is a second opinion on the interpolation, not an independent measurement. Retail MarketPlace's supply side is a compiled business file with the compilation biases above.
- *Price:* VERIFIED list price on Esri's own AWS Marketplace listing: Standard $700/yr and Advanced Bundle $5,200/yr per named user. Esri.com itself is quote-gated. Vendr's 32-deal median of $25,281/yr reflects negotiated enterprise agreements, a different population. Tapestry and Consumer Spending are bundled, not sold standalone.
- *Licence:* Esri's master agreement restricts sublicensing and redistributing underlying data; a standard seat licence does NOT clearly permit backing a paid product resold to third parties — an OEM agreement is needed. Also: legacy Esri Tapestry retires June 2026 in favour of ArcGIS Tapestry with non-1:1 segment redefinition, so anything built on the old segments needs migrating.
- *Evidence:* [https://aws.amazon.com/marketplace/seller-profile?id=esri](https://aws.amazon.com/marketplace/seller-profile?id=esri) (2026-09-13) · [https://www.esri.com/en-us/arcgis/products/arcgis-business-analyst/](https://www.esri.com/en-us/arcgis/products/arcgis-business-analyst/) (2026-09-13)

**P2 · PersonaLive segmentation** (Spatial.ai) — **$5,100/yr** (verified), med effort, med confidence

- *Closes:* (h) Demographics — behavioural segments are the non-income demand control D12 asks for (where absent supply reflects revealed demand rather than a gap, e.g. bars in Midwood and Borough Park), which ACS income and age cannot express.
- *Why this rank:* Best published pricing transparency in the segmentation category and it targets a specific named open question rather than generic demographics.
- *Grain:* Census block group or custom trade area.
- *NYC coverage:* National; block-group grain covers MN+BK fully.
- *Cannot see:* Modelled social/behavioural segments at block group, inferred from social and mobility signals rather than measured. Segment labels are proprietary and unauditable -- there is no way to test the assignment against ground truth.
- *Price:* VERIFIED published tiers: Analyst $5,100-$6,000/yr; Media Buyer $8,400-$9,600/yr; Strategist $16,200-$18,000/yr (includes credit-card spend insights). Pricing scales with trade-area count, so an NYC-wide deployment could land at the top of the 10k-50k band.
- *Licence:* Redistribution terms for a resold product are not published and need direct confirmation.
- *Evidence:* [https://www.spatial.ai/pricing](https://www.spatial.ai/pricing) (2026-09-13)

### (i) Sidewalk counts

**The question this graduates.** The same restricted-range problem as (a), from the
supply side: DOT's 114 points were chosen for traffic engineering on busy commercial
streets, so a rank correlation against them is fitted on the busy tail. Counts on quiet
residential blocks are what would make the access proxy testable where it matters.

**P2 · Computer vision on NYC DOT traffic camera frames (BUILD, not buy)** (self-built on NYCTMC feeds) — $4,320/yr (reported), high effort, med confidence

- *Closes:* (i) Sidewalk counts — the only route to more than 114 observation points without buying hardware, but CONTEXT already documents why the resulting number is a count on an unknown catchment.
- *Why this rank:* Cheapest way to multiply observation points ninefold, but the unknown-catchment problem and the C&D precedent mean it is a research probe, not a product dependency.
- *Grain:* Per camera, per sampled frame; the catchment is unknown and non-constant because bearing, field of view, height and lens are all unpublished.
- *NYC coverage:* 969 cameras (MN 376 / BK 204), but sited at signalised arterial intersections to watch vehicle queues — a quiet residential block has no camera, so the siting bias runs in the SAME direction as the DOT count points it is meant to escape.
- *Cannot see:* Cameras sit at signalised arterial intersections chosen to watch vehicle queues, so the siting bias runs in the SAME direction as the DOT count points it is meant to escape -- a quiet residential block has no camera. Bearing, field of view, height and lens are unpublished, so a person count is a count on an unknown, non-constant catchment: a stock, never a flow.
- *Price:* Compute only. Credible published industry figures: ~$24/camera/month on a rented cloud L4 GPU at full continuous stream density, cut 3-6x by dropping inference to 5-10 fps; or an ~$8,000 on-prem L4 server supporting ~24 simultaneous 1080p streams. For periodic sampling of a few dozen target blocks this is a few hundred dollars a month at most.
- *Licence:* MATERIAL RISK — no published, versioned terms-of-use text is retrievable (the site is a JS SPA and the terms link is client-side routed), but NYC DOT sent a cease-and-desist to at least one creative-reuse project in 2024 despite the feeds being technically open. Treat commercial automated scraping as legally ambiguous, not permitted.
- *Note:* BUILD, NOT BUY -- the sampler already exists (`loci sidewalk-count`, d948b6d). Cost books 15 DOT-adjacent cameras at ~$24/camera/month of rented cloud GPU = $4,320/yr at full continuous stream density; periodic sampling at 5-10 fps cuts that 3-6x.
- *Evidence:* [https://webcams.nyctmc.org/about](https://webcams.nyctmc.org/about) (2026-09-13) · [https://wttdotm.com/blog/tcpb_part_2.html](https://wttdotm.com/blog/tcpb_part_2.html) (2025) · [https://www.reddit.com/r/nyc/comments/1hcw3kc/nyc_traffic_camera_selfie_creator_holds_cease_and](https://www.reddit.com/r/nyc/comments/1hcw3kc/nyc_traffic_camera_selfie_creator_holds_cease_and) (2024-12)

---

## P3 — checked and rejected, recorded so it is not relitigated

Each of these was a plausible buy until something specific killed it. The reason is kept so a later session does not spend the survey again.

| Source | Gap | Price | Why it is P3 |
|---|---|---|---|
| **Dewey Data (Advan/SafeGraph reseller channel)** — Dewey Data | a | **$3,600/yr** (verified) | The obvious cheap route to Advan data and it is contractually closed; record it so nobody proposes it again. DISQUALIFIED … |
| **CE Vision** — Consumer Edge | b | $10,000/yr (tier floor — no price published) | Now the same corporate parent as Earnest; negotiate once, not twice, and lead with the Earnest ZIP table. Public terms of use bar reselling, redistributing or creating derivative commercial products without written consent. |
| **CoStar Retail** — CoStar Group | c | $15,000/yr (reported) | Best data, unusable licence; list it so the decision is explicit rather than revisited every quarter. NON-STARTER as written. CoStar is the most litigious vendor in this space, with 30+ copyright and trade-secret suits on record (CoStar v … |
| **D&B Data Blocks / Direct+ / Hoovers** — Dun & Bradstreet | d | $41,400/yr (reported) | Costs roughly an order of magnitude more than Data Axle and lacks the one field the gap needs. Enterprise licences are per-use-case; redistribution requires specific terms. |
| **Firefly (US foodservice operator database)** — Datassential | d | $10,000/yr (tier floor — no price published) | Duplicates Loci's strongest existing asset (DOHMH near-census) and is resale-restricted. Technomic/Ignite has the same shape and no published terms at all. Datassential's published Additional Product Terms explicitly bar embedding their data or reports into a third-party product for resale … |
| **Lightcast job postings + LMI** — Lightcast (formerly Emsi Burning Glass) | d | **$7,500/yr** (verified) | Right idea, wrong grain; revisit only if Lightcast can demonstrate address-resolved postings. Terms explicitly bar redistributing the dataset to third parties on an on-demand or standalone basis — usable as an internal signal only. |
| **PRIZM Premier / Claritas 360** — Claritas | h | $10,000/yr (tier floor — no price published) | Industry standard and contractually incompatible; Spatial.ai or Esri are the workable substitutes. Sharpest licence restriction found in the entire survey … |

---

## If we had $25k / $100k / $250k a year

**At $25k a year.** Buy nothing that requires a sales call. Spend it on the four verified-price items that each close a different named gap and can be live inside a sprint: Data Axle's Business API for the ten filing-blind categories (~$8–12k/yr at MN+BK refresh depth, the single highest-value line in the list because GTM-152 is the ticket that most limits the screen's credibility); Google Places Details Pro plus the Aggregate API for POI truth and the §7.1 coverage-bias audit (~$3–5k/yr, and the Aggregate SKU is largely inside its 5,000-call free tier); Esri Business Analyst Advanced at **$5,200/yr** for block-group Consumer Spending and Retail MarketPlace, the cheapest independent second opinion on the residual Loci computes itself; and Reonomy at **$4,800/yr** for BBL-keyed ownership. Then take the free wins nobody has taken: REBNY and Cushman corridor rents, the NYC Eco-Counter feed, the BID pedestrian PDFs. That is roughly $23k and it graduates gap (d) outright, moves (e) from argument to measurement, and gives (c) a real benchmark for the first time.

**At $100k a year.** Add the one thing money cannot substitute for. Put $40–60k against foot traffic — Advan first (it owns the former SafeGraph Patterns business and its POI-visit schema drops cleanly into DuckDB), Placer.ai second (real government contracts run $8–27.5k/yr, but its ban on redistributing derived data must be renegotiated before a Placer number appears on a card sold to anyone). Run a $2–3k BestTime.app pilot in parallel, purely to test whether an hourly busyness curve discriminates dayparts where the transit levels demonstrably do not. Spend $20–30k on LiveXYZ, the only true NYC storefront ground truth in existence; the route in is the NYC DCP and SBS relationships it already has. Reserve $10k for CompStak Enterprise or Crexi so the rent line on the card stops resting on a single comp.

**At $250k a year.** The binding constraint stops being money and becomes licence terms, so budget for lawyers as a line item. Add SafeGraph Spend or Mastercard Retail Location Insights ($50–120k) — address-grain and census-block-grain spend respectively — because that is what takes the economics grade off D for the nine categories D81 ships as "not modelled", and gives lambda its first out-of-sample test. Add Spatial.ai PersonaLive ($16–18k) for the non-income demand control D12 asks for. Fund a standing **$15–25k/yr retainer for redistribution riders** on Placer, Data Axle, Esri and whichever spend vendor wins — every one of them grants internal-use-only by default, and the whole list is worthless in a product that is sold. Keep $20k unspent against the LiveXYZ and DOT sensor conversations, which are relationship-priced and will not quote before a real meeting.

### The line item that is not a data source

**Redistribution riders — $15,000–$25,000/yr, legal retainer, not a data purchase.** Every commercial source in the table above grants an INTERNAL-USE-ONLY licence by default. Placer.ai explicitly prohibits reselling, redistributing or sublicensing its data *or derived data*, and prohibits training models on it. Data Axle's public T&Cs grant a non-sublicensable internal licence and need an OEM rider before a record reaches a sold product. Claritas bars distributing "Licensed Materials or derivatives" outright. CoStar has thirty-plus suits on record. Budget the rider alongside the subscription or the number cannot go on a card a customer sees — which is the whole point of buying it.

---

## Appendix — not on the list, and why

### Free, or already ours

Shortlisted as paid, found to cost nothing. Deliberately NOT registry wishlist entries: a wishlist entry is a line item with a price, and a $0 line item vanishes from every total. Take these regardless of the raise.

- **REBNY Manhattan Retail Report (First Half 2026, 16 corridors) and the separate Brooklyn Retail Report** — free PDFs, asking rent per sf, scoped exactly to the D78 MN+BK screen. Shortlisted as paid; it is not.
- **Cushman & Wakefield MarketBeat Manhattan Retail (Q2 2026, 12 corridors) and CBRE Manhattan Retail Figures (Q2 2026, 16-corridor blended)** — free, quarterly. Colliers and Newmark were checked and publish no NYC retail corridor report — a Newmark national $54.60/sf figure is not an NYC number.
- **NYC Bicycle and Pedestrian Counts (`ct66-47at` / `6up2-gnw8`)** — free Socrata API, Eco-Counter sensors at 15-minute resolution, last modified 2026-09-13. Only 4 pedestrian-capable locations, all greenway/park/bridge — but it is the only NYC source with real time-of-day resolution and Loci is not using it.
- **NYC BID pedestrian reports** — Grand Central Partnership publishes monthly count PDFs (verified through Feb 2026, some months broken out by location); Times Square Alliance publishes weekly and monthly counts from 27 cameras at 33 locations; Flatiron/NoMad publishes quarterly. Manhattan core only, PDF parsing required.
- **NYC SBS Commercial District Needs Assessments** — free per-corridor reports built from door-to-door merchant surveys and a storefront/retail-mix inventory. Real ground truth, PDF-only, corridor-by-corridor, dated.
- **NYC DOT Pedestrian Mobility Plan demand map** — free citywide ordinal classification of every street into five pedestrian-volume categories. Not a volume estimate, but a coarse prior for exactly the quiet blocks the 114 DOT points cannot reach.
- **Overture Maps / Foursquare OS Places** — already ingested. Licence confirmed: Foursquare-sourced records Apache-2.0, most others CDLA-Permissive-2.0, AllThePlaces CC0. Meta contributes the plurality (~58M of ~74M), not Foursquare.
- **Indeed Hiring Lab** — CC BY 4.0, the only unambiguously resale-friendly licence in the whole survey, and the coarsest grain (country/city index).

### Defunct, renamed, or not what the name implies

- **Placemeter** — acquired by NETGEAR, closed 2016-11-30 for $9.6M, folded into Arlo camera analytics. Gone.
- **PlanetRetail RNG** — Ascential → Flywheel Digital → sold to Omnicom (~$835M, Q1 2024). Domain no longer resolves.
- **Localize.city / Nestio** — Localize shut US operations August 2024 and was never a storefront vendor anyway; Nestio was absorbed into Funnel Leasing.
- **Near Intelligence** — Chapter 11 on 2023-12-08; assets sold and now operating as **Azira**, actively shipping in 2026. Buyable again, under a different name.
- **Creditntell** — merged into **RetailStat** in 2023; creditntell.com redirects. One vendor, not two options.
- **eSite Analytics / Buxton / Springboard** — eSite acquired by Kalibrate (2021); Buxton is now "Audiense In-Person powered by Buxton" and buxtonco.com redirects; Springboard was acquired by MRI Software (2022), now MRI OnLocation, with a verified £3,600/yr per external counter on UK G-Cloud.
- **Numina** — Brooklyn-based and the obvious NYC choice, but it never secured an NYC procurement contract and its NYC pilot data does not persist anywhere. NYC DOT's actual sensor vendor is VivaCity — registered here as `nyc_dot_vivacity_sensors`.
- **Replica** — the `/private-sector` page now 404s and the site brands itself for public agencies; one WA sole-source notice values a statewide subscription at $250,000. It may not sell to Loci at all.
- **Apple Mobility Trends / Google COVID-19 Community Mobility** — discontinued 2022-04-14 and 2022 respectively. Google Environmental Insights Explorer is alive but is a building-energy and emissions tool, not foot traffic.

### Corrections to assumptions worth recording

- **SafeGraph did not shut down.** It sold the *Patterns* foot-traffic line to Advan (2023–24) and still sells Places and Spend in 2026. Spend is address/POI-grain — the finest of any spend product surveyed.
- **Bloomberg Second Measure is still operating**, not shut down — but it is Terminal-gated with no standalone path.
- **Mastercard SpendingPulse is national/state/DMA/county only.** There is no ZIP, tract or address grain and redistribution is expressly barred; it cannot do what it was shortlisted for. (Retail Location Insights, in the table above, is the block-grain product.)
- **Visa has no equivalent product for an outside buyer** — its three adjacent offerings are restricted to Visa's own issuer, acquirer and commercial-card clients.
- **Environics Analytics DemoStats is Canada-only** at its core.
- **Google popular-times is still not in the official Places API** in 2026, and the $200/month Maps credit is gone, replaced in March 2025 by per-SKU free-call caps.
- **Yelp has no ongoing free production tier** — only a 5,000-call/30-day trial — and its API documents no opening dates, closure dates or review velocity, which is what it was shortlisted for.
- **Placekey is not simply free** at production volume: $3,000/yr Silver, $15,000/yr Gold, $40,000/yr Enterprise above the 10k/day free tier.
- **Buxton, Kalibrate, SiteZeus and Tango are competing products, not data sources.** SiteZeus (relaunched as "Atlas", ~May 2026) is architecturally the closest analogue to what Loci does internally and is the nearest true competitor for the raise narrative.

### Free but eligibility-gated, and the one ask

Registered in `registry.yaml` at `status: planned`, cost 0, because neither is a purchase:

- **NYC DOT VivaCity sidewalk sensors** (`nyc_dot_vivacity_sensors`) — an ASK, not a buy. DOT piloted 20 intersections in 2023 and announced expansion to ~100 locations citywide on 2026-06-04, **explicitly including residential neighborhoods**. That roster is the non-corridor validation set gap (a) and D76 / GTM-147 need, and the route in is a data-sharing request. Buying our own is the fallback the UK G-Cloud 14 benchmark of £4,095/unit/yr prices.
- **Strava Metro** (`strava_metro`) — free, and **Loci does not qualify**. Eligibility in 2026 covers public agencies, an Academic Researchers Program and trail/advocacy nonprofits; consultants get in only under contract with an agency that already has access. No path exists for a private venture-backed startup, and the terms forbid commercial exploitation of the raw data. Kept at `planned` rather than `excluded` only because it opens if Loci ever works under a DOT or MPO contract — and the activity skew (athletic and recreational trips, not errand walking) makes it the wrong behaviour for a daily-needs screen anyway.

