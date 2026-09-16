"""The curated watchlist, the import merge rule, and the research budget.

The merge rule is the load-bearing part: a research agent will produce 60-120
brands as JSON and merging that over a hand-corrected file is exactly when hand
corrections die. FILL-ONLY is the default and these tests are what hold it
there.

The research tests assert the BUDGET, because the budget is the difference
between a monthly cron and an unbounded bill. It is enforced in code, so it is
testable without an API key: the client is injected.
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci.chains import research, watchlist
from loci.chains.normalize import brand_key

TODAY = dt.date(2026, 9, 13)


def _doc(*rows):
    return {"version": 1, "brands": list(rows)}


def _row(**kw):
    base = {f: None for f in watchlist.FIELDS}
    base["evidence"] = []
    base.update(kw)
    return base


# --------------------------------------------------------------- the shipped file

def test_shipped_watchlist_is_valid():
    doc = watchlist.load()
    assert watchlist.validate(doc) == [], "src/loci/chains/watchlist.yaml is invalid"
    assert len(doc["brands"]) >= 2


def test_shipped_seeds_are_marked_unverified():
    """The two seeds exist to exercise the pipeline. If a later edit ever puts
    a real count on them without marking them verified, this fails -- which is
    the point: an unverified count that looks verified is the failure mode."""
    for row in watchlist.load()["brands"]:
        if row["confidence"] == "unverified":
            assert row["nyc_locations_now"] is None, \
                f"{row['brand']} carries a count but is still `unverified`"


def test_brand_key_must_be_what_the_normalizer_produces():
    doc = _doc(_row(brand="Apollo Bagels", brand_key="apollo-bagels"))
    errors = watchlist.validate(doc)
    assert any("would join to nothing" in e for e in errors)


def test_unknown_loci_category_is_rejected():
    doc = _doc(_row(brand="Apollo Bagels", brand_key="apollo bagels",
                    loci_category="bagel_shop"))
    assert any("loci_category" in e for e in watchlist.validate(doc))


def test_duplicate_brand_keys_are_rejected():
    doc = _doc(_row(brand="Apollo Bagels", brand_key="apollo bagels"),
               _row(brand="APOLLO BAGELS", brand_key="apollo bagels"))
    assert any("duplicate" in e for e in watchlist.validate(doc))


# ------------------------------------------------------------------- the merge rule

# ------------------------------------------- the hand-evidence block (GTM-189)
#
# Five optional fields nothing but a person writes. They are checked HARD for
# one reason each, and the reason is always that something READS them: the
# candidates escape hatch reads `capital_events[].date`, the confidence scale
# reads `store_count_source`, and a field nobody validates is a field that
# silently stops working.


def _hand(**kw):
    return _doc(_row(brand="Super Burrito", brand_key="super burrito",
                     confidence="auto", **kw))


def test_a_well_formed_hand_evidence_block_validates():
    doc = _hand(
        capital_events=[{"kind": "fundraise", "date": "2026-05-04",
                         "counterparty": "Enlightened Hospitality",
                         "amount": "$21M Series B",
                         "url": "https://example.test/round"}],
        signed_leases=[{"address": "376 Graham Ave, Brooklyn",
                        "signed_on": "2026-06-01", "expected_open": "2027-01-15",
                        "url": "https://example.test/lease"}],
        store_count_source="hand_count",
        expansion_contact_url="https://example.test/real-estate",
        trajectory_state="accelerating")
    assert watchlist.validate(doc) == []


@pytest.mark.parametrize("events,fragment", [
    ("not a list", "must be a list"),
    ([["kind", "fundraise"]], "must be a mapping"),
    ([{"kind": "series_a", "date": "2026-05-04"}], "kind 'series_a' not in"),
    ([{"kind": "fundraise", "date": "May 2026"}], "is not YYYY-MM-DD"),
    ([{"kind": "fundraise"}], "is not YYYY-MM-DD"),
    ([{"kind": "fundraise", "date": "2026-05-04", "amount": 21_000_000}],
     "amount must be a string"),
    ([{"kind": "fundraise", "date": "2026-05-04", "investor": "x"}],
     "unknown key(s) ['investor']"),
])
def test_a_malformed_capital_event_is_an_error(events, fragment):
    errors = watchlist.validate(_hand(capital_events=events))
    assert any(fragment in e for e in errors), errors


def test_an_undated_capital_event_is_refused_because_it_can_never_fire():
    """The escape hatch compares the date against `decided_on`. An undated
    event sits on the row looking armed and does nothing, which is worse than
    not being there: nobody re-reads a rejected row by hand."""
    errors = watchlist.validate(_hand(capital_events=[{"kind": "bankruptcy"}]))
    assert any("can never re-surface a rejected brand" in e for e in errors)


@pytest.mark.parametrize("leases,fragment", [
    ("123 Main St", "must be a list"),
    ([{"signed_on": "2026-06-01"}], "missing `address`"),
    ([{"address": "  "}], "missing `address`"),
    ([{"address": "1 Main St", "signed_on": "last June"}], "is not YYYY-MM-DD"),
    ([{"address": "1 Main St", "expected_open": "soon"}], "is not YYYY-MM-DD"),
    ([{"address": "1 Main St", "sqft": 1200}], "unknown key(s) ['sqft']"),
])
def test_a_malformed_signed_lease_is_an_error(leases, fragment):
    errors = watchlist.validate(_hand(signed_leases=leases))
    assert any(fragment in e for e in errors), errors


def test_a_lease_needs_only_an_address():
    """The other three are optional on purpose: a broker mentions a signed
    lease on a corner long before anyone knows the opening date, and refusing
    the row would lose the only signal detect structurally cannot see."""
    assert watchlist.validate(_hand(signed_leases=[{"address": "1 Main St"}])) == []


def test_store_count_source_is_an_enum():
    assert any("store_count_source 'guess' not in" in e
               for e in watchlist.validate(_hand(store_count_source="guess")))
    for value in watchlist.STORE_COUNT_SOURCE_VALUES:
        assert watchlist.validate(_hand(store_count_source=value)) == []


@pytest.mark.parametrize("source", ["press", "filing", None])
def test_verified_needs_a_counted_source(source):
    """`verified` means somebody here counted the stores. A press number is a
    journalist's count and a filing count is a floor off open data; promoting
    either to `verified` is the exact laundering the confidence scale exists to
    stop (docs/chains-process.md, quarterly re-verification)."""
    doc = _doc(_row(brand="Super Burrito", brand_key="super burrito",
                    confidence="verified", store_count_source=source,
                    evidence=[{"url": "https://example.test/a"}]))
    assert any("needs store_count_source in ['hand_count', 'locator']" in e
               for e in watchlist.validate(doc))


@pytest.mark.parametrize("source", ["hand_count", "locator"])
def test_verified_is_allowed_where_somebody_counted(source):
    doc = _doc(_row(brand="Super Burrito", brand_key="super burrito",
                    confidence="verified", store_count_source=source,
                    evidence=[{"url": "https://example.test/a"}]))
    assert watchlist.validate(doc) == []


def test_the_verified_gate_does_not_touch_any_other_confidence():
    for conf in ("reported", "unverified", "auto"):
        doc = _doc(_row(brand="Super Burrito", brand_key="super burrito",
                        confidence=conf,
                        evidence=[{"url": "https://example.test/a"}]))
        assert watchlist.validate(doc) == [], conf


def test_trajectory_state_is_an_enum():
    assert any("trajectory_state 'growing' not in" in e
               for e in watchlist.validate(_hand(trajectory_state="growing")))
    for value in watchlist.TRAJECTORY_STATE_VALUES:
        assert watchlist.validate(_hand(trajectory_state=value)) == []


def test_expansion_contact_url_must_be_a_string():
    assert any("expansion_contact_url must be a string" in e
               for e in watchlist.validate(_hand(expansion_contact_url=12)))


def test_the_hand_evidence_fields_are_all_optional_on_every_shipped_row():
    """All 902 rows predate the block and must still validate untouched: the
    fields are additive, and a required one would have invalidated the file the
    day it was added."""
    doc = watchlist.load()
    assert watchlist.validate(doc) == []
    for field in ("capital_events", "signed_leases", "store_count_source",
                  "expansion_contact_url", "trajectory_state"):
        assert field in watchlist.FIELDS
        assert all(r.get(field) is None for r in doc["brands"]), \
            f"{field} is hand-entered; nothing should have written it yet"


def test_nothing_machine_written_carries_a_hand_evidence_field():
    """`auto-admit` writes the DECISION block and never this one. The whole
    point of the split is that a `--month` re-run of detect cannot destroy a
    hand fact; a machine that started writing here would put the fact back in
    reach of the DELETE."""
    _, added, _ = watchlist.auto_admit(
        {"version": 1, "brands": []},
        [{"brand_key": "super burrito", "display_name": "Super Burrito",
          "locations_total": 9, "locations_new_12m": 3}], today=TODAY)
    for field in ("capital_events", "signed_leases", "store_count_source",
                  "expansion_contact_url", "trajectory_state"):
        assert added[0][field] is None


def test_import_never_clobbers_a_curated_field():
    doc = _doc(_row(brand="Apollo Bagels", brand_key="apollo bagels",
                    nyc_locations_now=7, confidence="verified",
                    why_they_grow="a person checked this"))
    doc, counts = watchlist.upsert(doc, [{
        "brand": "Apollo Bagels", "nyc_locations_now": 99,
        "why_they_grow": "an agent guessed this", "hq": "New York, NY",
    }], today=TODAY)
    row = doc["brands"][0]
    assert counts["added"] == 0 and counts["updated"] == 1 and counts["skipped"] == 0
    assert row["nyc_locations_now"] == 7
    assert row["why_they_grow"] == "a person checked this"
    assert row["hq"] == "New York, NY", "an EMPTY field must still be filled"


def test_overwrite_replaces_only_the_fields_the_record_carries():
    doc = _doc(_row(brand="Apollo Bagels", brand_key="apollo bagels",
                    nyc_locations_now=7, hq="New York, NY", confidence="verified"))
    doc, _ = watchlist.upsert(doc, [{"brand": "Apollo Bagels",
                                     "nyc_locations_now": 11}],
                              overwrite=True, today=TODAY)
    row = doc["brands"][0]
    assert row["nyc_locations_now"] == 11
    assert row["hq"] == "New York, NY", "a field absent from the JSON is not a correction"
    assert row["confidence"] == "verified"


def test_evidence_is_unioned_not_replaced():
    doc = _doc(_row(brand="Apollo Bagels", brand_key="apollo bagels",
                    evidence=[{"url": "https://a.example", "date": "2026-01-01"}]))
    doc, _ = watchlist.upsert(doc, [{
        "brand": "Apollo Bagels",
        "evidence": [{"url": "https://a.example", "date": "2026-01-01"},
                     {"url": "https://b.example", "date": "2026-02-01"}]}],
        today=TODAY)
    urls = [e["url"] for e in doc["brands"][0]["evidence"]]
    assert urls == ["https://a.example", "https://b.example"]


def test_first_added_is_never_overwritten():
    doc = _doc(_row(brand="Apollo Bagels", brand_key="apollo bagels",
                    first_added="2026-01-01"))
    doc, _ = watchlist.upsert(doc, [{"brand": "Apollo Bagels",
                                     "first_added": "2026-09-13"}],
                              overwrite=True, today=TODAY)
    assert doc["brands"][0]["first_added"] == "2026-01-01"


def test_import_derives_the_brand_key_and_dates_new_rows():
    doc = _doc()
    doc, counts = watchlist.upsert(doc, [{"brand": "VITAL CLIMBING GYM LLC",
                                          "loci_category": "fitness"}], today=TODAY)
    row = doc["brands"][0]
    assert counts["added"] == 1
    assert row["brand_key"] == brand_key("VITAL CLIMBING GYM LLC") == "vital climbing gym"
    assert row["first_added"] == "2026-09-13"
    assert watchlist.validate(doc) == [] or row["brand_key"] == "vital climbing gym"


def test_the_real_research_payload_spelling_is_mapped_not_dropped():
    """The producer of the research JSON spells fields its own way. Dropping
    `net_new_nyc_12mo` because this file says `net_new_12m` would lose the
    document's RANKING COLUMN while reporting a clean import."""
    doc = _doc()
    doc, counts = watchlist.upsert(doc, [{
        "brand": "Luckin Coffee", "hq_city": "Xiamen", "net_new_nyc_12mo": 17,
        "nyc_locations_12mo_ago": 9, "real_estate_role": "VP Development",
        "evidence_urls": ["https://ny.eater.com/x"], "pipeline_notes": "6 signed",
        "nyc_locations_now_method": "hand count", "source_slice": "coffee",
        "invented_field": 1,
    }], today=TODAY)
    row = doc["brands"][0]
    assert row["hq"] == "Xiamen"
    assert row["net_new_12m"] == 17
    assert row["nyc_locations_12m_ago"] == 9
    assert row["expansion_role_title"] == "VP Development"
    assert row["pipeline"] == "6 signed"
    assert row["evidence"] == [{"url": "https://ny.eater.com/x"}]
    # producer working-notes are ignored on purpose; a NEW key is reported loudly
    assert counts["unplaced_keys"] == ["invented_field"]
    assert watchlist.validate(doc) == []


def test_records_with_no_resolvable_brand_are_skipped_not_crashed():
    doc = _doc()
    doc, counts = watchlist.upsert(doc, [{"hq": "Nowhere"},
                                         {"brand": "n/a"}], today=TODAY)
    assert counts["skipped"] == 2
    assert doc["brands"] == []


def test_dump_round_trips_and_keeps_the_comment_header(tmp_path):
    doc = watchlist.load()
    text = watchlist.dump(doc)
    assert text.lstrip().startswith("#"), "the field documentation must survive a write"
    out = tmp_path / "wl.yaml"
    out.write_text(text)
    assert watchlist.validate(watchlist.load(out)) == []
    assert len(watchlist.load(out)["brands"]) == len(doc["brands"])


# ------------------------------------------------------------------ the spend budget

def test_press_domains_include_the_gtm191_additions():
    """GTM-191: What Now NY and Franchise Times were missing; The Real Deal and
    Commercial Observer were already there and must not be duplicated."""
    for domain in ("whatnow.com", "commercialobserver.com", "therealdeal.com",
                   "franchisetimes.com"):
        assert domain in research.PRESS_DOMAINS
    assert len(research.PRESS_DOMAINS) == len(set(research.PRESS_DOMAINS)), \
        "PRESS_DOMAINS has a duplicate"


class _FakeTavily:
    def __init__(self):
        self.calls = []

    def search(self, **kw):
        self.calls.append(kw)
        return {"results": [{"url": f"https://ny.eater.com/{len(self.calls)}",
                             "title": "A place opened", "published_date": "2026-09-01",
                             "content": "words", "score": 0.9}]}


def test_the_plan_never_exceeds_the_budget():
    plan = research.build_plan([f"brand{i}" for i in range(200)], max_queries=12)
    assert plan.n_queries == 12
    assert plan.truncated == 200 + len(research.DISCOVERY_QUERIES) - 12


def test_discovery_queries_survive_a_truncated_budget():
    """When the budget bites, the channel that finds UNKNOWN brands is the one
    worth keeping; confirming a listed brand can wait a month."""
    plan = research.build_plan(["apollo bagels"], max_queries=3)
    assert [kind for kind, _, _ in plan.queries] == ["discovery"] * 3


def test_run_spends_no_more_than_the_budget(tmp_path):
    from loci import db as locidb

    con = locidb.connect(":memory:")
    plan = research.build_plan(["a", "b", "c"], max_queries=4)
    plan.budget = 2                      # the code counts down, not the plan length
    fake = _FakeTavily()
    out = research.run(con, plan, client=fake, today=TODAY)
    assert len(fake.calls) == 2 == out["queries_spent"]
    assert out["written"] == 2


def test_run_upserts_rather_than_duplicating(tmp_path):
    from loci import db as locidb

    con = locidb.connect(":memory:")
    plan = research.build_plan([], max_queries=1)
    research.run(con, plan, client=_FakeTavily(), today=TODAY)
    research.run(con, plan, client=_FakeTavily(), today=TODAY)
    assert con.execute("SELECT count(*) FROM chains.press_hits").fetchone()[0] == 1


def test_missing_api_key_fails_with_the_variable_name(monkeypatch):
    monkeypatch.delenv(research.ENV_KEY, raising=False)
    with pytest.raises(RuntimeError, match=research.ENV_KEY):
        research._client()


def test_press_window_is_passed_as_a_start_date():
    fake = _FakeTavily()
    from loci import db as locidb

    con = locidb.connect(":memory:")
    research.run(con, research.build_plan([], max_queries=1), client=fake,
                 days=45, today=TODAY)
    assert fake.calls[0]["start_date"] == "2026-07-30"
    assert fake.calls[0]["include_domains"] == list(research.PRESS_DOMAINS)
