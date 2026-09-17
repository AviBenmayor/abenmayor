"""Citi Bike activity growth at address grain (phase 3, GTM-168) —
model/address_bike_growth.py.

A synthetic panel small enough that every number below is worked out by hand in
the test that asserts it. NOTHING HERE TOUCHES THE LIVE WAREHOUSE: a back-ingest
of 2021-02..2022-12 is running against it, so the live station-month table moves
under any read, and the whole point of this feature is that a window that moves
under it is a silent bug.

The bug classes guarded here are the ones this measure is most likely to get
wrong:

  * a NEW DOCK counted in the recent window and not the prior one, which turns
    every address near one into a boom and makes the feature a map of Lyft's
    capital plan (the D1 error with a trend line through it);
  * a RETIRED dock counted in the prior window and not the recent one, which
    manufactures the same thing with the sign flipped;
  * a SILENT ZERO where the honest answer is NULL — "the docks here did not get
    busier" is a claim about a neighbourhood, and the truth under the floor is a
    claim about a capital plan;
  * a PART-NULL row, which lets a downstream join read a growth with no activity
    behind it;
  * the DETREND applied as anything other than a subtraction of one system-wide
    scalar, which would make bike_growth_12m_rel a second measure rather than a
    detrend;
  * NETWORK EXPANSION folded into the feature instead of stored beside it as the
    control it is;
  * a PARTIAL WINDOW computed on rather than refused — eleven months against
    twelve is an 8% citywide "decline" that nothing in the output discloses;
  * the two VINTAGES overwriting each other, when two that disagree in sign is
    the R1 failure test;
  * WEEKEND rows summed into a weekday series.

sql/038 is applied here from its .draft text, exactly as it will read once the
lead renames it. This file never opens the real warehouse and never opens a
write connection to anything but its own tmp_path DuckDB.
"""
from __future__ import annotations

import datetime as dt
import math
import pathlib

import duckdb
import pandas as pd
import pytest

from loci.model import address_bike_growth as bg

DRAFT = (pathlib.Path(bg.__file__).resolve().parents[1]
         / "sql" / "038_bike_growth.sql")   # landed 2026-09-15 (D111); developed as .sql.draft

#: The vintage every test uses. Windows: prior 2024-09..2025-08, recent
#: 2025-09..2026-08.
M = dt.date(2026, 8, 1)
P_FIRST, P_LAST, R_FIRST, R_LAST = bg.windows(M)

#: (first_month, last_month, member per active month in the PRIOR window,
#:  member per active month in the RECENT window, casual prior, casual recent).
#: Every per-month value is divisible by 4 because `_station_month` splits it
#: across two weekday dayparts and across starts and ends.
DOCKS = {
    # balanced, doubles its member traffic; its casual half VANISHES, which is
    # what makes the all-rider robustness series read differently.
    "D1": ("2024-09-01", "2026-08-01", 500, 1000, 500, 0),
    # balanced, halves. D1 and D2 together make the system's log ratio exactly 0.
    "D2": ("2024-09-01", "2026-08-01", 1000, 500, 0, 0),
    # BORN MID-WINDOW (2025-06, inside the prior window) and busy: excluded from
    # BOTH windows, and big enough to push an address under the floor.
    "D3": ("2025-06-01", "2026-08-01", 3000, 3000, 0, 0),
    # RETIRED before M: a complete prior window and no recent one. Excluded from
    # BOTH, or it manufactures a collapse.
    "D4": ("2024-09-01", "2026-02-01", 5000, 5000, 0, 0),
    # born mid-window and QUIET: excluded from both windows, but small enough
    # that its address stays above the balanced-share floor.
    "D5": ("2025-06-01", "2026-08-01", 100, 100, 0, 0),
}

#: Which docks each lot address can walk to. ADDR-D reaches none.
REACH = {
    "ADDR-A": ["D1"],
    "ADDR-B": ["D2"],
    "ADDR-C": ["D1", "D3"],          # balanced share 1000/4000 = 0.25 -> NULL
    "ADDR-D": [],                    # no dock at all -> NULL
    "ADDR-E": ["D1", "D2", "D4"],    # the retired dock must not move the number
    "ADDR-F": ["D1", "D5"],          # 1000/1100 = 0.909 -> above the floor
}
BOROUGH = dict.fromkeys(REACH, "BK") | {"ADDR-MN": "MN"}

#: Hand-worked member totals over the twelve months of each window:
#:   D1 prior 12*500 = 6,000   recent 12*1,000 = 12,000
#:   D2 prior 12*1,000 = 12,000 recent 12*500 = 6,000
#: so the SYSTEM's balanced totals are 18,000 and 18,000 and its log ratio is 0.
G_A = math.log(12001) - math.log(6001)      # +0.69299…
G_B = math.log(6001) - math.log(12001)      # the mirror image


# --------------------------------------------------------------- the fixture

def _months(first: str, last: str) -> list[dt.date]:
    out, cur = [], dt.date.fromisoformat(first)
    stop = dt.date.fromisoformat(last)
    while cur <= stop:
        out.append(cur)
        cur = bg.add_months(cur, 1)
    return out


def _station_month(con, station_id: str, month: dt.date,
                   member_act: int, casual_act: int) -> None:
    """One dock-month: two WEEKDAY dayparts, each carrying a quarter of the
    activity as starts and a quarter as ends, so a module that forgets `ends`,
    forgets a daypart, or forgets to sum both halves cannot pass.

    Plus a SATURDAY row of 9,999 in every column. The series is weekday-only;
    if it leaks, every hand-worked number below breaks by an order of magnitude.
    """
    rows = [(dtp, dp, m_s, m_e, c_s, c_e) for dp in ("midday", "evening")
            for dtp, m_s, m_e, c_s, c_e in
            [("weekday", member_act // 4, member_act // 4,
              casual_act // 4, casual_act // 4)]]
    rows.append(("saturday", "midday", 9999, 9999, 9999, 9999))
    con.executemany(
        "INSERT INTO staging.citibike_station_month (station_id, station_name, "
        "lon, lat, month, day_type, daypart, starts, ends, member_starts, "
        "casual_starts, member_ends, casual_ends, days_in_cell, ingested_at) "
        "VALUES (?, ?, -73.95, 40.70, ?, ?, ?, ?, ?, ?, ?, ?, ?, 21, now())",
        [(station_id, f"dock {station_id}", month, dtp, dp,
          m_s + c_s, m_e + c_e, m_s, c_s, m_e, c_e)
         for dtp, dp, m_s, m_e, c_s, c_e in rows])


@pytest.fixture
def warehouse(tmp_path):
    """A temporary DuckDB carrying the tables the builder reads and writes.

    analysis.address_bike_growth comes from the .draft TEXT, so a column renamed
    in the migration and not here fails at the first test rather than in a peer's
    write connection.
    """
    con = duckdb.connect(str(tmp_path / "growth.duckdb"))
    con.execute("CREATE SCHEMA staging; CREATE SCHEMA analysis")
    con.execute("""
        CREATE TABLE staging.citibike_station_month (
            station_id VARCHAR, station_name VARCHAR, lon DOUBLE, lat DOUBLE,
            month DATE, day_type VARCHAR, daypart VARCHAR,
            starts BIGINT, ends BIGINT, member_starts BIGINT,
            casual_starts BIGINT, member_ends BIGINT, casual_ends BIGINT,
            days_in_cell SMALLINT, ingested_at TIMESTAMP)""")
    con.execute("""
        CREATE TABLE staging.citibike_station (
            station_id VARCHAR, name VARCHAR, lon DOUBLE, lat DOUBLE,
            first_month DATE, last_month DATE, months_active INTEGER,
            ingested_at TIMESTAMP)""")
    con.execute("""
        CREATE TABLE analysis.address (
            address_id VARCHAR, borough VARCHAR, lon DOUBLE, lat DOUBLE,
            frame VARCHAR DEFAULT 'lot')""")
    con.execute("""
        CREATE TABLE analysis.address_bike_station (
            address_id VARCHAR, borough VARCHAR, station_id VARCHAR,
            dist_m DOUBLE, radius_m REAL, graph_version VARCHAR,
            run_at TIMESTAMP)""")
    con.execute(DRAFT.read_text())
    return con


def _load_docks(con, docks: dict) -> None:
    for sid, (first, last, m_prior, m_recent, c_prior, c_recent) in docks.items():
        con.execute(
            "INSERT INTO staging.citibike_station (station_id, name, lon, lat, "
            "first_month, last_month, months_active, ingested_at) "
            "VALUES (?, ?, -73.95, 40.70, ?, ?, ?, now())",
            [sid, f"dock {sid}", dt.date.fromisoformat(first),
             dt.date.fromisoformat(last), len(_months(first, last))])
        for month in _months(first, last):
            recent = month >= R_FIRST
            _station_month(con, sid, month,
                           m_recent if recent else m_prior,
                           c_recent if recent else c_prior)


def _load_addresses(con, reach: dict) -> None:
    con.executemany(
        "INSERT INTO analysis.address (address_id, borough, lon, lat, frame) "
        "VALUES (?, ?, -73.95, 40.70, 'lot')",
        [(a, BOROUGH.get(a, "BK")) for a in reach])
    pairs = [(a, BOROUGH.get(a, "BK"), s) for a, docks in reach.items()
             for s in docks]
    if pairs:
        con.executemany(
            "INSERT INTO analysis.address_bike_station (address_id, borough, "
            "station_id, dist_m, radius_m, graph_version, run_at) "
            "VALUES (?, ?, ?, 120.0, 400.0, 'test', now())", pairs)


@pytest.fixture
def loaded(warehouse):
    _load_docks(warehouse, DOCKS)
    _load_addresses(warehouse, REACH)
    return warehouse


@pytest.fixture
def mirror(warehouse):
    """A panel that IS a faithful replica of its system: two balanced docks, one
    address on each, and every dock scaled by the SAME factor between the
    windows. That is the only condition under which the address values sum to
    zero, and the test that asserts it says so.
    """
    _load_docks(warehouse, {
        "D1": ("2024-09-01", "2026-08-01", 500, 1000, 0, 0),
        "D2": ("2024-09-01", "2026-08-01", 1000, 2000, 0, 0)})
    _load_addresses(warehouse, {"ADDR-A": ["D1"], "ADDR-B": ["D2"]})
    return warehouse


def _build(con, **kw) -> pd.DataFrame:
    meas, _ = bg.build_growth(con, M, ["BK"], **kw)
    return meas.set_index("address_id")


# ------------------------------------------------------------ the migration

def test_the_draft_declares_exactly_the_ruled_columns(warehouse):
    cols = [r[0] for r in warehouse.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'address_bike_growth' "
        "ORDER BY ordinal_position").fetchall()]
    assert cols == bg.GROWTH_COLUMNS


def test_the_migration_is_live_and_carries_the_caveat_header():
    # 038 was developed as 038_bike_growth.sql.draft — the suffix kept
    # db.init_schema's *.sql glob from applying it on a PEER session's write
    # connection (D105/D106) — and was renamed by the lead after announcing
    # to the peers (D111, 2026-09-15). A lingering .draft twin would mean two
    # divergent copies of one migration.
    assert DRAFT.name.endswith(".sql"), "038 must be the live migration"
    assert not DRAFT.with_suffix(".sql.draft").exists(), (
        "a .draft twin of 038 lingers next to the live migration")
    text = DRAFT.read_text().lower()
    for phrase in ("endogenous to retail", "e-bike", "riders are not residents",
                   "covid-recovery", "context only"):
        assert phrase in text, f"the caveat header has lost {phrase!r}"


# --------------------------------------------------------------- the windows

def test_the_windows_are_adjacent_twelve_month_blocks_that_do_not_overlap():
    p_first, p_last, r_first, r_last = bg.windows(M)
    assert (p_first, p_last, r_first, r_last) == (
        dt.date(2024, 9, 1), dt.date(2025, 8, 1),
        dt.date(2025, 9, 1), dt.date(2026, 8, 1))
    assert bg.add_months(p_last, 1) == r_first        # adjacent
    assert p_last < r_first                           # and disjoint
    # One August and one February in each, which is what makes the ratio
    # seasonally adjusted by construction rather than by a smoother.
    for first in (p_first, r_first):
        months = {bg.add_months(first, i).month for i in range(12)}
        assert months == set(range(1, 13))


def test_a_partial_panel_is_refused_and_the_missing_months_are_named(loaded):
    loaded.execute("DELETE FROM staging.citibike_station_month WHERE month = ?",
                   [dt.date(2025, 2, 1)])
    assert bg.missing_months(loaded, M) == [dt.date(2025, 2, 1)]
    with pytest.raises(RuntimeError, match="2025-02"):
        bg.require_panel(loaded, M)
    # ...and the builder refuses rather than comparing eleven months with twelve.
    with pytest.raises(RuntimeError, match="partial window"):
        bg.build_growth(loaded, M, ["BK"])


# ---------------------------------------------------------- the balanced set

def test_only_docks_alive_across_both_windows_are_balanced(loaded):
    panel = bg.station_panel(loaded, M).set_index("station_id")
    assert list(panel.loc[["D1", "D2"], "balanced"]) == [True, True]
    # D3 and D5 were born inside the window; D4 retired before M. None of the
    # three is balanced, and the two young ones are the ADDED ones.
    assert not panel.loc[["D3", "D4", "D5"], "balanced"].any()
    assert list(panel.loc[["D3", "D5"], "added_in_window"]) == [True, True]
    assert not panel.loc["D4", "added_in_window"]      # retired, not added
    # A dock is never both, and a dock whose first_month is exactly M-23 is
    # balanced rather than added: it was there for the whole span.
    assert not (panel["balanced"] & panel["added_in_window"]).any()


def test_a_dock_born_mid_window_contributes_to_neither_window(loaded):
    """D3 opens 2025-06 — inside the PRIOR window — and carries 3,000 a month.

    Folded into the recent window only, ADDR-C would read as a boom. Folded into
    both, it would still distort the ratio. It is in NEITHER, so ADDR-C's
    activity columns are D1's alone — and here D3 is big enough to also push
    ADDR-C under the balanced-share floor, which is the second half of the rule.
    """
    m = _build(loaded, dry_run=True)
    assert m.at["ADDR-C", "n_docks_balanced"] == 1
    assert m.at["ADDR-C", "docks_added_24m"] == 1
    # 1,000 of the 4,000 trips at month M are at the balanced dock.
    assert m.at["ADDR-C", "balanced_share"] == pytest.approx(0.25)


def test_a_young_dock_above_the_floor_still_enters_neither_window(loaded):
    """ADDR-F reaches D1 and the quiet young D5. It stays above the floor
    (1,000/1,100), so it gets a value — and that value must be IDENTICAL to
    ADDR-A's, which reaches D1 alone. If D5's 1,200-a-window showed up in either
    window the two would differ.
    """
    m = _build(loaded, dry_run=True)
    assert m.at["ADDR-F", "balanced_share"] == pytest.approx(1000 / 1100)
    assert m.at["ADDR-F", "docks_added_24m"] == 1
    assert m.at["ADDR-F", "activity_12m"] == m.at["ADDR-A", "activity_12m"]
    assert m.at["ADDR-F", "bike_growth_12m"] == pytest.approx(G_A)


def test_a_dock_retired_before_M_contributes_to_neither_window(loaded):
    """D4 ran at 5,000 a month from 2024-09 to 2026-02: a complete prior window
    and half a recent one. Counted in the prior window only, ADDR-E would read
    as a collapse. Excluded from both, ADDR-E is exactly D1 + D2 — whose totals
    are 18,000 against 18,000, i.e. no growth at all.
    """
    m = _build(loaded, dry_run=True)
    assert m.at["ADDR-E", "n_docks_balanced"] == 2
    assert m.at["ADDR-E", "docks_added_24m"] == 0
    assert m.at["ADDR-E", "activity_12m"] == pytest.approx(18000.0)
    assert m.at["ADDR-E", "activity_prior_12m"] == pytest.approx(18000.0)
    assert m.at["ADDR-E", "bike_growth_12m"] == pytest.approx(0.0)


def test_weekend_rows_never_reach_the_weekday_series(loaded):
    """Every dock-month carries a 9,999-a-column SATURDAY row. D1's twelve recent
    months are 12 x 1,000 member weekday trips and nothing else."""
    panel = bg.station_panel(loaded, M).set_index("station_id")
    assert panel.at["D1", "act_recent"] == pytest.approx(12000.0)
    assert panel.at["D1", "act_prior"] == pytest.approx(6000.0)
    assert panel.at["D1", "act_at_m"] == pytest.approx(1000.0)


# -------------------------------------------------------------- the identity

def test_the_log_ratio_is_the_ratio_of_the_two_stored_columns(loaded):
    m = _build(loaded, dry_run=True)
    assert m.at["ADDR-A", "activity_prior_12m"] == pytest.approx(6000.0)
    assert m.at["ADDR-A", "activity_12m"] == pytest.approx(12000.0)
    assert m.at["ADDR-A", "bike_growth_12m"] == pytest.approx(G_A)
    assert m.at["ADDR-B", "bike_growth_12m"] == pytest.approx(G_B)
    # ...and it holds for every row with a value, which is what check_identity
    # asserts on the frame before it is written.
    v = m[m["bike_growth_12m"].notna()]
    want = ((v["activity_12m"] + 1).apply(math.log)
            - (v["activity_prior_12m"] + 1).apply(math.log))
    assert (v["bike_growth_12m"] - want).abs().max() < 1e-12


def test_rel_is_the_growth_minus_one_system_wide_scalar(loaded):
    panel = bg.station_panel(loaded, M)
    system = bg.system_growth(panel)
    # D1 + D2 are the whole balanced set: 18,000 against 18,000.
    assert system == pytest.approx(0.0)
    m = _build(loaded, dry_run=True)
    v = m[m["bike_growth_12m"].notna()]
    assert ((v["bike_growth_12m_rel"]
             - (v["bike_growth_12m"] - system)).abs().max()) < 1e-12


def test_rel_sums_to_zero_over_the_system(mirror):
    """The panel's two addresses cover the system's two balanced docks exactly
    once, and both docks doubled. THAT is the condition: the system term is the
    log of a trip-weighted aggregate while the address terms are per-address
    logs, so they cancel only when the address panel replicates the system.

    The residual is the log1p offset — O(1/activity) — and nothing else.
    """
    meas, _ = bg.build_growth(mirror, M, ["BK"], dry_run=True)
    system = bg.system_growth(bg.station_panel(mirror, M))
    assert system == pytest.approx(math.log(2), abs=1e-3)     # non-trivially non-zero
    v = meas[meas["bike_growth_12m_rel"].notna()]
    assert len(v) == 2
    assert abs(float(v["bike_growth_12m_rel"].sum())) < 1e-3
    assert abs(float(v["bike_growth_12m_rel"].sum())) > 0     # the log1p residual


# ------------------------------------------------------ NULL, never zero

def test_below_the_balanced_share_floor_the_feature_is_null_never_zero(loaded):
    m = _build(loaded, dry_run=True)
    assert m.at["ADDR-C", "balanced_share"] < bg.BALANCED_SHARE_FLOOR
    for col in bg.VALUE_COLUMNS:
        assert pd.isna(m.at["ADDR-C", col]), f"{col} is not NULL under the floor"
    # The REASON is stored beside the NULL: a NULL whose reason is not recorded
    # is a hole, and these three columns are what a reader discounts by.
    assert m.at["ADDR-C", "n_docks_balanced"] == 1
    assert m.at["ADDR-C", "docks_added_24m"] == 1
    assert m.at["ADDR-C", "balanced_share"] == pytest.approx(0.25)


def test_an_address_with_no_balanced_dock_is_null_never_zero(loaded):
    m = _build(loaded, dry_run=True)
    assert m.at["ADDR-D", "n_docks_balanced"] == 0
    assert m.at["ADDR-D", "docks_added_24m"] == 0
    assert pd.isna(m.at["ADDR-D", "balanced_share"])
    for col in bg.VALUE_COLUMNS:
        assert pd.isna(m.at["ADDR-D", col])


def test_every_address_gets_a_row_including_the_street_frame(loaded):
    """Owner rule 2026-09-13: no eligibility gate. An address with nothing
    comparable nearby gets a ROW with NULLs, so "measured, nothing to compare"
    and "never computed" stay different facts.

    2026-09-16 (owner ruling 4) extended that to D84's street frame, which had
    been excluded on the grounds that it was not the frame the cards read. It
    was the ONLY frame for which "never computed" was being stored as an
    absence, and every join to it being LEFT, nothing could tell.
    """
    loaded.execute("INSERT INTO analysis.address (address_id, borough, frame) "
                   "VALUES ('ADDR-STREET', 'BK', 'street')")
    # phase 1 swept it: one dock in reach, exactly as ADDR-A has.
    loaded.execute(
        "INSERT INTO analysis.address_bike_station (address_id, borough, "
        "station_id, dist_m, radius_m, graph_version, run_at) "
        "VALUES ('ADDR-STREET', 'BK', 'D1', 120.0, 400.0, 'test', now())")
    m = _build(loaded, dry_run=True)
    assert set(m.index) == set(REACH) | {"ADDR-STREET"}
    assert math.isclose(m.loc["ADDR-STREET", "bike_growth_12m"], G_A, rel_tol=1e-9)


def test_an_unswept_street_frame_is_refused_rather_than_stored_as_no_dock(loaded):
    """The silent zero the widening could create. This module never touches the
    walk graph -- the dock geometry is phase 1's analysis.address_bike_station --
    so a frame in the universe but absent from that table writes well-formed
    rows that all read "no balanced dock". That is a fact about the pipeline,
    indistinguishable downstream from a real dock desert."""
    loaded.execute("INSERT INTO analysis.address (address_id, borough, frame) "
                   "VALUES ('ADDR-STREET', 'BK', 'street')")
    with pytest.raises(RuntimeError, match="ZERO rows in"):
        _build(loaded, dry_run=True)
    # ...and it can be stored deliberately, never by accident.
    m = _build(loaded, dry_run=True, allow_unswept_frame=True)
    assert m.loc["ADDR-STREET", "n_docks_balanced"] == 0
    assert m.loc["ADDR-STREET", "bike_growth_12m"] is None or pd.isna(
        m.loc["ADDR-STREET", "bike_growth_12m"])


def test_a_part_null_row_is_refused(loaded):
    """A row with an activity but no growth would let a downstream join read a
    growth with no activity behind it. check_identity raises on it."""
    meas, _ = bg.build_growth(loaded, M, ["BK"], dry_run=True)
    meas.loc[meas["address_id"] == "ADDR-A", "bike_growth_12m"] = None
    with pytest.raises(RuntimeError, match="part-NULL"):
        bg.check_identity(meas, 0.0)


# ---------------------------------------------- the two series and the write

def test_the_member_and_all_rider_series_differ_and_coexist(loaded):
    """D1's casual half vanishes between the windows, so its member traffic
    doubles while its all-rider traffic is flat. The robustness series must show
    that, and the two must sit in one table under member_only without pooling."""
    bg.build_growth(loaded, M, ["BK"], member_only=True)
    bg.build_growth(loaded, M, ["BK"], member_only=False)
    got = dict(loaded.execute(
        "SELECT member_only, bike_growth_12m FROM analysis.address_bike_growth "
        "WHERE address_id = 'ADDR-A' AND asof_month = ?", [M]).fetchall())
    assert got[True] == pytest.approx(G_A)
    assert got[False] == pytest.approx(0.0)           # 12,000 against 12,000
    assert loaded.execute(
        "SELECT count(*) FROM analysis.address_bike_growth "
        "WHERE address_id = 'ADDR-A'").fetchone()[0] == 2


def test_asof_month_and_member_only_are_the_unit_of_idempotence(loaded):
    """Two vintages must coexist — if 2023-01 and 2025-01 disagree in sign the
    feature fails (owner ruling R1), which is impossible if one rewrites the
    other. Rebuilding one must also not duplicate it."""
    earlier = bg.add_months(M, -1)
    # The second vintage's prior window reaches one month further back, and the
    # panel has to hold it — that refusal is its own test above.
    for sid in ("D1", "D2"):
        _station_month(loaded, sid, bg.add_months(P_FIRST, -1), 500, 0)
        loaded.execute("UPDATE staging.citibike_station SET first_month = ? "
                       "WHERE station_id = ?",
                       [bg.add_months(P_FIRST, -1), sid])
    bg.build_growth(loaded, M, ["BK"])
    bg.build_growth(loaded, earlier, ["BK"])
    bg.build_growth(loaded, M, ["BK"], member_only=False)
    bg.build_growth(loaded, M, ["BK"], re_sweep=True)          # rebuild one

    rows = dict(loaded.execute(
        "SELECT (asof_month, member_only), count(*) "
        "FROM analysis.address_bike_growth GROUP BY 1").fetchall())
    assert len(rows) == 3
    assert set(rows.values()) == {len(REACH)}                  # no duplication
    assert loaded.execute(
        "SELECT count(*) FROM analysis.address_bike_growth WHERE asof_month = ?",
        [earlier]).fetchone()[0] == len(REACH)


def test_a_stored_vintage_is_left_alone_without_re_sweep(loaded):
    bg.build_growth(loaded, M, ["BK"])
    stamped = loaded.execute(
        "SELECT max(run_at) FROM analysis.address_bike_growth").fetchone()[0]
    _, report = bg.build_growth(loaded, M, ["BK"])
    assert "skipped" in report["_written"]
    assert loaded.execute(
        "SELECT max(run_at) FROM analysis.address_bike_growth").fetchone()[0] \
        == stamped
    _, report = bg.build_growth(loaded, M, ["BK"], re_sweep=True)
    assert report["_written"]["rows_written"] == len(REACH)


def test_a_scoped_rebuild_does_not_wipe_the_other_borough(loaded):
    loaded.execute("INSERT INTO analysis.address (address_id, borough, frame) "
                   "VALUES ('ADDR-MN', 'MN', 'lot')")
    loaded.execute(
        "INSERT INTO analysis.address_bike_station (address_id, borough, "
        "station_id, dist_m) VALUES ('ADDR-MN', 'MN', 'D1', 100.0)")
    bg.build_growth(loaded, M, ["MN"])
    bg.build_growth(loaded, M, ["BK"])
    boroughs = dict(loaded.execute(
        "SELECT borough, count(*) FROM analysis.address_bike_growth "
        "GROUP BY 1").fetchall())
    assert boroughs == {"MN": 1, "BK": len(REACH)}


def test_the_validation_query_reports_no_impossible_zero_and_no_part_null(loaded):
    bg.build_growth(loaded, M, ["BK"])
    v = loaded.execute(bg.VALIDATION_SQL).fetchdf()
    assert int(v["impossible_zero"].sum()) == 0
    assert int(v["part_null"].sum()) == 0
    assert float(v["max_balanced_share"].max()) <= 1 + 1e-12
    assert float(v["min_balanced_share"].min()) >= 0


def test_reconcile_rebuilds_the_stored_vintage_from_the_panel(loaded):
    bg.build_growth(loaded, M, ["BK"])
    r = bg.reconcile(loaded, "ADDR-A", M)
    assert r["n_docks_balanced"] == 1
    assert r["bike_growth_12m"] == pytest.approx(G_A)
    assert bg.reconcile(loaded, "ADDR-D", M)["censored"] is True
    # A stored number that no longer follows from the panel must RAISE, or a
    # changed window can move the columns without anything saying so.
    loaded.execute("UPDATE analysis.address_bike_growth SET activity_12m = 99 "
                   "WHERE address_id = 'ADDR-A' AND member_only")
    with pytest.raises(RuntimeError, match="does not reproduce"):
        bg.reconcile(loaded, "ADDR-A", M)


def test_the_validation_rollup_row_renders_rather_than_raising(loaded):
    """The ROLLUP total rows come back with NULL grouping keys, which pandas
    hands over as NaT — and `f"{NaT:%Y-%m}"` RAISES rather than printing
    something. That table is printed only on a real write, so the crash would
    first appear in production, on the run whose output matters most.
    """
    from loci.cli import _growth_cell

    bg.build_growth(loaded, M, ["BK"])
    bg.build_growth(loaded, M, ["BK"], member_only=False)
    df = loaded.execute(bg.VALIDATION_SQL).fetchdf()
    assert df["asof_month"].isna().any(), "no total row to render"
    rendered = [[_growth_cell(c, r[c], blank="ALL") for c in df.columns]
                for r in df.to_dict("records")]
    assert all(isinstance(cell, str) for row in rendered for cell in row)
    assert any("ALL" in row for row in rendered)
    # The series is spelled out either way: "TRUE" is not the name of a series.
    flat = {cell for row in rendered for cell in row}
    assert {"member", "all-rider"} <= flat
