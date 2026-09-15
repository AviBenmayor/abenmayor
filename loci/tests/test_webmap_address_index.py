"""`webmap/data/address_index.json` (D99, GTM-171, seed AC-14) -- the
bbl -> address_id map the browser search box uses to resolve a GeoSearch
BBL hit locally, without a round trip, mirroring `loci.geo.geosearch.snap`'s
bbl-first rule server-side.

Own local warehouse fixture via `db.init_schema` (real `analysis.address`
columns, including `bbl` and `frame`) rather than the hand-rolled subset
`tests/test_webmap_export.py`'s `con` fixture uses -- that file is being
edited concurrently by a peer session (`_poi_sql`/`_nta_poi_sql`), so this
stays a separate module rather than sharing or extending its fixture.
"""
from __future__ import annotations

import datetime as dt
import json

import loci.db as locidb
from loci.viz import webmap_export as wx


def _insert_address(con, address_id, bbl, borough, *, frame="lot"):
    con.execute(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, "
        "nta_code, eligible, present_count, n_missing, reach_source, reach_hash, "
        "graph_version, run_at, frame) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [address_id, bbl, -73.95, 40.71, borough, "BK0601", True, 12, 3,
         "tiers", "h", "g", dt.datetime(2026, 9, 11), frame])


def test_lot_frame_addresses_with_a_bbl_are_indexed(tmp_path):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", "3012340001", "BK")
    _insert_address(con, "addr2", "1000010001", "MN")

    n = wx.write_address_index(con, ["MN", "BK"], tmp_path)

    index = json.loads((tmp_path / "address_index.json").read_text())
    assert index == {"3012340001": "addr1", "1000010001": "addr2"}
    assert n == len((tmp_path / "address_index.json").read_bytes())


def test_street_frame_rows_are_excluded(tmp_path):
    """D84 street-midpoint rows carry no real BBL ownership -- they must not
    appear even if a `bbl` value happens to be set on one."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", "3012340001", "BK", frame="lot")
    _insert_address(con, "addr3", "3099990001", "BK", frame="street")

    wx.write_address_index(con, ["BK"], tmp_path)

    index = json.loads((tmp_path / "address_index.json").read_text())
    assert index == {"3012340001": "addr1"}


def test_null_bbl_rows_are_excluded(tmp_path):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", None, "BK")

    wx.write_address_index(con, ["BK"], tmp_path)

    index = json.loads((tmp_path / "address_index.json").read_text())
    assert index == {}


def test_borough_filter_applies(tmp_path):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", "3012340001", "BK")
    _insert_address(con, "addr2", "1000010001", "MN")

    wx.write_address_index(con, ["BK"], tmp_path)

    index = json.loads((tmp_path / "address_index.json").read_text())
    assert index == {"3012340001": "addr1"}
