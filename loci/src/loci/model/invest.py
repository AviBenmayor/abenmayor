"""Axis 1 — the Investability Index.

Turns a *validated gap* (unmet demand today, confirmed absent by Google) into an
investment ranking. Raw "homes affected" is only reach; a good investment also
needs (a) somewhere you can legally open, (b) a catchment big enough for the
category's economics, (c) the right kind of demand, (d) little competition just
outside the walk ring, and (e) foot traffic. This module scores all five.

The load-bearing step is the **feasibility gate**: a "gap" in an all-residential
zone with no commercial frontage is a zoning artifact, not an opportunity
(CONTEXT.md threat #6 / CHECKPOINT D3). A cluster passes only if you can either
BUILD (PLUTO CommFAR > 0) or LEASE (existing PLUTO RetailArea > 0), and the
catchment clears the category's minimum viable size.

Inputs already in the warehouse: PLUTO (feasibility), hex_demographics (income,
renter share, population), hex_panel (LODES daytime jobs), hex_controls (transit),
and the deduped POI base (competition ring). Category economics live in ECON.
"""
from __future__ import annotations

import json
import math
import pathlib

import h3
import numpy as np

from loci import db as locidb
from loci.grid.pluto import PLUTO_CSV

CITY_MED_INC = 94_649.0  # 3-borough ACS 2023 median, for a spending-power anchor
RING_INNER_M, RING_OUTER_M = 800.0, 1600.0

# (minimum viable catchment in HOMES within a 10-min walk, primary demand driver)
# Rough but defensible; the gate is directional, not a pro-forma. Documented as an
# assumption in CHECKPOINT (D18). A pharmacy/supermarket/gym needs real scale; a
# bodega or cafe survives on far less but leans on renters and daytime workers.
ECON = {
    "grocery":     (1500, "income"),
    "convenience": (300,  "jobs_renter"),
    "pharmacy":    (2000, "income_pop"),
    "laundry":     (500,  "renter"),
    "cafe_bakery": (400,  "jobs_income"),
    "fitness":     (2000, "income"),
    "childcare":   (800,  "pop"),
}

BQ_REAL = ("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor-loci/"
           "b495b991-3549-4a4b-9741-40b94faa1a15/scratchpad/bq_real.json")
OUT = pathlib.Path("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor-loci/"
                   "b495b991-3549-4a4b-9741-40b94faa1a15/scratchpad/invest.json")


def _haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def run() -> None:
    con = locidb.connect()
    meta = json.load(open("webmap/buildings_meta.json"))
    LAB = dict(zip(meta["cats"], meta["catLabels"]))

    real = json.load(open(BQ_REAL))  # (cat,homes,blds,inc,boro,nta,lat,lon)
    clusters = [dict(cat=r[0], homes=r[1], blds=r[2], income=r[3], boro=r[4],
                     nta=r[5], lat=r[6], lon=r[7],
                     cell=h3.latlng_to_cell(r[6], r[7], 8))
                for r in real if r[0] in ECON]

    # --- feasibility from PLUTO: aggregate lots to res-8 cells ---
    print("aggregating PLUTO feasibility to res-8 cells...", flush=True)
    pl = con.execute(f"""
        SELECT TRY_CAST(latitude AS DOUBLE) lat, TRY_CAST(longitude AS DOUBLE) lon,
               TRY_CAST(commfar AS DOUBLE) commfar, TRY_CAST(retailarea AS DOUBLE) retail
        FROM read_csv('{PLUTO_CSV}', ALL_VARCHAR=TRUE)
        WHERE TRY_CAST(latitude AS DOUBLE) IS NOT NULL AND borocode IN ('3','4')
    """).df()
    want = {c["cell"] for c in clusters}
    feas: dict[str, list] = {c: [0, 0.0, 0] for c in want}  # n_comm, retail_sqft, n_lots
    for lat, lon, cf, ra in pl.itertuples(index=False):
        cell = h3.latlng_to_cell(lat, lon, 8)
        if cell in feas:
            f = feas[cell]
            f[2] += 1
            if cf and cf > 0: f[0] += 1
            if ra and ra > 0: f[1] += ra

    # --- res-9 hex aggregates: demographics, jobs, transit ---
    demo = {r[0]: r[1:] for r in con.execute(
        "SELECT h3_index, population, median_hh_income, renter_share "
        "FROM analysis.hex_demographics WHERE acs_year=2023").fetchall()}
    jobs = {r[0]: r[1] for r in con.execute(
        "SELECT h3_index, sum(jobs) FROM analysis.hex_panel WHERE year=2023 GROUP BY 1").fetchall()}
    ctrl = {r[0]: r[1:] for r in con.execute(
        "SELECT h3_index, walk_m_to_subway, subway_routes, subway_riders_2024, comm_far_capacity "
        "FROM analysis.hex_controls").fetchall()}

    # --- competition ring: canonical POIs per category ---
    poi_by_cat: dict[str, list] = {}
    for cat in ECON:
        rows = con.execute("""
            SELECT ST_Y(p.geom), ST_X(p.geom) FROM staging.poi p
            JOIN analysis.poi_dedup d ON p.poi_id=d.poi_id
            WHERE d.is_canonical AND p.category=?""", [cat]).fetchall()
        poi_by_cat[cat] = rows

    for c in clusters:
        kids = h3.cell_to_children(c["cell"], 9)
        pops = [demo[k][0] for k in kids if k in demo and demo[k][0]]
        incs = [(demo[k][0], demo[k][1]) for k in kids if k in demo and demo[k][1]]
        rents = [demo[k][2] for k in kids if k in demo and demo[k][2] is not None]
        c["pop"] = float(sum(pops))
        c["job"] = float(sum(jobs.get(k, 0) or 0 for k in kids))
        c["renter"] = float(np.mean(rents)) if rents else 0.5
        c["hexinc"] = (sum(p * i for p, i in incs) / sum(p for p, _ in incs)) if incs else c["income"]
        walks = [ctrl[k][0] for k in kids if k in ctrl and ctrl[k][0] is not None]
        riders = [ctrl[k][2] for k in kids if k in ctrl and ctrl[k][2] is not None]
        c["walk_subway"] = min(walks) if walks else 2000.0
        c["riders"] = float(sum(riders)) if riders else 0.0
        f = feas[c["cell"]]
        c["n_comm"], c["retail_sqft"], c["n_lots"] = f[0], f[1], f[2]
        # competition in the 800-1600m ring
        ring = sum(1 for la, lo in poi_by_cat[c["cat"]]
                   if RING_INNER_M < _haversine(c["lat"], c["lon"], la, lo) <= RING_OUTER_M)
        c["ring"] = ring
        # --- gate ---
        minv, driver = ECON[c["cat"]]
        can_open = c["n_comm"] > 0 or c["retail_sqft"] > 0
        big_enough = c["homes"] >= minv
        c["gate"] = "PASS" if (can_open and big_enough) else (
            "no storefront" if not can_open else f"too small (<{minv})")
        c["driver"] = driver

    passing = [c for c in clusters if c["gate"] == "PASS"]

    # --- score the passers (0-100, transparent components) ---
    def norm(x, lo, hi):
        return max(0.0, min(1.0, (x - lo) / (hi - lo))) if hi > lo else 0.0

    for c in passing:
        minv, driver = ECON[c["cat"]], None
        minv = ECON[c["cat"]][0]
        catchment = norm(math.log1p(c["homes"] / minv), 0, math.log1p(4))   # 1x..4x viable
        spending = norm(c["hexinc"] / CITY_MED_INC, 0.6, 1.6)
        # category-specific demand driver
        d = c["driver"]
        if d == "renter":        drv = c["renter"]
        elif d == "jobs_renter": drv = 0.5 * norm(c["job"], 0, 4000) + 0.5 * c["renter"]
        elif d == "jobs_income": drv = 0.5 * norm(c["job"], 0, 4000) + 0.5 * spending
        elif d == "income" or d == "income_pop": drv = spending if d == "income" else 0.5*spending+0.5*norm(c["pop"],0,8000)
        else:                    drv = norm(c["pop"], 0, 8000)
        competition = 1.0 / (1.0 + c["ring"])                                # fewer nearby = better
        transit = 0.6 * (1 - norm(c["walk_subway"], 100, 1500)) + 0.4 * norm(math.log1p(c["riders"]), 0, math.log1p(5e6))
        c["c_catchment"], c["c_spend"], c["c_driver"] = catchment, spending, drv
        c["c_comp"], c["c_transit"] = competition, transit
        c["score"] = round(100 * (0.30*catchment + 0.15*spending + 0.20*drv +
                                  0.20*competition + 0.15*transit), 1)

    passing.sort(key=lambda c: -c["score"])

    print(f"\n{'='*92}\nAXIS 1 — INVESTABILITY  ({len(passing)} of {len(clusters)} validated gaps pass the feasibility gate)\n{'='*92}")
    print(f"{'#':>2} {'score':>5} {'missing':13} {'neighborhood':30} {'homes':>5} {'comm':>4} {'ring':>4} {'income':>8}")
    for i, c in enumerate(passing, 1):
        print(f"{i:>2} {c['score']:>5} {LAB[c['cat']][:13]:13} {c['nta'][:30]:30} "
              f"{c['homes']:>5,} {c['n_comm']:>4} {c['ring']:>4} {('$'+format(int(c['hexinc']),',')):>8}")

    dropped = [c for c in clusters if c["gate"] != "PASS"]
    print(f"\n--- dropped by the gate ({len(dropped)}) ---")
    for c in sorted(dropped, key=lambda c: -c["homes"]):
        print(f"   {LAB[c['cat']][:13]:13} {c['nta'][:30]:30} {c['homes']:>5,}  [{c['gate']}]")

    OUT.write_text(json.dumps({"passing": passing, "dropped": dropped, "labels": LAB}, default=float))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    run()
