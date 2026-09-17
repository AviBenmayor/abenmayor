"""One-time warehouse rebuilds, guarded and idempotent.

WHY THESE ARE NOT .sql FILES
----------------------------
`db.init_schema` applies EVERY *.sql in src/loci/sql on EVERY session, in
filename order. That is the right contract for `CREATE ... IF NOT EXISTS` and
`CREATE OR REPLACE VIEW`, and the wrong one for a 25-million-row table rebuild:
DuckDB cannot `ALTER TABLE ... ADD CONSTRAINT` (verified, 1.5.5 --
"No support for that ALTER TABLE option yet"), so adding a CHECK means
CREATE-INSERT-DROP-RENAME, and a migration file that did that would re-run it
nightly.

So the heavy steps live here, each with a PROBE that reads the catalog and
returns True when the step has already been applied, and each is a CLI
subcommand rather than a loose script (CLAUDE.md's rule that eliminated the
`ops/` junk drawer). `loci migrate-warehouse` is DRY-RUN BY DEFAULT and prints
the before/after row counts it expects; `--apply` is the only way to write.

EVERY STEP IN THIS MODULE WRITES TO THE SHARED WAREHOUSE. None may run while
another wave holds the file. `reclaim` additionally needs every peer quiet, and
says so.

WHAT THE DATABASE CANNOT ENFORCE, AND THIS MODULE THEREFORE CHECKS BY HAND
--------------------------------------------------------------------------
A CTAS rebuild does NOT carry over constraints, comments, or indexes -- only
columns and rows. Each step re-declares them explicitly and asserts the row
count is unchanged before dropping the original. A rebuild that silently loses
rows is worse than no rebuild, so the count assertion is not optional and is
not a warning.
"""
from __future__ import annotations

import dataclasses
import pathlib
import shutil
import typing

#: Tables whose every row must be in the MN+BK screen, with the key they are
#: rebuilt under. Owner ruling 2026-09-16: enforce the scope IN THE SCHEMA on
#: screen and report tables. All of these hold MN+BK only TODAY -- the CHECK
#: locks in a fact rather than changing one, so the rebuild must not move a
#: single row, and `scope_checks` asserts exactly that.
SCREEN_TABLES: dict[str, str] = {
    "analysis.dev_pipeline": "job_number",
    "analysis.address_bike_growth": "",
    "analysis.address_transit_profile": "",
    "analysis.address_entrance": "",
    "analysis.address_bike_station": "",
}

#: Rebuilt with a physical sort so DuckDB's zonemaps can prune. The audit
#: measured 89,510 descents over 332,041 unsorted rows in analysis.address for
#: ONE single-address report.
ORDERED_TABLES: dict[str, tuple[str, str]] = {
    # table: (order-by clause, primary key)
    "analysis.address": ("address_id", "borough, address_id"),
    "analysis.address_category": ("address_id, category", "borough, address_id, category"),
}


@dataclasses.dataclass
class Result:
    step: str
    applied: bool
    before: dict[str, int]
    after: dict[str, int]
    notes: list[str]


def _count(con, rel: str) -> int:
    return con.execute(f"SELECT count(*) FROM {rel}").fetchone()[0]


def _columns(con, qualified: str) -> list[str]:
    schema, name = qualified.split(".", 1)
    return [r[0] for r in con.execute(
        "SELECT column_name FROM duckdb_columns() "
        "WHERE schema_name = ? AND table_name = ? ORDER BY column_index",
        [schema, name]).fetchall()]


def _coldefs(con, qualified: str, check_borough: bool = False) -> str:
    """Column definitions for a rebuild, PRESERVING nullability and defaults.

    A CTAS carries columns and rows and NOTHING ELSE -- not NOT NULL, not
    DEFAULT, not CHECK, not the primary key. `analysis.address` declares 11 NOT
    NULL columns including `lon`, `lat` and `borough`, plus
    `frame DEFAULT 'lot'`; `analysis.dev_pipeline` declares 8 and carries a
    GEOMETRY. Rebuilding them from `column_name || ' ' || data_type` alone would
    silently drop every one of those guarantees, and the table would look
    identical until something wrote a NULL coordinate a month later.

    So the definitions are reconstructed from duckdb_columns(), which reports
    `is_nullable` and `column_default`, and
    `test_rebuild_preserves_not_null_and_defaults` pins that they survive.
    """
    rows = con.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM duckdb_columns() WHERE schema_name = ? AND table_name = ? "
        "ORDER BY column_index", qualified.split(".")).fetchall()
    parts = []
    for name, dtype, nullable, default in rows:
        piece = f"{name} {dtype}"
        if default is not None:
            piece += f" DEFAULT {default}"
        if not nullable:
            piece += " NOT NULL"
        if check_borough and name == "borough":
            # NOT NULL too: an unknown borough in a SCREEN table is a row that
            # has not been resolved, not a row that gets a pass.
            if nullable:
                piece += " NOT NULL"
            piece += " CHECK (borough IN ('MN', 'BK'))"
        parts.append(piece)
    return ",\n            ".join(parts)


def _has_check(con, qualified: str) -> bool:
    """Does this table carry the BOROUGH scope CHECK specifically?

    NOT "does it carry any CHECK". That was the first version and it produced a
    FALSE GREEN on the live warehouse: `analysis.address` already had
    CHECK(reach_source IN ('tiers','p80')) and `analysis.address_category` had
    CHECK(demand_class IN (...)), so the probe reported "already applied" and
    `address_order` silently skipped the rebuild it was asked to do. The table
    was still unsorted and still unconstrained on borough, and nothing would
    have said so.

    A probe that can be satisfied by something OTHER than the thing it is
    probing for is worse than no probe -- it converts a skipped step into a
    reported success.
    """
    schema, name = qualified.split(".", 1)
    return bool(con.execute(
        "SELECT count(*) FROM duckdb_constraints() "
        "WHERE schema_name = ? AND table_name = ? AND constraint_type = 'CHECK' "
        "AND constraint_text ILIKE '%borough%'",
        [schema, name]).fetchone()[0])


def _swap(con, qualified: str, ddl: str, select: str, notes: list[str]) -> tuple[int, int]:
    """CREATE new -> INSERT -> assert count -> DROP old -> RENAME.

    The count assertion is the whole safety property. A CTAS that drops rows on
    a type coercion, a CHECK that rejects a row nobody expected, a predicate
    typo -- all of them look like success until something downstream reads a
    number that is quietly 3% low.
    """
    schema, name = qualified.split(".", 1)
    tmp = f"{schema}.{name}__rebuild"
    before = _count(con, qualified)
    con.execute(f"DROP TABLE IF EXISTS {tmp}")
    con.execute(ddl.replace("__TARGET__", tmp))
    con.execute(f"INSERT INTO {tmp} {select}")
    after = _count(con, tmp)
    if after != before:
        con.execute(f"DROP TABLE IF EXISTS {tmp}")
        raise RuntimeError(
            f"{qualified}: rebuild produced {after:,} rows from {before:,}. "
            f"Refusing to swap. Nothing was dropped; {tmp} has been removed.")
    con.execute(f"DROP TABLE {qualified}")
    con.execute(f"ALTER TABLE {tmp} RENAME TO {name}")
    notes.append(f"{qualified}: {before:,} -> {after:,} rows, count identical")
    return before, after


# --------------------------------------------------------------------- steps

def probe_forecast_slim(con) -> bool:
    cols = _columns(con, "analysis.forecast")
    return "features_json" not in cols and "forecast_id" not in cols


def step_forecast_slim(con, apply: bool) -> Result:
    """Drop features_json and forecast_id; keep EVERY vintage.

    Owner ruling (2026-09-16): keep every vintage, drop the redundant columns,
    reclaim the file space. The audit's proposal to keep one shipped vintage per
    issued_month was OVERRULED -- five superseded 2026-09 reruns stay.

    `forecast_id` is 'f-'||issued_month||'-'||githash||'-'||address_id||'-'||
    category: a restatement of the four-column key that already carries a UNIQUE
    index, costing 257 MiB. `features_json` is a 7-key VARCHAR blob repeated
    4.2M times per vintage, 526 MiB, and is the model INPUT -- re-derivable.

    `features_hash` REPLACES it: the first 16 chars of md5 over the same string.
    That is computed HERE, during the rebuild, because it is the last moment the
    values exist. It keeps the one property a reader actually needs -- "were
    these two vintages fitted on the same feature set?" -- and drops the 526 MiB
    that answered a question nobody asked.
    """
    notes: list[str] = []
    before = {"analysis.forecast": _count(con, "analysis.forecast")}
    vintages = con.execute(
        "SELECT count(DISTINCT (issued_month, model_version)) FROM analysis.forecast"
    ).fetchone()[0]
    notes.append(f"{vintages} vintages, ALL retained (owner ruling 2026-09-16)")
    if probe_forecast_slim(con):
        notes.append("already applied — no-op")
        return Result("forecast_slim", False, before, before, notes)
    if not apply:
        notes.append("DRY RUN — expect the row count to be IDENTICAL and the "
                     "table to fall from ~1,292 MiB to ~510 MiB; the file does "
                     "not shrink until `reclaim`")
        return Result("forecast_slim", False, before, before, notes)

    # Column for column with sql/028's CREATE TABLE -- a fresh build and a
    # migrated one must not differ, which is the exact defect
    # `activity_canonical` on analysis.storefront demonstrates today (ordinal 25
    # fresh, 31 on disk, and every neighbouring column a silently-compatible
    # VARCHAR).
    ddl = """
        CREATE TABLE __TARGET__ (
            issued_month      VARCHAR NOT NULL,
            horizon_months    INTEGER NOT NULL,
            model_version     VARCHAR NOT NULL,
            address_id        VARCHAR NOT NULL,
            category          VARCHAR NOT NULL,
            frame             VARCHAR NOT NULL DEFAULT 'lot',
            borough           VARCHAR NOT NULL CHECK (borough IN ('MN', 'BK')),
            nta_code          VARCHAR,
            surprise_cell     VARCHAR,
            p_opening         DOUBLE  NOT NULL,
            expected_openings DOUBLE  NOT NULL,
            support           VARCHAR NOT NULL
                CHECK (support IN ('fitted', 'pooled', 'street_no_homes')),
            features_hash     VARCHAR NOT NULL,
            frozen_at         TIMESTAMP NOT NULL,
            PRIMARY KEY (issued_month, model_version, address_id, category)
        )"""
    select = """
        (issued_month, horizon_months, model_version, address_id, category,
         frame, borough, nta_code, surprise_cell, p_opening, expected_openings,
         support, features_hash, frozen_at)
        SELECT issued_month, horizon_months, model_version, address_id, category,
               COALESCE(frame, 'lot'), borough, nta_code, surprise_cell,
               p_opening, expected_openings, support,
               substr(md5(features_json), 1, 16), frozen_at
        FROM analysis.forecast
        ORDER BY issued_month, model_version, address_id, category"""
    _swap(con, "analysis.forecast", ddl, select, notes)
    after = {"analysis.forecast": _count(con, "analysis.forecast")}
    return Result("forecast_slim", True, before, after, notes)


def probe_forecast_outcome_rekey(con) -> bool:
    return "forecast_id" not in _columns(con, "analysis.forecast_outcome")


def step_forecast_outcome_rekey(con, apply: bool) -> Result:
    """Re-key the outcome ledger off forecast_id onto the natural key.

    MUST RUN BEFORE `forecast_slim`, not after: it recovers the four key columns
    by JOINING analysis.forecast on forecast_id, and forecast_slim is what
    deletes that column. Run in the wrong order and the join key is gone.

    This is append-only outcome data. The row count must not move.
    """
    notes: list[str] = []
    before = {"analysis.forecast_outcome": _count(con, "analysis.forecast_outcome")}
    if probe_forecast_outcome_rekey(con):
        notes.append("already applied — no-op")
        return Result("forecast_outcome_rekey", False, before, before, notes)
    if "forecast_id" not in _columns(con, "analysis.forecast"):
        raise RuntimeError(
            "analysis.forecast has already lost forecast_id, so the natural key "
            "cannot be recovered by join. forecast_outcome_rekey had to run "
            "FIRST. Restore from the pre-migration backup.")
    orphans = con.execute("""
        SELECT count(*) FROM analysis.forecast_outcome o
        LEFT JOIN analysis.forecast f ON f.forecast_id = o.forecast_id
        WHERE f.forecast_id IS NULL""").fetchone()[0]
    if orphans:
        notes.append(f"WARNING {orphans:,} outcome rows have no matching "
                     f"forecast row — they CANNOT be re-keyed and would be "
                     f"lost. Resolve before applying.")
        if apply:
            raise RuntimeError(
                f"{orphans:,} orphaned forecast_outcome rows; refusing to "
                f"rebuild and silently drop them")
    if not apply:
        notes.append("DRY RUN — expect an identical row count")
        return Result("forecast_outcome_rekey", False, before, before, notes)

    # Column for column with sql/028's CREATE TABLE.
    ddl = """
        CREATE TABLE __TARGET__ (
            issued_month      VARCHAR NOT NULL,
            model_version     VARCHAR NOT NULL,
            address_id        VARCHAR NOT NULL,
            category          VARCHAR NOT NULL,
            scored_month      VARCHAR NOT NULL,
            horizon_elapsed   INTEGER NOT NULL,
            realized_openings INTEGER NOT NULL,
            realized_flag     BOOLEAN NOT NULL,
            scored_at         TIMESTAMP NOT NULL,
            PRIMARY KEY (issued_month, model_version, address_id, category,
                         scored_month)
        )"""
    select = """
        (issued_month, model_version, address_id, category, scored_month,
         horizon_elapsed, realized_openings, realized_flag, scored_at)
        SELECT f.issued_month, f.model_version, f.address_id, f.category,
               o.scored_month, o.horizon_elapsed, o.realized_openings,
               o.realized_flag, o.scored_at
        FROM analysis.forecast_outcome o
        JOIN analysis.forecast f ON f.forecast_id = o.forecast_id"""
    _swap(con, "analysis.forecast_outcome", ddl, select, notes)
    after = {"analysis.forecast_outcome": _count(con, "analysis.forecast_outcome")}
    return Result("forecast_outcome_rekey", True, before, after, notes)


def probe_scope_checks(con) -> bool:
    return all(_has_check(con, t) for t in SCREEN_TABLES)


def step_scope_checks(con, apply: bool) -> Result:
    """Put CHECK (borough IN ('MN','BK')) on the screen tables.

    DuckDB has no ALTER TABLE ADD CONSTRAINT, so each is a rebuild. Every one of
    these holds MN+BK only TODAY: the CHECK records a fact, it does not change
    one, and any row moved by this step is a bug. `_swap` asserts the count.

    NOT DONE HERE, deliberately: analysis.poi_presence, chains.brand_location,
    analysis.licence_interval and staging.alcohol_licences keep all five
    boroughs. They are SUPPLY, read spatially, and reach crosses borough lines --
    a pharmacy 200 m away in Queens is real supply for a Bushwick address.
    Constraining them would delete it and manufacture a gap. sql/045's header
    argues this in full.
    """
    notes: list[str] = []
    before = {t: _count(con, t) for t in SCREEN_TABLES}
    out_of_scope = {
        t: con.execute(
            f"SELECT count(*) FROM {t} "
            f"WHERE borough IS NULL OR borough NOT IN ('MN', 'BK')").fetchone()[0]
        for t in SCREEN_TABLES}
    bad = {t: n for t, n in out_of_scope.items() if n}
    if bad:
        notes.append(f"REFUSING: out-of-scope rows present {bad} — the CHECK "
                     f"would reject them. Investigate before applying; do not "
                     f"delete them to make the constraint fit.")
        if apply:
            raise RuntimeError(f"out-of-scope rows in {sorted(bad)}")
    if probe_scope_checks(con):
        notes.append("already applied — no-op")
        return Result("scope_checks", False, before, before, notes)
    if not apply:
        notes.append("DRY RUN — every table above must keep an IDENTICAL count")
        return Result("scope_checks", False, before, before, notes)

    for table, key in SCREEN_TABLES.items():
        cols = _columns(con, table)
        body = _coldefs(con, table, check_borough=True)
        pk = f",\n            PRIMARY KEY ({key})" if key else ""
        ddl = f"CREATE TABLE __TARGET__ (\n            {body}{pk}\n        )"
        names = ", ".join(cols)
        _swap(con, table, ddl, f"({names}) SELECT {names} FROM {table}", notes)
    after = {t: _count(con, t) for t in SCREEN_TABLES}
    return Result("scope_checks", True, before, after, notes)


def probe_address_order(con) -> bool:
    return all(_has_check(con, t) for t in ORDERED_TABLES)


def step_address_order(con, apply: bool) -> Result:
    """Rebuild analysis.address and address_category physically ordered.

    DuckDB prunes row groups by zonemap (per-group min/max). On an unsorted
    table the min/max of address_id in every group spans the whole domain, so a
    single-address predicate prunes nothing and the audit measured 89,510
    descents over 332,041 rows for ONE report. Sorted on address_id, a
    single-address lookup touches one row group.

    The CHECK goes on in the same rebuild -- there is no reason to rewrite these
    two tables twice.
    """
    notes: list[str] = []
    before = {t: _count(con, t) for t in ORDERED_TABLES}
    if probe_address_order(con):
        notes.append("already applied — no-op")
        return Result("address_order", False, before, before, notes)
    if not apply:
        notes.append("DRY RUN — counts must be IDENTICAL; this step changes "
                     "physical order and constraints only, never a value")
        return Result("address_order", False, before, before, notes)

    for table, (order_by, key) in ORDERED_TABLES.items():
        cols = _columns(con, table)
        body = _coldefs(con, table, check_borough=True)
        ddl = (f"CREATE TABLE __TARGET__ (\n            {body},\n"
               f"            PRIMARY KEY ({key})\n        )")
        names = ", ".join(cols)
        _swap(con, table, ddl,
              f"({names}) SELECT {names} FROM {table} ORDER BY {order_by}", notes)
    after = {t: _count(con, t) for t in ORDERED_TABLES}
    return Result("address_order", True, before, after, notes)


def probe_demographics_clip(con) -> bool:
    return con.execute("""
        SELECT count(*) FROM analysis.address_demographics d
        LEFT JOIN analysis.address a USING (address_id)
        WHERE a.address_id IS NULL""").fetchone()[0] == 0


def step_demographics_clip(con, apply: bool) -> Result:
    """Remove address_demographics rows with no address (audit finding 15).

    767,337 rows over a 332,041-address universe: 485,495 orphans left behind
    when D78 pruned the screen to MN+BK but not the demographics table built on
    the unclipped five-borough PLUTO universe.

    This is a DELETE, not a rebuild, and it is safe in a way the others are not:
    every row removed is unreachable from analysis.address by definition, so no
    join can lose a value. The reverse is the risk and it is checked -- an
    in-universe address whose demographics vanish would read as a NULL
    neighbourhood, which the screen would score as an absence.
    """
    notes: list[str] = []
    before = {"analysis.address_demographics": _count(con, "analysis.address_demographics")}
    orphans = con.execute("""
        SELECT count(*) FROM analysis.address_demographics d
        LEFT JOIN analysis.address a USING (address_id)
        WHERE a.address_id IS NULL""").fetchone()[0]
    covered = con.execute("""
        SELECT count(*) FROM analysis.address a
        JOIN analysis.address_demographics d USING (address_id)""").fetchone()[0]
    notes.append(f"{orphans:,} orphan rows; {covered:,} in-universe rows retained")
    if not orphans:
        notes.append("already applied — no-op")
        return Result("demographics_clip", False, before, before, notes)
    if not apply:
        notes.append(f"DRY RUN — expect {before['analysis.address_demographics']:,}"
                     f" -> {before['analysis.address_demographics'] - orphans:,}")
        return Result("demographics_clip", False, before, before, notes)

    con.execute("""
        DELETE FROM analysis.address_demographics
        WHERE address_id NOT IN (SELECT address_id FROM analysis.address)""")
    after = {"analysis.address_demographics": _count(con, "analysis.address_demographics")}
    if after["analysis.address_demographics"] != covered:
        raise RuntimeError(
            f"clip left {after['analysis.address_demographics']:,} rows but "
            f"{covered:,} were in-universe — a covered address lost its "
            f"demographics. Restore from backup.")
    notes.append(f"clipped to {after['analysis.address_demographics']:,}")
    return Result("demographics_clip", True, before, after, notes)


def probe_poi_presence_vocab(con) -> bool:
    return con.execute("""
        SELECT count(*) FROM analysis.poi_presence
        WHERE borough IN ('Manhattan', 'Brooklyn', 'Queens', 'Bronx',
                          'Staten Island')""").fetchone()[0] == 0


def step_poi_presence_vocab(con, apply: bool) -> Result:
    """One borough vocabulary: rewrite poi_presence.borough to codes.

    analysis.poi_presence is the LAST long-form carrier in analysis.* other than
    analysis.hex, which is calib-layer and moves with that layer. Two spellings
    for one dimension with no FK is how a join silently returns nothing.

    NULL boroughs (63,872) stay NULL. A POI whose hex is not in analysis.hex has
    an UNKNOWN borough, not an out-of-scope one, and it is still supply.
    """
    notes: list[str] = []
    before = {"long_form": con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE borough IN "
        "('Manhattan','Brooklyn','Queens','Bronx','Staten Island')").fetchone()[0]}
    nulls = con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE borough IS NULL").fetchone()[0]
    notes.append(f"{nulls:,} NULL boroughs retained as NULL (unknown, not out of scope)")
    if not before["long_form"]:
        notes.append("already applied — no-op")
        return Result("poi_presence_vocab", False, before, before, notes)
    if not apply:
        notes.append(f"DRY RUN — {before['long_form']:,} rows rewritten to codes")
        return Result("poi_presence_vocab", False, before, before, notes)

    con.execute("""
        UPDATE analysis.poi_presence p
        SET borough = b.borough_code
        FROM analysis.borough b
        WHERE p.borough = b.borough_name""")
    after = {"long_form": con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE borough IN "
        "('Manhattan','Brooklyn','Queens','Bronx','Staten Island')").fetchone()[0]}
    return Result("poi_presence_vocab", True, before, after, notes)


def step_reclaim(con_path: pathlib.Path, apply: bool) -> Result:
    """Reclaim the file. NEEDS EVERY PEER QUIET — no exceptions.

    DuckDB NEVER shrinks a database file. The audit measured 7.6 GiB on disk
    against 2,932 MiB of live segments: ~4.3 GiB unreclaimed. `VACUUM` is
    accepted by the parser and does NOT reclaim (verified, 1.5.5). The only
    mechanism is to write a fresh file:

        ATTACH '<new>' AS fresh;  COPY FROM DATABASE <old> TO fresh;  DETACH;

    This takes an exclusive read of every table and writes a complete second
    copy, so it needs (a) no other process holding the file, and (b) free disk
    for old + new simultaneously. It is the ONLY step here that cannot share the
    warehouse with a running ingest, and it must be the LAST step so it reclaims
    the space the column drops freed.

    The swap itself is a file move, done OUTSIDE the database, and the original
    is kept until the new file has been opened and its object count verified.
    """
    notes: list[str] = []
    con_path = pathlib.Path(con_path)
    size_before = con_path.stat().st_size if con_path.exists() else 0
    before = {"file_bytes": size_before}
    notes.append(f"file is {size_before / 2**20:,.1f} MiB")
    free = shutil.disk_usage(con_path.parent).free
    notes.append(f"{free / 2**30:,.1f} GiB free; a full copy needs "
                 f"~{size_before / 2**30:,.1f} GiB of headroom")
    if free < size_before:
        notes.append("REFUSING: not enough free disk for old + new")
        if apply:
            raise RuntimeError("insufficient disk headroom for reclaim")
    if not apply:
        notes.append("DRY RUN — expect ~7.6 GiB -> ~2.0 GiB after the column "
                     "drops; NEEDS EVERY PEER QUIET")
        return Result("reclaim", False, before, before, notes)
    raise NotImplementedError(
        "reclaim is a Phase B operator step, run by hand with every peer "
        "confirmed quiet and a verified backup. See the Phase B plan; this "
        "function deliberately refuses to fire from a scripted sweep.")


def probe_classify(con) -> bool:
    from loci import warehouse as wh
    return not [o for o in wh.catalog(con) if not o.layer]


def step_classify(con, apply: bool) -> Result:
    """Write every object's layer, grain and key into the catalog.

    MUST RUN LAST, and must be re-run after ANY session that re-renders a view:
    `CREATE OR REPLACE VIEW` drops the view's comment (verified, DuckDB 1.5.5)
    and `db.init_schema` re-renders views on every session. `loci
    check-warehouse` is what tells you it has gone stale.

    An object in the database with no entry in warehouse.CLASSIFICATION is
    reported and is a FAILURE -- that is "inventory before adding a table"
    (owner, 2026-09-09) made mechanical.
    """
    from loci import warehouse as wh

    notes: list[str] = []
    objects = wh.catalog(con)
    before = {"objects": len(objects),
              "classified": sum(1 for o in objects if o.layer)}
    undeclared = sorted(o.qualified for o in objects
                        if o.qualified not in wh.CLASSIFICATION)
    if undeclared:
        notes.append("UNDECLARED — add to warehouse.CLASSIFICATION: "
                     + ", ".join(undeclared))
    if not apply:
        notes.append(f"DRY RUN — would comment {before['objects'] - len(undeclared)} "
                     f"of {before['objects']} objects")
        return Result("classify", False, before, before, notes)

    n, absent, undeclared = wh.apply_classification(con)
    notes.append(f"{n} objects commented")
    if absent:
        notes.append("declared but not present (fine for ingest-created "
                     "tables whose ingest has not run): " + ", ".join(absent))
    if undeclared:
        raise RuntimeError(
            "these objects exist with no entry in warehouse.CLASSIFICATION: "
            + ", ".join(undeclared)
            + " — add them, then re-run. Inventory before adding a table.")
    objects = wh.catalog(con)
    after = {"objects": len(objects),
             "classified": sum(1 for o in objects if o.layer)}
    return Result("classify", True, before, after, notes)


def _observation_check_text(con) -> str:
    return con.execute(
        "SELECT coalesce(string_agg(constraint_text, ' '), '') FROM duckdb_constraints() "
        "WHERE schema_name = 'analysis' AND table_name = 'address_observation' "
        "AND constraint_type = 'CHECK' AND constraint_text ILIKE '%category_guess%'"
    ).fetchone()[0]


def probe_observation_category_check(con) -> bool:
    """Does analysis.address_observation's category_guess CHECK name EVERY
    registered slug? Reads the constraint text itself, not "some CHECK exists"
    (the false-green `_has_check` learned the hard way, above)."""
    from loci.categories import CATEGORIES
    text = _observation_check_text(con)
    return all(f"'{slug}'" in text for slug in CATEGORIES)


def _observation_create_ddl() -> str:
    """The CREATE TABLE statement from sql/036, verbatim, retargeted for a
    rebuild. ONE source of DDL: 036 is what a fresh warehouse gets, and this
    step is how an existing warehouse catches up with it."""
    import re
    from loci.db import SQL_DIR
    text = (SQL_DIR / "036_address_observation.sql").read_text()
    m = re.search(r"CREATE TABLE IF NOT EXISTS analysis\.address_observation \((.*?)\n\);",
                  text, re.S)
    if not m:
        raise RuntimeError("sql/036: CREATE TABLE analysis.address_observation not found")
    body = m.group(1)
    # price_label was ALTER-added at the END of the live table (036's D105
    # note) but sits mid-list in the literal; the INSERT below names columns,
    # so order is irrelevant here.
    return f"CREATE TABLE __TARGET__ ({body}\n)"


def _reapply_036(con) -> None:
    """Re-run sql/036 after the swap: the indexes died with the old table and
    the miss view must be re-bound. Idempotent (IF NOT EXISTS / OR REPLACE)."""
    from loci.db import SQL_DIR
    con.execute((SQL_DIR / "036_address_observation.sql").read_text())


def step_observation_category_check(con, apply: bool) -> Result:
    """Widen analysis.address_observation.category_guess's CHECK to the current
    registry (GTM-198: `bathhouse_sauna`, 2026-09-17).

    sql/036 wrote the fifteen slugs literally into the CHECK, so a ground-truth
    session that reads a bathhouse at a Gowanus anchor cannot be recorded
    until the table is rebuilt -- DuckDB cannot ALTER a CHECK, so this is the
    CREATE-INSERT-count-DROP-RENAME of `_swap`, from 036's own DDL. It does
    NOT move the supply hash (address_observation is outside
    canonical_poi_sql's universe) but it rewrites a table other sessions may
    be INSERTing into: run at the ingest step, announced, never on landing.
    036 is then re-applied so its indexes and the miss view come back.
    """
    notes: list[str] = []
    rel = "analysis.address_observation"
    before = {"rows": _count(con, rel)}
    if probe_observation_category_check(con):
        notes.append("already applied — the CHECK names every registered slug")
        return Result("observation_category_check", False, before, before, notes)
    if not apply:
        notes.append(f"DRY RUN — would rebuild {rel} ({before['rows']:,} rows) with "
                     "the widened category_guess CHECK from sql/036")
        return Result("observation_category_check", False, before, before, notes)

    cols = ", ".join(_columns(con, rel))
    _swap(con, rel, _observation_create_ddl(),
          f"({cols}) SELECT {cols} FROM {rel}", notes)
    _reapply_036(con)
    if not probe_observation_category_check(con):
        raise RuntimeError("rebuild ran but the CHECK still lacks a registered slug")
    after = {"rows": _count(con, rel)}
    return Result("observation_category_check", True, before, after, notes)


#: Order matters. forecast_outcome_rekey MUST precede forecast_slim (it
#: recovers the natural key by joining on forecast_id, which forecast_slim
#: deletes). `classify` MUST be last -- every step above changes the catalog.
STEPS: dict[str, typing.Callable] = {
    "forecast_outcome_rekey": step_forecast_outcome_rekey,
    "forecast_slim": step_forecast_slim,
    "scope_checks": step_scope_checks,
    "address_order": step_address_order,
    "demographics_clip": step_demographics_clip,
    "poi_presence_vocab": step_poi_presence_vocab,
    "observation_category_check": step_observation_category_check,
    "classify": step_classify,
}
