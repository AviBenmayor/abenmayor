"""MTA transit-access control onto the H3 grid (GTM-23).

Primary variable: walk_m_to_subway = network-distance (not straight-line) from a
hex's centroid node to the nearest subway STATION, via one scipy min_only
Dijkstra seeded from all station nodes on the walk graph. subway_routes = the
daytime route count at the nearest station (transit quality — a 12-route complex
is not a single-route stop).

Note: the MTA entrances dataset (68hr-j2j7) returned empty at build time, so
station points are used rather than entrances. A station point sits near its
entrances, so the distance is close; the small loss of precision is documented.
Writes only the MTA columns of analysis.hex_controls via UPSERT, co-existing with
the PLUTO writer.
"""
from __future__ import annotations

import pathlib
import pickle

import networkx as nx
import numpy as np
import osmnx as ox
import requests
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from loci import db as locidb
from loci.score.access import MIN_COMPONENT, _to_csr
from loci.score.walkgraph import OUT as GRAPH_PATH

STATIONS_URL = "https://data.ny.gov/resource/39hk-dx4f.json"
MAX_WALK = 3000.0  # m; beyond this, treat subway as not walkable (NULL)


def _fetch_stations() -> list[dict]:
    resp = requests.get(STATIONS_URL, params={"$limit": 2000}, timeout=90)
    resp.raise_for_status()
    return resp.json()


def build_mta_controls(con, graph_path: pathlib.Path = GRAPH_PATH) -> int:
    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    keep: set = set()
    for comp in nx.weakly_connected_components(G):
        if len(comp) >= MIN_COMPONENT:
            keep |= comp
    G = G.subgraph(keep).copy()
    A, idx = _to_csr(G)

    stations = _fetch_stations()
    # Route count is a COMPLEX property: a hub like Times Sq is many station rows
    # (one per line). Union daytime routes across each complex_id so subway_routes
    # reflects the whole interchange, not one platform.
    complex_routes: dict[str, set] = {}
    for s in stations:
        cid = s.get("complex_id")
        complex_routes.setdefault(cid, set()).update((s.get("daytime_routes") or "").split())
    slat, slon, sroutes = [], [], []
    for s in stations:
        try:
            la, lo = float(s["gtfs_latitude"]), float(s["gtfs_longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        slat.append(la); slon.append(lo)
        sroutes.append(len(complex_routes.get(s.get("complex_id"), ())))
    slat = np.array(slat); slon = np.array(slon); sroutes = np.array(sroutes)

    st_nodes = ox.distance.nearest_nodes(G, X=list(slon), Y=list(slat))
    st_idx = np.unique(np.array([idx[n] for n in st_nodes]))
    dist = dijkstra(A, directed=False, indices=st_idx, min_only=True, limit=MAX_WALK)

    hexrows = con.execute("SELECT h3_index, ST_X(centroid), ST_Y(centroid) FROM analysis.hex").fetchall()
    hlon = [r[1] for r in hexrows]; hlat = [r[2] for r in hexrows]
    hex_nodes = ox.distance.nearest_nodes(G, X=hlon, Y=hlat)
    hex_nidx = np.array([idx[n] for n in hex_nodes])
    walk_m = dist[hex_nidx]

    tree = cKDTree(np.c_[slon, slat])
    _, ni = tree.query(np.c_[hlon, hlat])
    routes = sroutes[ni]

    rows = []
    for i, (h, _, _) in enumerate(hexrows):
        wm = float(walk_m[i]) if np.isfinite(walk_m[i]) else None
        rows.append((h, wm, int(routes[i])))

    import pandas as pd
    df = pd.DataFrame(rows, columns=["h3_index", "walk_m_to_subway", "subway_routes"])
    con.register("_mta", df)
    con.execute("""
        INSERT INTO analysis.hex_controls (h3_index, walk_m_to_subway, subway_routes)
        SELECT h3_index, walk_m_to_subway, subway_routes FROM _mta
        ON CONFLICT (h3_index) DO UPDATE SET
            walk_m_to_subway = EXCLUDED.walk_m_to_subway,
            subway_routes    = EXCLUDED.subway_routes
    """)
    con.unregister("_mta")
    return len(df)
