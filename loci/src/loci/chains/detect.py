"""`loci chains detect` -- chains from open data, deterministically.

Reads the warehouse and NOTHING ELSE: no network, no API key, no judgement.
Group `analysis.poi_supply` (deduped, canonical locations) by `brand_key`,
count locations, date what can be dated, flag what is growing.

---------------------------------------------------------------------------
GRAIN
---------------------------------------------------------------------------
One LOCATION is one `analysis.poi_dedup.cluster_id`, not one staging.poi row.
A Starbucks carried by Overture and Foursquare is one location, not two. This
is the same supply grain the address screen reads, so a brand count and a
category count cannot disagree about how many stores exist.

`analysis.poi_supply` is used WITHOUT a supply-set filter (`in_principled`,
`is_active`, ...). That is deliberate and it is the opposite of the address
screen's default. The screen asks "does this location count as supply", a
question about false positives in a gap. This asks "how many storefronts does
this brand operate", where dropping a real store because only one source saw it
understates a chain -- and a brand with three uncorroborated locations is
exactly the young chain the list exists to find. The source count per brand
(`n_sources`) is published so a single-source brand can be discounted by eye.

---------------------------------------------------------------------------
DATES: read from the LEDGER, never re-derived here
---------------------------------------------------------------------------
`first_seen_on` per location comes from `analysis.poi_first_seen`
(model/poi_presence.py, sql/018), the monthly observation ledger -- NOT from
the sources directly. The ledger resolves the three kinds:

    source_date        a source published an open / licence / enrolment date.
                       `first_seen_on` is that DATE.
    observed           no source date; the ledger saw the storefront appear.
                       `first_seen_on` is the FIRST DAY of that month, so the
                       12m / 3m windows treat it exactly like a dated one.
    backfill_censored  the location already existed when the ledger started
                       (2026-09) and nothing dates it. LEFT-CENSORED:
                       `first_seen_on` is NULL and it counts as UNDATED, the
                       same way an undated location always has.

So `locations_new_12m` is STILL a floor -- but a floor that shrinks every
month, because each month's genuinely new storefronts arrive as 'observed'
rather than as nothing at all. `locations_dated` publishes the denominator, and
the run summary now splits it by kind so the shrinking is visible.

THE TRAP THAT MUST STAY SHUT: `attrs.last_inspection_date` is a LAST-seen
date. It is not in `poi_presence.FIRST_SEEN_FIELDS`, it must never be added,
and both tests/test_chains_detect.py and tests/test_poi_presence.py assert it
-- reading it as a first-seen would date every long-established restaurant to
its most recent inspection and label the whole food tier a new chain.

THE OTHER HALF of the growth measure is still the month-over-month difference
in `chains.brand_snapshot`, which depends on no date at all and needs two
snapshots. The ledger does not replace it; it makes the per-location story
auditable in between.

`location_key` IS NOW THE LEDGER KEY, not `poi_dedup.cluster_id`. cluster_id is
renumbered by every dedup re-run (sql/018 explains why), so the old
`brand_location` key silently meant a different storefront from one month to
the next. Comparing two months of that table is only valid with the ledger key.
"""
from __future__ import annotations

import datetime as dt
import functools
import pathlib
from dataclasses import dataclass

from loci.chains.normalize import ALIASES, brand_key
from loci.model.poi_presence import FIRST_SEEN_FIELDS, first_seen_sql  # noqa: F401

SQL_DIR = pathlib.Path(__file__).resolve().parents[1] / "sql"
SQL_015 = SQL_DIR / "015_chains.sql"
#: The three derived signal columns (GTM-189). Applied by `ensure_schema`
#: alongside 015 so any path that can write a snapshot can write them; also
#: applied by `db.init_schema` with every other migration.
SQL_039 = SQL_DIR / "039_chains_pipeline_signals.sql"

#: A brand needs at least this many deduped locations to be a chain at all.
#: Below it the table would be every sole proprietor in New York.
MIN_LOCATIONS = 2

#: The two flag rules, from the brief. FAST_SMALL catches the young chain --
#: two new stores when you only have eight is a faster expansion than three
#: new stores when you have four hundred -- which is the population this list
#: is for. Both are evaluated on the DATED subset, so both are floors.
FLAG_NEW_12M = 3
FLAG_FAST_SMALL_NEW = 2
FLAG_FAST_SMALL_TOTAL = 8

#: FIRST_SEEN_FIELDS is re-exported from model/poi_presence for backwards
#: compatibility only. It is DEFINED there, because the ledger and this module
#: must never disagree about which fields may be read as an opening date --
#: two copies of that list is how `last_inspection_date` eventually gets added
#: to one of them.


@dataclass(frozen=True)
class DetectResult:
    snapshot_month: str
    n_brands: int
    n_flagged: int
    n_locations: int
    n_dated: int
    #: The dated/undated split by LEDGER KIND, over brand-locations.
    #: n_by_source + n_observed == n_dated; n_censored is the undated
    #: remainder and is LEFT-CENSORED, never "opened in the ledger's first
    #: month".
    n_by_source: int = 0
    n_observed: int = 0
    n_censored: int = 0


def current_month(today: dt.date | None = None) -> str:
    return (today or dt.date.today()).strftime("%Y-%m")


#: Columns sql/039 adds to chains.brand_snapshot, in the order it adds them.
SIGNAL_COLUMNS = ("pipeline_filings_12m", "pipeline_coverage", "press_hits_12m")

#: Every column `_write` puts into chains.brand_snapshot, NAMED. It used to be
#: a positional `INSERT ... SELECT *`, which is a write that silently breaks
#: the first time the table is widened -- and sql/039 widens it.
SNAPSHOT_COLUMNS = (
    "snapshot_month", "brand_key", "display_name", "loci_category",
    "locations_total", "locations_dated", "locations_new_12m",
    "locations_new_3m", "n_boroughs", "boroughs", "categories",
    "n_sources", "flagged", "flag_reason", "detected_at",
) + SIGNAL_COLUMNS

#: Every column `_write` puts into chains.brand_location, NAMED, in the order
#: sql/015 creates them. sql/039's header claims BOTH chains inserts were made
#: to name their columns in that commit; only `brand_snapshot` above was, and
#: the `brand_location` write stayed `INSERT ... SELECT *` until now. The table
#: has exactly ONE column order today (verified: a fresh CREATE from sql/015
#: matches the live table position for position, and no migration ALTERs it),
#: so nothing was mis-written -- but sql/039 has already established ALTER as
#: the way a chains table is widened, and the next one would have broken this
#: write silently.
LOCATION_COLUMNS = (
    "snapshot_month", "brand_key", "location_key", "poi_id", "category",
    "borough", "lon", "lat", "first_seen_on", "first_seen_src",
)

#: The two `pipeline_coverage` values. NULL is the third state and means the
#: brand has no `loci_category`, so which regime applies is unknown.
COVERAGE_REAL = "real"
COVERAGE_STRUCTURAL_ZERO = "structural_zero"


def ensure_schema(con) -> None:
    """Apply sql/015_chains.sql and sql/039_chains_pipeline_signals.sql.
    Idempotent; safe on a warehouse whose init-db predates the chains schema."""
    con.execute(SQL_015.read_text())
    con.execute(SQL_039.read_text())


@functools.lru_cache(maxsize=1)
def filing_real_categories() -> frozenset[str]:
    """The Loci categories a government filing feed can actually see.

    DERIVED, never typed: it is every category any feed in
    model/filing_categories.yaml maps a licence type onto. On the 2026-09
    vocabulary that is restaurant, bar, cafe_bakery, grocery and pharmacy --
    the other ten are licensed by NYS DOS, NYS Education or NYS OCFS, or are
    not licensed at all, and no DOB feed carries a trade field that would
    attribute a filing to them (GTM-152, D80).

    A hand-copied list here would be a second definition of the same fact, and
    the first feed anybody adds is the moment the two disagree while both look
    right. `tests/test_chains_detect.py` pins today's five so the set moving is
    a visible event rather than a silent one."""
    from loci.model.storefront_pipeline import load_category_map

    doc = load_category_map()
    out: set[str] = set()
    for block in doc["sources"].values():
        out |= set((block.get("map") or {}).values())
    return frozenset(out)


def coverage_for(loci_category) -> str | None:
    """`real` | `structural_zero` | None for one brand's category.

    None (not `structural_zero`) for a brand with NO category: `structural_zero`
    is a CLAIM -- "the filing channel is blind to this trade" -- and nobody
    established it for a brand whose trade is unknown. NULL is this project's
    standing "not measured" (D79), and the render prints it as such."""
    if not loci_category or (isinstance(loci_category, float)):
        return None
    return (COVERAGE_REAL if loci_category in filing_real_categories()
            else COVERAGE_STRUCTURAL_ZERO)


def location_rows_sql() -> str:
    """One row per (cluster_id, raw name), with its first-seen taken FROM THE
    LEDGER (`analysis.poi_first_seen`).

    Names come from EVERY cluster member, not just the canonical POI: Overture
    is canonical far more often than DOHMH is, and Overture's spelling is the
    one most likely to be a bare brand ("Starbucks") while a licence filing
    carries the operating company. Taking all spellings and letting
    `brand_key` collapse them means a location reaches its brand if ANY source
    spelled it recognisably.

    THE JOIN TO THE LEDGER IS ON `cluster_id_latest`, and the view only ever
    exposes that column for rows seen in the newest snapshot month -- every
    other row has it NULLed by `loci poi-snapshot`, precisely so a stale dedup
    numbering cannot attach one storefront's history to another. A location
    with no ledger row therefore reads as UNDATED rather than as wrongly dated,
    and `build` raises on it instead of quietly shipping the zero."""
    return """
    WITH member AS (
        SELECT d.cluster_id,
               p.poi_id,
               p.source_id,
               p.name,
               p.category
        FROM analysis.poi_dedup d
        JOIN staging.poi p ON p.poi_id = d.poi_id
        WHERE p.name IS NOT NULL
    ),
    canon AS (
        SELECT s.cluster_id,
               any_value(s.poi_id)   AS poi_id,
               any_value(s.category) AS category,
               any_value(ST_X(s.geom)) AS lon,
               any_value(ST_Y(s.geom)) AS lat
        FROM analysis.poi_supply s
        GROUP BY 1
    ),
    srcs AS (
        SELECT cluster_id, count(DISTINCT source_id) AS n_sources
        FROM member GROUP BY 1
    ),
    led AS (
        SELECT cluster_id_latest AS cluster_id,
               location_key,
               first_seen_kind,
               first_seen_month,
               -- The window date. A source date is used as-is; an 'observed'
               -- location is dated to the FIRST DAY of the month the ledger
               -- saw it, which is the conservative end of that month. A
               -- censored location stays NULL: first_seen_month is already
               -- NULL for it in the view, so this COALESCE cannot resurrect
               -- the ledger's start month as a fake opening date.
               COALESCE(first_seen_on,
                        try_strptime(first_seen_month || '-01', '%Y-%m-%d')::DATE)
                                                          AS first_seen_on
        FROM analysis.poi_first_seen
        WHERE cluster_id_latest IS NOT NULL
    )
    SELECT m.cluster_id,
           m.name,
           c.poi_id,
           m.category           AS member_category,
           c.category           AS category,
           c.lon, c.lat,
           h.borough            AS borough,
           l.location_key,
           l.first_seen_on,
           COALESCE(l.first_seen_kind, 'unledgered') AS first_seen_kind,
           s.n_sources,
           m.source_id
    FROM member m
    JOIN canon c       ON c.cluster_id = m.cluster_id
    JOIN srcs  s       ON s.cluster_id = m.cluster_id
    LEFT JOIN led l    ON l.cluster_id = m.cluster_id
    LEFT JOIN analysis.hex h
           ON h.h3_index = h3_latlng_to_cell_string(c.lat, c.lon, 9)
    """


def build(con, *, month: str | None = None, dry_run: bool = False,
          today: dt.date | None = None) -> tuple[DetectResult, list[dict]]:
    """Detect chains and write one month of `chains.brand_snapshot` +
    `chains.brand_location`. Idempotent: the month is DELETEd first.

    Returns (summary, brand rows). `dry_run` computes everything and writes
    nothing, so the flag counts can be inspected before a snapshot is committed
    -- a bad snapshot is not just a bad row, it becomes the baseline every
    later month is differenced against."""
    today = today or dt.date.today()
    month = month or current_month(today)
    _validate_month(month)

    import pandas as pd

    _require_ledger(con)
    df = con.execute(location_rows_sql()).fetchdf()

    unledgered = int((df["first_seen_kind"] == "unledgered").sum())
    if unledgered:
        raise RuntimeError(
            f"{unledgered} of {len(df)} POI rows have no row in "
            f"analysis.poi_first_seen for the newest snapshot month. Run "
            f"`loci poi-snapshot --month {month}` first. Detecting without the "
            "ledger would silently report every one of them as undated, which "
            "reads as 'not growing' rather than as 'not measured'.")

    # brand_key is deliberately applied in Python, not SQL: the normalizer is
    # the unit-tested artefact and a SQL transliteration of it would be a
    # second implementation to keep in step. 300k rows is milliseconds.
    df["brand_key"] = df["name"].map(brand_key)
    df = df[df["brand_key"].notna()]

    # One (brand, location) pair per row. A cluster whose members normalize to
    # two different brands is counted under BOTH -- co-branded storefronts
    # (Dunkin'/Baskin) are real, and picking one would silently halve a brand.
    df = (df.sort_values(["brand_key", "cluster_id", "name"])
            .drop_duplicates(["brand_key", "cluster_id"]))


    cutoff_12m = today - dt.timedelta(days=365)
    cutoff_3m = today - dt.timedelta(days=91)
    fs = pd.to_datetime(df["first_seen_on"], errors="coerce").dt.date

    df = df.assign(
        is_dated=fs.notna(),
        is_new_12m=fs.notna() & (fs >= cutoff_12m),
        is_new_3m=fs.notna() & (fs >= cutoff_3m),
    )

    grouped = df.groupby("brand_key", sort=False)
    brands = grouped.agg(
        locations_total=("cluster_id", "nunique"),
        locations_dated=("is_dated", "sum"),
        locations_new_12m=("is_new_12m", "sum"),
        locations_new_3m=("is_new_3m", "sum"),
    ).reset_index()
    brands = brands[brands["locations_total"] >= MIN_LOCATIONS]

    keep = set(brands["brand_key"])
    loc = df[df["brand_key"].isin(keep)]

    from loci.chains.normalize import display_name

    def _set(s) -> list[str]:
        """Sorted distinct non-null strings. A POI outside analysis.hex (the
        grid is shoreline-clipped, so a pier or an airport terminal falls out)
        has a NaN borough; NaN is truthy, so it has to be dropped by name."""
        return sorted({str(v) for v in s if pd.notna(v)})

    meta = loc.groupby("brand_key").agg(
        display_name=("name", lambda s: display_name(list(s))),
        boroughs=("borough", lambda s: ",".join(_set(s))),
        n_boroughs=("borough", lambda s: len(_set(s))),
        categories=("category", lambda s: ",".join(_set(s))),
        loci_category=("category", lambda s: s.mode().iat[0] if len(s.mode()) else None),
        n_sources=("source_id", "nunique"),
    ).reset_index()
    brands = brands.merge(meta, on="brand_key", how="left")

    # A list comprehension, NOT DataFrame.apply: apply coerces a returned None
    # to NaN, and `nan is not None` is True, which silently flagged every brand.
    _attach_signals(con, brands, month)

    flags = [flag_for(int(n), int(t))
             for n, t in zip(brands["locations_new_12m"],
                             brands["locations_total"], strict=True)]
    brands["flagged"] = [f is not None for f in flags]
    brands["flag_reason"] = flags
    brands["snapshot_month"] = month
    brands["detected_at"] = dt.datetime.now()

    # The ledger kind, counted over BRAND-LOCATIONS (`loc` is exactly the
    # population `locations_total` sums over, co-branded storefronts included),
    # so source + observed + censored == n_locations and the censored share is
    # readable straight off the run summary. It is the number that says how
    # much of `locations_new_12m` is a floor rather than a measurement.
    kinds = loc["first_seen_kind"].value_counts()
    result = DetectResult(
        snapshot_month=month,
        n_brands=len(brands),
        n_flagged=int(brands["flagged"].sum()),
        n_locations=int(brands["locations_total"].sum()),
        n_dated=int(brands["locations_dated"].sum()),
        n_by_source=int(kinds.get("source_date", 0)),
        n_observed=int(kinds.get("observed", 0)),
        n_censored=int(kinds.get("backfill_censored", 0)),
    )
    rows = brands.sort_values(["locations_new_12m", "locations_total"],
                             ascending=False).to_dict("records")
    if dry_run:
        return result, rows

    _write(con, month, brands, loc)
    return result, rows


def month_window_12m(month: str) -> tuple[dt.date, dt.date]:
    """(start, end_exclusive) for the twelve CALENDAR months ending with
    `month`.

    Anchored on the snapshot, not on `today`: the month is the unit of
    idempotence for this table, and a re-run of 2026-09 next March has to
    produce the number September produced. A rolling 365 days off the clock
    would quietly make the snapshot un-reproducible."""
    year, mon = (int(x) for x in month.split("-"))
    start_year, start_month = divmod((year * 12 + (mon - 1)) - 11, 12)
    end_year, end_month = divmod((year * 12 + (mon - 1)) + 1, 12)
    return (dt.date(start_year, start_month + 1, 1),
            dt.date(end_year, end_month + 1, 1))


def _table_exists(con, schema: str, name: str) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, name]).fetchone()[0])


def _count_by_key(con, sql: str, params: list) -> dict[str, int]:
    return {k: int(n) for k, n in con.execute(sql, params).fetchall() if k}


def _attach_signals(con, brands, month: str) -> None:
    """Write `pipeline_filings_12m`, `pipeline_coverage` and `press_hits_12m`
    onto the month's brand frame (GTM-189; sql/039 carries the rationale).

    THE MISSING-TABLE RULE, copied from candidates.py rather than re-invented:
    a warehouse without `analysis.storefront_pipeline` or `chains.press_hits`
    is a normal state -- both are built by other commands -- and the column
    then stays NULL for every brand. It must never be 0. "We did not measure
    that channel" and "that channel saw nothing" are different facts, and this
    column is the only place the difference survives the month.

    A brand the table HAS but never names gets a real 0, which is a
    measurement, and `pipeline_coverage` says whether that 0 could ever have
    been anything else."""
    import pandas as pd

    start, end = month_window_12m(month)
    keys = brands["brand_key"]

    if _table_exists(con, "analysis", "storefront_pipeline"):
        # `business_name_key` IS chains.normalize.brand_key -- model/
        # storefront_pipeline.py imports the same function -- so this is an
        # exact match, not a fuzzy one. ALL filings, open and not: this
        # measures paperwork, not the candidate predicate's `pipeline_open`.
        counts = _count_by_key(con, """
            SELECT business_name_key, count(*)
            FROM analysis.storefront_pipeline
            WHERE business_name_key IS NOT NULL
              AND entry_date >= ? AND entry_date < ?
            GROUP BY 1
        """, [start.isoformat(), end.isoformat()])
        brands["pipeline_filings_12m"] = keys.map(counts).fillna(0).astype("Int64")
    else:
        brands["pipeline_filings_12m"] = pd.Series(pd.NA, index=brands.index,
                                                   dtype="Int64")

    if _table_exists(con, "chains", "press_hits"):
        counts = _count_by_key(con, """
            SELECT brand_key, count(*)
            FROM chains.press_hits
            WHERE brand_key <> '' AND published_on IS NOT NULL
              AND published_on >= ? AND published_on < ?
            GROUP BY 1
        """, [start.isoformat(), end.isoformat()])
        brands["press_hits_12m"] = keys.map(counts).fillna(0).astype("Int64")
    else:
        brands["press_hits_12m"] = pd.Series(pd.NA, index=brands.index, dtype="Int64")

    brands["pipeline_coverage"] = [coverage_for(c) for c in brands["loci_category"]]


def flag_for(new_12m: int, total: int) -> str | None:
    """The flag rule, and the reason in words. None = not flagged.

    Two rules, because the interesting population is bimodal: a national chain
    adding three NYC stores in a year, and a two-year-old local brand going
    from four stores to six. The second would never clear an absolute
    threshold, and it is the one worth a sales call."""
    if new_12m >= FLAG_NEW_12M:
        return f"{new_12m} new locations in 12 months"
    if new_12m >= FLAG_FAST_SMALL_NEW and total <= FLAG_FAST_SMALL_TOTAL:
        return f"{new_12m} new of only {total} locations (fast small chain)"
    return None


def _require_ledger(con) -> None:
    """Fail loud if the first-seen ledger has not been built.

    Without this, `location_rows_sql` would still run -- the LEFT JOIN simply
    yields NULLs -- and every brand would report `locations_dated = 0`. A
    zeroed growth column looks like "no chain is growing", which is a finding;
    it is actually "we did not measure". Never ingest a silent zero."""
    ok = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'analysis' AND table_name = 'poi_first_seen'"
    ).fetchone()[0]
    if not ok:
        raise RuntimeError(
            "analysis.poi_first_seen does not exist. Run `loci poi-snapshot` "
            "(sql/018_poi_presence.sql) before `loci chains detect`; "
            "`make chains-refresh` does this in order.")


def _validate_month(month: str) -> None:
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"--month must be YYYY-MM, got {month!r}") from exc


def _write(con, month: str, brands, loc) -> None:
    ensure_schema(con)
    snap = brands[list(SNAPSHOT_COLUMNS)].copy()
    for col in ("locations_total", "locations_dated", "locations_new_12m",
                "locations_new_3m", "n_boroughs", "n_sources"):
        snap[col] = snap[col].astype(int)

    # location_key is the LEDGER key (analysis.poi_presence.location_key), NOT
    # poi_dedup.cluster_id: cluster_id is renumbered by every dedup re-run, so
    # the old key made two months of this table incomparable. `first_seen_src`
    # now carries the ledger KIND -- source_date / observed / backfill_censored
    # -- which is what a reader of a date actually needs to know about it.
    detail = loc.assign(snapshot_month=month,
                        first_seen_src=loc["first_seen_kind"])
    detail = detail[list(LOCATION_COLUMNS)].copy()
    detail["location_key"] = detail["location_key"].astype(str)
    detail = detail.drop_duplicates(["snapshot_month", "brand_key", "location_key"])

    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM chains.brand_snapshot WHERE snapshot_month = ?", [month])
        con.execute("DELETE FROM chains.brand_location WHERE snapshot_month = ?", [month])
        con.register("_chain_snap", snap)
        con.register("_chain_loc", detail)
        cols = ", ".join(SNAPSHOT_COLUMNS)
        con.execute(f"INSERT INTO chains.brand_snapshot ({cols}) "
                    f"SELECT {cols} FROM _chain_snap")
        # Named on BOTH sides. The SELECT list alone would not protect this
        # write: DuckDB binds an INSERT ... SELECT by POSITION, so a column
        # added to chains.brand_location by a future ALTER would shift the
        # target ordinals under an unchanged SELECT.
        loc_cols = ", ".join(LOCATION_COLUMNS)
        con.execute(f"INSERT INTO chains.brand_location ({loc_cols}) "
                    f"SELECT {loc_cols} FROM _chain_loc")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_chain_snap")
        con.unregister("_chain_loc")


def latest_month(con) -> str | None:
    row = con.execute("SELECT max(snapshot_month) FROM chains.brand_snapshot").fetchone()
    return row[0] if row else None


def flagged_brands(con, month: str | None = None, limit: int = 0) -> list[dict]:
    """Flagged brands from one snapshot, newest first by new_12m then total."""
    month = month or latest_month(con)
    if month is None:
        return []
    sql = """
        SELECT * FROM chains.brand_snapshot
        WHERE snapshot_month = ? AND flagged
        ORDER BY locations_new_12m DESC, locations_total DESC, brand_key
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql, [month]).fetchdf().to_dict("records")


def alias_report() -> dict[str, str]:
    """The manual collapses in force, for the generated doc's provenance line."""
    return dict(ALIASES)
