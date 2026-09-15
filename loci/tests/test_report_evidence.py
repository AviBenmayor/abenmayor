"""AC-16/AC-17 read side: `loci.report.evidence`. `_synthetic_db()` here is
the SHARED fixture the rest of `tests/test_report_*.py` imports (naming
constraint: only `tests/test_report_*.py` files are this session's to
create) -- one address, five POIs (one open, one closed, three unknown, all
within the default 500 m catchment), enough for `area_facts`/`build_cards`
to grade without a 2 GB warehouse, on the same pattern
`tests/test_recommend.py::_synthetic_db` already uses for `area_facts`.
"""
from __future__ import annotations

import datetime as dt

import pytest

import loci.db as locidb
from loci.categories import CATEGORIES
from loci.report import evidence as ev

ADDR_ID = "addr1"
ADDR_LAT = 40.7100
ADDR_LON = -73.9500


def _poi(con, poi_id, name, category, source_id, dlat_m, attrs, cluster_id):
    lat = ADDR_LAT + dlat_m / 111_320.0
    lon = ADDR_LON
    import json

    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, category, tier, name, geom, "
        "observed_on, attrs) VALUES (?, ?, ?, 1, ?, ST_Point(?, ?), ?, ?)",
        [poi_id, source_id, category, name, lon, lat, dt.date(2026, 1, 1), json.dumps(attrs)])
    con.execute(
        "INSERT INTO analysis.poi_dedup (poi_id, cluster_id, is_canonical, category) "
        "VALUES (?, ?, TRUE, ?)", [poi_id, cluster_id, category])


def _synthetic_db():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)

    con.execute(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, neighborhood, "
        "nta_code, eligible, present_count, n_missing, reach_source, reach_hash, "
        "graph_version, run_at, homes_400m, addressable_homes_400m_laundry, "
        "units_permitted_400m, units_active_400m, units_stalled_400m, "
        "vacant_storefronts_400m, storefronts_400m, storefront_asof, "
        "supply_ratio_supply_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [ADDR_ID, "3012340001", ADDR_LON, ADDR_LAT, "BK", "Testville", "BK0601", True,
         12, 3, "tiers", "h", "g", dt.datetime(2026, 9, 11), 3000.0, 1000.0,
         50.0, 10.0, 5.0, 2.0, 20.0, "2024-12-31", "767b28674e30"])
    con.execute(
        "UPDATE analysis.address SET homes_800m = 9000, transit_entries_400m = 500, "
        "jobs_400m = 800, units_completed_24mo_400m = 5, units_completed_60mo_400m = 8, "
        "street_name = 'Test Street' WHERE address_id = ?", [ADDR_ID])

    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, "
        "supply_ratio_vs_base) VALUES (?,?,?,?)",
        [(ADDR_ID, "BK", c, 0.1 if c == "grocery" else 0.9) for c in CATEGORIES])
    con.execute(
        "UPDATE analysis.address_category SET revenue_p25 = 400000, revenue_p50 = 600000, "
        "revenue_p75 = 900000, rent_ceiling = 12000, "
        "demand_caveat_text = 'income below the MOE-confident cutoff (test fixture)' "
        "WHERE address_id = ? AND category = 'grocery'", [ADDR_ID])

    con.execute(
        "INSERT INTO analysis.address_demographics (address_id, bbl, acs_year, "
        "median_hh_income, median_hh_income_moe, age_18_34_share, renter_share) "
        "VALUES (?,?,?,?,?,?,?)",
        [ADDR_ID, "3012340001", 2023, 90_000.0, 8_000.0, 0.3, 0.65])

    _poi(con, "poi:open", "Test Grocery", "grocery", "nyc_dcwp_licenses", 50.0,
        {"active": "true", "expires": "2030-01-01"}, 1)
    _poi(con, "poi:closed", "Closed Hardware", "hardware", "nyc_dcwp_licenses", 100.0,
        {"active_basis": "out_of_business"}, 2)
    _poi(con, "poi:unknown1", "Mystery Cafe", "cafe_bakery", "overture_places", 150.0, {}, 3)
    _poi(con, "poi:unknown2", "Mystery Bar", "bar", "overture_places", 200.0, {}, 4)
    _poi(con, "poi:unknown3", "Mystery Salon", "nails_beauty", "overture_places", 250.0, {}, 5)
    return con


def test_assemble_reads_the_lead_category_and_grades():
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID)
    assert pack.lead_category == "grocery"      # thinnest supply_ratio_vs_base
    assert pack.grades and pack.grades[0]["category"] == "grocery"
    assert pack.address["address_id"] == ADDR_ID


def test_assemble_reads_legality_null_safe():
    """D97's `legality`/`legality_basis`/`has_open_commercial_poi` are
    MATERIALIZED columns on `analysis.address`, written by
    `model.address_legality.build_legality_columns` (`analysis.address_legality`
    is now a thin passthrough view over them, per that module's own
    `passthrough_view_sql`) -- a fresh fixture row that never ran that build
    step reads NULL, and `assemble()` must not crash on that, just carry the
    NULL through (`render.py` prints 'unknown' for it)."""
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID)
    assert pack.legality["legality"] is None
    assert pack.legality["zonedist1"] is None


def test_assemble_reads_a_populated_legality_verdict():
    con = _synthetic_db()
    con.execute(
        "UPDATE analysis.address SET legality = 'ineligible', "
        "legality_basis = 'R6 zoned, no C1/C2 overlay, no open commercial POI', "
        "zonedist1 = 'R6', has_open_commercial_poi = FALSE WHERE address_id = ?",
        [ADDR_ID])
    pack = ev.assemble(con, ADDR_ID)
    assert pack.legality["legality"] == "ineligible"
    assert pack.legality["zonedist1"] == "R6"


def test_supply_status_and_distance_are_correct():
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID)
    by_id = {p.poi_id: p for p in pack.supply}
    assert by_id["poi:open"].status == "open"
    assert by_id["poi:closed"].status == "closed"
    assert by_id["poi:closed"].basis and "out_of_business" in by_id["poi:closed"].basis
    assert by_id["poi:unknown1"].status == "unknown"
    # nearest-first ordering
    assert [p.poi_id for p in pack.supply] == [
        "poi:open", "poi:closed", "poi:unknown1", "poi:unknown2", "poi:unknown3"]
    assert by_id["poi:open"].dist_m == pytest.approx(50.0, abs=1.0)


def test_catchment_m_excludes_farther_pois():
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID, catchment_m=120.0)
    ids = {p.poi_id for p in pack.supply}
    assert ids == {"poi:open", "poi:closed"}


def test_unknown_pois_returns_only_unknown():
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID)
    unk = ev.unknown_pois(pack)
    assert {p.poi_id for p in unk} == {"poi:unknown1", "poi:unknown2", "poi:unknown3"}


def test_hash_is_stable_and_changes_with_supply():
    con = _synthetic_db()
    pack1 = ev.assemble(con, ADDR_ID)
    pack2 = ev.assemble(con, ADDR_ID)
    assert pack1.hash() == pack2.hash()

    # A closure verdict landing changes the hash (cache must not serve stale
    # evidence -- AC-19's flip side).
    from loci.model.poi_evidence import EvidenceRow, insert_evidence
    insert_evidence(con, EvidenceRow(
        poi_id="poi:unknown1", verdict="closed", source="web", source_name="eater.com",
        url="https://eater.com/x", evidence_date=dt.date(2026, 9, 1), dated_by="published",
        retrieved_at=dt.datetime.now(), query="test"))
    pack3 = ev.assemble(con, ADDR_ID)
    assert pack3.hash() != pack1.hash()


def test_resolve_address_passes_through_an_existing_address_id():
    """No network call: `resolve_address` short-circuits to a passthrough
    when the string already names a Loci `address_id` -- see
    `loci.geo.geosearch.resolve`'s own docstring."""
    con = _synthetic_db()
    assert ev.resolve_address(con, ADDR_ID) == ADDR_ID


def test_refresh_supply_picks_up_a_new_evidence_row():
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID)
    assert next(p for p in pack.supply if p.poi_id == "poi:unknown1").status == "unknown"

    from loci.model.poi_evidence import EvidenceRow, insert_evidence
    insert_evidence(con, EvidenceRow(
        poi_id="poi:unknown1", verdict="closed", source="web", source_name="eater.com",
        url="https://eater.com/x", evidence_date=dt.date(2026, 9, 1), dated_by="published",
        retrieved_at=dt.datetime.now(), query="test"))
    ev.refresh_supply(pack, con)
    assert next(p for p in pack.supply if p.poi_id == "poi:unknown1").status == "closed"
