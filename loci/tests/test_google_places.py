import pytest
from loci.validation.google_places import GooglePlacesClient, BudgetExhausted, GOOGLE_TYPES
from loci.categories import CATEGORIES


def test_every_category_has_google_types():
    assert set(GOOGLE_TYPES) == set(CATEGORIES)


def test_refuses_without_budget(tmp_path):
    c = GooglePlacesClient(api_key="k", budget=0, ledger_path=tmp_path / "l.json")
    with pytest.raises(BudgetExhausted):
        c.nearby_count(40.7, -73.9, "hardware")


def test_budget_is_enforced_and_persisted(tmp_path):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"places": [{"id": "a"}, {"id": "b"}]}
    class FakeSession:
        def __init__(self): self.n = 0
        def post(self, *a, **k): self.n += 1; return FakeResp()
    sess = FakeSession()
    ledger = tmp_path / "l.json"
    c = GooglePlacesClient(api_key="k", budget=2, ledger_path=ledger, session=sess)
    assert c.nearby_count(40.7, -73.9, "hardware") == 2
    assert c.nearby_count(40.7, -73.9, "fitness") == 2
    with pytest.raises(BudgetExhausted):
        c.nearby_count(40.7, -73.9, "bank")
    assert sess.n == 2
    # a fresh client reads the ledger, so the cap survives restarts
    c2 = GooglePlacesClient(api_key="k", budget=2, ledger_path=ledger, session=sess)
    assert c2.calls_used == 2 and c2.calls_left == 0


def test_metres_expression_uses_correct_axis_order():
    """1° of longitude at 40.7N is ~84.4 km; the unflipped call returns 111 km."""
    import duckdb
    from loci.validation.sample import METRES
    con = duckdb.connect(); con.execute("INSTALL spatial; LOAD spatial;")
    d = con.execute(f"select {METRES.format(a='ST_Point(-73.9, 40.7)', b='ST_Point(-72.9, 40.7)')}").fetchone()[0]
    assert 84_000 < d < 85_000
