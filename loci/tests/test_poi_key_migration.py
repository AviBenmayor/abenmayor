"""The location-key migration (model/poi_key_migration, sql/035).

Every test here is about ONE class of damage: the first-seen ledger recording
a fake opening or a fake disappearance because `location_key` changed without
the storefront changing. `first_seen_month` is write-once (sql/018), so these
are not recoverable after the fact -- which is why the guard has a test too.
"""
from __future__ import annotations

import datetime as dt
import hashlib

import duckdb
import pandas as pd
import pytest

from loci.model import poi_key_migration as km
from loci.model import poi_presence as pp


# ---------------------------------------------------------------------------
# a warehouse small enough to reason about
# ---------------------------------------------------------------------------
def _con():
    con = duckdb.connect(":memory:")
    con.execute("INSTALL spatial; LOAD spatial; INSTALL h3 FROM community; LOAD h3;")
    con.execute("CREATE SCHEMA IF NOT EXISTS analysis; CREATE SCHEMA IF NOT EXISTS staging;")
    con.execute("CREATE SCHEMA IF NOT EXISTS chains;")
    con.execute(pp.SQL_018.read_text())
    con.execute((pp.SQL_018.parent / "027_poi_closure.sql").read_text())
    con.execute((pp.SQL_018.parent / "015_chains.sql").read_text())
    con.execute((pp.SQL_018.parent / "026_recommendation.sql").read_text())
    km.ensure_schema(con)
    con.execute("""
        CREATE TABLE IF NOT EXISTS analysis.poi_dedup (
            poi_id VARCHAR PRIMARY KEY, cluster_id BIGINT NOT NULL,
            is_canonical BOOLEAN NOT NULL, category VARCHAR NOT NULL)""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS staging.poi (
            poi_id VARCHAR PRIMARY KEY, source_id VARCHAR, name VARCHAR,
            geom GEOMETRY, opened_on DATE, attrs VARCHAR)""")
    con.execute("CREATE TABLE IF NOT EXISTS analysis.hex (h3_index VARCHAR, borough VARCHAR)")
    return con


def _poi(con, poi_id, cluster_id, category, name, lon, lat, canonical=True,
         source="s1"):
    con.execute("INSERT INTO staging.poi VALUES (?, ?, ?, ST_Point(?, ?), NULL, '{}')",
                [poi_id, source, name, lon, lat])
    con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                [poi_id, cluster_id, canonical, category])


def _ledger(con, key, category, name_key, display, lon, lat, *,
            first_seen_month="2026-09", last_seen_month="2026-09",
            kind="backfill_censored", n_months=1, closed_on=None, closed_src=None,
            poi_id=None, src_date=None, src_field=None):
    con.execute("""
        INSERT INTO analysis.poi_presence
            (location_key, category, name_key, display_name, lon, lat, borough,
             first_seen_month, last_seen_month, first_seen_kind,
             first_seen_src_date, first_seen_src_field, n_months_seen,
             cluster_id_latest, poi_id_latest, ledger_started_month,
             last_snapshot_at, closed_on, closed_src)
        VALUES (?, ?, ?, ?, ?, ?, 'Brooklyn', ?, ?, ?, ?, ?, ?, NULL, ?, '2026-09',
                now(), ?, ?)""",
        [key, category, name_key, display, lon, lat, first_seen_month,
         last_seen_month, kind, src_date, src_field, n_months, poi_id,
         closed_on, closed_src])


# ---------------------------------------------------------------------------
# content_key must not drift away from mint_key
# ---------------------------------------------------------------------------
def test_content_key_is_mint_key_minus_category():
    """The migration's whole identity claim. If these two ever disagree, a
    'mapped' row stops meaning "only the category changed"."""
    for cat, nk, lon, lat, pid in (
            ("restaurant", "joes pizza", -73.9442, 40.7081, "p1"),
            ("cafe_bakery", "", -73.9442, 40.7081, "p2"),
            ("bar", "the four horsemen", -73.95511, 40.70992, "p3")):
        payload = cat + "|" + km.content_key(nk, lon, lat, pid)
        expect = "loc_" + hashlib.blake2b(payload.encode(), digest_size=8).hexdigest()
        assert pp.mint_key(cat, nk, lon, lat, pid) == expect


# ---------------------------------------------------------------------------
# 1. category-only re-mint maps 1:1
# ---------------------------------------------------------------------------
def test_category_only_remint_maps_one_to_one():
    con = _con()
    lon, lat, name = -73.9442, 40.7081, "Joes Pizza"
    nk = pp.name_key_of(name)
    old = pp.mint_key("restaurant", nk, lon, lat, "p1")
    _ledger(con, old, "restaurant", nk, name, lon, lat, poi_id="p1")
    # The B rule: the same storefront is now cafe_bakery.
    _poi(con, "p1", 1, "cafe_bakery", name, lon, lat)

    res = km.plan(con)
    assert res.mapped == 1 and res.merged_groups == 0 and res.unmapped == 0
    assert res.collisions == 0
    assert res.relabel_poi == 1, "the canonical poi_id is the strongest route"
    row = con.execute("SELECT old_key, new_key, reason, old_category, new_category "
                      "FROM analysis.poi_key_map").fetchone()
    assert row[0] == old
    assert row[1] == pp.mint_key("cafe_bakery", nk, lon, lat, "p1")
    assert (row[2], row[3], row[4]) == ("relabel_poi", "restaurant", "cafe_bakery")

    km.apply(con)
    got = con.execute("SELECT location_key, category, first_seen_month, "
                      "first_seen_kind FROM analysis.poi_presence").fetchone()
    assert got[0] == row[1]
    # THE CATEGORY MOVES WITH THE KEY, or pass A rejects the row next month.
    assert got[1] == "cafe_bakery"
    assert got[2] == "2026-09" and got[3] == "backfill_censored"
    assert con.execute("SELECT count(*) FROM analysis.poi_presence").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# 2. a merge keeps the earliest first_seen and the latest last_seen
# ---------------------------------------------------------------------------
def test_merge_keeps_earliest_first_seen_and_latest_last_seen():
    con = _con()
    lon, lat, name = -73.9550, 40.7099, "Four Horsemen"
    nk = pp.name_key_of(name)
    a = pp.mint_key("restaurant", nk, lon, lat, "p1")
    b = pp.mint_key("bar", nk, lon, lat, "p1")
    # Two ledger rows the dedup is now collapsing into one 'bar' cluster whose
    # canonical poi is p1 -- so `b` is one of the two old keys AND, for a
    # nameless row, would be the target. Here the name is non-empty, so the
    # target key is a function of the category only.
    _ledger(con, a, "restaurant", nk, name, lon, lat, first_seen_month="2019-03",
            kind="source_date", src_date=dt.date(2019, 3, 4),
            src_field="license_issue_date", last_seen_month="2026-09", n_months=1,
            poi_id="p1")
    _ledger(con, b, "bar", nk, name, lon, lat, first_seen_month="2026-09",
            kind="backfill_censored", last_seen_month="2026-10", n_months=2,
            poi_id="p2", closed_on=dt.date(2026, 8, 1), closed_src="foursquare:key")
    # Both fold into ONE new cluster. p1/p2 are MEMBERS of it -- that
    # membership is the dedup's own assertion that these were one business,
    # and it is the only evidence that authorises a merge.
    _poi(con, "p9", 7, "cafe_bakery", name, lon, lat)
    _poi(con, "p1", 7, "cafe_bakery", name, lon, lat, canonical=False)
    _poi(con, "p2", 7, "cafe_bakery", name, lon, lat, canonical=False)

    res = km.plan(con)
    assert res.merged_groups == 1 and res.merged_old_keys == 2
    assert res.mapped == 0 and res.unmapped == 0 and res.collisions == 0

    km.apply(con)
    rows = con.execute(
        "SELECT location_key, category, first_seen_month, first_seen_kind, "
        "first_seen_src_date, last_seen_month, n_months_seen, closed_on, "
        "ledger_started_month FROM analysis.poi_presence").fetchall()
    assert len(rows) == 1, "the merge must leave exactly one row"
    r = rows[0]
    assert r[0] == pp.mint_key("cafe_bakery", nk, lon, lat, "p9")
    assert r[1] == "cafe_bakery"
    assert r[2] == "2019-03", "earliest first_seen wins"
    assert r[3] == "source_date" and r[4] == dt.date(2019, 3, 4)
    assert r[5] == "2026-10", "latest last_seen wins"
    assert r[6] == 2, "n_months_seen is the MAX, never the sum"
    assert r[7] == dt.date(2026, 8, 1), "closures are unioned, not dropped"
    assert r[8] == "2026-09"


# ---------------------------------------------------------------------------
# 3. unmapped is never deleted
# ---------------------------------------------------------------------------
def test_unmapped_is_recorded_and_never_deleted():
    con = _con()
    lon, lat, name = -73.99, 40.71, "Gone Deli"
    nk = pp.name_key_of(name)
    gone = pp.mint_key("bodega", nk, lon, lat, "p1")
    _ledger(con, gone, "bodega", nk, name, lon, lat, last_seen_month="2026-09",
            poi_id="p1")
    # A completely different storefront is all the dedup now holds.
    _poi(con, "p2", 2, "laundry", "Sudsy", -73.88, 40.68)

    res = km.plan(con)
    assert res.unmapped == 1 and res.mapped == 0 and res.merged_groups == 0
    assert res.new_keys == 1
    km.apply(con)
    row = con.execute("SELECT location_key, last_seen_month FROM "
                      "analysis.poi_presence").fetchone()
    assert row == (gone, "2026-09"), "an unmapped row is left exactly as it was"
    assert con.execute("SELECT reason, new_key FROM analysis.poi_key_map "
                       "WHERE old_key = ?", [gone]).fetchone() == ("unmapped", None)


# ---------------------------------------------------------------------------
# 4. apply is idempotent
# ---------------------------------------------------------------------------
def test_apply_is_idempotent():
    con = _con()
    lon, lat, name = -73.9442, 40.7081, "Joes Pizza"
    nk = pp.name_key_of(name)
    _ledger(con, pp.mint_key("restaurant", nk, lon, lat, "p1"), "restaurant", nk,
            name, lon, lat, poi_id="p1")
    _poi(con, "p1", 1, "cafe_bakery", name, lon, lat)
    km.plan(con)
    first = km.apply(con)
    before = con.execute("SELECT * FROM analysis.poi_presence").fetchdf()
    second = km.apply(con)
    after = con.execute("SELECT * FROM analysis.poi_presence").fetchdf()
    assert second.noop, "a second apply finds no pending plan"
    assert first.n_rows_migrated == 1
    pd.testing.assert_frame_equal(before, after)
    # And a re-plan against the SAME dedup now finds nothing to do.
    again = km.plan(con)
    assert again.mapped == 0 and again.merged_groups == 0 and again.unmapped == 0


# ---------------------------------------------------------------------------
# 5. the guard refuses and allows
# ---------------------------------------------------------------------------
def test_guard_allows_small_drift_and_refuses_large():
    con = _con()
    # 200 ledger rows, 200 matching clusters -> zero drift.
    for i in range(200):
        lon, lat = -73.94 + i * 0.001, 40.70 + i * 0.001
        nk = pp.name_key_of(f"Shop {i}")
        _ledger(con, pp.mint_key("bodega", nk, lon, lat, f"p{i}"), "bodega", nk,
                f"Shop {i}", lon, lat, poi_id=f"p{i}")
        _poi(con, f"p{i}", i, "bodega", f"Shop {i}", lon, lat)
    stats = km.guard_snapshot(con)
    assert stats["ok"] and stats["n_absent"] == 0

    # Recategorise 40 of 200 (20%, far over the 0.5% threshold).
    con.execute("UPDATE analysis.poi_dedup SET category = 'cafe_bakery' "
                "WHERE cluster_id < 40")
    with pytest.raises(km.KeyDriftError) as exc:
        km.guard_snapshot(con)
    assert "poi-keys plan" in str(exc.value)

    # A PLANNED but UNAPPLIED map is NOT a pass -- that is the state in which
    # the snapshot writes the fake openings.
    month = dt.date.today().strftime("%Y-%m")
    km.plan(con)
    with pytest.raises(km.KeyDriftError) as exc2:
        km.guard_snapshot(con, month=month)
    assert "PLANNED BUT NOT APPLIED" in str(exc2.value)

    # Applied -> allowed.
    km.apply(con)
    stats = km.guard_snapshot(con, month=month)
    assert stats["ok"] and stats["n_absent"] == 0

    # --force always bypasses, as it does for the out-of-order-month refusal.
    con.execute("UPDATE analysis.poi_dedup SET category = 'laundry'")
    assert km.guard_snapshot(con, force=True)["bypass"] == "force"


def test_guard_refuses_rather_than_trusting_an_empty_dedup():
    """A silent zero here would wave through a snapshot marking every
    storefront in the city as disappeared."""
    con = _con()
    _ledger(con, "loc_x", "bodega", "shop", "Shop", -73.9, 40.7, poi_id="p1")
    with pytest.raises(RuntimeError, match="poi_dedup is empty"):
        km.guard_snapshot(con)


# ---------------------------------------------------------------------------
# 6. chains and recommendation-outcome keys are rewritten
# ---------------------------------------------------------------------------
def test_dependent_tables_are_rewritten_and_brand_location_pk_survives_a_merge():
    con = _con()
    lon, lat, name = -73.9550, 40.7099, "Four Horsemen"
    nk = pp.name_key_of(name)
    a = pp.mint_key("restaurant", nk, lon, lat, "p1")
    b = pp.mint_key("bar", nk, lon, lat, "p2")
    _ledger(con, a, "restaurant", nk, name, lon, lat, poi_id="p1")
    _ledger(con, b, "bar", nk, name, lon, lat, poi_id="p2")
    _poi(con, "p9", 7, "cafe_bakery", name, lon, lat)
    _poi(con, "p1", 7, "cafe_bakery", name, lon, lat, canonical=False)
    _poi(con, "p2", 7, "cafe_bakery", name, lon, lat, canonical=False)
    new = pp.mint_key("cafe_bakery", nk, lon, lat, "p9")

    # BOTH old keys under ONE brand in ONE month: after the merge they collide
    # on chains.brand_location's (snapshot_month, brand_key, location_key) PK.
    for k, pid in ((a, "p1"), (b, "p2")):
        con.execute("INSERT INTO chains.brand_location VALUES "
                    "('2026-09', 'fourhorsemen', ?, ?, 'restaurant', 'Brooklyn', "
                    "?, ?, NULL, NULL)", [k, pid, lon, lat])
    con.execute("INSERT INTO analysis.recommendation_outcome (rec_id, "
                "snapshot_month, matched_location_key, match_kind, quality_json, "
                "snapshot_at) VALUES ('r1', '2026-09', ?, 'opened', '{}', now())",
                [a])
    con.execute("INSERT INTO staging.poi_closure VALUES "
                "('fsq1', ?, 'bar', ?, ?, ?, NULL, DATE '2026-05-01', "
                "'foursquare', now())", [b, name, lon, lat])

    km.plan(con)
    res = km.apply(con)
    assert res.n_merged_groups == 1

    assert con.execute("SELECT location_key FROM chains.brand_location"
                       ).fetchall() == [(new,)], "PK collision collapsed, not raised"
    assert res.dependents["chains.brand_location"]["collapsed"] == 1
    assert con.execute("SELECT matched_location_key FROM "
                       "analysis.recommendation_outcome").fetchone()[0] == new
    assert con.execute("SELECT location_key FROM staging.poi_closure"
                       ).fetchone()[0] == new


# ---------------------------------------------------------------------------
# 7. refusals
# ---------------------------------------------------------------------------
def test_occupied_target_on_a_weak_route_is_refused_not_merged():
    """A CONTENT-route candidate landing on a key a surviving ledger row holds
    is refused. Only the dedup's own membership authorises a merge; a name +
    4 dp cell match landing on an occupied key would fuse two histories onto
    one storefront on no evidence at all.

    (The same shape on a POI route IS allowed and is tested above -- that is
    the B rule's dominant case. The difference is the evidence, not the shape.)
    """
    con = _con()
    lon, lat, name = -73.9442, 40.7081, "Joes Pizza"
    nk = pp.name_key_of(name)
    old = pp.mint_key("restaurant", nk, lon, lat, "p1")
    new_key = pp.mint_key("cafe_bakery", nk, lon, lat, "p9")
    # `old` has no live poi_id -> content route only. `new_key` is already held.
    _ledger(con, old, "restaurant", nk, name, lon, lat, poi_id=None)
    _ledger(con, new_key, "cafe_bakery", nk, name, lon, lat, poi_id="p9")
    _poi(con, "p9", 1, "cafe_bakery", name, lon, lat)

    res = km.plan(con)
    assert res.collisions == 1 and res.mapped == 0 and res.merged_groups == 0
    assert con.execute("SELECT reason FROM analysis.poi_key_map "
                       "WHERE old_key = ?", [old]).fetchone()[0] == "collision"
    km.apply(con)  # nothing actionable
    assert con.execute("SELECT count(*) FROM analysis.poi_presence "
                       "WHERE location_key = ?", [old]).fetchone()[0] == 1


def test_migration_report_flags_a_half_landed_apply():
    con = _con()
    lon, lat, name = -73.9442, 40.7081, "Joes Pizza"
    nk = pp.name_key_of(name)
    old = pp.mint_key("restaurant", nk, lon, lat, "p1")
    _ledger(con, old, "restaurant", nk, name, lon, lat, poi_id="p1")
    _poi(con, "p1", 1, "cafe_bakery", name, lon, lat)
    km.plan(con)
    km.apply(con)
    assert km.migration_report(con)["errors"] == []
    # Simulate the apply half-landing: the map says applied, the ledger did not
    # move. The next snapshot would mint the new key BESIDE the stale old one.
    con.execute("UPDATE analysis.poi_presence SET location_key = ?", [old])
    rep = km.migration_report(con)
    assert rep["stale_old_keys"] == 1 and rep["errors"]


# ---------------------------------------------------------------------------
# 8. the dominant shape of the B rule: absorbed into a key that ALREADY EXISTS
# ---------------------------------------------------------------------------
def test_merge_into_a_key_a_ledger_row_already_holds():
    """8,415 of the B rule's 12,011 absorbed clusters land on a key a surviving
    ledger row already holds. Refusing those (the naive conservative choice)
    would strand 8,415 histories and report them as disappearances -- the exact
    damage this module exists to prevent. The sitting row is folded IN, not
    overwritten, so its first_seen survives."""
    con = _con()
    lon, lat = -73.9550, 40.7099
    nk_r, nk_c = pp.name_key_of("Joes Pizza"), pp.name_key_of("Joes Cafe")
    # The surviving cluster: an aggregator cafe_bakery whose key does not move.
    survivor = pp.mint_key("cafe_bakery", nk_c, lon, lat, "p9")
    _ledger(con, survivor, "cafe_bakery", nk_c, "Joes Cafe", lon, lat,
            first_seen_month="2026-09", kind="backfill_censored",
            last_seen_month="2026-09", n_months=1, poi_id="p9")
    # The absorbed one: a DOHMH restaurant record, dated 2014, different name.
    absorbed = pp.mint_key("restaurant", nk_r, lon, lat, "p1")
    _ledger(con, absorbed, "restaurant", nk_r, "Joes Pizza", lon, lat,
            first_seen_month="2014-06", kind="source_date",
            src_date=dt.date(2014, 6, 2), src_field="license_issue_date",
            last_seen_month="2026-09", n_months=1, poi_id="p1")
    _poi(con, "p9", 7, "cafe_bakery", "Joes Cafe", lon, lat)
    _poi(con, "p1", 7, "cafe_bakery", "Joes Pizza", lon, lat, canonical=False)

    res = km.plan(con)
    assert res.merged_groups == 1 and res.merged_into_existing == 1
    assert res.collisions == 0, "an occupied MERGE target is allowed; the dedup said so"
    ap = km.apply(con)
    assert ap.n_merged_into_existing == 1
    rows = con.execute("SELECT location_key, first_seen_month, first_seen_kind, "
                       "n_months_seen FROM analysis.poi_presence").fetchall()
    assert len(rows) == 1 and rows[0][0] == survivor
    assert rows[0][1] == "2014-06" and rows[0][2] == "source_date", (
        "the absorbed row's older, DATED first_seen must survive the merge")
    assert km.apply(con).noop


def test_a_content_match_may_relabel_but_never_merge():
    """A name + 4 dp cell match is evidence of a relabelling, never evidence
    that two storefronts are one business. Merging on it would be the
    fusing-distinct-storefronts bug wearing a costume."""
    con = _con()
    lon, lat, name = -73.9550, 40.7099, "Corner Deli"
    nk = pp.name_key_of(name)
    a = pp.mint_key("restaurant", nk, lon, lat, "pA")
    b = pp.mint_key("bodega", nk, lon, lat, "pB")
    # Neither ledger row has a LIVE poi_id (the ledger NULLs poi_id_latest on
    # rows behind the newest month), so only the content route is available.
    _ledger(con, a, "restaurant", nk, name, lon, lat, poi_id=None)
    _ledger(con, b, "bodega", nk, name, lon, lat, poi_id=None)
    _poi(con, "p9", 7, "cafe_bakery", name, lon, lat)

    res = km.plan(con)
    assert res.merged_groups == 0, "two content-route rows may NOT be merged"
    assert res.collisions == 2
    km.apply(con)
    assert con.execute("SELECT count(*) FROM analysis.poi_presence").fetchone()[0] == 2
