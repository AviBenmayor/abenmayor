# RQ-002 — Greenpoint towers and the retail landscape

Scaffolded 2026-09-22 by `loci research new`. Filled from the owner interview (buttons,
2026-09-22, 3 rounds) and SEED.yaml.

## Question as asked

Owner, verbatim, 2026-09-22:

> in greenpoint, when the massive housing developments went up, how did it change the
> retail landscape? when did businesses move in? who came before the demand came? who
> came after? did the number of businesses in the area increase? did rent increase and
> by how much? when did the towers go up? what was the area like before?

## Interview rulings

Every bullet below is a ruling from the interview and maps to a constraint in
`SEED.yaml`.

- **Geography.** Unit is ZIP 11222 (Greenpoint), chosen because it lets CBP/ZBP
  establishment counts run back to 1994. Named businesses are still identified at
  address grain from DOHMH/SLA records, but counts and series are reported at the ZIP
  level.
- **Scope of "retail."** All storefront retail — food & drink, grocery, services,
  shops — broken down by Loci category, not restaurants alone.
- **Rent, two kinds, reported separately.**
  - Residential: Zillow ZORI/ZHVI and ACS median gross rent.
  - Commercial: no paid historical commercial-rent series (CoStar/REBNY) is bought
    this session — that is scoped as a ticket, nothing purchased without an explicit
    owner budget ruling. Commercial rent is instead estimated from free proxies only —
    listing snapshots, DOF market/assessed value of ground-floor-retail lots,
    press-reported asking rents — and every commercial-rent number states its
    confidence rather than being presented as precise.
- **Control group.** Yes, a control ZIP is used. It is chosen by the analysis itself as
  the nearest match on 1994–2010 pre-trend (establishments, rent, income) among North
  Brooklyn / western Queens ZIPs. 11211 (Williamsburg) is excluded because it also got
  waterfront towers and would contaminate the comparison. The chosen control, the full
  candidate ranking, and the pre-trend distance that decided it are all recorded, not
  just the winner.
- **Anchor — "when the demand came."** Two anchors are reported side by side rather
  than picking one:
  (a) the 2005 Greenpoint–Williamsburg rezoning, and
  (b) tower-by-tower first occupancy (Certificate of Occupancy) and the resulting
  new-units-per-year series.
  "Pioneers" are businesses that opened before an anchor; "followers" opened after it —
  computed once per anchor cut, so a business can be a pioneer under one anchor and a
  follower under the other.
- **Who came before / after.** Reported two ways: (1) category counts by year, and (2)
  a named list of notable pioneer and follower businesses with first-seen dates
  (DOHMH first inspection date, or SLA first license date), web-verified rather than
  taken from the raw record alone.
- **Towers — what counts and how they're dated.** Sourced from free DOB job
  filings/permits, Certificates of Occupancy, and PLUTO: residential buildings,
  roughly ≥10 stories, in ZIP 11222, permitted or completed since 2005. Each tower is
  web-verified rather than assumed from a database row, and the still-under-construction
  pipeline is included and flagged as pipeline (e.g. Greenpoint Landing phases, 77
  Commercial / Eagle + West, 145 Kent / Bell Slip area, Huron/India St towers — to be
  verified, not assumed, against current filings).
- **"What was the area like before."** The pre-2005 baseline comes from the same panel
  used everywhere else in this RQ: CBP/ZBP business mix, ACS/decennial population and
  income, residential rent, and PLUTO land use of the waterfront lots (industrial or
  vacant), plus a sourced narrative — not a separate, differently-sourced "history"
  section.
- **Publishing.** Executed `.ipynb` plus `ANSWER.md` in the repo only. No HTML artifact,
  no Notion mirror, for this question.
- **Data completeness.** Free sources are pulled in full — no rolling windows, caps, or
  samples (standing owner rule, 2026-09-16). Paid sources stay out unless the owner
  rules an explicit budget.
- **Causal claim, labeled honestly.** A difference-in-differences estimate against the
  chosen control is reported, with a pre-trend (parallel-trends) check. Every claim is
  labeled descriptive or causal according to what the data actually supports — DiD
  output is never presented as descriptive, and a merely descriptive comparison is
  never dressed up as causal.
- **Grain discipline.** No hex tables. Everything in this RQ is reported at address or
  ZIP grain only (standing Loci rule — hex work is not "done" work).
- **Session model and coordination** (operational, not analytical, but binding on how
  this RQ gets built):
  - The executive dispatches; Sonnet runs the analyses; Opus and the specialist agents
    (contrarian, statistician, urban-planner, etc.) only render judgment/verdicts, they
    do not execute analysis or write routine code; Haiku does mechanical edits
    (checkpoint/ticket text, doc regeneration).
  - The research-question framework itself (`src/loci/research.py`, the template
    folder, the `research-question` skill) is owned by session `abenmayor-9f` for this
    round — this RQ's content sessions do not edit those files.
  - New decision ids are D141 and up; new SQL migrations are numbered 063 and up.
  - `tickets.py` and `CHECKPOINT.md` are written for this RQ only after peer sessions
    `6d` (D138) and `9f` (D140) have committed their own pending edits to those files.
  - Commits touch only this session's own hunks, staged by explicit patch.
  - The RQ's Linear parent issue sits under the "Research questions" milestone in the
    Loci project, and every ticket under it is generated from `tickets.py`, never
    hand-written.

## Definitions

- **Storefront retail** — any ground-floor commercial establishment: food & drink,
  grocery, personal/business services, and shops — classified into Loci's existing
  category taxonomy. Not restricted to restaurants.
- **Tower** — a residential building in ZIP 11222, roughly ≥10 stories, permitted or
  completed on or after 2005 (i.e. post-rezoning), identified from DOB filings/permits,
  Certificates of Occupancy, and PLUTO, and confirmed by a web source. Still-permitted,
  not-yet-occupied buildings are included and flagged `pipeline`.
- **Anchor** — a dated reference point used to split business openings into "before"
  and "after." Two anchors are used, not one: the 2005 rezoning (a policy date) and
  first occupancy / TCO date, tower by tower (a delivery date). Each anchor produces
  its own pioneer/follower split; the two splits are reported side by side, not merged.
- **Pioneer / follower** — relative to a given anchor: a business is a pioneer if its
  first-seen date (DOHMH first inspection or SLA first license, web-verified) precedes
  the anchor date, and a follower if it comes after. Defined per anchor cut — a
  business can be a pioneer under the rezoning anchor and a follower under the TCO
  anchor, or vice versa.
- **Residential rent** — Zillow ZORI (asking rent index) and ZHVI (home values), plus
  ACS 5-year median gross rent, all at ZIP grain.
- **Commercial rent** — not a single clean series. Estimated from free proxies
  (commercial listing snapshots, DOF market/assessed value of ground-floor-retail
  lots, press-reported asking rents), each carrying a stated confidence level rather
  than being treated as a precise time series. Where the free proxies can't support an
  estimate for a period, that gap is marked partial/blocked with a ticket id, not
  filled in.
- **Control ZIP** — the ZIP among North Brooklyn / western Queens ZIPs (excluding
  11211) whose 1994–2010 pre-trend in establishments, rent, and income is closest to
  11222's, chosen algorithmically and reported with the full ranked candidate list and
  distance metric.
- **Descriptive vs. causal** — a "descriptive" claim is a level or change reported
  without attributing it to the towers/rezoning; a "causal" claim is the
  difference-in-differences estimate against the control, reported only if the
  pre-trend (parallel-trends) check supports it, and flagged as an assumption-dependent
  estimate rather than a proof either way.

## Tiers / unit

- **Primary unit of analysis:** ZIP 11222, for both the treatment series and the
  control-ZIP comparison. This is what makes the panel reach back to 1994 (CBP/ZBP
  don't publish reliable pre-2010 counts at finer grain).
- **Secondary/named grain:** individual business (address-level, from DOHMH/SLA) and
  individual tower (BBL/address-level, from DOB/PLUTO), used to build the named
  pioneer/follower lists and the tower timeline — but always rolled up to the ZIP
  panel for the counts, rates, and DiD estimate. No hex grain anywhere in this RQ.
- **Panel depth:** 1994 → latest available, annual, for both 11222 and the chosen
  control ZIP. Two anchor years are marked on that same panel (2005 rezoning; and the
  tower-by-tower TCO series charted as new-units-per-year) rather than requiring two
  separate panels.

## Out of scope

- Buying or otherwise acquiring a paid historical commercial-rent series (CoStar,
  REBNY licensed data). That capability is scoped as a ticket only; nothing is
  purchased without an explicit owner budget ruling.
- Any control ZIP outside North Brooklyn / western Queens, and 11211 (Williamsburg)
  specifically, which is excluded by ruling because it received its own waterfront
  towers and would confound the comparison.
- Hex-grid reporting of any kind — this RQ reports at address or ZIP grain only.
- Publishing an HTML artifact or a Notion mirror of the results — this RQ ships as a
  repo notebook and `ANSWER.md` only.
- Editing the research-question framework itself (`src/loci/research.py`, the
  scaffolding template, the `research-question` skill) — owned by another session this
  round.
- Treating the difference-in-differences estimate as proof of causation independent of
  its parallel-trends check — the causal claim is only as strong as that check, and is
  labeled accordingly.
- Re-litigating whether Greenpoint saw large-scale rezoning-driven towers at all — the
  interview already establishes that as the premise; this RQ measures the retail
  consequence, not whether the premise holds.
