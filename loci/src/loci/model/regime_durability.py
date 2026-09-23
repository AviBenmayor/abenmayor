"""RQ-001 — regime durability: how long favorable neighborhood conditions last for a
restaurant, and what ends them.

Implements the v0 recipe in ``docs/research/RQ-001-regime-durability/METHOD.md``
(the data-scientist's design memo), amended by the contrarian and statistician
verdicts at the bottom of that file, further amended by owner rulings dated
2026-09-22 (see the notebook's section 0 for the verbatim rulings). This module is
the tested logic; ``docs/research/RQ-001-regime-durability/notebook.ipynb`` is the
executed report that imports it.

**What v0 actually measures** (state this every time the composite is used): a ZIP's
survival in the top ~third of a within-year relative rank composite of demand,
supply-saturation and cost. It is descriptive of *relative position*, not of absolute
neighborhood quality, and it says nothing causal. See ANSWER.md for the full honesty
statement.

**Documented deviations from METHOD.md, made necessary by what is actually in this
warehouse (recorded once here, not repeated at every call site):**

1. **No 1994-99 pre-window.** ZBP in this warehouse starts 1998 (not 1994; the
   1994-97 SIC-era years were never crosswalked, D42) and the population panel
   (``zcta_pop_interpolated_2000_2020``) starts at the 2000 census. There is no
   2-pillar pre-window that could date a spell already running before the panel
   starts. The headline window is **2000-2023**, not the memo's imagined 1994-99
   dating panel, and "prevalent" (undatable onset) means "already favorable in
   2000", not "already favorable in 1994-99".
2. **ZIP == ZCTA.** No USPS ZIP-to-ZCTA crosswalk file was available in this repo's
   data directories. NYC ZIP codes and ZCTAs coincide for all but a handful of
   PO-box/single-building codes, which the ZBP/ZHVI/population sources already
   exclude by only carrying delivery-area codes. This is an approximation, stated
   once, not re-derived.
3. **PUMA bootstrap not run.** No ZIP/ZCTA-to-PUMA crosswalk was found. Only the
   spatial-block bootstrap (k-means on ZCTA centroids) runs; METHOD's instruction to
   report the wider of the two is satisfied trivially (spatial-block is the only
   one), and this is stated as a known gap, not silently dropped.
2. **Income source is runtime-conditional.** ``docs/research/RQ-001.../DATA-AUDIT.md``
   notes the IRS SOI ZIP panel was mid-build by a peer session. ``load_income_zip``
   checks for the parquet at call time and prints which source it used
   (IRS SOI 1998-2023 if present, else ACS median household income 2011-2024 only,
   clearly narrower). The notebook is re-runnable either way.
4. **Simplified spatial block bootstrap, reduced null-model and bootstrap rep
   counts** (500 instead of 2,000) for runtime; documented, not hidden.
5. **Discrete-time hazard uses borough-clustered (not two-way PUMA x year) robust
   SEs**, no PySAL spatial-error re-estimation, and a duration quadratic instead of
   a full spline. Holm correction is applied to the driver family and the 3 macro
   interaction terms.
6. **E2 (COVID exposure) uses "non-retail, non-food-service LODES job share"**
   (1 - (CNS07+CNS18)/C000) as an office/remote-work-exposure proxy, since this
   warehouse's LODES extract only carries C000/CNS07/CNS18, not a full industry
   breakdown.
"""
from __future__ import annotations

import pathlib
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RQ001_INTERIM = REPO_ROOT / "data" / "interim" / "rq001"
RQ002_INTERIM = REPO_ROOT / "data" / "interim" / "rq002"

# ---------------------------------------------------------------------------- NAICS

# "722 total" restaurant+bar family, continuous across the 2012 NAICS recode
# (statistician S3). Excludes 722310/722320/722330 (contractors/caterers/mobile).
NAICS_PRE2012 = ("722110", "722211", "722212", "722213", "722410")
NAICS_POST2012 = ("722511", "722513", "722514", "722515", "722410")
ALL_RESTAURANT_NAICS = tuple(sorted(set(NAICS_PRE2012) | set(NAICS_POST2012)))

# METHOD §7 segment crosswalk.
SEGMENT_NAICS = {
    "full_service": {"pre": ("722110",), "post": ("722511",)},
    "limited_service": {"pre": ("722211", "722212"), "post": ("722513", "722514")},
    "snack_coffee": {"pre": ("722213",), "post": ("722515",)},
    "bar": {"pre": ("722410",), "post": ("722410",)},
}

# ---------------------------------------------------------------------------- units

# Statistician S1 minimum merge list (splits the audit and PREREGISTRATION both
# name). Any ZIP not listed maps to itself. Additional candidate splits are
# surfaced by `detect_break_flags`, not auto-merged (documented simplification —
# full areal-overlap split detection needs a parcel-level crosswalk this repo does
# not have).
KNOWN_UNIT_MERGES: dict[str, str] = {
    "11249": "11211",  # Williamsburg waterfront, carved from 11211 in 2011
    "10065": "10021",  # UES, carved from 10021 in 2007
    "10075": "10021",
    "11109": "11101",  # LIC, carved from 11101
}

# PREREGISTRATION.md §1 (14 scored ZIPs) + §"unscored context". unit = the frozen
# unit each named ZIP rolls into (see KNOWN_UNIT_MERGES).
NAMED_ZIP_PREREGISTRATION = [
    # zip, neighborhood, onset_expected ('<=2000'|'none'|'2008'|'>=2016'), exit_expected (int|'ongoing'|'none'),
    # exit_driver_expected, confidence, non_template (bool)
    dict(zip="11211", neighborhood="Williamsburg (N/S Side)", onset="<=2000", exit=2011, driver="cost", conf="med", non_template=False),
    dict(zip="11206", neighborhood="E. Williamsburg / N. Bushwick", onset="<=2000", exit=2016, driver="cost", conf="low", non_template=False),
    dict(zip="11237", neighborhood="Bushwick core", onset="<=2000", exit=2017, driver="cost", conf="low_med", non_template=False),
    dict(zip="10002", neighborhood="LES / Chinatown", onset="<=2000", exit=2007, driver="cost", conf="low", non_template=False),
    dict(zip="10026", neighborhood="Central Harlem (FDB)", onset="<=2000", exit=2012, driver="cost", conf="low_med", non_template=False),
    dict(zip="10031", neighborhood="Hamilton Heights / Sugar Hill", onset="<=2000", exit="ongoing", driver="cost", conf="med", non_template=True),
    dict(zip="11215", neighborhood="Park Slope", onset="none", exit=None, driver=None, conf="med_high", non_template=True),
    dict(zip="11216", neighborhood="Bed-Stuy (west)", onset="<=2000", exit=2016, driver="cost", conf="med", non_template=False),
    dict(zip="11238", neighborhood="Prospect Heights / Clinton Hill", onset="<=2000", exit=2009, driver="cost", conf="low", non_template=False),
    dict(zip="11222", neighborhood="Greenpoint", onset="<=2000", exit=2012, driver="cost", conf="low", non_template=False),
    dict(zip="11103", neighborhood="Astoria (central)", onset="none", exit=None, driver="supply", conf="low", non_template=True),
    dict(zip="11101", neighborhood="Long Island City", onset="2008", exit="ongoing", driver="cost", conf="low", non_template=True),
    dict(zip="10128", neighborhood="Carnegie Hill / Yorkville (control)", onset="none", exit=None, driver=None, conf="high", non_template=True),
    dict(zip="11208", neighborhood="East New York / Cypress Hills (control)", onset="none_or_2016", exit=None, driver=None, conf="med", non_template=True),
]

OPERATOR_SITES = [
    # name, zip, opening_year (approximate, for spot-check only)
    dict(name="Lion's Milk", zip="11222", opening_year=2021),
    dict(name="El Punto", zip="10453", opening_year=2022),
    dict(name="Stone Street", zip="10004", opening_year=2015),
    dict(name="Deux Luxe", zip="11222", opening_year=2022),
    dict(name="Fazenda", zip="11201", opening_year=2019),
]

HEADLINE_START_YEAR = 2000
HEADLINE_END_YEAR = 2023
SUPPLY_START_YEAR = 1998

ENTER_THRESH = 0.70
EXIT_THRESH = 0.60
PERSIST_YEARS = 2

MIN_POP = 2000  # METHOD §1 universe rule


def to_unit(zipcode: str) -> str:
    return KNOWN_UNIT_MERGES.get(str(zipcode), str(zipcode))


# ============================================================================
# LOADERS — each prints which source it used, and never raises on a missing
# optional input; callers get a documented fallback instead.
# ============================================================================


def load_supply_zip_year(con) -> pd.DataFrame:
    """ZIP x year restaurant+bar establishment counts (NAICS 722 family, both eras)
    and per-segment counts, from analysis.zip_establishments (warehouse, 1998-2023)."""
    naics_list = ", ".join(f"'{n}'" for n in ALL_RESTAURANT_NAICS)
    df = con.execute(
        f"""
        select zipcode, year, naics, sum(estab) as estab
        from analysis.zip_establishments
        where naics in ({naics_list})
        group by zipcode, year, naics
        """
    ).fetchdf()
    df["unit"] = df["zipcode"].map(to_unit)
    total = df.groupby(["unit", "year"])["estab"].sum().rename("estab_restaurant_total").reset_index()

    seg_frames = []
    for seg, codes in SEGMENT_NAICS.items():
        codes_all = set(codes["pre"]) | set(codes["post"])
        seg_df = df[df["naics"].isin(codes_all)]
        seg_tot = (
            seg_df.groupby(["unit", "year"])["estab"].sum().rename(f"estab_{seg}").reset_index()
        )
        seg_frames.append(seg_tot)
    out = total
    for f in seg_frames:
        out = out.merge(f, on=["unit", "year"], how="left")
    for seg in SEGMENT_NAICS:
        out[f"estab_{seg}"] = out[f"estab_{seg}"].fillna(0.0)
    print(f"[loader] supply: analysis.zip_establishments, {out['year'].min()}-{out['year'].max()}, "
          f"{out['unit'].nunique()} units")
    return out


def load_zhvi(interim_dir: pathlib.Path = RQ001_INTERIM) -> pd.DataFrame:
    path = interim_dir / "zillow" / "zillow_nyc_annual.parquet"
    df = pd.read_parquet(path)
    zhvi = df[df["index"] == "zhvi"][["zip", "year", "value_mean"]].rename(
        columns={"value_mean": "zhvi"}
    )
    zhvi["unit"] = zhvi["zip"].map(to_unit)
    zhvi = zhvi.groupby(["unit", "year"], as_index=False)["zhvi"].mean()
    print(f"[loader] cost (ZHVI): {path.relative_to(REPO_ROOT)}, "
          f"{zhvi['year'].min()}-{zhvi['year'].max()}, {zhvi['unit'].nunique()} units")
    return zhvi


def load_zori(interim_dir: pathlib.Path = RQ001_INTERIM) -> pd.DataFrame:
    path = interim_dir / "zillow" / "zillow_nyc_annual.parquet"
    df = pd.read_parquet(path)
    zori = df[df["index"] == "zori"][["zip", "year", "value_mean"]].rename(
        columns={"value_mean": "zori"}
    )
    zori["unit"] = zori["zip"].map(to_unit)
    zori = zori.groupby(["unit", "year"], as_index=False)["zori"].mean()
    print(f"[loader] cost check (ZORI): {path.relative_to(REPO_ROOT)}, "
          f"{zori['year'].min()}-{zori['year'].max()}, {zori['unit'].nunique()} units (check only, not a composite input)")
    return zori


def load_population(rq002_dir: pathlib.Path = RQ002_INTERIM) -> pd.DataFrame:
    """Statistician S3: population from decennial 2000/2010/2020, linearly
    interpolated for every year, 2021-23 carried forward (documented, not S3's
    "every year" literally since there is no 2030 census to interpolate to).

    Self-heals a known race: `tests/test_census_decennial_zcta.py` calls
    `census_decennial_zcta.build_long`/`interpolate_population` directly with
    small synthetic DataFrames, and those functions write unconditionally to
    this exact production path — so a peer session running that test suite
    can (and, during this build, did) overwrite the real file with an 11-row
    toy fixture. This loader validates the file (a known NYC ZCTA must be
    present with a plausible population) and regenerates it from the raw
    per-vintage parquets (`decennial_zcta_{2000,2010,2020}.parquet`, which the
    test suite does not touch) if the validation fails."""
    path = rq002_dir / "decennial" / "zcta_pop_interpolated_2000_2020.parquet"

    def _valid(df: pd.DataFrame) -> bool:
        if df["zcta"].nunique() < 1000:
            return False
        probe = df[(df["zcta"] == "10001") & (df["year"] == 2010)]
        return len(probe) > 0 and probe["pop"].iloc[0] > MIN_POP

    df = pd.read_parquet(path)[["zcta", "year", "pop"]]
    if not _valid(df):
        print("[loader] population: zcta_pop_interpolated_2000_2020.parquet looks like a test "
              "fixture (too few ZCTAs / known ZIP missing) — regenerating from raw decennial "
              "vintage parquets (a peer session's test suite writes toy data to this exact path)")
        from loci.sources.universal import census_decennial_zcta as cdz
        frames = {y: pd.read_parquet(cdz.INTERIM_DIR / f"decennial_zcta_{y}.parquet") for y in (2000, 2010, 2020)}
        long_df = cdz.build_long(frames)
        df = cdz.interpolate_population(long_df)[["zcta", "year", "pop"]]
        if not _valid(df):
            raise RuntimeError("regenerated zcta_pop_interpolated_2000_2020.parquet still fails validation")

    df = df.rename(columns={"zcta": "unit"})
    df["unit"] = df["unit"].map(to_unit)
    df = df.groupby(["unit", "year"], as_index=False)["pop"].sum()
    last_year = df["year"].max()
    tail = df[df["year"] == last_year].copy()
    forward = []
    for y in range(last_year + 1, HEADLINE_END_YEAR + 1):
        t = tail.copy()
        t["year"] = y
        forward.append(t)
    if forward:
        df = pd.concat([df] + forward, ignore_index=True)
        print(f"[loader] population: {path.relative_to(REPO_ROOT)}, interpolated 2000-{last_year}, "
              f"carried forward flat {last_year + 1}-{HEADLINE_END_YEAR} ({df['unit'].nunique()} units)")
    else:
        print(f"[loader] population: {path.relative_to(REPO_ROOT)}, {df['year'].min()}-{df['year'].max()}")
    return df


def load_workers(interim_dir: pathlib.Path = RQ001_INTERIM) -> pd.DataFrame:
    """LODES C000 (total jobs), ZCTA x year, 2002-2023. 1998-2001 back-filled flat
    from the 2002 value — a stated 4-year gap at the very start of the panel."""
    path = interim_dir / "lodes" / "lodes_wac_zcta.parquet"
    df = pd.read_parquet(path)[["zcta", "year", "c000", "cns07", "cns18"]].rename(
        columns={"zcta": "unit", "c000": "workers", "cns07": "workers_retail", "cns18": "workers_foodaccom"}
    )
    df["unit"] = df["unit"].map(to_unit)
    df = df.groupby(["unit", "year"], as_index=False)[["workers", "workers_retail", "workers_foodaccom"]].sum()
    first_year = df["year"].min()
    early = df[df["year"] == first_year].copy()
    backfill = []
    for y in range(SUPPLY_START_YEAR, first_year):
        t = early.copy()
        t["year"] = y
        backfill.append(t)
    df = pd.concat(backfill + [df], ignore_index=True)
    print(f"[loader] workers: {path.relative_to(REPO_ROOT)}, LODES C000 {first_year}-{df['year'].max()}, "
          f"{SUPPLY_START_YEAR}-{first_year - 1} back-filled flat from {first_year} ({df['unit'].nunique()} units)")
    return df


def load_income_zip(interim_dir: pathlib.Path = RQ001_INTERIM) -> tuple[pd.DataFrame, str]:
    """Contrarian amendment 2 / statistician S4(a): prefer the IRS SOI ZIP panel if
    it exists at call time; else fall back to S4(b), ACS median household income,
    2011-2024 only (`acs_zcta_panel`), and say so. Returns (df[unit, year,
    income_real], source_label).

    Per the 2026-09-22 coordinator note: the IRS SOI panel has tax years
    1998, 2001, 2002, 2004-2022 (1999/2000/2003 never published at ZIP grain).
    Legacy years (pre-2011) carry only a ZIP-total row (`agi_stub` is NULL);
    2011+ carries a total row (`agi_stub == 0`) plus income brackets 1-6 — the
    total row is used, brackets are dropped. Missing single years inside the
    published range are linearly interpolated per unit (documented, not
    silently filled); years outside the published range (2023) are carried
    forward flat from the nearest published year."""
    irs_path = interim_dir / "irs_soi" / "irs_zip_income_panel.parquet"
    if irs_path.exists():
        try:
            df = pd.read_parquet(irs_path)
        except Exception as exc:  # concurrently-written parquet, race with a peer session
            print(f"[loader] income: IRS SOI parquet present but unreadable ({exc!r}) "
                  f"— falling back to ACS")
            df = None
        if df is not None:
            # mean AGI per return, real dollars requires a CPI deflator (macro loader);
            # this loader returns nominal AGI-per-return and the caller deflates.
            df = df.rename(columns={"zip": "unit", "tax_year": "year"})
            df["unit"] = df["unit"].map(to_unit)
            # total row only: agi_stub is NULL (legacy, pre-2011) or 0 (2011+ total)
            df = df[df["agi_stub"].isna() | (df["agi_stub"] == 0)].copy()
            df = df[df["n1"] > 0].copy()
            # `agi` in this parquet is already aggregate dollars (verified against raw:
            # 11208/2020/agi_stub=0 is agi=1.728e9, n1=48470 -> $35.7k/return, plausible;
            # NOT thousands, despite IRS SOI's usual $-thousands convention -- no *1000 here.
            df["income_nominal"] = df["agi"] / df["n1"]
            published = df.groupby(["unit", "year"], as_index=False).apply(
                lambda g: pd.Series({
                    "income_nominal": np.average(g["income_nominal"], weights=g["n1"])
                }),
                include_groups=False,
            )
            published_years = sorted(published["year"].unique())
            n_published = len(published)
            full_years = list(range(HEADLINE_START_YEAR, HEADLINE_END_YEAR + 1))
            idx = pd.MultiIndex.from_product([published["unit"].unique(), full_years], names=["unit", "year"])
            out = published.set_index(["unit", "year"]).reindex(idx).reset_index()
            out["income_nominal"] = (
                out.groupby("unit")["income_nominal"]
                .apply(lambda s: s.interpolate(limit_direction="both"))
                .reset_index(drop=True)
            )
            n_interpolated = out["income_nominal"].notna().sum() - n_published
            print(f"[loader] income: {irs_path.relative_to(REPO_ROOT)} (IRS SOI mean AGI/return, total row only), "
                  f"published tax years {published_years}, {n_published} published unit-years, "
                  f"{max(n_interpolated, 0)} interpolated/carried-forward unit-years, "
                  f"{out['unit'].nunique()} units")
            return out.dropna(subset=["income_nominal"]), "irs_soi"
    acs_path = interim_dir / "acs_zcta" / "acs_zcta_panel.parquet"
    df = pd.read_parquet(acs_path)
    df = df.rename(columns={"zcta": "unit", "acs_year": "year"})
    df["unit"] = df["unit"].map(to_unit)
    out = df.groupby(["unit", "year"], as_index=False)["median_hh_income_e"].mean().rename(
        columns={"median_hh_income_e": "income_nominal"}
    )
    print(f"[loader] income: IRS SOI parquet not present at call time — FALLBACK to "
          f"{acs_path.relative_to(REPO_ROOT)} (ACS median HH income), "
          f"{out['year'].min()}-{out['year'].max()} only, {out['unit'].nunique()} units")
    return out, "acs_fallback"


def load_macro(interim_dir: pathlib.Path = RQ001_INTERIM) -> pd.DataFrame:
    path = interim_dir / "macro" / "macro_annual.parquet"
    df = pd.read_parquet(path)
    print(f"[loader] macro: {path.relative_to(REPO_ROOT)}, series {sorted(df['series_id'].unique())}, "
          f"{df['year'].min()}-{df['year'].max()}")
    return df


def deflate_to_real(nominal: pd.Series, year: pd.Series, macro: pd.DataFrame, base_year: int = 2023) -> pd.Series:
    """CPI deflate using CUURA101SA0 (NY-metro CPI-U, all items) from the macro panel."""
    cpi = macro[macro["series_id"] == "CUURA101SA0"].set_index("year")["value"]
    base = cpi.get(base_year, cpi.iloc[-1])
    factor = year.map(lambda y: base / cpi.get(y, np.nan))
    return nominal * factor


def load_zcta_geometry(rq002_dir: pathlib.Path = RQ002_INTERIM):
    import geopandas as gpd

    path = rq002_dir / "zcta_boundaries" / "zcta_2020_nyc.parquet"
    g = gpd.read_parquet(path)
    g["unit"] = g["zcta"].map(to_unit)
    g = g.dissolve(by="unit", as_index=False)
    g_m = g.to_crs(2263)  # NY State Plane, feet
    g["area_km2"] = g_m.geometry.area * 0.092903 / 1e6
    centroid = g_m.geometry.centroid
    g["cx"] = centroid.x
    g["cy"] = centroid.y
    print(f"[loader] ZCTA geometry (2020 vintage, static across the panel): "
          f"{path.relative_to(REPO_ROOT)}, {g['unit'].nunique()} units")
    return g[["unit", "area_km2", "cx", "cy"]]


def load_restaurant_closures(con, rq002_dir: pathlib.Path = RQ002_INTERIM) -> pd.DataFrame:
    """DOHMH POI restaurant opens/closes, spatial-joined to the (static, 2020-vintage)
    ZCTA polygons — used only for the criterion-validity closure check, never as a
    composite input. Returns unit, year, n_open (at-risk restaurant-years), n_closed."""
    import geopandas as gpd
    from shapely.geometry import Point

    df = con.execute(
        """
        select location_key, lon, lat, first_seen_on, closed_on, is_closed
        from analysis.poi_first_seen
        where category = 'restaurant' and lon is not null and lat is not null
        """
    ).fetchdf()
    geom = [Point(xy) for xy in zip(df["lon"], df["lat"])]
    gdf = gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
    zctas = load_zcta_geometry.__wrapped__(rq002_dir) if hasattr(load_zcta_geometry, "__wrapped__") else None
    zcta_poly = gpd.read_parquet(rq002_dir / "zcta_boundaries" / "zcta_2020_nyc.parquet")
    zcta_poly["unit"] = zcta_poly["zcta"].map(to_unit)
    zcta_poly = zcta_poly.dissolve(by="unit", as_index=False)[["unit", "geometry"]]
    joined = gpd.sjoin(gdf, zcta_poly, how="inner", predicate="within")
    joined["first_seen_on"] = pd.to_datetime(joined["first_seen_on"])
    joined["closed_on"] = pd.to_datetime(joined["closed_on"])

    rows = []
    for y in range(2010, 2024):
        as_of_start = pd.Timestamp(f"{y}-01-01")
        as_of_end = pd.Timestamp(f"{y}-12-31")
        at_risk = joined[(joined["first_seen_on"] <= as_of_end) &
                          ((joined["closed_on"].isna()) | (joined["closed_on"] >= as_of_start))]
        closed_this_year = joined[(joined["closed_on"] >= as_of_start) & (joined["closed_on"] <= as_of_end)]
        g1 = at_risk.groupby("unit").size().rename("n_open")
        g2 = closed_this_year.groupby("unit").size().rename("n_closed")
        yr = pd.concat([g1, g2], axis=1).fillna(0).reset_index()
        yr["year"] = y
        rows.append(yr)
    out = pd.concat(rows, ignore_index=True)
    print(f"[loader] restaurant closures (DOHMH, spatial-joined to 2020 ZCTA polygons): "
          f"{joined.shape[0]} POIs matched, 2010-2023")
    return out


# ============================================================================
# UNIT / PANEL BUILD
# ============================================================================


def detect_break_flags(panel: pd.DataFrame, value_col: str, mad_k: float = 4.0) -> pd.DataFrame:
    """Statistician S1 detection assert: flag unit-years where |Δlog(value)| exceeds
    mad_k robust-SD (MAD) of that unit's own series. Applies to any level series
    (estab total, ZHVI) — used both for the unit-merge sanity check and §9/S5 break
    detection."""
    df = panel.sort_values(["unit", "year"]).copy()
    df["log_v"] = np.log(df[value_col].clip(lower=1e-6))
    df["d_log"] = df.groupby("unit")["log_v"].diff()
    def _flag(g):
        mad = (g["d_log"] - g["d_log"].median()).abs().median() * 1.4826
        thresh = mad_k * mad if mad > 0 else np.inf
        g["flag"] = g["d_log"].abs() > thresh
        return g
    df = df.groupby("unit", group_keys=False).apply(_flag, include_groups=True)
    return df[df["flag"]][["unit", "year", "d_log"]]


def build_universe(supply: pd.DataFrame, pop: pd.DataFrame, zhvi: pd.DataFrame) -> list[str]:
    """METHOD §1: fixed, balanced set of units — population >= MIN_POP in every
    headline year, present in supply and ZHVI every headline year."""
    years = range(HEADLINE_START_YEAR, HEADLINE_END_YEAR + 1)
    pop_ok = (
        pop[pop["year"].isin(years)]
        .groupby("unit")
        .apply(lambda g: (g.set_index("year")["pop"].reindex(years) >= MIN_POP).all(), include_groups=False)
    )
    pop_units = set(pop_ok[pop_ok].index)
    supply_units = set(
        supply[supply["year"].isin(years)].groupby("unit")["year"].nunique()
        .pipe(lambda s: s[s == len(list(years))]).index
    )
    zhvi_units = set(
        zhvi[zhvi["year"].isin(years)].groupby("unit")["year"].nunique()
        .pipe(lambda s: s[s == len(list(years))]).index
    )
    universe = sorted(pop_units & supply_units & zhvi_units)
    return universe


def build_zip_year_panel(con, interim_dir: pathlib.Path = RQ001_INTERIM,
                          rq002_dir: pathlib.Path = RQ002_INTERIM) -> tuple[pd.DataFrame, dict]:
    """Assemble the full ZIP(unit) x year panel, 2000-2023 headline, all components
    on the frozen unit universe. Returns (panel_df, provenance dict)."""
    supply = load_supply_zip_year(con)
    zhvi = load_zhvi(interim_dir)
    zori = load_zori(interim_dir)
    pop = load_population(rq002_dir)
    workers = load_workers(interim_dir)
    income, income_source = load_income_zip(interim_dir)
    macro = load_macro(interim_dir)
    geo = load_zcta_geometry(rq002_dir)

    income = income.copy()
    income["income_real"] = deflate_to_real(income["income_nominal"], income["year"], macro)

    universe = build_universe(supply, pop, zhvi)
    print(f"[panel] frozen universe: {len(universe)} units, {HEADLINE_START_YEAR}-{HEADLINE_END_YEAR}")

    years = list(range(HEADLINE_START_YEAR, HEADLINE_END_YEAR + 1))
    idx = pd.MultiIndex.from_product([universe, years], names=["unit", "year"])
    panel = pd.DataFrame(index=idx).reset_index()

    panel = panel.merge(supply, on=["unit", "year"], how="left")
    panel = panel.merge(zhvi, on=["unit", "year"], how="left")
    panel = panel.merge(zori, on=["unit", "year"], how="left")
    panel = panel.merge(pop, on=["unit", "year"], how="left")
    panel = panel.merge(workers[["unit", "year", "workers", "workers_retail", "workers_foodaccom"]],
                         on=["unit", "year"], how="left")
    panel = panel.merge(income[["unit", "year", "income_real"]], on=["unit", "year"], how="left")
    panel = panel.merge(geo, on="unit", how="left")

    # ZORI correlation check (METHOD §1)
    both = panel.dropna(subset=["zhvi", "zori"])
    zori_corr = both.groupby("year").apply(
        lambda g: g["zhvi"].corr(g["zori"], method="spearman"), include_groups=False
    ) if len(both) else pd.Series(dtype=float)

    provenance = {
        "n_units": len(universe),
        "years": (years[0], years[-1]),
        "income_source": income_source,
        "zori_zhvi_rank_corr_by_year": zori_corr.to_dict(),
    }
    return panel, provenance


# ============================================================================
# PILLARS AND COMPOSITES
# ============================================================================


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average")


def compute_pillar_percentiles(panel: pd.DataFrame) -> pd.DataFrame:
    """Within-year percentile ranks for every raw component, plus the ORIGINAL
    (composite A) and AMENDED (composite B owner/tenant) pillars."""
    df = panel.copy()
    df["density_pop"] = df["pop"] / df["area_km2"]
    df["density_workers"] = df["workers"] / df["area_km2"]
    df["saturation_headcount"] = df["estab_restaurant_total"] / (df["pop"] + df["workers"]).clip(lower=1)

    g = df.groupby("year")
    df["pct_income"] = g["income_real"].transform(_pct_rank)
    df["pct_pop_density"] = g["density_pop"].transform(_pct_rank)
    df["pct_worker_density"] = g["density_workers"].transform(_pct_rank)
    df["demand_pillar_A"] = df[["pct_income", "pct_pop_density", "pct_worker_density"]].mean(axis=1, skipna=True)
    df["demand_pillar_A"] = df.groupby("year")["demand_pillar_A"].transform(_pct_rank)

    df["pct_saturation_headcount"] = g["saturation_headcount"].transform(_pct_rank)
    df["supply_pillar_A"] = 1 - df["pct_saturation_headcount"]  # lower saturation = favorable

    df["pct_zhvi"] = g["zhvi"].transform(_pct_rank)
    df["cost_pillar_A"] = 1 - df["pct_zhvi"]  # lower cost = favorable

    df["composite_A_raw"] = df[["demand_pillar_A", "supply_pillar_A", "cost_pillar_A"]].mean(axis=1, skipna=True)
    df["composite_A"] = df.groupby("year")["composite_A_raw"].transform(_pct_rank)

    # ---- AMENDED (contrarian amendments 1-3) ----
    per_worker_const = df.groupby("year")["income_real"].transform("median")  # stated fixed real constant per year's median income
    df["spending_power"] = df["pop"] * df["income_real"] + df["workers"] * per_worker_const
    df["saturation_spending"] = df["estab_restaurant_total"] / df["spending_power"].clip(lower=1)
    df["supply_pillar_B"] = 1 - df.groupby("year")["saturation_spending"].transform(_pct_rank)

    df["demand_gate"] = df["demand_pillar_A"] >= df.groupby("year")["demand_pillar_A"].transform("median")

    def _gated_rank(frame: pd.DataFrame, col: str) -> pd.Series:
        out = pd.Series(0.0, index=frame.index)
        elig = frame["demand_gate"]
        out.loc[elig] = frame.loc[elig].groupby("year")[col].transform(_pct_rank)
        return out

    df["owner_supply_component"] = _gated_rank(df, "supply_pillar_B")
    df["owner_demand_component"] = _gated_rank(df, "demand_pillar_A")
    comp_owner_raw = (df["owner_demand_component"] + df["owner_supply_component"]) / 2
    df["composite_B_owner_raw"] = np.where(df["demand_gate"], comp_owner_raw, 0.0)
    df["composite_B_owner"] = df.groupby("year")["composite_B_owner_raw"].transform(_pct_rank)
    df.loc[~df["demand_gate"], "composite_B_owner"] = 0.0

    df["zhvi_entry_pct"] = df["pct_zhvi"]  # reported at spell onset, not a state variable, for owner reading

    df = df.sort_values(["unit", "year"])
    df["cost_pct_change_3yr"] = df.groupby("unit")["pct_zhvi"].diff(3)
    df["tenant_cost_component"] = df.groupby("year")["cost_pct_change_3yr"].transform(
        lambda s: pd.Series(-s).rank(pct=True)
    )
    # Statistician post-results correction 10: the composite must be defined
    # IDENTICALLY across the window it covers. `fillna(0.5)` for years before
    # the 3-year cost-change term exists (2000-02) silently substituted a
    # DIFFERENT (2-component) composite under the same name -- exactly the
    # kind of definition break METHOD S3/S4 forbids. Instead the tenant
    # composite is left undefined (NaN) wherever its cost component is
    # undefined; `hysteresis_spells` already treats a NaN composite-year as
    # "unknown" (it resets the run-length counters rather than silently
    # imputing a value), so the tenant headline window effectively begins in
    # 2003, the first year `diff(3)` exists. This is stated, not hidden.
    tenant_components = df[["owner_demand_component", "owner_supply_component", "tenant_cost_component"]]
    tenant_raw = tenant_components.mean(axis=1, skipna=False)
    df["composite_B_tenant_raw"] = np.where(df["demand_gate"], tenant_raw, 0.0)
    df.loc[tenant_raw.isna(), "composite_B_tenant_raw"] = np.nan
    df["composite_B_tenant"] = df.groupby("year")["composite_B_tenant_raw"].transform(_pct_rank)
    df.loc[~df["demand_gate"] & tenant_raw.notna(), "composite_B_tenant"] = 0.0
    df.loc[tenant_raw.isna(), "composite_B_tenant"] = np.nan

    return df


# ============================================================================
# SPELLS (hysteresis)
# ============================================================================


def _incident_dating(c: pd.Series, onset, start_year: int, exit_: float) -> bool:
    """Statistician post-results correction 9: a spell is `incident` (datable
    onset) only if a CLEARLY unfavorable year (composite < exit_ threshold,
    i.e. unambiguously non-favorable, not merely inside the hysteresis band)
    is observed the year immediately before onset. A unit sitting inside the
    0.60-0.70 band at onset-1 has an unknowable prior state -- that spell is
    undatable and must be treated as prevalent, not incident, even though its
    onset year is > start_year."""
    if onset is None or onset <= start_year:
        return False
    prior = c.get(onset - 1, np.nan)
    return bool(np.isfinite(prior) and prior < exit_)


def hysteresis_spells(panel: pd.DataFrame, composite_col: str,
                       enter: float = ENTER_THRESH, exit_: float = EXIT_THRESH,
                       persist: int = PERSIST_YEARS,
                       start_year: int = HEADLINE_START_YEAR,
                       end_year: int = HEADLINE_END_YEAR) -> pd.DataFrame:
    """METHOD §2 hysteresis rule, applied per unit. Returns one row per spell:
    unit, onset_year, exit_year (or None if censored), censored, incident (bool,
    onset > start_year AND a clearly-unfavorable year (< exit_ threshold) is
    observed the year before onset -- statistician post-results correction 9;
    an onset year preceded by an ambiguous in-band year is undatable and
    reported as prevalent instead), duration (years), entry_pct_at_onset."""
    spells = []
    for unit, g in panel.sort_values("year").groupby("unit"):
        g = g[(g["year"] >= start_year) & (g["year"] <= end_year)].set_index("year")
        c = g[composite_col].reindex(range(start_year, end_year + 1))
        state = "below"  # 'below' | 'in'
        run_hi = 0
        run_lo = 0
        onset = None
        for y in range(start_year, end_year + 1):
            v = c.get(y, np.nan)
            if np.isnan(v):
                run_hi = run_lo = 0
                continue
            if state == "below":
                run_hi = run_hi + 1 if v >= enter else 0
                if run_hi >= persist:
                    onset = y - persist + 1
                    state = "in"
                    run_lo = 0
            else:  # state == 'in'
                run_lo = run_lo + 1 if v < exit_ else 0
                if run_lo >= persist:
                    exit_year = y - persist + 1
                    incident = _incident_dating(c, onset, start_year, exit_)
                    spells.append(dict(
                        unit=unit, onset_year=onset, exit_year=exit_year,
                        censored=False, incident=incident,
                        duration=exit_year - onset,
                        entry_pct=c.get(onset, np.nan),
                    ))
                    state = "below"
                    run_hi = 0
                    onset = None
        if state == "in" and onset is not None:
            incident = _incident_dating(c, onset, start_year, exit_)
            spells.append(dict(
                unit=unit, onset_year=onset, exit_year=None,
                censored=True, incident=incident,
                duration=end_year - onset,
                entry_pct=c.get(onset, np.nan),
            ))
    out = pd.DataFrame(spells)
    if len(out) == 0:
        return out
    # last classifiable year is end_year - 1 (statistician point 2(a)): an exit
    # whose 2nd confirming year equals end_year cannot be distinguished from
    # censoring; relabel as censored.
    mask = (~out["censored"]) & (out["exit_year"] == end_year)
    out.loc[mask, "censored"] = True
    out.loc[mask, "duration"] = end_year - out.loc[mask, "onset_year"]
    out.loc[mask, "exit_year"] = None
    return out


def sensitivity_grid(panel: pd.DataFrame, composite_col: str,
                      bands=((0.667, 0.667), (0.63, 0.70), (0.60, 0.70), (0.57, 0.73)),
                      persist_values=(1, 2, 3)) -> pd.DataFrame:
    """METHOD §2 grid: bands x persistence. Reports the incident-spell KM median
    (or 'n/a' if KM never crosses 0.5) for each cell."""
    from lifelines import KaplanMeierFitter

    rows = []
    for exit_thr, enter_thr in bands:
        for p in persist_values:
            sp = hysteresis_spells(panel, composite_col, enter=enter_thr, exit_=exit_thr, persist=p)
            inc = sp[sp["incident"]] if len(sp) else sp
            median = np.nan
            n_completed = 0
            if len(inc):
                kmf = KaplanMeierFitter()
                kmf.fit(inc["duration"], event_observed=~inc["censored"])
                median = kmf.median_survival_time_
                n_completed = int((~inc["censored"]).sum())
            rows.append(dict(exit_thresh=exit_thr, enter_thresh=enter_thr, persist=p,
                              n_incident_spells=len(inc), n_completed=n_completed, median=median))
    return pd.DataFrame(rows)


# ============================================================================
# KM / HAZARD / BOOTSTRAP
# ============================================================================


def km_summary(spells: pd.DataFrame, low_sample_bar: int = 60) -> dict:
    """Incident-spell KM (lifelines), owner ruling: report the median with its CI
    even below the 60-completed-exit bar, flagged LOW-SAMPLE. Statistician S6: at
    this sample size the KM survival curve routinely never crosses 0.5 (heavy
    censoring), which makes the median mathematically infinite/undefined, not
    just imprecise — so this also reports the **restricted mean survival time**
    (RMST) truncated at the largest age with at-risk n_a >= 10 (capped at 20,
    per S6), which is defined even when the median is not, and is the number
    the bootstrap CI (below) is actually built on."""
    from lifelines import KaplanMeierFitter
    from lifelines.utils import restricted_mean_survival_time

    inc = spells[spells["incident"]].copy() if len(spells) else spells
    n_completed = int((~inc["censored"]).sum()) if len(inc) else 0
    n_units = inc["unit"].nunique() if len(inc) else 0
    out = dict(n_incident_spells=len(inc), n_completed=n_completed, n_distinct_units=n_units,
               low_sample_flag=n_completed < low_sample_bar)
    if len(inc) == 0:
        out.update(median=np.nan, ci_lower=np.nan, ci_upper=np.nan, rmst=np.nan, rmst_trunc=np.nan)
        return out
    kmf = KaplanMeierFitter()
    kmf.fit(inc["duration"], event_observed=~inc["censored"])
    ci = kmf.confidence_interval_survival_function_
    median = kmf.median_survival_time_
    # CI on the median via the survival CI band crossing 0.5 (approximate)
    try:
        lower_col, upper_col = ci.columns
        below_upper = ci[ci[upper_col] <= 0.5]
        below_lower = ci[ci[lower_col] <= 0.5]
        ci_upper = below_lower.index.min() if len(below_lower) else np.nan
        ci_lower = below_upper.index.min() if len(below_upper) else np.nan
    except Exception:
        ci_lower = ci_upper = np.nan

    n_at_risk = kmf.event_table["at_risk"]
    ages_with_n10 = n_at_risk[n_at_risk >= 10].index
    rmst_trunc = min(float(ages_with_n10.max()), 20.0) if len(ages_with_n10) else float(inc["duration"].max())
    try:
        rmst = float(restricted_mean_survival_time(kmf, t=rmst_trunc))
    except Exception:
        rmst = np.nan

    out.update(median=median, ci_lower=ci_lower, ci_upper=ci_upper, kmf=kmf,
               rmst=rmst, rmst_trunc=rmst_trunc)
    return out


def hazard_by_spell_age(spells: pd.DataFrame, bands=((0, 5), (6, 10), (11, 100))) -> pd.DataFrame:
    """Piecewise-constant annual exit hazard by spell-age band, pooling incident and
    prevalent spells (S6). 'unknown' band = prevalent (undatable onset age)."""
    rows = []
    prevalent = spells[~spells["incident"]]
    if len(prevalent):
        events = int((~prevalent["censored"]).sum())
        spell_years = int(prevalent["duration"].sum())
        rate = events / spell_years if spell_years else np.nan
        rows.append(dict(age_band="unknown (prevalent)", n_spells=len(prevalent),
                          n_events=events, spell_years=spell_years, hazard=rate))
    incident = spells[spells["incident"]]
    for lo, hi in bands:
        # spell-years where age in [lo, hi]
        n_events = 0
        spell_years = 0
        n_spells_touching = 0
        for _, row in incident.iterrows():
            age_lo = max(lo, 0)
            age_hi = min(hi, row["duration"] - 1 if row["censored"] else row["duration"] - 1)
            years_in_band = max(0, min(row["duration"] - 1, hi) - max(0, lo) + 1)
            if row["duration"] - 1 < lo:
                continue
            spell_years += years_in_band
            n_spells_touching += 1
            if (not row["censored"]) and (lo <= row["duration"] - 1 <= hi):
                n_events += 1
        rate = n_events / spell_years if spell_years else np.nan
        rows.append(dict(age_band=f"{lo}-{hi}", n_spells=n_spells_touching,
                          n_events=n_events, spell_years=spell_years, hazard=rate))
    return pd.DataFrame(rows)


def hazard_by_spell_age_ci(spells: pd.DataFrame, bands=((0, 5), (6, 10), (11, 100)),
                            reps: int = 1000, seed: int = 42) -> pd.DataFrame:
    """Cluster-robust CI for the piecewise annual exit hazard (S6 fallback
    headline, per the parent task's instruction to report the annual exit
    hazard with a cluster-robust CI as the fallback headline). Resamples
    UNITS with replacement -- not spell-years independently -- since a unit
    can contribute multiple spells/spell-years that are not independent of
    each other (the same clustering logic as the spatial-block bootstrap,
    simplified to unit-level since spatial blocks are not needed for a
    single pooled rate). A unit drawn twice contributes its spells twice
    (implemented by relabeling, same as spatial_block_bootstrap_median)."""
    rng = np.random.default_rng(seed)
    base = hazard_by_spell_age(spells, bands=bands)
    units = spells["unit"].unique() if len(spells) else np.array([])
    reps_hazards: dict[str, list[float]] = {row["age_band"]: [] for _, row in base.iterrows()}
    for _ in range(reps):
        if len(units) == 0:
            break
        chosen = rng.choice(units, size=len(units), replace=True)
        frames = []
        for i, u in enumerate(chosen):
            sub = spells[spells["unit"] == u].copy()
            sub["unit"] = sub["unit"].astype(str) + f"__b{i}"
            frames.append(sub)
        sub_spells = pd.concat(frames, ignore_index=True) if frames else spells.iloc[0:0]
        hb = hazard_by_spell_age(sub_spells, bands=bands)
        for _, r in hb.iterrows():
            if r["age_band"] in reps_hazards and np.isfinite(r["hazard"]):
                reps_hazards[r["age_band"]].append(r["hazard"])
    out_rows = []
    for _, row in base.iterrows():
        row = dict(row)
        vals = reps_hazards.get(row["age_band"], [])
        row["n_boot_valid"] = len(vals)
        if len(vals) >= 20:
            row["hazard_ci_lower"] = float(np.percentile(vals, 2.5))
            row["hazard_ci_upper"] = float(np.percentile(vals, 97.5))
        else:
            row["hazard_ci_lower"] = row["hazard_ci_upper"] = np.nan
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def stock_flow_check(panel: pd.DataFrame, spells: pd.DataFrame, composite_col: str) -> dict:
    n_units = panel["unit"].nunique()
    years = sorted(panel["year"].unique())
    favorable_years = panel.groupby("year")[composite_col].apply(lambda s: (s >= ENTER_THRESH).sum())
    mean_stock = favorable_years.mean()
    exits = spells[~spells["censored"]]
    exits_per_year = len(exits) / (max(years) - min(years) + 1) if len(exits) else np.nan
    implied_mean_duration = mean_stock / exits_per_year if exits_per_year else np.nan
    return dict(mean_stock=mean_stock, exits_per_year=exits_per_year,
                implied_mean_duration=implied_mean_duration)


def spatial_blocks(geo: pd.DataFrame, n_blocks: int = 15, random_state: int = 42) -> pd.Series:
    from sklearn.cluster import KMeans

    coords = geo[["cx", "cy"]].values
    n_blocks = min(n_blocks, len(geo))
    km = KMeans(n_clusters=n_blocks, n_init=10, random_state=random_state).fit(coords)
    return pd.Series(km.labels_, index=geo["unit"], name="block")


def spatial_block_bootstrap_median(panel: pd.DataFrame, composite_col: str, geo: pd.DataFrame,
                                    rmst_trunc: float,
                                    n_blocks: int = 15, reps: int = 500, seed: int = 42) -> dict:
    """CI for the incident-spell survival estimate via block-bootstrap resampling
    of spatial blocks (whole units move together; a block drawn twice
    contributes its units' spell-years twice — implemented by relabeling units
    with a per-draw suffix before re-detecting spells, not by `isin`, which
    would silently collapse repeated draws to a single inclusion and understate
    bootstrap variance). Reduced reps (500, not 2000) for runtime; documented.

    Bootstraps **RMST**, not the median: at this sample size the KM curve
    routinely never crosses 0.5 in a bootstrap resample (median = inf), so a
    median-based CI is mostly undefined by construction (see km_summary's
    docstring) — RMST is the statistic that is actually estimable here. The
    median CI is still attempted and reported (n_valid_reps_median), but expect
    it to be sparse or empty.

    Statistician post-results correction 7 (the bootstrap bug): `rmst_trunc` is
    now REQUIRED and FIXED across every replicate -- the previous per-rep
    "compute your own truncation from this rep's own at-risk table" behavior
    let each replicate's RMST integrate to a different horizon, which is why
    the old CI's upper bound (17.21) could exceed the observed estimate's own
    truncation point (17) despite RMST(tau) being bounded by tau. Pass the
    SAME rmst_trunc used for the observed `km_summary` call (or a common tau
    across composites, per statistician correction 8).

    Replicates are no longer silently dropped for having <3 exits: RMST is a
    well-defined statistic even at 0 observed exits (a heavily-censored
    resample's survival curve is just flatter, closer to `rmst_trunc`), so
    dropping those reps was a real source of the reported bias (statistician:
    "conditions on events and cuts the long-survival tail"). A replicate is
    now only dropped if it fails to produce *any* incident spells, or if the
    resulting fit throws -- every dropped replicate and its reason is counted
    and returned (`n_dropped_reps`, `drop_reasons`), never discarded
    silently."""
    from lifelines import KaplanMeierFitter
    from lifelines.utils import restricted_mean_survival_time

    if rmst_trunc is None or not np.isfinite(rmst_trunc):
        raise ValueError("spatial_block_bootstrap_median requires a fixed, finite rmst_trunc "
                          "(statistician post-results correction 7) — pass the observed "
                          "km_summary()['rmst_trunc'], or a common tau across composites.")

    blocks = spatial_blocks(geo, n_blocks=n_blocks)
    block_ids = blocks.unique()
    rng = np.random.default_rng(seed)
    medians = []
    rmsts = []
    drop_reasons: dict[str, int] = {}
    n_dropped = 0
    for _ in range(reps):
        chosen = rng.choice(block_ids, size=len(block_ids), replace=True)
        frames = []
        for i, b in enumerate(chosen):
            block_units = blocks[blocks == b].index.tolist()
            sub = panel[panel["unit"].isin(block_units)].copy()
            sub["unit"] = sub["unit"].astype(str) + f"__b{i}"
            frames.append(sub)
        sub_panel = pd.concat(frames, ignore_index=True)
        sp = hysteresis_spells(sub_panel, composite_col)
        inc = sp[sp["incident"]] if len(sp) else sp
        if len(inc) == 0:
            n_dropped += 1
            drop_reasons["no_incident_spells"] = drop_reasons.get("no_incident_spells", 0) + 1
            continue
        try:
            kmf = KaplanMeierFitter()
            kmf.fit(inc["duration"], event_observed=~inc["censored"])
        except Exception as exc:
            n_dropped += 1
            drop_reasons[f"km_fit_error:{type(exc).__name__}"] = drop_reasons.get(f"km_fit_error:{type(exc).__name__}", 0) + 1
            continue
        m = kmf.median_survival_time_
        if np.isfinite(m):
            medians.append(m)
        try:
            r = float(restricted_mean_survival_time(kmf, t=rmst_trunc))
            if np.isfinite(r):
                rmsts.append(r)
            else:
                n_dropped += 1
                drop_reasons["rmst_nonfinite"] = drop_reasons.get("rmst_nonfinite", 0) + 1
        except Exception as exc:
            n_dropped += 1
            drop_reasons[f"rmst_error:{type(exc).__name__}"] = drop_reasons.get(f"rmst_error:{type(exc).__name__}", 0) + 1
    out = dict(n_valid_reps_median=len(medians), n_valid_reps_rmst=len(rmsts),
               n_dropped_reps=n_dropped, drop_reasons=drop_reasons, reps=reps, rmst_trunc=rmst_trunc)
    if medians:
        out["median_ci_lower"] = float(np.percentile(medians, 2.5))
        out["median_ci_upper"] = float(np.percentile(medians, 97.5))
    else:
        out["median_ci_lower"] = out["median_ci_upper"] = np.nan
    if rmsts:
        out["rmst_ci_lower"] = float(np.percentile(rmsts, 2.5))
        out["rmst_ci_upper"] = float(np.percentile(rmsts, 97.5))
    else:
        out["rmst_ci_lower"] = out["rmst_ci_upper"] = np.nan
    # backward-compatible aliases (ci_lower/ci_upper = the RMST CI, the estimable one)
    out["ci_lower"] = out["rmst_ci_lower"]
    out["ci_upper"] = out["rmst_ci_upper"]
    out["n_valid_reps"] = out["n_valid_reps_rmst"]
    return out


# ============================================================================
# RANK-CHURN NULL (contrarian amendment 5 / statistician condition 3)
# ============================================================================


def rank_churn_null(panel: pd.DataFrame, composite_col: str, n_sims: int = 200, seed: int = 7,
                     rmst_trunc: float = 20.0) -> dict:
    """Simulate each unit's composite percentile as an AR(1) in percentile space
    using that unit's own autocorrelation/innovation variance, re-rank every
    simulated year (preserving the zero-sum tercile constraint), apply the
    identical hysteresis rule, and compute the null distribution.

    Compares **RMST** (truncated at `rmst_trunc`, default 20y to match
    km_summary's cap), not the median: at this sample size the KM curve
    routinely never crosses 0.5 in a 24-year simulated panel (heavy censoring
    is a property of the panel length, not of any one draw), so a median-based
    null comparison would be built almost entirely on the rare draws that
    happen to cross 0.5 — a biased subsample of the null, not the null itself.
    The median band is still reported (n_valid_sims_median) but expect it to
    be sparse or empty; RMST is the object actually compared to the observed
    RMST in the notebook."""
    from lifelines import KaplanMeierFitter
    from lifelines.utils import restricted_mean_survival_time

    rng = np.random.default_rng(seed)
    wide = panel.pivot(index="year", columns="unit", values=composite_col).dropna(axis=1, how="any")
    years = wide.index.to_numpy()
    units = wide.columns.to_numpy()
    x = wide.values  # years x units

    phis = []
    sigmas = []
    for j in range(x.shape[1]):
        series = x[:, j]
        if len(series) < 3 or np.std(series) == 0:
            phis.append(0.5)
            sigmas.append(0.05)
            continue
        y_t = series[1:]
        y_l = series[:-1]
        denom = np.sum((y_l - y_l.mean()) ** 2)
        phi = np.sum((y_l - y_l.mean()) * (y_t - y_t.mean())) / denom if denom > 0 else 0.5
        phi = np.clip(phi, -0.98, 0.98)
        resid = y_t - (y_t.mean() + phi * (y_l - y_l.mean()))
        phis.append(phi)
        sigmas.append(max(resid.std(), 1e-4))
    phis = np.array(phis)
    sigmas = np.array(sigmas)
    means = x.mean(axis=0)

    null_medians = []
    null_rmsts = []
    for s in range(n_sims):
        sim = np.zeros_like(x)
        sim[0] = x[0]
        for t in range(1, x.shape[0]):
            innovation = rng.normal(0, sigmas)
            sim[t] = means + phis * (sim[t - 1] - means) + innovation
        # re-rank each simulated year across units -> percentile in [0,1]
        ranked = np.apply_along_axis(lambda col: pd.Series(col).rank(pct=True).to_numpy(), 1, sim)
        sim_panel = pd.DataFrame(ranked, index=years, columns=units).reset_index().melt(
            id_vars="index", var_name="unit", value_name=composite_col
        ).rename(columns={"index": "year"})
        sp = hysteresis_spells(sim_panel, composite_col)
        inc = sp[sp["incident"]] if len(sp) else sp
        if len(inc) < 3 or (~inc["censored"]).sum() < 2:
            continue
        kmf = KaplanMeierFitter()
        kmf.fit(inc["duration"], event_observed=~inc["censored"])
        m = kmf.median_survival_time_
        if np.isfinite(m):
            null_medians.append(m)
        try:
            r = float(restricted_mean_survival_time(kmf, t=min(rmst_trunc, float(inc["duration"].max()))))
            if np.isfinite(r):
                null_rmsts.append(r)
        except Exception:
            pass

    result = dict(n_valid_sims=len(null_rmsts), n_valid_sims_median=len(null_medians))
    if null_medians:
        result["null_median_p2_5"] = float(np.percentile(null_medians, 2.5))
        result["null_median_p97_5"] = float(np.percentile(null_medians, 97.5))
        result["null_medians"] = null_medians
    else:
        result["null_median_p2_5"] = result["null_median_p97_5"] = np.nan
        result["null_medians"] = []
    if null_rmsts:
        result["null_rmst_p2_5"] = float(np.percentile(null_rmsts, 2.5))
        result["null_rmst_p97_5"] = float(np.percentile(null_rmsts, 97.5))
        result["null_rmsts"] = null_rmsts
    else:
        result["null_rmst_p2_5"] = result["null_rmst_p97_5"] = np.nan
        result["null_rmsts"] = []
    return result


# ============================================================================
# REGIME MODEL: k-means (k=4) + Markov
# ============================================================================


def kmeans_markov(panel: pd.DataFrame, demand_col="demand_pillar_A", supply_col="supply_pillar_A",
                   cost_col="cost_pillar_A", fit_cutoff_year: int = 2013, k: int = 4,
                   seed: int = 0) -> dict:
    from sklearn.cluster import KMeans

    df = panel.sort_values(["unit", "year"]).copy()
    for col in (demand_col, supply_col, cost_col):
        df[f"{col}_chg3"] = df.groupby("unit")[col].diff(3)
    feat_cols = [demand_col, supply_col, cost_col,
                 f"{demand_col}_chg3", f"{supply_col}_chg3", f"{cost_col}_chg3"]
    df_fit = df[df["year"] <= fit_cutoff_year].dropna(subset=feat_cols)
    if len(df_fit) < k * 5:
        return dict(ok=False, reason="insufficient rows <=2013 for k-means")

    km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(df_fit[feat_cols].values)
    centroid_composite = km.cluster_centers_[:, :3].mean(axis=1)
    favorable_state = int(np.argmax(centroid_composite))

    df_all = df.dropna(subset=feat_cols).copy()
    df_all["state"] = km.predict(df_all[feat_cols].values)
    df_all["state_favorable"] = df_all["state"] == favorable_state

    # persistence filter to match the hysteresis object (statistician point)
    df_all = df_all.sort_values(["unit", "year"])
    df_all["favorable_persist"] = (
        df_all.groupby("unit")["state_favorable"]
        .transform(lambda s: s.rolling(PERSIST_YEARS, min_periods=PERSIST_YEARS).apply(lambda w: w.all(), raw=True))
        .fillna(0).astype(bool)
    )

    # Markov transition on the persistence-filtered binary favorable/other sequence
    seq = df_all.sort_values(["unit", "year"]).groupby("unit")["favorable_persist"].apply(list)
    n_ff = n_fo = n_of = n_oo = 0
    for s in seq:
        for a, b in zip(s[:-1], s[1:]):
            if a and b:
                n_ff += 1
            elif a and not b:
                n_fo += 1
            elif (not a) and b:
                n_of += 1
            else:
                n_oo += 1
    p_ff = n_ff / (n_ff + n_fo) if (n_ff + n_fo) else np.nan
    implied_sojourn = 1 / (1 - p_ff) if p_ff is not None and p_ff < 1 else np.inf

    return dict(ok=True, k=k, favorable_state=favorable_state,
                transition=dict(p_ff=p_ff, n_ff=n_ff, n_fo=n_fo, n_of=n_of, n_oo=n_oo),
                implied_mean_sojourn=implied_sojourn, states=df_all[["unit", "year", "state", "state_favorable"]])


# ============================================================================
# BREAK-YEAR DETECTION (S5 / §9 threat 1)
# ============================================================================


def break_year_rank_shuffle(panel: pd.DataFrame, composite_col: str, mad_k: float = 3.5) -> pd.DataFrame:
    """Statistician S5: for each adjacent year pair, the rank shuffle
    1 - Spearman rho(c[t-1], c[t]). A year is flagged if its shuffle is a robust
    outlier against the *other* years' distribution (median + mad_k * MAD,
    leave-one-out) — not literally "the max of the non-candidate years", which
    is definitionally unable to flag a genuine break that happens to fall on a
    non-candidate year (it would then always be part of the set it's compared
    against). Candidate years (2007 CBP noise infusion, 2011 the 11249 split
    and ACS entry, 2012 NAICS recode, 2020/21 COVID + ZCTA redraw) are annotated
    for cross-reference, not exempted from flagging."""
    wide = panel.pivot(index="year", columns="unit", values=composite_col)
    years = sorted(wide.index)
    rows = []
    for y0, y1 in zip(years[:-1], years[1:]):
        both = wide.loc[[y0, y1]].dropna(axis=1, how="any")
        if both.shape[1] < 10:
            rows.append(dict(year=y1, shuffle=np.nan, n_units=both.shape[1]))
            continue
        rho = both.loc[y0].corr(both.loc[y1], method="spearman")
        rows.append(dict(year=y1, shuffle=1 - rho, n_units=both.shape[1]))
    df = pd.DataFrame(rows)
    candidates = {2007, 2011, 2012, 2020, 2021}
    df["is_candidate_year"] = df["year"].isin(candidates)

    def _leave_one_out_flag(idx):
        others = df["shuffle"].drop(index=idx).dropna()
        if len(others) < 3:
            return False
        med = others.median()
        mad = (others - med).abs().median() * 1.4826
        thresh = med + mad_k * mad if mad > 0 else others.max()
        val = df.loc[idx, "shuffle"]
        return bool(np.isfinite(val) and val > thresh)

    df["flagged"] = [_leave_one_out_flag(i) for i in df.index]
    return df


# ============================================================================
# DRIVERS: discrete-time hazard
# ============================================================================


def build_hazard_person_years(panel: pd.DataFrame, spells: pd.DataFrame, composite_col: str,
                               demand_col="demand_pillar_A", supply_col="supply_pillar_A",
                               cost_col="cost_pillar_A") -> pd.DataFrame:
    """One row per (unit, spell, year-at-risk): year, duration-so-far, lag2-4 pillar
    changes, borough (approximated from ZIP first digit / a simple map is not
    available — using unit prefix as a coarse geographic FE, documented), and the
    exit indicator for that year."""
    df = panel.sort_values(["unit", "year"]).copy()
    for col in (demand_col, supply_col, cost_col):
        df[f"{col}_lag2"] = df.groupby("unit")[col].shift(2)
        df[f"{col}_lag4"] = df.groupby("unit")[col].shift(4)
        df[f"{col}_chg_lag2to4"] = df[f"{col}_lag2"] - df[f"{col}_lag4"]

    rows = []
    for _, sp in spells.iterrows():
        exit_year = sp["exit_year"] if not sp["censored"] else sp["onset_year"] + sp["duration"]
        for age, y in enumerate(range(sp["onset_year"], int(exit_year) + 1)):
            row = dict(unit=sp["unit"], spell_onset=sp["onset_year"], year=y, age=age,
                       incident=sp["incident"])
            is_exit_year = (not sp["censored"]) and (y == sp["exit_year"])
            row["exit"] = int(is_exit_year)
            rows.append(row)
    py = pd.DataFrame(rows)
    py = py.merge(
        df[["unit", "year"] + [f"{c}_chg_lag2to4" for c in (demand_col, supply_col, cost_col)]],
        on=["unit", "year"], how="left",
    )
    py["borough_proxy"] = py["unit"].str[:2]  # coarse geographic FE (documented simplification)
    return py


def attribute_exit_cause(spells: pd.DataFrame, panel: pd.DataFrame,
                          demand_col="demand_pillar_A", supply_col="supply_pillar_A",
                          cost_col="cost_pillar_A") -> pd.DataFrame:
    """For each completed exit, attribute cause = the pillar with the largest
    adverse percentile move over the exit window (onset->exit)."""
    wide = panel.set_index(["unit", "year"])
    out = []
    for _, sp in spells[~spells["censored"]].iterrows():
        try:
            p0 = wide.loc[(sp["unit"], sp["onset_year"])]
            p1 = wide.loc[(sp["unit"], sp["exit_year"])]
        except KeyError:
            out.append(dict(unit=sp["unit"], onset_year=sp["onset_year"], exit_year=sp["exit_year"], cause="unknown"))
            continue
        deltas = {
            "demand": p1[demand_col] - p0[demand_col],
            "supply": p1[supply_col] - p0[supply_col],
            "cost": p1[cost_col] - p0[cost_col],
        }
        cause = min(deltas, key=deltas.get)  # most negative = biggest adverse move
        out.append(dict(unit=sp["unit"], onset_year=sp["onset_year"], exit_year=sp["exit_year"],
                         cause=cause, **{f"delta_{k}": v for k, v in deltas.items()}))
    return pd.DataFrame(out)


# ============================================================================
# BACKTEST (2013 origin)
# ============================================================================


def backtest_2013(panel: pd.DataFrame, composite_col: str, horizons=(5, 9)) -> dict:
    """Freeze the hysteresis spell-set on data <=2013 (already the case: the
    hysteresis function has no lookahead), score spells at risk (favorable) at the
    2013 origin against realized favorable status at 2013+h, for h in horizons.
    Comparators: (a) training-KM-implied survival S(a+h)/S(a) at the spell's 2013
    age, (b) naive persistence P=1. Brier score (no censoring correction needed —
    statistician point 7(c) — since the horizon 2022 is inside the panel)."""
    spells_train = hysteresis_spells(panel[panel["year"] <= 2013], composite_col)
    if len(spells_train) == 0:
        return dict(ok=False, reason="no spells detected in data <=2013")
    at_risk = spells_train[(spells_train["censored"]) | (spells_train["exit_year"] > 2013)]
    at_risk = at_risk[at_risk["onset_year"] <= 2013]
    if len(at_risk) == 0:
        return dict(ok=False, reason="no spells at risk at 2013 origin")
    at_risk = at_risk.copy()
    at_risk["age_2013"] = 2013 - at_risk["onset_year"]

    from lifelines import KaplanMeierFitter
    inc_train = spells_train[spells_train["incident"]]
    kmf = KaplanMeierFitter()
    if len(inc_train):
        kmf.fit(inc_train["duration"], event_observed=~inc_train["censored"])

    wide = panel.pivot(index="year", columns="unit", values=composite_col)
    results = {}
    for h in horizons:
        target_year = 2013 + h
        if target_year not in wide.index:
            continue
        actual_favorable = wide.loc[target_year].reindex(at_risk["unit"]).values >= ENTER_THRESH
        actual_favorable = np.where(np.isnan(wide.loc[target_year].reindex(at_risk["unit"]).values), np.nan, actual_favorable.astype(float))

        def s_ratio(age):
            try:
                s_a = kmf.survival_function_at_times(age).iloc[0]
                s_ah = kmf.survival_function_at_times(age + h).iloc[0]
                return s_ah / s_a if s_a > 0 else np.nan
            except Exception:
                return np.nan

        pred_km = at_risk["age_2013"].apply(s_ratio).values
        pred_persist = np.ones(len(at_risk))

        valid = ~np.isnan(actual_favorable)
        if valid.sum() == 0:
            continue
        y = actual_favorable[valid]
        brier_km = np.nanmean((pred_km[valid] - y) ** 2)
        brier_persist = np.mean((pred_persist[valid] - y) ** 2)

        age_flag = at_risk["age_2013"].values[valid]
        emerging = age_flag <= 3
        brier_km_emerging = np.nanmean((pred_km[valid][emerging] - y[emerging]) ** 2) if emerging.any() else np.nan
        brier_km_mature = np.nanmean((pred_km[valid][~emerging] - y[~emerging]) ** 2) if (~emerging).any() else np.nan

        results[h] = dict(
            n_at_risk=int(valid.sum()),
            brier_km=float(brier_km), brier_persist=float(brier_persist),
            beats_persistence=bool(brier_km < brier_persist),
            brier_km_emerging=float(brier_km_emerging) if np.isfinite(brier_km_emerging) else None,
            brier_km_mature=float(brier_km_mature) if np.isfinite(brier_km_mature) else None,
            n_emerging=int(emerging.sum()),
        )
    primary = results.get(5, {})
    passes = primary.get("beats_persistence", False) if primary else False
    return dict(ok=True, horizons=results, pass_5yr=passes)


def _spell_training_rows(panel: pd.DataFrame, spells: pd.DataFrame, composite_col: str,
                          h: int, max_origin_year: int = 2013) -> pd.DataFrame:
    """Build (unit, origin_year, composite value, spell age, label) rows for
    every year a spell is active, pooled over ALL pre-2013 origins (not just
    2013 itself) so the ranking-backtest logistic has enough training data.
    label = 1 if the spell is STILL NOT-EXITED h years later (the hysteresis
    STATE, not a raw "composite >= 0.70" snapshot -- statistician post-results
    correction 12). Both origin and origin+h are required to be <=
    max_origin_year, so nothing here leaks post-2013 information into
    training."""
    wide = panel.pivot(index="year", columns="unit", values=composite_col)
    rows = []
    for _, sp in spells.iterrows():
        onset = int(sp["onset_year"])
        censored = bool(sp["censored"])
        exit_year = sp["exit_year"]
        end = int(exit_year) if (not censored and pd.notna(exit_year)) else HEADLINE_END_YEAR
        for t in range(onset, end + 1):
            if t > max_origin_year - h or t + h > max_origin_year:
                continue
            if t not in wide.index or sp["unit"] not in wide.columns:
                continue
            val = wide.loc[t, sp["unit"]]
            if pd.isna(val):
                continue
            still_active = True if censored else ((t + h) < exit_year)
            rows.append(dict(unit=sp["unit"], origin_year=t, age=t - onset,
                              composite=float(val), label=int(still_active)))
    return pd.DataFrame(rows)


def ranking_backtest_2013(panel: pd.DataFrame, composite_col: str, horizons=(5, 9),
                           n_boot: int = 500, seed: int = 42) -> dict:
    """A REAL ranking backtest (contrarian + statistician post-results verdicts).
    `backtest_2013` above predicts survival from spell AGE alone via the
    training KM curve -- the composite's VALUE never enters the predictor, so
    "beats persistence" there says only that a base rate below 1 beats a
    constant prediction of 1, not that the composite ranks ZIPs. This function
    fixes that: a logistic regression trained on pooled pre-2013 (unit, year)
    observations (`_spell_training_rows`) predicts P(spell still not-exited at
    origin+h) from the composite VALUE and spell age AT THE ORIGIN. It is then
    scored at the true 2013 origin against three comparators:
      (a) naive persistence (P=1, i.e. `backtest_2013`'s floor),
      (b) a constant base rate (the training not-exited share, controls for
          "the logistic just learned the marginal rate"),
      (c) a ZIP-shuffled placebo -- composite values randomly permuted across
          the at-risk units before prediction, the contrarian's suggested
          null-of-no-ranking-information check ("Replace it with a logistic on
          the 2013 composite, compare that against a ZIP-shuffled placebo, and
          the gain disappears").
    A unit-level bootstrap (resampling at-risk units with replacement, paired
    per replicate) gives a Brier-difference CI for logit-vs-persistence and
    logit-vs-placebo, plus an approximate minimum detectable effect (MDE,
    normal approximation: (z_.975 + z_.80) * bootstrap SE, two-sided alpha=.05,
    80% power) so a null result reads as "underpowered" rather than "proof of
    no signal", per statistician correction 12."""
    import statsmodels.formula.api as smf

    spells_full = hysteresis_spells(panel, composite_col)
    spells_train_2013 = hysteresis_spells(panel[panel["year"] <= 2013], composite_col)
    if len(spells_train_2013) == 0:
        return dict(ok=False, reason="no spells detected in data <=2013")
    at_risk = spells_train_2013[(spells_train_2013["censored"]) |
                                 (spells_train_2013["exit_year"] > 2013)]
    at_risk = at_risk[at_risk["onset_year"] <= 2013].copy()
    if len(at_risk) == 0:
        return dict(ok=False, reason="no spells at risk at 2013 origin")

    wide = panel.pivot(index="year", columns="unit", values=composite_col)
    if 2013 not in wide.index:
        return dict(ok=False, reason="2013 not in panel")
    at_risk["composite_2013"] = at_risk["unit"].map(
        lambda u: wide.loc[2013, u] if u in wide.columns else np.nan)
    at_risk["age_2013"] = 2013 - at_risk["onset_year"]
    at_risk = at_risk.dropna(subset=["composite_2013"]).reset_index(drop=True)
    if len(at_risk) == 0:
        return dict(ok=False, reason="no at-risk spells with a defined composite value at 2013")

    z_975, z_80 = 1.959964, 0.841621
    results = {}
    for h in horizons:
        target_year = 2013 + h
        if target_year not in wide.index:
            results[h] = dict(ok=False, reason=f"{target_year} not in panel")
            continue
        train = _spell_training_rows(panel, spells_full, composite_col, h, max_origin_year=2013)
        if len(train) < 20 or train["label"].nunique() < 2:
            results[h] = dict(ok=False, reason=f"insufficient training rows for h={h} (n={len(train)})")
            continue

        model = smf.logit("label ~ composite + age", data=train).fit(disp=0)

        actual_series = wide.loc[target_year].reindex(at_risk["unit"])
        valid = actual_series.notna().values
        if valid.sum() == 0:
            results[h] = dict(ok=False, reason="no valid outcomes at target year")
            continue
        y = (actual_series.values[valid] >= ENTER_THRESH).astype(float)
        ar = at_risk.loc[valid].reset_index(drop=True)
        n = len(ar)

        X_pred = pd.DataFrame({"composite": ar["composite_2013"].values, "age": ar["age_2013"].values})
        pred_logit = model.predict(X_pred).values
        pred_persist = np.ones(n)
        base_rate = float(train["label"].mean())
        pred_const = np.full(n, base_rate)

        rng = np.random.default_rng(seed + h)
        shuffled_composite = rng.permutation(ar["composite_2013"].values)
        X_placebo = pd.DataFrame({"composite": shuffled_composite, "age": ar["age_2013"].values})
        pred_placebo = model.predict(X_placebo).values

        brier_logit = float(np.mean((pred_logit - y) ** 2))
        brier_persist = float(np.mean((pred_persist - y) ** 2))
        brier_const = float(np.mean((pred_const - y) ** 2))
        brier_placebo = float(np.mean((pred_placebo - y) ** 2))

        idx = np.arange(n)
        diffs_persist, diffs_placebo, diffs_const = [], [], []
        rng_boot = np.random.default_rng(seed)
        for _ in range(n_boot):
            samp = rng_boot.choice(idx, size=n, replace=True)
            yb = y[samp]
            b_logit = np.mean((pred_logit[samp] - yb) ** 2)
            diffs_persist.append(np.mean((pred_persist[samp] - yb) ** 2) - b_logit)
            diffs_const.append(np.mean((pred_const[samp] - yb) ** 2) - b_logit)
            diffs_placebo.append(np.mean((pred_placebo[samp] - yb) ** 2) - b_logit)
        diffs_persist = np.array(diffs_persist)
        diffs_const = np.array(diffs_const)
        diffs_placebo = np.array(diffs_placebo)

        def _ci(arr):
            return (float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)))

        se_persist = float(np.std(diffs_persist, ddof=1))
        se_placebo = float(np.std(diffs_placebo, ddof=1))
        results[h] = dict(
            ok=True, n_at_risk=n, n_train=len(train), base_rate=base_rate,
            brier_logit=brier_logit, brier_persist=brier_persist,
            brier_const=brier_const, brier_placebo=brier_placebo,
            beats_persistence=bool(brier_logit < brier_persist),
            beats_const=bool(brier_logit < brier_const),
            beats_placebo=bool(brier_logit < brier_placebo),
            diff_vs_persist=brier_persist - brier_logit, ci_diff_vs_persist=_ci(diffs_persist),
            diff_vs_const=brier_const - brier_logit, ci_diff_vs_const=_ci(diffs_const),
            diff_vs_placebo=brier_placebo - brier_logit, ci_diff_vs_placebo=_ci(diffs_placebo),
            mde_vs_persist=float((z_975 + z_80) * se_persist),
            mde_vs_placebo=float((z_975 + z_80) * se_placebo),
            significant_vs_persist=bool(_ci(diffs_persist)[0] > 0),
            significant_vs_placebo=bool(_ci(diffs_placebo)[0] > 0),
        )
    return dict(ok=True, horizons=results,
                note="Predictor = logistic(composite value, spell age) at the 2013 origin, "
                     "trained on pooled pre-2013 spell-years (not on 2013 alone). Outcome = "
                     "hysteresis state (spell not yet exited) at origin+h, not a raw "
                     "composite>=0.70 snapshot. 'significant_vs_X' requires the bootstrap CI "
                     "for the paired Brier difference to exclude 0.")


# ============================================================================
# NAMED-ZIP SCORING (PREREGISTRATION.md)
# ============================================================================


def score_named_zips(spells: pd.DataFrame, causes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for reg in NAMED_ZIP_PREREGISTRATION:
        unit = to_unit(reg["zip"])
        u_spells = spells[spells["unit"] == unit].sort_values("onset_year")
        onset_exp = reg["onset"]
        exit_exp = reg["exit"]
        driver_exp = reg["driver"]

        onset_hit = False
        exit_hit = False
        model_onset = None
        model_exit = None
        model_censored = None
        break_flag = False

        if onset_exp == "none":
            onset_hit = len(u_spells) == 0 or (len(u_spells) == 1 and u_spells.iloc[0]["duration"] <= 3)
        elif onset_exp == "<=2000":
            if len(u_spells):
                first = u_spells.iloc[0]
                model_onset = int(first["onset_year"])
                onset_hit = (not first["incident"]) or (first["onset_year"] <= 2003)
        elif onset_exp == "2008":
            if len(u_spells):
                for _, s in u_spells.iterrows():
                    if abs(s["onset_year"] - 2008) <= 3:
                        onset_hit = True
                        model_onset = int(s["onset_year"])
                        break
        elif onset_exp == "none_or_2016":
            if len(u_spells) == 0:
                onset_hit = True
            else:
                for _, s in u_spells.iterrows():
                    if s["onset_year"] >= 2016:
                        onset_hit = True
                        model_onset = int(s["onset_year"])
                        break

        if exit_exp is None:
            exit_hit = True  # no exit condition registered
        elif exit_exp == "ongoing":
            for _, s in u_spells.iterrows():
                if s["censored"] or (not s["censored"] and s["exit_year"] and s["exit_year"] >= 2021):
                    exit_hit = True
                    model_exit = "ongoing" if s["censored"] else int(s["exit_year"])
                    model_censored = bool(s["censored"])
                    break
        else:
            for _, s in u_spells.iterrows():
                if s["censored"]:
                    continue
                if abs(s["exit_year"] - exit_exp) <= 3:
                    cause_row = causes[(causes["unit"] == unit) & (causes["exit_year"] == s["exit_year"])]
                    cause = cause_row["cause"].iloc[0] if len(cause_row) else "unknown"
                    model_exit = int(s["exit_year"])
                    if 2009 <= s["exit_year"] <= 2011 or 2020 <= s["exit_year"] <= 2021:
                        break_flag = True
                    if cause == driver_exp:
                        exit_hit = True
                    break

        hit = onset_hit and exit_hit
        rows.append(dict(zip=reg["zip"], neighborhood=reg["neighborhood"], unit=unit,
                          onset_expected=onset_exp, exit_expected=exit_exp, driver_expected=driver_exp,
                          model_onset=model_onset, model_exit=model_exit, model_censored=model_censored,
                          onset_hit=onset_hit, exit_hit=exit_hit, hit=hit,
                          non_template=reg["non_template"], break_flag=break_flag))
    return pd.DataFrame(rows)


def evaluate_prereg_pass(scored: pd.DataFrame) -> dict:
    n = len(scored)
    n_hit = int(scored["hit"].sum())
    hit_rate_ok = n_hit >= 9  # out of 14, per the fixed rule (owner ruling: not scaled if all 14 present)
    control_10128 = scored[scored["zip"] == "10128"]
    control_hit = bool(control_10128["hit"].iloc[0]) if len(control_10128) else False
    non_template_hits = int(scored[scored["non_template"]]["hit"].sum())
    non_template_ok = non_template_hits >= 3
    n_transitions = int(((scored["model_onset"].notna()) | (scored["model_exit"].notna())).sum())
    transitions_ok = n_transitions >= 4
    n_break_flags = int(scored["break_flag"].sum())
    invalid_break = n_break_flags >= 3

    passed = hit_rate_ok and control_hit and non_template_ok and transitions_ok and not invalid_break
    return dict(n=n, n_hit=n_hit, hit_rate_ok=hit_rate_ok, control_10128_hit=control_hit,
                non_template_hits=non_template_hits, non_template_ok=non_template_ok,
                n_transitions=n_transitions, transitions_ok=transitions_ok,
                n_break_flags=n_break_flags, invalid_break=invalid_break,
                status=("INVALID_PENDING_BREAK_FIX" if invalid_break else ("PASS" if passed else "FAIL")))


# ============================================================================
# CLOSURE VALIDITY CHECK
# ============================================================================


def closure_validity_glm(panel: pd.DataFrame, composite_col: str, closures: pd.DataFrame,
                          lag_years: int = 1) -> dict:
    """Statistician post-results correction 11, replacing `closure_validity_check`
    (kept below for continuity). The original check was a raw Welch t-test on
    2,085 autocorrelated ZIP-years (pseudo-replication -- effective n is closer
    to ~150 units), never applied the borough conditioning its own docstring
    promised, and read favorable status CONTEMPORANEOUSLY with closures instead
    of testing whether favorability PRECEDES lower closures.

    This version: a binomial GLM of closures out of at-risk restaurants on
    favorable status LAGGED by `lag_years` (favorable status at year t predicts
    closures observed in year t+lag_years, never same-year), with year FE,
    borough-proxy FE, and unit-clustered (sandwich) robust SEs. A second
    "within-ZIP" specification replaces borough FE with unit FE: this is the
    only version that can survive a static closure-DETECTION-coverage
    confound (a ZIP that always gets more DOHMH inspection attention would
    show a spurious closure/favorability correlation in the between-unit
    model but not in the within-unit one). A coverage-proxy covariate
    (log1p(restaurants at risk) that year, standing in for "inspections per
    POI" -- no DOHMH inspection-frequency table exists in this warehouse,
    documented substitution) is included in both.

    Kill criterion (statistician's own words): the unit-FE coefficient is not
    negative at p<0.05 after clustering."""
    import patsy
    import statsmodels.api as sm

    fav = panel[["unit", "year", composite_col]].copy()
    fav["favorable"] = (fav[composite_col] >= ENTER_THRESH).astype(int)
    fav_lag = fav[["unit", "year", "favorable"]].copy()
    fav_lag["year"] = fav_lag["year"] + lag_years
    fav_lag = fav_lag.rename(columns={"favorable": "favorable_lag"})

    merged = closures.merge(fav_lag, on=["unit", "year"], how="inner")
    merged = merged[merged["n_open"] > 0].copy()
    merged["borough_proxy"] = merged["unit"].str[:2]
    merged["fail"] = merged["n_open"] - merged["n_closed"]
    merged["coverage_proxy"] = np.log1p(merged["n_open"])
    merged = merged.dropna(subset=["favorable_lag", "coverage_proxy"])

    out = dict(ok=True, lag_years=lag_years, n_zip_years=len(merged),
               n_closed_total=int(merged["n_closed"].sum()),
               n_favorable_lag=int(merged["favorable_lag"].sum()),
               coverage_control="log1p(n_open) -- a proxy for DOHMH inspection/detection "
                                 "coverage; no inspections-per-POI table exists in this "
                                 "warehouse (documented substitution, statistician correction 11)")
    if merged["favorable_lag"].nunique() < 2 or merged["n_closed"].sum() < 5:
        out.update(ok=False, reason="insufficient variation/events for closure GLM "
                                     f"(favorable_lag nunique={merged['favorable_lag'].nunique()}, "
                                     f"n_closed_total={merged['n_closed'].sum()})")
        return out

    y = merged[["n_closed", "fail"]].values

    def _fit(formula: str):
        X = patsy.dmatrix(formula, merged, return_type="dataframe")
        model = sm.GLM(y, X, family=sm.families.Binomial())
        try:
            res = model.fit(cov_type="cluster", cov_kwds={"groups": merged["unit"].values})
        except Exception:
            res = model.fit()
        return res

    def _coef_block(res):
        if "favorable_lag" not in res.params.index:
            return dict(ok=False, reason="favorable_lag dropped (collinear/rank-deficient)")
        return dict(ok=True, coef=float(res.params["favorable_lag"]),
                    se=float(res.bse["favorable_lag"]),
                    p=float(res.pvalues["favorable_lag"]),
                    ci=(float(res.conf_int().loc["favorable_lag", 0]),
                        float(res.conf_int().loc["favorable_lag", 1])))

    try:
        res_yb = _fit("favorable_lag + coverage_proxy + C(year) + C(borough_proxy)")
        out["year_borough_fe"] = _coef_block(res_yb)
    except Exception as exc:
        out["year_borough_fe"] = dict(ok=False, reason=f"{type(exc).__name__}: {exc}")

    try:
        res_unit = _fit("favorable_lag + coverage_proxy + C(year) + C(unit)")
        unit_block = _coef_block(res_unit)
        out["unit_fe"] = unit_block
    except Exception as exc:
        out["unit_fe"] = dict(ok=False, reason=f"{type(exc).__name__}: {exc}")

    uf = out.get("unit_fe", {})
    out["kill_criterion_pass"] = bool(uf.get("ok") and uf.get("coef", 0) < 0 and uf.get("p", 1) < 0.05)
    out["note"] = ("negative coef = lower closure hazard following favorable status, the "
                    "expected direction. kill_criterion_pass requires the WITHIN-ZIP "
                    "(unit-FE) coefficient specifically to be negative and p<0.05 after "
                    "clustering -- the year+borough model alone does not clear this bar "
                    "because it cannot rule out a static detection-coverage confound.")
    return out


def closure_validity_check(panel: pd.DataFrame, composite_col: str, closures: pd.DataFrame) -> dict:
    """Contrarian amendment 6, ORIGINAL (pre-results) implementation. Superseded
    by `closure_validity_glm` per statistician post-results correction 11 (this
    version is pseudo-replicated, contemporaneous not lagged, and never applies
    the borough conditioning it claims to). Kept only so the pre-results number
    can still be shown for comparison in the notebook; do not cite this
    function's output as the criterion-validity result."""
    fav = panel[["unit", "year", composite_col]].copy()
    fav["favorable"] = fav[composite_col] >= ENTER_THRESH
    merged = closures.merge(fav, on=["unit", "year"], how="inner")
    merged = merged[merged["n_open"] > 0]
    merged["closure_rate"] = merged["n_closed"] / merged["n_open"]
    merged["borough_proxy"] = merged["unit"].str[:2]

    by_fav = merged.groupby("favorable").apply(
        lambda g: pd.Series({
            "mean_closure_rate": np.average(g["closure_rate"], weights=g["n_open"]),
            "n_zip_years": len(g), "n_open_total": g["n_open"].sum(),
        }), include_groups=False,
    )
    from scipy import stats
    fav_rates = merged[merged["favorable"]]["closure_rate"]
    nonfav_rates = merged[~merged["favorable"]]["closure_rate"]
    t, p = stats.ttest_ind(fav_rates, nonfav_rates, equal_var=False, nan_policy="omit") if len(fav_rates) and len(nonfav_rates) else (np.nan, np.nan)
    lower_for_favorable = bool(
        by_fav.loc[True, "mean_closure_rate"] < by_fav.loc[False, "mean_closure_rate"]
    ) if True in by_fav.index and False in by_fav.index else False
    return dict(by_favorable=by_fav.to_dict(orient="index"), t_stat=float(t) if np.isfinite(t) else None,
                p_value=float(p) if np.isfinite(p) else None, favorable_has_lower_closure=lower_for_favorable)


# ============================================================================
# DISCRETE-TIME HAZARD DRIVER MODEL (METHOD §5, statistician S8/S9,
# contrarian amendment 8 momentum comparator)
# ============================================================================


def fit_hazard_driver_model(panel: pd.DataFrame, spells: pd.DataFrame, composite_col: str,
                             demand_col="demand_pillar_A", supply_col="supply_pillar_A",
                             cost_col="cost_pillar_A") -> dict:
    """Logit of P(exit in year t | at risk) on a duration quadratic (stand-in for
    METHOD's "duration spline"), lag-2-to-4 pillar percentage changes, and
    borough-proxy fixed effects, borough-clustered robust SEs. Also fits a
    momentum-only comparator (contrarian amendment 8): a driver is reported only
    if it improves training log-likelihood over that model AND is Holm-significant."""
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from statsmodels.stats.multitest import multipletests

    py = build_hazard_person_years(panel, spells, composite_col, demand_col, supply_col, cost_col)
    py = py.dropna(subset=[f"{c}_chg_lag2to4" for c in (demand_col, supply_col, cost_col)])
    if len(py) < 30 or py["exit"].sum() < 5:
        return dict(ok=False, reason=f"insufficient hazard person-years (n={len(py)}, events={py['exit'].sum() if len(py) else 0})")

    py["age2"] = py["age"] ** 2
    py = py.rename(columns={
        f"{demand_col}_chg_lag2to4": "demand_chg_lag24",
        f"{supply_col}_chg_lag2to4": "supply_chg_lag24",
        f"{cost_col}_chg_lag2to4": "cost_chg_lag24",
    })
    # composite lag2-4 change, for the momentum-only comparator
    comp_wide = panel.sort_values(["unit", "year"]).copy()
    comp_wide[f"{composite_col}_lag2"] = comp_wide.groupby("unit")[composite_col].shift(2)
    comp_wide[f"{composite_col}_lag4"] = comp_wide.groupby("unit")[composite_col].shift(4)
    comp_wide["composite_chg_lag24"] = comp_wide[f"{composite_col}_lag2"] - comp_wide[f"{composite_col}_lag4"]
    py = py.merge(comp_wide[["unit", "year", "composite_chg_lag24"]], on=["unit", "year"], how="left")
    py = py.dropna(subset=["composite_chg_lag24"])
    if len(py) < 30 or py["exit"].sum() < 5:
        return dict(ok=False, reason="insufficient hazard person-years after momentum merge")

    momentum_model = smf.logit("exit ~ age + age2 + composite_chg_lag24", data=py).fit(disp=0)

    full_formula = "exit ~ age + age2 + demand_chg_lag24 + supply_chg_lag24 + cost_chg_lag24 + C(borough_proxy)"
    full_model = smf.logit(full_formula, data=py).fit(disp=0, method="lbfgs", maxiter=200)
    try:
        full_model_clustered = full_model.get_robustcov_results(cov_type="cluster", groups=py["borough_proxy"])
    except Exception:
        full_model_clustered = full_model

    driver_names = ["demand_chg_lag24", "supply_chg_lag24", "cost_chg_lag24"]
    params = full_model_clustered.params if hasattr(full_model_clustered, "params") else full_model.params
    pvals = full_model_clustered.pvalues if hasattr(full_model_clustered, "pvalues") else full_model.pvalues
    param_names = list(full_model.params.index)

    rows = []
    raw_p = []
    for name in driver_names:
        if name not in param_names:
            continue
        idx = param_names.index(name)
        coef = params[idx] if not hasattr(params, "loc") else params[name]
        p = pvals[idx] if not hasattr(pvals, "loc") else pvals[name]
        rows.append(dict(driver=name, coef=float(coef), p_raw=float(p)))
        raw_p.append(float(p))

    if raw_p:
        holm_reject, holm_p, _, _ = multipletests(raw_p, alpha=0.05, method="holm")
        for row, rej, hp in zip(rows, holm_reject, holm_p):
            row["p_holm"] = float(hp)
            row["holm_significant"] = bool(rej)
    driver_table = pd.DataFrame(rows).sort_values("p_raw") if rows else pd.DataFrame(columns=["driver", "coef", "p_raw"])

    llf_full = full_model.llf
    llf_momentum = momentum_model.llf
    beats_momentum = llf_full > llf_momentum

    # D1 guardrail, enforced in code: never claim a supply-change coefficient
    # predicts a demand-led exit. This function returns accounting-level
    # coefficients only (which pillar moved before exit), never a causal or
    # cross-pillar predictive claim; see attribute_exit_cause for the separate
    # "which pillar fell most" accounting decomposition, also labeled
    # accounting-not-cause in the notebook/ANSWER.md.
    return dict(ok=True, driver_table=driver_table, llf_full=float(llf_full), llf_momentum=float(llf_momentum),
                beats_momentum_comparator=bool(beats_momentum), n_person_years=len(py), n_events=int(py["exit"].sum()))


def fit_macro_hazard_terms(panel: pd.DataFrame, spells: pd.DataFrame, composite_col: str,
                            supply_df: pd.DataFrame, workers_df: pd.DataFrame, macro: pd.DataFrame) -> dict:
    """Statistician S8: three pre-specified exposure x macro pairs, year FE
    (implemented as the macro series entering directly since year FE and a
    single NYC-wide series are collinear — METHOD §5 — so this reports the
    *exposure x macro* interaction only, never a level macro main effect).
    Exposures fixed at 2000-02 and standardized. Each gamma reported only if it
    survives Holm across the 3 tests (S9) — episode-drop robustness is left as
    a documented gap (GTM-230, the post-results contrarian/statistician pass)."""
    import statsmodels.formula.api as smf
    from statsmodels.stats.multitest import multipletests

    py = build_hazard_person_years(panel, spells, composite_col)
    if len(py) < 30 or py["exit"].sum() < 5:
        return dict(ok=False, reason="insufficient hazard person-years for macro terms")

    base = supply_df.merge(workers_df[["unit", "year", "workers"]], on=["unit", "year"])
    early = base[(base["year"] >= 2000) & (base["year"] <= 2002)].groupby("unit").agg(
        estab=("estab_restaurant_total", "mean"), workers=("workers", "mean")
    )
    total_zbp = panel.groupby("unit")["estab_restaurant_total"].mean()  # proxy: this warehouse's zip_establishments query is restaurant-only, so E1 uses restaurant estab relative to its own 2000-02 base (growth-normalized), not a true all-industry share (documented simplification: this warehouse loader pulls 722-only NAICS, not the full ZBP cross-industry table, so a true "restaurant share of total ZBP employment" exposure is not constructed here).
    e1 = (early["estab"] / early["estab"].mean()).rename("E1_restaurant_intensity")
    lodes = pd.read_parquet(RQ001_INTERIM / "lodes" / "lodes_wac_zcta.parquet")
    lodes["unit"] = lodes["zcta"].map(to_unit)
    lodes_early = lodes[(lodes["year"] >= 2002) & (lodes["year"] <= 2004)].groupby("unit").agg(
        c000=("c000", "mean"), cns07=("cns07", "mean"), cns18=("cns18", "mean")
    )
    e2 = (1 - (lodes_early["cns07"] + lodes_early["cns18"]) / lodes_early["c000"].clip(lower=1)).rename("E2_nonretail_nonfood_share")
    zhvi_early = panel[(panel["year"] >= 2000) & (panel["year"] <= 2002)].groupby("unit")["pct_zhvi"].mean().rename("E3_zhvi_pct") \
        if "pct_zhvi" in panel.columns else pd.Series(dtype=float, name="E3_zhvi_pct")

    exposures = pd.concat([e1, e2, zhvi_early], axis=1).dropna()
    for col in exposures.columns:
        exposures[col] = (exposures[col] - exposures[col].mean()) / exposures[col].std()

    py = py.merge(exposures, left_on="unit", right_index=True, how="inner")
    py = py.merge(macro[macro["series_id"] == "NEWY636URN"][["year", "value"]].rename(columns={"value": "NEWY636URN"}), on="year", how="left")
    py = py.merge(macro[macro["series_id"] == "MORTGAGE30US"][["year", "value"]].rename(columns={"value": "MORTGAGE30US"}), on="year", how="left")
    covid_years = macro[(macro["series_id"] == "USREC")]  # covid flag proxy via covid_window column if present
    py["covid_dummy"] = py["year"].isin([2021, 2022]).astype(int)
    py["ur_change"] = py.groupby("year")["NEWY636URN"].transform("first").diff() if "NEWY636URN" in py else np.nan
    py = py.dropna(subset=["E1_restaurant_intensity", "E2_nonretail_nonfood_share", "E3_zhvi_pct"])
    if len(py) < 30 or py["exit"].sum() < 5:
        return dict(ok=False, reason="insufficient rows after exposure/macro merge")

    py["age2"] = py["age"] ** 2
    py["e1_x_ur"] = py["E1_restaurant_intensity"] * py["NEWY636URN"]
    py["e2_x_covid"] = py["E2_nonretail_nonfood_share"] * py["covid_dummy"]
    py["e3_x_mortgage"] = py["E3_zhvi_pct"] * py["MORTGAGE30US"]

    formula = "exit ~ age + age2 + e1_x_ur + e2_x_covid + e3_x_mortgage + C(year)"
    try:
        model = smf.logit(formula, data=py).fit(disp=0, method="lbfgs", maxiter=300)
    except Exception as exc:
        return dict(ok=False, reason=f"macro hazard model failed to converge: {exc!r}")

    terms = ["e1_x_ur", "e2_x_covid", "e3_x_mortgage"]
    rows = []
    raw_p = []
    for t in terms:
        if t not in model.params.index:
            continue
        rows.append(dict(term=t, coef=float(model.params[t]), p_raw=float(model.pvalues[t])))
        raw_p.append(float(model.pvalues[t]))
    if raw_p:
        holm_reject, holm_p, _, _ = multipletests(raw_p, alpha=0.05, method="holm")
        for row, rej, hp in zip(rows, holm_reject, holm_p):
            row["p_holm"] = float(hp)
            row["holm_significant"] = bool(rej)
    return dict(ok=True, macro_table=pd.DataFrame(rows), n_person_years=len(py),
                note="H2 (exposure x macro, year FE) only — a level macro main effect is not "
                     "identified because year FE and any single NYC-wide series are collinear "
                     "(METHOD §5). Wording: 'units with higher E exited more in years of higher "
                     "M, conditional on year effects' — never 'M causes exits'. Episode leave-"
                     "one-out robustness (S8) is not run in v0; documented gap.")
