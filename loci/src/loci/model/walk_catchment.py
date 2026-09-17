"""One 400 m NETWORK sweep for any point-weighted address measure.

WHY THIS EXISTS
---------------
Three measures landed on 2026-09-17 -- the licence non-renewal count
(model/licence_event.py), the premises tenure prior (model/storefront_tenure.py)
and the category-blind filing counts (model/storefront_pipeline.py) -- and each
needs the same thing `storefront_pipeline.compute_openings` and
`supply_ratio.build_supply_ratio` already do: snap a set of points to the walk
graph, snap every address to it, and sum per-point weights within `radius_m`
NETWORK metres of each address. Copying that block a third time is how the
engine drifts (one copy mirrors edges by hand and doubles every distance --
score/access._to_csr says why not). So the block lives here once.

THE ENGINE IS REUSED, NOT RE-IMPLEMENTED. `score/access._prune` + `_to_csr`
build the CSR, `supply_ratio.node_weights` accumulates the weights, and
`supply_ratio.catchment_sums` runs the bounded Dijkstra. Nothing here is a
straight line: 400 m network is the project's one definition of within reach.

Points are ACCUMULATED, never deduplicated: two licences on one corner are two
licences. Weights are floats so a column can carry a run length as well as a
count; the caller rounds what should be an integer.

Caveat the database cannot enforce: `lon`/`lat` on the point frame are
EPSG:4326 by convention. The graph is in EPSG:4326 too, and OSMnx snaps in
degrees, which is fine for nearest-node but is why every metric number here
comes from edge lengths and never from coordinate arithmetic.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd


def load_addresses(con, boroughs: list[str] | None) -> pd.DataFrame:
    """Every address in scope, ordered so two runs snap identically."""
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        addr = con.execute(
            f"SELECT address_id, borough, lon, lat FROM analysis.address "
            f"WHERE borough IN ({holes}) ORDER BY borough, address_id",
            list(boroughs)).fetchdf()
    else:
        addr = con.execute(
            "SELECT address_id, borough, lon, lat FROM analysis.address "
            "ORDER BY borough, address_id").fetchdf()
    if addr.empty:
        raise RuntimeError(
            f"no addresses in analysis.address for boroughs={boroughs}. Run "
            f"`loci address-gaps` first; an empty frame would RESET every "
            f"column to NULL and write nothing back.")
    return addr


def network_sums(points: pd.DataFrame, weight_cols: list[str],
                 addresses: pd.DataFrame, *,
                 radius_m: float | None = None,
                 graph_path: pathlib.Path | None = None,
                 batch: int | None = None) -> tuple[pd.DataFrame, dict]:
    """(frame of address_id, borough + one summed column per `weight_cols`, report).

    `points` carries `lon`, `lat` and the weight columns (NaN = 0). Every
    address gets a row; 0 is a value (owner rule 2026-09-13: no eligibility
    gate, every street represented).
    """
    import pickle

    import osmnx as ox

    from loci.model.conveniences import graph_version
    from loci.model.supply_ratio import BATCH, catchment_sums, node_weights
    from loci.score.access import MIN_COMPONENT, THRESHOLDS, _prune, _to_csr
    from loci.score.walkgraph import OUT as GRAPH_PATH

    radius_m = float(radius_m if radius_m is not None else THRESHOLDS[5])
    graph_path = pathlib.Path(graph_path or GRAPH_PATH)
    batch = int(batch or BATCH)
    missing = [c for c in weight_cols if c not in points.columns]
    if missing:
        raise RuntimeError(f"walk_catchment: point frame is missing {missing}")
    pts = points.dropna(subset=["lon", "lat"]).reset_index(drop=True)

    with graph_path.open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)
    n_nodes = A.shape[0]

    nodes_of, weights = {}, {}
    if len(pts):
        p_nodes = ox.distance.nearest_nodes(
            Gp, X=pts["lon"].tolist(), Y=pts["lat"].tolist())
        p_nidx = np.array([idx[n] for n in np.atleast_1d(p_nodes)], dtype=np.int64)
    else:
        p_nidx = np.zeros(0, dtype=np.int64)
    for c in weight_cols:
        w = pd.to_numeric(pts[c], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64) \
            if len(pts) else np.zeros(0, dtype=np.float64)
        nodes_of[c] = p_nidx
        weights[c] = w
    W = node_weights(idx, nodes_of, weights, n_nodes)

    a_nodes = ox.distance.nearest_nodes(
        Gp, X=addresses["lon"].tolist(), Y=addresses["lat"].tolist())
    a_nidx = np.array([idx[n] for n in np.atleast_1d(a_nodes)], dtype=np.int64)
    uniq, inv = np.unique(a_nidx, return_inverse=True)
    acc = catchment_sums(A, uniq, W, radius_m=radius_m, batch=batch)[inv]

    out = pd.DataFrame({"address_id": addresses["address_id"].to_numpy(),
                        "borough": addresses["borough"].to_numpy()})
    for k, c in enumerate(weight_cols):
        out[c] = acc[:, k]
    report = {
        "radius_m": radius_m,
        "graph_version": graph_version(graph_path),
        "points": len(pts),
        "points_without_coordinates": int(len(points) - len(pts)),
        "addresses": len(addresses),
        "query_nodes": int(uniq.size),
    }
    return out, report
