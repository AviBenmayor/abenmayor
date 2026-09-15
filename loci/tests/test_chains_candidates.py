"""The D109 candidate predicate, auto-admission, and the render ordering.

Three things are asserted here, in order of how badly a regression would hurt:

  1. THE PREDICATE, clause by clause, as a pure function. Every input it reads
     is an argument, so each clause can be failed on its own and the reason
     string checked against what actually fired. Under the 2026-09-15 ruling
     this predicate writes to the watchlist unattended, so a clause that has
     quietly stopped biting is 900 rows nobody asked for.

  2. THE ESCAPE HATCH. A rejection that never expires turns a correct decision
     made on thin data into a permanent blind spot, and nothing else in the
     system re-reads a rejected row. Both arms are tested, plus the case that
     cannot re-surface at all (no `locations_at_decision`), because a silent
     zero there would re-open every old rejection forever.

  3. THE SEPARATION between what a person checked and what a machine admitted:
     `nyc_locations_now` stays NULL on an auto row, and `render` never mixes
     the two populations into one table.

The SQL runs against a THREE-TABLE synthetic warehouse built in-memory --
`chains.brand_snapshot` (plus the `brand_latest` view from sql/015),
`chains.press_hits`, and a minimal `analysis.storefront_pipeline`. The real
warehouse is never opened.
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci import db as locidb
from loci.chains import candidates as cand
from loci.chains import detect as detect_mod
from loci.chains import watchlist as wl

TODAY = dt.date(2026, 9, 15)
MONTH = "2026-09"


def _brand(key, **kw):
    """One `chains.brand_latest` record. Defaults CLEAR the predicate, so each
    test can fail exactly one clause and nothing else."""
    base = {"snapshot_month": MONTH, "brand_key": key,
            "display_name": key.title(), "loci_category": "restaurant",
            "locations_total": 9, "locations_dated": 9, "locations_new_12m": 3,
            "locations_new_3m": 1, "n_boroughs": 3, "boroughs": "Brooklyn,Manhattan",
            "categories": "restaurant", "n_sources": 2, "flagged": True,
            "flag_reason": "3 new locations in 12 months",
            "detected_at": dt.datetime(2026, 9, 15, 12, 0)}
    base.update(kw)
    return base


# =========================================================== 1. the predicate

def test_a_plain_growing_chain_is_a_candidate():
    reason = cand.candidate_reason(_brand("super burrito"))
    assert reason is not None
    assert "9 locations (5+ floor)" in reason
    assert "3 new locations in 12 months" in reason
    # ... and the count is not repeated. `flag_reason` already names it, and
    # every row in the first live run of 799 was flagged.
    assert reason.count("3 new") == 1


def test_one_source_is_not_two_opinions():
    """`n_sources >= 2` AFTER aliasing. One dataset's opinion is not a fact,
    and a single-source 'chain' is as often one dataset's duplicate rows."""
    assert cand.candidate_reason(_brand("super burrito", n_sources=1)) is None


def test_below_the_floor_and_unflagged_is_not_a_candidate():
    assert cand.candidate_reason(
        _brand("small thing", locations_total=4, flagged=False)) is None


def test_the_flag_arm_admits_a_fast_small_chain_the_size_floor_misses():
    """The OR is the clause that does the real work. A four-location brand
    that opened two of them this year is the population the list exists for,
    and no absolute size floor will ever see it."""
    reason = cand.candidate_reason(
        _brand("chahalo", locations_total=4, locations_new_12m=2,
               flag_reason="2 new of only 4 locations (fast small chain)"))
    assert reason is not None
    assert "5+ floor" not in reason
    assert "fast small chain" in reason


def test_a_brand_that_has_not_moved_is_a_logo_not_a_lead():
    assert cand.candidate_reason(
        _brand("static chain", locations_new_12m=0, flagged=False,
               locations_total=40)) is None


@pytest.mark.parametrize("kw,expect", [
    ({"press_hits_12m": 2}, "2 press hits in 12m"),
    ({"pipeline_open": 1}, "1 not-yet-open filing"),
])
def test_press_and_filings_are_movement_when_no_store_opened(kw, expect):
    """Detect can only see a store once it is open. A signed lease or a
    headline is the whole reason the movement test has three arms."""
    row = _brand("pipeline brand", locations_new_12m=0, flagged=False,
                 locations_total=12, flag_reason=None)
    reason = cand.candidate_reason(row, **kw)
    assert reason is not None and expect in reason


def test_an_excluded_class_never_reaches_the_queue():
    assert cand.candidate_reason(
        _brand("moneygram", locations_total=300, n_boroughs=5)) is None
    assert cand.candidate_reason(
        _brand("cafe", locations_total=60, n_boroughs=4, n_sources=4)) is None


def test_an_already_admitted_brand_is_not_offered_again():
    assert cand.candidate_reason(_brand("super burrito"),
                                 admitted={"super burrito"}) is None


# =================================================== 2. the re-surface hatch

def _rejected(**kw):
    row = {"brand_key": "rejected brand", "tier": "rejected",
           "rejection_reason": "one operator, two permits",
           "decided_on": "2026-09-15", "decided_by": "owner",
           "locations_at_decision": 5}
    row.update(kw)
    return {"rejected brand": row}


def test_a_rejection_sticks():
    assert cand.candidate_reason(_brand("rejected brand", locations_total=7),
                                 rejected=_rejected()) is None


def test_a_doubled_count_resurfaces_a_rejection():
    """"Rejected at 5 stores" must not permanently hide a brand now at 20.
    Doubling rather than a fixed step, because the signal is proportional."""
    reason = cand.candidate_reason(_brand("rejected brand", locations_total=10),
                                   rejected=_rejected())
    assert reason is not None
    assert reason.startswith("RE-SURFACED: rejected at 5 locations, now 10")


def test_a_rejection_with_no_recorded_count_cannot_resurface_on_doubling():
    """There is nothing to double. Treating the missing number as zero would
    re-open every rejection ever written, which is the same as having none."""
    assert cand.candidate_reason(_brand("rejected brand", locations_total=400),
                                 rejected=_rejected(
                                     locations_at_decision=None)) is None


def test_a_capital_event_resurfaces_a_rejection_regardless_of_size():
    reason = cand.candidate_reason(
        _brand("rejected brand", locations_total=6),
        rejected=_rejected(capital_events=[{"kind": "series_a"}]))
    assert reason is not None and "capital event" in reason


# ======================================================== sales_role, cheaply

@pytest.mark.parametrize("total,role", [(1, "prospect"), (99, "prospect"),
                                        (100, "incumbent"), (1420, "incumbent")])
def test_sales_role_is_the_hundred_location_line(total, role):
    assert cand.sales_role_for(_brand("x", locations_total=total)) == role


# ============================================== supermarket co-op banners

@pytest.mark.parametrize("key", sorted(cand.COOP_BANNERS))
def test_coop_banners_are_incumbent_regardless_of_count(key):
    """A co-op banner's count is stores under one sign across many
    independently owned supermarkets, not one operator's growth -- it must
    never earn `prospect`'s "sell this" framing, at any location count."""
    assert cand.sales_role_for(_brand(key, locations_total=1)) == "incumbent"
    assert cand.sales_role_for(_brand(key, locations_total=122)) == "incumbent"


def test_a_non_banner_below_the_incumbent_floor_is_still_a_prospect():
    assert cand.sales_role_for(_brand("super burrito", locations_total=9)) == "prospect"


def test_coop_banner_reason_names_itself_as_a_banner():
    """The note travels with the row's `reason` (and, via `auto_admit`, its
    `admission_reason`) so a reader sees WHY it is incumbent without having to
    know `COOP_BANNERS` exists."""
    reason = cand.candidate_reason(_brand("key food", locations_total=122))
    assert reason is not None
    assert cand.COOP_BANNER_NOTE in reason


def test_coop_banner_flows_through_select_as_incumbent_with_the_note():
    row = _brand("key food", locations_total=122, n_boroughs=5, n_sources=3)
    run = cand.select([row], month=MONTH)
    assert len(run.rows) == 1
    assert run.rows[0]["sales_role"] == "incumbent"
    assert cand.COOP_BANNER_NOTE in run.rows[0]["reason"]


def test_a_coop_banner_never_reaches_auto_admit_as_nyc_locations_now():
    """Same discipline as every other auto row: the machine count never lands
    in the curated field, banner or not."""
    doc, added, _ = wl.auto_admit(
        _empty_doc(),
        [{"brand_key": "key food", "display_name": "Key Food",
          "locations_total": 122, "locations_new_12m": 2,
          "reason": "122 locations (5+ floor); 2 new in 12m; "
                    + cand.COOP_BANNER_NOTE,
          "sales_role": "incumbent"}],
        month=MONTH, today=TODAY)
    row = added[0]
    assert row["sales_role"] == "incumbent"
    assert row["nyc_locations_now"] is None
    assert cand.COOP_BANNER_NOTE in row["admission_reason"]


# ============================================================ 3. the SQL path

@pytest.fixture()
def warehouse():
    """Three tables, built minimally. NOT the real warehouse."""
    con = locidb.connect(":memory:")
    detect_mod.ensure_schema(con)            # chains.* incl. the brand_latest view
    con.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    # Only the columns the two readers touch: the candidate SQL needs
    # business_name_key + is_open, and render's pipeline cell also reads bbl,
    # borough, entry_date, furthest_stage and sources. The other thirty
    # columns of sql/020 are not part of this contract.
    con.execute("CREATE TABLE analysis.storefront_pipeline ("
                "business_name_key VARCHAR, is_open BOOLEAN, bbl VARCHAR, "
                "borough VARCHAR, entry_date DATE, furthest_stage VARCHAR, "
                "sources VARCHAR)")

    rows = [
        _brand("super burrito"),                                     # candidate
        _brand("dunkin", locations_total=1420, locations_new_12m=42,
               n_boroughs=5, n_sources=3),                           # incumbent
        _brand("chase", loci_category="bank", locations_total=200),   # excluded
        _brand("cafe", locations_total=60, n_boroughs=4, n_sources=4),  # generic
        _brand("chestnut market", locations_total=13, n_boroughs=0,
               boroughs=""),                                         # geocode
        _brand("lonely brand", n_sources=1),                         # one source
        _brand("vital climbing gym", locations_total=4, flagged=False,
               locations_new_12m=0, loci_category="fitness"),        # already on list
        # No opening, no flag: it reaches the queue only through its filing.
        _brand("paper only", locations_new_12m=0, flagged=False,
               locations_total=6),
    ]
    con.register("_rows", __import__("pandas").DataFrame(rows))
    con.execute("INSERT INTO chains.brand_snapshot SELECT "
                + ", ".join(c for c in (
                    "snapshot_month", "brand_key", "display_name", "loci_category",
                    "locations_total", "locations_dated", "locations_new_12m",
                    "locations_new_3m", "n_boroughs", "boroughs", "categories",
                    "n_sources", "flagged", "flag_reason", "detected_at"))
                + " FROM _rows")
    con.unregister("_rows")

    con.execute(
        "INSERT INTO analysis.storefront_pipeline VALUES "
        "('paper only', FALSE, '1001', 'BK', DATE '2026-02-04', "
        " 'liquor_application', 'nys_sla_pending'), "
        "('super burrito', TRUE, '1002', 'MN', DATE '2025-06-01', "
        " 'first_inspection', 'nyc_dohmh_restaurants')")
    con.execute("INSERT INTO chains.press_hits VALUES "
                "('paper only', 'https://ny.eater.com/1', 'It is coming', "
                " DATE '2026-08-01', 'words', 0.9, 'q', 'brand', now())")
    return con


def test_fetch_joins_the_two_movement_signals(warehouse):
    month, rows = cand.fetch(warehouse, today=TODAY)
    assert month == MONTH
    by = {r["brand_key"]: r for r in rows}
    assert len(by) == 8
    # An OPEN filing is a store that already exists and is already counted.
    assert by["super burrito"]["pipeline_open"] == 0
    assert by["paper only"]["pipeline_open"] == 1
    assert by["paper only"]["press_hits_12m"] == 1
    assert by["dunkin"]["press_hits_12m"] == 0


def test_press_outside_the_window_is_not_movement(warehouse):
    warehouse.execute("UPDATE chains.press_hits SET published_on = DATE '2024-01-01'")
    _, rows = cand.fetch(warehouse, today=TODAY)
    by = {r["brand_key"]: r for r in rows}
    assert by["paper only"]["press_hits_12m"] == 0


def test_the_counts_account_for_every_row_that_met_the_predicate(warehouse):
    doc = {"version": 1, "brands": [
        {"brand": "Vital Climbing Gym", "brand_key": "vital climbing gym",
         "evidence": [{"url": "https://x.example"}], "confidence": "reported"}]}
    _, rows = cand.fetch(warehouse, today=TODAY)
    run = cand.select(rows, month=MONTH, admitted=wl.admitted_keys(doc),
                      rejected=wl.rejected_rows(doc))

    keys = [r["brand_key"] for r in run.rows]
    assert keys == ["dunkin", "super burrito", "paper only"], \
        "ranked by new_12m desc, then locations_total desc"
    assert run.n_predicate == run.n_excluded + run.n_admitted + run.n_rejected \
        + run.n_candidates
    assert run.excluded_by_class["bank_clinic_category"] == 1
    assert run.excluded_by_class["generic_key"] == 1
    assert run.excluded_by_class["geocode_defect"] == 1
    assert run.excluded_by_class["fuel"] == 0, "a class that matched nothing prints a zero"
    assert run.n_admitted == 0, "the admitted row never met the numeric predicate"
    assert run.n_rows == 8


def test_a_missing_optional_table_degrades_rather_than_raising(warehouse):
    """A warehouse without the filing pipeline is a normal state (the table is
    built by a separate command). The movement test then rests on openings
    alone -- which is 'we did not measure that channel', not 'nothing came'."""
    warehouse.execute("DROP TABLE analysis.storefront_pipeline")
    warehouse.execute("DROP TABLE chains.press_hits")
    _, rows = cand.fetch(warehouse, today=TODAY)
    by = {r["brand_key"]: r for r in rows}
    assert by["paper only"]["pipeline_open"] == 0
    run = cand.select(rows, month=MONTH)
    assert "paper only" not in [r["brand_key"] for r in run.rows]


def test_run_reads_the_admitted_set_off_the_shipped_watchlist(warehouse):
    """End to end against the real YAML: `vital climbing gym` is on it, so it
    can never come back as a new candidate."""
    run = cand.run(warehouse, today=TODAY)
    assert "vital climbing gym" not in [r["brand_key"] for r in run.rows]
    assert run.month == MONTH


# ================================================== 4. auto-admission, written

def _empty_doc():
    return {"version": 1, "brands": []}


def test_auto_admit_writes_a_marked_row_and_never_a_curated_count():
    doc, added, skipped = wl.auto_admit(
        _empty_doc(),
        [{"brand_key": "super burrito", "display_name": "Super Burrito",
          "loci_category": "restaurant", "locations_total": 9,
          "locations_new_12m": 3, "reason": "9 locations (5+ floor); 3 new in 12m",
          "sales_role": "prospect"}],
        month=MONTH, today=TODAY)
    row = added[0]
    assert not skipped
    assert row["brand"] == "Super Burrito" and row["brand_key"] == "super burrito"
    assert row["confidence"] == "auto" and row["decided_by"] == "auto"
    assert row["tier"] == "admitted" and row["sales_role"] == "prospect"
    assert row["decided_on"] == row["first_added"] == "2026-09-15"
    assert row["locations_at_decision"] == 9
    assert "detect 2026-09: 9 locations, 3 new 12m" in row["admission_reason"]
    # THE LINE THAT MATTERS: a machine count is never written where a curated
    # one lives. Null means NOT COUNTED, and 141 of the 161 hand rows carry a
    # real number in this field.
    assert row["nyc_locations_now"] is None
    assert row["category"] is None
    assert wl.validate(doc) == []


def test_an_auto_row_may_cite_nothing_but_a_reported_one_may_not():
    doc, added, _ = wl.auto_admit(
        _empty_doc(), [{"brand_key": "super burrito", "display_name": "Super Burrito",
                        "locations_total": 9, "locations_new_12m": 3}],
        month=MONTH, today=TODAY)
    assert added[0]["evidence"] == [] and wl.validate(doc) == []
    added[0]["confidence"] = "reported"
    assert any("only ['auto', 'unverified'] may cite nothing" in e
               for e in wl.validate(doc))


def test_auto_admit_never_touches_an_existing_row():
    doc = {"version": 1, "brands": [
        {"brand": "Super Burrito", "brand_key": "super burrito",
         "nyc_locations_now": 7, "confidence": "reported", "tier": "rejected",
         "evidence": [{"url": "https://x.example"}]}]}
    doc, added, skipped = wl.auto_admit(
        doc, [{"brand_key": "super burrito", "display_name": "Super Burrito",
               "locations_total": 90, "locations_new_12m": 3}],
        month=MONTH, today=TODAY)
    assert added == [] and len(doc["brands"]) == 1
    assert doc["brands"][0]["nyc_locations_now"] == 7
    assert doc["brands"][0]["tier"] == "rejected"
    assert any("already on the watchlist" in s for s in skipped)


def test_auto_admit_respects_a_limit_and_keeps_the_ranking():
    rows = [{"brand_key": f"brand {i}", "display_name": f"Brand {i}",
             "locations_total": 10 - i, "locations_new_12m": 10 - i}
            for i in range(5)]
    _, added, _ = wl.auto_admit(_empty_doc(), rows, month=MONTH, today=TODAY, limit=2)
    assert [r["brand_key"] for r in added] == ["brand 0", "brand 1"]


def test_an_unmappable_detect_category_becomes_null_not_invented():
    _, added, _ = wl.auto_admit(
        _empty_doc(), [{"brand_key": "super burrito", "display_name": "Super Burrito",
                        "loci_category": "pet_store", "locations_total": 9,
                        "locations_new_12m": 1}],
        month=MONTH, today=TODAY)
    assert added[0]["loci_category"] is None


# ==================================================== 5. admit / reject / render

def _doc_with(**kw):
    row = {f: None for f in wl.FIELDS}
    row.update({"brand": "Super Burrito", "brand_key": "super burrito",
                "evidence": [], "confidence": "auto", "tier": "admitted",
                "sales_role": "prospect", "decided_by": "auto",
                "locations_at_decision": 9})
    row.update(kw)
    return {"version": 1, "brands": [row]}


def test_admit_promotes_an_auto_row_without_claiming_anybody_counted():
    doc = _doc_with()
    row = wl.decide(doc, "super burrito", tier="admitted",
                    reason="four new Brooklyn sites, all leased", today=TODAY)
    assert row["decided_by"] == "owner"
    assert row["confidence"] == "auto", \
        "a person looking at a DECISION is not a person counting STORES"
    assert row["admission_reason"] == "four new Brooklyn sites, all leased"
    assert row["decided_on"] == "2026-09-15"
    assert wl.validate(doc) == []


def test_admit_can_be_told_the_confidence_explicitly():
    doc = _doc_with()
    row = wl.decide(doc, "super burrito", tier="admitted", reason="counted the site",
                    confidence="verified", today=TODAY)
    assert row["confidence"] == "verified"
    # ... and then it must cite something, like every other reported row.
    assert any("may cite nothing" in e for e in wl.validate(doc))


def test_reject_keeps_the_row_so_it_is_never_re_surfaced_blindly():
    doc = _doc_with()
    row = wl.decide(doc, "super burrito", tier="rejected",
                    reason="one operator, two permits", today=TODAY,
                    locations_at_decision=5)
    assert len(doc["brands"]) == 1
    assert row["tier"] == "rejected" and row["rejection_reason"]
    assert wl.rejected_rows(doc) == {"super burrito": row}
    assert "super burrito" not in wl.admitted_keys(doc)


def test_deciding_on_an_unknown_key_raises_and_offers_near_matches():
    doc = _doc_with()
    with pytest.raises(KeyError):
        wl.decide(doc, "super burito", tier="admitted", reason="typo", today=TODAY)
    assert wl.near_matches(doc, "super burito") == ["super burrito"]
    assert wl.near_matches(doc, "super") == ["super burrito"], \
        "a short prefix is the other way a key gets typed wrong"


def test_a_row_with_no_decision_block_reads_as_admitted_and_owner_decided():
    """The reading rule itself, on a row that carries neither field.

    The 161 rows that predate the decision block look exactly like this, and
    reading a missing `tier` as anything but `admitted` would drop the entire
    hand-curated watchlist out of the document. Asserted on a FIXTURE rather
    than on the shipped file so the contract survives the file filling up with
    explicit values."""
    bare = {"brand": "Vital Climbing Gym", "brand_key": "vital climbing gym"}
    assert wl.tier_of(bare) == "admitted"
    assert wl.decided_by_of(bare) == "owner"
    assert not wl.is_auto(bare)


def test_every_shipped_row_is_decided_by_a_person_or_by_the_machine():
    """Both populations now live in one file (the 2026-09 auto-admit run), and
    which one a row belongs to is the whole basis of how it is read: an
    `owner` row is somebody's judgement, an `auto` row is a predicate nobody
    has checked. A third value would mean a writer nobody knows about."""
    rows = wl.brands()
    assert rows, "the shipped watchlist is empty"
    for row in rows:
        assert wl.decided_by_of(row) in wl.DECIDED_BY_VALUES, row.get("brand")
        assert wl.tier_of(row) in wl.TIER_VALUES, row.get("brand")
    owner = [r for r in rows if not wl.is_auto(r)]
    auto = [r for r in rows if wl.is_auto(r)]
    assert owner and auto, \
        "this test is only meaningful while the file holds both populations"
    assert len(owner) + len(auto) == len(rows)


def test_every_auto_row_carries_the_full_machine_marking():
    """An auto row has to be unmistakable at EVERY level, because that marking
    is the only thing standing between a predicate and a sales list. The
    load-bearing one is `nyc_locations_now`: it means "a person counted this",
    and detect's floor must never be written into it."""
    auto = [r for r in wl.brands() if wl.is_auto(r)]
    assert auto, "no auto rows in the shipped file"
    for row in auto:
        where = row.get("brand")
        assert wl.tier_of(row) == "admitted", where
        assert row.get("confidence") == "auto", where
        assert (row.get("evidence") or []) == [], where
        assert row.get("nyc_locations_now") is None, \
            f"{where}: a machine count was written where a curated one lives"
        assert (row.get("admission_reason") or "").strip(), \
            f"{where}: admitted with no reason recorded"
        assert row.get("sales_role") in wl.SALES_ROLE_VALUES, where
        assert row.get("decided_on"), where


def test_no_owner_row_was_turned_into_a_machine_row():
    """`auto-admit` never touches an existing row. The hand-vetted half must
    still cite its sources and keep its counts, whatever the machine added
    around it."""
    owner = [r for r in wl.brands() if not wl.is_auto(r)]
    assert len(owner) >= 161, "hand-vetted rows went missing"
    assert all(r.get("confidence") != "auto" for r in owner)
    counted = [r for r in owner if isinstance(r.get("nyc_locations_now"), int)]
    assert len(counted) >= 100, \
        "the curated counts are the thing the auto rows must not have eaten"


def test_render_never_mixes_the_hand_vetted_rows_with_the_machine_ones(warehouse):
    from loci.chains import render as ren

    doc = {"version": 1, "brands": [
        {f: None for f in wl.FIELDS} | {
            "brand": "Vital Climbing Gym", "brand_key": "vital climbing gym",
            "net_new_12m": 0, "nyc_locations_now": 4, "confidence": "reported",
            "evidence": [{"url": "https://x.example"}]},
        {f: None for f in wl.FIELDS} | {
            "brand": "Super Burrito", "brand_key": "super burrito",
            "confidence": "auto", "decided_by": "auto", "tier": "admitted",
            "sales_role": "prospect", "evidence": [],
            "admission_reason": "9 locations (5+ floor); 3 new in 12m"},
        {f: None for f in wl.FIELDS} | {
            "brand": "Cafe", "brand_key": "cafe", "tier": "rejected",
            "confidence": "auto", "evidence": [],
            "rejection_reason": "a generic noun, not a chain"},
    ]}
    text = ren.render(warehouse, doc=doc, month=MONTH, today=TODAY)

    head, _, auto = text.partition(
        "## Auto-admitted this snapshot (nobody has looked yet)")
    assert auto, "the auto section must exist when an auto row is present"
    assert "Vital Climbing Gym" in head and "Vital Climbing Gym" not in auto
    assert "Super Burrito" not in head and "Super Burrito" in auto
    # The reason the machine admitted it is printed, so it can be rejected on
    # what it actually claims rather than on its name.
    assert "9 locations (5+ floor); 3 new in 12m" in auto
    # A rejected row is counted, never listed.
    assert "| Cafe |" not in text
    assert "1 rejected row omitted" in text
    assert "1 hand-vetted, 1 auto-admitted, 1 rejected" in text


def test_render_omits_the_auto_section_when_there_are_no_auto_rows(warehouse):
    """A hand-only watchlist must not sprout an empty heading. Fixture-based on
    purpose: the shipped file now holds both populations, and this is the
    contract for a file that does not."""
    from loci.chains import render as ren

    doc = {"version": 1, "brands": [
        {f: None for f in wl.FIELDS} | {
            "brand": "Vital Climbing Gym", "brand_key": "vital climbing gym",
            "net_new_12m": 0, "nyc_locations_now": 4, "confidence": "reported",
            "evidence": [{"url": "https://x.example"}]},
    ]}
    text = ren.render(warehouse, doc=doc, month=MONTH, today=TODAY)
    assert "## Auto-admitted this snapshot" not in text
    assert "## Watchlist — ranked by net new locations in 12 months" in text
    assert "| Vital Climbing Gym |" in text
    assert "1 hand-vetted, 0 auto-admitted, 0 rejected" in text


def test_the_auto_section_appears_exactly_when_the_file_holds_auto_rows(warehouse):
    """The shipped file, as it stands after the 2026-09 auto-admit run. The
    section is present iff there is something to put in it, every auto row is
    in it and no owner row is, and the header counts agree with the file."""
    from loci.chains import render as ren

    doc = wl.load()
    rows = doc["brands"]
    auto = [r for r in rows if wl.is_auto(r) and wl.tier_of(r) != "rejected"]
    rejected = [r for r in rows if wl.tier_of(r) == "rejected"]
    hand = [r for r in rows if not wl.is_auto(r) and wl.tier_of(r) != "rejected"]

    text = ren.render(warehouse, doc=doc, month=MONTH, today=TODAY)
    head, _, tail = text.partition(
        "## Auto-admitted this snapshot (nobody has looked yet)")
    assert bool(tail) == bool(auto)
    assert f"{len(hand)} hand-vetted, {len(auto)} auto-admitted, " \
           f"{len(rejected)} rejected" in head

    if not auto:                      # pragma: no cover - the pre-2026-09 shape
        return
    assert f"{len(auto)} brands admitted by `loci chains auto-admit`" in tail
    # Nothing a person vetted may be laundered into the machine's section, and
    # nothing the machine wrote may sit in the table a reader acts on.
    assert "| Vital Climbing Gym |" in head
    assert "| Vital Climbing Gym |" not in tail
    for row in auto[:200]:
        assert f"| {row['brand']} |" not in head, row["brand"]
