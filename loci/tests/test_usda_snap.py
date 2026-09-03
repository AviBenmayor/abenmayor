from loci.sources.universal.usda_snap import UsdaSnapAdapter, STORE_TYPE_MAP


def test_store_type_map_covers_only_bundle_storefronts():
    assert STORE_TYPE_MAP["Supermarket"] == "grocery"
    assert STORE_TYPE_MAP["Grocery Store"] == "grocery"
    assert STORE_TYPE_MAP["Convenience Store"] == "convenience"
    # Not daily-needs storefronts in the bundle's sense — must be dropped, not guessed.
    for t in ("Farmers and Markets", "Restaurant Meals Program", "Specialty Store", "Other"):
        assert t not in STORE_TYPE_MAP


def test_normalize_maps_types_dedupes_and_drops_unmapped():
    a = UsdaSnapAdapter()
    raw = [
        {"Record_ID": 1, "Store_Name": "BAY PARKWAY DELI CORP", "Store_Type": "Convenience Store",
         "Latitude": 40.60247, "Longitude": -73.993629, "County": "KINGS", "City": "Brooklyn", "Zip_Code": "11214"},
        {"Record_ID": 1, "Store_Name": "BAY PARKWAY DELI CORP", "Store_Type": "Convenience Store",
         "Latitude": 40.60247, "Longitude": -73.993629},                      # duplicate Record_ID
        {"Record_ID": 2, "Store_Name": "KEY FOOD", "Store_Type": "Supermarket",
         "Latitude": 40.65, "Longitude": -73.95},
        {"Record_ID": 3, "Store_Name": "UNION SQ GREENMARKET", "Store_Type": "Farmers and Markets",
         "Latitude": 40.73, "Longitude": -73.99},                             # unmapped type
        {"Record_ID": 4, "Store_Name": "NO GEO", "Store_Type": "Grocery Store",
         "Latitude": None, "Longitude": None},                                # missing coords
    ]
    recs = list(a.normalize(raw))
    by_id = {r.source_record_id: r for r in recs}
    assert set(by_id) == {"1", "2"}
    assert by_id["1"].category == "convenience" and by_id["1"].tier == 1
    assert by_id["2"].category == "grocery" and by_id["2"].tier == 1
    assert by_id["1"].name == "Bay Parkway Deli Corp"
    assert by_id["1"].poi_id == "usda_snap_retailers:1"
    assert by_id["1"].attrs["store_type"] == "Convenience Store"
    assert all(r.confidence == 0.9 for r in recs)
