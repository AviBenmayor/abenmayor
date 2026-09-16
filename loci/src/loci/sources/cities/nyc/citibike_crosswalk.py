"""The legacy -> modern Citi Bike station crosswalk (sql/044).

WHY THIS EXISTS
---------------------------------------------------------------------------
Citi Bike published trip files under TWO station-id schemes:

    2013-06 .. 2021-01   small integers        `3002`, `444`
    2021-02 .. today     the Lyft scheme       `5905.14`, `4962`

They OVERLAP AND MEAN DIFFERENT THINGS -- legacy `3002` is "South End Ave &
Liberty St", modern `3002` is another dock -- and Lyft never published a
crosswalk. Until 2026-09-16 the reader REFUSED every pre-2021 month for exactly
that reason. The owner's rule ("never ever ever limit data pulls") retires the
refusal, so the eight missing years land with their legacy id in its own column
and this module is what optionally joins the two eras.

THE JOIN IS NAME + COORDINATES, WHICH IS THE DANGEROUS KIND
---------------------------------------------------------------------------
This project has been bitten before by a name/position join fusing two distinct
records. A fused dock here would be worse than a missing one: it would
manufacture continuity, making one dock look like it has traded since 2013 when
it opened in 2022, and it would do so silently.

So the rule is conservative, tiered, one-to-one, and every row carries the
evidence for itself:

    name_and_position   normalised names EQUAL and points within XW_STRICT_M.
                        confidence 1.00.
    position_only       names differ, points within XW_STRICT_M, and the pair is
                        MUTUALLY NEAREST. confidence 0.60. Docks are renamed
                        ("W 52 St & 11 Ave" -> "W 52 St & 11 Av"); a rename is
                        not a new dock.
    name_only           normalised names EQUAL, points XW_STRICT_M..XW_MAX_M
                        apart, and the name is UNIQUE on BOTH sides.
                        confidence 0.50. A dock moved across the street.

and three guards that do the actual work of not fusing:

    1. ONE-TO-ONE, ENFORCED. A legacy id claims at most one modern id and a
       modern id is claimed by at most one legacy id. Ties are DROPPED, never
       arbitrated, and counted as `ambiguous`.
    2. MUTUAL NEAREST for every position-based match. "Nearest modern dock"
       alone lets two legacy docks on one corner both claim it.
    3. A HARD CEILING at XW_MAX_M. Nothing further is a match at any
       confidence, ever.

DISTANCES ARE METRES AND ARE REPROJECTED EXPLICITLY (D16)
---------------------------------------------------------------------------
DuckDB GEOMETRY carries NO SRID. Everything stored here is EPSG:4326 by
convention and the database will not catch a violation, so the convention is
held in code. `ST_Distance_Sphere` reads POINT(x, y) as (LATITUDE, LONGITUDE)
while our points are (lon, lat): both sides must be flipped or every distance is
computed at the equator and one degree of longitude reads 111 km instead of the
84 km it is at New York -- a 32% understatement of every east-west gap, which at
a 35 m threshold is the difference between a match and a fusion. The one legal
spelling is `loci.db.METRES_SQL` and it is what this module uses.

AN UNMATCHED DOCK IS NOT AN ERROR
---------------------------------------------------------------------------
`build` reports the match rate by dock count AND by trip volume. If it is under
`REPORT_FLOOR` (90%) that is REPORTED LOUDLY and nothing is dropped: the legacy
months stay in `staging.citibike_station_month` with `station_id_legacy`
populated and `station_id` NULL. A missing crosswalk row costs a join. A dropped
month costs the data, and the data is the point.
"""
from __future__ import annotations

import datetime as dt

from loci.db import METRES_SQL

__all__ = [
    "CROSSWALK_COLUMNS",
    "LEGACY_ROSTER_SQL",
    "REPORT_FLOOR",
    "XW_MAX_M",
    "XW_STRICT_M",
    "apply_crosswalk",
    "build",
    "candidates_sql",
    "choose",
    "name_norm_sql",
    "rebuild_legacy_roster",
    "write_crosswalk",
]

#: Inside this, two docks with the same normalised name are the same dock, and
#: two docks with different names are still the same dock if they are mutually
#: nearest. 35 m is about the length of a 20-dock corral plus the GPS jitter in
#: the published coordinates; the measured underscore-twin tolerance in
#: `lyft_bikeshare` (60 m) is deliberately LOOSER because there the id already
#: proves the relationship and here nothing does.
XW_STRICT_M = 35.0

#: The hard ceiling. Beyond this nothing is ever a match, at any confidence. Two
#: docks 200 m apart are two docks, whatever they are called.
XW_MAX_M = 150.0

#: Below this match rate the result is reported as a WARNING, not as a failure.
#: Nothing is dropped either way -- see the module docstring.
REPORT_FLOOR = 0.90

CROSSWALK_COLUMNS = [
    "station_id_legacy", "station_id", "name_legacy", "name_modern",
    "lon_legacy", "lat_legacy", "lon_modern", "lat_modern",
    "distance_m", "name_match", "method", "confidence", "legacy_trips",
    "run_at",
]


# --------------------------------------------------------- the legacy roster

#: The legacy dock roster, derived wholly from the legacy rows of the month
#: table -- the same derivation `citibike.ROSTER_SQL` applies to the Lyft rows,
#: for the same reason: name and position come from the dock's MOST RECENT
#: ACTIVE month, because a dock that moved must be described where it last
#: stood, not at the average of where it has been.
LEGACY_ROSTER_SQL = """
DELETE FROM staging.citibike_station_legacy;
INSERT INTO staging.citibike_station_legacy
    (station_id_legacy, name, lon, lat, first_month, last_month,
     months_active, trips, ingested_at)
WITH m AS (
    SELECT station_id_legacy, month,
           any_value(station_name) AS name,
           any_value(lon) AS lon, any_value(lat) AS lat,
           sum(starts) + sum(ends) AS trips
    FROM staging.citibike_station_month
    WHERE era = 'legacy' AND station_id_legacy IS NOT NULL
    GROUP BY 1, 2
), last_seen AS (
    SELECT station_id_legacy, max(month) AS last_month
    FROM m WHERE trips > 0 GROUP BY 1
)
SELECT m.station_id_legacy,
       any_value(m.name) FILTER (m.month = l.last_month) AS name,
       any_value(m.lon)  FILTER (m.month = l.last_month) AS lon,
       any_value(m.lat)  FILTER (m.month = l.last_month) AS lat,
       min(m.month) FILTER (m.trips > 0)                 AS first_month,
       l.last_month,
       count(*) FILTER (m.trips > 0)                     AS months_active,
       sum(m.trips)                                      AS trips,
       now()::TIMESTAMP                                  AS ingested_at
FROM m JOIN last_seen l USING (station_id_legacy)
GROUP BY m.station_id_legacy, l.last_month
"""


def rebuild_legacy_roster(con) -> int:
    for stmt in LEGACY_ROSTER_SQL.strip().split(";\n"):
        if stmt.strip():
            con.execute(stmt)
    return con.execute(
        "SELECT count(*) FROM staging.citibike_station_legacy").fetchone()[0]


# ------------------------------------------------------------ name normalising

#: Street-type spellings that changed between the two eras without the dock
#: moving. Folded to ONE spelling so "W 52 St & 11 Av" and "W 52 St & 11 Ave"
#: compare equal. Deliberately short: every entry is a pair this feed actually
#: uses, and a generous synonym list is how a name join starts matching two
#: different corners.
_STREET_TYPES = [
    (r"\b(av|ave|avenue)\b", "ave"),
    (r"\b(st|street)\b", "st"),
    (r"\b(pl|place)\b", "pl"),
    (r"\b(rd|road)\b", "rd"),
    (r"\b(dr|drive)\b", "dr"),
    (r"\b(blvd|boulevard)\b", "blvd"),
    (r"\b(pkwy|parkway)\b", "pkwy"),
    (r"\b(sq|square)\b", "sq"),
    (r"\b(ct|court)\b", "ct"),
    (r"\b(ln|lane)\b", "ln"),
    (r"\b(ter|terrace)\b", "ter"),
    (r"\b(plz|plaza)\b", "plz"),
]


def name_norm_sql(col: str) -> str:
    """A dock name, canonicalised for EQUALITY only.

    Lowercased, punctuation dropped, whitespace collapsed, and the handful of
    street-type spellings the feed changed between eras folded together. It is
    NOT a fuzzy matcher: there is no edit distance and no token subset here,
    because "close enough" on a street name is how two corners become one dock.
    """
    x = f"lower(trim({col}))"
    x = f"regexp_replace({x}, '[^a-z0-9 &]', ' ', 'g')"
    x = f"regexp_replace({x}, '\\s+', ' ', 'g')"
    for pat, rep in _STREET_TYPES:
        x = f"regexp_replace({x}, '{pat}', '{rep}', 'g')"
    return f"trim(regexp_replace({x}, '\\s+', ' ', 'g'))"


# -------------------------------------------------------------- the candidates

#: A coarse lon/lat box applied BEFORE the metric distance, purely so the join
#: does not materialise legacy x modern in full. 0.004 degrees is ~340 m of
#: latitude and ~440 m of longitude at New York -- comfortably wider than
#: XW_MAX_M in both directions, so it can only remove pairs the metric test
#: would have removed anyway.
_PREFILTER_DEG = 0.004


def candidates_sql(max_m: float = XW_MAX_M) -> str:
    """Every (legacy dock, modern dock) pair within `max_m` METRES.

    The distance is `loci.db.METRES_SQL` and nothing else. See the module
    docstring for what using the raw `ST_Distance_Sphere` would cost (D16).
    """
    dist = METRES_SQL.format(a="ST_Point(l.lon, l.lat)",
                             b="ST_Point(m.lon, m.lat)")
    return f"""
    WITH l AS (
        SELECT station_id_legacy, name, lon, lat, COALESCE(trips, 0) AS trips,
               {name_norm_sql('name')} AS name_norm
        FROM staging.citibike_station_legacy
        WHERE lon IS NOT NULL AND lat IS NOT NULL
    ), m AS (
        SELECT station_id, name, lon, lat,
               {name_norm_sql('name')} AS name_norm
        FROM staging.citibike_station
        WHERE lon IS NOT NULL AND lat IS NOT NULL
    )
    SELECT l.station_id_legacy,
           m.station_id,
           l.name  AS name_legacy,
           m.name  AS name_modern,
           l.lon   AS lon_legacy,
           l.lat   AS lat_legacy,
           m.lon   AS lon_modern,
           m.lat   AS lat_modern,
           l.trips AS legacy_trips,
           {dist}  AS distance_m,
           (l.name_norm = m.name_norm AND l.name_norm <> '') AS name_match
    FROM l JOIN m
      ON abs(l.lon - m.lon) < {_PREFILTER_DEG}
     AND abs(l.lat - m.lat) < {_PREFILTER_DEG}
    WHERE {dist} <= {max_m}
    """


# ------------------------------------------------------------- the tiering

def choose(cand, *, strict_m: float = XW_STRICT_M, max_m: float = XW_MAX_M):
    """(accepted frame, counts) from the candidate pairs. PURE -- no warehouse.

    Tiers are applied in descending confidence and each tier may only use
    legacy and modern ids that no earlier tier claimed, so the result is
    one-to-one by construction. Within a tier a candidate is accepted only if it
    is UNAMBIGUOUS on both sides; a tie is dropped and counted, never broken by
    ordering (an arbitrary winner is a fusion that looks like a decision).
    """
    import pandas as pd

    cand = cand.copy()
    counts = {"candidate_pairs": int(len(cand)), "ambiguous": 0}
    taken_l: set[str] = set()
    taken_m: set[str] = set()
    out: list[pd.DataFrame] = []

    def _mutual_nearest(df):
        """Rows that are each side's single nearest surviving candidate."""
        nl = df.loc[df.groupby("station_id_legacy")["distance_m"].idxmin()]
        nm = df.loc[df.groupby("station_id")["distance_m"].idxmin()]
        keys = set(map(tuple, nl[["station_id_legacy", "station_id"]].values)) & \
            set(map(tuple, nm[["station_id_legacy", "station_id"]].values))
        mask = [tuple(r) in keys
                for r in df[["station_id_legacy", "station_id"]].values]
        return df[pd.Series(mask, index=df.index)]

    def _accept(df, method: str, confidence: float, *, unique_only: bool):
        nonlocal counts
        df = df[~df["station_id_legacy"].isin(taken_l)
                & ~df["station_id"].isin(taken_m)]
        if df.empty:
            counts[method] = 0
            return
        if unique_only:
            dup_l = df["station_id_legacy"].duplicated(keep=False)
            dup_m = df["station_id"].duplicated(keep=False)
            ambiguous = df[dup_l | dup_m]
            counts["ambiguous"] += int(ambiguous["station_id_legacy"].nunique())
            df = df[~(dup_l | dup_m)]
        df = df.copy()
        df["method"] = method
        df["confidence"] = confidence
        counts[method] = int(len(df))
        taken_l.update(df["station_id_legacy"])
        taken_m.update(df["station_id"])
        out.append(df)

    near = cand[cand["distance_m"] <= strict_m]
    # 1. name AND position. Unambiguous only: two same-named docks 30 m apart is
    #    a real shape (a street corner with two corrals) and it is not a match.
    _accept(near[near["name_match"]], "name_and_position", 1.0, unique_only=True)
    # 2. position, mutually nearest, names disagree -- a rename.
    rest = near[~near["name_match"]]
    rest = rest[~rest["station_id_legacy"].isin(taken_l)
                & ~rest["station_id"].isin(taken_m)]
    _accept(_mutual_nearest(rest) if len(rest) else rest,
            "position_only", 0.6, unique_only=True)
    # 3. name, further than strict but inside the ceiling -- a dock that moved
    #    across the street. Only where the name is unique on BOTH sides.
    far = cand[(cand["distance_m"] > strict_m) & (cand["distance_m"] <= max_m)
               & cand["name_match"]]
    _accept(far, "name_only", 0.5, unique_only=True)

    for k in ("name_and_position", "position_only", "name_only"):
        counts.setdefault(k, 0)
    accepted = (pd.concat(out, ignore_index=True) if out
                else cand.head(0).assign(method="", confidence=0.0))
    counts["matched"] = int(len(accepted))
    return accepted, counts


# ---------------------------------------------------------------- the writer

def write_crosswalk(con, accepted, legacy, run_at: dt.datetime) -> int:
    """DELETE-then-INSERT the whole crosswalk. Every legacy dock gets a ROW.

    An unmatched dock is written with `station_id` NULL, `confidence` 0.0 and a
    `method` that says WHY it did not match, rather than being absent. The
    difference matters: absent reads as "not looked at", and the whole point of
    this table is that the miss is auditable.
    """
    import pandas as pd

    matched = accepted[["station_id_legacy", "station_id", "name_modern",
                        "lon_modern", "lat_modern", "distance_m", "name_match",
                        "method", "confidence"]] if len(accepted) else None
    base = legacy.rename(columns={"name": "name_legacy",
                                  "lon": "lon_legacy", "lat": "lat_legacy",
                                  "trips": "legacy_trips"})[
        ["station_id_legacy", "name_legacy", "lon_legacy", "lat_legacy",
         "legacy_trips"]]
    if matched is not None:
        out = base.merge(matched, on="station_id_legacy", how="left")
    else:
        out = base.copy()
        for c in ("station_id", "name_modern", "lon_modern", "lat_modern",
                  "distance_m", "name_match", "method", "confidence"):
            out[c] = None
    miss = out["station_id"].isna()
    out.loc[miss, "method"] = "unmatched_no_candidate_within_ceiling"
    out.loc[miss, "confidence"] = 0.0
    out["name_match"] = out["name_match"].astype("boolean")
    out["run_at"] = run_at
    out = out[CROSSWALK_COLUMNS]
    con.execute("DELETE FROM staging.citibike_station_crosswalk")
    con.register("_cb_xw", out)
    try:
        cols = ", ".join(CROSSWALK_COLUMNS)
        # Named column lists, never SELECT * -- D72.
        con.execute(f"INSERT INTO staging.citibike_station_crosswalk ({cols}) "
                    f"SELECT {cols} FROM _cb_xw")
    finally:
        con.unregister("_cb_xw")
    assert isinstance(out, pd.DataFrame)
    return len(out)


#: Fill `station_id` on the LEGACY rows of the month table from the crosswalk.
#: Scoped to `era = 'legacy'` so a 2021+ row can never be touched, and run ONCE
#: by `loci citibike crosswalk` -- never from a migration, which db.init_schema
#: re-applies on every write connection.
APPLY_SQL = """
UPDATE staging.citibike_station_month AS s
   SET station_id = x.station_id
  FROM staging.citibike_station_crosswalk AS x
 WHERE s.era = 'legacy'
   AND s.station_id_legacy = x.station_id_legacy
   AND x.station_id IS NOT NULL
"""

#: The reverse: clear `station_id` on legacy rows the crosswalk no longer
#: matches, so a rebuilt crosswalk cannot leave a stale mapping behind.
UNAPPLY_SQL = """
UPDATE staging.citibike_station_month
   SET station_id = NULL
 WHERE era = 'legacy'
"""


def apply_crosswalk(con) -> dict:
    con.execute(UNAPPLY_SQL)
    con.execute(APPLY_SQL)
    row = con.execute("""
        SELECT count(*) FILTER (station_id IS NOT NULL) AS mapped,
               count(*)                                 AS legacy_rows
        FROM staging.citibike_station_month WHERE era = 'legacy'
    """).fetchone()
    return {"legacy_rows": int(row[1]), "legacy_rows_mapped": int(row[0])}


# ------------------------------------------------------------------ the build

def build(con, *, apply: bool = True, dry_run: bool = False,
          rebuild: bool = True) -> dict:
    """Rebuild the legacy roster, the crosswalk, and (optionally) apply it.

    Returns the report the CLI prints: the match rate by DOCK and by TRIP
    VOLUME, the tier mix, and the worst accepted distance. The two rates differ
    and both are stated: a crosswalk that misses 200 docks that saw 40 trips
    between them is a different object from one that misses the 20 busiest docks
    in Midtown.
    """
    run_at = dt.datetime.now()
    # `rebuild=False` leaves an already-built legacy roster alone. It exists for
    # tests and for a re-run that only wants to re-tier an unchanged roster; the
    # CLI always rebuilds, because the roster is DERIVED and a stale one is a
    # statement about a previous ingest.
    if rebuild:
        n_legacy = rebuild_legacy_roster(con)
    else:
        n_legacy = con.execute(
            "SELECT count(*) FROM staging.citibike_station_legacy").fetchone()[0]
    if n_legacy == 0:
        raise RuntimeError(
            "citibike crosswalk: staging.citibike_station_legacy is empty. The "
            "legacy months have not been ingested, so there is nothing to map. "
            "Run `loci citibike ingest --start 2013-06 --end 2021-01` first.")
    n_modern = con.execute(
        "SELECT count(*) FROM staging.citibike_station").fetchone()[0]
    if n_modern == 0:
        raise RuntimeError(
            "citibike crosswalk: staging.citibike_station is empty. The modern "
            "roster is the RIGHT-HAND SIDE of this join; without it every legacy "
            "dock would report as unmatched, which is a statement about the "
            "warehouse and not about the docks.")

    legacy = con.execute(
        "SELECT station_id_legacy, name, lon, lat, COALESCE(trips, 0) AS trips "
        "FROM staging.citibike_station_legacy").fetchdf()
    cand = con.execute(candidates_sql()).fetchdf()
    accepted, counts = choose(cand)

    trips_total = float(legacy["trips"].sum())
    trips_matched = float(accepted["legacy_trips"].sum()) if len(accepted) else 0.0
    rep = {
        "run_at": run_at.isoformat(timespec="seconds"),
        "legacy_stations": int(n_legacy),
        "modern_stations": int(n_modern),
        **counts,
        "match_rate_stations": counts["matched"] / max(n_legacy, 1),
        "match_rate_trips": trips_matched / max(trips_total, 1.0),
        "legacy_trips": int(trips_total),
        "legacy_trips_matched": int(trips_matched),
        "max_accepted_distance_m": (float(accepted["distance_m"].max())
                                    if len(accepted) else None),
        "report_floor": REPORT_FLOOR,
        "strict_m": XW_STRICT_M,
        "max_m": XW_MAX_M,
    }
    rep["below_report_floor"] = rep["match_rate_stations"] < REPORT_FLOOR
    if dry_run:
        rep["written"] = 0
        return rep
    rep["written"] = write_crosswalk(con, accepted, legacy, run_at)
    if apply:
        rep.update(apply_crosswalk(con))
    return rep
