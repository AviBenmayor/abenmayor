"""Walkable access scoring (GTM-28).

Primary artifact: analysis.hex_poi_distance — every (hex, canonical business) pair
within a 30-minute walk with its NETWORK distance. One bounded scipy Dijkstra per
batch of hex nodes; minutes for ~8,300 hexes, without the per-hex python
isochrones CONTEXT.md §4.3 warns off. hex_access (counts per hex, category and
threshold — what the saturating DNCI consumes) is DERIVED from that table in SQL,
so any walk time, nearest-distance or spacing question is a query, not a rerun.

City-agnostic: consumes a walk graph, the grid, and canonical staging.poi.
"""
from __future__ import annotations

import pathlib
import pickle

import numpy as np
import osmnx as ox
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra

from loci import db as locidb
from loci.score.walkgraph import OUT as GRAPH_PATH

THRESHOLDS = {5: 400.0, 10: 800.0, 15: 1200.0}  # walk-minutes -> metres @ 80 m/min
WALK_M_PER_MIN = 80.0
DIST_LIMIT = 2400.0   # 30 min: how far the persisted hex_poi_distance table reaches
MAXCUT = max(THRESHOLDS.values())
BATCH = 100
MIN_COMPONENT = 100  # drop tiny isolated graph fragments (park loops, plaza stubs)


def _to_csr(G):
    """Undirected CSR adjacency on 'length', keeping the min length per node pair."""
    nodes = list(G.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    # OSMnx MultiDiGraph already carries both u->v and v->u; keep the MIN length
    # per directed pair. Do NOT mirror manually — csr_matrix SUMS duplicate
    # (row,col) entries, which would double every distance.
    best: dict[tuple[int, int], float] = {}
    for u, v, d in G.edges(data=True):
        length = float(d.get("length", 0.0))
        key = (idx[u], idx[v])
        if key not in best or length < best[key]:
            best[key] = length
    rows = [k[0] for k in best]
    cols = [k[1] for k in best]
    data = list(best.values())
    A = sp.csr_matrix((data, (rows, cols)), shape=(len(nodes), len(nodes)))
    return A, idx


def _prune(G, min_component: int):
    """Drop graph components smaller than min_component: the big components are the
    real separated landmasses (Manhattan, Staten Island, the Rockaways) and must stay
    split, but thousands of tiny fragments would make a hex or POI snapped onto one
    reach nothing — a false zero, i.e. a fake retail gap."""
    import networkx as nx
    keep = set()
    for comp in nx.weakly_connected_components(G):
        if len(comp) >= min_component:
            keep |= comp
    if len(keep) < G.number_of_nodes():
        G = G.subgraph(keep).copy()
    return G


def compute_distances(G, hexes, pois, limit: float = DIST_LIMIT, min_component: int = MIN_COMPONENT):
    """Yield batches of (h3, poi_id, category, network_m) for every pair within `limit`
    metres along the graph. hexes: [(h3, lon, lat)]; pois: [(poi_id, category, lon, lat)].
    One bounded scipy Dijkstra per batch of hex nodes; POIs sharing a node are expanded."""
    G = _prune(G, min_component)
    A, idx = _to_csr(G)
    hex_nidx = np.array([idx[n] for n in ox.distance.nearest_nodes(
        G, X=[h[1] for h in hexes], Y=[h[2] for h in hexes])])
    poi_nidx = np.array([idx[n] for n in ox.distance.nearest_nodes(
        G, X=[p[2] for p in pois], Y=[p[3] for p in pois])])
    poi_cols, inv = np.unique(poi_nidx, return_inverse=True)   # unique POI nodes
    members: list[list[int]] = [[] for _ in poi_cols]           # node -> POI positions
    for pi, col in enumerate(inv):
        members[col].append(pi)
    for s in range(0, len(hex_nidx), BATCH):
        batch = hex_nidx[s:s + BATCH]
        D = dijkstra(A, directed=False, indices=batch, limit=limit)[:, poi_cols]
        rows = []
        for bi, ci in zip(*np.nonzero(np.isfinite(D))):
            h = hexes[s + bi][0]
            d = float(D[bi, ci])
            for pi in members[ci]:
                rows.append((h, pois[pi][0], pois[pi][1], d))
        yield rows


def compute_access(G, hexes, pois, min_component: int = MIN_COMPONENT):
    """hexes: [(h3, lon, lat)]; pois: [(category, lon, lat)] or [(poi_id, category, lon, lat)].
    Returns rows of (h3, category, threshold_min, n_reachable, served_share) for
    n_reachable > 0 — derived by counting compute_distances() at each threshold, so the
    counts and the persisted distances can never disagree."""
    if pois and len(pois[0]) == 3:
        pois = [(str(i), c, lon, lat) for i, (c, lon, lat) in enumerate(pois)]
    counts: dict[tuple[str, str, int], int] = {}
    for rows in compute_distances(G, hexes, pois, limit=MAXCUT, min_component=min_component):
        for h, _pid, cat, d in rows:
            for tmin, tm in THRESHOLDS.items():
                if d <= tm:
                    counts[(h, cat, tmin)] = counts.get((h, cat, tmin), 0) + 1
    return [(h, cat, tmin, n, 1.0) for (h, cat, tmin), n in counts.items()]


def build_access(con, graph_path: pathlib.Path = GRAPH_PATH, limit: float = DIST_LIMIT) -> int:
    """Persist analysis.hex_poi_distance (every pair within `limit` m), then derive
    analysis.hex_access from it in SQL. Returns the number of hex_access rows."""
    import pandas as pd
    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    hexes = con.execute("SELECT h3_index, ST_X(centroid), ST_Y(centroid) FROM analysis.hex").fetchall()
    pois = con.execute(
        """SELECT p.poi_id, p.category, ST_X(p.geom), ST_Y(p.geom)
           FROM staging.poi p JOIN analysis.poi_dedup d
             ON d.poi_id = p.poi_id AND d.is_canonical""").fetchall()
    con.execute("DELETE FROM analysis.hex_poi_distance")
    n_pairs = 0
    for rows in compute_distances(G, hexes, pois, limit=limit):
        if not rows:
            continue
        df = pd.DataFrame(rows, columns=["h3_index", "poi_id", "category", "network_m"])
        con.register("_dist", df)
        con.execute("INSERT INTO analysis.hex_poi_distance SELECT h3_index, poi_id, category, network_m FROM _dist")
        con.unregister("_dist")
        n_pairs += len(df)
    con.execute("DELETE FROM analysis.hex_access")
    for tmin, tm in THRESHOLDS.items():
        con.execute("""INSERT INTO analysis.hex_access
            SELECT h3_index, category, ?, count(*), 1.0 FROM analysis.hex_poi_distance
            WHERE network_m <= ? GROUP BY 1, 2""", [tmin, tm])
    return con.execute("SELECT count(*) FROM analysis.hex_access").fetchone()[0]
