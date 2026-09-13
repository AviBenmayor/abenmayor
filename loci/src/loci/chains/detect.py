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
DATES: a floor, not a measurement
---------------------------------------------------------------------------
`first_seen_on` per location is the EARLIEST date any cluster member carries,
taken from FIRST_SEEN_FIELDS below. Most sources carry none:

    foursquare_os_places   opened_on            (FSQ `date_created`) -- present
    nys_sla_liquor_licenses opened_on           (licence effective)  -- present
    nys_dos_appearance_enhancement  attrs.license_issue_date         -- present
    nys_medicaid_pharmacies attrs.enrollment_begin_date              -- present
    overture_places, nyc_dohmh_restaurants, usda_snap_retailers,
    nyc_dcwp_inspections, nyc_dohmh_childcare                        -- NONE

So `locations_new_12m` is a COUNT OVER THE DATED SUBSET and is a floor.
`locations_dated` is written beside it so the denominator is never hidden.
`attrs.last_inspection_date` is deliberately NOT used: it is a LAST-seen date,
and reading it as a first-seen would date every long-established restaurant to
its most recent inspection and label the whole food tier a new chain.

The honest growth measure is the month-over-month difference in
`chains.brand_snapshot`, which depends on no source's dates at all. It needs
two snapshots to exist. Until then, the record-date estimate is what there is,
flagged as such in docs/CHAINS.md.
"""
from __future__ import annotations

import datetime as dt
import pathlib
from dataclasses import dataclass

from loci.chains.normalize import ALIASES, brand_key

SQL_015 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "015_chains.sql"

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

#: Per-location first-seen candidates, in no particular order: the minimum over
#: all of them wins. Each entry is (SQL expression over `p`, label).
#: try_strptime returns NULL instead of raising on a format mismatch, which is
#: what keeps one malformed attrs blob from failing the whole run.
FIRST_SEEN_FIELDS: tuple[tuple[str, str], ...] = (
    ("p.opened_on", "opened_on"),
    ("try_cast(try_strptime(json_extract_string(p.attrs, '$.license_issue_date'),"
     " '%m/%d/%Y') AS DATE)", "license_issue_date"),
    ("try_cast(try_strptime(json_extract_string(p.attrs, '$.enrollment_begin_date'),"
     " '%Y-%m-%dT%H:%M:%S.%g') AS DATE)", "enrollment_begin_date"),
)


@dataclass(frozen=True)
class DetectResult:
    snapshot_month: str
    n_brands: int
    n_flagged: int
    n_locations: int
    n_dated: int


def current_month(today: dt.date | None = None) -> str:
    return (today or dt.date.today()).strftime("%Y-%m")


def ensure_schema(con) -> None:
    """Apply sql/015_chains.sql. Idempotent; safe on a warehouse whose
    init-db predates the chains schema."""
    con.execute(SQL_015.read_text())


def _first_seen_sql() -> tuple[str, str]:
    """(least-of-the-candidates, the label of whichever won) as two SQL
    expressions over an aliased staging.poi row `p`."""
    exprs = [e for e, _ in FIRST_SEEN_FIELDS]
    value = "least(" + ", ".join(exprs) + ")" if len(exprs) > 1 else exprs[0]
    # Which field produced it. CASE rather than a lateral so this stays one pass.
    branches = " ".join(
        f"WHEN {expr} IS NOT NULL AND {expr} = {value} THEN '{label}'"
        for expr, label in FIRST_SEEN_FIELDS)
    return value, f"CASE {branches} END"


def location_rows_sql() -> str:
    """One row per (cluster_id, raw name) with its earliest dateable evidence.

    Names come from EVERY cluster member, not just the canonical POI: Overture
    is canonical far more often than DOHMH is, and Overture's spelling is the
    one most likely to be a bare brand ("Starbucks") while a licence filing
    carries the operating company. Taking all spellings and letting
    `brand_key` collapse them means a location reaches its brand if ANY source
    spelled it recognisably."""
    value, label = _first_seen_sql()
    return f"""
    WITH member AS (
        SELECT d.cluster_id,
               p.poi_id,
               p.source_id,
               p.name,
               p.category,
               {value} AS first_seen_on,
               {label} AS first_seen_src
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
    dated AS (
        SELECT cluster_id,
               min(first_seen_on) AS first_seen_on,
               arg_min(first_seen_src, first_seen_on) AS first_seen_src,
               count(DISTINCT source_id) AS n_sources
        FROM member
        GROUP BY 1
    )
    SELECT m.cluster_id,
           m.name,
           c.poi_id,
           m.category           AS member_category,
           c.category           AS category,
           c.lon, c.lat,
           h.borough            AS borough,
           d.first_seen_on,
           d.first_seen_src,
           d.n_sources,
           m.source_id
    FROM member m
    JOIN canon c  ON c.cluster_id = m.cluster_id
    JOIN dated d  ON d.cluster_id = m.cluster_id
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

    df = con.execute(location_rows_sql()).fetchdf()

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
    flags = [flag_for(int(n), int(t))
             for n, t in zip(brands["locations_new_12m"],
                             brands["locations_total"], strict=True)]
    brands["flagged"] = [f is not None for f in flags]
    brands["flag_reason"] = flags
    brands["snapshot_month"] = month
    brands["detected_at"] = dt.datetime.now()

    result = DetectResult(
        snapshot_month=month,
        n_brands=len(brands),
        n_flagged=int(brands["flagged"].sum()),
        n_locations=int(brands["locations_total"].sum()),
        n_dated=int(brands["locations_dated"].sum()),
    )
    rows = brands.sort_values(["locations_new_12m", "locations_total"],
                             ascending=False).to_dict("records")
    if dry_run:
        return result, rows

    _write(con, month, brands, loc)
    return result, rows


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


def _validate_month(month: str) -> None:
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"--month must be YYYY-MM, got {month!r}") from exc


def _write(con, month: str, brands, loc) -> None:
    ensure_schema(con)
    snap = brands[["snapshot_month", "brand_key", "display_name", "loci_category",
                   "locations_total", "locations_dated", "locations_new_12m",
                   "locations_new_3m", "n_boroughs", "boroughs", "categories",
                   "n_sources", "flagged", "flag_reason", "detected_at"]].copy()
    for col in ("locations_total", "locations_dated", "locations_new_12m",
                "locations_new_3m", "n_boroughs", "n_sources"):
        snap[col] = snap[col].astype(int)

    detail = loc.assign(snapshot_month=month).rename(
        columns={"cluster_id": "location_key"})
    detail = detail[["snapshot_month", "brand_key", "location_key", "poi_id",
                     "category", "borough", "lon", "lat",
                     "first_seen_on", "first_seen_src"]].copy()
    detail["location_key"] = detail["location_key"].astype(str)
    detail = detail.drop_duplicates(["snapshot_month", "brand_key", "location_key"])

    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM chains.brand_snapshot WHERE snapshot_month = ?", [month])
        con.execute("DELETE FROM chains.brand_location WHERE snapshot_month = ?", [month])
        con.register("_chain_snap", snap)
        con.register("_chain_loc", detail)
        con.execute("INSERT INTO chains.brand_snapshot SELECT * FROM _chain_snap")
        con.execute("INSERT INTO chains.brand_location SELECT * FROM _chain_loc")
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
