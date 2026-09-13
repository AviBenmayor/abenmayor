"""The camera sampler: the duplicate skip, the budget, the stamp, the join.

Four of these five things are the load-bearing ones, and none of them is about
computer vision:

1. THE DUPLICATE SKIP. The feed serves the last decoded still, so a fetch
   loop gets the same bytes back repeatedly. If duplicates reached the table
   the mean would be an average over how often the camera happened to be slow,
   not over the sidewalk.
2. THE BUDGET. `MAX_FRAMES_PER_RUN` must refuse before the first request AND
   stop the loop, because a plan can only be wrong about the future.
3. THE DAYPART STAMP. `sampled_at` is UTC and the daypart is a question about
   the New York clock; getting that backwards would put the evening rush in
   `early` and nothing downstream would notice.
4. THE VALIDATE JOIN. It has to survive an empty intersection (no co-located
   camera sampled yet) by reporting N, not by raising or by inventing a rho.

The detector itself is exercised two ways: mocked, so the pipeline is testable
on any machine, and — when the exported ONNX is present — for real against a
synthetic frame that contains no people, which is the one ground truth a
synthetic image can honestly carry.
"""
from __future__ import annotations

import datetime as dt
import io

import numpy as np
import pytest

from loci.model import sidewalk_count as sc
from loci.vision import person_detector as pd_mod


# --------------------------------------------------------------- helpers

def _jpeg(seed: int, size=(240, 352)) -> bytes:
    """A distinct, decodable JPEG per seed."""
    from PIL import Image

    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, size=(size[0], size[1], 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class FakeDetector:
    model = "fake"
    version = "v0"
    quality = "test"

    def __init__(self, counts=None):
        self.counts = list(counts or [])
        self.seen: list[bytes] = []

    def count(self, data: bytes) -> pd_mod.DetectionResult:
        self.seen.append(data)
        n = self.counts.pop(0) if self.counts else 1
        return pd_mod.DetectionResult(n_persons=n, n_persons_conf50=max(0, n - 1),
                                      scores=tuple([0.9] * n), width=352, height=240,
                                      seconds=0.001)


CAM = sc.Camera(camera_id="cam-1", name="Test Ave @ 1 St", lon=-73.95, lat=40.71,
                image_url="http://example.invalid/cam-1/image", borough="Brooklyn")


# ------------------------------------------------ 1. the duplicate skip

def test_identical_bytes_are_fetched_but_never_counted_twice():
    """Six fetches, three distinct images, each served twice: three rows.

    The detector must also see exactly three frames — skipping after detection
    would be correct in the table and wrong in the CPU budget, and the whole
    point of the hash is that it is cheap."""
    frames = [_jpeg(1), _jpeg(1), _jpeg(2), _jpeg(2), _jpeg(3), _jpeg(3)]
    it = iter(frames)
    det = FakeDetector()
    out = sc.sample(CAM, minutes=1, interval_s=12, detector=det,
                    fetch_fn=lambda url: next(it), sleep_fn=lambda s: None)
    assert out["report"]["fetched"] == 6
    assert out["report"]["unique"] == 3
    assert out["report"]["duplicates"] == 3
    assert out["report"]["duplicate_rate"] == pytest.approx(0.5)
    assert len(det.seen) == 3, "the detector ran on a frame the hash already knew"
    assert len({r["frame_hash"] for r in out["rows"]}) == 3


def test_a_frozen_camera_yields_one_row_and_a_visible_duplicate_rate():
    """A camera stuck on one still must not read as sixty observations of a
    busy corner. One row, and a 98% duplicate rate saying why."""
    same = _jpeg(7)
    out = sc.sample(CAM, minutes=2, interval_s=2, detector=FakeDetector([5]),
                    fetch_fn=lambda url: same, sleep_fn=lambda s: None)
    assert out["report"]["unique"] == 1
    assert out["report"]["duplicate_rate"] > 0.9


# ------------------------------------------------------- 2. the budget

def test_plan_refuses_a_run_over_budget_before_any_request_is_made():
    with pytest.raises(sc.BudgetExceeded) as exc:
        sc.plan_run(CAM, minutes=600, interval_s=10)       # 3601 frames
    assert "MAX_FRAMES_PER_RUN" in str(exc.value)
    assert str(sc.MAX_FRAMES_PER_RUN) in str(exc.value)


def test_plan_refuses_an_interval_under_the_politeness_floor():
    with pytest.raises(sc.BudgetExceeded):
        sc.plan_run(CAM, minutes=1, interval_s=0.5)


def test_the_loop_stops_at_the_budget_even_when_the_plan_lies(monkeypatch):
    """The belt to the plan's braces.

    `plan_run` guards the future; the loop counter guards the present. Feed
    `sample` a plan that claims 999 frames and the loop must still stop at the
    budget, counting FETCHES — duplicates included, because the endpoint sees
    fetches, not unique frames."""
    n = {"i": 0}

    def fetch(url):
        n["i"] += 1
        return _jpeg(n["i"] % 2)          # alternates: half are duplicates

    monkeypatch.setattr(sc, "plan_run", lambda *a, **k: sc.SamplePlan(
        camera=CAM, minutes=999, interval_s=2, frames=999, est_seconds=0))
    out = sc.sample(CAM, minutes=999, interval_s=2, detector=FakeDetector(),
                    fetch_fn=fetch, sleep_fn=lambda s: None, max_frames=5)
    assert n["i"] == 5
    assert out["report"]["fetched"] == 5
    assert out["report"]["unique"] == 2, "the 5 fetches were 2 distinct frames"


def test_dry_run_fetches_exactly_one_frame_and_returns_no_rows_to_write():
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        return _jpeg(calls["n"])

    out = sc.sample(CAM, minutes=60, interval_s=10, detector=FakeDetector(),
                    fetch_fn=fetch, sleep_fn=lambda s: None, dry_run=True)
    assert calls["n"] == 1
    assert out["report"]["dry_run"] is True
    assert out["plan"].frames == 361, "the PLAN still describes the full run"


def test_consecutive_failures_raise_rather_than_writing_a_run_full_of_holes():
    def fetch(url):
        raise ConnectionError("nope")

    with pytest.raises(RuntimeError, match="in a row"):
        sc.sample(CAM, minutes=5, interval_s=5, detector=FakeDetector(),
                  fetch_fn=fetch, sleep_fn=lambda s: None)


def test_a_transient_failure_does_not_abort_the_run():
    seq = [ConnectionError("blip"), _jpeg(1), _jpeg(2)]

    def fetch(url):
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    out = sc.sample(CAM, minutes=1, interval_s=30, detector=FakeDetector(),
                    fetch_fn=fetch, sleep_fn=lambda s: None)
    assert out["report"]["errors"] == 1
    assert out["report"]["unique"] == 2


# ------------------------------------------------- 3. the daypart stamp

@pytest.mark.parametrize("utc, daypart, day_type", [
    # 2026-09-14 is a Monday. EDT = UTC-4.
    (dt.datetime(2026, 9, 14, 12, 0), "am_peak", "weekday"),   # 08:00 local
    (dt.datetime(2026, 9, 14, 22, 30), "pm_peak", "weekday"),  # 18:30 local
    (dt.datetime(2026, 9, 15, 2, 0), "evening", "weekday"),    # Mon 22:00 local
    (dt.datetime(2026, 9, 14, 7, 0), "early", "weekday"),      # 03:00 local
    (dt.datetime(2026, 9, 13, 18, 0), "midday", "sunday"),     # Sun 14:00 local
    (dt.datetime(2026, 9, 12, 18, 0), "midday", "saturday"),   # Sat 14:00 local
])
def test_the_stamp_is_the_new_york_clock_not_utc(utc, daypart, day_type):
    assert sc._stamp(utc) == (daypart, day_type)


def test_a_utc_instant_can_belong_to_the_previous_local_day():
    """00:30 UTC on a Monday is 20:30 Sunday in New York. Stamping it 'weekday'
    would put a Sunday evening into the weekday profile."""
    assert sc._stamp(dt.datetime(2026, 9, 14, 0, 30)) == ("evening", "sunday")


def test_the_stamp_uses_the_same_five_boundaries_as_the_transit_profile():
    """Imported, not redefined. If the D76 edges move, these move with them."""
    from loci.sources.cities.nyc.mta_ridership import DAYPARTS

    for name, a, b in DAYPARTS:
        for hour in range(a, b):
            # 04:00 UTC is midnight local in EDT; add `hour` to walk the day.
            got, _ = sc._stamp(dt.datetime(2026, 9, 14, 4) + dt.timedelta(hours=hour))
            assert got == name


# ------------------------------------------------- 4. the validate join

def _db_with_staging(tmp_path):
    """An in-memory warehouse holding the two staging contracts + 024."""
    import duckdb

    from loci import db as locidb

    con = duckdb.connect(":memory:")
    con.execute((locidb.SQL_DIR / "001_bootstrap.sql").read_text())
    con.execute("CREATE SCHEMA IF NOT EXISTS staging")
    con.execute("""CREATE TABLE staging.dot_camera(
        camera_id VARCHAR, name VARCHAR, lon DOUBLE, lat DOUBLE,
        image_url VARCHAR, is_online BOOLEAN, area VARCHAR, borough VARCHAR,
        fetched_at TIMESTAMP)""")
    # Column names and types mirror sql/022_dot.sql, the concurrent DOT
    # registry migration: point_id is an INTEGER `loc`, not a string.
    con.execute("""CREATE TABLE staging.dot_pedestrian_count(
        point_id INTEGER, round VARCHAR, period VARCHAR, count INTEGER,
        lon DOUBLE, lat DOUBLE, borough VARCHAR, is_bridge BOOLEAN)""")
    con.execute((locidb.SQL_DIR / "024_sidewalk_count.sql").read_text())
    # Two cameras 0 m and ~400 m from one count point. 0.0047 deg lon at 40.7N
    # is ~400 m; the second must fall OUTSIDE the 60 m radius.
    con.executemany(
        "INSERT INTO staging.dot_camera VALUES (?,?,?,?,?,?,?,?,?)",
        [["near", "On The Point", -73.9500, 40.7100, "http://x/near", True,
          "Brooklyn", "Brooklyn", dt.datetime(2026, 9, 13)],
         ["far", "Four Blocks Away", -73.9453, 40.7100, "http://x/far", True,
          "Brooklyn", "Brooklyn", dt.datetime(2026, 9, 13)]])
    con.executemany(
        "INSERT INTO staging.dot_pedestrian_count VALUES (?,?,?,?,?,?,?,?)",
        [[1, "2026-05", "am", 1200, -73.9500, 40.7100, "Brooklyn", False],
         [1, "2026-05", "md", 900, -73.9500, 40.7100, "Brooklyn", False],
         [1, "2026-05", "pm", 1500, -73.9500, 40.7100, "Brooklyn", False],
         [1, "2025-05", "am", 1100, -73.9500, 40.7100, "Brooklyn", False],
         # A BRIDGE midpoint sitting right on top of the near camera. DOT's
         # loc 101-114 are East/Harlem River midspans; a camera there is
         # pointed at a roadway, not at a sidewalk the screen looks at.
         [101, "2026-05", "am", 9999, -73.9500, 40.7100, "Brooklyn", True]])
    return con


def test_validate_reports_n_and_no_rho_when_nothing_has_been_sampled(tmp_path):
    """The honest empty case: the join is right, the intersection is empty."""
    con = _db_with_staging(tmp_path)
    pairs, rep = sc.validate(con)
    assert rep["cameras_sampled"] == 0
    assert rep["n"] == 0
    assert rep["spearman_rho"] is None
    assert "empty" in rep["note"]
    assert len(pairs) == 0


def test_validate_pairs_only_cameras_inside_the_radius(tmp_path):
    con = _db_with_staging(tmp_path)
    pairs = sc._camera_point_pairs(con)
    assert set(pairs["camera_id"]) == {"near"}, "the 400 m camera must not pair"
    assert set(pairs["period"]) == {"am", "md", "pm"}
    assert set(pairs["point_id"]) == {1}, "the bridge midpoint must not pair"
    assert set(pairs["round"]) == {"2026-05"}, "latest round only, not 2025-05 too"
    assert pairs["dist_m"].max() < sc.VALIDATE_RADIUS_M


def test_validate_matches_sampled_windows_to_dot_windows_on_local_time(tmp_path):
    """Frames at 08:00, 13:00 and 17:00 local land in am / md / pm; a frame at
    22:00 local lands in none of them and must not inflate any window."""
    con = _db_with_staging(tmp_path)
    rows = []
    # 2026-09-14 is a Monday; EDT = UTC-4.
    for hour_utc, n, tag in [(12, 3, "am"), (17, 1, "md"), (21, 9, "pm"), (2, 7, "night")]:
        for k in range(2):
            at = dt.datetime(2026, 9, 14, hour_utc, k * 5)
            daypart, day_type = sc._stamp(at)
            rows.append({"camera_id": "near", "sampled_at": at, "n_persons": n,
                         "n_persons_conf50": n, "model": "fake", "model_version": "v0",
                         "frame_hash": f"{tag}{k}", "daypart": daypart,
                         "day_type": day_type})
    assert sc.write_rows(con, rows) == 8

    means = sc.camera_window_means(con)
    got = {r.period: r.mean_persons for r in means.itertuples()}
    assert got == pytest.approx({"am": 3.0, "md": 1.0, "pm": 9.0})
    assert means["frames"].sum() == 6, "the 22:00 local frames belong to no window"

    merged, rep = sc.validate(con)
    assert rep["n"] == 3 and rep["cameras_compared"] == 1
    assert set(merged["point_id"]) == {1}
    # Per COUNTED HOUR: am 1200/2=600, md 900/2=450, pm 1500/3=500. The camera
    # says am 3, md 1, pm 9. On the RAW counts the ranks agree exactly; on the
    # per-hour rate they do not, because pm's window is an hour longer. The two
    # rhos must differ here — that is the whole reason both are reported.
    assert rep["spearman_rho_raw_count"] == pytest.approx(1.0)
    assert rep["spearman_rho"] == pytest.approx(0.5)
    assert set(merged["window_hours"]) == {2.0, 3.0}


def test_a_weekend_only_sample_reports_n_zero_instead_of_raising(tmp_path):
    """DOT counts WEEKDAYS. Sample a camera all Sunday afternoon and the
    intersection with the yardstick is empty — which must read as N = 0 with a
    reason, not as a KeyError. (This is not hypothetical: the first real
    three-camera sample was taken on a Sunday.)"""
    con = _db_with_staging(tmp_path)
    rows = [{"camera_id": "near",
             # 2026-09-13 is a SUNDAY; 17:00 UTC is 13:00 local, inside DOT's md.
             "sampled_at": dt.datetime(2026, 9, 13, 17, m),
             "n_persons": 2, "n_persons_conf50": 1, "model": "fake",
             "model_version": "v0", "frame_hash": f"s{m}", "daypart": "midday",
             "day_type": "sunday"} for m in range(4)]
    sc.write_rows(con, rows)

    assert sc.camera_window_means(con).empty
    assert list(sc.camera_window_means(con).columns)[:2] == ["camera_id", "period"]

    pairs, rep = sc.validate(con)
    assert rep["cameras_sampled"] == 1
    assert rep["n"] == 0 and rep["spearman_rho"] is None
    assert "weekday" in rep["note"].lower()


def test_rewriting_the_same_frames_adds_nothing(tmp_path):
    """The PK is (camera, frame, model, version). Two overlapping runs must not
    double the mean."""
    con = _db_with_staging(tmp_path)
    rows = [{"camera_id": "near", "sampled_at": dt.datetime(2026, 9, 14, 12),
             "n_persons": 4, "n_persons_conf50": 2, "model": "fake",
             "model_version": "v0", "frame_hash": "abc", "daypart": "am_peak",
             "day_type": "weekday"}]
    assert sc.write_rows(con, rows) == 1
    assert sc.write_rows(con, rows) == 0
    assert con.execute("SELECT count(*) FROM analysis.sidewalk_count").fetchone()[0] == 1


def test_a_second_model_is_a_new_row_not_an_overwrite(tmp_path):
    """Re-scoring the archive with a better detector must be additive, and the
    two must never pool silently."""
    con = _db_with_staging(tmp_path)
    base = {"camera_id": "near", "sampled_at": dt.datetime(2026, 9, 14, 12),
            "n_persons": 4, "n_persons_conf50": 2, "frame_hash": "abc",
            "daypart": "am_peak", "day_type": "weekday"}
    sc.write_rows(con, [{**base, "model": "fake", "model_version": "v0"}])
    sc.write_rows(con, [{**base, "model": "yolo11n", "model_version": "3770b4e"}])
    assert con.execute("SELECT count(*) FROM analysis.sidewalk_count").fetchone()[0] == 2


def test_stats_groups_by_camera_day_type_and_daypart(tmp_path):
    con = _db_with_staging(tmp_path)
    rows = [{"camera_id": "near", "sampled_at": dt.datetime(2026, 9, 14, 12, m),
             "n_persons": n, "n_persons_conf50": 0, "model": "fake",
             "model_version": "v0", "frame_hash": f"h{m}", "daypart": "am_peak",
             "day_type": "weekday"} for m, n in enumerate([0, 0, 0, 11])]
    sc.write_rows(con, rows)
    s = sc.stats(con)
    assert len(s) == 1
    r = s.iloc[0]
    assert r["frames"] == 4 and r["max_persons"] == 11
    # The median is here precisely because these two disagree.
    assert r["mean_persons"] == pytest.approx(2.75)
    assert r["p50_persons"] == pytest.approx(0.0)


# --------------------------------------------------------- 5. the schedule

def test_schedule_emits_every_day_type_x_daypart_and_runs_nothing():
    plan = sc.schedule_plan(CAM, days=14, interval_s=10, minutes_per_daypart=10)
    assert len(plan) == 15                               # 3 day types x 5 dayparts
    assert set(plan["day_type"]) == set(sc.DAY_TYPES)
    assert set(plan["daypart"]) == set(sc.DAYPART_NAMES)
    # Every block is inside the budget, which is the point of emitting blocks.
    assert plan["frames_per_block"].max() <= sc.MAX_FRAMES_PER_RUN
    # 14 days is 10 weekdays, 2 Saturdays, 2 Sundays.
    wk = plan[plan.day_type == "weekday"]["blocks"].unique()
    assert list(wk) == [10]
    assert list(plan[plan.day_type == "sunday"]["blocks"].unique()) == [2]
    # Launch at the MIDPOINT of the daypart, not its edge.
    assert plan[plan.daypart == "am_peak"]["launch_local"].iloc[0] == "08:00"


# --------------------------------------------------------- 6. the detector

def test_nms_collapses_two_boxes_on_the_same_person():
    boxes = np.array([[0, 0, 10, 20], [1, 1, 11, 21], [100, 100, 110, 120]],
                     dtype=float)
    scores = np.array([0.9, 0.8, 0.7])
    keep = pd_mod._nms(boxes, scores)
    assert len(keep) == 2, "overlapping anchors on one person are one person"
    assert keep[0] == 0, "the higher-scoring box survives"


def test_nms_on_no_boxes_is_empty_not_an_error():
    assert len(pd_mod._nms(np.empty((0, 4)), np.empty(0))) == 0


def test_letterbox_preserves_aspect_ratio_and_pads():
    img = np.zeros((240, 352, 3), dtype=np.uint8)
    out = pd_mod._letterbox(img, size=640)
    assert out.shape == (640, 640, 3)
    # 352x240 scaled by 640/352 = 436 rows of image, the rest pad grey.
    assert (out[0] == 114).all(), "the top band is pad, not stretched image"


@pytest.mark.skipif(not pd_mod.ONNX_PATH.exists(),
                    reason="the exported ONNX is not on this machine")
def test_the_real_detector_finds_nobody_in_a_frame_with_nobody_in_it():
    """The one ground truth a synthetic image can honestly carry.

    A flat road-and-sky frame contains zero people, and a detector that
    hallucinates one in it would put a floor under every quiet corner in the
    study. This is deliberately NOT a 'finds N people' test: a synthetic
    person is not a person, and a real CC0 crowd photo would pin the count to
    whatever this particular checkpoint happens to say rather than to truth.
    """
    from PIL import Image

    arr = np.zeros((240, 352, 3), dtype=np.uint8)
    arr[:120] = (150, 170, 200)          # sky
    arr[120:] = (90, 90, 95)             # asphalt
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=90)

    det = pd_mod.load_detector()
    r = det.count(buf.getvalue())
    assert r.n_persons == 0
    assert r.n_persons_conf50 == 0
    assert (r.width, r.height) == (352, 240)


@pytest.mark.skipif(not pd_mod.ONNX_PATH.exists(),
                    reason="the exported ONNX is not on this machine")
def test_the_weights_match_the_recorded_digest():
    """The graph the counts came from is the graph that is recorded."""
    assert pd_mod.sha256(pd_mod.ensure_model().read_bytes()) == pd_mod.ONNX_SHA256


@pytest.mark.skipif(not pd_mod.ONNX_PATH.exists(),
                    reason="the exported ONNX is not on this machine")
def test_the_conf50_count_can_never_exceed_the_conf25_count():
    det = pd_mod.load_detector()
    r = det.count(_jpeg(11))
    assert r.n_persons_conf50 <= r.n_persons
    assert len(r.scores) == r.n_persons
