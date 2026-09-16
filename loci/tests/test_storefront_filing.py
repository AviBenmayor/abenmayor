"""staging.storefront_filing: stage ordering, name-key reuse, the DOB NOW
storefront filter, and the BBL-matching fallbacks.

No network. The BBL ladder is exercised against a synthetic three-lot PLUTO
CSV, so every rung is reachable and the 30 m boundary is testable to the metre.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from loci import db as locidb
from loci.chains.normalize import brand_key
from loci.filing_stages import (EARLY_STAGES, MATCH_METHODS, OPEN_STAGES,
                                STAGE_RANK, STAGES, UNPOPULATED_STAGES,
                                stage_rank)
from loci.model import storefront_filing as sf
from loci.sources.cities.nyc import filing_feeds as ff


# ------------------------------------------------------------ stage ordering

def test_stage_vocabulary_is_ordered_and_unique():
    assert len(set(STAGES)) == len(STAGES)
    assert [STAGE_RANK[s] for s in STAGES] == list(range(1, len(STAGES) + 1))


def test_stage_order_is_the_lifecycle_order():
    """The claim the rank encodes: an application precedes its own permit,
    which precedes the licence, which precedes the first inspection."""
    assert stage_rank("liquor_application") < stage_rank("fitout_filing")
    assert stage_rank("fitout_filing") < stage_rank("license_application")
    assert stage_rank("license_application") < stage_rank("permit_issued")
    assert stage_rank("permit_issued") < stage_rank("sign_permit")
    assert stage_rank("sign_permit") < stage_rank("license_issued")
    assert stage_rank("license_issued") < stage_rank("first_inspection")


def test_every_early_stage_ranks_before_every_open_stage():
    """If this ever fails the lead time can go negative by construction."""
    assert max(stage_rank(s) for s in EARLY_STAGES) < \
           min(stage_rank(s) for s in OPEN_STAGES)


def test_liquor_active_is_not_a_terminal_stage():
    """SLA's originalissuedate is the FIRST licence at the premises, possibly
    decades old. Using it as an opening date produces negative lead times."""
    assert "liquor_active" not in OPEN_STAGES
    assert "liquor_active" not in EARLY_STAGES


def test_unknown_stage_raises():
    with pytest.raises(ValueError):
        stage_rank("soft_opening")


def test_every_feed_emits_a_declared_stage():
    """A fetcher that invents a stage string would be rejected by the CHECK
    constraint at write time -- a network round trip too late."""
    emitted = {"liquor_application", "fitout_filing", "license_application",
               "permit_issued", "sign_permit", "license_issued",
               "liquor_active", "first_inspection"}
    assert emitted <= set(STAGES)
    assert set(STAGES) - emitted == UNPOPULATED_STAGES


def test_ddl_stage_vocabulary_matches_the_python_one():
    """sql/019 mirrors filing_stages.STAGES in a CHECK constraint. A stage added
    in one place and not the other fails the INSERT at run time."""
    from loci.db import SQL_DIR
    ddl = (SQL_DIR / "019_storefront_filing.sql").read_text()
    for stage in STAGES:
        assert f"'{stage}'" in ddl, stage
    for method in MATCH_METHODS:
        assert f"'{method}'" in ddl, method


# --------------------------------------------------------- name-key reuse

def test_business_name_key_is_the_chains_normalizer():
    """Not 'behaves like' -- IS. A second normalizer would put a filing and a
    chain location for one business under two different keys."""
    assert sf.brand_key is brand_key


@pytest.mark.parametrize("raw,expected", [
    ("Dunkin' Donuts #9911", "dunkin"),
    ("Apollo Bagels - Williamsburg", "apollo bagels"),
    ("VITAL CLIMBING GYM LLC NYC", "vital climbing gym"),
    ("PARADISELAUNDROMATNY@GMAIL.COM", None),
    ("N/A", None),
])
def test_name_key_matches_chains_on_real_filing_spellings(raw, expected):
    assert brand_key(raw) == expected


# ------------------------------------------------- the DOB NOW storefront rule

def test_dob_now_filter_excludes_new_building_and_demolition():
    where = ff.dob_now_where(dt.date(2026, 9, 13))
    for excluded in ff.EXCLUDED_JOB_TYPES:
        assert f"'{excluded}'" in where
    assert "job_type not in" in where


def test_dob_now_filter_excludes_small_residential():
    where = ff.dob_now_where(dt.date(2026, 9, 13))
    assert "building_type not in" in where
    for b in ("1 Family", "2 Family", "3 Family"):
        assert f"'{b}'" in where


def test_dob_now_filter_requires_a_storefront_work_type():
    where = ff.dob_now_where(dt.date(2026, 9, 13))
    for col in ff.STOREFRONT_WORK_TYPES:
        assert f"{col}='YES'" in where
    # OR, never AND: a sign permit with no general construction is still a
    # storefront, and requiring all three would keep almost nothing.
    assert " OR " in where
    assert "plumbing" not in where and "sprinkler" not in where


def test_dob_now_window_is_opt_in_and_full_history_is_the_default():
    """SUPERSEDES test_dob_now_window_is_24_months (2026-09-16). The 24-month
    clip stopped being the default: it made every pre-2024 cohort literally
    unobservable, which is what the rewind backtest ran into. The window MATHS
    is unchanged and still pinned -- only which side of the `since=None`
    default it sits on moved. Full-history behaviour is covered in
    tests/test_filing_backfill.py."""
    unclipped = ff.dob_now_where(dt.date(2026, 9, 13))
    assert "filing_date" not in unclipped

    clipped = ff.dob_now_where(dt.date(2026, 9, 13),
                               ff.window_start(dt.date(2026, 9, 13)))
    assert "filing_date >= '2024-09-13T00:00:00'" in clipped
    assert ff.window_start(dt.date(2026, 1, 31)) == dt.date(2024, 1, 28)
    assert ff.window_start(dt.date(2026, 3, 1)) == dt.date(2024, 3, 1)


def test_permit_work_types_map_to_two_distinct_stages():
    assert ff.PERMIT_WORK_STAGE["General Construction"] == "permit_issued"
    assert ff.PERMIT_WORK_STAGE["Sign"] == "sign_permit"
    # Scaffolding is not a business opening.
    assert "Sidewalk Shed" not in ff.PERMIT_WORK_STAGE


# ------------------------------------------------------- BBL match fallbacks

#: Three lots, hand-built so each rung of the ladder is reachable.
#: 1000010001  60 metres north of 1000010002, same street, unique address
#: 1000010002  the nearest-lot target
#: 1000010003  shares a normalised address with 1000010002 -> ambiguous, so the
#:             address rung must refuse both
_PLUTO_ROWS = [
    # bbl, borocode, address, lat, lon
    ("1000010001", "1", "100 MAIN STREET", 40.700000, -73.990000),
    ("1000010002", "1", "200 MAIN STREET", 40.710000, -73.980000),
    ("1000010003", "1", "200 MAIN STREET", 40.750000, -73.950000),
    ("3000010004", "3", "12 UNION AVENUE", 40.720000, -73.950000),
]


@pytest.fixture
def con(tmp_path):
    c = locidb.connect(":memory:")
    csv = tmp_path / "pluto.csv"
    csv.write_text(
        "borocode,address,latitude,longitude,BBL\n" +
        "".join(f"{b},{a},{lat},{lon},{bbl}\n"
                for bbl, b, a, lat, lon in _PLUTO_ROWS))
    # build_pluto_index refuses a truncated spine; the test lowers its
    # `min_lots` floor rather than inflating the fixture to 500k rows.
    c.execute("SET threads TO 2")
    yield c, csv
    c.close()


def _index(c, csv):
    return sf.build_pluto_index(c, csv, min_lots=1)


def _rows(**over):
    base = dict(source="t", stage="fitout_filing", business_name="X",
                business_name_key="x", bbl_raw=None, bin=None,
                house_number=None, street_name=None, borough="MN",
                lon=None, lat=None, filed_on=dt.date(2026, 1, 1), status=None,
                status_date=None, category_hint=None, license_type=None,
                raw_id="1", provenance="p", filing_id="t:fitout_filing:1")
    base.update(over)
    return base


def _match(con_csv, frame):
    c, csv = con_csv
    _index(c, csv)
    return sf.match_bbl(c, frame)


def test_feed_bbl_present_in_pluto(con):
    out = _match(con, pd.DataFrame([
        _rows(bbl_raw="1000010001", filing_id="a", raw_id="a")]))
    assert out.loc[0, "match_method"] == "feed_bbl"
    assert out.loc[0, "bbl"] == "1000010001"


def test_feed_bbl_absent_from_pluto_is_kept_and_flagged(con):
    """PLUTO is a 2026 snapshot. A newly subdivided lot legitimately misses,
    and dropping it would delete exactly the newest construction."""
    out = _match(con, pd.DataFrame([
        _rows(bbl_raw="1099998888", filing_id="b", raw_id="b")]))
    assert out.loc[0, "match_method"] == "feed_bbl_unverified"
    assert out.loc[0, "bbl"] == "1099998888"


def test_malformed_bbl_falls_through_to_the_next_rung(con):
    out = _match(con, pd.DataFrame([
        _rows(bbl_raw="0", house_number="100", street_name="MAIN STREET",
              filing_id="c", raw_id="c")]))
    assert out.loc[0, "match_method"] == "pluto_address"
    assert out.loc[0, "bbl"] == "1000010001"


def test_address_rung_expands_a_street_suffix(con):
    out = _match(con, pd.DataFrame([
        _rows(house_number="100", street_name="MAIN ST",
              filing_id="d", raw_id="d")]))
    assert out.loc[0, "bbl"] == "1000010001"


def test_ambiguous_address_is_refused_not_guessed(con):
    """Two lots share '200 MAIN STREET'. Picking one would attach the filing to
    an arbitrary neighbour, so the rung declines and the row falls through."""
    out = _match(con, pd.DataFrame([
        _rows(house_number="200", street_name="MAIN STREET",
              filing_id="e", raw_id="e")]))
    assert out.loc[0, "match_method"] == "unmatched"
    assert out.loc[0, "bbl"] is None


def test_nearest_lot_within_30m(con):
    """~11 m north of lot ...0002. Inside the radius."""
    out = _match(con, pd.DataFrame([
        _rows(lat=40.710100, lon=-73.980000, filing_id="f", raw_id="f")]))
    assert out.loc[0, "match_method"] == "pluto_nearest_30m"
    assert out.loc[0, "bbl"] == "1000010002"


def test_nearest_lot_beyond_30m_is_unmatched(con):
    """~55 m north of lot ...0002. Outside the radius -- and the row is KEPT,
    per the owner's no-eligibility-gate ruling (D75)."""
    out = _match(con, pd.DataFrame([
        _rows(lat=40.710500, lon=-73.980000, filing_id="g", raw_id="g")]))
    assert out.loc[0, "match_method"] == "unmatched"
    assert out.loc[0, "bbl"] is None


def test_ladder_never_changes_the_row_count(con):
    """The guard that catches a fan-out. A duplicated rung would inflate every
    count in the table."""
    frame = pd.DataFrame([
        _rows(bbl_raw="1000010001", filing_id="h1", raw_id="h1"),
        _rows(house_number="100", street_name="MAIN STREET",
              filing_id="h2", raw_id="h2"),
        _rows(lat=40.710100, lon=-73.980000, filing_id="h3", raw_id="h3"),
        _rows(filing_id="h4", raw_id="h4"),
        # the ambiguous address: must produce exactly ONE row, not two
        _rows(house_number="200", street_name="MAIN STREET",
              filing_id="h5", raw_id="h5"),
    ])
    out = _match(con, frame)
    assert len(out) == len(frame)
    assert out["filing_id"].is_unique
    assert set(out["match_method"]) <= set(MATCH_METHODS)


def test_borough_gates_the_address_rung(con):
    """'12 UNION AVENUE' exists only in Brooklyn. A Manhattan filing with that
    address must not pick it up."""
    out = _match(con, pd.DataFrame([
        _rows(house_number="12", street_name="UNION AVENUE", borough="MN",
              filing_id="i", raw_id="i")]))
    assert out.loc[0, "match_method"] == "unmatched"
    out2 = _match(con, pd.DataFrame([
        _rows(house_number="12", street_name="UNION AVENUE", borough="BK",
              filing_id="j", raw_id="j")]))
    assert out2.loc[0, "bbl"] == "3000010004"


def test_null_island_coordinates_become_null(con):
    """DOHMH, DCWP and the SLA all publish literal (0, 0). Left alone it would
    be handed to the nearest-lot matcher as a point off West Africa."""
    assert ff._point_ok(ff._float("0"), ff._float("0")) == (None, None)
    assert ff._point_ok(-73.98, 40.71) == (-73.98, 40.71)
    # outside the five-borough bbox
    assert ff._point_ok(-75.25, 43.10) == (None, None)


# ------------------------------------------------ the lead-time pair split

def test_same_agency_pair_is_named_and_excluded_from_the_headline():
    """DCWP application -> DCWP licence is the agency's own processing clock,
    not a time-to-open. On the 2026-09-13 build it is 5,206 of 5,377 pairs, so
    pooling it would report the agency's median as the city's."""
    assert ("license_application", "license_issued") in sf.SAME_AGENCY_PAIRS
    sql = sf._lead_pairs_sql()
    assert "same_agency_processing" in sql and "cross_agency" in sql


def test_lead_pairs_sql_refuses_a_negative_lead():
    """A terminal event before the application is a renewal or a name collision
    on one lot. The guard is in the SQL, not in a caller."""
    assert "o.opened_on >= e.first_filed" in sf._lead_pairs_sql()


def test_lead_pairing_is_on_name_key_AND_bbl():
    """'joes pizza' is a hundred businesses. A citywide name-only join would
    pair a Bronx application with a Brooklyn inspection."""
    assert "USING (business_name_key, bbl)" in sf._lead_pairs_sql()
