# Investor review — three `loci report` allocator memos (2026-09-14)

Investor lens, seed AC-23 / GTM-172. Files only; warehouse not opened.
Benchmark: the hand-written `graham-ave-376-*` pair sent to a live operator today.

## Cross-cutting (all three)

- **blocking — each memo contradicts itself about its own falsification test.** §1 prints
  "**Falsification test:** this call is wrong if no *X* is first-seen within 400 m by 2027-09",
  then two paragraphs later "No falsification test is present in the evidence… so none can be
  quoted." One of those is false in every report.
- **blocking — nothing is underwritable.** Revenue p25/p50/p75 and rent ceiling are null in all
  three. The same model produced `rent_ceiling` **$8,551/mo** for BBL 3027550006 on 2026-09-13
  (hand memo §5), so this is a pack-assembly regression, not a model limit. No rent-to-revenue
  ratio, no capex, no payback, no exit price.
- **blocking — the project's own feasibility gate is never run.** D18's ECON minimum-viable
  catchment (bodega ≈300 homes, pharmacy/gym ≈2,000) appears nowhere; homes are reported, the
  test is not applied. Nor is the competition ring just outside the radius (D23).
- **major — all three lead categories grade D, "do not act on this data,"** and the generator
  spends 300+ lines reaching it. Honest, correct, wrong format: a D should emit one page.
- **major — prose cites numbers absent from its own tables** (60-month units, permits, transit).
- **major — jargon leak:** run ids, `total spend $0.0240`, `model 0.1.1+f1cb6628`, supply hash
  `467cd5969200`, "Caveat (D88)", "support pooled/fitted", `overture_places:no_status_field`.
- **minor — the 200–870-row POI table is a data dump,** not a memo section.

## 1. 3027550006 · 376 Graham Ave — **FIX-BEFORE-SEND**

(a) No. The trade is "bank branch, grade D"; entry/exit exist only as a generic closing line.
(b) The LoopNet "$70/SF, 4,828 SF" and the "700–1,600 SF at 98 Graham Avenue" comparable cite
rotating search-index pages that will not show those figures tomorrow; the fast-food item cites a
homepage. (c) A **bank branch** led on a 74.7%-renter, 40.3%-young block — the memo half-notices
("this demographic does not use branches") and leads with it anyway; "for the lead category the
picture is empty" while its own table lists a bank at **122 m**; hardware graded C at supply ratio
**1.90** (over-supplied) with no account of what C means; "0.36 (the demand block reports 0.35)"
surfaced, unresolved. (d) **Conflicts with the page sent to the operator today** — the hand memo
calls `tailor_repair 0.00×` the address's `lead_category`; cafe_bakery is 3.48 here, 3.33 there.
Missing versus that page: the named vacant space (**318 Graham Ave, 77 m, ex-Café Camellia, fully
equipped, vacant since April 2025** — the only actionable item produced today), SLA-pending/DOB
fit-out pipeline, chains watchlist (Dunkin' at 32 m, expanding), dayparts, the named competitor
set with traffic, and kill criteria.

## 2. 3004260001 · Gowanus — **BLOCKING**

(a) No, and it says so ("The trade as screened is: there is no trade") — the best line in the set.
(b) The convenience ratio of **0.0** is contradicted inside the same paragraph by six SNAP delis.
(c) **The lot is Gowanus; every comp is Carroll Gardens / Red Hook / Cobble Hill** — a canal-side
M1-4/R7X site priced off Court and Smith Street asks ($120/SF at 361 Court). "Commercially zoned
(M1-4/R7X)", no overlay, ignores the **Special Gowanus Mixed Use District**, the floodplain and
the **Gowanus Canal Superfund** site; flood risk enters only via a Reddit link. "News" is Reddit,
a YouTube walking tour, Condé Nast Traveler, and **DNAinfo, defunct since 2017**. (d) All the hand
page's substance is absent; and 797 permitted units — the whole thesis — is never sized or timed.

## 3. 1005500023 · 4 East 8th St — **BLOCKING**

(a) No. (b) "**$302.72**, unit unstated" — a price quoted without knowing annual PSF or monthly.
"Cushman & Wakefield's Q2 2026 read… a Manhattan average near **$710**" is the *premier corridor*
figure, and report 1 explicitly discarded that same number as inapplicable. Starbucks/Astor Place
and the $30 wage cite a NY Post tag page, an amNY archive index and a chamber homepage. (c) **"No
open convenience POI in the radius" in Greenwich Village, inside 867 POIs** — the hedge
("classification hole") is right, which makes leading with it worse. Legality reduced to "C1-7"
ignores LPC storefront review (labelled, never costed) and the SLA 500-ft rule under an exit thesis
of food and beverage. **21 vacant storefronts within 400 m**, the most decision-relevant number
here, gets one line and no analysis.

## Six generator changes, ranked

1. **One falsification block from one field.** Delete the contradicting prose rule.
2. **Gate on grade:** below C, emit a one-page no-trade note, not a full memo.
3. **Restore revenue band + rent ceiling to the pack** and require an underwriting paragraph:
   catchment vs D18 ECON minimum, rent as % of modelled revenue, payback, downside case.
4. **Name supply and pipeline, don't count them:** DOF vacant-storefront rows (address, SF, use,
   vacant-since), SLA-pending / DOB fit-out, chains watchlist. This is what an operator acts on.
5. **Fix the web layer:** geo-scope searches to the lot's own corridor and reject off-corridor
   comps; require a dated article URL and the figure's unit; ban Reddit, YouTube, Instagram,
   Facebook, tag/archive indexes, chamber homepages, DNAinfo.
6. **Legality as a planner's verdict, not a zoning string** — special districts, floodplain/
   Superfund, LPC, SLA 500-ft — plus a same-BBL consistency check against other same-day
   artifacts; move the POI table to an appendix with internal identifiers stripped.

## Would this embarrass the owner in front of an allocator?

**Yes — two of the three would:** a convenience desert in Greenwich Village and a Gowanus site
underwritten off Court Street are claims a broker or planner would laugh at, and all three tell
the allocator not to act while taking three hundred lines and no underwriting to say it.
