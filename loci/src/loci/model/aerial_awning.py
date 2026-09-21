"""Projecting awnings per street face from the 2024 ortho (D82 corridors, memo §5 item 4).

    analysis.building_awning(bin, bbl, corridor, awning_faces, face_count,
                             awning_frac, ortho_year, computed_on)

    loci aerial awnings [--corridor NAME] [--year 2024]

WHY (memo §2, row 1). The twelve prewar retail strips the D82 planner review
named read RetailArea = 0 in PLUTO because a taxpayer folds its store area
into ComArea. A projecting awning seen from above is one witness of ground-
floor retail that no assessment column carries: it sits over the SIDEWALK,
outside the footprint, along the street face. This module measures exactly
that strip and nothing else.

THE FACE. For each building footprint on a corridor, the street face is the
footprint edge whose midpoint is nearest a street-frame point of that
corridor (analysis.address, frame='street', the CSCL midpoints of D84). The
band is that edge pushed FACE_OFFSET_M outward (away from the footprint
centroid) and FACE_DEPTH_M deep -- the sidewalk strip an awning covers. A
corner building gets a second face where a second street's points are within
FACE_MAX_DIST_M; `face_count` says how many were examined.

THE DETECTOR. A colour heuristic, deliberately (the vision module has a
COCO person detector and nothing that knows awnings; a learned model would
need labels this project does not have). In the band, a pixel is
"awning-like" when it is saturated AND lit (HSV S >= SAT_MIN and V >=
VALUE_MIN: canvas red, green, blue, yellow in sunlight) -- which excludes
sidewalk grey (low S), the roof (outside the band) and, after the first
run's lesson, the building's own shadow (dark, blue-tinted, and it covered
every north-facing band in March). Black and charcoal awnings are therefore
MISSED, and so is any awning in shadow; the count is a floor. `awning_frac`
is the share of band pixels that qualify; a face has an awning when
awning_frac >= AWNING_MIN.

WHAT IT CONFUSES (memo §5 threat column: "residential awnings, sheds").
A sidewalk shed is plywood over the same strip: brown, mid-V, moderate S --
it clears SAT_MIN on some boards. A parked box truck is a bright rectangle
in the same place. A tree canopy (leaf-off in March, so mostly bare) and a
stoop's railing shadow read dark. Residential awnings over a rowhouse door
are awnings and are counted. The gate is precision >= 0.8 against LL157
occupied premises on a hand-checked 100-face page
(data/aerial/awning_review.html), owner review pending; until then this is
card context, and the catalog comment says so.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import io
import pathlib

import numpy as np
import pandas as pd

from loci.sources.cities.nyc import orthoimagery as ortho

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "data" / "aerial"
OUT_TABLE = "analysis.building_awning"
FOOTPRINT_TABLE = "staging.building_footprint"
ADDRESS_TABLE = "analysis.address"

#: THE TWELVE D82 PLANNER-FLAGGED CORRIDORS (CHECKPOINT D82; the first
#: character pass read all twelve ~0 retail_mixed). Matched on
#: analysis.address.street_name for frame='street' points inside the lat/lon
#: box, which pins the named stretch rather than the whole street (7 Avenue
#: exists in three boroughs; Broadway runs the island).
#: (label, borough, street_name pattern (SQL LIKE, upper), min_lat, min_lon, max_lat, max_lon)
CORRIDORS: tuple[tuple[str, str, str, float, float, float, float], ...] = (
    ("Brighton Beach Ave",     "BK", "BRIGHTON BEACH AVE%",  40.575, -73.975, 40.582, -73.950),
    ("Cortelyou Rd",           "BK", "CORTELYOU R%",         40.638, -73.975, 40.643, -73.955),
    ("Myrtle Ave (Bushwick)",  "BK", "MYRTLE AVE%",          40.690, -73.940, 40.703, -73.900),
    ("7 Ave (Park Slope)",     "BK", "7 AVE%",               40.660, -73.990, 40.680, -73.970),
    ("Graham Ave",             "BK", "GRAHAM AVE%",          40.705, -73.950, 40.720, -73.935),
    ("Broadway (Hamilton Hts)", "MN", "BROADWAY",            40.820, -73.960, 40.835, -73.940),
    ("Dyckman St",             "MN", "DYCKMAN ST%",          40.860, -73.935, 40.870, -73.915),
    ("Fulton St (Bed-Stuy)",   "BK", "FULTON ST%",           40.678, -73.960, 40.684, -73.915),
    ("Church Ave",             "BK", "CHURCH AVE%",          40.645, -73.985, 40.653, -73.935),
    ("Kings Hwy",              "BK", "KINGS H%",             40.600, -73.980, 40.615, -73.940),
    ("5 Ave (Bay Ridge)",      "BK", "5 AVE%",               40.615, -74.035, 40.645, -74.005),
    ("Pitkin Ave",             "BK", "PITKIN AVE%",          40.665, -73.920, 40.675, -73.880),
)

#: A footprint is "on" the corridor when its nearest corridor street point is
#: within this straight-line distance of the footprint's nearest edge midpoint.
FACE_MAX_DIST_M = 22.0
#: The band: from FACE_OFFSET_M outside the edge, FACE_DEPTH_M deep.
#: An awning projects 1-2.5 m; 0.5 m clearance skips the parapet's shadow.
FACE_OFFSET_M = 0.5
FACE_DEPTH_M = 3.0
#: Faces shorter than this are a party-wall sliver, not a frontage.
FACE_MIN_LEN_M = 3.0

SAT_MIN = 0.32        # HSV saturation of coloured canvas
#: ...and LIT. The first corridor run (2026-09-17) scored 786 of 2,233
#: buildings positive and the top faces were all the building's own SHADOW on
#: the street: March sun, long shadows, and a "dark and smooth" rule that was
#: written for black canvas. Shadow in these orthos is dark AND blue-tinted
#: (saturation 0.3-0.5), so saturation alone does not exclude it either. A
#: pixel must be coloured and lit; black and charcoal awnings are a KNOWN MISS
#: and the review page says so.
VALUE_MIN = 0.35
AWNING_MIN = 0.22     # share of band pixels awning-like -> face has an awning

#: Footprints within this straight-line distance of a building are
#: subtracted from its band, so the strip measured is sidewalk, not roof.
NEIGHBOUR_M = 60.0
#: A band with fewer pixels than this after subtraction is not a frontage.
MIN_BAND_PX = 150

REVIEW_FACES = 100
REVIEW_PX = 220


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

def _m_per_deg(lat: float) -> tuple[float, float]:
    return 111_320.0, 111_320.0 * float(np.cos(np.radians(lat)))


def street_faces(ring: list[tuple[float, float]], street_pts: np.ndarray,
                 max_dist_m: float = FACE_MAX_DIST_M) -> list[dict]:
    """Edges of `ring` (lon/lat) facing a street point, at most one per street.

    `street_pts` is an (n, 3) array of lon, lat, street_key. Returns a list of
    {p0, p1, mid, dist_m, street_key, len_m, outward} where `outward` is the
    unit normal (in metres) pointing away from the ring's centroid.
    """
    if len(ring) < 3 or not len(street_pts):
        return []
    pts = np.asarray(ring, dtype=float)
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    lat0 = float(pts[:, 1].mean())
    lat_m, lon_m = _m_per_deg(lat0)
    xy = np.column_stack([(pts[:, 0] - pts[0, 0]) * lon_m, (pts[:, 1] - pts[0, 1]) * lat_m])
    sxy = np.column_stack([(street_pts[:, 0].astype(float) - pts[0, 0]) * lon_m,
                           (street_pts[:, 1].astype(float) - pts[0, 1]) * lat_m])
    centroid = xy.mean(axis=0)
    faces = []
    n = len(xy)
    for i in range(n):
        a, b = xy[i], xy[(i + 1) % n]
        seg = b - a
        length = float(np.hypot(*seg))
        if length < FACE_MIN_LEN_M:
            continue
        mid = (a + b) / 2
        d = np.hypot(*(sxy - mid).T)
        j = int(d.argmin())
        if d[j] > max_dist_m:
            continue
        normal = np.array([-seg[1], seg[0]]) / length
        if np.dot(normal, mid - centroid) < 0:
            normal = -normal
        faces.append({"i": i, "p0": pts[i], "p1": pts[(i + 1) % n], "mid_xy": mid,
                      "a_xy": a, "b_xy": b, "outward": normal, "dist_m": float(d[j]),
                      "street_key": street_pts[j, 2], "len_m": length,
                      "origin": pts[0], "lat_m": lat_m, "lon_m": lon_m})
    # One face per street: the longest edge nearest that street.
    best: dict = {}
    for f in faces:
        k = f["street_key"]
        if k not in best or f["len_m"] > best[k]["len_m"]:
            best[k] = f
    return sorted(best.values(), key=lambda f: -f["len_m"])[:2]


def band_polygon(face: dict, offset_m: float = FACE_OFFSET_M,
                 depth_m: float = FACE_DEPTH_M) -> list[tuple[float, float]]:
    """The sidewalk strip outside one face, as a lon/lat quadrilateral."""
    o, n = face["outward"], face["origin"]
    a, b = face["a_xy"] + o * offset_m, face["b_xy"] + o * offset_m
    c, d = b + o * depth_m, a + o * depth_m
    return [(float(n[0] + p[0] / face["lon_m"]), float(n[1] + p[1] / face["lat_m"]))
            for p in (a, b, c, d)]


# ---------------------------------------------------------------------------
# the detector
# ---------------------------------------------------------------------------

def rgb_to_hsv(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = img.astype(np.float32) / 255.0
    mx, mn = x.max(axis=-1), x.min(axis=-1)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return None, s, mx      # hue is not used


def awning_fraction(img: np.ndarray, mask: np.ndarray) -> float:
    """Share of `mask` pixels that are awning-like (see the module docstring)."""
    n = int(mask.sum())
    if n == 0:
        return 0.0
    _, s, v = rgb_to_hsv(img)
    coloured_and_lit = (s >= SAT_MIN) & (v >= VALUE_MIN)
    return float((coloured_and_lit & mask).sum() / n)


def _polygon_mask(poly: list[tuple[float, float]], m: ortho.Mosaic) -> np.ndarray:
    from PIL import Image, ImageDraw

    h, w = m.shape
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).polygon([m.to_pixel(lon, lat) for lon, lat in poly], fill=255)
    return np.asarray(im) > 0


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def corridor_buildings(con, corridor: tuple, *, footprint_table: str = FOOTPRINT_TABLE,
                       address_table: str = ADDRESS_TABLE) -> tuple[pd.DataFrame, np.ndarray]:
    """Footprints inside the corridor box + the corridor's street points."""
    _label, boro, pat, min_lat, min_lon, max_lat, max_lon = corridor
    con.execute("LOAD spatial")
    pts = con.execute(f"""
        SELECT lon, lat, street_name FROM {address_table}
        WHERE frame = 'street' AND borough = ? AND upper(street_name) LIKE ?
          AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
    """, [boro, pat, min_lat, max_lat, min_lon, max_lon]).fetchdf()
    fps = con.execute(f"""
        SELECT bin, bbl, ST_AsGeoJSON(geom) AS gj, height_roof_ft
        FROM {footprint_table}
        WHERE geom IS NOT NULL
          AND ST_Y(ST_Centroid(geom)) BETWEEN ? AND ?
          AND ST_X(ST_Centroid(geom)) BETWEEN ? AND ?
    """, [min_lat, max_lat, min_lon, max_lon]).fetchdf()
    arr = pts[["lon", "lat", "street_name"]].to_numpy(dtype=object) if len(pts) else np.empty((0, 3))
    return fps, arr


def _exterior_rings(gj: str) -> list[list[tuple[float, float]]]:
    import json

    g = json.loads(gj)
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g.get("coordinates", [])
    return [[(float(x), float(y)) for x, y, *_ in poly[0]] for poly in polys if poly]


def run_awnings(con, corridors=CORRIDORS, year: int = 2024, z: int = ortho.NATIVE_ZOOM, *,
                fetch_fn=None, root: pathlib.Path = ortho.CACHE_ROOT, keep_crops: bool = True,
                log=None, footprint_table: str = FOOTPRINT_TABLE,
                address_table: str = ADDRESS_TABLE) -> list[dict]:
    today = dt.date.today()
    rows = []
    for corr in corridors:
        fps, pts = corridor_buildings(con, corr, footprint_table=footprint_table,
                                      address_table=address_table)
        if log:
            log(f"{corr[0]}: {len(fps)} footprints in box, {len(pts)} street points")
        if not len(pts):
            continue
        # Every footprint's rings and centroid, so a band can subtract the
        # neighbours it overlaps (see `_polygon_mask` call below).
        all_rings = [_exterior_rings(gj) for gj in fps["gj"]]
        cents = np.array([[np.mean([q[0] for rg in rings for q in rg]) if rings else np.nan,
                           np.mean([q[1] for rg in rings for q in rg]) if rings else np.nan]
                          for rings in all_rings])
        for k, r in enumerate(fps.itertuples(index=False)):
            faces = []
            for ring in all_rings[k]:
                faces += street_faces(ring, pts)
            faces = faces[:2]
            if not faces:
                continue
            fracs, crops = [], []
            for f in faces:
                poly = band_polygon(f)
                lats, lons = [p[1] for p in poly], [p[0] for p in poly]
                bbox = (min(lats), min(lons), max(lats), max(lons))
                try:
                    m = ortho.mosaic(year, bbox, z, root=root, fetch_fn=fetch_fn)
                except ortho.OrthoUnavailable:
                    continue
                mask = _polygon_mask(poly, m)
                # THE BAND IS SIDEWALK ONLY. The first run's top "awnings" were
                # a blue pool cover and a dark roof next door: a band pushed
                # outward from a footprint edge can land on the neighbour when
                # the edge faces a rear yard or a party wall near the street.
                # Every footprint within NEIGHBOUR_M is subtracted, the
                # building's own included.
                lat_m, lon_m = _m_per_deg(float(f["origin"][1]))
                near = np.hypot((cents[:, 0] - f["origin"][0]) * lon_m,
                                (cents[:, 1] - f["origin"][1]) * lat_m) <= NEIGHBOUR_M
                for j in np.flatnonzero(near):
                    for rg in all_rings[j]:
                        mask &= ~_polygon_mask(rg, m)
                if mask.sum() < MIN_BAND_PX:
                    continue
                fracs.append(awning_fraction(m.img, mask))
                if keep_crops:
                    crops.append(_crop_b64(m, mask, f))
            if not fracs:
                continue
            rows.append({
                "bin": str(r.bin), "bbl": r.bbl, "corridor": corr[0],
                "awning_faces": int(sum(fr >= AWNING_MIN for fr in fracs)),
                "face_count": len(fracs), "awning_frac": round(max(fracs), 4),
                "ortho_year": year, "computed_on": today,
                "crops": crops, "fracs": fracs,
            })
    return rows


def _crop_b64(m: ortho.Mosaic, mask: np.ndarray, face: dict, pad_m: float = 6.0) -> str:
    from PIL import Image, ImageDraw

    ys, xs = np.where(mask)
    if not len(ys):
        return ""
    lat = float(face["origin"][1])
    pad = int(pad_m / ortho.metres_per_pixel(lat, m.z))
    y0, y1 = max(0, ys.min() - pad), min(m.img.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(m.img.shape[1], xs.max() + pad + 1)
    im = Image.fromarray(m.img[y0:y1, x0:x1]).convert("RGB")
    # Outline the band so the reviewer sees WHERE the strip was measured.
    edge = mask[y0:y1, x0:x1]
    draw = ImageDraw.Draw(im)
    p = np.pad(edge, 1)
    inner = p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    for yy, xx in np.argwhere(edge & ~inner)[::2]:
        draw.point((int(xx), int(yy)), fill=(255, 0, 255))
    im.thumbnail((REVIEW_PX, REVIEW_PX))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


WRITE_COLUMNS = ("bin", "bbl", "corridor", "awning_faces", "face_count", "awning_frac",
                 "ortho_year", "computed_on")


def write_awnings(con, rows: list[dict], corridors=None, year: int = 2024) -> int:
    """Replace the run's corridors wholesale. A per-BIN upsert left 900 stale
    rows behind when a detector change dropped buildings from the run
    (2026-09-17); a corridor x year is the unit a run produces, so it is the
    unit a write replaces."""
    if not rows and not corridors:
        return 0
    labels = sorted({r["corridor"] for r in rows} | {c[0] for c in (corridors or ())})
    cols = ", ".join(WRITE_COLUMNS)
    con.execute("BEGIN")
    try:
        con.execute(f"DELETE FROM {OUT_TABLE} WHERE ortho_year = ? "
                    f"AND corridor IN (SELECT unnest(?::VARCHAR[]))", [year, labels])
        if not rows:
            con.execute("COMMIT")
            return 0
        con.executemany(f"INSERT INTO {OUT_TABLE} ({cols}) VALUES ({', '.join('?' for _ in WRITE_COLUMNS)})",
                        [[r.get(c) for c in WRITE_COLUMNS] for r in rows])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(rows)


def review_html(rows: list[dict], path: pathlib.Path, ll157: pd.DataFrame | None = None) -> pathlib.Path:
    """100 faces: half the highest awning_frac positives, half near the cut,
    with the LL157 premises state on the lot where a filing exists."""
    faces = [(r, i) for r in rows for i in range(r["face_count"]) if r.get("crops") and i < len(r["crops"])]
    pos = sorted([f for f in faces if f[0]["fracs"][f[1]] >= AWNING_MIN], key=lambda f: -f[0]["fracs"][f[1]])
    neg = sorted([f for f in faces if f[0]["fracs"][f[1]] < AWNING_MIN], key=lambda f: -f[0]["fracs"][f[1]])
    picked = (pos[:REVIEW_FACES // 2] + neg[:REVIEW_FACES - min(len(pos), REVIEW_FACES // 2)])[:REVIEW_FACES]
    ll = {}
    if ll157 is not None and len(ll157):
        ll = ll157.groupby("bbl")["state"].agg(lambda s: ", ".join(sorted(set(s)))).to_dict()
    cards = []
    for k, (r, i) in enumerate(picked, 1):
        fr = r["fracs"][i]
        verdict = "awning" if fr >= AWNING_MIN else "no awning"
        cards.append(f"""
        <section class="face" data-bin="{r['bin']}" data-face="{i}" data-detector="{verdict}">
          <header><b>{k}.</b> BIN {r['bin']} · BBL {r['bbl']} · {html.escape(r['corridor'])} · face {i + 1}/{r['face_count']}
            <span class="tag {'pos' if fr >= AWNING_MIN else 'neg'}">detector: {verdict} ({fr:.0%})</span>
            <span class="tag">LL157: {html.escape(ll.get(r['bbl'], 'no filing'))}</span></header>
          <img src="data:image/jpeg;base64,{r['crops'][i]}" alt="face">
          <label>Your call: <select><option value="">—</option><option>awning</option><option>no awning</option>
            <option>shed / scaffold</option><option>vehicle</option><option>cannot tell</option></select></label>
        </section>""")
    n_pos = sum(1 for r in rows if r["awning_faces"] > 0)
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Awning review</title>
<style>
:root {{ --bg:#fff; --fg:#1a1a1a; --muted:#666; --line:#ddd; --pos:#26c; --neg:#999; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#111; --fg:#eee; --muted:#aaa; --line:#333; }} }}
:root[data-theme="dark"] {{ --bg:#111; --fg:#eee; --muted:#aaa; --line:#333; }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,sans-serif; margin:0; padding:16px; }}
main {{ max-width:960px; margin:0 auto; }} h1 {{ font-size:1.4rem; }}
.caveat {{ color:var(--muted); border-left:3px solid var(--line); padding:.4rem .8rem; margin:1rem 0; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; }}
.face {{ border:1px solid var(--line); border-radius:6px; padding:10px; }}
.face header {{ font-size:.85rem; margin-bottom:.4rem; }}
.face img {{ width:100%; height:auto; display:block; margin:.3rem 0; }}
.tag {{ display:inline-block; font-size:.8rem; padding:.05rem .4rem; border:1px solid var(--line); border-radius:4px; margin-top:.2rem; }}
.tag.pos {{ border-color:var(--pos); }} .tag.neg {{ border-color:var(--neg); }}
button {{ padding:.4rem .9rem; margin-top:1rem; }}
</style></head><body><main>
<h1>Awnings on the D82 corridors — 2024 ortho, {len(picked)} faces</h1>
<p>{n_pos} of {len(rows)} corridor buildings have at least one detected awning face. Shown: the strongest
positives and the faces nearest the {AWNING_MIN:.0%} cut. The magenta dots outline the measured sidewalk band. Black/charcoal awnings and awnings in shadow are
missed by design (the first run counted every north-face shadow as an awning); the count is a floor.</p>
<div class="caveat">Nadir view: the strip is 0.5–3.5 m outside the footprint edge. Sidewalk sheds, box trucks
and stoop shadows are the known false positives; residential door awnings are counted. Gate (memo §5 row 4):
precision ≥ 0.8 vs LL157 occupied premises on 100 hand-checked faces — this page is that check.
Card context only; nothing enters a grade.</div>
<div class="grid">{''.join(cards)}</div>
<button onclick="exportVerdicts()">Export verdicts (JSON)</button><pre id="out"></pre>
<script>
function exportVerdicts() {{
  const out = []; let tp = 0, fp = 0;
  document.querySelectorAll('section.face').forEach(s => {{
    const v = s.querySelector('select').value; if (!v) return;
    out.push({{bin: s.dataset.bin, face: s.dataset.face, detector: s.dataset.detector, verdict: v}});
    if (s.dataset.detector === 'awning') {{ if (v === 'awning') tp++; else fp++; }}
  }});
  const p = tp + fp ? (tp / (tp + fp) * 100).toFixed(0) : '—';
  document.getElementById('out').textContent = `checked ${{out.length}}; precision on detector positives ${{p}}% (${{tp}}/${{tp + fp}})\\n` + JSON.stringify(out, null, 1);
}}
</script></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path
