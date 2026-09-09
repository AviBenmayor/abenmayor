import math

import pandas as pd

from loci import db as locidb
from loci.grid.acs import (
    ACS_VARIABLE_NOTES,
    AGE_BANDS,
    B01001_AGE_CELLS,
    BORO_COUNTY,
    EDU_COLLEGE_CELLS,
    GETVARS,
    INTENSIVE_SPECS,
    MAX_GET_VARS,
    SHARE_SPECS,
    _clean,
    _moe_proportion,
    _sum_cells,
    build_acs,
    fetch_acs,
)

H1 = "892a100d67bffff"   # real H3 res-9 cells (arbitrary NYC-area points)
H2 = "892a100d183ffff"
LAT1, LON1 = 40.7580, -73.9855
LAT2, LON2 = 40.7300, -73.9350
TRACT_GEOID = "36061000100"   # county 061 (Manhattan), bct2020 "1000100"


def test_clean_handles_census_sentinels():
    assert _clean("4839") == 4839.0
    assert _clean("-666666666") is None   # ACS not-computable
    assert _clean("") is None
    assert _clean(None) is None
    assert _clean("92263") == 92263.0


def test_borough_county_mapping():
    # Queens borocode 4 -> county 081; used to build the tract GEOID
    assert BORO_COUNTY["4"] == "081"
    assert BORO_COUNTY["1"] == "061"  # Manhattan
    assert set(BORO_COUNTY) == {"1", "2", "3", "4", "5"}


def test_getvars_matches_documented_variable_notes():
    """Drift test (D54): ACS_VARIABLE_NOTES is a hand-maintained doc of what
    every fetched Census cell means. If GETVARS is edited without updating
    the notes (or vice versa), this catches it instead of letting the two
    silently diverge."""
    assert set(GETVARS) == set(ACS_VARIABLE_NOTES)
    assert len(GETVARS) == len(set(GETVARS))  # no accidental duplicates
    # every documented variable is a real Census E/M cell reference
    for var in ACS_VARIABLE_NOTES:
        table, _, cell = var.partition("_")
        assert table[0] == "B" and table[1:].isdigit()
        assert cell[-1] in ("E", "M")


def test_moe_proportion_matches_acs_handbook_formula():
    # X subset of Y, well inside [0,1] -- no fallback needed.
    x, x_moe, y, y_moe = 190.0, 20.0, 380.0, 30.0
    p = x / y
    expected = math.sqrt(x_moe ** 2 - (p ** 2) * (y_moe ** 2)) / y
    got = _moe_proportion(x, x_moe, y, y_moe)
    assert got is not None
    assert math.isclose(got, expected, rel_tol=1e-6)


def test_moe_proportion_falls_back_when_subtraction_negative():
    # p close to 1 with a large Y moe relative to X moe drives the subtraction
    # negative; the handbook fallback adds instead of subtracting, and must
    # never raise or return a negative/NaN value.
    x, x_moe, y, y_moe = 99.0, 1.0, 100.0, 50.0
    p = x / y
    under_sqrt_direct = x_moe ** 2 - (p ** 2) * (y_moe ** 2)
    assert under_sqrt_direct < 0   # confirms this case exercises the fallback
    expected = math.sqrt(x_moe ** 2 + (p ** 2) * (y_moe ** 2)) / y
    got = _moe_proportion(x, x_moe, y, y_moe)
    assert got is not None
    assert got > 0
    assert math.isclose(got, expected, rel_tol=1e-6)


def test_moe_proportion_handles_missing_or_zero_denominator():
    assert _moe_proportion(1.0, 1.0, 0.0, 1.0) is None
    assert _moe_proportion(1.0, 1.0, None, 1.0) is None
    assert _moe_proportion(None, 1.0, 10.0, 1.0) is None


def _fake_tract_record() -> dict:
    """One synthetic tract, values chosen to (a) pass the B25044/B25003
    cross-table sanity check build_acs runs (own+renter totals reconcile)
    and (b) give hand-computable expected hex outputs at the two unit-share
    weights the fixture below assigns (0.6 / 0.4)."""
    rec = {
        "B01003_001E": "1000", "B01003_001M": "100",
        "B11001_001E": "400", "B11001_001M": "40",
        "B19013_001E": "80000", "B19013_001M": "5000",
        "B25003_001E": "380", "B25003_001M": "30",
        "B25003_003E": "190", "B25003_003M": "20",
        "B08201_001E": "400", "B08201_001M": "40",
        "B08201_002E": "80", "B08201_002M": "15",
        "B25044_001E": "380", "B25044_001M": "30",
        "B25044_002E": "190", "B25044_002M": "20",
        "B25044_003E": "19", "B25044_003M": "6",
        "B25044_009E": "190", "B25044_009M": "20",
        "B25044_010E": "76", "B25044_010M": "12",
        # ---- 2026-09-09 extension ----
        # Median age / average household size: INTENSIVE, so the hex value is
        # the unit-share-weighted mean of the tract values -- with one tract
        # that is the tract value itself, at either weight.
        "B01002_001E": "38.4", "B01002_001M": "1.5",
        "B25010_001E": "2.50", "B25010_001M": "0.10",
        # Sex by age. B01001_001E MUST equal B01003_001E (1000) or build_acs
        # raises. The band cells below are chosen so the three bands are
        # hand-checkable: under_18 = 8 cells x 25 = 200 (0.20), age_18_34 =
        # 12 cells x 25 = 300 (0.30), age_65_plus = 12 cells x 10 = 120
        # (0.12); the remaining 380 are the uncarried 35-64 band.
        "B01001_001E": "1000", "B01001_001M": "100",
        # Race/ethnicity: 300/200/150/300 of 1000 -> .30/.20/.15/.30, the
        # remaining 50 being the non-Hispanic categories not carried.
        "B03002_001E": "1000", "B03002_001M": "100",
        "B03002_003E": "300", "B03002_003M": "40",
        "B03002_004E": "200", "B03002_004M": "30",
        "B03002_006E": "150", "B03002_006M": "25",
        "B03002_012E": "300", "B03002_012M": "45",
        # Education, 25+ universe of 800: 200+60+25+15 = 300 -> 0.375.
        "B15003_001E": "800", "B15003_001M": "60",
        "B15003_022E": "200", "B15003_022M": "20",
        "B15003_023E": "60", "B15003_023M": "12",
        "B15003_024E": "25", "B15003_024M": "8",
        "B15003_025E": "15", "B15003_025M": "6",
        # Household size: 160 one-person of 400 households -> 0.40.
        "B11016_001E": "400", "B11016_001M": "40",
        "B11016_010E": "160", "B11016_010M": "25",
    }
    # Age cells: uniform within a band so the expected shares are exact.
    for _band, _cells in AGE_BANDS.items():
        _est = {"under_18": "25", "age_18_34": "25", "age_65_plus": "10"}[_band]
        _moe = {"under_18": "5", "age_18_34": "5", "age_65_plus": "4"}[_band]
        for _c in _cells:
            rec[f"B01001_{_c}E"] = _est
            rec[f"B01001_{_c}M"] = _moe
    # Every cell in B01001_AGE_CELLS belongs to exactly one band, so the loop
    # above has already filled them all; this asserts that rather than
    # assuming it (a cell added to B01001_AGE_CELLS but to no band would be
    # fetched and then silently ignored by every share).
    assert set(B01001_AGE_CELLS) == {c for cells in AGE_BANDS.values() for c in cells}
    # The three bands cover 200 + 300 + 120 = 620 of the 1000; the missing 380
    # is the 35-64 band, whose cells this module deliberately does not fetch
    # (it is 1 - the other three by construction).
    return rec


def _write_pluto_fixture(path) -> None:
    """One tract split 60/40 (by residential units) between H1 and H2 --
    unit-weighted (dasymetric) apportionment, not areal."""
    df = pd.DataFrame([
        {"borocode": "1", "bct2020": "1000100", "latitude": LAT1, "longitude": LON1, "unitsres": 60},
        {"borocode": "1", "bct2020": "1000100", "latitude": LAT2, "longitude": LON2, "unitsres": 40},
    ])
    df.to_csv(path, index=False)


def test_tract_hex_propagation_and_moe_math(tmp_path, monkeypatch):
    """No-network synthetic fixture for the tract -> hex apportionment and
    MOE propagation added under D54 (GTM-78 D7 pre-test). Monkeypatches
    fetch_acs so no Census API call happens; verifies build_acs's arithmetic
    against hand-computed expectations for both the extensive-sum apportion
    (renter_share numerator/denominator) and the proportion-MOE formula."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    for h in (H1, H2):
        con.execute(
            "INSERT INTO analysis.hex (h3_index, resolution, geom, centroid, land_fraction) "
            "VALUES (?, 9, ST_Point(0,0), ST_Point(0,0), 1.0)", [h])

    pluto_csv = tmp_path / "pluto.csv"
    _write_pluto_fixture(pluto_csv)

    fake = {TRACT_GEOID: _fake_tract_record()}
    monkeypatch.setattr("loci.grid.acs.fetch_acs", lambda year=2023, refresh=False: fake)

    n = build_acs(con, pluto_csv=pluto_csv, year=2023)
    assert n == 2

    rows = {r[0]: r for r in con.execute(
        "SELECT h3_index, population, population_moe, renter_share, renter_share_moe, "
        "zero_vehicle_hh_share, zero_vehicle_hh_share_moe, "
        "zero_vehicle_owner_share, zero_vehicle_owner_share_moe, "
        "zero_vehicle_renter_share, zero_vehicle_renter_share_moe "
        "FROM analysis.hex_demographics").fetchall()}
    assert set(rows) == {H1, H2}

    for h, w in ((H1, 0.6), (H2, 0.4)):
        (_, pop, pop_moe, renter_share, renter_share_moe,
         zv_hh, zv_hh_moe, zv_own, zv_own_moe, zv_rt, zv_rt_moe) = rows[h]

        # Extensive apportionment: population * unit share.
        assert math.isclose(pop, w * 1000.0, rel_tol=1e-6)
        assert math.isclose(pop_moe, w * 100.0, rel_tol=1e-6)   # RSS of one term = the term

        # renter_share = apportioned renter units / apportioned occupied units.
        # Both numerator and denominator scale by the SAME w, so the ratio
        # reproduces the tract-level ratio exactly regardless of w.
        assert math.isclose(renter_share, 190.0 / 380.0, rel_tol=1e-6)
        rent_num_moe = w * 20.0
        occ_den_moe = w * 30.0
        p = 190.0 / 380.0
        under = rent_num_moe ** 2 - (p ** 2) * (occ_den_moe ** 2)
        if under < 0:
            under = rent_num_moe ** 2 + (p ** 2) * (occ_den_moe ** 2)
        expected_renter_moe = math.sqrt(under) / (w * 380.0)
        assert math.isclose(renter_share_moe, expected_renter_moe, rel_tol=1e-6)

        # zero_vehicle_hh_share = B08201_002E / B08201_001E.
        assert math.isclose(zv_hh, 80.0 / 400.0, rel_tol=1e-6)

        # tenure-split cross-check shares.
        assert math.isclose(zv_own, 19.0 / 190.0, rel_tol=1e-6)
        assert math.isclose(zv_rt, 76.0 / 190.0, rel_tol=1e-6)

        # every MOE is finite, non-negative, and actually got computed (not None)
        for moe in (renter_share_moe, zv_hh_moe, zv_own_moe, zv_rt_moe):
            assert moe is not None and moe >= 0.0


def test_build_acs_raises_on_b25044_b25003_cross_table_mismatch(tmp_path, monkeypatch):
    """Fail loud (CLAUDE.md/CONTEXT.md invariant): if B25044's owner+renter
    total materially disagrees with B25003's occupied-unit total across the
    pulled tracts, that means a cell index is wrong, not that the data is
    noisy -- build_acs must raise rather than silently ingest a bad pull."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute(
        "INSERT INTO analysis.hex (h3_index, resolution, geom, centroid, land_fraction) "
        "VALUES (?, 9, ST_Point(0,0), ST_Point(0,0), 1.0)", [H1])
    pluto_csv = tmp_path / "pluto.csv"
    _write_pluto_fixture(pluto_csv)

    bad = _fake_tract_record()
    bad["B25044_002E"] = "10"   # owner total slashed -> owner+renter << B25003 total
    fake = {TRACT_GEOID: bad}
    monkeypatch.setattr("loci.grid.acs.fetch_acs", lambda year=2023, refresh=False: fake)

    try:
        build_acs(con, pluto_csv=pluto_csv, year=2023)
    except RuntimeError as exc:
        assert "cross-check" in str(exc)
    else:
        raise AssertionError("expected build_acs to raise on the B25044/B25003 mismatch")


# ------------------------------------------------------------------------
# 2026-09-09 age / race / education / household-size extension
# ------------------------------------------------------------------------

def test_age_band_cells_match_the_verified_census_labels():
    """Pins the exact B01001 cell membership of each band against the labels
    read off api.census.gov/data/2023/acs/acs5/variables.json on 2026-09-09.
    A silently shifted index (say 65+ starting at _019, "62 to 64 years")
    would move real people between bands and never raise -- this is the only
    thing standing between that and a published number."""
    assert AGE_BANDS["under_18"] == ("003", "004", "005", "006",
                                     "027", "028", "029", "030")
    assert AGE_BANDS["age_18_34"] == ("007", "008", "009", "010", "011", "012",
                                      "031", "032", "033", "034", "035", "036")
    assert AGE_BANDS["age_65_plus"] == ("020", "021", "022", "023", "024", "025",
                                        "044", "045", "046", "047", "048", "049")
    # Male/female halves must be the same length -- the bands are unions of
    # matching age ranges across the two sexes.
    for cells in AGE_BANDS.values():
        male = [c for c in cells if int(c) <= 25]
        female = [c for c in cells if int(c) >= 27]
        assert len(male) == len(female)
        # female cell = male cell + 24 in this table's layout
        assert [f"{int(c) + 24:03d}" for c in male] == female
    # No cell is claimed by two bands.
    flat = [c for cells in AGE_BANDS.values() for c in cells]
    assert len(flat) == len(set(flat))
    assert set(flat) <= set(B01001_AGE_CELLS)


def test_every_share_and_intensive_cell_is_actually_fetched():
    """Nothing may be summed that is not in GETVARS -- a numerator cell absent
    from the request would read as null at build time and quietly shrink the
    share rather than fail."""
    for _col, (num_cells, den_cell) in SHARE_SPECS.items():
        for stem in (*num_cells, den_cell):
            assert stem + "E" in ACS_VARIABLE_NOTES
            assert stem + "M" in ACS_VARIABLE_NOTES
    for _col, stem in INTENSIVE_SPECS.items():
        assert stem + "E" in ACS_VARIABLE_NOTES
        assert stem + "M" in ACS_VARIABLE_NOTES
    assert EDU_COLLEGE_CELLS == ("B15003_022", "B15003_023", "B15003_024", "B15003_025")


def test_sum_cells_applies_the_handbook_sum_rule():
    rec = {"A_001E": "10", "A_001M": "3", "A_002E": "20", "A_002M": "4"}
    est, moe = _sum_cells(rec, ("A_001", "A_002"))
    assert est == 30.0
    assert math.isclose(moe, math.sqrt(9 + 16))     # 5.0, RSS not 7.0
    # all-null -> (None, None), never a spurious zero
    assert _sum_cells({"A_001E": "-666666666"}, ("A_001",)) == (None, None)


def test_new_demographics_propagate_with_hand_computed_share_and_moe(tmp_path, monkeypatch):
    """Extends the D54 propagation fixture to the four new groups. Asserts one
    band share and one MOE by hand, plus the intensive fields and the
    denominators the shares were normalised over."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    for h in (H1, H2):
        con.execute(
            "INSERT INTO analysis.hex (h3_index, resolution, geom, centroid, land_fraction) "
            "VALUES (?, 9, ST_Point(0,0), ST_Point(0,0), 1.0)", [h])
    pluto_csv = tmp_path / "pluto.csv"
    _write_pluto_fixture(pluto_csv)
    fake = {TRACT_GEOID: _fake_tract_record()}
    monkeypatch.setattr("loci.grid.acs.fetch_acs", lambda year=2023, refresh=False: fake)

    assert build_acs(con, pluto_csv=pluto_csv, year=2023) == 2

    cols = ("median_age", "median_age_moe", "avg_hh_size", "avg_hh_size_moe",
            "under_18_share", "under_18_share_moe",
            "age_18_34_share", "age_65_plus_share",
            "white_nh_share", "black_nh_share", "asian_nh_share", "hispanic_share",
            "hispanic_share_moe", "college_share", "college_share_moe",
            "one_person_hh_share", "one_person_hh_share_moe")
    rows = {r[0]: dict(zip(cols, r[1:])) for r in con.execute(
        f"SELECT h3_index, {', '.join(cols)} FROM analysis.hex_demographics").fetchall()}
    assert set(rows) == {H1, H2}

    for h, w in ((H1, 0.6), (H2, 0.4)):
        r = rows[h]

        # --- INTENSIVE: unit-share-weighted mean of tract values. One tract,
        # so the hex reproduces the tract value at either weight (num and the
        # weight sum both scale by w). Same for the MOE, which uses the
        # median_hh_income convention (weighted mean of MOEs).
        assert math.isclose(r["median_age"], 38.4, rel_tol=1e-5)
        assert math.isclose(r["median_age_moe"], 1.5, rel_tol=1e-5)
        assert math.isclose(r["avg_hh_size"], 2.50, rel_tol=1e-5)
        assert math.isclose(r["avg_hh_size_moe"], 0.10, rel_tol=1e-5)

        # --- AGE BANDS, BY HAND. under_18 = 8 cells x 25 = 200 over
        # B01001_001 = 1000. Numerator and denominator are both apportioned by
        # the same w, so the ratio is the tract ratio.
        assert math.isclose(r["under_18_share"], 200.0 / 1000.0, rel_tol=1e-5)
        assert math.isclose(r["age_18_34_share"], 300.0 / 1000.0, rel_tol=1e-5)
        assert math.isclose(r["age_65_plus_share"], 120.0 / 1000.0, rel_tol=1e-5)
        # The three carried bands leave the 35-64 residual; never sum to 1.
        assert (r["under_18_share"] + r["age_18_34_share"]
                + r["age_65_plus_share"]) < 1.0

        # --- ONE MOE, BY HAND, end to end. Within the tract the 8 under-18
        # cells (MOE 5 each) combine as the handbook sum: sqrt(8 * 5^2).
        # Apportioned to the hex the numerator MOE is w * that, and the
        # denominator MOE is w * 100 (B01001_001M). Then the handbook
        # proportion formula over the apportioned denominator w * 1000.
        num_moe = w * math.sqrt(8 * 25.0)
        den_moe = w * 100.0
        p = 0.2
        under = num_moe ** 2 - (p ** 2) * (den_moe ** 2)
        if under < 0:
            under = num_moe ** 2 + (p ** 2) * (den_moe ** 2)
        expected = math.sqrt(under) / (w * 1000.0)
        assert math.isclose(r["under_18_share_moe"], expected, rel_tol=1e-5)

        # --- RACE: four mutually exclusive shares over B03002_001.
        assert math.isclose(r["white_nh_share"], 0.30, rel_tol=1e-5)
        assert math.isclose(r["black_nh_share"], 0.20, rel_tol=1e-5)
        assert math.isclose(r["asian_nh_share"], 0.15, rel_tol=1e-5)
        assert math.isclose(r["hispanic_share"], 0.30, rel_tol=1e-5)
        # they sum to <= 1 with the uncarried categories as the remainder
        assert (r["white_nh_share"] + r["black_nh_share"]
                + r["asian_nh_share"] + r["hispanic_share"]) <= 1.0

        # --- EDUCATION: over the 25+ universe (800), NOT total population.
        assert math.isclose(r["college_share"], 300.0 / 800.0, rel_tol=1e-5)
        assert not math.isclose(r["college_share"], 300.0 / 1000.0, rel_tol=1e-3)

        # --- HOUSEHOLD COMPOSITION: over ALL households, not nonfamily only.
        assert math.isclose(r["one_person_hh_share"], 160.0 / 400.0, rel_tol=1e-5)

        for key in ("median_age_moe", "avg_hh_size_moe", "under_18_share_moe",
                    "hispanic_share_moe", "college_share_moe",
                    "one_person_hh_share_moe"):
            assert r[key] is not None and r[key] >= 0.0


def test_build_acs_raises_when_b01001_and_b01003_population_disagree(tmp_path, monkeypatch):
    """Sex-by-age and total-population are different tables over the same
    universe. If they disagree, an age cell index is wrong or a fetch chunk
    merged badly -- either way the band shares are mis-normalised, so
    build_acs must raise instead of ingesting them."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute(
        "INSERT INTO analysis.hex (h3_index, resolution, geom, centroid, land_fraction) "
        "VALUES (?, 9, ST_Point(0,0), ST_Point(0,0), 1.0)", [H1])
    pluto_csv = tmp_path / "pluto.csv"
    _write_pluto_fixture(pluto_csv)

    bad = _fake_tract_record()
    bad["B01001_001E"] = "600"      # 40% below B01003_001E = 1000
    monkeypatch.setattr("loci.grid.acs.fetch_acs",
                        lambda year=2023, refresh=False: {TRACT_GEOID: bad})
    try:
        build_acs(con, pluto_csv=pluto_csv, year=2023)
    except RuntimeError as exc:
        assert "B01001/B01003" in str(exc)
    else:
        raise AssertionError("expected build_acs to raise on the B01001/B01003 mismatch")


# ------------------------------------------------------------- chunked fetch

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_census_api(calls: list, tracts=("000100", "000200"), drop=None):
    """A stand-in for requests.get that answers a chunked ACS tract query the
    way the real API does: echo back only the variables asked for, plus the
    geo columns. Each variable's value encodes its own name, so the merge can
    be checked cell by cell. `drop` omits a tract from every chunk after the
    first, to exercise the tract-set mismatch guard."""
    def _get(url, params=None, timeout=None):
        calls.append(params["get"].split(","))
        wanted = params["get"].split(",")
        county = params["in"].split("county:")[1]
        head = wanted + ["state", "county", "tract"]
        rows = []
        local = list(tracts)
        if drop and len(calls) > 1:
            local = [t for t in local if t != drop]
        for t in local:
            rows.append([f"{v}@{county}{t}" for v in wanted] + ["36", county, t])
        return _FakeResponse([head] + rows)
    return _get


def test_fetch_acs_chunks_the_request_and_merges_per_tract(tmp_path, monkeypatch):
    """GETVARS is past the Census API's 50-variable cap, so fetch_acs splits
    it. The merge is the risky part: every tract record must come back
    carrying EVERY requested variable, with each variable's value the one that
    chunk actually returned for that tract."""
    calls: list = []
    monkeypatch.setattr("loci.grid.acs.requests.get", _fake_census_api(calls))
    monkeypatch.setattr("loci.grid.acs._census_key", lambda: "fake-key")
    monkeypatch.setattr("loci.grid.acs.ACS_TRACTS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("loci.grid.acs._acs_tracts_cache_path",
                        lambda year: tmp_path / f"tracts_{year}.json")

    out = fetch_acs(2023, refresh=True)

    # chunking actually happened, and no request exceeded the cap
    n_chunks = -(-len(GETVARS) // MAX_GET_VARS)
    assert n_chunks > 1, "this test is pointless if GETVARS fits in one request"
    assert len(calls) == len(BORO_COUNTY) * n_chunks
    assert all(len(c) <= MAX_GET_VARS for c in calls)
    # every variable is requested exactly once per county, none dropped or doubled
    per_county = [v for c in calls[:n_chunks] for v in c]
    assert per_county == GETVARS

    # 5 counties x 2 tracts, each record complete and correctly attributed
    assert len(out) == len(BORO_COUNTY) * 2
    geoid = "36061000100"
    assert geoid in out
    rec = out[geoid]
    assert all(v in rec for v in GETVARS)
    for v in GETVARS:
        assert rec[v] == f"{v}@061000100", "a chunk's values landed on the wrong tract"


def test_fetch_acs_raises_when_chunks_disagree_on_the_tract_set(tmp_path, monkeypatch):
    """A tract present in one chunk and absent from another would merge into a
    record missing variables, which build_acs would read as nulls -- i.e. a
    silent partial ingest. Fail loud instead."""
    calls: list = []
    monkeypatch.setattr("loci.grid.acs.requests.get",
                        _fake_census_api(calls, drop="000200"))
    monkeypatch.setattr("loci.grid.acs._census_key", lambda: "fake-key")
    monkeypatch.setattr("loci.grid.acs._acs_tracts_cache_path",
                        lambda year: tmp_path / f"tracts_{year}.json")
    try:
        fetch_acs(2023, refresh=True)
    except RuntimeError as exc:
        assert "disagreed on the tract set" in str(exc)
    else:
        raise AssertionError("expected fetch_acs to raise on the chunk tract-set mismatch")
