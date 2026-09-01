"""Overture Maps Places — the primary POI base layer (GTM-14).

Universal source, works for any US city: monthly GeoParquet snapshots
aggregating OSM, Meta, and Microsoft place data (registry.yaml
`overture_places`, CONTEXT.md §3). Inherits the coverage gaps of those
upstream sources — same lower-income/immigrant-neighborhood undercount risk
as OSM (CONTEXT.md §7.1) — but is not raw OSM either: it merges multiple
providers and runs its own conflation/dedup, so it's treated as a distinct,
moderate-confidence source rather than as an alias for `osm_overpass`.

Data access: the `overturemaps` CLI downloads a NYC-bbox GeoParquet extract
once to `data/raw/overture_places_nyc.parquet` (gitignored, ~590k place rows
citywide). fetch() downloads that cache on first use (subprocess call to the
CLI) and reads it locally with DuckDB's spatial extension on every run after
— never re-downloads once the file exists.

Scope decision (recorded): Overture's `categories.primary` is a free
taxonomy with ~1,700 distinct values in the NYC extract alone (many are
cuisine-specific restaurant leaves, e.g. `sichuan_restaurant`). Only a
curated subset maps onto Loci's 15 categories; PRIMARY_CATEGORY below is
that subset, built by inspecting the actual distinct values in the NYC file
rather than guessing. One dynamic rule supplements it: any primary category
ending in `_restaurant` (the ~150-value cuisine family, e.g.
`pizza_restaurant`, `chinese_restaurant`) maps to `restaurant` — enumerating
each would be unmaintainable and the suffix is unambiguous. Records whose
primary category doesn't map (including the large generic `health_and_medical`
bucket, and specialist medical/dental/vision categories that don't cleanly
read as a neighborhood "clinic") are dropped, never guessed at. See the
GTM-14 report for the full list of plausible-but-unmapped categories.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path

from loci.sources.base import POIRecord, SourceAdapter

# NYC bounding box, in the order the `overturemaps` CLI expects:
# west,south,east,north.
BBOX = (-74.3, 40.4, -73.6, 41.0)

CACHE_PATH = Path("data/raw/overture_places_nyc.parquet")

# Overture `categories.primary` slug -> Loci category slug. Built from the
# actual distinct primary categories observed in the NYC extract, not from
# Overture's documentation alone — see module docstring.
PRIMARY_CATEGORY: dict[str, str] = {
    # grocery — plain + regional/specialty grocers, and fresh-produce markets
    # (Overture has no bare "supermarket" slug; "grocery_store" covers it).
    "grocery_store": "grocery",
    "organic_grocery_store": "grocery",
    "asian_grocery_store": "grocery",
    "international_grocery_store": "grocery",
    "mexican_grocery_store": "grocery",
    "kosher_grocery_store": "grocery",
    "indian_grocery_store": "grocery",
    "korean_grocery_store": "grocery",
    "japanese_grocery_store": "grocery",
    "russian_grocery_store": "grocery",
    "farmers_market": "grocery",
    # convenience
    "convenience_store": "convenience",
    # pharmacy
    "pharmacy": "pharmacy",
    "drugstore": "pharmacy",
    # laundry
    "laundromat": "laundry",
    "laundry_services": "laundry",
    "dry_cleaning": "laundry",
    # hair_barber
    "hair_salon": "hair_barber",
    "barber": "hair_barber",
    "hair_stylist": "hair_barber",
    "kids_hair_salon": "hair_barber",
    # nails_beauty — nail/beauty salons plus generic spa and lash/brow/wax
    # services (all personal beauty services, OSM shop=beauty is similarly
    # broad).
    "nail_salon": "nails_beauty",
    "beauty_salon": "nails_beauty",
    "spas": "nails_beauty",
    "day_spa": "nails_beauty",
    "health_spa": "nails_beauty",
    "eyelash_service": "nails_beauty",
    "eyebrow_service": "nails_beauty",
    "waxing": "nails_beauty",
    # tailor_repair (Overture has no bare "tailor"; "gents_tailor" is the
    # closest exact slug)
    "gents_tailor": "tailor_repair",
    "sewing_and_alterations": "tailor_repair",
    "shoe_repair": "tailor_repair",
    # restaurant — plain + fast food; the ~150 cuisine-specific leaves
    # (chinese_restaurant, pizza_restaurant, ...) are caught by the
    # endswith("_restaurant") rule in normalize(), not enumerated here.
    "restaurant": "restaurant",
    "fast_food_restaurant": "restaurant",
    # cafe_bakery
    "cafe": "cafe_bakery",
    "coffee_shop": "cafe_bakery",
    "bakery": "cafe_bakery",
    "hong_kong_style_cafe": "cafe_bakery",
    # bar — alcohol-serving bars and pubs only (not "bar" in name only, e.g.
    # smoothie_juice_bar / salad_bar are food counters, not alcohol venues,
    # and are left unmapped).
    "bar": "bar",
    "cocktail_bar": "bar",
    "sports_bar": "bar",
    "wine_bar": "bar",
    "hookah_bar": "bar",
    "dive_bar": "bar",
    "beer_bar": "bar",
    "gay_bar": "bar",
    "hotel_bar": "bar",
    "whiskey_bar": "bar",
    "tiki_bar": "bar",
    "sake_bar": "bar",
    "piano_bar": "bar",
    "champagne_bar": "bar",
    "beer_garden": "bar",
    "pub": "bar",
    "gastropub": "bar",
    "irish_pub": "bar",
    # childcare
    "child_care_and_day_care": "childcare",
    "day_care_preschool": "childcare",
    "preschool": "childcare",
    # clinic — general/urgent/community clinics and medical centers only.
    # Overture has no bare "clinic" or "doctor" slug; dentists, optometrists,
    # chiropractors, and other specialist practices are left unmapped (see
    # module docstring) since they read as specialist offices, not the
    # OSM amenity=clinic|doctors neighborhood-clinic sense CONTEXT.md §2.1
    # scopes this category to.
    "urgent_care_clinic": "clinic",
    "walk_in_clinic": "clinic",
    "public_health_clinic": "clinic",
    "medical_center": "clinic",
    # fitness
    "gym": "fitness",
    "fitness_trainer": "fitness",
    "gymnastics_center": "fitness",
    "boxing_gym": "fitness",
    "gymnastics_club": "fitness",
    "rock_climbing_gym": "fitness",
    "aerial_fitness_center": "fitness",
    "yoga_studio": "fitness",
    "pilates_studio": "fitness",
    "martial_arts_club": "fitness",
    # bank (Overture uses "banks", plural, not "bank")
    "banks": "bank",
    "bank_credit_union": "bank",
    # hardware
    "hardware_store": "hardware",
    "home_improvement_store": "hardware",
}


class OverturePlacesAdapter(SourceAdapter):
    source_id = "overture_places"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        self._ensure_cache()

        import duckdb

        con = duckdb.connect()
        con.execute("INSTALL spatial; LOAD spatial;")
        query = """
            SELECT
                id,
                names.primary AS name,
                categories.primary AS primary_category,
                ST_X(geometry) AS lon,
                ST_Y(geometry) AS lat
            FROM read_parquet(?)
        """
        params: list = [str(CACHE_PATH)]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        try:
            cursor = con.execute(query, params)
            while True:
                rows = cursor.fetchmany(10_000)
                if not rows:
                    break
                for row in rows:
                    yield {
                        "id": row[0],
                        "name": row[1],
                        "primary_category": row[2],
                        "lon": row[3],
                        "lat": row[4],
                    }
        finally:
            con.close()

    def _ensure_cache(self) -> None:
        if CACHE_PATH.exists() and CACHE_PATH.stat().st_size > 0:
            return
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        w, s, e, n = BBOX
        subprocess.run(
            [
                "overturemaps", "download",
                f"--bbox={w},{s},{e},{n}",
                "-f", "geoparquet",
                "--type=place",
                "-o", str(CACHE_PATH),
            ],
            check=True,
        )

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        today = dt.date.today()
        seen: set[str] = set()
        for r in rows:
            rid = r.get("id")
            if not rid or rid in seen:
                continue

            lon, lat = r.get("lon"), r.get("lat")
            if lon is None or lat is None:
                continue
            try:
                lonf, latf = float(lon), float(lat)
            except (TypeError, ValueError):
                continue

            # The `overturemaps` CLI --bbox filter selects whole row groups
            # that intersect the box rather than clipping exactly, so a rare
            # record can land a hair outside it. Enforce the box here too.
            w, s, e, n = BBOX
            if not (w <= lonf <= e and s <= latf <= n):
                continue

            primary = r.get("primary_category")
            category = self._category_for(primary)
            if category is None:
                continue

            seen.add(rid)
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=rid,
                category=category,
                name=(r.get("name") or "").strip() or None,
                lon=lonf, lat=latf,
                observed_on=today,
                confidence=0.7,
                attrs={"primary_category": primary},
            )

    @staticmethod
    def _category_for(primary: str | None) -> str | None:
        if not primary:
            return None
        cat = PRIMARY_CATEGORY.get(primary)
        if cat:
            return cat
        # The cuisine-specific restaurant family (chinese_restaurant,
        # pizza_restaurant, ...) is too large to enumerate; the suffix is
        # unambiguous within this taxonomy.
        if primary.endswith("_restaurant"):
            return "restaurant"
        return None
