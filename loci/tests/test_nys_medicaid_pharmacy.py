"""The NYS Medicaid retail-pharmacy anchor.

Shaped after tests/test_dohmh_childcare.py: the same pending/apply sequencing
guarantee, the same fail-loud-on-empty rule, the same closed-vocabulary rule —
plus the two things specific to THIS source and found by probing it:

  * `mmis_id` is per-PROVIDER, not per-storefront, so the record key is
    composite. Keying on mmis_id alone silently deletes a real second location,
    which in a "which addresses have no pharmacy nearby" screen is a
    manufactured gap.
  * eight rows carry a (0, 0) null-island coordinate from a failed State
    geocode and must be dropped explicitly, never ingested and never guessed.
"""
from __future__ import annotations

import pytest

from loci import db as locidb
from loci.score.dedup import source_rank
from loci.sources.cities.nyc import nys_medicaid_pharmacy as rx
from loci.sources.cities.nyc.nys_medicaid_pharmacy import (
    KNOWN_SERVICES,
    NysMedicaidPharmacyAdapter,
    UnknownPharmacyService,
    record_key,
    service_included,
)


def _row(mmis="00259036", name="MIL RUE CHEMISTS INC", service="PHARMACY",
         address="6687 FRESH POND RD", lat="040.706600", lon="-073.896570",
         county="QUEENS", **kw):
    r = {"mmis_id": mmis, "npi": "1871581298", "mmis_name": name,
         "medicaid_type": "FFS", "profession_or_service": service,
         "service_address": address, "city": "RIDGEWOOD", "state": "NY",
         "zip_code": "11385-3948", "county": county, "latitude": lat,
         "longitude": lon, "enrollment_begin_date": "1978-04-01T00:00:00.000",
         "updated": "2026-09-07T00:00:00.000"}
    r.update(kw)
    return r


# ---------------------------------------------------------------- vocabulary

def test_only_retail_pharmacy_counts_and_every_exclusion_is_explicit():
    """The four exclusions are the whole reason this file needs a vocabulary.
    SUPERVISING PHARMACIST is an INDIVIDUAL enrolment (2,911 NYC rows) and
    would put a second point on top of nearly every store — the booth-renter
    failure in a source with no booth-renter pass. HOSPITAL / CLINIC /
    SPECIALTY are institutional or mail-order: counting them would close
    walk-to-a-pharmacy gaps that are real."""
    assert KNOWN_SERVICES == {
        "PHARMACY": True,
        "HOSPITAL PHARMACY": False,
        "CLINIC PHARMACY": False,
        "SPECIALTY PHARMACY": False,
        "SUPERVISING PHARMACIST": False,
    }
    assert service_included("PHARMACY") is True
    assert service_included("pharmacy") is True            # case-folded
    assert service_included("  Pharmacy  ") is True        # whitespace-folded
    for excluded in ("HOSPITAL PHARMACY", "CLINIC PHARMACY",
                     "SPECIALTY PHARMACY", "SUPERVISING PHARMACIST"):
        assert service_included(excluded) is False


@pytest.mark.parametrize("unseen", ["MAIL ORDER PHARMACY", "NUCLEAR PHARMACY",
                                    "DRUG STORE", "", None])
def test_an_unpublished_service_category_fails_loud(unseen):
    """Unlike dohmh_childcare's facility_type, a BLANK is NOT waved through:
    there the field only said which regulatory article a child care programme
    sat under, here it is the only thing separating a storefront from a
    hospital dispensary and from an individual pharmacist."""
    with pytest.raises(UnknownPharmacyService, match="KNOWN_SERVICES"):
        service_included(unseen)


def test_normalize_propagates_the_vocabulary_failure():
    with pytest.raises(UnknownPharmacyService):
        list(NysMedicaidPharmacyAdapter().normalize([_row(service="MAIL ORDER PHARMACY")]))


# ---------------------------------------------------------- the composite key

def test_one_provider_id_can_hold_two_real_storefronts():
    """THE BUG THIS KEY EXISTS TO PREVENT. Medicaid provider 03574081 (IDEAL
    CARE PHARMACY INC) enrols 1621 Avenue U and 811 Avenue U, two real
    storefronts ~670 m apart. Keying on mmis_id alone drops one of them, and a
    deleted business in this screen is a manufactured gap."""
    rows = [
        _row("03574081", "IDEAL CARE PHARMACY INC", address="1621 AVENUE U",
             lat="040.599070", lon="-073.955020", county="KINGS"),
        _row("03574081", "IDEAL CARE PHARMACY INC", address="811 AVENUE U",
             lat="040.598210", lon="-073.962860", county="KINGS"),
    ]
    recs = list(NysMedicaidPharmacyAdapter().normalize(rows))
    assert len(recs) == 2
    assert [r.source_record_id for r in recs] == [
        "03574081@1621-AVENUE-U", "03574081@811-AVENUE-U"]
    assert recs[0].poi_id == "nys_medicaid_pharmacies:03574081@1621-AVENUE-U"
    # ...and the key is still collision-free within one provider+address
    assert record_key("03574081", "1621 Avenue U") == "03574081@1621-AVENUE-U"
    assert record_key("03574081", None) == "03574081"


def test_an_exact_repeat_of_one_enrolment_is_collapsed():
    recs = list(NysMedicaidPharmacyAdapter().normalize([_row(), _row()]))
    assert len(recs) == 1


# ----------------------------------------------------------------- normalize

def test_null_island_is_dropped_and_counted_never_ingested_or_guessed():
    """Eight live rows carry latitude/longitude "000.000000". A point in the
    Gulf of Guinea is a silent corruption no downstream check would catch, and
    geocoding the address string instead would put a GUESSED point into a
    walk-distance screen, which is worse than a missing one. The drop is
    counted so it cannot become invisible."""
    ad = NysMedicaidPharmacyAdapter()
    recs = list(ad.normalize([
        _row("A", address="A ST"),
        _row("B", address="B ST", lat="000.000000", lon="000.000000"),
        _row("C", address="C ST", lat=None, lon=None),
        _row("D", address="D ST", lat="040.689900", lon="-071.000000"),  # off-bbox
        _row("E", address="E ST", lat="not-a-number", lon="-073.9"),
    ]))
    assert [r.source_record_id for r in recs] == ["A@A-ST"]
    assert ad.dropped == {"null_island": 1, "no_coordinates": 1,
                          "outside_nyc_bbox": 1, "unparseable_coordinates": 1}


def test_geometry_is_lon_lat_4326_and_the_leading_zero_format_parses():
    """The State writes latitude as "040.706600". EPSG:4326 by convention —
    DuckDB GEOMETRY carries no SRID — and lon/lat must never be flipped."""
    (rec,) = list(NysMedicaidPharmacyAdapter().normalize([_row()]))
    assert rec.lat == pytest.approx(40.7066)
    assert rec.lon == pytest.approx(-73.89657)
    assert -74.3 < rec.lon < -73.6 and 40.4 < rec.lat < 41.0


def test_active_is_an_observation_at_source_not_a_staleness_proxy():
    """Like DOHMH childcare (D65) and unlike DOHMH restaurants (D36/D47), this
    feed needs no "not inspected in N months" inference: the publisher's file
    IS the active roster. The basis is recorded in words so the assumption is
    visible in the data, and the attrs contract matches dohmh.py / dcwp.py."""
    (rec,) = list(NysMedicaidPharmacyAdapter().normalize([_row()]))
    assert rec.category == "pharmacy"
    assert rec.name == "Mil Rue Chemists Inc"
    assert rec.attrs["active"] is True
    assert rec.attrs["active_basis"] == "published_active_medicaid_ffs_roster"
    assert rec.attrs["mapping_confidence"] == "high"
    assert rec.attrs["borough"] == "QN"
    assert rec.attrs["zip"] == "11385"          # ZIP+4 truncated to ZIP5
    assert rec.attrs["profession_or_service"] == "PHARMACY"
    # the join key to NPPES, which is the route to the trade name that would
    # fix the legal-name dedup miss (see the module docstring)
    assert rec.attrs["npi"] == "1871581298"
    assert rec.confidence == 0.95


@pytest.mark.parametrize("county,abbr", [
    ("NEW YORK", "MN"), ("KINGS", "BK"), ("QUEENS", "QN"),
    ("BRONX", "BX"), ("RICHMOND", "SI"),
])
def test_counties_map_to_the_borough_codes_the_project_reports(county, abbr):
    (rec,) = list(NysMedicaidPharmacyAdapter().normalize([_row(county=county)]))
    assert rec.attrs["borough"] == abbr


# ------------------------------------------------------------ canonical rank

def test_the_anchor_outranks_the_aggregators_for_pharmacy():
    """Without an explicit branch in source_rank the new source falls through
    to the aggregator tail and scores WORSE than Overture, so an aggregator's
    name and geometry would survive as canonical for a cluster the registry
    anchors — the opposite of what source authority is for (the D65 trap)."""
    assert source_rank("pharmacy", "nys_medicaid_pharmacies") == 0
    assert source_rank("pharmacy", "nys_medicaid_pharmacies") < \
        source_rank("pharmacy", "overture_places")
    assert source_rank("pharmacy", "nys_medicaid_pharmacies") < \
        source_rank("pharmacy", "foursquare_os_places")
    # and it changes nothing for any other category's anchor
    assert source_rank("restaurant", "nyc_dohmh_restaurants") == 0
    assert source_rank("bar", "nys_sla_liquor_licenses") == 0
    assert source_rank("childcare", "nyc_dohmh_childcare") == 0
    # the pharmacy roster has no authority outside its own category
    assert source_rank("restaurant", "nys_medicaid_pharmacies") == \
        source_rank("restaurant", "some_unknown_source")


# ------------------------------------------------------------- registry entry

def test_the_registry_records_the_source_as_verified_with_its_dataset_id():
    """D65's dead-dataset trap in reverse: the planned NYSED entry is now
    marked EXCLUDED with the probe result, so a later session cannot re-plan
    against a bulk file that does not exist."""
    from loci import registry as reg_mod

    by_id = {s["id"]: s for s in reg_mod.load()["sources"]}
    rx_entry = by_id["nys_medicaid_pharmacies"]
    assert rx_entry["status"] == "verified"
    assert rx_entry["dataset_id"] == "keti-qx5t"
    assert rx_entry["role"] == "poi"
    assert by_id["nys_pharmacy_registrations"]["status"] == "excluded"


# ------------------------------------------------------ pending / apply split

@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    locidb.init_schema(c)
    return c


def test_pending_table_mirrors_staging_poi(con):
    rx.ensure_pending_table(con)
    def cols(t):
        return [(r[0], r[1]) for r in con.execute(f"DESCRIBE {t}").fetchall()]
    assert cols(rx.PENDING_TABLE) == cols("staging.poi")


def test_staging_never_touches_staging_poi_and_apply_promotes(con, monkeypatch):
    """THE SEQUENCING GUARANTEE (same as DCWP's and childcare's): the ingest
    must leave staging.poi byte-identical so it cannot race `loci dedup`
    reading the supply universe; only --apply moves rows, and it must not
    disturb any other source's."""
    con.execute("""INSERT INTO staging.poi
        (poi_id, source_id, source_record_id, category, tier, name, geom, confidence)
        VALUES ('other:1','overture_places','1','pharmacy',2,'Existing',
                ST_Point(-73.99, 40.73), 0.5)""")
    monkeypatch.setattr(NysMedicaidPharmacyAdapter, "fetch",
                        lambda self, *, limit=None: iter(
                            [_row("A", address="A ST"), _row("B", address="B ST")]))

    recs, dropped = rx.stage_pending(con)
    assert len(recs) == 2 and dropped == {}
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 1
    assert con.execute(
        "SELECT count(*) FROM staging.poi WHERE source_id='nys_medicaid_pharmacies'"
    ).fetchone()[0] == 0
    assert con.execute(f"SELECT count(*) FROM {rx.PENDING_TABLE}").fetchone()[0] == 2

    # re-staging is idempotent, not additive
    rx.stage_pending(con)
    assert con.execute(f"SELECT count(*) FROM {rx.PENDING_TABLE}").fetchone()[0] == 2

    deleted, inserted = rx.apply_pending(con)
    assert (deleted, inserted) == (0, 2)
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 3
    assert con.execute(
        "SELECT name FROM staging.poi WHERE poi_id='other:1'").fetchone()[0] == "Existing"
    x, y = con.execute("""SELECT ST_X(geom), ST_Y(geom) FROM staging.poi
                          WHERE poi_id='nys_medicaid_pharmacies:A@A-ST'""").fetchone()
    assert -74.3 < x < -73.6 and 40.4 < y < 41.0

    # apply is idempotent: a second promotion replaces, never doubles
    assert rx.apply_pending(con) == (2, 2)
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 3


def test_fetch_raises_rather_than_ingesting_a_silent_zero(monkeypatch):
    """An empty live feed is a failure, not an observation that NYC has no
    pharmacies. This source anchors the category, so a silent zero would delete
    the anchor, hand every pharmacy gap back to the aggregators, AND (via D52)
    stop vetoing the lone-aggregator records the anchor exists to veto — all
    without anyone noticing."""
    import requests

    class _Empty:
        def raise_for_status(self): pass
        def json(self): return []

    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: _Empty())
    with pytest.raises(RuntimeError, match="Refusing to ingest an empty"):
        list(NysMedicaidPharmacyAdapter().fetch())


def test_fetch_asks_only_for_nyc_and_only_for_pharm_categories(monkeypatch):
    """The vocabulary check can only fire on rows that arrive, so the source
    filter must be a SUBSTRING, not an enumeration of the five known values —
    otherwise a new enrolment category is filtered away upstream where nobody
    would ever see it."""
    seen: dict = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return []

    def _get(self, url, params=None, headers=None, timeout=None):
        seen.update(params or {})
        return _Resp()

    import requests
    monkeypatch.setattr(requests.Session, "get", _get)
    with pytest.raises(RuntimeError):
        list(NysMedicaidPharmacyAdapter().fetch())
    where = seen["$where"]
    assert "like '%PHARM%'" in where
    for county in ("KINGS", "QUEENS", "NEW YORK", "BRONX", "RICHMOND"):
        assert f"'{county}'" in where
    # deterministic paging, and a deterministic tie-break for the composite key
    assert seen["$order"] == "mmis_id, service_address, profession_or_service"
