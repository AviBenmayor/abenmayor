"""Sample a public traffic camera and count the people in each frame.

    analysis.sidewalk_count(camera_id, sampled_at, n_persons, n_persons_conf50,
                            model, model_version, frame_hash, daypart, day_type)

    loci sidewalk-count sample   --camera <id> | --near "lat,lon" --minutes N
    loci sidewalk-count schedule --camera <id> --days D
    loci sidewalk-count stats    [--camera <id>]
    loci sidewalk-count validate [--round 2026-05]

WHY THIS EXISTS (owner request, 2026-09-13)
---------------------------------------------------------------------------
"We need NYC DOT data, both the bi-annual and the camera data." The bi-annual
hand counts are already wired as an external check (`loci validate-pedestrian`,
GTM-146) and they are a fine yardstick and a useless instrument: 114
screenlines, two hours, three windows, twice a year, on corridors chosen by
traffic engineers. The cameras are the opposite -- 969 feeds, everywhere, all
day, refreshing every few seconds, and nobody has ever counted what is in
them. This module turns the second into a measurement and uses the first to
check it.

WHAT A ROW MEANS, IN ONE SENTENCE THAT MUST NEVER BE DROPPED
---------------------------------------------------------------------------
PERSONS VISIBLE IN ONE FRAME. A STOCK, not a FLOW. The DOT count is a flow
(people crossing a screenline per hour); this is a stock (people standing in a
cone of view at an instant). Little's law is the only bridge -- stock = flow x
dwell -- and nothing here measures dwell, so `validate()` reports a RANK
correlation and deliberately refuses to emit a conversion factor. A corner
with a bus stop and a light cycle holds people; a mid-block camera on the same
sidewalk flow does not. That difference is the measurement, and it is also the
confound.

THE DUPLICATE PROBLEM IS THE WHOLE SAMPLER
---------------------------------------------------------------------------
The feed serves the last decoded still, and the refresh is not synchronised to
anything. Fetch every 10 s and a meaningful share of responses are the
byte-identical file you already have. Scoring those again does not add
information, it multiplies the frames that happened to be served twice --
which biases the mean toward whatever was on screen during a slow refresh.
Every frame is therefore keyed by the sha256 of its BYTES, duplicates within a
run are skipped before the detector ever sees them, and the duplicate rate is
reported so a camera that has frozen is visible rather than silently
contributing sixty copies of one moment.

Hashing the BYTES rather than the pixels is deliberate. A re-encode of the
same scene is a new file, and we have no way to distinguish it from a genuine
refresh of a static scene; treating it as new is the conservative error, since
the alternative (perceptual hashing) would throw away real frames of an empty
sidewalk, which are exactly the observations a "quiet corner" reading needs.

PORTABILITY
---------------------------------------------------------------------------
The only NYC-specific things here are `CAMERA_TABLE` / `COUNT_TABLE` (the
staging contract another city would swap) and the daypart boundaries imported
from `sources.cities.nyc.mta_ridership` -- imported, not redefined, so the
sampler's `daypart` and the D76 transit profile's `daypart` are the same five
edges by construction. The detector knows nothing about any city at all.

BUDGETS ARE IN CODE
---------------------------------------------------------------------------
`MAX_FRAMES_PER_RUN` (720) caps a single run before it starts AND the loop
breaks on the same counter, so a clock bug cannot turn an overnight typo into
60,000 requests at a public endpoint. `--dry-run` prints the plan and fetches
exactly one frame, which is also the only way to check a camera is alive
without writing anything.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import math
import pathlib
import time
import zoneinfo

import pandas as pd
import requests

from loci.db import METRES_SQL
from loci.sources.cities.nyc.mta_ridership import (
    DAYPART_NAMES,
    DAY_TYPES,
    DOT_WINDOWS,
    day_type_of,
    daypart_of,
)
from loci.vision.person_detector import load_detector, sha256

#: <repo>/src/loci/model/sidewalk_count.py -> three up is src/, four is the repo.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FRAME_DIR = REPO_ROOT / "data" / "frames"

#: The staging contract this reads. One city, one pair of names; swapping them
#: is the whole of what porting the sampler to another city's camera feed costs.
CAMERA_TABLE = "staging.dot_camera"
COUNT_TABLE = "staging.dot_pedestrian_count"
OUT_TABLE = "analysis.sidewalk_count"

#: `sampled_at` is stored UTC; `daypart` and `day_type` are questions about the
#: LOCAL clock. One definition, here, so nothing downstream re-derives it.
LOCAL_TZ = zoneinfo.ZoneInfo("America/New_York")

#: BUDGET. 720 frames is two hours at 10 s, or one hour at 5 s -- long enough
#: for any single-session question and short enough that a mistake is cheap.
#: A longer study is many runs, which is what `schedule` is for.
MAX_FRAMES_PER_RUN = 720
#: Politeness floor. The feed itself refreshes in seconds; asking faster than
#: this buys duplicates, not data.
MIN_INTERVAL_S = 2.0
#: Give up on the camera, not on the run, after this many consecutive failures.
MAX_CONSECUTIVE_ERRORS = 5
FETCH_TIMEOUT_S = 20
#: How close a camera must be to a DOT count point to be treated as looking at
#: the same sidewalk. 60 m is roughly one Manhattan mid-block: further than
#: that and the camera is watching a different corner of the intersection.
VALIDATE_RADIUS_M = 60.0


class CameraRegistryMissing(RuntimeError):
    """The staging camera registry is not in the warehouse yet."""


class BudgetExceeded(RuntimeError):
    """A run was asked for more frames than the in-code budget allows."""


@dataclasses.dataclass(frozen=True)
class Camera:
    camera_id: str
    name: str
    lon: float
    lat: float
    image_url: str
    borough: str | None = None
    dist_m: float | None = None


@dataclasses.dataclass(frozen=True)
class SamplePlan:
    camera: Camera
    minutes: float
    interval_s: float
    frames: int
    est_seconds: float

    def describe(self) -> str:
        return (f"{self.camera.camera_id} {self.camera.name!r}: {self.frames} frames "
                f"over {self.minutes:g} min at {self.interval_s:g} s "
                f"(~{self.est_seconds / 60:.1f} min wall clock)")


# ---------------------------------------------------------------------------
# camera resolution
# ---------------------------------------------------------------------------

def _table_exists(con, qualified: str) -> bool:
    schema, _, name = qualified.partition(".")
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, name]).fetchone()[0])


def _require_registry(con) -> None:
    if not _table_exists(con, CAMERA_TABLE):
        raise CameraRegistryMissing(
            f"{CAMERA_TABLE} is not in the warehouse. The sampler reads the camera "
            f"registry rather than the live feed on purpose: a run has to be able to "
            f"say WHICH camera and WHERE it was pointing months later, and an id "
            f"resolved against a feed that has since changed cannot. Run "
            f"`loci dot-cameras ingest` first."
        )


def get_camera(con, camera_id: str) -> Camera:
    _require_registry(con)
    row = con.execute(
        f"SELECT camera_id, name, lon, lat, image_url, borough "
        f"FROM {CAMERA_TABLE} WHERE camera_id = ?", [camera_id]).fetchone()
    if row is None:
        raise KeyError(f"camera {camera_id!r} is not in {CAMERA_TABLE}")
    return Camera(*row)


def cameras_near(con, lat: float, lon: float, radius_m: float = 300.0,
                 limit: int = 20) -> list[Camera]:
    """Cameras within `radius_m` great-circle metres of a point, nearest first."""
    _require_registry(con)
    dist = METRES_SQL.format(a="ST_Point(lon, lat)", b="ST_Point(?, ?)")
    rows = con.execute(
        f"SELECT camera_id, name, lon, lat, image_url, borough, {dist} AS dist_m "
        f"FROM {CAMERA_TABLE} WHERE {dist} <= ? ORDER BY dist_m LIMIT ?",
        [lon, lat, lon, lat, radius_m, limit]).fetchall()
    return [Camera(*r) for r in rows]


# ---------------------------------------------------------------------------
# planning and budget
# ---------------------------------------------------------------------------

def plan_run(camera: Camera, minutes: float, interval_s: float,
             max_frames: int = MAX_FRAMES_PER_RUN) -> SamplePlan:
    """Frames this run would take, refusing over budget BEFORE any request."""
    if interval_s < MIN_INTERVAL_S:
        raise BudgetExceeded(
            f"--interval-s {interval_s:g} is below the {MIN_INTERVAL_S:g} s politeness "
            f"floor. The feed refreshes in seconds; a shorter interval buys duplicate "
            f"bytes, not observations.")
    if minutes <= 0:
        raise BudgetExceeded(f"--minutes {minutes:g} must be positive.")
    frames = int(math.floor(minutes * 60.0 / interval_s)) + 1
    if frames > max_frames:
        raise BudgetExceeded(
            f"{minutes:g} min at {interval_s:g} s is {frames} frames, over the "
            f"MAX_FRAMES_PER_RUN budget of {max_frames}. Either shorten the run to "
            f"<= {max_frames * interval_s / 60:.0f} min, lengthen the interval to "
            f">= {minutes * 60 / (max_frames - 1):.1f} s, or split it across runs with "
            f"`loci sidewalk-count schedule`. The budget is in code and is not a "
            f"CLI flag: an overnight typo at a public endpoint is not a recoverable "
            f"mistake.")
    return SamplePlan(camera=camera, minutes=minutes, interval_s=interval_s,
                      frames=frames, est_seconds=(frames - 1) * interval_s)


def schedule_plan(camera: Camera, days: int, interval_s: float = 10.0,
                  minutes_per_daypart: float = 10.0) -> pd.DataFrame:
    """The launchd-friendly plan: which dayparts, how many frames. RUNS NOTHING.

    One block per day type x daypart, sized so a single block fits the run
    budget. The launch time is the MIDPOINT of the daypart rather than its
    start: a block that begins at 06:00 sharp measures the quietest ten minutes
    of am_peak and calls it the peak.
    """
    from loci.sources.cities.nyc.mta_ridership import DAYPARTS

    if days < 1:
        raise ValueError("--days must be >= 1")
    rows = []
    frames = plan_run(camera, minutes_per_daypart, interval_s).frames
    # A day type recurs a different number of times in D days: 5/7 of days are
    # weekdays. Reporting that is the difference between a plan and a wish.
    per_week = {"weekday": 5, "saturday": 1, "sunday": 1}
    for day_type in DAY_TYPES:
        occurrences = max(1, round(days * per_week[day_type] / 7))
        for name, a, b in DAYPARTS:
            mid = (a + b) // 2
            rows.append({
                "day_type": day_type,
                "daypart": name,
                "hours": f"{a:02d}-{b:02d}",
                "launch_local": f"{mid:02d}:00",
                "minutes": minutes_per_daypart,
                "interval_s": interval_s,
                "frames_per_block": frames,
                "blocks": occurrences,
                "frames_total": frames * occurrences,
            })
    df = pd.DataFrame(rows)
    df.attrs["camera_id"] = camera.camera_id
    df.attrs["days"] = days
    return df


# ---------------------------------------------------------------------------
# the sampler
# ---------------------------------------------------------------------------

def _fetch(session: requests.Session, url: str) -> bytes:
    resp = session.get(url, timeout=FETCH_TIMEOUT_S)
    resp.raise_for_status()
    body = resp.content
    if not body or len(body) < 1024:
        raise ValueError(f"camera returned {len(body)} bytes, which is not a frame")
    return body


def _stamp(now_utc: dt.datetime) -> tuple[str, str]:
    """UTC instant -> (daypart, day_type) on the NEW YORK clock.

    Imported boundaries, never redefined: `daypart_of` and `day_type_of` are
    the same functions the D76 transit profile uses. `day_type_of` takes
    Socrata's day-of-week encoding (0 = Sunday), not Python's (0 = Monday).
    """
    local = now_utc.replace(tzinfo=dt.timezone.utc).astimezone(LOCAL_TZ)
    return daypart_of(local.hour), day_type_of((local.weekday() + 1) % 7)


def sample(camera: Camera, minutes: float, interval_s: float, *,
           detector=None, fetch_fn=None, sleep_fn=time.sleep,
           clock=None, keep_frames: bool = False,
           dry_run: bool = False, max_frames: int = MAX_FRAMES_PER_RUN) -> dict:
    """Fetch, deduplicate, count. Returns rows + a report; WRITES NOTHING.

    Persisting is `write_rows()`'s job and happens once, at the end, so the
    warehouse lock is held for a second rather than for the length of the run
    -- another session rebuilding the database mid-sample is normal here (D69).

    `fetch_fn`, `sleep_fn`, `clock` and `detector` are injected so the budget,
    the duplicate skip and the daypart stamp are testable without the network.
    """
    plan = plan_run(camera, minutes, interval_s, max_frames=max_frames)
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    detector = detector or load_detector()
    session = requests.Session()
    fetch_fn = fetch_fn or (lambda url: _fetch(session, url))

    frame_dir = FRAME_DIR / camera.camera_id
    if keep_frames and not dry_run:
        frame_dir.mkdir(parents=True, exist_ok=True)

    target = 1 if dry_run else plan.frames
    rows: list[dict] = []
    seen: set[str] = set()
    n_fetched = n_dup = n_err = 0
    consecutive = 0
    detect_seconds = 0.0
    bytes_total = 0

    for i in range(target):
        if n_fetched >= max_frames:
            # The same counter the plan was checked against. A plan can only be
            # wrong about the future; this cannot.
            break
        if i:
            sleep_fn(interval_s)
        try:
            body = fetch_fn(camera.image_url)
        except Exception as exc:                       # noqa: BLE001 - any transport error
            n_err += 1
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_ERRORS:
                raise RuntimeError(
                    f"camera {camera.camera_id} failed {consecutive} times in a row "
                    f"({exc}). Stopping rather than writing a run whose gaps look "
                    f"like an empty sidewalk.") from exc
            continue
        consecutive = 0
        n_fetched += 1
        bytes_total += len(body)
        h = sha256(body)
        if h in seen:
            n_dup += 1
            continue
        seen.add(h)

        at = clock()
        det = detector.count(body)
        detect_seconds += det.seconds
        daypart, day_type = _stamp(at)
        rows.append({
            "camera_id": camera.camera_id,
            "sampled_at": at,
            "n_persons": det.n_persons,
            "n_persons_conf50": det.n_persons_conf50,
            "model": detector.model,
            "model_version": detector.version,
            "frame_hash": h,
            "daypart": daypart,
            "day_type": day_type,
        })
        if keep_frames and not dry_run:
            (frame_dir / f"{at:%Y%m%dT%H%M%S}_{h[:12]}.jpg").write_bytes(body)

    counts = [r["n_persons"] for r in rows]
    report = {
        "camera_id": camera.camera_id,
        "camera_name": camera.name,
        "planned_frames": plan.frames,
        "fetched": n_fetched,
        "unique": len(rows),
        "duplicates": n_dup,
        "duplicate_rate": (n_dup / n_fetched) if n_fetched else 0.0,
        "errors": n_err,
        "model": detector.model,
        "model_version": detector.version,
        "model_quality": detector.quality,
        "mean_bytes": (bytes_total / n_fetched) if n_fetched else 0,
        "seconds_per_frame": (detect_seconds / len(rows)) if rows else 0.0,
        "mean_persons": (sum(counts) / len(counts)) if counts else 0.0,
        "max_persons": max(counts) if counts else 0,
        "keep_frames": bool(keep_frames and not dry_run),
        "dry_run": dry_run,
    }
    return {"rows": rows, "report": report, "plan": plan}


def write_rows(con, rows: list[dict]) -> int:
    """INSERT the run, ignoring frames already stored. Returns rows written.

    ON CONFLICT DO NOTHING on (camera_id, frame_hash, model, model_version):
    re-running a sample that overlapped a previous one adds the new frames and
    silently drops the shared ones, which is the only behaviour that makes a
    mean over the table independent of how many times it was collected.
    """
    if not rows:
        return 0
    before = con.execute(f"SELECT count(*) FROM {OUT_TABLE}").fetchone()[0]
    con.executemany(
        f"INSERT INTO {OUT_TABLE} (camera_id, sampled_at, n_persons, n_persons_conf50, "
        f"model, model_version, frame_hash, daypart, day_type) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        [[r["camera_id"], r["sampled_at"], r["n_persons"], r["n_persons_conf50"],
          r["model"], r["model_version"], r["frame_hash"], r["daypart"], r["day_type"]]
         for r in rows])
    after = con.execute(f"SELECT count(*) FROM {OUT_TABLE}").fetchone()[0]
    return int(after - before)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def stats(con, camera_id: str | None = None) -> pd.DataFrame:
    """Per camera x day_type x daypart: N frames, mean / p50 / max persons.

    The MEDIAN is here because the mean of a count that is zero most of the
    time and eleven once is not a description of the sidewalk. Both are
    reported, and a camera where they disagree badly is a camera whose reading
    rests on a handful of frames.
    """
    where, params = "", []
    if camera_id:
        where, params = "WHERE s.camera_id = ?", [camera_id]
    name = ("c.name" if _table_exists(con, CAMERA_TABLE) else "s.camera_id")
    join = (f"LEFT JOIN {CAMERA_TABLE} c USING (camera_id)"
            if _table_exists(con, CAMERA_TABLE) else "")
    return con.execute(f"""
        SELECT s.camera_id,
               {name}                                AS camera,
               s.day_type,
               s.daypart,
               count(*)                              AS frames,
               round(avg(s.n_persons), 2)            AS mean_persons,
               median(s.n_persons)                   AS p50_persons,
               max(s.n_persons)                      AS max_persons,
               round(avg(s.n_persons_conf50), 2)     AS mean_conf50,
               min(s.sampled_at)                     AS first_utc,
               max(s.sampled_at)                     AS last_utc
        FROM {OUT_TABLE} s {join} {where}
        GROUP BY 1, 2, 3, 4
        ORDER BY s.camera_id,
                 array_position({list(DAY_TYPES)!r}::VARCHAR[], s.day_type),
                 array_position({list(DAYPART_NAMES)!r}::VARCHAR[], s.daypart)
    """, params).fetchdf()


# ---------------------------------------------------------------------------
# validation against the bi-annual hand counts
# ---------------------------------------------------------------------------

def _camera_point_pairs(con, radius_m: float = VALIDATE_RADIUS_M,
                        round_: str | None = None) -> pd.DataFrame:
    """Every (camera, DOT count point) pair within `radius_m`, with the counts.

    The join is a cross product filtered by distance, not a nearest-neighbour
    lookup: a count point can sit between two cameras and both of them are
    looking at it. Which pairing is right is a question the data answers, and
    collapsing to the nearest would hide it.

    BRIDGE MIDPOINTS ARE EXCLUDED (`is_bridge`), for the same reason
    validation/pedestrian_counts.py excludes them: `loc` 101-114 are East and
    Harlem River bridge midspans, and a camera 8 m from the Brooklyn Bridge
    midspan is pointed at a roadway, not at a sidewalk this project screens.
    Observed on the live pairing before this filter: three of the fifteen
    matched cameras were bridge cameras, and they would have contributed a
    third of the correlation from a population the screen never looks at.
    """
    for t in (CAMERA_TABLE, COUNT_TABLE):
        if not _table_exists(con, t):
            raise CameraRegistryMissing(
                f"{t} is not in the warehouse; validation needs both the camera "
                f"registry and the bi-annual counts.")
    dist = METRES_SQL.format(a="ST_Point(c.lon, c.lat)", b="ST_Point(p.lon, p.lat)")
    # `round` is 'YYYY-MM' (sql/022_dot.sql), so string order IS chronological
    # order and the last one is the latest round.
    rounds = con.execute(f"SELECT DISTINCT round FROM {COUNT_TABLE} "
                         f"ORDER BY round").fetchdf()["round"].tolist()
    if round_ is None and rounds:
        round_ = rounds[-1]
    return con.execute(f"""
        SELECT c.camera_id, c.name AS camera, c.borough,
               p.point_id, p.period, p.count AS dot_count,
               p.round, {dist} AS dist_m
        FROM {CAMERA_TABLE} c
        JOIN {COUNT_TABLE} p ON {dist} <= ?
        WHERE p.round = ? AND NOT coalesce(p.is_bridge, FALSE)
        ORDER BY c.camera_id, p.point_id, p.period
    """, [radius_m, round_]).fetchdf()


def camera_window_means(con, camera_ids: list[str] | None = None) -> pd.DataFrame:
    """Mean persons-per-frame per camera per DOT window, on the LOCAL clock.

    The local-hour conversion is done in pandas rather than SQL so the result
    does not depend on DuckDB's ICU extension being loaded on whatever machine
    runs it -- and because `sampled_at` is stored UTC precisely so that this
    conversion is explicit somewhere a reader can find it.
    """
    q = f"SELECT camera_id, sampled_at, n_persons, n_persons_conf50 FROM {OUT_TABLE}"
    params: list = []
    if camera_ids:
        q += f" WHERE camera_id IN ({','.join('?' * len(camera_ids))})"
        params = list(camera_ids)
    # The column list is declared ONCE and used for the empty return too. Two
    # different empty paths land here -- nothing sampled at all, and (the one
    # that actually bit) everything sampled on a WEEKEND, when DOT counts only
    # weekdays -- and an empty frame with no columns makes the caller's merge
    # raise KeyError instead of reporting N = 0.
    cols = ["camera_id", "period", "frames", "mean_persons", "p50_persons",
            "max_persons"]
    df = con.execute(q, params).fetchdf()
    if df.empty:
        return pd.DataFrame(columns=cols)
    local = (df["sampled_at"].dt.tz_localize("UTC").dt.tz_convert(LOCAL_TZ))
    df["local_hour"] = local.dt.hour
    df["weekday"] = local.dt.weekday < 5
    out = []
    for period, (a, b) in DOT_WINDOWS.items():
        # DOT counts WEEKDAYS. A Saturday frame is not a counterpart to it.
        m = df[(df["local_hour"] >= a) & (df["local_hour"] < b) & df["weekday"]]
        for cam, g in m.groupby("camera_id"):
            out.append({"camera_id": cam, "period": period, "frames": len(g),
                        "mean_persons": g["n_persons"].mean(),
                        "p50_persons": g["n_persons"].median(),
                        "max_persons": int(g["n_persons"].max())})
    return pd.DataFrame(out, columns=cols)


def validate(con, radius_m: float = VALIDATE_RADIUS_M,
             round_: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Camera persons-per-frame vs the DOT hand count, at co-located points.

    Returns (per-pair table, report). READ-ONLY; writes nothing, and no score
    reads the result.

    THE COMPARISON IS A RANK CORRELATION AND NOTHING ELSE. The two sides are
    different physical quantities (stock vs flow, see the module docstring), so
    a ratio between them would be a dwell time in disguise, estimated from one
    number. What a positive rank correlation would support is narrow and
    useful: that the camera count ORDERS the three windows of a day, and orders
    co-located places, the way a hand count does.

    It will be thin for a long time. Only cameras that have actually been
    sampled can appear, so N is reported at every level and an empty result is
    a normal, explicitly-stated outcome rather than an error.
    """
    pairs = _camera_point_pairs(con, radius_m=radius_m, round_=round_)
    sampled = con.execute(
        f"SELECT DISTINCT camera_id FROM {OUT_TABLE}").fetchdf()["camera_id"].tolist()
    report = {
        "radius_m": radius_m,
        "round": (pairs["round"].iloc[0] if len(pairs) else None),
        "pairs_in_radius": int(len(pairs)),
        "cameras_in_radius": int(pairs["camera_id"].nunique()) if len(pairs) else 0,
        "points_in_radius": int(pairs["point_id"].nunique()) if len(pairs) else 0,
        "cameras_sampled": len(sampled),
    }
    if not len(pairs) or not sampled:
        report["cameras_compared"] = 0
        report["n"] = 0
        report["spearman_rho"] = None
        report["spearman_rho_raw_count"] = None
        report["note"] = ("no co-located camera has been sampled yet — the join is "
                          "correct and the intersection is empty")
        return pairs.head(0), report

    means = camera_window_means(con, camera_ids=sampled)
    if means.empty:
        report["cameras_compared"] = 0
        report["n"] = 0
        report["spearman_rho"] = None
        report["spearman_rho_raw_count"] = None
        report["note"] = ("cameras have been sampled, but no frame falls in a DOT "
                          "count window on a WEEKDAY — DOT counts weekdays only, so "
                          "a weekend sample has no counterpart to compare against")
        return pairs.head(0), report
    merged = pairs.merge(means, on=["camera_id", "period"], how="inner")

    # DOT'S THREE WINDOWS ARE NOT THE SAME LENGTH: am 07-09 and md 12-14 are two
    # hours, pm 16-19 is THREE (sql/022_dot.sql). Correlating the raw counts
    # across windows would reward pm for being an hour longer, which is a
    # property of the protocol and not of the sidewalk. The camera side is
    # already a RATE (persons per frame), so the count is put on a rate footing
    # too -- people per counted hour. That is division by a known window
    # length, not a day-expansion factor: DOT publishes none and none is
    # invented here. Both rhos are reported, because a big gap between them
    # says the ranking is being driven by window length.
    hours = {p: float(b - a) for p, (a, b) in DOT_WINDOWS.items()}
    merged["window_hours"] = merged["period"].map(hours)
    merged["dot_per_hour"] = merged["dot_count"] / merged["window_hours"]

    report["cameras_compared"] = int(merged["camera_id"].nunique())
    report["n"] = int(len(merged))
    if len(merged) >= 3:
        def _rho(col: str) -> float | None:
            r = merged["mean_persons"].corr(merged[col], method="spearman")
            return None if pd.isna(r) else float(r)
        report["spearman_rho"] = _rho("dot_per_hour")
        report["spearman_rho_raw_count"] = _rho("dot_count")
    else:
        report["spearman_rho"] = None
        report["spearman_rho_raw_count"] = None
        report["note"] = (f"{len(merged)} matched (camera, window) observations — a "
                          f"correlation over fewer than 3 is not a number, it is a "
                          f"line through the points")
    return merged, report
