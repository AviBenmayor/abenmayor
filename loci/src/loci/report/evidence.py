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

import datetime as dt
import hashlib
import json
import pathlib
import re
from dataclasses import dataclass, field

from loci.model.recommend import area_facts, build_cards, load_rules
from loci.score.dedup import haversine_m
from loci.score.supply import canonical_poi_sql

#: NY ABC Law's "500-foot rule" (SLA sections 64-a/110-b): a new on-premises
#: liquor licence application draws a mandatory public-interest hearing when
#: 3+ existing on-premises licences already sit within 500 feet. 500 ft =
#: 152.4 m -- investor review item 6, checked only for a bar/restaurant lead
#: category (the rule is meaningless context for any other category).
SLA_500FT_RADIUS_M = 152.4
SLA_500FT_TRIGGER_CATEGORIES = frozenset({"bar", "restaurant"})
SLA_500FT_LICENSE_COUNT_TRIGGER = 3

#: No flood-zone / Superfund-boundary source is loaded in this warehouse
#: (investor review item 6: render this rather than inventing a number).
#: Kept as a named constant, not a magic string, so a future source landing
#: is a one-place fix (see the session report for what was checked).
FLOOD_ENVIRONMENTAL_NOT_LOADED = "flood/environmental overlays: not loaded"

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

#: The SQL pre-filter box is widened by 1% before it is used to scope a read
#: that Python then refines with `haversine_m`. IT MUST BE A SUPERSET, always:
#: `_bbox_around` divides by 111,320 m/deg while `haversine_m` works on
#: R = 6,371,000 m (111,194.9 m/deg), so an un-padded box is ~0.11% TIGHT --
#: about 0.6 m at a 500 m catchment, which is exactly wide enough to drop a
#: storefront at 499.8 m and manufacture a supply gap that is not there. The
#: padding costs a handful of extra rows the Python test then rejects; the
#: alternative costs a wrong number with no symptom.
_BBOX_SUPERSET_PAD = 1.01

#: The MN+BK screen (§4f of the 2026-09-16 audit). NOTHING in the schema
#: enforces it -- `analysis.storefront` is 39% non-MN/BK, `storefront_pipeline`
#: 47%, `brand_location` 33% -- so every read of a five-borough table in this
#: module carries it explicitly.
SCREEN_BOROUGHS: tuple[str, ...] = ("MN", "BK")

#: `chains.brand_location` and `analysis.poi_presence` spell boroughs out in
#: full while the address family uses two-letter codes, with no FK and no
#: agreed vocabulary (audit §4f). One map, one place.
BOROUGH_FULL_NAMES = {"MN": "Manhattan", "BK": "Brooklyn", "QN": "Queens",
                      "BX": "Bronx", "SI": "Staten Island"}


class CategoryNotAvailable(ValueError):
    """`--category <cat>` named a category that is not one of the 15 Loci
    slugs, or that this address has no card for."""


class DemotedCategory(ValueError):
    """`--category <cat>` named a category demoted from headline use (owner
    ruling 2026-09-14 on the D30 precedent: clinic, tailor_repair,
    hair_barber -- 34-45% of their gaps are holes in the DATA, not in the
    market). It may still be forced with `--allow-demoted`, which is the
    point of the flag: the analyst has to say out loud that the lead category
    of this memo is one the project does not let lead a recommendation."""


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
class VacantStorefrontRow:
    """One DOF Storefront Registry premises currently reading vacant (investor
    review item 4: NAME the vacant space, don't just count it)."""
    premises_id: str
    address: str | None
    dist_m: float
    floor_area_sqft: float | None   # PLUTO retailarea on the storefront's own
                                     # BBL, None when no PLUTO match/record
    last_use: str | None            # most recent non-null primary_business_activity
    vacant_since: int | None        # earliest reporting_year of the CURRENT
                                     # contiguous vacant streak
    bbl: str | None = None


@dataclass
class PipelineRow:
    """One SLA-pending or DOB fit-out filing in the catchment
    (`analysis.storefront_pipeline`, D80) -- investor review item 4."""
    pipeline_id: str
    business_name: str | None
    category: str | None            # loci_category, may be None (uncategorised)
    kind: str                       # 'SLA pending' | 'DOB fit-out'
    stage: str | None               # raw entry_stage
    entry_date: object               # date | None
    dist_m: float


@dataclass
class ChainWatchRow:
    """One flagged, expanding chain location within the watch radius
    (`chains.brand_location`/`brand_latest`, D77) -- investor review item 4."""
    brand_key: str
    display_name: str
    category: str | None
    dist_m: float
    locations_new_12m: int | None
    locations_total: int | None


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
    vacant_storefronts: list = field(default_factory=list)  # list[VacantStorefrontRow]
    pipeline: list = field(default_factory=list)             # list[PipelineRow]
    chains_watch: list = field(default_factory=list)         # list[ChainWatchRow]

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
            "vacant_storefronts": sorted(
                (v.premises_id, v.vacant_since) for v in self.vacant_storefronts),
            "pipeline": sorted((p.pipeline_id, p.stage) for p in self.pipeline),
            "chains_watch": sorted(c.brand_key for c in self.chains_watch),
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


def _bbox_sql(lat: float, lon: float, radius_m: float, *,
              lon_expr: str, lat_expr: str) -> str:
    """A SQL fragment bounding `lon_expr`/`lat_expr` to a box that CONTAINS
    every point within `radius_m` of (lat, lon).

    Numeric literals, not placeholders: the fragment is composed into
    `canonical_poi_sql` and into queries whose other arguments are already
    parameterised, and the four values are floats this module computed from an
    address row -- never text off an input. `repr()` on a float round-trips
    exactly in Python, so the literal is the same number the Python filter
    then uses.

    Superset by `_BBOX_SUPERSET_PAD`; the exact circle is still cut in Python
    with `haversine_m`, so this only ever decides WHICH ROWS ARE READ, never
    which rows are counted."""
    minlat, minlon, maxlat, maxlon = _bbox_around(lat, lon,
                                                  radius_m * _BBOX_SUPERSET_PAD)
    return (f"{lat_expr} BETWEEN {minlat!r} AND {maxlat!r} "
            f"AND {lon_expr} BETWEEN {minlon!r} AND {maxlon!r}")


def _borough_sql(col: str, boroughs=SCREEN_BOROUGHS, *, keep_null: bool = True) -> str:
    """The MN+BK screen as a SQL fragment, in BOTH borough vocabularies.

    The warehouse spells boroughs two ways with no FK and no agreed
    vocabulary (audit §4f): `'MN'`/`'BK'` in the address family,
    `analysis.storefront`, `storefront_pipeline` and `staging.alcohol_licences`
    -- `'Manhattan'`/`'Brooklyn'` in `chains.brand_location` and
    `analysis.poi_presence`. A screen written in one vocabulary silently
    deletes every row written in the other, which is a far worse failure than
    the leak it was added to close, so this matches both spellings. Pick a
    vocabulary upstream and this collapses to one list.

    `keep_null` is TRUE by default and that is a deliberate, stated choice: a
    NULL borough is UNKNOWN, not "some other borough". `storefront_pipeline`
    has 17,532 NULL-borough rows and `brand_location` 22,434; dropping them
    would delete real filings and real chain locations inside the catchment on
    the strength of a missing label. They survive the borough screen and are
    then decided by the spatial bound, which is the measurement that actually
    answers the question."""
    names = list(boroughs) + [BOROUGH_FULL_NAMES[b] for b in boroughs]
    inlist = ", ".join(f"'{n}'" for n in names)
    clause = f"{col} IN ({inlist})"
    return f"({col} IS NULL OR {clause})" if keep_null else f"({clause})"


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
    plu_cols = ("zonedist1", "overlay1", "overlay2", "landuse", "ownertype",
               "histdist", "landmark", "spdist1")
    for col in plu_cols:
        base[col] = None
    plu = con.execute(
        f"SELECT {', '.join(plu_cols)} FROM analysis.address WHERE address_id = ?",
        [address_id]).fetchone()
    if plu:
        base.update(dict(zip(plu_cols, plu)))
    return base


def _sla_500ft_context(con, category: str | None, lat: float, lon: float) -> dict | None:
    """The SLA 500-foot rule (investor review item 6): applies only when the
    lead category is `bar` or `restaurant`. Counts ACTIVE, `on_premises`
    licences (`staging.alcohol_licences`) within `SLA_500FT_RADIUS_M`
    straight-line metres -- the same table and `active`/`classification`
    fields the hand-written comparator memos read. Returns `None` when the
    category does not trigger the rule (render prints nothing in that case,
    rather than a line that never applies to the address's own lead
    category)."""
    if category not in SLA_500FT_TRIGGER_CATEGORIES:
        return None
    df = con.execute(f"""
        SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat
        FROM staging.alcohol_licences
        WHERE active AND classification = 'on_premises' AND geom IS NOT NULL
          AND {_borough_sql("borough")}
          AND {_bbox_sql(lat, lon, SLA_500FT_RADIUS_M,
                         lon_expr="ST_X(geom)", lat_expr="ST_Y(geom)")}
    """).fetchdf()
    n = 0
    for r in df.itertuples(index=False):
        if haversine_m(lat, lon, r.lat, r.lon) <= SLA_500FT_RADIUS_M:
            n += 1
    return {
        "n_on_premises_licenses": n,
        "triggers_hearing": n >= SLA_500FT_LICENSE_COUNT_TRIGGER,
    }


def _same_bbl_consistency(bbl: str | None, lead_category: str | None, *,
                          recommendations_dir: "pathlib.Path | str | None" = None,
                          exclude_path: "pathlib.Path | str | None" = None,
                          now: dt.datetime | None = None,
                          within_days: int = 7) -> list[str]:
    """Best-effort same-BBL consistency check (investor review item 6): scan
    the OTHER files in `docs/recommendations/` -- this project's own
    generated memos and hand-written companion analyses alike, since both
    live in the same directory -- modified within `within_days` days for a
    mention of THIS address's BBL, and flag a DIFFERENT `lead_category` named
    for it there. A text scan, not a database join: the hand-written
    comparator memos (e.g. `graham-ave-376-2026-09-13.md`) are prose, not
    structured data, so this can only ever be a heuristic cross-check -- it
    flags disagreement, it does not resolve it. Returns `[]` (never raises)
    when there is no BBL, no directory, or nothing recent mentions it."""
    if not bbl:
        return []
    if recommendations_dir is None:
        from loci.report.render import OUT_DIR as recommendations_dir
    directory = pathlib.Path(recommendations_dir)
    if not directory.exists():
        return []
    from loci.categories import CATEGORIES

    now = now or dt.datetime.now()
    cutoff = now - dt.timedelta(days=within_days)
    exclude = pathlib.Path(exclude_path).resolve() if exclude_path else None
    cat_res = {c: re.compile(rf"\b{re.escape(c)}\b", re.I) for c in CATEGORIES}

    out: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if exclude is not None and path.resolve() == exclude:
            continue
        try:
            if dt.datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                continue
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if bbl not in text:
            continue
        # A markdown table row often reads "`lead_category` | 0.526 /
        # **tailor_repair**" -- the category name shares the LINE with the
        # "lead_category" mention, not a fixed offset from it, so this scans
        # whole lines rather than a single regex with a bounded gap.
        found = {c for line in text.splitlines() if "lead_category" in line.lower()
                for c, rx in cat_res.items() if rx.search(line)}
        conflicting = found - ({lead_category} if lead_category else set())
        if conflicting:
            out.append(f"{path.name} names lead_category {sorted(conflicting)} for BBL "
                       f"{bbl}; this report reads {lead_category!r}")
    return out


#: HOW `analysis.forecast_outcome` IS TIED BACK TO `analysis.forecast`.
#:
#: TODAY it is the surrogate `forecast_id`, because the reshape is STAGED and
#: not applied: `sql/028`'s edit and the `migrate-warehouse` rebuild land
#: together in one Phase B window, and until they do the live warehouse still
#: has `forecast_id`. Flip this to "natural" IN THAT SAME WINDOW and nothing
#: else in this module changes -- it is ONE constant so Phase B is a one-line
#: edit rather than a hunt through f-strings.
#:
#: `model_version` is load-bearing in the natural join: without it a scored
#: vintage fans out across all five same-month 2026-09 re-issues.
#:
#: Why it matters here at all: `analysis.forecast_latest` LEFT JOINs a
#: window-function CTE over the full `forecast x forecast_outcome` join, and
#: DuckDB will not push `address_id = ?` through that LEFT JOIN into the
#: right-hand side -- so reading the view for ONE address planned an unbounded
#: pass over 8,455,260 outcome rows. The query below carries the restriction
#: into BOTH arms itself.
FORECAST_OUTCOME_KEY = "natural"              # flipped in the Phase B window, 2026-09-16

#: The four columns the natural key is built on, in sql/028's order.
#: `scored_month` is the fifth and is the within-address ordering column, not
#: part of the address restriction.
FORECAST_NATURAL_KEY = ("issued_month", "model_version", "address_id", "category")


def _forecast_outcome_join() -> str:
    """The ON clause joining `o` (forecast_outcome) to `f` (forecast)."""
    if FORECAST_OUTCOME_KEY == "natural":
        return " AND ".join(f"o.{c} = f.{c}" for c in FORECAST_NATURAL_KEY)
    return "o.forecast_id = f.forecast_id"


#: `analysis.forecast_latest` rebuilt with the address restriction pushed into
#: every scan it makes, instead of read as a view and filtered on the way out.
#: Column-for-column and row-for-row the same answer for one (address_id,
#: category) -- `tests/test_report_scan.py` pins that against the view itself
#: on a fixture. The only difference is the plan.
_FORECAST_SCOPED_SQL = """
WITH fc AS (
    SELECT f.*
    FROM analysis.forecast f
    WHERE f.address_id = ? AND f.category = ?
    QUALIFY row_number() OVER (
        PARTITION BY f.address_id, f.category
        ORDER BY f.frozen_at DESC, f.model_version DESC) = 1
),
scored AS (
    SELECT f.address_id, f.category, f.issued_month AS scored_vintage_month,
           f.model_version AS scored_model_version,
           o.scored_month, o.horizon_elapsed, o.realized_openings, o.realized_flag,
           f.p_opening AS p_at_that_vintage
    FROM analysis.forecast f
    JOIN analysis.forecast_outcome o ON {on_clause}
    WHERE f.address_id = ? AND f.category = ?
    QUALIFY row_number() OVER (
        PARTITION BY f.address_id, f.category
        ORDER BY o.scored_month DESC, o.horizon_elapsed DESC) = 1
)
SELECT fc.address_id, fc.category, fc.frame, fc.borough, fc.nta_code,
       fc.issued_month, fc.model_version, fc.horizon_months, fc.p_opening,
       fc.expected_openings, fc.support, fc.features_hash,
       s.scored_vintage_month, s.scored_model_version, s.scored_month,
       s.horizon_elapsed, s.realized_openings, s.realized_flag,
       s.p_at_that_vintage,
       (date_diff('month',
                  strptime(fc.issued_month || '-01', '%Y-%m-%d')::DATE,
                  current_date) >= fc.horizon_months) AS is_scoreable_now
FROM fc LEFT JOIN scored s
  ON s.address_id = fc.address_id AND s.category = fc.category
"""


def _forecast_row(con, address_id: str, category: str | None) -> dict | None:
    """The newest issued forecast and newest scored outcome for one address x
    category.

    Reads the scoped query above rather than `analysis.forecast_latest`, so
    the plan carries the address restriction into the `forecast_outcome` scan
    instead of materialising the whole view and filtering afterwards. Falls
    back to the view if the scoped query cannot bind (a pre-D92 warehouse, or
    one mid-migration where `forecast_id` has gone and this constant has not
    been flipped) -- a slow correct answer beats a fast missing one.
    """
    if category is None:
        return None
    sql = _FORECAST_SCOPED_SQL.format(on_clause=_forecast_outcome_join())
    try:
        res = con.execute(sql, [address_id, category, address_id, category])
        cols = [d[0] for d in res.description]
        row = res.fetchone()
        return dict(zip(cols, row)) if row else None
    except Exception:      # noqa: BLE001 -- duckdb raises several types
        pass
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
    # SCOPED (2026-09-16): the unbounded read pulled all 136,563 rows of
    # `analysis.poi_supply_status` into pandas so a Python loop could throw
    # away 99.8% of them on `dist_m > catchment_m`. The box is a strict
    # superset of that circle (`_bbox_sql`), so the rows kept are identical
    # and the haversine test below is still the one that decides.
    sql = canonical_poi_sql(
        cols=cols, gate_closed=False,
        where=_bbox_sql(lat, lon, catchment_m,
                        lon_expr="ST_X(s.geom)", lat_expr="ST_Y(s.geom)"))
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


#: `analysis.storefront_pipeline.entry_stage` values read as "SLA pending"
#: (an on-premises liquor application, not yet issued) vs "DOB fit-out" (a
#: construction/sign filing on the storefront itself) -- investor review item
#: 4: name these filings, don't fold them into a count. `license_application`
#: is deliberately excluded from SLA_PENDING_STAGES: `storefront_pipeline`
#: mixes SLA and DCA/DOHMH license applications under one generic stage name
#: in some feeds, and only `liquor_application` is unambiguously SLA.
SLA_PENDING_STAGES: tuple[str, ...] = ("liquor_application",)
DOB_FITOUT_STAGES: tuple[str, ...] = ("fitout_filing", "permit_issued", "sign_permit")

#: Straight-line radius for the chains watchlist (investor review item 4:
#: "chains-watchlist entries within 800 m", stated as a fixed radius, not the
#: report's own `catchment_m`).
CHAINS_WATCH_RADIUS_M = 800.0


def _present(v) -> bool:
    """`v` is a real, non-null value -- true for anything but `None` and
    pandas' float `NaN` (DuckDB's `fetchdf()` renders some NULL VARCHARs as
    `NaN`, not `None`, depending on the column's inferred dtype; `NaN != NaN`
    is the standard float trick to catch that without importing pandas here
    just for `pd.notna`)."""
    return v is not None and v == v


def _isnull(v) -> bool:
    """True for None, NaN and pandas NA (fetchdf yields all three)."""
    if v is None:
        return True
    try:
        return bool(v != v)          # NaN is the only value unequal to itself
    except (TypeError, ValueError):  # pd.NA: comparison is ambiguous
        return True


def _flag(v) -> bool:
    """A nullable-boolean flag read as a plain bool; NULL/NA/NaN is False."""
    if _isnull(v):
        return False
    try:
        return bool(v)
    except (TypeError, ValueError):
        return False


def _vacant_storefront_rows(con, lat: float, lon: float,
                            catchment_m: float) -> list[VacantStorefrontRow]:
    """Every DOF Storefront Registry premises within `catchment_m` that reads
    vacant as of its OWN latest filing -- named (address, last use, vacant
    since), not counted. `vacant_since` is the earliest `reporting_year` of
    the contiguous run of vacant filings ending at that latest filing (a gap
    year breaks the streak); `last_use` is the most recent non-null
    `primary_business_activity` across ALL filings for the premises (often
    from a filing before the vacancy began -- that's the point: it names what
    used to be there). Floor area is PLUTO `retailarea` on the storefront's
    own BBL when that address has been through `address_legality`'s build
    step; `None` (rendered "not on file") otherwise -- this module never
    invents a square footage."""
    # ONE PASS, and the shape of it is load-bearing. The vacancy streak and
    # `last_use` below are computed over a premises' WHOLE filing history, so
    # a spatially-filtered row set would truncate both (a premises whose
    # earlier vacant years are exactly what `vacant_since` counts). The window
    # marks every premises that has AT LEAST ONE in-scope filing and then
    # keeps all of that premises' filings -- same answer as "name the premises
    # in the box, then re-read them", at one scan instead of two (the second
    # could not prune on `premises_id` and re-read all 412,967 rows).
    #
    # MN+BK: `analysis.storefront` carries all five boroughs (155,450 MN /
    # 98,069 BK / 89,251 QN / 55,286 BX / 16,828 SI) with nothing in the
    # schema enforcing the screen -- audit §4f, finding 5. The screen is
    # applied to the WHOLE subquery, not only to the in-scope test, so a
    # premises cannot be pulled in by an out-of-borough filing.
    scope = (f"{_borough_sql('borough')} AND "
             f"{_bbox_sql(lat, lon, catchment_m, lon_expr='ST_X(geom)', lat_expr='ST_Y(geom)')}")
    df = con.execute(f"""
        SELECT premises_id, storefront_id, filing_due_date,
               address, bbl, lon, lat, reporting_year, vacant_1231, vacant_0630,
               primary_business_activity
        FROM (
            SELECT premises_id, storefront_id, filing_due_date, address, bbl,
                   ST_X(geom) AS lon, ST_Y(geom) AS lat,
                   reporting_year, vacant_1231, vacant_0630,
                   -- `last_use` walks filings NEWEST-first, so before the
                   -- recode was undone it read the 2024/2025 vocabulary
                   -- preferentially.
                   activity_canonical AS primary_business_activity,
                   max(CASE WHEN {scope} THEN 1 ELSE 0 END)
                       OVER (PARTITION BY premises_id) AS _in_scope
            FROM analysis.storefront
            WHERE geom IS NOT NULL AND premises_id IS NOT NULL
              AND {_borough_sql('borough')}
        )
        WHERE _in_scope = 1
    """).fetchdf()
    if df.empty:
        return []

    groups: dict[str, list] = {}
    for r in df.itertuples(index=False):
        groups.setdefault(r.premises_id, []).append(r)

    out: list[VacantStorefrontRow] = []
    for premises_id, rows in groups.items():
        # DETERMINISM, and it is not cosmetic. `analysis.storefront`'s real
        # grain is (storefront_id, filing_due_date), NOT (storefront_id,
        # reporting_year): premises 3028930042| carries FIVE 2024 filings,
        # two due 2025-02-15 and three due 2025-06-03, whose `vacant_1231`
        # reads True, True, True, False, False. Sorting on reporting_year
        # alone left "is this storefront vacant?" decided by whichever of the
        # five DuckDB's scan happened to emit last -- a stable-sort tie -- so
        # merely changing the WHERE clause of the query above flipped this
        # premises in and out of the memo's vacant list (26 rows vs 27 at
        # address 3027550006). The full grain plus `storefront_id` makes the
        # pick reproducible.
        #
        # WHAT THIS DOES NOT FIX, and the owner has to rule on it: a premises
        # is a BUILDING and may hold several storefront units, so "the latest
        # filing" is still ONE unit's filing. A premises whose latest round
        # reports one vacant unit and two occupied ones is being called vacant
        # or occupied on the strength of the unit that sorts last. See the
        # handback note / audit finding 1 ("declare the grain + a
        # storefront-year view").
        rows = sorted(rows, key=lambda r: (
            r.reporting_year is None, r.reporting_year,
            r.filing_due_date is None, r.filing_due_date,
            str(r.storefront_id)))
        last = rows[-1]
        # DOF flags come back as pandas nullable booleans: bool(pd.NA) raises,
        # so a NULL flag must read as "not vacant", never crash the pack.
        if not (_flag(last.vacant_1231) or _flag(last.vacant_0630)):
            continue      # not currently vacant on its own latest filing
        if _isnull(last.lat) or _isnull(last.lon):
            continue
        dist_m = haversine_m(lat, lon, last.lat, last.lon)
        if dist_m > catchment_m:
            continue

        vacant_since = last.reporting_year
        prev_year = last.reporting_year
        for r in reversed(rows[:-1]):
            is_vacant = _flag(r.vacant_1231) or _flag(r.vacant_0630)
            if (is_vacant and r.reporting_year is not None and prev_year is not None
                    and prev_year - r.reporting_year <= 1):
                vacant_since = r.reporting_year
                prev_year = r.reporting_year
            else:
                break

        last_use = None
        for r in reversed(rows):
            if _present(r.primary_business_activity):
                last_use = r.primary_business_activity
                break

        out.append(VacantStorefrontRow(
            premises_id=premises_id,
            address=last.address if _present(last.address) else None,
            dist_m=round(dist_m, 1), floor_area_sqft=None, last_use=last_use,
            vacant_since=vacant_since if _present(vacant_since) else None,
            bbl=last.bbl if _present(last.bbl) else None))

    bbls = sorted({v.bbl for v in out if v.bbl})
    if bbls:
        placeholders = ",".join("?" for _ in bbls)
        area_by_bbl = dict(con.execute(
            f"SELECT bbl, TRY_CAST(retailarea AS DOUBLE) FROM analysis.address "
            f"WHERE bbl IN ({placeholders})", bbls).fetchall())
        for v in out:
            if v.bbl in area_by_bbl:
                v.floor_area_sqft = area_by_bbl[v.bbl]

    out.sort(key=lambda v: v.dist_m)
    return out


def _pipeline_rows(con, lat: float, lon: float, catchment_m: float) -> list[PipelineRow]:
    """SLA-pending and DOB-fit-out filings within `catchment_m`, nearest
    first, EXCLUDING anything `storefront_pipeline` already marks
    `is_open` (that filing has already resolved into a business -- it
    belongs in the supply table, not "what is coming"). Investor review item
    4: name these rows, don't fold them into `openings_pipeline_400m`."""
    df = con.execute(f"""
        SELECT pipeline_id, business_name, loci_category, entry_stage, entry_date,
               lon, lat, is_open
        FROM analysis.storefront_pipeline
        WHERE lon IS NOT NULL AND lat IS NOT NULL
          AND entry_stage IN ?
          AND {_borough_sql("borough")}
          AND {_bbox_sql(lat, lon, catchment_m, lon_expr="lon", lat_expr="lat")}
    """, [list(SLA_PENDING_STAGES) + list(DOB_FITOUT_STAGES)]).fetchdf()
    out: list[PipelineRow] = []
    for r in df.itertuples(index=False):
        if _flag(r.is_open):
            continue
        kind = "SLA pending" if r.entry_stage in SLA_PENDING_STAGES else "DOB fit-out"
        dist_m = haversine_m(lat, lon, r.lat, r.lon)
        if dist_m > catchment_m:
            continue
        # `_present`, not `or` (2026-09-15 fix): fetchdf() renders a NULL
        # VARCHAR as float NaN, which is TRUTHY -- `r.business_name or "—"`
        # kept the NaN and `render._pipeline_table` died on `.replace` the
        # first time a full memo met an unnamed filing.
        out.append(PipelineRow(
            pipeline_id=r.pipeline_id,
            business_name=r.business_name if _present(r.business_name) else None,
            category=r.loci_category if _present(r.loci_category) else None,
            kind=kind, stage=r.entry_stage if _present(r.entry_stage) else None,
            entry_date=r.entry_date if _present(r.entry_date) else None,
            dist_m=round(dist_m, 1)))
    out.sort(key=lambda p: p.dist_m)
    return out


def _chains_watch_rows(con, lat: float, lon: float,
                       radius_m: float = CHAINS_WATCH_RADIUS_M) -> list[ChainWatchRow]:
    """Flagged, expanding chain locations (D77: `chains.brand_latest.flagged`)
    within `radius_m` straight-line metres of the latest snapshot, nearest
    first. Investor review item 4: name the chains-watchlist entries, don't
    fold them into a generic supply row."""
    df = con.execute(f"""
        SELECT bl.brand_key, bl.category, bl.lon, bl.lat,
               br.display_name, br.locations_new_12m, br.locations_total
        FROM chains.brand_location bl
        JOIN chains.brand_latest br
          ON br.brand_key = bl.brand_key AND br.snapshot_month = bl.snapshot_month
        WHERE br.flagged
          AND bl.snapshot_month = (SELECT max(snapshot_month) FROM chains.brand_latest)
          AND {_borough_sql("bl.borough")}
          AND {_bbox_sql(lat, lon, radius_m, lon_expr="bl.lon", lat_expr="bl.lat")}
    """).fetchdf()
    out: list[ChainWatchRow] = []
    for r in df.itertuples(index=False):
        if _isnull(r.lat) or _isnull(r.lon):
            continue
        dist_m = haversine_m(lat, lon, r.lat, r.lon)
        if dist_m > radius_m:
            continue
        out.append(ChainWatchRow(
            brand_key=r.brand_key,
            display_name=r.display_name if _present(r.display_name) else r.brand_key,
            category=r.category if _present(r.category) else None,
            dist_m=round(dist_m, 1),
            locations_new_12m=r.locations_new_12m, locations_total=r.locations_total))
    out.sort(key=lambda c: c.dist_m)
    return out


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


def lead_category_override(grades: list, category: str, *,
                           allow_demoted: bool = False) -> list:
    """Re-order `grades` so `category` leads (owner ruling R3, 2026-09-15).

    The override moves a card to the FRONT; it never re-grades it, never
    invents one, and never drops the others -- `rank_categories`' thinnest-
    first order survives behind the forced lead, so the rest of the memo
    reads exactly as it would have. A demoted category is refused unless
    `allow_demoted`, because `rank_categories` exists precisely to stop one
    leading by accident (`model.recommend.non_headline_categories`)."""
    from loci.categories import CATEGORIES
    from loci.model.recommend import non_headline_categories

    if category not in CATEGORIES:
        raise CategoryNotAvailable(
            f"{category!r} is not a Loci category (one of: {', '.join(sorted(CATEGORIES))})")
    if category in non_headline_categories() and not allow_demoted:
        raise DemotedCategory(
            f"{category!r} is demoted from headline use (owner ruling 2026-09-14, D30 "
            "precedent: a gap of its own is as likely a hole in the data as in the "
            "market). Pass --allow-demoted to lead a memo with it anyway.")
    hit = next((i for i, c in enumerate(grades) if c["category"] == category), None)
    if hit is None:
        raise CategoryNotAvailable(
            f"{category!r} has no graded card at this address (no supply-ratio "
            "measurement for it in the catchment)")
    return [grades[hit]] + grades[:hit] + grades[hit + 1:]


def assemble(con, address_id: str, *, catchment_m: float = DEFAULT_CATCHMENT_M,
            recommendations_dir=None, category: str | None = None,
            allow_demoted: bool = False, cache=None) -> EvidencePack:
    """Every warehouse fact the four sections need, for ONE address. Pure
    read: no INSERT/UPDATE anywhere in this function, no paid call.

    `recommendations_dir` overrides where the same-BBL consistency check
    (investor review item 6) looks for other recent memos -- production
    callers never pass it (it defaults to `render.OUT_DIR`, the real
    `docs/recommendations/`); tests pass a `tmp_path` so this never reads or
    depends on the real repo's memo directory.

    `category` (owner ruling R3, `loci report --category`) forces the lead
    category instead of taking `rank_categories`' thinnest-first answer --
    `lead_category_override` refuses a demoted category unless
    `allow_demoted`. Everything downstream (forecast row, demand facts, the
    SLA 500-ft check, `EvidencePack.hash()`, so the cache key) keys off the
    lead, so the override changes the whole memo, not just its headline.

    `cache` is an optional `model.recommend.RunCache` shared across a sweep of
    addresses: it holds the four CITY-WIDE numbers a card needs (the coverage
    frame, the MN+BK reference demographics, the laundry-evidence BBL set and
    the supply hash), which are identical for every address in a run. `None`
    -- a single `loci report` -- computes them, exactly as before. A driver
    reporting on many addresses creates ONE and passes it to each call; see
    `RunCache` for the invalidation contract, and note in particular that it
    must be DROPPED after `enrich.py` writes closure evidence, because that
    moves the supply hash."""
    address = _address_row(con, address_id)
    legality = _legality_row(con, address_id)
    bbox = _bbox_around(address["lat"], address["lon"], GRADE_BBOX_HALF_WIDTH_M)
    rules = load_rules()
    scores = area_facts(con, address_id, bbox=bbox, boroughs=(address["borough"],),
                        cache=cache)
    grades = build_cards(scores, rules)
    if category is not None:
        grades = lead_category_override(grades, category, allow_demoted=allow_demoted)
    lead_category = grades[0]["category"] if grades else None
    forecast = _forecast_row(con, address_id, lead_category)
    supply = _supply_rows(con, address["lat"], address["lon"], catchment_m)
    demand = _demand_facts(con, address_id, lead_category, address)
    vacant_storefronts = _vacant_storefront_rows(con, address["lat"], address["lon"], catchment_m)
    pipeline = _pipeline_rows(con, address["lat"], address["lon"], catchment_m)
    chains_watch = _chains_watch_rows(con, address["lat"], address["lon"])
    sla_500ft = _sla_500ft_context(con, lead_category, address["lat"], address["lon"])
    # The file THIS run is about to write is not a second opinion about
    # itself (ruling R2's precondition): without the exclusion every re-run
    # on the same day reads yesterday's copy of its own memo and reports a
    # conflict with its own headline -- the `3027550006-2026-09-15.md` line
    # the 2026-09-15 review found in the footer.
    from loci.report.render import default_out_path
    same_bbl_conflicts = _same_bbl_consistency(
        address.get("bbl"), lead_category, recommendations_dir=recommendations_dir,
        exclude_path=default_out_path(address, directory=recommendations_dir))
    context = {
        "neighborhood": address.get("neighborhood"),
        "nta_code": address.get("nta_code"),
        "borough": address.get("borough"),
        "catchment_m": catchment_m,
    }
    provenance = {"asof": scores.get("asof"), "supply_hash": scores.get("live_hash"),
                 "sla_500ft": sla_500ft, "same_bbl_conflicts": same_bbl_conflicts,
                 "flood_environmental": FLOOD_ENVIRONMENTAL_NOT_LOADED}
    return EvidencePack(address=address, scores=scores, grades=grades, forecast=forecast,
                        supply=supply, demand=demand, legality=legality, context=context,
                        provenance=provenance, vacant_storefronts=vacant_storefronts,
                        pipeline=pipeline, chains_watch=chains_watch)
