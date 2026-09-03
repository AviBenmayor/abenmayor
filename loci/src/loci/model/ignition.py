"""Axis 4b — the exogenous IGNITION model.

The 2033 maturity backtest (O4 / D25) proved a neighborhood's own trajectory —
level, slope, AND acceleration — does not predict *ignition* (the flat-then-surge
takeoff). And a naive PLUTO development-headroom score just surfaces low-density
suburbs. Ignition is exogenous: it is driven by a committed transit expansion, a
neighborhood rezoning, or a megaproject — a datable, finite, public pipeline.

This module screens for PRE-IGNITION neighborhoods: still low-to-mid maturity
(runway left), genuinely urban (a built-density floor kills the suburban false
positives), and sitting on top of a real catalyst. It is anchored on a
hand-curated `CATALYSTS` layer, not inferred from zoning — because the honest
finding is that the signal lives in the project pipeline, not the numbers.

Curated as of 2026-09-02, 3 boroughs (BK/MN/QN). Status weights certainty:
committed 1.0 · planned/EIS 0.6 · study/proposed 0.3. This layer is the load-
bearing content — expand it from DCP ZAP (rezonings), the MTA capital program
(SAS/IBX), and EDC/ESD (megaprojects); validate each entry before trusting it.
"""
from __future__ import annotations

import json
import pathlib

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[3]  # src/loci/model/ -> project root
DB = ROOT / "data" / "loci.duckdb"
NTA = ROOT / "data" / "raw" / "boundaries" / "nyc_nta2020.geojson"
PANEL = ("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor/"
         "87470c85-2596-49c9-a8e9-2f0429772416/scratchpad/nta_trajectory.json")
SP = pathlib.Path("/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor-loci/"
                  "87470c85-2596-49c9-a8e9-2f0429772416/scratchpad")
OUT = SP / "ignition_shortlist.json"
NB_PATH = SP / "nb_by_nta_year.json"   # DOB new-building filings by NTA×year (corroboration + lag)

# (name, kind, status, year, weight, [NTA-name substrings it touches])
#   year   = adoption / opening / announcement year (the catalyst clock start)
#   status = committed 1.0 / planned 0.6 / study 0.3   (certainty)
# The `future` block is the forward pipeline (the screen). The `historical` block is dated
# past catalysts used ONLY by the lag study (loci ignition --lag) — pre-2015 so the panel
# has a post-catalyst window. Expand from DCP ZAP, MTA capital program, and EDC.
CATALYSTS = [
    # ---------- FORWARD PIPELINE (drives the pre-ignition screen) ----------
    # Transit
    ("Second Ave Subway Phase 2 (Q to 125 St)", "transit", "committed", 2032, 1.0, ["East Harlem"]),
    ("Interborough Express (Bay Ridge branch LRT)", "transit", "planned", 2032, 0.6,
     ["Bay Ridge", "Sunset Park", "Borough Park", "Kensington", "Midwood", "Flatbush",
      "East Flatbush", "Brownsville", "Bushwick", "Ridgewood", "Maspeth", "Middle Village",
      "Elmhurst", "Jackson Heights"]),
    ("Utica Ave subway (study)", "transit", "study", 2035, 0.3, ["Crown Heights", "East Flatbush"]),
    # Rezonings
    ("East New York rezoning (2016)", "rezoning", "committed", 2016, 1.0, ["East New York", "Cypress Hills"]),
    ("East Harlem rezoning (2017)", "rezoning", "committed", 2017, 1.0, ["East Harlem"]),
    ("Downtown Far Rockaway rezoning (2017)", "rezoning", "committed", 2017, 1.0, ["Far Rockaway"]),
    ("Inwood rezoning (2018)", "rezoning", "committed", 2018, 1.0, ["Inwood"]),
    ("Gowanus rezoning (2021, ~8,500 units)", "rezoning", "committed", 2021, 1.0, ["Gowanus", "Carroll Gardens"]),
    ("Atlantic Ave Mixed-Use Plan (2024)", "rezoning", "committed", 2024, 1.0,
     ["Bedford-Stuyvesant", "Crown Heights", "Ocean Hill", "Stuyvesant Heights"]),
    ("Jamaica Neighborhood Plan (in progress)", "rezoning", "planned", 2025, 0.6, ["Jamaica", "South Jamaica", "Hollis"]),
    ("OneLIC / Long Island City plan (proposed)", "rezoning", "planned", 2025, 0.6, ["Long Island City", "Hunters Point"]),
    ("Special Flushing Waterfront (2020)", "rezoning", "committed", 2020, 1.0, ["Flushing", "Willets Point"]),
    ("Two Bridges large-scale plan (2018)", "rezoning", "committed", 2018, 1.0, ["Chinatown", "Two Bridges", "Lower East Side"]),
    ("Broadway Junction upzoning study", "rezoning", "study", 2035, 0.3, ["East New York", "Broadway Junction", "Cypress Hills"]),
    # Megaprojects
    ("Willets Point redevelopment", "megaproject", "committed", 2030, 1.0, ["Willets Point", "Flushing"]),
    ("Sunnyside Yards (proposed deck)", "megaproject", "study", 2040, 0.3, ["Sunnyside", "Long Island City"]),
    ("Brooklyn Marine Terminal (planning)", "megaproject", "planned", 2035, 0.6, ["Red Hook", "Carroll Gardens"]),
    ("Coney Island redevelopment", "megaproject", "planned", 2030, 0.6, ["Coney Island"]),
    # ---------- HISTORICAL (dated past catalysts — for the lag study only) ----------
    ("Greenpoint-Williamsburg rezoning (2005)", "rezoning", "historical", 2005, 0.0, ["Williamsburg", "Greenpoint"]),
    ("Park Slope / 4th Ave rezoning (2003)", "rezoning", "historical", 2003, 0.0, ["Park Slope", "Gowanus"]),
    ("Downtown Brooklyn rezoning (2004)", "rezoning", "historical", 2004, 0.0, ["Downtown Brooklyn", "Fort Greene"]),
    ("125th St / Harlem rezoning (2008)", "rezoning", "historical", 2008, 0.0, ["Harlem", "East Harlem"]),
    ("Long Island City rezoning (2008)", "rezoning", "historical", 2008, 0.0, ["Long Island City", "Hunters Point", "Queensbridge"]),
    ("Hudson Yards rezoning + 7 extension (2005/2015)", "transit", "historical", 2015, 0.0, ["Hudson Yards", "Chelsea"]),
    ("SAS Phase 1 (Q to 96 St, 2017)", "transit", "historical", 2017, 0.0, ["Upper East Side-Yorkville", "Upper East Side-Lenox Hill"]),
    ("Coney Island rezoning (2009)", "rezoning", "historical", 2009, 0.0, ["Coney Island"]),
    ("Astoria Cove / Hallets Point (2015)", "megaproject", "historical", 2015, 0.0, ["Old Astoria", "Hallets"]),
    ("Atlantic Yards / Pacific Park (2006)", "megaproject", "historical", 2006, 0.0, ["Prospect Heights", "Fort Greene"]),
]
STATUS_W = {"committed": 1.0, "planned": 0.6, "study": 0.3, "historical": 0.0}

# A committed catalyst is the real suburb-filter (Fresh Meadows has none). The built-density
# floor is only a light guard against park/industrial slivers — kept LOW on purpose so it does
# NOT drop the low-rise-but-catalyzed frontiers (East New York, Far Rockaway) that are the whole
# "underdeveloped, ripe for rezoning" point.
URBAN_BUILT_FAR = 0.6
MATURITY_CEILING = 62.0  # above this it has already risen; below = runway


def _nta_agg(con) -> pd.DataFrame:
    a = con.execute("""
        SELECT h.nta_code, avg(hc.built_far) built, avg(hc.resid_far) resid,
               avg(hc.dev_headroom) headroom, avg(hc.comm_far_capacity) commfar,
               avg(hc.walk_m_to_subway) walk, max(hc.subway_routes) routes,
               sum(hc.subway_riders_2024) riders, count(*) nhex
        FROM analysis.hex_controls hc JOIN analysis.hex h USING(h3_index)
        WHERE h.nta_code IS NOT NULL GROUP BY 1""").df()
    g = gpd.read_file(NTA)[["ntaname", "nta2020", "boroname"]]
    return a.merge(g, left_on="nta_code", right_on="nta2020", how="left")


def catalysts_for(name: str, include_historical: bool = False) -> list[dict]:
    if not name:
        return []
    out = []
    for cname, kind, status, year, w, keys in CATALYSTS:
        if status == "historical" and not include_historical:
            continue
        if any(k.lower() in name.lower() for k in keys):
            out.append({"name": cname, "kind": kind, "status": status, "year": year, "weight": w})
    return out


def run() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    a = _nta_agg(con)
    panel = json.load(open(PANEL))
    a["m23"] = a.ntaname.map({r["ntaname"]: r["maturity"] for r in panel if r["year"] == 2023})

    a["cats"] = a.ntaname.map(catalysts_for)
    a["cat_w"] = a.cats.map(lambda cs: max([c["weight"] for c in cs], default=0.0))
    a["cat_n"] = a.cats.map(len)

    # DOB corroboration: is development actually happening here? (new-building filings 2018-2023)
    nb = _load_nb()
    if nb is not None:
        recent = nb[nb.year.between(2018, 2023)].groupby("ntaname").nb.sum()
        a["nb_recent"] = a.ntaname.map(recent).fillna(0).astype(int)
    else:
        a["nb_recent"] = 0

    def z(s):
        s = pd.to_numeric(s, errors="coerce"); sd = s.std()
        return (s - s.mean()) / sd if sd else s * 0

    # readiness = how build-ready the catalyst can act on: headroom + commercial capacity + transit
    a["transit"] = (0.5 * (1 - np.clip((a.walk - 100) / 1400, 0, 1))
                    + 0.3 * np.clip(a.routes / 6, 0, 1)
                    + 0.2 * np.clip(np.log1p(a.riders.fillna(0)) / np.log1p(5e6), 0, 1))
    a["readiness"] = (0.45 * z(a.headroom) + 0.25 * z(a.commfar) + 0.30 * z(a.transit)).clip(-3, 3)

    # SCREEN: has a real catalyst, urban (not suburban), runway left
    cand = a[(a.cat_w > 0) & (a.built >= URBAN_BUILT_FAR) & (a.m23 <= MATURITY_CEILING)
             & (a.nhex >= 5)].copy()
    # ignition score: certainty of the catalyst is primary; build-readiness modulates it
    cand["score"] = cand.cat_w * (1.0 + 0.5 * (cand.readiness - cand.readiness.min())
                                  / (cand.readiness.max() - cand.readiness.min() + 1e-9))
    cand = cand.sort_values(["cat_w", "score"], ascending=False)

    # what a NAIVE headroom screen (no catalyst) would have floated but the catalyst anchor kills:
    # high-headroom, low-maturity neighborhoods with NO committed project behind them.
    dropped = a[(a.cat_w == 0) & (a.m23 <= MATURITY_CEILING)].nlargest(6, "headroom")

    print(f"PRE-IGNITION SHORTLIST — catalyst-anchored, urban (built≥{URBAN_BUILT_FAR}), "
          f"runway (maturity≤{MATURITY_CEILING:.0f})   [{len(cand)} neighborhoods]\n")
    print(f"{'#':>2} {'neighborhood':32}{'boro':4}{'mat':>4}{'room':>5}{'rte':>4}{'cat':>5}{'NB18-23':>8}"
          f"  strongest catalyst")
    for i, (_, r) in enumerate(cand.iterrows(), 1):
        top = max(r.cats, key=lambda c: c["weight"])
        print(f"{i:>2} {str(r.ntaname)[:32]:32}{str(r.boroname)[:3]:4}{r.m23:>4.0f}"
              f"{r.headroom:>5.1f}{int(r.routes or 0):>4}{r.cat_w:>5.1f}{r.nb_recent:>8}"
              f"  {top['name']} [{top['status']}]")

    print("\na naive headroom screen would float these — NO catalyst behind them, so we drop them:")
    for _, r in dropped.iterrows():
        print(f"   {str(r.ntaname)[:32]:32} {str(r.boroname)[:3]:3} built {r.built:.1f} headroom {r.headroom:.1f} mat {r.m23:.0f}")

    rows = [{"nta": r.ntaname, "boro": r.boroname, "maturity": round(r.m23, 1),
             "built_far": round(r.built, 2), "headroom": round(r.headroom, 2),
             "routes": int(r.routes or 0), "nb_recent": int(r.nb_recent),
             "catalyst_weight": r.cat_w, "score": round(r.score, 3), "catalysts": r.cats}
            for _, r in cand.iterrows()]
    OUT.write_text(json.dumps({"shortlist": rows, "n_catalysts": len(CATALYSTS)}, default=float))
    print(f"\nwrote {OUT}")


def _load_nb() -> pd.DataFrame | None:
    if not NB_PATH.exists():
        return None
    return pd.read_json(NB_PATH)


def lag() -> None:
    """Event study: how long from a dated catalyst to (a) a new-building surge and
    (b) an above-baseline demographic (maturity) shift. See ignition_lag_findings.md."""
    nb = _load_nb()
    if nb is None:
        print(f"NB data missing ({NB_PATH}); run the DOB pull first."); return
    panel = json.load(open(PANEL))
    mat: dict[str, dict] = {}
    for r in panel:
        mat.setdefault(r["ntaname"], {})[r["year"]] = r["maturity"]
    base_d = float(np.mean([mat[n][2023] - mat[n][2013] for n in mat
                            if 2013 in mat[n] and 2023 in mat[n]]))
    ntas = nb.ntaname.unique()
    print(f"citywide mean maturity Δ 2013→2023 = {base_d:+.1f} (baseline drift)\n")
    print(f"{'catalyst':40}{'yr':>5}{'NB surge':>9}{'NB peak':>8}   mat Δ vs citywide")
    surge_l, peak_l = [], []
    for name, kind, status, year, w, keys in CATALYSTS:
        hits = [r for r in ntas if any(k.lower() in r.lower() for k in keys)]
        if not hits:
            continue
        s = nb[nb.ntaname.isin(hits)].groupby("year").nb.sum().reindex(range(2000, 2024), fill_value=0)
        pre = s.loc[max(2000, year - 4):year - 1].mean() if year > 2000 else s.loc[2000:2002].mean()
        thr = max(pre * 1.5, 3)
        surge = next((y - year for y in range(year + 1, 2024) if s.get(y, 0) >= thr), None)
        peak = int(s.loc[year:2023].idxmax()) - year if s.loc[year:2023].max() > 0 else None
        md = [mat[n][2023] - mat[n][2013] for n in hits if n in mat and 2013 in mat[n] and 2023 in mat[n]]
        vs = f"{np.mean(md) - base_d:+.1f}" if md else "n/a"
        if surge is not None and year <= 2018:
            surge_l.append(surge)
        if peak is not None and year <= 2018:
            peak_l.append(peak)
        print(f"{name[:40]:40}{year:>5}{('+' + str(surge) + 'y') if surge is not None else '--':>9}"
              f"{('+' + str(peak) + 'y') if peak is not None else '--':>8}   {vs}")
    print(f"\ncatalyst → NB-permit surge: median {int(np.median(surge_l))}y (range {min(surge_l)}–{max(surge_l)}y)"
          f" · peak: median {int(np.median(peak_l))}y")
    print("Two clocks: construction ~5–9y; demographic tip 10–20y (and only if market-rate). "
          "Caveat: DOB classic undercounts post-2016; descriptive not causal.")


if __name__ == "__main__":
    import sys
    lag() if "--lag" in sys.argv else run()
