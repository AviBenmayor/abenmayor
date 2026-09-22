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

from loci.sources.base import POIRecord, SourceAdapter, bathhouse_by_name, bathhouse_name_excluded

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
    # bathhouse_sauna (GTM-198) -- "Sports and Recreation > Sauna" and
    # "Health and Beauty Service > Bath House" in the 2026-08-11 taxonomy
    # (65 + 41 NYC rows). "Spa" stays with nails_beauty (narrow slug, owner
    # ruling pending). Known noise in these two leaves: gym sauna rooms
    # ("Sauna at Equinox ..."), condo amenity rooms and the odd contractor --
    # the D52(b) shared-premises problem; MIN_REFRESHED drops most ghosts.
    "sauna": "bathhouse_sauna", "bath house": "bathhouse_sauna",
    # brewery (D137, 2026-09-22) -- real 2026-08-11 taxonomy leaf "Dining and
    # Drinking > Brewery" (387 NYC rows), a TOP-LEVEL leaf under Dining and
    # Drinking, not nested under the Bar group -- verified directly against
    # the live extract, so it is unaffected by GROUP_CATEGORY's "dining and
    # drinking > bar" prefix rule. See the brewery-priority check in
    # map_leaf() below for the ~10% of rows where a Bar/Restaurant label is
    # listed before this leaf in `fsq_category_labels`.
    "brewery": "brewery",
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


def map_leaf(labels, name: str | None = None) -> str | None:
    """Map a Foursquare `fsq_category_labels` value (list of 'A > B > C' strings)
    onto a Loci slug: group prefix first, then leaf label. First hit wins.
    `name` feeds the pinned bathhouse name-term rule (sources/base.py) on the
    "Spa" leaf only: a spa whose name says bathhouse/banya/sauna is the
    bathhouse, not a nail spa."""
    if not labels:
        return None
    if isinstance(labels, str):
        labels = [labels]
    if any((p or "").split(">")[-1].strip().lower() in DROP_LEAVES for p in labels):
        return None
    # brewery PRIORITY CHECK (D137, 2026-09-22), ahead of the per-path loop.
    # `fsq_category_labels` is an UNORDERED-by-relevance list, and a live
    # measurement (2026-09-22) found 40 of 387 NYC rows carrying the leaf
    # "Dining and Drinking > Brewery" list a generic "... > Bar" or
    # "... > Restaurant" label FIRST -- which the per-path loop below would
    # match via GROUP_CATEGORY before ever reaching the brewery leaf,
    # mis-classifying ~10% of breweries as bars/restaurants under plain
    # first-path-wins traversal. Checked across ALL labels, ahead of order,
    # so a brewery is never shadowed by a co-occurring Bar/Restaurant label --
    # consistent with the owner ruling that a taproom (bar-shaped) is still a
    # brewery, not a bar.
    if any(low.split(">")[-1].strip() == "brewery"
           for low in ((p or "").strip().lower() for p in labels)):
        return "brewery"
    for path in labels:
        low = (path or "").strip().lower()
        leaf = low.split(">")[-1].strip()
        for prefix, slug in GROUP_CATEGORY.items():
            if low == prefix or low.startswith(prefix + " >"):
                return slug
        if bathhouse_by_name("foursquare", leaf, name):
            return "bathhouse_sauna"
        if leaf in LEAF_CATEGORY:
            if LEAF_CATEGORY[leaf] == "bathhouse_sauna" and bathhouse_name_excluded(name):
                return None  # gym sauna rooms, studios, contractors on the two leaves
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
        #: (POIRecord, stale_reason, date_refreshed) for every venue the
        #: staleness gate holds back. Populated by normalize(), written by
        #: load(). A LIST rather than a second pass over the parquet: the file
        #: is read once and the gate's decision is made once, so the held-back
        #: set and the loaded set cannot disagree.
        self.stale_records: list[tuple] = []
        for r in rows:
            rid = r.get("id")
            lat, lon = r.get("lat"), r.get("lon")
            if not rid or rid in seen or lat is None or lon is None:
                continue
            if r.get("closed"):
                continue
            refreshed = _as_date(r.get("refreshed"))
            category = map_leaf(r.get("labels"), r.get("name"))
            if category is None:
                for path in (r.get("labels") or []):
                    leaf = (path or "").split(">")[-1].strip().lower()
                    unmapped[leaf] = unmapped.get(leaf, 0) + 1
                continue
            # THE STALENESS GATE. Unchanged as a SUPPLY rule -- a venue nobody
            # has refreshed since MIN_REFRESHED still does not enter
            # staging.poi, and `poi_is_open` is untouched, so no POI that was
            # counted yesterday is counted differently today. What changed on
            # 2026-09-16 is that the row is no longer THROWN AWAY: it is held
            # in staging.poi_stale (sql/050) with the reason and the freshness
            # stamp, so the 79,182 mapped venues this gate removes are
            # measurable and the promotion is priceable.
            #
            # IT CANNOT SIMPLY BE RETAINED IN staging.poi. Foursquare publishes
            # no status field, so a stale venue there resolves to 'unknown',
            # and the closure gate is `poi_status <> 'closed'` -- 'unknown'
            # survives it and IS counted as supply. Retaining them in place
            # would move the supply hash on the strength of check-in records
            # nobody has touched in three years. That is an owner ruling, not
            # a plumbing change. sql/050's header has the full argument.
            if refreshed is None or refreshed < dt.date.fromisoformat(MIN_REFRESHED):
                self.dropped_stale += 1
                if rid not in seen:
                    self.stale_records.append((
                        POIRecord(
                            source_id=self.source_id, source_record_id=str(rid),
                            category=category,
                            name=(r.get("name") or "").strip() or None,
                            lon=float(lon), lat=float(lat), observed_on=today,
                            opened_on=_as_date(r.get("created")),
                            confidence=0.6,
                            attrs={"labels": list(r.get("labels") or []),
                                   "refreshed": str(r.get("refreshed") or "")[:10] or None}),
                        ("no_refresh_date" if refreshed is None
                         else "refreshed_before_min"),
                        refreshed))
                    seen.add(rid)
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


    def load(self, con, *, limit: int | None = None, dry_run: bool = False,
             table: str = "staging.poi"):
        """The base load(), plus the staleness hold-back written to its own
        table so the gate stops being a data loss.

        The hold-back is written ONLY on the real staging.poi load: staging
        into a holding table is a different operation with a different
        reviewer, and duplicating the stale set into it would make the two
        disagree the moment one is promoted. Idempotent per source, exactly
        like the base method.
        """
        records = super().load(con, limit=limit, dry_run=dry_run, table=table)
        if dry_run or table != "staging.poi":
            return records
        self._write_stale(con)
        return records

    def _write_stale(self, con) -> int:
        import json as _json

        import pandas as pd

        con.execute("DELETE FROM staging.poi_stale WHERE source_id = ?",
                    [self.source_id])
        held = getattr(self, "stale_records", [])
        if not held:
            return 0
        df = pd.DataFrame([{
            "poi_id": r.poi_id, "source_id": r.source_id,
            "source_record_id": r.source_record_id, "category": r.category,
            "tier": r.tier, "name": r.name, "lon": r.lon, "lat": r.lat,
            "observed_on": r.observed_on.isoformat() if r.observed_on else None,
            "opened_on": r.opened_on.isoformat() if r.opened_on else None,
            "closed_on": None, "confidence": r.confidence,
            "attrs": _json.dumps(r.attrs or {}),
            "stale_reason": reason,
            "date_refreshed": refreshed.isoformat() if refreshed else None,
        } for r, reason, refreshed in held])
        con.register("_stale_df", df)
        try:
            con.execute("""
                INSERT INTO staging.poi_stale
                    (poi_id, source_id, source_record_id, category, tier, name,
                     geom, observed_on, opened_on, closed_on, confidence, attrs,
                     stale_reason, date_refreshed, ingested_at)
                SELECT poi_id, source_id, source_record_id, category, tier, name,
                       ST_Point(lon, lat),
                       CAST(observed_on AS DATE), CAST(opened_on AS DATE),
                       CAST(closed_on AS DATE), confidence, CAST(attrs AS JSON),
                       stale_reason, CAST(date_refreshed AS DATE), now()
                FROM _stale_df
            """)
        finally:
            con.unregister("_stale_df")
        return len(df)


# ---------------------------------------------------------------------------
# THE CLOSED PARTITION (GTM: make closures observable)
# ---------------------------------------------------------------------------
# `_ensure_cache` above filters `date_closed IS NULL`. That filter is why the
# 2026-09 retrodiction found ZERO observable closures in 821,397 cached NYC
# rows: the column exists, the fetch threw the rows away. It STAYS as it is --
# the open cache feeds staging.poi and the dedup, and the screen's supply set
# is open businesses only.
#
# This second, SEPARATE extract re-pulls the same release and the same bbox
# with NO open-only filter, into its own directory. Nothing here is ever
# yielded by `fetch()` / `normalize()`, so no closed venue can reach
# staging.poi. The closure ledger (`staging.poi_closure`, sql/027) reads this
# file directly.
CLOSED_DIR = Path("data/raw/foursquare_closed")


def closed_cache_path(release: str = RELEASE) -> Path:
    """The unfiltered NYC extract for a release. Named by release because the
    closed set GROWS between releases and two of them must never be confused."""
    return CLOSED_DIR / f"fsq_places_nyc_all_{release}.parquet"


def ensure_closed_cache(release: str = RELEASE, *, force: bool = False) -> Path:
    """Download the NYC bbox WITHOUT the open-only filter. Fail loud.

    Same download-once pattern as `_ensure_cache`, one difference that matters:
    a partial or empty result RAISES rather than leaving a zero-row parquet on
    disk that a later run would treat as cached. A silent zero here would read
    downstream as "no closures in New York", which is the exact failure the
    retrodiction caught."""
    path = closed_cache_path(release)
    if path.exists() and path.stat().st_size > 0 and not force:
        return path
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "Foursquare OS Places is gated. Accept the terms at "
            "https://huggingface.co/datasets/foursquare/fsq-os-places, create a read "
            "token, set HF_TOKEN, and re-run.")
    import duckdb
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.partial")
    glob = f"hf://datasets/foursquare/fsq-os-places/release/dt={release}/places/parquet/*.parquet"
    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("CREATE SECRET hf (TYPE HUGGINGFACE, TOKEN ?)", [token])
        w, s, e, n = BBOX
        con.execute(f"""
            COPY (SELECT fsq_place_id, name, fsq_category_labels, latitude, longitude,
                         date_created, date_refreshed, date_closed, address, locality, postcode
                  FROM read_parquet('{glob}')
                  WHERE latitude BETWEEN {s} AND {n} AND longitude BETWEEN {w} AND {e})
            TO '{tmp}' (FORMAT PARQUET)""")
        n_rows, n_closed = con.execute(
            "SELECT count(*), count(date_closed) FROM read_parquet(?)", [str(tmp)]).fetchone()
        if not n_rows:
            raise RuntimeError(f"Foursquare release {release} returned 0 NYC rows -- refusing "
                               "to cache an empty extract.")
        if not n_closed:
            raise RuntimeError(
                f"Foursquare release {release} returned {n_rows} NYC rows but 0 with "
                "date_closed. Either the release genuinely publishes no closures or the "
                "open-only filter leaked back in -- refusing to cache, because a zero here "
                "reads downstream as 'no closures in New York'.")
    finally:
        con.close()
    tmp.replace(path)
    return path


def iter_closed(release: str = RELEASE):
    """Yield the CLOSED rows only, normalized to the closure-ledger contract.

    Categories are mapped with the SAME `map_leaf` the open path uses, so a
    closure is counted against a Loci category on exactly the rule that put its
    open neighbours there. Rows that do not map yield `category=None`; the
    ledger keeps them (with the mapping recorded) so the unmapped share is
    visible rather than silently dropped."""
    import duckdb
    path = closed_cache_path(release)
    if not path.exists():
        raise RuntimeError(f"{path} missing -- run `loci poi-closures ingest` first.")
    con = duckdb.connect()
    try:
        cur = con.execute(
            "SELECT fsq_place_id, name, fsq_category_labels, latitude, longitude, "
            "date_created, date_closed, date_refreshed FROM read_parquet(?) "
            "WHERE date_closed IS NOT NULL", [str(path)])
        while True:
            rows = cur.fetchmany(10_000)
            if not rows:
                break
            for r in rows:
                yield {"fsq_place_id": r[0], "name": r[1], "category": map_leaf(r[2], r[1]),
                       "lat": r[3], "lon": r[4], "date_created": _as_date(r[5]),
                       "date_closed": _as_date(r[6]), "date_refreshed": _as_date(r[7])}
    finally:
        con.close()
