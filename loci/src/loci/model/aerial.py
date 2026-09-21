"""Ortho 2022 -> 2024 ground change on permitted lots (AC-1 Gowanus, memo §5 item 3).

    analysis.lot_aerial_change(bbl, ortho_from, ortho_to, change_frac,
                               change_class, geom_source, pixels, dob_status,
                               named_site, zoom, computed_on)

    loci aerial change --gowanus | --bbox "minlat,minlon,maxlat,maxlon"
    loci aerial pull   --years 2022,2024 --gowanus | --boroughs MN,BK

WHAT THE MEASURE IS
---------------------------------------------------------------------------
For each D72 permitted lot (analysis.dev_pipeline stage='permitted', tagged
active / lapsed / stalled by model/dev_pipeline.py), the share of the lot's
pixels whose brightness moved by more than CHANGE_THRESHOLD between the
March-2022 and March-2024 flights, after the 2024 crop is put on the 2022
crop's brightness scale inside the lot mask (a robust gain/offset, so a
different sun, camera or processing chain does not read as change), plus a
COARSE CLASS from the 2024 texture:

    unchanged            change_frac < CHANGED_MIN, or the two crops still
                         share their structure (aligned NCC >= NCC_SAME; see
                         change_score -- brightness alone flagged 60% of
                         unchanged rowhouse blocks as change on the first
                         Gowanus run, because the sun moved)
    under_construction   changed, and the 2024 surface is busy or saturated
                         (formwork, rebar, tarps, stacked material)
    cleared              changed, and the 2024 surface is earth-coloured
    new_roof             changed, and the 2024 surface is a smooth grey/white
                         membrane sharing no structure with 2022
    no_imagery           fewer than MIN_PIXELS lot pixels (a sliver, or a
                         lot outside the tiled extent)

This is a HEURISTIC and it says so: sheds, tarpaulins, parked trucks and a
crane's shadow all change pixels (memo §5 threat column: "sheds, shadow").
The gate before any card use is memo §5 row 3 -- agreement >= 0.8 with the
DOB status on 100 hand-checked lots -- and a machine cannot hand-check, so
the run writes data/aerial/gowanus_change_review.html (2022 | 2024 crops,
the DOB status and this class, 100 lots) for the OWNER, and the table's
catalog comment reads "ungated: owner review pending" until that is done.

WHAT A TWO-YEAR BIN CANNOT SAY. When. A lot cleared in April 2022 and one
cleared in February 2024 read the same. The D72 `activity_status` carries
the permit dates; this carries the pixels; together they say "the permit is
live AND the ground moved" or "the permit is live and NOTHING moved", which
is the AC-1 question (memo §4: which "active" permits show ground change).

THE LOT GEOMETRY. A permitted lot's outline is the UNION of its 2022-era
building footprints (staging.building_footprint, base_bbl = the lot) --
`geom_source = 'footprint'` -- because those are the pixels a demolition or
a new roof changes. A lot with no footprint (already vacant when OTI last
edited) gets a square of PLUTO `lotarea` centred on the permit point,
`geom_source = 'lot_box'`; it is the honest fallback and it is labelled.

NAMED SITES (memo §4). The two CSO-tank sites (Butler/Nevins = RH-034 head
of canal; 2 Ave / 5 St = the Owls Head tank), the bulkhead reaches and the
memo's named developments are carried as `named_site` labels on whichever
lot they resolve to, permitted or not, so the review page shows them by name.
"""
from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import html
import io
import json
import pathlib

import numpy as np
import pandas as pd

from loci.grid.pluto import PLUTO_CSV
from loci.sources.cities.nyc import orthoimagery as ortho

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "data" / "aerial"
OUT_TABLE = "analysis.lot_aerial_change"
FOOTPRINT_TABLE = "staging.building_footprint"
PIPELINE_TABLE = "analysis.dev_pipeline"

#: The Gowanus CANAL CORRIDOR: Atlantic Ave to Hamilton Ave, Hoyt St to 4th
#: Ave -- wider than recommendation_ledger.GOWANUS_BBOX (the retail core),
#: because the permitted lots, the CSO tanks and the bulkheads sit on the
#: canal, not on the 3rd/4th Ave strip. (min_lat, min_lon, max_lat, max_lon).
GOWANUS_BBOX: tuple[float, float, float, float] = (40.664, -74.003, 40.690, -73.975)

#: memo §4, resolved to the nearest lot within NAMED_SITE_RADIUS_M of the
#: point. Coordinates are the sites' street-level positions; a wrong lot is
#: visible on the review page, which is what it is for.
NAMED_SITES: tuple[tuple[str, float, float], ...] = (
    ("CSO tank: Butler St / Nevins St (RH-034, head of canal)", 40.6829, -73.9866),
    ("CSO tank: 2 Ave / 5 St (Owls Head tank)", 40.6740, -73.9908),
    ("175 3rd St / Gowanus Wharf", 40.6748, -73.9884),
    ("Public Place (Smith St / 5 St)", 40.6742, -73.9945),
    ("Nevins St / Union St site", 40.6795, -73.9873),
    ("Carroll St bridge site", 40.6777, -73.9887),
    ("bulkhead reach: Carroll St to 3 St (west bank)", 40.6765, -73.9905),
    ("bulkhead reach: 4 St basin", 40.6738, -73.9860),
)
NAMED_SITE_RADIUS_M = 60.0

#: Per-pixel brightness change (0-255 grey, after matching and a 5x5 mean)
#: that counts as "changed". 35 is ~14% of the range: a re-roofed surface
#: moves 60-120, a wet-vs-dry roof 10-25.
CHANGE_THRESHOLD = 35.0
#: Below this share of changed pixels a lot is `unchanged`.
CHANGED_MIN = 0.20
#: Edge density (share of lot pixels with gradient > EDGE_T), reported only:
#: the 2024 flight is systematically sharper than 2022 (edge density ~2x on
#: unchanged roofs), so it is not a class signal on its own.
EDGE_T = 30.0
#: STRUCTURE RETAINED. Normalised cross-correlation of the two high-passed
#: crops inside the mask, after a +/-ALIGN_PX block search (the two true-orthos
#: are registered to about a metre, ~9 px, and shadows move with the sun).
#: Measured 2026-09-17 on eleven hand-read Gowanus lots: unchanged rowhouses
#: 0.22-0.59, a genuine new roof 0.29, a cleared lot 0.07, a site under
#: construction 0.03. Above NCC_SAME the lot is unchanged whatever the
#: brightness did; between NCC_PARTIAL and NCC_SAME it is unchanged only if
#: the 2024 surface is still textured (a rowhouse block with moved shadows),
#: because a new flat roof over an old textured one also lands there.
NCC_SAME = 0.40
NCC_PARTIAL = 0.20
ALIGN_PX = 14
ALIGN_STEP = 2
#: 2024 texture (grey std inside the mask) at or above which the surface is
#: "busy": formwork, rebar, stacked material, a rowhouse block.
TEXTURE_BUSY = 40.0
#: 2024 mean HSV saturation at or above which the surface is not a roof or
#: bare ground (blue tarps, orange fencing, plant).
SAT_BUSY = 0.15
#: 2024 mean (R - B) at or above which the surface is earth or rubble rather
#: than a grey/white membrane.
EARTH_RB = 8.0
#: Illumination match: the contrast gain between two flights of the same
#: surface is allowed to move this much; more than that is the surface.
GAIN_MIN, GAIN_MAX = 0.8, 1.25
#: A lot mask with fewer pixels than this is a sliver, not an observation.
MIN_PIXELS = 400
#: Review crops: the mask's bbox plus this many metres each side, at most
#: REVIEW_PX on the long side, JPEG.
REVIEW_MARGIN_M = 8.0
REVIEW_PX = 240
REVIEW_LOTS = 100

CLASSES = ("unchanged", "cleared", "under_construction", "new_roof", "no_imagery")


@dataclasses.dataclass(frozen=True)
class Lot:
    bbl: str
    rings: tuple[tuple[tuple[float, float], ...], ...]   # polygons as (lon, lat) rings
    geom_source: str
    dob_status: str | None
    named_site: str | None
    lon: float
    lat: float

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        lons = [p[0] for r in self.rings for p in r]
        lats = [p[1] for r in self.rings for p in r]
        return min(lats), min(lons), max(lats), max(lons)


# ---------------------------------------------------------------------------
# raster arithmetic (numpy only; no scipy, no opencv)
# ---------------------------------------------------------------------------

def grey(img: np.ndarray) -> np.ndarray:
    return (0.299 * img[..., 0] + 0.587 * img[..., 1] + 0.114 * img[..., 2]).astype(np.float32)


def box_mean(a: np.ndarray, k: int = 5) -> np.ndarray:
    """k x k mean filter via an integral image. Edges replicate."""
    pad = k // 2
    p = np.pad(a.astype(np.float64), pad, mode="edge")
    s = np.cumsum(np.cumsum(p, axis=0), axis=1)
    s = np.pad(s, ((1, 0), (1, 0)))
    out = (s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]) / (k * k)
    return out.astype(np.float32)


def gradient_magnitude(g: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(g)
    return np.hypot(gx, gy)


def histogram_match(src: np.ndarray, ref: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Put `src` on `ref`'s brightness scale INSIDE `mask`: a robust gain/offset.

    NOT a full quantile match, on purpose. Quantile matching forces src's
    whole distribution onto ref's, so a lot that is half re-roofed in a new
    shade (half its pixels moved) is mapped straight back onto the old roof
    and reads unchanged -- measured on a synthetic half-lot before this was
    written. What differs between two flights of the SAME surface is
    illumination and sensor response, which is a gain and an offset; so the
    gain is the IQR ratio clamped to [GAIN_MIN, GAIN_MAX] and the offset
    aligns the medians. A spatial rearrangement survives that; a sunnier day
    does not.
    """
    s = src[mask].ravel()
    r = ref[mask].ravel()
    if s.size < 2 or r.size < 2:
        return src
    iqr_s = float(np.subtract(*np.percentile(s, [75, 25]))) or 1.0
    iqr_r = float(np.subtract(*np.percentile(r, [75, 25]))) or 1.0
    gain = float(np.clip(iqr_r / iqr_s, GAIN_MIN, GAIN_MAX))
    offset = float(np.median(r) - gain * np.median(s))
    return (src * gain + offset).astype(np.float32)


def rasterize(lot: Lot, m: ortho.Mosaic) -> np.ndarray:
    """Boolean mask of the lot's polygons in mosaic pixels (PIL polygon fill)."""
    from PIL import Image, ImageDraw

    h, w = m.shape
    im = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(im)
    for ring in lot.rings:
        pts = [m.to_pixel(lon, lat) for lon, lat in ring]
        if len(pts) >= 3:
            draw.polygon(pts, fill=255)
    return np.asarray(im) > 0


def align_ncc(ha: np.ndarray, hb: np.ndarray, mask: np.ndarray, r: int = ALIGN_PX,
              step: int = ALIGN_STEP) -> tuple[float, int, int]:
    """Best NCC of two high-passed crops inside `mask` over a +/-r px shift.

    Returns (ncc, dy, dx). A block search rather than a phase correlation
    because the mask is irregular and the search window is tiny.
    """
    ys, xs = np.where(mask)
    if not len(ys):
        return 0.0, 0, 0
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    H, W = ha.shape
    best = (-1.0, 0, 0)
    for dy in range(-r, r + 1, step):
        for dx in range(-r, r + 1, step):
            ya0, ya1 = max(y0, y0 + dy), min(y1, y1 + dy)
            xa0, xa1 = max(x0, x0 + dx), min(x1, x1 + dx)
            if (ya1 - ya0 < 10 or xa1 - xa0 < 10 or ya0 - dy < 0 or ya1 - dy > H
                    or xa0 - dx < 0 or xa1 - dx > W):
                continue
            m = mask[ya0:ya1, xa0:xa1]
            a = ha[ya0:ya1, xa0:xa1][m]
            b = hb[ya0 - dy:ya1 - dy, xa0 - dx:xa1 - dx][m]
            if a.size < 10 or a.std() < 1e-6 or b.std() < 1e-6:
                continue
            c = float(np.corrcoef(a, b)[0, 1])
            if c > best[0]:
                best = (c, dy, dx)
    return best


def change_score(img_a: np.ndarray, img_b: np.ndarray, mask: np.ndarray) -> dict:
    """The per-lot measure on two aligned RGB crops and a lot mask.

    `change_frac` is the brightness measure (share of lot pixels that moved
    by more than CHANGE_THRESHOLD after the gain/offset match). The CLASS is
    decided by structure first (align_ncc), then by the 2024 surface:

        no_imagery          mask under MIN_PIXELS
        unchanged           change_frac < CHANGED_MIN, or ncc >= NCC_SAME, or
                            ncc >= NCC_PARTIAL with a still-textured 2024 surface
        under_construction  2024 surface busy (std >= TEXTURE_BUSY) or saturated
        cleared             2024 surface earth-coloured (R - B >= EARTH_RB)
        new_roof            otherwise: a smooth grey/white surface that shares
                            no structure with 2022
    """
    n = int(mask.sum())
    empty = {"change_frac": None, "change_class": "no_imagery", "pixels": n, "ncc": None,
             "shift_px": None, "edge_density_to": None, "edge_density_from": None,
             "texture_to": None, "sat_to": None, "rb_to": None}
    if n < MIN_PIXELS:
        return empty
    ga, gb = grey(img_a), grey(img_b)
    gb_m = histogram_match(gb, ga, mask)
    diff = np.abs(box_mean(gb_m) - box_mean(ga))
    frac = float(((diff > CHANGE_THRESHOLD) & mask).sum() / n)
    ha, hb = ga - box_mean(ga, 15), gb - box_mean(gb, 15)
    ncc, dy, dx = align_ncc(ha, hb, mask)
    edge_b = float(((gradient_magnitude(gb) > EDGE_T) & mask).sum() / n)
    edge_a = float(((gradient_magnitude(ga) > EDGE_T) & mask).sum() / n)
    texture = float(gb[mask].std())
    x = img_b.astype(np.float32)
    mx = x.max(axis=-1)
    sat = float(((mx - x.min(axis=-1)) / np.maximum(mx, 1.0))[mask].mean())
    rb = float((x[..., 0] - x[..., 2])[mask].mean())
    if (frac < CHANGED_MIN or ncc >= NCC_SAME
            or (ncc >= NCC_PARTIAL and texture >= TEXTURE_BUSY)):
        cls = "unchanged"
    elif texture >= TEXTURE_BUSY or sat >= SAT_BUSY:
        cls = "under_construction"
    elif rb >= EARTH_RB:
        cls = "cleared"
    else:
        cls = "new_roof"
    return {"change_frac": round(frac, 4), "change_class": cls, "pixels": n,
            "ncc": round(ncc, 3), "shift_px": (int(dy), int(dx)),
            "edge_density_to": round(edge_b, 4), "edge_density_from": round(edge_a, 4),
            "texture_to": round(texture, 1), "sat_to": round(sat, 3), "rb_to": round(rb, 1)}


# ---------------------------------------------------------------------------
# lots
# ---------------------------------------------------------------------------

def _m_per_deg(lat: float) -> tuple[float, float]:
    lat_m = 111_320.0
    return lat_m, lat_m * np.cos(np.radians(lat))


def lot_box(lon: float, lat: float, lotarea_sqft: float | None) -> tuple[tuple[float, float], ...]:
    """A square of PLUTO lotarea centred on the point; 400 m2 if area is unknown."""
    area = float(lotarea_sqft) if lotarea_sqft is not None and np.isfinite(lotarea_sqft) else 0.0
    m2 = area * 0.092903 or 400.0
    side = float(np.sqrt(m2))
    lat_m, lon_m = _m_per_deg(lat)
    dlat, dlon = side / 2 / lat_m, side / 2 / lon_m
    return ((lon - dlon, lat - dlat), (lon + dlon, lat - dlat),
            (lon + dlon, lat + dlat), (lon - dlon, lat + dlat), (lon - dlon, lat - dlat))


def _rings_from_geojson(text: str) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Exterior rings of a GeoJSON (Multi)Polygon. Holes are dropped: a
    courtyard is a few pixels and the mask is a fraction, not a survey."""
    g = json.loads(text)
    if g["type"] == "Polygon":
        polys = [g["coordinates"]]
    elif g["type"] == "MultiPolygon":
        polys = g["coordinates"]
    elif g["type"] == "GeometryCollection":
        polys = [x["coordinates"] for x in g["geometries"] if x["type"] == "Polygon"]
        polys += [q for x in g["geometries"] if x["type"] == "MultiPolygon" for q in x["coordinates"]]
    else:
        return ()
    return tuple(tuple((float(x), float(y)) for x, y, *_ in poly[0]) for poly in polys if poly)


def permitted_lots(con, bbox: tuple[float, float, float, float] = GOWANUS_BBOX,
                   pluto_csv: pathlib.Path | str = PLUTO_CSV) -> list[Lot]:
    """D72 permitted lots in the bbox, each with footprint rings or a lot box,
    plus the memo's named sites resolved to their nearest lot."""
    con.execute("LOAD spatial")
    min_lat, min_lon, max_lat, max_lon = bbox
    jobs = con.execute(f"""
        SELECT bbl, any_value(activity_status) AS dob_status,
               avg(ST_X(geom)) AS lon, avg(ST_Y(geom)) AS lat
        FROM {PIPELINE_TABLE}
        WHERE stage = 'permitted' AND activity_status IN ('active', 'lapsed', 'stalled')
          AND ST_Y(geom) BETWEEN ? AND ? AND ST_X(geom) BETWEEN ? AND ?
          AND bbl IS NOT NULL
        GROUP BY bbl
    """, [min_lat, max_lat, min_lon, max_lon]).fetchdf()

    # Named sites -> nearest PLUTO lot within NAMED_SITE_RADIUS_M.
    pluto = con.execute("""
        SELECT bbl AS bbl, TRY_CAST(latitude AS DOUBLE) AS lat,
               TRY_CAST(longitude AS DOUBLE) AS lon, TRY_CAST(lotarea AS DOUBLE) AS lotarea
        FROM read_csv_auto(?, ALL_VARCHAR = TRUE)
        WHERE TRY_CAST(latitude AS DOUBLE) BETWEEN ? AND ?
          AND TRY_CAST(longitude AS DOUBLE) BETWEEN ? AND ?
    """, [str(pluto_csv), min_lat, max_lat, min_lon, max_lon]).fetchdf()
    named: dict[str, str] = {}
    if len(pluto):
        lat_m, lon_m = _m_per_deg((min_lat + max_lat) / 2)
        for label, s_lat, s_lon in NAMED_SITES:
            d = np.hypot((pluto["lat"] - s_lat) * lat_m, (pluto["lon"] - s_lon) * lon_m)
            i = int(d.idxmin())
            if d[i] <= NAMED_SITE_RADIUS_M:
                named[pluto.loc[i, "bbl"]] = label
    extra = pluto[pluto["bbl"].isin(named) & ~pluto["bbl"].isin(jobs["bbl"])]
    lots = pd.concat([
        jobs.assign(lotarea=jobs["bbl"].map(pluto.set_index("bbl")["lotarea"].to_dict()
                                            if len(pluto) else {})),
        extra.assign(dob_status=None)[["bbl", "dob_status", "lon", "lat", "lotarea"]],
    ], ignore_index=True)

    fp = con.execute(f"""
        SELECT bbl, ST_AsGeoJSON(ST_Union_Agg(geom)) AS gj
        FROM {FOOTPRINT_TABLE}
        WHERE bbl IN (SELECT unnest(?::VARCHAR[])) AND geom IS NOT NULL
        GROUP BY bbl
    """, [lots["bbl"].tolist()]).fetchdf() if _table_exists(con, FOOTPRINT_TABLE) else pd.DataFrame()
    gjs = dict(zip(fp["bbl"], fp["gj"])) if len(fp) else {}

    out = []
    for r in lots.itertuples(index=False):
        if r.bbl in gjs and _rings_from_geojson(gjs[r.bbl]):
            rings, src = _rings_from_geojson(gjs[r.bbl]), "footprint"
        else:
            rings, src = (lot_box(r.lon, r.lat, r.lotarea),), "lot_box"
        out.append(Lot(bbl=str(r.bbl), rings=rings, geom_source=src,
                       dob_status=r.dob_status if isinstance(r.dob_status, str) else None,
                       named_site=named.get(r.bbl), lon=float(r.lon), lat=float(r.lat)))
    return out


def _table_exists(con, qualified: str) -> bool:
    schema, _, name = qualified.partition(".")
    return bool(con.execute("SELECT count(*) FROM information_schema.tables "
                            "WHERE table_schema = ? AND table_name = ?",
                            [schema, name]).fetchone()[0])


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def _crop(img: np.ndarray, mask: np.ndarray, m: ortho.Mosaic, lat: float) -> np.ndarray:
    ys, xs = np.where(mask)
    if not len(ys):
        return img[:REVIEW_PX, :REVIEW_PX]
    pad = int(REVIEW_MARGIN_M / ortho.metres_per_pixel(lat, m.z))
    y0, y1 = max(0, ys.min() - pad), min(img.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(img.shape[1], xs.max() + pad + 1)
    return img[y0:y1, x0:x1]


def _jpeg_b64(arr: np.ndarray, max_px: int = REVIEW_PX) -> str:
    from PIL import Image

    im = Image.fromarray(arr)
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def run_change(lots: list[Lot], years: tuple[int, int] = (2022, 2024),
               z: int = ortho.NATIVE_ZOOM, *, fetch_fn=None,
               root: pathlib.Path = ortho.CACHE_ROOT, keep_crops: bool = True,
               log=None) -> list[dict]:
    """Score every lot. Returns rows for OUT_TABLE plus (optional) review crops."""
    y_from, y_to = years
    today = dt.date.today()
    rows = []
    for i, lot in enumerate(lots, 1):
        try:
            if not all(np.isfinite(v) for v in lot.bbox):
                raise ortho.OrthoUnavailable(f"lot {lot.bbl} has no finite geometry")
            ma = ortho.mosaic(y_from, lot.bbox, z, root=root, fetch_fn=fetch_fn)
            mb = ortho.mosaic(y_to, lot.bbox, z, root=root, fetch_fn=fetch_fn)
        except ortho.OrthoUnavailable as exc:
            rows.append({"bbl": lot.bbl, "ortho_from": y_from, "ortho_to": y_to,
                         "change_frac": None, "change_class": "no_imagery",
                         "geom_source": lot.geom_source, "pixels": 0,
                         "dob_status": lot.dob_status, "named_site": lot.named_site,
                         "zoom": z, "computed_on": today, "error": str(exc)})
            continue
        mask = rasterize(lot, ma)
        sc = change_score(ma.img, mb.img, mask)
        row = {"bbl": lot.bbl, "ortho_from": y_from, "ortho_to": y_to,
               "change_frac": sc["change_frac"], "change_class": sc["change_class"],
               "geom_source": lot.geom_source, "pixels": sc["pixels"],
               "dob_status": lot.dob_status, "named_site": lot.named_site,
               "zoom": z, "computed_on": today, "ncc": sc["ncc"],
               "edge_density_to": sc["edge_density_to"], "lon": lot.lon, "lat": lot.lat}
        if keep_crops:
            row["crop_from"] = _jpeg_b64(_crop(ma.img, mask, ma, lot.lat))
            row["crop_to"] = _jpeg_b64(_crop(mb.img, mask, mb, lot.lat))
        rows.append(row)
        if log and i % 25 == 0:
            log(f"{i}/{len(lots)} lots scored")
    return rows


WRITE_COLUMNS = ("bbl", "ortho_from", "ortho_to", "change_frac", "change_class",
                 "geom_source", "pixels", "dob_status", "named_site", "zoom", "computed_on")


def write_change(con, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = ", ".join(WRITE_COLUMNS)
    con.execute("BEGIN")
    try:
        con.executemany(f"DELETE FROM {OUT_TABLE} WHERE bbl = ? AND ortho_from = ? AND ortho_to = ?",
                        [[r["bbl"], r["ortho_from"], r["ortho_to"]] for r in rows])
        con.executemany(f"INSERT INTO {OUT_TABLE} ({cols}) VALUES ({', '.join('?' for _ in WRITE_COLUMNS)})",
                        [[r.get(c) for c in WRITE_COLUMNS] for r in rows])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(rows)


# ---------------------------------------------------------------------------
# the review page -- the owner's hand-check (memo §5 row 3 gate)
# ---------------------------------------------------------------------------

def _review_order(rows: list[dict]) -> list[dict]:
    """Named sites first, then the permitted lots with the MOST change, then
    a spread of the rest: the gate is agreement with DOB status, and the
    disagreements live at the extremes."""
    scored = [r for r in rows if r.get("change_class") != "no_imagery"]
    named = [r for r in scored if r.get("named_site")]
    rest = sorted((r for r in scored if not r.get("named_site")),
                  key=lambda r: -(r.get("change_frac") or 0))
    return (named + rest)[:REVIEW_LOTS]


def review_html(rows: list[dict], path: pathlib.Path, title: str,
                years: tuple[int, int] = (2022, 2024)) -> pathlib.Path:
    picked = _review_order(rows)
    y0, y1 = years
    n_all = len([r for r in rows if r.get("change_class") != "no_imagery"])
    by_class = pd.Series([r["change_class"] for r in rows]).value_counts().to_dict()
    cards = []
    for i, r in enumerate(picked, 1):
        site = f"<div class='site'>{html.escape(r['named_site'])}</div>" if r.get("named_site") else ""
        cards.append(f"""
        <section class="lot" data-bbl="{r['bbl']}" data-class="{r['change_class']}">
          <header><b>{i}.</b> BBL {r['bbl']} {site}
            <span class="tag dob">DOB: {html.escape(str(r.get('dob_status') or 'not permitted'))}</span>
            <span class="tag cls {r['change_class']}">ortho: {r['change_class'].replace('_', ' ')}
              ({(r.get('change_frac') or 0):.0%} of {r.get('pixels', 0):,} px, ncc {r.get('ncc') if r.get('ncc') is not None else '—'}, {r['geom_source']})</span>
          </header>
          <div class="pair">
            <figure><img src="data:image/jpeg;base64,{r.get('crop_from', '')}" alt="{y0}"><figcaption>{y0}</figcaption></figure>
            <figure><img src="data:image/jpeg;base64,{r.get('crop_to', '')}" alt="{y1}"><figcaption>{y1}</figcaption></figure>
          </div>
          <label class="verdict">Your call:
            <select name="v-{r['bbl']}"><option value="">—</option>
              <option>agree</option><option>disagree: unchanged</option><option>disagree: cleared</option>
              <option>disagree: under construction</option><option>disagree: new roof</option>
              <option>cannot tell (shed / shadow / tree)</option></select></label>
        </section>""")
    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --bg:#fff; --fg:#1a1a1a; --muted:#666; --line:#ddd; --ok:#2a7; --warn:#c80; --bad:#c33; --new:#26c; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#111; --fg:#eee; --muted:#aaa; --line:#333; }} }}
:root[data-theme="dark"] {{ --bg:#111; --fg:#eee; --muted:#aaa; --line:#333; }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,sans-serif; margin:0; padding:16px; }}
main {{ max-width:960px; margin:0 auto; }}
h1 {{ font-size:1.4rem; margin:0 0 .3rem; }}
.caveat {{ color:var(--muted); border-left:3px solid var(--line); padding:.4rem .8rem; margin:1rem 0; }}
.lot {{ border-top:1px solid var(--line); padding:14px 0; }}
.lot header {{ display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; }}
.site {{ font-weight:600; color:var(--new); width:100%; }}
.tag {{ font-size:.85rem; padding:.1rem .5rem; border-radius:4px; border:1px solid var(--line); }}
.cls.unchanged {{ border-color:var(--ok); }} .cls.cleared {{ border-color:var(--warn); }}
.cls.under_construction {{ border-color:var(--bad); }} .cls.new_roof {{ border-color:var(--new); }}
.pair {{ display:flex; gap:12px; margin:.6rem 0; }}
figure {{ margin:0; flex:1; }} figure img {{ width:100%; height:auto; display:block; border:1px solid var(--line); }}
figcaption {{ font-size:.8rem; color:var(--muted); text-align:center; }}
.verdict select {{ margin-left:.4rem; }}
.export {{ margin:1rem 0; }} button {{ padding:.4rem .9rem; }}
@media (max-width:480px) {{ .pair {{ flex-direction:column; }} }}
</style></head><body><main>
<h1>{html.escape(title)}</h1>
<p>{len(picked)} of {n_all} scored lots shown (named sites first, then the most-changed permitted lots).
Class counts over all scored lots: {', '.join(f'{k} {v}' for k, v in sorted(by_class.items()))}.</p>
<div class="caveat">Nadir, leaf-off, {y0} and {y1} flights (March). A two-year bin dates nothing finer.
"ortho" is a heuristic on brightness change after histogram matching plus {y1} edge density; sheds, tarpaulins,
parked trucks and crane shadows all read as change. The gate (memo §5 row 3) is agreement ≥ 0.8 with the DOB
status on 100 hand-checked lots; this page IS that check. Pick a verdict per lot and export at the bottom.
Nothing here enters a grade.</div>
{''.join(cards)}
<div class="export"><button onclick="exportVerdicts()">Export verdicts (JSON)</button>
<pre id="out"></pre></div>
<script>
function exportVerdicts() {{
  const out = {{}};
  document.querySelectorAll('section.lot').forEach(s => {{
    const v = s.querySelector('select').value;
    if (v) out[s.dataset.bbl] = {{ ortho: s.dataset.class, verdict: v }};
  }});
  const n = Object.keys(out).length;
  const agree = Object.values(out).filter(o => o.verdict === 'agree').length;
  document.getElementById('out').textContent =
    `checked ${{n}}, agree ${{agree}} (${{n ? (agree / n * 100).toFixed(0) : 0}}%)\\n` + JSON.stringify(out, null, 1);
}}
</script>
</main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path
