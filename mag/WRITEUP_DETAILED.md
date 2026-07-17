# Detailed Write-Up — Parts 1–4

*Plain-English summary (Part 6) and AI-usage notes: [`WRITEUP.md`](WRITEUP.md).*

# Part 1 — Unified Position Model

## Grain

One row per `fill_id` — one row per matched trade MAG participated in. This is the
natural atomic unit of the desk's activity: every fill is a single position with a
single lifecycle (open → mark → settle), so it's the right level to build everything
else on top of.

`quotes` and `marks` are not their own grain in the model — they're context that
gets folded onto the fill they belong to. `venue_cash` is excluded entirely (see
below).

## Keys

- **Primary key:** `fill_id`, inherited from `fills`.
- `quotes.fill_id` and `marks.fill_id` are foreign keys back to `fills.fill_id`,
  used to join in `theoretical_hold_bps` and the latest mark, respectively.
- `venue_cash` has no `fill_id` at all — it's keyed on `(venue, as_of)`, a
  different grain (capital held at an exchange on a given day, not tied to any
  single position). Joining it onto `pos` would either fan out fill-level rows
  across every cash snapshot or force an arbitrary "as of" date onto a table that
  doesn't need one. It's kept as its own table and used directly for Part 4.

## Sources and how they join

- **`fills`** is the spine. Every row in `pos` starts here; nothing is dropped.
- **`quotes` → `qk`:** filtered to rows where `fill_id` is not null (a quote that
  never got filled has nothing to attach to), then keyed on `fill_id`. On this
  dataset every filled quote is 1:1 with its fill, so the key is safe to use
  directly; a real feed that allows re-quoting the same fill would need an
  aggregation choice here (e.g. first or last quote) before keying.
- **`marks` → `lm`:** reduced from one-row-per-position-per-day to one row per
  `fill_id` by sorting `as_of` ascending and taking the last `mark_value` (and its
  date) per fill. This gives the most recent available mark for each position,
  which in practice is only populated while a position is `OPEN` — once a fill
  settles it stops appearing in `marks`.
- **Join type:** `fills lj qk lj lm` — left joins from `fills`, so every fill
  appears in `pos` exactly once whether or not it was quoted or has a mark.

## Derived fields

- **`realized_pnl`** = `settle_value - mag_stake` for `WON`/`LOST`/`VOID`, else
  null. `settle_value` is already net of the venue fee, so no separate fee
  adjustment is needed. `VOID` correctly nets to `0` since stakes are returned
  in full.
- **`unrealized_pnl`** = `current_mark - mag_stake` for `OPEN` positions only,
  else null. This is gross of any fee that will eventually apply at settlement —
  that fee isn't knowable yet, so it's left out rather than estimated.
- **`realized_hold_bps`** = `1e4 * realized_pnl / mag_stake`, computed only for
  `WON`/`LOST`. `VOID` is deliberately excluded (not zeroed) — a cancelled
  market never tested the model's edge, so "no result" is a more honest value
  than "0 bps," which would otherwise read as a real leak.

## Assumptions worth flagging

- A fill is either fully realized (terminal status) or fully unrealized (`OPEN`);
  there's no partial-settlement case in this data.
- `theoretical_hold_bps` is only meaningful for fills that trace back to a quote;
  fills with no matching quote (if any) simply carry a null there rather than
  breaking the join.
- **The fee mechanics in the data contradict the brief — the data wins.** The
  brief says the fee is charged on `mag_stake` at `fee_bps`. Checked against
  all 127 `WON` fills: every single one settles at
  `(mag_stake + counterparty_stake) × (1 − fee_bps/10⁴)` — fee on the whole
  pool — and zero match the fee-on-stake formula. The model therefore never
  reconstructs payouts from the documented formula; it treats `settle_value`
  as the source of truth everywhere, so this discrepancy can't contaminate any
  downstream number.

---

# Part 2 — Desk P&L View

**Live dashboard:** https://mag-desk-pnl-production.up.railway.app

## What it answers

"How is the desk doing?" — total P&L, split into realized and unrealized, sliceable
by venue and by league. Built on the Part 1 `pos` model, nothing else.

## Tiles

- **Total P&L** — realized + unrealized combined. Deliberately labeled P&L, not
  "revenue": on a trading desk those are different concepts (revenue would be
  gross spread capture before costs), and there is no separate revenue line in
  this data — MAG pays venue fees, it doesn't collect them.
- **Realized P&L** — settled positions only (`WON`/`LOST`/`VOID`).
- **Unrealized P&L** — the current mark of the open book, subtitled with the
  open-position count and stake at risk so the small mark doesn't read as
  "nothing happening" — the exposure is the point, not the mark.
- **Notional volume** — sum of `mag_stake` across fills (fill count as its
  subtitle).
- **Maker / taker realized P&L** — on similar stake ($47.4K vs $44.1K, 160
  fills each), maker flow realized **+$5,754** against taker's **+$1,222**. For
  a market-making desk, "we earn when we rest quotes, roughly break even when
  we cross" is the most actionable read on the page — it's the desk's core
  thesis showing up in the numbers.
- **Open positions** — clickable, jumps to the Hold View.
- **Open book (stake at risk)** — dollars still exposed.
- **Win rate** (`WON / (WON + LOST)`) — excludes `VOID` since a cancelled market
  isn't a win or a loss.
- **Concentration risk — biggest winners & losers** — the five largest realized
  wins and losses side by side. Shown symmetrically on purpose: the top wins
  (+$1,889, +$1,805) are the same magnitude as the top losses (-$1,333,
  -$1,193), so the honest story is that P&L is concentrated in large-stake
  trades on *both* sides — stake size is the risk, not bad picking. Every row
  clicks through to full trade detail.

## Slicing

Venue and league are independent multi-select filters at the top of the view;
every tile and chart reacts to both. Below the tiles: a realized-vs-unrealized bar
chart by venue, the same by league, a cumulative realized P&L trend (by fill date
— there's no settlement-date field in the data, so this is a proxy, called out in
the app itself), and two expandable tables (venue × league breakdown, and open-
position detail) for anyone who wants to drop into the numbers behind a tile.

## The concrete numbers (full sample dataset, all venues/leagues)

- **Total realized P&L: $6,975.47**
- **Open book: $17,917.16 of stake still at risk across 51 positions, currently
  marking at $17,959.38 — unrealized P&L of +$42.22**
- Total P&L: $7,017.69
- Notional volume: $91,540.87 across 320 fills
- Maker realized P&L: +$5,753.86 on $47,425 staked (160 fills); taker: +$1,221.61
  on $44,116 (160 fills)
- Win rate: 51% (127 WON / 122 LOST, 20 VOID excluded)

"How much of the book is still open" deserves both numbers, not just one: the
unrealized P&L (+$42) says the open book is roughly flat against its stakes, but
taken alone it under-tells the exposure — nearly 20% of everything the desk has
staked is still open and unresolved. $17.9K at risk marking +$42 is a very
different picture from "there's $42 out there."

By venue: KALSHI is realizing well ($6,807.60 realized) but currently marking
slightly negative on its open book (-$266.15); POLY's realized P&L is much
smaller ($167.87) but its open book is marking up (+$308.37). By league: NFL is
the one clear loser on this sample (-$4,633.35 realized), while MLB is carrying
most of the desk's realized profit ($8,429.80).

## Notes / judgment calls

- "Volume" isn't a PDF-defined term — I made an explicit call (notional staked,
  with fill count alongside) rather than guessing silently. "Revenue" is avoided
  as a label entirely; see the Total P&L tile note.
- The trend chart uses `filled_at`, not an actual settlement timestamp, because
  the data doesn't carry one. It's a reasonable proxy for "when a position
  entered the book" but not literally "when it was realized" — flagged in the UI
  so it doesn't get mistaken for real settlement timing.
- All timestamps are parsed as UTC end to end (the source data is UTC with no
  zone suffix, which JS would otherwise read as local time and bin late-evening
  fills into the wrong day).
- Gain/loss marks are blue/red, not green/red — green/red fails the
  colorblind-separation check (deutan ΔE 4.0 vs the required 8+); blue/red is
  the standard diverging pair and passes. Realized vs unrealized use two
  lightness steps of the same blue, so blue means exactly one thing on the
  page: P&L dollars.

---

# Part 3 — The Hold View

**Live dashboard:** https://mag-desk-pnl-production.up.railway.app — `Hold View` page

## What it answers

"Are we capturing the edge we think we're quoting, or is there a leak?" —
theoretical (modeled) hold against realized hold, sliceable by league. Built on
the Part 1 `pos` model.

The short answer on this sample: **there is no detectable leak — and no
detectable edge either.** The desk realized 1,031 bps against a quoted 219 bps,
which looks like a large *positive* gap, but the 95% confidence interval on
realized hold runs [-1,151, +3,191] bps and comfortably contains the quoted 219.
249 settled fills cannot resolve a ~219 bps edge. That finding, not the point
estimate, is what the view is designed around.

## How realized hold is defined

**Realized hold (bps) = `1e4 * Σ realized_pnl / Σ mag_stake`**, over `WON`/`LOST`
fills.

Both sides of the comparison are stake-weighted ratios of sums — theoretical hold
is `Σ (theoretical_hold_bps × mag_stake) / Σ mag_stake` over the *same* fills —
and neither is the average of the per-fill `realized_hold_bps` column from Part 1.
That distinction is the main modeling call here:

- Per-fill realized hold is bimodal. A loss is exactly -10,000 bps; a win is
  roughly +10,000. Nothing lands near 219. Its *mean* answers a different
  question — "hold on the average trade" — and weights a $24 fill the same as a
  $1,099 one.
- The desk earns dollars per dollar staked, so the ratio of sums is the number
  that reconciles to the P&L view. It matters: 1,031 bps stake-weighted vs 821
  bps as a naive per-fill average.
- **The denominator is MAG stake (capital at risk), not matched volume**
  (MAG stake + counterparty stake). Matched volume would roughly halve every
  hold number. Either is defensible; what matters is naming the choice so the
  theoretical and realized sides use the same one — which they do here.

**Excluded from the population:**

- **`OPEN`** — a mark is an estimate, not a result. Mixing marks into realized
  hold imports mark noise into a settlement number.
- **`VOID`** — consistent with Part 1. The market was cancelled and the stake
  returned; it never tested the edge, so booking it at 0 bps would read as a leak
  that never happened.

Since `VOID` nets to exactly $0, the Part 3 population's realized P&L
($6,975.47) reconciles exactly to the Part 2 total realized figure, even though
the two populations differ.

## Design

League is the primary slice — it is both the breakdown on the central chart and a
filter (venue and MAG side are also filterable), so the hero numbers can be
recomputed for any single league or combination. The central chart is theoretical
vs realized hold by league, with **95% bootstrap error bars
on realized hold** — bars greyed where the interval covers the quoted edge, i.e.
where the difference is not distinguishable from noise.

The error bars are the design decision. Stripped of them, this chart reads "MLB
is printing, kill NFL" — and both of those are almost certainly luck. A
point-estimate bar chart here would actively mislead the GM into reallocating on
noise, which is a worse outcome than the view not existing. A histogram of
per-fill realized hold sits below the chart to show *why* the intervals are that
wide (the ±10,000 bps bimodality), so the width reads as a property of the
business rather than a defect in the analysis.

The uncertainty is carried everywhere, not just on the chart: the headline
realized-hold number wears its 95% CI as a subtitle, the gap is stated in σ
("+0.7σ — within noise"), each league is labeled with n and n_eff, and a
maker-vs-taker cut ties back to the P&L page's maker-earns story. The closing
chart is a **convergence view** — cumulative realized hold against quoted edge
as fills settle — which reframes the small sample as a design feature: the line
calms as volume grows, and *that chart* is how a real leak gets caught in three
months. Ten days is the noisy left edge of it.

## The concrete numbers (full sample dataset)

**Desk-wide:** 249 settled fills, $67,686.63 staked, $6,975.47 realized P&L.

| | bps |
|---|---:|
| Theoretical hold (stake-weighted) | 219 |
| Realized hold (stake-weighted) | 1,031 |
| **Gap (realized − theoretical)** | **+812** |
| 95% bootstrap CI on realized hold | [-1,151, +3,191] |

**By league** (sorted by stake; σ derived from the bootstrap CI):

| League | Settled fills | n_eff | Stake | Realized P&L | Theoretical | Realized | Gap | Gap (σ) | 95% CI on realized | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NFL | 66 | ≈26 | $21,295.46 | -$4,633.35 | 174 | -2,176 | -2,349 | -1.3σ | [-5,624, +1,576] | Inside CI — noise |
| NBA | 78 | ≈32 | $18,411.76 | $2,883.66 | 217 | 1,566 | +1,350 | +0.7σ | [-2,270, +5,163] | Inside CI — noise |
| MLB | 60 | ≈20 | $14,749.35 | $8,429.80 | 243 | 5,715 | +5,472 | +2.7σ | [+1,277, +9,177] | Outside CI |
| NHL | 45 | ≈19 | $13,230.06 | $295.36 | 268 | 223 | -45 | -0.0σ | [-4,884, +5,269] | Inside CI — noise |

**Effective sample size is the story behind the wide intervals.** The edge is a
coin weighted ~51/49, flipped 249 times — but with wildly uneven bet sizes, so
by the Kish formula ((Σstake)² / Σstake²) those 249 fills carry the information
of only **~95 even bets** desk-wide, and ~19–32 per league. Per-flip outcomes
are ±100% of stake; the edge is ~2% of stake. Ten days of results cannot
resolve a 219 bps signal under ~1,100 bps of noise — even a *total* leak (the
full 219 bps) would be invisible in this sample. That is not a defect in the
view; it is the honest property of the business the view has to communicate.

**Maker vs taker** (same population, cut by side): maker quotes realized 1,806
bps against 217 theoretical (+1.0σ); taker fills realized 341 bps against 221
(+0.1σ). Both inside their intervals — same noise caveat as the league cut —
but directionally consistent with the maker-earns story on the Desk P&L page
(maker +$5,754 realized vs taker +$1,222 on similar stake).

CI endpoints are Monte-Carlo estimates (20,000 resamples, fixed seed) and match
the live dashboard exactly; a different seed moves them by a few tens of bps
without changing any verdict. All point estimates (holds, gaps, P&L) are
deterministic and seed-independent.

MLB is the only league whose interval excludes its quoted edge (+2.7σ) — and
the right read is "probably ran hot," not "we have 5,700 bps of edge in
baseball." With four leagues each tested at 95%, there's roughly a one-in-five
chance that *some* league flags by luck alone (expected false positives: 0.2),
so a single flag is a prompt for more data, not evidence. Symmetrically, NFL's
-$4.6K is the narrative bait — it *looks* like the leak story, but at -1.3σ
it's within noise. Watch both; conclude on neither.

## Adverse selection check

The other place a hold leak hides: if MAG only gets filled when the quote is
wrong, realized hold decays even with a healthy model. Ruled out on this sample —
fill rate is flat across the theoretical-hold range (85% / 90% / 93% / 93% / 91%
for the <150, 150–200, 200–250, 250–300, 300+ bps buckets), and the 30 unfilled
quotes average 220 bps against 230 bps for filled ones. No sign the market is
picking us off on our thinnest edges.

## Assumptions worth flagging

- **The two holds aren't perfectly like-for-like on fees — by assumption.**
  `settle_value` is already net of the venue fee, so realized hold is post-fee.
  I *assume* `theoretical_hold_bps` is the pre-fee model edge; the brief doesn't
  say. If that's right, 150–200 bps of fee is on the order of the entire quoted
  edge and would push realized hold *below* theoretical before variance is
  considered; if the model already quotes net of fees, the caveat drops out
  entirely. On this sample the noise dwarfs the fee either way, so the
  conclusion doesn't change — but on a bigger sample this is the first thing to
  pin down.
- The bootstrap resamples whole fills, so stake and P&L move together and the
  ratio's denominator stays random the way it really is. It's non-parametric on
  purpose: with a two-spike payoff distribution, a normal-theory interval on the
  bps column would understate the spread.
- Every fill in this dataset carries a quote, so both holds are computed over an
  identical set of fills. If unquoted fills ever appeared, they'd have to be
  dropped from both sides, not just one.

---

# Part 4 — The Cash-at-Exchange View

**Live dashboard:** same app as Part 2, second page (`Cash at Exchange`)

## What it answers

"How much capital is deployed where, and how much revolver headroom do we
have?" — a capital snapshot by venue, for the GM and an ultimately executive
audience. Built directly on `venue_cash`, not the Part 1 `pos` model —
`venue_cash` is keyed on `(venue, as_of)`, a different grain (capital held at an
exchange on a given day, not tied to any single position), so it stays a
separate table rather than being forced into a fill-level join.

## Design

Deliberately the sparsest of the four views — the GM question is "how much
capital is where, and how levered are we": four numbers per venue, one
imbalance, one caveat. If the Hold View shows analytical depth, this one shows
restraint. Always broken out by venue first, because collateral is
venue-specific — cash posted at KALSHI cannot back a position at POLY, so a
blended firm-wide number would hide the thing the GM actually needs to act on.
A date selector picks the snapshot (defaults to the most recent date; the brief
explicitly asks for "as of a chosen date," so it's a real control).

- **Hero:** total capital deployed, revolver drawn (with % of capital), and
  headroom — the headroom tile carries its placeholder caveat printed on it.
- **Per-venue cards:** total at venue, posted collateral, free cash, revolver
  drawn, equity-funded — plus a collateral-coverage badge (amber when thin).
- **One chart:** a horizontal capital bar per venue (posted + free stacked)
  with an amber revolver marker overlaid, so deployment and funding read in one
  glance — where the marker sits deep inside the bar, the venue runs on
  borrowed money.
- **One trend:** revolver drawn by venue across the ten days. It's volatile
  (KALSHI swings $4.6K–$11.2K), which is itself the argument for monitoring it
  rather than snapshotting it.

Nothing else — no waterfall, no per-position drill.

## The cross-venue imbalance (the row of arithmetic that earns the view)

Cross-referencing the two tables the brief keeps separate — open stake from
`fills` against posted collateral from `venue_cash`, as of 05-27:

| Venue | Open stake | Posted collateral | Coverage | Revolver-funded |
|---|---:|---:|---:|---:|
| KALSHI | $10,771 | $10,167 | **0.94×** | 68% |
| POLY | $7,146 | $14,076 | **1.97×** | 38% |

Same desk, one venue thin, one double-parked — and the brief's own mechanics
note ("cash at KALSHI cannot back a position at POLY") is exactly why it
matters. The decision this dashboard drives: **move idle POLY collateral, or
draw less revolver.**

Caveat, attached in the UI as well: open stake is a rough proxy for required
margin — venue margin rules aren't in the data — and because statuses are a
current snapshot with no settlement dates, the open book can't be reconstructed
for earlier dates (the coverage badge only renders on the latest date).
Directionally right, precisely unknowable.

## The revolver-limit gap

`venue_cash` gives `revolver_drawn` per venue per day, but no field anywhere in
the dataset states the total facility size. Without a limit, "headroom" has
nothing to be measured against — utilization can be computed, headroom cannot.
Rather than invent a number, the dashboard takes the limit as a sidebar input:
the real figure is a treasury/credit-line fact, not something that would ever
live in the trading data feeds this dataset is modeling, so it makes sense for
it to enter the dashboard as a parameter someone types in rather than a derived
column. Utilization and drawn-dollar figures are shown regardless of whether a
limit is set; headroom updates live once one is entered.

## The concrete numbers (2026-05-27, the last date in the data)

| Venue | Posted collateral | Free cash | Total capital | Revolver drawn | Equity-funded | Utilization |
|---|---:|---:|---:|---:|---:|---:|
| KALSHI | $10,166.59 | $6,320.87 | $16,487.46 | $11,200.40 | $5,287.06 | 68% |
| POLY | $14,076.29 | $4,469.99 | $18,546.28 | $7,086.99 | $11,459.29 | 38% |
| **Total** | **$24,242.88** | **$10,790.86** | **$35,033.74** | **$18,287.39** | **$16,746.35** | **52%** |

At an illustrative $40,000 total revolver facility (the dashboard's default
placeholder, not a number from this dataset), headroom would be $21,712.61
firm-wide.

## Assumptions worth flagging

- `total_capital` = `posted_collateral + free_cash`. `revolver_drawn` is not
  added on top of this — it describes how much of that capital is
  debt-financed via the revolver rather than firm equity, not a separate pool
  of dollars sitting at the venue. Adding it in would double-count.
- The revolver is one facility funding multiple venues, so headroom is
  necessarily a firm-wide figure computed against total drawn across all
  venues, not something that can be derived independently per venue.

