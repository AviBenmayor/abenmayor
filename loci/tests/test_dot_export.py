"""`webmap/data/dot.json` -- the payload the map's DOT layer reads.

Four things can go wrong here and only one of them is loud:

1. NON-STANDARD JSON. A pandas object column holds a missing string as NaN and
   `json.dumps` writes the bare token `NaN`. Python reads that back happily, so
   every Python-side check passes -- and `JSON.parse` refuses the file, so the
   layer silently never loads. This shipped once (the bridge midpoints have no
   cross street), which is why the first test here is a STRICT parse and why
   `export` passes allow_nan=False.
2. THE BOROUGH CODE. The webmap's borough filter joins on a two-letter code.
   DOT's own borough string is 'East River Bridges' for a bridge and the
   truncated 'Staten Isla' for Staten Island; both must become NULL, not a
   guess, and a bridge must stay drawable.
3. THE CAVEAT SEAM. The trend caveat (no Sept 2019, no May 2020 -- COVID) is a
   fact about the SERIES and lives in the source module. If the viz module ever
   retypes it, the map and the memo drift.
4. THE NOT-SAMPLED CAMERA. 966 of 969 cameras have no frames. The payload has
   to let the map say "not sampled" about them, which means a sampled-ID list
   the map can test against -- not silence.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from loci import db as locidb
from loci.sources.cities.nyc import dot_pedestrian as dp
from loci.viz import dot_export as de

SQL_DIR = pathlib.Path(locidb.SQL_DIR)

CAM_A = "aaaaaaaa-0000-0000-0000-000000000001"   # sampled
CAM_B = "bbbbbbbb-0000-0000-0000-000000000002"   # never sampled


def _boom(token):
    raise ValueError(f"non-standard JSON token {token!r}")


@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute("""CREATE TABLE analysis.address (
                    address_id VARCHAR, borough VARCHAR, lon DOUBLE, lat DOUBLE,
                    gap_score DOUBLE, homes_400m BIGINT)""")
    c.execute((SQL_DIR / "022_dot.sql").read_text())

    # Two on-street points and one bridge midpoint. The bridge has NO cross
    # streets -- that is the row that used to write NaN into the file.
    recs = []
    for i, rnd in enumerate(["2024-05", "2024-10", "2025-05", "2025-10", "2026-05"]):
        for per, base in (("am", 100), ("md", 200), ("pm", 300)):
            recs.append({"point_id": 1, "round": rnd, "period": per,
                         "count": base + 10 * i, "lon": -73.99, "lat": 40.75,
                         "borough": "Manhattan", "street": "West 34th Street",
                         "from_street": "Broadway", "to_street": "Seventh Avenue",
                         "is_bridge": False, "loc_type": "on_street",
                         "is_index": True, "source_field": f"may{i}_{per}"})
            recs.append({"point_id": 2, "round": rnd, "period": per,
                         "count": base, "lon": -73.95, "lat": 40.71,
                         "borough": "Staten Isla", "street": "Bay Street",
                         "from_street": "A", "to_street": "B",
                         "is_bridge": False, "loc_type": "on_street",
                         "is_index": False, "source_field": f"may{i}_{per}"})
            recs.append({"point_id": 103, "round": rnd, "period": per,
                         "count": base, "lon": -73.97, "lat": 40.71,
                         "borough": "East River Bridges",
                         "street": "Williamsburg Bridge",
                         "from_street": None, "to_street": None,
                         "is_bridge": True, "loc_type": "east_river_bridge",
                         "is_index": False, "source_field": f"may{i}_{per}"})
    dp.write_counts(c, recs)

    c.execute("INSERT INTO staging.dot_camera VALUES (?,?,?,?,?,?,?,?,?)",
              [CAM_A, "5 AVE @ 50 St", -73.9766, 40.7588, "http://x/a", True,
               "Manhattan", "MN", dt.datetime(2026, 9, 13)])
    c.execute("INSERT INTO staging.dot_camera VALUES (?,?,?,?,?,?,?,?,?)",
              [CAM_B, "10 Ave @ 23 St", -74.0044, 40.7480, "http://x/b", True,
               "Manhattan", "MN", dt.datetime(2026, 9, 13)])
    return c


@pytest.fixture()
def sampled(con):
    """Frames for CAM_A only -- CAM_B is the not-sampled case, on purpose."""
    con.execute((SQL_DIR / "024_sidewalk_count.sql").read_text())
    rows = []
    # 22:54 UTC on 2026-09-13 is 18:54 LOCAL, a Sunday pm_peak. The local date
    # and the UTC date agree here; the 2026-09-14 03:00 UTC frame below is the
    # SAME local evening and must not be reported as a second sample date.
    for k in range(3):
        rows.append((CAM_A, dt.datetime(2026, 9, 13, 22, 54, k), k, k,
                     "sunday", "pm_peak"))
    rows.append((CAM_A, dt.datetime(2026, 9, 14, 3, 0, 0), 7, 5,
                 "sunday", "evening"))
    for (cam, ts, n, n50, day_type, daypart) in rows:
        con.execute("INSERT INTO analysis.sidewalk_count VALUES (?,?,?,?,?,?,?,?,?)",
                    [cam, ts, n, n50, "yolo11n", "abc123def456",
                     f"hash{ts.isoformat()}", daypart, day_type])
    return con


# --------------------------------------------------- 1. the file must parse

def test_the_written_file_is_json_a_browser_will_parse(con, tmp_path):
    """The bug that shipped: a bridge point has no cross street, pandas makes
    that NaN, and `json.dumps` writes the bare token `NaN`. `json.load` accepts
    it and `JSON.parse` does not -- so every Python check passed while the map
    could not load the layer at all."""
    de.export(con, out_dir=tmp_path)
    text = (tmp_path / de.OUT_NAME).read_text()
    assert "NaN" not in text and "Infinity" not in text
    bundle = json.loads(text, parse_constant=_boom)      # raises on NaN/Infinity

    i = {c: k for k, c in enumerate(bundle["counts"]["cols"])}
    bridge = [r for r in bundle["counts"]["rows"] if r[i["type"]] != "on_street"][0]
    assert bridge[i["from"]] is None and bridge[i["to"]] is None


def test_a_missing_cross_street_is_written_as_null_not_nan(con, tmp_path, monkeypatch):
    """THE ACTUAL REGRESSION. The live warehouse hands `point_summary` back
    with pandas' string dtype whose NA sentinel IS float NaN
    (`StringDtype(na_value=nan)`); an in-memory fixture happens to hand back
    None, so the failure mode has to be injected to be tested at all -- which
    is exactly why it reached a shipped file.

    Delete `_txt` from collect_counts and this test raises (allow_nan=False)
    instead of quietly writing a payload no browser can parse.
    """
    real = dp.point_summary

    def nan_strings(c, **kw):
        df = real(c, **kw)
        df["to_street"] = df["to_street"].astype(object)
        df.loc[df["to_street"].isna(), "to_street"] = float("nan")
        return df

    monkeypatch.setattr(dp, "point_summary", nan_strings)
    de.export(con, out_dir=tmp_path)
    text = (tmp_path / de.OUT_NAME).read_text()
    assert "NaN" not in text
    bundle = json.loads(text, parse_constant=_boom)
    i = {c: k for k, c in enumerate(bundle["counts"]["cols"])}
    bridge = [r for r in bundle["counts"]["rows"] if r[i["id"]] == 103][0]
    assert bridge[i["to"]] is None


def test_a_nan_anywhere_raises_instead_of_shipping(con, tmp_path, monkeypatch):
    """allow_nan=False is the backstop. If a future field skips `_txt`, the
    export must fail loudly rather than write a file the map cannot read."""
    monkeypatch.setattr(de, "collect_cameras",
                        lambda _c: {"cols": de.CAMERA_COLS,
                                    "rows": [["x", 0.0, float("nan"), "n", "MN", True]],
                                    "n": 1, "boroughNames": {}})
    with pytest.raises(ValueError):
        de.export(con, out_dir=tmp_path)


# ------------------------------------------------- 2. the borough code seam

def test_the_borough_code_is_null_rather_than_a_guess(con):
    """The map filters on a two-letter code. 'East River Bridges' is not a
    borough and DOT's 'Staten Isla' is truncated -- both must be NULL, and the
    bridge must still be a row, because the map draws it in every view."""
    counts = de.collect_counts(con)
    i = {c: k for k, c in enumerate(counts["cols"])}
    by_id = {r[i["id"]]: r for r in counts["rows"]}
    assert by_id[1][i["bc"]] == "MN"
    assert by_id[2][i["bc"]] is None          # 'Staten Isla', truncated by DOT
    assert by_id[103][i["bc"]] is None        # a span is in no borough
    assert by_id[103][i["type"]] == "east_river_bridge"
    # `bc` is LAST: the webmap reads these rows positionally.
    assert counts["cols"][-1] == "bc"


def test_the_counted_windows_come_from_the_source_module(con):
    """The popup prints 'AM 07-09'. If this file ever retyped the windows, a
    retuned constant would leave the map claiming hours DOT does not count --
    and AM/MD are two hours while PM is three, so they are not thirds."""
    counts = de.collect_counts(con)
    assert counts["windows"] == {p: list(w) for p, w in dp.WINDOWS.items()}
    assert counts["periods"] == list(dp.PERIODS)
    assert counts["windows"]["pm"] == [16, 19]


# ------------------------------------------------------- 3. the caveat seam

def test_the_covid_trend_caveat_is_the_source_modules_own_constant():
    cav = de.caveats()
    assert cav["trend"] is dp.TREND_CAVEAT
    assert "COVID" in cav["trend"]
    for r in dp.MISSING_ROUNDS:
        year = r[:4]
        assert year in cav["trend"]


def test_the_legend_line_never_claims_a_per_hour_rate():
    """DOT publishes no expansion factor. 'people per hour' would be a rate
    this project invented, so the one line the legend must carry says window,
    and says the two quantities are not comparable."""
    cav = de.caveats()["compare"]
    assert "per hour" not in cav.lower()
    assert "never compare the two" in cav
    assert "stock" in cav and "screenline" in cav


# ------------------------------------------------- 4. the camera sample block

def test_sample_summary_is_one_row_per_camera_daytype_daypart(sampled):
    s = de.collect_samples(sampled)
    assert s["available"] is True
    i = {c: k for k, c in enumerate(s["cols"])}
    keys = [(r[i["cam"]], r[i["dayType"]], r[i["daypart"]]) for r in s["rows"]]
    assert keys == [(CAM_A, "sunday", "pm_peak"), (CAM_A, "sunday", "evening")]
    pm = s["rows"][0]
    assert pm[i["frames"]] == 3 and pm[i["max"]] == 2
    assert pm[i["mean"]] == 1.0                     # (0+1+2)/3, 2 dp
    assert s["frames"] == 4 == sum(r[i["frames"]] for r in s["rows"])


def test_the_payload_stays_small_ints_and_two_dp_means(sampled):
    """969 cameras ride in the same file. A float per cell would be the whole
    budget, so counts are ints and means are 2 dp."""
    s = de.collect_samples(sampled)
    i = {c: k for k, c in enumerate(s["cols"])}
    for r in s["rows"]:
        assert isinstance(r[i["frames"]], int) and isinstance(r[i["max"]], int)
        assert r[i["mean"]] == round(r[i["mean"]], 2)


def test_sample_dates_are_local_not_utc(sampled):
    """`sampled_at` is stored UTC. A run at 23:00 local is stamped the NEXT day
    in UTC; printing that would tell a New York reader the sidewalk was watched
    on a day it was not."""
    s = de.collect_samples(sampled)
    assert s["dates"][CAM_A] == ["2026-09-13"]      # not ['2026-09-13','2026-09-14']


def test_an_unsampled_camera_is_absent_from_the_sampled_list(sampled):
    """THE 'NOT SAMPLED' CASE. The map says "not sampled" by testing a camera
    against `samples.cameras`; a camera with no frames must be missing from
    that list and have no rows -- never a zero, which would read as an empty
    sidewalk we measured."""
    s = de.collect_samples(sampled)
    i = {c: k for k, c in enumerate(s["cols"])}
    assert s["cameras"] == [CAM_A]
    assert CAM_B not in s["cameras"]
    assert CAM_B not in s["dates"]
    assert not [r for r in s["rows"] if r[i["cam"]] == CAM_B]
    # ... and the camera is still IN the registry: not sampled is not absent.
    cams = de.collect_cameras(sampled)
    ci = {c: k for k, c in enumerate(cams["cols"])}
    assert CAM_B in {r[ci["id"]] for r in cams["rows"]}


def test_no_sampling_at_all_says_so_rather_than_raising(con):
    """A database where `loci sidewalk-count sample` has never run must still
    export: the block reports why, and the map draws plain camera dots."""
    s = de.collect_samples(con)                      # 024 never applied
    assert s["available"] is False and s["rows"] == [] and s["cameras"] == []
    assert de.SAMPLE_TABLE in s["reason"]


def test_camera_borough_names_let_a_popup_name_a_borough_this_map_omits(con):
    """meta.json knows only the two boroughs the map draws; the cameras span
    five. The code -> name map rides here so the popup does not need a second
    borough vocabulary in the page."""
    cams = de.collect_cameras(con)
    assert cams["boroughNames"]["QN"] == "Queens"
    assert cams["boroughNames"]["SI"] == "Staten Island"


def test_build_carries_every_block_the_layer_reads(sampled):
    b = de.build(sampled)
    assert set(b) >= {"counts", "cameras", "samples", "source", "caveats"}
    assert set(b["caveats"]) >= {"counts", "cameras", "samples", "trend", "compare"}
