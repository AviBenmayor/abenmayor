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
    CHARACTER_CAVEAT,
    CHARACTER_COLUMNS,
    CHARACTER_COPY,
    COMMERCIAL_DISTRICT_PREFIXES,
    COMMERCIAL_OVERLAY_MIN_LOTS,
    COMMERCIAL_OVERLAY_PREFIXES,
    COMMERCIAL_OVERLAY_RADIUS_M,
    CORPORATE_JOBS_FLOOR,
    CORPORATE_JOBS_OFFICE_SHARE,
    CORPORATE_OFFICE_AREA_SHARE,
    INDUSTRIAL_FACTORY_AREA_SHARE,
    INSTITUTIONAL_BLDGCLASS_PREFIXES,
    LABEL_ORDER,
    MIN_NTA_ADDRESSES,
    NON_NEIGHBOURHOOD_NTA_SUFFIX,
    OFFICE_FACING_SECTORS,
    OTHER_SECTORS,
    RETAIL_AREA_SHARE,
    RETAIL_FACING_SECTORS,
    RETAIL_INDEX_OVERLAY_SHARE_FULL,
    RETAIL_JOBS_FLOOR,
    RETAIL_JOBS_SHARE,
    TRANSIT_AM_PM_NOTE,
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
        "bldgarea,unitsres,version,zonedist1,overlay1,overlay2,bldgclass,landuse\n"
        # a rowhouse in an R6 district with a C1-3 overlay -- the mapped
        # ground-floor-retail instrument this measure is looking for
        "1000010001,40.7100,-74.0100,0,0,4000,0,4000,4,24v4,R6,C1-3,,C0,01\n"
        # an office tower in C5-3, no overlay, UnitsRes 0
        "1000010002,40.7110,-74.0110,20000,900000,0,0,950000,0,24v4,C5-3,,,O4,05\n"
        # a factory in M1-2
        "3000010003,40.6600,-74.0200,0,0,0,120000,130000,0,24v4,M1-2,,,F1,06\n"
        # outside the bbox
        "5000010004,40.5800,-74.1500,0,0,3000,0,3000,3,24v4,R3-2,,,A1,01\n")
    return p


def _institution_pluto(tmp_path: pathlib.Path) -> pathlib.Path:
    """A VA-hospital-shaped lot (BldgClass I, LandUse 08, a large OfficeArea)
    beside a genuine office tower with the same OfficeArea, plus a school, a
    church and a museum. MapPLUTO books all of their floor area as OfficeArea;
    only the tower is a business district."""
    p = tmp_path / "pluto_inst.csv"
    p.write_text(
        "BBL,latitude,longitude,retailarea,officearea,resarea,factryarea,"
        "bldgarea,unitsres,version,zonedist1,overlay1,overlay2,bldgclass,landuse\n"
        "3000010001,40.6200,-74.0300,0,500000,0,0,500000,0,24v4,R6,,,I1,08\n"
        "3000010002,40.6210,-74.0310,0,500000,0,0,500000,0,24v4,C6-2,,,O4,05\n"
        "3000010003,40.6220,-74.0320,0,80000,0,0,80000,0,24v4,R6,,,W2,08\n"
        "3000010004,40.6230,-74.0330,0,40000,0,0,40000,0,24v4,R6,,,M1,08\n"
        "3000010005,40.6240,-74.0340,0,60000,0,0,60000,0,24v4,R8,,,P2,08\n")
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


# ---------------------------------------------------- the zoning route (D82)

def test_a_c1_overlay_on_a_residential_district_is_a_commercial_lot(tmp_path):
    """The rowhouse is R6 -- residential -- with a C1-3 OVERLAY, which is the
    instrument New York uses to permit a shop on the ground floor of a
    residential street. The zoning witness exists because PLUTO's RetailArea
    does not see that shop and LODES does not see its two employees."""
    con = duckdb.connect()
    lots = load_lot_points(con, (-74.10, 40.60, -73.90, 40.80),
                           pluto_csv=_tiny_pluto(tmp_path)).set_index("bbl")
    assert lots.loc["1000010001", "is_commercial"] == 1     # R6 + C1-3 overlay
    assert lots.loc["1000010002", "is_commercial"] == 1     # C5-3 district
    assert lots.loc["3000010003", "is_commercial"] == 0     # M1-2 is not retail


def test_the_commercial_test_reads_overlays_and_the_named_districts_only():
    """C3 (waterfront recreation) and C7 (amusement) are deliberately absent:
    neither is a daily-needs retail street, and C7 would light up the Coney
    Island Bowery as a shopping corridor."""
    assert COMMERCIAL_OVERLAY_PREFIXES == ("C1-", "C2-")
    assert set(COMMERCIAL_DISTRICT_PREFIXES) == {"C1", "C2", "C4", "C5", "C6", "C8"}
    assert "C3" not in COMMERCIAL_DISTRICT_PREFIXES
    assert "C7" not in COMMERCIAL_DISTRICT_PREFIXES


def test_the_overlay_count_radius_is_the_block_not_the_walk():
    """100 m is 'on or beside this block'. It is a SECOND sweep of the same
    engine at a second radius, not a straight-line buffer -- and it is a
    quarter of the 400 m the other columns use, so the two must not be
    confused."""
    assert COMMERCIAL_OVERLAY_RADIUS_M == 100.0
    assert COMMERCIAL_OVERLAY_MIN_LOTS == 20


# -------------------------------------- the institutional exclusion (D82)

def test_office_area_excludes_hospitals_schools_churches_and_museums(tmp_path):
    """THE Bay Ridge fix. MapPLUTO books the Brooklyn VA Medical Center's floor
    area as OfficeArea, which gave Bay Ridge 47 'corporate' addresses and East
    Flatbush-Rugby 134. A hospital campus is a weekday daytime population and is
    not a central business district."""
    con = duckdb.connect()
    lots = load_lot_points(con, (-74.10, 40.60, -73.90, 40.80),
                           pluto_csv=_institution_pluto(tmp_path)).set_index("bbl")
    # the hospital, the school, the church and the museum contribute nothing...
    for bbl in ("3000010001", "3000010003", "3000010004", "3000010005"):
        assert lots.loc[bbl, "office_area"] == 0
        assert lots.loc[bbl, "is_institutional"] == 1
    # ...while the raw column still carries them, so the exclusion is visible
    assert lots.loc["3000010001", "office_area_incl_inst"] == 500_000
    # ...and the genuine tower is untouched.
    assert lots.loc["3000010002", "office_area"] == 500_000
    assert lots.loc["3000010002", "is_institutional"] == 0
    assert lots["office_area"].sum() == 500_000
    assert lots["office_area_incl_inst"].sum() == 1_180_000


def test_the_institutional_prefixes_are_the_four_pluto_letters():
    assert INSTITUTIONAL_BLDGCLASS_PREFIXES == ("I", "M", "P", "W")


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
             "retail_area_400m", "office_area_400m", "office_area_incl_inst_400m",
             "res_area_400m", "factory_area_400m", "bldg_area_400m",
             "jobs_retail_400m", "jobs_office_400m", "jobs_other_400m",
             "commercial_overlay_100m", "commercial_lots_400m", "lots_400m",
             "character_radius_m", "character_near_radius_m",
             "character_jobs_vintage", "character_run_at")

#: Every label test needs its NTA to clear MIN_NTA_ADDRESSES or D82 suppression
#: nulls the label out from under it. `_labels` pads with this many plain
#: residential rows in the SAME NTA rather than making the threshold injectable:
#: a view generator that takes the threshold as an argument is a second place
#: the number can be wrong, and the point of these tests is the real constant.
PAD_TO = MIN_NTA_ADDRESSES + 5


def _row(address_id, *, retail=0.0, office=0.0, res=0.0, factory=0.0,
         office_incl_inst=None, j_retail=0, j_office=0, j_other=0,
         overlay=0, comm_lots=0, lots=100, built=True, borough="MN",
         nta="MN0000"):
    """One crafted analysis.address row.

    `office` is the D82 post-exclusion OfficeArea (institutional lots already
    removed) and `office_incl_inst` the raw sum; it defaults to `office`,
    so a test that does not care about hospitals gets the pre-D82 behaviour.
    `bldg` is built from the RAW office area, since BldgArea contains the
    hospital too.
    """
    office_incl_inst = office if office_incl_inst is None else office_incl_inst
    bldg = retail + office_incl_inst + res + factory
    return {
        "address_id": address_id, "borough": borough, "nta_code": nta,
        "neighborhood": nta, "lon": -73.98, "lat": 40.75, "units": 1,
        "present_count": 15, "eligible": True, "n_missing": 0,
        "reach_source": "tiers", "reach_hash": "t", "graph_version": "g",
        "run_at": dt.datetime(2026, 9, 13),
        "homes_400m": 100, "jobs_400m": j_retail + j_office + j_other,
        "retail_area_400m": retail, "office_area_400m": office,
        "office_area_incl_inst_400m": office_incl_inst,
        "res_area_400m": res, "factory_area_400m": factory,
        "bldg_area_400m": bldg,
        "jobs_retail_400m": j_retail, "jobs_office_400m": j_office,
        "jobs_other_400m": j_other,
        "commercial_overlay_100m": overlay, "commercial_lots_400m": comm_lots,
        "lots_400m": lots,
        "character_radius_m": 400.0, "character_near_radius_m": 100.0,
        "character_jobs_vintage": 2023,
        "character_run_at": dt.datetime(2026, 9, 13) if built else None,
    }


@pytest.fixture()
def warehouse():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def _insert(con, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)
    con.register("_rows", frame)
    con.execute(f"INSERT INTO analysis.address ({', '.join(ADDR_COLS)}) "
                f"SELECT {', '.join(ADDR_COLS)} FROM _rows")
    con.unregister("_rows")


def _labels(con, rows: list[dict], pad: int = PAD_TO) -> pd.DataFrame:
    """Insert `rows`, pad each NTA they touch up to `pad` addresses so D82
    suppression does not fire, and return the view's answer for `rows` ONLY."""
    padding = []
    if pad:
        for nta in dict.fromkeys(r["nta_code"] for r in rows):
            borough = next(r["borough"] for r in rows if r["nta_code"] == nta)
            padding += [_row(f"_pad_{nta}_{i}", res=1_000_000, nta=nta,
                             borough=borough)
                        for i in range(max(0, pad - sum(
                            1 for r in rows if r["nta_code"] == nta)))]
    _insert(con, rows + padding)
    ids = [r["address_id"] for r in rows]
    holes = ", ".join("?" for _ in ids)
    return con.execute(
        f"SELECT address_id, character, character_intensity, retail_index, "
        f"       suppressed, "
        f"       retail_area_share, office_area_share, factory_area_share, "
        f"       jobs_retail_share, jobs_office_share, "
        f"       commercial_overlay_share_400m "
        f"FROM analysis.address_character WHERE address_id IN ({holes}) "
        f"ORDER BY address_id", ids).fetchdf()


def test_midtown_shaped_row_is_corporate_on_floor_area(warehouse):
    # Office is 40% of the four named uses -> past CORPORATE_OFFICE_AREA_SHARE,
    # and (D82) the catchment carries CORPORATE_JOBS_FLOOR employment as well.
    out = _labels(warehouse, [_row("a", office=4_000_000, res=6_000_000,
                                   j_office=20_000, j_other=5_000)])
    assert out.loc[0, "character"] == "corporate"
    assert out.loc[0, "office_area_share"] == pytest.approx(0.4)


def test_a_hospital_campus_is_not_corporate(warehouse):
    """The Bay Ridge / East Flatbush-Rugby fix, at the label. Half the built
    floor area is a VA hospital booked as OfficeArea, and 4,000 people work
    there -- and it is not a business district. BOTH D82 corrections have to
    hold: the institutional area is out of `office_area_400m`, and the jobs
    floor now guards the floor-area route too."""
    out = _labels(warehouse, [_row("a", office=0, office_incl_inst=5_000_000,
                                   res=5_000_000, j_other=4_000)])
    assert out.loc[0, "office_area_share"] == pytest.approx(0.0)
    assert out.loc[0, "character"] != "corporate"


def test_the_jobs_floor_guards_the_floor_area_route_too(warehouse):
    """Pre-D82 the floor guarded only the payroll route, so a catchment with a
    big OfficeArea entry and no employment was corporate on the strength of an
    assessment column alone. Same floor area, employment either side of the
    floor: only the busy one is a business district."""
    empty = _labels(warehouse, [_row("a", office=4_000_000, res=6_000_000,
                                     j_office=CORPORATE_JOBS_FLOOR - 1)])
    assert empty.loc[0, "office_area_share"] >= CORPORATE_OFFICE_AREA_SHARE
    assert empty.loc[0, "character"] != "corporate"
    warehouse.execute("DELETE FROM analysis.address")
    busy = _labels(warehouse, [_row("a", office=4_000_000, res=6_000_000,
                                    j_office=CORPORATE_JOBS_FLOOR)])
    assert busy.loc[0, "character"] == "corporate"


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
    retail_mixed. D82 lowered the floor 1,000 -> 300, which is still far above
    what a corner deli and a nail salon produce."""
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


def test_a_commercial_overlay_on_the_block_is_retail_mixed_on_its_own(warehouse):
    """THE D82 OR-ROUTE. Brighton Beach Avenue, Cortelyou Road, Fulton Street
    and Pitkin Avenue all read 0.000 retail_mixed on the first build: prewar
    taxpayers fold their store area into ComArea so RetailArea is near zero,
    and thirty owner-run shops carry fewer than 300 payroll jobs. The C1/C2
    overlay mapped along the strip is the one witness that cannot be
    under-reported, and on its own it is enough."""
    out = _labels(warehouse, [_row("a", res=1_000_000, retail=10_000,
                                   j_retail=120, j_other=400,
                                   overlay=COMMERCIAL_OVERLAY_MIN_LOTS, comm_lots=22, lots=140)])
    assert out.loc[0, "retail_area_share"] < RETAIL_AREA_SHARE       # assessment says no
    assert out.loc[0, "jobs_retail_share"] < RETAIL_JOBS_SHARE       # payroll says no
    assert out.loc[0, "character"] == "retail_mixed"                 # zoning says yes


def test_no_commercial_lot_on_the_block_does_not_fire_the_zoning_route(warehouse):
    """The OR-route is a COUNT within 100 m, not the 400 m share: a side street
    four blocks from an avenue is within a five-minute walk of the overlay and
    is still not on a commercial corridor."""
    out = _labels(warehouse, [_row("a", res=1_000_000, retail=10_000,
                                   j_retail=120, j_other=400,
                                   overlay=0, comm_lots=22, lots=140)])
    assert out.loc[0, "character"] == "residential"
    # ...but the continuous measure still sees the corridor nearby.
    assert out.loc[0, "retail_index"] > 0


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
                                   res=3_500_000, j_office=30_000, j_retail=4_000,
                                   j_other=6_000)])
    assert out.loc[0, "character"] == "corporate"


def test_park_slope_shaped_row_is_residential(warehouse):
    out = _labels(warehouse, [_row("a", res=980_000, retail=20_000,
                                   j_retail=400, j_office=400, j_other=1_200)])
    assert out.loc[0, "character"] == "residential"
    # Nowhere near any threshold -> high residential intensity.
    assert out.loc[0, "character_intensity"] > 0.4


def test_intensity_is_zero_to_one_and_rises_with_distance_past_the_threshold(warehouse):
    out = _labels(warehouse, [
        # Employment past CORPORATE_JOBS_FLOOR but a MODEST office share, so the
        # intensity is read off the floor-area route rather than pinned at 1.0
        # by the payroll route.
        _row("a", office=350_001, res=649_999, j_office=5_000, j_other=5_000),
        _row("b", office=900_000, res=100_000, j_office=5_000, j_other=5_000),
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
        _row("a", office=4_000_000, res=6_000_000, j_office=9_000),
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
    """60 addresses so the NTA clears MIN_NTA_ADDRESSES: 20 corporate, 10
    retail_mixed, 30 residential. The unbuilt NTA drops out entirely -- a row
    whose sweep never ran is not a neighbourhood with no character."""
    rows = ([_row(f"a{i}", office=4_000_000, res=6_000_000, j_office=9_000,
                  nta="MN0101") for i in range(20)]
            + [_row(f"b{i}", retail=150_000, res=850_000, nta="MN0101")
               for i in range(10)]
            + [_row(f"c{i}", res=1_000_000, nta="MN0101") for i in range(30)]
            + [_row("d", res=1_000_000, nta="MN0202", built=False)])
    _labels(warehouse, rows, pad=0)
    n = warehouse.execute(
        "SELECT * FROM analysis.nta_character ORDER BY nta_code").fetchdf()
    assert list(n["nta_code"]) == ["MN0101"]                 # the unbuilt NTA drops out
    assert n.loc[0, "addresses"] == 60
    assert not bool(n.loc[0, "suppressed"])
    assert n.loc[0, "dominant_character"] == "residential"
    assert n.loc[0, "share_corporate"] == pytest.approx(20 / 60)
    assert n.loc[0, "share_retail_mixed"] == pytest.approx(10 / 60)


# ------------------------------------------------------- suppression (D82)

def test_an_nta_under_fifty_addresses_is_suppressed_not_labelled(warehouse):
    """Calvert Vaux Park holds 9 residential lots and came out 100%
    retail_mixed. That is not a finding about Calvert Vaux Park. A share over a
    denominator that small is arithmetic, not geography -- so the LABEL is
    withheld rather than quoted."""
    out = _labels(warehouse,
                  [_row(f"a{i}", retail=150_000, res=850_000, nta="MN0011")
                   for i in range(MIN_NTA_ADDRESSES - 1)], pad=0)
    assert out["suppressed"].all()
    assert out["character"].isna().all()
    assert out["character_intensity"].isna().all()
    # The MEASURES survive: only the four-way label is withheld.
    assert out["retail_index"].notna().all()
    assert (out["retail_area_share"] > 0).all()


def test_one_more_address_and_the_same_nta_is_labelled(warehouse):
    """The threshold is a real cut, not a mood: MIN_NTA_ADDRESSES either side."""
    out = _labels(warehouse,
                  [_row(f"a{i}", retail=150_000, res=850_000, nta="MN0011")
                   for i in range(MIN_NTA_ADDRESSES)], pad=0)
    assert not out["suppressed"].any()
    assert (out["character"] == "retail_mixed").all()


def test_a_park_or_cemetery_nta_is_suppressed_however_many_addresses_it_has(warehouse):
    """Green-Wood Cemetery (279 addresses), Holy Cross (272), Prospect Park
    (290) and Dyker Beach Park (256) all clear the size floor and none of them
    is a neighbourhood. The 2020 NTA code carries the type in its last two
    digits: 71-79 cemetery, 91-99 park or airport."""
    rows = ([_row(f"p{i}", retail=150_000, res=850_000, nta="BK0771")
             for i in range(80)]
            + [_row(f"q{i}", retail=150_000, res=850_000, nta="BK5591")
               for i in range(80)]
            + [_row(f"r{i}", retail=150_000, res=850_000, nta="BK0101")
               for i in range(80)])
    out = _labels(warehouse, rows, pad=0).set_index("address_id")
    assert out.loc["p0", "suppressed"] and pd.isna(out.loc["p0", "character"])
    assert out.loc["q0", "suppressed"] and pd.isna(out.loc["q0", "character"])
    # ...and an ordinary NTA in the same borough is untouched.
    assert not out.loc["r0", "suppressed"]
    assert out.loc["r0", "character"] == "retail_mixed"


def test_suppression_never_matches_on_the_name(warehouse):
    """'Park Slope', 'Borough Park', 'Sunset Park' and 'Ozone Park' are
    residential NTAs. A name rule would suppress four real neighbourhoods to
    catch polygons the CODE already identifies, so there is no name rule."""
    rows = [_row(f"a{i}", retail=150_000, res=850_000, nta="BK0602")
            for i in range(80)]
    for r in rows:
        r["neighborhood"] = "Park Slope"
    out = _labels(warehouse, rows, pad=0)
    assert not out["suppressed"].any()


def test_the_nta_roll_up_flags_a_suppressed_row_rather_than_dropping_it(warehouse):
    """A missing row is a question mark; `suppressed = true` with NULL shares is
    an answer. And the shares must be NULL, not 0 -- `ELSE 0` would report a
    cemetery as 0% corporate, 0% retail and 0% residential, which reads as a
    finding."""
    _labels(warehouse,
            ([_row(f"p{i}", retail=150_000, res=850_000, nta="BK0771")
              for i in range(80)]
             + [_row(f"r{i}", retail=150_000, res=850_000, nta="BK0101")
                for i in range(80)]), pad=0)
    n = warehouse.execute(
        "SELECT * FROM analysis.nta_character ORDER BY nta_code").fetchdf()
    assert list(n["nta_code"]) == ["BK0101", "BK0771"]
    park = n.set_index("nta_code").loc["BK0771"]
    assert bool(park["suppressed"])
    assert pd.isna(park["share_retail_mixed"])
    assert pd.isna(park["dominant_character"])
    # the continuous measure is still reported -- it is evidence, not identity
    assert park["mean_retail_index"] > 0


def test_the_suppression_suffix_rule_is_the_documented_nta_code_convention():
    assert MIN_NTA_ADDRESSES == 50
    assert NON_NEIGHBOURHOOD_NTA_SUFFIX == 70


# ------------------------------------------------- the continuous measure

def test_retail_index_is_bounded_and_is_the_max_of_the_three_witnesses(warehouse):
    out = _labels(warehouse, [
        # nothing at all
        _row("a", res=1_000_000),
        # assessment witness alone, exactly at its threshold -> 1.0
        _row("b", retail=120_000, res=880_000),
        # payroll witness alone, half-way to its threshold
        _row("c", res=1_000_000, j_retail=350, j_other=1_650),
        # zoning witness alone, half-way to a fully-commercial catchment
        _row("d", res=1_000_000, comm_lots=25, lots=200),
        # everything at once -- still capped
        _row("e", retail=500_000, res=500_000, j_retail=5_000, j_other=1_000,
             overlay=9, comm_lots=150, lots=200),
    ]).set_index("address_id")
    assert out["retail_index"].between(0.0, 1.0).all()
    assert out.loc["a", "retail_index"] == pytest.approx(0.0)
    assert out.loc["b", "retail_index"] == pytest.approx(1.0)
    assert out.loc["c", "retail_index"] == pytest.approx(0.175 / RETAIL_JOBS_SHARE)
    assert out.loc["d", "retail_index"] == pytest.approx(
        0.125 / RETAIL_INDEX_OVERLAY_SHARE_FULL)
    assert out.loc["e", "retail_index"] == pytest.approx(1.0)


def test_retail_index_ignores_a_high_job_share_below_the_floor(warehouse):
    """The same gate the label uses: a 60% retail share of 20 jobs is the
    corner deli, and the index must not read it as a shopping street."""
    out = _labels(warehouse, [_row("a", res=1_000_000, j_retail=12, j_other=8)])
    assert out.loc[0, "jobs_retail_share"] == pytest.approx(0.6)
    assert out.loc[0, "retail_index"] == pytest.approx(0.0)


def test_retail_index_is_null_only_where_the_build_never_ran(warehouse):
    out = _labels(warehouse, [_row("a", res=1_000_000, built=False),
                              _row("b", res=1_000_000)])
    got = out.set_index("address_id")["retail_index"]
    assert pd.isna(got["a"])
    assert got["b"] == pytest.approx(0.0)      # zero is an observation (D75)


# ----------------------------------------------------------- display copy

def test_character_copy_renames_corporate_for_humans_and_nothing_in_the_code():
    """The rule: the CODE renames nothing. `corporate` stays `corporate` in the
    label column, in LABEL_ORDER and in every share column; what a reader is
    shown changes in ONE place so a card and a map legend cannot drift."""
    assert set(CHARACTER_COPY) == set(LABEL_ORDER)
    assert CHARACTER_COPY["corporate"] == "weekday-office catchment"
    assert "corporate" in LABEL_ORDER          # unchanged in the code


def test_the_corporate_copy_carries_the_planners_caveat():
    """The label's plain-English reading -- 'nobody lives here' -- is the
    opposite of what the data says, so the caveat is not optional."""
    caveat = CHARACTER_CAVEAT["corporate"]
    assert "6,029" in caveat and "1,759" in caveat     # the current build
    assert "5,682" in caveat and "2,284" in caveat     # ...and what it superseded
    assert "rent" in caveat and "ground-floor supply" in caveat
    assert set(CHARACTER_CAVEAT) == set(LABEL_ORDER)


def test_the_am_pm_note_says_null_is_not_zero():
    assert "NULL" in TRANSIT_AM_PM_NOTE
    assert "not 'no morning commuters'" in TRANSIT_AM_PM_NOTE


# ------------------------------------------------------------ the thresholds

def test_the_thresholds_are_absolute_not_quantiles():
    """D34's lesson: a cut placed at the p80 of a distribution fixes the label
    rate at 20% BY CONSTRUCTION and the resulting ranking is a quantile
    artefact. These are absolute shares, chosen against known places, and the
    deciles are reported as evidence rather than used as the rule."""
    for v in (CORPORATE_OFFICE_AREA_SHARE, CORPORATE_JOBS_OFFICE_SHARE,
              RETAIL_AREA_SHARE, RETAIL_JOBS_SHARE, INDUSTRIAL_FACTORY_AREA_SHARE,
              RETAIL_INDEX_OVERLAY_SHARE_FULL):
        assert 0.0 < v < 1.0
    assert CORPORATE_JOBS_FLOOR >= 1_000


def test_the_retail_payroll_route_is_calibrated_for_outer_borough_shops():
    """D82. 1,000 retail-facing payroll jobs inside a five-minute walk is a
    MANHATTAN number: it excluded 7th Avenue Park Slope (732), Cortelyou Road
    (311) and Pitkin Avenue (93-329), all unmistakable shopping streets built
    of owner-operated shops with two or three people on the payroll. A count
    floor calibrated on Manhattan is an outer-borough erasure, not a noise
    filter."""
    assert RETAIL_JOBS_FLOOR == 300
    assert RETAIL_JOBS_SHARE == 0.35


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
    _labels(warehouse, [_row("a", res=1_000_000), _row("b", res=1_000_000, borough="BK")],
            pad=0)
    before = warehouse.execute("SELECT count(*) FROM analysis.address").fetchone()[0]
    frame = pd.DataFrame([{
        "address_id": "a", "borough": "MN",
        "retail_area_400m": 1.0, "office_area_400m": 2.0,
        "office_area_incl_inst_400m": 2.0, "res_area_400m": 3.0,
        "factory_area_400m": 4.0, "bldg_area_400m": 10.0,
        "jobs_retail_400m": 1, "jobs_office_400m": 2, "jobs_other_400m": 3,
        "commercial_overlay_100m": 0, "commercial_lots_400m": 0, "lots_400m": 5,
        "character_radius_m": 400.0, "character_near_radius_m": 100.0,
        "character_pluto_version": "24v4",
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
    _labels(warehouse, [_row("a", res=1_000_000), _row("z", res=1_000_000)], pad=0)
    frame = pd.DataFrame([{
        "address_id": "a", "borough": "MN",
        "retail_area_400m": 1.0, "office_area_400m": 2.0,
        "office_area_incl_inst_400m": 2.0, "res_area_400m": 3.0,
        "factory_area_400m": 4.0, "bldg_area_400m": 10.0,
        "jobs_retail_400m": 1, "jobs_office_400m": 2, "jobs_other_400m": 3,
        "commercial_overlay_100m": 0, "commercial_lots_400m": 0, "lots_400m": 5,
        "character_radius_m": 400.0, "character_near_radius_m": 100.0,
        "character_pluto_version": "24v4",
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
            WHERE character_run_at IS NOT NULL AND NOT suppressed
              AND (character IS NULL OR character_intensity IS NULL
                   OR character_intensity < 0 OR character_intensity > 1)
        """).fetchone()[0]
        assert bad == 0
        # D82: a suppressed address has NO label, and every built address has a
        # retail_index in [0, 1] whether suppressed or not.
        leaked = con.execute("""
            SELECT count(*) FROM analysis.address_character
            WHERE suppressed AND character IS NOT NULL
        """).fetchone()[0]
        assert leaked == 0
        idx = con.execute("""
            SELECT count(*) FROM analysis.address_character
            WHERE character_run_at IS NOT NULL
              AND (retail_index IS NULL OR retail_index < 0 OR retail_index > 1)
        """).fetchone()[0]
        assert idx == 0
        # ...and the institutional exclusion can only ever REMOVE floor area.
        raised = con.execute("""
            SELECT count(*) FROM analysis.address
            WHERE character_run_at IS NOT NULL
              AND office_area_400m > office_area_incl_inst_400m + 1
        """).fetchone()[0]
        assert raised == 0
        mismatch = con.execute("""
            SELECT count(*) FROM analysis.address
            WHERE character_run_at IS NOT NULL AND jobs_400m IS NOT NULL
              AND jobs_retail_400m + jobs_office_400m + jobs_other_400m <> jobs_400m
        """).fetchone()[0]
        assert mismatch == 0
    finally:
        con.close()
