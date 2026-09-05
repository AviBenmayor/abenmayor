"""Demand-side annotation of the gap screen (CHECKPOINT demand-caveat ticket;
Meltzer & Schuetz 2012, src/loci/demand.yaml).

Three things under test:

(a) `loci.demand.load_demand` fails closed -- a category missing from the
    config, or a value outside the allowed vocabulary, raises rather than
    silently defaulting (same discipline as `model.gaps._check_reach_complete`
    for reach.yaml).

(b) On a synthetic fixture: a discretionary category (restaurant) missing in
    a low-income hex is caveated, a necessity (grocery) missing in the SAME
    hex is not, and a discretionary category missing in a mid/high-income hex
    is not.

(c) The demand annotation never changes WHICH hexes are gaps or WHICH (hex,
    category) pairs are missing -- it only adds context columns. Compared
    against the pre-annotation set on the same fixture used by
    tests/test_gaps_monotonicity.py.
"""
from __future__ import annotations

import math

import pytest
import yaml

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.demand import DemandConfigError, load_demand
from loci.model.gaps import ALLCATS, compute_gaps

GOOD_DOC = {
    "low_income_cutoff": 0.80,
    "source": "test",
    "categories": {
        c: {"income_elasticity": "necessity", "evidence": "assumed", "note": "x"}
        for c in CATEGORIES
    },
}


def _write(tmp_path, doc) -> "pathlib.Path":
    p = tmp_path / "demand.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def test_load_demand_fails_closed_on_missing_category(tmp_path, monkeypatch):
    doc = {k: v for k, v in GOOD_DOC.items()}
    doc["categories"] = {c: v for c, v in GOOD_DOC["categories"].items() if c != "hardware"}
    monkeypatch.setattr("loci.demand.DEMAND_PATH", _write(tmp_path, doc))
    with pytest.raises(DemandConfigError, match="hardware"):
        load_demand()


def test_load_demand_fails_closed_on_bad_vocab(tmp_path, monkeypatch):
    doc = {k: v for k, v in GOOD_DOC.items()}
    doc["categories"] = dict(GOOD_DOC["categories"])
    doc["categories"]["grocery"] = {"income_elasticity": "luxury", "evidence": "assumed", "note": "x"}
    monkeypatch.setattr("loci.demand.DEMAND_PATH", _write(tmp_path, doc))
    with pytest.raises(DemandConfigError, match="grocery"):
        load_demand()


def test_load_demand_accepts_the_real_config():
    """The checked-in demand.yaml itself must load and cover all 15 categories --
    the fixture tests above prove the failure path works, this proves the real
    file doesn't trip it."""
    demand = load_demand()
    assert set(demand) == set(CATEGORIES)
    for cat, entry in demand.items():
        assert entry["income_elasticity"] in {"necessity", "discretionary"}
        assert entry["evidence"] in {"paper", "assumed"}


# --- synthetic fixture for (b) and (c) ---------------------------------

FILLER_INCOME = 100_000.0
LOW_INCOME = 30_000.0
HIGH_INCOME = 150_000.0
POP = 1_000.0


def _seed(con) -> None:
    """11 hexes. Every hex has `pharmacy` (necessity) present, satisfying a
    min_present=1 gate everywhere. `grocery` (necessity) present at every hex
    except H_low. `restaurant` (discretionary) present at every filler hex
    (H1..H9) but missing at H_low and H_mid -- 9/11 = 0.818 >= the default
    0.80 `expected` bar, so restaurant IS a conspicuous gap at both target
    hexes. H_low has low household income; H_mid has high household income;
    fillers sit in between so the citywide population-weighted mean lands
    between the two targets' incomes."""
    hexes = {
        "H_low": LOW_INCOME,
        "H_mid": HIGH_INCOME,
        **{f"H{i}": FILLER_INCOME for i in range(1, 10)},
    }
    for h, income in hexes.items():
        con.execute(
            "INSERT INTO analysis.hex (h3_index, resolution, geom, centroid, land_fraction) "
            "VALUES (?, 9, ST_Point(0,0), ST_Point(0,0), 1.0)", [h])
        con.execute(
            "INSERT INTO analysis.hex_demographics "
            "(h3_index, acs_year, population, median_hh_income, renter_share) "
            "VALUES (?, 2023, ?, ?, 0.5)", [h, POP, income])
        con.execute(
            "INSERT INTO analysis.hex_poi_distance (h3_index, poi_id, category, network_m) "
            "VALUES (?, ?, 'pharmacy', 50.0)", [h, f"{h}:pharmacy"])
        if h != "H_low":
            con.execute(
                "INSERT INTO analysis.hex_poi_distance (h3_index, poi_id, category, network_m) "
                "VALUES (?, ?, 'grocery', 50.0)", [h, f"{h}:grocery"])
        if h not in ("H_low", "H_mid"):
            con.execute(
                "INSERT INTO analysis.hex_poi_distance (h3_index, poi_id, category, network_m) "
                "VALUES (?, ?, 'restaurant', 50.0)", [h, f"{h}:restaurant"])


def _fresh_con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _row_by_hex(rows, h):
    for r in rows:
        if r[0] == h:
            return r
    raise AssertionError(f"{h} not in rows")


def test_discretionary_in_low_income_hex_is_caveated_necessity_is_not():
    con = _fresh_con()
    _seed(con)
    rows, _ = compute_gaps(con, threshold=10, min_present=1, expected=0.80, min_pop=0, rule="window")

    # row shape (compute_gaps): h3_index, threshold_min, population,
    # present_count, lead_missing, lead_prevalence, median_hh_income,
    # renter_share, income_class, demand_caveat, caveated_missing,
    # missing_expected (LAST -- see gaps.py's note on why).
    low = _row_by_hex(rows, "H_low")
    missing_low = set(low[-1].split(","))
    caveated_low = set(low[10].split(",")) if low[10] else set()
    assert missing_low == {"grocery", "restaurant"}
    assert low[8] == "low"
    assert "restaurant" in caveated_low, "discretionary missing in a low-income hex must be caveated"
    assert "grocery" not in caveated_low, "necessity missing must never be caveated regardless of income"
    # lead must prefer the non-caveated category (module docstring rule).
    assert low[4] == "grocery"
    assert low[9] is False  # demand_caveat tracks the lead, and the lead is non-caveated here

    mid = _row_by_hex(rows, "H_mid")
    missing_mid = set(mid[-1].split(","))
    caveated_mid = set(mid[10].split(",")) if mid[10] else set()
    assert missing_mid == {"restaurant"}
    assert mid[8] == "mid_high"
    assert caveated_mid == set(), "discretionary missing in a mid/high-income hex must not be caveated"
    assert mid[9] is False


def test_annotation_does_not_change_the_gap_or_missing_sets():
    """Same fixture as tests/test_gaps_monotonicity.py's monotonicity checks --
    here we assert the demand annotation is purely additive: the set of gap
    hexes and the set of (hex, category) missing pairs are identical whether
    or not the demand columns are read. Compares compute_gaps' current
    (annotated) output against re-deriving the gap/missing sets from the
    window rule's own presence+prevalence logic directly."""
    con = _fresh_con()
    _seed(con)
    rows, prevalence = compute_gaps(con, threshold=10, min_present=1, expected=0.80,
                                    min_pop=0, rule="window")

    # Re-derive gap hexes and (hex, category) missing pairs from first principles,
    # mirroring compute_gaps' pre-annotation logic (window presence + gate +
    # prevalence >= expected), with NO reference to demand.yaml at all.
    from loci.model.gaps import _window_presence, _gate
    presence = _window_presence(con, threshold=10, min_pop=0)
    gated = _gate(presence, min_present=1)
    expected_hexes = set()
    expected_pairs = set()
    for h, (pop, pr) in gated.items():
        missing = [c for c in ALLCATS if c not in pr and prevalence[c] >= 0.80]
        if missing:
            expected_hexes.add(h)
            for c in missing:
                expected_pairs.add((h, c))

    actual_hexes = {r[0] for r in rows}
    actual_pairs = {(r[0], c) for r in rows for c in r[-1].split(",")}

    assert actual_hexes == expected_hexes
    assert actual_pairs == expected_pairs


def test_reach_rule_annotation_also_preserves_missing_pairs():
    """Same non-filtering property, `rule='reach'`."""
    con = _fresh_con()
    _seed(con)
    reach = {c: math.inf for c in CATEGORIES}
    reach.update(pharmacy=100.0, grocery=100.0, restaurant=100.0)

    rows, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach", reach=reach)
    pairs_with_annotation = {(r[0], c) for r in rows for c in r[-1].split(",")}

    # H_low: pharmacy present (50<=100), grocery absent -> missing; restaurant absent -> missing.
    # H_mid: pharmacy present, grocery present, restaurant absent -> missing.
    # Fillers H1..H9: all three present -> not missing (no row at all).
    assert pairs_with_annotation == {("H_low", "grocery"), ("H_low", "restaurant"),
                                     ("H_mid", "restaurant")}

    low = _row_by_hex(rows, "H_low")
    caveated_low = set(low[10].split(",")) if low[10] else set()
    assert caveated_low == {"restaurant"}
    mid = _row_by_hex(rows, "H_mid")
    caveated_mid = set(mid[10].split(",")) if mid[10] else set()
    assert caveated_mid == set()
