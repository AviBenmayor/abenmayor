"""The recommendation card (model/recommend.py): the grading boundaries, the
D72 ruling that "act" is unreachable with a load-bearing D, the supply-hash
drift policy, and one end-to-end pass over a synthetic warehouse.

The load-bearing test here is `test_act_is_unreachable_with_any_load_bearing_d`.
Everything else checks arithmetic a reader can verify by eye; what a reader
CANNOT verify by eye is that no combination of seven grades slips past the
ruling, so that one is brute-forced over all 4**7 combinations rather than
argued in a docstring.
"""
from __future__ import annotations

import itertools
import pathlib

import pytest

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.model import recommend as rec

RULES = rec.load_rules()
WAREHOUSE = pathlib.Path(locidb.DEFAULT_PATH)


def _live():
    """The real warehouse, read-only, or a skip.

    A concurrent writer is the normal state of this project (D69/D72), and
    `connect_read_only` is the module's own answer to it -- but a test may not
    block a suite for two minutes waiting on another session's rebuild, so the
    retry budget is short and a still-locked file skips rather than fails."""
    try:
        return rec.connect_read_only(WAREHOUSE, retries=2, wait_s=3.0)
    except Exception as exc:                      # noqa: BLE001 -- duckdb raises several
        pytest.skip(f"warehouse is locked by a concurrent writer: {exc}")


def _cov(holes: int, n: int) -> dict:
    """The four coverage facts `grade_coverage` reads, from raw counts."""
    return {"coverage_n_holes": holes, "coverage_n_missing": n,
            "coverage_hole_rate": (holes / n) if n else None,
            "coverage_hole_hi95": rec.wilson_upper(holes, n)}


# ------------------------------------------------------- 0. the rule file

def test_rules_name_exactly_the_seven_sections():
    """A section named in the YAML but not in the code (or the reverse) would
    silently grade nothing, or grade something the owner cannot adjust."""
    assert set(RULES["load_bearing"]) | set(RULES["context"]) == set(rec.SECTION_ORDER)
    assert not set(RULES["load_bearing"]) & set(RULES["context"])
    assert set(RULES["load_bearing"]) == {"arriving_homes", "supply_thinness",
                                          "addressable_demand", "economics", "coverage"}
    # every load-bearing section has a cheapest check to print when it grades D
    assert set(RULES["cheapest_check"]) >= set(RULES["load_bearing"])


def test_worst_is_worst_and_rejects_a_typo():
    assert rec.worst("A", "C", "B") == "C"
    assert rec.worst("A", "A") == "A"
    assert rec.cap("A", "C") == "C"
    assert rec.cap("D", "C") == "D", "a cap may not IMPROVE a grade"
    with pytest.raises(ValueError):
        rec.worst("A", "E")


# ------------------------------------------------------- 1. the D72 ruling

def _sections(grades: dict) -> list[rec.Section]:
    lb = set(RULES["load_bearing"])
    return [rec.Section(key=k, title=rec.SECTION_TITLES[k], grade=grades[k],
                        reason="", facts={}, load_bearing=k in lb)
            for k in rec.SECTION_ORDER]


def test_act_is_unreachable_with_any_load_bearing_d():
    """THE RULING (D72). Brute-force every combination of seven grades: if any
    load-bearing section is D, the verdict must be "do not act on this data",
    and the D sections must be listed as what would change it."""
    for combo in itertools.product(rec.GRADES, repeat=len(rec.SECTION_ORDER)):
        grades = dict(zip(rec.SECTION_ORDER, combo))
        v = rec.verdict_for(_sections(grades), RULES)
        has_d = any(grades[k] == "D" for k in RULES["load_bearing"])
        if has_d:
            assert v["verdict"] == "do not act on this data", grades
            assert v["overall_grade"] == "D"
            assert {b["section"] for b in v["blockers"]} == \
                {k for k in RULES["load_bearing"] if grades[k] == "D"}
            assert all(b["cheapest_check"] for b in v["blockers"])
        else:
            assert v["verdict"] != "do not act on this data", grades


def test_a_context_section_can_never_move_the_verdict():
    """Sections 1 and 5 describe the site; they are not evidence for acting."""
    good = dict.fromkeys(rec.SECTION_ORDER, "A")
    base = rec.verdict_for(_sections(good), RULES)
    for ctx in RULES["context"]:
        worse = {**good, ctx: "D"}
        assert rec.verdict_for(_sections(worse), RULES) == base


def test_verdict_bands():
    g = dict.fromkeys(rec.SECTION_ORDER, "A")
    assert rec.verdict_for(_sections(g), RULES)["verdict"] == "act"
    assert rec.verdict_for(_sections({**g, "coverage": "B"}), RULES)["verdict"] == "act"
    assert rec.verdict_for(_sections({**g, "coverage": "C"}), RULES)["verdict"] == "diligence"


# --------------------------------------------------- 2. arriving homes (§2)

def _arriving(ex_share, med_share, permitted=1000.0):
    return {"units_permitted_sum": permitted,
            "units_active_sum": permitted * ex_share,
            "units_stalled_sum": 0.0,
            "active_share_median": med_share}


@pytest.mark.parametrize("share, expected", [
    (0.70, "B"), (0.7001, "B"), (0.6999, "C"), (0.40, "C"), (0.3999, "D"), (0.0, "D"),
])
def test_arriving_homes_boundaries(share, expected):
    """>=70% active is B, 40-70% is C, under 40% is D. Both shares agree here
    so the disagreement rule does not fire."""
    g, _ = rec.grade_arriving_homes(_arriving(share, share), RULES)
    assert g == expected


def test_arriving_homes_takes_the_worse_band_when_the_two_shares_disagree():
    """The real Gowanus case: 72% of permitted units active by exposure but the
    median address sees 50%, because the activity sits in a few big catchments.
    The card may not quote the flattering one."""
    g, why = rec.grade_arriving_homes(_arriving(0.72, 0.50), RULES)
    assert g == "C"
    assert "concentrated" in why and "72%" in why and "50%" in why


def test_arriving_homes_null_evidence_is_d_not_zero():
    """D72: `activity_status` is n/a, never `stalled`, when no permit row
    matched. NULL is not news of absence, and it is not a passing grade."""
    g, why = rec.grade_arriving_homes(
        {"units_permitted_sum": None, "units_active_sum": None}, RULES)
    assert g == "D" and "NULL is not zero" in why


# -------------------------------------------------- 3. supply thinness (§3)

def _supply(n, mismatch=False, supply_set="principled"):
    return {"ratio_median": 0.3, "n_ratio_addresses": n, "supply_set": supply_set,
            "live_hash": "aaaaaaaaaaaa", "baseline_hash": "bbbbbbbbbbbb" if mismatch
            else "aaaaaaaaaaaa", "hash_mismatch": mismatch}


@pytest.mark.parametrize("n, expected", [(200, "A"), (199, "B"), (50, "B"), (49, "C"), (1, "C")])
def test_supply_thinness_sample_size_boundaries(n, expected):
    assert rec.grade_supply_thinness(_supply(n), RULES)[0] == expected


def test_supply_thinness_on_the_wrong_universe_is_c():
    """D72 finding 1: the counts the owner was shown were `in_all`, not
    principled. A ratio on the wrong set is a C however many addresses back it."""
    assert rec.grade_supply_thinness(_supply(5000, supply_set="all"), RULES)[0] == "C"


def test_supply_thinness_with_no_ratio_at_all_is_d():
    g, why = rec.grade_supply_thinness({"ratio_median": None, "n_ratio_addresses": 0}, RULES)
    assert g == "D" and "supply-ratio" in why


# ---- the drift policy, argued and pinned

def test_hash_drift_caps_section_3_at_c_and_does_not_refuse_the_card():
    """DECISION, pinned: a baseline/live supply-hash mismatch WARNS and caps
    section 3 at C. It does NOT refuse the card.

    Why cap rather than refuse: the other six sections do not read the supply
    view at all, so refusing would discard six sound readings to punish one
    stale one, and a concurrent warehouse rebuild is the normal state of this
    project (D69/D72 both landed against one). Capping is not the soft option:
    section 3 is load-bearing, so a C there already makes "act" unreachable and
    forces the card to "diligence" at best -- the safety property the ruling
    asks for is preserved without making the tool unusable mid-rebuild.
    """
    g, why = rec.grade_supply_thinness(_supply(5000, mismatch=True), RULES)
    assert g == "C", "an A-sized sample on a drifted baseline is still only C"
    assert "not comparable" in why and "bbbbbbbbbbbb" in why and "aaaaaaaaaaaa" in why
    # and the cap can never IMPROVE a worse grade
    assert rec.grade_supply_thinness(
        {**_supply(0, mismatch=True), "ratio_median": None}, RULES)[0] == "D"
    # the ruling still bites: C at a load-bearing section cannot be "act"
    grades = dict.fromkeys(rec.SECTION_ORDER, "A") | {"supply_thinness": "C"}
    assert rec.verdict_for(_sections(grades), RULES)["verdict"] == "diligence"


# ----------------------------------------------- 4. addressable demand (§4)

def test_laundry_haircut_is_b_on_priors_and_a_only_on_evidence():
    b, why = rec.grade_addressable_demand("laundry", {"evidence_coverage": 0.50,
                                                      "haircut_version": 1}, RULES)
    assert b == "B", "exactly 50% coverage is not yet A (the rule is strictly greater)"
    assert "PRIORS" in why
    a, _ = rec.grade_addressable_demand("laundry", {"evidence_coverage": 0.5001}, RULES)
    assert a == "A"


def test_every_other_category_is_c_because_the_pool_is_undiscounted():
    """D72 finding 3 applies to all fifteen; only laundry has a haircut built."""
    for cat in CATEGORIES:
        g, why = rec.grade_addressable_demand(cat, {"homes_400m_median": 3000}, RULES)
        if cat == "laundry":
            continue
        assert g == "C", cat
        assert "no category-specific haircut yet" in why


# ---------------------------------------------------------- 5. space (§5)

def test_space_is_b_with_a_registry_and_d_when_nobody_filed():
    assert rec.grade_space({"storefronts_median": 43.0, "storefront_asof": "2024-12-31"},
                           RULES)[0] == "B"
    g, why = rec.grade_space({"storefronts_median": 0.0}, RULES)
    assert g == "D" and "nobody filed" in why


# ------------------------------------------------------ 6. economics (§6)

def _comps(n, level, cash=True):
    return {"n_comps": n, "level_used": level, "geo_value": "x",
            "cash_flow_p50": 90_000.0 if cash else None, "rent_source": "listed"}


@pytest.mark.parametrize("n, level, expected", [
    (5, "neighborhood", "A"), (9, "neighborhood", "A"),
    (5, "borough", "B"), (5, "citywide", "C"),
    (4, "neighborhood", "C"), (1, "borough", "C"), (0, "citywide", "D"),
])
def test_economics_boundaries(n, level, expected):
    assert rec.grade_economics(_comps(n, level), RULES)[0] == expected


def test_economics_without_cash_flow_is_d_however_many_comps():
    """The current state everywhere: listings exist without a cash-flow figure,
    which is a price tag, not an income statement."""
    g, why = rec.grade_economics(_comps(50, "neighborhood", cash=False), RULES)
    assert g == "D" and "no cash-flow data" in why


# ------------------------------------------------------- 7. coverage (§7)
# The G9 ladder (owner ruling 2026-09-14, docs/coverage-validation-2026-09.md
# §9(2)). Pure arithmetic on synthetic counts here; the live per-category grade
# table is pinned against the warehouse at the bottom of this file.

def test_wilson_upper_matches_the_published_intervals():
    """The four intervals printed in docs/coverage-validation-2026-09.md §4,
    to 0.1 pp. If this drifts, the memo and the card disagree about the same
    rows -- which is the failure the grade exists to prevent."""
    assert rec.wilson_upper(24, 200) == pytest.approx(0.172, abs=0.0005)   # hardware
    assert rec.wilson_upper(75, 200) == pytest.approx(0.444, abs=0.0005)   # tailor_repair
    assert rec.wilson_upper(64, 180) == pytest.approx(0.428, abs=0.0005)   # fitness, as asked
    assert rec.wilson_upper(1, 180) == pytest.approx(0.031, abs=0.0005)    # fitness, on-type
    assert rec.wilson_upper(5, 0) is None


def test_wilson_and_not_wald_at_zero_holes():
    """0/251 (convenience) must NOT promise a perfectly-seen category: Wald
    would hand back the single point 0.0 and grade A on an interval of width
    zero. Wilson keeps a real upper bound, which still clears A here."""
    hi = rec.wilson_upper(0, 251)
    assert 0.0 < hi < 0.02
    assert rec.grade_coverage(_cov(0, 251), RULES)[0] == "A"
    # ... and the same zero on a tiny sample must NOT reach A
    assert rec.wilson_upper(0, 20) > RULES["sections"]["coverage"]["hole_rate_hi95_a"]
    assert rec.grade_coverage(_cov(0, 20), RULES)[0] == "B"


def test_coverage_ladder_is_the_upper_bound_not_the_point_estimate():
    r = RULES["sections"]["coverage"]
    a, why = rec.grade_coverage(_cov(2, 200), RULES)       # 1.0%, hi95 3.6%
    assert a == "A" and "Wilson 95% upper bound" in why and "2/200" in why
    assert rec.grade_coverage(_cov(24, 200), RULES)[0] == "B"    # 12.0%, hi95 17.2%
    assert rec.grade_coverage(_cov(75, 200), RULES)[0] == "C"    # 37.5%, hi95 44.4%
    # THE POINT OF THE BOUND: a point estimate under 10% that a small sample
    # cannot support is a B, not an A.
    assert (8 / 144) < r["hole_rate_hi95_a"]
    assert rec.grade_coverage(_cov(8, 144), RULES)[0] == "B"     # grocery, hi95 10.6%


def test_a_category_with_no_validation_rows_is_c_unvalidated():
    """clinic: no Google primary type isolates 621111/621493 (D30), so it has
    no rows at all. Absence of a measurement may never read as a good one."""
    g, why = rec.grade_coverage(_cov(0, 0), RULES)
    assert g == "C" and "UNVALIDATED" in why
    assert rec.grade_coverage({}, RULES)[0] == "C"


def test_the_ladder_lives_in_exactly_one_place():
    """The thresholds are owner-adjustable YAML, not literals in the grader."""
    r = RULES["sections"]["coverage"]
    assert (r["hole_rate_hi95_a"], r["hole_rate_hi95_b"]) == (0.10, 0.25)
    assert r["unvalidated_grade"] == "C"
    src = (pathlib.Path(rec.__file__)).read_text()
    assert "0.10" not in src.split("def grade_coverage")[1].split("def ")[0]


# --------------------------------------- headline demotion (ruling 1, D30)

def test_the_four_demoted_categories_are_the_ruled_set():
    # bathhouse_sauna added by owner ruling 2026-09-17 (GTM-198): admitted as a
    # non-filtering signal, headline: false from the day it landed.
    assert rec.non_headline_categories() == frozenset(
        {"clinic", "tailor_repair", "hair_barber", "bathhouse_sauna"})


def test_a_demoted_category_can_never_lead_a_card():
    """THE RULING. tailor_repair is given the thinnest ratio in the area -- the
    one thing that otherwise puts a category first -- and must still not lead."""
    facts = {"categories": {c: {"ratio_median": 1.5} for c in CATEGORIES}}
    facts["categories"]["tailor_repair"]["ratio_median"] = 0.01
    facts["categories"]["hair_barber"]["ratio_median"] = 0.02
    facts["categories"]["clinic"]["ratio_median"] = 0.03
    facts["categories"]["bathhouse_sauna"]["ratio_median"] = 0.04   # demoted 2026-09-17
    ranked = rec.rank_categories(facts)
    assert ranked[0] not in rec.non_headline_categories()
    assert set(ranked[-4:]) == rec.non_headline_categories(), \
        "demoted categories sort behind every headline category, whatever the ratio"
    assert len(ranked) == len(CATEGORIES), "demotion drops nothing from the run"
    # and it holds when the caller asks for a subset that is ONLY demoted
    # categories plus one headline one
    assert rec.rank_categories(facts, ["tailor_repair", "bank"])[0] == "bank"


def test_a_demoted_category_still_gets_a_full_card_and_says_why():
    facts = _synthetic_facts()
    card = rec.build_card("tailor_repair", facts, _comps(0, "borough", cash=False), RULES)
    assert card["headline"] is False
    assert len(card["sections"]) == len(rec.SECTION_ORDER)
    md = rec.render_card(card, RULES)
    assert "Not a headline category" in md
    assert "may not LEAD" in md
    ok = rec.build_card("bank", facts, _comps(0, "borough", cash=False), RULES)
    assert ok["headline"] is True
    assert "Not a headline category" not in rec.render_card(ok, RULES)


# -------------------------------------------------- ranking and rendering

def test_categories_rank_by_thinnest_ratio_and_unmeasured_sorts_last():
    facts = {"categories": {c: {"ratio_median": None} for c in CATEGORIES}}
    facts["categories"]["pharmacy"]["ratio_median"] = 0.07
    facts["categories"]["laundry"]["ratio_median"] = 0.28
    facts["categories"]["bar"]["ratio_median"] = 1.12
    ranked = rec.rank_categories(facts)
    assert ranked[:3] == ["pharmacy", "laundry", "bar"]
    assert len(ranked) == len(CATEGORIES)


def test_the_card_never_emits_an_expected_profit():
    """A supportable rent is a ceiling; a profit would need a cost structure
    Loci has never seen."""
    facts = _synthetic_facts()
    card = rec.build_card("laundry", facts, _comps(9, "neighborhood"), RULES)
    md = rec.render_card(card, RULES)
    econ = next(s for s in card["sections"] if s["key"] == "economics")
    assert "supportable_rent" in econ["facts"]
    assert not any("profit" in k for k in econ["facts"])
    assert "No expected profit is emitted" in md
    assert "supportable rent" in md.lower()


# --------------------------------------------- synthetic warehouse, e2e

def _synthetic_facts() -> dict:
    return {
        "area": "Test box", "bbox": [0, 0, 1, 1], "nta": None, "boroughs": ["BK"],
        "address_boroughs": ["BK"], "neighborhoods": ["Testville"], "n_addresses": 300,
        "asof": "2026-09-11", "homes_400m_median": 3000.0,
        "median_hh_income": 100_000.0, "median_hh_income_moe": 10_000.0,
        "reference_median_hh_income": 90_000.0, "age_18_34_share": 0.25,
        "renter_share": 0.6, "units_permitted_sum": 1000.0, "units_active_sum": 800.0,
        "units_stalled_sum": 100.0, "units_other_sum": 100.0,
        "units_permitted_median": 50.0, "active_share_median": 0.8,
        "supply_set": "principled", "live_hash": "aaaaaaaaaaaa",
        "baseline_hash": "aaaaaaaaaaaa", "hash_mismatch": False,
        "addressable_homes_median": 1200.0, "addressable_share": 0.4,
        "evidence_coverage": 0.03, "haircut_version": 1,
        "share_with_vacant": 0.8, "vacant_storefronts_median": 2.0,
        "storefronts_median": 43.0, "storefront_asof": "2024-12-31",
        "categories": {c: {"ratio_median": 0.3, "per_1k_median": 0.4,
                           "supply_400m_median": 4.0, "n_ratio_addresses": 300,
                           "baseline_per_1k": 1.2, "regime": "saturating",
                           "anchor_qualifies": True, "anchor_coverage": 1.4,
                           "anchor_sources": "test", **_cov(3, 200)}
                       for c in CATEGORIES},
    }


def _synthetic_db():
    """A warehouse with exactly the six tables `area_facts` reads, populated
    with 120 addresses in one box -- enough to exercise the medians, the
    catchment sums and the per-category join without a 2 GB file."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    rows = []
    for i in range(120):
        rows.append((f"a{i}", f"300000{i:04d}", -73.99 + 0.0001 * i, 40.675,
                     "BK", "Testville", "BK0601", True, 12, 3, "tiers", "h", "g",
                     "2026-09-11",
                     3000.0 + i, 1200.0 + i, 100.0, 80.0, 10.0, 2.0, 43.0,
                     "2024-12-31", "767b28674e30"))
    con.executemany(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, neighborhood, "
        "nta_code, eligible, present_count, n_missing, reach_source, reach_hash, "
        "graph_version, run_at, homes_400m, addressable_homes_400m_laundry, "
        "units_permitted_400m, units_active_400m, units_stalled_400m, "
        "vacant_storefronts_400m, storefronts_400m, storefront_asof, "
        "supply_ratio_supply_hash) VALUES (" + ",".join("?" * 23) + ")", rows)
    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, eligible, "
        "supply_400m, supply_per_1k, supply_ratio_vs_base) VALUES (?,?,?,?,?,?,?)",
        [(f"a{i}", "BK", c, True, 4.0, 0.4, 0.3)
         for i in range(120) for c in CATEGORIES])
    con.executemany(
        "INSERT INTO analysis.address_demographics (address_id, bbl, acs_year, "
        "median_hh_income, median_hh_income_moe, age_18_34_share, renter_share) "
        "VALUES (?,?,?,?,?,?,?)",
        [(f"a{i}", f"300000{i:04d}", 2023, 100_000.0, 10_000.0, 0.25, 0.6)
         for i in range(120)])
    con.executemany(
        "INSERT INTO analysis.category_anchor (category, anchor_sources, anchor_coverage, "
        "threshold, qualifies, run_at) VALUES (?,?,?,?,?,now())",
        [(c, "test_registry", 1.4, 0.8, c == "laundry") for c in CATEGORIES])
    con.execute("INSERT INTO analysis.address_laundry_evidence (bbl, source, built_at) "
                "VALUES ('3000000000', 'll84', now())")
    return con


def test_street_frame_rows_never_enter_an_area_aggregate(monkeypatch):
    """D84. Every number `area_facts` produces is a median or a share over "the
    area's addresses". A street midpoint has ZERO homes and no tax lot, and an
    industrial box holds roughly as many street points as lots -- so admitting
    them would halve the median homes_400m of exactly the areas this card is
    most often asked about and drag every share toward the street network's
    geometry. The pin lives in ONE fragment (`base`) that every section's query
    reuses, so it cannot be applied to five queries out of six.

    The street rows here are deliberately ADVERSARIAL: same box, homes_400m 0,
    supply_ratio_vs_base 9.0, no vacancy. If they leaked in, every assertion
    below would move."""
    from loci.model import supply_ratio as sr

    con = _synthetic_db()
    monkeypatch.setattr("loci.score.supply.supply_hash",
                        lambda c, s="principled": sr.load_baselines()["supply_hash"])
    before = rec.area_facts(con, "Test box", bbox=(40.67, -74.0, 40.68, -73.95),
                            boroughs=("BK",))

    street = [(f"seg:{i}:0", None, -73.99 + 0.0001 * i, 40.675, "BK", "Testville",
               "BK0601", True, 12, 3, "tiers", "h", "g", "2026-09-11",
               0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "2024-12-31", "767b28674e30",
               "street")
              for i in range(120)]
    con.executemany(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, neighborhood, "
        "nta_code, eligible, present_count, n_missing, reach_source, reach_hash, "
        "graph_version, run_at, homes_400m, addressable_homes_400m_laundry, "
        "units_permitted_400m, units_active_400m, units_stalled_400m, "
        "vacant_storefronts_400m, storefronts_400m, storefront_asof, "
        "supply_ratio_supply_hash, frame) VALUES (" + ",".join("?" * 24) + ")", street)
    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, eligible, "
        "supply_400m, supply_per_1k, supply_ratio_vs_base, frame) VALUES (?,?,?,?,?,?,?,?)",
        [(f"seg:{i}:0", "BK", c, True, 0.0, 9.0, 9.0, "street")
         for i in range(120) for c in CATEGORIES])

    after = rec.area_facts(con, "Test box", bbox=(40.67, -74.0, 40.68, -73.95),
                           boroughs=("BK",))
    assert after["n_addresses"] == before["n_addresses"] == 120
    assert after["homes_400m_median"] == before["homes_400m_median"]
    assert after["units_permitted_sum"] == before["units_permitted_sum"]
    assert after["share_with_vacant"] == before["share_with_vacant"]
    for cat in ("laundry", "grocery"):
        assert after["categories"][cat]["ratio_median"] == \
            before["categories"][cat]["ratio_median"]
        assert after["categories"][cat]["n_ratio_addresses"] == \
            before["categories"][cat]["n_ratio_addresses"] == 120


def test_end_to_end_on_a_synthetic_warehouse(monkeypatch):
    con = _synthetic_db()
    # pin the live hash to the committed baseline's so the drift path is OFF
    # here; it has its own test above.
    from loci.model import supply_ratio as sr
    monkeypatch.setattr("loci.score.supply.supply_hash",
                        lambda c, s="principled": sr.load_baselines()["supply_hash"])

    facts = rec.area_facts(con, "Test box", bbox=(40.67, -74.0, 40.68, -73.95),
                           boroughs=("BK",))
    assert facts["n_addresses"] == 120
    assert facts["neighborhoods"] == ["Testville"]
    assert facts["address_boroughs"] == ["BK"]
    assert facts["hash_mismatch"] is False
    # catchment sums, not a unit count: 120 addresses x 100 permitted units
    assert facts["units_permitted_sum"] == pytest.approx(12_000.0)
    assert facts["units_active_sum"] == pytest.approx(9_600.0)
    assert facts["active_share_median"] == pytest.approx(0.8)
    assert facts["share_with_vacant"] == pytest.approx(1.0)
    assert facts["categories"]["laundry"]["n_ratio_addresses"] == 120
    assert facts["categories"]["laundry"]["anchor_qualifies"] is True
    assert facts["categories"]["grocery"]["anchor_qualifies"] is False

    cards = rec.build_cards(facts, RULES, ["laundry", "grocery"])
    assert [c["category"] for c in cards] == ["grocery", "laundry"] or \
           [c["category"] for c in cards] == ["laundry", "grocery"]
    by_cat = {c["category"]: c for c in cards}
    sec = {s["key"]: s for s in by_cat["laundry"]["sections"]}
    assert sec["arriving_homes"]["grade"] == "B"       # 80% active, both shares
    assert sec["supply_thinness"]["grade"] == "B"      # principled set, but n = 120 < 200
    assert sec["addressable_demand"]["grade"] == "B"   # laundry priors
    # G9: this synthetic warehouse has no coverage_validation rows at all, so
    # every category is UNVALIDATED -- C, regardless of whether its anchor
    # qualifies. A qualifying anchor is no longer a coverage grade (the old
    # rule graded this B on laundry's anchor alone).
    assert sec["coverage"]["grade"] == "C"
    assert "UNVALIDATED" in sec["coverage"]["reason"]
    assert facts["categories"]["laundry"]["coverage_n_missing"] == 0
    assert {s["key"]: s["grade"] for s in by_cat["grocery"]["sections"]}["coverage"] == "C"
    # economics is D everywhere today -> every verdict is "do not act"
    assert sec["economics"]["grade"] == "D"
    assert by_cat["laundry"]["verdict"] == "do not act on this data"
    assert [b["section"] for b in by_cat["laundry"]["blockers"]] == ["economics"]

    md = rec.render_markdown(cards, facts, RULES)
    assert "# Recommendation card — Test box" in md
    assert "What would change the verdict" in md
    assert "3-5 P&Ls" in md
    js = rec.to_json(cards, facts, RULES)
    assert js["area"]["n_addresses"] == 120
    assert len(js["summary"]) == len(js["cards"]) == 2


def test_an_empty_area_raises_rather_than_rendering_an_empty_card():
    con = _synthetic_db()
    with pytest.raises(ValueError, match="no eligible addresses"):
        rec.area_facts(con, "Nowhere", bbox=(1.0, 1.0, 2.0, 2.0), boroughs=("BK",))


def test_an_area_needs_a_bbox_or_an_nta():
    with pytest.raises(ValueError, match="--bbox or an --nta"):
        rec._area_predicate(None, None)


# ------------------------------------------- the real warehouse, if any
# The G9 grade table as it stands on today's coverage_validation rows. This is
# the test that would catch a silent regrade -- a type-map edit, a re-run of
# the screen that moves the missing arm, or a threshold nudge -- because every
# other test here runs on counts someone typed.

WAREHOUSE_GRADES = {
    "convenience": "A", "fitness": "A", "restaurant": "A", "bar": "A",
    "cafe_bakery": "A", "laundry": "A", "nails_beauty": "A", "pharmacy": "A",
    "childcare": "A", "bank": "A",
    "grocery": "B", "hardware": "B",
    "hair_barber": "C", "tailor_repair": "C", "clinic": "C",
}


@pytest.mark.skipif(not WAREHOUSE.exists(), reason="no data/loci.duckdb on this clone")
def test_the_g9_grade_table_on_the_real_warehouse():
    """Owner ruling 2026-09-14 and docs/coverage-validation-2026-09.md §4.

    Three things are pinned at once: the ladder, the frame (address rows only,
    the 2,970 hex rows never pooled) and the ON-TYPE recount. Fitness is the
    load-bearing row: its stored rows were bought with `sports_club` in the
    type map and read 35.4% as requested, which is a C. The recount against the
    CURRENT GOOGLE_TYPES reads 0.6% and grades A off the same rows, with no new
    Google spend -- that is the whole mechanism of ruling 3.
    """
    con = _live()
    try:
        n_addr = con.execute(
            "SELECT count(*) FROM analysis.coverage_validation "
            "WHERE address_id IS NOT NULL").fetchone()[0]
        if not n_addr:
            pytest.skip("no address-frame coverage_validation rows on this warehouse")
        cov = rec.coverage_hole_rates(con)
    finally:
        con.close()

    graded = {c: rec.grade_coverage(cov[c], RULES)[0] for c in CATEGORIES}
    # GTM-198 G9 (owner 2026-09-17): bathhouse_sauna has no validation rows and
    # no qualifying anchor, so it grades C ("aggregators only") by construction
    # on this warehouse -- asserted separately so the fifteen-slug pin below
    # stays exact and a later B/A for the slug cannot land unnoticed.
    assert graded.pop("bathhouse_sauna") == "C"
    assert graded == WAREHOUSE_GRADES

    assert cov["clinic"]["coverage_n_missing"] == 0, "clinic has no Google type map (D30)"
    assert cov["fitness"]["coverage_n_holes"] <= 2, \
        "fitness's holes were sports_club/marina returns; on-type it is ~1 in 180"
    assert cov["fitness"]["coverage_hole_hi95"] < 0.10
    # the two demoted categories are the two worst-covered anchored ones, which
    # is the evidence ruling 1 rests on
    worst = sorted(CATEGORIES, key=lambda c: -(cov[c]["coverage_hole_rate"] or 0))[:2]
    assert set(worst) == {"hair_barber", "tailor_repair"}
    assert set(worst) <= rec.non_headline_categories()


@pytest.mark.skipif(not WAREHOUSE.exists(), reason="no data/loci.duckdb on this clone")
def test_the_hex_frame_is_never_pooled_into_a_coverage_grade():
    """D58's frame rule, as a test rather than a comment: the 2,970 pre-D38 hex
    rows were measured at a different unit, geometry and (pre-D53) radius. They
    exist on this warehouse, and the query must not see one of them."""
    con = _live()
    try:
        hex_rows = con.execute(
            "SELECT count(*) FROM analysis.coverage_validation "
            "WHERE h3_index IS NOT NULL").fetchone()[0]
        if not hex_rows:
            pytest.skip("this warehouse holds no legacy hex-frame rows")
        pulled = con.execute(
            f"SELECT count(*) FROM ({rec.COVERAGE_FRAME_SQL}) q").fetchone()[0]
        addr = con.execute(
            "SELECT count(*) FROM analysis.coverage_validation "
            "WHERE address_id IS NOT NULL").fetchone()[0]
    finally:
        con.close()
    assert pulled <= addr, "the frame query pulled more rows than the address frame holds"


@pytest.mark.skipif(not WAREHOUSE.exists(), reason="no data/loci.duckdb on this clone")
def test_the_present_arm_is_not_a_denominator():
    """The hole rate is over the MISSING arm only. Half the sample is the
    present-arm control (D58); pooling it would roughly halve every rate and
    hand tailor_repair an A."""
    con = _live()
    try:
        cov = rec.coverage_hole_rates(con)
        both_arms = con.execute(
            "SELECT count(*) FROM analysis.coverage_validation "
            "WHERE address_id IS NOT NULL AND category = 'tailor_repair'").fetchone()[0]
    finally:
        con.close()
    if not both_arms:
        pytest.skip("no tailor_repair address-frame rows on this warehouse")
    assert cov["tailor_repair"]["coverage_n_missing"] < both_arms


def test_on_type_recount_reads_the_stored_histogram_against_current_types():
    """Ruling 3's mechanism, in isolation. A stored row that returned only
    sports_club places is no longer an on-type hit for fitness, so the same
    row regrades without re-spending a Google call."""
    assert rec.on_type_count('{"sports_club": 3, "marina": 2}', "fitness") == 0
    assert rec.on_type_count('{"gym": 1, "sports_club": 3}', "fitness") == 1
    assert rec.on_type_count('{"nail_salon": 9, "hair_salon": 2}', "hair_barber") == 2
    # NULL / unparseable / a category with no type map read as zero on-type
    # places -- conservative: it can only make coverage look BETTER, never worse
    assert rec.on_type_count(None, "fitness") == 0
    assert rec.on_type_count(float("nan"), "fitness") == 0
    assert rec.on_type_count("{not json", "fitness") == 0
    assert rec.on_type_count('{"doctor": 4}', "clinic") == 0
