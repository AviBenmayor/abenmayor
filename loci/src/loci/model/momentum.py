"""ACS income & college-share momentum, 2013 -> 2023.

The direct measure Axis 2 v1 was missing: are *higher-income, higher-education
residents actually arriving*? Pulls ACS 5-year 2013 (2009-13) and 2023 (2019-23)
at tract level for three boroughs, aggregates to neighborhood (NTA), and reports
the real change.

Two things done right, or the story would be wrong:
  * INCOME IS DEFLATED. 2013 dollars are inflated to 2023 dollars (CPI-U
    232.957 -> 304.702, x1.308). Nominal income "grew" ~30% everywhere just from
    inflation; only the REAL change says who actually got richer.
  * MEAN, NOT MEDIAN, so it aggregates. Uses aggregate household income
    (B19025) / households (B11001) — median-of-medians is not a real number.
    Comparable across the two tract vintages because both are re-aggregated to the
    same 2020 NTA polygons via each year's own tract centroids (Census gazetteer).

College share = bachelor's+ (B15003 022..025) / population 25+ (B15003_001).
"""
from __future__ import annotations

import io
import json
import pathlib

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

KEY = open(".env").read().split("CENSUS_API_KEY=")[1].split("\n")[0].strip()
COUNTIES = {"047": "Brooklyn", "061": "Manhattan", "081": "Queens"}
CPI = {2013: 232.957, 2023: 304.702}
DEFLATE = CPI[2023] / CPI[2013]
NTA = "data/raw/boundaries/nyc_nta2020.geojson"
OUT = pathlib.Path("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor-loci/"
                   "b495b991-3549-4a4b-9741-40b94faa1a15/scratchpad/momentum.json")

BACH = ["B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"]
VARS = ["B19025_001E", "B11001_001E", "B15003_001E", *BACH, "B01003_001E"]


def _pull(year: int) -> pd.DataFrame:
    frames = []
    for cty in COUNTIES:
        url = (f"https://api.census.gov/data/{year}/acs/acs5"
               f"?get=NAME,{','.join(VARS)}&for=tract:*&in=state:36+county:{cty}&key={KEY}")
        j = requests.get(url, timeout=60).json()
        df = pd.DataFrame(j[1:], columns=j[0])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    for v in VARS:
        df[v] = pd.to_numeric(df[v], errors="coerce")
    df = df[df[v].notna() | True]
    df["geoid"] = df.state + df.county + df.tract
    df["pop25"] = df["B15003_001E"]
    df["bach"] = df[BACH].sum(axis=1)
    df["agg_inc"] = df["B19025_001E"]
    df["hh"] = df["B11001_001E"]
    df["pop"] = df["B01003_001E"]
    return df[["geoid", "county", "agg_inc", "hh", "pop25", "bach", "pop"]]


def _centroids(year: int) -> pd.DataFrame:
    url = (f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
           f"{year}_Gazetteer/{year}_gaz_tracts_36.txt")
    txt = requests.get(url, timeout=60).content.decode("latin-1")
    g = pd.read_csv(io.StringIO(txt), sep="\t", dtype=str)
    g.columns = [c.strip() for c in g.columns]
    g["geoid"] = g["GEOID"].str.strip()
    g["lat"] = pd.to_numeric(g["INTPTLAT"], errors="coerce")
    lon_col = [c for c in g.columns if c.startswith("INTPTLONG") or c.startswith("INTPTLON")][0]
    g["lon"] = pd.to_numeric(g[lon_col], errors="coerce")
    return g[["geoid", "lat", "lon"]]


def _to_nta(df: pd.DataFrame, cent: pd.DataFrame, nta: gpd.GeoDataFrame) -> pd.DataFrame:
    m = df.merge(cent, on="geoid", how="inner")
    g = gpd.GeoDataFrame(m, geometry=[Point(x, y) for x, y in zip(m.lon, m.lat)], crs=4326)
    g = gpd.sjoin(g, nta, how="inner", predicate="within")
    # income: only tracts with BOTH aggregate income and households reported
    # (a suppressed-income tract counted as $0 would fake a poverty crash)
    gi = g[g.agg_inc.notna() & (g.hh > 0)]
    inc = gi.groupby(["boroname", "ntaname"]).agg(agg_inc=("agg_inc", "sum"), hh=("hh", "sum"),
                                                  pop=("pop", "sum")).reset_index()
    inc["mean_inc"] = inc.agg_inc / inc.hh
    # college: only tracts with education base reported
    ge = g[g.bach.notna() & (g.pop25 > 0)]
    col = ge.groupby("ntaname").agg(bach=("bach", "sum"), pop25=("pop25", "sum")).reset_index()
    col["college"] = col.bach / col.pop25
    return inc.merge(col[["ntaname", "college"]], on="ntaname", how="inner")


def run() -> None:
    nta = gpd.read_file(NTA).to_crs(4326)
    nta = nta[nta["boroname"].isin(["Brooklyn", "Manhattan", "Queens"])][["boroname", "ntaname", "geometry"]]
    print("pulling ACS 2013 + 2023 (3 boroughs)...", flush=True)
    a13 = _to_nta(_pull(2013), _centroids(2013), nta)
    a23 = _to_nta(_pull(2023), _centroids(2023), nta)
    a13["inc13_real"] = a13.mean_inc * DEFLATE
    m = a13[["boroname", "ntaname", "inc13_real", "college", "pop"]].rename(
        columns={"college": "coll13", "pop": "pop13"}).merge(
        a23[["ntaname", "mean_inc", "college", "pop"]].rename(
            columns={"mean_inc": "inc23", "college": "coll23", "pop": "pop23"}),
        on="ntaname", how="inner")
    import numpy as np
    m = m[(m.pop13 > 500) & (m.pop23 > 500) & (m.inc13_real > 10000) & np.isfinite(m.inc23) & np.isfinite(m.inc13_real)]
    m["d_inc_pct"] = (m.inc23 - m.inc13_real) / m.inc13_real * 100
    m["d_coll_pp"] = (m.coll23 - m.coll13) * 100          # percentage points
    m["d_pop_pct"] = (m.pop23 - m.pop13) / m.pop13 * 100
    m = m.sort_values("d_inc_pct", ascending=False).reset_index(drop=True)

    print(f"\ndeflator 2013->2023 = x{DEFLATE:.3f}; citywide (3-boro) real mean-income change: "
          f"{(m.inc23.sum()/ m.inc13_real.sum()-1)*100:+.1f}%\n")
    def show(rows, title):
        print(f"=== {title} ===")
        print(f"{'nta':38} {'boro':4} {'inc13→23 (real)':>20} {'Δinc':>6} {'Δcoll':>6} {'Δpop':>6}")
        for _, r in rows.iterrows():
            print(f"{r.ntaname[:38]:38} {r.boroname[:3]:4} "
                  f"{('$'+format(int(r.inc13_real),',')):>9}→{('$'+format(int(r.inc23),',')):<9} "
                  f"{r.d_inc_pct:>+5.0f}% {r.d_coll_pp:>+5.0f} {r.d_pop_pct:>+5.0f}%")
    show(m.head(15), "BIGGEST REAL-INCOME GAINERS (gentrification hotspots)")
    print()
    show(m.tail(10).iloc[::-1], "BIGGEST REAL-INCOME LOSERS")

    OUT.write_text(m.to_json(orient="records"))
    print(f"\nwrote {OUT}  ({len(m)} NTAs)")


if __name__ == "__main__":
    run()
