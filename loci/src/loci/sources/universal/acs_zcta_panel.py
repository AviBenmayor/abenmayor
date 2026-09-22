"""Census ACS 5-year, ZCTA geography, MULTI-VINTAGE panel — DEMAND pillar
input for RQ-001 (regime-durability, docs/research/RQ-001-regime-durability/).
Registry id `acs_5yr` (registry.yaml; registered at `geography: tract`, but
the entry itself notes the ZCTA pull is "the same acs5 dataset, different
`for=` clause", the D68/GTM-138 convention this module follows and extends).

WHY A NEW MODULE INSTEAD OF EXTENDING density_elasticity.fetch_zcta_acs
-------------------------------------------------------------------------
`density_elasticity.py` already pulls ZCTA ACS, but only two variables
(population, median income) at exactly two vintages (2013, 2023), hard-coded
for one regression. DATA-AUDIT.md's RQ001-acs-panel-backfill ticket needs a
real multi-year panel — every available ZCTA vintage, 2011→latest, with the
fuller variable set METHOD.md's demand pillar and RQ-001's DATA-AUDIT.md
column both call for (population, income, per-capita income, age 20-34 share
inputs, bachelor's+ share inputs, occupied housing units, gross rent, workers
by place of residence) and their MOEs. That is a different shape of object
(a stacked panel, not a single-vintage join), so it gets its own adapter
rather than bending the two-variable single-purpose one. Same Census API,
same key, same `for=zip code tabulation area:*` clause and NYC-filter
convention as `density_elasticity.fetch_zcta_acs` and `grid.acs.fetch_acs` —
reused conventions, not reused code, per those modules' own "own cache file"
precedent.

VINTAGE COVERAGE, PROBED LIVE 2026-09-22
------------------------------------------
ACS 5-year ZCTA geography starts at vintage 2011 (2007-2011 window). 2009 and
2010 do NOT serve ZCTA geography — probed directly:
`api.census.gov/data/2009/acs/acs5?get=B01003_001E&for=zip+code+tabulation+area:10001`
and the 2010 equivalent both return
`400 error: unknown/unsupported geography hierarchy`; 2011 returns 200. This
matches DATA-AUDIT.md's flagged open question ("check if 2009/2010 exist") —
they do not. Latest available vintage as of this probe is 2024 (2020-2024
window); 2025 returns 404 (not yet published). `VINTAGES` below is therefore
2011..2024 inclusive, 14 vintages.

TWO GEOGRAPHY QUERY SHAPES, PROBED LIVE
------------------------------------------
- 2011-2019: `for=zip code tabulation area:*` WITH `in=state:36` scopes the
  pull to New York State ZCTAs server-side (confirmed working for all of
  2011-2019; 2019 ALSO accepts `in=state:36`, unlike the note in
  density_elasticity.py's docstring which draws the line at "2018 and
  earlier" — re-probed here and 2019 is in fact state-qualifiable).
- 2020-2024: `in=state:36` is REJECTED ("unknown/unsupported geography
  hierarchy" — confirmed for 2020, 2021, 2022, 2023, 2024). Only the
  unqualified national wildcard `zip code tabulation area:*` works; this
  module pulls it and filters client-side to the NYC ZCTA set, the same
  pattern `density_elasticity.fetch_zcta_acs` already uses for its "later
  vintages" branch.
`STATE_QUALIFIED_MAX_YEAR` records the boundary found by the probe.

THE 2020 ZCTA BOUNDARY CHANGE — FLAGGED, NOT CROSSWALKED
-----------------------------------------------------------
The 2020 5-year ACS (2016-2020 window) was the first to tabulate against
2020-vintage ZCTA5 boundaries; every vintage 2011-2019 used 2010-vintage
ZCTA5 boundaries. `zcta_geography_vintage(year)` returns 2010 or 2020
accordingly and every output row carries it. Per this task's scope, NO
crosswalk between the two boundary vintages is attempted here — a ZCTA code
that is numerically identical across the two boundary vintages is NOT
guaranteed to cover the same area (METHOD.md item 1 lists "the 2020 ZCTA
redraw" as a candidate cause of synchronized fake panel breaks). Any
downstream use MUST treat a rank/level jump exactly at the 2019→2020 vintage
seam as a suspected measurement break until checked, not as a real change.

EDUCATIONAL-ATTAINMENT TABLE RENUMBERING — VERIFIED, HANDLED
-----------------------------------------------------------------
B15003 (Educational Attainment for the Population 25 Years and Over, the
table `grid/acs.py`'s tract pull uses) does NOT exist in the 2011 ACS5
vintage — verified against `api.census.gov/data/2011/acs/acs5/variables.json`
(`B15003_001E` absent) and confirmed live (`get=B15003_001E` for 2011
returns `400 error: unknown variable 'B15003_001E'`). 2012 onward has it.
2011 alone falls back to B15002 (Sex by Educational Attainment for the
Population 25 Years and Over — present in every vintage including 2011),
which carries the same "bachelor's degree or higher" categories split by
sex; `edu_spec()` sums the male + female bachelor's-and-above cells for
2011 and uses B15003's already-sex-collapsed cells for 2012+. Every output
row carries `education_table` ("B15002" or "B15003") so a reader can see
which table's sampling/definition underlies that vintage's share, mirroring
how ZBP-SIC crosswalk points are documented rather than silently patched
over elsewhere in this project (D42).

NYC ZCTA UNIVERSE
------------------
Reused, not rebuilt: `census_cbp_national.zcta_county_crosswalk()` (2020
ZCTA↔county relationship file, already cached at
data/raw/zbp/zcta_county_rel_2020.parquet) filtered to the five NYC county
FIPS codes (36005 Bronx, 36047 Kings, 36061 New York, 36081 Queens, 36085
Richmond) gives 211 ZCTAs. This is the SAME crosswalk vintage (2020
boundaries) applied to every ACS vintage's ZIP list, including pre-2020 ones
— consistent with "flag the boundary change, don't crosswalk it": the ZCTA
CODE list used to select rows is held constant so the panel has a stable ZIP
universe to report against, while the boundary-vintage flag on each row
warns a reader that the polygon behind a given code is not constant across
the panel. Not every one of the 211 codes reports data in ACS (PO-box/
single-building ZIPs are not autonomous ZCTAs) — that is expected, not an
ingest failure, and is why `build_panel` does not require a fixed row count,
only a non-trivial fraction of the crosswalk's 211.

FAIL LOUD
---------
Every fetch raises (never returns an empty/partial frame silently) on: a
missing CENSUS_API_KEY, a non-2xx API response, an API response with zero
data rows, or an NYC-filtered result of zero rows.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import pathlib

import pandas as pd
import requests

from loci.sources.universal.census_cbp_national import zcta_county_crosswalk

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
RAW_DIR = REPO_ROOT / "data" / "raw" / "acs_zcta"
INTERIM_DIR = REPO_ROOT / "data" / "interim" / "rq001" / "acs_zcta"

FIRST_ZCTA_VINTAGE = 2011
LAST_ZCTA_VINTAGE = 2024   # verified live 2026-09-22; 2025 not yet published (404)
VINTAGES = list(range(FIRST_ZCTA_VINTAGE, LAST_ZCTA_VINTAGE + 1))

# `in=state:36` accepted through 2019; 2020+ requires the national wildcard,
# filtered client-side. Verified live for every vintage in VINTAGES.
STATE_QUALIFIED_MAX_YEAR = 2019

# The Census API rejects a `get=` list longer than 50 variables (confirmed
# live 2026-09-22: 52 variables -> `400 'get' is limited to 50 variables`,
# triggered by the 2011 B15002 branch, which is 8 numerator cells wide vs
# B15003's 4). 48 leaves headroom for the geo column the API appends. Same
# convention as grid/acs.py's MAX_GET_VARS.
MAX_GET_VARS = 48

# 2020 5-year ACS is the first vintage on 2020-boundary ZCTAs.
ZCTA_2020_BOUNDARY_MIN_YEAR = 2020

NYC_COUNTY_FIPS = {"36005", "36047", "36061", "36081", "36085"}

# Single-cell (E/M) extensive/intensive variables, output column -> Census stem.
SIMPLE_VARS: dict[str, str] = {
    "population": "B01003_001",
    "median_hh_income": "B19013_001",
    "per_capita_income": "B19301_001",
    "workers_16plus": "B08301_001",          # workers 16+, BY PLACE OF RESIDENCE
    "occupied_housing_units": "B25003_001",
    "median_gross_rent": "B25064_001",
    "age_20_34_denom": "B01001_001",         # sex-by-age table total (denominator)
}

# B01001 (sex by age) cells for "20 to 34" — 20 yrs / 21 yrs / 22-24 / 25-29 /
# 30-34, both sexes. Verified against the same cell layout grid/acs.py's
# AGE_BANDS["age_18_34"] documents (008-012 male, 032-036 female); this band
# excludes the 18-19 cells (007/031) that grid/acs.py's 18-34 band includes,
# because this task's spec is age 20-34, not 18-34.
AGE_20_34_CELLS: tuple[str, ...] = (
    "B01001_008", "B01001_009", "B01001_010", "B01001_011", "B01001_012",
    "B01001_032", "B01001_033", "B01001_034", "B01001_035", "B01001_036",
)


def edu_spec(year: int) -> dict:
    """Bachelor's-and-above table + cells for `year`. B15003 2012+, B15002
    (sex-split) for 2011 alone — see module docstring."""
    if year < 2012:
        return {
            "table": "B15002",
            "denom": "B15002_001",
            "numerator_cells": ("B15002_015", "B15002_016", "B15002_017", "B15002_018",
                                 "B15002_032", "B15002_033", "B15002_034", "B15002_035"),
        }
    return {
        "table": "B15003",
        "denom": "B15003_001",
        "numerator_cells": ("B15003_022", "B15003_023", "B15003_024", "B15003_025"),
    }


def zcta_geography_vintage(year: int) -> int:
    return 2020 if year >= ZCTA_2020_BOUNDARY_MIN_YEAR else 2010


def variables_for(year: int) -> list[str]:
    """Full E/M variable list for `year`'s API call."""
    stems = list(SIMPLE_VARS.values()) + list(AGE_20_34_CELLS)
    edu = edu_spec(year)
    stems += [edu["denom"], *edu["numerator_cells"]]
    out: list[str] = []
    for stem in stems:
        out += [f"{stem}E", f"{stem}M"]
    return out


def _census_key() -> str:
    """Same lookup order as every other Census adapter in this project:
    checked-in .env, then the environment."""
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CENSUS_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
                if key:
                    return key
    return os.environ.get("CENSUS_API_KEY", "")


def _clean(v) -> float | None:
    """ACS null/jam-value sentinel handling, same convention as grid/acs.py."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x <= -666666 else x


def _sum_cells(rec: dict, stems: tuple[str, ...]) -> tuple[float | None, float | None]:
    """(estimate, MOE) for a sum of ACS cells within one row — handbook sum
    rule: estimates add, MOEs combine as the root sum of squares. Returns
    (None, None) if every cell is null/jammed."""
    est, m2, seen = 0.0, 0.0, False
    for stem in stems:
        e = _clean(rec.get(stem + "E"))
        m = _clean(rec.get(stem + "M"))
        if e is None:
            continue
        est += e
        m2 += (m or 0.0) ** 2
        seen = True
    return (est, math.sqrt(m2)) if seen else (None, None)


def _moe_proportion(x: float | None, x_moe: float | None,
                     y: float | None, y_moe: float | None) -> float | None:
    """ACS handbook MOE for a proportion p = X/Y, X a subset of Y. Falls back
    to the conservative (additive) ratio formula when the subtraction goes
    negative — same convention as grid/acs.py's `_moe_proportion`."""
    if y is None or y <= 0 or x is None or x_moe is None or y_moe is None:
        return None
    p = x / y
    under_sqrt = x_moe ** 2 - (p ** 2) * (y_moe ** 2)
    if under_sqrt < 0:
        under_sqrt = x_moe ** 2 + (p ** 2) * (y_moe ** 2)
    return math.sqrt(under_sqrt) / y


def _raw_cache_path(year: int) -> pathlib.Path:
    return RAW_DIR / f"acs_zcta_{year}.json"


_GEO_COL = "zip code tabulation area"


def fetch_vintage_raw(year: int, *, force: bool = False, timeout: int = 120) -> list[list[str]]:
    """Cache-first raw Census API pull for one ZCTA vintage, returned in the
    API's own [header, row, row, ...] shape (cached verbatim plus metadata).

    `variables_for(year)` can exceed the API's 50-variable-per-request cap
    (2011's B15002 branch is 52) -- chunked the same way grid/acs.py's
    `fetch_acs` chunks the tract pull: one request per chunk, merged per ZCTA,
    with a hard check that every chunk returned the SAME ZCTA set (otherwise
    a merged record could be silently short a variable). Fails loud on a
    missing key, a non-2xx response, zero data rows, a chunk-set mismatch, or
    a merged record missing a requested variable."""
    cache_path = _raw_cache_path(year)
    getvars = variables_for(year)
    if not force and cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get("vars") == getvars and cached.get("year") == year:
            return cached["data"]
    key = _census_key()
    if not key:
        raise RuntimeError(
            "no CENSUS_API_KEY found (checked loci/.env and the environment). "
            "ACS ZCTA demographics must be FETCHED, never guessed or zero-filled "
            "-- set the key and re-run.")
    url = f"https://api.census.gov/data/{year}/acs/acs5"
    chunks = [getvars[i:i + MAX_GET_VARS] for i in range(0, len(getvars), MAX_GET_VARS)]
    merged: dict[str, dict[str, str]] = {}
    seen_zctas: set[str] | None = None
    for chunk in chunks:
        params = {"get": ",".join(chunk), "for": f"{_GEO_COL}:*", "key": key}
        if year <= STATE_QUALIFIED_MAX_YEAR:
            params["in"] = "state:36"
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        if len(payload) <= 1:
            raise RuntimeError(f"ACS ZCTA {year} pull returned zero data rows")
        head = payload[0]
        chunk_zctas = set()
        for row in payload[1:]:
            rec = dict(zip(head, row))
            z = rec[_GEO_COL]
            chunk_zctas.add(z)
            merged.setdefault(z, {}).update(rec)
        if seen_zctas is None:
            seen_zctas = chunk_zctas
        elif chunk_zctas != seen_zctas:
            raise RuntimeError(
                f"ACS ZCTA {year} chunked pull disagreed on the ZCTA set: "
                f"{len(seen_zctas ^ chunk_zctas)} ZCTAs present in one chunk and not "
                "another -- merging would leave records with missing variables")
    for z, rec in merged.items():
        missing = [v for v in getvars if v not in rec]
        if missing:
            raise RuntimeError(f"ACS ZCTA {year} ZCTA {z} is missing {len(missing)} "
                                f"requested variables after merging chunks (first: {missing[0]})")
    header = getvars + [_GEO_COL]
    rows = [[merged[z][v] for v in getvars] + [z] for z in sorted(merged)]
    data = [header] + rows
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "year": year, "vars": getvars, "data": data, "source_url": url,
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }))
    return data


def _parse_vintage(year: int, data: list[list[str]]) -> pd.DataFrame:
    """Raw [header, row, ...] Census payload -> one row per ZCTA with derived
    shares and their MOEs. Does NOT filter to NYC (kept separate so tests can
    exercise the parse on a small synthetic payload)."""
    head, rows = data[0], data[1:]
    zi = next(i for i, c in enumerate(head) if "zip code" in c)
    idx = {c: i for i, c in enumerate(head)}
    edu = edu_spec(year)
    boundary = zcta_geography_vintage(year)
    records = []
    for row in rows:
        rec = {c: row[i] for c, i in idx.items()}
        zcta = str(row[zi])

        def cell(stem: str) -> tuple[float | None, float | None]:
            return _clean(rec.get(stem + "E")), _clean(rec.get(stem + "M"))

        out = {"zcta": zcta, "acs_year": year, "zcta_geography_vintage": boundary,
               "education_table": edu["table"]}
        for col, stem in SIMPLE_VARS.items():
            e, m = cell(stem)
            out[f"{col}_e"], out[f"{col}_m"] = e, m

        age_num_e, age_num_m = _sum_cells(rec, AGE_20_34_CELLS)
        age_den_e, age_den_m = out["age_20_34_denom_e"], out["age_20_34_denom_m"]
        out["age_20_34_e"], out["age_20_34_m"] = age_num_e, age_num_m
        out["age_20_34_share"] = (age_num_e / age_den_e) if age_den_e else None
        out["age_20_34_share_m"] = _moe_proportion(age_num_e, age_num_m, age_den_e, age_den_m)

        edu_den_e, edu_den_m = cell(edu["denom"])
        edu_num_e, edu_num_m = _sum_cells(rec, edu["numerator_cells"])
        out["bachelors_plus_denom_e"], out["bachelors_plus_denom_m"] = edu_den_e, edu_den_m
        out["bachelors_plus_e"], out["bachelors_plus_m"] = edu_num_e, edu_num_m
        out["bachelors_plus_share"] = (edu_num_e / edu_den_e) if edu_den_e else None
        out["bachelors_plus_share_m"] = _moe_proportion(edu_num_e, edu_num_m, edu_den_e, edu_den_m)

        records.append(out)
    df = pd.DataFrame(records)
    # age_20_34_denom is only a denominator; drop it in favor of the named pair.
    return df.drop(columns=["age_20_34_denom_e", "age_20_34_denom_m"])


def nyc_zcta_set() -> set[str]:
    """The 211-ZCTA NYC universe from the 2020 ZCTA↔county relationship file,
    reused as-is (not modified, not re-downloaded) from
    `census_cbp_national.zcta_county_crosswalk`."""
    cw = zcta_county_crosswalk()
    nyc = cw[cw["county_fips"].isin(NYC_COUNTY_FIPS)]
    if nyc.empty:
        raise RuntimeError("zcta_county_crosswalk() returned zero NYC ZCTAs -- "
                            "crosswalk file or county FIPS filter broke")
    return set(nyc["zipcode"].astype(str))


def build_vintage(year: int, *, force: bool = False) -> pd.DataFrame:
    """One vintage's NYC ZCTA panel rows."""
    data = fetch_vintage_raw(year, force=force)
    parsed = _parse_vintage(year, data)
    nyc_zctas = nyc_zcta_set()
    out = parsed[parsed["zcta"].isin(nyc_zctas)].reset_index(drop=True)
    if out.empty:
        raise RuntimeError(f"ACS ZCTA {year}: NYC filter matched zero of {len(parsed)} "
                            f"rows returned by the API")
    return out


def build_panel(*, years: list[int] | None = None, force: bool = False) -> pd.DataFrame:
    """Every vintage's NYC ZCTA panel, stacked. Writes one parquet per vintage
    plus a combined panel parquet under data/interim/rq001/acs_zcta/. Prints
    one progress line per vintage."""
    years = years or VINTAGES
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    n_nyc = len(nyc_zcta_set())
    for year in years:
        df = build_vintage(year, force=force)
        boundary = int(df["zcta_geography_vintage"].iloc[0])
        edu_table = df["education_table"].iloc[0]
        print(f"[acs_zcta] {year}: {len(df)}/{n_nyc} NYC ZCTAs, "
              f"boundary={boundary}, education_table={edu_table}")
        df.to_parquet(INTERIM_DIR / f"acs_zcta_{year}.parquet", index=False)
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    panel_path = INTERIM_DIR / "acs_zcta_panel.parquet"
    panel.to_parquet(panel_path, index=False)
    return panel


if __name__ == "__main__":
    build_panel()
