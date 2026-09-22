"""Offline tests for irs_soi_history.py (RQ-001 IRS SOI ZIP income panel).

No network, no warehouse file, no xlrd dependency: the legacy-format tests
build the raw (header=None) grid directly rather than round-tripping through
a real .xls file, since xlrd is deliberately not a project dependency (see
module docstring). `fetch_modern_year` is exercised against a pre-cached CSV
so it never hits the network either.
"""
from __future__ import annotations

import zipfile

import pandas as pd
import pytest

from loci.sources import irs_soi_history as H


# ===========================================================================
# _num / _zip5 coercion
# ===========================================================================


def test_num_suppressed_markers_are_null_not_zero():
    assert H._num("*") is None
    assert H._num("**") is None
    assert H._num(".") is None
    assert H._num("-") is None
    assert H._num("") is None
    assert H._num(None) is None
    assert H._num(float("nan")) is None


def test_num_parses_plain_and_comma_numbers():
    assert H._num(1234) == 1234.0
    assert H._num("1,234") == 1234.0
    assert H._num(1234.0) == 1234.0


def test_zip5_pads_int_like_cells_and_rejects_non_zip():
    assert H._zip5(10001) == "10001"
    assert H._zip5(6390.0) == "06390"
    assert H._zip5("501") == "00501"
    assert H._zip5("TOTAL") is None
    assert H._zip5(None) is None
    assert H._zip5(float("nan")) is None


# ===========================================================================
# find_state_member -- tolerant of all four legacy filename conventions
# ===========================================================================


@pytest.mark.parametrize("name", [
    "1998ZIPCode/98zp33ny.xls",
    "2001ZIPCode/01zp33ny.xls",
    "zptab02ny.xls",
    "2004ZipCode/ZIP Code 2004 NY.xls",
    "09zp33ny.xls",
])
def test_find_state_member_matches_every_naming_convention(name):
    namelist = ["2004ZipCode/ZIP Code 2004 AK.xls", name, "2004ZipCode/ZIP Code 2004 AL.xls"]
    assert H.find_state_member(namelist, "ny") == name


def test_find_state_member_raises_on_zero_or_multiple_matches():
    with pytest.raises(RuntimeError):
        H.find_state_member(["AK.xls", "AL.xls"], "ny")
    with pytest.raises(RuntimeError):
        H.find_state_member(["ny.xls", "NY.xls"], "ny")


# ===========================================================================
# parse_legacy_ny_sheet -- one constructed grid per format bucket
# ===========================================================================


def test_parse_fmt_a_1998_style_zip_is_row_label():
    # col0=label, col1=n1, col2=exempt total, col3=dependents, col4=agi($k),
    # col5=n_wages, col6=a_wages($k); year 2005 also uses FMT_A.
    rows = [
        ["NEW YORK", 100, 200, 30, 5000, 90, 4000, 80, 1000],   # state total -- must be skipped (>5 digit-ish label rejected: text)
        ["10001", 9636, 13492, 2488, 527449, 7440, 343493, 5819, 24072],
        ["Under $10,000", 2030, 2369, 418, 1068, 1236, 9633, 861, 1264],  # bracket row -- skipped
        ["", None, None, None, None, None, None, None, None],            # blank separator
        ["10002", 35244, 67088, 21595, 824484, 29007, 629472, 21330, 35235],
        ["Under $10,000", 11949, 18636, 5246, 64344, 8414, 45669, 6048, 3254],
    ]
    raw = pd.DataFrame(rows)
    out = H.parse_legacy_ny_sheet(raw, 1998)
    assert sorted(out["zip"]) == ["10001", "10002"]
    row = out.loc[out["zip"] == "10001"].iloc[0]
    assert row["n1"] == 9636
    assert row["agi"] == 527449 * 1000.0   # legacy $ thousands -> dollars
    assert row["a_wages"] == 343493 * 1000.0
    assert row["any_suppressed"] == False  # noqa: E712


def test_parse_fmt_d_2007_style_bracket_label_col0_zip_col1():
    # col0=bracket label ('TOTAL' on the zip block's first row), col1=zip,
    # col2=n1, ... col7=agi, col8=n_wages, col9=a_wages.
    rows = [
        [None, 501, 294, 100, 50, 562, 168, 6275, 232, 5450, 40],
        ["Under $10,000", 0, 34, 5, 2, 67, 24, 240, 20, 128, 5],
        [None, None, None, None, None, None, None, None, None, None, None],
        [None, 10001, 9636, 3000, 1500, 13492, 2488, 527449, 7440, 343493, 5819],
    ]
    raw = pd.DataFrame(rows)
    out = H.parse_legacy_ny_sheet(raw, 2007)
    assert sorted(out["zip"]) == ["00501", "10001"]
    row = out.loc[out["zip"] == "00501"].iloc[0]
    assert row["n1"] == 294
    assert row["agi"] == 6275 * 1000.0
    assert row["n_wages"] == 232
    assert row["a_wages"] == 5450 * 1000.0


def test_parse_fmt_f_2008_style_bracket_label_col0_zip_col1_no_wage_count():
    # Same shape as FMT_D (bracket label col0, blank on the total row; zip
    # col1, 0 = state total) but with only ONE wages column (amount, no
    # separate return count) -- col2=n1, ... col7=agi, col8=a_wages.
    rows = [
        [None, 0, 8964732, 2888049, 5920985, 16716515, 3128140, 623353087, 435016931],
        ["Under $10,000", 0, 1709042, 147950, 1030074, 1768273, 278514, 6722607, 6582929],
        [None, None, None, None, None, None, None, None, None],
        [None, 6390, 161, 100, 50, 279, 74, 14158, 6919],
    ]
    raw = pd.DataFrame(rows)
    out = H.parse_legacy_ny_sheet(raw, 2008)
    assert sorted(out["zip"]) == ["06390"]  # the 0-labeled state-total block must be dropped
    row = out.iloc[0]
    assert row["n1"] == 161
    assert row["agi"] == 14158 * 1000.0
    assert row["n_wages"] is None  # 2008 published no wage-return-count column
    assert row["a_wages"] == 6919 * 1000.0


def test_parse_legacy_flags_any_suppressed_without_coercing_to_zero():
    rows = [
        [None, 501, "*", 100, 50, 562, 168, "*", 232, "**", 40],
    ]
    raw = pd.DataFrame(rows)
    out = H.parse_legacy_ny_sheet(raw, 2007)
    row = out.iloc[0]
    assert row["any_suppressed"] == True  # noqa: E712
    assert row["n1"] is None
    assert row["agi"] is None
    assert row["a_wages"] is None


def test_parse_legacy_raises_on_unknown_year():
    with pytest.raises(ValueError):
        H.parse_legacy_ny_sheet(pd.DataFrame([[1, 2, 3]]), 2003)


def test_parse_legacy_raises_rather_than_silently_returning_empty():
    raw = pd.DataFrame([[None] * 11])  # a sheet with nothing parseable
    with pytest.raises(RuntimeError):
        H.parse_legacy_ny_sheet(raw, 2008)


# ===========================================================================
# fetch_modern_year -- pre-cached CSV, no network
# ===========================================================================


def _write_modern_csv(path, rows):
    header = "STATEFIPS,STATE,zipcode,agi_stub,N1,A00100,N00200,A00200\n"
    lines = [header] + [",".join(str(v) for v in r) + "\n" for r in rows]
    path.write_text("".join(lines))


def test_fetch_modern_year_filters_state_and_zip_and_builds_total_row(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    csv_path = raw_dir / "2022_zpallagi.csv"
    _write_modern_csv(csv_path, [
        ["36", "NY", "00000", 1, 900000, 8000000, 700000, 6000000],   # NY state total row -- not a real zip, must survive the STATE filter but be dropped by the zip-universe filter
        ["36", "NY", "10001", 1, 100, 1000, 80, 800],
        ["36", "NY", "10001", 2, 50, 2000, 45, 1900],
        ["06", "CA", "90210", 1, 999, 9999, 999, 9999],               # wrong state -- must be dropped
        ["36", "NY", "99999", 1, 10, 100, 8, 90],                     # not in the nyc zip universe -- must be dropped
    ])
    out = H.fetch_modern_year(2022, raw_dir, nyc_zips={"10001"})
    assert set(out["zip"]) == {"10001"}
    brackets = out.loc[out["agi_stub"] != 0].sort_values("agi_stub")
    assert list(brackets["agi_stub"]) == [1, 2]
    total = out.loc[out["agi_stub"] == 0].iloc[0]
    assert total["n1"] == 150
    assert total["agi"] == 3000 * 1000.0
    assert total["a_wages"] == 2700 * 1000.0


def test_fetch_modern_year_tolerates_column_casing_drift(tmp_path):
    # Confirmed live: 2011 ships 'ZIPCODE' (upper), 2012 ships 'AGI_STUB'
    # (upper), while every other year ships both lowercase. Must not raise.
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    csv_path = raw_dir / "2011_zpallagi.csv"
    csv_path.write_text(
        "STATEFIPS,STATE,ZIPCODE,agi_stub,N1,A00100,N00200,A00200\n"
        "36,NY,10001,1,100,1000,80,800\n"
    )
    out = H.fetch_modern_year(2011, raw_dir, nyc_zips={"10001"})
    assert set(out["zip"]) == {"10001"}


def test_fetch_modern_year_raises_on_zero_ny_rows(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    csv_path = raw_dir / "2022_zpallagi.csv"
    _write_modern_csv(csv_path, [["06", "CA", "90210", 1, 999, 9999, 999, 9999]])
    with pytest.raises(RuntimeError):
        H.fetch_modern_year(2022, raw_dir, nyc_zips={"10001"})


def test_fetch_modern_year_raises_when_nothing_matches_nyc_universe(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    csv_path = raw_dir / "2022_zpallagi.csv"
    _write_modern_csv(csv_path, [["36", "NY", "12345", 1, 10, 100, 8, 90]])
    with pytest.raises(RuntimeError):
        H.fetch_modern_year(2022, raw_dir, nyc_zips={"10001"})


# ===========================================================================
# ingest_all -- log-and-continue on a failed year
# ===========================================================================


def test_ingest_all_logs_and_continues_on_a_failed_year(tmp_path, monkeypatch):
    def fake_legacy(year, raw_dir, session=None):
        if year == 1998:
            raise RuntimeError("simulated fetch failure")
        return pd.DataFrame([{
            "zip": "10001", "tax_year": year, "n1": 10.0, "agi": 100000.0,
            "n_wages": 8.0, "a_wages": 80000.0, "any_suppressed": False,
        }])

    def fake_modern(year, raw_dir, zips, session=None):
        return pd.DataFrame([
            {"zip": "10001", "tax_year": year, "agi_stub": 0, "n1": 20.0,
             "agi": 200000.0, "n_wages": 18.0, "a_wages": 180000.0, "any_suppressed": False},
        ])

    monkeypatch.setattr(H, "fetch_legacy_year", fake_legacy)
    monkeypatch.setattr(H, "fetch_modern_year", fake_modern)

    panel, results = H.ingest_all(
        tmp_path / "raw", tmp_path / "out.parquet",
        years=[1998, 2001, 2011], zips={"10001"},
    )
    by_year = {r.year: r for r in results}
    assert by_year[1998].ok is False
    assert "simulated fetch failure" in by_year[1998].error
    assert by_year[2001].ok is True
    assert by_year[2011].ok is True
    assert sorted(panel["tax_year"].unique().tolist()) == [2001, 2011]
    assert (tmp_path / "out.parquet").exists()


def test_ingest_all_raises_if_every_year_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "fetch_legacy_year", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(H, "fetch_modern_year", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        H.ingest_all(tmp_path / "raw", tmp_path / "out.parquet", years=[1998, 2011], zips={"10001"})
