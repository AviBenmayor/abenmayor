"""The open/closed/unknown predicate, the co-location view, and the supply gate.

GTM-153: one cafe counted TWICE in the revenue supply pool. Cause D36/GTM-121 —
score/dedup.py merges only NAME-MATCHED points within 40 m, so a departed tenant
and its successor at one building coordinate are two different names and both
survive as canonical supply. The owner's rule: "any time we have 2 businesses in
the same address, we should do a check if one of them closed down."

WHAT IS BEING PINNED, AND WHY EACH MATTERS

1. THREE STATES, NEVER TWO. The predicate must emit 'open', 'closed' AND
   'unknown'. Collapsing unknown into closed would delete supply on the
   strength of nothing (the D47/M9 failure: whole categories at 0.10x of ZBP,
   fake retail gaps); collapsing it into open keeps the GTM-153 ghost. Most of
   the universe is legitimately unknown — four of the nine loaded feeds publish
   no status field at all.

2. D79, TWICE OVER. Absence from a snapshot is never a closure.
   (a) A DOHMH record ABSENT from the current pull is not a closure — DOHMH
       publishes active establishments only — so only a published status/expiry
       value is evidence. A DOHMH `active=false` whose basis is `stale_*` is
       derived from the ABSENCE of a recent inspection and must therefore be
       'unknown', never 'closed'.
   (b) `attrs.last_inspection_date` is a LAST-seen date. It may be read only as
       a freshness stamp on an OPEN verdict, never as a first-seen date —
       tests/test_chains_detect.py and tests/test_poi_presence.py already pin
       that against FIRST_SEEN_FIELDS and it is re-pinned here because this
       module is the new reader of that key.

3. THE PREDICATE NEVER DELETES OR MUTATES A LEDGER ROW. A closed location stays
   in analysis.poi_presence / analysis.poi_first_seen with closed_on and
   closed_src intact — survival analysis needs exactly those rows. Exclusion
   happens ONLY in the supply set.

4. ONE RULE, TWO RENDERINGS. `poi_status()` (Python) and `poi_is_open()` (SQL)
   must agree row for row, and sql/029_poi_colocation.sql must be the current
   rendering of `colocation_view_sql()`. Two copies of a rule is how a rule
   drifts.

5. NO FAN-OUT. analysis.poi_supply_status must have exactly as many rows as
   analysis.poi_supply. A duplicate here would DOUBLE supply — the very bug.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from loci.db import connect, init_schema
from loci.model import poi_presence as pp
from loci.score import supply
from loci.sources.cities.nyc import dohmh

TODAY = dt.date(2026, 9, 14)
FRESH = (TODAY - dt.timedelta(days=30)).isoformat()
ANCIENT = (TODAY - dt.timedelta(days=1500)).isoformat()


# =========================================================== 1. the truth table

#: (label, source_id, attrs, closed_on, observed_on, expected status).
#: One row per (source, state) combination that the loaded feeds can actually
#: produce — the states were enumerated from the warehouse with
#: `SELECT source_id, active, active_basis, count(*) FROM staging.poi GROUP BY`.
TRUTH_TABLE = [
    # ---- foursquare / the ledger: the only source that publishes a CLOSING DATE
    ("fsq closed_on", "foursquare_os_places", {"labels": []},
     dt.date(2025, 3, 1), None, "closed"),
    ("fsq open cache has no status", "foursquare_os_places",
     {"labels": [], "refreshed": "2026-08-01"}, None, None, "unknown"),

    # ---- DOHMH restaurants
    ("dohmh inspected recently", "nyc_dohmh_restaurants",
     {"active": True, "active_basis": "inspected_30d_ago",
      "last_inspection_date": FRESH}, None, None, "open"),
    ("dohmh inspected but evidence too old", "nyc_dohmh_restaurants",
     {"active": True, "active_basis": "inspected_30d_ago",
      "last_inspection_date": ANCIENT}, None, None, "unknown"),
    ("dohmh closed at last inspection", "nyc_dohmh_restaurants",
     {"active": False, "active_basis": "closed_at_last_inspection",
      "last_inspection_date": FRESH}, None, None, "closed"),
    # D79 (a): stale is derived from the ABSENCE of an inspection.
    ("dohmh stale", "nyc_dohmh_restaurants",
     {"active": False, "active_basis": "stale_1200d",
      "last_inspection_date": ANCIENT}, None, None, "unknown"),
    ("dohmh never inspected is a DEFAULT not a finding", "nyc_dohmh_restaurants",
     {"active": True, "active_basis": "never_inspected"}, None, None, "unknown"),

    # ---- DCWP: publishes the inspector's verdict
    ("dcwp out of business", "nyc_dcwp_inspections",
     {"active": False, "active_basis": "out_of_business"}, None, None, "closed"),
    ("dcwp unable to locate", "nyc_dcwp_inspections",
     {"active": False, "active_basis": "unable_to_locate"}, None, None, "closed"),
    ("dcwp no evidence of activity", "nyc_dcwp_inspections",
     {"active": False, "active_basis": "no_evidence_of_activity"}, None, None, "closed"),
    ("dcwp inspected pass", "nyc_dcwp_inspections",
     {"active": True, "active_basis": "inspected_pass",
      "last_inspection_date": FRESH}, None, None, "open"),
    ("dcwp dead marker overridden same day", "nyc_dcwp_inspections",
     {"active": True, "active_basis": "dead_marker_overridden_same_day",
      "last_inspection_date": FRESH}, None, None, "open"),
    ("dcwp no status", "nyc_dcwp_inspections",
     {"active": True, "active_basis": "no_status"}, None, None, "unknown"),

    # ---- licence expiries
    ("sla valid", "nys_sla_liquor_licenses",
     {"active": True, "active_basis": "valid_to_2028-01-31",
      "expires": "2028-01-31"}, None, None, "open"),
    ("sla lapsed since the pull", "nys_sla_liquor_licenses",
     {"active": True, "active_basis": "valid_to_2026-01-31",
      "expires": "2026-01-31"}, None, None, "closed"),
    ("sla no expiry published", "nys_sla_liquor_licenses",
     {"active": True, "active_basis": "no_expiration_date"}, None, None, "unknown"),
    ("dos valid", "nys_dos_appearance_enhancement",
     {"active": True, "active_basis": "valid_to_2029-10-07",
      "license_expiration_date": "2029-10-07"}, None, None, "open"),
    ("dos lapsed", "nys_dos_appearance_enhancement",
     {"active": True, "active_basis": "valid_to_2025-10-07",
      "license_expiration_date": "2025-10-07"}, None, None, "closed"),

    # ---- rosters: presence IS the observation, so they can only say OPEN
    ("medicaid roster, fresh pull", "nys_medicaid_pharmacies",
     {"active": True, "active_basis": "published_active_medicaid_ffs_roster"},
     None, dt.date(2026, 9, 1), "open"),
    ("medicaid roster, stale pull", "nys_medicaid_pharmacies",
     {"active": True, "active_basis": "published_active_medicaid_ffs_roster"},
     None, dt.date(2020, 1, 1), "unknown"),
    ("childcare roster, fresh pull", "nyc_dohmh_childcare",
     {"active": True, "active_basis": "published_active_roster"},
     None, dt.date(2026, 9, 1), "open"),

    # ---- feeds with no status field at all
    ("overture", "overture_places", {"primary_category": "cafe"}, None, None, "unknown"),
    ("osm", "osm_overpass", {}, None, None, "unknown"),
    ("snap", "usda_snap_retailers", {"store_type": "Grocery"}, None, None, "unknown"),
]


@pytest.mark.parametrize("label,src,attrs,closed_on,observed_on,expected",
                         TRUTH_TABLE, ids=[r[0] for r in TRUTH_TABLE])
def test_predicate_truth_table(label, src, attrs, closed_on, observed_on, expected):
    status, basis = pp.poi_status(attrs, source_id=src, closed_on=closed_on,
                                  observed_on=observed_on, today=TODAY)
    assert status == expected, f"{label}: got {status} ({basis})"
    assert status in pp.STATUSES
    assert basis                                   # every verdict names its evidence


def test_all_three_states_are_reachable():
    """A predicate that can only ever say two things is not this predicate."""
    got = {pp.poi_status(a, source_id=s, closed_on=c, observed_on=o, today=TODAY)[0]
           for _, s, a, c, o, _ in TRUTH_TABLE}
    assert got == {"open", "closed", "unknown"}


def test_d79_no_absence_derived_basis_can_ever_be_closed():
    """D79 (a). A DOHMH record absent from the pull is not a closure, and
    neither is one whose only signal is that nobody has inspected it lately."""
    for days in (750, 1200, 5000):
        status, basis = pp.poi_status(
            {"active": False, "active_basis": f"stale_{days}d",
             "last_inspection_date": (TODAY - dt.timedelta(days=days)).isoformat()},
            source_id="nyc_dohmh_restaurants", today=TODAY)
        assert status == "unknown"
        assert "absence_derived_not_a_closure" in basis
    # and no prefix in the absence-derived list may appear in the closed list
    assert not any(b.startswith(pp.ABSENCE_DERIVED_BASIS_PREFIXES)
                   for b in pp.PUBLISHED_CLOSED_BASES)


def test_d79_roster_sources_can_never_say_closed():
    """Their only closure signal would be disappearance from the roster, which
    is precisely what D79 forbids as evidence."""
    for basis in pp.ROSTER_ACTIVE_BASES:
        for observed in (dt.date(2026, 9, 1), dt.date(2015, 1, 1), None):
            status, _ = pp.poi_status({"active": True, "active_basis": basis},
                                      source_id="nys_medicaid_pharmacies",
                                      observed_on=observed, today=TODAY)
            assert status != "closed"


def test_last_inspection_date_is_a_freshness_stamp_not_a_first_seen_date():
    """D79 (b). It is a LAST-seen date; reading it as a first-seen would date
    every long-established restaurant to its most recent inspection. It must
    stay out of FIRST_SEEN_FIELDS (tests/test_chains_detect.py pins the same
    thing from the other side) while still being readable HERE."""
    assert not any("last_inspection_date" in expr for expr, _ in pp.FIRST_SEEN_FIELDS)
    # it does move the verdict, in the one direction it is allowed to
    attrs = {"active": True, "active_basis": "inspected_10d_ago"}
    assert pp.poi_status(dict(attrs, last_inspection_date=FRESH),
                         source_id="nyc_dohmh_restaurants", today=TODAY)[0] == "open"
    assert pp.poi_status(dict(attrs, last_inspection_date=ANCIENT),
                         source_id="nyc_dohmh_restaurants", today=TODAY)[0] == "unknown"


def test_open_evidence_window_agrees_with_the_dohmh_staleness_cut():
    """A DOHMH record must not be 'open' here and 'stale' in the adapter. The
    constant is restated (not imported) to keep this predicate city-agnostic,
    so the agreement has to be asserted."""
    assert pp.OPEN_EVIDENCE_MAX_AGE_DAYS == pytest.approx(dohmh.STALE_DAYS, abs=1)


# ==================================================== 2. the synthetic warehouse

def _poi(con, poi_id, source_id, category, name, lon, lat, cluster, canonical,
         attrs=None, observed_on=None):
    con.execute(
        "INSERT INTO staging.poi (poi_id, source_id, source_record_id, category, tier, "
        "name, geom, observed_on, confidence, attrs) "
        "VALUES (?, ?, ?, ?, 3, ?, ST_Point(?, ?), ?, 0.5, CAST(? AS JSON))",
        [poi_id, source_id, poi_id, category, name, lon, lat, observed_on,
         json.dumps(attrs or {})])
    con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                [poi_id, cluster, canonical, category])


def _ledger_closure(con, location_key, category, poi_id, closed_on):
    con.execute(
        "INSERT INTO analysis.poi_presence (location_key, category, first_seen_month, "
        "last_seen_month, first_seen_kind, n_months_seen, ledger_started_month, "
        "last_snapshot_at, poi_id_latest, closed_on, closed_src) "
        "VALUES (?, ?, '2026-09', '2026-09', 'observed', 1, '2026-09', now(), ?, ?, "
        "'foursquare:key')",
        [location_key, category, poi_id, closed_on])


#: One coordinate per scenario. The lon/lat are EPSG:4326 degrees (DuckDB
#: GEOMETRY carries no SRID) and the pairs share a coordinate EXACTLY, which is
#: what the feeds actually produce: DOHMH/SLA/DCWP geocode to the building.
A, B, C, D, E, F, G = (-73.9001, -73.9002, -73.9003, -73.9004, -73.9005,
                       -73.9006, -73.9007)
LAT = 40.7000


@pytest.fixture()
def db():
    con = connect(":memory:")
    init_schema(con)

    # (A) one_closed -- THE GTM-153 CASE: predecessor with a ledger closure and
    #     its successor at the identical coordinate, different names.
    _poi(con, "ovt:a1", "overture_places", "cafe_bakery", "Old Cafe", A, LAT, 1, True)
    _poi(con, "ovt:a2", "overture_places", "cafe_bakery", "New Cafe", A, LAT, 2, True)
    _ledger_closure(con, "k-a1", "cafe_bakery", "ovt:a1", dt.date(2025, 6, 1))

    # (B) both_open -- two restaurants in one large building, both positively
    #     open. This is the case the collapse would WRONGLY delete.
    _poi(con, "doh:b1", "nyc_dohmh_restaurants", "restaurant", "Thai", B, LAT, 3, True,
         {"active": True, "active_basis": "inspected_20d_ago",
          "last_inspection_date": FRESH})
    _poi(con, "doh:b2", "nyc_dohmh_restaurants", "restaurant", "Pizza", B, LAT, 4, True,
         {"active": True, "active_basis": "inspected_20d_ago",
          "last_inspection_date": FRESH})

    # (C) unresolved -- one open, one unknown. No published evidence splits it.
    _poi(con, "doh:c1", "nyc_dohmh_restaurants", "restaurant", "Deli", C, LAT, 5, True,
         {"active": True, "active_basis": "inspected_20d_ago",
          "last_inspection_date": FRESH})
    _poi(con, "ovt:c2", "overture_places", "restaurant", "Ghost", C, LAT, 6, True)

    # (D) unresolved -- the D36 turnover SIGNATURE (stale beside fresh), which
    #     D79 still refuses to call a closure.
    _poi(con, "doh:d1", "nyc_dohmh_restaurants", "restaurant", "Gone?", D, LAT, 7, True,
         {"active": False, "active_basis": "stale_1200d",
          "last_inspection_date": ANCIENT})
    _poi(con, "doh:d2", "nyc_dohmh_restaurants", "restaurant", "Successor", D, LAT, 8,
         True, {"active": True, "active_basis": "inspected_20d_ago",
                "last_inspection_date": FRESH})

    # (E) all_closed -- both members carry a published DCWP verdict.
    _poi(con, "dcwp:e1", "nyc_dcwp_inspections", "laundry", "Wash A", E, LAT, 9, True,
         {"active": False, "active_basis": "out_of_business"})
    _poi(con, "dcwp:e2", "nyc_dcwp_inspections", "laundry", "Wash B", E, LAT, 10, True,
         {"active": False, "active_basis": "out_of_business"})

    # (F) NOT a group: same coordinate, DIFFERENT categories. A bar above a
    #     nail salon is two markets, neither evidence about the other.
    _poi(con, "sla:f1", "nys_sla_liquor_licenses", "bar", "Tap", F, LAT, 11, True,
         {"active": True, "active_basis": "valid_to_2028-01-31",
          "expires": "2028-01-31"})
    _poi(con, "dos:f2", "nys_dos_appearance_enhancement", "nails_beauty", "Nails",
         F, LAT, 12, True, {"active": True, "active_basis": "valid_to_2029-01-31",
                            "license_expiration_date": "2029-01-31"})

    # (G) unresolved AND a GEOCODE SINK -- 6 restaurants at one coordinate,
    #     colocation_n=6 > SINK_GROUP_SIZE=5 (owner ruling 2026-09-21, D132 /
    #     GTM-202). Modelled on the real Penn Station / JFK / Port Authority
    #     groups (36 to 72 members): a whole terminal's food hall published
    #     at one building point. No published closure anywhere in the group
    #     (so resolution is 'unresolved', not 'all_closed'/'one_closed'), and
    #     not every member is positively open (so not 'both_open' either).
    #     MUST survive the default collapse untouched -- collapsing a sink
    #     would delete real, distinct restaurants on the strength of nothing.
    for i, (src, name, attrs) in enumerate([
        ("nyc_dohmh_restaurants", "Terminal Grill",
         {"active": True, "active_basis": "inspected_20d_ago",
          "last_inspection_date": FRESH}),
        ("nyc_dohmh_restaurants", "Terminal Noodles",
         {"active": True, "active_basis": "inspected_20d_ago",
          "last_inspection_date": FRESH}),
        ("overture_places", "Terminal Sushi", {}),
        ("overture_places", "Terminal Pizza", {}),
        ("overture_places", "Terminal Tacos", {}),
        ("overture_places", "Terminal Burgers", {}),
    ], start=13):
        _poi(con, f"sink:g{i}", src, "restaurant", name, G, LAT, i, True, attrs)
    return con


def _res(con, category, lon):
    row = con.execute(
        "SELECT resolution, n_poi, n_closed, n_open, n_unknown FROM analysis.poi_colocation "
        "WHERE category = ? AND abs(lon - ?) < 1e-9", [category, round(lon, pp.COORD_DP)]
    ).fetchone()
    return row


def test_view_has_no_fan_out(db):
    """analysis.poi_supply_status must be analysis.poi_supply relabelled, never
    a different population: a duplicated row here DOUBLES supply, which is the
    defect being fixed."""
    a = db.execute("SELECT count(*), count(DISTINCT poi_id) FROM analysis.poi_supply"
                   ).fetchone()
    b = db.execute("SELECT count(*), count(DISTINCT poi_id) FROM "
                   "analysis.poi_supply_status").fetchone()
    assert a == b == (18, 18)


def test_sql_and_python_renderings_of_the_predicate_agree(db):
    """One rule, two renderings. If these ever disagree the rule has drifted."""
    rows = db.execute(f"""
        SELECT p.poi_id, p.source_id, p.attrs, p.observed_on, f.closed_on,
               {pp.poi_is_open('p', 'f.closed_on', "DATE '2026-09-14'")} AS sql_status
        FROM staging.poi p
        LEFT JOIN (SELECT poi_id_latest AS poi_id, min(closed_on) AS closed_on
                   FROM analysis.poi_first_seen WHERE poi_id_latest IS NOT NULL
                   GROUP BY 1) f ON f.poi_id = p.poi_id
    """).fetchall()
    assert rows
    for poi_id, src, attrs, observed_on, closed_on, sql_status in rows:
        py_status, _ = pp.poi_status(json.loads(attrs), source_id=src,
                                     closed_on=closed_on, observed_on=observed_on,
                                     today=TODAY)
        assert py_status == sql_status, poi_id


def test_resolution_logic(db):
    assert _res(db, "cafe_bakery", A) == ("one_closed", 2, 1, 0, 1)
    assert _res(db, "restaurant", B) == ("both_open", 2, 0, 2, 0)
    assert _res(db, "restaurant", C) == ("unresolved", 2, 0, 1, 1)
    assert _res(db, "restaurant", D) == ("unresolved", 2, 0, 1, 1)
    assert _res(db, "laundry", E) == ("all_closed", 2, 2, 0, 0)
    # (G) the sink: 'unresolved' at n_poi=6 -- ABOVE SINK_GROUP_SIZE=5 -- is
    # what makes it a sink rather than an ordinary pair; the resolution
    # itself is computed identically either way.
    assert _res(db, "restaurant", G) == ("unresolved", 6, 0, 2, 4)


def test_one_open_plus_one_unknown_is_unresolved_not_both_open(db):
    """Collapsing 'unknown' into 'open' here would quietly re-assert the
    GTM-153 double count as a finding."""
    assert _res(db, "restaurant", C)[0] == "unresolved"


def test_different_categories_at_one_coordinate_are_not_a_group(db):
    """A bar above a nail salon shares a geocode and nothing else."""
    assert db.execute("SELECT count(*) FROM analysis.poi_colocation "
                      "WHERE category IN ('bar', 'nails_beauty')").fetchone()[0] == 0


def test_every_group_has_at_least_two_members_and_a_known_resolution(db):
    bad = db.execute(
        "SELECT count(*) FROM analysis.poi_colocation WHERE n_poi < 2 "
        "OR resolution NOT IN ('one_closed', 'all_closed', 'both_open', 'unresolved')"
    ).fetchone()[0]
    assert bad == 0
    totals = db.execute(
        "SELECT count(*) FROM analysis.poi_colocation "
        "WHERE n_closed + n_open + n_unknown <> n_poi").fetchone()[0]
    assert totals == 0


def test_evidence_names_the_source_key_behind_every_verdict(db):
    ev = json.loads(db.execute(
        "SELECT evidence FROM analysis.poi_colocation WHERE category = 'cafe_bakery'"
    ).fetchone()[0])
    assert {e["poi_id"] for e in ev} == {"ovt:a1", "ovt:a2"}
    closed = [e for e in ev if e["status"] == "closed"]
    assert len(closed) == 1
    assert closed[0]["basis"].startswith("ledger:closed_on_")
    assert closed[0]["closed_src"] == "foursquare:key"


# ================================================================ 3. the gate

def _ids(con, **kw):
    return {r[0] for r in con.execute(
        supply.canonical_poi_sql("all", "s.poi_id", **kw)).fetchall()}


def test_gate_excludes_evidenced_closures(db):
    ungated = _ids(db, gate_closed=False)
    gated = _ids(db, gate_closed=True)
    assert ungated - gated == {"ovt:a1", "dcwp:e1", "dcwp:e2"}


def test_gate_is_on_by_default(db):
    assert supply.GATE_CLOSED is True
    assert _ids(db) == _ids(db, gate_closed=True)


def test_gate_keeps_unknown(db):
    """'unknown' is most of the universe. Gating it would delete supply on the
    strength of nothing -- the D47/M9 fake-gap failure. Isolated from the
    2026-09-21 collapse ruling with collapse_unresolved=False: this test is
    about the CLOSURE GATE specifically, not about whether an unknown member
    of an ordinary unresolved pair later loses a collapse tie-break (that is
    covered separately, below)."""
    assert "ovt:c2" in _ids(db, collapse_unresolved=False)
    assert "doh:d1" in _ids(db, collapse_unresolved=False)  # DOHMH stale: D79 says not a closure


def test_ordinary_unresolved_groups_collapse_by_default(db):
    """OWNER RULING 2026-09-21 (CHECKPOINT D132, GTM-202, supersedes QUESTIONS
    D24): C3's rule -- 'resolve which is still open before counting; never
    count two' -- now actually applies. An ORDINARY unresolved group (C, D:
    colocation_n=2 <= SINK_GROUP_SIZE) collapses to its one positively-open
    survivor by default; the loser drops out of supply entirely."""
    ids = _ids(db)
    assert "doh:c1" in ids and "ovt:c2" not in ids
    assert "doh:d2" in ids and "doh:d1" not in ids
    # both_open (B) is untouched -- the collapse only ever touches 'unresolved'
    assert {"doh:b1", "doh:b2"} <= ids


def test_sink_groups_are_not_collapsed_by_default(db):
    """The charter exception: a same-category unresolved group ABOVE
    SINK_GROUP_SIZE members (G has 6) is a GEOCODE SINK -- a terminal food
    hall published at one coordinate, not a duplicate record -- and stays
    counted AS-IS, exactly as every unresolved group did before this ruling.
    The owner explicitly declined to route it to the paid closure check
    either (2026-09-21): there is no follow-up pending on a sink group."""
    ids = _ids(db)
    sink_ids = {f"sink:g{i}" for i in range(13, 19)}
    assert sink_ids <= ids, f"missing: {sink_ids - ids}"


def test_unresolved_rows_are_flagged_in_the_view_regardless_of_collapse(db):
    """is_colocated_unresolved is a property of analysis.poi_supply_status
    (the MEASUREMENT surface, sql/029) and is set the same way for an
    ordinary pair and a sink -- it is canonical_poi_sql, one layer up, that
    decides whether a flagged row is then collapsed away or kept."""
    flagged = {r[0] for r in db.execute(
        "SELECT poi_id FROM analysis.poi_supply_status WHERE is_colocated_unresolved"
    ).fetchall()}
    sink_ids = {f"sink:g{i}" for i in range(13, 19)}
    assert flagged == {"doh:c1", "ovt:c2", "doh:d1", "doh:d2"} | sink_ids


def test_collapse_is_on_by_default_with_the_owner_ruled_sink_cutoff():
    assert supply.COLLAPSE_UNRESOLVED is True
    assert supply.SINK_GROUP_SIZE == 5


def test_collapse_is_deterministic(db):
    a = _ids(db)
    b = _ids(db)
    assert a == b


def test_collapse_unresolved_false_reproduces_the_pre_ruling_set(db):
    """The explicit override that gets back the pre-2026-09-21 behaviour: no
    collapse at all, ordinary pairs and sinks alike counted in full."""
    ids = _ids(db, collapse_unresolved=False)
    sink_ids = {f"sink:g{i}" for i in range(13, 19)}
    assert {"doh:c1", "ovt:c2", "doh:d1", "doh:d2"} <= ids
    assert sink_ids <= ids


def test_collapse_unresolved_true_override_collapses_sinks_too(db):
    """The REJECTED alternative, priced but never applied by default: an
    explicit collapse_unresolved=True (as opposed to the inherited default)
    overrides the sink exemption, which is how `loci colocation
    --collapse-unresolved` shows what collapsing sinks too would cost without
    doing it. Deterministic survivor rule is unchanged: positively-open beats
    unknown, tie-broken by lowest poi_id -- sink:g13/g14 are the two DOHMH
    'open' members, so sink:g13 wins."""
    ids = _ids(db, collapse_unresolved=True)
    sink_ids = {f"sink:g{i}" for i in range(13, 19)}
    assert (sink_ids & ids) == {"sink:g13"}
    # ordinary groups collapse the same way under the explicit override
    assert "doh:c1" in ids and "ovt:c2" not in ids
    assert "doh:d2" in ids and "doh:d1" not in ids


def test_supply_hash_distinguishes_a_gated_run_from_an_ungated_one(db, monkeypatch):
    before = supply.supply_hash(db, "all")
    monkeypatch.setattr(supply, "GATE_CLOSED", False)
    assert supply.supply_hash(db, "all") != before


def test_supply_hash_distinguishes_the_collapse_ruling_from_no_collapse(db, monkeypatch):
    """The 2026-09-21 ruling is itself hash-moving (D106/C9): a warehouse
    built before it and one built after must never compare equal."""
    before = supply.supply_hash(db, "all")
    monkeypatch.setattr(supply, "COLLAPSE_UNRESOLVED", False)
    assert supply.supply_hash(db, "all") != before


def test_supply_hash_distinguishes_the_sink_cutoff(db, monkeypatch):
    """A future change to SINK_GROUP_SIZE (e.g. if a new sink is measured at
    a size that slips under the current cutoff) must also move the hash --
    same reasoning as GATE_CLOSED and COLLAPSE_UNRESOLVED above."""
    before = supply.supply_hash(db, "all")
    monkeypatch.setattr(supply, "SINK_GROUP_SIZE", 1000)   # nothing is a sink
    assert supply.supply_hash(db, "all") != before


# ============================================ 4. the ledger is never mutated

def test_closed_rows_stay_in_the_ledger_with_their_closure_intact(db):
    """The predicate EXCLUDES from supply; it never deletes or edits a ledger
    row. Survival analysis needs the closed spells."""
    row = db.execute(
        "SELECT closed_on, closed_src, is_closed FROM analysis.poi_first_seen "
        "WHERE poi_id_latest = 'ovt:a1'").fetchone()
    assert row == (dt.date(2025, 6, 1), "foursquare:key", True)
    assert "ovt:a1" not in _ids(db)                       # gone from supply only
    assert db.execute("SELECT count(*) FROM analysis.poi_presence").fetchone()[0] == 1


def test_closed_venues_still_never_enter_staging_poi(db):
    """The sql/027 invariant, restated from this side: the gate is a SECOND
    line of defence, not a replacement for keeping closures out of the feed."""
    assert db.execute("SELECT count(*) FROM staging.poi "
                      "WHERE closed_on IS NOT NULL").fetchone()[0] == 0


# ====================================== 5. the generated SQL file has not drifted

def test_sql_file_matches_generator():
    """sql/029_poi_colocation.sql is GENERATED from colocation_view_sql(). A
    hand edit there would give the open/closed rule a second definition."""
    path = pathlib.Path(supply.__file__).resolve().parents[1] / "sql" / \
        "029_poi_colocation.sql"
    text = path.read_text()
    assert pp.colocation_view_sql().strip() in text, (
        "sql/029_poi_colocation.sql is stale — regenerate it with "
        "`loci colocation --emit-sql > src/loci/sql/029_poi_colocation.sql`")


def test_coordinate_grouping_is_about_one_metre():
    """5 dp is ~1.1 m N-S at NYC's latitude. Looser would fuse distinct
    neighbouring storefronts -- the fake-gap failure; tighter would miss the
    building-centroid co-location the feeds actually publish."""
    assert pp.COORD_DP == 5
    metres_per_degree_lat = 111_320
    assert 0.5 < 10 ** -pp.COORD_DP * metres_per_degree_lat < 2.0
