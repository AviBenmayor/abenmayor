import pytest
from loci.validation.google_places import (
    GooglePlacesClient, BudgetExhausted, GOOGLE_TYPES, NearbyResult, MAX_RESULT_COUNT,
)
from loci.categories import CATEGORIES


def test_every_category_has_google_types_except_the_known_unmapped_ones():
    """clinic has no usable Google Places mapping (GTM-105 #7 / D30:
    doctor/medical_lab measure a different universe than the 621111/621493
    anchor) and is deliberately excluded from GOOGLE_TYPES."""
    unmapped = {"clinic"}
    assert set(GOOGLE_TYPES) == set(CATEGORIES) - unmapped
    assert not (set(GOOGLE_TYPES) & unmapped)


def test_no_category_exceeds_included_primary_types_cap():
    """includedPrimaryTypes accepts at most 50 entries per request (GTM-105
    finding E) -- restaurant's cuisine family is the one at risk of this."""
    for cat, types in GOOGLE_TYPES.items():
        assert len(types) <= 50, f"{cat} has {len(types)} types, exceeds the 50-type cap"


def test_refuses_without_budget(tmp_path):
    c = GooglePlacesClient(api_key="k", budget=0, ledger_path=tmp_path / "l.json")
    with pytest.raises(BudgetExhausted):
        c.nearby_count(40.7, -73.9, "hardware")


class _FakeResp:
    def __init__(self, places):
        self._places = places
    def raise_for_status(self): pass
    def json(self): return {"places": self._places}


class _FakeSession:
    def __init__(self, places):
        self.n = 0
        self.last_body = None
        self._places = places
    def post(self, url, json=None, timeout=None, headers=None):
        self.n += 1
        self.last_body = json
        return _FakeResp(self._places)


def _places(n, primary_type="hardware_store"):
    return [{"id": str(i), "primaryType": primary_type, "types": [primary_type, "store"]}
            for i in range(n)]


def test_budget_is_enforced_and_persisted(tmp_path):
    sess = _FakeSession(_places(2))
    ledger = tmp_path / "l.json"
    c = GooglePlacesClient(api_key="k", budget=2, ledger_path=ledger, session=sess)
    assert c.nearby_count(40.7, -73.9, "hardware").count == 2
    assert c.nearby_count(40.7, -73.9, "fitness").count == 2
    with pytest.raises(BudgetExhausted):
        c.nearby_count(40.7, -73.9, "bank")
    assert sess.n == 2
    # a fresh client reads the ledger, so the cap survives restarts
    c2 = GooglePlacesClient(api_key="k", budget=2, ledger_path=ledger, session=sess)
    assert c2.calls_used == 2 and c2.calls_left == 0


def test_nearby_count_returns_structured_result_below_cap(tmp_path):
    sess = _FakeSession(_places(5))
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    result = c.nearby_count(40.7, -73.9, "hardware")
    assert isinstance(result, NearbyResult)
    assert result.count == 5
    assert result.at_cap is False


def test_nearby_count_flags_at_cap_at_twenty(tmp_path):
    sess = _FakeSession(_places(MAX_RESULT_COUNT))
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    result = c.nearby_count(40.7, -73.9, "fitness")
    assert result.count == MAX_RESULT_COUNT
    assert result.at_cap is True


def test_nearby_count_persists_primary_type_per_place(tmp_path):
    places = [{"id": "a", "primaryType": "gym", "types": ["gym", "health"]},
              {"id": "b", "primaryType": "fitness_center", "types": ["fitness_center"]},
              {"id": "c", "primaryType": "gym", "types": ["gym"]}]
    sess = _FakeSession(places)
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    result = c.nearby_count(40.7, -73.9, "fitness")
    assert result.places == [
        ("gym", ["gym", "health"]),
        ("fitness_center", ["fitness_center"]),
        ("gym", ["gym"]),
    ]


def test_nearby_count_request_uses_included_primary_types(tmp_path):
    """GTM-105 finding A: includedPrimaryTypes, not includedTypes — loci's
    categories are single-label per place, so any-type matching double
    counts a place across every category one of its secondary types hits."""
    sess = _FakeSession(_places(1))
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    c.nearby_count(40.7, -73.9, "hardware")
    assert "includedTypes" not in sess.last_body
    assert sess.last_body["includedPrimaryTypes"] == GOOGLE_TYPES["hardware"]


def test_metres_expression_uses_correct_axis_order():
    """1° of longitude at 40.7N is ~84.4 km; the unflipped call returns 111 km."""
    import duckdb
    from loci.validation.sample import METRES
    con = duckdb.connect(); con.execute("INSTALL spatial; LOAD spatial;")
    d = con.execute(f"select {METRES.format(a='ST_Point(-73.9, 40.7)', b='ST_Point(-72.9, 40.7)')}").fetchone()[0]
    assert 84_000 < d < 85_000


# =========================================================================
# place_status -- closure evidence (D98, GTM-170, AC-10). Text Search (New),
# NOT Nearby Search; same _FakeSession/_FakeResp pattern (session.post is
# endpoint-agnostic), shaped like a Text Search `places[]` response instead
# of Nearby Search's.
# =========================================================================
from loci.validation.google_places import (
    PLACES_TEXT_SEARCH_USD, PLACE_STATUS_RADIUS_M, TEXT_SEARCH_FIELD_MASK,
)
from loci.evidence.verify import PlaceStatus, PLACES_TEXT_SEARCH_USD as VERIFY_PLACES_USD


def _text_place(place_id="p1", name="Windclimb", lat=40.7140, lon=-73.9440,
                status="CLOSED_PERMANENTLY"):
    return {"id": place_id, "displayName": {"text": name},
           "location": {"latitude": lat, "longitude": lon}, "businessStatus": status}


def test_place_status_closed_permanently(tmp_path):
    sess = _FakeSession([_text_place(status="CLOSED_PERMANENTLY")])
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    result = c.place_status("Windclimb", 40.7140, -73.9440)
    assert isinstance(result, PlaceStatus)
    assert result.verdict == "closed"
    assert result.place_id == "p1"


def test_place_status_operational_is_open(tmp_path):
    sess = _FakeSession([_text_place(status="OPERATIONAL")])
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    assert c.place_status("Windclimb", 40.7140, -73.9440).verdict == "open"


def test_place_status_closed_temporarily_is_inconclusive(tmp_path):
    sess = _FakeSession([_text_place(status="CLOSED_TEMPORARILY")])
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    result = c.place_status("Windclimb", 40.7140, -73.9440)
    assert result.verdict is None
    assert result.place_id == "p1"       # still returned for provenance/debugging


def test_place_status_no_result_is_none(tmp_path):
    sess = _FakeSession([])
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    result = c.place_status("Windclimb", 40.7140, -73.9440)
    assert result.verdict is None
    assert result.place_id is None


def test_place_status_name_mismatch_is_none(tmp_path):
    """A different business at roughly the same spot must never be read as
    this POI's status."""
    sess = _FakeSession([_text_place(name="Totally Different Cafe")])
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    assert c.place_status("Windclimb", 40.7140, -73.9440).verdict is None


def test_place_status_too_far_is_none(tmp_path):
    """Right name, wrong place -- a chain's OTHER branch a few blocks away
    must not be read as this location's status."""
    far_lat, far_lon = 40.7140 + 0.01, -73.9440   # ~1.1 km north
    sess = _FakeSession([_text_place(name="Windclimb", lat=far_lat, lon=far_lon)])
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    assert c.place_status("Windclimb", 40.7140, -73.9440).verdict is None


def test_place_status_charges_the_call_budget_before_the_request(tmp_path):
    sess = _FakeSession([_text_place()])
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    c.place_status("Windclimb", 40.7140, -73.9440)
    assert c.calls_used == 1
    with pytest.raises(BudgetExhausted):
        c.place_status("Windclimb", 40.7140, -73.9440)
    assert sess.n == 1                    # the second, refused call never hit the network


def test_place_status_uses_the_pro_field_mask_and_text_search_body(tmp_path):
    sess = _FakeSession([_text_place()])
    c = GooglePlacesClient(api_key="k", budget=1, ledger_path=tmp_path / "l.json", session=sess)
    c.place_status("Windclimb", 40.7140, -73.9440, radius_m=50)
    assert sess.last_body["textQuery"] == "Windclimb"
    assert sess.last_body["locationBias"]["circle"]["radius"] == 50
    assert PLACE_STATUS_RADIUS_M == 50
    assert TEXT_SEARCH_FIELD_MASK == "places.id,places.displayName,places.location,places.businessStatus"


def test_place_status_price_matches_the_closure_evidence_module():
    """The two closure-evidence sessions price this call identically --
    evidence/verify.py restates the number rather than importing this
    module (to keep the Places client a Protocol there); this test is the
    drift check that keeps the restatement honest."""
    assert PLACES_TEXT_SEARCH_USD == VERIFY_PLACES_USD == 0.032


def test_place_status_satisfies_the_verify_protocol(tmp_path):
    """GooglePlacesClient must be usable directly as evidence.verify.verify()'s
    `places` argument -- the whole point of AC-10 landing here."""
    from loci.evidence.verify import Budget, Candidate, verify
    from loci.evidence.web_search import FakeWebSearch
    from loci.db import connect, init_schema

    sess = _FakeSession([_text_place(status="CLOSED_PERMANENTLY")])
    places = GooglePlacesClient(api_key="k", budget=5, ledger_path=tmp_path / "l.json", session=sess)
    con = connect(":memory:")
    init_schema(con)
    cand = Candidate("ovt:1", "Windclimb", "cafe_bakery", -73.9440, 40.7140, 1)
    result = verify(con, [cand], budget=Budget(usd=1.0), places=places,
                    web=FakeWebSearch(), run_id="ac10")
    assert result.closed == 1
    assert result.places_calls == 1
    row = con.execute("SELECT verdict, source, dated_by FROM analysis.poi_closure_evidence "
                      "WHERE poi_id = 'ovt:1'").fetchone()
    assert row == ("closed", "places", "retrieval")
