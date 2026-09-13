"""NYC DOT Bi-Annual Pedestrian Counts, WIDE -> LONG, as an ingested source.

    staging.dot_pedestrian_count   one row per (point x round x period)

WHAT CHANGED AND WHY
---------------------------------------------------------------------------
This dataset entered the project as a validation HARNESS
(`loci.validation.pedestrian_counts`, GTM-146): it pulled the feed live, took
the single most recent round, and correlated it against the walkable-demand
measures. Nothing was stored, so nineteen years of counts at the same hundred
screenlines -- the only direct observation of sidewalk volume anywhere in this
project -- were fetched and thrown away on every run.

This module ingests the whole history instead. The harness now reads this
table (it keeps its own CLI and its own output), and the trend at a point
becomes a query rather than a re-pull.

STILL NOT AN INPUT TO ANY SCORE. See the caveats at the bottom: 114 points is
not a sample of New York, and a count at a screenline is a two-hour manual
observation on one day. It is CONTEXT and it is a CONTROL -- the registry role
moved from `validation` to `control` for exactly that reason (the schema takes
one role, `loci.registry.VALID_ROLES`, so `validation` could not be kept
alongside it; the notes say so).

THE COLUMN-NAME PARSER, WHICH IS THE WHOLE INGEST
---------------------------------------------------------------------------
DOT publishes each round as three new COLUMNS, and has never published them
twice the same way. Observed on the live feed, all of these are real:

    may_07_am   sept_07_pm   may_19_md   oct_20_am   may_21_pm
    may_22_p_m  (sic)        may_23_p_m  (sic)       oct_22_pm
    june_24_am  oct24_md     may25_pm    oct25_am    may26_md

Both the separator and the PM spelling move between rounds, and the month
abbreviation is sometimes three letters and sometimes four (`sept`, `june`).
So the rounds are DISCOVERED from the feed's own field names by
`parse_round`, never typed into a list. A hard-coded 'may26_pm' would have
gone silently stale at the next release; 'may_22_pm' never existed at all.

`round` is normalised to 'YYYY-MM' ('2026-05'), which sorts lexicographically
in the same order as it sorts chronologically -- so `MAX(round)` is the latest
round, in SQL, without a date cast.

WHAT IS AND IS NOT A ROW
---------------------------------------------------------------------------
Socrata OMITS a null cell rather than sending it, so a (point, round, period)
with no count arrives as an ABSENT KEY. Those become no row: a point that was
not counted in May 2011 has no May 2011 row, and the absence is legible as
absence. A count of 0 IS a row -- twelve of them exist in the feed and they
are real observations of an empty screenline, not missing data. This is the
one place where "drop the nulls, keep the zeros" is not a slogan but a
column-by-column decision, and inverting it would fabricate twelve holes or
342 zeros.

BRIDGES ARE KEPT HERE AND EXCLUDED DOWNSTREAM
---------------------------------------------------------------------------
`loc` 101-114 are bridge MIDPOINTS -- five East River crossings, nine Harlem
River -- and a point in the middle of the Williamsburg Bridge has no 400 m
residential catchment in any meaningful sense. The validation harness excludes
them and so does the address context. They are still INGESTED, flagged
`is_bridge`, because dropping a row at ingest time to suit one consumer is how
a source stops being a source; the flag lets every consumer make its own call.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. NOT A SAMPLE OF THE CITY. DOT picked these points for traffic-engineering
   reasons: busy commercial corridors and bridge approaches. The bottom of the
   volume range is barely represented, so any statistic computed here is on a
   RESTRICTED RANGE and does not transfer to a quiet residential block, which
   is most of the address universe.
2. TWO HOURS, ONE DAY, TWICE A YEAR. AM is 07:00-09:00, MD 12:00-14:00, PM
   16:00-19:00 (so PM is THREE hours: `count` summed over a round is seven
   hours of observation, not a day, and the three periods are not equal-length
   windows -- never average them as though they were). Weather and a single
   unusual day are not averaged out.
3. THE ROUNDS ARE NOT EVENLY SPACED and two are missing outright: there is no
   September 2019 round and no May 2020 round (COVID); 2024's spring round is
   JUNE, not May. A trend fitted on decimal years handles this; a trend fitted
   on "round number" silently treats a 17-month gap as one step.
4. NO EXPANSION FACTOR EXISTS. DOT publishes no public factor to scale a
   seven-hour screenline count to a daily volume. Do not invent one.
5. THE POINT SET IS NOT CONSTANT ACROSS HISTORY. 342 of the 12,654 possible
   cells are absent, and they are not spread evenly -- a point added in 2020
   has no 2007 row. Always report N rounds beside any per-point trend.
"""
from __future__ import annotations

import datetime as dt
import re

from loci.sources.cities.nyc import socrata

SOURCE_ID = "nyc_dot_pedestrian_counts"
DATASET_ID = "cqsj-cfgu"
DOMAIN = socrata.NYC_DOMAIN
ENDPOINT = f"{DOMAIN}/resource/{DATASET_ID}.json"

#: `loc` values above this are bridge midpoints, not street locations.
MAX_ON_STREET_LOC = 100

#: The three count periods, in clock order. A round is USABLE (for the latest
#: round, the trend, the address context) only if all three are present.
PERIODS = ("am", "md", "pm")

#: The clock windows DOT counts, for the record. PM is three hours; AM and MD
#: are two. Summing them is "people observed in the round's seven counted
#: hours", which is what `count` means and all it means.
WINDOWS = {"am": (7, 9), "md": (12, 14), "pm": (16, 19)}

#: The rounds the programme did not run. DOT published no September 2019 round
#: and no May 2020 round, and 2024's spring round was held in JUNE. These are
#: DATA, not trivia: they are why a trend here is fitted on decimal years (see
#: `point_summary`) and why the ten-year window straddles a pandemic.
MISSING_ROUNDS = ("2019-09", "2020-05")
MOVED_ROUNDS = {"2024-05": "2024-06"}

#: THE SENTENCE THAT MUST TRAVEL WITH EVERY TREND COMPUTED FROM THIS TABLE.
#: Defined here, beside the gaps it describes, so the webmap popup, a card and
#: a memo all print the same words -- a caveat retyped at the point of display
#: is a caveat that drifts from the data it is about.
TREND_CAVEAT = (
    "The series has holes. DOT ran no September 2019 round and no May 2020 "
    "round (COVID), and 2024's spring round was June, not May. The slope is "
    "fitted on decimal years, so the gaps are spaced correctly -- but a "
    "ten-year window straddles the shutdown and the recovery, and a positive "
    "slope over it can be a return to 2019 rather than growth past it. Read "
    "it with the N of rounds beside it, and read it as description.")

#: The non-count columns of the feed. Everything else is parsed as a round.
META_FIELDS = ("the_geom", "objectid", "loc", "borough", "street_nam",
               "from_stree", "to_street", "iex")

#: Fail-loud floors. The live feed carries 114 points and 37 rounds (2007-05 ..
#: 2026-05). If a parser change, a renamed column family or a truncated
#: response drops us below these, that is a broken ingest and NOT a city where
#: nobody counted anything -- so it raises rather than writing a thin table.
MIN_POINTS = 100
MIN_ROUNDS = 30

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "june": 6,
           "jun": 6, "july": 7, "jul": 7, "aug": 8, "sept": 9, "sep": 9,
           "oct": 10, "nov": 11, "dec": 12}

_FIELD_RE = re.compile(
    r"^(?P<mon>jan|feb|mar|apr|may|june|jun|july|jul|aug|sept|sep|oct|nov|dec)"
    r"_?(?P<yy>\d{2})_?(?P<per>am|md|pm|p_m)$")


class DotCountError(RuntimeError):
    """An ingest that must not be mistaken for a city nobody counted."""


# ------------------------------------------------------------- the parser

def parse_round(field: str) -> tuple[int, int, str] | None:
    """'may26_md' -> (2026, 5, 'md'); 'may_22_p_m' -> (2022, 5, 'pm');
    anything that is not a count column -> None.

    Two-digit years are read as 20YY. The feed starts in 2007 and this project
    will not outlive the century; a four-digit year would be better and DOT
    does not publish one.
    """
    m = _FIELD_RE.match(field.strip().lower())
    if not m:
        return None
    per = m.group("per").replace("_", "")
    return 2000 + int(m.group("yy")), _MONTHS[m.group("mon")], per


def round_label(year: int, month: int) -> str:
    """(2026, 5) -> '2026-05'. Sorts chronologically as a string."""
    return f"{year:04d}-{month:02d}"


def rounds_in(rows: list[dict]) -> list[str]:
    """Every round label the feed publishes, oldest first -- discovered from
    the column names, never typed."""
    seen = set()
    for r in rows:
        for f in r:
            p = parse_round(f)
            if p:
                seen.add(round_label(p[0], p[1]))
    return sorted(seen)


def latest_round(rows: list[dict]) -> tuple[int, int]:
    """The (year, month) of the most recent round for which AM, MD and PM all
    appear somewhere in `rows`. A round published with only one period -- it
    happens mid-release -- would otherwise silently become the denominator."""
    seen: dict[tuple[int, int], set[str]] = {}
    for r in rows:
        for f in r:
            p = parse_round(f)
            if p:
                seen.setdefault((p[0], p[1]), set()).add(p[2])
    full = [k for k, v in seen.items() if set(PERIODS) <= v]
    if not full:
        raise DotCountError(
            f"{ENDPOINT}: no round in the feed carries all of {PERIODS}; the "
            f"column naming has changed shape and the count cannot be assembled.")
    return max(full)


def loc_type(loc: int, borough: str | None) -> str:
    """'on_street' | 'east_river_bridge' | 'harlem_river_bridge'.

    DOT does not publish a location type. It publishes the bridge points with
    the BOROUGH field set to 'East River Bridges' / 'Harlem River Bridges',
    which is the only signal in the feed besides the `loc` range, so both are
    used and the two must agree -- if a future release renumbers the bridges
    without relabelling the borough (or vice versa) this returns the honest
    'bridge_unknown_water' rather than guessing.
    """
    b = (borough or "").strip().lower()
    by_loc = loc > MAX_ON_STREET_LOC
    by_label = "bridge" in b
    if not by_loc and not by_label:
        return "on_street"
    if by_loc != by_label:
        return "bridge_disputed"
    if b.startswith("east river"):
        return "east_river_bridge"
    if b.startswith("harlem river"):
        return "harlem_river_bridge"
    return "bridge_unknown_water"


# -------------------------------------------------------------- the fetch

def fetch_rows(*, refresh: bool = False, limit: int = 5000) -> list[dict]:
    """Every row of cqsj-cfgu, in the feed's own WIDE shape.

    Through `socrata.fetch`, so the raw JSON lands in data/raw/<source>/ before
    anything is parsed and an empty return RAISES rather than emptying the
    table.
    """
    rows = socrata.fetch(SOURCE_ID, DOMAIN, DATASET_ID, select="*",
                         limit=limit, use_cache=not refresh)
    if len(rows) < MIN_POINTS:
        raise DotCountError(
            f"{ENDPOINT}: returned {len(rows)} rows, fewer than the {MIN_POINTS} "
            f"count points this feed has published since 2007. Refusing to "
            f"ingest a truncated pull.")
    return rows


# --------------------------------------------------------- wide -> long

def to_long(rows: list[dict]) -> tuple[list[dict], dict]:
    """([{point_id, round, period, count, ...}], report) from the wide feed.

    ONE ROW PER NON-NULL CELL. An absent key is an uncounted (point, round,
    period) and produces no row; a 0 is a counted zero and produces one.
    """
    out: list[dict] = []
    dropped_geom = 0
    dropped_value = 0
    cells_seen = 0
    fields_by_round: dict[str, dict[str, str]] = {}

    for r in rows:
        try:
            loc = int(r["loc"])
        except (KeyError, TypeError, ValueError):
            raise DotCountError(
                f"a row of {DATASET_ID} has no usable `loc`: {r.get('objectid')!r}. "
                f"`loc` is the point identity; a row without one cannot be keyed.")
        geom = r.get("the_geom") or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if not coords or len(coords) != 2:
            dropped_geom += 1
            continue
        lon, lat = float(coords[0]), float(coords[1])
        borough = r.get("borough")
        base = {
            "point_id": loc,
            "lon": lon,
            "lat": lat,
            "borough": borough,
            "street": r.get("street_nam"),
            "from_street": r.get("from_stree"),
            "to_street": r.get("to_street"),
            "is_bridge": loc > MAX_ON_STREET_LOC,
            "loc_type": loc_type(loc, borough),
            # The feed's own flag. DOT's data dictionary does not define it;
            # it partitions the points 50/64 and is carried verbatim rather
            # than interpreted.
            "is_index": None if r.get("iex") is None else (
                str(r["iex"]).strip().upper() == "Y"),
        }
        for field, value in r.items():
            p = parse_round(field)
            if p is None:
                continue
            cells_seen += 1
            year, month, period = p
            label = round_label(year, month)
            fields_by_round.setdefault(label, {})[period] = field
            if value is None or str(value).strip() == "":
                dropped_value += 1
                continue
            try:
                count = int(round(float(value)))
            except (TypeError, ValueError):
                dropped_value += 1
                continue
            out.append({**base, "round": label, "period": period,
                        "count": count, "source_field": field})

    rounds = sorted(fields_by_round)
    if len(rounds) < MIN_ROUNDS:
        raise DotCountError(
            f"{DATASET_ID}: parsed only {len(rounds)} rounds ({rounds}), fewer "
            f"than the {MIN_ROUNDS} this feed has published since 2007. The "
            f"column naming has changed shape -- fix `parse_round` before "
            f"ingesting, do not write a thin table.")
    points = {row["point_id"] for row in out}
    report = {
        "dataset_id": DATASET_ID,
        "endpoint": ENDPOINT,
        "rows_in_feed": len(rows),
        "points": len(points),
        "on_street_points": len({p for p in points if p <= MAX_ON_STREET_LOC}),
        "bridge_points": len({p for p in points if p > MAX_ON_STREET_LOC}),
        "rounds": rounds,
        "n_rounds": len(rounds),
        "first_round": rounds[0] if rounds else None,
        "last_round": rounds[-1] if rounds else None,
        "fields_by_round": fields_by_round,
        "cells_possible": len(rows) * len(rounds) * len(PERIODS),
        "cells_present": len(out),
        "cells_absent_or_null": dropped_value,
        "cells_parsed": cells_seen,
        "zero_counts": sum(1 for row in out if row["count"] == 0),
        "total_count": sum(row["count"] for row in out),
        "dropped_rows_without_geometry": dropped_geom,
    }
    return out, report


# -------------------------------------------------------------- the write

LONG_COLUMNS = ["point_id", "round", "period", "count", "lon", "lat",
                "borough", "street", "from_street", "to_street", "is_bridge",
                "loc_type", "is_index", "source_field", "ingested_at"]


def write_counts(con, records: list[dict]) -> int:
    """Idempotent DELETE-then-INSERT of the whole table.

    Whole-table, not per-round: the feed republishes the entire history on
    every release (it is one wide row per point), a point's older cells can be
    revised, and 12k rows is not a volume that earns an incremental path.
    Refusing an empty write is the fail-loud half -- `DELETE` followed by an
    empty `INSERT` is how a source silently becomes a source of nothing.
    """
    if not records:
        raise DotCountError(
            "write_counts got zero records. That would DELETE the table and "
            "replace it with nothing -- which reads downstream as a city where "
            "DOT has never counted a pedestrian.")
    import pandas as pd

    now = dt.datetime.now().replace(microsecond=0)
    df = pd.DataFrame(records)
    df["ingested_at"] = now
    df = df[LONG_COLUMNS]
    con.execute("DELETE FROM staging.dot_pedestrian_count")
    con.register("_dot_long", df)
    try:
        cols = ", ".join(LONG_COLUMNS)
        con.execute(f"INSERT INTO staging.dot_pedestrian_count ({cols}) "
                    f"SELECT {cols} FROM _dot_long")
    finally:
        con.unregister("_dot_long")
    return len(df)


def ingest(con, *, refresh: bool = False, dry_run: bool = False
           ) -> tuple[list[dict], dict]:
    """fetch -> parse -> write. Returns (records, report)."""
    rows = fetch_rows(refresh=refresh)
    records, report = to_long(rows)
    report["written"] = 0 if dry_run else write_counts(con, records)
    report["dry_run"] = bool(dry_run)
    return records, report


# --------------------------------------------------------------- the reads

def table_summary(con) -> dict:
    """Row counts and coverage straight off staging.dot_pedestrian_count."""
    row = con.execute("""
        SELECT COUNT(*), COUNT(DISTINCT point_id), COUNT(DISTINCT round),
               MIN(round), MAX(round), SUM(count),
               COUNT(*) FILTER (WHERE count = 0),
               COUNT(DISTINCT point_id) FILTER (WHERE NOT COALESCE(is_bridge, FALSE)),
               COUNT(DISTINCT point_id) FILTER (WHERE COALESCE(is_bridge, FALSE)),
               MAX(ingested_at)
        FROM staging.dot_pedestrian_count
    """).fetchone()
    if not row or not row[0]:
        raise DotCountError(
            "staging.dot_pedestrian_count is empty -- run `loci dot-counts ingest`.")
    return {"rows": row[0], "points": row[1], "rounds": row[2],
            "first_round": row[3], "last_round": row[4], "total_count": row[5],
            "zero_counts": row[6], "on_street_points": row[7],
            "bridge_points": row[8], "ingested_at": row[9]}


def point_summary(con, trend_years: int = 10) -> "object":
    """One row per point: latest complete round, its AM/MD/PM, and the trend.

    THE TREND IS A SLOPE ON DECIMAL YEARS, NOT ON ROUND NUMBER. The rounds are
    not evenly spaced -- there is no September 2019 and no May 2020 round, and
    2024's spring round is June -- so "counts per round" would silently treat a
    17-month gap as one step. `trend_per_year` is the OLS slope of the
    whole-round total (AM+MD+PM, i.e. seven counted hours) against
    year + (month-1)/12, in people per year, over the last `trend_years` years.

    The window is anchored on the LATEST ROUND IN THE FEED, not on each point's
    own latest, so every point's slope is fitted over the same calendar window
    and the column is comparable across points. `trend_n_rounds` is reported
    beside it and a slope on fewer than three rounds is NULL: two points define
    a line through any two numbers, which is not a trend.

    A slope is not a forecast and not a significance test. Two hours on one day
    twice a year is a noisy series; read the slope with the N, and read both as
    description.
    """
    return con.execute(f"""
        WITH whole AS (
            SELECT point_id, round, SUM(count) AS total,
                   COUNT(DISTINCT period) AS n_periods,
                   MAX(count) FILTER (WHERE period = 'am') AS am,
                   MAX(count) FILTER (WHERE period = 'md') AS md,
                   MAX(count) FILTER (WHERE period = 'pm') AS pm
            FROM staging.dot_pedestrian_count
            GROUP BY point_id, round
        ),
        complete AS (
            SELECT *, CAST(SUBSTR(round, 1, 4) AS DOUBLE)
                      + (CAST(SUBSTR(round, 6, 2) AS DOUBLE) - 1) / 12.0 AS t
            FROM whole WHERE n_periods = 3
        ),
        anchor AS (SELECT MAX(t) AS t_max FROM complete),
        latest AS (
            SELECT point_id, round, total, am, md, pm,
                   ROW_NUMBER() OVER (PARTITION BY point_id ORDER BY round DESC) AS rn
            FROM complete
        ),
        trend AS (
            SELECT c.point_id,
                   REGR_SLOPE(c.total, c.t) AS slope,
                   COUNT(*)                 AS n
            FROM complete c, anchor a
            WHERE c.t >= a.t_max - {float(trend_years)}
            GROUP BY c.point_id
        ),
        meta AS (
            SELECT point_id, ANY_VALUE(lon) AS lon, ANY_VALUE(lat) AS lat,
                   ANY_VALUE(borough) AS borough,
                   ANY_VALUE(street) AS street, ANY_VALUE(from_street) AS from_street,
                   ANY_VALUE(to_street) AS to_street,
                   ANY_VALUE(loc_type) AS loc_type,
                   BOOL_OR(COALESCE(is_bridge, FALSE)) AS is_bridge,
                   COUNT(DISTINCT round) AS rounds_present
            FROM staging.dot_pedestrian_count GROUP BY point_id
        )
        SELECT m.point_id, m.lon, m.lat, m.borough, m.street, m.from_street, m.to_street,
               m.loc_type, m.is_bridge, m.rounds_present,
               l.round AS latest_round, l.am AS latest_am, l.md AS latest_md,
               l.pm AS latest_pm, l.total AS latest_total,
               CASE WHEN t.n >= 3 THEN t.slope END AS trend_per_year,
               t.n AS trend_n_rounds
        FROM meta m
        LEFT JOIN latest l ON l.point_id = m.point_id AND l.rn = 1
        LEFT JOIN trend  t ON t.point_id = m.point_id
        ORDER BY l.total DESC NULLS LAST, m.point_id
    """).fetchdf()


def wide_rows_from_db(con, limit: int | None = None) -> list[dict]:
    """The long table back in the feed's WIDE shape, for consumers that were
    written against the feed.

    This is the seam that lets `loci.validation.pedestrian_counts` read the
    warehouse without changing one line of its own logic or one character of
    its output: `source_field` is stored per cell, so the reconstructed dict
    carries DOT's original column spellings ('may_22_p_m' and all), and
    `on_street_counts` cannot tell the difference between this and a live pull.
    """
    rows = con.execute("""
        SELECT point_id, any_value(lon) AS lon, any_value(lat) AS lat,
               any_value(borough) AS borough, any_value(street) AS street,
               any_value(from_street) AS from_street,
               any_value(to_street) AS to_street,
               list(struct_pack(f := source_field, c := count)) AS cells
        FROM staging.dot_pedestrian_count
        GROUP BY point_id ORDER BY point_id
    """).fetchall()
    if not rows:
        raise DotCountError(
            "staging.dot_pedestrian_count is empty. Run `loci dot-counts "
            "ingest` -- this used to pull the feed live and now reads the "
            "warehouse, so an un-ingested database is an explicit error rather "
            "than a silent zero-point correlation.")
    out = []
    for (pid, lon, lat, borough, street, from_street, to_street, cells) in rows:
        rec = {"the_geom": {"type": "Point", "coordinates": [lon, lat]},
               "loc": str(pid), "borough": borough, "street_nam": street,
               "from_stree": from_street, "to_street": to_street}
        for cell in cells:
            rec[cell["f"]] = str(cell["c"])
        out.append(rec)
        if limit is not None and len(out) >= limit:
            break
    return out
