# RQ-001 — Named-neighborhood pre-registration

**Date:** 2026-09-22. **Author:** urban-planner agent.
**Blindness statement:** written **before any results exist**. The only project file read was `METHOD.md` in this folder. The warehouse, `data/` and all notebooks were not queried or opened. Every expectation below comes from knowledge of NYC, not from Loci output.

This file implements the METHOD §8 "named-neighborhood check". Do not edit it after results exist. Corrections go in a dated addendum below the scoring rule, and the original text stays as written.

## 0. How the definition changes what "favorable" means on the ground

Each expectation below reads the spell definition as it is written: within-year citywide percentile ranks, equal weights, demand high, saturation low, cost (ZHVI) low, enter at ≥0.70 for 2 years, exit below 0.60 for 2 years. Five features of the definition govern what the model can show.

1. **Two of the three pillars reward being cheap and under-restauranted.** A dense, poor ZIP scores well on supply (few restaurants per head) and on cost (low ZHVI) even when its demand is weak. So the favorable tercile is likely to be dominated by the South Bronx, northern Manhattan and central Brooklyn. Most gentrifying ZIPs therefore **enter before 2000**, when they were cheap, and **exit when cost rises**. Entries in the middle of the window will be rare. They should occur where the resident population rose sharply (LIC and similar places).
2. **Low saturation in a poor ZIP means low demand, not an unserved market.** Bodega-and-chicken-spot corridors show few restaurants per head because spending power is thin. The definition cannot tell the difference, and it will call such places favorable. East New York is the test of this (see 11208).
3. **Affluent ZIPs are pinned out by cost.** Upper East Side and Park Slope ZHVI sits in the top decile. No realistic demand score lifts the composite to 0.70. "Never favorable" there comes from the definition, and it is also correct on the ground for a new independent operator.
4. **Income does not enter demand until 2009** (METHOD §1: 2000–08 demand = employment + population fixed at 2000). Income gains from gentrification before 2009 are invisible, and poor ZIPs look stronger on demand before 2009 than after. **Expect a cluster of demand-led exits in low-income ZIPs in 2009–2010. That cluster is an artifact of the income join, not an event.**
5. **Saturation divides by residents + workers.** Job-heavy ZIPs (LIC, Midtown) look under-saturated. ZHVI is residential value, so on corridors where commercial rent runs ahead of home values (Ludlow St., Bedford Ave.) the model will under-state cost pressure.

**Universe hazards for named ZIPs:**
- **11249** was carved out of 11211 in 2011. Score 11211 on a merged 11211+11249 series if the crosswalk provides one. If it does not, an 11211 exit dated 2011–12 may be caused by the split.
- **10021** was split into 10065 and 10075 in 2007 and fails the balanced-universe rule. **10128** is used as the affluent control instead.

## 1. Registered expectations (14 scored ZIPs)

"≤2000" means the spell is already running in 2000 (left-truncated), with the onset datable from 1994–99 if the data allow it. The driver is the pillar with the largest adverse move over the exit window (METHOD §6 attribution). **Template** means "running in 2000, cost-led exit".

| ZIP | Neighborhood | Onset | Exit (±3) | Exit driver | Conf. | Why (one line) |
|---|---|---|---|---|---|---|
| 11211 | Williamsburg (N/S Side) | ≤2000 (1996–99) | 2011 | cost (supply second) | med | Cheap, dense, low-income in the 1990s. Condos after the 2005 rezoning and the Bedford Ave restaurant surge push ZHVI and saturation up. The Hasidic south side keeps the ZIP average favorable longer than the Northside actually was. |
| 11206 | E. Williamsburg / N. Bushwick | ≤2000 | 2016 | cost | low | Heavy NYCHA stock (Marcy, Williamsburg and Bushwick Houses) holds income and saturation down. Rowhouse ZHVI catches up in the mid-2010s. |
| 11237 | Bushwick core | ≤2000 | 2017 | cost | low–med | Frontier arrives around 2008–14. Rent-stabilized long-term tenants keep ACS income low, so only rowhouse ZHVI and saturation after 2012 can end the spell. |
| 10002 | LES / Chinatown | ≤2000 | 2007 | cost | low | On the ground, 1997–2007 (Clinton, Ludlow, Orchard) was the emerging window, and it closed with the Blue condo, the Bowery hotels and Whole Foods Houston (2007). **Definition risk:** Chinatown's restaurant density may keep supply unfavorable, so the model may show *no spell at all*. |
| 10026 | Central Harlem (FDB) | ≤2000 | 2012 | cost | low–med | Frederick Douglass Blvd and Lenox corridor boom 2005–12. Brownstone ZHVI climbs toward Manhattan levels. |
| 10031 | Hamilton Heights / Sugar Hill | ≤2000 | ongoing | (cost, if it exits) | med | Dense and rent-stabilized, with CCNY jobs. Cheap by Manhattan standards and still under-restauranted in 2023. |
| 11215 | Park Slope | none | — | — | med–high | ZHVI is already top-decile by 2000. The favorable window on 5th Ave (~1995–2005) was a corridor effect too small to lift the ZIP composite. |
| 11216 | Bed-Stuy (west) | ≤2000 | 2016 | cost | med | Tompkins/Nostrand restaurants from ~2008. Brownstone prices go from about $0.5M to over $2M in 2012–21. |
| 11238 | Prospect Heights / Clinton Hill | ≤2000 | 2009 | cost | low | Vanderbilt Ave restaurant row 2005–10 plus condo and Atlantic Yards pricing. Cost ranks high earlier than in Bed-Stuy. |
| 11222 | Greenpoint | ≤2000 | 2012 | cost | low | Cheap Polish working-class ZIP in 2000. Franklin St restaurants plus the 2005 waterfront rezoning. Moderate density makes it borderline to begin with. |
| 11103 | Astoria (central) | none (intermittent) | — | (supply) | low | A long-stable, restaurant-dense Greek, Arab and immigrant dining market. High saturation should keep it at the threshold without a 2-year spell. |
| 11101 | Long Island City | **2008** (mid-window entry) | ongoing / ≥2019 | cost | low | Queensbridge income and low residential density hold demand down in 2000. The 2001/2008 rezonings add towers, residents and income from ~2008. This is the one registered **entry** event. |
| 10128 | Carnegie Hill / Yorkville (affluent control) | none | — | — | **high** | Cost rank sits around the 95th percentile throughout. The definition pins it out, and that is correct for an operator paying UES rent. |
| 11208 | East New York / Cypress Hills (never control) | none, or onset ≥2016 | — | — | med (on the ground) | Thin spending power. Retail on Pitkin and Liberty is discount and fast food. The frontier (Ocean Hill → ENY, 2016 rezoning) had barely arrived by 2023. **Definition risk:** cheap + under-restauranted + no income before 2009 means the model will probably call it favorable for 2000–08. That would be the failure described in §0 point 2. |

**Unscored context** (recorded so it cannot be retrofitted later):
- 11249: follows 11211, with an earlier cost exit (~2009) because it is waterfront-condo heavy.
- 10027: running in 2000 and ongoing. Columbia and Manhattanville jobs and NYCHA hold it favorable.
- 11105 Ditmars: none, because single-family ZHVI is too high.
- 11225 PLG / Crown Heights South: running in 2000, cost exit ~2018.
- 11372 Jackson Heights: none or intermittent, because Roosevelt Ave saturation is high.

## 2. Scoring rule (fixed before results)

**Per-ZIP HIT** requires both the onset and the exit condition to hold.
- **Onset.** "≤2000" is a hit if the model spell is running in 2000 or starts ≤2003. A year Y is a hit if |onset − Y| ≤ 3. "None" is a hit if there is no spell, or if a single spell lasts ≤3 years in total. For 11208, onset ≥2016 also counts as a hit.
- **Exit.** A year Y is a hit if |exit − Y| ≤ 3 **and** the attributed driver equals the registered driver. "Ongoing" is a hit if the spell is censored at 2023 or exits ≥2021 (any driver). Rows registered "none" have no exit condition.

**Artifact rule.** A demand-led exit dated 2009–2011, or any exit dated 2020–2021, is scored a MISS and also counted as a *break flag*. If ≥3 named ZIPs carry a break flag, the check is reported **INVALID pending the METHOD §9 break fix**, not PASS or FAIL.

**PASS requires all four of the following:**
1. **≥9 of 14 HIT** (64%).
2. **10128 HITs.** This is a hard gate. If the model calls the Upper East Side favorable, the pillars are broken.
3. **≥3 HITs from the non-template set** {10031, 11215, 11103, 11101, 10128, 11208}. Matching only "running in 2000, cost exit" is too easy to prove the model discriminates.
4. **≥4 of the 14 show an entry or exit inside 2001–2022.** A static map that passes on persistence alone does not pass.

**Other rules:**
- If a named ZIP is missing from the balanced universe or lacks ZHVI, drop it and apply the threshold ⌈0.64 × n⌉.
- A MISS at 10002 or 11208 that matches the **definition risk registered above** is still a MISS. It is labeled "definition, predicted" and goes to the contrarian as evidence about the supply and cost pillars, not about the data.
