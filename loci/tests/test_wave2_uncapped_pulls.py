"""Wave two of the owner's 2026-09-16 rule: "never ever ever limit data pulls".

Each test here pins ONE cap that was removed, and — where the cap sat next to
the supply set — pins the thing that must NOT have moved with it. The pairing
is the point: "we kept more rows" and "the supply set is unchanged" are two
claims, and a change that quietly traded one for the other would pass a test
that only asserted the first.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from loci import db as locidb
from loci.model import licence_interval as li
from loci.model.poi_presence import poi_status
from loci.sources.cities.nyc import dcwp, filing_feeds as ff
from loci.sources.cities.nyc import storefront_registry as sr


# --------------------------------------------------------------- cap 1: DOF

def test_storefront_registry_ingests_all_five_boroughs():
    """The registry file is city-wide and already downloaded whole; the D48
    MN+BK SCREEN lives at query time, in `loci storefronts`, not in the pull."""
    assert set(sr.DEFAULT_BOROUGHS) == {"MN", "BX", "BK", "QN", "SI"}


# ------------------------------------------------ cap 2 / 11: DCWP roster

def test_roster_keeps_every_status_but_only_active_can_be_open():
    """Stop dropping non-Active rows WITHOUT widening what counts as open."""
    rows = [
        {"license_nbr": "A", "business_category": "Laundries",
         "license_status": "Active", "business_name": "LIVE WASH",
         "license_creation_date": "2024-01-01T00:00:00.000",
         "lic_expir_dd": "2027-12-31T00:00:00.000",
         "latitude": "40.7", "longitude": "-73.95", "address_borough": "Brooklyn"},
        {"license_nbr": "B", "business_category": "Laundries",
         "license_status": "Expired", "business_name": "DEAD WASH",
         "license_creation_date": "2021-07-01T00:00:00.000",
         "lic_expir_dd": "2023-12-31T00:00:00.000",
         "latitude": "40.7", "longitude": "-73.96", "address_borough": "Brooklyn"},
        {"license_nbr": "C", "business_category": "Laundries",
         "license_status": "Surrendered", "business_name": "GONE WASH",
         "license_creation_date": "2019-01-01T00:00:00.000",
         "latitude": "40.7", "longitude": "-73.97", "address_borough": "Brooklyn"},
    ]
    recs = {r.source_record_id: r for r in dcwp.DcwpAdapter().normalize(rows)}
    assert set(recs) == {"A", "B", "C"}, "every status is carried"

    src = "nyc_dcwp_licenses"
    assert poi_status(recs["A"].attrs, source_id=src)[0] == "open"
    # A published, DATED expiry in the past is the only thing that can close a
    # roster row.
    assert poi_status(recs["B"].attrs, source_id=src)[0] == "closed"
    # 'Surrendered' with no expiry is an ENDING WITH NO DATE. It must be
    # 'unknown', never 'closed': inventing an event time (the pull date? a
    # midpoint?) would hand a survival model a fabricated hazard shape.
    assert poi_status(recs["C"].attrs, source_id=src)[0] == "unknown"


def test_roster_promotes_licence_identity_to_columns():
    """sql/043: a JSON key is not a join key."""
    rows = [{"license_nbr": "A", "business_unique_id": "BA-1-2022",
             "business_category": "Laundries", "license_status": "Active",
             "business_name": "X", "lic_expir_dd": "2027-01-01T00:00:00.000",
             "latitude": "40.7", "longitude": "-73.95",
             "address_borough": "Brooklyn"}]
    r = next(iter(dcwp.DcwpAdapter().normalize(rows)))
    assert r.licence_number == "A"
    assert r.business_unique_id == "BA-1-2022"
    assert r.license_status == "Active"
    # and still in attrs, because poi_is_open reads attrs
    assert r.attrs["licence_number"] == "A"


def test_poi_table_carries_the_identity_columns():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    cols = {c[0] for c in con.execute("SELECT * FROM staging.poi LIMIT 0").description}
    assert {"license_status", "licence_number", "business_unique_id"} <= cols
    con.close()


# ----------------------------------------------------------- cap 4: NYS SLA

def test_sla_source_name_defect_is_fixed_everywhere():
    """One dataset, one name. `nyc_sla_liquor_licenses` was one letter from the
    registry id and matched no source in it."""
    assert "nys_sla_liquor_licenses" in ff.FEEDS
    assert "nyc_sla_liquor_licenses" not in ff.FEEDS
    assert "nys_sla_inactive_licenses" in ff.FEEDS


def test_sla_rename_migration_is_idempotent_and_rewrites_the_primary_key():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("""
        INSERT INTO staging.storefront_filing
            (filing_id, source, stage, match_method, raw_id, ingested_at,
             provenance)
        VALUES ('nyc_sla_liquor_licenses:liquor_active:XYZ',
                'nyc_sla_liquor_licenses', 'liquor_active', 'unmatched',
                'XYZ', now(), 'test')""")
    sql = (locidb.SQL_DIR / "042_sla_source_rename.sql").read_text()
    for _ in range(2):                       # idempotent: a second pass is a no-op
        con.execute(sql)
    got = con.execute("SELECT filing_id, source FROM staging.storefront_filing"
                      ).fetchone()
    assert got == ("nys_sla_liquor_licenses:liquor_active:XYZ",
                   "nys_sla_liquor_licenses")
    con.close()


def test_sla_inactive_normalizes_membership_as_the_status():
    """6dg3-2z7i publishes no status column: being in the file IS the status."""
    rows = [{"license_permit_id": "1", "premises_county": "Kings",
             "description": "Restaurant", "legalname": "OLD PLACE LLC",
             "dba": "Old Place", "actual_address_of_premises": "1 MAIN ST",
             "original_issue_date": "2016-03-01T00:00:00.000",
             "expiration_date": "2019-02-28T00:00:00.000",
             "georeference": {"coordinates": [-73.95, 40.70]},
             "class": 1, "type": 2}]
    monkey = ff.socrata
    orig_assert, orig_fetch = monkey.assert_fields, monkey.fetch
    monkey.assert_fields = lambda *a, **k: None
    monkey.fetch = lambda *a, **k: rows
    try:
        df = ff.fetch_sla_inactive(asof=dt.date(2026, 9, 16))
    finally:
        monkey.assert_fields, monkey.fetch = orig_assert, orig_fetch

    assert len(df) == 1
    r = df.iloc[0]
    assert r["source"] == "nys_sla_inactive_licenses"
    assert r["stage"] == "liquor_inactive"
    assert r["status"] == "Inactive"
    assert r["filed_on"] == dt.date(2016, 3, 1)      # the dated START
    assert r["status_date"] == dt.date(2019, 2, 28)  # the dated END
    assert r["borough"] == "BK"
    assert "THE CLOSURE HALF" in r["provenance"]


def test_sla_inactive_never_lands_a_silent_zero():
    """An empty closure history reads as a city where no bar ever closed."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    orig = li.__dict__.get("_noop")
    from loci.model import storefront_filing as sf
    real_assemble, real_pluto = sf.assemble, sf.build_pluto_index
    sf.assemble = lambda *a, **k: (pd.DataFrame(columns=list(ff.FEED_COLUMNS)), {})
    sf.build_pluto_index = lambda *a, **k: 0
    try:
        with pytest.raises(RuntimeError, match="empty closure history"):
            li.build_sla(con)
    finally:
        sf.assemble, sf.build_pluto_index = real_assemble, real_pluto
        del orig
    con.close()


def test_sla_inactive_vocabulary_is_closed():
    """`loci_category_of` RAISES on an undeclared licence class. The inactive
    file reaches back to 2015 and carries classes the active file has aged out
    of, so its vocabulary is a superset and every value must be declared."""
    from loci.model.storefront_pipeline import loci_category_of

    # Every distinct `description` in the NYC slice of 6dg3-2z7i, measured
    # live 2026-09-16. Pinned here so a portal that adds a class fails a test
    # rather than an ingest halfway through a write.
    observed = [
        "Restaurant", "Grocery Store", "Food & Beverage Business",
        "Liquor Store", "Drug Store", "Catering Establishment", "Hotel",
        "Wholesale Wine", "Vessel", "Wholesale Liquor", "Wholesale Beer",
        "Wholesale Beer (Retail)", "Club", "Summer Food & beverage business",
        "Wine Store", "Summer Food & Beverage Business", "Cabaret",
        "Summer Restaurant", "Importer", "Micro-Brewer", "Winter Vessel",
        "Distiller Class D (Farm Distiller)", "Brewer", "Summer Vessel",
        "Winter Food & Beverage Business", "Winery",
        "Distiller Class A-1 (Micro-distiller)", "Farm Brewer",
        "Cider Producer", "Distiller Class B-1 (Micro-rectifier)", "Aircraft",
        "Restaurant Brewer", "Summer Club", "Bottle Club", "Winter Restaurant",
        "Legitimate theatre", "Direct Shipper Wine", "Farm Cidery",
        "Winter - Tavern Miscellaneous", "Vendor", "Farm winery",
        "Tavern Miscellaneous", "Winter Legitimate Theatre",
        "Cider Producer (Manufacturer)",
        "Summer Athletic/Sporting Event/Expositions/Large Gathering Venue",
        "Distiller Class A", "Night Club",
    ]
    for value in observed:
        loci_category_of("nys_sla_inactive_licenses", value)   # must not raise
    # and the mapping is the SAME object as the active file's, by YAML anchor
    assert (loci_category_of("nys_sla_inactive_licenses", "Restaurant")
            == loci_category_of("nys_sla_liquor_licenses", "Restaurant"))


# --------------------------------------------- cap 3: Foursquare staleness

def test_stale_venues_are_retained_but_cannot_enter_supply():
    """The staleness gate stops being a data loss without becoming supply.

    Foursquare publishes no status field, so a stale venue in staging.poi
    resolves to 'unknown' -- and the closure gate is `poi_status <> 'closed'`,
    which 'unknown' SURVIVES. Retaining them in place would move the supply
    hash. They go to staging.poi_stale instead.
    """
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    cols = {c[0] for c in con.execute(
        "SELECT * FROM staging.poi_stale LIMIT 0").description}
    assert {"stale_reason", "date_refreshed", "category", "geom"} <= cols

    # analysis.poi_supply reads staging.poi BY NAME, so the stale table cannot
    # reach the supply set even by accident.
    view = con.execute(
        "SELECT sql FROM duckdb_views() WHERE view_name = 'poi_supply'"
    ).fetchone()
    assert view is not None and "poi_stale" not in view[0]
    con.close()


def test_stale_reason_vocabulary_is_constrained():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    with pytest.raises(Exception):           # noqa: B017 -- DuckDB ConstraintException
        con.execute("""
            INSERT INTO staging.poi_stale
                (poi_id, source_id, category, tier, geom, stale_reason)
            VALUES ('x', 'foursquare_os_places', 'laundry', 1,
                    ST_Point(-73.9, 40.7), 'closed')""")
    con.close()


# ------------------------------------------------------- cap 10: registry

def test_no_feed_still_declares_a_trailing_ingest_window():
    """`ingested_window: 24mo` was a clip WE cut, not one the city has. It is
    gone, and `temporal` now records what actually landed."""
    import yaml

    reg = yaml.safe_load((locidb.PKG / "registry.yaml").read_text())
    # The KEY, not the prose: several `temporal.note` strings now SAY
    # "ingested_window removed in wave one", which is the point.
    offenders = [s["id"] for s in reg["sources"]
                 if "ingested_window" in (s.get("temporal") or {})]
    assert offenders == [], offenders
