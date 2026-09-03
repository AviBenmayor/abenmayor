"""Axis 2 — the "Rising" trajectory score.

Axis 1 asks "is this gap investable today?" This asks the Williamsburg question:
"will this area attract higher-income people over time?" — so an investor can tell
a gap in a stable neighborhood (serve today's demand, flat forever) from a gap in
a heating-up one (be the incumbent as incomes climb).

Nobody predicts gentrification precisely; the literature (Furman Center, Philly
Fed) instead names leading indicators. This v1 builds the ones computable from
data already in the warehouse:

  frontier   value-gap: you're the cheaper side of a steep income boundary, with
             a much richer area nearby. The #1 predictor — gentrification jumps
             borders (Williamsburg was one L stop from Manhattan). [income surface]
  jobgrowth  LODES workplace jobs 2013->2023 — commercial momentum. [hex_panel]
  gentrifiable  high renter share = turnover-prone stock that can re-tenant up. [ACS]
  transit    connectivity to job cores (subway proximity + ridership). [hex_controls]

Deliberately NOT yet included, and flagged as the strengthening layer (needs
external pulls): resident income & college-share change (ACS 2013 vs 2023),
rent momentum (Zillow ZORI), permit pipeline (DOB), and upzoning events — the
single most causal signal. Stated limits: predicts direction not timing; rent
stabilization damps outer-borough turnover; false positives are common.
"""
from __future__ import annotations

import json
import math

import duckdb
import h3
import numpy as np

from loci.model.invest import OUT as INVEST_JSON, _haversine

DB = "data/loci.duckdb"
W = dict(frontier=0.40, jobgrowth=0.25, gentrifiable=0.20, transit=0.15)


def _norm(x, lo, hi):
    return max(0.0, min(1.0, (x - lo) / (hi - lo))) if hi > lo else 0.0


def run() -> None:
    con = duckdb.connect(DB, read_only=True)
    inv = json.loads(INVEST_JSON.read_text())
    LAB = inv["labels"]
    clusters = inv["passing"] + inv["dropped"]

    # income surface with centroids
    inc_rows = con.execute(
        "SELECT h3_index, median_hh_income FROM analysis.hex_demographics "
        "WHERE acs_year=2023 AND median_hh_income IS NOT NULL").fetchall()
    inc_pts = [(h3.cell_to_latlng(h)[0], h3.cell_to_latlng(h)[1], inc) for h, inc in inc_rows]

    # LODES jobs per res-9 hex, 2013 & 2023
    j13 = {r[0]: r[1] for r in con.execute(
        "SELECT h3_index, sum(jobs) FROM analysis.hex_panel WHERE year=2013 GROUP BY 1").fetchall()}
    j23 = {r[0]: r[1] for r in con.execute(
        "SELECT h3_index, sum(jobs) FROM analysis.hex_panel WHERE year=2023 GROUP BY 1").fetchall()}

    for c in clusters:
        kids = h3.cell_to_children(c["cell"], 9)
        own = c.get("hexinc") or 0
        # frontier: 85th-pctile income among hexes 400-1600m away, vs own
        near = [inc for la, lo, inc in inc_pts if 400 < _haversine(c["lat"], c["lon"], la, lo) <= 1600]
        hi_neighbor = float(np.percentile(near, 85)) if near else own
        c["hi_neighbor"] = hi_neighbor
        gap = (hi_neighbor - own) / own if own else 0.0
        # you must be the cheaper side to have runway; cap the gap
        c["frontier"] = _norm(gap, 0.05, 0.9) if own and own < hi_neighbor else 0.0
        # job growth 2013->2023
        a = sum(j13.get(k, 0) or 0 for k in kids)
        b = sum(j23.get(k, 0) or 0 for k in kids)
        c["jobs13"], c["jobs23"] = a, b
        dlog = math.log((b + 25) / (a + 25))   # +25 smooths tiny bases
        c["jobgrowth"] = _norm(dlog, -0.1, 0.8)
        # gentrifiable: renter turnover
        c["gentrifiable"] = _norm(c.get("renter", 0.5), 0.2, 0.75)
        # transit connectivity (reuse Axis-1 fields where present)
        walk = c.get("walk_subway", 1500.0)
        riders = c.get("riders", 0.0)
        c["transit"] = 0.6 * (1 - _norm(walk, 100, 1500)) + 0.4 * _norm(math.log1p(riders), 0, math.log1p(5e6))
        c["rising"] = round(100 * sum(W[k] * c[k] for k in W), 1)

    clusters.sort(key=lambda c: -c["rising"])
    print(f"{'='*100}\nAXIS 2 — RISING trajectory ({len(clusters)} validated gap clusters)\n{'='*100}")
    print(f"{'rise':>4} {'front':>5} {'jobΔ':>5} {'rent%':>5} {'trans':>5}  {'neighborhood':30} {'ownInc':>8} {'nbrInc':>8}")
    for c in clusters:
        print(f"{c['rising']:>4} {c['frontier']:>5.2f} {c['jobgrowth']:>5.2f} {c['gentrifiable']:>5.2f} {c['transit']:>5.2f}  "
              f"{c['nta'][:30]:30} {('$'+format(int(c['hexinc']),',')):>8} {('$'+format(int(c['hi_neighbor']),',')):>8}")

    # persist merged
    INVEST_JSON.with_name("axes.json").write_text(json.dumps({"clusters": clusters, "labels": LAB}, default=float))
    print(f"\nwrote {INVEST_JSON.with_name('axes.json')}")


if __name__ == "__main__":
    run()
