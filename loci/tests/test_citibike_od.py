"""Citi Bike OD leakage (phase 2, GTM-167).

Everything here runs against a TEMPORARY DuckDB built in `tmp_path`, never the
warehouse. sql/037_citibike_od.sql carries a `.draft` suffix on purpose --
`db.init_schema` globs `*.sql` on every write connection, so an undrafted file
would go live on a peer session's write and move the shared supply hash -- and
these tests therefore apply the draft's TEXT explicitly.

The bug classes guarded here are the ones this project keeps getting bitten by:

  * a SILENT ZERO -- an h3 join written against the BIGINT form of the index
    against a VARCHAR column matches nothing and reads as a city where nobody
    rode; a month with no phase-1 panel types every dock 'unknown' and empties
    the residential class;
  * DOUBLE COUNTING -- the leakage window is a UNION (evening OR weekend) and
    must be counted ONCE, and round trips must never be folded into a
    destination;
  * a CLASSIFIER THAT MEASURES SOMETHING ELSE -- the ticket's literal am/pm
    volume share measures the citywide diurnal curve, not a neighbourhood;
  * LOST OR INVENTED TRIPS -- OD must reconcile to phase 1's `starts` net of
    exactly the exclusions it names.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import duckdb
import h3
import pytest

from loci.sources.cities.nyc import citibike as cb
from loci.sources.cities.nyc import citibike_od as od

REPO = pathlib.Path(__file__).resolve().parents[1]
DRAFT = REPO / "src" / "loci" / "sql" / "037_citibike_od.sql"   # landed 2026-09-15 (D108); developed as .sql.draft

LYFT_HEADER = ("ride_id,rideable_type,started_at,ended_at,start_station_name,"
               "start_station_id,end_station_name,end_station_id,start_lat,"
               "start_lng,end_lat,end_lng,member_casual")

#: One dock per NTA, so an origin NTA IS an origin dock and the conservation
#: test can be read at the station grain the ticket states it at.
DOCKS = {
    "1001.01": (40.7000, -73.9900),      # residential by construction
    "2002.02": (40.7400, -73.9500),      # destination
    "3003.03": (40.7100, -73.9800),      # too quiet to type -> unknown
    "4004.04": (40.7200, -73.9700),      # mixed
}
#: Filler trips per calendar date. Every date must carry a trip or
#: `assert_month_complete` raises -- but the file must also be big enough that
#: the ONE Jersey City end below stays under `MAX_OUT_OF_SYSTEM_SHARE` (1%),
#: which is the same ratio a real month has (~0.005%) rather than a fixture
#: artefact that would refuse the whole month.
FILLERS_PER_DATE = 5

#: What the hand-built station-month below is shaped to produce.
#: (am_starts, am_ends, pm_starts, pm_ends) per dock.
PEAKS = {
    "1001.01": (300, 100, 100, 300),     # leave in the am, return in the pm
    "2002.02": (100, 300, 300, 100),     # the mirror image
    "3003.03": (10, 10, 10, 10),         # balanced but under the trip floor
    "4004.04": (200, 200, 200, 200),     # balanced and busy
}


# --------------------------------------------------------------- the migration

def test_the_migration_is_live_and_no_draft_lingers():
    """db.init_schema applies EVERY src/loci/sql/*.sql on the next write
    connection, including uncommitted ones, and three sessions share this tree
    (D105/D106). 037 was developed as 037_citibike_od.sql.draft (invisible to the
    glob) and renamed by the session lead after announcing to the peers (D108).
    A lingering .draft twin would mean two divergent copies of one migration."""
    assert DRAFT.exists(), DRAFT
    assert not DRAFT.with_suffix(".sql.draft").exists(), "a .draft twin of 037 lingers"


def test_the_sql_header_carries_the_caveats_the_columns_cannot():
    text = DRAFT.read_text()
    for phrase in ("RIDERS ARE NOT RESIDENTS", "ENDOGENOUS", "NO TRIP PURPOSE",
                   "ROUND TRIPS", "BOUNDARY MISASSIGNMENT", "CONTEXT ONLY"):
        assert phrase in text, phrase


# ------------------------------------------------------- the fixture warehouse

def _apply_draft(con) -> None:
    con.execute(DRAFT.read_text())


@pytest.fixture
def warehouse(tmp_path):
    """A tiny TEMPORARY warehouse: four docks in four NTAs, one address each.

    `analysis.hex` is built from the docks' own h3 cells, so the dock -> NTA
    join is exercised for real rather than stubbed.
    """
    con = duckdb.connect(str(tmp_path / "od.duckdb"))
    con.execute((REPO / "src" / "loci" / "sql" / "001_bootstrap.sql").read_text())
    con.execute("CREATE SCHEMA staging; CREATE SCHEMA analysis")
    con.execute("""
        CREATE TABLE analysis.hex (
            h3_index VARCHAR, resolution SMALLINT, land_fraction FLOAT,
            borough VARCHAR, nta_code VARCHAR)""")
    con.execute("""
        CREATE TABLE analysis.address (
            address_id VARCHAR, nta_code VARCHAR, borough VARCHAR)""")
    con.execute("""
        CREATE TABLE analysis.address_category (
            address_id VARCHAR, category VARCHAR, ratio DOUBLE)""")
    con.execute("""
        CREATE TABLE staging.citibike_station_month (
            station_id VARCHAR, station_name VARCHAR, lon DOUBLE, lat DOUBLE,
            month DATE, day_type VARCHAR, daypart VARCHAR,
            starts BIGINT, ends BIGINT, member_starts BIGINT,
            casual_starts BIGINT, member_ends BIGINT, casual_ends BIGINT,
            days_in_cell SMALLINT, ingested_at TIMESTAMP)""")
    _apply_draft(con)

    for i, (sid, (lat, lon)) in enumerate(DOCKS.items()):
        con.execute("INSERT INTO analysis.hex (h3_index, resolution, land_fraction, borough, nta_code) VALUES (?, 9, 1.0, 'Brooklyn', ?)",
                    [h3.latlng_to_cell(lat, lon, od.H3_RES), f"NTA{i}"])
        con.execute("INSERT INTO analysis.address (address_id, nta_code, borough) VALUES (?, ?, 'Brooklyn')",
                    [f"a{i}", f"NTA{i}"])

    rows = []
    for sid, (lat, lon) in DOCKS.items():
        am_s, am_e, pm_s, pm_e = PEAKS[sid]
        for day_type, days in (("weekday", 22), ("saturday", 4), ("sunday", 4)):
            for part in cb.DAYPART_NAMES:
                s = am_s if part == "am_peak" else (pm_s if part == "pm_peak" else 5)
                e = am_e if part == "am_peak" else (pm_e if part == "pm_peak" else 5)
                if day_type != "weekday":       # the classifier reads weekdays only
                    s = e = 7
                rows.append((sid, f"dock {sid}", lon, lat, dt.date(2026, 4, 1),
                             day_type, part, s, e, s, 0, e, 0, days))
    con.executemany(
        "INSERT INTO staging.citibike_station_month (station_id, station_name, "
        "lon, lat, month, day_type, daypart, starts, ends, member_starts, "
        "casual_starts, member_ends, casual_ends, days_in_cell) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return con


def _trip(rid, start, end, s_id, e_id, member="member"):
    s_lat, s_lon = DOCKS.get(s_id, (40.70, -73.99))
    e_lat, e_lon = DOCKS.get(e_id, (40.71, -73.98))
    return (f"{rid},classic_bike,{start},{end},S{s_id},{s_id},E{e_id},{e_id},"
            f"{s_lat},{s_lon},{e_lat},{e_lon},{member}")


@pytest.fixture
def fake_month(tmp_path):
    """A hand-built April 2026: 30 filler trips (one per calendar date, so
    `assert_month_complete` is satisfied) plus the trips the assertions are
    about. April 2026 carries no federal holiday."""
    rows = [LYFT_HEADER]
    for day in range(1, 31):                      # FILLERS_PER_DATE per date, midday
        for k in range(FILLERS_PER_DATE):
            rows.append(_trip(f"F{day:03d}{k}", f"2026-04-{day:02d} 12:05:00",
                              f"2026-04-{day:02d} 12:20:00", "1001.01", "2002.02"))
    rows += [
        # weekday evening -- IN the leakage window
        _trip("W1", "2026-04-07 19:30:00", "2026-04-07 19:50:00", "1001.01", "2002.02"),
        # weekday pm_peak -- the commute home, deliberately OUT of the window
        _trip("W2", "2026-04-07 17:30:00", "2026-04-07 17:50:00", "1001.01", "2002.02"),
        # Saturday midday and Saturday EVENING. The second is in the window by
        # BOTH clauses and must be counted ONCE.
        _trip("S1", "2026-04-11 14:00:00", "2026-04-11 14:20:00", "1001.01", "2002.02"),
        _trip("S2", "2026-04-11 20:00:00", "2026-04-11 20:20:00", "1001.01", "2002.02"),
        # a Sunday ROUND trip: no destination information at all
        _trip("R1", "2026-04-12 15:00:00", "2026-04-12 15:40:00", "1001.01", "1001.01"),
        # a dockless end and a Jersey City end: excluded, counted, never folded
        ("X1,electric_bike,2026-04-09 10:00:00,2026-04-09 10:10:00,"
         "S1001.01,1001.01,,,40.7000,-73.9900,40.7050,-73.9850,member"),
        _trip("X2", "2026-04-09 11:00:00", "2026-04-09 11:20:00", "1001.01", "JC115"),
    ]
    p = tmp_path / "202604-citibike-tripdata_1.csv"
    p.write_text("\n".join(rows) + "\n")
    return tmp_path


# ------------------------------------------------- origin_type, the R2 ruling

@pytest.mark.parametrize("sid,expect", [
    ("1001.01", "residential"), ("2002.02", "destination"),
    ("3003.03", "unknown"), ("4004.04", "mixed"),
])
def test_the_classifier_bands_are_the_owner_ruling(warehouse, sid, expect):
    types, rep = od.classify_origin_type(warehouse, 2026, 4)
    got = types.set_index("station_id").loc[sid, "origin_type"]
    assert got == expect
    assert rep["docks"] == 4
    assert set(rep) >= set(od.ORIGIN_TYPES)


def test_a_quiet_dock_is_unknown_and_never_a_silent_residential(warehouse):
    """3003.03 has a BALANCED peak shape and 40 weekday trips. Balanced would be
    'mixed', but under the trip floor the four numbers are noise, so the honest
    answer is 'unknown' -- a dock we cannot type, not a dock with no commuters.
    Typing it anyway would put a phantom residential origin, and therefore a
    phantom leakage flow, on exactly the blocks where the evidence is thinnest."""
    types, _ = od.classify_origin_type(warehouse, 2026, 4)
    row = types.set_index("station_id").loc["3003.03"]
    assert row["weekday_trips"] < od.MIN_STATION_MONTH_TRIPS
    assert row["origin_type"] == "unknown"


def test_a_month_with_no_phase_one_panel_raises_rather_than_typing_everything_unknown(
        warehouse):
    with pytest.raises(cb.CitibikeError, match="computed FROM the phase-1 panel"):
        od.classify_origin_type(warehouse, 2026, 5)


@pytest.mark.parametrize("am_s,am_e,pm_s,pm_e", [
    (300, 100, 100, 300), (100, 300, 300, 100), (200, 200, 200, 200),
    (101, 100, 100, 101), (7, 900, 900, 7), (150, 120, 130, 140),
])
def test_ratio_of_ratios_is_the_net_swing_form(am_s, am_e, pm_s, pm_e):
    """R2's parenthetical identity. `am_pm_share > 1` and the net-flow swing
    being positive are the SAME statement, because (x-1)/(x+1) is strictly
    increasing. Asserted so a future edit cannot quietly change what the bands
    mean while keeping the docstring."""
    share = (am_s / am_e) / (pm_s / pm_e)
    swing = od.net_swing(am_s, am_e, pm_s, pm_e)
    assert (share > 1) == (swing > 0)
    assert (share < 1) == (swing < 0)


def test_the_literal_am_over_pm_volume_share_is_a_different_measurement():
    """WHY the ticket's literal form was replaced. A dock people leave in the
    morning and return to in the evening is residential on the ratio of ratios,
    and can still carry MORE pm volume than am volume -- which is true of
    essentially every dock in the system (59 of 2,611 over the panel pass the
    literal test). The literal test measures the citywide diurnal curve."""
    am_s, am_e, pm_s, pm_e = 300, 100, 400, 900        # clearly residential shape
    assert (am_s / am_e) / (pm_s / pm_e) > od.RESIDENTIAL_ABOVE
    assert (am_s + am_e) < (pm_s + pm_e)               # ...and fails "am share > 1"


# ------------------------------------------------------------- dock -> NTA

def test_every_dock_maps_and_none_is_dropped_silently(warehouse):
    docks, rep = od.dock_nta(warehouse, 2026, 4)
    assert rep == {"docks": 4, "mapped": 4, "unmapped": 0, "ntas": 4}
    assert len(docks) == 4


def test_a_dock_outside_the_hex_frame_raises_instead_of_shrinking_the_panel(warehouse):
    warehouse.execute("DELETE FROM analysis.hex WHERE nta_code = 'NTA0'")
    with pytest.raises(cb.CitibikeError, match="no cell in analysis.hex"):
        od.dock_nta(warehouse, 2026, 4)


def test_the_hex_index_is_the_string_form_not_the_bigint_one(warehouse):
    """The silent-zero trap in this migration. `analysis.hex.h3_index` is the
    15-character STRING; DuckDB's `h3_latlng_to_cell` returns the BIGINT form and
    joins to NOTHING, which reads downstream as a city where nobody rode. The
    module uses python `h3` (the addresses' own rule); this asserts the two
    spellings and that only one of them matches."""
    lat, lon = DOCKS["1001.01"]
    as_string = warehouse.execute(
        f"SELECT h3_latlng_to_cell_string({lat}, {lon}, 9)").fetchone()[0]
    assert as_string == h3.latlng_to_cell(lat, lon, od.H3_RES)
    hit = warehouse.execute(
        f"SELECT count(*) FROM analysis.hex "
        f"WHERE h3_index = h3_latlng_to_cell({lat}, {lon}, 9)::VARCHAR").fetchone()[0]
    assert hit == 0, "the BIGINT form must NOT match -- that is the trap"


# -------------------------------------------------- the aggregation, end to end

def _od(warehouse, fake_month, tmp_path):
    return od.od_month_frame(warehouse, str(fake_month / "*.csv"), 2026, 4,
                             tmp_path, min_trips=1)


def test_trips_conserve_against_phase_one_net_of_the_named_exclusions(
        warehouse, fake_month, tmp_path):
    """The arithmetic proof that OD neither invents nor loses a trip. Summed per
    origin NTA (= per dock here, one dock to an NTA) x day_type x daypart, the
    OD cells must equal phase 1's `starts` MINUS exactly the trips OD excludes
    and phase 1 does not: an end with no dock, and an end on another operator's
    dock."""
    df, audit = _od(warehouse, fake_month, tmp_path)
    p1, _ = cb.month_frame(str(fake_month / "*.csv"), 2026, 4, tmp_path, min_trips=1)

    starts = p1.groupby(["station_id", "day_type", "daypart"])["starts"].sum()
    nta = {f"NTA{i}": sid for i, sid in enumerate(DOCKS)}
    got = df.groupby(["origin_nta", "day_type", "daypart"])["trips"].sum()
    got.index = got.index.set_levels(
        [nta[v] for v in got.index.levels[0]], level=0)

    excluded = 0
    for key, n in got.items():
        assert n <= starts[key], key
        excluded += int(starts[key]) - int(n)
    # X1 (dockless end) and X2 (Jersey City end). Nothing else.
    assert excluded == 2
    assert audit["dropped_dockless_end"] == 1
    assert audit["dropped_out_of_system"] == 1
    assert audit["trips_dropped_unmapped_dock"] == 0


def test_round_trips_are_stored_separately_and_never_folded_into_a_destination(
        warehouse, fake_month, tmp_path):
    df, audit = _od(warehouse, fake_month, tmp_path)
    assert audit["round_trips"] == 1                     # R1
    r = df[df["round_trips"] > 0]
    assert len(r) == 1
    assert r.iloc[0]["origin_nta"] == r.iloc[0]["destination_nta"] == "NTA0"
    # `trips` is the GROSS count and includes it; the view is what subtracts.
    assert int(r.iloc[0]["trips"]) == 1
    assert (df["round_trips"] <= df["trips"]).all()
    assert (df["member_trips"] <= df["trips"]).all()


def test_the_origin_type_rides_along_from_the_station_month_panel(
        warehouse, fake_month, tmp_path):
    df, _ = _od(warehouse, fake_month, tmp_path)
    assert set(df["origin_type"]) == {"residential"}     # every trip leaves 1001.01
    assert set(df["origin_type"]) <= set(od.ORIGIN_TYPES)


def test_the_month_is_stamped_and_no_trip_escapes_into_a_neighbouring_month(
        warehouse, fake_month, tmp_path):
    df, _ = _od(warehouse, fake_month, tmp_path)
    assert set(df["month"].astype(str)) == {"2026-04-01"}


# ------------------------------------------------------------ idempotence

def test_writing_a_month_twice_is_identical(warehouse, fake_month, tmp_path):
    """The month is the unit of idempotence: DELETE WHERE month = ? then INSERT.
    A re-run that appended would double every flow in the panel -- the
    double-count bug in its plainest form."""
    df, _ = _od(warehouse, fake_month, tmp_path)
    n1 = od.write_od_month(warehouse, df, 2026, 4, dt.datetime(2026, 9, 15, 10))
    first = warehouse.execute(
        "SELECT count(*), sum(trips), sum(round_trips) "
        "FROM analysis.bike_od_leakage").fetchone()
    n2 = od.write_od_month(warehouse, df, 2026, 4, dt.datetime(2026, 9, 15, 11))
    second = warehouse.execute(
        "SELECT count(*), sum(trips), sum(round_trips) "
        "FROM analysis.bike_od_leakage").fetchone()
    assert n1 == n2 and first == second


def test_re_running_one_month_leaves_another_month_alone(warehouse, fake_month,
                                                         tmp_path):
    df, _ = _od(warehouse, fake_month, tmp_path)
    od.write_od_month(warehouse, df, 2026, 4, dt.datetime(2026, 9, 15, 10))
    may = df.copy()
    may["month"] = dt.date(2026, 5, 1)
    od.write_od_month(warehouse, may, 2026, 5, dt.datetime(2026, 9, 15, 10))
    od.write_od_month(warehouse, df, 2026, 4, dt.datetime(2026, 9, 15, 12))
    got = warehouse.execute(
        "SELECT month, count(*) FROM analysis.bike_od_leakage "
        "GROUP BY 1 ORDER BY 1").fetchall()
    assert [r[1] for r in got] == [len(df), len(df)]


def test_the_insert_names_its_columns(warehouse, fake_month, tmp_path):
    """D72: a `SELECT *` INSERT silently mis-mapped two type-compatible columns
    when a new one landed. The column list is the fix, and the order of
    OD_COLUMNS must match the table."""
    df, _ = _od(warehouse, fake_month, tmp_path)
    od.write_od_month(warehouse, df, 2026, 4, dt.datetime(2026, 9, 15, 10))
    cols = [r[0] for r in warehouse.execute(
        "SELECT column_name FROM information_schema.columns WHERE "
        "table_schema='analysis' AND table_name='bike_od_leakage' "
        "ORDER BY ordinal_position").fetchall()]
    assert cols == od.OD_COLUMNS


# ------------------------------------------------------------- the view

def _loaded(warehouse, fake_month, tmp_path):
    df, _ = _od(warehouse, fake_month, tmp_path)
    od.write_od_month(warehouse, df, 2026, 4, dt.datetime(2026, 9, 15, 10))
    return warehouse


def test_the_window_is_the_union_and_is_counted_once(warehouse, fake_month, tmp_path):
    """S2 is a Saturday EVENING trip: it satisfies both clauses of the window and
    is ONE trip. A window written as a sum instead of an OR would count it twice
    and push the share above 1 -- a number that reads as a plausible
    'very evening-heavy' answer to every downstream reader."""
    con = _loaded(warehouse, fake_month, tmp_path)
    n = con.execute(
        f"SELECT sum(trips) FROM analysis.bike_od_leakage WHERE "
        f"origin_type = 'residential' AND {od.LEAKAGE_WINDOW_SQL}").fetchone()[0]
    # W1 (weekday evening) + S1 + S2 (Saturday midday, Saturday evening)
    # + R1 (Sunday pm_peak) + the 8 filler midday trips that fall on a weekend.
    # W2 (weekday pm_peak) is NOT in the window.
    weekend_fillers = FILLERS_PER_DATE * sum(
        1 for d in range(1, 31)
        if cb.day_type_of_date(dt.date(2026, 4, d)) in ("saturday", "sunday"))
    assert n == 1 + 2 + 1 + weekend_fillers


def test_the_view_excludes_round_trips_and_its_share_is_a_share(
        warehouse, fake_month, tmp_path):
    con = _loaded(warehouse, fake_month, tmp_path)
    rows = con.execute(
        "SELECT origin_nta, destination_nta, trips, share, out_of_nta "
        "FROM analysis.bike_od_leakage_evening ORDER BY 1, 2").fetchall()
    # R1 is the ONLY NTA0 -> NTA0 trip in the window, so netting it out removes
    # that cell entirely: a round trip carries no destination.
    assert all(o != d for o, d, *_ in rows)
    for _o, _d, trips, share, out in rows:
        assert trips > 0
        assert 0.0 <= share <= 1.0
        assert out is True
    total = sum(r[3] for r in rows)
    assert total == pytest.approx(1.0)


def test_the_share_sums_to_one_within_an_origin_nta_and_month(
        warehouse, fake_month, tmp_path):
    """The share is partitioned by (origin_nta, month) rather than origin_nta
    alone, so a downstream `WHERE month BETWEEN ...` window cannot silently
    invalidate it."""
    con = _loaded(warehouse, fake_month, tmp_path)
    may = con.execute("SELECT * FROM analysis.bike_od_leakage").fetchdf()
    may["month"] = dt.date(2026, 5, 1)
    od.write_od_month(con, may, 2026, 5, dt.datetime(2026, 9, 15, 10))
    got = con.execute(
        "SELECT origin_nta, month, round(sum(share), 9) "
        "FROM analysis.bike_od_leakage_evening GROUP BY 1, 2").fetchall()
    assert len(got) == 2
    assert all(s == pytest.approx(1.0) for *_x, s in got)


def test_the_card_columns_exist_and_are_nullable(warehouse):
    cols = {r[0]: r[1] for r in warehouse.execute(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema='analysis' AND table_name='address'").fetchall()}
    for c in ("bike_od_top_nta", "bike_od_top_nta_share", "bike_od_out_share",
              "bike_od_window", "bike_od_run_at"):
        assert cols.get(c) == "YES", c
    cat = [r[0] for r in warehouse.execute(
        "SELECT column_name FROM information_schema.columns WHERE "
        "table_schema='analysis' AND table_name='address_category'").fetchall()]
    assert "bike_od_supplied_share" in cat


def test_the_validation_query_runs_and_reports_no_bad_rows(
        warehouse, fake_month, tmp_path):
    con = _loaded(warehouse, fake_month, tmp_path)
    df = con.execute(od.OD_VALIDATION_SQL).fetchdf()
    assert int(df["bad_round"].max()) == 0
    assert int(df["bad_member"].max()) == 0
    assert int(df["cells"].iloc[-1]) > 0


# --------------------------------------------------- one vocabulary, one clock

def test_the_feed_vocabulary_is_imported_not_restated():
    """One definition of 'am_peak is 06-10' and one of 'a New York public dock'.
    A second copy would drift and the two panels would stop meaning the same
    thing -- which is exactly how an OD flow and a station-month count become
    incomparable without anything raising."""
    src = (REPO / "src" / "loci" / "sources" / "cities" / "nyc"
           / "citibike_od.py").read_text()
    for fn in ("daypart_case_sql", "day_type_case_sql", "holiday_predicate_sql",
               "station_id_sql", "is_ny_station_sql", "read_csv_sql"):
        assert f"def {fn}" not in src, f"{fn} was REDEFINED instead of imported"
        assert fn in src


def test_nothing_od_reaches_a_score():
    """CONTEXT ONLY under D76 (R1): no gap_score, no supply_ratio_vs_base, no
    grade, and lambda in model/revenue.py is untouched."""
    for path in ("src/loci/score", "src/loci/model/recommend.py",
                 "src/loci/model/supply_ratio.py", "src/loci/model/revenue.py"):
        p = REPO / path
        files = p.rglob("*.py") if p.is_dir() else [p]
        for f in files:
            text = f.read_text()
            assert "bike_od" not in text, f
            assert "bike_od_leakage" not in text, f
