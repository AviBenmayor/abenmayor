"""The DOHMH child-care anchor (D65).

Shaped after tests/test_dcwp.py: the same pending/apply sequencing guarantee,
the same fail-loud-on-empty rule, plus the two things that are specific to this
source -- the closed facility_type vocabulary (a new regulatory universe must
be a decision, not a silent ingest) and the ACTIVE-at-source contract.
"""
from __future__ import annotations

import pytest

from loci import db as locidb
from loci.score.dedup import source_rank
from loci.sources.cities.nyc import dohmh_childcare as ccare
from loci.sources.cities.nyc.dohmh_childcare import (
    DohmhChildcareAdapter,
    UnknownFacilityType,
    facility_included,
)


def _row(dcid="DC1", name="LITTLE ACORNS DAY CARE", facility="GCC",
         lat="40.6899", lon="-73.9601", **kw):
    r = {"dcid": dcid, "program_name": name, "facility_type": facility,
         "program_type": "PRESCHOOL", "address": "333 CLASSON AVENUE",
         "borough": "BROOKLYN", "zipcode": "11205", "age_range": "2 YEARS - 5 YEARS",
         "capacity": "70", "bin": "3321871", "bbl": "3019380001",
         "nta_code": "BK75", "census_tract": "023300", "community_board": "303",
         "permit_number": "2165", "latitude": lat, "longitude": lon}
    r.update(kw)
    return r


# ---------------------------------------------------------------- vocabulary

def test_both_published_universes_are_kept_and_the_choice_is_explicit():
    """GCC (Health Code Article 47 group child care) and SBCC (Article 43
    school-based) are both real walkable childcare destinations. SBCC is the
    half that carries yeshiva and parochial-school pre-K, which is precisely
    the supply D64 suspected the aggregators were missing in Borough Park, so
    dropping it would beg the question the anchor exists to answer."""
    assert ccare.KNOWN_FACILITY_TYPES == {"GCC": True, "SBCC": True}
    assert facility_included("GCC") is True
    assert facility_included("SBCC") is True
    assert facility_included("gcc") is True          # case-folded
    # A blank field is a blank field, not a new universe: the row is still an
    # active permitted program in this file.
    assert facility_included("") is True
    assert facility_included(None) is True


@pytest.mark.parametrize("unseen", ["FDC", "GFDC", "SACC", "OCFS-HOME"])
def test_an_unpublished_facility_type_fails_loud(unseen):
    """The one change that would most alter what this anchor MEANS is DOHMH
    starting to publish home-based (OCFS) care here. It must raise, not fall
    through: silently keeping it would inflate supply, silently dropping it
    would manufacture gaps, and either way nobody would know the universe had
    changed."""
    with pytest.raises(UnknownFacilityType, match="KNOWN_FACILITY_TYPES"):
        facility_included(unseen)


def test_normalize_propagates_the_vocabulary_failure():
    with pytest.raises(UnknownFacilityType):
        list(DohmhChildcareAdapter().normalize([_row(facility="GFDC")]))


# ----------------------------------------------------------------- normalize

def test_normalize_emits_one_poi_per_program_and_drops_the_unplaceable():
    """One POIRecord per `dcid`. The programme -> storefront collapse is left
    to score/dedup.py's shared 40 m + name rule rather than duplicated here,
    so `dcid` stays recoverable in analysis.poi_dedup as a survivorship
    record. A row with no coordinates cannot be placed and is dropped -- it is
    not geocoded from the address string, because a guessed point in a
    walk-distance screen is worse than a missing one."""
    rows = [
        _row("DC1"),
        # same centre, second programme, same door -> still its own record here
        _row("DC2", name="LITTLE ACORNS DAY CARE", **{"program_type": "INFANT TODDLER"}),
        _row("DC1"),                                   # exact duplicate id -> collapsed
        _row("DC3", lat=None, lon=None),               # ungeocoded -> dropped
        _row("DC4", lat="40.6899", lon="-71.0"),       # outside the NYC bbox -> dropped
    ]
    recs = list(DohmhChildcareAdapter().normalize(rows))
    assert [r.source_record_id for r in recs] == ["DC1", "DC2"]
    assert {r.category for r in recs} == {"childcare"}
    assert recs[0].poi_id == "nyc_dohmh_childcare:DC1"
    assert recs[0].name == "Little Acorns Day Care"
    # geometry is (lon, lat), EPSG:4326 by convention -- never flipped
    assert -74.3 < recs[0].lon < -73.6 and 40.4 < recs[0].lat < 41.0


def test_active_is_an_observation_at_source_not_a_staleness_proxy():
    """Unlike DOHMH restaurants (D36/D47), this feed needs no "not inspected in
    N months" inference: the publisher excludes preliminary, suspended and
    closed programmes, so presence IS the active observation. The basis is
    recorded in words so the assumption is visible in the data, and the attrs
    contract matches dohmh.py / dcwp.py."""
    (rec,) = list(DohmhChildcareAdapter().normalize([_row()]))
    assert rec.attrs["active"] is True
    assert rec.attrs["active_basis"] == "published_active_roster"
    assert rec.attrs["mapping_confidence"] == "high"
    assert rec.attrs["borough"] == "BK"
    assert rec.attrs["facility_type"] == "GCC"
    assert rec.confidence == 0.95


# ------------------------------------------------------------ canonical rank

def test_the_anchor_outranks_the_aggregators_for_childcare():
    """Without an explicit branch in source_rank the new source falls through
    to the aggregator tail and scores WORSE than Overture, so an aggregator's
    name and geometry would survive as canonical for a cluster the registry
    anchors -- the opposite of what source authority is for."""
    assert source_rank("childcare", "nyc_dohmh_childcare") == 0
    assert source_rank("childcare", "nyc_dohmh_childcare") < \
        source_rank("childcare", "overture_places")
    assert source_rank("childcare", "nyc_dohmh_childcare") < \
        source_rank("childcare", "foursquare_os_places")
    # and it changes nothing for any other category's anchor
    assert source_rank("restaurant", "nyc_dohmh_restaurants") == 0
    assert source_rank("bar", "nys_sla_liquor_licenses") == 0


# ------------------------------------------------------ pending / apply split

@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    locidb.init_schema(c)
    return c


def test_pending_table_mirrors_staging_poi(con):
    ccare.ensure_pending_table(con)
    def cols(t):
        return [(r[0], r[1]) for r in con.execute(f"DESCRIBE {t}").fetchall()]
    assert cols(ccare.PENDING_TABLE) == cols("staging.poi")


def test_staging_never_touches_staging_poi_and_apply_promotes(con, monkeypatch):
    """THE SEQUENCING GUARANTEE (same as DCWP's): the ingest must leave
    staging.poi byte-identical so it cannot race `loci dedup` reading the
    supply universe; only --apply moves rows, and it must not disturb any
    other source's."""
    con.execute("""INSERT INTO staging.poi
        (poi_id, source_id, source_record_id, category, tier, name, geom, confidence)
        VALUES ('other:1','overture_places','1','childcare',3,'Existing',
                ST_Point(-73.99, 40.73), 0.5)""")
    monkeypatch.setattr(DohmhChildcareAdapter, "fetch",
                        lambda self, *, limit=None: iter([_row("DC1"), _row("DC2")]))

    recs = ccare.stage_pending(con)
    assert len(recs) == 2
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 1
    assert con.execute(
        "SELECT count(*) FROM staging.poi WHERE source_id='nyc_dohmh_childcare'"
    ).fetchone()[0] == 0
    assert con.execute(f"SELECT count(*) FROM {ccare.PENDING_TABLE}").fetchone()[0] == 2

    # re-staging is idempotent, not additive
    ccare.stage_pending(con)
    assert con.execute(f"SELECT count(*) FROM {ccare.PENDING_TABLE}").fetchone()[0] == 2

    deleted, inserted = ccare.apply_pending(con)
    assert (deleted, inserted) == (0, 2)
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 3
    assert con.execute(
        "SELECT name FROM staging.poi WHERE poi_id='other:1'").fetchone()[0] == "Existing"
    x, y = con.execute("""SELECT ST_X(geom), ST_Y(geom) FROM staging.poi
                          WHERE poi_id='nyc_dohmh_childcare:DC1'""").fetchone()
    assert -74.3 < x < -73.6 and 40.4 < y < 41.0

    # apply is idempotent: a second promotion replaces, never doubles
    assert ccare.apply_pending(con) == (2, 2)
    assert con.execute("SELECT count(*) FROM staging.poi").fetchone()[0] == 3


def test_fetch_raises_rather_than_ingesting_a_silent_zero(monkeypatch):
    """An empty live feed is a failure, not an observation that NYC has no
    child care. This source anchors the category, so a silent zero would
    delete the anchor and hand every childcare gap back to the aggregators
    without anyone noticing."""
    import requests

    class _Empty:
        def raise_for_status(self): pass
        def json(self): return []

    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: _Empty())
    with pytest.raises(RuntimeError, match="Refusing to ingest an empty"):
        list(DohmhChildcareAdapter().fetch())
