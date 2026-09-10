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


# ---------------------------------------------------------------------------
# Station RIDERSHIP (D63, 2026-09-10). `analysis.hex_controls.subway_riders_2024`
# was NULL on all 8,321 rows, and the reason was neither a join bug nor a rename:
# NOTHING EVER WROTE IT. The column is a schema stub that landed ahead of its
# loader -- `build_mta_controls` above writes walk_m_to_subway and subway_routes
# and nothing else, and registry.yaml still carries `mta_subway_ridership` as
# `status: planned`. docs/bar_age_nyc.md §1.2 had to report the absence rather
# than use it as a nighttime-population control.
#
# The obstacle was never access: it is that wujg-7c2s is an HOURLY feed of
# ~110M rows, and a single server-side aggregation over a whole year times out
# (60 s, HTTP 000, measured). Chunked by CALENDAR MONTH it returns in ~18 s per
# request, so twelve requests build the annual total. That is the whole fix.
RIDERSHIP_URL = "https://data.ny.gov/resource/wujg-7c2s.json"
RIDERSHIP_YEAR = 2024


def _fetch_complex_ridership(year: int) -> dict[str, float]:
    """{station_complex_id: annual ridership} for `year`, summed month by month.

    Server-side `sum(ridership)` grouped by complex, one request per calendar
    month. `transfers` is deliberately NOT added: a transfer is a rider already
    counted at their entry complex, so summing both double-counts the network.
    `transit_mode` is pinned to subway -- the feed also carries Staten Island
    Railway and the Roosevelt Island tram, which are not what this column means.
    """
    totals: dict[str, float] = {}
    for month in range(1, 13):
        start = f"{year}-{month:02d}-01T00:00:00"
        end = (f"{year + 1}-01-01T00:00:00" if month == 12
               else f"{year}-{month + 1:02d}-01T00:00:00")
        resp = requests.get(RIDERSHIP_URL, params={
            "$select": "station_complex_id,sum(ridership) as riders",
            "$where": (f"transit_timestamp >= '{start}' AND transit_timestamp < '{end}' "
                       "AND transit_mode = 'subway'"),
            "$group": "station_complex_id",
            "$limit": 5000,
        }, timeout=300)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            raise RuntimeError(f"{RIDERSHIP_URL}: no ridership rows for {year}-{month:02d}")
        for r in rows:
            totals[str(r["station_complex_id"])] = (
                totals.get(str(r["station_complex_id"]), 0.0) + float(r["riders"]))
    return totals


def build_subway_ridership(con, year: int = RIDERSHIP_YEAR) -> tuple[int, int]:
    """Fill `analysis.hex_controls.subway_riders_2024`. Returns (hexes written,
    complexes matched).

    DEFINITION, and it matters: the annual ridership of the station complex
    NEAREST the hex centroid -- the same convention `subway_routes` already
    uses, so the two transit-quality columns are read the same way. It is NOT a
    catchment sum, and it is NOT masked by walkability: a hex far from any
    station still reports its nearest complex's ridership, and the caller gates
    on `walk_m_to_subway` (NULL beyond 3 km) exactly as it must for
    `subway_routes`.

    Straight-line nearest, not network: this is a QUALITY tag on a station the
    hex has already been matched to by `build_mta_controls`, not a distance
    measurement, and the network distance to that station is the column beside
    it. Writes only this one column by UPSERT, co-existing with the PLUTO and
    walk-distance writers.

    STATEN ISLAND COMES BACK NULL, and that is correct, not a miss: its nearest
    "station" is Staten Island Railway, which `transit_mode = 'subway'` excludes
    from the ridership feed. 6,768 of 8,321 hexes get a value; the 1,553 that do
    not are 1,553 of Staten Island's 1,555. Do not paper over it with an SIR
    total -- SIR ridership is not subway ridership and the column would stop
    meaning one thing.
    """
    riders = _fetch_complex_ridership(year)
    stations = _fetch_stations()

    slat, slon, sriders = [], [], []
    matched = set()
    for s in stations:
        try:
            la, lo = float(s["gtfs_latitude"]), float(s["gtfs_longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        cid = str(s.get("complex_id"))
        slat.append(la); slon.append(lo); sriders.append(riders.get(cid))
        if cid in riders:
            matched.add(cid)
    # Fail closed on an ID-space change: `station_complex_id` in the ridership
    # feed is the Stations feed's `complex_id`, and if that ever stops being
    # true every hex would silently receive NULL rather than an error.
    if len(matched) < 0.9 * len(riders):
        raise RuntimeError(
            f"only {len(matched)} of {len(riders)} ridership complexes matched a station "
            "complex_id -- the two feeds' ID spaces have diverged; do not write")

    hexrows = con.execute(
        "SELECT h3_index, ST_X(centroid), ST_Y(centroid) FROM analysis.hex").fetchall()
    hlon = [r[1] for r in hexrows]; hlat = [r[2] for r in hexrows]
    _, ni = cKDTree(np.c_[slon, slat]).query(np.c_[hlon, hlat])

    import pandas as pd
    df = pd.DataFrame({
        "h3_index": [r[0] for r in hexrows],
        "subway_riders_2024": [sriders[i] for i in ni],
    })
    con.register("_mta_riders", df)
    try:
        con.execute("""
            INSERT INTO analysis.hex_controls (h3_index, subway_riders_2024)
            SELECT h3_index, subway_riders_2024 FROM _mta_riders
            ON CONFLICT (h3_index) DO UPDATE SET
                subway_riders_2024 = EXCLUDED.subway_riders_2024
        """)
    finally:
        con.unregister("_mta_riders")
    return len(df), len(matched)
