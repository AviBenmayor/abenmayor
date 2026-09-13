"""The STREET sampling frame: one scored point every `L` metres along every
known street in scope (D84, docs/street_midpoint_frame.md).

WHY THIS EXISTS. The screen's frame was the residential tax lot (D38): one
PLUTO lot with UnitsRes > 0 is one address. That frame cannot see a street
nobody lives on yet -- the Navy Yard, the Gowanus/Red Hook industrial blocks,
a new street cut through a rezoned superblock -- because the frame is built
from residents. The owner's direction (2026-09-13): *"for addresses, we should
be sampling an address near the middle of every known street in the borough."*
Same motive as D75's removal of the eligibility gate: underdeveloped areas
must count, not disappear.

This module is the ONLY place CSCL column names live. It returns plain
`(point_id, lon, lat, borough, frontage_m, street_name, ...)` rows; nothing in
`model/` or `score/` ever sees `rw_type`, `nonped` or `boroughcode`, exactly as
`addresses.py` keeps BBL and `borocode` local.

THE KEEP RULE (verified against the live dataset 2026-09-13; §1.4 of the note):

    status          = '2'   -- Constructed
    rw_type         = 1     -- Street: the only feature type that carries house
                            --   number ranges and can front a storefront
    nonped         <> 'V'   -- pedestrians are not prohibited
    from_level_code = '13' AND to_level_code = '13'   -- at grade

32,291 of 41,784 MN+BK rows survive it (3,476.8 km). What is deliberately
excluded, and why: highways / ramps / tunnels / bridges (no frontage, and a
midpoint on a bridge is not a site); `rw_type=6` Path/Trail, which is every
park and greenway path including the private drives inside parks; Boardwalk,
StepStreet, Driveway, Alley, U-Turn, Ferry Route; `rw_type=12`
Non-Physical Street Segment -- CSCL's own name for the PAPER STREETS, of which
MN+BK has exactly 2; and the above/below-grade duplicates of a street's
footprint. Deliberately KEPT even though they look excludable: `trafdir='NV'`
Streets (161 rows) are pedestrian malls and plazas -- Fulton Mall, Dyckman St,
the Brooklyn Heights ped-ways -- which are real retail streets.

`nonped='D'` is NOT used: it is undocumented and self-contradictory as a
pedestrian flag (it covers the Central Park and Prospect Park drives AND
Manhattan Beach Promenade AND the Williamsburg Bridge pedestrian path).

THE TWO LENGTH TRAPS. DuckDB `GEOMETRY` carries no SRID and neither does a
GeoJSON coordinate list, so every length here is derived deliberately:

  * `shape_length` is **Web Mercator metres** -- inflated by 1/cos(phi), a
    measured median of 1.3211x the true length at NYC's latitude. It is not a
    length and it is not read anywhere in this module (pinned by a test).
  * `segmentlength` is US feet and agrees with the geometry at the median
    (1.0011) but not in the tails (p05 0.30, p95 1.64). It is used ONLY as a
    build-time cross-check, never as the length.
  * `ST_Length` on a 4326 geometry returns DEGREES and will not error.

Every length below is the polyline length after an explicit reprojection to
EPSG:2263 (NAD83 / New York Long Island, **US survey feet**), converted with
0.3048006096012192 m/ft -- the formula verified in the note against a geodesic
reference to 0.1 m.

SPACING. `L = 100 m` (`DEFAULT_SPACING_M`): the smallest round value at or
above the MN+BK median block face (81.9 m), so a street point stands for at
most one block face -- the same spatial unit a PLUTO lot frontage occupies.
`k = ceil(len / L)` points at arclength fractions `(2i-1)/2k`, evenly spaced
and never on an endpoint, so two segments meeting at a corner never put two
points on that corner. MULTIPART geometries (565 of the 32,291 kept) are split
PER PART: taking the longest part only would drop 33.4 km of kept street.

`physicalid` is documented as "a unique ID assigned to intersection-to-
intersection stretches of a street" and is NEAR-unique, not unique: MN+BK has
3 duplicated ids (all three outside the kept set). `point_id` uniqueness is
therefore ASSERTED at build time, not assumed.
"""
from __future__ import annotations

import datetime as dt
import math
import pathlib

import pandas as pd

from loci.sources.cities.nyc.addresses import BOROCODE, SCREEN_BOROUGHS
from loci.sources.cities.nyc.socrata import NYC_DOMAIN, fetch

#: registry.yaml id and Socrata dataset id (NYC Street Centerline (CSCL),
#: titled "Centerline" on the portal; automated weekly refresh).
SOURCE_ID = "nyc_cscl"
DATASET = "inkn-q76z"

#: The columns this module reads. `shape_length` is deliberately NOT among
#: them -- see the module docstring's length traps.
FIELDS = (
    "physicalid", "the_geom", "rw_type", "status", "nonped", "trafdir",
    "boroughcode", "segmentlength", "full_street_name", "streetwidth",
    "from_level_code", "to_level_code",
)

#: CSCL `rw_type`, the feature-type vocabulary (data dictionary, Centerline.pdf
#: p. 8-9). CLOSED on purpose: an unknown code means the vocabulary moved under
#: us, and silently dropping it would quietly shrink the frame -- the same
#: failure mode as a Socrata `$where` that stops matching. `segment_type` /
#: `segment_type_value` look like a usable feature type and are 100% NULL in
#: MN+BK; they are not read.
RW_TYPE = {
    1: "Street",
    2: "Highway",
    3: "Bridge",
    4: "Tunnel",
    5: "Boardwalk",
    6: "Path/Trail",
    7: "StepStreet",
    8: "Driveway",
    9: "Ramp",
    10: "Alley",
    11: "Unknown",
    12: "Non-Physical Street Segment",
    13: "U Turn",
    14: "Ferry Route",
}
KEEP_RW_TYPE = 1

#: Borough code -> the two-letter code the rest of the project speaks. Inverted
#: from addresses.BOROCODE so CSCL's `boroughcode` and PLUTO's `borocode` can
#: never drift apart: they are the same city vocabulary.
BOROUGH_OF_CODE = {v: k for k, v in BOROCODE.items()}

#: Metres per US survey foot -- EPSG:2263's unit. NOT 0.3048 (that is the
#: international foot); the difference is 2 ppm, which is nothing at segment
#: scale and is still written correctly because a wrong constant here would be
#: invisible forever.
US_FT_M = 0.3048006096012192

#: Point spacing, metres. See the module docstring.
DEFAULT_SPACING_M = 100.0

#: The kept-segment count the rule produced on 2026-09-13, and how far the
#: weekly refresh is allowed to move it before the build refuses. A silent
#: collapse to a tenth of the street network would read downstream as "these
#: neighbourhoods have no streets", which is exactly the failure the Socrata
#: reader's zero-row guard exists to prevent.
EXPECTED_KEPT_MNBK = 32_291
COUNT_TOLERANCE = 0.10


class StreetFrameError(RuntimeError):
    """A frame build that must not be mistaken for a city with fewer streets."""


# ----------------------------------------------------------------- fetching

def fetch_segments(boroughs: tuple[str, ...] = SCREEN_BOROUGHS, *,
                   use_cache: bool = True, asof: dt.date | None = None,
                   session=None) -> list[dict]:
    """Raw CSCL rows for `boroughs`, paged and cached under
    `data/raw/nyc_cscl/` by the shared Socrata reader (which RAISES on an
    exhausted retry and on a total-zero result rather than ingesting a silent
    empty city)."""
    codes = sorted(BOROCODE[b.upper()] for b in boroughs)
    where = "boroughcode in(" + ",".join(f"'{c}'" for c in codes) + ")"
    return fetch(SOURCE_ID, NYC_DOMAIN, DATASET,
                 select=",".join(FIELDS), where=where,
                 use_cache=use_cache, asof=asof, session=session)


# ------------------------------------------------------------- the keep rule

def _rw_type(row: dict) -> int:
    """`rw_type` as an int, refusing a code the vocabulary does not know."""
    raw = row.get("rw_type")
    try:
        code = int(str(raw).strip())
    except (TypeError, ValueError):
        raise StreetFrameError(
            f"CSCL row {row.get('physicalid')!r} has rw_type={raw!r}, which is not "
            f"an integer. The feature-type vocabulary is the whole keep rule; "
            f"refusing to guess.") from None
    if code not in RW_TYPE:
        raise StreetFrameError(
            f"CSCL rw_type={code} is not in the vocabulary {sorted(RW_TYPE)}. The "
            f"dataset refreshes weekly; re-read Centerline.pdf and decide whether "
            f"the new type fronts a storefront before extending RW_TYPE. Dropping "
            f"it silently would shrink the street frame with no trace.")
    return code


def keep_segment(row: dict) -> bool:
    """The §1.4 rule. See the module docstring for what each clause costs and
    why the pedestrian malls (`trafdir='NV'`) are kept."""
    return (
        row.get("status") == "2"
        and _rw_type(row) == KEEP_RW_TYPE
        and row.get("nonped") != "V"
        and row.get("from_level_code") == "13"
        and row.get("to_level_code") == "13"
    )


def keep_ladder(rows: list[dict]) -> list[tuple[str, int, float]]:
    """[(clause, rows surviving, km surviving)] -- the audit trail printed on
    every rebuild, so the filter is visible rather than asserted. The ladder is
    the artefact that would show a weekly refresh changing the meaning of
    `status` or `nonped` before the count assertion fired."""
    steps = [
        ("all rows in scope", lambda r: True),
        ("+ status='2' (Constructed)", lambda r: r.get("status") == "2"),
        ("+ rw_type=1 (Street)",
         lambda r: r.get("status") == "2" and _rw_type(r) == KEEP_RW_TYPE),
        ("+ nonped <> 'V' (pedestrians allowed)",
         lambda r: r.get("status") == "2" and _rw_type(r) == KEEP_RW_TYPE
         and r.get("nonped") != "V"),
        ("+ at grade (from/to level 13)", keep_segment),
    ]
    # One length per row, computed once: the ladder is five nested filters over
    # the same rows and reprojecting each of them five times would make the
    # audit trail the most expensive part of the build.
    lengths = {id(r): segment_length_m(parts_of(r))[0] for r in rows}
    out = []
    for label, pred in steps:
        kept = [r for r in rows if pred(r)]
        km = sum(lengths[id(r)] for r in kept) / 1000.0
        out.append((label, len(kept), km))
    return out


# --------------------------------------------------------------- geometry

def parts_of(row: dict) -> list[list[tuple[float, float]]]:
    """The row's MultiLineString parts as [(lon, lat), ...] lists. A row with
    no geometry yields no parts and contributes no points (it cannot be
    placed on a map, so there is nothing honest to do with it)."""
    geom = row.get("the_geom") or {}
    coords = geom.get("coordinates") or []
    if geom.get("type") == "LineString":
        coords = [coords]
    return [[(float(x), float(y)) for x, y in part] for part in coords if len(part) >= 2]


def _transformer():
    """4326 -> 2263, cached on the module. `always_xy=True` is REQUIRED:
    without it pyproj hands back (lat, lon) for 4326 and every length is
    computed from transposed coordinates -- a number that is wrong and does
    not look wrong."""
    global _TRANSFORMER
    try:
        return _TRANSFORMER
    except NameError:
        import pyproj
        _TRANSFORMER = pyproj.Transformer.from_crs(
            "EPSG:4326", "EPSG:2263", always_xy=True)
        return _TRANSFORMER


def _cumulative_ft(part: list[tuple[float, float]]) -> list[float]:
    """Cumulative planar length in US survey FEET along the part, projected to
    EPSG:2263. One transform call per part."""
    lon = [p[0] for p in part]
    lat = [p[1] for p in part]
    xs, ys = _transformer().transform(lon, lat)
    cum = [0.0]
    for i in range(len(xs) - 1):
        cum.append(cum[-1] + math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]))
    return cum


def segment_length_m(parts: list[list[tuple[float, float]]]) -> tuple[float, list[list[float]]]:
    """(total metres over every part, per-part cumulative metres). The ONE
    place a CSCL length is computed."""
    cums = [[c * US_FT_M for c in _cumulative_ft(part)] for part in parts]
    return (sum(c[-1] for c in cums) if cums else 0.0), cums


def _point_at(part: list[tuple[float, float]], cum: list[float], s: float) -> tuple[float, float]:
    """Linear interpolation along the polyline at arclength `s` metres."""
    if cum[-1] <= 0:
        return part[0]
    j = 0
    for i in range(len(cum) - 1):
        if cum[i] <= s <= cum[i + 1]:
            j = i
            break
        j = min(i + 1, len(cum) - 2)
    span = cum[j + 1] - cum[j]
    t = 0.0 if span <= 0 else (s - cum[j]) / span
    (x0, y0), (x1, y1) = part[j], part[j + 1]
    return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))


def split_points(part: list[tuple[float, float]], cum: list[float],
                 spacing_m: float) -> list[tuple[float, float, float]]:
    """[(lon, lat, frontage_m)] for one polyline part: `k = ceil(len/spacing)`
    points at arclength fractions `(2i-1)/2k`. A part shorter than `spacing`
    gets exactly one point, its MIDPOINT. `frontage_m` is the share of the
    part each point stands for (len/k) -- carried because a single point is a
    SAMPLE of its stretch, not a summary of it, and a reader has to be able to
    see how much street is behind one dot."""
    total = cum[-1]
    k = max(1, math.ceil(total / spacing_m)) if total > 0 else 1
    out = []
    for i in range(k):
        s = total * (2 * i + 1) / (2 * k)
        lon, lat = _point_at(part, cum, s)
        out.append((lon, lat, total / k))
    return out


# ------------------------------------------------------------ the frame API

def load_street_segments(rows: list[dict]) -> pd.DataFrame:
    """Raw CSCL rows -> the kept segments, with a true length.

    Columns: segment_id, borough, length_m, street_name, width_ft, n_parts,
    and `parts` (the geometry, kept because `street_midpoints` needs it and a
    second pass over the raw rows would be a second chance to disagree about
    which segments were kept).
    """
    kept = [r for r in rows if keep_segment(r)]
    recs = []
    for r in kept:
        parts = parts_of(r)
        if not parts:
            continue
        length_m, cums = segment_length_m(parts)
        boro = BOROUGH_OF_CODE.get(str(r.get("boroughcode")))
        if boro is None:
            raise StreetFrameError(
                f"CSCL boroughcode {r.get('boroughcode')!r} is not one of "
                f"{sorted(BOROUGH_OF_CODE)} -- the borough is the D78 scope key and "
                f"cannot be guessed.")
        recs.append({
            "segment_id": str(r.get("physicalid")),
            "borough": boro,
            "length_m": length_m,
            "street_name": r.get("full_street_name"),
            "width_ft": _num(r.get("streetwidth")),
            "n_parts": len(parts),
            "segmentlength_ft": _num(r.get("segmentlength")),
            "parts": parts,
            "cums": cums,
        })
    return pd.DataFrame(recs)


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def check_length_sanity(segments: pd.DataFrame, tol: float = 0.01) -> float:
    """Median of (computed metres) / (`segmentlength` feet x 0.3048), which
    must be 1.0 +/- `tol`. The published field is unreliable per row (p05 0.30,
    p95 1.64) but its MEDIAN is a real check on the projection: if
    `always_xy` were dropped, or EPSG:2263's feet were converted as metres,
    this ratio would move by a factor, not a percent. Returns the ratio."""
    ok = segments[(segments["length_m"] > 1.0) & segments["segmentlength_ft"].notna()]
    if ok.empty:
        raise StreetFrameError("no segment carries both a geometry and a segmentlength")
    ratio = float((ok["length_m"] / (ok["segmentlength_ft"] * 0.3048)).median())
    if not (1.0 - tol) <= ratio <= (1.0 + tol):
        raise StreetFrameError(
            f"computed length / segmentlength is {ratio:.4f}, outside 1.0 +/- {tol}. "
            f"That is a projection or unit error, not a data drift: check "
            f"always_xy=True and the US-survey-foot constant before trusting any "
            f"length in this frame.")
    return ratio


def street_midpoints(segments: pd.DataFrame,
                     spacing_m: float = DEFAULT_SPACING_M) -> pd.DataFrame:
    """The sampling frame: one row per point, PER PART.

    Columns: point_id, segment_id, lon, lat, borough, frontage_m,
    segment_len_m, street_name, width_ft, k_index, k_total.

    `point_id` is `seg:<physicalid>:<k>` with `k` running over the segment's
    points in part order. Uniqueness is ASSERTED, not assumed: `physicalid` is
    near-unique (3 duplicates in MN+BK) and a collision would silently
    overwrite a point rather than fail.
    """
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")
    recs = []
    for seg in segments.itertuples():
        pts = []
        for part, cum in zip(seg.parts, seg.cums):
            pts.extend(split_points(part, cum, spacing_m))
        for k, (lon, lat, frontage) in enumerate(pts):
            recs.append({
                "point_id": f"seg:{seg.segment_id}:{k}",
                "segment_id": seg.segment_id,
                "lon": lon,
                "lat": lat,
                "borough": seg.borough,
                "frontage_m": frontage,
                "segment_len_m": seg.length_m,
                "street_name": seg.street_name,
                "width_ft": seg.width_ft,
                "k_index": k,
                "k_total": len(pts),
            })
    df = pd.DataFrame(recs)
    if df.empty:
        raise StreetFrameError(
            "the keep rule produced no street points. An empty street frame is "
            "indistinguishable from a borough with no streets; refusing to build it.")
    dupes = df["point_id"][df["point_id"].duplicated()].unique()
    if len(dupes):
        raise StreetFrameError(
            f"{len(dupes)} duplicate point_id(s), e.g. {sorted(dupes)[:3]}. CSCL's "
            f"physicalid is NEAR-unique, not unique -- two kept segments share one, "
            f"and one point would silently overwrite the other.")
    return df


def check_segment_count(segments: pd.DataFrame, expected: int = EXPECTED_KEPT_MNBK,
                        tolerance: float = COUNT_TOLERANCE) -> None:
    """Refuse a build whose kept-segment count has moved more than `tolerance`
    from the verified baseline. CSCL refreshes weekly, so drift is expected and
    a factor is not."""
    n = len(segments)
    lo, hi = expected * (1 - tolerance), expected * (1 + tolerance)
    if not lo <= n <= hi:
        raise StreetFrameError(
            f"keep rule kept {n:,} segments; expected {expected:,} +/- "
            f"{tolerance:.0%} ({lo:,.0f}-{hi:,.0f}). CSCL refreshes weekly so small "
            f"drift is normal, but this is a changed schema, a changed status/nonped "
            f"vocabulary or a changed scope -- re-run the keep ladder and look at it "
            f"before rebuilding the frame.")


def frame_vintage(rows: list[dict] | None = None,
                  asof: dt.date | None = None) -> dt.date:
    """The extract date stamped onto every street row (`frame_vintage`). The
    dataset carries no per-row extract timestamp, so this is the date the raw
    cache was written -- which is what "how old is this frame" means."""
    return asof or dt.date.today()


def build_frame(boroughs: tuple[str, ...] = SCREEN_BOROUGHS,
                spacing_m: float = DEFAULT_SPACING_M, *,
                use_cache: bool = True, asof: dt.date | None = None,
                log=print) -> tuple[pd.DataFrame, dict]:
    """fetch -> keep rule -> length check -> points. (points frame, report).

    Pure read: touches the portal and `data/raw/`, never the warehouse.
    """
    rows = fetch_segments(boroughs, use_cache=use_cache, asof=asof)
    ladder = keep_ladder(rows)
    for label, n, km in ladder:
        log(f"  {label:<40} {n:>7,} segments  {km:>9,.1f} km")
    segments = load_street_segments(rows)
    # The count baseline was measured over MN+BK; a narrower scope has its own
    # count and asserting the MN+BK number against it would be nonsense.
    if {b.upper() for b in boroughs} == set(SCREEN_BOROUGHS):
        check_segment_count(segments)
    ratio = check_length_sanity(segments)
    points = street_midpoints(segments, spacing_m)
    report = {
        "source_id": SOURCE_ID,
        "dataset": DATASET,
        "boroughs": [b.upper() for b in boroughs],
        "spacing_m": float(spacing_m),
        "rows_fetched": len(rows),
        "segments_kept": len(segments),
        "km_kept": float(segments["length_m"].sum() / 1000.0),
        "multipart_segments": int((segments["n_parts"] > 1).sum()),
        "points": len(points),
        "points_by_borough": points["borough"].value_counts().to_dict(),
        "length_check_ratio": ratio,
        "ladder": ladder,
        "frame_vintage": frame_vintage(rows, asof).isoformat(),
    }
    return points, report


#: Where `loci street-frame` parks the built frame, so `loci address-gaps` can
#: union it in without re-fetching. Beside every other interim artefact.
POINTS_PARQUET = (pathlib.Path(__file__).resolve().parents[5]
                  / "data" / "interim" / "street_points.parquet")
