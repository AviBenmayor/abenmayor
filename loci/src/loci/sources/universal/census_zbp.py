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
DEFAULT_YEAR = 2023
GETVARS = ["ESTAB", "EMPSZES", "EMPSZES_LABEL", "NAICS2017", "NAICS2017_LABEL"]
MAX_RETRIES = 3
BACKOFF_S = 5.0

# Emp-size bands actually returned by the API (see docstring). '001' is the
# total; the rest partition it. Order matches the CBP EMPSZES code order.
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

    session = session or requests.Session()
    params = {"get": ",".join(GETVARS), "for": f"zipcode:{','.join(zip_list)}", "key": key}
    url = f"{BASE_URL}/{year}/cbp"

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
    return {
        "year": year,
        "url": f"{BASE_URL}/{year}/cbp",
        "get": ",".join(GETVARS),
        "n_zips": len(zips),
        "for": f"zipcode:{zips[0]},{zips[1]},...,{zips[-1]} ({len(zips)} zips total)",
    }


def _finest_level(rows: list[dict]) -> pd.DataFrame:
    """Rows -> DataFrame, filtered to 6-digit NAICS (the finest level; see
    docstring). Coarser 2-5 digit rollups are dropped, not stored."""
    df = pd.DataFrame(rows)
    df = df.rename(columns={"zip code": "zipcode"})
    df["naics_len"] = df["NAICS2017"].str.len()
    df = df[df["naics_len"] == 6].copy()
    df["estab"] = pd.to_numeric(df["ESTAB"], errors="coerce")
    df = df.dropna(subset=["estab"])
    df["estab"] = df["estab"].astype(int)
    return df[["zipcode", "NAICS2017", "NAICS2017_LABEL", "EMPSZES_LABEL", "estab"]].rename(
        columns={"NAICS2017": "naics", "NAICS2017_LABEL": "naics_label", "EMPSZES_LABEL": "emp_size_band"}
    )


def build_zip_establishments(con, year: int = DEFAULT_YEAR, *, dry_run: bool = False) -> dict:
    """Fetch + land analysis.zip_establishments for every NYC ZIP, ALL NAICS
    codes at the finest (6-digit) level (not just the 15 mapped categories --
    the mixed-format check in `loci zbp-compare` needs the full distribution).
    Idempotent for `year`: deletes prior rows for that year before inserting.
    Returns a summary dict; writes nothing if dry_run.
    """
    plan = request_plan(con, year)
    zips = nyc_zip_list(con)
    rows = fetch_zbp(zips, year=year)
    df = _finest_level(rows)
    df.insert(0, "year", year)

    summary = {
        **plan,
        "rows_fetched_all_levels": len(rows),
        "rows_finest_level": len(df),
        "n_zips_returned": df["zipcode"].nunique(),
        "n_naics_codes": df["naics"].nunique(),
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
