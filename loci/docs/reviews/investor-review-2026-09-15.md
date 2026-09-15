# Investor review — three regenerated no-trade notes (2026-09-15)

Investor lens, seed AC-23 / GTM-172. Files only; warehouse not opened.
Baseline: `docs/reviews/investor-review-2026-09-14.md` (BLOCKING / BLOCKING / FIX-BEFORE-SEND).

## Cross-cutting

- **blocking — no note says what would change the call.** Zero falsification test, trigger,
  re-look date or kill criterion in any of the three. The 09-14 memos at least printed a
  falsification line (then contradicted it); the fix deleted the contradiction *and* the test.
- **blocking — the closure-check disclosure was dropped.** All three 09-14 memos carried
  "Closure checks disabled for this run" plus the co-located-pair count. The 09-15 notes carry
  neither, while unknown-status shares are 129/302, 115/188, 439/867. The reader gets the
  symptom (unknown competitors → D) with the cause removed.
- **blocking — "no trade" and "no call" are conflated.** All three are data failures, not site
  failures, yet read as rejections; "Full underwriting is not built for a grade below C" is
  circular. Bad site or bad data? Answerable here, unanswered.
- **major — the D18 ECON catchment gate still never runs.** 4,003 / 1,485 / 7,997 homes printed,
  none tested against category minimum (bodega ≈300, pharmacy/gym ≈2,000).
- **major — p(opening) printed, never reconciled to grade** (0.539, 0.542 beside "do not act";
  0.016 as a *lead* category). The 09-14 Gowanus backtest — 2023-01 predicted 0.0051, realized
  zero, "model-version driven and untested" — was the best risk line in the set; gone.
- **minor — run id, spend and supply hash now sit in a provenance footer.** Working.

## 1. 3027550006 · 376 Graham Ave — **BLOCKING**

(a) One page, clear verdict, but ends at "no" with no trigger. (b) Three undated news links,
one a bare homepage (`northbrooklyndispatch.com`) — the class banned on 09-14 — printed
directly above prose saying "No dated news item was found… no headline to flag" (blocking).
The $20M revitalization grant is linked, never sized. (c) **Blocking: the footer refutes the
headline.** The same-BBL check names `3027550006-2026-09-15.md` — this file — as carrying
lead_category `['childcare','convenience','tailor_repair']`, "this report reads 'bank'"; the
09-13 hand memo agrees with the footer. **Major: "Legality: commercial — commercially zoned
(R6A)."** R6A is *residential*; commercial use comes from the C2-4 overlay, mentioned only in
prose. A planner stops reading there. **Major:** leading a p=0.016 category while dropping the
09-14 candidates (tailor_repair 0.00×, hardware C). (d) Grade gate, footer, POI-table removal ✔; web filter
partial (two off-corridor rejects listed, a homepage passed); legality verdict ✘ (zoning string);
named vacancy ✘ — "4 vacant storefronts… since 2022 and 2023" unnamed, while 318 Graham Ave
(ex-Café Camellia, 77 m, equipped) was 09-14's only actionable item. A no-trade note still needs
that name: it is what would change the call.

## 2. 3004260001 · 545 Sackett St — **FIX-BEFORE-SEND**

Most improved. (a) Yes on why-not, no on what-would-change. (b) Clean; the 0.0 convenience
contradiction is gone, replaced by six unknown-status delis. Off-corridor Court/Smith comps and
DNAinfo rejected and listed (change 5 ✔). (c) **Major: no flood, no Gowanus Canal Superfund** — "the risk is
simply that every input needed to size a trade is missing," on a canal-block lot in a Superfund
footprint; the promised floodplain "not loaded" line is absent. **Major:** 797 permitted + 610
completed units printed, never sized or timed — precisely the trigger this note lacks. (d) Special district named (legality ✔ partial); web filter ✔; format ✔.

## 3. 1005500023 · 4 East 8th St — **FIX-BEFORE-SEND**

(a) Names the data gap honestly, then still leads with it. (b) **A Getty Images stock-photo
search page, in Spanish, cited as news**, under prose saying "the only web hits are undated and
are not cited" — they are cited, immediately above. The bogus $302.72 and the $710 Manhattan-
average misuse are gone (change 5 ✔ on rents). (c) **Major regression:** 09-14 explained the
convenience zero — Bravo Supermarket 21.9 m, New Village Market 57.8 m, coded grocery. Both
dropped; the note now asserts the only convenience listing within 500 m of Astor Place is a CVS.
The hedge survived, the evidence that made it credible did not. 21 vacant storefronts again get
one line, unnamed. (d) LPC named with the fit-out consequence stated (legality ✔ partial,
uncosted); SLA 500-ft absent, acceptable at this lead category.

## Remaining generator changes, ranked

1. **Add a "what would change this" block** to the no-trade note — the falsification test as a
   trigger: named vacancy, permit delivery date, status verification.
2. **Split NO TRADE (site fails) from NO CALL (data insufficient)**, and restore the closure-
   check / co-located-pair disclosure that justifies the grade.
3. **Make the same-BBL check gate the run, not annotate it** — a note whose footer refutes its
   headline must not render.
4. **Fix legality strings:** print the effective commercial basis (overlay, special district),
   plus floodplain/Superfund and LPC, or say "not loaded."
5. **Require a dated article:** reject bare homepages, stock-photo/image-search pages and
   neighborhood guides; never print a news list under a sentence saying no news was found.

## Full-memo path

**Not judgeable** — three grade-D anchors exercise none of the restored underwriting. Cheapest
exercise on file: re-run **379 Broome St** (Stone Street Coffee), the one address with a
modelled revenue figure ($1,409,100 capacity-bound,
`docs/recommendations/379-broome-st-2026-09-14.md`); failing that, force a C-graded category at
these anchors — 376 Graham `tailor_repair` (0.00×, C) or 4 E 8th `laundry` (0.956, C).

## Would this embarrass the owner in front of an allocator?

**One of three, for a new reason:** 376 Graham ships a footer telling the reader its own
headline category is wrong, under a zoning verdict a planner would correct on sight. Gowanus
and 4 E 8th are now merely thin, not wrong.
