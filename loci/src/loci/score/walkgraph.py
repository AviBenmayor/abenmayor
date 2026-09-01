"""Pedestrian walk graph for network-distance access scoring (GTM-27).

Extends beyond the NYC boundary so cross-boundary businesses are reachable on
foot where they genuinely are (threat §7.7). retain_all=True keeps every
connected component — Staten Island, the Rockaways and other islands are NOT
walk-connected to the mainland and would otherwise be dropped. Saved as a
pickled networkx graph; the access engine (GTM-28) runs multi-source Dijkstra
over it.
"""
from __future__ import annotations

import pathlib
import pickle

import osmnx as ox

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = REPO_ROOT / "data" / "interim" / "walk_graph.pkl"

# Extended NYC bbox (west, south, east, north): grid extent + ~0.03deg (~3 km)
# buffer so businesses just over a border are reachable on foot.
BBOX = (-74.29, 40.47, -73.67, 40.95)
WALK_SPEED_M_PER_MIN = 80.0  # 4.8 km/h


def build_walk_graph(bbox=BBOX, out: pathlib.Path = OUT):
    ox.settings.overpass_url = "https://lz4.overpass-api.de/api"
    ox.settings.requests_timeout = 300
    ox.settings.overpass_rate_limit = True
    G = ox.graph_from_bbox(bbox, network_type="walk", simplify=True,
                           retain_all=True, truncate_by_edge=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        pickle.dump(G, fh)
    return G.number_of_nodes(), G.number_of_edges()


if __name__ == "__main__":
    n, e = build_walk_graph()
    print(f"walk graph: {n} nodes, {e} edges -> {OUT}")
