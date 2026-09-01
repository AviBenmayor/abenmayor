"""Walkable access scoring (GTM-28).

For each of the 15 categories we need, per hex, the COUNT of canonical
establishments reachable within a walk threshold (n_reachable) — the saturating
DNCI is driven by that count. A multi-source Dijkstra from the POI set gives only
distance-to-nearest, not counts, so instead we run scipy's C-level Dijkstra from
the hex nodes in batches, bounded at the max threshold (1200 m), and count POIs
per category with a numpy mat-mult. Bounded + vectorized keeps it to minutes over
~7,400 hexes, without the 7,400 slow python isochrones CONTEXT.md §4.3 warns off.

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


def compute_access(G, hexes, pois, min_component: int = MIN_COMPONENT):
    """hexes: list[(h3, lon, lat)]; pois: list[(category, lon, lat)].
    Returns rows of (h3, category, threshold_min, n_reachable, served_share)
    for n_reachable > 0 (missing (hex,cat,thr) means 0 — the DNCI treats it so).

    Drops graph components smaller than MIN_COMPONENT first: the big components
    are the real separated landmasses (Manhattan, Staten Island, the Rockaways)
    and must stay split, but the thousands of tiny fragments would make a hex or
    POI snapped onto one reach nothing — a false zero, i.e. a fake retail gap."""
    import networkx as nx
    keep = set()
    for comp in nx.weakly_connected_components(G):
        if len(comp) >= min_component:
            keep |= comp
    if len(keep) < G.number_of_nodes():
        G = G.subgraph(keep).copy()
    A, idx = _to_csr(G)

    hlon = [h[1] for h in hexes]; hlat = [h[2] for h in hexes]
    hex_nidx = np.array([idx[n] for n in ox.distance.nearest_nodes(G, X=hlon, Y=hlat)])

    pcat = [p[0] for p in pois]
    plon = [p[1] for p in pois]; plat = [p[2] for p in pois]
    poi_nidx = np.array([idx[n] for n in ox.distance.nearest_nodes(G, X=plon, Y=plat)])

    cats = sorted(set(pcat))
    catpos = {c: i for i, c in enumerate(cats)}
    poi_cols = np.unique(poi_nidx)
    colpos = {c: i for i, c in enumerate(poi_cols)}
    cnt = np.zeros((len(poi_cols), len(cats)))          # POIs per (node, category)
    for nid, cat in zip(poi_nidx, pcat):
        cnt[colpos[nid], catpos[cat]] += 1

    out = []
    for s in range(0, len(hex_nidx), BATCH):
        batch = hex_nidx[s:s + BATCH]
        D = dijkstra(A, directed=False, indices=batch, limit=MAXCUT)  # (b, N)
        Dsub = D[:, poi_cols]                                          # (b, ncols)
        for tmin, tm in THRESHOLDS.items():
            ncat = (Dsub <= tm).astype(float) @ cnt                    # (b, ncats)
            for bi in range(batch.shape[0]):
                h = hexes[s + bi][0]
                for ci, cat in enumerate(cats):
                    n = int(ncat[bi, ci])
                    if n > 0:
                        out.append((h, cat, tmin, n, 1.0))
    return out


def build_access(con, graph_path: pathlib.Path = GRAPH_PATH) -> int:
    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    hexes = con.execute("SELECT h3_index, ST_X(centroid), ST_Y(centroid) FROM analysis.hex").fetchall()
    pois = con.execute(
        """SELECT p.category, ST_X(p.geom), ST_Y(p.geom)
           FROM staging.poi p JOIN analysis.poi_dedup d
             ON d.poi_id = p.poi_id AND d.is_canonical""").fetchall()
    rows = compute_access(G, hexes, pois)
    con.execute("DELETE FROM analysis.hex_access")
    import pandas as pd
    df = pd.DataFrame(rows, columns=["h3_index", "category", "threshold_min", "n_reachable", "served_share"])
    con.register("_acc", df)
    con.execute("INSERT INTO analysis.hex_access SELECT h3_index, category, threshold_min, n_reachable, served_share FROM _acc")
    con.unregister("_acc")
    return len(df)
