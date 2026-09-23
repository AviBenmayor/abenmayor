"""Helper functions for RQ-002 — Greenpoint towers and the retail landscape.

docs/research/RQ-002-greenpoint-towers-retail/. Keeps the notebook readable by
moving non-trivial data assembly here; the modeling *choices* (control-ZIP distance
metric, tower threshold, category buckets, anchors) are made and justified in the
notebook's own Method section, not hidden in this module.

Scope discipline: this module reads the warehouse read-only and reads the interim
parquet files other sessions/modules already built (Zillow, ACS ZCTA panel, decennial
ZCTA, ZCTA boundaries, DOF assessment history). It writes nothing back to the
warehouse and nothing outside docs/research/RQ-002.../ or the caller's own return
values.
"""
from __future__ import annotations

import pathlib
import time

import duckdb
import numpy as np
import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]  # .../loci
DB_PATH = REPO_ROOT / "data" / "loci.duckdb"
INTERIM = REPO_ROOT / "data" / "interim"

# ---------------------------------------------------------------------- constants

TREATMENT_ZIP = "11222"

#: North Brooklyn / western Queens candidates for the control-ZIP screen. 11211 and
#: 11249 are excluded per SEED.yaml (they got their own waterfront towers). This list
#: is the set of ZIPs that (a) have zip_category_establishments coverage and (b) are
#: geographically adjacent North Brooklyn (Bushwick/Ridgewood) or western Queens
#: (Long Island City/Astoria) neighborhoods -- i.e. plausible pre-rezoning-era
#: industrial-waterfront-adjacent analogues to 11222, not an arbitrary NYC-wide pull.
CANDIDATE_CONTROL_ZIPS = [
    "11206", "11221", "11237", "11385",  # North Brooklyn: Bushwick, Bushwick, Bushwick/Ridgewood, Ridgewood/Glendale
    "11101", "11102", "11103", "11104", "11105", "11106", "11109",  # western Queens: LIC, Astoria
]
EXCLUDED_ZIPS = {"11211", "11249"}

#: Loci's 16 POI categories (per analysis.zip_category_establishments /
#: analysis.licence_interval, D137's `brewery` addition is a 17th category not yet
#: present in the ZBP crosswalk as of this pull) bucketed into the four groups
#: SEED.yaml names ("food & drink, grocery, services, shops"). A modeling choice
#: made here and stated, not hidden: `bathhouse_sauna` -> services (a personal-care
#: destination use, not a shop); `pharmacy`/`hardware` -> shops (retail goods, not a
#: service rendered on-site).
CATEGORY_BUCKET = {
    "bar": "food_drink", "cafe_bakery": "food_drink", "restaurant": "food_drink",
    "grocery": "grocery", "convenience": "grocery",
    "bank": "services", "childcare": "services", "clinic": "services",
    "fitness": "services", "hair_barber": "services", "laundry": "services",
    "nails_beauty": "services", "tailor_repair": "services", "bathhouse_sauna": "services",
    "hardware": "shops", "pharmacy": "shops",
}
BUCKETS = ["food_drink", "grocery", "services", "shops"]

#: "Massive housing development" / tower threshold used for AC-3. The warehouse has
#: no `stories`/`numfloors` field for any New Building job (DATA-AUDIT.md's TOWERS/
#: PLUTO row: MapPLUTO is not ingested as a historical time series, only a
#: current-day snapshot with no yearbuilt/numfloors column reachable from
#: analysis.dev_pipeline) -- so height cannot be enforced from warehouse data alone.
#: The threshold used here is UNITS ONLY: net_units >= 100. This is stated, not
#: silently substituted for the seed's "roughly >=10 stories" language; a ~100-unit
#: NYC multifamily building is very rarely under 10 stories on a standard
#: R6/R7/R8-zoned waterfront lot, but that correspondence is not verified row-by-row
#: here (that verification is web-verification's job per the brief, not this
#: notebook's).
TOWER_UNIT_THRESHOLD = 100

#: Greenpoint-Williamsburg rezoning: NYC Council approval, May 11 2005 (ULURP
#: #043-04ZMK et al.), the SEED-mandated first anchor.
REZONING_DATE = pd.Timestamp("2005-05-11")


# ------------------------------------------------------------------- warehouse I/O

def connect_ro(db_path: pathlib.Path | None = None, *, max_wait_s: int = 1800,
               interval_s: int = 120):
    """Open the warehouse read-only, retrying on a lock every `interval_s` seconds
    up to `max_wait_s`, printing one progress line per attempt (a peer session may
    hold a write lock -- this is expected, not an error, until the deadline).
    Raises RuntimeError at the deadline rather than falling back to a copy of the
    file: a stale copy could silently disagree with the live warehouse, which is a
    worse failure mode than stopping and saying BLOCKED."""
    path = db_path or DB_PATH
    deadline = time.monotonic() + max_wait_s
    attempt = 0
    last_err: Exception | None = None
    while True:
        attempt += 1
        try:
            con = duckdb.connect(str(path), read_only=True)
            con.execute("INSTALL spatial; LOAD spatial;")  # ST_Centroid/ST_X/ST_Y used below
            print(f"[rq002] connected read_only=True to {path} (attempt {attempt})")
            return con
        except duckdb.IOException as exc:
            last_err = exc
            if time.monotonic() >= deadline:
                break
            print(f"[rq002] attempt {attempt}: warehouse locked, retrying in "
                  f"{interval_s}s ... ({exc})")
            time.sleep(interval_s)
    raise RuntimeError(
        f"BLOCKED on warehouse lock: could not open {path} read_only after "
        f"{attempt} attempts over {max_wait_s}s. Last error: {last_err}")


# ------------------------------------------------------------------------- towers

def load_tower_timeline(con) -> pd.DataFrame:
    """Every New Building job in Greenpoint (analysis.dev_pipeline), tower_flag set
    at TOWER_UNIT_THRESHOLD, pipeline_flag set for anything not yet complete."""
    df = con.execute("""
        select job_number, bbl, net_units, units_init, units_prop, units_complete,
               stage, dcp_status, date_filed, date_permitted, date_complete, co_type,
               activity_status, source
        from analysis.dev_pipeline
        where neighborhood = 'Greenpoint' and job_type = 'New Building'
        order by date_filed
    """).df()
    df["tower_flag"] = df["net_units"] >= TOWER_UNIT_THRESHOLD
    df["pipeline_flag"] = df["stage"].isin(["filed", "permitted"])
    df["withdrawn_flag"] = df["stage"] == "withdrawn"
    df["complete_year"] = pd.to_datetime(df["date_complete"]).dt.year
    df["filed_year"] = pd.to_datetime(df["date_filed"]).dt.year
    return df


def new_units_per_year(tower_df: pd.DataFrame) -> pd.DataFrame:
    """Units actually delivered (date_complete populated), by calendar year, across
    ALL Greenpoint New Building jobs (not just tower_flag rows) -- the full supply
    series AC-3 asks for, with a separate column for the tower-threshold subset."""
    complete = tower_df.dropna(subset=["complete_year"]).copy()
    complete["complete_year"] = complete["complete_year"].astype(int)
    all_units = complete.groupby("complete_year")["units_complete"].sum(min_count=1)
    tower_units = (complete[complete["tower_flag"]]
                   .groupby("complete_year")["units_complete"].sum(min_count=1))
    out = pd.DataFrame({"units_complete_all": all_units,
                         "units_complete_towers_only": tower_units}).fillna(0).astype(int)
    out.index.name = "year"
    return out.reset_index()


# ------------------------------------------------------------------ ZBP / category

def load_zbp_category_panel(con, zips: list[str]) -> pd.DataFrame:
    """analysis.zip_category_establishments for `zips`, bucketed into the four
    SEED groups plus a `total` row per (zip, year). Categories present in the ZBP
    crosswalk that aren't in CATEGORY_BUCKET raise loud -- silently dropping an
    unmapped category would understate "total"."""
    zip_list = ",".join(f"'{z}'" for z in zips)
    df = con.execute(f"""
        select year, zipcode as zip, category, sum(estab_total) as estab
        from analysis.zip_category_establishments
        where zipcode in ({zip_list})
        group by 1, 2, 3
    """).df()
    unmapped = set(df["category"]) - set(CATEGORY_BUCKET)
    if unmapped:
        raise RuntimeError(f"unmapped ZBP categories, extend CATEGORY_BUCKET: {unmapped}")
    df["bucket"] = df["category"].map(CATEGORY_BUCKET)
    bucketed = df.groupby(["zip", "year", "bucket"], as_index=False)["estab"].sum()
    wide = bucketed.pivot_table(index=["zip", "year"], columns="bucket",
                                 values="estab", fill_value=0).reset_index()
    for b in BUCKETS:
        if b not in wide.columns:
            wide[b] = 0
    wide["total"] = wide[BUCKETS].sum(axis=1)
    return wide[["zip", "year"] + BUCKETS + ["total"]]


def load_naics_business_mix(con, zip_: str, year_start: int, year_end: int,
                             top_n: int = 20) -> pd.DataFrame:
    """Top NAICS industries by establishment count for `zip_` across
    [year_start, year_end] -- the pre-2005 "what was here before" business-mix read
    from raw census_zbp/cbp (not the 16-category storefront taxonomy, which is
    retail/food/service-only and would miss the contractor/industrial mix)."""
    return con.execute("""
        select naics, any_value(naics_label) as naics_label, sum(estab) as estab
        from analysis.zip_establishments
        where zipcode = ? and year between ? and ?
        group by naics
        order by estab desc
        limit ?
    """, [zip_, year_start, year_end, top_n]).df()


# --------------------------------------------------------------- decennial / ACS

def load_decennial(zip_: str) -> pd.DataFrame:
    """2000/2010/2020 decennial rows for one ZCTA, one row per vintage."""
    frames = []
    for year in (2000, 2010, 2020):
        df = pd.read_parquet(INTERIM / "rq002" / "decennial" / f"decennial_zcta_{year}.parquet")
        row = df[df["zcta"] == zip_]
        if not row.empty:
            frames.append(row)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("decennial_year")


def load_acs_panel(zips: list[str], con=None) -> pd.DataFrame:
    """ACS 5yr ZCTA panel (2011-2024), filtered to `zips`. v1 (D141): reads
    `raw.acs_zcta_panel` from the live warehouse (peer 9f loaded it commit 262cac1,
    2026-09-22) when `con` is given -- same underlying data as the v0 parquet read,
    but warehouse-sourced is more reproducible (one lineage, not a session-local
    file). Falls back to the interim parquet (peer-built, RQ-001) if `con` is not
    supplied, so this function still works standalone."""
    if con is not None:
        zip_list = ",".join(f"'{z}'" for z in zips)
        df = con.execute(f"select * from raw.acs_zcta_panel where zcta in ({zip_list})").df()
        return df.sort_values(["zcta", "acs_year"]).reset_index(drop=True)
    df = pd.read_parquet(INTERIM / "rq001" / "acs_zcta" / "acs_zcta_panel.parquet")
    return df[df["zcta"].isin(zips)].sort_values(["zcta", "acs_year"]).reset_index(drop=True)


def load_zillow(zips: list[str], con=None) -> pd.DataFrame:
    """Zillow ZHVI (2000-)/ZORI (2015-) annual panel, filtered to `zips`. v1 (D141):
    reads `raw.zillow_zip_annual` from the live warehouse when `con` is given (same
    schema as the v0 parquet: zip/year/index/value_mean); falls back to the interim
    parquet otherwise."""
    if con is not None:
        zip_list = ",".join(f"'{z}'" for z in zips)
        df = con.execute(f"select * from raw.zillow_zip_annual where zip in ({zip_list})").df()
        return df.sort_values(["zip", "index", "year"]).reset_index(drop=True)
    df = pd.read_parquet(INTERIM / "rq001" / "zillow" / "zillow_nyc_annual.parquet")
    return df[df["zip"].isin(zips)].sort_values(["zip", "index", "year"]).reset_index(drop=True)


# ----------------------------------------------------------------- control ranking

def rank_control_candidates(con, candidates: list[str] = CANDIDATE_CONTROL_ZIPS,
                             treatment: str = TREATMENT_ZIP) -> pd.DataFrame:
    """Rank `candidates` by 1994-2010-window pre-trend distance to `treatment`.

    Features (all standardized, z-scored across candidates + treatment together so
    the treatment ZIP anchors the same scale): 1998 total storefront establishment
    level, 1998->2005 establishment growth rate, 2000 population, 2000 median gross
    rent, 2000 median household income, and 2000->2010 population growth. ZBP starts
    in 1998 (not 1994 -- D42's SIC/NAICS crosswalk decision, stated in DATA-AUDIT.md),
    so the establishment features start 4 years later than the SEED's nominal
    1994 window; this is the same gap RQ-001 already accepted, not re-litigated here.
    Euclidean distance in the standardized feature space, ascending = more similar;
    rank 1 is the pick."""
    zips = candidates + [treatment]
    zbp = load_zbp_category_panel(con, zips)
    totals = zbp.groupby(["zip", "year"])["total"].sum().unstack("year")

    d2000 = pd.concat([load_decennial(z) for z in zips], ignore_index=True)
    d2000 = d2000[d2000["decennial_year"] == 2000].set_index("zcta")
    d2010 = pd.concat([load_decennial(z) for z in zips], ignore_index=True)
    d2010 = d2010[d2010["decennial_year"] == 2010].set_index("zcta")

    rows = []
    for z in zips:
        e1998 = totals.loc[z, 1998] if z in totals.index and 1998 in totals.columns else np.nan
        e2005 = totals.loc[z, 2005] if z in totals.index and 2005 in totals.columns else np.nan
        growth = (e2005 - e1998) / e1998 if e1998 not in (0, np.nan) and pd.notna(e1998) else np.nan
        pop2000 = d2000.loc[z, "population"] if z in d2000.index else np.nan
        rent2000 = d2000.loc[z, "median_gross_rent"] if z in d2000.index else np.nan
        inc2000 = d2000.loc[z, "median_household_income"] if z in d2000.index else np.nan
        pop2010 = d2010.loc[z, "population"] if z in d2010.index else np.nan
        popgrowth = (pop2010 - pop2000) / pop2000 if pd.notna(pop2000) and pop2000 else np.nan
        rows.append(dict(zip=z, estab_1998=e1998, estab_2005=e2005,
                          estab_growth_98_05=growth, pop_2000=pop2000,
                          median_gross_rent_2000=rent2000,
                          median_hh_income_2000=inc2000,
                          pop_growth_00_10=popgrowth))
    feat = pd.DataFrame(rows).set_index("zip")
    feature_cols = ["estab_1998", "estab_growth_98_05", "pop_2000",
                     "median_gross_rent_2000", "median_hh_income_2000", "pop_growth_00_10"]
    # A candidate with fewer than 4 of the 6 features present (e.g. 11109, a ZIP
    # not carved out until years after 2000, so it has no 2000 decennial row and no
    # 1998 ZBP row) cannot be pre-trend-matched at all -- summing only its few
    # available (squared) z-score terms would silently score it as an artificially
    # *close* match (fewer non-null terms -> smaller sum -> smaller distance),
    # exactly backwards. Excluded outright and reported separately, not ranked.
    n_present = feat[feature_cols].notna().sum(axis=1)
    excluded = feat[n_present < 4].copy()
    excluded["excluded_reason"] = "insufficient 2000-era data (<4 of 6 pre-trend features present)"
    feat = feat[n_present >= 4]

    z = (feat[feature_cols] - feat[feature_cols].mean()) / feat[feature_cols].std(ddof=0)
    target = z.loc[treatment]
    dist = np.sqrt(((z - target) ** 2).sum(axis=1))
    out = feat.copy()
    out["pretrend_distance"] = dist
    out = out[out.index != treatment].sort_values("pretrend_distance")
    out["control_rank"] = range(1, len(out) + 1)
    out = out.reset_index()
    out.attrs["excluded"] = excluded.reset_index()
    return out


# --------------------------------------------------------- pioneers / followers

def assign_zcta_safe(df: pd.DataFrame, lon_col: str = "lon", lat_col: str = "lat",
                      vintage: int = 2020) -> pd.Series:
    """Point-in-polygon ZCTA assignment against the TIGER boundary parquet this
    session loaded, tolerant of the rare point that sits exactly on a shared ZCTA
    boundary seam (floating-point-coincident vertex shared by two adjacent
    polygons). `census_zcta_boundaries.assign_zcta_df` raises loud on ANY such
    conflict, which is the right default for that module but too strict for this
    notebook's purpose (a handful of geocoded POIs snapped to a seam should not
    abort the whole pioneer/follower build) -- this wrapper resolves a conflict by
    nearest-polygon-centroid instead of failing, and prints how many points needed
    it so the resolution is visible, not silent. Not a fix to
    census_zcta_boundaries.py itself (out of scope for this RQ -- see AGENTS
    brief), just a tolerant caller."""
    import geopandas as gpd
    import shapely
    from loci.sources.universal.census_zcta_boundaries import INTERIM_DIR as ZCTA_DIR

    gdf = gpd.read_parquet(ZCTA_DIR / f"zcta_{vintage}.parquet")
    tree = shapely.STRtree(gdf.geometry.values)
    codes = gdf["zcta"].reset_index(drop=True)
    pts = shapely.points(df[lon_col].to_numpy(), df[lat_col].to_numpy())
    point_idx, poly_idx = tree.query(pts, predicate="intersects")
    result = pd.Series([None] * len(df), index=df.index, dtype=object)
    if len(point_idx) == 0:
        return result
    matched = pd.DataFrame({"point_idx": point_idx, "zcta": codes.iloc[poly_idx].to_numpy()})
    grouped = matched.groupby("point_idx")["zcta"].agg(lambda s: sorted(set(s)))
    n_conflict = 0
    for pidx, zlist in grouped.items():
        if len(zlist) == 1:
            result.iloc[pidx] = zlist[0]
        else:
            n_conflict += 1
            pt = pts[pidx]
            cent_dist = [(z, gdf.geometry.iloc[codes[codes == z].index[0]].centroid.distance(pt))
                         for z in zlist]
            result.iloc[pidx] = min(cent_dist, key=lambda t: t[1])[0]
    if n_conflict:
        print(f"[rq002] {n_conflict}/{len(df)} point(s) sat on a ZCTA boundary seam "
              f"(vintage {vintage}); resolved by nearest-polygon-centroid tie-break")
    return result


def load_poi_first_seen_for_zips(con, zips: list[str], vintage: int = 2020) -> pd.DataFrame:
    """analysis.poi_first_seen assigned to ZCTA via assign_zcta_safe (point-in-polygon
    against the TIGER boundary this session loaded), filtered to `zips`. Bounding-box
    pre-filter (North Brooklyn / western Queens envelope) before the spatial join --
    poi_first_seen is 219,458 rows citywide and the join is O(n); no need to run it
    against Staten Island points."""
    df = con.execute("""
        select location_key, category, name_key, display_name, lon, lat, borough,
               first_seen_kind, first_seen_month, first_seen_on, is_left_censored,
               last_seen_month, is_closed, closed_on
        from analysis.poi_first_seen
        where lon between -74.05 and -73.85 and lat between 40.68 and 40.80
    """).df()
    df["zcta"] = assign_zcta_safe(df, "lon", "lat", vintage=vintage)
    return df[df["zcta"].isin(zips)].reset_index(drop=True)


def load_licence_interval_for_zips(con, zips: list[str], vintage: int = 2020) -> pd.DataFrame:
    """analysis.licence_interval (SLA liquor licenses, BBL-matched) assigned to ZCTA
    the same way as POI first-seen. licence_creation_date is the first-seen proxy."""
    df = con.execute("""
        select licence_number, business_name, address, lon, lat, borough,
               loci_category, licence_creation_date, expiration_date, status,
               status_date
        from analysis.licence_interval
        where lon between -74.05 and -73.85 and lat between 40.68 and 40.80
    """).df()
    df["zcta"] = assign_zcta_safe(df, "lon", "lat", vintage=vintage)
    return df[df["zcta"].isin(zips)].reset_index(drop=True)


def classify_pioneer_follower(first_seen_dates: pd.Series, anchor_date: pd.Timestamp) -> pd.Series:
    """pioneer if first-seen precedes the anchor, else follower. NaT -> None (can't
    classify without a date)."""
    return first_seen_dates.apply(
        lambda d: None if pd.isna(d) else ("pioneer" if d < anchor_date else "follower"))


# ------------------------------------------------------------ commercial rent proxy

#: Building classes treated as ground-floor-retail-bearing for the DOF proxy: tax
#: class 4 commercial, K*/S*/O* building classes (store/mixed store-and-X/office),
#: kept broad on purpose since the FY2010-2011 partitions don't reliably carry a
#: separate retail-sqft field to narrow further.
COMMERCIAL_BLDG_CLASS_PREFIXES = ("K", "S", "O")


def load_dof_commercial_proxy(zips: list[str] | None = None) -> pd.DataFrame:
    """DOF assessment-roll partitions actually landed on disk (PARTIAL -- see
    DATA-AUDIT.md; FY2012+ was still downloading in the background as of this
    session, so only whatever fy=* directories exist under
    data/interim/rq002/dof_assessment/ are read), filtered to commercial/mixed-use
    lots (building_class starting K/S/O -- store, mixed store-and-X, office; a
    ground-floor-retail-bearing proxy, not a precise retail-only filter) and,
    if `zips` given, to those ZIPs via the loader's own `zip_code` column (already
    present and populated for ~97%+ of rows in the partitions probed -- no
    lat/lon spatial join needed here, unlike the POI tables)."""
    root = INTERIM / "rq002" / "dof_assessment"
    fy_dirs = sorted(p for p in root.glob("fy=*") if p.is_dir())
    frames = []
    for fy_dir in fy_dirs:
        fy = int(fy_dir.name.split("=")[1])
        for f in fy_dir.glob("*.parquet"):
            df = pd.read_parquet(f)
            df["fiscal_year"] = fy
            df["source_file"] = f.name
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined[combined["building_class"].str.startswith(
        COMMERCIAL_BLDG_CLASS_PREFIXES, na=False)]
    if zips is not None:
        combined = combined[combined["zip_code"].isin(zips)]
    combined["value_per_sqft"] = np.where(
        combined["gross_sqft"].fillna(0) > 0,
        combined["market_value_total"] / combined["gross_sqft"], np.nan)
    return combined.reset_index(drop=True)


# ------------------------------------------------------------- pioneer/follower II

def resolve_first_seen_date(df: pd.DataFrame) -> pd.Series:
    """One first-seen Timestamp per row: `first_seen_on` (day precision) where
    present, else `first_seen_month` (a "YYYY-MM" string) parsed to that month's
    first day. Both null -> NaT (can't classify, not defaulted to some anchor)."""
    on = pd.to_datetime(df["first_seen_on"], errors="coerce")
    month = pd.to_datetime(df["first_seen_month"] + "-01", format="%Y-%m-%d", errors="coerce")
    return on.fillna(month)


# ------------------------------------------------------------------------- DiD

def diff_in_diff(panel: pd.DataFrame, outcome_col: str, anchor_year: int,
                  treatment: str = TREATMENT_ZIP, control: str | None = None) -> dict:
    """Simple 2x2 difference-in-differences: mean(outcome) pre vs. post `anchor_year`
    (post = year >= anchor_year), treatment vs. `control`. `panel` must have columns
    zip, year, outcome_col. Returns the four cell means plus each side's own
    before/after change and the DiD estimate (treatment change minus control
    change) -- descriptive arithmetic; the causal label is a judgment made in the
    notebook's Method/Results text based on the pre-trend check below, not by this
    function."""
    control = control or panel["zip"].unique()[panel["zip"].unique() != treatment][0]
    pre = panel[panel["year"] < anchor_year]
    post = panel[panel["year"] >= anchor_year]
    pre_m = pre.groupby("zip")[outcome_col].mean()
    post_m = post.groupby("zip")[outcome_col].mean()
    # .get() returns None (not NaN) when a zip has ZERO rows in that half -- e.g. a
    # Zillow series that starts later for the control ZIP than for the treatment
    # one. Normalize to NaN so arithmetic below produces NaN, not a TypeError, and
    # add `data_ok` so a caller can report "no data" instead of a wrong number.
    t_pre = pre_m.get(treatment); t_post = post_m.get(treatment)
    c_pre = pre_m.get(control); c_post = post_m.get(control)
    t_pre, t_post, c_pre, c_post = (np.nan if v is None else v for v in (t_pre, t_post, c_pre, c_post))
    data_ok = all(pd.notna(v) for v in (t_pre, t_post, c_pre, c_post))
    t_diff = t_post - t_pre
    c_diff = c_post - c_pre
    return {
        "outcome": outcome_col, "anchor_year": anchor_year,
        "treatment": treatment, "control": control, "data_ok": data_ok,
        "treatment_pre": t_pre, "treatment_post": t_post,
        "treatment_pct_change": (t_diff / t_pre * 100) if t_pre else np.nan,
        "control_pre": c_pre, "control_post": c_post,
        "control_pct_change": (c_diff / c_pre * 100) if c_pre else np.nan,
        "treatment_diff": t_diff, "control_diff": c_diff,
        "did_estimate": t_diff - c_diff,
    }


def pretrend_check(panel: pd.DataFrame, outcome_col: str, anchor_year: int,
                    treatment: str = TREATMENT_ZIP, control: str | None = None) -> dict:
    """Parallel-trends diagnostic: OLS slope of `outcome_col` on year for
    treatment and control, restricted to years strictly before `anchor_year`.
    Close slopes (same sign, similar magnitude) support the DiD's identifying
    assumption; divergent pre-trends mean the DiD estimate should be labeled
    descriptive, not causal -- that labeling decision is made in the notebook
    text, this function only reports the numbers."""
    control = control or panel["zip"].unique()[panel["zip"].unique() != treatment][0]
    pre = panel[panel["year"] < anchor_year].dropna(subset=[outcome_col])
    out = {}
    for z, label in ((treatment, "treatment"), (control, "control")):
        sub = pre[pre["zip"] == z].sort_values("year")
        if len(sub) < 3:
            out[f"{label}_slope"] = np.nan
            out[f"{label}_n_years"] = len(sub)
            continue
        slope, intercept = np.polyfit(sub["year"], sub[outcome_col], 1)
        out[f"{label}_slope"] = slope
        out[f"{label}_n_years"] = len(sub)
    if pd.notna(out.get("treatment_slope")) and pd.notna(out.get("control_slope")):
        out["same_sign"] = np.sign(out["treatment_slope"]) == np.sign(out["control_slope"])
        denom = max(abs(out["treatment_slope"]), abs(out["control_slope"]), 1e-9)
        out["slope_gap_ratio"] = abs(out["treatment_slope"] - out["control_slope"]) / denom
    else:
        out["same_sign"] = None
        out["slope_gap_ratio"] = np.nan
    return out


# =====================================================================================
# v1 (D141 fixes A-K) -- everything below is new for the notebook.ipynb rework. Kept
# in this module (not the notebook) per the same discipline stated in the module
# docstring: modeling CHOICES are stated/justified in the notebook, mechanical data
# assembly lives here. v0's functions above are kept as-is (still used for the "before
# the fix" comparison in Section 1/3, and because several are still correct: the
# tower schema read, the DiD/pre-trend estimator, resolve_first_seen_date, etc).
# =====================================================================================

SUPPLY_HASH = "c796e59da990"  # live POI supply hash, per peer 6d (D139), stamped 2026-09-22

# --------------------------------------------------------- A/B. NAICS-2012 crosswalk
#
# FIX A (the "headline killer"): src/loci/zbp_naics.yaml -- the SHARED crosswalk this
# module must not edit -- maps restaurants/cafes only to the NAICS-2012+ codes
# (722511/722513/722515). NAICS revised the food-service subsector in 2012
# (722110/722211/722212/722213 -> 722511/722513/722514/722515; verified directly
# against analysis.zip_establishments for 11222: the OLD codes run 1998-2011 and the
# NEW codes pick up in 2012 with no gap or level jump in the raw establishment counts
# -- e.g. 722110+722211+722213 = 50+43+9 = 102 in 2011 vs. 722511+722513+722515 =
# 53+45+11 = 109 in 2012). So `analysis.zip_category_establishments`'s `restaurant`/
# `cafe_bakery` buckets (built through zbp_naics.yaml) silently drop to near-zero for
# 1998-2011 -- not because Greenpoint had no restaurants, but because the crosswalk
# only recognizes the codes NAICS introduced in 2012. This crosswalk is built HERE,
# reading raw `analysis.zip_establishments` NAICS codes directly, covering both eras,
# so food_drink has a continuous, correct 1998-2023 series. `bar` (722410) did not
# change in the 2012 revision and is unaffected either way.
#
# FIX B (double-count): `analysis.zip_establishments` is keyed by (year, zipcode,
# naics, emp_size_band) where emp_size_band includes BOTH a `"All establishments"`
# total row AND non-overlapping size-band sub-rows (`"...less than 5 employees"`,
# `"...5 to 9 employees"`, etc. -- verified: 10 distinct band values, 1 total + 9
# sub-bands). Every query below filters to `emp_size_band = 'All establishments'`
# ONLY -- summing the total row plus its own sub-bands would double (in fact ~2x)
# the true establishment count.
FOOD_DRINK_NAICS_XWALK: dict[str, str] = {
    # -- pre-2012 (NAICS 2007 and earlier) --
    "722110": "restaurant",       # Full-service restaurants
    "722211": "restaurant",       # Limited-service restaurants
    "722212": "restaurant",       # Cafeterias, grill buffets, buffets (rare in 11222; kept for completeness)
    "722213": "cafe_bakery",      # Snack & nonalcoholic beverage bars -- same real-world category NAICS
                                   # later renamed 722515 and zbp_naics.yaml already buckets as cafe_bakery.
    # -- post-2012 (NAICS 2012/2017) --
    "722511": "restaurant",       # Full-service restaurants
    "722513": "restaurant",       # Limited-service restaurants
    "722514": "restaurant",       # Cafeterias, grill buffets, buffets
    "722515": "cafe_bakery",      # Snack and nonalcoholic beverage bars
    # -- stable across both eras (code did not change in the 2012 revision) --
    "722410": "bar",              # Drinking places (alcoholic beverages)
    "311811": "cafe_bakery",      # Retail bakeries (manufacturing-sector code; zbp_naics.yaml's own choice, kept
                                   # for consistency with the Loci-categories total below).
}
FOOD_DRINK_BUCKETS = ["restaurant", "cafe_bakery", "bar"]

#: NAICS codes deliberately EXCLUDED from the food_drink crosswalk above, stated so the
#: exclusion is a decision, not an oversight: 722310 (food service contractors) and
#: 722320 (caterers) are contract/off-site food service, not a walk-in storefront;
#: 722330 (mobile food) has no fixed storefront address; 424420/424460 (frozen food /
#: seafood merchant wholesalers) are wholesale, not retail.
FOOD_DRINK_EXCLUDED_NAICS = ["722310", "722320", "722330", "424420", "424460"]


def load_naics_raw(con, zips: list[str], naics_codes: list[str] | None = None,
                    naics_prefixes: list[str] | None = None) -> pd.DataFrame:
    """Raw (year, zip, naics, estab) rows from analysis.zip_establishments, filtered
    to `emp_size_band = 'All establishments'` ONLY (Fix B -- never sum this against
    the sub-band rows in the same table). `naics_codes` matches exact 6-digit codes;
    `naics_prefixes` matches by LIKE 'prefix%' (for widened-scope groups specified as
    a NAICS subsector rather than an enumerated code list). At least one must be given."""
    if not naics_codes and not naics_prefixes:
        raise ValueError("give naics_codes and/or naics_prefixes")
    zip_list = ",".join(f"'{z}'" for z in zips)
    clauses = []
    if naics_codes:
        code_list = ",".join(f"'{c}'" for c in naics_codes)
        clauses.append(f"naics in ({code_list})")
    if naics_prefixes:
        clauses.extend(f"naics like '{p}%'" for p in naics_prefixes)
    where_naics = " or ".join(clauses)
    return con.execute(f"""
        select year, zipcode as zip, naics, any_value(naics_label) as naics_label, sum(estab) as estab
        from analysis.zip_establishments
        where zipcode in ({zip_list}) and emp_size_band = 'All establishments'
              and ({where_naics})
        group by year, zipcode, naics
        order by year, zipcode, naics
    """).df()


def load_food_drink_corrected(con, zips: list[str]) -> pd.DataFrame:
    """Corrected food_drink series (Fix A+B): restaurant/cafe_bakery/bar establishment
    counts per (zip, year), 1998-2023, built from FOOD_DRINK_NAICS_XWALK against raw
    analysis.zip_establishments (emp_size_band='All establishments' only). Returns a
    wide frame: zip, year, restaurant, cafe_bakery, bar, food_drink_corrected (sum of
    the three)."""
    raw = load_naics_raw(con, zips, naics_codes=list(FOOD_DRINK_NAICS_XWALK))
    raw["bucket"] = raw["naics"].map(FOOD_DRINK_NAICS_XWALK)
    wide = (raw.groupby(["zip", "year", "bucket"])["estab"].sum()
            .unstack("bucket").fillna(0))
    for b in FOOD_DRINK_BUCKETS:
        if b not in wide.columns:
            wide[b] = 0.0
    wide = wide[FOOD_DRINK_BUCKETS].reset_index()
    wide["food_drink_corrected"] = wide[FOOD_DRINK_BUCKETS].sum(axis=1)
    return wide.sort_values(["zip", "year"]).reset_index(drop=True)


def naics_2012_discontinuity_check(corrected: pd.DataFrame, broken: pd.DataFrame,
                                    zip_: str = TREATMENT_ZIP) -> pd.DataFrame:
    """Year-over-year % change in food_drink around 2012, for the CORRECTED series
    (this module) vs. the BROKEN one (analysis.zip_category_establishments's own
    food_drink bucket, i.e. what v0 used uncorrected) -- the fix is verified if the
    corrected series shows an ordinary year-over-year change at 2011->2012 while the
    broken one shows a cliff (near-total drop then reappearance)."""
    c = corrected[corrected["zip"] == zip_].set_index("year")["food_drink_corrected"]
    b = broken[broken["zip"] == zip_].set_index("year")["food_drink"]
    years = sorted(set(c.index) | set(b.index))
    out = pd.DataFrame({"year": years})
    out["corrected"] = out["year"].map(c)
    out["corrected_pct_chg"] = out["corrected"].pct_change() * 100
    out["broken_uncorrected"] = out["year"].map(b)
    out["broken_pct_chg"] = out["broken_uncorrected"].pct_change() * 100
    return out


def plot_naics_discontinuity(check_df: pd.DataFrame, zip_: str = TREATMENT_ZIP):
    """Fix A's required plot: corrected vs. broken food_drink series with vertical
    reference lines at 2003 (early rezoning run-up)/2008 (financial crisis)/2012 (the
    NAICS revision year the bug lives at)/2017 (last pre-tower-delivery year), so a
    reader can see directly whether the 2012 line coincides with a level break."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(check_df["year"], check_df["broken_uncorrected"], "o--", color="firebrick",
            label="broken (zip_category_establishments, v0)")
    ax.plot(check_df["year"], check_df["corrected"], "o-", color="steelblue",
            label="corrected (this module, NAICS both eras)")
    for yr in (2003, 2008, 2012, 2017):
        ax.axvline(yr, color="grey", linestyle=":", linewidth=1)
    ax.set_title(f"food_drink establishments, {zip_}: NAICS-2012 crosswalk fix")
    ax.set_xlabel("year"); ax.set_ylabel("establishments")
    ax.legend()
    fig.tight_layout()
    return fig


# ------------------------------------------------------------- C. widened storefront

#: NAICS groups ADDED beyond Loci's 16/17-category taxonomy (Fix C), each mapped to a
#: named group, none overlapping a code already used by zbp_naics.yaml's own 17
#: categories (checked against zbp_naics.yaml's contents 2026-09-22) -- so
#: "Loci categories total" + "widened extras total" below is additive with no
#: double-count, and the two are also reported as separate lines per the brief.
WIDENED_NAICS_GROUPS: dict[str, list[str]] = {
    "specialty_food": ["445210", "445220", "445230", "445291", "445292", "445299", "445310"],
    #                    meat mkts  fish/seafood  fruit/veg  baked gds  confectionery  other  beer/wine/liquor (4453xx)
    "apparel": ["448110", "448120", "448130", "448140", "448150", "448190", "448210"],
    #            men's     women's   kids'      family     (unlabeled) other clothing  shoe stores
    "jewelry": ["448310", "448320"],   # jewelry stores; luggage & leather goods (NAICS pairs these, 4483)
    "furniture_home": ["442110", "442210", "442291", "442299"],
    #                   furniture   floor covering  window treatment  other home furnishings
    "general_merchandise": ["452319", "452990"],
    "personal_services_other": ["812210", "812191", "812910", "812921", "812922", "812990"],
    #                            funeral   diet/weight  pet care   photofinishing x2   other personal
    # Deliberately excluded from personal_services_other: 812331/812332 (linen supply /
    # industrial launderers -- B2B, not a walk-in storefront) and 812930 (parking lots/
    # garages -- a ground-floor use, but not retail or a personal service in the
    # ordinary sense QUESTION.md's "shops/services" definition means).
}
WIDENED_GROUP_NAMES = list(WIDENED_NAICS_GROUPS)


def load_widened_storefront_panel(con, zips: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fix C: the six widened-scope groups above, per (zip, year), PLUS a thinness
    flag. Returns (wide_panel, thin_flags) -- wide_panel has zip, year, one column per
    group, and `widened_extra_total` (sum of the six); thin_flags lists every
    (zip, group, year>=2017) cell with <3 establishments, called out because ZBP/CBP
    suppress small cells starting around 2017 (the underlying source ROW is simply
    absent below its confidentiality threshold, not published as an explicit 0) -- a
    disappearance here should be read as "missing/uncertain", not "the category went
    to zero". This function does NOT fill those gaps with 0 for a whole group, since
    a widened group sums several codes and total absence of a whole group in an
    active ZIP is implausible; instead it prints the specific thin narrow-NAICS rows
    as a caveat list for the notebook to surface."""
    all_codes = [c for codes in WIDENED_NAICS_GROUPS.values() for c in codes]
    raw = load_naics_raw(con, zips, naics_codes=all_codes)
    code_to_group = {c: g for g, codes in WIDENED_NAICS_GROUPS.items() for c in codes}
    raw["group"] = raw["naics"].map(code_to_group)
    wide = (raw.groupby(["zip", "year", "group"])["estab"].sum()
            .unstack("group").fillna(0))
    for g in WIDENED_GROUP_NAMES:
        if g not in wide.columns:
            wide[g] = 0.0
    wide = wide[WIDENED_GROUP_NAMES].reset_index()
    wide["widened_extra_total"] = wide[WIDENED_GROUP_NAMES].sum(axis=1)

    thin = raw[(raw["year"] >= 2017) & (raw["estab"] < 3)].copy()
    thin["group"] = thin["naics"].map(code_to_group)
    thin = thin.sort_values(["zip", "group", "year"])
    return wide.sort_values(["zip", "year"]).reset_index(drop=True), thin.reset_index(drop=True)


def build_category_totals(zbp_panel_original: pd.DataFrame, food_drink_corrected: pd.DataFrame,
                           widened: pd.DataFrame) -> pd.DataFrame:
    """Assembles the two headline totals Fix C asks be reported side by side:
    `loci_categories_total` = grocery+services+shops (unaffected by the NAICS-2012
    break; unchanged from zbp_panel_original) + the CORRECTED food_drink (replacing
    zbp_panel_original's own broken food_drink column), and
    `all_storefront_total` = loci_categories_total + widened_extra_total."""
    base = zbp_panel_original.rename(columns={"food_drink": "food_drink_broken_v0"})
    merged = (base.merge(food_drink_corrected[["zip", "year", "food_drink_corrected"]],
                          on=["zip", "year"], how="left")
                   .merge(widened[["zip", "year", "widened_extra_total"]],
                          on=["zip", "year"], how="left"))
    merged["loci_categories_total"] = (merged["grocery"] + merged["services"]
                                        + merged["shops"] + merged["food_drink_corrected"].fillna(0))
    merged["all_storefront_total"] = merged["loci_categories_total"] + merged["widened_extra_total"].fillna(0)
    return merged


# --------------------------------------------------------- D. control-ZIP screening

PRIMARY_CONTROL = "11385"    # Ridgewood
SECONDARY_CONTROL = "11105"  # Ditmars
SYNTHETIC_DONOR_POOL = ["11385", "11105", "11104", "11103"]
DROPPED_CONTROL_ZIPS = {"11102": "Hallets Point towers -- owner ruling, dropped outright "
                                  "(dev_pipeline has no Queens coverage at all -- see below -- "
                                  "so this cannot be confirmed/screened from warehouse data; "
                                  "dropped on the strength of the ruling, not the screen)."}
CONTROL_SCREEN_WINDOW = (2005, 2023)  # post-rezoning through the latest panel year
CONTROL_SCREEN_UNIT_THRESHOLD = 100


def screen_control_candidates_for_towers(con, candidates: list[str] = CANDIDATE_CONTROL_ZIPS,
                                          unit_threshold: int = CONTROL_SCREEN_UNIT_THRESHOLD,
                                          window: tuple[int, int] = CONTROL_SCREEN_WINDOW,
                                          vintage: int = 2020) -> pd.DataFrame:
    """Fix D: exclude any control candidate that itself got >=1 residential New
    Building job at `unit_threshold`+ units, completed OR permitted, with a filing/
    completion date inside `window` -- assigned to a ZIP by point-in-polygon on the
    job's centroid (assign_zcta_safe), NOT by dev_pipeline's own `neighborhood` label
    (that label is an NTA name, doesn't cover Queens, and Section on tower selection
    shows it disagrees with the ZIP boundary by dozens of jobs even for Greenpoint
    itself).

    KNOWN GAP, stated not hidden: `analysis.dev_pipeline` covers Manhattan and
    Brooklyn ONLY (verified: `select distinct borough` returns exactly {MN, BK}, zero
    Queens rows) -- so every western-Queens candidate (11101/11102/11103/11104/11105/
    11106/11109) is UNSCREENABLE from this source; the function reports them as
    `screened: False, reason: 'no dev_pipeline coverage (Queens)'` rather than
    silently passing them as clean. The Brooklyn candidates (11206/11221/11237) DO
    get a real screen and all three fail it (each has >=1 qualifying job) -- this is
    itself informative: it is why none of them is used as control below."""
    import geopandas as gpd
    import shapely
    from loci.sources.universal.census_zcta_boundaries import INTERIM_DIR as ZCTA_DIR

    df = con.execute("""
        select job_number, bbl, net_units, stage, date_filed, date_permitted, date_complete, borough
        from analysis.dev_pipeline
        where job_type = 'New Building' and net_units >= ? and geom is not null
    """, [unit_threshold]).df()
    # date_permitted -- for 'permitted' stage; date_filed -- fallback if date_permitted
    # is null but the job is at least permitted; date_complete -- for 'complete' stage.
    geoms = con.execute("""
        select job_number, ST_X(ST_Centroid(geom)) as lon, ST_Y(ST_Centroid(geom)) as lat
        from analysis.dev_pipeline where job_type='New Building' and net_units >= ? and geom is not null
    """, [unit_threshold]).df()
    df = df.merge(geoms, on="job_number")
    df["zcta"] = assign_zcta_safe(df, "lon", "lat", vintage=vintage)

    def in_window(row):
        for col in ("date_complete", "date_permitted", "date_filed"):
            d = row[col]
            if pd.notna(d) and window[0] <= d.year <= window[1] and row["stage"] in ("complete", "permitted", "partially_complete"):
                return True
        return False
    df["in_window"] = df.apply(in_window, axis=1)
    qualifying = df[df["in_window"]]

    rows = []
    for z in candidates:
        has_qc_coverage = z not in {"11101", "11102", "11103", "11104", "11105", "11106", "11109"}
        z_jobs = qualifying[qualifying["zcta"] == z]
        rows.append({
            "zip": z,
            "screened": has_qc_coverage,
            "n_qualifying_jobs": len(z_jobs) if has_qc_coverage else None,
            "max_net_units": int(z_jobs["net_units"].max()) if len(z_jobs) else None,
            "excluded": bool(len(z_jobs)) if has_qc_coverage else None,
            "reason": ("n/a" if not has_qc_coverage
                       else (f"{len(z_jobs)} qualifying New Building job(s) >= {unit_threshold} units"
                             if len(z_jobs) else "clean -- no qualifying job in dev_pipeline"))
        })
        if not has_qc_coverage:
            rows[-1]["reason"] = "no dev_pipeline coverage (Queens) -- cannot be screened from this source"
    return pd.DataFrame(rows)


def fit_synthetic_control(panel: pd.DataFrame, outcome_col: str, donor_zips: list[str],
                           treatment: str, fit_years: list[int], validate_year: int) -> dict:
    """Fix D: nonnegative synthetic-control weights (sum to 1) over `donor_zips`,
    fit to match `treatment`'s log(outcome) across `fit_years` (2012-2016), validated
    OUT of the fit window on `validate_year` (2017) -- selection and validation on
    different years, per the brief. Minimizes sum of squared log-differences with
    scipy SLSQP under weights>=0, sum(weights)=1 (the standard Abadie et al.
    constraint set); with only 4 donors and a 5-year fit window this is a small,
    over-identified least-squares problem, not a black box."""
    from scipy.optimize import minimize

    wide = panel[panel["zip"].isin(donor_zips + [treatment])].pivot_table(
        index="year", columns="zip", values=outcome_col)
    fit = wide.loc[fit_years].dropna(axis=1, how="any")
    usable_donors = [d for d in donor_zips if d in fit.columns]
    if treatment not in fit.columns or not usable_donors:
        return {"ok": False, "reason": "insufficient data in fit window"}
    y = np.log(fit[treatment].to_numpy())
    X = np.log(fit[usable_donors].to_numpy())  # (n_fit_years, n_donors)

    n = len(usable_donors)
    def loss(w):
        return float(np.sum((y - X @ w) ** 2))
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = [(0.0, 1.0)] * n
    w0 = np.full(n, 1.0 / n)
    res = minimize(loss, w0, method="SLSQP", bounds=bounds, constraints=cons)
    weights = dict(zip(usable_donors, res.x))

    # Out-of-sample validation on validate_year (NOT in fit_years).
    val_ok = validate_year in wide.index and treatment in wide.columns
    val_row = {"validate_year": validate_year, "ok": val_ok}
    if val_ok:
        donors_val = wide.loc[validate_year, usable_donors]
        if donors_val.notna().all():
            synth_val = float(np.exp(sum(weights[d] * np.log(donors_val[d]) for d in usable_donors)))
            actual_val = float(wide.loc[validate_year, treatment])
            val_row.update({"synthetic": synth_val, "actual": actual_val,
                             "pct_error": (synth_val - actual_val) / actual_val * 100})
        else:
            val_row["ok"] = False

    full_years = sorted(wide.dropna(subset=usable_donors, how="any").index)
    synthetic_series = pd.Series(
        {yr: float(np.exp(sum(weights[d] * np.log(wide.loc[yr, d]) for d in usable_donors)))
         for yr in full_years if wide.loc[yr, usable_donors].notna().all()})

    return {"ok": True, "donors": usable_donors, "weights": weights,
            "fit_years": fit_years, "fit_rmse_log": float(np.sqrt(res.fun / len(fit_years))),
            "validation": val_row, "synthetic_series": synthetic_series}


# ------------------------------------------------------------------- F. towers, v1

#: The urban-planner's reconciliation list (owner-supplied, 2026-09-22), BBL-keyed
#: where a BBL is known, else block-keyed. Used only to cross-check
#: `load_tower_timeline_by_zip`'s output below -- never to override the warehouse
#: read.
KNOWN_TOWER_RECONCILIATION = [
    {"name": "One Blue Slip", "bbl": "3024727503", "known_units": 359, "known_date": "2018-08"},
    {"name": "The Greenpoint / 21 India St", "block": "302530", "known_units": 382, "known_date": "2018"},
    {"name": "Two Blue Slip", "bbl": "3024720050", "known_units": 421, "known_date": "2020"},
    {"name": "Eagle+West", "bbl_prefix": "3024720021", "known_units": 745, "known_date": "2022-12"},
    {"name": "Tower 77", "bbl": "3025700040", "known_units": (520, 554), "known_date": "2023"},
    {"name": "The Riverie", "bbl": "3025380001", "known_units": 834, "known_date": "2025-26"},
    {"name": "Greenpoint Landing next phase", "bbl_prefix": "3025020001", "known_units": None, "known_date": "pipeline"},
    {"name": "TF Cornerstone 2 Noble St", "bbl_prefix": "3025670001", "known_units": 1060, "known_date": "pre-application"},
]


def load_tower_timeline_by_zip(con, zip_: str = TREATMENT_ZIP, vintage: int = 2020) -> pd.DataFrame:
    """Fix F (selection): every New Building job assigned to `zip_` by point-in-
    polygon on the job's centroid (assign_zcta_safe against the TIGER ZCTA boundary),
    NOT by dev_pipeline's own `neighborhood` label. Verified against
    neighborhood='Greenpoint': the two selections disagree by dozens of jobs (40 in
    zcta=11222 but not neighborhood='Greenpoint'; 4 the other way -- NTA boundaries
    are not ZIP boundaries), so this is a real, not cosmetic, fix.

    Fix F (dating): `date_complete`/`co_type` in `analysis.dev_pipeline` store only
    ONE occupancy date per job row -- whichever CO status is CURRENT as of ingestion,
    not a full CO history. For a job still at `co_type='temporary'`, `date_complete`
    IS the first (and so far only) TCO date -- exactly what Fix F wants. For a job
    already at `co_type='final'`, the true FIRST TCO date is not recoverable from
    this table (only the LATER final-CO date is stored); `date_complete` for those
    rows is therefore a plausible-but-late stand-in for first occupancy, flagged via
    `date_is_final_co_not_first_tco`, not silently treated as if it were the TCO
    date. This is a genuine data-model limitation (TICKET NEEDED: dev_pipeline would
    need to retain the TCO date even after a final CO supersedes it), stated here
    rather than worked around."""
    df = con.execute("""
        select job_number, bbl, net_units, units_init, units_prop, units_complete,
               stage, dcp_status, date_filed, date_permitted, date_complete, co_type,
               activity_status, neighborhood, borough,
               ST_X(ST_Centroid(geom)) as lon, ST_Y(ST_Centroid(geom)) as lat
        from analysis.dev_pipeline
        where job_type = 'New Building' and geom is not null
    """).df()
    df["zcta"] = assign_zcta_safe(df, "lon", "lat", vintage=vintage)
    out = df[df["zcta"] == zip_].copy()
    out["tower_flag"] = out["net_units"] >= TOWER_UNIT_THRESHOLD
    out["pipeline_flag"] = out["stage"].isin(["filed", "permitted"])
    out["withdrawn_flag"] = out["stage"] == "withdrawn"
    out["date_is_final_co_not_first_tco"] = out["co_type"] == "final"
    out["complete_year"] = pd.to_datetime(out["date_complete"]).dt.year
    out["filed_year"] = pd.to_datetime(out["date_filed"]).dt.year
    return out.sort_values("date_filed").reset_index(drop=True)


def tower_units_per_year(tower_df: pd.DataFrame) -> pd.DataFrame:
    """Same shape as v0's new_units_per_year, computed on `load_tower_timeline_by_zip`'s
    ZIP-selected frame instead of the neighborhood-selected one."""
    complete = tower_df.dropna(subset=["complete_year"]).copy()
    complete["complete_year"] = complete["complete_year"].astype(int)
    all_units = complete.groupby("complete_year")["units_complete"].sum(min_count=1)
    tower_units = (complete[complete["tower_flag"]]
                   .groupby("complete_year")["units_complete"].sum(min_count=1))
    out = pd.DataFrame({"units_complete_all": all_units,
                         "units_complete_towers_only": tower_units}).fillna(0).astype(int)
    out.index.name = "year"
    return out.reset_index()


def anchor_year_sensitivity(units_series: pd.DataFrame, thresholds: list[int]) -> pd.DataFrame:
    """Fix F: rerun the 'first big TCO year' rule at each of `thresholds` (250/500/
    1,000 units delivered in a single year) and report the resulting year for each --
    the sensitivity check the brief asks for."""
    rows = []
    for t in thresholds:
        hit = units_series.loc[units_series["units_complete_all"] > t, "year"]
        rows.append({"threshold_units": t, "first_year_exceeding": int(hit.min()) if len(hit) else None})
    return pd.DataFrame(rows)


def reconcile_known_towers(tower_df: pd.DataFrame) -> pd.DataFrame:
    """Cross-check KNOWN_TOWER_RECONCILIATION against `tower_df` (from
    load_tower_timeline_by_zip). Reports what the warehouse shows for each named
    tower's BBL/block, so a units or date mismatch (e.g. the "589 vs 382" the owner
    flagged for 21 India St) is visible in the output, not silently resolved.

    A withdrawn filing (an earlier, abandoned proposal for the SAME lot -- e.g. The
    Riverie's BBL carries two withdrawn 2018 filings, 569u and 202u, alongside the
    live 834u job that was actually built) is EXCLUDED from `warehouse_net_units_sum`
    and from the first-TCO date -- summing it in would double/triple-count the same
    physical lot's design history, not add real delivered units. Withdrawn jobs at
    the matched BBL(s) are still reported (count and their units) so the exclusion is
    visible, not silent."""
    rows = []
    for t in KNOWN_TOWER_RECONCILIATION:
        if "bbl" in t:
            match_all = tower_df[tower_df["bbl"] == t["bbl"]]
        else:
            key = t.get("bbl_prefix", t.get("block", ""))
            match_all = tower_df[tower_df["bbl"].str.startswith(key, na=False)]
        match = match_all[match_all["stage"] != "withdrawn"]
        withdrawn = match_all[match_all["stage"] == "withdrawn"]
        rows.append({
            "name": t["name"], "known_units": t["known_units"], "known_date": t["known_date"],
            "n_jobs_matched": len(match),
            "n_withdrawn_excluded": len(withdrawn),
            "withdrawn_units_excluded": int(withdrawn["net_units"].sum()) if len(withdrawn) else 0,
            "warehouse_net_units_sum": int(match["net_units"].sum()) if len(match) else None,
            "warehouse_job_numbers": ", ".join(match["job_number"].tolist()) if len(match) else None,
            "warehouse_co_types": ", ".join(sorted(match["co_type"].dropna().unique())) if len(match) else None,
            "warehouse_dates_complete": ", ".join(
                d.strftime("%Y-%m-%d") for d in pd.to_datetime(match["date_complete"]).dropna()
            ) if len(match) else None,
            "first_tco_or_co_date": (
                pd.to_datetime(match["date_complete"]).dropna().min().strftime("%Y-%m-%d")
                if match["date_complete"].notna().any() else None),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------ G/H. fixed-window diffs

#: Fix G: no more all-pre/all-post averages. Two symmetric fixed windows, used
#: everywhere establishment counts and rent are compared, replacing v0's "mean of
#: everything before the anchor vs. mean of everything after" DiD input.
WINDOW_PRE = (2013, 2017)
WINDOW_POST = (2018, 2023)
COVID_YEARS = (2020, 2021)


def point_to_point(panel: pd.DataFrame, outcome_col: str, year_a: int, year_b: int,
                    zip_: str) -> dict:
    """Level and log-difference of `outcome_col` between exactly `year_a` and
    `year_b` for `zip_` (Fix G: a point-to-point change over a stated fixed window,
    not an averaged pre/post period). Returns NaN fields with `ok=False` if either
    year is missing for this zip rather than silently dropping the comparison."""
    sub = panel[panel["zip"] == zip_].set_index("year")[outcome_col]
    if year_a not in sub.index or year_b not in sub.index or pd.isna(sub.get(year_a)) or pd.isna(sub.get(year_b)):
        return {"zip": zip_, "outcome": outcome_col, "year_a": year_a, "year_b": year_b, "ok": False}
    a, b = float(sub[year_a]), float(sub[year_b])
    return {"zip": zip_, "outcome": outcome_col, "year_a": year_a, "year_b": year_b, "ok": True,
            "value_a": a, "value_b": b, "level_change": b - a,
            "pct_change": (b - a) / a * 100 if a else np.nan,
            "log_change": np.log(b) - np.log(a) if a > 0 and b > 0 else np.nan}


def yearly_series_table(panel: pd.DataFrame, outcome_col: str, zips: list[str]) -> pd.DataFrame:
    """Full year-by-year table for `outcome_col` across `zips`, wide (one column per
    zip) -- Fix G's "year-by-year series for everything" requirement, the thing that
    replaces any single pre/post average."""
    return (panel[panel["zip"].isin(zips)]
            .pivot_table(index="year", columns="zip", values=outcome_col)
            .reset_index())


# ------------------------------------------------------ E. pioneer/incumbent/follower

#: Owner-ruled definition (this session's brief): "pioneer" = an early NEW-WAVE
#: entrant, not simply "anything that opened before an anchor date" -- an old
#: Greenpoint institution that predates Loci's own tracking is an INCUMBENT, reported
#: separately, never counted as a pioneer even if its (unreliable) first-seen date
#: happens to fall before an anchor.
NEW_WAVE_PIONEER_CUTOFF_YEAR = 2013   # last of the hand-verified pioneer seed (Glasserie, 2013)
NEW_WAVE_FOLLOWER_START_YEAR = 2018   # first of the hand-verified follower seed (Oxomoco, Jun 2018)

#: Hand-verified seed list from the urban-planner review (2026-09-22). Dates are the
#: owner/reviewer's OWN verified values, used as-is for this named list regardless of
#: what the automated first-seen sources say (Section 4/Method logs the automated
#: read for each name too, and where it disagrees -- e.g. Achilles Heel is
#: left-censored in POI and its only SLA row is a 2025 re-license, not the true
#: ~2012-13 opening -- that disagreement is reported, not papered over).
PIONEER_SEED = [
    {"name": "Pencil Factory", "year": 2000, "note": "not in POI feed; SLA row present (2023-10-05) is a "
                                                       "re-license, not the ~2000 opening -- owner date used."},
    {"name": "Cafe Grumpy", "year": 2005, "note": "POI first_seen_on=2005-12-15, not censored -- confirms seed."},
    {"name": "Five Leaves", "year": 2008, "note": "POI first_seen_on=2008-10-12 (seed: 2008-09), not censored -- confirms seed."},
    {"name": "Paulie Gee's", "year": 2010, "note": "POI first_seen_on=2010-03-10, not censored -- confirms seed "
                                                     "(a separate 2016 'Slice Shop' spinoff is NOT this business)."},
    {"name": "Achilles Heel", "year": 2012, "note": "POI is_left_censored=True (no date); SLA's only row is a "
                                                      "2025-03-11 re-license, not original issue -- automated "
                                                      "sources cannot confirm this date, owner date used."},
    {"name": "Glasserie", "year": 2013, "note": "POI first_seen_on=2013-05-18, not censored -- confirms seed."},
]
FOLLOWER_SEED = [
    {"name": "Oxomoco", "year": 2018, "month": 6, "note": "POI first_seen_on=2018-05-01 (seed: Jun 2018), not censored -- close match."},
    {"name": "Laundromat (wine bar)", "year": 2021, "note": "not resolved by name in POI; a 2024-11-22 SLA row exists "
                                                              "at a plausible address (132 Franklin St) but reads as a "
                                                              "re-license, not opening -- owner date used, LOW automated corroboration."},
    {"name": "House at 50 Norman", "year": 2022, "note": "POI 'display_name'=50 Norman, first_seen_on=2022-09-18, not censored -- confirms seed."},
    {"name": "Wenwen", "year": 2022, "month": 3, "note": "POI first_seen_on=2022-03-11 (seed: Mar 2022), not censored -- confirms seed."},
]
INCUMBENT_SEED = [
    {"name": "Murawski", "note": "not found in POI or SLA feeds at all -- presumably closed before both "
                                  "sources' coverage windows; cannot be dated even as censored."},
    {"name": "Warsaw", "note": "POI first_seen_on=2003-12-10, is_left_censored=False -- but Thai Cafe (below) shows "
                                "the IDENTICAL date 2003-12-10, which is almost certainly a shared dataset-coverage-"
                                "start artifact (both are known multi-decade-old Greenpoint institutions), not each "
                                "business's real opening. Reported as INCUMBENT per owner ruling, NOT trusted as a "
                                "precise 2003 founding date despite is_left_censored=False."},
    {"name": "Thai Cafe", "note": "same 2003-12-10 first_seen_on artifact as Warsaw -- see above."},
]


def flag_shared_first_seen_artifact(poi_df: pd.DataFrame, min_group_size: int = 5) -> pd.Series:
    """Detects the Warsaw/Thai-Cafe pattern generally: a `first_seen_on` date shared
    by an unusually large number of otherwise-unrelated POIs, with `is_left_censored
    = False`, is far more likely a dataset-coverage-start artifact (everything already
    open on day 1 of some source's coverage gets stamped with that day) than
    `min_group_size`+ independent businesses opening on the exact same day. Returns a
    boolean Series aligned to `poi_df.index`, True where the row's first_seen_on
    falls on such a suspect date -- these rows should NOT be treated as having a
    reliable dated first-seen for pioneer/follower purposes even though
    is_left_censored says False."""
    counts = poi_df["first_seen_on"].value_counts()
    suspect_dates = set(counts[counts >= min_group_size].index)
    return poi_df["first_seen_on"].isin(suspect_dates)


def classify_new_wave(poi_df: pd.DataFrame) -> pd.DataFrame:
    """Rule-based first pass at NEW-WAVE vs INCUMBENT (Fix E) across every
    bar/cafe_bakery/restaurant POI in `poi_df` (already ZIP-filtered by the caller).
    A row is:
      - UNDATED  if first_seen_kind == 'observed' OR is_left_censored -- excluded
        from any dated claim per the brief; reported separately, never silently
        dropped.
      - INCUMBENT if it has a date but that date falls on a shared-first-seen-
        artifact day (flag_shared_first_seen_artifact) -- a dated-looking row that is
        almost certainly not really dated (the Warsaw/Thai Cafe pattern).
      - NEW_WAVE otherwise -- a genuinely distinct, plausible first-seen date.
    Within NEW_WAVE: PIONEER if year <= NEW_WAVE_PIONEER_CUTOFF_YEAR (2013),
    FOLLOWER if year >= NEW_WAVE_FOLLOWER_START_YEAR (2018), else TRANSITIONAL
    (2014-2017 -- the brief's seed list has no examples in this window, so it is
    reported as its own bucket rather than forced into pioneer or follower)."""
    df = poi_df[poi_df["category"].isin(FOOD_DRINK_BUCKETS + ["bar"])].copy()
    df["first_seen_date"] = resolve_first_seen_date(df)
    df["is_undated"] = (df["first_seen_kind"] == "observed") | df["is_left_censored"].fillna(False)
    df["is_artifact_date"] = flag_shared_first_seen_artifact(df) & ~df["is_undated"]

    def wave(row):
        if row["is_undated"]:
            return "UNDATED"
        if row["is_artifact_date"]:
            return "INCUMBENT (dataset-start artifact)"
        yr = row["first_seen_date"].year
        if yr <= NEW_WAVE_PIONEER_CUTOFF_YEAR:
            return "NEW_WAVE-PIONEER"
        if yr >= NEW_WAVE_FOLLOWER_START_YEAR:
            return "NEW_WAVE-FOLLOWER"
        return "NEW_WAVE-TRANSITIONAL"
    df["wave_class"] = df.apply(wave, axis=1)
    return df


def pioneer_follower_interval(classified: pd.DataFrame) -> dict:
    """Fix E interval reporting: for the NEW_WAVE-PIONEER and NEW_WAVE-FOLLOWER
    buckets, report [certain, certain+censored] where `certain` = rows with a real,
    non-artifact dated first-seen already in that bucket, and the `+censored` upper
    end acknowledges that some UNDATED rows COULD also belong there (their true date
    is unknown, not necessarily late) -- pioneers are explicitly labeled a LOWER
    bound, since a censored row's true date can only push a pioneer count UP, never
    down. Also reports the NaT/undated share, and open vs. closed split, for every
    wave_class bucket."""
    n_total = len(classified)
    n_undated = int((classified["wave_class"] == "UNDATED").sum())
    out = {"n_total": n_total, "n_undated": n_undated,
           "undated_share": n_undated / n_total if n_total else np.nan}
    for cls in ["NEW_WAVE-PIONEER", "NEW_WAVE-FOLLOWER", "NEW_WAVE-TRANSITIONAL",
                "INCUMBENT (dataset-start artifact)", "UNDATED"]:
        sub = classified[classified["wave_class"] == cls]
        out[cls] = {
            "certain": len(sub),
            "n_open": int((~sub["is_closed"].fillna(False)).sum()),
            "n_closed": int(sub["is_closed"].fillna(False).sum()),
        }
    # certain+censored upper bound: certain count in the bucket + ALL undated rows
    # (since an undated row cannot be ruled out of either bucket).
    out["NEW_WAVE-PIONEER"]["upper_bound_with_censored"] = out["NEW_WAVE-PIONEER"]["certain"] + n_undated
    out["NEW_WAVE-FOLLOWER"]["upper_bound_with_censored"] = out["NEW_WAVE-FOLLOWER"]["certain"] + n_undated
    out["NEW_WAVE-PIONEER"]["bound_type"] = "LOWER bound on true pioneer count (certain only); " \
        f"[{out['NEW_WAVE-PIONEER']['certain']}, {out['NEW_WAVE-PIONEER']['upper_bound_with_censored']}]"
    return out


# --------------------------------------------------------------- J. event study

def yearly_log_gap(panel: pd.DataFrame, outcome_col: str, treatment: str, control: str,
                    years: list[int] | None = None) -> pd.DataFrame:
    """Event-study-style yearly gap in log(outcome), treatment minus control, for
    every year both have data (Fix J). Reported as its own year-by-year series (not
    collapsed to a pre/post average) so a reader can see directly whether the gap was
    already widening before the towers delivered (2018) -- i.e. whether Section
    7/pre-trend's concern shows up here too."""
    wide = panel[panel["zip"].isin([treatment, control])].pivot_table(
        index="year", columns="zip", values=outcome_col)
    if years:
        wide = wide.loc[[y for y in years if y in wide.index]]
    wide = wide.dropna(subset=[treatment, control])
    gap = np.log(wide[treatment]) - np.log(wide[control])
    return pd.DataFrame({"year": gap.index, "log_gap": gap.to_numpy()}).reset_index(drop=True)


def placebo_gap_ranking(panel: pd.DataFrame, outcome_col: str, control: str,
                         candidate_zips: list[str], treatment: str,
                         pre_years: tuple[int, int] = WINDOW_PRE,
                         post_years: tuple[int, int] = WINDOW_POST) -> pd.DataFrame:
    """Fix J placebo: repeat the same yearly-log-gap-vs-`control` calculation with
    each of `candidate_zips` standing in for `treatment` (a placebo-in-space test,
    Abadie-style), rank all N+1 units (real treatment + N placebos) by
    mean(post_years log-gap) - mean(pre_years log-gap), and report where the REAL
    treatment ranks -- rank/(N+1), where rank 1 = the single largest excess-growth
    unit. A treatment ranking near the top (e.g. 1/(N+1)) says its excess growth vs.
    control is unusual among comparable ZIPs; a middling rank says it is not
    distinguishable from ordinary cross-ZIP variance. Purely descriptive -- no
    p-value is claimed from N+1 units."""
    units = [treatment] + [z for z in candidate_zips if z != control and z != treatment]
    rows = []
    for z in units:
        try:
            g = yearly_log_gap(panel, outcome_col, z, control)
        except Exception:
            continue
        pre = g[(g["year"] >= pre_years[0]) & (g["year"] <= pre_years[1])]["log_gap"]
        post = g[(g["year"] >= post_years[0]) & (g["year"] <= post_years[1])]["log_gap"]
        if pre.empty or post.empty:
            continue
        rows.append({"zip": z, "mean_pre_log_gap": pre.mean(), "mean_post_log_gap": post.mean(),
                      "excess_growth": post.mean() - pre.mean()})
    out = pd.DataFrame(rows).sort_values("excess_growth", ascending=False).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    out["rank_over_n_plus_1"] = out["rank"].astype(str) + f"/{len(out)}"
    return out


# ---------------------------------------------------------------- §1 provenance

def stamp_supply_hash(con) -> dict:
    """The live POI supply hash to stamp in the notebook's Section 1 provenance
    block. `score.supply.supply_hash(con)` IS the repo's own function for this
    (found under src/loci/score/supply.py) -- computed live here, against the
    recorded value from peer 6d's D139 report (SUPPLY_HASH, 'c796e59da990'), rather
    than just repeating the recorded string uncomputed."""
    from loci.score import supply as supply_mod
    live = supply_mod.supply_hash(con)
    return {"recorded_per_peer_6d": SUPPLY_HASH, "computed_live": live, "match": live == SUPPLY_HASH}
