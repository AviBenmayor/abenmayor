# Part 6 — Plain-English Summary

*Parts 1–4 — every judgment call and number in full — are in
[`WRITEUP_DETAILED.md`](WRITEUP_DETAILED.md).*

## What I built

Every question in this exercise comes down to trades, so I built one table where
each row is a single trade with everything we know about it: what we staked,
which side we were on, the edge our model expected when we quoted it, what it
settled for (or its latest estimated value if it hasn't settled), and where the
money sits. All four dashboards run on that one table plus the daily cash
ledger. One source of truth means the P&L view, the hold view, and the cash view
can never quietly disagree with each other.

## The judgment calls I'm most confident about

**I trusted the settlement numbers over the documentation.** The brief says our
fee is charged on our stake. The data says otherwise — on every single winning
trade, the payout works out to the pool minus a fee on the whole pool. Rather
than reconstruct payouts from a formula the data contradicts, I treated the
actual settlement amount as the source of truth everywhere. If I'm wrong about
which document is right, the numbers don't change — that's the point of the
choice.

**Cancelled markets count as nothing, and open positions are estimates.** A
voided trade returned our stake — no win, no loss — so it contributes zero
everywhere and is excluded from the edge analysis entirely. Open positions are
valued at their most recent daily estimate and always shown separately from
settled results, because one is money in the bank and the other is a guess that
moves.

## What the numbers say

We made about $7,000 over the ten days: $6,975 settled, plus roughly $42 of
estimated value on the $17,900 still riding on 51 open positions. Almost all of
the settled profit came from one venue (Kalshi) and we lost about $4,600 on NFL
markets — but here's the most important thing I can tell you: ten days is not
enough data to conclude anything from that. Every trade either wins big or
loses everything, so short-run results swing far more than our roughly 2%
quoted edge. The NFL loss, and an unusually good run in baseball, are both
within the range luck alone produces. The hold dashboard is built to say so
honestly — and to catch a real leak once a few months of volume settle.

One thing the data does say clearly: our collateral is in the wrong places.
Poly holds about twice what its open positions need while Kalshi is slightly
short, and money at one exchange can't back trades at the other.

## What I couldn't know

There's no settlement date in the data (so the daily profit trend uses trade
date as an imperfect stand-in, labeled as such), no size for the revolver
facility (so I can show what's drawn, but "headroom" needs the limit), and no
venue margin rules (so collateral coverage is directional, not exact).

## The decision each dashboard drives

- **Desk P&L** — where to allocate capital and attention: which venue and
  league is earning, whether resting quotes or crossing is paying, and whether
  profit is dangerously concentrated in a few large trades (right now, it is).
- **Hold** — when to retune the pricing model or pull back from a market: it
  flags a league only when the gap from quoted edge is too large to be luck.
  Today it says: no alarm, keep collecting data.
- **Cash at exchange** — this week's concrete action: rebalance idle Poly
  collateral toward Kalshi, or pay down part of the $18,300 revolver draw
  instead of funding positions with borrowed money at one venue while cash
  idles at another.

---

## Using AI

**Part 1:** I wrote the first draft of the q logic myself, then used Claude Code
to check it against the actual workbook — confirming the schema strings matched
the real columns, catching a few syntax typos (smart quotes, a `csv`/`css` typo, a
missing file-path colon), and verifying a couple of assumptions directly against
the data (that `VOID` fills return the full stake, that no fill is quoted more
than once, and that `marks` only ever covers positions that are currently
`OPEN`). I also had it draft the grain/keys/joins write-up from the finished
logic, which I reviewed and edited rather than taking as-is.

**Part 2:** I asked Claude Code to port the Part 1 q logic to pandas (no q
interpreter available to me locally) and build the dashboard end to
end — tiles, filters, charts — from a spec I gave it (which metrics,
what "revenue" and "volume" should mean, what stack, how to deploy). It computed
the actual Part 2 numbers in the detailed write-up from the full dataset and I checked them against the
Part 1 logic before accepting them. I didn't accept anything I couldn't explain —
in particular the exclusion of `VOID` from `realized_hold_bps` in Part 1, the
decision to leave `venue_cash` unjoined, and what "revenue" means in a
fee-paying (not fee-collecting) desk were my calls, not the AI's suggestions.

**Part 3:** I asked Claude Code to build the hold view on the Part 1 model and to
test whether the headline gap was real rather than just reporting it. It computed
the stake-weighted comparison, ran the bootstrap behind the [-1,120, +3,167] bps
interval, checked the adverse-selection angle (fill rate by theoretical-hold
bucket), and built the page. The variance framing that the view is now built
around — that 249 binary settlements can't resolve a ~219 bps edge, so the view
has to show intervals rather than point estimates — came out of that analysis
rather than from my initial spec, and it changed the answer from "MLB is
printing" to "this sample can't tell you yet." I checked the numbers back against
the Part 1 logic and had it run the page end to end before accepting it. The
pre-fee/post-fee mismatch between the two holds is called out in the detailed
write-up rather than silently corrected, because the data doesn't settle which
one the model meant.

**Part 4:** I flagged that the dataset has no revolver facility limit anywhere
and asked Claude Code to add the second dashboard page against a spec I gave it
(tiles, venue-first layout, the revolver-limit-as-input decision). It
computed the Part 4 numbers in the detailed write-up from `venue_cash`, and ran the app
locally to confirm both pages load before I accepted the page. The call to treat
the revolver limit as a user-entered parameter instead of guessing a number, and
the double-counting flag on `revolver_drawn`, were mine.
