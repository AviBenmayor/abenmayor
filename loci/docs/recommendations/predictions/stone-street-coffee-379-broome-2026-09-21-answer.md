# Correction and score — Stone Street Coffee, 379 Broome St

**Written:** 2026-09-21. Answers §6 Q1 (sales), most of Q2 (rent and square footage), Q3
(staff cost, partial), Q4 (orders and ticket), and Q5 (weekend share) of
`stone-street-coffee-379-broome-2026-09-15.md`. The record itself is frozen — see §7
there for the logged rows. This file scores the guesses and explains the two misses; it
revises nothing in the original.

## 1. Scoring the four sales guesses

True annual sales: **≈$1,400,000** (operator's figure, not an audited number — 107,000
transactions × ~$13.08 average).

| | Our number | ln(our ÷ true) | \|error\| | In range? |
|---|---|---|---|---|
| **(a) Loci model** | $1,409,100 | ln(1,409,100/1,400,000) = **+0.006** | 0.006 | HIT ($805,200–$2,013,000) |
| **(c) Bottom-up** | $1,160,000 | ln(1,160,000/1,400,000) = **−0.188** | 0.188 | HIT ($750,000–$1,650,000) |
| **(b) Judgment** | $1,000,000 | ln(1,000,000/1,400,000) = **−0.336** | 0.336 | HIT ($700,000–$1,450,000, barely) |

All three sales guesses hit their ranges. By the record's own error metric, **(a) the
Loci model wins**, by a wide margin.

## 2. Why (a)'s near-exact hit does not validate the model

The record pre-registered exactly this outcome and pre-committed to distrust it. From
§4a: `capacity_bound` is TRUE, meaning all three of the model's figures are "not a
demand estimate — it is floor area times a price band." From the record's closing line
in §4: **"(a) is high; the truth sits between $800,000 and $1,300,000. Above $1.4M, our
order count was far too low and the model was right by accident."**

True sales landed at ~$1,400,000 — at or just above that self-declared $1,300,000
ceiling. This is precisely the zone the record said in advance would make (a)'s hit
meaningless. So the correct read is: **the record's own qualitative sales estimate
(the $800k–$1.3M band, tighter than any of the four numeric guesses) was itself about
7–8% low**, and the model's win is the coincidence that was called ahead of time, not
evidence that floor-area × price-band is a working revenue model for `cafe_bakery`.
Nothing here should be used to argue for turning the capacity-bound heuristic into an
actual `cafe_bakery` estimator.

The order-count check confirms this reading rather than contradicting it: back-solving
from the true sales gives ≈107,000 orders/year (≈2,058/week), only about 5% above the
bottom-up guess's 1,960/week — a modest miss, not the "far too low" order count the
record said would be needed for truth to sit above $1.4M. The bottom-up method (c)
under-shot on orders by a small, explicable margin (a food-heavier mix than assumed
lifts revenue per order more than it lifts order count); the model's win is still not
mechanically connected to that.

## 3. The floor-area miss

The record assumed the 2,013 sq ft PLUTO retail floor was split roughly in half with
the neighboring business (Greecologies, 1 m away), putting Stone Street's own floor at
**~1,000 sq ft**. The operator says the shop has **the whole ground floor (2,013 sq ft)
plus a basement of equal size** — call it ~4,000 sq ft of usable space, none of which
matches the "half, ~1,000 sq ft" assumption. **MISS.**

This is the second floor-area miss on this project after Fazenda's
(`fazenda-soho-2026-09-17-rent-answer.md`, D130) — but it misses in the **opposite
direction**. Fazenda's guess assumed a floor area (2,500 sq ft) far **larger** than the
true figure (under 1,000 sq ft) because PLUTO's `retailarea` was 0 for that
condominium lot and a typical footprint was used in its place. Here, PLUTO's
`retailarea` (2,013 sq ft) was a real, present figure, and the miss came from an
*extra* assumption layered on top of good data — that a nearby second business implied
a shared floor. Together these two misses say the same thing from both sides: **do not
guess floor area or its split from adjacency or lot-typical footprints; ask.** A
present `retailarea` figure is necessary but not sufficient — it does not tell you who
holds how much of it, or whether a basement doubles it.

One reason this miss did not also break the sales guesses: none of (a)–(c) scale
linearly with the corrected floor area in a way that would have moved them further from
the true number. (a) is floor-area-driven but used the *building's* 2,013 sq ft, which
is close to what the operator actually holds on the ground floor alone (before the
basement) — so the floor-area assumption was wrong for the reason stated in the
original record (shared with the neighbor) while landing close to right for a different
reason (the operator's true footprint, ground floor only, is close to the number used).
(b) and (c) were built from per-square-foot judgment and order counts, not the PLUTO
figure, so they were insulated from this particular error either way.

## 4. Rent and staff — directional hits, not clean scores

**Rent.** No exact figure was given. The operator's "a little low... almost nobody in
Nolita has rent under 10k" places the true rent above the $10,500 guess but gives no
upper bound; it likely still clears the guessed $15,000 high end, but that is inference,
not a stated number. Logged as a directional **HIT** on range, not scored with an
ln-error the way the sales guesses were, because there is no point estimate to divide
by.

**Staff cost.** The operator's "close" on the $340,000 guess is treated as a **HIT** on
the dollar figure — again not ln-scored, since no exact figure was given. The headcount
answer (2 baristas + 3 kitchen + 1 porter = 6) contradicts the *composition* the guess
implied (two to three people at the busy hours, a counter-serve model with only
incidental food) even though the dollar total held up. This matters more than a clean
hit suggests: a coffee-only estimate that happens to land on the right total wage bill
because a kitchen-heavy staffing pattern costs about the same as a leaner one carrying
higher per-hour rates for fewer people is not the same as correctly modeling the
business.

## 5. Still open

Exact rent figure and lease terms; exact headcount hours (is "2 baristas / 3 kitchen /
1 porter" a single shift or the full daily roster?); before-or-after-sales-tax framing
on the $1.4M; whether delivery apps' share is counted gross or net of commission;
tips-on-top-of-wages; and customer mix (resident / worker / visitor). None of these
change the sales scoring above; they would sharpen the rent and staff-cost verdicts from
directional to exact.
