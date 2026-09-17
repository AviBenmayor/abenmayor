"""The STREET sampling frame (D84, docs/street_midpoint_frame.md).

Two halves, and the split matters:

  * PURE GEOMETRY AND VOCABULARY -- the keep rule, the closed `rw_type`
    vocabulary, the split arithmetic, the point-id namespace. No DB, no
    network, sub-second.
  * THE NON-FILTERING PROOF -- adding street rows to `analysis.address`
    changes NOTHING about the lot rows. This is the same proof D57/D61 ran for
    the demand annotation, on a small synthetic warehouse: checksums of
    gap_score / lead_category / n_missing / eligible / present_count /
    cluster_id before and after, Sigma units, every lot's homes_400m, and the
    baseline fit universe.

The claim being defended is precise: the street frame is a SECOND SET OF
POINTS, not a second screen. If a lot's reading moves because a street point
appeared 40 m away, the frame has become a filter wearing a costume.
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from loci.categories import CATEGORIES
from loci.model import address_gaps as ag
from loci.sources.cities.nyc import street_centerline as sc

# --------------------------------------------------------------- fixtures


def _row(physicalid="1", rw_type=1, status="2", nonped=None, boro="3",
         coords=((-73.95, 40.70), (-73.949, 40.70)), lvl="13", **extra):
    """One CSCL row in the shape the SODA API returns it."""
    r = {
        "physicalid": physicalid,
        "rw_type": str(rw_type),
        "status": status,
        "nonped": nonped,
        "boroughcode": boro,
        "from_level_code": lvl,
        "to_level_code": lvl,
        "full_street_name": "TEST ST",
        "streetwidth": "34",
        "segmentlength": None,
        "the_geom": {"type": "MultiLineString", "coordinates": [list(map(list, coords))]},
    }
    r.update(extra)
    return r


def _straight_row(length_m: float, physicalid="1", **kw):
    """A W-E segment `length_m` long at NYC latitude, with a `segmentlength`
    that agrees with it (so the build-time length check passes)."""
    dlon = length_m / (111_320.0 * math.cos(math.radians(40.70)))
    r = _row(physicalid=physicalid,
             coords=((-73.95, 40.70), (-73.95 + dlon, 40.70)), **kw)
    r["segmentlength"] = str(length_m / 0.3048)
    return r


# ------------------------------------------------- (1) the keep rule


def test_keep_rule_is_the_four_clauses_and_nothing_else():
    """§1.4. Each clause is load-bearing: drop one and the frame silently
    grows by highways, demapped stretches, pedestrian-prohibited roadway or
    the above/below-grade duplicate of a street's own footprint."""
    assert sc.keep_segment(_row())                                  # Street, constructed, at grade
    assert not sc.keep_segment(_row(status="5"))                    # demapped/re-mapped
    assert not sc.keep_segment(_row(status="4"))                    # proposed: the street does not exist
    assert not sc.keep_segment(_row(rw_type=2))                     # highway
    assert not sc.keep_segment(_row(rw_type=6))                     # path/trail: every park path
    assert not sc.keep_segment(_row(rw_type=12))                    # CSCL's own name for a paper street
    assert not sc.keep_segment(_row(nonped="V"))                    # pedestrians prohibited
    assert not sc.keep_segment(_row(lvl="12"))                      # below grade


def test_pedestrian_malls_are_kept_and_nonped_d_is_not_a_prohibition():
    """Two deliberate non-exclusions. `trafdir='NV'` Streets are Fulton Mall
    and the Brooklyn Heights ped-ways -- real retail streets. `nonped='D'` is
    undocumented and self-contradictory (park drives AND the Williamsburg
    Bridge pedestrian path), so it must not filter anything."""
    assert sc.keep_segment(_row(trafdir="NV"))
    assert sc.keep_segment(_row(nonped="D"))


def test_unknown_rw_type_raises_rather_than_quietly_shrinking_the_frame():
    """The vocabulary is CLOSED. CSCL refreshes weekly; a new feature type
    must be read and ruled on, not dropped by a `== 1` that happens to be
    False. A silent drop looks exactly like a neighbourhood with no streets."""
    with pytest.raises(sc.StreetFrameError, match="not in the vocabulary"):
        sc.keep_segment(_row(rw_type=99))
    with pytest.raises(sc.StreetFrameError, match="not an integer"):
        sc.keep_segment(_row(rw_type="street"))


def test_keep_ladder_reports_every_clause_in_order():
    rows = [_straight_row(100, "1"), _straight_row(100, "2", rw_type=2),
            _straight_row(100, "3", nonped="V")]
    ladder = sc.keep_ladder(rows)
    assert [n for _label, n, _km in ladder] == [3, 3, 2, 1, 1]


# ------------------------------------------- (2) length, and the two traps


def test_length_comes_from_the_geometry_reprojected_not_from_a_column():
    """EPSG:2263 is US survey FEET and `always_xy` is required. A 200 m
    segment must measure 200 m, to a metre."""
    seg = sc.load_street_segments([_straight_row(200.0)])
    assert len(seg) == 1
    assert seg["length_m"].iloc[0] == pytest.approx(200.0, abs=1.0)


def test_shape_length_is_never_read():
    """`shape_length` is Web Mercator metres -- 1.32x the true length at NYC's
    latitude -- and reading it would inflate every length by a third with no
    error anywhere. A grep test, because the failure is invisible at runtime."""
    src = (sc.__file__).replace(".pyc", ".py")
    body = [ln for ln in open(src) if "shape_length" in ln]
    # It may be NAMED in prose (the docstring warns about it); it may never be
    # subscripted, fetched or selected.
    assert all(('"' not in ln.split("shape_length")[0][-2:]) or ln.lstrip().startswith("#")
               or "row.get" not in ln for ln in body)
    assert "shape_length" not in "".join(
        ln for ln in open(src) if "row.get" in ln or "FIELDS" in ln)


def test_length_sanity_check_catches_a_projection_error():
    """The cross-check against `segmentlength` is not about data drift -- the
    published field is unreliable per row -- it is about the PROJECTION. A
    unit or axis-order error moves this ratio by a factor."""
    seg = sc.load_street_segments([_straight_row(200.0)])
    assert sc.check_length_sanity(seg) == pytest.approx(1.0, abs=0.01)
    seg.loc[0, "segmentlength_ft"] = seg["segmentlength_ft"].iloc[0] * 1.32
    with pytest.raises(sc.StreetFrameError, match="projection or unit error"):
        sc.check_length_sanity(seg)


# ------------------------------------------------ (3) the split arithmetic


def test_short_segment_gets_exactly_its_midpoint():
    """The owner's words: "an address near the middle of every known street".
    Below L that is literally one point, at the middle."""
    seg = sc.load_street_segments([_straight_row(60.0)])
    pts = sc.street_midpoints(seg, spacing_m=100.0)
    assert len(pts) == 1
    assert pts["lon"].iloc[0] == pytest.approx(-73.95 + (60.0 / 2) /
                                               (111_320.0 * math.cos(math.radians(40.70))),
                                               abs=1e-6)
    assert pts["frontage_m"].iloc[0] == pytest.approx(60.0, abs=1.0)


def test_k_is_ceil_len_over_L_and_no_point_lands_on_an_endpoint():
    """`k = ceil(len/L)` at fractions (2i-1)/2k: evenly spaced, symmetric, and
    never on a corner -- so two segments meeting at an intersection never put
    two points on the same doorway."""
    seg = sc.load_street_segments([_straight_row(250.0)])
    pts = sc.street_midpoints(seg, spacing_m=100.0).sort_values("k_index")
    assert len(pts) == 3 == math.ceil(250.0 / 100.0)
    x0 = -73.95
    m_per_deg = 111_320.0 * math.cos(math.radians(40.70))
    along = [(lon - x0) * m_per_deg for lon in pts["lon"]]
    assert along == pytest.approx([250 / 6, 250 / 2, 5 * 250 / 6], abs=1.0)
    assert all(1.0 < a < 249.0 for a in along)
    assert pts["frontage_m"].tolist() == pytest.approx([250 / 3] * 3, abs=1.0)


def test_multipart_geometry_is_split_per_part():
    """565 of the 32,291 kept MN+BK segments are multipart. Taking the longest
    part only drops 33.4 km of kept street -- real block faces with no point on
    them."""
    dlon = 1.0 / (111_320.0 * math.cos(math.radians(40.70)))
    row = _row(coords=((-73.95, 40.70), (-73.95 + 150 * dlon, 40.70)))
    row["the_geom"]["coordinates"].append(
        [[-73.90, 40.70], [-73.90 + 150 * dlon, 40.70]])
    row["segmentlength"] = str(300.0 / 0.3048)
    seg = sc.load_street_segments([row])
    assert seg["n_parts"].iloc[0] == 2
    assert seg["length_m"].iloc[0] == pytest.approx(300.0, abs=2.0)
    pts = sc.street_midpoints(seg, spacing_m=100.0)
    # ceil(150/100) = 2 per part, not ceil(300/100) = 3 over one part.
    assert len(pts) == 4
    assert {round(x, 2) for x in pts["lon"]} == {
        round(v, 2) for v in (-73.95, -73.95, -73.90, -73.90)}


def test_point_ids_are_namespaced_and_asserted_unique():
    """`physicalid` is NEAR-unique (3 duplicates in MN+BK). A collision would
    silently overwrite a point, so it raises."""
    seg = sc.load_street_segments([_straight_row(250.0, "12345")])
    pts = sc.street_midpoints(seg, spacing_m=100.0)
    assert pts["point_id"].tolist() == ["seg:12345:0", "seg:12345:1", "seg:12345:2"]
    dupe = sc.load_street_segments([_straight_row(100.0, "77"), _straight_row(100.0, "77")])
    with pytest.raises(sc.StreetFrameError, match="duplicate point_id"):
        sc.street_midpoints(dupe, spacing_m=100.0)


def test_a_street_id_can_never_collide_with_a_bbl():
    """`seg:` prefix vs a 10-digit numeric BBL. Disjoint by construction, so
    the two frames cannot overwrite each other's rows through the
    (borough, address_id) primary key."""
    seg = sc.load_street_segments([_straight_row(100.0, "3001230045")])
    pid = sc.street_midpoints(seg, spacing_m=100.0)["point_id"].iloc[0]
    assert pid.startswith("seg:") and not pid.isdigit()


def test_borough_comes_from_cscl_not_from_the_hex():
    """Invariant 8. The res-9 hex lookup disagrees with CSCL's own borough on
    120 of 39,277 points at river edges; `borough` is the D78 scope key, so it
    is taken from the source and the hex supplies only the NTA."""
    seg = sc.load_street_segments([_straight_row(100.0, "1", boro="1"),
                                   _straight_row(100.0, "2", boro="3")])
    assert seg["borough"].tolist() == ["MN", "BK"]
    with pytest.raises(sc.StreetFrameError, match="boroughcode"):
        sc.load_street_segments([_straight_row(100.0, boro="9")])


def test_segment_count_guard_refuses_a_collapsed_frame():
    """CSCL refreshes weekly. Drift is expected; a factor is a broken keep
    rule, and ingesting it would read as "these neighbourhoods lost their
    streets"."""
    sc.check_segment_count(pd.DataFrame(index=range(sc.EXPECTED_KEPT_MNBK)))
    with pytest.raises(sc.StreetFrameError, match="keep rule kept"):
        sc.check_segment_count(pd.DataFrame(index=range(3_000)))


# ------------------------------------------------ (4) the cluster namespace


def test_lot_cluster_ids_are_byte_identical_and_street_ids_are_disjoint():
    """D84's whole claim in one assertion: the lot frame's ids do not move.
    Street clusters take the `S` prefix, so the two namespaces cannot meet."""
    assert ag.cluster_key("BK", "lot", "bar", 12) == "BK:bar:12"
    assert ag.cluster_key("BK", "street", "bar", 12) == "BK:bar:S12"
    with pytest.raises(ValueError):
        ag.cluster_key("BK", "sidewalk", "bar", 1)


# ------------------------------------- (5) the non-filtering proof, on data


def _line_graph(n=41):
    """n nodes on a W-E line 100 m apart at NYC latitude."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    dx = 100 / 84_400.0
    for i in range(n):
        G.add_node(i, x=-73.98 + i * dx, y=40.75)
    for i in range(n - 1):
        G.add_edge(i, i + 1, length=100.0)
        G.add_edge(i + 1, i, length=100.0)
    return G


def _frame(n_lots=6, n_street=0):
    """A lot frame, optionally with street points interleaved between the lots
    -- the adversarial placement, because a street point that lands ON a lot's
    block is the one that could perturb it."""
    G = _line_graph()
    rows = [{"address_id": f"{3000000000 + i}", "bbl": f"{3000000000 + i}",
             "lon": G.nodes[i * 3]["x"], "lat": 40.75, "units": 10.0 + i,
             "borough": "BK", "frame": ag.LOT_FRAME} for i in range(n_lots)]
    for k in range(n_street):
        rows.append({"address_id": f"seg:{900 + k}:0", "bbl": None,
                     "lon": G.nodes[k * 3 + 1]["x"], "lat": 40.75, "units": 0.0,
                     "borough": "BK", "frame": ag.STREET_FRAME,
                     "frontage_m": 95.0, "street_name": "TEST ST",
                     "frame_source": sc.SOURCE_ID})
    return G, pd.DataFrame(rows)


def _score(G, df):
    """compute_gap_metrics over the synthetic graph, with the frame plumbing
    that compute_address_gaps would apply -- the pure half, no DB."""
    pois = [("grocery", G.nodes[4]["x"], 40.75), ("bar", G.nodes[30]["x"], 40.75)]
    M = ag._address_nearest_matrix_from_graph(
        G, list(zip(df["address_id"], df["lon"], df["lat"])), pois, min_component=1)
    reach = {c: 1.0e6 for c in CATEGORIES}
    reach.update({"grocery": 300.0, "bar": 300.0})
    return ag.compute_gap_metrics(M, reach)


def test_lot_readings_are_unchanged_by_the_presence_of_street_points():
    """INVARIANT (a), in its purest form: every lot's nearest_m, gap_score,
    lead_category and n_missing are identical with and without street rows in
    the frame. They must be -- `ratio` reads only that point's own distance to
    a POI -- and the test exists because "must be" has been wrong before."""
    G, lots = _frame(n_lots=6, n_street=0)
    G2, both = _frame(n_lots=6, n_street=5)
    a = _score(G, lots)
    b = _score(G2, both)
    keep = both["frame"].to_numpy() == ag.LOT_FRAME
    for key in ("gap_score", "lead_category", "n_missing", "present_count",
                "lead_excess_m", "lead_censored"):
        np.testing.assert_array_equal(np.asarray(a[key]), np.asarray(b[key])[keep])


def test_street_rows_contribute_exactly_zero_units():
    """INVARIANT (b). units is 0 and NOT NULL, which is what makes every
    downstream catchment sum's invariance arithmetic rather than approximate
    -- `COALESCE(units, 0)` over a NULL would be the same number only by
    accident of the coalesce."""
    _G, both = _frame(n_lots=6, n_street=5)
    street = both[both["frame"] == ag.STREET_FRAME]
    assert len(street) == 5
    assert (street["units"] == 0.0).all()
    assert street["units"].notna().all()
    assert both["units"].sum() == _frame(n_lots=6)[1]["units"].sum()


def test_clusters_are_built_within_frame_so_a_street_point_cannot_fuse_two_lot_clusters():
    """INVARIANT: clustering the UNION moved 429 of 571 existing lot clusters
    and MERGED 12 net, because a units-0 point bridges two markets the screen
    called distinct. Here: two lot clusters 300 m apart (eps is 200 m) with a
    street point exactly between them. Joint clustering fuses them; within-frame
    clustering does not."""
    lat = 40.75
    m = 1.0 / (111_320.0 * math.cos(math.radians(lat)))
    lon = np.array([0.0, 300.0 * m, 150.0 * m]) - 73.98
    frame = np.array([ag.LOT_FRAME, ag.LOT_FRAME, ag.STREET_FRAME])

    # joint (the rejected design): one component
    joint = ag._cluster_gap_addresses(lon, np.full(3, lat), ag.CLUSTER_RADIUS_M)
    assert len(set(joint.tolist())) == 1

    # within frame (D84): the two lots stay apart, the street point is its own
    lots = ag._cluster_gap_addresses(lon[frame == ag.LOT_FRAME], np.full(2, lat),
                                     ag.CLUSTER_RADIUS_M)
    assert len(set(lots.tolist())) == 2


def test_frame_travels_onto_the_long_table():
    """The frame is denormalised onto address_category (D61's reason: a reader
    must be able to slice the long table without a join), and `_split_wide`
    carries it rather than leaving it to a default."""
    assert "frame" in ag.ADDRESS_COLUMNS
    assert "frame" in ag.ADDRESS_CATEGORY_SCREEN_COLUMNS
    df = pd.DataFrame({
        "address_id": ["a", "seg:1:0"], "bbl": ["3001", None], "lon": [-73.9, -73.9],
        "lat": [40.7, 40.7], "units": [5.0, 0.0], "units_capped": [5.0, 0.0],
        "nta_code": [None, None], "neighborhood": [None, None], "borough": ["BK", "BK"],
        "h3_index": [None, None], "present_count": [1, 1], "eligible": [True, True],
        "gap_score": [2.0, 2.0], "lead_category": ["bar", "bar"],
        "lead_excess_m": [1.0, 1.0], "n_missing": [1, 1],
        "cluster_id": ["BK:bar:0", "BK:bar:S0"],
        "reach_source": ["tiers"] * 2, "reach_hash": ["x"] * 2, "graph_version": ["g"] * 2,
        "supply_set": ["principled"] * 2, "supply_hash": ["h"] * 2,
        "run_at": [pd.Timestamp("2026-09-13")] * 2, "lead_censored": [False, False],
        "frame": [ag.LOT_FRAME, ag.STREET_FRAME], "frontage_m": [None, 95.0],
        "street_name": [None, "TEST ST"], "frame_source": [None, "nyc_cscl"],
        "frame_vintage": [None, None],
    })
    for cat in ag.ALLCATS:
        df[f"{cat}_nearest_m"] = 100.0
        df[f"{cat}_ratio"] = 0.5
        df[f"{cat}_censored"] = False
    addr, cat_df = ag._split_wide(df)
    assert list(addr.columns) == ag.ADDRESS_COLUMNS
    assert list(cat_df.columns) == ag.ADDRESS_CATEGORY_SCREEN_COLUMNS
    assert set(cat_df["frame"]) == {ag.LOT_FRAME, ag.STREET_FRAME}
    assert len(cat_df) == len(ag.ALLCATS) * len(df)
    assert (cat_df[cat_df["address_id"] == "seg:1:0"]["frame"] == ag.STREET_FRAME).all()


def test_an_unknown_frame_value_is_refused():
    """DuckDB cannot ALTER-ADD a CHECK to an existing table, so the two-value
    domain has to be enforced in code or it is not enforced at all."""
    G, df = _frame(n_lots=3)
    df.loc[0, "frame"] = "sidewalk"
    with pytest.raises(ValueError, match="unknown frame"):
        ag.compute_address_gaps(None, df)


# ------------------------------- (6) the layers that must stay lot-pinned


def test_supply_baseline_fit_universe_is_pinned_to_the_lot_frame():
    """INVARIANT (d). The norm every `supply_ratio_vs_base` in the project is
    measured against was fitted on 281,842 residential addresses. Letting 50k
    units-0 points into the fit would move the RULER -- every existing address
    would look better supplied with no supply having changed."""
    from loci.model import supply_ratio as sr

    long_df = pd.DataFrame({
        "category": ["bar"] * 6,
        "frame": [ag.LOT_FRAME] * 3 + [ag.STREET_FRAME] * 3,
        "supply_per_1k": [2.0, 4.0, 6.0, 100.0, 200.0, 300.0],
        "homes_400m": [100.0] * 3 + [1.0] * 3,
        "supply_400m": [1.0] * 6,
        "eligible": [True] * 6,
    })
    fit = sr.fit_baselines(long_df)["bar"]
    assert fit["n"] == 3                       # the three lot rows, not six
    assert fit["median"] == pytest.approx(4.0)  # median(2,4,6), not median of all six
    assert sr.BASELINE_FIT_FRAMES == ("lot",)


def test_home_weights_are_lot_only_and_query_points_are_both_frames():
    """The two roles that were one query before D84: `load_home_points` is the
    WEIGHT set (who counts as homes) and `load_query_points` is who RECEIVES a
    catchment. A street point has no homes of its own and every reason to be
    told how many are within 400 m of it -- that catchment is what sorts a
    Navy Yard street below a Bushwick one instead of above it."""
    from loci.model import supply_ratio as sr

    assert sr.HOME_FRAMES == ("lot",)
    src = open(sr.__file__).read()
    assert "COALESCE(frame, 'lot') IN ({holes})" in src
    assert "load_query_points" in src


@pytest.mark.parametrize("module,needle", [
    ("loci.model.revenue", "COALESCE(frame, 'lot') = 'lot'"),
    ("loci.model.recommend", "COALESCE(a.frame, 'lot') = 'lot'"),
    ("loci.validation.sample", "COALESCE(g.frame, 'lot') = 'lot'"),
    ("loci.model.conveniences", "COALESCE(c.frame, 'lot') = 'lot'"),
])
def test_population_statistics_are_pinned_to_the_lot_frame(module, needle):
    """Every place a street point would change a POPULATION statistic or a
    FITTED parameter rather than add a scored point:

      revenue    lambda_c is calibrated so the mean prediction over a county's
                 establishments matches the Economic Census, and the backtest
                 scores ZIP-level folds. A units-0 point is not an observation
                 of realised receipts.
      recommend  every section is a median over "the area's addresses". The
                 street frame roughly doubles the points in an industrial area
                 and contributes zero homes -- it would halve the median
                 homes_400m of exactly the areas this card is asked about.
      sample     the strata are NTILE(10) over tract median income, which a
                 street midpoint does not have. A NULL stratum would change
                 the Google Places budget plan with nobody deciding to.
      conveniences  the per-address n_unsatisfied distribution is a statement
                 about addresses; its unit-weighted shares are unchanged
                 either way, which is precisely why the count-based one has to
                 be pinned explicitly.
    """
    import importlib
    assert needle in open(importlib.import_module(module).__file__).read()


# ------------------------------------- (7) the warehouse-shaped invariants


def _warehouse():
    """An in-memory warehouse with the real schema, one lot and one street
    point in scope and one of each out of scope."""
    from loci import db as locidb

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    rows = [
        ("3001", "3001", -73.99, 40.67, "BK", 10.0, ag.LOT_FRAME),
        ("seg:5:0", None, -73.99, 40.67, "BK", 0.0, ag.STREET_FRAME),
        ("4001", "4001", -73.80, 40.72, "QN", 8.0, ag.LOT_FRAME),
        ("seg:9:0", None, -73.80, 40.72, "QN", 0.0, ag.STREET_FRAME),
    ]
    con.executemany(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, units, frame, "
        "present_count, eligible, n_missing, reach_source, reach_hash, graph_version, "
        "run_at) VALUES (?,?,?,?,?,?,?, 12, TRUE, 1, 'tiers', 'h', 'g', now())", rows)
    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, frame) "
        "VALUES (?,?,?,?)",
        [(aid, boro, cat, frame)
         for aid, _bbl, _lon, _lat, boro, _u, frame in rows for cat in ag.ALLCATS])
    return con


def test_the_view_exposes_the_frame():
    """INVARIANT (h). analysis.address_gaps is what every renderer, every
    laundry view and `loci validate` read; a frame they cannot see is a frame
    they cannot exclude."""
    con = _warehouse()
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'address_gaps'").fetchall()}
    assert {"frame", "frontage_m", "street_name"} <= cols
    got = dict(con.execute(
        "SELECT address_id, frame FROM analysis.address_gaps WHERE borough = 'BK'"
    ).fetchall())
    assert got == {"3001": ag.LOT_FRAME, "seg:5:0": ag.STREET_FRAME}


def test_prune_removes_out_of_scope_rows_of_BOTH_frames():
    """INVARIANT (e). D78's prune keys on BOROUGH and needs no special case for
    the street frame -- but "needs none" has to be demonstrated, because street
    rows take their borough from CSCL rather than from the hex and an
    off-by-one there would leave Queens street points in a MN+BK deliverable."""
    con = _warehouse()
    n_addr, n_cat = ag.prune_out_of_scope(con, ("MN", "BK"))
    assert (n_addr, n_cat) == (2, 2 * len(ag.ALLCATS))
    left = con.execute(
        "SELECT borough, frame, count(*) FROM analysis.address GROUP BY 1, 2").fetchall()
    assert sorted(left) == [("BK", ag.LOT_FRAME, 1), ("BK", ag.STREET_FRAME, 1)]
    # idempotent
    assert ag.prune_out_of_scope(con, ("MN", "BK")) == (0, 0)


def test_every_street_point_carries_every_category_row():
    """INVARIANT (f), structural half. A street point is a scored point like
    any other: 15 rows, present or missing alike, so `count(address_category)`
    stays exactly 15 x `count(address)` across BOTH frames."""
    con = _warehouse()
    n_addr, n_cat = con.execute(
        "SELECT (SELECT count(*) FROM analysis.address), "
        "(SELECT count(*) FROM analysis.address_category)").fetchone()
    assert n_cat == len(ag.ALLCATS) * n_addr
    per_street = con.execute(
        "SELECT count(*) FROM analysis.address_category WHERE address_id = 'seg:5:0'"
    ).fetchone()[0]
    assert per_street == len(ag.ALLCATS)


def test_a_censored_street_point_sorts_to_the_bottom_by_density_with_no_gate():
    """INVARIANT (g), and the reason D84 needs no eligibility gate of its own.

    The 701 orphan points with ZERO lots within 400 m -- Randall's Island, Floyd
    Bennett Field, Governors Island -- have a median gap_score of 7.50, which is
    exactly CAP_M / reach(laundry) = 2400/320. That is the CENSORING CAP, not a
    measurement, and on a raw gap_score ranking they would top the list for a
    purely mechanical reason. Reintroducing a gate to remove them would be D75
    in reverse. The mechanism that already exists does it instead: homes_400m is
    0 there, so density is 0, and the owner's density ranking (D83) sorts them
    last for a STATED reason."""
    df = pd.DataFrame({
        "cluster_id": ["BK:laundry:S1", "BK:laundry:0"],
        "borough": ["BK", "BK"],
        "frame": [ag.STREET_FRAME, ag.LOT_FRAME],
        "lead_category": ["laundry", "laundry"],
        "units_capped": [0.0, 300.0],
        "lead_excess_m": [2080.0, 120.0],
        # the island point: no homes in 400 m, so no density
        "density_400m": [0.0, 18_000.0],
        "gap_score": [7.5, 1.4],
    })
    ranked = ag.cluster_table(df, rank_by="density")
    assert ranked["cluster_id"].tolist() == ["BK:laundry:0", "BK:laundry:S1"]
    assert ranked["frame"].tolist() == [ag.LOT_FRAME, ag.STREET_FRAME]
    # ...and on the RAW score it would have been the other way round, which is
    # the failure the density ranking prevents.
    assert df.sort_values("gap_score", ascending=False)["cluster_id"].iloc[0] \
        == "BK:laundry:S1"


def test_summary_reports_the_frames_separately_and_never_pools_them():
    """A street point has no residents. "N addresses have a gap" pooled over
    both frames is ~17% too big, for free, in the direction that flatters the
    screen."""
    G, both = _frame(n_lots=4, n_street=3)
    metrics = _score(G, both)
    df = both.assign(
        units_capped=both["units"], gap_score=metrics["gap_score"],
        lead_category=metrics["lead_category"], n_missing=metrics["n_missing"],
        lead_excess_m=metrics["lead_excess_m"], lead_censored=metrics["lead_censored"],
        eligible=metrics["eligible"], present_count=metrics["present_count"],
        cluster_id=None, density_400m=1.0)
    for i, cat in enumerate(ag.ALLCATS):
        df[f"{cat}_ratio"] = metrics["ratio"][:, i]
        df[f"{cat}_censored"] = metrics["censored"][:, i]
    summary = ag.summarize_gap_run(df, rank_by="units")
    assert set(summary["by_frame"]) == {ag.LOT_FRAME, ag.STREET_FRAME}
    assert summary["by_frame"][ag.LOT_FRAME]["n_addresses"] == 4
    assert summary["by_frame"][ag.STREET_FRAME]["n_addresses"] == 3
    assert summary["by_frame"][ag.STREET_FRAME]["n_units"] == 0.0
    assert summary["n_addresses"] == 7


def test_reach_times_0_8_removes_no_pair_over_BOTH_frames_on_the_warehouse():
    """INVARIANT (i), D75 part b, re-run over the union.

    Tightening a reach must only ever ADD (point, category) gap pairs. It holds
    by construction -- `ratio` reads only that point's own `nearest_m` against
    a reach that is fixed input -- and the reason it is re-asserted here is
    D39: the LITERAL port of the rule DID violate monotonicity, because the
    eligibility gate dropped addresses out of the universe faster than they
    gained gaps. The street frame doubles down on the risk by adding 50k points
    whose gap set is denser and much more censored, so the property is checked
    on the real table rather than argued from the formula."""
    from loci import db as locidb

    if not locidb.DEFAULT_PATH.exists():
        pytest.skip("no live warehouse (data/ is gitignored)")
    con = locidb.connect(read_only=True)
    try:
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='analysis' "
            "AND table_name='address_category'").fetchall()}
        if "frame" not in cols:
            pytest.skip("D84 has not been applied to this warehouse")
        # ratio / 0.8 > ratio for every positive ratio, so the tightened gap set
        # must contain the loose one: count the pairs that would LEAVE it.
        lost, gained = con.execute("""
            SELECT sum(CASE WHEN ratio > 1 AND NOT (ratio / 0.8 > 1) THEN 1 ELSE 0 END),
                   sum(CASE WHEN ratio <= 1 AND ratio / 0.8 > 1 THEN 1 ELSE 0 END)
            FROM analysis.address_category WHERE ratio IS NOT NULL""").fetchone()
        assert lost == 0, f"reach x 0.8 removed {lost:,} pairs"
        assert gained > 0, "reach x 0.8 added no pairs at all -- the test is not testing"
        per_frame = con.execute("""
            SELECT frame, sum(CASE WHEN ratio > 1 AND NOT (ratio / 0.8 > 1) THEN 1 ELSE 0 END)
            FROM analysis.address_category WHERE ratio IS NOT NULL GROUP BY 1""").fetchall()
        assert {f for f, _ in per_frame} == set(ag.FRAMES), per_frame
        assert all(n == 0 for _f, n in per_frame), per_frame
    finally:
        con.close()


def test_the_warehouse_holds_exactly_two_frames_and_the_namespaces_are_disjoint():
    """The domain the DDL cannot enforce (DuckDB refuses an ALTER-ADD with a
    constraint), plus the id namespaces, asserted on the real table."""
    from loci import db as locidb

    if not locidb.DEFAULT_PATH.exists():
        pytest.skip("no live warehouse (data/ is gitignored)")
    con = locidb.connect(read_only=True)
    try:
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='analysis' "
            "AND table_name='address'").fetchall()}
        if "frame" not in cols:
            pytest.skip("D84 has not been applied to this warehouse")
        assert {f for (f,) in con.execute(
            "SELECT DISTINCT frame FROM analysis.address").fetchall()} <= set(ag.FRAMES)
        assert con.execute(
            "SELECT count(*) FROM analysis.address WHERE frame IS NULL").fetchone()[0] == 0
        bad = con.execute("""
            SELECT sum(CASE WHEN frame = 'street' AND address_id NOT LIKE 'seg:%' THEN 1 ELSE 0 END),
                   sum(CASE WHEN frame = 'lot' AND address_id LIKE 'seg:%' THEN 1 ELSE 0 END),
                   sum(CASE WHEN frame = 'street' AND bbl IS NOT NULL THEN 1 ELSE 0 END),
                   sum(CASE WHEN frame = 'street' AND COALESCE(units, -1) <> 0 THEN 1 ELSE 0 END)
            FROM analysis.address""").fetchone()
        assert bad == (0, 0, 0, 0), bad
        # 15 category rows per point, in BOTH frames, exactly.
        n_addr, n_cat = con.execute(
            "SELECT (SELECT count(*) FROM analysis.address), "
            "(SELECT count(*) FROM analysis.address_category)").fetchone()
        assert n_cat == len(ag.ALLCATS) * n_addr
    finally:
        con.close()
