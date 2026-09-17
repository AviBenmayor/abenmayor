"""The SLA licence NON-RENEWAL label (model/licence_event.py, sql/047).

What is pinned:

(a) THE EVENT DEFINITION, both arms, on synthetic licences where every case
    of pre-registration v2 §1.2 is present by construction: no successor;
    same-name successor (renewal); different-name successor (transfer on
    sale); active (censored); expiry_future (dropped); sentinel creation
    date (dropped); BBL missing (unchecked -> NULL, never FALSE).
(b) THE WINDOW FLAGS agree with the baseline view and the address measure's
    numerator/denominator (one definition, three readers).
(c) THE CHECKS report numbers, never fit: p3_prime counts scored lots,
    event_counts applies the cohort rule, and the measure columns are guarded
    off everything the screen owns.
(d) NEVER A SILENT ZERO: an empty SLA panel raises.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from loci import db as locidb
from loci.model import licence_event as le

ASOF = dt.date(2026, 9, 17)
PULL = dt.date(2026, 9, 16)
ACTIVE, INACTIVE = le.SLA_SOURCES


def _con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _interval(con, nbr, *, source, category, bbl, issued, expires, name,
              end_kind, borough="BK", lon=-73.95, lat=40.68, cls="type 1 class 0340"):
    from loci.model.poi_presence import name_key_of
    status = "Active" if source == ACTIVE else "Inactive"
    interval_end = PULL if end_kind != "expiry_observed" else expires
    con.execute("""
        INSERT INTO analysis.licence_interval (
            licence_number, business_name_key, poi_name_key, business_name, bbl,
            match_method, borough, address, lon, lat, geom, business_category,
            licence_type, loci_category, category_confidence, licence_creation_date,
            expiration_date, status, status_date, interval_end, end_kind,
            days_observed, pulled_asof, source, provenance, ingested_at)
        VALUES (?, ?, ?, ?, ?, 'pluto_address', ?, '1 MAIN ST', ?, ?, ST_Point(?, ?),
                'Restaurant', ?, ?, 'high', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', now())
    """, [nbr, name.lower(), name_key_of(name), name, bbl, borough, lon, lat, lon, lat,
          cls, category, issued, expires, status,
          expires if end_kind == "expiry_observed" else None,
          interval_end, end_kind,
          (interval_end - issued).days if interval_end and issued else 0, PULL, source])


def _fixture(con):
    """Six licences at one BBL plus the edge cases."""
    i = dict(source=INACTIVE, category="restaurant", end_kind="expiry_observed")
    # 1. ended, no successor at all -> event under both arms
    _interval(con, "L1", bbl="3000010001", issued=dt.date(2018, 3, 1),
              expires=dt.date(2021, 2, 28), name="ALPHA DINER INC", **i)
    # 2. ended, same-name successor 30 d later -> ordinary renewal, no event
    _interval(con, "L2", bbl="3000010002", issued=dt.date(2017, 1, 1),
              expires=dt.date(2020, 1, 1), name="BETA GRILL LLC", **i)
    _interval(con, "L2s", bbl="3000010002", issued=dt.date(2020, 1, 31),
              expires=dt.date(2029, 1, 1), name="BETA GRILL CORP",
              source=ACTIVE, category="restaurant", end_kind="active_censored")
    # 3. ended, DIFFERENT-name successor 60 d BEFORE the expiry (transfer on
    #    sale) -> business event, no premises event
    _interval(con, "L3", bbl="3000010003", issued=dt.date(2016, 6, 1),
              expires=dt.date(2022, 6, 1), name="GAMMA TAVERN", **i)
    _interval(con, "L3s", bbl="3000010003", issued=dt.date(2022, 4, 2),
              expires=dt.date(2030, 1, 1), name="DELTA BISTRO",
              source=ACTIVE, category="bar", end_kind="active_censored")
    # 4. ended, successor at the BBL but 300 d later -> outside the window
    _interval(con, "L4", bbl="3000010004", issued=dt.date(2015, 1, 1),
              expires=dt.date(2019, 1, 1), name="EPSILON CAFE", **i)
    _interval(con, "L4s", bbl="3000010004", issued=dt.date(2019, 10, 28),
              expires=dt.date(2030, 1, 1), name="EPSILON CAFE",
              source=ACTIVE, category="restaurant", end_kind="active_censored")
    # 5. expiry_future -> dropped
    _interval(con, "L5", bbl="3000010005", issued=dt.date(2019, 1, 1),
              expires=dt.date(2028, 1, 1), name="ZETA", source=INACTIVE,
              category="bar", end_kind="expiry_future")
    # 6. sentinel creation date -> dropped
    _interval(con, "L6", bbl="3000010006", issued=dt.date(1900, 12, 31),
              expires=dt.date(2020, 1, 1), name="ETA", **i)
    # 7. ended, NO BBL -> unchecked: event flags NULL
    _interval(con, "L7", bbl=None, issued=dt.date(2019, 1, 1),
              expires=dt.date(2023, 1, 1), name="THETA", **i)
    # 8. a grocery, ended 2016 -- outside the 5-year window
    _interval(con, "L8", bbl="3000010008", issued=dt.date(2010, 1, 1),
              expires=dt.date(2016, 1, 1), name="IOTA MARKET",
              source=INACTIVE, category="grocery", end_kind="expiry_observed",
              cls="type 1 class 81")
    # 9. a DCWP row -- must not appear
    con.execute("""
        INSERT INTO analysis.licence_interval (licence_number, source, business_category,
            loci_category, licence_creation_date, expiration_date, status, interval_end,
            end_kind, days_observed, pulled_asof, provenance, ingested_at)
        VALUES ('D1', 'nyc_dcwp_licenses', 'Laundries', 'laundry', DATE '2020-01-01',
                DATE '2022-01-01', 'Expired', DATE '2022-01-01', 'expiry_observed',
                731, ?, 'test', now())""", [PULL])


def _rows(con):
    df = con.execute("SELECT * FROM analysis.licence_event ORDER BY licence_number").fetchdf()
    return df.set_index("licence_number")


# ------------------------------------------------------- (a) the definition

def test_no_successor_is_an_event_under_both_arms():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    r = _rows(con).loc["L1"]
    assert r["ended"] and r["successor_checkable"]
    assert pd.isna(r["successor_licence_number"])
    assert r["event_business"] is True or bool(r["event_business"])
    assert bool(r["event_premises"])


def test_same_name_successor_is_a_renewal_not_an_event():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    r = _rows(con).loc["L2"]
    assert r["successor_licence_number"] == "L2s"
    assert bool(r["successor_same_name"])
    assert not bool(r["event_business"]) and not bool(r["event_premises"])


def test_different_name_successor_is_a_business_event_only():
    """Transfer on sale: the business ended, the premises did not. The
    successor issued BEFORE the expiry, which the two-sided window admits."""
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    r = _rows(con).loc["L3"]
    assert r["successor_licence_number"] == "L3s"
    assert r["successor_gap_days"] < 0
    assert not bool(r["successor_same_name"])
    assert bool(r["event_business"]) and not bool(r["event_premises"])


def test_successor_outside_180_days_does_not_count():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    r = _rows(con).loc["L4"]
    assert pd.isna(r["successor_licence_number"])
    assert bool(r["event_business"]) and bool(r["event_premises"])


def test_expiry_future_sentinel_and_dcwp_rows_are_not_in_the_label():
    con = _con()
    _fixture(con)
    rep = le.build(con, asof=ASOF)
    idx = set(_rows(con).index)
    assert "L5" not in idx and "L6" not in idx and "D1" not in idx
    assert rep["dropped"] == {"expiry_future": 1, "sentinel_issue_date": 1}


def test_missing_bbl_leaves_the_event_flags_null_not_false():
    """The caveat the database cannot enforce: a licence the successor screen
    could not run on is UNKNOWN, and COALESCE-to-FALSE would invent renewals."""
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    r = _rows(con).loc["L7"]
    assert not bool(r["successor_checkable"])
    assert pd.isna(r["event_business"]) and pd.isna(r["event_premises"])
    assert pd.isna(r["event_5y_business"])


def test_active_rows_are_censored_at_the_pull_with_no_end_date():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    r = _rows(con).loc["L2s"]
    assert not bool(r["ended"]) and pd.isna(r["end_date"])
    assert r["censor_date"] == pd.Timestamp(PULL)
    assert not bool(r["event_business"])


def test_licence_class_is_the_number_with_zero_padding_stripped():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    rows = _rows(con)
    assert rows.loc["L1", "licence_class"] == 340      # 'class 0340'
    assert rows.loc["L8", "licence_class"] == 81       # 'class 81'


def test_build_is_idempotent_and_one_row_per_licence():
    con = _con()
    _fixture(con)
    a = le.build(con, asof=ASOF)["rows"]
    b = le.build(con, asof=ASOF)["rows"]
    assert a == b == 9          # L1 L2 L2s L3 L3s L4 L4s L7 L8
    dup = con.execute("SELECT count(*) FROM (SELECT licence_number FROM analysis.licence_event "
                      "GROUP BY 1 HAVING count(*) > 1)").fetchone()[0]
    assert dup == 0


def test_empty_sla_panel_raises():
    con = _con()
    with pytest.raises(RuntimeError, match="no SLA rows"):
        le.build(con, asof=ASOF)


# ------------------------------------------------- (b) window + baseline

def test_five_year_window_flags_and_baseline_view_agree():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    rows = _rows(con)
    # L8 ended 2016 -> not at risk in [2021-09-17, 2026-09-17]
    assert not bool(rows.loc["L8", "at_risk_5y"])
    # L1 ended 2021-02-28 -> also before the window
    assert not bool(rows.loc["L1", "at_risk_5y"])
    # L3 ended 2022-06-01 -> in window, business event only
    assert bool(rows.loc["L3", "at_risk_5y"])
    assert bool(rows.loc["L3", "event_5y_business"])
    assert not bool(rows.loc["L3", "event_5y_premises"])
    base = con.execute("""
        SELECT n_at_risk_5y, n_event_5y_business, n_event_5y_premises,
               nonrenewal_rate_5y_business
        FROM analysis.licence_event_baseline
        WHERE category = 'restaurant' AND borough = 'BK' AND licence_class IS NULL
    """).fetchone()
    # restaurant BK checkable at-risk: L2s(active), L3, L4s(active) -> 3; L7 unchecked
    assert base[0] == 3 and base[1] == 1 and base[2] == 0
    assert base[3] == pytest.approx(1 / 3)


def test_baseline_rollup_has_a_borough_row_and_a_category_row():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    n_cat_all = con.execute(
        "SELECT count(*) FROM analysis.licence_event_baseline "
        "WHERE category = 'restaurant' AND borough IS NULL AND licence_class IS NULL"
    ).fetchone()[0]
    assert n_cat_all == 1


# ---------------------------------------------------------- (c) the checks

def _address(con, aid, bbl, lon, lat, score=0.5):
    con.execute("""
        INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, frame, gap_score,
                                      nta_code, neighborhood, units, present_count, eligible,
                                      n_missing, reach_source, reach_hash, graph_version, run_at)
        VALUES (?, ?, ?, ?, 'BK', 'lot', ?, 'BK0101', 'Test', 10, 0, TRUE,
                0, 'tiers', 'h', 'g', now())""",
                [aid, bbl, lon, lat, score])


def test_p3_prime_counts_scored_lots_and_imputable_neighbours():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    _address(con, "A1", "3000010001", -73.95, 40.68)          # L1's lot, scored
    _address(con, "A2", "3000010002", -73.95, 40.68, score=None)  # L2's lot, unscored
    _address(con, "A3", "3999999999", -73.9502, 40.68)        # 17 m away, scored
    p = le.p3_prime(con)
    r = p["restaurant"]
    # MN+BK + NULL-borough universe: L1 L2 L2s L3 L4 L4s L7 = 7 (L3s is a bar)
    assert r["n"] == 7 and r["bbl_resolved"] == 6 and r["scored"] == 1
    assert r["share_scored"] == pytest.approx(1 / 7)
    # every unscored licence sits 17 m from A3, so all 6 are imputable
    assert r["imputable_within_50m"] == 6
    assert r["share_scored_or_imputed"] == pytest.approx(1.0)
    assert r["no_run"] is True and r["pass"] is False


def test_event_counts_apply_the_cohort_rule():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    e = le.event_counts(con)["restaurant"]
    # issued 2016-2021: L1 (2018, ended 2021-02 = 36 m -> in), L2 (2017, renewal),
    # L3 (2016-06, ended 2022-06 = 72 m -> out), L7 (2019, unchecked),
    # L2s (2020, active), L4s (2019, active)
    assert e["cohort_n"] == 6
    assert e["cohort_business"] == 1 and e["cohort_premises"] == 1
    assert e["raw_business"] == 3          # L1, L3, L4
    assert e["pass"] is False


def test_p5_scores_the_label_against_an_independent_closure():
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    # Foursquare closed ALPHA DINER 3 months after L1's expiry, 5 m away.
    con.execute("""INSERT INTO staging.poi_closure VALUES
        ('fsq1', 'k', 'restaurant', 'Alpha Diner', -73.95005, 40.68, DATE '2015-01-01',
         DATE '2021-05-30', 'foursquare_os_places', now())""")
    # Foursquare still refreshing GAMMA TAVERN two years after L3's expiry.
    con.execute("""INSERT INTO staging.poi (poi_id, source_id, category, tier, name, geom,
                     attrs) VALUES ('fsq2', 'foursquare_os_places', 'restaurant', 1,
                     'Gamma Tavern', ST_Point(-73.95, 40.68), '{"refreshed": "2024-06-01"}')""")
    p = le.p5_ppv(con)["restaurant"]
    assert p["n_events"] == 3 and p["n_joinable"] == 2
    assert p["n_closed_within_12m"] == 1 and p["n_seen_trading_after_12m"] == 1
    assert p["ppv_joinable"] == pytest.approx(0.5) and p["ppv_determined"] == pytest.approx(0.5)


def test_measure_columns_are_guarded_off_the_screen():
    from loci.model.address_gaps import ADDRESS_CATEGORY_SCREEN_COLUMNS
    assert not set(le.MEASURE_COLUMNS) & set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
    le._guard(le.MEASURE_COLUMNS)          # must not raise
    with pytest.raises(RuntimeError):
        le._guard(["nearest_m"])


def test_measure_reads_the_stamped_window_flags(monkeypatch):
    """The address measure sums exactly the at_risk_5y / event_5y_business
    flags -- no second window definition. The network engine is stubbed with
    'everything within reach' so the sums are the table's own totals."""
    con = _con()
    _fixture(con)
    le.build(con, asof=ASOF)
    _address(con, "A1", "3000010001", -73.95, 40.68)
    for c in [*le.CATEGORIES, "laundry"]:
        con.execute("INSERT INTO analysis.address_category (address_id, borough, category) "
                    "VALUES ('A1', 'BK', ?)", [c])

    def fake_sums(points, weight_cols, addresses, **kw):
        out = addresses[["address_id", "borough"]].copy()
        for c in weight_cols:
            out[c] = float(points[c].sum())
        return out, {"radius_m": 400.0, "graph_version": "stub", "points": len(points),
                     "points_without_coordinates": 0, "addresses": len(addresses),
                     "query_nodes": 1}
    monkeypatch.setattr("loci.model.walk_catchment.network_sums", fake_sums)
    _df, rep = le.build_measure(con, ["BK"])
    assert rep["_problems"] == []
    got = con.execute("SELECT category, n_licences_400m, n_nonrenewed_400m, "
                      "nonrenewal_rate_5y_400m FROM analysis.address_category "
                      "WHERE address_id = 'A1' ORDER BY 1").fetchall()
    d = {c: (n, e, r) for c, n, e, r in got}
    assert d["restaurant"] == (3, 1, pytest.approx(1 / 3))   # L2s, L3, L4s at risk; L3 event
    assert d["bar"] == (1, 0, 0.0)                            # L3s active
    assert d["grocery"] == (0, 0, None)                       # L8 ended 2016
    assert d["laundry"] == (None, None, None)                 # no SLA vocabulary
