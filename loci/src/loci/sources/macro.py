"""FRED macro series for RQ-001 (regime durability) — NOT yet registered in
registry.yaml (a peer session may be editing it; see
docs/research/RQ-001-regime-durability/drafts/registry-fred_macro.yaml for the
draft entry). This module only fetches and tidies; it never opens the
warehouse. `model/` code for RQ-001 reads the parquet output directly, the
same "fetcher, not loader" split as lodes_wac.py.

WHY THESE SERIES
---------------------------------------------------------------------------
SEED.yaml constrains macro to free FRED/BLS series only, tested as a
hypothesis rather than assumed (METHOD.md §5: level macro cannot move
*relative* favorability inside a tercile system — a citywide shock moves
everyone, so the identified tests are H1, the descriptive year-level churn
regression, and H2, macro x exposure interactions with year fixed effects).
Every id below was verified live against
https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES> on 2026-09-22
(HTTP 200, a real observation column) before being hard-coded — a 404 there
is a broken id, not an empty series, and FETCH must not swallow that
silently (see MacroFetchError below; same failure contract as
LodesFetchError in lodes_wac.py: a silently-missing series reads downstream
as "macro was flat that year", which is a fabricated zero).

SERIES_IDS (id -> human title, confirmed by probing the FRED series page):
    UNRATE                   U.S. unemployment rate (national), monthly, 1948-
    NYUR                     Unemployment rate, New York STATE, monthly, 1976-
    NEWY636URN                Unemployment rate, New York-Newark-Jersey City
                              NY-NJ-PA MSA (the NYC metro reading), monthly,
                              1990-, NOT seasonally adjusted
    FEDFUNDS                 Effective federal funds rate, monthly, 1954-
    MORTGAGE30US              30-year fixed mortgage rate, WEEKLY, 1971-
                              (resampled to monthly mean for macro_monthly;
                              the weekly series is not itself written out)
    GS10                      10-year Treasury constant maturity rate,
                              monthly, 1953-
    CUSR0000SEFV               CPI-U, Food Away From Home, U.S. city average,
                              seasonally adjusted, monthly, 1953-
    CUURA101SA0                CPI-U, All Items, New York-Newark-Jersey City
                              NY-NJ-PA (CBSA), NOT seasonally adjusted,
                              monthly, back to 1914 but with large early gaps
                              (BLS only sampled the NY metro periodically
                              before roughly the 1980s — the raw blanks are
                              dropped in tidy_series, not filled)
    USREC                     NBER-based recession indicator, monthly, binary
                              0/1, 1854- (annual rollup uses MAX, not MEAN —
                              a single recession month makes the year a
                              recession year for the hazard-driver join)
    CES7072200001             All employees, Food Services and Drinking
                              Places, U.S. (NAICS 7222), monthly, 1990-
    SMU36935617072200001       All employees, Leisure and Hospitality: Food
                              Services and Drinking Places, New York City NY
                              (the NYC-metro reading METHOD.md §5 wants for
                              "recession x the ZIP's restaurant share of
                              employment"), monthly, 1990-

Series NOT found and dropped from this pull (probed, no working FRED id):
    NYNRES, LAUCN360610000000003, LAUCT365000000000003,
    SMU36935610722200001, NYFOOD, NYCPI, CUURA101SEFV (404 — that id was
    guessed from CUSR0000SEFV's pattern; it does not exist. A
    NY-metro-specific food-away-from-home series was not found under any
    tried id — CUURA101SA0, the NY-metro ALL-ITEMS CPI, stands in as the
    regional cost-of-living series instead).

COVID WINDOW
---------------------------------------------------------------------------
Defined here as the one constant every RQ-001 notebook cell must import
rather than re-typing: NYC PAUSE (2020-03-22) through the last month CDC/NYC
still treated indoor dining and office return as suppressed, generously
through 2021-12. This is a modeling convenience flag, not a claim that
"COVID" ended on a specific date — METHOD.md §5 already says separating
COVID from the 2020 ACS collection anomaly is NOT identifiable.
"""
from __future__ import annotations

import datetime as dt
import io
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
USER_AGENT = "loci/rq001-macro (contact: repository owner)"
MAX_RETRIES = 4
BACKOFF_S = 3.0

#: (series_id, title, native_freq, units, rollup) — rollup is how
#: build_annual() aggregates that series' monthly (or weekly-resampled)
#: values into one number per year. "mean" for rates/indices/levels,
#: "max" for USREC (one recession month makes the year a recession year).
SERIES: tuple[dict, ...] = (
    {"series_id": "UNRATE", "title": "Unemployment rate, U.S.",
     "freq": "monthly", "units": "percent", "rollup": "mean"},
    {"series_id": "NYUR", "title": "Unemployment rate, New York State",
     "freq": "monthly", "units": "percent", "rollup": "mean"},
    {"series_id": "NEWY636URN",
     "title": "Unemployment rate, New York-Newark-Jersey City NY-NJ-PA MSA",
     "freq": "monthly", "units": "percent", "rollup": "mean"},
    {"series_id": "FEDFUNDS", "title": "Effective federal funds rate",
     "freq": "monthly", "units": "percent", "rollup": "mean"},
    {"series_id": "MORTGAGE30US", "title": "30-year fixed mortgage rate",
     "freq": "weekly", "units": "percent", "rollup": "mean"},
    {"series_id": "GS10", "title": "10-year Treasury constant maturity rate",
     "freq": "monthly", "units": "percent", "rollup": "mean"},
    {"series_id": "CUSR0000SEFV",
     "title": "CPI-U, Food Away From Home, U.S. city average (SA)",
     "freq": "monthly", "units": "index_1982_84_100", "rollup": "mean"},
    {"series_id": "CUURA101SA0",
     "title": "CPI-U, All Items, New York-Newark-Jersey City NY-NJ-PA CBSA (NSA)",
     "freq": "monthly", "units": "index_1982_84_100", "rollup": "mean"},
    {"series_id": "USREC", "title": "NBER-based recession indicator, U.S.",
     "freq": "monthly", "units": "binary", "rollup": "max"},
    {"series_id": "CES7072200001",
     "title": "All employees, Food Services and Drinking Places, U.S.",
     "freq": "monthly", "units": "thousands", "rollup": "mean"},
    {"series_id": "SMU36935617072200001",
     "title": "All employees, Leisure & Hospitality: Food Services and "
              "Drinking Places, New York City NY",
     "freq": "monthly", "units": "thousands", "rollup": "mean"},
)
SERIES_IDS: tuple[str, ...] = tuple(s["series_id"] for s in SERIES)
SERIES_BY_ID: dict[str, dict] = {s["series_id"]: s for s in SERIES}

#: NYC PAUSE (2020-03-22) through the last month indoor dining/office return
#: were still broadly suppressed. Constant, documented, used to derive a
#: COVID_WINDOW boolean column rather than re-deriving it per notebook.
COVID_WINDOW_START = dt.date(2020, 3, 1)
COVID_WINDOW_END = dt.date(2021, 12, 31)


class MacroFetchError(RuntimeError):
    """A FRED series could not be fetched, or came back with no usable rows.
    Raised rather than skipped — a macro series silently absent reads
    downstream as "macro was flat," and RQ-001 AC-10 requires macro to be
    either estimated or explicitly marked BLOCKED, never faked as zero."""


def fred_csv_url(series_id: str) -> str:
    return FRED_CSV.format(series_id=series_id)


def _get(url: str, timeout: int = 60) -> bytes:
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise MacroFetchError(
                    f"{url} -> HTTP 404: series id is wrong or retired "
                    "upstream, not a transient failure") from exc
            last = exc
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
        if attempt < MAX_RETRIES - 1:
            time.sleep(BACKOFF_S * (attempt + 1))
    raise MacroFetchError(f"{url} failed after {MAX_RETRIES} tries: {last}")


def fetch_series_csv(series_id: str, *, fetch=_get) -> bytes:
    """Raw bytes of one FRED series' CSV. Raises MacroFetchError on any
    total failure (network, HTTP error, or an empty body)."""
    blob = fetch(fred_csv_url(series_id))
    if not blob:
        raise MacroFetchError(
            f"{series_id}: FRED returned an empty body with no error. "
            "Refusing to treat that as a zero-row series.")
    return blob


def tidy_series(csv_bytes: bytes, meta: dict) -> pd.DataFrame:
    """One FRED series' CSV -> tidy long rows: series_id, date, value, freq,
    units, title. FRED marks a missing observation as an empty string (or
    the sentinel "."); both are dropped here rather than coerced to 0 --
    a dropped row is a documented gap, a coerced 0 is a fabricated one."""
    df = pd.read_csv(io.BytesIO(csv_bytes))
    date_col, value_col = df.columns[0], df.columns[1]
    if value_col != meta["series_id"]:
        raise MacroFetchError(
            f"expected FRED to name the value column '{meta['series_id']}', "
            f"got '{value_col}' -- the id may have been redirected upstream")
    df = df.rename(columns={date_col: "date", value_col: "value"})
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).copy()
    if df.empty:
        raise MacroFetchError(
            f"{meta['series_id']}: every observation was blank/non-numeric "
            "after parsing -- treating this as a total fetch failure")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["series_id"] = meta["series_id"]
    df["freq"] = meta["freq"]
    df["units"] = meta["units"]
    df["title"] = meta["title"]
    return df[["series_id", "date", "value", "freq", "units", "title"]].sort_values(
        ["series_id", "date"]).reset_index(drop=True)


def fetch_all(series_ids=None, *, fetch=_get, progress=None) -> pd.DataFrame:
    """Fetch + tidy every requested series (default: all of SERIES_IDS).
    ONE series failing raises immediately and fetches nothing further silent
    -- same contract as lodes_wac.download(): a partial macro pull that
    reports success would leave a hole no downstream code could see."""
    ids = list(series_ids) if series_ids is not None else list(SERIES_IDS)
    unknown = [s for s in ids if s not in SERIES_BY_ID]
    if unknown:
        raise MacroFetchError(f"not in SERIES_IDS (unknown to this adapter): {unknown}")
    frames = []
    for sid in ids:
        meta = SERIES_BY_ID[sid]
        blob = fetch_series_csv(sid, fetch=fetch)
        frame = tidy_series(blob, meta)
        frames.append(frame)
        if progress is not None:
            progress(sid, len(frame))
    return pd.concat(frames, ignore_index=True)


def _resample_weekly_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """MORTGAGE30US is published weekly; every other series here is monthly.
    Resampled to a monthly mean so macro_monthly.parquet has one row per
    (series_id, month) for every series -- the weekly cadence is preserved
    only implicitly, via this mean."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = (out.set_index("date")
              .groupby("series_id")["value"]
              .resample("MS").mean()
              .reset_index())
    meta = SERIES_BY_ID["MORTGAGE30US"]
    out["freq"] = "monthly"  # resampled from weekly, see module docstring
    out["units"] = meta["units"]
    out["title"] = meta["title"]
    out["date"] = out["date"].dt.date
    return out.dropna(subset=["value"])


def build_monthly(tidy: pd.DataFrame) -> pd.DataFrame:
    """macro_monthly grain: one row per (series_id, date) with every series
    on a monthly cadence (MORTGAGE30US resampled from weekly), plus a
    covid_window boolean. Non-monthly-native series pass through unchanged."""
    monthly_native = tidy[tidy["freq"] == "monthly"]
    weekly = tidy[tidy["freq"] == "weekly"]
    parts = [monthly_native]
    if not weekly.empty:
        parts.append(_resample_weekly_to_monthly(weekly))
    out = pd.concat(parts, ignore_index=True).sort_values(["series_id", "date"])
    out["covid_window"] = out["date"].apply(
        lambda d: COVID_WINDOW_START <= d <= COVID_WINDOW_END)
    return out.reset_index(drop=True)


def build_annual(monthly: pd.DataFrame) -> pd.DataFrame:
    """One row per (series_id, year). rollup is "mean" for rates/indices and
    "max" for USREC (see SERIES' rollup field) -- a mean would understate a
    one-month recession spike to near-zero for the year it happened in."""
    rows = []
    for sid, grp in monthly.groupby("series_id"):
        meta = SERIES_BY_ID.get(sid)
        rollup = meta["rollup"] if meta else "mean"
        units = meta["units"] if meta else grp["units"].iloc[0]
        title = meta["title"] if meta else grp["title"].iloc[0]
        g = grp.copy()
        g["year"] = pd.to_datetime(g["date"]).dt.year
        agg = g.groupby("year")["value"].max() if rollup == "max" else g.groupby("year")["value"].mean()
        agg = agg.reset_index()
        agg["series_id"] = sid
        agg["units"] = units
        agg["title"] = title
        agg["rollup"] = rollup
        # A year is inside the COVID window if any of its months are.
        covid_years = set(pd.to_datetime(
            g.loc[g["covid_window"], "date"]).dt.year) if "covid_window" in g else set()
        agg["covid_window"] = agg["year"].isin(covid_years)
        rows.append(agg)
    out = pd.concat(rows, ignore_index=True)
    return out[["series_id", "year", "value", "units", "title", "rollup",
                "covid_window"]].sort_values(["series_id", "year"]).reset_index(drop=True)


@dataclass
class MacroBuild:
    monthly: pd.DataFrame
    annual: pd.DataFrame
    fetched: dict[str, int]  # series_id -> row count, for the CLI/report line


def build(series_ids=None, *, fetch=_get, progress=None) -> MacroBuild:
    """Full pipeline: fetch every series, tidy, build monthly + annual. Does
    NOT write files or touch the warehouse -- see write_parquet() and the
    caller for that, kept separate so this stays testable without I/O."""
    fetched_counts: dict[str, int] = {}

    def _progress(sid, n):
        fetched_counts[sid] = n
        if progress is not None:
            progress(sid, n)

    tidy = fetch_all(series_ids, fetch=fetch, progress=_progress)
    monthly = build_monthly(tidy)
    annual = build_annual(monthly)
    return MacroBuild(monthly=monthly, annual=annual, fetched=fetched_counts)


def write_parquet(build_result: MacroBuild, out_dir) -> dict:
    """Write macro_monthly.parquet and macro_annual.parquet under out_dir.
    Separate from build() so tests can exercise the pipeline with no
    filesystem writes."""
    import pathlib
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    monthly_path = out_dir / "macro_monthly.parquet"
    annual_path = out_dir / "macro_annual.parquet"
    build_result.monthly.to_parquet(monthly_path, index=False)
    build_result.annual.to_parquet(annual_path, index=False)
    return {"monthly_path": str(monthly_path), "monthly_rows": len(build_result.monthly),
            "annual_path": str(annual_path), "annual_rows": len(build_result.annual)}
