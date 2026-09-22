"""Decennial Census, ZCTA geography, 2000/2010/2020 -- the pre-ACS DEMAND
baseline for RQ-002 (Greenpoint towers, docs/research/RQ-002-greenpoint-
towers-retail/). Registry id `census_decennial_zcta` (drafted, not yet
registered -- see docs/research/RQ-002-greenpoint-towers-retail/drafts/
registry-census.yaml). DATA-AUDIT.md flagged this as the single most
consequential gap for the control-ZIP pre-trend match: nothing in the
project reached earlier than 1998 (ZBP) for any demand-side measure before
this module.

THREE VINTAGES, THREE DIFFERENT CENSUS PRODUCTS -- PROBED LIVE 2026-09-22
---------------------------------------------------------------------------
Decennial census products changed shape every ten years; ZCTA geography
support and the fields available differ per vintage, verified directly
against the live API (not assumed from documentation):

  2000: `dec/sf1` (short form, full count) has population/housing/tenure.
        `dec/sf3` (long form, ~1-in-6 SAMPLE, so these two fields carry
        sampling error despite being "decennial") has median household
        income and median gross rent -- ACS's precursor tables, same
        sample-based caveat applies. BOTH datasets serve
        `for=zip+code+tabulation+area:*` directly, confirmed 33,178 ZCTA
        rows returned for `dec/sf1` and matching rows for `dec/sf3`.
  2010: `dec/sf1` only -- SF3/the long-form sample was discontinued after
        2000 (replaced by the now-annual ACS), so 2010 has NO decennial
        income or rent field at all. Population/housing/occupied/
        owner+renter-occupied are all present. 33,120 ZCTA rows.
  2020: `dec/pl` (PL 94-171, the redistricting file, first out) does NOT
        serve ZCTA geography at all -- confirmed live: `for=zip+code+
        tabulation+area:11222` against `2020/dec/pl` returns
        `error: unknown/unsupported geography hierarchy`. `dec/dhc`
        (Demographic and Housing Characteristics File, released later)
        DOES serve ZCTA geography and carries the same population/housing/
        tenure fields PL94-171 has for other geographies, so this module
        uses `dec/dhc` exclusively for 2020 -- there is no PL94-171 branch.
        33,774 ZCTA rows. No income/rent in DHC either (ACS-only since 2010).

VARIABLE MAP, VERIFIED AGAINST EACH VINTAGE'S OWN variables.json
---------------------------------------------------------------------------
Table H004 (owner/renter breakdown) is NOT the same shape in 2000 vs 2010 --
verified by pulling both variables.json files rather than assumed constant:
  2000 H004: 002=Owner occupied, 003=Renter occupied (2 cells).
  2010 H004: 002=Owned w/ mortgage, 003=Owned free & clear, 004=Renter
             occupied (3 cells; owner_occupied_2010 = 002 + 003).
2020 uses table H10 (Tenure by Race, DHC) instead of H004 (DHC has no plain
H004 table): 001=total occupied, 002=owner occupied, 010=renter occupied.
`VINTAGE_SPEC` below records each vintage's dataset(s)/variables exactly as
probed; nothing here infers a 2010 or 2020 shape from the 2000 layout.

FAIL LOUD
---------------------------------------------------------------------------
Every fetch raises (never returns an empty/partial frame silently) on: a
missing CENSUS_API_KEY, a non-2xx API response, or zero data rows.

ZCTA DEFINITIONS CHANGE BETWEEN VINTAGES -- KEPT, NOT CROSSWALKED
---------------------------------------------------------------------------
Per this task's brief, the RAW vintage ZCTA is kept for every year (a 2000
ZCTA5 code is not guaranteed to cover the same area as the numerically
identical 2020 code -- see `census_zcta_boundaries.py`'s own caveat). A ZCTA
present in one vintage's Census response and absent from another's is
recorded as ABSENT (a boolean `present` flag in the combined long file), not
silently dropped from the ZCTA universe or filled with a zero. The peer
session building the ZIP-merge crosswalk (11211+11249, 10021+10065+10075,
11101+11109) is explicitly out of scope here.

INTERPOLATED POPULATION FILE -- CONSUMED BY A PEER (RQ-001)
---------------------------------------------------------------------------
`zcta_pop_interpolated_2000_2020.parquet` gives one row per (zcta, year) for
every year 2000..2020, linear-interpolated between whichever decennial
anchors that zcta actually has (2000<->2010, 2010<->2020, or directly
2000<->2020 if the 2010 vintage is missing that code). A zcta with only ONE
anchor present cannot be interpolated at all -- it gets exactly that one
anchor row (`method="anchor"`) and no synthesized years, rather than a flat
extrapolation that would fabricate a trend. Columns are fixed at
`zcta, year, pop, method, is_anchor` because a peer session (abenmayor-9f,
RQ-001) reads this exact schema -- do not rename or reorder these columns.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import pandas as pd
import requests

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
RAW_DIR = REPO_ROOT / "data" / "raw" / "decennial_zcta"
INTERIM_DIR = REPO_ROOT / "data" / "interim" / "rq002" / "decennial"

_GEO_COL = "zip code tabulation area"

# One entry per (year, dataset) API pull actually made. `fields` maps output
# column -> Census variable stem (no E/M suffix -- decennial vars have none).
VINTAGE_SPEC: dict[int, list[dict]] = {
    2000: [
        {"dataset": "dec/sf1", "fields": {
            "population": "P001001", "housing_units": "H001001",
            "occupied_housing_units": "H003002",
            "owner_occupied": "H004002", "renter_occupied": "H004003",
        }},
        {"dataset": "dec/sf3", "fields": {
            "median_household_income": "P053001", "median_gross_rent": "H063001",
        }},
    ],
    2010: [
        {"dataset": "dec/sf1", "fields": {
            "population": "P001001", "housing_units": "H001001",
            "occupied_housing_units": "H003002",
            "owner_occupied_mortgage": "H004002", "owner_occupied_free_clear": "H004003",
            "renter_occupied": "H004004",
        }},
    ],
    2020: [
        {"dataset": "dec/dhc", "fields": {
            "population": "P1_001N", "housing_units": "H1_001N",
            "occupied_housing_units": "H10_001N",
            "owner_occupied": "H10_002N", "renter_occupied": "H10_010N",
        }},
    ],
}
VINTAGES = (2000, 2010, 2020)


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


def _raw_cache_path(year: int, dataset: str) -> pathlib.Path:
    safe = dataset.replace("/", "_")
    return RAW_DIR / f"decennial_{safe}_{year}.json"


def fetch_dataset_raw(year: int, dataset: str, fields: dict[str, str], *,
                       force: bool = False, timeout: int = 120) -> list[list[str]]:
    """Cache-first raw Census API pull for one (year, dataset) pair, ALL
    ZCTAs nationally (`for=zip+code+tabulation+area:*`, no state filter --
    ZCTA is a national, not state-nested, geography for the decennial API,
    confirmed live for all three vintages). Returned in the API's own
    [header, row, row, ...] shape plus cache metadata. Fails loud on a
    missing key, non-2xx response, or zero data rows."""
    cache_path = _raw_cache_path(year, dataset)
    getvars = sorted(fields.values())
    if not force and cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get("vars") == getvars and cached.get("year") == year \
                and cached.get("dataset") == dataset:
            return cached["data"]
    key = _census_key()
    if not key:
        raise RuntimeError(
            "no CENSUS_API_KEY found (checked loci/.env and the environment). "
            "Decennial ZCTA data must be FETCHED, never guessed or zero-filled "
            "-- set the key and re-run.")
    url = f"https://api.census.gov/data/{year}/{dataset}"
    params = {"get": ",".join(getvars), "for": f"{_GEO_COL}:*", "key": key}
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if len(payload) <= 1:
        raise RuntimeError(f"decennial {dataset} {year} pull returned zero data rows")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "year": year, "dataset": dataset, "vars": getvars, "data": payload,
        "source_url": url, "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }))
    return payload


def _parse_dataset(data: list[list[str]], fields: dict[str, str]) -> pd.DataFrame:
    head, rows = data[0], data[1:]
    idx = {c: i for i, c in enumerate(head)}
    zi = idx[_GEO_COL]
    inv = {v: k for k, v in fields.items()}  # Census var -> output column
    records = []
    for row in rows:
        rec = {"zcta": str(row[zi]).zfill(5)}
        for var, i in idx.items():
            if var in inv:
                raw = row[i]
                try:
                    rec[inv[var]] = float(raw) if raw not in (None, "", "null") else None
                except (TypeError, ValueError):
                    rec[inv[var]] = None
        records.append(rec)
    return pd.DataFrame(records)


def build_vintage(year: int, *, force: bool = False) -> pd.DataFrame:
    """One vintage's national ZCTA panel row set -- merges every dataset
    pull for that year (2000 merges sf1 + sf3) on `zcta`. Derives
    `owner_occupied` for 2010 (mortgage + free-and-clear cells) since that
    vintage has no single owner-occupied total variable. Every row carries
    `decennial_year` and `datasets` (comma-joined provenance)."""
    if year not in VINTAGE_SPEC:
        raise ValueError(f"unknown decennial vintage {year!r}; expected one of {VINTAGES}")
    specs = VINTAGE_SPEC[year]
    merged: pd.DataFrame | None = None
    dataset_names = []
    for spec in specs:
        raw = fetch_dataset_raw(year, spec["dataset"], spec["fields"], force=force)
        df = _parse_dataset(raw, spec["fields"])
        dataset_names.append(spec["dataset"])
        merged = df if merged is None else merged.merge(df, on="zcta", how="outer")
    if merged is None or merged.empty:
        raise RuntimeError(f"decennial {year}: no data merged from {dataset_names}")
    if year == 2010:
        merged["owner_occupied"] = (
            merged["owner_occupied_mortgage"].fillna(0)
            + merged["owner_occupied_free_clear"].fillna(0)
        )
    merged["decennial_year"] = year
    merged["datasets"] = ",".join(dataset_names)
    return merged.reset_index(drop=True)


def build_all(*, force: bool = False) -> dict[int, pd.DataFrame]:
    """Every vintage's panel, written individually and combined. Prints one
    progress line per vintage."""
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    frames: dict[int, pd.DataFrame] = {}
    for year in VINTAGES:
        df = build_vintage(year, force=force)
        path = INTERIM_DIR / f"decennial_zcta_{year}.parquet"
        df.to_parquet(path, index=False)
        print(f"[census_decennial_zcta] {year}: {len(df)} ZCTAs, "
              f"datasets={df['datasets'].iloc[0]} -> {path.name}")
        frames[year] = df
    return frames


def build_long(frames: dict[int, pd.DataFrame] | None = None, *,
                force: bool = False) -> pd.DataFrame:
    """Combined long panel across ALL ZCTA codes ever seen (union of the
    three vintages' own ZCTA sets) x the three decennial years -- an outer
    join, not an inner one, so a ZCTA present in only one or two vintages
    still gets a row for every year with `present=False` and null metrics
    for the years it is missing, rather than being dropped from the file or
    silently zero-filled."""
    frames = frames or build_all(force=force)
    all_zctas = sorted(set().union(*(set(df["zcta"]) for df in frames.values())))
    scaffold = pd.DataFrame(
        [(z, y) for z in all_zctas for y in VINTAGES], columns=["zcta", "decennial_year"])
    long_frames = []
    for year, df in frames.items():
        year_df = df.copy()
        year_df["present"] = True
        long_frames.append(year_df)
    stacked = pd.concat(long_frames, ignore_index=True)
    out = scaffold.merge(stacked, on=["zcta", "decennial_year"], how="left")
    out["present"] = out["present"].astype("boolean").fillna(False).astype(bool)
    n_missing = (~out["present"]).sum()
    print(f"[census_decennial_zcta] combined long panel: {len(all_zctas)} distinct ZCTAs "
          f"x {len(VINTAGES)} vintages = {len(out)} rows, {n_missing} (zcta, year) "
          f"cells flagged present=False")
    path = INTERIM_DIR / "decennial_zcta_long.parquet"
    out.to_parquet(path, index=False)
    return out


# ---------------------------------------------------------- interpolation

def interpolate_population(long_df: pd.DataFrame | None = None, *,
                            force: bool = False) -> pd.DataFrame:
    """Yearly population per ZCTA, 2000..2020, linear-interpolated between
    whichever decennial anchors that ZCTA actually has present. Columns are
    FIXED at `zcta, year, pop, method, is_anchor` -- a peer session (RQ-001)
    reads this exact schema.

    A ZCTA with population present at all three anchors gets 21 rows
    (2000..2020), interpolated piecewise (2000-2010, then 2010-2020) so a
    kink at 2010 is possible and expected (this is NOT a single straight
    line across the whole span). A ZCTA missing the 2010 anchor still
    interpolates directly 2000->2020 across the full 20-year gap. A ZCTA
    with only ONE anchor present gets exactly that one row
    (`method="anchor"`) -- no extrapolation, since a single point implies no
    trend."""
    long_df = long_df if long_df is not None else build_long(force=force)
    anchors = long_df[long_df["present"] & long_df["population"].notna()][
        ["zcta", "decennial_year", "population"]].rename(
        columns={"decennial_year": "year", "population": "pop"})
    out_rows = []
    for zcta, group in anchors.groupby("zcta"):
        pts = group.sort_values("year")
        years_present = pts["year"].tolist()
        pops = dict(zip(pts["year"], pts["pop"]))
        if len(years_present) == 1:
            y = years_present[0]
            out_rows.append({"zcta": zcta, "year": y, "pop": pops[y],
                              "method": "anchor", "is_anchor": True})
            continue
        for lo, hi in zip(years_present[:-1], years_present[1:]):
            span = hi - lo
            for y in range(lo, hi + 1):
                is_anchor = y in (lo, hi)
                if is_anchor:
                    pop = pops[y]
                    method = "anchor"
                else:
                    frac = (y - lo) / span
                    pop = pops[lo] + frac * (pops[hi] - pops[lo])
                    method = "linear_interp"
                # 2010 (the shared boundary of the 2000-2010 and 2010-2020
                # segments) is appended twice when all 3 anchors are present;
                # the final drop_duplicates below keeps the first (anchor)
                # copy either way, so no special-casing is needed here.
                out_rows.append({"zcta": zcta, "year": y, "pop": pop,
                                  "method": method, "is_anchor": is_anchor})
    out = pd.DataFrame(out_rows).drop_duplicates(subset=["zcta", "year"], keep="first")
    out = out.sort_values(["zcta", "year"]).reset_index(drop=True)
    path = INTERIM_DIR / "zcta_pop_interpolated_2000_2020.parquet"
    out.to_parquet(path, index=False)
    n_zctas = out["zcta"].nunique()
    anchor_counts = anchors.groupby("zcta").size()
    n_anchor_only = int((anchor_counts == 1).sum())
    print(f"[census_decennial_zcta] interpolated population: {n_zctas} ZCTAs, "
          f"{len(out)} (zcta, year) rows, {n_anchor_only} ZCTAs with only one anchor "
          f"(no interpolation possible) -> {path.name}")
    return out


def build(*, force: bool = False) -> dict[str, pathlib.Path]:
    """Full pipeline: per-vintage panels -> combined long panel -> interpolated
    population file. Returns the paths of every parquet written."""
    frames = build_all(force=force)
    long_df = build_long(frames, force=force)
    interpolate_population(long_df, force=force)
    return {
        **{f"vintage_{y}": INTERIM_DIR / f"decennial_zcta_{y}.parquet" for y in VINTAGES},
        "long": INTERIM_DIR / "decennial_zcta_long.parquet",
        "interpolated_pop": INTERIM_DIR / "zcta_pop_interpolated_2000_2020.parquet",
    }


if __name__ == "__main__":
    build()
