"""Supply intensity (model/supply_ratio.py): the disjointness guarantee, the
ratio math, the laundry haircut's boundaries, the baseline YAML round-trip and
the supply-hash drift check.

The disjointness test is the load-bearing one. Everything else in this module
is arithmetic that a reader can check by eye; the thing a reader CANNOT check
by eye is whether an UPDATE-only annotation quietly names a column the screen
owns, and that is what turns a non-filtering annotation into a filter.
"""
from __future__ import annotations

import pathlib

import networkx as nx
import numpy as np
import pandas as pd
import pytest
import yaml

from loci.categories import CATEGORIES
from loci.model.supply_ratio import (
    ADDRESS_RATIO_COLUMNS,
    BASELINE_PATH,
    CATEGORY_RATIO_COLUMNS,
    DEFAULT_RADIUS_M,
    HAIRCUT_PATH,
    addressable_units,
    baseline_of,
    box_summary,
    catchment_sums,
    fit_baselines,
    load_baselines,
    load_haircut,
    node_weights,
    p_inhome,
    per_1k,
    ratio_vs_base,
    save_baselines,
)
from loci.score.access import _to_csr

ALLCATS = list(CATEGORIES)


# ------------------------------------------------------- 1. disjointness

def test_set_lists_are_disjoint_from_every_other_module():
    """The non-filtering guarantee, mechanically.

    model/supply_ratio.py may only ever name its own columns in a SET clause.
    If any of them collided with the screen's (gap_score, ratio, eligible...),
    with D57's demand annotation, D62's pipeline columns, D63's age-fit columns
    or D67's storefront columns, a plain re-run of `loci supply-ratio` would
    clobber another module's output -- and, worse, could move the screen.
    """
    from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
    from loci.model.address_gaps import ADDRESS_CATEGORY_SCREEN_COLUMNS, ADDRESS_COLUMNS
    from loci.model.dev_pipeline import PIPELINE_COLUMNS
    from loci.model.storefronts import AGE_FIT_COLUMNS, STOREFRONT_COLUMNS

    mine = set(ADDRESS_RATIO_COLUMNS) | set(CATEGORY_RATIO_COLUMNS)
    others = {
        "address screen": set(ADDRESS_COLUMNS),
        "address_category screen": set(ADDRESS_CATEGORY_SCREEN_COLUMNS),
        "demand annotation": set(DEMAND_ANNOTATION_COLUMNS),
        "pipeline": set(PIPELINE_COLUMNS),
        "age fit": set(AGE_FIT_COLUMNS),
        "storefronts": set(STOREFRONT_COLUMNS),
    }
    for label, cols in others.items():
        assert not (mine & cols), f"supply_ratio collides with {label}: {sorted(mine & cols)}"
    # ... and my own two lists must not overlap each other either: the same
    # name on two tables would make "which table owns this" unanswerable.
    assert not (set(ADDRESS_RATIO_COLUMNS) & set(CATEGORY_RATIO_COLUMNS))


def test_restated_screen_column_list_matches_the_real_one():
    """supply_ratio restates ADDRESS_SCREEN_COLUMNS for its runtime guard. A
    restatement that drifts is a guard that stops guarding."""
    from loci.model.address_gaps import ADDRESS_COLUMNS
    from loci.model.supply_ratio import ADDRESS_SCREEN_COLUMNS

    assert ADDRESS_SCREEN_COLUMNS == ADDRESS_COLUMNS


def test_declared_columns_exist_in_the_schema_ddl():
    """Every column the module writes must be ALTERed into sql/002_schema.sql's
    tail -- and onto the RIGHT table. An UPDATE naming a column that does not
    exist fails at run time, on the live warehouse, after a 3-minute sweep."""
    ddl = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "loci" / "sql" / "002_schema.sql").read_text()
    for col in ADDRESS_RATIO_COLUMNS:
        assert f"analysis.address ADD COLUMN IF NOT EXISTS {col}" in ddl, col
    for col in CATEGORY_RATIO_COLUMNS:
        assert f"analysis.address_category ADD COLUMN IF NOT EXISTS {col}" in ddl, col


def test_address_gaps_view_exposes_the_address_grain_columns():
    """The generated view must carry the category-INDEPENDENT half, and must
    NOT pivot the per-category half (45 columns for a 15-category pivot is the
    duplication D61 removed; age_fit set the precedent)."""
    from loci.model.address_gaps import address_gaps_view_sql

    sql = address_gaps_view_sql()
    # Comments in the generated SQL legitimately NAME the per-category columns
    # to explain why they are absent, so the check runs on the code only.
    code = "\n".join(ln for ln in sql.splitlines() if "--" not in ln)
    for col in ADDRESS_RATIO_COLUMNS:
        assert f"a.{col}" in code, col
    for col in CATEGORY_RATIO_COLUMNS:
        assert col not in code, col


# ---------------------------------------------------------- 2. ratio math

@pytest.mark.parametrize("supply,homes,expected", [
    (4, 2000, 2.0),
    (0, 2000, 0.0),          # zero supply with a real denominator IS zero
    (4, 1000, 4.0),
    (4, 0, None),            # no homes -> no denominator, and that is not 0
    (4, None, None),
    (None, 2000, None),
])
def test_per_1k(supply, homes, expected):
    assert per_1k(supply, homes) == expected


@pytest.mark.parametrize("value,base,expected", [
    (0.5, 1.0, 0.5),
    (2.0, 1.0, 2.0),
    (0.0, 1.0, 0.0),
    (1.0, 0.0, None),        # a category with no norm has no ratio; 0/0 != 1
    (1.0, None, None),
    (None, 1.0, None),
])
def test_ratio_vs_base(value, base, expected):
    assert ratio_vs_base(value, base) == expected


def test_a_present_but_thin_category_is_visible_where_the_gap_test_is_blind():
    """The point of the whole module, in one assertion. Two addresses with the
    SAME `ratio <= 1` screen verdict (a business is within reach at both) but
    eight times the supply intensity at one of them."""
    thin, thick = per_1k(1, 4000), per_1k(8, 4000)
    assert thin == pytest.approx(0.25)
    assert ratio_vs_base(thin, thick) == pytest.approx(0.125)


# ------------------------------------------------------ 3. laundry haircut

def test_haircut_yaml_loads_and_tiles():
    h = load_haircut()
    assert h["category"] == "laundry"
    assert h["evidence_p_inhome"] == 1.0
    bands = h["size_class"]
    assert bands[0]["min_units"] == 1
    assert bands[-1]["max_units"] is None
    for a, b in zip(bands, bands[1:]):       # contiguous, no gap, no overlap
        assert b["min_units"] == a["max_units"] + 1


@pytest.mark.parametrize("units,expected", [
    (1, 0.74), (2, 0.50),                    # NYCHVS 2023, the two CITED ones
    (3, 0.35), (5, 0.35),                    # band boundaries, both ends
    (6, 0.15), (50, 0.15),
    (51, 0.85), (400, 0.85),                 # deliberately NON-monotonic: big
                                             # buildings have a laundry room
])
def test_p_inhome_boundaries(units, expected):
    assert p_inhome(units, False, load_haircut()) == pytest.approx(expected)


@pytest.mark.parametrize("units", [0, None, -3])
def test_no_homes_no_haircut(units):
    """A commercial lot contributes nothing either way; 0 * (1 - p) = 0."""
    h = load_haircut()
    assert p_inhome(units, False, h) == 0.0
    assert addressable_units(units, False, h) == 0.0


def test_evidence_overrides_the_prior_in_one_direction_only():
    """A positive LL84/StreetEasy assertion removes the whole building. The
    ABSENCE of evidence never adds one back -- an LL84 blank and a silent
    amenity list are not observations of 'no laundry' (sql/005 CAVEAT ZERO)."""
    h = load_haircut()
    assert addressable_units(20, True, h) == 0.0             # evidence: none addressable
    assert addressable_units(20, False, h) == pytest.approx(17.0)    # 6-50 prior, 0.15
    assert addressable_units(200, True, h) == 0.0
    assert addressable_units(200, False, h) == pytest.approx(30.0)   # 51+ prior, 0.85


def test_haircut_rejects_a_gappy_band_table(tmp_path):
    """A unit count falling in no band would silently get p = 0 and read as
    fully addressable -- the exact overstatement the table exists to stop."""
    doc = load_haircut()
    doc["size_class"] = [
        {"name": "a", "min_units": 1, "max_units": 2, "p_inhome": 0.5},
        {"name": "b", "min_units": 9, "max_units": None, "p_inhome": 0.5},   # gap 3..8
    ]
    p = tmp_path / "h.yaml"
    p.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="no gap and no overlap"):
        load_haircut(p)


def test_haircut_rejects_a_closed_last_band(tmp_path):
    doc = load_haircut()
    doc["size_class"] = [{"name": "a", "min_units": 1, "max_units": 10, "p_inhome": 0.5}]
    p = tmp_path / "h.yaml"
    p.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="must be open"):
        load_haircut(p)


# --------------------------------------------------------- 4. the baseline

def _long(rows):
    return pd.DataFrame(rows, columns=["address_id", "category", "eligible",
                                       "homes_400m", "supply_400m", "supply_per_1k"])


def test_fit_baselines_is_address_weighted_and_excludes_the_ineligible():
    """Median over ELIGIBLE addresses with a denominator; the 400-unit tower
    and the rowhouse are one observation each. `aggregate_per_1k` is the
    home-weighted alternative and must differ."""
    rows = [
        ("a", "grocery", True,  1000, 1, 1.0),
        ("b", "grocery", True,  1000, 3, 3.0),
        ("c", "grocery", True,  1000, 5, 5.0),
        ("d", "grocery", False, 1000, 99, 99.0),   # ineligible: must not count
        ("e", "grocery", True,     0, 0, None),    # no denominator: must not count
    ]
    out = fit_baselines(_long(rows))["grocery"]
    assert out["n"] == 3
    assert out["median"] == pytest.approx(3.0)
    assert out["p25"] == pytest.approx(2.0)
    assert out["p75"] == pytest.approx(4.0)
    # aggregate is home-weighted over the SAME eligible rows: (1+3+5)/3000*1000
    assert out["aggregate_per_1k"] == pytest.approx(3.0)
    assert out["estimator"] == "median"
    assert baseline_of(out) == pytest.approx(3.0)


def test_a_zero_median_falls_back_to_the_home_weighted_aggregate():
    """A category thin enough that MORE THAN HALF of eligible addresses have
    none within reach (tailor_repair: 966 POIs over MN+BK) has a median of
    exactly 0. A zero norm is not a norm -- every ratio against it would be
    NULL and the category would vanish from the ranking. The fallback is
    declared per category, not silent."""
    rows = [("a", "tailor_repair", True, 1000, 0, 0.0),
            ("b", "tailor_repair", True, 1000, 0, 0.0),
            ("c", "tailor_repair", True, 1000, 3, 3.0)]
    out = fit_baselines(_long(rows))["tailor_repair"]
    assert out["median"] == 0.0
    assert out["estimator"] == "aggregate_per_1k"
    assert baseline_of(out) == pytest.approx(1.0)      # 3 POIs / 3000 homes * 1000
    assert ratio_vs_base(0.0, baseline_of(out)) == 0.0


def test_baseline_of_refuses_a_zero_or_absent_norm():
    assert baseline_of(None) is None
    assert baseline_of({"baseline": 0.0}) is None
    assert baseline_of({"median": 2.0}) == 2.0          # pre-estimator YAML


def test_fit_baselines_emits_every_category_even_with_no_rows():
    """A category with nothing in scope gets an explicit None, not a missing
    key: a KeyError downstream reads as a crash, a None reads as 'no norm'."""
    out = fit_baselines(_long([("a", "grocery", True, 1000, 2, 2.0)]))
    assert set(out) == set(ALLCATS)
    assert out["tailor_repair"]["median"] is None
    assert out["tailor_repair"]["n"] == 0


def test_fit_baselines_skips_a_swept_category_with_zero_supply(monkeypatch):
    """GTM-209 (2026-09-22): distinct from the 'not in scope at all' fixture
    above. A category that WAS swept -- a row exists for every address, exactly
    what compute_supply_ratio emits for a real (unignested) category like
    bathhouse_sauna -- but whose supply_400m is 0 EVERYWHERE has no evidence
    to fit a baseline from. It must be ABSENT from the output entirely, not
    written as a fabricated `baseline: 0.0` (tests/test_category_registry.py's
    GTM-198 G8 rule: 'a hand-written row would be a fabrication'). Uses a
    fake ALLCATS via monkeypatch so this test does not depend on which real
    slug happens to be unfitted today."""
    import loci.model.supply_ratio as sr_mod

    monkeypatch.setattr(sr_mod, "ALLCATS", ["grocery", "bathhouse_sauna"])
    rows = [
        ("a", "grocery", True, 1000, 2, 2.0),
        ("b", "grocery", True, 1000, 4, 4.0),
        ("a", "bathhouse_sauna", True, 1000, 0, 0.0),
        ("b", "bathhouse_sauna", True, 1000, 0, 0.0),
    ]
    out = fit_baselines(_long(rows))
    assert set(out) == {"grocery"}
    assert "bathhouse_sauna" not in out


def test_baseline_yaml_round_trip(tmp_path):
    doc = {
        "supply_hash": "deadbeef1234", "supply_set": "principled",
        "asof": "2026-09-11", "radius_m": 400.0, "boroughs": ["MN", "BK"],
        "universe": "all addresses with homes_400m > 0",
        "n_addresses": 281842, "graph_version": "abc123",
        "categories": fit_baselines(_long([("a", "grocery", True, 1000, 2, 2.0)])),
    }
    p = save_baselines(doc, tmp_path / "b.yaml")
    back = load_baselines(p)
    assert back["supply_hash"] == "deadbeef1234"
    assert back["categories"]["grocery"]["median"] == pytest.approx(2.0)
    assert set(back["categories"]) == set(ALLCATS)
    assert "REVEALED SUPPLY" in p.read_text()     # the D6 caveat ships with the file


def test_missing_baseline_fails_loudly(tmp_path):
    """A ratio with no norm is not a ratio. Never default the baseline to 1.0."""
    with pytest.raises(FileNotFoundError, match="no meaning without the norm"):
        load_baselines(tmp_path / "nope.yaml")


# ------------------------------------------------------------ 5. the engine

def _line_graph(n=13):
    """n nodes on a W-E line ~100 m apart at NYC latitude -- the same fixture
    shape as tests/test_address_gaps.py and test_storefront_registry.py, so a
    catchment here is read on the same ruler as the screen's nearest_m."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    dx = 100 / 84400.0
    for i in range(n):
        G.add_node(i, x=-73.98 + i * dx, y=40.75)
    for i in range(n - 1):
        G.add_edge(i, i + 1, length=100.0)
        G.add_edge(i + 1, i, length=100.0)
    return G


def test_catchment_sums_counts_exactly_the_radius_inclusive():
    """On a 100 m line: from node 5, a 400 m catchment reaches nodes 1..9
    inclusive (400 m is IN, 500 m is OUT) and includes node 5 itself."""
    A, idx = _to_csr(_line_graph(13))
    W = np.zeros((A.shape[0], 1))
    for i in range(13):
        W[idx[i], 0] = 1.0
    got = catchment_sums(A, np.array([idx[5]]), W, radius_m=400.0)
    assert got[0, 0] == pytest.approx(9.0)
    assert catchment_sums(A, np.array([idx[5]]), W, radius_m=0.0)[0, 0] == pytest.approx(1.0)


def test_catchment_sums_is_weighted_not_a_head_count():
    """Homes are UNITS, not buildings: a 300-unit tower and a 1-unit rowhouse
    on the same node contribute 301, never 2."""
    A, idx = _to_csr(_line_graph(5))
    W = np.zeros((A.shape[0], 1))
    W[idx[2], 0] = 301.0
    assert catchment_sums(A, np.array([idx[2]]), W, radius_m=100.0)[0, 0] == 301.0


def test_catchment_sums_is_symmetric_in_the_two_readings():
    """The reversal the module rests on: on an undirected graph, "weights
    within r of node i" summed over i equals "nodes within r of weight j"
    summed over j. If this ever failed, sourcing from the query nodes instead
    of from the POIs would not be the same computation."""
    A, idx = _to_csr(_line_graph(9))
    n = A.shape[0]
    W = np.zeros((n, 1))
    for i in (1, 4, 7):
        W[idx[i], 0] = 1.0
    q = np.array([idx[i] for i in range(9)])
    forward = catchment_sums(A, q, W, radius_m=200.0).sum()
    Wq = np.zeros((n, 1))
    for i in range(9):
        Wq[idx[i], 0] += 1.0
    reverse = catchment_sums(A, np.array([idx[i] for i in (1, 4, 7)]), Wq,
                             radius_m=200.0).sum()
    assert forward == pytest.approx(reverse)


def test_catchment_sums_batches_agree_with_one_shot():
    A, idx = _to_csr(_line_graph(11))
    W = np.zeros((A.shape[0], 2))
    for i in range(11):
        W[idx[i], 0] = 1.0
        W[idx[i], 1] = float(i)
    q = np.array([idx[i] for i in range(11)])
    assert np.allclose(catchment_sums(A, q, W, 300.0, batch=2),
                       catchment_sums(A, q, W, 300.0, batch=64))


def test_node_weights_accumulates_never_dedupes():
    """Two laundromats at one intersection are two laundromats."""
    W = node_weights({}, {"x": np.array([3, 3, 5])},
                     {"x": np.array([1.0, 1.0, 1.0])}, n_nodes=8)
    assert W[3, 0] == 2.0 and W[5, 0] == 1.0 and W.sum() == 3.0


# --------------------------------------------------------- 6. the box table

def test_box_summary_ranks_by_ratio_and_respects_eligibility():
    addr = pd.DataFrame({
        "address_id": ["a", "b", "c"],
        "lat": [40.675, 40.676, 40.900],          # c is outside the box
        "lon": [-73.99, -73.99, -73.99],
        "eligible": [True, False, True],          # b is ineligible
    })
    long_df = pd.DataFrame([
        {"address_id": "a", "category": "pharmacy", "supply_400m": 1,
         "homes_400m": 4000, "supply_per_1k": 0.25},
        {"address_id": "a", "category": "bar", "supply_400m": 8,
         "homes_400m": 4000, "supply_per_1k": 2.0},
        {"address_id": "b", "category": "pharmacy", "supply_400m": 99,
         "homes_400m": 4000, "supply_per_1k": 99.0},
        {"address_id": "c", "category": "pharmacy", "supply_400m": 99,
         "homes_400m": 4000, "supply_per_1k": 99.0},
    ])
    base = {"pharmacy": {"baseline": 2.5}, "bar": {"baseline": 2.0}}
    out = box_summary(long_df, addr, (40.670, 40.682), (-74.0, -73.982), base)
    assert list(out["category"])[:2] == ["pharmacy", "bar"]     # thinnest first
    row = out.set_index("category").loc["pharmacy"]
    assert row["ratio"] == pytest.approx(0.1)     # 0.25 / 2.5 -- b and c excluded
    assert out.set_index("category").loc["bar", "ratio"] == pytest.approx(1.0)
    assert out["ratio"].isna().sum() == len(ALLCATS) - 2        # no norm -> no ratio


# -------------------------------------------------------- 7. the drift test

def test_baseline_supply_hash_matches_the_live_poi_supply():
    """The baseline is only comparable to ratios computed on the SAME supply
    set. analysis.poi_supply is a VIEW: re-running dedup or landing an anchor
    moves it silently, and every ratio in the warehouse then mixes two sets.

    Skipped with a reason when the warehouse is absent (a fresh clone, CI) --
    a missing database must not read as a passing drift check.
    """
    from loci import db as locidb

    if not BASELINE_PATH.exists():
        pytest.skip("model/supply_baseline.yaml not fitted yet "
                    "(`loci supply-ratio --fit-baseline`)")
    if not locidb.DEFAULT_PATH.exists():
        pytest.skip(f"warehouse absent at {locidb.DEFAULT_PATH}; drift cannot be checked")

    from loci.model.supply_asof import baseline_asof
    from loci.score.supply import supply_hash

    doc = load_baselines()
    asof = baseline_asof()
    con = locidb.connect(read_only=True)
    try:
        live = supply_hash(con, doc.get("supply_set", "principled"), asof=asof)
    finally:
        con.close()
    assert doc["supply_hash"] == live, (
        f"supply_baseline.yaml was fitted on supply {doc['supply_hash']} at as-of "
        f"{asof} but the live set at that same as-of date is {live}. Every "
        f"supply_ratio_vs_base in the warehouse now mixes two supply sets. This is "
        f"a REAL evidence change (a closure verdict, a dedup re-run, an anchor), "
        f"not a date roll -- the date is pinned. Re-fit with "
        f"`loci supply-ratio --boroughs MN,BK --fit-baseline`.")


def test_the_hash_at_the_next_day_may_differ_and_that_is_not_a_failure():
    """THE POINT OF THE PIN, asserted rather than described.

    The hash at the baseline's as-of date is what the drift test above pins.
    The hash ONE DAY LATER is allowed to differ -- licences lapse and evidence
    ages -- and that difference must not fail anything, because it is not a
    change to the warehouse. It is what `loci supply-asof advance` exists to
    make into a deliberate, announced event.

    Measured on the 2026-09-16 build: ba944e18c57b at 2026-09-15, 18eb5ab24629
    at 2026-09-16, 12 POIs flipping (9 lapsed licences leaving supply, 3 DOHMH
    inspections aging out of the OPEN window and staying).
    """
    import datetime as dt

    from loci import db as locidb
    from loci.model.supply_asof import baseline_asof, status_flips
    from loci.score.supply import supply_hash

    if not BASELINE_PATH.exists() or not locidb.DEFAULT_PATH.exists():
        pytest.skip("warehouse or baseline absent; the date roll cannot be priced")

    asof = baseline_asof()
    nxt = asof + dt.timedelta(days=1)
    con = locidb.connect(read_only=True)
    try:
        h0 = supply_hash(con, asof=asof)
        h1 = supply_hash(con, asof=nxt)
        flips = status_flips(con, asof, nxt)
    finally:
        con.close()

    # No assertion that they DIFFER (on a quiet day they will not) and none
    # that they AGREE (a lapsing licence is not a defect). What is asserted is
    # that the difference is fully explained by the date: every flip carries a
    # date-dependent reason, so nothing else has moved underneath.
    if h0 != h1:
        assert not flips.empty, (
            f"the hash moved with the date ({h0} -> {h1}) but no POI changed "
            f"verdict. Something other than the as-of date is in the hash.")
        assert set(flips["reason"]) <= {
            "licence expiry lapsed",
            "evidence aged past the open-evidence window",
        }, f"a date roll produced a flip with no date-dependent cause: {flips}"


def test_baseline_yaml_declares_its_radius_and_universe():
    if not BASELINE_PATH.exists():
        pytest.skip("model/supply_baseline.yaml not fitted yet")
    doc = load_baselines()
    assert doc["radius_m"] == pytest.approx(DEFAULT_RADIUS_M)
    assert doc["boroughs"] == ["MN", "BK"]
    # GTM-198 G8 (owner 2026-09-17): bathhouse_sauna's baseline lands with the
    # first ingest on the announced hash; until then the unfitted set is
    # exactly that one slug, and a hand-written row would be a fabrication.
    assert set(ALLCATS) - set(doc["categories"]) == {"bathhouse_sauna"}
    assert set(doc["categories"]) <= set(ALLCATS)
    assert HAIRCUT_PATH.exists()
