"""Address-level gap screen (per residential PLUTO lot -- D38: one tax lot
with UnitsRes > 0 is one "address" for this purpose).

SUPERSEDES the old rule entirely (CHECKPOINT D33/D38/D39/D41): a single
shared 800 m walk window plus an 80%-prevalence "expected" test, the same
design defect model/gaps.py's `rule="window"` has (QUESTIONS D6/CHECKPOINT
D33) -- tightening the window could make a gap disappear, because "expected"
was re-derived from the whole city on every call. The old 800m/80% code path
is deleted here, not kept behind a flag.

The new rule, at address grain:

  - ELIGIBILITY is a FIXED, reach-independent walkability gate: an address is
    in scope iff >= `MIN_PRESENT` (12) of the 15 categories sit within
    `WINDOW_M` (800 m, the window rule's own 10-minute definition) of it --
    mirrors model/gaps.py's `_eligible_universe` at address grain, so
    changing the reach table can never change which addresses are screened
    (tests/test_address_gaps.py part a).

  - Among eligible addresses, `ratio[c] = nearest_m[c] / reach[c]` is a
    CONTINUOUS score per category (D39), not a binary flag: `gap_score` is
    its row-max, `lead_category` its argmax (ties -> the LARGER raw
    nearest_m, since a farther near-miss is the more conspicuous absence),
    `lead_excess_m` is nearest - reach at the lead, and `n_missing` counts
    categories with ratio > 1. Tightening any reach can only grow the set of
    (address, category) pairs with ratio > 1, never shrink it (part b) --
    reach never touches the gate, only the ratio.

  - `units_capped` clips units at `UNITS_CAP` (500/lot) for any unit-weighted
    ranking: D39 found Co-op City-scale lots (~10k units) would otherwise
    dominate every cluster ranking on their own. Raw `units` is kept too.

  - Eligible, gap_score > 1 addresses that share a `lead_category` and sit
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
from loci.model.conveniences import ALLCATS, graph_version
from loci.reach import load_reach
from loci.score.access import DIST_LIMIT, MIN_COMPONENT, _prune, _to_csr
from loci.score.supply import DEFAULT_SUPPLY_SET, canonical_poi_sql, supply_hash
from loci.score.walkgraph import OUT as GRAPH_PATH

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
INTERIM_DIR = REPO_ROOT / "data" / "interim"

WINDOW_M = 800.0        # gaps.py's own window-rule presence definition (10 min @ 80 m/min)
MIN_PRESENT = 12        # gaps.py's _eligible_universe default gate, mirrored at address grain
UNITS_CAP = 500.0       # D39: cap per-lot units for any unit-weighted ranking
CLUSTER_RADIUS_M = 200.0

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
]

#: analysis.address_category's SCREEN-owned columns (D38/D58 split) -- the
#: ones write_address_gaps is allowed to touch. The demand annotation columns
#: on the same table (demand_class, elasticity, income_ratio, ...) are NOT
#: here: model/address_demand.py owns those and issues UPDATE only, per the
#: D57/D58 non-filtering guarantee -- this writer never names them, so it
#: cannot accidentally clobber an annotation with a plain re-run of the screen.
ADDRESS_CATEGORY_SCREEN_COLUMNS = [
    "address_id", "borough", "category", "nearest_m", "ratio", "is_lead", "eligible",
]


# --------------------------------------------------------------- the engine

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
                         window_m: float = WINDOW_M, min_present: int = MIN_PRESENT
                         ) -> dict[str, np.ndarray]:
    """Pure numpy classification from an (n_addresses, 15) nearest-metres
    matrix (ALLCATS column order) and a complete {category: reach_m} dict.
    Fails closed (mirrors loci.reach._check_reach_complete) if `reach` is
    missing a category.

    `eligible` = present_count (categories with nearest_m <= window_m) >=
    min_present -- FIXED and reach-independent by construction (`reach`
    never enters this computation). `ratio[c] = nearest_m[c] / reach[c]` is
    always populated (informational, even for ineligible rows); `gap_score`
    (row-max ratio), `lead_category` (argmax ratio, ties -> larger
    nearest_m), `lead_excess_m` (nearest - reach at the lead) are NaN/None
    for an ineligible row, and `n_missing` (count of ratio > 1) is 0 for one
    -- out of scope, exactly like a hex failing gaps.py's window gate.
    """
    missing_cats = sorted(set(CATEGORIES) - set(reach))
    if missing_cats:
        raise ValueError(
            f"reach table is missing {len(missing_cats)} of {len(CATEGORIES)} categories: "
            f"{', '.join(missing_cats)}"
        )
    reach_arr = np.array([reach[c] for c in ALLCATS], dtype=np.float64)

    present_count = (M <= window_m).sum(axis=1)
    eligible = present_count >= min_present

    ratio = M / reach_arr[None, :]
    max_ratio = ratio.max(axis=1)
    is_max = ratio == max_ratio[:, None]
    # tie-break: among the tied max-ratio categories, the one with the
    # LARGER raw nearest_m is the more conspicuous absence.
    nearest_masked = np.where(is_max, M, -np.inf)
    lead_idx = nearest_masked.argmax(axis=1)
    lead_excess = M[np.arange(len(M)), lead_idx] - reach_arr[lead_idx]
    n_missing_all = (ratio > 1.0).sum(axis=1)

    gap_score = np.where(eligible, max_ratio, np.nan)
    lead_excess_m = np.where(eligible, lead_excess, np.nan)
    lead_category = np.array(
        [ALLCATS[i] if e else None for i, e in zip(lead_idx, eligible)], dtype=object
    )
    n_missing = np.where(eligible, n_missing_all, 0)

    return {
        "present_count": present_count,
        "eligible": eligible,
        "ratio": ratio,
        "gap_score": gap_score,
        "lead_category": lead_category,
        "lead_excess_m": lead_excess_m,
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


def _reach_hash(reach: dict[str, float]) -> str:
    """Short, stable hash of the {category: reach_m} actually used for a
    run, independent of dict insertion order -- same rationale as
    model/gaps.py's `_reach_hash` (not imported from there: gaps.py is being
    edited concurrently this session, so this module stays self-contained)."""
    blob = json.dumps({c: reach[c] for c in sorted(reach)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


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

    # ---- clustering: eligible, gap_score > 1, grouped by (borough, lead) ----
    gap_mask = eligible & (np.nan_to_num(gap_score, nan=-1.0) > 1.0)
    cluster_id = np.full(len(addresses_df), None, dtype=object)
    gap_idx = np.flatnonzero(gap_mask)
    if len(gap_idx):
        keys = pd.DataFrame({"borough": boro_arr[gap_idx], "lead": lead_category[gap_idx]})
        for (b, cat), sub in keys.groupby(["borough", "lead"]):
            local_idx = gap_idx[sub.index.to_numpy()]
            labels = _cluster_gap_addresses(lon_arr[local_idx], lat_arr[local_idx], CLUSTER_RADIUS_M)
            cluster_id[local_idx] = [f"{b}:{cat}:{int(lab)}" for lab in labels]

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
    }
    ratio = metrics["ratio"]
    for i, cat in enumerate(ALLCATS):
        data[f"{cat}_nearest_m"] = M[:, i]
        data[f"{cat}_ratio"] = ratio[:, i]
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
    30 pivoted `{cat}_nearest_m`/`{cat}_ratio` columns) into the two shapes
    analysis.address and analysis.address_category actually store (D38/D58):
    identity + summary + provenance on one row per address, and
    nearest_m/ratio/is_lead/eligible on one row per (address, category) --
    ALLCATS rows per address, always, present or missing alike."""
    addr_df = df[ADDRESS_COLUMNS].copy()
    lead = df["lead_category"]
    long_frames = [
        pd.DataFrame({
            "address_id": df["address_id"],
            "borough": df["borough"],
            "category": cat,
            "nearest_m": df[f"{cat}_nearest_m"],
            "ratio": df[f"{cat}_ratio"],
            # IS NOT NULL guard: an ineligible address has lead_category NULL,
            # and `NULL == cat` is NULL, not FALSE -- would read as neither
            # true nor false rather than "not the lead" if compared bare.
            "is_lead": lead.notna() & (lead == cat),
            "eligible": df["eligible"],
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
        f"            MAX(CASE WHEN category = '{c}' THEN ratio END) AS {c}_ratio"
        for c in ALLCATS
    )
    select_cols = ",\n            ".join(f"w.{c}_nearest_m, w.{c}_ratio" for c in ALLCATS)
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
            a.nearest_large_project_date, a.pipeline_asof
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

def summarize_gap_run(df: pd.DataFrame) -> dict:
    """Pure, DB-free summary from the address_gaps working DataFrame (the
    same shape build_address_gaps writes) -- shared by --dry-run and the
    post-write CLI summary, so both report the same numbers."""
    n_addr = len(df)
    n_units = float(df["units"].sum()) if n_addr else 0.0
    elig = df["eligible"].astype(bool)
    eligible_addr_share = float(elig.mean()) if n_addr else 0.0
    eligible_unit_share = float(df.loc[elig, "units"].sum() / n_units) if n_units else 0.0

    per_cat_gap_addr, per_cat_gap_units = {}, {}
    for cat in ALLCATS:
        gap_mask = elig & (df[f"{cat}_ratio"] > 1.0)
        per_cat_gap_addr[cat] = int(gap_mask.sum())
        per_cat_gap_units[cat] = float(df.loc[gap_mask, "units"].sum())

    # "lead distribution" counts only addresses that actually HAVE a gap
    # (n_missing > 0) -- an eligible, fully-served address still gets a
    # lead_category (the argmax ratio, which can be <= 1), but it isn't a
    # gap and shouldn't inflate this table (matches the per-category gap
    # counts and cluster scoping above, and the D8 reference implementation).
    has_gap = elig & (df["n_missing"] > 0)
    lead_distribution = (
        df.loc[has_gap & df["lead_category"].notna(), "lead_category"]
        .value_counts()
        .to_dict()
    )

    clustered = df.loc[df["cluster_id"].notna()]
    if len(clustered):
        clusters = (
            clustered.groupby("cluster_id")
            .agg(
                units_capped=("units_capped", "sum"),
                n_addresses=("units_capped", "size"),
                borough=("borough", "first"),
                lead_category=("lead_category", "first"),
                median_lead_excess_m=("lead_excess_m", "median"),
            )
            .reset_index()
            .sort_values("units_capped", ascending=False)
        )
        top_clusters = clusters.head(10).to_dict("records")
    else:
        top_clusters = []

    return {
        "n_addresses": n_addr,
        "n_units": n_units,
        "eligible_addr_share": eligible_addr_share,
        "eligible_unit_share": eligible_unit_share,
        "per_cat_gap_addr": per_cat_gap_addr,
        "per_cat_gap_units": per_cat_gap_units,
        "lead_distribution": lead_distribution,
        "top_clusters": top_clusters,
    }
