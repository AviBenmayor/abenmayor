"""Frozen rewind snapshots (model/supply_snapshot.py, sql/049).

THE ONE INVARIANT: a snapshot's per-category counts equal what
`validation.retrodiction.supply_as_of` counts for the same t0 -- one
leakage-safe rule, materialised, not re-derived. Plus: the censored share is
stamped, closure is flagged and never filtered, a rebuild replaces only its
own t0, and an empty t0 set raises rather than writing a city with no shops.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from loci import db as locidb
from loci.model import supply_snapshot as ss
from loci.validation import retrodiction as rd

LON, LAT = -73.95, 40.68


@pytest.fixture()
def con(monkeypatch):
    c = locidb.connect(":memory:")
    locidb.init_schema(c)
    # analysis.poi_supply is a view over staging.poi + poi_dedup; the rule
    # reads only (poi_id, in_principled), so a two-column stand-in is the
    # honest fixture -- the same shape tests/test_forecast.py uses.
    c.execute("DROP VIEW analysis.poi_supply_status")
    c.execute("DROP VIEW analysis.poi_colocation")
    c.execute("DROP VIEW analysis.poi_supply")
    c.execute("CREATE TABLE analysis.poi_supply (poi_id VARCHAR, in_principled BOOLEAN)")
    monkeypatch.setattr("loci.score.supply.supply_hash", lambda con, *a, **k: "testhash")
    return c


def add_poi(con, key, cat, kind, date, *, principled=True, borough="BK", closed=None,
            lon=LON, lat=LAT):
    con.execute("""
        INSERT INTO analysis.poi_presence (location_key, category, name_key, display_name,
            lon, lat, borough, first_seen_month, last_seen_month, first_seen_kind,
            first_seen_src_date, n_months_seen, poi_id_latest, ledger_started_month,
            last_snapshot_at, closed_on)
        VALUES (?, ?, ?, ?, ?, ?, ?, '2026-08', '2026-09', ?, ?, 2, ?, '2026-08', now(), ?)""",
                [key, cat, key, key, lon, lat, borough, kind, date, f"poi:{key}", closed])
    con.execute("INSERT INTO analysis.poi_supply VALUES (?, ?)", [f"poi:{key}", principled])


def add_address(con, aid, bbl, lon=LON, lat=LAT):
    con.execute("""
        INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, frame, present_count,
            eligible, n_missing, reach_source, reach_hash, graph_version, run_at)
        VALUES (?, ?, ?, ?, 'BK', 'lot', 0, TRUE, 0, 'tiers', 'h', 'g', now())""",
                [aid, bbl, lon, lat])


def _seed(con):
    add_poi(con, "a", "bar", "source_date", dt.date(2015, 5, 1))          # in every t0
    add_poi(con, "b", "bar", "source_date", dt.date(2019, 5, 1))          # in 2020+
    add_poi(con, "c", "grocery", "backfill_censored", None)               # censored: always
    add_poi(con, "d", "grocery", "source_date", dt.date(2010, 1, 1),
            closed=dt.date(2014, 1, 1))                                   # closed before t0
    add_poi(con, "e", "bar", "source_date", dt.date(2015, 1, 1), principled=False)
    add_poi(con, "f", "bar", "source_date", dt.date(2015, 1, 1), borough="QN")
    add_address(con, "A1", "3000010001")


def test_snapshot_counts_equal_supply_as_of_for_the_same_t0(con):
    _seed(con)
    t0 = dt.date(2016, 1, 1)
    ss.build(con, t0)
    pts = pd.DataFrame({"point_id": ["p"], "lon": [LON], "lat": [LAT]})
    live = rd.supply_as_of(con, pts, t0).set_index("category")["supply"].to_dict()
    snap = dict(con.execute("SELECT category, count(*) FROM analysis.supply_snapshot "
                            "WHERE t0 = ? GROUP BY 1", [t0]).fetchall())
    assert snap == live == {"bar": 1, "grocery": 2}
    assert ss.validate(con, t0) == []


def test_the_rule_is_leakage_safe_and_counts_the_censored(con):
    _seed(con)
    ss.build(con, dt.date(2016, 1, 1))
    ss.build(con, dt.date(2020, 1, 1))
    keys = {t0: set(r[0] for r in con.execute(
        "SELECT location_key FROM analysis.supply_snapshot WHERE t0 = ?", [t0]).fetchall())
        for t0 in (dt.date(2016, 1, 1), dt.date(2020, 1, 1))}
    assert keys[dt.date(2016, 1, 1)] == {"a", "c", "d"}       # b is AFTER 2016; e, f out
    assert keys[dt.date(2020, 1, 1)] == {"a", "b", "c", "d"}


def test_census_stamps_the_censored_share_and_flags_closure(con):
    _seed(con)
    c = ss.build(con, dt.date(2016, 1, 1))["2016-01-01"]
    assert c["ALL"]["n"] == 3 and c["ALL"]["n_censored"] == 1
    assert c["ALL"]["censored_share"] == pytest.approx(1 / 3)
    assert c["ALL"]["n_closed_before_t0"] == 1
    assert c["grocery"]["n"] == 2 and c["grocery"]["censored_share"] == pytest.approx(0.5)
    status = dict(con.execute("SELECT location_key, status_at_t0 FROM analysis.supply_snapshot"
                              ).fetchall())
    assert status["d"] == "closed" and status["a"] == "open"


def test_bbl_is_the_nearest_lot_within_30m_and_hash_is_stamped(con):
    _seed(con)
    ss.build(con, dt.date(2016, 1, 1))
    rows = con.execute("SELECT location_key, bbl, supply_hash FROM analysis.supply_snapshot"
                       ).fetchall()
    assert all(r[1] == "3000010001" and r[2] == "testhash" for r in rows)


def test_rebuild_replaces_only_its_own_t0(con):
    _seed(con)
    ss.build(con, dt.date(2016, 1, 1))
    ss.build(con, dt.date(2020, 1, 1))
    ss.build(con, dt.date(2016, 1, 1))
    n = dict(con.execute("SELECT t0, count(*) FROM analysis.supply_snapshot GROUP BY 1").fetchall())
    assert n == {dt.date(2016, 1, 1): 3, dt.date(2020, 1, 1): 4}


def test_empty_t0_set_raises(con):
    add_poi(con, "b", "bar", "source_date", dt.date(2019, 5, 1))
    with pytest.raises(RuntimeError, match="EMPTY"):
        ss.build(con, dt.date(2016, 1, 1))


def test_default_t0s_are_the_ten_january_firsts():
    assert ss.DEFAULT_T0S[0] == dt.date(2016, 1, 1)
    assert ss.DEFAULT_T0S[-1] == dt.date(2025, 1, 1)
    assert len(ss.DEFAULT_T0S) == 10 and all(d.month == 1 and d.day == 1 for d in ss.DEFAULT_T0S)
