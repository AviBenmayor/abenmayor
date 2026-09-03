"""Foursquare Open Source Places — third opinion on presence (GTM-15).

Universal source: ~100M venues worldwide, Apache-2.0, refreshed monthly, one
parquet release per month. What it adds that Overture and OSM do not: a
check-in-derived venue base with fine-grained categories for the bundle's
anchor-less categories (gym, hardware store, laundromat, nail salon, urgent
care) and per-venue `date_created` / `date_closed`, the only temporal signal in
any free POI source.

Bias, stated: built from check-ins and partner feeds, so it over-represents
places people announce being at (bars, gyms, cafes) and under-represents
laundromats and tailors. Different blind spot from OSM's income skew, which is
the point of having both. Its other failure mode is GHOSTS — venues that closed
years ago but were never marked closed — handled by the MIN_REFRESHED gate.

ACCESS (changed 2025-10): the public S3 bucket now holds only LICENSE/NOTICE.
Data is served from the Foursquare Places Portal (Iceberg, token) or the gated
Hugging Face mirror `foursquare/fsq-os-places` (accept terms, then a token).
This adapter reads the HF mirror through DuckDB's `hf://` support using
`HF_TOKEN`, filters to BBOX once, and caches the extract locally — the same
download-once pattern as the Overture adapter. Without a token and no cache it
fails loud rather than silently yielding nothing.

Category mapping: Foursquare labels are a path ("Retail > Food and Beverage
Retail > Grocery Store"). Cuisine/bar/cafe families are matched by path prefix,
everything else by leaf label — see GROUP_CATEGORY / LEAF_CATEGORY, built from
the real 2026-08-11 taxonomy. `normalize()` records the top unmapped leaves in
`self.unmapped_leaves` so drift in future releases is visible.
"""
from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from loci.sources.base import POIRecord, SourceAdapter

# west, south, east, north — same NYC bbox as the Overture adapter
BBOX = (-74.3, 40.4, -73.6, 41.0)
RELEASE = os.environ.get("LOCI_FSQ_RELEASE", "2026-08-11")
HF_GLOB = f"hf://datasets/foursquare/fsq-os-places/release/dt={RELEASE}/places/parquet/*.parquet"
CACHE_PATH = Path("data/raw/fsq_places_nyc.parquet")
# Freshness gate. Measured 2026-09-02 against the other five sources: rows last
# refreshed before 2019 are corroborated <10% of the time, 2024 → 29%, 2025 →
# 38%, 2026 → 55%. Check-in venues that closed are rarely marked closed; they
# just stop being refreshed. Anything older than this is treated as a ghost.
MIN_REFRESHED = os.environ.get("LOCI_FSQ_MIN_REFRESHED", "2024-01-01")

# Mapping, built from the actual 2026-08-11 taxonomy (1,279 categories).
# Two mechanisms:
#  1. GROUP prefixes — Foursquare nests every cuisine under
#     "Dining and Drinking > Restaurant > …" (~300 leaves), every bar type under
#     "… > Bar > …", every coffee place under "… > Cafe, Coffee, and Tea House > …".
#     Matching the path prefix is exact and needs no enumeration.
#  2. LEAF labels for everything else, matched on the last path segment.
# Deliberately DROPPED: "Deli" (a Restaurant leaf in Foursquare; in NYC it is
# usually a bodega — SNAP anchors those, DOHMH anchors restaurants, so mapping it
# either way double-counts), "Retail > Market" (generic), "Fish Market",
# contractor leaves under "Home Improvement Service", specialist physicians.
GROUP_CATEGORY: dict[str, str] = {
    "dining and drinking > restaurant": "restaurant",
    "dining and drinking > bar": "bar",
    "dining and drinking > cafe, coffee, and tea house": "cafe_bakery",
}
DROP_LEAVES = {"deli", "atm"}   # any label with one of these leaves disqualifies the record
LEAF_CATEGORY: dict[str, str] = {
    # grocery
    "grocery store": "grocery", "organic grocery": "grocery", "supermarket": "grocery",
    "farmers market": "grocery",
    # convenience
    "convenience store": "convenience",
    # pharmacy
    "pharmacy": "pharmacy", "drugstore": "pharmacy",
    # laundry
    "laundromat": "laundry", "laundry service": "laundry", "dry cleaner": "laundry",
    # hair_barber
    "hair salon": "hair_barber", "barbershop": "hair_barber",
    # nails_beauty (same breadth as Overture: nails, spa, brow, hair removal)
    "nail salon": "nails_beauty", "spa": "nails_beauty", "brow bar": "nails_beauty",
    "hair removal service": "nails_beauty",
    # tailor_repair
    "tailor": "tailor_repair", "shoe repair service": "tailor_repair",
    # cafe_bakery leaves outside the cafe group
    "bakery": "cafe_bakery", "bagel shop": "cafe_bakery",
    # childcare
    "child care service": "childcare", "daycare": "childcare", "preschool": "childcare",
    "nursery school": "childcare",
    # clinic — walk-in and general-practice only. "Doctor's Office" (23k rows in
    # NYC, mostly solo specialists) and bare "Physician" are DROPPED: mapping them
    # would quintuple the category and erase clinic gaps for the wrong reason.
    "urgent care center": "clinic", "medical center": "clinic", "healthcare clinic": "clinic",
    "family medicine doctor": "clinic", "internal medicine doctor": "clinic", "pediatrician": "clinic",
    # fitness — public gyms and studios; hotel/college/outdoor gyms are not
    "gym and studio": "fitness", "gym": "fitness", "yoga studio": "fitness",
    "pilates studio": "fitness", "boxing gym": "fitness", "climbing gym": "fitness",
    "cycle studio": "fitness", "martial arts dojo": "fitness", "gymnastics center": "fitness",
    # bank
    "bank": "bank", "credit union": "bank",
    # hardware ("Home Improvement Service" is contractors, not a store)
    "hardware store": "hardware",
}


def _as_date(v) -> dt.date | None:
    """Foursquare ships dates as 'YYYY-MM-DD' strings; tolerate real dates too."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def map_leaf(labels) -> str | None:
    """Map a Foursquare `fsq_category_labels` value (list of 'A > B > C' strings)
    onto a Loci slug: group prefix first, then leaf label. First hit wins."""
    if not labels:
        return None
    if isinstance(labels, str):
        labels = [labels]
    if any((p or "").split(">")[-1].strip().lower() in DROP_LEAVES for p in labels):
        return None
    for path in labels:
        low = (path or "").strip().lower()
        leaf = low.split(">")[-1].strip()
        for prefix, slug in GROUP_CATEGORY.items():
            if low == prefix or low.startswith(prefix + " >"):
                return slug
        if leaf in LEAF_CATEGORY:
            return LEAF_CATEGORY[leaf]
    return None


class FoursquarePlacesAdapter(SourceAdapter):
    source_id = "foursquare_os_places"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        self._ensure_cache()
        import duckdb
        con = duckdb.connect()
        q = ("SELECT fsq_place_id, name, fsq_category_labels, latitude, longitude, "
             "date_created, date_refreshed, date_closed FROM read_parquet(?)")
        params: list = [str(CACHE_PATH)]
        if limit is not None:
            q += " LIMIT ?"; params.append(limit)
        try:
            cur = con.execute(q, params)
            while True:
                rows = cur.fetchmany(10_000)
                if not rows:
                    break
                for r in rows:
                    yield {"id": r[0], "name": r[1], "labels": r[2], "lat": r[3], "lon": r[4],
                           "created": r[5], "refreshed": r[6], "closed": r[7]}
        finally:
            con.close()

    def _ensure_cache(self) -> None:
        if CACHE_PATH.exists() and CACHE_PATH.stat().st_size > 0:
            return
        token = os.environ.get("HF_TOKEN")
        if not token:
            raise RuntimeError(
                "Foursquare OS Places is gated. Accept the terms at "
                "https://huggingface.co/datasets/foursquare/fsq-os-places, create a read token, "
                "set HF_TOKEN, and re-run; the NYC extract is cached once at "
                f"{CACHE_PATH}.")
        import duckdb
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("CREATE SECRET hf (TYPE HUGGINGFACE, TOKEN ?)", [token])
        w, s, e, n = BBOX
        con.execute(f"""
            COPY (SELECT fsq_place_id, name, fsq_category_labels, latitude, longitude,
                         date_created, date_refreshed, date_closed, address, locality, postcode
                  FROM read_parquet('{HF_GLOB}')
                  WHERE latitude BETWEEN {s} AND {n} AND longitude BETWEEN {w} AND {e}
                    AND date_closed IS NULL)
            TO '{CACHE_PATH}' (FORMAT PARQUET)""")
        con.close()

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        today = dt.date.today()
        seen: set[str] = set()
        unmapped: dict[str, int] = {}
        self.dropped_stale = 0
        for r in rows:
            rid = r.get("id")
            lat, lon = r.get("lat"), r.get("lon")
            if not rid or rid in seen or lat is None or lon is None:
                continue
            if r.get("closed"):
                continue
            refreshed = _as_date(r.get("refreshed"))
            if refreshed is None or refreshed < dt.date.fromisoformat(MIN_REFRESHED):
                self.dropped_stale += 1
                continue
            category = map_leaf(r.get("labels"))
            if category is None:
                for path in (r.get("labels") or []):
                    leaf = (path or "").split(">")[-1].strip().lower()
                    unmapped[leaf] = unmapped.get(leaf, 0) + 1
                continue
            seen.add(rid)
            opened = _as_date(r.get("created"))
            yield POIRecord(
                source_id=self.source_id, source_record_id=str(rid), category=category,
                name=(r.get("name") or "").strip() or None,
                lon=float(lon), lat=float(lat), observed_on=today, opened_on=opened,
                confidence=0.6,   # check-in-derived; third opinion, never the anchor
                attrs={"labels": list(r.get("labels") or []),
                       "refreshed": str(r.get("refreshed") or "")[:10] or None},
            )
        self.unmapped_leaves = dict(sorted(unmapped.items(), key=lambda kv: -kv[1])[:40])
