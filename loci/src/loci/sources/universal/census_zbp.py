"""Census ZIP Business Patterns (ZBP), via the County Business Patterns (CBP)
API -- VALIDATION AND CALIBRATION ONLY (registry.yaml `census_zbp`;
docs/CHECKPOINT.md ZBP-validation ticket).

Why this exists: Meltzer & Schuetz (2012) used ZBP establishment counts by
NAICS as their retail measure. Loci has no establishment-count source
independent of its own POI feeds, so ZBP gives an external, free check on
per-category POI coverage by ZIP, establishment size bands (a small-format
vs. supermarket distinction a count-based screen cannot see, QUESTIONS D9),
and establishments-per-resident as a revealed floor for the minimum-viable-
catchment question (O6). ZIP is far coarser than Loci's geography of record
(residential address / hex) -- this NEVER feeds staging.poi or the gap flag.

PROBE FINDINGS (2026-09-05, recorded here per CLAUDE.md's "verify the real
capability first" rule -- see also registry.yaml `census_zbp` for the
condensed version):

* The standalone `zbp` dataset (api.census.gov/data/{year}/zbp) serves ONLY
  1994-2018 -- confirmed by probing variables.json for 2018-2023 (2018 = 200,
  2019-2023 all 404). Census's own page confirms why: "Starting with
  reference year 2019, ZIP Code Business Patterns data will be available as
  part of the County Business Patterns (CBP) API."
* From 2019 on, ZBP lives inside the CBP API (api.census.gov/data/{year}/cbp)
  under `for=zipcode:<...>` geography. Confirmed working for 2019-2023;
  2024 returns 404 (not yet published as of this probe) -- so DEFAULT_YEAR
  is 2023, the latest available vintage.
* `for=zipcode:*` works with NO state filter -- `in=state:36` is REJECTED
  ("unknown/unsupported geography hierarchy": ZIP geography is not nested
  under state in this API). A COMMA-SEPARATED zipcode list IS accepted, e.g.
  `for=zipcode:11206,11207,10001`, and is what this adapter uses: one request
  for all 217 NYC PLUTO postcodes returns ~137.5k rows (all NAICS levels x
  all EMPSZES bands x 217 zips) in about 14 seconds, ~13.8 MB. No pagination
  or rate-limiting was needed for a pull this size.
* NAICS2017 is returned at EVERY level (2, 3, 4, 5, 6 digit) in the same
  response, duplicating the same ESTAB total at each ancestor level. Filter
  to 6-digit codes for the finest, non-redundant granularity (confirmed:
  37,804 of 137,507 rows for the NYC pull are 6-digit).
* EMPSZES / EMPSZES_LABEL bands actually returned (verified against a live
  pull, not assumed from documentation):
      001  All establishments
      210  Establishments with less than 5 employees
      220  Establishments with 5 to 9 employees
      230  Establishments with 10 to 19 employees
      241  Establishments with 20 to 49 employees
      242  Establishments with 50 to 99 employees
      251  Establishments with 100 to 249 employees
      252  Establishments with 250 to 499 employees
      254  Establishments with 500 to 999 employees
      260  Establishments with 1,000 employees or more
* Suppression: no ESTAB_F (flag) value was ever non-null in spot checks, and
  the API does not return a placeholder/zero row for a suppressed cell -- it
  simply omits the row. A (zip, naics, band) combination absent from the
  response is NOT evidence of zero establishments; only trust "zero" when the
  '001' (All establishments) band is present and itself zero, which does not
  occur in practice (a present NAICS/zip combination has an ESTAB > 0).
* Noise infusion: Census applies a disclosure-avoidance noise-injection
  method to published ESTAB counts (in place since the mid-2000s, revised
  2017) -- expect published county-level ESTAB sums to not always equal the
  sum of the ZIP-level rows exactly, and treat single-digit ESTAB counts in
  a small ZIP as approximate, not exact.

SECOND PROBE (2026-09-16): THE YEAR CAP IS GONE
---------------------------------------------------------------------------
This module used to carry `DEFAULT_YEAR = 2023` and pull ONE vintage. ZBP is
an annual series; pulling one year of it was a cap, not a limit of the source.
Every served year is now pulled, keyed by year. What the live probe found:

* The two endpoints between them cover **1994-2023**, with 2018 served by
  both. Neither covers anything outside that: `zbp` 1993 -> 404, `cbp` 2024
  -> 404. Both ends are UPSTREAM limits.
      1994-2018   api.census.gov/data/<year>/zbp   (standalone ZBP dataset)
      2019-2023   api.census.gov/data/<year>/cbp   under `for=zipcode:...`
  2018 is pulled from `zbp`, matching Census's own statement that CBP carries
  ZBP only "starting with reference year 2019".

* The classification VARIABLE, its LABEL variable and the GEOGRAPHY name all
  move underneath you. Verified, year by year, against variables.json and a
  live 3-ZIP request:

      1994-1997  zbp  SIC        SIC_TTL     for=zipcode:   EMPSZES_TTL
      1998-2002  zbp  NAICS1997  NAICS_TTL   for=zipcode:   EMPSZES_TTL
      2003-2007  zbp  NAICS2002  NAICS_TTL   for=zipcode:   EMPSZES_TTL
      2008-2011  zbp  NAICS2007  NAICS_TTL   for=zipcode:   EMPSZES_TTL
      2012-2016  zbp  NAICS2012  (none)      for=zip code:  (none)
      2017-2018  zbp  NAICS2017  (none)      for=zip code:  (none)
      2019-2023  cbp  NAICS2017  NAICS2017_LABEL  for=zipcode:  EMPSZES_LABEL

  Note there is NO label variable at all for 2012-2018, which is why the
  emp-size band label is derived from the EMPSZES CODE for every year rather
  than read off the response: one rule, all years, no year silently NULL.

* **The emp-size band codes changed in 2017 and it is a DEFINITION change, not
  a data change.** 1994-2016 publish band `212` = "Establishments with 1 to 4
  employees". 2017-2023 publish band `210` = "Establishments with less than 5
  employees". Both are landed under the 2017+ label so the series joins and
  `analysis.zip_category_establishments.estab_small_1_4` is populated in every
  year -- but "1 to 4" and "less than 5" are not the same set (the second can
  admit a zero-employee establishment), so a level shift at 2017 in that one
  band is a classification artifact first and a finding second. `BAND_ERAS`
  below keeps the raw code per era so the break stays visible in code, and
  every ingest summary reports the raw band codes the year actually returned.

* SIC YEARS ARE NOT INGESTED, AND THAT IS OUR LIMIT, NOT CENSUS'S. 1994-1997
  are served and return data. They are skipped because `analysis.zip_
  establishments.naics` means a NAICS code and this project holds exactly one
  industry crosswalk, in NAICS (D42). Landing SIC codes in a column named
  `naics`, or inventing a SIC crosswalk to avoid that, are both worse than
  saying so. The ingest records those years as explicitly absent, with this
  reason, instead of skipping them quietly.

* NAICS RENUMBERING makes three crosswalk codes genuinely unavailable before
  2012 -- the two restaurant codes and the coffee-shop code were introduced in
  NAICS 2012. For 1998-2011 the per-category rollup therefore has no
  restaurant and no cafe_bakery row from that side of the crosswalk. The
  ingest reports this per year (`categories_absent`) rather than writing a
  zero, because a zero would say New York had no restaurants in 2008.
"""
from __future__ import annotations

import os
import pathlib
import time
from collections.abc import Iterable

import pandas as pd
import requests

from loci.grid.pluto import PLUTO_CSV

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
SOURCE_ID = "census_zbp"
BASE_URL = "https://api.census.gov/data"
MAX_RETRIES = 3
BACKOFF_S = 5.0

#: First and last year ZIP business patterns are served AT ALL, across both
#: endpoints. UPSTREAM limits: 1993 404s on `zbp`, 2024 404s on `cbp`.
ZBP_FIRST_YEAR = 1994
ZBP_LAST_YEAR = 2023

#: The year the series moves from the standalone `zbp` dataset to `cbp`.
#: Census: "Starting with reference year 2019, ZIP Code Business Patterns data
#: will be available as part of the County Business Patterns (CBP) API."
FIRST_CBP_ZIP_YEAR = 2019

#: The first year classified under NAICS rather than SIC. Everything before it
#: is served but not ingested -- see the docstring, "OUR limit, not Census's".
FIRST_NAICS_YEAR = 1998


class ZbpYearUnavailable(RuntimeError):
    """`year` cannot be ingested and the reason is named. Separate from a
    transport failure so a year loop can record an explicit absence instead of
    writing zero rows for that year."""

    def __init__(self, year: int, reason: str):
        self.year = year
        self.reason = reason
        super().__init__(f"ZBP {year}: {reason}")


def era(year: int) -> dict:
    """Everything that varies by year, in one place: which dataset serves it,
    what the industry variable is called, whether a label variable exists at
    all, and what goes after `for=`.

    Every request in this module goes through this. Hardcoding NAICS2017 and
    EMPSZES_LABEL -- which is what the single-year version did -- produces a
    400 for every year before 2019, and a year loop that swallowed those would
    publish a 26-year table containing five years of data.
    """
    if not ZBP_FIRST_YEAR <= year <= ZBP_LAST_YEAR:
        raise ZbpYearUnavailable(
            year, f"outside the served range {ZBP_FIRST_YEAR}-{ZBP_LAST_YEAR} "
                  f"(UPSTREAM: both /zbp and /cbp 404 for this year)")
    if year >= FIRST_CBP_ZIP_YEAR:
        return {"dataset": "cbp", "classification": "NAICS2017",
                "label": "NAICS2017_LABEL", "geo": "zipcode"}
    if year >= 2017:
        return {"dataset": "zbp", "classification": "NAICS2017",
                "label": None, "geo": "zip code"}
    if year >= 2012:
        return {"dataset": "zbp", "classification": "NAICS2012",
                "label": None, "geo": "zip code"}
    if year >= 2008:
        return {"dataset": "zbp", "classification": "NAICS2007",
                "label": "NAICS_TTL", "geo": "zipcode"}
    if year >= 2003:
        return {"dataset": "zbp", "classification": "NAICS2002",
                "label": "NAICS_TTL", "geo": "zipcode"}
    if year >= FIRST_NAICS_YEAR:
        return {"dataset": "zbp", "classification": "NAICS1997",
                "label": "NAICS_TTL", "geo": "zipcode"}
    return {"dataset": "zbp", "classification": "SIC",
            "label": "SIC_TTL", "geo": "zipcode"}


def ingestable_years() -> tuple[int, ...]:
    """Every year that can land in `analysis.zip_establishments`: 1998-2023.
    1994-1997 are served but SIC-classified; see the module docstring."""
    return tuple(range(FIRST_NAICS_YEAR, ZBP_LAST_YEAR + 1))


def served_years() -> tuple[int, ...]:
    """Every year either endpoint answers for: 1994-2023."""
    return tuple(range(ZBP_FIRST_YEAR, ZBP_LAST_YEAR + 1))


def _require_ingestable(year: int) -> dict:
    spec = era(year)
    if not spec["classification"].startswith("NAICS"):
        raise ZbpYearUnavailable(
            year,
            f"classified under {spec['classification']}, not NAICS. Census serves "
            f"it; this project cannot land it, because analysis.zip_establishments."
            f"naics means a NAICS code and there is exactly one industry crosswalk "
            f"in this repo and it is NAICS (D42). Mapping SIC is an owner decision, "
            f"not an adapter's.")
    return spec


def getvars(year: int) -> list[str]:
    """The `get=` list for `year` -- label variables only where they exist."""
    spec = era(year)
    out = ["ESTAB", "EMPSZES", spec["classification"]]
    if spec["label"]:
        out.append(spec["label"])
    return out


#: Kept so a caller that passes no year still resolves to a real vintage. It is
#: NOT a cap: `build_all_years` ignores it and walks the whole series.
DEFAULT_YEAR = ZBP_LAST_YEAR
GETVARS = getvars(DEFAULT_YEAR)

# Emp-size bands actually returned by the API (see docstring). '001' is the
# total; the rest partition it. Order matches the CBP EMPSZES code order.
#
# This dict is the 2017+ vocabulary. BAND_ERAS below records that 1994-2016
# publish '212' ("1 to 4 employees") where 2017+ publish '210' ("less than 5"),
# and _band_label() folds the two so one series exists -- a fold that is a
# JUDGEMENT, documented in the module docstring, not a silent equivalence.
EMPSZES_LABELS = {
    "001": "All establishments",
    "210": "Establishments with less than 5 employees",
    "220": "Establishments with 5 to 9 employees",
    "230": "Establishments with 10 to 19 employees",
    "241": "Establishments with 20 to 49 employees",
    "242": "Establishments with 50 to 99 employees",
    "251": "Establishments with 100 to 249 employees",
    "252": "Establishments with 250 to 499 employees",
    "254": "Establishments with 500 to 999 employees",
    "260": "Establishments with 1,000 employees or more",
}
# The four labels analysis.zip_category_establishments buckets into; anything
# else that isn't '001' rolls into estab_20_plus.
_LABEL_1_4 = EMPSZES_LABELS["210"]
_LABEL_5_9 = EMPSZES_LABELS["220"]
_LABEL_10_19 = EMPSZES_LABELS["230"]
_LABEL_TOTAL = EMPSZES_LABELS["001"]

#: The smallest-band code by era, verified against live EMPSZES_TTL responses
#: for 1994 / 1998 / 2008 / 2011 (all '212' = "Establishments with 1 to 4
#: employees") and EMPSZES_LABEL for 2019 / 2023 (both '210' = "Establishments
#: with less than 5 employees"). Kept as data so the 2017 break is greppable.
BAND_ERAS = {
    "1994-2016": {"smallest_band_code": "212",
                  "published_label": "Establishments with 1 to 4 employees"},
    "2017-2023": {"smallest_band_code": "210",
                  "published_label": _LABEL_1_4},
}
#: Raw EMPSZES code -> the label this project stores in `emp_size_band`.
#: '212' folds onto '210' deliberately; see BAND_ERAS and the docstring.
BAND_CODE_TO_LABEL = {**EMPSZES_LABELS, "212": _LABEL_1_4}


def _band_label(code: str) -> str:
    """Store the label for an EMPSZES CODE, never the label the response
    happened to carry: 2012-2018 carry no label variable at all, so reading one
    off the response would leave seven years with a NULL band and a rollup that
    quietly summed nothing."""
    try:
        return BAND_CODE_TO_LABEL[code]
    except KeyError:
        raise RuntimeError(
            f"unknown CBP/ZBP EMPSZES band code {code!r}. Every code seen in the "
            f"1994-2023 probe is in BAND_CODE_TO_LABEL; a new one means Census "
            f"changed the vocabulary again and the fold needs re-deciding, not "
            f"a row dropped on the floor.") from None


def _census_key() -> str:
    """Same lookup order as loci.grid.acs._census_key (duplicated, not
    imported: adapters under sources/ are self-contained by convention).
    Checked-in .env wins only if no real environment variable is set."""
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CENSUS_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key:
                    return key
    return os.environ.get("CENSUS_API_KEY", "")


def nyc_zip_list(con) -> list[str]:
    """Distinct 5-digit ZIPs (PLUTO `postcode`) across all five boroughs.
    This is the NYC ZIP universe for the adapter -- derived from data already
    on disk rather than a hardcoded prefix range. 217 ZIPs as of the 2026
    PLUTO export (2026-09-05 probe); a handful are low-lot-count edge cases
    (e.g. Rikers/park-adjacent codes) which `zbp-compare` excludes downstream
    via the population < 1,000 filter, not here -- ingest keeps every ZIP
    PLUTO reports so the raw table is a faithful landing, not a pre-filtered one.
    """
    df = con.execute(
        """
        SELECT DISTINCT postcode
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE postcode SIMILAR TO '[0-9]{5}'
        ORDER BY 1
        """,
        [str(PLUTO_CSV)],
    ).df()
    return df["postcode"].tolist()


def fetch_zbp(zips: Iterable[str], year: int = DEFAULT_YEAR,
              *, session: requests.Session | None = None) -> list[dict]:
    """One CBP API request for every zip in `zips` (comma-joined -- confirmed
    to work for 217 ZIPs in the probe above). Raises on total failure (no
    silent empty result): a bad key, a network failure, or a non-2xx status
    after MAX_RETRIES attempts all raise RuntimeError with the underlying
    error message, per the project rule that live-API sources must fail loud.
    """
    key = _census_key()
    if not key:
        raise RuntimeError(
            "CENSUS_API_KEY is not set (checked loci/.env and the process "
            "environment). ZBP ingest cannot proceed without it -- see "
            "https://api.census.gov/data/key_signup.html."
        )
    zip_list = list(zips)
    if not zip_list:
        raise RuntimeError("nyc_zip_list() returned no ZIPs -- refusing to run an empty ZBP pull.")

    spec = _require_ingestable(year)
    session = session or requests.Session()
    params = {"get": ",".join(getvars(year)),
              "for": f"{spec['geo']}:{','.join(zip_list)}", "key": key}
    url = f"{BASE_URL}/{year}/{spec['dataset']}"

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=180)
            resp.raise_for_status()
            body = resp.json()
            break
        except Exception as exc:  # noqa: BLE001 - re-raised below with context
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_S * attempt)
    else:
        raise RuntimeError(
            f"Census CBP API request failed after {MAX_RETRIES} attempts "
            f"(year={year}, {len(zip_list)} zips): {last_exc}"
        ) from last_exc

    if not isinstance(body, list) or len(body) < 1:
        raise RuntimeError(f"Census CBP API returned an unexpected body shape: {body!r}")

    header, *data_rows = body
    return [dict(zip(header, row)) for row in data_rows]


def request_plan(con, year: int = DEFAULT_YEAR) -> dict:
    """What `--dry-run` prints before touching the network: the exact request
    shape, with no fetch performed."""
    zips = nyc_zip_list(con)
    spec = era(year)
    return {
        "year": year,
        "url": f"{BASE_URL}/{year}/{spec['dataset']}",
        "get": ",".join(getvars(year)),
        "classification": spec["classification"],
        "n_zips": len(zips),
        "for": f"{spec['geo']}:{zips[0]},{zips[1]},...,{zips[-1]} "
               f"({len(zips)} zips total)",
    }


def _finest_level(rows: list[dict], year: int = DEFAULT_YEAR) -> pd.DataFrame:
    """Rows -> DataFrame, filtered to 6-digit NAICS (the finest level; see
    docstring). Coarser 2-5 digit rollups are dropped, not stored.

    `year` selects the era: which column carries the code, whether a label
    column exists, and what the ZIP column is called. The 6-digit filter is
    `len == 6 AND all digits` rather than `len == 6`, because the pre-2012
    responses right-pad codes with spaces -- the all-industries total comes
    back as `'00    '`, which is six characters and is not an industry.
    """
    spec = era(year)
    cls, lbl = spec["classification"], spec["label"]
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(
            f"ZBP {year}: the API returned a header and no data rows. That is "
            f"never a real year for 217 NYC ZIPs; refusing to land zero rows.")
    df = df.rename(columns={"zip code": "zipcode"})
    code = df[cls].astype(str)
    df = df[(code.str.len() == 6) & code.str.isdigit()].copy()
    df["naics"] = df[cls].astype(str)
    df["naics_label"] = df[lbl] if lbl else pd.NA
    df["emp_size_band"] = df["EMPSZES"].astype(str).map(_band_label)
    df["estab"] = pd.to_numeric(df["ESTAB"], errors="coerce")
    df = df.dropna(subset=["estab"])
    df["estab"] = df["estab"].astype(int)
    # Suppressed/ragged cells come back negative in some early vintages; the
    # schema's CHECK (estab >= 0) would reject the whole insert on one of them.
    df = df[df["estab"] >= 0]
    return df[["zipcode", "naics", "naics_label", "emp_size_band", "estab"]]


def categories_absent(df: pd.DataFrame) -> dict[str, list[str]]:
    """{category: [crosswalk codes this pull did not contain]} for categories
    that came back with NO code at all.

    This is the guard against the NAICS-renumbering trap. The two restaurant
    codes and the coffee-shop code were introduced in NAICS 2012; for any year
    before that they are absent from the response, and the per-category rollup
    would emit nothing for `restaurant` -- a gap that looks identical to a real
    finding that nobody in New York ran a restaurant in 2008. Naming it here
    turns a missing row into a stated one.
    """
    from loci.zbp import naics_to_category

    got = set(df["naics"].astype(str))
    missing: dict[str, list[str]] = {}
    for code, cat in naics_to_category().items():
        if code not in got:
            missing.setdefault(cat, []).append(code)
    # Only report a category as ABSENT when it has no surviving code at all; a
    # multi-code category that lost one code is thinner, not missing.
    present = set(df["naics"].astype(str))
    by_cat: dict[str, set[str]] = {}
    for code, cat in naics_to_category().items():
        by_cat.setdefault(cat, set()).add(code)
    return {cat: sorted(codes) for cat, codes in missing.items()
            if not (by_cat[cat] & present)}


def build_zip_establishments(con, year: int = DEFAULT_YEAR, *, dry_run: bool = False) -> dict:
    """Fetch + land analysis.zip_establishments for every NYC ZIP, ALL NAICS
    codes at the finest (6-digit) level (not just the 15 mapped categories --
    the mixed-format check in `loci zbp-compare` needs the full distribution).
    Idempotent for `year`: deletes prior rows for that year before inserting.
    Returns a summary dict; writes nothing if dry_run.
    """
    _require_ingestable(year)
    plan = request_plan(con, year)
    zips = nyc_zip_list(con)
    rows = fetch_zbp(zips, year=year)
    df = _finest_level(rows, year)
    df.insert(0, "year", year)

    summary = {
        **plan,
        "rows_fetched_all_levels": len(rows),
        "rows_finest_level": len(df),
        "n_zips_returned": df["zipcode"].nunique(),
        "n_naics_codes": df["naics"].nunique(),
        # The raw band codes this year actually returned, so the 2017 '212' ->
        # '210' definition break is visible in the ingest log and not only in a
        # docstring nobody re-reads.
        "empszes_codes": sorted({str(r.get("EMPSZES")) for r in rows
                                 if r.get("EMPSZES") is not None}),
        "categories_absent": categories_absent(df),
    }
    if dry_run:
        return summary

    con.execute("DELETE FROM analysis.zip_establishments WHERE year = ?", [year])
    con.register("_zbp_df", df)
    try:
        con.execute("""
            INSERT INTO analysis.zip_establishments
                (year, zipcode, naics, naics_label, emp_size_band, estab)
            SELECT year, zipcode, naics, naics_label, emp_size_band, estab FROM _zbp_df
        """)
    finally:
        con.unregister("_zbp_df")
    summary["rows_written"] = len(df)
    return summary


def build_zip_category_establishments(con, year: int = DEFAULT_YEAR) -> int:
    """Roll analysis.zip_establishments up to the 15 Loci categories via
    src/loci/zbp_naics.yaml, writing analysis.zip_category_establishments.
    Requires build_zip_establishments(con, year) to have already run for
    `year`. A category with more than one NAICS code (e.g. laundry) is summed
    across codes within each emp-size band before bucketing.
    """
    from loci.zbp import naics_to_category

    xwalk = naics_to_category()
    xwalk_df = pd.DataFrame({"naics": list(xwalk.keys()), "category": list(xwalk.values())})

    con.register("_zbp_xwalk", xwalk_df)
    try:
        con.execute("DELETE FROM analysis.zip_category_establishments WHERE year = ?", [year])
        con.execute(f"""
            INSERT INTO analysis.zip_category_establishments
                (year, zipcode, category, estab_total, estab_small_1_4,
                 estab_5_9, estab_10_19, estab_20_plus)
            SELECT
                z.year, z.zipcode, x.category,
                sum(CASE WHEN z.emp_size_band = '{_LABEL_TOTAL}'   THEN z.estab END) AS estab_total,
                sum(CASE WHEN z.emp_size_band = '{_LABEL_1_4}'     THEN z.estab END) AS estab_small_1_4,
                sum(CASE WHEN z.emp_size_band = '{_LABEL_5_9}'     THEN z.estab END) AS estab_5_9,
                sum(CASE WHEN z.emp_size_band = '{_LABEL_10_19}'   THEN z.estab END) AS estab_10_19,
                sum(CASE WHEN z.emp_size_band NOT IN
                        ('{_LABEL_TOTAL}', '{_LABEL_1_4}', '{_LABEL_5_9}', '{_LABEL_10_19}')
                    THEN z.estab END) AS estab_20_plus
            FROM analysis.zip_establishments z
            JOIN _zbp_xwalk x ON x.naics = z.naics
            WHERE z.year = {year}
            GROUP BY z.year, z.zipcode, x.category
        """)
    finally:
        con.unregister("_zbp_xwalk")

    return con.execute(
        "SELECT count(*) FROM analysis.zip_category_establishments WHERE year = ?", [year]
    ).fetchone()[0]


def build_all_years(con, years=None, *, dry_run: bool = False,
                    progress=None) -> dict:
    """Land EVERY served ZBP vintage, keyed by year -- the default is the whole
    1998-2023 NAICS series, not one vintage.

    The failure contract, which is the point of the loop:

    * A year that CANNOT be served for a named reason (SIC era, outside the
      served range) is recorded in `skipped` with that reason and the loop goes
      on. It is never landed as zero rows.
    * A year that fails any OTHER way -- a transport error, an empty response,
      a schema violation -- re-raises immediately and the whole run stops. A
      network blip on 2011 and a 2011 that does not exist are different facts,
      and a pipeline that turned the first into the second would publish a
      series with a hole in it and no way to tell.
    * `years_written` is returned explicitly so the caller can diff it against
      `ingestable_years()` rather than trusting a row count.
    """
    years = tuple(years) if years is not None else ingestable_years()
    written: dict[int, dict] = {}
    skipped: list[dict] = []
    for y in years:
        try:
            _require_ingestable(y)
        except ZbpYearUnavailable as exc:
            skipped.append({"year": y, "reason": exc.reason})
            if progress is not None:
                progress(y, None, exc.reason)
            continue
        summary = build_zip_establishments(con, y, dry_run=dry_run)
        if not dry_run:
            summary["category_rows"] = build_zip_category_establishments(con, y)
        written[y] = summary
        if progress is not None:
            progress(y, summary, None)

    if not written:
        raise RuntimeError(
            f"ZBP: not one of {list(years)!r} was ingestable "
            f"({len(skipped)} skipped: {skipped!r}). Refusing to report success.")

    return {
        "years_requested": list(years),
        "years_written": sorted(written),
        "skipped": skipped,
        "rows_written": sum(s.get("rows_written", s.get("rows_finest_level", 0))
                            for s in written.values()),
        "per_year": written,
        "dry_run": dry_run,
    }
