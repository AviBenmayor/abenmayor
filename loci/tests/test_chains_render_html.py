"""`loci chains render --html`: the data/chains/ page and its JSON payload.

Shares `render.assemble()` with docs/CHAINS.md (see render.py's docstring), so
what is tested here is the HTML/JSON *packaging* of that shared data, not a
second implementation of the hand/auto/rejected split:

  1. Both files land on disk, under 2 MB, with the two section headings a
     reader (or a future test) can grep for.
  2. A rejected row never reaches either table.
  3. Incumbents/co-op banners sort to the bottom of their section.
  4. Every auto-admitted row carries a working `loci chains reject <key>`
     snippet.
  5. The JSON row counts equal the fixture's own counts -- not a hard-coded
     number, so the test does not silently stop checking anything the day the
     fixture grows a row.

A live smoke test at the bottom renders the real watchlist read-only and
checks against the YAML's own tier counts, guarded by a warehouse-exists skip.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pandas as pd
import pytest

from loci import db as locidb
from loci.chains import detect as detect_mod
from loci.chains import render_html as rh
from loci.chains import watchlist as wl

MONTH = "2026-09"
TODAY = dt.date(2026, 9, 16)


def _row(**kw):
    base = {f: None for f in wl.FIELDS}
    base["evidence"] = []
    base.update(kw)
    return base


def _doc() -> dict:
    """Hand-vetted prospect, hand-vetted incumbent, auto prospect, auto co-op
    banner (incumbent), and one rejected row -- the five shapes the render
    must sort and filter correctly."""
    return {"version": 1, "brands": [
        _row(brand="Blank Street Coffee", brand_key="blank street coffee",
             category="coffee", loci_category="cafe_bakery",
             net_new_12m=20, nyc_locations_now=45, confidence="verified",
             # `verified` requires a counted source (GTM-189) -- a store
             # locator or a hand count, never a press or filing number.
             store_count_source="locator",
             sales_role="prospect", last_verified="2026-08-01",
             evidence=[{"url": "https://x.example"}]),
        _row(brand="Dunkin'", brand_key="dunkin",
             category="coffee", loci_category="cafe_bakery",
             net_new_12m=90, nyc_locations_now=900, confidence="reported",
             sales_role="incumbent", evidence=[{"url": "https://y.example"}]),
        _row(brand="Some New Brand", brand_key="some new brand",
             loci_category="restaurant", confidence="auto", tier="admitted",
             decided_by="auto", sales_role="prospect",
             admission_reason="cleared the D109 candidate predicate; detect "
                               "2026-09: 10 locations, 4 new 12m",
             decided_on="2026-09-15", locations_at_decision=10),
        _row(brand="Key Food", brand_key="key food",
             loci_category="grocery", confidence="auto", tier="admitted",
             decided_by="auto", sales_role="incumbent",
             admission_reason="co-op banner: no single site-selector",
             decided_on="2026-09-15", locations_at_decision=40),
        _row(brand="Rejected Brand", brand_key="rejected brand",
             loci_category="fitness", tier="rejected", decided_by="owner",
             rejection_reason="too small", decided_on="2026-08-01",
             locations_at_decision=3),
    ]}


@pytest.fixture()
def con():
    c = locidb.connect(":memory:")
    detect_mod.ensure_schema(c)
    # (key, total, new_12m, loci_category, pipeline_filings_12m,
    #  pipeline_coverage, press_hits_12m). `some new brand` is a FITNESS brand:
    # the filing feeds cannot see that category at all, so its pipeline cell
    # must read the blind-spot sentence and never a zero (sql/039).
    specs = [
        ("blank street coffee", 50, 20, "cafe_bakery", 3, "real", 2),
        ("dunkin", 905, 6, "restaurant", 0, "real", 0),
        ("some new brand", 10, 4, "fitness", 0, "structural_zero", 1),
        ("key food", 40, 1, "grocery", 1, "real", 0),
    ]
    frame = pd.DataFrame([{
        "snapshot_month": MONTH, "brand_key": bk, "display_name": bk.title(),
        "loci_category": cat, "locations_total": total,
        "locations_dated": total, "locations_new_12m": new12,
        "locations_new_3m": 1, "n_boroughs": 3, "boroughs": "Brooklyn,Manhattan",
        "categories": cat, "n_sources": 2, "flagged": True,
        "flag_reason": "test fixture", "detected_at": dt.datetime(2026, 9, 15, 12, 0),
        "pipeline_filings_12m": filings, "pipeline_coverage": coverage,
        "press_hits_12m": press,
    } for bk, total, new12, cat, filings, coverage, press in specs])
    c.register("_rows", frame)
    cols = ", ".join(detect_mod.SNAPSHOT_COLUMNS)
    c.execute(f"INSERT INTO chains.brand_snapshot ({cols}) SELECT {cols} FROM _rows")
    c.unregister("_rows")
    yield c
    c.close()


@pytest.fixture()
def data(con):
    return rh.build_data(con, doc=_doc(), month=MONTH, today=TODAY)


# ------------------------------------------------------------------ the payload

def test_counts_match_the_fixture():
    doc = _doc()
    assert sum(1 for r in doc["brands"] if wl.tier_of(r) != "rejected"
               and not wl.is_auto(r)) == 2
    assert sum(1 for r in doc["brands"] if wl.is_auto(r)
               and wl.tier_of(r) != "rejected") == 2
    assert sum(1 for r in doc["brands"] if wl.tier_of(r) == "rejected") == 1


def test_json_row_counts_equal_the_docs_own_counts(data):
    assert data["counts"]["hand_vetted"] == len(data["watchlist"]) == 2
    assert data["counts"]["auto_admitted"] == len(data["auto_admitted"]) == 2
    assert data["counts"]["rejected"] == 1
    assert data["counts"]["total"] == 5


def test_rejected_row_is_in_neither_table(data):
    keys = {r["brand_key"] for r in data["watchlist"]} \
        | {r["brand_key"] for r in data["auto_admitted"]}
    assert "rejected brand" not in keys


def test_incumbents_and_banners_sort_last(data):
    watchlist_keys = [r["brand_key"] for r in data["watchlist"]]
    assert watchlist_keys[-1] == "dunkin", "the incumbent must sort to the bottom"
    assert watchlist_keys[0] == "blank street coffee"

    auto_keys = [r["brand_key"] for r in data["auto_admitted"]]
    assert auto_keys[-1] == "key food", "the co-op banner must sort to the bottom"
    assert auto_keys[0] == "some new brand"


def test_every_auto_row_has_a_working_reject_snippet(data):
    for row in data["auto_admitted"]:
        snippet = row["reject_snippet"]
        assert snippet.startswith("loci chains reject ")
        assert row["brand_key"] in snippet
        assert '--reason ""' in snippet


def test_detected_counts_are_attached_from_the_snapshot(data):
    by_key = {r["brand_key"]: r for r in data["watchlist"]}
    assert by_key["blank street coffee"]["detected_total"] == 50
    assert by_key["blank street coffee"]["detected_new_12m"] == 20

    auto_by_key = {r["brand_key"]: r for r in data["auto_admitted"]}
    assert auto_by_key["some new brand"]["detected_total"] == 10


def test_hand_row_has_no_admission_reason_field(data):
    """The auto columns (admission_reason, decided_on, reject_snippet) are
    only meaningful for a row nobody has looked at -- the watchlist rows
    never carry them."""
    for row in data["watchlist"]:
        assert "admission_reason" not in row
        assert "reject_snippet" not in row


# --------------------------------------------------------------------- the page

def test_render_html_returns_html_and_json(con):
    html_text, json_text = rh.render_html(con, doc=_doc(), month=MONTH, today=TODAY)
    assert "<html" in html_text.lower()
    payload = json.loads(json_text)
    assert payload["detect_snapshot"] == MONTH
    assert payload["generated"] == TODAY.isoformat()


def test_write_creates_both_files_under_2mb(con, tmp_path):
    html_text, json_text = rh.render_html(con, doc=_doc(), month=MONTH, today=TODAY)
    html_path, json_path = rh.write(html_text, json_text, out_dir=tmp_path)

    assert html_path.exists() and html_path.name == rh.HTML_NAME
    assert json_path.exists() and json_path.name == rh.JSON_NAME
    assert html_path.stat().st_size + json_path.stat().st_size < 2 * 1024 * 1024

    text = html_path.read_text()
    assert "Watchlist" in text
    assert "Auto-admitted this snapshot (nobody has looked yet)" in text


def test_written_json_round_trips_the_same_counts(con, tmp_path):
    html_text, json_text = rh.render_html(con, doc=_doc(), month=MONTH, today=TODAY)
    _, json_path = rh.write(html_text, json_text, out_dir=tmp_path)
    payload = json.loads(json_path.read_text())
    assert payload["counts"]["hand_vetted"] == 2
    assert payload["counts"]["auto_admitted"] == 2
    assert payload["counts"]["rejected"] == 1


# ------------------------------------------------------------------- live smoke

WAREHOUSE = pathlib.Path(locidb.DEFAULT_PATH)


@pytest.mark.skipif(not WAREHOUSE.exists(), reason="no data/loci.duckdb on this clone")
def test_live_render_matches_the_watchlists_own_counts():
    """Read-only against the real warehouse. Asserts against the YAML's own
    tier counts (never a hard-coded row count), so this does not need
    updating every time `chains auto-admit` runs."""
    from loci.model.recommend import connect_read_only

    try:
        con = connect_read_only(WAREHOUSE, retries=2, wait_s=3.0)
    except Exception as exc:                      # noqa: BLE001
        pytest.skip(f"warehouse is locked by a concurrent writer: {exc}")

    try:
        doc = wl.load()
        assert wl.validate(doc) == [], "the shipped watchlist.yaml must be valid"
        n_hand = sum(1 for r in doc["brands"] if wl.tier_of(r) != "rejected"
                    and not wl.is_auto(r))
        n_auto = sum(1 for r in doc["brands"] if wl.is_auto(r)
                    and wl.tier_of(r) != "rejected")
        n_rejected = sum(1 for r in doc["brands"] if wl.tier_of(r) == "rejected")

        data = rh.build_data(con, doc=doc)
    finally:
        con.close()

    assert data["counts"]["hand_vetted"] == n_hand
    assert data["counts"]["auto_admitted"] == n_auto
    assert data["counts"]["rejected"] == n_rejected
    assert len(data["watchlist"]) == n_hand
    assert len(data["auto_admitted"]) == n_auto
    assert n_hand + n_auto + n_rejected == len(doc["brands"])


# --------------------------------------- the sql/039 signals on the page

def test_the_page_carries_the_coverage_label_beside_the_pipeline_cell(data):
    """`Some New Brand` is fitness in the snapshot fixture -- a category no NYC
    filing feed can attribute a licence to. The cell has to say so; an empty
    cell or a 0 would be read as "nothing is coming"."""
    from loci.chains import render as ren

    row = next(r for r in data["auto_admitted"] if r["brand_key"] == "some new brand")
    assert row["pipeline_coverage"] == "structural_zero"
    assert row["pipeline"] == ren.NO_COVERAGE_CELL


def test_a_covered_category_keeps_an_ordinary_pipeline_cell(data):
    from loci.chains import render as ren

    row = next(r for r in data["watchlist"] if r["brand_key"] == "blank street coffee")
    assert row["pipeline_coverage"] == "real"
    assert row["pipeline"] != ren.NO_COVERAGE_CELL


def test_every_row_carries_its_press_count(data):
    """A NUMBER, not a string: the column sorts numerically on the page."""
    auto = {r["brand_key"]: r["press_hits_12m"] for r in data["auto_admitted"]}
    hand = {r["brand_key"]: r["press_hits_12m"] for r in data["watchlist"]}
    assert auto["some new brand"] == 1 and auto["key food"] == 0
    assert hand["blank street coffee"] == 2 and hand["dunkin"] == 0
    assert all(isinstance(v, int) for v in {**auto, **hand}.values())


def test_a_press_count_the_snapshot_never_measured_serializes_null(con):
    """NULL is "we did not measure that channel" and must reach the page as
    null, never as 0 -- JSON has no other way to keep the distinction."""
    con.execute("UPDATE chains.brand_snapshot SET press_hits_12m = NULL, "
                "pipeline_coverage = NULL WHERE brand_key = 'dunkin'")
    payload = rh.build_data(con, doc=_doc(), month=MONTH, today=TODAY)
    row = next(r for r in payload["watchlist"] if r["brand_key"] == "dunkin")
    assert row["press_hits_12m"] is None
    assert row["pipeline_coverage"] is None


def test_the_auto_table_has_a_press_column_the_body_fills():
    """Header and body are written in two different places in the page shell;
    a column added to one and not the other shifts every cell after it."""
    assert '<th class="num" data-key="press_hits_12m" data-type="num">Press 12m</th>' \
        in rh.PAGE_HTML
    assert "fmt(r.press_hits_12m)" in rh.PAGE_HTML


def test_the_footer_caveat_explains_the_blind_spot():
    from loci.chains import render as ren

    text = rh.caveat_text()
    assert ren.NO_COVERAGE_CELL in text
    for category in ren.detect_mod.filing_real_categories():
        assert category in text
    assert "BLIND SPOT, not an absence" in text
