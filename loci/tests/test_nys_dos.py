import datetime as dt

from loci.sources.cities.nyc.nys_dos import classify, in_nyc_bbox, NysDosAdapter


def test_classify():
    assert classify("DOSBARSHOPOWNER") == "hair_barber"
    assert classify("DOSBARRENTER") == "hair_barber"
    assert classify("DOSAEBUSINESS") == "nails_beauty"
    assert classify("DOSAERENTER") == "nails_beauty"
    assert classify(None) is None
    assert classify("SOMETHING_ELSE") is None


def test_in_nyc_bbox():
    assert in_nyc_bbox(-73.9, 40.7)          # Manhattan-ish
    assert not in_nyc_bbox(-75.21965, 43.0951)  # Utica


def test_normalize_maps_dedupes_and_filters_nyc():
    a = NysDosAdapter()
    raw = [
        # barber in NYC
        {"license_number": "BSO-1", "license_type": "DOSBARSHOPOWNER",
         "business_name": "spanish barbershop", "business_city": "Bronx",
         "business_zip": "10458",
         "georeference": {"type": "Point", "coordinates": [-73.88652, 40.85389]}},
        # nail / appearance-enhancement in NYC
        {"license_number": "AEB-1", "license_type": "DOSAEBUSINESS",
         "business_name": "yirat beauty salon corp", "business_city": "New York",
         "business_zip": "10075",
         "georeference": {"type": "Point", "coordinates": [-73.95967, 40.7739]}},
        # non-NYC row (Utica) -- must be dropped
        {"license_number": "BSO-2", "license_type": "DOSBARSHOPOWNER",
         "business_name": "spanish barbershop", "business_city": "Utica",
         "business_zip": "13501",
         "georeference": {"type": "Point", "coordinates": [-75.21965, 43.0951]}},
        # duplicate license_number -- second copy must collapse
        {"license_number": "BSO-1", "license_type": "DOSBARSHOPOWNER",
         "business_name": "spanish barbershop", "business_city": "Bronx",
         "business_zip": "10458",
         "georeference": {"type": "Point", "coordinates": [-73.88652, 40.85389]}},
        # unrecognized license_type -- must be dropped
        {"license_number": "XXX-1", "license_type": "SOMETHING_ELSE",
         "business_name": "mystery co", "business_city": "New York",
         "business_zip": "10001",
         "georeference": {"type": "Point", "coordinates": [-73.99, 40.75]}},
        # missing georeference -- must be dropped
        {"license_number": "AEB-2", "license_type": "DOSAEBUSINESS",
         "business_name": "no geo salon", "business_city": "New York",
         "business_zip": "10001", "georeference": None},
    ]
    recs = list(a.normalize(raw))
    ids = {r.source_record_id for r in recs}
    assert ids == {"BSO-1", "AEB-1"}   # non-NYC, dup, bad type, no-geo all dropped

    by_id = {r.source_record_id: r for r in recs}
    assert by_id["BSO-1"].category == "hair_barber"
    assert by_id["AEB-1"].category == "nails_beauty"
    assert all(r.tier == 2 for r in recs)

    today = dt.date.today()
    for r in recs:
        assert r.observed_on == today
        assert r.opened_on is None
        assert r.closed_on is None
        assert r.confidence == 0.85
        assert r.source_id == "nys_dos_appearance_enhancement"

    assert by_id["BSO-1"].poi_id == "nys_dos_appearance_enhancement:BSO-1"
