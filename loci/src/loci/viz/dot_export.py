"""`webmap/data/dot.json` -- the DOT count points and cameras as a map layer.

A STANDALONE FILE ON PURPOSE. `viz/webmap_export.py` and `webmap/index.html`
are owned by another thread right now, so this writes its OWN file with its own
command (`loci dot-export`) and touches neither. Wiring the layer into the map
later is an `index.html` fetch of `data/dot.json` plus a toggle; nothing in the
existing export has to change, and until that happens the file is inert.

THE SHAPE
---------------------------------------------------------------------------
Column-oriented (`cols` + `rows`), the same packing the other overlays use, so
a 969-camera layer is ~60 KB instead of a quarter of a megabyte of repeated
JSON keys. Coordinates are rounded to 5 decimal places -- about 1.1 m, which is
finer than the position of a camera pole is known and far finer than what a
straight-line distance in this project means.

WHAT THE LAYER MUST SAY ON ITS FACE
---------------------------------------------------------------------------
Both point sets are DOT's operational geography, not a sample of the city, and
a map is exactly where that gets forgotten -- 969 dots look like coverage. So
`caveats` rides in the file and is meant to be rendered UNTRUNCATED wherever
these layers are switched on, the same contract `densityCaveat` has in
meta.json.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: Mirrors webmap_export's output directory WITHOUT importing it -- that module
#: is being edited by another thread and importing it would couple this
#: command's success to the state of a file it does not own.
WEBMAP_DATA = REPO_ROOT / "webmap" / "data"
OUT_NAME = "dot.json"

COUNT_COLS = ["id", "lon", "lat", "boro", "street", "from", "to", "type",
              "round", "am", "md", "pm", "total", "trend", "trendN", "rounds"]
CAMERA_COLS = ["id", "lon", "lat", "name", "boro", "online"]

CAVEATS = {
    "counts": (
        "NYC DOT Bi-Annual Pedestrian Counts: 114 screenlines DOT chose for "
        "traffic engineering, on busy commercial corridors and bridges -- not a "
        "sample of New York. Each number is a MANUAL count over two hours "
        "(AM 07-09, MD 12-14) or three (PM 16-19), on ONE day, twice a year. "
        "'total' is the round's seven counted hours, NOT a daily volume: DOT "
        "publishes no expansion factor. 'trend' is the OLS slope of that total "
        "against decimal years over the last ten years, in people per year, and "
        "is NULL on fewer than three rounds; it is a description of a noisy "
        "series, not a forecast."),
    "cameras": (
        "NYC DOT traffic cameras (NYCTMC): sited at signalised intersections on "
        "ARTERIALS to watch vehicle queues. Manhattan has 376 and the Bronx 81 "
        "-- that gradient is DOT's, not the city's. The dot is the POLE: the "
        "feed publishes no bearing, field of view or height, so what a camera "
        "sees is an unknown distance away in an unknown direction. 'online' is "
        "the feed's own flag and read true for 969 of 969 cameras, so treat it "
        "as 'published', not 'returning frames'."),
    "distance": (
        "Any address-to-DOT distance in this project (dot_point_m, camera_m) is "
        "STRAIGHT-LINE metres, unlike homes_400m and every other *_400m column, "
        "which are NETWORK metres on the pedestrian walk graph. A straight line "
        "is a lower bound on the walk. Never compare the two."),
}


def _num(value, dp: int):
    """Round, and keep NULL as null rather than as 0."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:                                   # NaN
        return None
    return round(f, dp) if dp else int(round(f))


def collect_counts(con, trend_years: int = 10) -> dict:
    """The count points, one row per point, latest complete round + trend."""
    from loci.sources.cities.nyc import dot_pedestrian as dp

    df = dp.point_summary(con, trend_years=trend_years)
    rows = []
    for r in df.itertuples(index=False):
        rows.append([
            int(r.point_id), _num(r.lon, 5), _num(r.lat, 5),
            r.borough, r.street, r.from_street, r.to_street, r.loc_type,
            r.latest_round, _num(r.latest_am, 0), _num(r.latest_md, 0),
            _num(r.latest_pm, 0), _num(r.latest_total, 0),
            _num(r.trend_per_year, 1), _num(r.trend_n_rounds, 0),
            int(r.rounds_present),
        ])
    return {"cols": COUNT_COLS, "rows": rows, "n": len(rows),
            "trendYears": trend_years}


def collect_cameras(con) -> dict:
    """The camera registry. Every camera, online flag included, never filtered
    on it -- see the caveat."""
    df = con.execute("""
        SELECT camera_id, lon, lat, name, borough, is_online
        FROM staging.dot_camera
        WHERE lon IS NOT NULL AND lat IS NOT NULL
        ORDER BY camera_id
    """).fetchdf()
    rows = [[r.camera_id, _num(r.lon, 5), _num(r.lat, 5), r.name, r.borough,
             bool(r.is_online) if r.is_online is not None else None]
            for r in df.itertuples(index=False)]
    return {"cols": CAMERA_COLS, "rows": rows, "n": len(rows)}


def build(con, trend_years: int = 10) -> dict:
    """The whole bundle, in memory. Writes nothing."""
    from loci.sources.cities.nyc import dot_pedestrian as dp

    counts = collect_counts(con, trend_years=trend_years)
    summary = dp.table_summary(con)
    return {
        "generated": dt.datetime.now().replace(microsecond=0).isoformat(),
        "counts": counts,
        "cameras": collect_cameras(con),
        "source": {
            "counts": {"dataset": dp.DATASET_ID, "endpoint": dp.ENDPOINT,
                       "rounds": summary["rounds"],
                       "firstRound": summary["first_round"],
                       "lastRound": summary["last_round"],
                       "observations": summary["rows"]},
            "cameras": {"endpoint":
                        "https://webcams.nyctmc.org/api/cameras"},
        },
        "caveats": CAVEATS,
    }


def export(con, out_dir: pathlib.Path | str | None = None,
           trend_years: int = 10) -> dict:
    """Write `<out_dir>/dot.json`. Returns {path, bytes, counts, cameras}."""
    out = pathlib.Path(out_dir) if out_dir else WEBMAP_DATA
    out.mkdir(parents=True, exist_ok=True)
    bundle = build(con, trend_years=trend_years)
    text = json.dumps(bundle, separators=(",", ":"))
    path = out / OUT_NAME
    path.write_text(text)
    return {"path": str(path), "bytes": len(text.encode()),
            "counts": bundle["counts"]["n"], "cameras": bundle["cameras"]["n"]}
