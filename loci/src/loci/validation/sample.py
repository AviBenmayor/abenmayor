"""Stratified coverage-validation sample and runner (GTM-47 / GTM-48).

THE SAMPLING FRAME IS GAP ADDRESSES (CHECKPOINT D38 / D58)
--------------------------------------------------------------------------
`draw_sample` draws rows of analysis.address_gaps — residential PLUTO lots,
the project's unit of analysis since D38 — not hex centroids. A hex centroid
was never a place: it is the middle of a 461 m cell that may sit in a park, a
rail yard or the middle of a block, and the screen being validated no longer
speaks in hexes. Validating the address screen against a sample of hex
centroids would measure coverage at points no lead ever refers to.

Scope is Manhattan + Brooklyn (D48). Strata are

    income decile  ×  "missing this category" (its {category}_ratio > 1.0)

per category. The income decile is NTILE(10) over
analysis.address_demographics.median_hh_income — the tract's own ACS median
looked up directly on the lot's BBL (D56: a tax lot sits in exactly one
tract, so there is no apportionment and no MAUP wobble as there was on the
hex grid). The missing/present split is what makes this sample able to answer
the question the validator exists for (D29 §7.1 / P3): if OSM/Overture
undercount small business in lower-income neighbourhoods, loci's "gaps" there
are a data gap wearing a costume. Measuring Google's enumeration ONLY where
loci says a category is missing cannot separate coverage bias from a real
hole — the present side of each stratum is the control.

The sample is ADDRESS-weighted by default: every eligible lot is one draw,
so a 400-unit apartment building and a two-family house count the same. That
is the right weighting for "is loci's inventory right at this point", which
is a property of the point, not of the households behind it. Pass
`unit_weighted=True` (CLI `--unit-weighted`) to draw proportional to
`units_capped` instead — the right weighting for "how many households sit
behind a mis-measured gap", and the one to use if the sample is ever read as
a population statement rather than a coverage statement.

Cross-stratification by foreign-born share (QUESTIONS.md X3) is still not
possible — neither address_demographics nor hex_demographics carries a
foreign-born column; add it to the ACS ingest before claiming that contrast.

Per sampled ADDRESS × category we record:
  n_ground_truth  Google Nearby count within RADIUS_M of the ADDRESS point
                  (≤20), primary-type-matched against loci's single-label
                  categories (GTM-105 finding A).
  n_ground_truth_at_cap  True iff n_ground_truth == 20 — the API has no
                  pagination, so a capped row is right-censored and must be
                  excluded from any mean/ratio/undercount statistic.
  ground_truth_types  JSON histogram of Google's primaryType for this call,
                  read at zero extra API spend (GTM-105 finding G).
  n_overture / n_osm / n_city_source  our own sources within the same
                  straight-line radius of the SAME point — the like-for-like
                  comparison (address_gaps uses network distance, which
                  Google cannot).
  radius_m        the straight-line radius both sides were measured at, so a
                  circuity-corrected run is distinguishable from the 800 m
                  rows (QUESTIONS M8 / D53). NULL on pre-D53 rows.
Only counts (and, since GTM-105, the returned type labels) are stored (Maps
Platform terms).

Rows carrying h3_index are the PRE-D38 HEX FRAME (the 2,970 rows written
2026-09-02..03, every one measured at LEGACY_RADIUS_M) and must never be
pooled with address rows: different unit, different geometry, different disc.
See `ensure_address_frame` for why the table's hex-era primary key has to go.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import random

from loci.categories import CATEGORIES
from loci.validation.google_places import GooglePlacesClient, GOOGLE_TYPES
from loci.validation.google_places import RADIUS_M as _DERIVED_RADIUS_M

# Straight-line radius for BOTH sides of the comparison. Derived, not
# hardcoded: reach_tiers.yaml's `validation` block carries the gap screen's
# 800 m NETWORK threshold and NYC's measured circuity (1.233), and
# loci.reach.validation_radius_m divides one by the other (QUESTIONS M8,
# CHECKPOINT D53). It was a literal 800 until 2026-09-08 -- see LEGACY_RADIUS_M.
RADIUS_M: int = _DERIVED_RADIUS_M

# What rows written before D53 were measured at. analysis.coverage_validation
# gained radius_m in the same change, so those rows read NULL; anything that
# re-measures the local side of a historical row must use ITS radius, not
# today's, or the Google count and the local count stop being comparable.
LEGACY_RADIUS_M: int = 800

# D48: the screen's scope. Sampling outside it would spend the Google budget
# validating addresses no lead is ever drawn from.
DEFAULT_BOROUGHS: tuple[str, ...] = ("MN", "BK")

# An address is "missing" a category when its network distance to the nearest
# one exceeds that category's reach — analysis.address_gaps stores exactly
# that as {category}_ratio (nearest_m / reach_m), so > 1.0 IS the gap
# definition (D39), not a re-derivation of it.
MISSING_RATIO: float = 1.0

CITY_SOURCE = {  # the near-census anchor per category, where one exists
    "restaurant": "nyc_dohmh_restaurants", "cafe_bakery": "nyc_dohmh_restaurants",
    "bar": "nys_sla_liquor_licenses", "grocery": "usda_snap_retailers",
    "convenience": "usda_snap_retailers", "hair_barber": "nys_dos_appearance_enhancement",
    "nails_beauty": "nys_dos_appearance_enhancement",
}


def mapped_categories(categories: list[str]) -> tuple[list[str], list[str]]:
    """Split `categories` into (mapped, skipped) against GOOGLE_TYPES.

    A category not in loci's own CATEGORIES is a typo and still raises. A
    category that IS a valid loci category but has no Google Places mapping
    (currently just `clinic` -- GTM-105 #7: `doctor`/`medical_lab` measure a
    different universe than the 621111/621493 anchor) is skipped, not
    KeyError'd -- Google's taxonomy does not cover every NAICS anchor.
    """
    for c in categories:
        if c not in CATEGORIES:
            raise ValueError(f"unknown category {c!r}")
    mapped = [c for c in categories if c in GOOGLE_TYPES]
    skipped = [c for c in categories if c not in GOOGLE_TYPES]
    return mapped, skipped


def _draw(rng: random.Random, pool: list[dict], n: int, unit_weighted: bool) -> list[dict]:
    """n rows from `pool`, seeded and reproducible.

    The pool is sorted by address_id first: DuckDB does not promise a row
    order, and an unsorted pool would make the seed meaningless (the same
    seed would draw a different sample after a rebuild of address_gaps).

    unit_weighted uses Efraimidis-Spirakis A-Res -- key = u ** (1/weight),
    keep the largest n keys -- which is weighted sampling WITHOUT replacement
    with inclusion probability proportional to `units_capped`. units_capped,
    not raw units: D39 found ~10k-unit lots (Co-op City scale) otherwise
    swallow the whole draw.
    """
    pool = sorted(pool, key=lambda r: r["address_id"])
    if n >= len(pool):
        return list(pool)
    if not unit_weighted:
        return rng.sample(pool, n)
    keyed = []
    for r in pool:
        w = max(float(r.get("units_capped") or 0.0), 1e-9)
        keyed.append((rng.random() ** (1.0 / w), r["address_id"], r))
    keyed.sort(key=lambda t: (-t[0], t[1]))
    return [r for _, _, r in keyed[:n]]


def draw_sample(con, categories: list[str] | None = None, per_stratum: int = 20,
                boroughs: tuple[str, ...] | list[str] = DEFAULT_BOROUGHS,
                seed: int = 20260902, unit_weighted: bool = False,
                eligible_only: bool = True, acs_year: int | None = None) -> list[dict]:
    """Gap ADDRESSES, stratified by income decile × missing-this-category.

    Returns one dict per (address, category) CALL -- the category is part of
    the draw, because the missing/present half of the stratum is defined per
    category: the addresses missing groceries are not the addresses missing a
    hardware store. Each row carries address_id, bbl, lat, lon, borough,
    income_decile, units_capped, category and `missing`.

    Strata: 10 income deciles × {missing, present} × |categories|, with
    `per_stratum` addresses each. Deciles are NTILE(10) over
    address_demographics.median_hh_income across the WHOLE frame (all
    eligible addresses in scope), computed once, so a decile means the same
    thing in every category's strata. Ties at a decile boundary are split
    arbitrarily by NTILE; with ~265k addresses over ~2.3k distinct tract
    medians the effect on a stratum of 20 is negligible.

    `eligible_only` keeps the address screen's own walkability gate
    (present_count >= 12 of 15 within 800 m, D38/D39): an ineligible address
    is out of scope for a lead, so ground-truthing it validates nothing.
    """
    mapped, _skipped = mapped_categories(list(categories) if categories is not None else list(CATEGORIES))
    if not mapped:
        return []
    boroughs = tuple(boroughs)
    if not boroughs:
        return []

    if acs_year is None:
        acs_year = con.execute(
            "SELECT max(acs_year) FROM analysis.address_demographics").fetchone()[0]
        if acs_year is None:
            return []

    # Category names are validated against CATEGORIES above, so the column
    # interpolation below cannot carry anything but a known identifier.
    ratio_cols = ", ".join(f'g."{c}_ratio" AS "{c}_ratio"' for c in mapped)
    boro_ph = ", ".join(["?"] * len(boroughs))
    eligible_sql = "AND g.eligible" if eligible_only else ""
    rows = con.execute(f"""
        SELECT g.address_id, g.bbl, g.lat, g.lon, g.borough,
               COALESCE(g.units_capped, 0.0) AS units_capped,
               NTILE(10) OVER (ORDER BY d.median_hh_income) AS income_decile,
               {ratio_cols}
        FROM analysis.address_gaps g
        JOIN analysis.address_demographics d
          ON d.address_id = g.address_id AND d.acs_year = ?
        WHERE g.borough IN ({boro_ph})
          AND d.median_hh_income IS NOT NULL
          {eligible_sql}
    """, [acs_year, *boroughs]).fetchall()
    if not rows:
        return []

    base = ["address_id", "bbl", "lat", "lon", "borough", "units_capped", "income_decile"]
    recs = [dict(zip(base + [f"{c}_ratio" for c in mapped], r)) for r in rows]

    out: list[dict] = []
    for c in mapped:
        # A seed per category, so adding a category to a run does not reshuffle
        # the addresses already drawn for the others.
        rng = random.Random(f"{seed}:{c}")
        strata: dict[tuple[int, bool], list[dict]] = {}
        for r in recs:
            ratio = r.get(f"{c}_ratio")
            missing = ratio is not None and float(ratio) > MISSING_RATIO
            strata.setdefault((int(r["income_decile"]), missing), []).append(r)
        for (decile, missing) in sorted(strata, key=lambda k: (k[0], not k[1])):
            for r in _draw(rng, strata[(decile, missing)], per_stratum, unit_weighted):
                out.append({"address_id": r["address_id"], "bbl": r["bbl"],
                            "lat": r["lat"], "lon": r["lon"], "borough": r["borough"],
                            "units_capped": r["units_capped"], "income_decile": decile,
                            "category": c, "missing": missing})
    return out


from loci.db import METRES_SQL as METRES   # axis-order-safe distance, see D16


def _local_counts(con, lat: float, lon: float, category: str,
                  radius_m: int = RADIUS_M) -> tuple[int, int, int | None, int]:
    """Per-source and canonical-total local counts within `radius_m` straight-line
    of the sampled POINT — since D58 that point is the ADDRESS (the lot's own
    lon/lat as stored in analysis.address_gaps), the same centre passed to
    Google's Nearby Search, at the same radius. Hex-frame rows re-measured by
    `recount_local` still pass their hex centroid here.

    `radius_m` is an argument, not a constant read inside, because
    recount_local has to re-measure historical rows at THEIR radius.

    n_overture/n_osm/n_city are read off staging.poi (raw, un-deduped) purely to
    populate the legacy per-source columns; they are NOT summed into the
    canonical total and must not be treated as "loci's coverage" on their own —
    n_overture + n_osm silently dropped foursquare_os_places (the dominant
    hardware/fitness/clinic source) and every other ingested source.

    n_local_canonical is the corrected figure: canonical (deduped, is_canonical)
    POIs of `category` across ALL sources, same radius — the same canonical
    layer analysis.address_gaps is built from, just measured straight-line
    instead of network so it is comparable to n_ground_truth.
    """
    q_raw = f"""
        SELECT source_id, count(*) FROM staging.poi
        WHERE category = ? AND {METRES.format(a="geom", b="ST_Point(?, ?)")} <= ?
        GROUP BY 1"""
    counts = dict(con.execute(q_raw, [category, lon, lat, radius_m]).fetchall())
    city = CITY_SOURCE.get(category)

    q_canon = f"""
        SELECT count(*) FROM staging.poi p
        JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id AND d.is_canonical
        WHERE p.category = ? AND {METRES.format(a="p.geom", b="ST_Point(?, ?)")} <= ?"""
    n_canon = con.execute(q_canon, [category, lon, lat, radius_m]).fetchone()[0]

    return (counts.get("overture_places", 0), counts.get("osm_overpass", 0),
            counts.get(city, 0) if city else None, n_canon)


def ensure_address_frame(con) -> int:
    """Drop analysis.coverage_validation's hex-era PRIMARY KEY (h3_index,
    category) so address rows can be written with h3_index NULL. Returns the
    number of rows carried over (0 when the table is already migrated).

    Why a rebuild and not an ALTER: a DuckDB PRIMARY KEY column is implicitly
    NOT NULL and there is no `ALTER TABLE ... DROP CONSTRAINT`, so a table
    keyed on h3_index physically cannot hold an address-frame row. The
    migration renames the old table, re-applies sql/002_schema.sql (which
    creates the current, key-free shape and adds address_id/borough), copies
    every row back by column NAME, and drops the rename — so a migrated
    database ends up with exactly the shape a fresh one gets, with no DDL
    duplicated in Python. The 2,970 pre-D38 hex rows are preserved verbatim,
    h3_index and all.

    Uniqueness is now maintained by `run` (delete-then-insert on the row's own
    key: h3_index+category for a hex row, address_id+category for an address
    row) rather than by the engine, because no single key covers both frames.
    """
    from loci import db as locidb

    has_pk = con.execute("""
        SELECT count(*) FROM duckdb_constraints()
        WHERE schema_name = 'analysis' AND table_name = 'coverage_validation'
          AND constraint_type = 'PRIMARY KEY'""").fetchone()[0]
    if not has_pk:
        return 0

    con.execute("ALTER TABLE analysis.coverage_validation RENAME TO coverage_validation_hexpk")
    con.execute((locidb.SQL_DIR / "002_schema.sql").read_text())
    old = [r[0] for r in con.execute("""
        SELECT column_name FROM duckdb_columns()
        WHERE schema_name = 'analysis' AND table_name = 'coverage_validation_hexpk'""").fetchall()]
    new = [r[0] for r in con.execute("""
        SELECT column_name FROM duckdb_columns()
        WHERE schema_name = 'analysis' AND table_name = 'coverage_validation'""").fetchall()]
    cols = ", ".join(f'"{c}"' for c in old if c in new)
    con.execute(f"""INSERT INTO analysis.coverage_validation ({cols})
                    SELECT {cols} FROM analysis.coverage_validation_hexpk""")
    moved = con.execute("SELECT count(*) FROM analysis.coverage_validation_hexpk").fetchone()[0]
    con.execute("DROP TABLE analysis.coverage_validation_hexpk")
    return int(moved)


def recount_local(con) -> int:
    """Recompute n_overture/n_osm/n_city_source/n_local_canonical for every row
    already in analysis.coverage_validation, against the CURRENT staging.poi /
    poi_dedup contents. Spends nothing — n_ground_truth (the Google count) is
    left untouched. Use after fixing _local_counts, or after re-ingesting /
    re-deduping sources, to refresh the local side of the comparison without
    burning Google Places budget.

    Handles BOTH frames: an address row is re-measured at its lot's own
    lon/lat (analysis.address_gaps), a pre-D38 hex row at its hex centroid.
    A row whose point can no longer be resolved (an address dropped from a
    rebuilt address_gaps, say) is left untouched and not counted — silently
    recounting it at the wrong point would be worse than leaving it stale.

    Each row is re-measured at ITS OWN radius (COALESCE(radius_m,
    LEGACY_RADIUS_M) -- a NULL means a pre-D53 row), NOT at today's RADIUS_M.
    Recounting a legacy row at the smaller circuity-corrected radius would
    shrink the local side while leaving its Google count untouched, and
    manufacture an undercount that never happened."""
    ensure_address_frame(con)
    rows = con.execute("""
        SELECT cv.h3_index, cv.address_id, cv.category,
               COALESCE(ST_Y(h.centroid), g.lat) AS lat,
               COALESCE(ST_X(h.centroid), g.lon) AS lon,
               COALESCE(cv.radius_m, ?) AS radius_m
        FROM analysis.coverage_validation cv
        LEFT JOIN analysis.hex h ON h.h3_index = cv.h3_index
        LEFT JOIN analysis.address_gaps g
               ON g.address_id = cv.address_id
              AND g.borough = COALESCE(cv.borough, g.borough)
    """, [LEGACY_RADIUS_M]).fetchall()
    n = 0
    for h3_index, address_id, category, lat, lon, radius_m in rows:
        if lat is None or lon is None:
            continue
        n_ov, n_osm, n_city, n_canon = _local_counts(con, lat, lon, category, int(radius_m))
        con.execute("""
            UPDATE analysis.coverage_validation
            SET n_overture = ?, n_osm = ?, n_city_source = ?, n_local_canonical = ?
            WHERE category = ?
              AND h3_index IS NOT DISTINCT FROM ?
              AND address_id IS NOT DISTINCT FROM ?""",
                    [n_ov, n_osm, n_city, n_canon, category, h3_index, address_id])
        n += 1
    return n


def plan(sample: list[dict], categories: list[str]) -> dict:
    """What a run would cost, and on what frame — printed before anything is spent.

    An address-frame sample (rows carrying `category`, from draw_sample) is
    one CALL per row, so the strata ARE the plan. A legacy hex sample (rows
    with no category) is still the cross product of points × mapped
    categories, so old callers and the pre-D38 rows read the same as before.
    """
    mapped, skipped = mapped_categories(categories)
    address_frame = bool(sample) and "category" in sample[0]
    if address_frame:
        rows = [s for s in sample if s["category"] in mapped]
        calls = len(rows)
        addresses = len({s["address_id"] for s in rows})
        strata = collections.Counter(
            (s["category"], int(s["income_decile"]), bool(s["missing"])) for s in rows)
        boroughs = sorted({s["borough"] for s in rows if s.get("borough")})
        per_category = {
            c: {"missing": sum(n for (cat, _d, m), n in strata.items() if cat == c and m),
                "present": sum(n for (cat, _d, m), n in strata.items() if cat == c and not m)}
            for c in mapped}
    else:
        rows = sample
        calls = len(sample) * len(mapped)
        addresses = len(sample)
        strata = collections.Counter()
        boroughs = []
        per_category = {}
    if address_frame:
        frame = "addresses, {}, income-decile × missing strata".format(
            "+".join(boroughs) or "no borough")
    elif not sample:
        frame = "empty draw — nothing in the address frame"
    else:
        frame = "hexes (pre-D38 frame)"
    return {"unit": "address" if address_frame else "hex",
            "frame": frame,
            "addresses": addresses, "points": len(rows),
            "boroughs": boroughs,
            "categories": len(mapped), "calls": calls, "skipped": skipped,
            "strata": dict(strata), "per_category": per_category,
            "n_strata": len(strata),
            "radius_m": RADIUS_M,
            "est_cost_usd": round(max(0, calls - 5000) * 0.032, 2)}   # Pro SKU beyond the free tier


def run(con, client: GooglePlacesClient, sample: list[dict], categories: list[str],
        dry_run: bool = True) -> int:
    """Spend the Google budget on `sample` and write analysis.coverage_validation.

    Each sample row is called at ITS OWN point — the address's lon/lat for an
    address-frame row (D58), the hex centroid for a legacy row — and the local
    side is counted at the same point and the same radius, so the two sides of
    every row are like-for-like by construction.
    """
    mapped, _skipped = mapped_categories(categories)
    if dry_run:
        return 0
    ensure_address_frame(con)
    today = dt.date.today()
    written = 0
    for s in sample:
        row_cats = [s["category"]] if s.get("category") else mapped
        for c in row_cats:
            if c not in mapped:
                continue
            n_ov, n_osm, n_city, n_canon = _local_counts(con, s["lat"], s["lon"], c, RADIUS_M)
            gt = client.nearby_count(s["lat"], s["lon"], c, RADIUS_M)
            # Per-call histogram of Google's primaryType, at zero extra API
            # spend (GTM-105 finding G) — measures over-inclusion instead of
            # asserting it. Places with no primaryType are dropped from the
            # histogram (their `types` are still discarded here; nothing else
            # currently consumes them).
            histogram = collections.Counter(pt for pt, _types in gt.places if pt)
            gt_types_json = json.dumps(dict(histogram)) if histogram else None
            h3_index, address_id = s.get("h3_index"), s.get("address_id")
            con.execute("""DELETE FROM analysis.coverage_validation
                WHERE category = ?
                  AND h3_index IS NOT DISTINCT FROM ?
                  AND address_id IS NOT DISTINCT FROM ?""", [c, h3_index, address_id])
            con.execute("""INSERT INTO analysis.coverage_validation
                (h3_index, address_id, borough, category, income_decile, n_ground_truth,
                 n_overture, n_osm, n_city_source, n_local_canonical, n_ground_truth_at_cap,
                 ground_truth_types, radius_m, sampled_on)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [h3_index, address_id, s.get("borough"), c, s["income_decile"], gt.count,
                         n_ov, n_osm, n_city, n_canon, gt.at_cap, gt_types_json, RADIUS_M, today])
            written += 1
    return written
