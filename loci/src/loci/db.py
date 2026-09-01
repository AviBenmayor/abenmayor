"""DuckDB connection bootstrap.

DuckDB extensions load per-connection, not per-database, so every connection
must apply loci/sql/001_bootstrap.sql. Always obtain connections through `connect()`.

GEOMETRY in DuckDB carries no SRID. Everything stored is EPSG:4326 by
convention; reproject explicitly for metric work. The database will not catch a
violation of this, so the convention has to be held in code.
"""
from __future__ import annotations

import os
import pathlib

import duckdb

PKG = pathlib.Path(__file__).resolve().parent
SQL_DIR = PKG / "sql"
REPO_ROOT = PKG.parents[1]
DEFAULT_PATH = REPO_ROOT / "data" / "loci.duckdb"


def connect(path: pathlib.Path | str | None = None,
            read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a bootstrapped connection. `path=':memory:'` for a scratch database."""
    target = (os.environ.get("LOCI_DB") or DEFAULT_PATH) if path is None else path
    if target != ":memory:":
        pathlib.Path(target).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(target), read_only=read_only)
    con.execute((SQL_DIR / "001_bootstrap.sql").read_text())
    return con


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Apply loci/sql/002_schema.sql. Idempotent."""
    con.execute((SQL_DIR / "002_schema.sql").read_text())
