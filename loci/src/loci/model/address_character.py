"""NEIGHBOURHOOD CHARACTER at address grain (owner request, 2026-09-13).

    retail_area_400m / office_area_400m / res_area_400m / factory_area_400m
    bldg_area_400m                      MapPLUTO floor area, SQUARE FEET, over
                                        every tax lot within 400 m NETWORK m
    jobs_retail_400m / jobs_office_400m / jobs_other_400m
                                        LODES8 WAC jobs in 2020 blocks within
                                        the same 400 m, split into three
                                        DISJOINT sector groups that sum to
                                        analysis.address.jobs_400m (C000)

    analysis.address_character           a VIEW: the shares and the label
    analysis.nta_character               a VIEW: the NTA roll-up

"Give color to neighborhoods for whether they are retail- or corporate-
dominated." Two addresses with identical `homes_400m`, `jobs_400m` and
`transit_entries_400m` are the same number to everything downstream and are not
the same retail location if one of them is surrounded by 30 million square feet
of offices emptying at 6 p.m. and the other by rowhouses. `jobs_400m` is a
single total that cannot tell the two apart -- 20,000 jobs is Midtown or it is
a hospital campus or it is a distribution cluster, and those are three
different customers.

THE LOT SET -- THE ONE PLACE "REUSE homes_400m's SET" WOULD HAVE BEEN WRONG
---------------------------------------------------------------------------
The brief asked for the exact lot set `homes_400m` sums over. That set is
`analysis.address` itself, which is `PLUTO lots WHERE UnitsRes > 0`
(sources/cities/nyc/addresses.py: address_id IS the BBL, one row per tax lot).
It therefore contains NO pure-office, pure-retail and NO industrial lot. Summed
over it, OfficeArea would report the Financial District, Midtown East and
Industry City as ZERO office and ZERO factory floor area, and the label would
call Midtown "residential" -- the exact failure this measure exists to detect.

So the weight set here is EVERY MapPLUTO lot with usable coordinates inside the
scope bounding box. The catchment ENGINE is byte-for-byte the same one:
`score/access._prune` + `_to_csr` build the undirected CSR (see that module on
NOT mirroring edges -- csr_matrix SUMS duplicate entries, which doubled every
distance once already), and `model/supply_ratio.catchment_sums` does the sweep,
sourced FROM the query nodes, one bounded scipy Dijkstra per batch. Same pruned
graph, same 400 m, same `ox.distance.nearest_nodes` snapping, same
accumulate-never-deduplicate rule.

ONE DELIBERATE DIFFERENCE FROM homes_400m, AND IT IS NOT A BUG. `homes_400m`'s
weight set is `analysis.address`, which since D78 holds MANHATTAN AND BROOKLYN
ONLY -- so a Bushwick address at the Queens line gets no credit for Ridgewood's
housing, and `homes_400m` carries a real borough-boundary edge effect.
`load_lot_points` reads PLUTO directly and takes every lot in the padded scope
bbox, Queens and the Bronx included, so these four area columns do NOT have that
edge effect. The consequence: at the borough line, `res_area_400m` and
`homes_400m` disagree in a way that is the AREA column being right and
`homes_400m` being truncated. Never form a ratio of the two there. Filtering
these lots to `unitsres > 0` reproduces `homes_400m`'s weight set only INSIDE
MN+BK; that is the subset on which the two are comparable.

WHY THE PAIR TABLE IS *NOT* PERSISTED
---------------------------------------------------------------------------
The brief offered `analysis.address_lot(address_id, bbl, dist_m)` as a
persisted pair set so future measures are SQL-only. It is not built, and the
reason is arithmetic, not taste: 281,842 MN+BK addresses x roughly 500-1,500
PLUTO lots inside a 400 m walk is 1.4-4 x 10^8 rows, 6-12 GB in a 1.5 GB
warehouse -- to store a set that the sweep regenerates in 42 SECONDS. (The
addresses collapse onto 39,083 distinct graph nodes, so the Dijkstra runs 815
times, not 281,842.) The reusable
artefact here is the WEIGHT-VECTOR contract instead: adding a new lot-derived
catchment measure is one more column in `LOT_WEIGHTS` and costs nothing extra,
because `catchment_sums` computes k weight columns in the SAME Dijkstra. That
is the same trade `model/address_access.py` made for transit and jobs.

CATEGORY-INDEPENDENT, SO analysis.address AND NOT address_category
---------------------------------------------------------------------------
The same office towers are within 400 m whether you are asking about pharmacies
or bars. On `analysis.address_category` these would be fifteen identical copies
of one number -- the pivot-shaped duplication D61 removed. New measures at an
existing grain extend that grain (owner rule, D61 inventory).

UPDATE-ONLY, NON-FILTERING
---------------------------------------------------------------------------
`write_character` issues ONLY `UPDATE analysis.address SET <CHARACTER_COLUMNS>`,
and `CHARACTER_COLUMNS` is asserted disjoint from the screen's own columns and
from every sibling annotation before the statement runs (`_guard`, plus
tests/test_address_character.py). RESET-then-UPDATE in scope, for the reason
every sibling resets: an address that leaves scope, or a rebuilt graph, must
not keep the previous run's number.

An address does not become a gap because it is near an office tower and does
not stop being one because it is not. These columns do NOT enter `gap_score`,
`supply_ratio_vs_base`, the revenue model or any recommendation grade.

RE-APPLY AFTER EVERY SCREEN RE-RUN -- NOT OPTIONAL
---------------------------------------------------------------------------
`loci address-gaps` DELETEs and re-INSERTs analysis.address, so these twelve
columns come back NULL exactly as every other annotation does. Run
`loci address-character build --boroughs MN,BK` in the same re-apply sequence
as `loci address-access` / `loci transit-profile`; `character_run_at IS NULL`
is the flag that says it has not been.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. PLUTO FLOOR AREAS ARE AN ASSESSMENT ARTEFACT. `areasource` records whether a
   lot's use split came from DOF records, a DCP estimate, or a sketch. A
   mixed-use rowhouse's ground-floor store is frequently folded into ComArea
   and never reaches RetailArea, so `retail_area_400m` is a FLOOR on storefront
   floor area and the shortfall is worst exactly on old mixed-use retail
   strips -- the places this measure most wants to find. Read the retail SHARE
   as an ordering, never as square feet of shops.
2. LODES COUNTS PAYROLL JOBS AT A BLOCK CENTROID, not people on a sidewalk.
   Remote and hybrid workers are counted at an office they may not enter, which
   biases `jobs_office_400m` UP relative to present-day daytime population
   post-2020; most of the self-employed are not counted at all.
3. `jobs_other_400m` IS A REMAINDER, NOT A CATEGORY. Health care and social
   assistance (CNS16) and education (CNS15) are its two largest members in New
   York. A hospital or a university campus reads as `other`-dominated, which is
   correct -- it is neither storefront retail nor desk work -- but a reader who
   treats `other` as "nothing here" will misread Morningside Heights and the
   Bellevue/NYU corridor.
4. AREAS ARE STOCK, JOBS ARE PAYROLL FLOW, AND THE TWO DISAGREE. The label
   takes either as sufficient on purpose; both shares stay on the view so a
   reader can see which criterion fired.
5. NEVER SUM A CATCHMENT COLUMN ACROSS ADDRESSES. A lot within 400 m of N
   addresses is counted N times by design.
6. THE NTA ROLL-UP IS ADDRESS-WEIGHTED, and `analysis.address` is residential
   lots, so a NTA's mean shares are "what the average RESIDENT's five-minute
   walk contains", not "what the average acre of the NTA contains". In an NTA
   with a large non-residential district and a small residential pocket (Sunset
   Park waterfront, the FiDi fringe) those two are very different numbers.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pickle

import numpy as np
import osmnx as ox
import pandas as pd

from loci.grid.pluto import PLUTO_CSV
from loci.model.address_access import (
    BBOX_PAD_DEG,
    LODES_DIR,
    XWALK,
    load_address_points,
)
from loci.model.conveniences import graph_version
from loci.model.supply_ratio import BATCH, catchment_sums, node_weights
from loci.score.access import MIN_COMPONENT, THRESHOLDS, _prune, _to_csr
from loci.score.walkgraph import OUT as GRAPH_PATH

#: 5-minute walk, pinned to THRESHOLDS[5] exactly as supply_ratio, storefronts,
#: dev_pipeline and address_access pin it, so "within reach" is ONE distance
#: everywhere in this project.
DEFAULT_RADIUS_M = THRESHOLDS[5]        # 400.0

#: LODES8 WAC vintage on disk. 2023 is OBSERVED on 2020 blocks; pre-2020 years
#: were area-retro-allocated onto them, which is bias and not noise
#: (CONTEXT.md 7.4b), so the present-day measure uses 2023 and nothing older.
DEFAULT_JOBS_VINTAGE = 2023


# --------------------------------------------------------- the sector groups
#
# LEHD LODES WAC ships employment by 2-digit NAICS as CNS01..CNS20, and they
# sum to C000 exactly. The split below is RETAIL-FACING vs DESK-FACING: does
# the job put a person on the sidewalk as a CUSTOMER of the block's storefronts
# at lunch and after work (desk-facing), or is the job ITSELF the storefront
# (retail-facing)?  The distinction is what separates "this corner is a
# shopping street" from "this corner is a business district that shops".

#: Jobs that ARE the street-level economy. A block with 3,000 of these is a
#: retail district: the employment is the shops, restaurants, cinemas, gyms,
#: salons and repair shops themselves.
#:   CNS07 Retail Trade                     (NAICS 44-45)
#:   CNS17 Arts, Entertainment & Recreation (NAICS 71) -- cinemas, gyms,
#:         theatres: ground-floor destination uses, not offices
#:   CNS18 Accommodation & Food Services    (NAICS 72) -- restaurants, bars,
#:         cafes, hotels
#:   CNS19 Other Services except Public Admin (NAICS 81) -- hair, nails, dry
#:         cleaning, laundry, shoe repair, auto repair. This is the NAICS bucket
#:         that holds most of Loci's own daily-needs categories, which is
#:         exactly why it is retail-facing and not "other".
RETAIL_FACING_SECTORS: tuple[str, ...] = ("CNS07", "CNS17", "CNS18", "CNS19")

#: Jobs that SIT AT A DESK and come downstairs to spend. A block with 30,000 of
#: these is a business district: its lunch trade, after-work bars and weekday
#: dry cleaners exist because of employment that is invisible from the street.
#:   CNS09 Information                            (NAICS 51)
#:   CNS10 Finance & Insurance                    (NAICS 52)
#:   CNS11 Real Estate & Rental & Leasing         (NAICS 53)
#:   CNS12 Professional, Scientific & Technical   (NAICS 54)
#:   CNS13 Management of Companies & Enterprises  (NAICS 55)
#:   CNS14 Administrative & Support & Waste Mgmt  (NAICS 56)
#:   CNS20 Public Administration                  (NAICS 92) -- city, state and
#:         federal offices are office buildings with a different landlord; the
#:         Civic Center is a business district, and excluding CNS20 would call
#:         it residential.
OFFICE_FACING_SECTORS: tuple[str, ...] = (
    "CNS09", "CNS10", "CNS11", "CNS12", "CNS13", "CNS14", "CNS20")

#: Everything else, as a REMAINDER rather than a third opinion: CNS01-06
#: (agriculture, mining, utilities, construction, manufacturing, wholesale),
#: CNS08 (transportation & warehousing), CNS15 (educational services), CNS16
#: (health care & social assistance). In New York CNS15+CNS16 dominate it. They
#: are large daytime-population generators that are neither storefront retail
#: nor desk work, and lumping them into either group would make the two
#: headline shares mean something else (a hospital block would read
#: "corporate"). `jobs_other_400m` is computed as C000 minus the two groups, so
#: the three ALWAYS sum to jobs_400m by construction -- never re-derive it.
OTHER_SECTORS: tuple[str, ...] = (
    "CNS01", "CNS02", "CNS03", "CNS04", "CNS05", "CNS06",
    "CNS08", "CNS15", "CNS16")

#: LODES WAC total. C000 = sum(CNS01..CNS20) by the feed's own construction.
JOBS_TOTAL_COLUMN = "C000"


# ------------------------------------------------------- the zoning route
#
# D82 (urban-planner review of the first build). The floor-area and payroll
# routes BOTH miss prewar outer-borough retail: a 1-2 storey taxpayer or a
# rowhouse with a store underneath folds its ground floor into ComArea and
# never reaches RetailArea (caveat 1), and a strip of thirty tiny owner-run
# shops carries fewer than 300 payroll jobs. Brighton Beach Avenue, Cortelyou
# Road, Fulton Street and Pitkin Avenue all read 0.000 retail_mixed on a first
# build, which is false on the ground.
#
# ZONING is the third, independent witness, and it is the one that cannot be
# under-reported by an assessor: a C1/C2 COMMERCIAL OVERLAY on a residential
# district is the instrument New York uses to permit exactly this -- local
# retail on the ground floor of a residential street -- and the City Planning
# Commission maps it ONTO THE CORRIDOR, lot by lot. Where an overlay is mapped,
# retail is legal, was intended, and (because overlays are mapped over existing
# strips far more often than ahead of them) is usually already there.
#
# WHAT COUNTS AS A COMMERCIAL LOT:
#   overlay1 / overlay2 starting 'C1-' or 'C2-'   the commercial overlay itself
#   zonedist1 starting C1, C2, C4, C5, C6, C8     a mapped commercial DISTRICT
# C3 (waterfront recreation) and C7 (amusement, Coney Island's Bowery) are
# deliberately NOT in the list: neither is a daily-needs retail street.
# Only zonedist1 is read. A split-zoned lot whose commercial half is zonedist2
# is missed, which makes the count a FLOOR -- the same direction of error as
# RetailArea, and preferable to counting a lot whose commercial sliver is 3% of
# its area.
COMMERCIAL_OVERLAY_PREFIXES: tuple[str, ...] = ("C1-", "C2-")
COMMERCIAL_DISTRICT_PREFIXES: tuple[str, ...] = ("C1", "C2", "C4", "C5", "C6", "C8")

#: Radius for the OVERLAY COUNT, in NETWORK metres on the same walk graph.
#: 100 m is "this block and the corners at either end of it" -- an address is
#: ON a commercial corridor, not merely within a five-minute walk of one. It is
#: a SECOND sweep of the same engine at a second radius, not a straight-line
#: buffer: `catchment_sums` takes the radius as an argument and the only cost
#: is one more bounded Dijkstra per batch over the same CSR.
#: CAVEAT THE DATABASE CANNOT ENFORCE: neither end's SNAP OFFSET is counted
#: (the lot's distance to its nearest graph node, and the address's), so at
#: 100 m the effective radius is 100 m plus two offsets -- typically 10-40 m on
#: a dense street grid. At 400 m that slack is 5% and ignorable; at 100 m it is
#: not, and the count should be read as "on or beside this block", never as a
#: metric buffer.
COMMERCIAL_OVERLAY_RADIUS_M = 100.0

#: How many commercially-zoned lots within that 100 m make the OR-route fire.
#: ONE, as the D82 review specified. An overlay is mapped in RUNS along a
#: corridor, never on an isolated lot, so a single C1-2 lot within a block is
#: the end of a corridor rather than an accident.
#:
#: THE COST, MEASURED AND STATED RATHER THAN HIDDEN. C1/C2 overlays are mapped
#: along very nearly every Brooklyn avenue, and Brooklyn's cross-street spacing
#: is ~80 m, so 46.8% of BK addresses have at least one commercially-zoned lot
#: within 100 m network metres (only 5 points of that are in the 1-2 lot band,
#: so this is real corridor geography and not snap slack). The OR-route at 1
#: therefore takes BK retail_mixed to 52%, against the ~20% the review's own
#: ground truth expects -- and the floor/share correction ALONE already
#: delivers 20.5%. Measured on the 2026-09-13 MN+BK build, share of addresses
#: labelled retail_mixed:
#:
#:     rule                                            BK      MN
#:     floor-area OR payroll (pre-D82: 1,000 / 0.40)   8.4%   37.7%
#:     ... payroll at 300 / 0.35 (D82, no zoning)     20.5%   52.6%
#:     ... + zoning OR-route at >= 1 lot   (current)  53.1%   89.2%
#:     ... + zoning OR-route at >= 10 lots            41.8%   78.6%
#:     ... + zoning OR-route at >= 20 lots            35.5%   67.5%
#:     ... + zoning OR-route at >= 30 lots            30.8%   59.0%
#:
#: All twelve corridors the review named flip at every one of those settings
#: (see the D82 report), so the threshold buys DISCRIMINATION, not coverage.
#: If the four-way label is wanted as a discriminator rather than as "is retail
#: legal near here", this is the one number to move -- and note that
#: `retail_index` carries the zoning witness CONTINUOUSLY either way, so
#: raising this constant costs the map nothing.
COMMERCIAL_OVERLAY_MIN_LOTS = 20

#: The overlay share at which `retail_index` reads 1.0 on the zoning route --
#: a quarter of every lot within the five-minute walk commercially zoned. For
#: scale: a two-sided avenue overlay through an otherwise residential grid runs
#: 0.10-0.20 at 400 m; Fifth Avenue Bay Ridge and Fulton Street sit near 0.25.
RETAIL_INDEX_OVERLAY_SHARE_FULL = 0.25


# ------------------------------------------------- institutional floor area
#
# D82. `office_area_400m` was the VA hospital problem: MapPLUTO books a
# hospital's, a university's and a diocese's floor area as OfficeArea, so
# Bay Ridge (the Brooklyn VA Medical Center) took 47 'corporate' addresses and
# East Flatbush-Rugby (Kings County / Kingsbrook) took 134. A hospital campus
# is a large weekday daytime population and it is NOT a business district: its
# staff do not leave the building for lunch the way a trading floor does, and
# nothing about its retail demand resembles Midtown's.
#
# So the CORPORATE route's office floor area EXCLUDES institutional lots:
#   BldgClass I  hospitals and health facilities
#   BldgClass M  churches, synagogues, religious buildings
#   BldgClass P  public assembly and cultural
#   BldgClass W  educational structures
#   LandUse  08  public facilities and institutions
# The RAW sum is kept beside it as `office_area_incl_inst_400m` -- it is one
# more weight column in the SAME Dijkstra and therefore free -- so the size of
# the exclusion is visible instead of asserted.
INSTITUTIONAL_BLDGCLASS_PREFIXES: tuple[str, ...] = ("I", "M", "P", "W")
INSTITUTIONAL_LANDUSE: tuple[str, ...] = ("08",)


# ------------------------------------------------------------- the thresholds
#
# ONE definition, used by the generated view SQL below and by the tests. Tuned
# by looking at the MN+BK decile distribution and at places whose answer is
# known before the model runs (see `loci address-character stats`):
# Midtown East and FiDi must be corporate; Bedford Ave and Flatbush Ave
# Downtown must be retail_mixed; the Sunset Park waterfront and East
# Williamsburg must be industrial; Park Slope side streets and Bay Ridge must
# be residential.

#: OFFICE floor-area share of the four named uses at which a catchment reads as
#: a business district. Deliberately far above the MN+BK median: a share this
#: high means office floor area rivals housing within a five-minute walk, which
#: outside a CBD does not happen.
CORPORATE_OFFICE_AREA_SHARE = 0.35
#: ...or the payroll route to the same conclusion. Both conditions are needed
#: because they fail in opposite directions: a converted-loft office district
#: (SoHo, DUMBO) carries the jobs without the PLUTO office split, and a
#: half-empty new tower carries the floor area without the jobs.
CORPORATE_JOBS_OFFICE_SHARE = 0.55
#: A FLOOR on BOTH corporate routes (D82), so a rowhouse block with 11 jobs --
#: six of them a title company -- cannot be "corporate" on a 55% share of
#: nearly nothing, AND a converted warehouse block with a big OfficeArea entry
#: and no employment cannot be one either. Before D82 the floor guarded only
#: the payroll route, which is how a hospital's OfficeArea alone could label a
#: catchment corporate.
CORPORATE_JOBS_FLOOR = 5_000

#: RETAIL floor-area share at which the catchment reads as a shopping street.
#: Low in absolute terms ON PURPOSE: retail is a GROUND FLOOR and competes with
#: every storey above it, so a fully retail-fronted avenue in a six-storey
#: neighbourhood tops out near 0.17. See caveat 1 -- PLUTO under-reports
#: RetailArea on exactly these blocks, so this is a floor on a floor.
RETAIL_AREA_SHARE = 0.12
#: ...or the payroll route: two in five jobs within the walk are the shops,
#: restaurants and services themselves.
#: LOWERED 0.40 -> 0.35 at D82. 0.40 was set from the MN+BK distribution with
#: no outer-borough ground truth in front of it, and it sat just above the
#: observed share on real Brooklyn shopping streets: Cortelyou Road runs 0.384,
#: Graham Avenue 0.384, Fulton Street 0.329, Church Avenue 0.302. A cut that
#: excludes Cortelyou Road is measuring Manhattan, not retail.
RETAIL_JOBS_SHARE = 0.35
#: ...but only where there is enough of it to be a commercial district. This
#: floor is on the retail-facing COUNT, not on total jobs.
#:
#: LOWERED 1,000 -> 300 at D82, and this is the review's central correction.
#: 1,000 retail-facing payroll jobs inside a five-minute walk is a MANHATTAN
#: number. It was defended above on the grounds that without a floor the
#: payroll route labelled 74% of Park Slope -- true, and the answer to that is
#: a floor, not THIS floor. At 1,000 the rule silently required the shops to be
#: BIG: 7th Avenue Park Slope (732 retail-facing jobs, share 0.448) failed,
#: Cortelyou Road (311) failed, Pitkin Avenue (93-329) failed, and every one of
#: them is an unmistakable shopping street. Outer-borough retail is built of
#: owner-operated shops with two or three people on the payroll -- the same
#: storefront count as a Manhattan block at a third of the payroll -- so a
#: COUNT floor calibrated on Manhattan is a systematic outer-borough erasure,
#: not a noise filter.
#: At 300 (roughly 30-100 small establishments within a five-minute walk) the
#: share-of-almost-nothing failure the floor exists to stop is still stopped:
#: 300 retail-facing jobs is well above what a purely residential catchment's
#: corner deli and nail salon produce.
#: The COST, stated rather than hidden: more of Park Slope's and Bay Ridge's
#: near-avenue side streets now clear the rule. That is the honest reading of a
#: 400 m catchment -- a side street one block off 7th Avenue IS within a
#: five-minute walk of 7th Avenue -- and it is the direction the map should err
#: in, since the measure is "what is around this address", not "is this address
#: itself a storefront".
RETAIL_JOBS_FLOOR = 300

#: FACTORY floor-area share at which the catchment reads as a working
#: industrial district (IBZ, waterfront manufacturing, Industry City).
#: Tuned DOWN from a first pass at 0.25, which sat above the 99th percentile of
#: MN+BK and found 1,476 addresses citywide -- it labelled nothing. At 0.15
#: (~p97) the ranking is exactly the one a planner would write down: Sunset Park
#: West 18.6% of addresses, Red Hook-Gowanus 12.9%, Greenpoint 11.7%, East
#: Williamsburg 10.6%, Bushwick (West) 5.8% -- while Park Slope is 0.0%,
#: Williamsburg 0.2% and Bay Ridge 0.0%. One square foot in seven of the four
#: named uses being factory space is a working district; one in four is a rate
#: no NYC catchment containing housing reaches.
INDUSTRIAL_FACTORY_AREA_SHARE = 0.15

#: Rule ORDER. corporate -> industrial -> retail_mixed -> residential, and the
#: order is load-bearing: an IBZ edge that has picked up a brewery taproom and a
#: coffee roaster can clear RETAIL_AREA_SHARE while still being East
#: Williamsburg, so `industrial` is tested BEFORE `retail_mixed`. `corporate` is
#: first because a CBD with a large retail podium (Herald Square) is a business
#: district with shops in it, not a shopping district with offices above.
LABEL_ORDER: tuple[str, ...] = ("corporate", "industrial", "retail_mixed", "residential")


# ------------------------------------------------------------- suppression
#
# D82. Two kinds of NTA row are arithmetic rather than geography, and both take
# top slots on any share ranking if they are left in.
#
#  * TINY DENOMINATORS. Calvert Vaux Park holds 9 residential lots and came out
#    100% retail_mixed. That is not a finding about Calvert Vaux Park.
#  * PARK, CEMETERY AND AIRPORT POLYGONS. The 2020 NTA layer covers the whole
#    city, so Green-Wood Cemetery, Holy Cross Cemetery, Prospect Park, Central
#    Park and Dyker Beach Park are NTAs. The residential lots inside them are
#    real addresses on the fringe, but their NTA aggregate is not a
#    neighbourhood anybody can act on.
#
# The 2020 NTA CODE carries the type in its last two digits: 01-59 is a
# residential neighbourhood, 61-69 "other" non-residential (Brooklyn Navy Yard,
# the United Nations, Fort Hamilton), 71-79 cemetery, 91-99 park or airport.
# The type rule below is >= 70 -- cemeteries, parks and airports, exactly what
# the review asked for. The 61-69 codes are left to the size rule, which in
# MN+BK catches all three of them (Navy Yard 47 addresses, Fort Hamilton 21,
# United Nations 20). NO NAME MATCHING: 'Park Slope', 'Borough Park', 'Sunset
# Park' and 'Ozone Park' are residential NTAs, and a name rule would suppress
# four real neighbourhoods to catch polygons the code already identifies.
#
# Suppression NULLs the per-address `character` and `character_intensity` (a
# label nobody should read is worse than no label) but leaves every stored
# measure and `retail_index` intact, so the continuous map shade still renders
# the fringe of Prospect Park honestly.
MIN_NTA_ADDRESSES = 50
#: Last-two-digits of the NTA code at or above which the polygon is a park,
#: cemetery or airport rather than a neighbourhood.
NON_NEIGHBOURHOOD_NTA_SUFFIX = 70


# ------------------------------------------------- the continuous measure
#
# D82. The review's strongest point about the MAP (not the rules): four
# categorical classes force a binary call on a continuum, and the call lands
# wrong exactly where the inputs are weakest. `retail_index` is the shade the
# map should carry, with corporate and industrial as sparse overlays on top of
# it rather than as competing fills.
#
# It is a MAX over the three independent witnesses, each normalised to its own
# rule threshold and capped at 1.0:
#
#   retail_area_share / RETAIL_AREA_SHARE                       (assessment)
#   jobs_retail_share / RETAIL_JOBS_SHARE, gated on the floor   (payroll)
#   commercial_overlay_share_400m / 0.25                        (zoning)
#
# MAX and not a mean, for the same reason the label takes any route as
# sufficient: each witness fails in a different place and each failure is a
# FALSE ZERO, never a false positive. Averaging three numbers of which two are
# known-zero by construction on a prewar retail street would reproduce the
# exact erasure this index exists to fix. The cost is that the index cannot
# fall below its most generous witness -- it is an upper envelope of retail
# evidence, and should be read as "how much evidence of retail character",
# never as "what fraction of this catchment is retail".
RETAIL_INDEX_TERMS = ("retail_area", "jobs_retail", "commercial_overlay")


# ------------------------------------------------------------ display copy
#
# D82. Rule: the CODE renames nothing -- `corporate` stays `corporate` in the
# label column, in LABEL_ORDER, in every share column and in every downstream
# join. What changes is what a HUMAN is shown, and it changes here, in one
# place, so a card and a map legend cannot drift apart.
CHARACTER_COPY: dict[str, str] = {
    "corporate":    "weekday-office catchment",
    "retail_mixed": "retail / mixed-use",
    "industrial":   "working industrial",
    "residential":  "residential",
}

#: The one-line caveat that must travel with the corporate copy, because the
#: label's plain-English reading ("nobody lives here, don't open a laundromat")
#: is the opposite of what the data says. From the D82 review: a weekday-office
#: catchment adds weekday demand ON TOP OF a resident base that is usually
#: LARGER than the borough median. The figures below are the 2026-09-13 MN+BK
#: build (5,682 vs 2,284 on the pre-D82 label set); `am_pm_corroboration()`
#: prints the current pair, and the copy should be re-read off it whenever the
#: rules move. What limits daily-needs retail in these catchments is
#: ground-floor supply, rent and loading, NOT absent customers.
CHARACTER_CAVEAT: dict[str, str] = {
    "corporate": (
        "A weekday-office catchment adds weekday demand on top of a resident "
        "base that is usually larger than the borough median: corporate-labelled "
        "addresses have a median 6,029 homes within 400 m against 1,759 for "
        "residential-labelled ones (5,682 vs 2,284 before D82). What limits "
        "daily-needs retail here is rent, loading and ground-floor supply -- "
        "not absent customers."),
    "retail_mixed": (
        "Retail character is an UPPER ENVELOPE of three witnesses (PLUTO "
        "RetailArea, LODES retail-facing payroll, C1/C2 commercial zoning); any "
        "one of them firing is enough, because each fails to zero in a different "
        "place."),
    "industrial": (
        "A working industrial catchment has weekday employment and very few "
        "residents; it is tested BEFORE retail, so an IBZ edge with a brewery "
        "taproom still reads industrial."),
    "residential": (
        "No route fired. This is the absence of evidence of the other three, "
        "not evidence of absence -- read `retail_index` beside it."),
}

#: A note the copy layer must not lose. `transit_am_pm_share_400m` (the D76
#: addendum) is NULL, not zero, for the ~61% of MN+BK addresses with no
#: profiled subway station within 400 m. A card that prints "AM share 0%" for a
#: Marine Park address is reporting the absence of a subway as a fact about
#: commuters. Render NULL as "no station within 400 m" and never as a number,
#: and never average it across a set without saying how many rows it rests on
#: (`n_am_pm` on analysis.nta_character).
TRANSIT_AM_PM_NOTE = (
    "transit_am_pm_share_400m is NULL outside the subway shed (~61% of MN+BK "
    "addresses have no profiled station within 400 m). NULL means 'no station', "
    "not 'no morning commuters' -- never render it as 0.")

#: Degrees of padding on the SCOPE bounding box when selecting weight points.
#: A lot or block more than this far outside the box holding the scored
#: addresses cannot be within 400 m NETWORK metres of any of them, because
#: network distance along a polyline is never shorter than the great-circle
#: distance it spans. 0.02 deg is ~1.7 km of longitude at 40.7 N, which leaves
#: four times the radius of slack for the snap-to-node offsets at both ends.
#: The filter is not merely an optimisation: ny_wac is the WHOLE STATE, and an
#: Albany block left in the frame would snap to whichever NYC-graph node is
#: nearest (`nearest_nodes` has no distance limit) and dump upstate employment
#: onto the northern edge of the Bronx.
SCOPE_PAD_DEG = BBOX_PAD_DEG            # 0.02

#: The weight columns of the single sweep, in the order `catchment_sums`
#: returns them. Adding a lot-derived measure is one more entry here.
LOT_WEIGHTS: tuple[str, ...] = (
    "retail_area", "office_area", "office_area_incl_inst", "res_area",
    "factory_area", "bldg_area", "comm_lots", "lots")
JOB_WEIGHTS: tuple[str, ...] = ("jobs_retail", "jobs_office", "jobs_total")
SWEEP_KEYS: tuple[str, ...] = (*LOT_WEIGHTS, *JOB_WEIGHTS)

#: The weights of the SECOND sweep, at COMMERCIAL_OVERLAY_RADIUS_M. One column,
#: because the 100 m radius answers exactly one question ("is this address on a
#: commercially-zoned block"). Same CSR, same query nodes, same engine.
NEAR_WEIGHTS: tuple[str, ...] = ("comm_lots",)

#: The ONLY columns write_character may name in a SET clause.
CHARACTER_COLUMNS = [
    "retail_area_400m",
    "office_area_400m",
    "office_area_incl_inst_400m",
    "res_area_400m",
    "factory_area_400m",
    "bldg_area_400m",
    "jobs_retail_400m",
    "jobs_office_400m",
    "jobs_other_400m",
    "commercial_overlay_100m",
    "commercial_lots_400m",
    "lots_400m",
    "character_radius_m",
    "character_near_radius_m",
    "character_pluto_version",
    "character_jobs_vintage",
    "character_run_at",
]


# ----------------------------------------------------------------- the reads

def _commercial_lot_sql(alias: str = "") -> str:
    """The zoning predicate, as SQL over MapPLUTO's raw VARCHAR columns.

    Uppercased and trimmed before matching because the export is not
    case-consistent across versions. A blank overlay is the empty string in
    some vintages and NULL in others; both fail every LIKE, which is correct.
    """
    p = f"{alias}." if alias else ""
    def up(col: str) -> str:
        return f"UPPER(TRIM(COALESCE({p}{col}, '')))"
    tests = []
    for ov in ("overlay1", "overlay2"):
        tests += [f"{up(ov)} LIKE '{pre}%'" for pre in COMMERCIAL_OVERLAY_PREFIXES]
    tests += [f"{up('zonedist1')} LIKE '{pre}%'"
              for pre in COMMERCIAL_DISTRICT_PREFIXES]
    return "(" + " OR ".join(tests) + ")"


def _institutional_lot_sql(alias: str = "") -> str:
    """The institutional predicate (D82): hospitals, religious buildings,
    public assembly, schools, and DCP LandUse 08 public facilities. These lots'
    OfficeArea is excluded from the corporate route -- a hospital campus is not
    a central business district."""
    p = f"{alias}." if alias else ""
    cls = f"UPPER(TRIM(COALESCE({p}bldgclass, '')))"
    lu = f"LPAD(TRIM(COALESCE({p}landuse, '')), 2, '0')"
    tests = [f"{cls} LIKE '{pre}%'" for pre in INSTITUTIONAL_BLDGCLASS_PREFIXES]
    tests += [f"{lu} = '{code}'" for code in INSTITUTIONAL_LANDUSE]
    return "(" + " OR ".join(tests) + ")"


def load_lot_points(con, bbox: tuple[float, float, float, float],
                    pluto_csv: pathlib.Path | str = PLUTO_CSV) -> pd.DataFrame:
    """One row per MapPLUTO tax lot inside `bbox` with usable coordinates:
    (bbl, lon, lat, retail_area, office_area, office_area_incl_inst, res_area,
    factory_area, bldg_area, is_commercial, is_institutional, unitsres,
    version). SQUARE FEET.

    `office_area` EXCLUDES institutional lots (D82) and
    `office_area_incl_inst` is the raw column, so the size of the exclusion
    stays visible. `is_commercial` is the C1/C2 overlay + C1/C2/C4/C5/C6/C8
    district test; it is a 0/1 weight, so summing it over a catchment counts
    LOTS, not floor area.

    EVERY lot, not only UnitsRes > 0 -- see the module docstring on why reusing
    `homes_400m`'s set would zero out the Financial District. `unitsres` rides
    along so a caller can reproduce that set exactly and prove the engine
    agrees with `homes_400m`.

    Read straight off the CSV with DuckDB's read_csv, ALL_VARCHAR then
    TRY_CAST, exactly as grid/pluto.py reads it: the raw export mixes blanks and
    numbers in one column and a strict inferred type errors. Both sides of the
    geography are EPSG:4326 degrees -- PLUTO's own latitude/longitude columns
    and the walk graph's node coordinates -- so there is NO reprojection here
    and none is needed; the metric work happens on the graph's edge lengths,
    which are already metres.
    """
    pluto_csv = pathlib.Path(pluto_csv)
    if not pluto_csv.exists():
        raise FileNotFoundError(
            f"MapPLUTO CSV not found at {pluto_csv}. Writing zero floor area onto "
            f"every address would read as 'New York has no buildings'.")
    minlon, minlat, maxlon, maxlat = bbox
    df = con.execute(
        f"""
        SELECT BBL                                             AS bbl,
               TRY_CAST(longitude AS DOUBLE)                   AS lon,
               TRY_CAST(latitude  AS DOUBLE)                   AS lat,
               COALESCE(TRY_CAST(retailarea AS DOUBLE), 0)     AS retail_area,
               CASE WHEN {_institutional_lot_sql()} THEN 0
                    ELSE COALESCE(TRY_CAST(officearea AS DOUBLE), 0)
               END                                             AS office_area,
               COALESCE(TRY_CAST(officearea AS DOUBLE), 0)     AS office_area_incl_inst,
               COALESCE(TRY_CAST(resarea    AS DOUBLE), 0)     AS res_area,
               COALESCE(TRY_CAST(factryarea AS DOUBLE), 0)     AS factory_area,
               COALESCE(TRY_CAST(bldgarea   AS DOUBLE), 0)     AS bldg_area,
               CASE WHEN {_commercial_lot_sql()} THEN 1 ELSE 0 END AS is_commercial,
               CASE WHEN {_institutional_lot_sql()} THEN 1 ELSE 0 END AS is_institutional,
               COALESCE(TRY_CAST(unitsres   AS DOUBLE), 0)     AS unitsres,
               version                                         AS version
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE TRY_CAST(longitude AS DOUBLE) BETWEEN ? AND ?
          AND TRY_CAST(latitude  AS DOUBLE) BETWEEN ? AND ?
          AND TRY_CAST(latitude  AS DOUBLE) <> 0
          AND TRY_CAST(longitude AS DOUBLE) <> 0
        """,
        [str(pluto_csv), minlon, maxlon, minlat, maxlat],
    ).fetchdf()
    if df.empty:
        raise RuntimeError(
            f"MapPLUTO: no lots with coordinates inside {bbox}. That is a broken "
            f"bbox or a broken file, never a real city; refusing to write zeros.")
    return df


def _sector_sum_sql(cols: tuple[str, ...], alias: str) -> str:
    inner = " + ".join(f"COALESCE(TRY_CAST(w.{c} AS DOUBLE), 0)" for c in cols)
    return f"({inner}) AS {alias}"


def load_job_sector_points(con, bbox: tuple[float, float, float, float],
                           vintage: int = DEFAULT_JOBS_VINTAGE,
                           lodes_dir: pathlib.Path = LODES_DIR) -> pd.DataFrame:
    """One row per 2020 census block inside `bbox` with at least one job:
    (w_geocode, lon, lat, jobs_total, jobs_retail, jobs_office).

    The same file, the same join key and the same block centroid as
    `model/address_access.load_job_points` -- `w_geocode = tabblk2020` against
    the LODES8 crosswalk, point = the crosswalk's published `blklatdd`/
    `blklondd`. LODES8 puts EVERY vintage on 2020 blocks, so there is no
    2010/2020 tract-or-block crosswalk step here and none is correct: the
    pre-2020 files got onto 2020 blocks by area-proportional ALLOCATION, and
    that is bias, not noise (CONTEXT.md 7.4b).

    No reprojection: both the crosswalk centroids and the graph nodes are
    EPSG:4326 degrees.

    `jobs_other` is deliberately NOT returned. It is computed once, at the end
    of the sweep, as total - retail - office, so the three columns sum to
    jobs_400m by construction rather than by luck.
    """
    wac = pathlib.Path(lodes_dir) / f"ny_wac_S000_JT00_{vintage}.csv.gz"
    if not wac.exists():
        raise FileNotFoundError(
            f"{wac} is absent. LODES WAC {vintage} has not been downloaded; "
            f"writing zero jobs on every address would read as 'nobody works in "
            f"New York'.")
    if not pathlib.Path(XWALK).exists():
        raise FileNotFoundError(f"{XWALK} is absent (the LODES8 block crosswalk).")
    minlon, minlat, maxlon, maxlat = bbox
    df = con.execute(f"""
        SELECT w.w_geocode                                       AS w_geocode,
               TRY_CAST(x.blklondd AS DOUBLE)                    AS lon,
               TRY_CAST(x.blklatdd AS DOUBLE)                    AS lat,
               COALESCE(TRY_CAST(w.{JOBS_TOTAL_COLUMN} AS DOUBLE), 0) AS jobs_total,
               {_sector_sum_sql(RETAIL_FACING_SECTORS, 'jobs_retail')},
               {_sector_sum_sql(OFFICE_FACING_SECTORS, 'jobs_office')}
        FROM read_csv('{wac}', ALL_VARCHAR=TRUE) w
        JOIN read_csv('{XWALK}', ALL_VARCHAR=TRUE) x ON w.w_geocode = x.tabblk2020
        WHERE TRY_CAST(x.blklondd AS DOUBLE) BETWEEN {minlon} AND {maxlon}
          AND TRY_CAST(x.blklatdd AS DOUBLE) BETWEEN {minlat} AND {maxlat}
          AND TRY_CAST(w.{JOBS_TOTAL_COLUMN} AS DOUBLE) > 0
    """).fetchdf()
    if df.empty:
        raise RuntimeError(
            f"LODES WAC {vintage}: no blocks with jobs inside {bbox}. That is a "
            f"broken join or a wrong bbox, never a real city; refusing to write "
            f"zeros.")
    bad = df[(df["jobs_retail"] + df["jobs_office"]) > df["jobs_total"] + 1e-6]
    if len(bad):
        raise RuntimeError(
            f"LODES WAC {vintage}: {len(bad)} blocks where the retail+office sector "
            f"groups exceed C000. C000 is the feed's own sum of CNS01..CNS20, so "
            f"this means a mis-named column, not a real city.")
    return df


def scope_bbox(addr: pd.DataFrame, pad: float = SCOPE_PAD_DEG
               ) -> tuple[float, float, float, float]:
    """(minlon, minlat, maxlon, maxlat) of the SCORED addresses, padded."""
    return (float(addr["lon"].min()) - pad, float(addr["lat"].min()) - pad,
            float(addr["lon"].max()) + pad, float(addr["lat"].max()) + pad)


# ---------------------------------------------------------------- the build

def compute_character(
    con,
    boroughs: list[str] | None,
    radius_m: float = DEFAULT_RADIUS_M,
    near_radius_m: float = COMMERCIAL_OVERLAY_RADIUS_M,
    graph_path: pathlib.Path = GRAPH_PATH,
    jobs_vintage: int = DEFAULT_JOBS_VINTAGE,
    pluto_csv: pathlib.Path | str = PLUTO_CSV,
    batch: int = BATCH,
) -> tuple[pd.DataFrame, dict]:
    """(frame of address_id/borough + CHARACTER_COLUMNS, report). READ-ONLY on
    the warehouse -- it SELECTs analysis.address and writes nothing."""
    addr = load_address_points(con, boroughs)
    if addr.empty:
        raise RuntimeError(
            f"no addresses in analysis.address for boroughs={boroughs}. Run "
            f"`loci address-gaps` first; an empty frame would RESET every column "
            f"to NULL and write nothing back.")

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)
    n_nodes = A.shape[0]

    bbox = scope_bbox(addr)
    lots = load_lot_points(con, bbox, pluto_csv=pluto_csv)
    jobs = load_job_sector_points(con, bbox, vintage=jobs_vintage)

    # --- snap every point onto the ALREADY-PRUNED graph -------------------
    l_nodes = ox.distance.nearest_nodes(
        Gp, X=lots["lon"].tolist(), Y=lots["lat"].tolist())
    l_nidx = np.array([idx[n] for n in np.atleast_1d(l_nodes)], dtype=np.int64)
    j_nodes = ox.distance.nearest_nodes(
        Gp, X=jobs["lon"].tolist(), Y=jobs["lat"].tolist())
    j_nidx = np.array([idx[n] for n in np.atleast_1d(j_nodes)], dtype=np.int64)

    # Points are ACCUMULATED, never deduplicated: two lots snapped to one node
    # are two lots' worth of floor area, and two job blocks on one node are two
    # blocks' worth of jobs. (node_weights uses np.add.at.)
    nodes_of = {k: l_nidx for k in LOT_WEIGHTS}
    weights = {
        "retail_area": lots["retail_area"].to_numpy(dtype=np.float64),
        "office_area": lots["office_area"].to_numpy(dtype=np.float64),
        "office_area_incl_inst": lots["office_area_incl_inst"].to_numpy(dtype=np.float64),
        "res_area": lots["res_area"].to_numpy(dtype=np.float64),
        "factory_area": lots["factory_area"].to_numpy(dtype=np.float64),
        "bldg_area": lots["bldg_area"].to_numpy(dtype=np.float64),
        # 0/1 lot weights: summed over a catchment these COUNT LOTS. `lots` is
        # the denominator of commercial_overlay_share_400m and is deliberately
        # every lot in the bbox, so the share is "of the lots around me, how
        # many may legally hold a shop" and not a share of anything smaller.
        "comm_lots": lots["is_commercial"].to_numpy(dtype=np.float64),
        "lots": np.ones(len(lots), dtype=np.float64),
    }
    for k in JOB_WEIGHTS:
        nodes_of[k] = j_nidx
    weights["jobs_retail"] = jobs["jobs_retail"].to_numpy(dtype=np.float64)
    weights["jobs_office"] = jobs["jobs_office"].to_numpy(dtype=np.float64)
    weights["jobs_total"] = jobs["jobs_total"].to_numpy(dtype=np.float64)

    keys = list(SWEEP_KEYS)
    W = node_weights(idx, nodes_of, {k: weights[k] for k in keys}, n_nodes)

    # --- the sweep --------------------------------------------------------
    a_nodes = ox.distance.nearest_nodes(
        Gp, X=addr["lon"].tolist(), Y=addr["lat"].tolist())
    a_nidx = np.array([idx[n] for n in np.atleast_1d(a_nodes)], dtype=np.int64)
    # Addresses collapse onto far fewer graph nodes -- a 400 m catchment cannot
    # tell two doorways on one block apart -- so the sweep runs once per NODE.
    uniq, inv = np.unique(a_nidx, return_inverse=True)
    acc = catchment_sums(A, uniq, W, radius_m=radius_m, batch=batch)[inv]

    # SECOND sweep, same engine, same query nodes, at the 100 m "on this block"
    # radius (D82). Only the commercial-lot indicator is carried, so the weight
    # matrix is one column wide and the Dijkstra is bounded at a quarter of the
    # radius -- it costs a small fraction of the 400 m pass.
    Wn = node_weights(idx, {"comm_lots": l_nidx},
                      {"comm_lots": weights["comm_lots"]}, n_nodes)
    near = catchment_sums(A, uniq, Wn, radius_m=near_radius_m, batch=batch)[inv]

    col = {k: acc[:, keys.index(k)] for k in keys}
    # LODES values are integers and the catchment is a 0/1 matrix product over
    # them, so these sums are exact in float64 and rint changes nothing. The
    # remainder is computed from the SAME total, which is what makes the three
    # columns sum to jobs_400m rather than approximately sum to it.
    j_tot = np.rint(col["jobs_total"]).astype("int64")
    j_ret = np.rint(col["jobs_retail"]).astype("int64")
    j_off = np.rint(col["jobs_office"]).astype("int64")
    j_oth = j_tot - j_ret - j_off
    if (j_oth < 0).any():
        raise RuntimeError(
            f"{int((j_oth < 0).sum())} addresses got a NEGATIVE jobs_other_400m. "
            f"C000 is the feed's own sum of CNS01..CNS20, so a remainder below "
            f"zero means the sector groups overlap or a column is mis-named.")

    version = str(lots["version"].dropna().iloc[0]) if lots["version"].notna().any() else None
    run_at = dt.datetime.now()
    out = pd.DataFrame({
        "address_id": addr["address_id"].to_numpy(),
        "borough": addr["borough"].to_numpy(),
        "retail_area_400m": col["retail_area"],
        "office_area_400m": col["office_area"],
        "office_area_incl_inst_400m": col["office_area_incl_inst"],
        "res_area_400m": col["res_area"],
        "factory_area_400m": col["factory_area"],
        "bldg_area_400m": col["bldg_area"],
        "jobs_retail_400m": j_ret,
        "jobs_office_400m": j_off,
        "jobs_other_400m": j_oth,
        # Lot COUNTS, so integer. rint before the cast because these are exact
        # sums of a 0/1 matrix product in float64 and a bare astype would
        # truncate a 3.0000000000000004 to 3 by luck rather than by rule.
        "commercial_overlay_100m": np.rint(near[:, 0]).astype("int64"),
        "commercial_lots_400m": np.rint(col["comm_lots"]).astype("int64"),
        "lots_400m": np.rint(col["lots"]).astype("int64"),
        "character_radius_m": float(radius_m),
        "character_near_radius_m": float(near_radius_m),
        "character_pluto_version": version,
        "character_jobs_vintage": int(jobs_vintage),
        "character_run_at": run_at,
    })

    report = {
        "boroughs": list(boroughs) if boroughs else "ALL",
        "radius_m": float(radius_m),
        "graph_version": graph_version(graph_path),
        "scope_bbox": bbox,
        "addresses": len(out),
        "query_nodes": int(uniq.size),
        "lots": len(lots),
        "lots_residential": int((lots["unitsres"] > 0).sum()),
        "lots_commercial_zoned": int(lots["is_commercial"].sum()),
        "lots_institutional": int(lots["is_institutional"].sum()),
        "lot_bldg_area_total": float(lots["bldg_area"].sum()),
        "lot_office_area_total": float(lots["office_area"].sum()),
        "lot_office_area_incl_inst_total": float(lots["office_area_incl_inst"].sum()),
        "lot_retail_area_total": float(lots["retail_area"].sum()),
        "near_radius_m": float(near_radius_m),
        "pluto_version": version,
        "job_blocks": len(jobs),
        "job_total_in_bbox": float(jobs["jobs_total"].sum()),
        "job_retail_in_bbox": float(jobs["jobs_retail"].sum()),
        "job_office_in_bbox": float(jobs["jobs_office"].sum()),
        "jobs_vintage": int(jobs_vintage),
        "retail_sectors": list(RETAIL_FACING_SECTORS),
        "office_sectors": list(OFFICE_FACING_SECTORS),
        "other_sectors": list(OTHER_SECTORS),
        "run_at": run_at.isoformat(timespec="seconds"),
        "addresses_with_office_area": int((out["office_area_400m"] > 0).sum()),
        "addresses_with_retail_area": int((out["retail_area_400m"] > 0).sum()),
        "addresses_with_factory_area": int((out["factory_area_400m"] > 0).sum()),
        "addresses_on_commercial_block": int(
            (out["commercial_overlay_100m"] >= COMMERCIAL_OVERLAY_MIN_LOTS).sum()),
        "office_area_excluded_pct": (
            1.0 - float(lots["office_area"].sum())
            / float(lots["office_area_incl_inst"].sum())
            if float(lots["office_area_incl_inst"].sum()) > 0 else None),
    }
    return out, report


# --------------------------------------------------------------- the write

def _guard(cols: list[str]) -> None:
    """Refuse to write if the SET list touches a column another module owns.
    Belt and braces; tests/test_address_character.py is the real guard."""
    forbidden: set[str] = set()
    try:
        from loci.model.address_access import ACCESS_COLUMNS
        from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
        from loci.model.address_gaps import (
            ADDRESS_CATEGORY_SCREEN_COLUMNS,
            ADDRESS_COLUMNS,
        )
        from loci.model.dev_pipeline import PIPELINE_COLUMNS
        from loci.model.storefronts import AGE_FIT_COLUMNS, STOREFRONT_COLUMNS
        from loci.model.supply_ratio import (
            ADDRESS_RATIO_COLUMNS,
            CATEGORY_RATIO_COLUMNS,
        )
        forbidden |= set(ADDRESS_COLUMNS) | set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
        forbidden |= set(PIPELINE_COLUMNS) | set(STOREFRONT_COLUMNS)
        forbidden |= set(AGE_FIT_COLUMNS) | set(DEMAND_ANNOTATION_COLUMNS)
        forbidden |= set(ADDRESS_RATIO_COLUMNS) | set(CATEGORY_RATIO_COLUMNS)
        forbidden |= set(ACCESS_COLUMNS)
    except ImportError:                                     # pragma: no cover
        pass
    overlap = sorted(set(cols) & forbidden)
    if overlap:
        raise RuntimeError(
            f"address-character would clobber analysis.address columns: {overlap}")


def write_character(con, df: pd.DataFrame, boroughs: list[str] | None) -> int:
    """UPDATE-only on analysis.address. RESET then UPDATE, in scope."""
    _guard(CHARACTER_COLUMNS)
    absent = [c for c in CHARACTER_COLUMNS if c not in df.columns]
    if absent:
        raise RuntimeError(
            f"frame is missing {absent}; every column in CHARACTER_COLUMNS is reset "
            f"to NULL below, so a partial frame would blank them permanently.")
    reset = ", ".join(f"{c} = NULL" for c in CHARACTER_COLUMNS)
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        con.execute(f"UPDATE analysis.address SET {reset} WHERE borough IN ({holes})",
                    list(boroughs))
    else:
        con.execute(f"UPDATE analysis.address SET {reset}")
    if df.empty:
        return 0
    con.register("_chr", df[["address_id", "borough", *CHARACTER_COLUMNS]])
    try:
        sets = ", ".join(f"{c} = _chr.{c}" for c in CHARACTER_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address AS a SET {sets}
            FROM _chr
            WHERE a.address_id = _chr.address_id AND a.borough = _chr.borough
        """)
    finally:
        con.unregister("_chr")
    return len(df)


def build_character(
    con,
    boroughs: list[str] | None,
    radius_m: float = DEFAULT_RADIUS_M,
    near_radius_m: float = COMMERCIAL_OVERLAY_RADIUS_M,
    graph_path: pathlib.Path = GRAPH_PATH,
    jobs_vintage: int = DEFAULT_JOBS_VINTAGE,
    pluto_csv: pathlib.Path | str = PLUTO_CSV,
    dry_run: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """compute + write, then (re)create the two views so a tuned threshold
    takes effect without a schema re-init."""
    df, report = compute_character(
        con, boroughs, radius_m=radius_m, near_radius_m=near_radius_m,
        graph_path=graph_path, jobs_vintage=jobs_vintage, pluto_csv=pluto_csv)
    if not dry_run:
        report["_written"] = write_character(con, df, boroughs)
        create_views(con)
    return df, report


# ----------------------------------------------------------------- the views
#
# The label lives in SQL, computed on demand from the stored columns, because
# it is pure arithmetic on them: materialising it would create a second thing
# to keep in sync every time a threshold moves, and the whole point of
# `character_intensity` is that a reader can see how close to the line an
# address sits. If the view ever becomes too slow for an export, materialise it
# with CREATE TABLE AS from the SAME generator -- do not hand-copy the CASE.

def _share(num: str, den: str) -> str:
    return f"CASE WHEN {den} > 0 THEN CAST({num} AS DOUBLE) / {den} END"


def _corporate_rule(prefix: str = "") -> str:
    """D82: the jobs floor now guards BOTH routes. Before, a hospital's
    OfficeArea alone could label a catchment corporate with no employment test
    at all -- and `office_area_400m` itself no longer contains institutional
    floor area, so the two corrections are independent."""
    return (f"COALESCE({prefix}jobs_three_400m, 0) >= {CORPORATE_JOBS_FLOOR} "
            f"AND (COALESCE({prefix}office_area_share, 0) >= {CORPORATE_OFFICE_AREA_SHARE} "
            f"OR COALESCE({prefix}jobs_office_share, 0) >= {CORPORATE_JOBS_OFFICE_SHARE})")


def _industrial_rule(prefix: str = "") -> str:
    return f"COALESCE({prefix}factory_area_share, 0) >= {INDUSTRIAL_FACTORY_AREA_SHARE}"


def _retail_rule(prefix: str = "") -> str:
    """Three routes, any one sufficient (D82 added the third). Each witness
    fails to ZERO in a different place -- assessment on prewar taxpayers,
    payroll on owner-operated strips, zoning on new-build retail condos in a
    residential district -- so OR is the only combination that does not
    inherit every one of those blind spots."""
    return (f"COALESCE({prefix}retail_area_share, 0) >= {RETAIL_AREA_SHARE} "
            f"OR (COALESCE({prefix}jobs_retail_share, 0) >= {RETAIL_JOBS_SHARE} "
            f"AND COALESCE({prefix}jobs_retail_400m, 0) >= {RETAIL_JOBS_FLOOR}) "
            f"OR COALESCE({prefix}commercial_overlay_100m, 0) "
            f">= {COMMERCIAL_OVERLAY_MIN_LOTS}")


def _retail_index_sql(prefix: str = "") -> str:
    """`retail_index` in [0, 1]: the MAX of three witnesses, each normalised to
    its own rule threshold and capped. See RETAIL_INDEX_TERMS on why MAX.

    NULL only where the build has not run -- the callers wrap this in the same
    `character_run_at IS NULL` test the label uses. A catchment with no built
    area and no jobs reads 0.0, which is an observation (D75: zero is a
    measurement, NULL is not a thing here)."""
    return (
        f"GREATEST("
        f"LEAST(1.0, COALESCE({prefix}retail_area_share, 0) / {RETAIL_AREA_SHARE}), "
        f"CASE WHEN COALESCE({prefix}jobs_retail_400m, 0) >= {RETAIL_JOBS_FLOOR} "
        f"THEN LEAST(1.0, COALESCE({prefix}jobs_retail_share, 0) / {RETAIL_JOBS_SHARE}) "
        f"ELSE 0 END, "
        f"LEAST(1.0, COALESCE({prefix}commercial_overlay_share_400m, 0) "
        f"/ {RETAIL_INDEX_OVERLAY_SHARE_FULL}))")


def _suppressed_sql(prefix: str = "") -> str:
    """TRUE where the NTA is too small to quote or is a park, cemetery or
    airport polygon rather than a neighbourhood (D82). See MIN_NTA_ADDRESSES.
    `nta_addresses` is supplied by the view's own CTE, not stored."""
    return (f"(COALESCE({prefix}nta_addresses, 0) < {MIN_NTA_ADDRESSES} "
            f"OR TRY_CAST(substr({prefix}nta_code, 5, 2) AS INTEGER) "
            f">= {NON_NEIGHBOURHOOD_NTA_SUFFIX})")


def address_character_view_sql() -> str:
    """analysis.address_character -- shares, label, intensity, retail_index.

    `character` is NULL in exactly two cases, and both are refusals to state
    something the data cannot support:
      * `character_run_at IS NULL` -- the build has not run for that borough;
      * `suppressed` -- the address sits in an NTA with fewer than
        MIN_NTA_ADDRESSES addresses, or in a park / cemetery / airport polygon
        (D82). Every stored measure and `retail_index` survive suppression;
        only the four-way label and its intensity are withheld.
    A fabricated 'residential' in either case would not be honest.
    """
    # `character_intensity` answers "how far past the line", 0..1, so a map can
    # shade instead of flood-filling four colours. For a triggered label it is
    # the excess over the threshold as a fraction of the distance from the
    # threshold to 1.0, taking the FURTHEST-past criterion when two fire. For
    # `residential` it is inverted: 1.0 is a catchment nowhere near any
    # threshold, 0.0 is one sitting exactly on the tightest of them, so the
    # colour ramp runs continuously across the label boundary instead of
    # jumping.
    corp_int = (f"GREATEST("
                f"(COALESCE(office_area_share, 0) - {CORPORATE_OFFICE_AREA_SHARE}) "
                f"/ {round(1 - CORPORATE_OFFICE_AREA_SHARE, 10)}, "
                f"CASE WHEN COALESCE(jobs_three_400m, 0) >= {CORPORATE_JOBS_FLOOR} "
                f"THEN (COALESCE(jobs_office_share, 0) - {CORPORATE_JOBS_OFFICE_SHARE}) "
                f"/ {round(1 - CORPORATE_JOBS_OFFICE_SHARE, 10)} ELSE -1 END)")
    ind_int = (f"(COALESCE(factory_area_share, 0) - {INDUSTRIAL_FACTORY_AREA_SHARE}) "
               f"/ {round(1 - INDUSTRIAL_FACTORY_AREA_SHARE, 10)}")
    # The zoning route is a COUNT with a threshold of one, so "how far past the
    # line" has no meaning on it; the continuous quantity that goes with it is
    # the 400 m overlay SHARE, which is what the third term reads.
    ret_int = (f"GREATEST("
               f"(COALESCE(retail_area_share, 0) - {RETAIL_AREA_SHARE}) "
               f"/ {round(1 - RETAIL_AREA_SHARE, 10)}, "
               f"CASE WHEN COALESCE(jobs_retail_400m, 0) >= {RETAIL_JOBS_FLOOR} "
               f"THEN (COALESCE(jobs_retail_share, 0) - {RETAIL_JOBS_SHARE}) "
               f"/ {round(1 - RETAIL_JOBS_SHARE, 10)} ELSE -1 END, "
               f"CASE WHEN COALESCE(commercial_overlay_100m, 0) "
               f">= {COMMERCIAL_OVERLAY_MIN_LOTS} "
               f"THEN LEAST(1.0, COALESCE(commercial_overlay_share_400m, 0) "
               f"/ {RETAIL_INDEX_OVERLAY_SHARE_FULL}) ELSE -1 END)")
    res_int = (f"1.0 - GREATEST("
               f"CASE WHEN COALESCE(jobs_three_400m, 0) >= {CORPORATE_JOBS_FLOOR} "
               f"THEN COALESCE(office_area_share, 0) / {CORPORATE_OFFICE_AREA_SHARE} "
               f"ELSE 0 END, "
               f"COALESCE(factory_area_share, 0) / {INDUSTRIAL_FACTORY_AREA_SHARE}, "
               f"COALESCE(retail_area_share, 0) / {RETAIL_AREA_SHARE}, "
               f"CASE WHEN COALESCE(jobs_retail_400m, 0) >= {RETAIL_JOBS_FLOOR} "
               f"THEN COALESCE(jobs_retail_share, 0) / {RETAIL_JOBS_SHARE} "
               f"ELSE 0 END, "
               f"COALESCE(commercial_overlay_share_400m, 0) "
               f"/ {RETAIL_INDEX_OVERLAY_SHARE_FULL}, "
               f"CASE WHEN COALESCE(jobs_three_400m, 0) >= {CORPORATE_JOBS_FLOOR} "
               f"THEN COALESCE(jobs_office_share, 0) / {CORPORATE_JOBS_OFFICE_SHARE} "
               f"ELSE 0 END)")
    return f"""
CREATE OR REPLACE VIEW analysis.address_character AS
WITH nta_size AS (
    -- The suppression denominator (D82). Counted over BUILT addresses only,
    -- so a borough that has not been run does not suppress itself to nothing.
    -- D84: LOT frame only. "Fewer than 50 addresses" is a statement about
    -- residential addresses; counting street midpoints would un-suppress small
    -- NTAs on the strength of points where nobody lives.
    SELECT borough, nta_code, count(*) AS nta_addresses
    FROM analysis.address
    WHERE character_run_at IS NOT NULL AND COALESCE(frame, 'lot') = 'lot'
    GROUP BY borough, nta_code
), base AS (
    SELECT a.address_id, a.borough, a.nta_code, a.neighborhood, a.lon, a.lat,
           -- D84: the sampling frame travels onto the view so the NTA roll-up
           -- below can stay a statement about residential addresses while a
           -- street midpoint still carries its own character reading.
           COALESCE(a.frame, 'lot') AS frame,
           a.homes_400m, a.jobs_400m, a.transit_entries_400m,
           a.transit_am_pm_share_400m,
           a.retail_area_400m, a.office_area_400m, a.office_area_incl_inst_400m,
           a.res_area_400m, a.factory_area_400m, a.bldg_area_400m,
           a.jobs_retail_400m, a.jobs_office_400m, a.jobs_other_400m,
           a.commercial_overlay_100m, a.commercial_lots_400m, a.lots_400m,
           a.character_radius_m, a.character_near_radius_m,
           a.character_pluto_version, a.character_jobs_vintage,
           a.character_run_at,
           COALESCE(s.nta_addresses, 0) AS nta_addresses,
           -- The share DENOMINATOR is the four NAMED uses, not BldgArea:
           -- garage, storage, "other" and unclassified floor area are ~18% of
           -- BldgArea citywide and dividing by it would make every share read
           -- systematically low for no gain in meaning. bldg_area_400m stays on
           -- the view so a reader can see how much was left out.
           (COALESCE(a.retail_area_400m, 0) + COALESCE(a.office_area_400m, 0)
            + COALESCE(a.res_area_400m, 0) + COALESCE(a.factory_area_400m, 0))
               AS area_four_400m,
           (COALESCE(a.jobs_retail_400m, 0) + COALESCE(a.jobs_office_400m, 0)
            + COALESCE(a.jobs_other_400m, 0)) AS jobs_three_400m
    FROM analysis.address a
    LEFT JOIN nta_size s
           ON s.borough = a.borough
          AND s.nta_code IS NOT DISTINCT FROM a.nta_code
), shares AS (
    SELECT base.*,
           {_share('retail_area_400m', 'area_four_400m')}  AS retail_area_share,
           {_share('office_area_400m', 'area_four_400m')}  AS office_area_share,
           {_share('res_area_400m', 'area_four_400m')}     AS res_area_share,
           {_share('factory_area_400m', 'area_four_400m')} AS factory_area_share,
           {_share('jobs_retail_400m', 'jobs_three_400m')} AS jobs_retail_share,
           {_share('jobs_office_400m', 'jobs_three_400m')} AS jobs_office_share,
           {_share('jobs_other_400m', 'jobs_three_400m')}  AS jobs_other_share,
           -- The ZONING witness (D82). Denominator is EVERY lot within 400 m,
           -- so this is "of the lots around me, what fraction may legally hold
           -- a shop". NULL where the catchment contains no lot at all, which
           -- on this graph means an address on a pier or a bridge approach.
           {_share('commercial_lots_400m', 'lots_400m')}    AS commercial_overlay_share_400m
    FROM base
), flagged AS (
    SELECT shares.*,
           {_suppressed_sql()} AS suppressed,
           CASE WHEN character_run_at IS NULL THEN NULL
                ELSE LEAST(1.0, GREATEST(0.0, {_retail_index_sql()})) END
               AS retail_index
    FROM shares
)
SELECT flagged.*,
       CASE
           WHEN character_run_at IS NULL THEN NULL
           WHEN suppressed           THEN NULL
           WHEN {_corporate_rule()}  THEN 'corporate'
           WHEN {_industrial_rule()} THEN 'industrial'
           WHEN {_retail_rule()}     THEN 'retail_mixed'
           ELSE 'residential'
       END AS character,
       CASE
           WHEN character_run_at IS NULL THEN NULL
           WHEN suppressed           THEN NULL
           WHEN {_corporate_rule()}  THEN LEAST(1.0, GREATEST(0.0, {corp_int}))
           WHEN {_industrial_rule()} THEN LEAST(1.0, GREATEST(0.0, {ind_int}))
           WHEN {_retail_rule()}     THEN LEAST(1.0, GREATEST(0.0, {ret_int}))
           ELSE LEAST(1.0, GREATEST(0.0, {res_int}))
       END AS character_intensity
FROM flagged
"""


def nta_character_view_sql() -> str:
    """analysis.nta_character -- the NTA roll-up, ADDRESS-WEIGHTED.

    One row per (borough, nta_code). `share_*` is the fraction of the NTA's
    addresses carrying each label; `mean_*_share` is the mean of the per-address
    shares. The two answer different questions and both are here on purpose: an
    NTA can be 90% residential-labelled and still carry a high mean retail share
    if its one avenue is dense enough.

    `am_pm_share_median` is the D76 addendum's `transit_am_pm_share_400m` --
    the morning share of subway ENTRIES, which reads high where people LEAVE in
    the morning (a residential catchment) and low where they ARRIVE (a
    destination catchment). It is here as CORROBORATION from a completely
    different source: if this label says corporate, the AM share should be low.
    It is NULL for the ~61% of MN+BK addresses with no profiled station within
    400 m, so `n_am_pm` says how many addresses the median rests on.
    """
    #: D82: the row now survives suppression, flagged rather than dropped, so a
    #: reader asking "what about Green-Wood Cemetery" gets an explicit
    #: `suppressed = true` with NULL shares instead of a missing row they must
    #: guess the meaning of. The four share columns use a NULL-PRESERVING CASE
    #: (`WHEN character IS NULL THEN NULL`): the naive `ELSE 0` would report a
    #: suppressed NTA as 0% corporate, 0% retail and 0% residential, which
    #: reads as a finding rather than as a refusal.
    return f"""
CREATE OR REPLACE VIEW analysis.nta_character AS
SELECT borough,
       nta_code,
       any_value(neighborhood)                                        AS neighborhood,
       count(*)                                                       AS addresses,
       bool_or(suppressed)                                            AS suppressed,
       mode(character)                                                AS dominant_character,
       avg(CASE WHEN character IS NULL THEN NULL
                WHEN character = 'corporate'    THEN 1 ELSE 0 END)    AS share_corporate,
       avg(CASE WHEN character IS NULL THEN NULL
                WHEN character = 'retail_mixed' THEN 1 ELSE 0 END)    AS share_retail_mixed,
       avg(CASE WHEN character IS NULL THEN NULL
                WHEN character = 'industrial'   THEN 1 ELSE 0 END)    AS share_industrial,
       avg(CASE WHEN character IS NULL THEN NULL
                WHEN character = 'residential'  THEN 1 ELSE 0 END)    AS share_residential,
       -- The CONTINUOUS measure (D82). Computed for suppressed NTAs too: it is
       -- an evidence score, not a claim about a neighbourhood's identity.
       avg(retail_index)                                              AS mean_retail_index,
       median(retail_index)                                           AS med_retail_index,
       avg(commercial_overlay_share_400m)                             AS mean_overlay_share,
       avg(CASE WHEN commercial_overlay_100m >= {COMMERCIAL_OVERLAY_MIN_LOTS}
                THEN 1 ELSE 0 END)                                    AS share_on_commercial_block,
       avg(retail_area_share)                                         AS mean_retail_area_share,
       avg(office_area_share)                                         AS mean_office_area_share,
       avg(res_area_share)                                            AS mean_res_area_share,
       avg(factory_area_share)                                        AS mean_factory_area_share,
       avg(jobs_retail_share)                                         AS mean_jobs_retail_share,
       avg(jobs_office_share)                                         AS mean_jobs_office_share,
       avg(jobs_other_share)                                          AS mean_jobs_other_share,
       avg(character_intensity)                                       AS mean_intensity,
       median(homes_400m)                                             AS med_homes_400m,
       median(jobs_three_400m)                                        AS med_jobs_400m,
       median(transit_am_pm_share_400m)                               AS am_pm_share_median,
       count(transit_am_pm_share_400m)                                AS n_am_pm
FROM analysis.address_character
-- D84: LOT frame only. Every share, mean and median here is "over this
-- neighbourhood's addresses", and D82's published numbers were measured over
-- residential lots. Street midpoints carry their own character on the address
-- view; letting them into this GROUP BY would move every share in the
-- neighbourhood layer without any building having changed.
WHERE character_run_at IS NOT NULL AND COALESCE(frame, 'lot') = 'lot'
GROUP BY borough, nta_code
"""


def create_views(con) -> None:
    """Create/replace both views. Called by db.init_schema() straight after
    021_address_character.sql, and again by `build_character` so a tuned
    threshold takes effect on the next read."""
    con.execute(address_character_view_sql())
    con.execute(nta_character_view_sql())


# ------------------------------------------------------------- the read-back

VALIDATION_SQL = """
-- Proves, ON THE WAREHOUSE and not on the frame:
--   * row counts, and that every in-scope address has EVERY column (the
--     no-missing rule -- 0 is an observation, NULL means the build never ran);
--   * that the three sector columns SUM EXACTLY to jobs_400m, which is the
--     cross-check that this sweep reproduced `loci address-access`'s sweep on
--     the same graph at the same radius with a different weight vector. Any
--     row where they differ means the two runs saw different geography;
--   * that the four named floor areas never exceed BldgArea over the same lot
--     set, which a double-counting bug inside one catchment would break;
--   * that every labelled address got exactly one label and an intensity in
--     [0, 1].
-- A lot within 400 m of N addresses is counted N times BY DESIGN -- these are
-- per-address catchments, not a partition -- so "does the sum match PLUTO" is
-- the WRONG check and is deliberately not made.
SELECT borough,
       count(*)                                                  AS addresses,
       count(character_run_at)                                   AS built,
       count(retail_area_400m)                                   AS have_retail_area,
       count(office_area_400m)                                   AS have_office_area,
       count(jobs_retail_400m)                                   AS have_jobs_retail,
       sum(CASE WHEN jobs_retail_400m + jobs_office_400m + jobs_other_400m
                     <> jobs_400m THEN 1 ELSE 0 END)             AS jobs_sum_mismatch,
       sum(CASE WHEN jobs_other_400m < 0 THEN 1 ELSE 0 END)      AS jobs_other_negative,
       sum(CASE WHEN retail_area_400m + office_area_incl_inst_400m + res_area_400m
                     + factory_area_400m > bldg_area_400m + 1
                THEN 1 ELSE 0 END)                               AS area_exceeds_bldg,
       -- D82: the institutional exclusion can only REMOVE office floor area,
       -- and the commercial lots are a subset of all lots. Either inequality
       -- flipping means the weight vectors were mis-ordered in the sweep.
       sum(CASE WHEN office_area_400m > office_area_incl_inst_400m + 1
                THEN 1 ELSE 0 END)                               AS office_excl_exceeds_raw,
       sum(CASE WHEN commercial_lots_400m > lots_400m
                THEN 1 ELSE 0 END)                               AS comm_lots_exceed_lots,
       sum(CASE WHEN commercial_overlay_100m > commercial_lots_400m
                THEN 1 ELSE 0 END)                               AS near_exceeds_far,
       count(DISTINCT character_radius_m)                        AS n_radii,
       count(DISTINCT character_pluto_version)                   AS n_pluto_versions,
       count(DISTINCT character_jobs_vintage)                    AS n_jobs_vintages
FROM analysis.address
GROUP BY ROLLUP(borough)
ORDER BY borough NULLS LAST
"""

LABEL_VALIDATION_SQL = """
-- Every in-scope, UNSUPPRESSED address carries a label; every intensity and
-- every retail_index is in [0, 1]; and a NULL label is accounted for by one of
-- the two reasons a NULL is allowed (D82: not built, or suppressed). If
-- `unexplained_null_label` is ever non-zero the CASE has a hole in it.
SELECT borough,
       count(*)                                                   AS addresses,
       count(character)                                           AS labelled,
       sum(CASE WHEN suppressed THEN 1 ELSE 0 END)                AS suppressed,
       sum(CASE WHEN character IS NULL THEN 1 ELSE 0 END)         AS null_label,
       sum(CASE WHEN character IS NULL AND NOT suppressed
                     AND character_run_at IS NOT NULL
                THEN 1 ELSE 0 END)                                AS unexplained_null_label,
       sum(CASE WHEN character IS NOT NULL AND character_intensity IS NULL
                THEN 1 ELSE 0 END)                                AS null_intensity,
       sum(CASE WHEN character_intensity < 0 OR character_intensity > 1
                THEN 1 ELSE 0 END)                                AS intensity_out_of_range,
       sum(CASE WHEN retail_index < 0 OR retail_index > 1
                THEN 1 ELSE 0 END)                                AS retail_index_out_of_range,
       sum(CASE WHEN character_run_at IS NOT NULL AND retail_index IS NULL
                THEN 1 ELSE 0 END)                                AS null_retail_index,
       sum(CASE WHEN area_four_400m = 0 THEN 1 ELSE 0 END)        AS zero_built_area,
       sum(CASE WHEN jobs_three_400m = 0 THEN 1 ELSE 0 END)       AS zero_jobs
FROM analysis.address_character
GROUP BY ROLLUP(borough)
ORDER BY borough NULLS LAST
"""

SUPPRESSION_SQL = """
-- WHICH NTAs were suppressed and why (D82). Printed rather than asserted: a
-- suppression rule nobody can see the victims of is a silent filter.
SELECT borough, nta_code, substr(any_value(neighborhood), 1, 40) AS neighborhood,
       count(*) AS addresses,
       CASE WHEN TRY_CAST(substr(nta_code, 5, 2) AS INTEGER) >= 70
            THEN 'park/cemetery/airport polygon'
            ELSE 'fewer than 50 addresses' END                     AS reason
FROM analysis.address_character
WHERE suppressed AND character_run_at IS NOT NULL
GROUP BY borough, nta_code
ORDER BY addresses DESC
"""


def label_counts(con) -> pd.DataFrame:
    return con.execute("""
        SELECT borough, character, count(*) AS addresses,
               round(avg(character_intensity), 3) AS mean_intensity
        FROM analysis.address_character
        WHERE character IS NOT NULL
        GROUP BY ROLLUP(borough), character
        ORDER BY borough NULLS LAST, addresses DESC
    """).fetchdf()


#: The share columns whose distribution justifies the thresholds.
DECILE_COLUMNS = ("retail_area_share", "office_area_share", "res_area_share",
                  "factory_area_share", "jobs_retail_share", "jobs_office_share",
                  "jobs_other_share")


def deciles(con, boroughs: list[str] | None = None) -> pd.DataFrame:
    """Deciles of each share over the labelled addresses. This is the table a
    threshold has to be read off: a cut at the 90th percentile of a share is a
    QUANTILE ARTEFACT (D34's lesson -- a p80 calibration fixes the rate at 20%
    by construction), so the thresholds here are absolute and the deciles are
    what says whether an absolute cut lands somewhere meaningful."""
    where = ""
    params: list = []
    if boroughs:
        where = f"AND borough IN ({', '.join('?' for _ in boroughs)})"
        params = list(boroughs)
    qs = "[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]"
    cols = ",\n               ".join(
        f"unnest(list_transform(quantile_cont({c}, {qs}), x -> round(x, 4))) AS {c}"
        for c in DECILE_COLUMNS)
    return con.execute(f"""
        SELECT unnest({qs}) AS quantile,
               {cols}
        FROM analysis.address_character
        WHERE character IS NOT NULL {where}
    """, params).fetchdf()


def rule_overlap(con) -> pd.DataFrame:
    """How often two rules fire on the same address, which is what makes
    LABEL_ORDER load-bearing. Printed so the ordering's cost is visible rather
    than hidden inside a CASE."""
    return con.execute(f"""
        SELECT sum(CASE WHEN ({_corporate_rule()}) THEN 1 ELSE 0 END) AS corporate_fires,
               sum(CASE WHEN ({_industrial_rule()}) THEN 1 ELSE 0 END) AS industrial_fires,
               sum(CASE WHEN ({_retail_rule()}) THEN 1 ELSE 0 END)    AS retail_fires,
               sum(CASE WHEN ({_corporate_rule()}) AND ({_retail_rule()})
                        THEN 1 ELSE 0 END)                            AS corp_and_retail,
               sum(CASE WHEN ({_industrial_rule()}) AND ({_retail_rule()})
                        THEN 1 ELSE 0 END)                            AS ind_and_retail,
               sum(CASE WHEN ({_corporate_rule()}) AND ({_industrial_rule()})
                        THEN 1 ELSE 0 END)                            AS corp_and_ind,
               sum(CASE WHEN commercial_overlay_100m >= {COMMERCIAL_OVERLAY_MIN_LOTS}
                        THEN 1 ELSE 0 END)                            AS overlay_fires,
               sum(CASE WHEN commercial_overlay_100m >= {COMMERCIAL_OVERLAY_MIN_LOTS}
                         AND COALESCE(retail_area_share, 0) < {RETAIL_AREA_SHARE}
                         AND NOT (COALESCE(jobs_retail_share, 0) >= {RETAIL_JOBS_SHARE}
                              AND COALESCE(jobs_retail_400m, 0) >= {RETAIL_JOBS_FLOOR})
                        THEN 1 ELSE 0 END)                            AS overlay_only
        FROM analysis.address_character
        WHERE character IS NOT NULL
    """).fetchdf()


def am_pm_corroboration(con) -> pd.DataFrame:
    """The label against `transit_am_pm_share_400m` (D76 addendum), which comes
    from a COMPLETELY DIFFERENT SOURCE -- MTA turnstile entries by hour -- and
    knows nothing about PLUTO or LODES.

    The morning share of subway ENTRIES is high where people LEAVE in the
    morning (a residential catchment) and low where they ARRIVE (a destination
    catchment). If the label means anything, this number should fall
    monotonically from residential to corporate. It does. That is the only
    external check available here, and it is worth more than any internal
    consistency test, because nothing in the label's construction could have
    produced it.

    It rests on the ~40% of MN+BK addresses with a profiled station within
    400 m; `n_am_pm` says how many, per label.
    """
    return con.execute("""
        SELECT character,
               count(*)                                       AS addresses,
               count(transit_am_pm_share_400m)                AS n_am_pm,
               round(median(transit_am_pm_share_400m), 2)     AS am_pm_median,
               round(median(jobs_three_400m))                 AS med_jobs_400m,
               round(median(homes_400m))                      AS med_homes_400m
        FROM analysis.address_character
        WHERE character IS NOT NULL
        GROUP BY character
        ORDER BY am_pm_median
    """).fetchdf()


def nta_table(con, boroughs: list[str] | None = None,
              order_by: str = "share_corporate", limit: int | None = None,
              ascending: bool = False, min_addresses: int = 200) -> pd.DataFrame:
    """The NTA roll-up, narrowed to what a reader can hold in one line.

    `min_addresses` exists because the NTA layer includes park, cemetery and
    island polygons that happen to contain a handful of residential lots
    (Calvert Vaux Park has 9, Lincoln Terrace Park has 6). Ranked without a
    floor, those tiny denominators take every top slot on any share and say
    nothing about New York. 200 is the smallest NTA anyone would quote.
    """
    clauses, params = [], []
    if boroughs:
        clauses.append(f"borough IN ({', '.join('?' for _ in boroughs)})")
        params += list(boroughs)
    clauses.append(f"addresses >= {int(min_addresses)}")
    # D82: suppressed NTAs carry NULL shares, so they would sort to the bottom
    # anyway -- excluded explicitly so nobody has to rely on that.
    clauses.append("NOT suppressed")
    where = "WHERE " + " AND ".join(clauses)
    direction = "ASC" if ascending else "DESC"
    lim = f"LIMIT {int(limit)}" if limit else ""
    return con.execute(f"""
        SELECT nta_code,
               substr(neighborhood, 1, 34)      AS neighborhood,
               addresses                        AS addr,
               dominant_character               AS dominant,
               round(share_corporate, 3)        AS corp,
               round(share_retail_mixed, 3)     AS retail,
               round(share_industrial, 3)       AS indus,
               round(share_residential, 3)      AS resid,
               round(mean_office_area_share, 3) AS off_area,
               round(mean_retail_area_share, 3) AS ret_area,
               round(mean_factory_area_share, 3) AS fac_area,
               round(mean_jobs_office_share, 3) AS off_jobs,
               round(mean_jobs_retail_share, 3) AS ret_jobs,
               round(mean_overlay_share, 3)     AS ovl_share,
               round(mean_retail_index, 3)      AS ret_idx,
               round(med_retail_index, 3)       AS ret_idx_p50,
               med_jobs_400m                    AS jobs_p50,
               round(am_pm_share_median, 2)     AS am_pm
        FROM analysis.nta_character
        {where}
        ORDER BY {order_by} {direction} NULLS LAST, addresses DESC
        {lim}
    """, params).fetchdf()
