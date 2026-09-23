# RQ-001 — Named-ZIP miss review (GTM-257)

**Date:** 2026-09-23. **Author:** urban-planner agent (the same role that wrote
`PREREGISTRATION.md` blind on 2026-09-22).
**Scope:** diagnosis only. No model change and no re-scoring. This reviews the
9 misses in the named-neighborhood check (5/14 hit, pass needs ≥9; the 10128 gate
passed), which is ANSWER.md v0.2 Confidence #4.
**Inputs:** notebook cell 35 (composite A scoring). Per-ZIP pillar paths and the
B-owner/B-tenant spells were rebuilt read-only with
`regime_durability.build_zip_year_panel` + `compute_pillar_percentiles`, the same
code the notebook calls. The income source at run time was IRS SOI mean AGI,
1998–2023. The closure signal is known-broken (GTM-259) and is not used here.

**Verdict key:** (a) index blind spot · (b) data gap / measurement break ·
(c) boundary artifact · (d) my pre-registration was wrong on the ground ·
(e) a surprising finding worth believing. A primary verdict is given first and
a secondary one in brackets where it matters.

Pillars are within-year percentiles, where 1 = favorable. So cost 0.90 means
cheaper than 90% of units, and supply 0.10 means more restaurant-saturated than
90% of units.

## The nine misses

**11211 Williamsburg (unit includes 11249). Expected: running in 2000, cost exit
around 2011. A: no spell. B-tenant: none. B-owner: onset 2020, still running.
Verdict (d) [b].** Composite A is 0.48 in 2000 and falls to 0.21 by 2003. It
never reaches 0.70. Cost is already mid-table in 2000 (0.49). ZHVI then rises 63%
in 2000–02, against a citywide median of 23%, and cost falls to 0.23. Supply sits
at 0.35 from the start: the Southside Latino and Hasidic food stock plus Bedford
Ave already make this a mid-saturation ZIP. I registered the 1990s Williamsburg,
cheap and empty. By 2000 the Northside was about eight years into the L-train
artist wave, and the ZIP's favorable window, if it had one, closed in the 1990s.
The panel starts in 2000 with no pre-window (GTM-233), so it cannot see that
window. My "Hasidic south side keeps the average favorable" logic also fails
mechanically. The south side holds *income* down (income percentile 0.17), but
cost is one ZIP-wide ZHVI that the Northside drives, and supply counts the whole
ZIP's restaurants. **Separate measurement break:** the merged unit's population
goes from 70,698 in 2019 to 110,564 in 2020, a 56% jump in one year. 11249 enters
the population series only in the 2020 vintage, while 2011–19 are interpolated
downward on 11211 alone. That jump flips the demand gate on in 2020, so the
**B-owner "onset 2020" is an artifact, not an event.**

**11237 Bushwick. Expected: running in 2000, cost exit around 2017. A: 2000 to
2009 exit, supply-led (Δsupply −0.18, Δcost −0.01, Δdemand +0.02). B: gated out
until 2022. Verdict (a).** The model dates the end of favorability to the first
pioneer wave. Restaurant count goes from 122 to 172 in 2008–10 (Roberta's, the
Morgan/Bogart bar cluster) and reaches 461 by 2023. The count dates a real event
correctly, but it gives that event the wrong sign. For an operator, 2008–12
Bushwick is when the market *proved itself*: the arrivals are what made the next
50 openings bankable. A per-head saturation pillar reads them as competition and
ends the spell right when the opportunity begins. Cost does not move until
2014–16, and that is the exit I registered. The B composites are no better: the
fixed-anchor demand gate keeps Bushwick at zero until 2022 because its tax-filer
income stays in the bottom quintile, so under B the whole Bushwick frontier cannot
be seen. Brooklyn establishment counts rose 24% in 2008–10 against 5% in Manhattan.
That fits the real outer-borough food boom, but it falls inside a recession and is
worth a ZBP coverage check before anyone leans on the exact year.

**10002 LES / Chinatown. Expected: running in 2000, cost exit around 2007. A: no
spell. B-tenant: 2003 onward, B-owner: 2000 onward, both still running.
Verdict (a), definition, predicted [c].** This is the definition risk I
registered. Supply sits at 0.00–0.02 in every year (812–1,196 restaurants on 2.1
km²). Chinatown's dense Cantonese/Fujianese restaurant stock serves a regional
and tourist market that a new LES operator does not compete with head-on, but the
pillar counts every one of those restaurants as saturation. The 1997–2007 emerging window
(Clinton, Ludlow, Orchard) was a corridor inside the ZIP. A ZIP average that
blends Chinatown, the LES grid and the Two Bridges NYCHA towers cannot show it.
That is the secondary boundary problem (c). Composite B fails in the opposite
direction. Its spending-power denominator (82k residents × income) makes 10002
look under-restauranted, so B calls it favorable for 20+ years, straight through
the Blue-condo and Bowery-hotel era. That is a density artifact.

**10026 Central Harlem. Expected: running in 2000, cost exit around 2012. A: 2000
to 2013, supply-led (Δsupply −0.48, Δcost −0.31). B: 2000/2003 onward, still
running. Verdict (d), bordering on (e).** The exit year is a hit (2013 against
2012). The miss comes only from the driver field. My own one-line reason was "the
FDB/Lenox *corridor boom*" (Harlem Tavern, Red Rooster in 2010), which is a
restaurant story, yet I registered cost as the driver. The data support the model.
Establishments go from 16 to 124 by 2014 in a 30–35k-resident ZIP, which takes it
from the most under-restauranted ZIP in the city to mid-table. Supply also starts
at the 0.93–0.98 ceiling, so it has the most room to fall. That ceiling effect
makes "largest percentile move" favor supply in any ZIP that starts nearly empty.
The attribution rule is a horse race between collinear pillars, and the
pre-registration's driver requirement was stricter than the rule can support. On
the ground, the model is right.

**11216 Bed-Stuy (west). Expected: running in 2000, cost exit around 2016. A:
2000 to 2008, cost-led (Δcost −0.41). B-owner: onset 2015; B-tenant: none.
Verdict (a) [d].** The driver matches and the timing is 8 years early. ZHVI goes
from $133k to $470k in 2000–08, and cost falls from 0.95 (among the cheapest) to
0.54 (median). The model is correct that Bed-Stuy's *residential* values had
converged to the city median by 2008, and I underestimated that. That is the (d)
part. But the 2003–07 run-up in black Brooklyn was partly credit, not demand:
subprime and predatory lending were concentrated in Bed-Stuy, East New York and
Canarsie. 11208 shows the signature cleanly: $192k to $444k by 2008, then back
down to $319k by 2012. Commercial rents on Nostrand, Tompkins and Lewis did not
move until about 2012, and that is the cost an operator pays. Residential ZHVI
recorded a mortgage bubble and read it as the end of an operator window.

**11238 Prospect Heights / Clinton Hill. Expected: running in 2000, cost exit
around 2009. A: no spell. B: gated out except 2022. Verdict (d) [b].** Composite
A is 0.54 in 2000 and falls from there. Cost is already 0.20 in 2000 (ZHVI $317k,
above Williamsburg's) and ZHVI rises another 53% by 2002. Clinton Hill and
Prospect Heights brownstones were priced as Fort Greene/Park Slope spillover
through the late 1990s (Pratt, the Vanderbilt and Washington Ave blocks), so the
cheap window closed before 2000. My confidence was low, and the model is right.
The unseen pre-2000 window is the same left-truncation problem as 11211.

**11222 Greenpoint. Expected: running in 2000, cost exit around 2012. A: no spell
(0.63 in 2000, 0.56 in 2001, 0.33 in 2002). B: never. Verdict (d) [a, b].** Cost
was favorable in 2000 (0.89), but supply was not (0.28). Manhattan and Nassau
Avenues already carried a dense stock of Polish diners, bakeries and bars: 122
establishments, about 2.3 per 1,000 residents plus workers, against Harlem's 0.5.
I registered it as "borderline". It started below the bar and ZHVI then rose 67%
in two years, the largest 2000–02 jump in the panel. I carried Greenpoint as an
empty cheap market when it was a dense cheap one, which is the (d). The mechanism
is the same supply-pillar reading as 10002, where incumbent ethnic food stock
counts as saturation against a new-format operator, which is the (a). Whether 1998–99 cleared
0.70 cannot be known (b). Note that the operator spot-check sites Lion's Milk and
Deux Luxe opened in 2021–22 in a ZIP the model has called unfavorable since 2002.

**11101 LIC (unit includes 11109). Expected: entry around 2008, running to 2023.
A: no spell (peak 0.58 in 2006). B-tenant/B-owner: onset 2021, still running.
Verdict (a) [c].** The towers that raise demand also raise cost, at the same time
and faster. Cost falls from 0.83 to 0.25 in 2006–08 as Hunters Point condo
deliveries set a new-construction ZHVI ($389k to $611k), while demand rises
slowly (income percentile 0.51 to 0.82 over 2006–2016). An equal-weight composite
cancels one against the other, so **tower-led growth cannot produce an entry
under A in any year.** This is a structural fact about the index, not about LIC.
The density leg is also a boundary artifact. The ZCTA's 7.08 km² (88th percentile
by area) includes Sunnyside Yard, Dutch Kills industrial land and Queensbridge's
superblock, so population-density percentile goes only from 0.07 to 0.26 while the
residential population doubles (25.6k to 57.3k). B's 2021 entry comes 13 years
late for the same reason: the fixed-anchor density gate is crossed only when the
towers' residents finally outweigh the rail yard. The LIC restaurant scene on
Vernon Blvd and Jackson Ave grew up in 2010–19, entirely outside every spell the
model draws.

**11208 East New York / Cypress Hills (never-control). Expected: none, or onset
2016 or later. A: 2000 to 2023, never exits. B: never. Verdict (a), definition,
predicted.** This is exactly §0 point 2 of the pre-registration, and worse than
registered: I expected it to be favorable in 2000–08 only, and it is favorable
for all 24 years. Demand percentile is 0.09–0.29 every year; supply
(0.79–0.92) and cost (0.59–0.85) carry the composite. Pitkin and Liberty Avenues
are discount retail and fast food. Few restaurants per head here means there is
little money to spend, not an unserved market. The B demand gate cures this miss.
(B scores 11208 correctly.)

## Pattern

**Verdict counts (primary): (a) 5 (10002, 11237, 11216, 11101, 11208) · (d) 4
(11211, 11238, 11222, 10026) · (b) 0 primary, 4 secondary (11211 ×2, 11238,
11222) · (c) 0 primary, 2 secondary (10002, 11101) · (e) 0 (10026 comes
closest).** Two of the five (a) verdicts, 10002 and 11208, are the definition
risks I registered in advance.

**The common cause is one phase of the gentrification cycle.** Composite A's
"favorable" state is the *pre-discovery* state: cheap relative to the city and
empty of restaurants. It therefore ends at the first sign of discovery, either the
first ZHVI jump (11211, 11222, 11238 in 2000–02; 11216 by 2008; 11101 in 2006–08)
or the first pioneer restaurants (11237 in 2009, 10026 in 2013). My registration
encoded the *operator* window, which runs from discovery to maturity: the years a
new independent could open into proven demand before rents repriced. The two
definitions are offset by roughly one phase. Where the model dates an end, it
comes about 8–10 years before mine (11237 and 11216 by −8; 11211, 11222 and 11238
by −9 to −12, closing at or before panel start). Only Harlem, whose restaurant
wave and price wave arrived together, lines up.

The scorecard splits along the same line. The model hits **4 of 6 non-template
ZIPs** (10031, 11215, 11103, 10128), which test *levels*: rich stays expensive,
Astoria stays saturated, Hamilton Heights stays cheap. It hits **1 of 8 template
ZIPs** (11206 only), which test *timing through a gentrification*. A ranks levels
correctly and dates transitions wrong. This agrees with the contrarian's
discovery-vs-favorability falsifier (63.2% cost-led exits) and with A's real
ranking-backtest signal. A ranks *discovery*, and it ranks it well.

Three physical mechanisms turn that offset into misses:
1. **Supply is read with the wrong sign at the frontier.** A count per head
   treats pioneer arrivals (Bushwick 2008–10, FDB) and incumbent ethnic stock
   (Chinatown, Manhattan Ave, and Astoria, which "hit" for the same reason) as
   saturation. Neither competes with a new-format entrant the way a like-for-like
   concept does.
2. **Residential ZHVI is not operator cost.** It picks up mortgage credit (11216
   and 11208 in 2003–08) and new-condo product mix (11101), and it runs years
   ahead of or behind commercial rent on the actual corridor.
3. **ZIP-average geography.** A corridor window inside a mixed ZIP (Clinton and
   Ludlow inside 10002) and a residential boom diluted by a rail yard (11101)
   cannot show up at ZIP grain.

Measurement breaks explain none of the nine on their own. The one I predicted,
a 2009–10 cluster of demand-led exits from the ACS income join (§0 point 4), did
not occur, because the income source became IRS SOI from 1998. That leaves no
break-flagged ZIPs. It is also worth recording that IRS SOI is *mean* AGI, which
top earners pull upward in mixed ZIPs such as 10002 and 11211.

**Composite B does not rescue the check. It fails it worse.** B-tenant and
B-owner each score **2/14** and **fail the 10128 hard gate**: B calls the Upper
East Side control favorable from 2000/2003 to 2023, and Park Slope from 2014. The
demand gate fixes the poor-equals-favorable error (11208) by bringing in
rich-equals-favorable. This is the "rich ZIPs stay rich" reading ANSWER v0.2
already reached from the hazard side, now confirmed on the ground.

## Implications

**For RQ-001's definitions:**
- **Rename composite A to what it measures: an undiscovered / relative-cheapness
  index.** The named check, the cost-led-exit falsifier and the ranking backtest
  now point the same way. Its spell durations are "time until discovery", not
  "time an operator can act". It should not be quoted as a favorability duration.
- **Neither equal-weight composite can represent the operator window.** The
  window starts at discovery, which is exactly where A exits. A pillar-level
  composite has to choose between "poor equals favorable" (A) and "rich equals
  favorable" (B). This is a problem with the construct, not with its tuning, and
  re-weighting will not move the 5/14.
- If the pillar form is kept at all: measure supply as a *change* or by format
  (a like-for-like concept count, net of the incumbent ethnic and limited-service
  stock), not as a per-head level. Take cost from commercial rent or retail-frontage
  values, not ZHVI. Score transitions at corridor grain, not ZIP grain.
- **Data items to fix whatever form is chosen:** (1) the 11211+11249 population
  series jumps 56% at 2020 because 11249 enters only in the 2020 vintage, and
  B-owner's 11211 onset in 2020 is that artifact. (2) Density denominators need
  residential, not gross, land area (11101 is the worst case; probably also the
  Red Hook and Hunts Point type ZIPs). (3) The 2008–10 Brooklyn establishment
  jump (+24% against Manhattan's +5%) is worth a ZBP coverage check. (4) Four of
  the 9 misses are ZIPs whose window closed at or before 2000, so GTM-233 (the
  pre-2000 window) is a validity item for the early frontier, not an extension
  for completeness.

**For RQ-004 (GTM-253, outcome-anchored "favorable"):**
- This review is the strongest case yet for RQ-004's premise. A favorability
  definition built from pillars measures *where a ZIP sits in the gentrification
  cycle*, not *whether an opening there will do well*. RQ-004 should define the
  label from operator outcomes (new independent openings that survive 3 or more
  years) and then treat the pillars as *predictors* of that label, never as the
  label.
- Expect the outcome-anchored window to begin near where composite A exits. RQ-004
  should pre-register that hypothesis explicitly: in Bushwick, Bed-Stuy and Harlem,
  survival-favorable years begin within ±3 years of A's exit. If it holds, A's exit
  becomes a useful *entry* signal, the "discovery" trigger, which turns RQ-001's
  weakness into an input.
- The survival label needs closure data, and closures are 100% Foursquare-sourced
  (GTM-259). **RQ-004 is blocked on GTM-259/GTM-251 for the label**, not only for
  validation. An openings-only interim label (ZBP births by segment) is possible
  but cannot tell a pioneer wave apart from churn.
- My pre-registered windows can serve as a weak held-out check for RQ-004, but
  only after the four (d) corrections above: 11211, 11238 and 11222 closed around
  2000, and 10026's driver is supply. They are one expert's map, not ground-truth
  labels.
