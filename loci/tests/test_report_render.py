"""AC-16: `loci.report.render`. Pure -- a hand-built `EvidencePack` +
`Enrichment`, no warehouse needed. Confirms the four fixed headings are
always present and non-empty, with or without prose.

Also covers the investor review's six generator changes (GTM-172,
2026-09-14/15), on the render side: item 1 (one falsification block from one
field), item 2 (the grade gate / no-trade note), item 3 (the underwriting
paragraph), item 4 (named vacant-storefront/pipeline/chains rows, raw POI
table moved to an appendix), and item 6 (special district, SLA 500-foot rule,
flood/environmental "not loaded", same-BBL conflicts in the provenance
footer).

2026-09-15 (GTM-183 regression fix): `test_cli_style_prose_reply_renders_...`
and `test_unparsed_prose_prints_the_honest_parse_failed_line_...` cover the
render side of the fix -- `PROSE_UNAVAILABLE` must appear ONLY when no prose
call was ever attempted, never when a call happened but its reply could not
be parsed (that gets `PROSE_PARSE_FAILED`, with the raw reply moved to the
provenance footer, never treated as narrative in the body)."""
from __future__ import annotations

import json

import loci.db as locidb
from loci.report.clients import FakeProse
from loci.report.enrich import Enrichment
from loci.report.evidence import (
    ChainWatchRow, EvidencePack, PipelineRow, POIRow, VacantStorefrontRow,
)
from loci.report.ledger import Budget
from loci.report.prose import ProseSections, write_prose
from loci.report.render import (
    GRADE_GATE_MIN, HEADINGS, PROSE_PARSE_FAILED, PROSE_UNAVAILABLE, is_below_c, out_path,
    render, slug,
)


def _pack(legality="commercial", *, grade="C", no_grades=False) -> EvidencePack:
    grades = [] if no_grades else [{
        "category": "grocery", "category_label": "Grocery / supermarket",
        "overall_grade": grade, "verdict": "wait for more evidence",
        "supply_ratio_vs_base": 0.4,
        "sections": [{"key": "coverage", "facts": {"coverage_hole_rate": 0.08}}]}]
    return EvidencePack(
        address={"address_id": "addr1", "bbl": "3012340001", "lat": 40.71, "lon": -73.95,
                 "street_name": "Test Street", "borough": "BK"},
        scores={"asof": "2026-09-14", "live_hash": "abc123"},
        grades=grades,
        forecast={"p_opening": 0.21, "issued_month": "2026-06", "horizon_months": 12,
                 "model_version": "0.1.1+deadbeef"},
        supply=[
            POIRow(poi_id="p1", name="Test Grocery", category="grocery", dist_m=50.0,
                  status="open", basis="nyc_dcwp_licenses:valid_to_2030-01-01",
                  colocation=None),
            POIRow(poi_id="p2", name="Closed Hardware", category="hardware", dist_m=100.0,
                  status="closed", basis="nyc_dcwp_licenses:out_of_business",
                  colocation=None),
            POIRow(poi_id="p3", name="Mystery Cafe", category="cafe_bakery", dist_m=150.0,
                  status="unknown", basis="overture_places:no_status_field",
                  colocation=None),
        ],
        demand={"homes_400m": 3000, "median_hh_income": 90000, "median_hh_income_moe": 8000,
               "renter_share": 0.65, "age_18_34_share": 0.3, "transit_entries_400m": 500,
               "jobs_400m": 800, "units_permitted_400m": 50,
               "units_completed_24mo_400m": 5, "revenue_p25": 400000, "revenue_p50": 600000,
               "revenue_p75": 900000, "rent_ceiling": 12000,
               "demand_caveat_text": "income below the MOE-confident cutoff (test)"},
        legality={"legality": legality, "legality_basis": "commercially zoned (C4-1)",
                  "zonedist1": "C4-1", "overlay1": None, "overlay2": None,
                  "landuse": "03", "ownertype": None, "histdist": None, "landmark": None,
                  "has_open_commercial_poi": True},
        context={"neighborhood": "Testville", "nta_code": "BK0601", "borough": "BK",
                 "catchment_m": 500.0},
        provenance={"asof": "2026-09-14", "supply_hash": "abc123"},
    )


def test_all_four_headings_are_present_and_non_empty_with_no_prose():
    pack = _pack()
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    for h in HEADINGS:
        assert h in md
        idx = md.index(h)
        nxt = min((md.index(h2) for h2 in HEADINGS if h2 != h and md.index(h2) > idx),
                 default=len(md))
        section = md[idx + len(h):nxt].strip()
        assert section, f"section {h!r} is empty"
    assert md.count(PROSE_UNAVAILABLE) == 4


def test_prose_replaces_the_unavailable_line_when_present():
    pack = _pack()
    prose = {0: "Prose for section one.", 1: "Prose for section two.",
            2: "Prose for section three.", 3: "Prose for section four."}
    md = render(pack, None, prose, run_id="r1", total_usd=0.45)
    assert PROSE_UNAVAILABLE not in md
    assert "Prose for section one." in md
    assert "Prose for section four." in md


def test_supply_table_lists_every_poi_with_status_and_basis():
    pack = _pack()
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "Test Grocery" in md and "open" in md
    assert "Closed Hardware" in md and "out_of_business" in md
    assert "Mystery Cafe" in md and "unknown" in md


def test_enrichment_check_counts_are_printed():
    pack = _pack()
    enrichment = Enrichment(checks_planned=3, checks_done=2, cap_hit=True)
    md = render(pack, enrichment, None, run_id="r1", total_usd=0.5)
    assert "**2**" in md and "**3**" in md
    assert "cap hit" in md.lower()


def test_slug_is_filesystem_safe_and_deterministic():
    assert slug("Graham Avenue") == "graham-avenue"
    assert slug("  Weird!! Name??  ") == "weird-name"
    assert slug("") == "address"


def test_out_path_lands_under_docs_recommendations():
    pack = _pack()
    p = out_path(pack)
    assert p.parent.name == "recommendations"
    assert p.name.startswith("test-street-")
    assert p.suffix == ".md"


def test_never_prints_a_legality_flip_from_histdist_or_landmark():
    """D82 sanity, rendering side: a landmark/histdist card label must never
    change the printed legality verdict."""
    pack = _pack(legality="commercial")
    pack.legality["histdist"] = "Test Historic District"
    pack.legality["landmark"] = "Individual Landmark"
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "Legality: commercial" in md
    assert "label only" in md


# ------------------------------------------ investor review item 1: falsification

def test_falsification_sentence_prints_once_from_the_forecast_field_alone():
    pack = _pack()      # forecast present, p_opening set
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert md.count("**Falsification test:**") == 1
    assert "no falsification test" not in md.lower()


def test_prose_can_never_contradict_the_falsification_line_when_forecast_present():
    """Adversarial prose that denies a test exists must not survive into the
    rendered file -- the deterministic line from `pack.forecast` is the only
    place this report ever states whether one exists (investor review item
    1)."""
    pack = _pack()
    prose = {0: "No falsification test is present in the evidence, so none can be "
                "quoted. The category call otherwise looks reasonable."}
    md = render(pack, None, prose, run_id="r1", total_usd=0.0)
    assert md.count("**Falsification test:**") == 1
    assert "no falsification test" not in md.lower()
    # the rest of that adversarial sentence (unrelated to the claim) survives
    assert "category call otherwise looks reasonable" in md.lower()


def test_no_falsification_line_when_forecast_is_absent_even_if_prose_invents_one():
    pack = _pack()
    pack.forecast = None
    prose = {0: "Falsification test: this call is wrong if nothing opens nearby."}
    md = render(pack, None, prose, run_id="r1", total_usd=0.0)
    assert "**Falsification test:**" not in md
    assert "falsification" not in md.lower()
    assert "No forecast is on file" in md


# ------------------------------------------------- investor review item 2: grade gate

def test_is_below_c_grade_rankings():
    assert is_below_c(_pack(grade="D")) is True
    assert is_below_c(_pack(no_grades=True)) is True
    assert is_below_c(_pack(grade="C")) is False
    assert is_below_c(_pack(grade="B")) is False
    assert is_below_c(_pack(grade="A")) is False


def test_grade_d_renders_the_one_page_no_trade_note():
    pack = _pack(grade="D")
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "**NO TRADE.**" in md
    for h in HEADINGS:
        assert h in md
    # no POI table / appendix, no underwriting paragraph, no web-beyond-news
    assert "## Appendix — supply detail" not in md
    assert "Test Grocery" not in md
    assert "**Underwriting**" not in md
    assert md.count(PROSE_UNAVAILABLE) == 4


def test_no_grades_at_all_also_renders_the_no_trade_note():
    pack = _pack(no_grades=True)
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "**NO TRADE.**" in md
    assert "No category could be graded for this address." in md


def test_grade_c_still_renders_the_full_memo():
    pack = _pack(grade="C")
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "**NO TRADE.**" not in md
    assert "## Appendix — supply detail" in md
    assert "**Underwriting**" in md


# ----------------------------------------- investor review item 3: underwriting

def test_underwriting_paragraph_checks_homes_against_the_d18_econ_minimum():
    pack = _pack(grade="C")     # lead category grocery, homes_400m=3000, ECON min 1500
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "D18 minimum-viable **1,500**" in md
    assert "clears the threshold" in md
    assert "3,000" in md


def test_underwriting_paragraph_flags_a_category_below_the_d18_minimum():
    pack = _pack(grade="C")
    pack.demand["homes_400m"] = 100     # well below grocery's 1,500 D18 minimum
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "is BELOW the threshold" in md


def test_underwriting_paragraph_names_categories_with_no_d18_minimum():
    pack = _pack(grade="C")
    pack.grades[0]["category"] = "bar"          # not in the D18 ECON table
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "No D18 minimum-viable-catchment threshold is defined for bar" in md


def test_underwriting_paragraph_computes_rent_to_revenue_and_downside_case():
    pack = _pack(grade="C")     # rent_ceiling=12000, revenue_p50=600000, revenue_p25=400000
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    # (12000 * 12) / 600000 = 24.0%
    assert "24.0%" in md
    # downside at p25: (12000 * 12) / 400000 = 36.0%
    assert "36.0%" in md
    assert "Payback:" in md


# --------------------------- investor review item 4: named rows, not counts

def test_vacant_storefronts_render_as_named_rows_not_a_count():
    pack = _pack(grade="C")
    pack.vacant_storefronts = [VacantStorefrontRow(
        premises_id="sf1", address="318 Graham Ave", dist_m=77.0,
        floor_area_sqft=900.0, last_use="FOOD SERVICES", vacant_since=2025)]
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "318 Graham Ave" in md
    assert "FOOD SERVICES" in md
    assert "2025" in md
    # in section 2's body, not the appendix
    idx_vacant = md.index("318 Graham Ave")
    idx_appendix = md.index("## Appendix")
    assert idx_vacant < idx_appendix


def test_pipeline_filings_render_as_named_rows():
    pack = _pack(grade="C")
    pack.pipeline = [PipelineRow(
        pipeline_id="pl1", business_name="Riff", category="bar", kind="SLA pending",
        stage="liquor_application", entry_date=None, dist_m=82.0)]
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "Riff" in md
    assert "SLA pending" in md


def test_chains_watchlist_renders_as_named_rows_within_800m():
    pack = _pack(grade="C")
    pack.chains_watch = [ChainWatchRow(
        brand_key="dunkin", display_name="Dunkin'", category="cafe_bakery",
        dist_m=32.0, locations_new_12m=61, locations_total=1480)]
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "Dunkin'" in md
    assert "61" in md


def test_raw_poi_table_lives_only_in_the_appendix_not_section_2():
    pack = _pack(grade="C")
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    sec2 = md[md.index(HEADINGS[1]):md.index(HEADINGS[2])]
    assert "Test Grocery" not in sec2
    appendix = md[md.index("## Appendix"):]
    assert "Test Grocery" in appendix


# --------------------------------- investor review item 6: planner's verdict

def test_special_district_prints_not_loaded_when_absent():
    pack = _pack(grade="C")
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "Special district: not loaded." in md


def test_special_district_prints_spdist1_when_present():
    pack = _pack(grade="C")
    pack.legality["spdist1"] = "Special Gowanus Mixed Use District"
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "Special district: Special Gowanus Mixed Use District." in md


def test_flood_environmental_not_loaded_line_is_rendered():
    pack = _pack(grade="C")
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "flood/environmental overlays: not loaded" in md


def test_sla_500ft_rule_prints_only_for_bar_or_restaurant():
    pack = _pack(grade="C")
    pack.grades[0]["category"] = "bar"
    pack.provenance["sla_500ft"] = {"n_on_premises_licenses": 5, "triggers_hearing": True}
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    assert "SLA 500-foot rule:** 5 active" in md
    assert "mandatory public-interest hearing" in md


def test_same_bbl_conflicts_render_in_the_provenance_footer_not_the_body():
    pack = _pack(grade="C")
    pack.provenance["same_bbl_conflicts"] = [
        "other-memo-2026-09-14.md names lead_category ['tailor_repair'] for BBL "
        "3012340001; this report reads 'grocery'"]
    md = render(pack, None, None, run_id="r1", total_usd=0.0)
    footer = md[md.index("## Provenance"):]
    assert "tailor_repair" in footer
    body = md[:md.index("## Provenance")]
    assert "tailor_repair" not in body


# ------------------------------------------------- provenance footer / header

def test_internal_identifiers_move_to_the_provenance_footer():
    pack = _pack(grade="C")
    md = render(pack, None, None, run_id="report-abc123", total_usd=0.1234)
    header = md.split("\n\n", 3)[0] + md.split("\n\n", 3)[1]
    assert "report-abc123" not in header
    assert "0.1234" not in header
    footer = md[md.index("## Provenance"):]
    assert "report-abc123" in footer
    assert "0.1234" in footer


# --------------------------------------------- 2026-09-15 GTM-183 regression

def test_cli_style_prose_reply_renders_in_all_four_sections_no_unavailable_line():
    """End-to-end through `write_prose` -> `render`: `ClaudeCliProse`
    (GTM-172) is not guaranteed to return bare JSON -- observed to wrap its
    reply in a ``` fence. Before the fix, `_split_sections` failed to parse
    that, dumped the whole fenced blob into section 1 as if it were
    narrative, and left sections 2-4 showing `PROSE_UNAVAILABLE` even though
    a billed call had run. All four sections must carry real prose here, the
    fence markup must not leak into the document, and neither "unavailable"
    line may appear."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    budget = Budget(run_id="r1", cap_usd=1.0, con=con)
    payload = json.dumps({"1": "Category call prose.", "2": "Supply prose.",
                          "3": "Demand prose.", "4": "Legality prose."})
    fake = FakeProse(text=f"```json\n{payload}\n```")
    pack = _pack(grade="C")
    sections = write_prose(pack, Enrichment(), fake, budget)

    md = render(pack, None, sections, run_id="r1", total_usd=0.01)

    assert PROSE_UNAVAILABLE not in md
    assert PROSE_PARSE_FAILED not in md
    assert "```json" not in md
    assert "Category call prose." in md
    assert "Supply prose." in md
    assert "Demand prose." in md
    assert "Legality prose." in md


def test_unparsed_prose_prints_the_honest_parse_failed_line_and_raw_text_in_footer():
    """A prose call that ran (billed, `called=True`) but whose reply could
    not be recovered into any section must never say "ANTHROPIC_API_KEY
    unset" (that message is only honest when the client was never called at
    all) -- and the raw reply belongs in the provenance footer, not the
    body, so a reader never mistakes it for narrative."""
    pack = _pack(grade="C")
    prose = ProseSections(called=True, parsed=False, raw_text="garbled model reply")
    md = render(pack, None, prose, run_id="r1", total_usd=0.01)

    assert PROSE_UNAVAILABLE not in md
    assert md.count(PROSE_PARSE_FAILED) == 4
    footer = md[md.index("## Provenance"):]
    assert "garbled model reply" in footer
    body = md[:md.index("## Provenance")]
    assert "garbled model reply" not in body
