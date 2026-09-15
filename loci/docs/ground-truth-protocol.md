# Ground-Truth Protocol (Interceptor / Street View)

Operating procedure for an AI agent verifying what is physically at a Loci
recommendation anchor, using [Interceptor](https://github.com/Hacker-Valley-Media/Interceptor)
to drive the owner's real, logged-in Chrome.

## 1. Purpose and rules

- This is a **human-supervised, human-paced session with the owner present** —
  not an unattended job. Roughly **15 anchors per session**, then stop.
- **Session cap (owner ruling 2026-09-15, QUESTIONS D36):** no Google Maps
  segment runs longer than **30 minutes**, and consecutive segments are
  separated by a break of **at least 2 minutes** with no Maps page loads.
  Note the segment start time in the run notes; when 30 minutes elapse,
  finish the anchor in progress, `interceptor wait 120000`, then continue.
  The first session (57 page loads, 19 anchors) ran about 28 minutes.
- **Never run this in a loop or unattended.** Google's terms of service forbid
  automated querying of Maps/Street View; this protocol is a supervised,
  assistive session at the owner's keyboard, same standing as the
  owner-approved BizQuest browser session earlier in the project.
- **Absence is never evidence of closure (project rule D79).** A storefront
  not visible, or a business not named, in Street View is `unknown` — never
  `closed`. Only an explicit Google Maps **"Permanently closed"** label (or an
  equivalent unambiguous label, e.g. "Temporarily closed") yields a `closed`
  status. No inference from a shuttered gate, no storefront, or dark windows
  alone.
- **The free price channel (owner decision 2026-09-15, D105).** Google Maps
  shows a price token (`$`, `$$`, `$10–20`, ...) right next to the rating on
  most listings the protocol already reads. Copying it costs nothing extra —
  no new page load, no new read — so every storefront record also carries
  `price_label`, copied verbatim, never parsed or inferred (see §3, §4). This
  does **not** extend the session cap or the scope above: price is captured
  only for storefronts this protocol was already going to read. QUESTIONS D49
  found the token present on roughly 80% of matched food/bar places and on
  none of the service categories checked, so in practice this channel is
  food-only — a coverage limit, not a bug in the copying rule.

## 2. Inputs

The manifest comes from:

```bash
loci ground-truth plan --out data/ground_truth/manifest.csv
```

Fields per row: `rec_id`, `anchor_address_id`, `area_kind`, `address_label`,
`anchor_lon`, `anchor_lat`, `category`, `proposed_solution`, `grade`,
`nearby_url`, `address_url`, `streetview_url`, `maps_url`.

Four URLs, three of which get opened (verified live 2026-09-15 against 376
Graham Ave, a bank anchor):

- **`nearby_url`** — a category-nearby search
  (`/maps/search/<term>/@lat,lon,18z`) centered on the anchor. This is the
  read that answers the actual question: is there an open storefront of the
  *recommended category* near here. It returns a results list — name,
  category, address, and a status label per hit.
- **`address_url`** — an address search (`/maps/search/<address label>`) that
  opens the building's own panel: what tenant Maps has on file at this exact
  address. `null` when the anchor is not an address (`area_kind != 'address'`
  — a bbox/NTA card has no doorway to look up).
- **`streetview_url`** — the anchor in Street View, for a visual read and the
  imagery capture date.
- **`maps_url`** — a bare coordinate pin. Kept for reference only: opening it
  directly shows a pin with no business list attached, so it answers nothing
  on its own and is not part of the read sequence below.

`address_label` (and, from it, `address_url`) is a real, geocodable street
address whenever `data/raw/pluto.csv` (MapPLUTO, ~330 MB, gitignored) is on
disk — `plan()` reads it keyed by BBL, which is `anchor_address_id` for a
lot-frame row, and prefers it over every other source (verified live
2026-09-15: `376 Graham Avenue, Brooklyn, NY 11211`, `379 Broome Street,
Manhattan, NY 10013`, `4 East 8 Street, Manhattan, NY 10003`, `545 Sackett
Street, Brooklyn, NY 11217`). `analysis.address` itself carries no
house-number/full-address column at all, so a run without the PLUTO extract
on disk (a fresh clone, CI) falls back to the recommendation's own
`area_label` — which for a rec issued through the address-resolution flow is
also a real street address, just not always for older ones — and only then
to a neighborhood/borough label with no street number. If `address_url` does
not land on a specific building panel, treat it as inconclusive for that read
and rely on `nearby_url` + Street View instead — do not force a match.

## 3. Per-anchor command sequence

All commands run in a dedicated tab group so the owner's own tabs are never
touched, and reuse one tab across anchors rather than accumulating new ones:

```bash
--group loci-ground-truth   # append to every interceptor command below
--reuse                     # append to every `open` below
```

For each `rec_id` in the manifest, in this order — **nearby, then address,
then Street View** — because `nearby_url` is the only one of the three that
answers "is there an open storefront of the recommended category near the
anchor," which is the question this whole protocol exists to check:

```bash
# 1. Open the category-nearby search, text only (skip the DOM tree — we just
#    need the results-list text). This is the FIRST read, not the pin.
interceptor open "<nearby_url>" --group loci-ground-truth --reuse --text-only
interceptor wait-stable
interceptor text --group loci-ground-truth
# Read the results list: name, category, address, status per hit. Two things
# to hold in mind while reading it:
#   - "Sponsored" entries are ads, not businesses at the anchor. Skip them.
#   - Results extend well beyond the 400 m catchment the gap score is
#     computed over -- there is no radius cutoff on the list. Judge distance
#     from each hit's own listed address against the anchor, by eye; do not
#     assume the top result is the closest one.
#   - "Permanently closed" appears in the SAME position in the listing as an
#     open business's status (e.g. "Open · Closes 5 PM") -- read that field
#     for every hit, it is not a separate flag.
#   - A price token often follows the rating in the SAME line, e.g.
#     "4.5(304) · $$" or "4.2(88) · $10–20". Copy it into `price_label`
#     VERBATIM -- the whole token, including a range -- and leave it null
#     when no such token is shown. Never infer a price from the category or
#     the neighborhood; this is a free byproduct of a read already made, not
#     a second lookup (see §1).

# 2. Open the address search for the anchor's own building (skip when
#    address_url is null -- a bbox/NTA card has no doorway to look up)
interceptor open "<address_url>" --group loci-ground-truth --reuse --text-only
interceptor wait-stable
interceptor find "Permanently closed" --group loci-ground-truth
interceptor text --group loci-ground-truth
# If the panel shows a rating line ("4.5(304) · $$"), copy that same price
# token into `price_label` as in step 1 -- one field, whichever read supplied
# it; do not merge two conflicting tokens from the two reads. If neither read
# showed one, price_label stays null.
# If the URL landed on a list of results rather than a single building panel,
# use tree refs to open the first result:
interceptor tree --group loci-ground-truth
interceptor act <ref-of-first-result> --group loci-ground-truth

# 3. Open Street View for the same anchor
interceptor open "<streetview_url>" --group loci-ground-truth --reuse --text-only
interceptor wait-stable

# 4. Screenshot the view. --save takes no path -- it writes an auto-named
#    file into the CURRENT DIRECTORY -- so run this from inside
#    data/ground_truth/screens/, then rename the result.
cd data/ground_truth/screens
interceptor screenshot --save --format webp --target-max-long-edge 1568 --quality 85 \
  --group loci-ground-truth
mv <auto-named-file>.webp <rec_id>-<n>.webp

# 5. Read the imagery date off the Street View chrome
interceptor find "Image capture" --group loci-ground-truth
# Google renders this as "Image capture: <Month YYYY>" — record as YYYY-MM
```

`maps_url` (the bare coordinate pin) is not part of this sequence — opening it
directly shows a pin with no business list, so it answers nothing that
`nearby_url` doesn't already answer better. It is still in the manifest, for
reference and for `analysis.address_observation.maps_url`'s repeatability
column.

Optional — rotate the Street View camera to see both sides of the street
before deciding `unknown` vs a confident read. Use the WebGL pan/zoom recipe
(`interceptor eval --main "<dispatched MouseEvent/WheelEvent script>"` on the
Street View canvas, per Interceptor's
`use-cases/interaction-skills/webgl-camera-control.md`): drag-pan via
`mousedown` → `mousemove`×N → `mouseup` dispatched on the canvas element
(`event.__interceptor_trust = true` on each), or wheel-zoom via a
`WheelEvent`. Re-screenshot after rotating if the second side changes the
verdict.

At the end of the session, clean up the dedicated tab group (either form is
correct per the README — prefer group close, fall back to closing the tab):

```bash
interceptor group close --group loci-ground-truth
# or, if group close is unavailable in your build:
interceptor tab close --group loci-ground-truth
```

## 4. Verdict rules

For **each storefront seen** at the anchor, record:

- **name** — as displayed on the sign / Maps listing.
- **category_guess** — one of the 15 Loci categories, or `null` if it does
  not map cleanly:
  `bank`, `bar`, `cafe_bakery`, `childcare`, `clinic`, `convenience`,
  `fitness`, `grocery`, `hair_barber`, `hardware`, `laundry`, `nails_beauty`,
  `pharmacy`, `restaurant`, `tailor_repair`.
- **status** — one of:
  - `open` — Maps shows the listing as operating (no closure label), or
    Street View shows an active, signed, stocked storefront.
  - `closed` — Maps panel or a listing explicitly says "Permanently closed"
    (or an equivalent explicit label). This is the *only* path to `closed`.
  - `vacant` — Street View clearly shows an empty, unleased storefront
    (For Lease/For Rent signage, bare interior, no business name anywhere)
    and there is no matching Maps listing at all.
  - `unknown` — anything else: no clear signage, imagery too old to trust,
    panel unreadable, or absence with no explicit closure label. Per rule
    D79, absence alone is always `unknown`, never `closed`.
- **maps_status_label** — the exact label text from Maps, verbatim (e.g.
  `"Permanently closed"`), or `null` if Maps showed no status label.
- **price_label** — the exact price token from Maps, verbatim (e.g. `"$$"`,
  `"$10–20"`, `"$100+"`), copied from wherever the rating line was already
  being read (§3) — never normalised to a tier and never inferred when Maps
  showed none. `null` when absent. String, at most 32 characters. This is the
  free price channel (§1, D105): captured only for storefronts already being
  read, and in practice populated mostly for food/bar places (D49).

For **each anchor**, record one `gap_verdict`:

- `confirmed_gap` — no open storefront of the recommended category is
  visible within sight of the anchor.
- `supply_missed` — an open storefront of the recommended category is
  present, but the model recommended it as a gap (missing supply).
- `closure_missed` — the model counts a POI here as open, but Maps labels it
  "Permanently closed."
- `inconclusive` — Street View imagery is older than 18 months and there is
  no matching Maps listing, or the place panel could not be read.

## 5. Output

Write one JSONL record per anchor, exactly in this schema:

```json
{"rec_id": "string", "observed_at": "ISO-8601", "observer": "string", "maps_url": "string", "streetview_url": "string|null", "streetview_capture_date": "YYYY-MM|null", "screenshot_path": "string|null", "storefronts": [{"name": "string", "category_guess": "string|null", "status": "open|closed|vacant|unknown", "maps_status_label": "string|null", "price_label": "string|null, <=32 chars, verbatim", "notes": "string|null"}], "gap_verdict": "confirmed_gap|supply_missed|closure_missed|inconclusive", "notes": "string|null"}
```

Then ingest and report:

```bash
loci ground-truth record data/ground_truth/session-<date>.jsonl --run-id <id>
loci ground-truth report
```

## 6. Threats to validity

- **Street View imagery age vs. today** — the capture date can be months to
  years stale; a storefront may have turned over since.
- **Maps listings lag real closures and openings** — a business can be
  closed on the ground before Maps updates, or already open before it is
  listed.
- **Pin placement** — the anchor pin may sit on the wrong side of the street
  from the actual storefront.
- **Category mapping is a judgment call** — when the mapping from a visible
  business to one of the 15 Loci categories is uncertain, record that
  uncertainty in `notes` rather than guessing silently.
- **Anchor-only coverage** — these observations cover only the anchor point,
  not the 400 m catchment the gap score is computed over. A `confirmed_gap`
  at the anchor does not, by itself, confirm the catchment-level gap.

## 7. Install prerequisites

- Interceptor Browser pkg, v1.0.1, from the
  [GitHub Releases](https://github.com/Hacker-Valley-Media/Interceptor/releases) page.
- The Interceptor Chrome Web Store extension (same profile as the owner's
  logged-in Chrome).
- `interceptor status` reports `mode: browser-only` before starting a session.
