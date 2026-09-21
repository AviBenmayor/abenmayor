"""Convertible stock: one-storey, big-footprint, parking/vacant lots (A8 step 5, memo §5 item 5).

    analysis.lot_convertible(bbl, height_m, footprint_m2, lot_m2, lot_class,
                             landuse, bldgclass, zoning, borough, in_gowanus,
                             score, lon, lat, computed_on)

    loci aerial convertible [--gowanus | --boroughs MN,BK]

WHAT IT FINDS. The floorplates a bathhouse, a gym, a food hall or a garage
conversion needs: a lot whose building is ONE STOREY (LiDAR-derived
`height_roof` under HEIGHT_MAX_M) with a footprint of at least
FOOTPRINT_MIN_M2, or a lot with no building at all in a parking / vacant
land-use class. Every candidate is scored 0-1 for ordering only:

    score = 0.5 * min(footprint_m2 / SCORE_FOOTPRINT_FULL_M2, 1)
          + 0.3 * class weight (parking 1.0, vacant 0.9, garage 0.8, one_storey 0.6)
          + 0.2 * zoning weight (M / C districts 1.0, R with C overlay 0.6, R 0.2)

It is a SORT KEY for a review list, not a measure of anything; the gate is
"hand-check top 30" (memo §5), and data/aerial/convertible_review.html is
that list, owner review pending.

THE HEIGHT SOURCE, HONESTLY. The memo names "LiDAR 2021". Verified 2026-09-17:
https://gis.ny.gov/lidar lists New York City collections for 2014 (USGS) and
2017 (topobathymetric, Open Data 7sc8-jtbz); no 2021 NYC collection is
published there or on Open Data. OTI's building footprints carry
`height_roof` derived from that 2017 LiDAR and maintained from imagery, and
that is the height used here: `height_m = max(height_roof_ft) * 0.3048` over
the lot's footprints. The raw point cloud (terabytes of LAZ) is not pulled
to recompute a column OTI already publishes; the source is registered and
the caveat travels with every row -- "2021 already stale in Gowanus" (memo
§2) is 2017 here, staler.

PLUTO gives lot area, land use (10 = parking, 11 = vacant), building class
(G = garage) and zoning. A lot in PLUTO with no footprint and land use 10/11
is `parking` / `vacant`; one with footprints under HEIGHT_MAX_M is
`one_storey` unless its class is G (`garage`).
"""
from __future__ import annotations

import datetime as dt
import html
import math
import pathlib

import pandas as pd

from loci.grid.pluto import PLUTO_CSV
from loci.model.aerial import GOWANUS_BBOX

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "data" / "aerial"
OUT_TABLE = "analysis.lot_convertible"
FOOTPRINT_TABLE = "staging.building_footprint"

HEIGHT_MAX_M = 6.0
FOOTPRINT_MIN_M2 = 500.0
SCORE_FOOTPRINT_FULL_M2 = 2_000.0
CLASS_WEIGHT = {"parking": 1.0, "vacant": 0.9, "garage": 0.8, "one_storey": 0.6}
PLUTO_BOROUGH = {"MN": "1", "BK": "3"}        # BBL's leading digit
REVIEW_TOP = 30


def _s(v) -> str:
    """A PLUTO text cell: NaN from pandas, None from DuckDB, or a string."""
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)


def zoning_weight(zonedist1: str | None, overlay1: str | None) -> float:
    z = _s(zonedist1).upper()
    if z.startswith(("M", "C")):
        return 1.0
    if z.startswith("R") and _s(overlay1).upper().startswith("C"):
        return 0.6
    if z.startswith("R"):
        return 0.2
    return 0.4      # parks, special districts, unknown


def score(footprint_m2: float, lot_class: str, zonedist1: str | None, overlay1: str | None) -> float:
    fp = min(max(footprint_m2, 0.0) / SCORE_FOOTPRINT_FULL_M2, 1.0)
    return round(0.5 * fp + 0.3 * CLASS_WEIGHT.get(lot_class, 0.0)
                 + 0.2 * zoning_weight(zonedist1, overlay1), 4)


def find(con, *, boroughs: tuple[str, ...] = ("MN", "BK"),
         bbox: tuple[float, float, float, float] | None = None,
         pluto_csv: pathlib.Path | str = PLUTO_CSV,
         footprint_table: str = FOOTPRINT_TABLE) -> pd.DataFrame:
    """Candidates as a DataFrame with OUT_TABLE's columns."""
    con.execute("LOAD spatial")
    boro_digits = [PLUTO_BOROUGH[b] for b in boroughs]
    where_bbox, params = "", []
    if bbox:
        min_lat, min_lon, max_lat, max_lon = bbox
        where_bbox = "AND p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?"
        params = [min_lat, max_lat, min_lon, max_lon]
    df = con.execute(f"""
        WITH p AS (
            SELECT bbl AS bbl, TRY_CAST(latitude AS DOUBLE) AS lat,
                   TRY_CAST(longitude AS DOUBLE) AS lon,
                   TRY_CAST(lotarea AS DOUBLE) * 0.092903 AS lot_m2,
                   landuse AS landuse, bldgclass AS bldgclass, zonedist1 AS zonedist1,
                   overlay1 AS overlay1, borough AS borough
            FROM read_csv_auto(?, ALL_VARCHAR = TRUE)
            WHERE substr(bbl, 1, 1) IN (SELECT unnest(?::VARCHAR[]))
        ),
        f AS (
            -- ST_Area_Spheroid takes [lat, lon] axis order (DuckDB spatial), as
            -- db.METRES_SQL does for distance: without the flip a 600 m2 shed
            -- reads 219 m2 (measured) and the filter silently drops it.
            SELECT bbl, max(height_roof_ft) * 0.3048 AS height_m,
                   sum(ST_Area_Spheroid(ST_FlipCoordinates(geom))) AS footprint_m2, count(*) AS n
            FROM {footprint_table}
            WHERE substr(bbl, 1, 1) IN (SELECT unnest(?::VARCHAR[]))
            GROUP BY bbl
        )
        SELECT p.bbl, f.height_m, coalesce(f.footprint_m2, 0.0) AS footprint_m2, p.lot_m2,
               CASE WHEN f.bbl IS NULL AND p.landuse = '10' THEN 'parking'
                    WHEN f.bbl IS NULL AND p.landuse = '11' THEN 'vacant'
                    WHEN f.bbl IS NOT NULL AND f.height_m < ? AND p.bldgclass LIKE 'G%' THEN 'garage'
                    WHEN f.bbl IS NOT NULL AND f.height_m < ? THEN 'one_storey'
               END AS lot_class,
               p.landuse, p.bldgclass, p.zonedist1 AS zoning, p.overlay1, p.borough,
               p.lon, p.lat
        FROM p LEFT JOIN f USING (bbl)
        WHERE p.lat IS NOT NULL {where_bbox}
    """, [str(pluto_csv), boro_digits, boro_digits, HEIGHT_MAX_M, HEIGHT_MAX_M, *params]).fetchdf()
    df = df[df["lot_class"].notna()].copy()
    # A built candidate needs the floorplate; an empty lot needs the LOT to hold one.
    keep = ((df["lot_class"].isin(["one_storey", "garage"]) & (df["footprint_m2"] >= FOOTPRINT_MIN_M2))
            | (df["lot_class"].isin(["parking", "vacant"]) & (df["lot_m2"] >= FOOTPRINT_MIN_M2)))
    df = df[keep].copy()
    g = GOWANUS_BBOX
    df["in_gowanus"] = (df["lat"].between(g[0], g[2]) & df["lon"].between(g[1], g[3]))
    df["score"] = [score(fp if cls in ("one_storey", "garage") else lot, cls, z, o)
                   for fp, lot, cls, z, o in zip(df["footprint_m2"], df["lot_m2"].fillna(0),
                                                  df["lot_class"], df["zoning"], df["overlay1"])]
    df["computed_on"] = dt.date.today()
    return df.sort_values("score", ascending=False).reset_index(drop=True)


WRITE_COLUMNS = ("bbl", "height_m", "footprint_m2", "lot_m2", "lot_class", "landuse", "bldgclass",
                 "zoning", "borough", "in_gowanus", "score", "lon", "lat", "computed_on")


def write(con, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    con.execute("BEGIN")
    try:
        con.execute(f"DELETE FROM {OUT_TABLE} WHERE bbl IN (SELECT bbl FROM df)")
        con.execute(f"INSERT INTO {OUT_TABLE} ({', '.join(WRITE_COLUMNS)}) "
                    f"SELECT {', '.join(WRITE_COLUMNS)} FROM df")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(df)


def review_html(df: pd.DataFrame, path: pathlib.Path, crops: dict[str, str] | None = None,
                top: int = REVIEW_TOP, title: str = "Convertible stock — top 30") -> pathlib.Path:
    crops = crops or {}
    picked = df.head(top)
    rows = []
    for i, r in enumerate(picked.itertuples(index=False), 1):
        img = (f"<img src='data:image/jpeg;base64,{crops[r.bbl]}' alt='2024 ortho'>"
               if r.bbl in crops else "<div class='noimg'>no ortho crop</div>")
        h = "" if pd.isna(r.height_m) else f"{r.height_m:.1f} m"
        rows.append(f"""
        <section class="lot" data-bbl="{r.bbl}">
          <header><b>{i}.</b> BBL {r.bbl} · {html.escape(str(r.lot_class))} · score {r.score:.2f}
            {'· <span class="tag">Gowanus</span>' if r.in_gowanus else ''}</header>
          <div class="facts">height {h or '—'} · footprint {r.footprint_m2:,.0f} m² · lot {0 if pd.isna(r.lot_m2) else r.lot_m2:,.0f} m²
            · land use {html.escape(str(r.landuse))} · class {html.escape(str(r.bldgclass))} · zoning {html.escape(str(r.zoning))}
            · <a href="https://www.google.com/maps?q={r.lat},{r.lon}" target="_blank" rel="noopener">map</a></div>
          {img}
          <label>Your call: <select><option value="">—</option><option>convertible</option><option>not one storey</option>
            <option>too small</option><option>in use / not available</option><option>cannot tell</option></select></label>
        </section>""")
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root {{ --bg:#fff; --fg:#1a1a1a; --muted:#666; --line:#ddd; --acc:#26c; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#111; --fg:#eee; --muted:#aaa; --line:#333; }} }}
:root[data-theme="dark"] {{ --bg:#111; --fg:#eee; --muted:#aaa; --line:#333; }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,sans-serif; margin:0; padding:16px; }}
main {{ max-width:960px; margin:0 auto; }} h1 {{ font-size:1.4rem; }}
.caveat {{ color:var(--muted); border-left:3px solid var(--line); padding:.4rem .8rem; margin:1rem 0; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(290px,1fr)); gap:14px; }}
.lot {{ border:1px solid var(--line); border-radius:6px; padding:10px; }}
.facts {{ font-size:.85rem; color:var(--muted); margin:.3rem 0; }}
.lot img {{ width:100%; height:auto; display:block; margin:.3rem 0; }}
.noimg {{ height:120px; display:grid; place-items:center; color:var(--muted); border:1px dashed var(--line); }}
.tag {{ font-size:.8rem; padding:.05rem .4rem; border:1px solid var(--acc); border-radius:4px; }}
a {{ color:var(--acc); }} button {{ padding:.4rem .9rem; margin-top:1rem; }}
</style></head><body><main>
<h1>{html.escape(title)}</h1>
<p>{len(df):,} candidates; the top {len(picked)} by score are shown (footprint × class × zoning, a sort key only).</p>
<div class="caveat">Heights are OTI footprint <code>height_roof</code> (2017 LiDAR, maintained from imagery) — no 2021 NYC
LiDAR is published on gis.ny.gov or Open Data (verified 2026-09-17). A parapet or bulkhead reads as height; a lot in
use as a yard or a depot reads as convertible. Gate (memo §5 row 5): hand-check the top 30 — this page. Card
context only; nothing enters a grade.</div>
<div class="grid">{''.join(rows)}</div>
<button onclick="exportVerdicts()">Export verdicts (JSON)</button><pre id="out"></pre>
<script>
function exportVerdicts() {{
  const out = {{}};
  document.querySelectorAll('section.lot').forEach(s => {{ const v = s.querySelector('select').value; if (v) out[s.dataset.bbl] = v; }});
  document.getElementById('out').textContent = JSON.stringify(out, null, 1);
}}
</script></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path
