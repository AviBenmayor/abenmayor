"""AC-6 (seed 2026-09-14, D82): the recommendation ledger and every top-N
output contain zero ineligible addresses.

`model/recommend.py` (card generation) is uncommitted peer work this session
was told not to edit, so the gate lives at the ONE place every write to
`analysis.recommendation` already passes through:
`model.recommendation_ledger.insert_rows`. This pins that gate directly
(`test_insert_rows_refuses_ineligible_anchor`) and then proves it holds for
the base table AFTER a mixed batch is offered
(`test_ledger_and_report_carry_zero_ineligible_rows`) -- the two things
AC-6's own verification text names: "queries analysis.recommendation and the
recs report path; assert count == 0".
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci import db as locidb
from loci.model import recommendation_ledger as rl

ADDR_REQUIRED = ("address_id", "lon", "lat", "borough", "present_count",
                 "eligible", "n_missing", "reach_source", "reach_hash",
                 "graph_version", "run_at")


@pytest.fixture()
def warehouse():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _seed_addresses(con) -> None:
    """Two analysis.address rows: one 'commercial' (a real, investable
    storefront address) and one 'ineligible' (zoned pure-residential, no
    open business) -- set directly, bypassing the PLUTO/spatial-join
    machinery `tests/test_address_legality.py` already covers."""
    import pandas as pd

    rows = [
        {"address_id": "eligible-1", "lon": -73.98, "lat": 40.75, "borough": "MN",
         "present_count": 0, "eligible": True, "n_missing": 0,
         "reach_source": "tiers", "reach_hash": "t", "graph_version": "g",
         "run_at": dt.datetime(2026, 9, 14), "legality": "commercial"},
        {"address_id": "ineligible-1", "lon": -73.99, "lat": 40.76, "borough": "MN",
         "present_count": 0, "eligible": True, "n_missing": 0,
         "reach_source": "tiers", "reach_hash": "t", "graph_version": "g",
         "run_at": dt.datetime(2026, 9, 14), "legality": "ineligible"},
    ]
    cols = list(ADDR_REQUIRED) + ["legality"]
    frame = pd.DataFrame(rows)[cols]
    con.register("_rows", frame)
    con.execute(f"INSERT INTO analysis.address ({', '.join(cols)}) "
                f"SELECT {', '.join(cols)} FROM _rows")
    con.unregister("_rows")


def _rec_row(rec_id: str, anchor_address_id: str) -> dict:
    """Minimal INSERT_COLUMNS-shaped row, built with the module's own `_row`
    helper (the SAME constructor `rows_from_cards` uses) so this test cannot
    drift from what a real card produces."""
    row = rl._row(issued_on=dt.date(2026, 9, 14), issued_by="test",
                  area_kind="address", area_id=anchor_address_id,
                  area_label=anchor_address_id, category="grocery",
                  anchor_address_id=anchor_address_id,
                  proposed_solution="grocery",
                  now=dt.datetime(2026, 9, 14, 12, 0))
    row["rec_id"] = rec_id
    return row


def test_insert_rows_refuses_ineligible_anchor(warehouse):
    _seed_addresses(warehouse)
    ok = _rec_row("r-ok", "eligible-1")
    blocked = _rec_row("r-blocked", "ineligible-1")
    res = rl.insert_rows(warehouse, [ok, blocked])
    assert res.n_written == 1
    assert res.n_ineligible == 1
    assert res.rec_ids == (ok["rec_id"],)


def test_ledger_and_report_carry_zero_ineligible_rows(warehouse):
    """The two checks AC-6's verification text names: a direct query of
    analysis.recommendation, and the recs report path."""
    _seed_addresses(warehouse)
    rl.insert_rows(warehouse, [
        _rec_row("r-ok", "eligible-1"),
        _rec_row("r-blocked", "ineligible-1"),
    ])

    # 1. analysis.recommendation directly.
    n_ineligible_in_ledger = warehouse.execute("""
        SELECT count(*) FROM analysis.recommendation r
        JOIN analysis.address a ON a.address_id = r.anchor_address_id
        WHERE a.legality = 'ineligible'
    """).fetchone()[0]
    assert n_ineligible_in_ledger == 0
    assert warehouse.execute(
        "SELECT count(*) FROM analysis.recommendation").fetchone()[0] == 1

    # 2. the recs report path (report_rows / list_recommendations).
    warehouse.execute("INSERT INTO analysis.recommendation_outcome "
                      "(rec_id, snapshot_month, match_kind, same_category, "
                      " still_open, quality_json, snapshot_at) "
                      "VALUES ('r-ok', '2026-09', 'none', TRUE, TRUE, '{}', now())")
    report = rl.report_rows(warehouse)
    listed = rl.list_recommendations(warehouse)
    assert {r["rec_id"] for r in report} == {"r-ok"}
    assert set(listed["rec_id"]) == {"r-ok"}


def test_gate_fails_open_when_legality_column_absent():
    """A pre-sql/031 database (or one on which `loci address-legality build`
    has never run) must not have every recommendation insert start failing --
    the missing-measurement-fails-open contract `score.supply`'s anchor
    coverage already uses."""
    con = locidb.connect(":memory:")
    con.execute("INSTALL spatial; LOAD spatial;")
    # A bare analysis.address with none of sql/031's columns -- simulate a
    # database frozen before this migration existed by using a fresh schema
    # that never applied 031 is not reachable through init_schema (it always
    # applies every file), so this pins the FUNCTION directly instead.
    ineligible = rl._ineligible_anchor_ids(
        _no_legality_column_con(), {"whatever"})
    assert ineligible == set()


def test_report_and_list_filter_ineligible_read_time_not_just_at_insert(warehouse):
    """D97 item 6: `insert_rows`'s gate is write-time only -- it checks
    legality as of the INSERT, not as of the READ. An anchor's legality can
    change afterward (a rebuild re-zones the lot, or the row predates
    sql/031 entirely and was inserted before the column existed at all), so
    `report_rows` / `list_recommendations` must re-check the CURRENT
    `analysis.address.legality` on every read -- defense in depth, not
    redundant with the insert-time gate `test_insert_rows_refuses_ineligible_anchor`
    already pins.

    This writes a row while its anchor is still 'commercial' (insert_rows
    lets it through, correctly), THEN flips that same anchor to 'ineligible'
    -- exactly what a re-zoning or an address-gaps rebuild followed by
    `address-legality build` can do -- and proves the row disappears from
    both read paths without ever being deleted from the ledger itself (the
    ledger is history; AC-6 is about what gets SHOWN as a live top-N/report
    row, not about erasing the record)."""
    _seed_addresses(warehouse)
    rl.insert_rows(warehouse, [_rec_row("r-was-eligible", "eligible-1")])
    assert {r["rec_id"] for r in rl.report_rows(warehouse)} == {"r-was-eligible"}

    # The anchor's legality changes AFTER the row was written.
    warehouse.execute(
        "UPDATE analysis.address SET legality = 'ineligible' WHERE address_id = 'eligible-1'")

    assert rl.report_rows(warehouse) == []
    assert rl.list_recommendations(warehouse).empty
    # The row is still IN the ledger -- history is not erased.
    assert warehouse.execute(
        "SELECT count(*) FROM analysis.recommendation WHERE rec_id = 'r-was-eligible'"
    ).fetchone()[0] == 1


def test_report_and_list_fail_open_when_legality_column_absent():
    """The READ-path gate (`_ineligible_filter_sql`) fails open the same way
    the write-path gate does: a database with no `legality` column at all
    must still print its report, not silently empty it."""
    con = _no_legality_column_con()
    rl.ensure_schema(con)
    row = rl._row(issued_on=dt.date(2026, 9, 14), issued_by="test",
                  area_kind="bbox", area_id="1,2,3,4", area_label="nowhere",
                  category="grocery", anchor_address_id=None,
                  proposed_solution="grocery",
                  now=dt.datetime(2026, 9, 14, 12, 0))
    row["rec_id"] = "r-x"
    rl.insert_rows(con, [row])
    assert {r["rec_id"] for r in rl.report_rows(con)} == {"r-x"}
    assert set(rl.list_recommendations(con)["rec_id"]) == {"r-x"}


def _no_legality_column_con():
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.address (address_id VARCHAR)")
    return con
