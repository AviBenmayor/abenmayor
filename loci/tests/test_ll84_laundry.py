"""LL84 in-building laundry ingest (D51(d)).

The load-bearing test here is `test_field_names_resolve_by_display_name_not_position`:
Socrata's positional fieldName for the two hookup columns SWAPS MEANING between
vintages, so a positional read transposes in-unit and common-area laundry for
half the panel with no downstream symptom.
"""
import pytest

from loci.sources.cities.nyc.ll84_laundry import (
    normalize_bbl, parse_count, resolve_fields, normalize_vintage, VINTAGES,
)


# --------------------------------------------------------------- BBL normalization

def test_bbl_canonical_and_padded():
    assert normalize_bbl("4026780001") == ["4026780001"]
    # dashed borough-block-lot with stray spaces, zero-padded on the way out
    assert normalize_bbl("1- 02090-0024") == ["1020900024"]
    assert normalize_bbl("02-02452-0029") == ["2024520029"]
    assert normalize_bbl(" 3067300001 ") == ["3067300001"]


def test_bbl_multi_split():
    # semicolon-separated campus filing -> BOTH lots, exploded
    assert normalize_bbl("02-03220-0040;02-03220-0051") == ["2032200040", "2032200051"]
    # comma is a separator too; `-` inside a BBL is NOT
    assert normalize_bbl("1000160100, 1000160200") == ["1000160100", "1000160200"]
    # duplicates within one cell collapse
    assert normalize_bbl("1000160100;1000160100") == ["1000160100"]


def test_bbl_unattributable_is_dropped_never_guessed():
    assert normalize_bbl("00847-0027;00847-7501") == []   # block-lot, no borough
    assert normalize_bbl("072610008") == []               # 9 digits, ambiguous
    assert normalize_bbl("01791") == []                   # block only
    assert normalize_bbl("0-00000-0000") == []            # junk
    assert normalize_bbl("0000000001, 0000000002") == []  # borough 0 is not a borough
    assert normalize_bbl("6000160100") == []              # borough 6 does not exist
    assert normalize_bbl("1020900000") == []              # lot 0 is not a real lot
    assert normalize_bbl(None) == []
    assert normalize_bbl("") == []


# --------------------------------------------------------------- counts

def test_zero_is_an_affirmative_none_not_a_blank():
    assert parse_count("0") == 0
    assert parse_count(0) == 0
    assert parse_count("4") == 4
    assert parse_count("Not Available") is None
    assert parse_count("") is None
    assert parse_count(None) is None
    assert parse_count("n/a") is None
    assert parse_count("1,200") == 1200
    assert parse_count("-3") is None


# --------------------------------------------------------------- field resolution

def _cols(pairs):
    return [{"name": n, "fieldName": f} for n, f in pairs]


# The real metadata, verified against /api/views/<id>.json on 2026-09-08.
_V2024 = _cols([
    ("Multifamily Housing - Number of Laundry Hookups in All Units", "multifamily_housing_number_2"),
    ("Multifamily Housing - Number of Laundry Hookups in Common Area(s)", "multifamily_housing_number_3"),
    ("NYC Borough, Block and Lot (BBL)", "nyc_borough_block_and_lot"),
    ("Multifamily Housing - Total Number of Residential Living Units", "multifamily_housing_total"),
    ("Year Ending", "year_ending"),
])
_V2019 = _cols([
    ("Multifamily Housing - Number of Laundry Hookups in All Units", "multifamily_housing_number_1"),
    ("Multifamily Housing - Number of Laundry Hookups in Common Area(s)", "multifamily_housing_number_2"),
    ("NYC Borough, Block and Lot (BBL)", "nyc_borough_block_and_lot"),
    ("Multifamily Housing - Total Number of Residential Living Units", "multifamily_housing_total"),
    ("Year Ending", "year_ending"),
])


def test_field_names_resolve_by_display_name_not_position():
    a = resolve_fields("5zyy-y8am", columns=_V2024)
    b = resolve_fields("4tys-3tzj", columns=_V2019)
    # THE TRAP: the same machine name is a different quantity in the two vintages.
    assert a["in_unit_hookups"] == "multifamily_housing_number_2"
    assert b["common_area_hookups"] == "multifamily_housing_number_2"
    assert a["common_area_hookups"] == "multifamily_housing_number_3"
    assert b["in_unit_hookups"] == "multifamily_housing_number_1"
    # ...so a positional read would swap them, and display-name resolution must not.
    assert a["common_area_hookups"] != b["common_area_hookups"]


def test_2013_vintage_uses_the_short_bbl_column_name():
    cols = _cols([
        ("Multifamily Housing - Number of Laundry Hookups in Common Area(s)", "multifamily_housing_number_1"),
        ("Multifamily Housing - Number of Laundry Hookups in All Units", "multifamily_housing_number_2"),
        ("BBL", "bbl"),
        ("Year Ending", "year_ending"),
    ])
    f = resolve_fields("r6ub-zhff", columns=cols)
    assert f["bbl"] == "bbl"
    assert f["common_area_hookups"] == "multifamily_housing_number_1"


def test_missing_laundry_field_raises_rather_than_nulling():
    cols = _cols([("NYC Borough, Block and Lot (BBL)", "nyc_borough_block_and_lot")])
    with pytest.raises(RuntimeError, match="no longer exposes"):
        resolve_fields("5zyy-y8am", columns=cols)


def test_ll84_2012_is_excluded():
    assert "k7nh-aufb" not in {d for d, _ in VINTAGES}
    assert len(VINTAGES) == 8


# --------------------------------------------------------------- normalize_vintage

def test_normalize_vintage_explodes_and_counts_drops():
    fields = resolve_fields("5zyy-y8am", columns=_V2024)
    rows = [
        {"nyc_borough_block_and_lot": "1016490009", "multifamily_housing_number_2": "0",
         "multifamily_housing_number_3": "4", "multifamily_housing_total": "120",
         "year_ending": "2023-12-31T00:00:00.000"},
        {"nyc_borough_block_and_lot": "3-02200-0040;3-02200-0051",
         "multifamily_housing_number_2": "Not Available",
         "multifamily_housing_number_3": "2", "multifamily_housing_total": "80",
         "year_ending": "2022-12-31T00:00:00.000"},
        {"nyc_borough_block_and_lot": "01791", "multifamily_housing_number_2": "1",
         "multifamily_housing_number_3": "1", "year_ending": "2022-12-31T00:00:00.000"},
    ]
    recs, stats = normalize_vintage(rows, fields, dataset_id="5zyy-y8am", default_year=2024)
    # `answered` counts rows that SURVIVED the BBL drop: the third row answers
    # both fields but has no attributable BBL, so it contributes to neither.
    assert stats == {"rows": 3, "bbl_unparsable": 1, "multi_bbl_rows": 1,
                     "exploded_rows": 3, "answered": 2}
    assert len(recs) == 3
    # report year = covered calendar year + 1
    assert recs[0]["filed_year"] == 2024
    assert recs[0]["common_area_hookups"] == 4 and recs[0]["in_unit_hookups"] == 0
    campus = [r for r in recs if r["bbl"].startswith("3022")]
    assert {r["bbl"] for r in campus} == {"3022000040", "3022000051"}
    assert all(r["multi_bbl"] and r["filed_year"] == 2023 for r in campus)
    assert all(r["in_unit_hookups"] is None for r in campus)


# --------------------------------------------------------------- pooling / disagreement

def test_address_laundry_latest_non_null_wins_and_counts_disagreement():
    from loci.db import connect, init_schema
    from loci.sources.cities.nyc.ll84_laundry import build_address_laundry
    import pandas as pd

    con = connect(":memory:")
    init_schema(con)
    df = pd.DataFrame([
        # A: said YES in 2018, NO in 2024 -> latest (NO) wins, 1 vintage dissents
        {"bbl": "1000000001", "filed_year": 2018, "common_area_hookups": 3, "in_unit_hookups": 0},
        {"bbl": "1000000001", "filed_year": 2024, "common_area_hookups": 0, "in_unit_hookups": 0},
        # B: blank in 2024, answered in 2019 -> the 2019 answer survives
        {"bbl": "3000000002", "filed_year": 2019, "common_area_hookups": 2, "in_unit_hookups": None},
        {"bbl": "3000000002", "filed_year": 2024, "common_area_hookups": None, "in_unit_hookups": None},
        # C: never answered either field -> laundry_measured FALSE, not a "no"
        {"bbl": "3000000003", "filed_year": 2024, "common_area_hookups": None, "in_unit_hookups": None},
    ])
    df["dataset_id"] = "test"
    df["units_reported"] = 50
    df["n_filings"] = 1
    df["any_multi_bbl"] = False
    con.register("_d", df)
    con.execute("""INSERT INTO staging.ll84_laundry
        SELECT bbl, CAST(filed_year AS SMALLINT), dataset_id,
               CAST(common_area_hookups AS INTEGER), CAST(in_unit_hookups AS INTEGER),
               CAST(units_reported AS INTEGER), CAST(n_filings AS SMALLINT),
               any_multi_bbl, now() FROM _d""")
    assert build_address_laundry(con) == 3

    got = {r[0]: r[1:] for r in con.execute(
        """SELECT bbl, has_common_laundry, has_in_unit_laundry, laundry_measured,
                  latest_vintage, n_vintages, n_vintages_disagree
           FROM analysis.address_laundry""").fetchall()}

    assert got["1000000001"] == (False, False, True, 2024, 2, 1)
    assert got["3000000002"] == (True, None, True, 2019, 2, 0)
    # a blank is NOT a "no": has_* stay NULL and laundry_measured is False
    assert got["3000000003"] == (None, None, False, None, 1, 0)
