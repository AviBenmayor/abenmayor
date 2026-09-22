"""Supply INTENSITY at address grain: how much of a category is within reach
per 1,000 homes, relative to the MN+BK norm (red-team findings 1-3, 2026-09-11).

WHY THIS EXISTS -- "is there a gap" is the wrong statistic
---------------------------------------------------------------------------
The address screen answers a BINARY-ish question: is the nearest business of
category c further away than the category's reach (`ratio > 1`)? That question
is silent about the case the Gowanus red-team actually found -- a category that
is PRESENT but THIN. One pharmacy 380 m away makes `ratio <= 1` and the address
stops being a pharmacy gap, even though the same walk in Park Slope passes
eight of them. `nearest_m` cannot see density, and density is what a retail
operator is buying.

So this module measures the other thing:

    supply_400m           principled POIs of the category within 400 m network
    homes_400m            residential units within 400 m network
    supply_per_1k         supply_400m / homes_400m * 1000
    supply_ratio_vs_base  supply_per_1k / the MN+BK median of supply_per_1k

`supply_ratio_vs_base` is the deliverable: 0.07 means "this neighbourhood has
7% of the pharmacy-per-resident the median MN+BK block has", which is a
statement about UNDER-PROVISION, not about absence. It is scale-free, it is
comparable across categories with wildly different absolute densities (there
are 39,459 principled restaurants and 966 tailors), and it ranks.

THE PRINCIPLED SET, AND THE HASH (red-team finding 1)
---------------------------------------------------------------------------
Every count here comes from `analysis.poi_supply WHERE in_principled` -- the
D52/D59 set the screen itself runs on -- and NEVER from `in_all`. The two
differ enormously in exactly the categories this analysis is about: bar 5,011
vs 12,516, nails_beauty 9,412 vs 24,009, laundry 4,979 vs 7,981. A ratio built
on one set and compared against a baseline built on the other is meaningless,
so the run stamps `score.supply.supply_hash(con)` onto every row it writes
(`supply_ratio_supply_hash`) and into the baseline YAML. A baseline whose hash
does not match the live one is a drift warning, loudly, in the CLI and in a
test -- the supply view is a VIEW, so it moves the moment someone re-runs
`loci dedup` or loads an anchor.

WHAT THE BASELINE IS, AND WHAT IT IS NOT (D6)
---------------------------------------------------------------------------
`baseline_per_1k(category)` is the MEDIAN of `supply_per_1k` over ELIGIBLE
MN+BK addresses with at least one home within reach -- address-weighted, not
home-weighted, so a 400-unit tower and a rowhouse count once each. The YAML
also stores p25, p75, n and an `aggregate_per_1k` (total principled POIs over
total units in scope), which is the home-weighted alternative; they differ and
the difference is informative, so both ship.

It is REVEALED SUPPLY (D6 circularity, restated once here because it is the
whole risk of this measure): the baseline is what New York built, not what New
York needed. If the median MN+BK block is itself under-served in a category,
every ratio is flattered; if the median block is over-served, every ratio is
deflated. A ratio of 1.0 means "normal for this city", never "correctly
provisioned". And the same Meltzer & Schuetz caveat the demand annotation
carries applies with full force: under-provision is correlated with race net of
income, so a low ratio is a measurement of what is there, not a proof of unmet
demand.

WHERE THE COLUMNS LIVE, AND WHY NOT ALL IN ONE PLACE (D61)
---------------------------------------------------------------------------
`supply_400m`, `supply_per_1k` and `supply_ratio_vs_base` vary by category, so
they extend `analysis.address_category` (767,337 x 15). `homes_400m` and
`addressable_homes_400m_laundry` DO NOT vary by category -- the same homes are
within 400 m whether you are asking about pharmacies or bars -- so they extend
`analysis.address`, exactly as `storefronts_400m` and `units_permitted_400m`
do, and for the same reason model/storefronts.py gives: putting them on
address_category would write fifteen identical copies of one number, 11.5M
rows to say 767k things, which is the pivot-shaped duplication D61 removed.
`supply_per_1k` therefore reads its denominator by JOIN at compute time; the
task brief asked for `homes_400m` on address_category and this is the one
deliberate deviation from it.

`supply_per_1k` IS stored even though it is `supply_400m / homes_400m * 1000`,
because the ratio's denominator lives on the other table and a reader who wants
the headline number should not have to re-derive it (and re-derive the
divide-by-zero rule) in every query.

NON-FILTERING, UPDATE-ONLY (D48/D57/D58/D62/D67)
---------------------------------------------------------------------------
`write_address_measures` issues ONLY `UPDATE analysis.address SET
<ADDRESS_RATIO_COLUMNS>` and `write_category_measures` only `UPDATE
analysis.address_category SET <CATEGORY_RATIO_COLUMNS>`. Neither INSERTs nor
DELETEs, and both SET lists are pinned disjoint from the screen's own columns,
from D57's demand annotation, from D62's pipeline columns, from D63's age-fit
columns and from D67's storefront columns by tests/test_supply_ratio.py. A
thin category does not become a gap; a thick one does not stop being one.
Intensity is a SECOND reading beside the screen, never a filter on it.

RE-APPLIABLE BY ONE COMMAND
---------------------------------------------------------------------------
Because the address screen clears UPDATE-only columns and re-applies
`loci pipeline`, `loci storefronts`, age-fit in that order, everything here has
to survive being wiped. It does: `loci supply-ratio --boroughs MN,BK` recomputes
all five columns from scratch off the warehouse and the committed baseline YAML,
in one command, with no dependency on any other annotation. Run it after
age-fit. `--fit-baseline` is the ONLY flag that rewrites the YAML and is not
part of the re-apply path -- a re-apply must not silently re-baseline, or every
run measures itself against itself.

NETWORK DISTANCE, NOT STRAIGHT LINE
---------------------------------------------------------------------------
Same engine as the gap screen, the pipeline catchments and the storefront
counts: `score/access._prune` + `_to_csr`, then scipy Dijkstra on the pedestrian
walk graph. The direction of the sweep is the one thing that differs from
model/storefronts.py, and it is what makes 11.5M rows tractable: storefronts
sources Dijkstra FROM the ~38k storefronts, which is right when the weights are
few. Here the weights are 140k POIs AND 767k addresses, and the OUTPUT is
needed at only 39,083 distinct graph nodes (282k MN+BK addresses collapse onto
39k nodes, because a 400 m catchment cannot tell two doorways on one block
apart). So the sweep is sourced FROM those 39k query nodes, each batch reading
off every weight inside the radius in one matrix product -- one pass that
produces all seventeen measures (15 categories + homes + addressable homes)
instead of seventeen passes. ~611 Dijkstra calls at 400 m, not 2,200.

Symmetry is what licenses the reversal: the walk graph is undirected, so
"POIs within 400 m of node i" and "nodes within 400 m of POI j" are the same
relation read from opposite ends.

THE WALK-SHED'S AREA, AND WHY DENSITY IS NOT homes_400m (owner ruling,
2026-09-13: "rank by density")
---------------------------------------------------------------------------
`homes_400m` is a COUNT. Two addresses with 3,000 homes inside a five-minute
walk are not equally dense if one of them reaches those homes across a
permeable Manhattan grid and the other has to spend its 400 m walking the one
street that crosses a rail cut. Density is the count divided by the area the
walk actually reaches, so this module also persists that area:

    walkshed_km2_400m   area of the CONVEX HULL of the graph nodes within
                        `radius_m` NETWORK metres of the address's own node
    density_400m        homes_400m / walkshed_km2_400m  (units per km2)

It is computed in the SAME sweep, from the SAME Dijkstra rows that produce
`homes_400m` -- the reachable-node mask is already materialised for the
weight product, so the area costs one convex hull per query node (~39k hulls,
~70 s) and not a second pass.

NOT a nominal disc. pi*0.4^2 = 0.5027 km2 is the area a 400 m walk would
reach on a featureless plain; the measured median over the MN+BK query nodes
is well under half of that, and the gap between them IS the permeability
signal the ranking is supposed to see. Dividing by a constant would rank by
`homes_400m` again under a different name.

Convex, not concave, ON PURPOSE, and the direction of the error is the
argument. A concave hull needs an alpha/ratio knob that silently moves every
area; the convex hull has none. Where the reachable network is broken --
water, a park, a highway, a superblock -- the convex hull spans the hole and
OVERSTATES the shed, which UNDERSTATES the density, which is the conservative
direction for a screen whose output is "put capital here". It is also bounded
above for free: network distance >= straight-line distance, so every
reachable node lies inside the 400 m straight-line disc and the hull can
never exceed 0.5027 km2. What it understates is the frontier -- the walk does
not stop at the last intersection, it continues down the partially-traversed
edge -- so the hull is a little tight at the edges and a little loose at the
holes.

CAVEAT, carried into every card and popup that prints it: this is a UNITS
count over an area, not ACS households per km2. It has no margin of error
because PLUTO's UnitsRes has none to give; it is a register count, not a
survey estimate, and it must never be compared like-for-like with an ACS
household density that does carry an MOE.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pickle

import numpy as np
import osmnx as ox
import pandas as pd
import yaml
from pyproj import Transformer
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import ConvexHull, QhullError

from loci.categories import CATEGORIES
from loci.model import supply_asof as supply_asof_mod
from loci.model.conveniences import ALLCATS, graph_version
from loci.score.access import MIN_COMPONENT, THRESHOLDS, _prune, _to_csr
from loci.score.supply import DEFAULT_SUPPLY_SET, supply_hash, supply_predicate
from loci.score.walkgraph import OUT as GRAPH_PATH

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE_PATH = PKG_ROOT / "model" / "supply_baseline.yaml"
HAIRCUT_PATH = PKG_ROOT / "model" / "laundry_haircut.yaml"

#: 5-minute walk, pinned to THRESHOLDS[5] exactly as model/storefronts.py and
#: model/dev_pipeline.py pin it, so "within reach" is ONE distance everywhere.
DEFAULT_RADIUS_M = THRESHOLDS[5]      # 400.0

#: Query nodes per Dijkstra call. (BATCH, n_nodes) float64 is the peak
#: allocation: 48 x 605,130 x 8 = 232 MB.
BATCH = 48

#: Projected CRS the walk-shed hull is measured in. UTM 18N covers all five
#: boroughs; metres, so a hull area is metres squared with no further scaling.
#: Named here rather than inline so a city port changes ONE string.
SHED_CRS = "EPSG:32618"

#: Floor on a walk-shed's area, in km2 -- the area of a 50 m-radius disc. A
#: node on a stub with two reachable neighbours produces a degenerate sliver
#: of a hull, and `homes / sliver` is an arbitrarily large density that would
#: take the top of any ranking on a graph artifact. Below this the area is
#: recorded as the floor (never as NULL: the address is real and its homes are
#: real), and the run report counts how many addresses hit it.
MIN_SHED_KM2 = 0.00785

#: The ONLY columns write_address_measures may name in a SET clause.
#: Category-INDEPENDENT by construction -- see the module docstring on D61.
ADDRESS_RATIO_COLUMNS = [
    "homes_400m",
    "walkshed_km2_400m",
    "density_400m",
    "addressable_homes_400m_laundry",
    "supply_ratio_radius_m",
    "supply_ratio_supply_hash",
    "supply_ratio_run_at",
]

#: The ONLY columns write_category_measures may name in a SET clause.
CATEGORY_RATIO_COLUMNS = [
    "supply_400m",
    "supply_per_1k",
    "supply_ratio_vs_base",
]

#: analysis.address's screen-owned columns (model/address_gaps.ADDRESS_COLUMNS,
#: restated for the disjointness assertion; the test compares against the real
#: list by import, so a drift here fails rather than weakens the check).
ADDRESS_SCREEN_COLUMNS = [
    "address_id", "bbl", "lon", "lat", "units", "units_capped",
    "nta_code", "neighborhood", "borough", "h3_index",
    "present_count", "eligible", "gap_score", "lead_category",
    "lead_excess_m", "n_missing", "cluster_id",
    "reach_source", "reach_hash", "graph_version",
    "supply_set", "supply_hash", "run_at",
    "lead_censored",          # D75, appended
    # D84, appended: the sampling frame and the street-row descriptors. Owned
    # by the SCREEN (model/address_gaps.py writes them on INSERT); this list
    # exists so no annotation writer can name one.
    "frame", "frontage_m", "street_name", "frame_source", "frame_vintage",
]


# ------------------------------------------------------------ the haircut

def load_haircut(path: pathlib.Path | None = None) -> dict:
    """The in-home-laundry priors (model/laundry_haircut.yaml), validated.

    The bands must tile 1..inf with no gap and no overlap: a building whose
    unit count falls in no band would silently get p = 0 and be counted as
    fully addressable, which is the exact overstatement this table exists to
    prevent. Fail loudly instead.
    """
    doc = yaml.safe_load((path or HAIRCUT_PATH).read_text())
    bands = doc["size_class"]
    lo = 1
    for b in bands:
        if int(b["min_units"]) != lo:
            raise ValueError(
                f"laundry_haircut.yaml: band {b['name']} starts at "
                f"{b['min_units']}, expected {lo} -- bands must tile 1..inf "
                f"with no gap and no overlap.")
        if not 0.0 <= float(b["p_inhome"]) <= 1.0:
            raise ValueError(f"laundry_haircut.yaml: p_inhome out of [0,1] on {b['name']}")
        if b["max_units"] is None:
            if b is not bands[-1]:
                raise ValueError("laundry_haircut.yaml: an open band must be last")
            lo = None
            break
        lo = int(b["max_units"]) + 1
    if lo is not None:
        raise ValueError("laundry_haircut.yaml: the last band must be open (max_units: null)")
    return doc


def p_inhome(units: float | None, has_evidence: bool, haircut: dict) -> float:
    """Share of a building's homes that are NOT in the addressable market.

    `has_evidence` is the D55/D59 positive assertion only (LL84 reports a
    common-area or in-unit hookup, or a StreetEasy listing advertises laundry).
    It overrides the size prior in ONE direction: evidence of laundry removes
    the building, absence of evidence never adds one back, because an LL84
    blank and a silent amenity list are not observations of "no laundry"
    (sql/005 CAVEAT ZERO, sql/010).

    Returns 0.0 for a building with no homes -- it contributes nothing either
    way, and 0 * (1 - p) = 0 for any p, so the value is cosmetic.
    """
    if units is None or not units > 0:
        return 0.0
    if has_evidence:
        return float(haircut["evidence_p_inhome"])
    u = float(units)
    for b in haircut["size_class"]:
        hi = b["max_units"]
        if u >= float(b["min_units"]) and (hi is None or u <= float(hi)):
            return float(b["p_inhome"])
    raise ValueError(f"no size band covers units={units!r}")   # pragma: no cover


def addressable_units(units: float | None, has_evidence: bool, haircut: dict) -> float:
    """`units * (1 - p_inhome)`. A deterministic haircut, not a draw."""
    if units is None or not units > 0:
        return 0.0
    return float(units) * (1.0 - p_inhome(units, has_evidence, haircut))


# ------------------------------------------------------------- ratio math

def per_1k(supply: float | None, homes: float | None) -> float | None:
    """supply per 1,000 homes within reach. None -- never 0, never inf -- when
    there are no homes within reach: a block of warehouses with no pharmacy is
    not an under-served block, it is a block with no denominator."""
    if homes is None or not homes > 0 or supply is None:
        return None
    return float(supply) / float(homes) * 1000.0


def ratio_vs_base(value: float | None, base: float | None) -> float | None:
    """value / baseline. None when either side is missing or the baseline is
    zero (a category with no supply anywhere in scope has no norm to be
    measured against, and 0/0 is not 1.0)."""
    if value is None or base is None or not base > 0:
        return None
    return float(value) / float(base)


# ---------------------------------------------------------------- the read

def load_supply_points(con, supply_set: str = DEFAULT_SUPPLY_SET) -> pd.DataFrame:
    """Every POI in the supply set, CITYWIDE, with its category and lon/lat.

    Citywide on purpose and not restricted to the scored boroughs: a Bushwick
    address is served by the bodega 200 m across the Queens line, and clipping
    the weights at the borough boundary would invent a supply desert along
    every edge of the study area. The same reasoning the walk graph's 3 km
    bbox buffer already encodes.
    """
    pred = supply_predicate(supply_set)
    return con.execute(f"""
        SELECT category, ST_X(geom) AS lon, ST_Y(geom) AS lat
        FROM analysis.poi_supply
        WHERE {pred} AND category IN ({','.join("'" + c + "'" for c in ALLCATS)})
          AND geom IS NOT NULL
    """).fetchdf()


#: Which sampling frame carries HOMES (D84). A street midpoint has no
#: residents: its `units` is 0, so including it in the weight set would add
#: exactly nothing and would only make the arithmetic look approximate. The
#: home set is pinned to the LOT frame so "homes within 400 m" cannot drift
#: with the sampling density of the street frame.
HOME_FRAMES = ("lot",)


def load_home_points(con, haircut: dict, frames: tuple[str, ...] = HOME_FRAMES) -> pd.DataFrame:
    """Every LOT address in the warehouse, CITYWIDE (same edge-effect reason as
    load_supply_points), with `units` and the laundry-haircut evidence flag.

    `frames` is the D84 guard: these rows are the WEIGHTS -- the homes every
    other point's catchment sums -- and only the lot frame has residents.
    Street points are scored FOR their homes_400m (see `load_query_points`)
    and contribute ZERO to anybody else's.

    The evidence join is on BBL against analysis.address_laundry_evidence and
    fires only on a POSITIVE assertion from either source. The table may be
    absent on a partially-built database; that degrades to "no evidence
    anywhere", which is the conservative direction (a larger addressable pool),
    and the run report says so.
    """
    try:
        ev = con.execute("""
            SELECT DISTINCT bbl FROM analysis.address_laundry_evidence
            WHERE (source = 'll84'    AND (has_common_laundry OR has_in_unit_laundry))
               OR (source = 'listing' AND any_laundry_advertised)
        """).fetchdf()
        have_ev = True
    except Exception:                                       # pragma: no cover
        ev, have_ev = pd.DataFrame({"bbl": []}), False

    holes = ", ".join("?" for _ in frames)
    df = con.execute(f"""
        SELECT address_id, borough, bbl, lon, lat, COALESCE(units, 0) AS units
        FROM analysis.address
        WHERE lon IS NOT NULL AND lat IS NOT NULL
          AND COALESCE(frame, 'lot') IN ({holes})
    """, list(frames)).fetchdf()
    df["has_laundry_evidence"] = df["bbl"].isin(set(ev["bbl"].astype(str)))
    df["addressable_units"] = [
        addressable_units(u, e, haircut)
        for u, e in zip(df["units"], df["has_laundry_evidence"])
    ]
    df.attrs["have_evidence_table"] = have_ev
    return df


def load_query_points(con, boroughs: list[str]) -> pd.DataFrame:
    """Every scored point in scope, BOTH FRAMES (D84) -- the rows that RECEIVE
    homes_400m, the walk-shed area and the density.

    Deliberately separate from `load_home_points`, which is the weight set.
    Before D84 the two were the same query and the same list, which was right
    while every row was a residential lot. They are different questions now: a
    street point has no homes of its own to contribute and every reason to be
    told how many homes are within 400 m of it -- that catchment is exactly
    what makes a street in the Navy Yard rank below a street in Bushwick
    instead of above it (the censored, homes-free points then sort to the
    bottom by density with no gate and no special case).
    """
    holes = ", ".join("?" for _ in boroughs)
    return con.execute(f"""
        SELECT address_id, borough, COALESCE(frame, 'lot') AS frame, lon, lat
        FROM analysis.address
        WHERE lon IS NOT NULL AND lat IS NOT NULL AND borough IN ({holes})
    """, list(boroughs)).fetchdf()


# ------------------------------------------------------------- the engine

def node_weights(idx: dict, nodes_of: dict[str, np.ndarray],
                 weights: dict[str, np.ndarray], n_nodes: int) -> np.ndarray:
    """(n_nodes, k) weight matrix: each source point's weight added onto the
    graph node it snaps to, in `weights` key order.

    Points are ACCUMULATED, never deduplicated -- two laundromats at one
    intersection are two laundromats, and two buildings snapped to one node are
    two buildings' worth of homes.
    """
    keys = list(weights)
    W = np.zeros((n_nodes, len(keys)), dtype=np.float64)
    for k_i, key in enumerate(keys):
        np.add.at(W[:, k_i], nodes_of[key], weights[key])
    return W


def node_xy_m(G, idx: dict) -> np.ndarray:
    """(n_nodes, 2) projected metres (`SHED_CRS`) for every pruned graph node,
    in CSR index order -- the coordinate table `catchment_walkshed_km2` takes
    hulls in. OSMnx node `x`/`y` are lon/lat degrees; an area in degrees is not
    an area, so this projects once for the whole graph rather than per query."""
    nodes = list(G.nodes())
    lon = np.array([G.nodes[n]["x"] for n in nodes], dtype=np.float64)
    lat = np.array([G.nodes[n]["y"] for n in nodes], dtype=np.float64)
    x, y = Transformer.from_crs("EPSG:4326", SHED_CRS, always_xy=True).transform(lon, lat)
    xy = np.empty((len(idx), 2), dtype=np.float64)
    rows = np.array([idx[n] for n in nodes], dtype=np.int64)
    xy[rows, 0] = x
    xy[rows, 1] = y
    return xy


def hull_area_km2(pts: np.ndarray, min_km2: float = MIN_SHED_KM2) -> float:
    """Convex-hull area of `pts` (projected metres) in km2, floored at
    `min_km2`. Fewer than three points, or three collinear ones, is a
    degenerate hull with no area at all -- Qhull raises, and the answer is the
    floor, not zero: an address whose walk reaches two intersections still
    houses people, and a zero denominator would make its density infinite.

    Pure, no graph, no DB -- the property the tests lean on."""
    if len(pts) >= 3:
        try:
            return max(float(ConvexHull(pts).volume) / 1e6, min_km2)
        except (QhullError, ValueError):
            pass
    return min_km2


def catchment_sums(A, query_nidx: np.ndarray, W: np.ndarray,
                   radius_m: float = DEFAULT_RADIUS_M,
                   batch: int = BATCH) -> np.ndarray:
    """(n_query, k) sum of every weight within `radius_m` NETWORK metres of
    each query node, self included. Thin wrapper on
    `catchment_sums_and_shed`, kept so every caller that does not want the
    walk-shed area reads the same as before."""
    return catchment_sums_and_shed(A, query_nidx, W, radius_m=radius_m, batch=batch)[0]


def catchment_sums_and_shed(A, query_nidx: np.ndarray, W: np.ndarray,
                            radius_m: float = DEFAULT_RADIUS_M,
                            batch: int = BATCH,
                            xy_m: np.ndarray | None = None,
                            ) -> tuple[np.ndarray, np.ndarray | None]:
    """((n_query, k) weight sums, (n_query,) walk-shed km2 or None).

    Sourced from the QUERY nodes, not from the weights -- see the module
    docstring. Only the weight-bearing columns of the distance matrix are
    materialised for the product, which is what keeps the matmul at ~130 MFLOP
    a batch instead of ~660.

    Pass `xy_m` (the whole graph's projected coordinates, `node_xy_m`) to also
    get each query node's walk-shed area off the SAME Dijkstra rows: the
    reachable mask is already computed for the product, so the area is one
    convex hull per query and not a second sweep. `xy_m=None` skips it
    entirely and returns None in its place.

    Pure: takes a CSR matrix and arrays, touches no database, no cache and no
    graph pickle, so tests exercise it on a synthetic line graph where every
    distance is known by construction.
    """
    n_q, k = len(query_nidx), W.shape[1]
    out = np.zeros((n_q, k), dtype=np.float64)
    shed = None if xy_m is None else np.full(n_q, np.nan, dtype=np.float64)
    if n_q == 0:
        return out, shed
    wnz = np.flatnonzero(np.abs(W).sum(axis=1) > 0)
    if wnz.size == 0 and xy_m is None:
        return out, shed
    Wsub = W[wnz]
    for s in range(0, n_q, batch):
        chunk = query_nidx[s:s + batch]
        D = dijkstra(A, directed=False, indices=chunk, limit=float(radius_m))
        if wnz.size:
            M = (D[:, wnz] <= radius_m).astype(np.float64)
            out[s:s + batch] = M @ Wsub
        if shed is not None:
            reach = D <= radius_m
            for r in range(len(chunk)):
                shed[s + r] = hull_area_km2(xy_m[np.flatnonzero(reach[r])])
    return out, shed


# ------------------------------------------------------------ the baseline

#: The universe the baseline is FITTED over (D84). The norm every
#: `supply_ratio_vs_base` in the project is measured against was fitted on
#: 281,842 residential addresses; letting street points into it would move the
#: ruler itself -- 49k units-0 points, disproportionately on industrial and
#: park streets, would drag every category's median supply_per_1k down and make
#: every existing address look better supplied than it was yesterday, with no
#: supply having changed. The fit is pinned; the APPLY is not (a street point
#: gets a real ratio against the lot-frame norm, which is the comparison a
#: reader wants).
BASELINE_FIT_FRAMES = ("lot",)


def fit_baselines(long_df: pd.DataFrame, eligible_only: bool = True,
                  frames: tuple[str, ...] = BASELINE_FIT_FRAMES) -> dict:
    """Per-category median / p25 / p75 of `supply_per_1k`, plus the
    home-weighted `aggregate_per_1k`, over the addresses in `long_df`.

    `long_df` columns: category, supply_400m, homes_400m, supply_per_1k,
    eligible. Addresses with no homes within reach are excluded by
    construction (their supply_per_1k is None) -- the norm is measured over
    the blocks that have residents, not over parkland and rail yards.

    `eligible_only` is a NO-OP on any current run: D75 (2026-09-13, owner
    ruling) retired the eligibility gate, so the column is TRUE everywhere and
    the universe is every address with a denominator. That change of universe
    is why the baseline was re-fit once under D75 even though the supply set
    did not move: MN+BK n 267,329 -> 281,842. The parameter survives for a
    pre-D75 snapshot, whose FALSE rows belong to a different universe.

    Address-weighted, deliberately: a 400-unit tower and a rowhouse are one
    observation each. `aggregate_per_1k` is the home-weighted alternative and
    ships beside it precisely because the two disagree.

    A category with literally zero POIs anywhere in the swept set is SKIPPED
    -- absent from the returned dict entirely, not written as a fabricated
    `baseline: 0.0` (GTM-209, 2026-09-22; see the skip inline below).
    """
    df = long_df
    if eligible_only and "eligible" in df.columns:
        df = df[df["eligible"].astype(bool)]
    # D84: pin the fit universe to the LOT frame. A frame column that is
    # absent means a pre-D84 frame, which was all lots.
    if "frame" in df.columns:
        df = df[df["frame"].fillna("lot").isin(frames)]
    out: dict[str, dict] = {}
    for cat in ALLCATS:
        sub = df[df["category"] == cat]
        vals = pd.to_numeric(sub["supply_per_1k"], errors="coerce").dropna()
        homes = pd.to_numeric(sub["homes_400m"], errors="coerce")
        supply = pd.to_numeric(sub["supply_400m"], errors="coerce")
        # GTM-209 (2026-09-22): a category that WAS swept (rows exist for it
        # -- distinguishes this from `test_fit_baselines_emits_every_category
        # _even_with_no_rows`'s "not in scope at all" fixture, which still
        # gets an explicit None below) but has ZERO principled POIs anywhere
        # in that sweep (`supply.sum() == 0`, distinct from a category that
        # merely has a zero MEDIAN like tailor_repair below) has no evidence
        # to fit a baseline FROM -- a slug admitted to categories.py before
        # any adapter mapped it (bathhouse_sauna, GTM-198) is a registry
        # state, not a norm of "1,000 homes get zero of these". Writing
        # `baseline: 0.0` for it would be exactly the fabrication GTM-198's
        # own rule forbids ("a hand-written row would be a fabrication",
        # tests/test_category_registry.py); the category is skipped here and
        # simply absent from the YAML until it has real supply, matching
        # `UNFITTED_PENDING_INGEST` in tests/test_category_registry.py and
        # tests/test_supply_ratio.py::test_baseline_yaml_declares_its_radius_and_universe.
        # NOT the same test as `ships_as: signal` (address_gaps.py's
        # signal_categories()) -- this skip is about EVIDENCE, not about
        # whether the category is allowed to gate a card; once bathhouse_sauna
        # has even one POI, it gets a real baseline row like any other
        # category, signal or not.
        if len(sub) > 0 and float(supply.sum()) == 0.0:
            continue
        tot_h = float(homes.sum())
        med = float(vals.median()) if len(vals) else None
        agg = (float(supply.sum()) / tot_h * 1000.0) if tot_h > 0 else None
        # THE ESTIMATOR FALLBACK, declared per category rather than hidden.
        # `tailor_repair` has 966 principled POIs over MN+BK, so MORE THAN HALF
        # of addresses have none within 400 m and the address-weighted
        # median is exactly 0. A zero norm is not a norm: every ratio against it
        # is NULL and a whole category drops out of the ranking. Where that
        # happens the baseline falls back to the HOME-WEIGHTED aggregate (total
        # supply over total homes in scope), which is well defined whenever the
        # category exists at all. The two estimators are NOT interchangeable --
        # the aggregate is dominated by dense blocks and runs 15-50% higher in
        # every category here -- so the choice is stamped in `estimator` and a
        # reader can see which categories are being judged on which ruler.
        estimator = "median" if (med is not None and med > 0) else "aggregate_per_1k"
        out[cat] = {
            "n": len(vals),
            "median": med,
            "p25": float(vals.quantile(0.25)) if len(vals) else None,
            "p75": float(vals.quantile(0.75)) if len(vals) else None,
            "aggregate_per_1k": agg,
            "estimator": estimator,
            "baseline": med if estimator == "median" else agg,
        }
    return out


def baseline_of(cat_doc: dict | None) -> float | None:
    """The one number a ratio divides by, for one category. Reads `baseline`
    (written by fit_baselines with its estimator already resolved) and falls
    back to `median` for a YAML written before the estimator field existed."""
    if not cat_doc:
        return None
    b = cat_doc.get("baseline", cat_doc.get("median"))
    return None if b is None or not b > 0 else float(b)


_BASELINE_HEADER = """\
# Supply-intensity baselines -- the MN+BK norm each address's supply_per_1k is
# divided by (red-team finding 2, 2026-09-11).
# GENERATED by `loci supply-ratio --fit-baseline`. Do not hand-edit.
#
# `median` is the address-weighted median of supply_per_1k (principled POIs of
# the category within 400 m network metres, per 1,000 residential units within
# the same 400 m) over EVERY address in `boroughs` that has at least one home
# within reach. Before D75 (2026-09-13) the universe was the subset the
# eligibility gate admitted; the owner retired the gate, so the baseline was
# re-fit once on the gate-free universe (MN+BK n 267,329 -> 281,842) with the
# supply set itself unchanged. Since D84 (2026-09-13) analysis.address holds TWO
# sampling frames and the fit universe is pinned to `frame='lot'`: a street
# midpoint has no residents, and letting 49k units-0 points into the fit would
# move the ruler every existing ratio is measured against without any supply
# having changed. `aggregate_per_1k` is the home-weighted alternative --
# total supply over total homes -- and is NOT what the ratio divides by; it is
# here because the two disagree and the gap is informative.
#
# REVEALED SUPPLY (D6). This is what New York BUILT, not what New York needs.
# A ratio of 1.0 means "normal for this city". It is not a sufficiency test,
# and under-provision is correlated with race net of income (Meltzer &
# Schuetz), so a low ratio measures what is there and never proves unmet demand.
#
# `supply_asof` is the date the open/closed predicate was EVALUATED at
# (analysis.supply_asof, owner ruling 2026-09-16) -- NOT `asof`, which is the
# wall-clock day the fit ran. Licences lapse and inspection evidence ages, so
# the same warehouse yields a different supply set at a different as-of date;
# pinning it is what keeps `supply_hash` moving only on real evidence writes.
# Advance it with `loci supply-asof advance`, then re-run the canonical order.
#
# `supply_hash` is score/supply.supply_hash at fit time. analysis.poi_supply is
# a VIEW: it moves when dedup is re-run or an anchor is loaded, and a baseline
# fitted on a different supply set is not comparable to a ratio computed on
# this one. tests/test_supply_ratio.py fails when the two drift.
"""


def save_baselines(doc: dict, path: pathlib.Path | None = None) -> pathlib.Path:
    p = path or BASELINE_PATH
    p.write_text(_BASELINE_HEADER + yaml.safe_dump(doc, sort_keys=False, width=88))
    return p


def load_baselines(path: pathlib.Path | None = None) -> dict:
    p = path or BASELINE_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"{p} does not exist. Run `loci supply-ratio --fit-baseline` once to "
            f"create it; a ratio has no meaning without the norm it divides by.")
    return yaml.safe_load(p.read_text())


# -------------------------------------------------------------- the build

def compute_supply_ratio(
    con,
    boroughs: list[str],
    radius_m: float = DEFAULT_RADIUS_M,
    supply_set: str = DEFAULT_SUPPLY_SET,
    graph_path: pathlib.Path = GRAPH_PATH,
    baselines: dict | None = None,
    haircut: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(address frame, category long frame, report). READ-ONLY on the warehouse.

    The address frame carries ADDRESS_RATIO_COLUMNS; the long frame carries one
    row per (address, category) with CATEGORY_RATIO_COLUMNS plus the join keys
    and `eligible`/`homes_400m` for the baseline fit. `baselines=None` means
    "compute supply_per_1k but leave supply_ratio_vs_base NULL", which is the
    --fit-baseline path: the norm cannot be read off a table that does not
    exist yet.
    """
    haircut = haircut or load_haircut()
    pois = load_supply_points(con, supply_set)
    if pois.empty:
        raise RuntimeError(
            f"supply-ratio: analysis.poi_supply has no rows in the '{supply_set}' "
            f"set. Writing zeros onto every address would read as 'there is no "
            f"retail anywhere in New York' -- a confident false negative.")
    homes = load_home_points(con, haircut)
    # D84: the WEIGHTS are lot rows (homes); the QUERY set is every scored
    # point in scope, both frames. Before D84 one query served both roles.
    query = load_query_points(con, boroughs)

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)
    n_nodes = A.shape[0]

    poi_nodes = ox.distance.nearest_nodes(
        Gp, X=pois["lon"].tolist(), Y=pois["lat"].tolist())
    poi_nidx = np.array([idx[n] for n in np.atleast_1d(poi_nodes)], dtype=np.int64)
    home_nodes = ox.distance.nearest_nodes(
        Gp, X=homes["lon"].tolist(), Y=homes["lat"].tolist())
    home_nidx = np.array([idx[n] for n in np.atleast_1d(home_nodes)], dtype=np.int64)
    query_nodes = ox.distance.nearest_nodes(
        Gp, X=query["lon"].tolist(), Y=query["lat"].tolist())
    query_nidx_all = np.array([idx[n] for n in np.atleast_1d(query_nodes)], dtype=np.int64)

    nodes_of, weights = {}, {}
    cat_arr = pois["category"].to_numpy()
    for cat in ALLCATS:
        m = cat_arr == cat
        nodes_of[cat] = poi_nidx[m]
        weights[cat] = np.ones(int(m.sum()), dtype=np.float64)
    nodes_of["homes"] = home_nidx
    weights["homes"] = homes["units"].to_numpy(dtype=np.float64)
    nodes_of["addressable"] = home_nidx
    weights["addressable"] = homes["addressable_units"].to_numpy(dtype=np.float64)

    keys = [*ALLCATS, "homes", "addressable"]
    W = node_weights(idx, nodes_of, {k: weights[k] for k in keys}, n_nodes)

    scope = query.reset_index(drop=True)
    scope_nidx = query_nidx_all
    uniq, inv = np.unique(scope_nidx, return_inverse=True)
    acc_u, shed_u = catchment_sums_and_shed(A, uniq, W, radius_m=radius_m,
                                            xy_m=node_xy_m(Gp, idx))
    acc, shed = acc_u[inv], shed_u[inv]

    hash_now = supply_hash(con, supply_set)
    run_at = dt.datetime.now()
    # Owner ruling 2026-09-13, "rank by density": homes per km2 of the walk
    # the address can actually make. Both the numerator and the denominator
    # come off the same sweep, so they can never be measured over different
    # reachable sets.
    homes_400m = np.rint(acc[:, keys.index("homes")]).astype("int64")
    addr = pd.DataFrame({
        "address_id": scope["address_id"],
        "borough": scope["borough"],
        "homes_400m": homes_400m,
        "walkshed_km2_400m": shed,
        "density_400m": homes_400m / shed,
        "addressable_homes_400m_laundry": acc[:, keys.index("addressable")],
        "supply_ratio_radius_m": float(radius_m),
        "supply_ratio_supply_hash": hash_now,
        "supply_ratio_run_at": run_at,
    })

    base = (baselines or {}).get("categories", {})
    frames = []
    homes_col = addr["homes_400m"].to_numpy(dtype=np.float64)
    # The screen's OWN eligibility gate, read once and never recomputed: this
    # module must not form its own opinion about which addresses count.
    elig = scope["address_id"].map(_eligible_universe(con, boroughs)).fillna(False)
    for cat in ALLCATS:
        sup = np.rint(acc[:, keys.index(cat)]).astype("int64")
        with np.errstate(divide="ignore", invalid="ignore"):
            p1k = np.where(homes_col > 0, sup / np.maximum(homes_col, 1e-9) * 1000.0, np.nan)
        b = baseline_of(base.get(cat))
        rvb = (p1k / b) if b is not None else np.full(len(sup), np.nan)
        frames.append(pd.DataFrame({
            "address_id": scope["address_id"],
            "borough": scope["borough"],
            # D84: carried so `fit_baselines` can pin its universe to the lot
            # frame without a second query, and so any reader of the long frame
            # can slice it the same way.
            "frame": scope["frame"],
            "category": cat,
            "eligible": elig.to_numpy(),
            "homes_400m": addr["homes_400m"],
            "supply_400m": sup,
            "supply_per_1k": p1k,
            "supply_ratio_vs_base": rvb,
        }))
    long_df = pd.concat(frames, ignore_index=True)

    report = {
        "boroughs": list(boroughs),
        "radius_m": float(radius_m),
        "supply_set": supply_set,
        "supply_hash": hash_now,
        "graph_version": graph_version(graph_path),
        "pois": len(pois),
        "home_rows": len(homes),
        "home_frames": list(HOME_FRAMES),
        "addresses": len(addr),
        # D84: how much of the swept set is each frame. The street frame
        # RECEIVES homes_400m/walkshed/density and CONTRIBUTES zero homes.
        "addresses_by_frame": scope["frame"].value_counts().to_dict(),
        "query_nodes": int(uniq.size),
        "shed_crs": SHED_CRS,
        "shed_km2_p10": float(np.nanpercentile(shed, 10)) if len(shed) else None,
        "shed_km2_median": float(np.nanmedian(shed)) if len(shed) else None,
        "shed_km2_p90": float(np.nanpercentile(shed, 90)) if len(shed) else None,
        "shed_at_floor": int((shed <= MIN_SHED_KM2).sum()),
        "density_median": float(np.nanmedian(addr["density_400m"])) if len(addr) else None,
        "have_evidence_table": bool(homes.attrs.get("have_evidence_table", False)),
        "evidence_bbls": int(homes["has_laundry_evidence"].sum()),
        "haircut_version": haircut.get("version"),
        "baseline_hash": (baselines or {}).get("supply_hash"),
        "run_at": run_at.isoformat(timespec="seconds"),
    }
    return addr, long_df, report


def _eligible_universe(con, boroughs: list[str]) -> dict:
    """address_id -> eligible, straight off analysis.address. The screen's own
    D48 gate, READ and never recomputed."""
    holes = ", ".join("?" for _ in boroughs)
    df = con.execute(
        f"SELECT address_id, COALESCE(eligible, FALSE) AS eligible "
        f"FROM analysis.address WHERE borough IN ({holes})", list(boroughs)
    ).fetchdf()
    return dict(zip(df["address_id"], df["eligible"].astype(bool)))


# --------------------------------------------------------------- the write

def _guard(cols: list[str], table: str) -> None:
    """Refuse to write if the SET list touches anything another module owns.
    Belt and braces; tests/test_supply_ratio.py is the real guard."""
    forbidden = set(ADDRESS_SCREEN_COLUMNS)
    try:
        from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
        from loci.model.address_gaps import ADDRESS_CATEGORY_SCREEN_COLUMNS
        from loci.model.dev_pipeline import PIPELINE_COLUMNS
        from loci.model.storefronts import AGE_FIT_COLUMNS, STOREFRONT_COLUMNS
        forbidden |= set(PIPELINE_COLUMNS) | set(STOREFRONT_COLUMNS)
        forbidden |= set(AGE_FIT_COLUMNS) | set(DEMAND_ANNOTATION_COLUMNS)
        forbidden |= set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
    except ImportError:                                     # pragma: no cover
        pass
    overlap = sorted(set(cols) & forbidden)
    if overlap:
        raise RuntimeError(f"supply-ratio would clobber {table} columns: {overlap}")


def write_address_measures(con, df: pd.DataFrame, boroughs: list[str]) -> int:
    """UPDATE-only on analysis.address. RESET then UPDATE, for the reason every
    sibling module resets: an address whose homes_400m changes to NULL-worthy
    (it left scope, the graph changed) must not keep last run's number, and
    UPDATE has no DELETE to fall back on."""
    if not boroughs:
        return 0
    _guard(ADDRESS_RATIO_COLUMNS, "analysis.address")
    holes = ", ".join("?" for _ in boroughs)
    reset = ", ".join(f"{c} = NULL" for c in ADDRESS_RATIO_COLUMNS)
    con.execute(f"UPDATE analysis.address SET {reset} WHERE borough IN ({holes})",
                list(boroughs))
    if df.empty:
        return 0
    con.register("_sr_addr", df)
    try:
        sets = ", ".join(f"{c} = _sr_addr.{c}" for c in ADDRESS_RATIO_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address AS a SET {sets}
            FROM _sr_addr
            WHERE a.address_id = _sr_addr.address_id AND a.borough = _sr_addr.borough
        """)
    finally:
        con.unregister("_sr_addr")
    return len(df)


def write_category_measures(con, df: pd.DataFrame, boroughs: list[str]) -> int:
    """UPDATE-only on analysis.address_category. Same RESET-then-UPDATE."""
    if not boroughs:
        return 0
    _guard(CATEGORY_RATIO_COLUMNS, "analysis.address_category")
    holes = ", ".join("?" for _ in boroughs)
    reset = ", ".join(f"{c} = NULL" for c in CATEGORY_RATIO_COLUMNS)
    con.execute(f"UPDATE analysis.address_category SET {reset} WHERE borough IN ({holes})",
                list(boroughs))
    if df.empty:
        return 0
    payload = df[["address_id", "borough", "category", *CATEGORY_RATIO_COLUMNS]]
    con.register("_sr_cat", payload)
    try:
        sets = ", ".join(f"{c} = _sr_cat.{c}" for c in CATEGORY_RATIO_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address_category AS ac SET {sets}
            FROM _sr_cat
            WHERE ac.address_id = _sr_cat.address_id
              AND ac.borough = _sr_cat.borough
              AND ac.category = _sr_cat.category
        """)
    finally:
        con.unregister("_sr_cat")
    return len(payload)


def build_supply_ratio(
    con,
    boroughs: list[str],
    radius_m: float = DEFAULT_RADIUS_M,
    supply_set: str = DEFAULT_SUPPLY_SET,
    graph_path: pathlib.Path = GRAPH_PATH,
    fit_baseline: bool = False,
    baseline_path: pathlib.Path | None = None,
    dry_run: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """compute (+ optionally re-fit the baseline) + write.

    `--fit-baseline` runs the sweep ONCE, fits the norm on that run's own
    output, writes the YAML, and then applies the norm to the same frame. It
    does NOT sweep twice: the ratio is deterministic given supply_per_1k and
    the medians.
    """
    haircut = load_haircut()
    baselines = None if fit_baseline else load_baselines(baseline_path)
    addr, long_df, report = compute_supply_ratio(
        con, boroughs, radius_m=radius_m, supply_set=supply_set,
        graph_path=graph_path, baselines=baselines, haircut=haircut)

    if fit_baseline:
        cats = fit_baselines(long_df)
        doc = {
            "supply_hash": report["supply_hash"],
            "supply_set": supply_set,
            # `asof` is the WALL-CLOCK day the fit RAN -- provenance only.
            # `supply_asof` is the date the open/closed predicate was EVALUATED
            # at, read from analysis.supply_asof (owner ruling 2026-09-16).
            # They are not the same thing and conflating them is how the pin
            # comes undone: a re-fit run on 2026-09-20 against a pin held at
            # 2026-09-15 is a legitimate, reproducible state.
            # tests/test_supply_ratio.py's drift test hashes at `supply_asof`.
            "asof": dt.date.today().isoformat(),
            "supply_asof": supply_asof_mod.read(con).isoformat(),
            "radius_m": float(radius_m),
            "boroughs": list(boroughs),
            # D75: the eligibility gate is retired, so this is every address
            # with a denominator. The string is stamped into the YAML and is
            # how a later reader tells a post-D75 baseline from a pre-D75 one.
            # D84: and only the LOT frame -- `fit_baselines` filters on it, so
            # the string and the fit cannot disagree. `n_addresses` is the fit
            # universe, not the swept universe: the sweep now also covers the
            # street frame, which receives ratios and never moves the norm.
            "universe": "all LOT addresses with homes_400m > 0",
            # Every category's `n` is the same number -- supply_per_1k is NULL
            # exactly where homes_400m is 0, which does not vary by category --
            # so the max IS the fit universe, read off the fit itself rather
            # than recomputed from a second predicate that could drift from it.
            "n_addresses": max((v["n"] for v in cats.values()), default=0),
            "n_swept": len(addr),
            "graph_version": report["graph_version"],
            "categories": cats,
        }
        if not dry_run:
            report["baseline_written"] = str(save_baselines(doc, baseline_path))
        baselines = doc
        report["baseline_hash"] = doc["supply_hash"]
        base_med = {c: baseline_of(v) for c, v in cats.items()}
        long_df["supply_ratio_vs_base"] = [
            ratio_vs_base(v, base_med.get(c))
            for v, c in zip(long_df["supply_per_1k"], long_df["category"])
        ]

    report["baselines"] = (baselines or {}).get("categories", {})
    if not dry_run:
        report["_written_address"] = write_address_measures(con, addr, boroughs)
        report["_written_category"] = write_category_measures(con, long_df, boroughs)
    return addr, long_df, report


# ------------------------------------------------------------- reporting

def box_summary(long_df: pd.DataFrame, addr_xy: pd.DataFrame,
                lat: tuple[float, float], lon: tuple[float, float],
                baselines: dict, eligible_only: bool = True,
                lead_only: bool = False) -> pd.DataFrame:
    """The deliverable table for one lat/lon box: per category, the median
    supply_400m, median homes_400m, median supply_per_1k, the baseline and the
    ratio of the two medians.

    `addr_xy` carries address_id, lat, lon, eligible and (optionally)
    lead_category. Pure -- no DB -- so the same function serves the CLI, the
    tests and any ad-hoc box.

    The reported ratio is median(supply_per_1k) / baseline, NOT
    median(supply_ratio_vs_base); the two differ only by the order of the
    median and the divide, and the first is the one that can be read straight
    off the two columns beside it in the table.
    """
    inbox = addr_xy[(addr_xy["lat"].between(*lat)) & (addr_xy["lon"].between(*lon))]
    if eligible_only and "eligible" in inbox.columns:
        inbox = inbox[inbox["eligible"].astype(bool)]
    ids = set(inbox["address_id"])
    sub = long_df[long_df["address_id"].isin(ids)]
    rows = []
    for cat in ALLCATS:
        s = sub[sub["category"] == cat]
        if lead_only:
            leads = set(inbox.loc[inbox.get("lead_category", "") == cat, "address_id"])
            s = s[s["address_id"].isin(leads)]
        p1k = pd.to_numeric(s["supply_per_1k"], errors="coerce").dropna()
        b = baseline_of((baselines or {}).get(cat))
        med = float(p1k.median()) if len(p1k) else None
        rows.append({
            "category": cat,
            "tier": CATEGORIES[cat].tier,
            "n_addresses": int(s["address_id"].nunique()),
            "supply_400m_median": float(pd.to_numeric(s["supply_400m"]).median())
                                  if len(s) else None,
            "homes_400m_median": float(pd.to_numeric(s["homes_400m"]).median())
                                 if len(s) else None,
            "supply_per_1k": med,
            "baseline_per_1k": b,
            "ratio": ratio_vs_base(med, b),
        })
    out = pd.DataFrame(rows)
    return out.sort_values("ratio", na_position="last").reset_index(drop=True)
