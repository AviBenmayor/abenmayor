"""`webmap/data/address_index.json` (D99, GTM-171, seed AC-14; extended
GTM-169 to carry legality) -- `{"values": [...], "idx": {bbl: [address_id,
legality_idx, histdist, landmark]}}` the browser search box uses to resolve
a GeoSearch BBL hit locally, without a round trip, mirroring
`loci.geo.geosearch.snap`'s bbl-first rule server-side, AND to render the
same legality/fit-out line `legHTML()` shows on a gap card even when the
searched address is not a gap for the selected category (defect: the bare
"Address found / not a <category> gap" card had no legality line because
`openAddressCard` previously only read legality via the selected category's
gap arrays).

Own local warehouse fixture via `db.init_schema` (real `analysis.address`
columns, including `bbl`, `frame`, and the legality columns sql/031 adds)
rather than the hand-rolled subset `tests/test_webmap_export.py`'s `con`
fixture uses -- that file is being edited concurrently by a peer session
(`_poi_sql`/`_nta_poi_sql`), so this stays a separate module rather than
sharing or extending its fixture.
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


def _set_legality(con, address_id, legality, *, histdist=None, landmark=None):
    con.execute(
        "UPDATE analysis.address SET legality = ?, histdist = ?, landmark = ? "
        "WHERE address_id = ?",
        [legality, histdist, landmark, address_id])


def test_lot_frame_addresses_with_a_bbl_are_indexed_with_no_legality_reading(tmp_path):
    """No `loci address-legality build` has run on this fixture -- every row
    gets the null legality triple, not a silent 'commercial' (same
    membership-is-the-test contract `collect_legality_detail` documents)."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", "3012340001", "BK")
    _insert_address(con, "addr2", "1000010001", "MN")

    n = wx.write_address_index(con, ["MN", "BK"], tmp_path)

    payload = json.loads((tmp_path / "address_index.json").read_text())
    assert payload["values"] == list(wx.LEGALITY_VALUES)
    assert payload["idx"] == {
        "3012340001": ["addr1", None, None, None],
        "1000010001": ["addr2", None, None, None],
    }
    assert n == len((tmp_path / "address_index.json").read_bytes())


def test_legality_reading_is_carried_as_an_int_index_plus_flags(tmp_path):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", "3012340001", "BK")
    _set_legality(con, "addr1", "grandfathered", histdist="Historic District", landmark=None)

    wx.write_address_index(con, ["BK"], tmp_path)

    payload = json.loads((tmp_path / "address_index.json").read_text())
    li = wx.LEGALITY_VALUES.index("grandfathered")
    assert payload["idx"]["3012340001"] == ["addr1", li, 1, 0]


def test_ineligible_legality_is_indexed_the_same_way_report_button_reads(tmp_path):
    """The report button's eligibility gate and this index share one source
    of truth (D82): 'ineligible' must round-trip as the exact index the
    webmap's LEGALITY_VALUES-ordered `values` list resolves back to
    'ineligible'."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", "3012340001", "BK")
    _set_legality(con, "addr1", "ineligible")

    wx.write_address_index(con, ["BK"], tmp_path)

    payload = json.loads((tmp_path / "address_index.json").read_text())
    li = payload["idx"]["3012340001"][1]
    assert payload["values"][li] == "ineligible"


def test_street_frame_rows_are_excluded(tmp_path):
    """D84 street-midpoint rows carry no real BBL ownership -- they must not
    appear even if a `bbl` value happens to be set on one."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", "3012340001", "BK", frame="lot")
    _insert_address(con, "addr3", "3099990001", "BK", frame="street")

    wx.write_address_index(con, ["BK"], tmp_path)

    payload = json.loads((tmp_path / "address_index.json").read_text())
    assert list(payload["idx"].keys()) == ["3012340001"]


def test_null_bbl_rows_are_excluded(tmp_path):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", None, "BK")

    wx.write_address_index(con, ["BK"], tmp_path)

    payload = json.loads((tmp_path / "address_index.json").read_text())
    assert payload["idx"] == {}


def test_borough_filter_applies(tmp_path):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _insert_address(con, "addr1", "3012340001", "BK")
    _insert_address(con, "addr2", "1000010001", "MN")

    wx.write_address_index(con, ["BK"], tmp_path)

    payload = json.loads((tmp_path / "address_index.json").read_text())
    assert list(payload["idx"].keys()) == ["3012340001"]
