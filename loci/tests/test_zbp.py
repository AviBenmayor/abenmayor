"""Tests for the Census ZBP/CBP validation source (docs/CHECKPOINT.md
ZBP-validation ticket): crosswalk loading (fails closed), response parsing
against a real-shaped fixture, and the per-category rollup arithmetic.
"""
from __future__ import annotations

import json
import pathlib

import pandas as pd
import pytest
import yaml

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.model.zbp_compare import UNDERCOVER_RATIO
from loci.sources.universal.census_zbp import _finest_level, build_zip_category_establishments
from loci.zbp import ZbpConfigError, load_zbp_naics, naics_to_category

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- crosswalk loader

def test_load_zbp_naics_has_all_15_categories_with_6_digit_codes():
    xwalk = load_zbp_naics()
    assert set(xwalk) == set(CATEGORIES)
    for cat, entries in xwalk.items():
        assert entries, f"{cat} has no NAICS codes"
        for entry in entries:
            assert isinstance(entry["naics"], str)
            assert len(entry["naics"]) == 6 and entry["naics"].isdigit()
            assert entry["confidence"] in {"high", "medium"}


def test_naics_to_category_is_flat_and_covers_every_category():
    flat = naics_to_category()
    assert set(flat.values()) == set(CATEGORIES)
    assert flat["445110"] == "grocery"
    assert flat["812113"] == "nails_beauty"


def test_crosswalk_loader_fails_closed_on_missing_category(tmp_path, monkeypatch):
    doc = yaml.safe_load((pathlib.Path(__file__).parents[1]
                           / "src" / "loci" / "zbp_naics.yaml").read_text())
    del doc["categories"]["hardware"]   # drop one of the 15 categories
    bad_path = tmp_path / "zbp_naics_missing.yaml"
    bad_path.write_text(yaml.safe_dump(doc))

    import loci.zbp as zbp_mod
    monkeypatch.setattr(zbp_mod, "ZBP_NAICS_PATH", bad_path)

    with pytest.raises(ZbpConfigError, match="hardware"):
        zbp_mod.load_zbp_naics()


def test_crosswalk_loader_fails_closed_on_bad_naics_code(tmp_path, monkeypatch):
    doc = yaml.safe_load((pathlib.Path(__file__).parents[1]
                           / "src" / "loci" / "zbp_naics.yaml").read_text())
    doc["categories"]["hardware"] = [{"naics": "4441", "confidence": "high", "note": "too short"}]
    bad_path = tmp_path / "zbp_naics_bad_code.yaml"
    bad_path.write_text(yaml.safe_dump(doc))

    import loci.zbp as zbp_mod
    monkeypatch.setattr(zbp_mod, "ZBP_NAICS_PATH", bad_path)

    with pytest.raises(ZbpConfigError, match="6-digit"):
        zbp_mod.load_zbp_naics()


# ---------------------------------------------------------------- response parsing

def _load_fixture_rows() -> list[dict]:
    body = json.loads((FIXTURES / "zbp_response.json").read_text())
    header, *data = body
    return [dict(zip(header, row)) for row in data]


def test_finest_level_filters_to_6_digit_naics_only():
    rows = _load_fixture_rows()
    df = _finest_level(rows)
    # The fixture includes one 4-digit rollup row (NAICS "4451") that must be dropped.
    assert set(df["naics"].str.len()) == {6}
    assert "4451" not in set(df["naics"])
    # 3 rows for 445110 + 2 for 445120 + 4 for 812320/812310 = 9 six-digit rows.
    assert len(df) == 9


def test_finest_level_column_names_and_types():
    rows = _load_fixture_rows()
    df = _finest_level(rows)
    assert list(df.columns) == ["zipcode", "naics", "naics_label", "emp_size_band", "estab"]
    assert df["estab"].dtype.kind in "iu"
    row = df[(df["naics"] == "445110") & (df["emp_size_band"] == "All establishments")].iloc[0]
    assert row["zipcode"] == "11206"
    assert row["estab"] == 18


# ---------------------------------------------------------------- category rollup

def test_category_rollup_sums_bands_and_naics_codes_correctly():
    rows = _load_fixture_rows()
    df = _finest_level(rows)
    df.insert(0, "year", 2023)

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.register("_fixture", df)
    con.execute("""
        INSERT INTO analysis.zip_establishments (year, zipcode, naics, naics_label, emp_size_band, estab)
        SELECT year, zipcode, naics, naics_label, emp_size_band, estab FROM _fixture
    """)
    con.unregister("_fixture")

    n = build_zip_category_establishments(con, 2023)
    assert n > 0

    out = con.execute("""
        SELECT category, estab_total, estab_small_1_4, estab_5_9, estab_10_19, estab_20_plus
        FROM analysis.zip_category_establishments
        WHERE year = 2023 AND zipcode = '11206'
    """).df().set_index("category")

    # grocery: NAICS 445110 only (18 total / 7 small / 5 mid, no 10-19 or 20+ rows in fixture)
    assert out.loc["grocery", "estab_total"] == 18
    assert out.loc["grocery", "estab_small_1_4"] == 7
    assert out.loc["grocery", "estab_5_9"] == 5
    assert pd.isna(out.loc["grocery", "estab_10_19"])

    # convenience: NAICS 445120 only
    assert out.loc["convenience", "estab_total"] == 17
    assert out.loc["convenience", "estab_small_1_4"] == 10

    # laundry: SUMS across both mapped codes (812310 + 812320)
    assert out.loc["laundry", "estab_total"] == 9 + 4          # 001 bands summed across both codes
    assert out.loc["laundry", "estab_10_19"] == 3               # 812320's 230 band
    assert out.loc["laundry", "estab_20_plus"] == 2              # 812320's 241 band rolls into 20_plus


def test_undercover_ratio_constant_is_below_one():
    # sanity: the "likely undercoverage" threshold used by zbp-compare must be < 1.0
    assert 0 < UNDERCOVER_RATIO < 1.0
