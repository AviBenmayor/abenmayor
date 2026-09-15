"""Do walkable BIKE flows rank real sidewalk volume? (Citi Bike phase 1)

EXTERNAL CHECK, NOT A FEATURE. Nothing here writes to the warehouse and no
score, grade or ranking reads it. A SIBLING of `validation/pedestrian_counts.py`,
not a rewrite of it: that module is imported for the DOT feed, the round parser,
the on-street point set and `spearman`, so there is exactly one definition of
"which points count" and the two commands cannot drift into comparing different
screenlines.

THE QUESTION
---------------------------------------------------------------------------
D76 measured `transit_entries_400m` against the DOT counts and got rho +0.79
overall -- but the sharper test killed it: the AM count was ranked BETTER by
`pm_peak` (+0.788) than by `am_peak` itself (+0.620), so the daypart split was
carrying no information and the measure was a station on/off flag with extra
steps. The same off-diagonal test is run here, for the same reason. If the AM
count is ranked as well by a bike dock's evening flow as by its morning flow,
then the bike measure is "is there a dock here", and the levels earn no more
than transit's card-context status.

Bike is compared BOTH WAYS in one row -- the DOT window, the subway daypart and
the bike daypart -- which is possible only because
`citibike.daypart_case_sql()` renders its CASE from `mta_ridership.DAYPARTS`, so
the three clocks are the same clock.

WHY STARTS + ENDS AND NOT EACH SEPARATELY
---------------------------------------------------------------------------
A DOT screenline counts people PASSING, in both directions, with no notion of
origin or destination. The comparable bike quantity is therefore total dock
activity -- departures plus arrivals -- not one direction. Each direction is
reported alongside so a reader can see which one carries the rank, but the
headline correlate is the sum. Adding them is not a double count: a departure
and an arrival are two different people-movements past that corner.

WHAT A HIGH RHO WOULD NOT PROVE
---------------------------------------------------------------------------
Everything `pedestrian_counts` says about the restricted range applies unchanged
-- DOT's points are traffic-engineering locations on busy commercial corridors,
so a rank correlation there is silent about how the measure orders one quiet
residential block against another, which is most of the address universe.

And one thing more, specific to this source: DOT count points and Citi Bike
docks are BOTH sited on busy commercial corridors, by two organisations
optimising for related things. A correlation between them is partly a
correlation between two siting policies. That is the reason the COVERAGE number
is reported beside the rho: the share of addresses with a dock within 400 m is
the honest statement of where this measure exists at all, and it is the number
that decides whether bike does better than transit's 65%-of-Brooklyn-reads-zero.
"""
from __future__ import annotations

import pathlib
import pickle

import numpy as np
import pandas as pd

from loci.validation.pedestrian_counts import (
    fetch_points,
    latest_round,
    on_street_counts,
    spearman,
)

#: The dock-side weights, per daypart, on WEEKDAYS only -- DOT counts weekdays.
#: `starts + ends` is the headline; the two directions ride along so a reader
#: can see which one the rank is coming from.
STATION_DAYPART_SQL = """
WITH w AS (
    SELECT * FROM staging.citibike_station_month
    WHERE month BETWEEN ? AND ? AND day_type = 'weekday'
),
d AS (SELECT sum(days) AS days FROM (
        SELECT month, any_value(days_in_cell) AS days FROM w GROUP BY 1))
SELECT w.station_id, w.daypart,
       sum(w.starts) / any_value(d.days)               AS starts_per_weekday,
       sum(w.ends)   / any_value(d.days)               AS ends_per_weekday,
       (sum(w.starts) + sum(w.ends)) / any_value(d.days) AS trips_per_weekday
FROM w CROSS JOIN d
GROUP BY 1, 2
"""


def station_daypart_weights(con, first, last) -> pd.DataFrame:
    df = con.execute(STATION_DAYPART_SQL, [first, last]).fetchdf()
    if df.empty:
        raise RuntimeError(
            f"no Citi Bike weekday cells between {first} and {last}; run "
            f"`loci citibike ingest` before validating. A zero-point correlation "
            f"is exactly the silent failure this project refuses.")
    st = con.execute(
        "SELECT station_id, lon, lat FROM staging.citibike_station "
        "WHERE lon IS NOT NULL AND lat IS NOT NULL").fetchdf()
    return df.merge(st, on="station_id", how="inner")


def measure_bike_at_points(con, points: list[dict], radius_m: float,
                           first, last, graph_path=None):
    """Bike starts/ends per average weekday within `radius_m` NETWORK metres of
    each DOT count point, per daypart, with the SAME machinery the address
    columns use.

    Recomputed at the count points rather than read off the nearest address --
    the same ruling `pedestrian_counts.measure_at_points` records: reading a
    neighbouring address's column would add that address's snap error to the
    count point's and would fail silently wherever the address build had not
    been run.
    """
    import osmnx as ox

    from loci.model.supply_ratio import catchment_sums, node_weights
    from loci.score.access import MIN_COMPONENT, _prune, _to_csr
    from loci.score.walkgraph import OUT as GRAPH_PATH
    from loci.sources.cities.nyc.mta_ridership import DAYPART_NAMES

    graph_path = GRAPH_PATH if graph_path is None else graph_path
    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)
    n_nodes = A.shape[0]

    w = station_daypart_weights(con, first, last)
    stations = (w[["station_id", "lon", "lat"]].drop_duplicates("station_id")
                 .reset_index(drop=True))
    nodes = ox.distance.nearest_nodes(
        Gp, X=stations["lon"].tolist(), Y=stations["lat"].tolist())
    s_nidx = np.array([idx[n] for n in np.atleast_1d(nodes)], dtype=np.int64)
    pos = {s: i for i, s in enumerate(stations["station_id"])}

    nodes_of, weights = {}, {}
    for kind, col in (("trips", "trips_per_weekday"),
                      ("starts", "starts_per_weekday"),
                      ("ends", "ends_per_weekday")):
        for p in DAYPART_NAMES:
            vec = np.zeros(len(stations), dtype=np.float64)
            sub = w[w["daypart"] == p]
            vec[[pos[s] for s in sub["station_id"]]] = sub[col].to_numpy(float)
            nodes_of[f"{kind}/{p}"] = s_nidx
            weights[f"{kind}/{p}"] = vec
    keys = list(weights)
    W = node_weights(idx, nodes_of, weights, n_nodes)

    df = pd.DataFrame(points)
    q = np.array([idx[n] for n in np.atleast_1d(
        ox.distance.nearest_nodes(Gp, X=df["lon"].tolist(), Y=df["lat"].tolist()))],
        dtype=np.int64)
    acc = catchment_sums(A, q, W, radius_m=float(radius_m))
    for i, k in enumerate(keys):
        df[f"bike_{k.replace('/', '_')}_400m"] = acc[:, i]
    for kind in ("trips", "starts", "ends"):
        df[f"bike_{kind}_400m"] = sum(
            df[f"bike_{kind}_{p}_400m"] for p in DAYPART_NAMES)
    rep = {"radius_m": float(radius_m), "stations": int(len(stations)),
           "window": f"{first:%Y-%m}..{last:%Y-%m}", "points": int(len(df))}
    return df, rep


COVERAGE_SQL = """
-- The share of LOT addresses with any dock within the radius, beside the same
-- share for subway entrances. This is the number that decides whether the bike
-- layer is less degenerate than transit, and it is read from the two PERSISTED
-- reachable sets rather than recomputed, so it cannot disagree with the columns.
SELECT a.borough,
       count(*)                                              AS lot_addresses,
       count(*) FILTER (WHERE bs.address_id IS NOT NULL)      AS with_a_dock,
       round(100.0 * count(*) FILTER (WHERE bs.address_id IS NOT NULL)
             / nullif(count(*), 0), 1)                        AS dock_pct,
       count(*) FILTER (WHERE ae.address_id IS NOT NULL)      AS with_an_entrance,
       round(100.0 * count(*) FILTER (WHERE ae.address_id IS NOT NULL)
             / nullif(count(*), 0), 1)                        AS entrance_pct,
       count(*) FILTER (WHERE bs.address_id IS NOT NULL
                          AND ae.address_id IS NULL)          AS dock_only
FROM analysis.address a
LEFT JOIN (SELECT DISTINCT address_id FROM analysis.address_bike_station) bs
       ON bs.address_id = a.address_id
LEFT JOIN (SELECT DISTINCT address_id FROM analysis.address_entrance) ae
       ON ae.address_id = a.address_id
WHERE COALESCE(a.frame, 'lot') = 'lot'
GROUP BY ROLLUP(a.borough)
ORDER BY a.borough NULLS LAST
"""


def run_validation(con, radius_m: float = 400.0, months: int = 3,
                   window_months: int = 12, with_transit: bool = True):
    """Fetch -> latest round -> on-street points -> bike sweep (+ the transit /
    homes sweep for comparison) -> Spearman. Writes nothing, anywhere."""
    from loci.model.address_bike import window_bounds
    from loci.sources.cities.nyc.mta_ridership import (
        DAYPART_NAMES,
        DOT_WINDOW_DAYPART,
        DOT_WINDOWS,
    )

    rows = fetch_points(con)
    year, month = latest_round(rows)
    pts, rep = on_street_counts(rows, year, month)
    first, last = window_bounds(con, window_months)
    df, brep = measure_bike_at_points(con, pts, radius_m, first, last)

    if with_transit:
        from loci.validation import pedestrian_counts as pc
        tdf, trep = pc.measure_at_points(con, pts, radius_m=radius_m, months=months)
        keep = ["loc", "transit_entries_400m", "jobs_400m", "homes_400m",
                *[f"transit_weekday_{p}_400m" for p in DAYPART_NAMES]]
        df = df.merge(tdf[keep], on="loc", how="left")
        brep["transit"] = {k: trep[k] for k in ("radius_m", "jobs_vintage")}

    bk = df["borough"].astype(str).str.strip().str.lower() == "brooklyn"

    cols = ["bike_trips_400m", "bike_starts_400m", "bike_ends_400m"]
    if with_transit:
        cols += ["transit_entries_400m", "homes_400m"]
    corr = {}
    for col in cols:
        rho, n = spearman(df["count"], df[col])
        rho_bk, n_bk = spearman(df.loc[bk, "count"], df.loc[bk, col])
        corr[col] = {"spearman_rho": rho, "n": n,
                     "spearman_rho_bk": rho_bk, "n_bk": n_bk}

    # PER-WINDOW, with the OFF-DIAGONAL. The diagonal alone cannot tell a
    # daypart-sensitive measure from a busy-place flag; if AM-count vs
    # bike_evening ranks as well as AM-count vs bike_am_peak, the split carries
    # no time-of-day information. This is the test that demoted transit in D76.
    by_window = {}
    for win, part in DOT_WINDOW_DAYPART.items():
        obs = f"dot_{win}"
        col = f"bike_trips_{part}_400m"
        rho, n = spearman(df[obs], df[col])
        rho_bk, n_bk = spearman(df.loc[bk, obs], df.loc[bk, col])
        off = {p: spearman(df[obs], df[f"bike_trips_{p}_400m"])[0]
               for p in DAYPART_NAMES}
        entry = {"dot_window_hours": list(DOT_WINDOWS[win]), "daypart": part,
                 "spearman_rho": rho, "n": n,
                 "spearman_rho_bk": rho_bk, "n_bk": n_bk, "off_diagonal": off}
        if with_transit:
            entry["transit_rho"] = spearman(
                df[obs], df[f"transit_weekday_{part}_400m"])[0]
        by_window[win] = entry

    coverage = con.execute(COVERAGE_SQL).fetchdf()
    zero = int((df["bike_trips_400m"] <= 0).sum())
    return df, {**rep, **brep, "correlations": corr, "by_window": by_window,
                "coverage": coverage,
                "points_with_zero_bike": zero,
                "points_with_zero_bike_bk": int((df.loc[bk, "bike_trips_400m"] <= 0).sum()),
                "brooklyn_points": int(bk.sum()),
                "weekend_validated": False}
