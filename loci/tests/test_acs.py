from loci.grid.acs import _clean, BORO_COUNTY


def test_clean_handles_census_sentinels():
    assert _clean("4839") == 4839.0
    assert _clean("-666666666") is None   # ACS not-computable
    assert _clean("") is None
    assert _clean(None) is None
    assert _clean("92263") == 92263.0


def test_borough_county_mapping():
    # Queens borocode 4 -> county 081; used to build the tract GEOID
    assert BORO_COUNTY["4"] == "081"
    assert BORO_COUNTY["1"] == "061"  # Manhattan
    assert set(BORO_COUNTY) == {"1", "2", "3", "4", "5"}
