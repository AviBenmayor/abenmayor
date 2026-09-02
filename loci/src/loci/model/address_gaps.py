"""Address-level gap analysis (per building), then let same-gap buildings cluster.

For every residential tax lot (PLUTO ~ a building/address), compute which
daily-needs categories are reachable on foot (<=800 m network) and which
"expected" ones (present for >=80% of buildings) are conspicuously missing. The
action signal is clusters of nearby buildings sharing the same missing business.

Reuses the walk graph: one multi-source min-distance Dijkstra per category gives
each graph node its distance to the nearest business of that category; a building
inherits its nearest node's reachability. Fast at ~300k buildings.
"""
from __future__ import annotations

import pathlib, pickle, h3
import numpy as np, pandas as pd, osmnx as ox
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.score.access import MIN_COMPONENT, _to_csr
from loci.score.walkgraph import OUT as GRAPH_PATH
from loci.grid.pluto import PLUTO_CSV

THRESH_M = 800.0
BOROCODES = ("1","3","4")  # Manhattan, Brooklyn, Queens
EXPECTED = 0.80
ALLCATS = list(CATEGORIES)


def run(out_geojson: pathlib.Path):
    con = locidb.connect(read_only=True)
    G = pickle.load(open(GRAPH_PATH, "rb"))
    import networkx as nx
    keep = set()
    for comp in nx.weakly_connected_components(G):
        if len(comp) >= MIN_COMPONENT: keep |= comp
    G = G.subgraph(keep).copy()
    A, idx = _to_csr(G)
    N = A.shape[0]

    # per-node served distance to nearest POI, per category
    served = np.zeros((N, len(ALLCATS)), dtype=bool)
    for ci, cat in enumerate(ALLCATS):
        pts = con.execute("""SELECT ST_X(p.geom), ST_Y(p.geom) FROM staging.poi p
            JOIN analysis.poi_dedup d ON d.poi_id=p.poi_id AND d.is_canonical
            WHERE p.category=?""", [cat]).fetchall()
        if not pts: continue
        nodes = ox.distance.nearest_nodes(G, X=[x for x,_ in pts], Y=[y for _,y in pts])
        src = np.unique([idx[n] for n in nodes])
        dist = dijkstra(A, directed=False, indices=src, min_only=True, limit=THRESH_M)
        served[:, ci] = np.isfinite(dist)

    # residential buildings from PLUTO
    lots = con.execute(f"""
        SELECT TRY_CAST(latitude AS DOUBLE) lat, TRY_CAST(longitude AS DOUBLE) lon,
               TRY_CAST(unitsres AS DOUBLE) units, address, bbl
        FROM read_csv('{PLUTO_CSV}', ALL_VARCHAR=TRUE)
        WHERE TRY_CAST(unitsres AS DOUBLE)>0 AND TRY_CAST(latitude AS DOUBLE) IS NOT NULL
          AND borocode IN ('1','3','4')
    """).df()
    lots = lots[(lots.lat.between(40.4,41.0)) & (lots.lon.between(-74.3,-73.6))].reset_index(drop=True)
    lots["address"] = lots["address"].fillna("").astype(str)
    lot_nodes = ox.distance.nearest_nodes(G, X=lots.lon.tolist(), Y=lots.lat.tolist())
    lni = np.array([idx[n] for n in lot_nodes])
    lot_served = served[lni]                                 # (n_lots, n_cats)

    prev = lot_served.mean(axis=0)                           # per-category prevalence across buildings
    expected = np.array([prev[i] >= EXPECTED for i in range(len(ALLCATS))])
    expected_or_bar = expected.copy()
    expected_or_bar[ALLCATS.index("bar")] = True             # user wants bars too
    missing = expected_or_bar[None, :] & ~lot_served         # (expected + bar) but not reachable

    print("building-level prevalence (share reachable):")
    for i, c in enumerate(ALLCATS):
        print(f"  {c:14} {prev[i]*100:4.0f}%  {'[expected]' if expected[i] else ''}")

    has_gap = missing.any(axis=1)
    print(f"\nresidential buildings: {len(lots):,}; with >=1 conspicuous gap: {has_gap.sum():,}")
    # per-business building counts
    for i, c in enumerate(ALLCATS):
        n = int(missing[:, i].sum())
        if n: print(f"  missing {c:14} {n:>7,} buildings")

    # income per building from its own ACS hex (demand signal)
    inc = dict(con.execute("SELECT h3_index, median_hh_income FROM analysis.hex_demographics WHERE acs_year=2023").fetchall())
    import json
    lm = lots[has_gap].reset_index(drop=True); mm = missing[has_gap]
    pts = []
    for r in range(len(lm)):
        mask = 0
        for i in range(len(ALLCATS)):
            if mm[r, i]: mask |= (1 << i)
        cell = h3.latlng_to_cell(float(lm.lat[r]), float(lm.lon[r]), 9)
        income = int(inc.get(cell) or 0)
        pts += [round(float(lm.lon[r]),5), round(float(lm.lat[r]),5), mask, int(lm.units[r]), income]
    # compact flat array [lon,lat,mask,units,income]*n
    (out_geojson.parent/"gap_buildings.json").write_text(json.dumps({"pts":pts,"n":len(lm),"stride":5},separators=(",",":")))
    meta = {"cats":ALLCATS,"catLabels":[CATEGORIES[c].label for c in ALLCATS],
            "expected":[bool(expected[i]) for i in range(len(ALLCATS))],
            "prevalence":{ALLCATS[i]:round(float(prev[i]),3) for i in range(len(ALLCATS))},
            "gapCounts":{ALLCATS[i]:int(missing[:,i].sum()) for i in range(len(ALLCATS)) if missing[:,i].sum()},
            "nBuildings":int(len(lots)),"nGap":int(has_gap.sum())}
    (out_geojson.parent/"buildings_meta.json").write_text(json.dumps(meta))
    print(f"\nwrote {len(lm):,} gap-building points (compact, w/ income) -> webmap/gap_buildings.json")


if __name__ == "__main__":
    run(pathlib.Path("webmap/gap_buildings.geojson"))
