"""The supply model and the residual — the heart of the thesis (GTM-33/34/35).

The raw DNCI is endogenous: retail follows rooftops, so it tracks density and
wealth. We regress DNCI on the things that legitimately explain retail supply —
population density, income, transit access, commercial zoning capacity — plus
borough fixed effects. The RESIDUAL is the signal: strongly negative = a hex with
materially less daily-needs retail than otherwise-comparable places. That, not the
raw count, is the opportunity (CONTEXT.md §1.3, §4.5).

Only inhabited hexes enter the model (demographics present) — a park or rail yard
has no "retail gap". Moran's I on the residuals is mandatory (§4.5): OLS standard
errors on gridded data are wrong if residuals are spatially autocorrelated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

HEX_KM2 = 0.105  # H3 res-9 average cell area


def build_supply_model(con, threshold: int = 10, model_version: str = "dnci-v1"):
    df = con.execute(
        """
        SELECT d.h3_index, d.dnci, h.borough, h.land_fraction,
               dm.population, dm.median_hh_income,
               c.comm_far_capacity, c.walk_m_to_subway, c.dev_headroom
        FROM analysis.hex_dnci d
        JOIN analysis.hex h USING(h3_index)
        JOIN analysis.hex_demographics dm USING(h3_index)
        LEFT JOIN analysis.hex_controls c USING(h3_index)
        WHERE d.threshold_min = ? AND d.model_version = ? AND dm.population > 0
        """, [threshold, model_version]).df()

    df = df.dropna(subset=["median_hh_income"]).copy()
    df["pop_density"] = df["population"] / (HEX_KM2 * df["land_fraction"])
    df["log_density"] = np.log1p(df["pop_density"])
    df["log_income"] = np.log(df["median_hh_income"].clip(lower=1))
    df["transit_access"] = np.exp(-df["walk_m_to_subway"].fillna(3000.0) / 800.0)
    df["comm_far"] = df["comm_far_capacity"].fillna(0.0)

    feats = ["log_density", "log_income", "transit_access", "comm_far", "land_fraction"]
    boro = pd.get_dummies(df["borough"], prefix="boro", drop_first=True).astype(float)
    X = sm.add_constant(pd.concat([df[feats], boro], axis=1))
    y = df["dnci"]
    model = sm.OLS(y, X).fit()

    df["predicted"] = model.predict(X).clip(0, 1)
    df["residual"] = y - df["predicted"]
    df["opportunity"] = ((-df["residual"]).clip(lower=0)
                         * df["transit_access"]
                         * df["dev_headroom"].fillna(0.0).clip(lower=0))

    con.register("_res", df[["h3_index", "predicted", "residual", "opportunity"]])
    con.execute(
        """UPDATE analysis.hex_dnci d
           SET dnci_predicted = r.predicted, residual = r.residual, opportunity = r.opportunity
           FROM _res r
           WHERE d.h3_index = r.h3_index AND d.threshold_min = ? AND d.model_version = ?""",
        [threshold, model_version])
    con.unregister("_res")
    return model, df


def morans_i(df: pd.DataFrame, con):
    """Moran's I of the residuals over a KNN(6) hex graph. Returns (I, p_sim)."""
    from libpysal.weights import KNN
    from esda.moran import Moran
    coords = con.execute(
        "SELECT ST_X(centroid), ST_Y(centroid) FROM analysis.hex WHERE h3_index = ANY(?)",
        [df["h3_index"].tolist()]).fetchall()
    # keep order aligned with df
    cmap = {h: (x, y) for h, (x, y) in zip(
        con.execute("SELECT h3_index FROM analysis.hex WHERE h3_index = ANY(?)",
                    [df["h3_index"].tolist()]).df()["h3_index"], coords)}
    xy = np.array([cmap[h] for h in df["h3_index"]])
    w = KNN.from_array(xy, k=6)
    w.transform = "r"
    mi = Moran(df["residual"].values, w, permutations=199)
    return mi.I, mi.p_sim
