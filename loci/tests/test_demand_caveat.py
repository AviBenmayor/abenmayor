"""Demand-side annotation of the gap screen (Meltzer & Schuetz 2012,
src/loci/demand.yaml + src/loci/spend.yaml; rebuilt by the GTM-109 contrarian
review).

Six things under test:

(a) `loci.demand.load_demand` fails closed -- a category missing from
    demand.yaml, a category with no `income_elasticity` in spend.yaml, or an
    `evidence` value outside the vocabulary raises rather than silently
    defaulting (same discipline as `model.gaps._check_reach_complete` for
    reach.yaml).

(b) THE 7/7 CHECK. The classes are DERIVED from spend.yaml's BLS CEX
    elasticity at demand.yaml's `cutoff_elasticity`, and that derivation
    reproduces all seven of Meltzer & Schuetz's own paper-backed rows exactly.
    This is the entire evidentiary basis for the split -- if it ever fails, the
    cut point has stopped being a reproduction of the paper and has become a
    free parameter again, which is precisely the defect GTM-109 removed.

(b2) DRIFT. Every category in categories.yaml has a spend.yaml elasticity.
    The class is derived from that number, so a category added to the registry
    without one would otherwise be silently unclassifiable.

(c) On a synthetic fixture: a discretionary category (restaurant) missing in a
    confidently-low-income hex is caveated, a necessity (grocery) missing in
    the SAME hex is not, and a discretionary category missing in a
    mid/high-income hex is not.

(d) The annotation never changes WHICH hexes are gaps or WHICH (hex, category)
    pairs are missing -- for BOTH rules, and now also under a demand config
    that classifies everything as a necessity (i.e. the annotation switched
    fully off). It adds context columns and nothing else; nothing sorts,
    filters, ranks or scores on it.

(e) The continuous, MOE-aware output: income_ratio, its ACS derived-ratio MOE,
    income_indeterminate near the cutoff, and demand_caveat_text emitted only
    when the hex is CONFIDENTLY below the cutoff -- always carrying the X6
    disclaimer.
"""
from __future__ import annotations

import math

import pytest
import yaml

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.demand import (
    X6_DISCLAIMER,
    DemandConfigError,
    caveat_categories,
    classify,
    load_cutoff_elasticity,
    load_demand,
    load_spend_elasticities,
)
from loci.model.gaps import ALLCATS, _ratio_moe, compute_gaps
# tests/ has no __init__.py, so pytest puts it on sys.path and conftest is a
# plain top-level module here.
from conftest import TEST_CITYWIDE_MEAN_HH_INCOME as CITYWIDE
from conftest import TEST_CITYWIDE_MEAN_HH_INCOME_MOE as CITYWIDE_MOE

GOOD_DOC = {
    "cutoff_elasticity": 0.35,
    "low_income_cutoff": 0.80,
    "source": "test",
    "categories": {c: {"evidence": "cex", "note": "x"} for c in CATEGORIES},
}


def _write(tmp_path, doc) -> "pathlib.Path":
    p = tmp_path / "demand.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


# --- (a) fail-closed -----------------------------------------------------

def test_load_demand_fails_closed_on_missing_category(tmp_path, monkeypatch):
    doc = dict(GOOD_DOC)
    doc["categories"] = {c: v for c, v in GOOD_DOC["categories"].items() if c != "hardware"}
    monkeypatch.setattr("loci.demand.DEMAND_PATH", _write(tmp_path, doc))
    with pytest.raises(DemandConfigError, match="hardware"):
        load_demand()


def test_load_demand_fails_closed_on_bad_vocab(tmp_path, monkeypatch):
    doc = dict(GOOD_DOC)
    doc["categories"] = dict(GOOD_DOC["categories"])
    doc["categories"]["grocery"] = {"evidence": "assumed", "note": "x"}
    monkeypatch.setattr("loci.demand.DEMAND_PATH", _write(tmp_path, doc))
    with pytest.raises(DemandConfigError, match="grocery"):
        load_demand()


def test_load_demand_fails_closed_without_a_cut_point(tmp_path, monkeypatch):
    doc = {k: v for k, v in GOOD_DOC.items() if k != "cutoff_elasticity"}
    monkeypatch.setattr("loci.demand.DEMAND_PATH", _write(tmp_path, doc))
    with pytest.raises(DemandConfigError, match="cutoff_elasticity"):
        load_demand()


def test_load_demand_fails_closed_when_spend_has_no_elasticity(tmp_path, monkeypatch):
    """The class is derived from spend.yaml; a category with no elasticity
    there must raise, never default to necessity."""
    from loci import demand as demand_mod
    doc = yaml.safe_load(demand_mod.SPEND_PATH.read_text())
    doc["categories"]["hardware"].pop("income_elasticity")
    p = tmp_path / "spend.yaml"
    p.write_text(yaml.safe_dump(doc))
    monkeypatch.setattr("loci.demand.SPEND_PATH", p)
    with pytest.raises(DemandConfigError, match="hardware"):
        load_demand()


def test_load_demand_accepts_the_real_config():
    """The checked-in demand.yaml + spend.yaml pair must load and cover all 15
    categories -- the fixture tests above prove the failure paths work, this
    proves the real files don't trip them."""
    demand = load_demand()
    assert set(demand) == set(CATEGORIES)
    for cat, entry in demand.items():
        assert entry["income_elasticity"] in {"necessity", "discretionary"}
        assert entry["evidence"] in {"paper", "cex"}, cat
        assert isinstance(entry["elasticity"], float)
        assert entry["note"], f"{cat} has no note"


# --- (b) the 7/7 reproduction of Meltzer & Schuetz ------------------------

#: The seven rows Meltzer & Schuetz classify DIRECTLY (Tables 5-7): necessity
#: from Table 6 (groceries per acre HIGHER in low-income ZIPs, 0.051 vs 0.036;
#: drugstores only a small gap), discretionary from Tables 5-7 (food service
#: and gyms, 0.29 vs 1.04 per ZIP, concentrate in higher-income ZIPs).
PAPER_ROWS = {
    "grocery": "necessity",
    "convenience": "necessity",
    "pharmacy": "necessity",
    "restaurant": "discretionary",
    "cafe_bakery": "discretionary",
    "bar": "discretionary",
    "fitness": "discretionary",
}


def test_derived_classes_reproduce_the_seven_paper_rows_exactly():
    """THE load-bearing test. Cutting spend.yaml's BLS CEX elasticity at
    demand.yaml's `cutoff_elasticity` must reproduce all seven paper-backed
    rows -- that 7/7 out-of-sample agreement is the only reason the cut point
    is a derivation rather than an owner prior (GTM-109 §1). If this fails, the
    annotation is no longer defensible and must not ship."""
    demand = load_demand()
    derived = {c: demand[c]["income_elasticity"] for c in PAPER_ROWS}
    assert derived == PAPER_ROWS
    # ...and each of those seven is still marked as paper-backed, so the
    # citation and the derivation are asserting the same thing.
    for c in PAPER_ROWS:
        assert demand[c]["evidence"] == "paper", c


def test_cut_point_is_the_one_that_achieves_7_of_7():
    """Guards the cut point itself, not just today's classes: no OTHER cut
    point on the CEX scale may also reproduce the paper's seven rows while
    disagreeing with the one in demand.yaml. (The admissible band is
    [0.35, 0.40): grocery at 0.35 must stay a necessity, fitness/cafe at 0.40
    must stay discretionary.)"""
    e = load_spend_elasticities()
    cut = load_cutoff_elasticity()
    assert all(classify(e[c], cut) == want for c, want in PAPER_ROWS.items())
    for bad in (0.30, 0.34, 0.40, 0.45):
        assert any(classify(e[c], bad) != want for c, want in PAPER_ROWS.items()), (
            f"cut point {bad} also reproduces 7/7 -- the cut point is under-identified")


def test_former_owner_priors_are_now_derived_and_marked_cex():
    """The eight rows that were `evidence: assumed` before GTM-109 are all
    `cex` now, and the rule puts every one of them in NECESSITY -- the
    conservative direction (fewer gaps caveated away). nails_beauty (0.35, =
    grocery) and tailor_repair (0.30, = hair_barber) are the two that flipped
    out of `discretionary`."""
    demand = load_demand()
    former_priors = ["laundry", "hair_barber", "nails_beauty", "tailor_repair",
                     "childcare", "clinic", "bank", "hardware"]
    for c in former_priors:
        assert demand[c]["evidence"] == "cex", c
        assert demand[c]["income_elasticity"] == "necessity", c
    assert demand["nails_beauty"]["elasticity"] == demand["grocery"]["elasticity"]
    assert demand["tailor_repair"]["elasticity"] == demand["hair_barber"]["elasticity"]


def test_clinic_is_excluded_from_the_annotation_entirely():
    """CHECKPOINT D30 excludes clinic from headline claims pending
    re-anchoring; annotating a category whose supply layer is not trusted
    asserts a confidence the data does not support (GTM-109 §5). The exclusion
    is independent of the derived class, so a later coverage fix cannot
    silently start annotating it."""
    demand = load_demand()
    assert demand["clinic"]["annotate"] is False
    assert "clinic" not in caveat_categories()
    assert all(demand[c]["annotate"] for c in CATEGORIES if c != "clinic")


def test_caveat_set_is_exactly_the_four_paper_discretionary_categories_plus_bathhouse():
    # The four paper-backed rows, plus bathhouse_sauna: its class is DERIVED
    # (CEX "Fees and admissions" elasticity 0.40 > 0.35, spend.yaml) and the
    # owner widened this exact-set pin on 2026-09-17 (GTM-198) rather than
    # have the number hand-set below the cut to keep the set at four.
    assert caveat_categories() == {"restaurant", "cafe_bakery", "bar", "fitness", "bathhouse_sauna"}


# --- (b2) drift ----------------------------------------------------------

def test_every_registry_category_has_a_spend_elasticity():
    """Drift check between categories.yaml and spend.yaml. The demand class is
    derived from `income_elasticity`, so a category added to the registry
    without one has no class at all -- catch that here rather than at the point
    where a gap row silently loses its annotation."""
    elasticities = load_spend_elasticities()
    assert set(elasticities) == set(CATEGORIES)
    for c, e in elasticities.items():
        assert 0.0 <= e <= 1.0, f"{c} elasticity {e} outside [0, 1]"


# --- synthetic fixture for (c), (d) and (e) ------------------------------

FILLER_INCOME = 100_000.0
LOW_INCOME = 30_000.0
HIGH_INCOME = 150_000.0
MOE = 6_000.0          # ~5% of a filler income: small enough that H_low and
                       # H_mid are both CONFIDENTLY on their side of the line
POP = 1_000.0


def _seed(con) -> None:
    """11 hexes. Every hex has `pharmacy` (necessity) present, satisfying a
    min_present=1 gate everywhere. `grocery` (necessity) present at every hex
    except H_low. `restaurant` (discretionary) present at every filler hex
    (H1..H9) but missing at H_low and H_mid -- 9/11 = 0.818 >= the default
    0.80 `expected` bar, so restaurant IS a conspicuous gap at both target
    hexes. H_low sits confidently below 0.80 x the pinned citywide mean
    ($102,315); H_mid sits confidently above it."""
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
            "(h3_index, acs_year, population, median_hh_income, median_hh_income_moe, renter_share) "
            "VALUES (?, 2023, ?, ?, ?, 0.5)", [h, POP, income, MOE])
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


# Row shape (compute_gaps / _compute_gaps_reach): h3_index, threshold_min,
# population, present_count, lead_missing, lead_prevalence, median_hh_income,
# renter_share, income_class, demand_caveat, caveated_missing, income_ratio,
# income_ratio_moe, income_indeterminate, demand_caveat_text, missing_expected
# (LAST -- see gaps.py's note on why).
I_INCOME, I_CLASS, I_CAVEAT, I_CAVMISS = 6, 8, 9, 10
I_RATIO, I_RATIO_MOE, I_INDET, I_TEXT = 11, 12, 13, 14


# --- (c) --------------------------------------------------------------------

def test_discretionary_in_low_income_hex_is_caveated_necessity_is_not():
    con = _fresh_con()
    _seed(con)
    rows, _ = compute_gaps(con, threshold=10, min_present=1, expected=0.80, min_pop=0, rule="window")

    low = _row_by_hex(rows, "H_low")
    missing_low = set(low[-1].split(","))
    caveated_low = set(low[I_CAVMISS].split(",")) if low[I_CAVMISS] else set()
    assert missing_low == {"grocery", "restaurant"}
    assert low[I_CLASS] == "low"
    assert "restaurant" in caveated_low, "discretionary missing in a low-income hex must be caveated"
    assert "grocery" not in caveated_low, "necessity missing must never be caveated regardless of income"
    # lead must prefer the non-caveated category (module docstring rule).
    assert low[4] == "grocery"
    assert low[I_CAVEAT] is False  # demand_caveat tracks the lead, and the lead is non-caveated here

    mid = _row_by_hex(rows, "H_mid")
    missing_mid = set(mid[-1].split(","))
    caveated_mid = set(mid[I_CAVMISS].split(",")) if mid[I_CAVMISS] else set()
    assert missing_mid == {"restaurant"}
    assert mid[I_CLASS] == "mid_high"
    assert caveated_mid == set(), "discretionary missing in a mid/high-income hex must not be caveated"
    assert mid[I_CAVEAT] is False
    assert mid[I_TEXT] is None


# --- (d) non-filtering, non-ranking -----------------------------------------

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
    caveated_low = set(low[I_CAVMISS].split(",")) if low[I_CAVMISS] else set()
    assert caveated_low == {"restaurant"}
    mid = _row_by_hex(rows, "H_mid")
    caveated_mid = set(mid[I_CAVMISS].split(",")) if mid[I_CAVMISS] else set()
    assert caveated_mid == set()


@pytest.mark.parametrize("rule", ["window", "reach"])
def test_gap_sets_identical_with_the_annotation_switched_off(rule, monkeypatch):
    """The sharpest form of "never filters, never ranks" (GTM-109 release
    condition): run the screen twice, once normally and once with a demand
    config that classifies EVERY category as a necessity so nothing can ever be
    caveated. The gap hexes, the (hex, category) missing pairs, population and
    present_count must be byte-identical. Only the annotation columns -- and,
    where a caveat exists, `lead_missing` -- may differ.

    A regression that made the annotation filter or re-rank the gap set would
    show up here as a set difference; nothing else in the repo sorts or filters
    on demand_caveat (verified by grep at the time of writing: it appears only
    in gaps.py, the schema DDL, docs and this test)."""
    con = _fresh_con()
    _seed(con)
    reach = {c: math.inf for c in CATEGORIES}
    reach.update(pharmacy=100.0, grocery=100.0, restaurant=100.0)
    kwargs = dict(min_present=1, min_pop=0, rule=rule)
    if rule == "reach":
        kwargs["reach"] = reach

    annotated, _ = compute_gaps(con, **kwargs)

    real = load_demand()
    monkeypatch.setattr("loci.model.gaps.caveat_categories", lambda: set())
    monkeypatch.setattr("loci.model.gaps.load_demand",
                        lambda: {c: {**v, "income_elasticity": "necessity"} for c, v in real.items()})
    plain, _ = compute_gaps(con, **kwargs)

    def core(rows):
        # h3_index, population, present_count, missing_expected -- everything
        # the screen actually claims, with the annotation columns dropped.
        return sorted((r[0], r[2], r[3], r[-1]) for r in rows)

    assert core(annotated) == core(plain)
    assert {r[0] for r in annotated} == {r[0] for r in plain}
    assert ({(r[0], c) for r in annotated for c in r[-1].split(",")}
            == {(r[0], c) for r in plain for c in r[-1].split(",")})
    # and the annotation really was doing something in the first run, so this
    # test is not vacuous
    assert any(r[I_CAVMISS] for r in annotated)
    assert not any(r[I_CAVMISS] for r in plain)


# --- (e) continuous, MOE-aware output ---------------------------------------

def test_ratio_moe_matches_the_acs_derived_ratio_formula():
    """MOE(X/Y) ~= (1/Y) * sqrt(MOE_X^2 + R^2 * MOE_Y^2) -- the RATIO form
    (terms add), not the proportion form (terms subtract)."""
    x, xm, y, ym = 30_000.0, 6_000.0, 127_894.0, 988.0
    r = x / y
    assert _ratio_moe(x, xm, y, ym) == pytest.approx(
        math.sqrt(xm ** 2 + (r ** 2) * (ym ** 2)) / y)
    # unknown numerator MOE -> unclassifiable, never "exact"
    assert _ratio_moe(x, None, y, ym) is None


def test_income_ratio_and_moe_are_carried_on_every_row():
    con = _fresh_con()
    _seed(con)
    rows, _ = compute_gaps(con, threshold=10, min_present=1, expected=0.80, min_pop=0, rule="window")

    low = _row_by_hex(rows, "H_low")
    assert low[I_RATIO] == pytest.approx(LOW_INCOME / CITYWIDE)
    assert low[I_RATIO_MOE] == pytest.approx(
        _ratio_moe(LOW_INCOME, MOE, CITYWIDE, CITYWIDE_MOE))
    # 0.235 + 0.047 is nowhere near 0.80 -> determinate, and confidently low
    assert low[I_INDET] is False
    assert low[I_TEXT] is not None

    mid = _row_by_hex(rows, "H_mid")
    assert mid[I_RATIO] == pytest.approx(HIGH_INCOME / CITYWIDE)
    assert mid[I_INDET] is False
    assert mid[I_TEXT] is None


def test_caveat_text_is_worded_continuous_and_carries_the_x6_disclaimer():
    con = _fresh_con()
    _seed(con)
    rows, _ = compute_gaps(con, threshold=10, min_present=1, expected=0.80, min_pop=0, rule="window")
    text = _row_by_hex(rows, "H_low")[I_TEXT]
    assert "household income 23% of citywide mean" in text
    assert "pts)" in text                       # the MOE travels with the ratio
    assert "restaurant 0.45" in text            # the BLS CEX elasticity, not a class word
    assert X6_DISCLAIMER in text, "the X6 disclaimer must never be detachable from the caveat"


def test_hex_within_one_moe_of_the_cutoff_is_indeterminate_and_never_caveated():
    """The review's core statistical objection: ~55% of real gap hexes sit
    within one ACS MOE of the cutoff, where `income_class` is a coin flip. Such
    a hex must be flagged indeterminate and must NOT get a caveat, even though
    its point estimate is below the line."""
    con = _fresh_con()
    _seed(con)
    cutoff_income = 0.80 * CITYWIDE
    borderline = cutoff_income - 1_000.0        # below the line by far less than its MOE
    con.execute("UPDATE analysis.hex_demographics SET median_hh_income = ?, "
                "median_hh_income_moe = ? WHERE h3_index = 'H_low'",
                [borderline, 15_000.0])

    rows, _ = compute_gaps(con, threshold=10, min_present=1, expected=0.80, min_pop=0, rule="window")
    low = _row_by_hex(rows, "H_low")
    assert low[I_CLASS] == "low"                # point estimate still says low...
    assert low[I_INDET] is True                 # ...but it cannot be asserted
    assert low[I_CAVMISS] == ""                 # so nothing is caveated
    assert low[I_TEXT] is None
    # and the gap set is untouched by any of that
    assert set(low[-1].split(",")) == {"grocery", "restaurant"}


def test_missing_moe_fails_closed_to_no_caveat():
    """No MOE, no assertion: a hex whose income MOE is NULL gets a ratio but
    neither an indeterminacy verdict nor a caveat."""
    con = _fresh_con()
    _seed(con)
    con.execute("UPDATE analysis.hex_demographics SET median_hh_income_moe = NULL "
                "WHERE h3_index = 'H_low'")
    rows, _ = compute_gaps(con, threshold=10, min_present=1, expected=0.80, min_pop=0, rule="window")
    low = _row_by_hex(rows, "H_low")
    assert low[I_RATIO] == pytest.approx(LOW_INCOME / CITYWIDE)
    assert low[I_RATIO_MOE] is None
    assert low[I_INDET] is None
    assert low[I_CAVMISS] == ""
    assert low[I_TEXT] is None
