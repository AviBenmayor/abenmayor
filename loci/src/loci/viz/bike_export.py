"""`webmap/data/bike.json` -- Citi Bike docks as a standalone map layer.

A STANDALONE FILE ON PURPOSE, exactly as `viz/dot_export.py` is: another thread
owns `viz/webmap_export.py`, `webmap/index.html` and `webmap/server.js`, so this
writes its OWN file with its own command (`loci citibike export`) and touches
none of them. Wiring the layer in later is a fetch of `data/bike.json` plus a
toggle; until that happens the file is inert.

THE SHAPE
---------------------------------------------------------------------------
Column-oriented (`cols` + `rows`), the packing the other overlays already use,
so ~2,300 docks with a fifteen-cell shape each stay in the low hundreds of KB
rather than a megabyte of repeated JSON keys. Coordinates are rounded to 5
decimal places (~1.1 m, finer than a dock's published position is meaningful).

`shape` is the dock's WEEKDAY daypart profile as five integers -- the popup's
sparkline -- plus the saturday and sunday all-day totals, so a reader can see a
weekend-destination dock without loading the whole panel. It is trips per
average day of that type, so the five weekday numbers sum to the dock's weekday
daily total by construction and the sizing field is not a sixth, independent
number that can drift from them.

WHAT THE LAYER MUST SAY ON ITS FACE
---------------------------------------------------------------------------
A map of 2,300 dots sized by volume is exactly where "no dot" gets read as "no
activity". It is not: a dock is where the operator put one. `caveats` rides in
the payload and is meant to be rendered UNTRUNCATED wherever this layer is
switched on, the same contract `densityCaveat` has in meta.json.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: Mirrors webmap_export's output directory WITHOUT importing it -- that module
#: is owned by another thread and importing it would couple this command's
#: success to the state of a file it does not own.
WEBMAP_DATA = REPO_ROOT / "webmap" / "data"
OUT_NAME = "bike.json"

#: Read POSITIONALLY by the webmap, so a new column is only safe APPENDED.
#: `wdStarts`/`wdEnds` are per average weekday; `evShare` and `casShare` are
#: shares in [0, 1] at 3 dp; `shape` is the five weekday dayparts.
STATION_COLS = ["id", "lon", "lat", "name", "wdStarts", "wdEnds", "satTrips",
                "sunTrips", "evShare", "casShare", "first", "last", "months"]
SHAPE_DAYPARTS = ["early", "am_peak", "midday", "pm_peak", "evening"]

CAVEATS = {
    "whatItIs": (
        "Citi Bike trips at a DOCK, from the operator's published trip files. "
        "A 'start' is a bike taken out and an 'end' a bike returned; both are "
        "per AVERAGE WEEKDAY over the window, with federal holidays excluded. "
        "Ends are dated by the ARRIVAL time, so a 00:40 return is an 'early' "
        "fact, not an evening one."),
    "notFootfall": (
        "NOT a pedestrian count. It counts people who chose a bike, held a "
        "membership or a card, and found a free dock. DOCK PLACEMENT is the "
        "dominant term in any comparison between neighbourhoods -- an area "
        "with no dots reads zero because the operator has not built there, not "
        "because nobody walks there -- and placement is correlated with income. "
        "Read it as relative busyness where there are docks."),
    "capacity": (
        "Dock capacity CENSORS the count at exactly the busiest station-hours: "
        "a full dock turns an arrival into an arrival somewhere else, an empty "
        "one turns a departure into no trip. Rebalancing trucks move bikes and "
        "are not trips, so the morning starts/ends asymmetry at a commuter dock "
        "is partly an operational artefact."),
    "membership": (
        "'casual' is anyone on a single ride or a day pass and 'member' anyone "
        "with a subscription -- NOT visitor versus resident. A high casual "
        "share reads as tourist or weekend-destination geography, mixed."),
    "fleet": (
        "The fleet changed mid-panel (72% of April 2026 trips were electric), "
        "which lengthened trips and pushed the network outward. A 2023-vs-2026 "
        "comparison at one dock mixes a demand change with a fleet change."),
}

STATION_SQL = """
WITH w AS (
    SELECT * FROM staging.citibike_station_month WHERE month BETWEEN ? AND ?
),
days AS (
    SELECT day_type, sum(days) AS days FROM (
        SELECT day_type, month, any_value(days_in_cell) AS days
        FROM w GROUP BY 1, 2) GROUP BY 1
),
agg AS (
    SELECT station_id,
           sum(w.starts) FILTER (day_type = 'weekday')
             / (SELECT days FROM days WHERE day_type = 'weekday')   AS wd_starts,
           sum(w.ends)   FILTER (day_type = 'weekday')
             / (SELECT days FROM days WHERE day_type = 'weekday')   AS wd_ends,
           -- FILTER binds to ONE aggregate, so the sum must be inside it:
           -- `(sum(a) + sum(b)) FILTER (...)` is a parser error, and the
           -- version that parses would filter only the second term.
           sum(w.starts + w.ends) FILTER (day_type = 'saturday')
             / (SELECT days FROM days WHERE day_type = 'saturday')  AS sat_trips,
           sum(w.starts + w.ends) FILTER (day_type = 'sunday')
             / (SELECT days FROM days WHERE day_type = 'sunday')    AS sun_trips,
           sum(w.ends)                                              AS all_ends,
           sum(w.ends) FILTER (daypart = 'evening'
                            OR day_type IN ('saturday', 'sunday'))  AS ev_ends,
           sum(w.starts)                                            AS all_starts,
           sum(w.casual_starts)                                     AS casual_starts
    FROM w GROUP BY 1
),
shape AS (
    SELECT station_id, daypart,
           sum(starts + ends)
             / (SELECT days FROM days WHERE day_type = 'weekday')   AS trips
    FROM w WHERE day_type = 'weekday' GROUP BY 1, 2
)
SELECT st.station_id, st.name, st.lon, st.lat,
       st.first_month, st.last_month, st.months_active,
       agg.wd_starts, agg.wd_ends, agg.sat_trips, agg.sun_trips,
       CASE WHEN agg.all_ends   > 0 THEN agg.ev_ends / agg.all_ends END      AS ev_share,
       CASE WHEN agg.all_starts > 0 THEN agg.casual_starts / agg.all_starts END AS cas_share,
       {shape_cols}
FROM staging.citibike_station st
JOIN agg USING (station_id)
LEFT JOIN shape sh USING (station_id)
WHERE st.lon IS NOT NULL AND st.lat IS NOT NULL
GROUP BY ALL
ORDER BY agg.wd_starts DESC NULLS LAST
"""


def _shape_cols() -> str:
    return ", ".join(
        f"COALESCE(max(sh.trips) FILTER (sh.daypart = '{p}'), 0) AS shape_{p}"
        for p in SHAPE_DAYPARTS)


def _r(v, dp: int = 1):
    """Round, and turn NaN/None into JSON null rather than a bare `NaN`.

    `allow_nan=False` at dump time is the backstop; this is the fix. D85 records
    a bare-`NaN`-in-JSON export bug that Python read back happily and
    `JSON.parse` refused -- a file that looks fine from a test and is unloadable
    by the map.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):                          # pragma: no cover
        return None
    return None if f != f else round(f, dp)


def build(con, window_months: int = 12) -> dict:
    from loci.model.address_bike import window_bounds

    first, last = window_bounds(con, window_months)
    sql = STATION_SQL.replace("{shape_cols}", _shape_cols())
    df = con.execute(sql, [first, last]).fetchdf()
    if df.empty:
        raise RuntimeError(
            "no Citi Bike stations in the window: run `loci citibike ingest` "
            "first. An empty map layer is indistinguishable from a city with no "
            "bike share.")
    rows, shapes = [], []
    for r in df.to_dict("records"):
        rows.append([
            r["station_id"], _r(r["lon"], 5), _r(r["lat"], 5), r["name"],
            _r(r["wd_starts"], 1), _r(r["wd_ends"], 1),
            _r(r["sat_trips"], 1), _r(r["sun_trips"], 1),
            _r(r["ev_share"], 3), _r(r["cas_share"], 3),
            str(r["first_month"])[:7], str(r["last_month"])[:7],
            int(r["months_active"] or 0),
        ])
        shapes.append([_r(r[f"shape_{p}"], 1) for p in SHAPE_DAYPARTS])
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "window": f"{first:%Y-%m}..{last:%Y-%m}",
        "stations": {"n": len(rows), "cols": STATION_COLS, "rows": rows,
                     "shapeDayparts": SHAPE_DAYPARTS, "shape": shapes},
        "source": {"name": "Citi Bike System Data (NYCBS)",
                   "url": "https://s3.amazonaws.com/tripdata/",
                   "license": "NYCBS Data Use Policy — analysis and derived "
                              "measures permitted; the raw dataset is not "
                              "redistributed. Attribution required."},
        "caveats": CAVEATS,
    }


def export(con, out_dir: pathlib.Path | str | None = None,
           window_months: int = 12) -> dict:
    """Write `<out_dir>/bike.json`. Returns {path, bytes, stations, window}."""
    out = pathlib.Path(out_dir) if out_dir else WEBMAP_DATA
    out.mkdir(parents=True, exist_ok=True)
    bundle = build(con, window_months=window_months)
    # allow_nan=False IS THE POINT -- see `_r`.
    text = json.dumps(bundle, separators=(",", ":"), allow_nan=False)
    path = out / OUT_NAME
    path.write_text(text)
    return {"path": str(path), "bytes": len(text.encode()),
            "stations": bundle["stations"]["n"], "window": bundle["window"]}
