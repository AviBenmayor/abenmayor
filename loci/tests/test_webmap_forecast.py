"""Unit tests for the MODELED / REALIZED / SURPRISE webmap layer (D92).

Owner framing 2026-09-14: the product has a MODELED layer (what could be) and
a REALIZED layer (what happened), and the difference -- SURPRISE -- is where
the new information is. Five things here are load-bearing and every one of them
fails SILENTLY: the map still draws, it just draws something untrue.

  (a) THE PROBABILITY IS KEYED TO THE GAP FILE'S OWN ADDRESS ORDER. The browser
      paints `p` onto the dot at slot j of `gaps/<cat>.json`. `gap_id_order`
      re-derives that order WITHOUT building the layers -- that is the whole
      reason `loci forecast-export` can rewrite one file in seconds instead of
      paying the 90-second export -- so if its predicate ever drifts from
      `_gap_sql` + `pack_gaps`, every probability lands on the wrong doorway
      and nothing on screen looks wrong. The test pins the two together,
      including the adversarial row `pack_gaps` drops for a NULL coordinate.

  (b) NOT MEASURED IS NOT ZERO, THREE TIMES OVER. An address the model did not
      score, a category with no forecast, and a forecast nothing has scored are
      three different absences and none of them is a zero. Each must reach the
      browser as an explicit state with its own reason.

  (c) SURPRISE NEVER RENDERS WITHOUT AN EXPECTED VALUE. A neighborhood with no
      expectation is not emitted at all -- not with a null, not with a zero --
      so nothing downstream can paint it by accident. And a null `z_clustered`
      is NOT backfilled from `z_naive`: sql/028 returns null below five
      variance clusters because "a sandwich variance from three clusters is not
      an estimate", and the naive z it publishes beside it is 3-5x too
      confident by that same header.

  (d) ONLY A DATED FIRST-SEEN IS AN OPENING. `first_seen_kind` 'observed' means
      we first saw it in that month's snapshot and 'backfill_censored' means it
      was already there when the ledger opened. Drawing either as an opening
      turns our own snapshot cadence into a market event.

  (e) THE WINDOW IS COUNTED BACK FROM THE LEDGER, NOT FROM THE CLOCK. A map
      built on a six-month-old snapshot must shorten its window, not draw six
      empty months and call them a slowdown.

Runs against a scratch in-memory DuckDB built by `loci.db.connect(":memory:")`.
"""
from __future__ import annotations

import json

import pytest

from loci import db
from loci.viz import webmap_export as wx

CATS = list(wx.ALLCATS)
CAT = "laundry"
OTHER = "pharmacy"

#: The ledger's own borough spelling. `analysis.poi_first_seen` stores the NAME
#: and every other layer on this map uses the CODE; a fixture that used one for
#: both would let a real bug through.
LEDGER_BOROUGH = wx.BOROUGH_NAMES["MN"]


@pytest.fixture()
def con():
    c = db.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis;")
    c.execute("CREATE SCHEMA IF NOT EXISTS staging;")
    ratios = ", ".join(f"{cat}_ratio DOUBLE, {cat}_nearest_m DOUBLE" for cat in CATS)
    c.execute(f"""
        CREATE TABLE analysis.address_gaps (
            address_id VARCHAR, borough VARCHAR, lon DOUBLE, lat DOUBLE,
            units_capped INTEGER, neighborhood VARCHAR, nta_code VARCHAR,
            gap_score DOUBLE, lead_category VARCHAR, {ratios})
    """)
    c.execute("""
        CREATE TABLE analysis.forecast (
            forecast_id VARCHAR, issued_month VARCHAR, horizon_months INTEGER,
            model_version VARCHAR, address_id VARCHAR, category VARCHAR,
            frame VARCHAR, borough VARCHAR, nta_code VARCHAR,
            surprise_cell VARCHAR, p_opening DOUBLE, expected_openings DOUBLE,
            support VARCHAR, features_json VARCHAR, frozen_at TIMESTAMP)
    """)
    c.execute("""
        CREATE TABLE analysis.forecast_outcome (
            forecast_id VARCHAR, scored_month VARCHAR, horizon_elapsed INTEGER,
            realized_openings INTEGER, realized_flag BOOLEAN, scored_at TIMESTAMP)
    """)
    # The two VIEWS the export reads through, in the shape sql/028 defines them.
    c.execute("""
        CREATE VIEW analysis.forecast_latest AS
        SELECT f.address_id, f.category, f.frame, f.borough, f.nta_code,
               f.issued_month, f.model_version, f.horizon_months,
               f.p_opening, f.expected_openings, f.support, f.features_json,
               o.scored_month, o.horizon_elapsed, o.realized_openings, o.realized_flag
        FROM analysis.forecast f
        LEFT JOIN analysis.forecast_outcome o ON o.forecast_id = f.forecast_id
        WHERE f.issued_month = (SELECT max(issued_month) FROM analysis.forecast)
    """)
    c.execute("""
        CREATE TABLE analysis.forecast_surprise_nta (
            issued_month VARCHAR, model_version VARCHAR, scored_month VARCHAR,
            horizon_elapsed INTEGER, nta_code VARCHAR, category VARCHAR,
            n_addresses BIGINT, n_cells BIGINT, realized BIGINT,
            expected DOUBLE, surprise DOUBLE, z_naive DOUBLE, z_clustered DOUBLE)
    """)
    c.execute("""
        CREATE TABLE analysis.poi_first_seen (
            location_key VARCHAR, category VARCHAR, display_name VARCHAR,
            lon DOUBLE, lat DOUBLE, borough VARCHAR, first_seen_kind VARCHAR,
            first_seen_on DATE, closed_on DATE, closed_src VARCHAR,
            poi_id_latest VARCHAR)
    """)
    # The predicate's join target (model.poi_presence.poi_is_open, GTM-153).
    # Column subset of the real staging.poi (sql/002_schema.sql) -- only what
    # the predicate reads.
    c.execute("""
        CREATE TABLE staging.poi (
            poi_id VARCHAR, source_id VARCHAR, category VARCHAR,
            observed_on DATE, attrs VARCHAR)
    """)
    c.execute("""
        CREATE TABLE analysis.storefront_pipeline (
            pipeline_id VARCHAR, borough VARCHAR, lon DOUBLE, lat DOUBLE,
            business_name VARCHAR, entry_stage VARCHAR, entry_date DATE,
            loci_category VARCHAR, is_open BOOLEAN)
    """)
    yield c
    c.close()


def _add_gap(con, address_id, borough="MN", lon=-73.9857, lat=40.7484,
             gap_cats=(CAT,), nta="MN0001"):
    cols = ["address_id", "borough", "lon", "lat", "units_capped", "neighborhood",
            "nta_code", "gap_score", "lead_category"]
    vals = [address_id, borough, lon, lat, 50, "Midtown", nta, 0.5, CAT]
    for cat in CATS:
        cols += [f"{cat}_ratio", f"{cat}_nearest_m"]
        vals += [2.0 if cat in gap_cats else 0.5, 300.0]
    con.execute(f"INSERT INTO analysis.address_gaps ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in vals)})", vals)


def _issue(con, address_id, p, category=CAT, month="2026-09",
           version="0.1.0+deadbeef", horizon=12, nta="MN0001"):
    fid = f"{month}|{version}|{category}|{address_id}"
    con.execute("""
        INSERT INTO analysis.forecast (forecast_id, issued_month, horizon_months,
            model_version, address_id, category, nta_code, p_opening)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [fid, month, horizon, version, address_id, category, nta, p])
    return fid


def _seen(con, category=CAT, kind="source_date", on="2026-08-01", name="Sud Club",
          closed=None, lon=-73.98, lat=40.75, borough=LEDGER_BOROUGH,
          poi_id_latest=None):
    con.execute("""
        INSERT INTO analysis.poi_first_seen (location_key, category, display_name,
            lon, lat, borough, first_seen_kind, first_seen_on, closed_on, closed_src,
            poi_id_latest)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [name + str(on), category, name, lon, lat, borough, kind, on, closed,
          "foursquare" if closed else None, poi_id_latest])


def _spoi(con, poi_id, source_id, category=CAT, attrs=None, observed_on=None):
    """A `staging.poi` row for the predicate's attrs-based branches
    (model.poi_presence.poi_is_open, GTM-153)."""
    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, category, observed_on, attrs) "
        "VALUES (?, ?, ?, ?, ?)",
        [poi_id, source_id, category, observed_on, json.dumps(attrs or {})])


def _filing(con, category=CAT, entry="2026-08-01", stage="fitout_filing",
            is_open=False, name="Future Wash", borough="MN"):
    con.execute("""
        INSERT INTO analysis.storefront_pipeline (pipeline_id, borough, lon, lat,
            business_name, entry_stage, entry_date, loci_category, is_open)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [name + str(entry), borough, -73.99, 40.74, name, stage, entry,
          category, is_open])


def _surprise(con, nta="MN0001", category=CAT, expected=2.0, realized=5,
              surprise=3.0, z_naive=4.0, z_clustered=1.8, scored="2024-01",
              issued="2023-01", version="0.1.0+deadbeef", cells=7, addresses=900):
    con.execute("""
        INSERT INTO analysis.forecast_surprise_nta VALUES
        (?, ?, ?, 12, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [issued, version, scored, nta, category, addresses, cells, realized,
          expected, surprise, z_naive, z_clustered])


# --------------------------------------------------------------- permille

def test_permille_is_an_integer_and_null_stays_null():
    assert wx.permille(0.1234) == 123
    assert wx.permille(0.1239) == 124
    assert wx.permille(0.0) == 0
    assert wx.permille(1.0) == wx.P_SCALE
    # Out-of-range input is clamped, not exported as a probability above one.
    assert wx.permille(1.4) == wx.P_SCALE
    assert wx.permille(-0.2) == 0
    # The two not-measured inputs. Neither may become a zero.
    assert wx.permille(None) is None
    assert wx.permille(float("nan")) is None


def test_permille_round_trips_through_json_as_an_integer(con):
    _add_gap(con, "a")
    _issue(con, "a", 0.0)                       # a real, measured zero
    fc = wx.collect_forecast(con, ["MN"])
    block = fc["modeled"]["byCat"][CAT]
    p = block["p"][0] if block["encoding"] == "dense" else block["p"][0]
    assert p == 0 and isinstance(p, int)
    # ...and survives the serialiser as 0, never as null.
    assert '"p":[0]' in json.dumps(fc, separators=(",", ":"))


# ------------------------------------------------ (a) the address ordering

def test_gap_id_order_is_the_order_pack_gaps_writes(con):
    """The load-bearing pairing. `gap_id_order` must reproduce, without
    building the layers, exactly the id list `pack_gaps` emits -- INCLUDING
    the row it drops for a missing coordinate. A silent divergence here
    attaches every probability to the wrong doorway."""
    _add_gap(con, "zzz")                        # inserted out of id order
    _add_gap(con, "aaa")
    _add_gap(con, "mmm", lon=None, lat=None)    # pack_gaps drops this one
    _add_gap(con, "bbb", borough="BK")          # outside the borough filter

    sql, params = wx._gap_sql(CAT, ["MN"], pipeline=False, storefront=False,
                              age_fit=False, age_source=False, censoring=False,
                              frame=False)
    packed = wx.pack_gaps(con.execute(sql, params).fetchall(), ["MN"], CAT)
    assert packed["ids"] == ["aaa", "zzz"]
    assert wx.gap_id_order(con, ["MN"])[CAT] == packed["ids"]


def test_probability_lands_on_the_address_it_was_issued_for(con):
    _add_gap(con, "zzz")
    _add_gap(con, "aaa")
    _issue(con, "zzz", 0.4)
    fc = wx.collect_forecast(con, ["MN"])
    block = fc["modeled"]["byCat"][CAT]
    # `aaa` sorts first, so the forecast belongs to slot 1 and slot 0 is unscored.
    if block["encoding"] == "sparse":
        assert block["idx"] == [1] and block["p"] == [400]
    else:
        assert block["p"] == [None, 400]


def test_sparse_and_dense_pick_whichever_is_smaller():
    order = {CAT: [f"a{i}" for i in range(10)]}
    dense = wx.pack_modeled({CAT: {f"a{i}": 0.5 for i in range(10)}}, order)[CAT]
    assert dense["encoding"] == "dense" and len(dense["p"]) == 10
    sparse = wx.pack_modeled({CAT: {"a3": 0.5}}, order)[CAT]
    assert sparse["encoding"] == "sparse" and sparse["idx"] == [3]
    # Both must report the same two counts, or the legend's "N of M carry a
    # forecast" sentence would depend on an encoding the reader cannot see.
    assert dense["n"] == sparse["n"] == 10
    assert (dense["nForecast"], sparse["nForecast"]) == (10, 1)


def test_ramp_stops_are_strictly_increasing_after_the_integer_round():
    """MapLibre's `interpolate` rejects a repeated stop, and a saturated
    forecast -- most doorways near zero -- produces plenty of them."""
    order = {CAT: [f"a{i}" for i in range(50)]}
    block = wx.pack_modeled({CAT: {f"a{i}": 0.001 for i in range(50)}}, order)[CAT]
    assert len(block["stops"]) == wx.FORECAST_RAMP_STOPS
    assert all(b > a for a, b in zip(block["stops"], block["stops"][1:]))


# --------------------------------------------- (b) three kinds of absence

def test_no_forecast_issued_is_a_stated_reason_not_an_empty_map(con):
    _add_gap(con, "a")
    _seen(con)                                   # the ledger still has something
    fc = wx.collect_forecast(con, ["MN"])
    assert fc["modeled"]["available"] is False
    assert "forecast issue" in fc["modeled"]["reason"]
    assert fc["modeled"]["byCat"] == {}
    # The other two blocks are INDEPENDENT: a database with no model still
    # draws what actually happened.
    assert fc["realized"]["available"] is True
    assert fc["realized"]["byCat"][CAT]["open"]["n"] == 1
    # And every key the UI reads is present, so the not-measured state renders
    # rather than throwing.
    for key in ("modeled", "realized", "surprise", "caveats", "pScale", "cats"):
        assert key in fc


def test_a_category_with_no_forecast_is_absent_not_zero(con):
    _add_gap(con, "a", gap_cats=(CAT, OTHER))
    _issue(con, "a", 0.3, category=CAT)
    fc = wx.collect_forecast(con, ["MN"])
    assert CAT in fc["modeled"]["byCat"]
    # No key at all for the unforecast category -- a block of zeros would be a
    # map saying "nothing will open here", which the model never said.
    assert OTHER not in fc["modeled"]["byCat"]
    assert OTHER not in fc["modeled"]["cats"]


def test_an_unscored_address_is_null_never_zero(con):
    _add_gap(con, "a")
    _add_gap(con, "b")
    _issue(con, "a", 0.25)
    fc = wx.collect_forecast(con, ["MN"])
    block = fc["modeled"]["byCat"][CAT]
    if block["encoding"] == "dense":
        assert block["p"] == [250, None]
        assert "null" in json.dumps(block["p"])
    else:
        assert block["idx"] == [0] and block["p"] == [250]
    assert block["nForecast"] == 1 and block["n"] == 2


def test_no_scored_outcome_is_not_a_surprise_of_zero(con):
    _add_gap(con, "a")
    _issue(con, "a", 0.3)
    fc = wx.collect_forecast(con, ["MN"])
    assert fc["surprise"]["available"] is False
    assert fc["surprise"]["byCat"] == {}
    assert "forecast score" in fc["surprise"]["reason"]


# --------------------------------------- (c) surprise and its refusals

def test_surprise_never_renders_for_an_nta_without_an_expected_value(con):
    _add_gap(con, "a")
    _surprise(con, nta="MN0001", expected=2.0)
    _surprise(con, nta="MN0002", expected=None, realized=4, surprise=None,
              z_naive=None, z_clustered=None)
    fc = wx.collect_forecast(con, ["MN"])
    rows = fc["surprise"]["byCat"][CAT]
    assert [r[0] for r in rows] == ["MN0001"]


def test_a_null_clustered_z_ships_as_not_measured_never_as_the_naive_z(con):
    """sql/028 returns a null `z_clustered` below five variance clusters
    because 'a sandwich variance from three clusters is not an estimate'.
    Substituting `z_naive` -- 3-5x too confident by that file's own header --
    would be this map claiming exactly the significance the model declined."""
    _add_gap(con, "a")
    _surprise(con, nta="MN0001", expected=2.0, realized=5, surprise=3.0,
              z_naive=4.0, z_clustered=None, cells=3)
    fc = wx.collect_forecast(con, ["MN"])
    i = {c: k for k, c in enumerate(fc["surprise"]["cols"])}
    row = fc["surprise"]["byCat"][CAT][0]
    assert row[i["z"]] is None
    assert row[i["zNaive"]] == 4.0          # carried, for the design effect
    assert row[i["expected"]] == 2.0 and row[i["realized"]] == 5
    assert fc["surprise"]["nNoZ"] == 1


def test_the_pooled_all_category_row_is_dropped(con):
    _add_gap(con, "a")
    _surprise(con, category=CAT)
    _surprise(con, category=wx.SURPRISE_POOLED_CATEGORY)
    fc = wx.collect_forecast(con, ["MN"])
    assert set(fc["surprise"]["byCat"]) == {CAT}


def test_surprise_draws_one_scored_vintage_not_a_pool_of_two(con):
    """Two vintages scored at different dates must not be averaged. The newest
    scored month wins, and the block says which vintage it is showing."""
    _add_gap(con, "a")
    _surprise(con, nta="MN0001", issued="2023-01", scored="2024-01",
              expected=2.0, realized=5, z_clustered=1.8)
    _surprise(con, nta="MN0001", issued="2024-01", scored="2025-01",
              expected=3.0, realized=3, z_clustered=0.1)
    fc = wx.collect_forecast(con, ["MN"])
    rows = fc["surprise"]["byCat"][CAT]
    assert len(rows) == 1
    i = {c: k for k, c in enumerate(fc["surprise"]["cols"])}
    assert rows[0][i["expected"]] == 3.0
    assert fc["surprise"]["vintage"]["issuedMonth"] == "2024-01"
    assert fc["surprise"]["vintage"]["scoredMonth"] == "2025-01"


def test_surprise_obeys_the_borough_filter(con):
    _add_gap(con, "a")
    _surprise(con, nta="MN0001")
    _surprise(con, nta="BK0101")
    assert [r[0] for r in wx.collect_surprise(con, ["MN"])["byCat"][CAT]] == ["MN0001"]
    assert len(wx.collect_surprise(con, ["MN", "BK"])["byCat"][CAT]) == 2


# ------------------------------------------------- (d)(e) the realized block

def test_only_a_dated_first_seen_is_drawn_as_an_opening(con):
    _add_gap(con, "a")
    _seen(con, kind="source_date", on="2026-08-01", name="dated")
    _seen(con, kind="gov_filing", on="2026-07-01", name="filed")
    _seen(con, kind="observed", on="2026-06-01", name="observed")
    _seen(con, kind="backfill_censored", on="2026-05-01", name="backfilled")
    marks = wx.collect_realized(con, ["MN"])["byCat"][CAT]
    assert marks["open"]["n"] == 2
    assert sorted(marks["names"][i] for i in marks["open"]["nm"]) == ["dated", "filed"]


def test_the_window_is_counted_back_from_the_ledger_not_the_clock(con):
    _add_gap(con, "a")
    _seen(con, on="2024-06-15", name="newest")
    _seen(con, on="2023-09-01", name="inside")
    _seen(con, on="2023-05-01", name="outside")
    r = wx.collect_realized(con, ["MN"])
    assert r["asof"] == "2024-06"
    assert (r["from"], r["to"]) == ("2023-07", "2024-06")
    assert len(r["months"]) == wx.REALIZED_MONTHS
    names = {r["byCat"][CAT]["names"][i] for i in r["byCat"][CAT]["open"]["nm"]}
    assert names == {"newest", "inside"}


def test_closures_ride_beside_openings_and_keep_their_own_month(con):
    _add_gap(con, "a")
    _seen(con, on="2026-01-01", name="Open then shut", closed="2026-06-10")
    r = wx.collect_realized(con, ["MN"])
    marks = r["byCat"][CAT]
    assert marks["open"]["n"] == 1 and marks["closed"]["n"] == 1
    assert r["months"][marks["closed"]["m"][0]] == "2026-06"
    assert r["months"][marks["open"]["m"][0]] == "2026-01"


def test_closed_via_predicate_without_closed_on_has_no_month_to_draw(con):
    """A DCWP/DOHMH/SLA/DOS-only closure -- read via `model.poi_presence.
    poi_is_open` (GTM-153) -- carries no `closed_on` date on the ledger row,
    so it has nothing to bucket into on this DATED timeline. Unchanged from
    before: `closed_on` was already the only closure evidence this query
    used, so a closure the predicate now also recognises but cannot date
    silently does not appear, exactly as it silently did not appear before
    the predicate existed."""
    _add_gap(con, "a")
    _spoi(con, "dcwp:1", "nyc_dcwp_inspections", category=CAT,
          attrs={"active": False, "active_basis": "out_of_business"})
    _seen(con, kind="observed", on="2026-01-01", name="Ghost", closed=None,
          poi_id_latest="dcwp:1")
    r = wx.collect_realized(con, ["MN"])
    marks = r["byCat"].get(CAT, {"open": {"n": 0}, "closed": {"n": 0}})
    assert marks["closed"]["n"] == 0


def test_closed_on_wins_over_a_contradictory_open_predicate_basis(con):
    """The ledger's own `closed_on` is the predicate's FIRST branch: it wins
    even when the joined POI row's attrs would otherwise read 'open', so this
    map and the recommendation ledger's `still_open` component
    (model/recommendation_ledger.py) can never disagree about this case."""
    _add_gap(con, "a")
    _spoi(con, "doh:1", "nyc_dohmh_restaurants", category=CAT,
          attrs={"active": True, "active_basis": "inspected_5d_ago",
                 "last_inspection_date": "2026-06-05"})
    _seen(con, on="2026-01-01", name="Closed anyway", closed="2026-06-10",
          poi_id_latest="doh:1")
    r = wx.collect_realized(con, ["MN"])
    marks = r["byCat"][CAT]
    assert marks["closed"]["n"] == 1
    assert r["months"][marks["closed"]["m"][0]] == "2026-06"


def test_only_unopened_filings_are_pipeline_marks(con):
    _add_gap(con, "a")
    _filing(con, entry="2026-08-01", is_open=False, name="still filing")
    _filing(con, entry="2026-08-02", is_open=True, name="already open")
    _filing(con, entry="2026-08-03", is_open=False, name="uncategorised",
            category=None)
    _seen(con, on="2026-08-20")                  # sets the window's asof
    marks = wx.collect_realized(con, ["MN"])["byCat"][CAT]
    assert marks["pipe"]["n"] == 1
    assert marks["names"][marks["pipe"]["nm"][0]] == "still filing"
    assert marks["stages"][marks["pipe"]["st"][0]] == "fitout_filing"


def test_the_ledger_borough_is_matched_by_name_not_by_code(con):
    """`analysis.poi_first_seen` stores 'Manhattan'; every other layer here
    uses 'MN'. A filter built from the codes would export silently nothing."""
    _add_gap(con, "a")
    _seen(con, borough=wx.BOROUGH_NAMES["MN"], name="in")
    _seen(con, borough=wx.BOROUGH_NAMES["QN"], name="out")
    marks = wx.collect_realized(con, ["MN"])["byCat"][CAT]
    assert marks["open"]["n"] == 1


def test_an_empty_ledger_is_a_stated_reason(con):
    _add_gap(con, "a")
    r = wx.collect_realized(con, ["MN"])
    assert r["available"] is False and "poi-snapshot" in r["reason"]
    assert r["byCat"] == {}


# ------------------------------------------------------------ the payload

def test_export_carries_every_field_the_ui_reads(con, tmp_path):
    _add_gap(con, "a")
    _issue(con, "a", 0.42)
    _seen(con, on="2026-08-01")
    _filing(con)
    _surprise(con)
    fc = wx.collect_forecast(con, ["MN"])
    written = wx.write_forecast(fc, tmp_path)
    assert set(written) == {wx.FORECAST_FILE}
    out = json.loads((tmp_path / wx.FORECAST_FILE).read_text())

    assert out["issuedMonth"] == "2026-09"
    assert out["modelVersion"] == "0.1.0+deadbeef"
    assert out["horizonMonths"] == 12
    assert out["pScale"] == wx.P_SCALE
    block = out["modeled"]["byCat"][CAT]
    assert set(block) >= {"n", "nForecast", "encoding", "p", "stops", "pMin", "pMax"}
    assert out["realized"]["byCat"][CAT]["open"]["n"] == 1
    assert out["surprise"]["cols"] == list(wx.SURPRISE_COLS)
    # The three caveats are the page's contract, not decoration.
    assert set(out["caveats"]) == {"modeled", "realized", "surprise"}
    assert "not of viability" in out["caveats"]["modeled"]
    assert "3%" in out["caveats"]["realized"]


def test_meta_block_is_data_free(con, tmp_path):
    """meta.json carries the legend, never the 645k probabilities: a viewer who
    never opens the mode must not download it."""
    _add_gap(con, "a")
    _issue(con, "a", 0.42)
    meta = wx.forecast_meta(wx.collect_forecast(con, ["MN"]))
    assert meta["file"] == wx.FORECAST_FILE
    assert meta["modeledCats"] == [CAT]
    assert "byCat" not in meta and "modeled" not in meta
    assert len(meta["rampColors"]) == wx.FORECAST_RAMP_STOPS
    assert len(meta["surpriseColors"]) == len(wx.SURPRISE_STOPS) + 1
    assert len(meta["surpriseLabels"]) == len(meta["surpriseColors"])
    assert len(meta["rampColorsDark"]) == len(meta["rampColors"])
    assert len(meta["surpriseColorsDark"]) == len(meta["surpriseColors"])


def test_every_palette_entry_is_a_hex_colour():
    for ramp in (wx.FORECAST_RAMP, wx.FORECAST_RAMP_DARK,
                 wx.SURPRISE_COLORS, wx.SURPRISE_COLORS_DARK):
        assert all(len(c) == 7 and c.startswith("#") for c in ramp)
    # The no-data steps are NOT on either ramp -- a grey that collided with a
    # ramp step would make "not measured" unreadable.
    assert wx.FORECAST_NODATA_COLOR not in wx.FORECAST_RAMP
    assert wx.SURPRISE_NODATA_COLOR not in wx.SURPRISE_COLORS


def test_empty_forecast_has_the_same_keys_as_a_full_one(con):
    """A not-measured state that is missing keys is a not-measured state the
    browser crashes on."""
    _add_gap(con, "a")
    _issue(con, "a", 0.42)
    full = wx.collect_forecast(con, ["MN"])
    empty = wx.empty_forecast("nothing here")
    assert set(empty) <= set(full)
    for block in ("modeled", "realized", "surprise"):
        assert set(empty[block]) <= set(full[block])


def test_dry_run_counts_come_off_the_packed_block(con):
    _add_gap(con, "a")
    _issue(con, "a", 0.42)
    _seen(con, on="2026-08-01")
    _surprise(con)
    rep = wx.forecast_summary(wx.collect_forecast(con, ["MN"]))
    assert rep["modeled"][CAT] == 1
    assert rep["realized"][CAT]["open"] == 1
    assert rep["surprise"][CAT] == 1
    assert rep["issuedMonth"] == "2026-09"


def test_unknown_borough_fails_loud(con):
    with pytest.raises(ValueError, match="unknown borough"):
        wx.collect_forecast(con, ["ZZ"])
