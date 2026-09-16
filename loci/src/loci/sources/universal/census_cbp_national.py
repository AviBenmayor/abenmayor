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

WHY THERE IS NO `DEFAULT_YEAR` ANY MORE (2026-09-16, owner rule: "never ever
ever limit data pulls")
---------------------------------------------------------------------------
This module used to carry `DEFAULT_YEAR = 2023` and every puller took one
year. That was a cap, not a fact about the source: CBP is an ANNUAL series and
the API serves far more than one vintage. The pullers now default to EVERY
year the API serves, keyed by year, with the classification system recorded on
every row.

PROBE, 2026-09-16 (`api.census.gov/data/<year>/cbp`, live, with a key):

  * `variables.json` returns 200 for **1986 through 2023** and 404 for 2024.
    1986 is therefore the true first served year and matches what
    registry.yaml already claimed; 2024 is simply not published yet.
  * The industry-classification VARIABLE NAME changes by era, and a request
    using the wrong one is a hard 400. Verified name per year:

        1986-1997  SIC        (+ SIC_TTL)          <- NOT NAICS
        1998-2002  NAICS1997  (+ NAICS1997_TTL)
        2003-2007  NAICS2002  (+ NAICS2002_TTL)
        2008-2011  NAICS2007  (+ NAICS2007_TTL)
        2012-2016  NAICS2012  (+ NAICS2012_TTL)
        2017-2023  NAICS2017  (no _TTL / _LABEL on this dataset)

  * GEOGRAPHY also changes. `county` is served in every year 1986-2023.
    `zip code` appears in `geography.json` only from **2018** onward, so the
    national ZCTA half of this module cannot go back further than 2018 through
    the CBP endpoint. (The separate `zbp` dataset covers 1994-2018 ZIPs and is
    driven from `sources/universal/census_zbp.py`, which pulls NYC ZIPs, not
    the nation.)
  * A code that is VALID for the year but not published returns **HTTP 204
    with an empty body** -- not an error, not an empty JSON array. A wrong
    variable name returns 400. Those two are kept apart deliberately below: a
    204 is recorded as an explicit absence with its reason, never turned into
    a zero-establishment row, and never allowed to shrink a year to silence.
  * An unfiltered `for=county:*` (no industry filter) is rejected with
    "estimated query results exceed cell limit of ~981,000", so the per-code
    loop is not a choice -- it is the only shape the API allows.

UPSTREAM LIMITS vs OUR LIMITS (say which, always)
---------------------------------------------------------------------------
UPSTREAM: 2024 and later are not published. 1985 and earlier are not served.
ZIP geography on this endpoint begins in 2018. Nothing here can fix those.

OURS, and deliberate: the per-CATEGORY pull runs 1998-2023 only. 1986-1997 IS
served, but only under SIC, and this project has exactly ONE industry
crosswalk -- `src/loci/zbp_naics.yaml`, in NAICS (D42: one NAICS mapping,
never two). Writing a SIC -> Loci-category mapping here would be a second
crosswalk wearing a costume and is an owner decision, not an adapter's. So
the SIC years are pulled at the ALL-INDUSTRIES level instead, where no
crosswalk is needed at all: `fetch_cbp_county_totals` covers the full
1986-2023 span and gives a 38-year county establishment/employment series.

A SECOND OURS, recorded rather than hidden: NAICS renumbered the eating-and-
drinking codes in 2012. Three of the crosswalk's codes (the two restaurant
codes and the coffee-shop code) return 204 for every year 1998-2011 and 200
from 2012 on -- verified code-by-code against `for=state:36`, all 20 crosswalk
codes x 26 years. The other 17 codes are served in all 26 years. Those 204s
are landed in an `absent` manifest per year with the reason, so a downstream
reader sees "not published in NAICS2007" and not "nobody ran a restaurant".
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

#: Earliest and latest CBP vintage the API answers for at all (probe 2026-09-16:
#: 1985 -> 404, 1986..2023 -> 200, 2024 -> 404). UPSTREAM limits, both ends.
CBP_FIRST_YEAR = 1986
CBP_LAST_YEAR = 2023

#: year -> the industry-classification VARIABLE NAME that year's endpoint takes.
#: Using the wrong one is a 400, not an empty result, so this table is load-
#: bearing. Verified by reading `variables.json` for all 38 years (2026-09-16).
CBP_CLASSIFICATION: dict[int, str] = {
    **{y: "SIC" for y in range(1986, 1998)},
    **{y: "NAICS1997" for y in range(1998, 2003)},
    **{y: "NAICS2002" for y in range(2003, 2008)},
    **{y: "NAICS2007" for y in range(2008, 2012)},
    **{y: "NAICS2012" for y in range(2012, 2017)},
    **{y: "NAICS2017" for y in range(2017, CBP_LAST_YEAR + 1)},
}

#: The years whose classification is some vintage of NAICS, i.e. the years the
#: project's ONE crosswalk (zbp_naics.yaml, D42) can address at all. 1998-2023.
CBP_NAICS_YEARS: tuple[int, ...] = tuple(
    y for y in sorted(CBP_CLASSIFICATION) if CBP_CLASSIFICATION[y].startswith("NAICS"))

#: The SIC years. Served by the API, NOT pulled per category -- see the module
#: docstring ("OURS, and deliberate"). They ARE pulled by the totals puller.
CBP_SIC_YEARS: tuple[int, ...] = tuple(
    y for y in sorted(CBP_CLASSIFICATION) if CBP_CLASSIFICATION[y] == "SIC")

#: Years whose `geography.json` offers `zip code`. UPSTREAM limit: 2018 is the
#: first. Everything earlier is ZIP-less on this endpoint.
CBP_ZIP_YEARS: tuple[int, ...] = tuple(range(2018, CBP_LAST_YEAR + 1))

#: The GEOGRAPHY-NAME variable also moved. `NAME` is a 2016+ spelling only:
#: 1986-2015 answer `get=...,NAME` with "error: unknown variable 'NAME'" and
#: want `GEO_TTL` instead, while 2017+ do the reverse. 2016 accepts both.
#: Verified live for 1986/1997/1998/2007/2011/2016/2017/2023 (2026-09-16).
FIRST_NAME_VAR_YEAR = 2017


def name_var_for(year: int) -> str:
    """The county-name variable `year` accepts. See FIRST_NAME_VAR_YEAR."""
    return "NAME" if year >= FIRST_NAME_VAR_YEAR else "GEO_TTL"


#: The "all industries" roll-up code. Accepted verbatim as the filter value in
#: EVERY era (the RESPONSE pads it differently -- '00', '00   ', '00    ' --
#: but the REQUEST takes a bare '00' from 1986 through 2023; verified for all
#: 38 years). Two characters, so it is not a crosswalk and cannot become one.
ALL_INDUSTRIES = "00"

#: Kept only so existing callers that pass no year still resolve to a real
#: vintage. It is NOT a cap any more: every `*_all_years` puller ignores it.
DEFAULT_YEAR = CBP_LAST_YEAR
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


class CensusYearUnavailable(CensusPullError):
    """The requested year is not something this adapter can pull, and the
    reason is known and named. Distinct from a transport failure so a caller
    looping over years can record the year as EXPLICITLY ABSENT with its
    reason instead of writing zero rows and moving on."""

    def __init__(self, year: int, reason: str):
        self.year = year
        self.reason = reason
        super().__init__(f"CBP {year}: {reason}")


def classification_for(year: int) -> str:
    """The industry-classification variable name for `year`, or raise.

    Every request in this module goes through this rather than hardcoding
    NAICS2017: a 2008 request carrying NAICS2017 is answered with a 400, and a
    year loop that swallowed that would quietly publish a 26-year series with
    18 empty years in it.
    """
    try:
        return CBP_CLASSIFICATION[year]
    except KeyError:
        raise CensusYearUnavailable(
            year,
            f"outside the served range {CBP_FIRST_YEAR}-{CBP_LAST_YEAR} "
            f"(UPSTREAM: api.census.gov/data/{year}/cbp 404s)") from None


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def _key() -> str:
    """CENSUS_API_KEY from the process environment, falling back to the repo
    `.env`. The fallback matches `sources/universal/census_zbp.py` -- without
    it this module silently ran keyless, and a keyless `for=county:*` request
    is answered with a 302 to an empty body, which reads exactly like "this
    year has no data"."""
    key = os.environ.get("CENSUS_API_KEY", "")
    if key:
        return key
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CENSUS_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _fetch(url: str, timeout: int = 300) -> bytes:
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            # A 4xx is a malformed request (wrong variable name for the era,
            # cell limit exceeded). Retrying it four times with backoff just
            # makes a 38-year loop slow; surface it immediately with the body,
            # which is where Census puts the actual complaint.
            if 400 <= exc.code < 500:
                body = ""
                try:
                    body = exc.read()[:300].decode("utf8", "replace")
                except Exception:  # noqa: BLE001 - best-effort diagnostics only
                    pass
                raise CensusPullError(
                    f"{url.split('?')[0]} -> HTTP {exc.code}: {body}") from exc
            last = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_S * (attempt + 1))
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised as CensusPullError
            last = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_S * (attempt + 1))
    raise CensusPullError(f"{url.split('?')[0]} failed after {MAX_RETRIES} tries: {last}")


#: Census's own signal that a request was well-formed and valid for the year
#: but matched nothing published: HTTP 204, empty body. Verified 2026-09-16
#: (`2008/cbp?...&NAICS2007=<a 2012-era code>` -> 204, 0 bytes; the same code
#: against 2012 -> 200 with data; a WRONG variable name -> 400).
NO_CONTENT = 204


def _api(dataset: str, params: dict[str, str]) -> list[list[str]]:
    rows = _api_optional(dataset, params)
    if rows is None:
        raise CensusPullError(
            f"{API}/{dataset} returned {NO_CONTENT} (nothing published) for "
            f"{params!r}; the caller treated that as fatal.")
    return rows


def _api_optional(dataset: str, params: dict[str, str]) -> list[list[str]] | None:
    """`None` means HTTP 204 -- valid request, nothing published. Anything else
    that goes wrong still raises. Callers MUST branch on the None rather than
    coercing it to an empty frame."""
    key = _key()
    if key:
        params = {**params, "key": key}
    url = f"{API}/{dataset}?" + urllib.parse.urlencode(params, safe="*():/,")
    raw = _fetch(url)
    if not raw.strip():
        return None
    return json.loads(raw)


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

def _require_naics_year(year: int) -> str:
    """The classification variable for a year the CATEGORY pull can serve."""
    var = classification_for(year)
    if not var.startswith("NAICS"):
        raise CensusYearUnavailable(
            year,
            f"classified under {var}, not NAICS. The API serves this year; this "
            f"project does not map it, because it holds exactly one industry "
            f"crosswalk (src/loci/zbp_naics.yaml, D42) and it is in NAICS. Pull "
            f"`fetch_cbp_county_totals({year})` instead, which needs no crosswalk.")
    return var


def _absent_path(kind: str, year: int) -> pathlib.Path:
    base = CBP_DIR if kind == "county" else ZBP_DIR
    return base / f"cbp_{year}_{kind}_absent.parquet"


def _pull_by_code(year: int, geo: str, getvars: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One request per crosswalk code against `year`'s own classification
    variable. Returns (rows, absent).

    `absent` is the whole point. Three outcomes are possible per code and they
    must stay three:
      HTTP 200 -> rows, appended.
      HTTP 204 -> the code is not published in this vintage. Recorded in
                  `absent` with the reason. NEVER emitted as estab = 0: a
                  renumbered NAICS code and a category nobody operates are the
                  same number and opposite facts.
      anything else -> raises, so one bad year cannot quietly shrink the series.
    """
    var = _require_naics_year(year)
    mapping = naics_codes()
    parts: list[pd.DataFrame] = []
    absent: list[dict] = []
    for code, cat in sorted(mapping.items()):
        rows = _api_optional(f"{year}/cbp", {"get": getvars, "for": geo, var: code})
        if rows is None:
            absent.append({
                "year": year, "naics_vintage": var, "naics": code, "category": cat,
                "reason": f"HTTP {NO_CONTENT}: code not published under {var} "
                          f"(NAICS renumbering, not an absence of businesses)",
            })
            continue
        df = _frame(rows)
        df["naics"] = code
        df["category"] = cat
        parts.append(df)
    if not parts:
        raise CensusPullError(
            f"CBP {year} {geo}: every one of the {len(mapping)} crosswalk codes "
            f"came back {NO_CONTENT}. That is a broken request shape, not a year "
            f"in which America had no shops; refusing to cache an empty year.")
    out = pd.concat(parts, ignore_index=True)
    out.insert(0, "naics_vintage", var)
    out.insert(0, "year", year)
    return out, pd.DataFrame(absent, columns=["year", "naics_vintage", "naics",
                                              "category", "reason"])


def fetch_cbp_county(year: int = DEFAULT_YEAR, refresh: bool = False) -> pd.DataFrame:
    """Establishments by county x NAICS for ONE year. Columns: year,
    naics_vintage, state, county, county_fips, county_name, naics, category,
    estab, emp.

    One request per NAICS code (20 codes, ~1 s each). A (county, naics) pair
    absent from a 200 response is NOT a zero -- it is zero-or-suppressed, and
    the distinction is carried by simply not emitting a row. Callers that need
    a dense grid must fill explicitly and say so.

    A whole CODE absent for the year (HTTP 204) is a different thing again and
    lands in the sidecar written by `cbp_county_absent(year)`.
    """
    path = CBP_DIR / f"cbp_{year}_county.parquet"
    apath = _absent_path("county", year)

    def build() -> pd.DataFrame:
        nm = name_var_for(year)
        out, absent = _pull_by_code(year, "county:*", f"ESTAB,EMP,{nm}")
        out = out.rename(columns={nm: "county_name"})
        out["county_fips"] = out["state"].str.zfill(2) + out["county"].str.zfill(3)
        out["estab"] = pd.to_numeric(out["ESTAB"], errors="coerce").fillna(0).astype(int)
        out["emp"] = pd.to_numeric(out["EMP"], errors="coerce")
        apath.parent.mkdir(parents=True, exist_ok=True)
        absent.to_parquet(apath, index=False)
        return out[["year", "naics_vintage", "state", "county", "county_fips",
                    "county_name", "naics", "category", "estab", "emp"]]

    return _cached(path, build, refresh)


def cbp_county_absent(year: int) -> pd.DataFrame:
    """Which crosswalk codes `year` does not publish, and why. Empty frame if
    the year has been pulled and every code was served; raises if the year has
    not been pulled at all, because "no absences recorded" and "never looked"
    must not read the same."""
    path = _absent_path("county", year)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist -- fetch_cbp_county({year}) has not run, so "
            f"nothing is known about which codes that year publishes.")
    return pd.read_parquet(path)


def fetch_cbp_county_totals(year: int = CBP_LAST_YEAR,
                            refresh: bool = False) -> pd.DataFrame:
    """ALL-INDUSTRIES establishments and employment by county, for any year
    1986-2023 -- SIC era included.

    This is the puller that makes the SIC years usable. It filters on the
    all-industries roll-up code, which every era accepts verbatim, so it needs
    no industry crosswalk of any kind and therefore does not care that
    1986-1997 are SIC. One request per year, ~3,200 rows, ~1 s.

    Columns: year, classification, state, county, county_fips, county_name,
    estab, emp.
    """
    path = CBP_DIR / f"cbp_{year}_county_totals.parquet"

    def build() -> pd.DataFrame:
        var = classification_for(year)
        nm = name_var_for(year)
        rows = _api_optional(f"{year}/cbp", {
            "get": f"ESTAB,EMP,{nm}", "for": "county:*", var: ALL_INDUSTRIES})
        if rows is None:
            raise CensusPullError(
                f"CBP {year}: the all-industries total came back {NO_CONTENT}. "
                f"Every year 1986-2023 was verified to serve it on 2026-09-16, so "
                f"this is a change upstream, not an empty year.")
        df = _frame(rows).rename(columns={nm: "county_name"})
        df.insert(0, "classification", var)
        df.insert(0, "year", year)
        df["county_fips"] = df["state"].str.zfill(2) + df["county"].str.zfill(3)
        df["estab"] = pd.to_numeric(df["ESTAB"], errors="coerce").fillna(0).astype(int)
        df["emp"] = pd.to_numeric(df["EMP"], errors="coerce")
        return df[["year", "classification", "state", "county", "county_fips",
                   "county_name", "estab", "emp"]]

    return _cached(path, build, refresh)


def fetch_zbp_zcta(year: int = DEFAULT_YEAR, refresh: bool = False) -> pd.DataFrame:
    """Establishments by ZIP x NAICS, every US ZIP, for ONE year. Columns:
    year, naics_vintage, zipcode, naics, category, estab. Same absence
    semantics as `fetch_cbp_county`.

    UPSTREAM limit: `zip code` geography exists on this endpoint only from
    2018 (verified against `geography.json` for all 38 years), so 2017 and
    earlier raise rather than returning an empty frame.
    """
    if year not in CBP_ZIP_YEARS:
        raise CensusYearUnavailable(
            year,
            f"the CBP endpoint offers `zip code` geography only for "
            f"{CBP_ZIP_YEARS[0]}-{CBP_ZIP_YEARS[-1]} (UPSTREAM: it is absent from "
            f"{year}'s geography.json). NYC ZIPs before 2019 come from the "
            f"separate `zbp` dataset via sources/universal/census_zbp.py.")

    path = ZBP_DIR / f"zbp_{year}_national.parquet"
    apath = _absent_path("zcta", year)

    def build() -> pd.DataFrame:
        out, absent = _pull_by_code(year, "zipcode:*", "ESTAB")
        out = out.rename(columns={"zip code": "zipcode"})
        out["estab"] = pd.to_numeric(out["ESTAB"], errors="coerce").fillna(0).astype(int)
        apath.parent.mkdir(parents=True, exist_ok=True)
        absent.to_parquet(apath, index=False)
        return out[["year", "naics_vintage", "zipcode", "naics", "category", "estab"]]

    return _cached(path, build, refresh)


# ---------------------------------------------------------------------------
# the year loops -- the whole series, not one vintage
# ---------------------------------------------------------------------------

def _loop_years(years, one, label: str) -> tuple[pd.DataFrame, list[dict]]:
    """Run `one(year)` across `years`, keeping failures VISIBLE.

    A year that cannot be served for a NAMED reason (CensusYearUnavailable) is
    recorded and skipped. A year that fails any other way re-raises, because
    "the network flaked on 2011" and "2011 does not exist" are different facts
    and only one of them is safe to paper over.
    """
    frames, skipped = [], []
    for y in years:
        try:
            frames.append(one(y))
        except CensusYearUnavailable as exc:
            skipped.append({"year": y, "reason": exc.reason})
    if not frames:
        raise CensusPullError(
            f"{label}: no year in {list(years)!r} produced rows "
            f"({len(skipped)} skipped with reasons: {skipped!r}).")
    return pd.concat(frames, ignore_index=True), skipped


def cbp_county_years() -> tuple[int, ...]:
    """Every year the per-category county pull can serve: 1998-2023."""
    return CBP_NAICS_YEARS


def cbp_county_totals_years() -> tuple[int, ...]:
    """Every year the all-industries county pull can serve: 1986-2023."""
    return tuple(range(CBP_FIRST_YEAR, CBP_LAST_YEAR + 1))


def fetch_cbp_county_all_years(years=None, refresh: bool = False
                               ) -> tuple[pd.DataFrame, list[dict]]:
    """The whole per-category county series, keyed by year. Default: 1998-2023."""
    years = tuple(years) if years is not None else cbp_county_years()
    return _loop_years(years, lambda y: fetch_cbp_county(y, refresh), "cbp_county")


def fetch_cbp_county_totals_all_years(years=None, refresh: bool = False
                                      ) -> tuple[pd.DataFrame, list[dict]]:
    """The whole all-industries county series, keyed by year. Default: 1986-2023
    -- the full span the API serves, SIC years included."""
    years = tuple(years) if years is not None else cbp_county_totals_years()
    return _loop_years(years, lambda y: fetch_cbp_county_totals(y, refresh),
                       "cbp_county_totals")


def fetch_zbp_zcta_all_years(years=None, refresh: bool = False
                             ) -> tuple[pd.DataFrame, list[dict]]:
    """The whole national ZIP series, keyed by year. Default: 2018-2023, which
    is every year this endpoint carries ZIP geography."""
    years = tuple(years) if years is not None else CBP_ZIP_YEARS
    return _loop_years(years, lambda y: fetch_zbp_zcta(y, refresh), "zbp_zcta")


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
    """Every national artifact the carrying-capacity comparison needs, for ONE
    vintage. `pull_every_year` is the one that honours the series."""
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


def pull_every_year(refresh: bool = False, acs_year: int = DEFAULT_ACS_YEAR,
                    progress=None) -> dict:
    """EVERY year the CBP API serves, for each of the three CBP shapes, plus the
    single-vintage geography artifacts the comparison needs.

    Returns a report, not just counts: `skipped` names each year that could not
    be pulled and why, and `absent` names each (year, code) the API answered
    with a 204. Neither is allowed to be silent -- the owner's rule is as much
    data as possible, and the honest way to obey it is to say out loud what did
    not come back and whether the limit was upstream or ours.
    """
    def note(msg: str) -> None:
        if progress is not None:
            progress(msg)

    note(f"county totals {CBP_FIRST_YEAR}-{CBP_LAST_YEAR} (all industries, no crosswalk)")
    totals, totals_skipped = fetch_cbp_county_totals_all_years(refresh=refresh)

    note(f"county by category {CBP_NAICS_YEARS[0]}-{CBP_NAICS_YEARS[-1]}")
    county, county_skipped = fetch_cbp_county_all_years(refresh=refresh)

    note(f"national ZIP by category {CBP_ZIP_YEARS[0]}-{CBP_ZIP_YEARS[-1]}")
    zcta, zcta_skipped = fetch_zbp_zcta_all_years(refresh=refresh)

    absent = []
    for y in sorted(county["year"].unique()):
        try:
            a = cbp_county_absent(int(y))
        except FileNotFoundError:
            continue
        absent.extend(a.to_dict("records"))

    return {
        "cbp_county_totals": {"rows": len(totals),
                              "years": sorted(int(y) for y in totals["year"].unique())},
        "cbp_county": {"rows": len(county),
                       "years": sorted(int(y) for y in county["year"].unique())},
        "zbp_zcta": {"rows": len(zcta),
                     "years": sorted(int(y) for y in zcta["year"].unique())},
        "skipped": {"cbp_county_totals": totals_skipped,
                    "cbp_county": county_skipped,
                    "zbp_zcta": zcta_skipped,
                    "sic_years_not_pulled_by_category": [
                        {"year": y, "reason": "SIC era; one crosswalk only (D42). "
                                              "Covered by cbp_county_totals."}
                        for y in CBP_SIC_YEARS]},
        "absent_codes": absent,
        "acs_county": len(fetch_acs_county(acs_year, refresh)),
        "acs_zcta": len(fetch_acs_zcta(acs_year, refresh)),
        "acs_msa": len(fetch_acs_msa(acs_year, refresh)),
        "gaz_county": len(fetch_county_land_area(CBP_LAST_YEAR, refresh)),
        "gaz_zcta": len(fetch_zcta_land_area(CBP_LAST_YEAR, refresh)),
        "cbsa_crosswalk": len(fetch_cbsa_crosswalk(CBP_LAST_YEAR, refresh)),
        "zcta_county": len(zcta_county_crosswalk(refresh)),
    }
