import datetime as dt
from loci.sources.universal.foursquare_places import FoursquarePlacesAdapter, map_leaf


def test_map_leaf_matches_leaf_label_and_cuisine_suffix():
    assert map_leaf(["Retail > Food and Beverage Retail > Grocery Store"]) == "grocery"
    assert map_leaf(["Dining and Drinking > Bar > Dive Bar"]) == "bar"
    assert map_leaf(["Dining and Drinking > Restaurant > Sichuan Restaurant"]) == "restaurant"
    assert map_leaf(["Sports and Recreation > Gym and Studio > Yoga Studio"]) == "fitness"
    assert map_leaf(["Sports and Recreation > Gym and Studio"]) == "fitness"
    assert map_leaf(["Dining and Drinking > Restaurant > Deli"]) is None        # dropped on purpose
    assert map_leaf(["Dining and Drinking > Bar > Speakeasy"]) == "bar"       # group prefix, no leaf entry
    assert map_leaf(["Dining and Drinking > Cafe, Coffee, and Tea House > Bubble Tea Shop"]) == "cafe_bakery"
    assert map_leaf(["Health and Medicine > Physician > Cardiologist"]) is None  # specialist stays unmapped
    assert map_leaf(["Health and Medicine > Physician > Doctor's Office"]) is None  # 23k rows; not a clinic
    assert map_leaf(["Health and Medicine > Urgent Care Center"]) == "clinic"
    assert map_leaf(["Business and Professional Services > Home Improvement Service > Carpenter"]) is None
    assert map_leaf(["Retail > Bookstore"]) is None
    assert map_leaf(None) is None
    assert map_leaf("Retail > Hardware Store") == "hardware"   # bare string tolerated
    assert map_leaf(["Business and Professional Services > Financial Service > Banking and Finance > ATM",
                     "Business and Professional Services > Financial Service > Banking and Finance > Bank"]) is None


def test_normalize_skips_closed_unmapped_and_dupes_and_records_unmapped():
    a = FoursquarePlacesAdapter()
    raw = [
        {"id": "x1", "name": "Ace Hardware", "labels": ["Retail > Hardware Store"], "lat": 40.7, "lon": -73.9,
         "created": dt.date(2015, 3, 1), "refreshed": dt.date(2025, 6, 1), "closed": None},
        {"id": "x1", "name": "Ace Hardware", "labels": ["Retail > Hardware Store"], "lat": 40.7, "lon": -73.9,
         "created": None, "refreshed": "2026-01-01", "closed": None},                    # dup id
        {"id": "x2", "name": "Gone Gym", "labels": ["Sports and Recreation > Gym and Studio > Gym"], "lat": 40.7, "lon": -73.9,
         "created": None, "refreshed": "2026-01-01", "closed": dt.date(2023, 1, 1)},      # closed
        {"id": "x3", "name": "Books", "labels": ["Retail > Bookstore"], "lat": 40.7, "lon": -73.9,
         "created": None, "refreshed": "2026-01-01", "closed": None},                    # unmapped
        {"id": "x4", "name": "No Geo", "labels": ["Retail > Hardware Store"], "lat": None, "lon": None,
         "created": None, "refreshed": "2026-01-01", "closed": None},
        {"id": "x5", "name": "Ghost Hardware", "labels": ["Retail > Hardware Store"], "lat": 40.7, "lon": -73.9,
         "created": "2011-05-05", "refreshed": "2012-03-03", "closed": None},           # stale: last refreshed 2012
        {"id": "x6", "name": "Never Refreshed", "labels": ["Retail > Hardware Store"], "lat": 40.7, "lon": -73.9,
         "created": "2011-05-05", "refreshed": None, "closed": None},
    ]
    recs = list(a.normalize(raw))
    assert [r.source_record_id for r in recs] == ["x1"]
    assert recs[0].category == "hardware" and recs[0].tier == 4
    assert recs[0].opened_on == dt.date(2015, 3, 1)
    assert recs[0].poi_id == "foursquare_os_places:x1"
    assert recs[0].confidence == 0.6
    assert a.unmapped_leaves == {"bookstore": 1}
    assert a.dropped_stale == 2
