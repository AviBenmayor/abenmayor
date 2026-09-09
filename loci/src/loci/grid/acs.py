"""ACS 5-year demographics, dasymetrically interpolated onto the H3 grid (GTM-24).

PLUTO is the ancillary surface: each residential lot knows its 2020 census tract
(bct2020) AND its H3 cell, so a tract's ACS counts are distributed to hexes in
proportion to each hex's share of that tract's residential units — exact, no
polygon intersection. Plain areal weighting would spread population across parks
and rail yards; unit-weighting puts it where the housing is (CONTEXT.md §4.2).

Extensive vars (population, households, renter/owner/no-vehicle counts, age-band
/race/education/one-person-household counts) are apportioned by unit share;
intensive vars (median income, median age, average household size) are
unit-share-weighted averages of the overlapping tracts. ACS margins of error are
propagated, not dropped (§7.8):

  - Apportioned SUM (e.g. population in a hex): MOE = sqrt(sum (w_t * MOE_t)^2)
    -- root-sum-of-squares of the weighted tract MOEs, tracts assumed independent.
  - Apportioned PROPORTION p = X/Y, where X and Y are themselves apportioned sums
    and X is a subset of Y (renter_share, zero_vehicle_hh_share, and the
    zero_vehicle_owner/renter_share tenure splits): first get MOE_X and MOE_Y at
    the hex level by the sum rule above, then apply the ACS handbook's derived
    proportion formula (`_moe_proportion` below) --
        MOE_p = (1/Y) * sqrt(MOE_X^2 - p^2 * MOE_Y^2)
    with the handbook's own fallback to sqrt(MOE_X^2 + p^2*MOE_Y^2) (the general
    ratio formula, which overstates MOE_p and so is conservative) whenever the
    subtraction goes negative -- can happen when p is close to 0 or 1. This
    additionally assumes X and Y's MOEs are independent of each other, on top of
    the independence-across-tracts assumption in the sum rule; both are the
    handbook's own stated approximations, not exact.

  - Apportioned SUM OF SEVERAL CELLS (the three B01001 age bands and the
    B15003 bachelor's-and-above numerator): the ACS handbook's sum rule is
    applied TWICE and in this order -- first WITHIN the tract, across the
    cells of the band, MOE_band,t = sqrt(sum_cells MOE_c,t^2); then ACROSS
    tracts with the unit weights, MOE = sqrt(sum_t (w_t * MOE_band,t)^2).
    (Algebraically the two collapse into one root-sum-of-squares over every
    (tract, cell) pair, which is how the code accumulates it.) The handbook's
    refinement for summing many ZERO-estimate cells -- keep only the largest
    zero-cell MOE -- is deliberately NOT applied: it would shrink the MOE, and
    the plain RSS is the conservative direction.

Income interpolation is an approximation — a unit-weighted mean of tract MEDIAN
incomes is not itself a true median. Documented, acceptable for a control. The
same approximation, and the same caveat, applies to the two intensive fields
added on 2026-09-09: `median_age` (B01002_001, a mean of tract medians) and
`avg_hh_size` (B25010_001, a mean of tract averages -- unweighted by each
tract's household count, so it drifts from a true household-weighted average
where overlapping tracts differ a lot in household count). Their MOEs use the
same weighted-mean-of-MOEs that median_hh_income uses, NOT a root sum of
squares: it is the incumbent treatment for an intensive field in this module,
and having two intensive MOE conventions side by side would be worse than
having one imperfect one. It errs large (a mean of MOEs exceeds the RSS of the
same MOEs), so it is conservative.

2026-09-09 age/race/education/household-size extension: B01002 (median age),
B01001 (sex by age -> under_18 / age_18_34 / age_65_plus shares), B03002
(white/black/asian non-Hispanic and Hispanic shares), B15003 (bachelor's and
above, over the 25+ universe), B25010 (average household size) and B11016
(one-person household share). Every cell index was re-verified against
api.census.gov/data/2023/acs/acs5/variables.json on that date. The variable
list is now past the Census API's 50-per-request cap, so `fetch_acs` chunks it
and merges per tract GEOID.

D54 (GTM-78 D7 pre-test): renter_share's MOE was never carried (B25003_001M/
_003M were missing from GETVARS below) even though every other field had one.
The D7 density-class pre-test on renter_share came back negative -- it's a
population-density proxy (rho=0.62 citywide, but 0.09 within Manhattan, exactly
where a travel-MODE variable would need to carry weight) -- so this module now
also pulls the ACS vehicle-ownership tables the pre-test recommended:
B08201 (household-level zero-vehicle share, the primary measure) and B25044
(owner/renter tenure-split cross-check), alongside fixing the renter_share MOE.
"""
from __future__ import annotations

import collections
import datetime as _dt
import json
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

# Documented Census table/cell meanings, hand-maintained. `test_acs.py` asserts
# this set of keys equals GETVARS below -- a drift test: if one is edited
# without the other, the test fails instead of silently mismatching what is
# fetched against what a reader believes is fetched. Cell indices verified
# against api.census.gov/data/2023/acs/acs5/variables.json before coding
# (2026-09-08) -- do not trust table-cell numbers from memory.
ACS_VARIABLE_NOTES: dict[str, str] = {
    "B01003_001E": "total population, estimate",
    "B01003_001M": "total population, MOE",
    "B11001_001E": "total households, estimate",
    "B11001_001M": "total households, MOE",
    "B19013_001E": "median household income, estimate",
    "B19013_001M": "median household income, MOE",
    "B25003_001E": "occupied housing units, total, estimate",
    "B25003_001M": "occupied housing units, total, MOE",
    "B25003_003E": "occupied housing units, renter-occupied, estimate",
    "B25003_003M": "occupied housing units, renter-occupied, MOE",
    # Household size by vehicles available. _001 total households is its own
    # self-consistent denominator for the no-vehicle share (not B11001_001,
    # a different ACS table that can differ slightly on universe/rounding).
    "B08201_001E": "households (by vehicles available), total, estimate",
    "B08201_001M": "households (by vehicles available), total, MOE",
    "B08201_002E": "households with no vehicle available, estimate",
    "B08201_002M": "households with no vehicle available, MOE",
    # Tenure by vehicles available. _002/_009 are the owner/renter DENOMINATORS
    # (not in the task's literal cell list -- verified separately against the
    # 2023 variables.json: _002E is "Owner occupied:", _009E is "Renter
    # occupied:") needed to express zero_vehicle_owner/renter_share as a
    # within-tenure rate rather than a share of all occupied units; _001 is
    # fetched only as a cross-table sanity check (_002E + _009E should equal
    # it, and it should equal B25003_001E).
    "B25044_001E": "occupied housing units (by tenure/vehicles), total, estimate",
    "B25044_001M": "occupied housing units (by tenure/vehicles), total, MOE",
    "B25044_002E": "owner-occupied housing units, total, estimate",
    "B25044_002M": "owner-occupied housing units, total, MOE",
    "B25044_003E": "owner-occupied, no vehicle available, estimate",
    "B25044_003M": "owner-occupied, no vehicle available, MOE",
    "B25044_009E": "renter-occupied housing units, total, estimate",
    "B25044_009M": "renter-occupied housing units, total, MOE",
    "B25044_010E": "renter-occupied, no vehicle available, estimate",
    "B25044_010M": "renter-occupied, no vehicle available, MOE",
    # ---- 2026-09-09 age / race / education / household-size extension ----
    # Median age. INTENSIVE: a hex gets the unit-share-weighted mean of the
    # medians of the tracts overlapping it, exactly the approximation
    # median_hh_income already carries -- a weighted mean of tract MEDIANS is
    # not itself a median. Fine as a control, never as a published "the median
    # age of this hex is X".
    "B01002_001E": "median age (both sexes), estimate",
    "B01002_001M": "median age (both sexes), MOE",
    # Sex by age. The three age-band shares are summed ACROSS SEXES (male +
    # female cells) and divided by B01001_001, the table's OWN total -- not by
    # B01003_001, so numerator and denominator come from one table and one
    # universe. (They agree: the runtime cross-check below fails loud if
    # B01001_001E and B01003_001E disagree materially per tract.) Individual
    # cell membership is spelled out in B01001_AGE_CELLS / AGE_BANDS below.
    "B01001_001E": "total population (sex by age), estimate",
    "B01001_001M": "total population (sex by age), MOE",
    # Hispanic or Latino origin by race. _003/_004/_006 are the NOT-Hispanic
    # single-race cells (white/black/asian alone), _012 is Hispanic of ANY
    # race -- the standard mutually-exclusive four-way split. Denominator is
    # _001 (the table total), so the four shares are directly comparable and
    # sum to <= 1 (the remainder is AIAN/NHPI/other/two-or-more non-Hispanic,
    # deliberately not carried: NYC tract counts there are small and their
    # MOEs swamp them).
    "B03002_001E": "total population (hispanic origin by race), estimate",
    "B03002_001M": "total population (hispanic origin by race), MOE",
    "B03002_003E": "white alone, not hispanic, estimate",
    "B03002_003M": "white alone, not hispanic, MOE",
    "B03002_004E": "black or african american alone, not hispanic, estimate",
    "B03002_004M": "black or african american alone, not hispanic, MOE",
    "B03002_006E": "asian alone, not hispanic, estimate",
    "B03002_006M": "asian alone, not hispanic, MOE",
    "B03002_012E": "hispanic or latino (any race), estimate",
    "B03002_012M": "hispanic or latino (any race), MOE",
    # Educational attainment, population 25 years and over. Denominator is
    # B15003_001 -- the table's own 25+ universe, NOT total population: a
    # "college share" over all ages would be a child-count artifact. The
    # numerator is bachelor's + master's + professional + doctorate
    # (_022.._025); associate's (_021) is deliberately excluded, which is the
    # convention model/momentum.py already used for B15003, and the two must
    # stay consistent or the same phrase would mean two different things.
    "B15003_001E": "population 25 years and over, estimate",
    "B15003_001M": "population 25 years and over, MOE",
    "B15003_022E": "25+ with bachelor's degree, estimate",
    "B15003_022M": "25+ with bachelor's degree, MOE",
    "B15003_023E": "25+ with master's degree, estimate",
    "B15003_023M": "25+ with master's degree, MOE",
    "B15003_024E": "25+ with professional school degree, estimate",
    "B15003_024M": "25+ with professional school degree, MOE",
    "B15003_025E": "25+ with doctorate degree, estimate",
    "B15003_025M": "25+ with doctorate degree, MOE",
    # Average household size of occupied housing units. INTENSIVE, same
    # unit-share-weighted-mean treatment (and same caveat) as median_hh_income
    # and median age above -- it is already a per-household ratio, so it is
    # averaged, never summed.
    "B25010_001E": "average household size of occupied units, estimate",
    "B25010_001M": "average household size of occupied units, MOE",
    # Household type by household size. _010 is the ONLY 1-person cell in the
    # table (family households are 2+ persons by definition, so a 1-person
    # household is necessarily nonfamily) -- verified against the 2023
    # variables.json label "Nonfamily households:!!1-person household". The
    # denominator is _001, ALL households, so one_person_hh_share is a share
    # of every household and not of nonfamily households only.
    "B11016_001E": "total households (household type by size), estimate",
    "B11016_001M": "total households (household type by size), MOE",
    "B11016_010E": "one-person (nonfamily, 1-person) households, estimate",
    "B11016_010M": "one-person (nonfamily, 1-person) households, MOE",
}

# B01001 (sex by age) age cells, cell number -> label, verified line by line
# against api.census.gov/data/2023/acs/acs5/variables.json on 2026-09-09.
# Male cells run _003.._025, female _027.._049, in the SAME age order; the
# bands below pair them off. Written out rather than range()-generated so a
# reader can check a cell against the Census label without leaving the file.
B01001_AGE_CELLS: dict[str, str] = {
    "003": "male, under 5 years",       "027": "female, under 5 years",
    "004": "male, 5 to 9 years",        "028": "female, 5 to 9 years",
    "005": "male, 10 to 14 years",      "029": "female, 10 to 14 years",
    "006": "male, 15 to 17 years",      "030": "female, 15 to 17 years",
    "007": "male, 18 and 19 years",     "031": "female, 18 and 19 years",
    "008": "male, 20 years",            "032": "female, 20 years",
    "009": "male, 21 years",            "033": "female, 21 years",
    "010": "male, 22 to 24 years",      "034": "female, 22 to 24 years",
    "011": "male, 25 to 29 years",      "035": "female, 25 to 29 years",
    "012": "male, 30 to 34 years",      "036": "female, 30 to 34 years",
    "020": "male, 65 and 66 years",     "044": "female, 65 and 66 years",
    "021": "male, 67 to 69 years",      "045": "female, 67 to 69 years",
    "022": "male, 70 to 74 years",      "046": "female, 70 to 74 years",
    "023": "male, 75 to 79 years",      "047": "female, 75 to 79 years",
    "024": "male, 80 to 84 years",      "048": "female, 80 to 84 years",
    "025": "male, 85 years and over",   "049": "female, 85 years and over",
}

# Band -> the B01001 cells summed into its numerator. Each band is the union
# of the male and female cells covering the same ages, so the bands are
# mutually exclusive and each is a clean share of B01001_001. 35-64 is NOT
# carried as a column: it is 1 - (under_18 + 18_34 + 65_plus) by construction,
# and a fourth column would only invite it to be read as independent.
AGE_BANDS: dict[str, tuple[str, ...]] = {
    # under 18: under 5 / 5-9 / 10-14 / 15-17, both sexes.
    "under_18": ("003", "004", "005", "006", "027", "028", "029", "030"),
    # 18-34: 18-19 / 20 / 21 / 22-24 / 25-29 / 30-34, both sexes. The Census
    # splits the early 20s into single years, hence six cells per sex.
    "age_18_34": ("007", "008", "009", "010", "011", "012",
                  "031", "032", "033", "034", "035", "036"),
    # 65+: 65-66 / 67-69 / 70-74 / 75-79 / 80-84 / 85+, both sexes.
    "age_65_plus": ("020", "021", "022", "023", "024", "025",
                    "044", "045", "046", "047", "048", "049"),
}

# Education numerator cells (bachelor's and above), summed like an age band.
EDU_COLLEGE_CELLS = ("B15003_022", "B15003_023", "B15003_024", "B15003_025")

# ---- the 2026-09-09 fields, as data rather than as eight copied code blocks ----
# Every entry is `output column -> (numerator cell stems, denominator cell stem)`.
# Numerator and denominator are BOTH apportioned tract -> hex as extensive sums
# (unit share, RSS of weighted tract MOEs; multi-cell numerators additionally
# RSS across their own cells first, `_sum_cells`), and only then divided --
# never a weighted average of tract-level ratios, which would weight a tract
# with 4 households the same as one with 4,000. The share's own MOE is the ACS
# handbook proportion formula (`_moe_proportion`), valid here because every
# numerator listed is a strict SUBSET of its denominator's universe.
SHARE_SPECS: dict[str, tuple[tuple[str, ...], str]] = {
    "under_18_share": (tuple(f"B01001_{c}" for c in AGE_BANDS["under_18"]), "B01001_001"),
    "age_18_34_share": (tuple(f"B01001_{c}" for c in AGE_BANDS["age_18_34"]), "B01001_001"),
    "age_65_plus_share": (tuple(f"B01001_{c}" for c in AGE_BANDS["age_65_plus"]), "B01001_001"),
    "white_nh_share": (("B03002_003",), "B03002_001"),
    "black_nh_share": (("B03002_004",), "B03002_001"),
    "asian_nh_share": (("B03002_006",), "B03002_001"),
    "hispanic_share": (("B03002_012",), "B03002_001"),
    "college_share": (EDU_COLLEGE_CELLS, "B15003_001"),
    "one_person_hh_share": (("B11016_010",), "B11016_001"),
}

# INTENSIVE fields: `output column -> cell stem`. A tract's value is already a
# per-person or per-household quantity (a median, an average), so it is
# unit-share WEIGHTED-AVERAGED across the overlapping tracts, never summed --
# the median_hh_income treatment, with the same "a mean of medians is not a
# median" caveat spelled out in the module docstring.
INTENSIVE_SPECS: dict[str, str] = {
    "median_age": "B01002_001",
    "avg_hh_size": "B25010_001",
}

for _cell, _label in B01001_AGE_CELLS.items():
    for _suffix, _what in (("E", "estimate"), ("M", "MOE")):
        ACS_VARIABLE_NOTES[f"B01001_{_cell}{_suffix}"] = f"{_label}, {_what}"
del _cell, _label, _suffix, _what

GETVARS = list(ACS_VARIABLE_NOTES)

# The Census API rejects a `get=` list longer than 50 variables. GETVARS is
# past that, so `fetch_acs` splits it into chunks and merges the responses per
# tract GEOID. 48 leaves headroom for the geo columns the API appends
# (state/county/tract) inside the same 50-item budget.
MAX_GET_VARS = 48

# Raw tract-level ACS pull, cached once per vintage (data/raw/, gitignored) --
# same pattern as pluto.csv landing under data/raw/. The pull is
# (5 counties x ceil(len(GETVARS)/MAX_GET_VARS)) requests -- since the
# 2026-09-09 extension GETVARS is past the API's 50-variable cap, so it is no
# longer one request per county. All the more reason not to re-hit the Census
# API on every `loci acs` re-run, retry-on-lock included. The cache stores the
# variable list it was built with and invalidates itself when GETVARS changes.
ACS_TRACTS_CACHE_DIR = REPO_ROOT / "data" / "raw" / "acs"

# Citywide MEAN household income (GTM-109). Separate from the tract pull above
# because it is a single city-level scalar, not a per-hex surface: five
# county rows, one API call. B19025_001E is AGGREGATE household income (a sum
# of dollars, so it is additive across counties, unlike a median); B11001_001E
# is the household count. Their quotient is the household-weighted citywide
# mean -- Meltzer & Schuetz's own denominator.
CITYWIDE_INCOME_VARS = ["B19025_001E", "B19025_001M", "B11001_001E", "B11001_001M"]
CITYWIDE_INCOME_CACHE = REPO_ROOT / "data" / "interim" / "citywide_mean_hh_income.json"


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


def _acs_tracts_cache_path(year: int) -> pathlib.Path:
    return ACS_TRACTS_CACHE_DIR / f"tracts_{year}.json"


def fetch_acs(year: int = ACS_YEAR, refresh: bool = False) -> dict[str, dict]:
    """Cache-first tract-level ACS pull for all five NYC counties.

    Fails closed: raises if no Census API key is available rather than
    returning an empty/partial result that build_acs would silently ingest as
    zeros. `refresh=True` bypasses the cache and re-fetches from the API,
    overwriting it (use when GETVARS changes, as it just did for D54).
    """
    cache_path = _acs_tracts_cache_path(year)
    if not refresh and cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get("vars") == GETVARS and cached.get("acs_year") == year:
            return cached["tracts"]
        # GETVARS drifted from what's cached (e.g. this session's new fields) --
        # re-fetch rather than silently serving a stale/incomplete cache.

    key = _census_key()
    if not key:
        raise RuntimeError(
            "no CENSUS_API_KEY found (checked loci/.env and the environment). "
            "ACS tract demographics must be FETCHED, never guessed or zero-filled "
            "-- set the key and re-run."
        )
    chunks = [GETVARS[i:i + MAX_GET_VARS] for i in range(0, len(GETVARS), MAX_GET_VARS)]
    out: dict[str, dict] = {}
    for county in BORO_COUNTY.values():
        # One request per (county, chunk); chunks are MERGED per tract GEOID.
        # Every chunk must return the SAME tract set -- if a later chunk is
        # missing a tract the earlier one had, the merged record would be
        # silently short a variable and build_acs would treat that as a null
        # rather than as an error, so the mismatch raises instead.
        county_tracts: dict[str, dict] = {}
        seen_geoids: set[str] | None = None
        for chunk in chunks:
            resp = requests.get(
                f"https://api.census.gov/data/{year}/acs/acs5",
                params={"get": ",".join(chunk), "for": "tract:*",
                        "in": f"state:36 county:{county}", "key": key},
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()
            head = data[0]
            if len(data) <= 1:
                raise RuntimeError(f"ACS {year} 5-year returned no tract rows for county {county}")
            chunk_geoids = set()
            for row in data[1:]:
                rec = dict(zip(head, row))
                geoid = rec["state"] + rec["county"] + rec["tract"]
                chunk_geoids.add(geoid)
                county_tracts.setdefault(geoid, {}).update(rec)
            if seen_geoids is None:
                seen_geoids = chunk_geoids
            elif chunk_geoids != seen_geoids:
                raise RuntimeError(
                    f"ACS {year} chunked pull disagreed on the tract set for county "
                    f"{county}: {len(seen_geoids ^ chunk_geoids)} tracts present in one "
                    "chunk and not another -- merging would leave records with missing "
                    "variables silently read as nulls")
        # A merged record must carry EVERY requested variable. A chunk that
        # came back short (a bad variable name accepted with a partial row)
        # must not be ingested as zeros.
        for geoid, rec in county_tracts.items():
            missing = [v for v in GETVARS if v not in rec]
            if missing:
                raise RuntimeError(
                    f"ACS {year} tract {geoid} is missing {len(missing)} requested "
                    f"variables after merging chunks (first: {missing[0]}) -- the "
                    "chunked fetch did not reassemble a complete record")
        out.update(county_tracts)
    if not out:
        raise RuntimeError(f"ACS {year} 5-year tract pull returned zero tracts across all counties")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "acs_year": year, "vars": GETVARS, "tracts": out,
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }))
    return out


def fetch_citywide_mean_hh_income(year: int = ACS_YEAR) -> dict:
    """One ACS call: the citywide MEAN household income for the five NYC
    counties, household-weighted.

        mean = sum(B19025_001E) / sum(B11001_001E)   over 36005/36047/36061/36081/36085

    This is the denominator Meltzer & Schuetz use for their "< 80% of citywide
    mean household income" cutoff. It is NOT what gaps.py computed before
    GTM-109, which was `sum(population * median_hh_income) / sum(population)`
    over hexes -- a POPULATION-weighted mean of tract MEDIANS ($88,154). That
    quantity is (a) not a mean, (b) weighted by people rather than households,
    and (c) not comparable to a mean in a right-skewed income distribution, so
    it made the cutoff materially stricter than the paper's.

    Aggregate income is a dollar SUM, so it adds across counties exactly; the
    county MOEs combine as the root sum of squares. The mean's own MOE uses the
    ACS derived-ratio approximation (see `moe` below).

    Requires a Census API key (`CENSUS_API_KEY` in loci/.env or the
    environment) -- the same key and the same 5-year vintage `fetch_acs` uses.
    """
    key = _census_key()
    if not key:
        raise RuntimeError(
            "no CENSUS_API_KEY found (checked loci/.env and the environment). The "
            "citywide mean household income must be FETCHED from ACS B19025/B11001, "
            "never guessed -- set the key and re-run."
        )
    resp = requests.get(
        f"https://api.census.gov/data/{year}/acs/acs5",
        params={"get": ",".join(CITYWIDE_INCOME_VARS),
                "for": "county:" + ",".join(sorted(BORO_COUNTY.values())),
                "in": "state:36", "key": key},
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    head, rows = data[0], data[1:]

    agg = agg_m2 = hh = hh_m2 = 0.0
    counties = []
    for row in rows:
        rec = dict(zip(head, row))
        a, am = _clean(rec["B19025_001E"]), _clean(rec["B19025_001M"])
        h_, hm = _clean(rec["B11001_001E"]), _clean(rec["B11001_001M"])
        if a is None or h_ is None:
            raise RuntimeError(f"ACS returned no B19025/B11001 for county {rec.get('county')}")
        agg += a
        hh += h_
        agg_m2 += (am or 0.0) ** 2
        hh_m2 += (hm or 0.0) ** 2
        counties.append(rec["state"] + rec["county"])

    mean = agg / hh
    # ACS derived-RATIO MOE (ACS General Handbook, "Calculating MOEs for
    # Derived Ratios"): MOE(X/Y) ~= (1/Y) * sqrt(MOE_X^2 + R^2 * MOE_Y^2).
    # Households are a subset of nothing here -- aggregate dollars over
    # household counts is a true ratio, not a proportion, so the term ADDS.
    moe = math.sqrt((agg_m2) + (mean ** 2) * (hh_m2)) / hh
    return {
        "acs_year": year,
        "mean_hh_income": mean,
        "mean_hh_income_moe": moe,
        "aggregate_household_income": agg,
        "households": hh,
        "counties": sorted(counties),
        "vars": CITYWIDE_INCOME_VARS,
        "source": (f"ACS {year} 5-year, B19025_001E / B11001_001E summed over the five "
                   "NYC counties (api.census.gov/data/{y}/acs/acs5)".format(y=year)),
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }


def load_citywide_mean_hh_income(year: int = ACS_YEAR, refresh: bool = False) -> dict:
    """Cache-first accessor for `fetch_citywide_mean_hh_income`.

    The value is one scalar per ACS vintage, so it is cached as JSON under
    `data/interim/` (the existing pattern -- cf. `nta_names.json`,
    `google_calls.json`) rather than as a DuckDB table: nothing joins to it.
    `refresh=True` re-fetches and rewrites the cache.

    Fails closed. If the cache is absent for `year` and no Census key is
    available, this raises rather than falling back to a hardcoded dollar
    figure -- a wrong denominator here silently moves the low-income cutoff for
    the whole screen.
    """
    if not refresh and CITYWIDE_INCOME_CACHE.exists():
        try:
            cached = json.loads(CITYWIDE_INCOME_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            cached = None
        if cached and cached.get("acs_year") == year and cached.get("mean_hh_income"):
            return cached
    rec = fetch_citywide_mean_hh_income(year)
    CITYWIDE_INCOME_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CITYWIDE_INCOME_CACHE.write_text(json.dumps(rec, indent=2) + "\n")
    return rec


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


def _moe_proportion(x: float, x_moe: float, y: float, y_moe: float) -> float | None:
    """ACS handbook MOE for a proportion p = X/Y where X is a subset of Y
    (e.g. renter-occupied units within all occupied units, or no-vehicle
    households within all households).

        MOE_p = (1/Y) * sqrt(MOE_X^2 - p^2 * MOE_Y^2)

    Falls back to the general ratio formula (addition instead of subtraction)
    when the subtraction goes negative -- the handbook's own documented case,
    which happens when p is near 0 or near 1. That fallback OVERSTATES MOE_p
    (conservative), never understates it, so it never manufactures a false
    "precise" reading. Both this formula and the sum rule used to build X and
    Y assume independence (across tracts for the sum; between X and Y here)
    that the handbook itself flags as an approximation.
    """
    if y is None or y <= 0 or x is None or x_moe is None or y_moe is None:
        return None
    p = x / y
    under_sqrt = x_moe ** 2 - (p ** 2) * (y_moe ** 2)
    if under_sqrt < 0:
        under_sqrt = x_moe ** 2 + (p ** 2) * (y_moe ** 2)
    return math.sqrt(under_sqrt) / y


def _sum_cells(rec: dict, cells: tuple[str, ...]) -> tuple[float | None, float | None]:
    """(estimate, MOE) for a sum of ACS cells WITHIN one tract -- the handbook
    sum rule: estimates add, MOEs combine as the root sum of squares.

    `cells` are variable stems without the E/M suffix (e.g. "B01001_003").
    Returns (None, None) if every cell is null/jammed, so the caller can skip
    the tract rather than record a spurious zero. A cell that is individually
    null contributes nothing to either the estimate or the MOE -- that is a
    small downward bias in both, and it is why the fail-loud cross-checks
    above matter more than a null guard here.
    """
    est = 0.0
    m2 = 0.0
    seen = False
    for stem in cells:
        e = _clean(rec.get(stem + "E"))
        m = _clean(rec.get(stem + "M"))
        if e is not None:
            est += e
            seen = True
        if m is not None:
            m2 += m ** 2
    if not seen:
        return None, None
    return est, math.sqrt(m2)


def build_acs(con, pluto_csv: pathlib.Path | str = PLUTO_CSV, year: int = ACS_YEAR) -> int:
    th = _tract_hex_weights(con, pathlib.Path(pluto_csv))
    acs = fetch_acs(year)

    # Cross-table sanity check (fail loud, not silent): B25044's total
    # (owner + renter occupied) should equal B25003's total occupied-unit
    # count for the same tract, within ACS rounding/disclosure-avoidance
    # noise. A material average mismatch would mean a cell index is wrong --
    # exactly the mistake this ingest was warned against blindly repeating.
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
    if denom > 0:
        rel = sum(diffs) / denom
        if rel > 0.02:
            raise RuntimeError(
                f"B25044/B25003 tract-total cross-check failed: aggregate relative "
                f"discrepancy {rel:.1%} across NYC tracts (expect near 0, ACS noise "
                "only) -- re-verify the B25044 cell indices against "
                "api.census.gov/data/{y}/acs/acs5/variables.json before trusting this "
                "pull".format(y=year))

    # Second cross-table check, same fail-loud principle (2026-09-09): B01001
    # (sex by age) and B01003 (total population) are two different tables that
    # must report the SAME tract population. If they do not, an age cell index
    # is wrong or a chunk merged badly -- either way the age-band shares would
    # be silently mis-normalised, so raise rather than ingest.
    age_diffs, age_denom = [], 0.0
    for rec in acs.values():
        pop_b01003 = _clean(rec.get("B01003_001E"))
        pop_b01001 = _clean(rec.get("B01001_001E"))
        if pop_b01003 is None or pop_b01001 is None:
            continue
        age_diffs.append(abs(pop_b01001 - pop_b01003))
        age_denom += pop_b01003
    if age_denom > 0:
        rel = sum(age_diffs) / age_denom
        if rel > 0.02:
            raise RuntimeError(
                f"B01001/B01003 tract-population cross-check failed: aggregate "
                f"relative discrepancy {rel:.1%} across NYC tracts (expect 0 -- the "
                "two tables share a universe) -- re-verify the B01001 cell indices "
                "against api.census.gov/data/{y}/acs/acs5/variables.json before "
                "trusting this pull".format(y=year))

    agg = collections.defaultdict(lambda: dict(
        pop=0.0, pop_m2=0.0, hh=0.0, hh_m2=0.0,
        inc_num=0.0, inc_m_num=0.0, inc_w=0.0,
        # B25003: renter_share numerator/denominator (apportioned sums + RSS)
        rent_num=0.0, rent_num_m2=0.0, occ_den=0.0, occ_den_m2=0.0,
        # B08201: zero_vehicle_hh_share numerator/denominator
        veh0_num=0.0, veh0_num_m2=0.0, veh_den=0.0, veh_den_m2=0.0,
        # B25044 owner: zero_vehicle_owner_share numerator/denominator
        own0_num=0.0, own0_num_m2=0.0, own_den=0.0, own_den_m2=0.0,
        # B25044 renter: zero_vehicle_renter_share numerator/denominator
        rt0_num=0.0, rt0_num_m2=0.0, rt_den=0.0, rt_den_m2=0.0,
        # 2026-09-09 extension: one num/den pair per SHARE_SPECS entry and one
        # weighted-average accumulator per INTENSIVE_SPECS entry.
        **{f"{col}_{part}": 0.0
           for col in SHARE_SPECS
           for part in ("num", "num_m2", "den", "den_m2")},
        **{f"{col}_{part}": 0.0
           for col in INTENSIVE_SPECS
           for part in ("num", "m_num", "w")}))
    for r in th.itertuples(index=False):
        rec = acs.get(r.geoid)
        if not rec:
            continue
        w, a = r.w, agg[r.h3_index]
        pop, pm = _clean(rec["B01003_001E"]), _clean(rec["B01003_001M"])
        hh, hm = _clean(rec["B11001_001E"]), _clean(rec["B11001_001M"])
        inc, im = _clean(rec["B19013_001E"]), _clean(rec["B19013_001M"])
        occ, occ_m = _clean(rec["B25003_001E"]), _clean(rec["B25003_001M"])
        rent, rent_m = _clean(rec["B25003_003E"]), _clean(rec["B25003_003M"])
        veh_tot, veh_tot_m = _clean(rec["B08201_001E"]), _clean(rec["B08201_001M"])
        veh0, veh0_m = _clean(rec["B08201_002E"]), _clean(rec["B08201_002M"])
        own_tot, own_tot_m = _clean(rec["B25044_002E"]), _clean(rec["B25044_002M"])
        own0, own0_m = _clean(rec["B25044_003E"]), _clean(rec["B25044_003M"])
        rt_tot, rt_tot_m = _clean(rec["B25044_009E"]), _clean(rec["B25044_009M"])
        rt0, rt0_m = _clean(rec["B25044_010E"]), _clean(rec["B25044_010M"])

        if pop is not None: a["pop"] += w * pop
        if pm is not None: a["pop_m2"] += (w * pm) ** 2
        if hh is not None: a["hh"] += w * hh
        if hm is not None: a["hh_m2"] += (w * hm) ** 2
        if inc is not None:
            a["inc_num"] += w * inc; a["inc_w"] += w
            if im is not None: a["inc_m_num"] += w * im

        if occ is not None: a["occ_den"] += w * occ
        if occ_m is not None: a["occ_den_m2"] += (w * occ_m) ** 2
        if rent is not None: a["rent_num"] += w * rent
        if rent_m is not None: a["rent_num_m2"] += (w * rent_m) ** 2

        if veh_tot is not None: a["veh_den"] += w * veh_tot
        if veh_tot_m is not None: a["veh_den_m2"] += (w * veh_tot_m) ** 2
        if veh0 is not None: a["veh0_num"] += w * veh0
        if veh0_m is not None: a["veh0_num_m2"] += (w * veh0_m) ** 2

        if own_tot is not None: a["own_den"] += w * own_tot
        if own_tot_m is not None: a["own_den_m2"] += (w * own_tot_m) ** 2
        if own0 is not None: a["own0_num"] += w * own0
        if own0_m is not None: a["own0_num_m2"] += (w * own0_m) ** 2

        if rt_tot is not None: a["rt_den"] += w * rt_tot
        if rt_tot_m is not None: a["rt_den_m2"] += (w * rt_tot_m) ** 2
        if rt0 is not None: a["rt0_num"] += w * rt0
        if rt0_m is not None: a["rt0_num_m2"] += (w * rt0_m) ** 2

        # ---- 2026-09-09 extension: shares and intensive fields, table-driven ----
        for col, (num_cells, den_cell) in SHARE_SPECS.items():
            n_est, n_moe = _sum_cells(rec, num_cells)
            d_est, d_moe = _sum_cells(rec, (den_cell,))
            if n_est is not None: a[f"{col}_num"] += w * n_est
            if n_moe is not None: a[f"{col}_num_m2"] += (w * n_moe) ** 2
            if d_est is not None: a[f"{col}_den"] += w * d_est
            if d_moe is not None: a[f"{col}_den_m2"] += (w * d_moe) ** 2

        for col, stem in INTENSIVE_SPECS.items():
            v, vm = _clean(rec.get(stem + "E")), _clean(rec.get(stem + "M"))
            if v is not None:
                a[f"{col}_num"] += w * v
                a[f"{col}_w"] += w
                if vm is not None:
                    a[f"{col}_m_num"] += w * vm

    rows = []
    for h, a in agg.items():
        inc = a["inc_num"] / a["inc_w"] if a["inc_w"] > 0 else None
        inc_m = a["inc_m_num"] / a["inc_w"] if a["inc_w"] > 0 else None

        occ_den, occ_den_moe = a["occ_den"], math.sqrt(a["occ_den_m2"])
        rent_num, rent_num_moe = a["rent_num"], math.sqrt(a["rent_num_m2"])
        renter_share = rent_num / occ_den if occ_den > 0 else None
        renter_share_moe = (_moe_proportion(rent_num, rent_num_moe, occ_den, occ_den_moe)
                            if occ_den > 0 else None)

        veh_den, veh_den_moe = a["veh_den"], math.sqrt(a["veh_den_m2"])
        veh0_num, veh0_num_moe = a["veh0_num"], math.sqrt(a["veh0_num_m2"])
        zero_vehicle_hh_share = veh0_num / veh_den if veh_den > 0 else None
        zero_vehicle_hh_share_moe = (_moe_proportion(veh0_num, veh0_num_moe, veh_den, veh_den_moe)
                                     if veh_den > 0 else None)

        own_den, own_den_moe = a["own_den"], math.sqrt(a["own_den_m2"])
        own0_num, own0_num_moe = a["own0_num"], math.sqrt(a["own0_num_m2"])
        zero_vehicle_owner_share = own0_num / own_den if own_den > 0 else None
        zero_vehicle_owner_share_moe = (_moe_proportion(own0_num, own0_num_moe, own_den, own_den_moe)
                                        if own_den > 0 else None)

        rt_den, rt_den_moe = a["rt_den"], math.sqrt(a["rt_den_m2"])
        rt0_num, rt0_num_moe = a["rt0_num"], math.sqrt(a["rt0_num_m2"])
        zero_vehicle_renter_share = rt0_num / rt_den if rt_den > 0 else None
        zero_vehicle_renter_share_moe = (_moe_proportion(rt0_num, rt0_num_moe, rt_den, rt_den_moe)
                                         if rt_den > 0 else None)

        row = [
            h, year, a["pop"], math.sqrt(a["pop_m2"]), a["hh"], math.sqrt(a["hh_m2"]),
            inc, inc_m, renter_share, renter_share_moe,
            zero_vehicle_hh_share, zero_vehicle_hh_share_moe,
            zero_vehicle_owner_share, zero_vehicle_owner_share_moe,
            zero_vehicle_renter_share, zero_vehicle_renter_share_moe,
        ]
        # 2026-09-09: intensive first (median_age, avg_hh_size), then the
        # shares -- the order here must stay in step with `columns` below,
        # which is why both are built from the same two spec dicts.
        for col in INTENSIVE_SPECS:
            wsum = a[f"{col}_w"]
            row.append(a[f"{col}_num"] / wsum if wsum > 0 else None)
            row.append(a[f"{col}_m_num"] / wsum if wsum > 0 else None)
        for col in SHARE_SPECS:
            den, den_moe = a[f"{col}_den"], math.sqrt(a[f"{col}_den_m2"])
            num, num_moe = a[f"{col}_num"], math.sqrt(a[f"{col}_num_m2"])
            row.append(num / den if den > 0 else None)
            row.append(_moe_proportion(num, num_moe, den, den_moe) if den > 0 else None)
        rows.append(tuple(row))

    columns = [
        "h3_index", "acs_year", "population", "population_moe", "households",
        "households_moe", "median_hh_income", "median_hh_income_moe",
        "renter_share", "renter_share_moe",
        "zero_vehicle_hh_share", "zero_vehicle_hh_share_moe",
        "zero_vehicle_owner_share", "zero_vehicle_owner_share_moe",
        "zero_vehicle_renter_share", "zero_vehicle_renter_share_moe",
    ]
    for col in INTENSIVE_SPECS:
        columns += [col, f"{col}_moe"]
    for col in SHARE_SPECS:
        columns += [col, f"{col}_moe"]
    df = pd.DataFrame(rows, columns=columns)

    con.execute("DELETE FROM analysis.hex_demographics WHERE acs_year = ?", [year])
    con.register("_acs", df)
    try:
        # Name the target columns explicitly rather than relying on the
        # positional order of ALTER-added columns -- with 38 columns, a
        # positional INSERT is one appended column away from writing
        # black_nh_share into asian_nh_share with no error at all.
        collist = ", ".join(df.columns)
        con.execute(
            f"INSERT INTO analysis.hex_demographics ({collist}) SELECT {collist} FROM _acs")
    finally:
        con.unregister("_acs")
    return len(df)
