# MAG Desk Analytics — Four Dashboards, One Position Model

**Analytics Lead take-home · Avi Benmayor**

Live and interactive: mag-desk-pnl-production.up.railway.app

Ten trading days, 320 fills, two venues, four leagues — and the four views a GM
needs to run the desk: how we're doing, whether our edge is real, and where the
money sits.

*(Design note for Gamma: dark theme, restrained palette — deep blue #4a6cd4 as
the accent, near-black background. This mirrors the dashboards themselves.)*

---

# One table underneath everything

Fills, marks, quotes, and cash arrive in four shapes. Everything below runs on
**one row per trade**: stake, side, quoted edge, settlement (or latest mark),
venue — joined once, disagreeing never.

**Three judgment calls made early, named out loud:**

- **The data beat the documentation.** The brief says fees are charged on our
  stake; all 127 winning fills settle as pool × (1 − fee). We trust
  `settle_value` everywhere, so the discrepancy can't touch a downstream number.
- **VOID = nothing.** Stake returned, no outcome — zero P&L, excluded from edge
  analysis rather than booked as a fake 0-bps result.
- **Open ≠ realized.** Marks are estimates; they never mix with settled money.

*(Slide asset: deck_assets/pnl_top.png or a simple schema diagram)*

---

# Desk P&L — how are we doing?

**Realized +$6,975 · open book $17,917 at risk, marking +$42 · total +$7,018**

- Slice by venue and league; one bar per trade, click any trade for full detail
- **Maker +$5,754 vs taker +$1,222 on equal stake** — resting quotes earn,
  crossing roughly breaks even. The market-making thesis, visible in the data.
- **Concentration is the risk callout:** the five biggest wins (+$1,889 …) and
  five biggest losses (−$1,333 …) are the same magnitude — P&L lives in a
  handful of large-stake trades on both sides. Stake size is the risk, not bad
  picking.

*Decision this drives: where to allocate capital and attention — and whether
we're comfortable with how concentrated the book is (right now, we shouldn't be).*

*(Slide asset: deck_assets/pnl_full.png)*

---

# Hold View — are we capturing our quoted edge?

**Quoted 219 bps · realized 1,031 bps · gap +0.7σ — within noise**

The honest headline: **ten days cannot answer this question, and the dashboard
says so.** Every fill pays ±10,000 bps; the edge is ~200. Stake concentration
makes 249 settled fills behave like ~95 even bets, so the noise floor is 5× the
entire quoted edge.

- NFL's −$4.6K *looks* like the leak story — it's −1.3σ. Noise.
- MLB flags at +2.7σ — with four leagues tested, a ~1-in-5 chance something
  flags by luck. "Probably ran hot," not "5,700 bps of edge in baseball."
- One clean non-noisy check: filled quotes average 230 bps vs 220 unfilled —
  **no adverse selection** in what gets filled.

*Decision this drives: when to retune the model or pull a market. Today: no
alarm — keep collecting. The CI funnel chart is how a real leak gets caught in
three months.*

*(Slide asset: deck_assets/hold_full.png — the error-bar chart is the
centerpiece; diamonds sit inside every band except MLB's)*

---

# Cash at Exchange — where is the money, and how levered are we?

**$35,034 at venues · $18,287 revolver-drawn (52%) · headroom needs a limit the
data doesn't contain**

The one thing this dataset says unambiguously:

**KALSHI is thin — 0.94× collateral coverage of its open stake, 68%
revolver-funded. POLY is double-parked — 1.97× coverage, 38%.** Cash at one
exchange cannot back the other.

*Decision this drives — this week's concrete action: move idle POLY collateral
to KALSHI, or pay down part of the revolver draw.*

Two gaps named, not papered over: no facility limit exists in the data
(headroom shown against a stated placeholder), and coverage compares collateral
to open stake — a proxy, since venue margin rules aren't provided.

*(Slide asset: deck_assets/cash_full.png)*

---

# What the analytics can and cannot say — by design

**Executive register vs operational register, on purpose:**

| View | Register | Verdict today |
|---|---|---|
| Desk P&L | Executive: five numbers, one risk callout | +$7,018; concentrated book |
| Hold View | Analytical: every number wears its uncertainty | No leak detectable — yet |
| Cash | Sparse: four numbers per venue, one imbalance | Rebalance KALSHI/POLY |

**What I couldn't know, said plainly:** no settlement dates (trend uses fill
date, labeled), no revolver limit (headroom is an input), no margin rules
(coverage is directional).

The dashboards are built to get *more* decisive as data accumulates — the hold
view's confidence funnel narrows with every settled week.

---

# Appendix — numbers a reviewer may want to check

- Realized P&L $6,975.47 · unrealized +$42.22 on $17,917.16 open stake (51 positions)
- Fee check: 127/127 WON fills settle at pool × (1 − fee_bps/10⁴); 0/127 match fee-on-stake
- Hold: theo 219 / realized 1,031 bps, 95% CI [−1,151, +3,191]; n=249, n_eff≈95 (Kish)
- League σ-gaps: NFL −1.3σ · NBA +0.7σ · MLB +2.7σ · NHL −0.0σ
- Maker 1,806/217 bps (+1.0σ) · Taker 341/221 bps (+0.1σ)
- Cash 05-27: KALSHI $16,487 ($11,200 revolver) · POLY $18,546 ($7,087)
- Coverage: KALSHI $10,167 posted / $10,771 open = 0.94× · POLY $14,076 / $7,146 = 1.97×

All computed live at mag-desk-pnl-production.up.railway.app — filters, CIs, and
per-trade drill-downs included.
