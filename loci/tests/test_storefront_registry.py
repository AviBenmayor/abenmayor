"""The storefront-vacancy layer (sql/012_storefront_registry.sql,
sources/cities/nyc/storefront_registry.py, model/storefronts.py).

Five things under test, mirroring tests/test_dev_pipeline.py:

(a) THE NON-DEDUP RULE. This source has NO storefront identifier and `unit` is
    blank on 87% of rows, so four identical rows at one address are four
    ground floors, not one filed four times. Collapsing them would delete
    three real storefronts and manufacture a gap where the operator can
    actually sign a lease -- the "dedup fusing distinct storefronts" bug
    CLAUDE.md names. The ingest must be LOSSLESS at filing grain, and
    (storefront_id, filing_due_date) must still be a key.

(b) THE FILING CALENDAR, derived from the data and not hard-coded. Five of the
    eleven filings are VACANT-ONLY; pooled with the full filings they read as a
    100% vacancy rate. `universe`, `observed_1231`, `observed_0630` and
    `reporting_year` must come out right for both filing shapes, and the
    Y/YES/N/NO vocabulary must parse to BOOLEAN with NULL preserved as NULL --
    never as FALSE.

(c) FAIL LOUD. A missing required column raises; a truncated download raises;
    a transform selecting zero rows raises; a snapshot with no storefronts
    raises. A vacancy layer that silently ingested nothing reads downstream as
    "there is no empty ground floor anywhere in Manhattan" -- the most
    confident possible way to be wrong.

(d) NON-FILTERING, pinned the way tests/test_dev_pipeline.py pins the pipeline
    annotation: STOREFRONT_COLUMNS is disjoint from the screen's own columns,
    from D62's PIPELINE_COLUMNS and from D63's age_fit columns, and a real
    write leaves gap_score / lead_category / n_missing / eligible byte-
    identical.

(e) THE CATCHMENT MATHS on a synthetic line graph, where every network distance
    is known by construction: counts are over STOREFRONTS (two at the same node
    both count), vacant is a strict SUBSET of all, the nearest vacant is the
    nearest VACANT one and not merely the nearest, and a row with no coordinate
    is excluded rather than silently counted at (0, 0).
"""
from __future__ import annotations

import datetime as dt
import re
import pathlib

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from loci import db as locidb
from loci.model.address_gaps import ADDRESS_COLUMNS
from loci.model.dev_pipeline import PIPELINE_COLUMNS
from loci.model.storefronts import (
    ADDRESS_SCREEN_COLUMNS,
    AGE_FIT_COLUMNS,
    STOREFRONT_COLUMNS,
    load_storefronts,
    node_storefront_matrix,
    weight_matrix,
    write_storefronts,
)
from loci.sources.cities.nyc.storefront_registry import (
    BBOX,
    BORO_NAME,
    CSV_HEADERS,
    DATASET,
    LEASE_MAX,
    LEASE_MIN,
    REQUIRED_FIELDS,
    _boro_case,
    assert_fields,
    latest_full_observation,
    staging_sql,
    write_storefronts as write_storefront_rows,
)

ASOF = dt.date(2026, 9, 10)
SNAPSHOT = dt.date(2024, 12, 31)


# --------------------------------------------------------------- fixtures

def _line_graph(n=13):
    """n nodes on a W-E line ~100 m apart at NYC latitude -- the same fixture
    shape as tests/test_address_gaps.py, test_conveniences.py and
    test_dev_pipeline.py, so storefront distances are read on the same ruler as
    the gap screen's nearest_m."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    dx = 100 / 84400.0
    for i in range(n):
        G.add_node(i, x=-73.98 + i * dx, y=40.75)
    for i in range(n - 1):
        G.add_edge(i, i + 1, length=100.0)
        G.add_edge(i + 1, i, length=100.0)
    return G


def _csv(tmp_path: pathlib.Path, rows: list[dict], name="sf.csv") -> pathlib.Path:
    """Write a CSV with the EXPORT's own header names, so the test exercises
    staging_sql's real column contract rather than a convenient renaming."""
    frame = pd.DataFrame([{CSV_HEADERS[k]: v for k, v in r.items()} for r in rows])
    for col in CSV_HEADERS.values():
        if col not in frame.columns:
            frame[col] = None
    path = tmp_path / name
    frame[list(CSV_HEADERS.values())].to_csv(path, index=False)
    return path


def _row(**kw) -> dict:
    base = {
        "filing_due": "06/03/2025", "reporting_period": "2024",
        "bbl": "1013470012", "address": "325 EAST 54 STREET", "borough": "MANHATTAN",
        "zip": "10022", "sold_date": None, "vacant_1231": "NO",
        "construction": None, "vacant_0630": None,
        "pba": "RETAIL", "lease_expiry": None,
        "street_number": "325", "street_name": "EAST 54 STREET", "unit": None,
        "latitude": 40.757104, "longitude": -73.9654603,
        "census_tract": "009800", "bin": "1084045", "nta": "MN0602",
    }
    base.update(kw)
    return base


def _stage(con, path, boroughs=("MN", "BK")) -> pd.DataFrame:
    return con.execute(staging_sql(path, boroughs, None, "2026-09-06", ASOF)).fetchdf()


# ------------------------------------------- (a) the NON-dedup rule


def _apply_storefront_year(con):
    """Create analysis.storefront_year from sql/045, draft or applied.

    The migration is staged as `045_scope_and_vocabulary.sql.draft` during
    Phase A -- `db.init_schema` applies every *.sql on disk in every session,
    so a migration keeps the .draft suffix until it is deliberately landed.
    The view is still testable: read the statement out and execute it.
    """
    import pathlib as _pl

    sql_dir = _pl.Path(locidb.SQL_DIR)
    src = sql_dir / "045_scope_and_vocabulary.sql"
    if not src.exists():
        src = sql_dir / "045_scope_and_vocabulary.sql.draft"
    # strip `--` comments first: sql/045's column comments contain semicolons.
    text = re.sub(r"--[^\n]*", "", src.read_text())
    stmt = re.search(r"(CREATE OR REPLACE VIEW analysis\.storefront_year.*?;)",
                     text, re.S)
    assert stmt, "analysis.storefront_year DDL not found in sql/045"
    con.execute(stmt.group(1))

def test_identical_rows_are_kept_because_they_are_distinct_storefronts(tmp_path):
    """350 EAST 54 STREET unit COM1 really files four rows in every filing --
    two FOOD SERVICES and two OTHER -- because the premises holds four
    storefronts and DOF's form has no field to tell them apart. Fusing them
    would turn three occupied ground floors into nothing at all."""
    con = locidb.connect(":memory:")
    rows = [_row(address="350 EAST 54 STREET", unit="COM1", bbl="1013461201",
                 pba=p) for p in ("FOOD SERVICES", "OTHER", "FOOD SERVICES", "OTHER")]
    out = _stage(con, _csv(tmp_path, rows))

    assert len(out) == 4, "the ingest must be lossless at filing grain"
    assert out["premises_id"].nunique() == 1, "premises_id is the STABLE identity"
    assert out["storefront_id"].nunique() == 4, \
        "(storefront_id, filing_due_date) must still be a key"
    assert set(out["storefront_id"]) == {"1013461201|COM1#1", "1013461201|COM1#2",
                                         "1013461201|COM1#3", "1013461201|COM1#4"}


def test_storefront_id_is_deterministic_across_reingests(tmp_path):
    """`seq` is ordered by (pba, lease_expiry, address, source row), so the same
    download twice produces the same ids and the borough DELETE-then-INSERT is
    genuinely idempotent rather than merely re-inserting."""
    con = locidb.connect(":memory:")
    rows = [_row(pba=p, unit="A") for p in ("RETAIL", "FOOD SERVICES", "OTHER")]
    a = _stage(con, _csv(tmp_path, rows, "a.csv"))
    b = _stage(con, _csv(tmp_path, rows, "b.csv"))
    key = lambda d: sorted(zip(d["storefront_id"], d["primary_business_activity"]))
    assert key(a) == key(b)
    # ordered by primary_business_activity, so FOOD SERVICES takes #1
    assert a.sort_values("storefront_id").iloc[0]["primary_business_activity"] == "FOOD SERVICES"


def test_reingest_replaces_the_borough_and_does_not_double_it(tmp_path):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    path = _csv(tmp_path, [_row(), _row(pba="OTHER")])
    n1 = write_storefront_rows(con, path, ("MN", "BK"), "2026-09-06", ASOF, pluto_csv=None)
    n2 = write_storefront_rows(con, path, ("MN", "BK"), "2026-09-06", ASOF, pluto_csv=None)
    assert n1 == n2 == 2, "a second ingest must replace, never double"


def test_a_borough_scoped_reingest_leaves_other_boroughs_alone(tmp_path):
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    both = _csv(tmp_path, [_row(), _row(borough="BROOKLYN", bbl="3000010001",
                                        address="1 BK ST", latitude=40.68,
                                        longitude=-73.95)], "both.csv")
    write_storefront_rows(con, both, ("MN", "BK"), "v", ASOF, pluto_csv=None)
    only_mn = _csv(tmp_path, [_row()], "mn.csv")
    write_storefront_rows(con, only_mn, ("MN",), "v", ASOF, pluto_csv=None)
    boros = {r[0] for r in con.execute(
        "SELECT DISTINCT borough FROM analysis.storefront").fetchall()}
    assert boros == {"MN", "BK"}, "an MN-only re-run must not delete Brooklyn"


# ------------------------------------ (b) the filing calendar + vocabularies

def test_full_and_vacant_only_filings_are_told_apart_from_the_data(tmp_path):
    """Five of the eleven real filings contain ONLY vacant storefronts. Pooled
    with the full filings they read as a 100% vacancy rate, so `universe` is
    load-bearing -- and it is DERIVED (a filing with no reported-not-vacant row
    is vacant_only), so a 2027 filing classifies itself."""
    con = locidb.connect(":memory:")
    rows = [
        # the annual full-universe filing: mixed YES/NO
        _row(filing_due="06/03/2025", reporting_period="2024", vacant_1231="NO"),
        _row(filing_due="06/03/2025", reporting_period="2024", vacant_1231="YES", unit="B"),
        # the February supplement: vacant only
        _row(filing_due="02/15/2026", reporting_period="2025", vacant_1231="YES"),
        # the August supplement: 6/30 only, vacant only, NO 12/31 field at all
        _row(filing_due="08/15/2025", reporting_period="2025",
             vacant_1231=None, vacant_0630="YES"),
    ]
    out = _stage(con, _csv(tmp_path, rows)).set_index("filing_due_date")

    d = lambda y, m, dd: pd.Timestamp(y, m, dd)   # DuckDB DATE arrives as Timestamp
    assert out.loc[d(2025, 6, 3), "universe"].tolist() == ["full", "full"]
    assert out.loc[d(2026, 2, 15), "universe"] == "vacant_only"
    assert out.loc[d(2025, 8, 15), "universe"] == "vacant_only"

    # observation dates, derived from the filing due date, not the text label
    assert out.loc[d(2025, 6, 3), "observed_1231"].tolist() == [d(2024, 12, 31)] * 2
    assert out.loc[d(2026, 2, 15), "observed_1231"] == d(2025, 12, 31)
    assert pd.isna(out.loc[d(2025, 8, 15), "observed_1231"]), \
        "a filing that never asks the 12/31 question observes no 12/31"
    assert out.loc[d(2025, 8, 15), "observed_0630"] == d(2025, 6, 30)

    # reporting_year matches DOF's own label in every shape
    assert out.loc[d(2025, 6, 3), "reporting_year"].tolist() == [2024, 2024]
    assert out.loc[d(2026, 2, 15), "reporting_year"] == 2025
    assert out.loc[d(2025, 8, 15), "reporting_year"] == 2025


def test_two_year_label_filing_observes_both_dates(tmp_path):
    """'2019 and 2020', due 2020-08-15, reports vacancy on 12/31/2019 AND on
    6/30/2020. The label is text; the dates come from the due date."""
    con = locidb.connect(":memory:")
    out = _stage(con, _csv(tmp_path, [
        _row(filing_due="08/15/2020", reporting_period="2019 and 2020",
             vacant_1231="NO", vacant_0630="YES")])).iloc[0]
    assert out["observed_1231"] == pd.Timestamp(2019, 12, 31)
    assert out["observed_0630"] == pd.Timestamp(2020, 6, 30)
    assert out["reporting_year"] == 2019
    assert out["reporting_period"] == "2019 and 2020"


def test_vacancy_vocabulary_parses_and_keeps_null_as_null(tmp_path):
    """{YES, Y} -> TRUE, {NO, N} -> FALSE, anything else -> NULL. NULL must
    NEVER become FALSE: on a vacant-only filing a NULL 12/31 flag means 'this
    filing did not ask', not 'not vacant'."""
    con = locidb.connect(":memory:")
    rows = [_row(vacant_1231=v, unit=f"U{i}", construction=c)
            for i, (v, c) in enumerate([("YES", "Y"), ("Y", "YES"), ("NO", "N"),
                                        (None, "NO"), ("", None)])]
    out = _stage(con, _csv(tmp_path, rows)).sort_values("unit")
    v = [None if pd.isna(x) else bool(x) for x in out["vacant_1231"]]
    c = [None if pd.isna(x) else bool(x) for x in out["construction_reported"]]
    assert v == [True, True, False, None, None]
    assert c == [True, True, False, False, None]


def test_lease_expiry_out_of_range_is_dropped_never_clamped(tmp_path):
    """The file contains a literal 1969-01-01 and a 2099-12-31. Clamping a typo
    to today would INVENT an expiry, and lease_expired is a decision input."""
    con = locidb.connect(":memory:")
    rows = [_row(lease_expiry=d, unit=f"U{i}") for i, d in enumerate(
        ["01/01/1969", "12/31/2099", "06/30/2025", None])]
    out = _stage(con, _csv(tmp_path, rows)).sort_values("unit")
    got = [None if pd.isna(x) else x for x in out["lease_expiry"]]
    # 1969 is impossible and goes. 2099 STAYS: a 99-year ground lease is a real
    # instrument in New York, and the guard only catches what cannot be a date,
    # never what merely looks unusual. Either way a far-future expiry reads as
    # "not expired", so nothing downstream turns on it.
    assert got == [None, pd.Timestamp(2099, 12, 31), pd.Timestamp(2025, 6, 30), None]
    assert LEASE_MIN == dt.date(1990, 1, 1) and LEASE_MAX == dt.date(2100, 1, 1)


def test_poison_coordinate_is_nulled_and_then_carried_from_another_filing(tmp_path):
    """4,780 real MN+BK rows carry latitude AND longitude of literal 0 -- one
    point in the Gulf of Guinea, 8,600 km from Brooklyn. It must never become a
    geometry; the premises' own coordinate from another filing rescues it."""
    con = locidb.connect(":memory:")
    rows = [
        _row(filing_due="08/15/2020", reporting_period="2019 and 2020",
             unit="COMM1", latitude=0, longitude=0),
        _row(filing_due="08/15/2022", reporting_period="2021 and 2022",
             unit="COMM1", latitude=40.756641, longitude=-73.965522),
        # outside the five-borough bbox: also nulled, and nothing to carry from
        _row(filing_due="06/03/2025", unit="ZZZ", latitude=25.7, longitude=-80.2),
    ]
    out = _stage(con, _csv(tmp_path, rows)).set_index(["unit", "filing_due_date"])
    assert out.loc[("COMM1", pd.Timestamp(2020, 8, 15)), "geom_source"] == "premises_carry"
    assert out.loc[("COMM1", pd.Timestamp(2022, 8, 15)), "geom_source"] == "filing"
    assert pd.isna(out.loc[("ZZZ", pd.Timestamp(2025, 6, 3)), "geom_source"])
    assert pd.isna(out.loc[("ZZZ", pd.Timestamp(2025, 6, 3)), "geom"])
    assert BBOX == (40.4, 41.0, -74.3, -73.6)


def test_boroughs_are_filtered_and_recoded(tmp_path):
    con = locidb.connect(":memory:")
    rows = [_row(), _row(borough="QUEENS", bbl="4000010001", latitude=40.72,
                         longitude=-73.85)]
    out = _stage(con, _csv(tmp_path, rows), boroughs=("MN", "BK"))
    assert list(out["borough"]) == ["MN"], "Queens must not survive an MN+BK run"
    assert BORO_NAME["STATEN ISLAND"] == "SI"
    assert "CASE borough_name" in _boro_case()


# --------------------------------------------------------- (c) fail loud

def test_missing_required_field_raises_rather_than_nulling_a_column():
    meta = {"columns": [{"fieldName": f} for f in REQUIRED_FIELDS
                        if f != "vacant_on_12_31"],
            "rowsUpdatedAt": 1775745106}
    with pytest.raises(RuntimeError, match="no longer exposes"):
        assert_fields(meta)


def test_assert_fields_returns_the_vintage_as_an_iso_date():
    meta = {"columns": [{"fieldName": f} for f in REQUIRED_FIELDS],
            "rowsUpdatedAt": 1775745106}
    vintage = assert_fields(meta)
    assert vintage.count("-") == 2 and vintage.startswith("20")
    assert DATASET == "92iy-9c3n"


def test_empty_snapshot_raises_rather_than_writing_zeros():
    """Zeros on every address would read as 'there is no empty ground floor
    anywhere' -- a confident false negative, not a missing value."""
    from loci.model.storefronts import compute_storefronts

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    with pytest.raises(RuntimeError, match="no rows for"):
        compute_storefronts(con, ["MN"], SNAPSHOT)


def test_latest_full_observation_ignores_the_vacant_only_supplements(tmp_path):
    """The 2026-02-15 supplement is FRESHER and must still lose: it has no
    denominator, so counting it gives a numerator with nothing to divide by
    (sql/012 caveat 4)."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    write_storefront_rows(con, _csv(tmp_path, [
        _row(filing_due="06/03/2025", vacant_1231="NO"),
        _row(filing_due="06/03/2025", vacant_1231="YES", unit="B"),
        _row(filing_due="02/15/2026", reporting_period="2025", vacant_1231="YES"),
    ]), ("MN", "BK"), "v", ASOF, pluto_csv=None)
    assert latest_full_observation(con, ["MN", "BK"]) == SNAPSHOT


# ------------------------------------------------------ (d) non-filtering

def test_storefront_columns_are_disjoint_from_every_other_writer():
    """The D57/D58/D62 guarantee at analysis.address grain: model/storefronts.py
    may never name a column the gap screen, the pipeline annotation or the D63
    age-fit ranking owns, so a plain re-run cannot move gap_score,
    lead_category, n_missing or eligible -- nor clobber the pipeline's numbers.
    ADDRESS_SCREEN_COLUMNS is pinned against the writer's own list in
    model/address_gaps.py so the two cannot drift apart silently."""
    assert ADDRESS_SCREEN_COLUMNS == ADDRESS_COLUMNS
    assert not (set(STOREFRONT_COLUMNS) & set(ADDRESS_SCREEN_COLUMNS))
    assert not (set(STOREFRONT_COLUMNS) & set(PIPELINE_COLUMNS))
    assert not (set(STOREFRONT_COLUMNS) & set(AGE_FIT_COLUMNS))
    assert AGE_FIT_COLUMNS == ["age_fit_lead", "age_fit_lead_moe", "gap_score_fit"]
    assert len(set(STOREFRONT_COLUMNS)) == len(STOREFRONT_COLUMNS) == 7


def test_write_storefronts_is_update_only_and_leaves_the_screen_byte_identical():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("""
        INSERT INTO analysis.address
          (address_id, bbl, lon, lat, units, units_capped, nta_code, neighborhood,
           borough, h3_index, present_count, eligible, gap_score, lead_category,
           lead_excess_m, n_missing, cluster_id, reach_source, reach_hash,
           graph_version, supply_set, supply_hash, run_at)
        VALUES ('A1','1','-73.98',40.75,10,10,'MN01','X','MN','h',13,TRUE,2.5,'laundry',
                300,3,'c','tiers','abc','g','principled','h1', now()),
               ('A2','2','-73.97',40.75,10,10,'MN01','X','MN','h',13,TRUE,1.1,'cafe_bakery',
                20,1,NULL,'tiers','abc','g','principled','h1', now())
    """)
    before = con.execute("SELECT address_id, gap_score, lead_category, n_missing, eligible "
                         "FROM analysis.address ORDER BY address_id").fetchall()

    df = pd.DataFrame([{
        "address_id": "A1", "borough": "MN",
        "vacant_storefronts_400m": 3, "storefronts_400m": 41,
        "nearest_vacant_storefront_m": 118.0,
        "nearest_vacant_storefront_id": "1013470012|#1",
        "nearest_vacant_storefront_business": "FOOD SERVICES",
        "nearest_vacant_lease_expired": True, "storefront_asof": SNAPSHOT,
    }])
    assert write_storefronts(con, df, ["MN"]) == 1

    after = con.execute("SELECT address_id, gap_score, lead_category, n_missing, eligible "
                        "FROM analysis.address ORDER BY address_id").fetchall()
    assert after == before, "the storefront annotation moved a screen column"
    assert con.execute("SELECT count(*) FROM analysis.address").fetchone()[0] == 2, \
        "UPDATE-only: no row may be inserted or deleted"
    assert con.execute("SELECT vacant_storefronts_400m FROM analysis.address "
                       "WHERE address_id='A1'").fetchone()[0] == 3
    assert con.execute("SELECT vacant_storefronts_400m FROM analysis.address "
                       "WHERE address_id='A2'").fetchone()[0] is None

    # the RESET pass: an address whose vacant storefront got leased must go back
    # to NULL, not keep last run's number
    assert write_storefronts(con, df.iloc[0:0], ["MN"]) == 0
    assert con.execute("SELECT vacant_storefronts_400m FROM analysis.address "
                       "WHERE address_id='A1'").fetchone()[0] is None


def test_fresh_schema_carries_all_seven_columns_and_the_view_exposes_them():
    """002_schema.sql's ALTERs and the generated address_gaps view must agree,
    or a fresh test database and the live database diverge -- the D61/D62 bug
    class."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='analysis' AND table_name='address'").fetchall()}
    assert set(STOREFRONT_COLUMNS) <= cols
    view = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='analysis' AND table_name='address_gaps'").fetchall()}
    assert set(STOREFRONT_COLUMNS) <= view, \
        "the address_gaps view must expose the annotation (D62 precedent)"
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='analysis'").fetchall()}
    assert "storefront" in tables and "storefront_latest" in tables


# ------------------------------------------------------ (e) catchment maths

def _shops(specs):
    """specs: [(id, node_index, vacant, pba, lease)] on the 100 m line graph."""
    dx = 100 / 84400.0
    return pd.DataFrame([{
        "storefront_id": sid, "premises_id": sid.split("#")[0], "borough": "MN",
        "address": sid, "unit": None, "universe": "full", "reporting_year": 2024,
        "observed_1231": SNAPSHOT, "vacant": vac, "construction_reported": False,
        "primary_business_activity": pba, "lease_expiry": lease,
        "lon": -73.98 + i * dx, "lat": 40.75,
    } for sid, i, vac, pba, lease in specs])


def test_counts_are_over_storefronts_and_vacant_is_a_subset_of_all():
    """Two storefronts at the SAME node both count -- the accumulator sums over
    storefronts, not over nodes -- and `vacant` is nested inside `all`, so the
    two must never be added."""
    G = _line_graph()
    shops = _shops([("P1#1", 5, True, "RETAIL", None),
                    ("P1#2", 5, True, "OTHER", None),      # same node, same premises
                    ("P2#1", 6, False, "FOOD SERVICES", None),
                    ("P3#1", 11, True, "RETAIL", None)])   # 600 m from node 5
    W, labels = weight_matrix(shops)
    assert labels == ["vacant_storefronts", "storefronts"]
    idx, acc, (near_d, near_p) = node_storefront_matrix(G, shops, W, radius_m=400.0,
                                                        min_component=0)
    i5 = idx[5]
    assert acc[1][i5] == 3, "nodes 5,6 hold 3 storefronts within 400 m of node 5"
    assert acc[0][i5] == 2, "two of them are vacant"
    assert acc[0][i5] <= acc[1][i5], "vacant must be a SUBSET of all, never added to it"
    # node 0 is 500 m from the nearest storefront (node 5): outside the radius
    assert acc[1][idx[0]] == 0, "nothing is within 400 m of node 0"
    assert acc[1][idx[11]] == 1, "only the storefront at node 11 is within 400 m of it"


def test_nearest_vacant_is_the_nearest_VACANT_not_the_nearest():
    """Node 4 has an OCCUPIED storefront 100 m away and a VACANT one 300 m
    away. The measure must report 300 m, not 100."""
    G = _line_graph()
    shops = _shops([("OCC#1", 5, False, "RETAIL", None),
                    ("VAC#1", 7, True, "FOOD SERVICES", dt.date(2023, 6, 30))])
    W, _ = weight_matrix(shops)
    idx, _acc, (near_d, near_p) = node_storefront_matrix(G, shops, W, radius_m=400.0,
                                                         min_component=0)
    i4 = idx[4]
    assert near_d[i4] == pytest.approx(300.0)
    assert shops.iloc[near_p[i4]]["storefront_id"] == "VAC#1"
    assert shops.iloc[near_p[i4]]["primary_business_activity"] == "FOOD SERVICES"


def test_a_snapshot_with_no_vacancy_leaves_nearest_censored():
    G = _line_graph()
    shops = _shops([("OCC#1", 5, False, "RETAIL", None)])
    W, _ = weight_matrix(shops)
    idx, acc, (near_d, near_p) = node_storefront_matrix(G, shops, W, radius_m=400.0,
                                                        min_component=0)
    assert (near_p == -1).all(), "no vacant storefront means no nearest vacant"
    assert acc[0].sum() == 0 and acc[1].sum() > 0, \
        "the denominator is still populated -- that is what tells 'none vacant' " \
        "apart from 'nobody filed'"


def test_rows_without_a_coordinate_are_excluded_not_counted_at_zero_zero():
    G = _line_graph()
    shops = _shops([("A#1", 5, True, "RETAIL", None), ("B#1", 6, True, "OTHER", None)])
    shops.loc[1, ["lon", "lat"]] = [np.nan, np.nan]
    W, _ = weight_matrix(shops)
    idx, acc, _near = node_storefront_matrix(G, shops, W, radius_m=400.0, min_component=0)
    assert acc[1].max() == 1, "the coordinate-less storefront must not be counted anywhere"


def test_load_storefronts_takes_one_observation_date_only(tmp_path):
    """A premises that has filed in seven years must contribute EXACTLY ONCE to
    a catchment count. The snapshot is one observation date, which is what makes
    that true by construction."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    write_storefront_rows(con, _csv(tmp_path, [
        _row(filing_due="08/15/2021", reporting_period="2020 and 2021", vacant_1231="NO"),
        _row(filing_due="08/15/2023", reporting_period="2022 and 2023", vacant_1231="YES"),
        _row(filing_due="06/03/2025", reporting_period="2024", vacant_1231="YES"),
    ]), ("MN", "BK"), "v", ASOF, pluto_csv=None)
    snap = load_storefronts(con, ["MN", "BK"], SNAPSHOT)
    assert len(snap) == 1 and bool(snap.iloc[0]["vacant"]) is True
    assert con.execute("SELECT count(*) FROM analysis.storefront").fetchone()[0] == 3, \
        "history is kept in the table; only the SNAPSHOT is one row"


def test_storefront_latest_view_counts_consecutive_vacant_years(tmp_path):
    """`consecutive_vacant_years` is a PREMISES question, not a storefront_id
    one -- storefront_id renumbers between filings. The run stops at the first
    observed year that is not vacant OR is not observed at all."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    write_storefront_rows(con, _csv(tmp_path, [
        _row(filing_due="08/15/2021", reporting_period="2020 and 2021", vacant_1231="NO"),
        _row(filing_due="08/15/2022", reporting_period="2021 and 2022", vacant_1231="YES"),
        _row(filing_due="08/15/2023", reporting_period="2022 and 2023", vacant_1231="YES"),
        _row(filing_due="06/03/2024", reporting_period="2023", vacant_1231="YES",
             lease_expiry="06/30/2022"),
        _row(filing_due="06/03/2025", reporting_period="2024", vacant_1231="YES"),
    ]), ("MN", "BK"), "v", ASOF, pluto_csv=None)
    row = con.execute("SELECT * FROM analysis.storefront_latest").fetchdf().iloc[0]
    assert row["latest_year"] == 2024
    assert bool(row["vacant_latest"]) is True
    assert row["consecutive_vacant_years"] == 4, "2021..2024 vacant; 2020 was not"
    assert row["lease_expiry"] == pd.Timestamp(2022, 6, 30)
    assert bool(row["lease_expired"]) is True


def test_the_supplement_and_the_annual_filing_are_never_pooled(tmp_path):
    """THE DOUBLE-COUNT BUG, caught on the live run. The 2025-06-03 annual
    filing and the 2025-02-15 vacant-only supplement BOTH observe 2024-12-31,
    and a premises that filed the supplement appears in the annual file too --
    as vacant, in both. Selecting on the observation date alone counted those
    storefronts twice and lifted the real MN+BK vacancy rate from 9.94% to
    13.79%. The full-universe filing wins because it carries a denominator."""
    from loci.model.storefronts import snapshot_filing

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    write_storefront_rows(con, _csv(tmp_path, [
        # the annual full filing: one occupied, one vacant
        _row(filing_due="06/03/2025", vacant_1231="NO"),
        _row(filing_due="06/03/2025", vacant_1231="YES", unit="B"),
        # the supplement, same 12/31, re-reporting that SAME vacant storefront
        _row(filing_due="02/15/2025", vacant_1231="YES", unit="B"),
    ]), ("MN", "BK"), "v", ASOF, pluto_csv=None)

    assert snapshot_filing(con, ["MN", "BK"], SNAPSHOT) == (dt.date(2025, 6, 3), "full")
    snap = load_storefronts(con, ["MN", "BK"], SNAPSHOT)
    assert len(snap) == 2, "the supplement must not be pooled into the annual filing"
    assert int(snap["vacant"].sum()) == 1, "one vacant storefront, reported twice, is one"

    # an observation date with ONLY a supplement still works -- and says so, so
    # `storefronts_400m` is not mistaken for a universe count
    write_storefront_rows(con, _csv(tmp_path, [
        _row(filing_due="02/15/2026", reporting_period="2025", vacant_1231="YES"),
    ], "supp.csv"), ("MN",), "v", ASOF, pluto_csv=None)
    assert snapshot_filing(con, ["MN"], dt.date(2025, 12, 31)) == (
        dt.date(2026, 2, 15), "vacant_only")


def test_storefront_year_never_pools_a_supplement_into_a_full_filing(tmp_path):
    """The BY-YEAR reading of the same never-pooled rule (audit finding 1).

    `test_the_supplement_and_the_annual_filing_are_never_pooled` above pins the
    rule for the ADDRESS MEASURES, which pick one filing by observation date.
    Nothing pinned it for the BY-YEAR question, and that is where it was being
    broken: group analysis.storefront by `reporting_year` and the 2025-06-03
    annual filing pools with the 2025-02-15 supplement that shares its
    reporting_year, leaving 5,534 duplicate groups / 6,354 excess rows citywide.

    Measured on the live file 2026-09-16, the cost is not 1.5% on a rate:

        2023   full 62,923 rows / 5,552 vacant   +  vacant_only 2,496 / 2,496
               pooled  8,048 / 65,419 = 12.30%      true 5,552 / 62,923 = 8.82%

    3.5 points of invented vacancy, and it looks entirely plausible.
    `analysis.storefront_year` (sql/045) picks ONE filing per (premises_id,
    reporting_year) -- the full one where it exists.
    """
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _apply_storefront_year(con)
    write_storefront_rows(con, _csv(tmp_path, [
        # 2024 annual full filing: two storefronts at one premises, one vacant
        _row(filing_due="06/03/2025", vacant_1231="NO"),
        _row(filing_due="06/03/2025", vacant_1231="YES", unit="B"),
        # the supplement observing the SAME 12/31/2024, re-reporting the vacancy
        _row(filing_due="02/15/2025", vacant_1231="YES", unit="B"),
    ]), ("MN", "BK"), "v", ASOF, pluto_csv=None)

    pooled = con.execute(
        "SELECT count(*) FROM analysis.storefront WHERE reporting_year = 2024"
    ).fetchone()[0]
    assert pooled == 3, "fixture should contain both filings"

    rows = {r[0]: r[1:] for r in con.execute("""
        SELECT premises_id, universe, vacant, n_storefronts
        FROM analysis.storefront_year WHERE reporting_year = 2024
    """).fetchall()}
    # premises_id is BBL || '|' || unit, so the two storefronts are two
    # PREMISES, not one. That is the identity rule sql/012 established and it
    # is what stops the dedup-fusing-distinct-storefronts bug; the pooling this
    # view fixes is across FILINGS, not across units.
    assert len(rows) == 2, f"one row per (premises_id, reporting_year): {rows}"
    vacant_premises = [p for p in rows if p.endswith("|B")]
    assert len(vacant_premises) == 1
    universe, vacant, n_storefronts = rows[vacant_premises[0]]

    assert universe == "full", "the full filing must win -- it carries a denominator"
    assert n_storefronts == 1, (
        "the vacant premises filed ONE storefront in the full filing; pooling "
        "the 02/15 supplement, which re-reports the same storefront, would "
        "count it twice and report two")
    assert vacant is True

    # the vacancy RATE is the number this protects: 1 vacant storefront over a
    # denominator of 2. Pooled, the denominator becomes 3 and the rate 0.33.
    rate = con.execute("""
        SELECT sum(CASE WHEN vacant THEN n_storefronts ELSE 0 END)::DOUBLE
               / sum(n_storefronts)
        FROM analysis.storefront_year WHERE reporting_year = 2024
    """).fetchone()[0]
    assert rate == 0.5, f"expected 1 vacant of 2 storefronts, got {rate}"


def test_storefront_year_labels_a_supplement_only_year_as_having_no_denominator(tmp_path):
    """2025 is supplement-only: a numerator with no denominator.

    The view cannot stop a consumer dividing by it; it can only label it. That
    label is `universe`, and this pins that it survives to the reader.
    """
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    _apply_storefront_year(con)
    write_storefront_rows(con, _csv(tmp_path, [
        _row(filing_due="02/15/2026", reporting_period="2025", vacant_1231="YES"),
    ]), ("MN", "BK"), "v", ASOF, pluto_csv=None)

    rows = con.execute(
        "SELECT universe, vacant FROM analysis.storefront_year "
        "WHERE reporting_year = 2025").fetchall()
    assert rows and all(u == "vacant_only" for u, _ in rows), (
        "a supplement-only year must be labelled vacant_only so a rate "
        "computed over it is visibly meaningless")
