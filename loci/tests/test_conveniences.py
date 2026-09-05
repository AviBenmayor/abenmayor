"""Unit tests for the address-level convenience check (model/conveniences.py).

No DB, no real walk graph, no addresses.py: compute_address_convenience() takes
plain (id, lon, lat) tuples and a bare networkx graph, so the fixture is a tiny
synthetic line graph -- same shape as tests/test_access.py's `_line_graph`, which
compute_address_convenience shares its Dijkstra code path with (score/access.py).
Runs in well under a second.
"""
from __future__ import annotations

import networkx as nx

from loci.model.conveniences import ALLCATS, compute_address_convenience


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


def _full_conveniences(**overrides: float) -> dict[str, float]:
    """A complete {category: distance_m} covering all 15 categories --
    compute_address_convenience fails closed on an incomplete one -- defaulting
    every category not named in `overrides` to a large, irrelevant norm (those
    categories have no POI in the fixture, so they are always unsatisfied
    regardless of the norm's value)."""
    base = {c: 1500.0 for c in ALLCATS}
    base.update(overrides)
    return base


def _fixture():
    """Two addresses, three categories with POIs at fixed network distances:
      A0 (node 0): grocery 200 m, pharmacy 400 m, hardware 1000 m
      A1 (node 6): grocery 400 m, pharmacy 200 m, hardware  400 m
    (node i sits i*100 m along the line; POIs at nodes 2, 4, 10.)
    The other 12 categories have no POI at all -- always unsatisfied,
    independent of their norm.
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


def test_within_norm_satisfied_beyond_norm_not():
    """grocery norm 320 m: A0 (200 m) is satisfied, A1 (400 m) is not."""
    G, addresses, pois = _fixture()
    conveniences = _full_conveniences(grocery=320.0, pharmacy=640.0, hardware=960.0)
    rows = {r["address_id"]: r for r in compute_address_convenience(G, addresses, pois, conveniences, min_component=1)}

    assert rows["A0"]["distance_m"]["grocery"] == 200.0
    assert rows["A0"]["satisfied"]["grocery"] is True
    assert rows["A1"]["distance_m"]["grocery"] == 400.0
    assert rows["A1"]["satisfied"]["grocery"] is False


def test_n_unsatisfied_equals_count_of_unsatisfied_categories():
    G, addresses, pois = _fixture()
    conveniences = _full_conveniences(grocery=320.0, pharmacy=640.0, hardware=960.0)
    rows = compute_address_convenience(G, addresses, pois, conveniences, min_component=1)

    assert len(rows) == 2
    for r in rows:
        assert r["n_unsatisfied"] == sum(1 for ok in r["satisfied"].values() if not ok)
        # sanity: exactly 15 categories reported per address, all of ALLCATS.
        assert set(r["satisfied"]) == set(ALLCATS)


def test_tightening_every_norm_never_turns_unsatisfied_into_satisfied():
    """Same monotonicity bar as the reach rule (QUESTIONS D6 / test_gaps_monotonicity):
    shrinking every category's norm by 20% can only ADD unsatisfied categories,
    never remove one -- distances are unchanged, so `d <= norm` cannot flip
    False -> True when norm only shrinks."""
    # grocery norm 210 m sits just above A0's actual 200 m distance, so
    # shrinking it by 20% (to 168 m) is guaranteed to flip A0's grocery from
    # satisfied to unsatisfied -- the case that proves the test isn't vacuous.
    G, addresses, pois = _fixture()
    loose = _full_conveniences(grocery=210.0, pharmacy=640.0, hardware=960.0)
    tight = {c: 0.8 * v for c, v in loose.items()}

    before = {r["address_id"]: r["satisfied"] for r in compute_address_convenience(G, addresses, pois, loose, min_component=1)}
    after = {r["address_id"]: r["satisfied"] for r in compute_address_convenience(G, addresses, pois, tight, min_component=1)}

    for aid in before:
        for cat in ALLCATS:
            if not before[aid][cat]:
                assert not after[aid][cat], (
                    f"{aid}/{cat} was unsatisfied at the looser norm but satisfied after tightening"
                )

    # and the tightening actually bit somewhere, or the test would be vacuous:
    assert before["A0"]["grocery"] is True
    assert after["A0"]["grocery"] is False


def test_unreachable_category_beyond_cap_is_none_and_unsatisfied():
    """A category with no POI at all is unreachable within the cap: distance_m
    is None and it always counts as unsatisfied, regardless of its norm."""
    G, addresses, pois = _fixture()
    conveniences = _full_conveniences(grocery=320.0, pharmacy=640.0, hardware=960.0)
    rows = {r["address_id"]: r for r in compute_address_convenience(G, addresses, pois, conveniences, min_component=1)}

    for aid in ("A0", "A1"):
        assert rows[aid]["distance_m"]["bank"] is None
        assert rows[aid]["satisfied"]["bank"] is False


def test_fails_closed_on_incomplete_conveniences_table():
    G, addresses, pois = _fixture()
    incomplete = {"grocery": 320.0, "pharmacy": 640.0}  # missing 13 categories
    try:
        compute_address_convenience(G, addresses, pois, incomplete, min_component=1)
    except ValueError as e:
        assert "hardware" in str(e)
    else:
        raise AssertionError("expected ValueError for an incomplete conveniences table")
