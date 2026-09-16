"""DCWP licence intervals (model/licence_interval.py, sql/041).

What this table is for: the warehouse's first firm-survival clock. What it must
never do is invent one.

Five things under test:

(a) EVERY STATUS SURVIVES. The pre-registration assigns DCWP's ten statuses to
    event / competing-risk / censored / dropped, and DIFFERENTLY under its
    primary and strict definitions. A builder that dropped or recoded any of
    them would silently pick one arm of a check designed to run both ways.

(b) `end_kind` TELLS THE TRUTH. w7w3-xahh publishes no status-change date, so a
    non-Active licence whose expiry is in the future has an UNKNOWN end. It
    must be typed as a bound, never handed over as an observation.

(c) NO NEGATIVE DURATIONS, EVER, and `interval_end` never runs past the pull.

(d) ONE ROW PER LICENCE. DCWP repeats a licence number across address rows; two
    intervals for one licence would count one closure twice.

(e) THE JOIN USES THE RIGHT KEY. The project has TWO name normalisers --
    `chains.normalize.brand_key` and `poi_presence.name_key_of` -- and they do
    not agree ('DUANE READE #14' -> 'duane reade' vs '14 duane reade').
    Joining one against the other measured 0.1% and looked like a coverage
    finding; it was a category error.
"""
from __future__ import annotations

import datetime as dt

import pytest

from loci import db as locidb
from loci.model import licence_interval as li

ASOF = dt.date(2026, 9, 16)


def _con():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _filing(con, rows):
    """rows: (licence_nbr, name, created, expiry, status, category, lon, lat)."""
    for nbr, name, created, expiry, status, cat, lon, lat in rows:
        con.execute("""
            INSERT INTO staging.storefront_filing (
                filing_id, source, stage, business_name, business_name_key,
                bbl, match_method, borough, house_number, street_name,
                lon, lat, filed_on, status, status_date, category_hint,
                license_type, raw_id, provenance, ingested_at)
            VALUES (?, 'nyc_dcwp_licenses', 'license_issued', ?, ?,
                    '1000010001', 'feed_bbl', 'MN', '1', 'MAIN ST',
                    ?, ?, ?, ?, ?, ?, 'Premises', ?, 'test', now())
        """, [f"nyc_dcwp_licenses:license_issued:{nbr}", name,
              (name or "").lower().strip() or None,
              lon, lat, created, status, expiry, cat, nbr])


# --------------------------------------------------------- (a) every status

ALL_STATUSES = ["Active", "Expired", "Surrendered", "Revoked",
                "Failed to Renew", "Out of Business", "Suspended", "Voided",
                "Ready for Renewal", "Close"]


def test_every_dcwp_status_is_carried_verbatim():
    con = _con()
    _filing(con, [(f"{i}-DCA", f"SHOP {i}", dt.date(2020, 1, 1),
                   dt.date(2025, 1, 1), s, "Laundries", -73.98, 40.75)
                  for i, s in enumerate(ALL_STATUSES)])
    li.build(con, asof=ASOF)
    got = {r[0] for r in con.execute(
        "SELECT DISTINCT status FROM analysis.licence_interval").fetchall()}
    assert got == set(ALL_STATUSES)


def test_no_status_is_translated_into_a_closure_flag():
    """The table must carry no column that pre-judges the event definition."""
    cols = {r[0] for r in con_desc()}
    assert not {"is_closure", "closed", "is_event", "closure_date"} & cols


def con_desc():
    con = _con()
    return con.execute("DESCRIBE analysis.licence_interval").fetchall()


# ------------------------------------------------------------ (b) end_kind

@pytest.mark.parametrize("status,expiry,kind,end", [
    ("Active",      dt.date(2027, 1, 1), "active_censored", ASOF),
    ("Active",      None,                "active_censored", ASOF),
    ("Expired",     dt.date(2024, 5, 1), "expiry_observed", dt.date(2024, 5, 1)),
    ("Surrendered", dt.date(2027, 1, 1), "expiry_future",   ASOF),
    ("Revoked",     None,                "no_expiry",       ASOF),
])
def test_end_kind_names_what_is_actually_known(status, expiry, kind, end):
    con = _con()
    _filing(con, [("1-DCA", "SHOP", dt.date(2020, 1, 1), expiry, status,
                   "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    got = con.execute(
        "SELECT end_kind, interval_end FROM analysis.licence_interval").fetchone()
    assert got == (kind, end)


def test_a_surrendered_licence_never_reports_a_fabricated_event_date():
    """The one that matters. DCWP says WHAT happened, never WHEN. A future
    expiry on a surrendered licence must not be handed over as the end date."""
    con = _con()
    _filing(con, [("1-DCA", "SHOP", dt.date(2020, 1, 1), dt.date(2028, 1, 1),
                   "Surrendered", "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    end, kind, sdate = con.execute(
        "SELECT interval_end, end_kind, status_date "
        "FROM analysis.licence_interval").fetchone()
    assert end != dt.date(2028, 1, 1)
    assert kind == "expiry_future"
    assert sdate is None            # the feed publishes none; never guessed


def test_status_date_is_null_because_the_feed_publishes_none():
    con = _con()
    _filing(con, [("1-DCA", "S", dt.date(2020, 1, 1), dt.date(2024, 1, 1),
                   "Expired", "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    assert con.execute(
        "SELECT count(*) FROM analysis.licence_interval "
        "WHERE status_date IS NOT NULL").fetchone()[0] == 0


# ------------------------------------------------------ (c) duration sanity

def test_an_expiry_before_creation_cannot_make_a_negative_duration():
    """A real data error in the feed. Clamping is right; a negative duration
    would poison every median downstream and would not be caught by any type."""
    con = _con()
    _filing(con, [("1-DCA", "S", dt.date(2020, 1, 1), dt.date(2015, 1, 1),
                   "Expired", "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    end, days = con.execute(
        "SELECT interval_end, days_observed FROM analysis.licence_interval").fetchone()
    assert days == 0
    assert end == dt.date(2020, 1, 1)


def test_interval_end_never_runs_past_the_pull():
    con = _con()
    _filing(con, [("1-DCA", "S", dt.date(2020, 1, 1), dt.date(2030, 1, 1),
                   "Active", "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    assert con.execute(
        "SELECT count(*) FROM analysis.licence_interval "
        "WHERE interval_end > pulled_asof").fetchone()[0] == 0


# ------------------------------------------------------- (d) one per licence

def test_a_licence_number_yields_exactly_one_interval():
    con = _con()
    _filing(con, [("1-DCA", "S", dt.date(2020, 1, 1), dt.date(2024, 1, 1),
                   "Expired", "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    li.build(con, asof=ASOF)          # idempotent: not two rows, not two closures
    assert con.execute(
        "SELECT count(*) FROM analysis.licence_interval").fetchone()[0] == 1


def test_a_row_with_no_creation_date_is_dropped_not_dated_to_the_epoch():
    con = _con()
    _filing(con, [("1-DCA", "S", None, dt.date(2024, 1, 1), "Expired",
                   "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    assert con.execute(
        "SELECT count(*) FROM analysis.licence_interval").fetchone()[0] == 0


def test_other_sources_in_the_staging_table_are_ignored():
    con = _con()
    _filing(con, [("1-DCA", "S", dt.date(2020, 1, 1), dt.date(2024, 1, 1),
                   "Expired", "Laundries", -73.98, 40.75)])
    con.execute("""
        INSERT INTO staging.storefront_filing (
            filing_id, source, stage, filed_on, raw_id, match_method,
            provenance, ingested_at)
        VALUES ('x', 'nyc_dob_permit_issuance', 'permit_issued',
                DATE '2020-01-01', '9-XYZ', 'feed_bbl', 'test', now())""")
    li.build(con, asof=ASOF)
    assert {r[0] for r in con.execute(
        "SELECT licence_number FROM analysis.licence_interval").fetchall()} == {"1-DCA"}


# ------------------------------------------------------------ (e) the join key

def test_the_two_name_normalisers_are_not_interchangeable():
    """Pins the fact the join bug turned on. If these ever converge, the extra
    `poi_name_key` column becomes redundant and someone should notice."""
    from loci.chains.normalize import brand_key
    from loci.model.poi_presence import name_key_of
    assert brand_key("DUANE READE #14") != name_key_of("DUANE READE #14")


def test_poi_name_key_is_the_ledgers_normaliser_not_brand_key():
    from loci.model.poi_presence import name_key_of
    con = _con()
    _filing(con, [("1-DCA", "DUANE READE #14", dt.date(2020, 1, 1),
                   dt.date(2024, 1, 1), "Expired", "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    got = con.execute(
        "SELECT poi_name_key, business_name_key "
        "FROM analysis.licence_interval").fetchone()
    assert got[0] == name_key_of("DUANE READE #14")
    assert got[0] != got[1]


def test_the_poi_view_never_returns_two_rows_for_one_licence():
    """A licence on a corner lot with three same-name ledger rows must yield
    ONE. Without the QUALIFY, every match rate computed from this view exceeds
    100% -- the double-count bug in a different costume."""
    from loci.model.poi_presence import name_key_of
    con = _con()
    _filing(con, [("1-DCA", "SUNNY WASH", dt.date(2020, 1, 1),
                   dt.date(2024, 1, 1), "Expired", "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    key = name_key_of("SUNNY WASH")
    for i, dlon in enumerate((0.0, 0.00010, 0.00020)):
        con.execute("""
            INSERT INTO analysis.poi_presence (
                location_key, category, name_key, display_name, lon, lat,
                first_seen_month, last_seen_month, first_seen_kind,
                n_months_seen, ledger_started_month, last_snapshot_at)
            VALUES (?, 'laundry', ?, 'Sunny Wash', ?, 40.75,
                    '2026-09', '2026-09', 'observed', 1, '2026-09', now())
        """, [f"k{i}", key, -73.98 + dlon])
    rows = con.execute(
        "SELECT licence_number, count(*) FROM analysis.licence_interval_poi "
        "GROUP BY 1").fetchall()
    assert rows == [("1-DCA", 1)]


def test_a_different_name_within_50m_does_not_match():
    """Proximity is NOT identity. Accepting the nearest POI regardless of name
    would attribute a supermarket's survival to a laundromat -- the real pair
    that motivated this test was 'BANANA SUPERMARKET INC.' and
    'Jkl Laundromat Inc' 30 m apart."""
    con = _con()
    _filing(con, [("1-DCA", "BANANA SUPERMARKET INC", dt.date(2020, 1, 1),
                   dt.date(2024, 1, 1), "Expired", "Laundries", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    con.execute("""
        INSERT INTO analysis.poi_presence (
            location_key, category, name_key, display_name, lon, lat,
            first_seen_month, last_seen_month, first_seen_kind,
            n_months_seen, ledger_started_month, last_snapshot_at)
        VALUES ('k1', 'laundry', 'jkl', 'Jkl Laundromat Inc', -73.9801, 40.75,
                '2026-09', '2026-09', 'observed', 1, '2026-09', now())""")
    assert con.execute(
        "SELECT count(*) FROM analysis.licence_interval_poi").fetchone()[0] == 0


def test_the_category_map_is_the_roster_vocabulary_not_the_inspections_one():
    """The first draft of this map reused sources/.../dcwp.py's INSPECTIONS
    vocabulary ('Retail Laundry', 'Restaurant - 818'). Those values do not
    occur in w7w3-xahh and the map matched 6 rows in 72,451."""
    assert "Laundries" in li.CATEGORY_MAP
    assert "Retail Laundry" not in li.CATEGORY_MAP
    assert "Restaurant - 818" not in li.CATEGORY_MAP


def test_industrial_laundry_is_excluded_on_the_record():
    assert li.category_of("Industrial Laundry") == (None, None)
    assert "Industrial Laundry" in li.DELIBERATELY_UNMAPPED
    assert li.category_of("Laundries") == ("laundry", "high")


def test_an_unmapped_category_keeps_its_row():
    """A licence Loci cannot categorise is still a licence. Dropping it would
    make the table describe 4% of DCWP and call it DCWP."""
    con = _con()
    _filing(con, [("1-DCA", "TOW CO", dt.date(2020, 1, 1), dt.date(2024, 1, 1),
                   "Expired", "Tow Truck Driver", -73.98, 40.75)])
    li.build(con, asof=ASOF)
    cat, n = con.execute(
        "SELECT loci_category, count(*) FROM analysis.licence_interval "
        "GROUP BY 1").fetchone()
    assert (cat, n) == (None, 1)
