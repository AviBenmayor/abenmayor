"""The FIRST-SEEN LEDGER (`analysis.poi_presence`) -- Loci's own observation
history for every deduplicated storefront location.

Owner's ask (2026-09-13): "make sure moving forward we have dates on which
month data was first seen for storefronts." The point is that this must NOT
depend on a source publishing an open date. Most do not: of the nine POI
feeds, four carry a usable first-seen and five carry none at all, which is why
`chains.brand_snapshot.locations_new_12m` has always been a floor over a 60%
subset. A ledger we write ourselves, every month, is the measure that needs no
source's cooperation.

sql/018_poi_presence.sql carries the schema rationale: why this is a new table
under the D61 inventory rule, why `location_key` is not `cluster_id`, what the
`first_seen_kind` values mean, and the five caveats the database cannot
enforce. Read it before changing anything here.

A FOURTH KIND, 'gov_filing', was added by sql/020_storefront_pipeline.sql. It
is written by model/storefront_pipeline.apply_gov_filing, never by `snapshot`:
a government filing that dated an opening earlier than any POI source could,
or dated a LEFT-CENSORED row at all. It carries a real `first_seen_src_date`,
so every invariant that used to test `kind = 'source_date'` now tests
membership of `DATED_KINDS`. 20,345 rows on the 2026-09-13 build, 17,574 of
them previously censored.

WHAT THIS MODULE GUARANTEES
---------------------------
1. IDEMPOTENCE. Re-running a month never moves `first_seen_month` and never
   double-counts `n_months_seen`: the upsert increments only when the
   snapshot's month is STRICTLY NEWER than the row's `last_seen_month`.
2. NO SILENT MIS-JOIN. `cluster_id` is not stable across dedup re-runs (see
   sql/018), so identity is carried by a content hash first and a
   name+distance link second, and every ledger row whose `last_seen_month` is
   behind the newest snapshot has its `cluster_id_latest` NULLed. A stale join
   returns nothing rather than the wrong storefront.
3. THE LINK IS NEVER LOOSER THAN THE DEDUP. It reuses
   `score.dedup.norm_tokens` / `names_match` / `MATCH_METERS`, the same rule
   that formed the cluster in the first place. Widening it here would fuse
   distinct storefronts and manufacture fake retail gaps downstream -- the
   failure score/dedup.py's own comments are about.
4. FAIL LOUD. `snapshot` raises if the warehouse has no deduped locations
   rather than writing an empty month, and refuses an out-of-order month
   without `force=True`.

`FIRST_SEEN_FIELDS` lives here, NOT in chains/detect.py, because two copies of
"which fields may be read as an opening date" is how `last_inspection_date`
eventually gets read as one. detect.py imports it from here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import pathlib
from dataclasses import dataclass, field

import h3

from loci.score.dedup import BLOCK_RES, MATCH_METERS, haversine_m, names_match, norm_tokens

SQL_018 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "018_poi_presence.sql"

#: The month the ledger began. Documented, asserted by `check`, and NOT used to
#: decide censoring -- that is decided by "was the ledger empty before this
#: snapshot", which survives the constant drifting out of date.
LEDGER_START_MONTH = "2026-09"

#: The first month in which "new" is a real observation rather than an artefact
#: of the ledger starting. Nothing before this may be reported as an opening.
FIRST_HONEST_MONTH = "2026-10"

#: 'gov_filing' is written by model/storefront_pipeline.apply_gov_filing, NOT
#: by `snapshot` -- a government filing dated the opening earlier than any POI
#: source could, or dated a left-censored row at all. It carries a real
#: `first_seen_src_date` exactly as 'source_date' does, which is why the two
#: appear together in every invariant below and in the sql/020 reporting view.
#: `snapshot` never MINTS it and never overwrites it except by the same
#: one-way upgrade that already applies: a source date at or before the month
#: already held.
KINDS = ("source_date", "observed", "backfill_censored", "gov_filing")

#: The kinds that carry a DATE rather than a month of observation. Anything
#: reading `first_seen_src_date` must branch on this set, never on
#: `== 'source_date'`.
DATED_KINDS = frozenset({"source_date", "gov_filing"})

#: Decimal places for the coordinate component of the minted key. 4 dp is
#: ~11 m N-S and ~8.5 m E-W at NYC's latitude -- finer than dedup's 40 m match
#: radius, so two clusters the dedup deliberately kept apart will nearly always
#: round apart too. It is a GRID, though, so a cluster whose canonical member
#: changes can cross a boundary and hash differently; that is precisely what
#: the name+distance link pass exists to absorb, and why the hash is never the
#: only route to identity.
KEY_PRECISION = 4

#: Per-location first-seen candidates from the SOURCE, in no particular order:
#: the minimum over all of them wins. Each entry is (SQL expression over an
#: aliased `staging.poi` row `p`, label). `try_strptime` returns NULL instead
#: of raising on a format mismatch, which keeps one malformed attrs blob from
#: failing the whole run.
#:
#: `attrs.last_inspection_date` IS DELIBERATELY ABSENT AND MUST STAY ABSENT.
#: It is a LAST-seen date. Reading it as a first-seen would date every
#: long-established restaurant to its most recent inspection and label the
#: whole food tier newly opened. tests/test_poi_presence.py and
#: tests/test_chains_detect.py both assert it.
FIRST_SEEN_FIELDS: tuple[tuple[str, str], ...] = (
    ("p.opened_on", "opened_on"),
    ("try_cast(try_strptime(json_extract_string(p.attrs, '$.license_issue_date'),"
     " '%m/%d/%Y') AS DATE)", "license_issue_date"),
    ("try_cast(try_strptime(json_extract_string(p.attrs, '$.enrollment_begin_date'),"
     " '%Y-%m-%dT%H:%M:%S.%g') AS DATE)", "enrollment_begin_date"),
)


@dataclass
class SnapshotResult:
    month: str
    n_locations: int          # deduped locations seen this month
    n_matched_hash: int       # carried forward by an exact key match
    n_matched_link: int       # carried forward by the name+distance link
    n_new: int                # minted this month
    n_gone: int               # ledger rows NOT seen this month
    n_rows_total: int         # ledger size after the write
    kinds: dict = field(default_factory=dict)          # first_seen_kind -> count
    hash_collisions: int = 0  # live clusters sharing one minted key
    upgraded: int = 0         # censored/observed rows a source finally dated
    dry_run: bool = False


def ensure_schema(con) -> None:
    """Apply sql/018_poi_presence.sql. Idempotent."""
    con.execute(SQL_018.read_text())


def connect_write(path=None, retries: int = 20, wait_s: float = 30.0):
    """Open the warehouse READ-WRITE, waiting out a concurrent writer's lock.

    Mirrors model/recommend.connect_read_only, with a longer patience because
    this one has to WAIT for the other writer to finish rather than merely for
    a window. Never kills anything: another session rebuilding the warehouse is
    the normal state here (D69), and working on a copy would mean the ledger --
    the one table whose whole value is being continuous -- got written
    somewhere that is thrown away."""
    import time

    from loci import db as locidb

    target = path or locidb.DEFAULT_PATH
    last = None
    for i in range(retries):
        try:
            return locidb.connect(target)
        except Exception as exc:            # noqa: BLE001 -- duckdb raises several
            last = exc
            if i < retries - 1:
                time.sleep(wait_s)
    raise RuntimeError(
        f"could not open {target} read-write after {retries} tries "
        f"({retries * wait_s / 60:.0f} min): {last}")


def current_month(today: dt.date | None = None) -> str:
    return (today or dt.date.today()).strftime("%Y-%m")


def validate_month(month: str) -> None:
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"--month must be YYYY-MM, got {month!r}") from exc


def first_seen_sql() -> tuple[str, str]:
    """(least-of-the-candidates, the label of whichever won) as two SQL
    expressions over an aliased `staging.poi` row `p`."""
    exprs = [e for e, _ in FIRST_SEEN_FIELDS]
    value = "least(" + ", ".join(exprs) + ")" if len(exprs) > 1 else exprs[0]
    branches = " ".join(
        f"WHEN {expr} IS NOT NULL AND {expr} = {value} THEN '{label}'"
        for expr, label in FIRST_SEEN_FIELDS)
    return value, f"CASE {branches} END"


def current_locations_sql() -> str:
    """One row per DEDUPLICATED LOCATION as the warehouse stands right now.

    Reads `analysis.poi_dedup` + `staging.poi` directly rather than
    `analysis.poi_supply`: the ledger records every location Loci observed,
    which is deliberately NOT the supply-set question (`in_principled`,
    `is_active`). Dropping a single-source storefront from the ledger would
    make it look like it opened later, when a second feed finally noticed it.
    Going through the base tables also means the ledger does not inherit
    poi_supply's dependency on analysis.category_anchor.

    The source date is the minimum over EVERY cluster member, not just the
    canonical one: a DOHMH-canonical restaurant whose Foursquare member
    carries the only `opened_on` still gets dated."""
    value, label = first_seen_sql()
    return f"""
    WITH member AS (
        SELECT d.cluster_id,
               p.source_id,
               {value} AS src_date,
               {label} AS src_field
        FROM analysis.poi_dedup d
        JOIN staging.poi p ON p.poi_id = d.poi_id
    ),
    dated AS (
        SELECT cluster_id,
               min(src_date)                    AS src_date,
               arg_min(src_field, src_date)     AS src_field,
               count(DISTINCT source_id)        AS n_sources
        FROM member
        GROUP BY 1
    ),
    canon AS (
        SELECT d.cluster_id,
               d.poi_id,
               d.category,
               p.name,
               ST_X(p.geom) AS lon,
               ST_Y(p.geom) AS lat
        FROM analysis.poi_dedup d
        JOIN staging.poi p ON p.poi_id = d.poi_id
        WHERE d.is_canonical
    )
    SELECT c.cluster_id, c.poi_id, c.category, c.name, c.lon, c.lat,
           h.borough,
           t.src_date, t.src_field, t.n_sources
    FROM canon c
    LEFT JOIN dated t ON t.cluster_id = c.cluster_id
    LEFT JOIN analysis.hex h
           ON h.h3_index = h3_latlng_to_cell_string(c.lat, c.lon, 9)
    """


def name_key_of(name) -> str:
    """The link key: `score.dedup.norm_tokens` sorted and joined. Empty for a
    nameless or wholly-generic POI, which means such a location can only ever
    be carried forward by the hash, never by the link. That is intentional --
    `names_match` refuses an empty token set for the same reason."""
    return " ".join(sorted(norm_tokens(name)))


def mint_key(category: str, name_key: str, lon: float, lat: float,
             poi_id: str | None = None) -> str:
    """The content hash. See KEY_PRECISION for why 4 dp, and sql/018 for why a
    hash alone is not identity.

    NAMELESS LOCATIONS ALSO HASH THEIR CANONICAL poi_id, and that clause is
    load-bearing. Measured on the live warehouse (227,548 clusters): every one
    of the 118 clusters that collided on `category | name | lon,lat` had an
    EMPTY `name_key` -- CJK and Arabic shopfront names, which `norm_tokens`
    strips to nothing because it keeps only `[a-z0-9]`, plus all-generic names
    like "Chicken Kitchen" whose every token is a stopword -- typically sitting
    on one fallback geocode. For those rows the hash carries no distinguishing
    content at all, so without this the same key would be minted for genuinely
    different storefronts.

    Disambiguating by a positional suffix instead was tried and is WRONG: the
    suffix depends on which collider is processed first, so the assignment
    changed between runs and the second snapshot minted 63 duplicate rows for
    locations it already held -- caught by `coverage_check`'s
    one-row-per-cluster assertion. `poi_id` is a deterministic function of
    cluster membership (the canonical pick is 100% reproducible under input
    reordering, measured), so hashing it is stable where a suffix is not.

    THE COST, stated plainly: for a nameless cluster the key moves if its
    CANONICAL MEMBER changes -- a feed dropping the winning row re-mints. The
    name+distance link cannot rescue those either, because `names_match`
    refuses an empty token set. So ~0.05% of locations have a weaker identity
    guarantee than the rest, and they are the ones we know least about anyway."""
    payload = (f"{category}|{name_key}|"
               f"{round(float(lon), KEY_PRECISION):.{KEY_PRECISION}f}|"
               f"{round(float(lat), KEY_PRECISION):.{KEY_PRECISION}f}")
    if not name_key:
        payload += f"|{poi_id}"
    return "loc_" + hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()


# ---------------------------------------------------------------------------
# the link
# ---------------------------------------------------------------------------
def link_to_ledger(cur, existing) -> tuple[list[str], dict]:
    """Resolve each current location to a ledger `location_key`.

    `cur` and `existing` are DataFrames. Returns (keys aligned to cur.index,
    stats). Three passes, in decreasing confidence:

      A. exact minted-key match (same category). O(1), and the whole ledger
         takes this path on a month where nothing upstream changed.
      B. name + distance link, H3 res-11 blocked, against ledger rows pass A
         did not claim: same category, `names_match`, within MATCH_METERS,
         nearest wins, one-to-one.
      C. mint.

    One-to-one is enforced by `claimed`: a ledger row can be carried forward by
    at most one current location. Two live clusters that both hash to one key
    (or both link to one row) are NOT merged -- the loser mints its own key and
    the collision is counted and reported. Merging them would be the
    fusing-distinct-storefronts bug."""
    import numpy as np

    n = len(cur)
    minted = [mint_key(c, nk, lon, lat, pid) for c, nk, lon, lat, pid in
              zip(cur["category"], cur["name_key"], cur["lon"], cur["lat"],
                  cur["poi_id"], strict=True)]

    out: list[str | None] = [None] * n
    claimed: set[str] = set()
    stats = {"hash": 0, "link": 0, "new": 0, "hash_collisions": 0}

    if existing is not None and len(existing):
        by_key = dict(zip(existing["location_key"], existing["category"], strict=True))
    else:
        by_key = {}

    # ---- pass A: exact key
    for i, k in enumerate(minted):
        if k in by_key and k not in claimed and by_key[k] == cur["category"].iat[i]:
            out[i] = k
            claimed.add(k)
            stats["hash"] += 1
        elif k in by_key or k in claimed:
            # Someone else already owns this hash. Not an error yet -- pass B
            # may still find this location its own ledger row.
            stats["hash_collisions"] += 1

    # ---- pass B: name + distance, against unclaimed ledger rows
    todo = [i for i in range(n) if out[i] is None]
    if todo and existing is not None and len(existing):
        ex_key = existing["location_key"].to_numpy()
        ex_cat = existing["category"].to_numpy()
        ex_lat = existing["lat"].to_numpy(dtype=float)
        ex_lon = existing["lon"].to_numpy(dtype=float)
        ex_tok = [norm_tokens(s) for s in existing["display_name"]]

        cells: dict[str, list[int]] = {}
        for j in range(len(existing)):
            if ex_key[j] in claimed:
                continue
            if not np.isfinite(ex_lat[j]) or not np.isfinite(ex_lon[j]):
                continue
            cells.setdefault(h3.latlng_to_cell(ex_lat[j], ex_lon[j], BLOCK_RES), []).append(j)

        for i in todo:
            lat_i, lon_i = float(cur["lat"].iat[i]), float(cur["lon"].iat[i])
            tok_i = norm_tokens(cur["name"].iat[i])
            cat_i = cur["category"].iat[i]
            best, best_d = None, MATCH_METERS + 1.0
            for cell in h3.grid_disk(h3.latlng_to_cell(lat_i, lon_i, BLOCK_RES), 1):
                for j in cells.get(cell, ()):
                    if ex_key[j] in claimed or ex_cat[j] != cat_i:
                        continue
                    if not names_match(tok_i, ex_tok[j]):
                        continue
                    d = haversine_m(lat_i, lon_i, ex_lat[j], ex_lon[j])
                    if d <= MATCH_METERS and d < best_d:
                        best, best_d = j, d
            if best is not None:
                out[i] = ex_key[best]
                claimed.add(ex_key[best])
                stats["link"] += 1

    # ---- pass C: mint, disambiguating a collision rather than merging
    #
    # Processed in canonical-poi_id order, NOT row order, so that if the suffix
    # path ever does fire the assignment is at least reproducible. It should
    # not fire: `mint_key` folds the poi_id in for exactly the population that
    # used to collide. A suffix here now means a genuine 64-bit hash collision.
    used = set(by_key) | {k for k in out if k}
    for i in sorted((i for i in range(n) if out[i] is None),
                    key=lambda i: str(cur["poi_id"].iat[i])):
        k = minted[i]
        if k in used:
            # A genuine 64-bit hash collision (mint_key already folds poi_id in
            # for the nameless population that used to collide on content).
            # Suffix, never merge: fusing two live storefronts would delete a
            # real one and manufacture a retail gap where none exists.
            stats["hash_collisions"] += 1
            suffix = 2
            while f"{k}-{suffix}" in used:
                suffix += 1
            k = f"{k}-{suffix}"
        out[i] = k
        used.add(k)
        stats["new"] += 1

    return [str(k) for k in out], stats


# ---------------------------------------------------------------------------
# the snapshot
# ---------------------------------------------------------------------------
#: THE ONE-WAY UPGRADE CONDITION, written once because it appears in four SET
#: clauses and four copies is how three of them eventually drift apart.
#:
#: A snapshot may replace the stored first-seen with a SOURCE date only when
#:   * the row is not already dated by a source, AND
#:   * the incoming date is not LATER than the month already held, AND
#:   * where a date is already held (a 'gov_filing' row, written by
#:     model/storefront_pipeline.apply_gov_filing), the incoming one is
#:     STRICTLY EARLIER.
#:
#: The third clause is what keeps a government filing's actual opening date
#: from being nudged later by a source date that merely falls in the same
#: month. Without it, a 'gov_filing' row dated 2025-03-02 would be overwritten
#: by a licence date of 2025-03-28 -- a later date, presented as an upgrade.
_UPGRADE_SQL = """pp.first_seen_kind <> 'source_date'
             AND excluded.first_seen_src_date IS NOT NULL
             AND strftime(excluded.first_seen_src_date, '%Y-%m') <= pp.first_seen_month
             AND (pp.first_seen_src_date IS NULL
                  OR excluded.first_seen_src_date < pp.first_seen_src_date)"""

_UPSERT_TEMPLATE = """
INSERT INTO analysis.poi_presence AS pp
SELECT location_key, category, name_key, display_name, lon, lat, borough,
       first_seen_month, last_seen_month, first_seen_kind, first_seen_src_date,
       first_seen_src_field, n_months_seen, cluster_id_latest, poi_id_latest,
       ledger_started_month, last_snapshot_at
FROM _presence_in
ON CONFLICT (location_key) DO UPDATE SET
    category         = excluded.category,
    name_key         = excluded.name_key,
    display_name     = excluded.display_name,
    lon              = excluded.lon,
    lat              = excluded.lat,
    borough          = excluded.borough,
    -- last_seen / n_months move only FORWARD. This is what makes re-running a
    -- month a no-op instead of a double count.
    last_seen_month  = greatest(pp.last_seen_month, excluded.last_seen_month),
    n_months_seen    = pp.n_months_seen
                       + CASE WHEN excluded.last_seen_month > pp.last_seen_month
                              THEN 1 ELSE 0 END,
    cluster_id_latest = excluded.cluster_id_latest,
    poi_id_latest     = excluded.poi_id_latest,
    -- ONE-WAY UPGRADE (_UPGRADE_SQL): a row we could only censor (or only
    -- observe) becomes 'source_date' if a source later publishes a date at or
    -- before the month we already had. Censoring can only ever shrink; it
    -- never reappears, and a later-than-known date is refused rather than
    -- allowed to move first_seen_month forward. `ledger_started_month` is
    -- untouched either way, so when we FIRST HELD the row is never lost.
    first_seen_kind = CASE
        WHEN {UPGRADE}
        THEN 'source_date' ELSE pp.first_seen_kind END,
    first_seen_month = CASE
        WHEN {UPGRADE}
        THEN strftime(excluded.first_seen_src_date, '%Y-%m') ELSE pp.first_seen_month END,
    first_seen_src_date = CASE
        WHEN {UPGRADE}
        THEN excluded.first_seen_src_date ELSE pp.first_seen_src_date END,
    first_seen_src_field = CASE
        WHEN {UPGRADE}
        THEN excluded.first_seen_src_field ELSE pp.first_seen_src_field END,
    last_snapshot_at = excluded.last_snapshot_at
"""

_UPSERT = _UPSERT_TEMPLATE.replace("{UPGRADE}", _UPGRADE_SQL)


def snapshot(con, *, month: str | None = None, dry_run: bool = False,
             today: dt.date | None = None, force: bool = False) -> SnapshotResult:
    """Record one month of observation for every deduplicated location.

    Idempotent: re-running a month changes no `first_seen_month` and no
    `n_months_seen`. `dry_run` computes everything and writes nothing."""
    import pandas as pd

    today = today or dt.date.today()
    month = month or current_month(today)
    validate_month(month)
    ensure_schema(con)

    newest = con.execute(
        "SELECT max(last_seen_month) FROM analysis.poi_presence").fetchone()[0]
    if newest and month < newest and not force:
        raise ValueError(
            f"refusing to snapshot {month}: the ledger already holds {newest}. "
            "Out-of-order months do not increment n_months_seen and cannot move "
            "last_seen_month backwards (sql/018 caveat 2). Pass force=True only "
            "if you understand that.")

    cur = con.execute(current_locations_sql()).fetchdf()
    if cur.empty:
        raise RuntimeError(
            "analysis.poi_dedup is empty -- refusing to write an empty month. "
            "Run `loci dedup` first; a silent zero here would mark every "
            "storefront in the city as disappeared.")

    cur["name_key"] = [name_key_of(s) for s in cur["name"]]

    # A source date is usable only if it is a real past date. A future date is
    # a data error, not an opening; taking it would let a location claim it
    # opened after we saw it.
    src = pd.to_datetime(cur["src_date"], errors="coerce").dt.date
    usable = src.notna() & (src <= today) & (src.map(
        lambda d: d.strftime("%Y-%m") if d is not None and d == d else "9999-99") <= month)
    cur["src_date_ok"] = src.where(usable)
    cur["src_field_ok"] = cur["src_field"].where(usable)

    existing = con.execute(
        "SELECT location_key, category, display_name, lon, lat, first_seen_month, "
        "first_seen_kind FROM analysis.poi_presence").fetchdf()
    first_ever = existing.empty

    keys, stats = link_to_ledger(cur, existing)
    cur["location_key"] = keys

    known = set(existing["location_key"]) if not first_ever else set()
    is_new = [k not in known for k in keys]

    # The mint-time kind. An existing row keeps its own (the upsert only ever
    # upgrades it to 'source_date'), so these values matter only for new rows;
    # they are computed for every row because the upsert needs a full frame.
    kinds, fs_month = [], []
    for i in range(len(cur)):
        d = cur["src_date_ok"].iat[i]
        if d is not None and d == d:
            kinds.append("source_date")
            fs_month.append(d.strftime("%Y-%m"))
        elif first_ever:
            kinds.append("backfill_censored")
            fs_month.append(month)
        else:
            kinds.append("observed")
            fs_month.append(month)

    now = dt.datetime.now()
    frame = pd.DataFrame({
        "location_key": cur["location_key"],
        "category": cur["category"],
        "name_key": cur["name_key"],
        "display_name": cur["name"],
        "lon": cur["lon"].astype(float),
        "lat": cur["lat"].astype(float),
        "borough": cur["borough"],
        "first_seen_month": fs_month,
        "last_seen_month": month,
        "first_seen_kind": kinds,
        "first_seen_src_date": cur["src_date_ok"],
        "first_seen_src_field": cur["src_field_ok"],
        "n_months_seen": 1,
        "cluster_id_latest": cur["cluster_id"].astype("int64"),
        "poi_id_latest": cur["poi_id"].astype(str),
        "ledger_started_month": month,
        "last_snapshot_at": now,
    })
    if frame["location_key"].duplicated().any():
        dup = frame.loc[frame["location_key"].duplicated(), "location_key"].tolist()[:5]
        raise RuntimeError(
            f"link_to_ledger produced duplicate location_keys ({dup}) -- that "
            "would fuse distinct storefronts. This is a bug, not a data issue.")

    n_gone = 0 if first_ever else int(
        (~existing["location_key"].isin(set(keys))).sum())

    result = SnapshotResult(
        month=month,
        n_locations=len(cur),
        n_matched_hash=stats["hash"],
        n_matched_link=stats["link"],
        n_new=int(sum(is_new)),
        n_gone=n_gone,
        n_rows_total=len(existing) + int(sum(is_new)),
        kinds={k: int((frame["first_seen_kind"] == k).sum()) for k in KINDS},
        hash_collisions=stats["hash_collisions"],
        dry_run=dry_run,
    )
    if dry_run:
        return result

    # UNDATED = not in DATED_KINDS. Written that way rather than
    # `!= "source_date"` because 'gov_filing' rows ARE dated (by
    # model/storefront_pipeline.apply_gov_filing) and counting them as
    # undated would report a phantom upgrade every month.
    before_censored = 0 if first_ever else int(
        (~existing["first_seen_kind"].isin(DATED_KINDS)).sum())

    con.execute("BEGIN")
    try:
        con.register("_presence_in", frame)
        con.execute(_UPSERT)
        # A stale cluster_id is worse than none: it would silently attach this
        # month's dedup numbering to a location we did not see this month.
        con.execute(
            "UPDATE analysis.poi_presence "
            "SET cluster_id_latest = NULL, poi_id_latest = NULL "
            "WHERE last_seen_month < ?", [month])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_presence_in")

    dated = ", ".join(f"'{k}'" for k in sorted(DATED_KINDS))
    after = con.execute(
        "SELECT count(*), "
        f"count(*) FILTER (WHERE first_seen_kind NOT IN ({dated})) "
        "FROM analysis.poi_presence").fetchone()
    result.n_rows_total = int(after[0])
    result.upgraded = max(0, before_censored - int(after[1])) if not first_ever else 0
    result.kinds = dict(con.execute(
        "SELECT first_seen_kind, count(*) FROM analysis.poi_presence "
        "GROUP BY 1 ORDER BY 1").fetchall())
    return result


# ---------------------------------------------------------------------------
# the guard
# ---------------------------------------------------------------------------
def coverage_check(con) -> tuple[list[str], dict]:
    """Assert the ledger covers the warehouse. Returns (errors, stats).

    The load-bearing one is (1): after an ingest + snapshot, EVERY current
    deduplicated location must have a ledger row. A location with no row is a
    location whose first-seen we will never be able to state."""
    errors: list[str] = []
    stats: dict = {}

    have = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'analysis' AND table_name = 'poi_presence'").fetchone()[0]
    if not have:
        return (["analysis.poi_presence does not exist -- run `loci poi-snapshot`"],
                stats)

    stats["ledger_rows"] = con.execute(
        "SELECT count(*) FROM analysis.poi_presence").fetchone()[0]
    stats["newest_month"] = con.execute(
        "SELECT max(last_seen_month) FROM analysis.poi_presence").fetchone()[0]
    stats["clusters"] = con.execute(
        "SELECT count(DISTINCT cluster_id) FROM analysis.poi_dedup").fetchone()[0]

    # (1) coverage: every current cluster is claimed by a ledger row that was
    #     seen in the newest month.
    uncovered = con.execute("""
        SELECT count(*) FROM (
            SELECT DISTINCT d.cluster_id FROM analysis.poi_dedup d
            WHERE NOT EXISTS (
                SELECT 1 FROM analysis.poi_presence pp
                WHERE pp.cluster_id_latest = d.cluster_id
                  AND pp.last_seen_month = (SELECT max(last_seen_month)
                                            FROM analysis.poi_presence))
        )""").fetchone()[0]
    stats["uncovered_clusters"] = uncovered
    stats["coverage_pct"] = (
        100.0 * (stats["clusters"] - uncovered) / stats["clusters"]
        if stats["clusters"] else 0.0)
    if uncovered:
        errors.append(
            f"{uncovered} of {stats['clusters']} deduped locations have no ledger "
            f"row in {stats['newest_month']} -- run `loci poi-snapshot` after ingest")

    # (2) one ledger row per live cluster, never two.
    dupes = con.execute(
        "SELECT count(*) FROM (SELECT cluster_id_latest FROM analysis.poi_presence "
        "WHERE cluster_id_latest IS NOT NULL GROUP BY 1 HAVING count(*) > 1)").fetchone()[0]
    if dupes:
        errors.append(f"{dupes} cluster_ids are claimed by more than one ledger row "
                      "-- two histories are fused onto one storefront")

    # (3) the kind invariants.
    holes = ", ".join("?" for _ in KINDS)
    bad_kind = con.execute(
        f"SELECT count(*) FROM analysis.poi_presence WHERE first_seen_kind "
        f"NOT IN ({holes})", list(KINDS)).fetchone()[0]
    if bad_kind:
        errors.append(f"{bad_kind} rows carry an unknown first_seen_kind")

    dated_holes = ", ".join(f"'{k}'" for k in sorted(DATED_KINDS))
    bad_src = con.execute(
        f"SELECT count(*) FROM analysis.poi_presence WHERE "
        f"(first_seen_kind IN ({dated_holes})) <> (first_seen_src_date IS NOT NULL)"
    ).fetchone()[0]
    if bad_src:
        errors.append(f"{bad_src} rows disagree about first_seen_src_date: it must be "
                      f"non-NULL for exactly the {sorted(DATED_KINDS)} rows")

    # A 'gov_filing' row's month must BE its date's month. The writer sets both
    # in one statement; a disagreement means something else wrote one of them.
    bad_gov = con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE "
        "first_seen_kind = 'gov_filing' AND (first_seen_src_date IS NULL "
        "OR strftime(first_seen_src_date, '%Y-%m') <> first_seen_month)"
    ).fetchone()[0]
    if bad_gov:
        errors.append(f"{bad_gov} 'gov_filing' rows have a first_seen_month that is "
                      "not their opening date's month")

    bad_order = con.execute(
        "SELECT count(*) FROM analysis.poi_presence "
        "WHERE first_seen_month > last_seen_month").fetchone()[0]
    if bad_order:
        errors.append(f"{bad_order} rows have first_seen_month after last_seen_month")

    # (4) censoring can only be a backfill-month artefact.
    bad_censor = con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE "
        "first_seen_kind = 'backfill_censored' AND ledger_started_month <> ?",
        [con.execute("SELECT min(ledger_started_month) FROM analysis.poi_presence"
                     ).fetchone()[0] or LEDGER_START_MONTH]).fetchone()[0]
    if bad_censor:
        errors.append(f"{bad_censor} left-censored rows were minted after the ledger's "
                      "first month -- censoring is only ever a backfill artefact")

    stats["kinds"] = dict(con.execute(
        "SELECT first_seen_kind, count(*) FROM analysis.poi_presence "
        "GROUP BY 1 ORDER BY 1").fetchall())
    return errors, stats
