"""CAP 5: the pre-2021 Citi Bike era, and the crosswalk that is allowed to miss.

Two caps came off on 2026-09-16 (owner: "your goal is to have AS MUCH AS DATA AS
POSSIBLE", "never ever ever limit data pulls"):

  * the default ingest start moved from 2023-01 to 2013-06, the first month the
    bucket publishes;
  * the 2021-02 floor, which RAISED on every earlier month, is gone.

What must NOT come off with them is the reason the floor existed: legacy `3002`
and modern `3002` are different docks. Every test here is about that seam --
that the old months land, that their ids never enter `station_id`, that the
crosswalk refuses to fuse, and that a poor match rate costs a join and never a
month.

Pure: no network, no warehouse file. CSVs are written to tmp_path and read by an
in-memory DuckDB, exactly as the production month pass does.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import zipfile

import pytest

from loci import db as locidb
from loci.sources.cities import lyft_bikeshare as lyft
from loci.sources.cities.nyc import citibike as cb
from loci.sources.cities.nyc import citibike_crosswalk as xw

SQL_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "loci" / "sql"

# The three header spellings the archives actually ship. Measured from the
# bucket 2026-09-16 by range-reading each year zip's central directory and
# inflating the first member.
HDR_BARE = ("tripduration,starttime,stoptime,start station id,"
            "start station name,start station latitude,start station longitude,"
            "end station id,end station name,end station latitude,"
            "end station longitude,bikeid,usertype,birth year,gender")
HDR_QUOTED = ",".join(f'"{c}"' for c in HDR_BARE.split(","))
HDR_TITLE = ("Trip Duration,Start Time,Stop Time,Start Station ID,"
             "Start Station Name,Start Station Latitude,Start Station Longitude,"
             "End Station ID,End Station Name,End Station Latitude,"
             "End Station Longitude,Bike ID,User Type,Birth Year,Gender")


def _row(start_ts: str, end_ts: str, s_id: str, e_id: str,
         user: str = "Subscriber") -> str:
    return (f"600,{start_ts},{end_ts},{s_id},Broadway & W 24 St,"
            f"40.7423543,-73.98915076,{e_id},9 Ave & W 18 St,"
            f"40.74317449,-74.00366443,19678,{user},1983,1")


# =============================================================== the header

def test_every_published_legacy_spelling_folds_onto_one_column_map():
    """2013 ships bare lowercase, the 2013 flat copies ship it quoted, and 2017
    ships Title Case with spaces. One `columns={...}` map has to serve all
    three, so the header is REWRITTEN at extraction rather than sniffed."""
    for hdr in (HDR_BARE, HDR_QUOTED, HDR_TITLE):
        m = lyft.legacy_header_map(hdr.split(","))
        assert m is not None, hdr[:40]
        assert [m[i] for i in sorted(m)] == list(lyft.LEGACY_CANONICAL)


def test_an_unknown_legacy_column_is_refused_and_not_near_matched():
    """A shape that moved must be LOOKED AT. Reading an unrecognised column as
    the nearest known one would put a silently wrong number into eight years."""
    hdr = HDR_BARE.replace("start station latitude", "start_station_lat_wgs84")
    assert lyft.legacy_header_map(hdr.split(",")) is None
    assert cb.classify_header(HDR_BARE.split(",")) == "legacy_pre2021"


def test_rewriting_the_header_is_what_extract_does_for_a_legacy_member(tmp_path):
    zp = tmp_path / "2017-citibike-tripdata.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("2017-citibike-tripdata/1_January/201701-citibike-tripdata.csv_1.csv",
                   HDR_TITLE + "\n" + _row("2017-01-03 08:00:00",
                                           "2017-01-03 08:10:00", "3226", "3165") + "\n")
    out = cb.extract_month(zp, 2017, 1, tmp_path / "x")
    assert len(out) == 1
    first = out[0].read_text().splitlines()[0]
    assert first == ",".join(lyft.LEGACY_CANONICAL)


# ========================================= the duplicated month (2013, 2018)

def test_the_2013_archive_shape_is_deduped_and_not_concatenated():
    """`2013-citibike-tripdata.zip` holds June 2013 TWICE: a quoted flat CSV at
    the root and an unquoted chunked copy under `6_June/`. Their first two data
    rows are the same two trips. Flattening both onto one directory -- which is
    what the phase-1 extractor did -- would DOUBLE the month with no error
    anywhere."""
    names = ["2013-citibike-tripdata/201306-citibike-tripdata.csv",
             "2013-citibike-tripdata/6_June/201306-citibike-tripdata_1.csv"]
    keep, dropped = lyft.dedupe_members(names)
    assert keep == [names[0]]
    assert dropped == [names[1]]


def test_the_2018_april_shape_keeps_the_whole_month_over_its_chunks():
    """April 2018 is published three times, two of them at the SAME depth: a
    flat whole-month CSV and the `_1`/`_2` chunks beside it. Depth alone does
    not separate those, so the unsuffixed member wins."""
    names = ["2018-citibike-tripdata/201804-citibike-tripdata.csv",
             "2018-citibike-tripdata/201804-citibike-tripdata_1.csv",
             "2018-citibike-tripdata/201804-citibike-tripdata_2.csv",
             "2018-citibike-tripdata/4_April/201804-citibike-tripdata_1.csv"]
    keep, dropped = lyft.dedupe_members(names)
    assert keep == [names[0]]
    assert len(dropped) == 3


def test_a_genuinely_chunked_month_keeps_every_chunk():
    """The Lyft-era monthly zips are ALL chunks and none is a duplicate. The
    rule must be a no-op there or every 2024+ month loses two thirds of itself."""
    names = ["202409-citibike-tripdata/202409-citibike-tripdata_1.csv",
             "202409-citibike-tripdata/202409-citibike-tripdata_2.csv",
             "202409-citibike-tripdata/202409-citibike-tripdata_3.csv"]
    keep, dropped = lyft.dedupe_members(names)
    assert keep == names and dropped == []


def test_extract_writes_one_copy_when_the_archive_holds_two(tmp_path):
    zp = tmp_path / "2013-citibike-tripdata.zip"
    body = HDR_BARE + "\n" + _row("2013-06-03 08:00:00", "2013-06-03 08:10:00",
                                  "444", "434") + "\n"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("2013-citibike-tripdata/201306-citibike-tripdata.csv", body)
        z.writestr("2013-citibike-tripdata/6_June/201306-citibike-tripdata_1.csv", body)
    out = cb.extract_month(zp, 2013, 6, tmp_path / "x")
    assert len(out) == 1


# ============================================================ the timestamps

@pytest.mark.parametrize("ts,expect", [
    ("2013-06-01 00:00:01", dt.datetime(2013, 6, 1, 0, 0, 1)),
    ("2019-12-01 00:00:05.5640", dt.datetime(2019, 12, 1, 0, 0, 5)),   # 4 digits
    ("9/1/2014 00:00:25", dt.datetime(2014, 9, 1, 0, 0, 25)),          # unpadded
    ("10/31/2016 23:59:00", dt.datetime(2016, 10, 31, 23, 59)),
])
def test_every_published_timestamp_format_parses(ts, expect):
    """Three formats, one of them with FOUR fractional digits (`%f` refuses it)
    and one with no zero padding. A TIMESTAMP column type makes DuckDB refuse
    the whole file on the second row it meets."""
    con = locidb.connect(":memory:")
    try:
        got = con.execute(
            f"SELECT {lyft._legacy_ts_sql('?')}", [ts]).fetchone()[0]
    finally:
        con.close()
    assert got == expect


def test_an_unparseable_timestamp_is_refused_rather_than_silently_dropped():
    """An unparsed timestamp does not error -- it becomes NULL, falls out of the
    month predicate, and reads downstream as a dock nobody used."""
    audit = {"rows_in_file": 1000, "unparsed_starttime": 50, "unparsed_stoptime": 0}
    with pytest.raises(cb.CitibikeError, match="matches none of"):
        lyft.assert_legacy_parses(cb.SYSTEM, audit, 2016, 1)
    ok = {"rows_in_file": 1_000_000, "unparsed_starttime": 3, "unparsed_stoptime": 0}
    lyft.assert_legacy_parses(cb.SYSTEM, ok, 2016, 1)     # under the gate


# ====================================================== a whole legacy month

@pytest.fixture()
def legacy_month(tmp_path):
    """One complete legacy month (2016-01), in the M/D/YYYY spelling, with a
    dockless-free legacy id space and a Jersey City row to be excluded."""
    lines = [HDR_BARE]
    for day in range(1, 32):
        for hour, sid, eid in ((8, "268", "3002"), (18, "3002", "268")):
            lines.append(_row(f"1/{day}/2016 {hour:02d}:05:00",
                              f"1/{day}/2016 {hour:02d}:20:00", sid, eid))
    # a customer, so the member/casual split is exercised
    lines.append(_row("1/6/2016 09:00:00", "1/6/2016 09:20:00", "268", "3002",
                      "Customer"))
    d = tmp_path / "legacy"
    d.mkdir()
    (d / "201601-citibike-tripdata.csv").write_text("\n".join(lines) + "\n")
    return d


def test_a_legacy_month_aggregates_through_the_same_sql_as_a_modern_one(
        legacy_month, tmp_path):
    """`legacy_projection_sql` presents the old columns AS the Lyft contract, so
    there is ONE aggregation and not a second one that can drift."""
    df, audit = cb.month_frame(str(legacy_month / "*.csv"), 2016, 1, tmp_path,
                               min_trips=10, era="legacy")
    assert audit["era"] == "legacy"
    assert audit["dates_with_no_trip"] == 0
    # 31 days x 2 trips + 1 customer = 63, MINUS the two federal holidays in
    # January 2016 (the 1st and MLK on the 18th) at 2 trips each. That the
    # holidays bite at all is the HOLIDAYS_2013_2020 block doing its job: without
    # it `assert_holidays_cover` would have refused the month outright.
    assert int(df["starts"].sum()) == 59
    assert int(df["ends"].sum()) == 59
    # the day-type x daypart partition is the transit one, unchanged
    assert set(df["daypart"]) <= set(cb.DAYPART_NAMES)
    assert set(df["day_type"]) <= set(cb.DAY_TYPES)


def test_the_legacy_id_never_enters_station_id(legacy_month, tmp_path):
    """THE SEAM. Legacy `3002` is South End Ave & Liberty St; modern `3002` is
    another dock, and no published crosswalk maps them. If both ever share a
    column the panel either invents a dock that opened in 2021-02 or fuses two
    distinct docks -- and does it silently."""
    df, _ = cb.month_frame(str(legacy_month / "*.csv"), 2016, 1, tmp_path,
                           min_trips=10, era="legacy")
    assert df["station_id"].isna().all()
    assert set(df["station_id_legacy"]) == {"268", "3002"}
    assert set(df["era"]) == {"legacy"}


def test_usertype_maps_to_member_casual_and_is_not_invented(legacy_month, tmp_path):
    df, _ = cb.month_frame(str(legacy_month / "*.csv"), 2016, 1, tmp_path,
                           min_trips=10, era="legacy")
    assert int(df["casual_starts"].sum()) == 1
    assert int(df["member_starts"].sum()) == 58     # 62 minus the two holidays


def test_rideable_type_is_null_and_never_guessed_as_classic(legacy_month, tmp_path):
    """Citi Bike's e-bikes launched in 2018, INSIDE the legacy era. A blanket
    'classic_bike' default would be a false statement about 2018-2020, not a
    harmless one; the feed does not say, so neither do we."""
    _, audit = cb.month_frame(str(legacy_month / "*.csv"), 2016, 1, tmp_path,
                              min_trips=10, era="legacy")
    assert int(audit["electric_trips"]) == 0
    assert "rideable_type" not in lyft.LEGACY_READ_TYPES


def test_the_truncation_floor_is_per_era(legacy_month, tmp_path):
    """2014-02 is a real month with ~169k trips. The 2021+ floor is 300k, so
    applying one floor to both eras refuses eight genuine winters as truncated
    publications."""
    assert cb.MIN_TRIPS_PER_MONTH_LEGACY < cb.MIN_TRIPS_PER_MONTH
    with pytest.raises(cb.CitibikeError, match="truncated publication"):
        cb.month_frame(str(legacy_month / "*.csv"), 2016, 1, tmp_path,
                       era="legacy")


def test_the_lyft_era_frame_still_carries_the_new_columns_as_nulls(tmp_path):
    """A 2021+ month must be describable by the same table. `era` is 'lyft' and
    `station_id_legacy` is NULL -- not absent, so a UNION over the panel works."""
    hdr = ("ride_id,rideable_type,started_at,ended_at,start_station_name,"
           "start_station_id,end_station_name,end_station_id,start_lat,"
           "start_lng,end_lat,end_lng,member_casual")
    lines = [hdr]
    for day in range(1, 31):
        lines.append(f"r{day},classic_bike,2026-04-{day:02d} 08:05:00,"
                     f"2026-04-{day:02d} 08:20:00,A,5905.14,B,5303.06,"
                     f"40.70,-73.99,40.71,-73.98,member")
    d = tmp_path / "lyft"
    d.mkdir()
    (d / "202604-citibike-tripdata_1.csv").write_text("\n".join(lines) + "\n")
    df, audit = cb.month_frame(str(d / "*.csv"), 2026, 4, tmp_path, min_trips=10)
    assert audit["era"] == "lyft"
    assert set(df["era"]) == {"lyft"}
    assert df["station_id_legacy"].isna().all()
    assert set(df["station_id"]) == {"5905.14", "5303.06"}


# =============================================================== the crosswalk

@pytest.fixture()
def xwdb(tmp_path):
    """A scratch warehouse holding just the three tables sql/044 needs."""
    con = locidb.connect(str(tmp_path / "xw.duckdb"))
    con.execute("CREATE SCHEMA IF NOT EXISTS staging; CREATE SCHEMA IF NOT EXISTS analysis")
    con.execute((SQL_DIR / "034_citibike.sql").read_text()
                .split("ALTER TABLE analysis.address")[0])
    con.execute((SQL_DIR / "044_citibike_legacy.sql").read_text())
    yield con
    con.close()


def _legacy(con, rows):
    con.executemany(
        "INSERT INTO staging.citibike_station_legacy "
        "(station_id_legacy, name, lon, lat, trips) VALUES (?,?,?,?,?)", rows)


def _modern(con, rows):
    con.executemany(
        "INSERT INTO staging.citibike_station (station_id, name, lon, lat) "
        "VALUES (?,?,?,?)", rows)


def test_name_and_position_is_the_only_full_confidence_tier(xwdb):
    _legacy(xwdb, [("444", "Broadway & W 24 St", -73.98915, 40.74235, 100)])
    _modern(xwdb, [("6098.10", "Broadway & W 24 St", -73.98917, 40.74237)])
    cand = xwdb.execute(xw.candidates_sql()).fetchdf()
    acc, counts = xw.choose(cand)
    assert counts["name_and_position"] == 1
    assert acc.iloc[0]["confidence"] == 1.0
    assert acc.iloc[0]["station_id"] == "6098.10"


def test_a_renamed_dock_matches_on_position_only_and_at_lower_confidence(xwdb):
    _legacy(xwdb, [("444", "W 52 St & 11 Ave", -73.98915, 40.74235, 100)])
    _modern(xwdb, [("6098.10", "Hudson Yards Pier", -73.98917, 40.74237)])
    acc, counts = xw.choose(xwdb.execute(xw.candidates_sql()).fetchdf())
    assert counts["position_only"] == 1
    assert acc.iloc[0]["confidence"] == 0.6
    assert bool(acc.iloc[0]["name_match"]) is False


def test_the_street_type_spellings_that_changed_between_eras_compare_equal(xwdb):
    """'11 Av' and '11 Ave' are one corner. The normaliser folds exactly the
    handful of spellings this feed uses -- it is not a fuzzy matcher, because
    'close enough' on a street name is how two corners become one dock."""
    _legacy(xwdb, [("444", "W 52 St & 11 Av", -73.98915, 40.74235, 100)])
    _modern(xwdb, [("6098.10", "W 52 St & 11 Ave", -73.98917, 40.74237)])
    acc, counts = xw.choose(xwdb.execute(xw.candidates_sql()).fetchdf())
    assert counts["name_and_position"] == 1


def test_two_docks_beyond_the_ceiling_are_never_matched(xwdb):
    """150 m is a hard ceiling at ANY confidence. Two docks 200 m apart are two
    docks, whatever they are called."""
    _legacy(xwdb, [("444", "Broadway & W 24 St", -73.98915, 40.74235, 100)])
    _modern(xwdb, [("6098.10", "Broadway & W 24 St", -73.98915, 40.74515)])  # ~310 m N
    cand = xwdb.execute(xw.candidates_sql()).fetchdf()
    assert cand.empty
    acc, counts = xw.choose(cand)
    assert counts["matched"] == 0


def test_an_ambiguous_pair_is_dropped_and_never_arbitrated(xwdb):
    """Two legacy docks on one corner must not both claim the same modern dock,
    and one legacy dock must not pick between two same-named modern ones. A tie
    broken by row order is a fusion that looks like a decision."""
    _legacy(xwdb, [("444", "Broadway & W 24 St", -73.98915, 40.74235, 100)])
    _modern(xwdb, [("6098.10", "Broadway & W 24 St", -73.98917, 40.74237),
                   ("6098.11", "Broadway & W 24 St", -73.98913, 40.74233)])
    acc, counts = xw.choose(xwdb.execute(xw.candidates_sql()).fetchdf())
    assert counts["matched"] == 0
    assert counts["ambiguous"] == 1


def test_the_result_is_one_to_one(xwdb):
    _legacy(xwdb, [("1", "A St & B St", -73.9900, 40.7000, 10),
                   ("2", "C St & D St", -73.9800, 40.7100, 10),
                   ("3", "A St & B St", -73.9700, 40.7200, 10)])
    _modern(xwdb, [("10.1", "A St & B St", -73.99001, 40.70001),
                   ("10.2", "C St & D St", -73.98001, 40.71001)])
    acc, _ = xw.choose(xwdb.execute(xw.candidates_sql()).fetchdf())
    assert acc["station_id_legacy"].is_unique
    assert acc["station_id"].is_unique


def test_the_distance_is_metres_and_is_reprojected_explicitly(xwdb):
    """D16. DuckDB GEOMETRY carries no SRID and `ST_Distance_Sphere` reads
    POINT(x, y) as (LATITUDE, LONGITUDE) while our points are (lon, lat). Unflipped,
    one degree of longitude reads 111 km instead of the 84 km it is at New York
    -- a 32% UNDERSTATEMENT of every east-west gap, which at a 35 m threshold is
    the difference between a match and a fusion.

    This pair is 0.00120 degrees of longitude apart: ~101 m in reality, which is
    outside the 35 m strict tier, and ~134 m if the flip is forgotten -- also
    outside. So the test pins the NUMBER, not just the tier.
    """
    _legacy(xwdb, [("444", "Broadway & W 24 St", -73.98915, 40.74235, 100)])
    _modern(xwdb, [("6098.10", "Broadway & W 24 St", -73.98795, 40.74235)])
    d = float(xwdb.execute(xw.candidates_sql()).fetchdf().iloc[0]["distance_m"])
    assert 98.0 < d < 105.0, d                     # the New York metre
    assert not (130.0 < d < 138.0), "coordinates were not flipped (D16)"
    # and it lands in the name_only tier, not in name_and_position
    acc, counts = xw.choose(xwdb.execute(xw.candidates_sql()).fetchdf())
    assert counts["name_only"] == 1
    assert acc.iloc[0]["confidence"] == 0.5


def test_an_unmatched_dock_is_written_with_its_reason_not_omitted(xwdb):
    """Absent reads as 'not looked at'. The whole point of this table is that
    the MISS is auditable."""
    _legacy(xwdb, [("444", "Broadway & W 24 St", -73.98915, 40.74235, 100),
                   ("999", "Nowhere & Nothing", -73.7000, 40.6000, 7)])
    _modern(xwdb, [("6098.10", "Broadway & W 24 St", -73.98917, 40.74237)])
    rep = xw.build(xwdb, apply=False, rebuild=False)
    rows = xwdb.execute(
        "SELECT station_id_legacy, station_id, method, confidence "
        "FROM staging.citibike_station_crosswalk ORDER BY station_id_legacy"
    ).fetchall()
    assert len(rows) == 2
    miss = [r for r in rows if r[1] is None]
    assert len(miss) == 1 and miss[0][0] == "999"
    assert miss[0][2].startswith("unmatched")
    assert miss[0][3] == 0.0
    assert rep["match_rate_stations"] == 0.5


def test_a_low_match_rate_is_reported_and_costs_no_month(xwdb, tmp_path):
    """Requirement (c), verbatim: under 90% the legacy months land ANYWAY, with
    station_id_legacy populated and station_id NULL. A missing crosswalk row
    costs a join; a dropped month costs the data."""
    xwdb.executemany(
        "INSERT INTO staging.citibike_station_month "
        "(station_id, station_id_legacy, station_name, lon, lat, month, "
        " day_type, daypart, starts, ends, days_in_cell, era) "
        "VALUES (NULL,?,?,?,?,?,'weekday','am_peak',5,5,21,'legacy')",
        [("444", "Broadway & W 24 St", -73.98915, 40.74235, dt.date(2016, 1, 1)),
         ("999", "Nowhere & Nothing", -73.70, 40.60, dt.date(2016, 1, 1))])
    _modern(xwdb, [("6098.10", "Broadway & W 24 St", -73.98917, 40.74237)])
    rep = xw.build(xwdb, apply=True)
    assert rep["legacy_stations"] == 2
    assert rep["below_report_floor"] is True       # 50% < 90%
    # NOT ONE ROW LOST
    n = xwdb.execute("SELECT count(*) FROM staging.citibike_station_month "
                     "WHERE era = 'legacy'").fetchone()[0]
    assert n == 2
    got = dict(xwdb.execute(
        "SELECT station_id_legacy, station_id FROM staging.citibike_station_month "
        "WHERE era = 'legacy'").fetchall())
    assert got == {"444": "6098.10", "999": None}


def test_rebuilding_the_crosswalk_clears_a_stale_mapping(xwdb):
    """A rebuilt crosswalk that no longer matches a dock must not leave the old
    station_id behind on the month rows -- that is a mapping nothing supports."""
    xwdb.execute(
        "INSERT INTO staging.citibike_station_month "
        "(station_id, station_id_legacy, station_name, lon, lat, month, "
        " day_type, daypart, starts, ends, days_in_cell, era) "
        "VALUES ('STALE','999','Nowhere & Nothing',-73.70,40.60,DATE '2016-01-01',"
        "'weekday','am_peak',5,5,21,'legacy')")
    _legacy(xwdb, [("999", "Nowhere & Nothing", -73.70, 40.60, 7)])
    _modern(xwdb, [("6098.10", "Broadway & W 24 St", -73.98917, 40.74237)])
    xw.build(xwdb, apply=True, rebuild=False)
    assert xwdb.execute(
        "SELECT station_id FROM staging.citibike_station_month"
    ).fetchone()[0] is None


def test_the_crosswalk_never_touches_a_lyft_row(xwdb):
    xwdb.execute(
        "INSERT INTO staging.citibike_station_month "
        "(station_id, station_name, lon, lat, month, day_type, daypart, "
        " starts, ends, days_in_cell, era) "
        "VALUES ('5905.14','A',-73.99,40.70,DATE '2024-01-01','weekday',"
        "'am_peak',5,5,21,'lyft')")
    _legacy(xwdb, [("444", "Broadway & W 24 St", -73.98915, 40.74235, 100)])
    _modern(xwdb, [("6098.10", "Broadway & W 24 St", -73.98917, 40.74237)])
    xw.build(xwdb, apply=True, rebuild=False)
    assert xwdb.execute(
        "SELECT station_id FROM staging.citibike_station_month WHERE era = 'lyft'"
    ).fetchone()[0] == "5905.14"


def test_the_roster_every_measure_reads_is_still_the_lyft_era(xwdb):
    """`model/address_bike_growth.py` gates on `first_month <= M-23`. If a
    crosswalked dock's first_month slid to 2013 the growth measure would quietly
    change population while keeping its column name."""
    xwdb.executemany(
        "INSERT INTO staging.citibike_station_month "
        "(station_id, station_id_legacy, station_name, lon, lat, month, "
        " day_type, daypart, starts, ends, days_in_cell, era) "
        "VALUES (?,?,?,?,?,?,'weekday','am_peak',5,5,21,?)",
        [("6098.10", "444", "A", -73.99, 40.70, dt.date(2016, 1, 1), "legacy"),
         ("6098.10", None, "A", -73.99, 40.70, dt.date(2024, 1, 1), "lyft")])
    cb.rebuild_roster(xwdb)
    first = xwdb.execute(
        "SELECT first_month FROM staging.citibike_station").fetchone()[0]
    assert first == dt.date(2024, 1, 1)


# ================================================================ the holidays

def test_the_legacy_holiday_block_covers_the_legacy_window():
    cb.assert_holidays_cover([(2013, 6), (2026, 8)])
    assert cb.HOLIDAY_COVERAGE == (2013, 2027)
    with pytest.raises(cb.CitibikeError, match="holiday list covers"):
        cb.assert_holidays_cover([(2012, 12)])


def test_every_legacy_holiday_is_mon_to_fri():
    """The docstring's claim that the exclusion touches the WEEKDAY mean only
    rests on this. A Saturday in the list would shrink a saturday divisor and
    inflate every weekend average in that year."""
    assert [h for h in lyft.HOLIDAYS_2013_2020 if h.weekday() >= 5] == []


def test_juneteenth_is_not_back_dated():
    """It became a federal holiday on 2021-06-17. Back-dating it would silently
    delete a real working weekday from seven years of divisors."""
    june = sorted(h for h in lyft.HOLIDAYS_2013_2020 if h.month == 6)
    assert june == []


def test_adding_the_legacy_years_did_not_move_the_2021_panel():
    """The 2021+ panel was built from a holiday set; extending it BACKWARD must
    be invisible to every month inside that panel."""
    assert lyft.HOLIDAYS_2021_2024 <= lyft.HOLIDAYS
    within = {h for h in lyft.HOLIDAYS if h.year >= 2021}
    assert within == set(lyft.HOLIDAYS_2021_2024) | set(
        h for h in lyft.HOLIDAYS if h.year >= 2025)
