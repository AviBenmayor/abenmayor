"""Day type x daypart subway entries, and the conservation that keeps the
daypart split honest (owner request 2026-09-13, follow-up to GTM-146).

The Dijkstra distance maths is already covered by tests/test_supply_ratio.py
and tests/test_address_access.py. What is tested here is what is NEW: the
daypart partition, the day-type mapping, the divisors, the two conservation
checks, the even split carried through to entrance grain, the pair sweep, and
the refusal to write a profile beside a column that is not there.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.sparse import csr_matrix

from loci.model.address_transit_profile import (
    PROFILE_ADDRESS_COLUMNS,
    _guard,
    am_pm_share_frame,
    catchment_pairs,
    entrance_weights,
    profile_long,
)
from loci.sources.cities.nyc import mta_ridership as mr

# --------------------------------------------------------- the boundaries

def test_dayparts_partition_the_whole_day_with_no_gap_or_overlap():
    """The conservation check is only meaningful if the five dayparts cover
    00:00-24:00 exactly once. A gap would silently delete riders; an overlap
    would double-count them."""
    hours = [mr.daypart_of(h) for h in range(24)]
    assert len(hours) == 24
    seen: dict[str, int] = {}
    for h in hours:
        seen[h] = seen.get(h, 0) + 1
    assert set(seen) == set(mr.DAYPART_NAMES)
    assert sum(seen.values()) == 24
    # contiguous and half-open, in order
    edges = [(a, b) for _, a, b in mr.DAYPARTS]
    assert edges[0][0] == 0 and edges[-1][1] == 24
    assert all(b == a2 for (_, b), (a2, _) in zip(edges, edges[1:]))


def test_every_dot_count_window_falls_strictly_inside_one_daypart():
    """This containment is the ONLY reason the daypart edges are where they
    are: `loci validate-pedestrian` compares a hand-counted window to a
    measured daypart, and a window straddling two dayparts could not be
    compared to either without interpolating. If DAYPARTS is ever edited, this
    is the test that should stop it."""
    for win, (start, end) in mr.DOT_WINDOWS.items():
        part = mr.DOT_WINDOW_DAYPART[win]
        lo, hi = next((a, b) for n, a, b in mr.DAYPARTS if n == part)
        assert lo <= start < end <= hi, f"DOT {win} {start}-{end} escapes {part} {lo}-{hi}"
        # and every hour of the window really maps there
        assert {mr.daypart_of(h) for h in range(start, end)} == {part}


def test_day_type_mapping_matches_the_feeds_dow_encoding():
    """Socrata date_extract_dow is 0=Sunday..6=Saturday -- verified on the live
    feed against August 2026's calendar. The incumbent weekday pull relies on
    it (`between 1 and 5`), so getting it backwards would put Sundays in the
    weekday mean."""
    assert mr.day_type_of(0) == "sunday"
    assert mr.day_type_of(6) == "saturday"
    assert [mr.day_type_of(d) for d in range(1, 6)] == ["weekday"] * 5
    with pytest.raises(ValueError):
        mr.day_type_of(7)
    with pytest.raises(ValueError):
        mr.daypart_of(24)


# --------------------------------------------------- the aggregation itself

def _profile_rows():
    """Two complexes, hand-built so every cell's expected value is arithmetic
    a reader can check: complex A puts 10 riders in every one of the 168
    (dow, hour) cells; complex B puts riders only at 08:00 on weekdays."""
    rows = []
    for dow in range(7):
        for hh in range(24):
            rows.append({"station_complex_id": "A", "dow": str(dow), "hh": str(hh),
                         "riders": "10"})
    for dow in range(1, 6):
        rows.append({"station_complex_id": "B", "dow": str(dow), "hh": "8",
                     "riders": "100"})
    return rows


def test_profile_entries_divides_by_the_right_day_count(monkeypatch):
    """The divisor is the number of distinct DATES OF THAT DAY TYPE, so the
    output is per average weekday / per average Saturday, not a sum that grows
    with the window."""
    # a 4-week month: 20 weekdays, 4 saturdays, 4 sundays
    monkeypatch.setattr(mr, "fetch_month_profile",
                        lambda y, m, refresh=False: _profile_rows())
    monkeypatch.setattr(mr, "fetch_month_daycounts",
                        lambda y, m, refresh=False: {0: 4, 1: 4, 2: 4, 3: 4, 4: 4,
                                                     5: 4, 6: 4})
    monkeypatch.setattr(mr, "weekday_dates", lambda *a, **k: [None] * 20)

    prof, rep = mr.profile_entries([(2026, 8)])
    assert rep["n_days_by_type"] == {"weekday": 20, "saturday": 4, "sunday": 4}
    # A: 10 riders x 5 weekdays x 4 hours in am_peak = 200 over 20 weekday dates
    assert prof["A"][("weekday", "am_peak")] == pytest.approx(10 * 5 * 4 / 20)
    # A: Saturday early is 6 hours x 10 over 4 saturdays
    assert prof["A"][("saturday", "early")] == pytest.approx(10 * 6 / 4)
    # B exists only at 08:00 on weekdays -> every other cell is a TRUE ZERO and
    # is materialised, not dropped, so a sum over dayparts is the all-day total
    assert set(prof["B"]) == {(d, p) for d in mr.DAY_TYPES for p in mr.DAYPART_NAMES}
    assert prof["B"][("weekday", "am_peak")] == pytest.approx(100 * 5 / 20)
    assert prof["B"][("saturday", "midday")] == 0.0


def test_profile_entries_raises_when_the_feed_is_short_a_weekday(monkeypatch):
    """A month whose feed carries 19 of 20 weekdays would inflate every per-day
    mean by 5%. That is a silent scale error, so it raises."""
    monkeypatch.setattr(mr, "fetch_month_profile",
                        lambda y, m, refresh=False: _profile_rows())
    monkeypatch.setattr(mr, "fetch_month_daycounts",
                        lambda y, m, refresh=False: {0: 4, 1: 3, 2: 4, 3: 4, 4: 4,
                                                     5: 4, 6: 4})
    monkeypatch.setattr(mr, "weekday_dates", lambda *a, **k: [None] * 20)
    with pytest.raises(RuntimeError, match="non-holiday weekday"):
        mr.profile_entries([(2026, 8)])


# ------------------------------------------------------------ conservation

def _flat_profile(weekday_by_part: dict[str, float]) -> dict:
    cell = {(d, p): 0.0 for d in mr.DAY_TYPES for p in mr.DAYPART_NAMES}
    for p, v in weekday_by_part.items():
        cell[("weekday", p)] = v
    return {"A": cell}


def test_check_conservation_accepts_an_exact_split():
    prof = _flat_profile({"early": 10.0, "am_peak": 400.0, "midday": 200.0,
                          "pm_peak": 300.0, "evening": 90.0})
    rep = mr.check_conservation(prof, {"A": {"entries_per_weekday": 1000.0}})
    assert rep["worst_relative_error"] == pytest.approx(0.0)
    assert rep["weekday_total_from_profile"] == pytest.approx(1000.0)


def test_check_conservation_raises_when_a_daypart_is_dropping_hours():
    """The failure this is really guarding: an edit to DAYPARTS that leaves a
    gap. The dayparts would then sum to less than the day and every
    transit_entries_400m built from them would be quietly low."""
    prof = _flat_profile({"early": 10.0, "am_peak": 400.0, "midday": 200.0,
                          "pm_peak": 300.0, "evening": 0.0})
    with pytest.raises(RuntimeError, match="conservation FAILED"):
        mr.check_conservation(prof, {"A": {"entries_per_weekday": 1000.0}})


def test_check_conservation_raises_when_the_two_pulls_see_different_complexes():
    prof = _flat_profile({"early": 0.0, "am_peak": 0.0, "midday": 0.0,
                          "pm_peak": 0.0, "evening": 1000.0})
    with pytest.raises(RuntimeError, match="disagree on WHICH"):
        mr.check_conservation(prof, {"A": {"entries_per_weekday": 1000.0},
                                     "Z": {"entries_per_weekday": 5.0}})


def test_am_pm_share_is_null_not_zero_when_there_is_no_evening_peak():
    cell = {(d, p): 0.0 for d in mr.DAY_TYPES for p in mr.DAYPART_NAMES}
    cell[("weekday", "am_peak")] = 500.0
    assert mr.am_pm_share(cell) is None            # pm_peak == 0 -> no ratio
    cell[("weekday", "pm_peak")] = 250.0
    assert mr.am_pm_share(cell) == pytest.approx(2.0)      # residential


# --------------------------------------------------- the entrance identity

def _entries():
    return {"A": {"entries_per_weekday": 1000.0, "name": "A", "lon": -73.9, "lat": 40.7},
            "B": {"entries_per_weekday": 500.0, "name": "B", "lon": -73.8, "lat": 40.6}}


def _entrances():
    return [
        {"complex_id": "A", "entry_allowed": "YES", "entrance_longitude": "-73.901",
         "entrance_latitude": "40.701"},
        {"complex_id": "A", "entry_allowed": "YES", "entrance_longitude": "-73.899",
         "entrance_latitude": "40.699"},
        {"complex_id": "A", "entry_allowed": "NO", "entrance_longitude": "-73.905",
         "entrance_latitude": "40.705"},
        {"complex_id": "B", "entry_allowed": "YES", "entrance_longitude": "-73.801",
         "entrance_latitude": "40.601"},
    ]


def test_entrance_table_matches_entry_points_door_for_door():
    """The persisted entrance table and the weight-point build must never
    disagree about which doors exist -- they share `entrances_by_complex`, and
    this is the test that says so. A divergence would mean the address sweep
    walked to doors the weights were never put on."""
    pts, prep = mr.entry_points(_entries(), _entrances())
    rows, rrep = mr.entrance_table(_entries(), _entrances())
    assert len(rows) == prep["weight_points"] == 3
    assert rrep["complexes_without_entrances"] == prep["complexes_without_entrances"]
    assert sorted((r["lon"], r["lat"]) for r in rows) == sorted(p[1:3] for p in pts)
    # n_doors is the even-split DENOMINATOR, carried beside the row instead of
    # multiplied into it, so the window and the split can change later.
    assert {r["n_doors"] for r in rows if r["complex_id"] == "A"} == {2}


def test_entrance_id_is_deterministic_and_names_the_fallback():
    assert mr.entrance_id("617", -73.978879, 40.683905) == "617@-73.978879,40.683905"
    assert mr.entrance_id("617", None, None) == "complex:617"


def test_entrance_weights_apply_the_even_split_and_conserve_the_complex():
    """Summing the fifteen cells over a complex's doors must return the
    complex's own grid -- no rider created, none lost."""
    prof = {"A": {(d, p): 0.0 for d in mr.DAY_TYPES for p in mr.DAYPART_NAMES}}
    prof["A"][("weekday", "am_peak")] = 900.0
    rows, _ = mr.entrance_table({"A": {"entries_per_weekday": 900.0, "lon": 0.0,
                                       "lat": 0.0, "name": "A"}}, _entrances()[:3])
    w = entrance_weights(prof, rows)
    got = w[(w.day_type == "weekday") & (w.daypart == "am_peak")]["entries_per_day"].sum()
    assert got == pytest.approx(900.0)
    assert set(w["entries_per_day"][w.daypart == "am_peak"][w.day_type == "weekday"]) \
        == {450.0}


def test_entrance_weights_raise_on_a_complex_with_no_profile():
    rows, _ = mr.entrance_table(_entries(), _entrances())
    with pytest.raises(RuntimeError, match="no ridership profile"):
        entrance_weights({"A": {(d, p): 0.0 for d in mr.DAY_TYPES
                                for p in mr.DAYPART_NAMES}}, rows)


# ------------------------------------------------------------- the sweep

def _line_graph(n: int, step: float):
    """A path graph 0-1-...-(n-1) with every edge `step` metres. Every distance
    is known by construction, so the pair sweep is checked against arithmetic
    rather than against another implementation."""
    r, c, v = [], [], []
    for i in range(n - 1):
        r += [i, i + 1]
        c += [i + 1, i]
        v += [step, step]
    return csr_matrix((v, (r, c)), shape=(n, n))


def test_catchment_pairs_returns_exactly_the_points_inside_the_radius():
    A = _line_graph(11, 100.0)                       # nodes 0..10, 100 m apart
    targets = np.array([0, 5, 10], dtype=np.int64)   # three entrances
    qi, ti, d = catchment_pairs(A, np.array([5]), targets, radius_m=400.0, batch=8)
    assert sorted(ti.tolist()) == [1]                # only the one at node 5
    assert d.tolist() == [0.0]                       # self, distance zero
    qi, ti, d = catchment_pairs(A, np.array([5]), targets, radius_m=500.0, batch=8)
    assert sorted(ti.tolist()) == [0, 1, 2]
    assert sorted(np.round(d, 6).tolist()) == [0.0, 500.0, 500.0]


def test_catchment_pairs_keeps_two_entrances_that_share_a_node():
    """Two doors snapped to one graph node are TWO rows, exactly as
    node_weights would have added both their weights onto that node. Collapsing
    them would halve a complex that happens to have two stairs on one corner."""
    A = _line_graph(5, 100.0)
    qi, ti, d = catchment_pairs(A, np.array([0]), np.array([2, 2]), radius_m=400.0)
    assert sorted(ti.tolist()) == [0, 1]
    assert d.tolist() == [200.0, 200.0]


def test_catchment_pairs_batching_does_not_shift_the_query_index():
    """The per-batch offset is easy to get wrong and would silently attribute
    one address's entrances to another."""
    A = _line_graph(9, 100.0)
    q = np.array([0, 4, 8])
    for batch in (1, 2, 3, 8):
        qi, ti, d = catchment_pairs(A, q, np.array([4]), radius_m=400.0, batch=batch)
        assert sorted(qi.tolist()) == [0, 1, 2]
        assert sorted(np.round(d, 6).tolist()) == [0.0, 400.0, 400.0]


# ---------------------------------------------------------- the long form

def test_profile_long_credits_a_fraction_of_a_complex_per_reachable_door():
    """An address that can reach 1 of a complex's 2 doors gets half of it; an
    address that can reach both gets all of it. That is the even split's own
    arithmetic, and it is the bias section 4 of the contrarian memo names --
    not a double count."""
    prof = {"A": {(d, p): 0.0 for d in mr.DAY_TYPES for p in mr.DAYPART_NAMES}}
    prof["A"][("weekday", "pm_peak")] = 1000.0
    ents = [{"entrance_id": "A@1", "complex_id": "A", "lon": 0.0, "lat": 0.0, "n_doors": 2},
            {"entrance_id": "A@2", "complex_id": "A", "lon": 0.0, "lat": 0.0, "n_doors": 2}]
    reach = pd.DataFrame({"address_id": ["near", "far"], "entrance_id": ["A@1", "A@1"]})
    reach = pd.concat([reach.iloc[[0]],
                       pd.DataFrame({"address_id": ["near"], "entrance_id": ["A@2"]}),
                       reach.iloc[[1]]], ignore_index=True)
    long_df = profile_long(reach, entrance_weights(prof, ents))
    got = long_df[(long_df.day_type == "weekday") & (long_df.daypart == "pm_peak")]
    got = dict(zip(got["address_id"], got["transit_entries_400m"]))
    assert got["near"] == pytest.approx(1000.0)
    assert got["far"] == pytest.approx(500.0)


def test_am_pm_share_frame_is_null_where_there_is_no_pm_peak():
    long_df = pd.DataFrame({
        "address_id": ["r", "r", "j", "j", "n"],
        "day_type": ["weekday"] * 5,
        "daypart": ["am_peak", "pm_peak", "am_peak", "pm_peak", "am_peak"],
        "transit_entries_400m": [600.0, 300.0, 100.0, 400.0, 50.0],
    })
    out = am_pm_share_frame(long_df).set_index("address_id")
    assert out.loc["r", "transit_am_pm_share_400m"] == pytest.approx(2.0)   # residential
    assert out.loc["j", "transit_am_pm_share_400m"] == pytest.approx(0.25)  # job centre
    assert np.isnan(out.loc["n", "transit_am_pm_share_400m"])               # no ratio


# ------------------------------------------------------- the column contract

def test_profile_columns_are_disjoint_from_access_and_every_sibling():
    """Deliberately NOT folded into ACCESS_COLUMNS: `loci address-access`
    RESETS that list to NULL and does not compute the share, so sharing the
    list would blank the share on every access re-run."""
    from loci.model.address_access import ACCESS_COLUMNS

    assert set(PROFILE_ADDRESS_COLUMNS) & set(ACCESS_COLUMNS) == set()
    _guard(PROFILE_ADDRESS_COLUMNS)
    with pytest.raises(RuntimeError, match="clobber"):
        _guard([*PROFILE_ADDRESS_COLUMNS, "transit_entries_400m"])
    with pytest.raises(RuntimeError, match="clobber"):
        _guard([*PROFILE_ADDRESS_COLUMNS, "gap_score"])


def test_sql_migration_declares_the_profile_columns_and_the_wide_view():
    import pathlib

    sql = (pathlib.Path(__file__).resolve().parents[1] / "src" / "loci" / "sql"
           / "017_address_transit_profile.sql").read_text()
    alters = [ln.strip() for ln in sql.splitlines()
              if ln.strip().upper().startswith("ALTER TABLE")]
    declared = {ln.split("ADD COLUMN IF NOT EXISTS")[1].split()[0] for ln in alters}
    assert declared == set(PROFILE_ADDRESS_COLUMNS)
    assert "CREATE TABLE IF NOT EXISTS analysis.address_transit_profile" in sql
    assert "CREATE TABLE IF NOT EXISTS analysis.address_entrance" in sql
    # the PIVOT is a VIEW, never a table (D61)
    assert "CREATE OR REPLACE VIEW analysis.address_transit_profile_wide" in sql
    assert "CREATE TABLE IF NOT EXISTS analysis.address_transit_profile_wide" not in sql


def test_migration_and_wide_view_run_on_an_empty_database():
    """The wide view must build on a fresh warehouse, and must return every
    address with zeros rather than dropping the ones with no station (D75: no
    eligibility gate anywhere)."""
    import pathlib

    import duckdb

    sql = (pathlib.Path(__file__).resolve().parents[1] / "src" / "loci" / "sql"
           / "017_address_transit_profile.sql").read_text()
    con = duckdb.connect()
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.address(address_id VARCHAR, borough VARCHAR, "
                "transit_entries_400m DOUBLE)")
    con.execute(sql)
    con.execute(sql)                                   # idempotent
    con.execute("INSERT INTO analysis.address(address_id, borough, transit_entries_400m) "
                "VALUES ('with', 'BK', 100.0), ('without', 'BK', 0.0)")
    con.execute("INSERT INTO analysis.address_transit_profile VALUES "
                "('with','BK','weekday','am_peak',60.0,400,'w','entrances',now()), "
                "('with','BK','weekday','pm_peak',40.0,400,'w','entrances',now())")
    out = con.execute("SELECT address_id, weekday_all_day, weekday_am_peak, "
                      "weekday_evening, saturday_all_day "
                      "FROM analysis.address_transit_profile_wide ORDER BY 1").fetchall()
    assert out == [("with", 100.0, 60.0, 0.0, 0.0), ("without", 0.0, 0.0, 0.0, 0.0)]


def test_rebuild_check_refuses_a_borough_whose_access_columns_are_null():
    """The concurrency hazard, made into a test: `loci address-gaps`
    DELETE/INSERTs analysis.address and NULLs access_run_at. Writing a daypart
    profile beside a NULL transit_entries_400m is exactly the divergence the
    owner asked to prevent, so it raises and names the borough."""
    import duckdb

    from loci.model.address_transit_profile import check_rebuilds_the_daily_total

    con = duckdb.connect()
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.address(address_id VARCHAR, borough VARCHAR, "
                "transit_entries_400m DOUBLE, access_run_at TIMESTAMP)")
    con.execute("INSERT INTO analysis.address VALUES "
                "('b1','BK',100.0,now()), ('m1','MN',50.0,NULL)")
    long_df = pd.DataFrame({"address_id": ["b1"], "day_type": ["weekday"],
                            "daypart": ["am_peak"], "transit_entries_400m": [100.0]})
    with pytest.raises(RuntimeError, match=r"\['MN'\]"):
        check_rebuilds_the_daily_total(con, long_df, ["MN", "BK"])
    rep = check_rebuilds_the_daily_total(con, long_df, ["BK"])
    assert rep["worst_relative_error"] == pytest.approx(0.0)


def test_rebuild_check_raises_when_the_weekday_sum_drifts_from_the_column():
    import duckdb

    from loci.model.address_transit_profile import check_rebuilds_the_daily_total

    con = duckdb.connect()
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.address(address_id VARCHAR, borough VARCHAR, "
                "transit_entries_400m DOUBLE, access_run_at TIMESTAMP)")
    con.execute("INSERT INTO analysis.address VALUES ('b1','BK',100.0,now())")
    long_df = pd.DataFrame({"address_id": ["b1"], "day_type": ["weekday"],
                            "daypart": ["am_peak"], "transit_entries_400m": [90.0]})
    with pytest.raises(RuntimeError, match="does not reproduce"):
        check_rebuilds_the_daily_total(con, long_df, ["BK"])


def test_an_address_absent_from_the_profile_must_have_a_stored_zero():
    """The sparse table is not an eligibility gate: an address with no rows is
    an address with no station within 400 m, and its stored column must agree."""
    import duckdb

    from loci.model.address_transit_profile import check_rebuilds_the_daily_total

    con = duckdb.connect()
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.address(address_id VARCHAR, borough VARCHAR, "
                "transit_entries_400m DOUBLE, access_run_at TIMESTAMP)")
    con.execute("INSERT INTO analysis.address VALUES "
                "('b1','BK',100.0,now()), ('b2','BK',0.0,now())")
    long_df = pd.DataFrame({"address_id": ["b1"], "day_type": ["weekday"],
                            "daypart": ["am_peak"], "transit_entries_400m": [100.0]})
    rep = check_rebuilds_the_daily_total(con, long_df, ["BK"])
    assert rep["stored_zero_and_absent"] == 1
    assert rep["addresses_compared"] == 2


def test_on_street_counts_keeps_the_three_windows_separately():
    """Summing AM+MD+PM away was the only thing stopping the validation from
    asking "does the AM measure rank the AM count", which is the question the
    daypart split exists to answer."""
    from loci.validation.pedestrian_counts import on_street_counts

    rows = [{"loc": "1", "borough": "Brooklyn", "street_nam": "Broadway",
             "the_geom": {"type": "Point", "coordinates": [-73.9, 40.7]},
             "may26_am": "100", "may26_md": "200", "may26_pm": "300"}]
    pts, _ = on_street_counts(rows, 2026, 5)
    assert pts[0]["dot_am"] == 100.0
    assert pts[0]["dot_md"] == 200.0
    assert pts[0]["dot_pm"] == 300.0
    assert pts[0]["count"] == 600.0            # the incumbent column, unchanged


def test_a_persisted_reachable_set_is_refused_when_the_entrance_feed_moves(monkeypatch):
    """The persisted (address, entrance, dist) rows describe a SPECIFIC door
    set. If MTA moves or renames a door, the ids stop matching and the stored
    distances no longer describe the doors being weighted -- silently reusing
    them would put a complex's entries on a stair that is no longer there."""
    from loci.model import address_transit_profile as atp

    prof = {"A": {(d, p): 1.0 for d in mr.DAY_TYPES for p in mr.DAYPART_NAMES}}
    ents = [{"entrance_id": "A@new", "complex_id": "A", "lon": 0.0, "lat": 0.0,
             "n_doors": 1}]
    monkeypatch.setattr(mr, "build_profile",
                        lambda **kw: (prof, ents, {"window_start": "2026-06-01",
                                                   "window_end": "2026-08-31",
                                                   "snap": "entrances",
                                                   "conservation": {}}))
    stale = pd.DataFrame({"address_id": ["a"], "borough": ["BK"],
                          "entrance_id": ["A@old"], "complex_id": ["A"],
                          "dist_m": [120.0]})
    with pytest.raises(RuntimeError, match="not in the current entrance feed"):
        atp.build_transit_profile(object(), ["BK"], reachable=stale, dry_run=True)
