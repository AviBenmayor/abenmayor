from loci.sources.universal.overture_places import OverturePlacesAdapter


def test_normalize_maps_categories_dedupes_and_drops_bad_records():
    a = OverturePlacesAdapter()
    raw = [
        # exact-match slug -> grocery
        {
            "id": "id-1", "name": "Key Food", "primary_category": "grocery_store",
            "lon": -73.95, "lat": 40.71,
        },
        # exact-match slug -> nails_beauty
        {
            "id": "id-2", "name": "Polished", "primary_category": "nail_salon",
            "lon": -73.99, "lat": 40.72,
        },
        # cuisine-specific leaf caught by the endswith("_restaurant") rule
        {
            "id": "id-3", "name": "Joe's Pizza", "primary_category": "pizza_restaurant",
            "lon": -73.90, "lat": 40.68,
        },
        # unmapped category -> dropped
        {
            "id": "id-4", "name": "Unrelated Co", "primary_category": "coworking_space",
            "lon": -73.91, "lat": 40.69,
        },
        # no coordinates -> dropped
        {
            "id": "id-5", "name": "No Geo Bakery", "primary_category": "bakery",
            "lon": None, "lat": None,
        },
        # duplicate of id-1 -> deduped
        {
            "id": "id-1", "name": "Key Food", "primary_category": "grocery_store",
            "lon": -73.95, "lat": 40.71,
        },
    ]

    recs = list(a.normalize(raw))
    ids = {r.source_record_id for r in recs}

    assert ids == {"id-1", "id-2", "id-3"}  # dup collapsed, unmapped + bad-geo dropped

    by_id = {r.source_record_id: r for r in recs}
    assert by_id["id-1"].category == "grocery"
    assert by_id["id-1"].lon == -73.95
    assert by_id["id-1"].lat == 40.71
    assert by_id["id-2"].category == "nails_beauty"
    assert by_id["id-3"].category == "restaurant"  # via endswith("_restaurant")

    assert all(r.confidence == 0.7 for r in recs)
    assert all(r.source_id == "overture_places" for r in recs)
    assert by_id["id-1"].poi_id == "overture_places:id-1"
    assert by_id["id-1"].attrs == {"primary_category": "grocery_store"}


def test_normalize_drops_records_with_no_primary_category():
    a = OverturePlacesAdapter()
    raw = [
        {"id": "id-6", "name": "Mystery Place", "primary_category": None,
         "lon": -73.9, "lat": 40.7},
    ]
    assert list(a.normalize(raw)) == []


def test_normalize_drops_records_with_no_id():
    a = OverturePlacesAdapter()
    raw = [
        {"id": None, "name": "No Id", "primary_category": "bank",
         "lon": -73.9, "lat": 40.7},
    ]
    assert list(a.normalize(raw)) == []
