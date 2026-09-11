"""Tests for the ACTIVE filter and the CORROBORATED flag (D36 / D47).

Two things are being pinned here, and they matter for different reasons.

The ACTIVE filter is the one place in the pipeline where a supply record is
DELETED on a proxy rather than an observation ("not inspected in N months" is
not "closed"). Every default in it therefore has to fail SAFE — toward keeping
supply — because a filter that over-removes manufactures the exact retail gaps
this project exists to detect. The tests below assert each of those defaults
explicitly: never-inspected is active, no-expiry is active, and a source with
no activity signal at all is active.

The CORROBORATED flag is the opposite risk: it is cheap to compute and
tempting to trust, but "one feed saw it" is confounded with dedup source rank
(a Foursquare row can only be canonical when NO higher-ranked feed is in its
cluster), so the view must define corroboration over ALL cluster members, not
the canonical row. That is asserted directly.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from loci.db import connect, init_schema
from loci.model import zbp_compare
from loci.score import supply
from loci.sources.cities.nyc import dohmh, nys_dos

TODAY = dt.date(2026, 9, 8)


# --------------------------------------------------------------- DOHMH active
def test_dohmh_active_state_defaults_toward_keeping_supply():
    # never inspected -> ACTIVE. 12% of CAMIS are permitted-but-uninspected and
    # are the NEWEST establishments; marking them stale would delete new supply.
    assert dohmh.active_state(None, False, today=TODAY) == (True, "never_inspected")


def test_dohmh_active_state_stale_boundary_is_inclusive_of_n_months():
    n = dohmh.STALE_DAYS
    on_the_line = TODAY - dt.timedelta(days=n)
    just_over = TODAY - dt.timedelta(days=n + 1)
    assert dohmh.active_state(on_the_line, False, today=TODAY)[0] is True
    active, basis = dohmh.active_state(just_over, False, today=TODAY)
    assert active is False
    assert basis.startswith("stale_")


def test_dohmh_active_state_closed_at_last_inspection():
    recent = TODAY - dt.timedelta(days=10)
    assert dohmh.active_state(recent, True, today=TODAY) == (False, "closed_at_last_inspection")
    assert dohmh.active_state(recent, False, today=TODAY)[0] is True


def test_dohmh_stale_months_is_a_parameter_not_a_constant():
    """The 24-month cut is a judgement call (~1.4x the empirical p90 gap), so
    the 18-month sensitivity must be runnable without editing the module."""
    d = TODAY - dt.timedelta(days=600)          # ~19.7 months
    assert dohmh.active_state(d, False, today=TODAY)[0] is True           # 24m: active
    assert dohmh.active_state(d, False, today=TODAY, stale_days=int(18 * 30.44))[0] is False


def test_dohmh_normalize_aggregates_activity_over_all_rows_of_a_camis():
    """The feed is one row per VIOLATION. Taking the first row's date would
    read a 2019 violation as the establishment's last inspection and delete a
    restaurant inspected last month."""
    a = dohmh.DohmhAdapter()
    recent = (TODAY - dt.timedelta(days=30)).isoformat()
    raw = [
        {"camis": "1", "dba": "JOE PIZZA", "cuisine_description": "Pizza",
         "latitude": "40.7", "longitude": "-73.9",
         "inspection_date": "2019-01-05T00:00:00.000",
         "action": "Violations were cited in the following area(s)."},
        {"camis": "1", "dba": "JOE PIZZA", "cuisine_description": "Pizza",
         "latitude": "40.7", "longitude": "-73.9",
         "inspection_date": f"{recent}T00:00:00.000",
         "action": "No violations were recorded at the time of this inspection.",
         "grade": "A", "grade_date": f"{recent}T00:00:00.000"},
    ]
    (rec,) = list(a.normalize(raw))
    assert rec.attrs["last_inspection_date"] == recent
    assert rec.attrs["active"] is True
    assert rec.attrs["n_inspection_rows"] == 2
    assert rec.attrs["grade"] == "A"


def test_dohmh_normalize_sentinel_date_is_not_an_inspection():
    a = dohmh.DohmhAdapter()
    raw = [{"camis": "9", "dba": "BRAND NEW", "cuisine_description": "Thai",
            "latitude": "40.7", "longitude": "-73.9",
            "inspection_date": "1900-01-01T00:00:00.000", "action": None}]
    (rec,) = list(a.normalize(raw))
    assert rec.attrs["last_inspection_date"] is None
    assert rec.attrs["active_basis"] == "never_inspected"
    assert rec.attrs["active"] is True


def test_dohmh_normalize_reopen_on_the_same_day_cancels_the_closure():
    """A DOHMH closure is a health action, not a business closure, and is
    routinely followed by a re-open. Only a closure with no re-open counts."""
    a = dohmh.DohmhAdapter()
    d = (TODAY - dt.timedelta(days=5)).isoformat()
    base = {"camis": "3", "dba": "SHUT", "cuisine_description": "Italian",
            "latitude": "40.7", "longitude": "-73.9",
            "inspection_date": f"{d}T00:00:00.000"}
    closed_only = [dict(base, action="Establishment Closed by DOHMH. Violations were cited.")]
    (rec,) = list(a.normalize(closed_only))
    assert rec.attrs["active"] is False

    with_reopen = closed_only + [dict(base, action="Establishment re-opened by DOHMH.")]
    (rec2,) = list(a.normalize(with_reopen))
    assert rec2.attrs["active"] is True


# ------------------------------------------------------------- NYS DOS active
def test_nys_dos_active_state():
    assert nys_dos.active_state(dt.date(2028, 12, 11), today=TODAY)[0] is True
    assert nys_dos.active_state(dt.date(2025, 1, 1), today=TODAY)[0] is False
    # A NULL expiry is a publishing gap, never evidence of lapse.
    assert nys_dos.active_state(None, today=TODAY) == (True, "no_expiration_date")


def test_nys_dos_normalize_carries_the_expiry_and_the_verdict():
    a = nys_dos.NysDosAdapter()
    raw = [{"license_number": "AEB-1", "license_type": "DOSAEBUSINESS",
            "business_name": "Bleu Sur Bleu", "business_city": "New York",
            "business_zip": "10003",
            "license_issue_date": "12/11/2020",
            "license_cur_effective_term": "2024-12-11T00:00:00.000",
            "license_expiration_date": "2028-12-11T00:00:00.000",
            "georeference": {"type": "Point", "coordinates": [-73.99432, 40.7314]}}]
    (rec,) = list(a.normalize(raw))
    assert rec.attrs["license_expiration_date"] == "2028-12-11"
    assert rec.attrs["license_active"] is True
    assert rec.attrs["active"] is True


def test_nys_dos_assert_active_only_fails_loud_if_the_snapshot_changes():
    """0 of 32,178 licences are expired (probed 2026-09-08). If DOS ever starts
    publishing lapsed rows, ingest must STOP, not quietly inflate salon counts."""
    a = nys_dos.NysDosAdapter()
    expired = [{"license_number": f"AEB-{i}", "license_type": "DOSAEBUSINESS",
                "business_name": f"Salon {i}", "business_city": "New York",
                "business_zip": "10003",
                "license_expiration_date": "2020-01-01T00:00:00.000",
                "georeference": {"type": "Point", "coordinates": [-73.99, 40.73]}}
               for i in range(10)]
    with pytest.raises(RuntimeError, match="survivorship"):
        list(a.normalize(expired))


# ------------------------------------------------- analysis.poi_supply (view)
def _seed(con, rows):
    """rows: (poi_id, source_id, category, name, lon, lat, cluster_id,
    is_canonical, active_or_None)."""
    for (pid, src, cat, name, lon, lat, cid, canon, active) in rows:
        attrs = {} if active is None else {"active": active, "active_basis": "test"}
        con.execute(
            "INSERT INTO staging.poi (poi_id, source_id, source_record_id, category, tier, "
            "name, geom, confidence, attrs) VALUES (?, ?, ?, ?, 3, ?, ST_Point(?, ?), 0.5, "
            "CAST(? AS JSON))",
            [pid, src, pid, cat, name, lon, lat, json.dumps(attrs)])
        con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                    [pid, cid, canon, cat])


@pytest.fixture()
def supply_db():
    con = connect(":memory:")
    init_schema(con)
    _seed(con, [
        # cluster 1: two feeds saw it -> CORROBORATED. DOHMH is canonical.
        ("dohmh:1", "nyc_dohmh_restaurants", "restaurant", "Joe", -73.9, 40.7, 1, True, True),
        ("ovt:1", "overture_places", "restaurant", "Joe", -73.9, 40.7, 1, False, None),
        # cluster 2: one feed only, and it says CLOSED.
        ("dohmh:2", "nyc_dohmh_restaurants", "restaurant", "Gone", -73.8, 40.7, 2, True, False),
        # cluster 3: one feed only, no activity signal at all (aggregator).
        ("ovt:3", "overture_places", "fitness", "Gym", -73.7, 40.7, 3, True, None),
        # cluster 4: two rows, SAME feed -> NOT corroborated.
        ("ovt:4a", "overture_places", "fitness", "Yoga", -73.6, 40.7, 4, True, None),
        ("ovt:4b", "overture_places", "fitness", "Yoga", -73.6, 40.7, 4, False, None),
    ])
    return con


def test_view_row_count_equals_canonical_count(supply_db):
    """The view must be exactly the canonical set relabelled -- never a
    different population. A silent drop here would look like a retail gap."""
    n_view = supply_db.execute("SELECT count(*) FROM analysis.poi_supply").fetchone()[0]
    n_canon = supply_db.execute(
        "SELECT count(*) FROM analysis.poi_dedup WHERE is_canonical").fetchone()[0]
    assert n_view == n_canon == 4


def test_in_all_is_true_on_every_row(supply_db):
    assert supply_db.execute(
        "SELECT count(*) FROM analysis.poi_supply WHERE NOT in_all").fetchone()[0] == 0


def test_corroborated_counts_all_cluster_members_not_the_canonical_source(supply_db):
    got = dict(supply_db.execute(
        "SELECT poi_id, is_corroborated FROM analysis.poi_supply").fetchall())
    assert got["dohmh:1"] is True      # two DISTINCT feeds in the cluster
    assert got["dohmh:2"] is False
    assert got["ovt:3"] is False
    assert got["ovt:4a"] is False      # two rows, ONE feed -> not corroboration


def test_active_defaults_true_when_the_source_publishes_no_signal(supply_db):
    """Absence of evidence is not evidence of closure. fitness and hardware
    have no licence anchor at all; defaulting them inactive would erase both
    categories outright."""
    got = dict(supply_db.execute(
        "SELECT poi_id, is_active FROM analysis.poi_supply").fetchall())
    assert got["ovt:3"] is True
    assert got["dohmh:1"] is True
    assert got["dohmh:2"] is False     # only an EXPLICIT false excludes


def test_active_testable_separates_a_verdict_from_a_default(supply_db):
    """Without this column, "fitness ACTIVE = 10,416" reads as verified-open
    when it is only a default. The distinction has to live in the data."""
    got = dict(supply_db.execute(
        "SELECT poi_id, active_testable FROM analysis.poi_supply").fetchall())
    assert got["dohmh:1"] is True
    assert got["dohmh:2"] is True
    assert got["ovt:3"] is False
    assert got["ovt:4a"] is False


def test_active_corroborated_is_the_conjunction(supply_db):
    rows = supply_db.execute(
        "SELECT poi_id FROM analysis.poi_supply WHERE is_active_corroborated").fetchall()
    assert [r[0] for r in rows] == ["dohmh:1"]


# ------------------------------------------------------ supply-set plumbing
def test_supply_set_names_fail_closed():
    """A typo'd set name must RAISE, never quietly fall back to 'all'. The
    silent-default failure mode is invisible: the screen would keep running
    and simply count a different, larger, supply."""
    assert set(zbp_compare.SUPPLY_SETS) == {
        # the three D52 screening sets ...
        "all", "principled", "corroborated",
        # ... the anchor-coverage numerator, and the two ACTIVE slices, both
        # validation-only (see zbp_compare.SUPPLY_SETS' comment).
        "registry_anchored", "active", "active_corroborated"}
    assert zbp_compare._supply_predicate("corroborated") == "is_corroborated"
    with pytest.raises(ValueError, match="unknown supply set"):
        zbp_compare._supply_predicate("corrobrated")


def test_zbp_compare_and_score_agree_on_what_each_set_name_means():
    """ONE definition per name. zbp_compare adds validation-only slices, but
    for any name score/supply.py also knows, the predicate column must be
    identical -- otherwise `--supply-set principled` would validate one
    population and screen another."""
    for name, col in supply.SUPPLY_SETS.items():
        assert zbp_compare.SUPPLY_SETS[name] == col
    assert supply.DEFAULT_SUPPLY_SET == "principled"


def test_supply_predicate_rejects_a_validation_only_set_for_screening():
    """`registry_anchored` and the ACTIVE slices are measurement aids, not
    supply sets. score/supply.supply_predicate -- the one every downstream
    consumer calls -- must not accept them."""
    for name in ("registry_anchored", "active", "active_corroborated"):
        with pytest.raises(ValueError, match="unknown supply set"):
            supply.supply_predicate(name)


# -------------------------------------------------- PRINCIPLED (D52) in view
def test_principled_equals_all_when_no_category_is_anchored(supply_db):
    """FAIL OPEN. An empty analysis.category_anchor -- a forgotten
    `loci anchor-coverage --write`, or a fresh database -- must degrade to
    counting everything, never to silently deleting supply."""
    assert supply_db.execute(
        "SELECT count(*) FROM analysis.category_anchor").fetchone()[0] == 0
    rows = supply_db.execute(
        "SELECT poi_id, in_all, in_principled FROM analysis.poi_supply").fetchall()
    assert all(a == p for _, a, p in rows)


def _anchor(con, category, qualifies, is_floor: bool = False):
    con.execute(
        "INSERT OR REPLACE INTO analysis.category_anchor (category, anchor_poi, zbp_estab, "
        "anchor_coverage, threshold, qualifies, anchor_is_floor, run_at) "
        "VALUES (?, 1, 1, 1.0, ?, ?, ?, now())",
        [category, supply.ANCHOR_COVERAGE_MIN, qualifies, is_floor])


def test_principled_drops_only_the_lone_aggregator_in_an_anchored_category(supply_db):
    _anchor(supply_db, "restaurant", True)     # anchored
    _anchor(supply_db, "fitness", False)       # measured, does NOT qualify
    got = dict(supply_db.execute(
        "SELECT poi_id, in_principled FROM analysis.poi_supply").fetchall())
    assert got["dohmh:1"] is True     # registry member
    assert got["dohmh:2"] is True     # registry member (PRINCIPLED is not ACTIVE)
    # fitness is unanchored -> nothing dropped, even though both are
    # single-source aggregator clusters. Loading an anchor is the fix.
    assert got["ovt:3"] is True
    assert got["ovt:4a"] is True


def test_principled_drops_a_lone_aggregator_once_its_category_is_anchored(supply_db):
    _anchor(supply_db, "fitness", True)
    got = dict(supply_db.execute(
        "SELECT poi_id, in_principled FROM analysis.poi_supply").fetchall())
    assert got["ovt:3"] is False      # one cluster, one aggregator feed -> dropped
    assert got["ovt:4a"] is False     # two ROWS but ONE feed -> still not corroboration


def test_two_aggregators_agreeing_survive_in_an_anchored_category(supply_db):
    """CORROBORATED must stay a SUBSET of PRINCIPLED. Dropping a cluster two
    independent feeds both saw would make PRINCIPLED stricter than the set it
    exists to relax."""
    _seed(supply_db, [
        ("ovt:5", "overture_places", "fitness", "Crunch", -73.5, 40.7, 5, True, None),
        ("fsq:5", "foursquare_os_places", "fitness", "Crunch", -73.5, 40.7, 5, False, None),
    ])
    _anchor(supply_db, "fitness", True)
    got = {r[0]: (r[1], r[2]) for r in supply_db.execute(
        "SELECT poi_id, in_principled, is_corroborated FROM analysis.poi_supply").fetchall()}
    assert got["ovt:5"] == (True, True)


def test_nesting_corroborated_subset_principled_subset_all(supply_db):
    _anchor(supply_db, "restaurant", True)
    _anchor(supply_db, "fitness", True)
    bad = supply_db.execute("""
        SELECT count(*) FROM analysis.poi_supply
        WHERE (is_corroborated AND NOT in_principled) OR (in_principled AND NOT in_all)
    """).fetchone()[0]
    assert bad == 0


def test_aggregator_list_matches_the_sql_view():
    """score/supply.AGGREGATOR_SOURCES and the literal list inside EVERY
    migration that restates the view are copies of one fact. Drift would make
    has_registry_member disagree with the Python that measures coverage; 013
    restates 006's SELECT to add the floor disjunct, so it carries a second
    copy and is checked here rather than being taken on trust."""
    sql_dir = pathlib.Path(supply.__file__).resolve().parents[1] / "sql"
    for name in ("006_principled_supply.sql", "013_floor_anchor.sql"):
        sql = (sql_dir / name).read_text()
        block = sql.split("NOT IN", 1)[1].split(")", 1)[0]
        in_sql = {tok.strip().strip("'") for tok in block.strip(" \n(").split(",")}
        assert in_sql == set(supply.AGGREGATOR_SOURCES), name


# -------------------------------------------- the FLOOR-ANCHOR exception (D69)
def test_childcare_is_the_declared_floor_anchor():
    """The flag is CONFIG, not a constant in the scorer, and it is declared for
    exactly one category today. If a second one is added, this test is the place
    the addition has to be argued for."""
    assert supply.floor_anchor_categories() == frozenset({"childcare"})


def test_the_veto_still_applies_to_a_category_that_is_not_a_floor(supply_db):
    """FLAG OFF -> D52 UNCHANGED. Pinned on the same fixture as the flag-on
    case, so "the exception is narrow" is a test rather than a claim: fitness
    is anchored and not a floor, and its lone-aggregator clusters still go."""
    _anchor(supply_db, "fitness", True, is_floor=False)
    got = dict(supply_db.execute(
        "SELECT poi_id, in_principled FROM analysis.poi_supply").fetchall())
    assert got["ovt:3"] is False
    assert got["ovt:4a"] is False


def test_a_floor_anchor_retains_the_lone_aggregator_record(supply_db):
    """FLAG ON (D69). The DOHMH childcare roster covers group settings only and
    OCFS home-based care is in no NYC feed, so "no registry member" carries no
    information for this category and the veto would delete supply exactly where
    home-based care dominates. The anchor still QUALIFIES -- only the veto is
    suspended."""
    _anchor(supply_db, "fitness", True, is_floor=True)
    got = {r[0]: (r[1], r[2], r[3]) for r in supply_db.execute(
        "SELECT poi_id, in_principled, is_anchored_category, anchor_is_floor "
        "FROM analysis.poi_supply").fetchall()}
    assert got["ovt:3"] == (True, True, True)
    assert got["ovt:4a"] == (True, True, True)


def test_a_floor_anchor_makes_principled_equal_all_for_that_category(supply_db):
    """The whole content of the exception, stated as one identity -- and the
    nesting CORROBORATED subset PRINCIPLED subset ALL survives it, because the
    flag can only ADD rows to the middle set."""
    _anchor(supply_db, "fitness", True, is_floor=True)
    _anchor(supply_db, "restaurant", True, is_floor=False)
    same = supply_db.execute(
        "SELECT count(*) FROM analysis.poi_supply "
        "WHERE category = 'fitness' AND in_all <> in_principled").fetchone()[0]
    assert same == 0
    bad = supply_db.execute("""
        SELECT count(*) FROM analysis.poi_supply
        WHERE (is_corroborated AND NOT in_principled) OR (in_principled AND NOT in_all)
    """).fetchone()[0]
    assert bad == 0


def test_a_floor_flag_without_a_loaded_anchor_is_refused():
    """DRIFT CHECK. A floor is a floor UNDER a roster. Flagging a category whose
    registry was never ingested would declare "the veto does not apply here" for
    a category where the veto could not fire anyway -- and would then go on
    being silently wrong the day an anchor did land."""
    measured = [{"category": "childcare", "anchor_sources": None, "anchor_poi": 0}]
    with pytest.raises(ValueError, match="no registry anchor loaded"):
        supply.check_floor_anchors(measured)
    with pytest.raises(ValueError, match="not measured at all"):
        supply.check_floor_anchors([{"category": "bar", "anchor_sources": "x",
                                     "anchor_poi": 9}])
    # the same measurement WITH the roster ingested passes
    supply.check_floor_anchors(
        [{"category": "childcare", "anchor_sources": "nyc_dohmh_childcare",
          "anchor_poi": 1362}])


def test_supply_hash_distinguishes_a_floor_anchor_from_a_veto(supply_db):
    """Two runs whose supply differs must be distinguishable once written. The
    per-category counts alone would catch this one, but the RULE belongs in the
    hash for the same reason the qualifying-anchor set already is: a config edge
    that changes nothing today must still change the stamp."""
    _anchor(supply_db, "fitness", True, is_floor=False)
    veto = supply.supply_hash(supply_db)
    _anchor(supply_db, "fitness", True, is_floor=True)
    floor = supply.supply_hash(supply_db)
    assert veto != floor


def test_qualifies_as_anchor_rule():
    """A THIN registry must not earn a veto, and an UNMEASURABLE one (no ZBP
    denominator) must not either -- deleting supply on the strength of nothing
    is the failure mode D52 exists to avoid."""
    assert supply.qualifies_as_anchor(70, 100) is True          # at the line
    assert supply.qualifies_as_anchor(69, 100) is False
    assert supply.qualifies_as_anchor(1000, 0) is False         # no denominator
    assert supply.qualifies_as_anchor(1000, None) is False
