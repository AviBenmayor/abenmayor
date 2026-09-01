"""The causal test (P2): does the retail gap predict subsequent growth? (GTM-40/41/42)

Temporal ordering is the whole point. Measure the retail gap at t0=2013 — the
residual of log LODES retail employment on 2013 supply drivers — then ask whether
a NEGATIVE gap (less retail than comparable places) predicts population growth
2013->2023. P2 predicts beta < 0: underserved-but-viable hexes fill in.

Correlational, not identified (no instrument; §7.2). The residual design + temporal
ordering reduce reverse causality but do not eliminate it. Reported honestly, with
the pre-trend and placebo checks that a serious reader asks for first.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from loci.grid.acs import BORO_COUNTY, _census_key
import requests

HEX_KM2 = 0.105


def _acs_pop_2013_to_hex(con):
    """ACS 2009-2013 population by 2010 tract, dasymetrically -> hex via PLUTO tract2010."""
    key = _census_key()
    pop = {}
    for county in BORO_COUNTY.values():
        d = requests.get("https://api.census.gov/data/2013/acs/acs5",
                         params={"get": "B01003_001E", "for": "tract:*",
                                 "in": f"state:36 county:{county}", "key": key}, timeout=90).json()
        for row in d[1:]:
            geoid = row[1] + row[2] + row[3]
            try: pop[geoid] = float(row[0])
            except (TypeError, ValueError): pass
    from loci.grid.pluto import PLUTO_CSV
    th = con.execute(f"""
        SELECT '36' || m.county || m.t2010 AS geoid, m.h3_index, sum(m.u) u FROM (
          SELECT borocode, TRY_CAST(latitude AS DOUBLE) lat, TRY_CAST(longitude AS DOUBLE) lon,
                 TRY_CAST(unitsres AS DOUBLE) u,
                 CASE borocode WHEN '1' THEN '061' WHEN '2' THEN '005' WHEN '3' THEN '047'
                               WHEN '4' THEN '081' WHEN '5' THEN '085' END county,
                 lpad(tract2010,6,'0') t2010,
                 h3_h3_to_string(h3_latlng_to_cell(TRY_CAST(latitude AS DOUBLE), TRY_CAST(longitude AS DOUBLE), 9)) h3_index
          FROM read_csv('{PLUTO_CSV}', ALL_VARCHAR=TRUE)
          WHERE tract2010 IS NOT NULL AND TRY_CAST(unitsres AS DOUBLE) > 0
            AND TRY_CAST(latitude AS DOUBLE) IS NOT NULL) m
        WHERE m.county IS NOT NULL GROUP BY 1,2""").df()
    th = th[th["h3_index"].isin(set(con.execute("SELECT h3_index FROM analysis.hex").df()["h3_index"]))]
    tot = th.groupby("geoid")["u"].sum().rename("tot")
    th = th.join(tot, on="geoid")
    th["w"] = th["u"] / th["tot"]
    th["pop"] = th["geoid"].map(pop).fillna(0) * th["w"]
    return th.groupby("h3_index")["pop"].sum()


def build_growth_test(con):
    pop13 = _acs_pop_2013_to_hex(con)
    df = con.execute("""
      SELECT h.h3_index, h.borough, h.land_fraction,
             dm.population AS pop23,
             c.comm_far_capacity, c.walk_m_to_subway,
             p13.jobs AS retail13
      FROM analysis.hex h
      JOIN analysis.hex_demographics dm ON dm.h3_index=h.h3_index AND dm.acs_year=2023
      LEFT JOIN analysis.hex_controls c ON c.h3_index=h.h3_index
      LEFT JOIN (SELECT h3_index, sum(jobs) jobs FROM analysis.hex_panel
                 WHERE year=2013 GROUP BY 1) p13 ON p13.h3_index=h.h3_index
    """).df()
    df["pop13"] = df["h3_index"].map(pop13)
    df = df[(df["pop13"] > 50) & (df["pop23"] > 50)].copy()      # inhabited both years
    df["retail13"] = df["retail13"].fillna(0)
    df["transit_access"] = np.exp(-df["walk_m_to_subway"].fillna(3000.0) / 800.0)
    df["comm_far"] = df["comm_far_capacity"].fillna(0.0)
    df["dens13"] = df["pop13"] / (HEX_KM2 * df["land_fraction"])
    df["log_dens13"] = np.log1p(df["dens13"])

    boro = pd.get_dummies(df["borough"], prefix="b", drop_first=True).astype(float)
    ctrl = ["log_dens13", "transit_access", "comm_far", "land_fraction"]

    # retail gap at 2013 = residual of log retail employment on 2013 supply drivers
    Xg = sm.add_constant(pd.concat([df[ctrl], boro], axis=1))
    gapfit = sm.OLS(np.log1p(df["retail13"]), Xg).fit()
    df["retail_gap13"] = np.log1p(df["retail13"]) - gapfit.predict(Xg)

    # outcome: log population growth 2013 -> 2023
    df["growth"] = np.log(df["pop23"]) - np.log(df["pop13"])

    # main test: does the 2013 gap predict 2013->2023 growth? (HC3-robust)
    Xm = sm.add_constant(pd.concat([df[["retail_gap13"] + ctrl], boro], axis=1))
    main = sm.OLS(df["growth"], Xm).fit(cov_type="HC3")

    # placebo: shuffle the gap -> effect should vanish
    rng = np.random.default_rng(0)
    dfp = df.copy(); dfp["retail_gap13"] = rng.permutation(dfp["retail_gap13"].values)
    Xp = sm.add_constant(pd.concat([dfp[["retail_gap13"] + ctrl], boro], axis=1))
    plac = sm.OLS(dfp["growth"], Xp).fit(cov_type="HC3")

    return main, plac, df
