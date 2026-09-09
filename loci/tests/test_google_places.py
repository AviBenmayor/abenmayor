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
