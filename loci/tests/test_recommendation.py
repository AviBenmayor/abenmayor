"""The recommendation ledger (model/recommendation_ledger.py, sql/026).

The load-bearing tests here are the ones a reader cannot check by eye:

  * `test_mutable_and_immutable_partition_the_table` and
    `test_the_only_update_names_only_mutable_columns` hold the append-only
    invariant that DuckDB cannot enforce (no triggers). A column added to
    sql/026 without being classified fails the first; an UPDATE that learns to
    touch a grade fails the second.
  * `test_an_opening_before_the_issue_date_is_not_a_fill` is the adversarial
    case. A gap that was already being filled when we called it a gap is the
    one result that would flatter this project most and mean least.
  * `test_re_running_a_month_reproduces_it` pins the DELETE/INSERT contract
    through the status flip -- the first run marks the row 'filled', and a
    naive re-run would then find nothing open and wipe the month.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from loci import db as locidb
from loci.model import recommendation_ledger as rl

SQL_018 = locidb.SQL_DIR / "018_poi_presence.sql"
SQL_020 = locidb.SQL_DIR / "020_storefront_pipeline.sql"

ISSUED = dt.date(2026, 9, 1)
ANCHOR_LON, ANCHOR_LAT = -73.9885, 40.676

#: ~0.0010 degrees of latitude is ~111 m; 0.0050 is ~555 m, comfortably
#: outside a 400 m disc. Distances are asserted, not assumed, in
#: `test_the_radius_is_a_real_distance`.
NEAR_LAT = ANCHOR_LAT + 0.0010
FAR_LAT = ANCHOR_LAT + 0.0050


# --------------------------------------------------------------- fixtures

@pytest.fixture()
def con():
    """A synthetic warehouse carrying the REAL sql/018 + sql/020 + sql/026
    DDL, so a schema change upstream breaks these tests instead of quietly
    invalidating them."""
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute("CREATE SCHEMA IF NOT EXISTS staging")
    # sql/020 ALTERs analysis.address_category; a stub is enough for the DDL.
    c.execute("CREATE TABLE analysis.address_category ("
              "address_id VARCHAR, category VARCHAR)")
    c.execute(SQL_018.read_text())
    c.execute(SQL_020.read_text())
    c.execute(rl.SQL_026.read_text())
    c.execute("CREATE TABLE analysis.poi_dedup (poi_id VARCHAR, cluster_id BIGINT, "
              "is_canonical BOOLEAN, category VARCHAR)")
    c.execute("CREATE TABLE staging.poi (poi_id VARCHAR, source_id VARCHAR, "
              "category VARCHAR, name VARCHAR, attrs VARCHAR)")
    yield c
    c.close()


def _rec(con, **kw):
    row = rl._row(issued_on=kw.pop("issued_on", ISSUED),
                  issued_by=kw.pop("issued_by", "test"),
                  area_kind="bbox", area_id="box", area_label="Test area",
                  anchor_lon=ANCHOR_LON, anchor_lat=ANCHOR_LAT, **kw)
    rl.insert_rows(con, [row])
    return row


def _ledger_location(con, *, key="loc1", category="laundry", name="Sudsy Wash",
                     first_seen_on=dt.date(2026, 9, 20), lat=NEAR_LAT,
                     last_seen_month="2026-10", cluster_id=1, sources=("overture_places",),
                     attrs=None):
    con.execute("""
        INSERT INTO analysis.poi_presence VALUES
        (?, ?, ?, ?, ?, ?, 'BK', ?, ?, 'source_date', ?, 'opened_on', 1, ?, 'p1',
         '2026-09', now())
    """, [key, category, name.lower(), name, ANCHOR_LON, lat,
          first_seen_on.strftime("%Y-%m"), last_seen_month, first_seen_on, cluster_id])
    for i, src in enumerate(sources):
        pid = f"{key}-{i}"
        con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                    [pid, cluster_id, i == 0, category])
        con.execute("INSERT INTO staging.poi VALUES (?, ?, ?, ?, ?)",
                    [pid, src, category, name, json.dumps(attrs or {})])


def _pipeline_row(con, *, pid="pipe1", category="laundry", name="Future Laundry",
                  entry_date=dt.date(2026, 9, 15), entry_stage="fitout",
                  is_open=False, opened_on=None, lat=NEAR_LAT, n_sources=1):
    con.execute("""
        INSERT INTO analysis.storefront_pipeline
        (pipeline_id, group_kind, bbl, business_name_key, business_name, borough,
         lon, lat, geom, point_source, entry_stage, entry_date, furthest_stage,
         furthest_date, n_filings, n_sources, sources, stages, loci_category,
         category_confidence, is_open, opened_on, opened_on_stage, lead_days,
         bbl_missing, name_key_missing, asof_date, built_at)
        VALUES (?, 'bbl_name', '3000010001', ?, ?, 'BK', ?, ?, NULL, 'filing',
                ?, ?, ?, ?, 1, ?, 'dob_now_jobs', ?, ?, 'high', ?, ?, ?, NULL,
                FALSE, FALSE, DATE '2026-09-30', now())
    """, [pid, name.lower().replace(" ", ""), name, ANCHOR_LON, lat,
          entry_stage, entry_date, entry_stage, entry_date, n_sources,
          entry_stage, category, is_open, opened_on,
          "first_inspection" if is_open else None])


# ------------------------------------------------ 1. the append-only invariant

def test_mutable_and_immutable_partition_the_table(con):
    """Every column of analysis.recommendation must be classified as mutable or
    immutable. A column added to sql/026 and classified as neither would be
    silently editable, which is the one thing this table may not be."""
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'recommendation'").fetchall()}
    assert cols == rl.MUTABLE_COLUMNS | rl.IMMUTABLE_COLUMNS
    assert not (rl.MUTABLE_COLUMNS & rl.IMMUTABLE_COLUMNS)
    assert "grade" in rl.IMMUTABLE_COLUMNS
    assert "supply_ratio_at_issue" in rl.IMMUTABLE_COLUMNS


def test_the_only_update_names_only_mutable_columns():
    """Parsed from the statement itself, so the assertion cannot drift from the
    thing it asserts about."""
    set_clause = rl.UPDATE_STATUS_SQL.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
    named = {part.split("=")[0].strip() for part in set_clause.split(",")}
    assert named <= rl.MUTABLE_COLUMNS, f"an UPDATE touches {named - rl.MUTABLE_COLUMNS}"


def test_recording_the_same_card_twice_writes_nothing_new(con):
    row = rl._row(issued_on=ISSUED, issued_by="test", area_kind="bbox",
                  area_id="box", area_label="Test", category="laundry",
                  anchor_lon=ANCHOR_LON, anchor_lat=ANCHOR_LAT, grade="C",
                  supply_ratio_at_issue=0.72)
    assert rl.insert_rows(con, [row]).n_written == 1
    again = rl.insert_rows(con, [row])
    assert (again.n_written, again.n_duplicate) == (0, 1)
    assert con.execute("SELECT count(*) FROM analysis.recommendation").fetchone()[0] == 1


def test_a_regraded_card_is_a_new_row_not_an_edit(con):
    """2026-09-11 graded restaurant D; 2026-09-13 graded it C. Both are true of
    their own date and the ledger must hold both."""
    common = dict(area_kind="bbox", area_id="box", area_label="Gowanus core",
                  category="restaurant", anchor_lon=ANCHOR_LON, anchor_lat=ANCHOR_LAT,
                  issued_by="loci recommend", supply_ratio_at_issue=1.84)
    rl.insert_rows(con, [rl._row(issued_on=dt.date(2026, 9, 11), grade="D", **common)])
    rl.insert_rows(con, [rl._row(issued_on=dt.date(2026, 9, 13), grade="C", **common)])
    got = con.execute("SELECT issued_on, grade FROM analysis.recommendation "
                      "ORDER BY issued_on").fetchall()
    assert got == [(dt.date(2026, 9, 11), "D"), (dt.date(2026, 9, 13), "C")]


def test_status_change_leaves_every_immutable_column_alone(con):
    row = _rec(con, category="laundry", grade="C", supply_ratio_at_issue=0.94)
    before = con.execute("SELECT grade, supply_ratio_at_issue, issued_on, card_hash "
                         "FROM analysis.recommendation").fetchone()
    rl.withdraw(con, row["rec_id"], "not thin after all", on=dt.date(2026, 9, 11))
    after = con.execute("SELECT grade, supply_ratio_at_issue, issued_on, card_hash, "
                        "status, status_reason FROM analysis.recommendation").fetchone()
    assert after[:4] == before
    assert after[4] == "withdrawn"
    assert after[5] == "not thin after all"


def test_a_withdrawal_needs_a_reason(con):
    row = _rec(con, category="laundry")
    with pytest.raises(ValueError, match="reason"):
        rl.withdraw(con, row["rec_id"], "")


# ------------------------------------------------------------- 2. the backfill

def test_the_backfill_is_the_card_not_the_checkpoint_paraphrase():
    """13 of 15 categories grade D on the 2026-09-11 card; hardware and
    tailor_repair grade C. The CHECKPOINT phase line says "14 of 15", and the
    card is the source of truth because the card is what was issued."""
    rows = rl.backfill_rows()
    card = [r for r in rows if r["issued_on"] == dt.date(2026, 9, 11)]
    assert len(card) == 15
    grades = {r["category"]: r["grade"] for r in card}
    assert sorted(g for g in grades.values() if g == "D").__len__() == 13
    assert grades["hardware"] == "C" and grades["tailor_repair"] == "C"
    assert grades["restaurant"] == "D", "restaurant graded C only on 2026-09-13"


def test_the_d73_laundry_lead_is_withdrawn_with_its_reason():
    rows = rl.backfill_rows()
    laundry_lead = [r for r in rows
                    if r["category"] == "laundry" and r["issued_on"] == dt.date(2026, 9, 10)]
    assert len(laundry_lead) == 1
    row = laundry_lead[0]
    assert row["status"] == "withdrawn"
    assert row["status_changed_on"] == dt.date(2026, 9, 11)
    assert "0.94" in row["status_reason"]
    assert row["grade"] is None, "no card existed on 2026-09-10, so there is no grade"


def test_the_three_d73_thin_leads_carry_a_named_solution_and_format():
    rows = {r["category"]: r for r in rl.backfill_rows()
            if r["issued_on"] == dt.date(2026, 9, 11)}
    for cat, ratio in (("pharmacy", 0.0), ("convenience", 0.40), ("hardware", 0.72)):
        assert rows[cat]["supply_ratio_at_issue"] == pytest.approx(ratio)
        assert rows[cat]["format_hint"], f"{cat} is a named lead and needs a format"
        assert json.loads(rows[cat]["evidence_json"])["is_d73_thin_lead"] is True
    # a category with no named proposal must NOT invent a format hint
    assert rows["bar"]["format_hint"] is None


def test_the_backfill_is_idempotent(con):
    first = rl.backfill(con)
    second = rl.backfill(con)
    assert first.n_written == 16          # 15 card rows + the withdrawn laundry lead
    assert (second.n_written, second.n_duplicate) == (0, 16)


# ------------------------------------------------------------- 3. the check

def test_an_opening_before_the_issue_date_is_not_a_fill(con):
    """THE ADVERSARIAL CASE. A laundromat that opened three weeks BEFORE we
    called the area thin is not evidence that our recommendation was filled --
    it is evidence that the screen was stale. Crediting it would flatter every
    number this table produces."""
    _rec(con, category="laundry")
    _ledger_location(con, first_seen_on=ISSUED - dt.timedelta(days=21))
    rows, res = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert res.n_opened == 0 and res.n_none == 1
    assert rows[0]["match_kind"] == "none"


def test_a_left_censored_ledger_row_can_never_match(con):
    """It existed when the ledger started. Its opening date is unknown and
    unbounded below; reading '2026-09' off it would manufacture an opening."""
    _rec(con, category="laundry")
    con.execute("""
        INSERT INTO analysis.poi_presence VALUES
        ('old', 'laundry', 'old laundry', 'Old Laundry', ?, ?, 'BK',
         '2026-09', '2026-10', 'backfill_censored', NULL, NULL, 2, 1, 'p1',
         '2026-09', now())
    """, [ANCHOR_LON, NEAR_LAT])
    _, res = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert res.n_opened == 0


def test_a_different_category_is_not_a_fill(con):
    _rec(con, category="laundry")
    _ledger_location(con, category="cafe_bakery", name="Corner Cafe")
    _, res = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert res.n_opened == 0 and res.n_none == 1


def test_the_radius_is_a_real_distance(con):
    """555 m away is outside a 400 m disc and inside a 700 m one. The radius is
    a straight line by design (sql/026); this pins that it is a DISTANCE and not
    a bounding box."""
    _rec(con, category="laundry")
    _ledger_location(con, lat=FAR_LAT)
    _, tight = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert tight.n_opened == 0
    rows, wide = rl.check(con, month="2026-10", radius_m=700.0,
                          today=dt.date(2026, 10, 31))
    assert wide.n_opened == 1
    assert 500 < rows[0]["distance_m"] < 600


def test_days_to_fill_counts_from_the_issue_date(con):
    _rec(con, category="laundry")
    _ledger_location(con, first_seen_on=dt.date(2026, 10, 11))
    rows, res = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert res.n_opened == 1
    assert rows[0]["days_to_fill"] == (dt.date(2026, 10, 11) - ISSUED).days == 40
    assert json.loads(rows[0]["quality_json"])["days_basis"] == "opened_on"
    assert con.execute("SELECT status FROM analysis.recommendation").fetchone()[0] == "filled"


def test_a_pipeline_filing_is_in_pipeline_and_says_so(con):
    _rec(con, category="laundry")
    _pipeline_row(con, entry_date=dt.date(2026, 9, 15), entry_stage="fitout")
    rows, res = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert res.n_in_pipeline == 1 and res.n_newly_filled == 0
    q = json.loads(rows[0]["quality_json"])
    assert rows[0]["entry_stage"] == "fitout"
    assert q["days_basis"] == "entry_date"
    assert "INTENTION" in q["note"]
    assert con.execute("SELECT status FROM analysis.recommendation").fetchone()[0] == "open"


def test_an_opened_ledger_match_beats_a_pipeline_filing(con):
    _rec(con, category="laundry")
    _pipeline_row(con)
    _ledger_location(con, first_seen_on=dt.date(2026, 10, 2))
    rows, res = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert res.n_opened == 1
    assert rows[0]["matched_location_key"] == "loc1"


def test_nothing_after_the_snapshot_month_is_visible(con):
    """A re-run of an old month must reproduce that month, not today."""
    _rec(con, category="laundry")
    _ledger_location(con, first_seen_on=dt.date(2026, 11, 5))
    _, sept = rl.check(con, month="2026-09", today=dt.date(2026, 12, 1))
    assert sept.n_opened == 0, "a November opening is not visible in September"
    _, nov = rl.check(con, month="2026-11", today=dt.date(2026, 12, 1))
    assert nov.n_opened == 1


def test_none_is_stored_not_skipped(con):
    _rec(con, category="laundry")
    rows, res = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert res.n_none == 1
    stored = con.execute("SELECT match_kind, quality_json FROM "
                         "analysis.recommendation_outcome").fetchall()
    assert stored[0][0] == "none"
    assert "no same-category opening" in json.loads(stored[0][1])["note"]


def test_re_running_a_month_reproduces_it(con):
    """DELETE + INSERT for the month. The first run flips the row to 'filled',
    so a check that only looked at OPEN rows would find nothing on the second
    run and silently wipe the month it was asked to reproduce."""
    _rec(con, category="laundry")
    _ledger_location(con, first_seen_on=dt.date(2026, 10, 11))
    rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    first = con.execute("SELECT rec_id, match_kind, days_to_fill, distance_m, "
                        "solution_match_score FROM analysis.recommendation_outcome "
                        "ORDER BY rec_id").fetchall()
    rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    second = con.execute("SELECT rec_id, match_kind, days_to_fill, distance_m, "
                         "solution_match_score FROM analysis.recommendation_outcome "
                         "ORDER BY rec_id").fetchall()
    assert first == second
    assert con.execute("SELECT count(*) FROM analysis.recommendation_outcome "
                       "WHERE snapshot_month = '2026-10'").fetchone()[0] == 1


def test_a_withdrawn_recommendation_is_not_checked(con):
    row = _rec(con, category="laundry")
    rl.withdraw(con, row["rec_id"], "0.94x, not thin")
    _ledger_location(con, first_seen_on=dt.date(2026, 10, 11))
    _, res = rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    assert res.n_checked == 0, "we retracted the claim; scoring it now is marking our own homework"


def test_dry_run_writes_nothing(con):
    _rec(con, category="laundry")
    _ledger_location(con, first_seen_on=dt.date(2026, 10, 11))
    rl.check(con, month="2026-10", today=dt.date(2026, 10, 31), dry_run=True)
    assert con.execute("SELECT count(*) FROM analysis.recommendation_outcome").fetchone()[0] == 0
    assert con.execute("SELECT status FROM analysis.recommendation").fetchone()[0] == "open"


# -------------------------------------------------------------- 4. the rubric

def test_category_only_scores_the_category_weight_and_says_what_was_missing():
    """'Never fabricate quality': a bare category match is 0.50, and the JSON
    names every component that could not be evaluated."""
    rec = {"category": "laundry", "format_hint": None}
    cand = {"display_name": "Wash Palace", "n_sources": None,
            "last_seen_month": None, "fill_month": None}
    score, q = rl.score_match(rec, cand, {"chains_available": False})
    assert score == pytest.approx(0.50)
    assert set(q["unavailable"]) == {"format_hint", "corroboration",
                                     "independent", "still_open"}
    assert q["max_available"] == pytest.approx(0.50)
    assert q["components"]["format_hint"]["earned"] is None


def test_an_unavailable_component_is_never_scored_as_a_zero_or_a_pass():
    rec = {"category": "laundry", "format_hint": None}
    cand = {"display_name": "Wash Palace"}
    _, q = rl.score_match(rec, cand, {})
    for key in q["unavailable"]:
        assert q["components"][key]["earned"] is None
        assert q["components"][key]["evidence"]


def test_the_format_hint_is_a_keyword_match_over_name_cuisine_and_licence():
    rec = {"category": "laundry", "format_hint": "24/7 staffed laundromat"}
    hit = {"display_name": "Bergen Laundromat", "n_sources": 2}
    miss = {"display_name": "Bergen Cleaners", "n_sources": 2}
    assert rl.score_match(rec, hit, {})[1]["components"]["format_hint"]["earned"] is True
    assert rl.score_match(rec, miss, {})[1]["components"]["format_hint"]["earned"] is False
    # The match is EXACT SUBSTRING, deliberately: "laundromat" does not match
    # DCWP's "Retail Laundry", and no stemming is applied because a fuzzy match
    # here would score a dry cleaner as a laundromat. The fix is to name the
    # alternatives in the hint -- a comma-separated hint is a list of them --
    # which is what the backfill's laundry lead does.
    assert rl.score_match(rec, {"display_name": "Bergen Street Co",
                                "business_category": "Retail Laundry"},
                          {})[1]["components"]["format_hint"]["earned"] is False
    alternatives = {"category": "laundry", "format_hint": "laundromat, laundry, wash and fold"}
    # the DOHMH cuisine / DCWP business category count as evidence too
    via_attrs = {"display_name": "Bergen Street Co", "business_category": "Retail Laundry"}
    assert rl.score_match(alternatives, via_attrs,
                          {})[1]["components"]["format_hint"]["earned"] is True


def test_format_keywords_drop_words_too_generic_to_prove_anything():
    kws = rl.format_keywords("a small local hardware store with lumber")
    assert "hardware" in kws and "lumber" in kws
    assert "store" not in kws and "small" not in kws and "local" not in kws


def test_a_chain_is_noted_not_scored_as_independent():
    rec = {"category": "pharmacy", "format_hint": "independent pharmacy"}
    cand = {"display_name": "Duane Reade Pharmacy", "brand_key": "duanereade",
            "n_sources": 3}
    ctx = {"chains_available": True, "chain_brands": {"duanereade": "Duane Reade"}}
    score, q = rl.score_match(rec, cand, ctx)
    assert q["components"]["independent"]["earned"] is False
    assert "Duane Reade" in q["components"]["independent"]["evidence"]
    # still a real outcome: category + format + corroboration all earned
    assert score == pytest.approx(0.50 + 0.20 + 0.15)


def test_still_open_is_unavailable_in_the_fill_month():
    """'Open the month it opened' is true by construction and proves nothing."""
    rec = {"category": "laundry", "format_hint": None}
    cand = {"display_name": "New Wash", "last_seen_month": "2026-10",
            "fill_month": "2026-10"}
    _, q = rl.score_match(rec, cand, {"newest_ledger_month": "2026-10"})
    assert q["components"]["still_open"]["earned"] is None


def test_every_rubric_component_can_be_earned():
    """A component nobody can earn is a component that is not measuring
    anything. Extending RUBRIC without extending this fixture fails here."""
    rec = {"category": "laundry", "format_hint": "laundromat"}
    cand = {"display_name": "Corner Laundromat", "brand_key": "cornerlaundromat",
            "n_sources": 3, "last_seen_month": "2026-11", "fill_month": "2026-10"}
    ctx = {"chains_available": True, "chain_brands": {}, "newest_ledger_month": "2026-11"}
    score, q = rl.score_match(rec, cand, ctx)
    assert all(c["earned"] is True for c in q["components"].values())
    assert score == pytest.approx(sum(s["weight"] for s in rl.RUBRIC.values()))


def test_the_rubric_runs_end_to_end_on_a_real_match(con):
    _rec(con, category="laundry", format_hint="laundromat, wash and fold",
         proposed_solution="A laundromat on the block")
    _ledger_location(con, name="Gowanus Laundromat", first_seen_on=dt.date(2026, 10, 11),
                     last_seen_month="2026-11",
                     sources=("overture_places", "nyc_dcwp_inspections"),
                     attrs={"business_category": "Retail Laundry"})
    rows, _ = rl.check(con, month="2026-11", today=dt.date(2026, 11, 30))
    q = json.loads(rows[0]["quality_json"])
    assert q["components"]["category"]["earned"] is True
    assert q["components"]["format_hint"]["earned"] is True
    assert q["components"]["corroboration"]["earned"] is True, "two feeds see it"
    assert rows[0]["solution_match_score"] >= 0.85


# --------------------------------------------------------------- 5. the views

def test_recommendation_latest_marks_an_open_row_as_censored(con):
    _rec(con, category="laundry")
    rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    row = con.execute("SELECT status, is_censored, match_kind FROM "
                      "analysis.recommendation_latest").fetchone()
    assert row == ("open", True, "none")


def test_the_category_summary_says_no_exposure_rather_than_zero(con):
    """share_still_open_12m must be NULL, never 0, before anything has had a
    twelve-month anniversary."""
    _rec(con, category="laundry")
    _ledger_location(con, first_seen_on=dt.date(2026, 10, 11))
    rl.check(con, month="2026-10", today=dt.date(2026, 10, 31))
    df = rl.category_summary(con)
    row = df[df["category"] == "laundry"].iloc[0]
    assert int(row["n_filled"]) == 1
    assert int(row["n_exposed_12m"]) == 0
    assert row["share_still_open_12m"] is None or row["share_still_open_12m"] != row["share_still_open_12m"]


# ------------------------------------------------- 6. the `--record` hook

def test_rows_from_cards_carries_the_grade_and_the_evidence(con):
    """`loci recommend --record` builds its rows through this function, so the
    shape of what lands in the ledger is testable without a warehouse."""
    from loci.model import recommend as rec

    rules = rec.load_rules()
    facts = {"area": "Test area", "n_addresses": 42, "homes_400m_median": 3646.0,
             "live_hash": "deadbeef", "asof": "2026-09-14",
             "categories": {"laundry": {"ratio_median": 0.94, "regime": "saturating",
                                        "n_ratio_addresses": 400}}}
    card = rec.build_card("laundry", facts, {"n_comps": 0}, rules)
    rows = rl.rows_from_cards([card], facts, issued_on=dt.date(2026, 9, 14),
                              issued_by="loci recommend (rules v1)",
                              area_kind="bbox", area_id="box",
                              area_label="Test area",
                              anchor_lon=ANCHOR_LON, anchor_lat=ANCHOR_LAT,
                              gap_score=0.61)
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == "laundry"
    assert row["grade"] == card["overall_grade"]
    assert row["supply_ratio_at_issue"] == pytest.approx(0.94)
    assert row["homes_400m_at_issue"] == pytest.approx(3646.0)
    assert row["gap_score_at_issue"] == pytest.approx(0.61)
    assert row["status"] == "open"
    ev = json.loads(row["evidence_json"])
    assert ev["section_grades"].keys() == set(rec.SECTION_ORDER)
    assert ev["supply_hash"] == "deadbeef"
    # and it is insertable, idempotently
    assert rl.insert_rows(con, rows).n_written == 1
    assert rl.insert_rows(con, rows).n_duplicate == 1


def test_recording_a_do_not_act_card_is_the_point_not_a_bug(con):
    """The D rows are the control group. A `--record` that quietly dropped them
    would leave the ledger holding only the claims we already believed."""
    from loci.model import recommend as rec

    rules = rec.load_rules()
    facts = {"area": "Test", "n_addresses": 10, "homes_400m_median": 100.0,
             "categories": {c: {"ratio_median": 1.0} for c in ("laundry", "bar")}}
    cards = [rec.build_card(c, facts, {"n_comps": 0}, rules) for c in ("laundry", "bar")]
    assert all(c["overall_grade"] == "D" for c in cards), "no comps, so every card is D"
    rows = rl.rows_from_cards(cards, facts, issued_on=dt.date(2026, 9, 14),
                              issued_by="test", area_kind="bbox", area_id="box",
                              anchor_lon=ANCHOR_LON, anchor_lat=ANCHOR_LAT)
    assert rl.insert_rows(con, rows).n_written == 2
