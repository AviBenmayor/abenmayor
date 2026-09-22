"""NYC MapPLUTO/PLUTO historical vintages, rolled up to ZIP-year (RQ-001
COST/land-use pillar input). Fetches the annual archive releases from NYC
DCP's "BYTES of the BIG APPLE" archive and aggregates each vintage by
`ZipCode` -- NOT a POI source (writes no `staging.poi` rows), same
`grid/pluto.py` role as a plain builder, but across many years instead of one
current snapshot.

WHY THIS IS A NEW MODULE, NOT AN EDIT TO `grid/pluto.py`
---------------------------------------------------------------------------
`grid/pluto.py` builds `analysis.hex_controls` from exactly one CSV at
`data/raw/pluto.csv` (the current release only) and writes to the warehouse.
This module answers a different question -- a multi-year ZIP panel for
RQ-001 -- reads/writes nothing in the warehouse, and has its own fetch step
(historical vintages are not on disk anywhere else in this repo). Keeping it
separate avoids coupling the hex-grid builder's contract to a research-only
panel; if RQ-001's ANSWER stage wants this promoted into the warehouse, that
is a `staging`/`analysis` migration ticket, not a change to this file.

WHERE THE ARCHIVE ACTUALLY LIVES (probed 2026-09-22)
---------------------------------------------------------------------------
`nyc.gov/.../mappluto-pluto-change` is a JS-rendered SPA; curl alone returns
an empty shell. Rendered in a real browser (Chrome via the claude-in-chrome
MCP), its "Previous Releases Archive" table links resolve to a CDN,
`s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/pluto/`, and
the archive covers only 2023 onward at 4-5 minor releases per year -- but a
brute-force HEAD probe of `nyc_pluto_<YYvN>*.zip` against that same CDN
across three filename templates (the naming changed twice) turned up every
MAJOR release back to **2009v1**. Nothing answered for any `<08` vintage
under any template tried (`nyc_pluto_0Xv1.zip`, `_csv.zip`, `_arc_csv.zip`) --
2002-2008 could not be located at this CDN and are NOT fetched by this
module. The task's "2002->present" was an expectation to verify, not a fact;
verified false at the early end. This is recorded as a gap, not silently
dropped (see `FIRST_VINTAGE` and `main()`'s printed caveat).

THREE FILENAME ERAS, ONE STABLE COLUMN SET
---------------------------------------------------------------------------
Confirmed by downloading and inspecting 2009v2, 2017v1, 2020v1, 2021v1 and
2026v2 (`tests/test_rq001_lodes_pluto.py` pins the column names, not the
filenames, against fixtures shaped like each era):

  * 2009-2017(ish): `nyc_pluto_<YYvN>.zip`, containing FIVE per-borough files
    (`{BORO}<YY>v<N>.txt` at the zip root in 2009, `Borofiles_CSV/
    {BORO}<YYYY>V<N>.csv` by 2017) plus 1-2 PDFs. Columns are Pascal-case
    (`ZipCode`, `LotArea`, `BldgArea`, `ComArea`, `RetailArea`, `AssessTot`,
    `UnitsRes`, `BBL`).
  * 2018v2-2020: `nyc_pluto_<YYvN>_csv.zip`, containing ONE unified
    `pluto_<YYvN>.csv` (the switch away from per-borough files landed at
    2020v1) plus PDFs. Same Pascal-case columns.
  * 2021-present: `nyc_pluto_<YYvN>_arc_csv.zip` (the archive's own naming;
    `_csv.zip` without `_arc_` also resolves for the same file), one unified
    CSV, columns now **lowercase** (`zipcode`, `lotarea`, `bldgarea`,
    `comarea`, `retailarea`, `assesstot`, `unitsres`, `bbl`).

  The 8 fields this module reads are present, under the same names modulo
  case, in EVERY era. DuckDB resolves column names case-insensitively (the
  same fact `grid/pluto.py` already relies on for its own SELECT), so one SQL
  query handles both eras without a per-year column-rename table. What DOES
  differ, and is handled explicitly, is the FILE STRUCTURE: one file per zip
  vs five. `_extract_data_files` globs for `.csv`/`.txt` entries (excluding
  PDFs) inside each zip and UNIONs whatever it finds, so 1-file and 5-file
  vintages are read by the same code path.

CANONICAL VERSION PER YEAR
---------------------------------------------------------------------------
Most years ship several minor releases (23v1, 23v1.1, ... 23v3.1). This
module takes ONE vintage per calendar year -- the latest MAJOR version
released that year (minors only touch zoning fields, not the land-use/area
fields this module reads) -- recorded in `VINTAGE_BY_YEAR` below, each entry
verified reachable with a live HEAD request on 2026-09-22.

PRE-FLIGHT (per the task's own instruction)
---------------------------------------------------------------------------
Before the full run, one old vintage (2009v2) and one current vintage
(2026v2) were downloaded and diffed column-for-column (see the era note
above) to confirm the column map holds at both ends. Only then does
`download_all` fetch the rest.
"""
from __future__ import annotations

import pathlib
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

import duckdb
import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
PLUTO_DIR = REPO_ROOT / "data" / "raw" / "rq001" / "pluto"
OUT_PATH = REPO_ROOT / "data" / "interim" / "rq001" / "pluto" / "pluto_zip_vintage.parquet"

CDN_BASE = "https://s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/pluto"
USER_AGENT = "loci/pluto-vintages (contact: repository owner)"
MAX_RETRIES = 3
BACKOFF_S = 4.0

#: One canonical (latest-major-release) version string per calendar year,
#: 2009-2026. Verified live (HEAD 200) on 2026-09-22 against CDN_BASE under
#: the filename template FILENAME_TEMPLATES resolves for that year. 2002-2008
#: are UPSTREAM-absent at this CDN under every template tried -- see the
#: module docstring. This is the "typically 2002->present" claim the task
#: asked to verify; it verified false before 2009.
VINTAGE_BY_YEAR: dict[int, str] = {
    2009: "09v2", 2010: "10v2", 2011: "11v2", 2012: "12v2", 2013: "13v2",
    2014: "14v2", 2015: "15v1", 2016: "16v2", 2017: "17v1", 2018: "18v2",
    2019: "19v2", 2020: "20v4", 2021: "21v4", 2022: "22v3", 2023: "23v3",
    2024: "24v4", 2025: "25v4", 2026: "26v2",
}
FIRST_VINTAGE = min(VINTAGE_BY_YEAR)
LAST_VINTAGE = max(VINTAGE_BY_YEAR)

#: Filename templates to try, in priority order, for a given version string.
#: The naming changed twice (see module docstring); trying all three and
#: keeping the first that downloads means this list does not need to be kept
#: in lockstep with exactly which year switched over.
FILENAME_TEMPLATES: tuple[str, ...] = (
    "nyc_pluto_{v}_arc_csv.zip",  # 2021+ (archive's own current naming)
    "nyc_pluto_{v}_csv.zip",      # 2018v2-2020
    "nyc_pluto_{v}.zip",          # 2009-2018v1
)

#: The 8 columns this module reads, and what each becomes in the output.
#: Read case-insensitively (DuckDB default) so both the Pascal-case (pre-2021)
#: and lowercase (2021+) eras resolve against the same SQL.
_COLUMNS = ("ZipCode", "LotArea", "BldgArea", "ComArea", "RetailArea",
            "AssessTot", "UnitsRes", "BBL")


class PlutoVintageError(RuntimeError):
    """A PLUTO vintage could not be fetched or parsed. Raised, not skipped --
    a silently-missing year reads downstream as NYC having no buildings that
    year (CONTEXT.md 'fail loud, never ingest a silent zero')."""


def vintage_filename(version: str, template: str) -> str:
    return template.format(v=version)


def _fetch(url: str, timeout: int = 300) -> bytes:
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise PlutoVintageError(f"{url} -> HTTP 404") from exc
            last = exc
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
        if attempt < MAX_RETRIES - 1:
            time.sleep(BACKOFF_S * (attempt + 1))
    raise PlutoVintageError(f"{url} failed after {MAX_RETRIES} tries: {last}")


def download_vintage(year: int, version: str, pluto_dir: pathlib.Path = PLUTO_DIR,
                      *, refresh: bool = False, fetch=_fetch) -> pathlib.Path:
    """Download one vintage's zip, trying each filename template in order.
    Returns the path on disk. Skips (and returns the existing path) if
    already present and `refresh` is False -- matches `lodes_wac.py`'s
    cache-and-report convention.

    The cache check runs over ALL templates before any network call: which
    template succeeds differs by year (see module docstring), so a call that
    already cached the file under template 3 must not re-issue the two
    template-1/2 404s on every subsequent call -- it would still end up at
    the same cached file, but only after paying for two guaranteed-failing
    requests it doesn't need.
    """
    if not refresh:
        for template in FILENAME_TEMPLATES:
            cached = pluto_dir / vintage_filename(version, template)
            if cached.exists():
                return cached

    for template in FILENAME_TEMPLATES:
        fname = vintage_filename(version, template)
        dest = pluto_dir / fname
        url = f"{CDN_BASE}/{fname}"
        try:
            blob = fetch(url)
        except PlutoVintageError as exc:
            if "404" in str(exc):
                continue  # try the next filename template
            raise
        if not blob:
            raise PlutoVintageError(
                f"{year} ({version}): {url} returned an empty body with no "
                f"error. Refusing to write a zero-byte zip.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        return dest
    raise PlutoVintageError(
        f"{year} ({version}): none of {FILENAME_TEMPLATES} resolved at "
        f"{CDN_BASE}. The archive's naming may have changed again.")


def _extract_data_files(zip_path: pathlib.Path, workdir: pathlib.Path) -> list[pathlib.Path]:
    """Extract every .csv/.txt entry that is PLUTO lot data (case-insensitive
    extension) from the zip -- 1 for a unified vintage, 5 for a per-borough
    vintage -- skipping PDFs (data dictionary, readme) AND, discovered
    2026-09-22, the "PLUTO Change File" some vintages bundle in the same zip
    (e.g. `nyc_pluto_20v4_arc_csv.zip` also contains
    `PLUTOChangeFile20v4.csv`). That file is a DIFFERENT registry source
    (field-level correction log, not lot data): its schema has no ZipCode/
    LotArea/etc, so `union_by_name` padded every one of its ~43,000 rows with
    NULLs for our columns and they were silently counted as lots-with-no-zip,
    inflating that vintage's `dropped_no_zip` ~15x with rows that were never
    tax lots at all. Matched by filename containing "changefile"
    (case-insensitive) -- distinct from every real PLUTO data filename seen
    across 2009-2026 (`{BORO}...`, `pluto_<v>.csv`). Raises if nothing is left
    after that exclusion: a zip with only PDFs (or only a change file) inside
    means the archive changed shape again."""
    out: list[pathlib.Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            lower = name.lower()
            if not lower.endswith((".csv", ".txt")):
                continue
            if "changefile" in lower:
                continue
            target = workdir / pathlib.Path(name).name
            target.write_bytes(zf.read(name))
            out.append(target)
    if not out:
        raise PlutoVintageError(
            f"{zip_path.name}: no PLUTO lot-data .csv/.txt entries found "
            f"inside (after excluding PDFs and any PLUTO Change File) -- "
            f"expected 1 (unified) or 5 (per-borough) data files.")
    return out


def _aggregate_vintage(con, data_files: list[pathlib.Path], year: int,
                        version: str = "") -> pd.DataFrame:
    """Read the extracted PLUTO file(s) for one vintage and aggregate by
    ZipCode. ALL_VARCHAR + TRY_CAST for the same reason `grid/pluto.py` reads
    PLUTO that way: blanks mixed with numbers in the raw export would
    otherwise fail a strict auto-inferred type."""
    paths = [str(p) for p in data_files]
    df = con.execute(
        f"""
        SELECT
            TRY_CAST(ZipCode AS INTEGER)   AS zipcode,
            TRY_CAST(LotArea AS DOUBLE)    AS lotarea,
            TRY_CAST(BldgArea AS DOUBLE)   AS bldgarea,
            TRY_CAST(ComArea AS DOUBLE)    AS comarea,
            TRY_CAST(RetailArea AS DOUBLE) AS retailarea,
            TRY_CAST(AssessTot AS DOUBLE)  AS assesstot,
            TRY_CAST(UnitsRes AS DOUBLE)   AS unitsres,
            BBL AS bbl
        FROM read_csv_auto({paths!r}, ALL_VARCHAR=TRUE, union_by_name=TRUE,
                           null_padding=TRUE, ignore_errors=TRUE)
        """
    ).df()

    before = len(df)
    df = df[df["zipcode"].notna() & (df["zipcode"] > 0)]
    dropped_no_zip = before - len(df)

    agg = df.assign(
        has_retail=(df["retailarea"].fillna(0) > 0),
    ).groupby("zipcode").agg(
        n_lots=("bbl", "size"),
        bldgarea_total=("bldgarea", "sum"),
        comarea_total=("comarea", "sum"),
        retailarea_total=("retailarea", "sum"),
        assesstot_total=("assesstot", "sum"),
        unitsres_total=("unitsres", "sum"),
        n_lots_with_retail=("has_retail", "sum"),
    ).reset_index()
    agg.insert(1, "year", year)
    agg.insert(2, "pluto_version", version)
    # A CITYWIDE constant broadcast onto every zipcode row for this vintage
    # (not a per-ZIP count). Aggregate downstream with max()/first(), never
    # sum() -- summing it across a year's ZIP rows multiplies it by that
    # year's ZIP count. Caught exactly this way during validation
    # (2026-09-22): a first-draft check query used sum() and read a ~200x
    # inflated figure before the mistake was in the query, not the data.
    agg["dropped_no_zip"] = dropped_no_zip
    return agg


def build_zip_vintage_panel(years=None, pluto_dir: pathlib.Path = PLUTO_DIR,
                             *, refresh: bool = False, progress=None) -> pd.DataFrame:
    """Download (if needed) and aggregate every requested vintage to
    zipcode-year. Continues past a failed vintage (heartbeat, per the task's
    own instruction) rather than stopping the whole run -- but the failure is
    collected and re-raised at the end if EVERY vintage failed, and always
    printed, so a silently-empty output is never mistaken for a clean run."""
    if years is None:
        years = sorted(VINTAGE_BY_YEAR)
    else:
        years = sorted(int(y) for y in years)
        unknown = [y for y in years if y not in VINTAGE_BY_YEAR]
        if unknown:
            raise PlutoVintageError(
                f"No canonical vintage recorded for years {unknown}. "
                f"VINTAGE_BY_YEAR covers {FIRST_VINTAGE}-{LAST_VINTAGE}.")

    rows: list[pd.DataFrame] = []
    failures: list[tuple[int, str]] = []
    for year in years:
        version = VINTAGE_BY_YEAR[year]
        # A fresh in-memory connection per vintage, deliberately: reusing one
        # DuckDB connection across many read_csv_auto(ALL_VARCHAR, sniffed)
        # calls in a loop was observed (2026-09-22) to occasionally return an
        # inflated row count on a later iteration while the grouped output
        # stayed correct -- a stale-sniff/caching artifact, not reproduced
        # with one connection per call. Cheap (in-memory, no schema) and
        # removes the whole class of cross-vintage state bleed.
        con = duckdb.connect(":memory:")
        try:
            zpath = download_vintage(year, version, pluto_dir, refresh=refresh)
            with tempfile.TemporaryDirectory() as tmp:
                data_files = _extract_data_files(zpath, pathlib.Path(tmp))
                agg = _aggregate_vintage(con, data_files, year, version)
            rows.append(agg)
            msg = f"{year} ({version}): {len(agg)} ZIPs, {agg['n_lots'].sum()} lots"
        except Exception as exc:  # noqa: BLE001 - heartbeat: log, continue
            failures.append((year, str(exc)))
            msg = f"{year} ({version}): FAILED -- {exc}"
        finally:
            con.close()
        if progress is not None:
            progress(year, msg)
        else:
            print(msg)

    if not rows:
        raise PlutoVintageError(
            f"every requested vintage failed: {failures}")
    if failures:
        print(f"WARNING: {len(failures)} vintage(s) failed and were skipped: "
              f"{[y for y, _ in failures]}")

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["zipcode", "year"]).reset_index(drop=True)
    return out


def main() -> None:
    print(f"Building PLUTO ZIP-year panel ({FIRST_VINTAGE}-{LAST_VINTAGE})...")
    print("NOTE: 2002-2008 requested by the task but not found at the DCP "
          "archive CDN under any filename template tried -- see module "
          "docstring. Panel starts at 2009.")
    df = build_zip_vintage_panel()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"wrote {len(df)} rows ({df['zipcode'].nunique()} ZIPs x "
          f"{df['year'].nunique()} years) to {OUT_PATH}")


if __name__ == "__main__":
    main()
