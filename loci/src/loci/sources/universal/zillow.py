"""Zillow ZHVI / ZORI ingest — COST pillar input for RQ-001 (regime-durability,
docs/research/RQ-001-regime-durability/). Registry id `zillow_zori_zhvi`
(registry.yaml, `status: planned` as of this ingest — this module is the first
adapter code against it).

WHY THIS EXISTS
----------------
DATA-AUDIT.md (RQ-001) found COST the weakest of the three ZIP-tier pillars:
zero Zillow rows were ever ingested despite the source being registered
`verified`/servable back to 2000. This module is the adapter: download the
two public CSVs Zillow Research publishes (no auth, no rate limit), filter to
the five NYC boroughs, and tidy to a long panel plus an annual mean —
METHOD.md's ZIP panel wants ZHVI as the headline COST component (2000→latest,
"lower is favorable") and ZORI only as a rank-correlation check from 2015 on,
never a composite input (a definition that starts mid-panel would manufacture
fake exits).

FILES, VERIFIED LIVE 2026-09-22
--------------------------------
  ZHVI: https://files.zillowstatic.com/research/public_csvs/zhvi/
        Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv
        "All Homes (SFR, Condo/Co-op), Smoothed, Seasonally Adjusted",
        monthly columns 2000-01-31 .. current, ~123 MB, all national ZIPs.
  ZORI: https://files.zillowstatic.com/research/public_csvs/zori/
        Zip_zori_uc_sfrcondomfr_sm_sa_month.csv
        "All Homes Plus Multifamily, Smoothed, Seasonally Adjusted",
        monthly columns 2015-01-31 .. current, ~10 MB.

Both share the same header shape: RegionID, SizeRank, RegionName (the ZIP,
as a string — NOT parsed as int, Zillow does not zero-pad but some NYC ZIPs
like 07030-adjacent could in principle collide if cast to int and back; kept
as `dtype=str` defensively), RegionType, StateName, State, City, Metro,
CountyName, then one column per month-end date.

NYC FILTER
----------
State == "NY" and CountyName in the five borough county names, verified
directly against the live ZHVI file's own CountyName value_counts on
2026-09-22: "Bronx County" (20 ZIPs), "Kings County" (37), "New York County"
(31), "Queens County" (41), "Richmond County" (10) — 139 ZIPs. This uses the
Zillow file's OWN columns; no external ZIP↔county crosswalk needed, unlike
the ACS ZCTA adapter in this same directory (Zillow ZIPs are postal ZIPs, not
ZCTAs, and Zillow already resolves them to a county).

CAVEATS THE DATABASE / THIS MODULE CANNOT ENFORCE
--------------------------------------------------
- Postal ZIP, not ZCTA. Joining this to ACS/decennial data (ZCTA-keyed)
  requires the frozen ZIP↔ZCTA crosswalk METHOD.md §1 calls for — NOT done
  here; this module's job stops at a clean NYC ZIP panel.
- ZORI covers a subset of ZIPs (sparser than ZHVI — low-density listing ZIPs
  are dropped by Zillow itself, not by this filter). A ZIP present in the
  annual ZHVI panel is not guaranteed present in ZORI.
- Smoothed/seasonally-adjusted values are Zillow's own model output, not raw
  transaction prices — do not treat ZHVI as a sale-price index.
"""
from __future__ import annotations

import pathlib

import pandas as pd
import requests

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
RAW_DIR = REPO_ROOT / "data" / "raw" / "zillow"
INTERIM_DIR = REPO_ROOT / "data" / "interim" / "rq001" / "zillow"

URLS: dict[str, str] = {
    "zhvi": ("https://files.zillowstatic.com/research/public_csvs/zhvi/"
             "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"),
    "zori": ("https://files.zillowstatic.com/research/public_csvs/zori/"
             "Zip_zori_uc_sfrcondomfr_sm_sa_month.csv"),
}
RAW_FILES: dict[str, pathlib.Path] = {
    "zhvi": RAW_DIR / "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "zori": RAW_DIR / "Zip_zori_uc_sfrcondomfr_sm_sa_month.csv",
}

# Verified against the live ZHVI file's CountyName column, 2026-09-22.
NYC_COUNTIES = {
    "Bronx County", "Kings County", "New York County", "Queens County", "Richmond County",
}
ID_COLS = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName",
           "State", "City", "Metro", "CountyName"]


def fetch_raw(index: str, *, force: bool = False, timeout: int = 300) -> pathlib.Path:
    """Download (or reuse the cached copy of) Zillow's public CSV for `index`
    ('zhvi' or 'zori'). Fails loud: a non-2xx response or an empty body raises
    rather than caching a truncated file a later read would silently treat as
    zero rows."""
    if index not in URLS:
        raise ValueError(f"unknown Zillow index {index!r}; expected one of {sorted(URLS)}")
    path = RAW_FILES[index]
    if path.exists() and not force:
        return path
    resp = requests.get(URLS[index], timeout=timeout)
    resp.raise_for_status()
    if not resp.content:
        raise RuntimeError(f"Zillow {index} download returned an empty body from {URLS[index]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return path


def _month_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ID_COLS]


def load_nyc_tidy(index: str, *, force: bool = False,
                   path: pathlib.Path | None = None) -> pd.DataFrame:
    """Tidy long NYC panel for `index`: one row per (zip, month).

    Columns: zip (str), month (Timestamp, the CSV's own column label, always
    a month-end date), index ('zhvi'/'zori'), value (float), county_name
    (provenance). Filters to State == 'NY' and CountyName in the five NYC
    counties using the file's own columns.

    Fails loud if the read comes back empty or the NYC filter matches zero
    rows — either is a broken schema, not a legitimate "no NYC data" result.
    """
    csv_path = path or fetch_raw(index, force=force)
    df = pd.read_csv(csv_path, dtype={"RegionName": str})
    if df.empty:
        raise RuntimeError(f"Zillow {index} CSV at {csv_path} parsed to zero rows")
    missing_id_cols = [c for c in ID_COLS if c not in df.columns]
    if missing_id_cols:
        raise RuntimeError(f"Zillow {index} CSV at {csv_path} is missing expected columns "
                            f"{missing_id_cols} — schema likely changed upstream")
    nyc = df[(df["State"] == "NY") & (df["CountyName"].isin(NYC_COUNTIES))].copy()
    if nyc.empty:
        raise RuntimeError(f"Zillow {index}: NYC filter (State=NY, 5 boroughs) matched zero "
                            f"of {len(df)} rows in {csv_path} — filter or source schema broke")
    month_cols = _month_columns(df)
    long = nyc.melt(id_vars=["RegionName", "CountyName"], value_vars=month_cols,
                     var_name="month", value_name="value")
    long = long.rename(columns={"RegionName": "zip", "CountyName": "county_name"})
    long["month"] = pd.to_datetime(long["month"])
    long["index"] = index
    long = long.dropna(subset=["value"])
    return long[["zip", "month", "index", "value", "county_name"]].reset_index(drop=True)


def annualize(long_df: pd.DataFrame) -> pd.DataFrame:
    """Annual mean of the monthly tidy panel: one row per (zip, year, index).

    `n_months` records how many of the 12 monthly observations fed the mean —
    a partial current-year mean (fewer than 12) should read as provisional,
    not silently averaged in on equal footing with a complete year."""
    out = long_df.copy()
    out["year"] = out["month"].dt.year
    grouped = (out.groupby(["zip", "year", "index"], as_index=False)
                  .agg(value_mean=("value", "mean"), n_months=("value", "size")))
    return grouped.sort_values(["index", "zip", "year"]).reset_index(drop=True)


def build(*, force: bool = False) -> dict[str, pathlib.Path]:
    """Fetch both indexes, tidy to NYC long panels, write monthly + annual
    parquet under data/interim/rq001/zillow/. Prints one progress line per
    index so a full run can be watched rather than trusted blind."""
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    monthly_frames, annual_frames = [], []
    for index in ("zhvi", "zori"):
        long_df = load_nyc_tidy(index, force=force)
        ann_df = annualize(long_df)
        n_zip = long_df["zip"].nunique()
        yr_min, yr_max = int(long_df["month"].dt.year.min()), int(long_df["month"].dt.year.max())
        print(f"[zillow] {index}: {n_zip} NYC ZIPs, {len(long_df)} monthly rows, "
              f"{yr_min}-{yr_max}")
        monthly_frames.append(long_df)
        annual_frames.append(ann_df)
    monthly = pd.concat(monthly_frames, ignore_index=True)
    annual = pd.concat(annual_frames, ignore_index=True)
    monthly_path = INTERIM_DIR / "zillow_nyc_monthly.parquet"
    annual_path = INTERIM_DIR / "zillow_nyc_annual.parquet"
    monthly.to_parquet(monthly_path, index=False)
    annual.to_parquet(annual_path, index=False)
    return {"monthly": monthly_path, "annual": annual_path}


if __name__ == "__main__":
    build()
