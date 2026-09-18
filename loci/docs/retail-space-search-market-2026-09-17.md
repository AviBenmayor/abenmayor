# Retail space search: is there a market gap, and should Loci build for it?

**2026-09-17 · market-research memo, assembled from five source reports**

The owner's question, verbatim: *"I am noticing there might be a market gap for available retail spaces in new york... If nothing exists, we might need to carve out a large portion of loci capacity to develop this."*

**Date:** 2026-09-17. **Method:** three Opus research threads (tenant-facing search landscape, rent and lease-terms visibility, demand-side evidence and prior attempts — all web research via WebFetch/Tavily, no gate circumvention, no Chrome extension), synthesized through an investor pass and a contrarian pass. This memo assembles those five reports; it adds no new research, no new numbers, and no new URLs. Anything a source report flagged UNVERIFIED, unverified, or NOT FOUND stays flagged that way below.

**Prior state.** D67 (2026-09-10, `docs/CHECKPOINT.md`) ingested the NYC DOF Storefront Registry and concluded, in the same session: *"no rent data exists at address grain anywhere public."* Separately, `docs/PAID-SOURCES.md` already prices three commercial real-estate data vendors as Loci **data-input** candidates — CompStak Enterprise ($10,000/yr, row 4), Crexi Intelligence ($2,988/yr reported, row 17), CoStar Retail ($15,000/yr reported, non-starter on litigation history, row 31) — for feeding rent onto Loci's own cards. This memo is a different question: not "should Loci buy rent data to improve its cards" but **"is there an unmet tenant-side product need — a place a hopeful NYC operator goes to find available space, see asking rent, and see lease terms — and if not, should Loci build one."** That question was not previously asked or answered; it is new as of this research pass.

---

## 1. The two verdicts, side by side

| | Investor | Contrarian |
|---|---|---|
| **Verdict** | **Build-narrow.** Ship the smallest version now: a card line inside the existing screen (option d) plus one FOIL letter (option c); carry the per-address dossier shape (option b) into the AC-2 broker call as the artifact shown, rather than a slide. **Do not build a tenant-facing listings site** (option a). | **Not a gap a product can close.** The three research reports document a *machine's* access problem (HTTP 403s, blank template fields, ToS walls) and present it as a *tenant's* problem. A tenant has a phone. Run the pre-registered 100-storefront, two-persona corridor test (option e) before building anything, alongside the AC-2 broker call the charter already owes. |
| **What kind of gap** | Opaque rent and terms (price shown on 35% of the broker-fed marketplace, 0 of 68 pooled listings show lease type/term/escalation/deposit/guaranty); unlisted inventory (~21–35% of visibly vacant storefronts appear on a marketplace); undecodable cost and acceptance (NNN, tax pass-through, key money, personal guarantee, whether the landlord will take you). | Opacity is the market's equilibrium, not a bug — revealed by the most active retail-leasing team in the city shipping a blank "Asking Rent:" field on every listing. The size gradient shows opacity concentrates where the landlord has leverage and the deal is large; the small owner-listed storefront the hopeful operator actually shops is already the most transparent object in the market. |
| **Binding constraint** | Decodability and acceptance, not discovery — this is what a per-address dossier should sell. | Acceptance (credit and fit), not discovery — but rated H7 in the underlying report is itself weakly evidenced; the contrarian holds that the burden of proof sits with the pivot, not with the status quo. |
| **Willingness to pay** | Zero, evidenced; no tenant pays for anything in today's funnel. The dossier's hypothesized payer (a small-deal tenant rep, or a landlord with a long vacancy) is untested — this *is* AC-2. | Zero, evidenced, on terrain (office, larger deals, repeat tenants) more favorable than NYC small retail. If the model failed there, it fails here *a fortiori*. |
| **Immediate action** | Add a findable-rent-and-contact line to the vacant-storefront table already on the owner's own cards (El Punto second site, Gowanus) this month — the first paying-customer test the charter allows, 2–4 sessions. | Pull 100 addresses from `closure_triangulation`/LL157 flips on one Brooklyn corridor, walk it once, call every contact under two personas, and pre-register the disclosure thresholds — 2 sessions, $0. |

### Where they agree

- **Listings are not the problem.** Thousands of NYC retail-for-lease listings exist (Crexi 4,830; Yardi's feed 2,467–3,458; Craigslist 90+). Neither reviewer treats "no listings exist" as the finding.
- **Rent and lease terms are genuinely opaque on every professional channel.** Both cite the same evidence: Meridian's blank "Asking Rent:" field, the 0-of-68 showing of lease type/term/escalation/deposit/guaranty, Sinvin's "Rent: Please Inquire."
- **The City already holds the missing dataset and does not publish it.** LL157 compels ~70,000 storefront owners to report signed rent/SF, lease dates, an escalation flag, and concessions at address grain; the public file carries none of it. Both reviewers treat the FOIL letter (option c) as cheap and worth filing regardless of outcome.
- **A tenant-facing listings site should not be built.** 42Floors, Truss, TenantBase, SquareFoot and Digsy all tried a version of this on more favorable terrain (larger office deals, repeat tenants) and each either died or bolted on a brokerage and became one.
- **Willingness to pay for information has not been demonstrated by anyone, anywhere, in this market.** Both reviewers treat this as a live, unresolved risk rather than a settled "no" — which is exactly why AC-2's three discovery calls matter to both of them.
- **The FOIL letter and the AC-2 broker call are worth doing regardless of which verdict is right.** Both name them as immediate next steps.

### Where they split

- **Whether opacity is "a gap a product can close" at all.** The investor reads the same opacity evidence as an addressable wedge for a narrow dossier product (sells decodability, not discovery). The contrarian reads it as the market's stable equilibrium — a phone call defeats every gate the landscape report logged, so the "gap" is a research artifact of automated fetchers being blocked, not a tenant's lived experience.
- **Whether the unlisted-inventory and staleness statistics are real.** The investor treats "~25–35% of visibly vacant storefronts appear on a marketplace" and "259-day median days-on-market" as load-bearing evidence of a coverage gap. The contrarian grades the coverage estimate a **D** (mismatched numerator/denominator — marketed *spaces* vs visibly vacant *ground floor*, unverified borough totals) and grades the Crexi DOM figure a **C** as "what Crexi says," an **F** as a market fact.
- **What H7 (the binding constraint is acceptance/creditworthiness, not discovery) licenses.** The demand report rates H7 "Strong." The contrarian calls the evidence for H7 itself weak — but argues that doesn't matter, because the *pivot's* thesis ("discovery is the bottleneck") has zero discriminating evidence either, and the burden sits with whoever wants to build something.
- **What to do next.** The investor's plan is to ship the narrow product now (card line + FOIL) and let AC-2 discover the payer along the way. The contrarian's plan is to run the corridor test *first*, before committing any capacity beyond the FOIL letter and the already-chartered AC-2 calls, because the test's pre-registered thresholds can kill the pivot outright at near-zero cost.

**This split is not resolved here.** It is the owner's decision, not a research finding — see §9 and §10 for what each option costs and what single number would move each reviewer.

---

## 2. What exists today for a tenant — the channel map

Every channel identified in the tenant-facing landscape report, condensed. "Gate" is what stands between a tenant and the information; "what it hides" is what the channel structurally withholds even after the gate is passed.

### Marketplaces

| Channel | Who pays | NYC retail coverage | Asking rent visible? | Lease terms visible? | Gate | What it hides |
|---|---|---|---|---|---|---|
| LoopNet | CoStar; landlord/broker advertising | "750+" NY/Manhattan (display cap; true count higher); Queens 442; zip 10012 37 | Sometimes — $/SF/yr; many "Rate Upon Request" | No (lease type only, sometimes) | HTTP 403 to two fetchers; page text admits a "blue" CoStar-only tier "NOT shown to the millions of regular LoopNet users" | The CoStar-only tier; rent on the "upon request" share; every term beyond headline rent |
| Crexi | Crexi; brokers pay Pro/Intelligence, free basic listing | 4,830 active NYC retail lease spaces (Feb-2026 blog), median ask $60/SF/yr, median 2,000 SF, days-on-market 259 | Sometimes | No | HTTP 403 to two fetchers; sign-in for exports/comps | Terms; the no-price fraction; comps behind a paywall |
| CommercialCafe (Yardi) | Yardi; landlords/brokers pay Yardi | 3,458 retail listings, "as of Sept 10, 2026" | Sometimes — e.g. $97.00/SF/YR, others "Contact for pricing" | No | None observed | Terms; price on the "contact" share |
| CommercialSearch (Yardi) | Yardi | 4,723 NYC listings; Manhattan 2,071; Brooklyn 1,365 | Sometimes (same feed) | No | None observed | as above |
| PropertyShark listings (Yardi) | Yardi | 2,365–2,467 listings; Manhattan 1,099, Brooklyn 741 | Sometimes — mixes $/SF/YR and $/MO, with "Price on request" on numerous listings incl. SoHo/Flatiron | No — "Reach out to the broker" | None for listings | Terms; rent on the "on request" share |
| CityFeet (CoStar/LoopNet sibling) | CoStar | "500 available listings" (LoopNet subset) | Sometimes — "Rate Upon Request" common | No | None (mirrors LoopNet gating) | as LoopNet |
| Craigslist (office/commercial) | Craigslist; poster fee | 342 posts NYC-wide (all commercial types); 91+ when filtered to "storefront" | **Always** — $/month, the only channel defaulting to a monthly number | No; occasionally free text | None | Landlord identity; SF often; terms; office/sublet noise |
| Brevitas | Brevitas; freemium | Investment-sales oriented; NYC retail-lease depth UNVERIFIED | Unknown | No | Account for saved searches | Thin for a storefront tenant |
| SquareFoot | SquareFoot; landlord-paid commission | Historically office-only; UNVERIFIED whether any retail today | n/a | n/a | JS-only page (empty to fetcher) | Not a retail channel |
| Realtor.com Commercial | News Corp | Fetch refused; UNVERIFIED whether the vertical still exists | Unknown | Unknown | Fetch-blocked | Unknown |
| Zillow / StreetEasy | Zillow | **No commercial vertical.** StreetEasy's own forum: "there aren't any current websites… dedicated for commercial spaces" | n/a | n/a | n/a | Does not carry commercial listings at all |
| Localize.city | Localize | Residential only | n/a | n/a | n/a | Not a channel |
| Spacelist | Spacelist (Canada) | Redirects to .ca; no NYC | n/a | n/a | n/a | Not a NYC channel |
| Digsy | Digsy; free + broker-referral | "31,000 properties" claimed nationally; NYC retail depth UNVERIFIED | Unknown | No | None claimed | Thin/indirect — routes to a broker |
| Storefront (thestorefront.com) | Storefront; booking fee/commission | ~14 pages of NYC spaces; e.g. 400 SF from $960/day (Bowery); Brooklyn inventory dense and cheap ($260–300/day) | **Always, but per day** — short-term only | n/a (licence, not lease) | None to browse | Not a path to a 5–10-yr lease; no long-term asking rent |
| Peerspace | Peerspace; hourly/daily fee | HTTP 500 at fetch — UNVERIFIED count | Hourly | n/a | Fetch failed | Pop-up only |
| Splacer | Splacer | TLS error at fetch — UNVERIFIED | Hourly/daily | n/a | Fetch failed | Pop-up only |
| Listings Project | Listings Project; free to read, paid to post | NYC-centric but apartments/rooms/artist-space; rarely storefronts | $/month when posted | No | Paid to post | Rarely storefronts |
| AI-native entrants (2024–26) | — | **No tenant-facing AI storefront-search product for NYC surfaced** under obvious queries; only broker content marketing and Crexi's internal "Research AI BETA" | — | — | — | Nothing findable by a tenant's obvious query |

### Broker sites

| Channel | Who pays | NYC retail coverage | Asking rent visible? | Lease terms visible? | Gate | What it hides |
|---|---|---|---|---|---|---|
| RIPCO | Landlord-rep; landlord commission | Manhattan listings page, count not displayed | **Never on page** — a lead-capture form promises "lease rates" by email | No | Email-blast signup form | Rent itself is the lead magnet |
| Meridian Retail Leasing (nycretailleasing.com) | Meridian Capital's retail arm | Featured exclusives (55 Water St, 1191 First Ave, etc.) | **Template field "Asking Rent:" is empty on every card** | No | WebFetch 403; Tavily succeeded | Rent (a blank field, not a missing one) |
| Sinvin (SoHo/Tribeca/Nolita) | Landlord-rep | ~50+ exclusive listings | **Never** — "Rent: Please Inquire" | Partial — "Term: 5 or 10 Years," possession date | Weekly-email signup; "please be discreet, do not view without speaking to us" | Rent, escalations, free rent, security, GGG |
| Kassin Sabbagh Realty (KSR) | Landlord-rep | Many Manhattan/Bronx cards, 250–8,500 SF | Never on cards | No | Listings page 403; "off-market deals" reserved for broker-blast subscribers | Rent; the off-market pool |
| Tri State Commercial (Brooklyn/Bronx) | Landlord-rep | Handful of "For Lease" cards | Not on cards | No | None | Rent |
| Traded (traded.co) — closed-deal feed | Ad-supported deal-announcement platform | Post-hoc only: e.g. "1175 Fulton St… $156/ft… LEASE TERM: 7 years… Modified Gross" | Disclosed **after signing** (comps), never for availabilities | Term + lease type on closed deals | None | Availability — but the most transparent public $/SF+term source found, for deals already done |
| Winick Realty | Landlord-rep | Legacy 2017 PDF format: sizes, frontage, "New Direct, Long Term Lease" | Never | "Long term lease" phrasing only | Certificate error at fetch | Rent |
| RTL (ex-Winick team) | Landlord-rep | Featured listings, no counts | Not on cards | No | Mailing-list modal | Rent |
| Katz & Associates | Landlord-rep | Filter form, no rendered data | Unknown | No | JS search | — |
| Lee & Associates NYC | Full-service | Marketing copy, no counts | Unknown | No | — | — |
| Cushman & Wakefield | Full-service | Landing page link, no rents shown | Unknown | No | — | — |
| CBRE | Full-service | Search UI only, no data rendered | Unknown | No | JS app | — |
| JLL | Full-service | property.jll.com returned a 500 error | Unknown | No | 500 error | — |
| Newmark | Full-service | Navigation only; listings load client-side | Unknown | No | Lead form for brochures | — |
| Eastern Consolidated | — | **Defunct — shut down July 2018** | — | — | — | — |
| Ariel Property Advisors | Investment sales, not leasing | Not fetched — UNVERIFIED | — | — | — | Not a tenant channel |
| Compass / Corcoran Commercial | Residential-first, commercial arm | Not fetched (cap) — UNVERIFIED | — | — | — | — |
| Rosenberg & Estis | Law firm, not a brokerage | n/a | n/a | n/a | n/a | Not a listing channel |

### Government / civic

| Channel | Who pays | NYC retail coverage | Asking rent visible? | Lease terms visible? | Gate | What it hides |
|---|---|---|---|---|---|---|
| NYC SBS — Commercial Lease Assistance Program | City-funded free legal help | Reviews a lease **after** one is found; no space-finding function; 812 businesses served FY25 | n/a | Reviews terms brought to it | SBS Connect account; income eligibility; no franchises | Does not find space |
| NYC SBS — "Shop Your City" | SBS | Map of open businesses, not availability | n/a | n/a | — | Not a channel |
| NYC Small Business Resource Network | Chambers + Partnership Fund | Advisory helpdesks, no listings | n/a | n/a | — | — |
| NYCEDC | City EDC | RFPs for city-owned sites (institutional scale) | n/a | RFP terms | Proposal process | Not a storefront search |
| DOF Storefront Registry — NYC Open Data "Storefronts Reported Vacant or Not" (92iy-9c3n) | City; owner-filed under LL157/LL95 | Citywide, address-level; ~70,202 storefronts (2019 filing) | **No rent field published**; no tenant-facing map | No | Open Data portal, but zero UX for a tenant | Whether it's actually on the market, who to call, price |
| NYC Comptroller "Who's Minding the Storefronts?" (June 2026) | Comptroller, Live XYZ ground survey | Citywide vacancy **11.0% ≈ 15,700 vacant**, implying **~142,000–143,000 visible storefronts**; some neighborhoods ~20% | n/a (statistical) | n/a | None | Not a search tool — gives the denominator |
| NYC Council Data Team — "Vacant Storefronts" | Council, LL157 registry-based | **6,631 vacant / ≈63,800 registered storefronts (Dec 2021)** — well under half the Live XYZ universe | n/a | n/a | None | Aggregate maps only |
| Manhattan Chamber — Storefront Tracker | Chamber (Wells Fargo-funded), Live XYZ | Manhattan **13.74% vacancy Q4-2025; 5,134 vacant of ~37,000**; citywide 11.04% | n/a | n/a | None | No addresses, no rents |
| Downtown Alliance (Lower Manhattan BID) | BID | Concierge "preliminary search" service; RE:Store gives free pop-up ≤3 months + up to $15k grant | Not published; on request | n/a | Contact-us | Rent; list not public |
| Union Square Partnership (BID) | BID | Q3-2025 PDF: 19 ground-floor spaces, 700–9,932 SF, address + broker + phone | **No asking rents in the PDF** | UNVERIFIED (not fetched) | None | — |
| Myrtle Avenue Brooklyn Partnership (BID) | BID | "Available Storefronts to Lease" page, ~5 entries with address, block, size | **Often, $/month** — the only BID page found that publishes rents ("541 Myrtle Ave… $11,000/month") | No | None | Terms; whether entries are current |
| Flatbush Ave / Church Ave BID | BID | No availability page surfaced | — | — | — | — |
| North Flatbush, Fulton St, Grand St, Bronx Little Italy, Woodhaven, SoHo Broadway BIDs | BIDs | Link to SBS clinics and storefront-activation art programs, not availability lists | — | — | — | — |
| Pace University SBDC — "Finding Commercial Space" | SBA/SUNY SBDC | Resource page pointing elsewhere | n/a | n/a | — | — |

### Informal

| Channel | Notes |
|---|---|
| Reddit (r/AskNYC, r/smallbusiness, r/CommercialRealEstate, r/RealEstate) | Recurring "how do I find a storefront" threads; canonical answer: LoopNet/Crexi → walk and call signs → get a broker (landlord pays). |
| "For Rent" signs / walking | The Comptroller and Manhattan Chamber both count vacancy by *visible* survey — exactly the tenant's own method. No published survey of what share of leases originate from a sign — UNVERIFIED gap in the literature. |
| Instagram broker accounts / Traded | Brokers and Traded post closed deals with $/SF and term post-hoc. |
| Broker "blast" lists / WhatsApp | KSR's Broker Blast, RIPCO's "free list," Sinvin's weekly email — the rent lives in the email, not on the web. |
| Facebook groups | "NY Commercial Real Estate for Lease and Sale" — private, 15.1K members, 359 posts/month; "Commercial Spaces for Lease and Sale in NY" — public, landlord-direct posts, monthly rent typically in the post, membership gate. |
| Broker content / corridor-average rent guides (cdrenyc.com, metro-manhattan.com) | Republish REBNY/C&W/JLL corridor averages ("~$710/SF" Q2-2026 prime corridors); explicitly route the reader to a broker; useless for a side-street storefront. |

### The coverage estimate, with the contrarian's grade attached

The landscape report's own triangulation: the largest single marketplace count is Crexi's 4,830 active NYC retail lease "spaces" (Feb 2026); Yardi's feed shows 2,467 NYC listings (1,099 Manhattan, 741 Brooklyn). Against a Live XYZ-derived denominator of ~15,700 visibly vacant storefronts citywide (~5,134 vacant of ~37,000 in Manhattan alone), the report estimates **roughly one in four to one in three visibly vacant NYC storefronts is findable on a marketplace** — Manhattan ≈ 1,099/5,134 ≈ 21% on the Yardi feed alone, higher once LoopNet/Crexi are added — with the rest sign-only, broker-blast-only, landlord-direct, or pop-up-monetized. The report itself flags this as an order-of-magnitude estimate, UNVERIFIED.

**Contrarian grade: D.** The numerator (marketed *spaces* — including upper floors, mall bays, new-build shells with multiple units, five-borough inventory, and spaces occupied with future possession) is not a subset of the denominator (visibly vacant *ground-floor* storefronts). Cross-platform overlap between Yardi's three sibling sites is assumed rather than measured, the "4,000–6,000 unique marketed spaces" figure is a guess, and the ~40,000-Brooklyn-storefronts denominator used for the Brooklyn ratio is UNVERIFIED by the source report's own note. The landscape report itself concedes that a tenant who uses LoopNet + Craigslist + walks the block "has probably covered most of what is genuinely marketed" — the number that actually matters, and it was not measured. Fix proposed by the contrarian: draw 200 addresses at random from `closure_triangulation`/LL157 flips, check presence across the four largest marketplaces, and walk for a sign — a like-for-like ratio at n≥200 rather than a cross-source guess.

---

## 3. Rent and lease-terms visibility

### 3.1 Source × grain × visibility matrix

Legend: A = asking rent, S = signed/in-place rent, T = term, E = escalations, F = free rent/TI, D = security deposit, G = good-guy guaranty, K = key money. ● visible · ◐ aggregate/sometimes · ○ not visible.

| Source | Grain | A | S | T | E | F/TI | D | G | K | Audience |
|---|---|---|---|---|---|---|---|---|---|---|
| REBNY Manhattan Retail Report (biannual) | corridor (16) | ● avg+median | ○ | ○ | ○ | ◐ narrative | ○ | ○ | ○ | public |
| REBNY Brooklyn Retail Report | corridor (16–17) | ● avg | ○ | ○ | ○ | ◐ narrative | ○ | ○ | ○ | public |
| C&W Manhattan Retail MarketBeat (quarterly) | corridor (12) | ● avg | ○ | ○ | ○ | ○ | ○ | ○ | ○ | public |
| CBRE Manhattan Retail Figures / JLL | corridor (16 / prime) | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ | PDF form-gated |
| Matthews / M&M / Lee (CoStar-fed) | borough | ● avg | ○ | ○ | ○ | ○ | ○ | ○ | ○ | public |
| CommercialCafe / PropertyShark / Realmo listings | address | ◐ ~35% of cards | ○ | ○ | ○ | ○ | ○ | ○ | ○ | public |
| LoopNet / Crexi listings | address | ◐ UNVERIFIED share, fetch blocked | ○ | ○ | ○ | ○ | ○ | ○ | ○ | public view, ToS bars automation |
| Craigslist | neighborhood/cross-street | ● 77% Bk, 40% Mn ($/mo) | ○ | ○ | ○ | ○ | ○ | ○ | ○ | public |
| Commercial Observer deal stories | address | ● "asking was $X" on publicized deals | ○ | ◐ | ○ | ○ | ○ | ○ | ○ | public/metered |
| Realgraph (Commercial Observer) | address | UNVERIFIED | UNVERIFIED | UNVERIFIED | ○ | ○ | ○ | ○ | ○ | account gate |
| CompStak blog (Deals of Distinction, concession trends) | address for ~10 deals/qtr; market for aggregates | ○ | ● top deals | ● top deals | ○ | ◐ aggregate | ◐ aggregate | ○ | ○ | public blog; database paywalled |
| Columbia–CompStak Quality-Adjusted Rent Index | submarket index | ○ | ◐ index | ◐ | ○ | ◐ index | ◐ index | ○ | ○ | public paper |
| BizBuySell / BizQuest / FB groups / Instagram | neighborhood, no address | ○ | ● often ($/mo) | ● years remaining | ○ | ○ | ○ | ○ | ◐ "key money opportunity" | public; BizBuySell blocks bots |
| DOF LL157 registry — **collected** | address | ○ | ● $/SF/mo | ● start/expiry | ● yes/no flag | ● concessions | ○ | ○ | ○ | confidential (RPIE regime) |
| DOF LL157 — Open Data 92iy-9c3n **published** | address | ○ | ○ | ◐ expiry date, vacant premises only, sparsely populated | ○ | ○ | ○ | ○ | ○ | public |
| DOF LL157 — summary PDF | council district/borough | ○ | ● avg & median $/SF/mo (2019 vintage) | ○ | ○ | ○ | ○ | ○ | ○ | public |
| DOF RPIE + rent-roll addendum | address/tenant | ○ | ● | ● | ○ | ○ | ○ | ○ | ○ | confidential; City-internal |
| ACRIS memorandum of lease (RPL §291-c) | address | ○ | ○ | ● when recorded (rare for small retail) | ○ | ○ | ○ | ○ | ○ | public, free |
| Commercial Rent Tax | n/a (≥$250k, Manhattan south of 96th) | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | confidential |
| NYS SLA licence application | address | ○ | UNVERIFIED (lease attached; FOIL redaction unknown) | ◐ via licence intervals | ○ | ○ | ○ | ○ | ○ | FOIL |
| DOB permits | address | ○ | ○ | ◐ timing proxy | ○ | ○ | ○ | ○ | ○ | public |
| REBNY store-lease form / NYC Bar Model Retail Lease | form | ○ | ○ | blank template | blank | blank | blank | blank | ○ | public ($7–9 official; free copies) |
| Broker/law-firm explainers | structural defaults | ○ | ○ | ◐ | ◐ "~3%" | ◐ | ◐ "2–12 mo" | ● | ◐ | public |
| SBS Commercial Lease Assistance | per-tenant counsel | ○ | ○ | ● for your lease | ● | ● | ● | ● | ● | eligibility-gated, free |

### 3.2 The 68-listing sample

**Method:** first results page of each public search (no login, no scraping beyond one page); sites that refused automated fetch were logged as gates. CommercialCafe Brooklyn (23 retail-for-lease cards, page 1 of 5), Craigslist Brooklyn "office & commercial" (30 retail/storefront/restaurant posts identified by title, of 261 total posts), Craigslist Manhattan query "retail store" (15 posts). Pooled across the three: **68 cards, price shown on 37 (54%)**. By source: 35% on the broker-fed marketplace (8/23), 77% on Brooklyn Craigslist (23/30), 40% on Manhattan Craigslist (6/15). Every priced CommercialCafe listing was ≤3,600 SF; every listing ≥6,000 SF was "Contact." Units are incompatible across channels ($/SF/yr on marketplaces, $/month on classifieds), and the SF needed to reconcile them is missing from most classifieds. No source in the sample showed lease type, term, escalation, free rent, deposit, or guaranty on the card.

**Contrarian grade: D as a tenant claim, C as arithmetic.** The frame is chosen by fetchability — LoopNet and Crexi are absent entirely (403), and CommercialCafe's default sort favors larger landlords. n=68 gives roughly ±12 percentage points. Re-cut by size, the picture reverses: of the 13 CommercialCafe cards ≤3,600 SF, 8 were priced (62%); Craigslist ran 77%. For the segment that actually matters to a hopeful first-time operator, price is shown roughly 60–75% of the time — the pooled 54% headline understates transparency exactly where the customer shops. Fix proposed: stratify by size band and channel, n≥100 per stratum, and get LoopNet into the sample via a browser rather than a blocked fetcher.

### 3.3 Public records

**What the City collects (LL157/2019, amended LL95/2022).** Every class-2/4 storefront owner files, with the RPIE by June 1, for each lease in the prior 12 months: the start date and expiration/renewal date of the lease; whether scheduled rent increases are contained in it; information on lease concessions granted to the lessee; the average monthly rent per square foot charged for the premises (excluding any period it sat unleased); and the type of economic activity conducted there. For a premises not leased the full year: the monthly rent/SF paid by the most recent tenant. For vacancies: start and end date of each vacancy period and whether it was under construction/alteration. Semi-annual vacancy supplements report status as of June 30 (due Aug 15) and Dec 31 (due Feb 15). This covers roughly 70,000 storefronts.

**What the City publishes.** Two channels only:

1. **NYC Open Data 92iy-9c3n, "Storefronts Reported Vacant or Not."** 31 published columns: Filing Due Date; Reporting Year; BBL; Property Street Address/Storefront Address; Borough; Zip Code; Sold Date; Vacant on 12/31; Construction Reported; Vacant 6/30 or Date Sold; Primary Business Activity; **Expiration date of the most recent lease** (for vacant premises, as reported by owner); Property Number; Property Street; Unit; Borough1; Postcode; Latitude; Longitude; Lat/Long; Community Board; Council District; Census Tract; BIN; BBL; NTA; NTA Neighborhood; Community Districts; Borough Boundaries; Police Precincts; City Council Districts. **No rent column, no lease-start column, no scheduled-increase or concession column.** The lease-expiration column exists in the schema but is populated only in one release and is otherwise sparsely populated — why is not documented in any DOF changelog found (UNVERIFIED).
2. **DOF summary PDFs at borough/council-district grain.** The 2019-vintage release gives average monthly rent per SF by council district — citywide $10.74/SF/month; Manhattan CD4 $37.01, CD3 $28.65, CD1 $15.83, CD6 $13.11; lowest CD31 Queens $2.59, CD12 Bronx $2.83, CD46/CD45 Brooklyn $2.88/$3.13. ANHD reports medians from the same release: Manhattan median $9.00/SF/month, every other borough under $4.00. A separate May-2021 census-tract-grain aggregate is described in secondary sources; whether it is still downloadable is UNVERIFIED.

**Why rent is withheld at address grain (INFERRED, not verified).** Registry statements are filed as part of the RPIE, which DOF treats under the RPIE confidentiality regime — Admin Code §11-208.1 bars per-property disclosure of income-and-expense statements used for assessment. The statute's own publication clause was not fetched in this research; the mechanism is inferred from DOF's filing architecture and the observed publication pattern, and is flagged as **INFERRED**.

**ACRIS — memoranda of lease (RPL §291-c).** A lease with a term over 3 years may be recorded, or a memorandum with like effect. Statutory minimum content: lessor/lessee names and addresses; a reference to the lease and its execution date; description of the premises; term with commencement/termination dates; any renewal/extension right with maximum period and exercise dates. **Rent is not a required element and is customarily omitted** — the memorandum exists to give notice, not economics. Recording is optional and, for small NYC retail leases, believed rare (asserted from practice, UNVERIFIED by count); chain and anchor tenants record more often. Searchable free by BBL.

**RPIE and rent-roll addendum.** Owners with actual assessed value over $40,000 file RPIE annually; those with AV ≥ $750,000 file a rent-roll addendum with tenant-level rents. Used for assessment only; nothing published at property grain. The only public RPIE artifact is the non-compliance list.

**Corridor reports, incl. REBNY Brooklyn.** REBNY's Manhattan Retail Report (biannual; H1 2026 released 2026-06-24) covers 16 corridors with average and median asking rent per SF and a per-corridor availability count. REBNY's Brooklyn Retail Report — the only corridor-grain Brooklyn series, running since 3Q2015 — covers 16–17 corridors: e.g. Court St (Montague–Atlantic) $125→$115/SF, Smith St $90/SF, North 6th St Williamsburg peak $275/SF; "nearly 80% of available spaces ≤2,500 SF"; "ample supply renting <$100/SF in Bay Ridge, Brooklyn Heights, Greenpoint… negligible buildout allowances." REBNY's own 3Q2015 methodology note warns why finer grain isn't published: rents vary greatly "between properties that are only a few doors down from each other," driven by frontage, ceiling height, basement, and landlord type. Cushman & Wakefield's Manhattan Retail MarketBeat (quarterly, 12 corridors, overall average $710/SF Q2-2026) and CBRE's Manhattan Retail Figures (16 "premier corridors," ~$682/SF, PDF form-gated) round out the corridor tier. No corridor report publishes block or address grain.

### 3.4 Regulation and opacity — jurisdiction table

| Jurisdiction | Measure | Forces asking-rent disclosure on vacant retail? | Forces pre-signing lease-term disclosure to the tenant? | Publishes signed rent? |
|---|---|---|---|---|
| NYC | LL157/2019 + LL95/2022 storefront registry | No | No | Collects signed rent/SF, lease dates, escalation flag, concessions at address grain; publishes only vacancy + business type per address, rent as 2019-vintage council-district averages |
| NYC | Int 1473-2019 (vacant-storefront registration w/ SBS) | No (contact info + reasons, not rent) | No | — (never passed) |
| NYC | Int 0352-2022 (registry for all commercial premises) | No | No | — (filed, died) |
| NYC | Commercial rent stabilization lineage / Small Business Jobs Survival Act | No | No (renewal rights/arbitration) | — |
| NYS | S8319/A5568A "Small Business Rent Stabilization Act" (2026) | No | No | — |
| San Francisco | Prop D Commercial Vacancy Tax + DBI vacant-storefront registration | No | No | No |
| Australia (NSW/Vic/Qld/SA Retail Leases Acts) | Mandatory lessor disclosure statement + draft lease + info brochure before signing (NSW ≥7 days, Vic ≥14 days) | No (market asking rent not posted) | **Yes — the only precedent found of mandated pre-signing lease-term disclosure to a specific prospective tenant** | No |
| UK | Land Registry registration of leases > 7 years | No | No | Partially, per recorded lease, for a fee — UNVERIFIED today, not fetched |
| Washington DC / Chicago / LA | Vacant-property registries | No (UNVERIFIED) | No | No |

**Answer to the question posed:** no jurisdiction found forces asking-rent disclosure on vacant retail. Australia's Retail Leases Acts force pre-signing disclosure of a proposed lease's economics to the specific prospective tenant — not to the public — and are the only mandated lease-term disclosure precedent located. NYC is unusual in that it already compels landlords to report signed rent per SF and lease dates at address grain, and then withholds those fields from the public dataset.

---

## 4. Demand side

### 4.1 The funnel operators actually use

Across every first-hand account gathered, the same three-step funnel recurs: **(1)** LoopNet/Crexi for a rough $/SF; **(2)** walking the target blocks and calling the phone number on the sign; **(3)** a tenant-rep broker (paid by the landlord) for off-market inventory and negotiation. The complaints in these accounts are not "I can't find listings." They are "I can't tell what a space really costs (NNN, tax, key money, fit-out, electrical), whether I'll be accepted (financials, personal guarantee), or what terms are normal" — and the operators themselves treat this information as socially guarded.

### 4.2 First-hand account quotes

| # | Source | Who | What they said / did | Signal |
|---|---|---|---|---|
| 1 | r/CommercialRealEstate, "Beginning my search…" (~Oct 2025) | First-time Manhattan retail tenant | "I'm a complete newbie!… Looking at a listing on loopnet that is $100/sq foot… what could/should I pad the numbers with?" → "I'll get a broker and go from there." Two brokers solicited in-thread within hours. | Starts on LoopNet; cannot decode all-in cost; funneled to a broker immediately. |
| 2 | r/parkslope, "Leasing a commercial space in Park Slope" (Jun 2024) | Online seller taking a first storefront | "Do most landlords give a couple months free for renovations?" Reply: "a lot of this stuff is pretty secretive… businesses don't even like revealing who their landlord *is*." Another: "Every one of our favorite restaurants that has closed did so because of their leases." | Term information is socially guarded; the pain is lease terms and build-out surprises, not discovery. |
| 3 | r/Brooklyn, "Any retail/cafe Spaces for rent…" (Aug 2025) | Barista trainer opening a first café | Crowdsources availability on Reddit; reply: "This former cafe has been empty with a for rent sign in the window for just about a year… if you walk by it you'll see the phone number." OP: "Who can I contact?" Reply: "I have no idea. I just live in the neighborhood." | Discovery is window signs and neighbours; no tool in the loop. A year-vacant café with a sign is exactly what a registry should surface — and does not. |
| 4 | r/RealEstate, "What's the best way to find commercial real estate…" (2018–2024) | Prospective NYC retail tenant | "Crexi and Loopnet are good. Off market deals are best found through brokers. Landlords pay broker fees 99% of the time… but the rents are undoubtedly pricing in those fees right back to you." | The consistent triad: LoopNet/Crexi → walk and call signs → broker for off-market and negotiation. |
| 5 | r/AskNYC, "Why do some storefronts in NYC stay vacant for years?" (Dec 2024) | Residents + a CRE insider | "Commercial real estate is still very much a 'handshake' type of business." Brooklyn Heights ex-Starbucks "empty 10+ years… he's very rich, value keeps going up, what does he care." "Why hustle to piece together a bunch of short-term popups… when they could just wait it out for a Warby Parker?" | Landlord-side reason vacant ≠ available-to-you: owners wait for credit tenants. |
| 6 | r/CommercialRealEstate, "Looking for retail space…" (2023) | Small tenant (not NYC-specific) | "Your best bet is reaching out to a local commercial broker… Loopnet and Crexi are the best platforms." | Same triad outside NYC. |
| 7 | r/CommercialRealEstate, "How to find a good commercial RE Agent for NYC…" (Nov 2024) | NYC tenant | "Loopnet, Crexi, and MLS will have the ability to find commercial listings. Start looking at listings and the brokers at these firms." | Listings used to find brokers, not spaces. |
| 8 | r/AskNYC, "Commercial rents and gross revenue" (Feb 2025) | Resident doing the arithmetic | "At 80/sqft with typical 2500 sqft restaurant space, rent alone is 16.7k. Add real estate tax… BID tax, NNN, etc." | All-in occupancy cost is folk knowledge, backed into from $/SF. |
| 9 | NYT, "How to Open a Restaurant in NYC" (Oct 2025), Cheeni, Bed-Stuy | Two first-time owners, $176k budget | Search began Feb 2025, $4,000–6,000/mo budget for ~30 seats. Sample space at $6,042/mo; a former restaurant's current renter wanted **$250,000** on top of rent for the fit-out he'd already paid for. | Key money and inherited fit-out are the real price; asking rent is a fraction of it. |
| 10 | The City (June 2026), on the Comptroller report | Demetri Ganiaris, Tribeca Alliance chair, small CRE broker | Downtown asking rents down "20–25% from 2019 levels… the tenants who do come looking often do not have enough funds — offering, for example, $12,000 a month for a 2,000-square-foot space that typically rented for at least $20,000." | Broker/landlord view of the hopeful operator: under-capitalized and mis-priced. The mismatch is expectations, not information. |
| 11 | Verada Retail (Brooklyn tenant-rep brokerage), broker marketing | Broker | "The site search can take weeks (or months)… many business owners quickly realize that trying to scour listings, conduct market research, set up showings, and negotiate the lease is too overwhelming." | The broker's own framing of DIY search as the failure they monetize. |
| 12 | Skyline Properties, broker guide | Broker | "Skipping the broker" listed as a top small-business mistake; "most small businesses run 3–6 months of rent before opening." | Post-signing burn is 3–9 months of rent. |
| 13 | The Counter (2020) | Jasmine Moy (hospitality attorney); Birch Coffee co-owner | "Most independent restaurant owners personally guarantee their leases… The only exception is New York City, where leases contain a 'good guy' clause." | The personal guarantee is the term operators fear most. |

### 4.3 Quantified demand

**The universe.** 142,000–143,000 storefronts citywide, 15,700 vacant (11.0%, April 2026, Comptroller/Live XYZ). Turnover proxy: 16% of ~96,500 small-business storefronts changed or vacated 2020–2026 (~2,600/yr net replacement; gross openings higher). Storefront Startup's applicant list — a pre-assembled sample of exactly this customer — had 200 applicants for ~50 free pop-up slots in one program in one year.

**Opening rates.** Loci's own warehouse (not new research for this memo, cited as internal context) holds NYS SLA licence intervals (`analysis.licence_event`, 43,863 SLA licences) and DOHMH permits that could compute first-issue on-premises licences per year in Manhattan+Brooklyn; that count was not pulled within the research cap. External web figures for a precise annual opening rate were not found.

**The tenant-rep commission floor.** NYC broker commission schedule (REBNY-style): ~5% year 1, 4% years 2–3, 3% years 4–5, 2.5% years 6–10 of base rent, landlord-paid; a tenant's broker takes a full commission, the listing broker half — ≈19% of one year's rent to the tenant rep on a 5-year lease. Worked example: a $5,000/mo Brooklyn café on a 5-year lease yields a tenant-rep commission of ≈0.19 × $60,000 ≈ **$11,400 gross**, split with the house to ~$5–6k for 2–4 months of touring, LOI, and lease — for one individual broker. Below roughly $3–4k/mo, the economics are asserted to stop working.

**Contrarian grade on the floor: C for the arithmetic, D for the floor claim itself.** The 19% schedule checks out as arithmetic (5+4+4+3+3), but it is broker-blog sourced and depends on whether the deal is co-broked in full or split. "Below $3–4k/mo the economics stop working" is asserted with no broker actually asked — and the same report notes small deals *do* get brokered (two brokers solicited a Reddit newbie in-thread within hours). Fix proposed: ask three brokers directly (Verada, Zelnik, a KSR junior) — which is functionally the same call as AC-2.

### 4.4 Willingness-to-pay evidence: none found

No tenant pays for anything in today's funnel. Brokerage is landlord-paid; SBS Commercial Lease Assistance (812 businesses served, FY25) is city-paid; LoopNet's basic tier is free. The only tenant-side spend identified in any account is a lawyer and an architect/contractor walk-through. Operators demonstrably *will* pay for flexible-term access (Storefront.com, by the day, no personal guarantee) and for the space itself (key money — $250,000 on one Bed-Stuy restaurant example). Nobody in any account, thread, report, or program was found paying for *information*. This is treated by both the investor and contrarian syntheses as the single strongest piece of evidence against building a paid product, and as the reason AC-2 (three discovery calls with a payer, due 2026-12-31) is load-bearing for any of the options in §9.

---

## 5. Prior attempts

### 5.1 Startups

| Name | Years | What it built | Model | Outcome | Why | NYC small retail in scope? |
|---|---|---|---|---|---|---|
| 42Floors | 2011/12 (YC) → brokerage shut Mar 2015 → acq. Knotel Jul 2018 → acq. Yardi Dec 2021 → folded into CommercialCafe May 2024 | Office search engine for sub-5,000 SF deals brokers ignore; added an in-house brokerage late 2014 | Free search/lead-gen, then commissions | Dead as a brand | "A startup can only be great at one thing" — could not run national search and a local hands-on brokerage at once; Yardi bought it as SEO inventory (320k listings) and folded it. | Office, SF-first. **No.** |
| Knotel | 2016 → Ch. 11 Jan 2021 [unverified, from memory] | Flex office operator; bought 42Floors | Master leases | Bankrupt | Flex-office overexpansion | No. |
| SquareFoot | 2011 Houston → NYC; acq. PivotDesk Feb 2019; launched FLEX Jun 2019; $16M Series B | Office listings + in-house tenant-rep brokerage, then flex/sublet | Landlord-paid commissions | Alive as an office tenant-rep brokerage; current scale UNVERIFIED | Listings alone did not monetize; revenue came from being a broker. | Office only. **No.** |
| Truss | 2016 Chicago/Dallas; $7.7M A, $15M A-2; expanded to 10 metros | Chatbot + Matterport tours for <10,000 SF tenants; "price transparency for small business owners"; own brokers | Landlord-paid commissions | [Unverified] believed wound down ~2020 | Same hybrid: search front-end, brokerage back-end. | Retail nominally; never NYC. **No.** |
| TenantBase | ~2014 Orange County → LA, Dallas | Tenant-facing search + in-house advisors, <5,000 SF | Commissions | [Unverified] | | Office. No. |
| Digsy / Digsy AI | ~2014 → pivot to broker CRM [unverified] | Small-tenant office search → broker prospecting software | SaaS to brokers | Pivoted away from tenants | Sold to the side with money | No. |
| Spacious | 2016 NYC → acq. WeWork Aug 2019 (~$42M reported) → shut Dec 2019, 50 laid off | Daytime coworking inside restaurants | Membership | Dead | WeWork "renewed focus on its core workspace business" post-IPO collapse. | Used NYC restaurant space as *supply*, not for tenants. **No.** |
| Storefront (thestorefront.com) | 2012– | Short-term/pop-up retail marketplace | Take-rate on bookings | Alive, niche | Changed the product (days–3 months, no personal guarantee) rather than fixing search. | **Yes — pop-ups only.** |
| Peerspace / Splacer | 2014– | Hourly event/shoot space | Take-rate | Alive [unverified] | Hourly is the only tenant-side model that cleared | Not leases. |
| LiquidSpace | 2010– | Office/coworking booking | Take-rate | Alive [unverified] | | Office. No. |
| LoopNet (CoStar) | 1995–; CoStar acq. 2012 ($860M) | Listings marketplace, 500k–800k listings | Paid listings + premium subs | Dominant, disliked | Own 2006 S-1: without an MLS, CRE listing data is "slow and expensive… often resulting in inaccurate and incomplete information." Reviews: "gets worse over time," "bait and switch." | Retail listed; small NYC storefronts thin and stale. **Partial.** |
| Yardi CommercialCafe / CommercialEdge | 42Floors folded into it 2024 | Listing syndication network for Yardi's landlord clients | Landlord software upsell; lead-gen | Alive | Listings exist to serve Yardi's landlord customers, not to serve tenants. | Incidental. |
| Crexi | 2015– | Listings + auctions | Broker subs | Alive; not researched within cap | | Partial. |
| Reonomy | 2013 → acq. Altus 2021 [unverified] | Ownership/property data | Data subs to brokers/lenders | Sold | Data side wins | No (owner data, not availability). |
| Zillow / StreetEasy commercial | — | No dedicated commercial product; StreetEasy shut non-NYC expansions after the 2013 Zillow deal | — | Never entered | "Zillow's commercial listings may lack critical information… such as financial details, lease terms." | **No** (claim StreetEasy ran commercial listings until ~2016 is unverified). |
| 2023–26 AI-native entrants | YC S24–S26 cohort (128 real-estate companies) | Lease abstraction, AI brokerage for multifamily buyers, tenant-mix analytics for landlords, site-requirement marketplace for chains, CoStar's Apartments.com AI | B2B SaaS/brokerage | Active | **Not one is a tenant-side search product for small retail.** The AI wave went to the sides with budgets — landlords, brokers, buyers, chains. | **No.** |

### 5.2 Government / civic

| Program | Jurisdiction, years | Intent | Tenant-usable list with rents? | Outcome / evidence |
|---|---|---|---|---|
| Intro 1472-2019 → LL157 of 2019 Storefront Registry (amended LL95 of 2022) | NYC; first data Dec 2019 | **Pitched as exactly this product**: "would mandate that the city compile a storefront-properties online database, which would include information on rent, size and permitted use" | **No.** What shipped: an annual DOF filing bundled with RPIE; the public dataset is BBL/address/vacant-flag; rent and lease fields self-reported and unverified by the City, 6–18 months lagged, no contact, no asking rent, no availability flag. | Council Member Bottcher (2024): "isn't fulfilling that promise… an incomplete dataset." The public-database *intent* was legislated and then hollowed out in implementation — a compliance filing, not a marketplace. |
| SBS Commercial Lease Assistance | NYC, 2018– | Free lawyers for signing/renewal/harassment | No (post-discovery) | 812 businesses served FY25; funding reported doubling to a to-be-confirmed total for FY27. |
| Storefront Startup (SBS + Chashama, Durst-backed) | NYC, 2021– | Rent-free pop-ups up to 3 months in landlord-donated vacant storefronts | **No public list; curated placement.** | 20 businesses placed by Jun 2021, 50 more funded, **200-person waitlist**; ~75% minority-owned, 61% women-owned. The only NYC program that actually *places* hopeful operators in space; demand outstrips slots 4:1. |
| Downtown Alliance RE:Store | Lower Manhattan BID, 2025– | Free pop-up ≤3 months + up to $15,000 fit-out/operating grant | No public list; application | BID-curated, corridor-specific. |
| Int 0568-2024 (mandatory pre-lease disclosures + SBS model leases) | NYC Council, 2024 | Mandated disclosures to prospective storefront tenants | Would not have listed spaces; **died** (filed, end of session) | The closest the Council came to tenant-side transparency at the point of leasing. |
| Small Business Jobs Survival Act (SBJSA) | NYC Council, 1986–2018+ | Renewal rights / arbitration | No; critics say it would *reduce* availability | Never reached a vote after 8 hearings. |
| NYC vacancy tax proposals | Mayoral support 2019; State S6804 (2025), S9823 (Apr 2026); prior versions 2021–25 died in committee | Penalize warehousing | No | Not enacted; NYC lacks state authority to levy it unilaterally. |
| San Francisco Commercial Vacancy Tax (Prop D, 2020; effective 2022) | SF NCDs/NCTs, ~2,700–2,800 parcels; downtown/Union Square excluded | $250/$500/$1,000 per linear foot of frontage for years 1/2/3+ of >182-day vacancy | **Partially** — DataSF's "Taxable Commercial Spaces" dataset (issued May 2025, refreshed daily) publishes parcel, address, filer type, and vacancy status per filing, plus a map. **No asking rent, no contact.** | Haight St broker: "At our peak, we were at 32 out of 150 were closed. Now we're below 14." Best-in-class public vacancy dataset found in the US — still not a listing. |
| Washington DC Vacant & Blighted Building registry | DC, Title 42 | Register after 90 days; tax-class penalty; public dashboard | Addresses only; no rents; mostly residential blight | Enforcement tool, not a search tool. |
| UK High Street Rental Auctions (LURA 2023; live Dec 2024) | England | Councils auction 1–5 yr leases of units vacant >365 days/24 months; refurb grants; landlord fine for non-response | **Partially** — each lot publicly marketed for a 6-week bid window; no national list | ">60 high street shop units… reoccupied without a rental auction needing to be held" (Caliskan). The *threat* of forced letting moves landlords; the register is a by-product, not transferable to NYC without state law. |
| Paris Semaest / Vital'Quartier; Chicago | — | Public entities buy ground floors and curate tenants | Not researched within cap | [not fetched] |
| Civic tech on LL157 | — | No LL157-based tenant tool found in searches; ANHD built an analysis map (2021) | No | |

**Which of these produced a tenant-usable availability list with rents? None.** San Francisco's dataset comes closest (daily-refreshed vacancy status by parcel, public map) and still has no rent or contact. LL157 was legislated to include rent, size, and permitted use, and shipped without a usable version of any of them. The programs that actually put hopeful operators into space (Storefront Startup, RE:Store, the UK auctions) are curated placements, not lists.

---

## 6. Failure-mode hypotheses

| # | Hypothesis | Demand report's rating | Contrarian's counter-rating / note |
|---|---|---|---|
| H1 | Landlords and brokers control inventory and benefit from opacity | **Strong** | Agrees and sharpens it: the size gradient (small owner-listed storefronts are the most transparent objects in the market; opacity concentrates in large, broker-listed deals) shows opacity is a **revealed-preference equilibrium**, not a fixable data hole. Does not downgrade the rating, but reframes the conclusion: not fixable by a product. |
| H2 | Broker-paid listing economics don't fund small deals | **Strong** | Not directly re-rated, but the underlying "$3–4k/mo floor" number is separately graded C (arithmetic)/D (floor claim) in §8 — small deals do get brokered in practice (two brokers solicited a newbie in-thread within hours). |
| H3 | Two-sided marketplace cold start | **Moderate** | Not directly re-rated; implicitly weakened by A1's point that supply is *visible* (signs, DOF filings, the Comptroller's count) — the cold start, if real, is on verified/priced/contactable supply, not on knowing where vacancies are. |
| H4 | Listings go stale because there is no closing loop | **Strong** | Not directly contested. |
| H5 | Small tenants are one-time, low-LTV customers | **Strong** | Reinforced, not softened: "the graveyard is office" — larger deals, repeat tenants, better economics than NYC small retail — and every one of those companies still died or pivoted to brokerage. If the model failed on easier terrain, it fails here *a fortiori*. |
| H6 | The real product is the broker relationship, not the listing | **Strong** | Supported via A2: the value named across every account (negotiation, NNN decoding, landlord vetting, off-market access) is matching on credit, not search — none of it is a listing attribute. |
| H7 (emergent) | The binding constraint is tenant creditworthiness and fit, not discovery | **Strong** | **Explicitly contested.** "The evidence for H7 is itself weak: Ganiaris is a broker and BID chair, an interested party; r/AskNYC is anecdote; 80–90% persistence is predicted equally by 'landlord is choosing' and 'nobody knows it's available.'" The contrarian's position: H7 is unproven — but that doesn't matter, because the pivot's own thesis ("discovery is the bottleneck") has zero discriminating evidence either, and the burden of proof sits with whoever wants to build something new. |

**Net reading (demand report).** Discovery is not the bottleneck; decodability and acceptance are. Every prior tenant-side product attacked discovery, found no tenant willing to pay, added a brokerage to monetize, and either died in the hybrid or became a broker. The public sector legislated the database that would have fixed discovery and delivered a compliance filing instead. The only things that demonstrably moved hopeful operators into storefronts were curated free placements with fit-out money (Storefront Startup, RE:Store) and a credible threat to landlords (UK auctions, SF's vacancy tax) — neither is a listing.

---

## 7. Load-bearing numbers

| # | Number | Source | Investor used it for | Contrarian grade | What would fix it |
|---|---|---|---|---|---|
| 1 | "~25–35% of vacant storefronts appear on any marketplace" (Manhattan Yardi feed alone ≈21%) | Tenant-landscape report §7.2, triangulating Crexi/Yardi listing counts against the Comptroller/Live XYZ vacancy count | Ranked as the #2 gap ("unlisted inventory") in the investor's ordered list of which gap is real | **D** | Numerator (marketed *spaces*, incl. upper floors/mall bays/multi-unit shells/five boroughs/future-possession units) is not a subset of the denominator (visibly vacant *ground floor*); cross-platform overlap and the Brooklyn storefront-count denominator are both guesses. Fix: 200 random addresses from `closure_triangulation`/LL157 flips, checked across the four largest marketplaces plus a walk-by. |
| 2 | "Price shown on 37 of 68 pooled cards (54%)" | Rent-terms report §1e, three-source listing sample | Cited as the headline for gap #1 ("opaque rent and terms") | **D as a tenant claim, C as arithmetic** | Frame is chosen by fetchability (LoopNet/Crexi 403'd out; CommercialCafe's default sort favors large landlords). Re-cut by size, price is shown ~60–75% of the time in the segment the customer actually shops. Fix: stratify by size band and channel, n≥100 per stratum, LoopNet via a browser. |
| 3 | Crexi "4,830 active NYC retail lease spaces / $60/SF median / 259-day median days-on-market" | Crexi's own Feb-2026 marketing blog | Cited as evidence listings exist at scale, and as the staleness signal | **C as "what Crexi says," F as a market fact** | It's marketing copy; Crexi's median $60/SF against REBNY corridor medians near $700–800/SF implies Crexi's NYC book skews outer-borough/secondary; DOM is time-since-posted-on-Crexi, inflated by ghost listings, deflated by reposting. Fix: an authorized account pull, or use Loci's own LL157 vacancy durations instead. |
| 4 | "142,000–143,000 storefronts / 15,700 vacant (11.0%) / 60–90%+ of vacancies persisting for months to years" | NYC Comptroller "Who's Minding the Storefronts?" (June 2026) | Used as the denominator for "how many" hopeful operators and vacant addresses exist | **B on the headline, D on the persistence stat** | A single proprietary walk (Live XYZ), and the persistence figure is quoted two different ways by two of the five source reports covering the same underlying Comptroller report — three storefront-universe counts (143k visible, ~70k LL157, ~63.8k Council) conflict with each other by roughly 2×. Fix: read the underlying PDF table directly and reconcile to one denominator. |
| 5 | Tenant-rep commission floor "~$3–4k/mo" below which small deals don't get brokered | Demand report §A.3, broker commission-schedule arithmetic | Used to define "the customer" as the sub-$5,000/mo segment | **C as arithmetic, D as a floor claim** | The 19%-of-year-one-rent schedule checks out, but no broker was actually asked whether $3–4k/mo is a real floor, and the same report notes small deals do get brokered. Fix: three direct broker calls (Verada, Zelnik, a KSR junior) — functionally the AC-2 call. |
| 6 | "200-person waitlist for ~50 free Storefront Startup slots" used as demand evidence | Demand report §A.4/Part B | Used as one data point calibrating "how many" operator-search episodes occur per year | **F, for a paid product** | Demand for *free* space in 2021 is not demand for *information* or for a paid product. Fix: drop it as willingness-to-pay evidence entirely. |
| 7 | "~2,600/yr" hopeful operators (net turnover proxy) | Demand report §A.4, derived from "16% of ~96,500 storefronts over six years" | Used alongside Loci's own retrodiction figure as a flow-rate estimate for the addressable market | **D** | It's a net-replacement rate, not a gross-openings rate, and it wasn't independently checked. Fix: one query against Loci's existing warehouse — first-issue SLA on-premises licences per year, Manhattan+Brooklyn. |
| 8 | "LL157 collects signed rent/SF, lease start/expiry, escalation flag, and concessions at address grain for ~70,000 storefronts" | Rent-terms report §2a, DOF's own requirement page | The basis for option (c), the FOIL letter, and the investor's stated "one number that would flip me" (§9 below) | **B** | The requirement page is a primary source; only the non-publication mechanism (RPIE confidentiality, §11-208.1) is inferred rather than confirmed. Fix: file the FOIL request. |

---

## 8. Options and capacity

### 8.1 The investor's four options

**(a) Tenant-facing listings site — do not build.**
- *Reuses:* the address frame, walk graph, LL157 vacancy overlay, webmap.
- *Lacks:* an actual listing feed. CoStar licensing is a non-starter (30+ suits on record, `docs/PAID-SOURCES.md` row 31); LoopNet and Crexi 403 every fetcher tried; Crexi Intelligence's embed terms for a resold product are unverified. It also lacks broker relationships and any closing loop.
- *Who pays:* nobody. Tenants won't (§4.4); landlords and brokers already pay LoopNet and Yardi for this exact function.
- *Why it dies the same way as before:* 42Floors, Truss, and TenantBase each launched on "brokers ignore sub-5,000-SF deals," found no tenant revenue, bolted on a brokerage, and died or pivoted; Digsy and the 2023–26 AI cohort sold to the side with budgets instead. Loci would be a fourth entrant, with worse underlying data than any of them.
- *Kill criterion:* already met — pre-killed by the prior-attempts table in §5.
- *Sessions:* 40–80 to a v1, then permanent ongoing operations for freshness and licence risk.

**(b) Free per-address dossier over vacancies-as-leads, monetized on the paid side.**
The product shape the research points to: for one vacant storefront, *what it really costs* (asking rent if findable, tax pass-through, an estimated fit-out class from the prior tenant's DOHMH/DOB history), *will this landlord take me* (owner portfolio, months vacant, prior small-tenant lease starts, licence churn at the BBL), and *is this block worth it for my category* (the existing Loci card).
- *Reuses:* most of the existing warehouse — `analysis.storefront` (253,519 filing rows, 31,797 premises), `analysis.storefront_tenure` (50,565 premises, 34,099 turnovers), `analysis.storefront_pipeline` (541,051 filing rows with fit-out/sign/permit counts), `analysis.licence_event` (43,863 SLA licences), `analysis.closure_triangulation` (4,668 corroborated closures, not promoted), legality from PLUTO, the graded card, and the restaurant revenue model (grade C). The card already prints named vacant storefronts within 400m with floor area, last use, and vacant-since.
- *Lacks:* (i) asking rent, structurally — the card's "Rent ceiling (monthly)" line reads "—" today; (ii) a landlord-acceptance label, because the LL157 lease-start/escalation/concession fields that would train one are collected and withheld; (iii) owner contact — cheaply fixable from HPD registration and ACRIS, both free and not yet ingested; (iv) a freshness loop, since the public registry updates annually and the quarterly ground truth (LiveXYZ) is a paid source; (v) a tenant-facing channel of any kind.
- *Who pays:* hypothesized as either the small-deal tenant reps who can't afford to prospect below $5k/mo, or landlords with ≥9-month vacancies. Both are untested hypotheses — this **is** AC-2, which has had zero discovery calls to date.
- *Why it might not die like the predecessors:* it does not sell discovery and never becomes a broker. It sells decodability, which Loci already computes at near-zero marginal cost, and it stays honest to the charter's likely earned claim ("cost of search," not "better decisions"). A dossier needs no survival gate to be true.
- *Kill criteria:* the AC-2 consequence branch (three written no's closes the segment); or the rent-band predictions in `docs/recommendations/predictions/` missing on more than half of scored operators. Current score: 1 hit (El Punto, $4,000 within a $3,500–6,500 band) and 1 miss (Fazenda, $15,000 on under 1,000 sq ft against a $37,500 guess) — the rent line is not yet trustworthy enough to lead a page.
- *Sessions:* 15–25 (HPD/ACRIS owner ingest, findable-rent staging, an acceptance prior from `storefront_tenure`, a re-index cadence, a rendered page) plus the three AC-2 calls.

**(c) FOIL and advocacy for the LL157 rent fields.**
- *Reuses:* `analysis.storefront` is already keyed on `premises_id = BBL|unit`; the day the columns appear they join in one migration.
- *Lacks:* legal standing beyond a FOIL request; the statute's publication clause was never fetched.
- *Who pays:* nobody; the cost is one letter and the 20-business-day statutory clock.
- *Why it's worth doing anyway:* asymmetric payoff. A yes turns a $10,000/yr CompStak Enterprise floor into free signed rent at 70,000 addresses, fills the empty rent line for every category, and resolves the rent-data question without a paid feed. A no costs nothing and creates the record. The realistic first ask is the May-2021 census-tract aggregate; address-level fields are the anticipated denial.
- *Kill criterion:* a denial citing §11-208.1. Then stop — don't litigate, don't lobby.
- *Sessions:* 1–2, then a statutory clock and one possible appeal.

**(d) The card line — build now.**
"Here are the vacant storefronts near this gap address, with whatever asking rent is findable, who to call, and how long it has sat." Roughly 70% of this shipped already (D67's named vacancy table). What's missing:
- Asking rent where a landlord chose to show one (Craigslist, Facebook groups, BID pages, PropertyShark/Realmo where not "Price on request") — hand-pulled per candidate address, never scraped from LoopNet or Crexi.
- Owner/managing-agent contact from HPD registration (free).
- A "monetized as pop-up" flag from Storefront.com — a shadow-availability signal.
- Unit normalization: one $/month and one $/SF/yr per row.
- *Who pays:* nobody. It serves the first customer — the owner, already searching for El Punto's second site.
- *Kill criterion:* none needed; it's a card line, deleted if the owner never reads it.
- *Sessions:* 2–4.

### 8.2 The contrarian's smallest test — option (e)

**Pull 100 vacant storefronts from `closure_triangulation`/LL157 flips on one walkable Brooklyn corridor. Walk it once, recording sign-with-phone share and marketplace-listed share. Then call each contact under two randomized personas, 50 each: a vague first-timer ("opening a café, what's the rent?") and a qualified operator ("two cafés, $X liquidity, 5-year, what's the ask?"). Record whether an asking rent and term arrive within 48 hours.**

**Pre-registered thresholds:**
- **Disclosed-on-call ≥70% for either persona** → opacity is a scraper's problem, not a tenant's; the pivot is dead, and §6's fetch-block log is retired as evidence.
- **Disclosed-on-call <40% for both personas** → a real information gap exists and a willingness-to-pay experiment is earned.
- **≥25 percentage-point gap between the two personas** → confirms price discrimination on tenant quality (H1/H7 combined): the tenant's problem is *qualification*, not information, and the product — if any — is a credit-and-fit dossier aimed at landlords, not a search tool aimed at tenants.

Run the AC-2 broker call the same fortnight; it answers the commission-floor question (§7 row 5) and the payer question at once.

- *Sessions:* 2, at $0 cost.

### 8.3 Capacity table

Loci's baseline cadence is roughly two decision sessions a day (114 decisions over 33 sessions since 2026-09-01).

| Option | Sessions | Displaces |
|---|---|---|
| (a) listings site | 40–80 to v1, then permanent ops | Everything: the P3′/P5/P6 survival-gate write-up due 2027-01-31, the AC-1 trade-area sheet, AC-2 by 2026-12-31, category expansion — roughly a quarter of the project, for a product with a documented zero price. |
| (b) dossier v1 | 15–25 plus the three AC-2 calls | Category expansion for about two weeks; AC-6 follow-up. Does not touch the survival gate, whose pre-registered checks have already run (P3′ restaurant 65.2% FAIL, P5 PPV all-fail against a 0.50 floor). |
| (c) FOIL | 1–2, then a statutory clock | Nothing. |
| (d) card line | 2–4 | Nothing material. |
| (e) 100-storefront corridor test | 2, $0 | Per the contrarian: AC-1's own two-week trade-area sheet, and the P3′/P5/P6 pre-registration due 2027-01-31 — where grocery PPV already reads 0.07 and restaurant 0.29 against a 0.50 floor. The contrarian's position is that the survival gate, which is failing, needs the capacity more than a new product for customers who have never been asked what they'd pay. |

**What all five displace, taken together:** every option beyond (c) and (d) draws down capacity that is currently committed to the survival-gate pre-registration due 2027-01-31, AC-1 (the Gowanus bathhouse base-rate decision, already partly landed at 1.7 openings/year citywide 2019–2026), category expansion (the GTM-112 checklist process that admitted `bathhouse_sauna`), and operator validation (the recommendation-ledger scoring of El Punto/Fazenda-style predictions). Options (c) and (d) are cheap enough not to compete meaningfully with any of that. Options (a), (b), and (e) do compete, at very different scales — (a) most severely, (e) least severely per session but with the largest single-test information yield.

---

## 9. The one number that flips each reviewer

**Investor:** *"A FOIL response that returns the LL157 monthly-rent-per-SF column at premises grain."* With it, the dossier (option b) becomes the only address-grain signed-rent product in New York built on public data, the rent-line question resolves without a paid feed, and the investor would move the dossier to the front of the queue ahead of category expansion. Without it, the dossier stays "a pitch waiting for a broker to name a price." The investor names a secondary flip: *"one tenant-rep broker who says in writing what a qualified sub-$5k/mo lead is worth to them"* — i.e., a concrete AC-2 outcome.

**Contrarian:** the corridor test's own pre-registered disclosure rate. A result under 40% disclosed-on-call across both personas is the number that flips the contrarian toward "a real information gap exists" and earns a willingness-to-pay experiment. Conversely, a result at or above 70% is the number that would confirm the contrarian's verdict outright and retire the machine-access fetch-block log as evidence of anything tenant-relevant. The contrarian treats the FOIL result as worth having regardless of outcome, but does not name it as the single flip — the corridor-test's disclosure rate is the operationalized test the contrarian actually pre-registered a decision rule against.

---

## 10. Open questions for QUESTIONS.md

- **Does asking rent and lease term actually disclose on a phone call, for a representative sample of vacant storefronts?**
  *Why it matters:* this is the crux the investor and contrarian split on — whether the opacity documented in the three research reports is a real tenant-facing gap or an artifact of automated fetchers being blocked (403s, blank template fields) that a human with a phone would never hit.
  *How to answer:* run the contrarian's pre-registered corridor test (§8.2) — 100 addresses from `closure_triangulation`/LL157 flips on one Brooklyn corridor, walk it once, call every contact under two randomized personas, record disclosure within 48 hours against the ≥70%/<40%/≥25pp thresholds already pre-registered.

- **Will DOF release the LL157 monthly-rent-per-SF, lease-start/expiry, escalation-flag, or concession fields under a FOIL request?**
  *Why it matters:* this is the investor's stated flip number for the whole dossier option — a yes turns Loci into the only address-grain signed-rent product on public NYC data and removes the need for a paid CompStak/Crexi/CoStar feed for that purpose.
  *How to answer:* file the FOIL request (option c). Ask for the census-tract-grain 2021 aggregate as a realistic first ask if the address-grain fields are denied; note the denial's citation (expected: RPIE confidentiality, Admin Code §11-208.1) so the INFERRED mechanism in §3.3 becomes confirmed either way.

- **What does a real tenant-rep broker, lender/feasibility shop, and 3–30-unit operator actually say a sub-$5,000/mo lead or a landlord-acceptance dossier is worth to them?**
  *Why it matters:* this names or kills the paying customer for option (b), the dossier — the single biggest unresolved risk both reviewers flag, and it is already chartered as AC-2 with a 2026-12-31 deadline.
  *How to answer:* the three AC-2 discovery calls (one tenant-rep broker, one lender or feasibility shop, one 3-to-30-unit operator), each producing a dated written record of what was shown, what was asked, what price was named, and what the person said they would pay for.

- **Does a landlord-acceptance signal (LL157 lease starts, licence churn at the BBL, months vacant) actually predict which vacant storefronts a small operator can get into?**
  *Why it matters:* if H7 is right (the binding constraint is acceptance, not discovery — contested between the demand report and the contrarian in §6), the dossier's headline field should be an acceptance score, not a decodability score; this is currently undecided and changes what option (b) leads with.
  *How to answer:* cross `storefront_tenure`/`licence_event` turnover history against the corridor test's outcomes (which contacts actually converted to a shown space vs. a flat "no") once the §8.2 test has run.

- **Is the ~25–35% marketplace-coverage estimate (and the 259-day median days-on-market) real, or an artifact of mismatched numerator and denominator?**
  *Why it matters:* the investor's #2-ranked gap ("unlisted inventory") depends on this number, which the contrarian grades D — a market-fact grade of F for the Crexi DOM figure specifically.
  *How to answer:* draw 200 addresses at random from LL157 flips/`closure_triangulation`, check presence across the four largest marketplaces plus a walk-by, and compute a like-for-like ratio at n≥200, per the contrarian's proposed fix (§7 row 1).

- **Has there been any further legislative movement on storefront-disclosure mandates (an Int 0568-2024 successor) or an NYC/NYS vacancy tax since this research was done?**
  *Why it matters:* both reviewers agree that only a mandate, a tax, or an un-withholdable data source changes the landlord's incentive to disclose — the StreetEasy analogy fails on lease structure, so no listing product on its own moves this. A live bill would change the calculus on options (c) and (e).
  *How to answer:* a periodic check of NYS Senate bill trackers (S9823, S1451A) and NYC Council Legistar for any successor to Int 0568-2024.

---

## 11. Sources — every URL cited across the five research files, deduplicated

Access date for every URL below is 2026-09-17 unless a specific date is embedded in the URL or was noted otherwise in the source report.

http://catalog.data.gov/dataset/vacant-and-blighted-building-addresses
http://www.throggsneckbid.com/nyc-storefront-registration-requirement
https://abc7news.com/post/remember-vacant-storefront-tax-san-francisco-heres-how-going/16588700
https://aiforcrecollective.com/ai-tools-for-commercial-real-estate
https://aldersol.com.au/landlord-disclosure-obligations-retail-leases
https://anhd.org/blog/storefront-registry-will-help-small-businesses-combat-speculation
https://apers.app/learn/operations/leasing/leasing-commission-structures-broker-comp
https://assets.ctfassets.net/6zi14rd5umxw/gco2l7R3CpZVneoym5Pf9/1551a7465151ed5c6724ce786fad501c/Brooklyn_Retail_Report_3Q15.pdf
https://beancount.io/blog/2026/07/10/san-francisco-commercial-vacancy-tax-guide
https://benjaminbwright.substack.com/p/loopnets-dominant-position-in-commercial
https://bloxcommercial.com.au/retail-lease-disputes-nsw
https://bronxlittleitaly.com/bid/businessresources
https://buj.org/tracking-the-trends-for-nyc-small-businesses
https://bushwickdaily.com/news/new-bill-seeks-to-guarantee-lease-renewals-for-nyc-small-bus
https://business.columbia.edu/sites/default/files-efs/imce-uploads/svannieuwerburgh/papers/CQR_12012025.pdf
https://cdrenyc.com/retail-space/cost-lease-term-manhattan-retail-space-for-rent-guide
https://citymeetings.nyc/meetings/new-york-city-council/2024-04-17-1000-am-committee-on-small-business/chapter/what-is-the-status-of-the-implementation-of-local-law-157-of-2019-regarding-the-reporting-of-monthly-rents-and-lease-status-for-commercial-spaces
https://citymeetings.nyc/meetings/new-york-city-council/2025-01-30-0130-pm-committee-on-small-business
https://columbiacompstak.com/methodology
https://commercialobserver.com/2025/10/rebny-brooklyn-retail-h1-2025
https://commercialobserver.com/2026/02/manhattan-soho-retail-h1-2025-rebny
https://commercialobserver.com/2026/05/intuit-turbotax-retail-lease-one-willoughby-square
https://commercialobserver.com/2026/07/storefront-lease-555-west-25th-street
https://committees.westminster.gov.uk/documents/s70150/7.%20High%20Street%20Rental%20Auction%20-%20Cabinet%20Report%20and%20appendices.pdf
https://compstak.com/blog/q1-2026-retail-lease-deals
https://compstak.com/blog/retail-rent-concession-trends-compstak-lease-data
https://compstak.com/go/q1-2026-retail-deals-of-distinction
https://comptroller.nyc.gov/newsroom/press-releases/new-report-citywide-storefront-vacancies-decline-but-some-neighborhoods-still-face-20-empty-retail-spaces
https://comptroller.nyc.gov/reports/retail-vacancy-in-new-york-city
https://comptroller.nyc.gov/reports/whos-minding-the-storefronts
https://conveyancing.com/information-centre/commercial-leases
https://council.nyc.gov/budget/wp-content/uploads/sites/54/2026/02/Department-of-Small-Business-Services-Commercial-Lease-Assistance-1.pdf
https://council.nyc.gov/data/vacant-storefronts
https://data.cityofnewyork.us/City-Government/Storefronts-Reported-Vacant-or-Not/92iy-9c3n
https://data.cityofnewyork.us/api/views/92iy-9c3n.json
https://data.sf.gov/Economy-and-Community/Taxable-Commercial-Spaces/rzkk-54yv
https://data.sfgov.org/Economy-and-Community/Map-of-Commercial-Vacancy-Tax-Status/iynh-ydf2
https://dob.dc.gov/vacantbuildings
https://downtownny.com/business/business-resources/storefront-business-assistance
https://downtownny.com/restore
https://edc.nyc/nyc-groceries-operators-rfp
https://edc.nyc/rfps
https://eladmichael.com/he/Blog/Understanding-the-Good-Guy-Guaranty-in-NYC-Commercial-Leases
https://en.wikipedia.org/wiki/Eastern_Consolidated
https://fkks.com/news/opening-your-restaurant-avoid-the-good-guy-guaranty-leasing-trap
https://getstationcrm.com/blog/what-is-a-retail-leasing-broker
https://inclusivecre.com/zillow-for-commercial-real-estate
https://katzretail.com/listings
https://law.justia.com/codes/new-york/rpp/article-9/291-cc
https://legistar.council.nyc.gov/LegislationDetail.aspx?ID=3877905
https://legistar.council.nyc.gov/LegislationDetail.aspx?ID=5641451
https://legistar.council.nyc.gov/LegislationDetail.aspx?ID=6565923
https://legistar.council.nyc.gov/LegislationDetail.aspx?ID=6716352
https://loopnet.pissedconsumer.com/complaints/RT-P.html
https://midtownsouthcc.org/blogs/how-bad-is-nycs-vacant-storefront-problem-council-wants-to-know
https://myrtleavenue.org/lease
https://newyork.craigslist.org/search/brk/off
https://newyork.craigslist.org/search/mnh/off?query=retail%20store
https://nextcity.org/urbanist-news/can-nyc-storefront-registry-level-the-playing-field-for-commercial-tenants
https://nomadgroup.io/feeds/blog/commercial-lease-deposit
https://nomadgroup.io/feeds/blog/commercial-lease-negotiation-checklist
https://nyc-business.nyc.gov/nycbusiness/business-services/legal-assistance/commercial-lease-assistance-program
https://pennplazaproperty.com/blog/commercial-lease-negotiation-strategies-nyc-landlords-2026
https://portal.311.nyc.gov/article?kanumber=KA-01277
https://property.jll.com/search?propertyType=Retail&location=New%20York
https://queenseagle.com/all/sbjsa-city-council-small-business-queens
https://realgraph.co/
https://realmo.com/restaurants/for-lease/ny/brooklyn
https://redwoodnyc.com/leasing-guide-full-commission
https://rltyservice.com/rpie/storefront-registry
https://rtl-re.com
https://rtl-re.com/uploads/pdf/FINAL-WinickMagazine.pdf
https://sandalphoncapital.com/2019/01/17/sandalphon-follows-on-in-truss-15m-series-a-2
https://sftreasurer.org/business/taxes-fees/commercial-vacancy-tax-cvt
https://shopyourcity.cityofnewyork.us
https://sinvin.com/listings/11-prince-street
https://sinvin.com/listings?type=Retail
https://sky-nyc.com/blog/start-small-business-nyc-finding-commercial-space
https://sohobroadway.org/commercial-lease-assistance-program-for-small-businesses
https://sprintlaw.com.au/articles/retail-leases-in-queensland-guide-to-the-retail-shop-leases-act
https://streeteasy.com/search?search=commercial
https://streeteasy.com/talk/discussion/43457-website-for-commercial-spaces-for-sale
https://techcrunch.com/2017/08/23/truss-raises-7-7m-for-its-commercial-real-estate-tech-platform
https://techcrunch.com/2018/07/18/knotel-acquires-42floors-in-order-to-build-the-blockchain-of-property
https://thecounter.org/covid-19-restaurant-lease-negotiations-landlords-reduce-rent
https://therealdeal.com/issues_articles/zillow-shocks-insiders-with-streeteasy-strategy
https://therealdeal.com/new-york/2018/06/15/eastern-consolidated-is-going-out-of-business
https://therealdeal.com/new-york/2021/06/15/durst-backed-nonprofit-puts-popups-into-empty-storefronts
https://traded.co/company/kassin-sabbagh-realty
https://traded.co/company/tri-state-commercial-realty
https://tristatecr.com
https://www.1degree.org/opp/apply-for-rent-free-storefronts-chashama
https://www.6sqft.com/de-blasio-is-considering-a-vacancy-tax-for-landlords-who-leave-their-storefronts-empty
https://www.alleywatch.com/2019/08/wework-acquires-spacious-restaurant-coworking
https://www.biggerpockets.com/forums/432/topics/531943-how-come-they-never-show-noi-on-loopnet
https://www.bizbuysell.com/business-opportunity/profitable-manhattan-deli-30k-weekly-sales-absentee-ownership/2442575
https://www.bizbuysell.com/business-opportunity/turnkey-brooklyn-restaurant-key-money-opportunity-6-000-sf-full/2445788
https://www.bizquest.com/asset-sales/brooklyn-mexican-restaurant-opportunity-closed-asset-sale/BW2458544
https://www.bizquest.com/business-for-sale/brooklyn-corner-grocery-with-rent-income-and-huge-deli-flower-upside/BW2441338
https://www.brevitas.com/
https://www.brooklynartcave.com/about-1
https://www.brownstoner.com/brooklyn-life/flatbush-avenue-church-avenue-business-improvement-districts-bid-merger-fee-change
https://www.buchalter.com/insights/update-on-san-franciscos-treatment-of-vacant-properties
https://www.cbre.com/insights/figures/manhattan-retail-figures-q2-2026
https://www.cbre.com/properties/properties-for-lease/retail
https://www.cityfeet.com/cont/new-york-ny/retail-space-for-lease
https://www.commercialcafe.com/blog/42floors-relaunched-following-yardi-acquisition
https://www.commercialcafe.com/commercial-real-estate/us/ny/brooklyn/retail-space/
https://www.commercialcafe.com/commercial-real-estate/us/ny/new-york/retail/
https://www.commercialsearch.com/retail/us/ny/new-york-city
https://www.costargroup.com/press-room/2026/costar-group-launches-apartmentscom-ai-redefining-future-apartment-search
https://www.craigslist.org/search/area/newyork?cat=off
https://www.craigslist.org/search/area/newyork?cat=off&query=storefront
https://www.credaily.com/newsletters/new-york/issue/nyc-doubles-funding-for-small-business-lease-assistance
https://www.crexi.com/blog/new-york-city-commercial-real-estate-market
https://www.crexi.com/lease/properties/NY/New-York/Retail
https://www.cushmanwakefield.com/en/united-states/insights/us-marketbeats/new-york-city-area-marketbeats/manhattan-retail
https://www.cushmanwakefield.com/en/united-states/properties/new-york
https://www.facebook.com/groups/340036112096660/posts/846840741416192
https://www.facebook.com/groups/649498905826315
https://www.facebook.com/groups/commercialpropertiesny
https://www.failurepedia.com/cases/42floors
https://www.instagram.com/p/DSTUMpgjTqH
https://www.instagram.com/reel/DYk8UrANtgD
https://www.ksrny.com/agents/david-green
https://www.ksrny.com/listings
https://www.landlordzone.co.uk/news/councils-share-ps10m-to-roll-out-empty-shop-auction-scheme
https://www.lee-associates.com/new-york/lee-associates-new-york-retail-leasing-services
https://www.lee-associates.com/wp-content/uploads/2026/07/2026-Q2-Market-Report-Final.pdf
https://www.lincolnsquarebid.org/2021/05/13/storefront-startup-program-to-activate-vacant-storefronts
https://www.listingsproject.com
https://www.localize.city
https://www.loopnet.com/Listing/2528-Broadway-New-York-NY/31973064
https://www.loopnet.com/search/retail-space/manhattan-county-ny/for-lease
https://www.loopnet.com/search/retail-space/new-york-ny/for-lease
https://www.manhattancc.org/storefront-resurgence-project
https://www.manhattancc.org/storefront-tracker
https://www.marcusmillichap.com/research/market-report/new-york-city/new-york-city-2026-investment-forecast-retail-market-report
https://www.matthews.com/insights/new-york-retail-market-report-q2-2026
https://www.metro-manhattan.com/blog/key-terms-to-include-in-a-commercial-lease-offer-a-guide
https://www.metro-manhattan.com/blog/understanding-brokerage-fees-in-nyc-office-space-search
https://www.metro-manhattan.com/blog/what-is-the-good-guy-guarantee-in-new-york-city-commercial-real-estate
https://www.metro-manhattan.com/commercial-space/retail-space
https://www.nmrk.com/properties
https://www.nyc.gov/assets/finance/downloads/pdf/21pdf/storefront-registry-submission-summary-2020.pdf
https://www.nyc.gov/assets/finance/downloads/pdf/rpie/storefront_faq.pdf
https://www.nyc.gov/site/finance/property/property-rpie.page
https://www.nyc.gov/site/finance/property/storefront-registry-requirement.page
https://www.nyc.gov/site/finance/property/storefront-registry.page
https://www.nycbar.org/reports/small-business-jobs-survival-act-testimony
https://www.nycbar.org/serving-the-community/legal-forms-resources/real-estate-forms
https://www.nyclease.com/
https://www.nycretailleasing.com
https://www.nycsmallbusinessresourcenetwork.org
https://www.nysenate.gov/legislation/bills/2025/S6804
https://www.nysenate.gov/legislation/laws/RPP/291-C
https://www.nytimes.com/interactive/2025/10/06/dining/how-to-open-restaurant-nyc.html
https://www.pacesbdc.org/finding-commercial-space
https://www.peerspace.com/s/new-york--ny/pop-up-shop
https://www.pjlesq.com/post/2015/09/29/do-small-business-owners-need-an-attorney-to-review-their-commercial-lease
https://www.prnewswire.com/news-releases/squarefoot-raises-16-million-in-series-b-funding-to-modernize-commercial-real-estate-300952094.html
https://www.propertyshark.com/cre/commercial-property/us/ny/brooklyn/30-flatbush-avenue
https://www.propertyshark.com/cre/commercial-real-estate/us/ny/brooklyn
https://www.propertyshark.com/cre/retail/us/ny/new-york-city
https://www.prospect-by-buildout.com/blog/a-loopnet-com-review
https://www.realtor.com/commercial/
https://www.rebny.com/press-release/h1-2025-brooklyn-retail-report-limited-availability-spurs-investment-sales
https://www.rebny.com/press-release/latest-brooklyn-retail-report-shows-strong-demand-fundamentals-and-emerging
https://www.rebny.com/press-release/new-rebny-report-finds-manhattan-retail-momentum-extending-beyond-prime-corridors-in-first-half-of-2026
https://www.rebny.com/press-release/rebny-launches-nyc-lease-a-new-trusted-site-for-lease-forms
https://www.rebny.com/reports/manhattan-retail-report-first-half-2026
https://www.reddit.com/r/AskNYC/comments/1hdfn6a/
https://www.reddit.com/r/AskNYC/comments/1ivszjs/
https://www.reddit.com/r/AskNYC/comments/uywq2m/
https://www.reddit.com/r/Brooklyn/comments/1n1mpwc/
https://www.reddit.com/r/CommercialRealEstate/comments/148na9e/
https://www.reddit.com/r/CommercialRealEstate/comments/1gy8mry/
https://www.reddit.com/r/CommercialRealEstate/comments/1nuwocg/
https://www.reddit.com/r/CommercialRealEstate/comments/1pth3t9/
https://www.reddit.com/r/RealEstate/comments/96u288/
https://www.reddit.com/r/parkslope/comments/1doz6xh/
https://www.retail-insight-network.com/news/uk-launches-auction-system-for-vacant-shops
https://www.ripcony.com/manhattan-commercial-real-estate
https://www.rosenbergestis.com/media/blog/nyc-property-tax/supplemental-storefront-registry-deadline-august-15-2024-2
https://www.rosenbergestis.com/media/blog/nyc-property-tax/two-retail-focused-bills-to-watch-after-recent-action-in-albany
https://www.rugby.gov.uk/w/high-street-rental-auctions
https://www.sec.gov/Archives/edgar/data/1353209/000095013406011225/z17421b4e424b4.htm
https://www.sec.gov/Archives/edgar/data/731947/000073194701500019/lease.htm
https://www.sharplaunch.com/blog/the-ultimate-guide-to-commercial-real-estate-listing-sites
https://www.spacelist.ca/
https://www.spacelist.co/
https://www.splacer.co/spaces/new-york/pop-up-store
https://www.spur.org/voter-guide/2020-03/sf-prop-d-vacancy-tax
https://www.squarefoot.com/
https://www.squarefoot.com/blog/why-we-launched-flex-by-squarefoot
https://www.stewart.com/en/insights/new-york-city-administrative-code-11-208-1
https://www.tenantbase.com/press
https://www.teslarealtygroup.com/pdf/form_rentals/rsl_000.pdf
https://www.thecityreporter.nyc/2026/06/04/nyc-empty-storefronts-vacancy-neighborhoods-mamdani
https://www.thehabitatgroup.com/articles/3522
https://www.thestorefront.com/search/new-york
https://www.thestorefront.com/selections/cheap-retail-space-new-york
https://www.thestorefront.com/selections/cheap-space-brooklyn
https://www.torresbusinesslaw.com/practice-areas/commercial-lease-review
https://www.troutman.com/insights/considerations-for-new-york-city-commercial-leases
https://www.unionsquarenyc.org/publications
https://www.unionsquarenyc.org/s/2025-10-15-BB-Q3-Final-High-Res.pdf
https://www.unionsquarenyc.org/usqnews/news-release-2025-commercial-market-report
https://www.veradaretail.com/the-guide-to-choosing-your-next-retail-space
https://www.vox.com/recode/2019/12/12/21012723/wework-spacious-shutting-down-adam-neumann-coworking
https://www.winick.com/listings
https://www.yardi.com/blog/yardi-acquires-42floors-com
https://www.ycombinator.com/companies/industry/real-estate-and-construction
https://www.youtube.com/watch?v=Ah3Z9DnyZ6Q
https://www.youtube.com/watch?v=ykjqRqULN_8

*End of memo.*
