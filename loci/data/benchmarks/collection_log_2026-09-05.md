# BizQuest NYC comps collection log — 2026-09-05

## Run 2

Resumed from a prior run that had collected 46 rows (per brief) — the CSV actually
already held 49 rows at the start of this run, including 3 `hardware` rows the brief's
stated counts said were zero (`BW2536314`, `BW2499596`, `BW2289338` — Manhattan/Queens).
That discrepancy predates this run; not something this run caused. Stopped mid-collection
on a coordinator instruction to close out immediately, so several planned lookups
(Queens/Staten Island clinic top-up, hardware/childcare/fitness top-up beyond what's
below) were not attempted.

### Page loads used
Approximately 15 full page navigations (listing pages + category index pages), plus a
handful of in-page dropdown interactions (Industries filter clicks) that did not count
as page loads. Well under the 80-load cap.

### Index / category pages visited
- `https://www.bizquest.com/health-clubs-gyms-and-fitness-centers-for-sale-in-new-york/` (statewide fitness/health-club index — filtered by borough text in listing cards, not a native NYC filter)
- `https://www.bizquest.com/medical-clinics-for-sale-in-new-york/` → **0 results** (category exists but is empty for NY)
- `https://www.bizquest.com/medical-practices-businesses-for-sale-in-new-york/` (statewide; used for clinic candidates)
- `https://www.bizquest.com/day-care-and-child-care-centers-for-sale-in-new-york/` (statewide; used for childcare candidates)
- `https://www.bizquest.com/businesses-for-sale/` (nationwide root, used only to open the Industries filter UI and discover real category-slug URLs via its checkboxes — BizQuest's URL slugs aren't guessable from category labels; `/health-clubs-gyms-fitness-centers-for-sale/new-york-ny/` guessed cold 404'd, the real slug pattern is `<category-slug>-for-sale-in-new-york`, discovered by clicking through a real listing's breadcrumb link)

None of BizQuest's category pages are natively NYC-scoped — they are NY-statewide, so
every listing had to be individually checked for a NYC borough (Manhattan/Brooklyn/
Queens/Bronx/Staten Island) vs. Long Island/Westchester/upstate before counting it.

### Rows added this run: 10

| listing_id | category | borough | asking | gross_revenue | rent | sqft |
|---|---|---|---|---|---|---|
| 2409955 | fitness | Brooklyn | 850,000 | 1,445,463 | 30,000/mo | 20,000 |
| 2489271 | fitness | Bronx | 225,000 | — | — | 1,800 |
| 2539718 | fitness | Queens | 400,000 | 189,758 | 7,426/mo | 4,000 |
| 2479530 | fitness | Staten Island | 399,000 | — | — | 14,000 |
| 2519730 | clinic | Manhattan (Midtown East) | 2,200,000 | 1,693,202 | — | — |
| 2513188 | clinic | Brooklyn | 290,000 | 721,178 | — | 1,600 |
| 2508047 | childcare | Bronx | 400,000 | 232,000 | — | 1,560 |
| 2476244 | childcare | Brooklyn | 1,000,000 | 803,620 | — | 3,500 |
| 2514381 | childcare | Brooklyn | 650,000 | — | 7,500/mo | 1,200 |
| 2441387 | childcare | Queens | 349,000 | 389,971 | 5,600/mo | 1,400 |

### Per-category counts after this run (59 total rows in CSV)
restaurant 8, laundry 6, cafe_bakery 5, grocery 5, convenience 5, pharmacy 5, bar 4,
hair_barber 4, fitness 4, childcare 4, nails_beauty 3, hardware 3, clinic 2,
tailor_repair 1, bank 0 (not listable on BizQuest — see brief; no page loads spent on it).

### Fill rates (whole CSV, n=59)
- gross_revenue: 41/59 (69.5%)
- cash_flow_sde: 8/59 (13.6%)
- rent: 35/59 (59.3%)
- sqft: 34/59 (57.6%)

### Ambiguities / judgment calls
- **BW2528760 (2nd "Martial Arts Business for Sale in New York", Queens) — skipped as a
  likely duplicate of BW2539718.** Same LISTING ID # 36779 in the description, same
  address/facility (4,000 sq ft, Queens, martial arts, NYC-school vendor since 2008), same
  asking price ($400,000), but internally inconsistent gross income ($189,758 on 2539718 vs
  $120,000 on 2528760) and rent ($7,426/mo vs $7,210/mo). Kept only the first (2539718);
  including both would double-count one underlying business as two comps.
- **BW2456127 (Bronx "Urgent Care", start-up listing type) — excluded, not added as a
  row.** This is a BizQuest "Start-Up" listing (Initial Fee / Capital Required fields),
  not a standard resale with Asking Price / Cash Flow / Gross Revenue — structurally
  not comparable to the other comps and has no real financial disclosure.
- **BW2479530 (Staten Island pickleball facility) category is genuinely ambiguous.**
  BizQuest's own top badge tags it "Food & Beverage | Bars & Taverns" (it has a full bar),
  but the page's breadcrumb trail files it under "Health & Medical | Health Clubs, Gyms &
  Fitness Center," and it surfaced in the fitness/health-club search index. Recorded as
  `fitness` (content-driven: 8 pickleball courts is the core business) with both tag sets
  preserved in `raw_category_text`.
- **BW2441387 (Queens "STEM Education Franchise") is a borderline `childcare` fit.**
  It's an after-school STEM enrichment program for ages 7–14, not a licensed
  daycare/preschool — but BizQuest itself files it under "Educational | Day Care & Child
  Care Centers" (its bottom breadcrumb inconsistently says "Other Educational" instead).
  Recorded as `childcare` per BizQuest's own primary categorization since our schema has
  no separate youth-enrichment bucket; flagging for the owner to reconsider/exclude if a
  stricter "actual daycare" definition is wanted.
- **BW2476244 (Brooklyn childcare) title claims "$350K SDE"** but the listing's own
  structured Cash Flow field says "Sign In to View" (not disclosed to us). Left
  `cash_flow_sde` blank rather than trusting the marketing headline, per the convention of
  only using the site's disclosed field, not title copy.
- **BW2514381 (Brooklyn infant/toddler childcare)**: description gives partial-year
  tuition revenue (~$187,595 for Jan–Jun 2026) but the structured Gross Revenue field says
  "Not Disclosed." Left `gross_revenue` blank rather than annualizing a partial figure.
- **Medical Clinics category (the literal BizQuest subcategory name) returned 0 NY
  results** — all clinic comps came from the broader "Medical Practices" subcategory
  instead, which mixes urgent/primary care with dental, chiropractic, ophthalmology, etc.
  Both `clinic` rows added here are primary/internal-medicine practices (closest fit to
  "Clinic / urgent care"); narrower specialty practices (dental, plastic surgery, etc.)
  seen on that index were deliberately excluded as poor category fits.
- Not attempted before stop: Manhattan/Staten Island clinic top-up, hardware/nails_beauty/
  hair_barber/bar/grocery/convenience top-up toward 8 each per the brief's priority (2).
  Tab left open on the last-visited listing page (STEM Education Franchise, BW2441387).
