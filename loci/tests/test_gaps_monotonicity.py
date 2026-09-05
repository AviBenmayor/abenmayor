"""Monotonicity acceptance test for the gap screen (QUESTIONS D6, CHECKPOINT D33).

The property a "missing" rule must satisfy: adding a business of category c
ANYWHERE can never turn a not-missing hex into a missing one, and tightening a
distance parameter (a walk window, or a reach) can only ADD hexes to the
missing set, never remove them.

The OLD rule (`rule="window"`) fails this by construction: it decides whether
category c is "expected" from a citywide PREVALENCE that is recomputed from
scratch every call, over every populated hex — so a business added anywhere
can push a category's prevalence over the `expected` bar and flip a hex on
the other side of the city into a fresh gap, with nothing near that hex
having changed. `test_window_rule_violates_monotonicity` reproduces exactly
this (the mechanism behind CHECKPOINT D31/D33's Manhattan 10-vs-5-minute
flip) on a tiny synthetic fixture — it PASSES by asserting the bad flip
happens, i.e. it documents/pins the defect.

The NEW rule (`rule="reach"`) fixes this because "is hex h missing c" reads
only h's own nearest-c distance against a reach(c) that is fixed input, not
recomputed from the rest of the dataset. `test_reach_rule_satisfies_*`
confirms both halves of the property on the same fixture.
"""
from __future__ import annotations

import math

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.model.gaps import compute_gaps, _eligible_universe

GROCERY_D = 50.0    # every hex has grocery this close — keeps each hex in every
                     # window's result set and keeps min_present trivially satisfied,
                     # isolating the hardware-only effect under test.


def _full_reach(**overrides: float) -> dict[str, float]:
    """A complete reach dict (all 15 categories -- `rule="reach"` fails closed
    on an incomplete one, defect review item 2) defaulting every category to
    +inf ("never a gap") except the ones named in `overrides`, which isolates
    the category under test exactly like the old `reach.get(c, math.inf)`
    default used to (informally, and buggily -- see item 2's fix) do for
    every caller, not just tests."""
    r = {c: math.inf for c in CATEGORIES}
    r.update(overrides)
    return r


def _seed(con, hardware: dict[str, float | None], population: float = 1000.0) -> None:
    """hardware: {h3_index: network_m or None (absent)}. Every hex also gets grocery
    at GROCERY_D. Ids H0..H10 by construction; caller passes the hardware map."""
    for h in hardware:
        con.execute(
            "INSERT INTO analysis.hex (h3_index, resolution, geom, centroid, land_fraction) "
            "VALUES (?, 9, ST_Point(0,0), ST_Point(0,0), 1.0)", [h])
        con.execute(
            "INSERT INTO analysis.hex_demographics (h3_index, acs_year, population) VALUES (?, 2023, ?)",
            [h, population])
        con.execute(
            "INSERT INTO analysis.hex_poi_distance (h3_index, poi_id, category, network_m) "
            "VALUES (?, ?, 'grocery', ?)", [h, f"{h}:grocery", GROCERY_D])
        d = hardware[h]
        if d is not None:
            con.execute(
                "INSERT INTO analysis.hex_poi_distance (h3_index, poi_id, category, network_m) "
                "VALUES (?, ?, 'hardware', ?)", [h, f"{h}:hardware", d])


def _fresh_con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _missing_set(rows, category: str) -> set[str]:
    """Hex ids for which `category` appears in missing_expected."""
    return {h for h, *_rest, missing in rows if category in missing.split(",")}


def test_window_rule_violates_monotonicity():
    """Adding one hardware store far from H0 flips H0 from not-missing to
    missing, with H0's own surroundings unchanged. This is the exact mechanism
    behind CHECKPOINT D31's Manhattan 10-vs-5-minute category-mix flip: the
    `expected` prevalence bar is a citywide aggregate, not a per-hex fact."""
    con = _fresh_con()
    # H0 = target, never has hardware. H1..H8 have hardware (8/11 = 0.727 <
    # 0.80 -> not "expected" yet). H9, H10 lack hardware.
    hardware = {"H0": None, **{f"H{i}": 200.0 for i in range(1, 9)},
                "H9": None, "H10": None}
    _seed(con, hardware)

    before, prevalence_before = compute_gaps(con, threshold=10, min_present=1,
                                             expected=0.80, min_pop=0, rule="window")
    assert prevalence_before["hardware"] < 0.80
    assert "H0" not in _missing_set(before, "hardware")   # not a gap yet

    # Add ONE hardware store at H9 — nowhere near H0.
    con.execute(
        "INSERT INTO analysis.hex_poi_distance (h3_index, poi_id, category, network_m) "
        "VALUES ('H9', 'H9:hardware2', 'hardware', 200.0)")

    after, prevalence_after = compute_gaps(con, threshold=10, min_present=1,
                                           expected=0.80, min_pop=0, rule="window")
    assert prevalence_after["hardware"] >= 0.80   # 9/11 = 0.818, crossed the bar
    # H0 is unchanged on the ground -- still no hardware nearby -- yet a
    # business added elsewhere turned it INTO a gap. This is the violation.
    assert "H0" in _missing_set(after, "hardware")


def test_reach_rule_no_spurious_flip_from_a_distant_addition():
    """Same fixture, `rule="reach"`: H0's own nearest-hardware distance never
    changes, so adding hardware at H9 must not affect whether H0 is missing."""
    con = _fresh_con()
    hardware = {"H0": None, **{f"H{i}": 200.0 for i in range(1, 9)},
                "H9": None, "H10": None}
    _seed(con, hardware)
    reach = _full_reach(grocery=1000.0, hardware=500.0)

    before, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach", reach=reach)
    assert "H0" in _missing_set(before, "hardware")

    con.execute(
        "INSERT INTO analysis.hex_poi_distance (h3_index, poi_id, category, network_m) "
        "VALUES ('H9', 'H9:hardware2', 'hardware', 200.0)")

    after, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach", reach=reach)
    assert "H0" in _missing_set(after, "hardware")   # unchanged -- correctly still a gap
    # And H9 itself, which gained a store, must flip the RIGHT way: missing -> not missing.
    assert "H9" not in _missing_set(after, "hardware")


def test_reach_rule_adding_business_never_creates_a_new_gap():
    """General direction check: for every hex, going from `before` to `after`
    (one POI added), a hex that was NOT missing hardware must still not be
    missing hardware. (The converse -- missing -> not-missing -- is allowed
    and expected, as H9 demonstrates above.)"""
    con = _fresh_con()
    hardware = {"H0": None, **{f"H{i}": 200.0 for i in range(1, 9)},
                "H9": None, "H10": None}
    _seed(con, hardware)
    reach = _full_reach(grocery=1000.0, hardware=500.0)

    before, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach", reach=reach)
    before_missing = _missing_set(before, "hardware")

    con.execute(
        "INSERT INTO analysis.hex_poi_distance (h3_index, poi_id, category, network_m) "
        "VALUES ('H9', 'H9:hardware2', 'hardware', 200.0)")
    after, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach", reach=reach)
    after_missing = _missing_set(after, "hardware")

    not_missing_before = {f"H{i}" for i in range(11)} - before_missing
    assert not_missing_before.isdisjoint(after_missing), (
        "a hex that was not missing hardware became missing after a business was ADDED"
    )


def test_reach_rule_lowering_reach_only_grows_the_missing_set():
    """Tightening reach(hardware) may only add hexes to the missing set, never
    remove any -- the second half of the acceptance test in CHECKPOINT D33."""
    con = _fresh_con()
    hardware = {"H0": None, **{f"H{i}": 200.0 for i in range(1, 9)},
                "H9": None, "H10": None}
    _seed(con, hardware)

    loose, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach",
                            reach=_full_reach(grocery=1000.0, hardware=500.0))
    tight, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach",
                            reach=_full_reach(grocery=1000.0, hardware=100.0))

    loose_missing = _missing_set(loose, "hardware")
    tight_missing = _missing_set(tight, "hardware")
    assert loose_missing <= tight_missing
    # And the tightening actually bit: H1..H8 were at 200m, present at reach=500,
    # missing at reach=100.
    assert tight_missing - loose_missing == {f"H{i}" for i in range(1, 9)}


def test_reach_rule_lowering_reach_never_creates_a_new_present_hex():
    """Direct converse phrasing of the same property: nothing exits the
    missing set as reach tightens."""
    con = _fresh_con()
    hardware = {"H0": None, **{f"H{i}": 200.0 for i in range(1, 9)},
                "H9": None, "H10": None}
    _seed(con, hardware)

    reach_values = [500.0, 300.0, 200.0, 100.0, 50.0]
    missing_sets = []
    for r in reach_values:
        rows, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach",
                               reach=_full_reach(grocery=1000.0, hardware=r))
        missing_sets.append(_missing_set(rows, "hardware"))
    for looser, tighter in zip(missing_sets, missing_sets[1:]):
        assert looser <= tighter


def test_eligible_universe_matches_between_rules():
    """Defect review item 1: the walkability gate must be the SAME test (the
    window rule's own presence-within-800m definition) for both rules, so
    they screen the same population even though they can disagree on which
    of those hexes are missing something.

    Fixture: H0 has grocery (50m) and hardware within the WINDOW (200m <
    800m default), but reach(hardware) is set tighter than the window
    (100m). Before this fix the reach rule gated on reach-based presence, so
    H0 would count only 1 category present (grocery; hardware fails its own
    100m reach) and fail a min_present=2 gate -- vanishing from the reach
    rule's universe even though the window rule accepts it (its 200m
    hardware clears the 800m window, independent of reach). After the fix
    both rules gate on the window definition, so H0 is eligible under both,
    and the reach rule still correctly flags hardware as missing."""
    con = _fresh_con()
    _seed(con, {"H0": 200.0})   # grocery @ 50m, hardware @ 200m -- both within the 800m window
    reach = _full_reach(grocery=1000.0, hardware=100.0)   # reach(hardware) tighter than the window

    universe = _eligible_universe(con, threshold=10, min_present=2, min_pop=0)
    reach_rows, _ = compute_gaps(con, threshold=10, min_present=2, min_pop=0,
                                 rule="reach", reach=reach)
    reach_ids = {h for h, *_rest in reach_rows}

    assert len(universe) == 1 and "H0" in universe   # H0 clears the window gate
    assert "H0" in reach_ids                          # ... and the reach rule sees it too
    assert "H0" in _missing_set(reach_rows, "hardware")   # correctly: 200m > reach 100m


def test_reach_rule_fails_closed_on_incomplete_reach_table():
    """Defect review item 2: a category missing from the reach dict must
    raise, not silently default to 'always present' (the old
    `reach.get(c, math.inf)`)."""
    con = _fresh_con()
    _seed(con, {"H0": 200.0})
    incomplete = {"grocery": 1000.0, "hardware": 500.0}   # missing 13 categories
    try:
        compute_gaps(con, min_present=1, min_pop=0, rule="reach", reach=incomplete)
    except ValueError as e:
        assert "hardware" not in str(e)   # hardware IS present; must not be listed
        assert "grocery" not in str(e)    # grocery IS present; must not be listed
        assert "restaurant" in str(e)     # a genuinely-absent category must be named
    else:
        raise AssertionError("expected ValueError for an incomplete reach table")


def test_reach_rule_missing_category_row_is_a_gap_not_a_drop():
    """Defect review item 3: a hex with NO row in hex_poi_distance for a
    category (nothing within the 30-minute cap) must be classified as
    missing that category (distance treated as +inf) and must still appear
    in the output -- not silently dropped from the reach classification."""
    con = _fresh_con()
    # H0 has grocery (clears the gate) but literally no hardware row at all.
    _seed(con, {"H0": None})
    reach = _full_reach(grocery=1000.0, hardware=500.0)

    rows, _ = compute_gaps(con, min_present=1, min_pop=0, rule="reach", reach=reach)

    ids = {h for h, *_rest in rows}
    assert "H0" in ids, "hex with no hardware row vanished instead of being a gap"
    assert "H0" in _missing_set(rows, "hardware")
    assert "H0" not in _missing_set(rows, "grocery")   # grocery IS present, must not be missing
