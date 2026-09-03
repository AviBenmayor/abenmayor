"""Stratified coverage-validation sample and runner (GTM-47 / GTM-48).

Sample: populated hexes drawn at random within each median-income decile.
Cross-stratification by foreign-born share (QUESTIONS.md X3) is not possible
yet — `hex_demographics` carries no foreign-born column; add it to the ACS
ingest before claiming that contrast.

Per sampled hex × category we record:
  n_ground_truth  Google Nearby count within RADIUS_M of the hex centroid (≤20)
  n_overture / n_osm / n_city_source  our own sources within the same
                  straight-line radius — the SAME geometry as the Google call,
                  so the comparison is like-for-like (hex_access uses network
                  distance, which Google cannot).
Only counts are stored (Maps Platform terms).
"""
from __future__ import annotations

import datetime as dt
import random

from loci.categories import CATEGORIES
from loci.validation.google_places import GooglePlacesClient, GOOGLE_TYPES

RADIUS_M = 800
CITY_SOURCE = {  # the near-census anchor per category, where one exists
    "restaurant": "nyc_dohmh_restaurants", "cafe_bakery": "nyc_dohmh_restaurants",
    "bar": "nys_sla_liquor_licenses", "grocery": "usda_snap_retailers",
    "convenience": "usda_snap_retailers", "hair_barber": "nys_dos_appearance_enhancement",
    "nails_beauty": "nys_dos_appearance_enhancement",
}


def draw_sample(con, per_decile: int = 20, min_pop: float = 800.0, seed: int = 20260902) -> list[dict]:
    rows = con.execute("""
        SELECT h.h3_index, ST_Y(h.centroid) lat, ST_X(h.centroid) lon,
               NTILE(10) OVER (ORDER BY d.median_hh_income) AS decile
        FROM analysis.hex h
        JOIN analysis.hex_demographics d ON d.h3_index = h.h3_index AND d.acs_year = 2023
        WHERE d.population > ? AND d.median_hh_income IS NOT NULL
    """, [min_pop]).fetchall()
    rng = random.Random(seed)
    by_decile: dict[int, list] = {}
    for h, lat, lon, dec in rows:
        by_decile.setdefault(int(dec), []).append((h, lat, lon))
    out = []
    for dec in sorted(by_decile):
        pool = by_decile[dec]
        for h, lat, lon in rng.sample(pool, min(per_decile, len(pool))):
            out.append({"h3_index": h, "lat": lat, "lon": lon, "income_decile": dec})
    return out


from loci.db import METRES_SQL as METRES   # axis-order-safe distance, see D16


def _local_counts(con, lat: float, lon: float, category: str) -> tuple[int, int, int | None, int]:
    """Per-source and canonical-total local counts within RADIUS_M straight-line.

    n_overture/n_osm/n_city are read off staging.poi (raw, un-deduped) purely to
    populate the legacy per-source columns; they are NOT summed into the
    canonical total and must not be treated as "loci's coverage" on their own —
    n_overture + n_osm silently dropped foursquare_os_places (the dominant
    hardware/fitness/clinic source) and every other ingested source.

    n_local_canonical is the corrected figure: canonical (deduped, is_canonical)
    POIs of `category` across ALL sources, same radius — the same canonical
    layer analysis.hex_gaps is built from (via hex_poi_distance), just measured
    straight-line instead of network so it is comparable to n_ground_truth.
    """
    q_raw = f"""
        SELECT source_id, count(*) FROM staging.poi
        WHERE category = ? AND {METRES.format(a="geom", b="ST_Point(?, ?)")} <= ?
        GROUP BY 1"""
    counts = dict(con.execute(q_raw, [category, lon, lat, RADIUS_M]).fetchall())
    city = CITY_SOURCE.get(category)

    q_canon = f"""
        SELECT count(*) FROM staging.poi p
        JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id AND d.is_canonical
        WHERE p.category = ? AND {METRES.format(a="p.geom", b="ST_Point(?, ?)")} <= ?"""
    n_canon = con.execute(q_canon, [category, lon, lat, RADIUS_M]).fetchone()[0]

    return (counts.get("overture_places", 0), counts.get("osm_overpass", 0),
            counts.get(city, 0) if city else None, n_canon)


def recount_local(con) -> int:
    """Recompute n_overture/n_osm/n_city_source/n_local_canonical for every row
    already in analysis.coverage_validation, against the CURRENT staging.poi /
    poi_dedup contents. Spends nothing — n_ground_truth (the Google count) is
    left untouched. Use after fixing _local_counts, or after re-ingesting /
    re-deduping sources, to refresh the local side of the comparison without
    burning Google Places budget."""
    rows = con.execute("""
        SELECT cv.h3_index, cv.category, ST_Y(h.centroid), ST_X(h.centroid)
        FROM analysis.coverage_validation cv
        JOIN analysis.hex h ON h.h3_index = cv.h3_index
    """).fetchall()
    for h3_index, category, lat, lon in rows:
        n_ov, n_osm, n_city, n_canon = _local_counts(con, lat, lon, category)
        con.execute("""
            UPDATE analysis.coverage_validation
            SET n_overture = ?, n_osm = ?, n_city_source = ?, n_local_canonical = ?
            WHERE h3_index = ? AND category = ?""",
                    [n_ov, n_osm, n_city, n_canon, h3_index, category])
    return len(rows)


def plan(sample: list[dict], categories: list[str]) -> dict:
    calls = len(sample) * len(categories)
    return {"hexes": len(sample), "categories": len(categories), "calls": calls,
            "est_cost_usd": round(max(0, calls - 5000) * 0.032, 2)}   # Pro SKU beyond the free tier


def run(con, client: GooglePlacesClient, sample: list[dict], categories: list[str],
        dry_run: bool = True) -> int:
    for c in categories:
        if c not in CATEGORIES or c not in GOOGLE_TYPES:
            raise ValueError(f"unknown category {c!r}")
    if dry_run:
        return 0
    today = dt.date.today()
    written = 0
    for s in sample:
        for c in categories:
            n_ov, n_osm, n_city, n_canon = _local_counts(con, s["lat"], s["lon"], c)
            n_gt = client.nearby_count(s["lat"], s["lon"], c, RADIUS_M)
            con.execute("DELETE FROM analysis.coverage_validation WHERE h3_index = ? AND category = ?",
                        [s["h3_index"], c])
            con.execute("""INSERT INTO analysis.coverage_validation
                (h3_index, category, income_decile, n_ground_truth, n_overture, n_osm, n_city_source,
                 n_local_canonical, sampled_on)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [s["h3_index"], c, s["income_decile"], n_gt, n_ov, n_osm, n_city, n_canon, today])
            written += 1
    return written
