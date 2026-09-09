"""_local_counts / recount_local (GTM-48 bug fix): the coverage-validation local
side must count CANONICAL POIs across ALL ingested sources, not un-deduped
staging.poi restricted to two hardcoded source ids (see sample.py docstring)."""
import datetime as dt

from loci import db as locidb
from loci.validation.google_places import GooglePlacesClient
from loci.validation import sample as smp
from loci.validation.sample import _local_counts, plan, recount_local, run

LAT, LON = 40.7000, -73.9000  # test point; ~0 m from itself


def _fixture():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("""INSERT INTO analysis.hex (h3_index, geom, centroid, land_fraction)
        VALUES ('h1', ST_Point(?, ?), ST_Point(?, ?), 1.0)""", [LON, LAT, LON, LAT])
    return con


def _add_poi(con, poi_id, source_id, category, canonical, lat=LAT, lon=LON):
    con.execute("""INSERT INTO staging.poi (poi_id, source_id, category, tier, geom)
        VALUES (?, ?, ?, 1, ST_Point(?, ?))""", [poi_id, source_id, category, lon, lat])
    con.execute("""INSERT INTO analysis.poi_dedup (poi_id, cluster_id, is_canonical, category)
        VALUES (?, ?, ?, ?)""", [poi_id, hash(poi_id) % 10_000, canonical, category])


def test_canonical_total_spans_all_sources_and_excludes_duplicates():
    con = _fixture()
    # two DIFFERENT businesses, canonical, from two different ingested sources
    _add_poi(con, "overture_places:1", "overture_places", "clinic", True)
    _add_poi(con, "foursquare_os_places:2", "foursquare_os_places", "clinic", True)
    # a THIRD poi that duplicates one of the above (same underlying business),
    # marked non-canonical by dedup -> must NOT be counted
    _add_poi(con, "osm_overpass:3", "osm_overpass", "clinic", False)
    # a fourth, canonical, but a DIFFERENT category -> must not leak in
    _add_poi(con, "overture_places:4", "overture_places", "grocery", True)

    n_ov, n_osm, n_city, n_canon = _local_counts(con, LAT, LON, "clinic")
    assert n_canon == 2                 # both canonical clinics, across both sources
    assert n_ov == 1                    # legacy per-source columns still per-source
    assert n_osm == 1                   # (the duplicate, un-deduped, still shows here)


def test_canonical_total_is_zero_when_nothing_canonical_nearby():
    con = _fixture()
    _add_poi(con, "overture_places:1", "overture_places", "clinic", False)
    _, _, _, n_canon = _local_counts(con, LAT, LON, "clinic")
    assert n_canon == 0


def test_recount_local_backfills_existing_rows_without_touching_ground_truth():
    con = _fixture()
    _add_poi(con, "overture_places:1", "overture_places", "clinic", True)
    _add_poi(con, "foursquare_os_places:2", "foursquare_os_places", "clinic", True)
    con.execute("""INSERT INTO analysis.coverage_validation
        (h3_index, category, income_decile, n_ground_truth, n_overture, n_osm, sampled_on)
        VALUES ('h1', 'clinic', 5, 7, 0, 0, ?)""", [dt.date.today()])

    n = recount_local(con)
    assert n == 1
    row = con.execute("""SELECT n_ground_truth, n_local_canonical FROM analysis.coverage_validation
        WHERE h3_index = 'h1' AND category = 'clinic'""").fetchone()
    assert row[0] == 7            # n_ground_truth (Google) untouched
    assert row[1] == 2            # backfilled from the canonical layer, both sources


class _FakeResp:
    def raise_for_status(self): pass
    def json(self): return {"places": []}


class _FakeSession:
    def post(self, *a, **k): return _FakeResp()


def test_plan_skips_categories_with_no_google_mapping():
    """clinic is a valid loci category (categories.yaml) but has no Google
    Places mapping (GTM-105 #7) -- plan() must skip it, not KeyError."""
    sample = [{"h3_index": "h1", "lat": LAT, "lon": LON, "income_decile": 5}]
    p = plan(sample, ["clinic"])
    assert p["calls"] == 0
    assert p["categories"] == 0
    assert p["skipped"] == ["clinic"]

    p2 = plan(sample, ["clinic", "hardware"])
    assert p2["calls"] == 1
    assert p2["categories"] == 1
    assert p2["skipped"] == ["clinic"]


def test_run_skips_categories_with_no_google_mapping(tmp_path):
    """run() must skip clinic gracefully rather than KeyError on
    GOOGLE_TYPES[category] (GTM-105 #7)."""
    con = _fixture()
    client = GooglePlacesClient(api_key="k", budget=5, ledger_path=tmp_path / "l.json",
                                 session=_FakeSession())
    sample = [{"h3_index": "h1", "lat": LAT, "lon": LON, "income_decile": 5}]

    n = run(con, client, sample, ["clinic", "hardware"], dry_run=False)
    assert n == 1   # only hardware written; clinic silently skipped
    rows = con.execute("SELECT category FROM analysis.coverage_validation").fetchall()
    assert [r[0] for r in rows] == ["hardware"]

    # a category no other loci category recognizes is still a hard error
    import pytest
    with pytest.raises(ValueError):
        run(con, client, sample, ["not_a_real_category"], dry_run=False)


# ---------------------------------------------------------------------------
# The ADDRESS frame (GTM-48 / CHECKPOINT D38, D58)
#
# The validator used to sample hex centroids stratified by income decile from
# analysis.hex_demographics. D38 made the address the unit and froze the hex
# tables, so the sampling frame is now gap ADDRESSES: rows of
# analysis.address_gaps in MN+BK (D48), stratified income decile (from
# analysis.address_demographics, address grain) × whether the address is
# missing that category. These tests run entirely on a synthetic fixture --
# no network, no Google call, no ledger spend.
# ---------------------------------------------------------------------------

_ADDR_COLS = ("address_id", "bbl", "lon", "lat", "units", "units_capped", "borough",
              "present_count", "eligible", "gap_score", "n_missing",
              "reach_source", "reach_hash", "graph_version", "run_at",
              "hardware_ratio", "grocery_ratio")


def _add_address(con, address_id, income, borough="BK", units=10.0, eligible=True,
                 hardware_ratio=0.5, grocery_ratio=0.5, lon=None, lat=None, acs_year=2023):
    """One residential lot in analysis.address_gaps + its tract demographics."""
    lon = LON if lon is None else lon
    lat = LAT if lat is None else lat
    con.execute(f"""INSERT INTO analysis.address_gaps ({", ".join(_ADDR_COLS)})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [address_id, address_id, lon, lat, units, min(units, 500.0), borough,
                 14, eligible, max(hardware_ratio, grocery_ratio), 0,
                 "tiers", "h", "g", dt.datetime(2026, 9, 9),
                 hardware_ratio, grocery_ratio])
    con.execute("""INSERT INTO analysis.address_demographics
        (address_id, bbl, tract_geoid, acs_year, median_hh_income)
        VALUES (?, ?, ?, ?, ?)""", [address_id, address_id, "36047" + address_id[-6:].zfill(6),
                                     acs_year, income])


def _address_fixture(n=40, borough="BK"):
    """n addresses at distinct incomes, alternating missing/present on hardware.

    Lon/lat are nudged per address so the sampled point is identifiably the
    LOT's own coordinate, not a shared centroid.
    """
    con = _fixture()
    for i in range(n):
        _add_address(con, f"a{i:03d}", income=20_000 + 1_000 * i, borough=borough,
                     units=10.0 + i,
                     hardware_ratio=1.5 if i % 2 else 0.5,
                     grocery_ratio=1.5 if i % 4 == 0 else 0.5,
                     lon=LON + i * 1e-4, lat=LAT + i * 1e-4)
    return con


def test_draw_sample_draws_addresses_not_hex_centroids():
    con = _address_fixture()
    s = smp.draw_sample(con, categories=["hardware"], per_stratum=1)
    assert s, "the address frame produced no sample"
    assert all("h3_index" not in r for r in s)
    assert all(r["address_id"].startswith("a") for r in s)
    # the Nearby Search centre is the LOT's own point, straight off address_gaps
    lots = dict(con.execute("SELECT address_id, lon FROM analysis.address_gaps").fetchall())
    assert all(r["lon"] == lots[r["address_id"]] for r in s)


def test_income_decile_comes_from_address_demographics():
    """Deciles are NTILE(10) over address_demographics.median_hh_income across
    the whole in-scope frame -- the address-grain, direct-tract-lookup measure
    (D56), not hex_demographics."""
    con = _address_fixture(n=40)
    s = smp.draw_sample(con, categories=["hardware"], per_stratum=99)   # take everything
    by_addr = {r["address_id"]: r["income_decile"] for r in s}
    assert sorted(set(by_addr.values())) == list(range(1, 11))
    assert by_addr["a000"] == 1     # lowest income
    assert by_addr["a039"] == 10    # highest income


def test_strata_split_missing_from_present_per_category():
    """The control side matters: a sample taken only where loci says the
    category is missing cannot separate coverage bias from a real hole (D29)."""
    con = _address_fixture(n=40)
    s = smp.draw_sample(con, categories=["hardware", "grocery"], per_stratum=1)
    hw = [r for r in s if r["category"] == "hardware"]
    assert {r["missing"] for r in hw} == {True, False}
    # 10 deciles × {missing, present} × 1 address
    assert len(hw) == 20
    # the flag agrees with the {category}_ratio > 1 rule it is defined by
    ratios = dict(con.execute(
        "SELECT address_id, hardware_ratio FROM analysis.address_gaps").fetchall())
    assert all(r["missing"] == (ratios[r["address_id"]] > 1.0) for r in hw)
    # grocery's missing set is a different set of addresses -- strata are per category
    groc_missing = {r["address_id"] for r in s if r["category"] == "grocery" and r["missing"]}
    hw_missing = {r["address_id"] for r in hw if r["missing"]}
    assert groc_missing != hw_missing


def test_sample_is_restricted_to_the_scope_boroughs():
    """D48: MN+BK. A Queens address is outside the screen's scope, so
    ground-truthing it would spend the budget validating nothing."""
    con = _address_fixture(n=20, borough="BK")
    for i in range(20):
        _add_address(con, f"q{i:03d}", income=20_000 + 1_000 * i, borough="QN")
    s = smp.draw_sample(con, categories=["hardware"], per_stratum=99)
    assert {r["borough"] for r in s} == {"BK"}
    s_qn = smp.draw_sample(con, categories=["hardware"], per_stratum=99, boroughs=("QN",))
    assert {r["borough"] for r in s_qn} == {"QN"}


def test_ineligible_addresses_are_out_of_frame():
    con = _address_fixture(n=20)
    con.execute("UPDATE analysis.address_gaps SET eligible = false WHERE address_id = 'a000'")
    s = smp.draw_sample(con, categories=["hardware"], per_stratum=99)
    assert "a000" not in {r["address_id"] for r in s}
    s_all = smp.draw_sample(con, categories=["hardware"], per_stratum=99, eligible_only=False)
    assert "a000" in {r["address_id"] for r in s_all}


def test_unit_weighted_flag_changes_the_draw():
    """Address-weighted by default (one lot, one draw); --unit-weighted draws
    proportional to units_capped, for reading the sample as a statement about
    households rather than about loci's inventory at a point."""
    con = _address_fixture(n=40)
    # make one address in each stratum enormously large so weighting must show
    con.execute("UPDATE analysis.address_gaps SET units = 5000, units_capped = 500 "
                "WHERE address_id IN ('a001', 'a003', 'a005', 'a007', 'a009')")
    plain = smp.draw_sample(con, categories=["hardware"], per_stratum=1)
    weighted = smp.draw_sample(con, categories=["hardware"], per_stratum=1, unit_weighted=True)
    assert len(plain) == len(weighted)
    big = {"a001", "a003", "a005", "a007", "a009"}
    assert len(big & {r["address_id"] for r in weighted}) > len(big & {r["address_id"] for r in plain})
    # and both draws are reproducible from the seed
    assert [r["address_id"] for r in weighted] == \
        [r["address_id"] for r in smp.draw_sample(con, categories=["hardware"],
                                                  per_stratum=1, unit_weighted=True)]


def test_unmapped_categories_are_still_skipped_on_the_address_frame():
    con = _address_fixture(n=20)
    s = smp.draw_sample(con, categories=["clinic", "hardware"], per_stratum=1)
    assert {r["category"] for r in s} == {"hardware"}
    p = smp.plan(s, ["clinic", "hardware"])
    assert p["skipped"] == ["clinic"]
    assert p["calls"] == len(s)
    assert p["unit"] == "address"


class _RecordingSession:
    def __init__(self):
        self.bodies = []
    def post(self, url, json=None, timeout=None, headers=None):
        self.bodies.append(json)
        return _FakeResp()


def test_run_writes_address_id_and_null_h3_index(tmp_path):
    """An address row carries address_id + borough and a NULL h3_index; the
    2,970 pre-D38 rows are the ones with an h3_index, and the two frames must
    stay separable in SQL."""
    con = _address_fixture(n=20)
    sess = _RecordingSession()
    client = GooglePlacesClient(api_key="k", budget=100, ledger_path=tmp_path / "l.json",
                                session=sess)
    s = smp.draw_sample(con, categories=["hardware"], per_stratum=1)
    n = smp.run(con, client, s, ["hardware"], dry_run=False)
    assert n == len(s)

    rows = con.execute("""SELECT address_id, borough, h3_index, category, income_decile, radius_m
        FROM analysis.coverage_validation ORDER BY address_id""").fetchall()
    assert len(rows) == n
    assert all(r[0] is not None and r[1] == "BK" and r[2] is None for r in rows)
    assert {r[3] for r in rows} == {"hardware"}
    assert all(1 <= r[4] <= 10 for r in rows)
    assert {r[5] for r in rows} == {smp.RADIUS_M}
    # every hex-frame query still works and returns nothing from this run
    assert con.execute("SELECT count(*) FROM analysis.coverage_validation "
                       "WHERE h3_index IS NOT NULL").fetchone()[0] == 0

    # the Google centre is the ADDRESS point, not a hex centroid
    lots = dict(con.execute("SELECT address_id, lat FROM analysis.address_gaps").fetchall())
    sent = {b["locationRestriction"]["circle"]["center"]["latitude"] for b in sess.bodies}
    assert sent <= set(lots.values())
    assert len(sent) > 1, "every call went to the same point"


def test_run_is_idempotent_per_address_and_category(tmp_path):
    con = _address_fixture(n=20)
    client = GooglePlacesClient(api_key="k", budget=100, ledger_path=tmp_path / "l.json",
                                session=_FakeSession())
    s = smp.draw_sample(con, categories=["hardware"], per_stratum=1)
    smp.run(con, client, s, ["hardware"], dry_run=False)
    smp.run(con, client, s, ["hardware"], dry_run=False)
    assert con.execute("SELECT count(*) FROM analysis.coverage_validation").fetchone()[0] == len(s)


def test_recount_local_re_measures_address_rows_at_their_lot(tmp_path):
    """The local side counts loci's canonical POIs around the ADDRESS point,
    the same centre and radius as the Google call."""
    con = _address_fixture(n=20)
    lon, lat = con.execute("SELECT lon, lat FROM analysis.address_gaps "
                           "WHERE address_id = 'a005'").fetchone()
    _add_poi(con, "overture_places:9", "overture_places", "hardware", True, lat=lat, lon=lon)
    con.execute("""INSERT INTO analysis.coverage_validation
        (address_id, borough, category, income_decile, n_ground_truth, n_overture, n_osm,
         sampled_on, radius_m)
        VALUES ('a005', 'BK', 'hardware', 5, 3, 0, 0, ?, ?)""",
                [dt.date.today(), smp.RADIUS_M])
    assert smp.recount_local(con) == 1
    row = con.execute("SELECT n_ground_truth, n_local_canonical FROM analysis.coverage_validation "
                      "WHERE address_id = 'a005'").fetchone()
    assert row[0] == 3        # Google count untouched
    assert row[1] == 1        # counted at the lot


def test_ensure_address_frame_drops_the_hex_era_primary_key():
    """A database still carrying PRIMARY KEY (h3_index, category) physically
    cannot hold an address row -- a DuckDB PK column is implicitly NOT NULL
    and there is no DROP CONSTRAINT. The migration must preserve every frozen
    hex row while making the address frame writable."""
    con = _fixture()
    con.execute("DROP TABLE analysis.coverage_validation")
    con.execute("""CREATE TABLE analysis.coverage_validation (
        h3_index       VARCHAR REFERENCES analysis.hex(h3_index),
        category       VARCHAR NOT NULL,
        income_decile  SMALLINT NOT NULL CHECK (income_decile BETWEEN 1 AND 10),
        n_ground_truth INTEGER NOT NULL,
        n_overture     INTEGER NOT NULL,
        n_osm          INTEGER NOT NULL,
        n_city_source  INTEGER,
        sampled_on     DATE NOT NULL,
        PRIMARY KEY (h3_index, category))""")
    con.execute("""INSERT INTO analysis.coverage_validation
        (h3_index, category, income_decile, n_ground_truth, n_overture, n_osm, sampled_on)
        VALUES ('h1', 'hardware', 5, 7, 1, 1, ?)""", [dt.date(2026, 9, 2)])

    assert smp.ensure_address_frame(con) == 1
    assert smp.ensure_address_frame(con) == 0        # idempotent

    kept = con.execute("""SELECT h3_index, n_ground_truth, radius_m, address_id
        FROM analysis.coverage_validation""").fetchall()
    assert kept == [("h1", 7, None, None)]           # the frozen hex row, verbatim
    con.execute("""INSERT INTO analysis.coverage_validation
        (address_id, borough, category, income_decile, n_ground_truth, n_overture, n_osm,
         sampled_on, radius_m)
        VALUES ('a1', 'BK', 'hardware', 5, 2, 0, 0, ?, ?)""", [dt.date.today(), smp.RADIUS_M])
    assert con.execute("SELECT count(*) FROM analysis.coverage_validation "
                       "WHERE h3_index IS NULL").fetchone()[0] == 1
