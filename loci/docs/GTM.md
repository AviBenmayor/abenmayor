Strategy memo — 2026-09-13 — drafted by the investor lens, red-teamed by the contrarian; owner decides.

# Loci — go-to-market

> ## What we will not claim
>
> 1. "No buyer has seen Loci: every price here derives from published competitor contracts rather than a quote we have issued, and the first three customer conversations may invalidate §4."
> 2. "Loci measures supply thinness, not site quality — an address with no competitors may have none because the location cannot support retail — and we have not run the retrodiction (score 2023–24 openings, test whether supply ratio predicts survival) that would show our screen improves a siting decision at all."
> 3. "Our lead-time medians rest on N=67 / N=741 / N=22, our ledger holds one month with 47.7% censored, and Google Places Insights already sells monthly POI snapshots back to January 2024 — the asset we call a moat is thinner and younger than a substitute anyone can buy."

---

## 1. Value proposition, and what we can prove

**The paragraph.** Loci is an address-level screen of New York's walkable daily-needs retail. For every residential lot and street midpoint in Manhattan and Brooklyn, across fifteen categories, it answers: what is reachable on foot (network distance, not a circle), how that supply compares to the borough baseline, what is already filed with the government but not yet open, and — with a stated evidence grade — whether you should act on any of it. It runs on auditable public data, so a buyer can re-derive every number, and it refuses to render a verdict when the evidence is thin.

**What we sell is cost of search, not better decisions.** The honest claim is that assembling this for one address — fifteen categories, walk-network distances, borough baselines, seven filing feeds, zoning and character — takes an analyst days and takes Loci minutes. That is measurable and defensible. The claim that Loci *avoids a bad site* is not established: Loci measures supply thinness, and an address with no competitors may have none because the market already tested it. Foot traffic is context-only with 65% of Brooklyn addresses reading zero (D76), so we cannot separate "underserved" from "unviable" in exactly the addresses we flag. That is the same reverse causality that killed the causal thesis. **No build-out-percentage framing, no failure-rate math, in any deck.**

**The next analytical deliverable is the retrodiction, and it gates the sales claim.** Score 2023–24 openings (52.3% carry source dates) and test whether the supply ratio at open predicts still-open today. If it does, we have a decision-value claim for the first time. If it doesn't, we say so and sell cost-of-search only. Until it runs, there is no demonstrated decision value.

**Three things we can prove today.** (i) Address-grain walk-network supply and a borough-baseline supply ratio, city-wide, MN+BK, fifteen categories (D73) — competitors deliver block-group rings or one subject property. (ii) A storefront lifecycle assembled from 232,667 filings across seven agency feeds, reconciled to 135,912 business-at-BBL pipelines (D80). (iii) An evidence grade on every claim: the first Gowanus card read *"do not act on this data"* for 14 of 15 categories (D74).

**Two we cannot.** Economics is **grade D** — no purchased spend or rent data; revenue is modelled for restaurant only (grade C, leave-one-ZIP-out backtest), nine categories honestly "not modelled" (D81). Foot traffic is a proxy, never a grade and never a denominator; DOT camera sidewalk counts have **N=0 validated weekday samples** (D85).

And the disclosure that leads every conversation: **the causal thesis was tested and rejected.** The 2013 gap predicts *lower* subsequent population growth (β = +0.069, p = 4.7e-16); parallel trends are broken. Loci ranks present-day supply. It does not forecast appreciation.

---

## 2. Is anyone selling the model, or the complete dataset?

No — with one substitute closer than the first draft admitted.

- **Esri Retail MarketPlace** (dollar leakage/surplus) — **discontinued**; only 2017 data on 2010 geography survives, no replacement date, because e-commerce broke the local-sales model ([Esri](https://community.esri.com/en/discussion/1206027/retail-marketplace-report-replacement-leakage-surplus-factor)).
- **Placer.ai Void Analysis** — property-in, tenant-list-out, ranked by Relative Fit Score; needs a branded panel signature, so effectively chain-level ([placer.ai](https://www.placer.ai/guides/void-analysis)). No dataset SKU.
- **Buxton / Intalytics / SiteZeus** — bespoke per-brand models, one client, one community ([Ames IA, $35,000](https://vault.amesnews.net/gov/city/CouncilPackets/2012/030612CouncilAgenda/29.pdf)).
- **Cherre / Reonomy / PropertyShark** — property and ownership only.
- **Live XYZ** — 160,000+ NYC storefronts, and **NYC SBS cites it as a supplier** in the FY25 BID Trends Report ([on.nyc.gov/fy25bidtrends](https://on.nyc.gov/fy25bidtrends)). A census with vacancy, not a gap model.
- **Google Places Insights (BigQuery)** — **monthly POI snapshots back to January 2024** at ~**€3,300/mo, 12-month minimum** ([Ubilabs](https://ubilabs.com/en/google-maps/places-insights)). This is the substitute for our ledger and it is 32 months older. Name it before a buyer does.

**Nearest substitute a buyer prices us against: Placer.ai + Live XYZ, ~$30k–$50k/yr combined, both quote-gated.** Read Esri's retirement correctly — evidence the concept is hard, not evidence of a vacuum.

---

## 3. Competitor price map

| Vendor | Buyer | Unit | Verified price | Source |
|---|---|---|---|---|
| Placer.ai | Retail / CRE / civic | annual sub | **$31,000/yr** (Bloomington IN); gov $8k–$27.5k; enterprise $12k–$50k+ | [order form](https://bloomdocs.org/wp-content/uploads/simple-file-list/23-767_PlacerAI_Data_Analysis_Software_Agreement_Packet-1.pdf), [CivicIQ](https://civiciq.com/blog/placer-ai-government-contracts-how-cities-and-counties-use-location-analytics-in-2026) |
| Buxton (Audiense) | Cities, EDOs, chains | model + seat | **$35,000** build; SCOUT-only $15,000/yr; Mitchell SD $65,000/yr | [Ames](https://vault.amesnews.net/gov/city/CouncilPackets/2012/030612CouncilAgenda/29.pdf), [Mitchell](https://www.cityofmitchellsd.gov/AgendaCenter/ViewFile/Item/4224?fileID=5405) |
| Esri Business Analyst | GIS teams, EDOs | seat/yr | **$3,908–$13,395/yr**; $1,100 single-use | [NC MPA](https://it.nc.gov/documents/it-contracts/esri-mpa-pricing/open), [Idaho](https://purchasing.idaho.gov/wp-content/uploads/Esri_Price_List.pdf) |
| CoStar | Brokers, lenders | seat/market | median **$40,000/yr** (list $71k); Vendr ACV $15,130 | [PriceLevel](https://www.pricelevel.com/vendors/costar/pricing), [Vendr](https://www.vendr.com/buyer-guides/costar) |
| **Reonomy** (Altus) | Brokers, investors | seat | **$4,800/yr** published | [reonomy.com/pricing](https://www.reonomy.com/pricing) |
| **GrowthFactor** | 10–100-unit retailers | seat/mo | **$200/mo** ($2,400/yr) self-serve | [growthfactor.ai](https://www.growthfactor.ai/resources/blog/retail-site-selection-software) |
| Leasecake | Multi-unit operators | per location/mo | **$8 / $12 / $18** per location per month | [SoftwareConnect](https://softwareconnect.com/reviews/leasecake) |
| SBA feasibility study | Lenders, franchisees | per report | **from $4,900**, SOP 50 10 8-aligned; retail $8k–$25k | [MMCG](https://www.mmcginvest.com/retail-feasibility-study), [OGS](https://ogscapital.com/article/feasibility-study-cost-2025) |
| Google Places Insights | Analysts | annual sub | **€3,300/mo**, 12-mo min | [Ubilabs](https://ubilabs.com/en/google-maps/places-insights) |
| SizeUp / Localintel | Independents via EDOs | free, white-labelled | **$0 to the business** | — |

**Where we sit:** the per-seat anchors are **Reonomy $4,800 and GrowthFactor $2,400**, not Placer. "Below Placer" is an apology, not a price — $6k clears no procurement threshold and earns no champion.

---

## 4. ICP, re-ranked

Two ICPs is no ICP. The evidence grade is an asset **only where the buyer's liability is being wrong on the record.**

1. **Tenant-rep brokers needing a defensible memo.** Fastest cycle, a research budget that already buys seats, and referral flow. Sell a seat, not a deal-priced report.
2. **Lenders and feasibility shops — B2B2B.** Sell Loci as a **$500–$1,500 subcontracted input into their $4,900 SBA study**, not against it. They carry preparer's liability; we supply the market-supply section and they keep the pro formas and SOP 50 10 8 compliance we cannot satisfy. Best structural fit in the list.
3. **BID and SBS grant writers.** Neighborhood 360° grants run to **$300,000/yr for three years** ([nyc.gov](https://www1.nyc.gov/site/sbs/neighborhoods/neighborhood-360-grants.page)); the money attaches to the grant, not the study. A corridor supply table is an input to an application, which is a faster path than procurement.
4. **3–30-unit operators with no real-estate department.** Real willingness to pay, no internal alternative; the $500–900 report lands here.

**Chains and franchisors are a logo and partnership channel, not a paying segment yet.** A VP RE at Raising Cane's or Paris Baguette buys models calibrated on their own store P&Ls — the one asset Loci can never have — and "do not act" for 14/15 is, to them, a missing product. The filings hook is weaker than it looked: Chipotle's 16 BK/MN/QN filings are public records *their own broker filed*, and filings see only food, drink, grocery and pharmacy — the categories DOHMH and Datassential already cover best.

**The 121-brand watchlist stays valuable, repurposed:** it is a lead list *for brokers* ("here are fifteen brands adding stores in your submarket, with their filings") and a logo slide. Top of the list by net new in 12 months: Luckin Coffee (+15), NAYA (+10), Raising Cane's (+9), Blank Street (+8), Joe & The Juice (+7), Paris Baguette (+7), CAVA (+6), Apollo Bagels (+5), The Learning Experience (+5), Bluestone Lane (+5), Los Tacos No. 1 (+5), Chipotle (+5), HeyTea (+5), Wingstop (+5), LaundryBee (+4).

**Top-two detail.**

| | Tenant-rep brokers | Lenders / feasibility shops |
|---|---|---|
| Budget owner | Team lead / research budget | Credit ops, or the study preparer's COGS |
| Deal size | $4,800–$7,200 per seat/yr | $500–$1,500 per study, volume-recurring |
| Cycle | 1–3 months | 3–9 months (compliance) |
| Objection | "CoStar and Placer already cover me" | "Our preparer already does this section" |
| Proof needed | One memo a broker put in front of a client | One study where our section shipped verbatim |

---

## 5. Pricing and SKUs

| SKU | Price | Role |
|---|---|---|
| **Site-memo retainer** (lead with this) | **$20,000 / quarter**, 8–10 sites, includes camera verification and manual pipeline diligence | **The only SKU with demonstrated willingness to pay — it is consulting the founder already sells.** |
| **Subcontracted study input** | **$500–$1,500 per site** to a feasibility shop | B2B2B, recurring, rides someone else's compliance |
| **Operator report** | **$500–$900**, or **free into a seat** | Marketing, not revenue. The operator carrying the Good Guy personal guaranty is the only party feeling six figures of downside |
| **Per-seat licence** | **$4,800/seat/yr**, team of 5 at $18,000 | Anchored on Reonomy $4,800 / GrowthFactor $2,400, sold into the research budget. **No 20-seat tier** — $900/seat is under cost to serve |
| **Data / API licence** | **$50k–$120k/yr** | **Blocked until redistribution riders exist.** Do not forecast it |

**Cost of goods.** The full P1 wishlist is ~**$74k/yr**. The sprint subset is ~$23k: Data Axle Business API ($8–12k), Google Places Details Pro + Aggregate (~$3–5k), Esri BA Advanced (**$5,200**), Reonomy (**$4,800**), plus free wins (REBNY and Cushman corridor rents, Eco-Counter, BID pedestrian PDFs). The $23k subset is covered by **one and a half retainer quarters**. Every P1 vendor grants internal-use-only by default: a redistribution rider is a precondition, not a nice-to-have.

---

## 6. Wedge and sequencing, next two quarters

**Q4 2026 — sell the retainer, run the retrodiction.** Two retainers ($40k) fund the $23k data buy and the founder's time. In parallel, the retrodiction ships: it is the cheapest thing that could turn cost-of-search into decision value, and it uses data already in the warehouse. Give the operator report away to seed references.

**Q1 2027 — convert to seats.** Broker seats at $4,800 off retainer references and the watchlist hook; one feasibility shop signed as a subcontract channel. Public sector only if a BID grant writer pulls us in — procurement takes 6–12 months and cannot be pushed.

**What the raise converts:** a head start into customers before it evaporates. Concretely — the $74k P1 buy (takes economics off D for the filing-blind categories, the single largest credibility unlock), Queens and the Bronx, and the legal budget for redistribution riders. It does not buy a moat; see §7.

**Metrics that prove the wedge:** 2 signed retainers; 1 feasibility-shop subcontract; 3 broker seats; the retrodiction run and published whichever way it comes out; 6 consecutive monthly ledger snapshots with censoring below 20%.

---

## 7. Moat, honestly

**What is real:** the **BBL reconciliation** — seven feeds matched to business-at-BBL, 92% sole-pair — is months of NYC-specific work that does not generalise and cannot be bought; and **the operator**, which is to say the founder's judgment about what the data will not say.

**What is not yet real.** The first-seen ledger holds **one month, 0 observed rows, 47.7% censored** (D79). "Worth more every month" means worth nothing now, and **Google Places Insights sells a 32-month monthly POI history to anyone with €3,300/mo**. The lead-time headline rests on **N=67 strict / N=741 reconciled / N=22 liquor** (D80), with p25 178 / p75 378 days on the strict figure — a small sample sold as a feature, and the most overclaimed number in the first draft. Quote it with the N and the quartiles or not at all.

**Duration.** The head start is measured in **months, not years**. Placer or Esri could add a filings layer; Live XYZ already holds the census and the city relationship. Incumbent economics point away from it — Placer monetises a panel, Esri retired its gap product rather than rebuild it — which is a reason to move, not a reason to relax. **The moat resets to zero in city number two**, which is the central tension in §8.

---

## 8. The business — narrative, raise, TAM, capacity

**Narrative: a consulting-funded data company, not SaaS.** Every SKU routes through the founder's calendar; the data licence is blocked on riders that do not exist. Price it on earnings, not ARR, until a self-serve path is named. "Consulting-funded data company" is fundable at this stage; "SaaS" at zero customers is not.

**Raise size and runway — an owner decision, with the arithmetic.** Annual burn at one founder: data $74k (P1 full) or $23k (sprint subset), founder comp $150k, legal for redistribution riders $25k, compute and tooling $15k → **$215k–$265k/yr**. Cycles of 2–6 months mean roughly nine months before revenue is informative. An 18-month runway is therefore **$400k–$500k**, and the honest framing is that it buys one city's proof plus the first attempt at city #2. A smaller raise ($150k) buys the sprint data subset and keeps the business consulting-funded — slower, less dilutive, and arguably the better trade given the TAM below.

**TAM sketch, and the tension.** ≈200 NYC tenant-rep brokers × 20% penetration × $12k ≈ **$480k** caps the NYC seat business. Retainers cap on founder capacity: 4 concurrent at $20k/quarter ≈ $320k/yr gross. Subcontracted study inputs add perhaps $100–200k at plausible volume. **NYC tops out under $1M.** So the raise is a bet on city #2 — and §7 says the moat resets there. Either that bet is made explicitly, or the business is a very good consultancy with a proprietary tool and should not raise venture money at all. **That choice is the memo's real decision.**

**CAC and sales capacity.** One person, 2–6-month cycles, no SDR. Realistic: 10–15 first meetings per month at part-time effort, ~20% to a second meeting, single-digit closes per quarter. At a $4,800 seat, any CAC above ~$1,500 fully loaded makes seats unprofitable to sell by hand — which is a second argument for leading with the $20k retainer and letting seats arrive as a by-product.

**Live XYZ: partner or compete.** They hold the storefront census *and* the SBS relationship. Competing means rebuilding a 160k-storefront ground truth we do not have; partnering means they supply supply-side truth and we supply the gap model and filings lifecycle. **Ask them for a quote and a conversation in the same email** — the answer determines whether the public-sector channel is open at all.

**ToS and resale status of what ships today — unresolved and load-bearing.** StreetEasy content in the warehouse is flagged *internal analysis only, no redistribution*. DOT camera frames, Google Places API calls, and Tavily press enrichment were all acquired under terms written for internal use, and Citi Bike data has its own attribution conditions. **Before a single paid deliverable leaves the building, one pass over every source's redistribution clause, with anything ambiguous excluded from the sold artifact.** This is the cheapest possible unforced error.

**Why you.** The memo must answer it and currently cannot: a solo fractional GTM-engineering consultant, part-time, no co-founder, no domain hire. The defensible version is that the operator *is* the product right now — the retainer sells judgment with data attached. State whether this goes full-time on funding, and name the second hire.

---

## 9. Risks, and the cheapest test for each

| Risk | Cheapest test |
|---|---|
| **Zero customer evidence.** Every price is derived from competitor contracts. | Three discovery calls — one broker, one feasibility shop, one operator. One week. Do this before anything else. |
| **Grade-D economics make 14/15 categories unsellable.** | Show the real card to those same three and ask what they'd pay for the restaurant-only version. |
| **No demonstrated decision value.** | The retrodiction: score 2023–24 openings (52.3% carry dates), test supply ratio vs still-open. Data is in hand. |
| **P3 coverage bias unresolved** — the "gap" may be a data hole in the low-income areas we flag. | The stratified Google Places sample: ~5,000 calls, $0–$100, budgeted and still unspent. **Before any paid deliverable.** |
| **Redistribution terms void the COGS model.** | Email each P1 vendor for a rider *before* spending. A "no" changes everything. |
| **Live XYZ forecloses the public sector.** | One email: quote request plus partnership question. |
| **NYC TAM caps under $1M.** | Decide explicitly whether this raises or stays consulting-funded. Not a test — a choice. |
| **Single-operator delivery risk.** | Time one site memo end to end before quoting the retainer. |

---

## 10. What the red-team rejected, and why we accept it

- **Chains as ICP #1 — rejected.** They buy models calibrated on their own P&Ls, and our filings hook shows them records their own brokers filed. Accepted: chains become logos and a broker-facing lead list.
- **The $2,500 site report — rejected.** It is neither free (as the broker's client-acquisition study is) nor SBA-accepted (as the $4,900 study is), and it prices at 6–15% of a broker's commission on a deal that may not close. Accepted: $500–900 as marketing, $500–1,500 as a subcontracted input, and the $20k retainer leads.
- **The $-per-avoided-bad-site math — rejected.** It is the rejected causal thesis in percentage clothing: Loci measures supply thinness, not site quality, and cannot separate "underserved" from "unviable". Accepted: argue cost of search, and gate any decision-value claim on the retrodiction.
- **The ledger as moat — rejected.** One month, 47.7% censored, against a purchasable 32-month substitute at €3,300/mo. Accepted: the moat is the BBL reconciliation and the operator, and it is months long.
- **"SaaS" as the narrative — rejected.** Every SKU is founder time and the data licence is blocked. Accepted: consulting-funded data company, priced on earnings, until a self-serve path exists.
