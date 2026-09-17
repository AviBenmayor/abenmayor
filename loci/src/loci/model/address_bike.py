"""Walkable Citi Bike activity at address grain (Citi Bike phase 1).

    analysis.address_bike_station(address_id, station_id, dist_m)   -- persisted
    analysis.address.bike_starts_400m
    analysis.address.bike_ends_400m
    analysis.address.bike_evening_ends_share_400m
    analysis.address.bike_casual_share_400m
    analysis.address.bike_window / bike_radius_m / bike_run_at

WHY THIS EXISTS
---------------------------------------------------------------------------
D76's foot-traffic proxy is subway ENTRIES, and its two named defects are that
it sees only the tap-IN direction and that it is zero for 65% of Brooklyn
addresses. Citi Bike fixes both: a trip publishes BOTH ends, and the dock
network reaches Bay Ridge, Greenpoint and Red Hook, which the 400 m subway
catchment does not. `bike_ends_400m` is the first ARRIVAL measure in the
warehouse -- the flow that buys something on the way home rather than the flow
leaving in the morning.

NOTHING ABOUT THE GEOGRAPHY IS NEW
---------------------------------------------------------------------------
Same walk graph, same `_prune` + `_to_csr` CSR, same bounded scipy Dijkstra,
same 400 m NETWORK radius, same collapse-to-distinct-node trick as
`model/address_transit_profile.py` -- `catchment_pairs` is IMPORTED from it, not
re-implemented, so a bug fixed in one is fixed in both. The only new thing is
what sits at the target points: 2,300-odd docks instead of 2,000-odd subway
doors.

THE PERSISTED REACHABLE SET
---------------------------------------------------------------------------
`analysis.address_bike_station` is to this build what `analysis.address_entrance`
is to the transit profile: (address_id, station_id, dist_m) and NO WEIGHT. The
sweep is the expensive object (tens of minutes); the window, the day type and
the member/casual split all move, and the persisted distances must outlive all
three. Re-running with a different window is then a join, not another Dijkstra.

THE DENOMINATOR IS THE WINDOW, NOT THE DOCK
---------------------------------------------------------------------------
`bike_starts_400m` is total weekday starts at reachable docks over the window,
divided by the number of NON-HOLIDAY WEEKDAY DATES IN THE WINDOW -- one constant
for every station and every address, taken from the calendar (`days_in_cell`).

The alternative -- dividing each dock by the months it was actually active --
was rejected: it makes a dock installed last month look identical to one that
has been there for a decade, and, worse, it makes the SUM over several docks
uninterpretable, because each term would carry a different denominator. Under
the convention used here a dock installed three months into a twelve-month
window honestly contributes only the three months it delivered, which is what
"average weekday activity within a five-minute walk over the last year" means.
The cost is that a brand-new dock reads low; `staging.citibike_station.
first_month` is how a reader sees that, and it is why the default window is the
LATEST TWELVE MONTHS rather than the whole panel.

ZERO IS A VALUE; TWO OF THE FOUR COLUMNS ARE NULLABLE, AND THEY ARE THE RATIOS
---------------------------------------------------------------------------
Owner rule 2026-09-13: no eligibility gate, never drop an address. Every lot
address in scope gets a `bike_starts_400m` and a `bike_ends_400m`, and 0 means
"no dock within a five-minute walk" -- a real observation about the OPERATOR'S
network, never "nobody walks here".

The two SHARES are NULL where their denominator is zero, exactly as
`transit_am_pm_share_400m` is NULL where pm_peak is zero. A share of no
arrivals does not exist, and writing 0 would assert "a pure commuter dock",
which is a claim about a dock that is not there. NULL here means undefined;
`bike_run_at IS NULL` means the command has never run.

BOTH FRAMES (owner ruling 4, 2026-09-16 -- was LOT ROWS ONLY)
---------------------------------------------------------------------------
D84 put a second sampling frame (street midpoints every 100 m) into
`analysis.address`. Until 2026-09-16 this build wrote the LOT frame only, on
the grounds that it was the frame the cards read and that sweeping both doubles
a Dijkstra that dominates the runtime; the street rows kept NULL. The owner
reversed it: the street frame gets everything the lot frame has. The street
rows were reading as "not computed", indistinguishable from "no dock here", on
exactly the industrial and newly-cut streets the frame exists to see.

ONE SWEEP, NOT TWO. The street frame goes through THIS function, THIS graph,
THIS radius -- `load_address_points` simply stopped filtering. There is no
parallel path, because a parallel path is how two "network metres" come to mean
two things. The cost is real (+18% query nodes) and is paid once.

The widening cannot move a lot-frame number: the sweep is one SSSP per distinct
query node over a graph built from the pickle alone, so an extra query node
adds rows and perturbs none. Pinned by
`tests/test_street_frame_coverage.py::test_widening_the_sweep_leaves_lot_pairs_identical`.

DO NOT MIRROR EDGES if you touch `_to_csr`. `score/access.py` documents why:
scipy's `csr_matrix` SUMS duplicate (row, col) entries, so manually mirroring an
undirected edge DOUBLES its length. This module reuses the graph and does not
build one.

NOT A SCORE INPUT
---------------------------------------------------------------------------
Card context only, on the same footing as `transit_entries_400m` under D76.
Nothing here enters `gap_score`, `supply_ratio_vs_base` or any recommendation
grade, and `BIKE_ADDRESS_COLUMNS` is asserted disjoint from every sibling
annotation before the UPDATE runs.

WHAT THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. DOCK PLACEMENT IS THE DOMINANT TERM. Zero means the operator has not built
   there; it is correlated with income and it is not a statement about the
   sidewalk. Any cross-neighbourhood comparison of levels is partly a
   comparison of Lyft's and DOT's capital plans.
2. CAPACITY CENSORS THE TOP. A full dock turns an arrival into an arrival
   somewhere else, hardest at the busiest station-hours.
3. THE FLEET CHANGED MID-PANEL (72% of 2026-04 trips were electric), which is
   why the window is the latest twelve months and not the whole series.
4. `bike_casual_share_400m` IS NOT A TOURIST COUNT: a "member" is anyone with a
   subscription and a "casual" rider anyone on a single ride or day pass.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pickle

import numpy as np
import pandas as pd

from loci.model.address_access import DEFAULT_RADIUS_M
from loci.model.address_transit_profile import catchment_pairs
from loci.model.conveniences import graph_version
from loci.model.supply_ratio import BATCH
from loci.score.access import MIN_COMPONENT, _prune, _to_csr
from loci.score.walkgraph import OUT as GRAPH_PATH

#: The ONLY columns this module may name in a SET clause on analysis.address.
BIKE_ADDRESS_COLUMNS = [
    "bike_starts_400m",
    "bike_ends_400m",
    "bike_evening_ends_share_400m",
    "bike_casual_share_400m",
    "bike_window",
    "bike_radius_m",
    "bike_run_at",
]

#: Twelve months, so the window covers a full seasonal cycle. A three-month
#: window (the transit default) would be a summer reading, and Citi Bike's
#: seasonality is far larger than the subway's -- August runs ~2.5x February.
DEFAULT_WINDOW_MONTHS = 12

#: Above this share of the persisted reachable set missing from the current
#: window, refuse the rebuild: that is an id-space change, not attrition.
#: Citi Bike retires a handful of docks a year out of ~2,300.
MAX_RETIRED_SHARE = 0.5


# ------------------------------------------------------------- the weights

#: One row per dock over the window. Everything the four measures need, and
#: nothing else -- the daypart shape stays in the staging table.
#:
#: `weekday_days` is `any_value(days_in_cell)` per (month, day_type) summed over
#: the window: the CALENDAR count of non-holiday weekdays, identical for every
#: dock, which is what makes the per-address SUM over docks divisible by a
#: single denominator.
STATION_WEIGHTS_SQL = """
WITH w AS (
    SELECT * FROM staging.citibike_station_month
    WHERE month BETWEEN ? AND ?
),
s AS (
    SELECT station_id,
           sum(starts) FILTER (day_type = 'weekday')        AS weekday_starts,
           sum(ends)   FILTER (day_type = 'weekday')        AS weekday_ends,
           sum(ends)                                        AS all_ends,
           sum(ends) FILTER (daypart = 'evening'
                          OR day_type IN ('saturday', 'sunday'))
                                                            AS evening_weekend_ends,
           sum(starts)                                      AS all_starts,
           sum(casual_starts)                               AS casual_starts,
           sum(member_starts)                               AS member_starts
    FROM w GROUP BY 1
)
SELECT s.*, st.lon, st.lat, st.name AS station_name,
       st.first_month, st.last_month, st.months_active
FROM s JOIN staging.citibike_station st USING (station_id)
WHERE st.lon IS NOT NULL AND st.lat IS NOT NULL
"""

#: The divisor. One row; a CALENDAR count, not an observed one.
WEEKDAY_DAYS_SQL = """
WITH d AS (
    SELECT month, any_value(days_in_cell) AS days
    FROM staging.citibike_station_month
    WHERE month BETWEEN ? AND ? AND day_type = 'weekday'
    GROUP BY 1
)
SELECT sum(days) AS weekday_days, count(*) AS months FROM d
"""


def window_bounds(con, months: int = DEFAULT_WINDOW_MONTHS) -> tuple[dt.date, dt.date]:
    """The latest `months` calendar months present in the panel, inclusive.

    Derived from the TABLE's own max month, never from today's date: the file
    for a month lands days into the next one, and anchoring on `today` would
    silently shorten the window every time it is run early in a month.
    """
    row = con.execute(
        "SELECT min(month), max(month), count(DISTINCT month) "
        "FROM staging.citibike_station_month").fetchone()
    if not row or row[1] is None:
        raise RuntimeError(
            "staging.citibike_station_month is empty: run `loci citibike ingest` "
            "first. Refusing to write a bike measure of zero for every address, "
            "which is indistinguishable from a city with no bike share.")
    last = row[1]
    y, m = last.year, last.month - (months - 1)
    while m <= 0:
        y, m = y - 1, m + 12
    first = dt.date(y, m, 1)
    first = max(first, row[0])
    return first, last


def station_weights(con, first: dt.date, last: dt.date) -> tuple[pd.DataFrame, dict]:
    """(one row per dock over the window, report). RAISES on an empty window."""
    df = con.execute(STATION_WEIGHTS_SQL, [first, last]).fetchdf()
    days = con.execute(WEEKDAY_DAYS_SQL, [first, last]).fetchone()
    if df.empty or not days or not days[0]:
        raise RuntimeError(
            f"no Citi Bike station-months between {first} and {last}. Refusing to "
            f"build an address measure out of an empty window -- every address "
            f"would read 0, which is exactly the silent zero this project "
            f"refuses to ingest.")
    weekday_days = int(days[0])
    rep = {
        "window": f"{first:%Y-%m}..{last:%Y-%m}",
        "months": int(days[1]),
        "weekday_days": weekday_days,
        "stations": int(len(df)),
        "weekday_starts": int(df["weekday_starts"].fillna(0).sum()),
        "weekday_ends": int(df["weekday_ends"].fillna(0).sum()),
        "all_ends": int(df["all_ends"].fillna(0).sum()),
        "casual_share_citywide": float(
            df["casual_starts"].sum() / max(df["all_starts"].sum(), 1)),
    }
    for c in ("weekday_starts", "weekday_ends", "all_ends", "evening_weekend_ends",
              "all_starts", "casual_starts", "member_starts"):
        df[c] = df[c].fillna(0).astype("float64")
    return df, rep


# --------------------------------------------------------------- the sweep

def load_address_points(con, boroughs: list[str] | None,
                        frames: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Every address in scope to measure -- BOTH sampling frames.

    `frames=None` means the whole `analysis.address` universe (owner ruling 4,
    2026-09-16). `frames=('lot',)` reproduces the pre-2026-09-16 behaviour and
    exists ONLY so a test can prove the two agree on the lot rows; nothing in
    the build passes it.

    WIDENING THIS DOES NOT MOVE AN EXISTING NUMBER, and that is a property of
    the algorithm rather than a hope. The sweep is a single-source shortest
    path from each distinct query NODE over a graph built from the pickle alone
    (`_prune` then `_to_csr`, neither of which sees the address frame), so
    adding query nodes adds rows and changes none: node A's distance to dock S
    does not depend on whether node B was also in the batch.
    `tests/test_street_frame_coverage.py` pins it by running the sweep both
    ways and asserting the lot pairs are equal to the byte.
    """
    where = ["lon IS NOT NULL", "lat IS NOT NULL"]
    params: list = []
    if frames is not None:
        where.append(
            f"COALESCE(frame, 'lot') IN ({', '.join('?' for _ in frames)})")
        params += list(frames)
    if boroughs:
        where.append(f"borough IN ({', '.join('?' for _ in boroughs)})")
        params += list(boroughs)
    return con.execute(
        f"SELECT address_id, borough, lon, lat FROM analysis.address "
        f"WHERE {' AND '.join(where)}", params).fetchdf()


def build_reachable(con, boroughs: list[str] | None, stations: pd.DataFrame,
                    radius_m: float = DEFAULT_RADIUS_M,
                    graph_path: pathlib.Path = GRAPH_PATH,
                    batch: int = BATCH,
                    frames: tuple[str, ...] | None = None) -> tuple[pd.DataFrame, dict]:
    """(address_id, borough, station_id, dist_m) for every address in scope --
    both frames -- and every dock it can WALK to inside `radius_m` network
    metres.

    READ-ONLY on the warehouse.
    """
    import osmnx as ox

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)

    s_nodes = ox.distance.nearest_nodes(
        Gp, X=stations["lon"].tolist(), Y=stations["lat"].tolist())
    s_nidx = np.array([idx[n] for n in np.atleast_1d(s_nodes)], dtype=np.int64)

    addr = load_address_points(con, boroughs, frames=frames)
    if addr.empty:
        raise RuntimeError(
            f"no addresses in analysis.address for boroughs={boroughs}, "
            f"frames={frames or 'ALL'}. Run `loci address-gaps` first; an empty "
            f"frame would DELETE the reachable set for that scope and write "
            f"nothing back.")
    a_nodes = ox.distance.nearest_nodes(
        Gp, X=addr["lon"].tolist(), Y=addr["lat"].tolist())
    a_nidx = np.array([idx[n] for n in np.atleast_1d(a_nodes)], dtype=np.int64)
    # Identical collapse to compute_access / build_reachable: a 400 m catchment
    # cannot tell two doorways on one block apart, so the sweep runs once per
    # distinct NODE and is broadcast back to the addresses on it.
    uniq, inv = np.unique(a_nidx, return_inverse=True)

    qi, ti, dist = catchment_pairs(A, uniq, s_nidx, radius_m=radius_m, batch=batch)
    node_pairs = pd.DataFrame({"q": qi, "t": ti, "dist_m": dist})
    st = stations[["station_id"]].copy()
    st["t"] = np.arange(len(st), dtype=np.int64)
    node_pairs = node_pairs.merge(st, on="t", how="inner")

    left = pd.DataFrame({"address_id": addr["address_id"].to_numpy(),
                         "borough": addr["borough"].to_numpy(),
                         "q": inv.astype(np.int64)})
    out = left.merge(node_pairs[["q", "station_id", "dist_m"]], on="q", how="inner")
    out = out.drop(columns=["q"])
    report = {
        "boroughs": list(boroughs) if boroughs else "ALL",
        "frames": list(frames) if frames else "ALL",
        "radius_m": float(radius_m),
        "graph_version": graph_version(graph_path),
        "addresses_in_scope": int(len(addr)),
        "query_nodes": int(uniq.size),
        "station_points": int(len(stations)),
        "pairs": int(len(out)),
        "addresses_with_a_station": int(out["address_id"].nunique()),
        "coverage_share": float(out["address_id"].nunique() / max(len(addr), 1)),
    }
    return out, report


# ------------------------------------------------------------ the measures

def measures(reachable: pd.DataFrame, weights: pd.DataFrame,
             weekday_days: int) -> pd.DataFrame:
    """(address_id, the four measures) for the addresses with >= 1 reachable dock.

    Aggregated in an IN-MEMORY DuckDB rather than pandas, for the same reason
    `profile_long` is: the natural pandas route materialises the pair table
    times every weight column, and this step must run identically against a
    read-only snapshot.

    Two docks reachable from one address are SUMMED, not deduplicated: they are
    two different docks and their trips are different trips. (Contrast the
    transit split, where two doors of ONE complex each carry 1/n of it.)
    """
    import duckdb

    if weekday_days <= 0:                                   # pragma: no cover
        raise RuntimeError("weekday_days must be positive; it is the divisor.")
    mem = duckdb.connect()
    try:
        mem.register("reach", reachable[["address_id", "station_id"]])
        mem.register("w", weights[[
            "station_id", "weekday_starts", "weekday_ends", "all_ends",
            "evening_weekend_ends", "all_starts", "casual_starts"]])
        return mem.execute(f"""
            SELECT r.address_id,
                   sum(w.weekday_starts) / {weekday_days}.0 AS bike_starts_400m,
                   sum(w.weekday_ends)   / {weekday_days}.0 AS bike_ends_400m,
                   -- NULL, not 0, where the denominator does not exist. A share
                   -- of no arrivals is undefined; a 0 would assert a pure
                   -- commuter dock at a place with no dock at all.
                   CASE WHEN sum(w.all_ends) > 0
                        THEN sum(w.evening_weekend_ends) / sum(w.all_ends)
                   END AS bike_evening_ends_share_400m,
                   CASE WHEN sum(w.all_starts) > 0
                        THEN sum(w.casual_starts) / sum(w.all_starts)
                   END AS bike_casual_share_400m
            FROM reach r JOIN w USING (station_id)
            GROUP BY 1
        """).fetchdf()
    finally:
        mem.close()


def check_shares_in_bounds(df: pd.DataFrame) -> dict:
    """Both shares are shares. A value outside [0, 1] means the numerator is not
    a subset of the denominator -- e.g. an evening weekend arrival counted twice
    by an OR that became a sum. RAISES, because a 1.4 share reads as a plausible
    'very evening-heavy' number to every downstream reader."""
    rep = {}
    for col in ("bike_evening_ends_share_400m", "bike_casual_share_400m"):
        v = df[col].dropna()
        lo, hi = (float(v.min()), float(v.max())) if len(v) else (float("nan"),) * 2
        rep[col] = {"n": int(len(v)), "min": lo, "max": hi,
                    "median": float(v.median()) if len(v) else float("nan")}
        if len(v) and (lo < 0 or hi > 1 + 1e-12):
            raise RuntimeError(
                f"{col} ranges [{lo}, {hi}] -- outside [0, 1]. The numerator is "
                f"not a subset of the denominator; the evening/weekend union is "
                f"the usual suspect (a Saturday evening arrival is ONE arrival).")
    return rep


# ---------------------------------------------------------------- the write

def _guard(cols: list[str]) -> None:
    """Refuse to write if the SET list touches a column another module owns."""
    from loci.model.address_access import ACCESS_COLUMNS
    from loci.model.address_access import _guard as access_guard
    from loci.model.address_transit_profile import PROFILE_ADDRESS_COLUMNS

    access_guard(cols)                       # every sibling annotation
    overlap = sorted(set(cols) & (set(ACCESS_COLUMNS) | set(PROFILE_ADDRESS_COLUMNS)))
    if overlap:
        raise RuntimeError(
            f"citibike address-measures would clobber columns owned elsewhere: "
            f"{overlap}")


def write_measures(con, reachable: pd.DataFrame, meas: pd.DataFrame,
                   boroughs: list[str] | None, meta: dict) -> dict:
    """DELETE-then-INSERT the reachable set IN SCOPE, then UPDATE the columns
    IN SCOPE. Scoped by borough, exactly as every sibling builder is."""
    _guard(BIKE_ADDRESS_COLUMNS)
    run_at = meta["run_at"]
    where, params = "", []
    if boroughs:
        where = f"WHERE borough IN ({', '.join('?' for _ in boroughs)})"
        params = list(boroughs)

    con.execute(f"DELETE FROM analysis.address_bike_station {where}", params)
    pairs = reachable.copy()
    pairs["radius_m"] = float(meta["radius_m"])
    pairs["graph_version"] = meta["graph_version"]
    pairs["run_at"] = run_at
    con.register("_bs", pairs[["address_id", "borough", "station_id", "dist_m",
                               "radius_m", "graph_version", "run_at"]])
    m = meas.copy()
    m["bike_window"] = meta["window"]
    m["bike_radius_m"] = float(meta["radius_m"])
    m["bike_run_at"] = run_at
    con.register("_bm", m[["address_id", *BIKE_ADDRESS_COLUMNS]])
    try:
        con.execute(
            "INSERT INTO analysis.address_bike_station "
            "(address_id, borough, station_id, dist_m, radius_m, graph_version, run_at) "
            "SELECT address_id, borough, station_id, dist_m, radius_m, graph_version, "
            "       run_at FROM _bs")
        # RESET first: an address that had a dock last run and none now must go
        # back to 0/NULL rather than keeping a stale number.
        reset = ", ".join(f"{c} = NULL" for c in BIKE_ADDRESS_COLUMNS)
        scope = (f"WHERE borough IN ({', '.join('?' for _ in boroughs)})"
                 if boroughs else "")
        con.execute(f"UPDATE analysis.address SET {reset} {scope}",
                    list(boroughs) if boroughs else [])
        sets = ", ".join(f"{c} = _bm.{c}" for c in BIKE_ADDRESS_COLUMNS)
        con.execute(f"UPDATE analysis.address AS a SET {sets} "
                    f"FROM _bm WHERE a.address_id = _bm.address_id")
        # THE ZEROES, EXPLICITLY. An in-scope address with no reachable dock
        # gets 0.0 levels, NULL shares and a stamped run_at: "measured, nothing
        # within a five-minute walk". Without this the absence would read as
        # "never run" and the no-eligibility-gate rule would be broken by
        # omission rather than by a filter.
        #
        # 2026-09-16 (owner ruling 4): no longer restricted to the lot frame.
        # It was the frame filter HERE, not the sweep, that decided whether a
        # street row read as "measured, no dock" or as "never computed", and a
        # street row silently kept the second.
        zero_scope = "lon IS NOT NULL AND lat IS NOT NULL"
        if boroughs:
            zero_scope += f" AND borough IN ({', '.join('?' for _ in boroughs)})"
        con.execute(
            f"UPDATE analysis.address SET bike_starts_400m = 0.0, "
            f"    bike_ends_400m = 0.0, bike_window = ?, bike_radius_m = ?, "
            f"    bike_run_at = ? "
            f"WHERE bike_run_at IS NULL AND {zero_scope}",
            [meta["window"], float(meta["radius_m"]), run_at,
             *(boroughs or [])])
    finally:
        for v in ("_bs", "_bm"):
            con.unregister(v)
    return {
        "address_bike_station_rows": int(len(pairs)),
        "addresses_with_a_station": int(len(m)),
        "addresses_zeroed": int(con.execute(
            "SELECT count(*) FROM analysis.address WHERE bike_run_at IS NOT NULL "
            "AND bike_starts_400m = 0").fetchone()[0]),
    }


# ------------------------------------------------------------ the read-back

VALIDATION_SQL = """
-- Proves on the WAREHOUSE (not on the frames this run built):
--   0. BOTH SAMPLING FRAMES appear, broken out. The street frame carried zero
--      rows here until 2026-09-16 and a citywide roll-up could not tell that
--      from "the street frame has no docks near it"; grouping by frame makes
--      the coverage of each one a number on the page rather than an assumption;
--   1. every address in scope carries a level (0 is a value) and a run_at,
--      so the no-eligibility-gate rule is visible rather than asserted;
--   2. an address with NO reachable dock has level 0 and NULL shares -- never a
--      0 share, which would be a claim about a dock that is not there;
--   3. both shares lie in [0, 1];
--   4. the citywide sum of bike_starts_400m over addresses is NOT compared to
--      the system total on purpose: catchments OVERLAP, so one dock is counted
--      once per address that can reach it. The per-dock reconciliation lives in
--      the ingest's own validation query; the number here is a coverage and
--      distribution read, and anyone summing it across addresses is
--      double-counting by construction.
SELECT a.borough,
       COALESCE(a.frame, 'lot')                                  AS frame,
       count(*)                                                  AS addresses,
       count(a.bike_run_at)                                      AS measured,
       count(*) FILTER (WHERE bs.address_id IS NOT NULL)          AS with_a_dock,
       round(100.0 * count(*) FILTER (WHERE bs.address_id IS NOT NULL)
             / nullif(count(*), 0), 1)                            AS coverage_pct,
       count(*) FILTER (WHERE a.bike_starts_400m = 0)             AS zero_starts,
       count(*) FILTER (WHERE bs.address_id IS NULL
                          AND a.bike_starts_400m > 0)             AS impossible_nonzero,
       count(*) FILTER (WHERE bs.address_id IS NULL
                          AND a.bike_evening_ends_share_400m IS NOT NULL)
                                                                  AS impossible_share,
       round(median(a.bike_starts_400m), 1)                       AS p50_starts,
       round(quantile_cont(a.bike_starts_400m, 0.9), 1)           AS p90_starts,
       round(median(a.bike_ends_400m), 1)                         AS p50_ends,
       round(median(a.bike_evening_ends_share_400m), 4)           AS p50_evening_share,
       min(a.bike_evening_ends_share_400m)                        AS min_evening_share,
       max(a.bike_evening_ends_share_400m)                        AS max_evening_share,
       round(median(a.bike_casual_share_400m), 4)                 AS p50_casual_share,
       max(a.bike_casual_share_400m)                              AS max_casual_share
FROM analysis.address a
LEFT JOIN (SELECT DISTINCT address_id FROM analysis.address_bike_station) bs
       ON bs.address_id = a.address_id
GROUP BY ROLLUP(a.borough, COALESCE(a.frame, 'lot'))
ORDER BY a.borough NULLS LAST, frame NULLS LAST
"""


#: Rebuilds ONE address's four numbers from the staging panel and the persisted
#: reachable set, independently of the frames the build used, and diffs them
#: against what is stored. This is the query that says the pipeline is arithmetic
#: rather than hope: it re-derives the divisor from `days_in_cell`, re-sums the
#: dock weights, and re-forms both shares from raw counts.
#:
#: Parameters: address_id, window start, window end (three times over).
RECONCILE_SQL = """
WITH r AS (
    SELECT station_id FROM analysis.address_bike_station WHERE address_id = ?
), w AS (
    SELECT * FROM staging.citibike_station_month
    WHERE month BETWEEN ? AND ? AND station_id IN (SELECT station_id FROM r)
), d AS (
    SELECT sum(dd) AS weekday_days FROM (
        SELECT month, any_value(days_in_cell) AS dd
        FROM staging.citibike_station_month
        WHERE month BETWEEN ? AND ? AND day_type = 'weekday'
        GROUP BY 1)
)
SELECT (SELECT count(*) FROM r)                    AS docks_reachable,
       (SELECT weekday_days FROM d)                AS weekday_days,
       sum(starts) FILTER (day_type = 'weekday')
           / (SELECT weekday_days FROM d)          AS rebuilt_starts,
       sum(ends)   FILTER (day_type = 'weekday')
           / (SELECT weekday_days FROM d)          AS rebuilt_ends,
       sum(ends) FILTER (daypart = 'evening'
                      OR day_type IN ('saturday', 'sunday'))
           / nullif(sum(ends), 0)                  AS rebuilt_evening_share,
       sum(casual_starts) / nullif(sum(starts), 0) AS rebuilt_casual_share
FROM w
"""


def reconcile(con, address_id: str, first: dt.date, last: dt.date,
              rtol: float = 1e-9) -> dict:
    """Re-derive one address's four measures and RAISE if they differ.

    Cheap enough to run on every build; the point is that a future change to the
    weighting, the divisor or the share definition cannot land quietly.
    """
    r = con.execute(RECONCILE_SQL,
                    [address_id, first, last, first, last]).fetchdf()
    if r.empty:
        raise RuntimeError(f"{address_id} has no reachable dock to reconcile")
    got = con.execute(
        "SELECT bike_starts_400m, bike_ends_400m, bike_evening_ends_share_400m, "
        "bike_casual_share_400m FROM analysis.address WHERE address_id = ?",
        [address_id]).fetchone()
    pairs = list(zip(
        ("bike_starts_400m", "bike_ends_400m", "bike_evening_ends_share_400m",
         "bike_casual_share_400m"),
        got,
        (r.at[0, "rebuilt_starts"], r.at[0, "rebuilt_ends"],
         r.at[0, "rebuilt_evening_share"], r.at[0, "rebuilt_casual_share"])))
    bad = [(k, a, b) for k, a, b in pairs
           if a is None or b is None or abs(a - b) > rtol * max(abs(b), 1.0)]
    if bad:
        raise RuntimeError(
            f"the stored measures for {address_id} do not reproduce from the "
            f"panel: {bad}. Either the window moved under the columns, or the "
            f"weighting changed without the columns being rebuilt.")
    return {"address_id": address_id,
            "docks_reachable": int(r.at[0, "docks_reachable"]),
            "weekday_days": int(r.at[0, "weekday_days"]),
            **{k: float(a) for k, a, _ in pairs}}


# ---------------------------------------------------------------- the build

def build_address_bike(
    con,
    boroughs: list[str] | None,
    radius_m: float = DEFAULT_RADIUS_M,
    graph_path: pathlib.Path = GRAPH_PATH,
    window_months: int = DEFAULT_WINDOW_MONTHS,
    reachable: pd.DataFrame | None = None,
    dry_run: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(measures frame, reachable frame, report).

    `reachable` short-circuits the Dijkstra sweep: pass the frame recovered from
    `analysis.address_bike_station` and the whole rebuild is weights and SQL.
    That is the entire reason that table exists.
    """
    first, last = window_bounds(con, window_months)
    weights, wrep = station_weights(con, first, last)

    if reachable is None:
        reachable, rrep = build_reachable(con, boroughs, weights,
                                          radius_m=radius_m, graph_path=graph_path)
        rrep["source"] = "dijkstra sweep"
    else:
        known = set(weights["station_id"])
        persisted = set(reachable["station_id"])
        # A persisted dock that is NOT in the window was retired, or the window
        # rolled past it. That is ordinary attrition and it is already handled
        # correctly -- `measures` inner-joins, so the dock contributes zero,
        # which is what "it was not there" means. Reported, not raised.
        #
        # What IS raised is a wholesale divergence: if most of the persisted ids
        # are unknown, the id SPACE has changed (a re-keyed feed, or a pre-2021
        # file ingested by mistake) and the persisted distances describe docks
        # that no longer exist under these names. Silently zeroing most of the
        # network would read as a city that stopped cycling.
        unknown = sorted(persisted - known)
        if persisted and len(unknown) > MAX_RETIRED_SHARE * len(persisted):
            raise RuntimeError(
                f"{len(unknown)} of {len(persisted)} station_ids in the persisted "
                f"reachable set are not in the current window ({unknown[:3]}). "
                f"Above {MAX_RETIRED_SHARE:.0%} that is not dock attrition, it is an "
                f"ID-SPACE change -- the persisted distances describe docks that no "
                f"longer exist under these names. Re-run with --re-sweep.")
        # THE OTHER DIRECTION, which is the one that fails QUIETLY. A dock
        # installed AFTER the sweep is in the window's weights but in nobody's
        # reachable set, so every address near it silently under-counts. The
        # check above (persisted id not in the window) raises; this one cannot,
        # because a few new docks are normal and refusing the rebuild would make
        # the persisted set useless -- so it is REPORTED and `--re-sweep` fixes it.
        #
        # It keys on the dock's FIRST ACTIVE MONTH against the sweep's run_at,
        # NOT on mere absence from the reachable set. Most absent docks are in
        # Queens and the Bronx, correctly unreachable on foot from any MN+BK
        # address; flagging those would be a warning that is always on, which is
        # a warning nobody reads.
        swept_at = con.execute(
            "SELECT max(run_at) FROM analysis.address_bike_station").fetchone()[0]
        absent = known - set(reachable["station_id"])
        missed = weights[weights["station_id"].isin(absent)]
        if swept_at is not None:
            missed = missed[pd.to_datetime(missed["first_month"])
                            > pd.Timestamp(swept_at).normalize().replace(day=1)]
        unswept = sorted(missed["station_id"])
        rrep = {"boroughs": list(boroughs) if boroughs else "ALL",
                "radius_m": float(radius_m), "pairs": int(len(reachable)),
                "addresses_with_a_station": int(reachable["address_id"].nunique()),
                "station_points": int(len(weights)),
                "docks_retired_since_sweep": len(unknown),
                "docks_not_in_the_reachable_set": len(unswept),
                "share_of_weekday_starts_unswept": float(
                    missed["weekday_starts"].sum()
                    / max(weights["weekday_starts"].sum(), 1.0)),
                "source": "analysis.address_bike_station"}

    meas = measures(reachable, weights, wrep["weekday_days"])
    bounds = check_shares_in_bounds(meas)

    run_at = dt.datetime.now()
    meta = {"run_at": run_at, "radius_m": float(radius_m),
            "graph_version": rrep.get("graph_version", graph_version(graph_path)),
            "window": wrep["window"]}
    report = {**rrep, "window": wrep["window"], "panel": wrep,
              "share_bounds": bounds,
              "measured_addresses": int(len(meas)),
              "run_at": run_at.isoformat(timespec="seconds")}
    if not dry_run:
        report["_written"] = write_measures(con, reachable, meas, boroughs, meta)
    return meas, reachable, report


def load_reachable(con, boroughs: list[str] | None) -> pd.DataFrame | None:
    """The persisted reachable set for `boroughs`, or None if absent. Partial
    counts as absent: a half-populated scope would silently zero every address
    the previous run did not cover."""
    try:
        where, params = "", []
        if boroughs:
            where = f"WHERE borough IN ({', '.join('?' for _ in boroughs)})"
            params = list(boroughs)
        df = con.execute(
            f"SELECT address_id, borough, station_id, dist_m "
            f"FROM analysis.address_bike_station {where}", params).fetchdf()
    except Exception:
        return None
    return None if df.empty else df
