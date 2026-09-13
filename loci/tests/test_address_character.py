"""Neighbourhood character at address grain (owner request 2026-09-13).

The distance maths is already covered by tests/test_supply_ratio.py (the same
`catchment_sums` on the same synthetic line graph), so what is tested here is
what is NEW:

  * the LODES sector grouping -- that the three groups partition CNS01..CNS20
    with no overlap and no omission, because `jobs_other_400m` is computed as
    C000 minus the other two and a double-counted sector would silently make it
    negative;
  * the LOT SET -- that `load_lot_points` keeps NON-residential lots, which is
    the one thing that separates this measure from `homes_400m` and the one
    mistake that would report the Financial District as zero office;
  * the LABEL RULES, exercised as SQL on a real DuckDB view over crafted rows,
    not as a re-implementation in Python;
  * that every built address gets exactly one label and an intensity in [0, 1];
  * the column contract and the refusal to write a partial or filtering update.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import duckdb
import pandas as pd
import pytest

from loci import db as locidb
from loci.model.address_character import (
    CHARACTER_COLUMNS,
    CORPORATE_JOBS_FLOOR,
    CORPORATE_JOBS_OFFICE_SHARE,
    CORPORATE_OFFICE_AREA_SHARE,
    INDUSTRIAL_FACTORY_AREA_SHARE,
    LABEL_ORDER,
    OFFICE_FACING_SECTORS,
    OTHER_SECTORS,
    RETAIL_AREA_SHARE,
    RETAIL_FACING_SECTORS,
    RETAIL_JOBS_FLOOR,
    RETAIL_JOBS_SHARE,
    _guard,
    _sector_sum_sql,
    load_lot_points,
    write_character,
)

MIGRATION = pathlib.Path(locidb.SQL_DIR) / "021_address_character.sql"


# ---------------------------------------------------------- the sector split

ALL_CNS = tuple(f"CNS{i:02d}" for i in range(1, 21))


def test_the_three_sector_groups_partition_cns01_to_cns20():
    """`jobs_other_400m` is C000 - retail - office, and C000 is the feed's own
    sum of CNS01..CNS20. If the groups overlapped, `other` would come out
    negative on a block whose employment is entirely in the overlap; if they
    omitted a sector, `other` would quietly absorb it, which is the intended
    behaviour and is exactly what OTHER_SECTORS documents."""
    grouped = (*RETAIL_FACING_SECTORS, *OFFICE_FACING_SECTORS, *OTHER_SECTORS)
    assert sorted(grouped) == sorted(ALL_CNS), "a sector is missing or duplicated"
    assert len(set(grouped)) == len(grouped), "a sector is in two groups"


def test_retail_facing_is_the_storefront_naics_and_nothing_else():
    # 44-45 retail trade, 71 arts/entertainment/recreation, 72 accommodation and
    # food services, 81 other services (hair, nails, laundry, repair) -- the
    # NAICS bucket that holds most of Loci's own daily-needs categories.
    assert RETAIL_FACING_SECTORS == ("CNS07", "CNS17", "CNS18", "CNS19")


def test_office_facing_is_desk_work_including_public_administration():
    # 51 information, 52 finance, 53 real estate, 54 professional, 55 management,
    # 56 admin/support, 92 public administration. CNS20 is in on purpose: the
    # Civic Center is a business district with a different landlord, and leaving
    # it out would label it residential.
    assert OFFICE_FACING_SECTORS == (
        "CNS09", "CNS10", "CNS11", "CNS12", "CNS13", "CNS14", "CNS20")
    assert "CNS20" in OFFICE_FACING_SECTORS


def test_health_and_education_are_the_remainder_not_retail_or_office():
    """CNS15 (education) and CNS16 (health care) are the two biggest members of
    `other` in New York. Folding them into either headline share would make a
    hospital block read 'corporate' and Morningside Heights read like Midtown."""
    for sector in ("CNS15", "CNS16"):
        assert sector in OTHER_SECTORS
        assert sector not in RETAIL_FACING_SECTORS
        assert sector not in OFFICE_FACING_SECTORS


def test_sector_sum_sql_names_every_column_once():
    sql = _sector_sum_sql(RETAIL_FACING_SECTORS, "jobs_retail")
    for c in RETAIL_FACING_SECTORS:
        assert sql.count(f"w.{c} ") == 1
    assert sql.endswith("AS jobs_retail")


# ----------------------------------------------------------------- the lots

def _tiny_pluto(tmp_path: pathlib.Path) -> pathlib.Path:
    """Three lots: a rowhouse, an office tower with UnitsRes = 0, and a factory
    with UnitsRes = 0. The two zero-unit lots are the whole point."""
    p = tmp_path / "pluto.csv"
    p.write_text(
        "BBL,latitude,longitude,retailarea,officearea,resarea,factryarea,"
        "bldgarea,unitsres,version\n"
        "1000010001,40.7100,-74.0100,0,0,4000,0,4000,4,24v4\n"
        "1000010002,40.7110,-74.0110,20000,900000,0,0,950000,0,24v4\n"
        "3000010003,40.6600,-74.0200,0,0,0,120000,130000,0,24v4\n"
        "5000010004,40.5800,-74.1500,0,0,3000,0,3000,3,24v4\n")
    return p


def test_load_lot_points_keeps_lots_with_no_residential_units(tmp_path):
    """THE regression guard. analysis.address is `PLUTO lots WHERE UnitsRes > 0`,
    so reusing homes_400m's weight set -- which is what "the exact lot set
    homes_400m uses" would have meant -- drops every pure-office and every
    industrial lot and reports the Financial District as zero office floor
    area."""
    con = duckdb.connect()
    lots = load_lot_points(con, (-74.10, 40.60, -73.90, 40.80),
                           pluto_csv=_tiny_pluto(tmp_path))
    assert len(lots) == 3                                   # the SI lot is outside the bbox
    assert (lots["unitsres"] == 0).sum() == 2
    assert lots["office_area"].sum() == 900_000
    assert lots["factory_area"].sum() == 120_000
    # And the subset that reproduces homes_400m's set is recoverable.
    assert (lots["unitsres"] > 0).sum() == 1


def test_load_lot_points_refuses_an_empty_bbox_rather_than_writing_zeros(tmp_path):
    con = duckdb.connect()
    with pytest.raises(RuntimeError, match="refusing to write zeros"):
        load_lot_points(con, (0.0, 0.0, 1.0, 1.0), pluto_csv=_tiny_pluto(tmp_path))


def test_load_lot_points_refuses_a_missing_file(tmp_path):
    con = duckdb.connect()
    with pytest.raises(FileNotFoundError, match="no buildings"):
        load_lot_points(con, (-74.1, 40.6, -73.9, 40.8),
                        pluto_csv=tmp_path / "absent.csv")


# ------------------------------------------------------------- the label SQL

ADDR_COLS = ("address_id", "borough", "nta_code", "neighborhood", "lon", "lat",
             "units", "present_count", "eligible", "n_missing", "reach_source",
             "reach_hash", "graph_version", "run_at", "homes_400m", "jobs_400m",
             "retail_area_400m", "office_area_400m", "res_area_400m",
             "factory_area_400m", "bldg_area_400m",
             "jobs_retail_400m", "jobs_office_400m", "jobs_other_400m",
             "character_radius_m", "character_jobs_vintage", "character_run_at")


def _row(address_id, *, retail=0.0, office=0.0, res=0.0, factory=0.0,
         j_retail=0, j_office=0, j_other=0, built=True, borough="MN",
         nta="MN0000"):
    bldg = retail + office + res + factory
    return {
        "address_id": address_id, "borough": borough, "nta_code": nta,
        "neighborhood": nta, "lon": -73.98, "lat": 40.75, "units": 1,
        "present_count": 15, "eligible": True, "n_missing": 0,
        "reach_source": "tiers", "reach_hash": "t", "graph_version": "g",
        "run_at": dt.datetime(2026, 9, 13),
        "homes_400m": 100, "jobs_400m": j_retail + j_office + j_other,
        "retail_area_400m": retail, "office_area_400m": office,
        "res_area_400m": res, "factory_area_400m": factory,
        "bldg_area_400m": bldg,
        "jobs_retail_400m": j_retail, "jobs_office_400m": j_office,
        "jobs_other_400m": j_other,
        "character_radius_m": 400.0, "character_jobs_vintage": 2023,
        "character_run_at": dt.datetime(2026, 9, 13) if built else None,
    }


@pytest.fixture()
def warehouse():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _labels(con, rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    con.register("_rows", frame)
    con.execute(f"INSERT INTO analysis.address ({', '.join(ADDR_COLS)}) "
                f"SELECT {', '.join(ADDR_COLS)} FROM _rows")
    con.unregister("_rows")
    return con.execute(
        "SELECT address_id, character, character_intensity, "
        "       retail_area_share, office_area_share, factory_area_share, "
        "       jobs_retail_share, jobs_office_share "
        "FROM analysis.address_character ORDER BY address_id").fetchdf()


def test_midtown_shaped_row_is_corporate_on_floor_area(warehouse):
    # Office is 40% of the four named uses -> past CORPORATE_OFFICE_AREA_SHARE.
    out = _labels(warehouse, [_row("a", office=4_000_000, res=6_000_000)])
    assert out.loc[0, "character"] == "corporate"
    assert out.loc[0, "office_area_share"] == pytest.approx(0.4)


def test_a_loft_office_district_is_corporate_on_jobs_alone(warehouse):
    """SoHo/DUMBO: converted lofts whose PLUTO split still says residential or
    'other', but whose payroll is unmistakably desk work. The jobs route exists
    because the two sources fail in opposite directions."""
    out = _labels(warehouse, [_row("a", res=1_000_000, retail=50_000,
                                   j_office=9_000, j_retail=800, j_other=700)])
    assert out.loc[0, "character"] == "corporate"


def test_the_jobs_floor_stops_a_rowhouse_block_being_corporate_on_eleven_jobs(warehouse):
    """A 60% office share of 10 jobs is a title company over a bodega, not a
    business district. CORPORATE_JOBS_FLOOR is what makes the share meaningful."""
    out = _labels(warehouse, [_row("a", res=1_000_000, j_office=6, j_other=4)])
    assert out.loc[0, "jobs_office_share"] == pytest.approx(0.6)
    assert out.loc[0, "character"] == "residential"


def test_a_retail_avenue_is_retail_mixed(warehouse):
    out = _labels(warehouse, [_row("a", retail=150_000, res=850_000)])
    assert out.loc[0, "retail_area_share"] == pytest.approx(0.15)
    assert out.loc[0, "character"] == "retail_mixed"


def test_a_block_whose_jobs_are_the_shops_is_retail_mixed_without_the_floor_area(warehouse):
    """PLUTO folds ground-floor stores into ComArea on old mixed-use strips, so
    RetailArea is a floor on a floor. The payroll route is what rescues them."""
    out = _labels(warehouse, [_row("a", res=1_000_000, retail=10_000,
                                   j_retail=1_500, j_office=600, j_other=900)])
    assert out.loc[0, "retail_area_share"] < RETAIL_AREA_SHARE
    assert out.loc[0, "jobs_retail_share"] == pytest.approx(0.5)
    assert out.loc[0, "character"] == "retail_mixed"


def test_the_retail_jobs_floor_stops_a_quiet_block_being_retail_mixed_on_a_deli(warehouse):
    """THE most consequential threshold here. In a quiet residential catchment
    the few jobs that exist are disproportionately the corner deli and the nail
    salon, so a high retail SHARE of almost nothing is a data gap wearing a
    costume. Without the floor the payroll route labelled 74% of Park Slope
    retail_mixed; with it, 25% -- its avenues, not its side streets."""
    out = _labels(warehouse, [_row("a", res=1_000_000, retail=10_000,
                                   j_retail=90, j_office=40, j_other=70)])
    assert out.loc[0, "jobs_retail_share"] == pytest.approx(0.45)
    assert out.loc[0, "character"] == "residential"


def test_the_retail_jobs_floor_is_on_the_retail_count_not_on_total_jobs(warehouse):
    """Symmetric with CORPORATE_JOBS_FLOOR in spirit, different in unit: the
    corporate floor is on TOTAL jobs (a CBD is dense in employment of every
    kind), the retail floor is on the retail-facing COUNT, because a commercial
    district is defined by how many shops it has, not by how busy the office
    tower next door is."""
    just_under = _labels(warehouse, [_row("a", res=1_000_000,
                                          j_retail=RETAIL_JOBS_FLOOR - 1,
                                          j_office=100, j_other=100)])
    assert just_under.loc[0, "character"] == "residential"
    warehouse.execute("DELETE FROM analysis.address")
    just_over = _labels(warehouse, [_row("a", res=1_000_000,
                                         j_retail=RETAIL_JOBS_FLOOR,
                                         j_office=100, j_other=100)])
    assert just_over.loc[0, "character"] == "retail_mixed"


def test_an_ibz_is_industrial_even_when_a_taproom_pushes_retail_past_its_cut(warehouse):
    """LABEL_ORDER is load-bearing: East Williamsburg and the Sunset Park
    waterfront pick up breweries, roasteries and food halls, which clear
    RETAIL_AREA_SHARE while the block is still a working industrial district."""
    out = _labels(warehouse, [_row("a", factory=400_000, retail=150_000,
                                   res=450_000)])
    assert out.loc[0, "factory_area_share"] >= INDUSTRIAL_FACTORY_AREA_SHARE
    assert out.loc[0, "retail_area_share"] >= RETAIL_AREA_SHARE
    assert out.loc[0, "character"] == "industrial"
    assert LABEL_ORDER.index("industrial") < LABEL_ORDER.index("retail_mixed")


def test_a_cbd_with_a_retail_podium_is_corporate_not_retail_mixed(warehouse):
    """Herald Square is a business district with shops in it, not a shopping
    district with offices above -- so `corporate` is tested first."""
    out = _labels(warehouse, [_row("a", office=5_000_000, retail=1_500_000,
                                   res=3_500_000)])
    assert out.loc[0, "character"] == "corporate"


def test_park_slope_shaped_row_is_residential(warehouse):
    out = _labels(warehouse, [_row("a", res=980_000, retail=20_000,
                                   j_retail=400, j_office=400, j_other=1_200)])
    assert out.loc[0, "character"] == "residential"
    # Nowhere near any threshold -> high residential intensity.
    assert out.loc[0, "character_intensity"] > 0.4


def test_intensity_is_zero_to_one_and_rises_with_distance_past_the_threshold(warehouse):
    out = _labels(warehouse, [
        _row("a", office=350_001, res=649_999),      # a hair over the cut
        _row("b", office=900_000, res=100_000),      # far past it
        _row("c", res=1_000_000),                    # far below everything
    ])
    i = out.set_index("address_id")["character_intensity"]
    assert 0.0 <= i["a"] < 0.02
    assert i["b"] > 0.7
    assert 0.0 <= i["c"] <= 1.0
    assert (out["character_intensity"].between(0, 1)).all()


def test_a_park_edge_with_nothing_built_is_residential_not_null(warehouse):
    """Owner rule D75: no eligibility gate, never drop an address. Zero built
    floor area and zero jobs within 400 m is a MEASUREMENT, and the label has to
    say something rather than go NULL."""
    out = _labels(warehouse, [_row("a")])
    assert out.loc[0, "character"] == "residential"
    assert out.loc[0, "character_intensity"] == pytest.approx(1.0)
    assert pd.isna(out.loc[0, "office_area_share"])          # 0/0 is NULL, not 0


def test_every_built_address_gets_exactly_one_label_and_no_built_address_is_null(warehouse):
    rows = [
        _row("a", office=4_000_000, res=6_000_000),
        _row("b", retail=150_000, res=850_000),
        _row("c", factory=400_000, res=600_000),
        _row("d", res=1_000_000),
        _row("e"),
        _row("f", res=1_000_000, j_office=9_000, j_other=1_000),
    ]
    out = _labels(warehouse, rows)
    assert out["character"].notna().all()
    assert set(out["character"]) <= set(LABEL_ORDER)
    assert out["character_intensity"].notna().all()


def test_an_unbuilt_address_gets_a_null_label_not_a_fabricated_residential(warehouse):
    """`character_run_at IS NULL` means the sweep has never run for that
    borough. Labelling it 'residential' would be inventing an observation."""
    out = _labels(warehouse, [_row("a", res=1_000_000, built=False)])
    assert pd.isna(out.loc[0, "character"])
    assert pd.isna(out.loc[0, "character_intensity"])


def test_nta_character_rolls_up_and_excludes_unbuilt_addresses(warehouse):
    _labels(warehouse, [
        _row("a", office=4_000_000, res=6_000_000, nta="MN0101"),
        _row("b", office=4_000_000, res=6_000_000, nta="MN0101"),
        _row("c", retail=150_000, res=850_000, nta="MN0101"),
        _row("d", res=1_000_000, nta="MN0202", built=False),
    ])
    n = warehouse.execute(
        "SELECT * FROM analysis.nta_character ORDER BY nta_code").fetchdf()
    assert list(n["nta_code"]) == ["MN0101"]                 # the unbuilt NTA drops out
    assert n.loc[0, "addresses"] == 3
    assert n.loc[0, "dominant_character"] == "corporate"
    assert n.loc[0, "share_corporate"] == pytest.approx(2 / 3)
    assert n.loc[0, "share_retail_mixed"] == pytest.approx(1 / 3)


# ------------------------------------------------------------ the thresholds

def test_the_thresholds_are_absolute_not_quantiles():
    """D34's lesson: a cut placed at the p80 of a distribution fixes the label
    rate at 20% BY CONSTRUCTION and the resulting ranking is a quantile
    artefact. These are absolute shares, chosen against known places, and the
    deciles are reported as evidence rather than used as the rule."""
    for v in (CORPORATE_OFFICE_AREA_SHARE, CORPORATE_JOBS_OFFICE_SHARE,
              RETAIL_AREA_SHARE, RETAIL_JOBS_SHARE, INDUSTRIAL_FACTORY_AREA_SHARE):
        assert 0.0 < v < 1.0
    assert CORPORATE_JOBS_FLOOR >= 1_000


def test_label_order_puts_industrial_before_retail_mixed():
    assert LABEL_ORDER == ("corporate", "industrial", "retail_mixed", "residential")


# -------------------------------------------------------- the write contract

def test_migration_declares_every_character_column():
    text = MIGRATION.read_text()
    for c in CHARACTER_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {c} " in text, f"021 never adds {c}"


def test_guard_refuses_a_column_another_module_owns():
    with pytest.raises(RuntimeError, match="clobber"):
        _guard([*CHARACTER_COLUMNS, "gap_score"])
    with pytest.raises(RuntimeError, match="clobber"):
        _guard(["jobs_400m"])                 # address_access owns this one
    _guard(CHARACTER_COLUMNS)                 # the real list is clean


def test_write_refuses_a_partial_frame_rather_than_blanking_columns(warehouse):
    """RESET-then-UPDATE means a frame missing a column would leave it NULL
    forever. Refuse instead."""
    partial = pd.DataFrame({"address_id": ["a"], "borough": ["MN"],
                            "retail_area_400m": [1.0]})
    with pytest.raises(RuntimeError, match="missing"):
        write_character(warehouse, partial, ["MN"])


def test_write_is_update_only_and_never_inserts_or_deletes(warehouse):
    _labels(warehouse, [_row("a", res=1_000_000), _row("b", res=1_000_000, borough="BK")])
    before = warehouse.execute("SELECT count(*) FROM analysis.address").fetchone()[0]
    frame = pd.DataFrame([{
        "address_id": "a", "borough": "MN",
        "retail_area_400m": 1.0, "office_area_400m": 2.0, "res_area_400m": 3.0,
        "factory_area_400m": 4.0, "bldg_area_400m": 10.0,
        "jobs_retail_400m": 1, "jobs_office_400m": 2, "jobs_other_400m": 3,
        "character_radius_m": 400.0, "character_pluto_version": "24v4",
        "character_jobs_vintage": 2023, "character_run_at": dt.datetime(2026, 9, 13),
    }])
    n = write_character(warehouse, frame, ["MN"])
    assert n == 1
    assert warehouse.execute("SELECT count(*) FROM analysis.address").fetchone()[0] == before
    # Out-of-scope rows are untouched; in-scope rows not in the frame are RESET.
    got = warehouse.execute(
        "SELECT address_id, office_area_400m FROM analysis.address ORDER BY address_id"
    ).fetchall()
    assert got == [("a", 2.0), ("b", 0.0)]    # 'b' is BK, outside the MN reset


def test_write_resets_in_scope_rows_the_frame_does_not_carry(warehouse):
    _labels(warehouse, [_row("a", res=1_000_000), _row("z", res=1_000_000)])
    frame = pd.DataFrame([{
        "address_id": "a", "borough": "MN",
        "retail_area_400m": 1.0, "office_area_400m": 2.0, "res_area_400m": 3.0,
        "factory_area_400m": 4.0, "bldg_area_400m": 10.0,
        "jobs_retail_400m": 1, "jobs_office_400m": 2, "jobs_other_400m": 3,
        "character_radius_m": 400.0, "character_pluto_version": "24v4",
        "character_jobs_vintage": 2023, "character_run_at": dt.datetime(2026, 9, 13),
    }])
    write_character(warehouse, frame, ["MN"])
    z = warehouse.execute(
        "SELECT character_run_at FROM analysis.address WHERE address_id = 'z'").fetchone()[0]
    assert z is None, "an address that left scope kept the previous run's number"


# --------------------------------------------------- the real warehouse, if any

WAREHOUSE = pathlib.Path(locidb.DEFAULT_PATH)


@pytest.mark.skipif(not WAREHOUSE.exists(), reason="no data/loci.duckdb on this clone")
def test_every_mn_bk_address_carries_a_label_on_the_real_warehouse():
    """0 NULL labels over the whole screen scope, and the three sector columns
    sum EXACTLY to jobs_400m -- the cross-check that this sweep and
    `loci address-access`'s sweep saw the same graph at the same radius."""
    con = locidb.connect(WAREHOUSE, read_only=True)
    try:
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'analysis' AND table_name = 'address'").fetchall()}
        if "character_run_at" not in cols:
            pytest.skip("migration 021 has not been applied to this warehouse")
        built = con.execute(
            "SELECT count(*) FROM analysis.address WHERE character_run_at IS NOT NULL"
        ).fetchone()[0]
        if not built:
            pytest.skip("`loci address-character build` has not been run")
        bad = con.execute("""
            SELECT count(*) FROM analysis.address_character
            WHERE character_run_at IS NOT NULL
              AND (character IS NULL OR character_intensity IS NULL
                   OR character_intensity < 0 OR character_intensity > 1)
        """).fetchone()[0]
        assert bad == 0
        mismatch = con.execute("""
            SELECT count(*) FROM analysis.address
            WHERE character_run_at IS NOT NULL AND jobs_400m IS NOT NULL
              AND jobs_retail_400m + jobs_office_400m + jobs_other_400m <> jobs_400m
        """).fetchone()[0]
        assert mismatch == 0
    finally:
        con.close()
