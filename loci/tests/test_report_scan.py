"""THE REGRESSION FENCE around the `loci report` read path (2026-09-16).

WHAT THIS FILE IS FOR. A one-address report used to plan three passes over
`analysis.address_category` (4,980,615 rows) and an unbounded pass over
`analysis.forecast_outcome` (8,455,260), plus unscoped reads of
`poi_supply_status`, `storefront`, `storefront_pipeline`, `brand_location` and
`alcohol_licences`. None of that was visible in any test: every number the
memo printed was correct, the report just read the whole warehouse to get it.
A performance defect with no failing test comes back, so this file makes the
SHAPE OF THE PLAN a tested property.

TWO KINDS OF TEST HERE, and they are not interchangeable:

  1. PLAN tests -- `EXPLAIN` the statements the report path issues and assert
     that each one touching a big table carries a filter on it. These fail
     when someone drops a predicate, which is the regression that actually
     happened.
  2. EQUIVALENCE tests -- the rewritten one-pass query returns EXACTLY what
     the three-query version returned, and the scoped `forecast_latest`
     equivalent returns exactly what the view returns. These are what make
     the plan tests safe to satisfy: a fast wrong answer must fail.

The fixture is deliberately bigger than `tests/test_report_evidence.py`'s
(2,400 address_category rows over 160 addresses, 320 outcome rows) so that a
full scan and a filtered scan are DISTINGUISHABLE in an `EXPLAIN` plan and in
a row count. It is still a few hundred KB.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import tempfile

import pytest

import loci.db as locidb
from loci.categories import CATEGORIES
from loci.model import recommend as R
from loci.report import evidence as ev

CTR_LAT, CTR_LON = 40.7100, -73.9500
N_ADDR = 160


def _scan_rows(con, sql: str, params=None) -> dict:
    """{table: rows the scan operator actually EMITTED} for one statement.

    Measured, not guessed: DuckDB's JSON profiler, the same instrument the
    before/after numbers in the session scratchpad were taken with. An
    `EXPLAIN` text match was tried first and is not usable -- 1.5.x renders
    every projected column inside a box, so a table's NAME appears in the plan
    in places that are not scans of it.

    This is rows EMITTED by the scan (post pushed-down filter), which is
    exactly the quantity a lost predicate blows up.
    """
    out_path = pathlib.Path(tempfile.gettempdir()) / f"loci_scan_{os.getpid()}.json"
    out_path.unlink(missing_ok=True)
    con.execute("PRAGMA enable_profiling='json'")
    con.execute(f"PRAGMA profiling_output='{out_path}'")
    try:
        (con.execute(sql, params) if params else con.execute(sql)).fetchall()
    finally:
        con.execute("PRAGMA disable_profiling")
    doc = json.loads(out_path.read_text())
    found: dict[str, int] = {}

    def walk(node):
        name = (node.get("operator_name") or node.get("name") or "").upper()
        if "SCAN" in name:
            info = node.get("extra_info") or {}
            tbl = info.get("Table") or info.get("Text") or ""
            card = node.get("operator_cardinality")
            if card is None:
                card = node.get("cardinality")
            if tbl:
                key = str(tbl).strip().split(".")[-1]
                found[key] = found.get(key, 0) + int(card or 0)
        for c in (node.get("children") or []):
            walk(c)

    walk(doc)
    return found


# --------------------------------------------------------------- the fixture

def _big_db():
    """One address frame big enough that a scan and a seek differ."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)

    addr_rows, cat_rows, demo_rows = [], [], []
    for i in range(N_ADDR):
        aid = f"addr{i:04d}"
        # A tight cluster of 10 around the centre; the rest spread out to
        # 20 km so a bbox predicate has something to reject.
        if i < 10:
            lat, lon = CTR_LAT + i * 0.0002, CTR_LON + i * 0.0002
        else:
            lat, lon = CTR_LAT + 0.02 * (i % 9 + 1), CTR_LON + 0.02 * (i % 7 + 1)
        addr_rows.append((aid, f"30123{i:05d}", lon, lat, "BK", "Testville", "BK0601",
                          True, 12, 3, "tiers", "h", "g", dt.datetime(2026, 9, 11),
                          3000.0, 1000.0, 50.0, 10.0, 5.0, 2.0, 20.0, "2024-12-31",
                          "767b28674e30"))
        demo_rows.append((aid, f"30123{i:05d}", 2023, 90_000.0, 8_000.0, 0.3, 0.65))
        for c in CATEGORIES:
            cat_rows.append((aid, "BK", c,
                             0.1 if (c == "grocery" and i < 10) else 0.9,
                             1.5, 4.0, 400_000.0, 600_000.0, 900_000.0, 12_000.0,
                             "rev-0.1", 500_000.0, False, 1.2))

    con.executemany(
        "INSERT INTO analysis.address (address_id, bbl, lon, lat, borough, neighborhood, "
        "nta_code, eligible, present_count, n_missing, reach_source, reach_hash, "
        "graph_version, run_at, homes_400m, addressable_homes_400m_laundry, "
        "units_permitted_400m, units_active_400m, units_stalled_400m, "
        "vacant_storefronts_400m, storefronts_400m, storefront_asof, "
        "supply_ratio_supply_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        addr_rows)
    con.executemany(
        "INSERT INTO analysis.address_category (address_id, borough, category, "
        "supply_ratio_vs_base, supply_per_1k, supply_400m, revenue_p25, revenue_p50, "
        "revenue_p75, rent_ceiling, revenue_model_version, revenue_cap_p50, "
        "capacity_bound, ratio) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", cat_rows)
    con.executemany(
        "INSERT INTO analysis.address_demographics (address_id, bbl, acs_year, "
        "median_hh_income, median_hh_income_moe, age_18_34_share, renter_share) "
        "VALUES (?,?,?,?,?,?,?)", demo_rows)
    return con


def _seed_forecasts(con, n_addr: int = 40) -> None:
    """A forecast + outcome ledger with more than one vintage per address, so
    the `QUALIFY` picks have something to pick between."""
    fc, oc = [], []
    for i in range(n_addr):
        aid = f"addr{i:04d}"
        for cat in ("grocery", "laundry"):
            for k, month in enumerate(("2026-07", "2026-08")):
                version = f"0.1.1+aaaaaaa{k}"
                fc.append((month, 12, version, aid, cat, "lot", "BK",
                           "BK0601", "cell1", 0.1 + 0.01 * k, 0.2, "fitted",
                           "0123456789abcdef", dt.datetime(2026, 9, 1 + k)))
                for j, scored in enumerate(("2026-08", "2026-09")):
                    # The outcome ledger carries the forecast's NATURAL key
                    # (sql/028, reshaped 2026-09-16). `model_version` is
                    # load-bearing: drop it and a scored vintage fans out across
                    # every same-month re-issue.
                    oc.append((month, version, aid, cat, scored, 1 + j, j,
                               bool(j), dt.datetime(2026, 9, 10 + j)))
    con.executemany(
        "INSERT INTO analysis.forecast (issued_month, horizon_months, "
        "model_version, address_id, category, frame, borough, nta_code, surprise_cell, "
        "p_opening, expected_openings, support, features_hash, frozen_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", fc)
    con.executemany(
        "INSERT INTO analysis.forecast_outcome (issued_month, model_version, "
        "address_id, category, scored_month, "
        "horizon_elapsed, realized_openings, realized_flag, scored_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)", oc)


def _base_for(con, address_id: str):
    row = ev._address_row(con, address_id)
    bbox = ev._bbox_around(row["lat"], row["lon"], ev.GRADE_BBOX_HALF_WIDTH_M)
    where, params = R._area_predicate(bbox, None)
    base = ("FROM analysis.address a WHERE a.borough IN (?) AND " + where
            + " AND COALESCE(a.frame, 'lot') = 'lot'"
            + " AND COALESCE(a.eligible, FALSE)")
    return row, base, [row["borough"], *params]


# ------------------------------------------------------- 1. equivalence

def test_one_pass_category_frame_equals_the_two_query_version():
    """F2(b): the folded query must be the SAME NUMBERS, not merely fewer
    statements. This is the test that makes the plan test below safe."""
    con = _big_db()
    _, base, params = _base_for(con, "addr0000")
    one_cats, one_rev = R._category_frame(con, base, params)
    two_cats, two_rev = R._category_frame_two_pass(con, base, params)
    assert not one_cats.empty and not one_rev.empty
    assert one_cats.sort_index().equals(two_cats.sort_index())
    assert one_rev.sort_index().equals(two_rev.sort_index())
    # and the values are real, not all-NULL (a frame of NaNs would compare
    # equal to another frame of NaNs and prove nothing)
    assert one_cats.loc["grocery", "n_ratio_addresses"] > 0


def test_one_pass_frame_survives_a_warehouse_with_no_revenue_columns():
    """The D76 revenue block is OPTIONAL. Folding it into the supply query
    must not make a pre-revenue warehouse fail to produce a card."""
    con = _big_db()
    for col in ("revenue_p25", "revenue_p50", "revenue_p75", "rent_ceiling",
                "revenue_model_version", "revenue_cap_p50", "capacity_bound"):
        con.execute(f"ALTER TABLE analysis.address_category DROP COLUMN {col}")
    _, base, params = _base_for(con, "addr0000")
    cats, revenue = R._category_frame(con, base, params)
    assert not cats.empty
    assert revenue.empty                      # -> `_revenue_facts` returns None
    assert R._revenue_facts(revenue, "grocery") is None


def test_scoped_forecast_row_equals_the_forecast_latest_view():
    """F3: the address-scoped rewrite must agree with `forecast_latest`
    column for column, including the NULL-scored case."""
    con = _big_db()
    _seed_forecasts(con)
    cols = con.execute("DESCRIBE analysis.forecast_latest").fetchdf()["column_name"].tolist()
    compared = 0
    for aid in ("addr0000", "addr0005", "addr0039"):
        for cat in ("grocery", "laundry", "bar"):      # bar has no forecast at all
            view = con.execute(
                f"SELECT {', '.join(cols)} FROM analysis.forecast_latest "
                "WHERE address_id = ? AND category = ?", [aid, cat]).fetchone()
            view = dict(zip(cols, view)) if view else None
            scoped = ev._forecast_row(con, aid, cat)
            assert (view is None) == (scoped is None), (aid, cat)
            if view is None:
                continue
            compared += 1
            for k in cols:
                assert repr(view[k]) == repr(scoped[k]), (aid, cat, k)
    assert compared >= 6


# --------------------------------------------------------------- 2. plans

@pytest.mark.parametrize("table", ["address_category"])
def test_every_area_query_filters_address_category(table):
    """The area's per-category frame must carry the address predicate. The
    CITY-WIDE coverage frame is the one deliberate exception and is asserted
    separately below -- it is excluded here, not silently tolerated."""
    con = _big_db()
    _, base, params = _base_for(con, "addr0000")
    have = R._table_columns(con, "analysis.address_category")
    selected = list(R._SUPPLY_AGGREGATES) + list(R._REVENUE_AGGREGATES)
    cols = ", ".join(f"{expr} AS {name}" for name, expr in selected)
    sql = (f"SELECT c.category, {cols} FROM analysis.address_category c "
           f"WHERE c.address_id IN (SELECT a.address_id {base}) GROUP BY 1")
    assert R._REVENUE_COLUMNS <= have
    total, = con.execute("SELECT count(*) FROM analysis.address_category").fetchone()
    scanned = _scan_rows(con, sql, params)
    assert scanned.get(table, 0) < total / 2, (
        f"the area query emitted {scanned.get(table)} of {total} "
        f"address_category rows -- the address predicate is not reaching the scan")


def test_the_report_path_makes_exactly_one_unfiltered_address_category_pass():
    """F2, stated as a property: across the whole `assemble()` read path,
    exactly ONE statement may scan `analysis.address_category` without an
    address predicate -- `COVERAGE_FRAME_SQL`, which is city-wide BY DESIGN
    (`coverage_hole_rates`' docstring: an area-restricted rate would grade a
    category on whether the sampler happened to visit it). Two would be the
    regression this file exists to catch."""
    con = _big_db()
    _seed_forecasts(con)
    seen: list[str] = []
    real_execute = con.execute

    class Spy:
        def execute(self, sql, params=None):
            seen.append(sql)
            return real_execute(sql) if params is None else real_execute(sql, params)

        def __getattr__(self, name):
            return getattr(con, name)

    ev.assemble(Spy(), "addr0000")

    touching = [s for s in seen
                if "address_category" in s.lower() and "describe" not in s.lower()]
    assert touching, "the report path stopped reading address_category at all"
    unfiltered = [s for s in touching
                  if "address_id = ?" not in s and "address_id IN" not in s]
    assert len(unfiltered) == 1, (
        f"{len(unfiltered)} unfiltered address_category statements, expected 1 "
        f"(the deliberate city-wide coverage frame):\n" + "\n---\n".join(unfiltered))
    assert "coverage_validation" in unfiltered[0]


def test_the_report_path_never_scans_forecast_outcome_unfiltered():
    """F3. `analysis.forecast_outcome` is 8.5M rows in production; every read
    of it on the report path must carry the address restriction."""
    con = _big_db()
    _seed_forecasts(con)
    seen: list[str] = []
    real_execute = con.execute

    class Spy:
        def execute(self, sql, params=None):
            seen.append(sql)
            return real_execute(sql) if params is None else real_execute(sql, params)

        def __getattr__(self, name):
            return getattr(con, name)

    ev.assemble(Spy(), "addr0000")

    for sql in seen:
        if "forecast_outcome" not in sql.lower():
            continue
        assert "address_id = ?" in sql, sql
    # ...and the statement that does read it emits a small fraction of the
    # ledger, which is the property that actually matters at 8.5M rows.
    scoped = ev._FORECAST_SCOPED_SQL.format(on_clause=ev._forecast_outcome_join())
    total, = con.execute("SELECT count(*) FROM analysis.forecast_outcome").fetchone()
    scanned = _scan_rows(con, scoped, ["addr0000", "grocery", "addr0000", "grocery"])
    assert total > 100
    assert scanned.get("forecast_outcome", 0) < total / 4, (
        f"the scoped forecast query emitted {scanned.get('forecast_outcome')} of "
        f"{total} forecast_outcome rows -- the restriction is not reaching the scan")

    # The unscoped view, for contrast: this is what the report path used to do.
    cols = con.execute("DESCRIBE analysis.forecast_latest").fetchdf()["column_name"].tolist()
    via_view = _scan_rows(
        con, f"SELECT {', '.join(cols)} FROM analysis.forecast_latest "
             "WHERE address_id = ? AND category = ?", ["addr0000", "grocery"])
    assert via_view.get("forecast_outcome", 0) >= scanned.get("forecast_outcome", 0)


def test_supply_storefront_pipeline_chains_reads_are_all_bounded():
    """F4. Every five-borough table read on this path must carry BOTH the
    MN+BK screen and a spatial bound. `analysis.poi_supply_status` is a view
    and carries only the spatial bound (its base tables have no borough
    column), which is why it is checked separately."""
    con = _big_db()
    seen: list[str] = []
    real_execute = con.execute

    class Spy:
        def execute(self, sql, params=None):
            seen.append(sql)
            return real_execute(sql) if params is None else real_execute(sql, params)

        def __getattr__(self, name):
            return getattr(con, name)

    ev.assemble(Spy(), "addr0000")

    for table, needs_borough in (("analysis.storefront", True),
                                 ("analysis.storefront_pipeline", True),
                                 ("chains.brand_location", True),
                                 ("staging.alcohol_licences", True),
                                 ("analysis.poi_supply_status", False)):
        for sql in seen:
            if table not in sql:
                continue
            if _is_supply_hash_count(sql):
                continue          # the one deliberate city-wide read; see below
            assert "BETWEEN" in sql, f"{table} read with no spatial bound:\n{sql}"
            if needs_borough:
                assert ("'MN'" in sql or "'Manhattan'" in sql), \
                    f"{table} read with no borough screen:\n{sql}"


def _is_supply_hash_count(sql: str) -> bool:
    """`score.supply.supply_hash`'s per-category count.

    CITY-WIDE BY DEFINITION and the one read on this path that must stay that
    way: the hash is the project's identity for "which POIs did this run
    count" (model/supply_asof.py; the ba944e18c57b freeze). Scoping it to an
    address's catchment would silently change every supply hash ever written
    and break the reproduction the freeze rests on. It is excluded here by
    NAME, not by a loose predicate, so a second unscoped read cannot sneak
    through under the same exemption."""
    flat = " ".join(sql.split())
    return flat.startswith("SELECT category, count(*) FROM (SELECT s.category")


def test_supply_hash_read_is_the_only_city_wide_poi_supply_status_read():
    """The exemption above is itself a tested property: exactly one statement
    on the report path may read `analysis.poi_supply_status` unbounded."""
    con = _big_db()
    seen: list[str] = []
    real_execute = con.execute

    class Spy:
        def execute(self, sql, params=None):
            seen.append(sql)
            return real_execute(sql) if params is None else real_execute(sql, params)

        def __getattr__(self, name):
            return getattr(con, name)

    ev.assemble(Spy(), "addr0000")
    reads = [s for s in seen if "poi_supply_status" in s]
    unbounded = [s for s in reads if "BETWEEN" not in s]
    assert len(unbounded) == 1, "\n---\n".join(unbounded)
    assert _is_supply_hash_count(unbounded[0])


def test_bbox_sql_is_a_strict_superset_of_the_haversine_circle():
    """The SQL pre-filter decides which rows are READ; `haversine_m` decides
    which are COUNTED. If the box were ever tighter than the circle the report
    would print a supply gap that is not there -- the exact failure mode this
    project treats as unacceptable. `_bbox_around` divides by 111,320 m/deg
    while `haversine_m` works on R = 6,371,000 m, so the box is ~0.11% tight
    before `_BBOX_SUPERSET_PAD` widens it."""
    from loci.score.dedup import haversine_m

    for radius in (152.4, 500.0, 800.0):
        minlat, minlon, maxlat, maxlon = ev._bbox_around(
            CTR_LAT, CTR_LON, radius * ev._BBOX_SUPERSET_PAD)
        # walk the circle and demand every point on it is inside the box
        import math
        for deg in range(0, 360, 5):
            th = math.radians(deg)
            # a point at exactly `radius` metres, in degrees
            dlat = (radius * math.cos(th)) / 111_194.9
            dlon = ((radius * math.sin(th))
                    / (111_194.9 * math.cos(math.radians(CTR_LAT))))
            plat, plon = CTR_LAT + dlat, CTR_LON + dlon
            assert haversine_m(CTR_LAT, CTR_LON, plat, plon) <= radius * 1.001
            assert minlat <= plat <= maxlat, (radius, deg, "lat")
            assert minlon <= plon <= maxlon, (radius, deg, "lon")


# ------------------------------------------------------- 3. the caches

def test_run_cache_pays_for_the_city_wide_frame_once():
    """F2(a). The coverage frame is a per-category CONSTANT within a run; a
    sweep must scan `address_category` for it once, not once per address."""
    con = _big_db()
    con.executemany(
        "INSERT INTO analysis.coverage_validation (h3_index, category, income_decile, "
        "n_ground_truth, n_overture, n_osm, n_city_source, sampled_on, address_id, "
        "borough, n_local_canonical, ground_truth_types, radius_m) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(None, "grocery", 5, 2, 1, 1, 1, dt.date(2026, 9, 1), f"addr{i:04d}", "BK",
          0, json.dumps({"grocery_store": 2}), 400.0) for i in range(40)])

    seen: list[str] = []
    real_execute = con.execute

    class Spy:
        def execute(self, sql, params=None):
            seen.append(sql)
            return real_execute(sql) if params is None else real_execute(sql, params)

        def __getattr__(self, name):
            return getattr(con, name)

    spy = Spy()
    cache = R.RunCache()
    first = R.coverage_hole_rates(spy, cache=cache, live_hash="h1", baseline_hash="b1")
    n_after_first = sum(1 for s in seen if "coverage_validation" in s and "JOIN" in s)
    second = R.coverage_hole_rates(spy, cache=cache, live_hash="h1", baseline_hash="b1")
    n_after_second = sum(1 for s in seen if "coverage_validation" in s and "JOIN" in s)

    assert first == second
    assert n_after_first == 1
    assert n_after_second == 1, "the city-wide coverage frame was scanned twice"
    assert cache.hits == 1 and cache.misses == 1


def test_run_cache_invalidates_when_the_supply_hash_moves():
    """A cached city-wide number that outlives its inputs is worse than the
    scan it replaced. The supply hash is in the key, so a re-scored supply
    set re-measures."""
    con = _big_db()
    cache = R.RunCache()
    R.coverage_hole_rates(con, cache=cache, live_hash="h1", baseline_hash="b1")
    R.coverage_hole_rates(con, cache=cache, live_hash="h2", baseline_hash="b1")
    assert cache.misses == 2, "a new supply hash must not hit the cache"


def test_coverage_hole_rates_without_a_cache_is_unchanged():
    """`cache=None` -- every pre-existing caller -- must behave exactly as
    before this cache existed."""
    con = _big_db()
    a = R.coverage_hole_rates(con)
    b = R.coverage_hole_rates(con, cache=None)
    assert a == b
    assert set(a) == set(CATEGORIES)


def test_comps_cache_is_keyed_on_content_not_just_path(tmp_path, monkeypatch):
    """F5. Memoising on the path alone would keep serving the empty parse
    through the refresh that finally puts real listings on disk."""
    from loci.model import comps

    csv_path = tmp_path / "listings.csv"
    header = ("loci_category,borough,neighborhood,asking_price,gross_revenue,"
              "cash_flow_sde,cash_flow_before_rent,rent,sqft,self_reported\n")
    csv_path.write_text(header)
    monkeypatch.setattr(comps, "LISTINGS_CSV", csv_path)
    comps.clear_parse_cache()

    assert comps.load_listings() == []
    csv_path.write_text(header + "grocery,Brooklyn,Testville,100,500000,80000,,4000,900,true\n")
    rows = comps.load_listings()
    assert len(rows) == 1 and rows[0]["gross_revenue"] == 500000.0


def test_comps_cache_hands_back_an_independent_copy(tmp_path, monkeypatch):
    """A cached parse a caller can mutate is a cache that poisons the next
    card. The rows come back fresh."""
    from loci.model import comps

    csv_path = tmp_path / "listings.csv"
    csv_path.write_text(
        "loci_category,borough,neighborhood,asking_price,gross_revenue,"
        "cash_flow_sde,cash_flow_before_rent,rent,sqft,self_reported\n"
        "grocery,Brooklyn,Testville,100,500000,80000,,4000,900,true\n")
    monkeypatch.setattr(comps, "LISTINGS_CSV", csv_path)
    comps.clear_parse_cache()

    first = comps.load_listings()
    first[0]["gross_revenue"] = -1.0
    second = comps.load_listings()
    assert second[0]["gross_revenue"] == 500000.0

    doc = comps.load_benchmarks()
    doc["occupancy_cost_ratio"] = {}
    assert comps.load_benchmarks().get("occupancy_cost_ratio")


def test_comps_parsed_content_is_identical_cached_or_not(tmp_path, monkeypatch):
    """The cache must change WHEN the work happens, never WHAT it returns."""
    from loci.model import comps

    csv_path = tmp_path / "listings.csv"
    csv_path.write_text(
        "loci_category,borough,neighborhood,asking_price,gross_revenue,"
        "cash_flow_sde,cash_flow_before_rent,rent,sqft,self_reported\n"
        "grocery,Brooklyn,Testville,100,500000,80000,120000,4000,900,true\n"
        "laundry,Brooklyn,Testville,200,300000,60000,,3000,700,false\n")
    monkeypatch.setattr(comps, "LISTINGS_CSV", csv_path)

    comps.clear_parse_cache()
    cold = comps.load_listings()
    warm = comps.load_listings()
    comps.clear_parse_cache()
    again = comps.load_listings()
    assert cold == warm == again
    assert comps.comps_for("grocery", borough="Brooklyn") == \
           comps.comps_for("grocery", borough="Brooklyn",
                           listings=again, benchmarks=comps.load_benchmarks())
