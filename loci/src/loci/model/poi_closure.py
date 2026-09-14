"""THE CLOSURE LEDGER (`staging.poi_closure`) -- the other end of the spell.

docs/retrodiction-2026-09.md §4 found ZERO observable closures in the whole
warehouse and named the cheapest unlock: Foursquare OS Places publishes
`date_closed`, the column is in the schema of the file already on disk, and the
fetch threw those rows away with `WHERE date_closed IS NULL`. This module loads
them, and ONLY them, into their own table.

sql/027_poi_closure.sql carries the schema rationale and the five caveats the
database cannot enforce. Read it before changing anything here. The two that
govern this file:

  * THE SUPPLY SET IS NOT TOUCHED. Nothing here writes staging.poi,
    analysis.poi_dedup or analysis.poi_supply. `FoursquarePlacesAdapter` still
    reads the OPEN cache and still `continue`s on any row with a `date_closed`.
    A closed venue counted as supply would erase the very gap the screen exists
    to find.
  * ABSENCE IS STILL NOT A CLOSURE (D79). `closed_on` is written only from a
    source-published `date_closed`. A ledger row whose `last_seen_month` falls
    behind gets NOTHING from this module, ever.

IDENTITY reuses `poi_presence.mint_key` / `name_key_of` and
`score.dedup.norm_tokens` / `names_match` / `MATCH_METERS` -- the same
functions, imported, not reimplemented. A second copy of the matching rule is
how a closure eventually gets attached to the shop next door.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import h3

from loci.model.poi_presence import mint_key, name_key_of
from loci.score.dedup import BLOCK_RES, MATCH_METERS, haversine_m, names_match, norm_tokens

SQL_027 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "027_poi_closure.sql"

TABLE = "staging.poi_closure"
SOURCE = "foursquare"

#: How a closure was attached to a ledger row, most confident first. Stored in
#: `analysis.poi_presence.closed_src`, so provenance AND mapping confidence are
#: both recoverable from the ledger alone.
MATCH_KINDS = ("foursquare:key", "foursquare:link")


def ensure_schema(con) -> None:
    """Apply sql/018 (the ledger) then sql/027 (this table + the two ALTERs).

    BOTH, in that order, and the order matters: 027 ALTERs `poi_presence`, so
    the table has to exist; and 018 re-creates `analysis.poi_first_seen` in its
    ORIGINAL, source_date-only form, so applying 027 afterwards is what puts
    `first_seen_on` for 'gov_filing' rows and `closed_on` back on the reporting
    surface. Idempotent either way."""
    from loci.model.poi_presence import ensure_schema as ensure_ledger
    ensure_ledger(con)
    con.execute(SQL_027.read_text())


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------
def load(con, *, release: str | None = None, dry_run: bool = False,
         fetched_at: dt.datetime | None = None) -> dict:
    """Load every CLOSED Foursquare NYC row into `staging.poi_closure`.

    Replaces the table wholesale (sql/027 caveat 5: one release, one snapshot --
    a later release carries more closures for the same venues, and accumulating
    them would leave stale rows that no release still asserts).

    FAILS LOUD on an empty result. A silent zero here is precisely the bug this
    module exists to undo: it would read downstream as "New York closes no
    storefronts"."""
    import pandas as pd

    from loci.sources.universal import foursquare_places as fsq

    release = release or fsq.RELEASE
    fetched_at = fetched_at or dt.datetime.now()
    ensure_schema(con)

    rows = []
    for r in fsq.iter_closed(release):
        cat = r["category"]
        lon, lat = r["lon"], r["lat"]
        if lon is None or lat is None or r["date_closed"] is None:
            continue
        nk = name_key_of(r["name"])
        # A key is minted only for a row that could ever match: the ledger holds
        # the 15 Loci categories, and `mint_key` folds a canonical poi_id into a
        # nameless row's hash (sql/018 caveat 6) which a closure does not have.
        key = mint_key(cat, nk, lon, lat) if (cat and nk) else None
        rows.append((r["fsq_place_id"], key, cat, r["name"], float(lon), float(lat),
                     r["date_created"], r["date_closed"], SOURCE, fetched_at))

    if not rows:
        raise RuntimeError(
            f"Foursquare release {release} yielded 0 closed NYC rows -- refusing to "
            "write an empty closure ledger. Either the unfiltered extract is missing "
            "(run `loci poi-closures ingest` to pull it) or the open-only filter "
            "leaked back into the fetch.")

    frame = pd.DataFrame(rows, columns=[
        "fsq_place_id", "location_key", "category", "name", "lon", "lat",
        "date_created", "date_closed", "source", "fetched_at"])
    frame = frame.drop_duplicates(subset="fsq_place_id", keep="first")

    report = {
        "release": release,
        "rows": int(len(frame)),
        "mapped": int(frame["category"].notna().sum()),
        "keyed": int(frame["location_key"].notna().sum()),
        "by_category": frame["category"].value_counts(dropna=False).to_dict(),
        "by_year": (frame["date_closed"].map(lambda d: d.year)
                    .value_counts().sort_index().to_dict()),
        "dry_run": dry_run,
    }
    if dry_run:
        return report

    con.execute("BEGIN")
    try:
        con.register("_closure_in", frame)
        con.execute(f"DELETE FROM {TABLE}")
        con.execute(f"INSERT INTO {TABLE} SELECT * FROM _closure_in")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_closure_in")
    return report


# ---------------------------------------------------------------------------
# the match
# ---------------------------------------------------------------------------
def resolve(con) -> "object":
    """Attach each closure to at most one ledger row. Returns a DataFrame of
    (location_key, closed_on, closed_src), one row per LEDGER location.

    Two passes, the ledger's own order of confidence:
      1. exact `location_key`  -> 'foursquare:key'
      2. same category, `names_match`, within MATCH_METERS (40 m), H3 res-11
         blocked, nearest wins                         -> 'foursquare:link'

    PRECEDENCE, where several closures land on one ledger row: the EARLIEST
    `date_closed` wins, and a key match beats a link match on a tie. Earliest is
    the conservative direction -- it can only shorten an observed spell, never
    invent survival. Unlike `link_to_ledger` this pass is NOT one-to-one in the
    other direction: three closed tenants of one address may all match one
    ledger row, and the earliest is the one kept."""
    import numpy as np
    import pandas as pd

    clo = con.execute(
        f"SELECT fsq_place_id, location_key, category, name, lon, lat, date_closed "
        f"FROM {TABLE} WHERE category IS NOT NULL").fetchdf()
    led = con.execute(
        "SELECT location_key, category, display_name, lon, lat "
        "FROM analysis.poi_presence").fetchdf()
    if clo.empty or led.empty:
        return pd.DataFrame(columns=["location_key", "closed_on", "closed_src"])

    known = set(led["location_key"])
    hits: list[tuple[str, object, str]] = []

    # ---- pass 1: exact key
    is_key = clo["location_key"].isin(known) & clo["location_key"].notna()
    for k, d in zip(clo.loc[is_key, "location_key"], clo.loc[is_key, "date_closed"],
                    strict=True):
        hits.append((k, d, "foursquare:key"))

    # ---- pass 2: name + distance, against the WHOLE ledger (a closure that
    # matched by key is done; the rest may still be the same storefront under a
    # coordinate that rounded across a 4 dp boundary, which is exactly what
    # sql/018's pass B exists to absorb).
    todo = clo.loc[~is_key].reset_index(drop=True)
    if len(todo):
        lk = led["location_key"].to_numpy()
        lcat = led["category"].to_numpy()
        llat = led["lat"].to_numpy(dtype=float)
        llon = led["lon"].to_numpy(dtype=float)
        ltok = [norm_tokens(s) for s in led["display_name"]]

        cells: dict[str, list[int]] = {}
        for j in range(len(led)):
            if not (np.isfinite(llat[j]) and np.isfinite(llon[j])):
                continue
            cells.setdefault(h3.latlng_to_cell(llat[j], llon[j], BLOCK_RES), []).append(j)

        for i in range(len(todo)):
            lat_i, lon_i = float(todo["lat"].iat[i]), float(todo["lon"].iat[i])
            tok_i = norm_tokens(todo["name"].iat[i])
            if not tok_i:          # names_match refuses an empty token set
                continue
            cat_i = todo["category"].iat[i]
            best, best_d = None, MATCH_METERS + 1.0
            for cell in h3.grid_disk(h3.latlng_to_cell(lat_i, lon_i, BLOCK_RES), 1):
                for j in cells.get(cell, ()):
                    if lcat[j] != cat_i or not names_match(tok_i, ltok[j]):
                        continue
                    d = haversine_m(lat_i, lon_i, llat[j], llon[j])
                    if d <= MATCH_METERS and d < best_d:
                        best, best_d = j, d
            if best is not None:
                hits.append((lk[best], todo["date_closed"].iat[i], "foursquare:link"))

    if not hits:
        return pd.DataFrame(columns=["location_key", "closed_on", "closed_src"])

    out = pd.DataFrame(hits, columns=["location_key", "closed_on", "closed_src"])
    out["_rank"] = out["closed_src"].map({k: i for i, k in enumerate(MATCH_KINDS)})
    out = (out.sort_values(["location_key", "closed_on", "_rank"])
              .drop_duplicates(subset="location_key", keep="first")
              .drop(columns="_rank")
              .reset_index(drop=True))
    return out


def apply_to_ledger(con, *, dry_run: bool = False) -> dict:
    """Fill `analysis.poi_presence.closed_on` / `closed_src` FROM THIS TABLE.

    Called by `loci poi-snapshot` on every run. IDEMPOTENT: it clears both
    columns and re-derives them, so a closure Foursquare retracts disappears
    instead of being frozen into the ledger, and a re-run changes nothing.

    THE COLUMNS ARE NEVER WRITTEN FROM THE ABSENCE OF A SNAPSHOT ROW (D79).
    There is no code path in this module that reads `last_seen_month`."""
    resolved = resolve(con)
    report = {
        "ledger_rows": con.execute(
            "SELECT count(*) FROM analysis.poi_presence").fetchone()[0],
        "matched": int(len(resolved)),
        "by_src": resolved["closed_src"].value_counts().to_dict() if len(resolved) else {},
        "dry_run": dry_run,
    }
    if dry_run:
        return report

    con.execute("BEGIN")
    try:
        con.execute("UPDATE analysis.poi_presence SET closed_on = NULL, closed_src = NULL")
        if len(resolved):
            con.register("_closure_hit", resolved)
            con.execute("""
                UPDATE analysis.poi_presence AS pp
                SET closed_on = h.closed_on, closed_src = h.closed_src
                FROM _closure_hit h
                WHERE h.location_key = pp.location_key""")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        try:
            con.unregister("_closure_hit")
        except Exception:       # noqa: BLE001 -- never registered on an empty match
            pass
    report["written"] = int(con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE closed_on IS NOT NULL"
    ).fetchone()[0])
    return report


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def stats(con) -> dict:
    """Counts for `loci poi-closures stats`. Read-only."""
    out: dict = {}
    out["closures"] = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    out["mapped"] = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE category IS NOT NULL").fetchone()[0]
    out["by_year"] = con.execute(
        f"SELECT year(date_closed) AS yr, count(*) FROM {TABLE} "
        "WHERE category IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()
    out["by_category"] = con.execute(
        f"SELECT category, count(*) FROM {TABLE} WHERE category IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC").fetchall()
    out["ledger_rows"] = con.execute(
        "SELECT count(*) FROM analysis.poi_presence").fetchone()[0]
    out["ledger_closed"] = con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE closed_on IS NOT NULL"
    ).fetchone()[0]
    out["ledger_closed_by_category"] = con.execute(
        "SELECT category, count(*) FILTER (WHERE closed_on IS NOT NULL), count(*) "
        "FROM analysis.poi_presence GROUP BY 1 ORDER BY 2 DESC").fetchall()
    out["ledger_closed_by_kind"] = con.execute(
        "SELECT first_seen_kind, count(*) FILTER (WHERE closed_on IS NOT NULL), count(*) "
        "FROM analysis.poi_presence GROUP BY 1 ORDER BY 1").fetchall()
    out["unmatched"] = con.execute(f"""
        SELECT count(*) FROM {TABLE} c
        WHERE c.category IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM analysis.poi_presence pp
                          WHERE pp.location_key = c.location_key)""").fetchone()[0]
    return out
