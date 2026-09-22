"""Offline tests for the RQ-001 macro adapter (src/loci/sources/macro.py):
tidy/rollup logic against a fixture CSV, no network. Mirrors the
fetch-injection pattern in tests exercising lodes_wac/census_zbp -- `fetch`
is swapped for a function returning canned bytes so nothing here touches
FRED.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from loci.sources.macro import (
    COVID_WINDOW_END,
    COVID_WINDOW_START,
    MacroFetchError,
    SERIES_BY_ID,
    SERIES_IDS,
    build,
    build_annual,
    build_monthly,
    fetch_all,
    tidy_series,
)

UNRATE_CSV = (
    b"observation_date,UNRATE\n"
    b"2019-11-01,3.5\n"
    b"2019-12-01,3.5\n"
    b"2020-01-01,3.6\n"
    b"2020-02-01,3.5\n"
    b"2020-03-01,4.4\n"
    b"2020-04-01,14.7\n"
    b"2020-05-01,\n"          # blank observation -- must be dropped, not coerced to 0
    b"2020-06-01,11.1\n"
    b"2021-01-01,6.4\n"
)

USREC_CSV = (
    b"observation_date,USREC\n"
    b"2019-11-01,0\n"
    b"2019-12-01,0\n"
    b"2020-01-01,0\n"
    b"2020-02-01,1\n"
    b"2020-03-01,1\n"
    b"2020-04-01,1\n"
    b"2020-06-01,0\n"
    b"2021-01-01,0\n"
)

MORTGAGE_WEEKLY_CSV = (
    b"observation_date,MORTGAGE30US\n"
    b"2020-03-05,3.29\n"
    b"2020-03-12,3.36\n"
    b"2020-03-19,3.65\n"
    b"2020-03-26,3.50\n"
    b"2020-04-02,3.33\n"
)

FIXTURES = {
    "UNRATE": UNRATE_CSV,
    "USREC": USREC_CSV,
    "MORTGAGE30US": MORTGAGE_WEEKLY_CSV,
}


def _fake_fetch(url: str) -> bytes:
    for series_id, blob in FIXTURES.items():
        if f"id={series_id}" in url:
            return blob
    if "id=MISSING" in url:
        raise AssertionError("MISSING should raise before reaching fetch")
    raise AssertionError(f"no fixture for {url}")


# --------------------------------------------------------------- tidy_series

def test_tidy_series_drops_blank_observations_not_coerces_to_zero():
    df = tidy_series(UNRATE_CSV, SERIES_BY_ID["UNRATE"])
    assert len(df) == 8  # 9 rows in fixture minus one blank
    assert not (df["value"] == 0).any()
    assert set(df.columns) == {"series_id", "date", "value", "freq", "units", "title"}
    assert (df["series_id"] == "UNRATE").all()
    assert df.loc[df["date"] == dt.date(2020, 4, 1), "value"].iloc[0] == pytest.approx(14.7)


def test_tidy_series_rejects_wrong_value_column():
    bad = b"observation_date,SOMETHING_ELSE\n2020-01-01,1.0\n"
    with pytest.raises(MacroFetchError):
        tidy_series(bad, SERIES_BY_ID["UNRATE"])


def test_tidy_series_raises_on_all_blank():
    all_blank = b"observation_date,UNRATE\n2020-01-01,\n2020-02-01,.\n"
    with pytest.raises(MacroFetchError):
        tidy_series(all_blank, SERIES_BY_ID["UNRATE"])


# ----------------------------------------------------------------- fetch_all

def test_fetch_all_raises_on_404_never_writes_a_silent_gap():
    def fetch_404(url):
        raise MacroFetchError(f"{url} -> HTTP 404")

    with pytest.raises(MacroFetchError):
        fetch_all(["UNRATE"], fetch=fetch_404)


def test_fetch_all_unknown_series_id_rejected_before_any_network_call():
    with pytest.raises(MacroFetchError):
        fetch_all(["NOT_A_REAL_SERIES"], fetch=_fake_fetch)


def test_fetch_all_concatenates_requested_series_only():
    df = fetch_all(["UNRATE", "USREC"], fetch=_fake_fetch)
    assert set(df["series_id"]) == {"UNRATE", "USREC"}


# --------------------------------------------------------------- build_monthly

def test_build_monthly_resamples_weekly_mortgage_to_month_mean():
    tidy = fetch_all(["MORTGAGE30US"], fetch=_fake_fetch)
    monthly = build_monthly(tidy)
    assert (monthly["freq"] == "monthly").all()  # weekly source, resampled
    march = monthly.loc[monthly["date"] == dt.date(2020, 3, 1), "value"]
    assert march.iloc[0] == pytest.approx((3.29 + 3.36 + 3.65 + 3.50) / 4)
    april = monthly.loc[monthly["date"] == dt.date(2020, 4, 1), "value"]
    assert april.iloc[0] == pytest.approx(3.33)


def test_build_monthly_flags_covid_window():
    tidy = fetch_all(["UNRATE"], fetch=_fake_fetch)
    monthly = build_monthly(tidy)
    flagged = dict(zip(monthly["date"], monthly["covid_window"]))
    assert flagged[dt.date(2020, 2, 1)] is False
    assert flagged[dt.date(2020, 3, 1)] is True  # window starts 2020-03
    assert flagged[dt.date(2021, 1, 1)] is True  # still inside window
    assert COVID_WINDOW_START == dt.date(2020, 3, 1)
    assert COVID_WINDOW_END == dt.date(2021, 12, 31)


# ---------------------------------------------------------------- build_annual

def test_build_annual_uses_mean_for_rate_series():
    tidy = fetch_all(["UNRATE"], fetch=_fake_fetch)
    monthly = build_monthly(tidy)
    annual = build_annual(monthly)
    row2020 = annual[annual["year"] == 2020].iloc[0]
    expected = pd.Series([3.6, 3.5, 4.4, 14.7, 11.1]).mean()  # 2020-05 was blank, dropped upstream
    assert row2020["value"] == pytest.approx(expected)
    assert row2020["rollup"] == "mean"


def test_build_annual_uses_max_for_usrec_not_mean():
    tidy = fetch_all(["USREC"], fetch=_fake_fetch)
    monthly = build_monthly(tidy)
    annual = build_annual(monthly)
    row2020 = annual[annual["year"] == 2020].iloc[0]
    # months present: 0,1,1,1,0 -> mean=0.6, max=1. Must be max (a recession
    # year is a recession year even if only one flagged month survives).
    assert row2020["value"] == 1
    assert row2020["rollup"] == "max"
    row2019 = annual[annual["year"] == 2019].iloc[0]
    assert row2019["value"] == 0


def test_build_annual_marks_covid_year_when_any_month_is_inside_window():
    tidy = fetch_all(["UNRATE"], fetch=_fake_fetch)
    monthly = build_monthly(tidy)
    annual = build_annual(monthly)
    flagged = dict(zip(annual["year"], annual["covid_window"]))
    assert flagged[2019] is False
    assert flagged[2020] is True
    assert flagged[2021] is True


# -------------------------------------------------------------------- build()

def test_build_end_to_end_reports_fetched_counts():
    result = build(["UNRATE", "USREC"], fetch=_fake_fetch)
    assert result.fetched == {"UNRATE": 8, "USREC": 8}
    assert set(result.monthly["series_id"]) == {"UNRATE", "USREC"}
    assert set(result.annual["series_id"]) == {"UNRATE", "USREC"}
    assert list(result.annual.columns) == [
        "series_id", "year", "value", "units", "title", "rollup", "covid_window"]


def test_series_ids_registry_has_no_duplicates_and_every_entry_has_rollup():
    assert len(SERIES_IDS) == len(set(SERIES_IDS))
    for sid in SERIES_IDS:
        meta = SERIES_BY_ID[sid]
        assert meta["rollup"] in {"mean", "max"}
        assert meta["freq"] in {"monthly", "weekly"}
