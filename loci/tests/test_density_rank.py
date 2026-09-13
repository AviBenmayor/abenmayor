"""Walk-shed density, and the cluster ordering that rests on it (owner ruling
2026-09-13: "rank by density", read as households per km2 inside the
walk-shed).

Two things are load-bearing here and neither is checkable by eye.

The first is the DENOMINATOR. `density_400m` is `homes_400m` divided by the
area the 400 m walk actually reaches, and the whole point of the ruling is
that this is NOT `homes_400m` wearing a new label -- which is exactly what it
would become if the denominator were the nominal disc pi*0.4^2, a constant.
So the area is measured from the reachable node set, and the tests below pin
it on a grid where the answer is known by construction (a 100 m grid reaches
an L1 diamond of half-diagonal 400 m: 2*400^2 = 0.32 km2, against the 0.5027
km2 disc a straight-line reading would have used).

The second is the AGGREGATION. A cluster's density is the units-weighted
MEDIAN of its members', not Sum(homes)/Sum(area): members sit within 200 m of
each other so their sheds overlap almost entirely, and the pooled ratio counts
the same homes and the same land once per member. The adversarial case is a
cluster of low-rise blocks with one tower dropped in it -- the pooled ratio and
the unweighted mean both move a long way, the weighted median barely at all.

And the ordering must not leak into the screen: `cluster_table` may reorder a
list and may never touch `gap_score`, `n_missing` or which addresses are in the
gap set. That is checksummed below.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from loci.model.address_gaps import (
    ADDRESS_COLUMNS,
    DEFAULT_RANK_BY,
    RANK_BY,
    cluster_table,
    summarize_gap_run,
    weighted_median,
)
from loci.model.supply_ratio import (
    ADDRESS_RATIO_COLUMNS,
    MIN_SHED_KM2,
    catchment_sums,
    catchment_sums_and_shed,
    hull_area_km2,
    node_xy_m,
)
from loci.score.access import _to_csr

NOMINAL_DISC_KM2 = np.pi * 0.4 ** 2      # 0.5027 -- what a straight-line read would use


# --------------------------------------------------------- graph fixtures

def _grid_graph(n=9, spacing_m=100.0, lat=40.75, lon=-73.98):
    """n x n nodes on a `spacing_m` square grid at NYC latitude -- the same
    ruler as the line fixture in tests/test_supply_ratio.py, in two dimensions
    so a hull has an area to have."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    dx = spacing_m / (111320.0 * np.cos(np.radians(lat)))
    dy = spacing_m / 110540.0
    for i in range(n):
        for j in range(n):
            G.add_node((i, j), x=lon + j * dx, y=lat + i * dy)
    for i in range(n):
        for j in range(n):
            for di, dj in ((0, 1), (1, 0)):
                a, b = (i, j), (i + di, j + dj)
                if b in G:
                    G.add_edge(a, b, length=spacing_m)
                    G.add_edge(b, a, length=spacing_m)
    return G


def _line_graph(n=13, spacing_m=100.0, lat=40.75):
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    dx = spacing_m / (111320.0 * np.cos(np.radians(lat)))
    for i in range(n):
        G.add_node(i, x=-73.98 + i * dx, y=lat)
    for i in range(n - 1):
        G.add_edge(i, i + 1, length=spacing_m)
        G.add_edge(i + 1, i, length=spacing_m)
    return G


# ------------------------------------------------- 1. the hull, on its own

def test_hull_area_is_metres_squared_read_as_km2():
    """A 400 m square is 0.16 km2. If this ever reads 160,000 the projection
    step has been skipped and the areas are in degrees."""
    square = np.array([[0.0, 0.0], [400.0, 0.0], [400.0, 400.0], [0.0, 400.0]])
    assert hull_area_km2(square) == pytest.approx(0.16)


def test_degenerate_sheds_get_the_floor_not_a_zero():
    """Two reachable nodes, or three collinear ones, have no hull at all. The
    answer is the 50 m-disc floor, NOT zero: `homes / 0` would put a graph
    artifact at the top of a density ranking, which is the one failure mode a
    density ranking has that a units ranking does not."""
    assert hull_area_km2(np.array([[0.0, 0.0], [100.0, 0.0]])) == MIN_SHED_KM2
    collinear = np.array([[0.0, 0.0], [100.0, 0.0], [200.0, 0.0]])
    assert hull_area_km2(collinear) == MIN_SHED_KM2
    assert hull_area_km2(np.empty((0, 2))) == MIN_SHED_KM2


def test_a_sliver_hull_is_raised_to_the_floor():
    """Same guard, one step subtler: a hull with a real but absurd area (a
    1 m x 10 m splinter) is floored too, not just the exactly-degenerate one."""
    splinter = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 1.0], [0.0, 1.0]])
    assert hull_area_km2(splinter) == MIN_SHED_KM2


# ------------------------------------- 2. the shed, off the real Dijkstra

def test_walkshed_on_a_grid_is_the_L1_diamond_not_the_disc():
    """THE test for the denominator. From the centre of a 100 m grid a 400 m
    NETWORK walk reaches the L1 ball of radius 400 m, whose convex hull is a
    diamond of area 2*400^2 = 0.32 km2. A straight-line reading would have
    said 0.5027, a 57% overstatement -- and, being a constant, would have made
    density a relabelled homes_400m."""
    G = _grid_graph(9)
    A, idx = _to_csr(G)
    W = np.zeros((A.shape[0], 1))
    _sums, shed = catchment_sums_and_shed(
        A, np.array([idx[(4, 4)]]), W, radius_m=400.0, xy_m=node_xy_m(G, idx))
    assert shed[0] == pytest.approx(0.32, rel=0.02)
    assert shed[0] < NOMINAL_DISC_KM2


def test_walkshed_never_exceeds_the_straight_line_disc():
    """Network distance >= straight-line distance, so every reachable node is
    inside the 400 m disc and the hull cannot escape it. Free upper bound, and
    a shed above it means the projection or the radius is wrong."""
    G = _grid_graph(11)
    A, idx = _to_csr(G)
    W = np.zeros((A.shape[0], 1))
    q = np.array([idx[(i, j)] for i in range(11) for j in range(11)])
    _s, shed = catchment_sums_and_shed(A, q, W, radius_m=400.0, xy_m=node_xy_m(G, idx))
    assert shed.max() <= NOMINAL_DISC_KM2


def test_a_one_dimensional_network_has_no_shed_and_gets_the_floor():
    """A node whose whole walk is one street: collinear, no area, floored --
    the case that would otherwise divide by zero on a real stub or pier."""
    G = _line_graph(13)
    A, idx = _to_csr(G)
    W = np.zeros((A.shape[0], 1))
    _s, shed = catchment_sums_and_shed(
        A, np.array([idx[6]]), W, radius_m=400.0, xy_m=node_xy_m(G, idx))
    assert shed[0] == MIN_SHED_KM2


def test_asking_for_the_shed_does_not_move_the_sums():
    """The numerator and the denominator come off the same Dijkstra rows, so
    turning the denominator on must leave homes_400m bit-identical. If this
    fails, two sweeps disagree about the same reachable set."""
    G = _grid_graph(9)
    A, idx = _to_csr(G)
    W = np.zeros((A.shape[0], 1))
    for node in G.nodes():
        W[idx[node], 0] = 1.0
    q = np.array([idx[(4, 4)], idx[(0, 0)], idx[(8, 3)]])
    plain = catchment_sums(A, q, W, radius_m=400.0)
    both, shed = catchment_sums_and_shed(A, q, W, radius_m=400.0, xy_m=node_xy_m(G, idx))
    assert np.array_equal(plain, both)
    assert shed is not None and np.isfinite(shed).all()
    assert catchment_sums_and_shed(A, q, W, radius_m=400.0)[1] is None


def test_density_is_homes_over_the_measured_shed():
    """The composition, end to end on the fixture: 41 nodes are within a 400 m
    grid walk of the centre, one home each, over a 0.32 km2 shed."""
    G = _grid_graph(9)
    A, idx = _to_csr(G)
    W = np.zeros((A.shape[0], 1))
    for node in G.nodes():
        W[idx[node], 0] = 1.0
    sums, shed = catchment_sums_and_shed(
        A, np.array([idx[(4, 4)]]), W, radius_m=400.0, xy_m=node_xy_m(G, idx))
    assert sums[0, 0] == pytest.approx(41.0)
    assert (sums[0, 0] / shed[0]) == pytest.approx(41.0 / 0.32, rel=0.02)


# ---------------------------------------------- 3. the weighted median

def test_weighted_median_follows_the_units_not_the_lots():
    """Three rowhouses at 5,000 and one 500-unit tower at 40,000: unweighted
    the median is ~7,500; weighted by units the households are mostly IN the
    tower and the median is the tower's own density."""
    v = [5000.0, 5000.0, 5000.0, 40000.0]
    w = [2.0, 2.0, 2.0, 500.0]
    assert weighted_median(v, w) == 40000.0
    assert np.median(v) == 5000.0        # lot-weighted: three rowhouses outvote 500 homes


def test_weighted_median_falls_back_when_every_weight_is_zero():
    assert weighted_median([1.0, 3.0, 5.0], [0.0, 0.0, 0.0]) == 3.0
    assert np.isnan(weighted_median([np.nan, np.nan], [1.0, 1.0]))


# ------------------------------------------------- 4. the cluster ordering

def _addr(cluster, density, units, boro="BK", lead="laundry", nta="BK0101"):
    return {"cluster_id": cluster, "density_400m": density, "units_capped": units,
            "borough": boro, "lead_category": lead, "lead_excess_m": 120.0,
            "nta_code": nta, "neighborhood": nta, "gap_score": 1.5, "n_missing": 3}


def _two_clusters():
    """BIG: 40 low-rise lots, 3,000 u/km2, 2,000 capped units in total.
    DENSE: 4 towers, 30,000 u/km2, 800 capped units. The pre-ruling order puts
    BIG first; the ruling puts DENSE first. This IS the swing the owner asked
    for."""
    rows = [_addr("BK:laundry:0", 3000.0, 50.0) for _ in range(40)]
    rows += [_addr("BK:laundry:1", 30000.0, 200.0) for _ in range(4)]
    return pd.DataFrame(rows)


def test_density_order_and_units_order_disagree():
    df = _two_clusters()
    by_density = cluster_table(df, rank_by="density")["cluster_id"].tolist()
    by_units = cluster_table(df, rank_by="units")["cluster_id"].tolist()
    assert by_density == ["BK:laundry:1", "BK:laundry:0"]
    assert by_units == ["BK:laundry:0", "BK:laundry:1"]


def test_the_default_is_density():
    assert DEFAULT_RANK_BY == "density"
    assert cluster_table(_two_clusters())["cluster_id"].iloc[0] == "BK:laundry:1"
    assert summarize_gap_run_ordering(_two_clusters())[0] == "BK:laundry:1"


def summarize_gap_run_ordering(df):
    """`summarize_gap_run` needs the whole screen frame; `cluster_table` is the
    piece under test, so this helper reads the order back off it."""
    return cluster_table(df)["cluster_id"].tolist()


def test_capped_units_is_the_tiebreak_and_is_still_reported():
    """Two clusters at the same density: the bigger one leads, and Sigma
    units_capped is on the row either way -- "how dense" and "how many" are
    different questions and the reader gets both."""
    df = pd.DataFrame(
        [_addr("BK:bar:0", 12000.0, 100.0) for _ in range(3)]
        + [_addr("BK:bar:1", 12000.0, 400.0) for _ in range(3)])
    out = cluster_table(df, rank_by="density")
    assert out["cluster_id"].tolist() == ["BK:bar:1", "BK:bar:0"]
    assert out.loc[0, "units_capped"] == 1200.0
    assert set(["units_capped", "cluster_density_400m",
                "cluster_density_mean_400m"]).issubset(out.columns)


def test_one_mega_lot_does_not_carry_a_cluster():
    """The adversarial case the median exists for. Nine rowhouse lots at 4,000
    u/km2 and one capped mega-lot at 60,000: the MEAN is dragged to 9,600 and
    the pooled-ratio reading would be worse, but the weighted median stays on
    the mega-lot's side only when the units really are there -- here they are
    (500 capped vs 9x5), so the median is the tower's, and the mean is
    reported beside it so the skew is visible rather than hidden."""
    df = pd.DataFrame([_addr("BK:cafe_bakery:0", 4000.0, 5.0) for _ in range(9)]
                      + [_addr("BK:cafe_bakery:0", 60000.0, 500.0)])
    row = cluster_table(df, rank_by="density").iloc[0]
    assert row["cluster_density_400m"] == 60000.0
    assert row["cluster_density_mean_400m"] == pytest.approx(9600.0)
    # and with the tower's units capped away to a rowhouse's, the median
    # returns to the rowhouses -- the weighting is doing the work, not the max.
    df2 = df.copy()
    df2.loc[df2.index[-1], "units_capped"] = 5.0
    assert cluster_table(df2, rank_by="density").iloc[0]["cluster_density_400m"] == 4000.0


def test_pooled_ratio_is_not_what_is_computed():
    """Sum(homes)/Sum(area) over overlapping sheds is the tempting wrong
    answer. Pin that the reported density is a member statistic: every member
    here has density 7,000, so the cluster's density is 7,000 -- it does NOT
    scale with how many lots the block was cut into."""
    for n_lots in (2, 20, 200):
        df = pd.DataFrame([_addr("MN:bank:0", 7000.0, 10.0) for _ in range(n_lots)])
        assert cluster_table(df, rank_by="density").iloc[0]["cluster_density_400m"] == 7000.0


# --------------------------------------- 5. the guard rails on the ordering

def test_density_ranking_refuses_rather_than_silently_reverting():
    """A NULL density column means supply-ratio has not run. Ordering by
    units while claiming to order by density is precisely the failure the
    ruling corrects, so `cluster_table` raises."""
    df = _two_clusters()
    df["density_400m"] = np.nan
    with pytest.raises(ValueError, match="density_400m"):
        cluster_table(df, rank_by="density")
    assert len(cluster_table(df, rank_by="units")) == 2
    with pytest.raises(ValueError, match="unknown rank_by"):
        cluster_table(df, rank_by="unitz")
    assert RANK_BY == ("density", "units")


def test_summary_records_the_fallback_it_took():
    """`summarize_gap_run` degrades instead of killing a --dry-run on a
    database where supply-ratio has not run -- but it says so, on the summary
    dict the CLI prints."""
    df = _screen_frame()
    df["density_400m"] = np.nan
    summary = summarize_gap_run(df)
    assert summary["rank_by"] == "units"
    assert "density_400m" in summary["rank_by_fallback"]
    df["density_400m"] = [3000.0, 30000.0, 30000.0]
    assert summarize_gap_run(df)["rank_by"] == "density"
    assert summarize_gap_run(df)["rank_by_fallback"] is None


def _screen_frame():
    """The minimum `summarize_gap_run` reads: the per-category ratio/censored
    pairs plus the summary columns."""
    from loci.model.conveniences import ALLCATS
    base = pd.DataFrame([
        {"units": 10.0, "units_capped": 10.0, "eligible": True, "n_missing": 1,
         "lead_category": "laundry", "lead_excess_m": 100.0, "lead_censored": False,
         "cluster_id": "BK:laundry:0", "borough": "BK", "gap_score": 1.4,
         "nta_code": "BK0101", "neighborhood": "BK0101"},
        {"units": 500.0, "units_capped": 500.0, "eligible": True, "n_missing": 1,
         "lead_category": "laundry", "lead_excess_m": 120.0, "lead_censored": False,
         "cluster_id": "BK:laundry:1", "borough": "BK", "gap_score": 1.6,
         "nta_code": "BK0102", "neighborhood": "BK0102"},
        {"units": 500.0, "units_capped": 500.0, "eligible": True, "n_missing": 1,
         "lead_category": "laundry", "lead_excess_m": 130.0, "lead_censored": False,
         "cluster_id": "BK:laundry:1", "borough": "BK", "gap_score": 1.7,
         "nta_code": "BK0102", "neighborhood": "BK0102"},
    ])
    for cat in ALLCATS:
        base[f"{cat}_ratio"] = 1.4 if cat == "laundry" else 0.5
        base[f"{cat}_censored"] = False
    return base


# ----------------------------- 6. the ordering may not touch the gap set

def test_reordering_leaves_the_gap_set_and_gap_score_byte_identical():
    """NON-FILTERING, checksummed. `cluster_table` is a reporting function: it
    may reorder a list and may not change which addresses are in the gap set,
    their gap_score, or their cluster_id. Both orderings are run against the
    same frame and the frame is compared to a hash of itself."""
    df = _two_clusters()
    before = pd.util.hash_pandas_object(
        df[["cluster_id", "gap_score", "n_missing", "units_capped"]], index=True).sum()
    cluster_table(df, rank_by="density")
    cluster_table(df, rank_by="units")
    after = pd.util.hash_pandas_object(
        df[["cluster_id", "gap_score", "n_missing", "units_capped"]], index=True).sum()
    assert before == after
    # and the two orderings are permutations of ONE set of clusters
    assert (set(cluster_table(df, rank_by="density")["cluster_id"])
            == set(cluster_table(df, rank_by="units")["cluster_id"]))


def test_the_density_columns_are_not_the_screens_to_write():
    """Same guarantee one level down: the two new columns are supply-ratio's
    UPDATE-only annotation and must never appear on the screen's own SET list,
    or an ordering re-run could clobber gap_score."""
    assert "walkshed_km2_400m" in ADDRESS_RATIO_COLUMNS
    assert "density_400m" in ADDRESS_RATIO_COLUMNS
    assert not set(ADDRESS_RATIO_COLUMNS) & set(ADDRESS_COLUMNS)


def test_an_empty_cluster_set_is_an_empty_table_not_a_crash():
    df = _two_clusters()
    df["cluster_id"] = None
    assert len(cluster_table(df, rank_by="units")) == 0


# --------------------------------- 7. the ordering, on the face of the map

def test_meta_names_the_ordering_and_carries_the_caveat():
    """The map must be able to SAY what it sorted by. `rankBy` is the ordering
    that was actually applied -- it reads "units" on an export whose database
    has no density -- and `densityCaveat` ships with it so a reader never
    meets the number without the sentence that says it is a register count
    over a walk-shed and not an ACS household density."""
    from loci.viz import webmap_export as wx

    assert set(wx.RANK_LABELS) == set(RANK_BY)
    assert "NO margin of error" in wx.DENSITY_CAVEAT
    assert "ACS" in wx.DENSITY_CAVEAT
    assert wx.CLUSTER_COLUMNS[4] == "cluster_density_400m"
    assert "units_capped" in wx.CLUSTER_COLUMNS


def test_nta_index_orders_by_density_and_says_so():
    """The picker's order follows the ruling when there are densities to
    follow, and falls back to size -- LABELLED as size -- when there are not."""
    from loci.viz import webmap_export as wx

    layers = {
        "BK0001": _nta_layer("BK0001", "Big and low-rise", "BK", n=900, units=9000),
        "MN0001": _nta_layer("MN0001", "Small and tall", "MN", n=40, units=4000),
    }
    by_size = wx.nta_index(layers, ["MN", "BK"], "principled", "abc")
    assert [r["nta"] for r in by_size["ntas"]] == ["BK0001", "MN0001"]
    assert by_size["rankBy"] == "units"

    by_density = wx.nta_index(layers, ["MN", "BK"], "principled", "abc",
                              {"BK0001": 6000.0, "MN0001": 31000.0})
    assert [r["nta"] for r in by_density["ntas"]] == ["MN0001", "BK0001"]
    assert by_density["rankBy"] == "density"
    assert "density" in by_density["rankLabel"]
    # `n` and `units` survive on the row: how dense and how many are both
    # answerable from the file the picker already has.
    assert by_density["ntas"][0]["n"] == 40
    assert by_density["ntas"][0]["units"] == 4000
    assert by_density["ntas"][0]["density"] == 31000


def test_a_nan_density_is_written_as_null_not_as_the_NaN_token():
    """json.dumps writes NaN as the bare token `NaN`, which JSON.parse
    rejects -- one such cluster would 404 the whole file for every viewer."""
    import json

    from loci.viz.webmap_export import _fnum
    assert _fnum(float("nan")) is None
    assert _fnum(None) is None
    assert _fnum(31000.4) == 31000
    assert "NaN" not in json.dumps({"d": _fnum(float("nan"))})


def _nta_layer(code, name, boro, n, units):
    return {"name": name, "boro": boro, "n": n, "units": units,
            "pois": {"n": 5, "nSet": 4}, "gapCounts": {}, "bounds": [0, 0, 1, 1],
            "center": [0.5, 0.5], "character": None}
