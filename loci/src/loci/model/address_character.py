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
#: A FLOOR on the jobs route, so a rowhouse block with 11 jobs -- six of them a
#: title company -- cannot be "corporate" on a 55% share of nearly nothing.
CORPORATE_JOBS_FLOOR = 5_000

#: RETAIL floor-area share at which the catchment reads as a shopping street.
#: Low in absolute terms ON PURPOSE: retail is a GROUND FLOOR and competes with
#: every storey above it, so a fully retail-fronted avenue in a six-storey
#: neighbourhood tops out near 0.17. See caveat 1 -- PLUTO under-reports
#: RetailArea on exactly these blocks, so this is a floor on a floor.
RETAIL_AREA_SHARE = 0.12
#: ...or the payroll route: two in five jobs within the walk are the shops,
#: restaurants and services themselves.
RETAIL_JOBS_SHARE = 0.40
#: ...but only where there is enough of it to be a commercial district. This
#: floor is on the retail-facing COUNT, not on total jobs, and it is the single
#: most consequential tuning decision here. Without it the payroll route labels
#: 28% of MN+BK retail_mixed and 74% of PARK SLOPE, because in a quiet
#: residential catchment the few jobs that exist are disproportionately the
#: corner deli and the nail salon -- a high share of almost nothing, which is a
#: data gap wearing a costume. At 1,000 retail-facing jobs (roughly 100-200
#: establishments within a five-minute walk) Park Slope falls to 25% -- its
#: avenues, not its side streets -- and Bay Ridge to 5%, while Williamsburg
#: (54%), the East Village (59%) and the West Village (74%) are untouched.
#: The COST, stated rather than hidden: outer-borough strips built of very small
#: shops (Flatbush Avenue, Church Avenue) have real retail and few payroll jobs,
#: so they clear this only via the floor-area route and their NTA reads
#: residential-dominant with a retail_mixed minority ON the strip. That is the
#: honest reading of an address-grain measure, but it means `share_retail_mixed`
#: UNDERSTATES small-shop retail geography relative to Manhattan.
RETAIL_JOBS_FLOOR = 1_000

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
    "retail_area", "office_area", "res_area", "factory_area", "bldg_area")
JOB_WEIGHTS: tuple[str, ...] = ("jobs_retail", "jobs_office", "jobs_total")
SWEEP_KEYS: tuple[str, ...] = (*LOT_WEIGHTS, *JOB_WEIGHTS)

#: The ONLY columns write_character may name in a SET clause.
CHARACTER_COLUMNS = [
    "retail_area_400m",
    "office_area_400m",
    "res_area_400m",
    "factory_area_400m",
    "bldg_area_400m",
    "jobs_retail_400m",
    "jobs_office_400m",
    "jobs_other_400m",
    "character_radius_m",
    "character_pluto_version",
    "character_jobs_vintage",
    "character_run_at",
]


# ----------------------------------------------------------------- the reads

def load_lot_points(con, bbox: tuple[float, float, float, float],
                    pluto_csv: pathlib.Path | str = PLUTO_CSV) -> pd.DataFrame:
    """One row per MapPLUTO tax lot inside `bbox` with usable coordinates:
    (bbl, lon, lat, retail_area, office_area, res_area, factory_area,
    bldg_area, unitsres, version). SQUARE FEET.

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
        """
        SELECT BBL                                             AS bbl,
               TRY_CAST(longitude AS DOUBLE)                   AS lon,
               TRY_CAST(latitude  AS DOUBLE)                   AS lat,
               COALESCE(TRY_CAST(retailarea AS DOUBLE), 0)     AS retail_area,
               COALESCE(TRY_CAST(officearea AS DOUBLE), 0)     AS office_area,
               COALESCE(TRY_CAST(resarea    AS DOUBLE), 0)     AS res_area,
               COALESCE(TRY_CAST(factryarea AS DOUBLE), 0)     AS factory_area,
               COALESCE(TRY_CAST(bldgarea   AS DOUBLE), 0)     AS bldg_area,
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
        "res_area": lots["res_area"].to_numpy(dtype=np.float64),
        "factory_area": lots["factory_area"].to_numpy(dtype=np.float64),
        "bldg_area": lots["bldg_area"].to_numpy(dtype=np.float64),
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
        "res_area_400m": col["res_area"],
        "factory_area_400m": col["factory_area"],
        "bldg_area_400m": col["bldg_area"],
        "jobs_retail_400m": j_ret,
        "jobs_office_400m": j_off,
        "jobs_other_400m": j_oth,
        "character_radius_m": float(radius_m),
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
        "lot_bldg_area_total": float(lots["bldg_area"].sum()),
        "lot_office_area_total": float(lots["office_area"].sum()),
        "lot_retail_area_total": float(lots["retail_area"].sum()),
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
    graph_path: pathlib.Path = GRAPH_PATH,
    jobs_vintage: int = DEFAULT_JOBS_VINTAGE,
    pluto_csv: pathlib.Path | str = PLUTO_CSV,
    dry_run: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """compute + write, then (re)create the two views so a tuned threshold
    takes effect without a schema re-init."""
    df, report = compute_character(
        con, boroughs, radius_m=radius_m, graph_path=graph_path,
        jobs_vintage=jobs_vintage, pluto_csv=pluto_csv)
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
    return (f"COALESCE({prefix}office_area_share, 0) >= {CORPORATE_OFFICE_AREA_SHARE} "
            f"OR (COALESCE({prefix}jobs_office_share, 0) >= {CORPORATE_JOBS_OFFICE_SHARE} "
            f"AND COALESCE({prefix}jobs_three_400m, 0) >= {CORPORATE_JOBS_FLOOR})")


def _industrial_rule(prefix: str = "") -> str:
    return f"COALESCE({prefix}factory_area_share, 0) >= {INDUSTRIAL_FACTORY_AREA_SHARE}"


def _retail_rule(prefix: str = "") -> str:
    return (f"COALESCE({prefix}retail_area_share, 0) >= {RETAIL_AREA_SHARE} "
            f"OR (COALESCE({prefix}jobs_retail_share, 0) >= {RETAIL_JOBS_SHARE} "
            f"AND COALESCE({prefix}jobs_retail_400m, 0) >= {RETAIL_JOBS_FLOOR})")


def address_character_view_sql() -> str:
    """analysis.address_character -- shares, label, intensity.

    Every in-scope address gets a label. NULL appears in exactly one case,
    `character_run_at IS NULL`, which means the build has not run for that
    borough; a NULL there is honest and a fabricated 'residential' would not be.
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
    ret_int = (f"GREATEST("
               f"(COALESCE(retail_area_share, 0) - {RETAIL_AREA_SHARE}) "
               f"/ {round(1 - RETAIL_AREA_SHARE, 10)}, "
               f"CASE WHEN COALESCE(jobs_retail_400m, 0) >= {RETAIL_JOBS_FLOOR} "
               f"THEN (COALESCE(jobs_retail_share, 0) - {RETAIL_JOBS_SHARE}) "
               f"/ {round(1 - RETAIL_JOBS_SHARE, 10)} ELSE -1 END)")
    res_int = (f"1.0 - GREATEST("
               f"COALESCE(office_area_share, 0) / {CORPORATE_OFFICE_AREA_SHARE}, "
               f"COALESCE(factory_area_share, 0) / {INDUSTRIAL_FACTORY_AREA_SHARE}, "
               f"COALESCE(retail_area_share, 0) / {RETAIL_AREA_SHARE}, "
               f"CASE WHEN COALESCE(jobs_retail_400m, 0) >= {RETAIL_JOBS_FLOOR} "
               f"THEN COALESCE(jobs_retail_share, 0) / {RETAIL_JOBS_SHARE} "
               f"ELSE 0 END, "
               f"CASE WHEN COALESCE(jobs_three_400m, 0) >= {CORPORATE_JOBS_FLOOR} "
               f"THEN COALESCE(jobs_office_share, 0) / {CORPORATE_JOBS_OFFICE_SHARE} "
               f"ELSE 0 END)")
    return f"""
CREATE OR REPLACE VIEW analysis.address_character AS
WITH base AS (
    SELECT address_id, borough, nta_code, neighborhood, lon, lat,
           homes_400m, jobs_400m, transit_entries_400m, transit_am_pm_share_400m,
           retail_area_400m, office_area_400m, res_area_400m, factory_area_400m,
           bldg_area_400m,
           jobs_retail_400m, jobs_office_400m, jobs_other_400m,
           character_radius_m, character_pluto_version, character_jobs_vintage,
           character_run_at,
           -- The share DENOMINATOR is the four NAMED uses, not BldgArea:
           -- garage, storage, "other" and unclassified floor area are ~18% of
           -- BldgArea citywide and dividing by it would make every share read
           -- systematically low for no gain in meaning. bldg_area_400m stays on
           -- the view so a reader can see how much was left out.
           (COALESCE(retail_area_400m, 0) + COALESCE(office_area_400m, 0)
            + COALESCE(res_area_400m, 0) + COALESCE(factory_area_400m, 0))
               AS area_four_400m,
           (COALESCE(jobs_retail_400m, 0) + COALESCE(jobs_office_400m, 0)
            + COALESCE(jobs_other_400m, 0)) AS jobs_three_400m
    FROM analysis.address
), shares AS (
    SELECT base.*,
           {_share('retail_area_400m', 'area_four_400m')}  AS retail_area_share,
           {_share('office_area_400m', 'area_four_400m')}  AS office_area_share,
           {_share('res_area_400m', 'area_four_400m')}     AS res_area_share,
           {_share('factory_area_400m', 'area_four_400m')} AS factory_area_share,
           {_share('jobs_retail_400m', 'jobs_three_400m')} AS jobs_retail_share,
           {_share('jobs_office_400m', 'jobs_three_400m')} AS jobs_office_share,
           {_share('jobs_other_400m', 'jobs_three_400m')}  AS jobs_other_share
    FROM base
)
SELECT shares.*,
       CASE
           WHEN character_run_at IS NULL THEN NULL
           WHEN {_corporate_rule()}  THEN 'corporate'
           WHEN {_industrial_rule()} THEN 'industrial'
           WHEN {_retail_rule()}     THEN 'retail_mixed'
           ELSE 'residential'
       END AS character,
       CASE
           WHEN character_run_at IS NULL THEN NULL
           WHEN {_corporate_rule()}  THEN LEAST(1.0, GREATEST(0.0, {corp_int}))
           WHEN {_industrial_rule()} THEN LEAST(1.0, GREATEST(0.0, {ind_int}))
           WHEN {_retail_rule()}     THEN LEAST(1.0, GREATEST(0.0, {ret_int}))
           ELSE LEAST(1.0, GREATEST(0.0, {res_int}))
       END AS character_intensity
FROM shares
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
    return """
CREATE OR REPLACE VIEW analysis.nta_character AS
SELECT borough,
       nta_code,
       any_value(neighborhood)                                        AS neighborhood,
       count(*)                                                       AS addresses,
       mode(character)                                                AS dominant_character,
       avg(CASE WHEN character = 'corporate'    THEN 1 ELSE 0 END)    AS share_corporate,
       avg(CASE WHEN character = 'retail_mixed' THEN 1 ELSE 0 END)    AS share_retail_mixed,
       avg(CASE WHEN character = 'industrial'   THEN 1 ELSE 0 END)    AS share_industrial,
       avg(CASE WHEN character = 'residential'  THEN 1 ELSE 0 END)    AS share_residential,
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
WHERE character IS NOT NULL
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
       sum(CASE WHEN retail_area_400m + office_area_400m + res_area_400m
                     + factory_area_400m > bldg_area_400m + 1
                THEN 1 ELSE 0 END)                               AS area_exceeds_bldg,
       count(DISTINCT character_radius_m)                        AS n_radii,
       count(DISTINCT character_pluto_version)                   AS n_pluto_versions,
       count(DISTINCT character_jobs_vintage)                    AS n_jobs_vintages
FROM analysis.address
GROUP BY ROLLUP(borough)
ORDER BY borough NULLS LAST
"""

LABEL_VALIDATION_SQL = """
-- Every in-scope address carries a label, and every intensity is in [0, 1].
SELECT borough,
       count(*)                                                   AS addresses,
       count(character)                                           AS labelled,
       sum(CASE WHEN character IS NULL THEN 1 ELSE 0 END)         AS null_label,
       sum(CASE WHEN character_intensity IS NULL THEN 1 ELSE 0 END) AS null_intensity,
       sum(CASE WHEN character_intensity < 0 OR character_intensity > 1
                THEN 1 ELSE 0 END)                                AS intensity_out_of_range,
       sum(CASE WHEN area_four_400m = 0 THEN 1 ELSE 0 END)        AS zero_built_area,
       sum(CASE WHEN jobs_three_400m = 0 THEN 1 ELSE 0 END)       AS zero_jobs
FROM analysis.address_character
GROUP BY ROLLUP(borough)
ORDER BY borough NULLS LAST
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
                        THEN 1 ELSE 0 END)                            AS corp_and_ind
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
               med_jobs_400m                    AS jobs_p50,
               round(am_pm_share_median, 2)     AS am_pm
        FROM analysis.nta_character
        {where}
        ORDER BY {order_by} {direction} NULLS LAST, addresses DESC
        {lim}
    """, params).fetchdf()
