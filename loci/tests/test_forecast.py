"""The forecast ledger: leakage, vintage idempotence, scoring-window boundaries,
the surprise z, and the view contract.

No network, no warehouse. Every case runs against a SYNTHETIC in-memory DuckDB
built row by row here, because what is worth pinning is boundaries and
invariants, not magnitudes:

  * NOTHING DATED ON OR AFTER THE ISSUE MONTH may enter a frozen feature. This
    is the one that matters. A forecast whose inputs know the future is not a
    forecast, and the failure would look exactly like skill.
  * A VINTAGE IS IDEMPOTENT PER (issued_month, model_version). Re-running the
    same model on the same month must reproduce that month's answer byte for
    byte -- same ids, same probabilities, same row count -- or the track record
    is a record of when the job last ran.
  * THE SCORING WINDOW IS HALF-OPEN [issue, issue + elapsed). An opening on the
    first day of the issue month counts; one the day before does not; one on
    the first day of the scoring month does not.
  * THE SURPRISE Z IS CLUSTER-ROBUST. Its variance comes from the between-cell
    sum of squared residual sums, and on a hand-built fixture it equals the
    hand-computed value. The naive z must be LARGER on positively correlated
    cells -- that gap is the design effect, and if the two ever agreed the
    clustering would have stopped working.
  * THE MODEL VERSION IS A FUNCTION OF THE MODEL. Change the feature list and
    the hash must change, or two different models can share a version and the
    ledger's central promise is void.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from loci import db as locidb
from loci.model import forecast as fc

#: Gowanus-ish. At this latitude 0.001 deg of longitude is ~84 m, so the offsets
#: below sit comfortably inside and outside a 400 m radius.
LON, LAT = -73.990, 40.675


# ---------------------------------------------------------------------------
# a minimal warehouse: the four tables the module reads
# ---------------------------------------------------------------------------
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


def add_address(con, aid, lon, lat, *, nta="BK0101", units=100.0, ri=0.4,
                frame="lot", borough="BK"):
    con.execute("INSERT INTO analysis.address VALUES (?,?,?,?,?,?,?)",
                [aid, lon, lat, nta, borough, frame, units])
    con.execute("INSERT INTO analysis.address_character VALUES (?,?)", [aid, ri])


def add_poi(con, key, cat, lon, lat, kind, date, *, principled=True,
            borough="BK"):
    con.execute("INSERT INTO analysis.poi_presence VALUES (?,?,?,?,?,?,?,?,?,?)",
                [key, cat, key, lon, lat, borough, kind, "opened_on", date,
                 f"poi:{key}"])
    con.execute("INSERT INTO analysis.poi_supply VALUES (?,?)",
                [f"poi:{key}", principled])


# ---------------------------------------------------------------------------
# the ledger, on the NATURAL-KEY contract (sql/045, 2026-09-16)
# ---------------------------------------------------------------------------
#: THE TARGET CONTRACT, REHEARSED. sql/045_forecast_natural_key.sql is owned by
#: the migration lead and had not landed when this module was written. Without
#: it every ledger test here would SKIP, and "30 skipped" is not evidence that
#: the module's SQL is right -- it is evidence that nothing ran. So when the
#: real migration is absent these two statements stand in for it, and the
#: moment it lands `schema_is_reshaped` is true, this block is never reached,
#: and it should be deleted. It is a scaffold with an expiry date, not a second
#: definition of the schema: `test_forecast_latest_holds_the_columns...` still
#: skips, because the VIEWS come from sql/028 and nothing here can rehearse a
#: view contract without becoming the thing it is supposed to be testing.
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
    """The ledger tables on the NATURAL-KEY contract (sql/045, 2026-09-16).

    `analysis.forecast` lost `forecast_id` and `features_json` and gained
    `features_hash`; `analysis.forecast_outcome` lost `forecast_id` for the
    four natural-key columns. If the warehouse in front of us already has that
    -- asked of the CATALOGUE, never of the filesystem, because what matters is
    whether the migration was APPLIED -- this is just `ensure_schema`.

    Otherwise it rehearses the two tables and neutralises `ensure_schema`,
    which would otherwise re-run sql/028 and fail at `CREATE OR REPLACE VIEW`
    (DuckDB binds a view's columns at CREATE, verified). `monkeypatch` undoes
    that after the test.
    """
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


def ledger_with_views(con):
    """For the cases that test sql/028's VIEWS -- `forecast_latest` and
    `forecast_surprise_nta`. There is nothing honest to rehearse here: a
    hand-copied view in this file would be testing the copy. SKIPS until the
    migration lands."""
    fc.ensure_schema(con)
    if not fc.schema_is_reshaped(con):
        pytest.skip(
            "analysis.forecast is still on the forecast_id / features_json "
            "contract, so sql/028's two VIEWS still select the dropped "
            "columns. sql/045_forecast_natural_key.sql and the sql/028 edit "
            "are owned by the migration lead and have not landed in this tree.")
    return con


#: Every column of analysis.forecast, in DDL order, NAMED. The tests write the
#: ledger the same way the module does -- through a column list -- so that a
#: future column reorder cannot make a test fixture quietly disagree with
#: production about which value is `frame` and which is `borough`.
FORECAST_COLS = ("issued_month", "horizon_months", "model_version",
                 "address_id", "category", "frame", "borough", "nta_code",
                 "surprise_cell", "p_opening", "expected_openings", "support",
                 "features_hash", "frozen_at")
OUTCOME_COLS = ("issued_month", "model_version", "address_id", "category",
                "scored_month", "horizon_elapsed", "realized_openings",
                "realized_flag", "scored_at")

#: A stand-in pre-image hash. Sixteen hex characters, the width
#: `fc.FEATURES_HASH_CHARS` fixes; no test here asserts anything about its
#: VALUE except in `test_features_hash_*`, which computes it for real.
HASH16 = "0123456789abcdef"


def ins_forecast(con, *, issued_month, address_id, category="restaurant",
                 model_version="v1", horizon=12, frame="lot", borough="BK",
                 nta="BK0101", cell="0:0", p=0.5, support="pooled",
                 features_hash=HASH16, frozen_at=None):
    con.execute(
        f"INSERT INTO analysis.forecast ({', '.join(FORECAST_COLS)}) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, COALESCE(?::TIMESTAMP, now()))",
        [issued_month, horizon, model_version, address_id, category, frame,
         borough, nta, cell, p, p, support, features_hash, frozen_at])


def ins_outcome(con, *, issued_month, address_id, scored_month,
                category="restaurant", model_version="v1", elapsed=12,
                realized=0, flag=None):
    con.execute(
        f"INSERT INTO analysis.forecast_outcome ({', '.join(OUTCOME_COLS)}) "
        "VALUES (?,?,?,?,?,?,?,?, now())",
        [issued_month, model_version, address_id, category, scored_month,
         elapsed, realized, bool(realized > 0) if flag is None else flag])


# ===========================================================================
# THE LEAKAGE TEST -- the one that matters
# ===========================================================================
def test_a_location_first_seen_after_the_issue_month_cannot_enter_the_features(con):
    """A competitor dated 2026-03 must be invisible to a 2026-01 vintage.

    If it were counted, `supply_ratio` at issue would already reflect openings
    that had not happened, and the model would be predicting its own right-hand
    side. The failure mode looks like an excellent AUC."""
    add_address(con, "a1", LON, LAT)
    add_poi(con, "before", "restaurant", LON + 0.001, LAT, "source_date",
            dt.date(2025, 6, 1))
    add_poi(con, "after", "restaurant", LON + 0.0011, LAT, "source_date",
            dt.date(2026, 3, 1))
    add_poi(con, "on_the_day", "restaurant", LON + 0.0012, LAT, "source_date",
            dt.date(2026, 1, 1))

    pts = fc.load_points(con)
    f = fc.frozen_features(con, pts, fc.month_first("2026-01"),
                           anchors={"restaurant": 1.0}, categories=("restaurant",))
    supply = int(f.loc[f["category"] == "restaurant", "supply"].iloc[0])

    # 'before' counts. 'on_the_day' counts -- `supply_as_of` is <= t0 and t0 is
    # the FIRST day of the issue month, so a location whose source date is that
    # very day existed when the shutter of the forecast closed. 'after' must not.
    assert supply == 2, f"a location dated after the issue month leaked (supply={supply})"


def test_the_fit_folds_both_close_before_the_issue_month(con):
    """The fit-window rule, asserted as arithmetic rather than trusted as prose."""
    t0s = fc.fit_t0s("2026-09", horizon=12)
    assert t0s == [dt.date(2024, 9, 1), dt.date(2025, 9, 1)]
    for t0 in t0s:
        assert fc.add_months(t0, 12) <= fc.month_first("2026-09"), (
            "a training fold's outcome window runs into the issue month")


def test_build_fit_panel_refuses_a_fold_that_runs_past_the_issue_month(con, monkeypatch):
    """The guard is not decorative, and it is the last line of defence.

    `fit_t0s` and the outcome window are derived from the same horizon, so
    under the shipped rule the guard can never fire. That is exactly why it is
    tested by breaking the rule: if a later session changes the fold origins
    and forgets the horizon, this is the assertion that turns a silently
    leaking model into a crash."""
    add_address(con, "a1", LON, LAT)
    monkeypatch.setattr(fc, "fit_t0s",
                        lambda month, horizon=12: [fc.add_months(fc.month_first(month), -6)])
    with pytest.raises(ValueError, match="leakage"):
        fc.build_fit_panel(con, "2026-09", horizon=12, categories=("restaurant",))


def test_the_outcome_window_never_sees_a_censored_row(con):
    """D79's undated 40% can never be an opening. They are not openings; they
    are locations that already existed. The consequence -- a realized rate that
    is a uniform lower bound -- is stated in sql/028, not hidden."""
    add_address(con, "a1", LON, LAT)
    add_poi(con, "undated", "restaurant", LON + 0.001, LAT, "backfill_censored", None)
    got = fc.openings_between(con, fc.load_points(con), dt.date(2023, 1, 1),
                              dt.date(2024, 1, 1), categories=("restaurant",))
    assert got.empty or int(got["n"].sum()) == 0


# ===========================================================================
# scoring-window boundaries
# ===========================================================================
@pytest.mark.parametrize("date,counts", [
    (dt.date(2022, 12, 31), False),   # the day before the issue month: out
    (dt.date(2023, 1, 1), True),      # the first day of the issue month: in
    (dt.date(2023, 12, 31), True),    # the last day of the horizon: in
    (dt.date(2024, 1, 1), False),     # the first day of the scoring month: out
])
def test_the_scoring_window_is_half_open(con, date, counts):
    """[first day of issued_month, first day of issued_month + elapsed).

    Half-open at both ends and asserted at all four boundaries, because an
    off-by-one month here would move every realized rate in the track record
    and nothing else would notice."""
    add_address(con, "a1", LON, LAT)
    add_poi(con, "x", "restaurant", LON + 0.001, LAT, "source_date", date)
    got = fc.openings_between(con, fc.load_points(con),
                              fc.month_first("2023-01"), fc.month_first("2024-01"),
                              categories=("restaurant",))
    n = 0 if got.empty else int(got["n"].sum())
    assert (n == 1) is counts, f"{date} counted={n}, expected {counts}"


def test_scoring_refuses_an_as_of_that_is_not_after_the_issue_month(con, monkeypatch):
    add_address(con, "a1", LON, LAT)
    ledger(con, monkeypatch)
    ins_forecast(con, issued_month="2023-01", model_version="0.1.0+abcdabcd",
                 address_id="a1")
    with pytest.raises(ValueError, match="no window to score"):
        fc.score(con, "2023-01", as_of="2023-01", dry_run=True)


def test_scoring_writes_one_outcome_row_per_forecast_and_rescoring_replaces_it(con, monkeypatch):
    """THE SCORING ROUND TRIP on the natural key, end to end.

    `forecast_outcome` lost `forecast_id`; the four key columns it used to
    concatenate are on the row itself now, and the DELETE that makes a re-score
    idempotent names them instead of re-scanning the 25M-row forecast table for
    a vintage it was handed as an argument. Three things are asserted and all
    three would have been satisfied by a join that silently fanned out:

      * one outcome row per forecast row, not more (a wrong join key would
        multiply them, and every realized rate downstream with them);
      * ZERO IS A REAL OBSERVATION -- the row exists for the discs that saw
        nothing, because a calibration curve without a denominator is not one;
      * re-scoring the same (vintage, as-of) REPLACES; it does not accumulate.
    """
    for i in range(6):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    for i in range(8):
        add_poi(con, f"o{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0005, LAT,
                "source_date", dt.date(2023, 5, 1))
    ledger(con, monkeypatch)
    rep = fc.issue(con, "2025-01", categories=("restaurant",), sample_n=6)
    n_fc = rep["n_rows_issued"]
    assert n_fc == 6

    # one same-category opening inside a0's disc, inside the horizon
    add_poi(con, "hit", "restaurant", LON + 0.0005, LAT, "source_date",
            dt.date(2025, 6, 1))
    fc.score(con, "2025-01", as_of="2026-01")

    rows = con.execute("""
        SELECT count(*), count(DISTINCT (issued_month, model_version,
                                         address_id, category)),
               sum(CASE WHEN realized_flag THEN 1 ELSE 0 END)
        FROM analysis.forecast_outcome
    """).fetchone()
    assert rows[0] == n_fc, "outcome rows fanned out against the forecast"
    assert rows[1] == n_fc
    assert rows[2] >= 1, "the opening inside the horizon was not realized"

    # every outcome row joins back to exactly one forecast row
    fan = con.execute(f"""
        SELECT count(*) FROM analysis.forecast f
        JOIN analysis.forecast_outcome o
               ON {fc._key_join('o', 'f')}
    """).fetchone()[0]
    assert fan == n_fc

    fc.score(con, "2025-01", as_of="2026-01")
    assert con.execute("SELECT count(*) FROM analysis.forecast_outcome"
                       ).fetchone()[0] == n_fc, "re-scoring accumulated"

    # a SECOND as-of is a different row on the same forecasts, not a correction
    fc.score(con, "2025-01", as_of="2027-01")
    assert con.execute("SELECT count(*) FROM analysis.forecast_outcome"
                       ).fetchone()[0] == 2 * n_fc
    assert {r[0] for r in con.execute(
        "SELECT DISTINCT horizon_elapsed FROM analysis.forecast_outcome"
    ).fetchall()} == {12, 24}

    tr = fc.track_record(con)
    assert {r["scored_month"] for r in tr} == {"2026-01", "2027-01"}
    assert all(r["n"] == n_fc for r in tr), (
        "track_record's count is not one row per forecast -- the join fanned out")


# ===========================================================================
# vintage idempotence and the version discipline
# ===========================================================================
def test_the_model_version_changes_when_the_feature_list_changes():
    """Two runs that share a version must share a model. Nothing enforces that
    except this: the hash covers the feature list, the window rule, the horizon,
    the radius and the support floor."""
    a = fc.model_version()
    b = fc.model_version(features=("log_score", "log_homes"))
    c = fc.model_version(horizon=24)
    d = fc.model_version(radius_m=800.0)
    assert a != b and a != c and a != d
    assert a == fc.model_version(), "the version is not deterministic"
    assert a.startswith(fc.MODEL_SEMVER + "+")


def test_issuing_the_same_vintage_twice_replaces_it_and_changes_nothing(con, monkeypatch):
    """DELETE + INSERT per (issued_month, model_version). Re-running the same
    model on the same month reproduces that month's answer; it does not
    accumulate, and it does not drift."""
    for i in range(6):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    for i in range(8):
        add_poi(con, f"old{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0005, LAT,
                "source_date", dt.date(2023, 5, 1))
        add_poi(con, f"new{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0006, LAT,
                "source_date", dt.date(2024, 5, 1))

    ledger(con, monkeypatch)
    kw = {"categories": ("restaurant",), "sample_n": 6}
    # THE NATURAL KEY IS THE ORDER, and it is also the identity now. This used
    # to `ORDER BY forecast_id`, a string that concatenated these same four
    # columns; sorting on them directly asserts the same thing without the
    # 257 MiB restatement. `features_hash` is selected too, so idempotence is
    # pinned on the FROZEN INPUTS as well as on the probability -- two runs
    # that agreed on p while disagreeing on what they were looking at would
    # have passed the old assertion.
    order = "ORDER BY issued_month, model_version, address_id, category"
    sel = ("SELECT issued_month, model_version, address_id, category, "
           "p_opening, features_hash FROM analysis.forecast ")
    first = fc.issue(con, "2025-01", **kw)
    rows1 = con.execute(sel + order).fetchdf()
    second = fc.issue(con, "2025-01", **kw)
    rows2 = con.execute(sel + order).fetchdf()

    assert first["model_version"] == second["model_version"]
    assert len(rows1) == len(rows2) == first["n_rows_issued"]
    pd.testing.assert_frame_equal(rows1, rows2)
    assert con.execute("SELECT count(*) FROM analysis.forecast_run").fetchone()[0] == 1


def test_features_hash_witnesses_the_frozen_inputs_and_moves_when_they_do(con, monkeypatch):
    """`features_hash` replaced `features_json` (526 MiB of the 1,292 MiB
    table). What it must still be able to answer is the only question anyone
    asked the blob: DID THESE TWO VINTAGES SEE THE SAME INPUTS?

    So: sixteen lowercase hex characters; identical across a re-issue on an
    unchanged warehouse; and DIFFERENT the moment a competitor appears inside
    the disc, with the address, the category and the model version all
    unchanged. If the third assertion failed, the column would be a decoration
    -- it would say "same inputs" about two rows that saw different ones, and
    dropping features_json would have destroyed information rather than
    restating it."""
    for i in range(6):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    for i in range(8):
        add_poi(con, f"o{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0005, LAT,
                "source_date", dt.date(2023, 5, 1))
        add_poi(con, f"n{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0006, LAT,
                "source_date", dt.date(2024, 5, 1))
    ledger(con, monkeypatch)
    kw = {"categories": ("restaurant",), "sample_n": 6}
    ver = fc.issue(con, "2025-01", **kw)["model_version"]

    sel = ("SELECT address_id, features_hash FROM analysis.forecast "
           "WHERE model_version = ? ORDER BY address_id")
    before = dict(con.execute(sel, [ver]).fetchall())
    assert before, "no rows issued"
    for h in before.values():
        assert len(h) == fc.FEATURES_HASH_CHARS == 16
        assert h == h.lower() and all(c in "0123456789abcdef" for c in h)

    # a NEW competitor, dated well before the issue month, inside a0's disc
    add_poi(con, "extra", "restaurant", LON + 0.0005, LAT, "source_date",
            dt.date(2024, 6, 1))
    fc.issue(con, "2025-01", version=ver, **kw)
    after = dict(con.execute(sel, [ver]).fetchall())

    assert set(after) == set(before), "the re-issue changed the address set"
    assert after["a0"] != before["a0"], (
        "a competitor appeared inside a0's 400 m disc and its features_hash "
        "did not move — the hash is not witnessing the frozen inputs")


def test_a_second_model_version_lands_beside_the_first_not_over_it(con, monkeypatch):
    """The vintage discipline, in one assertion: a new model gets a new version
    and its own rows. A past vintage is never re-issued with a newer model, and
    the only way to make that impossible is to make the two coexist."""
    for i in range(6):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    for i in range(8):
        add_poi(con, f"o{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0005, LAT,
                "source_date", dt.date(2023, 5, 1))
        add_poi(con, f"n{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0006, LAT,
                "source_date", dt.date(2024, 5, 1))
    ledger(con, monkeypatch)
    kw = {"categories": ("restaurant",), "sample_n": 6}
    a = fc.issue(con, "2025-01", **kw)
    b = fc.issue(con, "2025-01", version="9.9.9+deadbeef", **kw)
    got = con.execute("SELECT model_version, count(*) FROM analysis.forecast "
                      "GROUP BY 1 ORDER BY 1").fetchall()
    assert len(got) == 2, "the second version overwrote the first"
    assert {v for v, _ in got} == {a["model_version"], b["model_version"]}


# ===========================================================================
# the surprise z
# ===========================================================================
def _surprise_fixture(con):
    """Six 800 m cells in one NTA. Every p = 0.5; cells 0-2 realize 1, cells 3-5
    realize 0, so the residual sums are +0.5 x3 and -0.5 x3 and the total
    surprise is exactly 0... which would be a boring fixture. So cell 0 gets a
    second address, tipping the total to +0.5."""
    ledger_with_views(con)
    rows = []
    for i, (cell, realized) in enumerate(
            [("0:0", 1), ("0:0", 1), ("1:0", 1), ("2:0", 1),
             ("3:0", 0), ("4:0", 0), ("5:0", 0)]):
        rows.append((f"addr-f{i}", cell, 0.5, bool(realized)))
    for aid, cell, p, realized in rows:
        ins_forecast(con, issued_month="2023-01", address_id=aid, cell=cell, p=p)
        ins_outcome(con, issued_month="2023-01", address_id=aid,
                    scored_month="2024-01", realized=1 if realized else 0,
                    flag=realized)
    return rows


def test_the_surprise_z_is_cluster_robust_and_matches_the_hand_computation(con):
    """z = sum(r) / sqrt(sum over cells of (cell residual sum)^2).

    Hand: cell 0:0 has two addresses at +0.5 -> +1.0; cells 1:0 and 2:0 -> +0.5
    each; cells 3:0, 4:0, 5:0 -> -0.5 each. surprise = 1.0 + 0.5 + 0.5 - 1.5 =
    +0.5. Clustered variance = 1.0^2 + 3 x 0.5^2 + ... = 1.0 + 5 x 0.25 = 2.25,
    so z = 0.5 / 1.5 = 0.3333."""
    _surprise_fixture(con)
    got = con.execute("""
        SELECT n_addresses, n_cells, surprise, z_naive, z_clustered
        FROM analysis.forecast_surprise_nta
        WHERE nta_code = 'BK0101' AND category = '(all)'
    """).fetchone()
    n_addr, n_cells, surprise, z_naive, z_clust = got
    assert n_addr == 7 and n_cells == 6
    assert surprise == pytest.approx(0.5)
    assert z_clust == pytest.approx(0.5 / 1.5, abs=1e-9)
    # naive: sum p(1-p) = 7 * 0.25 = 1.75, z = 0.5 / sqrt(1.75) = 0.378
    assert z_naive == pytest.approx(0.5 / np.sqrt(1.75), abs=1e-9)
    assert abs(z_naive) > abs(z_clust), (
        "the naive z is not larger than the clustered one on positively "
        "correlated cells -- the design effect has gone the wrong way")


def test_the_z_is_null_below_five_clusters(con, monkeypatch):
    """A sandwich variance from three clusters is not an estimate, and NULL says
    so where a small number would have been read as a small z."""
    ledger_with_views(con)
    for i in range(3):
        ins_forecast(con, issued_month="2023-01", address_id=f"addr-g{i}",
                     nta="BK0102", cell=f"{i}:9")
        ins_outcome(con, issued_month="2023-01", address_id=f"addr-g{i}",
                    scored_month="2024-01", realized=1, flag=True)
    row = con.execute("""
        SELECT n_cells, z_clustered FROM analysis.forecast_surprise_nta
        WHERE nta_code = 'BK0102' AND category = '(all)'
    """).fetchone()
    assert row[0] == 3 and row[1] is None


# ===========================================================================
# the view contract
# ===========================================================================
def test_forecast_latest_carries_the_newest_p_beside_the_newest_outcome(con):
    """The card and the map read this view. Its contract: one row per address x
    category, the NEWEST issued probability, and the newest SCORED outcome even
    when that outcome belongs to an older vintage -- because the newest vintage
    is normally unscoreable."""
    ledger_with_views(con)
    for month, p in (("2023-01", 0.20), ("2026-09", 0.44)):
        ins_forecast(con, issued_month=month, address_id="a1", p=p,
                     support="fitted")
    ins_outcome(con, issued_month="2023-01", address_id="a1",
                scored_month="2024-01", realized=3, flag=True)

    row = con.execute("""SELECT issued_month, p_opening, scored_vintage_month,
                                scored_month, realized_flag, realized_openings,
                                p_at_that_vintage, is_scoreable_now
                         FROM analysis.forecast_latest""").fetchdf()
    assert len(row) == 1
    r = row.iloc[0]
    assert r["issued_month"] == "2026-09"
    assert r["p_opening"] == pytest.approx(0.44)
    assert r["scored_vintage_month"] == "2023-01"
    assert r["p_at_that_vintage"] == pytest.approx(0.20)
    assert bool(r["realized_flag"]) is True
    assert int(r["realized_openings"]) == 3


def test_forecast_latest_breaks_a_same_month_tie_on_frozen_at_not_the_version_string(con):
    """2026-09-15 (D112 fallout): two vintages of the SAME month are tied on
    `issued_month`, so the view has to pick one. It used to pick
    `max(model_version)` -- a lexicographic sort on '<semver>+<8 hex>', which
    orders by the HASH. The real pair was '0.1.1+f1cb6628' (frozen 09-14
    23:26) and D112's re-issue '0.1.1+51bab17f' (frozen 09-15 17:53): 'f' >
    '5', so the STALE vintage won and every card and allocator report stamped
    the wrong model version. The tie-break is `frozen_at DESC`."""
    ledger_with_views(con)
    for version, frozen, p_open in (("0.1.1+f1cb6628", "2026-09-14 23:26:50", 0.31),
                                    ("0.1.1+51bab17f", "2026-09-15 17:53:22", 0.11)):
        ins_forecast(con, issued_month="2026-09", address_id="a1",
                     category="hardware", model_version=version, p=p_open,
                     support="fitted", frozen_at=frozen)

    r = con.execute("SELECT model_version, p_opening FROM analysis.forecast_latest"
                    ).fetchone()
    assert r[0] == "0.1.1+51bab17f", "the newest-FROZEN vintage must win the tie"
    assert r[1] == pytest.approx(0.11)


def test_forecast_latest_holds_the_columns_the_webmap_and_the_card_read(con):
    """A view contract is a promise to callers. Pin the column names so a
    rename is a failing test rather than a silently empty panel on a card."""
    ledger_with_views(con)
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'forecast_latest'").fetchall()}
    # `features_json` is GONE from the contract and `features_hash` replaces
    # it. The promise the view makes changed in kind, not only in name: it used
    # to hand a caller the frozen feature VALUES, and it now hands them an
    # equality witness over those values. Both halves are asserted -- the
    # presence of the new column AND the absence of the old one -- because a
    # view that kept emitting `features_json` would mean the 526 MiB never left.
    assert {"address_id", "category", "issued_month", "model_version",
            "p_opening", "expected_openings", "support", "features_hash",
            "scored_month", "realized_flag", "realized_openings",
            "is_scoreable_now"} <= cols
    assert "features_json" not in cols and "forecast_id" not in cols

    base = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'forecast'").fetchall()}
    assert base == set(fc.FORECAST_INSERT_COLUMNS), (
        "analysis.forecast and the module's INSERT column list disagree; one "
        "of sql/045 and forecast.py has moved without the other")
    outcome = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'forecast_outcome'"
    ).fetchall()}
    assert outcome == set(fc.FORECAST_OUTCOME_INSERT_COLUMNS)

    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'forecast_surprise_nta'").fetchall()}
    assert {"issued_month", "model_version", "scored_month", "nta_code",
            "category", "n_addresses", "n_cells", "realized", "expected",
            "surprise", "z_naive", "z_clustered"} <= cols


def test_expected_openings_equals_p_and_the_residual_has_one_unit(con, monkeypatch):
    """The unit choice, pinned. `expected_openings` is p x 1 -- the expected
    number of DISCS-WITH-AN-OPENING contributed by the row, not an expected
    number of storefronts. If it ever became a Poisson rate, the surprise would
    stop being realized minus expected in a shared unit and this assertion is
    where that would surface."""
    for i in range(6):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    for i in range(8):
        add_poi(con, f"o{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0005, LAT,
                "source_date", dt.date(2023, 5, 1))
        add_poi(con, f"n{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0006, LAT,
                "source_date", dt.date(2024, 5, 1))
    ledger(con, monkeypatch)
    fc.issue(con, "2025-01", categories=("restaurant",), sample_n=6)
    bad = con.execute("SELECT count(*) FROM analysis.forecast "
                      "WHERE abs(expected_openings - p_opening) > 1e-12").fetchone()[0]
    assert bad == 0


# ===========================================================================
# the failure criterion is stored, not re-judged
# ===========================================================================
def test_a_run_that_fails_the_criterion_is_still_written(con, monkeypatch):
    """Deleting a vintage that failed is how a track record becomes a highlight
    reel. A failing fit is written with ships=false and a reason."""
    for i in range(6):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    for i in range(8):
        add_poi(con, f"o{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0005, LAT,
                "source_date", dt.date(2023, 5, 1))
        add_poi(con, f"n{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0006, LAT,
                "source_date", dt.date(2024, 5, 1))
    ledger(con, monkeypatch)
    fc.issue(con, "2025-01", categories=("restaurant",), sample_n=6)
    row = con.execute("SELECT ships, ships_reason, n_rows_issued, feature_list, "
                      "fit_window_rule FROM analysis.forecast_run").fetchone()
    assert row[1], "ships_reason is empty — the verdict carries no reason"
    assert row[2] > 0
    assert json.loads(row[3]) == list(fc.FEATURE_LIST)
    # the fit-window rule is stored as PROSE beside the numbers, so a reader in
    # 2028 can reproduce the fold origins without reading this module
    assert "Nothing dated on or after issued_month enters the fit" in row[4]


def test_calibration_gap_is_the_max_absolute_decile_gap():
    cal = [{"decile": 1, "n": 10, "predicted": 0.10, "observed": 0.12},
           {"decile": 2, "n": 10, "predicted": 0.50, "observed": 0.31}]
    assert fc.calibration_max_gap(cal) == pytest.approx(0.19)


def test_due_for_scoring_only_returns_vintages_whose_horizon_has_elapsed(con, monkeypatch):
    ledger(con, monkeypatch)
    for month in ("2023-01", "2026-09"):
        ins_forecast(con, issued_month=month, address_id="a1")
    due = fc.due_for_scoring(con, today=dt.date(2026, 9, 14))
    assert [d[0] for d in due] == ["2023-01"]
    assert due[0][2] == "2024-01"


# ===========================================================================
# the supply-set identity is part of the version (D96, GTM-163 addendum)
# ===========================================================================
def test_the_model_version_changes_when_the_supply_hash_changes():
    """A peer re-fitting the supply baseline (owner ruling 2026-09-14,
    767b28674e30 -> 9a11a2f5...) changes nothing about the feature list or the
    fit-window rule and MUST still change model_version, or a reader could
    see one version standing for two different supply sets."""
    a = fc.model_version(supply_hash="767b28674e30")
    b = fc.model_version(supply_hash="9a11a2f5")
    assert a != b
    assert a == fc.model_version(supply_hash="767b28674e30"), (
        "the version is not deterministic in the supply hash")
    # the closure gate is hashed too, independently of the supply_hash string
    # itself -- redundant with supply_hash's own internals, and hashed again
    # here so a reader of model_version's payload does not have to trust that.
    c = fc.model_version(supply_hash="767b28674e30", gate_closed=True)
    d = fc.model_version(supply_hash="767b28674e30", gate_closed=False)
    assert c != d
    assert a.startswith(fc.MODEL_SEMVER + "+")


def test_guard_reissue_refuses_an_existing_vintage_without_force(con, monkeypatch):
    """`loci forecast issue` must not silently overwrite a vintage that
    already has a forecast_run row. `--force` is the explicit override;
    a different (month, version) is never blocked."""
    ledger(con, monkeypatch)
    con.execute("""INSERT INTO analysis.forecast_run
        (issued_month, model_version, horizon_months, radius_m, fit_t0s,
         fit_window_rule, feature_list, ships, ships_reason, issued_at,
         supply_hash)
        VALUES ('2025-01', 'v1', 12, 400.0, '[]', 'x', '[]', true, 'ok',
                now(), 'abc123')""")

    assert fc.already_issued(con, "2025-01", "v1") is True
    assert fc.already_issued(con, "2025-01", "v2") is False
    assert fc.already_issued(con, "2025-02", "v1") is False

    with pytest.raises(fc.AlreadyIssuedError, match="already exists"):
        fc.guard_reissue(con, "2025-01", "v1")
    fc.guard_reissue(con, "2025-01", "v1", force=True)      # no raise
    fc.guard_reissue(con, "2025-01", "v2")                  # no raise -- new version
    fc.guard_reissue(con, "2025-02", "v1")                  # no raise -- new month


# ===========================================================================
# retention (GTM-163): keep-latest-N-per-model-version, never forecast_run /
# forecast_outcome, never an unscored or open-horizon vintage
# ===========================================================================
def _prune_fixture(con, monkeypatch):
    """Six 'v1' vintages, two rows each. Under a UNIFORM horizon an older
    vintage's horizon always elapses no later than a newer one's, so testing
    the open-horizon protection in ISOLATION from ranking needs a vintage
    whose horizon is itself unusual -- 2019-01 is given a 120-month horizon on
    purpose, so it is both the LOWEST-ranked vintage and still open at the
    fixed `today` the tests pass in.

      2023-01  h=12   scored   rank 0 -- kept by ranking (--keep-vintages 2)
      2022-01  h=12   scored   rank 1 -- kept by ranking
      2021-01  h=12   UNSCORED rank 2 -- kept: never scored
      2020-07  h=12   scored   rank 3 -- PRUNE candidate
      2020-01  h=12   scored   rank 4 -- PRUNE candidate
      2019-01  h=120  scored   rank 5 -- kept: horizon still open at `today`
    """
    ledger(con, monkeypatch)
    vintages = [("2019-01", 120, True), ("2020-01", 12, True),
                ("2020-07", 12, True), ("2021-01", 12, False),
                ("2022-01", 12, True), ("2023-01", 12, True)]
    for month, horizon, scored in vintages:
        con.execute("""INSERT INTO analysis.forecast_run
            (issued_month, model_version, horizon_months, radius_m, fit_t0s,
             fit_window_rule, feature_list, ships, ships_reason, issued_at,
             supply_hash)
            VALUES (?, 'v1', ?, 400.0, '[]', 'x', '[]', true, 'ok', now(),
                    'abc123')""", [month, horizon])
        for i in range(2):
            aid = f"addr-{month}-{i}"
            ins_forecast(con, issued_month=month, address_id=aid,
                         horizon=horizon, p=0.3)
            if scored:
                scored_month = fc.month_str(
                    fc.add_months(fc.month_first(month), horizon))
                ins_outcome(con, issued_month=month, address_id=aid,
                            scored_month=scored_month, elapsed=horizon,
                            realized=0, flag=False)
    return vintages


def test_prunable_vintages_counts_forecast_rows_not_forecast_x_scoring_pairs(con, monkeypatch):
    """THE DOUBLE COUNT, pinned. `prunable_vintages` used to aggregate over
    `forecast LEFT JOIN forecast_outcome`, so `n_rows` counted (forecast row x
    scored_month) pairs. A vintage scored TWICE -- which is what `--as-of`
    exists for, and which sql/028 calls a second row rather than a correction
    -- doubled the row count `prune` prints for a human to authorise.

    Two forecast rows, scored at 12 AND 24 months: n_rows must be 2."""
    ledger(con, monkeypatch)
    for i in range(2):
        ins_forecast(con, issued_month="2020-01", address_id=f"addr-{i}")
        for scored, elapsed in (("2021-01", 12), ("2022-01", 24)):
            ins_outcome(con, issued_month="2020-01", address_id=f"addr-{i}",
                        scored_month=scored, elapsed=elapsed, realized=1)

    got = fc.prunable_vintages(con, keep_vintages=1, today=dt.date(2023, 6, 1))
    assert len(got) == 1
    assert int(got.iloc[0]["n_rows"]) == 2, (
        "n_rows counted forecast x scoring-date pairs, not forecast rows")
    assert bool(got.iloc[0]["has_outcome"]) is True


def test_prune_keeps_open_horizon_and_unscored_vintages_and_never_touches_outcomes_or_runs(con, monkeypatch):
    _prune_fixture(con, monkeypatch)
    today = dt.date(2023, 6, 1)
    n_run_before = con.execute(
        "SELECT count(*) FROM analysis.forecast_run").fetchone()[0]
    n_outcome_before = con.execute(
        "SELECT count(*) FROM analysis.forecast_outcome").fetchone()[0]

    rep = fc.prune(con, keep_vintages=2, dry_run=False, today=today)

    pruned = {r["issued_month"] for r in rep["candidates"]}
    assert pruned == {"2020-01", "2020-07"}, pruned
    assert rep["n_rows"] == 4                # 2 rows x 2 pruned vintages

    kept_outside_window = {r["issued_month"] for r in rep["kept_open_horizon"]}
    assert kept_outside_window == {"2019-01", "2021-01"}, kept_outside_window

    remaining = {r[0] for r in con.execute(
        "SELECT DISTINCT issued_month FROM analysis.forecast").fetchall()}
    assert remaining == {"2019-01", "2021-01", "2022-01", "2023-01"}, remaining

    # THE POINT OF THE TICKET: forecast_run and forecast_outcome are
    # UNTOUCHED. Only analysis.forecast prediction rows are ever deleted.
    assert con.execute("SELECT count(*) FROM analysis.forecast_run"
                       ).fetchone()[0] == n_run_before
    assert con.execute("SELECT count(*) FROM analysis.forecast_outcome"
                       ).fetchone()[0] == n_outcome_before
    assert rep["checkpointed"] is True


def test_prune_dry_run_deletes_nothing(con, monkeypatch):
    _prune_fixture(con, monkeypatch)
    today = dt.date(2023, 6, 1)
    n_before = con.execute(
        "SELECT count(*) FROM analysis.forecast").fetchone()[0]

    rep = fc.prune(con, keep_vintages=2, dry_run=True, today=today)

    assert rep["dry_run"] is True
    assert rep["n_rows"] == 4
    assert {r["issued_month"] for r in rep["candidates"]} == {"2020-01", "2020-07"}
    assert rep["checkpointed"] is False and rep["vacuumed"] is False

    n_after = con.execute(
        "SELECT count(*) FROM analysis.forecast").fetchone()[0]
    assert n_after == n_before, "dry_run=True deleted rows"
