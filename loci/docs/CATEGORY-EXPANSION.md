# Category expansion — the fail-closed checklist for a 16th slug

*GTM-112 (Urgent, milestone E10). Open question D13. Written 2026-09-14.*

**Fail-closed means:** a new slug does not appear in the screen, on a recommendation
card, or on the map until every gate below has a recorded pass. A gate that cannot be
evaluated is a FAIL, not a skip. Every number below is cited to the file that holds it;
where no threshold exists, the gate is marked **OPEN** rather than given one here.

---

## 1. Why this document exists

Three failure modes, all of which have already happened in this project:

1. **A number wearing a label it did not earn.** `demand.yaml` once hand-coded a
   necessity/discretionary class per category; the GTM-109 contrarian review found no cut
   point on the real CEX scale reproduced it — it was "a free variable wearing a citation"
   (`src/loci/demand.yaml` header). `pharmacy` then passed the age-fit contrast F2a on
   "fewer 18–34s" rather than on 65+, and was refused (`src/loci/model/age_fit.py:202`,
   D69). A new category multiplies the surfaces on which this can happen.
2. **A data gap wearing a costume.** D64 read Borough Park as a childcare desert; D65
   showed it was aggregator under-coverage — the DOHMH roster moved the median address
   from 298 m to 104 m and 3 → 31 sites within 640 m (CHECKPOINT D65). A slug with no
   registry anchor produces gaps that are unfalsifiable, and **this failure is currently
   fail-OPEN, not fail-closed**: an empty `analysis.category_anchor` row degrades the
   PRINCIPLED supply set to ALL rather than refusing (`src/loci/score/supply.py:30-32`). That fallback is deliberate and documented at its own site — a missing measurement must never silently delete supply for the 15 shipped slugs — so the refusal belongs here, in gate G3 before a slug is registered, not in `supply.py`.
3. **Silent re-statement of published numbers.** `TIER_WEIGHTS` is a partition over 15
   slugs and `gap_score` is a max over categories, so a 16th slug moves values that were
   already shown to the owner for reasons unrelated to any new evidence at any address.

The codebase already fails closed in four places (`reach.py:35 _check_reach_complete`,
`zbp.py:42`, `demand.py:78`, `tests/test_demand_caveat.py`). This checklist is the rest.

---

## 2. Prerequisites — do not open a ticket without these three

| # | Prerequisite | Evidence required |
|---|---|---|
| P1 | **An anchor source with measurable coverage** — a government act of registration, bulk-downloadable, with a practice/premises STREET address | A live probe recorded in `src/loci/registry.yaml`. D71's counter-examples: NYSED Office of the Professions has no bulk form at all; NPPES taxonomy 3336C0003X has no coordinates and a 1,200-record cap |
| P2 | **A definition mapped into every POI source's own taxonomy** — OSM key=value, Overture `categories.primary`, Foursquare group/leaf | Rows in `src/loci/categories.yaml` `sources:` and entries in `foursquare_places.GROUP_CATEGORY`/`LEAF_CATEGORY`. Pinned by `tests/test_category_registry.py` |
| P3 | **A real BLS CEX line** for the spend row | A row in `src/loci/spend.yaml` with `income_elasticity`; the necessity/discretionary class is DERIVED at the 0.35 cut (`src/loci/demand.yaml` header), never hand-set |

If P1 fails and no substitute exists, the category may still ship **as a non-filtering
signal** (§4) — never as a screen category.

---

## 3. The ordered gates

Run in order. Each row gives the command, the threshold, what a fail looks like, and the
action on fail.

### G0 · Registry completeness (no warehouse needed)
- **Command:** `uv run pytest tests/test_category_registry.py tests/test_categories_anchor.py -q`
- **Threshold:** every slug in `CATEGORIES` has a row in all seven yamls
  (`categories.yaml`, `reach.yaml`, `reach_tiers.yaml`, `conveniences.yaml`,
  `demand.yaml`, `spend.yaml`, `zbp_naics.yaml`), every `naics_2022` code exists in
  `src/loci/naics/naics_2022.csv`, `benchmarks.yaml` and `GOOGLE_TYPES` gain the slug,
  and CONTEXT.md §2.1's table matches `categories.py`.
- **Fail:** a missing row anywhere. **Action:** refuse — this is cheap and total.

### G1 · Reach rule
- **Command:** `loci reach-table` (comparison only); the value ships in `reach_tiers.yaml`.
- **Threshold:** `reach_m` ∈ {400, 800, 1200} (`reach_tiers.yaml:candidate_tiers_m`; 600 m
  is reserved for a source that names it — none has), plus `basis: cited | analog | none`
  with citations in `docs/reach_sources.md`. `basis: none` falls back to the owner norm in
  `conveniences.yaml`. `reach.load_reach` raises on a missing category.
- **Fail:** no row, or a value off the tier set. **Action:** refuse. A `basis: none` value
  is a PASS with an owner norm recorded — it is not a silent default.

### G2 · Monotonicity of the missing rule
- **Command:** `uv run pytest tests/test_gaps_monotonicity.py -q`
- **Threshold:** property, not a number — adding a business of category *c* anywhere may
  never turn a not-missing address into a missing one, and tightening a distance may only
  ADD to the missing set. Holds by construction for `rule="reach"`; the old `rule="window"`
  violates it and the test pins that defect.
- **Fail:** a new slug wired through a prevalence-style rule. **Action:** refuse.

### G3 · Anchor coverage — the gate that decides whether gaps are real
- **Command:** `loci anchor-coverage --boroughs MN,BK`
- **Threshold:** `ANCHOR_COVERAGE_MIN = 0.70` against ZBP establishments over the same
  comparable-ZIP universe as `loci zbp-compare` (`src/loci/score/supply.py:100`).
  Precedents: childcare 0.000 → 0.85 (D65), pharmacy 0.000 → 0.903 (D71), laundry 1.06
  (D59); nails 3.04 qualifies **for the wrong reason** (D14, still open).
- **Fail:** below 0.70, or no ZBP denominator at all (an unmeasurable anchor is not a
  qualifying one, `supply.py:239`). **Action:** load a better anchor. Moving the number is
  never the answer. The only sanctioned escape is `anchor_is_floor: true` in
  `categories.yaml` — declared per category, granted once (`childcare`, D65), and only
  where the missed slice biases toward MORE supply, not less.
- **Note the asymmetry:** a fail here does not stop the screen. It silently widens the
  supply set to ALL. Treat a missing `category_anchor` row as a blocking fail by hand.

### G4 · Dedup rank branch
- **Threshold:** `score/dedup.py::source_rank` must have a branch for the new anchor.
  Missing it is the D65 trap (the registry fell behind Overture and an aggregator's
  geometry stayed canonical) and it recurred in D71 — **two for two on the last two adds.**
- **Fail:** anchor records present but not canonical. **Action:** refuse until fixed; then
  re-record `supply_hash`.

### G5 · Census validation
- **Command:** `loci zbp-compare`
- **Threshold:** a `zbp_naics.yaml` row with a NAICS 2017 code that resolves in the live
  CBP vocabulary, plus a `confidence`. `zbp.py:42` raises on a missing category — silence
  is indistinguishable from zero establishments.
- **Fail:** the code is government-classified (NAICS 491110, shipping/mail) or absent.
  **Action:** refuse — the category can never be checked against Census (E10 drop list).

### G6 · Demand row
- **Command:** `uv run pytest tests/test_demand_caveat.py -q`, then `loci address-demand`
- **Threshold:** a CEX `income_elasticity` in `spend.yaml`; class derived at the **0.35**
  cut; the demand caveat fires only on the MOE-confident test
  `income_ratio + income_ratio_moe < 0.80` (CHECKPOINT D49/D57).
- **Fail:** no CEX line. **Action:** refuse — there is deliberately no way to add a
  category without one.

### G7 · Density-elasticity regime (the clustering-vs-saturation coefficient)
- **Command:** `loci density-elasticity fit`
- **Thresholds** (`src/loci/model/density_elasticity.py:129-142`): MN+BK ZIPs, 2013→2023,
  `MIN_POP_BASE` 5,000, `MIN_ZIPS` 25, `MIN_NONZERO_BASE` 10, Conley `T_GATE` 1.96,
  `LOZO_SIGN_GATE` 0.90, `PLACEBO_QUANTILE` 0.90.
- **Fail:** too few ZIPs → the category is simply not fitted; t below 1.96 or a placebo
  beat → `no_signal`. **Action:** ship with `not_fitted`/`no_signal` — the card prints
  "supply count is NOT evidence either way" (`recommend_grades.yaml:88-91`). NULL is never
  1.0. This is a pass-with-label, not a refusal.

### G8 · Supply-ratio baseline
- **Command:** `loci supply-ratio --fit-baseline` then `loci supply-ratio`
- **Threshold:** an address-weighted median `supply_per_1k` at 400 m network distance over
  all MN+BK addresses with `homes_400m > 0` (n = 281,842 today), written to
  `model/supply_baseline.yaml` with the `supply_hash` it was fitted on;
  `tests/test_supply_ratio.py` fails when ratio and baseline drift apart.
- **Fail:** no baseline row, or a hash mismatch. **Action:** re-fit. A hash mismatch caps
  the card's supply section at grade C (`recommend_grades.yaml:86`), which already makes
  "act" unreachable.

### G9 · Coverage validation (Google)
- **Command:** `loci validate --run`; drift pinned by `uv run pytest tests/test_google_types_drift.py -q`
- **Threshold:** a `GOOGLE_TYPES` entry mirrored byte-for-byte in `webmap/server.js`'s `GT`
  map. **OPEN — there is no numeric recall/undercount threshold anywhere in the code.**
  The only encoded consequence is the card's coverage ladder: A validated / B anchored
  (`category_anchor.qualifies`) / C aggregators only (`recommend_grades.yaml:125-128`).
- **Fail:** no Google primary type exists for the category (Table A has no `shoe_repair`;
  `tailor_repair` is kept only because nothing better exists). **Action:** ship capped at
  coverage grade B or C and say so on the card. Do **not** invent a recall threshold.

### G10 · Age-fit (optional, and only as a signal)
- **Command:** `loci age-fit fit --category <slug>` then `loci age-fit apply`
- **Thresholds** (`src/loci/model/age_fit.py:179-201, 284-300`): **F2a** Brooklyn-only
  Conley CI on the low→high age contrast excludes 1.0 with the demanded sign (`CI_Z` 1.96);
  **F2b** Brooklyn-only CI on the PRIMARY demand regressor's own coefficient excludes zero
  with that sign; **F3** (p90−p10 of the multiplier) ÷ median MOE ≥ `DISPERSION_GATE_MIN`
  1.0; multipliers reported against `MULTIPLIER_BOUNDS` (0.5, 2.0).
- **Fail:** `fit` exits non-zero and writes nothing. Precedent: pharmacy refused at
  b(age_65_plus_share) +0.396, Conley t +1.39 (D69/D71). **Action:** refuse the curve; the
  category keeps `age_fit` NULL. Most categories will never have a curve and that is fine.

### G11 · Economics
- **Threshold:** `n_comps_min: 5` for grade B; `modelled_grade: C` for a category with a
  shipped, gated revenue calibration; otherwise D (`recommend_grades.yaml:108-120`). Only
  `restaurant` passes the revenue backtest today (D81).
- **Fail:** none possible — a new category grades D on economics, and D anywhere in
  `load_bearing` forces the verdict "do not act on this data"
  (`recommend_grades.yaml:26-33`). **This is the expected steady state, not a blocker.**

### G12 · Scope and rendering
- **Threshold:** MN+BK only — `loci address-gaps` refuses other boroughs (D78); the webmap
  reads `ALLCATS = list(CATEGORIES)` (`viz/webmap_export.py:211`), so legend, `catLabels`
  and the per-category POI layer all follow from the registry.
- **Fail:** a slug rendered outside MN+BK, or a hand-maintained legend entry.
  **Action:** refuse.

### Three consequences to price before the add lands
- **`TIER_WEIGHTS` 0.40/0.20/0.25/0.15** is a partition; `score/dnci.py:32` divides each
  tier weight by that tier's member count, so a 16th slug re-weights **every DNCI value
  ever computed**. Decide explicitly: re-state DNCI, or scope the expansion to the address
  screen only.
- **`MIN_PRESENT = 12`** (`model/address_gaps.py:114`) — **already retired as a gate** by
  owner ruling D75; the constant survives only so `present_count` keeps its old meaning.
  The 12-of-15 re-derivation the ticket asks for is therefore moot; say so rather than
  re-deriving a dead threshold.
- **`gap_score` is a max over categories** (D41) and is monotone in the number of
  categories: adding a slug can only raise scores and can move `lead`. Report the
  before/after **as a per-category distribution, never a top-N list** (D52 rule).

---

## 4. The signal-vs-filter rule

A category that fails G3 (or any gate that makes its gaps unfalsifiable) does not have to
be thrown away. It ships as a **non-filtering signal**: something that can reorder or
annotate, never gate. The four precedents:

| Thing | How it ships | Citation |
|---|---|---|
| `age_fit` | a strictly positive multiplier — `gap_score * age_fit` is monotone in `gap_score`, so it can reorder but can never gate | `age_fit.py:173-177` |
| liquor / alcohol | a map OVERLAY with its own legend, not a 16th category | D52(c), reaffirmed by the owner 2026-09-09 |
| neighborhood character | map colour and card context only; enters no grade | D82 |
| DOT sidewalk counts | a shortlist-verification instrument, not a screen-wide layer | D85 |

The test of a signal: removing it must leave `gap_score`, `lead_category`, `n_missing` and
the missing set byte-identical. That is the same separation `analysis.address_demand`
proves by construction — a sibling table with no write path to `address_gaps` (D57).

---

## 5. Artifacts a pass must leave behind

1. Rows in all seven yamls, plus `benchmarks.yaml` and `GOOGLE_TYPES` (+ `server.js` `GT`).
2. A `registry.yaml` entry for the anchor with a recorded live probe.
3. A row in `analysis.category_anchor` with `anchor_coverage`, `qualifies`, `threshold`.
4. A `supply_hash` recorded in provenance, and a re-fit `model/supply_baseline.yaml`
   carrying that same hash.
5. A `model/density_elasticity.yaml` row (even `no_signal` / `not_fitted`).
6. A CONTEXT.md §2.1 table row, and a dated CHECKPOINT decision-log entry stating the
   TIER_WEIGHTS/DNCI decision and the before/after gap distribution.
7. Green: `uv run pytest tests/test_category_registry.py tests/test_categories_anchor.py
   tests/test_demand_caveat.py tests/test_google_types_drift.py
   tests/test_gaps_monotonicity.py tests/test_supply_ratio.py -q`.

**Two standing exceptions, both deliberate and both pinned as an exact set by
`tests/test_category_registry.py`:** `bank` has no `benchmarks.yaml` row ("not listable as
a small-business comp", `benchmarks.yaml:111`) and `clinic` has no `GOOGLE_TYPES` entry
(`doctor` is every solo physician's office, a different population from clinic's
621111/621493 anchor — `google_places.py:81`, D30; `clinic` can therefore never reach
coverage grade A). A 16th slug cannot join either set silently — it widens the set and
fails the test, forcing the same explicit ruling these two got.

---

## 6. Worked dry-run — `dentist` (GTM-113, the first E10 add)

| Gate | Verdict today | Why |
|---|---|---|
| P1 anchor | **CONDITIONAL** | NPPES is verified downloadable with LOCATION street addresses, taxonomy family 122300000X. But it is a PROVIDER registry: several dentists share one address, so counts must be collapsed by address first — the D52(b) booth-renter failure in a new costume |
| P2 taxonomy | **FAIL** | no `dentist` row in `categories.yaml`; no OSM/Overture/Foursquare vocab mapped |
| P3 CEX line | **PASS (expected)** | CEX Table 1101 "Dental services" is a clean 1:1 line; must ship `reliable: false` — revenue is largely third-party-payer, so a household-budget model is wrong in SHAPE, not merely noisy |
| G0 registry | **FAIL** | `tests/test_category_registry.py` fails on the missing `benchmarks.yaml` row and on `GOOGLE_TYPES` — which is exactly the fail-closed behaviour intended |
| G1 reach | **OPEN** | no walk standard exists; the dental-access literature is HPSA population-to-provider RATIOS, the shape D41 already rejected for childcare. `basis: none`, owner norm, proposed 1,200 m |
| G3 anchor coverage | **FAIL (unmeasured)** | NPPES is not ingested, so `analysis.category_anchor` has no dentist row — and the degradation is silent (§1.2). Blocking until `loci anchor-coverage` prints a number ≥ 0.70 after the address collapse |
| G4 dedup rank | **FAIL** | no `source_rank` branch for NPPES. Two of the last two adds hit this |
| G5 ZBP | **PASS** | 621210, unchanged 2017→2022, confidence high; 190 establishments across ten MN+BK ZIPs (CBP 2023) — the highest prevalence of any E10 candidate |
| G9 coverage | **FAIL** | no `GOOGLE_TYPES["dentist"]`; coverage caps at B (if anchored) or C |
| G10 age-fit | **N/A** | not in `CURVES`; `age_fit` stays NULL, which is correct — NULL is not 1.0 |
| G11 economics | **D** (expected) | no comps, no revenue calibration → verdict "do not act on this data" |
| TIER_WEIGHTS | **DECISION REQUIRED** | dentist lands in T4 (civic & wellness), splitting 0.15 six ways instead of five and re-stating every DNCI value |

**Conclusion:** `dentist` fails today at G0, G3, G4 and G9, and forces the TIER_WEIGHTS
decision before any of it can land. The cheapest next step is the NPPES ingest plus the
address collapse, because G3 is the gate that decides whether every dentist "gap" the
screen would produce is a hole or a missing file.

---

## 7. Not yet built

`loci check-categories` (the CLI subcommand GTM-112 asks for) **does not exist** in
`src/loci/cli.py`. `tests/test_category_registry.py` implements its warehouse-free half
(the seven yamls, the NAICS existence check, the adapter vocabs, the CONTEXT §2.1 drift
check). Still missing: asserting every `naics_2017` code resolves in the live CBP
vocabulary and every slug has a `category_anchor` row — both need a warehouse and an API
call, so they belong in the subcommand, not in a test.
