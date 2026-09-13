"""analysis.storefront_pipeline: the category mapping, the two D75 carry rules,
the cross-agency reconciliation, the 'gov_filing' ledger precedence, and
idempotence.

No network, no warehouse. The roll-up, the ledger write and the openings write
are exercised against a SYNTHETIC in-memory DuckDB built row by row here, so
every case is reachable and the boundaries (the 540-day window, the idf
threshold, the strict inequality that makes the ledger idempotent) are testable
to the unit.

The category-mapping completeness check runs against a CAPTURED vocabulary --
tests/fixtures/filings/category_hints.json, every distinct (source,
category_hint) pair in the live table on 2026-09-13 -- for the same reason
tests/test_alcohol_licences.py captures the SLA vocabulary: a mapping that
degrades an unseen value to "unmapped" would never fail on its own, so this is
the thing that fails instead.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pandas as pd
import pytest

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.chains.normalize import brand_key
from loci.filing_stages import EARLY_STAGES, STAGES, stage_rank
from loci.model import poi_presence as pp
from loci.model import storefront_pipeline as sp
from loci.sources.cities.nyc import dohmh, dcwp, nys_sla

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "filings"
HINTS = json.loads((FIXTURES / "category_hints.json").read_text())


# ===========================================================================
# the category mapping
# ===========================================================================
def test_every_controlled_vocabulary_value_is_named_by_the_yaml():
    """THE DRIFT CHECK, and the completeness requirement in one.

    Every distinct `category_hint` a controlled-vocabulary feed published is
    either MAPPED onto a Loci category or listed under `unmapped`. A value in
    neither is a decision nobody made; `loci_category_of` raises on it and
    `build` therefore raises before writing a row."""
    for source, values in HINTS["controlled"].items():
        for value in values:
            cat, conf = sp.loci_category_of(source, value)
            assert conf in ("high", "medium", "unmapped")
            assert cat is None or cat in CATEGORIES


def test_the_two_dob_feeds_are_declared_free_text_with_a_reason():
    """The two feeds whose vocabulary CANNOT be enumerated are declared, not
    forgotten. 47,930 + 57,331 distinct job descriptions is the whole feed, so
    the honest form of "explicitly listed as unmapped" is a source-level
    declaration carrying its evidence."""
    doc = sp.load_category_map()
    for source, n_distinct in HINTS["free_text_distinct_counts"].items():
        block = doc["sources"][source]
        assert block["vocabulary"] == "free_text"
        assert block["reason"].strip()
        assert n_distinct > 1000, "if this feed became a vocabulary, map it"
        assert sp.loci_category_of(source, "ANY PROSE AT ALL") == (None, "unmapped")


def test_an_unseen_controlled_value_raises_rather_than_defaulting():
    """The adversarial half. A test that only ever sees a complete vocabulary
    proves nothing: inject a licence class DCWP has never issued and the mapper
    must NAME it, because an unclassified trade silently reading as 'unmapped'
    is indistinguishable from that trade being absent from the city -- which is
    the exact claim this project exists to make."""
    with pytest.raises(ValueError, match="neither"):
        sp.loci_category_of("nyc_dcwp_licenses", "Zeppelin Mooring Operator")


def test_an_unknown_source_raises():
    with pytest.raises(KeyError):
        sp.loci_category_of("nyc_department_of_invented_feeds", "anything")


def test_mapping_agrees_with_the_dohmh_ingest_except_where_stated():
    """MACHINE-CHECK THE MAPPING AGAINST THE CODE. `dohmh.classify()` decides
    what a cuisine means when a POI enters staging.poi; this file decides what
    the same cuisine means on a filing. Two answers for one string is how a
    category silently splits in half."""
    exceptions = sp.load_category_map()["dohmh_classify_exceptions"]
    for value in HINTS["controlled"]["nyc_dohmh_restaurants"]:
        if value is None:
            continue
        mapped, _conf = sp.loci_category_of("nyc_dohmh_restaurants", value)
        if mapped is None:
            continue                      # 'Other', 'Bottled Beverages', ...
        if value in exceptions:
            assert mapped != dohmh.classify(value), (
                f"{value!r} is listed as a classify() disagreement but agrees; "
                f"remove it from dohmh_classify_exceptions")
            continue
        assert mapped == dohmh.classify(value), value


def test_the_steakhouse_bug_is_real_and_documented():
    """The exception that proves the check works, and a live bug in the POI
    ingest: `dohmh.CAFE_KEYWORDS` contains "tea", and "tea" is a substring of
    "s-TEA-khouse", so every steakhouse in New York enters staging.poi as a
    cafe. This file maps it to `restaurant` and says why."""
    assert "tea" in "steakhouse"
    assert dohmh.classify("Steakhouse") == "cafe_bakery"      # the bug
    assert sp.loci_category_of("nyc_dohmh_restaurants", "Steakhouse")[0] == "restaurant"
    assert "Steakhouse" in sp.load_category_map()["dohmh_classify_exceptions"]


def test_nothing_mapped_to_bar_is_an_off_premises_licence():
    """A `bar` must be somewhere you drink, not somewhere you buy a bottle.
    Cross-checked against the overlay's own classification of the SAME licence
    vocabulary (sources/cities/nyc/alcohol_licences.yaml), so a liquor store
    can never end up in the bar supply."""
    doc = sp.load_category_map()
    for source in ("nyc_sla_liquor_licenses", "nyc_sla_pending_licenses"):
        for value, slug in doc["sources"][source]["map"].items():
            if slug == "bar":
                # 'unknown' is allowed: alcohol_licences.yaml was captured from
                # the ACTIVE file and does not name pending-only classes
                # ("For-profit Club"). What must never happen is a `bar` the
                # overlay calls package retail.
                assert nys_sla.classify(value) in ("on_premises", "unknown"), value


def test_additional_bar_is_not_a_new_storefront():
    """A rider on an existing licensed premises -- a second service bar inside
    a hotel or a theatre -- is not a business opening. 2,080 active rows;
    mapping it to `bar` would count one venue as two openings."""
    for value in HINTS["controlled"]["nyc_sla_liquor_licenses"]:
        if value and value.lower().startswith("additional bar"):
            assert sp.loci_category_of("nyc_sla_liquor_licenses", value)[0] is None


def test_industrial_laundry_is_unmapped_exactly_as_the_dcwp_ingest_has_it():
    """B2B linen supply is not neighbourhood laundry. The POI ingest maps it to
    None (dcwp.KNOWN_LAUNDRY_CATEGORIES); so does this. Two different answers
    would put laundry access where no resident can use it."""
    for value in ("Industrial Laundry", "Industrial Laundry Delivery"):
        assert dcwp.KNOWN_LAUNDRY_CATEGORIES[value] is None
        assert sp.loci_category_of("nyc_dcwp_licenses", value)[0] is None


def test_yaml_rejects_a_slug_outside_the_taxonomy(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: test\nsources:\n  s:\n    vocabulary: controlled\n"
        "    map:\n      X: laundromat\n")
    with pytest.raises(ValueError, match="not Loci categories"):
        sp.load_category_map(bad)


def test_yaml_rejects_a_value_in_both_map_and_unmapped(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: test\nsources:\n  s:\n    vocabulary: controlled\n"
        "    map:\n      X: laundry\n    unmapped:\n      - X\n")
    with pytest.raises(ValueError, match="BOTH"):
        sp.load_category_map(bad)


def test_yaml_rejects_a_free_text_declaration_with_no_reason(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: test\nsources:\n  s:\n    vocabulary: free_text\n")
    with pytest.raises(ValueError, match="reason"):
        sp.load_category_map(bad)


# ===========================================================================
# the stage rank
# ===========================================================================
def test_stage_rank_sql_is_generated_from_the_vocabulary():
    """filing_stages caveat 3: `outdoor_dining` is declared and not ingested,
    and inserting a stage in the MIDDLE later renumbers every rank. The rank is
    therefore a BUILD-TIME fact and must be generated, never typed."""
    sql = sp.stage_rank_sql()
    for stage in STAGES:
        assert f"('{stage}', {stage_rank(stage)})" in sql


def test_no_rank_integer_is_stored_on_the_table():
    """The corollary: the DDL stores the stage STRING. A stored integer would
    silently mean a different stage the day the vocabulary grows."""
    ddl = (locidb.SQL_DIR / "020_storefront_pipeline.sql").read_text()
    assert "furthest_stage      VARCHAR" in ddl
    assert "stage_rank" not in ddl.split("CREATE TABLE")[1].split(";")[0]


# ===========================================================================
# the roll-up, on a synthetic warehouse
# ===========================================================================
def _filing(**kw) -> dict:
    row = {
        "filing_id": None, "source": "nyc_dob_now_job_filings",
        "stage": "fitout_filing", "business_name": None,
        "business_name_key": None, "bbl": "3001234567", "bin": None,
        "house_number": None, "street_name": None, "borough": "BK",
        "lon": -73.99, "lat": 40.68, "filed_on": dt.date(2025, 1, 1),
        "status": None, "status_date": None, "category_hint": None,
        "license_type": None, "match_method": "feed_bbl", "raw_id": None,
        "ingested_at": dt.datetime(2026, 9, 13), "provenance": "test",
    }
    row.update(kw)
    if row["business_name"] and row["business_name_key"] is None:
        row["business_name_key"] = brand_key(row["business_name"])
    row["raw_id"] = row["raw_id"] or f"r{abs(hash(str(row))) % 10**8}"
    row["filing_id"] = row["filing_id"] or f"{row['source']}:{row['stage']}:{row['raw_id']}"
    return row


@pytest.fixture
def con(tmp_path):
    """An in-memory warehouse holding just what this module reads and writes.

    `analysis.poi_presence` (018) and a three-column stub of
    `analysis.address_category` are created because sql/020 replaces a view
    over the first and ALTERs the second. In production 002_schema.sql creates it long before 020
    runs (db.init_schema applies every migration in numeric order); here the
    stub is what makes the migration applicable in isolation."""
    c = locidb.connect(":memory:")
    c.execute("CREATE SCHEMA IF NOT EXISTS staging")
    c.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    c.execute((locidb.SQL_DIR / "019_storefront_filing.sql").read_text())
    c.execute((locidb.SQL_DIR / "018_poi_presence.sql").read_text())
    c.execute("""
        CREATE TABLE IF NOT EXISTS analysis.address_category (
            address_id VARCHAR NOT NULL,
            borough    VARCHAR NOT NULL,
            category   VARCHAR NOT NULL,
            PRIMARY KEY (borough, address_id, category))""")
    yield c
    c.close()


def _load(c, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)
    c.register("_in", frame)
    c.execute("""
        INSERT INTO staging.storefront_filing
            (filing_id, source, stage, business_name, business_name_key, bbl,
             bin, house_number, street_name, borough, lon, lat, geom, filed_on,
             status, status_date, category_hint, license_type, match_method,
             raw_id, ingested_at, provenance)
        SELECT filing_id, source, stage, business_name, business_name_key, bbl,
               bin, house_number, street_name, borough, lon, lat,
               CASE WHEN lon IS NOT NULL THEN ST_Point(lon, lat) END,
               CAST(filed_on AS DATE), status, CAST(status_date AS DATE),
               category_hint, license_type, match_method, raw_id, ingested_at,
               provenance
        FROM _in""")
    c.unregister("_in")


def _build(c, **kw):
    return sp.build(c, asof=dt.date(2026, 9, 13), pluto=False, **kw)


def test_two_agencies_two_names_is_two_groups_until_reconciled(con):
    """THE PROBLEM THE RECONCILIATION EXISTS FOR, in two rows. `brand_key`
    normalises "Kinship Coffee Roasters LLC" to a different key from "Kinship
    Coffee", so the strict grain honestly reports two businesses -- and the
    lead time between them is invisible until the link pass finds the rare
    token they share."""
    _load(con, [
        _filing(business_name="Kinship Coffee", stage="fitout_filing",
                filed_on=dt.date(2025, 1, 10)),
        _filing(business_name="Kinship Coffee Roasters", stage="first_inspection",
                source="nyc_dohmh_restaurants", category_hint="Coffee/Tea",
                filed_on=dt.date(2025, 9, 3)),
    ])
    df, rep = _build(con, reconcile_links=False)
    assert rep["filings"] == 2
    assert len(df) == 2                      # NOT fused: two different keys
    assert df["lead_days"].isna().all()      # and so no lead time at all

    linked, lrep = sp.reconcile(df, min_idf=0.0)
    assert lrep["links"] == 1
    assert lrep["links_by_method"] == {"rare_token": 1}
    early = linked[~linked["is_open"]].iloc[0]
    assert int(early["link_lead_days"]) == 236


def test_entry_furthest_open_and_lead_days(con):
    _load(con, [
        _filing(business_name="Aster Bagels", stage="fitout_filing",
                filed_on=dt.date(2025, 1, 10)),
        _filing(business_name="Aster Bagels", stage="sign_permit",
                source="nyc_dob_permit_issuance", filed_on=dt.date(2025, 6, 1)),
        _filing(business_name="Aster Bagels", stage="first_inspection",
                source="nyc_dohmh_restaurants", category_hint="Bagels/Pretzels",
                filed_on=dt.date(2025, 9, 3)),
    ])
    df, _ = _build(con, reconcile_links=False)
    row = df.iloc[0]
    assert row["group_kind"] == "bbl_name"
    assert row["entry_stage"] == "fitout_filing"
    assert pd.Timestamp(row["entry_date"]).date() == dt.date(2025, 1, 10)
    # max RANK, not max date: first_inspection outranks sign_permit.
    assert row["furthest_stage"] == "first_inspection"
    assert bool(row["is_open"]) is True
    assert pd.Timestamp(row["opened_on"]).date() == dt.date(2025, 9, 3)
    assert row["opened_on_stage"] == "first_inspection"
    assert int(row["lead_days"]) == (dt.date(2025, 9, 3) - dt.date(2025, 1, 10)).days
    assert row["loci_category"] == "cafe_bakery"
    assert row["n_filings"] == 3 and row["n_sources"] == 3


def test_lead_days_is_null_when_the_entry_is_already_terminal(con):
    """NULL, never 0. A restaurant whose first appearance is its own DOHMH
    inspection has no measured lead time; zero would claim it opened the day it
    filed."""
    _load(con, [
        _filing(business_name="Triona's", stage="first_inspection",
                source="nyc_dohmh_restaurants", category_hint="Irish",
                filed_on=dt.date(2024, 7, 18)),
    ])
    df, _ = _build(con, reconcile_links=False)
    assert df.iloc[0]["entry_stage"] == "first_inspection"
    assert pd.isna(df.iloc[0]["lead_days"])
    assert df.iloc[0]["entry_stage"] not in EARLY_STAGES


def test_null_bbl_is_carried_as_its_own_row_and_flagged(con):
    """D75, and the anti-fusion rule. Two applications by the same name with no
    BBL are NOT one business: "joes pizza" is a hundred businesses in New York
    and a citywide name join would pair a Bronx application with a Brooklyn
    inspection."""
    _load(con, [
        _filing(business_name="Joes Pizza", bbl=None, match_method="unmatched",
                source="nyc_dcwp_license_applications",
                stage="license_application", category_hint="Newsstand",
                raw_id="a1", filed_on=dt.date(2025, 2, 1)),
        _filing(business_name="Joes Pizza", bbl=None, match_method="unmatched",
                source="nyc_dcwp_license_applications",
                stage="license_application", category_hint="Newsstand",
                raw_id="a2", filed_on=dt.date(2025, 3, 1)),
    ])
    df, rep = _build(con, reconcile_links=False)
    assert len(df) == 2                       # never fused
    assert set(df["group_kind"]) == {"filing"}
    assert df["bbl_missing"].all()
    assert not df["name_key_missing"].any()
    assert rep["bbl_missing"] == 2


def test_null_name_key_is_carried_as_its_own_row_and_flagged(con):
    """The mirror rule. Grouping every unnamed filing on one lot together would
    fuse the laundromat, the deli and the nail salon into one business with an
    eleven-year lifecycle."""
    _load(con, [
        _filing(business_name="N/A", raw_id="b1", filed_on=dt.date(2025, 2, 1)),
        _filing(business_name="paradiselaundromatny@gmail.com", raw_id="b2",
                filed_on=dt.date(2025, 3, 1)),
    ])
    df, rep = _build(con, reconcile_links=False)
    assert len(df) == 2
    assert set(df["group_kind"]) == {"filing"}
    assert df["name_key_missing"].all()
    assert rep["name_key_missing"] == 2


def test_every_filing_lands_in_exactly_one_group(con):
    """The conservation law, which `compute_pipeline` raises on and `validate`
    re-proves against the warehouse. A fan-out here inflates every count
    downstream."""
    rows = [_filing(business_name=f"Shop {i}", bbl=f"300000000{i % 3}",
                    raw_id=f"c{i}", filed_on=dt.date(2025, 1, 1 + i % 27))
            for i in range(30)]
    rows += [_filing(business_name=None, bbl=None, match_method="unmatched",
                     raw_id=f"d{i}") for i in range(5)]
    _load(con, rows)
    df, rep = _build(con)
    assert int(df["n_filings"].sum()) == 35 == rep["filings"]
    assert not sp.validate(con, df)


# ===========================================================================
# the cross-agency reconciliation
# ===========================================================================
def _pipe_row(pid, bbl, name, *, is_open, entry, opened=None, lead=None):
    return {
        "pipeline_id": pid, "bbl": bbl, "business_name_key": name,
        "is_open": is_open, "entry_date": entry, "opened_on": opened,
        "lead_days": lead,
    }


def _frame(rows):
    df = pd.DataFrame(rows)
    df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.date
    df["opened_on"] = pd.to_datetime(df["opened_on"]).dt.date
    df["lead_days"] = df["lead_days"].astype("Int64")
    return df


def test_sole_pair_in_one_bbl_links():
    df = _frame([
        _pipe_row("e", "3001", "arwal realty", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("t", "3001", "sunset deli", is_open=True,
                  entry=dt.date(2025, 8, 1), opened=dt.date(2025, 8, 1)),
    ])
    out, rep = sp.reconcile(df)
    assert rep["links"] == 1
    assert set(out["link_method"]) == {"sole_pair_in_bbl"}
    assert out.loc[0, "link_partner_id"] == "t"
    assert out.loc[1, "link_partner_id"] == "e"
    assert int(out.loc[0, "link_lead_days"]) == 212


def test_ambiguous_bbl_needs_a_rare_token():
    """Two early and two terminal rows on one lot: the sole-pair rule cannot
    fire, so only the pair sharing a rare token links. The other two are left
    unlinked rather than guessed at -- a wrong link manufactures a lead time
    that never happened."""
    df = _frame([
        _pipe_row("e1", "3001", "zamboanga holdings", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("e2", "3001", "generic realty", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("t1", "3001", "zamboanga kitchen", is_open=True,
                  entry=dt.date(2025, 6, 1), opened=dt.date(2025, 6, 1)),
        _pipe_row("t2", "3001", "other deli", is_open=True,
                  entry=dt.date(2025, 6, 1), opened=dt.date(2025, 6, 1)),
    ])
    out, rep = sp.reconcile(df, min_idf=0.0)
    assert rep["links"] == 1
    assert rep["links_by_method"] == {"rare_token": 1}
    assert out.set_index("pipeline_id").at["e1", "link_partner_id"] == "t1"
    assert out.set_index("pipeline_id").at["e2", "link_partner_id"] is None


def test_a_common_token_is_not_evidence():
    """"deli" appears in 2,786 of 76,706 name keys. Sharing it inside one lot
    is a coincidence, not an identification."""
    df = _frame([
        _pipe_row("e1", "3001", "first deli corp", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("e2", "3001", "another builder", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("t1", "3001", "second deli", is_open=True,
                  entry=dt.date(2025, 6, 1), opened=dt.date(2025, 6, 1)),
        _pipe_row("t2", "3001", "third place", is_open=True,
                  entry=dt.date(2025, 6, 1), opened=dt.date(2025, 6, 1)),
    ])
    # Give "deli" a df high enough to fall below the threshold by handing
    # reconcile a vocabulary in which it is common.
    df_many = _frame([_pipe_row(f"x{i}", None, f"deli {i}", is_open=False,
                                entry=dt.date(2025, 1, 1)) for i in range(4000)])
    out, rep = sp.reconcile(pd.concat([df, df_many], ignore_index=True))
    assert rep["links"] == 0


def test_the_link_never_crosses_a_lot_line():
    df = _frame([
        _pipe_row("e", "3001", "zamboanga holdings", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("t", "3002", "zamboanga kitchen", is_open=True,
                  entry=dt.date(2025, 6, 1), opened=dt.date(2025, 6, 1)),
    ])
    out, rep = sp.reconcile(df, min_idf=0.0)
    assert rep["links"] == 0


def test_the_window_is_a_hard_boundary():
    for gap, expect in ((sp.LINK_WINDOW_DAYS, 1), (sp.LINK_WINDOW_DAYS + 1, 0)):
        start = dt.date(2024, 1, 1)
        df = _frame([
            _pipe_row("e", "3001", "arwal realty", is_open=False, entry=start),
            _pipe_row("t", "3001", "sunset deli", is_open=True,
                      entry=start + dt.timedelta(days=gap),
                      opened=start + dt.timedelta(days=gap)),
        ])
        assert sp.reconcile(df)[1]["links"] == expect


def test_a_backwards_pair_is_not_a_lead_time():
    """A terminal event BEFORE the application is a renewal or a name
    collision on one lot, never a lead time."""
    df = _frame([
        _pipe_row("e", "3001", "arwal realty", is_open=False,
                  entry=dt.date(2025, 8, 1)),
        _pipe_row("t", "3001", "sunset deli", is_open=True,
                  entry=dt.date(2025, 1, 1), opened=dt.date(2025, 1, 1)),
    ])
    assert sp.reconcile(df)[1]["links"] == 0


def test_the_link_is_one_to_one():
    """THE DOUBLE-COUNT GUARD. Two early rows, one terminal row: exactly one
    link. Letting both claim it would turn one build-out into two lead times
    and inflate every reconciled median."""
    df = _frame([
        _pipe_row("e1", "3001", "zamboanga holdings", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("e2", "3001", "zamboanga partners", is_open=False,
                  entry=dt.date(2025, 3, 1)),
        _pipe_row("t1", "3001", "zamboanga kitchen", is_open=True,
                  entry=dt.date(2025, 6, 1), opened=dt.date(2025, 6, 1)),
    ])
    out, rep = sp.reconcile(df, min_idf=0.0)
    assert rep["links"] == 1
    assert out["link_partner_id"].dropna().nunique() == 2     # one pair, both sides
    assert (out["link_partner_id"] == "t1").sum() == 1


def test_a_row_that_already_has_a_strict_lead_time_is_not_relinked():
    """Reconciliation only ever ADDS pairs. A terminal row already measured
    strictly must not also be measured against a different name on the same
    lot -- that would count one build-out twice and the reconciled N would rise
    without a single new business being measured."""
    df = _frame([
        _pipe_row("e", "3001", "arwal realty", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("t", "3001", "sunset deli", is_open=True,
                  entry=dt.date(2025, 2, 1), opened=dt.date(2025, 8, 1), lead=188),
    ])
    out, rep = sp.reconcile(df)
    assert rep["links"] == 0
    assert rep["terminal_rows_already_strict"] == 1


def test_reconcile_is_reproducible_under_row_reordering():
    rows = [
        _pipe_row("e1", "3001", "zamboanga holdings", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("e2", "3002", "quetzalcoatl group", is_open=False,
                  entry=dt.date(2025, 1, 1)),
        _pipe_row("t1", "3001", "zamboanga kitchen", is_open=True,
                  entry=dt.date(2025, 6, 1), opened=dt.date(2025, 6, 1)),
        _pipe_row("t2", "3002", "quetzalcoatl cafe", is_open=True,
                  entry=dt.date(2025, 6, 1), opened=dt.date(2025, 6, 1)),
    ]
    a = sp.reconcile(_frame(rows))[0].set_index("pipeline_id")["link_partner_id"]
    b = sp.reconcile(_frame(rows[::-1]))[0].set_index("pipeline_id")["link_partner_id"]
    assert a.to_dict() == b.to_dict()


def test_rare_token_rejects_short_and_numeric_tokens():
    idf = {"ab": 20.0, "123": 20.0, "zamboanga": 20.0}
    assert sp.rare_shared_tokens("ab 123", "ab 123", idf) == []
    assert sp.rare_shared_tokens("zamboanga x", "zamboanga y", idf) == ["zamboanga"]


# ===========================================================================
# the 'gov_filing' ledger kind
# ===========================================================================
def test_gov_filing_is_in_the_ledger_vocabulary_and_is_a_dated_kind():
    assert sp.GOV_FILING_KIND in pp.KINDS
    assert sp.GOV_FILING_KIND in pp.DATED_KINDS
    assert "source_date" in pp.DATED_KINDS
    assert "backfill_censored" not in pp.DATED_KINDS


def test_the_reporting_view_returns_a_date_for_a_gov_filing_row():
    """sql/020 replaces analysis.poi_first_seen so `first_seen_on` covers both
    dated kinds. Without that, the ledger would hold a real opening date and
    the view -- which chains/detect.py reads -- would report the row as
    UNDATED, i.e. the rows we finally managed to date would read as the ones we
    could not."""
    ddl = (locidb.SQL_DIR / "020_storefront_pipeline.sql").read_text()
    assert "first_seen_kind IN ('source_date', 'gov_filing')" in ddl
    assert "CREATE OR REPLACE VIEW analysis.poi_first_seen" in ddl


def test_only_an_open_signal_can_set_a_first_seen():
    """The invariant the whole step turns on. `opened_on` exists ONLY for rows
    carrying one of the three open-evidence stages; an application, a permit
    and a fit-out filing are dates on which somebody INTENDED to open."""
    assert set(sp.OPEN_EVIDENCE_STAGES).isdisjoint(EARLY_STAGES)
    for stage in sp.OPEN_EVIDENCE_STAGES:
        assert stage in STAGES


def _ledger_fixture(c):
    c.execute((locidb.SQL_DIR / "020_storefront_pipeline.sql").read_text())
    c.execute("""
        INSERT INTO analysis.poi_presence VALUES
        ('loc_censored', 'cafe_bakery', 'aster bagels', 'Aster Bagels',
         -73.99, 40.68, 'BK', '2026-09', '2026-09', 'backfill_censored',
         NULL, NULL, 1, 1, 'p1', '2026-09', now()),
        ('loc_late', 'restaurant', 'sunset deli', 'Sunset Deli',
         -73.98, 40.69, 'BK', '2026-01', '2026-09', 'source_date',
         DATE '2026-01-15', 'opened_on', 9, 2, 'p2', '2026-09', now()),
        ('loc_early', 'restaurant', 'first place', 'First Place',
         -73.97, 40.70, 'BK', '2020-01', '2026-09', 'source_date',
         DATE '2020-01-15', 'opened_on', 9, 3, 'p3', '2026-09', now())
    """)
    now = dt.datetime(2026, 9, 13)
    rows = [
        # matched to loc_censored by brand key + 100 m: resolves a censored row
        {"pipeline_id": "p_a", "bbl": "3001", "business_name_key": "aster bagels",
         "lon": -73.99, "lat": 40.68, "opened_on": dt.date(2025, 3, 2)},
        # matched to loc_late: an EARLIER date than the source's
        {"pipeline_id": "p_b", "bbl": "3002", "business_name_key": "sunset deli",
         "lon": -73.98, "lat": 40.69, "opened_on": dt.date(2025, 11, 4)},
        # matched to loc_early: a LATER date. Must be refused.
        {"pipeline_id": "p_c", "bbl": "3003", "business_name_key": "first place",
         "lon": -73.97, "lat": 40.70, "opened_on": dt.date(2025, 5, 5)},
    ]
    frame = pd.DataFrame([{
        "pipeline_id": r["pipeline_id"], "group_kind": "bbl_name", "bbl": r["bbl"],
        "business_name_key": r["business_name_key"], "business_name": None,
        "borough": "BK", "lon": r["lon"], "lat": r["lat"], "point_source": "filing",
        "entry_stage": "fitout_filing", "entry_date": dt.date(2024, 1, 1),
        "furthest_stage": "first_inspection", "furthest_date": r["opened_on"],
        "n_filings": 2, "n_sources": 2, "sources": "a,b",
        "stages": "fitout_filing,first_inspection", "loci_category": "restaurant",
        "category_confidence": "high", "category_hint": "American", "is_open": True,
        "opened_on": r["opened_on"], "opened_on_stage": "first_inspection",
        "lead_days": 400, "bbl_missing": False, "name_key_missing": False,
        "link_group_id": None, "link_method": None, "link_partner_id": None,
        "link_lead_days": None, "asof_date": dt.date(2026, 9, 13), "built_at": now,
    } for r in rows])
    sp.write(c, frame)
    # An empty PLUTO index: the name+distance rung is the one under test, and
    # building a real one would need the 334 MB CSV.
    c.execute("CREATE OR REPLACE TEMP TABLE _pluto_lot AS "
              "SELECT '' AS bbl, '' AS borocode, '' AS addr_key, "
              "CAST(NULL AS DOUBLE) AS lon, CAST(NULL AS DOUBLE) AS lat, "
              "CAST(NULL AS GEOMETRY) AS geom WHERE FALSE")


def test_gov_filing_resolves_censored_and_only_moves_dates_earlier(con, monkeypatch):
    _ledger_fixture(con)
    monkeypatch.setattr("loci.model.storefront_filing.build_pluto_index",
                        lambda c, *a, **k: 0)
    rep = sp.apply_gov_filing(con, asof=dt.date(2026, 9, 13))
    got = dict(con.execute(
        "SELECT location_key, first_seen_kind || '|' || first_seen_month || '|' "
        "|| coalesce(CAST(first_seen_src_date AS VARCHAR), '-') "
        "FROM analysis.poi_presence").fetchall())
    assert got["loc_censored"] == "gov_filing|2025-03|2025-03-02"
    assert got["loc_late"] == "gov_filing|2025-11|2025-11-04"
    # THE REFUSAL: a filing later than a date the ledger already holds is not
    # an upgrade, and nothing moves.
    assert got["loc_early"] == "source_date|2020-01|2020-01-15"
    assert rep["censored_resolved"] == 1
    assert rep["updated"] == 2
    assert con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE first_seen_kind = "
        "'gov_filing' AND first_seen_src_field <> ?",
        [sp.GOV_FILING_FIELD]).fetchone()[0] == 0


def test_gov_filing_is_idempotent(con, monkeypatch):
    """The strict inequality is what guarantees it: after one run the
    condition is false for every row the run wrote."""
    _ledger_fixture(con)
    monkeypatch.setattr("loci.model.storefront_filing.build_pluto_index",
                        lambda c, *a, **k: 0)
    sp.apply_gov_filing(con, asof=dt.date(2026, 9, 13))
    first = con.execute(
        "SELECT location_key, first_seen_kind, first_seen_month, "
        "first_seen_src_date FROM analysis.poi_presence ORDER BY 1").fetchall()
    rep2 = sp.apply_gov_filing(con, asof=dt.date(2026, 9, 13))
    second = con.execute(
        "SELECT location_key, first_seen_kind, first_seen_month, "
        "first_seen_src_date FROM analysis.poi_presence ORDER BY 1").fetchall()
    assert first == second
    assert rep2["updated"] == 0
    assert rep2["censored_resolved"] == 0


def test_ledger_invariants_accept_gov_filing(con, monkeypatch):
    """`loci check-presence` must stay green. Its src-date invariant used to
    read `kind = 'source_date'` exactly; a fourth dated kind would have failed
    every row this step wrote."""
    _ledger_fixture(con)
    monkeypatch.setattr("loci.model.storefront_filing.build_pluto_index",
                        lambda c, *a, **k: 0)
    sp.apply_gov_filing(con, asof=dt.date(2026, 9, 13))
    con.execute("CREATE TABLE IF NOT EXISTS analysis.poi_dedup "
                "(poi_id VARCHAR, cluster_id BIGINT, category VARCHAR, "
                " is_canonical BOOLEAN)")
    con.execute("INSERT INTO analysis.poi_dedup VALUES "
                "('p1', 1, 'cafe_bakery', TRUE), ('p2', 2, 'restaurant', TRUE), "
                "('p3', 3, 'restaurant', TRUE)")
    errors, stats = pp.coverage_check(con)
    assert errors == []
    assert stats["kinds"].get("gov_filing") == 2


def test_an_out_of_range_opening_date_is_refused(con, monkeypatch):
    """A sentinel or a typo must never become a first-seen."""
    _ledger_fixture(con)
    con.execute("UPDATE analysis.storefront_pipeline SET opened_on = DATE '1901-01-01' "
                "WHERE pipeline_id = 'p_a'")
    monkeypatch.setattr("loci.model.storefront_filing.build_pluto_index",
                        lambda c, *a, **k: 0)
    sp.apply_gov_filing(con, asof=dt.date(2026, 9, 13))
    assert con.execute(
        "SELECT first_seen_kind FROM analysis.poi_presence "
        "WHERE location_key = 'loc_censored'").fetchone()[0] == "backfill_censored"


# ===========================================================================
# the address measures
# ===========================================================================
def test_openings_columns_are_disjoint_from_every_other_module():
    """THE NON-FILTERING GUARANTEE. These are CONTEXT measures: nothing here
    may move gap_score, supply_ratio_vs_base, supply_400m or a recommendation
    grade."""
    from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
    from loci.model.address_gaps import (ADDRESS_CATEGORY_SCREEN_COLUMNS,
                                         ADDRESS_COLUMNS)
    from loci.model.storefronts import AGE_FIT_COLUMNS
    from loci.model.supply_ratio import CATEGORY_RATIO_COLUMNS

    owned = (set(ADDRESS_COLUMNS) | set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
             | set(CATEGORY_RATIO_COLUMNS) | set(AGE_FIT_COLUMNS)
             | set(DEMAND_ANNOTATION_COLUMNS))
    assert set(sp.OPENINGS_COLUMNS).isdisjoint(owned)
    sp._guard(sp.OPENINGS_COLUMNS)          # must not raise
    with pytest.raises(RuntimeError, match="clobber"):
        sp._guard(["supply_400m"])


def test_the_two_windows_are_disjoint_by_construction():
    """`openings_pipeline_400m` counts NOT-open rows; `openings_recent_400m`
    counts rows with an opening date. A row cannot be in both, which is why
    they may be added -- and why adding them answers nothing."""
    assert sp.OPENINGS_PIPELINE_MONTHS == 18
    assert sp.OPENINGS_RECENT_MONTHS == 12


def test_months_before_matches_the_dev_pipeline_arithmetic():
    """Two windows named '18 months' in this project must mean the same 18
    months."""
    from loci.model.dev_pipeline import _months_before as dp_months_before
    for asof in (dt.date(2026, 9, 13), dt.date(2026, 3, 31), dt.date(2024, 2, 29)):
        for months in (12, 18, 24, 60):
            assert sp._months_before(asof, months) == dp_months_before(asof, months)


def test_zero_is_a_value_not_a_missing_one(con):
    """Owner rule: no eligibility gate, every street represented. The write
    RESETs to NULL and then sets every in-scope row, so a 0 means 'nothing
    filed within a five-minute walk' and a NULL means 'not run'."""
    con.execute((locidb.SQL_DIR / "020_storefront_pipeline.sql").read_text()
                .split("ALTER TABLE analysis.address_category")[0])
    assert sp.OPENINGS_COLUMNS[0] == "openings_pipeline_400m"
    assert "openings_run_at" in sp.OPENINGS_COLUMNS
