# Planner packets — September 2026

*Three findings, one page each, ready to send. Format and recording rules:
[planner-review.md](planner-review.md). Map: `node webmap/server.js` → `<MAP_URL>`.*

---

## Packet A — Openings went where supply was already thick

**Record:** QUESTIONS T12 (new, Tier T, beside T11) · **Source:** D88, `docs/retrodiction-2026-09.md`

**The claim.** We froze the screen at 2023-01-01 and asked where storefronts opened over the next
two years. Blocks that already had *more* of a category per resident were **more** likely to get
another one — and a block with no restaurant within 400 m was *less* likely to get one. The screen
ranks retail streets, not unserved demand.

**Open the map.** `<MAP_URL>` → **Show known locations** on → *Jump to neighborhood*: **Bushwick**,
then **East Williamsburg**. Compare the storefront lines on Knickerbocker and Broadway with the
interior blocks two streets away that our score rates highly.

| What | Value | Grade | Meaning |
|---|---|---|---|
| Own-category supply → own-category entry | +1.17 [0.87, 1.47] | — | thicker supply, more openings, net of density |
| Restaurant, no competitor within 400 m | −0.89 [−1.44, −0.33] | — | an empty block is *less* likely to get one |
| Screen's added predictive lift | +0.013 AUC | — | real but small |
| Card verdict, 14 of 15 categories | "do not act on this data" | D on economics | no local cash-flow comps exist |

**Three yes/no questions**
1. Yes / No — Is this just the geometry of where retail is *legal*? I.e. mostly C1/C2 overlay
   frontage plus existing storefront certificates of occupancy, rather than operators copying
   each other?
2. Yes / No — Would the same hold on a **new-build** corridor where ground floor is mandated but
   empty (Fourth Ave, Frederick Douglass Blvd, Gowanus post-rezoning)? If it breaks there, the
   mechanism is space supply, not demand.
3. Yes / No — Can a corridor read "thick" to us and be a **graveyard** — high count, high churn?

**One open question.** If an operator asked you to find a block where daily needs are underserved,
what would you actually look at? The first three things — we want to know what we are missing.

**What would change if you say no** (it's legality and re-letting, not herding): the entry model
gains a legal-supply control — commercially zoned frontage within 100 m, prior ground-floor retail
occupancy — and the cost-of-search claim narrows to *"ranks sites inside the legal retail set"*: a
smaller, truer claim than `docs/GTM.md` carries today.

**Not asking.** Nothing statistical — we need the mechanism, not the inference.

---

## Packet B — Ten corridors we did not use to tune the character label

**Record:** QUESTIONS X8 · **Source:** D82, GTM-154, next-action 34

**The claim.** We label each address `retail_mixed` / `corporate` / `industrial` / `residential`
from floor area, payroll jobs, and a rule firing when **≥20 commercially zoned lots** sit within
100 m. The first version called twelve prewar retail corridors "residential." We fixed it against
those twelve, so they can no longer test it — every one of them flips at every threshold tried.

**Open the map.** `<MAP_URL>` → **Shade neighborhoods by retail character** on, **Tint addresses
too** on → type each corridor's neighborhood into *Jump to neighborhood*. Current mix:
BK 34.7% retail_mixed / 62.2% residential / 1.9% industrial / 0.2% corporate;
MN 58.2 / 25.6 / 0.0 / 15.5.

**The ten. Please mark each: retail / corporate / industrial / residential — from memory first,
then tell us what the map says.**

| # | Corridor | Segment | Why it's in the set |
|---|---|---|---|
| 1 | Nostrand Ave, Crown Heights | Eastern Pkwy – Empire Blvd | prewar retail, low payroll |
| 2 | Knickerbocker Ave, Bushwick | Myrtle – Halsey | dense small-shop strip |
| 3 | 13th Ave, Borough Park | 44th – 50th | busy strip, almost no recorded jobs |
| 4 | 86th St, Bensonhurst | 18th – 24th Ave | retail under an elevated line |
| 5 | St. Nicholas Ave, Wash. Hts | 175th – 181st | topography, split frontage |
| 6 | Frederick Douglass Blvd | 116th – 125th | **new-build** ground floor — floor-area route, not overlay |
| 7 | E Broadway, Two Bridges | Pike – Clinton | tenement ground floors, upper-floor uses |
| 8 | **3rd Ave, Sunset Park** | 36th – 50th | *negative* — under the expressway |
| 9 | **Columbia St, Carroll Gdns** | Degraw – Sackett | *negative* — two shop blocks in a residential edge |
| 10 | **Ocean Ave, Prospect Lefferts** | Parkside – Lincoln Rd | *negative* — apartment boulevard, corner stores only |

**Three yes/no questions**
1. Yes / No — Are the three marked negative controls correctly *not* retail corridors?
2. Yes / No — Is **lot count within 100 m** the wrong unit — should the rule count *linear feet of
   commercially zoned frontage* instead? A corner-overlay street has few lots and real retail.
3. Yes / No — Would you accept "retail character" as **map colour and card context only**, never
   as an input to a recommendation? That is our current rule.

**One open question.** Where in Manhattan or Brooklyn is the retail/residential distinction
genuinely meaningless — where would you refuse to draw the line at all? We would suppress there.

**What would change if you say no** (≥5 of 10 wrong): the 20-lot threshold is replaced by a
frontage-length rule, the layer re-published, and GTM-154 closes on a measured error rate.

**Not asking.** Not the code, not the zoning lookup — we can read the district. Only whether the
*label* matches the street.

---

## Packet C — Gowanus core: pharmacy 0.00×, convenience 0.40×, hardware 0.72×

**Record:** QUESTIONS D21 (new, Tier D, beside D12) · **Source:** D73/D74,
`docs/recommendations/gowanus-core-2026-09-13.md`

**The claim.** In the Bond–4th Ave / Douglass–9th St box (1,831 addresses, median 3,646 homes
within a 400 m walk), pharmacy supply per resident is **0.00×** the MN+BK median, convenience
**0.40×**, hardware **0.72×**. Laundry, our first lead, is **0.94×** — normal — and was withdrawn.

**Open the map.** `<MAP_URL>` → *Jump to neighborhood*: **Gowanus** → **Show known locations** on,
then the pipeline toggle. Context we hold: the 2021 rezoning's active-use requirement adds roughly
100,000 sq ft of mandated storefront; new-build asks ~$70/SF against Court St ~$115, Smith St ~$90;
13 active permitted jobs / 3,433 units, 7 stalled / 1,673; CSO tanks finish ~2029.

| Category | Ratio | Grade | Meaning |
|---|---|---|---|
| Pharmacy | 0.00× | C | 961 of 1,831 addresses have no pharmacy within a 400 m walk |
| Convenience | 0.40× | C | thin against the city median |
| Hardware | 0.72× | C | thin — but note Lowe's on 2nd Ave sits just outside the principled set |
| Economics, all 15 | — | **D** | no cash-flow comps exist anywhere in the area |

**Three yes/no questions**
1. Yes / No — Is pharmacy 0.00× a **market verdict** rather than an opening? Chain closures,
   mail-order, and scripts following prescribers rather than rooftops would all say so.
2. Yes / No — Can a bodega pay new-construction ground-floor rent here? If not, our "gap" is a
   rent statement and the fill will be a different format or nothing.
3. Yes / No — Does hardware 0.72× survive once Lowe's and the building-supply yards count as
   supply for a resident who needs a hinge?

**One open question — the one we most need.** For each of the three, **what would "filled well"
look like on this block?** The ledger currently scores a fill by category and format; we want your
criteria instead — pharmacy: Medicaid accepted, pharmacist past 7pm, delivery? convenience: EBT,
milk before 7am? hardware: keys, paint, glass, staff who can answer? Those become the fit rubric.

**What would change if you say no** (these are verdicts, not openings): the card gains a
**structurally absent** flag per category, capping the verdict at "do not act," and a `none`
outcome in the ledger stops counting as the market failing to fill a gap.

**Not asking.** Not whether the ratio is computed right. It is measured against revealed citywide
supply: 1.0× means "normal for this city," never "correctly provisioned." Only whether *this*
absence is an opportunity.
