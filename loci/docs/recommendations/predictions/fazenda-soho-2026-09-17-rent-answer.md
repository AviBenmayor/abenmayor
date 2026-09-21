# Correction — rent and square footage, Fazenda, 177 Mott St

**Written:** 2026-09-17. Answers two of five questions in
`fazenda-soho-2026-09-17.md` §6 (question 2). The record itself is frozen — see
§7 there for the logged rows and scoring. This file explains the error; it
revises nothing in the original.

## What was predicted, what is true

The record guessed **$37,500/month** for the whole unit (low–high $22,000–$60,000),
on an assumed **2,500 sq ft** floor of which the counter takes about a third,
**800 sq ft** ($12,000/month, $144,000/yr, the counter's guessed share).

The operator says: **$15,000/month, exactly**, for the whole unit, on a unit
**under 1,000 sq ft** (the owner's words — no exact figure given).

Both guesses are a **miss** against §8's scoring rule: $15,000 falls outside the
$22,000–$60,000 range, and under 1,000 sq ft is nowhere near 2,500.

## Where the error came from

Not the price per square foot — the floor area. $15,000/month × 12 = $180,000/yr.
On a unit under 1,000 sq ft, that is **≥ $180/sq ft/yr** (the true figure is
higher, since the true square footage is smaller than 1,000). The record's guess
was $37,500 × 12 ÷ 2,500 sq ft = **$180/sq ft/yr exactly**. The per-foot rate was
about right; the floor area was wrong by **more than 2.5×** (2,500 vs under
1,000). This is stated as an inequality, not a point estimate, because the exact
square footage still is not known.

The record itself flagged why: PLUTO carries `retailarea` **0** for this
condominium lot (§1, §4a), so the 2,500 sq ft figure had no floor-area data
behind it at all, and no Mott St or Broome St asking rent exists in the
warehouse (§5) — the listings table holds flats, not shops. Both gaps were
named in advance; the guess used a typical footprint in their place, and the
footprint is what missed.

## What this does to the cost side (footnote only — the frozen $530,000 stands)

The pre-registered break-even, **$530,000**, is not revised — that is the frozen
number §6 scores against. As a footnote only: if the counter still takes 32% of
the floor (the record's own assumed split, itself unconfirmed) of a **$15,000**
rent, its share is $4,800/month = **$57,600/yr**, not $144,000/yr. Holding other
fixed costs ($45,000) and staff cost ($140,000) as guessed:

**($57,600 + $45,000 + $140,000) ÷ 0.544 ≈ $446,000**

against the frozen §5 math (fixed $287,000 ÷ 0.544 + owner wage) that produced
$530,000. $446,000 sits **below** the $470,000 bottom-up sales guess (§4c) — the opposite
of the record's stated conclusion that "the counter alone does not carry its
third of the corner" (§4d). Two things keep this a footnote and not a
correction: the 32% floor split was itself a guess, never confirmed, and the
rent figure moves the answer only if that split holds — the counter's share of
the unit is still an open question (§6, question 2, not yet answered).

## What this does to the sales guess

Nothing mechanical. The $470,000 bottom-up figure (§4c) was built from orders ×
ticket, not from floor area, so the rent-and-size answer does not move it
directly. But a unit under 1,000 sq ft means the counter is smaller than the
800 sq ft assumed, which bears on seats and capacity — that connection is left
for the sales answer (§6, question 1), not resolved here.

## Still open

From §6: first-year counter sales (Q1); counter staff cost, headcount, and
whether store staff cover the counter (Q3); weekday orders and average order,
including beer's share of the ticket (Q4); and the coffee-and-beer share vs
clothing share, weekend share of the week, and customer mix (Q5). The counter's
share of the floor, asked as part of Q2, is also still unanswered.
