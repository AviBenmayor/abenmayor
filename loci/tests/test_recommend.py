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

import pytest

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.model import recommend as rec

RULES = rec.load_rules()


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

def test_coverage_ladder():
    assert rec.grade_coverage({"validation_rows": 4, "anchor_qualifies": False}, RULES)[0] == "A"
    assert rec.grade_coverage({"validation_rows": 0, "anchor_qualifies": True,
                               "anchor_coverage": 1.42}, RULES)[0] == "B"
    g, why = rec.grade_coverage({"validation_rows": 0, "anchor_qualifies": False}, RULES)
    assert g == "C" and "coverage hole" in why


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
                           "anchor_sources": "test", "validation_rows": 0}
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
    assert sec["coverage"]["grade"] == "B"             # anchor qualifies
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
