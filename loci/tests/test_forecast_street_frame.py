"""THE STREET FRAME GETS A FORECAST — and the fit does not change (2026-09-16).

Owner ruling (4), 2026-09-16: "frame='street' points get everything the lot
frame has, including a forecast." The audit found all 50,199 street-frame
addresses carrying zero forecast rows, zero demographics and zero bike growth,
surfacing through LEFT JOINs as NULLs and never as an error.

Scoring them is a one-line change and a three-way trap. What is pinned here:

  (a) EVERY STREET ADDRESS GETS A ROW. Not most, not the ones that look
      promising. The owner's 2026-09-13 ruling is that there is no eligibility
      gate and every street is represented; a scoring pass that quietly drops
      the awkward midpoints is that gate wearing a different hat.

  (b) THE FIT UNIVERSE IS UNCHANGED, BYTE FOR BYTE. A street midpoint has no
      PLUTO lot, `units_capped = 0` on every one of them, and its feature
      vector is assembled from what is AROUND it rather than what is under it.
      Letting one into the fit would move every coefficient for a reason that
      is an artefact of point construction. The test fits twice -- once on a
      universe that contains street rows, once on a lot-only universe -- and
      asserts the coefficient dictionaries are identical. This is the
      assertion that would fail if someone "simplified" `_predict_frame` and
      `build_fit_panel` into one call over one frame.

  (c) A MISSING FEATURE RAISES. It is not coalesced to zero, not filled with a
      median, not written as NULL. `frozen_features` fills a NULL
      `retail_index` with the panel median -- harmless on a frame where the
      column is 100% populated, a fabricated feature on one where it is not --
      so the street path refuses BEFORE it gets there. A zero that means "we
      did not look" is indistinguishable from a zero that means "nothing here",
      and the second one is a gap this project would then draw on a map.

  (d) A MEASURED DEFICIENCY IS LABELLED, NOT DROPPED AND NOT HIDDEN. 1,169 of
      the 50,199 street midpoints (2.3%, measured read-only on 2026-09-16) have
      no PLUTO residential units anywhere inside their 400 m disc. That is a
      real property of the place, not an absence of measurement, so the row is
      written -- with `support = 'street_no_homes'`, which says the number in
      `p_opening` came from a logit extrapolating outside the entire fit
      support (every lot row that trains it has homes > 0).

Synthetic in-memory DuckDB throughout. No warehouse, no network.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from loci import db as locidb
from loci.model import forecast as fc

#: Gowanus-ish, same anchor as tests/test_forecast.py. 0.001 deg of longitude
#: is ~84 m here, so the offsets below sit inside and outside a 400 m radius
#: predictably.
LON, LAT = -73.990, 40.675


@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute("""CREATE TABLE analysis.address (
        address_id VARCHAR, lon DOUBLE, lat DOUBLE, nta_code VARCHAR,
        borough VARCHAR, frame VARCHAR, units_capped DOUBLE)""")
    c.execute("""CREATE TABLE analysis.address_character (
        address_id VARCHAR, retail_index DOUBLE)""")
    c.execute("""CREATE TABLE analysis.poi_presence (
        location_key VARCHAR, category VARCHAR, display_name VARCHAR,
        lon DOUBLE, lat DOUBLE, borough VARCHAR,
        first_seen_kind VARCHAR, first_seen_src_field VARCHAR,
        first_seen_src_date DATE, poi_id_latest VARCHAR)""")
    c.execute("CREATE TABLE analysis.poi_supply (poi_id VARCHAR, in_principled BOOLEAN)")
    return c


def add_demographics(con, address_ids):
    """The sibling build's table (`analysis.address_demographics`), stubbed.

    It is NOT read by any of the four features -- `street_frame_readiness`
    declares it a prerequisite for a provenance reason, not an arithmetic one
    -- so the stub carries a key and nothing else. Making it richer would
    imply the model uses it, which it does not."""
    con.execute("CREATE TABLE IF NOT EXISTS analysis.address_demographics "
                "(address_id VARCHAR, population DOUBLE)")
    for aid in address_ids:
        con.execute("INSERT INTO analysis.address_demographics VALUES (?, ?)",
                    [aid, 1000.0])


def add_address(con, aid, lon, lat, *, nta="BK0101", units=100.0, ri=0.4,
                frame="lot", borough="BK"):
    con.execute("INSERT INTO analysis.address VALUES (?,?,?,?,?,?,?)",
                [aid, lon, lat, nta, borough, frame, units])
    if ri is not None:
        con.execute("INSERT INTO analysis.address_character VALUES (?,?)",
                    [aid, ri])


def add_poi(con, key, cat, lon, lat, kind, date, *, principled=True,
            borough="BK"):
    con.execute("INSERT INTO analysis.poi_presence VALUES (?,?,?,?,?,?,?,?,?,?)",
                [key, cat, key, lon, lat, borough, kind, "opened_on", date,
                 f"poi:{key}"])
    con.execute("INSERT INTO analysis.poi_supply VALUES (?,?)",
                [f"poi:{key}", principled])


def build_universe(con, *, n_lot=6, n_street=3, street_ri=0.55,
                   street_far=False):
    """Both frames, overlapping in space so the street midpoints pick up real
    homes from the LOT rows around them -- which is the whole claim about why a
    street midpoint is scoreable at all.

    `street_far=True` puts the street rows 5 km away instead, out of every lot
    disc, which is the `homes = 0` case.
    """
    for i in range(n_lot):
        add_address(con, f"lot{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    offset = 0.06 if street_far else 0.0
    for j in range(n_street):
        add_address(con, f"st{j}", LON + offset + 0.004 * j, LAT + 0.0005,
                    nta=f"BK010{j % 2}", units=0.0, ri=street_ri,
                    frame="street")
    for i in range(8):
        add_poi(con, f"o{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0005, LAT,
                "source_date", dt.date(2023, 5, 1))
        add_poi(con, f"n{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0006, LAT,
                "source_date", dt.date(2024, 5, 1))
    add_demographics(con, [f"st{j}" for j in range(n_street)])


#: THE TARGET CONTRACT, REHEARSED — the same scaffold, and the same expiry
#: date, as `tests/test_forecast.py`. sql/045_forecast_natural_key.sql is the
#: migration lead's file and had not landed when this module was written;
#: skipping every street-frame test until it does would mean the street work
#: shipped with nothing run against it. Duplicated rather than imported across
#: test modules on purpose: a cross-module test import is a rootdir-dependent
#: trick, and this block is meant to be DELETED from both files the day the
#: migration lands, not refactored into a home it will outlive.
#:
#: Nothing here is a second definition of the schema. It is asserted against
#: the module's own column lists by
#: `test_the_rehearsed_ddl_matches_the_modules_column_lists`, and against the
#: real migration by `schema_is_reshaped` the moment that exists.
REHEARSAL_FORECAST_DDL = """
CREATE TABLE analysis.forecast (
    issued_month      VARCHAR NOT NULL,
    horizon_months    INTEGER NOT NULL,
    model_version     VARCHAR NOT NULL,
    address_id        VARCHAR NOT NULL,
    category          VARCHAR NOT NULL,
    frame             VARCHAR NOT NULL DEFAULT 'lot',
    borough           VARCHAR,
    nta_code          VARCHAR,
    surprise_cell     VARCHAR,
    p_opening         DOUBLE  NOT NULL,
    expected_openings DOUBLE  NOT NULL,
    support           VARCHAR NOT NULL
        CHECK (support IN ('fitted', 'pooled', 'street_no_homes')),
    features_hash     VARCHAR NOT NULL,
    frozen_at         TIMESTAMP NOT NULL,
    PRIMARY KEY (issued_month, model_version, address_id, category)
)"""
REHEARSAL_OUTCOME_DDL = """
CREATE TABLE analysis.forecast_outcome (
    issued_month      VARCHAR NOT NULL,
    model_version     VARCHAR NOT NULL,
    address_id        VARCHAR NOT NULL,
    category          VARCHAR NOT NULL,
    scored_month      VARCHAR NOT NULL,
    horizon_elapsed   INTEGER NOT NULL,
    realized_openings INTEGER NOT NULL,
    realized_flag     BOOLEAN NOT NULL,
    scored_at         TIMESTAMP NOT NULL,
    PRIMARY KEY (issued_month, model_version, address_id, category, scored_month)
)"""


def ledger(con, monkeypatch):
    """The ledger on the natural-key contract, real if the migration has been
    applied to this catalogue and rehearsed if it has not. `ensure_schema` is
    neutralised in the rehearsed case because re-running sql/028 would fail at
    `CREATE OR REPLACE VIEW` — DuckDB binds a view's columns at CREATE."""
    fc.ensure_schema(con)
    if fc.schema_is_reshaped(con):
        return con
    con.execute("DROP VIEW IF EXISTS analysis.forecast_surprise_nta")
    con.execute("DROP VIEW IF EXISTS analysis.forecast_latest")
    con.execute("DROP TABLE IF EXISTS analysis.forecast_outcome")
    con.execute("DROP TABLE IF EXISTS analysis.forecast")
    con.execute(REHEARSAL_FORECAST_DDL)
    con.execute(REHEARSAL_OUTCOME_DDL)
    monkeypatch.setattr(fc, "ensure_schema", lambda _c: None)
    return con


KW = {"categories": ("restaurant",), "sample_n": 6}


def test_the_rehearsed_ddl_matches_the_modules_column_lists(con, monkeypatch):
    """The scaffold is only useful if it is the same shape as the thing it
    stands in for. Both tables, in order, against the lists `forecast.py`
    INSERTs through — and the `support` CHECK against the module's own
    vocabulary, since `_write_vintage` refuses an unknown value BEFORE the DDL
    would."""
    ledger(con, monkeypatch)
    for table, expected in (("forecast", fc.FORECAST_INSERT_COLUMNS),
                            ("forecast_outcome",
                             fc.FORECAST_OUTCOME_INSERT_COLUMNS)):
        got = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'analysis' AND table_name = ? "
            "ORDER BY ordinal_position", [table]).fetchall()]
        assert got == list(expected), f"analysis.{table}: {got}"
        assert "forecast_id" not in got and "features_json" not in got
    for value in fc.SUPPORT_VALUES:
        con.execute(
            "INSERT INTO analysis.forecast (issued_month, horizon_months, "
            "model_version, address_id, category, frame, p_opening, "
            "expected_openings, support, features_hash, frozen_at) "
            "VALUES ('2025-01', 12, 'v1', ?, 'restaurant', 'lot', 0.5, 0.5, "
            "?, '0123456789abcdef', now())", [value, value])
    assert con.execute("SELECT count(*) FROM analysis.forecast").fetchone()[0] \
        == len(fc.SUPPORT_VALUES)


# ===========================================================================
# (a) every street address gets a forecast row
# ===========================================================================
def test_every_street_address_has_a_forecast_row_after_issue(con, monkeypatch):
    """The literal ruling. Zero street addresses without a row, in every
    category -- and the row count is the address count times the category
    count, which is the same cross-check the real vintage gets against
    `analysis.address_category` (4,980,615)."""
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    rep = fc.issue(con, "2025-01", **KW)

    missing = con.execute("""
        SELECT count(*) FROM analysis.address a
        WHERE a.frame = 'street'
          AND NOT EXISTS (SELECT 1 FROM analysis.forecast f
                           WHERE f.address_id = a.address_id
                             AND f.frame = 'street')
    """).fetchone()[0]
    assert missing == 0, f"{missing} street addresses have no forecast row"

    by_frame = dict(con.execute(
        "SELECT frame, count(*) FROM analysis.forecast GROUP BY 1").fetchall())
    assert by_frame == {"lot": 6 * 1, "street": 3 * 1}, by_frame
    assert rep["n_rows_issued"] == 9
    assert rep["by_frame"]["street"]["n_addresses"] == 3
    # the frame column says which frame the row IS -- not a module constant
    # applied to every row, which is what it used to be
    assert con.execute("SELECT count(*) FROM analysis.forecast "
                       "WHERE frame NOT IN ('lot','street')").fetchone()[0] == 0


def test_the_street_rows_carry_the_same_columns_the_lot_rows_do(con, monkeypatch):
    """"Everything the lot frame has" includes the NTA, the variance cell and
    the frozen-input witness. A street row that arrived with a NULL
    `surprise_cell` would silently drop out of `forecast_surprise_nta`'s
    cluster count and quietly shrink the sandwich variance."""
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    fc.issue(con, "2025-01", **KW)
    bad = con.execute("""
        SELECT count(*) FROM analysis.forecast
        WHERE frame = 'street'
          AND (nta_code IS NULL OR surprise_cell IS NULL
               OR features_hash IS NULL OR borough IS NULL
               OR p_opening IS NULL OR expected_openings IS NULL)
    """).fetchone()[0]
    assert bad == 0


# ===========================================================================
# (b) the fit universe did not move
# ===========================================================================
def test_the_coefficients_are_identical_to_a_lot_only_fit(con, monkeypatch):
    """THE ONE THAT PROTECTS THE MODEL. Same warehouse, same month, same seed:
    fitting with the street frame present in `analysis.address` must produce
    the same coefficients as fitting on a universe that has no street rows at
    all, because `build_fit_panel` reads `FIT_FRAME` and nothing else.

    Compared as a dict of floats rather than "close enough": these are the same
    computation on the same rows, so anything other than equality means a
    street row reached the design matrix."""
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    with_street = fc.issue(con, "2025-01", dry_run=True, **KW)

    lot_only = locidb.connect(":memory:")
    lot_only.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    for t in ("address", "address_character", "poi_presence", "poi_supply"):
        cols = con.execute(f"DESCRIBE analysis.{t}").fetchdf()
        decl = ", ".join(f"{r.column_name} {r.column_type}"
                         for r in cols.itertuples())
        lot_only.execute(f"CREATE TABLE analysis.{t} ({decl})")
    rows = con.execute("SELECT * FROM analysis.address WHERE frame = 'lot'").fetchdf()
    lot_only.register("_a", rows)
    lot_only.execute("INSERT INTO analysis.address SELECT * FROM _a")
    for t in ("address_character", "poi_presence", "poi_supply"):
        src = con.execute(f"SELECT * FROM analysis.{t}").fetchdf()
        lot_only.register("_t", src)
        lot_only.execute(f"INSERT INTO analysis.{t} SELECT * FROM _t")
        lot_only.unregister("_t")
    fc.ensure_schema(lot_only)
    without = fc.issue(lot_only, "2025-01", dry_run=True,
                       score_frames=("lot",), **KW)

    # Compared through `json.dumps`, not with `==`. A separated logit reports
    # `se = nan` for a perfectly-separated term, and `nan != nan`, so a plain
    # dict comparison fails on two IDENTICAL fits and would have been "fixed"
    # by loosening it to approximate equality -- which is exactly the assertion
    # that must stay exact here.
    assert (json.dumps(with_street["fit"]["coefficients"], sort_keys=True,
                       default=str)
            == json.dumps(without["fit"]["coefficients"], sort_keys=True,
                          default=str))
    assert with_street["fit"]["n_rows"] == without["fit"]["n_rows"]
    assert with_street["fit"]["n_addresses"] == without["fit"]["n_addresses"]
    assert with_street["fit"]["n_ntas"] == without["fit"]["n_ntas"]
    assert with_street["support"] == without["support"]
    # `repr` for the same reason as `json.dumps` above: a fixture this small
    # can leave the blocked-CV AUC undefined, and `nan != nan`.
    assert (repr(with_street["fit"]["auc_blocked"])
            == repr(without["fit"]["auc_blocked"]))
    # ...and the PREDICTION did grow, or the assertion above is vacuous
    assert with_street["n_rows_predicted"] > without["n_rows_predicted"]
    lot_only.close()


def test_the_lot_block_is_unchanged_by_the_street_frame_being_scored(con, monkeypatch):
    """The street frame is additive on the prediction side too. The same lot
    address must get the same probability whether or not the street frame was
    scored in the same pass -- if it did not, the two frames would be sharing
    something they must not (the retail_index median fill is the live risk,
    which is why `_predict_frame` scores them in separate calls)."""
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    both = fc.issue(con, "2025-01", dry_run=True, **KW)["_pred"]
    lot = fc.issue(con, "2025-01", dry_run=True, score_frames=("lot",),
                   **KW)["_pred"]

    a = (both[both["frame"] == "lot"]
         .set_index(["point_id", "category"])["p_opening"].sort_index())
    b = lot.set_index(["point_id", "category"])["p_opening"].sort_index()
    assert list(a.index) == list(b.index)
    assert (a == b).all(), "scoring the street frame moved a lot probability"


def test_issue_refuses_to_score_the_street_frame_alone(con, monkeypatch):
    """A vintage that scored street rows and not lot rows would be a model
    applied only where it was never fitted."""
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    with pytest.raises(ValueError, match="omits the fit frame"):
        fc.issue(con, "2025-01", score_frames=("street",), **KW)


# ===========================================================================
# (c) a missing feature raises -- it is never coalesced
# ===========================================================================
def test_a_street_row_with_a_null_required_feature_raises(con, monkeypatch):
    """`retail_index` is a MODEL FEATURE and the only one of the four that is
    read off the address rather than computed from its coordinates.
    `frozen_features` would fill a NULL with the panel median. On a frame where
    the column is 100% populated that fill never fires; on one where it is not,
    it invents a feature value and the resulting `p_opening` is arithmetic on a
    number nobody measured."""
    build_universe(con, n_lot=6, n_street=3)
    con.execute("DELETE FROM analysis.address_character WHERE address_id = 'st1'")
    ledger(con, monkeypatch)
    with pytest.raises(fc.StreetFrameNotReadyError, match="retail_index"):
        fc.issue(con, "2025-01", **KW)
    assert con.execute("SELECT count(*) FROM analysis.forecast").fetchone()[0] == 0


def test_issue_refuses_street_rows_while_the_demographics_build_is_missing(con, monkeypatch):
    """The sibling build (`analysis.address_demographics` for the 50,199 street
    rows) had not landed on 2026-09-16. Nothing in FEATURE_LIST reads it, so
    this refusal is a PROVENANCE rule, not an arithmetic one: a vintage is a
    frozen claim about a warehouse state, and issuing the first street rows
    against a half-built street frame produces a vintage nobody can re-derive
    once the other half arrives.

    The refusal names the table and offers the lot-only escape, because a wall
    with no door is how a guard gets deleted."""
    build_universe(con, n_lot=6, n_street=3)
    con.execute("DROP TABLE analysis.address_demographics")
    ledger(con, monkeypatch)
    with pytest.raises(fc.StreetFrameNotReadyError,
                       match="address_demographics"):
        fc.issue(con, "2025-01", **KW)

    # the lot frame is still issuable while the sibling build is in flight
    rep = fc.issue(con, "2025-01", score_frames=("lot",), **KW)
    assert rep["n_rows_issued"] == 6
    assert con.execute("SELECT count(*) FROM analysis.forecast "
                       "WHERE frame = 'street'").fetchone()[0] == 0


def test_partial_demographics_coverage_is_refused_not_averaged(con, monkeypatch):
    """Two of three covered is not "mostly ready". It is a frame where a third
    of the rows would be provenanced differently from the rest, with nothing on
    the row to say which."""
    build_universe(con, n_lot=6, n_street=3)
    con.execute("DELETE FROM analysis.address_demographics WHERE address_id = 'st2'")
    ledger(con, monkeypatch)
    with pytest.raises(fc.StreetFrameNotReadyError, match="covers 2 of 3"):
        fc.issue(con, "2025-01", **KW)


def test_a_warehouse_with_no_street_rows_at_all_is_not_an_error(con, monkeypatch):
    """`score/` and `model/` are meant to be city-agnostic. A second city with
    no street frame has nothing to score on it and nothing to get wrong;
    refusing there would make the street frame a requirement."""
    build_universe(con, n_lot=6, n_street=0)
    con.execute("DROP TABLE IF EXISTS analysis.address_demographics")
    ledger(con, monkeypatch)
    rep = fc.street_frame_readiness(con)
    assert rep["ready"] is True and rep["n_street"] == 0
    assert fc.issue(con, "2025-01", **KW)["n_rows_issued"] == 6


# ===========================================================================
# (d) a measured deficiency is labelled, not dropped
# ===========================================================================
def test_a_street_midpoint_with_no_homes_in_its_disc_is_labelled_not_dropped(con, monkeypatch):
    """1,169 of 50,199 street midpoints (2.3%) have zero PLUTO residential
    units inside 400 m -- parks, water edges, industrial strips. The row is
    WRITTEN, because dropping it is the eligibility gate the owner forbade on
    2026-09-13, and it is LABELLED, because `log_homes` and `supply_ratio` both
    collapse to their zero-information value there and the logit is
    extrapolating outside its entire fit support.

    Both halves are asserted. A label with the row dropped, or the row with no
    label, each fails one of the two rulings."""
    build_universe(con, n_lot=6, n_street=3, street_far=True)
    ledger(con, monkeypatch)
    rep = fc.issue(con, "2025-01", **KW)

    rows = con.execute("""
        SELECT address_id, support, p_opening FROM analysis.forecast
        WHERE frame = 'street' ORDER BY address_id
    """).fetchall()
    assert len(rows) == 3, "a zero-homes street midpoint was dropped"
    assert {r[1] for r in rows} == {fc.SUPPORT_STREET_NO_HOMES}
    assert all(r[2] is not None for r in rows), "p_opening went NULL"
    assert rep["by_frame"]["street"]["n_street_no_homes"] == 3


def test_a_street_midpoint_with_homes_is_scored_normally(con, monkeypatch):
    """The label is for the deficiency, not for the frame. A street midpoint
    surrounded by lots gets a real `fitted`/`pooled` row, exactly as a lot
    address does -- 47.7k of the 50,199 in production."""
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    fc.issue(con, "2025-01", **KW)
    got = {r[0] for r in con.execute(
        "SELECT DISTINCT support FROM analysis.forecast WHERE frame = 'street'"
    ).fetchall()}
    assert got <= {"fitted", "pooled"}, got
    assert fc.SUPPORT_STREET_NO_HOMES not in got


def test_the_support_vocabulary_is_closed(con, monkeypatch):
    """`analysis.forecast.support` carries a CHECK. A value outside it must be
    refused by this module BEFORE the DDL refuses it, so the error names the
    prediction block rather than a constraint."""
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    rep = fc.issue(con, "2025-01", dry_run=True, **KW)
    pred = rep["_pred"].copy()
    pred.loc[pred.index[0], "support"] = "improvised"
    with pytest.raises(ValueError, match="outside"):
        fc._write_vintage(con, pred, month="2025-01",
                          version=rep["model_version"], horizon=12,
                          t0=dt.date(2025, 1, 1))


def test_a_null_feature_in_the_prediction_block_is_refused_at_the_write(con, monkeypatch):
    """The last gate. `features_hash` is built by string concatenation and ONE
    NULL term makes the whole expression NULL, so a NULL feature would arrive
    as `features_hash = NULL` and be rejected by a NOT NULL constraint naming
    the wrong column. This says it where the cause is in scope."""
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    rep = fc.issue(con, "2025-01", dry_run=True, **KW)
    pred = rep["_pred"].copy()
    pred.loc[pred.index[0], "retail_index"] = None
    with pytest.raises(ValueError, match="retail_index"):
        fc._write_vintage(con, pred, month="2025-01",
                          version=rep["model_version"], horizon=12,
                          t0=dt.date(2025, 1, 1))


# ===========================================================================
# the fit frame is not reachable through a default
# ===========================================================================
def test_load_points_defaults_to_the_fit_frame_and_the_score_frames_include_street():
    assert fc.FIT_FRAME == "lot"
    assert fc.SCORE_FRAMES == ("lot", "street")
    assert fc.FIT_FRAME in fc.SCORE_FRAMES


def test_an_unknown_score_frame_is_refused(con, monkeypatch):
    build_universe(con, n_lot=6, n_street=3)
    ledger(con, monkeypatch)
    with pytest.raises(ValueError, match="unknown score frame"):
        fc.issue(con, "2025-01", score_frames=("lot", "rooftop"), **KW)
