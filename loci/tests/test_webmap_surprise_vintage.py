"""WHICH scored vintage the surprise layer draws (audit finding 8).

`model_version` is `'<semver>+<8 hex git-ish hash>'`. Ordering two vintages by
that string orders them BY THE HEX, which is arbitrary. The warehouse carried
five `2026-09` vintages on 2026-09-16 whose true issue order (by
`analysis.forecast_run.issued_at`) was

    0.1.0+f7d190df  2026-09-14 11:53
    0.1.1+3cd0e269  2026-09-14 22:51
    0.1.1+f1cb6628  2026-09-14 23:27
    0.1.1+ae3eadb3  2026-09-15 08:54
    0.1.1+51bab17f  2026-09-15 17:53   <- the newest

while the lexicographic maximum is `0.1.1+f1cb6628`, purely on `'f' > '5'`.
sql/028:330 fixed `analysis.forecast_latest` this way and the fix is verified
live; `viz/webmap_export.surprise_vintage` was the unfixed analogue.

The hashes below are the REAL ones, ordered so the string sort and the clock
disagree: any implementation that reaches for `model_version DESC` first fails
these tests rather than passing them by luck.

TWO THINGS ARE PINNED, and the second is as important as the first:
  1. the frozen-LATER vintage wins a same-`scored_month` tie;
  2. `scored_month` still DOMINATES the clock -- a 2023-01 vintage scored last
     month beats a 2026-09 vintage nothing has scored yet, because an unscored
     forecast has no surprise. Putting the timestamp first would invert that.
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci import db as locidb
from loci.viz import webmap_export as wx

#: earlier clock, HIGHER string sort -- the trap
OLD_HASH = "0.1.1+f1cb6628"
OLD_AT = dt.datetime(2026, 9, 14, 23, 26, 50)
#: later clock, LOWER string sort -- the right answer
NEW_HASH = "0.1.1+51bab17f"
NEW_AT = dt.datetime(2026, 9, 15, 17, 53, 22)

SURPRISE_DDL = """
CREATE TABLE analysis.forecast_surprise_nta (
    issued_month VARCHAR, model_version VARCHAR, scored_month VARCHAR,
    horizon_elapsed INTEGER, nta_code VARCHAR, category VARCHAR,
    n_addresses BIGINT, n_cells BIGINT, realized DOUBLE, expected DOUBLE,
    surprise DOUBLE, z_naive DOUBLE, z_clustered DOUBLE)
"""
RUN_DDL = """
CREATE TABLE analysis.forecast_run (
    issued_month VARCHAR, model_version VARCHAR, issued_at TIMESTAMP)
"""
FORECAST_DDL = """
CREATE TABLE analysis.forecast (
    forecast_id VARCHAR, issued_month VARCHAR, model_version VARCHAR,
    frozen_at TIMESTAMP)
"""


@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute(SURPRISE_DDL)
    return c


def _surprise(con, issued_month, model_version, scored_month, horizon=12,
              nta="BK0101", category="(all)"):
    con.execute(
        "INSERT INTO analysis.forecast_surprise_nta (issued_month, model_version, "
        "scored_month, horizon_elapsed, nta_code, category, n_addresses, n_cells, "
        "realized, expected, surprise, z_naive, z_clustered) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [issued_month, model_version, scored_month, horizon, nta, category,
         100, 6, 3.0, 2.0, 1.0, 0.8, 0.3])


def _run(con, issued_month, model_version, issued_at):
    con.execute("INSERT INTO analysis.forecast_run "
                "(issued_month, model_version, issued_at) VALUES (?,?,?)",
                [issued_month, model_version, issued_at])


def _forecast(con, issued_month, model_version, frozen_at):
    con.execute("INSERT INTO analysis.forecast "
                "(forecast_id, issued_month, model_version, frozen_at) "
                "VALUES (?,?,?,?)",
                [f"f-{issued_month}-{model_version}", issued_month,
                 model_version, frozen_at])


# ---------------------------------------------------------------- the defect
def test_the_frozen_later_vintage_wins_a_same_month_tie(con):
    """Two 2026-09 vintages, both scored in 2026-09, whose hash strings sort
    the WRONG way. The pick must be the one ISSUED last."""
    con.execute(RUN_DDL)
    _surprise(con, "2026-09", OLD_HASH, "2026-09")
    _surprise(con, "2026-09", NEW_HASH, "2026-09")
    _run(con, "2026-09", OLD_HASH, OLD_AT)
    _run(con, "2026-09", NEW_HASH, NEW_AT)

    v = wx.surprise_vintage(con)
    assert v is not None
    assert v["modelVersion"] == NEW_HASH, (
        "picked the lexicographic maximum, not the newest vintage")
    assert v["scoredMonth"] == "2026-09"


def test_the_string_sort_alone_would_pick_the_other_one(con):
    """The trap is real, not hypothetical: with the clock removed the old
    ORDER BY returns the WRONG vintage on exactly this data. If this ever
    fails, the fixture stopped exercising the bug."""
    _surprise(con, "2026-09", OLD_HASH, "2026-09")
    _surprise(con, "2026-09", NEW_HASH, "2026-09")
    row = con.execute("""
        SELECT model_version FROM analysis.forecast_surprise_nta
        WHERE scored_month IS NOT NULL
        GROUP BY 1 ORDER BY model_version DESC LIMIT 1""").fetchone()
    assert row[0] == OLD_HASH


def test_the_clock_can_come_from_the_forecast_table_instead(con):
    """`analysis.forecast_run` is preferred because it is six rows wide, but a
    database that has only `analysis.forecast.frozen_at` -- the column sql/028
    itself uses -- must get the same answer, not the string sort."""
    con.execute(FORECAST_DDL)
    _surprise(con, "2026-09", OLD_HASH, "2026-09")
    _surprise(con, "2026-09", NEW_HASH, "2026-09")
    _forecast(con, "2026-09", OLD_HASH, OLD_AT)
    _forecast(con, "2026-09", NEW_HASH, NEW_AT)

    assert wx.surprise_vintage(con)["modelVersion"] == NEW_HASH


# ------------------------------------------------- what must NOT be inverted
def test_scored_month_still_dominates_the_clock(con):
    """A 2023-01 vintage issued LONG AGO but scored in 2025-01 beats a 2026-09
    vintage issued yesterday and scored in 2024-01. An unscored — or
    stale-scored — forecast has no surprise to draw, and no amount of
    freshness in the ISSUE date changes that."""
    con.execute(RUN_DDL)
    _surprise(con, "2023-01", "0.1.0+f7d190df", "2025-01", horizon=24)
    _surprise(con, "2026-09", NEW_HASH, "2024-01", horizon=12)
    _run(con, "2023-01", "0.1.0+f7d190df", dt.datetime(2026, 9, 14, 11, 44))
    _run(con, "2026-09", NEW_HASH, NEW_AT)

    v = wx.surprise_vintage(con)
    assert v["scoredMonth"] == "2025-01"
    assert v["issuedMonth"] == "2023-01"
    assert v["horizonElapsed"] == 24


# ----------------------------------------------------------- the degradation
def test_an_old_database_with_no_clock_degrades_instead_of_raising(con):
    """Neither `forecast_run` nor `forecast` present. The pick is then the
    pre-fix version-string order — wrong, but the export still runs, which is
    what `_relation_columns` has always guaranteed the other blocks."""
    _surprise(con, "2026-09", OLD_HASH, "2026-09")
    _surprise(con, "2026-09", NEW_HASH, "2026-09")
    v = wx.surprise_vintage(con)
    assert v is not None
    assert v["modelVersion"] == OLD_HASH


def test_no_surprise_relation_at_all_returns_none():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    assert wx.surprise_vintage(c) is None


def test_nothing_scored_yet_returns_none(con):
    con.execute(RUN_DDL)
    _surprise(con, "2026-09", NEW_HASH, None)
    assert wx.surprise_vintage(con) is None


# --------------------------------------------- the same defect, second site
def test_the_header_vintage_is_picked_by_frozen_at_not_by_hash(con):
    """`forecast_vintage()` stamps the model version on every exported map
    header, and it picked `max(model_version)` within the newest issued month.
    Unlike `surprise_vintage` this one MANIFESTED on the live warehouse."""
    con.execute(FORECAST_DDL)
    _forecast(con, "2026-09", OLD_HASH, OLD_AT)
    _forecast(con, "2026-09", NEW_HASH, NEW_AT)
    assert wx.forecast_vintage(con)["modelVersion"] == NEW_HASH
