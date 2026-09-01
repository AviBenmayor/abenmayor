from loci.sources.universal.osm_overpass import OsmOverpassAdapter


def test_normalize_maps_categories_dedupes_and_drops_bad_geometry():
    a = OsmOverpassAdapter()
    raw = [
        # node: supermarket -> grocery
        {
            "type": "node", "id": 1, "lat": 40.71, "lon": -73.95,
            "tags": {"shop": "supermarket", "name": "Key Food"},
            "_matched_tag": "shop=supermarket",
        },
        # way with center: hairdresser -> hair_barber
        {
            "type": "way", "id": 2,
            "center": {"lat": 40.72, "lon": -73.99},
            "tags": {"shop": "hairdresser", "name": "Cut Above"},
            "_matched_tag": "shop=hairdresser",
        },
        # another tag from the map: bar
        {
            "type": "node", "id": 3, "lat": 40.68, "lon": -73.9,
            "tags": {"amenity": "bar", "name": "Local Pub"},
            "_matched_tag": "amenity=bar",
        },
        # no coordinates at all -> dropped
        {
            "type": "way", "id": 4,
            "tags": {"shop": "bakery", "name": "No Geo Bakery"},
            "_matched_tag": "shop=bakery",
        },
        # way with center missing lat/lon keys -> dropped
        {
            "type": "way", "id": 5,
            "center": {},
            "tags": {"amenity": "pharmacy"},
            "_matched_tag": "amenity=pharmacy",
        },
        # duplicate of element 1 (same type+id) -> deduped
        {
            "type": "node", "id": 1, "lat": 40.71, "lon": -73.95,
            "tags": {"shop": "supermarket", "name": "Key Food"},
            "_matched_tag": "shop=supermarket",
        },
    ]

    recs = list(a.normalize(raw))
    ids = {r.source_record_id for r in recs}

    assert ids == {"node/1", "way/2", "node/3"}  # dup collapsed, bad-geo dropped

    by_id = {r.source_record_id: r for r in recs}
    assert by_id["node/1"].category == "grocery"
    assert by_id["node/1"].lat == 40.71
    assert by_id["node/1"].lon == -73.95
    assert by_id["way/2"].category == "hair_barber"
    assert by_id["way/2"].lat == 40.72   # taken from way center
    assert by_id["way/2"].lon == -73.99
    assert by_id["node/3"].category == "bar"

    assert all(r.confidence == 0.6 for r in recs)
    assert all(r.source_id == "osm_overpass" for r in recs)
    assert by_id["node/1"].poi_id == "osm_overpass:node/1"


def test_normalize_falls_back_to_scanning_tags_without_matched_tag_stamp():
    a = OsmOverpassAdapter()
    raw = [
        {
            "type": "node", "id": 10, "lat": 40.7, "lon": -73.8,
            "tags": {"amenity": "bank", "name": "Community Bank"},
        },
    ]
    recs = list(a.normalize(raw))
    assert len(recs) == 1
    assert recs[0].category == "bank"


def test_normalize_drops_elements_that_match_no_known_tag():
    a = OsmOverpassAdapter()
    raw = [
        {
            "type": "node", "id": 20, "lat": 40.7, "lon": -73.8,
            "tags": {"amenity": "fountain"},
        },
    ]
    assert list(a.normalize(raw)) == []
