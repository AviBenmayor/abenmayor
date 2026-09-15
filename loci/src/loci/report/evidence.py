"""THE READ SIDE (D100, AC-16, AC-17) -- one `EvidencePack` assembled from the
warehouse alone, no paid call, no writes. `enrich.py` adds the paid layer on
top of what this module returns; `render.py` never reads the warehouse
directly, only this pack plus an `Enrichment`.

`resolve_address` is a thin wrapper around `loci.geo.geosearch.resolve` (D99,
built by the closure-evidence/geosearch session) -- imported LOCALLY, inside
the function, not at module load time, so `loci.report.evidence` stays
importable even on a checkout where `loci/geo/geosearch.py` has not landed
yet (this session's own concurrency note). `assemble()` has no such
dependency: it takes an `address_id` that already resolved, so every fixture
test below can build a pack without touching GeoSearch or the network at all.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from loci.model.recommend import area_facts, build_cards, load_rules
from loci.score.dedup import haversine_m
from loci.score.supply import canonical_poi_sql

#: Half the seed's "catchment" default (500 m) is generous for a single-block
#: memo but matches D100's own facts section ("assemble(con, address_id, *,
#: catchment_m=500)"); the ±100 m bbox `area_facts` grades against is
#: deliberately much tighter (see `_bbox_around`).
DEFAULT_CATCHMENT_M = 500.0

#: `area_facts` grades a BOX, not a point -- ±100 m around the address, per
#: the design's own facts section ("area_facts is bbox-based -> +-100 m bbox
#: around the address (lot frame)"). A wider box would blur one address's
#: card into its block's.
GRADE_BBOX_HALF_WIDTH_M = 100.0

#: One degree of latitude is ~111,320 m everywhere; longitude shrinks with
#: cos(lat). NYC sits at ~40.7 deg N, where cos(40.7 deg) ~ 0.758 -- close
#: enough for a ±100 m grading box (not a distance measurement, which stays
#: on `haversine_m` throughout this module).
_M_PER_DEG_LAT = 111_320.0


@dataclass
class POIRow:
    """One business in the catchment, as the supply section prints it."""
    poi_id: str
    name: str | None
    category: str
    dist_m: float
    status: str                  # 'open' | 'closed' | 'unknown'
    basis: str | None
    colocation: str | None       # colocation_resolution, or None if solo
    source_id: str | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass
class EvidencePack:
    address: dict
    scores: dict                 # raw `area_facts` output (facts dict)
    grades: list                 # `build_cards` output, thinnest-ratio first
    forecast: dict | None        # analysis.forecast_latest row for the lead category
    supply: list                 # list[POIRow], nearest first
    demand: dict
    legality: dict
    context: dict                 # transit/DOT/pipeline context, best-effort
    provenance: dict = field(default_factory=dict)

    @property
    def lead_category(self) -> str | None:
        return self.grades[0]["category"] if self.grades else None

    def hash(self) -> str:
        """A stable digest of everything that could change what the report
        SAYS -- the cache key ingredient (`cache.key`) alongside `address_id`.
        Includes the supply list's (poi_id, status, basis) so a closure check
        landing between two runs busts the cache even though nothing on
        `analysis.address` itself changed. Deliberately excludes `context`/
        `provenance` (timestamps, run_at stamps) that vary run to run without
        the SUBSTANCE changing -- a hash that never stabilizes defeats the
        cache."""
        payload = {
            "address_id": self.address.get("address_id"),
            "legality": self.legality.get("legality"),
            "legality_basis": self.legality.get("legality_basis"),
            "lead_category": self.lead_category,
            "grades": [(g["category"], g["overall_grade"], g["verdict"])
                       for g in self.grades],
            "forecast": None if not self.forecast else
                (self.forecast.get("p_opening"), self.forecast.get("issued_month"),
                 self.forecast.get("model_version")),
            "supply": sorted((p.poi_id, p.status, p.basis) for p in self.supply),
            "demand": self.demand,
        }
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def resolve_address(con, query: str, *, session=None) -> str:
    """`query` (a free-text address, or an `address_id` already) -> a Loci
    `address_id`. Raises `loci.geo.geosearch.NotInCoverage` for anything
    outside the universe -- callers (`run.generate`) let that propagate
    rather than rendering a degraded report (seed's Search rule)."""
    from loci.geo.geosearch import resolve as geo_resolve

    return geo_resolve(con, query, session=session)


def _bbox_around(lat: float, lon: float, half_m: float) -> tuple[float, float, float, float]:
    import math

    dlat = half_m / _M_PER_DEG_LAT
    dlon = half_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def _address_row(con, address_id: str) -> dict:
    cols = con.execute("DESCRIBE analysis.address").fetchdf()["column_name"].tolist()
    row = con.execute(
        f"SELECT {', '.join(cols)} FROM analysis.address WHERE address_id = ?",
        [address_id]).fetchone()
    if row is None:
        raise ValueError(f"address_id {address_id!r} not found in analysis.address")
    return dict(zip(cols, row))


def _legality_row(con, address_id: str) -> dict:
    row = con.execute(
        "SELECT legality, legality_basis, has_open_commercial_poi "
        "FROM analysis.address_legality WHERE address_id = ?", [address_id]).fetchone()
    base = {"legality": None, "legality_basis": None, "has_open_commercial_poi": None}
    if row:
        base.update({"legality": row[0], "legality_basis": row[1],
                     "has_open_commercial_poi": row[2]})
    for col in ("zonedist1", "overlay1", "overlay2", "landuse", "ownertype",
               "histdist", "landmark"):
        base[col] = None
    plu = con.execute(
        "SELECT zonedist1, overlay1, overlay2, landuse, ownertype, histdist, landmark "
        "FROM analysis.address WHERE address_id = ?", [address_id]).fetchone()
    if plu:
        base.update(dict(zip(
            ("zonedist1", "overlay1", "overlay2", "landuse", "ownertype",
             "histdist", "landmark"), plu)))
    return base


def _forecast_row(con, address_id: str, category: str | None) -> dict | None:
    if category is None:
        return None
    try:
        cols = con.execute("DESCRIBE analysis.forecast_latest").fetchdf()["column_name"].tolist()
    except Exception:      # noqa: BLE001 -- view absent on a pre-D92 warehouse
        return None
    row = con.execute(
        f"SELECT {', '.join(cols)} FROM analysis.forecast_latest "
        "WHERE address_id = ? AND category = ?", [address_id, category]).fetchone()
    return dict(zip(cols, row)) if row else None


def _supply_rows(con, lat: float, lon: float, catchment_m: float) -> list[POIRow]:
    """Every POI in the supply set within `catchment_m`, open/closed/unknown
    alike -- `gate_closed=False` deliberately (the supply SECTION must show a
    closed storefront with its basis, not hide it the way the SCREEN's own
    consumers do). `Never bypass` (design facts section) means "read
    `analysis.poi_supply_status` through this function", not "only ever ask
    for the gated set"."""
    cols = ("s.poi_id, s.name, s.category, s.source_id, ST_X(s.geom) AS lon, "
            "ST_Y(s.geom) AS lat, s.poi_status, s.poi_status_basis, "
            "s.colocation_n, s.colocation_resolution")
    sql = canonical_poi_sql(cols=cols, gate_closed=False)
    df = con.execute(sql).fetchdf()
    out: list[POIRow] = []
    for r in df.itertuples(index=False):
        dist_m = haversine_m(lat, lon, r.lat, r.lon)
        if dist_m > catchment_m:
            continue
        # colocation_n == 1 is a solo POI; the view still labels its
        # (vacuous) group 'both_open', which is only meaningful once a
        # SECOND POI shares the coordinate -- print nothing for the solo
        # case rather than a co-location note about a group of one.
        colo = r.colocation_resolution if (r.colocation_n or 0) >= 2 else None
        out.append(POIRow(
            poi_id=r.poi_id, name=r.name, category=r.category, dist_m=round(dist_m, 1),
            status=r.poi_status, basis=r.poi_status_basis, colocation=colo,
            source_id=r.source_id, lat=r.lat, lon=r.lon))
    out.sort(key=lambda p: p.dist_m)
    return out


def refresh_supply(pack: EvidencePack, con) -> EvidencePack:
    """Re-read `pack.supply` from `analysis.poi_supply_status` and replace it
    IN PLACE. Called by `enrich.py` after it writes one or more closure
    evidence rows -- `poi_supply_status` is a VIEW, so a freshly-inserted row
    is visible to the very next query; this just re-runs the same read
    `assemble()` did so `render.py` sees the updated open/closed/unknown
    without the caller reassembling grades/demand/legality too."""
    pack.supply = _supply_rows(con, pack.address["lat"], pack.address["lon"],
                               pack.context.get("catchment_m", DEFAULT_CATCHMENT_M))
    return pack


def unknown_pois(pack: EvidencePack) -> list[POIRow]:
    """The subset `enrich.py` may spend budget checking, nearest first (the
    same ordering `design-closure-evidence.md`'s `verify.select_unknown`
    uses: `colocation_n DESC, poi_id` for a citywide sweep; a single report's
    catchment is small enough that nearest-first is the more useful reading
    for a human deciding whether the cap was well spent)."""
    return [p for p in pack.supply if p.status == "unknown"]


def _demand_facts(con, address_id: str, category: str | None, row: dict) -> dict:
    out = {
        "homes_400m": row.get("homes_400m"),
        "homes_800m": row.get("homes_800m"),
        "transit_entries_400m": row.get("transit_entries_400m"),
        "jobs_400m": row.get("jobs_400m"),
        "vacant_storefronts_400m": row.get("vacant_storefronts_400m"),
        "units_permitted_400m": row.get("units_permitted_400m"),
        "units_completed_24mo_400m": row.get("units_completed_24mo_400m"),
        "units_completed_60mo_400m": row.get("units_completed_60mo_400m"),
    }
    demo = con.execute(
        "SELECT median_hh_income, median_hh_income_moe, renter_share, age_18_34_share "
        "FROM analysis.address_demographics WHERE address_id = ? "
        "ORDER BY acs_year DESC LIMIT 1", [address_id]).fetchone()
    out.update({
        "median_hh_income": demo[0] if demo else None,
        "median_hh_income_moe": demo[1] if demo else None,
        "renter_share": demo[2] if demo else None,
        "age_18_34_share": demo[3] if demo else None,
    })
    if category is not None:
        cat = con.execute(
            "SELECT revenue_p25, revenue_p50, revenue_p75, rent_ceiling, "
            "supply_ratio_vs_base, demand_caveat_text "
            "FROM analysis.address_category WHERE address_id = ? AND category = ?",
            [address_id, category]).fetchone()
        if cat:
            out.update({
                "revenue_p25": cat[0], "revenue_p50": cat[1], "revenue_p75": cat[2],
                "rent_ceiling": cat[3], "supply_ratio_vs_base": cat[4],
                "demand_caveat_text": cat[5],
            })
    return out


def assemble(con, address_id: str, *, catchment_m: float = DEFAULT_CATCHMENT_M) -> EvidencePack:
    """Every warehouse fact the four sections need, for ONE address. Pure
    read: no INSERT/UPDATE anywhere in this function, no paid call."""
    address = _address_row(con, address_id)
    legality = _legality_row(con, address_id)
    bbox = _bbox_around(address["lat"], address["lon"], GRADE_BBOX_HALF_WIDTH_M)
    rules = load_rules()
    scores = area_facts(con, address_id, bbox=bbox, boroughs=(address["borough"],))
    grades = build_cards(scores, rules)
    lead_category = grades[0]["category"] if grades else None
    forecast = _forecast_row(con, address_id, lead_category)
    supply = _supply_rows(con, address["lat"], address["lon"], catchment_m)
    demand = _demand_facts(con, address_id, lead_category, address)
    context = {
        "neighborhood": address.get("neighborhood"),
        "nta_code": address.get("nta_code"),
        "borough": address.get("borough"),
        "catchment_m": catchment_m,
    }
    provenance = {"asof": scores.get("asof"), "supply_hash": scores.get("live_hash")}
    return EvidencePack(address=address, scores=scores, grades=grades, forecast=forecast,
                        supply=supply, demand=demand, legality=legality, context=context,
                        provenance=provenance)
