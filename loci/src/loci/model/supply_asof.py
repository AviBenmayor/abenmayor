"""THE SUPPLY AS-OF DATE -- the one date the open/closed predicate is evaluated
at, stored with the baseline instead of being read off the wall clock.

Owner ruling 2026-09-16: "the supply hash and poi open status must take an
explicit as-of date stored with the baseline, so the hash moves only on real
evidence writes; advancing the date becomes a named step in the canonical
order."

WHAT WENT WRONG
---------------
`model/poi_presence.poi_is_open()` defaulted its `today` argument to the SQL
literal `current_date`, and `colocation_view_sql()` baked that into
`analysis.poi_supply_status`. A DuckDB view's `current_date` is evaluated at
QUERY time, not at CREATE time, so the view answered a different question every
midnight. `score/supply.supply_hash()` hashes the per-category counts of that
view, so the hash moved at the 2026-09-16 date roll with NO write to the
warehouse at all:

    supply_hash at asof 2026-09-15  ->  ba944e18c57b   (the D112 re-baseline)
    supply_hash at asof 2026-09-16  ->  18eb5ab24629   (the live drift)

Twelve POIs changed verdict between those two days: nine NYS DOS appearance-
enhancement licences whose `expires` is exactly 2026-09-15 (`expiry < today`
became true), which flipped open -> closed and left the supply set, and three
DOHMH restaurants whose last inspection crossed OPEN_EVIDENCE_MAX_AGE_DAYS at
724 -> 732 days, which flipped open -> unknown and STAYED in supply (the gate
fires on 'closed' only). Nothing was ingested, verified or written.

That is a real property of the licences -- a licence that lapsed yesterday is
lapsed -- but it is NOT a property of the warehouse, and a hash that moves
without a write destroys the one signal the freeze protocol (D96/D106) rests
on: "the hash moved, so somebody wrote evidence, so every stamped artefact is
now a vintage behind." Four re-baselines in one night were chased that way.

THE PIN
-------
One date, in two places that must agree:

  * `analysis.supply_asof` -- a ONE-ROW table in the warehouse. Every SQL
    rendering of the predicate reads it through `ASOF_SQL`, so the view no
    longer contains a clock and advancing the date is an UPDATE, not a view
    re-render. (A view re-render is itself a hash-moving event -- D106.)
  * `supply_asof:` in `model/supply_baseline.yaml` -- written by
    `loci supply-ratio --fit-baseline` from the table, so the file on disk
    records the date the norm was fitted at. `check()` fails loud when the two
    disagree, because a baseline fitted at one asof and ratios computed at
    another mix two supply sets exactly as a moved `supply_hash` does.

`asof:` (already in the YAML) is the WALL-CLOCK day the fit RAN. It is a
provenance stamp and is deliberately left alone. `supply_asof:` is the date the
PREDICATE was evaluated at. On the 2026-09-15 baseline they coincide; they will
not always, and conflating them is how the pin would quietly come undone.

ADVANCING THE DATE IS A HASH-MOVING EVENT
-----------------------------------------
THE CANONICAL ORDER RUNS AT THE BASELINE'S ASOF. Advancing the asof is a
NAMED STEP -- `loci supply-asof advance` -- that runs BEFORE step 01
(`supply-ratio --fit-baseline`), never in the middle, and it must be announced
to every peer session exactly like a `poi_status` write, because it moves the
shared supply hash for every one of them. It is not a refresh and it is not
free: it re-reads every licence expiry and every inspection age against a later
day, so licences lapse and evidence ages out, and every stamped artefact
(baseline, address_gaps, revenue, forecast vintage, webmap meta.json) is a
vintage behind until the order is re-run. Run it deliberately, on a quiet
warehouse, and then re-run the order -- the D106 discipline, applied to the
clock instead of to a closure verdict.

`advance` refuses while a freeze marker is set (`data/SUPPLY_FREEZE`, or the
env var `LOCI_SUPPLY_FREEZE`). No such marker existed before this module: the
"a final hash freezes poi_status writes" rule of D96/D106 was a human protocol
with nothing to enforce it. This is the first mechanical form of it, and it is
honoured by THIS command only -- it does not stop a direct write to
`analysis.poi_closure_evidence`, and claiming otherwise would be worse than
having no marker.

CAVEATS THE DATABASE CANNOT ENFORCE
-----------------------------------
 1. A PINNED ASOF GOES STALE ON PURPOSE. Holding 2026-09-15 for three months
    means three months of licence lapses are not seen. That is the trade: a
    reproducible supply set that moves when a human moves it, against a set
    that drifts nightly. The answer is to ADVANCE ON A SCHEDULE (with the
    canonical order behind it), not to unpin the date.
 2. THE PIN IS ON THE PREDICATE, NOT ON THE DATA. `observed_on`,
    `last_inspection_date` and `expires` still come from whatever the last
    ingest pulled. Advancing the asof without re-ingesting ages the same
    evidence; re-ingesting without advancing reads fresher evidence at an old
    date. Both are legitimate; neither is the other.
 3. `supply_asof` IS NOT IN THE HASH BLOB, deliberately. Adding it would change
    every historical hash and `ba944e18c57b` would no longer be reproducible --
    the one fact that proves this change is inert. The asof is carried beside
    the hash in the YAML instead.
 4. THE ONE-ROW TABLE IS ENFORCED BY CONVENTION plus a PRIMARY KEY on a
    constant column. DuckDB will not stop a second row from being inserted with
    a different `pin`; `read()` raises rather than picking one.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib

#: The one-row table. Qualified, because every SQL rendering embeds it.
TABLE = "analysis.supply_asof"

#: The SQL expression every rendering of the predicate passes as `today`.
#: A scalar subquery, so the view carries no clock and the date can be moved
#: with an UPDATE instead of a CREATE OR REPLACE VIEW (which is itself a
#: hash-moving event under D106).
ASOF_SQL = f"(SELECT asof_date FROM {TABLE})"

#: Where the freeze marker lives. A file, so it survives a process and is
#: visible to a human in `ls`. `LOCI_SUPPLY_FREEZE` overrides the path (or, set
#: to a non-path truthy value, freezes unconditionally -- handy in a test).
FREEZE_ENV = "LOCI_SUPPLY_FREEZE"

DDL = f"""
CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS {TABLE} (
    -- A constant PRIMARY KEY is how "exactly one row" is said in DDL. It is
    -- not a real key; it exists so a second INSERT fails loudly instead of
    -- leaving two dates in a table every view reads as a scalar.
    pin        VARCHAR PRIMARY KEY DEFAULT 'the',
    -- NOT `asof`: ASOF is a reserved word in DuckDB (ASOF JOIN) and an
    -- unquoted `SELECT asof FROM ...` is a parser error, so the scalar
    -- subquery every view embeds would not even bind.
    asof_date  DATE    NOT NULL,
    set_at     TIMESTAMP NOT NULL DEFAULT current_timestamp,
    set_by     VARCHAR,
    reason     VARCHAR
);
""".strip()


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def freeze_marker() -> pathlib.Path | None:
    """The freeze marker's path if one is SET, else None."""
    env = os.environ.get(FREEZE_ENV)
    if env:
        p = pathlib.Path(env)
        # A non-path value freezes unconditionally: `LOCI_SUPPLY_FREEZE=1`.
        return p if p.exists() or "/" in env else pathlib.Path(env)
    default = _repo_root() / "data" / "SUPPLY_FREEZE"
    return default if default.exists() else None


# --------------------------------------------------------------- the YAML

def baseline_asof(path: pathlib.Path | None = None) -> dt.date | None:
    """`supply_asof:` from model/supply_baseline.yaml, or None.

    Falls back to `asof:` for a YAML written before this field existed -- on
    the 2026-09-15 baseline the two coincide, which is why re-stamping the file
    is NOT required to land this change. Returns None rather than raising when
    the file is absent (a fresh clone, CI), because the caller that needs it to
    exist is the one that should say so.
    """
    import yaml

    from loci.model.supply_ratio import BASELINE_PATH

    p = path or BASELINE_PATH
    if not p.exists():
        return None
    doc = yaml.safe_load(p.read_text()) or {}
    raw = doc.get("supply_asof") or doc.get("asof")
    if raw is None:
        return None
    return raw if isinstance(raw, dt.date) else dt.date.fromisoformat(str(raw)[:10])


def default_today() -> dt.date:
    """The date the PYTHON twin of the predicate evaluates at when no caller
    passes one: the baseline's pinned asof, and only failing that the wall
    clock. Kept here so `poi_presence.poi_status()` and every SQL rendering
    answer the same question -- two clocks is how two renderings of one rule
    disagree."""
    return baseline_asof() or dt.date.today()


# ---------------------------------------------------------------- the table

def ensure_table(con, *, default: dt.date | None = None) -> dt.date:
    """Create `analysis.supply_asof` and seed it if empty. Idempotent.

    Seeded from the baseline YAML (`supply_asof`, else `asof`), and only on a
    warehouse with no baseline at all from the wall clock -- a fresh warehouse
    has nothing to be inconsistent with. Called by `db.init_schema` BEFORE the
    migration sweep, because `sql/029_poi_colocation.sql` binds this table by
    name at CREATE VIEW time and DuckDB resolves that immediately.
    """
    con.execute(DDL)
    row = con.execute(f"SELECT asof_date FROM {TABLE}").fetchall()
    if row:
        return row[0][0]
    seed = default or baseline_asof() or dt.date.today()
    con.execute(
        f"INSERT INTO {TABLE} (pin, asof_date, set_by, reason) VALUES ('the', ?, ?, ?)",
        [seed, "ensure_table", "seeded from model/supply_baseline.yaml"])
    return seed


def read(con) -> dt.date:
    """The pinned asof. Raises rather than falling back to `date.today()`: a
    silent fall back to the wall clock is the exact bug this module removes."""
    try:
        rows = con.execute(f"SELECT asof_date FROM {TABLE}").fetchall()
    except Exception as exc:                      # noqa: BLE001 -- CatalogException
        raise RuntimeError(
            f"{TABLE} does not exist on this warehouse. It is created by "
            f"db.init_schema (before the migration sweep) and by "
            f"sql/040_supply_asof.sql; until it does, the open/closed predicate "
            f"has no as-of date to read. Do NOT fall back to the wall clock -- "
            f"that is the drift this table removes.") from exc
    if not rows:
        raise RuntimeError(
            f"{TABLE} is empty. Every rendering of the open/closed predicate "
            f"reads it, so an empty table means poi_status is NULL for every "
            f"POI. Run `loci supply-asof show` (it seeds from "
            f"model/supply_baseline.yaml) before anything reads supply.")
    if len(rows) > 1:
        raise RuntimeError(
            f"{TABLE} holds {len(rows)} rows ({[r[0] for r in rows]}). It is a "
            f"ONE-ROW table read as a scalar subquery; picking one here would "
            f"make the supply set depend on row order.")
    return rows[0][0]


def write(con, day: dt.date, *, set_by: str = "cli", reason: str = "") -> dt.date:
    """Move the pin. WRITE -- moves the shared supply hash; announce it."""
    ensure_table(con, default=day)
    con.execute(
        f"UPDATE {TABLE} SET asof_date = ?, set_at = current_timestamp, "
        f"set_by = ?, reason = ? WHERE pin = 'the'", [day, set_by, reason])
    return read(con)


def check(con, path: pathlib.Path | None = None) -> tuple[dt.date, dt.date | None, bool]:
    """(warehouse asof, baseline YAML asof, they agree).

    Disagreement is the same class of error as a moved `supply_hash`: the norm
    was fitted with one predicate and the ratios computed with another.
    """
    live = read(con)
    doc = baseline_asof(path)
    return live, doc, (doc is not None and doc == live)


# ------------------------------------------------- hashing at another date

def pinned_supply_view(con, asof, *, name: str | None = None) -> str:
    """A TEMP VIEW of `analysis.poi_supply_status` with the asof subquery
    replaced by a DATE literal, so a hash can be computed at ANOTHER date
    WITHOUT writing (it works on a `read_only=True` connection).

    Reads the LIVE view's own SQL out of `duckdb_views()` rather than
    re-rendering from `colocation_view_sql()`: the live view is the
    `evidence=True` rendering that `db.init_schema` applies after sql/033, so
    re-rendering here would hash a DIFFERENT view than the warehouse actually
    uses and the "what would tomorrow cost" answer would be quietly wrong.
    """
    day = asof if isinstance(asof, dt.date) else dt.date.fromisoformat(str(asof)[:10])
    sql = con.execute(
        "SELECT sql FROM duckdb_views() WHERE schema_name = 'analysis' "
        "AND view_name = 'poi_supply_status'").fetchall()
    if not sql:
        raise RuntimeError(
            "analysis.poi_supply_status does not exist; run `loci init` "
            "(db.init_schema) before asking what the supply set looks like.")
    body = sql[0][0].split(" AS ", 1)[1]
    if ASOF_SQL not in body and "current_date" not in body:
        raise RuntimeError(
            "the live analysis.poi_supply_status contains neither "
            f"{ASOF_SQL} nor current_date, so its as-of date cannot be pinned. "
            "Re-apply sql/029 (db.init_schema) on this build first.")
    body = body.replace(ASOF_SQL, f"DATE '{day.isoformat()}'")
    # A warehouse still carrying the PRE-pin view (current_date baked in) is
    # handled too -- that is how the mechanism was proved read-only.
    body = body.replace("current_date", f"DATE '{day.isoformat()}'")
    view = name or "_pinned_supply_status_" + day.isoformat().replace("-", "")
    con.execute(f"CREATE OR REPLACE TEMP VIEW {view} AS {body}")
    return view


def status_flips(con, a, b) -> "object":
    """One row per (status at `a`, status at `b`, reason, n) for every POI whose
    verdict differs between the two dates. READ-ONLY.

    `reason` is read off the BASIS string rather than re-derived, so it cannot
    disagree with what the predicate actually said.
    """
    va = pinned_supply_view(con, a, name="_flip_a")
    vb = pinned_supply_view(con, b, name="_flip_b")
    return con.execute(f"""
        SELECT x.poi_status AS status_before,
               y.poi_status AS status_after,
               CASE WHEN y.poi_status_basis LIKE '%:expired\\_%' ESCAPE '\\'
                        THEN 'licence expiry lapsed'
                    WHEN y.poi_status_basis LIKE '%evidence\\_older\\_than%' ESCAPE '\\'
                        THEN 'evidence aged past the open-evidence window'
                    ELSE 'other' END AS reason,
               count(*) AS n,
               count(*) FILTER (WHERE x.in_principled) AS n_principled,
               count(*) FILTER (WHERE x.in_principled
                                AND x.poi_status <> 'closed'
                                AND y.poi_status = 'closed') AS n_leaving_supply
        FROM {va} x JOIN {vb} y USING (poi_id)
        WHERE x.poi_status IS DISTINCT FROM y.poi_status
        GROUP BY 1, 2, 3
        ORDER BY n DESC
    """).df()


def advance(con, *, to: dt.date | None = None, dry_run: bool = True,
            supply_set: str = "principled", force: bool = False,
            set_by: str = "cli", reason: str = "") -> dict:
    """THE NAMED STEP. Move the pinned asof, reporting what it costs.

    Returns a report with the hash before and after, the flip table, and the
    freeze marker if one is set. `dry_run=True` (the default) computes all of
    that and writes nothing -- it works on a read-only connection.

    Refuses while a freeze marker is set unless `force=True`, and refuses to
    move the pin BACKWARDS without `force=True` as well: an earlier asof
    un-lapses licences that really did lapse, which reads as supply appearing
    out of nowhere.
    """
    from loci.score.supply import supply_hash

    unpinned = False
    try:
        current = read(con)
    except RuntimeError:
        if not dry_run:
            raise
        # PRE-LANDING DRY RUN. On a warehouse that has not yet got the table
        # (sql/040 not applied), a dry run still has to be able to price the
        # move -- that is exactly when the lead wants to see the cost. Fall
        # back to the baseline's own as-of, and SAY SO in the report. This
        # branch is unreachable once the table exists, and it never writes.
        current = baseline_asof()
        unpinned = True
        if current is None:
            raise
    target = to or dt.date.today()
    if isinstance(target, str):
        target = dt.date.fromisoformat(target[:10])

    marker = freeze_marker()
    if marker is not None and not dry_run and not force:
        raise RuntimeError(
            f"freeze marker set ({marker}) -- refusing to advance the supply "
            f"as-of date. Advancing moves the shared supply hash for every "
            f"session, which is exactly what a freeze forbids (D96/D106). "
            f"Clear the marker, or pass --force if you are the hash steward "
            f"and have announced it.")
    if target < current and not dry_run and not force:
        raise RuntimeError(
            f"refusing to move the as-of date backwards ({current} -> {target}): "
            f"a licence that lapsed would un-lapse and supply would appear out "
            f"of nowhere. Pass --force if that is genuinely what you want.")

    before = supply_hash(con, supply_set, asof=current)
    after = supply_hash(con, supply_set, asof=target)
    flips = status_flips(con, current, target) if current != target else None

    if not dry_run and target != current:
        write(con, target, set_by=set_by, reason=reason)

    return {
        "from": current,
        "to": target,
        "hash_before": before,
        "hash_after": after,
        "moved": before != after,
        "flips": flips,
        "freeze_marker": str(marker) if marker else None,
        "dry_run": dry_run,
        "unpinned": unpinned,
        "supply_set": supply_set,
        "baseline_asof": baseline_asof(),
    }
