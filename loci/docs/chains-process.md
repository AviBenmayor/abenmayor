# The chain watchlist — what it is and how to run it

*Human-readable. The generated list itself is [CHAINS.md](CHAINS.md), which is
written by `loci chains render` and must never be hand-edited.*

> **Why this file is not called `chains.md`.** macOS is case-insensitive:
> `docs/chains.md` and `docs/CHAINS.md` are the same file, and the generated
> list would silently overwrite this one on every `make chains-refresh`. It
> did, once. The two names had to differ by more than case.

---

## What the list is for

Retail and consumer brands opening aggressively in New York. Two uses:

1. **Companies to sell to.** A brand that added six stores in a year has a
   person whose job is picking the next site. That person is the buyer for a
   site-selection product, which is why `expansion_role_title` is a field.
2. **A signal for recommendations, later.** "Apollo Bagels signed a lease two
   blocks from here" is evidence about a location that no POI count carries.
   **Nothing consumes this yet.** Every brand carries a `loci_category` — one
   of the fifteen in `src/loci/categories.py` — purely so the join exists when
   something does.

It is *not* a competitive-supply measure. The address screen already counts
storefronts; this counts *companies*.

---

## The three layers, and which one wins

| Layer | Where | Costs | Authority |
|---|---|---|---|
| **Detection** | `chains.brand_snapshot` (DuckDB) | free | a measurement, and a floor |
| **Press** | `chains.press_hits` (DuckDB) | Tavily credits | a reading queue, not evidence |
| **Watchlist** | `src/loci/chains/watchlist.yaml` | a person's time | **outranks both** |

The watchlist is hand-maintained and wins every disagreement. `docs/CHAINS.md`
prints the curated number *and* the detected number side by side rather than
reconciling them, because the gap between them is itself informative — see the
failure modes below.

---

## The monthly process

```bash
make chains-refresh          # = loci chains refresh:
                             #   poi-snapshot -> detect -> research -> render
```

Run on the 1st of each month. Each step is also a command of its own:

```bash
uv run loci poi-snapshot    [--month 2026-09] [--dry-run] [--force]
uv run loci chains detect   [--month 2026-09] [--dry-run] [--limit 25]
uv run loci chains research [--max-queries 60] [--days 45] [--detected 20] [--dry-run]
uv run loci chains import   path/to/brands.json [--overwrite] [--dry-run]
uv run loci chains render   [--month 2026-09] [--dry-run]
```

`poi-snapshot` must run **before** `detect`, and `loci chains refresh` does it
as step 1/4 for exactly that reason: `detect` reads first-seen from the ledger
and **raises** if the ledger is missing, rather than reporting every brand as
undated. A month's observation also cannot be recovered once the month has
passed — if the job does not run in October, October is simply not in the
record. Both commands are idempotent per month.

`detect` is idempotent per month — re-running `--month 2026-09` deletes and
rewrites that month rather than duplicating it. `research` will not spend more
than `--max-queries` (default 60); `--dry-run` prints the exact query list and
sends nothing, and needs no API key.

### Why a monthly snapshot exists at all

`locations_new_12m` is derived from whatever date each source happens to carry,
and **most carry none**:

| Source | First-seen date | Usable |
|---|---|---|
| `foursquare_os_places` | `opened_on` (FSQ `date_created`) | yes |
| `nys_sla_liquor_licenses` | `opened_on` (licence effective) | yes |
| `nys_dos_appearance_enhancement` | `attrs.license_issue_date` | yes |
| `nys_medicaid_pharmacies` | `attrs.enrollment_begin_date` | yes |
| `overture_places` | — | **no** |
| `nyc_dohmh_restaurants` | only `last_inspection_date`, a *last*-seen | **no** |
| `usda_snap_retailers`, `nyc_dcwp_inspections`, `nyc_dohmh_childcare` | — | **no** |

On the 2026-09 snapshot that leaves **60% of brand-locations dated** — so
`locations_new_12m` is a **count over the dated subset** and a floor.
`locations_dated` is published beside it so the denominator is never hidden;
when `Dated` is far below `Locations`, the ranking is weak evidence.

Since 2026-09-13 these source dates are read **through the first-seen ledger**
(below), never from the sources directly, and from 2026-10 the undated
remainder starts shrinking on its own: a storefront the ledger watches appear
is dated `observed`, whatever the sources say.

The fix that depends on no source's dates is to **take the count ourselves,
every month**, and difference it. `chains.brand_latest.locations_delta_since`
is that measure. It is NULL until two snapshots exist — NULL means "not yet
measurable", never zero. The list gets materially more trustworthy after a
year of snapshots, and that is the whole reason for the cron job.

---

## Sourcing and admission

*Owner ruling, 2026-09-15, triggered by two rows (All'Antico Vinaio, Super
Burrito) landing on the watchlist with no process behind them.* Full case:
`docs/CHECKPOINT.md` D1XX.

### Two tiers, and which one wins

On top of the three layers above, the list now has a machine half and a
human half. **CANDIDATE** is mechanical, lives in `chains.brand_snapshot` —
nobody hand-picked these rows, they cleared a predicate. **ADMITTED** is the
YAML, hand-vetted, and **outranks both CANDIDATE and detection**, same as
the watchlist already outranks Press. A rejected CANDIDATE stays rejected
until it earns a re-review (below).

### The candidate predicate

A brand enters CANDIDATE when **all** hold:

- `n_sources >= 2` **after aliasing** — two spellings of one chain are one
  two-source brand, not two real ones.
- `locations_total >= 5` **OR** `detect.flag_for` fires (≥3 new in 12m, or
  ≥2 new of ≤8). "5+" alone admits incumbents wholesale and misses the
  small-fast movers `flag_for` catches; detection can't see a 3-store brand
  with signed leases at all — the OR does the real floor-setting.
- not in an excluded class (below).
- a movement signal in the last 12 months — an opening, a press hit, or a
  filing. A brand that hasn't moved is a logo, not a lead.
- not already `admitted` or `rejected` — a rejection has to stick, or the
  same brands come back every month.

### Exclusions

Hard excludes, never surfaced as a candidate, each with a reason:

| Class | Reason |
|---|---|
| Banks | Not a retail tenant |
| Health-system practice lines | Site-specific names collapsing to one key; a clinic network |
| Agent networks (MoneyGram, Western Union) | Bodega counters — the fastest-"growing" name in the first raw run |
| Wireless carriers | Kiosk format, not a site-selection lead |
| Parking, ATMs, government/postal | Not commercial tenants |
| Fuel-branded convenience | The storefront is a gas station, not the brand |

### `sales_role`, and who reads it

| `sales_role` | Meaning | Lead list | Recommend card (D19) |
|---|---|---|---|
| `prospect` | growing, a lead | included, default sort | context |
| `incumbent` | 100+ NYC locations (Dunkin', Starbucks, Chase) | off default sort | feeds "brand X opening nearby" |
| `contraction` | net-negative, a supply event | included, reverse sort | context |
| `excluded` | hard-excluded class | never surfaced | never surfaced |

Daily-needs `loci_category` is **not required** — a null-category admitted
row is a real lead that simply joins to no card.

### Signal schema

| Signal | Source | Cadence | Derived / hand |
|---|---|---|---|
| `locations_total`, `locations_new_12m/3m`, `n_boroughs`, `n_sources`, `flagged` | `brand_snapshot` | monthly | derived |
| `locations_delta_since` — cross-snapshot delta | `brand_latest` | monthly | derived; NULL until 2 snapshots |
| `pipeline_filings_12m`, `pipeline_coverage` (`real`/`structural_zero`) *(not built)* | `storefront_pipeline` | monthly | derived |
| `press_hits_12m` *(not built)* | `press_hits` | monthly | derived |
| `trajectory_state` — `unmeasured` until 4 snapshots exist, else accelerating/steady/decelerating/declining/static from `d3`/`d12` *(not built)* | `brand_snapshot` deltas | monthly | derived |
| `tier`, `sales_role`, `*_reason`, `decided_on`, `capital_events`, `signed_leases`, `store_count_source`, `expansion_contact_url` *(not built)* | `watchlist.yaml` | on review | hand — never in `brand_snapshot`, a DELETE+INSERT per `--month` that would destroy it |

### Sources

| Source | Feeds |
|---|---|
| `chains detect`, `poi_first_seen`, `storefront_pipeline`, `press_hits` (free, running) | candidate floor; filing and press signals |
| Trade press — What Now NY, Eater NY, Commercial Observer, The Real Deal, Restaurant Business, QSR, Nation's Restaurant News, Franchise Times (Tavily) | discovery, `capital_events`, `signed_leases` |
| Company store-locator pages (Tavily extract) | the **only** scheduled path to `verified` |
| SEC EDGAR full-text (free) | public-parent counts, closures, franchise deals |
| NYS SLA pending, DOB NOW filings (free) | `signed_leases` for food/drink |
| RetailStat, Coresight, Data Axle (paid, not built; RetailStat quote open) | store-level location, national trajectory, cross-category openings/closings |

### The monthly runbook

**Automatic** — `loci chains candidates` *(not built)*: the ranked diff
since last month with the reason each row fired, run inside
`make chains-refresh` after `detect`.

**Human, ~45–60 min.** Read the diff (~10 min); `admit <key> --reason "…"
--role prospect` / `reject --reason "…"` *(not built)* write `tier`,
`decided_on` and the reason into the YAML in one edit; refresh signals the
press pass flagged (~20 min). A rejected key **re-surfaces automatically**
if `locations_total` doubles or a capital event lands, so "rejected at 5"
never permanently hides a brand at 20.

**First-run backlog.** On the 2026-09-13 snapshot the unlisted pool at the
floor ran 2,341, narrowing to 244 sub-5 flagged adds and 697 after excluding
banks/clinics and requiring 12-month movement — too large for one sitting.
A 2026-09-15 rebuild (fixed normalizer, post-dedup ledger) shrank the base
~20%, so treat those three numbers as scale only and re-derive on the first
real `candidates` run. Owner plan: hand-triage the top 100 by
`locations_new_12m`; the rest waits for the 2026-10 diff.

### Quarterly re-verification

Every admitted row with `confidence: reported` and `last_verified` older
than 90 days gets a store-locator count — the only path to `verified`; an
import can never produce one. As of 2026-09-15, 0 of 123 rows are
`verified` or carry a `last_verified` date, so the first quarterly pass is
not maintenance — it's the first time anyone here will have counted a store.

### Trajectory: honestly unmeasured

One snapshot cannot separate "growing" from "acquired and frozen" — both
read as a flat count. `trajectory_state` returns `unmeasured`, never a
label, until four monthly snapshots exist to compute `d3`/`d12` deltas.
Shipping a `static` guess off one would manufacture the exact misreading
(a frozen-since-2021 gym reading like a growing one) the field exists to
prevent.

### Tier 3: `watch` — before a chain is a chain *(not built — D110, GTM-192)*

CANDIDATE starts at five locations or `flag_for`'s "2 new of ≤8", so it meets a brand only
after it has expanded. `watch` is the tier below: **one or two open MN+BK locations, at
least one intent signal in the last 12 months, not an excluded class.** It reads
`analysis.poi_first_seen` rather than `chains.brand_latest`, because `detect.MIN_LOCATIONS`
is 2 and a single-site operator has no brand row to read; the key is
`chains.normalize.brand_key`, never `poi_first_seen.name_key` (token-sorted, and not the
same key as `storefront_filing.business_name_key`). There is no category gate: Bathhouse's
POI rows split across `nails_beauty` and `restaurant`, so filtering on category would admit
or drop the owner's own example by chance. **A `watch` row is internal only** — never on the
lead list or a D19 card until it graduates, because the evidence behind it is one filing or
one headline. A row graduates when it clears the CANDIDATE predicate, keeping
`watched_since` so the tier's lead time is measured; it expires after 18 months without a
new signal, a window chosen against D80's fit-out → first-inspection p75 of 378 days.

Signals: a second-site government filing, a "Brand II"/dba name hint, and a scan of fit-out
**work descriptions** are derived monthly from the filings pipeline at no new spend;
expansion-language press needs a new Tavily `query_kind`, funded by raising `MAX_QUERIES`
60 → 68 rather than re-splitting, so the admitted-brand re-verification cycle — which has
never once completed — is not slowed to pay for a new tier; capital events stay hand-entered;
job postings are out.

Two honest limits. First, every feed in `staging.storefront_filing` except DOHMH begins
**2024-09-13** and `chains.press_hits` holds 45 days; both are live-status snapshots, so
this tier accrues forward and cannot be back-tested — Bathhouse's January 2024 second
opening was invisible for exactly that reason. Second, and sharper: the filings are
food-and-drink. Every row in the measured pool entered at `liquor_application`. **Mink
Padel** (West Harlem, opened 2025) has no row anywhere in the warehouse; **Padel Haus** has
three, but only through its café. A premium amenity that sells no drink is invisible to the
name-key route, and where its landlord files, the filing carries the landlord's name or
none. The fit-out-description scan exists because of this: the only filing in the warehouse
that names padel — "Padel State", 73 West St — was found by its work text and by nothing
else.

---

## The first-seen ledger

*Owner's ask, 2026-09-13: "make sure moving forward we have dates on which
month data was first seen for storefronts."*

`analysis.poi_presence` (schema and full rationale in
`src/loci/sql/018_poi_presence.sql`) holds **one row per deduplicated
storefront location** — all of them, not just the ones that belong to a chain —
recording the month Loci **first** and **last** observed it. It does not depend
on any source publishing an open date. `loci poi-snapshot` writes one month of
it; `analysis.poi_first_seen` is the view every consumer reads.

### The three kinds

| `first_seen_kind` | means | `first_seen_month` in the view |
|---|---|---|
| `source_date` | a source published an open / licence / enrolment date at or before the month we first saw it. `first_seen_on` is that DATE. | the source's month |
| `observed` | no source date; the ledger **watched it appear** in that month. | that month |
| `backfill_censored` | it already existed when the ledger started and nothing dates it. **Left-censored** — the true opening date is unknown and unbounded below. | **NULL** |

**The first honest month is 2026-10.** September 2026 is the backfill: every
location then in the warehouse got a row, so "new in 2026-09" is not a
measurement of anything. October is the first month with a prior snapshot for a
new location to be new *relative to*.

**A left-censored row must never be reported as "opened in 2026-09."** The view
is the guard: it returns `NULL` for a censored `first_seen_month`, so a naive
`GROUP BY first_seen_month` cannot produce a fake September spike. Read the
view, not the table.

### Why the key is not `cluster_id`

`analysis.poi_dedup.cluster_id` is **renumbered by every dedup re-run**. It is
assigned by `enumerate()` over a dict whose order is the order rows came back
from an unordered `SELECT`, plus a per-category offset that shifts when any
earlier category gains or loses one cluster. Measured on the live warehouse:
re-running the dedup on **byte-identical data in a shuffled row order**
reproduces the partition exactly (100% identical clusters, 100% identical
canonical picks) and yet **0.00%** of POIs keep their `cluster_id`.

So the ledger carries identity itself: a content hash of
`category | normalized-name | lon,lat @ 4 dp` to mint, then a **name +
distance link** (the same `norm_tokens` / `names_match` / 40 m rule that formed
the cluster) to carry a row forward when the hash moves. `cluster_id_latest` is
kept only as a convenience join key, and is NULLed on every row not seen in the
newest month so a stale join returns nothing instead of the wrong storefront.

**Nameless locations are the weak spot.** 118 of 227,548 clusters (0.052%)
collided on the content hash, and *every one* had an empty normalized name —
CJK and Arabic shopfront names (`norm_tokens` keeps only `[a-z0-9]`) and
all-generic names like "Chicken Kitchen", usually stacked on one fallback
geocode. Their key folds in the canonical `poi_id`, which keeps them apart but
means the key moves if that canonical member changes. An openings spike
concentrated in empty-`name_key` rows is a churn artefact, not turnover.

### What detect now reports

`locations_new_12m` is still a floor, but the run summary splits the
brand-locations three ways — **dated by source / dated by observation /
left-censored** — so the size of the floor is visible. The censored share
shrinks every month the job runs, and only the first two count toward
`locations_dated`.

### The guard

`loci check-presence` (wired into `make check`) asserts that **100% of current
deduplicated locations have a ledger row in the newest snapshot month**, that no
cluster is claimed by two rows, and that the `first_seen_kind` invariants hold.
It skips quietly on a clone with no warehouse.

### Out of scope: `analysis.storefront`

The DOF Local Law 157 registry inventories **commercial space**, not
businesses, its rows are filings rather than observations, and it already
carries its own history — `SELECT premises_id, min(filing_due_date) FROM
analysis.storefront GROUP BY 1`. Folding it into this ledger would put two
grains under one primary key.
---

## Installing the monthly job (launchd)

The template is `src/loci/chains/com.loci.chains-refresh.plist`. It contains
`__REPO__` placeholders because launchd expands neither `~` nor `$HOME`.

```bash
cd ~/Documents/Projects/abenmayor/loci
mkdir -p data/chains/logs
sed "s|__REPO__|$PWD|g" src/loci/chains/com.loci.chains-refresh.plist \
  > ~/Library/LaunchAgents/com.loci.chains-refresh.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.loci.chains-refresh.plist
launchctl kickstart -p gui/$(id -u)/com.loci.chains-refresh    # run it once now
```

Logs land in `data/chains/logs/`. Remove with
`launchctl bootout gui/$(id -u)/com.loci.chains-refresh`.

Two things that will bite: launchd agents get a **minimal PATH** and do not
read your shell profile (the plist sets PATH explicitly — check `which uv`
matches), and if the machine is asleep at 03:10 the job runs at next wake. A
slipped run is *mostly* harmless: `detect` is idempotent per month and the press
window is 45 days, not 30, precisely so a late run leaves no hole. The
**ledger** is the exception — a month with no `poi-snapshot` is a month with no
observation, and it cannot be reconstructed later. Slipping by days is fine; a
month skipped entirely is a permanent hole in the first-seen record.

**The job is not installed yet** (checked 2026-09-13: there is no
`~/Library/LaunchAgents/com.loci.chains-refresh.plist`). The plist is still a
template. It runs `make chains-refresh`, which now runs `poi-snapshot` first, so
no edit to the plist is needed — only the bootstrap above.

---

## Hand-editing the watchlist

`src/loci/chains/watchlist.yaml` — config lives with the code that reads it.
The field documentation is the comment block at the top of that file. Two rules:

- **`brand_key` must equal `normalize.brand_key(brand)`.** It is the join key
  to `chains.brand_snapshot`; a hand-typed key the normalizer would never
  produce joins to nothing and reports a tracked brand as undetected.
  `loci chains render` refuses to run if any row violates this.
- **`null` means "not counted", not "zero".** A seeded row carries nulls and
  `confidence: unverified`, and `docs/CHAINS.md` says so in the table.

`loci chains import <json>` upserts a research JSON (a flat array of records
with the same snake_case keys). It is **fill-only by default**: an incoming
value is written only where the curated value is empty, `evidence` is unioned
by url, and `first_added` is never overwritten. `--overwrite` lets incoming
values replace non-empty ones — but only for fields the record actually
carries, because "absent from the JSON" is not "the curator was wrong".

Three translations happen on the way in, all in `chains/watchlist.py`:

- **`KEY_ALIASES`** maps the producer's spelling to the field name
  (`net_new_nyc_12mo` → `net_new_12m`, `real_estate_role` →
  `expansion_role_title`, `evidence_urls` → `evidence`). A key that matches
  neither an alias nor `IGNORED_KEYS` is **reported, not swallowed** — dropped
  data must show up as a message.
- **`CONFIDENCE_ALIASES`** maps a certainty scale (`high`/`med`/`low`) onto the
  provenance scale. It is lossy on purpose: **an import can never produce
  `verified`**, because "the model was confident" is not "someone here counted
  the stores". Promoting a row to `verified` is a hand edit, with
  `last_verified` set at the same time.
- **`LOCI_CATEGORY_ALIASES`** maps retail vocabulary to the fifteen daily-needs
  slugs (`coffee`/`bakery` → `cafe_bakery`, `medical` → `clinic`). Anything
  unmappable — `other`, `pet`, `bookstore`, an apparel chain — becomes **null**,
  and the nulled values are listed. That is correct: those brands are real and
  worth selling to, they simply have no daily-needs category to join to.

A dry run of the first real 122-brand payload landed 119 added / 2 updated /
1 skipped, with `bookstore`, `other` and `pet` nulled.

---

## How the detect heuristics are wrong

Every one of these pushes counts **down**, so a detected count is a floor.

**Franchisee filings.** DOHMH and DCWP carry the *operating company*, not the
brand — `PRIYA FOODS INC` running a Dunkin'. Those locations are invisible to
the brand, and no normalization recovers them. This is the single largest
source of undercount for franchised chains.

**DOHMH lag, and the missing open date.** A new restaurant is inspected within
months of opening, not on opening day, and the feed publishes only the *latest*
inspection. The adapter therefore gives `detect` no first-seen date at all for
the whole food tier — which is the largest category. A new Apollo Bagels is
visible to `detect` only if Foursquare or Overture has also picked it up.

**Brands no city dataset sees.** Nothing licenses a clothing store, a bookshop,
a climbing gym or a phone-repair counter. Vital Climbing Gym is on the
watchlist precisely because open data would never have surfaced it — that is
what the curated layer and the press queries are for.

**Name variants that should merge and don't.** `FastBrand` and `Fast Brand` are
different keys and the normalizer will not merge them; a chain that files
inconsistently is split and each half looks small. The escape hatch is the
`ALIASES` map in `src/loci/chains/normalize.py` — keep it short, and every
entry is a claim someone should be able to check.

**Names that merge and shouldn't.** The dash rule is unconditional, so
`Dunkin - Baskin Robbins` collapses to `dunkin`. Trailing numbers of three or
more digits are treated as store numbers, so a brand genuinely ending in three
digits would be mangled. Two-digit tails are kept on purpose (`Cafe 88`,
`Studio 54`) — merging two unrelated two-digit bars invents a chain, which is
worse than splitting one real chain.

**Health systems and agent networks look like chains.** On the first real run,
the fastest-growing "brand" in the city was **MoneyGram** (67 of 69 locations
new in 12 months) — agent counters inside bodegas, not storefronts — and four
of the top thirty were Northwell practice lines whose long site-specific names
normalize into one key. Both are real rows; neither is a retail tenant. Read
`loci_category` and `n_sources` before believing a flag, and treat a brand with
`n_sources = 1` as unconfirmed.

**A generic name can become a brand.** "Cafe" appears as a brand key with 64
locations, because that is genuinely what some storefronts are called in the
source. Anything that reads like a common noun is an artefact.

**No supply-set filter is applied.** Unlike the address screen, `detect` reads
`analysis.poi_supply` without `in_principled`/`is_active`. That is deliberate:
dropping a store because only one source saw it understates a *young* chain,
which is the population this list exists to find. The cost is that a
single-source brand may be a data artefact — `n_sources` is published so it can
be discounted by eye.

**A high `New 3m` equal to `New 12m` usually means a source, not a chain.**
Foursquare's `date_created` is when the *record* was made, not when the store
opened, so a bulk refresh of one brand's records lands as a cluster of
same-month "openings". Northwell Labs (8 of 8 new, all within 3 months, one
source) is that pattern.

---

## Tables

Three tables and one view in the `chains` schema (`src/loci/sql/015_chains.sql`).
A fourth schema exists because a *brand* is a different grain from everything in
`analysis`, which is keyed on an address, a hex or a POI.

| Object | Grain |
|---|---|
| `chains.brand_location` | `(snapshot_month, brand_key, deduped location)` — the audit trail |
| `chains.brand_snapshot` | `(snapshot_month, brand_key)` — the monthly history |
| `chains.press_hits` | `(brand_key, url)`; `brand_key = ''` is a discovery hit |
| `chains.brand_latest` | VIEW: newest snapshot + the cross-snapshot delta |

Plus the ledger the chain work now depends on, in `analysis`
(`src/loci/sql/018_poi_presence.sql`):

| Object | Grain |
|---|---|
| `analysis.poi_presence` | one deduplicated location — its first/last observed month |
| `analysis.poi_first_seen` | VIEW: the reporting surface; NULLs a censored `first_seen_month` |

One location is one deduplicated storefront, so a Starbucks carried by both
Overture and Foursquare counts once. Since 2026-09-13 `brand_location.location_key`
is the **ledger** key, not `poi_dedup.cluster_id` — cluster_id is renumbered by
every dedup re-run, which made two months of that table incomparable — and
`first_seen_src` carries the ledger **kind** (`source_date` / `observed` /
`backfill_censored`) rather than a source field name.

---

## Recommendation tracking

*Owner ask, 2026-09-14: "start to track recommendations so that we can see how long
it takes for the free market to fill those gaps and if they do it well (with our
proposed solution)."*

The same monthly job now also scores **us**. `loci recommendations check` runs last
in `make chains-refresh`, after `storefront-pipeline build` and the `poi-snapshot`
inside `chains refresh`, because it reads both of them — checking against a stale
ledger would record an absence this month's data does not support, and a `none` is a
**stored observation**, not a skip.

### What is recorded

| Object | Grain |
|---|---|
| `analysis.recommendation` | one claim we made: area × category, dated, with an issuer |
| `analysis.recommendation_outcome` | one claim × one monthly snapshot |
| `analysis.recommendation_latest` | VIEW: each claim with its newest outcome and days open |
| `analysis.recommendation_category_summary` | VIEW: open / filled / median time-to-fill per category |

A row is an **assessment we dated**, not an instruction to open a store.
`loci recommend --record` records the whole card — the `do not act on this data`
verdicts included — because those are the **control group**: if the areas we graded
D fill as fast as the ones we graded C, the screen carries no information, and
nothing else in this project would ever tell us.

The ledger is **append-only except `status`**. DuckDB has no triggers, so the
invariant lives in `model/recommendation_ledger.MUTABLE_COLUMNS` and
`tests/test_recommendation.py` asserts that every column is classified and that the
one UPDATE in the module names nothing else. The 2026-09-11 Gowanus card graded
restaurant **D**; the 2026-09-13 regeneration graded it **C**. Both are true of their
own date, and a ledger that let the second overwrite the first would erase the only
evidence that the model moved.

### The honest first rows

Sixteen rows, all transcribed from what was actually issued — not leads invented to
give the table something to hold:

| Issued | Category | Grade | Ratio | Status |
|---|---|:-:|---:|---|
| 2026-09-10 | laundry | — | — | **withdrawn** 2026-09-11 |
| 2026-09-11 | pharmacy · convenience · hardware | D · D · C | 0.00× · 0.40× · 0.72× | open (the D73 thin leads, with a named solution and a format hint) |
| 2026-09-11 | the other twelve of the D74 card | 12 × D except tailor_repair C | 0.00×–5.58× | open |

The 2026-09-10 laundry lead is in the ledger *because* it was wrong: the supply ratio
came back 0.94× of the MN+BK baseline — normal for this city, not thin — and the lead
had been built on a raw count with no baseline. It is **withdrawn with its reason**,
never deleted. A ledger holding only the leads that survived is the survivorship bias
this exercise exists to defeat.

One transcription note: the CHECKPOINT phase line paraphrases the D74 card as "14 of
15 do not act". The card itself says 13 of 15 — hardware and tailor_repair reach C.
The **card** is what was issued, so the card is what the ledger holds.

### The match, and the radius

For each live recommendation (open **or already filled** — a filled gap still has to
be observed, or `still_open` is never measured after the fill):

1. `analysis.poi_first_seen` — same category, first-seen on or after `issued_on`,
   within the radius → `opened`. Left-censored rows carry a NULL first-seen and
   cannot match, which is right: they existed before we said anything.
2. `analysis.storefront_pipeline` — same category, same radius. Open with
   `opened_on >= issued_on` → `opened`; not open with `entry_date >= issued_on` →
   `in_pipeline`, carrying its stage.
3. Otherwise `none`, which is stored.

**A filing that predates the recommendation does not count.** Somebody who was already
building when we called the block thin is evidence the screen was stale, not evidence
we were right.

**The radius is a straight line, not the project's usual 400 m network distance.**
There is no persisted anchor-to-POI pair set to read, and a network radius from an
arbitrary anchor costs a graph load and a bounded Dijkstra for a job with a handful of
anchors. The bias has a known sign: network distance ≥ straight-line, so the disc
strictly contains the network catchment and the check is **over-inclusive** — it errs
toward "the gap filled", which is the direction that makes us look worse.
`distance_m` is stored on every match, and `--radius-m` re-cuts it.

### "Did they do it well" — the rubric

`solution_match_score` is 0–1: the sum of the components we could **confirm**. It is
not a quality rating.

| Component | Weight | Earned when |
|---|---:|---|
| `category` | 0.50 | required — a different category is not a match at all |
| `format_hint` | 0.20 | the proposal named a format and a keyword of it appears in the business name, DOHMH cuisine, DCWP business category, DOS licence type, SNAP store type or SLA description |
| `corroboration` | 0.15 | more than one source sees the storefront |
| `independent` | 0.10 | the name resolves to no chain on the watchlist or in `chains.brand_latest` |
| `still_open` | 0.05 | seen in the newest ledger month — **unavailable in the fill month**, where it is true by construction |

If only the category matches, the score is **0.50** and `quality_json` names every
component that was unavailable and why. An unavailable component is never scored as a
zero and never as a pass; `max_available` is stored beside the score so 0.50 out of
0.65 is not read as 0.50 out of 1.00. Extending it is one entry in
`recommendation_ledger.RUBRIC` with a weight and a `score(rec, cand, ctx)` callable.

Open data carries a name, sometimes a cuisine or a licence class, and a source count.
It cannot see hours, staffing, price, fit-out, or whether the place is any good.

### Time-to-fill is right-censored

An open recommendation has no `days_to_fill`; its elapsed days are a **lower bound**,
printed with a `+`. A median over the filled rows alone answers "among gaps that
filled, how fast", never "how fast do gaps fill" — so the summary view publishes
`n_open` beside the median, and `share_still_open_12m` is **NULL, never 0**, until
something has had a twelve-month anniversary. A Kaplan-Meier estimate is the honest
version and is not built: there is no exposure to build it on yet.

**A match is not a causal effect.** Nobody read our card. A filled gap says the market
moved, not that we moved it. What the ledger buys is calibration — of the places we
called thin, how many turned out to be openable — and any causal reading of it is the
D1 reverse-causality error in a new costume (D87).

### Running it

```bash
uv run loci recommendations backfill              # once; idempotent on card_hash
uv run loci recommend --area "…" --bbox … --record
uv run loci recommendations check --month 2026-09 # monthly; DELETE+INSERT per month
uv run loci recommendations report
uv run loci recommendations withdraw --rec-id … --reason "…"
```

First check, 2026-09: **15 outcome rows, all `none`** — 0 opened, 0 in pipeline. That
is the instrument, not the market. The first-seen ledger is left-censored before
2026-10 (nothing that already existed can read as an opening) and the newest pipeline
`entry_date` within 400 m of the Gowanus anchor is 2026-09-03, eight days *before* the
card was issued. The first month in which `none` means anything is **2026-10**.

---

## The forecast ledger

*Owner ask, 2026-09-14: "almost feels like we are building multiple layers here:
predicted/modeled (not what the world reflects but what it could) vs
realized/actual. worth building this out further."*

The screen is the **realized** layer: what the data reads at a doorway today. The
forecast ledger is the **modelled** one, and the only thing separating a model
from an opinion is that a model is frozen on a date and scored afterwards. So the
monthly job now issues a dated vintage and scores the vintages whose horizon has
come due.

Schema and the long-form reasoning: `src/loci/sql/028_forecast.sql`.
Code: `src/loci/model/forecast.py`. Tests: `tests/test_forecast.py`.

### What it predicts, and what it does not

`p_opening` is the probability that the **market** puts a same-category
storefront within 400 m of this doorway in the next twelve months. It is
**entry, not viability** (D88). The retrodiction established both halves:
entry is predictable out of sample (NTA-blocked AUC 0.866 against a no-score
baseline of 0.854), and survival is **not identified** in Loci's data — every
business-level closure instrument in the warehouse is a current-state extract,
and the one premises-level outcome that is identified (LL157 go-dark) returns a
null whose sign flips with the definition of attrition.

A high `p_opening` therefore says *the market is likely to act here*, never *a
shop here will work*. `loci forecast report` prints that sentence every time.

D1 is unchanged: retail is the **dependent** read. Openings are the left-hand
side; nothing is regressed on future retail.

### The objects

| Object | Grain |
|---|---|
| `analysis.forecast` | `(issued_month, model_version, address_id, category)` — one prediction, with its frozen inputs |
| `analysis.forecast_run` | `(issued_month, model_version)` — the FIT: window, coefficients, baselines, ships verdict |
| `analysis.forecast_outcome` | `(forecast_id, scored_month)` — what actually happened, at each scoring date |
| `analysis.forecast_latest` | VIEW: newest `p_opening` beside newest scored outcome, per address × category |
| `analysis.forecast_surprise_nta` | VIEW: `realized − expected` per NTA, with a cluster-robust z |

MN+BK, `frame = 'lot'`, all fifteen categories, every doorway (owner
2026-09-13: no eligibility gate — a `p_opening` of 0.004 is a forecast, and the
rows at the bottom are what make the calibration curve mean anything). Street
rows are excluded and the exclusion is not trivial: a street midpoint has no
residents, so the homes denominator of `supply_ratio` would be structurally zero
and `p_opening` would be a division artefact.

### The model, in one paragraph

Logistic, four features, category fixed effects, two stages. Features frozen at
the **first day** of the issue month: `log1p(supply_ratio)`, an own-category-gap
flag, `log(homes)` and `retail_index` — the retrodiction's specification, with
`log_jobs` and `log_transit` **withheld** because their intervals barely clear
zero against out-of-sample residual Moran's I of 0.64–0.77. A category with at
least 150 dated openings in the fit window gets **its own logit** (`support =
'fitted'`); the rest are predicted by the pooled model (`support = 'pooled'`)
and their p50 is an extrapolation of a slope estimated mostly on restaurants,
not a measurement. `expected_openings = p_opening × 1`: the unit is a
*disc-with-an-opening*, not a storefront, because 400 m discs overlap and a
Poisson rate summed over addresses would report hundreds of expected openings
for one actual shop.

Everything is **straight-line 400 m in EPSG:32618** — supply, homes, the anchor
median and the outcome radius alike, exactly as the retrodiction fixed it. D85's
rule is kept by never mixing: nothing here is comparable to
`analysis.address_category.supply_ratio_vs_base`, which is a network measure.

### The fit window, and the leakage contract

> Two stacked folds with `t0 ∈ {issue − 24 months, issue − 12 months}`, each
> carrying features frozen at **its own** `t0` and an outcome observed over
> **its own** following twelve months.

So every observation entering a fit has a source date strictly before the issue
month. Two folds rather than one because a single 12-month outcome window is
thin in the thin categories; non-overlapping rather than rolling because
overlapping outcome windows would count the same opening twice on the same
address. The **anchor** — the per-category median that turns a supply count into
a ratio — is computed on one deterministic 12,000-address hash sample at every
`t0`, for fit rows and prediction rows alike; computing it on the fit sample and
applying it to the full frame would shift the feature between fitting and
predicting, which is the quiet kind of leakage, the kind that looks like skill.

`tests/test_forecast.py` pins the contract against a synthetic ledger row dated
after the issue month, and pins the scoring window at all four boundaries.

### The baselines, and the failure criterion

Three baselines on the same NTA-blocked folds:

* **no-score** — the same design with the score dropped (`log_homes` +
  `retail_index` + category). **This is the bar.** The retrodiction's first
  draft headlined +0.048 against a homes-only comparator; the statistician's
  correction showed density + character + category FE alone reach 0.854, so the
  honest marginal contribution was +0.013. The flattering comparator is
  reported for continuity and never used as the bar.
* **persistence** — rank by whether the disc got a same-category opening in the
  twelve months *before* `t0`. Free, available at issue time, and the thing a
  sceptic would actually do.
* **homes-only** — context, not the bar.

Fixed before any vintage was issued, a run is stamped `ships = false` if the
blocked-CV AUC fails to beat no-score, or fails to beat persistence, or the
calibration max decile gap exceeds 15 points. **A failing vintage is still
written**, still dated and still scored. Deleting a vintage that failed is how a
track record becomes a highlight reel.

### The vintage and version discipline

**A past vintage is never re-issued with a newer model.** `issue` is idempotent
per `(issued_month, model_version)` by DELETE-then-INSERT: re-running the *same*
model on the *same* month reproduces that month's answer, and running a
*different* model writes a *different* version alongside, never over. Both then
get scored, and the comparison between them is the only honest way to say a
model improved.

`model_version` is `<semver>+<8 hex>`, the hex over the exact feature list in
order, the fit-window rule, the horizon, the radius and the support floor.
Change any of them and the version changes **by construction** — which is the
only version discipline that survives contact with a hurried session. A test
pins that changing the feature list changes the hash.

The temptation this forbids is precise, and it is the one every forecasting shop
loses to: re-issuing 2023-01 with the 2026 model, scoring it well, and calling
that a track record. It would be a measurement of hindsight.

### The NTA surprise, and why the obvious z is wrong

`surprise = Σ(realized_flag − p_opening)` over the addresses in an NTA. The
naive variance `Σ p(1−p)` assumes independent Bernoulli draws, and two addresses
150 m apart share nearly their whole 400 m disc — they are close to the *same*
observation. So the headline z is **cluster-robust** on 800 m grid cells
(`surprise_cell`, twice the catchment radius, assigned at issue time), with
`Var(Σr) = Σ_cells (Σ_within r)²`. `z_naive` is published beside it and the gap
between the two is the design effect. Fewer than five cells and the z is
**NULL**, not small.

`loci forecast report` prints the Bonferroni |z| threshold over the number of
NTA statistics actually computed, because a "top 10 by z" list is a maximum over
hundreds of statistics and will contain |z| > 2 under the pure null.

### The supply-set identity is part of the version (D96, GTM-163 addendum)

*Owner ruling, 2026-09-14: the closure gate (GTM-153) stays ON; a peer is
re-fitting the supply baseline, `supply_hash` moving 767b28674e30 ->
9a11a2f5....*

`model_version` covered the FORM (feature list, fit-window rule, horizon,
radius, support floor) but said nothing about which canonical POIs the frozen
features were actually read off. As of **0.1.1**, the hash also covers
`score.supply.supply_hash(con)` and the closure-gate flag
(`score.supply.GATE_CLOSED`), so two fits on the identical form but two
different supply sets get different versions by construction — a peer's
baseline re-fit changes `model_version` even though nothing about the model
itself changed. The supply hash a run was fit on is also stamped onto
`analysis.forecast_run.supply_hash` (sql/030, ALTER; NULL on any row written
before this migration landed).

`loci forecast issue` now **refuses to reuse an existing
(issued_month, model_version)** unless `--force` is passed, printing the
supply hash it is about to fit on first. This is not the vintage-idempotence
contract — DELETE+INSERT on the *same* (month, version) is still safe and
still reproduces that vintage byte for byte — it is a guard against doing
that *blindly* from the command line.

### Retention (GTM-163)

`analysis.forecast` has no natural ceiling: one issue+score cycle added
~1.4 GB (the warehouse went 1.8 → 4.6 GB, D92) and every monthly vintage adds
another ~4.2M rows. `loci forecast prune [--keep-vintages 3] [--dry-run]`
deletes **prediction rows only** — vintages older than the newest N per
`model_version` — and never touches `analysis.forecast_run` or
`analysis.forecast_outcome`, which are the ledger itself. A vintage is never
pruned while its 12-month horizon has not elapsed, or while it has not
actually been scored yet, however old its rank — `forecast score` still needs
to join its rows.

**Dry run by default.** A real prune deletes, then runs `CHECKPOINT` and a
best-effort `VACUUM` — verified empirically against DuckDB 1.5: neither
shrinks the `.duckdb` file on disk. `CHECKPOINT` flushes the WAL and marks the
freed row-groups reusable by future writes; `VACUUM` only recomputes
statistics. The file's byte size is unchanged by either. Actually shrinking
the file requires a full offline rebuild (`EXPORT DATABASE` to a new file, or
`ATTACH` a new file and `COPY FROM DATABASE current`) — out of scope for a
routine prune, and not run automatically by anything here.

### Running it

```bash
uv run loci forecast issue --month 2026-09          # monthly; idempotent per vintage
uv run loci forecast score                          # every vintage whose horizon is due
uv run loci forecast score --issued-month 2023-01 --as-of 2025-01
uv run loci forecast report                         # the track record + the surprise tables
uv run loci forecast distribution --issued-month 2026-09
uv run loci forecast prune --keep-vintages 3         # dry run; --no-dry-run to delete
```

`make chains-refresh` runs `forecast issue --month $(date +%Y-%m)`,
`forecast score`, then `forecast prune` — **after** `storefront-pipeline
build` and the `poi-snapshot` inside `chains refresh` (both the frozen supply
and the realized outcome are read off the first-seen ledger and the filings
pipeline, so issuing before them would freeze a vintage on last month's
evidence and then date it this month), and **before** `recommendations
check`. `prune` stays a dry run inside `make chains-refresh` unless
`LOCI_FORECAST_PRUNE_REAL=1` is set in the environment — the owner decides
when real deletion goes live.

`issue` and `score` do all their reading and fitting on a read-only handle and
open the write handle last, waiting up to 45 minutes for a peer session's
lock. They never work on a copy of the warehouse: a peer mid-write produces a
torn snapshot, and a vintage fitted on a torn snapshot is frozen, dated and
wrong forever.
