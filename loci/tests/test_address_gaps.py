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
    CAP_M,
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


# --------------------------------------------- (a) the gate, retired (D75)

def test_every_address_is_eligible():
    """D75, owner ruling: "If an address is truly in a super underdeveloped
    area, this would completely not count it." The gate is gone. `eligible`
    survives as an always-TRUE column, and the summary quantities it used to
    blank out -- gap_score, lead_category, lead_excess_m, n_missing -- are
    populated for EVERY address, including A0, which the old 12-of-15 rule
    would have dropped."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    # A0 can reach only grocery and pharmacy inside 800 m; twelve of its
    # fifteen categories have no POI at all. Under the retired gate it was out
    # of scope at ANY min_present above 2.
    m = compute_gap_metrics(M, _full_reach(grocery=50.0), min_present=3)

    assert list(m["eligible"]) == [True, True]
    assert m["present_count"][0] == 2      # the gate WOULD have bitten
    assert m["gap_score"][0] is not None and not np.isnan(m["gap_score"][0])
    assert m["lead_category"][0] is not None
    assert not np.isnan(m["lead_excess_m"][0])
    assert m["n_missing"][0] > 0


def test_present_count_is_still_reach_independent():
    """`present_count` outlived the gate as a descriptive statistic and a
    candidate ranking feature. It must still read only the fixed 800 m window,
    never the reach table -- two wildly different reach dicts must produce the
    identical counts."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)

    tight_reach = _full_reach(grocery=50.0, pharmacy=50.0, hardware=50.0)
    loose_reach = _full_reach(grocery=5000.0, pharmacy=5000.0, hardware=5000.0)

    m_tight = compute_gap_metrics(M, tight_reach, min_present=3)
    m_loose = compute_gap_metrics(M, loose_reach, min_present=3)

    assert list(m_tight["present_count"]) == list(m_loose["present_count"])
    # not vacuous: A0 has grocery(200m)+pharmacy(400m) within 800m but NOT
    # hardware (1000m > 800m) -> 2. A1 has all three -> 3.
    assert list(m_tight["present_count"]) == [2, 3]
    # ...and min_present no longer changes anything at all.
    assert list(compute_gap_metrics(M, tight_reach, min_present=15)["eligible"]) == [True, True]


# ------------------------------------------------------- (b) monotonicity

def test_tightening_reach_only_grows_the_gap_set():
    """reach * 0.8 must yield a SUPERSET of (address, category) pairs with
    ratio > 1 -- shrinking any reach can only add gaps, never remove one.

    This is the property D39 built the fixed gate to protect: the literal port
    gated on REACH, so tightening a reach dropped addresses out of scope faster
    than they gained gaps and the missing set SHRANK. With no gate at all (D75)
    the property is structural rather than engineered -- `ratio` reads one
    address's own nearest_m against a fixed reach and nothing else -- so the
    assertion is now made over the WHOLE universe, with no eligibility mask to
    hide behind, and `removed` is checked explicitly at zero."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    base_reach = _full_reach(grocery=300.0, pharmacy=300.0, hardware=1200.0)
    tight_reach = {c: 0.8 * v for c, v in base_reach.items()}

    loose = compute_gap_metrics(M, base_reach, min_present=1)
    tight = compute_gap_metrics(M, tight_reach, min_present=1)

    loose_gap = loose["ratio"] > 1.0
    tight_gap = tight["ratio"] > 1.0
    assert np.all(loose_gap <= tight_gap)
    assert int((loose_gap & ~tight_gap).sum()) == 0, "reach x 0.8 removed a pair"
    assert (tight_gap & ~loose_gap).any(), "tightening never actually bit -- test would be vacuous"


def test_the_non_filtering_identity_holds_over_every_address():
    """n_missing is the per-address count of ratio > 1, so summing it over ALL
    addresses must equal the size of the gap set. Before D75 this identity was
    conditioned on eligibility on both sides; the whole point of the ruling is
    that there is no longer a side to condition on."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    m = compute_gap_metrics(M, _full_reach(grocery=100.0, pharmacy=100.0, hardware=100.0))
    assert int(m["n_missing"].sum()) == int((m["ratio"] > 1.0).sum())


# --------------------------------------------------- (b2) censoring (D75)

def test_censored_flags_mark_the_cap_and_only_the_cap():
    """`nearest_m` is a Dijkstra capped at CAP_M, so a category with NOTHING
    inside the cap is recorded AT it and its ratio is a floor. The fixture's
    other twelve categories have no POI at all and must all be flagged; the
    three that do have one must not be."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    m = compute_gap_metrics(M, _full_reach())

    cens = m["censored"]
    assert cens.shape == M.shape
    for cat in ("grocery", "pharmacy", "hardware"):
        assert not cens[:, ALLCATS.index(cat)].any(), cat
    unmeasured = [c for c in ALLCATS if c not in ("grocery", "pharmacy", "hardware")]
    assert len(unmeasured) == 12
    for cat in unmeasured:
        assert cens[:, ALLCATS.index(cat)].all(), cat
    # ...and the flag means exactly `nearest_m >= CAP_M`, nothing else.
    assert np.array_equal(cens, M >= CAP_M)


def test_lead_censored_is_the_flag_at_the_lead_category():
    """`lead_censored` is what a ranking or a popup reads: TRUE means this
    address's gap_score is a FLOOR, because its worst category has nothing
    within CAP_M."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)

    # An unmeasured category (2,400 m / reach 800) beats hardware (1,000 / 800),
    # so the lead is censored.
    m = compute_gap_metrics(M, _full_reach(grocery=800.0, pharmacy=800.0,
                                           hardware=800.0, laundry=800.0))
    assert m["lead_category"][0] not in ("grocery", "pharmacy", "hardware")
    assert bool(m["lead_censored"][0]) is True

    # Give every unmeasured category a huge reach and hardware a tiny one: the
    # lead moves to a category that was actually walked, and the flag clears.
    reach = _full_reach(grocery=1.0e6, pharmacy=1.0e6, hardware=10.0)
    m2 = compute_gap_metrics(M, reach)
    assert m2["lead_category"][0] == "hardware"
    assert bool(m2["lead_censored"][0]) is False


def test_censoring_does_not_touch_the_score():
    """The handling is a FLAG, not a rule: gap_score, ratio, lead_category and
    n_missing are computed identically whether or not the flag is read. A
    censored ratio is still the smallest value that ratio could take, so the
    ranking stays monotone and conservative rather than being rewritten by an
    uncalibrated extrapolation."""
    G, addresses, pois = _fixture()
    M = _address_nearest_matrix_from_graph(G, addresses, pois, min_component=1)
    reach = _full_reach(grocery=300.0, pharmacy=300.0, hardware=800.0)
    m = compute_gap_metrics(M, reach)

    reach_arr = np.array([reach[c] for c in ALLCATS])
    assert np.allclose(m["ratio"], M / reach_arr[None, :])
    assert np.allclose(m["gap_score"], (M / reach_arr[None, :]).max(axis=1))
    assert m["censored"].any(), "fixture must actually censor something"


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


# ------------------------------- (g) the written shape and the view (D75)

def _d75_frame():
    """A two-row compute_address_gaps working frame, hand-built so the DB half
    of D75 can be tested without a walk graph. A0's lead category is censored
    (nothing within CAP_M); A1's is measured."""
    import datetime

    import pandas as pd

    rows = []
    for aid, lead, censored_cats in (("A0", "tailor_repair", set(ALLCATS) - {"grocery"}),
                                     ("A1", "hardware", set())):
        row = {
            "address_id": aid, "bbl": "1" + aid, "lon": -73.98, "lat": 40.75,
            "units": 10.0, "units_capped": 10.0, "h3_index": None,
            "nta_code": "MN0001", "neighborhood": "Somewhere", "borough": "MN",
            "present_count": 15 - len(censored_cats), "eligible": True,
            "gap_score": 2.5, "lead_category": lead, "lead_excess_m": 1440.0,
            "n_missing": max(len(censored_cats), 1), "cluster_id": "MN:%s:0" % lead,
            "lead_censored": lead in censored_cats,
            "reach_source": "tiers", "reach_hash": "h" * 12,
            "graph_version": "g", "supply_set": "principled",
            "supply_hash": "s" * 12,
            "run_at": datetime.datetime(2026, 9, 13, tzinfo=datetime.timezone.utc),
        }
        for cat in ALLCATS:
            hit = cat in censored_cats
            row[f"{cat}_nearest_m"] = CAP_M if hit else 100.0
            row[f"{cat}_ratio"] = 2.5 if hit else 0.5
            row[f"{cat}_censored"] = hit
        rows.append(row)
    return pd.DataFrame(rows)


def _written_con():
    from loci import db as locidb
    from loci.model.address_gaps import write_address_gaps

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    write_address_gaps(con, _d75_frame())
    return con


def test_the_writer_stores_eligible_true_on_every_address():
    """D75 keeps the column for schema compatibility and fills it TRUE. A
    stored FALSE would mean the gate came back."""
    con = _written_con()
    assert con.execute(
        "SELECT count(*) FROM analysis.address WHERE NOT eligible").fetchone()[0] == 0
    assert con.execute(
        "SELECT count(*) FROM analysis.address_category WHERE NOT eligible").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM analysis.address").fetchone()[0] == 2


def test_the_writer_stores_the_censoring_flags_per_category():
    con = _written_con()
    rows = dict(con.execute(
        "SELECT category, censored FROM analysis.address_category "
        "WHERE address_id = 'A0'").fetchall())
    assert rows["grocery"] is False
    assert rows["tailor_repair"] is True
    assert sum(bool(v) for v in rows.values()) == 14
    # ...and censored is exactly `nearest_m >= CAP_M`, with no third opinion.
    assert con.execute(
        "SELECT count(*) FROM analysis.address_category "
        f"WHERE censored <> (nearest_m >= {CAP_M})").fetchone()[0] == 0


def test_the_view_exposes_lead_censored_and_the_per_category_flags():
    """analysis.address_gaps is GENERATED, so a column added to the two base
    tables does not reach the view unless the SELECT list names it. This is
    that drift check for D75 -- and it pins the APPEND: every positional
    consumer of the older column order is untouched."""
    con = _written_con()
    cols = [d[0] for d in con.execute(
        "SELECT * FROM analysis.address_gaps LIMIT 0").description]
    assert "lead_censored" in cols
    for cat in ALLCATS:
        assert f"{cat}_censored" in cols, cat
    assert cols.index("gap_score") < cols.index("lead_censored")
    assert cols.index("supply_ratio_run_at") < cols.index("lead_censored")

    lead = dict(con.execute(
        "SELECT address_id, lead_censored FROM analysis.address_gaps").fetchall())
    assert lead == {"A0": True, "A1": False}
    assert con.execute(
        "SELECT tailor_repair_censored, grocery_censored FROM analysis.address_gaps "
        "WHERE address_id = 'A0'").fetchone() == (True, False)
