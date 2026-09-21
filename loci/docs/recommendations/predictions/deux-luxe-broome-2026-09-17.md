# Pre-registered guesses — Deux Luxe, 384 Broome St, New York NY 10013

**Written:** 2026-09-17, **before** any figure was heard from the shop. Every number below is frozen;
a correction goes in a new dated file, never in this one. **Purpose:** test Loci's numbers against one
real burger restaurant that is open and trading today. Same shape as
`predictions/stone-street-coffee-379-broome-2026-09-15.md` (café, across the street),
`predictions/lions-milk-2026-09-13.md` (café) and `graham-ave-376-2026-09-13.md` (El Punto).
**Spelling:** the owner wrote "Deux Leux"; the health department, Overture and Foursquare all carry
**Deux Luxe**, and that is the name used here. **Reader:** written for the shop's current operator
(we do not yet know who the owner will talk to); if it turns out to be a former manager, drop the
"you/your" framing and the pay-yourself line, nothing else changes.
**Warehouse values are live** — `data/loci.duckdb` read on 2026-09-17, supply set `ed55301203a4`,
as-of pin 2026-09-16, forecast vintage untouched. No fallback to older files was needed.

## 1. The shop

| | |
|---|---|
| Name | **Deux Luxe** — one name in all three sources (health department, Overture, Foursquare). Cluster 34285, three sources, health-department row canonical |
| Address | 384 Broome St, NY 10013 — Broome between Mulberry and Mott, **south side**, 32 m across the street from the 379 Broome record. Loci `address_id` **1004800041**, area **MN0201** SoHo–Little Italy–Hudson Square |
| Type | American (health department cuisine code); `burger_restaurant` (Overture); "Burger Joint" (Foursquare). Counter-serve wagyu burgers, fries, combos. Loci category `restaurant` |
| Health record | CAMIS **50169020**, first **and only** inspection **2025-05-13 (492 days ago)**, not closed at that visit, 6 inspection rows all from that one date. **No grade on file** — sixteen months open and never graded |
| Liquor | **No licence** in the SLA active or pending files, under this name or at 384 Broome. Zutto holds the Restaurant Wine licence at this address; the last beer licence at "384 Broome St Store 1" was Sal's Family Pizza, 2019–2021, expired. **The brief said restaurant/bar — Loci reads a restaurant with no bar** |
| First seen trading | **2025-05-13** (health department first inspection, `gov_filing`) / Foursquare `opened_on` **2025-05-15** — about **16 months** here |
| Seats, hours, price tier, star rating | **None of it is in the warehouse.** Public listings (web, 2026-09-17, not Loci): open 11:30–22:00 Sun–Wed, to 23:00 Thu, to midnight Fri–Sat ≈ **78.5 h/week**; Grubhub "$$$", combos about $20; Time Out "best burger in NY 2025"; 15.5k Instagram followers; delivery on at least one platform |
| Same brand elsewhere | Loci sees **no other** Deux Luxe. The burger comes from *Café Deux* in Westchester, outside Loci's map. **Any money number must be for 384 Broome only** |
| The building (PLUTO 26v2) | BBL 1004800041, class **C7 = walk-up flats with stores**, retail floor **4,685 sq ft for the whole lot**, 6 floors, 40 flats, 2 buildings, lot 6,529 sq ft, 78.33 ft frontage, built 1900, altered 1964, owner BCD BROOME LLC |
| Storefront register | **Four storefronts filed at this lot** (380 and 384 Broome), all "FOOD SERVICES" every year since 2019. On **2024-12-31 one of them (#1, 384 Broome) was VACANT — "NO BUSINESS ACTIVITY IDENTIFIED"** — the space Deux Luxe opened in five months later. The other three leases run to 2031-08, 2031-11 and 2032-09 (2023 filing). Deux Luxe's own lease is not yet in the register. One new DOB fit-out filing at the lot, 2026-08-04, unit unknown |
| Zoning | **C6-2G** (lot split with C6-1), commercial. Special Little Italy District. No landmark, no historic district. Legal for a shop |

**The most important line in that table.** The lot holds **four** food storefronts, so the model
divides its 4,685 sq ft by four and prices Deux Luxe on **1,171 sq ft** — a better guess than the
Stone Street case, where the register was empty, but the four demises are not equal (78 ft of
frontage across two buildings) and a burger counter can run on 800. Per-square-foot numbers below
are given on 1,171 sq ft. **Confirming the real square footage is the cheapest useful thing the
operator can tell us.**

## 2. The block

| | |
|---|---|
| Homes within a 5-minute walk (400 m) | **5,956** (19,289 homes per km²); 18,879 within 800 m |
| Jobs within 400 m | **18,202** — 8,338 shop, 4,441 office, 5,423 other. **3.1 jobs for every home** |
| Subway entries within 400 m | **12,253 weekday**, **14,085 Saturday** (1.15×), 10,289 Sunday. Busiest weekday stretch is late afternoon (4,663); Saturday late afternoon is busier still (5,602), and Saturday evening (3,726) beats a weekday evening (3,208). *Window 2025-01-01..2026-08-31 — longer than the Jun–Aug window the Stone Street page used, so the two pages' entry counts differ by design* |
| Loci street type | **`retail_mixed`**, retail index **1.00**, intensity **1.00** — the top of the scale |
| Pedestrian counts | **None on this street.** The nearest city counter is 626 m away (2026-05: AM 1,217 / midday 3,547 / PM 4,315); a camera 125 m away at Kenmare & Cleveland counts nothing |
| Storefronts within 400 m | **576**, of which **57 empty (9.9%)** at 2024-12-31. Nearest empty one is **this lot's own #1** — the space the shop now fills. 470 premises with a tenure record: **18.5% turn over in a year, median tenant stays 2.0 years** |
| New homes being built within 400 m | 53 permitted, but only **9 active and 42 stalled**; 56 finished in the last two years |
| Fit-outs and licences within 400 m | 241 storefront fit-out filings in the last 12 months; 15 liquor applications |

Read plainly: **this is a workplace-and-visitor street, not a bedroom street** — three jobs per home,
Saturday busier than a weekday, and one shop in five changes hands each year. Same read as the coffee
shop across the road.

## 3. Who else sells burgers and food nearby (400 m)

Loci's counted supply at this address, supply set `ed55301203a4`: **restaurant 183**, **bar 55**,
**cafe_bakery 95**, convenience 2. The same 400 m disc by trading status (distinct locations):
**restaurants — 156 open, 100 unknown, 4 closed**; **bars — 51 open, 25 unknown**; cafés — 97 open,
25 unknown, 1 closed.

**Burger places within 400 m, thirteen by name:** Moonburger **42 m** (health grade A, 2026-03),
Khondoker Luncheonette 46, Cantiere Hambirreria 89, NADC Burger 138, Neat Burger 151, Genuine
Superette 174, "218" 198, Dog Haus 203, Casa 13Urger 241, 7th Street Burger 289, Burger By Day 292,
Bronson's Burgers 294, Kwan's Burger & Pizza 396. Four of those are chains. Nearest restaurants and
bars: on the **same lot** Zutto 23, Happy Tuna / Momoya 28; then Caffe Roma 25, Acai Berry Foods 32,
Unagi 34, Quan Sushi 37, The Wooly 38, Saito 41, Broome St. Project 43, Gem Home 48, Grotta Azzurra
48, Fazenda 48, Shoo Shoo Nolita 50, Niukee Shumai 52, Nolita Pizza 54, Benito One 55, Thai Diner
61, Lunella 65, Pasquale Jones 70, Saigon Vietnamese Sandwich 70, El Gallo Taqueria 70, L'Amore 74,
La Mela 92, Ceres 98, Sweetgreen 102, Carrot Express 102, Kimika 110. Closed on the ledger nearby:
**Marcellino 27 m (2023-10-23)** and **Wild Ginger Vegetarian Kitchen 28 m — on this same lot,
found shut on Maps 2026-09-15**.

**How full the street is** (supply against the Manhattan+Brooklyn baseline, this address):
**bar 17.69×, cafe_bakery 11.22×, fitness 7.16×, hardware 6.39×, restaurant 6.04×**, hair 5.50×.
Only two are thin: **childcare 0.52× and convenience 0.32×**. **This shop trades on one of the most
heavily served retail streets in New York, with thirteen other burger counters inside a five-minute
walk.**

## 4. Our four guesses — one number each: yearly sales for 384 Broome only, before sales tax

| | Method | Low | **Our number** | High |
|---|---|---|---|---|
| **a** | **Loci model** | $468,500 | **$819,875** | $1,171,250 |
| **b** | **Judgment** | $1,000,000 | **$1,500,000** | $2,100,000 |
| **c** | **Bottom-up (orders × ticket)** | $970,000 | **$1,510,000** | $2,240,000 |
| **d** | **Cost side (what the bills need)** | $840,000 | **$1,110,000** (break-even) | $1,480,000 |

**(a) The Loci model — read the small print.** `analysis.address_category`, restaurant row, model
`revenue-v0.2`, supply `ed55301203a4`: p25 **$468,500**, p50 **$819,875**, p75 **$1,171,250**,
rent ceiling **$65,590/yr ($5,466/month)**. **`capacity_bound` is TRUE**: all three figures are just
1,171 sq ft (4,685 ÷ 4 registered storefronts) times $400, $700 and $1,000 per sq ft. **That is not
a demand estimate — it is floor area times a price band.** The band was set for a typical NYC
restaurant; a queue-out-the-door burger counter runs far above $1,000/sq ft, so this time the cap
is a floor, not a ceiling. Restaurant is the only category the model ships; the number is for that
category, not for burgers specifically.

**(b) Judgment — $1,500,000.** A counter-serve wagyu burger shop of about 1,171 sq ft on Broome
between Mulberry and Mott, sixteen months open, 78 hours a week, a "best burger" award and a
delivery menu. $1,281/sq ft. Strong NYC independent burger counters run $1,000–$2,000 per sq ft
(7th Street Burger's small boxes reportedly higher), so this sits in the lower half — lifted by
18,202 jobs, 12,253 weekday subway entries and tourist flow, held back by thirteen burger
competitors and 156 open restaurants within a five-minute walk. **Judgment, not a query.**

**(c) Bottom-up — $1,510,000.** Assumptions, all judgment: **190 orders on a weekday** (140–250);
**average order $23.00 before tax** ($20–$26 — a $20 combo, a burger and fries alone below it,
pairs and delivery orders above it); **Saturday 1.15× a weekday, Sunday 0.84×**, taken straight
from the subway counts (14,085 Sat, 10,289 Sun against 12,253 weekday); open 7 days; **52 weeks at
0.95** for holidays and quiet weeks. 1,328 orders a week × 52 × $23.00 × 0.95 = **$1,508,987**.
**The whole answer rests on the order count, which we have never observed** — that is the number to
ask for.

**(d) Cost side — $1,110,000 is what the bills need.** See §5: below it the shop is not paying its
own way, before the owner takes anything. Note that it sits **above the model's p75** — if the
model were right, this shop would be losing money, and it is posting new menu items, not closing.

**Stated in advance:** **(a) is low** — the opposite of the Stone Street case across the road; the
truth sits between **$1,200,000 and $1,900,000**. **Our one number for the operator page is
$1,500,000.** Below $1.0M our order count was far too high and the model's floor was right by
accident; above $2.1M the burger counter is out-trading its floor by more than 2× and the capacity
band needs a fast-casual re-cut.

## 5. Cost model — one number each

| Line | Low | **Our number** | High |
|---|---|---|---|
| **Rent per month** | $10,000 | **$14,000** | $19,000 |
| **Staff cost per year** (wages + employer taxes + insurance) | $380,000 | **$450,000** | $540,000 |
| **Break-even sales per year** (before any owner pay) | $840,000 | **$1,110,000** | $1,480,000 |

**Rent.** $14,000/month = $168,000/year = **$143 per sq ft per year on 1,171 sq ft**. The register
says the space was empty at the end of 2024 and let in early 2025, so this is a fresh lease at
today's Nolita side-street level, not a legacy Little Italy rent. **No Broome St asking rent exists in
the warehouse — the listings table holds flats, not shops — so the asking range is judgment.** The
model's own ceiling is $5,466/month — **less than half of any plausible rent here**, which is D91's
known floor in dollars. At sales of $1,510,000, $14,000/month is **11.1% of sales**: above the 6–10%
a burger counter wants, so rent is the line most likely to be squeezing this shop.

**Staff.** About 89 staffed hours a week (78.5 open plus prep and close) with about four people on
at once — a two- or three-person line plus counter — is roughly 356 paid hours at about $21/hour
blended, plus about 18.7% on top for employer taxes, workers' comp, overtime, spread-of-hours and
sick pay. **$450,000 = 30% of $1,510,000**, normal for fast-casual. *Whether the late Friday and
Saturday hours (to midnight) are staffed at the same level as lunch moves this by $40,000–$60,000 a
year — the biggest single thing we are guessing.*

**Break-even.** Cost of goods 32% of sales (wagyu is dearer than a standard patty), card fees ~3.0%,
delivery commissions and marketing ~4.0%, plus about 30% of the wage bill moving with sales →
**47.9% variable, 52.1% left over**. Fixed: rent $168,000 + other fixed (power, gas, water,
insurance, licences, till software, repairs, waste, accountant) about $95,000 + the fixed 70% of
wages $315,000 = **$578,000**. Break-even = $578,000 ÷ 0.521 = **$1,110,300**; with a $90,000 owner
wage on top, **$1,283,100**. New York City's commercial rent tax does **not** bite here — Manhattan
south of 96th, but it starts at $250,000 of base rent a year.

## 6. Five questions for the operator

In this order. The first four decide the score.

1. **In a normal full year, what are the shop's sales?** Roughly, or a range, is fine. Just 384
   Broome, not Café Deux. Before or after sales tax? Do delivery apps count at the full menu price
   or after their commission, and what share of sales is delivery?
2. **What is the rent each month?** And how many square feet — the register shows four food
   storefronts on this lot; is yours a quarter of the 4,685, or smaller?
3. **What does staff cost in a year?** How many people, and how many are on at once at lunch versus
   at 11 pm on a Saturday?
4. **How many orders on a normal weekday, and what is the average order?** Best guesses are fine.
5. **Shop-specific: is Saturday busier than a weekday?** The subway counts say Saturday is 15% busier
   here and Saturday evening beats a weekday evening — unusual for our other shops. What share of
   the week's money comes in Friday to Sunday, and are the customers residents, office workers,
   visitors? And: has the health department been back since May 2025? The record shows one visit
   and no grade.

## 7. Owner evidence log — blank on purpose; nothing goes here until the operator answers

| Field | Answer | Date heard |
|---|---|---|
| Yearly sales (384 Broome only); before or after sales tax; delivery gross or net, delivery share | | |
| Rent per month; square feet leased | | |
| Staff cost per year; headcount; staffing at lunch vs late Saturday | | |
| Weekday orders; average order | | |
| Weekend share of the week; customer mix (residents / workers / visitors); inspection since May 2025 | | |
| Anything that contradicts §1–§3 | | |

**Scoring rule.** For each of the four guesses: **error = ln(our number ÷ the true number)**, smallest
wins, plus **hit or miss** on whether the truth falls inside our low–high range. Rent, staff cost and
break-even are scored the same way, one at a time.

## 8. What this record is, and is not — read this before quoting any number

- **This is a test of the model against a real business, not a recommendation.** Nobody is being
  told to open anything at 384 Broome.
- **Loci finds no gap here.** All fifteen categories are present within reach (`n_missing` = 0); only
  convenience (0.32×) and childcare (0.52×) are thin, everything else runs 1.9× to 17.7× the city
  baseline. A bodega is the "lead" by arithmetic only — two already sit inside 400 m, the nearest
  213 m away, and Loci's own rule says supply counts are not evidence either way for that category at
  this density. **This is one of the most completely served addresses in the city.**
- **The model number is a floor-area band, not a forecast** (`capacity_bound` TRUE — §4a), and
  **Loci cannot see what decides a burger counter**: seats, hours, prices, the queue, the award, the
  delivery mix, the meat.
- **The shop is 16 months old.** Loci's survival label (CONTEXT §3.1) is not yet fitted; nothing here
  says whether it will still be trading in 2027. The lot it sits on lost Wild Ginger and the block
  turns over 18.5% of premises a year.
- **One shop cannot prove a model right; it can only embarrass it** — a miss we predicted in advance
  is worth more than a hit.
- **The old finding still stands:** gaps do not predict growth (β = +0.069, wrong sign; parallel
  trends broken). Nothing here is a claim about property values or future appreciation.
- **Read-only.** `data/loci.duckdb` opened `read_only=True`, supply set `ed55301203a4`, as-of pin
  2026-09-16. No closure check was run, no `poi_status` changed, no code, table, CHECKPOINT or
  ticket was changed. Straight-line distances in §3 use `ST_FlipCoordinates` (D16). Scratchpad
  scripts: `…/0bf374dc-c609-4d57-be67-60e58ed35f76/scratchpad/deux/probe1–6.py`.
