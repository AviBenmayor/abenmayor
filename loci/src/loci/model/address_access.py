"""Two PRESENT-DAY demand measures at address grain (GTM-146).

    transit_entries_400m   average weekday daily subway ENTRIES at station
                           complexes reachable within 400 m NETWORK metres
    jobs_400m              LEHD LODES8 WAC total jobs (C000) in census blocks
                           within the same 400 m

WHY THESE TWO, AND WHY BESIDE homes_400m
---------------------------------------------------------------------------
`homes_400m` (model/supply_ratio.py) is the resident half of demand and it is
the only half the screen can currently see. Two addresses with the same
`homes_400m` are the same number to every downstream consumer, and they are not
the same retail location if one of them is 80 m from a station complex putting
30,000 people on the sidewalk each weekday, or sits inside an office district
whose daytime population is ten times its residential one. These two columns
are the daytime and passer-by halves, measured on exactly the same walk graph,
at exactly the same radius, with exactly the same Dijkstra.

THE SAME ENGINE, DELIBERATELY
---------------------------------------------------------------------------
`score/access._prune` + `_to_csr` build the undirected CSR walk graph (see that
module's comment on NOT mirroring edges -- csr_matrix SUMS duplicate entries,
which doubled every distance once already), and
`model/supply_ratio.catchment_sums` does the sweep: sourced FROM the query
nodes, one bounded scipy Dijkstra per batch, weights read off in one matrix
product. Nothing here re-implements distance. No `ST_DWithin`, no straight
line: 400 m network is the project's one definition of "within reach"
(`score/access.THRESHOLDS[5]`), and a straight-line 400 m in Manhattan crosses
an avenue that takes 600 m of walking to get around.

Both measures ride ONE sweep, because the query nodes and the radius are
identical -- a second pass would cost a second 40-minute Dijkstra to compute a
column that the first pass could have produced as another weight vector.

EVERY ADDRESS GETS A VALUE (owner rule, 2026-09-13)
---------------------------------------------------------------------------
No eligibility gate, and nothing is dropped. A block of warehouses with no
station and no jobs within 400 m gets 0.0 and 0, and that zero is a REAL
observation -- "nothing within a five-minute walk" -- not a missing value. This
is the opposite convention to `supply_per_1k`, which is NULL when the
denominator is zero, and the difference is that these two are numerators.

There is also NO CENSORING to record. `analysis.address_category.censored` and
`analysis.address.lead_censored` (D75) exist because `nearest_m` is a DISTANCE
right-censored at the 2,400 m Dijkstra cap, and a censored distance is a floor
rather than a measurement. A catchment SUM inside a hard 400 m radius has no
such ceiling: every weight inside the circle is counted exactly once and every
weight outside it is excluded exactly once. Adding a `*_censored` flag here
would be inventing a state that cannot occur. What CAN occur -- an address on a
graph component too small to survive `_prune` -- cannot occur either, because
`ox.distance.nearest_nodes` snaps onto the ALREADY-pruned graph, so every
address lands on a real node of a real component.

CATEGORY-INDEPENDENT, SO analysis.address AND NOT address_category
---------------------------------------------------------------------------
The same subway entries and the same jobs are within 400 m whether you are
asking about pharmacies or bars. Putting these on `analysis.address_category`
would write fifteen identical copies of one number -- 11.5M rows to say 767k
things, the pivot-shaped duplication D61 removed. So they extend
`analysis.address`, exactly as `homes_400m`, `storefronts_400m` and
`units_permitted_400m` do, and for the same reason (owner rule, D61: inventory
before adding a table; new measures extend the existing grain).

UPDATE-ONLY, NON-FILTERING (D48/D57/D58/D62/D67/D73)
---------------------------------------------------------------------------
`write_access` issues ONLY `UPDATE analysis.address SET <ACCESS_COLUMNS>`.
Never an INSERT, never a DELETE, and `ACCESS_COLUMNS` is asserted disjoint from
the screen's own columns and from every sibling annotation before the statement
runs (`_guard`, plus tests/test_address_access.py). An address does not become
a gap because it is near a station, and does not stop being one because it is
not. These are a reading beside the screen, never a filter on it -- and in
particular they do NOT enter `gap_score`, `supply_ratio_vs_base` or any
recommendation grade.

RESET-then-UPDATE, for the reason every sibling resets: an address that leaves
scope, or a rebuilt graph, must not keep the previous run's number, and UPDATE
has no DELETE to fall back on.

RE-APPLY AFTER EVERY SCREEN RE-RUN -- THIS IS NOT OPTIONAL
---------------------------------------------------------------------------
`loci address-gaps` does `DELETE FROM analysis.address WHERE borough = ?`
followed by an INSERT, so it does not merely reset the annotation columns: it
destroys the rows they were on. Every UPDATE-only annotation in this project
comes back NULL after a screen re-run, and this one is no different. Put
`loci address-access --boroughs MN,BK` in the same re-apply sequence as
`loci pipeline` -> `loci storefronts` -> age-fit -> `loci supply-ratio`. Order
within that sequence does not matter here (nothing in this module reads another
annotation), but running it BEFORE the screen wastes the whole sweep.
`access_run_at IS NULL` is the flag that says it has not been re-applied.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. ENTRIES ARE NOT FOOTFALL, and they are the MORNING-OUTBOUND direction at a
   residential complex. The evening arrival flow -- the one that buys
   groceries on the way home -- is not published per station anywhere. See
   sources/cities/nyc/mta_ridership.py.
2. THE WINDOW IS THREE SUMMER MONTHS by default (whatever the feed's latest
   three full months are). School is out and offices are thinner in July and
   August, so a school-adjacent or CBD complex reads low relative to an annual
   mean. The window is stamped per row in `transit_entries_window` so a reader
   can see which three months produced the number, and `--months 12` buys a
   trailing year for twelve requests instead of three.
3. LODES COUNTS JOBS, NOT PEOPLE PRESENT. It is a payroll-record count at the
   WORK location: a ten-employee supermarket and a one-employee laundromat are
   not comparable units of foot traffic (CONTEXT.md 7.4), remote and hybrid
   workers are counted at an office they may not enter, and most of the
   self-employed are not counted at all.
4. LODES BLOCK CENTROIDS, NOT BUILDINGS. Every job in a block lands on one
   point. At 400 m that is a real quantisation in NYC's large waterfront and
   industrial blocks; it is unbiased on average and wrong in particular.
5. THE TWO ARE CORRELATED WITH EACH OTHER AND WITH homes_400m. Never add them,
   never treat them as three independent demand signals, and never build a
   composite from them without deciding what the weights mean.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pickle

import numpy as np
import osmnx as ox
import pandas as pd

from loci.model.conveniences import graph_version
from loci.model.supply_ratio import BATCH, catchment_sums, node_weights
from loci.score.access import MIN_COMPONENT, THRESHOLDS, _prune, _to_csr
from loci.score.walkgraph import OUT as GRAPH_PATH

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
LODES_DIR = REPO_ROOT / "data" / "raw" / "lodes"
XWALK = LODES_DIR / "ny_xwalk.csv.gz"

#: 5-minute walk, pinned to THRESHOLDS[5] exactly as model/supply_ratio.py,
#: model/storefronts.py and model/dev_pipeline.py pin it, so "within reach" is
#: ONE distance everywhere in this project.
DEFAULT_RADIUS_M = THRESHOLDS[5]        # 400.0

#: The LODES8 WAC vintage on disk (data/raw/lodes). LODES8 puts every vintage on
#: 2020 TIGER blocks, so no 2010/2020 crosswalk is needed -- but pre-2020 years
#: got onto 2020 blocks by AREA-PROPORTIONAL ALLOCATION, which is bias and not
#: noise (CONTEXT.md 7.4b). 2023 is OBSERVED on its own blocks, which is why the
#: present-day measure uses it and nothing older.
DEFAULT_JOBS_VINTAGE = 2023

#: LODES WAC total-jobs column. C000 = all jobs; the CNS01-CNS20 sector columns
#: are what analysis.hex_panel uses and are NOT what this column means.
JOBS_COLUMN = "C000"

#: Degrees of padding on the walk graph's bbox when selecting LODES blocks.
#: ny_wac is the WHOLE STATE: an Albany block left in the frame would snap to
#: whichever NYC-graph node happens to be nearest -- `nearest_nodes` has no
#: distance limit -- and dump upstate employment onto the northern edge of the
#: Bronx. 0.02 deg is ~2 km, enough to keep every block a downstate address
#: could walk to and to exclude everything it could not.
BBOX_PAD_DEG = 0.02

#: The ONLY columns write_access may name in a SET clause. Category-INDEPENDENT
#: by construction -- see the module docstring.
ACCESS_COLUMNS = [
    "transit_entries_400m",
    "jobs_400m",
    "access_radius_m",
    "transit_entries_window",
    "transit_entries_snap",
    "jobs_vintage",
    "access_run_at",
]


# ----------------------------------------------------------------- the reads

def load_job_points(con, bbox: tuple[float, float, float, float],
                    vintage: int = DEFAULT_JOBS_VINTAGE,
                    lodes_dir: pathlib.Path = LODES_DIR) -> pd.DataFrame:
    """One row per 2020 census block inside `bbox` with at least one job:
    (w_geocode, lon, lat, jobs).

    Read straight off the gzipped LODES files with DuckDB's read_csv, exactly as
    model/panel.py reads them -- a pure SELECT, no warehouse table involved. The
    join is `w_geocode = tabblk2020`, the LODES8 crosswalk's own key, and the
    point is the crosswalk's published block centroid (blklatdd/blklondd), not a
    TIGER shapefile: there is no reprojection step because both sides are
    EPSG:4326 degrees, which is what the walk graph's node coordinates are.

    `bbox` is (minlon, minlat, maxlon, maxlat) of the WALK GRAPH -- see
    BBOX_PAD_DEG on why a statewide frame is not merely wasteful but wrong.
    """
    wac = lodes_dir / f"ny_wac_S000_JT00_{vintage}.csv.gz"
    if not wac.exists():
        raise FileNotFoundError(
            f"{wac} is absent. LODES WAC {vintage} has not been downloaded; "
            f"writing jobs_400m = 0 on every address would read as 'nobody works "
            f"in New York'.")
    if not XWALK.exists():
        raise FileNotFoundError(f"{XWALK} is absent (the LODES8 block crosswalk).")
    minlon, minlat, maxlon, maxlat = bbox
    df = con.execute(f"""
        SELECT w.w_geocode                       AS w_geocode,
               TRY_CAST(x.blklondd AS DOUBLE)    AS lon,
               TRY_CAST(x.blklatdd AS DOUBLE)    AS lat,
               TRY_CAST(w.{JOBS_COLUMN} AS DOUBLE) AS jobs
        FROM read_csv('{wac}', ALL_VARCHAR=TRUE) w
        JOIN read_csv('{XWALK}', ALL_VARCHAR=TRUE) x ON w.w_geocode = x.tabblk2020
        WHERE TRY_CAST(x.blklondd AS DOUBLE) BETWEEN {minlon} AND {maxlon}
          AND TRY_CAST(x.blklatdd AS DOUBLE) BETWEEN {minlat} AND {maxlat}
          AND TRY_CAST(w.{JOBS_COLUMN} AS DOUBLE) > 0
    """).fetchdf()
    if df.empty:
        raise RuntimeError(
            f"LODES WAC {vintage}: no blocks with jobs inside the walk-graph bbox "
            f"{bbox}. That is a broken join or a wrong bbox, never a real city; "
            f"refusing to write zeros.")
    return df


def load_address_points(con, boroughs: list[str] | None = None) -> pd.DataFrame:
    """Addresses to SCORE. `boroughs=None` means every borough in the warehouse.

    Unlike the WEIGHTS (which are citywide by construction -- the subway and the
    job blocks do not stop at a borough line), the query set is scoped, because
    the sweep costs one Dijkstra per batch of query nodes and the caller may
    only want MN+BK.
    """
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        sql = (f"SELECT address_id, borough, lon, lat FROM analysis.address "
               f"WHERE borough IN ({holes}) AND lon IS NOT NULL AND lat IS NOT NULL")
        return con.execute(sql, list(boroughs)).fetchdf()
    return con.execute(
        "SELECT address_id, borough, lon, lat FROM analysis.address "
        "WHERE lon IS NOT NULL AND lat IS NOT NULL").fetchdf()


def graph_bbox(G, pad: float = BBOX_PAD_DEG) -> tuple[float, float, float, float]:
    """(minlon, minlat, maxlon, maxlat) of the graph's nodes, padded."""
    xs = np.fromiter((d["x"] for _, d in G.nodes(data=True)), dtype=float)
    ys = np.fromiter((d["y"] for _, d in G.nodes(data=True)), dtype=float)
    return (float(xs.min()) - pad, float(ys.min()) - pad,
            float(xs.max()) + pad, float(ys.max()) + pad)


# ---------------------------------------------------------------- the build

def compute_access(
    con,
    boroughs: list[str] | None,
    radius_m: float = DEFAULT_RADIUS_M,
    graph_path: pathlib.Path = GRAPH_PATH,
    months: int = 3,
    use_entrances: bool = True,
    jobs_vintage: int = DEFAULT_JOBS_VINTAGE,
    refresh: bool = False,
    batch: int = BATCH,
) -> tuple[pd.DataFrame, dict]:
    """(frame of address_id/borough + ACCESS_COLUMNS, report). READ-ONLY on the
    warehouse -- it SELECTs analysis.address and writes nothing."""
    from loci.sources.cities.nyc import mta_ridership as mr

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)
    n_nodes = A.shape[0]
    bbox = graph_bbox(Gp)

    # --- the weights ------------------------------------------------------
    transit_pts, transit_rep = mr.build_entry_points(
        months=months, use_entrances=use_entrances, refresh=refresh)
    jobs = load_job_points(con, bbox, vintage=jobs_vintage)

    t_lon = [p[1] for p in transit_pts]
    t_lat = [p[2] for p in transit_pts]
    t_w = np.array([p[3] for p in transit_pts], dtype=np.float64)
    t_nodes = ox.distance.nearest_nodes(Gp, X=t_lon, Y=t_lat)
    t_nidx = np.array([idx[n] for n in np.atleast_1d(t_nodes)], dtype=np.int64)

    j_nodes = ox.distance.nearest_nodes(
        Gp, X=jobs["lon"].tolist(), Y=jobs["lat"].tolist())
    j_nidx = np.array([idx[n] for n in np.atleast_1d(j_nodes)], dtype=np.int64)
    j_w = jobs["jobs"].to_numpy(dtype=np.float64)

    # Points are ACCUMULATED, never deduplicated: two entrances of two different
    # complexes on one corner are two entrances, and two job blocks snapped to
    # one node are two blocks' worth of jobs. (node_weights uses np.add.at.)
    keys = ["transit", "jobs"]
    W = node_weights(idx, {"transit": t_nidx, "jobs": j_nidx},
                     {"transit": t_w, "jobs": j_w}, n_nodes)

    # --- the sweep --------------------------------------------------------
    addr = load_address_points(con, boroughs)
    if addr.empty:
        raise RuntimeError(
            f"no addresses in analysis.address for boroughs={boroughs}. Run "
            f"`loci address-gaps` first; an empty frame would RESET every column "
            f"to NULL and write nothing back.")
    a_nodes = ox.distance.nearest_nodes(
        Gp, X=addr["lon"].tolist(), Y=addr["lat"].tolist())
    a_nidx = np.array([idx[n] for n in np.atleast_1d(a_nodes)], dtype=np.int64)
    # Addresses collapse onto far fewer graph nodes -- a 400 m catchment cannot
    # tell two doorways on one block apart -- so the sweep runs once per NODE.
    uniq, inv = np.unique(a_nidx, return_inverse=True)
    acc = catchment_sums(A, uniq, W, radius_m=radius_m, batch=batch)[inv]

    run_at = dt.datetime.now()
    window = f"{transit_rep['window_start']}..{transit_rep['window_end']} weekdays"
    out = pd.DataFrame({
        "address_id": addr["address_id"],
        "borough": addr["borough"],
        "transit_entries_400m": acc[:, keys.index("transit")],
        "jobs_400m": np.rint(acc[:, keys.index("jobs")]).astype("int64"),
        "access_radius_m": float(radius_m),
        "transit_entries_window": window,
        "transit_entries_snap": transit_rep["snap"],
        "jobs_vintage": int(jobs_vintage),
        "access_run_at": run_at,
    })

    report = {
        "boroughs": list(boroughs) if boroughs else "ALL",
        "radius_m": float(radius_m),
        "graph_version": graph_version(graph_path),
        "graph_bbox": bbox,
        "addresses": len(out),
        "query_nodes": int(uniq.size),
        "transit": transit_rep,
        "transit_window": window,
        "job_blocks": len(jobs),
        "job_total_in_bbox": float(jobs["jobs"].sum()),
        "jobs_vintage": int(jobs_vintage),
        "jobs_column": JOBS_COLUMN,
        "run_at": run_at.isoformat(timespec="seconds"),
        # Coverage, stated rather than assumed. A zero here is a real
        # observation ("nothing within 400 m"), never a missing value.
        "addresses_with_transit": int((out["transit_entries_400m"] > 0).sum()),
        "addresses_with_jobs": int((out["jobs_400m"] > 0).sum()),
        "addresses_censored": 0,
    }
    return out, report


# --------------------------------------------------------------- the write

def _guard(cols: list[str]) -> None:
    """Refuse to write if the SET list touches a column another module owns.
    Belt and braces; tests/test_address_access.py is the real guard."""
    forbidden: set[str] = set()
    try:
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
    except ImportError:                                     # pragma: no cover
        pass
    overlap = sorted(set(cols) & forbidden)
    if overlap:
        raise RuntimeError(f"address-access would clobber analysis.address columns: {overlap}")


def write_access(con, df: pd.DataFrame, boroughs: list[str] | None) -> int:
    """UPDATE-only on analysis.address. RESET then UPDATE, in scope."""
    _guard(ACCESS_COLUMNS)
    absent = [c for c in ACCESS_COLUMNS if c not in df.columns]
    if absent:
        raise RuntimeError(
            f"frame is missing {absent}; every column in ACCESS_COLUMNS is reset "
            f"to NULL below, so a partial frame would blank them permanently.")
    reset = ", ".join(f"{c} = NULL" for c in ACCESS_COLUMNS)
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        con.execute(f"UPDATE analysis.address SET {reset} WHERE borough IN ({holes})",
                    list(boroughs))
    else:
        con.execute(f"UPDATE analysis.address SET {reset}")
    if df.empty:
        return 0
    con.register("_acc", df[["address_id", "borough", *ACCESS_COLUMNS]])
    try:
        sets = ", ".join(f"{c} = _acc.{c}" for c in ACCESS_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address AS a SET {sets}
            FROM _acc
            WHERE a.address_id = _acc.address_id AND a.borough = _acc.borough
        """)
    finally:
        con.unregister("_acc")
    return len(df)


def build_access(
    con,
    boroughs: list[str] | None,
    radius_m: float = DEFAULT_RADIUS_M,
    graph_path: pathlib.Path = GRAPH_PATH,
    months: int = 3,
    use_entrances: bool = True,
    jobs_vintage: int = DEFAULT_JOBS_VINTAGE,
    refresh: bool = False,
    dry_run: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """compute + write."""
    df, report = compute_access(
        con, boroughs, radius_m=radius_m, graph_path=graph_path, months=months,
        use_entrances=use_entrances, jobs_vintage=jobs_vintage, refresh=refresh)
    if not dry_run:
        report["_written"] = write_access(con, df, boroughs)
    return df, report


# ------------------------------------------------------------- the read-back

VALIDATION_SQL = """
-- Proves, on the warehouse and not on the frame: row counts, the no-missing
-- rule (every in-scope address has BOTH values), and that the total jobs
-- credited is a plausible multiple of the city's job count rather than a
-- double-count. A block within 400 m of N addresses is counted N times BY
-- DESIGN -- these are per-address catchments, not a partition -- so the right
-- check is not "does the sum match LODES", it is "is the MAX per address below
-- the citywide total", which a double-counting bug inside one catchment would
-- break.
SELECT borough,
       count(*)                                      AS addresses,
       count(transit_entries_400m)                   AS have_transit,
       count(jobs_400m)                              AS have_jobs,
       sum(CASE WHEN transit_entries_400m > 0 THEN 1 ELSE 0 END) AS transit_nonzero,
       sum(CASE WHEN jobs_400m > 0 THEN 1 ELSE 0 END)            AS jobs_nonzero,
       round(median(transit_entries_400m))           AS med_transit,
       round(max(transit_entries_400m))              AS max_transit,
       median(jobs_400m)                             AS med_jobs,
       max(jobs_400m)                                AS max_jobs,
       count(DISTINCT transit_entries_window)        AS n_windows,
       count(DISTINCT jobs_vintage)                  AS n_vintages
FROM analysis.address
WHERE access_run_at IS NOT NULL
GROUP BY ROLLUP(borough)
ORDER BY borough NULLS LAST
"""
