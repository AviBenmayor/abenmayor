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
from loci.score.supply import DEFAULT_SUPPLY_SET, canonical_poi_sql

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


def _canonical_pois(con, core_only: bool, supply_set: str = DEFAULT_SUPPLY_SET):
    """Supply points for the spacing diagnostic, read through analysis.poi_supply
    (D52) rather than a private is_canonical join, so this measures the SAME
    population the screen counts. `core_only` clips to the NYC core bbox; the
    coordinates are EPSG:4326 degrees (DuckDB GEOMETRY carries no SRID) and all
    distance maths downstream is on the walk graph, in metres."""
    core = ("AND ST_Y(s.geom) BETWEEN 40.49 AND 40.92 AND ST_X(s.geom) BETWEEN -74.26 AND -73.70"
            if core_only else "")
    return con.execute(
        canonical_poi_sql(supply_set) + f" {core}"
    ).fetchall()


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


# ---------------------------------------------------------------------------
# RETIRED UNDER D38 (2026-09-09). `gap_to_nearest` read analysis.hex_gaps to
# report how far each gap HEX sat from its lead-missing business. The address
# screen answers the same question better and without the table: the distance
# is `<lead_category>_nearest_m` on analysis.address_gaps, and the excess over
# reach is `lead_excess_m` -- per address, not per 0.1 km2 cell.
# `same_type_spacing` above is untouched: it reads staging.poi only, is the
# revealed-spacing evidence behind D35/D41's reach tiers, and has nothing to do
# with the hex screen.
# ---------------------------------------------------------------------------
