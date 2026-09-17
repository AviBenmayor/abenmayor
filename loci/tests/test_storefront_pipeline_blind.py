"""Category-BLIND filing counts (storefront_pipeline.build_blind, sql/051).

Pinned: the four stages and three windows are read straight off
staging.storefront_filing (no roll-up key decides what counts), the windows
nest, an unplaced filing contributes nothing and is counted as such, the
columns are guarded off the screen, and the check that once FAILED the build
on an old liquor_active date is now a reported note (the SLA feed is no
longer windowed -- D119).
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci import db as locidb
from loci.model import storefront_pipeline as sp

ASOF = dt.date(2026, 9, 17)
LON, LAT = -73.95, 40.68


def _con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("CREATE TEMP TABLE _pluto_lot (bbl VARCHAR, borocode VARCHAR, addr_key VARCHAR, "
                "lon DOUBLE, lat DOUBLE, geom GEOMETRY)")
    con.execute("INSERT INTO _pluto_lot VALUES ('3000010009', '3', '', ?, ?, ST_Point(?, ?))",
                [LON, LAT, LON, LAT])
    return con


def _filing(con, fid, stage, filed_on, *, lon=LON, lat=LAT, bbl=None,
            source="nyc_dob_now_job_filings"):
    con.execute("""
        INSERT INTO staging.storefront_filing (filing_id, source, stage, business_name,
            business_name_key, bbl, match_method, borough, lon, lat, filed_on, raw_id,
            ingested_at, provenance)
        VALUES (?, ?, ?, 'X', 'x', ?, 'unmatched', 'BK', ?, ?, ?, ?, now(), 'test')""",
                [fid, source, stage, bbl, lon, lat, filed_on, fid])


def test_windows_nest_and_stages_are_read_from_the_filing_table():
    con = _con()
    _filing(con, "f1", "sign_permit", dt.date(2026, 8, 1))            # 6 m
    _filing(con, "f2", "sign_permit", dt.date(2026, 1, 1))            # 12 m
    _filing(con, "f3", "sign_permit", dt.date(2025, 1, 1))            # 24 m
    _filing(con, "f4", "sign_permit", dt.date(2023, 1, 1))            # outside
    _filing(con, "f5", "fitout_filing", dt.date(2026, 6, 1))
    _filing(con, "f6", "liquor_application", dt.date(2026, 6, 1),
            source="nyc_sla_pending_licenses")
    _filing(con, "f7", "first_inspection", dt.date(2026, 6, 1),
            source="nyc_dohmh_restaurants")          # not a blind stage
    _filing(con, "f8", "permit_issued", dt.date(2026, 6, 1), lon=None, lat=None)  # unplaced
    _filing(con, "f9", "permit_issued", dt.date(2026, 6, 1), lon=None, lat=None,
            bbl="3000010009")                                          # placed from PLUTO
    pts, rep = sp.load_blind_points(con, ASOF)
    assert rep["filings_in_widest_window"] == 7 and rep["unplaced"] == 1   # f4 out, f7 not blind
    assert rep["placed_from_pluto"] == 1
    s = pts[[c for c in sp.BLIND_COLUMNS]].sum()
    assert (s["sign_permit_400m_6m"], s["sign_permit_400m_12m"],
            s["sign_permit_400m_24m"]) == (1, 2, 3)
    assert s["fitout_400m_6m"] == 1 and s["liquor_application_400m_6m"] == 1
    assert s["permit_issued_400m_6m"] == 2       # the unplaced one is in the frame, weight 1


def test_measure_writes_every_address_and_validates(monkeypatch):
    con = _con()
    _filing(con, "f1", "sign_permit", dt.date(2026, 8, 1))
    _filing(con, "f8", "permit_issued", dt.date(2026, 6, 1), lon=None, lat=None)
    con.execute("""
        INSERT INTO analysis.address (address_id, lon, lat, borough, frame, present_count,
            eligible, n_missing, reach_source, reach_hash, graph_version, run_at)
        VALUES ('A1', ?, ?, 'BK', 'lot', 0, TRUE, 0, 'tiers', 'h', 'g', now())""", [LON, LAT])

    def fake_sums(points, weight_cols, addresses, **kw):
        # the engine drops unplaced points before snapping; mirror that
        pts = points.dropna(subset=["lon", "lat"])
        out = addresses[["address_id", "borough"]].copy()
        for c in weight_cols:
            out[c] = float(pts[c].sum())
        return out, {"radius_m": 400.0, "graph_version": "stub", "points": len(pts),
                     "points_without_coordinates": len(points) - len(pts),
                     "addresses": len(addresses), "query_nodes": 1}
    monkeypatch.setattr("loci.model.walk_catchment.network_sums", fake_sums)
    _df, rep = sp.build_blind(con, ["BK"], asof=ASOF)
    assert rep["_problems"] == [] and rep["_written"] == 1
    row = con.execute("SELECT sign_permit_400m_6m, permit_issued_400m_24m, filings_blind_asof "
                      "FROM analysis.address").fetchone()
    assert row == (1, 0, ASOF)


def test_blind_columns_are_guarded_off_the_screen():
    from loci.model.address_gaps import ADDRESS_COLUMNS
    assert not set(sp.BLIND_COLUMNS) & set(ADDRESS_COLUMNS)
    sp._guard(sp.BLIND_COLUMNS)
    with pytest.raises(RuntimeError):
        sp._guard(["gap_score"])


def test_no_placed_filing_raises_rather_than_writing_zeros():
    con = _con()
    _filing(con, "f8", "permit_issued", dt.date(2026, 6, 1), lon=None, lat=None)
    with pytest.raises(RuntimeError, match="no placed filing"):
        sp.load_blind_points(con, ASOF)


def test_old_liquor_active_opened_on_is_a_note_not_a_failure():
    """The full-history SLA feed reaches 1981. sql/020's window check used to
    FAIL the build on that; it now reports the age (D119)."""
    con = _con()
    _filing(con, "s1", "liquor_active", dt.date(1990, 1, 1), bbl="3000010009",
            source="nys_sla_liquor_licenses")
    _df, rep = sp.build(con, asof=ASOF, reconcile_links=False, pluto=False)
    assert rep["_problems"] == []
    assert "1990-01-01" in getattr(sp.validate, "liquor_active_note", "")


def test_card_pipeline_list_is_windowed_on_the_full_history():
    """A fit-out filed in 1996 that never opened must not read as 'coming'."""
    from loci.report import evidence as ev

    con = _con()
    con.execute("""
        INSERT INTO analysis.storefront_pipeline (pipeline_id, group_kind, business_name,
            loci_category, entry_stage, entry_date, lon, lat, is_open, n_filings, n_sources,
            bbl_missing, name_key_missing, asof_date, built_at)
        VALUES ('old', 'filing', 'OLD', 'restaurant', 'fitout_filing', DATE '1996-01-01',
                ?, ?, FALSE, 1, 1, FALSE, FALSE, DATE '2026-09-17', now()),
               ('new', 'filing', 'NEW', 'restaurant', 'fitout_filing', DATE '2026-06-01',
                ?, ?, FALSE, 1, 1, FALSE, FALSE, DATE '2026-09-17', now()),
               ('undated', 'filing', 'UND', 'restaurant', 'fitout_filing', NULL,
                ?, ?, FALSE, 1, 1, FALSE, FALSE, DATE '2026-09-17', now())""",
                [LON, LAT] * 3)
    rows = ev._pipeline_rows(con, LAT, LON, 400.0)
    assert {r.pipeline_id for r in rows} == {"new", "undated"}
