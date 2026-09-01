from loci.sources.cities.nyc.dohmh import classify, DohmhAdapter

def test_classify():
    assert classify("Coffee/Tea") == "cafe_bakery"
    assert classify("Bakery Products/Desserts") == "cafe_bakery"
    assert classify("Italian") == "restaurant"
    assert classify(None) == "restaurant"

def test_normalize_dedupes_and_drops_bad_geo():
    a = DohmhAdapter()
    raw = [
        {"camis": "1", "dba": "JOE PIZZA", "cuisine_description": "Pizza", "latitude": "40.7", "longitude": "-73.9"},
        {"camis": "1", "dba": "JOE PIZZA", "cuisine_description": "Pizza", "latitude": "40.7", "longitude": "-73.9"},  # dup CAMIS
        {"camis": "2", "dba": "NO GEO", "cuisine_description": "Thai", "latitude": "0", "longitude": "0"},  # (0,0)
        {"camis": "3", "dba": "BLUE BOTTLE", "cuisine_description": "Coffee/Tea", "latitude": "40.71", "longitude": "-73.95"},
    ]
    recs = list(a.normalize(raw))
    ids = {r.source_record_id for r in recs}
    assert ids == {"1", "3"}  # dup collapsed, (0,0) dropped
    cats = {r.source_record_id: r.category for r in recs}
    assert cats["3"] == "cafe_bakery"
    assert all(r.tier == 3 for r in recs)
    assert recs[0].poi_id == "nyc_dohmh_restaurants:1"
