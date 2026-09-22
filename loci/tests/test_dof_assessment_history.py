"""Offline tests for the RQ-002 DOF assessment-history adapter
(src/loci/sources/cities/nyc/dof_assessment_history.py): schema normalisation
across the three source shapes (FY2010 tax-class-1/234 split, FY2011-2019
condensed, FY2023-2027 current), the BBL builder, and the double-count guard
(period='3' final-only, rectype='1' primary-record-only) that keeps
8y4t-faws from being pooled tentative+final. No network -- fixture rows only,
mirroring the fetch-injection pattern in test_macro.py.
"""
from __future__ import annotations

from loci.sources.cities.nyc import dof_assessment_history as dah


# ---------------------------------------------------------------------
# FY2010: m8p6-tp4b (tax class 1) / kevu-8hby (tax classes 2,3,4) shape
# ---------------------------------------------------------------------

TC1_ROW = {
    "bble": "1000750043", "boro": "1", "block": "75", "lot": "43",
    "bldgcl": "C0", "txcl": "1",
    "cur_fv_l": "1200000", "cur_fv_t": "9480000",
    "curavl": "72000", "curavt": "213120",
    "tot_unit": "6", "res_unit": "6", "gr_sqft": "6400",
    "hnum_lo": "10", "hnum_hi": "12", "str_name": "EXAMPLE ST",
    "zip": "10038", "year4": "2010",
}

TC234_ROW = {
    "bble": "1000060001", "boro": "1", "block": "6", "lot": "1",
    "bldgcl": "Q9", "txcl": "4",
    "cur_fv_l": "10000000", "cur_fv_t": "50040000",
    "curavl": "4500000", "curavt": "16077600",
    "tot_unit": None, "res_unit": None, "gr_sqft": "0",
    "hnum_lo": "100", "hnum_hi": None, "str_name": "MAIN ST",
    "zip": "10004", "year4": "2010",
}


def test_normalize_tc1_tc234_maps_market_and_assessed_values():
    df = dah.normalize_tc1_tc234([TC1_ROW, TC234_ROW], 2010, "m8p6-tp4b")
    assert list(df.columns) == dah.OUTPUT_COLUMNS
    assert len(df) == 2
    row = df.iloc[0]
    assert row["bbl"] == "1000750043"
    assert row["fiscal_year"] == 2010
    assert row["building_class"] == "C0"
    assert row["tax_class"] == "1"
    assert row["market_value_total"] == 9_480_000.0
    assert row["market_value_land"] == 1_200_000.0
    assert row["assessed_value_actual_total"] == 213_120.0
    # this source shape has no transitional-value field at all -- must be
    # NULL, never zero (a zero would read as "no phase-in cap applies")
    assert row["assessed_value_transitional_total"] is None
    assert row["gross_sqft"] == 6400.0
    # no retail/office sqft breakdown exists in this source shape either
    assert row["retail_sqft"] is None
    assert row["address"] == "10 EXAMPLE ST"


def test_normalize_tc1_tc234_handles_missing_units_and_address():
    df = dah.normalize_tc1_tc234([TC234_ROW], 2010, "kevu-8hby")
    row = df.iloc[0]
    assert row["residential_units"] is None
    assert row["total_units"] is None
    assert row["address"] == "100 MAIN ST"


# ---------------------------------------------------------------------
# FY2011-2019: yjxr-fw8i condensed shape (avtot2/avland2 = transitional)
# ---------------------------------------------------------------------

CONDENSED_ROW = {
    "bble": "1000163712", "boro": "1", "block": "16", "lot": "3712",
    "bldgcl": "R4", "taxclass": "2",
    "fullval": "418548", "avland": "84800", "avtot": "188347",
    "avland2": "85200", "avtot2": "190903",
    "staddr": "1 EXAMPLE PLACE", "zip": "10001", "year": "2010/11",
    "period": "FINAL", "latitude": "40.75", "longitude": "-73.99",
}


def test_normalize_condensed_maps_transitional_from_suffix2_fields():
    df = dah.normalize_condensed([CONDENSED_ROW], 2011, "yjxr-fw8i")
    row = df.iloc[0]
    assert row["bbl"] == "1000163712"
    assert row["fiscal_year"] == 2011
    assert row["market_value_total"] == 418_548.0
    # no land-only market value field exists in the condensed shape
    assert row["market_value_land"] is None
    assert row["assessed_value_actual_total"] == 188_347.0
    assert row["assessed_value_transitional_total"] == 190_903.0
    assert row["assessed_value_transitional_land"] == 85_200.0
    assert row["latitude"] == 40.75
    assert row["longitude"] == -73.99
    # no sqft-by-use breakdown exists in the condensed shape
    assert row["gross_sqft"] is None
    assert row["residential_units"] is None


def test_normalize_condensed_transitional_null_when_source_field_blank():
    row = dict(CONDENSED_ROW)
    row["avtot2"] = None
    row["avland2"] = None
    df = dah.normalize_condensed([row], 2011, "yjxr-fw8i")
    assert df.iloc[0]["assessed_value_transitional_total"] is None


# ---------------------------------------------------------------------
# FY2023-2027: 8y4t-faws current shape, incl. retail/gross sqft
# ---------------------------------------------------------------------

CURRENT_ROW_FINAL = {
    "parid": "1000251032", "boro": "1", "block": "25", "lot": "1032",
    "bldg_class": "R4", "curtaxclass": "2",
    "curmktland": "50000", "curmkttot": "274934",
    "curactland": "27700", "curacttot": "123720",
    "curtrnland": "26300", "curtrntot": "117521",
    "gross_sqft": "866", "retail_area_gross": "0",
    "units": "1", "housenum_lo": "150", "street_name": "EXAMPLE AVE",
    "zip_code": "10004", "year": "2023", "period": "3", "rectype": "1",
}

# a utility special-franchise sub-account row under the SAME parent BBL --
# rectype='1' filtering (done upstream, in fetch_year's $where) is what keeps
# this out of the pull; the mapper itself does not re-filter, so this fixture
# documents what such a row would normalize to if it slipped through.
CURRENT_ROW_UTILITY_SUBACCOUNT = {
    "parid": "1726160001 143", "boro": "1", "block": "72616", "lot": "1",
    "bldg_class": "U0", "curtaxclass": "3",
    "curmktland": None, "curmkttot": "500000",
    "curactland": None, "curacttot": "225000",
    "curtrnland": None, "curtrntot": "225000",
    "gross_sqft": None, "retail_area_gross": None,
    "units": None, "housenum_lo": None, "street_name": None,
    "zip_code": None, "year": "2027", "period": "3", "rectype": "3",
}


def test_normalize_current_maps_retail_and_gross_sqft():
    df = dah.normalize_current([CURRENT_ROW_FINAL], 2023, "8y4t-faws")
    row = df.iloc[0]
    assert row["bbl"] == "1000251032"
    assert row["market_value_total"] == 274_934.0
    assert row["market_value_land"] == 50_000.0
    assert row["assessed_value_actual_total"] == 123_720.0
    assert row["assessed_value_transitional_total"] == 117_521.0
    assert row["gross_sqft"] == 866.0
    assert row["retail_sqft"] == 0.0
    assert row["total_units"] == 1.0
    assert row["address"] == "150 EXAMPLE AVE"
    # no residential/commercial unit split is published in this source shape
    assert row["residential_units"] is None


def test_current_where_clause_excludes_tentative_and_subaccount_rows():
    """The double-count guard: fetch_year's $where must ask for the FINAL
    roll only and the primary record type only, so a caller can never
    construct a request that pools period 1 (tentative) with period 3
    (final) for the same BBL."""
    spec = next(s for s in dah.DATASETS if s.dataset_id == "8y4t-faws")
    assert spec.where_extra == "period='3' AND rectype='1'"


def test_condensed_where_clause_is_final_only():
    spec = next(s for s in dah.DATASETS if s.dataset_id == "yjxr-fw8i")
    assert spec.where_extra == "period='FINAL'"


# ---------------------------------------------------------------------
# BBL construction
# ---------------------------------------------------------------------

def test_bbl_zero_pads_block_and_lot():
    assert dah._bbl("1", "75", "43") == "1000750043"
    assert dah._bbl(3, 2554, 11) == "3025540011"


def test_bbl_returns_none_on_unparseable_input():
    assert dah._bbl(None, "75", "43") is None
    assert dah._bbl("1", "abc", "43") is None


# ---------------------------------------------------------------------
# Coverage bookkeeping: no fiscal year is covered by two datasets at once
# (the pooling trap this module exists to avoid at the *year* level, on
# top of the period/rectype trap within 8y4t-faws).
# ---------------------------------------------------------------------

def test_no_fiscal_year_is_double_covered_across_datasets():
    from collections import Counter
    counts = Counter()
    for spec in dah.DATASETS:
        for fy in spec.year_values:
            counts[(fy, spec.dataset_id)] += 1
    # m8p6-tp4b and kevu-8hby legitimately share FY2010 (tax class 1 vs
    # 2/3/4 -- a real split, not a duplicate); no other pairing may share a year.
    by_year: dict[int, set[str]] = {}
    for spec in dah.DATASETS:
        for fy in spec.year_values:
            by_year.setdefault(fy, set()).add(spec.dataset_id)
    for fy, ids in by_year.items():
        if len(ids) > 1:
            assert ids == {"m8p6-tp4b", "kevu-8hby"}, (
                f"FY{fy} is claimed by {ids} -- would double-count every BBL "
                f"in that year if both are written to the same partition"
            )


def test_known_gap_years_are_not_claimed_by_any_dataset():
    covered = {fy for spec in dah.DATASETS for fy in spec.year_values}
    for fy in dah.KNOWN_GAP_FISCAL_YEARS:
        assert fy not in covered
