"""Address-level gap screen (per residential PLUTO lot -- D38: one tax lot
with UnitsRes > 0 is one "address" for this purpose).

SUPERSEDES the old rule entirely (CHECKPOINT D33/D38/D39/D41): a single
shared 800 m walk window plus an 80%-prevalence "expected" test, the same
design defect model/gaps.py's `rule="window"` has (QUESTIONS D6/CHECKPOINT
D33) -- tightening the window could make a gap disappear, because "expected"
was re-derived from the whole city on every call. The old 800m/80% code path
is deleted here, not kept behind a flag.

The new rule, at address grain:

  - THE ELIGIBILITY GATE IS RETIRED (D75, 2026-09-13, owner ruling). Every
    residential address is in the universe. The owner's words: "I 100%
    vehemently disagree with 'which addresses count at all'. If an address is
    truly in a super underdeveloped area, this would completely not count
    it." The gate existed for one reason -- D39 found the LITERAL port
    (eligible iff within *reach* of >= 12/15) violated monotonicity, because
    tightening a reach dropped addresses out of eligibility faster than they
    gained gaps; a FIXED, reach-independent presence test restored it. With
    NO gate at all that role is filled trivially: the gap set is
    `ratio > 1` over every address, `ratio` reads only that address's own
    nearest_m against a reach that is fixed input, so tightening a reach can
    only ADD pairs (tests/test_address_gaps.py part b, now asserted over the
    whole universe). `eligible` survives as a column, always TRUE, for
    schema and query compatibility; `present_count` survives as the
    informational count it always was (categories within `WINDOW_M`), and is
    a candidate RANKING feature, never a filter.

  - For every address, `ratio[c] = nearest_m[c] / reach[c]` is a CONTINUOUS
    score per category (D39), not a binary flag: `gap_score` is its row-max,
    `lead_category` its argmax (ties -> the LARGER raw nearest_m, since a
    farther near-miss is the more conspicuous absence), `lead_excess_m` is
    nearest - reach at the lead, and `n_missing` counts categories with
    ratio > 1.

  - RIGHT-CENSORING IS NOW VISIBLE, and is flagged rather than smoothed
    (D51 finding, exposed by D75). `nearest_m` is the output of a Dijkstra
    capped at `CAP_M` (2,400 m, score/access.DIST_LIMIT): a category with
    NOTHING within the cap is recorded AT the cap, so its ratio is
    `CAP_M / reach[c]` -- a floor, not a measurement. The gate used to hide
    most of these, because an address with several unreachable categories
    usually failed `present_count >= 12`. It no longer does. The handling is
    explicitly NOT a new rule on the score: `gap_score` keeps the same
    monotone, continuous definition (a censored ratio is still the smallest
    value that category's ratio could take, so the ordering is conservative,
    never inflated). Instead the fact is CARRIED: `censored` per (address,
    category) and `lead_censored` on the address, so a ranking, a card or a
    popup can say "nearest X beyond 2,400 m -- distance not measured"
    instead of printing a number that is really the cap. `CAP_M` is NOT
    changed here.

  - `units_capped` clips units at `UNITS_CAP` (500/lot) for any unit-weighted
    ranking: D39 found Co-op City-scale lots (~10k units) would otherwise
    dominate every cluster ranking on their own. Raw `units` is kept too.

  - `gap_score > 1` addresses that share a `lead_category` and sit
    within `CLUSTER_RADIUS_M` (200 m) of each other are grouped into one
    `cluster_id` (single-linkage / DBSCAN-like, eps=200m, min_samples=1) --
    the action signal is a CLUSTER of addresses missing the same business,
    not any one address on its own.

NO DEMOGRAPHICS HERE (D56, 2026-09-09). An earlier version of this module
copied all 36 analysis.hex_demographics measure columns onto every address row
by CONTAINING res-9 hex. That is removed: analysis.address_demographics is the
single canonical address-grain demographic carrier and takes each value
DIRECTLY from the lot's own 2020 census tract (a BBL lookup on PLUTO's
bct2020), so it is strictly less modelled than a tract -> hex apportionment
followed by a hex -> address containment step. Two median_hh_income values for
one address, differing, was the concrete harm. `h3_index` is still computed and
persisted -- it is the borough/NTA join key and lets an address be rolled back
up to the grid -- but nothing demographic rides on it. Join
analysis.address_demographics on address_id.

Reuses the conveniences engine's METHOD (model/conveniences.py's
`compute_address_convenience`: one multi-source Dijkstra per category via
score/access.py's `_prune`/`_to_csr`, 15 passes total, independent of address
count) via `_dijkstra_per_category` below -- but does NOT call
`compute_address_convenience` itself, because that function materializes two
15-key python dicts PER ADDRESS; at NYC's ~767k residential addresses that is
tens of millions of short-lived dicts for data that is one (n, 15) float
array. `address_nearest_matrix` is the shared entry point: it caches the
per-NODE distance matrix (every pruned graph node's nearest-category
distance) as parquet under `data/interim/`, keyed by (graph_version,
supply_set, supply_hash, POI count) -- independent of which addresses are
queried, so a
`--borough MN` smoke run and a later `--borough ALL` run share one cache file
instead of repeating 15 citywide Dijkstra passes.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import pickle

import numpy as np
import osmnx as ox
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from loci.categories import CATEGORIES
from loci.model.conveniences import ALLCATS, graph_version, signal_categories
from loci.reach import load_reach
from loci.score.access import DIST_LIMIT, MIN_COMPONENT, _prune, _to_csr
from loci.score.supply import DEFAULT_SUPPLY_SET, canonical_poi_sql, supply_hash
from loci.score.walkgraph import OUT as GRAPH_PATH

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
INTERIM_DIR = REPO_ROOT / "data" / "interim"

WINDOW_M = 800.0        # gaps.py's own window-rule presence definition (10 min @ 80 m/min)
MIN_PRESENT = 12        # RETIRED as a gate (D75); kept so present_count keeps its old meaning
UNITS_CAP = 500.0       # D39: cap per-lot units for any unit-weighted ranking
CLUSTER_RADIUS_M = 200.0
#: The Dijkstra's own right-censoring point (score/access.DIST_LIMIT, 30 min
#: walk). A nearest_m AT this value means "nothing of that category was found
#: within 2,400 m", not "it is 2,400 m away". Aliased here rather than
#: re-declared so there is exactly ONE cap in the codebase (D75).
CAP_M = DIST_LIMIT

#: analysis.address's column list, DDL order (sql/002_schema.sql). Identity +
#: the summary of the screen + ONE set of provenance stamps -- everything
#: else on compute_address_gaps' wide working frame is a per-category pair
#: that belongs on analysis.address_category instead. Declared once here so
#: write_address_gaps' split and address_gaps_view_sql's SELECT list can
#: never quietly diverge from the DDL.
ADDRESS_COLUMNS = [
    "address_id", "bbl", "lon", "lat", "units", "units_capped",
    "nta_code", "neighborhood", "borough", "h3_index",
    "present_count", "eligible", "gap_score", "lead_category",
    "lead_excess_m", "n_missing", "cluster_id",
    "reach_source", "reach_hash", "graph_version",
    "supply_set", "supply_hash", "run_at",
    # D75, APPENDED (the column is added by an ALTER at the tail of
    # sql/002_schema.sql, so it is last in DDL order too): the lead
    # category's nearest_m is AT the 2,400 m Dijkstra cap, i.e. gap_score is
    # a floor rather than a measurement for this address.
    "lead_censored",
    # D84, APPENDED for the same reason: which SAMPLING FRAME this row came
    # from. 'lot' is a residential PLUTO tax lot (D38, bbl set, units > 0);
    # 'street' is a point every 100 m along a kept CSCL street segment
    # (sources/cities/nyc/street_centerline.py, bbl NULL, units 0). The four
    # after it describe a street row and are NULL on a lot row.
    "frame", "frontage_m", "street_name", "frame_source", "frame_vintage",
]

#: The two values `frame` may take. Declared here rather than as a DDL CHECK
#: because DuckDB cannot ALTER-ADD a CHECK to an existing table; the domain is
#: asserted by tests/test_street_frame.py on a real warehouse.
FRAMES = ("lot", "street")
LOT_FRAME = "lot"
STREET_FRAME = "street"

#: analysis.address_category's SCREEN-owned columns (D38/D58 split) -- the
#: ones write_address_gaps is allowed to touch. The demand annotation columns
#: on the same table (demand_class, elasticity, income_ratio, ...) are NOT
#: here: model/address_demand.py owns those and issues UPDATE only, per the
#: D57/D58 non-filtering guarantee -- this writer never names them, so it
#: cannot accidentally clobber an annotation with a plain re-run of the screen.
ADDRESS_CATEGORY_SCREEN_COLUMNS = [
    "address_id", "borough", "category", "nearest_m", "ratio", "is_lead", "eligible",
    # D75, APPENDED: nearest_m is AT the 2,400 m cap -- there is no location
    # of this category within the cap, so `nearest_m` and `ratio` are floors.
    "censored",
    # D84, APPENDED: denormalised from analysis.address for the same reason
    # `is_lead`/`eligible`/`censored` are (D61) -- a reader must be able to
    # slice the long table by frame without a join, and every "lot only"
    # aggregate over this table is one WHERE clause.
    "frame",
]


# --------------------------------------------------------------- the engine

class EmptyCategoryError(RuntimeError):
    """A registered category with NO POI in the supply set (docs/CATEGORY-
    EXPANSION.md §1.2, the fail-open trap made fail-closed here)."""


def _refuse_empty_categories(by_cat: dict[str, list]) -> None:
    """Refuse to screen when a FILTERING category in ALLCATS has zero supply
    POIs.

    Such a category sits at `cap_m` for EVERY address, so `nearest_m /
    reach_m` is its maximum everywhere: it becomes `lead_category` for the
    whole city and `n_missing` gains one at every address -- silently, because
    nothing else in this module distinguishes "no bathhouse within reach" from
    "no adapter has emitted this slug yet". That is a registry state (a 16th
    slug landed in categories.py before any ingest mapped it), not a
    measurement, and the screen must say so rather than rank on it. The pure
    engine `_address_nearest_matrix_from_graph` is NOT guarded: its callers
    pass synthetic POI sets that deliberately leave categories empty.

    GTM-209 (2026-09-22): a `ships_as: signal` category (`signal_categories()`)
    is EXEMPT from this guard. The signal-vs-filter rule
    (docs/CATEGORY-EXPANSION.md §4) already excludes a signal slug from every
    aggregate this guard exists to protect (`gap_score`, `lead_category`,
    `n_missing` -- see `compute_gap_metrics`), so a signal category sitting at
    zero supply is the expected, harmless pre-ingest state, not the silent
    failure mode this guard was built to catch. Once a signal category is
    ingested it is still exempt -- the exemption is a property of `ships_as`,
    not of the POI count -- because the charter never lets it gate a card
    regardless of how much supply eventually exists.
    """
    signal = signal_categories()
    empty = [c for c in ALLCATS if c not in signal and not by_cat.get(c)]
    if empty:
        raise EmptyCategoryError(
            f"{len(empty)} of {len(ALLCATS)} categories have no POI in the supply "
            f"set: {', '.join(empty)}. A category with no supply would be missing "
            "at every address and lead every card; that is a registry state, not a "
            "gap. Ingest a source that maps the slug (and re-record supply_hash) "
            "or remove it from categories.py before running the screen."
        )


def _dijkstra_per_category(A, idx: dict, N: int, by_cat: dict[str, list[tuple[float, float]]],
                            G, cap_m: float) -> np.ndarray:
    """(N, 15) network distance from EVERY graph node to the nearest canonical
    POI of each category (ALLCATS order), censored at `cap_m` for a category
    with nothing reachable. The one Dijkstra-per-category loop, shared by the
    pure test engine (`_address_nearest_matrix_from_graph`) and the cached,
    DB-backed engine (`address_nearest_matrix`) -- so there is exactly one
    place in this module that calls `dijkstra`."""
    node_m = np.full((N, len(ALLCATS)), cap_m, dtype=np.float64)
    for ci, cat in enumerate(ALLCATS):
        pts = by_cat.get(cat) or []
        if not pts:
            continue
        nodes = ox.distance.nearest_nodes(G, X=[p[0] for p in pts], Y=[p[1] for p in pts])
        src = np.unique([idx[n] for n in nodes])
        d = dijkstra(A, directed=False, indices=src, min_only=True, limit=cap_m)
        node_m[:, ci] = np.where(np.isfinite(d), d, cap_m)
    return node_m


def _address_nearest_matrix_from_graph(
    G,
    addresses: list[tuple[str, float, float]],
    pois: list[tuple[str, float, float]],
    cap_m: float = DIST_LIMIT,
    min_component: int = MIN_COMPONENT,
) -> np.ndarray:
    """Pure engine, no DB, no cache: (n_addresses, 15) network distance to the
    nearest POI per category (ALLCATS order). addresses: [(id, lon, lat)];
    pois: [(category, lon, lat)]. This is what tests/test_address_gaps.py
    exercises directly on a tiny synthetic graph -- the DB-free half that
    `address_nearest_matrix` wraps with a real graph, a DB read of
    staging.poi, and a parquet cache.
    """
    G = _prune(G, min_component)
    A, idx = _to_csr(G)
    N = A.shape[0]

    by_cat: dict[str, list[tuple[float, float]]] = {c: [] for c in ALLCATS}
    for cat, lon, lat in pois:
        if cat in by_cat:
            by_cat[cat].append((lon, lat))

    node_m = _dijkstra_per_category(A, idx, N, by_cat, G, cap_m)

    addr_nodes = ox.distance.nearest_nodes(G, X=[a[1] for a in addresses], Y=[a[2] for a in addresses])
    addr_nidx = np.array([idx[n] for n in addr_nodes])
    return node_m[addr_nidx]


def address_nearest_matrix(
    con,
    addresses_df: pd.DataFrame,
    graph_path: pathlib.Path = GRAPH_PATH,
    cache_dir: pathlib.Path = INTERIM_DIR,
    supply_set: str = DEFAULT_SUPPLY_SET,
) -> tuple[np.ndarray, str, str]:
    """(n_addresses, 15) network distance to the nearest canonical POI per
    category (ALLCATS order) for every row of `addresses_df` (columns lon,
    lat). Loads the walk graph once, computes (or loads from cache) the
    per-NODE distance table, then just snaps + gathers for these addresses --
    the 15 citywide Dijkstra passes run once per (graph_version, canonical
    POI count), not once per call. Returns (matrix, graph_version, cache_key).
    """
    gver = graph_version(graph_path)
    # Cache key must fold in the SUPPLY SET, not just the POI count: two sets
    # can coincidentally have the same cardinality per category while pointing
    # at different storefronts, and serving one run's distance matrix to the
    # other would be a silent, invisible error. supply_hash() folds in the set
    # name, the dedup radii, the qualifying-anchor set and the per-category
    # counts, so any of those changing invalidates the cache.
    shash = supply_hash(con, supply_set)
    n_poi = con.execute(
        f"SELECT count(*) FROM ({canonical_poi_sql(supply_set, 's.poi_id')})"
    ).fetchone()[0]
    key = hashlib.sha256(f"{gver}:{supply_set}:{shash}:{n_poi}".encode()).hexdigest()[:16]
    cache_dir = pathlib.Path(cache_dir)
    cache_path = cache_dir / f"node_nearest_m_{key}.parquet"

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    G = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(G)
    N = A.shape[0]

    cached = pd.read_parquet(cache_path) if cache_path.exists() else None
    if cached is not None and len(cached) == N:
        node_m = cached[[f"d_{c}" for c in ALLCATS]].to_numpy(dtype=np.float64)
    else:
        pois = con.execute(canonical_poi_sql(supply_set)).fetchall()
        by_cat: dict[str, list[tuple[float, float]]] = {c: [] for c in ALLCATS}
        for cat, lon, lat in pois:
            if cat in by_cat:
                by_cat[cat].append((lon, lat))
        _refuse_empty_categories(by_cat)
        node_m = _dijkstra_per_category(A, idx, N, by_cat, G, DIST_LIMIT)
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({f"d_{c}": node_m[:, i] for i, c in enumerate(ALLCATS)}).to_parquet(
            cache_path, index=False
        )

    addr_nodes = ox.distance.nearest_nodes(G, X=addresses_df["lon"].tolist(), Y=addresses_df["lat"].tolist())
    addr_nidx = np.array([idx[n] for n in addr_nodes])
    return node_m[addr_nidx], gver, key


# ------------------------------------------------------------ pure metrics

def compute_gap_metrics(M: np.ndarray, reach: dict[str, float],
                         window_m: float = WINDOW_M, min_present: int = MIN_PRESENT,
                         cap_m: float = CAP_M,
                         signal_cats: frozenset[str] | None = None,
                         ) -> dict[str, np.ndarray]:
    """Pure numpy classification from an (n_addresses, 15) nearest-metres
    matrix (ALLCATS column order) and a complete {category: reach_m} dict.
    Fails closed (mirrors loci.reach._check_reach_complete) if `reach` is
    missing a category.

    D75 -- THE GATE IS GONE. `eligible` is TRUE for every row and is kept
    only so that every stored column, view and query written against the
    pre-D75 shape keeps working. Nothing here filters: `gap_score` (row-max
    ratio), `lead_category` (argmax ratio, ties -> larger nearest_m),
    `lead_excess_m` and `n_missing` (count of ratio > 1) are populated for
    EVERY address, including the ones in "super underdeveloped" areas the
    gate used to drop. `present_count` (categories with nearest_m <=
    window_m) is still computed and still reach-independent -- `reach` never
    enters it -- but it is now a descriptive statistic and a candidate
    ranking feature, not a filter. `min_present` is therefore unused by the
    classification and kept only so callers and tests can still ask for the
    count's definition.

    CENSORING (D75). `censored[i, c]` is True where `M[i, c] >= cap_m`: the
    Dijkstra found nothing of that category within the cap, so the stored
    nearest_m IS the cap and the ratio is a lower bound. `lead_censored` is
    that flag at the lead category. Neither changes `ratio` or `gap_score` --
    a censored ratio is still the smallest value that ratio could take, so
    the ranking stays monotone and conservative; the flags exist so that a
    renderer prints "beyond 2,400 m -- not measured" instead of the cap.

    SIGNAL EXCLUSION (GTM-209, 2026-09-22). `signal_cats` (default:
    `conveniences.signal_categories()`, `ships_as: signal` in categories.yaml)
    is excluded from the row-max/argmax/`>1` count that produce `gap_score`,
    `lead_category` and `n_missing` -- the signal-vs-filter rule
    (docs/CATEGORY-EXPANSION.md §4): "removing it must leave gap_score,
    lead_category, n_missing and the missing set byte-identical". `ratio`
    ITSELF is still computed for a signal category, unmasked, for every
    address -- a signal reorders or annotates a card, it never disappears
    from the table -- so a signal column can still be read off `ratio`
    directly; it just never wins the argmax or adds to the `>1` count. This
    is a property of `ships_as`, not of POI count: a signal category stays
    excluded from these three even after it is fully ingested. `present_count`
    is deliberately NOT masked -- the charter names only the three aggregates
    above plus "the missing set" (== the `ratio > 1` membership this function
    also masks for `n_missing`); `present_count` is a separate descriptive
    statistic D75 already demoted to "not a filter", and masking it is a
    different, un-ruled-on question.
    """
    missing_cats = sorted(set(CATEGORIES) - set(reach))
    if missing_cats:
        raise ValueError(
            f"reach table is missing {len(missing_cats)} of {len(CATEGORIES)} categories: "
            f"{', '.join(missing_cats)}"
        )
    reach_arr = np.array([reach[c] for c in ALLCATS], dtype=np.float64)
    signal_cats = signal_categories() if signal_cats is None else signal_cats
    filter_mask = np.array([c not in signal_cats for c in ALLCATS], dtype=bool)

    present_count = (M <= window_m).sum(axis=1)
    # D75: retired. TRUE for every address, by owner ruling -- kept as a
    # column, not as a predicate. `min_present` is deliberately not read.
    eligible = np.ones(len(M), dtype=bool)
    censored = M >= cap_m

    ratio = M / reach_arr[None, :]
    # Signal columns excluded from the row-max/argmax/`>1` count ONLY -- the
    # `ratio` returned below is the full, unmasked matrix.
    filter_ratio = np.where(filter_mask[None, :], ratio, -np.inf)
    max_ratio = filter_ratio.max(axis=1)
    is_max = filter_ratio == max_ratio[:, None]
    # tie-break: among the tied max-ratio categories, the one with the
    # LARGER raw nearest_m is the more conspicuous absence.
    nearest_masked = np.where(is_max, M, -np.inf)
    lead_idx = nearest_masked.argmax(axis=1)
    rows = np.arange(len(M))
    lead_excess = M[rows, lead_idx] - reach_arr[lead_idx]
    n_missing = ((ratio > 1.0) & filter_mask[None, :]).sum(axis=1)
    lead_category = np.array([ALLCATS[i] for i in lead_idx], dtype=object)
    lead_censored = censored[rows, lead_idx]

    return {
        "present_count": present_count,
        "eligible": eligible,
        "ratio": ratio,
        "censored": censored,
        "gap_score": max_ratio,
        "lead_category": lead_category,
        "lead_excess_m": lead_excess,
        "lead_censored": lead_censored,
        "n_missing": n_missing,
    }


def _cap_units(units, cap: float = UNITS_CAP) -> np.ndarray:
    """D39: clip per-lot units for any unit-weighted ranking. Raw units are
    kept separately -- this is never applied at the source."""
    return np.minimum(np.asarray(units, dtype=np.float64), cap)


def _cluster_gap_addresses(lon: np.ndarray, lat: np.ndarray, radius_m: float = CLUSTER_RADIUS_M
                            ) -> np.ndarray:
    """Single-linkage / DBSCAN-like clustering (eps=`radius_m`, min_samples=1)
    over a local equirectangular projection: any two addresses within
    `radius_m` of each other land in the same cluster (transitively). Returns
    a 0-based cluster label per row. Callers group by lead_category (and
    borough) FIRST -- a grocery-gap cluster and a bank-gap cluster covering
    the same blocks are different investment opportunities, not one cluster.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    n = len(lon)
    if n == 0:
        return np.array([], dtype=np.int64)
    if n == 1:
        return np.array([0], dtype=np.int64)

    lat0 = float(np.mean(lat))
    k = np.pi / 180.0 * 6371000.0
    x = np.asarray(lon) * k * np.cos(np.radians(lat0))
    y = np.asarray(lat) * k
    xy = np.column_stack([x, y])

    tree = cKDTree(xy)
    pairs = tree.query_pairs(r=radius_m, output_type="ndarray")
    if len(pairs):
        rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
        cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
        data = np.ones(len(rows))
    else:
        rows = cols = data = np.array([])
    graph = coo_matrix((data, (rows, cols)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    return labels


def cluster_key(borough: str, frame: str, lead: str, label: int) -> str:
    """The cluster id for one connected component, namespaced by FRAME.

    A LOT cluster keeps exactly the pre-D84 form `"{borough}:{lead}:{n}"` --
    byte-identical, because the whole claim of D84 is that adding street rows
    changes nothing about the lot frame, and a moved cluster id is the first
    thing that would falsify it (tests/test_street_frame.py checksums it).
    A STREET cluster takes an `S` prefix on the local id --
    `"{borough}:{lead}:S{n}"`, e.g. `BK:bar:S12` -- so the two namespaces are
    disjoint by construction, still split into the same three fields for any
    reader, and visibly different in a cluster list, a popup or a CSV.
    """
    if frame not in FRAMES:
        raise ValueError(f"unknown frame {frame!r}; expected one of {FRAMES}")
    return (f"{borough}:{lead}:{label}" if frame == LOT_FRAME
            else f"{borough}:{lead}:S{label}")


def _reach_hash(reach: dict[str, float]) -> str:
    """Short, stable hash of the {category: reach_m} actually used for a
    run, independent of dict insertion order -- same rationale as
    model/gaps.py's `_reach_hash` (not imported from there: gaps.py is being
    edited concurrently this session, so this module stays self-contained)."""
    blob = json.dumps({c: reach[c] for c in sorted(reach)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _col(df: pd.DataFrame, name: str, n: int):
    """`df[name]` if the caller supplied it, else a column of None. The street
    descriptors (frontage_m, street_name, frame_source, frame_vintage) exist
    only on the street frame; a lot-only caller must not have to invent them."""
    return df[name].to_numpy() if name in df.columns else np.full(n, None, dtype=object)


def _nan_to_none(arr: np.ndarray) -> list:
    """float64 array with NaN -> a python list with NaN replaced by None, so
    a DuckDB REAL column round-trips NULL rather than a stored NaN."""
    out = []
    for v in arr:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out.append(None)
        else:
            out.append(float(v))
    return out


# --------------------------------------------------------------- DB layer

def compute_address_gaps(
    con,
    addresses_df: pd.DataFrame,
    reach_source: str = "tiers",
    graph_path: pathlib.Path = GRAPH_PATH,
    cache_dir: pathlib.Path = INTERIM_DIR,
    supply_set: str = DEFAULT_SUPPLY_SET,
) -> pd.DataFrame:
    """Read-only: assembles the full analysis.address_gaps working table for
    `addresses_df` (columns: address_id, bbl, lon, lat, units, borough -- see
    sources/cities/nyc/addresses.py plus a `borough` column the caller adds).
    Does not write anything. This is the `loci address-gaps --dry-run` path
    and the shared computation `build_address_gaps` also uses before writing.
    """
    if "borough" not in addresses_df.columns:
        raise ValueError("addresses_df must carry a 'borough' column (see the CLI)")
    # D84: which sampling frame each row came from. Defaults to 'lot' so every
    # caller that predates the street frame -- and every test that hands this
    # function a bare (address_id, lon, lat, units, borough) frame -- keeps
    # working and keeps meaning what it meant. Validated HERE, before the
    # fifteen Dijkstra passes: a bad frame value is a caller bug, and finding
    # it ten minutes in would be ten minutes wasted.
    frame_arr = (addresses_df["frame"].to_numpy() if "frame" in addresses_df.columns
                 else np.full(len(addresses_df), LOT_FRAME, dtype=object))
    bad = sorted(set(map(str, frame_arr)) - set(FRAMES))
    if bad:
        raise ValueError(f"unknown frame(s) {bad}; expected one of {FRAMES}")

    reach = load_reach(reach_source)
    reach_hash_ = _reach_hash(reach)
    supply_hash_ = supply_hash(con, supply_set)
    M, gver, _key = address_nearest_matrix(con, addresses_df, graph_path=graph_path,
                                           cache_dir=cache_dir, supply_set=supply_set)
    metrics = compute_gap_metrics(M, reach)

    units = addresses_df["units"].to_numpy(dtype=np.float64)
    units_capped = _cap_units(units)
    lon_arr = addresses_df["lon"].to_numpy(dtype=np.float64)
    lat_arr = addresses_df["lat"].to_numpy(dtype=np.float64)
    boro_arr = addresses_df["borough"].to_numpy()
    eligible = metrics["eligible"]
    lead_category = metrics["lead_category"]
    gap_score = metrics["gap_score"]

    # ---- clustering: gap_score > 1, grouped by (borough, FRAME, lead) ----
    # D75: no `eligible &` term any more -- the gate is retired and every
    # address is in the universe, so a cluster is now purely "addresses near
    # each other whose worst category is the same and is beyond its reach".
    #
    # D84: WITHIN FRAME, and the frame is in the id. Clustering the union
    # measured 429 of the 571 existing lot clusters changing membership and id
    # and 12 net MERGING (BK bar 57 -> 44), because a street point bridges two
    # lot clusters the screen previously called distinct opportunities. That is
    # a merge bug in the same family as the dedup failures this project has
    # already been bitten by -- a point with ZERO residents silently becoming
    # the bridge that makes two markets look like one -- and it would destroy
    # the run-to-run cluster continuity (D75's top-50 Jaccard) for a reason
    # that has nothing to do with retail. Street-only clusters are the new
    # signal and they get their own namespace. The adjacency a reader will want
    # ("this street cluster is next to that lot cluster") is a derived,
    # non-mutating lookup, never a shared id.
    gap_mask = np.nan_to_num(gap_score, nan=-1.0) > 1.0
    cluster_id = np.full(len(addresses_df), None, dtype=object)
    gap_idx = np.flatnonzero(gap_mask)
    if len(gap_idx):
        keys = pd.DataFrame({"borough": boro_arr[gap_idx],
                             "frame": frame_arr[gap_idx],
                             "lead": lead_category[gap_idx]})
        for (b, fr, cat), sub in keys.groupby(["borough", "frame", "lead"]):
            local_idx = gap_idx[sub.index.to_numpy()]
            labels = _cluster_gap_addresses(lon_arr[local_idx], lat_arr[local_idx], CLUSTER_RADIUS_M)
            cluster_id[local_idx] = [cluster_key(b, fr, cat, int(lab)) for lab in labels]

    # ---- h3 res-9 cell -> analysis.hex (borough, nta_code), same join
    # convention as model/conveniences.py's build_address_convenience.
    import h3

    RES = 9
    h3_index = [h3.latlng_to_cell(lat, lon, RES) for lat, lon in zip(lat_arr, lon_arr)]
    # NOTE: dict() of the raw 3-column fetchall() rows would raise ("dictionary
    # update sequence element #0 has length 3; 2 is required") -- build the
    # {h3_index: (borough, nta_code)} map explicitly instead.
    hex_lookup = {
        h: (boro, nta)
        for h, boro, nta in con.execute("SELECT h3_index, borough, nta_code FROM analysis.hex").fetchall()
    }
    names_path = pathlib.Path(graph_path).resolve().parents[1] / "interim" / "nta_names.json"
    nta_names: dict[str, str] = {}
    if names_path.exists():
        nta_names = json.loads(names_path.read_text())
    nta_code, neighborhood = [], []
    for h in h3_index:
        _b, code = hex_lookup.get(h, (None, None))
        nta_code.append(code)
        neighborhood.append(nta_names.get(code, code) if code else None)

    data = {
        "address_id": addresses_df["address_id"].to_numpy(),
        "bbl": addresses_df["bbl"].to_numpy() if "bbl" in addresses_df.columns else [None] * len(addresses_df),
        "lon": lon_arr,
        "lat": lat_arr,
        "units": units,
        "units_capped": units_capped,
        "h3_index": h3_index,
        "nta_code": nta_code,
        "neighborhood": neighborhood,
        "borough": boro_arr,
        "present_count": metrics["present_count"],
        "eligible": eligible,
        "gap_score": _nan_to_none(gap_score),
        "lead_category": lead_category,
        "lead_excess_m": _nan_to_none(metrics["lead_excess_m"]),
        "n_missing": metrics["n_missing"],
        "cluster_id": cluster_id,
        "lead_censored": metrics["lead_censored"],
        "frame": frame_arr,
        # Street-row descriptors, NULL on a lot row. `frontage_m` is how much
        # street one point stands for: the screen varies at the block scale
        # (adjacent points 120-160 m apart disagree on lead_category 39.7% of
        # the time), so a street point is a SAMPLE of its segment and the
        # reader has to be able to see the sample's span.
        "frontage_m": _col(addresses_df, "frontage_m", len(addresses_df)),
        "street_name": _col(addresses_df, "street_name", len(addresses_df)),
        "frame_source": _col(addresses_df, "frame_source", len(addresses_df)),
        "frame_vintage": _col(addresses_df, "frame_vintage", len(addresses_df)),
    }
    ratio = metrics["ratio"]
    censored = metrics["censored"]
    for i, cat in enumerate(ALLCATS):
        data[f"{cat}_nearest_m"] = M[:, i]
        data[f"{cat}_ratio"] = ratio[:, i]
        data[f"{cat}_censored"] = censored[:, i]
    data["reach_source"] = reach_source
    data["reach_hash"] = reach_hash_
    data["graph_version"] = gver
    # D52 provenance: WHICH POIs counted as supply, and a hash of everything
    # that decided that (set name, dedup radii, qualifying anchors, per-category
    # counts). Same rationale as reach_hash -- two runs differing only in supply
    # are otherwise indistinguishable once written, and the difference is large.
    data["supply_set"] = supply_set
    data["supply_hash"] = supply_hash_
    data["run_at"] = datetime.datetime.now(datetime.timezone.utc)

    return pd.DataFrame(data)


def _split_wide(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split compute_address_gaps' wide working frame (one row per address,
    45 pivoted `{cat}_nearest_m`/`{cat}_ratio`/`{cat}_censored` columns) into
    the two shapes analysis.address and analysis.address_category actually
    store (D38/D58): identity + summary + provenance on one row per address,
    and nearest_m/ratio/is_lead/eligible/censored on one row per (address,
    category) -- ALLCATS rows per address, always, present or missing
    alike."""
    # D84: a frame built before the street frame existed (and every test that
    # assembles one by hand) carries no `frame` columns. Fill them rather than
    # requiring every caller to invent five columns whose answer is "this is a
    # lot, like everything was" -- the same tolerance `_col` gives the
    # street-only descriptors upstream.
    df = df.copy()
    if "frame" not in df.columns:
        df["frame"] = LOT_FRAME
    for c in ("frontage_m", "street_name", "frame_source", "frame_vintage"):
        if c not in df.columns:
            df[c] = None
    addr_df = df[ADDRESS_COLUMNS].copy()
    lead = df["lead_category"]
    long_frames = [
        pd.DataFrame({
            "address_id": df["address_id"],
            "borough": df["borough"],
            "category": cat,
            "nearest_m": df[f"{cat}_nearest_m"],
            "ratio": df[f"{cat}_ratio"],
            # IS NOT NULL guard: kept after D75 even though every address now
            # has a lead_category -- `NULL == cat` is NULL, not FALSE, so a
            # bare comparison on any future NULL would read as neither true
            # nor false rather than "not the lead".
            "is_lead": lead.notna() & (lead == cat),
            "eligible": df["eligible"],
            "censored": df[f"{cat}_censored"],
            "frame": df["frame"],
        })
        for cat in ALLCATS
    ]
    cat_df = pd.concat(long_frames, ignore_index=True)[ADDRESS_CATEGORY_SCREEN_COLUMNS]
    return addr_df, cat_df


def write_address_gaps(con, df: pd.DataFrame) -> int:
    """Persist `df` (compute_address_gaps' wide working frame) by splitting
    it into analysis.address and analysis.address_category (D38/D58's
    principled split -- see sql/002_schema.sql's "THE ADDRESS SCREEN, in its
    principled shape" header) and delete-then-inserting every borough present
    in `df` on BOTH tables together, so a partial rebuild can never leave one
    table one borough ahead of the other. analysis.address_gaps is a VIEW
    over these two (address_gaps_view_sql, applied by db.init_schema()) --
    there is no wide table to write here at all any more.

    Only the screen's own columns are ever named on address_category
    (ADDRESS_CATEGORY_SCREEN_COLUMNS): the demand annotation columns on the
    same table are left at their DEFAULT (NULL) by this INSERT and are
    model/address_demand.py's to fill, by UPDATE, never by this writer.
    """
    addr_df, cat_df = _split_wide(df)
    for b in sorted(df["borough"].unique()):
        con.execute("DELETE FROM analysis.address_category WHERE borough = ?", [b])
        con.execute("DELETE FROM analysis.address WHERE borough = ?", [b])
    con.register("_aa", addr_df)
    try:
        cols = ", ".join(addr_df.columns)
        con.execute(f"INSERT INTO analysis.address ({cols}) SELECT {cols} FROM _aa")
    finally:
        con.unregister("_aa")
    con.register("_ac", cat_df)
    try:
        cols = ", ".join(cat_df.columns)
        con.execute(f"INSERT INTO analysis.address_category ({cols}) SELECT {cols} FROM _ac")
    finally:
        con.unregister("_ac")
    return len(df)


def prune_out_of_scope(con, scope) -> tuple[int, int]:
    """Delete every analysis.address / analysis.address_category row whose
    borough is outside `scope`, and report (address rows, category rows)
    removed.

    write_address_gaps only delete-then-inserts the boroughs PRESENT in the
    frame it is handed, which is right for a partial rebuild but means a
    narrower re-run cannot clean up after a wider one: the citywide run that
    D61 made to attach demographics left QN/BX/SI rows that an MN+BK run would
    simply leave in place. This is the explicit, idempotent removal of them
    (D78). `scope` is passed in -- a borough code never appears in this module.
    """
    scope = tuple(scope)
    if not scope:
        raise ValueError("scope must name at least one borough")
    q = ", ".join("?" for _ in scope)
    n_cat = con.execute(
        f"SELECT count(*) FROM analysis.address_category WHERE borough NOT IN ({q})",
        list(scope)).fetchone()[0]
    n_addr = con.execute(
        f"SELECT count(*) FROM analysis.address WHERE borough NOT IN ({q})",
        list(scope)).fetchone()[0]
    if n_cat or n_addr:
        # category first, so an interrupted prune can never leave a category
        # row whose address row is gone (the same ordering discipline
        # write_address_gaps keeps on its per-borough delete).
        con.execute(
            f"DELETE FROM analysis.address_category WHERE borough NOT IN ({q})", list(scope))
        con.execute(
            f"DELETE FROM analysis.address WHERE borough NOT IN ({q})", list(scope))
    return n_addr, n_cat


def address_gaps_view_sql() -> str:
    """`CREATE OR REPLACE VIEW analysis.address_gaps`: analysis.address
    joined to a PIVOT of analysis.address_category's long rows back into the
    old wide `{cat}_nearest_m`/`{cat}_ratio` column pairs, in the OLD column
    order (identity, summary, the 15 pairs in categories.py order, then
    provenance) -- so viz/webmap_export.py, sql/004+005's laundry views and
    every CLI query written against the pre-split table keep working
    unchanged. Generated from ALLCATS (loci.categories.CATEGORIES order) so a
    16th category is one entry in that dict, never a hand-edited SELECT list.

    Applied by db.init_schema() immediately after 002_schema.sql -- NOT at
    the end of the migration sweep -- because sql/004_ll84_laundry.sql,
    005_listings_laundry.sql and 006_principled_supply.sql all reference
    analysis.address_gaps by name, and DuckDB resolves a view's query at
    CREATE time, not at first SELECT.
    """
    pivot_cols = ",\n            ".join(
        f"MAX(CASE WHEN category = '{c}' THEN nearest_m END) AS {c}_nearest_m,\n"
        f"            MAX(CASE WHEN category = '{c}' THEN ratio END) AS {c}_ratio,\n"
        f"            MAX(CASE WHEN category = '{c}' THEN censored END) AS {c}_censored"
        for c in ALLCATS
    )
    select_cols = ",\n            ".join(f"w.{c}_nearest_m, w.{c}_ratio" for c in ALLCATS)
    censored_cols = ", ".join(f"w.{c}_censored" for c in ALLCATS)
    return f"""
        CREATE OR REPLACE VIEW analysis.address_gaps AS
        WITH wide AS (
            SELECT address_id, borough,
            {pivot_cols}
            FROM analysis.address_category
            GROUP BY address_id, borough
        )
        SELECT
            a.address_id, a.bbl, a.lon, a.lat, a.units, a.units_capped,
            a.nta_code, a.neighborhood, a.borough,
            a.present_count, a.eligible, a.gap_score, a.lead_category,
            a.lead_excess_m, a.n_missing, a.cluster_id,
            {select_cols},
            a.reach_source, a.reach_hash, a.graph_version, a.run_at,
            a.supply_set, a.supply_hash, a.h3_index,
            -- The development-pipeline annotation (sql/011, model/dev_pipeline.py),
            -- APPENDED so every positional consumer of the old column order is
            -- untouched. All NULL until `loci pipeline` has run for the borough.
            a.units_permitted_400m, a.units_permitted_800m,
            a.units_completed_24mo_400m, a.units_completed_24mo_800m,
            a.units_completed_60mo_400m, a.units_completed_60mo_800m,
            a.nearest_large_project_id, a.nearest_large_project_m,
            a.nearest_large_project_units, a.nearest_large_project_stage,
            a.nearest_large_project_date, a.pipeline_asof,
            -- The construction-progress split of units_permitted_400m
            -- (sql/014_dev_pipeline_activity.sql, D62 caveats 3 and 9).
            -- APPENDED, same reason. NOT a partition: active + stalled <=
            -- permitted, the remainder being `lapsed` and evidence-less jobs.
            -- NULL (not 0) until `loci pipeline-activity` has run.
            a.units_active_400m, a.units_stalled_400m,
            -- The D63 age-fit ranking columns (model/age_fit.py). APPENDED for
            -- the same reason: every positional consumer of the older column
            -- order is untouched. All NULL until `loci age-fit apply` has run.
            -- `gap_score_fit` sits BESIDE `gap_score`, never in place of it --
            -- the un-multiplied score is the one the screen owns and the one a
            -- reader compares against. The PER-CATEGORY `age_fit`/`age_fit_moe`
            -- are deliberately NOT pivoted in here: exactly one of the fifteen
            -- categories has a fitted curve (bar), so a generated pair per
            -- category would add 30 columns, 28 of them always NULL. Query
            -- analysis.address_category directly for the per-category value.
            a.age_fit_lead, a.age_fit_lead_moe, a.gap_score_fit,
            -- The storefront-vacancy annotation (sql/012, model/storefronts.py).
            -- APPENDED for the same reason as the two blocks above: every
            -- positional consumer of the older column order is untouched. All
            -- NULL until `loci storefronts` has run for the borough.
            -- `vacant_storefronts_400m` is a SUBSET of `storefronts_400m`, and
            -- the pair is a rate -- never a sum. The denominator is carried
            -- here on purpose: the registry is self-reported, so "0 vacant
            -- within 400 m" and "nobody near here filed" are the same
            -- observation until you can see how many storefronts filed at all.
            a.vacant_storefronts_400m, a.storefronts_400m,
            a.nearest_vacant_storefront_m, a.nearest_vacant_storefront_id,
            a.nearest_vacant_storefront_business,
            a.nearest_vacant_lease_expired, a.storefront_asof,
            -- The supply-INTENSITY denominators (sql/002 tail,
            -- model/supply_ratio.py, 2026-09-11 red-team). APPENDED for the
            -- same reason as every block above: positional consumers of the
            -- older column order are untouched. NULL until `loci supply-ratio`
            -- has run for the borough.
            --
            -- Only the CATEGORY-INDEPENDENT half is here. `supply_400m`,
            -- `supply_per_1k` and `supply_ratio_vs_base` are genuinely per
            -- category and live on analysis.address_category; they are NOT
            -- pivoted in, for the same reason age_fit is not -- fifteen
            -- generated triples would add 45 columns to a view whose whole
            -- purpose is the OLD wide shape. Query address_category directly.
            --
            -- `addressable_homes_400m_laundry` is a SUBSET of `homes_400m`
            -- (homes less the in-unit/in-building laundry haircut,
            -- model/laundry_haircut.yaml). Never add the two, and never quote
            -- `homes_400m` as a laundry demand pool.
            a.homes_400m, a.addressable_homes_400m_laundry,
            a.supply_ratio_radius_m, a.supply_ratio_supply_hash,
            a.supply_ratio_run_at,
            -- The D75 CENSORING flags (sql/002 tail). APPENDED, same reason as
            -- every block above: positional consumers of the older column
            -- order are untouched. `lead_censored` says the lead category's
            -- nearest_m is AT the 2,400 m Dijkstra cap, so `gap_score` for
            -- this address is a FLOOR, not a measurement; the fifteen
            -- `{{cat}}_censored` flags say the same per category and sit beside
            -- their own `{{cat}}_nearest_m`/`{{cat}}_ratio` pair. They are pivoted
            -- in (unlike age_fit, which is not) because a censored distance
            -- and the distance itself are the SAME reading -- a renderer that
            -- can reach one must be able to reach the other, or it prints the
            -- cap as if it were a measurement.
            a.lead_censored,
            {censored_cols},
            -- The WALK-SHED DENSITY columns (sql/002 tail,
            -- model/supply_ratio.py; owner ruling 2026-09-13 "rank by
            -- density"). APPENDED last, same reason as every block above.
            -- `density_400m` = homes_400m / walkshed_km2_400m: residential
            -- UNITS per km2 of the walk the address can actually make, NOT
            -- ACS households per km2 and carrying no margin of error.
            -- NULL until `loci supply-ratio` has run for the borough.
            a.walkshed_km2_400m, a.density_400m,
            -- THE SAMPLING FRAME (D84, sql/002 tail). APPENDED last, same
            -- reason as every block above. 'lot' is a residential PLUTO tax
            -- lot (bbl set, units > 0); 'street' is a point every 100 m along
            -- a kept CSCL street segment (bbl NULL, units 0, frontage_m set).
            -- EVERY consumer of this view that reads a row as "a residential
            -- address" must now filter on it: a street point has no residents,
            -- so counting street rows as addresses inflates any "N addresses
            -- have a gap" headline by ~17%, and a units-weighted statistic is
            -- unaffected only because street units are 0 and not NULL.
            a.frame, a.frontage_m, a.street_name
        FROM analysis.address a
        LEFT JOIN wide w ON w.address_id = a.address_id AND w.borough = a.borough
    """


def build_address_gaps(
    con,
    addresses_df: pd.DataFrame,
    reach_source: str = "tiers",
    graph_path: pathlib.Path = GRAPH_PATH,
    cache_dir: pathlib.Path = INTERIM_DIR,
    supply_set: str = DEFAULT_SUPPLY_SET,
) -> tuple[int, pd.DataFrame]:
    """compute_address_gaps + write_address_gaps. Returns (rows written, the
    working DataFrame) so the CLI can print the same summary for the write
    path as for --dry-run without recomputing."""
    df = compute_address_gaps(con, addresses_df, reach_source=reach_source,
                               graph_path=graph_path, cache_dir=cache_dir,
                               supply_set=supply_set)
    n = write_address_gaps(con, df)
    return n, df


# ------------------------------------------------------------- reporting

#: How a cluster list is ordered. `density` is the owner's 2026-09-13 ruling
#: ("rank by density"); `units` is the pre-ruling order, kept selectable so the
#: two can be compared rather than argued about.
RANK_BY = ("density", "units")
DEFAULT_RANK_BY = "density"


def weighted_median(values, weights) -> float:
    """Median of `values` weighted by `weights` -- the lower weighted median
    (the first value whose cumulative weight reaches half the total).

    Falls back to the UNWEIGHTED median when every usable weight is zero, so a
    cluster of unit-less rows still gets a number instead of a NaN. Returns NaN
    only when there is no finite value at all."""
    v = np.asarray(values, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    finite = np.isfinite(v)
    if not finite.any():
        return float("nan")
    ok = finite & np.isfinite(w) & (w > 0)
    if not ok.any():
        ok, w = finite, np.ones(len(v), dtype=np.float64)
    v, w = v[ok], w[ok]
    order = np.argsort(v, kind="mergesort")
    v, w = v[order], w[order]
    cum = np.cumsum(w)
    return float(v[int(np.searchsorted(cum, 0.5 * cum[-1], side="left"))])


def cluster_table(df: pd.DataFrame, rank_by: str = DEFAULT_RANK_BY) -> pd.DataFrame:
    """One row per `cluster_id`, ordered by `rank_by`. Pure, DB-free.

    THE ORDERING IS THE OWNER'S, AND IT WAS NEVER A DECISION BEFORE
    -----------------------------------------------------------------------
    Until 2026-09-13 every cluster list in this project was sorted by
    `Sum(units_capped)`, which nobody ever chose: it was the first plausible
    weight to hand when D39 capped mega-lots, and it silently ranks by SIZE --
    a big cluster of low-rise blocks outranks a small one of towers. The owner
    ruled "rank by density", and confirmed the reading: households per km2
    inside the walk-shed. `Sum(units_capped)` survives as the tiebreak and is
    still printed, because "how dense" and "how many" are different questions
    and the reader needs both.

    WHY A WEIGHTED MEDIAN AND NOT A POOLED RATIO
    -----------------------------------------------------------------------
    The obvious cluster density -- `Sum(homes) / Sum(walkshed area)` -- is
    wrong, and not slightly. Member addresses sit within 200 m of each other,
    so their 400 m walk-sheds overlap almost completely: the numerator counts
    the same homes once per member while the denominator counts the same land
    once per member, and the ratio is neither a density nor stable under how
    finely the block was subdivided into tax lots. So the cluster's density is
    the `units_capped`-weighted MEDIAN of its members' own `density_400m` --
    a statement about the typical doorway in the cluster, weighted by the
    households behind it, and robust to the one mega-lot D39 capped for
    exactly this reason. The unweighted MEAN is reported beside it as a
    secondary: where the two diverge, the cluster is skewed and the reader
    should look at the members.

    Requires `density_400m` on `df` when `rank_by="density"` -- it is not
    recomputed here (model/supply_ratio.py owns it, off the same sweep as
    `homes_400m`). A frame whose `density_400m` is entirely NULL is a
    supply-ratio that has not been run for the borough, and that is an error
    rather than a silent fallback to the old ordering.
    """
    if rank_by not in RANK_BY:
        raise ValueError(f"unknown rank_by {rank_by!r}; expected one of {RANK_BY}")
    clustered = df.loc[df["cluster_id"].notna()]
    if not len(clustered):
        cols = ["cluster_id", "borough", "frame", "lead_category", "n_addresses",
                "units_capped", "cluster_density_400m", "cluster_density_mean_400m",
                "median_lead_excess_m"]
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in cols})
    has_density = "density_400m" in clustered.columns and \
        pd.to_numeric(clustered["density_400m"], errors="coerce").notna().any()
    if rank_by == "density" and not has_density:
        raise ValueError(
            "rank_by='density' needs a populated `density_400m` column "
            "(analysis.address.density_400m) -- run `loci supply-ratio "
            "--boroughs ...` first, or pass rank_by='units'")

    work = clustered.copy()
    # D84: a cluster belongs to exactly one frame (clustering is WITHIN frame),
    # so `first` is the whole truth and not a summary. A frame missing from the
    # caller's frame means a lot-only query, which is what it was before D84.
    if "frame" not in work.columns:
        work["frame"] = LOT_FRAME
    work["_density"] = (pd.to_numeric(work["density_400m"], errors="coerce")
                        if has_density else np.nan)
    work["_units"] = pd.to_numeric(work["units_capped"], errors="coerce").fillna(0.0)

    out = (
        work.groupby("cluster_id")
        .agg(
            units_capped=("units_capped", "sum"),
            n_addresses=("units_capped", "size"),
            borough=("borough", "first"),
            frame=("frame", "first"),
            lead_category=("lead_category", "first"),
            median_lead_excess_m=("lead_excess_m", "median"),
            cluster_density_mean_400m=("_density", "mean"),
        )
        .reset_index()
    )
    wmed = {cid: weighted_median(g["_density"].to_numpy(), g["_units"].to_numpy())
            for cid, g in work.groupby("cluster_id", sort=False)}
    out["cluster_density_400m"] = out["cluster_id"].map(wmed)
    if "nta_code" in work.columns:
        mode = (work.groupby("cluster_id")["nta_code"]
                    .agg(lambda s: s.dropna().mode().iloc[0] if s.notna().any() else None)
                    .rename("nta_code").reset_index())
        out = out.merge(mode, on="cluster_id", how="left")
    if "neighborhood" in work.columns:
        nb = (work.groupby("cluster_id")["neighborhood"]
                  .agg(lambda s: s.dropna().mode().iloc[0] if s.notna().any() else None)
                  .rename("neighborhood").reset_index())
        out = out.merge(nb, on="cluster_id", how="left")

    # Density first, capped units as the TIEBREAK -- never the other way round,
    # and never density alone: two clusters on the same block face can share a
    # density to the last decimal and the bigger one is the better lead.
    by = (["cluster_density_400m", "units_capped"] if rank_by == "density"
          else ["units_capped", "cluster_density_400m"])
    return out.sort_values(by, ascending=False, na_position="last").reset_index(drop=True)


def summarize_gap_run(df: pd.DataFrame, rank_by: str = DEFAULT_RANK_BY) -> dict:
    """Pure, DB-free summary from the address_gaps working DataFrame (the
    same shape build_address_gaps writes) -- shared by --dry-run and the
    post-write CLI summary, so both report the same numbers."""
    n_addr = len(df)
    n_units = float(df["units"].sum()) if n_addr else 0.0
    # D75: `eligible` is TRUE everywhere, so these two shares are 1.0 by
    # construction. They stay in the summary dict (the CLI prints them and a
    # reader comparing against a pre-D75 run needs to SEE the 100%), but no
    # count below is masked by them any more.
    elig = df["eligible"].astype(bool)
    eligible_addr_share = float(elig.mean()) if n_addr else 0.0
    eligible_unit_share = float(df.loc[elig, "units"].sum() / n_units) if n_units else 0.0

    per_cat_gap_addr, per_cat_gap_units, per_cat_censored = {}, {}, {}
    for cat in ALLCATS:
        gap_mask = df[f"{cat}_ratio"] > 1.0
        per_cat_gap_addr[cat] = int(gap_mask.sum())
        per_cat_gap_units[cat] = float(df.loc[gap_mask, "units"].sum())
        per_cat_censored[cat] = int(df[f"{cat}_censored"].astype(bool).sum())

    # "lead distribution" counts only addresses that actually HAVE a gap
    # (n_missing > 0) -- a fully-served address still gets a lead_category
    # (the argmax ratio, which can be <= 1), but it isn't a gap and
    # shouldn't inflate this table (matches the per-category gap counts and
    # cluster scoping above, and the D8 reference implementation).
    has_gap = df["n_missing"] > 0
    lead_distribution = (
        df.loc[has_gap & df["lead_category"].notna(), "lead_category"]
        .value_counts()
        .to_dict()
    )

    # Cluster ordering: the owner's 2026-09-13 ruling is density, and
    # `cluster_table` REFUSES to pretend when `density_400m` is not there. The
    # fallback is caught here rather than allowed to kill a --dry-run on a
    # database where supply-ratio has not run yet -- but it is RECORDED and
    # printed, never silent: a units-ordered list that claims to be
    # density-ordered is the exact failure this ruling was correcting.
    rank_fallback = None
    try:
        clusters = cluster_table(df, rank_by=rank_by)
    except ValueError as exc:
        if rank_by != "density":
            raise
        rank_fallback = str(exc).split(" -- ")[0]
        rank_by, clusters = "units", cluster_table(df, rank_by="units")
    top_clusters = clusters.head(10).to_dict("records")

    # D84: the two frames, side by side and never pooled into one headline.
    # "N addresses have a gap" means residential addresses; a street point has
    # no residents, so pooling the two inflates that number by ~17% for free.
    frame_col = df["frame"] if "frame" in df.columns else pd.Series(
        [LOT_FRAME] * n_addr, index=df.index)
    by_frame = {}
    for fr in FRAMES:
        m = frame_col == fr
        if not bool(m.any()):
            continue
        by_frame[fr] = {
            "n_addresses": int(m.sum()),
            "n_units": float(df.loc[m, "units"].sum()),
            "n_gap_addresses": int((df.loc[m, "n_missing"] > 0).sum()),
            "n_clustered": int(df.loc[m, "cluster_id"].notna().sum()),
            "n_clusters": int(df.loc[m, "cluster_id"].dropna().nunique()),
            "median_gap_score": float(pd.to_numeric(
                df.loc[m, "gap_score"], errors="coerce").median()),
            "lead_censored": int(df.loc[m, "lead_censored"].astype(bool).sum()),
        }

    return {
        "rank_by": rank_by,
        "rank_by_fallback": rank_fallback,
        "by_frame": by_frame,
        "n_addresses": n_addr,
        "n_units": n_units,
        "eligible_addr_share": eligible_addr_share,
        "eligible_unit_share": eligible_unit_share,
        "per_cat_gap_addr": per_cat_gap_addr,
        "per_cat_gap_units": per_cat_gap_units,
        "lead_distribution": lead_distribution,
        "top_clusters": top_clusters,
        # D75 censoring: how much of the screen is reading the cap rather
        # than a distance. `lead_censored_addr` is the number that matters
        # for the ranking -- those addresses' gap_score is a floor.
        "per_cat_censored": per_cat_censored,
        "censored_pairs": int(sum(per_cat_censored.values())),
        "lead_censored_addr": int(df["lead_censored"].astype(bool).sum()),
        "cap_m": CAP_M,
    }
