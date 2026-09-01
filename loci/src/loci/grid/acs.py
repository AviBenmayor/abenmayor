"""ACS 5-year demographics, dasymetrically interpolated onto the H3 grid (GTM-24).

PLUTO is the ancillary surface: each residential lot knows its 2020 census tract
(bct2020) AND its H3 cell, so a tract's ACS counts are distributed to hexes in
proportion to each hex's share of that tract's residential units — exact, no
polygon intersection. Plain areal weighting would spread population across parks
and rail yards; unit-weighting puts it where the housing is (CONTEXT.md §4.2).

Extensive vars (population, households) are apportioned by unit share; intensive
vars (median income, renter share) are unit-share-weighted averages of the
overlapping tracts. ACS margins of error are propagated, not dropped (§7.8):
for an apportioned sum, MOE = sqrt(sum (w_t * MOE_t)^2).

Income interpolation is an approximation — a unit-weighted mean of tract MEDIAN
incomes is not itself a true median. Documented, acceptable for a control.
"""
from __future__ import annotations

import collections
import math
import os
import pathlib

import h3
import pandas as pd
import requests

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PLUTO_CSV = REPO_ROOT / "data" / "raw" / "pluto.csv"
ACS_YEAR = 2023
BORO_COUNTY = {"1": "061", "2": "005", "3": "047", "4": "081", "5": "085"}
GETVARS = ["B01003_001E", "B01003_001M", "B11001_001E", "B11001_001M",
           "B19013_001E", "B19013_001M", "B25003_001E", "B25003_003E"]


def _census_key() -> str:
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CENSUS_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("CENSUS_API_KEY", "")


def _clean(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x <= -666666 else x   # ACS null/jam sentinels


def fetch_acs(year: int = ACS_YEAR) -> dict[str, dict]:
    key = _census_key()
    out: dict[str, dict] = {}
    for county in BORO_COUNTY.values():
        resp = requests.get(
            f"https://api.census.gov/data/{year}/acs/acs5",
            params={"get": ",".join(GETVARS), "for": "tract:*",
                    "in": f"state:36 county:{county}", "key": key},
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        head = data[0]
        for row in data[1:]:
            rec = dict(zip(head, row))
            geoid = rec["state"] + rec["county"] + rec["tract"]
            out[geoid] = rec
    return out


def _tract_hex_weights(con, pluto_csv: pathlib.Path) -> pd.DataFrame:
    lots = con.execute(
        """
        SELECT borocode, bct2020,
               TRY_CAST(latitude AS DOUBLE) lat, TRY_CAST(longitude AS DOUBLE) lon,
               TRY_CAST(unitsres AS DOUBLE) u
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE bct2020 IS NOT NULL AND TRY_CAST(unitsres AS DOUBLE) > 0
          AND TRY_CAST(latitude AS DOUBLE) IS NOT NULL
        """, [str(pluto_csv)]).df()
    lots["county"] = lots["borocode"].map(BORO_COUNTY)
    lots = lots[lots["county"].notna()].copy()
    lots["geoid"] = "36" + lots["county"] + lots["bct2020"].str[1:].str.zfill(6)
    lots["h3_index"] = [h3.latlng_to_cell(la, lo, 9) for la, lo in zip(lots.lat, lots.lon)]

    hexes = {r[0] for r in con.execute("SELECT h3_index FROM analysis.hex").fetchall()}
    th = lots.groupby(["geoid", "h3_index"])["u"].sum().reset_index()
    th = th[th["h3_index"].isin(hexes)]
    tot = th.groupby("geoid")["u"].sum().rename("tot").reset_index()
    th = th.merge(tot, on="geoid")
    th["w"] = th["u"] / th["tot"]
    return th


def build_acs(con, pluto_csv: pathlib.Path | str = PLUTO_CSV, year: int = ACS_YEAR) -> int:
    th = _tract_hex_weights(con, pathlib.Path(pluto_csv))
    acs = fetch_acs(year)

    agg = collections.defaultdict(lambda: dict(
        pop=0.0, pop_m2=0.0, hh=0.0, hh_m2=0.0,
        inc_num=0.0, inc_m_num=0.0, inc_w=0.0, rent_num=0.0, rent_den=0.0))
    for r in th.itertuples(index=False):
        rec = acs.get(r.geoid)
        if not rec:
            continue
        w, a = r.w, agg[r.h3_index]
        pop, pm = _clean(rec["B01003_001E"]), _clean(rec["B01003_001M"])
        hh, hm = _clean(rec["B11001_001E"]), _clean(rec["B11001_001M"])
        inc, im = _clean(rec["B19013_001E"]), _clean(rec["B19013_001M"])
        occ, rent = _clean(rec["B25003_001E"]), _clean(rec["B25003_003E"])
        if pop is not None: a["pop"] += w * pop
        if pm is not None: a["pop_m2"] += (w * pm) ** 2
        if hh is not None: a["hh"] += w * hh
        if hm is not None: a["hh_m2"] += (w * hm) ** 2
        if inc is not None:
            a["inc_num"] += w * inc; a["inc_w"] += w
            if im is not None: a["inc_m_num"] += w * im
        if occ: a["rent_den"] += w * occ
        if rent is not None: a["rent_num"] += w * rent

    rows = []
    for h, a in agg.items():
        inc = a["inc_num"] / a["inc_w"] if a["inc_w"] > 0 else None
        inc_m = a["inc_m_num"] / a["inc_w"] if a["inc_w"] > 0 else None
        rent = a["rent_num"] / a["rent_den"] if a["rent_den"] > 0 else None
        rows.append((h, year, a["pop"], math.sqrt(a["pop_m2"]), a["hh"],
                     math.sqrt(a["hh_m2"]), inc, inc_m, rent))
    df = pd.DataFrame(rows, columns=[
        "h3_index", "acs_year", "population", "population_moe", "households",
        "households_moe", "median_hh_income", "median_hh_income_moe", "renter_share"])

    con.execute("DELETE FROM analysis.hex_demographics WHERE acs_year = ?", [year])
    con.register("_acs", df)
    con.execute("""
        INSERT INTO analysis.hex_demographics
        SELECT h3_index, acs_year, population, population_moe, households, households_moe,
               median_hh_income, median_hh_income_moe, renter_share FROM _acs
    """)
    con.unregister("_acs")
    return len(df)
