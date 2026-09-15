"""Citi Bike OD leakage on the card (phase 2, GTM-167) — model/bike_od.py.

A synthetic world small enough that every share below is worked out by hand in
the test that asserts it. The bug classes guarded here are the ones this measure
is most likely to get wrong, and the five the red-team pass of 2026-09-15 found:

  * a SILENT ZERO where the honest answer is NULL — an NTA with no residential
    dock must not read "its riders go nowhere" (owner ruling R3);
  * a BOROUGH DUMMY wearing a retail label: POIs per ADDRESS made 27 of 110 NTAs
    above median in all fifteen categories, so the denominator is residential
    UNITS and two NTAs with identical POI counts per address must now separate;
  * PHANTOM NTAs — one address and 728 POIs — clearing every threshold by
    arithmetic accident;
  * a trip FLOOR applied to the total but not to the outbound subset, so a
    neighbourhood whose riders almost all stay could publish a share read off
    twenty rides;
  * a STALE COLUMN: an address_category rebuild wipes bike_od_supplied_share, and
    a POI closure sweep moves the supply set, neither of which the window string
    can see;
  * the NTA-grain value drifting between two addresses in the same NTA;
  * the ratio > 1 gate (D39) leaking onto categories that are already present;
  * round trips folded into the origin, inflating every "they stay" reading;
  * the leakage window counted TWICE (a Saturday evening trip is ONE trip);
  * a share outside [0, 1], which reads as a plausible number downstream.

The fixture builds `analysis.bike_od_leakage` from the ruled DDL in
gtm167_spec.md §Grain and table. Track A owns sql/037; this file never touches
it, and never opens the real warehouse.
"""
from __future__ import annotations

import datetime as dt
import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from loci.model import bike_od as bo

# The spec's table contract, verbatim in columns and types.
OD_DDL = """
CREATE TABLE analysis.bike_od_leakage (
    origin_nta        VARCHAR,
    destination_nta   VARCHAR,
    month             DATE,
    day_type          VARCHAR,
    daypart           VARCHAR,
    origin_type       VARCHAR,
    trips             BIGINT,
    member_trips      BIGINT,
    round_trips       BIGINT,
    n_origin_stations SMALLINT,
    n_dest_stations   SMALLINT,
    ingested_at       TIMESTAMP
)
"""

#: Three real neighbourhoods and one phantom. A sends riders out; B is the
#: destination; C has no residential dock; P is BX0401 — one address, many POIs.
A, B, C, P = "BK0101", "BK0202", "BK0303", "BX0401"

POINTS = {A: (-73.990, 40.700), B: (-73.960, 40.720),
          C: (-73.930, 40.740), P: (-73.900, 40.760)}

#: Lot-frame addresses per NTA, and residential units per address. A and B carry
#: the SAME number of addresses and DIFFERENT unit counts — that is the whole
#: point: under POIs-per-address they are indistinguishable, and under POIs per
#: 1,000 units they are not. P is under MIN_UNIVERSE_ADDRESSES on purpose.
FRAME = {A: (600, 4), B: (600, 1), C: (600, 2), P: (1, 1)}


def _cell(lon: float, lat: float) -> str:
    import h3

    return h3.latlng_to_cell(lat, lon, bo.H3_RES)


@pytest.fixture
def warehouse(tmp_path):
    """A temporary DuckDB with the tables the measures read and write."""
    con = duckdb.connect(str(tmp_path / "od.duckdb"))
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("CREATE SCHEMA staging; CREATE SCHEMA analysis")
    con.execute(OD_DDL)
    con.execute("""
        CREATE TABLE analysis.hex (
            h3_index VARCHAR, resolution SMALLINT, borough VARCHAR,
            nta_code VARCHAR)""")
    con.executemany(
        "INSERT INTO analysis.hex VALUES (?, ?, 'Brooklyn', ?)",
        [(_cell(lon, lat), bo.H3_RES, nta)
         for nta, (lon, lat) in POINTS.items()])

    con.execute("""
        CREATE TABLE analysis.address (
            address_id VARCHAR, borough VARCHAR, nta_code VARCHAR,
            neighborhood VARCHAR, units INTEGER,
            lon DOUBLE, lat DOUBLE, frame VARCHAR DEFAULT 'lot',
            bike_od_top_nta VARCHAR, bike_od_top_nta_share DOUBLE,
            bike_od_out_share DOUBLE, bike_od_outside_share DOUBLE,
            bike_od_window VARCHAR, bike_od_supply_hash VARCHAR,
            bike_od_run_at TIMESTAMP)""")
    rows = []
    for nta, (n_addr, units) in FRAME.items():
        lon, lat = POINTS[nta]
        for i in range(n_addr):
            rows.append((f"{nta}-{i}", "BK", nta, f"name {nta}", units,
                         lon + 1e-6 * i, lat, "lot"))
    rows.append(("MN9999-0", "MN", "MN0101", "Chelsea", 5, -73.99, 40.75, "lot"))
    con.executemany(
        "INSERT INTO analysis.address (address_id, borough, nta_code, "
        "neighborhood, units, lon, lat, frame) VALUES (?,?,?,?,?,?,?,?)", rows)

    con.execute("""
        CREATE TABLE analysis.address_category (
            address_id VARCHAR, borough VARCHAR, category VARCHAR,
            ratio DOUBLE, bike_od_supplied_share DOUBLE)""")
    # grocery is MISSING (ratio > 1) everywhere; bar is PRESENT (ratio <= 1), so
    # the D39 gate has something to hold. Only the three real NTAs, to keep the
    # fixture's category table small.
    cat_rows = [(f"{n}-{i}", "BK", cat, ratio)
                for n in (A, B, C) for i in range(FRAME[n][0])
                for cat, ratio in (("grocery", 2.0), ("bar", 0.5))]
    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, "
        "ratio) VALUES (?, ?, ?, ?)", cat_rows)

    con.execute("""
        CREATE TABLE analysis.poi_supply_status (
            poi_id VARCHAR, category VARCHAR, poi_status VARCHAR,
            geom GEOMETRY)""")
    # A and B each hold THREE open groceries. Equal per address; 1.25 vs 5.00 per
    # 1,000 units. The closed one in B must be gated out (D94).
    pois = ([(f"g-a{i}", "grocery", "open", A) for i in range(3)]
            + [(f"g-b{i}", "grocery", "open", B) for i in range(3)]
            + [("g-b-dead", "grocery", "closed", B)]
            + [(f"bar-{n}", "bar", "open", n) for n in (A, B)]
            # the phantom: 20 groceries on one address
            + [(f"g-p{i}", "grocery", "open", P) for i in range(20)])
    con.executemany(
        "INSERT INTO analysis.poi_supply_status (poi_id, category, poi_status, "
        "geom) VALUES (?, ?, ?, ST_Point(?, ?))",
        [(pid, cat, st, POINTS[n][0], POINTS[n][1]) for pid, cat, st, n in pois])

    con.execute("""
        CREATE TABLE staging.citibike_station (
            station_id VARCHAR, name VARCHAR, lon DOUBLE, lat DOUBLE)""")
    con.executemany(
        "INSERT INTO staging.citibike_station VALUES (?, ?, ?, ?)",
        [(f"dock-{n}", f"dock {n}", POINTS[n][0], POINTS[n][1]) for n in POINTS])

    con.execute("""
        CREATE TABLE staging.dot_pedestrian_count (
            point_id INTEGER, round VARCHAR, period VARCHAR, count INTEGER,
            lon DOUBLE, lat DOUBLE, is_bridge BOOLEAN)""")
    return con


def _od(con, rows: list[tuple]) -> None:
    """rows: (origin, destination, month, day_type, daypart, origin_type,
    trips, round_trips)."""
    con.executemany(
        "INSERT INTO analysis.bike_od_leakage (origin_nta, destination_nta, "
        "month, day_type, daypart, origin_type, trips, member_trips, "
        "round_trips, n_origin_stations, n_dest_stations, ingested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, now())",
        [(o, d, dt.date.fromisoformat(m), dtp, dp, ot, t, t // 2, r)
         for o, d, m, dtp, dp, ot, t, r in rows])


#: The hand-worked world. A's residential docks send, in the leakage window,
#: 900 non-round trips: 300 stay in A (400 gross, 100 of them round) and 600 go
#: to B. Plus a weekday pm_peak row the window must EXCLUDE and a
#: 'destination'-type row the origin_type filter must exclude.
BASE_FLOW = [
    (A, A, "2026-08-01", "weekday",  "evening", "residential", 400, 100),
    (A, B, "2026-08-01", "weekday",  "evening", "residential", 300, 0),
    (A, B, "2026-08-01", "saturday", "evening", "residential", 300, 0),
    (A, B, "2026-08-01", "weekday",  "pm_peak", "residential", 900, 0),
    (A, B, "2026-08-01", "weekday",  "evening", "destination",  900, 0),
    (B, B, "2026-08-01", "weekday",  "evening", "residential", 500, 0),
    (B, A, "2026-08-01", "saturday", "midday",  "residential", 250, 0),
]

W0, W1 = dt.date(2026, 8, 1), dt.date(2026, 8, 1)


@pytest.fixture
def loaded(warehouse):
    _od(warehouse, BASE_FLOW)
    return warehouse


def _parts(con, min_trips: int = bo.MIN_ORIGIN_TRIPS):
    f = bo.flow(con, W0, W1)
    d = bo.supply_density(con)
    return f, d, bo.supply_thresholds(d), min_trips


# --------------------------------------------------------------- the window

def test_window_comes_from_the_table_not_from_today(loaded):
    assert bo.window_bounds(loaded, 12) == (W0, W1)
    assert bo.window_label(W0, W1) == "2026-08..2026-08"


def test_an_empty_table_raises_rather_than_stamping_null_everywhere(warehouse):
    with pytest.raises(RuntimeError, match="empty"):
        bo.window_bounds(warehouse)


# ------------------------------------------------------------------ the flow

def test_the_window_is_counted_once_and_pm_peak_is_excluded(loaded):
    f = bo.flow(loaded, W0, W1)
    a = f[f["origin_nta"] == A].set_index("destination_nta")["trips"]
    assert a[A] == 300.0          # 400 gross - 100 round
    assert a[B] == 600.0          # 300 weekday evening + 300 saturday evening
    assert len(a) == 2            # the pm_peak and 'destination' rows are gone


def test_a_saturday_evening_trip_is_one_trip_not_two(warehouse):
    """The leakage window is an OR. Expanded into a sum, a saturday-evening row
    would be counted on both arms and the share would break [0, 1]."""
    _od(warehouse, [(A, B, "2026-08-01", "saturday", "evening",
                     "residential", 1000, 0)])
    assert bo.flow(warehouse, W0, W1)["trips"].sum() == 1000.0


def test_round_trips_are_never_folded_into_the_origin(loaded):
    m = bo.nta_measures(loaded, W0, W1)
    row = m[m["nta_code"] == A].iloc[0]
    assert row["trips_total"] == 900.0
    assert row["bike_od_out_share"] == pytest.approx(600 / 900)
    assert row["bike_od_top_nta"] == B
    assert row["bike_od_top_nta_share"] == pytest.approx(600 / 900)


def test_an_nta_below_the_trip_floor_is_absent_not_zero(loaded):
    m = bo.nta_measures(loaded, W0, W1, min_trips=800)
    assert set(m["nta_code"]) == {A}          # B's 750 is below the floor


# ---------------------------------------------------------------- the supply

def test_supply_density_is_per_1k_units_not_per_address(loaded):
    """RED-TEAM FIX 1. A and B hold three open groceries each across the same
    number of addresses, so a per-address density cannot tell them apart. Per
    1,000 residential units they are 1.25 and 5.00."""
    d = bo.supply_density(loaded)
    g = d[d["category"] == "grocery"].set_index("nta_code")
    assert g.loc[A, "n_pois"] == g.loc[B, "n_pois"] == 3   # the tie per address
    assert g.loc[A, "poi_per_1k_units"] == pytest.approx(3 / 2.4)
    assert g.loc[B, "poi_per_1k_units"] == pytest.approx(3 / 0.6)
    assert g.loc[C, "poi_per_1k_units"] == 0.0
    t = bo.supply_thresholds(d).set_index("category")["threshold"]
    assert t["grocery"] == pytest.approx((1.25 + 5.0) / 2)
    assert g.loc[B, "poi_per_1k_units"] > t["grocery"]
    assert g.loc[A, "poi_per_1k_units"] < t["grocery"]


def test_a_phantom_nta_is_outside_the_universe(loaded):
    """RED-TEAM FIX 2. BX0401: one address, twenty open groceries. Its density is
    an arithmetic accident and it must not be a measurable destination."""
    d = bo.supply_density(loaded)
    assert P not in set(d["nta_code"])
    assert set(d["nta_code"]) == {A, B, C}
    # and it is not in the universe at ANY POI count -- the floor is on addresses
    assert bo.MIN_UNIVERSE_ADDRESSES == 500


def test_the_universe_floor_can_be_relaxed_for_a_deliberate_look(loaded):
    d = bo.supply_density(loaded, min_addresses=1)
    assert P in set(d["nta_code"])


def test_the_threshold_is_the_median_over_ntas_that_have_the_category(loaded):
    t = bo.supply_thresholds(bo.supply_density(loaded)).set_index("category")
    # A category with no open POI anywhere is unmeasurable, never 0.
    assert np.isnan(t.loc["pharmacy", "threshold"])


def test_supplied_share_is_right_by_hand(loaded):
    """A sends 600 out-of-NTA trips, all to B, and only B clears the grocery
    threshold. So A's grocery supplied_share is 1.0 and B's (250 trips, all to A)
    is 0.0."""
    cat, outside, rep = bo.supplied_share(*_parts(loaded))
    s = cat.set_index(["nta_code", "category"])["bike_od_supplied_share"]
    assert s[(A, "grocery")] == pytest.approx(1.0)
    assert s[(B, "grocery")] == pytest.approx(0.0)
    assert rep["origins"] == 2
    o = outside.set_index("nta_code")["bike_od_outside_share"]
    assert o[A] == pytest.approx(0.0) and o[B] == pytest.approx(0.0)


def test_a_category_with_no_threshold_is_null_not_zero(loaded):
    cat, _, _ = bo.supplied_share(*_parts(loaded))
    s = cat.set_index(["nta_code", "category"])["bike_od_supplied_share"]
    assert np.isnan(s[(A, "pharmacy")])


def test_trips_to_a_phantom_nta_count_as_outside_the_universe(warehouse):
    _od(warehouse, [
        (A, B, "2026-08-01", "weekday", "evening", "residential", 600, 0),
        (A, P, "2026-08-01", "weekday", "evening", "residential",  60, 0),
    ])
    cat, outside, _ = bo.supplied_share(*_parts(warehouse))
    o = outside.set_index("nta_code")["bike_od_outside_share"]
    assert o[A] == pytest.approx(60 / 660)
    s = cat.set_index(["nta_code", "category"])["bike_od_supplied_share"]
    assert s[(A, "grocery")] == pytest.approx(1.0)     # still under the 20% bar


def test_an_origin_over_the_outside_bar_is_null(warehouse):
    """RED-TEAM FIX 2, second half: 0.2, not 0.5. 30% outside is already a number
    about a selected majority."""
    assert bo.MAX_OUTSIDE_UNIVERSE_SHARE == 0.2
    _od(warehouse, [
        (A, B, "2026-08-01", "weekday", "evening", "residential", 700, 0),
        (A, P, "2026-08-01", "weekday", "evening", "residential", 300, 0),
    ])
    cat, outside, rep = bo.supplied_share(*_parts(warehouse))
    assert outside.set_index("nta_code").loc[A, "bike_od_outside_share"] == \
        pytest.approx(0.3)
    s = cat.set_index(["nta_code", "category"])["bike_od_supplied_share"]
    assert np.isnan(s[(A, "grocery")])
    assert rep["origins_dropped_outside_universe"] == 1


def test_the_trip_floor_is_applied_to_the_outbound_subset_too(warehouse):
    """RED-TEAM FIX 3. C's total flow is 5,050 — far over the floor — but only 50
    trips ever leave. A supplied_share read off fifty rides is not a reading."""
    _od(warehouse, [
        (C, C, "2026-08-01", "weekday", "evening", "residential", 5000, 0),
        (C, B, "2026-08-01", "weekday", "evening", "residential",   50, 0),
    ])
    # nta_measures lets it through: its floor is on the TOTAL, correctly.
    assert C in set(bo.nta_measures(warehouse, W0, W1)["nta_code"])
    cat, _, rep = bo.supplied_share(*_parts(warehouse))
    s = cat.set_index(["nta_code", "category"])["bike_od_supplied_share"]
    assert np.isnan(s[(C, "grocery")])
    assert rep["origins_dropped_thin_outbound"] == 1
    # and it passes once the floor is low enough to be honest about 50 trips
    cat2, _, _ = bo.supplied_share(*_parts(warehouse, min_trips=10))
    s2 = cat2.set_index(["nta_code", "category"])["bike_od_supplied_share"]
    assert s2[(C, "grocery")] == pytest.approx(1.0)


def test_shares_outside_zero_one_raise(loaded):
    bad = pd.DataFrame({"bike_od_out_share": [1.4]})
    with pytest.raises(RuntimeError, match=r"outside \[0, 1\]"):
        bo.check_shares_in_bounds(bad, ["bike_od_out_share"])


# ----------------------------------------------------------------- the write

def test_the_build_stamps_every_address_and_nulls_the_ones_with_no_dock(loaded):
    nta, cat, rep = bo.build_bike_od(loaded, boroughs=["BK"], re_sweep=True)
    got = loaded.execute(
        "SELECT nta_code, borough, bike_od_top_nta, bike_od_out_share, "
        "       bike_od_window, bike_od_supply_hash, bike_od_run_at "
        "FROM analysis.address").fetchdf()
    bk = got[got["nta_code"].isin((A, B, C))]
    assert bk["bike_od_window"].notna().all()
    assert bk["bike_od_run_at"].notna().all()
    assert bk["bike_od_supply_hash"].notna().all()
    c = bk[bk["nta_code"] == C]                 # no residential dock: NULL, not 0
    assert c["bike_od_out_share"].isna().all()
    assert c["bike_od_top_nta"].isna().all()
    mn = got[got["borough"] == "MN"]            # out of scope, untouched
    assert mn["bike_od_window"].isna().all()
    assert rep["_written"]["ntas_measured"] == len(nta)
    assert not cat.empty


def test_the_outside_share_is_stored_on_the_address(loaded):
    bo.build_bike_od(loaded, boroughs=["BK"], re_sweep=True)
    v = loaded.execute(
        "SELECT DISTINCT bike_od_outside_share FROM analysis.address "
        "WHERE nta_code = ?", [A]).fetchall()
    assert v == [(0.0,)]


def test_the_value_is_identical_for_every_address_in_the_nta(loaded):
    bo.build_bike_od(loaded, boroughs=["BK"], re_sweep=True)
    n = loaded.execute(
        "SELECT nta_code, count(DISTINCT bike_od_out_share) AS n_vals, "
        "       count(DISTINCT bike_od_top_nta) AS n_tops "
        "FROM analysis.address GROUP BY 1").fetchdf()
    assert (n["n_vals"] <= 1).all()
    assert (n["n_tops"] <= 1).all()
    a = loaded.execute("SELECT DISTINCT bike_od_out_share FROM analysis.address "
                       "WHERE nta_code = ?", [A]).fetchall()
    assert a[0][0] == pytest.approx(600 / 900)


def test_the_ratio_gate_is_respected(loaded):
    """`bar` is PRESENT at every address (ratio 0.5). The measure is about what is
    MISSING, so those rows stay NULL while `grocery` (ratio 2.0) fills."""
    bo.build_bike_od(loaded, boroughs=["BK"], re_sweep=True)
    by = loaded.execute(
        "SELECT category, count(bike_od_supplied_share) AS filled "
        "FROM analysis.address_category GROUP BY 1").fetchdf().set_index("category")
    assert by.loc["bar", "filled"] == 0
    assert by.loc["grocery", "filled"] == FRAME[A][0] + FRAME[B][0]


def test_the_category_value_is_the_nta_value_stamped_on_each_address(loaded):
    bo.build_bike_od(loaded, boroughs=["BK"], re_sweep=True)
    got = loaded.execute(
        "SELECT a.nta_code, count(DISTINCT g.bike_od_supplied_share) AS n_vals, "
        "       any_value(g.bike_od_supplied_share) AS v "
        "FROM analysis.address_category g JOIN analysis.address a USING (address_id) "
        "WHERE g.category = 'grocery' GROUP BY 1").fetchdf().set_index("nta_code")
    assert (got["n_vals"] <= 1).all()
    assert got.loc[A, "v"] == pytest.approx(1.0)
    assert got.loc[B, "v"] == pytest.approx(0.0)


def test_dry_run_writes_nothing(loaded):
    bo.build_bike_od(loaded, boroughs=["BK"], dry_run=True, re_sweep=True)
    assert loaded.execute(
        "SELECT count(bike_od_run_at) FROM analysis.address").fetchone()[0] == 0


def test_the_writer_refuses_a_column_another_module_owns():
    with pytest.raises(RuntimeError, match="clobber"):
        bo._guard(["bike_starts_400m"], bo.BIKE_OD_CATEGORY_COLUMNS)
    with pytest.raises(RuntimeError, match="clobber"):
        bo._guard(bo.BIKE_OD_ADDRESS_COLUMNS, ["supply_ratio_vs_base"])


# ------------------------------------------------------- the rebuild detector

def test_a_rerun_without_re_sweep_is_a_no_op_and_re_sweep_forces_it(loaded):
    bo.build_bike_od(loaded, boroughs=["BK"], re_sweep=True)
    _, _, rep = bo.build_bike_od(loaded, boroughs=["BK"])
    assert "skipped" in rep["_written"]
    loaded.execute("UPDATE analysis.address SET bike_od_window = NULL")
    _, _, rep2 = bo.build_bike_od(loaded, boroughs=["BK"])
    assert "skipped" not in rep2["_written"]


def test_a_moved_supply_hash_forces_a_rebuild(loaded):
    """RED-TEAM FIX 4a. A POI closure sweep changes supply_density under an
    unchanged window, and nothing in the window string can see it."""
    bo.build_bike_od(loaded, boroughs=["BK"], re_sweep=True)
    window = bo.window_label(W0, W1)
    live = bo.live_supply_hash(loaded)
    assert bo.needs_rebuild(loaded, ["BK"], window, live) is False
    assert bo.needs_rebuild(loaded, ["BK"], window, "a-different-hash") is True


def test_an_address_category_rebuild_forces_a_rebuild(loaded):
    """RED-TEAM FIX 4b. `loci address-gaps` re-creates address_category, wiping
    bike_od_supplied_share while analysis.address stays fully stamped. An
    address-only detector reports 'nothing to do' and the column stays NULL
    forever."""
    _, cat, _ = bo.build_bike_od(loaded, boroughs=["BK"], re_sweep=True)
    window, live = bo.window_label(W0, W1), bo.live_supply_hash(loaded)
    assert bo.needs_rebuild(loaded, ["BK"], window, live, cat) is False
    loaded.execute("UPDATE analysis.address_category "
                   "SET bike_od_supplied_share = NULL")
    # the address side is untouched and still says "done"
    assert bo.needs_rebuild(loaded, ["BK"], window, live) is False
    assert bo.needs_rebuild(loaded, ["BK"], window, live, cat) is True
    _, _, rep = bo.build_bike_od(loaded, boroughs=["BK"])
    assert "skipped" not in rep["_written"]


# ------------------------------------------------------------- the card line

def _names_riders_not_residents(line: str) -> bool:
    """The population the sentence is ABOUT must be riders. `residential docks`
    is R2's dimension name and `riders are not residents` is the standing
    caveat; both are allowed. `residents` as the subject of the flow is not."""
    low = line.lower().replace("residential", "").replace(
        "riders are not residents", "")
    return "riders" in line.lower() and "resident" not in low


def test_the_card_line_says_riders_and_neighbourhood_wide_never_residents():
    line = bo.card_line(A, B, 600 / 900, 600 / 900, window="2025-09..2026-08",
                        labels={A: "Bushwick", B: "Williamsburg"})
    assert _names_riders_not_residents(line)
    assert "neighbourhood-wide" in line.lower()
    assert "Bushwick" in line and "Williamsburg" in line
    assert "67%" in line


def test_the_card_line_names_its_denominator(loaded):
    """RED-TEAM FIX 5. out_share and supplied_share have different denominators;
    quoting both without saying so invites a reader to subtract them."""
    line = bo.card_line(A, B, 0.6, 0.6, labels={A: "Bushwick", B: "Williamsburg"})
    assert "trips that stay included" in line


def test_the_card_line_for_a_null_states_the_absence_rather_than_a_zero():
    line = bo.card_line(C, None, None, None, labels={C: "Red Hook"})
    assert "not measured" in line
    assert "0%" not in line
    assert "dock network" in line
    assert _names_riders_not_residents(line)
    # a NaN out of a pandas frame must read as NULL too, not crash on format
    assert "not measured" in bo.card_line(C, None, float("nan"), float("nan"))


def test_the_card_line_words_a_stay_at_home_neighbourhood_as_one():
    line = bo.card_line(B, B, 0.55, 0.20, labels={B: "Williamsburg"})
    assert "stay in Williamsburg" in line
    assert "20% leave" in line


def test_the_category_card_line_names_its_conditional_denominator():
    """RED-TEAM FIX 5. The share is over trips landing where supply is
    measurable, and the rest is quoted rather than hidden."""
    line = bo.category_card_line(A, "grocery", 0.82, outside_share=0.13,
                                 labels={A: "Bushwick"})
    assert "82%" in line
    assert "Manhattan or Brooklyn neighbourhood we can measure" in line
    assert "13% went elsewhere" in line
    assert "per 1,000 homes" in line
    assert _names_riders_not_residents(line)
    assert "neighbourhood-wide" in line.lower()
    assert "not measured" in bo.category_card_line(C, "grocery", None)
    assert "not measured" in bo.category_card_line(C, "grocery", float("nan"))


def test_nta_labels_name_a_queens_destination_instead_of_printing_a_code(tmp_path):
    """RED-TEAM FIX 5. A raw QN0201 on a card is not an answer to 'where do
    riders go', and Queens and Bronx destinations are common."""
    (tmp_path / "interim").mkdir()
    (tmp_path / "interim" / "nta_names.json").write_text(
        json.dumps({"QN0201": "Long Island City", A: "Greenpoint"}))
    labels = bo.nta_labels(graph_path=tmp_path / "interim" / "walk.pkl")
    assert labels["QN0201"] == "Long Island City"
    line = bo.card_line(A, "QN0201", 0.4, 0.7, labels=labels)
    assert "Long Island City" in line and "QN0201" not in line


# ------------------------------------------------------------- §Validation

def test_the_report_carries_the_monthly_iqr_of_the_top_share(warehouse):
    """RED-TEAM FIX 5. The pooled window is summer-weighted (August ~2.5x
    February), so the width of the top-share across months belongs in the report
    beside it — reported, never stored: it is a property of the window."""
    _od(warehouse, [
        (A, B, "2026-07-01", "weekday", "evening", "residential", 100, 0),
        (A, A, "2026-07-01", "weekday", "evening", "residential", 900, 0),
        (A, B, "2026-08-01", "weekday", "evening", "residential", 900, 0),
        (A, A, "2026-08-01", "weekday", "evening", "residential", 100, 0),
    ])
    _, _, rep = bo.build_bike_od(warehouse, boroughs=["BK"], dry_run=True)
    iqr = rep["top_share_monthly_iqr"]
    assert iqr["months"] == 2
    # B is the pooled top (1,000 of 2,000); monthly shares are 0.10 and 0.90.
    assert iqr["median_iqr"] == pytest.approx(0.4)


def test_the_placebo_returns_a_full_category_matrix_with_a_unit_diagonal(loaded):
    mat, summary = bo.placebo(loaded)
    assert mat.shape == (15, 15)
    assert list(mat.index) == list(mat.columns)
    assert np.allclose(np.diag(mat.to_numpy()), 1.0)
    assert summary["diag"] == 1.0
    assert len(summary["per_category"]) == 15


def test_the_placebo_gate_is_the_null_baseline_not_the_off_diagonal(loaded):
    """RED-TEAM FIX 1. The old bar (mean off-diagonal rho < 0.95) gated nothing:
    destination supply density already correlates across categories at 0.76 mean
    / 0.94 max, so anything short of a literal copy passed."""
    assert not hasattr(bo, "OFFDIAG_TIE_RHO")
    assert bo.NULL_BASELINE_MIN_EXCESS == 0.05
    _, summary = bo.placebo(loaded)
    assert "null_baseline" in summary
    assert summary["bar"] == bo.NULL_BASELINE_MIN_EXCESS
    assert (set(summary["categories_passing"])
            | set(summary["categories_failing"])
            == set(summary["per_category"]["category"]))


def test_the_null_baseline_is_the_busy_destination_share():
    """A destination above median in ALL FIFTEEN categories is just a busy
    neighbourhood. A category that cannot beat that share is measuring busyness."""
    cats = sorted(__import__("loci.categories", fromlist=["x"]).CATEGORIES)
    density = pd.DataFrame(
        [{"nta_code": n, "category": c, "poi_per_1k_units": v}
         for n, v in (("BUSY", 10.0), ("QUIET", 0.1), ("ORIGIN", 1.0))
         for c in cats])
    thresholds = pd.DataFrame({"category": cats, "threshold": [1.0] * len(cats)})
    flow_df = pd.DataFrame({
        "origin_nta": ["ORIGIN", "ORIGIN"],
        "destination_nta": ["BUSY", "QUIET"],
        "trips": [300.0, 700.0]})
    null, all_cat = bo.null_baseline(flow_df, density, thresholds)
    assert all_cat == ["BUSY"]
    assert null["ORIGIN"] == pytest.approx(0.3)


def test_dot_validation_refuses_an_empty_instrument(loaded):
    with pytest.raises(RuntimeError, match="no usable points"):
        bo.dot_validation(loaded)


def test_dot_validation_ranks_inflow_against_dot_and_names_the_baseline(loaded):
    _od(loaded, [(B, C, "2026-08-01", "saturday", "evening",
                  "residential", 120, 0)])
    loaded.executemany(
        "INSERT INTO staging.dot_pedestrian_count VALUES (?, '2026-05', 'pm', "
        "?, ?, ?, FALSE)",
        [(i, c, POINTS[n][0], POINTS[n][1])
         for i, (n, c) in enumerate([(A, 100), (B, 900), (C, 300)])])
    rep = bo.dot_validation(loaded)
    assert rep["n_ntas"] == 3
    assert rep["dot_period"] == "pm"
    assert -1.0 <= rep["rho_inflow_vs_dot"] <= 1.0
    assert rep["rho_baseline_supply_density_vs_dot"] == \
        rep["rho_baseline_poi_per_addr_vs_dot"]
    assert rep["bar"] == bo.DOT_RHO_BAR
    assert "placebo_null_baseline" in rep
