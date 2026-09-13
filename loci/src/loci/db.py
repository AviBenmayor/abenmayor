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
    """Apply every migration from 002 onward, in numeric filename order.
    Idempotent (each file is CREATE ... IF NOT EXISTS / CREATE OR REPLACE).
    001 is the per-connection extension bootstrap and is applied by connect()."""
    for path in sorted(SQL_DIR.glob("*.sql")):
        if path.name.startswith("001_"):
            continue
        con.execute(path.read_text())
        if path.name == "002_schema.sql":
            # analysis.address_gaps is a VIEW generated from
            # loci.categories.CATEGORIES (model/address_gaps.address_gaps_view_sql),
            # not static DDL -- 002 itself never creates it. It has to exist
            # by THIS point, not at the end of the sweep: 004/005/006 all
            # reference analysis.address_gaps by name and DuckDB resolves a
            # view's query at CREATE time. Imported locally (not at module
            # level) because model.address_gaps imports loci.score.access,
            # which imports loci.db -- a module-level import here would be
            # circular.
            from loci.model.address_gaps import address_gaps_view_sql
            con.execute(address_gaps_view_sql())
        if path.name == "021_address_character.sql":
            # analysis.address_character / analysis.nta_character are VIEWS
            # generated from model/address_character.py, for the same reason
            # address_gaps is: the label thresholds must have ONE definition in
            # the codebase, and a CASE expression copied into a .sql file is a
            # second one waiting to drift. They must be created AFTER 021's
            # ALTERs (DuckDB resolves a view's query at CREATE time and the
            # columns would not exist yet), and nothing else references them, so
            # here is the right moment.
            from loci.model.address_character import create_views
            create_views(con)


# DuckDB's ST_Distance_Sphere reads POINT(x, y) as (LATITUDE, LONGITUDE); our geometry
# is (lon, lat), so both sides must be flipped or every distance is computed at the
# equator (1° lon at NYC → 111 km instead of 84 km). Decision D16. Use this, never the
# raw function.  METRES_SQL.format(a="geom", b="ST_Point(?, ?)")
METRES_SQL = "ST_Distance_Sphere(ST_FlipCoordinates({a}), ST_FlipCoordinates({b}))"
