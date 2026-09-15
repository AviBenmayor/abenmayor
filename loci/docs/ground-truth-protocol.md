# Ground-Truth Protocol (Interceptor / Street View)

Operating procedure for an AI agent verifying what is physically at a Loci
recommendation anchor, using [Interceptor](https://github.com/Hacker-Valley-Media/Interceptor)
to drive the owner's real, logged-in Chrome.

## 1. Purpose and rules

- This is a **human-supervised, human-paced session with the owner present** —
  not an unattended job. Roughly **15 anchors per session**, then stop.
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

## 2. Inputs

The manifest comes from:

```bash
loci ground-truth plan --out data/ground_truth/manifest.csv
```

Fields per row: `rec_id`, `anchor_address_id`, `address label`, `anchor_lon`,
`anchor_lat`, `category`, `proposed_solution`, `grade`, `maps_url`,
`streetview_url`.

## 3. Per-anchor command sequence

All commands run in a dedicated tab group so the owner's own tabs are never
touched, and reuse one tab across anchors rather than accumulating new ones:

```bash
--group loci-ground-truth   # append to every interceptor command below
--reuse                     # append to every `open` below
```

For each `rec_id` in the manifest:

```bash
# 1. Open the Maps pin, text only (skip the DOM tree — we just need the panel text)
interceptor open "<maps_url>" --group loci-ground-truth --reuse --text-only
interceptor wait-stable

# 2. Check for an explicit closure label, then read the place panel text
interceptor find "Permanently closed" --group loci-ground-truth
interceptor text --group loci-ground-truth

# 3. If the URL landed on a list of results rather than a single place, use
#    tree refs to open the first result
interceptor tree --group loci-ground-truth
interceptor act <ref-of-first-result> --group loci-ground-truth

# 4. Open Street View for the same anchor
interceptor open "<streetview_url>" --group loci-ground-truth --reuse --text-only
interceptor wait-stable

# 5. Screenshot the view (path stays local, no context spent on image bytes)
interceptor screenshot --save --format webp --target-max-long-edge 1568 --quality 85 \
  --group loci-ground-truth
# move/rename the saved file to: data/ground_truth/screens/<rec_id>-<n>.webp

# 6. Read the imagery date off the Street View chrome
interceptor find "Image capture" --group loci-ground-truth
# Google renders this as "Image capture: <Month YYYY>" — record as YYYY-MM
```

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
{"rec_id": "string", "observed_at": "ISO-8601", "observer": "string", "maps_url": "string", "streetview_url": "string|null", "streetview_capture_date": "YYYY-MM|null", "screenshot_path": "string|null", "storefronts": [{"name": "string", "category_guess": "string|null", "status": "open|closed|vacant|unknown", "maps_status_label": "string|null", "notes": "string|null"}], "gap_verdict": "confirmed_gap|supply_missed|closure_missed|inconclusive", "notes": "string|null"}
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
