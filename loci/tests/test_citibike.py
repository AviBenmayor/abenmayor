"""Citi Bike ingest and address measures (phase 1).

The tests that matter here are the ones guarding the bug classes this project
keeps getting bitten by:

  * fusing two ID SPACES (pre-2021 integer station ids vs the modern
    '5905.14' scheme) -- a fake opening and a fake gap, or a fake doubling;
  * a SILENT ZERO (a holiday `NOT IN (NULL)` deleting a whole month, an empty
    window, a truncated file divided by a full calendar);
  * a SHARE that is not a share, because a union was summed instead of OR'd;
  * an ELIGIBILITY GATE arriving by omission (owner rule 2026-09-13).
"""
from __future__ import annotations

import datetime as dt
import pathlib
import zipfile

import duckdb
import pandas as pd
import pytest

from loci.sources.cities.nyc import citibike as cb
from loci.sources.cities.nyc import mta_ridership as mr

LYFT_HEADER = ("ride_id,rideable_type,started_at,ended_at,start_station_name,"
               "start_station_id,end_station_name,end_station_id,start_lat,"
               "start_lng,end_lat,end_lng,member_casual")
LEGACY_HEADER = ('"tripduration","starttime","stoptime","start station id",'
                 '"start station name","start station latitude",'
                 '"start station longitude","end station id","usertype","birth year"')


# --------------------------------------------------------------- the schema

def test_lyft_header_is_recognised():
    assert cb.classify_header(LYFT_HEADER.split(",")) == "lyft_2021"


def test_lyft_header_survives_a_bom_and_quotes():
    hdr = '﻿"ride_id","rideable_type","started_at","ended_at",' \
          '"start_station_name","start_station_id","end_station_name",' \
          '"end_station_id","start_lat","start_lng","end_lat","end_lng",' \
          '"member_casual"'
    assert cb.classify_header(hdr.split(",")) == "lyft_2021"


def test_legacy_header_is_named_not_guessed():
    assert cb.classify_header(LEGACY_HEADER.split(",")) == "legacy_pre2021"


def test_unknown_header_raises_rather_than_normalising_to_null():
    with pytest.raises(cb.CitibikeError, match="neither the"):
        cb.classify_header(["a", "b", "c"])


def test_the_refusal_text_still_names_the_id_space_problem():
    """`refuse_legacy` is no longer New York's path -- the legacy era is READ --
    but it is still the one place the ID-SPACE argument is written down, and it
    is still what an unprobed system's files hit. A future reader who only sees
    'unsupported' will reasonably decide to map the columns, which is the easy
    half and the wrong half."""
    with pytest.raises(cb.CitibikeError) as e:
        cb.refuse_legacy("202001")
    msg = str(e.value)
    assert "station ids" in msg and "5905.14" in msg
    assert "2021-02" in msg


def test_the_pre_2021_cap_is_gone_and_the_window_starts_at_the_first_month(
        monkeypatch):
    """CAP 5. The default start was 2023-01 and anything before 2021-02 RAISED.
    Both are gone (owner 2026-09-16): the bucket publishes from 2013-06 and all
    of it is planned, with the pre-cutoff months marked 'legacy'."""
    monkeypatch.setattr(cb, "list_bucket", lambda **k: [
        {"key": "2020-citibike-tripdata.zip", "size": 1, "last_modified": "x"},
        {"key": "2021-citibike-tripdata.zip", "size": 1, "last_modified": "x"},
        {"key": "202102-citibike-tripdata.zip", "size": 1, "last_modified": "x"},
    ])
    out, rep = cb.plan((2020, 12), (2021, 2))
    assert [(e["year"], e["month"], e["era"]) for e in out] == [
        (2020, 12, "legacy"), (2021, 1, "legacy"), (2021, 2, "lyft")]
    assert rep["legacy_months"] == 2 and rep["lyft_months"] == 1
    assert cb.DEFAULT_START == (2013, 6)
    import inspect
    assert inspect.signature(cb.ingest).parameters["start"].default == (2013, 6)


def test_a_month_before_the_feed_itself_is_still_refused(monkeypatch):
    """Removing the cap is not the same as inventing data. 2013-05 has no file:
    planning it would put a hole at the front of the panel."""
    monkeypatch.setattr(cb, "list_bucket", lambda **k: [
        {"key": "2013-citibike-tripdata.zip", "size": 1, "last_modified": "x"}])
    with pytest.raises(cb.CitibikeError, match="before the first month"):
        cb.plan((2013, 5), (2013, 6))


def test_schema_cutoff_is_the_documented_one():
    assert cb.SCHEMA_CUTOFF == (2021, 2)
    assert cb.LEGACY_START == (2013, 6)
    assert cb.era_of(2021, 1) == "legacy" and cb.era_of(2021, 2) == "lyft"


# ------------------------------------------------------- Jersey City exclusion

def test_jc_keys_never_enter_the_plan(monkeypatch):
    monkeypatch.setattr(cb, "list_bucket", lambda **k: [
        {"key": "202401-citibike-tripdata.zip", "size": 10, "last_modified": "x"},
        {"key": "JC-202401-citibike-tripdata.csv.zip", "size": 9, "last_modified": "x"},
    ])
    out, rep = cb.plan((2024, 1), (2024, 1))
    assert [e["key"] for e in out] == ["202401-citibike-tripdata.zip"]
    assert not any("JC-" in k for k in rep["keys"])


def test_jc_members_inside_a_zip_are_skipped(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("202401-citibike-tripdata_1.csv", LYFT_HEADER)
        zf.writestr("JC-202401-citibike-tripdata.csv", LYFT_HEADER)
        zf.writestr("__MACOSX/._x.csv", "junk")
        zf.writestr(".DS_Store", "junk")
    with zipfile.ZipFile(z) as zf:
        assert cb.csv_members(zf) == ["202401-citibike-tripdata_1.csv"]


def test_a_zip_with_no_csv_raises(tmp_path):
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with zipfile.ZipFile(z) as zf, pytest.raises(cb.CitibikeError, match="no CSV"):
        cb.csv_members(zf)


def _audit(**kw):
    base = {"rows_in_file": 1_000_000, "out_of_system_starts": 0,
            "out_of_system_ends": 0, "jersey_city_ends": 0,
            "out_of_system_stations": 0, "lon_min": -74.041, "lon_max": -73.85,
            "lat_min": 40.61, "lat_max": 40.89}
    base.update(kw)
    return base


def test_a_small_cross_river_leak_is_tolerated_and_counted():
    """2023-06 really does carry eight Jersey City docks and thirteen rides in
    the NEW YORK file. Refusing 3.45M good trips over thirteen bad ones would be
    the wrong trade; the id filter removes them and the share is asserted."""
    a = _audit(out_of_system_ends=13, jersey_city_ends=13, out_of_system_stations=8)
    cb.assert_out_of_system_bounded(a, 2023, 6)
    assert a["out_of_system_share"] == pytest.approx(13 / 1_000_000)


def test_a_whole_jersey_city_file_is_refused():
    with pytest.raises(cb.CitibikeError, match="the wrong FILE"):
        cb.assert_out_of_system_bounded(
            _audit(out_of_system_ends=900_000, jersey_city_ends=900_000), 2024, 1)


def test_a_numeric_dock_in_the_wrong_place_still_raises():
    """The bbox is a backstop for an id that PASSES the pattern but is not in
    New York -- an id scheme reused across systems, or a corrupt coordinate."""
    with pytest.raises(cb.CitibikeError, match="even after the"):
        cb.assert_out_of_system_bounded(_audit(lon_min=-74.20), 2024, 1)


@pytest.mark.parametrize("sid,keep", [
    ("5905.14", True), ("1001", True), ("5303.06_", True),
    ("JC109", False), ("HB202", False), ("SYS033", False),
    ("Shop Morgan", False), ("MTL-LAB-BKN", False), ("", False),
])
def test_only_new_york_public_dock_ids_survive(sid, keep):
    """Jersey City and Hoboken ids reach the NEW YORK file as the far end of a
    cross-river trip, and a bounding box cannot exclude Hoboken (-74.027, inside
    any NY box and at Bay Ridge's longitude). The id pattern can. The same rule
    removes the operator's shops and loading docks, which are where bikes are
    serviced, not where a member takes one out."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t(start_station_id VARCHAR)")
    con.execute("INSERT INTO t VALUES (?)", [sid])
    got = con.execute(
        f"SELECT count(*) FROM t WHERE {cb.is_ny_station_sql('start_station_id')}"
    ).fetchone()[0]
    assert bool(got) is keep


def test_the_trailing_underscore_is_fused_to_its_base_dock():
    con = duckdb.connect()
    got = con.execute(
        f"SELECT {cb.station_id_sql(chr(39) + '5303.06_' + chr(39))}").fetchone()[0]
    assert got == "5303.06"


def test_fusing_a_twin_that_disagrees_is_refused():
    """The guard against the dedup-fuses-distinct-storefronts bug. A pair whose
    published names differ, or whose points are far apart, is two docks."""
    ok = pd.DataFrame({
        "station_id": ["5303.06", "5303.06_"],
        "station_name": ["Clinton St & Grand St", "Clinton St & Grand St"],
        "lon": [-73.98703, -73.98699], "lat": [40.71560, 40.71574]})
    rep = cb.assert_underscore_twins_agree(ok)
    assert rep["pairs"] == 1 and rep["max_dist_m"] < cb.TWIN_MAX_M

    far = ok.copy()
    far.loc[1, "lat"] = 40.7300                  # ~1.6 km away
    with pytest.raises(cb.CitibikeError, match="evidenced on name AND position"):
        cb.assert_underscore_twins_agree(far)

    renamed = ok.copy()
    renamed.loc[1, "station_name"] = "Somewhere Else"
    with pytest.raises(cb.CitibikeError, match="evidenced on name AND position"):
        cb.assert_underscore_twins_agree(renamed)


# ------------------------------------------------- dayparts on the NY clock

def test_dayparts_are_the_transit_dayparts_not_a_second_definition():
    assert cb.DAYPART_NAMES == mr.DAYPART_NAMES
    assert cb.DAY_TYPES == mr.DAY_TYPES


@pytest.mark.parametrize("hour,part", [
    (0, "early"), (5, "early"), (6, "am_peak"), (9, "am_peak"),
    (10, "midday"), (14, "midday"), (15, "pm_peak"), (18, "pm_peak"),
    (19, "evening"), (23, "evening"),
])
def test_daypart_sql_agrees_with_the_python_definition(hour, part):
    """The SQL CASE is RENDERED from mr.DAYPARTS. This asserts the render, not
    the boundaries -- if the two ever disagree, a bike cell and a subway cell
    stop meaning the same hours and `loci validate-bike` compares two clocks."""
    con = duckdb.connect()
    ts = f"TIMESTAMP '2026-04-07 {hour:02d}:30:00'"
    got = con.execute(f"SELECT {cb.daypart_case_sql(ts)}").fetchone()[0]
    assert got == part == mr.daypart_of(hour)


@pytest.mark.parametrize("date,day_type", [
    ("2026-04-06", "weekday"),    # Monday
    ("2026-04-10", "weekday"),    # Friday
    ("2026-04-11", "saturday"),
    ("2026-04-12", "sunday"),
])
def test_day_type_sql_agrees_with_python(date, day_type):
    con = duckdb.connect()
    ts = f"TIMESTAMP '{date} 12:00:00'"
    assert con.execute(f"SELECT {cb.day_type_case_sql(ts)}").fetchone()[0] == day_type
    assert cb.day_type_of_date(dt.date.fromisoformat(date)) == day_type


def test_timestamps_are_read_as_naive_wall_clock():
    """No timezone conversion anywhere. A daypart is a fact about the clock on
    the wall; converting to UTC would move every NYC evening into the next
    day's `early`."""
    assert "TIMESTAMP" == cb.READ_TYPES["started_at"] == cb.READ_TYPES["ended_at"]
    assert "AT TIME ZONE" not in cb.month_sql("x/*.csv", 2026, 4)


# --------------------------------------------------------- holiday exclusion

def test_holidays_belong_to_no_day_type():
    assert cb.day_type_of_date(dt.date(2026, 7, 3)) is None      # Independence Day obs
    assert cb.day_type_of_date(dt.date(2026, 7, 2)) == "weekday"


def test_every_listed_holiday_is_mon_to_fri():
    """The docstring's claim that the exclusion touches the WEEKDAY mean only
    rests on this. A Saturday in the list would silently shrink a saturday
    divisor and inflate every weekend average."""
    bad = [h for h in cb.HOLIDAYS if h.weekday() >= 5]
    assert bad == []


def test_holiday_coverage_spans_the_ingest_window():
    cb.assert_holidays_cover([(2023, 1), (2026, 8)])
    with pytest.raises(cb.CitibikeError, match="holiday list covers"):
        cb.assert_holidays_cover([(2030, 1)])


def test_days_by_type_excludes_the_holiday_from_the_divisor():
    """July 2026 has 23 Mon-Fri dates; the 3rd is the observed holiday."""
    d = cb.days_by_type(2026, 7)
    assert d["weekday"] == 22
    assert d["weekday"] + d["saturday"] + d["sunday"] == 30      # 31 minus 1 holiday


def test_a_month_with_no_holidays_keeps_every_row():
    """The regression this exists for: `NOT IN (NULL)` is NULL for every row,
    so a 'no holidays this month' placeholder of NULL deletes the whole month
    -- a silent zero of exactly the kind this source refuses to ingest."""
    assert cb.holiday_predicate_sql("started_at", 2026, 4) == ""
    assert "NOT IN" in cb.holiday_predicate_sql("started_at", 2026, 7)


# --------------------------------------------- the aggregation, end to end

def _trip(rid, start, end, s_id, e_id, member="member",
          s=(40.700, -73.990), e=(40.710, -73.980)):
    return (f"{rid},classic_bike,{start},{end},S{s_id},{s_id},E{e_id},{e_id},"
            f"{s[0]},{s[1]},{e[0]},{e[1]},{member}")


@pytest.fixture
def fake_month(tmp_path):
    """A hand-built April 2026 with two docks and known counts.

    April 2026 has NO federal holiday, 22 weekdays, 4 Saturdays and 4 Sundays,
    and every calendar date must be present or `assert_month_complete` raises --
    so the fixture lays down one filler trip per date and then the trips the
    assertions are about.
    """
    rows = [LYFT_HEADER]
    n = 0
    for day in range(1, 31):                 # one filler trip per calendar date
        n += 1
        rows.append(_trip(f"F{n:06d}", f"2026-04-{day:02d} 12:05:00",
                          f"2026-04-{day:02d} 12:20:00", "1001.01", "1001.01"))
    # a morning commuter departure and an evening arrival at dock 2002.02,
    # both on Tuesday 2026-04-07
    rows.append(_trip("A1", "2026-04-07 08:10:00", "2026-04-07 08:40:00",
                      "2002.02", "1001.01"))
    rows.append(_trip("A2", "2026-04-07 19:30:00", "2026-04-07 19:55:00",
                      "1001.01", "2002.02", member="casual"))
    # an arrival AFTER midnight: dated by ended_at, so it is `early` on the 8th,
    # not `evening` on the 7th.
    rows.append(_trip("A3", "2026-04-07 23:50:00", "2026-04-08 00:20:00",
                      "1001.01", "2002.02"))
    # a dockless end (blank end_station_id) -- excluded, never folded onto a dock
    rows.append("D1,electric_bike,2026-04-09 10:00:00,2026-04-09 10:10:00,"
                "S1001.01,1001.01,,,40.700,-73.990,40.705,-73.985,member")
    # an arrival spilling past the month end -- dropped, and counted
    rows.append(_trip("A4", "2026-04-30 23:50:00", "2026-05-01 00:20:00",
                      "1001.01", "2002.02"))
    p = tmp_path / "202604-citibike-tripdata_1.csv"
    p.write_text("\n".join(rows) + "\n")
    return tmp_path


def test_month_frame_counts_and_dates_the_events_correctly(fake_month):
    df, audit = cb.month_frame(str(fake_month / "*.csv"), 2026, 4, fake_month,
                               min_trips=1)
    assert audit["start_dates"] == 30
    assert audit["dockless_ends"] == 1
    assert audit["end_events_after_month_end"] == 1

    def cell(sid, dtp, part, col):
        m = df[(df.station_id == sid) & (df.day_type == dtp) & (df.daypart == part)]
        return 0 if m.empty else int(m.iloc[0][col])

    assert cell("2002.02", "weekday", "am_peak", "starts") == 1
    # the 19:30 arrival is evening; the 00:20 arrival is `early` on the NEXT day
    assert cell("2002.02", "weekday", "evening", "ends") == 1
    assert cell("2002.02", "weekday", "early", "ends") == 1
    # 30 filler arrivals + A1 + A2 + A3. The dockless end (D1) went nowhere and
    # the month-end spill (A4) was dropped rather than carried into May.
    assert df["ends"].sum() == 33
    # 30 filler + A1 + A2 + A3 + A4 + D1. D1 is a dockless END, so its
    # departure is a real dock event and only its arrival is excluded.
    assert df["starts"].sum() == 35
    # ...and the month-end spill was dropped, not carried into May
    assert (df["month"].astype(str) == "2026-04-01").all()


def test_days_in_cell_is_the_calendar_not_the_observation(fake_month):
    """Dock 2002.02 is seen on ONE weekday. Its divisor must still be 22, or a
    dock with a single busy Tuesday would out-rank a dock busy every day."""
    df, _ = cb.month_frame(str(fake_month / "*.csv"), 2026, 4, fake_month,
                           min_trips=1)
    wd = df[(df.station_id == "2002.02") & (df.day_type == "weekday")]
    assert set(wd["days_in_cell"]) == {22}


def test_an_incomplete_month_raises(tmp_path):
    rows = [LYFT_HEADER] + [
        _trip(f"F{i:06d}", f"2026-04-{d:02d} 12:05:00", f"2026-04-{d:02d} 12:20:00",
              "1001.01", "1001.01")
        for i, d in enumerate(range(1, 20))]          # only 19 of 30 dates
    (tmp_path / "202604-citibike-tripdata_1.csv").write_text("\n".join(rows) + "\n")
    audit = {"rows_in_file": 500_000, "start_dates": 19,
             "first_date": "2026-04-01", "last_date": "2026-04-19"}
    with pytest.raises(cb.CitibikeError, match="calendar dates"):
        cb.assert_month_complete(audit, 2026, 4)


def test_a_truncated_month_raises():
    with pytest.raises(cb.CitibikeError, match="truncated publication"):
        cb.assert_month_complete({"rows_in_file": 1000, "start_dates": 30}, 2026, 4)


# ------------------------------------------- the address measure on a fixture

@pytest.fixture
def warehouse(tmp_path):
    """A tiny warehouse: three docks, four lot addresses, one street address."""
    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    con.execute("CREATE SCHEMA staging; CREATE SCHEMA analysis")
    con.execute(pathlib.Path("src/loci/sql/034_citibike.sql").read_text()
                .split("ALTER TABLE analysis.address")[0])
    # 044 is part of the definition of staging.citibike_station_month now: it
    # adds station_id_legacy and era, and `rebuild_roster` scopes to era='lyft'.
    con.execute(pathlib.Path("src/loci/sql/044_citibike_legacy.sql").read_text())
    con.execute("""
        CREATE TABLE analysis.address (
            address_id VARCHAR, borough VARCHAR, lon DOUBLE, lat DOUBLE,
            frame VARCHAR DEFAULT 'lot',
            bike_starts_400m DOUBLE, bike_ends_400m DOUBLE,
            bike_evening_ends_share_400m DOUBLE, bike_casual_share_400m DOUBLE,
            bike_window VARCHAR, bike_radius_m REAL, bike_run_at TIMESTAMP)""")
    con.execute("""INSERT INTO analysis.address
        (address_id, borough, lon, lat, frame) VALUES
        ('a1','Brooklyn',-73.99,40.70,'lot'),
        ('a2','Brooklyn',-73.98,40.71,'lot'),
        ('a3','Brooklyn',-73.97,40.72,'lot'),
        ('a4','Manhattan',-73.96,40.73,'lot'),
        ('s1','Brooklyn',-73.95,40.74,'street')""")
    rows = []
    for sid, lon, lat in (("1001.01", -73.99, 40.70), ("2002.02", -73.98, 40.71),
                          ("3003.03", -73.97, 40.72)):
        for month in ("2026-07-01", "2026-08-01"):
            for day_type, days in (("weekday", 22), ("saturday", 4), ("sunday", 5)):
                for part in cb.DAYPART_NAMES:
                    starts = 10 if day_type == "weekday" else 4
                    ends = 12 if part == "evening" else 8
                    rows.append((sid, f"dock {sid}", lon, lat, month, day_type,
                                 part, starts, ends, starts - 3, 3,
                                 ends - 2, 2, days))
    con.executemany(
        "INSERT INTO staging.citibike_station_month (station_id, station_name, "
        "lon, lat, month, day_type, daypart, starts, ends, member_starts, "
        "casual_starts, member_ends, casual_ends, days_in_cell) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    from loci.sources.cities.nyc.citibike import rebuild_roster
    rebuild_roster(con)
    return con


def test_window_bounds_are_taken_from_the_panel_not_from_today(warehouse):
    first, last = __import__("loci.model.address_bike", fromlist=["x"]).window_bounds(
        warehouse, 12)
    assert (first.year, first.month) == (2026, 7)
    assert (last.year, last.month) == (2026, 8)


def test_empty_panel_raises_rather_than_measuring_zero(tmp_path):
    from loci.model import address_bike as ab

    con = duckdb.connect()
    con.execute("CREATE SCHEMA staging")
    con.execute("CREATE TABLE staging.citibike_station_month (month DATE)")
    with pytest.raises(RuntimeError, match="empty"):
        ab.window_bounds(con)


def test_measures_divide_by_the_window_and_sum_over_docks(warehouse):
    from loci.model import address_bike as ab

    first, last = ab.window_bounds(warehouse, 12)
    weights, wrep = ab.station_weights(warehouse, first, last)
    assert wrep["weekday_days"] == 44                    # 22 + 22, from the calendar

    # a1 reaches one dock, a2 reaches two -- summed, never deduplicated: two
    # docks are two docks, unlike two doors of one subway complex.
    reach = pd.DataFrame({"address_id": ["a1", "a2", "a2"],
                          "station_id": ["1001.01", "1001.01", "2002.02"]})
    m = ab.measures(reach, weights, wrep["weekday_days"]).set_index("address_id")
    # per dock: 5 dayparts x 10 starts x 2 months x 22 days-worth of rows
    # = 5*10*2 = 100 weekday starts per month-pair... in raw counts: 100
    one = m.loc["a1", "bike_starts_400m"]
    assert one == pytest.approx(100 / 44)
    assert m.loc["a2", "bike_starts_400m"] == pytest.approx(2 * one)


def test_evening_weekend_share_is_a_share_and_counts_the_union_once(warehouse):
    from loci.model import address_bike as ab

    first, last = ab.window_bounds(warehouse, 12)
    weights, wrep = ab.station_weights(warehouse, first, last)
    reach = pd.DataFrame({"address_id": ["a1"], "station_id": ["1001.01"]})
    m = ab.measures(reach, weights, wrep["weekday_days"])
    share = float(m["bike_evening_ends_share_400m"].iloc[0])
    # weekday ends: 4 parts x 8 + 1 evening x 12 = 44 per month, x2 = 88
    # weekend ends: (4*8 + 12) x 2 day types x 2 months = 176 -- ALL of them
    # count, plus the 24 weekday evening ends.
    assert share == pytest.approx((176 + 24) / (88 + 176))
    assert 0.0 <= share <= 1.0
    ab.check_shares_in_bounds(m)


def test_a_share_outside_zero_one_raises():
    """The guard against an OR that became a sum. A 1.4 reads as a plausible
    'very evening-heavy' number to every downstream reader, which is why it
    must fail here rather than be rendered on a card."""
    from loci.model import address_bike as ab

    bad = pd.DataFrame({"bike_evening_ends_share_400m": [1.4],
                        "bike_casual_share_400m": [0.3]})
    with pytest.raises(RuntimeError, match=r"outside \[0, 1\]"):
        ab.check_shares_in_bounds(bad)


def test_write_zeroes_every_in_scope_address_in_both_frames(warehouse):
    """The no-eligibility-gate rule (owner 2026-09-13) must hold by WRITE, not
    by omission: an address with no dock gets 0.0 and a run_at, not a NULL that
    reads as 'never measured'.

    Owner ruling 4 (2026-09-16) extended that to D84's street frame, which was
    the LAST frame still storing "never computed" as an absence -- and stored it
    in the same column, with the same NULL, as "measured, no dock nearby". This
    test used to assert the opposite; it was rewritten, not relaxed, because the
    behaviour it pinned is the behaviour the ruling reverses."""
    from loci.model import address_bike as ab

    reach = pd.DataFrame({"address_id": ["a1"], "borough": ["Brooklyn"],
                          "station_id": ["1001.01"], "dist_m": [120.0]})
    meas = pd.DataFrame({"address_id": ["a1"], "bike_starts_400m": [2.27],
                         "bike_ends_400m": [2.0],
                         "bike_evening_ends_share_400m": [0.4],
                         "bike_casual_share_400m": [0.3]})
    meta = {"run_at": dt.datetime(2026, 9, 14), "radius_m": 400.0,
            "graph_version": "test", "window": "2026-07..2026-08"}
    ab.write_measures(warehouse, reach, meas, ["Brooklyn"], meta)

    got = warehouse.execute(
        "SELECT address_id, bike_starts_400m, bike_evening_ends_share_400m, "
        "bike_run_at FROM analysis.address ORDER BY address_id").fetchall()
    d = {r[0]: r for r in got}
    assert d["a1"][1] == pytest.approx(2.27)
    for aid in ("a2", "a3"):                       # Brooklyn lots with no dock
        assert d[aid][1] == 0.0                    # a value, not a gap
        assert d[aid][2] is None                   # ...but the share is undefined
        assert d[aid][3] is not None
    assert d["a4"][3] is None                      # Manhattan: out of scope
    assert d["s1"][1] == 0.0                       # street frame: measured, no dock
    assert d["s1"][2] is None                      # ...share still undefined
    assert d["s1"][3] is not None


def test_bike_columns_do_not_collide_with_a_sibling_annotation():
    from loci.model import address_bike as ab

    ab._guard(ab.BIKE_ADDRESS_COLUMNS)             # must not raise
    with pytest.raises(RuntimeError):
        ab._guard(["transit_entries_400m"])


def test_nothing_bike_reaches_a_score():
    """Card context only, on the D76 footing. If a future edit wires a bike
    column into the screen or the grade, this is the test that says so."""
    for path in ("src/loci/score", "src/loci/model/recommend.py",
                 "src/loci/model/supply_ratio.py"):
        p = pathlib.Path(path)
        files = p.rglob("*.py") if p.is_dir() else [p]
        for f in files:
            assert "bike_starts_400m" not in f.read_text(), f
            assert "bike_ends_400m" not in f.read_text(), f


# ------------------------------------------------------------- the map export

def test_bike_json_is_loadable_and_its_shape_conserves(warehouse, tmp_path):
    """Two things the map cannot survive being wrong about: a bare `NaN` (which
    Python writes happily and `JSON.parse` refuses -- the D85 export bug), and a
    daypart shape that does not add up to the number the dot is SIZED by."""
    import json

    from loci.viz import bike_export as bx

    rep = bx.export(warehouse, out_dir=tmp_path)
    bundle = json.loads(pathlib.Path(rep["path"]).read_text())
    st = bundle["stations"]
    assert st["n"] == 3
    assert st["cols"][:4] == ["id", "lon", "lat", "name"]
    for row, shape in zip(st["rows"], st["shape"]):
        assert sum(shape) == pytest.approx(row[4] + row[5], abs=0.3)
        assert 0.0 <= row[8] <= 1.0 and 0.0 <= row[9] <= 1.0
    assert "notFootfall" in bundle["caveats"]
    assert "NYCBS" in bundle["source"]["license"]


def test_export_refuses_a_bare_nan():
    from loci.viz import bike_export as bx

    assert bx._r(float("nan")) is None
    assert bx._r(None) is None
    assert bx._r(1.234, 2) == 1.23


# ---------------------------------------------------- the registry contract

def test_registry_entry_exists_and_is_sound():
    from loci import registry

    reg = registry.load()
    entry = next(s for s in reg["sources"] if s["id"] == "citibike_tripdata")
    assert entry["cost"]["amount"] == 0
    assert set(entry["portability"]["feeds"]) == {"demand", "validation"}
    assert entry["portability"]["class"] == "national"
    # a med/low confidence class must say WHY, and this one's reason is that the
    # portable thing is the Lyft SCHEMA, not the operator.
    assert entry["portability"]["confidence"] == "med"
    assert "Lyft" in entry["portability"]["note"]
    assert "NYCBS Data Use Policy" in entry["license"]
    assert registry.validate() == []


def test_reconcile_rebuilds_the_stored_measures_and_catches_drift(warehouse):
    """The arithmetic proof: re-derive the four numbers from the panel and the
    persisted reachable set, independently of the frames the build used."""
    import datetime as _dt

    from loci.model import address_bike as ab

    first, last = ab.window_bounds(warehouse, 12)
    weights, wrep = ab.station_weights(warehouse, first, last)
    reach = pd.DataFrame({"address_id": ["a1", "a1"], "borough": ["Brooklyn"] * 2,
                          "station_id": ["1001.01", "2002.02"],
                          "dist_m": [120.0, 330.0]})
    meas = ab.measures(reach[["address_id", "station_id"]], weights,
                       wrep["weekday_days"])
    meta = {"run_at": _dt.datetime(2026, 9, 14), "radius_m": 400.0,
            "graph_version": "test", "window": wrep["window"]}
    ab.write_measures(warehouse, reach, meas, ["Brooklyn"], meta)

    rep = ab.reconcile(warehouse, "a1", first, last)
    assert rep["docks_reachable"] == 2
    assert rep["weekday_days"] == 44

    # ...and it must NOTICE when the stored number stops matching the panel.
    warehouse.execute(
        "UPDATE analysis.address SET bike_starts_400m = bike_starts_400m * 2 "
        "WHERE address_id = 'a1'")
    with pytest.raises(RuntimeError, match="do not reproduce from the panel"):
        ab.reconcile(warehouse, "a1", first, last)


# ------------------------------- truncation versus a system outage (2026-02)

def _complete(**kw):
    a = {"rows_in_file": 2_000_000, "start_dates": 28,
         "first_date": dt.date(2026, 2, 1), "last_date": dt.date(2026, 2, 28),
         "last_date_in_month": dt.date(2026, 2, 28)}
    a.update(kw)
    return a


def test_an_interior_zero_date_is_an_outage_and_is_allowed():
    """2026-02-23 is the measured case: the whole system carried nobody, with
    02-22 at 19k rides and 02-24 at 13k against a ~60k February norm. A storm,
    not a missing file. The date STAYS in the divisor -- an average weekday that
    month really did include a day the docks were shut -- and dropping days
    because ridership was low would select on the outcome."""
    a = _complete(start_dates=27)
    cb.assert_month_complete(a, 2026, 2)
    assert a["dates_with_no_trip"] == 1


def test_a_missing_tail_is_truncation_and_is_refused():
    """The shape test: a truncated export loses a contiguous SUFFIX."""
    with pytest.raises(cb.CitibikeError, match="TRUNCATED publication"):
        cb.assert_month_complete(
            _complete(start_dates=20, last_date_in_month=dt.date(2026, 2, 20)),
            2026, 2)


def test_too_many_zero_dates_is_refused_even_in_the_interior():
    with pytest.raises(cb.CitibikeError, match="publication problem"):
        cb.assert_month_complete(_complete(start_dates=25), 2026, 2)


def test_a_complete_month_records_zero_missing_dates():
    a = _complete()
    cb.assert_month_complete(a, 2026, 2)
    assert a["dates_with_no_trip"] == 0
