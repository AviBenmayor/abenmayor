# Loci — Research Questions

**The build compass.** Every question below carries exactly one lifecycle state:

- **`open`** — no answer yet, or the answer is still partial/in-progress. Full content kept.
- **`answered`** — the question has a real answer; cites the CHECKPOINT decision (D-id),
  commit, or ticket that answered it. Reduced to title + the answering citation — the
  reasoning that produced the answer stays in CHECKPOINT's decision log / commit history,
  not duplicated here.
- **`dropped`** — out of scope per the SCOPE CORRECTION section of CHECKPOINT.md, or made
  moot by a later decision. Reduced to title + what dropped it.

This is a restructure only (2026-09-15): every entry below is unchanged in substance from
the previous version of this file, just re-sectioned by state and — where an entry's own
prose already recorded a clear answer or ruling that its `Status:` field hadn't caught up
to — reclassified to match. `loci check-questions` still parses every `### ID — text`
block wherever it lives in the file, so IDs and anchors are untouched: existing links keep
working.

Two lists live inside **Open**, kept separate as before:

- **Part A — questions the project answers.** Tiered by how much each can honestly claim:
  Measurement → Descriptive → Explanatory → Predictive → Causal. The charter's three
  falsifiable predictions (CONTEXT.md §1.4, P1–P3) are *evidence* for questions here, not
  questions themselves.
- **Part B — homework.** Things the owner must read up on or probe before building. Most are
  30-minute checks; they are deliberately **not** Linear tickets.

This file changes faster than `CONTEXT.md` (the charter) and slower than `CHECKPOINT.md`
(the state). Decisions still go in CONTEXT.md §9 and the CHECKPOINT decision log — this file
holds *questions* and their current answers only.

**Machine-checked.** `loci check-questions` asserts every ticket title cited in *Answered by*
exists in `src/loci/tickets.py`, every epic cited in *Unblocks* exists, every status is in the
vocabulary, and each of P1, P2, P3 is claimed by at least one question. Run it with
`make check`.

**Status vocabulary:** the validator still accepts the legacy five-value set
(`open` · `in-progress` · `answered` · `deferred` · `dropped`) for compatibility, but as of
this restructuring every entry in this file uses only the three states above — `in-progress`
entries were folded into `open` (still active, just not finished) and `deferred` entries
(C1–C3, Tier C · Causal, parked at Phase 5) were folded into `open` too, since Phase 5 is a
real future phase, not an abandonment. See the Dropped section's note for the judgment calls
left open on purpose.

---

## Open

Full content, unchanged from the previous version of this file, minus the entries moved
to Answered below.

## Stopping rule

**None.** A defensible DNCI map plus residual map ships regardless of how P1, P2 and P3 come
out — a null on the growth test is a real answer and still a publishable map.

One condition attached. If **M1** fails — the POI undercount concentrates in the very hexes
flagged as underserved — the *descriptive* map is contaminated in the same hexes, not just
the predictive claims. What survives is the food tier (DOHMH is a near-census) and any stratum
the Google sample validates. In that case the map ships restricted to those, and says so.

---

### Prioritised (P1 / P2)

#### Part A research

### M13 — What share of NYC storefront closures does each source ascertain (Foursquare ~3%?, DOHMH absence, LL157 vacancy, Google Places Insights), and can an ascertainment-weighted hazard model recover a survival curve?
- **Status:** open
- **Answered by:** `Survival outcome: model Foursquare closure ascertainment and build the pre-2026 historical closure panel` — GTM-161
- **Tier:** P1 — M13 survival gate
- **Why it matters:** D88's retrodiction found Foursquare's unfiltered closure re-pull ascertains only ~3% of the true two-year food-service closure rate, and categorically non-random (a bar closing is announced, a tailor closing is not). Without an ascertainment model per category, no hazard curve fitted on any current source can be trusted, and the business-level survival question stays permanently untested rather than answered null.
- **Fails if:** ascertainment cannot be estimated per category against the LL157 go-dark base rate (8.4% strict / 28% with attrition) and DOHMH absence with usable precision, and Google Places Insights (GTM-159) does not materially improve coverage — in which case business-level survival stays out of reach until a new source lands.
- **Current answer:** Open, ticketed GTM-161.

### D24 — Should unresolved co-located POI pairs from the closure gate collapse, or count as-is?
- **Status:** answered
- **Answered by:** `Owner ruling + implementation: unresolved co-located POI pairs collapse or count (QUESTIONS D24)`
- **Tier:** P1 — decision value for AC-1
- **Why it matters:** the co-location closure gate (commit a67f03e) flags 2,527 groups / 7,597 POIs as unresolved rather than collapsing them; collapsing would remove 4,270 more POIs from the supply set. The default is OFF (count as-is), which is conservative for supply counts but leaves a known duplication risk uncorrected wherever a group really is one business under two records.
- **Fails if:** n/a — data-quality/method question; but leaving this open indefinitely means every supply-based count downstream carries an unquantified, undecided bias in one direction.
- **Current answer:** Answered 2026-09-21/22 (owner ruling, CHECKPOINT D132, GTM-202): an unresolved co-located pair collapses to its one positively-open (else lowest-poi_id) survivor by default, EXCEPT a group above `SINK_GROUP_SIZE` (5) members — a documented geocode-sink exception (Penn Station/JFK/Port Authority, 36–72 members) that counts as-is and is not routed to a paid closure check. Code landed in `score/supply.py` 2026-09-21; the live warehouse re-run that actually moves `supply_hash` landed 2026-09-22 (CHECKPOINT D134): `ed55301203a4` → `1898163ac8ce`, gated supply 133,356 → 130,536 (−2,820, −2.11%), full canonical order re-run end to end.

### T10 — Which government feeds would make the 10 filing-blind categories visible (NYS DOS professions, OCFS childcare, DOH clinics, DCWP laundry mapping), and at what lead time?
- **Status:** open
- **Answered by:** `Government-feed anchor for filing-blind amenity categories (QUESTIONS T10)`
- **Tier:** P1 — decision value for AC-1
- **Why it matters:** D80's `openings_pipeline_400m` reads structurally zero for laundry, hair, nails, childcare, clinic, fitness, bank, hardware, convenience, and tailor — not because nothing is opening in those trades, but because they are licensed by NYS DOS or NYS Education Department, or not licensed at all, and no DOB feed carries a trade field that would attribute a filing to one of them. Left unaddressed, a zero pipeline count in these categories risks being misread as "nothing coming" on the recommend card, when it is actually "not tracked."
- **Fails if:** the candidate feeds (NYS DOS licensed professions, NYS OCFS childcare licenses, DOH Article 28 clinics, DCWP laundry — already ingested but currently unmapped to a category) either don't exist in bulk-downloadable form, don't carry a usable address/BBL, or arrive with a lead time too short to matter (e.g. the license is issued at or after opening, not before it).
- **Current answer:** Open, ticketed GTM-152.

### T12 — Do planners confirm the legality-vs-herding reading on the ground (Packet A), and does the 20-lot overlay threshold survive the ten held-out corridors (Packet B)?
- **Status:** open
- **Answered by:** (not ticketed) — GTM-165
- **Tier:** P1 — decision value
- **Why it matters:** T11/D88 found the screen ranks retail streets, and the D92 legality addendum found that reading survives controlling for present-day legal-capacity — but "survives a regression" and "matches what someone who knows the block sees" are different tests. Packet A asks a planner whether openings clustering into already-thick supply reads as demand herding or as the geometry of where retail is legal and re-lettable, on streets they know. Packet B asks whether the COMMERCIAL_OVERLAY_MIN_LOTS=20 threshold (D82) — tuned on the same corridors it was later checked against — holds on ten it never saw.
- **Fails if:** a planner reviewer says the legality-vs-herding reading does not match a corridor they know (send both packets to at least two reviewer types per docs/planner-review.md §5, contrast a broker's read against a planner's), or the 20-lot threshold flips sign or coverage badly on the held-out corridors — either result changes a rule, not just an answer, and lands in the CHECKPOINT decision log per docs/planner-review.md §4.
- **Current answer:** Open. Packets are send-ready in docs/planner-packets-2026-09.md; ticketed GTM-165 (ticket c).

### O1 — Where is there unmet demand for a premium destination amenity (padel, spa)? · *predictive screen*
- **Status:** open
- **Prediction:** —
- **Answered by:** `Premium opportunity score + ranked site list` · `Travel-time catchment engine (drive + transit isochrones)` · `Premium demand pool per catchment`
- **Tier:** P1 — decision value for AC-1
- **Fails if:** the ranked site list reshuffles materially across 10/15/20/30-minute catchments — then "opportunity" is an artifact of the willingness-to-travel assumption, which is the load-bearing parameter of the whole axis (it inverts the walkable gap screen precisely because people travel for these). Report the ranking under the catchment sweep, never a single radius.
- **Current answer:** —

### O2 — Is a premium-amenity "gap" real, or a supply-coverage artifact (worse than M1)? · *measurement*
- **Status:** open
- **Prediction:** —
- **Answered by:** `Ingest premium-amenity supply + Google-validate (mandatory here)`
- **Tier:** P1 — decision value for AC-1
- **Fails if:** Google + a manual web check finds the amenity already present within the candidate's catchment. This threat is *sharper* than M1: padel barely existed before 2022 and boutique studios open fast, so OSM/Foursquare snapshots undercount them severely and unevenly — a padel "gap" is more likely a data hole than a daily-needs gap is.
- **Current answer:** **Confirmed, and for padel it's total.** 2026-09-02 Google validation (8 budget-charged calls, `src/loci/validation/google_places.py`): **PADEL — Foursquare 0 vs Google 22 real named venues** (Padel Haus Williamsburg/Greenpoint/Dumbo, Reserve Padel Hudson Yards/UES, Court 16 LIC) — a 100% coverage artifact, so padel CANNOT be screened from OSM/Foursquare and its supply must come from Google/manual. The existing venues cluster in the exact high-demand NTAs the model flagged, so the demand model validates but the top cores are already served — the real padel opportunity is the demand-rich + buildable + not-yet-served set (e.g. Sunnyside: 241 large-format sites, no venue found). SPA and PILATES: Google returns ≥20 (API cap) at every top candidate, so those are NOT coverage holes and the Foursquare counts are trustworthy there. Next: subtract the Google-found padel venues from the padel opportunity map (feeds GTM-75); run the stratified premium validation before publishing any site list.

### D3 — How sensitive is the completeness picture to walk threshold and tier weights?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Run 5/10/15-minute threshold sweep` · `Tier-weight sensitivity analysis`
- **Tier:** P2 — cost of search
- **Fails if:** the bottom decile of hexes reshuffles substantially between 5/10/15 minutes or across plausible reweightings — then "underserved" is an artifact of parameter choice.
- **Current answer:** **Partially answered — Manhattan only.** 2026-09-03 (`d3_manhattan_walk_threshold.py`, read-only; CHECKPOINT D31). It fails: not just a reshuffle but a category-mix flip.

  | Walk window | Eligible hexes | Gap hexes | Lead categories |
  |---|---|---|---|
  | 10 min (gate fixed) | 419 | 9 | mixed, no single dominant type |
  | 5 min (gate recomputed) | 371 | 19 | convenience (16), hair_barber (3) |
  | 5 min (gate held fixed) | 419 | 53 | upper bound, noisier |

  At 5 minutes, hardware/pharmacy/clinic/bank vanish as gap types (their 400m prevalence drops below
  the 0.80 expected bar) and convenience/hair_barber dominate instead, concentrated in
  superblock/institutional footprints (FiDi, Lincoln Square, Morningside Heights, Turtle Bay). Not
  yet run for Brooklyn/Queens/Bronx/Staten Island or the 15-minute end of the sweep. Motivates D6/D7
  (per-category, density-class thresholds) as the next-session focus.

  **2026-09-03:** this 10-vs-5 comparison is what revealed that the "missing" rule itself violates
  monotonicity (a gap at 10 min must survive at 5 min, and here it didn't) — see D6, now rewritten
  around that finding, and CHECKPOINT D33. D3 is superseded in spirit by D6: the open question is no
  longer "how sensitive is completeness to one shared threshold" but "the shared threshold was never
  well-defined." Status left as-is below pending the reach-based rebuild.

### D13 — Which additional daily-needs categories belong in the screen, in what order, and which are too discretionary or too car-dependent to include?
- **Status:** open
- **Answered by:** (not ticketed in Linear yet) — milestone E10 Category Expansion generated 2026-09-09 via loci gen-tickets, pending owner review (D55)
- **Tier:** P2 — product surface
- **Tag:** *scope / categories*
- **Why it matters:** The 15 categories were chosen before the address screen existed; the co-location regression shows hair↔nails behave as one amenity, while liquor stores, dentists, vets, shipping, specialty food and dollar stores are absent from the list yet common on walkable blocks. Expanding the bundle affects the gap prevalence thresholds and resets every supply-set validation.
- **Current answer:** Planning agent's proposal (scratchpad category_expansion_plan.md) and tickets under a new milestone, pending owner review.

### D19 — Should `chains.loci_category` feed the `loci recommend` card as a "brand X opening nearby" line, and is that context or evidence?
- **Status:** open
- **Answered by:** (not ticketed) — GTM-148
- **Tier:** P2 — product surface
- **Why it matters:** The chains watchlist (D77, GTM-148) identifies growing brands and where they already operate; a "brand X opening nearby" line would be the most legible single fact on a recommend card. But the same mistake that foot-traffic proxies avoided (D76) is available here too: a chain's siting decision could be read as demand evidence when it may just be the chain's own real-estate strategy (lease terms, a corporate rollout schedule) — closer to the age-fit "supply-revealed" caveat than to an independent demand signal.
- **Fails if:** the line is added as a load-bearing grade section before the chains watchlist has a growth measure (a snapshot delta, per D77) to point to — a raw brand-count with no trend is exactly the "context, not evidence" mistake D76 was written to prevent.
- **Current answer:** Open; decide only after the 2026-10 chains snapshot exists (D77 next action).

### D58 — Will DOF release usable LL157 storefront-registry rent and lease fields at premises grain?
- **Status:** open
- **Prediction:** —
- **Answered by:** `File FOIL for LL157 storefront-registry rent and lease fields (D126)`
- **Tier:** P2 — product surface / AC-2
- **Why it matters:** LL157 requires collection of lease terms and average monthly rent per square foot, but its public-data clause names address/vacancy search and aggregate reporting, not raw premises-grain rent disclosure. A usable response is the only identified flip condition for the parked tenant-side product idea.
- **How to answer:** File the drafted FOIL; if premises-grain fields are withheld, request the tiered aggregate fallback and record the precise statutory basis for denial.
- **Fails if:** DOF withholds the fields, releases only aggregates, or produces records too redacted, stale, or non-addressable for the stated question.
- **Current answer:** FOIL drafted; no response yet (D126).

### O12 — Does asking rent and lease term actually disclose on a phone call for a representative sample of vacant storefronts?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not yet ticketed) — corridor interview test
- **Tier:** P2 — opportunity evidence
- **Why it matters:** This is the crux of the investor/contrarian split: whether observed opacity is a tenant-facing gap or an artifact of automated listing fetches being blocked when a human caller would get the terms.
- **How to answer:** Run the pre-registered 100-address corridor test from memo §8.2, call every contact under two randomized personas, and score disclosure within 48 hours against the declared ≥70%, <40%, and ≥25-point thresholds.
- **Fails if:** calls disclose terms consistently enough that the supposed opacity is only an online-display problem.
- **Current answer:** Not tested; parked under D126.

### O13 — Will brokers or tenant representatives pay for, refer, or reliably use a rent-and-terms intelligence product?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not yet ticketed) — broker willingness-to-pay interviews
- **Tier:** P2 — opportunity evidence
- **Why it matters:** Broker-led workflows may be the viable distribution channel, but no willingness-to-pay, referral, or workflow evidence has been collected.
- **How to answer:** Complete AC-2 discovery calls with one tenant-rep broker, one lender or feasibility shop, and one 3–30-unit operator, recording the artifact shown, price named, and stated willingness to pay.
- **Fails if:** brokers regard the information as non-actionable, already available through relationships, or not worth a paid workflow.
- **Current answer:** Not tested; parked under D126.

### O14 — Does a landlord-acceptance signal predict which vacant storefronts a small operator can actually enter?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not yet ticketed) — landlord-acceptance validation
- **Tier:** P2 — opportunity evidence
- **Why it matters:** If landlord acceptance rather than discovery is the binding constraint, any future dossier would need to lead with an acceptance signal rather than a decodability score.
- **How to answer:** Cross storefront-tenure, licence-event turnover, and months-vacant history against the corridor test's observed outcomes: shown space versus flat rejection.
- **Fails if:** the proposed signals do not separate spaces that a small operator can access from those they cannot.
- **Current answer:** Not tested; parked under D126.

### M16 — What share of tenant-relevant commercial inventory is absent, duplicate, or stale across public listing channels?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not yet ticketed) — listing-coverage audit
- **Tier:** P2 — measurement
- **Why it matters:** The research identifies unlisted and stale inventory as a possible gap, but its size and persistence have not been measured against a defined ground truth.
- **How to answer:** Sample at least 200 LL157 flips or closure-triangulation addresses, check the four largest marketplaces plus a walk-by, and compute a like-for-like coverage ratio and days-on-market distribution.
- **Fails if:** a repeatable audit finds public channels sufficiently complete and current for the target corridors.
- **Current answer:** Not measured; parked under D126.

### T14 — Does the proposed commercial-tenant disclosure legislation advance, change materially, or become law?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not yet ticketed) — legislative status check
- **Tier:** P2 — temporal / policy context
- **Why it matters:** Int 0090-2026 was laid over in committee on 2026-09-16; if enacted, it would require landlord-to-prospective-tenant disclosures, changing the private-information baseline without creating a public rent database.
- **How to answer:** Periodically check NYC Council Legistar and NYS Senate trackers for Int 0090-2026, successors to Int 0568-2024, S9823/S1451A, or an NYC/NYS vacancy tax.
- **Fails if:** the bill is enacted with no material disclosure duty, or the claim is left unmonitored while the bill changes.
- **Current answer:** Proposed only; not law (D126 research).

### T15 — Does Int 0090-2026 alter the claim that no jurisdiction currently requires storefront lease disclosure?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not yet ticketed) — legislative interpretation check
- **Tier:** P2 — temporal / policy context
- **Why it matters:** The bill is a material caveat: it proposes prospective-tenant disclosure by landlords, but it was laid over and does not require public premises-grain rent publication.
- **How to answer:** Re-read the enacted text and committee status at each legislative movement; distinguish private disclosure to a prospective tenant from public posting or premises-grain data release.
- **Fails if:** the claim omits the proposal or overstates an unenacted bill as current law.
- **Current answer:** The claim stands only with this caveat; bill not enacted (D126 research).

### X10 — Which of the NYC carrying-capacity parameters replicate in Chicago / LA / Philadelphia on CBP alone (the CBP↔POI ratio, the grocery flattening point, the accelerating categories)?
- **Status:** open
- **Answered by:** (not ticketed) — GTM-164
- **Tier:** P2 — product surface
- **Why it matters:** docs/carrying-capacity-2026-09.md (D93) fits the NYC curve on Loci's own POIs, overlapping 400 m walksheds; every calibrated constant in it is NYC-fitted, and D93's portability claim — that the CBP-to-POI ratio, not the raw curve, is what travels — has never been checked against a second city's own CBP data. Chicago, Philadelphia and LA are the nearest metros to NYC by dense population and the candidates for the first check.
- **Fails if:** a closed-catchment (NTA/CD-partition) refit of the gated forms does not survive at all, in which case there is no NYC parameter stable enough to even ask the portability question of; or, if it does survive, the CBP-only replication in a second city returns a ratio or flattening point far outside the NYC range, in which case the curve is NYC-specific and only the METHOD (gate, fit form, closed-catchment design) travels, not the numbers.
- **Current answer:** Open, ticketed GTM-164 (ticket b). Blocked on the closed-catchment refit (same ticket) — the open-shed fit cannot itself be handed to a second city as the number to reproduce.

### C3 — Does the pattern generalize beyond NYC?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Extract universal interface; run a second city`
- **Tier:** P2 — product surface
- **Fails if:** the universal-source-only run on a second city produces a residual distribution with no usable spread, or the NYC-only controls (PLUTO zoning) turn out to be load-bearing with no national analogue.
- **Current answer:** Phase 5.

### O6 — Will a new store in a gap hex push both itself and its nearest neighbor below break-even? · *risk / feasibility*
- **Status:** open
- **Prediction:** —
- **Answered by:** — (not yet ticketed; scope decision pending owner + investor-agent review before it enters Axis 1 investability)
- **Tier:** P2 — decision value / AC-4
- **Fails if:** n/a — risk/feasibility question, not a screen result to validate. The concern: filling a gap hex could cannibalize a neighboring store rather than create net new viable retail.
- **Current answer:** Open, sketch only (2026-09-03). Nearest-store catchment assignment over hexes already exists; missing pieces are a category-specific minimum viable catchment population (candidate sources: County Business Patterns receipts per establishment, or SNAP redemption per store) and a rule — qualify a gap only if the new store's own catchment clears the minimum AND no neighbor drops below it after entry. Belongs in **Axis 1 investability**, not the gap screen itself. Flagged explicitly as a scope-creep risk; needs investor-agent review of the framing before any build. 2026-09-05: the address screen's leads are dominated by the thinnest category (tailor); a supply-floor or viability filter on lead eligibility is now needed for the screen itself, not only for Axis 1 (CHECKPOINT D44).

### O7 — Fair-value rent for a storefront at a given site. · *pricing / feasibility*
- **Status:** open
- **Prediction:** —
- **Answered by:** — (not yet ticketed; scope decision pending owner + investor-agent review before it enters Axis 1 investability)
- **Tier:** P2 — decision value / AC-4
- **Fails if:** n/a — pricing/feasibility question, not a screen result to validate.
- **Current answer:** Open, sketch only (2026-09-03). Given a site (hex + category), what rent can a new store of that category bear, and how does it compare to asking rent? Sketch: bearable rent = expected revenue × a category-specific sustainable occupancy-cost ratio (retail rule of thumb ~6–10% of sales, restaurants ~8–12%), minus amortized startup cost. Expected revenue comes from O6 (catchment population × per-capita category spend), so O6 is a prerequisite. Fair-value spread = bearable rent − asking rent; positive spread is the opportunity signal. Data candidates: NYC Storefront Registry (DOF, Local Law 157 of 2019 — vacant storefront filings, public), Manhattan Commercial Rent Tax filings (below 96th St only), listing scrapes (LoopNet/StreetEasy commercial; thin and biased). Threats to validity: asking rents are observed mostly on vacant storefronts, which are vacant for a reason (selection bias); occupancy-cost ratios are national rules of thumb, not NYC-calibrated; startup cost varies more by operator than by site. Belongs to **Axis 1 investability** (cross-ref O6). Scope-creep risk flagged: this is a pricing model, not a gap screen — keep it a downstream gate on already-flagged sites, never a citywide ranking. Investor-agent review of framing required before any build.

### O11 — Which buyer segment pays first for an honesty-graded screen — brokers, lenders, or BIDs — and at what seat price? · *strategy / go-to-market*
- **Status:** open
- **Prediction:** —
- **Answered by:** — (not ticketed; the answer comes from the first three customer conversations, which docs/GTM.md (D87) says have not happened)
- **Tier:** P2 — product surface
- **Fails if:** n/a — go-to-market question, not a screen result to validate.
- **Current answer:** — (Open. The GTM memo (D87) ranks the ICP brokers → lenders/feasibility shops → BID/SBS → 3–30-unit operators, and anchors seat price on Reonomy $4,800 / GrowthFactor $2,400, but no customer conversation has happened yet to confirm which segment actually pays first, or at what price — the memo is explicit that this is unverified.)

#### Recent session decisions (D29–D57)

### D57 — Does the screen's present-day demand read for Bed-Stuy agree with the Furman Center composition story?
- **Status:** open
- **Answered by:** — (not ticketed; a CANDIDATE source, nyc_doe_demographic_snapshot, is registered in registry.yaml and its ingest is ticketed under E1 — see docs/TICKETS.md)
- **Tier:** P2 — validation / demand context
- **Tag:** *validation / data*
- **Session:** 2026-09-16
- **Why it matters:** Owner shared a Gothamist piece (2026-09-16, https://gothamist.com/news/schools-chancellor-weighs-plans-for-30k-students-in-small-nyc-schools) citing the NYU Furman Center: Bed-Stuy's Black population share ~75% (2000) → 38% (2024), families with children thinning, P.S. 25 closed 2025 at 54 students. Loci's demand composition (D60 ACS at address grain; D63/D65/D69 age-fit on under_18_share / under_5_share for childcare and bar) rests on ACS 5-year estimates alone — lagged, MOE-heavy, and unable to show year-over-year change in the pool of children. Two independent, more granular reads on the same composition shift now exist: the Furman Center's CoreData neighborhood profiles (downloadable per sub-borough area, series 2000/2006/2010/2019/2023/2024 — households with children, single-person households, race, income, homeownership, rent — https://furmancenter.org/neighborhoods) and the DOE Demographic Snapshot (probed 2026-09-16: datasets s52a-8aq6, c7ru-d68s, vmmu-wj3w, nie4-bv6q, covering 2013-14..2021-22, zone-joined via cmjf-yawu). A read-only Bed-Stuy check against Furman's numbers is in progress this session. This question is whether the screen's own present-day demand read (not a growth projection — CONTEXT.md's present-day-screen charter) agrees with that story, and if not, whether the gap is an ACS-lag artifact or a real miss.
- **Current answer:** —

### D55 — Gowanus core bank supply ratio reads 1.97x on the 2026-09-11 card and 0.67x on the 2026-09-13 card, same supply hash 767b28674e30, same 1,831 addresses. Which is right, and why did it move?
- **Status:** open
- **Answered by:** `Reconcile the Gowanus bank supply ratio: 1.97× vs 0.67× (QUESTIONS D55)`
- **Tier:** P1 — decision value for AC-1
- **Tag:** *data / rigor*
- **Session:** 2026-09-16, abenmayor-af
- **Why it matters:** CONTEXT.md v2 §7 (AC-1) and the Gowanus card of record both cite this unreconciled 2.9× move on a frozen hash; no CHECKPOINT decision explains it. Until resolved, no deliverable may print either bank figure (CONTEXT.md §7 standing rule).
- **Current answer:** —

### D32 — Freeze protocol for a stamped supply hash: a "final" declaration must go to every active session in one message before the first fit stamps it; any poi_status-changing write after that is a re-stamp event. Where should this live: CHECKPOINT rules, CLAUDE.md, or a `loci freeze` marker table the CLI refuses to write past?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P2 — infrastructure
- **Tag:** *infra / decision*
- **Session:** 2026-09-14, abenmayor-29
- **Why it matters:** Prevents supply hash moving under a running screen re-run due to mid-run evidence updates.
- **Current answer:** —

### D54 — Can any category other than restaurant/hardware/tailor_repair ever grade above D?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P2 — decision value / AC-4
- **Tag:** *model / economics*
- **Session:** 2026-09-16, abenmayor-db
- **Why it matters:** Economics caps every category without a revenue calibration or ≥5 BizBuySell comps at D, and addressable_demand caps all but laundry at C. The cheapest lever per recommend_grades.yaml's own `cheapest_check` is 3–5 P&Ls or broker set-ups per category per borough. Until that evidence exists the allocator report can only ever say "diligence" for three categories and "no" for twelve — which the owner should know before showing the report to an operator.
- **Current answer:** —

---

### Parked (P3)

#### Part A research

### M2 — How well do LODES *jobs* proxy *establishments*?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Validate LODES 2023 against establishment counts`
- **Tier:** P3 — dead LODES/ACS hex math
- **Fails if:** the per-hex correlation between 2023 LODES retail employment and 2023 DOHMH/DCWP establishment counts is weak enough that the panel is measuring payroll, not storefronts.
- **Current answer:** —

### M3 — How much pre-2020 LODES allocation error leaks across res-9 hex boundaries?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Quantify pre-2020 LODES allocation bias`
- **Tier:** P3 — dead LODES/ACS hex math
- **Fails if:** the area-proportional retro-allocation moves a material share of jobs across hex boundaries in split blocks, so pre-2020 panel values cannot be treated as observed (CONTEXT.md §7.4b).
- **Current answer:** —

### M4 — Do Overture, Foursquare and OSM agree on presence, and where do they disagree?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Cross-source POI dedup / entity resolution` · `Foursquare OS Places adapter`
- **Tier:** P3 — coverage follow-ups
- **Fails if:** disagreement is concentrated by geography or by category (laundromats, salons) rather than spread randomly — then source choice is itself a bias.
- **Current answer:** Loaded 2026-09-02. Dedup on six sources collapses 25% of rows (299,029 → 224,370 canonical). **Foursquare's disagreement is mostly staleness, not geography:** rows last refreshed before 2019 are corroborated by any other source <10% of the time, 2026-refreshed rows 55%. With a 2024 freshness gate it adds 54k canonical POIs, concentrated in bars, gyms, cafes and salons. Its effect on the gap screen is modest (hardware 270→245, fitness 154→138) — the ungated version had erased far more, all ghosts. Also observed: adding any source can push a category's prevalence over the 80% 'expected' line and turn its absences into gaps (bank did, 0→285 hexes). That is a screen-design sensitivity, filed for the owner.

### M5 — Do ACS margins of error leave hex-level income and population usable as controls?
- **Status:** open
- **Prediction:** —
- **Answered by:** `ACS ingest + dasymetric interpolation onto hexes`
- **Tier:** P3 — dead LODES/ACS hex math
- **Fails if:** propagated MOEs on hex median income are wide enough that the income control cannot distinguish neighbouring hexes.
- **Current answer:** —

### M7 — What anchor source would establish a true fitness coverage hole?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Fitness anchor source for the ~20% true coverage hole`
- **Tier:** P3 — coverage follow-ups
- **Fails if:** n/a — measurement/sourcing question. Needed because D29 found a real ~21% [10–37] true-coverage-hole rate for fitness after removing geometry artifacts, and OSM/Overture/Foursquare are the only sources feeding that category today — none is a near-census the way DOHMH is for food or SNAP is for grocery.
- **Current answer:** Open. Candidates to evaluate: NYS business registry, DOHMH (if it licenses fitness facilities), state gym/health-club licensing. None yet verified for NYC coverage or access.

### M10 — Which MN+BK addresses have laundry in the basement or in unit, and from what source?
- **Status:** open
- **Answered by:** (not ticketed) — loci ingest-ll84, loci ingest-listings pilot, DCWP laundry anchor (D55, owner request 2026-09-08)
- **Tier:** P3 — coverage follow-ups
- **Why it matters:** An address with in-building laundry does not experience a laundromat gap, so the laundry category's supply is under-counted wherever such buildings cluster; laundry currently owns the top of the ratio ranking.
- **Current answer:** None; research agent probing DOB certificates of occupancy, DOB job filings, HPD registrations, and listing-site amenity data.

### M12 — Does an 800 m or distance-decay transit variable stop being binary in Brooklyn, and does it beat homes_400m at the quiet end of the distribution? · *graduation test for D76*
- **Status:** open
- **Answered by:** (not ticketed) — GTM-147
- **Tier:** P3 — coverage follow-ups
- **Why it matters:** transit_entries_400m and jobs_400m shipped as card-context only (D76, GTM-147) because the Brooklyn-only DOT validation ρ is 0.56 with a CI floor of 0.14, and a binary any-station-within-400m flag alone already accounts for most of the correlation — the variable barely varies where it matters most (65% of Brooklyn addresses read zero). Until a wider radius or a distance-decay kernel produces real variation in Brooklyn, the column cannot be trusted to distinguish a genuinely busy corner from a genuinely quiet one, which is a precondition for entering any grade section.
- **Fails if:** the 800 m / distance-decay rebuild does not clear all three D76 graduation criteria (≥100 non-corridor validation points, Brooklyn-only ρ ≥ 0.6 with CI lower bound > 0.4, non-degenerate variance) — in which case foot traffic stays card-context indefinitely, not just until the next attempt.
- **Current answer:** Open. Blocks any future grade-section proposal for transit/jobs.

### D1 — How complete is the daily-needs bundle within a 10-minute walk across NYC, and how is completeness distributed?
- **Status:** open
- **Prediction:** —
- **Answered by:** `DNCI: weighted geometric mean + unit tests` · `SHIP W2: the DNCI map`
- **Tier:** P3 — hex-era descriptive
- **Fails if:** n/a — descriptive. Report the distribution by borough and the share of hexes below 0.5.
- **Current answer:** —

### D4 — Where do transit-rich and daily-needs-poor hexes overlap?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Bivariate transit × residual map` · `MTA transit access control`
- **Tier:** P3 — hex-era descriptive
- **Fails if:** n/a — descriptive. This is the thesis stated as one image.
- **Current answer:** —

### D7 — Should thresholds vary by density class or transit/car-dependence, not just by category?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Density-class / mode-dependent thresholds`
- **Tier:** P3 — hex-era descriptive
- **Fails if:** n/a — descriptive/method question. Lower Manhattan and car-dependent outer-borough areas should not share one walk window. Cheap proxy: scale the threshold by residential density class (no new data needed). Honest version: ACS vehicle ownership per tract (needs an ACS vehicle-ownership ingest; key is set). Note the interaction with D6: threshold(category, density_class) is one parameterization, not two independent sweeps — keep it small to avoid overfitting a matrix.
- **Current answer:** Open; still needs the ACS vehicle-ownership ingest for the mode/car-dependence threshold (key is set). 2026-09-05 (CHECKPOINT D43): mature Manhattan's complete areas reveal amenity distances 3–7× tighter than the adopted citywide tiers — a single reach is either too loose for Manhattan or too tight for Queens. Proposed: reach(c) per density class from complete addresses in that class, floored by reach_tiers.yaml's cited values. See docs/market_reach_manhattan.md.

### D9 — Is a count/distance-based gap flag missing quality gaps that a size or diversity measure would catch?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not ticketed) — needs an establishment-size proxy (employment band, floor area from PLUTO retail sqft, or chain identity) per POI
- **Tier:** P3 — hex-era descriptive
- **Fails if:** size/diversity metrics are highly correlated with count-based presence (paper reports 0.70–0.90 correlation among density metrics but weak correlation to size/diversity — so expect this NOT to fail).
- **Current answer:** Expectation (not a P1–P3 prediction): Some hexes that pass the reach test for grocery are served only by small-format stores (bodega-scale), which Meltzer & Schuetz show is the actual low-income pattern. — (Source: Meltzer & Schuetz 2012 Table 4 and the Herfindahl index over NAICS subsectors.)

### D10 — Is a max nearest/reach ratio comparable across categories with different reaches, and what does a graded recommendation look like?
- **Status:** open
- **Answered by:** (not ticketed) — session-13 grade proposal and contrarian review (scratchpad grade_proposal.md, grade_contrarian.md; D48/D51, 2026-09-08)
- **Tier:** P3 — hex-era descriptive
- **Why it matters:** The ranking sorts every address by its single worst ratio across 15 categories. The category with the tightest reach (laundry, 320 m) mechanically produces the largest ratios, so it owns the top of any ranking regardless of whether its gaps matter most. A grade needs to combine the ratio with absolute excess meters (D44 candidate b, sound as an input) and residential density, and to define the band above which the recommendation is "act, at a fair price."
- **Current answer:** None. Session-13 description on MN+BK and a data-scientist proposal are in progress; contrarian to attack whatever the proposal picks.

### D11 — Which supply set is real: all POIs, corroborated-only (≥2 sources), or active-licensed?
- **Status:** open
- **Answered by:** (not ticketed yet) — D52 supply-set principle: loci anchor-coverage, loci zbp-compare --supply-sets, view analysis.poi_supply (2026-09-08)
- **Tier:** P3 — hex-era descriptive
- **Why it matters:** The contrarian's re-run showed the act band moves 6× and rank-correlates at 0.19 between the all-POI and corroborated-only sets; nothing else in the grade matters until this is settled.
- **Current answer:** None; D36/D47 plumbing in progress (fetch DOHMH/NYS DOS date fields, active-establishment filter).

### D12 — Where does absent supply reflect revealed demand rather than a gap (bars in Midwood/Borough Park), and what non-income demand control catches it?
- **Status:** open
- **Answered by:** (not ticketed) — needs a non-income demand control before discretionary categories are published (D51, 2026-09-08)
- **Tier:** P3 — hex-era descriptive
- **Why it matters:** The largest cell in the drafted grade's act band is ~9,800 bar gaps in high-income south-central Brooklyn where the income caveat is silent; publishing it would repeat the D1 error.
- **Current answer:** None; candidates to probe are religious-institution density, SLA license application counts, and household composition from ACS.

### D14 — Does nails_beauty's DOS registry anchor over-count (≈3× ZBP), and what is the right supply set for a category whose anchor itself is inflated?
- **Status:** open
- **Answered by:** (not ticketed) — D59 caveat; candidates: tighten booth-renter radius, exclude non-salon appearance-enhancement licence types, or cap anchor coverage at ZBP parity
- **Tier:** P3 — hex-era descriptive
- **Tag:** *data / supply*
- **Why it matters:** anchor qualifies for the wrong reason; PRINCIPLED nails still 3.74× ZBP, flagged OVER; what to do about it?
- **Current answer:** None.

### D21 — Should `poi_is_open` gain a "stale" state for a DOHMH record whose last inspection is well beyond a fresher co-located record's?
- **Status:** open
- **Answered by:** `poi_is_open: add a 'stale' state for inspection-gap-beside-fresh co-located records`
- **Tier:** P3 — schema/dedup housekeeping
- **Why it matters:** the co-location closure gate (commit a67f03e, `analysis.poi_colocation`) built `poi_is_open` as a tri-state predicate (open / closed / unresolved) but has no way to flag a record that is merely stale: Okozushi at 376 Graham was last inspected 384 days ago and still reads "open" under the current predicate, sitting beside a co-located record with a much fresher inspection. D79 forbids treating absence-as-closure, so a plain "no recent inspection → closed" rule is exactly the mistake that decision exists to prevent — but an aging gap next to a fresher neighbor is a weaker, different signal than either open or closed, and today it is silently folded into "open."
- **Fails if:** n/a — data-quality/method question; but a stale-age threshold set without reference to a co-located comparator would reintroduce the absence-as-closure mistake D79 already rejected.
- **Current answer:** Open. Not part of the 2026-09-14 "yes to all 4" ruling (CHECKPOINT D90).

### D23 — Are the bank/hardware/clinic anchor NAICS-vs-adapter contradictions (Next-actions item 21) resolved?
- **Status:** open
- **Answered by:** (not ticketed) — CHECKPOINT Next-actions item 21, D90
- **Tier:** P3 — schema/dedup housekeeping
- **Why it matters:** `categories.yaml`'s bank anchor (NAICS 522110) excludes the credit unions Overture feeds in; hardware's anchor (444140) excludes the home centers the adapters ingest; clinic's anchor lists 621111 while `foursquare_places.py` deliberately excludes solo doctors' offices. These concern the ZBP anchor measure itself, not the Google validation calls, so GTM-48 running does not resolve them.
- **Fails if:** n/a — data/method question.
- **Current answer:** Open. Explicitly NOT part of the 2026-09-14 "yes to all 4" ruling (CHECKPOINT D90) — the owner ruled only on the three Google-validation follow-ups plus cross-category dedup.

### D25 — Should `db.init_schema` apply only HEAD-tracked migrations, not every `*.sql` on disk?
- **Status:** open
- **Answered by:** `init_schema must apply only HEAD-tracked migrations (uncommitted *.sql went live across sessions)`
- **Tier:** P3 — schema/dedup housekeeping
- **Why it matters:** found during the D101 dedup screen re-run #2: `init_schema` applies every `*.sql` file it finds on disk, in sorted order, INCLUDING files that are not yet committed — so a peer session's uncommitted migration goes live on any OTHER session's next write connection, not just the peer's own. This is invisible to every hash check this project uses at re-run checkpoints, because those check the supply set's rows, not the schema a query runs against.
- **Fails if:** n/a — infra/method question; but any fix that still lets an uncommitted file affect a connection it did not originate from reproduces the same defect under a different name.
- **Current answer:** Open. abenmayor-88 (the ledger owner) will bring the actual guard design as an owner decision; ticketed (GTM-179) for the fix once that shape is settled.

### D26 — Is cafe_bakery's newly-anchored principled set (registry-backed under category-precedence B) right, or should café keep aggregator members?
- **Status:** open
- **Answered by:** (not ticketed) — CHECKPOINT D101
- **Tier:** P3 — schema/dedup housekeeping
- **Why it matters:** D101's CATEGORY_PRECEDENCE=finer_food ruling relabels enough restaurant→cafe_bakery rows (1,981) that cafe_bakery now clears the anchor-qualification bar (DOHMH members present, coverage 1.507) for the first time — so its principled/gated supply set (8,932 of 19,150 canonical cafes) is now registry-backed the way restaurant, grocery and the other anchored categories are. This is a genuine consequence of the category-precedence ruling, not something anyone decided on its own terms: nobody asked whether café SHOULD be anchor-gated, or whether its Overture/Foursquare-only members (the other 10,218) are being wrongly excluded from supply just because they lack a DOHMH row.
- **Fails if:** n/a — data-model/method question; but gating café to its DOHMH-corroborated subset when the un-gated aggregator members are otherwise legitimate cafes would understate café supply the same way any anchor-fallback failing closed does (D30 precedent).
- **Current answer:** Open. Flagged as a consequence of the D101 ruling worth a look, not decided by it.

### D27 — Should the ~390 residual wrong merges from the D101 dedup rule (the one-brand-two-storefronts pattern) be accepted, or fixed with a brand-suffix rule?
- **Status:** open
- **Answered by:** (not ticketed) — CHECKPOINT D101
- **Tier:** P3 — schema/dedup housekeeping
- **Why it matters:** the shipped D101 dedup rule audited at 0.970 [0.915, 0.990] precision on a fresh 100-pair sample, meaning roughly 390 of its 12,928 merges are estimated wrong. The residual failure mode named during the audit is one brand operating two nearby, genuinely separate storefronts under names that share a core (e.g. "Saraghina Bakery" vs "Saraghina") — the name-core-equality rule cannot distinguish a second location of the same brand from one business double-counted across sources, because both present as "the same distinctive name within 40 m."
- **Fails if:** n/a — data-quality/method question; but a brand-suffix rule loose enough to separate "Saraghina Bakery" from "Saraghina" without reintroducing the cross-category duplicates D101 was built to fix would need its own precision audit before shipping.
- **Current answer:** Open. Not part of the 2026-09-14/15 dedup ruling — recorded as a residual worth a look, not decided.

### X1 — How much DNCI variation is explained by density, income, transit and commercial zoning capacity?
- **Status:** open
- **Prediction:** P1
- **Answered by:** `Fit the supply model`
- **Tier:** P3 — hex-era explanatory
- **Fails if:** R² > 0.9. Retail supply is fully determined by the controls and there is nothing left to explain.
- **Current answer:** —

### X3 — Does the residual behave differently by borough or in high-foreign-born hexes, and is that real or coverage bias?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Fit the supply model` · `Design stratified coverage validation sample` · `Coverage-bias chart`
- **Tier:** P3 — hex-era explanatory
- **Fails if:** a borough or foreign-born contrast in the residual disappears once the stratum's measured undercount is applied — then it was M1 wearing a costume. The validation sample is stratified by foreign-born share as well as income so this can be separated.
- **Current answer:** —

### X4 — Is the top-20 underserved list free of zoning artifacts, and does it contain genuine surprises?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Top-20 list + zoning-artifact audit`
- **Tier:** P3 — hex-era explanatory
- **Fails if:** any park edge, industrial zone or cemetery block appears (the zoning control failed), or fewer than three entries are places not nameable in advance (the residual is not doing any work).
- **Current answer:** —

### X5 — Is Staten Island a high-leverage outlier that distorts the supply model?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Staten Island leverage check`
- **Tier:** P3 — hex-era explanatory
- **Fails if:** Cook's distance flags Staten Island hexes and coefficients move materially with them excluded. Report with and without.
- **Current answer:** —

### X6 — Does race/ethnicity predict gap incidence net of income and density, and in which direction?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not ticketed)
- **Tier:** P3 — hex-era explanatory
- **Fails if:** gap incidence by race is fully explained by income_class + population density.
- **Current answer:** Expectation (not a P1–P3 prediction): Per Meltzer & Schuetz, predominantly Black hexes show more gaps than income alone predicts; predominantly Hispanic hexes fewer (more small-format supply). Loci has NO race/ethnicity column today; needs an ACS B03002 ingest. — (Descriptive only; this is the "retail redlining" question. Investor lens: a gap that exists for supply-side reasons in a high-demand area is the strongest kind of opportunity; a gap that reflects thin demand is not. The demand_caveat flag is the first, crude version of that distinction.)

### X7 — Does the AM/PM entry share (station type) explain category mix or supply ratios better than transit levels do — is "residential vs destination catchment" a usable segmentation for the screen?
- **Status:** open
- **Answered by:** (not ticketed) — D76 daypart addendum (2026-09-13), analysis.address_transit_profile
- **Tier:** P3 — hex-era explanatory
- **Why it matters:** The daypart profile shows a shape the D76-refused transit levels do not carry: Brooklyn addresses split cleanly by AM/PM share (84.5% read residential-type, median 1.79; East Village 0%, a destination catchment; Gowanus core mixed at 1.03), while at DOT validation points every window is best ranked by the largest daypart — i.e. station size, not time-of-day. If the ratio predicts which categories an address should carry (daily-needs under-supplied where residential-type, food/bar over-supplied where destination-type), it is a legitimate segmentation input for supply_ratio_vs_base or the recommend card, distinct from the levels D76 capped at card-context.
- **Fails if:** category mix or supply_ratio_vs_base show no material difference between residential-type (AM/PM share > 1) and destination-type (AM/PM share ≤ 1) addresses once density and income are controlled — in which case the ratio is descriptive color, the same fate D76 gave the raw levels.
- **Current answer:** Open. Saturday/Sunday profiles are unvalidated (DOT counts weekdays only), so any segmentation built on the share should be scoped to weekday dayparts until a weekend validation source is found.

### X8 — Does the neighborhood character (retail_index, weekday-office catchment) explain supply-ratio residuals or storefront survival better than homes/jobs alone — i.e. is it a control the screen should carry, or just a map colour?
- **Status:** open
- **Answered by:** (not ticketed) — GTM-154
- **Tier:** P3 — hex-era explanatory
- **Why it matters:** D82 shipped retail_index and the corporate/industrial/residential labels as map colour and card context only, on the owner's ruling that character enters no grade. But if character predicts *why* a supply ratio or age-fit residual reads high or low — e.g. a "thin" category in a corporate-labeled address is thin because the daytime population is real but transient, not because the daily-needs opportunity is real — then it is quietly doing the work of a control variable without being treated as one, and every grade that omits it risks the same "supply-revealed, not demand-revealed" confound D63's age-fit caveat exists to catch. If it explains nothing net of homes_400m/jobs_400m, the D82 ruling (map colour only) stands confirmed rather than merely asserted.
- **Fails if:** retail_index or character_label add no explanatory power over supply_ratio_vs_base residuals or storefront survival/first-seen duration once homes_400m and jobs_400m are already in the model — in which case character is confirmed as descriptive color, the same fate D76 gave the raw transit levels.
- **Current answer:** Open. Ticketed GTM-154 alongside the retail_index saturation and 20-lot threshold review.

### X9 — Does persons-per-frame at a DOT camera rank-correlate with DOT's screenline counts across the AM/MD/PM windows, and is the relationship stable enough across cameras (field of view) to use camera counts as the shortlist verification for leads?
- **Status:** open
- **Answered by:** (not ticketed) — GTM-157
- **Tier:** P3 — hex-era explanatory
- **Why it matters:** `loci sidewalk-count` (D85) gives a free, near-live person count at any of 969 cameras, but a still-frame count is a stock (people present) not a flow (people passing), and each camera's field of view is an uncorrected confound (a camera pointed down a wide plaza will always read higher than one on a narrow sidewalk regardless of true footfall). Before camera counts can stand in for DOT's screenline counts anywhere DOT has no physical count point, the two need to agree in RANK at the 15 cameras that sit within 60 m of a DOT count point — first per window (AM/MD/PM), then across cameras. If the correlation holds, a camera-based shortlist check becomes available citywide wherever DOT has no counter; if it doesn't hold, or holds only at some cameras, the tool stays scoped to comparing a camera against itself over time.
- **Fails if:** the rank correlation between camera person-counts and DOT screenline counts is weak, inconsistent across the AM/MD/PM windows, or inconsistent across cameras (i.e. driven by field-of-view differences rather than true footfall) — in which case sidewalk counts remain a self-comparison tool only, never a cross-location verification signal.
- **Current answer:** Open. First samples (2026-09-13) were a Sunday evening, so `validate` reports N=0 against DOT's weekday counts; weekday AM/MD/PM sampling at the 15 DOT-adjacent cameras is ticketed as GTM-157.

### X11 — Does dock activity add information beyond transit for entry/forecast, or is it collinear once character and homes are in the model?
- **Status:** open
- **Answered by:** `Citi Bike phase 3: station activity growth as a retrodiction/forecast feature; Divvy (Chicago) adapter as the portability probe`
- **Tier:** P3 — hex-era explanatory
- **Why it matters:** Citi Bike phase 1 (D102, GTM-166) found the Gowanus-vs-East-Village ordering REVERSES between bike and transit (bike starts p50 265 vs 1,286; transit runs the other way) — the first evidence any of Loci's foot-traffic proxies is not just a restatement of the transit signal. If bike activity carries information transit and neighborhood character don't already capture, it belongs in the forecast model as a feature; if it's collinear with character+homes once both are in, it's redundant and should stay context-only like transit (D76).
- **Fails if:** a challenger forecast-model version with bike_starts/ends_400m added shows no AUC lift, or the same-sign coefficient as transit density, once character and homes_400m are already in the model — in which case dock activity is a restatement, not new information.
- **Current answer:** Open. Test in the forecast model as a challenger version (GTM-168, Citi Bike phase 3) once the entry-retrodiction panel is re-run.

### T4 — Do the results survive MAUP and a spatial error specification?
- **Status:** open
- **Prediction:** —
- **Answered by:** `MAUP sweep at res 8 and res 10` · `Moran's I + spatial error/lag model`
- **Tier:** P3 — dead predictive
- **Fails if:** the sign or significance of β flips between res 8, 9 and 10, or under the spatial error model.
- **Current answer:** —

### T5 — Does the gap close on its own?
- **Status:** open
- **Prediction:** —
- **Answered by:** `LODES WAC annual panel loader 2002–2023` · `LODES block → hex apportionment` · `Residual convergence test`
- **Tier:** P3 — dead predictive
- **Fails if:** n/a — exploratory. The question: over 2002–2023, do negative-residual hexes converge toward their peers? If yes, the market already corrects and the opportunity is *timing*, not location. The memo must say which.
- **Current answer:** —

### T6 — Does retail lead or lag rooftops?
- **Status:** open
- **Prediction:** —
- **Answered by:** `LODES WAC annual panel loader 2002–2023` · `Retail lead/lag timing test`
- **Tier:** P3 — dead predictive
- **Fails if:** n/a — exploratory. Directly interrogates "retail follows rooftops", the assumption the residual design rests on. Caveat: ACS 5-year smoothing limits timing resolution to roughly half-decades; LODES is annual but is jobs, not storefronts (M2).
- **Current answer:** —

### T7 — How do nearby storefronts respond to a residential density shock (new units / occupancy), on what lag, and at which construction stage is the signal actionable?
- **Status:** open
- **Prediction:** —
- **Answered by:** `Residential development pipeline: DCP Housing Database + DOB CO at job grain, pipeline exposure on analysis.address, webmap overlay` · `Storefront opening/closing history: inactive DCWP licences, full SLA history, DOHMH raw` · `Stacked matched event study around ≥50-unit completions`
- **Tier:** P3 — dead predictive
- **Fails if:** Q5 not separating from Q1 beyond bootstrap CI; separation already present at τ=−4; not beating persistence baseline; **KILL CHECK (verified 2026-09-09):** no storefront opening/closing time series exists in Loci. Only foursquare_os_places has opened_on (109k rows; 2010 spike is Foursquare's launch, not storefronts). nys_sla_liquor_licenses has opened_on only for recent licences (3,205 rows, 2023-09→2026-09). overture, dohmh, dos, snap, dcwp_inspections have no opened_on. No source has closed_on. Conclusion: Loci has no storefront opening/closing time series; the one-session MVA cannot run until inactive/expired DCWP licences, full historical SLA licences, and raw DOHMH history are ingested (Increment-2 work, not an MVA).
- **Current answer:** Exploratory only, pending full historical licensing ingest (see *Fails if* above). T5 (gap closure over 2002–2023) and T6 (retail vs rooftop lead/lag) map longer horizons. Timing catalysts from O5: catalyst→construction ~5–9 yr, catalyst→demographic ~10–20 yr (market-rate only). LODES panel issue: registry.yaml describes lodes_wac as annual 2002–2023, but analysis.hex_panel holds only three vintages (2002, 2013, 2023; ~11.5k hex rows each); cannot resolve a 1–3 year lag. Registry mismatch flagged for docs/CHECKPOINT decision log. Literature synthesis: Li 2022 JEG (effects within ~500 ft, 1–3 yr, modest), Asquith/Mast/Reed 2023 REStat (amenity effect too small to offset rent), Glaeser/Luca/Moszkowski 2023 (gentrifying tracts show faster entry AND exit), HR&A 2024 + NYC Comptroller 2024 (churn > net growth; post-COVID glut). **Contrarian caveats to carry (2026-09-09, Opus review):** (a) survivor truncation in opened_on series manufactures clean event-time separation under the null (gentrifying hexes have higher exit rates); (b) licence date ≠ opening date, lag longer for new construction, biasing estimated lag toward zero where treatment is; (c) "flat count, more profitable" unfalsifiable with survival/LODES/ZBP proxies — needs lease comps, taxable sales, or foot-traffic panel; (d) stage rule (permit→open by CO+18 mo) asserted, not estimated — needs issued-permit→CO survival curve + out-of-sample horse race (stage-s pipeline at t predicting openings at t+k, ≤2016 train / 2017–23 test, vs baselines, by category); (e) hex-year panel conflicts with address-level directive; narrowest charter-consistent framings are a demand-pool covariate (units under construction / recently CO'd within reach) or a timing annotation on ranked gap addresses. **Provisional planner heuristic (unvalidated):** permit issued → underwrite for daily-needs; operating by CO+18 mo → demand arrives; 50–60% leased across ≥2 buildings → signal for restaurants/fitness. Subsumes T6's focus on magnitude, lag, and pipeline-stage forecast skill. 2026-09-09: pipeline layer built (CHECKPOINT D62) — units permitted / completed within 400 m and nearest ≥50-unit project now sit on every MN+BK address and on the map; investor review (same day) found the rooftops→retail lag is a rational landlord option, not a friction, so T7's causal increments stay unbuilt and the pipeline is a timing annotation only. 2026-09-10: the DOF Storefront Registry is ingested (CHECKPOINT D67) — vacancy exposure now sits on every MN+BK address; still no opening/closing series, so T7's increments remain gated.

### T8 — Do chain opening pipelines lead category gap closure — is the chains watchlist a leading indicator of supply?
- **Status:** open
- **Prediction:** —
- **Answered by:** (not ticketed) — GTM-148, needs the chains snapshot delta
- **Tier:** P3 — forecast/chains deadlines far off
- **Fails if:** brand openings from the watchlist show no lead relationship to `analysis.address_gaps` category closure — e.g. a category's gap count in an area does not fall more often in the months following a watchlist brand's opening nearby than in a matched control period/area. Also fails if the relationship is only visible because both series move with general neighbourhood growth (the D1 endogeneity trap in a new costume — same shape as the transit/supply correlation D76 found).
- **Current answer:** Untestable until a second chains snapshot exists (D77) — one snapshot gives a count, not a delta, and this question is specifically about the delta's timing relative to gap closure. Shares T7's structural problem: no address-level opening/closing time series exists for most categories, so the chains watchlist (which does carry approximate first-seen dates for ~60% of brand-locations, D77) may end up as the closest thing Loci has to that series, category coverage permitting.

### T9 — What is the median lead time from first government filing (liquor application, fit-out filing, license application) to first DOHMH inspection or license issue, by category — and is it stable enough to turn filings into an "opening within N months" forecast?
- **Status:** open
- **Answered by:** D80 (2026-09-13), analysis.storefront_pipeline
- **Tier:** P3 — forecast/chains deadlines far off
- **Why it matters:** T7's kill check found no storefront opening/closing time series anywhere in Loci; government filings (SLA pending licenses, DOB NOW job filings, DCWP license applications, DOHMH promoted inspections) are the closest candidate the project has assembled since, and a stable per-category lead time is what would let the chains/pipeline work (T7, T8) turn a filing into a dated forecast rather than a bare count.
- **Fails if:** lead time varies too widely across category or borough to support a single-N forecast, or the filing-to-open correlation disappears once withdrawn/never-opened filings are accounted for — in which case filings are context (like transit, D76) rather than a forecast input.
- **Current answer:** fitout_filing → first_inspection strict N=67 median 259 d (p25 178 / p75 378); reconciled N=741 median 221 d — but the reconciliation linking those pairs is 92% sole-pair-in-BBL (only one candidate filing existed at that BBL, not a confirmed multi-agency match), so strict is the reference, not the larger reconciled N. liquor_application → first_inspection N=22 median 73 d; fitout → license_issued N=35 median 183 d. Same-agency clocks (DCWP 11 d, SLA pending→active 26 d) are excluded — they measure the agency's own processing time, not the store. N is still small per category and the pipeline is filing-blind for 10 of 15 categories (see T10), so this is not yet stable enough to ship as an "opening within N months" forecast.

### T13 — Does the 2026-09 forecast vintage keep its ranking power when scored live in 2027-09, and does per-category recalibration fix the level errors?
- **Status:** open
- **Answered by:** (not ticketed) — GTM-163
- **Tier:** P3 — forecast/chains deadlines far off
- **Why it matters:** D92's forecast ledger backtested 2023-01 (AUC 0.899 vs 0.860 no-score at 12 months) with a vintage the model form was itself chosen after seeing — specification-search leakage that makes the backtest optimistic. 2026-09 is the first vintage frozen before its outcome exists, and its pooled calibration gap (0.12) hides opposite-signed per-category errors (restaurant 0.38, bar 0.28) that a live score would expose for real.
- **Fails if:** the 2027-09 score reproduces the 2023-01 backtest's AUC lift within its confidence interval but per-category isotonic recalibration (fit on the same folds as the model) does not shrink the restaurant/bar calibration gap — in which case the pooled number is masking a defect recalibration cannot fix, and a capacity term or a structural respecification is needed instead.
- **Current answer:** Open. Blocked on the calendar (scored 2027-09) and on shipping a retention rule first (ticket a, GTM-163) so the DB holds the vintage to score.

### O3 — Where does each neighborhood sit on its development maturity curve today? · *descriptive*
- **Status:** open
- **Prediction:** —
- **Answered by:** `Neighborhood maturity-stage classifier` · `Assemble the multi-decade neighborhood trajectory panel`
- **Tier:** P3 — parked: Appendix A8 demotes the maturity axis until it passes a backtest
- **Fails if:** n/a — descriptive. But the stage must be defined by **level + rate + acceleration** (1st and 2nd derivative), or it collapses into a static wealth map that just re-labels rich = mature.
- **Current answer:** First cut, 2026-09-02. A momentum maturity index (0.45·real income + 0.55·college, fixed anchors, 2013→2023) places all 145 3-borough NTAs; the frontier reads East New York / Ridgewood / Bed-Stuy East (emerging) → Bushwick (just arrived) → Williamsburg / UES-UWS / Tribeca (saturated at the $250k cap). This is level+rate only — no acceleration term yet, and a single 2-point momentum, so it is not the full classifier.

### O5 — Where does the next neighborhood ignite — and is that predictable? · *explanatory / predictive*
- **Status:** open
- **Prediction:** —
- **Answered by:** `Frontier-diffusion map: where the edge moved, where it goes next`
- **Tier:** P3 — parked: Appendix A8 demotes the maturity axis until it passes a backtest
- **Fails if:** neither adjacency to an already-risen NTA nor a committed exogenous catalyst predicts which neighborhoods rise next.
- **Current answer:** 2026-09-02. Reframed after O4: since ignition is **not** in a neighborhood's own trajectory (level/slope/acceleration all fail the backtest, D25), the predictive signal must be **exogenous**. Built `src/loci/model/ignition.py` + `loci ignition` (Axis 4b): a hand-curated **catalyst layer** (17 real committed/planned projects — SAS Phase 2, Interborough Express, DCP neighborhood rezonings, Willets Point) screened against low-mid maturity + a light urban-density floor. Key finding: a **naive PLUTO development-headroom score fails** (it floats low-density suburbs — Fresh Meadows, Bath Beach); **requiring a real catalyst is the actual suburb-filter**, and the density floor must stay LOW or it wrongly drops the low-rise-but-catalyzed frontiers (East New York) that are the whole point. 42 catalyst-anchored candidates; the committed tier is defensible and converges with the independent trajectory work — **East Harlem N (mat 29, SAS Ph2 Q-train + '17 rezoning)** is the flagship; the Atlantic-Ave-rezoning cluster (Ocean Hill, Crown Heights, Bed-Stuy) and the East New York cluster (2016 rezoning) follow. The screen's "dropped, no catalyst" list (Chinatown-Two Bridges, Harlem-125th, Washington Heights) is honest QA — real urban candidates whose catalysts the curated layer is still MISSING. Catalyst layer expanded to 28 dated projects (forward + historical). **DOB corroboration added** (`loci ignition` NB18-23 column, from 198k geocoded new-building filings): confirms heavy building in East New York (253), Crown Heights (215), Ocean Hill (151), East Harlem (118) — and flags stalled ones (Two Bridges 14). **Two-clock lag finding** (`loci ignition --lag`): catalyst→**construction** ~5–9 yr (permit surge, peak ~6–11 yr); catalyst→**demographic/human-behavior change** 10–20 yr, sustained, and **only if the rezoning is market-rate** — East New York (affordable-dominated, 2016) built the most but gentrified *below* the citywide drift, i.e. densified without tipping (confirms D21). So the construction/land play is this cycle; the appreciation play is a 2030s–40s horizon, conditional on catalyst type. Reports: ignition_lag_findings.md, nb_by_nta_year.json. Remaining: union DOB NOW (`w9ak-ipjd`) to fix the post-2016 undercount; a proper diff-in-diff to move from timing to causation; validate adjacency-diffusion as a distinct channel.

### O8 — Buy versus build: acquire an existing business or open a new one, and where is the inflection point? · *strategy / feasibility*
- **Status:** open
- **Prediction:** —
- **Answered by:** — (not yet ticketed; scope decision pending investor-agent review before it enters Axis 1 investability)
- **Tier:** P3 — parked opportunity axis
- **Fails if:** n/a — strategy/feasibility question, not a screen result to validate.
- **Current answer:** Open, sketch only (2026-09-03). For a category and area, is it cheaper (risk-adjusted) to acquire an existing store than to open one, and what saturation level flips the answer? Sketch: acquisition cost ≈ multiple of seller's discretionary earnings (small retail typically 2–3×; category-dependent — bodega goodwill low, restaurant higher) vs. build cost = startup cost + ramp-period losses + failure risk. Inflection = the catchment-saturation level at which the acquisition premium falls below the ramp-plus-risk cost. Key structural link to the core screen: in a true gap hex there is nothing to acquire by definition, so buy-vs-build applies to the NON-gap, saturated areas — the gap screen says "build here," O8 says "elsewhere, buy instead." Data candidates: BizBuySell / BizQuest listings (asking price, revenue, cash flow — public but self-reported), SBA 7(a) loan data (public; flags business-acquisition loans by NAICS and location), the O6 catchment model. Threats: listing prices are asks, not closes; survivorship (only businesses worth selling get listed); ramp curves are category folklore. Depends on O6 and O7 (cross-ref O6, Axis 1). Scope-creep risk flagged: this is a second product (an acquisition screen), not a refinement of the first. Investor-agent review required before any build.

### O10 — Within the cities that are trying to become walkable (H-L13), which neighborhoods have the most opportunity? · *predictive screen*
- **Status:** open
- **Prediction:** —
- **Answered by:** `Extract universal interface; run a second city`
- **Tier:** P3 — parked opportunity axis
- **Fails if:** the screen run on universal sources only (CONTEXT.md §10) produces a gap distribution with no usable spread in the second city, or its top-ranked neighborhoods are the ones with no policy tailwind — in which case "trying to become walkable" added nothing over the plain screen and H-L13's premise is wrong.
- **Current answer:** — (Owner question, 2026-09-09, follow-up to H-L13. Depends on H-L13 producing a ranked city list first. The intent is that the second-city screen is joined to the policy signal: a neighborhood scores highest when it is both under-supplied on daily needs *and* inside the footprint of an adopted walkability program (upzoning, parking-minimum repeal, bike/pedestrian capital), since that is where a present-day gap is about to become an actionable one. This is C3's generalization test with an investment reading attached; it inherits C3's `deferred` risk and the NYC-only-controls threat (PLUTO has no national analogue). Investor-agent review before any build, as O6–O8 require.)

#### Homework

Each item names the epic it unblocks. Record the answer inline when found; do not open a
ticket unless the answer turns into work.

Links for every reading live in Notion: **Projects → LOCI → Loci Reading List**
(https://app.notion.com/p/3cf48af1331b8108bfb3d2bd483b45fb).

### H-L1 — What did "Consumer City" and "Urban Revival" find about amenities and residential demand?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Glaeser, Kolko & Saiz 2001; Couture & Handbury 2020. Would T1 replicate or contradict them? What controls did they use?)

### H-L3 — What thresholds and saturation forms do food-desert and 15-minute-city measurements use?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E2 · Access Engine
- **Current answer:** (USDA Food Access Research Atlas; Moreno et al. on the 15-minute city. Precedent for k_c and the 800 m headline. Full research: docs/reach_sources.md.)

### H-L4 — What does Walk Score's methodology do for distance decay and category weights?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E2 · Access Engine
- **Current answer:** (Borrow the decay shape if defensible; avoid inheriting its category weights uncritically. Full research: docs/reach_sources.md.)

### H-L5 — Spatial error or spatial lag on gridded urban data: which is the right default?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Anselin's LM / robust LM tests; LeSage & Pace on when lag is theoretically motivated. Decide before W3 so the choice is not made by the result.)

### H-L6 — What does Zukin et al. (2009) say about which retail categories signal gentrification, and does that contaminate the gap screen?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E7 · Maturity and 2033 Projection
- **Current answer:** [was: Axis 2 (Rising) · D9] — (Zukin, Trujillo, Frase, Jackson, Recuber & Walker, "New Retail Capital and Neighborhood Change: Boutiques and Gentrification in NYC", City & Community 8:47–64. Harlem/Williamsburg: gentrification arrives as independent boutique retail. Question for Loci: a cafe "gap" closing may be a trajectory signal, not a need being met — should discretionary-category arrivals feed rising.py rather than gaps?)

### H-L8 — Does Waldfogel (2008) "median consumer" logic mean "comparable areas" must be defined on composition, not income alone?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** [was: X6 · D8] — (J. Urban Econ. 63:567–582. Local private goods follow the locally dominant group's preferences. If true, a citywide reach per category is mis-specified for categories whose demand is composition-driven.)

### H-L9 — What does Zenk et al. (2005) establish about supermarket access by race net of poverty, and which access metric did they use?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** [was: X6 · M-tier access metric choice] — (Detroit tracts, GIS distance to nearest supermarket; segregation, not poverty alone, drives access. Precedent for a distance-based rather than count-based "missing".)

### H-L10 — Does Powell et al. (2007) national ZIP-level food-store availability by race/SES replicate Meltzer & Schuetz's NYC pattern, and is its establishment-count method close enough to Loci's to borrow?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** [was: X6] — (Preventive Medicine 44:189–195. National ZIP counts by store type; count-based, so a useful contrast with Zenk's distance-based access.)

### H-L11 — Do Haltiwanger, Jarmin & Krizan (2010) give a usable displacement/complementarity estimate for the minimum-viable-catchment check?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E5 · Deferred
- **Current answer:** [was: O6] — (J. Urban Econ. 67:116–134, big-box entry vs mom-and-pop exit.)

### H-L12 — Chapple & Jacobus (2009): where does gap-filling retail actually succeed, and does that argue for an income floor in Axis 1?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E5 · Deferred
- **Current answer:** [was: Axis 1 (invest.py)] — (Bay Area; revitalization gains concentrate in middle-income, not poorest, neighborhoods.)

### H-L13 — Which cities are actively trying to become walkable, and which of them could be Loci's second city?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E8 · Second-City Feasibility
- **Current answer:** — (Owner question, 2026-09-09. Candidate signals: adopted 15-minute-city or complete-neighborhoods plans (Paris, Melbourne, Portland), parking-minimum repeal and upzoning (Minneapolis, Austin, Buffalo), pedestrianisation and bike-network capital programs, walkability targets in a comprehensive plan. A city *trying* to become walkable is the interesting second-city case: its retail gaps are the ones policy is about to make actionable, whereas an already-walkable city just replicates NYC. Output should be a short ranked list with the policy citation per city and whether the universal sources in CONTEXT.md §10 cover it.)

### H-L14 — Do retail agglomeration effects concentrate around new residential construction, and how long is the lag?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** (Li 2022 JEG, within ~500 ft, 1–3 yr lag. Precedent for the matched-event-study design and effect sizes; review which categories showed demand response vs supply-driven agglomeration.)

### H-L15 — When new housing enters a low-income neighbourhood, what types of retail follow or decline?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** (Asquith/Mast/Reed 2023 REStat. Amenity effects exist but are too small to offset rent increases; separates which categories are demand-elastic vs gentrification-driven.)

### H-L16 — Do entry and exit rates in retail rise together in gentrifying tracts, and what does that tell us about supply-vs-demand mechanisms?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** (Glaeser/Luca/Moszkowski 2023 JEG. Gentrifying tracts show faster entry AND exit; reframes the null from "supply shifts" to "category churn without net growth." Key for understanding survivor truncation bias in T7.)

### H-L17 — What do NYC Comptroller vacancy reports and HR&A 2024 say about post-COVID retail churn vs net growth?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** (NYC Comptroller 2024, Comptroller 2019 baseline, HR&A 2024 "The Retail Reckoning". Quantifies churn patterns and structural change; benchmarks expectations for entry rates around new residential supply.)

### H-L18 — Should address demographics be catchment-weighted (aggregated over the address's walk-shed) rather than the lot's own tract?
- **Status:** open
- **Tier:** P3 — literature
- **Unblocks:** E6 · Premium Amenities
- **Current answer:** — (Today (D60) each address carries its tract's ACS values 1:1. A retail thesis about who is within reach of a gap wants the demographics of the walk-shed, which is far larger than a tract in Manhattan and smaller than one in eastern Queens. Unblocks: investor-grade catchment reads on gap clusters. Fails if: tract-direct and catchment-weighted rank the same top-50 clusters, in which case the extra modelling buys nothing.)

### H-D1 — Does LODES block-level noise infusion matter after hex aggregation?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (LODES8 tech doc, noise model section.)

### H-D2 — Which of the 15 categories map cleanly onto Overture's taxonomy, and which are lossy?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Read the Overture categories file before writing the adapter. Expect laundromat, nail and tailor to be the lossy ones; record mapping confidence.)
- **Touched 2026-09-05 (D42, `src/loci/categories.yaml`):** the current per-slug Overture `categories.primary` lists are now recorded in one place (`sources.overture` per slug) alongside each slug's NAICS 2022 anchor, but lossiness/confidence per mapping is still not scored — this question stays open.

### H-D3 — Does Google Nearby Search's 60-result cap bias enumeration in dense hexes?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** — (20 results per page, 3 pages max, radius semantics. If dense hexes saturate, the sample design needs smaller radii or per-type queries — decide before spending calls.)

### H-D4 — How many NYC ZIPs have ZORI coverage in both 2013 and 2023?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Count before committing rent as an outcome. CONTEXT.md already labels it the weakest of the four.)

### H-D6 — ACS tract vintages: 2009–13 is on 2010 tracts, 2019–23 on 2020 tracts. Crosswalk, or interpolate per vintage?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (LODES needs no crosswalk; ACS does — unless dasymetric interpolation onto hexes is run separately per vintage, which sidesteps it. Decide.)

### H-D7 — Do the MTA entrances and hourly ridership datasets cover the Staten Island Railway?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (If not, Staten Island's transit control is systematically understated, which interacts with X5.)

### H-D8 — Which DCWP license categories are in scope beyond laundries?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Freshness is already a ticket; this is about coverage of the 15 categories.)

### H-D9 — Which NYS Liquor Authority license descriptions denote a bar?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (The active-licenses file `9s3h-dpkz` has no "bar" type. The adapter currently emits `bar` for Food & Beverage Business, Club, Cabaret and Bottle Club, skips Restaurant (DOHMH anchors it) and skips "Additional Bar" riders (they attach to an existing premises). Confirm against the SLA licence-class guide whether Food & Beverage Business is the tavern class, and whether a material share of bars hold a Restaurant licence.)

### H-D10 — Is a Foursquare "Medical Center" a neighbourhood clinic, and is a Foursquare "Gym and Studio" a gym?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** — (Medical Center is 6,971 of the 10,579 Foursquare clinic rows before the freshness gate and looks like a catch-all; Gym and Studio is a level-2 label used as a leaf on ~4k rows. Both are exactly what the Google sample on clinic/fitness should test — run `loci validate --categories clinic,fitness` and compare undercount by source.)

### H-D12 — Is there any public per-entrance transit volume to replace the even split across station entrances?
- **Status:** open
- **Tier:** P3 — data quirks
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (D76 splits MTA hourly ridership entries evenly across every entry-allowed entrance at a complex, which is wrong at 59.7% of entries — the share landing at complexes with ≥6 entrances, where one busy entrance and five quiet ones read identically. Candidates to check: MTA OMNY reader-level tap data (per-turnstile, not per-complex, if published), ADA entrance usage/elevator counts as a partial per-entrance proxy, or MTA's own entrance-level ridership estimates if any exist beyond the complex-level hourly feed. If none is public, the 800 m / distance-decay graduation test (M12) has to proceed with the even-split bias disclosed rather than fixed.)

### H-M1 — Does `tobler` carry or drop ACS margins of error through dasymetric interpolation?
- **Status:** open
- **Tier:** P3 — DNCI-era methods
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (If dropped, propagate by simulation: draw tract values from their MOE, interpolate, repeat. M5 depends on this.)

### H-M2 — How should k_c be calibrated from observed count distributions rather than by judgment?
- **Status:** open
- **Tier:** P3 — DNCI-era methods
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (CONTEXT.md §9 #2. A defensible procedure, not a number.)

### H-M3 — What does "prior decade" mean per outcome when t0 outcomes are ACS 5-year?
- **Status:** open
- **Tier:** P3 — DNCI-era methods
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (ACS 5-year begins 2005–09. A "2003" population needs Census 2000 / 2010 on 2010 geography. Define the pre-trend window per outcome before W3, or T2 is undefined.)

### H-M4 — Memory, runtime and served-node weighting for multi-source Dijkstra on the NYC walk graph
- **Status:** open
- **Tier:** P3 — DNCI-era methods
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (`nx.multi_source_dijkstra_path_length` with cutoff; how to compute population-weighted served-node shares per hex.)

### H-M5 — How sensitive is the DNCI ranking to ε in the geometric mean?
- **Status:** open
- **Tier:** P3 — DNCI-era methods
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (ε = 0.01 is stated. Sweep 0.001–0.05 and confirm the bottom decile is stable.)

### H-M6 — `pysal.spreg` GM vs ML estimation with borough fixed effects at ~7,400 observations
- **Status:** open
- **Tier:** P3 — DNCI-era methods
- **Unblocks:** E3 · Residual and Panel
- **Current answer:** — (Runtime, and how to interpret the spatial parameter alongside borough FE.)

### H-T1 — PMTiles pipeline: tippecanoe → pmtiles → static hosting → MapLibre
- **Status:** open
- **Tier:** P3 — tooling
- **Unblocks:** E4 · Validation and Artifact
- **Current answer:** — (Confirm the `pmtiles://` protocol handler and a zero-server hosting path.)

### H-T2 — OSMnx graph for NYC plus the NJ / Westchester / Nassau fringe
- **Status:** open
- **Tier:** P3 — tooling
- **Unblocks:** E2 · Access Engine
- **Current answer:** — (Download size, simplification, `network_type='walk'` filter. Threat §7.7 requires the fringe.)

### H-T3 — DuckDB `h3` extension: polyfill functions and behaviour on the NYC boundary
- **Status:** open
- **Tier:** P3 — tooling
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Which polyfill function, and does it behave at res 8/9/10 on a multipolygon with holes.)

### H-T4 — Moving geometry between DuckDB (no SRID) and geopandas / tobler without CRS confusion
- **Status:** open
- **Tier:** P3 — tooling
- **Unblocks:** E1 · Ingest and Grid
- **Current answer:** — (Convention is EPSG:4326 in the database; metric work reprojects explicitly. Where does the CRS get re-attached on the way out?)

#### Recent session decisions (D29–D56)

Logged directly by recent sessions (2026-09-14/15) rather than filed under a
tier above; IDs continue the Tier D (Descriptive) sequence. Kept together here
rather than re-sorted into Part A, since these are mostly operational/protocol
decisions pending an owner ruling, not descriptive-tier research questions.

### D29 — When closure evidence names a successor at the same address (Windclimb → D's Grab and Go), should Loci mint a POI for the successor?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P3 — infra housekeeping
- **Tag:** *data / supply*
- **Session:** 2026-09-14, abenmayor-29
- **Why it matters:** Today successor_name is recorded on the evidence row only; minting would fabricate a first-seen date (D79 tension) but the map otherwise shows a hole where a business trades.
- **Current answer:** —

### D30 — spend_ledger provider CHECK is ('places','tavily','anthropic'); plan-billed Claude CLI prose is recorded as provider 'anthropic' with usd 0 and a 'plan-billed' detail. Widen the CHECK in a migration, or keep provider = model vendor and add a billing column?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P3 — infra housekeeping
- **Tag:** *data / schema*
- **Session:** 2026-09-14, abenmayor-29
- **Current answer:** —

### D31 — verify-closures orders candidates by colocation_n then distance to the bbox centre. Should staleness of the last observation (oldest observed_on first) rank above distance, since stale POIs are the likeliest closures?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P3 — infra housekeeping
- **Tag:** *method*
- **Session:** 2026-09-14, abenmayor-29
- **Current answer:** —

### D33 — The grandfathering POI test uses a 20 m point radius; PLUTO lot polygons would make it exact (POI inside the lot). Worth the geometry ingest, given the sensitivity table (20 m -> 30 m moves grandfathered 15k -> 34k under the not-closed rule)?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P3 — infra housekeeping
- **Tag:** *method*
- **Session:** 2026-09-14, abenmayor-29
- **Current answer:** —

### D34 — db.init_schema re-renders the co-location view with evidence after sql/033 from poi_presence.colocation_view_sql(evidence=True); a single-file apply of sql/029 alone would regress it to the evidence-less form, the same class of defect as storefront_pipeline.ensure_schema reverting poi_first_seen (fixed f8142e0). Should view definitions be owned by exactly one renderer with a drift test?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P3 — infra housekeeping
- **Tag:** *infra / data-model*
- **Session:** 2026-09-14, abenmayor-29
- **Why it matters:** Two independent instances of this class of bug in D101/D103 suggest the fix belongs at the init_schema/ensure_schema level, not per-caller.
- **Current answer:** —

### D37 — Benchmarks: which of the surveyed public sources should enter the revenue model — IRS SOI nonfarm sole-proprietorship receipts by NAICS (targets the D40 owner-operated undercount), trade-association per-store anchors (NCPA pharmacy ~$5.4M, NGA grocery $380/sqft independents, NACS convenience ~$2.25M/store, laundromat $410–564k), and ICSC's measured occupancy-cost ratios by tenant category (fitness ~32%, specialty restaurant ~24%, drug store ~6%) to replace benchmarks.yaml's generic occupancy_cost_ratio. Nothing public gives per-storefront revenue.
- **Status:** open
- **Tag:** *model / data*
- **Answered by:** — (no ticket yet; candidate sources listed above)
- **Tier:** P3 — infra housekeeping
- **Session:** 2026-09-15, abenmayor-cc
- **Current answer:** —

### D38 — What counts as a ground-truth "miss": a name_key mismatch against a chain alias is not missing supply; a hit beyond 400 m is not in the catchment; propose the rule (reconcile aliases, require storefront distance ≤ 400 m, then hand-review) before any miss count is quoted.
- **Status:** open
- **Tag:** *validation / method*
- **Answered by:** `Ground-truth follow-ups: storefront coordinates in the observation grain, name reconciliation of the 45 miss candidates, deli-aware convenience terms, anchor eligibility check`
- **Tier:** P3 — infra housekeeping
- **Session:** 2026-09-15, abenmayor-cc
- **Current answer:** —

### D39 — Convenience search terms: should the protocol query 'deli' and 'bodega' alongside 'convenience store', and should each category carry several Maps terms?
- **Status:** open
- **Tag:** *validation / data*
- **Answered by:** `Ground-truth follow-ups: storefront coordinates in the observation grain, name reconciliation of the 45 miss candidates, deli-aware convenience terms, anchor eligibility check`
- **Tier:** P3 — infra housekeeping
- **Session:** 2026-09-15, abenmayor-cc
- **Current answer:** —

### D40 — Anchor eligibility: how did a fenced construction lot (545 Sackett St) pass as a 'commercial' address-level anchor; should address-level recommendations require a Storefront Registry or building-class check?
- **Status:** open
- **Tag:** *validation / rigor*
- **Answered by:** `Ground-truth follow-ups: storefront coordinates in the observation grain, name reconciliation of the 45 miss candidates, deli-aware convenience terms, anchor eligibility check`
- **Tier:** P3 — infra housekeeping
- **Session:** 2026-09-15, abenmayor-cc
- **Current answer:** —

### D41 — Instrument writes vs re-baseline windows: should `ground-truth record` be batched to the start of a planned re-baseline instead of running ad hoc, given each closed verdict moves the hash under stamped artefacts?
- **Status:** open
- **Tag:** *infra / policy*
- **Answered by:** — (no ticket yet; rule proposal pending owner ruling)
- **Tier:** P3 — infra housekeeping
- **Session:** 2026-09-15, abenmayor-cc
- **Current answer:** —

### D45 — Should the `.sql.draft` pattern be the standing rule for D25's uncommitted-migration hazard?
- **Status:** open
- **Answered by:** —
- **Tier:** P3 — infra housekeeping
- **Tag:** *infra / policy*
- **Session:** 2026-09-15, abenmayor-db
- **Why it matters:** sql/037_citibike_od.sql was developed as `037_citibike_od.sql.draft` (invisible to `init_schema`'s `*.sql` glob), tests executed the draft text against a temp DuckDB, and the rename was an announced, peer-cleared event (D108). If adopted, the rule belongs in CLAUDE.md's concurrent-sessions section, and `check-tickets` could refuse a tree with both a `.sql` and a `.sql.draft` of one number.
- **Current answer:** —

### D46 — What counts as `confidence: verified`: does a store-locator page count suffice, or must a person reconcile the locator against detect before a row is promoted?
- **Status:** open
- **Answered by:** — (quarterly re-verification pass, D109; not ticketed until the first pass is scheduled)
- **Tier:** P3 — infra housekeeping
- **Tag:** *validation / method*
- **Session:** 2026-09-15
- **Why it matters:** The quarterly re-verification pass (D109) treats a store-locator count as the only path to `verified`, but the proposal never specified whether reading the locator page is itself sufficient or whether the count must be cross-checked against `chains.brand_snapshot` before the row is promoted. As of 2026-09-15, 0 of 123 admitted rows are `verified` and 0 carry a `last_verified` date, so the first quarterly pass needs this settled before it runs, not after.
- **Current answer:** —

### D47 — Paid sourcing: request a RetailStat quote now, or stay free until there is revenue?
- **Status:** open
- **Answered by:** — (paid-source decision, owner's call; GTM-191 covers the free-source half)
- **Tier:** P3 — infra housekeeping
- **Tag:** *infra / cost*
- **Session:** 2026-09-15
- **Why it matters:** RetailStat Location (#23, P2, gap f, $10,000/yr tier floor, no published price) is the one paid source that replaces real hand work outright — it carries brand AND individual store location, standing in for the locator hand-count and `signed_leases`. Coresight and Data Axle are lower priority (Data Axle at $8,000/yr is already in the $23k sprint subset and is the best value of the three, but is national-brand grain and cannot place a store at a borough for Coresight, or covers all fifteen categories but still needs a human curator for trajectory). The decision gates whether GTM-xxx (source expansion) scopes a paid quote request into the same session as T1-T6 or defers it.
- **Current answer:** —

### D49 — Premium services: what business types fall in, and how could a price signal be obtained?
- **Status:** in-progress
- **Tag:** *data / sourcing*
- **Answered by:** — (no ticket yet; candidate answer above)
- **Tier:** P3 — infra housekeeping
- **Session:** 2026-09-15, abenmayor-cc
- **Why it matters:** The owner asked what data Loci holds on "premium services" and how to get price. Inventory (read-only, 2026-09-15): no POI table carries a price tier, rating, or review count; `webmap/data/character.json` is land-use character (D-independent), not retail tier; the premium track is Axis 3 (CONTEXT §11, D22/D28, `model/premium.py`) and covers types outside the 15 slugs (wine bars, bathhouses, spas/med-spas, boutique fitness, climbing, padel, pet grooming, florists, dry cleaning). Fine-grained source categories survive only in `staging.poi.attrs` (Overture `primary_category`; Foursquare `labels`) and nothing downstream reads them; they cleanly split fitness (gym/yoga/pilates/cycle/climbing), nails_beauty (nail salon/beauty salon/spa/day spa/waxing/lash), hair_barber (salon/barber), cafe_bakery (coffee shop/bakery/bagel/donut), partially clinic; restaurant has cuisine only. Price probes (47 budgeted Text Search calls, ~$1.65 at Enterprise, ledger 8,992 → 9,039; USD not written to `analysis.spend_ledger` because its `kind` CHECK admits only report/verify — record this gap): probe 1 (32 calls, 2 per category, `priceLevel` only) returned price for 5/32, bars and cafés only, services zero; probe 2 (15 food/bar calls, `priceLevel` + `priceRange`) returned price for 12/15, the two fields co-occurring perfectly (`priceRange` = `{startPrice, endPrice}` in USD units, open-ended top e.g. "$100+"), the three blanks being one Permanently-closed match and two wrong-business matches. Probe 1's restaurant zero was a two-POI sample with bad matches, not a coverage fact. Name match of the top hit was 18/32 and 7/15, so any price ingest needs a name-and-distance acceptance rule first. `priceLevel`, `priceRange`, `rating`, `userRatingCount` are all Enterprise SKU ($35/1,000 vs Pro $32/1,000 that the closure check uses; Google bills the highest SKU touched, so +9.4% per call). Interceptor reads the same "$$" labels from Maps results for free, but only at supervised-session scale (≈1,000 POIs per 30-min segment under the D36 cap) and with the same food-only coverage; systematic city-wide collection through the browser would be scraping in substance, outside the D36 standing. No channel gives service prices (salon/gym/clinic pricing lives on booking sites); for services, business sub-type is the only proxy. Owner 2026-09-15: assessment only for now, no pilot.
- **Candidate answer (not ruled):** (1) surface `staging.poi.attrs` sub-types into `poi_presence` as `subcategory` so premium sub-types are a filter, not a new source; (2) if ratings become useful for Axis 3, run closure checks at Enterprise and capture `priceRange`/`priceLevel`/`rating`/`userRatingCount` in one pass behind a match rule, food categories only; (3) widen `spend_ledger.kind` to admit `probe`; (4) no price budget line on its own.
- **Partial ruling (owner 2026-09-15):** free price-label capture in the ground-truth protocol approved and shipped (b871dbb; food-only in practice, supervised scale only). Still open: surfacing `staging.poi.attrs` sub-types as a premium filter, whether to pay the Enterprise SKU for price/rating on closure checks, widening `spend_ledger.kind`.
- **Current answer:** —

### D50 — Three reporting quibbles in the D111 growth test.
- **Status:** open
- **Answered by:** —
- **Tier:** P3 — infra housekeeping
- **Tag:** *model / reporting*
- **Session:** 2026-09-15, abenmayor-db
- **Why it matters:** (a) `bike_growth_verdict` assumes the run is the primary vintage; when `--asof` is the confirmatory one the P7 line should say so instead of "the confirmatory vintage has not been run". (b) The P9 lagged-growth pre-trend requires a lag column the CLI does not build (`build_panel` has `bike_growth_lag_asof`; the retrodiction run has no flag for it) — moot for a null result but mandatory before any positive result could ship. (c) The run stamps the baseline table's supply hash (d993b3802c6a) rather than the live one (ba944e18c57b); provenance should read `live_supply_hash`. Fix all three in one small ticket before the growth test is ever re-run.
- **Current answer:** —

### D51 — Should the canonical order be a `loci rebaseline` CLI command?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P3 — infra housekeeping
- **Tag:** *infra / method*
- **Session:** 2026-09-15, abenmayor-cc
- **Why it matters:** Session 28 (2026-09-15, D112) ran the D106 canonical order as a scratch zsh script with per-step timing, stop-on-failure and resume-from-step. It caught one designed non-zero exit — `age-fit fit` returns 1 when it refuses the pharmacy curve (D69/D71) — that a naive runner treats as fatal, and it recorded per-step seconds nobody had written down for eleven of the steps. A `loci rebaseline [--from STEP] [--dry-run]` command would make the order a machine-checked artefact (a drift test against the order documented in CHECKPOINT), treat the designed refusals as designed, write the per-step timings into the run's own log for the decision entry, include the post-address-gaps re-sweeps (od-measures, growth-measures) that peers otherwise forget, and give peers one process to announce and one lock to wait on. Open; needs a ticket under E2.
- **Current answer:** —

### D52 — Should the supply freeze marker bind direct evidence writes?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P3 — infra housekeeping
- **Tag:** *infra / policy*
- **Session:** 2026-09-16, abenmayor-db
- **Why it matters:** D115 made `supply-asof advance` honour data/SUPPLY_FREEZE / LOCI_SUPPLY_FREEZE, the first machine-enforced freeze. Direct writers of closure evidence (ground-truth record, report closure checks, chains refresh) still ignore it. Proposal: one `supply.assert_not_frozen(con)` guard in every poi_status-affecting writer, with --force for the steward.
- **Current answer:** —

### D53 — Review ask 5: should the dated-article filter reject pages without a parseable date outright?
- **Status:** open
- **Answered by:** — (not ticketed)
- **Tier:** P3 — infra housekeeping
- **Tag:** *model / reporting*
- **Session:** 2026-09-16, abenmayor-db
- **Why it matters:** A bare homepage and a Getty image-search page passed the web-hit filter on the 2026-09-15 notes. Cosmetic for a no-trade note; for a full memo a source with no date is not evidence. Proposed rule: require a parsed publication date within the memo's window or drop the hit and count it in the footer.
- **Current answer:** —

---

## Answered

### D56 — AC-1 base rate: the citywide 12-month opening rate for a `bathhouse_sauna` category is unknown until the category is admitted. Hand-enumerate it before pre-registering the Gowanus decision.
- **Status:** answered
- **Answered by:** `Hand-enumerate the Gowanus bathhouse base rate (QUESTIONS D56)`
- **Tier:** P1 — decision value for AC-1
- **Current answer:** Answered 2026-09-17 (owner, D123): citywide rate 1.7/yr (0.9–2.9), 3.4/yr since 2024, plus named pipeline; bathing-primary day spas count in the stock. Memo docs/bathhouse-base-rate-2026-09.md.

### M1 — Is the measured retail gap real, or a POI-coverage artifact?
- **Status:** answered
- **Prediction:** P3
- **Answered by:** `Design stratified coverage validation sample` · `Run Google Places ground-truth enumeration on sampled gap addresses` · `DOHMH-anchored undercount calibration (address level)` · `Coverage-bias chart` · `USDA SNAP retailer adapter (ANCHOR for grocery/convenience)` — CHECKPOINT D90 (coverage-bias gate: 7.6% [6.5–8.8] true-hole rate at an 800 m network threshold, no detectable income gradient); the §9.12 radius sweep (800 m validated vs 400 m card radius) stays open.
- **Fails if:** the undercount rate by income decile is materially higher in hexes flagged as underserved than in their well-served peers.
- **Current answer:** Partly, and badly, for at least one category. 2026-09-02: adding the SNAP near-census cut bodega/convenience gap hexes from **166 to 16** — 90% of that gap type was an OSM/Overture coverage hole, not a missing business. Hardware, fitness and clinic gaps (the current top three) still rest on OSM/Overture only; the Google sample (`loci validate`) is aimed at those next. **2026-09-03 (CHECKPOINT D29/D30):** the raw Google survival rates (hardware 58%, fitness 29%, clinic 0%) turned out to measure the Google type map, not coverage — split each result into geometry-artifact vs true coverage hole. Corrected true-hole rates: hardware 5% [2–12] (not disproven — Google's type is an upper bound), fitness 21% [10–37] (real hole, needs an anchor, M7), clinic 0% [0–15] but unfalsifiable by construction (loci excludes doctor's offices, Google doesn't) — clinic dropped from headline claims pending a re-anchor to licensed urgent care (D30). 2026-09-09 (D58): the validator's sampling frame is now gap ADDRESSES stratified income decile × missing/present per category, both sides measured at the lot's point at 649 m; the 2,970 hex-frame rows are frozen and never pooled. GTM-48 still needs a budget approval to run.

### M6 — For each loci category, are Google's included types narrower or wider than loci's definition?
- **Status:** answered
- **Answered by:** `Google type-map audit per category`
- **Current answer:** Answered 2026-09-08 (GTM-105, D50): both, per category — wider for restaurant/bar/grocery/convenience/hair/nails, narrower for cafe_bakery and fitness; the structural 20-result cap invalidated D29's clinic/fitness rates. Remainder moved to M8 (radius) and D23 (anchor contradictions).

### M8 — Should the validator compare against network distance rather than a straight-line radius?
- **Status:** answered
- **Answered by:** `Validator: network distance or circuity correction`
- **Current answer:** Answered 2026-09-08 (D53): circuity correction adopted (measured 1.233, giving a 649 m radius) instead of a network re-measurement. Closed.

### M9 — How do Loci's deduped POI counts compare with Census ZIP Business Patterns establishment counts, per category and ZIP?
- **Status:** answered
- **Prediction:** —
- **Answered by:** (not ticketed yet — Linear cleanup 2026-09-05 adds one) — CLI subcommands ingest-zbp and zbp-compare; table analysis.zip_coverage_check; CHECKPOINT D40 — answered by its own dated Current answer below (ZBP per-source run, 2026-09-05; CHECKPOINT D40/D47).
- **Fails if:** ratios are far above 1 in categories that are NOT sole-proprietor-heavy — that would mean the POI feeds overcount supply (stale or duplicate records), which tightens every reach value and hides gaps.
- **Current answer:** Expectation (not a P1–P3 prediction): Ratios near 1 for employer-heavy categories (pharmacy, bank, grocery, hardware); above 1 for sole-proprietor-heavy categories (nails, barber, tailor) because CBP/ZBP counts only establishments with paid employees. First run (2026-09-05, ZIPs with population ≥1,000; ratio = Loci POIs / ZBP establishments): median ratio by category — childcare 0.85, clinic 0.95, laundry 1.33, pharmacy 1.48, grocery 2.06, bank 2.17, convenience 2.31, hair_barber 2.79, restaurant 3.16, hardware 3.21, cafe_bakery 3.51, fitness 5.92, bar 6.00, nails_beauty 7.96. Share of ZIPs above 2× is 94–98% for restaurant, cafe_bakery, fitness, bar, nails. Pattern: the categories closest to 1 are the OSM/Overture-only ones (childcare, clinic, laundry, pharmacy); the largest overcounts are exactly the license-registry-anchored categories (DOHMH → restaurant/cafe, NYS DOS → hair/nails, SLA → bar) plus fitness. Consistent with D36 (DOHMH turnover duplication) and suggests SLA and NYS DOS anchors also carry closed or non-storefront licensees. Bank at 2.17 and hardware at 3.21 are not explained by the employer-only bias and point to POI duplication or ZIP assignment error. Caveats: POI→ZIP uses a majority-vote hex→ZIP crosswalk from PLUTO lots (no ZCTA polygons in the DB); ZIP population is summed dasymetric hex population; CBP excludes non-employers and noise-infuses cells from 2017 on; NAICS self-classification bleeds between adjacent formats (Meltzer & Schuetz). Next: (a) rerun per SOURCE (which feed drives each overcount), (b) ZCTA polygons for a proper ZIP join, (c) use `analysis.zip_category_establishments` size bands for D9 and establishments-per-resident for O6.
 UPDATE (per-source run, CHECKPOINT D47): the overcount is mostly uncorroborated single-source records — dropping them gives restaurant 1.09, cafe 1.12, hardware 0.86, hair 0.65, but bar 1.54, fitness 1.74, nails 1.77 remain; fitness and hardware have NO license anchor (Overture+Foursquare only), so the "license-anchored" framing above applies to restaurant/cafe/hair/nails/bar only. Staleness untestable for DOHMH and DOS because the adapters do not fetch date fields; SLA 0% expired. Residual hypothesis: dedup misses (registry name vs storefront name).

### M11 — What is the co-location structure of the 15 categories net of density, and how should 'expected presence given neighbors' enter the grade?
- **Status:** answered
- **Answered by:** (not ticketed) — scratchpad colocation.md, coloc_*.csv, session 13 (2026-09-08)
- **Current answer:** Manhattan is saturated (8/15 categories at 100% presence); structure identified off Brooklyn — hair↔nails partial r 0.65, hardware↔grocery 0.50. Use as a grade input (expected presence), not a finder (session 13, 2026-09-08).

### M14 — Should fitness's Google type map drop sports_club and marina, the type-map defect the GTM-48 coverage validation found?
- **Status:** answered
- **Answered by:** `Fitness type map: remove sports_club and marina from GOOGLE_TYPES (validator-only)`
- **Current answer:** Ruled 2026-09-14 (owner "yes to all 4," CHECKPOINT D90): drop sports_club and marina from fitness's GOOGLE_TYPES. Implementation GTM-173.

### M15 — Should cross-category name+distance dedup run before per-category dedup?
- **Status:** answered
- **Answered by:** `Co-located POIs: tri-state poi_is_open predicate, analysis.poi_colocation view, closure gate on the supply set (owner rule 2026-09-14)`, `Cross-category name+distance dedup before per-category dedup (Lion's Milk / GTM-153 proper)`
- **Current answer:** Ruled 2026-09-14 (D90) and shipped 2026-09-15 (D101, commit 13f0fec): one global cross-source union-find on name-core + distance; 12,928 merges, precision 0.970 [0.915, 0.990] on a fresh 100-pair audit sample.

### D2 — Which category drives the gap?
- **Status:** answered
- **Prediction:** —
- **Answered by:** `DNCI: weighted geometric mean + unit tests` · `Per-category radar small multiples for top gap clusters` — CHECKPOINT D88 per-category coefficients: restaurant own-category gap −0.89 [−1.44, −0.33], p = 0.0018, the only category to survive Bonferroni — no restaurant within 400 m predicted fewer restaurant openings.
- **Fails if:** n/a — descriptive. The question: in low-DNCI hexes, is the missing piece essentials (grocery, pharmacy, laundry) or food & gathering, and does gap composition cluster into recognisable types? Changes what an "opportunity" means.
- **Current answer:** —

### D5 — How far apart do same-type businesses sit, and how far is the nearest missing business from a gap hex?
- **Status:** answered
- **Answered by:** `Spacing and nearest-missing distance diagnostics` · `Cross-source POI dedup / entity resolution`
- **Current answer:** Same-type spacing is tight (median 0–200 m); the nearest missing business sits a median 860–1,030 m from a gap hex — a 10–17 min band, not a hole. `loci spacing`, 2026-09-02.

### D6 — What is the empirical distribution of hex-to-nearest-business network distance per category, and should each category's "missing" threshold be set from it?
- **Status:** answered
- **Answered by:** `Redefine 'missing' via per-category reach (monotonicity fix)`
- **Current answer:** Built and verified 2026-09-05 (CHECKPOINT D34): fixed per-category reach passes the monotonicity test the old shared-window rule failed. The calibration statistic itself continues as D8.

### D8 — What statistic sets reach(c) without fixing the per-category gap rate, and how should the lead category be ranked?
- **Status:** answered
- **Answered by:** `Redefine 'missing' via per-category reach (monotonicity fix)`
- **Current answer:** External walk-time tiers adopted 2026-09-05 (D41, reach_tiers.yaml) as the only non-tautological calibration; continuous max nearest/reach ranking ships, the binary exactly-one list rejected as a quantile artifact.

### D15 — Should `age_fit` extend to pharmacy and childcare, the two categories that also passed the CEX survey gate and whose supply-revealed placebo b(w18) signs are the OPPOSITE of bar's (−0.846 and −0.574 against +1.256)?
- **Status:** answered
- **Answered by:** (not ticketed)
- **Current answer:** childcare SHIPS (age-fit applied, D69, pooled b +2.744); pharmacy REFUSED under the tightened F2 gate — its own regressor's Brooklyn CI includes near-zero (D64→D66→D69).

### D16 — Does a category have headroom (room for more of the same type) given current plus incoming residents, and does headroom predict entry?
- **Status:** answered
- **Answered by:** `Per-category clustering-vs-saturation coefficient for the grade (from the headroom backtest)`
- **Current answer:** Headroom has no predictive skill (bars/cafés cluster rather than saturate); shipped as `density_elasticity.yaml` (D70, GTM-138) and superseded as the ranking statistic by supply-ratio-vs-baseline (D73).

### D17 — Should the eligibility gate be POI-free (PLUTO retail floor area within 800 m) rather than ≥12-of-15 categories present within 800 m of the current supply set?
- **Status:** answered
- **Answered by:** (not ticketed yet)
- **Current answer:** Gate removed entirely by owner ruling 2026-09-13 (D75); the built-form-gate question is moot for eligibility, survives only as a possible ranking feature.

### D18 — Should clusters be ranked by capped units or by mean gap_score?
- **Status:** answered
- **Answered by:** (not ticketed yet)
- **Current answer:** Settled by owner ruling 2026-09-13 (D83): clusters rank by `cluster_density_400m`, Σ`units_capped` as tiebreak; `--rank-by units` kept selectable.

### D20 — Can site revenue be predicted from public data well enough to grade the economics of a recommendation?
- **Status:** answered
- **Answered by:** Site-revenue model v0 (D81, GTM-150): CEX spend pool × fitted capture share, leakage calibrated to Economic Census 2022 county receipts, gated by a leave-one-ZIP-out backtest and cross-category placebo.
- **Current answer:** Restaurant alone passes the leave-one-ZIP-out backtest (ρ_oos 0.763) and grades C (D81, GTM-150); nine other categories honestly not modelled. v0.2 refit (D91) tightens levels 3–5×.

### D22 — What is the numeric Wilson-upper coverage-grade ladder (G9) that replaces presence-only grade A?
- **Status:** answered
- **Answered by:** `Coverage grade G9: numeric Wilson-upper ladder replacing presence-only grade A`
- **Current answer:** Ruled 2026-09-14 (owner "yes to all 4," D90): Wilson-upper ladder — coverage-hole rate ≤10% → A, ≤25% → B, else C. Implementation GTM-174.

### D28 — Should a system-wide zero-ridership day (2026-02-23) stay in the per-weekday divisor?
- **Status:** answered
- **Answered by:** (not ticketed) — CHECKPOINT D102
- **Current answer:** Answered 2026-09-15 (owner, D108 addendum): the zero-ridership day stays in the per-weekday divisor.

### X2 — After controls, where is retail materially undersupplied relative to comparable hexes, and is the residual spatially clustered?
- **Status:** answered
- **Prediction:** —
- **Answered by:** `Residual extraction + opportunity score` · `Moran's I + spatial error/lag model` — CHECKPOINT D88 per-category coefficients: restaurant own-category gap −0.89 [−1.44, −0.33], p = 0.0018, the only category to survive Bonferroni.
- **Fails if:** Moran's I on the residual is significant and the spatial-error re-estimate changes which hexes sit in the tail. Report both models either way.
- **Current answer:** —

### T1 — Does a negative residual in 2013 predict above-average growth 2013→2023?
- **Status:** answered
- **Prediction:** P2
- **Answered by:** `Main growth regression (prediction P2)` · `Assemble outcome variables`
- **Current answer:** REJECTED, wrong sign. CONTEXT.md §0 (2026-09-01 headline): regressing 2013→2023 growth on the 2013 residual gives β = +0.069 (p=4.7e-16) — over-retailed hexes grew MORE.

### T2 — Does the 2013 residual also "predict" the prior decade?
- **Status:** answered
- **Answered by:** `Pre-trend test (2003→2013)`
- **Current answer:** Parallel trends BROKEN. CONTEXT.md §0: the 2013 gap also "predicts" prior (2002→2013) retail growth (β=+0.27) — retail and residents co-move, the gap does not identify latent opportunity.

### T3 — Does a placebo outcome with no mechanism return a null?
- **Status:** answered
- **Answered by:** `Placebo outcome`
- **Current answer:** Clean null. CONTEXT.md §0: the placebo confirms the T1/P2 reversal is real, not a specification artifact.

### T11 — Does the opening-time score (supply ratio, gap score) predict survival to today, and does it beat a placebo? · *predictive*
- **Status:** answered
- **Answered by:** `Retrodiction: does supply ratio at opening predict survival? (gating test for any decision-value claim)` — GTM-158, Done
- **Current answer:** Answered 2026-09-14 (D88, GTM-158 Done): the frozen screen ranks retail streets (AUC 0.866 vs 0.854 no-score), not unserved demand; the one survival-adjacent outcome tested (LL157 go-dark) returns a null. Cost-of-search only — decision value stays unclaimed.

### O4 — Where could each neighborhood reach by 2033, and does the projection survive a backtest? · *predictive*
- **Status:** answered
- **Answered by:** `2033 trajectory projection with scenario bands` · `Backtest the projection (fit 2000→2013, predict 2013→2023)` · `Assemble the multi-decade neighborhood trajectory panel`
- **Current answer:** Settled 2026-09-02: fails as a 10-yr point forecast (only ~12% better MAE than naive persistence) but rank order survives (corr 0.96) — ships as ranking + scenario illustration, never a point forecast.

### O9 — Should the three parallel uncommitted streams (comps, conveniences, spend.yaml) be kept, parked, or deleted? · *governance / scope*
- **Status:** answered
- **Answered by:** owner decision with investor-agent review (as O6–O8 already require)
- **Current answer:** Owner directed 2026-09-05 to resume all three streams; conveniences and spend wired in, comps thin (BizQuest, only restaurant clears the ≥8-row bar); demand annotation fixed 2026-09-08 (D49).

### H-L2 — What have Meltzer & Schuetz, and Meltzer & Capperis, already established about NYC neighbourhood retail?
- **Status:** answered
- **Unblocks:** E3 · Residual and Panel
- **Answered by:** — (not ticketed)
- **Current answer:** Read and applied 2026-09-05 as `demand.yaml` + the `demand_caveat` annotation in gaps.py; findings feed D9, X6 and H-L6.

### H-L7 — What covariates does Schuetz, Kolko & Meltzer (2010, 58 metros) find for retail density, and can they make the screen city-agnostic?
- **Status:** answered
- **Unblocks:** E8 · Second-City Feasibility
- **Answered by:** — (not ticketed)
- **Current answer:** Closed for the D7 purpose 2026-09-08 (D54): the density↔retail relationship replicates citywide but dissolves under a density control within MN+BK; renter_share is a density proxy, not a mode variable — kept as a demand covariate.

### H-D5 — How does DOHMH represent closed establishments within the 3-year rolling window?
- **Status:** answered
- **Unblocks:** E1 · Ingest and Grid
- **Answered by:** — (not ticketed)
- **Current answer:** Found 2026-09-05 (CHECKPOINT D36, 2026-09-05 session): the DOHMH adapter dedupes by CAMIS but never drops closed establishments — the source of the 13–14% exact-coordinate same-type share; fix is an active-establishment filter before dedup.

### H-D11 — Are same-category cross-source pairs within 25 m the same business under two names?
- **Status:** answered
- **Unblocks:** E1 · Ingest and Grid
- **Answered by:** — (not ticketed)
- **Current answer:** 2026-09-05: of 24,908 restaurant pairs within 15 m, only 0.09% share a normalized name — cross-source naming is not the dominant duplication driver (see H-D5).

### D35 — Ground-truth subjects: all 15 open ledger recs are one point (Gowanus bbox centroid). Add address-level recs for the four 2026-09-14 report addresses via `loci recommendations add` so the instrument checks real storefronts? Owner call.
- **Status:** answered
- **Answered by:** `Ground-truth browser session: verify the ledger anchors with Interceptor and score the miss view`
- **Current answer:** Owner 2026-09-14: add the four 2026-09-14 address reports as ledger rows via `loci recommendations add`; the Gowanus bbox centroid stays as a fifth look.

### D36 — Standing of the supervised Google Maps browser session under Google's terms: same footing as the BizQuest session (fe59eb2), human-paced, owner present, ~15 anchors per session. Confirm the owner is comfortable and whether a per-session cap should be enforced in the protocol.
- **Status:** answered
- **Answered by:** `Ground-truth browser session: verify the ledger anchors with Interceptor and score the miss view`
- **Current answer:** Owner 2026-09-15: no Maps segment over 30 minutes without a 2-minute break, owner present, never unattended; written into docs/ground-truth-protocol.md §1 (commit d7c6fd1).

### D44 — 74 of 124 Citi Bike origin NTAs lose supplied_share to the 0.2 outside-universe threshold: is 0.2 right, should the universe admit QN/BX lot addresses for the denominator only, or should the share report with its outside share and no NULL cut at all?
- **Status:** answered
- **Answered by:** `Citi Bike phase 2: origin-destination leakage per NTA × category ('where residents of this gap area go') and the card line`
- **Current answer:** Answered 2026-09-15 (owner, D108 addendum): report all Citi Bike origins with the outside share always shown; no NULL cut (commit 82db230).

### D48 — Pre-chain detection: can Loci flag a one- or two-location operator BEFORE it becomes a chain (owner examples: Bathhouse, Mink)?
- **Status:** answered
- **Answered by:** — (GTM-192, tier 3 watch; the ticket title contains backticks the citation parser cannot carry, see CHECKPOINT D110)
- **Current answer:** Designed and ticketed as GTM-192 (D110): tier-3 `watch` for 1–2-location operators with an intent signal, internal-only until graduation.

### D42 — Where does OD leakage enter the revenue model if it ever graduates?
- **Status:** answered
- **Answered by:** — (not ticketed)
- **Current answer:** Answered 2026-09-16 (owner, D120): parked behind DOT ρ ≥ +0.50 with the pre-registration recorded in docs/retrodiction-2026-09.md §12.

### D43 — The Citi Bike OD category placebo's null baseline is unfalsifiable as built.
- **Status:** answered
- **Answered by:** `Citi Bike phase 2: origin-destination leakage per NTA × category ('where residents of this gap area go') and the card line`
- **Current answer:** Answered 2026-09-16 (owner, D120): residual-rank placebo with blind thresholds replaces the intersection null; 4 of 15 category-specific.

### D59 — Café revenue band on café addresses.
- **Status:** open
- **Answered by:** (not ticketed)
- **Current answer:** `cafe_bakery` revenue is unshipped by design (fails placebo, D81), so the Fazenda page had to explain away a restaurant p50 of $1.4M (`capacity_bound` TRUE on a `retailarea` 0 condo lot = the 2,000 sq ft default × $700). Should the report/page render "not modelled" for cafés instead of the restaurant row, and should `capacity_bound` refuse on `retailarea` 0 rather than default a footprint? Status: open (2026-09-17, Session 42).

### D60 — Floor area on condo lots.
- **Status:** open
- **Answered by:** (not ticketed)
- **Current answer:** PLUTO `retailarea` is 0 on condo billing lots (177 Mott / 372 Broome), and the DOF storefront registry carries sq ft only once a lease is filed. Is there a per-unit source (DOF condo unit BBLs, ACRIS, LL84 for larger buildings) that gives shop floor area before the registry catches up? Fazenda's $37,500 rent miss was entirely floor area. Status: open (2026-09-17, Session 42).

### D61 — Ledger lag for new openings.
- **Status:** open
- **Answered by:** (not ticketed)
- **Current answer:** Fazenda (opened summer 2026) is first-seen 2026-09 backfill_censored from a DOHMH permit alone; absent from Overture (2026-09-01) and Foursquare (2026-09-02). How long do new openings take to appear in each commercial source, and should the DOHMH permit be the official first-seen kind for food? Bears on the recommendations ledger's time-to-fill (D89). Status: open (2026-09-17, Session 42).

### D62 — Commuter origin–destination for Gowanus.
- **Status:** open
- **Answered by:** (not ticketed)
- **Current answer:** Loci has LODES WAC (jobs located here) but no OD or RAC, so "where do Gowanus workers come from / residents go" is unanswerable; MTA station-level ridership is not stored as a time series either. Worth loading LODES OD before the AC-1 trade-area sheet (D116-2 / D124-2), which needs a transit-time catchment? Status: open (2026-09-17, Session 42).

### D63 — Category tier / TIER_WEIGHTS: define or retire?
- **Status:** open
- **Answered by:** GTM-211
- **Current answer:** Raised 2026-09-21 (glossary audit, D132). `categories.py` still carries a 1–4 category tier with DNCI weights; charter A4 retired DNCI, no scorer reads the weights, yet they are rendered into CATEGORIES.md and drift-tested. Either the tier means something in the address era (then define it in §4.2) or it is dead and the drift test guards a fossil. Also open from the same audit, lower stakes: `coverage`, `ledger`, `cluster`, `vintage` and `storefront` each carry several meanings and got no canonical names beyond a "say which" note. Status: open (2026-09-21, Session 43).

---

## Dropped

### C1 — Does adding daily-needs retail to a transit-rich, underserved hex *cause* residential growth?
- **Status:** dropped
- **Prediction:** —
- **Answered by:** `Identification strategy: quasi-experimental variation`
- **Dropped:** charter v2 (2026-09-16, D116) — the causal retail→growth thesis was tested and wrong-signed (D1/D88); Loci does not forecast appreciation.
- **Fails if:** no plausibly exogenous source of variation in retail supply can be found (candidates: historic rezonings, the L-train shutdown). Without one the project makes no causal claim, and the memo says so (CONTEXT.md §7.2).
- **Current answer:** Out of scope at four weeks. Phase 5.

### C2 — Does the effect appear in behaviour before it appears in residence?
- **Status:** dropped
- **Prediction:** —
- **Answered by:** `Foot-traffic outcome`
- **Dropped:** charter v2 (2026-09-16, D116) — the causal retail→growth thesis was tested and wrong-signed (D1/D88); Loci does not forecast appreciation.
- **Fails if:** foot-traffic data is unaffordable within the ~$400 headroom after the validation sample is enlarged, which has priority.
- **Current answer:** Phase 5, budget-dependent. **Budget premise superseded 2026-09-13 (D76):** the ~$200–400/yr assumption in CONTEXT.md §3.5 is stale — in 2026 Advan via Dewey Data is $3,600/yr and academic-only, Placer.ai/Replica/Cuebiq are enterprise-only with no published price, and MTA turnstile data (the free legacy alternative) is discontinued. Free proxies (transit_entries_400m, jobs_400m) were built instead (D76) and validate at ρ +0.79 headline / +0.56 [0.14, 0.83] Brooklyn-only — good enough for card context, not for this question. The behavioural-outcome question itself — does foot traffic move before residence does — stays deferred: a card-context correlate at one point in time says nothing about lead/lag, which is what C2 actually asks.

No other entry currently clears the dropped bar (out of scope per CHECKPOINT's SCOPE
CORRECTION, or made moot). Left **open** on purpose, flagged here for a future owner look
rather than guessed shut:

- **T4, T5, T6** (MAUP/spatial robustness, gap-closure convergence, retail-lead/lag timing) —
  all three test or extend the residual/growth thesis that CONTEXT.md §0 and T1/T2/T3 already
  found REJECTED with a broken pre-trend (2026-09-01 headline finding). Nothing in QUESTIONS.md
  or CHECKPOINT explicitly closes them, so they stay open rather than being guessed dropped.
- **C3** (Tier C · Causal — second-city generalization) — `Status: open`, parked at "Phase 5"
  per CONTEXT.md's phase plan. C1 and C2, the other two Tier C questions, moved to Dropped
  above (2026-09-16, D116); C3 asks a different question (does the pattern generalize, not
  does retail cause growth) and stays open on the same footing as T4–T6.
