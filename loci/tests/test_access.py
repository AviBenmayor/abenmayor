import networkx as nx
from loci.score.access import compute_access


def _line_graph(n=13):
    """n nodes on a W-E line ~100 m apart at NYC latitude, with a CRS."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    dx = 100 / 84400.0  # ~100 m in degrees lon at lat 40.75
    for i in range(n):
        G.add_node(i, x=-73.98 + i * dx, y=40.75)
    for i in range(n - 1):
        G.add_edge(i, i + 1, length=100.0)
        G.add_edge(i + 1, i, length=100.0)
    return G


def test_counts_and_threshold_boundaries():
    G = _line_graph()
    hexes = [("h", G.nodes[0]["x"], 40.75)]                 # hex at node 0
    pois = [("grocery", G.nodes[2]["x"], 40.75),            # 200 m
            ("grocery", G.nodes[5]["x"], 40.75)]            # 500 m
    rows = {(c, t): n for _, c, t, n, _ in compute_access(G, hexes, pois, min_component=1)}
    # 5 min = 400 m: only the 200 m grocery -> 1
    assert rows[("grocery", 5)] == 1
    # 10 min = 800 m and 15 min = 1200 m: both -> 2
    assert rows[("grocery", 10)] == 2
    assert rows[("grocery", 15)] == 2


def test_absent_category_not_emitted():
    G = _line_graph()
    hexes = [("h", G.nodes[0]["x"], 40.75)]
    pois = [("pharmacy", G.nodes[11]["x"], 40.75)]          # 1100 m -> only 15 min
    rows = {(c, t): n for _, c, t, n, _ in compute_access(G, hexes, pois, min_component=1)}
    assert ("pharmacy", 5) not in rows                      # 1100 m > 400
    assert ("pharmacy", 10) not in rows                     # 1100 m > 800
    assert rows[("pharmacy", 15)] == 1                      # 1100 m <= 1200
