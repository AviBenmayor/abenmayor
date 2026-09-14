"""National County Business Patterns (CBP) + ZIP Business Patterns (ZBP) pulls,
for the carrying-capacity comparison (docs/carrying-capacity-2026-09.md).

WHY A SECOND CBP MODULE AND NOT AN EDIT TO census_zbp.py
---------------------------------------------------------------------------
`sources/universal/census_zbp.py` pulls ONE geography (the ~217 NYC PLUTO ZIPs)
at EVERY employment-size band, and lands it in `analysis.zip_establishments`
for the D40 coverage check. This module pulls the OPPOSITE shape: the whole
country at one size band (all establishments), at two geographies (county and
ZCTA), for a cross-metro curve. Merging the two would give one function four
mutually exclusive modes; they share the thing that actually must not fork --
the NAICS crosswalk, which BOTH read from `loci.zbp.load_zbp_naics()` (D42:
one NAICS mapping, never two).

Nothing here writes to the warehouse. Every pull lands as a cached artifact
under `data/raw/cbp/` or `data/raw/zbp/` and is read back as a DataFrame, so a
re-fit is reproducible offline and a locked database cannot block the analysis.

PROBE FINDINGS (2026-09-14, per CLAUDE.md "verify before designing around it")
---------------------------------------------------------------------------
* CBP 2023 is the latest published vintage (2024 404s), and it still keys on
  `NAICS2017` -- the same vocabulary `src/loci/zbp_naics.yaml` already holds,
  so the existing crosswalk is used VERBATIM with no recode.
* `for=county:*` returns all ~3,140 counties in one request per NAICS code
  (~1.4 s, 2,291 rows for 445110 -- counties with zero or suppressed cells are
  simply ABSENT, which is why a missing (county, naics) is filled with 0 only
  after an explicit `present` join, never assumed).
* `for=zipcode:*` also works with no state filter (~5.7 s, 7,152 rows for
  445110). This is the ZBP half.
* The `CBSA` variable IS returnable on county rows but comes back NULL for
  counties (verified: Albany County NY -> None), so it cannot serve as the
  county->metro crosswalk. The OMB delineation file is used instead, parsed
  from xlsx with the standard library (`zipfile` + `xml`) because openpyxl is
  not a project dependency and this is a once-a-year 140 KB file.
* County and ZCTA land area come from the Census Gazetteer (`ALAND_SQMI`),
  not from a geometry computation -- Loci has no national boundary layer and
  does not want one for a density denominator.
* ACS 2023 5-year serves county (`for=county:*`), metro
  (`for=metropolitan statistical area/micropolitan statistical area:*`) and
  ZCTA (`for=zip code tabulation area:*`) population and housing units in one
  request each.
"""
from __future__ import annotations

import csv
import io
import json
import os
import pathlib
import time
import urllib.parse
import urllib.request
import zipfile
from xml.etree import ElementTree

import pandas as pd

from loci.zbp import load_zbp_naics

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
CBP_DIR = REPO_ROOT / "data" / "raw" / "cbp"
ZBP_DIR = REPO_ROOT / "data" / "raw" / "zbp"

SOURCE_ID = "census_cbp"
API = "https://api.census.gov/data"
DEFAULT_YEAR = 2023
DEFAULT_ACS_YEAR = 2023

GAZ_COUNTY = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
              "{year}_Gazetteer/{year}_Gaz_counties_national.zip")
GAZ_ZCTA = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
            "{year}_Gazetteer/{year}_Gaz_zcta_national.zip")
DELINEATION = ("https://www2.census.gov/programs-surveys/metro-micro/geographies/"
               "reference-files/{year}/delineation-files/list1_{year}.xlsx")

MAX_RETRIES = 4
BACKOFF_S = 4.0
USER_AGENT = "loci/carrying-capacity (contact: repository owner)"


class CensusPullError(RuntimeError):
    """A Census endpoint failed after every retry. Raised rather than returning
    a partial frame: a national curve fitted on a silently truncated pull would
    look exactly like a real cross-metro difference."""


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def _key() -> str:
    return os.environ.get("CENSUS_API_KEY", "")


def _fetch(url: str, timeout: int = 300) -> bytes:
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised as CensusPullError
            last = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_S * (attempt + 1))
    raise CensusPullError(f"{url.split('?')[0]} failed after {MAX_RETRIES} tries: {last}")


def _api(dataset: str, params: dict[str, str]) -> list[list[str]]:
    key = _key()
    if key:
        params = {**params, "key": key}
    url = f"{API}/{dataset}?" + urllib.parse.urlencode(params, safe="*():/,")
    return json.loads(_fetch(url))


def _frame(rows: list[list[str]]) -> pd.DataFrame:
    return pd.DataFrame(rows[1:], columns=rows[0])


def _cached(path: pathlib.Path, build, refresh: bool = False) -> pd.DataFrame:
    """Parquet cache. `build()` runs only on a miss or an explicit refresh, so
    a re-fit costs nothing and is reproducible with the network unplugged."""
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    df = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


# ---------------------------------------------------------------------------
# NAICS -- reused, never re-derived (D42)
# ---------------------------------------------------------------------------

def naics_codes() -> dict[str, str]:
    """{naics_2017_code: loci_category}, straight from `src/loci/zbp_naics.yaml`.

    This is the ONLY NAICS mapping in the project. CBP 2023 still keys on
    NAICS2017, which is the vintage that file is written in, so nothing is
    recoded here -- a recode would be a second mapping wearing a costume.
    """
    out: dict[str, str] = {}
    for cat, entries in load_zbp_naics().items():
        for entry in entries:
            out[str(entry["naics"])] = cat
    return out


# ---------------------------------------------------------------------------
# CBP / ZBP establishment counts
# ---------------------------------------------------------------------------

def fetch_cbp_county(year: int = DEFAULT_YEAR, refresh: bool = False) -> pd.DataFrame:
    """Establishments by county x NAICS, all US counties. Columns:
    state, county, county_fips, naics, category, estab, emp.

    One request per NAICS code (~30 codes, ~1.5 s each). A (county, naics) pair
    absent from the response is NOT a zero -- it is zero-or-suppressed, and the
    distinction is carried by simply not emitting a row. Callers that need a
    dense grid must fill explicitly and say so.
    """
    path = CBP_DIR / f"cbp_{year}_county.parquet"

    def build() -> pd.DataFrame:
        mapping = naics_codes()
        parts = []
        for code, cat in sorted(mapping.items()):
            rows = _api(f"{year}/cbp", {
                "get": "ESTAB,EMP,NAME",
                "for": "county:*",
                "NAICS2017": code,
            })
            df = _frame(rows)
            df["naics"] = code
            df["category"] = cat
            parts.append(df)
        out = pd.concat(parts, ignore_index=True)
        out["county_fips"] = out["state"].str.zfill(2) + out["county"].str.zfill(3)
        out["estab"] = pd.to_numeric(out["ESTAB"], errors="coerce").fillna(0).astype(int)
        out["emp"] = pd.to_numeric(out["EMP"], errors="coerce")
        return out[["state", "county", "county_fips", "NAME", "naics", "category",
                    "estab", "emp"]].rename(columns={"NAME": "county_name"})

    return _cached(path, build, refresh)


def fetch_zbp_zcta(year: int = DEFAULT_YEAR, refresh: bool = False) -> pd.DataFrame:
    """Establishments by ZIP x NAICS, every US ZIP. Columns: zipcode, naics,
    category, estab. Same absence semantics as `fetch_cbp_county`."""
    path = ZBP_DIR / f"zbp_{year}_national.parquet"

    def build() -> pd.DataFrame:
        mapping = naics_codes()
        parts = []
        for code, cat in sorted(mapping.items()):
            rows = _api(f"{year}/cbp", {
                "get": "ESTAB",
                "for": "zipcode:*",
                "NAICS2017": code,
            })
            df = _frame(rows)
            df = df.rename(columns={"zip code": "zipcode"})
            df["naics"] = code
            df["category"] = cat
            parts.append(df)
        out = pd.concat(parts, ignore_index=True)
        out["estab"] = pd.to_numeric(out["ESTAB"], errors="coerce").fillna(0).astype(int)
        return out[["zipcode", "naics", "category", "estab"]]

    return _cached(path, build, refresh)


# ---------------------------------------------------------------------------
# ACS denominators
# ---------------------------------------------------------------------------

def fetch_acs_county(year: int = DEFAULT_ACS_YEAR, refresh: bool = False) -> pd.DataFrame:
    """County population, housing units, households and median household income
    (ACS 5-year). Columns: county_fips, county_name, population, housing_units,
    households, median_hh_income."""
    path = CBP_DIR / f"acs_{year}_county.parquet"

    def build() -> pd.DataFrame:
        rows = _api(f"{year}/acs/acs5", {
            "get": "NAME,B01003_001E,B25001_001E,B11001_001E,B19013_001E",
            "for": "county:*",
        })
        df = _frame(rows)
        df["county_fips"] = df["state"].str.zfill(2) + df["county"].str.zfill(3)
        num = {"B01003_001E": "population", "B25001_001E": "housing_units",
               "B11001_001E": "households", "B19013_001E": "median_hh_income"}
        for src, dst in num.items():
            df[dst] = pd.to_numeric(df[src], errors="coerce")
        df.loc[df["median_hh_income"] < 0, "median_hh_income"] = pd.NA
        return df[["county_fips", "NAME", *num.values()]].rename(
            columns={"NAME": "county_name"})

    return _cached(path, build, refresh)


def fetch_acs_zcta(year: int = DEFAULT_ACS_YEAR, refresh: bool = False) -> pd.DataFrame:
    """ZCTA population, housing units, households, median household income."""
    path = ZBP_DIR / f"acs_{year}_zcta.parquet"

    def build() -> pd.DataFrame:
        rows = _api(f"{year}/acs/acs5", {
            "get": "B01003_001E,B25001_001E,B11001_001E,B19013_001E",
            "for": "zip code tabulation area:*",
        })
        df = _frame(rows)
        df = df.rename(columns={"zip code tabulation area": "zipcode"})
        num = {"B01003_001E": "population", "B25001_001E": "housing_units",
               "B11001_001E": "households", "B19013_001E": "median_hh_income"}
        for src, dst in num.items():
            df[dst] = pd.to_numeric(df[src], errors="coerce")
        df.loc[df["median_hh_income"] < 0, "median_hh_income"] = pd.NA
        return df[["zipcode", *num.values()]]

    return _cached(path, build, refresh)


def fetch_acs_msa(year: int = DEFAULT_ACS_YEAR, refresh: bool = False) -> pd.DataFrame:
    """Metro/micro area population. Columns: cbsa, cbsa_name, population."""
    path = CBP_DIR / f"acs_{year}_msa.parquet"

    def build() -> pd.DataFrame:
        rows = _api(f"{year}/acs/acs5", {
            "get": "NAME,B01003_001E",
            "for": "metropolitan statistical area/micropolitan statistical area:*",
        })
        df = _frame(rows)
        df = df.rename(columns={
            "metropolitan statistical area/micropolitan statistical area": "cbsa",
            "NAME": "cbsa_name"})
        df["population"] = pd.to_numeric(df["B01003_001E"], errors="coerce")
        return df[["cbsa", "cbsa_name", "population"]]

    return _cached(path, build, refresh)


# ---------------------------------------------------------------------------
# geography: land area and the county -> metro crosswalk
# ---------------------------------------------------------------------------

def _gazetteer(url: str, geoid_col: str, out_col: str, path: pathlib.Path,
               refresh: bool) -> pd.DataFrame:
    def build() -> pd.DataFrame:
        raw = _fetch(url)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
            text = zf.read(name).decode("latin-1")
        df = pd.read_csv(io.StringIO(text), sep="\t", dtype=str)
        df.columns = [c.strip() for c in df.columns]
        df[out_col] = pd.to_numeric(df["ALAND_SQMI"], errors="coerce")
        df = df.rename(columns={geoid_col: "geoid"})
        return df[["geoid", out_col]]
    return _cached(path, build, refresh)


def fetch_county_land_area(year: int = DEFAULT_YEAR, refresh: bool = False) -> pd.DataFrame:
    """County land area in square miles (Gazetteer ALAND_SQMI). Land, not total:
    a coastal county's water area is not somewhere people live, and including it
    would push every waterfront metro down the density axis."""
    df = _gazetteer(GAZ_COUNTY.format(year=year), "GEOID", "land_sqmi",
                    CBP_DIR / f"gaz_{year}_county.parquet", refresh)
    return df.rename(columns={"geoid": "county_fips"})


def fetch_zcta_land_area(year: int = DEFAULT_YEAR, refresh: bool = False) -> pd.DataFrame:
    """ZCTA land area in square miles."""
    df = _gazetteer(GAZ_ZCTA.format(year=year), "GEOID", "land_sqmi",
                    ZBP_DIR / f"gaz_{year}_zcta.parquet", refresh)
    return df.rename(columns={"geoid": "zipcode"})


def _xlsx_rows(raw: bytes) -> list[list[str]]:
    """Minimal xlsx reader: sharedStrings + the first worksheet, standard library
    only. openpyxl is not a project dependency and this file is 140 KB once a
    year -- adding a dependency for it would be the larger commitment."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ElementTree.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{ns}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))
        sheet = min(n for n in zf.namelist()
                    if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        root = ElementTree.fromstring(zf.read(sheet))
        rows = []
        for row in root.iter(f"{ns}row"):
            vals = []
            for c in row.findall(f"{ns}c"):
                v = c.find(f"{ns}v")
                if v is None or v.text is None:
                    vals.append("")
                elif c.get("t") == "s":
                    vals.append(shared[int(v.text)])
                else:
                    vals.append(v.text)
            rows.append(vals)
    return rows


def fetch_cbsa_crosswalk(year: int = DEFAULT_YEAR, refresh: bool = False) -> pd.DataFrame:
    """County -> CBSA from the OMB delineation file. Columns: county_fips,
    cbsa, cbsa_name, metro_micro.

    Used INSTEAD of the CBP `CBSA` variable, which is returnable on county rows
    but comes back null (probed 2026-09-14).
    """
    path = CBP_DIR / f"cbsa_{year}_crosswalk.parquet"

    def build() -> pd.DataFrame:
        rows = _xlsx_rows(_fetch(DELINEATION.format(year=year)))
        header_idx = next(i for i, r in enumerate(rows)
                          if r and r[0].strip().upper().startswith("CBSA CODE"))
        header = [c.strip() for c in rows[header_idx]]
        body = [r for r in rows[header_idx + 1:] if r and r[0].strip().isdigit()]
        df = pd.DataFrame(body, columns=header[:len(body[0])] if body else header)
        col = {c.lower(): c for c in df.columns}
        df = df.rename(columns={
            col["cbsa code"]: "cbsa",
            col["cbsa title"]: "cbsa_name",
            col["metropolitan/micropolitan statistical area"]: "metro_micro",
            col["fips state code"]: "st",
            col["fips county code"]: "cty",
        })
        df["county_fips"] = df["st"].str.zfill(2) + df["cty"].str.zfill(3)
        return df[["county_fips", "cbsa", "cbsa_name", "metro_micro"]]

    return _cached(path, build, refresh)


def zcta_county_crosswalk(refresh: bool = False) -> pd.DataFrame:
    """ZCTA -> county (2020 relationship file), used only to LABEL a ZCTA with a
    metro. A ZCTA can straddle counties; the county with the largest shared land
    area wins, and the tie is broken deterministically by FIPS so the label is
    reproducible."""
    path = ZBP_DIR / "zcta_county_rel_2020.parquet"
    url = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
           "tab20_zcta520_county20_natl.txt")

    def build() -> pd.DataFrame:
        text = _fetch(url).decode("latin-1")
        reader = csv.DictReader(io.StringIO(text), delimiter="|")
        recs = []
        for r in reader:
            z, c = r.get("GEOID_ZCTA5_20"), r.get("GEOID_COUNTY_20")
            if not z or not c:
                continue
            recs.append({"zipcode": z, "county_fips": c,
                         "aland": pd.to_numeric(r.get("AREALAND_PART"), errors="coerce")})
        df = pd.DataFrame(recs).dropna(subset=["aland"])
        df = df.sort_values(["zipcode", "aland", "county_fips"],
                            ascending=[True, False, True])
        return df.drop_duplicates("zipcode")[["zipcode", "county_fips"]]

    return _cached(path, build, refresh)


def pull_all(year: int = DEFAULT_YEAR, acs_year: int = DEFAULT_ACS_YEAR,
             refresh: bool = False) -> dict[str, int]:
    """Every national artifact the carrying-capacity comparison needs.
    Returns {artifact: row count}."""
    out = {
        "cbp_county": len(fetch_cbp_county(year, refresh)),
        "zbp_zcta": len(fetch_zbp_zcta(year, refresh)),
        "acs_county": len(fetch_acs_county(acs_year, refresh)),
        "acs_zcta": len(fetch_acs_zcta(acs_year, refresh)),
        "acs_msa": len(fetch_acs_msa(acs_year, refresh)),
        "gaz_county": len(fetch_county_land_area(year, refresh)),
        "gaz_zcta": len(fetch_zcta_land_area(year, refresh)),
        "cbsa_crosswalk": len(fetch_cbsa_crosswalk(year, refresh)),
        "zcta_county": len(zcta_county_crosswalk(refresh)),
    }
    return out
