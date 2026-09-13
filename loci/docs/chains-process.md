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
make chains-refresh          # = loci chains refresh: detect -> research -> render
```

Run on the 1st of each month. Each step is also a command of its own:

```bash
uv run loci chains detect   [--month 2026-09] [--dry-run] [--limit 25]
uv run loci chains research [--max-queries 60] [--days 45] [--detected 20] [--dry-run]
uv run loci chains import   path/to/brands.json [--overwrite] [--dry-run]
uv run loci chains render   [--month 2026-09] [--dry-run]
```

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

The fix that depends on no source's dates is to **take the count ourselves,
every month**, and difference it. `chains.brand_latest.locations_delta_since`
is that measure. It is NULL until two snapshots exist — NULL means "not yet
measurable", never zero. The list gets materially more trustworthy after a
year of snapshots, and that is the whole reason for the cron job.

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
slipped run is harmless: `detect` is idempotent per month and the press window
is 45 days, not 30, precisely so a late run leaves no hole.

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

One location is one `analysis.poi_dedup.cluster_id`, so a Starbucks carried by
both Overture and Foursquare counts once.
