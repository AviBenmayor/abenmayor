# Pre-registered guesses — Fazenda, 177 Mott St, New York NY 10012

**Written:** 2026-09-17, **before** the shop has a trading year behind it — it opened in summer 2026
and no sales figure exists yet, from the operator or anyone else. Every number below is frozen; a
correction goes in a new dated file, never in this one. **Purpose:** a forward test of Loci's numbers
against one real coffee shop in its first year. **This is a prediction, not a validation:** the
guesses cover the twelve months **2026-09-17 to 2027-09-17** and are scored on **2027-09-17**, when
the operator is asked the questions in §6. Same shape as
`predictions/stone-street-coffee-379-broome-2026-09-15.md` (café, 45 m away — the closest sibling),
`predictions/lions-milk-2026-09-13.md` (café) and `graham-ave-376-2026-09-13.md` (El Punto).
**What the shop is:** the owner's correction of 2026-09-17 — part coffee shop, part men's clothing
store, **not a restaurant**. Loci filed it as a restaurant because the only source that sees it is a
health-department food permit. **The page prices the coffee counter; the clothing is a second line
Loci cannot price and it is stated in prose only.** **Reader:** written for the shop's operator; if it
turns out to be a manager, drop the "you/your" framing and the pay-yourself line, nothing else changes.
**Warehouse values are live** — `data/loci.duckdb` read on 2026-09-17, supply set `ed55301203a4`,
as-of pin 2026-09-16, forecast vintage untouched. No fallback to older files was needed.

## 1. The shop

| | |
|---|---|
| Name | **Fazenda** — one name, **one source**: the health department. Not in Overture (2026-09-01 snapshot) or Foursquare (2026-09-02). Cluster 206555, single source, `poi_status` **unknown** (`never_inspected:default_not_evidence`) |
| Address | 177 Mott St, NY 10012 — the **south-east corner of Mott and Broome**, 45 m east of the Stone Street Coffee record and 52 m from Deux Luxe. Loci `address_id` **1004807502**, area **MN0201** SoHo–Little Italy–Hudson Square |
| Type | Health department: no cuisine code yet. Public listings (web, 2026-09-17, not Loci): "Brazil-inspired coffee shop and beer bar in Nolita, set inside a curated, premium multibrand menswear store" (barista job ad); Instagram "Multibrand Menswear Store, 177 Mott Street"; website "Opening Summer 2026". Loci category for this page: **`cafe_bakery`**, as the Stone Street page used. **Clothing is not a Loci category** — none of the sixteen — so there is no supply ratio for it |
| Health record | CAMIS **50191163**, **never inspected** — one placeholder row dated 1900-01-01, record date 2026-09-16, no grade. Loci first observed it **2026-09-08** |
| Liquor | **No licence** in the SLA active, pending or inactive files (2026-09-16 pulls) under this name or at 177 Mott / 372 Broome, although the shop bills itself a beer bar. Expect a beer-and-wine application to appear; until it does, Loci cannot see the bar |
| First seen trading | **2026-09**, `backfill_censored` — the first-seen ledger started for this location the month it appeared, so Loci **cannot say when it opened**; the web says summer 2026. About **two months** trading at most |
| Seats, hours, price tier, star rating | **None of it is in the warehouse**, and none of it is on the web yet either — 447 Instagram followers, six posts |
| Same brand elsewhere | Loci sees **no other** Fazenda. The website lists one address. **Any money number must be for 177 Mott only** |
| The building (PLUTO 26v2) | Billing BBL 1004807502 "372 Broome Street", class **RM = mixed-use condominium** (Brewster Carriage House Condominium, condo 2333), 6 floors, 9 flats + **1 commercial unit**, building 27,953 sq ft, lot 4,592 sq ft, **corner lot, 50.75 ft on Broome × 97 ft down Mott**, built 1900. `retailarea` **0** — a condo lot carries no retail floor in PLUTO, so the model falls back to a typical footprint (§4a) |
| Storefront register | **One commercial unit, CU1 (unit BBL 1004801101), filed three times a year under three doors** — 175 Mott, 177 Mott, 372 Broome — every year 2020–2024: OTHER (2020) → RETAIL (2021–22) → EDUCATIONAL SERVICES (2023–24), never vacant, one turnover in five years. Fazenda's own lease is not yet in the register (the 2025 filing is not in). One DOB fit-out filing at the lot, by the condominium, 2024-03-28 → permit 2024-04-05; nothing under Fazenda |
| Zoning | **C6-2G**, commercial. Special Little Italy District. No landmark, no historic district. Legal for a shop |

**The most important line in that table.** The whole ground-floor corner is **one** commercial unit
with three doors, and the shop is a clothing store first. The model has no floor area for it at all
(condo lot) and prices a **typical 2,000 sq ft restaurant** (§4a). Our guess is a unit of about
**2,500 sq ft** (1,500–4,000) of which the coffee counter takes about **a third, 800 sq ft**; every
per-square-foot number below is given on those two figures. **Confirming the real square footage,
and how much of it the counter gets, is the cheapest useful thing the operator can tell us.**

## 2. The block

| | |
|---|---|
| Homes within a 5-minute walk (400 m) | **6,425** (20,840 homes per km²); 19,032 within 800 m |
| Jobs within 400 m | **16,081** — 6,963 shop, 3,968 office, 5,150 other. **2.5 jobs for every home** |
| Subway entries within 400 m | **24,287 weekday**, **24,199 Saturday** (1.00×), 18,491 Sunday. Busiest weekday stretch is late afternoon (9,403); Saturday late afternoon nearly matches it (9,269), and Saturday evening (6,327) beats a weekday evening (5,667). *Twice the Stone Street / Deux Luxe figure (12,253) on the same window, 2025-01-01..2026-08-31, because from this corner the **Grand St B/D** entrances come inside the 400 m walk at 354 m; Spring St (6) at 275 m and Bowery (J/Z) at 305 m are shared with the other two* |
| Loci street type | **`retail_mixed`**, retail index **1.00**, intensity **1.00** — the top of the scale |
| Pedestrian counts | **None on this street.** The nearest city counter is 592 m away (2026-05: AM 1,217 / midday 3,547 / PM 4,315); a camera 157 m away counts nothing |
| Storefronts within 400 m | **581**, of which **61 empty (10.5%)** at 2024-12-31. Nearest empty one **12 m** away (368 Broome, empty every filing since 2022). 468 premises with a tenure record: **18.6% turn over in a year, median tenant stays 2.0 years** |
| New homes being built within 400 m | 59 permitted, but only **12 active and 45 stalled**; 66 finished in the last two years |
| Fit-outs and licences within 400 m | 206 storefront fit-out filings in the last 12 months; 17 liquor applications |

Read plainly: **this is a workplace-and-visitor corner, not a bedroom street** — two and a half jobs
per home, Saturday as busy as a weekday, and one shop in five changes hands each year. Same read as
the two records across the road, with more subway feet.

## 3. Who else sells coffee and food nearby (400 m)

Loci's counted supply at this address, supply set `ed55301203a4`: **cafe_bakery 98**,
**restaurant 198**, **bar 54**, **convenience 3**. The same 400 m disc by trading status (distinct
locations): **cafés — 96 open, 30 unknown, 1 closed**; **restaurants — 163 open, 99 unknown,
4 closed**; bars — 50 open, 26 unknown.

Nearest coffee and bakery competitors: **Coffee For Sasquatch 42 m**, **Stone Street Coffee 45**,
Voila Crepes & Waffles 57, Kolkata Chai 61, Caffe Roma 65, On Broome 66, Milkweed Studio 69, Frame
Cafe 71, Figo Il Gelato 73, Cafe Integral 73, Goat Bakeshop 74, Urban Backyard 74, Leon's Bagels 81,
Chiu Hong Bakery 96, Parisi Bakery 99, Epistrophy 106, The Chai Spot 107, Black Seed Bagels 111,
Ferrara's 159, Alden's Coffee 159. **Two shops inside 200 m already run a café inside a clothing
store — the same format as this one: Madhappy / Pantry 148 m and Café Leon Dore 199 m (Aimé Leon
Dore 196 m).** Chains in the ring: **Luckin Coffee 178, Toby's Estate 186, Maman 191, The Elk on Mott
238, Blank Street 243, Joe & The Juice 257, Paris Baguette 269, two Starbucks (276, 292).** Nearest
restaurants and bars: on this corner **Gem Home 11 m** (bar) and **Oriana 18 m** (a new restaurant,
never inspected, liquor licence issued 2026-04-07 at "174 Mott St", pinned by the SLA onto this
lot), Shoo Shoo Nolita 27, Mott Street Bakery LLC 28 (never inspected), Saigon Vietnamese Sandwich 31,
El Gallo Taqueria 31, Quan Sushi 33, Acai Berry Foods 39, Happy Tuna / Momoya 40, Thai Diner 45,
Deux Luxe 52, Zutto 52, Mott Corner 60, Nolita Pizza 69, Kimika 73, Moonburger 73, Ceres 76, Grotta
Azzurra 81. Closed on the ledger nearby: **Wild Ginger Vegetarian Kitchen 40 m (found shut on Maps
2026-09-15)** and **Marcellino 73 m (2023-10-23)**.

**How full the street is** (supply against the Manhattan+Brooklyn baseline, this address):
**bar 16.10×, cafe_bakery 10.73×, hardware 6.32×, fitness 6.25×, restaurant 6.06×**, hair 5.47×.
Only two are thin: **childcare 0.48× and convenience 0.44×**. **This shop opens on one of the most
heavily served retail corners in New York, with a four-year-old specialty coffee shop 45 m away and
96 open cafés inside a five-minute walk.**

## 4. Our four guesses — one number each: coffee-counter sales in the twelve months to 2027-09-17, 177 Mott only, before sales tax, clothing excluded

| | Method | Low | **Our number** | High |
|---|---|---|---|---|
| **a** | **Loci model** | $800,000 | **$1,400,000** | $2,000,000 |
| **b** | **Judgment** | $350,000 | **$500,000** | $800,000 |
| **c** | **Bottom-up (orders × ticket)** | $300,000 | **$470,000** | $750,000 |
| **d** | **Cost side (what the bills need)** | $380,000 | **$530,000** (break-even) | $700,000 |

**(a) The Loci model — read the small print.** `analysis.address_category`, restaurant row, model
`revenue-v0.2`, supply `ed55301203a4`: p25 **$800,000**, p50 **$1,400,000**, p75 **$2,000,000**,
rent ceiling **$112,000/yr ($9,333/month)**. Two warnings. First, **coffee shops are not modelled** —
`cafe_bakery` revenue is empty here by design because that category failed its test, so the
restaurant number is the only one shipped. Second, and worse, **`capacity_bound` is TRUE on a lot
with no floor area**: PLUTO carries `retailarea` 0 on a condo, so all three figures are the spec's
**typical 2,000 sq ft restaurant** times $400, $700 and $1,000 per sq ft (`revenue.yaml`
`capacity.typical_sqft`). **That is not a demand estimate — it is a default footprint times a price
band, for a category this shop is not.** The same spec's café band on its 1,200 sq ft typical
footprint would read $600,000 / $1,020,000 / $1,440,000, and on our 800 sq ft counter **$400,000 /
$680,000 / $960,000** — quoted for scale only, it is not a shipped number.

**(b) Judgment — $500,000.** A coffee counter and beer bar of about 800 sq ft inside a new
multibrand menswear store, on the corner of Mott and Broome, in its first year, with no brand
following yet. $625/sq ft on the counter, $200 on the whole 2,500 sq ft unit. A café inside a shop
trades below a standalone café: it keeps the store's hours, it cannot own the 7–9 am commute, and
half its customers are there for the clothes. Strong NYC independents run $700–$1,200 per sq ft;
Stone Street, 45 m away and four years in, was guessed at $1,000,000 on 1,000 sq ft. This sits at
half that — lifted by 24,287 weekday subway entries, 16,081 jobs and Saturday tourist flow, held
back by 96 open cafés within a five-minute walk and a first year. **Judgment, not a query.**

**(c) Bottom-up — $470,000.** Assumptions, all judgment: **140 orders on a weekday** (90–220);
**average order $10.00 before tax** ($8.50–$12 — a $6.50–7.50 coffee for most of the day, a $9–10
beer in the evening, a pastry on a fifth of orders); **Saturday 1.00× a weekday, Sunday 0.76×**,
taken straight from the subway counts (24,199 Sat, 18,491 Sun against 24,287 weekday); open 7 days;
**52 weeks at 0.95** for holidays and quiet weeks. 946 orders a week × 52 × $10.00 × 0.95 =
**$467,300**. **The whole answer rests on the order count, which nobody has observed** — that is the
number to ask for.

**(d) Cost side — $530,000 is what the bills need.** See §5: below it the coffee counter is not
paying its own share of the rent, before the owner takes anything. Note that it sits **above (b) and
(c)** — we are saying in advance that **the counter alone does not carry its third of the corner; the
clothing does.** Whether the clothing does is a second line we cannot price; our prose guess is that
it sells two to four times what the counter does.

**Stated in advance:** **(a) is high by 3×** — a default restaurant footprint on a café; the truth
sits between **$300,000 and $750,000**. **Our one number for the operator page is $470,000.**
Below $300,000 the counter is a pure amenity and our order count was far too high; above $750,000
the store's brand pull works the way Café Leon Dore's does and the café-inside-a-shop discount in (b)
was wrong. **Survival call, stated in advance: Fazenda is still trading food at 177 Mott on
2027-09-17 — p = 0.75.** Base rates behind it, all live: the category-blind tenure prior within
400 m (18.6% of premises turn over in a year, `analysis.address.premises_turnover_400m`, 468
premises), the restaurant licence measure at this address (**35.6%** of 174 SLA licences within
400 m not renewed within five years, `nonrenewal_rate_5y_400m`, against the Manhattan restaurant
baseline of 35.0%, `analysis.licence_event_baseline`, median 734 days to the event — so failures are
front-loaded), and a first-year, first-location discount that is judgment. **There is no café base
rate: `cafe_bakery` is one of the eleven categories CONTEXT §3.1 drops before the survival fit, and
the shop holds no SLA licence, so this call is scored against the ledger (health record, `closed_on`,
Maps evidence), not against the gate, and counts for nothing under AC-3.**

## 5. Cost model — one number each

| Line | Low | **Our number** | High |
|---|---|---|---|
| **Rent per month** (the whole unit) | $22,000 | **$37,500** | $60,000 |
| **Staff cost per year** (counter only: wages + employer taxes + insurance) | $100,000 | **$140,000** | $190,000 |
| **Break-even sales per year** (counter only, before any owner pay) | $380,000 | **$530,000** | $700,000 |

**Rent.** $37,500/month = $450,000/year = **$180 per sq ft per year on 2,500 sq ft** — a corner
unit with three doors on Mott and Broome, let fresh in 2025–26 after an educational tenant, so this
is a current Nolita side-street rent, not a legacy Little Italy one. The counter's share, by floor,
is **$12,000/month ($144,000/yr on 800 sq ft)**. **No Mott St or Broome St asking rent exists in the
warehouse — the listings table holds flats, not shops — so the asking range is judgment.** The
model's own ceiling is $9,333/month, for a restaurant on a footprint it invented; at $37,500 the
whole unit needs about **$3.75M of combined sales** to hold rent at 12%, which is the plainest
statement of why the clothing, not the coffee, decides this lease. At counter sales of $470,000 the
counter's share is **30.6% of its sales**: far above the 10–12% a café can carry on its own.

**Staff.** About 84 open hours a week (12-hour day, 7 days) with one barista most of the day and two
at the busy hours and the beer evening, plus setup and close — roughly 110 paid hours a week at
about $21/hour blended, plus about 18.7% on top for employer taxes, workers' comp, overtime,
spread-of-hours and sick pay. **$140,000 = 30% of $470,000**, normal for a counter. Clothing staff
are excluded and will be shared with the counter in practice. *Whether the store's sales staff
cover the counter in quiet hours moves this by $30,000–$50,000 a year — the biggest single thing we
are guessing.*

**Break-even.** Cost of goods 32% of sales (beer is dearer to buy than coffee), card fees ~3.2%,
marketing and delivery ~1.5%, plus about 30% of the wage bill moving with sales → **45.6% variable,
54.4% left over**. Fixed: rent share $144,000 + other fixed (power, water, insurance, licences, till
software, repairs, waste, accountant, the counter's share of the rent tax) about $45,000 + the fixed
70% of wages $98,000 = **$287,000**. Break-even = $287,000 ÷ 0.544 = **$527,600**; with a $90,000
owner wage on top, **$693,000**. New York City's commercial rent tax **does** bite on this unit —
it starts at $250,000 of base rent a year and $450,000 is well past it: about 3.9% of rent, roughly
$17,500 a year on the unit, $5,600 of it on the counter's share, folded into other fixed above.

## 6. Five questions for the operator — asked on 2027-09-17, not before

In this order. The first four decide the score.

1. **In the first full year, what were the coffee counter's sales?** Roughly, or a range, is fine.
   Just the coffee and beer at 177 Mott, not the clothes. Before or after sales tax? Do delivery
   apps count at the full menu price or after their commission?
2. **What is the rent each month?** And how many square feet — the whole corner unit, and how much
   of it the counter gets?
3. **What did counter staff cost in a year?** How many baristas, and do the store's sales staff
   cover the counter in quiet hours?
4. **How many orders on a normal weekday, and what is the average order?** Best guesses are fine.
   How much of the ticket is beer?
5. **Shop-specific: what share of the shop's money is coffee and beer, and what share is
   clothing?** And is Saturday as busy as a weekday? The subway counts say Saturday matches a
   weekday here and Saturday evening beats a weekday evening — unusual for our other shops. Are the
   customers residents, office workers, visitors, and do they come for the clothes or the coffee?

## 7. Owner evidence log — blank on purpose; nothing goes here until 2027-09-17

| Field | Answer | Date heard |
|---|---|---|
| First-year counter sales (177 Mott only); before or after sales tax; delivery gross or net | | |
| Rent per month; square feet leased; counter's share of the floor | Rent: **$15,000/month, exactly**, for the whole unit — vs guessed $37,500: **MISS** (outside the $22,000–$60,000 range). Square feet: **under 1,000 sq ft** (owner's words, no exact figure given) — vs guessed 2,500 sq ft: **MISS**. Counter's share of the floor: not answered. Source: owner, from the operator, verbally. | 2026-09-17 |
| Counter staff cost per year; headcount; store staff covering the counter? | | |
| Weekday orders; average order; beer share of the ticket | | |
| Coffee-and-beer share vs clothing share; weekend share of the week; customer mix | | |
| Still trading food at 177 Mott on 2027-09-17 (health record, ledger `closed_on`, Maps) | | |
| Anything that contradicts §1–§3 | | |

**Scoring rule.** For each of the four guesses: **error = ln(our number ÷ the true number)**, smallest
wins, plus **hit or miss** on whether the truth falls inside our low–high range. Rent, staff cost and
break-even are scored the same way, one at a time. **The survival call is scored hit or miss on
2027-09-17 against the health record, the ledger's `closed_on` and Maps evidence; a permit re-issued
to a different name at 177 Mott counts as a miss.**

## 8. What this record is, and is not — read this before quoting any number

- **This is a forward test of the model against a real business, not a recommendation.** Nobody is
  being told to open anything at 177 Mott; someone already has.
- **Loci finds no gap here.** All fifteen categories are present within reach (`n_missing` = 0); only
  convenience (0.44×) and childcare (0.48×) are thin, everything else runs 1.5× to 16.1× the city
  baseline. A bank is the "lead" by arithmetic only — seven already sit inside 400 m, the nearest
  248 m away, and Loci's own rule says supply counts are not evidence either way for that category at
  this density. **This is one of the most completely served addresses in the city.**
- **The model number is a default footprint times a price band, not a forecast** (`capacity_bound`
  TRUE on a zero-retailarea condo lot — §4a), for a category this shop is not, and **Loci cannot see
  what decides a coffee counter inside a clothing store**: the clothes, seats, hours, prices, the
  beer licence it does not yet hold, the brand.
- **The shop is about two months old and single-source.** Loci's ledger has it only as a health
  permit first seen 2026-09, left-censored; Overture and Foursquare do not carry it yet. That is the
  one finding about the ledger this page records, and it is stated once.
- **One shop cannot prove a model right; it can only embarrass it** — a miss we predicted in advance
  is worth more than a hit.
- **The old finding still stands:** gaps do not predict growth (β = +0.069, wrong sign; parallel
  trends broken). Nothing here is a claim about property values or future appreciation.
- **Read-only.** `data/loci.duckdb` opened `read_only=True`, supply set `ed55301203a4`, as-of pin
  2026-09-16. No closure check was run, no `poi_status` changed, no code, table, CHECKPOINT or
  ticket was changed. Straight-line distances in §3 use `ST_FlipCoordinates` (D16) from the
  health-department point. The street address came from the health department's open-data row for
  CAMIS 50191163 (the warehouse row carries no address text); the concept and opening season came
  from the web. Scratchpad scripts:
  `…/0bf374dc-c609-4d57-be67-60e58ed35f76/scratchpad/fazenda/probe1–6.py`.
