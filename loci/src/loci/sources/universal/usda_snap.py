"""USDA SNAP Retailer Locator — ANCHOR for grocery and convenience.

Every store authorized to accept SNAP, nationally, served as an ArcGIS feature
service with lat/lon on every row. Store_Type is USDA's stocking-breadth
classification, which happens to be a decent proxy for the bundle's
grocery-vs-bodega distinction:

    Supermarket, Super Store, Grocery Store  -> grocery
    Convenience Store                        -> convenience
    Specialty Store, Farmers and Markets,
    Restaurant Meals Program, Other          -> dropped (not a daily-needs storefront
                                                in the bundle's sense; farmers markets
                                                are seasonal, RMP are restaurants)

Bias, stated: this is a near-census of stores that ACCEPT SNAP. Stores that do
not are missing, and those skew toward affluent areas — the opposite direction
from OSM's undercount of low-income neighborhoods. That opposition is what makes
it useful as a second calibration curve for the coverage-bias check (§7.1).

Universal-tier: scoped by a bounding box, like the OSM adapter. Verified
2026-09-02: 16,624 NY rows, 8,052 in the five boroughs, maxRecordCount 1,000.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

SERVICE = ("https://services1.arcgis.com/RLQu0rK7h4kbsBq5/arcgis/rest/services/"
           "snap_retailer_location_data/FeatureServer/0/query")
PAGE = 1_000
# (min_lat, min_lon, max_lat, max_lon) — same convention as osm_overpass.BBOX
BBOX = (40.4, -74.3, 41.0, -73.6)

STORE_TYPE_MAP = {
    "Supermarket": "grocery",
    "Super Store": "grocery",
    "Grocery Store": "grocery",
    "Convenience Store": "convenience",
}
FIELDS = "Record_ID,Store_Name,Store_Type,Latitude,Longitude,County,City,Zip_Code"


class UsdaSnapAdapter(SourceAdapter):
    source_id = "usda_snap_retailers"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        min_lat, min_lon, max_lat, max_lon = BBOX
        base = {
            "where": "1=1",
            "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": FIELDS,
            "returnGeometry": "false",
            "orderByFields": "Record_ID",
            "f": "json",
        }
        offset, seen = 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            resp = session.get(SERVICE, params={**base, "resultOffset": offset,
                                                "resultRecordCount": page}, timeout=120)
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                raise RuntimeError(f"ArcGIS error: {body['error']}")
            feats = body.get("features", [])
            if not feats:
                break
            for f in feats:
                yield f["attributes"]
            seen += len(feats)
            offset += len(feats)
            if not body.get("exceededTransferLimit") or (limit is not None and seen >= limit):
                break

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        today = dt.date.today()
        seen: set[str] = set()
        for r in rows:
            category = STORE_TYPE_MAP.get(r.get("Store_Type") or "")
            rid = r.get("Record_ID")
            lat, lon = r.get("Latitude"), r.get("Longitude")
            if category is None or rid is None or lat is None or lon is None:
                continue
            rid = str(rid)
            if rid in seen:
                continue
            seen.add(rid)
            yield POIRecord(
                source_id=self.source_id,
                source_record_id=rid,
                category=category,
                name=(r.get("Store_Name") or "").strip().title() or None,
                lon=float(lon), lat=float(lat),
                observed_on=today,
                confidence=0.9,   # near-census within SNAP-accepting stores
                attrs={"store_type": r.get("Store_Type"), "county": r.get("County"),
                       "city": r.get("City"), "zip": r.get("Zip_Code")},
            )
