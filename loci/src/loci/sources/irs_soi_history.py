"""IRS SOI ZIP-code individual income tax statistics -- MULTI-YEAR PANEL.

`public_signals.py` (untracked, another session's work in progress) ingests a
single vintage (tax year 2022) of this same publisher into
`staging.public_irs_zip_income`. This module is a SEPARATE, standalone
adapter for RQ-001 (regime durability): it pulls EVERY tax year IRS has
published ZIP-code data for -- 1998, 2001, 2002, and 2004 through the latest
year available -- because RQ-001's demand pillar needs an income covariate
defined identically back to 2000, and ACS median household income only
starts in 2011 (five-year ACS) / the mid-2000s (one-year, coarse geography).
IRS SOI ZIP income is the only annual, ZIP-grain income series that reaches
back that far.

WHY A NEW MODULE INSTEAD OF EXTENDING public_signals.py: that file is
untracked and may be edited by another concurrent session; this module does
not import from or write to it. Any future consolidation is a separate,
deliberate decision, not a side effect of this ingest.

FILE FORMAT ARCHAEOLOGY (probed live against irs.gov 2026-09-22 -- every
year's file was downloaded and its NY sheet inspected; none of the mappings
below are guessed from a single sample):

  MODERN (tax years 2011-2022): a single national CSV,
  https://www.irs.gov/pub/irs-soi/{yy}zpallagi.csv, columns STATE, zipcode,
  agi_stub (AGI bracket 1-6), N1 (return count), A00100 (AGI, $ thousands),
  N00200/A00200 (wage return count / amount, $ thousands). One row per
  (zip, agi_stub); zipcode "00000" is the state total, not a real ZIP, and
  is dropped. This is the ONLY vintage where AGI-bracket detail is reliably
  present with a stable, named layout -- "by AGI bracket if consistent" per
  the ingest brief resolves to: consistent only 2011 onward.

  LEGACY (tax years 1998-2010): one Excel workbook per state inside a
  national zip archive at https://www.irs.gov/pub/irs-soi/{year}zipcode.zip
  (1998-2015 naming) -- filenames and column layouts drift across years with
  NO stable schema; five distinct positional layouts were found by direct
  inspection and are encoded in `_LEGACY_FORMATS` below (format id ->
  (n1_col, agi_col, n_wages_col | None, a_wages_col)), keyed by year:

    FMT_A  1998, 2001, 2002, 2004, 2005  -- zip is the row LABEL (col 0) on
           a block's first row; n1=1, agi=4, n_wages=5, a_wages=6.
    FMT_C  2006                          -- zip label col0 (+redundant float
           dup col1); n1=2, agi=5, n_wages=6, a_wages=7.
    FMT_D  2007                          -- bracket label col0 ('TOTAL' on
           the zip's first row), zip is col1; n1=2, agi=7, n_wages=8,
           a_wages=9.
    FMT_F  2008                          -- same "bracket label col0 (blank
           on the total row) / zip col1 (0 = state total)" shape as FMT_D;
           n1=2, agi=7, a_wages=8, NO separate wage return count published
           this year (single combined column instead of count+amount).
    FMT_E  2009, 2010                    -- same block shape as FMT_F but
           WITH a wage return count column; n1=2, agi=7, n_wages=8,
           a_wages=9.

  Only the per-ZIP TOTAL row is extracted from legacy years (not the AGI
  brackets beneath it) -- the brackets are real but their bucket boundaries
  and count (4 vs 6 vs 7) change release to release and are not comparable
  across years, whereas the ZIP total (N1, AGI, wage returns/amount) is.

  ZIP suppression: cells with '*' (value suppressed to avoid disclosure) or
  '**' (folded into an adjacent cell) are common in low-population ZIPs in
  every legacy year and appear in some MODERN brackets too. These decode to
  NULL, never zero -- coercing a suppressed cell to 0 would fabricate a
  reported-zero income ZIP where the true value is merely undisclosed. Rows
  originating from a block containing any suppressed cell are flagged
  `any_suppressed = true` in the output so downstream code can choose to
  drop or impute rather than silently trust a partial total.

  Units: IRS reports every dollar figure in THOUSANDS of dollars in both eras
  (confirmed: 2022 AL state-total AGI ~$8.7B on N1=659,530 returns implies
  ~$13.2k mean, i.e. the raw cell IS already annual dollars/1000, consistent
  with SOI's own "money amounts are in thousands" note printed on every
  legacy sheet). This module multiplies AGI/wage amounts by 1000 on the way
  out so `irs_zip_income_panel.parquet` is in dollars, not the raw
  thousands-of-dollars units -- documented in the `MONEY_UNIT` module
  constant so a caller cannot silently assume the source unit.

DEPENDENCY NOTE: legacy-year .xls files are the old BIFF format, which
pandas reads only via `xlrd>=2.0.1`. `xlrd` is NOT declared in
pyproject.toml (this module was told not to touch pyproject.toml/uv.lock --
see the ingest brief) and is not part of the project's normal environment.
Running `ingest_all()` for any pre-2011 year therefore requires xlrd
installed ad hoc, e.g. `uv run --with xlrd loci-irs-soi-history ...` or
`pip install xlrd` in the active venv. The MODERN (2011+) path has no such
dependency (plain CSV). Import of xlrd is deferred to the call site that
needs it so importing this module, or ingesting only 2011+, never requires
xlrd to be present. This is a caveat the database/type system cannot catch:
a missing xlrd fails LOUD (ImportError with an install hint), never silently
skips the year.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

MONEY_UNIT = "usd"  # output unit for AGI / wage amount columns (source is $ thousands)

# ---------------------------------------------------------------------------
# Year coverage & URL patterns
# ---------------------------------------------------------------------------

# Per IRS's own page text: "ZIP Code data for years 1998, 2001, and 2004
# through 2022 are available" (probed 2026-09-22). 1999, 2000, 2003 were
# never published at ZIP grain -- not a gap in this ingest, a gap in the
# source.
LEGACY_YEARS = [1998, 2001, 2002] + list(range(2004, 2011))  # 1998-2010, minus the missing years
MODERN_YEARS = list(range(2011, 2023))  # 2011-2022; probed: 2023 not yet published (404 as of 2026-09-22)
ALL_YEARS = LEGACY_YEARS + MODERN_YEARS

# 1998-2015 used "{year}zipcode.zip"; 2016+ switched to "zipcode{year}.zip"
# (both confirmed live; boundary probed directly, not inferred).
_LEGACY_ARCHIVE_TMPL_EARLY = "https://www.irs.gov/pub/irs-soi/{year}zipcode.zip"
_LEGACY_ARCHIVE_TMPL_LATE = "https://www.irs.gov/pub/irs-soi/zipcode{year}.zip"


def legacy_archive_url(year: int) -> str:
    return _LEGACY_ARCHIVE_TMPL_EARLY.format(year=year) if year <= 2015 else _LEGACY_ARCHIVE_TMPL_LATE.format(year=year)


def modern_csv_url(year: int) -> str:
    yy = f"{year % 100:02d}"
    return f"https://www.irs.gov/pub/irs-soi/{yy}zpallagi.csv"


# ---------------------------------------------------------------------------
# Legacy column-position maps (see module docstring for how these were derived)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegacyFormat:
    name: str
    n1_col: int
    agi_col: int
    n_wages_col: int | None
    a_wages_col: int


_FMT_A = LegacyFormat("A", n1_col=1, agi_col=4, n_wages_col=5, a_wages_col=6)
_FMT_C = LegacyFormat("C", n1_col=2, agi_col=5, n_wages_col=6, a_wages_col=7)
_FMT_D = LegacyFormat("D", n1_col=2, agi_col=7, n_wages_col=8, a_wages_col=9)
_FMT_F = LegacyFormat("F", n1_col=2, agi_col=7, n_wages_col=None, a_wages_col=8)
_FMT_E = LegacyFormat("E", n1_col=2, agi_col=7, n_wages_col=8, a_wages_col=9)

LEGACY_FORMAT_BY_YEAR: dict[int, LegacyFormat] = {
    1998: _FMT_A, 2001: _FMT_A, 2002: _FMT_A, 2004: _FMT_A, 2005: _FMT_A,
    2006: _FMT_C,
    2007: _FMT_D,
    2008: _FMT_F,
    2009: _FMT_E, 2010: _FMT_E,
}

# zip position differs by format: "label" means the zip appears as the text
# in column 0 on the block's total row (FMT_A / FMT_C); "col1" means column 0
# holds the AGI-bracket label and the zip is a value in column 1 (FMT_D);
# "col0" means column 0 holds the zip on every row of the block, with the
# bracket label in column 1, and 0 marks the state-total block (FMT_F / FMT_E).
_ZIP_LAYOUT = {"A": "label", "C": "label", "D": "col1", "F": "col1", "E": "col0"}

_SUPPRESSED = {"*", "**"}


def _num(v) -> float | None:
    """Coerce one legacy/modern cell to a float, or None for suppressed/blank.

    Never coerces a suppressed cell to 0 -- see module docstring.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            if v != v:  # NaN
                return None
        except Exception:
            pass
        return float(v)
    s = str(v).strip()
    if s == "" or s in _SUPPRESSED or s in {".", "-", "nan", "NaN"}:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _is_suppressed_cell(v) -> bool:
    return isinstance(v, str) and v.strip() in _SUPPRESSED


def _zip5(v) -> str | None:
    """Normalize a legacy zip cell (int, float, or padded/unpadded string) to
    a zero-padded 5-digit string, or None if it doesn't look like a ZIP."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return None
    s = re.sub(r"\.0$", "", s)  # pandas often reads an int-like cell as float
    if not s.isdigit():
        return None
    if len(s) > 5:
        return None
    return s.zfill(5)


# ---------------------------------------------------------------------------
# Legacy parsing
# ---------------------------------------------------------------------------


def find_state_member(namelist: list[str], state_abbr: str = "ny") -> str:
    """Locate the one archive member for a state, tolerant of the four
    filename conventions observed across 1998-2010 (see docstring): strip
    spaces and compare the lowercased basename's suffix to '{state}.xls'.
    """
    pattern = re.compile(rf"{re.escape(state_abbr)}\.xlsx?$")
    candidates = [n for n in namelist if pattern.search(n.lower().replace(" ", ""))]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one NY member in archive, found {len(candidates)}: {candidates[:5]}"
        )
    return candidates[0]


def parse_legacy_ny_sheet(raw: pd.DataFrame, year: int) -> pd.DataFrame:
    """Extract one row per ZIP (the block's TOTAL row only, not AGI brackets)
    from a raw (header=None) legacy NY worksheet, using the column map for
    `year`. Returns columns: zip, tax_year, n1, agi, n_wages, a_wages,
    any_suppressed.
    """
    fmt = LEGACY_FORMAT_BY_YEAR.get(year)
    if fmt is None:
        raise ValueError(f"no legacy column map registered for tax year {year}")
    layout = _ZIP_LAYOUT[fmt.name]
    out: list[dict] = []
    n_rows, n_cols = raw.shape
    needed = max(fmt.n1_col, fmt.agi_col, fmt.a_wages_col, (fmt.n_wages_col or 0))
    if n_cols <= needed:
        raise RuntimeError(f"legacy sheet for {year} has only {n_cols} columns, need >{needed}")

    for i in range(n_rows):
        row = raw.iloc[i]
        if layout == "label":
            zip5 = _zip5(row[0])
            if zip5 is None:
                continue  # bracket sub-row, blank separator, or state-total header row
        elif layout == "col1":
            # total row: col0 blank/NaN AND col1 holds the zip
            c0 = row[0]
            if not (c0 is None or (isinstance(c0, float) and c0 != c0)):
                continue
            zip5 = _zip5(row[1])
            if zip5 is None or zip5 == "00000":
                continue  # 0 marks the state-total block (FMT_F), not a ZIP
        else:  # "col0": zip repeats on every row of the block; total row has blank/NaN col1
            c1 = row[1]
            is_total_row = c1 is None or (isinstance(c1, float) and c1 != c1)
            if not is_total_row:
                continue
            zip5 = _zip5(row[0])
            if zip5 is None or zip5 == "00000":
                continue  # 0 marks the state-total block, not a ZIP

        cells = [row[fmt.n1_col], row[fmt.agi_col], row[fmt.a_wages_col]]
        if fmt.n_wages_col is not None:
            cells.append(row[fmt.n_wages_col])
        any_suppressed = any(_is_suppressed_cell(c) for c in cells)

        n1 = _num(row[fmt.n1_col])
        agi_k = _num(row[fmt.agi_col])
        a_wages_k = _num(row[fmt.a_wages_col])
        n_wages = _num(row[fmt.n_wages_col]) if fmt.n_wages_col is not None else None

        out.append({
            "zip": zip5,
            "tax_year": year,
            "n1": n1,
            "agi": None if agi_k is None else agi_k * 1000.0,
            "n_wages": n_wages,
            "a_wages": None if a_wages_k is None else a_wages_k * 1000.0,
            "any_suppressed": any_suppressed,
        })
    if not out:
        raise RuntimeError(f"parsed zero ZIP rows from the {year} NY legacy sheet -- format map is wrong")
    return pd.DataFrame(out)


def fetch_legacy_year(year: int, raw_dir: Path, *, session: requests.Session | None = None) -> pd.DataFrame:
    """Download (if not cached), extract the NY member, and parse one legacy year."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    archive_path = raw_dir / f"{year}zipcode.zip"
    if not archive_path.exists():
        session = session or requests.Session()
        r = session.get(legacy_archive_url(year), timeout=180, headers={"User-Agent": "Mozilla/5.0 (loci research)"})
        r.raise_for_status()
        if not r.content:
            raise RuntimeError(f"IRS legacy archive for {year} returned an empty body")
        archive_path.write_bytes(r.content)

    with zipfile.ZipFile(archive_path) as bundle:
        member = find_state_member(bundle.namelist(), "ny")
        with bundle.open(member) as fh:
            data = fh.read()

    try:
        import xlrd  # noqa: F401  -- import for the clear error message below, not used directly
    except ImportError as exc:
        raise ImportError(
            f"tax year {year} needs the legacy .xls reader (xlrd>=2.0.1) to parse {member!r}, "
            "which is not a project dependency (irs_soi_history.py was told not to edit "
            "pyproject.toml). Install it ad hoc, e.g. `uv run --with xlrd ...`, or "
            "`pip install xlrd` into the active venv, then re-run."
        ) from exc

    raw = pd.read_excel(pd.io.common.BytesIO(data), header=None, engine="xlrd")
    return parse_legacy_ny_sheet(raw, year)


# ---------------------------------------------------------------------------
# Modern (2011-2022) national CSV
# ---------------------------------------------------------------------------


def fetch_modern_year(year: int, raw_dir: Path, nyc_zips: set[str], *, session: requests.Session | None = None) -> pd.DataFrame:
    """Download (if not cached) the national all-states CSV for `year`,
    filter to NY-state rows whose ZIP is in `nyc_zips`, and return both
    per-bracket rows (agi_stub 1-6) and a per-ZIP TOTAL row (agi_stub 0,
    summed across brackets) so downstream code can use whichever grain it
    needs. This is the only vintage range where the AGI-bracket split is on
    a stable, named layout across years.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_path = raw_dir / f"{year}_zpallagi.csv"
    if not csv_path.exists():
        session = session or requests.Session()
        r = session.get(modern_csv_url(year), timeout=180, headers={"User-Agent": "Mozilla/5.0 (loci research)"})
        r.raise_for_status()
        if not r.content:
            raise RuntimeError(f"IRS modern CSV for {year} returned an empty body")
        csv_path.write_bytes(r.content)

    # Column CASING drifts year to year even though the names don't: 2011
    # ships 'ZIPCODE' (upper) while every other year ships 'zipcode', and
    # 2012 ships 'AGI_STUB' (upper) while every other year ships 'agi_stub'
    # -- confirmed live, not a hypothetical. Match case-insensitively and
    # normalize to canonical lowercase names before anything else runs.
    df = pd.read_csv(csv_path, low_memory=False)
    colmap = {c.lower(): c for c in df.columns}
    canonical = {"state": "STATE", "zipcode": "zipcode", "agi_stub": "agi_stub",
                 "n1": "N1", "a00100": "A00100", "n00200": "N00200", "a00200": "A00200"}
    missing = [c for c in canonical if c not in colmap]
    if missing:
        raise RuntimeError(f"IRS modern CSV for {year} is missing expected column(s) {missing}: {list(df.columns)[:15]}")
    df = df.rename(columns={colmap[c]: canon for c, canon in canonical.items()})
    df["STATE"] = df["STATE"].astype("string")
    df["zipcode"] = df["zipcode"].astype(str)
    df["agi_stub"] = pd.to_numeric(df["agi_stub"], errors="coerce").astype("Int64")

    ny = df.loc[df["STATE"].fillna("").str.upper().eq("NY")].copy()
    if ny.empty:
        raise RuntimeError(f"IRS modern CSV for {year} yielded zero NY rows")
    ny["zip5"] = ny["zipcode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
    nyc = ny.loc[ny["zip5"].isin(nyc_zips)].copy()
    if nyc.empty:
        raise RuntimeError(f"IRS modern CSV for {year}: zero rows matched the {len(nyc_zips)}-ZIP NYC universe")

    bracket = pd.DataFrame({
        "zip": nyc["zip5"],
        "tax_year": year,
        "agi_stub": nyc["agi_stub"].astype("Int64"),
        "n1": pd.to_numeric(nyc["N1"], errors="coerce"),
        "agi": pd.to_numeric(nyc["A00100"], errors="coerce") * 1000.0,
        "n_wages": pd.to_numeric(nyc["N00200"], errors="coerce"),
        "a_wages": pd.to_numeric(nyc["A00200"], errors="coerce") * 1000.0,
        "any_suppressed": False,  # modern CSV publishes 0 for small cells, not '*'; nothing to flag
    })

    totals = (
        bracket.groupby(["zip", "tax_year"], as_index=False)
        .agg(n1=("n1", "sum"), agi=("agi", "sum"), n_wages=("n_wages", "sum"), a_wages=("a_wages", "sum"))
    )
    totals["agi_stub"] = pd.array([0] * len(totals), dtype="Int64")  # 0 = synthetic "all brackets" row
    totals["any_suppressed"] = False

    bracket["agi_stub"] = bracket["agi_stub"].astype("Int64")
    return pd.concat([totals[bracket.columns], bracket], ignore_index=True)


# ---------------------------------------------------------------------------
# NYC ZIP universe (read-only reuse of the PLUTO-derived list the
# zillow/ACS/ZBP adapters already use -- not re-derived here)
# ---------------------------------------------------------------------------


def nyc_zips() -> set[str]:
    import duckdb

    from loci.sources.universal.census_zbp import nyc_zip_list

    con = duckdb.connect()  # in-memory only -- never opens the project warehouse
    try:
        zips = nyc_zip_list(con)
    finally:
        con.close()
    if not zips:
        raise RuntimeError("nyc_zip_list() returned no ZIPs -- cannot scope the IRS pull to NYC")
    return set(zips)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class YearResult:
    year: int
    ok: bool
    rows: int = 0
    zips: int = 0
    error: str | None = None


def ingest_all(
    raw_dir: Path,
    out_path: Path,
    *,
    years: list[int] | None = None,
    zips: set[str] | None = None,
) -> tuple[pd.DataFrame, list[YearResult]]:
    """Pull every requested tax year, log-and-continue on a failed year (per
    project rule: live-API sources fail loud PER YEAR, but one bad year must
    not take down the whole multi-decade pull), and write one combined
    parquet with an explicit `agi_stub` grain column (0 = zip total,
    1-6 = MODERN-only bracket, NULL = legacy year with no bracket detail).
    """
    years = years if years is not None else ALL_YEARS
    zips = zips if zips is not None else nyc_zips()
    raw_dir = Path(raw_dir)
    frames: list[pd.DataFrame] = []
    results: list[YearResult] = []

    for year in years:
        print(f"[irs_soi_history] tax year {year} ...", flush=True)
        try:
            if year in LEGACY_FORMAT_BY_YEAR:
                df = fetch_legacy_year(year, raw_dir)
                df["agi_stub"] = pd.array([pd.NA] * len(df), dtype="Int64")
                df = df[["zip", "tax_year", "agi_stub", "n1", "agi", "n_wages", "a_wages", "any_suppressed"]]
                df = df.loc[df["zip"].isin(zips)]
            elif year in MODERN_YEARS:
                df = fetch_modern_year(year, raw_dir, zips)
                df = df[["zip", "tax_year", "agi_stub", "n1", "agi", "n_wages", "a_wages", "any_suppressed"]]
            else:
                raise ValueError(f"tax year {year} is not in LEGACY_FORMAT_BY_YEAR or MODERN_YEARS")
            if df.empty:
                raise RuntimeError(f"tax year {year}: zero rows survived the NYC ZIP filter")
            frames.append(df)
            n_zips = df.loc[df["agi_stub"].isna() | (df["agi_stub"] == 0), "zip"].nunique()
            results.append(YearResult(year, ok=True, rows=len(df), zips=n_zips))
            print(f"[irs_soi_history] tax year {year}: {len(df)} rows, {n_zips} ZIPs", flush=True)
        except Exception as exc:  # noqa: BLE001 -- log-and-continue is the explicit brief for this ingest
            print(f"[irs_soi_history] tax year {year} FAILED: {exc}", flush=True)
            results.append(YearResult(year, ok=False, error=str(exc)))

    ok_years = [r.year for r in results if r.ok]
    if not frames:
        raise RuntimeError(f"every requested tax year failed -- see per-year errors: {results}")

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["tax_year", "zip", "agi_stub"], na_position="first").reset_index(drop=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(out_path, index=False)
    print(
        f"[irs_soi_history] wrote {len(panel)} rows, {len(ok_years)}/{len(years)} years ok -> {out_path}",
        flush=True,
    )
    return panel, results
