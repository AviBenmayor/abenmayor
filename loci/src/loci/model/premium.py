"""Axis 3 — premium / destination-amenity opportunity screen (E6).

INVERTS the daily-needs gap screen (CONTEXT §11). Daily needs are convenience
goods → walkable, "missing what ≥80% of peers have." Premium amenities (spa,
padel, boutique fitness) are DESTINATION goods people travel for, and rare by
nature → a prevalence-gap screen is meaningless. So this scores, per neighborhood
catchment: a *premium demand pool* (affluent + educated residents) minus the
existing supply reachable in that catchment. High demand + low supply = opportunity.

v1 scope (what is built here):
  * Supply from the cached Foursquare NYC extract (fresh rows only), clean leaves.
  * Demand = affluent-educated resident pool per NTA (income × college × pop).
  * Catchment = straight-line radius around the NTA centroid.
Deferred to their own E6 tickets: drive-time / transit isochrones (GTM-71), the
large-format feasibility gate (GTM-73), Google ground-truth validation (GTM-70).

DATA-HOLE FINDING (GTM-70): **padel = 0 rows** in Foursquare — it barely existed
before 2022, so it cannot be screened from standard sources at all. Padel demand
is scored, but its "supply" must come from Google / a manual web check. This is
the charter's "undercount worse than §7.1" made concrete.
"""
from __future__ import annotations

import json
import math
import pathlib

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[3]
FSQ = ROOT / "data" / "raw" / "fsq_places_nyc.parquet"
NTA = ROOT / "data" / "raw" / "boundaries" / "nyc_nta2020.geojson"
PANEL = ("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor/"
         "87470c85-2596-49c9-a8e9-2f0429772416/scratchpad/nta_trajectory.json")
OUT = pathlib.Path("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor-loci/"
                   "87470c85-2596-49c9-a8e9-2f0429772416/scratchpad/premium_shortlist.json")

FRESH = "2024-01-01"   # FSQ ghost gate (session 8c): keep only recently-refreshed rows

# category -> (FSQ leaf substrings that ARE this category, catchment km, demand target note)
PREMIUM = {
    "spa":              (["Health and Beauty Service > Spa"], 3.0, "affluent, 30-55"),
    "boutique_fitness": (["Gym and Studio > Pilates Studio", "Gym and Studio > Yoga Studio",
                          "Gym and Studio > Boxing Gym", "Gym and Studio > Climbing Gym"],
                         2.5, "affluent, young, educated"),
    "padel":            ([], 8.0, "affluent, athletic, 25-44"),   # DATA HOLE — 0 supply rows
}


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = map(math.radians, (lat1, lat2))
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _supply(con, leaves: list[str]) -> np.ndarray:
    if not leaves:
        return np.empty((0, 2))
    like = " OR ".join([f"cast(fsq_category_labels as varchar) like '%{l}%'" for l in leaves])
    rows = con.execute(f"""
        SELECT latitude, longitude FROM read_parquet('{FSQ}')
        WHERE ({like}) AND latitude IS NOT NULL
          AND cast(date_refreshed as varchar) >= '{FRESH}'""").fetchall()
    return np.array([[r[0], r[1]] for r in rows], dtype=float)


def _feasibility(g: gpd.GeoDataFrame) -> pd.DataFrame:
    """Per NTA, count PLUTO lots that can physically host each amenity's FOOTPRINT.
    Padel needs a big lot + height (warehouse/flex, C or M zoning); a spa fits mid-size
    commercial/retail space; boutique fitness sits between. This is the large-format gate:
    an affluent neighborhood of small brownstone lots can host a spa but NOT a padel box."""
    from loci.grid.pluto import PLUTO_CSV
    con = duckdb.connect()
    lots = con.execute(f"""
        SELECT try_cast(latitude AS DOUBLE) lat, try_cast(longitude AS DOUBLE) lon,
               try_cast(lotarea AS DOUBLE) lotarea, try_cast(bldgarea AS DOUBLE) bldgarea,
               try_cast(retailarea AS DOUBLE) retailarea, try_cast(commfar AS DOUBLE) commfar,
               upper(left(coalesce(zonedist1,''),1)) zc
        FROM read_csv('{PLUTO_CSV}', ALL_VARCHAR=TRUE)
        WHERE borocode IN ('1','3','4') AND try_cast(latitude AS DOUBLE) IS NOT NULL
          AND (try_cast(lotarea AS DOUBLE) >= 3000 OR try_cast(retailarea AS DOUBLE) >= 2000)""").df()
    lots = lots.fillna({"lotarea": 0, "bldgarea": 0, "retailarea": 0, "commfar": 0})
    pts = gpd.GeoDataFrame(lots, geometry=gpd.points_from_xy(lots.lon, lots.lat), crs=4326)
    j = gpd.sjoin(pts, g[["ntaname", "geometry"]], how="inner", predicate="within")
    comm = j.zc.isin(["C", "M"]) | (j.commfar > 0)
    j["f_padel"] = ((j.lotarea >= 15000) & comm).astype(int)                       # big + height
    j["f_spa"] = ((j.retailarea >= 2500) | ((j.commfar > 0) & (j.bldgarea >= 3000))).astype(int)
    j["f_boutique_fitness"] = (((j.lotarea >= 5000) & comm) | (j.retailarea >= 4000)).astype(int)
    return j.groupby("ntaname")[["f_padel", "f_spa", "f_boutique_fitness"]].sum().reset_index()


def run() -> None:
    con = duckdb.connect()
    g = gpd.read_file(NTA)
    g = g[g.boroname.isin(["Brooklyn", "Manhattan", "Queens"])].copy()
    cent = g.geometry.centroid
    nta = pd.DataFrame({"nta": g.ntaname.values, "boro": g.boroname.values,
                        "lat": cent.y.values, "lon": cent.x.values})
    panel = json.load(open(PANEL))
    p23 = {r["ntaname"]: r for r in panel if r["year"] == 2023}
    nta["mat"] = nta.nta.map(lambda n: p23.get(n, {}).get("maturity", np.nan))
    nta["pop"] = nta.nta.map(lambda n: p23.get(n, {}).get("pop", np.nan))
    nta = nta.dropna(subset=["mat", "pop"]).reset_index(drop=True)
    # premium demand pool: the premium consumer concentrates HARD at the top of the
    # affluence+education curve, so weight population by maturity CUBED (a moderate-income
    # area barely counts; a spa/padel market is the affluent-educated core, not raw headcount).
    nta["pool"] = nta["pop"] * (np.clip(nta.mat, 0, 100) / 100) ** 3

    # large-format feasibility per NTA (PLUTO) — can you physically put this amenity here?
    feas = _feasibility(g)
    nta = nta.merge(feas, left_on="nta", right_on="ntaname", how="left")
    for c in ["f_padel", "f_spa", "f_boutique_fitness"]:
        nta[c] = nta[c].fillna(0).astype(int)

    # precompute pairwise NTA distances (km) once
    la, lo = nta.lat.values, nta.lon.values
    D = np.array([[_haversine_km(la[i], lo[i], la[j], lo[j]) for j in range(len(nta))]
                  for i in range(len(nta))])

    out = {}
    for cat, (leaves, R, target) in PREMIUM.items():
        sup = _supply(con, leaves)
        demand = np.array([nta.pool.values[D[i] <= R].sum() for i in range(len(nta))])
        if len(sup):
            supply = np.array([int(np.sum(
                (np.abs(sup[:, 0] - la[i]) < R / 90) &  # cheap bbox prefilter
                (np.array([_haversine_km(la[i], lo[i], s[0], s[1]) for s in sup]) <= R)))
                for i in range(len(nta))])
        else:
            supply = np.zeros(len(nta), dtype=int)
        # unmet premium demand = pool in the catchment beyond what current supply serves.
        # PER = citywide premium-pool per facility (the market's average loading); a catchment
        # with more pool than PER×(its facilities) is under-served. (Zero-supply no longer explodes.)
        per = demand.sum() / max(supply.sum(), 1)
        opp = demand - per * supply
        feasible = nta[f"f_{cat}"].values                    # large-format sites in the NTA
        # GATE: no site you can physically build the amenity on → not an opportunity, whatever the demand
        gated = np.where(feasible > 0, opp, -np.inf)
        order = np.argsort(-gated)
        dropped = int(((opp > np.median(opp[opp > 0])) & (feasible == 0)).sum())  # demand-rich but unbuildable
        hole = " ⚠ DATA HOLE (0 supply rows — screen supply via Google/manual)" if not len(sup) else ""
        print(f"\n=== {cat.upper()}  (catchment {R:.0f} km, {len(sup)} supply POIs, target: {target}){hole} ===")
        print(f"{'#':>2} {'neighborhood':34}{'boro':4}{'demand':>8}{'supply':>7}{'sites':>6}{'opp':>8}")
        for k, i in enumerate(order[:10], 1):
            r = nta.iloc[i]
            print(f"{k:>2} {r.nta[:34]:34}{r.boro[:3]:4}{int(demand[i]):>8,}{int(supply[i]):>7}"
                  f"{int(feasible[i]):>6}{opp[i]:>8,.0f}")
        print(f"   ({dropped} demand-rich NTAs dropped by the feasibility gate — no large-format site)")
        out[cat] = [{"nta": nta.iloc[i].nta, "boro": nta.iloc[i].boro, "demand": int(demand[i]),
                     "supply": int(supply[i]), "sites": int(feasible[i]),
                     "opportunity": round(float(opp[i]), 1)}
                    for i in order[:15] if np.isfinite(gated[i])]

    OUT.write_text(json.dumps({"catchment_km": {k: v[1] for k, v in PREMIUM.items()},
                               "shortlists": out}, default=float))
    print(f"\nwrote {OUT}")
    print("\nv1 caveats: straight-line catchment (drive-time isochrones = GTM-71); NTA granularity; "
          "supply not Google-validated (GTM-70 — padel needs manual/Google supply). "
          "Large-format feasibility gate (GTM-73) NOW APPLIED — see 'sites'.")


if __name__ == "__main__":
    run()
