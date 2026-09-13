"""NYC DOT: the count-column parser, the wide->long conservation, the camera
registry contract, and the address context.

The four things that can silently go wrong here, in order of how expensive
they would be to discover late:

1. THE PARSER. Every round is three new COLUMNS whose naming DOT has never
   repeated ('may_07_am', 'may_22_p_m', 'oct24_md', 'may26_pm'). A parser that
   misses a shape does not error -- it quietly ingests 34 rounds instead of 37.
2. CONSERVATION. Wide -> long is the whole ingest. If a cell is dropped,
   duplicated or type-coerced away, the table looks fine and the totals are
   wrong.
3. THE CAMERA CONTRACT. A separate build fetches frames against
   staging.dot_camera. Its column names and types are an interface, and
   `isOnline` arrives as the STRING 'true' -- bool('false') is True, which is
   the exact bug that would mark every dead camera live.
4. THE ADDRESS CONTEXT. UPDATE-only means the blast radius is every other
   column on analysis.address if the SET list is ever wrong.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from loci import db as locidb
from loci.model import address_dot_context as adc
from loci.sources.cities.nyc import dot_cameras as dc
from loci.sources.cities.nyc import dot_pedestrian as dp

SQL_DIR = pathlib.Path(locidb.SQL_DIR)


# --------------------------------------------------------------- the parser

def test_parse_round_handles_every_naming_shape_the_feed_has_used():
    # Every one of these is a real column name observed on cqsj-cfgu.
    assert dp.parse_round("may_07_am") == (2007, 5, "am")
    assert dp.parse_round("sept_07_pm") == (2007, 9, "pm")
    assert dp.parse_round("may_19_md") == (2019, 5, "md")
    assert dp.parse_round("oct_20_am") == (2020, 10, "am")
    assert dp.parse_round("may_22_p_m") == (2022, 5, "pm")    # the sic spelling
    assert dp.parse_round("may_23_p_m") == (2023, 5, "pm")
    assert dp.parse_round("june_24_am") == (2024, 6, "am")    # four-letter month
    assert dp.parse_round("oct24_md") == (2024, 10, "md")     # no separators
    assert dp.parse_round("may25_pm") == (2025, 5, "pm")
    assert dp.parse_round("may26_md") == (2026, 5, "md")


def test_parse_round_rejects_the_metadata_columns():
    # A meta column parsed as a round would become a phantom count.
    for field in ("the_geom", "objectid", "loc", "borough", "street_nam",
                  "from_stree", "to_street", "iex"):
        assert dp.parse_round(field) is None


def test_parse_round_is_case_and_whitespace_insensitive_but_not_loose():
    assert dp.parse_round(" MAY26_AM ") == (2026, 5, "am")
    # Not a period the feed publishes, and not a month: both must be None
    # rather than a plausible-looking guess.
    assert dp.parse_round("may26_ev") is None
    assert dp.parse_round("mayo26_am") is None


def test_all_37_published_rounds_parse_from_the_feeds_own_field_list():
    """The rounds are DISCOVERED, never typed. This pins the full set the live
    feed carried on 2026-09-13: 2007-05 .. 2026-05, with September 2019 and May
    2020 genuinely absent and 2024's spring round in JUNE."""
    fields = []
    for y in range(7, 19):                       # 2007-2018: May + Sept
        for mon in ("may", "sept"):
            fields += [f"{mon}_{y:02d}_{p}" for p in ("am", "md", "pm")]
    fields += [f"may_19_{p}" for p in ("am", "md", "pm")]
    fields += [f"oct_20_{p}" for p in ("am", "md", "pm")]
    fields += [f"may_21_{p}" for p in ("am", "md", "pm")]
    fields += [f"oct_21_{p}" for p in ("am", "md", "pm")]
    fields += ["may_22_am", "may_22_md", "may_22_p_m"]
    fields += [f"oct_22_{p}" for p in ("am", "md", "pm")]
    fields += ["may_23_am", "may_23_md", "may_23_p_m"]
    fields += [f"oct_23_{p}" for p in ("am", "md", "pm")]
    fields += [f"june_24_{p}" for p in ("am", "md", "pm")]
    fields += [f"oct24_{p}" for p in ("am", "md", "pm")]
    fields += [f"may25_{p}" for p in ("am", "md", "pm")]
    fields += [f"oct25_{p}" for p in ("am", "md", "pm")]
    fields += [f"may26_{p}" for p in ("am", "md", "pm")]

    row = {f: "1" for f in fields}
    rounds = dp.rounds_in([row])
    assert len(rounds) == 37
    assert rounds[0] == "2007-05" and rounds[-1] == "2026-05"
    assert "2019-09" not in rounds and "2020-05" not in rounds   # never counted
    assert "2024-06" in rounds and "2024-05" not in rounds       # spring was June
    assert dp.latest_round([row]) == (2026, 5)
    # Every field maps to a (round, period); nothing is silently skipped.
    assert sum(1 for f in fields if dp.parse_round(f)) == len(fields) == 111


def test_latest_round_ignores_a_round_that_is_missing_a_period():
    rows = [{"may_25_am": "1", "may_25_md": "2", "may_25_pm": "3",
             "oct_25_am": "9"}]
    assert dp.latest_round(rows) == (2025, 5)


def test_latest_round_raises_when_no_round_is_complete():
    with pytest.raises(dp.DotCountError):
        dp.latest_round([{"may_26_am": "1"}])


def test_loc_type_uses_loc_and_the_borough_label_together():
    assert dp.loc_type(57, "Manhattan") == "on_street"
    assert dp.loc_type(101, "East River Bridges") == "east_river_bridge"
    assert dp.loc_type(110, "Harlem River Bridges") == "harlem_river_bridge"
    # The two signals disagreeing is reported, never resolved by a guess.
    assert dp.loc_type(57, "East River Bridges") == "bridge_disputed"
    assert dp.loc_type(101, "Queens") == "bridge_disputed"


# ------------------------------------------------------- wide -> long

def _wide_fixture() -> list[dict]:
    """Three points x three rounds, exercising every rule at once: a null cell
    (absent key), a zero count, a bridge point, and one incomplete round."""
    return [
        {"the_geom": {"type": "Point", "coordinates": [-73.99, 40.75]},
         "loc": "57", "borough": "Manhattan", "street_nam": "West 34th Street",
         "from_stree": "Broadway", "to_street": "Seventh Avenue", "iex": "Y",
         "may_25_am": "100", "may_25_md": "200", "may_25_pm": "300",
         "oct25_am": "110", "oct25_md": "210", "oct25_pm": "310",
         "may26_am": "120", "may26_md": "220", "may26_pm": "320"},
        {"the_geom": {"type": "Point", "coordinates": [-73.95, 40.70]},
         "loc": "58", "borough": "Brooklyn", "street_nam": "Bedford Avenue",
         "from_stree": "N 7 St", "to_street": "N 8 St", "iex": "N",
         "may_25_am": "10", "may_25_md": "0", "may_25_pm": "30",
         # oct25 entirely absent -- this point was not counted that round.
         "may26_am": "12", "may26_md": "22"},          # incomplete round
        {"the_geom": {"type": "Point", "coordinates": [-73.97, 40.71]},
         "loc": "103", "borough": "East River Bridges",
         "street_nam": "Williamsburg Bridge", "from_stree": None,
         "to_street": None, "iex": "N",
         "may_25_am": "1", "may_25_md": "2", "may_25_pm": "3",
         "oct25_am": "4", "oct25_md": "5", "oct25_pm": "6",
         "may26_am": "7", "may26_md": "8", "may26_pm": "9"},
    ]


def test_long_form_conserves_every_cell_of_the_wide_file(monkeypatch):
    monkeypatch.setattr(dp, "MIN_ROUNDS", 1)
    rows = _wide_fixture()
    records, rep = dp.to_long(rows)

    # One row per NON-NULL cell, and not one more.
    non_meta = [(r["loc"], f, v) for r in rows for f, v in r.items()
                if dp.parse_round(f)]
    # 9 cells at point 57, 5 at point 58 (one round absent, one incomplete),
    # 9 at the bridge = 23 of the 27-cell grid.
    assert len(records) == len(non_meta) == 23
    assert rep["cells_present"] == 23
    # cells_possible is the full grid; the difference is rounds a point was not
    # in the programme for, NOT zeros.
    assert rep["cells_possible"] == 3 * 3 * 3 == 27
    assert rep["total_count"] == sum(int(v) for _, _, v in non_meta)

    # A ZERO is a row. Dropping it would fabricate a gap.
    zeros = [r for r in records if r["count"] == 0]
    assert len(zeros) == 1 == rep["zero_counts"]
    assert (zeros[0]["point_id"], zeros[0]["round"], zeros[0]["period"]) == (58, "2025-05", "md")

    # An ABSENT cell is no row. Writing it as 0 would fabricate an empty street.
    assert not [r for r in records if r["point_id"] == 58 and r["round"] == "2025-10"]
    # ... and an incomplete round keeps the periods it does have.
    may26_58 = {r["period"] for r in records if r["point_id"] == 58 and r["round"] == "2026-05"}
    assert may26_58 == {"am", "md"}

    # Bridges are INGESTED and flagged, never dropped at the door.
    bridge = [r for r in records if r["point_id"] == 103]
    assert len(bridge) == 9 and all(r["is_bridge"] for r in bridge)
    assert bridge[0]["loc_type"] == "east_river_bridge"
    assert rep["on_street_points"] == 2 and rep["bridge_points"] == 1

    # Provenance: the ORIGINAL column name rides with every cell.
    assert {r["source_field"] for r in records} == {f for _, f, _ in non_meta}


def test_to_long_refuses_a_feed_that_lost_its_rounds():
    """A parser that stops recognising the column family must RAISE, not write
    a thin table -- three rounds where there should be 37 reads downstream as
    'DOT only started counting in 2024'."""
    rows = _wide_fixture()
    with pytest.raises(dp.DotCountError, match="parsed only"):
        dp.to_long(rows)          # MIN_ROUNDS is 30; the fixture has 3


def test_to_long_drops_a_row_with_no_geometry_and_counts_it(monkeypatch):
    monkeypatch.setattr(dp, "MIN_ROUNDS", 1)
    rows = _wide_fixture()
    rows[1]["the_geom"] = None
    records, rep = dp.to_long(rows)
    assert rep["dropped_rows_without_geometry"] == 1
    assert not [r for r in records if r["point_id"] == 58]


# -------------------------------------------------------------- the write

@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute("""CREATE TABLE analysis.address (
                    address_id VARCHAR, borough VARCHAR, lon DOUBLE, lat DOUBLE,
                    gap_score DOUBLE, homes_400m BIGINT)""")
    c.execute((SQL_DIR / "022_dot.sql").read_text())
    return c


def test_ingest_is_idempotent_and_refuses_an_empty_write(con, monkeypatch):
    monkeypatch.setattr(dp, "MIN_ROUNDS", 1)
    records, _ = dp.to_long(_wide_fixture())
    assert dp.write_counts(con, records) == 23
    assert con.execute("SELECT count(*) FROM staging.dot_pedestrian_count").fetchone()[0] == 23
    # Running it again replaces, never appends -- the PK would reject a double
    # insert anyway, which is the second line of defence.
    dp.write_counts(con, records)
    assert con.execute("SELECT count(*) FROM staging.dot_pedestrian_count").fetchone()[0] == 23
    with pytest.raises(dp.DotCountError):
        dp.write_counts(con, [])


def test_the_harness_reads_the_table_and_rebuilds_the_feeds_wide_shape(con, monkeypatch):
    """validation/pedestrian_counts.py must see exactly what it used to fetch,
    DOT's original column spellings included."""
    monkeypatch.setattr(dp, "MIN_ROUNDS", 1)
    wide = _wide_fixture()
    dp.write_counts(con, dp.to_long(wide)[0])

    from loci.validation import pedestrian_counts as pc
    rebuilt = pc.fetch_points(con)
    assert len(rebuilt) == 3
    by_loc = {int(r["loc"]): r for r in rebuilt}
    assert by_loc[57]["may26_pm"] == "320"
    assert by_loc[58]["may_25_md"] == "0"           # the zero survives
    assert "oct25_am" not in by_loc[58]             # the absent cell stays absent
    assert by_loc[57]["the_geom"]["coordinates"] == [-73.99, 40.75]
    # The harness's own logic, unchanged, on the rebuilt rows.
    assert pc.latest_round(rebuilt) == (2026, 5)
    pts, rep = pc.on_street_counts(rebuilt, 2026, 5)
    assert [p["loc"] for p in pts] == [57]          # 58 incomplete, 103 a bridge
    assert pts[0]["count"] == 120 + 220 + 320
    assert rep["dropped_bridge_points"] == 1


def test_point_summary_trend_is_per_year_not_per_round(con, monkeypatch):
    """The rounds are unevenly spaced, so the slope must be fitted on decimal
    years. Two rounds a year at +100 each round is +200/year, not +100."""
    monkeypatch.setattr(dp, "MIN_ROUNDS", 1)
    recs = []
    for i, rnd in enumerate(["2024-05", "2024-10", "2025-05", "2025-10", "2026-05"]):
        for per in ("am", "md", "pm"):
            recs.append({"point_id": 1, "round": rnd, "period": per,
                         "count": 100 + 50 * i, "lon": -73.9, "lat": 40.7,
                         "borough": "Manhattan", "street": "A", "from_street": "B",
                         "to_street": "C", "is_bridge": False,
                         "loc_type": "on_street", "is_index": True,
                         "source_field": f"x{i}_{per}"})
    dp.write_counts(con, recs)
    df = dp.point_summary(con, trend_years=10)
    row = df.iloc[0]
    assert row.latest_round == "2026-05"
    assert (row.latest_am, row.latest_md, row.latest_pm) == (300, 300, 300)
    assert row.trend_n_rounds == 5
    # totals 300,450,600,750,900 over t = 2024.33,2024.75,2025.33,2025.75,2026.33
    assert row.trend_per_year == pytest.approx(300.0, rel=0.05)


# ------------------------------------------------------ the camera registry

def _camera_feed() -> list[dict]:
    return [
        {"id": "aaa", "name": "Central Park West @ 86 St", "latitude": 40.7853,
         "longitude": -73.9694, "area": "Manhattan", "isOnline": "true",
         "imageUrl": "https://webcams.nyctmc.org/api/cameras/aaa/image"},
        {"id": "bbb", "name": "Bedford Av @ N 7 St", "latitude": 40.7171,
         "longitude": -73.9569, "area": "Brooklyn", "isOnline": "false",
         "imageUrl": "https://webcams.nyctmc.org/api/cameras/bbb/image"},
        {"id": "ccc", "name": "Somewhere new", "latitude": 40.60,
         "longitude": -74.10, "area": "Governors Island", "isOnline": "true",
         "imageUrl": "https://webcams.nyctmc.org/api/cameras/ccc/image"},
    ]


def test_is_online_is_parsed_from_the_string_not_truthiness():
    """The feed sends 'false', and bool('false') is True. Getting this wrong
    marks every dead camera live."""
    cams, rep = dc.normalise(_camera_feed())
    by_id = {c["camera_id"]: c for c in cams}
    assert by_id["aaa"]["is_online"] is True
    assert by_id["bbb"]["is_online"] is False
    assert rep["online"] == 2 and rep["offline"] == 1


def test_area_maps_to_a_borough_code_and_an_unknown_area_is_null_not_a_guess():
    cams, rep = dc.normalise(_camera_feed())
    by_id = {c["camera_id"]: c for c in cams}
    assert by_id["aaa"]["borough"] == "MN"
    assert by_id["bbb"]["borough"] == "BK"
    assert by_id["ccc"]["borough"] is None
    assert by_id["ccc"]["area"] == "Governors Island"      # raw value kept
    assert rep["unknown_areas"] == ["Governors Island"]


def test_a_camera_outside_nyc_or_without_a_position_is_dropped_and_counted():
    feed = _camera_feed() + [
        {"id": "ddd", "name": "no position", "area": "Bronx", "isOnline": "true"},
        {"id": "eee", "name": "gulf of guinea", "latitude": 0.0, "longitude": 0.0,
         "area": "Bronx", "isOnline": "true"},
        {"id": "", "name": "no id", "latitude": 40.7, "longitude": -73.9,
         "area": "Bronx", "isOnline": "true"},
    ]
    cams, rep = dc.normalise(feed)
    assert len(cams) == 3
    assert rep["dropped_without_geometry"] == 1
    assert rep["dropped_outside_nyc"] == 1
    assert rep["dropped_without_id"] == 1


def test_the_camera_table_is_exactly_the_contract_the_sampler_builds_against(con):
    """Column names and types are an INTERFACE. A rename here breaks a build
    that is not in this repository's test suite, so it is pinned."""
    cams, _ = dc.normalise(_camera_feed())
    assert dc.write_cameras(con, cams) == 3
    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'staging' AND table_name = 'dot_camera' "
        "ORDER BY ordinal_position").fetchall()
    assert cols == [
        ("camera_id", "VARCHAR"), ("name", "VARCHAR"), ("lon", "DOUBLE"),
        ("lat", "DOUBLE"), ("image_url", "VARCHAR"), ("is_online", "BOOLEAN"),
        ("area", "VARCHAR"), ("borough", "VARCHAR"), ("fetched_at", "TIMESTAMP"),
    ]
    assert dc.COLUMNS == [c[0] for c in cols]
    url = con.execute("SELECT image_url FROM staging.dot_camera WHERE camera_id = 'aaa'").fetchone()[0]
    assert url == "https://webcams.nyctmc.org/api/cameras/aaa/image"


def test_camera_write_refuses_to_empty_the_registry(con):
    with pytest.raises(dc.CameraFeedError):
        dc.write_cameras(con, [])


def test_a_duplicate_camera_id_raises_because_it_is_the_samplers_key():
    feed = _camera_feed() + [dict(_camera_feed()[0])]
    with pytest.raises(dc.CameraFeedError, match="duplicate"):
        dc.normalise(feed)


def test_fetch_cameras_raises_on_a_truncated_pull(tmp_path, monkeypatch):
    """An empty or short registry must never be ingested: 'no camera is near
    any address' is a confident wrong answer."""
    monkeypatch.setattr(dc, "RAW_ROOT", tmp_path)
    (tmp_path / f"cameras_{dt.date.today().isoformat()}.json").write_text(
        json.dumps(_camera_feed()))
    with pytest.raises(dc.CameraFeedError, match="fewer than"):
        dc.fetch_cameras()


# ------------------------------------------------------- the address context

@pytest.fixture()
def fixture_db(con, monkeypatch):
    """Two count points, two cameras, four addresses at known offsets."""
    monkeypatch.setattr(dp, "MIN_ROUNDS", 1)
    dp.write_counts(con, dp.to_long(_wide_fixture())[0])
    dc.write_cameras(con, dc.normalise(_camera_feed())[0])
    con.execute("""INSERT INTO analysis.address
                   (address_id, borough, lon, lat, gap_score, homes_400m) VALUES
                   ('a1', 'MN', -73.9900, 40.7500, 0.5, 100),
                   ('a2', 'MN', -73.9800, 40.7500, 0.6, 200),
                   ('a3', 'BK', -73.9500, 40.7000, 0.7, 300),
                   ('a4', 'BK', -73.9000, 40.6500, 0.8, 400)""")
    return con


def test_address_context_finds_the_nearest_on_street_point_and_camera(fixture_db):
    df, rep = adc.compute_context(fixture_db, ["MN", "BK"])
    by_id = df.set_index("address_id")

    # a1 sits exactly on point 57.
    assert by_id.loc["a1", "dot_point_id"] == 57
    assert by_id.loc["a1", "dot_point_m"] < 1.0
    # a3 sits exactly on point 58.
    assert by_id.loc["a3", "dot_point_id"] == 58
    # The BRIDGE point (103) is nearer to nothing, because it is excluded.
    assert 103 not in set(df["dot_point_id"])
    assert rep["count_points"] == 2         # 57 and 58; the bridge is filtered

    # a2 is ~0.01 deg of longitude east of point 57: ~845 m at this latitude.
    assert 800 < by_id.loc["a2", "dot_point_m"] < 900

    # The latest COMPLETE round per point: 57 has may26 complete, 58 does not
    # (am+md only), so 58 falls back to may25 rather than writing NULL counts.
    assert by_id.loc["a1", "dot_latest_round"] == "2026-05"
    assert (by_id.loc["a1", "dot_latest_am"], by_id.loc["a1", "dot_latest_md"],
            by_id.loc["a1", "dot_latest_pm"]) == (120, 220, 320)
    assert by_id.loc["a3", "dot_latest_round"] == "2025-05"
    assert by_id.loc["a3", "dot_latest_md"] == 0          # a counted zero

    # Cameras: nearest is found and the OFFLINE one is still eligible (the flag
    # is a publication flag, not a liveness one, and filtering on it would
    # silently shrink the universe).
    assert by_id.loc["a3", "camera_id"] == "bbb"
    assert by_id.loc["a1", "camera_id"] == "aaa"
    assert (df["camera_m"] >= 0).all()


def test_distances_are_metres_not_degrees(fixture_db):
    """The one invariant DuckDB cannot enforce: GEOMETRY carries no SRID and
    these are plain DOUBLEs. 0.01 degrees of longitude read as metres would be
    0.01, not ~845."""
    df, _ = adc.compute_context(fixture_db, ["MN"])
    a2 = df.set_index("address_id").loc["a2", "dot_point_m"]
    assert a2 > 100          # degrees would give 0.01
    assert a2 < 2000


def test_write_context_is_update_only_and_touches_no_other_column(fixture_db):
    before = fixture_db.execute(
        "SELECT address_id, gap_score, homes_400m FROM analysis.address "
        "ORDER BY address_id").fetchall()
    df, _ = adc.compute_context(fixture_db, ["MN", "BK"])
    n = adc.write_context(fixture_db, df, ["MN", "BK"])
    after = fixture_db.execute(
        "SELECT address_id, gap_score, homes_400m FROM analysis.address "
        "ORDER BY address_id").fetchall()
    assert n == 4
    assert before == after                     # no INSERT, no DELETE, no clobber
    assert fixture_db.execute(
        "SELECT count(*) FROM analysis.address WHERE dot_context_run_at IS NULL"
    ).fetchone()[0] == 0


def test_write_context_resets_scope_so_a_stale_value_cannot_survive(fixture_db):
    df, _ = adc.compute_context(fixture_db, ["MN", "BK"])
    adc.write_context(fixture_db, df, ["MN", "BK"])
    # Re-run over the SAME scope with a frame that no longer contains the BK
    # addresses -- an address that left scope must not keep the previous run's
    # numbers. The RESET is what makes that true; UPDATE alone has no DELETE to
    # fall back on. (Narrowing the scope to ["MN"] deliberately leaves BK
    # untouched: out of scope is out of scope, not silently blanked.)
    mn = df[df["borough"] == "MN"]
    adc.write_context(fixture_db, mn, ["MN", "BK"])
    bk_nulls = fixture_db.execute(
        "SELECT count(*) FROM analysis.address "
        "WHERE borough = 'BK' AND dot_point_id IS NULL").fetchone()[0]
    assert bk_nulls == 2
    assert fixture_db.execute(
        "SELECT count(*) FROM analysis.address "
        "WHERE borough = 'MN' AND dot_point_id IS NOT NULL").fetchone()[0] == 2


def test_the_column_list_is_disjoint_from_every_sibling_annotation():
    """_guard is belt; this is braces. A SET list that overlapped another
    module's columns would blank them on every run."""
    adc._guard(adc.DOT_CONTEXT_COLUMNS)         # must not raise
    with pytest.raises(RuntimeError, match="clobber"):
        adc._guard(["gap_score"])


def test_a_partial_frame_is_refused_rather_than_blanking_columns(fixture_db):
    df, _ = adc.compute_context(fixture_db, ["MN"])
    with pytest.raises(RuntimeError, match="missing"):
        adc.write_context(fixture_db, df.drop(columns=["camera_m"]), ["MN"])


def test_an_un_ingested_database_raises_instead_of_writing_nulls(con):
    con.execute("""INSERT INTO analysis.address
                   (address_id, borough, lon, lat) VALUES ('a1','MN',-73.99,40.75)""")
    with pytest.raises(RuntimeError, match="dot_pedestrian_count"):
        adc.compute_context(con, ["MN"])


def test_an_empty_address_scope_raises_rather_than_resetting_everything(fixture_db):
    with pytest.raises(RuntimeError, match="no addresses"):
        adc.compute_context(fixture_db, ["QN"])
