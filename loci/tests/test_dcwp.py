from loci.sources.cities.nyc.dcwp import classify, DcwpAdapter


def test_classify():
    assert classify("Laundries") == "laundry"
    assert classify("Industrial Laundry Delivery") is None  # B2B, not walkable
    assert classify("Dry Cleaning Plant") == "laundry"
    assert classify("Pharmacy - Retail") == "pharmacy"
    assert classify("Tow Truck Company") is None
    assert classify(None) is None


def test_normalize_maps_dedupes_and_drops():
    a = DcwpAdapter()
    raw = [
        # laundromat, active, in-NYC -> kept as laundry
        {"license_nbr": "L1", "business_name": "167 LAUNDRY MART INC.",
         "business_category": "Laundries", "license_status": "Active",
         "license_creation_date": "2021-09-27T00:00:00.000",
         "latitude": "40.83", "longitude": "-73.91", "address_borough": "Bronx"},
        # dry cleaner, active, in-NYC, with dba_trade_name -> kept as laundry
        {"license_nbr": "L2", "business_name": "WJS CLEANERS INC",
         "dba_trade_name": "J'S CLEANERS",
         "business_category": "Dry Cleaning Plant", "license_status": "Active",
         "license_creation_date": "2020-01-01T00:00:00.000",
         "latitude": "40.76", "longitude": "-73.96", "address_borough": "Manhattan"},
        # duplicate of L1 -> collapsed
        {"license_nbr": "L1", "business_name": "167 LAUNDRY MART INC.",
         "business_category": "Laundries", "license_status": "Active",
         "license_creation_date": "2021-09-27T00:00:00.000",
         "latitude": "40.83", "longitude": "-73.91", "address_borough": "Bronx"},
        # non-mapping category -> dropped
        {"license_nbr": "L3", "business_name": "ACME TOW",
         "business_category": "Tow Truck Company", "license_status": "Active",
         "latitude": "40.7", "longitude": "-73.9", "address_borough": "Queens"},
        # laundry category but expired license -> dropped
        {"license_nbr": "L4", "business_name": "OLD LAUNDROMAT",
         "business_category": "Laundries", "license_status": "Expired",
         "latitude": "40.7", "longitude": "-73.9", "address_borough": "Brooklyn"},
        # laundry category, active, but outside NYC -> dropped
        {"license_nbr": "L5", "business_name": "CINTAS CORP",
         "business_category": "Industrial Laundry Delivery", "license_status": "Active",
         "latitude": "40.9", "longitude": "-73.85", "address_borough": "Outside NYC"},
        # laundry category, active, in-NYC borough label, but missing coordinates -> dropped
        {"license_nbr": "L6", "business_name": "NO GEO LAUNDRY",
         "business_category": "Laundries", "license_status": "Active",
         "address_borough": "Queens"},
    ]
    recs = list(a.normalize(raw))
    ids = {r.source_record_id for r in recs}
    assert ids == {"L1", "L2"}

    by_id = {r.source_record_id: r for r in recs}
    assert by_id["L1"].category == "laundry"
    assert by_id["L2"].category == "laundry"
    assert by_id["L2"].name == "J'S Cleaners"
    assert all(r.tier == 1 for r in recs)
    assert all(r.confidence == 0.8 for r in recs)
    assert by_id["L1"].poi_id == "nyc_dcwp_licenses:L1"
    assert by_id["L1"].attrs["license_creation_date"] == "2021-09-27T00:00:00.000"


# ==========================================================================
# DCWP Inspections — the retail-laundry anchor (D55)
# ==========================================================================
import pytest

from loci import db as locidb
from loci.sources.cities.nyc import dcwp
from loci.sources.cities.nyc.dcwp import (
    KNOWN_LAUNDRY_CATEGORIES,
    DcwpInspectionsAdapter,
    UnknownLaundryCategory,
    classify_inspection,
    inspection_active_state,
)


def _insp(bid, *, cat="Retail Laundry", status="Pass", date="2025-06-01T00:00:00.000",
          lat="40.70", lon="-73.95", boro="Brooklyn", name="Sudsy Inc", **kw):
    row = {"business_unique_id": bid, "business_category": cat,
           "inspection_status": status, "date_of_occurrence": date,
           "latitude": lat, "longitude": lon, "borough": boro,
           "business_name": name, "inspection_number": f"INS-{bid}-{date}"}
    row.update(kw)
    return row


# -------------------------------------------------------------- vocabulary
def test_known_vocabulary_maps_only_walk_in_laundry():
    assert classify_inspection("Retail Laundry") == "laundry"
    assert classify_inspection("Dry Cleaners - 230") == "laundry"
    # B2B linen supply: laundry-like, explicitly mapped to None, not a gap.
    assert classify_inspection("Industrial Laundry") is None
    assert classify_inspection("Industrial Laundry Delivery") is None
    # Not laundry-like at all: silently ignored is correct here.
    assert classify_inspection("Tobacco Retail Dealer") is None
    assert classify_inspection(None) is None
    assert classify_inspection("") is None


@pytest.mark.parametrize("unseen", [
    "Coin Laundry",              # a plausible future DCWP rename
    "Retail Laundry - 231",      # the legacy-code variant
    "Self-Service Launderette",  # 'launder' stem, not 'laundr'
    "Dry Cleaning Plant",
])
def test_unseen_laundry_like_value_fails_loud(unseen):
    """VOCABULARY DRIFT. A laundry-like category DCWP has not shown before must
    RAISE, never fall through to None. A silent drop would shrink the anchor
    and manufacture exactly the supply gaps this project is looking for."""
    with pytest.raises(UnknownLaundryCategory):
        classify_inspection(unseen)


def test_normalize_propagates_the_drift_failure():
    """The guard has to survive the aggregation path, not just the classifier."""
    with pytest.raises(UnknownLaundryCategory):
        list(DcwpInspectionsAdapter().normalize([_insp("B1", cat="Coin Laundry")]))


def test_every_known_value_is_a_deliberate_decision():
    """Each frozen value maps to a real Loci category or to an explicit None."""
    from loci.categories import CATEGORIES
    for value, mapped in KNOWN_LAUNDRY_CATEGORIES.items():
        assert mapped is None or mapped in CATEGORIES, value


# ------------------------------------------------------------- active basis
def test_active_basis_reads_an_observation_not_a_proxy():
    assert inspection_active_state(["Out of Business"]) == (False, "out_of_business")
    assert inspection_active_state(["Unable to Locate"]) == (False, "unable_to_locate")
    assert inspection_active_state(["No Evidence of Activity"]) == (
        False, "no_evidence_of_activity")
    # A live outcome on the SAME date contradicts the dead marker.
    active, basis = inspection_active_state(["No Evidence of Activity", "Pass"])
    assert active and basis == "dead_marker_overridden_same_day"
    # 'Closed' reverses on half the establishments that carry it: NOT death.
    assert inspection_active_state(["Closed"])[0] is True
    assert inspection_active_state([])[0] is True


def test_active_uses_the_latest_date_only():
    """An establishment that went Out of Business in 2023 and passed in 2025 is
    ALIVE; the reverse is dead. Only the most recent inspection votes."""
    a = DcwpInspectionsAdapter()
    revived = next(iter(a.normalize([
        _insp("B1", status="Out of Business", date="2023-08-01T00:00:00.000"),
        _insp("B1", status="Pass", date="2025-06-01T00:00:00.000"),
    ])))
    assert revived.attrs["active"] is True
    assert revived.attrs["last_inspection_date"] == "2025-06-01"
    assert revived.attrs["n_inspections"] == 2

    departed = next(iter(a.normalize([
        _insp("B2", status="Pass", date="2023-08-01T00:00:00.000"),
        _insp("B2", status="Out of Business", date="2025-06-01T00:00:00.000"),
    ])))
    assert departed.attrs["active"] is False
    assert departed.attrs["active_basis"] == "out_of_business"


def test_normalize_is_one_poi_per_establishment_and_drops_the_unplaceable():
    a = DcwpInspectionsAdapter()
    recs = list(a.normalize([
        _insp("B1"), _insp("B1", date="2026-01-05T00:00:00.000"),   # collapses
        _insp("B2", cat="Industrial Laundry"),                       # B2B, dropped
        _insp("B3", lat=None, lon=None),                             # ungeocoded
        _insp("B4", lat="41.9", lon="-87.6", boro="Outside NYC"),     # not NYC
        _insp("B5", cat="Dry Cleaners - 230"),
    ]))
    assert {r.source_record_id for r in recs} == {"B1", "B5"}
    assert all(r.category == "laundry" and r.tier == 1 for r in recs)
    assert all(r.confidence == 0.9 for r in recs)
    by = {r.source_record_id: r for r in recs}
    assert by["B1"].poi_id == "nyc_dcwp_inspections:B1"
    assert by["B1"].attrs["mapping_confidence"] == "high"


# ------------------------------------------------------ pending / apply split
@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    locidb.init_schema(c)
    return c


def test_pending_table_mirrors_staging_poi(con):
    dcwp.ensure_pending_table(con)
    cols = lambda t: [(r[0], r[1]) for r in con.execute(f"DESCRIBE {t}").fetchall()]
    assert cols(dcwp.PENDING_TABLE) == cols("staging.poi")


def test_staging_never_touches_staging_poi_and_apply_promotes(con, monkeypatch):
    """THE SEQUENCING GUARANTEE. `loci ingest-dcwp` must leave staging.poi
    byte-identical; only --apply moves rows, and it must not disturb any other
    source's rows."""
    con.execute("""INSERT INTO staging.poi
        (poi_id, source_id, source_record_id, category, tier, name, geom, confidence)
        VALUES ('other:1','overture_places','1','laundry',1,'Existing',
                ST_Point(-73.99, 40.73), 0.5)""")

    rows = [_insp("B1"), _insp("B2", status="Out of Business")]
    monkeypatch.setattr(DcwpInspectionsAdapter, "fetch",
                        lambda self, *, limit=None: iter(rows))

    recs = dcwp.stage_pending(con)
    assert len(recs) == 2
    # staging.poi untouched by the ingest.
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 1
    assert con.execute(
        "SELECT count(*) FROM staging.poi WHERE source_id='nyc_dcwp_inspections'"
    ).fetchone()[0] == 0
    assert con.execute(
        f"SELECT count(*) FROM {dcwp.PENDING_TABLE}").fetchone()[0] == 2

    # re-staging is idempotent, not additive.
    dcwp.stage_pending(con)
    assert con.execute(
        f"SELECT count(*) FROM {dcwp.PENDING_TABLE}").fetchone()[0] == 2

    deleted, inserted = dcwp.apply_pending(con)
    assert (deleted, inserted) == (0, 2)
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 3
    # the pre-existing source survived promotion untouched.
    assert con.execute(
        "SELECT name FROM staging.poi WHERE poi_id='other:1'").fetchone()[0] == "Existing"
    # geometry landed as (lon, lat), EPSG:4326 by convention -- not flipped.
    x, y = con.execute("""SELECT ST_X(geom), ST_Y(geom) FROM staging.poi
                          WHERE poi_id='nyc_dcwp_inspections:B1'""").fetchone()
    assert -74.3 < x < -73.6 and 40.4 < y < 41.0

    # apply is idempotent: a second promotion replaces, never doubles.
    deleted, inserted = dcwp.apply_pending(con)
    assert (deleted, inserted) == (2, 2)
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 3


def test_fetch_raises_rather_than_ingesting_a_silent_zero(monkeypatch):
    """An empty live feed is a failure, not an observation that NYC has no
    laundromats."""
    import requests

    class _Empty:
        def raise_for_status(self): pass
        def json(self): return []

    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: _Empty())
    with pytest.raises(RuntimeError, match="Refusing to ingest an empty"):
        list(DcwpInspectionsAdapter().fetch())
