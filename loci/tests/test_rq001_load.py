"""Offline tests for loci.sources.rq001_load (GTM-224).

All in-memory duckdb + tiny parquet fixtures written to tmp_path -- no
network, no real warehouse file, no dependency on data/interim/rq001/*
(gitignored, may not exist on a fresh clone).
"""
from __future__ import annotations

import duckdb
import pytest

from loci.db import SQL_DIR
from loci.sources import rq001_load


def _write_parquet(con: duckdb.DuckDBPyConnection, path, rows_sql: str) -> None:
    """Write a tiny parquet fixture via a scratch table, so column types are
    explicit rather than inferred from a bare VALUES clause."""
    con.execute(f"COPY ({rows_sql}) TO '{path}' (FORMAT PARQUET)")


def test_load_all_replaces_and_reports_counts(tmp_path, monkeypatch, capsys):
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE TABLE raw.t1 (a INTEGER, b VARCHAR)")
    con.execute("INSERT INTO raw.t1 VALUES (99, 'stale')")  # must be replaced, not appended to

    fixture = tmp_path / "t1.parquet"
    _write_parquet(con, fixture, "SELECT * FROM (VALUES (1, 'x'), (2, 'y')) AS v(a, b)")

    monkeypatch.setattr(rq001_load, "_LOADS", [("raw.t1", fixture, "SELECT a, b FROM src")])

    counts = rq001_load.load_all(con)

    assert counts == {"raw.t1": 2}
    rows = con.execute("SELECT a, b FROM raw.t1 ORDER BY a").fetchall()
    assert rows == [(1, "x"), (2, "y")]  # stale row 99 gone -- DELETE, not append
    assert "raw.t1: 2 rows" in capsys.readouterr().out


def test_load_all_raises_on_missing_parquet(tmp_path, monkeypatch):
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE TABLE raw.t1 (a INTEGER)")

    missing = tmp_path / "does_not_exist.parquet"
    monkeypatch.setattr(rq001_load, "_LOADS", [("raw.t1", missing, "SELECT a FROM src")])

    with pytest.raises(FileNotFoundError):
        rq001_load.load_all(con)


def test_load_all_raises_on_zero_rows_never_ingests_a_silent_empty_table(tmp_path, monkeypatch):
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE TABLE raw.t1 (a INTEGER)")

    empty = tmp_path / "empty.parquet"
    _write_parquet(con, empty, "SELECT * FROM (VALUES (1)) AS v(a) WHERE a = 2")  # 0 rows
    monkeypatch.setattr(rq001_load, "_LOADS", [("raw.t1", empty, "SELECT a FROM src")])

    with pytest.raises(RuntimeError, match="0 rows"):
        rq001_load.load_all(con)


def test_irs_zip_income_panel_ddl_accepts_null_agi_stub_legacy_rows(tmp_path, monkeypatch):
    """Regression test for the bug caught live during GTM-224: DuckDB's
    PRIMARY KEY (unlike UNIQUE) silently requires every key column NOT NULL,
    even when the column itself carries no NOT NULL -- so a PRIMARY KEY on
    (zip, tax_year, agi_stub) rejected every legacy-year row (agi_stub IS
    NULL by construction, sql/060's GRAIN note). sql/060 now declares UNIQUE
    instead. This test applies the REAL migration file, not a hand-copied
    schema, so it fails again if that constraint ever regresses to
    PRIMARY KEY.
    """
    con = duckdb.connect(":memory:")
    con.execute((SQL_DIR / "060_rq001_macro_income.sql").read_text())

    fixture = tmp_path / "irs.parquet"
    _write_parquet(
        con,
        fixture,
        """
        SELECT * FROM (VALUES
            ('10001', 2005, NULL, 100.0, 5000000.0, NULL, 4000000.0, false),
            ('10001', 2011, 0,    120.0, 6000000.0, 110.0, 4800000.0, false)
        ) AS v(zip, tax_year, agi_stub, n1, agi, n_wages, a_wages, any_suppressed)
        """,
    )

    # Reuse the module's own real SELECT expression for this table (the
    # tax_year/agi_stub CAST logic), pointed at the tiny fixture instead of
    # the real parquet path.
    real_select = next(s for (t, _p, s) in rq001_load._LOADS if t == "raw.irs_zip_income_panel")
    monkeypatch.setattr(rq001_load, "_LOADS", [("raw.irs_zip_income_panel", fixture, real_select)])

    counts = rq001_load.load_all(con)

    assert counts == {"raw.irs_zip_income_panel": 2}
    legacy = con.execute(
        "SELECT agi_stub FROM raw.irs_zip_income_panel WHERE tax_year = 2005"
    ).fetchone()
    assert legacy == (None,)
