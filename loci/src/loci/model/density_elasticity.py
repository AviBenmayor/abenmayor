"""Density elasticity: the per-category clustering-vs-saturation coefficient (D68 -> GTM-138).

WHAT THIS IS
------------
One number per retail category, `beta`, estimated on the ZIP x category panel
that D68's headroom backtest was run on:

    log((estab_2023 + 1) / (estab_2013 + 1))
        ~ beta * log(density_2013) + dlog_pop + log_pop13 + log_inc13
          + dlog_inc + borough FE

with `density = 1000 * (estab_2013 + 1) / pop_2013` -- establishments per
thousand residents. `beta > 0` means ZIPs that were ALREADY dense in that
category added MORE of it over the decade (clustering); `beta < 0` means they
added less (saturation). D68 found this sign flipping by category and made it
the next increment, because the grade has to know which categories reward
proximity to incumbents and which are punished by it.

WHAT THIS IS NOT
----------------
1. NOT A FORECAST. D68 established that headroom has no out-of-sample skill
   (1 of 14 categories beat persistence/drift/population-only, and that one is
   a NAICS artifact). `beta` is a DESCRIPTIVE decade-average regime label, not
   a predicted establishment count. Nothing here may be extrapolated forward.
2. NOT A CAUSAL ESTIMATE. The outcome contains log(estab_2013 + 1) with a
   negative sign and the regressor contains it with a positive sign, so
   classical measurement error in the 2013 count pushes `beta` DOWNWARD --
   toward "saturating" -- by mean reversion alone. Consequence, and it is
   asymmetric: a CLUSTERING verdict is conservative (it survived a bias working
   against it); a SATURATING verdict is the weaker of the two and may be partly
   mean reversion. The placebo gate defends against generic ZIP growth, NOT
   against this. Read `saturating` as "no evidence of clustering, and the level
   the decade rewarded was lower", never as "this category is full".
3. NOT PER-CAPITA IN ANY MEANINGFUL SENSE. Conditional on log_pop13 (a
   control), log(density) is an affine function of log(estab_2013 + 1), so
   `beta` IS the coefficient on the incumbent count holding population fixed.
   The "per 1,000 residents" framing is cosmetic -- the same structural point
   D68 made about headroom being an affine recombination of population and
   count.

THE DATA, AND WHAT IT CANNOT RESOLVE
------------------------------------
- ZIP grain. 11215 fuses Park Slope with Gowanus; 11231 fuses Red Hook with
  Carroll Gardens. A within-ZIP corridor is invisible here.
- ZIP 11249 has no 2013 ZCTA (its residents sat in 11211), so it is merged into
  11211 on BOTH sides in BOTH years -- constant geography across the window.
- ZBP/CBP is EMPLOYER-ONLY (no non-employer sole proprietors -- the reason
  `tailor_repair` is a rounding error here) and is noise-infused from 2017, so
  a single-digit ZIP cell is approximate.
- The 2017 NAICS 445110 -> 445120 reclassification moved NYC bodegas from
  grocery to convenience between the two vintages (MN+BK grocery down, convenience
  up several-fold, the sum flat). `grocery` and `convenience` are therefore
  ALSO reported as a combined `food_retail` series, and the combined series is
  the one to trust for the food-retail regime.
- The norms behind any downstream headroom are REVEALED SUPPLY (D6): they
  encode the historical supply that got built, not a welfare optimum.
- COVID sits inside the window. The decade average absorbs it.

HOW THE GRADE SHOULD USE THE REGIME (D68's ruling, operationalised)
-------------------------------------------------------------------
- `saturating`  -> score the category as demand pool DIVIDED BY incumbents.
  Incumbents count AGAINST the site. Arriving pipeline residents add to the
  numerator directly.
- `clustering`  -> incumbents count IN FAVOUR of the site (proximity is the
  amenity). The cap is NOT headcount: cap from spend per resident by age and
  income (spend.yaml, and the D63 age curve where one exists), because a
  headcount norm says Greenpoint had no bar headroom in 2013 and it added 12.
- `no_signal`   -> residents only. Do not let the incumbent count enter the
  score in either direction; there is no evidence for a sign.

The classification rule is in `classify()`, not in prose. A category is
classified only if ALL THREE hold: |t_Conley| >= 1.96, the sign is stable in
>= 90% of leave-one-ZIP-out refits, and |beta| exceeds the 90th percentile of
the placebo |beta| distribution (that category's growth regressed on OTHER
categories' 2013 density). Otherwise: `no_signal`. The sign is never forced.

WHAT THIS RESULT DID TO D68
---------------------------
It SUPERSEDES D68's reading that "bars and cafes cluster rather than saturate".
On the same panel, with a Conley SE, a leave-one-ZIP-out check and a placebo
distribution built from every other category, neither survives:

  * CAFES fail the PLACEBO. The level-form coefficient is large and clean
    (beta +6.20, Conley t +4.83, LOZO 1.00) but cafe growth is predicted just
    as well -- better, in fact -- by 2013 RESTAURANT density (standardized
    6.18) and 2013 HARDWARE density (5.88) as by cafes' own (5.354, against a
    placebo p90 of 5.820). That is generic gentrification: "this ZIP was about
    to be re-priced", not cafe-specific agglomeration. It is the same defect
    D68's own placebo section found when bar headroom predicted pharmacy
    growth better than pharmacy's own headroom did.
  * BARS fail SIGNIFICANCE. Level-form beta is positive (+3.47) but Conley
    t = +1.63, below the 1.96 gate, and beta_std 1.499 also sits under the
    placebo p90 of 1.751.

D68's CHORE-CATEGORY conclusions STAND and are strengthened: grocery, laundry,
hair, nails, fitness, clinic, bank and childcare all classify `saturating`
here, which is the divide-by-incumbents reading D68 proposed for them.

THE GATE WAS RELAXED ON 2026-09-11
----------------------------------
The first gate required a category in every regime including `clustering`.
Because no category clusters on this panel it refused to write anything, which
would have discarded eight sound saturating verdicts to enforce a conclusion.
The owner ruled that requirement a spec error -- it forces a sign at the
portfolio level, the exact failure the per-category placebo exists to prevent.
See `REQUIRED_REGIMES`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import time

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
YAML_PATH = PKG_ROOT / "model" / "density_elasticity.yaml"
DB_PATH = REPO_ROOT / "data" / "loci.duckdb"
PLUTO_CSV = REPO_ROOT / "data" / "raw" / "pluto.csv"
ACS_DIR = REPO_ROOT / "data" / "raw" / "acs"
ZBP_DIR = REPO_ROOT / "data" / "raw" / "zbp"

BASE_YEAR = 2013
END_YEAR = 2023
BOROUGHS = ("MN", "BK")
MIN_POP_BASE = 5_000          # D68's ZIP universe, unchanged
#: Conley bandwidth. 3 km is roughly one ZIP-to-ZIP step in MN+BK, so the
#: kernel reaches a ZIP's immediate neighbours and no further. D63 used 2 km on
#: TRACT centroids; the unit here is ~10x larger, hence the wider default.
CONLEY_BANDWIDTH_M = 3_000.0
T_GATE = 1.96                 # |t| on the Conley SE, not HC3
LOZO_SIGN_GATE = 0.90         # share of leave-one-ZIP-out refits keeping the sign
PLACEBO_QUANTILE = 0.90       # |beta| must beat this quantile of the placebo |beta|s
MIN_ZIPS = 25                 # a category with fewer usable ZIPs is not fitted
MIN_NONZERO_BASE = 10         # ...nor is one present in fewer than this many in 2013
MORAN_PERMUTATIONS = 999
#: The ALLOWED regimes. A form ships only if every fitted category carries one
#: of these and at least one of them is a SIGNAL (not `no_signal`).
#:
#: RELAXED 2026-09-11 (owner). The first version of this gate required a
#: category in EVERY regime, `clustering` included. That was a spec error and
#: it is worth recording why rather than quietly deleting: requiring a
#: clustering verdict forces a sign at the portfolio level, which is precisely
#: what the per-category placebo exists to prevent. It also had a concrete
#: consequence -- on the real 2013->2023 panel NO category clusters under
#: either functional form, so the gate refused to write anything at all and
#: the eight genuine saturating verdicts were lost with it. The gate now asks
#: only that the estimate be well-formed (every category classified, the
#: placebo actually run) and informative (at least one signal), never that it
#: reach a particular conclusion.
REQUIRED_REGIMES = ("clustering", "saturating", "no_signal")
#: The subset of REQUIRED_REGIMES that counts as an actual finding. A form in
#: which every category is `no_signal` is a null result, not a coefficient
#: table, and must not be written as though it were one.
SIGNAL_REGIMES = ("clustering", "saturating")
#: A form whose beta has the SAME SIGN for every fitted category is rejected.
#:
#: This is the diagnostic the original "every regime" gate was groping at, now
#: stated in the form it should always have taken. It is SYMMETRIC -- an
#: all-positive table is refused exactly as an all-negative one is -- so it
#: forces no sign on any category and is not a disguised requirement for a
#: `clustering` verdict; it is a statement about the COEFFICIENT VECTOR, not
#: about the regimes. Sixteen unrelated retail categories cannot all reward,
#: or all punish, incumbent density; when they do, the form has measured a
#: common factor or an arithmetic property of its own transform rather than
#: anything category-specific.
#:
#: It is what actually demotes the log form here, and the demotion is
#: diagnosable rather than incidental: the log form's dependent variable is
#: PROPORTIONAL growth, whose denominator is the regressor itself, so it comes
#: back negative for all 16 series -- and the only three it calls significant
#: (convenience, tailor_repair, childcare) are precisely the three with a
#: known base-year definitional break (the 2017 445110->445120 bodega recode,
#: the employer-only collapse of tailor_repair, and childcare's 2013
#: coverage). A table whose every verdict is a data artifact must not ship.
REJECT_UNANIMOUS_SIGN = True

#: The 2017 reclassification pair, reported combined as well as separately.
COMBINED_SERIES = {"food_retail": ("grocery", "convenience")}

CONTROLS = ["dlog_pop", "log_pop13", "log_inc13", "dlog_inc", "bk"]

#: The two functional forms, and the ORDER OF PREFERENCE. `log` is the stated
#: primary (GTM-138); `level` is the robustness that is PROMOTED only if `log`
#: fails its own gate -- see `choose_form`. Pre-stating the fallback here is
#: what keeps the choice from being form-shopping after the fact.
FORMS = {
    "log": {"y": "g_log", "x": "log_dens13",
            "label": "log((estab_end+1)/(estab_base+1)) ~ log(1000*(estab_base+1)/pop_base)",
            "units": "elasticity: a 1% higher 2013 density goes with beta% faster "
                     "proportional growth"},
    "level": {"y": "d_estab", "x": "dens13_level",
              "label": "(estab_end - estab_base) ~ 1000*estab_base/pop_base",
              "units": "establishments added per unit of 2013 density "
                       "(one extra incumbent per 1,000 residents)"},
}
FORM_ORDER = ("log", "level")

DISCLAIMER = (
    "Density elasticity is a DESCRIPTIVE decade-average regime label on ZIP x "
    "category ZBP counts, never a forecast (D68) and never causal: mean "
    "reversion biases beta toward 'saturating', so a clustering verdict is the "
    "conservative one."
)


class DensityElasticityGateFailure(RuntimeError):
    """Raised when the fit does not earn the right to overwrite the YAML."""


# --------------------------------------------------------------------- inputs

def _census_key() -> str:
    """Same lookup order as the ACS/ZBP adapters: checked-in .env, then env."""
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CENSUS_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
                if key:
                    return key
    return os.environ.get("CENSUS_API_KEY", "")


def connect_read_only(retries: int = 8, wait_s: float = 40.0):
    """Open the warehouse READ ONLY, retrying on the lock another session holds.

    Never kills anything; a concurrent writer is normal in this project."""
    import duckdb

    last = None
    for i in range(retries):
        try:
            return duckdb.connect(str(DB_PATH), read_only=True)
        except Exception as exc:  # noqa: BLE001 -- duckdb raises several types
            last = exc
            if i < retries - 1:
                time.sleep(wait_s)
    raise RuntimeError(f"could not open {DB_PATH} read-only after {retries} tries: {last}")


def fetch_zcta_acs(year: int, *, force: bool = False, path: pathlib.Path | None = None
                   ) -> pathlib.Path:
    """Cache ACS 5-year ZCTA population + median household income for `year`.

    Same Census API and the same key as `sources/.../acs`; ZCTA rather than
    tract geography, which is why it lands in its own cache file rather than
    extending the tract pull. 2018 and earlier require `in=state:36`; later
    vintages serve ZCTAs nationally and are filtered client-side by the ZIP
    universe, so the file is a faithful landing of what the API returned."""
    import requests

    p = path or (ACS_DIR / f"zcta_{year}.json")
    if p.exists() and not force:
        return p
    key = _census_key()
    if not key:
        raise RuntimeError("CENSUS_API_KEY absent; cannot fetch ZCTA ACS")
    params = {"get": "B01003_001E,B19013_001E",
              "for": "zip code tabulation area:*", "key": key}
    if year <= 2018:
        params["in"] = "state:36"
    url = f"https://api.census.gov/data/{year}/acs/acs5"
    r = requests.get(url, params=params, timeout=600)
    r.raise_for_status()
    data = r.json()
    head, rows = data[0], data[1:]
    zi = next(i for i, c in enumerate(head) if "zip code" in c)
    pi, ii = head.index("B01003_001E"), head.index("B19013_001E")
    out = {}
    for row in rows:
        pop = pd.to_numeric(row[pi], errors="coerce")
        inc = pd.to_numeric(row[ii], errors="coerce")
        out[str(row[zi])] = {
            "pop": None if pd.isna(pop) else float(pop),
            # Census codes suppressed/negative medians as large negatives.
            "income": None if pd.isna(inc) or inc < 0 else float(inc),
        }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"year": year, "dataset": f"acs/acs5 {year} 5-year", "geography": "ZCTA5",
         "variables": ["B01003_001E", "B19013_001E"], "source_url": url,
         "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
         "n": len(out), "zctas": out}, indent=1, sort_keys=True) + "\n")
    return p


def fetch_zbp_base(zips: list[str], *, year: int = BASE_YEAR, force: bool = False,
                   path: pathlib.Path | None = None) -> pathlib.Path:
    """Cache the 2013 ZBP establishment counts by 6-digit NAICS for `zips`.

    The warehouse holds 2023 only (`analysis.zip_category_establishments`), so
    the base year has to come from the standalone ZBP API, which serves
    1994-2018 (registry `census_zbp`). `EMPSZES=001` is the all-establishments
    band -- the same band the 2023 warehouse total represents."""
    import requests

    p = path or (ZBP_DIR / f"zbp_{year}_mnbk.json")
    if p.exists() and not force:
        return p
    key = _census_key()
    if not key:
        raise RuntimeError("CENSUS_API_KEY absent; cannot fetch ZBP base year")
    url = f"https://api.census.gov/data/{year}/zbp"
    rows: list[dict] = []
    chunk = 120
    for i in range(0, len(zips), chunk):
        part = zips[i:i + chunk]
        r = requests.get(url, params={"get": "ESTAB,NAICS2012,EMPSZES",
                                      "for": "zipcode:" + ",".join(part),
                                      "key": key}, timeout=300)
        r.raise_for_status()
        data = r.json()
        head = data[0]
        zi = next(j for j, c in enumerate(head) if "zip" in c.lower())
        ni, ei, si = head.index("NAICS2012"), head.index("ESTAB"), head.index("EMPSZES")
        for row in data[1:]:
            if row[si] != "001" or len(str(row[ni])) != 6:
                continue
            rows.append({"zipcode": str(row[zi]), "naics": str(row[ni]),
                         "estab": int(row[ei])})
        time.sleep(1)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"year": year, "dataset": f"zbp {year}", "naics_vintage": "NAICS2012",
         "emp_size_band": "001 (all establishments)", "source_url": url,
         "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
         "n": len(rows), "rows": rows}, indent=1, sort_keys=True) + "\n")
    return p


def _read_acs(year: int, path: pathlib.Path | None = None) -> pd.DataFrame:
    doc = json.loads((path or (ACS_DIR / f"zcta_{year}.json")).read_text())
    return pd.DataFrame(
        [{"zipcode": z, "pop": v["pop"], "income": v["income"]}
         for z, v in doc["zctas"].items()])


def _read_zbp_base(year: int = BASE_YEAR, path: pathlib.Path | None = None) -> pd.DataFrame:
    doc = json.loads((path or (ZBP_DIR / f"zbp_{year}_mnbk.json")).read_text())
    return pd.DataFrame(doc["rows"])


def category_naics() -> pd.DataFrame:
    """Category <- 6-digit NAICS, from the SAME crosswalk the 2023 warehouse
    table was built with (`src/loci/zbp_naics.yaml`, NAICS 2017). Applied to a
    NAICS2012 base year: the codes coincide except for the documented
    445110/445120 food-retail recode, which is why `food_retail` exists."""
    y = yaml.safe_load((PKG_ROOT / "zbp_naics.yaml").read_text())
    return pd.DataFrame([{"category": c, "naics": e["naics"]}
                         for c, es in y["categories"].items() for e in es])


def zip_geography(pluto_csv: pathlib.Path | None = None) -> pd.DataFrame:
    """ZIP -> borough and a residential-unit-weighted centroid, from PLUTO.

    Borough by majority residential units (a ZIP that straddles a borough line
    is assigned where its people are). The centroid is what the Conley kernel
    and Moran's I run on; it is unit-weighted rather than lot-weighted so a ZIP
    with a large park or rail yard is not pulled off its population. PLUTO, not
    `analysis.address` -- this module must not depend on the screen tables."""
    import duckdb

    src = str(pluto_csv or PLUTO_CSV)
    con = duckdb.connect()
    df = con.execute(
        """
        WITH lots AS (
            SELECT lpad(CAST(CAST(postcode AS INT) AS VARCHAR), 5, '0') AS zipcode,
                   borough,
                   coalesce(unitsres, 0) AS units,
                   latitude AS lat, longitude AS lon
            FROM read_csv_auto(?, ignore_errors=true)
            WHERE postcode IS NOT NULL AND postcode > 0
              AND latitude IS NOT NULL AND longitude IS NOT NULL
        ),
        by_boro AS (
            SELECT zipcode, borough, sum(units) u, count(*) lots,
                   row_number() OVER (PARTITION BY zipcode
                                      ORDER BY sum(units) DESC, count(*) DESC) rn
            FROM lots GROUP BY 1, 2
        ),
        centroid AS (
            SELECT zipcode,
                   sum(lon * (units + 1)) / sum(units + 1) AS lon,
                   sum(lat * (units + 1)) / sum(units + 1) AS lat,
                   sum(units) AS res_units
            FROM lots GROUP BY 1
        )
        SELECT b.zipcode, b.borough, c.lon, c.lat, c.res_units
        FROM by_boro b JOIN centroid c USING (zipcode)
        WHERE b.rn = 1
        """, [src]).df()
    con.close()
    return df


def establishments_2023(con) -> pd.DataFrame:
    """2023 category counts straight out of the warehouse (2,079 rows).

    Read and released immediately: this is the only warehouse read the module
    makes, and it deliberately touches neither `analysis.address` nor
    `analysis.address_category`."""
    return con.execute(
        """
        SELECT zipcode, category, CAST(sum(estab_total) AS DOUBLE) AS estab
        FROM analysis.zip_category_establishments
        WHERE year = ?
        GROUP BY 1, 2
        """, [END_YEAR]).df()


# ---------------------------------------------------------------------- panel

def build_panel(est23: pd.DataFrame, zbp13: pd.DataFrame, acs13: pd.DataFrame,
                acs23: pd.DataFrame, geo: pd.DataFrame,
                xw: pd.DataFrame | None = None) -> pd.DataFrame:
    """The ZIP x category panel, assembled in DuckDB and returned small.

    ~80 ZIPs x 16 series. Every join, the 11249 -> 11211 merge and the
    combined food-retail series happen in SQL so nothing large is ever
    materialised in pandas."""
    import duckdb

    xw = category_naics() if xw is None else xw
    con = duckdb.connect()
    for name, frame in (("est23_raw", est23), ("zbp13_raw", zbp13),
                        ("acs13_raw", acs13), ("acs23_raw", acs23),
                        ("geo_raw", geo), ("xw", xw)):
        con.register(name, frame)
    con.execute("CREATE MACRO z(x) AS (CASE WHEN x = '11249' THEN '11211' ELSE x END)")
    panel = con.execute(
        f"""
        WITH acs13 AS (
            SELECT z(zipcode) zipcode, sum(pop) pop,
                   sum(income * pop) / nullif(sum(CASE WHEN income IS NULL
                                                       THEN 0 ELSE pop END), 0) income
            FROM acs13_raw GROUP BY 1
        ),
        acs23 AS (
            SELECT z(zipcode) zipcode, sum(pop) pop,
                   sum(income * pop) / nullif(sum(CASE WHEN income IS NULL
                                                       THEN 0 ELSE pop END), 0) income
            FROM acs23_raw GROUP BY 1
        ),
        geo AS (
            SELECT zipcode, any_value(borough) borough,
                   sum(lon * (res_units + 1)) / sum(res_units + 1) lon,
                   sum(lat * (res_units + 1)) / sum(res_units + 1) lat
            FROM (SELECT z(zipcode) zipcode, borough, lon, lat, res_units FROM geo_raw)
            GROUP BY 1
        ),
        zips AS (
            SELECT g.zipcode, g.borough, g.lon, g.lat,
                   a13.pop pop13, a13.income inc13, a23.pop pop23, a23.income inc23
            FROM geo g
            JOIN acs13 a13 USING (zipcode)
            JOIN acs23 a23 USING (zipcode)
            WHERE g.borough IN ('{BOROUGHS[0]}', '{BOROUGHS[1]}')
              AND a13.pop >= {MIN_POP_BASE}
              AND a13.income IS NOT NULL AND a23.income IS NOT NULL
        ),
        base AS (
            SELECT z(r.zipcode) zipcode, x.category, sum(r.estab) estab
            FROM zbp13_raw r JOIN xw x USING (naics) GROUP BY 1, 2
        ),
        endp AS (
            SELECT z(zipcode) zipcode, category, sum(estab) estab
            FROM est23_raw GROUP BY 1, 2
        ),
        cats AS (SELECT DISTINCT category FROM xw),
        grid AS (SELECT z.*, c.category FROM zips z CROSS JOIN cats c),
        single AS (
            SELECT g.*, coalesce(b.estab, 0) estab13, coalesce(e.estab, 0) estab23
            FROM grid g
            LEFT JOIN base b ON b.zipcode = g.zipcode AND b.category = g.category
            LEFT JOIN endp e ON e.zipcode = g.zipcode AND e.category = g.category
        ),
        combined AS (
            SELECT zipcode, borough, lon, lat, pop13, inc13, pop23, inc23,
                   ? AS category, sum(estab13) estab13, sum(estab23) estab23
            FROM single WHERE category IN (?, ?)
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
        )
        SELECT * FROM single UNION ALL SELECT * FROM combined
        """, ["food_retail", *COMBINED_SERIES["food_retail"]]).df()
    con.close()

    panel["d_estab"] = panel.estab23 - panel.estab13
    panel["g_log"] = np.log((panel.estab23 + 1.0) / (panel.estab13 + 1.0))
    # +1 matches the outcome's smoothing and keeps zero-establishment ZIPs in
    # the sample instead of silently selecting on the regressor.
    panel["dens13"] = 1000.0 * (panel.estab13 + 1.0) / panel.pop13
    panel["log_dens13"] = np.log(panel.dens13)
    # The LEVEL form's regressor: raw establishments per 1,000 residents, no
    # smoothing (a zero here is a real zero, not a log singularity).
    panel["dens13_level"] = 1000.0 * panel.estab13 / panel.pop13
    panel["dlog_pop"] = np.log(panel.pop23 / panel.pop13)
    panel["log_pop13"] = np.log(panel.pop13)
    panel["log_inc13"] = np.log(panel.inc13)
    panel["dlog_inc"] = np.log(panel.inc23 / panel.inc13)
    panel["bk"] = (panel.borough == "BK").astype(float)
    return panel


def zip_universe_hash(zips) -> str:
    """Identity of the estimation geography. A coefficient revealed on one ZIP
    universe is not valid on another (the D63 `inputs_hash` habit)."""
    key = "|".join(sorted(str(z) for z in set(zips)))
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# ------------------------------------------------------------------ estimator

def _to_utm(lon, lat) -> np.ndarray:
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    x, y = tf.transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.column_stack([x, y])


def _bartlett(xy: np.ndarray, bandwidth_m: float) -> np.ndarray:
    from scipy.spatial.distance import cdist

    d = cdist(xy, xy)
    return np.where(d <= bandwidth_m, 1.0 - d / bandwidth_m, 0.0)


def conley_cov(model, xy: np.ndarray, bandwidth_m: float = CONLEY_BANDWIDTH_M) -> np.ndarray:
    """Conley spatial-HAC covariance, Bartlett kernel -- the same estimator
    D63 uses on tracts (`model/age_fit._conley_cov`), on ZCTA centroids and a
    wider bandwidth. Needed because ZIP residuals are spatially autocorrelated:
    neighbouring ZIPs share a retail corridor, so the effective n is well below
    the row count and HC3 is optimistic."""
    X = np.asarray(model.model.exog, float)
    e = np.asarray(model.resid, float)
    n, k = X.shape
    kern = _bartlett(xy, bandwidth_m)
    xe = X * e[:, None]
    bread = np.linalg.inv(X.T @ X)
    return bread @ (xe.T @ kern @ xe) @ bread * (n / (n - k))


def morans_i(resid: np.ndarray, xy: np.ndarray, bandwidth_m: float = CONLEY_BANDWIDTH_M,
             permutations: int = MORAN_PERMUTATIONS, seed: int = 0) -> dict:
    """Moran's I on the fit residuals with the SAME kernel the Conley SE uses,
    row-standardised, plus a permutation p-value. Reported, never a gate: its
    job is to say whether the Conley correction was needed, not to veto."""
    w = _bartlett(xy, bandwidth_m).copy()
    np.fill_diagonal(w, 0.0)
    rs = w.sum(axis=1, keepdims=True)
    if not np.any(rs > 0):
        return {"i": None, "p_perm": None, "note": "no neighbours within bandwidth"}
    w = np.divide(w, np.where(rs > 0, rs, 1.0))

    def stat(v: np.ndarray) -> float:
        z = v - v.mean()
        denom = float(z @ z)
        if denom == 0:
            return 0.0
        return float(len(z) * (z @ (w @ z)) / (w.sum() * denom))

    obs = stat(np.asarray(resid, float))
    rng = np.random.default_rng(seed)
    v = np.asarray(resid, float)
    null = np.array([stat(rng.permutation(v)) for _ in range(permutations)])
    p = float((1 + np.sum(np.abs(null) >= abs(obs))) / (permutations + 1))
    return {"i": obs, "p_perm": p, "bandwidth_m": float(bandwidth_m)}


def _ols(d: pd.DataFrame, y: str, x: list[str]):
    import statsmodels.api as sm

    X = sm.add_constant(d[x].astype(float), has_constant="add")
    return sm.OLS(d[y].astype(float), X).fit()


def fit_one(d: pd.DataFrame, y: str, focal: str, bandwidth_m: float,
            controls: list[str] | None = None) -> dict:
    """One regression: `y ~ focal + controls`, with HC3 and Conley SEs on the
    focal coefficient and Moran's I on the residuals."""
    ctrl = list(CONTROLS if controls is None else controls)
    cols = [focal] + [c for c in ctrl if d[c].nunique() > 1]
    m = _ols(d, y, cols)
    xy = _to_utm(d["lon"], d["lat"])
    cov_c = conley_cov(m, xy, bandwidth_m)
    names = list(m.params.index)
    j = names.index(focal)
    se_c = float(np.sqrt(max(cov_c[j, j], 0.0)))
    se_h = float(m.HC3_se[focal])
    b = float(m.params[focal])
    sd_x = float(np.std(d[focal].astype(float), ddof=1))
    return {
        "beta": b, "beta_std": b * sd_x, "sd_x": sd_x,
        "se_hc3": se_h, "se_conley": se_c,
        "t_hc3": b / se_h if se_h > 0 else float("nan"),
        "t_conley": b / se_c if se_c > 0 else float("nan"),
        "n_zips": len(d), "r_squared": float(m.rsquared),
        "moran": morans_i(np.asarray(m.resid, float), xy, bandwidth_m),
        "terms": cols,
    }


def lozo_sign_stability(d: pd.DataFrame, y: str, focal: str, bandwidth_m: float) -> dict:
    """Share of leave-one-ZIP-out refits whose focal coefficient keeps the
    full-sample sign. The influential-ZIP check: MN+BK has a handful of ZIPs
    (Midtown, Downtown Brooklyn) that could carry a coefficient by themselves."""
    full = np.sign(fit_one(d, y, focal, bandwidth_m)["beta"])
    signs = []
    for z in d["zipcode"].unique():
        sub = d[d["zipcode"] != z]
        try:
            signs.append(np.sign(_ols(sub, y, [focal] + [
                c for c in CONTROLS if sub[c].nunique() > 1]).params[focal]))
        except Exception:  # noqa: BLE001 -- a singular drop is a failed refit
            signs.append(0.0)
    signs = np.array(signs, float)
    return {"stability": float(np.mean(signs == full)) if len(signs) else 0.0,
            "n_refits": len(signs), "full_sign": float(full)}


def placebo_betas(panel: pd.DataFrame, cat: str, others: list[str], y: str,
                  bandwidth_m: float, x: str = "log_dens13") -> dict:
    """|beta| when this category's growth is regressed on ANOTHER category's
    2013 density, same controls, same ZIPs.

    D68's placebo table showed bar HEADROOM predicting pharmacy growth better
    than pharmacy's own headroom did -- i.e. most of the apparent signal was
    "this ZIP was under-retailed and later grew". This is that test, run
    against every other category rather than a hand-picked pair, so the
    comparison value is a distribution and not an anecdote.

    Compared on STANDARDIZED coefficients (beta x sd of the regressor), never
    raw ones. In the level form beta carries the units of the placebo
    category's own density, so a thin category like `tailor_repair` (0.02
    establishments per 1,000 residents) produces an enormous raw beta purely
    because its regressor barely varies; a raw comparison would make the
    placebo bar unpassable for exactly the wrong reason. Standardizing puts
    every comparison on "per one standard deviation of 2013 density" and is
    applied identically in both forms.

    It defends against a COMMON ZIP-GROWTH factor. It does NOT defend against
    the mean reversion in the own-density term (see the module docstring):
    only the focal regression has the 2013 count on both sides."""
    focal = panel[panel.category == cat][["zipcode", y, *CONTROLS, "lon", "lat"]]
    bs = {}
    for d_cat in others:
        if d_cat == cat:
            continue
        dd = panel[panel.category == d_cat][["zipcode", x]].rename(
            columns={x: "placebo_dens"})
        j = focal.merge(dd, on="zipcode", how="inner").dropna()
        if len(j) < MIN_ZIPS:
            continue
        try:
            bs[d_cat] = abs(fit_one(j, y, "placebo_dens", bandwidth_m)["beta_std"])
        except Exception as exc:  # noqa: BLE001 -- a singular placebo is dropped
            print(f"  placebo {cat} ~ {d_cat}: skipped ({exc})")
            continue
    if not bs:
        return {"p90": None, "n": 0, "max": None, "betas": {}}
    v = np.array(list(bs.values()), float)
    return {"p90": float(np.quantile(v, PLACEBO_QUANTILE)), "n": len(v),
            "max": float(v.max()), "median": float(np.median(v)),
            "betas": {k: float(x) for k, x in sorted(bs.items())}}


def classify(beta: float, t_conley: float, lozo_stability: float,
             placebo_p90: float | None, beta_std: float | None = None
             ) -> tuple[str, list[str]]:
    """THE RULE, in code. Returns (regime, reasons it fell short).

    clustering  : beta > 0 and all three tests pass
    saturating  : beta < 0 and all three tests pass
    no_signal   : anything else -- the sign is NEVER forced

    Three tests, each killing a different failure mode:
      T1  |t_Conley| >= 1.96   -- not noise, on the SE that respects spatial
                                 autocorrelation (HC3 would pass more often)
      T2  LOZO sign stability >= 0.90 -- not one ZIP
      T3  |beta_std| > placebo p90 -- not the generic "this ZIP grew" factor.
          Standardized on both sides so the comparison is like for like.
    """
    b_cmp = beta if beta_std is None else beta_std
    fails = []
    if not np.isfinite(t_conley) or abs(t_conley) < T_GATE:
        fails.append(f"T1 |t_Conley| = {abs(t_conley):.2f} < {T_GATE}")
    if lozo_stability < LOZO_SIGN_GATE:
        fails.append(f"T2 LOZO sign stability {lozo_stability:.2f} < {LOZO_SIGN_GATE}")
    if placebo_p90 is None:
        fails.append("T3 placebo did not run")
    elif abs(b_cmp) <= placebo_p90:
        fails.append(f"T3 |beta_std| {abs(b_cmp):.3f} <= placebo p90 {placebo_p90:.3f}")
    if fails or beta == 0:
        return "no_signal", fails
    return ("clustering" if beta > 0 else "saturating"), []


# ------------------------------------------------------------------- the fit

def _usable(panel: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    """Which categories have enough base-year signal to be fitted at all."""
    usable, skipped = [], {}
    for cat, g in panel.groupby("category"):
        d = g.dropna(subset=["g_log", "log_dens13", *CONTROLS])
        n_present = int((d.estab13 > 0).sum())
        if len(d) < MIN_ZIPS:
            skipped[cat] = f"only {len(d)} usable ZIPs (need {MIN_ZIPS})"
        elif n_present < MIN_NONZERO_BASE:
            skipped[cat] = (f"present in only {n_present} ZIPs in {BASE_YEAR} "
                            f"(need {MIN_NONZERO_BASE}); ZBP is employer-only, so a "
                            "non-employer trade is invisible in the base year")
        else:
            usable.append(cat)
    return usable, skipped


def estimate_form(panel: pd.DataFrame, usable: list[str], form: str,
                  bandwidth_m: float) -> dict:
    """Every usable category under ONE functional form, with the full
    apparatus: Conley + HC3 SEs, Moran's I, leave-one-ZIP-out sign stability,
    the placebo distribution, and the classification."""
    f = FORMS[form]
    out: dict[str, dict] = {}
    for cat in usable:
        d = panel[panel.category == cat].dropna(
            subset=[f["y"], f["x"], *CONTROLS]).reset_index(drop=True)
        fit_ = fit_one(d, f["y"], f["x"], bandwidth_m)
        lozo = lozo_sign_stability(d, f["y"], f["x"], bandwidth_m)
        plc = placebo_betas(panel, cat, usable, f["y"], bandwidth_m, x=f["x"])
        reg, fails = classify(fit_["beta"], fit_["t_conley"], lozo["stability"],
                              plc["p90"], beta_std=fit_["beta_std"])
        out[cat] = {**fit_, "lozo": lozo, "placebo": plc, "regime": reg,
                    "not_classified_because": fails,
                    "estab13": int(d.estab13.sum()), "estab23": int(d.estab23.sum())}
    return out


def form_gate_failures(cats: dict) -> list[str]:
    """Why a FORM may not be shipped. Empty == this form is admissible.

    Three criteria, and all three are about whether the estimate is
    WELL-FORMED, never about which answer it reached:

      (a) the placebo ran, on at least three comparisons, for every fitted
          category -- a classification whose T3 was vacuous is not a
          classification;
      (b) at least one category carries a SIGNAL regime, so a table in which
          everything is `no_signal` is reported as the null result it is
          rather than written out as a coefficient table;
      (c) every fitted category carries a regime from REQUIRED_REGIMES, so a
          caller can never read an unclassified row as a classified one;
      (d) the estimated betas are not UNANIMOUS in sign across every fitted
          category (see REJECT_UNANIMOUS_SIGN) -- symmetric, so it forces no
          sign, and it is what separates a category-specific coefficient from
          a common factor or a transform artifact.

    See REQUIRED_REGIMES for the 2026-09-11 relaxation and its reasoning: an
    earlier version additionally demanded a `clustering` category, which
    forced a sign at the portfolio level and suppressed eight sound saturating
    verdicts because the panel happens to contain no clustering one."""
    bad = []
    if not cats:
        return ["no category was fitted at all"]
    regimes = {c["regime"] for c in cats.values()}
    unknown = sorted(regimes - set(REQUIRED_REGIMES))
    if unknown:
        bad.append(f"categories carry regimes outside {list(REQUIRED_REGIMES)}: {unknown}")
    if not (regimes & set(SIGNAL_REGIMES)):
        bad.append(f"no category carries a signal regime "
                   f"({' or '.join(SIGNAL_REGIMES)}); every category is no_signal, "
                   "which is a null result and not a coefficient table")
    no_placebo = [c for c, v in cats.items()
                  if v["placebo"]["p90"] is None or v["placebo"]["n"] < 3]
    if no_placebo:
        bad.append("placebo did not run (or ran on < 3 comparisons) for: "
                   + ", ".join(sorted(no_placebo)))
    signs = {np.sign(v["beta"]) for v in cats.values() if "beta" in v}
    if REJECT_UNANIMOUS_SIGN and len(cats) >= 3 and len(signs) == 1:
        only = "positive" if signs == {1.0} else "negative"
        bad.append(f"beta is {only} for ALL {len(cats)} fitted categories; "
                   "sixteen unrelated retail categories cannot all reward (or "
                   "all punish) incumbent density, so this form has measured a "
                   "common factor or its own transform, not a category-specific "
                   "coefficient")
    return bad


def choose_form(forms: dict) -> tuple[str | None, dict]:
    """Apply the PRE-STATED preference order and return (adopted, why).

    `log` is the primary. It is demoted ONLY by failing its own gate, and the
    reason is recorded in the shipped YAML so the promotion of `level` is
    auditable rather than a post-hoc preference. If no form is admissible,
    `fit` exits non-zero and writes nothing.

    Why the log form can fail here, and it is not a bug: its dependent variable
    is PROPORTIONAL growth, whose base is the regressor itself, so a ZIP with 5
    bars that adds 5 reads +69% while a ZIP with 100 bars that adds 5 reads
    +5%. When a category grows citywide by roughly a constant number of
    establishments per resident, log growth is mechanically decreasing in the
    base count for every category at once -- which is exactly the "every beta
    negative" signature that demotes it. The level form asks the question the
    grade actually needs ("did dense ZIPs add MORE establishments"), and its
    own mean-reversion bias still runs toward saturation, so a positive
    (clustering) level coefficient survived a bias working against it."""
    why = {}
    for name in FORM_ORDER:
        bad = form_gate_failures(forms[name]["categories"])
        why[name] = bad
        if not bad:
            return name, why
    return None, why


def estimate(panel: pd.DataFrame, bandwidth_m: float = CONLEY_BANDWIDTH_M) -> dict:
    """Estimate BOTH forms for every category. Pure of IO."""
    usable, skipped = _usable(panel)
    forms = {name: {"categories": estimate_form(panel, usable, name, bandwidth_m),
                    **FORMS[name]}
             for name in FORM_ORDER}
    adopted, why = choose_form(forms)
    return {"forms": forms, "adopted_form": adopted, "form_gate": why,
            "skipped": skipped, "bandwidth_m": float(bandwidth_m),
            "categories": forms[adopted]["categories"] if adopted else {}}


def gate_failures(result: dict) -> list[str]:
    """Why this estimate may NOT overwrite the YAML. Empty == ship.

    Delegates to `form_gate_failures` under the pre-stated preference order:
    the estimate ships if EITHER form is admissible, and the YAML records which
    one and why the other was not."""
    if result.get("adopted_form"):
        return []
    return [f"form `{k}`: " + "; ".join(v) for k, v in result["form_gate"].items()
            if v]


def _fitted_on(panel: pd.DataFrame, acs_vintages: dict) -> dict:
    zips = sorted(panel.zipcode.unique())
    return {
        "panel": f"ZBP {BASE_YEAR}→{END_YEAR}, ZCTA ACS {BASE_YEAR}/{END_YEAR}",
        "vintage": {
            "zbp_base": f"api.census.gov/data/{BASE_YEAR}/zbp (NAICS2012, EMPSZES 001)",
            "zbp_end": f"analysis.zip_category_establishments year={END_YEAR}",
            "acs_base": acs_vintages.get(BASE_YEAR),
            "acs_end": acs_vintages.get(END_YEAR),
            "crosswalk": "src/loci/zbp_naics.yaml",
            "geography": "PLUTO postcode; 11249 merged into 11211 both years",
        },
        "zip_universe_hash": zip_universe_hash(zips),
        "n_zips_universe": len(zips),
    }


def to_document(result: dict, panel: pd.DataFrame, acs_vintages: dict) -> dict:
    """The shipped YAML document. `fitted_on` is ONE object shared by every
    entry, so PyYAML emits it once and aliases it rather than repeating it 16
    times."""
    fo = _fitted_on(panel, acs_vintages)
    adopted = result["adopted_form"]
    if adopted is None:
        raise DensityElasticityGateFailure(
            "no functional form cleared its gate, so there is no document to "
            "write: " + "; ".join(gate_failures(result)))
    other = [f for f in FORM_ORDER if f != adopted]
    cats = {}
    for cat, v in sorted(result["categories"].items()):
        alt = {f: result["forms"][f]["categories"].get(cat, {}) for f in other}
        entry = {
            "beta": round(v["beta"], 6),
            "beta_std": round(v["beta_std"], 6),
            "sd_density_base": round(v["sd_x"], 6),
            "se_hc3": round(v["se_hc3"], 6),
            "se_conley": round(v["se_conley"], 6),
            "t_conley": round(v["t_conley"], 4),
            "t_hc3": round(v["t_hc3"], 4),
            "n_zips": v["n_zips"],
            "regime": v["regime"],
            "lozo_sign_stability": round(v["lozo"]["stability"], 4),
            "placebo_p90": (None if v["placebo"]["p90"] is None
                            else round(v["placebo"]["p90"], 6)),
            "placebo_n": v["placebo"]["n"],
            "placebo_compared_on": "standardized |beta x sd(regressor)|",
            "morans_i": (None if v["moran"]["i"] is None else round(v["moran"]["i"], 4)),
            "morans_p": v["moran"].get("p_perm"),
            "r_squared": round(v["r_squared"], 4),
            "estab_base": v["estab13"],
            "estab_end": v["estab23"],
            "not_classified_because": v["not_classified_because"] or None,
        }
        for f, a in alt.items():
            if a:
                entry[f"{f}_form_beta"] = round(a["beta"], 6)
                entry[f"{f}_form_t_conley"] = round(a["t_conley"], 4)
                entry[f"{f}_form_regime"] = a["regime"]
                entry[f"{f}_form_agrees_on_sign"] = bool(
                    np.sign(a["beta"]) == np.sign(v["beta"]))
        entry["fitted_on"] = fo
        cats[cat] = entry
    for cat, why in sorted(result["skipped"].items()):
        cats[cat] = {"regime": "not_fitted", "not_fitted_because": why, "fitted_on": fo}
    return {
        "version": 1,
        "fitted_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "disclaimer": DISCLAIMER,
        "adopted_form": adopted,
        "form": FORMS[adopted]["label"] + " + dlog_pop + log_pop_base + log_inc_base "
                "+ dlog_inc + borough_FE",
        "beta_units": FORMS[adopted]["units"],
        "form_preference_order": list(FORM_ORDER),
        "forms_rejected": {f: (result["form_gate"].get(f) or None) for f in other},
        "inference": (f"HC3 and Conley spatial-HAC (Bartlett, "
                      f"{result['bandwidth_m']:.0f} m, unit-weighted ZCTA centroids); "
                      "classification reads the Conley t only"),
        "rule": {
            "t_gate": T_GATE, "lozo_sign_gate": LOZO_SIGN_GATE,
            "placebo_quantile": PLACEBO_QUANTILE,
            "text": ("clustering if beta > 0, saturating if beta < 0, and only if "
                     "|t_Conley| >= t_gate AND lozo_sign_stability >= lozo_sign_gate "
                     "AND |beta| > placebo p90; else no_signal. The sign is never "
                     "forced."),
        },
        "fitted_on": fo,
        "categories": cats,
    }


def write_if_gate_passes(doc: dict, result: dict,
                         path: pathlib.Path | None = None) -> pathlib.Path:
    """Gate first, write second -- the D63 order. A failed re-fit leaves the
    previous YAML exactly as it was, so the degradation is "yesterday's
    coefficients, explicitly stale" rather than "today's, quietly invalid"."""
    bad = gate_failures(result)
    if bad:
        raise DensityElasticityGateFailure(
            "density elasticity failed its own gate: " + "; ".join(bad)
            + ". Nothing written.")
    p = path or YAML_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_HEADER + yaml.safe_dump(doc, sort_keys=False, width=88))
    return p


def fit(*, bandwidth_m: float = CONLEY_BANDWIDTH_M, dry_run: bool = False,
        path: pathlib.Path | None = None, con=None) -> tuple[dict, dict, pathlib.Path | None]:
    """Re-estimate from the warehouse + cached ACS/ZBP and write the YAML.

    Returns (document, raw result, written path or None). Raises
    `DensityElasticityGateFailure` -- writing nothing -- when the gate fails."""
    acs_paths = {y: fetch_zcta_acs(y) for y in (BASE_YEAR, END_YEAR)}
    geo = zip_geography()
    mnbk = sorted(geo.loc[geo.borough.isin(BOROUGHS), "zipcode"].unique())
    zbp_path = fetch_zbp_base(mnbk)
    own_con = con is None
    c = connect_read_only() if own_con else con
    try:
        est23 = establishments_2023(c)
    finally:
        if own_con:
            c.close()
    panel = build_panel(est23, _read_zbp_base(), _read_acs(BASE_YEAR),
                        _read_acs(END_YEAR), geo)
    result = estimate(panel, bandwidth_m)
    vint = {y: {"path": str(p.relative_to(REPO_ROOT)),
                "fetched_at": json.loads(p.read_text()).get("fetched_at")}
            for y, p in acs_paths.items()}
    vint["zbp_base_cache"] = str(zbp_path.relative_to(REPO_ROOT))
    # A failed gate must still be REPORTABLE: the caller gets the full result
    # and prints both forms' tables before exiting non-zero, because "which
    # criterion did it miss, and by how much" is the useful output of a refusal.
    if result["adopted_form"] is None:
        if dry_run:
            return None, result, None
        raise DensityElasticityGateFailure(
            "density elasticity failed its own gate: "
            + "; ".join(gate_failures(result)) + ". Nothing written.")
    doc = to_document(result, panel, vint)
    if dry_run:
        return doc, result, None
    return doc, result, write_if_gate_passes(doc, result, path)


# ------------------------------------------------------------------- readers

def load(path: pathlib.Path | None = None) -> dict:
    """Read the shipped YAML. Raises if it has never been fitted."""
    p = path or YAML_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"{p} does not exist -- run `loci density-elasticity fit` first")
    return yaml.safe_load(p.read_text())


def regime(category: str, doc: dict | None = None) -> str:
    """The regime for one category: clustering / saturating / no_signal /
    not_fitted. An UNKNOWN category raises -- a typo and "this category has no
    coefficient" must not look the same to a caller (the D63 `spec_for` habit)."""
    d = doc if doc is not None else load()
    cats = d.get("categories") or {}
    if category not in cats:
        raise ValueError(
            f"no density-elasticity entry for category {category!r}; "
            f"fitted set is {sorted(cats)}")
    return cats[category]["regime"]


_HEADER = '''# Density elasticity -- per-category clustering vs saturation (D68 / GTM-138).
# GENERATED by `loci density-elasticity fit`. Do not hand-edit: the gate in
# src/loci/model/density_elasticity.py is what earns a value the right to be here.
#
# WHAT IT IS: beta is the coefficient on log(2013 establishments per 1,000
# residents) in a regression of log establishment growth 2013->2023 across
# MN+BK ZIPs with 2013 population >= 5,000. beta > 0 = CLUSTERING (ZIPs already
# dense in the category added more of it). beta < 0 = SATURATION.
#
# WHAT IT IS NOT:
#  * NOT A FORECAST. D68 showed headroom has no out-of-sample skill; this is a
#    descriptive decade-average regime label and must never be extrapolated.
#  * NOT CAUSAL, and the bias has a direction: the 2013 count sits on both
#    sides of the equation, so measurement error pushes beta toward
#    "saturating". A CLUSTERING verdict is therefore the conservative one; a
#    SATURATING verdict is partly mean reversion and means "no evidence of
#    clustering", never "this category is full".
#  * NOT PER-CAPITA in substance: conditional on log_pop_base (a control),
#    log(density) is an affine function of log(count), so beta is the
#    coefficient on incumbents holding population fixed.
#  * ZIP GRAIN. 11215 fuses Park Slope with Gowanus, 11231 Red Hook with
#    Carroll Gardens; 11249 has no 2013 ZCTA and is merged into 11211 in both
#    years. A corridor inside a ZIP is invisible here.
#  * ZBP/CBP is EMPLOYER-ONLY (no sole proprietors) and noise-infused from
#    2017, so a single-digit ZIP cell is approximate.
#  * The 2017 NAICS 445110->445120 recode moved bodegas from grocery to
#    convenience between the two vintages. Trust `food_retail` (the two
#    combined) over either alone.
#  * Norms behind any downstream headroom are REVEALED SUPPLY (D6): what got
#    built, not what should have been.
#
# THIS SUPERSEDES D68's READING THAT BARS AND CAFES CLUSTER. On the same panel,
# with Conley SEs, leave-one-ZIP-out and a placebo distribution: CAFES FAIL THE
# PLACEBO -- beta is clean (+6.20, Conley t +4.83) but cafe growth is predicted
# as well by 2013 restaurant density (standardized 6.18) and hardware density
# (5.88) as by cafes' own (5.354 vs placebo p90 5.820), i.e. generic
# gentrification, not cafe-specific agglomeration. BARS FAIL SIGNIFICANCE --
# beta +3.47 but Conley t +1.63, under the 1.96 gate. D68's CHORE-CATEGORY
# conclusions STAND: grocery, laundry, hair, nails, fitness, clinic, bank and
# childcare all classify `saturating`, the divide-by-incumbents reading D68
# proposed for them.
#
# GATE HISTORY: until 2026-09-11 the gate also required at least one
# `clustering` category. Since no category clusters on this panel it refused to
# write at all, discarding eight sound saturating verdicts to enforce a
# conclusion. The owner ruled that a spec error -- it forces a sign at the
# portfolio level, which is what the per-category placebo exists to prevent --
# and the gate now only asks that the estimate be well-formed (every category
# classified, placebo run for each) and informative (at least one signal).
#
# HOW THE GRADE SHOULD USE `regime`:
#   saturating -> demand pool DIVIDED BY incumbents; incumbents count against
#                 the site; pipeline residents add to the numerator directly.
#   clustering -> incumbents count IN FAVOUR; the cap is NOT headcount but
#                 spend per resident by age and income (spend.yaml, plus the
#                 D63 age curve where one exists). A headcount norm said
#                 Greenpoint had no bar headroom in 2013; it added 12.
#   no_signal  -> residents only. The incumbent count must not enter the score
#                 in either direction.
#   not_fitted -> no coefficient exists. NULL is not 1.0 and not 0.
#
'''
