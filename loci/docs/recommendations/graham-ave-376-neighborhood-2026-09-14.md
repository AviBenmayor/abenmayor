# 376 Graham Ave — neighborhood, cuisine demand, dayparts and menu

**Written 2026-09-14.** Companion to `docs/recommendations/graham-ave-376-2026-09-13.md`.
**Nothing in that file is changed by this one** — the pre-registered revenue numbers, levers and
caveats there stand as written. This file answers a different question: *who lives here, do they
want Cuban food, when are they outside, and what should the menu be.*

Warehouse read-only at `data/loci.duckdb`, `frame='lot'`. ACS 2023 5-year pulled **fresh from the
Census API** (the warehouse holds only a 42-column subset). Scripts in the session scratchpad; no
warehouse table, YAML or ticket was modified, nothing committed.

**Method.** Every PLUTO lot within **400 m** / **800 m** straight-line, grouped to its 2020 tract
(`bct2020`), each tract's ACS profile weighted by its **residential units inside the ring**. The
400 m ring draws on 21 tracts; 049700 — the lot's own tract — carries only **11.9%** of the weight.
That is why these differ from the earlier memo's single-tract figures: *the walk shed is not the
tract.* Sensitivity in §5.

---

## 1. Who lives within a 5- and 10-minute walk

Shares are unit-weighted tract averages with propagated MOEs (ACS ratio formula). Counts are shares
applied to the pinned `homes_400m` = **4,003** and `homes_800m` = **14,999**.

| | **Graham 400 m** | **Graham 800 m** | Roebling 400 m | Brooklyn |
|---|---|---|---|---|
| **Age** | | | | |
| under 18 | **16.2% ± 2.0** | 19.3% ± 1.5 | 14.6% ± 2.0 | 22.5% ± 0.1 |
| 18–34 | **35.4% ± 2.3** | 34.3% ± 1.4 | **45.8% ± 2.1** | 25.3% ± 0.1 |
| 35–54 | **27.1% ± 1.7** | 25.4% ± 1.2 | 26.1% ± 3.5 | 26.0% ± 0.1 |
| 55+ | **21.2% ± 1.8** | 21.1% ± 1.3 | 13.5% ± 1.7 | 26.2% ± 0.2 |
| **Households** | | | | |
| family households | **44.2% ± 3.1** | 46.9% ± 2.1 | 35.5% ± 2.1 | 59.4% ± 0.5 |
| married-couple | 29.1% ± 2.8 | 27.2% ± 1.9 | 25.2% ± 2.7 | 36.7% ± 0.5 |
| **with ≥1 person under 18** | **19.4% ± 2.5** | 20.8% ± 2.0 | 16.1% ± 2.0 | 28.1% ± 0.4 |
| living alone | 33.8% ± 2.7 | 32.6% ± 2.1 | 37.7% ± 6.5 | 30.2% ± 0.4 |
| avg household size | 2.11 | 2.35 | 2.21 | 2.57 |
| **Income distribution** | | | | |
| under $50k | **31.4% ± 3.8** | 36.0% ± 2.9 | 22.5% ± 3.0 | 35.1% ± 0.5 |
| $50–100k | 19.0% ± 2.6 | 20.4% ± 2.1 | 16.3% ± 2.6 | 24.3% ± 0.4 |
| $100–200k | **30.2% ± 3.3** | 25.8% ± 2.1 | 24.6% ± 2.9 | 24.6% ± 0.4 |
| over $200k | **19.4% ± 2.0** | 17.8% ± 1.4 | **36.6% ± 7.2** | 16.0% ± 0.3 |
| median HH income (shed) | **$109,431** | $95,885 | $139,899 | $78,548 |
| **Hispanic origin (B03001, % of all residents)** | | | | |
| Hispanic/Latino, any | **29.9% ± 3.5** | 31.1% ± 2.6 | 30.0% ± 3.0 | 18.9% |
| — Puerto Rican | **13.6% ± 3.6** | 13.4% ± 2.3 | 9.5% ± 2.1 | 5.2% |
| — Dominican | 6.0% ± 1.7 | 6.6% ± 1.3 | 7.3% ± 2.1 | 3.7% |
| — **Cuban** | **0.8% ± 0.4** | 0.7% ± 0.2 | 0.5% ± 0.5 | 0.4% |
| — Mexican | 2.7% ± 1.1 | 3.7% ± 0.9 | 4.0% ± 1.6 | 3.6% |
| — Central American | 1.4% ± 0.8 | 1.2% ± 0.5 | 1.5% ± 0.8 | 2.0% |
| — South American | 3.5% ± 0.9 | 3.7% ± 0.9 | 4.2% ± 1.8 | 2.6% |
| **Origin & language** | | | | |
| foreign-born | 25.9% ± 2.1 | 24.4% ± 1.5 | 23.8% ± 2.5 | 35.2% ± 0.3 |
| **Spanish at home (5+)** | **22.0% ± 2.4** | 23.8% ± 2.0 | 23.5% ± 2.7 | 14.5% ± 0.2 |
| — Spanish, English < "very well" | **8.9% ± 1.7** | 9.4% ± 1.2 | 8.7% ± 1.7 | 6.5% ± 0.2 |
| **Work** | | | | |
| worked from home | **25.2% ± 2.7** | 23.7% ± 1.9 | 28.7% ± 5.6 | 17.0% ± 0.3 |
| public transit | 51.7% ± 3.3 | 50.9% ± 2.3 | 50.0% ± 3.7 | 48.6% ± 0.5 |
| walked | 8.4% ± 1.7 | 9.4% ± 1.5 | 9.2% ± 1.6 | 8.4% ± 0.2 |
| car/truck/van | 9.1% ± 1.6 | 10.0% ± 1.1 | 6.7% ± 1.9 | 21.8% ± 0.3 |
| **Time leaving home for work (B08302)** | | | | |
| before 6:00 | 4.2% ± 1.4 | 4.9% ± 0.9 | 4.3% ± 1.3 | 8.1% |
| 6:00–6:59 | 7.7% ± 1.7 | 8.3% ± 1.3 | 8.7% ± 3.2 | 11.4% |
| **7:00–7:59** | **18.7% ± 3.6** | 19.8% ± 2.2 | 14.2% ± 3.0 | 22.7% |
| **8:00–8:59** | **30.9% ± 3.0** | 28.6% ± 2.1 | 36.1% ± 3.9 | 26.5% |
| 9:00–10:59 | **26.0% ± 2.7** | 25.5% ± 2.1 | 25.4% ± 2.9 | 18.5% |
| 11:00–15:59 | 7.2% ± 1.5 | 8.2% ± 1.2 | 7.3% ± 2.0 | 8.3% |
| 16:00+ | 5.3% ± 1.7 | 4.7% ± 1.1 | 3.9% ± 1.5 | 4.5% |
| **Education (25+)** | | | | |
| bachelor's or higher | **55.9% ± 3.0** | 48.5% ± 1.9 | 65.2% ± 4.6 | 41.3% ± 0.4 |
| graduate degree | 18.9% ± 2.1 | 15.6% ± 1.2 | 20.8% ± 4.3 | 16.8% ± 0.2 |
| renters | 84.7% ± 2.0 | 86.1% ± 1.4 | 85.5% ± 3.6 | 70.3% ± 0.4 |

**Top foreign birthplaces** (share of the shed's foreign-born): 400 m — Poland 14.3%, China 14.1%,
**Dominican Republic 9.2%**, Italy 7.3%, Colombia 4.7%, Mexico 3.9%. 800 m — China 15.1%, Poland
12.4%, **Dominican Republic 10.9%**, Mexico 5.5%, Ecuador 3.9%, Colombia 3.4%, **Jamaica 2.0%**.
**Cuba does not appear in the top ten at either radius.** Brooklyn-wide, Jamaica is 6.8% of the
foreign-born — this shed is *under*-Jamaican relative to the borough.

**In people, at 400 m:** ~8,530 residents in 4,003 households — **1,383 under 18**, 775 households
with a child, ~2,549 Hispanic/Latino of whom **1,162 Puerto Rican and about 69 Cuban**, ~1,881
speaking Spanish at home (~760 with limited English), 4,881 workers of whom **1,231 work from home**.
At 800 m: ~10,700 Hispanic/Latino, ~8,230 Spanish-speaking, ~6,660 under 18.

**What this shed is.** Older, more family, more Latino and **much less rich** than the earlier
memo's single-tract read. Against Roebling it trades 10 points of 18–34 for 8 points of 55+, and 17
points of $200k+ households for 9 points of sub-$50k. The income distribution is **bimodal** — 31%
under $50k beside 19% over $200k — so the median ($109,431) describes almost nobody.

---

## 2. Does the neighborhood need a Cuban place?

Supply is `analysis.poi_supply` where `in_principled`, joined to the DOHMH self-reported
`cuisine_description`, at network distance from the lot.

| Cuisine label | within 400 m | within 800 m |
|---|---|---|
| **Cuban** | **0** | **0** |
| Caribbean | 1 (Los Primos, 132 m) | 5 |
| Chinese/Cuban (cuchifrito) | 1 (Caridad China, 369 m) | 2 |
| Spanish (incl. La Isla Cuchifritos, 504 m) | 2 | 6 |
| Latin American | 6 | 17 |
| Soul Food | 1 | 4 |
| Peruvian / Brazilian / Creole / Tapas | 4 | 10 |
| **Mexican + Tex-Mex** | **12** | **22** |
| American | 32 | 72 |
| Coffee/Tea + Donuts + Bakery | 26 | 62 |
| Pizza | 12 | 30 |

**Verdict: yes on Cuban specifically, no on "Latin" generally, and the honest reason is not the
Cuban population.** Three findings, in order of weight:

1. **Zero Cuban-labelled venues within 800 m, and Cuba is not a top-ten birthplace.** But the Cuban
   *resident* population is ~69 people at 400 m (0.8% ± 0.4), against Brooklyn's 0.4%. **This is a
   cuisine-slot gap, not an ethnic-demand gap** — he is serving a 29.9%-Hispanic, 13.6%-Puerto-Rican,
   22%-Spanish-speaking shed that has no Cuban option, and it should be sold that way.
2. **The Caribbean slot is thinner still, and it is his real edge.** 1 Caribbean venue within 400 m
   against 12 Mexican; Pine & Ginger (430 m, Jamaican, grade A) is the only real jerk-and-oxtail
   competitor. **The Jamaican half of this menu faces less competition in five minutes than the
   Cuban half faces in ten.**
3. **The Latin slot overall is not thin** — 17 Latin American + 22 Mexican/Tex-Mex + 6 Spanish within
   800 m, Palenque at 95 m. "There is no Latin food here" is false, and D70 forbids trading on
   incumbent `restaurant` counts in either direction regardless.

**And a live threat.** `analysis.poi_first_seen` records **"Sophie's Cuban Cuisine — Williamsburg",
first seen 2026-08-07, 730 m away** — a multi-location Cuban operator opening **one month after**
El Punto. Single-source (Foursquare `opened_on`), uncorroborated by DOHMH, so treat as *probable not
certain*; it is the single highest-value thing on this page to verify in person this week.

Web sweep agrees: no operating Cuban restaurant within 1.5 miles; Cubana Social closed; the nearest
cafecito culture (Pilar, Tico's) is 1.5+ miles away; Cafetería La Mejor closed Nov 2025.

---

## 3. When people are on the street

MTA hourly entries at **Graham Av (L), complex 122**, averaged per day over Jun–Aug 2026, plus the
DOT pedestrian count **134 m away** on Grand St between Manhattan Ave and Graham Ave (round 2026-05).

| Hour | Weekday entries | Sat | Sun | | Hour | Weekday | Sat | Sun |
|---|---|---|---|---|---|---|---|---|
| 06 | 186 | 68 | 40 | | 15 | 398 | 389 | 347 |
| **07** | **508** | 93 | 67 | | 16 | 444 | 431 | 310 |
| **08** | **1,128** | 167 | 110 | | **17** | **533** | 409 | 303 |
| 09 | 786 | 264 | 209 | | 18 | 471 | 410 | 314 |
| 10 | 390 | 358 | 282 | | 19 | 327 | 373 | 228 |
| 11 | 307 | 389 | 370 | | 20 | 224 | 289 | 178 |
| 12 | 279 | 419 | 403 | | 21 | 180 | 256 | 144 |
| 13 | 283 | 415 | 406 | | 22 | 157 | 229 | 205 |
| 14 | 324 | 387 | 388 | | 23 | 120 | 238 | 89 |
| | | | | | **All day** | **7,196** | **6,080** | **4,996** |

### Who is out, by band

| Band | Weekday subway entries (% of day) | Sat | Sun | ACS / other evidence | **Who is actually out** |
|---|---|---|---|---|---|
| **07–09** | **1,636 (22.7%)** | 260 | 177 | 49.6% of 3,651 commuters leave 07:00–08:59 = **~1,810 people**; DOT AM 532 peds | **Outbound commuters.** The single densest human flow past the door, and the shutter is down. |
| 09–11 | 1,177 (16.4%) | 623 | 490 | a further 26.0% leave 09:00–10:59 = ~950 | Late/flexible leavers, parents post-drop-off, 55+ (21.2%) |
| **11–14** | 868 (12.1%) | **1,222** | **1,179** | **1,231 WFH workers** at 400 m (25.2%); DOT midday 1,199 peds | **WFH locals + retirees on weekdays; the peak weekend band.** |
| 14–15 | 324 (4.5%) | 387 | 388 | — | Trough |
| **15–17** | 842 (11.7%) | 820 | 657 | **three schools inside 200 m**: St Francis of Paola (92 m), PS 132 Conselyea (160 m), 190 Manhattan Ave (183 m); 11 licensed childcare sites within 400 m; **1,383 under-18s** | **School and daycare pick-up.** Entries rise from 324 at 14:00 to 444 by 16:00 — the only weekday band that climbs without a commute to explain it. |
| **17–20** | **1,332 (18.5%)** | 1,192 | 845 | DOT PM **1,879 peds** — the day's busiest count, up from 1,130 in 2022-10 | **Returning residents.** Note: MTA reports *entries only*; the ~1,636 who entered at 07–09 return as **exits** in this band, which the feed cannot see. The 1,332 entries here are people going *out*. Street traffic (DOT 1,879) is the better read of this band and it is the day's highest. |
| **20+** | 561 (7.8%) | 773 | 527 | 3 "Additional Bar" licences within 400 m vs 36 at Roebling | **Thin.** 22:00 weekday = 157 entries. This is not a late-night block. |

**Weekend index 0.75** (avg weekend ÷ weekday) — confirmed, and the *shape* matters more than the
level: the weekday curve is a morning spike, the weekend curve is a **flat midday plateau**
(11:00–17:00 runs 389→431 on Saturday with no peak at all).

---

## 4. Menu structure — ranked, each tied to a number

Ranked by the size of the evidence. **E** = evidence-backed, **J** = judgment.

| # | Move | The number | |
|---|---|---|---|
| 1 | **Family / feeds-2–3 platter bundle for 17:00–21:00 pickup** | 775 households with a child, 1,383 under-18s, avg HH 2.11, DOT PM 1,879 peds (day's highest) | **E** |
| 2 | **A real midday offer 11:00–14:00: a sub-$16 lunch plate** | **1,231 WFH workers inside 400 m** (25.2% ± 2.7 vs Brooklyn 17.0%) — a resident lunch market that does not commute away | **E** |
| 3 | **A low-price anchor tier at $8–12** | **31.4% of households are under $50k** while 19.4% are over $200k. The menu's floor is a $5.50 empanada and its next step is a $14 side and an $18 platter. There is nothing to buy between $8 and $18. | **E** |
| 4 | **Spanish-language menu and signage, Spanish-speaking counter staff** | **22.0% ± 2.4 Spanish at home at 400 m (23.8% at 800 m) vs Brooklyn 14.5%; 8.9% speak English less than "very well"** — ~760 people at 400 m, ~3,250 at 800 m | **E** |
| 5 | **A 15:00–17:00 after-school item at $4–7** | three schools inside 200 m, 11 childcare sites inside 400 m, 1,383 under-18s; entries climb 324→444 across the band | **E** (presence), **J** (conversion) |
| 6 | **Delivery-designed menu for the 800 m ring** | 10,996 households reachable only by delivery; the ring is *more* Latino (31.1%) and *poorer* (36.0% under $50k) than the walk-in shed — **price the delivery menu differently, not just higher** | **E** |
| 7 | **Beer/wine only, no bar programme** | 38 × class-0340 and 16 × 0240 within 400 m; only **3 "Additional Bar" (0423)** vs 36 at Roebling; 20:00+ = 7.8% of the weekday | **E** |
| 8 | **Cuban coffee + pastelito window from 07:30** | 1,636 entries in 07–09 (22.7% of the day) — but **26 coffee/donut/bakery venues inside 400 m**, Variety Coffee at 31 m and Dunkin at 32 m, and D70 says `cafe_bakery` **failed its placebo** | **J — see below** |

### The 07–09 window: argued both ways

**For.** The largest single flow past the door (08:00 alone = 1,128 entries), currently captured at
zero. The product is not coffee-shop coffee — it is a **$3.50 cortadito and a $3.00 guava
pastelito**, which nothing within 800 m sells (nearest: Pilar, Bed-Stuy). Labour: one person, 90
minutes.

**Against.** `cafe_bakery` supply is **3.33× the MN+BK baseline** — a saturated coffee block — and
D70 rates the category `no_signal` *and* placebo-failing, so that count is not evidence either way.
Commuters at an origin station are walking to a train with a fixed departure; conversion is
unestablished, and the labour competes with Lever 2, which serves 1,231 people who are not moving.

**Run it as a 6-week test, not a build-out:** two SKUs, 07:30–10:00 Mon–Fri, no seating change.
**Kill criterion set in advance: under 40 transactions/day averaged over weeks 3–6.**

### What NOT to do

- **Do not build a weekend brunch.** Weekend index 0.75; Saturday 11–14 (1,222) barely exceeds a
  weekday 17–20 (1,332) and Sunday is 4,996 all day against a weekday 7,196. Roebling's index is
  1.06 — that is a different business.
- **Do not open late.** 22:00 weekday = 157 entries; 3 Additional Bar licences within 400 m.
- **Do not lean the marketing on "Cuban community."** ~69 Cuban residents at 400 m. Lead with the
  food and with **Caribbean**, where the supply gap is real and the borough is under-served here.
- **Do not read "restaurant supply 1.86× baseline" as headroom** (D70, `no_signal`) — unchanged from
  the 2026-09-13 memo.
- **Do not price the delivery menu as the counter menu plus a markup.** The 800 m ring is poorer,
  not richer, than the block.

---

## 5. Caveats

- **Tract MOEs are the binding uncertainty on every share.** Puerto Rican is 13.6% ± 3.6 — a band
  spanning 10.0–17.2%. Weighted-sum MOEs assume **independence across tracts**, which overstates
  precision: ACS tract estimates within a PUMA share sample.
- **MAUP is severe, and both answers are shown.** Re-weighting the same tracts to reproduce
  `homes_400m` = 4,003 (a 216 m-equivalent disc) gives a materially different neighborhood: Hispanic
  **20.8%** not 29.9%, Spanish at home **13.4%** not 22.0%, under-18 13.9% not 16.2%, median income
  **$131,297** not $109,431, sub-$50k 21.2% not 31.4%. **The tighter the shed, the richer it gets** —
  Graham Ave is a gradient and the block sits on its north, wealthier side. Every §1 figure is a ring
  average across that gradient, not a description of the corner. **Levers 3, 4 and 6 are the ones
  most exposed** if the true catchment is tighter than 400 m.
- **DOHMH cuisine is self-reported and El Punto's own row is `cuisine: null`** (`never_inspected`),
  so "zero Cuban within 800 m" is partly a labelling fact — though no *other* venue in the ring
  carries a Cuban, Puerto Rican or Dominican label either.
- **The supply double-count is unchanged.** Okozushi still occupies two principled restaurant slots
  at this exact lot; 44 within 400 m is an upper bound, 35–39 is more plausible.
- **Transit is a Jun–Aug 2026 window and reports ENTRIES only.** There is no exit feed, so the
  evening "returning residents" read in §3 is an *inference* from the morning outflow, not a
  measurement. Summer is not February.
- **Sophie's Cuban Cuisine — Williamsburg is single-source** (Foursquare) and unconfirmed.
- §6 review counts are mostly Yelp search snippets (Yelp returned 403 to direct fetch); almost no
  Google counts and **no review-velocity figures** could be obtained. **"n/a" means unmeasured, not
  low.**
- **B08302 excludes WFH workers by construction** — the departure profile describes only the 74.8%
  who commute.

---

## 6. The named competitor set

Network distance from the lot; cuisine from DOHMH; review counts from a web sweep (Yelp unless
noted). **⚑ = Cuban / Caribbean / Latin.**

| Venue | m | Cuisine (DOHMH) | Reviews | Note |
|---|---|---|---|---|
| **OKOZUSHI by Megumi / Okozushi** | 17 / 34 | Japanese | — | **CLOSED. Still counted twice in supply** (`inspected_384d_ago`) |
| **El Punto Cubano Express** | 34 | *null* (never inspected) | none established | Subject |
| Variety Coffee Roasters | 31 | Coffee/Tea | **Google 4.5 / 397**; Yelp ~260 | The AM competitor |
| Dunkin' | 32 | Donuts | — | Chains watchlist, flagged |
| ⚑ **Mesa Coyoacan** | 32 | Mexican | Yelp **851** | Highest review count on the block |
| ⚑ El Loco Burrito | 34 | Mexican | Yelp 3.0 / 198 | Weak rating |
| Good Thanks | 33 | American | **Google 4.5 / 821**; Yelp 72 | Brunch, $13–16 |
| Chingoo | 39 | Korean | **Google 4.7 / 359**; Yelp 147 | Entrées under $20 |
| ⚑ Please Tell Me | 44 | Brazilian | Yelp 24 | Also a bar |
| Carmine's Pizza | 30 | Pizza | Yelp 588 | Legacy Italian layer |
| ⚑ **Palenque Colombian Food** | 95 | Spanish | Yelp 147 | Arepas $8–12; nearest Latin counter |
| ⚑ **Los Primos** | 132 | **Caribbean** | Yelp 71 | 704 Grand St. Oxtail stew **$14.99** |
| ⚑ Grand Morelos | 142 | Mexican | Yelp 254 | 24 h diner |
| ⚑ Bahia Restaurant & Cafe | 148 | Latin American | Yelp 298 | 690 Grand St |
| ⚑ Guest House | 144 | Soul Food | Yelp 36 | 265 Graham Ave |
| The Richardson | 142 | Tapas | — | |
| ⚑ **Casa Ora** | 240 | Latin American | Yelp 320 | Venezuelan, Michelin-rec, $$$ |
| ⚑ Warique | 246 | Peruvian | Yelp 42 | 181 Graham Ave |
| ⚑ **Caridad China** | 369 | **Chinese/Cuban** | Yelp 149 | 108 Graham Ave. **Has a kids' menu** — the only one found on the corridor |
| ⚑ Princesa Bakery & Restaurant | 390 | Latin American | Yelp 66 | 94 Graham Ave |
| ⚑ **Pine & Ginger** | 430 | **Caribbean** (Jamaican) | n/a | DOHMH grade A. **The real jerk/oxtail competitor.** |
| ⚑ **La Isla Cuchifritos** | 504 | Spanish (Puerto Rican) | Yelp 98 | 6 Graham Ave. Half chicken ~$7 |
| ⚑ **Sophie's Cuban Cuisine — Williamsburg** | 730 | *(not in DOHMH)* | n/a | **First seen 2026-08-07. Unverified.** |

**Closed / mis-listed, do not treat as competition:** La Nortena II (255 Graham Ave, closed);
Homemade Taqueria's nearest real site is Meeker Ave; Cubana Social (N 6th St) closed; Cafetería La
Mejor (Suydam St) closed Nov 2025.

**So what:** the block's high-traffic venues (Mesa Coyoacan 851, Good Thanks 821 at 4.5★, Chingoo
359 at 4.7★) are *not* his cuisine — they prove the corner converts foot traffic. His direct
competitors (Los Primos 71, Caridad China 149, Pine & Ginger n/a) are low-review, low-price counters
on the southern stretch. **He is the only Caribbean venue on the corridor's high-traffic north end.**

---

## 7. What is coming

**Restaurants in the works (SLA pending + DOB fit-out, D80):**

| Business | Category | Stage | Date | m |
|---|---|---|---|---|
| **Riff** | bar | liquor application | 2026-07-10 | **82** |
| Metro Organic Market | grocery | liquor application | 2026-09-03 | 222 |
| Bonny's Grocery | grocery | liquor application | 2026-08-26 | 345 |
| TFS Burger Works | restaurant | liquor application | 2025-12-12 | 377 |
| XEFE LLC | restaurant | liquor application | 2026-02-23 | 569 |
| Brown Eyed Hen Group | restaurant | liquor application | 2026-07-31 | 573 |
| Seki Brooklyn | restaurant | liquor application | 2026-06-05 | 669 |

Plus ~40 uncategorised DOB fit-out/permit filings within 800 m since mid-2025, five of them inside
60 m (346/373/374 Graham Ave and the lot itself).

**Newest arrivals within 450 m in 12 months (D79): ~50.** Restaurants — Balera (116 m), Ammazza
Caffe (134 m), Taqueria Bar N.2 (140 m), Hawa (180 m), **Azul Williamsburg (201 m, Aug 2026)**, Kaze
Sushi (238 m), Kirbee's (242 m), **151 Burger Bar (267 m, Sep 2026)**, Loaded (365 m). Bars — Eris
Evolution (266 m), Sizzle and Swizzle (290 m), Small Change (306 m). Cafés — Kinhfolk (90 m), Smor
(108 m), Glasshaus (114 m), Hawa Smoothies (201 m), Hyunah (371 m), Qatra (405 m). Grocery — Meat
Hook (81 m), Met Foodmarkets (229 m), **Whole Foods Daily Shop (284 m, Feb 2026)**.

**Chains watchlist (D77) within 800 m, all flagged as expanding:** Dunkin' (**32 m**, +61 locations
in 12 months, 1,480 total), Burger King (152 m, +4), Yoyo Chicken (281 m, +6), Taco Bell (367 m, +9),
Adobo Mexican Grill (418 m, +5), Wendy's (455 m), Baskin-Robbins (476 m), Chipotle (594 m),
Starbucks (594 m), Aldi (618 m, +4), Pizza Hut (623 m, +15).

**Vacant storefronts within 400 m (DOF registry):** **346 Graham Ave unit 5 (31 m, RETAIL, vacant
2025)** · 357 Graham Ave (54 m) · 328/326 Graham Ave unit 9 (60 m) · 324 Graham Ave (69 m) ·
**318 Graham Ave (77 m, "FOOD SERVICES", vacant 2025 — the former Café Camellia, an NYT Top-50
restaurant that closed April 2025)** · 301 Graham Ave (85 m) · 444 Graham Ave (88 m, vacant
2023/24/25) · 425 Graham Ave (119 m) · 258 Graham Ave unit 7 (162 m) · 751/753/754/757 Grand St.

**So what:** 318 Graham Ave is a **fully-equipped food space 77 m away, vacant since April 2025** —
the second-site option and the place a Cuban or Caribbean competitor would most plausibly land. Riff
at 82 m is applying for a licence; TFS Burger Works, XEFE and Brown Eyed Hen are three more
restaurants applying within 600 m. **Nothing in the pipeline is Cuban or Caribbean.**

---

## 8. Pipeline residents — who is moving in

`analysis.dev_pipeline` within 400 m, ≥1 net unit, D72 `activity_status`:

| Job | BBL | Units | Stage | Filed → Complete | m |
|---|---|---|---|---|---|
| 321191802 | 3030710040 | **162** | complete | 2017-11 → **2025-02** | 366 |
| B00668695 | 3029160014 | **136** | complete | 2022-02 → **2024-07** | 316 |
| 321189851 | 3027647502 | **69** | complete | 2016-12 → **2023-06** | 115 |
| 320627390 | 3027607502 | 80 | complete | → 2017-07 | 128 |
| 320514314 | 3028320015 | 67 | complete | → 2015-05 | 291 |
| 320577746 | 3027907504 | 64 | complete | → 2016-11 | 293 |
| **310081639** | 3027350004 | **57** | permitted | 2008-01 → **STALLED** | **105** |
| 320398191 | 3030520022 | 56 | complete | → 2014-08 | 244 |
| **B01283545** | 3030620012 | **55** | **filed 2025-09-16** | — | 339 |
| **321277499** | 3030620012 | **75** | filed 2015-12 | — | 339 |
| **B01248951** | 3027810036 | **35** | **filed 2025-08-15** | — | 285 |
| 321386077 | 3030610025 | 52 | complete | → 2022-04 | 288 |
| 320623250 | 3027827502 | 51 | complete | → 2018-08 | 144 |
| 320597948 | 3027347502 | 50 | complete | → 2017-04 | 259 |
| 321644538 | 3027240018 | 46 | complete | → 2023-01 | 244 |
| (+6 more complete, 33–42 units, 2010–2015) | | | | | |

**So what:** **298 units completed within 400 m since 2023** (162 + 136 at 366 m and 316 m, both
delivered in the last 24 months) — those residents are **already inside the 4,003** and already in
the §1 demographics. What is genuinely *ahead* is thin and early: two 2025 filings (55 and 35 units)
with no permit yet, one 75-unit filing dormant since 2015, and **a 57-unit job 105 m away that has
been stalled since 2008**. **Do not underwrite on arriving residents.** The demand that will exist
in three years is close to the demand that exists today.

---

## 9. Menu and prices

Prices from public delivery listings (Uber Eats / DoorDash), **not confirmed against the in-store
Graham Ave menu** — the listing may be the shared brand menu also used by the 356 Devoe St kitchen,
and platform prices typically carry a ~15% markup. **Where a price is his, it is marked ●.**

| His item | ● listed | Nearest benchmark | Their price | Read |
|---|---|---|---|---|
| Sándwich Cubano | **$19.00** | Pilar (Bed-Stuy) media noche $9.00; Mesa Coyoacan torta $16.00 | $9–16 | **High vs every Latin sandwich in reach** |
| Cuban-Jamaican Oxtail Sandwich | **$27.00** | — (no comparable) | — | Signature; no competitor to anchor against |
| Oxtail Platter | **$32.00** | Los Primos oxtail stew **$14.99** | $14.99 | **2.1× the nearest Caribbean oxtail** |
| Curry Chicken Platter | **$18.00** | La Isla half chicken ~$7; Los Primos platter $22.99 | $7–23 | In band |
| Pollo a la Plancha | **$20.00** | Mesa Coyoacan enchiladas $23.00 | $23 | In band |
| Chicken / Cuban Mofongo | **$21 / $22** | Caridad China mofongo (price n/a) | n/a | Unbenchmarked |
| Ham Croquettes | **$5.50** | Pilar croqueta **$2.00** | $2.00 | 2.75× |
| Plantain & cheese empanada | **$5.50** | Palenque chicken empanada $6.50; Pilar pastelito $2.50–4.50 | $2.50–6.50 | In band |
| Sweet plantain empanada | **$5.00** | Pilar guava pastelito **$2.50** | $2.50 | 2× |
| Arroz blanco con frijoles (side) | **$14.00** | — | — | **A $14 side of rice and beans is the clearest mis-price on the menu** |
| Fried green plantain (side) | **$6.00** | — | — | In band |
| Mango juice | **$8.00** | Variety espresso "from $4" | $4 | High for a juice |
| **Cuban coffee (cortadito / colada / café con leche)** | **ABSENT** | Pilar café con leche **$4.50**; Variety espresso from $4 | $4–4.50 | **Not on the menu at all** |
| **Pastelitos** | **ABSENT** | Pilar guava pastelito $2.50 | $2.50 | **Not on the menu at all** |
| **Kids' item** | **ABSENT** | Caridad China kids' menu (price n/a) | — | Only corridor example |
| **Family / bundle platter** | **ABSENT** | Palenque $25 brunch bundle | $25 | No family format found on the corridor |

### Ranked changes — impact first

1. **Add a $10–13 "plato del día", 11:00–15:00** (protein + rice + beans + plantain). *Why:* 1,231
   WFH workers inside 400 m and 31.4% of households under $50k, against a cheapest hot dish of $18.
   *Impact:* orders at the weakest weekday band (11–14 = 12.1% of entries). **E**
2. **Cut the rice-and-beans side from $14 to $5–6** and fold it into bundles. *Why:* nothing on this
   corridor supports $14 for a starch side. *Impact:* items-per-ticket, price perception. **E**
3. **Add a "Mesa Familiar" for 2–3 at $45–55.** *Why:* 775 households with a child, avg HH 2.11, DOT
   PM 1,879 (day's highest); dinner ticket is a 30.0% model swing. *Impact:* average order in the
   strongest band. **E**
4. **Hold oxtail at $27 / $32 — do not discount.** *Why:* 49.6% of households clear $100k and no
   competing oxtail in reach exceeds $15; it is the differentiator. *Impact:* margin. **E**
5. **Bring the Cubano to $16–17.** *Why:* the anchor item a first-timer prices the menu by, currently
   above every Latin sandwich within a mile while being his least differentiated dish. *Impact:*
   trial and repeat. **J**
6. **Add cafecito $3.00 / cortadito $3.50 / café con leche $4.00 + $3.00 guava pastelito**, as the
   §4 test. *Why:* 1,636 entries 07–09, nothing within 800 m sells Cuban coffee. *Impact:* revenue at
   a closed hour. **J**
7. **Add a $6–7 kids' plate from 15:00.** *Why:* three schools inside 200 m, 11 childcare sites
   inside 400 m, 1,383 under-18s; Caridad China has the corridor's only kids' menu. *Impact:* the
   15–17 trough. **E** presence / **J** conversion
8. **Price delivery separately — absorb the ~28% commission under $20, recover it on platters.**
   *Why:* the 800 m ring is poorer (36.0% under $50k) and more Latino (31.1%) than the walk-in shed;
   a flat markup prices out the households delivery exists to reach. *Impact:* delivery margin. **E**
9. **Spanish-first menu board, bilingual printed menu.** *Why:* 22.0% Spanish at home at 400 m, 23.8%
   at 800 m, 8.9% limited-English. *Impact:* removes a barrier for ~1 in 11. **E**
10. **Add one vegetarian plate at $13–15.** *Why:* 55.9% BA+, 35.4% aged 18–34, every main is meat.
    *Impact:* removes a veto on group orders. **J**

**De-emphasise:** the $8 mango juice, and whichever mofongo sells less — two at $21/$22 is menu
length for no choice.

**Do not add:** a late-night menu (22:00 weekday = 157 entries), a weekend brunch (weekend index
0.75), or a full bar (3 Additional Bar licences within 400 m vs Roebling's 36).

---

**Files.** Scratchpad, not committed:
`…/773ef68e-4fb0-488b-aeba-d4ff98f84218/scratchpad/graham/neighborhood/` — `shed.py`/`shed.json`
(walk-shed tract weights), `acs.py` + `acs_cache/` (17 ACS tables, tract and county),
`agg.py`/`profiles.json` (weighted profiles, propagated MOEs), `mta.py`, `labels.py`.

**Sources.** ACS 2023 5-year, Census API: B01001, B03001, B05002, B05006, B08006, B08301, B08302,
B11001, B11005, B11016, B15003, B19001, B19013, B25003, B25010, C16001 · PLUTO `bct2020`,
`unitsres`, building-class W · `analysis.poi_supply` + `staging.poi` DOHMH `cuisine` ·
`analysis.poi_first_seen` (D79) · `analysis.storefront_pipeline` (D80) · `analysis.storefront` (DOF
Storefront Registry) · `analysis.dev_pipeline` (D62/D72) · `chains.brand_latest`/`brand_location`
(D77) · `staging.alcohol_licences` · `staging.dot_pedestrian_count` · MTA hourly ridership Jun–Aug
2026 · web sweep (Yelp, Google, Uber Eats, DoorDash, Greenpointers, Gothamist, Sprudge, Edible
Brooklyn).

- **2026-09-14:** owner-facing page "Graham Avenue, on paper" (artifact b176da82) sent to the operator via the owner: shed demographics as people counts, hour-of-day table, cuisine-slot verdict, the Sophie's Cuban alert, 318 Graham vacancy, nine ranked menu/price moves and three do-nots. Nothing requested from him on this page.
