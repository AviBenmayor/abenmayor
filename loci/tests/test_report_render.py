"""AC-16: `loci.report.render`. Pure -- a hand-built `EvidencePack` +
`Enrichment`, no warehouse needed. Confirms the four fixed headings are
always present and non-empty, with or without prose."""
from __future__ import annotations

from loci.report.enrich import Enrichment
from loci.report.evidence import EvidencePack, POIRow
from loci.report.render import HEADINGS, PROSE_UNAVAILABLE, out_path, render, slug


def _pack(legality="commercial") -> EvidencePack:
    return EvidencePack(
        address={"address_id": "addr1", "bbl": "3012340001", "lat": 40.71, "lon": -73.95,
                 "street_name": "Test Street", "borough": "BK"},
        scores={"asof": "2026-09-14", "live_hash": "abc123"},
        grades=[{"category": "grocery", "category_label": "Grocery / supermarket",
                 "overall_grade": "C", "verdict": "wait for more evidence",
                 "supply_ratio_vs_base": 0.4,
                 "sections": [{"key": "coverage",
                              "facts": {"coverage_hole_rate": 0.08}}]}],
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
