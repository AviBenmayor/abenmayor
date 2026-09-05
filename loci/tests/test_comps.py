"""Synthetic-fixture tests for the comps fair-value model (loci.model.comps).

No real BizBuySell data exists yet -- collection was blocked (HTTP 403 on
robots.txt and every index URL tried; BizQuest/LoopNet fallbacks also 403'd,
see benchmarks.yaml's `collection` block and comps.py's module docstring).
These tests build small synthetic listing rows in memory (never touching the
real, currently-empty, data/benchmarks/bizbuysell_nyc_listings.csv) and check
the pipeline logic that will run the moment real rows exist: the
neighborhood -> borough -> citywide fallback, the thin-data flag (n < 8),
the rent fallback tiers, and the sign of `cushion`.
"""
from __future__ import annotations

from loci.model.comps import THIN_N, comps_for

BENCH = {"occupancy_cost_ratio": {"restaurant": 0.08, "cafe_bakery": 0.10}}


def _listing(category, borough, neighborhood, revenue, cash_flow,
             rent=None, cash_flow_before_rent=None):
    return {
        "loci_category": category, "borough": borough, "neighborhood": neighborhood,
        "gross_revenue": revenue, "cash_flow_sde": cash_flow,
        "rent": rent, "cash_flow_before_rent": cash_flow_before_rent,
    }


def test_fallback_uses_neighborhood_when_available():
    listings = [_listing("restaurant", "Brooklyn", "Williamsburg", 500_000, 80_000, rent=6_000)
                for _ in range(3)]
    r = comps_for("restaurant", borough="Brooklyn", neighborhood="Williamsburg",
                   listings=listings, benchmarks=BENCH)
    assert r["level_used"] == "neighborhood"
    assert r["n_comps"] == 3
    assert r["geo_value"] == "Williamsburg"


def test_fallback_drops_to_borough_when_neighborhood_has_no_comps():
    listings = [_listing("restaurant", "Brooklyn", "Bushwick", 500_000, 80_000, rent=6_000)
                for _ in range(3)]
    r = comps_for("restaurant", borough="Brooklyn", neighborhood="Williamsburg",
                   listings=listings, benchmarks=BENCH)
    assert r["level_used"] == "borough"
    assert r["n_comps"] == 3
    assert r["geo_value"] == "Brooklyn"


def test_fallback_drops_to_citywide_when_borough_has_no_comps():
    listings = [_listing("restaurant", "Queens", "Astoria", 500_000, 80_000, rent=6_000)
                for _ in range(3)]
    r = comps_for("restaurant", borough="Brooklyn", neighborhood="Williamsburg",
                   listings=listings, benchmarks=BENCH)
    assert r["level_used"] == "citywide"
    assert r["n_comps"] == 3
    assert r["geo_value"] == "(all)"


def test_fallback_ignores_unrequested_levels():
    """No borough/neighborhood passed -> go straight to citywide, no
    accidental filtering."""
    listings = [_listing("restaurant", "Queens", "Astoria", 500_000, 80_000, rent=6_000)
                for _ in range(2)] + [_listing("restaurant", "Brooklyn", "Bushwick", 400_000, 60_000, rent=5_000)]
    r = comps_for("restaurant", listings=listings, benchmarks=BENCH)
    assert r["level_used"] == "citywide"
    assert r["n_comps"] == 3


def test_thin_flag_below_eight():
    listings = [_listing("restaurant", "Brooklyn", None, 500_000, 80_000, rent=6_000) for _ in range(5)]
    r = comps_for("restaurant", borough="Brooklyn", listings=listings, benchmarks=BENCH)
    assert r["n_comps"] == 5
    assert r["thin"] is True


def test_thin_flag_clears_at_eight():
    listings = [_listing("restaurant", "Brooklyn", None, 500_000, 80_000, rent=6_000) for _ in range(THIN_N)]
    r = comps_for("restaurant", borough="Brooklyn", listings=listings, benchmarks=BENCH)
    assert r["n_comps"] == THIN_N
    assert r["thin"] is False


def test_zero_comps_is_thin_with_no_data():
    r = comps_for("restaurant", borough="Bronx", listings=[], benchmarks=BENCH)
    assert r["n_comps"] == 0
    assert r["thin"] is True
    assert r["gross_revenue_p50"] is None
    assert r["rent_source"] == "no_data"
    assert r["cushion"] is None
    assert r["cushion_basis"] == "no_data"


def test_cushion_positive_when_cash_flow_exceeds_rent():
    listings = [_listing("restaurant", "Brooklyn", None, 500_000, 100_000, rent=4_000) for _ in range(8)]
    r = comps_for("restaurant", borough="Brooklyn", listings=listings, benchmarks=BENCH)
    assert r["rent_source"] == "listed"
    assert r["cushion_basis"] == "cash_flow_vs_rent"
    assert r["cushion"] > 0


def test_cushion_negative_when_rent_exceeds_cash_flow():
    listings = [_listing("restaurant", "Brooklyn", None, 500_000, 20_000, rent=15_000) for _ in range(8)]
    r = comps_for("restaurant", borough="Brooklyn", listings=listings, benchmarks=BENCH)
    assert r["rent_source"] == "listed"
    assert r["cushion"] < 0


def test_rent_falls_back_to_cash_flow_before_rent_addback():
    listings = [_listing("restaurant", "Brooklyn", None, 500_000, 80_000,
                          rent=None, cash_flow_before_rent=140_000) for _ in range(8)]
    r = comps_for("restaurant", borough="Brooklyn", listings=listings, benchmarks=BENCH)
    assert r["rent_source"] == "cash_flow_before_rent_addback"
    assert r["supportable_rent"] == 60_000   # 140k - 80k, the implied rent add-back
    assert r["cushion_basis"] == "cash_flow_vs_rent"
    assert r["cushion"] > 0


def test_rent_falls_back_to_occupancy_ratio_when_no_rent_data():
    listings = [_listing("restaurant", "Brooklyn", None, 500_000, 30_000) for _ in range(8)]
    r = comps_for("restaurant", borough="Brooklyn", listings=listings, benchmarks=BENCH)
    assert r["rent_source"] == "occupancy_ratio_fallback"
    assert r["supportable_rent"] == 500_000 * 0.08
    assert r["cushion_basis"] == "cash_flow_margin_p25"
    assert r["cushion"] == 30_000 / 500_000


def test_unknown_category_raises():
    import pytest
    with pytest.raises(ValueError):
        comps_for("not_a_real_category", listings=[], benchmarks=BENCH)
