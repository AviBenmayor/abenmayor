from loci.sources.cities.nyc.dcwp import classify, DcwpAdapter


def test_classify():
    assert classify("Laundries") == "laundry"
    assert classify("Industrial Laundry Delivery") is None  # B2B, not walkable
    assert classify("Dry Cleaning Plant") == "laundry"
    assert classify("Pharmacy - Retail") == "pharmacy"
    assert classify("Tow Truck Company") is None
    assert classify(None) is None


def test_normalize_maps_dedupes_and_drops():
    a = DcwpAdapter()
    raw = [
        # laundromat, active, in-NYC -> kept as laundry
        {"license_nbr": "L1", "business_name": "167 LAUNDRY MART INC.",
         "business_category": "Laundries", "license_status": "Active",
         "license_creation_date": "2021-09-27T00:00:00.000",
         "latitude": "40.83", "longitude": "-73.91", "address_borough": "Bronx"},
        # dry cleaner, active, in-NYC, with dba_trade_name -> kept as laundry
        {"license_nbr": "L2", "business_name": "WJS CLEANERS INC",
         "dba_trade_name": "J'S CLEANERS",
         "business_category": "Dry Cleaning Plant", "license_status": "Active",
         "license_creation_date": "2020-01-01T00:00:00.000",
         "latitude": "40.76", "longitude": "-73.96", "address_borough": "Manhattan"},
        # duplicate of L1 -> collapsed
        {"license_nbr": "L1", "business_name": "167 LAUNDRY MART INC.",
         "business_category": "Laundries", "license_status": "Active",
         "license_creation_date": "2021-09-27T00:00:00.000",
         "latitude": "40.83", "longitude": "-73.91", "address_borough": "Bronx"},
        # non-mapping category -> dropped
        {"license_nbr": "L3", "business_name": "ACME TOW",
         "business_category": "Tow Truck Company", "license_status": "Active",
         "latitude": "40.7", "longitude": "-73.9", "address_borough": "Queens"},
        # laundry category but expired license -> dropped
        {"license_nbr": "L4", "business_name": "OLD LAUNDROMAT",
         "business_category": "Laundries", "license_status": "Expired",
         "latitude": "40.7", "longitude": "-73.9", "address_borough": "Brooklyn"},
        # laundry category, active, but outside NYC -> dropped
        {"license_nbr": "L5", "business_name": "CINTAS CORP",
         "business_category": "Industrial Laundry Delivery", "license_status": "Active",
         "latitude": "40.9", "longitude": "-73.85", "address_borough": "Outside NYC"},
        # laundry category, active, in-NYC borough label, but missing coordinates -> dropped
        {"license_nbr": "L6", "business_name": "NO GEO LAUNDRY",
         "business_category": "Laundries", "license_status": "Active",
         "address_borough": "Queens"},
    ]
    recs = list(a.normalize(raw))
    ids = {r.source_record_id for r in recs}
    assert ids == {"L1", "L2"}

    by_id = {r.source_record_id: r for r in recs}
    assert by_id["L1"].category == "laundry"
    assert by_id["L2"].category == "laundry"
    assert by_id["L2"].name == "J'S Cleaners"
    assert all(r.tier == 1 for r in recs)
    assert all(r.confidence == 0.8 for r in recs)
    assert by_id["L1"].poi_id == "nyc_dcwp_licenses:L1"
    assert by_id["L1"].attrs["license_creation_date"] == "2021-09-27T00:00:00.000"
