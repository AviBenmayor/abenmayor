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
            borough="Brooklyn"):
    con.execute("INSERT INTO analysis.poi_presence VALUES (?,?,?,?,?,?,?,?,?,?)",
                [key, cat, key, lon, lat, borough, kind, "opened_on", date,
                 f"poi:{key}"])
    con.execute("INSERT INTO analysis.poi_supply VALUES (?,?)",
                [f"poi:{key}", principled])


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


def test_scoring_refuses_an_as_of_that_is_not_after_the_issue_month(con):
    add_address(con, "a1", LON, LAT)
    fc.ensure_schema(con)
    con.execute("""INSERT INTO analysis.forecast VALUES
        ('f1','2023-01',12,'0.1.0+abcdabcd','a1','restaurant','lot','BK','BK0101',
         '0:0',0.5,0.5,'pooled','{}', now())""")
    with pytest.raises(ValueError, match="no window to score"):
        fc.score(con, "2023-01", as_of="2023-01", dry_run=True)


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


def test_issuing_the_same_vintage_twice_replaces_it_and_changes_nothing(con):
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

    kw = {"categories": ("restaurant",), "sample_n": 6}
    first = fc.issue(con, "2025-01", **kw)
    rows1 = con.execute("SELECT forecast_id, p_opening FROM analysis.forecast "
                        "ORDER BY forecast_id").fetchdf()
    second = fc.issue(con, "2025-01", **kw)
    rows2 = con.execute("SELECT forecast_id, p_opening FROM analysis.forecast "
                        "ORDER BY forecast_id").fetchdf()

    assert first["model_version"] == second["model_version"]
    assert len(rows1) == len(rows2) == first["n_rows_issued"]
    pd.testing.assert_frame_equal(rows1, rows2)
    assert con.execute("SELECT count(*) FROM analysis.forecast_run").fetchone()[0] == 1


def test_a_second_model_version_lands_beside_the_first_not_over_it(con):
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
    fc.ensure_schema(con)
    rows = []
    for i, (cell, realized) in enumerate(
            [("0:0", 1), ("0:0", 1), ("1:0", 1), ("2:0", 1),
             ("3:0", 0), ("4:0", 0), ("5:0", 0)]):
        rows.append((f"f{i}", cell, 0.5, bool(realized)))
    for fid, cell, p, realized in rows:
        con.execute("""INSERT INTO analysis.forecast VALUES
            (?, '2023-01', 12, 'v1', ?, 'restaurant', 'lot', 'BK', 'BK0101',
             ?, ?, ?, 'pooled', '{}', now())""",
                    [fid, f"addr-{fid}", cell, p, p])
        con.execute("""INSERT INTO analysis.forecast_outcome VALUES
            (?, '2024-01', 12, ?, ?, now())""",
                    [fid, 1 if realized else 0, realized])
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


def test_the_z_is_null_below_five_clusters(con):
    """A sandwich variance from three clusters is not an estimate, and NULL says
    so where a small number would have been read as a small z."""
    fc.ensure_schema(con)
    for i in range(3):
        con.execute("""INSERT INTO analysis.forecast VALUES
            (?, '2023-01', 12, 'v1', ?, 'restaurant', 'lot', 'BK', 'BK0102',
             ?, 0.5, 0.5, 'pooled', '{}', now())""",
                    [f"g{i}", f"addr-g{i}", f"{i}:9"])
        con.execute("""INSERT INTO analysis.forecast_outcome VALUES
            (?, '2024-01', 12, 1, true, now())""", [f"g{i}"])
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
    fc.ensure_schema(con)
    for month, p in (("2023-01", 0.20), ("2026-09", 0.44)):
        con.execute("""INSERT INTO analysis.forecast VALUES
            (?, ?, 12, 'v1', 'a1', 'restaurant', 'lot', 'BK', 'BK0101', '0:0',
             ?, ?, 'fitted', '{"sr":1.0}', now())""",
                    [f"f-{month}", month, p, p])
    con.execute("""INSERT INTO analysis.forecast_outcome VALUES
        ('f-2023-01', '2024-01', 12, 3, true, now())""")

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
    fc.ensure_schema(con)
    for version, frozen, p_open in (("0.1.1+f1cb6628", "2026-09-14 23:26:50", 0.31),
                                    ("0.1.1+51bab17f", "2026-09-15 17:53:22", 0.11)):
        con.execute("""INSERT INTO analysis.forecast VALUES
            (?, '2026-09', 12, ?, 'a1', 'hardware', 'lot', 'BK', 'BK0101', '0:0',
             ?, ?, 'fitted', '{"sr":1.0}', ?::TIMESTAMP)""",
                    [f"f-2026-09-{version}", version, p_open, p_open, frozen])

    r = con.execute("SELECT model_version, p_opening FROM analysis.forecast_latest"
                    ).fetchone()
    assert r[0] == "0.1.1+51bab17f", "the newest-FROZEN vintage must win the tie"
    assert r[1] == pytest.approx(0.11)


def test_forecast_latest_holds_the_columns_the_webmap_and_the_card_read(con):
    """A view contract is a promise to callers. Pin the column names so a
    rename is a failing test rather than a silently empty panel on a card."""
    fc.ensure_schema(con)
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'forecast_latest'").fetchall()}
    assert {"address_id", "category", "issued_month", "model_version",
            "p_opening", "expected_openings", "support", "features_json",
            "scored_month", "realized_flag", "realized_openings",
            "is_scoreable_now"} <= cols

    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'forecast_surprise_nta'").fetchall()}
    assert {"issued_month", "model_version", "scored_month", "nta_code",
            "category", "n_addresses", "n_cells", "realized", "expected",
            "surprise", "z_naive", "z_clustered"} <= cols


def test_expected_openings_equals_p_and_the_residual_has_one_unit(con):
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
    fc.issue(con, "2025-01", categories=("restaurant",), sample_n=6)
    bad = con.execute("SELECT count(*) FROM analysis.forecast "
                      "WHERE abs(expected_openings - p_opening) > 1e-12").fetchone()[0]
    assert bad == 0


# ===========================================================================
# the failure criterion is stored, not re-judged
# ===========================================================================
def test_a_run_that_fails_the_criterion_is_still_written(con):
    """Deleting a vintage that failed is how a track record becomes a highlight
    reel. A failing fit is written with ships=false and a reason."""
    for i in range(6):
        add_address(con, f"a{i}", LON + 0.004 * i, LAT, nta=f"BK010{i % 2}")
    for i in range(8):
        add_poi(con, f"o{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0005, LAT,
                "source_date", dt.date(2023, 5, 1))
        add_poi(con, f"n{i}", "restaurant", LON + 0.004 * (i % 6) + 0.0006, LAT,
                "source_date", dt.date(2024, 5, 1))
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


def test_due_for_scoring_only_returns_vintages_whose_horizon_has_elapsed(con):
    fc.ensure_schema(con)
    for month in ("2023-01", "2026-09"):
        con.execute("""INSERT INTO analysis.forecast VALUES
            (?, ?, 12, 'v1', 'a1', 'restaurant', 'lot', 'BK', 'BK0101', '0:0',
             0.5, 0.5, 'pooled', '{}', now())""", [f"f-{month}", month])
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


def test_guard_reissue_refuses_an_existing_vintage_without_force(con):
    """`loci forecast issue` must not silently overwrite a vintage that
    already has a forecast_run row. `--force` is the explicit override;
    a different (month, version) is never blocked."""
    fc.ensure_schema(con)
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
def _prune_fixture(con):
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
    fc.ensure_schema(con)
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
            fid = f"f-{month}-{i}"
            con.execute("""INSERT INTO analysis.forecast VALUES
                (?, ?, ?, 'v1', ?, 'restaurant', 'lot', 'BK', 'BK0101', '0:0',
                 0.3, 0.3, 'pooled', '{}', now())""",
                        [fid, month, horizon, f"addr-{month}-{i}"])
            if scored:
                scored_month = fc.month_str(
                    fc.add_months(fc.month_first(month), horizon))
                con.execute("""INSERT INTO analysis.forecast_outcome VALUES
                    (?, ?, ?, 0, false, now())""",
                            [fid, scored_month, horizon])
    return vintages


def test_prune_keeps_open_horizon_and_unscored_vintages_and_never_touches_outcomes_or_runs(con):
    _prune_fixture(con)
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


def test_prune_dry_run_deletes_nothing(con):
    _prune_fixture(con)
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
