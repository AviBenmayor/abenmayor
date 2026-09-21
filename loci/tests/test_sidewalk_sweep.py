"""The weekly sweep: the privacy rule, the scene hash, the spool, the plists.

Nothing here touches the network or the warehouse file. The load-bearing
claims:

1. NO PIXELS SURVIVE A TICK. `sweep()` without --keep-frames writes no file
   under data/frames and its rows are integers plus two hashes.
2. THE SCENE HASH FLAGS A RE-AIM. The same scene twice is `scene_changed`
   False; a different scene on the second run is True; the first run ever is
   None (there is nothing to compare with), never False.
3. THE SPOOL ROUND-TRIPS AND FLUSHES IDEMPOTENTLY. Flushing the same file
   twice adds nothing; the extra classes come back as integers, not floats.
4. THE OWNER'S THROTTLE. `--max-cameras` is a fixed, ordered subset; the
   default is everything.
5. THE PLISTS fire on Tue + Thu at the window's opening hour and never run
   anything on render.
6. THE REPORT compares a camera only with itself, and starts its history at
   the last scene change.
"""
from __future__ import annotations

import datetime as dt
import io
import plistlib

import numpy as np
import pytest

from loci.model import sidewalk_count as sc
from loci.sources.cities.nyc.mta_ridership import DOT_WINDOWS
from loci.vision import person_detector as pd_mod


def _jpeg(arr: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _scene(seed: int, size=(240, 352)) -> np.ndarray:
    """A smooth, distinctive 'view': blocks of colour, not white noise, so
    the dHash of two different scenes actually differs."""
    rng = np.random.default_rng(seed)
    arr = np.zeros((size[0], size[1], 3), dtype=np.uint8)
    for _ in range(12):
        y, x = rng.integers(0, size[0]), rng.integers(0, size[1])
        h, w = rng.integers(20, 120), rng.integers(20, 160)
        arr[y:y + h, x:x + w] = rng.integers(0, 255, 3)
    return arr


class FakeDetector:
    model = "fake"
    version = "v0"
    quality = "test"

    def count(self, data: bytes) -> pd_mod.DetectionResult:
        return pd_mod.DetectionResult(n_persons=2, n_persons_conf50=1, scores=(0.9, 0.3),
                                      width=352, height=240, seconds=0.001,
                                      extra={"car": 3, "truck": 0, "bus": 1, "bicycle": 0})


def _cams(n: int) -> list[sc.Camera]:
    return [sc.Camera(camera_id=f"cam-{i:02d}", name=f"Ave @ {i} St", lon=-73.95,
                      lat=40.71, image_url=f"http://example.invalid/{i}", borough="MN")
            for i in range(n)]


#: 2026-09-17 is a Thursday; 12:30 local is 16:30 UTC, inside the md window.
MD_CLOCK = dt.datetime(2026, 9, 17, 16, 30)


def _run(tmp_path, cams, scenes: dict[str, np.ndarray], clock=MD_CLOCK, **kw):
    """Each fetch returns the camera's scene with a fresh speck of noise, the
    way a live feed re-encodes the same view every few seconds: the bytes
    differ (so the duplicate skip lets it through) while the dHash does not."""
    by_url = {c.image_url: scenes[c.camera_id] for c in cams}
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        arr = by_url[url].copy()
        arr[calls["n"] % 240, calls["n"] % 352] ^= 0xFF
        return _jpeg(arr)

    return sc.sweep(cams, "md", detector=FakeDetector(), fetch_fn=fetch,
                    sleep_fn=lambda s: None, clock=lambda: clock, interval_s=600.0,
                    spool_dir=tmp_path / "spool", scene_state_path=tmp_path / "scene.json",
                    concurrency=2, **kw)


# ---------------------------------------------------------- 1. privacy

def test_a_sweep_keeps_no_pixels_and_writes_only_aggregate_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "FRAME_DIR", tmp_path / "frames")
    cams = _cams(3)
    out = _run(tmp_path, cams, {c.camera_id: _scene(i) for i, c in enumerate(cams)})
    assert not (tmp_path / "frames").exists()
    assert out["report"]["unique"] == 3 * out["plan"]["ticks"]
    for r in out["rows"]:
        assert set(r) == set(sc.ROW_COLUMNS)
        assert isinstance(r["n_persons"], int) and isinstance(r["n_car"], int)
        assert len(r["frame_hash"]) == 64 and len(r["scene_hash"]) == 16


def test_keep_frames_is_the_only_path_that_writes_a_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "FRAME_DIR", tmp_path / "frames")
    cams = _cams(1)
    _run(tmp_path, cams, {"cam-00": _scene(1)}, keep_frames=True)
    assert list((tmp_path / "frames" / "cam-00").glob("*.jpg"))


# ------------------------------------------------------- 2. scene hash

def test_the_first_run_ever_has_no_verdict_not_a_false(tmp_path):
    cams = _cams(1)
    out = _run(tmp_path, cams, {"cam-00": _scene(1)})
    assert all(r["scene_changed"] is None for r in out["rows"])
    assert out["report"]["scene_first_seen"] == 1


def test_the_same_view_twice_is_not_a_change_and_a_new_view_is(tmp_path):
    cams = _cams(1)
    _run(tmp_path, cams, {"cam-00": _scene(1)})
    same = _run(tmp_path, cams, {"cam-00": _scene(1)}, clock=MD_CLOCK + dt.timedelta(days=2))
    assert all(r["scene_changed"] is False for r in same["rows"])
    moved = _run(tmp_path, cams, {"cam-00": _scene(7)}, clock=MD_CLOCK + dt.timedelta(days=4))
    assert all(r["scene_changed"] is True for r in moved["rows"])
    assert moved["report"]["scene_changed"] == 1


def test_dhash_is_64_bits_and_hamming_counts_differing_bits():
    a = sc.dhash(np.arange(72, dtype=np.float32).reshape(8, 9))
    assert len(a) == 16
    assert sc.hamming(a, a) == 0
    assert sc.hamming(a, None) is None
    flipped = f"{int(a, 16) ^ 0b1011:016x}"
    assert sc.hamming(a, flipped) == 3


# ----------------------------------------------------- 3. spool + flush

def _db():
    import duckdb

    from loci import db as locidb

    con = duckdb.connect(":memory:")
    con.execute((locidb.SQL_DIR / "001_bootstrap.sql").read_text())
    con.execute((locidb.SQL_DIR / "024_sidewalk_count.sql").read_text())
    con.execute((locidb.SQL_DIR / "053_sidewalk_sweep.sql.draft").read_text()
                if (locidb.SQL_DIR / "053_sidewalk_sweep.sql.draft").exists()
                else (locidb.SQL_DIR / "053_sidewalk_sweep.sql").read_text())
    return con


def test_spool_round_trips_and_a_second_flush_adds_nothing(tmp_path):
    cams = _cams(2)
    out = _run(tmp_path, cams, {c.camera_id: _scene(i) for i, c in enumerate(cams)})
    assert out["spool"].exists()
    con = _db()
    first = sc.flush(con, tmp_path / "spool")
    assert first["files"] == 1
    assert first["rows_written"] == len(out["rows"])
    # The flushed file moved to done/; a re-flush of an empty spool is a no-op,
    # and re-inserting the same rows is refused by the key.
    assert sc.flush(con, tmp_path / "spool")["files"] == 0
    assert sc.write_rows(con, out["rows"]) == 0
    got = con.execute("SELECT n_car, n_bus, scene_hash, run_id FROM analysis.sidewalk_count "
                      "LIMIT 1").fetchone()
    assert got[0] == 3 and got[1] == 1 and len(got[2]) == 16 and got[3] == "20260917-md"


def test_rows_from_a_detector_without_extra_classes_write_null_not_zero():
    con = _db()
    det = pd_mod.DetectionResult(n_persons=1, n_persons_conf50=1, scores=(0.9,),
                                 width=352, height=240, seconds=0.0)
    row = sc._row(_cams(1)[0], MD_CLOCK, det, FakeDetector(), "h" * 64, "midday", "weekday")
    assert row["n_car"] is None
    sc.write_rows(con, [row])
    assert con.execute("SELECT n_car FROM analysis.sidewalk_count").fetchone()[0] is None


# ------------------------------------------------- 4. the owner throttle

def test_max_cameras_is_a_fixed_ordered_subset_and_the_default_is_all():
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA staging")
    con.execute("CREATE TABLE staging.dot_camera(camera_id VARCHAR, name VARCHAR, lon DOUBLE, "
                "lat DOUBLE, image_url VARCHAR, is_online BOOLEAN, area VARCHAR, "
                "borough VARCHAR, fetched_at TIMESTAMP)")
    con.executemany("INSERT INTO staging.dot_camera (camera_id, name, lon, lat, image_url, "
                    "is_online, area, borough, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    [[f"c{i}", "n", 0.0, 0.0, "u", True, "a", b, None]
                     for i, b in enumerate(["MN", "BK", "QN", "MN", "BK"])])
    assert [c.camera_id for c in sc.sweep_cameras(con)] == ["c0", "c1", "c3", "c4"]
    assert [c.camera_id for c in sc.sweep_cameras(con, max_cameras=2)] == ["c0", "c1"]
    with pytest.raises(ValueError):
        sc.sweep_cameras(con, max_cameras=0)


def test_a_sweep_started_after_the_window_closes_does_nothing(tmp_path):
    cams = _cams(2)
    late = dt.datetime(2026, 9, 17, 19, 0)          # 15:00 local, md closed at 14:00
    out = _run(tmp_path, cams, {c.camera_id: _scene(1) for c in cams}, clock=late)
    assert out["rows"] == [] and out["report"]["ticks"] == 0
    assert "closed" in out["report"]["note"]
    assert not (tmp_path / "spool").exists()


def test_a_slow_sweep_stops_at_the_window_close_not_at_the_planned_tick_count(tmp_path):
    """The first live pm sweep (2026-09-17) planned 17 ticks to 19:00 and ran
    to 22:39 because each tick's work was added to a full interval's sleep.
    The clock, not the tick count, ends a sweep; the sleep is the remainder."""
    cams = _cams(3)
    scenes = {c.camera_id: _scene(1) for c in cams}
    by_url = {c.image_url: scenes[c.camera_id] for c in cams}
    now = {"t": dt.datetime(2026, 9, 17, 17, 45)}       # 13:45 local: 2 ticks planned to 14:00
    slept: list[float] = []

    def clock():
        return now["t"]

    def sleep(s):
        slept.append(s)
        now["t"] += dt.timedelta(minutes=20)              # a slow endpoint: 20 min pass

    def fetch(url):
        now["t"] += dt.timedelta(minutes=4)               # each tick's work costs 4 min
        return _jpeg(by_url[url])

    out = sc.sweep(cams, "md", detector=FakeDetector(), fetch_fn=fetch, sleep_fn=sleep,
                   clock=clock, interval_s=600.0, spool_dir=tmp_path / "spool",
                   scene_state_path=tmp_path / "scene.json", concurrency=1)
    assert out["plan"]["ticks"] == 2
    assert out["report"]["ticks_run"] == 1                # the second tick fell after 14:00
    assert len(out["rows"]) == len(cams)
    # The sleep was the REMAINDER of the interval after the tick's 12 min of work.
    assert slept == [0.0]
    assert all(r["daypart"] == "midday" for r in out["rows"])


def test_sweep_plan_ticks_cover_the_remaining_window():
    now = dt.datetime(2026, 9, 17, 12, 0)
    assert sc.sweep_plan(10, "md", now)["ticks"] == 13          # 12:00 .. 14:00 inclusive
    assert sc.sweep_plan(10, "md", now.replace(hour=13, minute=45))["ticks"] == 2
    assert sc.sweep_plan(10, "md", now.replace(hour=6))["start_local"].hour == 12
    with pytest.raises(ValueError):
        sc.sweep_plan(1, "night", now)


# ------------------------------------------------------- 5. the plists

def test_plists_fire_tue_and_thu_at_each_windows_opening_hour(tmp_path):
    paths = sc.write_launchd_plists(out_dir=tmp_path, uv_path="/usr/local/bin/uv")
    assert len(paths) == 3
    for p in paths:
        d = plistlib.loads(p.read_bytes())
        window = d["ProgramArguments"][-1]
        assert d["ProgramArguments"][:5] == ["/usr/local/bin/uv", "run", "loci",
                                             "sidewalk-count", "sweep"]
        assert "--max-cameras" not in d["ProgramArguments"]          # default = ALL
        assert [c["Weekday"] for c in d["StartCalendarInterval"]] == [2, 4]
        assert {c["Hour"] for c in d["StartCalendarInterval"]} == {DOT_WINDOWS[window][0]}
    throttled = plistlib.loads(sc.launchd_plist("am", "uv", max_cameras=60))
    assert throttled["ProgramArguments"][-2:] == ["--max-cameras", "60"]


# ------------------------------------------------------- 6. the report

def test_report_compares_a_camera_with_itself_and_cuts_history_at_a_scene_change():
    con = _db()
    cam = _cams(1)[0]
    det = FakeDetector()

    def rows(run_id, day, persons, changed):
        at = dt.datetime(2026, 9, day, 16, 30)
        out = []
        for i in range(25):
            r = sc._row(cam, at + dt.timedelta(seconds=i), det.count(b""), det,
                        f"{run_id}{i:060d}", "midday", "weekday", run_id)
            r["n_persons"] = persons
            r["scene_hash"], r["scene_changed"] = "0" * 16, changed
            out.append(r)
        return out

    sc.write_rows(con, rows("20260901-md", 1, 9, None))    # old view: 9 persons
    sc.write_rows(con, rows("20260908-md", 8, 2, True))    # RE-AIMED: history restarts
    sc.write_rows(con, rows("20260915-md", 15, 4, False))  # latest
    df = sc.report(con, camera_id="cam-00")
    assert len(df) == 1
    r = df.iloc[0]
    assert r["latest_run"] == "20260915-md" and r["latest_persons"] == 4
    # History is the 09-08 run only (25 frames, mean 2): the 9-person run
    # before the re-aim is a different instrument and is not averaged in.
    assert r["history_runs"] == 1 and r["history_persons"] == 2
    assert r["ratio"] == pytest.approx(2.0)
    assert r["latest_car"] == 3


def test_report_prints_no_ratio_on_a_thin_history():
    con = _db()
    cam = _cams(1)[0]
    det = FakeDetector()
    for run_id, day in (("20260901-md", 1), ("20260908-md", 8)):
        at = dt.datetime(2026, 9, day, 16, 30)
        sc.write_rows(con, [sc._row(cam, at + dt.timedelta(seconds=i), det.count(b""), det,
                                    f"{run_id}{i:060d}", "midday", "weekday", run_id)
                            for i in range(3)])
    df = sc.report(con, camera_id="cam-00")
    assert df.iloc[0]["history_frames"] == 3 < sc.HISTORY_MIN_FRAMES
    assert np.isnan(df.iloc[0]["ratio"])


# --------------------------------------------------- the detector output

def test_extra_class_counts_come_from_the_same_forward_pass():
    """A synthetic head output with one confident car anchor and one person."""
    pred = np.zeros((6, 4 + 80), dtype=np.float32)
    pred[:, :4] = [50, 50, 20, 20]
    pred[0, 4 + pd_mod.PERSON_CLASS] = 0.9
    pred[1, 4 + pd_mod.EXTRA_CLASSES["car"]] = 0.8
    pred[2, 4 + pd_mod.EXTRA_CLASSES["car"]] = 0.7       # same box: NMS folds it
    pred[3, :4] = [200, 200, 20, 20]
    pred[3, 4 + pd_mod.EXTRA_CLASSES["bus"]] = 0.6
    assert len(pd_mod._class_scores(pred, pd_mod.PERSON_CLASS)) == 1
    assert len(pd_mod._class_scores(pred, pd_mod.EXTRA_CLASSES["car"])) == 1
    assert len(pd_mod._class_scores(pred, pd_mod.EXTRA_CLASSES["bus"])) == 1
    assert len(pd_mod._class_scores(pred, pd_mod.EXTRA_CLASSES["truck"])) == 0
