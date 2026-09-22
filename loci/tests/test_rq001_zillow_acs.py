"""Offline tests for the RQ-001 Zillow (COST) and ACS ZCTA panel (DEMAND)
ingest adapters. No network access: every Census/Zillow HTTP call is
monkeypatched, matching the existing test_acs.py convention of stubbing
`requests.get` / `_census_key` rather than hitting the live API."""
import math

import pandas as pd
import pytest

from loci.sources.universal import acs_zcta_panel as azp
from loci.sources.universal import zillow


# ----------------------------------------------------------------- Zillow --

def _write_zillow_csv(path, rows, months=("2020-01-31", "2020-02-28", "2021-01-31")):
    cols = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName",
            "State", "City", "Metro", "CountyName", *months]
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)


def test_load_nyc_tidy_filters_to_five_boroughs(tmp_path):
    csv_path = tmp_path / "zhvi.csv"
    _write_zillow_csv(csv_path, [
        [1, 1, "11201", "Zip", "New York", "NY", "Brooklyn", "New York-Newark-Jersey City, NY-NJ-PA",
         "Kings County", 500000, 501000, 520000],
        [2, 2, "10001", "Zip", "New York", "NY", "New York", "New York-Newark-Jersey City, NY-NJ-PA",
         "New York County", 900000, 905000, 950000],
        [3, 3, "11550", "Zip", "New York", "NY", "Hempstead", "New York-Newark-Jersey City, NY-NJ-PA",
         "Nassau County", 400000, 401000, 410000],  # NY state but NOT one of the 5 boroughs
        [4, 4, "60601", "Zip", "Illinois", "IL", "Chicago", "Chicago-Naperville-Elgin, IL-IN-WI",
         "Cook County", 300000, 301000, 310000],
    ])
    long_df = zillow.load_nyc_tidy("zhvi", path=csv_path)
    assert set(long_df["zip"]) == {"11201", "10001"}
    assert set(long_df["index"]) == {"zhvi"}
    assert len(long_df) == 2 * 3  # 2 NYC zips x 3 month columns


def test_load_nyc_tidy_raises_when_filter_matches_nothing(tmp_path):
    csv_path = tmp_path / "zhvi.csv"
    _write_zillow_csv(csv_path, [
        [1, 1, "60601", "Zip", "Illinois", "IL", "Chicago", "Chicago-Naperville-Elgin, IL-IN-WI",
         "Cook County", 300000, 301000, 310000],
    ])
    with pytest.raises(RuntimeError, match="matched zero"):
        zillow.load_nyc_tidy("zhvi", path=csv_path)


def test_load_nyc_tidy_raises_on_empty_csv(tmp_path):
    csv_path = tmp_path / "zhvi.csv"
    _write_zillow_csv(csv_path, [])
    with pytest.raises(RuntimeError, match="zero rows"):
        zillow.load_nyc_tidy("zhvi", path=csv_path)


def test_annualize_computes_mean_and_n_months(tmp_path):
    csv_path = tmp_path / "zhvi.csv"
    _write_zillow_csv(csv_path, [
        [1, 1, "11201", "Zip", "New York", "NY", "Brooklyn", "New York-Newark-Jersey City, NY-NJ-PA",
         "Kings County", 100, 200, 900],  # 2020: 100,200 -> mean 150, n=2 ; 2021: 900 -> mean 900, n=1
    ])
    long_df = zillow.load_nyc_tidy("zhvi", path=csv_path)
    ann = zillow.annualize(long_df)
    row_2020 = ann[(ann["zip"] == "11201") & (ann["year"] == 2020)].iloc[0]
    row_2021 = ann[(ann["zip"] == "11201") & (ann["year"] == 2021)].iloc[0]
    assert row_2020["value_mean"] == 150.0 and row_2020["n_months"] == 2
    assert row_2021["value_mean"] == 900.0 and row_2021["n_months"] == 1


def test_fetch_raw_raises_on_empty_body(tmp_path, monkeypatch):
    class _Resp:
        content = b""
        def raise_for_status(self):
            return None
    monkeypatch.setattr(zillow, "requests", type("R", (), {"get": staticmethod(lambda *a, **k: _Resp())}))
    monkeypatch.setattr(zillow, "RAW_FILES", {"zhvi": tmp_path / "zhvi.csv", "zori": tmp_path / "zori.csv"})
    with pytest.raises(RuntimeError, match="empty body"):
        zillow.fetch_raw("zhvi", force=True)


def test_fetch_raw_rejects_unknown_index():
    with pytest.raises(ValueError):
        zillow.fetch_raw("zrent")


# ---------------------------------------------------------------- ACS ZCTA --

def test_moe_proportion_matches_handbook_formula():
    x, x_moe, y, y_moe = 190.0, 20.0, 380.0, 30.0
    p = x / y
    expected = math.sqrt(x_moe ** 2 - (p ** 2) * (y_moe ** 2)) / y
    assert math.isclose(azp._moe_proportion(x, x_moe, y, y_moe), expected, rel_tol=1e-9)


def test_moe_proportion_falls_back_when_subtraction_negative():
    x, x_moe, y, y_moe = 99.0, 1.0, 100.0, 50.0
    p = x / y
    assert (x_moe ** 2 - (p ** 2) * (y_moe ** 2)) < 0
    expected = math.sqrt(x_moe ** 2 + (p ** 2) * (y_moe ** 2)) / y
    assert math.isclose(azp._moe_proportion(x, x_moe, y, y_moe), expected, rel_tol=1e-9)


def test_moe_proportion_handles_missing_denominator():
    assert azp._moe_proportion(10.0, 2.0, None, 3.0) is None
    assert azp._moe_proportion(10.0, 2.0, 0.0, 3.0) is None


def test_clean_handles_census_sentinels():
    assert azp._clean("4839") == 4839.0
    assert azp._clean("-666666666") is None
    assert azp._clean("") is None
    assert azp._clean(None) is None


def test_sum_cells_applies_handbook_sum_rule():
    rec = {"A_001E": "10", "A_001M": "3", "A_002E": "20", "A_002M": "4"}
    est, moe = azp._sum_cells(rec, ("A_001", "A_002"))
    assert est == 30.0
    assert math.isclose(moe, math.sqrt(3 ** 2 + 4 ** 2))


def test_sum_cells_all_null_returns_none():
    rec = {"A_001E": "-666666666", "A_001M": "3"}
    est, moe = azp._sum_cells(rec, ("A_001",))
    assert est is None and moe is None


def test_edu_spec_switches_table_at_2012():
    assert azp.edu_spec(2011)["table"] == "B15002"
    assert azp.edu_spec(2012)["table"] == "B15003"
    assert azp.edu_spec(2024)["table"] == "B15003"


def test_zcta_geography_vintage_switches_at_2020():
    assert azp.zcta_geography_vintage(2019) == 2010
    assert azp.zcta_geography_vintage(2020) == 2020
    assert azp.zcta_geography_vintage(2011) == 2010
    assert azp.zcta_geography_vintage(2024) == 2020


def test_variables_for_returns_paired_e_and_m_columns():
    for year in (2011, 2012, 2023):
        gv = azp.variables_for(year)
        assert len(gv) % 2 == 0
        stems = {v[:-1] for v in gv}
        for stem in stems:
            assert f"{stem}E" in gv and f"{stem}M" in gv
        assert len(gv) == len(set(gv))  # no accidental duplicates
        # 2011's B15002 branch (8 numerator cells) exceeds the Census API's
        # 50-variable cap (52) -- that's what MAX_GET_VARS chunking is for,
        # so it's asserted against MAX_GET_VARS-based chunk count, not <=50.
        n_chunks = -(-len(gv) // azp.MAX_GET_VARS)
        assert n_chunks == (2 if year == 2011 else 1)


def _synthetic_payload(year: int, zctas: list[str]) -> list[list[str]]:
    """Build a fake Census [header, row, ...] response: every requested
    variable's estimate encodes the ZCTA + variable name as a small, checkable
    number; MOEs are a fixed 10% of the estimate."""
    getvars = azp.variables_for(year)
    header = getvars + ["state", "zip code tabulation area"]
    rows = []
    for i, z in enumerate(zctas):
        row = []
        for v in getvars:
            # deterministic per (zcta, variable) value so shares are checkable
            base = 1000 + i * 10 + (hash(v) % 7)
            row.append(str(base))
        row += ["36", z]
        rows.append(row)
    return [header] + rows


def test_parse_vintage_computes_shares_and_carries_boundary_flag():
    year = 2023
    zctas = ["10001", "11201"]
    data = _synthetic_payload(year, zctas)
    df = azp._parse_vintage(year, data)
    assert set(df["zcta"]) == set(zctas)
    assert (df["acs_year"] == year).all()
    assert (df["zcta_geography_vintage"] == 2020).all()
    assert (df["education_table"] == "B15003").all()
    # shares are numerator/denominator of the synthetic estimates
    for _, row in df.iterrows():
        assert 0 <= row["age_20_34_share"]
        assert 0 <= row["bachelors_plus_share"]
    assert "age_20_34_denom_e" not in df.columns  # denominator dropped after use


def test_parse_vintage_2011_uses_b15002():
    data = _synthetic_payload(2011, ["10001"])
    df = azp._parse_vintage(2011, data)
    assert (df["education_table"] == "B15002").all()
    assert (df["zcta_geography_vintage"] == 2010).all()


def test_nyc_zcta_set_filters_to_five_boroughs(monkeypatch):
    fake_cw = pd.DataFrame({
        "zipcode": ["10001", "11201", "11550", "07030"],
        "county_fips": ["36061", "36047", "36059", "34017"],  # 36059=Nassau, 34017=Hudson NJ
    })
    monkeypatch.setattr(azp, "zcta_county_crosswalk", lambda: fake_cw)
    zctas = azp.nyc_zcta_set()
    assert zctas == {"10001", "11201"}


def test_fetch_vintage_raw_raises_without_key(monkeypatch, tmp_path):
    monkeypatch.setattr(azp, "RAW_DIR", tmp_path)
    monkeypatch.setattr(azp, "_census_key", lambda: "")
    with pytest.raises(RuntimeError, match="CENSUS_API_KEY"):
        azp.fetch_vintage_raw(2023, force=True)


def test_fetch_vintage_raw_raises_on_zero_rows(monkeypatch, tmp_path):
    class _Resp:
        def raise_for_status(self):
            return None
        def json(self):
            return [["B01003_001E"]]  # header only, no data rows
    monkeypatch.setattr(azp, "RAW_DIR", tmp_path)
    monkeypatch.setattr(azp, "_census_key", lambda: "fake-key")
    monkeypatch.setattr(azp.requests, "get", lambda *a, **k: _Resp())
    with pytest.raises(RuntimeError, match="zero data rows"):
        azp.fetch_vintage_raw(2023, force=True)


def test_fetch_vintage_raw_qualifies_state_through_2019(monkeypatch, tmp_path):
    seen_params = {}

    class _Resp:
        def raise_for_status(self):
            return None
        def json(self):
            return _synthetic_payload(seen_params["year"], ["10001"])

    def _get(url, params=None, timeout=None):
        seen_params.update(params)
        seen_params["year"] = int(url.rsplit("/", 3)[1])
        return _Resp()

    monkeypatch.setattr(azp, "RAW_DIR", tmp_path)
    monkeypatch.setattr(azp, "_census_key", lambda: "fake-key")
    monkeypatch.setattr(azp.requests, "get", _get)

    azp.fetch_vintage_raw(2019, force=True)
    assert seen_params.get("in") == "state:36"

    seen_params.clear()
    azp.fetch_vintage_raw(2020, force=True)
    assert "in" not in seen_params


def test_build_vintage_filters_to_nyc(monkeypatch, tmp_path):
    year = 2023
    data = _synthetic_payload(year, ["10001", "11201", "99999"])
    monkeypatch.setattr(azp, "fetch_vintage_raw", lambda y, force=False: data)
    monkeypatch.setattr(azp, "nyc_zcta_set", lambda: {"10001", "11201"})
    out = azp.build_vintage(year)
    assert set(out["zcta"]) == {"10001", "11201"}


def test_build_vintage_raises_when_nyc_filter_empty(monkeypatch):
    year = 2023
    data = _synthetic_payload(year, ["99999"])
    monkeypatch.setattr(azp, "fetch_vintage_raw", lambda y, force=False: data)
    monkeypatch.setattr(azp, "nyc_zcta_set", lambda: {"10001", "11201"})
    with pytest.raises(RuntimeError, match="NYC filter matched zero"):
        azp.build_vintage(year)


def test_build_panel_writes_one_parquet_per_vintage_plus_combined(monkeypatch, tmp_path):
    monkeypatch.setattr(azp, "INTERIM_DIR", tmp_path)
    monkeypatch.setattr(azp, "nyc_zcta_set", lambda: {"10001", "11201"})

    def _fake_build_vintage(year, force=False):
        data = _synthetic_payload(year, ["10001", "11201"])
        return azp._parse_vintage(year, data)

    monkeypatch.setattr(azp, "build_vintage", _fake_build_vintage)
    panel = azp.build_panel(years=[2011, 2023])
    assert set(panel["acs_year"]) == {2011, 2023}
    assert (tmp_path / "acs_zcta_2011.parquet").exists()
    assert (tmp_path / "acs_zcta_2023.parquet").exists()
    assert (tmp_path / "acs_zcta_panel.parquet").exists()
    # 2011 boundary is 2010, 2023 boundary is 2020 -- both vintages present
    assert set(panel.loc[panel["acs_year"] == 2011, "zcta_geography_vintage"]) == {2010}
    assert set(panel.loc[panel["acs_year"] == 2023, "zcta_geography_vintage"]) == {2020}
