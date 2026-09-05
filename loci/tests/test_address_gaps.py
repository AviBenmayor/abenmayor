"""Unit tests for the address-level gap screen (model/address_gaps.py),
CHECKPOINT D33/D38/D39/D41 -- the continuous, reach-independent-gate ranking
that supersedes the old 800m/80% rule.

No DB, no real walk graph: same synthetic line-graph fixture shape as
tests/test_conveniences.py (compute_address_convenience shares this Dijkstra
code path). Runs in well under a second.
"""
from __future__ import annotations

import networkx as nx
import numpy as np

from loci.categories import CATEGORIES
from loci.model.address_gaps import (
    ALLCATS,
    UNITS_CAP,
    _address_nearest_matrix_from_graph,
    _cap_units,
    compute_gap_metrics,
)


def _line_graph(n=13):
    """n nodes on a W-E line ~100 m apart at NYC latitude, with a CRS --
    identical fixture shape to tests/test_conveniences.py's `_line_graph`."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    dx = 100 / 84400.0  # ~100 m in degrees lon at lat 40.75
    for i in range(n):
        G.add_node(i, x=-73.98 + i * dx, y=40.75)
    for i in range(n - 1):
        G.add_edge(i, i + 1, length=100.0)
        G.add_edge(i + 1, i, length=100.0)
    return G


def _full_reach(**overrides: float) -> dict[str, float]:
    """A complete reach dict (all 15 categories -- compute_gap_metrics fails
    closed on an incomplete one) defaulting every category to a very large
    distance ("never a gap") except the ones named in `overrides`."""
    r = {c: 1.0e6 for c in CATEGORIES}
    r.update(overrides)
    return r


def _fixture():
    """Two addresses, three categories with POIs at fixed network distances:
      A0 (node 0): grocery 200 m, pharmacy 400 m, hardware 1000 m
      A1 (node 6): grocery 400 m, pharmacy 200 m, hardware  400 m
    (node i sits i*100 m along the line; POIs at nodes 2, 4, 10.) The other
    12 categories have no POI at all -- censored at cap_m, independent of
    their reach value.
    """
    G = _line_graph()
    addresses = [
        ("A0", G.nodes[0]["x"], 40.75),
        ("A1", G.nodes[6]["x"], 40.75),
    ]
    pois = [
        ("grocery", G.nodes[2]["x"], 40.75),
        ("pharmacy", G.nodes[4]["x"], 40.75),
        ("hardware", G.nodes[10]["x"], 40.75),
    ]
    return G, addresses, pois


# ------------------------------------------------------------- (a) the gate

def test_gate_is_reach_independent():
    """Eligibility depends only on the fixed 800m/min_present window, never
    on the reach table -- two wildly different reach dicts must produce the
    identical eligible set and the identical present_count."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)

    tight_reach = _full_reach(grocery=50.0, pharmacy=50.0, hardware=50.0)
    loose_reach = _full_reach(grocery=5000.0, pharmacy=5000.0, hardware=5000.0)

    m_tight = compute_gap_metrics(M, tight_reach, min_present=3)
    m_loose = compute_gap_metrics(M, loose_reach, min_present=3)

    assert list(m_tight["present_count"]) == list(m_loose["present_count"])
    assert list(m_tight["eligible"]) == list(m_loose["eligible"])
    # not vacuous: A0 has grocery(200m)+pharmacy(400m) within 800m but NOT
    # hardware (1000m > 800m) -> present_count 2, ineligible at min_present=3.
    # A1 has all three within 800m -> present_count 3, eligible.
    assert bool(m_tight["eligible"][0]) is False
    assert bool(m_tight["eligible"][1]) is True


# ------------------------------------------------------- (b) monotonicity

def test_tightening_reach_only_grows_the_gap_set():
    """reach * 0.8 must yield a SUPERSET of (address, category) pairs with
    ratio > 1 -- shrinking any reach can only add gaps, never remove one."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    base_reach = _full_reach(grocery=300.0, pharmacy=300.0, hardware=1200.0)
    tight_reach = {c: 0.8 * v for c, v in base_reach.items()}

    loose = compute_gap_metrics(M, base_reach, min_present=1)
    tight = compute_gap_metrics(M, tight_reach, min_present=1)

    loose_gap = loose["ratio"] > 1.0
    tight_gap = tight["ratio"] > 1.0
    assert np.all(loose_gap <= tight_gap)
    assert (tight_gap & ~loose_gap).any(), "tightening never actually bit -- test would be vacuous"


# --------------------------------------------------- (c) continuous ratio

def test_ratio_monotone_in_nearest_m():
    """Moving a category's POI farther from an address (reach fixed) can
    only increase that address's ratio for the category, never decrease it."""
    G = _line_graph()
    reach = _full_reach(grocery=500.0)
    addresses = [("A0", G.nodes[0]["x"], 40.75)]

    prev_ratio = -1.0
    for poi_node in (1, 2, 3, 4, 5):
        pois = [("grocery", G.nodes[poi_node]["x"], 40.75)]
        M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
        m = compute_gap_metrics(M, reach, min_present=0)
        ratio = m["ratio"][0, ALLCATS.index("grocery")]
        assert ratio >= prev_ratio
        prev_ratio = ratio
    assert prev_ratio > -1.0  # the loop ran and moved distance


# ------------------------------------------------------------- (d) lead

def test_lead_is_max_ratio_category():
    """lead_category is always the argmax of that row's ratio vector."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    reach = _full_reach(grocery=100.0, pharmacy=1000.0, hardware=5000.0)
    m = compute_gap_metrics(M, reach, min_present=1)

    for i in range(len(addresses)):
        expected_idx = int(np.argmax(m["ratio"][i]))
        assert m["lead_category"][i] == ALLCATS[expected_idx]
        got_idx = ALLCATS.index(m["lead_category"][i])
        excess = M[i, got_idx] - reach[ALLCATS[got_idx]]
        assert m["lead_excess_m"][i] == excess


def test_lead_tiebreak_prefers_larger_nearest_m():
    """Two categories tied exactly on ratio: the lead must be whichever has
    the larger RAW nearest_m -- the more conspicuous absence -- not just
    whichever comes first in ALLCATS order."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    # A0: grocery 200m / reach 200 -> ratio 1.0; pharmacy 400m / reach 400 -> ratio 1.0 (tie)
    reach = _full_reach(grocery=200.0, pharmacy=400.0, hardware=1.0e6)
    m = compute_gap_metrics(M, reach, min_present=1)

    g_ratio = m["ratio"][0, ALLCATS.index("grocery")]
    p_ratio = m["ratio"][0, ALLCATS.index("pharmacy")]
    assert g_ratio == p_ratio == 1.0
    assert m["lead_category"][0] == "pharmacy"  # 400m > 200m wins the tie


# --------------------------------------------------------- (e) units cap

def test_units_cap_applies():
    raw = np.array([10.0, 500.0, 10000.0, 0.0])
    capped = _cap_units(raw)
    assert list(capped) == [10.0, 500.0, UNITS_CAP, 0.0]
    assert UNITS_CAP == 500.0


# ---------------------------------------------- (f) load_reach fails closed

def test_load_reach_fails_closed_on_missing_category():
    from loci.reach import _check_reach_complete

    incomplete = {"grocery": 800.0, "pharmacy": 800.0}  # missing 13 categories
    try:
        _check_reach_complete(incomplete, "tiers")
    except ValueError as e:
        assert "hardware" in str(e)
        assert "tiers" in str(e)
    else:
        raise AssertionError("expected ValueError for an incomplete reach table")


def test_compute_gap_metrics_fails_closed_on_incomplete_reach():
    """Same fail-closed contract, exercised through compute_gap_metrics
    directly (the function tests/test_address_gaps.py's other cases call)."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    incomplete = {"grocery": 300.0, "pharmacy": 300.0}
    try:
        compute_gap_metrics(M, incomplete)
    except ValueError as e:
        assert "hardware" in str(e)
    else:
        raise AssertionError("expected ValueError for an incomplete reach table")
