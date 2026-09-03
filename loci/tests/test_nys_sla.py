from loci.sources.cities.nyc.nys_sla import NysSlaAdapter, BAR_DESCRIPTIONS


def _row(lid, desc, coords=(-73.98535, 40.66635), dba="CROSTA", legal="PICCOLI804 LLC", issued="2025-11-04T00:00:00.000"):
    return {"licensepermitid": lid, "description": desc, "dba": dba, "legalname": legal,
            "class": "0340", "premisescounty": "Kings", "actualaddressofpremises": "486 6TH AVE",
            "city": "BROOKLYN", "zipcode": "11215", "originalissuedate": issued,
            "expirationdate": "2027-11-30T00:00:00.000",
            "georeference": {"type": "Point", "coordinates": list(coords)} if coords else None}


def test_mapping_is_conservative():
    # H-D9: descriptions never say "bar"; only on-premises non-restaurant classes are emitted.
    assert "food & beverage business" in BAR_DESCRIPTIONS
    assert "club" in BAR_DESCRIPTIONS
    # DOHMH anchors restaurants; riders and retail licences are not venues.
    for d in ("restaurant", "additional bar", "grocery store", "liquor store", "drug store"):
        assert d not in BAR_DESCRIPTIONS


def test_normalize_emits_bars_only_and_handles_geo():
    a = NysSlaAdapter()
    raw = [
        _row("A-1", "Food & Beverage Business"),
        _row("A-1", "Food & Beverage Business"),                       # duplicate licence id
        _row("B-2", "Restaurant"),                                     # DOHMH's job
        _row("C-3", "Additional Bar"),                                 # rider on an existing premises
        _row("D-4", "Club", coords=None),                              # no georeference
        _row("E-5", "Cabaret", coords=(0.0, 0.0)),                     # (0,0) sentinel
        _row("F-6", "Bottle Club", dba="", legal="SOME LLC", issued=None),
    ]
    recs = list(a.normalize(raw))
    by_id = {r.source_record_id: r for r in recs}
    assert set(by_id) == {"A-1", "F-6"}
    assert all(r.category == "bar" and r.tier == 3 for r in recs)
    assert by_id["A-1"].name == "Crosta"
    assert by_id["A-1"].opened_on.isoformat() == "2025-11-04"
    assert (by_id["A-1"].lon, by_id["A-1"].lat) == (-73.98535, 40.66635)
    assert by_id["F-6"].name == "Some Llc"          # falls back to legal name
    assert by_id["F-6"].opened_on is None
    assert by_id["A-1"].poi_id == "nys_sla_liquor_licenses:A-1"
