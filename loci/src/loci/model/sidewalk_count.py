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

THE WEEKLY SWEEP (owner ruling 2026-09-17) AND ITS LEGAL EXPOSURE
---------------------------------------------------------------------------
    loci sidewalk-count sweep    --window am|md|pm [--max-cameras N] [--dry-run]
    loci sidewalk-count flush                      # spool -> warehouse
    loci sidewalk-count schedule --install|--uninstall|--status
    loci sidewalk-count report   --camera <id> | --nta <code>

The owner chose EVERY Manhattan + Brooklyn camera in staging.dot_camera,
weekly on two weekdays (Tue + Thu), one frame per 10 min across each of the
three DOT windows (am 07-09, md 12-14, pm 16-19) -- over the scope memo's
advice of <= 60 cameras -- knowing the following, recorded here verbatim from
the memo (2026-09-17, §1b):

    "Regime A, one frame per 10 min across each 2 h DOT window: 20,880
    frames/week, 0.5 GB transferred, 9 CPU-min at 0.027 s/frame (D85), ~2 MB
    of rows. Regime B, today's 10 s cadence: 106,000 frames/week, 2.4 GB, 48
    CPU-min, ~58 req/s in parallel -- a scrape. The binding cost is legal:
    DOT sent Traffic Cam Photobooth a cease-and-desist on 2024-11-06 for
    "unauthorized use of NYC traffic cameras"
    (https://www.404media.co/traffic-cam-photobooth-cease-and-desist); the
    feed is not Open Data. My ruling: Regime A at <= 60 cameras (validation
    pairs plus shortlist anchors), not 580, until terms are read or an ask
    goes in beside the VivaCity one."

The ask is drafted at docs/asks/dot-camera-and-vivacity-2026-09-17.md.
`--max-cameras N` exists so the OWNER can throttle; its default is ALL (the
owner's "never limit data pulls" rule), and it is the only knob -- the
cadence (SWEEP_INTERVAL_S) and the windows are constants, not flags.

THE PRIVACY RULE (memo §1e, verbatim)
---------------------------------------------------------------------------
    "Privacy rule: persons are counted in memory and never stored; no frame
    is kept without `--keep-frames` (QA-only, gitignored, local); no face,
    plate or track is ever produced; rows are aggregate per camera x
    timestamp."

Built as two protections: (1) `sweep()` decodes each frame, counts, and drops
the bytes -- the only thing that survives a tick is the row of integers and
a 9x8 grey thumbnail accumulated into the run's MEAN frame for the scene
hash (people are averaged out of it by construction); (2) `--keep-frames` is
the one path that writes a JPEG, to data/frames/<camera>/, gitignored, local.

THE SCENE HASH (memo §1e: "unannounced re-aiming (detect by scene hash)")
---------------------------------------------------------------------------
DOT staff "may reposition them to view traffic from varying directions"
(https://www.nyc.gov/html/dot/html/motorist/atis.shtml). A camera that has
been re-aimed and is then compared with its own history is a different
instrument wearing the same id. Each sweep therefore dHashes the camera's
mean frame over the run and compares it with the previous run's hash; a
Hamming distance over SCENE_CHANGE_BITS sets `scene_changed` on every row of
the run, and `report` starts a camera's "own history" at its last change
rather than silently reading across it.

THE SPOOL. A sweep never waits on the warehouse lock: rows go to
data/sidewalk/spool/<run_id>.parquet after every tick, and `flush` (called at
the end of the sweep, and available on its own) moves them into
analysis.sidewalk_count with ON CONFLICT DO NOTHING. A long ingest holding the
file for hours (the normal state of this warehouse, D69) costs the sweep
nothing but a later flush.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import datetime as dt
import json
import math
import os
import pathlib
import plistlib
import shutil
import subprocess
import time
import zoneinfo

import numpy as np
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
#: Sweep rows wait here until the warehouse lock is free (see module docstring).
SPOOL_DIR = REPO_ROOT / "data" / "sidewalk" / "spool"
#: The previous run's scene hash per camera, so a sweep can flag a re-aim
#: without opening the warehouse. The warehouse rows are the record; this is
#: the sweep's working copy of the last one.
SCENE_STATE_PATH = REPO_ROOT / "data" / "sidewalk" / "scene_hashes.json"
#: Generated launchd plists live here (gitignored); `schedule --install`
#: copies them to ~/Library/LaunchAgents.
LAUNCHD_DIR = REPO_ROOT / "data" / "launchd"
LAUNCHD_LABEL = "com.loci.sidewalk-sweep"

#: THE SWEEP CONTRACT. One frame per camera per SWEEP_INTERVAL_S across each
#: DOT window, every camera in SWEEP_BOROUGHS, on SWEEP_WEEKDAYS. The windows
#: are DOT_WINDOWS (imported, so the sweep and `validate` cannot disagree
#: about what "am" means). launchd weekday numbering: 0 = Sunday .. 6 =
#: Saturday, so Tue + Thu are 2 and 4.
SWEEP_INTERVAL_S = 600.0
SWEEP_BOROUGHS: tuple[str, ...] = ("MN", "BK")
SWEEP_WEEKDAYS: tuple[int, ...] = (2, 4)
#: Parallel fetches within a tick. 580 cameras at 8-wide and ~0.3 s each is
#: ~25 s per tick, well inside the 600 s interval; higher buys nothing but
#: a burst the endpoint can see.
SWEEP_CONCURRENCY = 8
#: Hamming distance (of 64 bits) between this run's and the previous run's
#: mean-frame dHash above which the camera is treated as re-aimed. 10 bits is
#: the conventional "different image" cut for dHash; lighting and weather
#: move a fixed scene by 0-6 bits in practice.
SCENE_CHANGE_BITS = 10
#: The extra COCO classes stored beside persons (memo §1c). The column names
#: mirror vision.person_detector.EXTRA_CLASSES; NULL when a detector cannot
#: produce them.
EXTRA_CLASS_COLUMNS: tuple[str, ...] = ("n_car", "n_truck", "n_bus", "n_bicycle")

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


#: Every column write_rows() names, in one place. The sweep columns (run_id,
#: scene_hash, scene_changed) and the extra classes are NULL on a plain
#: `sample` run before sql/053 -- write_rows reads them with .get().
ROW_COLUMNS: tuple[str, ...] = (
    "camera_id", "sampled_at", "n_persons", "n_persons_conf50", "model",
    "model_version", "frame_hash", "daypart", "day_type",
    *EXTRA_CLASS_COLUMNS, "run_id", "scene_hash", "scene_changed",
)


def _row(camera: Camera, at: dt.datetime, det, detector, frame_hash: str,
         daypart: str, day_type: str, run_id: str | None = None) -> dict:
    extra = getattr(det, "extra", {}) or {}
    return {
        "camera_id": camera.camera_id,
        "sampled_at": at,
        "n_persons": det.n_persons,
        "n_persons_conf50": det.n_persons_conf50,
        "model": detector.model,
        "model_version": detector.version,
        "frame_hash": frame_hash,
        "daypart": daypart,
        "day_type": day_type,
        "n_car": extra.get("car"),
        "n_truck": extra.get("truck"),
        "n_bus": extra.get("bus"),
        "n_bicycle": extra.get("bicycle"),
        "run_id": run_id,
        "scene_hash": None,
        "scene_changed": None,
    }


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
        rows.append(_row(camera, at, det, detector, h, daypart, day_type))
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


def _present_columns(con) -> tuple[str, ...]:
    """ROW_COLUMNS restricted to what the table has. A warehouse that has not
    yet replayed sql/053 (a `sample` run applies 024 alone) still takes the
    nine original columns; the sweep columns wait for the next init."""
    schema, _, name = OUT_TABLE.partition(".")
    have = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ?", [schema, name]).fetchall()}
    return tuple(c for c in ROW_COLUMNS if c in have)


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
    cols = _present_columns(con)
    con.executemany(
        f"INSERT INTO {OUT_TABLE} ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' for _ in cols)}) ON CONFLICT DO NOTHING",
        [[r.get(c) for c in cols] for r in rows])
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


# ---------------------------------------------------------------------------
# the scene hash -- "same view?", as distinct from frame_hash's "same file?"
# ---------------------------------------------------------------------------

#: dHash geometry: a 9x8 grey thumbnail gives 8 horizontal gradients per row,
#: 64 bits. Small enough that a running SUM over a run's frames costs 72
#: floats per camera; that sum's mean is the thumbnail of the MEAN frame
#: (the downscale is linear), so no full frame is ever retained.
DHASH_W, DHASH_H = 9, 8


def thumbnail_grey(img: np.ndarray) -> np.ndarray:
    """HxWx3 uint8 -> 8x9 float32 grey thumbnail (the dHash input)."""
    from PIL import Image

    grey = Image.fromarray(img).convert("L").resize((DHASH_W, DHASH_H), Image.BILINEAR)
    return np.asarray(grey, dtype=np.float32)


def dhash(thumb: np.ndarray) -> str:
    """Difference hash of an 8x9 grey thumbnail -> 16 hex characters."""
    diff = thumb[:, 1:] > thumb[:, :-1]
    bits = 0
    for b in diff.ravel():
        bits = (bits << 1) | int(b)
    return f"{bits:016x}"


def hamming(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    return (int(a, 16) ^ int(b, 16)).bit_count()


def load_scene_state(path: pathlib.Path = SCENE_STATE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_scene_state(state: dict, path: pathlib.Path = SCENE_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True))


# ---------------------------------------------------------------------------
# the weekly sweep
# ---------------------------------------------------------------------------

def sweep_cameras(con, boroughs: tuple[str, ...] = SWEEP_BOROUGHS,
                  max_cameras: int | None = None) -> list[Camera]:
    """Every camera in `boroughs`, ordered by id for a stable subset.

    `max_cameras` is the OWNER's throttle and defaults to None = all. The
    order is by camera_id, not by anything informative, so a throttled sweep
    is a fixed, reproducible subset rather than "whichever came first".
    """
    _require_registry(con)
    rows = con.execute(
        f"SELECT camera_id, name, lon, lat, image_url, borough FROM {CAMERA_TABLE} "
        f"WHERE borough IN ({', '.join('?' for _ in boroughs)}) ORDER BY camera_id",
        list(boroughs)).fetchall()
    cams = [Camera(*r) for r in rows]
    if max_cameras is not None:
        if max_cameras < 1:
            raise ValueError("--max-cameras must be >= 1")
        cams = cams[:max_cameras]
    return cams


def window_bounds_local(window: str, now_local: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """Today's DOT window as local datetimes. Raises on an unknown window."""
    if window not in DOT_WINDOWS:
        raise ValueError(f"window must be one of {sorted(DOT_WINDOWS)}, got {window!r}")
    a, b = DOT_WINDOWS[window]
    day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day.replace(hour=a), day.replace(hour=b)


def sweep_plan(n_cameras: int, window: str, now_local: dt.datetime,
               interval_s: float = SWEEP_INTERVAL_S) -> dict:
    """Ticks and frames this sweep would take. RUNS NOTHING."""
    start, end = window_bounds_local(window, now_local)
    first = max(start, now_local)
    if first >= end:
        ticks = 0
    else:
        ticks = math.floor((end - first).total_seconds() / interval_s) + 1
    return {"window": window, "start_local": first, "end_local": end, "ticks": ticks,
            "cameras": n_cameras, "frames": ticks * n_cameras, "interval_s": interval_s}


def _new_run_id(window: str, now_local: dt.datetime) -> str:
    return f"{now_local:%Y%m%d}-{window}"


def sweep(cameras: list[Camera], window: str, *, detector=None, fetch_fn=None,
          sleep_fn=time.sleep, clock=None, keep_frames: bool = False,
          dry_run: bool = False, interval_s: float = SWEEP_INTERVAL_S,
          spool_dir: pathlib.Path = SPOOL_DIR,
          scene_state_path: pathlib.Path = SCENE_STATE_PATH,
          concurrency: int = SWEEP_CONCURRENCY, log=None) -> dict:
    """One DOT window, every camera, one frame per tick. Spools; never locks.

    The tick clock is the LOCAL wall clock: the sweep runs from now (or the
    window start, whichever is later) to the window end, so a launchd job
    that fires at 07:00 and a hand-run started at 07:40 both stop at 09:00.
    `clock` returns UTC (naive) like `sample()`'s; local time is derived.

    Per tick: fetch every camera in a thread pool, skip byte-duplicates of
    the camera's previous tick, count, accumulate the 9x8 grey thumbnail,
    drop the bytes. After each tick the rows so far are written to the spool
    so a crash loses one tick, not the window. At the end the scene hash is
    computed from each camera's mean thumbnail, compared with the previous
    run's, stamped onto every row, and the spool file rewritten.

    `dry_run` fetches ONE tick of at most 5 cameras, writes nothing.
    """
    clock = clock or (lambda: dt.datetime.now(dt.UTC).replace(tzinfo=None))
    log = log or (lambda msg: None)
    now_local = clock().replace(tzinfo=dt.UTC).astimezone(LOCAL_TZ).replace(tzinfo=None)
    plan = sweep_plan(len(cameras), window, now_local, interval_s)
    run_id = _new_run_id(window, now_local)
    if dry_run:
        cameras = cameras[:5]
        plan = {**plan, "ticks": min(plan["ticks"], 1), "cameras": len(cameras)}
        plan["frames"] = plan["ticks"] * len(cameras)
    if plan["ticks"] == 0:
        return {"rows": [], "report": {"run_id": run_id, "ticks": 0, "fetched": 0,
                                       "unique": 0, "errors": 0, "note":
                                       f"the {window} window ({plan['end_local']:%H:%M} local) "
                                       f"has already closed today"},
                "plan": plan, "spool": None}

    detector = detector or load_detector()
    session = requests.Session()
    fetch_fn = fetch_fn or (lambda url: _fetch(session, url))
    from loci.vision.person_detector import decode_jpeg

    rows: list[dict] = []
    last_hash: dict[str, str] = {}
    thumb_sum: dict[str, np.ndarray] = {}
    thumb_n: dict[str, int] = {}
    n_fetched = n_dup = n_err = 0
    detect_seconds = 0.0
    spool_path = None if dry_run else spool_dir / f"{run_id}.parquet"

    def one(cam: Camera):
        try:
            return cam, fetch_fn(cam.image_url), None
        except Exception as exc:                        # noqa: BLE001 - any transport error
            return cam, None, exc

    # The window's close, on the same naive-UTC clock the ticks are stamped
    # with. Two things the first live sweep (2026-09-17 pm) taught: a tick is
    # not free (580 fetches + detections took 4-15 min, not the 25 s the
    # budget assumed, when the endpoint timed out), so the sleep is the
    # REMAINDER of the interval, not the whole of it; and the tick count is a
    # plan, not a contract -- the clock is. A sweep that has overrun stops at
    # the close instead of stamping "pm" rows onto the evening.
    end_utc = (plan["end_local"].replace(tzinfo=LOCAL_TZ)
               .astimezone(dt.UTC).replace(tzinfo=None))
    ticks_run = 0
    tick_started = clock()
    for tick in range(plan["ticks"]):
        if tick:
            spent = (clock() - tick_started).total_seconds()
            sleep_fn(max(0.0, interval_s - spent))
            if clock() >= end_utc:
                log(f"window closed at {plan['end_local']:%H:%M} local after "
                    f"{ticks_run} of {plan['ticks']} planned ticks; stopping")
                break
        tick_started = clock()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(one, cameras))
        at = clock()
        ticks_run += 1
        daypart, day_type = _stamp(at)
        tick_rows = 0
        for cam, body, exc in results:
            if exc is not None:
                n_err += 1
                continue
            n_fetched += 1
            h = sha256(body)
            if last_hash.get(cam.camera_id) == h:
                n_dup += 1
                continue
            last_hash[cam.camera_id] = h
            try:
                img = decode_jpeg(body)
            except Exception:                           # noqa: BLE001 - grey card or HTML 200
                n_err += 1
                continue
            det = detector.count(body)
            detect_seconds += det.seconds
            thumb = thumbnail_grey(img)
            thumb_sum[cam.camera_id] = thumb_sum.get(cam.camera_id, 0) + thumb
            thumb_n[cam.camera_id] = thumb_n.get(cam.camera_id, 0) + 1
            rows.append(_row(cam, at, det, detector, h, daypart, day_type, run_id))
            tick_rows += 1
            if keep_frames and not dry_run:
                d = FRAME_DIR / cam.camera_id
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{at:%Y%m%dT%H%M%S}_{h[:12]}.jpg").write_bytes(body)
            del body, img
        log(f"tick {tick + 1}/{plan['ticks']} {at:%H:%M:%S}Z: {tick_rows} frames counted, "
            f"{n_err} errors so far")
        if spool_path is not None and rows:
            spool_write(rows, spool_path)

    # Scene hash per camera, against the previous run.
    state = load_scene_state(scene_state_path)
    changed: dict[str, bool | None] = {}
    hashes: dict[str, str] = {}
    for cam_id, total in thumb_sum.items():
        hsh = dhash(total / thumb_n[cam_id])
        prev = state.get(cam_id, {}).get("scene_hash")
        d = hamming(prev, hsh)
        hashes[cam_id] = hsh
        changed[cam_id] = None if d is None else (d > SCENE_CHANGE_BITS)
        if not dry_run:
            state[cam_id] = {"scene_hash": hsh, "run_id": run_id,
                             "hamming_vs_prev": d, "prev_run_id": state.get(cam_id, {}).get("run_id")}
    for r in rows:
        r["scene_hash"] = hashes.get(r["camera_id"])
        r["scene_changed"] = changed.get(r["camera_id"])
    if not dry_run:
        save_scene_state(state, scene_state_path)
        if spool_path is not None and rows:
            spool_write(rows, spool_path)

    counts = [r["n_persons"] for r in rows]
    report = {
        "run_id": run_id, "window": window, "ticks": plan["ticks"], "ticks_run": ticks_run,
        "cameras": len(cameras), "fetched": n_fetched, "unique": len(rows),
        "duplicates": n_dup, "errors": n_err,
        "cameras_with_frames": len(thumb_n),
        "scene_changed": sum(1 for v in changed.values() if v),
        "scene_first_seen": sum(1 for v in changed.values() if v is None),
        "model": detector.model, "model_version": detector.version,
        "seconds_per_frame": (detect_seconds / len(rows)) if rows else 0.0,
        "mean_persons": (sum(counts) / len(counts)) if counts else 0.0,
        "keep_frames": bool(keep_frames and not dry_run), "dry_run": dry_run,
    }
    return {"rows": rows, "report": report, "plan": plan, "spool": spool_path}


# ---------------------------------------------------------------------------
# the spool -- rows wait here for the warehouse lock
# ---------------------------------------------------------------------------

def spool_write(rows: list[dict], path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=list(ROW_COLUMNS))
    # Nullable ints must not silently become floats on the way through parquet.
    for c in EXTRA_CLASS_COLUMNS:
        df[c] = df[c].astype("Int64")
    df["scene_changed"] = df["scene_changed"].astype("boolean")
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def flush(con, spool_dir: pathlib.Path = SPOOL_DIR) -> dict:
    """Move every spooled run into analysis.sidewalk_count. Returns counts.

    Files are read with DuckDB's parquet reader and inserted BY NAME with ON
    CONFLICT DO NOTHING, so a spool flushed twice adds nothing and a sweep's
    per-tick rewrites are harmless. A flushed file moves to spool/done/ rather
    than being deleted: it is the only copy of a run whose insert was later
    found wrong, and it is ~100 KB.
    """
    files = sorted(spool_dir.glob("*.parquet")) if spool_dir.exists() else []
    out = {"files": len(files), "rows_read": 0, "rows_written": 0, "runs": []}
    if not files:
        return out
    done = spool_dir / "done"
    done.mkdir(parents=True, exist_ok=True)
    cols = ", ".join(_present_columns(con))
    for f in files:
        n_read = con.execute("SELECT count(*) FROM read_parquet(?)", [str(f)]).fetchone()[0]
        before = con.execute(f"SELECT count(*) FROM {OUT_TABLE}").fetchone()[0]
        con.execute(
            f"INSERT INTO {OUT_TABLE} ({cols}) SELECT {cols} FROM read_parquet(?) "
            f"ON CONFLICT DO NOTHING", [str(f)])
        after = con.execute(f"SELECT count(*) FROM {OUT_TABLE}").fetchone()[0]
        out["rows_read"] += int(n_read)
        out["rows_written"] += int(after - before)
        out["runs"].append((f.stem, int(n_read), int(after - before)))
        shutil.move(str(f), str(done / f.name))
    return out


# ---------------------------------------------------------------------------
# launchd -- the weekly schedule as three plists under data/launchd/
# ---------------------------------------------------------------------------

def launchd_labels() -> dict[str, str]:
    return {w: f"{LAUNCHD_LABEL}-{w}" for w in DOT_WINDOWS}


def launchd_plist(window: str, uv_path: str, repo: pathlib.Path = REPO_ROOT,
                  weekdays: tuple[int, ...] = SWEEP_WEEKDAYS,
                  max_cameras: int | None = None) -> bytes:
    """The plist for one window: fires at the window's opening hour on each
    weekday in `weekdays`, runs `loci sidewalk-count sweep --window W`.

    The sweep itself stops at the window's closing hour, so the job needs no
    duration; a machine asleep at 07:00 gets the job on wake (launchd runs a
    missed StartCalendarInterval once) and the sweep then covers whatever is
    left of the window -- which is the honest behaviour, and the report
    shows the shorter run as fewer frames.
    """
    a, _ = DOT_WINDOWS[window]
    args = [uv_path, "run", "loci", "sidewalk-count", "sweep", "--window", window]
    if max_cameras is not None:
        args += ["--max-cameras", str(max_cameras)]
    logs = repo / "data" / "sidewalk" / "logs"
    plist = {
        "Label": launchd_labels()[window],
        "ProgramArguments": args,
        "WorkingDirectory": str(repo),
        "StartCalendarInterval": [{"Weekday": wd, "Hour": a, "Minute": 0} for wd in weekdays],
        "StandardOutPath": str(logs / f"sweep-{window}.log"),
        "StandardErrorPath": str(logs / f"sweep-{window}.err"),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:"
                    + str(pathlib.Path.home() / ".local" / "bin"),
        },
        "ProcessType": "Background",
        "LowPriorityIO": True,
    }
    return plistlib.dumps(plist, sort_keys=False)


def write_launchd_plists(out_dir: pathlib.Path = LAUNCHD_DIR, uv_path: str | None = None,
                         max_cameras: int | None = None) -> list[pathlib.Path]:
    """Render the three plists to data/launchd/. Writes nothing outside it."""
    uv_path = uv_path or shutil.which("uv") or "uv"
    out_dir.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "data" / "sidewalk" / "logs").mkdir(parents=True, exist_ok=True)
    paths = []
    for w, label in launchd_labels().items():
        p = out_dir / f"{label}.plist"
        p.write_bytes(launchd_plist(w, uv_path, max_cameras=max_cameras))
        paths.append(p)
    return paths


def _launch_agents_dir() -> pathlib.Path:
    return pathlib.Path.home() / "Library" / "LaunchAgents"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def schedule_install(max_cameras: int | None = None) -> list[str]:
    """Copy the plists into ~/Library/LaunchAgents and bootstrap them.

    The ONLY function in this module that writes outside the repo. It is
    reached solely through `loci sidewalk-count schedule --install`, run by
    the owner; nothing calls it on import or from a test.
    """
    paths = write_launchd_plists(max_cameras=max_cameras)
    agents = _launch_agents_dir()
    agents.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    notes = []
    for p in paths:
        dest = agents / p.name
        shutil.copyfile(p, dest)
        _launchctl("bootout", domain, str(dest))          # idempotent re-install
        r = _launchctl("bootstrap", domain, str(dest))
        notes.append(f"{p.stem}: {'installed' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}")
    return notes


def schedule_uninstall() -> list[str]:
    agents = _launch_agents_dir()
    domain = f"gui/{os.getuid()}"
    notes = []
    for label in launchd_labels().values():
        dest = agents / f"{label}.plist"
        if dest.exists():
            _launchctl("bootout", domain, str(dest))
            dest.unlink()
            notes.append(f"{label}: removed")
        else:
            notes.append(f"{label}: not installed")
    return notes


def schedule_status() -> list[dict]:
    r = _launchctl("list")
    loaded = {line.split("\t")[-1] for line in r.stdout.splitlines()}
    agents = _launch_agents_dir()
    out = []
    for w, label in launchd_labels().items():
        a, b = DOT_WINDOWS[w]
        out.append({"window": w, "label": label, "hours": f"{a:02d}-{b:02d}",
                    "plist_in_repo": (LAUNCHD_DIR / f"{label}.plist").exists(),
                    "installed": (agents / f"{label}.plist").exists(),
                    "loaded": label in loaded})
    return out


# ---------------------------------------------------------------------------
# report -- daypart profiles against each camera's OWN history
# ---------------------------------------------------------------------------

def _history_start_sql() -> str:
    """Per camera: the FIRST frame of its most recent re-aimed run, or none.

    A camera's "own history" starts at its last re-aim -- the whole of that
    run, since the new view was in place for all of it. Rows before it are a
    different view and are excluded from the baseline rather than averaged
    into it. `run_id` and `scene_changed` are written together by the sweep,
    so a changed row always has a run to anchor on.
    """
    return (f"SELECT s.camera_id, min(s.sampled_at) AS history_from FROM {OUT_TABLE} s "
            f"JOIN (SELECT camera_id, max(run_id) AS run_id FROM {OUT_TABLE} "
            f"      WHERE scene_changed GROUP BY camera_id) c USING (camera_id, run_id) "
            f"GROUP BY s.camera_id")


def report(con, camera_id: str | None = None, nta: str | None = None,
           nta_radius_m: float = 250.0) -> pd.DataFrame:
    """Per camera x day_type x daypart: the latest run vs the camera's history.

    `latest` is the most recent run_id (or, for pre-053 rows, the most recent
    local date) the camera has in that cell; `history` is every earlier row
    since the camera's last scene change. `ratio` is latest/history mean, and
    is NULL when the history has fewer than HISTORY_MIN_FRAMES frames -- a
    ratio against three frames is a coin, not a baseline. The four vehicle
    classes ride along as means, unvalidated.

    `nta` selects cameras within `nta_radius_m` straight-line metres of any
    analysis.address in that NTA (the registry carries no NTA; the pole's
    position does). Comparisons are WITHIN camera only -- a camera is not
    compared with another, per the module docstring.
    """
    where, params = [], []
    if camera_id:
        where.append("s.camera_id = ?")
        params.append(camera_id)
    cam_filter = ""
    if nta:
        if not _table_exists(con, "analysis.address"):
            raise CameraRegistryMissing("analysis.address is needed for --nta")
        dist = METRES_SQL.format(a="ST_Point(c.lon, c.lat)", b="ST_Point(a.lon, a.lat)")
        cam_filter = (f"AND s.camera_id IN (SELECT DISTINCT c.camera_id FROM {CAMERA_TABLE} c "
                      f"JOIN analysis.address a ON a.nta_code = ? AND {dist} <= ?)")
        params += [nta, nta_radius_m]
    w = ("WHERE " + " AND ".join(where)) if where else ""
    name = "c.name" if _table_exists(con, CAMERA_TABLE) else "s.camera_id"
    join = (f"LEFT JOIN {CAMERA_TABLE} c USING (camera_id)"
            if _table_exists(con, CAMERA_TABLE) else "")
    q = f"""
    WITH hist AS ({_history_start_sql()}),
    base AS (
        SELECT s.*, {name} AS camera,
               coalesce(s.run_id, strftime(s.sampled_at AT TIME ZONE 'UTC' AT TIME ZONE
                        'America/New_York', '%Y%m%d')) AS run_key
        FROM {OUT_TABLE} s {join}
        LEFT JOIN hist h USING (camera_id)
        {w} {('AND' if w else 'WHERE')} (h.history_from IS NULL OR s.sampled_at >= h.history_from)
        {cam_filter}
    ),
    latest AS (
        SELECT camera_id, day_type, daypart, max(run_key) AS latest_run
        FROM base GROUP BY 1, 2, 3
    )
    SELECT b.camera_id, any_value(b.camera) AS camera, b.day_type, b.daypart,
           any_value(l.latest_run)                                    AS latest_run,
           count(*) FILTER (WHERE b.run_key = l.latest_run)           AS latest_frames,
           avg(b.n_persons) FILTER (WHERE b.run_key = l.latest_run)   AS latest_persons,
           count(*) FILTER (WHERE b.run_key < l.latest_run)           AS history_frames,
           avg(b.n_persons) FILTER (WHERE b.run_key < l.latest_run)   AS history_persons,
           count(DISTINCT b.run_key) FILTER (WHERE b.run_key < l.latest_run) AS history_runs,
           avg(b.n_car) FILTER (WHERE b.run_key = l.latest_run)       AS latest_car,
           avg(b.n_truck) FILTER (WHERE b.run_key = l.latest_run)     AS latest_truck,
           avg(b.n_bus) FILTER (WHERE b.run_key = l.latest_run)       AS latest_bus,
           avg(b.n_bicycle) FILTER (WHERE b.run_key = l.latest_run)   AS latest_bicycle,
           bool_or(coalesce(b.scene_changed, FALSE))                  AS scene_changed_in_history
    FROM base b JOIN latest l USING (camera_id, day_type, daypart)
    GROUP BY 1, 3, 4
    ORDER BY b.camera_id,
             array_position({list(DAY_TYPES)!r}::VARCHAR[], b.day_type),
             array_position({list(DAYPART_NAMES)!r}::VARCHAR[], b.daypart)
    """
    df = con.execute(q, params).fetchdf()
    if df.empty:
        return df
    ok = df["history_frames"] >= HISTORY_MIN_FRAMES
    df["ratio"] = np.where(ok & (df["history_persons"] > 0),
                           df["latest_persons"] / df["history_persons"].where(df["history_persons"] > 0),
                           np.nan)
    return df


#: Below this many history frames in a cell, `report` prints no ratio.
HISTORY_MIN_FRAMES = 20
