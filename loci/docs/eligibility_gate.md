# The eligibility gate — where it binds, what it costs, and what should replace it

**Status:** read-only analysis, no code or data changed.
**Run analysed:** the single run stamped on `analysis.address` —
`supply_set = principled`, `supply_hash = 06bb6f357cc1`, `reach_hash = f6339bf9d842`,
`graph_version = walk_graph.pkl:1788298912:306836099`, 767,337 addresses, `run_at` 2026-09-11 11:13:27 UTC.
**Scope of the deliverable:** MN+BK (D48). Outer boroughs appear only because the gate's behaviour
there is what made D69 visible.

**Tier of claim.** Everything below is **descriptive** — a measurement of what the current rule does
to the current data, plus one **external-criterion comparison** (§6) that is predictive at best.
Nothing here is causal, and no statement that a different gate is "better" means anything
beyond "it agrees more closely with an independent register of storefronts."

**Reproduction check.** `present_count` and `eligible` as stored in `analysis.address` were
recomputed from `analysis.address_category.nearest_m ≤ 800 m` and agree on **all 767,337 rows,
0 disagreements**. A separate Dijkstra re-run of two categories (`bar`, `childcare`) on
`in_principled` reproduces the stored `nearest_m` to 1.2 × 10⁻⁴ m, so every counterfactual in this
document is computed on the same engine that produced the run.

---

## 1. Where the gate binds

### 1.1 Full `present_count` distribution, addresses

| present_count | BK | BX | MN | QN | SI |
|---:|---:|---:|---:|---:|---:|
| 0 | 431 | 86 | 0 | 1,550 | 4,461 |
| 1 | 338 | 77 | 0 | 1,800 | 3,903 |
| 2 | 557 | 444 | 0 | 2,390 | 6,047 |
| 3 | 436 | 191 | 0 | 3,177 | 6,087 |
| 4 | 575 | 630 | 0 | 3,266 | 6,112 |
| 5 | 1,003 | 561 | 0 | 3,794 | 5,036 |
| 6 | 356 | 503 | 0 | 3,647 | 4,889 |
| 7 | 414 | 644 | 1 | 4,471 | 5,225 |
| 8 | 830 | 1,445 | 0 | 6,355 | 6,277 |
| 9 | 1,739 | 2,685 | 1 | 9,708 | 5,189 |
| 10 | 2,903 | 3,031 | 0 | 14,283 | 7,126 |
| **11 (one short)** | **4,927** | **4,660** | **2** | **19,609** | **9,535** |
| **12 (exactly at the line)** | **9,658** | **6,558** | **34** | **34,790** | **10,935** |
| 13 | 29,202 | 12,208 | 76 | 53,859 | 14,299 |
| 14 | 75,988 | 23,559 | 4,013 | 70,571 | 14,851 |
| 15 | 120,095 | 18,443 | 28,263 | 64,300 | 2,228 |

### 1.2 Binding share by borough

`sh11` / `sh12` are the share of the borough's addresses sitting exactly one short of, and exactly
on, the line. `u11` / `u12` are the same in units.

| borough | addresses | units | sh11 % | u11 % | sh12 % | u12 % | eligible % (addr) | eligible % (units) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MN | 32,390 | 958,418 | 0.01 | 0.88 | 0.10 | 0.71 | **99.99** | 98.98 |
| BK | 249,452 | 1,115,826 | 1.98 | 1.95 | 3.87 | 3.18 | **94.18** | 95.31 |
| BX | 75,725 | 591,133 | 6.15 | 4.92 | 8.66 | 6.95 | 80.25 | 87.77 |
| QN | 297,570 | 889,749 | 6.59 | 5.05 | 11.69 | 8.00 | 75.12 | 82.49 |
| SI | 112,200 | 180,143 | 8.50 | 8.62 | 9.75 | 9.06 | 37.71 | 39.85 |

**Read:** the gate is nearly inert in Manhattan (36 addresses of 32,390 within one category of the
line), mildly live in Brooklyn (14,585 addresses, 5.8%, within one category either way) and a
first-order rule in Queens and Staten Island (18.3% and 18.3% of addresses within one category).

Total MN+BK exposure:

| band | addresses | share of MN+BK | units | share of units |
|---|---:|---:|---:|---:|
| pc ≤ 10 (ineligible, not marginal) | 9,584 | 3.40% | 31,870 | 1.54% |
| pc = 11 (one short) | 4,929 | 1.75% | 30,179 | 1.45% |
| pc = 12 (exactly at the line) | 9,692 | 3.44% | 42,304 | 2.04% |
| pc ≥ 13 | 257,637 | 91.41% | 1,969,891 | 94.97% |

### 1.3 Which category is the marginal 12th

Every `present_count = 11` address has **exactly four** absent categories, and any one of them
would flip it. The table is therefore the frequency with which each category appears in that
four-member absent set.

| category | reach (m) | absent at pc=11, citywide % | absent at pc=11, **pre-D69** % | absent at pc=11, MN+BK % | absent at pc=12, MN+BK % | absent at any address, citywide % |
|---|---:|---:|---:|---:|---:|---:|
| tailor_repair | 960 | **93.2** | 93.3 | **94.2** | 87.1 | 60.2 |
| hardware | 960 | 57.3 | 54.9 | 32.8 | 29.1 | 25.4 |
| bar | 400 | 51.3 | 48.9 | 63.5 | 36.0 | 23.9 |
| bank | 640 | 49.2 | 49.5 | **80.4** | 58.9 | 25.2 |
| clinic | 960 | 25.7 | 24.6 | 17.1 | 20.9 | 15.0 |
| convenience | 400 | 24.6 | 23.3 | 6.2 | 3.5 | 14.3 |
| fitness | 1200 | 22.5 | 22.4 | 40.1 | 41.4 | 14.6 |
| cafe_bakery | 400 | 20.0 | 17.5 | 24.0 | 10.5 | 13.1 |
| pharmacy | 800 | 18.8 | 16.8 | 7.7 | 3.1 | 13.1 |
| **childcare** | 640 | **14.5** | **29.6** | 4.8 | 0.1 | 7.4 |
| laundry | 320 | 9.6 | 7.9 | 6.8 | 5.8 | 11.0 |
| grocery | 800 | 6.7 | 5.6 | 8.0 | 0.0 | 7.2 |
| nails_beauty | 640 | 4.1 | 3.6 | 10.8 | 1.1 | 7.5 |
| hair_barber | 640 | 2.5 | 2.1 | 3.7 | 2.5 | 8.0 |
| restaurant | 400 | 0.0 | 0.0 | 0.0 | 0.0 | 4.6 |

Restricting to the **single closest** absent category — the one most plausibly one storefront away
from flipping the address:

| closest absent category | n (of 38,733 pc=11 addresses) | share |
|---|---:|---:|
| bar | 5,134 | 13.3% |
| hardware | 4,986 | 12.9% |
| bank | 4,590 | 11.9% |
| clinic | 3,705 | 9.6% |
| childcare | 3,609 | 9.3% |
| cafe_bakery | 3,608 | 9.3% |
| fitness | 3,356 | 8.7% |
| pharmacy | 2,814 | 7.3% |
| convenience | 1,842 | 4.8% |
| laundry | 1,714 | 4.4% |
| grocery | 1,104 | 2.9% |
| nails_beauty | 872 | 2.3% |
| tailor_repair | 839 | 2.2% |
| hair_barber | 560 | 1.4% |

That closest absent category sits at a median 861 m (p10 809, p90 1,055) — i.e. the marginal
address is typically failing the window by 60 m.

**Is childcare disproportionately the marginal 12th?** *Not now — but it was.* On the current
supply childcare is absent for 14.5% of the one-short band against a 7.4% citywide absence rate.
On the **pre-D69** supply it was absent for **29.6%** of that band, second only to
`tailor_repair`/`bank`/`hardware`. The floor-anchor ruling halved it. Geographically the remaining
childcare-marginal addresses are almost entirely outside scope: of the 5,623 pc=11 addresses with
childcare absent, **SI 2,996 (31.4% of SI's one-short band), QN 2,097, BX 295, BK 235, MN 0.**

### 1.4 A design incoherence worth naming

Four of the fifteen categories carry a reach **longer than the gate's window**: `tailor_repair` 960,
`clinic` 960, `hardware` 960, `fitness` 1,200. The gate therefore counts them "absent" at distances
the screen's own reach table calls *present*. This is not a rounding issue: `tailor_repair` is
"absent" for **60.2%** of all NYC addresses and for **93.2%** of the one-short band — it is by a wide
margin the single most binding category in the gate, and it is binding at a distance the project
itself says is acceptable for a tailor. The gate's "present" and the screen's "present" are two
different predicates sharing one word.

Replacing the gate with a 9-of-11 rule over only the categories whose reach ≤ 800 m
(grocery, convenience, pharmacy, laundry, hair_barber, nails_beauty, restaurant, cafe_bakery, bar,
childcare, bank) is internally coherent and barely moves the deliverable
(MN+BK gap set 180,408 vs 176,217, Jaccard **0.9746**) — but it does **not** fix the D69 defect
(§3): it still admits 5,449 crossers citywide.

### 1.5 NTAs where the gate binds

Citywide, the ten NTAs with the most one-short addresses (NTAs with ≥ 500 addresses):

| borough | NTA | addresses | pc=11 | sh11 % | pc=12 | eligible % |
|---|---|---:|---:|---:|---:|---:|
| QN | St. Albans | 11,445 | 1,811 | 15.8 | 3,903 | 68.7 |
| SI | Annadale-Huguenot-Prince's Bay-Woodrow | 10,977 | 1,191 | 10.8 | 603 | 14.1 |
| SI | Great Kills-Eltingville | 15,179 | 1,171 | 7.7 | 2,561 | 34.9 |
| SI | Westerleigh-Castleton Corners | 8,640 | 1,155 | 13.4 | 1,090 | 62.5 |
| BX | Eastchester-Edenwald-Baychester | 6,389 | 1,122 | 17.6 | 1,200 | 66.9 |
| QN | Queens Village | 11,913 | 1,096 | 9.2 | 1,645 | 63.9 |
| QN | Whitestone-Beechhurst | 6,126 | 1,038 | 16.9 | 522 | 45.6 |
| SI | West New Brighton-Silver Lake-Grymes Hill | 7,439 | 1,019 | 13.7 | 656 | 53.6 |
| **BK** | **East New York-New Lots** | **4,782** | **1,004** | **21.0** | **1,402** | **67.9** |
| QN | Murray Hill-Broadway Flushing | 7,424 | 909 | 12.2 | 1,058 | 79.3 |

Inside MN+BK the gate is concentrated in a short, recognisable list — the top fifteen NTAs by
(pc=11 + pc=12):

| borough | NTA | addresses | pc=11 | pc=12 | eligible % |
|---|---|---:|---:|---:|---:|
| BK | East New York-New Lots | 4,782 | 1,004 | 1,402 | 67.9 |
| BK | Canarsie | 11,837 | 355 | 1,497 | 84.0 |
| BK | East New York (North) | 4,637 | 661 | 473 | 67.6 |
| BK | Brownsville | 3,651 | 472 | 626 | 75.0 |
| BK | Cypress Hills | 4,689 | 119 | 770 | 95.2 |
| BK | East New York-City Line | 3,590 | 254 | 569 | 86.9 |
| BK | Marine Park-Mill Basin-Bergen Beach | 10,578 | 552 | 187 | 76.2 |
| BK | East Flatbush-Remsen Village | 3,330 | 222 | 477 | 93.3 |
| BK | Sheepshead Bay-Manhattan Beach-Gerritsen Beach | 8,672 | 281 | 400 | 76.9 |
| BK | Bay Ridge | 9,625 | 108 | 391 | 95.9 |
| BK | Spring Creek-Starrett City | 560 | 175 | 212 | 51.6 |
| BK | Madison | 5,467 | 110 | 256 | 98.0 |
| BK | East Flatbush-Rugby | 5,157 | 49 | 257 | 98.6 |
| BK | Gravesend (West) | 6,668 | 1 | 279 | 100.0 |
| BK | Gravesend (South) | 2,066 | 34 | 243 | 97.6 |

**Threat this raises (M1).** The marginal band is not a random slice of MN+BK. Median tract
household income (`analysis.address_demographics`, no interpolation):

| band | MN+BK addresses | median tract income |
|---|---:|---:|
| pc ≤ 10 | 9,584 | $98,750 |
| pc = 11 | 4,929 | $75,833 |
| pc = 12 | 9,692 | $75,833 |
| pc 13–14 | 109,279 | $77,552 |
| pc = 15 | 148,358 | $90,625 |
| MN+BK overall | 281,842 | $83,083 |

The one-short band sits ~9% below the MN+BK median, and the ineligible-but-not-marginal band
(Marine Park, Manhattan Beach, Bay Ridge fringe) sits 19% *above* it. So the gate's instability is
concentrated in exactly the low-income, thin-feed neighbourhoods where the −0.6 coverage
correlation (M1) is worst. **Gate flips and coverage bias are correlated, not independent** —
any claim that "the gate is small" must be made about the *right* subgroup, not the average.

---

## 2. Sensitivity

### 2.1 Eligibility under each gate

Addresses (and unit shares) passing, by borough. `in_all` variants compute the gate on the
aggregator-inclusive supply and leave the ratios on `in_principled`.

| borough | K=11 | K=12 (base) | K=13 | K=11 in_all | K=12 in_all | K=13 in_all |
|---|---:|---:|---:|---:|---:|---:|
| MN | 32,388 (99.99%) | 32,386 (99.99%) | 32,352 (99.88%) | 32,389 (100.00%) | 32,387 (99.99%) | 32,354 (99.89%) |
| BK | 239,870 (96.16%) | 234,943 (94.18%) | 225,285 (90.31%) | 242,634 (97.27%) | 237,995 (95.41%) | 228,604 (91.64%) |
| BX | 65,428 (86.40%) | 60,768 (80.25%) | 54,210 (71.59%) | 68,431 (90.37%) | 64,194 (84.77%) | 56,997 (75.27%) |
| QN | 243,129 (81.70%) | 223,520 (75.12%) | 188,730 (63.42%) | 251,759 (84.60%) | 235,507 (79.14%) | 204,766 (68.81%) |
| SI | 51,848 (46.21%) | 42,313 (37.71%) | 31,378 (27.97%) | 56,615 (50.46%) | 48,692 (43.40%) | 37,120 (33.08%) |

Unit shares (%):

| borough | K=11 | K=12 | K=13 | K=11 in_all | K=12 in_all | K=13 in_all |
|---|---:|---:|---:|---:|---:|---:|
| MN | 99.86 | 98.98 | 98.27 | 99.96 | 99.02 | 98.37 |
| BK | 97.26 | 95.31 | 92.13 | 98.04 | 96.49 | 93.57 |
| BX | 92.69 | 87.77 | 80.82 | 94.60 | 92.10 | 84.80 |
| QN | 87.54 | 82.49 | 74.49 | 89.94 | 85.69 | 78.72 |
| SI | 48.48 | 39.85 | 30.79 | 53.44 | 46.05 | 35.44 |

### 2.2 The MN+BK gap set (eligible ∧ `gap_score > 1`)

| gate | gap addresses | gap units | Δ vs base | Jaccard vs K=12 |
|---|---:|---:|---:|---:|
| **K=12 (baseline)** | **176,217** | **1,026,726** | — | **1.0000** |
| K=11 | 181,146 | 1,056,905 | +4,929 | 0.9728 |
| K=13 | 166,525 | 984,422 | −9,692 | 0.9450 |
| K=12 on `in_all` | 179,270 | 1,040,277 | +3,053 | 0.9830 |
| K=11 on `in_all` | 183,911 | 1,066,553 | +7,694 | 0.9582 |
| K=13 on `in_all` | 169,846 | 1,001,359 | −6,371 | 0.9602 |

The gate is monotone, so these sets nest and the Jaccard is just the size ratio. All six clear the
D34 stability bar of 0.80 comfortably.

### 2.3 Top-50 MN+BK clusters

Cluster ids are not comparable across gates (they are `{boro}:{cat}:{connected-component index}`),
so the comparison is over the **union of member addresses** of the top 50 clusters. Two rankings are
reported because the choice of ranking is itself load-bearing and has never been settled:
`uc` = summed `units_capped` (the ranking `model/address_gaps.py`'s own summary uses) and
`gs_mean` = cluster mean `gap_score`.

| gate | top-50 Jaccard (rank = capped units) | top-50 Jaccard (rank = mean gap_score) | total MN+BK clusters |
|---|---:|---:|---:|
| K=12 (baseline) | 1.0000 | 1.0000 | 546 |
| K=11 | 0.9794 | 0.9171 | 556 |
| K=13 | 0.9274 | 0.8658 | 535 |
| K=12 on `in_all` | 0.9871 | 0.9369 | 552 |
| K=11 on `in_all` | 0.9562 | **0.3514** | 560 |
| K=13 on `in_all` | 0.9491 | 0.9275 | 540 |

**The `gs_mean` column is the finding.** A units-weighted top-50 is essentially immune to the gate
(≥ 0.93 everywhere). A gap-score-weighted top-50 is not: relaxing to K=11 on `in_all` replaces
**two-thirds** of the top-50's member addresses. The reason is mechanical — ratios are censored at
`cap_m` = 2,400 m, so the highest `gap_score` attainable is 2400/reach, and the addresses that
attain it are precisely the fringe, low-density addresses the gate exists to exclude. Relaxing the
gate hands the top of a gap-score ranking to the fringe.

### 2.4 The window, not just K

`W = 800 m` is as free a parameter as `K = 12` and has never been swept. Holding K = 12:

| window (m) | MN elig % | BK elig % | QN elig % | SI elig % | MN+BK gap addresses | Jaccard vs 800 |
|---:|---:|---:|---:|---:|---:|---:|
| 640 | 99.92 | 85.88 | 57.47 | 22.89 | 155,473 | 0.8823 |
| 720 | 99.95 | 91.09 | 66.85 | 29.94 | 168,478 | 0.9561 |
| **800** | **99.99** | **94.18** | **75.12** | **37.71** | **176,217** | **1.0000** |
| 880 | 99.99 | 95.81 | 81.80 | 45.06 | 180,280 | 0.9775 |
| 960 | 100.00 | 96.93 | 86.79 | 52.38 | 183,079 | 0.9625 |
| 1000 | 100.00 | 97.32 | 88.67 | 55.69 | 184,056 | 0.9574 |

Inside MN+BK the window is a second-order parameter (±20% moves the gap set by 2–12%). Outside it,
the window *is* the answer: Staten Island's eligible share runs 23% → 56% across the same sweep.
Any statement about the gate outside MN+BK is a statement about 800 m, not about 12-of-15.

---

## 3. The D69 mechanism, reconstructed

### 3.1 Method

The pre-D69 childcare supply is exactly reconstructible: the floor-anchor flag suspends only the
lone-aggregator veto, so the pre-ruling set is
`category='childcare' AND in_principled AND (is_corroborated OR has_registry_member)` =
**2,657 POIs**, against 6,066 now — a difference of **3,409**, matching D69's figure to the record.
One Dijkstra pass on that restricted set gives the counterfactual `nearest_m` for childcare; every
other column is held at its live value.

### 3.2 Who crossed

| borough | crossers | units |
|---|---:|---:|
| QN | 4,458 | 6,606 |
| SI | 1,484 | 2,430 |
| BK | **359** | **623** |
| BX | 266 | 1,384 |
| MN | 0 | 0 |
| **total** | **6,567** | **11,043** |

All 6,567 came from `present_count = 11` exactly — as they must, since only one category's
distances moved.

Top NTAs: St. Albans (QN) 857, Queens Village (QN) 551, South Ozone Park (QN) 524, South Jamaica
(QN) 327, Westerleigh-Castleton Corners (SI) 271, Springfield Gardens (North)-Rochdale Village (QN)
238, Great Kills-Eltingville (SI) 210, Baisley Park (QN) 185, Bellerose (QN) 182, Glen
Oaks-Floral Park-New Hyde Park (QN) 177, Howard Beach-Lindenwood (QN) 164,
Sheepshead Bay-Manhattan Beach-Gerritsen Beach (BK) 164.

**Discrepancy with the record, stated plainly.** D69 records eligible rising 587,408 → 593,930. My
reconstruction gives 587,363 → 593,930: the endpoint matches exactly, the starting point is **45
addresses** lower and the crosser count is **6,567, not 6,522**. The childcare floor anchor is
therefore not quite the whole difference between supply `f1b12ab55878` and `06bb6f357cc1`; about
45 addresses (0.7% of the recorded delta) came from something else in that rebuild. The
qualitative conclusion is unaffected; the recorded number should be read as 6,567 ± that residue.

### 3.3 Is the bar-lead increase composed of newly-eligible addresses?

**Partly — and much less than D69 implies.** Two things happened at once, and D69 attributes both
to the gate.

First, a definitional point. D69's "bar-lead gaps 144,731 → 148,221" counts **eligible addresses
whose `lead_category` is bar, with no gap filter**: 148,221 is
`count(* ) FROM analysis.address WHERE eligible AND lead_category='bar'`, which includes 17,329
addresses whose bar ratio is ≤ 1 and which are therefore **not gaps at all**. The gap count on the
project's own definition (eligible ∧ `gap_score > 1`) is **130,892**. The same paragraph then pairs
that inflated address count with a cluster count (240) computed only over gap addresses, because
`cluster_id` is assigned only where `gap_score > 1`. **The headline number and its cluster count do
not describe the same set.** The honest gap-count delta is **+3,267**, not +3,490.

Second, the decomposition. Citywide, `eligible ∧ lead = c` (D69's definition):

| category | lead before | lead after | Δ | from newly-eligible | switched in (already eligible) | switched out | gap count before | gap count after | Δ gap |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| tailor_repair | 152,688 | 158,100 | +5,412 | +1,525 | +3,887 | 0 | 126,426 | 129,794 | +3,368 |
| **bar** | **143,686** | **148,221** | **+4,535** | **+1,832** | **+2,703** | **0** | **127,625** | **130,892** | **+3,267** |
| laundry | 90,056 | 94,110 | +4,054 | +977 | +3,077 | 0 | 67,676 | 69,611 | +1,935 |
| bank | 57,527 | 61,658 | +4,131 | +878 | +3,260 | −7 | 36,496 | 37,755 | +1,259 |
| convenience | 64,629 | 67,026 | +2,397 | +659 | +1,738 | 0 | 42,364 | 43,464 | +1,100 |
| cafe_bakery | 39,248 | 41,367 | +2,119 | +669 | +1,450 | 0 | 31,552 | 32,952 | +1,400 |
| hardware | 7,777 | 8,455 | +678 | +10 | +668 | 0 | 4,686 | 4,704 | +18 |
| **childcare** | **26,668** | **9,289** | **−17,379** | 0 | +7 | **−17,386** | 10,832 | 1,342 | −9,490 |
| clinic | 1,005 | 1,271 | +266 | 0 | +266 | 0 | 433 | 433 | 0 |
| pharmacy | 1,830 | 1,995 | +165 | 0 | +165 | 0 | 170 | 170 | 0 |
| others | — | — | +189 | +17 | +172 | 0 | — | — | +52 |
| **Σ Δ** | | | **+6,567** | **+6,567** | | | | | |

The Σ column is an identity check: the sum of the lead-count changes equals the crosser count
exactly (6,567), because every "switched in" is matched by a "switched out" from childcare.

**So: only 1,832 of bar's +4,535 (40%) — or 1,832 of +3,267 (56%) on the honest gap definition —
is the eligibility gate.** The remaining ~2,700 is a category ordinarily losing the argmax: 3,409
childcare POIs entered, childcare's ratio fell at 17,386 already-eligible addresses, and bar/
tailor/laundry/bank took over as the max-ratio category. **That second mechanism is not a defect.**
It is exactly what a continuous argmax ranking is supposed to do (D41), and D69's framing — "adding
childcare raised every other category's gap count" — reads as if all of it were the gate.

Lead distribution of the 6,567 genuinely gate-driven crossers: bar 1,832, tailor_repair 1,525,
laundry 977, bank 878, cafe_bakery 669, convenience 659, restaurant 17, hardware 10.

### 3.4 The same decomposition inside MN+BK

| category | lead before | lead after | Δ | from newly-eligible | switched in | switched out | Δ gap count |
|---|---:|---:|---:|---:|---:|---:|---:|
| bar | 77,615 | 77,928 | +313 | **+15** | +298 | 0 | +16 |
| tailor_repair | 54,466 | 55,067 | +601 | +178 | +423 | 0 | +180 |
| laundry | 49,524 | 50,375 | +851 | +91 | +760 | 0 | +158 |
| bank | 29,680 | 30,821 | +1,141 | +75 | +1,073 | −7 | +116 |
| convenience | 30,562 | 31,143 | +581 | 0 | +581 | 0 | 0 |
| cafe_bakery | 12,757 | 13,271 | +514 | 0 | +514 | 0 | +246 |
| childcare | 8,286 | 4,125 | −4,161 | 0 | +7 | −4,168 | −664 |

**Inside the screen's actual scope the whole D69 event is 359 addresses (0.13% of MN+BK) carrying
623 units, and bar's gate-driven increase is 15 addresses.** The surprise was an outer-borough
phenomenon reported on a citywide run that D48 says is out of scope.

---

## 4. Re-verifying D51 inside MN+BK

D51 recorded "the fixed 800 m / 12-of-15 gate does no work inside MN+BK (100% MN, 95% BK
eligible)." On the current run:

| borough | addresses | ineligible | % | ineligible units | % of units |
|---|---:|---:|---:|---:|---:|
| MN | 32,390 | **4** | 0.01% | 9,754 | 1.02% |
| BK | 249,452 | **14,509** | 5.82% | 52,295 | 4.69% |

Manhattan's four ineligible addresses sit at `present_count` 7, 9, 11, 11. Brooklyn's 14,509 run
the full range 0–11, with a third of them (4,927) one category short. They concentrate in
Marine Park-Mill Basin-Bergen Beach (2,521), Sheepshead Bay-Manhattan Beach-Gerritsen Beach
(2,004), Canarsie (1,890), East New York-New Lots (1,537), East New York (North) (1,503),
Coney Island-Sea Gate (1,078), Brownsville (912), East New York-City Line (469), Bay Ridge (394).

**All 14,513 MN+BK ineligible addresses have `max ratio > 1`** — every one of them would enter the
gap set the instant the gate were dropped. Their would-be leads: bar 6,401, laundry 3,287,
tailor_repair 1,719, bank 1,591, cafe_bakery 657, convenience 644, nails_beauty 214.

**Does the gate change the MN+BK top-50?** It depends entirely on the ranking, and this is where
D51's summary needs qualifying:

| comparison | gap set | top-50 by capped units | top-50 by mean gap_score |
|---|---:|---:|---:|
| gate ON vs gate entirely OFF | 176,217 vs 190,730 addresses | Jaccard **0.9261** | Jaccard **0.3184** |

**D51's "the gate does no work inside MN+BK" is correct for a units-weighted deliverable and wrong
for a gap-score-weighted one.** Removing the gate replaces two-thirds of a gap-score top-50's member
addresses with Marine Park / Gerritsen Beach / Sea Gate fringe. The gate is doing real work — it is
suppressing the censoring artifact (§2.3) — it simply does not show up in the ranking the project
currently prints.

### 4.1 How much can supply move the gate inside MN+BK? A measured bound.

Rather than argue, I perturbed it. For each category in turn, 10% of its `in_principled` POIs were
dropped at random (numpy PCG64, seed 20260911), the screen recomputed, and two quantities measured
in MN+BK: the total absolute change in **every other category's** gap-address count with eligibility
recomputed, and the same with eligibility **frozen at baseline**. The difference is the leakage
attributable purely to the gate.

| perturbed category | POIs | dropped | MN+BK Δ eligible | other-category Δ (gate live) | other-category Δ (gate frozen) | **leakage from the gate** |
|---|---:|---:|---:|---:|---:|---:|
| clinic | 8,097 | 810 | −243 | 243 | 0 | **243** |
| hardware | 2,765 | 264 | −230 | 230 | 0 | **230** |
| fitness | 10,416 | 1,001 | −226 | 226 | 0 | **226** |
| cafe_bakery | 8,038 | 795 | −289 | 1,731 | 1,543 | 188 |
| pharmacy | 5,536 | 565 | −144 | 265 | 121 | 144 |
| hair_barber | 15,601 | 1,484 | −145 | 152 | 8 | 144 |
| nails_beauty | 9,412 | 940 | −139 | 298 | 159 | 139 |
| laundry | 4,979 | 516 | −209 | 2,765 | 2,636 | 129 |
| tailor_repair | 966 | 95 | −107 | 1,009 | 902 | 107 |
| childcare | 6,066 | 621 | −65 | 79 | 14 | 65 |
| convenience | 4,740 | 466 | −55 | 878 | 848 | 30 |
| bar | 5,011 | 528 | −353 | 2,988 | 2,971 | 17 |
| grocery | 15,504 | 1,558 | −11 | 11 | 0 | 11 |
| bank | 5,222 | 525 | 0 | 2,840 | 2,840 | 0 |
| restaurant | 39,459 | 3,908 | 0 | 0 | 0 | 0 |

Two readings:

1. **The bound is small.** Worst case, a 10% supply shock in one category moves **243** other-category
   gap addresses through the gate — 0.14% of the 176,217 MN+BK gap set. D51's "does no work" is
   defensible as a *magnitude* claim inside MN+BK, and can now be quoted as a number rather than an
   impression.
2. **Four categories enter the screen through the gate and nowhere else.** `clinic`, `fitness`,
   `hardware` and (nearly) `grocery` have **zero** gate-frozen effect — they are essentially never
   the argmax lead — yet they move the gate by 226–243 addresses each. Their entire contribution to
   the deliverable is noise injected through a threshold. Three of the four are the long-reach
   categories from §1.4.

---

## 5. The principled question

The property D69 violated has a name. Call it **cross-category supply invariance**: *changing the
supply of category c must not change the gap count of any category c′ ≠ c, except through the
argmax.* The current design fails it, because eligibility is a function of all fifteen categories'
supply and eligibility gates every category's gap.

Note what does **not** distinguish the four options: all four are reach-independent, so all four
preserve D39's monotonicity-in-reach. That constraint is not in play.

### (a) Re-derive every run from live supply — the status quo

*Fixes:* nothing. It is the thing being questioned.
*Breaks:* cross-category supply invariance. Every future ingestion is a D69 — and the next one is
already scheduled (the DCWP laundry merge, CHECKPOINT next action #8). The perturbation table puts
that at ≤ 243 MN+BK addresses per shock, so it is survivable; it is also unexplainable to an
outside reader, which is the actual cost.
*Keeps:* reproducibility (the run is a pure function of its inputs, and `supply_hash` already
stamps them), city-agnosticism, present-day semantics.

### (b) Freeze eligibility per supply-set baseline

*Fixes:* cross-category supply invariance, exactly and by construction. Leakage = 0.
*Breaks:* the screen's meaning. Loci is a **present-day** investment screen. Under (b) a lot that
was ineligible in September 2026 stays ineligible after a real supermarket opens across the
street — eligibility becomes a function of run *history*, not of the city. It also introduces a
new un-derived parameter (when do you re-freeze?) and a baseline artifact that must be versioned,
shipped and reasoned about per city. **Reject.** The cure is worse than D69.

### (c) Compute the gate on `in_all`

*Fixes:* the entire class of events D69 belongs to — **rule** changes. Childcare's `in_all` count
was 6,066 before and after the floor-anchor ruling, so under an `in_all` gate the D69 event would
have moved **0 addresses instead of 6,567**, by arithmetic, not by estimate. It also separates two
questions that should be separate: "is this a retail environment" (coarse) and "is this business
real enough to count as supply" (fine). It is a one-predicate change.
*Breaks:* not the D69 class, but not the general problem either — an actual **ingestion** still
moves the gate, because `in_all` grows when a feed lands. It also grounds the gate on the dirtiest
available supply: an address becomes "an urban retail environment" because Overture carries four
stale listings. That is the M1 coverage-bias channel wired directly into the gate, in the same
low-income neighbourhoods §1.5 identified.
*Cost to the deliverable:* small. MN+BK gap set 179,270 vs 176,217 (Jaccard 0.9830); top-50 Jaccard
0.9871 by units, 0.9369 by mean gap score.

### (d) A POI-free density / land-use gate

*Fixes:* cross-category supply invariance **and** ingestion invariance, permanently. The gate stops
being a function of the thing the screen measures, which is the only structural cure. It also
removes the §1.4 incoherence and the §4.1 finding that clinic/fitness/hardware affect the
deliverable only through a threshold.
*Breaks:* it is a genuinely different gate, not a refactor — see below. It needs a threshold, and
that threshold must be derived, not chosen. PLUTO `retailarea` / `commfar` are NYC fields, though
"retail floor area within 800 m" is a city-agnostic *form*; a new city needs an equivalent
land-use layer, which is a real portability cost.

Four POI-free candidates, all computed on a 100 m raster with an 800 m disc kernel (PLUTO,
857,347 lots). "Threshold" is the value maximising agreement with the current gate — reported to
size the difference, **not** proposed as a derivation, since calibrating a replacement against the
thing it replaces is circular:

| candidate gate | AUC vs current gate (citywide) | AUC (MN+BK) | agreement | MN elig % | BK % | QN % | SI % | MN+BK gap set | Jaccard vs current |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| retail floor area within 800 m | **0.9123** | 0.8876 | 87.6% | 100.0 | 97.7 | 81.4 | 48.5 | 184,915 | 0.9391 |
| commercially-zoned lots within 800 m | 0.8857 | 0.7705 | 85.4% | 100.0 | 96.7 | 78.8 | 52.7 | 182,545 | 0.9360 |
| commercial floor area within 800 m | 0.8728 | 0.8060 | 84.7% | 100.0 | 97.9 | 81.3 | 45.4 | 185,393 | 0.9339 |
| residential units within 800 m | 0.8871 | 0.8668 | 84.0% | 100.0 | 98.3 | 81.2 | 36.7 | 186,385 | 0.9404 |

A **threshold-free** version — "≥ 1 commercially-zoned or commercial-overlay lot within 800 m" —
was tested and **fails**: it passes 100.0% of MN, 99.99% of BK, 99.71% of QN and 97.95% of SI. NYC
zones commercial overlays nearly everywhere; the binary land-use fact is not a gate. A threshold is
unavoidable.

Citywide agreement with the current gate is only 84–88%. For the units-within-800 m variant at its
best-agreeing threshold the disagreement is 78,994 addresses the POI gate rejects and the density
gate accepts, against 43,688 the reverse; for the retail-floor-area variant inside MN+BK it is
10,022 against 1,358 (§6). **Option (d) is a change of rule, not a refactor**, and must be justified
against evidence rather than against the incumbent.

---

## 6. The evidence that decides between (c) and (d)

Neither gate has ever been validated against anything. There is, however, an independent measure
already in the warehouse that neither gate uses: the **DOF Storefront Registry** (D67,
`analysis.address.storefronts_400m`) — a Local Law 157 filing register of actual ground-floor
storefronts, populated for MN+BK (100% coverage; 0% outside, so this test runs only in scope).

Scoring each candidate gate's underlying statistic against "≥ 1 registered storefront within 400 m"
(base rate 93.6% of MN+BK addresses):

| gate statistic | AUC vs "≥ 1 registered storefront within 400 m" | Spearman vs storefront count within 400 m |
|---|---:|---:|
| `present_count` (the current POI gate) | 0.8559 | 0.5657 |
| residential units within 800 m | 0.8587 | 0.6648 |
| **retail floor area within 800 m** | **0.8729** | **0.7238** |

And the disputed cells — MN+BK addresses where the two gates disagree, scored by the register:

| POI gate | retail-sqft gate | addresses | mean registered storefronts within 400 m | share with ≥ 1 |
|---|---|---:|---:|---:|
| pass | pass | 265,971 | 51.64 | 96% |
| **fail** | **pass** | **10,022** | **4.68** | **64%** |
| **pass** | **fail** | **1,358** | **1.47** | **45%** |
| fail | fail | 4,491 | 0.65 | 23% |

**The POI gate is wrong on both sides of the disagreement, and worse on the exclusion side.** The
10,022 MN+BK addresses it excludes and a built-form gate admits have, on average, nearly five
registered storefronts within 400 m and a 64% chance of at least one — these are real retail
environments. The 1,358 it admits and the built-form gate rejects have 1.47 and 45%. This is not a
tie; it is the incumbent losing the only external test available.

**Caveats that survive this result.** The register is self-reported, non-filers are invisible, Tax
Class 1 is 0.27% of MN+BK rows so rowhouse corner stores are under-covered (D67), and "storefront
within 400 m" is correlated with POI density by construction — it is *independent of the feeds*,
not independent of the phenomenon. It is the best available criterion, not ground truth, and it
cannot be run outside MN+BK until the register is extended.

---

## 7. Recommendation

**Adopt (d) — replace the 12-of-15 POI gate with a POI-free built-form gate (PLUTO retail floor
area within a fixed 800 m), because it is the only option that makes the gate structurally immune
to the supply it screens and the only one that beats the incumbent on the single external
criterion available (AUC 0.873 vs 0.856; Spearman 0.724 vs 0.566 against the DOF Storefront
Registry), and ship (c) — the gate on `in_all` — in the meantime, since it costs one predicate,
would have reduced the D69 event from 6,567 addresses to exactly 0, and moves the MN+BK
deliverable by less than 2% (gap-set Jaccard 0.983, top-50 by units 0.987).** Reject (b): freezing
eligibility makes a present-day screen depend on run history, so a lot stays ineligible after a real
supermarket opens, and reject (a) as the status quo that produced D69.

### The settling test

Two gates, one pre-registered battery, run before the swap. A replacement is adopted only if it
wins all four.

1. **Cross-category leakage (the D69 property).** Re-run §4.1: drop ε = 10% of each category's
   POIs at random under a fixed seed, recompute, and measure the change in every *other* category's
   MN+BK gap-address count with eligibility recomputed minus the same with eligibility frozen.
   *Null:* leakage = 0. *Current gate:* max 243 addresses (clinic). *Kills option (c):* if leakage
   under `in_all` is not materially below the 243 baseline, (c) buys nothing but a one-off
   immunity to rule changes and should not be shipped. *Option (d) passes by construction* — and
   that must be *verified*, not assumed, since a land-use gate that accidentally reads a POI table
   would fail silently.
2. **External criterion, held out.** Split MN+BK 50/50 by NTA (not by address — the addresses are
   spatially autocorrelated and a random split would leak). Fit nothing on the holdout; compare
   `present_count` against the candidate statistic on AUC and Spearman versus
   `storefronts_400m`, with **Conley or NTA-clustered standard errors** on the AUC difference,
   because 281,842 addresses sit in ~200 neighbourhoods and the naive n is off by three orders of
   magnitude. *Kills (d):* if the AUC gap (currently +0.017) does not exclude zero with clustered
   SEs on held-out NTAs, the incumbent stands — 0.017 is small and I have not yet put an interval
   on it.
3. **Threshold derivation, not calibration.** The retail-floor-area threshold must be derived from
   something external — a cited minimum viable retail cluster size, or a change-point in the
   storefront-register relationship estimated on the training NTAs — and then *held fixed* for the
   holdout. *Kills (d):* if no derivation survives that is not "the value that best reproduces
   the old gate," the threshold is hand-picked and the option fails the owner's own rule.
4. **Deliverable stability, reported not required.** MN+BK gap-set Jaccard and top-50 cluster
   member-address Jaccard under **both** rankings (capped units and mean gap score). A large change
   is not disqualifying — the whole point is that the old gate may be wrong — but it must be
   reported, and the `gs_mean` column must be shown, because §2.3 and §4 establish that it is the
   ranking the gate actually governs.

### Two fixes that are independent of which option wins

- **Stop publishing "lead gaps" as a count that includes non-gaps.** §3.3: D69's 148,221 counts
  17,329 addresses whose lead ratio is ≤ 1, and pairs that count with a cluster count computed
  only over `gap_score > 1`. One definition, used everywhere: eligible ∧ `gap_score > 1`.
- **Settle the cluster ranking before the gate.** The gate's importance ranges from
  Jaccard 0.93 to 0.32 depending purely on whether clusters are ranked by capped units or by mean
  gap score (§4). Which of those is the deliverable is a larger open question than the gate itself,
  and the `cap_m` = 2,400 m censoring makes the gap-score ranking partly a sort of the reach table
  (D51). Resolve that first; the gate decision reads differently under each.
