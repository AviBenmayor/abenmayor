"""Do the walkable-demand measures rank real sidewalk volume? (GTM-146)

EXTERNAL CHECK, NOT A FEATURE. Nothing here writes to the warehouse and no
score, grade or ranking reads it. It exists to answer one question about
`transit_entries_400m`, `jobs_400m` and `homes_400m`: at places where somebody
physically counted pedestrians, do the three measures put the busy places
above the quiet ones?

THE YARDSTICK
---------------------------------------------------------------------------
NYC DOT Bi-Annual Pedestrian Counts (`cqsj-cfgu`; the catalogue also publishes
a map view `2de2-6x2h` that returns an empty object for every row -- use the
tabular id). 114 screenline locations, counted by hand in three two-hour
windows (AM 07:00-09:00, MD 12:00-14:00, PM 16:00-19:00) twice a year since
2007.

`loc` 101-114 are BRIDGE MIDPOINTS (five East River, nine Harlem River) and are
excluded: a point in the middle of the Williamsburg Bridge has no 400 m
residential catchment in any meaningful sense, and including them would put
fourteen structural outliers into a correlation of one hundred points. The
usable set is the 100 ON-STREET points, which is what the brief asked for.

WHY SPEARMAN AND NOT PEARSON
---------------------------------------------------------------------------
Both sides are heavy-tailed counts (Times Square is not 3x Bay Ridge, it is
40x), the relationship has no reason to be linear, and the question is
"does it RANK", not "is it proportional". Spearman answers the question asked.

WHAT A HIGH CORRELATION WOULD AND WOULD NOT PROVE
---------------------------------------------------------------------------
It would NOT validate the measures as a pedestrian model. DOT's 114 points are
not a sample of New York: they are traffic-engineering locations on busy
commercial corridors, so the bottom of the volume range is barely represented
and the correlation is measured on a RESTRICTED RANGE -- it says how the
measures order busy places against each other, and is silent about how they
order a quiet residential block against a slightly less quiet one, which is
most of the address universe. Each count is also one day, two hours, three
times, twice a year: weather and a single unusual day are not averaged out.

It would also not separate the three measures from each other. They overlap
heavily by construction -- a station complex sits where the jobs and the homes
are -- so three similar correlations are the expected result and are not three
pieces of evidence.

COLUMN NAMES ARE PER-ROUND AND INCONSISTENT, SO THEY ARE PARSED, NOT TYPED
---------------------------------------------------------------------------
Observed on the live feed: `may_07_am`, `sept_07_pm`, `oct_20_am`,
`may_22_p_m` (sic), `oct24_am`, `may25_pm`, `june_24_am`, `may26_md`. Both the
separator and the PM spelling move between rounds. `parse_round` resolves them
from the feed's own field names and `latest_round` picks the most recent, so a
new round needs no edit here; a hard-coded 'may26_pm' would have silently
become stale (and 'may_22_pm' never existed at all).

THE FEED IS NO LONGER PULLED HERE -- IT IS READ FROM THE WAREHOUSE
---------------------------------------------------------------------------
This file used to fetch cqsj-cfgu live on every run and keep only the latest
round, throwing nineteen years of counts away each time. The source is now
INGESTED (`staging.dot_pedestrian_count`, sources/cities/nyc/dot_pedestrian.py,
`loci dot-counts ingest`) and this harness reads that table instead.

Nothing else changed. `wide_rows_from_db` hands back the feed's own WIDE shape,
DOT's original column spellings included (they are stored per cell as
`source_field`), so `on_street_counts` below cannot tell the difference and
this command's output is identical to what it printed when it pulled. The
parser itself now has ONE definition, in the source module, and is re-exported
here so existing importers keep working.

An un-ingested database RAISES rather than correlating zero points.
"""
from __future__ import annotations

# The parser and the vocabulary live with the SOURCE now (one definition, not
# two) and are re-exported so `from loci.validation.pedestrian_counts import
# parse_round` keeps working.
from loci.sources.cities.nyc.dot_pedestrian import (  # noqa: F401
    DATASET_ID,
    ENDPOINT,
    MAX_ON_STREET_LOC,
    PERIODS,
    latest_round,
    parse_round,
    wide_rows_from_db,
)

TIMEOUT = 120


def fetch_points(con, limit: int | None = None) -> list[dict]:
    """Every count point, in the feed's WIDE shape, FROM THE WAREHOUSE.

    RAISES if `staging.dot_pedestrian_count` is empty -- that is an
    un-ingested database, not a city nobody counted, and a zero-point
    correlation is exactly the silent failure this project refuses.
    """
    return wide_rows_from_db(con, limit=limit)


def _field_for(rows: list[dict], year: int, month: int, period: str) -> str | None:
    for r in rows:
        for f in r:
            if parse_round(f) == (year, month, period):
                return f
    return None


def on_street_counts(rows: list[dict], year: int, month: int
                     ) -> tuple[list[dict], dict]:
    """[{loc, lon, lat, borough, street, count}] for the on-street points that
    carry all three periods of the (year, month) round, plus a report.

    `count` = AM + MD + PM, i.e. the total people observed across the round's
    seven counted hours at that screenline. Not scaled to a day: no public
    expansion factor exists, and a rank correlation does not need one.
    """
    fields = {p: _field_for(rows, year, month, p) for p in PERIODS}
    missing_field = [p for p, f in fields.items() if f is None]
    if missing_field:
        raise RuntimeError(f"round {year}-{month:02d} has no field for {missing_field}")

    out, dropped_bridge, dropped_incomplete, dropped_geom = [], 0, 0, 0
    for r in rows:
        try:
            loc = int(r.get("loc"))
        except (TypeError, ValueError):
            continue
        if loc > MAX_ON_STREET_LOC:
            dropped_bridge += 1
            continue
        geom = r.get("the_geom") or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if not coords or len(coords) != 2:
            dropped_geom += 1
            continue
        vals = []
        for p in PERIODS:
            v = r.get(fields[p])
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                vals = None
                break
        if vals is None:
            dropped_incomplete += 1
            continue
        # The three windows are kept SEPARATELY as well as summed. `count` is
        # the incumbent whole-round total; dot_am / dot_md / dot_pm are what
        # the per-daypart validation needs, and summing them away was the only
        # thing stopping this file from answering "does the AM measure rank the
        # AM count" rather than only "does the day rank the day".
        out.append({
            "loc": loc,
            "lon": float(coords[0]),
            "lat": float(coords[1]),
            "borough": r.get("borough"),
            "street": r.get("street_nam"),
            "from_street": r.get("from_stree"),
            "dot_am": vals[0],
            "dot_md": vals[1],
            "dot_pm": vals[2],
            "count": sum(vals),
        })
    report = {
        "dataset_id": DATASET_ID,
        "round": f"{year}-{month:02d}",
        "fields": fields,
        "rows_in_feed": len(rows),
        "on_street_points": len(out),
        "dropped_bridge_points": dropped_bridge,
        "dropped_missing_count": dropped_incomplete,
        "dropped_missing_geometry": dropped_geom,
    }
    return out, report


def spearman(x, y) -> tuple[float, int]:
    """(rho, n) over the pairs where both sides are finite. Ties get average
    ranks (scipy's default), which matters here: several DOT points share a
    count value and several addresses share a catchment of exactly zero."""
    import numpy as np
    from scipy import stats

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return float("nan"), int(m.sum())
    rho = stats.spearmanr(x[m], y[m]).statistic
    return float(rho), int(m.sum())


# ---------------------------------------------------------------- the sweep

def measure_at_points(con, points: list[dict], radius_m: float | None = None,
                      graph_path=None, months: int | None = None,
                      use_entrances: bool = True,
                      jobs_vintage: int | None = None, refresh: bool = False):
    """Compute transit_entries / jobs / homes within `radius_m` NETWORK metres
    of each DOT count point, with the SAME machinery the address columns use.

    Recomputed at the DOT points rather than read off the nearest address,
    deliberately: reading the nearest address's column would add that address's
    own snap error to the count point's, and would silently fail wherever
    `loci address-access` had not been run. `homes` is the plain PLUTO unit sum
    from analysis.address -- the same weight model/supply_ratio.py uses for
    `homes_400m`, without the laundry haircut, which is category-specific and
    has nothing to do with sidewalks.

    Returns (DataFrame with transit/jobs/homes columns appended, report).
    """
    import pathlib
    import pickle

    import numpy as np
    import osmnx as ox
    import pandas as pd

    from loci.model.address_access import (
        DEFAULT_JOBS_VINTAGE,
        DEFAULT_RADIUS_M,
        graph_bbox,
        load_job_points,
    )
    from loci.model.supply_ratio import catchment_sums, node_weights
    from loci.score.access import MIN_COMPONENT, _prune, _to_csr
    from loci.score.walkgraph import OUT as GRAPH_PATH
    from loci.sources.cities.nyc import mta_ridership as mr

    radius_m = DEFAULT_RADIUS_M if radius_m is None else radius_m
    jobs_vintage = DEFAULT_JOBS_VINTAGE if jobs_vintage is None else jobs_vintage
    graph_path = GRAPH_PATH if graph_path is None else graph_path

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)
    n_nodes = A.shape[0]

    # build_profile, not build_entry_points: it returns the (complex x day_type
    # x daypart) grid AND asserts that the five weekday dayparts re-sum to the
    # incumbent average-weekday total, so `transit_entries_400m` below is the
    # same number the old code path produced, by construction rather than by
    # hope. The even split across entry-allowed entrances is applied here,
    # exactly as `entry_points` applies it.
    profile, entrances, transit_rep = mr.build_profile(
        months=months, use_entrances=use_entrances, refresh=refresh)
    transit_pts = [(e["complex_id"], e["lon"], e["lat"], e["n_doors"])
                   for e in entrances]
    jobs = load_job_points(con, graph_bbox(Gp), vintage=jobs_vintage)
    homes = con.execute(
        "SELECT lon, lat, COALESCE(units, 0) AS units FROM analysis.address "
        "WHERE lon IS NOT NULL AND lat IS NOT NULL").fetchdf()

    def _nidx(lons, lats):
        nodes = ox.distance.nearest_nodes(Gp, X=list(lons), Y=list(lats))
        return np.array([idx[n] for n in np.atleast_1d(nodes)], dtype=np.int64)

    # One weight column per (day_type, daypart) cell, each carrying that
    # complex's entries for that cell divided evenly over its entry-allowed
    # doors -- the SAME arithmetic model/address_transit_profile.py applies,
    # so a DOT point and an address 10 m away get the same number.
    e_nidx = _nidx([p[1] for p in transit_pts], [p[2] for p in transit_pts])
    cells = [(d, p) for d in mr.DAY_TYPES for p in mr.DAYPART_NAMES]
    nodes_of = {f"{d}/{p}": e_nidx for d, p in cells}
    weights = {f"{d}/{p}": np.array([profile[c][(d, p)] / n
                                     for c, _, _, n in transit_pts], dtype=np.float64)
               for d, p in cells}
    nodes_of["jobs"] = _nidx(jobs["lon"], jobs["lat"])
    weights["jobs"] = jobs["jobs"].to_numpy(dtype=np.float64)
    nodes_of["homes"] = _nidx(homes["lon"], homes["lat"])
    weights["homes"] = homes["units"].to_numpy(dtype=np.float64)
    keys = list(weights)
    W = node_weights(idx, nodes_of, weights, n_nodes)

    df = pd.DataFrame(points)
    q = _nidx(df["lon"], df["lat"])
    acc = catchment_sums(A, q, W, radius_m=float(radius_m))
    for i, k in enumerate(keys):
        if k in ("jobs", "homes"):
            continue
        df[f"transit_{k.replace('/', '_')}_400m"] = acc[:, i]
    # The incumbent column, DERIVED rather than separately computed: the five
    # weekday dayparts partition the day, so their sum is the average-weekday
    # total the old code path returned.
    df["transit_entries_400m"] = sum(
        df[f"transit_weekday_{p}_400m"] for p in mr.DAYPART_NAMES)
    df["jobs_400m"] = np.rint(acc[:, keys.index("jobs")]).astype("int64")
    df["homes_400m"] = np.rint(acc[:, keys.index("homes")]).astype("int64")
    return df, {"radius_m": float(radius_m), "transit": transit_rep,
                "job_blocks": len(jobs), "jobs_vintage": int(jobs_vintage),
                "home_rows": len(homes), "points": len(df),
                "daypart_bounds": {n: [a, b] for n, a, b in mr.DAYPARTS},
                "dot_windows": dict(mr.DOT_WINDOWS),
                "dot_window_daypart": dict(mr.DOT_WINDOW_DAYPART)}


def run_validation(con, radius_m: float | None = None, months: int | None = None,
                   use_entrances: bool = True, refresh: bool = False):
    """Fetch -> latest round -> on-street points -> sweep -> Spearman.
    Returns (DataFrame, report). Writes nothing, anywhere."""
    from loci.sources.cities.nyc import mta_ridership as mr

    rows = fetch_points(con)
    year, month = latest_round(rows)
    pts, rep = on_street_counts(rows, year, month)
    df, srep = measure_at_points(con, pts, radius_m=radius_m, months=months,
                                 use_entrances=use_entrances, refresh=refresh)
    bk = df["borough"].astype(str).str.strip().str.lower() == "brooklyn"
    corr = {}
    for col in ("transit_entries_400m", "jobs_400m", "homes_400m"):
        rho, n = spearman(df["count"], df[col])
        rho_bk, n_bk = spearman(df.loc[bk, "count"], df.loc[bk, col])
        corr[col] = {"spearman_rho": rho, "n": n,
                     "spearman_rho_bk": rho_bk, "n_bk": n_bk}

    # PER-WINDOW: each DOT count window against the daypart that CONTAINS it.
    # This is the comparison the whole-day rho could not make. It is also the
    # sharper test: a measure that is really just "is there a subway here" has
    # no reason to rank the AM count better with the AM measure than with the
    # PM one, so the OFF-DIAGONAL is reported too -- if AM-count vs pm_peak is
    # as strong as AM-count vs am_peak, the daypart split is carrying no
    # information and the number is a station on/off flag with extra steps.
    by_window = {}
    for win, part in mr.DOT_WINDOW_DAYPART.items():
        col = f"transit_weekday_{part}_400m"
        obs = f"dot_{win}"
        rho, n = spearman(df[obs], df[col])
        rho_bk, n_bk = spearman(df.loc[bk, obs], df.loc[bk, col])
        off = {p: spearman(df[obs], df[f"transit_weekday_{p}_400m"])[0]
               for p in mr.DAYPART_NAMES}
        by_window[win] = {
            "dot_window_hours": list(mr.DOT_WINDOWS[win]),
            "daypart": part,
            "daypart_hours": next([a, b] for n, a, b in mr.DAYPARTS if n == part),
            "spearman_rho": rho, "n": n,
            "spearman_rho_bk": rho_bk, "n_bk": n_bk,
            "off_diagonal": off,
        }

    # Saturday midday, reported with NO DOT counterpart on purpose: DOT counts
    # weekdays, so there is nothing to validate it against. It is here so a
    # reader can see the weekend measure exists and is UNVALIDATED, rather than
    # discovering that later.
    zero = int((df["transit_entries_400m"] <= 0).sum())
    return df, {**rep, **srep,
                "correlations": corr,
                "by_window": by_window,
                "points_with_zero_transit": zero,
                "points_with_zero_transit_bk": int((df.loc[bk, "transit_entries_400m"] <= 0).sum()),
                "brooklyn_points": int(bk.sum()),
                "saturday_midday_validated": False}
