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
meta.json. `caveats.compare` is the one the LEGEND must carry: a DOT count is
a flow past a screenline and a camera number is a stock in a frame, and the two
are drawn as dots a few pixels apart.

THE CAMERA SAMPLE SUMMARY
---------------------------------------------------------------------------
`samples` is `analysis.sidewalk_count` rolled up to one row per (camera x
day_type x daypart) so a camera popup can show what was actually measured
there. Three of 969 cameras have been sampled, so the block's real job is to
let the map say "not sampled" about the other 966: `samples.cameras` is the
sampled ID list, and a camera absent from it is absent from the measurement,
not quiet.
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

#: `bc` is the two-letter borough CODE and it is last on purpose: the columns
#: are read positionally by the webmap, so a new one is only safe appended.
#: It is NULL for the fourteen bridge midpoints (which belong to no borough)
#: and for DOT's truncated 'Staten Isla' -- an unrecognised borough string maps
#: to null rather than to a guess, the same rule dot_cameras.normalise follows.
COUNT_COLS = ["id", "lon", "lat", "boro", "street", "from", "to", "type",
              "round", "am", "md", "pm", "total", "trend", "trendN", "rounds",
              "bc"]
CAMERA_COLS = ["id", "lon", "lat", "name", "boro", "online"]
#: The per-camera sample summary: one row per (camera x day_type x daypart).
#: Means are 2 dp and everything else is an integer -- this rides in the same
#: file 969 cameras do, and a float per cell would be the whole budget.
SAMPLE_COLS = ["cam", "dayType", "daypart", "frames", "mean", "p50", "max"]

#: The table the sample summary reads. Named here rather than imported so an
#: export still runs on a database that has never sampled a camera.
SAMPLE_TABLE = "analysis.sidewalk_count"

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
    "samples": (
        "A camera sample is PERSONS VISIBLE IN ONE FRAME, averaged over the "
        "frames taken in that day_type x daypart -- a STOCK (who is standing in "
        "the cone of view at an instant), not a flow. It is a detector's reading "
        "of a 352x240 JPEG, so a crowd at 80 m is a few pixels and is missed, "
        "and a camera watching a roadway counts people on the far sidewalk. "
        "Read it as RELATIVE busyness for one camera across time, never as a "
        "headcount and never between cameras with different views."),
}

#: THE ONE LINE THE LEGEND MUST CARRY. The two number families on this layer
#: are different physical quantities and the map is exactly where that gets
#: forgotten, because both are drawn as dots a few pixels apart. Stated here so
#: the page prints it from the payload rather than retyping it.
#:
#: It does NOT say "people per hour": a DOT count is the people counted in a
#: two- or three-hour window, and DOT publishes no expansion factor, so "per
#: hour" would be a rate this project invented.
COMPARE_CAVEAT = (
    "Counts are people counted past a screenline in a two- or three-hour "
    "window (DOT, twice a year, by hand); camera numbers are people in frame "
    "(a stock, not a flow) -- never compare the two.")


def caveats() -> dict:
    """The caveat block, with the trend text READ FROM the source module.

    `trend` is `dot_pedestrian.TREND_CAVEAT` -- the missing September 2019 and
    May 2020 rounds and the June 2024 one are facts about the series, and they
    belong beside the parser that discovered them, not retyped in a viz module
    where nothing would notice them drifting.
    """
    from loci.sources.cities.nyc import dot_pedestrian as dp

    return {**CAVEATS, "trend": dp.TREND_CAVEAT, "compare": COMPARE_CAVEAT}


def _txt(value):
    """A string field, or null -- and NEVER the float NaN.

    A pandas object column holds a missing string as NaN, and `json.dumps`
    writes that as the bare token `NaN`. Python's own `json.load` accepts it;
    `JSON.parse` in every browser does NOT, so one un-named cross street (the
    bridge midpoints have none) is enough to make the whole file unloadable by
    the map it was written for. `export` also passes `allow_nan=False`, so a
    field this helper is not applied to raises instead of shipping.
    """
    if value is None:
        return None
    if isinstance(value, float) and value != value:        # NaN
        return None
    return value


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

    from loci.sources.cities.nyc import dot_cameras as dc

    df = dp.point_summary(con, trend_years=trend_years)
    rows = []
    for r in df.itertuples(index=False):
        rows.append([
            int(r.point_id), _num(r.lon, 5), _num(r.lat, 5),
            _txt(r.borough), _txt(r.street), _txt(r.from_street),
            _txt(r.to_street), _txt(r.loc_type),
            _txt(r.latest_round), _num(r.latest_am, 0), _num(r.latest_md, 0),
            _num(r.latest_pm, 0), _num(r.latest_total, 0),
            _num(r.trend_per_year, 1), _num(r.trend_n_rounds, 0),
            int(r.rounds_present),
            # ONE borough vocabulary for the whole file: the camera registry's
            # own map, so a count point and a camera on the same corner carry
            # the same code and the map's borough filter can hold both.
            dc.AREA_TO_BOROUGH.get(str(_txt(r.borough) or "").strip().lower()),
        ])
    return {"cols": COUNT_COLS, "rows": rows, "n": len(rows),
            "trendYears": trend_years,
            # The counted clock windows, from the source module's own constant,
            # so the popup can say WHICH hours a period is instead of implying
            # three equal thirds of a day.
            "windows": {p: list(w) for p, w in dp.WINDOWS.items()},
            "periods": list(dp.PERIODS)}


def collect_cameras(con) -> dict:
    """The camera registry. Every camera, online flag included, never filtered
    on it -- see the caveat."""
    df = con.execute("""
        SELECT camera_id, lon, lat, name, borough, is_online
        FROM staging.dot_camera
        WHERE lon IS NOT NULL AND lat IS NOT NULL
        ORDER BY camera_id
    """).fetchdf()
    from loci.sources.cities.nyc import dot_cameras as dc

    rows = [[r.camera_id, _num(r.lon, 5), _num(r.lat, 5), _txt(r.name),
             _txt(r.borough),
             bool(r.is_online) if r.is_online is not None else None]
            for r in df.itertuples(index=False)]
    return {"cols": CAMERA_COLS, "rows": rows, "n": len(rows),
            # Code -> the area name DOT publishes, so a popup can say
            # "Queens" without the page carrying a second borough vocabulary
            # (this map's own meta.json knows only the two it draws).
            "boroughNames": {code: area.title()
                             for area, code in dc.AREA_TO_BOROUGH.items()}}


def _has_table(con, qualified: str) -> bool:
    """`analysis.sidewalk_count` may not exist. Asked here rather than caught
    as a SQL error so "nobody has sampled a camera yet" and "the query is
    wrong" stay two different outcomes."""
    schema, _, name = qualified.partition(".")
    return bool(con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, name]).fetchone())


def collect_samples(con) -> dict:
    """Per-camera persons-per-frame, one row per (camera x day_type x daypart).

    NOT A COVERAGE LAYER. Three of 969 cameras have been sampled, so this block
    exists to let the map say "not sampled" about the other 966 rather than to
    shade anything -- `cameras` is the sampled ID list precisely so the page can
    ask that question without scanning the rows.

    The grouping is `model/sidewalk_count.stats`, not a query written here: the
    mean, the median beside it and the day_type x daypart grain are that
    module's decisions (a count that is zero most of the time and eleven once
    has no useful mean), and re-deriving them in a viz module is how two
    numbers for one camera appear in two places.

    `dates` are LOCAL calendar dates. `sampled_at` is stored UTC, and a run
    that starts at 19:00 EDT is stamped the next day in UTC -- printing that in
    a popup would tell a New York reader the sidewalk was watched on a day it
    was not.
    """
    empty = {"available": False, "reason": f"{SAMPLE_TABLE} has no rows",
             "cols": SAMPLE_COLS, "rows": [], "cameras": [], "dates": {},
             "n": 0, "frames": 0, "models": []}
    if not _has_table(con, SAMPLE_TABLE):
        return {**empty, "reason": f"{SAMPLE_TABLE} does not exist -- "
                                   f"`loci sidewalk-count sample` has not run"}

    from loci.model import sidewalk_count as sw

    df = sw.stats(con)
    if df.empty:
        return empty
    rows = [[r.camera_id, _txt(r.day_type), _txt(r.daypart), int(r.frames),
             _num(r.mean_persons, 2), _num(r.p50_persons, 2),
             _num(r.max_persons, 0)]
            for r in df.itertuples(index=False)]

    stamps = con.execute(
        f"SELECT camera_id, sampled_at FROM {SAMPLE_TABLE}").fetchdf()
    local = stamps["sampled_at"]
    local = (local.dt.tz_localize("UTC") if local.dt.tz is None else local)
    stamps["day"] = local.dt.tz_convert(sw.LOCAL_TZ).dt.strftime("%Y-%m-%d")
    dates = {cam: sorted(set(g)) for cam, g in
             stamps.groupby("camera_id")["day"]}

    models = con.execute(
        f"SELECT DISTINCT model, model_version FROM {SAMPLE_TABLE} "
        f"ORDER BY 1, 2").fetchall()
    return {"available": True, "reason": None,
            "cols": SAMPLE_COLS, "rows": rows, "n": len(rows),
            "cameras": sorted(dates),
            "dates": dates,
            "frames": int(sum(r[3] for r in rows)),
            "dayparts": list(sw.DAYPART_NAMES),
            "dayTypes": list(sw.DAY_TYPES),
            "models": [f"{m}@{v}" for m, v in models]}


def build(con, trend_years: int = 10) -> dict:
    """The whole bundle, in memory. Writes nothing."""
    from loci.sources.cities.nyc import dot_pedestrian as dp

    counts = collect_counts(con, trend_years=trend_years)
    summary = dp.table_summary(con)
    return {
        "generated": dt.datetime.now().replace(microsecond=0).isoformat(),
        "counts": counts,
        "cameras": collect_cameras(con),
        "samples": collect_samples(con),
        "source": {
            "counts": {"dataset": dp.DATASET_ID, "endpoint": dp.ENDPOINT,
                       "rounds": summary["rounds"],
                       "firstRound": summary["first_round"],
                       "lastRound": summary["last_round"],
                       "observations": summary["rows"]},
            "cameras": {"endpoint":
                        "https://webcams.nyctmc.org/api/cameras"},
        },
        "caveats": caveats(),
    }


def export(con, out_dir: pathlib.Path | str | None = None,
           trend_years: int = 10) -> dict:
    """Write `<out_dir>/dot.json`. Returns {path, bytes, counts, cameras}."""
    out = pathlib.Path(out_dir) if out_dir else WEBMAP_DATA
    out.mkdir(parents=True, exist_ok=True)
    bundle = build(con, trend_years=trend_years)
    # allow_nan=False IS THE POINT. The default writes bare `NaN`/`Infinity`,
    # which Python reads back happily and `JSON.parse` refuses -- a file that
    # looks fine from a test and is unloadable by the map. Raising here is the
    # only way that failure is ever seen.
    text = json.dumps(bundle, separators=(",", ":"), allow_nan=False)
    path = out / OUT_NAME
    path.write_text(text)
    return {"path": str(path), "bytes": len(text.encode()),
            "counts": bundle["counts"]["n"], "cameras": bundle["cameras"]["n"],
            "sampled": len(bundle["samples"]["cameras"]),
            "sampleFrames": bundle["samples"]["frames"]}
