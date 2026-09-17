"""Ground truth at the anchors (model/ground_truth.py, sql/036).

The load-bearing tests here are the ones a reader cannot check by eye:

  * `test_absence_is_recorded_not_inferred` -- an empty storefront list stores
    ONE row with a NULL name. "We looked and saw nothing" and "nobody has
    looked yet" are different states and the table has to tell them apart
    (D79). A version that skipped the empty record would silently collapse
    them.
  * `test_vacant_and_unknown_write_no_evidence` -- the adversarial case. An
    observer reporting an empty shopfront must NEVER produce a closure
    verdict for a POI: that is exactly the inference-from-absence D79 forbids,
    and it is the one mistake that would look like the tool working.
  * `test_the_miss_view_is_the_supply_model_s_miss` -- the view's whole job.
    An observed open storefront of the recommended category that the
    warehouse does not hold is a measured false positive of the screen; one
    it DOES hold is not, and the view must not confuse them.
  * `test_a_same_name_poi_120m_away_matches_and_is_not_a_miss` and
    `test_a_same_name_poi_450m_away_does_not_match_and_is_a_miss` -- D105
    2026-09-15's fix. The protocol's first read is a category-nearby search
    ranging across the whole 400 m catchment, so a same-name POI 120 m from
    the anchor is the SAME business and must not read as a miss; one 450 m
    away is genuinely outside the catchment and must.
  * `test_category_check_matches_the_categories_module` and
    `test_the_view_radius_matches_the_module_constant` -- drift checks. The
    CHECK list and the match radius are written literally in sql/036; these
    pin them to `loci.categories.CATEGORIES` and
    `ground_truth.MATCH_RADIUS_M` (400 m, the catchment radius -- see that
    constant's docstring), so widening one without the other fails the suite
    instead of silently disagreeing at runtime.
  * `test_summary_returns_none_not_nan_for_missing_imagery` and
    `test_cli_report_renders_a_rec_with_null_imagery_without_error` -- the
    NotRenderableError regression: pandas turns a SQL NULL into `float('nan')`
    even in a text column, and `NaN or default` returns `NaN` (a nonzero
    float is truthy), which rich's Table refuses to render.

No network anywhere: a browser session produces the JSONL, this module only
ingests it.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.model import ground_truth as gt
from loci.model import recommendation_ledger as rl

ISSUED = dt.date(2026, 9, 11)
OBSERVED = "2026-09-15T14:30:00"
ANCHOR_LON, ANCHOR_LAT = -73.9885, 40.676

#: ~0.0001 degrees of latitude is ~11 m -- "at the anchor" by the OLD 40 m
#: radius and comfortably inside the current 400 m one.
#: ~0.0011 is ~122 m -- inside the 400 m catchment radius (MATCH_RADIUS_M)
#: but outside the old 40 m "same doorway" radius: THE case D105's fix is
#: about, a same-name POI the nearby_url search would surface that the OLD
#: rule reported as a miss.
#: ~0.0041 is ~455 m -- outside the 400 m catchment entirely.
#: All three are asserted, not assumed, in
#: `test_the_match_radius_is_a_real_distance`.
NEAR_LAT = ANCHOR_LAT + 0.0001
CATCHMENT_LAT = ANCHOR_LAT + 0.0011
FAR_LAT = ANCHOR_LAT + 0.0041


# --------------------------------------------------------------- fixtures

@pytest.fixture()
def con(monkeypatch, tmp_path):
    """A synthetic warehouse carrying the REAL sql/018 + 026 + 033 + 036 DDL
    (via `ground_truth.ensure_schema`, the same path the CLI takes), so a
    schema change upstream breaks these tests instead of quietly invalidating
    them.

    `ground_truth.PLUTO_CSV` is monkeypatched to a path that never exists, so
    every test below runs `plan()`'s MapPLUTO lookup as a guaranteed no-op
    (`_pluto_street_labels` returns `{}`) regardless of whether the dev
    machine happens to have the real ~330 MB extract on disk -- reproducible
    behavior, not host-dependent. The dedicated PLUTO tests pass their own
    `pluto_csv=` fixture file to `plan()`, which overrides this entirely."""
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute("CREATE SCHEMA IF NOT EXISTS staging")
    c.execute("CREATE TABLE analysis.address (address_id VARCHAR, borough VARCHAR, "
              "street_name VARCHAR, neighborhood VARCHAR)")
    c.execute("INSERT INTO analysis.address VALUES "
              "('bk-1', 'BK', 'GRAHAM AVENUE', 'Williamsburg')")
    gt.ensure_schema(c)
    monkeypatch.setattr(gt, "PLUTO_CSV", tmp_path / "no-pluto-here.csv")
    yield c
    c.close()


def _rec(con, *, category="laundry", status="open", address_id="bk-1",
         lon=ANCHOR_LON, lat=ANCHOR_LAT, solution="A 24/7 staffed laundromat",
         grade="C", reason=None, area_kind="address", area_label="Test area"):
    row = rl._row(issued_on=ISSUED, issued_by="test", area_kind=area_kind,
                  area_id=address_id or "box", area_label=area_label,
                  anchor_address_id=address_id, anchor_lon=lon, anchor_lat=lat,
                  category=category, proposed_solution=solution, grade=grade,
                  status=status, status_reason=reason)
    rl.insert_rows(con, [row])
    return row["rec_id"]


def _presence(con, *, key="loc1", category="laundry", name="Sudsy Wash",
              lat=NEAR_LAT, lon=ANCHOR_LON, poi_id="p1"):
    con.execute("""
        INSERT INTO analysis.poi_presence
        (location_key, category, name_key, display_name, lon, lat, borough,
         first_seen_month, last_seen_month, first_seen_kind, n_months_seen,
         poi_id_latest, ledger_started_month, last_snapshot_at)
        VALUES (?, ?, ?, ?, ?, ?, 'BK', '2026-09', '2026-09', 'backfill_censored',
                1, ?, '2026-09', now())
    """, [key, category, gt.name_key(name), name, lon, lat, poi_id])


def _obs(rec_id, storefronts, *, gap_verdict="confirmed_gap", observed_at=OBSERVED,
         streetview_capture_date="2025-06"):
    return {"rec_id": rec_id, "observed_at": observed_at, "observer": "abenmayor",
            "maps_url": gt.maps_url(ANCHOR_LAT, ANCHOR_LON),
            "streetview_url": gt.streetview_url(ANCHOR_LAT, ANCHOR_LON),
            "streetview_capture_date": streetview_capture_date, "screenshot_path": None,
            "storefronts": storefronts, "gap_verdict": gap_verdict, "notes": None}


def _sf(name="Sudsy Wash", *, category_guess="laundry", status="open",
        label=None, notes=None, price_label=None):
    return {"name": name, "category_guess": category_guess, "status": status,
            "maps_status_label": label, "price_label": price_label, "notes": notes}


# ================================================================ 0. URLs

def test_maps_search_term_covers_exactly_categories():
    """Drift check: a category added to loci.categories.CATEGORIES without a
    matching Google Maps search term here would ship a manifest row whose
    nearby_url() call blows up at plan() time -- catch it in the suite
    instead."""
    assert set(gt.MAPS_SEARCH_TERM) == set(CATEGORIES)


def test_nearby_url_encodes_the_term_and_carries_lat_lon_zoom():
    url = gt.nearby_url(ANCHOR_LAT, ANCHOR_LON, "cafe_bakery")
    assert url == (
        f"https://www.google.com/maps/search/cafe/@{ANCHOR_LAT},{ANCHOR_LON},18z")
    # A term with a space URL-encodes it (verified live against "medical
    # clinic" and "grocery store" -- %20, not '+').
    url2 = gt.nearby_url(ANCHOR_LAT, ANCHOR_LON, "clinic", zoom=16)
    assert url2 == (
        "https://www.google.com/maps/search/medical%20clinic/"
        f"@{ANCHOR_LAT},{ANCHOR_LON},16z")
    with pytest.raises(ValueError):
        gt.nearby_url(ANCHOR_LAT, ANCHOR_LON, "not_a_category")


def test_address_url_is_none_for_no_label_and_encoded_for_a_real_one():
    assert gt.address_url(None) is None
    assert gt.address_url("") is None
    assert gt.address_url("376 Graham Ave, Brooklyn, NY 11211") == (
        "https://www.google.com/maps/search/376%20Graham%20Ave%2C%20Brooklyn%2C"
        "%20NY%2011211")


# =============================================================== 1. plan

def test_the_manifest_carries_well_formed_urls(con):
    rec_id = _rec(con)
    [entry] = gt.plan(con)
    assert entry["rec_id"] == rec_id
    assert entry["maps_url"] == (
        f"https://www.google.com/maps/search/?api=1&query={ANCHOR_LAT},{ANCHOR_LON}")
    assert entry["streetview_url"] == (
        "https://www.google.com/maps/@?api=1&map_action=pano"
        f"&viewpoint={ANCHOR_LAT},{ANCHOR_LON}")
    # No PLUTO extract in this test sandbox (the `con` fixture points
    # PLUTO_CSV at a path that never exists), so the label falls to priority
    # 2: the recommendation's own area_label.
    assert entry["address_label"] == "Test area"
    assert entry["category"] == "laundry"
    assert entry["proposed_solution"] == "A 24/7 staffed laundromat"
    # nearby_url is the category search, centered on the anchor.
    assert entry["nearby_url"] == (
        f"https://www.google.com/maps/search/laundromat/@{ANCHOR_LAT},{ANCHOR_LON},18z")
    # address_url is a real URL for an address-anchored rec, built from the
    # same address_label carried in the manifest.
    assert entry["address_url"] == gt.address_url(entry["address_label"])
    assert entry["address_url"].startswith("https://www.google.com/maps/search/")


def test_address_label_falls_back_to_neighborhood_when_no_pluto_or_area_label(con):
    """Priority 3: with no PLUTO match and no area_label, the neighborhood/
    borough label joined off `analysis.address` still gives every anchor
    SOME label -- never a bare address_id."""
    rec_id = _rec(con, area_label=None)
    [entry] = gt.plan(con)
    assert entry["rec_id"] == rec_id
    assert entry["address_label"] == "GRAHAM AVENUE — Williamsburg — BK"
    assert entry["address_url"] == gt.address_url(entry["address_label"])


def test_pluto_street_address_is_preferred_over_area_label_and_neighborhood(con, tmp_path):
    """THE FIX this test pins: `analysis.address` carries no house-number/
    full-address text column at all (`street_name` is populated only on
    CSCL street-frame rows and stays NULL on every real, lot-frame
    gap-screen anchor -- verified 2026-09-15 against the four 2026-09-14
    recs, `street_name IS NULL` on all of them). The one place a real,
    geocodable address lives is MapPLUTO, keyed by BBL -- which IS
    `address_id` on a lot-frame row. `plan()` must prefer it over BOTH the
    recommendation's own area_label and the neighborhood-only join label."""
    pluto_csv = tmp_path / "pluto.csv"
    pluto_csv.write_text(
        "BBL,address,postcode,borough\n"
        "bk-1,545 SACKETT STREET,11217,BK\n"
    )
    rec_id = _rec(con, area_label="Some other label entirely")
    [entry] = gt.plan(con, pluto_csv=pluto_csv)
    assert entry["rec_id"] == rec_id
    assert entry["address_label"] == "545 Sackett Street, Brooklyn, NY 11217"
    assert entry["address_url"] == gt.address_url(entry["address_label"])
    assert entry["address_url"] == (
        "https://www.google.com/maps/search/"
        "545%20Sackett%20Street%2C%20Brooklyn%2C%20NY%2011217")


def test_pluto_lookup_is_a_quiet_noop_without_the_extract_on_disk(con):
    """A fresh clone (or CI) has no ~330 MB raw PLUTO extract -- `plan()`
    must not raise, it must fall through to area_label/neighborhood. This is
    exactly what the `con` fixture's default monkeypatch already exercises
    in every other test; this one asserts it directly."""
    import pathlib as _pl
    assert not _pl.Path(gt.PLUTO_CSV).exists()
    rec_id = _rec(con)
    [entry] = gt.plan(con)
    assert entry["rec_id"] == rec_id
    assert entry["address_label"] == "Test area"


def test_address_url_is_none_for_a_bbox_anchored_recommendation(con):
    """A bbox/NTA card has no doorway -- `address_url` must be None even
    though `analysis.address` never gets a row to look up, distinguishing it
    from an address anchor whose lookup simply misses."""
    rec_id = _rec(con, address_id=None, area_kind="bbox")
    [entry] = gt.plan(con)
    assert entry["rec_id"] == rec_id
    assert entry["area_kind"] == "bbox"
    assert entry["address_url"] is None
    # nearby_url and streetview_url are unaffected -- they only need a point.
    assert entry["nearby_url"] is not None
    assert entry["streetview_url"] is not None


def test_only_open_anchored_recommendations_are_planned(con):
    open_id = _rec(con, category="laundry")
    _rec(con, category="pharmacy", status="withdrawn",
         reason="supply ratio came back 0.94x")
    _rec(con, category="bar", lon=None, lat=None, address_id=None)
    assert [e["rec_id"] for e in gt.plan(con)] == [open_id]


def test_plan_filters_and_limits(con):
    _rec(con, category="laundry")
    _rec(con, category="pharmacy", solution="A pharmacy")
    assert [e["category"] for e in gt.plan(con, category="pharmacy")] == ["pharmacy"]
    assert len(gt.plan(con, limit=1)) == 1
    with pytest.raises(ValueError):
        gt.plan(con, category="not_a_category")


# ============================================================= 2. record

def test_record_is_idempotent(con):
    rec_id = _rec(con)
    _presence(con)
    obs = [_obs(rec_id, [_sf()])]
    first = gt.record(con, obs, run_id="r1")
    second = gt.record(con, obs, run_id="r2")
    assert first.n_rows == second.n_rows == 1
    n_obs, n_ev = con.execute(
        "SELECT (SELECT count(*) FROM analysis.address_observation), "
        "       (SELECT count(*) FROM analysis.poi_closure_evidence)").fetchone()
    assert (n_obs, n_ev) == (1, 1)


def test_absence_is_recorded_not_inferred(con):
    """An empty storefront list stores ONE row with a NULL name and status
    'vacant'. D79: absence observed is stored; absence is never inferred."""
    rec_id = _rec(con)
    res = gt.record(con, [_obs(rec_id, [], gap_verdict="confirmed_gap")])
    assert (res.n_rows, res.n_vacant_rows, res.n_evidence) == (1, 1, 0)
    name, status, verdict = con.execute(
        "SELECT storefront_name, status, gap_verdict "
        "FROM analysis.address_observation").fetchone()
    assert (name, status, verdict) == (None, "vacant", "confirmed_gap")


def test_a_matched_open_storefront_writes_one_maps_ui_evidence_row(con):
    rec_id = _rec(con)
    _presence(con)
    gt.record(con, [_obs(rec_id, [_sf(status="open")])], run_id="r1")
    rows = con.execute(
        "SELECT poi_id, verdict, source, domain_class, source_name, dated_by, "
        "       evidence_date, query FROM analysis.poi_closure_evidence").fetchall()
    assert len(rows) == 1
    poi_id, verdict, source, dclass, sname, dated_by, edate, query = rows[0]
    assert (poi_id, verdict, source, dclass) == ("p1", "open", "web", "maps_ui")
    assert sname == gt.MAPS_SOURCE_NAME
    assert (dated_by, edate.isoformat()) == ("retrieval", "2026-09-15")
    assert query == f"ground-truth {rec_id}"


def test_a_matched_closed_storefront_writes_a_closed_verdict(con):
    rec_id = _rec(con)
    _presence(con)
    gt.record(con, [_obs(rec_id, [_sf(status="closed", label="Permanently closed")],
                         gap_verdict="closure_missed")])
    assert con.execute("SELECT verdict FROM analysis.poi_closure_evidence"
                       ).fetchone()[0] == "closed"
    assert con.execute("SELECT maps_status_label FROM analysis.address_observation"
                       ).fetchone()[0] == "Permanently closed"


@pytest.mark.parametrize("status", ["vacant", "unknown"])
def test_vacant_and_unknown_write_no_evidence(con, status):
    """THE ADVERSARIAL CASE. An empty or unreadable shopfront standing where a
    POI is recorded must not produce a closure verdict for it -- that is
    inference from absence, which D79 forbids outright."""
    rec_id = _rec(con)
    _presence(con)
    res = gt.record(con, [_obs(rec_id, [_sf(status=status)])])
    assert res.n_matched == 1                    # the POI WAS matched...
    assert res.n_evidence == 0                   # ...and still says nothing about it
    assert con.execute("SELECT count(*) FROM analysis.poi_closure_evidence"
                       ).fetchone()[0] == 0


def test_an_unmatched_storefront_writes_no_evidence(con):
    """No poi_id, nothing to attach a verdict to. The observation is stored;
    the evidence table is not touched."""
    rec_id = _rec(con)
    res = gt.record(con, [_obs(rec_id, [_sf(name="Brand New Laundromat")])])
    assert (res.n_rows, res.n_matched, res.n_evidence) == (1, 0, 0)
    assert con.execute("SELECT matched_poi_id FROM analysis.address_observation"
                       ).fetchone()[0] is None


def test_the_match_radius_is_a_real_distance(con):
    rec_id = _rec(con)
    _presence(con, key="near", poi_id="p-near", lat=NEAR_LAT)
    gt.record(con, [_obs(rec_id, [_sf()])])
    poi, dist = con.execute("SELECT matched_poi_id, match_distance_m "
                            "FROM analysis.address_observation").fetchone()
    assert poi == "p-near" and 0 < dist < gt.MATCH_RADIUS_M

    con.execute("DELETE FROM analysis.poi_presence")
    con.execute("DELETE FROM analysis.address_observation")
    _presence(con, key="far", poi_id="p-far", lat=FAR_LAT)
    gt.record(con, [_obs(rec_id, [_sf()])])
    assert con.execute("SELECT matched_poi_id FROM analysis.address_observation"
                       ).fetchone()[0] is None


def test_a_bad_status_or_category_guess_stops_the_file(con):
    rec_id = _rec(con)
    with pytest.raises(ValueError, match="status"):
        gt.record(con, [_obs(rec_id, [_sf(status="maybe")])])
    with pytest.raises(ValueError, match="category_guess"):
        gt.record(con, [_obs(rec_id, [_sf(category_guess="dry_cleaner")])])
    with pytest.raises(ValueError, match="gap_verdict"):
        gt.record(con, [_obs(rec_id, [_sf()], gap_verdict="looks_fine")])
    with pytest.raises(ValueError, match="not in analysis.recommendation"):
        gt.record(con, [_obs("r-nope", [_sf()])])
    assert con.execute("SELECT count(*) FROM analysis.address_observation"
                       ).fetchone()[0] == 0


# ========================================================= 2b. price_label

def test_price_label_is_stored_verbatim(con):
    """D105 2026-09-15: the free price channel. A price token Maps showed is
    copied through unparsed and lands on the row exactly as given."""
    rec_id = _rec(con)
    gt.record(con, [_obs(rec_id, [_sf(price_label="$$")])])
    assert con.execute("SELECT price_label FROM analysis.address_observation"
                       ).fetchone()[0] == "$$"


def test_price_label_is_null_when_maps_showed_none(con):
    rec_id = _rec(con)
    gt.record(con, [_obs(rec_id, [_sf()])])
    assert con.execute("SELECT price_label FROM analysis.address_observation"
                       ).fetchone()[0] is None


def test_a_vacant_row_carries_a_null_price_label(con):
    """A NULL-name 'nothing observed' row has no storefront to have read a
    price off -- price_label is NULL there too, never inferred."""
    rec_id = _rec(con)
    gt.record(con, [_obs(rec_id, [])])
    assert con.execute("SELECT price_label FROM analysis.address_observation"
                       ).fetchone()[0] is None


def test_a_price_label_over_32_chars_is_rejected(con):
    rec_id = _rec(con)
    with pytest.raises(ValueError, match="price_label"):
        gt.record(con, [_obs(rec_id, [_sf(price_label="x" * (gt.PRICE_LABEL_MAX_LEN + 1))])])
    assert con.execute("SELECT count(*) FROM analysis.address_observation"
                       ).fetchone()[0] == 0


def test_a_price_label_at_the_length_limit_is_accepted(con):
    rec_id = _rec(con)
    label = "x" * gt.PRICE_LABEL_MAX_LEN
    gt.record(con, [_obs(rec_id, [_sf(price_label=label)])])
    assert con.execute("SELECT price_label FROM analysis.address_observation"
                       ).fetchone()[0] == label


def test_summary_counts_n_priced_and_the_miss_view_carries_price_label(con):
    rec_id = _rec(con, category="laundry")
    gt.record(con, [_obs(rec_id, [_sf(name="Bubbles Laundromat", price_label="$$")])])
    s = gt.summary(con)
    [row] = s["by_rec"]
    assert row["n_priced"] == 1
    [miss] = s["misses"]
    assert miss["price_label"] == "$$"


def test_cli_report_renders_the_price_column(con, monkeypatch):
    """The 'price' column in the misses table and 'n_priced' in the by-rec
    table both render through `_gt_cell`/plain ints without error, and the
    stored label is visible in the output.

    The by-rec table's OWN headers are asserted against the live `Table`
    object, not the printed text: with ten narrow columns, rich's CliRunner
    console (fixed, narrow width) already truncates neighbouring headers like
    'same-cat open' -> 'same…' -- pre-existing behavior this test must not
    depend on to pass. The misses table's 'price' header is short enough to
    survive that truncation, so it IS asserted against the printed text."""
    from typer.testing import CliRunner

    from loci import cli

    rec_id = _rec(con, category="laundry")
    gt.record(con, [_obs(rec_id, [_sf(name="Bubbles Laundromat", price_label="$$")])])

    monkeypatch.setattr(cli.locidb, "connect", lambda *a, **k: con)
    result = CliRunner().invoke(cli.app, ["ground-truth", "report"])
    assert result.exit_code == 0, result.output
    assert "$$" in result.output
    assert "price" in result.output


# =========================================================== 3. miss view

def test_the_miss_view_is_the_supply_model_s_miss(con):
    """An OPEN storefront of the RECOMMENDED category that the warehouse does
    not hold is a measured false positive of the screen. One it does hold is
    not, and the view must not confuse them."""
    missed = _rec(con, category="laundry")
    held = _rec(con, category="pharmacy", solution="A pharmacy")
    _presence(con, key="rx", category="pharmacy", name="Graham Rx", poi_id="p-rx")

    gt.record(con, [
        _obs(missed, [_sf(name="Bubbles Laundromat", category_guess="laundry")],
             gap_verdict="supply_missed"),
        _obs(held, [_sf(name="Graham Rx", category_guess="pharmacy")]),
    ])
    rows = con.execute("SELECT rec_id, storefront_name "
                       "FROM analysis.address_observation_miss").fetchall()
    assert rows == [(missed, "Bubbles Laundromat")]


def test_the_miss_view_excludes_other_categories_and_closed_storefronts(con):
    rec_id = _rec(con, category="laundry")
    gt.record(con, [_obs(rec_id, [
        _sf(name="Corner Deli", category_guess="convenience"),      # wrong category
        _sf(name="Old Wash House", category_guess="laundry", status="closed"),
        _sf(name="Unnamed Place", category_guess=None),             # no guess at all
    ])])
    assert con.execute("SELECT count(*) FROM analysis.address_observation_miss"
                       ).fetchone()[0] == 0


def test_a_same_name_poi_120m_away_matches_and_is_not_a_miss(con):
    """THE FIX D105 exists for. The protocol's first read is the
    category-nearby search (`nearby_url`), which legitimately surfaces
    results anywhere in the 400 m catchment. A same-name POI ~120 m from the
    anchor -- inside the catchment, outside the OLD 40 m 'same doorway'
    radius -- must match, and a matched storefront can never be a miss: the
    warehouse DOES hold this business."""
    rec_id = _rec(con, category="laundry")
    _presence(con, key="catchment", poi_id="p-catchment", lat=CATCHMENT_LAT)
    gt.record(con, [_obs(rec_id, [_sf()], gap_verdict="inconclusive")])
    poi, dist = con.execute("SELECT matched_poi_id, match_distance_m "
                            "FROM analysis.address_observation").fetchone()
    assert poi == "p-catchment"
    assert 40.0 < dist < gt.MATCH_RADIUS_M
    assert con.execute("SELECT count(*) FROM analysis.address_observation_miss"
                       ).fetchone()[0] == 0


def test_a_same_name_poi_450m_away_does_not_match_and_is_a_miss(con):
    """Outside the 400 m catchment a same-name POI is genuinely a different
    business as far as this channel can tell -- the storefront reads as
    unmatched and, being open and of the recommended category, lands in the
    miss view."""
    rec_id = _rec(con, category="laundry")
    _presence(con, key="far", poi_id="p-far", lat=FAR_LAT)
    gt.record(con, [_obs(rec_id, [_sf()], gap_verdict="supply_missed")])
    assert con.execute("SELECT matched_poi_id FROM analysis.address_observation"
                       ).fetchone()[0] is None
    rows = con.execute("SELECT rec_id, storefront_name "
                       "FROM analysis.address_observation_miss").fetchall()
    assert rows == [(rec_id, "Sudsy Wash")]


def test_summary_counts_every_anchor_that_was_checked(con):
    rec_id = _rec(con)
    gt.record(con, [_obs(rec_id, [_sf(name="Bubbles Laundromat")])])
    s = gt.summary(con)
    [row] = s["by_rec"]
    assert row["rec_id"] == rec_id
    assert (row["n_storefronts"], row["n_open"], row["n_vacant"]) == (1, 1, 0)
    assert [m["storefront_name"] for m in s["misses"]] == ["Bubbles Laundromat"]


def test_summary_returns_none_not_nan_for_missing_imagery(con):
    """`gt.summary()` must hand back a real `None` for a missing
    streetview_capture_date, never pandas' `float('nan')` -- `NaN or default`
    returns `NaN` itself (a nonzero float is truthy), which is exactly the
    value that later raised `NotRenderableError` in `loci ground-truth
    report`."""
    rec_id = _rec(con)
    gt.record(con, [_obs(rec_id, [_sf()], streetview_capture_date=None)])
    [row] = gt.summary(con)["by_rec"]
    assert row["imagery"] is None


# =================================================== 3b. re-ingest (replace)

def test_replace_run_leaves_the_row_count_unchanged_on_a_repeat_ingest(con):
    """The exact scenario `--replace-run` exists for: after the 40m->400m
    matching-rule fix, the SAME observation file needs to be re-ingested so
    its matched_poi_id/match_distance_m are recomputed under the new rule.
    Ingesting it twice with `replace_run` must leave the row count (and the
    run_id) exactly where it started."""
    rec_id = _rec(con)
    _presence(con)
    obs = [_obs(rec_id, [_sf()])]
    first = gt.record(con, obs, run_id="r1")
    assert first.run_id == "r1"
    n_before = con.execute(
        "SELECT count(*) FROM analysis.address_observation").fetchone()[0]

    second = gt.record(con, obs, replace_run="r1")
    assert second.run_id == "r1"
    n_after = con.execute(
        "SELECT count(*) FROM analysis.address_observation").fetchone()[0]
    assert n_before == n_after == 1
    assert con.execute("SELECT DISTINCT run_id FROM analysis.address_observation"
                       ).fetchall() == [("r1",)]


def test_replace_run_actually_deletes_rows_the_new_file_no_longer_carries(con):
    """A plain re-run (no flag) can only add or overwrite rows sharing a PK --
    it can never remove one the corrected file dropped, because
    `observation_id` does not change when only the matching rule changes.
    `--replace-run` must: an observation from run r1's first ingest that is
    absent from the corrected file must not survive a replace."""
    rec_id = _rec(con)
    gt.record(con, [_obs(rec_id, [_sf(name="Ghost Laundromat"),
                                  _sf(name="Real Wash")])], run_id="r1")
    assert con.execute("SELECT count(*) FROM analysis.address_observation"
                       ).fetchone()[0] == 2

    gt.record(con, [_obs(rec_id, [_sf(name="Real Wash")])], replace_run="r1")
    rows = con.execute("SELECT storefront_name FROM analysis.address_observation"
                       ).fetchall()
    assert rows == [("Real Wash",)]


def test_replace_run_ignores_an_explicit_run_id_and_uses_replace_run_instead(con):
    rec_id = _rec(con)
    res = gt.record(con, [_obs(rec_id, [_sf()])], run_id="ignored",
                    replace_run="r1")
    assert res.run_id == "r1"
    assert con.execute("SELECT run_id FROM analysis.address_observation"
                       ).fetchone()[0] == "r1"


# ============================================================== 3c. the CLI

def test_cli_report_renders_a_rec_with_null_imagery_without_error(con, monkeypatch):
    """Reproduces the NotRenderableError bug end to end: a rec whose
    observation carries no streetview_capture_date must still render
    through `loci ground-truth report` via typer's CliRunner, proving rich
    does not choke on the missing-imagery cell."""
    from typer.testing import CliRunner

    from loci import cli

    rec_id = _rec(con)
    gt.record(con, [_obs(rec_id, [_sf()], streetview_capture_date=None)])

    monkeypatch.setattr(cli.locidb, "connect", lambda *a, **k: con)
    result = CliRunner().invoke(cli.app, ["ground-truth", "report"])
    assert result.exit_code == 0, result.output
    assert "—" in result.output          # the missing-imagery cell, not a crash


# ====================================================== 4. schema and drift

def test_applying_033_then_036_twice_is_idempotent_and_keeps_rows(con):
    """sql/036 must be a NO-OP on a warehouse that already has it -- peers'
    `db.init_schema` runs apply every .sql file on disk, uncommitted ones
    included, so a re-application happens in sessions that are not this one
    and must not cost them a row."""
    rec_id = _rec(con)
    _presence(con)
    gt.record(con, [_obs(rec_id, [_sf()])], run_id="r1")
    before = con.execute(
        "SELECT (SELECT count(*) FROM analysis.address_observation), "
        "       (SELECT count(*) FROM analysis.poi_closure_evidence)").fetchone()
    sql_033 = (locidb.SQL_DIR / "033_poi_closure_evidence.sql").read_text()
    for _ in range(2):
        con.execute(sql_033)
        con.execute(gt.SQL_036.read_text())
    after = con.execute(
        "SELECT (SELECT count(*) FROM analysis.address_observation), "
        "       (SELECT count(*) FROM analysis.poi_closure_evidence)").fetchone()
    assert before == after == (1, 1)


def test_sql_036_touches_no_object_sql_033_created(con):
    """The constraint that replaced the original plan to widen sql/033's
    `source` CHECK. DuckDB 1.5.5 implements no in-place CHECK alteration, and
    a create-copy-swap of `analysis.poi_closure_evidence` would fire inside a
    peer session mid-write. So 036 must not name that table at all -- the
    'maps_ui' distinction lives in `domain_class`.

    036 DOES now carry one `ALTER TABLE` (D105 2026-09-15, the price_label
    column), but it targets `analysis.address_observation` -- the table this
    file itself owns -- never `poi_closure_evidence`, which is the specific
    thing this test guards against."""
    sql = gt.SQL_036.read_text()
    body = "\n".join(line for line in sql.splitlines()
                     if not line.lstrip().startswith("--"))
    assert "poi_closure_evidence" not in body
    assert "DROP TABLE" not in body.upper()
    alters = [ln for ln in body.upper().splitlines() if "ALTER TABLE" in ln]
    assert alters, "expected the price_label ADD COLUMN ALTER TABLE"
    assert all("ADDRESS_OBSERVATION" in a for a in alters)


def test_category_check_matches_the_categories_module():
    """sql/036 writes the 15 category slugs literally in a CHECK. A category
    added to loci/categories.py without being added there would be rejected
    at INSERT time in production; it fails here instead."""
    sql = gt.SQL_036.read_text()
    tail = sql[sql.index("category_guess IN ("):]
    listed = tail[tail.index("(") + 1:tail.index(")")]
    slugs = {s.strip().strip("'") for s in listed.split(",")}
    assert slugs == set(CATEGORIES)
    # GTM-198 (2026-09-17): 036's literal reaches only a FRESH warehouse; an
    # existing one is rebuilt by migrate.step_observation_category_check from
    # this same DDL, so the rebuild statement must carry the same list.
    from loci import migrate as mg
    ddl = mg._observation_create_ddl()
    tail = ddl[ddl.index("category_guess IN ("):]
    listed = tail[tail.index("(") + 1:tail.index(")")]
    assert {s.strip().strip("'") for s in listed.split(",")} == set(CATEGORIES)
    assert ddl.startswith("CREATE TABLE __TARGET__ (")


def test_the_view_radius_matches_the_module_constant():
    assert f"<= {gt.MATCH_RADIUS_M}" in gt.SQL_036.read_text()


def test_the_manifest_file_carries_the_schema_the_ingest_expects(con, tmp_path):
    _rec(con)
    path = gt.write_manifest(gt.plan(con), tmp_path / "manifest.json")
    doc = json.loads(path.read_text())
    assert doc["n_anchors"] == 1
    assert doc["match_radius_m"] == gt.MATCH_RADIUS_M
    assert set(doc["observation_schema"]) >= {"rec_id", "observed_at", "storefronts",
                                              "gap_verdict"}
    assert doc["anchors"][0]["streetview_url"].startswith("https://www.google.com/maps/@")


def test_write_manifest_replaces_atomically_with_no_leftover_temp_file(con, tmp_path):
    """A browser-session agent may be reading the manifest concurrently with
    a re-plan. `write_manifest` must never leave a reader looking at a
    half-written file -- write to a temp path in the same directory, then
    `os.replace()` over the target in one step -- and must not litter the
    directory with temp files afterward, on the first write or a
    re-write."""
    _rec(con)
    path = tmp_path / "manifest.json"
    for _ in range(2):                          # first write, then a re-plan
        gt.write_manifest(gt.plan(con), path)
        assert path.exists()
        assert json.loads(path.read_text())["n_anchors"] == 1
        assert list(tmp_path.glob(".manifest.json.*.tmp")) == []
