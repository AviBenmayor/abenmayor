# Pre-registered guesses — Stone Street Coffee, 379 Broome St, New York NY 10013

**Written:** 2026-09-15, **before** any figure was heard from the shop's former manager. Every number
below is frozen; a correction goes in a new dated file, never in this one. **Purpose:** test Loci's
numbers against one real coffee shop that is open and trading today. Same shape as
`predictions/lions-milk-2026-09-13.md` (café) and `graham-ave-376-2026-09-13.md` (El Punto).
**Replaces the framing of** `docs/recommendations/379-broome-st-2026-09-14.md`, which treated this
address as an empty site to screen. It is not empty — a coffee shop has traded here since 2022.

## 1. The shop

| | |
|---|---|
| Name | **Stone Street Coffee Soho** (health department) / *Stone Street Coffee Company* (Foursquare) / *Stone Street Café* (Overture) — three names, one shop |
| Address | 379 Broome St, NY 10013 — Broome between Mulberry and Mott. Loci `address_id` **1004710039**, area **MN0201** SoHo–Little Italy–Hudson Square |
| Type | Coffee/Tea (health department cuisine code). Counter service. Loci category `cafe_bakery` |
| Health record | CAMIS **50093481**, last inspected **2026-06-12 (88 days ago)**, not closed at that visit, **33 inspection rows**. Grade letter is **"Z" = grade pending**, dated 2026-06-12 |
| First seen trading | **2022-10-16** (Foursquare) — about **3.9 years** here. But the first health inspection is **2024-07-16**, so the permit was probably re-issued along the way |
| Seats, hours, price tier, star rating | **None of it is in the warehouse.** The health record holds no seat count; Overture gives only `primary_category: cafe`, Foursquare only the label "Coffee Shop" |
| Same brand elsewhere | Loci sees **five** Stone Street Coffee locations (Bushwick, two downtown, one in the west 20s, plus this one). **Any money number must be for 379 Broome only** |
| The building (PLUTO) | BBL 1004710039, class **S2 = homes with two stores**, retail floor **2,013 sq ft** for the whole lot, 2 floors, 2 flats, lot 2,970 sq ft, 25.25 ft frontage, built 1878, altered 2014 |
| Storefront register | **No filing at all at this lot** — so it cannot tell us how the 2,013 sq ft splits |
| Zoning | **C6-2G**, commercial. Special Little Italy District. No landmark, no historic district. Legal for a shop |

**The most important line in that table.** The building holds **two** stores and a second business
(*Greecologies*) sits 1 metre away, so the 2,013 sq ft is almost certainly **two shops** and Stone
Street's own floor is probably **about 1,000 sq ft**. Per-square-foot numbers below are given on
1,000 sq ft, with the 2,013 figure shown too. **Confirming the real square footage is the cheapest
useful thing the manager can tell us.**

## 2. The block

| | |
|---|---|
| Homes within a 5-minute walk (400 m) | **6,077** (18,944 homes per km²) |
| Jobs within 400 m | **19,426** — 8,774 shop, 4,943 office, 5,709 other. **3.2 jobs for every home** |
| Subway entries within 400 m | **12,919 weekday**, **14,076 Saturday** (1.09×), 11,068 Sunday. Busiest weekday stretch is late afternoon (4,891); Saturday late afternoon is busier still (5,376) |
| Loci street type | **`retail_mixed`**, retail index **1.00**, intensity **1.00** — the top of the scale |
| Pedestrian counts | **None on this street.** The nearest city counter is 600 m away in Chinatown; a camera 166 m away counts nothing |
| Storefronts within 400 m | **588**, of which **59 empty (10.0%)**. Nearest empty one **16 m** away |
| New homes being built within 400 m | 53 permitted, but only **9 active and 42 stalled**; 66 finished in the last two years |

Read plainly: **this is a workplace-and-visitor street, not a bedroom street** — three jobs per home
and Saturday busier than a weekday. The opposite of the Graham Ave case.

## 3. Who else sells coffee and food nearby (400 m)

Loci's counted supply at this address, supply set `467cd5969200`: **cafe_bakery 94**,
**restaurant 202**, **bar 55**, **convenience 2**. The same ring by trading status: **cafés — 84
open, 26 unknown**; **restaurants — 151 open, 86 unknown, 2 closed**.

Nearest coffee and bakery competitors: **Caffe Roma 40 m**, Milkweed Studio 57, Figo Il Gelato 59,
Coffee For Sasquatch 60, Goat Bakeshop 67, Urban Backyard 67, Chiu Hong Bakery 68, The Chai Spot 78,
Leon's Bagels 85, Ferrara's 111, Kolkata Chai 115. Chains in the ring: **Maman 181, Toby's Estate
188, Blank Street 260, Joe & The Juice 274, Luckin Coffee 168, two Starbucks (285, 311), Paris
Baguette 318.** Nearest restaurants: Wild Ginger 30, Happy Tuna / Momoya 30, Zutto 32, Deux Luxe 32,
Quan Sushi 34, Benito One 42, Grotta Azzurra 45, Lunella 46, L'Amore 49, Ceres 59, La Mela 61, Da
Nico 66. One closed on the ledger nearby: **Marcellino, 59 m**.

**How full the street is** (supply against the Manhattan+Brooklyn baseline, this address):
**bar 17.34×, cafe_bakery 10.88×, fitness 7.64×, restaurant 6.53×**, hardware 5.85×, hair 5.63×.
Only two are thin: **childcare 0.64× and convenience 0.31×**. *(The brief quoted 10.92× / 14.31× /
6.99× — that was the run before the duplicate clean-up; above is the current table.)*
**This shop trades on one of the most heavily served retail streets in New York.**

## 4. Our four guesses — one number each: yearly sales for 379 Broome only, before sales tax

| | Method | Low | **Our number** | High |
|---|---|---|---|---|
| **a** | **Loci model** | $805,200 | **$1,409,100** | $2,013,000 |
| **b** | **Judgment** | $700,000 | **$1,000,000** | $1,450,000 |
| **c** | **Bottom-up (orders × ticket)** | $750,000 | **$1,160,000** | $1,650,000 |
| **d** | **Cost side (what the bills need)** | $700,000 | **$800,000** (break-even) | $950,000 |

**(a) The Loci model — read the small print.** `analysis.address_category`, restaurant row, model
`revenue-v0.2`: p25 **$805,200**, p50 **$1,409,100**, p75 **$2,013,000**, rent ceiling **$112,728/yr
($9,394/month)**. Two warnings. First, **coffee shops are not modelled** — `cafe_bakery` revenue is
empty here by design because that category failed its test, so the restaurant number is a floor.
Second, and worse, **`capacity_bound` is TRUE**: all three figures are just 2,013 sq ft of retail
floor times $400, $700 and $1,000 per sq ft. **That is not a demand estimate — it is floor area
times a price band, and the floor area includes the shop next door.** On a realistic 1,000 sq ft
demise the same rule gives **$400,000 / $700,000 / $1,000,000**.

**(b) Judgment — $1,000,000.** A counter-serve specialty coffee shop of about 1,000 sq ft on Broome
between Mulberry and Mott, four years trading, one of five branches of a small local roaster.
$1,000/sq ft on 1,000 sq ft, $497 on 2,013. Strong NYC independents run roughly $700–$1,200 per
sq ft, so this sits near the top — lifted by 19,426 jobs, 12,919 weekday subway entries and tourist
flow, held back by 84 open cafés within a 5-minute walk. **Judgment, not a query.**

**(c) Bottom-up — $1,160,000.** Assumptions, all judgment: **280 orders on a weekday** (200–380);
**average order $12.00 before tax** ($10–$14 — a $6.50–7.50 coffee plus a pastry or sandwich on
about half of orders); **Saturday 1.10× a weekday, Sunday 0.90×**, taken straight from the subway
counts (14,076 Sat, 11,068 Sun against 12,919 weekday); open 7 days; **52 weeks at 0.95** for
holidays and quiet weeks. 1,960 orders a week × 52 × $12.00 × 0.95 = **$1,161,888**. **The whole
answer rests on the order count, which we have never observed** — that is the number to ask for.

**(d) Cost side — $800,000 is what the bills need.** See §5: below it the shop is not paying its own
way, before the owner takes anything.

**Stated in advance:** **(a) is high**; the truth sits between **$800,000 and $1,300,000**. Above
$1.4M, our order count was far too low and the model was right by accident.

## 5. Cost model — one number each

| Line | Low | **Our number** | High |
|---|---|---|---|
| **Rent per month** | $7,500 | **$10,500** | $15,000 |
| **Staff cost per year** (wages + employer taxes + insurance) | $280,000 | **$340,000** | $410,000 |
| **Break-even sales per year** (before any owner pay) | $700,000 | **$800,000** | $950,000 |

**Rent.** $10,500/month = $126,000/year = **$126 per sq ft per year on a 1,000 sq ft shop** ($63 on
2,013). The earlier report's supportable rents on this lot were $55/sq ft (restaurant) and $90/sq ft
(café) **on 2,013 sq ft** — which is $112 and $182 per sq ft on a 1,000 sq ft demise; our number
sits between them. **No Broome St asking rent exists in the warehouse — the listings table holds
flats, not shops — so the asking range is judgment.** The model's own ceiling is $9,394/month. At
sales of $1,160,000, $10,500/month is **10.9% of sales**: inside the 10–12% a café can carry, with
nothing to spare.

**Staff.** About 265 paid hours a week (12-hour day, 7 days, two to three people at the busy hours) at
roughly $21/hour blended, plus about 18.7% on top for employer taxes, workers' comp, overtime,
spread-of-hours and sick pay. **$340,000 = 29% of $1,160,000**, normal for a café. *Whether tips are
paid on top of full wages or counted against them moves this by $50,000–$70,000 a year — the biggest
single thing we are guessing.*

**Break-even.** Cost of goods 30% of sales, card fees ~3.2%, marketing and delivery ~1.8%, plus
about 30% of the wage bill moving with sales → **43.7% variable, 56.3% left over**. Fixed: rent
$126,000 + other fixed (power, water, insurance, licences, till software, repairs, waste, accountant)
about $85,000 + the fixed 70% of wages $238,000 = **$449,000**. Break-even = $449,000 ÷ 0.563 =
**$797,500**; with a $90,000 owner wage on top, **$957,300**. New York City's commercial rent tax
does **not** bite here — it starts at $250,000 of base rent a year.

## 6. Five questions for the former manager

In this order. The first four decide the score.

1. **In a normal full year, what were the shop's sales?** Roughly, or a range, is fine. Just
   379 Broome, not the other branches. Before or after sales tax? Do delivery apps count at the
   full menu price or after their commission?
2. **What was the rent each month?** And how many square feet — the whole ground floor, or half of
   it with the neighbour taking the rest?
3. **What did staff cost in a year?** How many people, and are tips paid **on top of** wages or
   counted as part of them?
4. **How many orders on a normal weekday, and what was the average order?** Best guesses are fine.
5. **Shop-specific: was Saturday busier than a weekday?** The subway counts say Saturday is 9%
   busier here — unusual; most of our other shops are quieter at weekends. What share of the week's
   money came in on Saturday and Sunday, and were the customers residents, office workers, visitors?

## 7. Owner evidence log — blank on purpose; nothing goes here until the manager answers

| Field | Answer | Date heard |
|---|---|---|
| Yearly sales (379 Broome only); before or after sales tax; delivery gross or net | **≈$1,400,000/year**, 107,000 transactions, ~$13.08 average sale ("we're big on food"). Delivery ≈5% of sales for the year (operator unsure — "maybe"); a recent single week ran 2,300 sales at $12.90 average ($29,670), delivery under 3%. Before/after sales tax and gross-vs-net-of-delivery-commission not specified. vs guessed $1,409,100 (a) / $1,000,000 (b) / $1,160,000 (c): **all three HIT** their low–high ranges; **(a) wins** by ln-error — see the 2026-09-21 answer file for why that is not a validation of the model. Source: the shop's former manager, via text, relayed by the owner. | 2026-09-21 |
| Rent per month; square feet leased | Exact rent not given; operator says the $10,500/month guess was **"a little low"** — "almost nobody in Nolita has rent under 10k unless they're on a very old lease," implying actual sits above $10,500, likely still under the $15,000 high end (**directional HIT** on range, point guess low). Square footage: **the whole ground floor (2,013 sq ft) plus a basement of equal size** — not the ~1,000 sq ft (half the lot, split with the neighbor) assumed. **MISS** on floor area — see the answer file. | 2026-09-21 |
| Staff cost per year; headcount; tips on top of wages? | Operator says the $340,000 guess was **"close"** — **HIT** on the dollar figure. Headcount: 2 baristas on the floor, 3 in the kitchen, 1 porter (6 total) — more kitchen-heavy than the record's "two to three people at the busy hours" assumption, consistent with the operator's framing that food is "a big draw," more than a coffee shop that happens to serve it. Tips-on-top-of-wages not answered. | 2026-09-21 |
| Weekday orders; average order | Not asked in these terms; back-calculated from the sales answer: ≈107,000 orders/year ÷ 52 ≈ 2,058/week vs the record's 1,960/week bottom-up assumption — about 5% higher, **HIT**, order count only modestly low as the record's stated-in-advance caveat anticipated. Average order ≈$13.08 (most recent week $12.90) vs guessed $12.00 — **HIT**, slightly higher, consistent with "big on food." | 2026-09-21 |
| Weekend share of the week; customer mix (residents / workers / visitors) | "Saturday and Sunday dominate the sales" — confirms the record's Q5 call (Saturday busier than a weekday, unusual for our other shops), directionally. **HIT.** No share number given; resident/worker/visitor mix not answered. | 2026-09-21 |
| Anything that contradicts §1–§3 | §1's implicit assumption (floor shared with Greecologies next door, ~1,000 sq ft) is contradicted — see the rent/floor row above. §1's framing is sharpened: the operator describes the shop as kitchen-forward, with food "a big draw," more than a coffee shop that happens to sell food — a distinction §1 and §4 did not make. | 2026-09-21 |

**Scoring rule.** For each of the four guesses: **error = ln(our number ÷ the true number)**, smallest
wins, plus **hit or miss** on whether the truth falls inside our low–high range. Rent, staff cost and
break-even are scored the same way, one at a time.

## 8. What this record is, and is not — read this before quoting any number

- **This is a test of the model against a real business, not a recommendation.** Nobody is being
  told to open anything at 379 Broome.
- **Loci finds no gap here.** All fifteen categories are present within reach (`n_missing` = 0); only
  convenience (0.31×) and childcare (0.64×) are thin, everything else runs 1.8× to 17.3× the city
  baseline. A bodega is the "lead" by arithmetic only — two already sit inside 400 m, the nearest
  174 m away, and Loci's own rule says supply counts are not evidence either way for that category at
  this density. **This is one of the most completely served addresses in the city.**
- **The model number is a ceiling, not a forecast** (`capacity_bound` TRUE — §4a), and **Loci cannot
  see what decides a coffee shop**: seats, hours, prices, rating, staff, the coffee itself.
- **One shop cannot prove a model right; it can only embarrass it** — a miss we predicted in advance
  is worth more than a hit.
- **The old finding still stands:** gaps do not predict growth (β = +0.069, wrong sign; parallel
  trends broken). Nothing here is a claim about property values or future appreciation.
- **Read-only.** `data/loci.duckdb` opened `read_only=True`, supply set `467cd5969200`. No code,
  table, CHECKPOINT or ticket was changed.
