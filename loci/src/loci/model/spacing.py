"""Spacing diagnostics on the WALK NETWORK (read-only).

Two questions the gap screen cannot answer on its own, both measured along the
pedestrian graph — never straight-line, because waterfronts, rail cuts and
superblocks make 300 m of separation a 20-minute walk (CONTEXT.md §2.2):

1. How far apart do businesses of the SAME type sit? For a sample of each
   category's canonical POIs, the network distance to the nearest OTHER business
   of that category. Median = how clustered a trade is; tail = how often a
   business has no competitor within a walk.
2. For each gap hex, the network distance from the hex to the nearest business
   of the category it is missing. Separates a marginal 10-minute gap (900 m) from
   a real hole (3 km).

Reuses the access engine's graph, component pruning, CSR build and node snapping
so the numbers are on the same footing as `hex_access`.
"""
from __future__ import annotations

import pickle
import random

import numpy as np
import osmnx as ox
from scipy.sparse.csgraph import dijkstra

from loci.score.access import GRAPH_PATH, MIN_COMPONENT, _to_csr

BATCH = 100
WALK_M_PER_MIN = 80.0


def _graph():
    import networkx as nx
    with open(GRAPH_PATH, "rb") as fh:
        G = pickle.load(fh)
    keep = set()
    for comp in nx.weakly_connected_components(G):
        if len(comp) >= MIN_COMPONENT:
            keep |= comp
    if len(keep) < G.number_of_nodes():
        G = G.subgraph(keep).copy()
    A, idx = _to_csr(G)
    return G, A, idx


def _canonical_pois(con, core_only: bool):
    core = ("AND ST_Y(p.geom) BETWEEN 40.49 AND 40.92 AND ST_X(p.geom) BETWEEN -74.26 AND -73.70"
            if core_only else "")
    return con.execute(f"""
        SELECT p.category, ST_X(p.geom), ST_Y(p.geom) FROM staging.poi p
        JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id AND d.is_canonical
        WHERE 1=1 {core}""").fetchall()


def _snap(G, idx, lons, lats):
    return np.array([idx[n] for n in ox.distance.nearest_nodes(G, X=lons, Y=lats)])


def _pct(v, q):
    return float(np.quantile(v, q)) if len(v) else float("nan")


def same_type_spacing(con, core_only: bool = True, walk_m: float = 800.0,
                      per_category: int = 2000, limit_m: float = 2400.0, seed: int = 20260902,
                      graph=None) -> list[tuple]:
    """(category, n_total, n_sampled, p10, median, p90, share_beyond_walk, share_beyond_limit).
    Network metres to the nearest OTHER canonical business of the same category.
    Distances beyond `limit_m` are censored (reported as > limit, counted in the last column)."""
    G, A, idx = graph or _graph()
    pois = _canonical_pois(con, core_only)
    nodes = _snap(G, idx, [p[1] for p in pois], [p[2] for p in pois])
    rng = random.Random(seed)
    out = []
    for cat in sorted({p[0] for p in pois}):
        members = np.array([i for i, p in enumerate(pois) if p[0] == cat])
        cat_nodes = nodes[members]
        uniq, counts = np.unique(cat_nodes, return_counts=True)
        share_node = dict(zip(uniq.tolist(), counts.tolist()))
        sample = members if len(members) <= per_category else np.array(rng.sample(members.tolist(), per_category))
        dists = []
        for s in range(0, len(sample), BATCH):
            src = nodes[sample[s:s + BATCH]]
            D = dijkstra(A, directed=False, indices=src, limit=limit_m)
            Dsub = D[:, uniq]                                   # (b, n_uniq_cat_nodes)
            for bi, node in enumerate(src):
                if share_node[node] > 1:                        # another same-type POI on the same node
                    dists.append(0.0)
                    continue
                row = Dsub[bi].copy()
                row[np.searchsorted(uniq, node)] = np.inf       # exclude itself
                m = row.min()
                dists.append(float(m) if np.isfinite(m) else limit_m + 1)
        v = np.array(dists)
        out.append((cat, len(members), len(sample), _pct(v, .10), _pct(v, .50), _pct(v, .90),
                    float((v > walk_m).mean()), float((v > limit_m).mean())))
    return sorted(out, key=lambda r: r[4])


def gap_to_nearest(con, threshold: int = 10, core_only: bool = True, limit_m: float = 2400.0,
                   graph=None) -> list[tuple]:
    """(lead_missing, gaps, min, median, p90, n_beyond_1500m, n_beyond_limit) — network metres
    from the gap hex to the nearest canonical business of its lead-missing category, read
    straight from analysis.hex_poi_distance (pairs beyond its 30-minute reach count as > limit)."""
    rows = con.execute("""
        WITH nd AS (
          SELECT g.lead_missing,
                 (SELECT min(d.network_m) FROM analysis.hex_poi_distance d
                   WHERE d.h3_index = g.h3_index AND d.category = g.lead_missing) AS m
          FROM analysis.hex_gaps g WHERE g.threshold_min = ?)
        SELECT lead_missing, count(*), min(coalesce(m, ?)), median(coalesce(m, ?)),
               quantile_cont(coalesce(m, ?), 0.9), sum((coalesce(m, ?) > 1500)::int), sum((m IS NULL)::int)
        FROM nd GROUP BY 1 ORDER BY 2 DESC""", [threshold, limit_m + 1, limit_m + 1, limit_m + 1, limit_m + 1]).fetchall()
    return [(r[0], r[1], float(r[2]), float(r[3]), float(r[4]), int(r[5]), int(r[6])) for r in rows]
