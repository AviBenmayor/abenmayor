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


def _vacant_storefront(con, premises_id, address, dlat_m, reporting_year, vacant,
                       bbl="3099990001", activity=None):
    lat = ADDR_LAT + dlat_m / 111_320.0
    con.execute(
        "INSERT INTO analysis.storefront (storefront_id, premises_id, filing_due_date, "
        "reporting_year, universe, borough, source, ingested_at, "
        "bbl, address, geom, vacant_1231, vacant_0630, primary_business_activity, "
        "activity_canonical) "   # sql/041; `last_use` reads the canonical one
        "VALUES (?,?,?,?,?,?,?,?,?,?,ST_Point(?,?),?,?,?,?)",
        [f"{premises_id}-{reporting_year}", premises_id, dt.date(reporting_year, 12, 31),
         reporting_year, "full", "BK", "nyc_dof_storefront_registry", dt.datetime.now(),
         bbl, address, ADDR_LON, lat, vacant, vacant, activity,
         # Pre-recode-era fixture, so canonical == raw here. Present because
         # `last_use` binds to the canonical column (sql/041).
         activity])


def _pipeline_filing(con, pipeline_id, business_name, category, entry_stage, dlat_m,
                     is_open=False, entry_date=None):
    lat = ADDR_LAT + dlat_m / 111_320.0
    con.execute(
        "INSERT INTO analysis.storefront_pipeline (pipeline_id, group_kind, business_name, "
        "loci_category, entry_stage, entry_date, lon, lat, is_open, n_filings, n_sources, "
        "bbl_missing, name_key_missing, asof_date, built_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [pipeline_id, "filing", business_name, category, entry_stage, entry_date,
         ADDR_LON, lat, is_open, 1, 1, False, False, dt.date(2026, 9, 14),
         dt.datetime.now()])


def _chain_location(con, brand_key, display_name, category, dlat_m,
                    locations_new_12m=10, flagged=True, snapshot_month="2026-09"):
    lat = ADDR_LAT + dlat_m / 111_320.0
    con.execute(
        "INSERT INTO chains.brand_location (snapshot_month, brand_key, location_key, poi_id, "
        "category, borough, lon, lat, first_seen_on, first_seen_src) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [snapshot_month, brand_key, f"{brand_key}-loc1", f"{brand_key}-poi1", category, "BK",
         ADDR_LON, lat, None, None])
    con.execute(
        "INSERT INTO chains.brand_snapshot (snapshot_month, brand_key, display_name, "
        "loci_category, locations_total, locations_dated, locations_new_12m, "
        "locations_new_3m, n_boroughs, boroughs, categories, n_sources, flagged, "
        "flag_reason, detected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [snapshot_month, brand_key, display_name, category, 100, 100, locations_new_12m,
         5, 1, "BK", category, 1, flagged, None, dt.datetime.now()])


def _alcohol_license(con, licence_id, dlat_m, active=True, classification="on_premises"):
    lat = ADDR_LAT + dlat_m / 111_320.0
    con.execute(
        "INSERT INTO staging.alcohol_licences (licence_id, description, licence_class, "
        "classification, name, address, zip, borough, geom, expires_on, active, "
        "observed_on) VALUES (?,?,?,?,?,?,?,?,ST_Point(?,?),?,?,?)",
        [licence_id, "test", "0340", classification, "Test Bar", "1 Test St", "11211",
         "BK", ADDR_LON, lat, None, active, dt.date(2026, 1, 1)])


# ----------------------------------- investor review item 4: named supply/pipeline


def test_vacant_storefront_is_named_with_address_last_use_and_vacant_since():
    con = _synthetic_db()
    _vacant_storefront(con, "sf1", "318 Graham Ave", 77.0, 2025, True,
                       activity="FOOD SERVICES")
    pack = ev.assemble(con, ADDR_ID)
    assert len(pack.vacant_storefronts) == 1
    row = pack.vacant_storefronts[0]
    assert row.address == "318 Graham Ave"
    assert row.last_use == "FOOD SERVICES"
    assert row.vacant_since == 2025
    assert row.dist_m == pytest.approx(77.0, abs=1.0)


def test_vacant_storefront_since_is_the_earliest_year_of_the_contiguous_streak():
    con = _synthetic_db()
    _vacant_storefront(con, "sf1", "1 Test Row", 80.0, 2022, False, activity="RETAIL")
    _vacant_storefront(con, "sf1", "1 Test Row", 80.0, 2023, True, activity="RETAIL")
    _vacant_storefront(con, "sf1", "1 Test Row", 80.0, 2024, True, activity="RETAIL")
    _vacant_storefront(con, "sf1", "1 Test Row", 80.0, 2025, True, activity=None)
    pack = ev.assemble(con, ADDR_ID)
    assert len(pack.vacant_storefronts) == 1
    row = pack.vacant_storefronts[0]
    assert row.vacant_since == 2023            # 2022 breaks the streak
    assert row.last_use == "RETAIL"             # most recent NON-NULL activity


def test_currently_occupied_storefront_is_not_named_as_vacant():
    con = _synthetic_db()
    _vacant_storefront(con, "sf1", "1 Test Row", 80.0, 2024, True, activity="RETAIL")
    _vacant_storefront(con, "sf1", "1 Test Row", 80.0, 2025, False, activity="RETAIL")
    pack = ev.assemble(con, ADDR_ID)
    assert pack.vacant_storefronts == []


def test_vacant_storefront_null_flags_do_not_crash_and_are_not_listed():
    """Regression: `analysis.storefront.vacant_1231`/`vacant_0630` come back
    from `fetchdf()` as pandas nullable booleans, so a premises whose latest
    filing has BOTH flags NULL used to crash `_vacant_storefront_rows` with
    "boolean value of NA is ambiguous" on `bool(last.vacant_1231)`. The
    `_flag()`/`_isnull()` guards must read a NULL flag as not-vacant without
    raising, while a real TRUE flag on another premises still lists it."""
    con = _synthetic_db()
    _vacant_storefront(con, "sfnull", "1 Null Row", 90.0, 2025, None, activity="RETAIL")
    _vacant_storefront(con, "sftrue", "2 True Row", 95.0, 2025, True, activity="RETAIL")
    pack = ev.assemble(con, ADDR_ID)   # must not raise
    ids = {row.premises_id for row in pack.vacant_storefronts}
    assert "sfnull" not in ids
    assert "sftrue" in ids


def test_vacant_storefront_null_flags_mid_streak_break_the_streak():
    """Regression sibling to the crash guard above: a NULL-flagged filing
    SANDWICHED between two TRUE-flagged filings must still break the
    contiguous-streak walk (the guard reads NULL as not-vacant, and
    not-vacant breaks the streak per the docstring's "a gap year breaks the
    streak") -- the premises is still listed (it reads vacant on its own
    latest filing) but `vacant_since` must not walk past the NULL row back
    to the earliest TRUE filing."""
    con = _synthetic_db()
    _vacant_storefront(con, "sfgap", "3 Gap Row", 85.0, 2023, True, activity="RETAIL")
    _vacant_storefront(con, "sfgap", "3 Gap Row", 85.0, 2024, None, activity="RETAIL")
    _vacant_storefront(con, "sfgap", "3 Gap Row", 85.0, 2025, True, activity="RETAIL")
    pack = ev.assemble(con, ADDR_ID)   # must not raise
    assert len(pack.vacant_storefronts) == 1
    row = pack.vacant_storefronts[0]
    assert row.premises_id == "sfgap"
    assert row.vacant_since == 2025    # the NULL 2024 filing breaks the streak


def test_vacant_storefront_floor_area_from_pluto_retailarea_when_present():
    con = _synthetic_db()
    con.execute(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, "
        "eligible, present_count, n_missing, reach_source, reach_hash, graph_version, "
        "run_at, retailarea) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ["addr2", "3055550001", ADDR_LON, ADDR_LAT, "BK", True, 0, 0, "tiers", "h",
         "g", dt.datetime(2026, 9, 11), "900"])
    _vacant_storefront(con, "sf1", "318 Graham Ave", 77.0, 2025, True,
                       bbl="3055550001", activity="FOOD SERVICES")
    pack = ev.assemble(con, ADDR_ID)
    assert pack.vacant_storefronts[0].floor_area_sqft == pytest.approx(900.0)


def test_pipeline_filings_are_named_and_open_filings_excluded():
    con = _synthetic_db()
    _pipeline_filing(con, "pl1", "Riff", "bar", "liquor_application", 82.0)
    _pipeline_filing(con, "pl2", "TFS Burger Works", "restaurant", "fitout_filing", 90.0)
    _pipeline_filing(con, "pl3", "Already Open Cafe", "cafe_bakery", "fitout_filing",
                     95.0, is_open=True)
    _pipeline_filing(con, "pl4", "Just Inspected", "restaurant", "first_inspection", 60.0)
    pack = ev.assemble(con, ADDR_ID)
    names = {p.business_name for p in pack.pipeline}
    assert names == {"Riff", "TFS Burger Works"}
    kinds = {p.business_name: p.kind for p in pack.pipeline}
    assert kinds["Riff"] == "SLA pending"
    assert kinds["TFS Burger Works"] == "DOB fit-out"


def test_chains_watch_lists_only_flagged_brands_and_respects_the_radius():
    con = _synthetic_db()
    _chain_location(con, "dunkin", "Dunkin'", "cafe_bakery", 32.0,
                    locations_new_12m=61, flagged=True)
    _chain_location(con, "unflagged", "Steady Chain", "restaurant", 40.0, flagged=False)
    _chain_location(con, "far_chain", "Far Away Chain", "restaurant", 900.0, flagged=True)
    pack = ev.assemble(con, ADDR_ID)
    names = {c.display_name for c in pack.chains_watch}
    assert names == {"Dunkin'"}
    assert pack.chains_watch[0].locations_new_12m == 61


# --------------------------- investor review item 6: SLA 500-ft, same-BBL check


def test_sla_500ft_only_populated_for_bar_or_restaurant_lead_category():
    con = _synthetic_db()      # lead category here is 'grocery'
    pack = ev.assemble(con, ADDR_ID)
    assert pack.provenance["sla_500ft"] is None


def test_sla_500ft_counts_active_on_premises_licenses_within_500ft():
    con = _synthetic_db()
    con.execute("UPDATE analysis.address_category SET supply_ratio_vs_base = 0.05 "
               "WHERE address_id = ? AND category = 'bar'", [ADDR_ID])
    _alcohol_license(con, "lic1", 50.0, active=True, classification="on_premises")
    _alcohol_license(con, "lic2", 100.0, active=True, classification="on_premises")
    _alcohol_license(con, "lic3", 120.0, active=False, classification="on_premises")  # inactive
    _alcohol_license(con, "lic4", 130.0, active=True, classification="off_premises_beer")
    _alcohol_license(con, "lic5", 300.0, active=True, classification="on_premises")   # > 500 ft
    pack = ev.assemble(con, ADDR_ID)
    assert pack.lead_category == "bar"
    sla = pack.provenance["sla_500ft"]
    assert sla["n_on_premises_licenses"] == 2
    assert sla["triggers_hearing"] is False


def test_sla_500ft_triggers_hearing_at_three_or_more_licenses():
    con = _synthetic_db()
    con.execute("UPDATE analysis.address_category SET supply_ratio_vs_base = 0.05 "
               "WHERE address_id = ? AND category = 'bar'", [ADDR_ID])
    for i, d in enumerate((30.0, 60.0, 90.0)):
        _alcohol_license(con, f"lic{i}", d, active=True, classification="on_premises")
    pack = ev.assemble(con, ADDR_ID)
    assert pack.provenance["sla_500ft"]["triggers_hearing"] is True


def test_same_bbl_consistency_flags_a_conflicting_lead_category(tmp_path):
    other = tmp_path / "other-memo-2026-09-14.md"
    other.write_text(
        "Some analysis for BBL 3012340001. `gap_score` / `lead_category` | 0.526 / "
        "**tailor_repair** (0.00x supply)")
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID, recommendations_dir=tmp_path)
    conflicts = pack.provenance["same_bbl_conflicts"]
    assert len(conflicts) == 1
    assert "tailor_repair" in conflicts[0]
    assert "grocery" in conflicts[0]


def test_same_bbl_consistency_ignores_files_older_than_seven_days(tmp_path):
    import os as _os
    import time as _time

    other = tmp_path / "old-memo-2026-08-01.md"
    other.write_text("BBL 3012340001, lead_category **tailor_repair**")
    old_ts = _time.time() - 30 * 86400
    _os.utime(other, (old_ts, old_ts))
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID, recommendations_dir=tmp_path)
    assert pack.provenance["same_bbl_conflicts"] == []


def test_same_bbl_consistency_is_empty_with_no_recent_files(tmp_path):
    con = _synthetic_db()
    pack = ev.assemble(con, ADDR_ID, recommendations_dir=tmp_path)
    assert pack.provenance["same_bbl_conflicts"] == []


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
