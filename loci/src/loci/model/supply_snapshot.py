"""Frozen rewind snapshots: `analysis.supply_snapshot` + its census view.

sql/049_supply_snapshot.sql carries the rationale. The one thing this module
must never do is grow a second definition of "existed at t0": the row set is
`validation.retrodiction.supply_as_of_sql` verbatim, and
tests/test_supply_snapshot.py pins that a snapshot's per-category counts
equal `supply_as_of`'s for the same t0.

`DEFAULT_T0S` are the ten January firsts 2016-2025 the rewind reads. Any
other t0 is allowed (`--t0`), and each build replaces only its own t0.
"""
from __future__ import annotations

import datetime as dt

TABLE = "analysis.supply_snapshot"
CENSUS_VIEW = "analysis.supply_snapshot_census"

DEFAULT_T0S: tuple[dt.date, ...] = tuple(dt.date(y, 1, 1) for y in range(2016, 2026))
BBL_RADIUS_M = 30.0


def build(con, t0: dt.date, *, include_censored: bool = True) -> dict:
    """Materialise the t0 set. Replaces existing rows for that t0."""
    from loci.db import METRES_SQL
    from loci.score.supply import supply_hash
    from loci.validation.retrodiction import supply_as_of_sql

    h = supply_hash(con)
    con.execute("CREATE OR REPLACE TEMP TABLE _snap AS "
                + supply_as_of_sql(t0, include_censored=include_censored, with_closure=True))
    n = con.execute("SELECT count(*) FROM _snap").fetchone()[0]
    if not n:
        raise RuntimeError(
            f"supply_snapshot: the t0={t0} set is EMPTY. The ledger has no dated "
            f"or censored row at all before that date -- that is a missing "
            f"first-seen ledger, not a city with no shops. Refusing to write.")
    metres = METRES_SQL.format(a="ST_Point(s.lon, s.lat)", b="ST_Point(a.lon, a.lat)")
    con.execute("BEGIN")
    try:
        con.execute(f"DELETE FROM {TABLE} WHERE t0 = ?", [t0])
        con.execute(f"""
            INSERT INTO {TABLE} (
                t0, location_key, category, borough, bbl, bbl_m, lon, lat,
                status_at_t0, first_seen_kind, first_seen_src_date, closed_on,
                censored, supply_hash, built_at)
            WITH lot AS (
                SELECT s.location_key, a.bbl, {metres} AS m
                FROM _snap s
                JOIN analysis.address a
                  ON a.frame = 'lot' AND a.bbl IS NOT NULL
                 AND a.lon BETWEEN s.lon - 0.0006 AND s.lon + 0.0006
                 AND a.lat BETWEEN s.lat - 0.0005 AND s.lat + 0.0005
                 AND {metres} <= {BBL_RADIUS_M}
                QUALIFY row_number() OVER (PARTITION BY s.location_key
                                           ORDER BY {metres}, a.bbl) = 1
            )
            SELECT DATE '{t0.isoformat()}', s.location_key, s.category, s.borough,
                   l.bbl, l.m, s.lon, s.lat,
                   CASE WHEN s.closed_on IS NOT NULL AND s.closed_on <= DATE '{t0.isoformat()}'
                        THEN 'closed' ELSE 'open' END,
                   s.first_seen_kind, s.first_seen_src_date, s.closed_on,
                   s.first_seen_kind = 'backfill_censored',
                   '{h}', now()
            FROM _snap s
            LEFT JOIN lot l USING (location_key)
        """)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return census(con, t0)


def census(con, t0: dt.date | None = None) -> dict:
    """Per-(t0, category) census; the ALL row is category NULL."""
    where = "WHERE t0 = ?" if t0 else "WHERE t0 IS NOT NULL"
    params = [t0] if t0 else []
    # `t0` is fetched as its ISO string: fetchdf() renders a DATE as a
    # pandas Timestamp whose isoformat() carries 'T00:00:00'.
    df = con.execute(
        f"SELECT strftime(t0, '%Y-%m-%d') AS t0_iso, * FROM {CENSUS_VIEW} {where} "
        f"ORDER BY t0, category NULLS FIRST", params).fetchdf()
    out: dict = {}
    for _, r in df.iterrows():
        key = r["t0_iso"]
        cat = r["category"] if isinstance(r["category"], str) else "ALL"
        out.setdefault(key, {})[cat] = {
            "n": int(r["n"]), "n_censored": int(r["n_censored"]),
            "censored_share": float(r["censored_share"]),
            "n_closed_before_t0": int(r["n_closed_before_t0"]),
            "n_without_bbl": int(r["n_without_bbl"]),
            "supply_hash": r["supply_hash"], "n_hashes": int(r["n_hashes"]),
        }
    return out


def validate(con, t0: dt.date) -> list[str]:
    """Prove the snapshot equals the live rule for this t0, on the warehouse."""
    from loci.validation.retrodiction import supply_as_of_sql
    problems: list[str] = []
    live = dict(con.execute(
        f"SELECT category, count(*) FROM ({supply_as_of_sql(t0)}) GROUP BY 1").fetchall())
    snap = dict(con.execute(
        f"SELECT category, count(*) FROM {TABLE} WHERE t0 = ? GROUP BY 1", [t0]).fetchall())
    for c in sorted(set(live) | set(snap)):
        if live.get(c, 0) != snap.get(c, 0):
            problems.append(f"t0={t0} {c}: snapshot {snap.get(c, 0):,} != live rule "
                            f"{live.get(c, 0):,}")
    hashes = con.execute(
        f"SELECT count(DISTINCT supply_hash) FROM {TABLE} WHERE t0 = ?", [t0]).fetchone()[0]
    if hashes > 1:
        problems.append(f"t0={t0} carries {hashes} supply hashes -- rebuilt under two sets")
    return problems
