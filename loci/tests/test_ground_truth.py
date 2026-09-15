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
  * `test_category_check_matches_the_categories_module` and
    `test_the_view_radius_matches_the_module_constant` -- drift checks. The
    CHECK list and the 40 m radius are written literally in sql/036; these
    pin them to `loci.categories.CATEGORIES` and
    `ground_truth.MATCH_RADIUS_M`, so widening one without the other fails
    the suite instead of silently disagreeing at runtime.

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

#: ~0.0001 degrees of latitude is ~11 m -- inside the 40 m match radius.
#: ~0.0010 is ~111 m, comfortably outside it. Both are asserted, not assumed,
#: in `test_the_match_radius_is_a_real_distance`.
NEAR_LAT = ANCHOR_LAT + 0.0001
FAR_LAT = ANCHOR_LAT + 0.0010


# --------------------------------------------------------------- fixtures

@pytest.fixture()
def con():
    """A synthetic warehouse carrying the REAL sql/018 + 026 + 033 + 036 DDL
    (via `ground_truth.ensure_schema`, the same path the CLI takes), so a
    schema change upstream breaks these tests instead of quietly invalidating
    them."""
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute("CREATE SCHEMA IF NOT EXISTS staging")
    c.execute("CREATE TABLE analysis.address (address_id VARCHAR, borough VARCHAR, "
              "street_name VARCHAR, neighborhood VARCHAR)")
    c.execute("INSERT INTO analysis.address VALUES "
              "('bk-1', 'BK', 'GRAHAM AVENUE', 'Williamsburg')")
    gt.ensure_schema(c)
    yield c
    c.close()


def _rec(con, *, category="laundry", status="open", address_id="bk-1",
         lon=ANCHOR_LON, lat=ANCHOR_LAT, solution="A 24/7 staffed laundromat",
         grade="C", reason=None):
    row = rl._row(issued_on=ISSUED, issued_by="test", area_kind="address",
                  area_id=address_id or "box", area_label="Test area",
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


def _obs(rec_id, storefronts, *, gap_verdict="confirmed_gap", observed_at=OBSERVED):
    return {"rec_id": rec_id, "observed_at": observed_at, "observer": "abenmayor",
            "maps_url": gt.maps_url(ANCHOR_LAT, ANCHOR_LON),
            "streetview_url": gt.streetview_url(ANCHOR_LAT, ANCHOR_LON),
            "streetview_capture_date": "2025-06", "screenshot_path": None,
            "storefronts": storefronts, "gap_verdict": gap_verdict, "notes": None}


def _sf(name="Sudsy Wash", *, category_guess="laundry", status="open",
        label=None, notes=None):
    return {"name": name, "category_guess": category_guess, "status": status,
            "maps_status_label": label, "notes": notes}


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
    # The label comes from analysis.address when the anchor is an address.
    assert entry["address_label"] == "GRAHAM AVENUE — Williamsburg — BK"
    assert entry["category"] == "laundry"
    assert entry["proposed_solution"] == "A 24/7 staffed laundromat"


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


def test_summary_counts_every_anchor_that_was_checked(con):
    rec_id = _rec(con)
    gt.record(con, [_obs(rec_id, [_sf(name="Bubbles Laundromat")])])
    s = gt.summary(con)
    [row] = s["by_rec"]
    assert row["rec_id"] == rec_id
    assert (row["n_storefronts"], row["n_open"], row["n_vacant"]) == (1, 1, 0)
    assert [m["storefront_name"] for m in s["misses"]] == ["Bubbles Laundromat"]


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
    'maps_ui' distinction lives in `domain_class`."""
    sql = gt.SQL_036.read_text()
    body = "\n".join(line for line in sql.splitlines()
                     if not line.lstrip().startswith("--"))
    assert "poi_closure_evidence" not in body
    assert "DROP TABLE" not in body.upper()
    assert "ALTER TABLE" not in body.upper()


def test_category_check_matches_the_categories_module():
    """sql/036 writes the 15 category slugs literally in a CHECK. A category
    added to loci/categories.py without being added there would be rejected
    at INSERT time in production; it fails here instead."""
    sql = gt.SQL_036.read_text()
    tail = sql[sql.index("category_guess IN ("):]
    listed = tail[tail.index("(") + 1:tail.index(")")]
    slugs = {s.strip().strip("'") for s in listed.split(",")}
    assert slugs == set(CATEGORIES)


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
