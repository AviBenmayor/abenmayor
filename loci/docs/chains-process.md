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
