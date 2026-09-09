"""Address-level ACS demographics (D56): income, tenure, and vehicle
ownership per residential PLUTO lot, TAKEN DIRECTLY from the lot's 2020
census tract -- no apportionment. A PLUTO tax lot sits in exactly one
census tract, unlike the H3 hex grid (grid/acs.py), where a hex can
straddle several tracts and unit-share (dasymetric) weighting is required.
Direct assignment is strictly simpler and loses nothing: there is nothing
to apportion when the geography is 1:1.

Tract assignment -- the cheapest correct path, not a spatial join
--------------------------------------------------------------------------
PLUTO's own `bct2020` column (2020 census tract, DCP-computed) already sits
on every tax lot; it is the exact field grid/acs.py's `_tract_hex_weights`
already trusts to interpolate demographics onto hexes. Since
`address_id` IS the tax lot's BBL for every lot that has one
(sources/cities/nyc/addresses.py), joining address -> tract is a lookup on
BBL against the raw PLUTO extract, not a point-in-polygon join: no TIGER
shapefile download, no `spatial` extension call needed here at all.

Measured coverage (2026-09-09, data/raw/pluto.csv, all 5 boroughs, the same
UnitsRes > 0 + valid-lat/lon filter addresses.py applies): 767,337
residential lots, every one with a non-blank, non-colliding BBL, and all
but 6 (99.9992%) with a non-null `bct2020`. The 6 addresses with no tract
get NULL demographics, never dropped -- they still appear in
analysis.address_demographics with tract_geoid IS NULL.

ACS values
--------------------------------------------------------------------------
Reuses grid.acs.fetch_acs's cache-first tract-level ACS pull
(data/raw/acs/tracts_2023.json already carries every variable this module
needs -- B01003, B11001, B19013, B25003, B08201, B25044 for income/tenure/
vehicles, plus B01002, B01001, B03002, B15003, B25010, B11016 for age, race,
education and household size -- so this module makes no new Census API call),
and grid.acs's OWN definitions of every derived measure: `SHARE_SPECS` and
`INTENSIVE_SPECS` (which cells make which column), `_sum_cells` (the handbook
sum rule within a tract) and `_moe_proportion` (the handbook derived-proportion
MOE). They are imported, never copied: the hex table and this table therefore
cannot define `college_share` (or any other measure) two different ways, and
adding a measure to grid/acs.py adds it here for free.

Because there is no apportionment, the "sum-of-squares across tracts" step in
grid/acs.py's `build_acs` does not apply here: each address's numerator and
denominator MOEs ARE the tract's own MOEs, taken as-is. Nor does the hex
table's "a unit-weighted mean of tract medians is not a median" caveat -- for
median_hh_income, median_age and avg_hh_size this table holds the tract's own
published figure, not a weighted mean of several tracts'. This table is
strictly LESS modelled than analysis.hex_demographics, which is why D56 made
it the canonical demographic carrier for the address screen.

THE canonical demographic carrier (D38/D56)
--------------------------------------------------------------------------
analysis.address_demographics is the ONE address-grain demographic table.
`analysis.address_gaps` used to carry a parallel copy of all 36 measures,
joined by CONTAINING H3 HEX (sql/008, first version) -- so the same address
had two different median_hh_income values, one tract-direct and one doubly
modelled. That copy is removed; model/address_gaps.py joins no demographics
at all now and keeps only `h3_index` so an address can still be rolled back
up to the grid. Anything wanting a demographic about an address joins THIS
table on address_id.

CAVEAT THE DATABASE CANNOT ENFORCE -- do not SUM population/households
--------------------------------------------------------------------------
Every address in the same tract carries that tract's FULL population and
household count (this is a per-address ATTRIBUTE lookup, not an
apportionment). Summing `population` or `households` over more than one
address is an N-times overcount, N being the number of addresses sharing
that tract -- exactly the double-count failure mode CLAUDE.md warns about,
just at address grain instead of edge-mirroring. `median_hh_income`,
`renter_share`, `zero_vehicle_*_share` and their MOEs are fine to read
per-address or to take medians/means-of-medians over, because they are
already tract-level rates/medians repeated verbatim, not counts. If a
population TOTAL is needed at some aggregate (NTA, borough, city), get it
from analysis.hex_demographics (apportioned) or straight from ACS by
tract -- never by summing this table's population column across addresses.
"""
from __future__ import annotations

import math
import pathlib

import pandas as pd

from loci.grid.acs import (
    ACS_YEAR,
    BORO_COUNTY,
    INTENSIVE_SPECS,
    PLUTO_CSV,
    SHARE_SPECS,
    _clean,
    _moe_proportion,
    _sum_cells,
    fetch_acs,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# Columns this table carries -- the drift test (tests/test_address_demographics.py)
# asserts analysis.address_demographics' column list matches this constant, so
# an edit to one without the other fails loudly instead of silently drifting.
#
# The 2026-09-09 age / race / education / household-size block is NOT written
# out by hand: it is generated from grid/acs.py's own INTENSIVE_SPECS and
# SHARE_SPECS, the same two dicts build_acs drives the hex table from. Adding
# a measure to grid/acs.py therefore adds it here automatically, and the drift
# test (tests/test_address_gaps_demographics.py) asserts every
# hex_demographics measure has an address_demographics twin -- so a demographic
# can no longer land on the hex grid alone (D38/D56).
ADDRESS_DEMOGRAPHICS_MEASURES: tuple[str, ...] = (
    "population",
    "households",
    "median_hh_income",
    "renter_share",
    "zero_vehicle_hh_share",
    "zero_vehicle_owner_share",
    "zero_vehicle_renter_share",
    *INTENSIVE_SPECS,          # median_age, avg_hh_size
    *SHARE_SPECS,              # under_18_share ... one_person_hh_share
)

ADDRESS_DEMOGRAPHICS_COLUMNS = [
    "address_id", "bbl", "tract_geoid", "acs_year",
    *[c for m in ADDRESS_DEMOGRAPHICS_MEASURES for c in (m, f"{m}_moe")],
]


def load_bbl_tract_map(pluto_csv: pathlib.Path | str = PLUTO_CSV) -> pd.DataFrame:
    """BBL -> 2020 census tract GEOID, straight off the raw PLUTO extract.

    Same construction grid/acs.py's `_tract_hex_weights` uses for the hex
    table: county from borocode (BORO_COUNTY), tract from `bct2020` with its
    leading borough digit stripped and zero-padded to 6. Returns one row per
    BBL with a non-null bct2020; a BBL missing from the result has no tract
    (caller must left-join and expect NaN, not drop).
    """
    lots = pd.read_csv(
        pluto_csv, dtype=str,
        usecols=["BBL", "borocode", "bct2020"],
    )
    lots = lots.rename(columns={"BBL": "bbl"})
    lots = lots[lots["bct2020"].notna() & (lots["bct2020"] != "")]
    lots["county"] = lots["borocode"].map(BORO_COUNTY)
    lots = lots[lots["county"].notna()].copy()
    lots["tract_geoid"] = "36" + lots["county"] + lots["bct2020"].str[1:].str.zfill(6)
    lots = lots.drop_duplicates(subset="bbl")
    return lots[["bbl", "tract_geoid"]]


def _cross_check_b25044_vs_b25003(acs: dict[str, dict], year: int) -> None:
    """Same fail-loud sanity check grid/acs.py's `build_acs` runs before
    trusting a pull: B25044's owner+renter total should reconcile with
    B25003's total occupied-unit count for the same tract. A material
    aggregate mismatch means a Census cell index is wrong, not that the data
    is noisy -- this module must raise rather than silently compute wrong
    shares from a bad pull, independent of whether grid/acs.py has already
    run this cycle."""
    diffs, denom = [], 0.0
    for rec in acs.values():
        b25003_tot = _clean(rec.get("B25003_001E"))
        b25044_tot = _clean(rec.get("B25044_001E"))
        b25044_own = _clean(rec.get("B25044_002E"))
        b25044_rent = _clean(rec.get("B25044_009E"))
        if None in (b25003_tot, b25044_tot, b25044_own, b25044_rent):
            continue
        diffs.append(abs(b25044_tot - b25003_tot))
        diffs.append(abs(b25044_tot - (b25044_own + b25044_rent)))
        denom += b25003_tot
    if denom > 0 and (sum(diffs) / denom) > 0.02:
        raise RuntimeError(
            f"B25044/B25003 tract-total cross-check failed for ACS {year} 5-year "
            "-- re-verify cell indices before trusting this pull (see grid/acs.py's "
            "identical check)."
        )


def _cross_check_b01001_vs_b01003(acs: dict[str, dict], year: int) -> None:
    """B01001 (sex by age) and B01003 (total population) are two different ACS
    tables that must report the SAME tract population. If they do not, an age
    cell index is wrong or a GETVARS chunk merged badly -- either way the age-band
    shares would be silently mis-normalised. Raise rather than ingest a silent
    wrong number. Mirrors the identical check in grid/acs.py's build_acs, run
    here too so this module is safe to call whether or not `loci acs` ran first.
    """
    diffs, denom = [], 0.0
    for rec in acs.values():
        a = _clean(rec.get("B01003_001E"))
        b = _clean(rec.get("B01001_001E"))
        if a is None or b is None:
            continue
        diffs.append(abs(b - a))
        denom += a
    if denom > 0 and (sum(diffs) / denom) > 0.02:
        raise RuntimeError(
            f"B01001/B01003 tract-population cross-check failed for ACS {year} "
            "5-year -- re-verify the B01001 cell indices before trusting this pull "
            "(see grid/acs.py's identical check)."
        )


def _tract_row_stats(rec: dict) -> dict:
    """Direct (unapportioned) per-tract stats: the tract's own E/M cells,
    with the three proportion shares (renter, zero-vehicle overall,
    zero-vehicle by tenure) derived via the ACS handbook formula. No
    weighting, no RSS across tracts -- an address sits in exactly one
    tract, so this IS the address's value."""
    pop, pop_m = _clean(rec.get("B01003_001E")), _clean(rec.get("B01003_001M"))
    hh, hh_m = _clean(rec.get("B11001_001E")), _clean(rec.get("B11001_001M"))
    inc, inc_m = _clean(rec.get("B19013_001E")), _clean(rec.get("B19013_001M"))

    occ, occ_m = _clean(rec.get("B25003_001E")), _clean(rec.get("B25003_001M"))
    rent, rent_m = _clean(rec.get("B25003_003E")), _clean(rec.get("B25003_003M"))
    renter_share = rent / occ if (occ and occ > 0 and rent is not None) else None
    renter_share_moe = _moe_proportion(rent, rent_m, occ, occ_m) if occ else None

    veh_den, veh_den_m = _clean(rec.get("B08201_001E")), _clean(rec.get("B08201_001M"))
    veh0, veh0_m = _clean(rec.get("B08201_002E")), _clean(rec.get("B08201_002M"))
    zv_hh = veh0 / veh_den if (veh_den and veh_den > 0 and veh0 is not None) else None
    zv_hh_moe = _moe_proportion(veh0, veh0_m, veh_den, veh_den_m) if veh_den else None

    own_den, own_den_m = _clean(rec.get("B25044_002E")), _clean(rec.get("B25044_002M"))
    own0, own0_m = _clean(rec.get("B25044_003E")), _clean(rec.get("B25044_003M"))
    zv_own = own0 / own_den if (own_den and own_den > 0 and own0 is not None) else None
    zv_own_moe = _moe_proportion(own0, own0_m, own_den, own_den_m) if own_den else None

    rt_den, rt_den_m = _clean(rec.get("B25044_009E")), _clean(rec.get("B25044_009M"))
    rt0, rt0_m = _clean(rec.get("B25044_010E")), _clean(rec.get("B25044_010M"))
    zv_rt = rt0 / rt_den if (rt_den and rt_den > 0 and rt0 is not None) else None
    zv_rt_moe = _moe_proportion(rt0, rt0_m, rt_den, rt_den_m) if rt_den else None

    out = {
        "population": pop, "population_moe": pop_m,
        "households": hh, "households_moe": hh_m,
        "median_hh_income": inc, "median_hh_income_moe": inc_m,
        "renter_share": renter_share, "renter_share_moe": renter_share_moe,
        "zero_vehicle_hh_share": zv_hh, "zero_vehicle_hh_share_moe": zv_hh_moe,
        "zero_vehicle_owner_share": zv_own, "zero_vehicle_owner_share_moe": zv_own_moe,
        "zero_vehicle_renter_share": zv_rt, "zero_vehicle_renter_share_moe": zv_rt_moe,
    }

    # ---- age / race / education / household size (2026-09-09) --------------
    # INTENSIVE fields (median_age, avg_hh_size): the tract's own median or
    # average, and its own MOE, taken verbatim. grid/acs.py has to take a
    # unit-share-weighted MEAN of tract medians because a hex straddles
    # tracts; an address does not, so the "a mean of medians is not a median"
    # approximation that the hex table carries simply does not arise here.
    # This is the tract's published median, full stop.
    for col, stem in INTENSIVE_SPECS.items():
        out[col] = _clean(rec.get(stem + "E"))
        out[f"{col}_moe"] = _clean(rec.get(stem + "M"))

    # SHARE fields: numerator cells summed WITHIN the tract by the ACS
    # handbook sum rule (`_sum_cells`: estimates add, MOEs root-sum-square),
    # divided by the denominator cell from the SAME table, with the handbook's
    # derived-proportion MOE (`_moe_proportion`). Identical arithmetic to
    # grid/acs.py's SHARE_SPECS loop minus the across-tract apportionment step,
    # and driven by the same SHARE_SPECS dict so the two cannot drift.
    for col, (num_cells, den_cell) in SHARE_SPECS.items():
        n_est, n_moe = _sum_cells(rec, num_cells)
        d_est, d_moe = _sum_cells(rec, (den_cell,))
        if d_est and d_est > 0 and n_est is not None:
            out[col] = n_est / d_est
            out[f"{col}_moe"] = _moe_proportion(n_est, n_moe, d_est, d_moe)
        else:
            out[col] = None
            out[f"{col}_moe"] = None

    return out


def build_address_demographics(
    con, addresses_df: pd.DataFrame,
    year: int = ACS_YEAR, pluto_csv: pathlib.Path | str = PLUTO_CSV,
) -> pd.DataFrame:
    """addresses_df: must carry `address_id`, `bbl` (sources/cities/nyc/addresses.py's
    output, concatenated across boroughs). Returns one row per address_id,
    every column in ADDRESS_DEMOGRAPHICS_COLUMNS, ready for
    `write_address_demographics`. Addresses whose BBL has no tract (blank
    BBL, or a lot missing bct2020) get tract_geoid + every demographic
    column as NULL/NaN -- never dropped from the returned frame.
    """
    acs = fetch_acs(year)
    _cross_check_b25044_vs_b25003(acs, year)
    _cross_check_b01001_vs_b01003(acs, year)

    tract_map = load_bbl_tract_map(pluto_csv)
    merged = addresses_df[["address_id", "bbl"]].merge(tract_map, on="bbl", how="left")

    # Compute each distinct tract's stats once, not once per address --
    # NYC has ~767k addresses over ~2,300 tracts.
    stats_by_tract = {
        geoid: _tract_row_stats(acs[geoid])
        for geoid in merged["tract_geoid"].dropna().unique()
        if geoid in acs
    }
    stats_df = pd.DataFrame.from_dict(stats_by_tract, orient="index")
    stats_df.index.name = "tract_geoid"
    stats_df = stats_df.reset_index()

    out = merged.merge(stats_df, on="tract_geoid", how="left")
    out["acs_year"] = year
    return out[ADDRESS_DEMOGRAPHICS_COLUMNS]


def write_address_demographics(con, df: pd.DataFrame, year: int = ACS_YEAR) -> int:
    con.execute("DELETE FROM analysis.address_demographics WHERE acs_year = ?", [year])
    con.register("_addr_demo", df)
    cols = ", ".join(ADDRESS_DEMOGRAPHICS_COLUMNS)
    con.execute(f"INSERT INTO analysis.address_demographics ({cols}) SELECT {cols} FROM _addr_demo")
    con.unregister("_addr_demo")
    return len(df)


def summarize(df: pd.DataFrame, addresses_df: pd.DataFrame,
              income_threshold: float | None = None) -> dict:
    """Sanity numbers for the CLI report. `addresses_df` must carry `borough`
    (added by the caller from sources/cities/nyc/addresses.BOROCODE loop),
    joined on address_id, so the MN/BK-vs-citywide comparison uses the same
    universe the table was built from."""
    merged = df.merge(addresses_df[["address_id", "borough"]], on="address_id", how="left")
    n = len(merged)
    n_tract = merged["tract_geoid"].notna().sum()

    mnbk = merged[merged["borough"].isin(["MN", "BK"])]
    out = {
        "n_addresses": n,
        "n_with_tract": int(n_tract),
        "tract_assignment_rate": n_tract / n if n else 0.0,
        "citywide_median_income": merged["median_hh_income"].median(),
        "mnbk_median_income": mnbk["median_hh_income"].median(),
        "citywide_median_zero_vehicle_hh_share": merged["zero_vehicle_hh_share"].median(),
        "mnbk_median_zero_vehicle_hh_share": mnbk["zero_vehicle_hh_share"].median(),
    }

    inc = merged["median_hh_income"]
    moe = merged["median_hh_income_moe"]
    valid = inc.notna() & moe.notna() & (inc != 0)
    out["median_income_moe_share"] = (moe[valid] / inc[valid]).median() if valid.any() else None

    if income_threshold is not None:
        within = valid & ((inc - income_threshold).abs() <= moe)
        out["income_threshold"] = income_threshold
        out["share_within_one_moe_of_threshold"] = within[valid].mean() if valid.any() else None

    return out
