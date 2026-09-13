"""Nearest DOT observation, per address: the count point and the camera.

    dot_point_id / dot_point_m           nearest ON-STREET bi-annual count
                                          point, straight-line metres
    dot_latest_round / _am / _md / _pm   that point's most recent complete
                                          round and its three counts
    camera_id / camera_m                 nearest NYCTMC traffic camera
    dot_context_run_at                   NULL = never run for this row

WHAT THIS IS FOR, AND WHAT IT IS NOT
---------------------------------------------------------------------------
It answers one question at the address grain: *is there a real, external
observation of this street anywhere nearby, and what did it see?* For the
handful of addresses within a block of a DOT screenline that is a genuine
ground truth to put on a card. For the rest of the city it is a distance that
says "no, there is nothing near here", which is equally worth knowing and
equally honest.

It is CONTEXT. Nothing here enters `gap_score`, `supply_ratio_vs_base`, a
recommendation grade or any rank. An address does not become an opportunity
because DOT counts pedestrians 80 m away, and it does not stop being one
because the nearest camera is 3 km off -- that is a fact about DOT's
programme, not about the address.

STRAIGHT-LINE, AND SAYING SO LOUDLY
---------------------------------------------------------------------------
`homes_400m`, `transit_entries_400m`, `jobs_400m`, `storefronts_400m` and
every supply ratio are NETWORK distances on the pedestrian walk graph, because
a straight-line 400 m in Manhattan can cross an avenue that takes 600 m of
walking to get around. These two columns are NOT. They are Euclidean metres in
EPSG:32618 (UTM 18N) -- as the crow flies -- and are therefore a LOWER BOUND
on the walk. Across a rail cut, a highway, a canal or a superblock the walk can
be several times the number in this column.

Why straight-line is the right call here anyway: 114 points and 969 cameras do
not justify a second 40-minute Dijkstra sweep, and the question is not a
catchment question. "Which observation is nearest" has a defensible
straight-line answer; "how many homes can walk here" does not. The tradeoff is
stated in the column comments in sql/022_dot.sql and must be repeated wherever
these numbers are rendered. NEVER compare `dot_point_m` or `camera_m` to a
`*_400m` column: they are different metrics on different graphs.

THE REPROJECTION, EXPLICITLY
---------------------------------------------------------------------------
DuckDB GEOMETRY carries no SRID and `lon`/`lat` here are plain DOUBLEs, so
nothing in the database would catch degrees being treated as metres. Both
sides are transformed 4326 -> 32618 with `always_xy=True` (without it pyproj
hands back (lat, lon) for 4326 and every distance is wrong), and the nearest
neighbour is found with a cKDTree in projected metres -- the same convention
model/age_fit.py and model/density_elasticity.py use. UTM 18N over New York
City has a scale error well under 0.1%, i.e. under a metre at the distances
these columns report, which is far inside the error introduced by calling a
walk a straight line.

BRIDGE MIDPOINTS ARE EXCLUDED FROM THE NEAREST-POINT SEARCH
---------------------------------------------------------------------------
`loc` 101-114 sit in the middle of East River and Harlem River crossings.
They are ingested (see sources/cities/nyc/dot_pedestrian.py) and excluded
here: the nearest sidewalk observation to a Brooklyn Heights address is not a
point 400 m out over the water on the Brooklyn Bridge. `--include-bridges`
exists for anyone who wants to argue otherwise, and is off.

"LATEST ROUND" IS PER POINT, NOT GLOBAL
---------------------------------------------------------------------------
`dot_latest_round` is the most recent round AT THAT POINT carrying all three
periods -- which is not always the feed's latest round, because points enter
and leave the programme (342 of 12,654 possible cells are absent). Using the
global latest would write NULL counts at a point that was simply not counted
in May 2026, and a NULL count is indistinguishable from a quiet street. The
round is stamped per address so a reader can see they are looking at 2018 and
not 2026.

UPDATE-ONLY, RESET-THEN-UPDATE (D48/D57/D58/D61/D62/D73)
---------------------------------------------------------------------------
`write_context` issues ONLY `UPDATE analysis.address SET <DOT_CONTEXT_COLUMNS>`.
Never an INSERT, never a DELETE, and the SET list is asserted disjoint from
the screen's own columns and from every sibling annotation before the
statement runs. `loci address-gaps` DELETEs and re-INSERTs the rows these
columns live on, so this command -- like every other annotation -- must be
re-applied after every screen re-run. `dot_context_run_at IS NULL` is the flag
that says it has not been.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. THE COUNT POINTS ARE NOT A SAMPLE OF THE CITY. DOT chose 114 locations for
   traffic engineering, concentrated on busy commercial corridors. An address
   200 m from one is near a corridor DOT thought worth counting, which is
   itself a selection effect, and the count belongs to the SCREENLINE, not to
   the address: a number 200 m away on a different street is not a
   measurement of this block.
2. A CAMERA'S POSITION IS THE POLE, NOT THE VIEW. No bearing, no field of
   view, no height is published. `camera_m` = 60 does not mean this address is
   in frame.
3. THE CAMERA GRADIENT IS DOT'S, NOT THE CITY'S. 376 cameras in Manhattan and
   81 in the Bronx, sited at signalised intersections on arterials. "Share of
   addresses within 400 m of a camera" is a statement about arterial proximity
   as much as about surveillance coverage, and must never be read as exposure,
   footfall or activity.
4. THE TWO DISTANCES ARE NOT INDEPENDENT OF ANYTHING. Both are large exactly
   where the city is quiet and small exactly where it is busy -- which is the
   same gradient as homes_400m, jobs_400m and transit_entries_400m. Never add
   them to anything, and never treat a short distance as a demand signal.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

#: EPSG:32618 = WGS 84 / UTM zone 18N, METRES. The project's metric CRS for
#: nearest-neighbour work (model/age_fit.py, model/density_elasticity.py).
METRIC_CRS = "EPSG:32618"

DOT_CONTEXT_COLUMNS = [
    "dot_point_id",
    "dot_point_m",
    "dot_latest_round",
    "dot_latest_am",
    "dot_latest_md",
    "dot_latest_pm",
    "camera_id",
    "camera_m",
    "dot_context_run_at",
]


# ------------------------------------------------------------- the reads

def _to_metric(lon, lat) -> np.ndarray:
    """(lon, lat) degrees -> (N, 2) metres in EPSG:32618.

    `always_xy=True` is REQUIRED: without it pyproj reads EPSG:4326 as
    (lat, lon) and every distance below is silently nonsense.
    """
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True)
    x, y = tf.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    return np.column_stack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])


def load_count_points(con, include_bridges: bool = False) -> pd.DataFrame:
    """One row per count point: point_id, lon, lat, and the point's OWN latest
    complete round with its three counts.

    Complete = all three periods present. An incomplete round is skipped
    rather than written with NULLs, because a NULL AM count reads as a quiet
    morning and it is not one.
    """
    where = "" if include_bridges else "WHERE NOT COALESCE(is_bridge, FALSE)"
    df = con.execute(f"""
        WITH src AS (SELECT * FROM staging.dot_pedestrian_count {where}),
        per_round AS (
            SELECT point_id, round,
                   MAX(count) FILTER (WHERE period = 'am') AS am,
                   MAX(count) FILTER (WHERE period = 'md') AS md,
                   MAX(count) FILTER (WHERE period = 'pm') AS pm,
                   COUNT(DISTINCT period)                  AS n_periods
            FROM src GROUP BY point_id, round
        ),
        latest AS (
            SELECT point_id, round, am, md, pm,
                   ROW_NUMBER() OVER (PARTITION BY point_id ORDER BY round DESC) AS rn
            FROM per_round WHERE n_periods = 3
        ),
        geo AS (
            SELECT point_id, ANY_VALUE(lon) AS lon, ANY_VALUE(lat) AS lat,
                   ANY_VALUE(borough) AS borough, ANY_VALUE(street) AS street
            FROM src GROUP BY point_id
        )
        SELECT g.point_id, g.lon, g.lat, g.borough, g.street,
               l.round AS latest_round, l.am, l.md, l.pm
        FROM geo g LEFT JOIN latest l ON l.point_id = g.point_id AND l.rn = 1
        WHERE g.lon IS NOT NULL AND g.lat IS NOT NULL
        ORDER BY g.point_id
    """).fetchdf()
    if df.empty:
        raise RuntimeError(
            "staging.dot_pedestrian_count has no usable points. Run "
            "`loci dot-counts ingest` first -- writing NULL into every "
            "dot_point_m would read as 'no address is near a count point', "
            "which is a confident wrong answer.")
    return df


def load_cameras(con) -> pd.DataFrame:
    """One row per camera with a position. `is_online` is NOT filtered on:
    969/969 read true at verification, so it is a publication flag rather than
    a liveness one, and filtering a universe on a flag that is always true is
    a filter that will silently start biting the day it stops being true.
    """
    df = con.execute("""
        SELECT camera_id, lon, lat, name, borough, is_online
        FROM staging.dot_camera
        WHERE lon IS NOT NULL AND lat IS NOT NULL
        ORDER BY camera_id
    """).fetchdf()
    if df.empty:
        raise RuntimeError(
            "staging.dot_camera is empty. Run `loci dot-cameras ingest` first.")
    return df


def load_address_points(con, boroughs: list[str] | None) -> pd.DataFrame:
    """address_id, borough, lon, lat for the addresses in scope."""
    sql = ("SELECT address_id, borough, lon, lat FROM analysis.address "
           "WHERE lon IS NOT NULL AND lat IS NOT NULL")
    params: list = []
    if boroughs:
        sql += f" AND borough IN ({', '.join('?' for _ in boroughs)})"
        params = list(boroughs)
    return con.execute(sql, params).fetchdf()


# ------------------------------------------------------------- the compute

def compute_context(con, boroughs: list[str] | None,
                    include_bridges: bool = False) -> tuple[pd.DataFrame, dict]:
    """(frame of address_id/borough + DOT_CONTEXT_COLUMNS, report).

    READ-ONLY on the warehouse: it SELECTs and writes nothing.
    """
    from scipy.spatial import cKDTree

    pts = load_count_points(con, include_bridges=include_bridges)
    cams = load_cameras(con)
    addr = load_address_points(con, boroughs)
    if addr.empty:
        raise RuntimeError(
            f"no addresses in analysis.address for boroughs={boroughs}. An "
            f"empty frame would RESET every DOT column to NULL and write "
            f"nothing back.")

    a_xy = _to_metric(addr["lon"], addr["lat"])
    p_xy = _to_metric(pts["lon"], pts["lat"])
    c_xy = _to_metric(cams["lon"], cams["lat"])

    p_dist, p_i = cKDTree(p_xy).query(a_xy, k=1)
    c_dist, c_i = cKDTree(c_xy).query(a_xy, k=1)

    run_at = dt.datetime.now().replace(microsecond=0)
    near_pts = pts.iloc[p_i].reset_index(drop=True)
    near_cams = cams.iloc[c_i].reset_index(drop=True)

    out = pd.DataFrame({
        "address_id": addr["address_id"].to_numpy(),
        "borough": addr["borough"].to_numpy(),
        "dot_point_id": near_pts["point_id"].to_numpy(),
        # UNCAPPED, deliberately. Most of the city is kilometres from a count
        # point and the honest number is large; a cap would turn a measured
        # distance into a censored one and require a censoring flag to say so.
        "dot_point_m": np.asarray(p_dist, dtype=float),
        "dot_latest_round": near_pts["latest_round"].to_numpy(),
        "dot_latest_am": near_pts["am"].to_numpy(),
        "dot_latest_md": near_pts["md"].to_numpy(),
        "dot_latest_pm": near_pts["pm"].to_numpy(),
        "camera_id": near_cams["camera_id"].to_numpy(),
        "camera_m": np.asarray(c_dist, dtype=float),
        "dot_context_run_at": run_at,
    })
    for col in ("dot_point_id", "dot_latest_am", "dot_latest_md", "dot_latest_pm"):
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")

    def _q(series, q):
        return float(np.nanpercentile(series.astype(float), q)) if len(series) else float("nan")

    by_boro = {}
    for boro, g in out.groupby("borough", dropna=False):
        by_boro[str(boro)] = {
            "addresses": int(len(g)),
            "dot_point_m_p50": _q(g["dot_point_m"], 50),
            "dot_point_m_p90": _q(g["dot_point_m"], 90),
            "camera_m_p50": _q(g["camera_m"], 50),
            "camera_m_p90": _q(g["camera_m"], 90),
            "within_400m_of_camera": float((g["camera_m"] <= 400).mean()),
            "within_400m_of_count_point": float((g["dot_point_m"] <= 400).mean()),
        }
    report = {
        "boroughs": list(boroughs) if boroughs else "ALL",
        "metric_crs": METRIC_CRS,
        "distance": "straight-line (Euclidean in EPSG:32618), NOT network",
        "count_points": int(len(pts)),
        "count_points_with_complete_latest_round": int(pts["latest_round"].notna().sum()),
        "include_bridges": bool(include_bridges),
        "cameras": int(len(cams)),
        "addresses": int(len(out)),
        "dot_point_m_p50": _q(out["dot_point_m"], 50),
        "camera_m_p50": _q(out["camera_m"], 50),
        "within_400m_of_camera": float((out["camera_m"] <= 400).mean()),
        "within_400m_of_count_point": float((out["dot_point_m"] <= 400).mean()),
        "by_borough": by_boro,
        "run_at": run_at.isoformat(timespec="seconds"),
    }
    return out, report


# --------------------------------------------------------------- the write

def _guard(cols: list[str]) -> None:
    """Refuse to write if the SET list touches a column another module owns."""
    forbidden: set[str] = set()
    try:
        from loci.model.address_access import ACCESS_COLUMNS
        from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
        from loci.model.address_gaps import (
            ADDRESS_CATEGORY_SCREEN_COLUMNS,
            ADDRESS_COLUMNS,
        )
        from loci.model.dev_pipeline import PIPELINE_COLUMNS
        from loci.model.storefronts import AGE_FIT_COLUMNS, STOREFRONT_COLUMNS
        from loci.model.supply_ratio import (
            ADDRESS_RATIO_COLUMNS,
            CATEGORY_RATIO_COLUMNS,
        )
        forbidden |= set(ADDRESS_COLUMNS) | set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
        forbidden |= set(PIPELINE_COLUMNS) | set(STOREFRONT_COLUMNS)
        forbidden |= set(AGE_FIT_COLUMNS) | set(DEMAND_ANNOTATION_COLUMNS)
        forbidden |= set(ADDRESS_RATIO_COLUMNS) | set(CATEGORY_RATIO_COLUMNS)
        forbidden |= set(ACCESS_COLUMNS)
    except ImportError:                                     # pragma: no cover
        pass
    overlap = sorted(set(cols) & forbidden)
    if overlap:
        raise RuntimeError(
            f"dot address-context would clobber analysis.address columns: {overlap}")


def write_context(con, df: pd.DataFrame, boroughs: list[str] | None) -> int:
    """UPDATE-only on analysis.address. RESET then UPDATE, in scope."""
    _guard(DOT_CONTEXT_COLUMNS)
    absent = [c for c in DOT_CONTEXT_COLUMNS if c not in df.columns]
    if absent:
        raise RuntimeError(
            f"frame is missing {absent}; every column in DOT_CONTEXT_COLUMNS is "
            f"reset to NULL below, so a partial frame would blank them "
            f"permanently.")
    reset = ", ".join(f"{c} = NULL" for c in DOT_CONTEXT_COLUMNS)
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        con.execute(
            f"UPDATE analysis.address SET {reset} WHERE borough IN ({holes})",
            list(boroughs))
    else:
        con.execute(f"UPDATE analysis.address SET {reset}")
    if df.empty:
        return 0
    con.register("_dotctx", df[["address_id", "borough", *DOT_CONTEXT_COLUMNS]])
    try:
        sets = ", ".join(f"{c} = _dotctx.{c}" for c in DOT_CONTEXT_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address AS a SET {sets}
            FROM _dotctx
            WHERE a.address_id = _dotctx.address_id AND a.borough = _dotctx.borough
        """)
    finally:
        con.unregister("_dotctx")
    return len(df)


def build_context(con, boroughs: list[str] | None,
                  include_bridges: bool = False,
                  dry_run: bool = False) -> tuple[pd.DataFrame, dict]:
    """compute + write."""
    df, report = compute_context(con, boroughs, include_bridges=include_bridges)
    if not dry_run:
        report["_written"] = write_context(con, df, boroughs)
    report["dry_run"] = bool(dry_run)
    return df, report
