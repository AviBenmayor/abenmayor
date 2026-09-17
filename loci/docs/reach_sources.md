# Walk-reach thresholds: sources (D8, drafted 2026-09-05)

Bibliography backing `tiers_draft.yaml`. Each entry gives the exact
threshold(s) the source uses, quoted or tightly paraphrased, and which
category row(s) it supports.

## 1. Food access

**USDA Economic Research Service, Food Access Research Atlas — documentation.**
ers.usda.gov/data-products/food-access-research-atlas
> Low-access designations use distance thresholds of 1/2-mile or 1-mile for
> urban areas and 10-mile or 20-mile for rural areas... A low-income census
> tract qualifies as low-access if at least 500 people or 33% of the tract
> population live more than 1/2 mile (urban) from the nearest supermarket,
> supercenter, or large grocery store [the "half mile" flag is FARA's
> primary/headline urban measure; the 1-mile threshold is a secondary,
> stricter flag also published in the Atlas].
Method: 0.5-km population grid, distance measured grid-centroid to
grid-centroid, aggregated to tract. Scope is explicitly limited to
supermarkets/supercenters/large grocery — convenience stores and bodegas are
excluded from the measure. Used for: `grocery` (cited, 800 m). Negative
evidence for `convenience` (no on-point standard).

**NYC Department of City Planning — FRESH program (Food Retail Expansion to
Support Health).** nyc.gov/site/planning/plans/fresh2/fresh2-overview.page;
FRESH Food Store Areas report (nyc.gov/assets/planning/downloads/pdf/our-work/plans/citywide/archive/fresh-food-stores.pdf)
> FRESH designates underserved areas as those lacking a full-service
> supermarket within a comfortable walking distance, operationalized at
> approximately half a mile; the program has since brought a supermarket
> within walking distance of 1.2 million New Yorkers.
Originates from DCP's 2008 "Going to Market" study (presented to the Mayor's
Office/City Planning Commission, April 21 2008), which built a composite
need index (diet-related disease + limited fresh-food access) identifying
high-need areas in Northern Manhattan, the South Bronx, Central Brooklyn, and
parts of Queens/Staten Island, affecting ~3 million New Yorkers. FRESH
(2009) is the zoning/tax-incentive program that followed. Used for:
`grocery` (cited, 800 m) — NYC-specific corroboration of the USDA figure.

**City of Portland, Portland Climate Action Plan / "20-Minute Neighborhood"
program.**
> Objective: 90 percent of Portlanders live within a half-mile of a store
> that sells fresh groceries at affordable prices. A 2006 University of
> Washington study found people were willing to walk an average of ~1,445
> feet (~0.27 mi) to reach a grocery store.
Portland's 20-minute-neighborhood concept (adopted 2010, tied to the city's
Climate Action Plan) targets 90% of residents able to walk or bike to meet
daily needs (schools, parks, grocery) by 2030, using topography/rivers/
freeways as access barriers, not just Euclidean distance. Used for:
`grocery` (cited, 800 m) — a third independent convergence on 0.5 mi.

## 2. 15-minute city / 20-minute neighbourhood literature

**Moreno C, Allam Z, Chabaud D, Gall C, Pratlong F. "Introducing the
'15-Minute City': Sustainability, Resilience and Place Identity in Future
Post-Pandemic Cities." Smart Cities 4(1):93-111, 2021 (MDPI).**
> The city should be planned so that, within a 15-minute walking or cycling
> distance, residents can meet all essential needs: living, working, food
> supply, health, education, culture and leisure — organized around four
> pillars: proximity, density, diversity, digitalization (chrono-urbanism).
Important limitation for Loci: Moreno's framework sets ONE aggregate 15-
minute (1,200 m) envelope across all daily needs; it does NOT assign
different minute budgets to different amenity types (no per-category
grocery-vs-bar-vs-bank breakdown). It is precedent for the outer 1,200 m
tier and for treating "15 minutes" as a literature-comparable ceiling, but
cannot be cited category-by-category. Not used as a direct citation for any
individual row in tiers_draft.yaml; corroborates the 1,200 m tier's general
legitimacy.

**Victoria State Government / Plan Melbourne 2017-2050 — "20-Minute
Neighbourhoods."** planning.vic.gov.au/policy-and-strategy/planning-for-melbourne/plan-melbourne/20-minute-neighbourhoods
> 20 minutes is the maximum time people are willing to walk to meet daily
> needs locally (health facilities, services, schools, shopping), which
> Melbourne operationalizes as an 800 m walk from home — used as a guide/
> standard comparison measure approximating a 20-minute RETURN walk (i.e.
> ~10 minutes each way), not used as a strict cutoff.
Note the internal ambiguity Melbourne itself flags: 20 minutes is a round
trip, so the effective one-way distance is closer to Loci's 800 m / 10-min
tier, not 1,200/15-min — this is corroborating evidence for 800 m as a
"daily needs, generic bundle" distance, again not category-specific.

**City of Portland — "20-Minute Neighborhoods."** See above (food access
section); same program, general framework only (walkable environment +
range-of-daily-needs destinations + residential density), no per-category
minute breakdown beyond the grocery figure already cited.

Overall assessment for section 2: the 15-minute-city/20-minute-neighbourhood
literature is a strong precedent for the EXISTENCE of Loci's three-tier
system (400/800/1200 m already brackets Melbourne's 800 m and Moreno's
1,200 m ceiling) but supplies exactly one number that survives contact with
a specific category (Portland's grocery figure, already counted above under
food access). It does not independently license per-category assignments
for the other 14 categories.

## 3. Walk Score methodology and validation

**Walk Score Methodology.** walkscore.com/methodology.shtml
> For each address, Walk Score analyzes hundreds of walking routes to nearby
> amenities. Amenities within a 5-minute walk (0.25 miles) are given maximum
> points... no points are given after a 30-minute walk (per the public
> page's plain-language description). Independent technical write-ups
> (academic surveys of the tool, not the proprietary page itself) describe a
> polynomial distance-decay function reaching ~12% of maximum credit by 1
> mile and zero by 1.5 miles, applied per amenity category, then summed and
> renormalized. Category list (commonly reproduced, not itself on the public
> methodology page): grocery stores, restaurants, shopping, coffee shops,
> banks, parks, schools, book stores, entertainment/nightlife — 9 core
> categories in most third-party descriptions, up to 13 in some. Grocery and
> restaurants carry the highest weights (most frequent daily trips); up to
> 10 nearest restaurants, 5 nearest shops, and 2 nearest cafes are counted
> per address (vs. 1 nearest for singleton categories), to reward
> co-location.
Used for: `restaurant`, `cafe_bakery` (cited, 400 m full-credit radius);
`convenience`, `bar` (analog, 400 m — mapped from the same full-credit
radius but the category isn't explicitly named or is a stretch fit).
CAVEAT: the exact numeric weight table (which sums to 15 in one popularized
reproduction) is not published by Walk Score itself and could not be
verified against a primary source in this pass — treat any specific weight
number as third-party reconstruction, not confirmed original methodology.
The distance-decay envelope (0.25 mi full credit / ~1-1.5 mi zero credit) is
corroborated across the official page and academic reviews and is safe to
cite.

**Carr LJ, Dunsiger SI, Marcus BH. "Walk Score as a Global Estimate of
Neighborhood Walkability." American Journal of Preventive Medicine
39(5):460-463, 2010.**
> First validation of Walk Score against objective GIS-based walkability
> measures; found Walk Score correlated with established walkability indices
> (street connectivity, residential density, land-use mix) across a
> national sample.

**Carr LJ, Dunsiger SI, Marcus BH. "Validation of Walk Score for estimating
access to walkable amenities." British Journal of Sports Medicine
45(14):1144-1148, 2011.**
> Walk Score was significantly correlated with an objective audit-based
> count of walkable destinations and with self-reported walking for
> transportation, supporting its use as a proxy for amenity access
> specifically (not just general walkability).
Both Carr et al. papers are cited as the standard methodological validation
of Walk Score as a construct; neither publishes the category weight table
or decay function itself (that is Walk Score's proprietary "methodology"
page, above) — they validate that the score correlates with real-world
walkable access, which is the basis for borrowing its decay SHAPE (per
H-L4's framing) while being cautious about its category weights.

## 4. Category-specific access standards

**Guadamuz JS, Wilder J, Mouslim MC, Zenk SN, Alexander GC, Qato DM. "Fewer
Pharmacies In Black And Hispanic/Latino Neighborhoods Compared With White Or
Diverse Neighborhoods, 2007-15." Health Affairs 40(5):802-811, 2021.**
(Summarized via USC Schaeffer Center: today.usc.edu/pharmacy-deserts-american-cities-health-disparities-usc-research)
> Pharmacy deserts are neighborhoods where the average distance to the
> nearest pharmacy is >= 1 mile; the qualifying distance drops to >= 0.5
> mile in low-income neighborhoods with substantial no-vehicle-household
> populations, to account for reduced mobility. Found ~1 in 3 neighborhoods
> in the largest US cities were pharmacy deserts by this definition,
> disproportionately Black and Latino.
Used for: `pharmacy` (cited, 800 m — the low-income/low-vehicle-ownership
threshold, judged the applicable case for NYC).

**Centers for Disease Control and Prevention. "Development of a Nationally
Representative Built Environment Measure of Access to Exercise
Opportunities." Preventing Chronic Disease 12:E140, 2015.**
cdc.gov/pcd/issues/2015/14_0378.htm
> A person has access to exercise opportunities if they live within 0.5
> mile of a park, OR within 1 mile of a recreational facility, in an urban
> census tract (3 miles in a rural tract).
Used for: `fitness` (analog, 1,200 m — literature's 1-mile/1,609 m figure
exceeds Loci's tier ceiling, so 1,200 m is used as the nearest available
tier, understating the source by ~400 m).

**Banking desert convention** (Federal Reserve Bank of St. Louis;
summarized in Richmond Fed, "High and Dry: Banking Deserts Increased in the
Fifth District During the Pandemic," 2024, and Bank Policy Institute
research notes).
> A banking desert is a census tract whose centroid is more than a threshold
> distance from the nearest bank branch: commonly 2 miles for urban tracts,
> 5 miles for mixed tracts, 10 miles for rural tracts.
Used for: `bank` — cited as the standard convention, but scored `none` in
tiers_draft.yaml because 2 miles (~3,200 m) is 2.7x Loci's max 1,200 m tier
and the convention is explicitly built around driving access; forcing it
into a walk tier would misrepresent the source.

**Child care access literature** — Center for American Progress, "Mapping
America's Child Care Deserts" / "Measuring America's Licensed Child Care
Supply" (americanprogress.org, various years); Davis EE, Lee W, Sojourner A,
Early Childhood Research Quarterly, 2019.
> CAP's headline "child care desert" definition is a supply ratio (>=3
> children under age 6 per licensed slot in the local area), not a distance
> threshold. CAP's continuous-distance access measure (a later refinement)
> searches for providers within a 30-MILE radius per hexagon — a regional
> labor-market-style radius, not a walk-access cutoff. Davis, Lee & Sojourner
> introduce continuous family-to-provider distance as an access construct
> but do not publish a walk-specific policy threshold.
Used for: `childcare` — no citable walk threshold; scored `none`.

**Primary care / urgent care access** — HRSA Bureau of Primary Health Care;
Robert Graham Center, "Comparison of Primary Care Service Areas and
Estimated Drive Times" (graham-center.org).
> 94% of Americans live in a census tract within a 30-minute DRIVE time of a
> federally-funded health center service site; average drive time to the
> nearest primary care physician is ~24 minutes in rural areas.
Confirms the task's expectation: no walk-based standard exists for
clinic/urgent-care access in the literature reviewed — all major standards
(HRSA, Graham Center) are drive-time. Used for: `clinic` — scored `none`.

**Bathhouse / sauna / banya access** — no walk-distance standard in any
source reviewed (2026-09-17, GTM-198). The category's own literature is
trade-area shaped: CONTEXT.md §7 AC-1 point 5 and Appendix A8 put its
catchment at a 15–30 minute drive or transit trip, 2–4× Loci's 1,200 m
ceiling. Used for: `bathhouse_sauna` — scored `analog` at 1,200 m via the
CDC recreational-facility measure that backs `fitness` (the CDC facility
list is NAICS 713940, not 812199, so the analogy is behavioural — a booked,
occasional, travel-for-it trip — not a citation of the category). Owner norm
12 min / 960 m. Either value makes the missing set nearly every MN+BK
address (~45 venues citywide), which is why reach_tiers.yaml's justification
says the value exists so the loader does not raise, not because it measures
access.

**No standard found** (searched, nothing on-point): laundromat/dry-cleaner
consumer access distance (siting guides address operator trade-area
economics, ~1 mile, not a resident-access norm); hair/barber and
nail/beauty personal-grooming access; tailor/shoe-repair access; hardware/
home-supply store access. All four scored `none` in tiers_draft.yaml.

## 5. NYC-specific walk conventions (context, not per-category citations)

**NYC PlaNYC (2007) / OneNYC 2050 — park access goals.**
> PlaNYC: virtually every New Yorker within a 10-minute walk of a park by
> 2030. OneNYC 2050: 85% of residents within walking distance of a park by
> 2030. CEQR Technical Manual / NYC Parks "Walk to a Park" operationalize
> "walking distance" as 1/4 mile (400 m) for small sites (playgrounds,
> sitting areas) and 1/2 mile (800 m) for larger parks (>6 acres) or parks
> with a recreation center.
Not a category in Loci's bundle (parks are explicitly excluded per
CONTEXT.md §2.1), but establishes NYC's own planning convention that splits
exactly at 400 m / 800 m — independent confirmation that Loci's tier
spacing matches how the city itself defines "near" vs. "far" on foot, and
the closest thing to an NYC-native precedent for the two lower tiers.

**MTA/NYC DCP subway walkshed convention.**
> Standard convention: 0.5 mile walk to rail transit, 0.25 mile to bus
> transit. DCP publishes "Walksheds — MTA Subway" (quarter- and half-mile
> rings from every station) on ArcGIS Hub.
Not a category in Loci's bundle, but confirms 800 m (0.5 mi) as NYC
planning's standard "rail-scale" walk radius — the same figure the food-
access literature converges on for grocery/pharmacy, reinforcing 800 m as
the credible mid-tier rather than an arbitrary round number.
