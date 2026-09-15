"""geo/geosearch.py -- NYC Planning Labs GeoSearch, snapped to the Loci
address frame (D99, GTM-171, AC-14/15 BACKEND ONLY -- the search box and the
"not in Loci coverage" toast are webmap/index.html's job, out of scope for
this build; these tests pin `geocode()`, `snap()` and `resolve()` against a
fake HTTP session and a synthetic warehouse, with NO real network call.
"""
from __future__ import annotations

import pytest

from loci.db import connect, init_schema
from loci.geo.geosearch import GeoHit, NotInCoverage, geocode, resolve, snap

_ADDR_COLS = ("address_id, bbl, lon, lat, borough, neighborhood, present_count, "
             "eligible, n_missing, reach_source, reach_hash, graph_version, run_at")


def _addr(con, address_id, bbl, lon, lat, borough="BK", neighborhood="Testville"):
    con.execute(
        f"INSERT INTO analysis.address ({_ADDR_COLS}) VALUES "
        "(?, ?, ?, ?, ?, ?, 0, TRUE, 0, 'tiers', 'h', 'g', now())",
        [address_id, bbl, lon, lat, borough, neighborhood])


@pytest.fixture()
def db():
    con = connect(":memory:")
    init_schema(con)
    # Richardson St, BK -- matches the AC-13 warehouse landmark for this build.
    _addr(con, "a-richardson-61", "3028980001", -73.9440, 40.7140)
    _addr(con, "a-other", "3028980002", -73.9500, 40.7200)
    return con


# ---------------------------------------------------------------- geocode()


class _FakeResp:
    def __init__(self, body):
        self._body = body
    def raise_for_status(self): pass
    def json(self): return self._body


class _FakeSession:
    def __init__(self, body):
        self.body = body
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return _FakeResp(self.body)


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _feature(lon, lat, label="61 Richardson Street, Brooklyn, NY", bbl="3028980001"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
           "properties": {"label": label, "addendum": {"pad": {"bbl": bbl}}}}


def test_geocode_returns_none_on_no_features():
    sess = _FakeSession(_fc([]))
    assert geocode("nowhere at all", session=sess) is None


def test_geocode_returns_a_geohit_with_bbl():
    sess = _FakeSession(_fc([_feature(-73.9440, 40.7140)]))
    hit = geocode("61 Richardson St", session=sess)
    assert hit == GeoHit(label="61 Richardson Street, Brooklyn, NY",
                         lat=40.7140, lon=-73.9440, bbl="3028980001")
    assert sess.calls[0][1]["text"] == "61 Richardson St"


def test_geocode_handles_a_hit_with_no_bbl():
    feat = _feature(-73.95, 40.72, label="Somewhere, NY", bbl=None)
    sess = _FakeSession(_fc([feat]))
    hit = geocode("somewhere", session=sess)
    assert hit.bbl is None


def test_geocode_blank_query_short_circuits_with_no_call():
    sess = _FakeSession(_fc([]))
    assert geocode("   ", session=sess) is None
    assert sess.calls == []


# -------------------------------------------------------------------- snap()


def test_snap_matches_on_bbl_first(db):
    hit = GeoHit(label="x", lat=0.0, lon=0.0, bbl="3028980001")   # wrong coords, right bbl
    assert snap(db, hit) == "a-richardson-61"


def test_snap_falls_back_to_nearest_within_50m_when_bbl_absent(db):
    hit = GeoHit(label="x", lat=40.71401, lon=-73.94401, bbl=None)   # ~1-2 m from a-richardson-61
    assert snap(db, hit) == "a-richardson-61"


def test_snap_falls_back_to_nearest_when_bbl_does_not_match_any_row(db):
    hit = GeoHit(label="x", lat=40.71401, lon=-73.94401, bbl="9999999999")
    assert snap(db, hit) == "a-richardson-61"


def test_snap_refuses_beyond_50m():
    """AC-15's backend half: an address genuinely outside the Loci
    universe -- e.g. Staten Island, borough SI never loaded -- must refuse,
    never silently return the closest thing in a different borough."""
    con = connect(":memory:")
    init_schema(con)
    _addr(con, "a-far", "1000000001", -73.9440, 40.7140)   # BK
    staten_island = GeoHit(label="Staten Island, NY", lat=40.5795, lon=-74.1502, bbl=None)
    with pytest.raises(NotInCoverage, match="not in Loci coverage"):
        snap(con, staten_island)


# ----------------------------------------------------------------- resolve()


def test_resolve_is_a_passthrough_for_an_existing_address_id(db):
    class _ExplodingSession:
        def get(self, *a, **kw):
            raise AssertionError("resolve() must not geocode an address_id it already has")
    assert resolve(db, "a-richardson-61", session=_ExplodingSession()) == "a-richardson-61"


def test_resolve_geocodes_and_snaps_an_unrecognized_query(db):
    sess = _FakeSession(_fc([_feature(-73.9440, 40.7140)]))
    assert resolve(db, "61 Richardson St", session=sess) == "a-richardson-61"


def test_resolve_refuses_out_of_coverage_query(db):
    """AC-15: an out-of-universe address is refused, never a degraded report."""
    sess = _FakeSession(_fc([_feature(-74.1502, 40.5795, label="Staten Island, NY", bbl=None)]))
    with pytest.raises(NotInCoverage, match="not in Loci coverage"):
        resolve(db, "somewhere on Staten Island", session=sess)


def test_resolve_refuses_when_geosearch_finds_nothing(db):
    sess = _FakeSession(_fc([]))
    with pytest.raises(NotInCoverage):
        resolve(db, "asdkfjhalskdjfh not an address", session=sess)
