# RQ-003 — Does a favorable-regime exit hurt the restaurants that opened during it?

Scaffolded 2026-09-23 by `loci research new`. Filled 2026-09-23 from the 3-round
interview (Ambiguity Score 0.18) recorded in `SEED.yaml`.

## Question as asked

"When a neighborhood's favorable regime ends (RQ-001's regime exit — ~60% cost-led),
does that hurt the restaurants that opened DURING the favorable stretch, or is an
'exit' usually the neighborhood succeeding (getting expensive) while incumbents do
fine?"

## Interview rulings

Owner, 2026-09-23. Every bullet below is one `constraints:` line in `SEED.yaml`.

- **Outcome is two things, not one**: restaurant survival (closure within 3 and 5
  years after the area's exit) **plus** replacement — what actually occupies the
  storefront next (restaurant, chain, other use, vacancy), read from the POI ledger
  and the LL157 storefront registry (2019+). A "good" exit and a "bad" exit can both
  show the incumbent closing; what tells them apart is what replaces it.
- **Comparison design is difference-in-differences**: incumbents (restaurants that
  opened during a favorable spell) in areas whose spell then exits, vs. the *same
  opening cohorts* in areas that stayed favorable. Not a before/after on exit areas
  alone — that can't separate "regime exit hurt them" from "restaurants of that
  vintage generally age out."
- **Exits are split by cause**: cost-led vs. demand-led vs. supply-led, using
  RQ-001's own exit-cause attribution (`attribute_exit_cause` in
  `regime_durability.py` — the pillar with the largest adverse percentile move over
  the spell's onset→exit window). The owner's framing of the question — "the
  neighborhood succeeding (getting expensive)" — is specifically the cost-led case;
  demand- and supply-led exits are a different story and must not be pooled into one
  number.
- **Both of RQ-001's spell definitions are compared, not just one**: composite A
  (original) and composite B-tenant (amended, demand-gated + 3-year cost-change
  term). B-owner is explicitly excluded — the owner ruling names "definitions A and
  B-tenant," and RQ-001's own ANSWER.md already found B-owner's near-zero exit count
  is a construction artifact (a mechanically ~50/50 demand gate on slow-moving,
  interpolated inputs), not a real signal, so it would contribute noise, not evidence,
  to a DiD on WHAT exits look like.
- **Two horizons**: 3 and 5 years after the area's exit year, matching the outcome
  definition above. No single-horizon shortcut.
- **Tenure (owner-occupied vs. tenant) is a proxy, not a measurement, and must be
  labelled that way everywhere it appears.** Inferred approximately from PLUTO/DOF
  lot-ownership signals (see `DATA-AUDIT.md` — this turns out to be a real gap: PLUTO
  is not currently ingested with an owner-name field, only a coarse public/private
  `ownertype`, which is not a tenure signal at all).
- **Sample gate: wait for the address tier.** RQ-001's ZIP tier has too few completed
  exits to support a DiD split by cause × definition × horizon (RQ-001 ANSWER.md: 1 /
  0 / 6 completed incident exits across the three composites, out of 150 ZIP-units).
  RQ-003's analysis does not run until the address-tier calibration (GTM-226) exists.
  Do not pool across RQ-001's sensitivity grid instead, and do not substitute a raw
  cost/demand/supply shock for a dated spell exit — both were considered and rejected
  as ways to manufacture a larger sample this session.
- **The Q8 gate governs whether RQ-003 can run at all, and where.** Closure data
  (DOHMH/SLA/POI-ledger) is complete enough to trust only where recorded
  closure/attrition reproduces a published NYC restaurant attrition benchmark within
  ±25%, overall and per borough. A borough that fails is out of scope for RQ-003
  until the detection gap is fixed there. See `DATA-AUDIT.md` for the computed
  verdict — it is a hard FAIL, citywide, this session.
- **Session scope**: this session ships interview → seed → scaffold → data audit
  only. The notebook and the answer wait for GTM-226 (address tier) — building them
  on the ZIP tier's 1/0/6 exit count, or on data that fails Q8, would produce a number
  that looks precise and isn't.
- **Loci standards apply**: address grain (no hexes) once the notebook runs,
  tickets generated from `tickets.py` (not hand-written), model routing per
  CLAUDE.md, and peer-session coordination on any shared file touched.

## Definitions

- **Incumbent**: a restaurant (POI category `restaurant`, or a licence-tracked
  restaurant in `analysis.licence_interval`/`licence_event`) whose `open_date` falls
  inside a favorable spell (RQ-001 `hysteresis_spells`, composite A or B-tenant) for
  its unit.
- **Regime exit**: the end of a favorable spell for a unit, dated to `exit_year` in
  RQ-001's spell table, with `exit_cause` in {cost, demand, supply} from
  `attribute_exit_cause`.
- **Survival**: the incumbent has no recorded `closed_on` within the horizon window
  (3 or 5 years) after its unit's `exit_year`. Given the Q8 finding below, "no
  recorded closure" and "survived" are NOT the same statement in this warehouse today
  — see caveats.
- **Replacement**: the next occupant of the same storefront (matched on
  `location_key`/BBL/premises_id) after an incumbent's closure — restaurant, chain,
  other retail use, or vacant — read from the POI ledger (successor POI at the same
  location) and the LL157 storefront `activity_canonical` sequence
  (`analysis.storefront_tenure.runs_json`, 2019+ only).
- **Tenure proxy**: `owner_occupied_likely` / `tenant_likely` / `unknown`, approximated
  from lot-ownership signals. Labelled "approximate" everywhere it is reported; not a
  ground-truth lease-vs-deed distinction (Loci has no lease data).
- **Cost-led / demand-led / supply-led exit**: whichever of RQ-001's three pillars
  (`demand_pillar_A`/`supply_pillar_A`/`cost_pillar_A`, or the B-tenant equivalents)
  moved most adversely between the spell's onset and exit year.
- **Censored observation**: an incumbent still open (no `closed_on`) at the end of the
  observation window, or a spell still favorable (no exit) at the panel's end — both
  carried as censored, never coded as "survived forever."

## Tiers / unit

- **Primary unit**: address / trade area (the "address tier," GTM-226) — not yet
  built. This is the buyer-facing grain per the standing Loci rule ("hex work is not
  done"; addresses, never ZIPs, for anything that ships).
- **Regime-exit unit**: RQ-001's ZIP-tier spells (`unit` = ZCTA-derived ZIP), 2000–2023
  headline panel — this is where `exit_year` and `exit_cause` come from; it stays at
  ZIP grain regardless of tier, since that is the grain RQ-001's regime label is
  defined at.
- **Restaurant/incumbent grain**: individual POI / licence record (`location_key` or
  `licence_number`), address-level from source, assigned to a ZIP (today) or an
  address-tier trade area (once GTM-226 lands) for the DiD comparison group.
- **History depth**: RQ-001's headline panel is 2000–2023; DOHMH-derived POI opening
  dates in `analysis.poi_first_seen` for category `restaurant` run 2003–2026 (82,085
  rows); SLA/DCWP licence intervals for restaurants run from the mid-2010s issuance
  window through 2026 (see `DATA-AUDIT.md`). LL157 storefront successor tracking
  (`analysis.storefront_tenure`) only reaches back to 2019 — it can date a
  replacement for any exit after 2019, not before.

## Out of scope

- Any result this session — no notebook, no answer, no DiD estimate. That is
  explicitly deferred to a future session per the seed's exit condition
  `session_success`.
- B-owner spells (excluded by the owner ruling above).
- ZIP-tier-only DiD as a substitute for the address tier, even as a "v0" — the owner
  ruling says wait, not "run a weaker version now."
- Fixing the Q8 closure-detection gap itself. This audit identifies and quantifies
  the gap (see `DATA-AUDIT.md`); closing it is a separate, ticketed pipeline task.
- A true owner-occupied/tenant classification. The tenure proxy stays a proxy; a real
  lease-vs-deed signal does not exist in any source Loci has registered.
- Commercial rent at the storefront level for the DiD's cost channel — no source
  provides it (see RQ-001/RQ-002 audits); RQ-003 inherits RQ-001's ZIP-level
  ZORI/ZHVI-and-assessed-value proxies, not a per-address rent figure.
