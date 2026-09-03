from loci.score.dedup import norm_tokens, names_match, source_rank, _dedup_category


def test_distinctive_token_matching():
    # true twins across sources with different generic words -> match
    assert names_match(norm_tokens("Tom's Restaurant"), norm_tokens("Tom's Diner"))
    # containment of a distinctive multi-token name
    assert names_match(norm_tokens("The Starlight"), norm_tokens("The Starlight Tavern"))
    # generic-word overlap must NOT match distinct businesses
    assert not names_match(norm_tokens("Kennedy Fried Chicken"), norm_tokens("Crown Fried Chicken"))
    assert not names_match(norm_tokens("Joe's Pizza"), norm_tokens("Ray's Pizza"))
    # empty after stripping generics -> no match
    assert not names_match(norm_tokens("Restaurant"), norm_tokens("Pizza Place"))


def test_source_rank_prefers_anchor():
    assert source_rank("restaurant", "nyc_dohmh_restaurants") < source_rank("restaurant", "overture_places")
    assert source_rank("nails_beauty", "nys_dos_appearance_enhancement") < source_rank("nails_beauty", "osm_overpass")


def test_dedup_category_merges_twins_not_neighbors():
    rows = [
        {"poi_id": "overture_places:a", "source_id": "overture_places", "name": "Tom's Restaurant",
         "category": "restaurant", "confidence": 0.7, "lat": 40.7000, "lon": -73.9000},
        {"poi_id": "nyc_dohmh_restaurants:b", "source_id": "nyc_dohmh_restaurants", "name": "Tom's Diner",
         "category": "restaurant", "confidence": 0.95, "lat": 40.70005, "lon": -73.90005},  # ~7m, same
        {"poi_id": "overture_places:c", "source_id": "overture_places", "name": "Ruby's Grill",
         "category": "restaurant", "confidence": 0.7, "lat": 40.70010, "lon": -73.90010},  # ~14m, different
    ]
    out = {pid: (cid, canon) for pid, cid, canon in _dedup_category(rows)}
    # a and b merge (same distinctive token), c stays separate
    assert out["overture_places:a"][0] == out["nyc_dohmh_restaurants:b"][0]
    assert out["overture_places:c"][0] != out["overture_places:a"][0]
    # canonical of the twin cluster is the DOHMH anchor
    assert out["nyc_dohmh_restaurants:b"][1] is True
    assert out["overture_places:a"][1] is False


def test_source_rank_new_anchors_win_their_category():
    assert source_rank("convenience", "usda_snap_retailers") < source_rank("convenience", "overture_places")
    assert source_rank("bar", "nys_sla_liquor_licenses") < source_rank("bar", "nyc_dohmh_restaurants")
    assert source_rank("hardware", "foursquare_os_places") > source_rank("hardware", "overture_places")
    # anchors carry no authority outside their category
    assert source_rank("hardware", "usda_snap_retailers") == source_rank("hardware", "some_unknown_source")
