"""Export the MapLibre webmap's two point layers from the database.

Replaces the ad-hoc scratchpad script that produced `webmap/gap_buildings.json`
(commit e1784b6) -- per the repo standard, loose scripts become CLI
subcommands: `loci export-webmap`.

TWO LAYERS, ONE CATEGORY FILTER. The map answers one question -- "where is
business X missing, and where does X actually exist?" -- so both layers are
sliced the same way:

  gaps/<category>.json   addresses from `analysis.address_gaps` whose
                         `<category>_ratio > 1` (the model's own definition of
                         a missing category: see model/address_gaps.py, D41),
                         restricted to eligible addresses.
  pois/<category>.json   every canonical business location for that category,
                         read through `analysis.poi_supply` (sql/003 + sql/006).

THE MAP MUST SHOW THE SUPPLY THE GAPS WERE MEASURED AGAINST (D52). Until this
module read `analysis.poi_dedup.is_canonical` directly, so the map drew 100,213
"known locations" for MN+BK while `analysis.address_gaps` had been computed
against the PRINCIPLED supply set. The owner's whole validation move -- eyeball
a gap next to the laundromats around it -- was therefore being made against a
supply the model never saw. Both layers now come from one place:
`analysis.poi_supply`, filtered by `score/supply.supply_predicate(...)`, the
same function `model/address_gaps.py` uses. `--supply-set` selects the set and
is CHECKED against the `supply_set` recorded in address_gaps provenance; a
disagreement is printed loudly and written into meta.json rather than silently
producing a map whose two layers disagree.

EXCLUDED POINTS ARE EXPORTED, NOT DELETED. A record the set drops -- under
PRINCIPLED, a lone aggregator record in an anchored category, with no licence
and no second feed -- still ships in the same file, flagged `in_set = 0`, and
the UI draws it as a grey x it can toggle on. D52 removes ~81k MN+BK records
citywide; a filter that large has to be inspectable by eye, and a supply
decision the owner cannot see is a supply decision he cannot overrule. The
sidebar/legend "known locations" count is the IN-SET count only, so the number
on screen is the number the gaps were measured against.

Per-category files, not one big file: the UI only ever draws one category at a
time, so the browser should only ever fetch one category. The largest single
file (Brooklyn laundry gaps) is ~1 MB uncompressed and the server gzips it;
nothing here needs a tile pipeline.

CORROBORATION (CHECKPOINT D47). D47 found that single-source POI records
inflate apparent supply -- an uncorroborated Overture row can erase a real gap.
`analysis.poi_dedup` records source membership only as `cluster_id`, so the
flag is derived: a cluster backed by 2+ DISTINCT `staging.poi.source_id` values
is corroborated. Two rows from the SAME source in one cluster are NOT
corroboration -- that is one source double-listing a place, which is exactly
the failure mode dedup exists to collapse. The UI draws single-source points
hollow so the owner can see, per point, whether the supply that closes a gap is
actually attested twice.

RESTAURANT DETAIL. DOHMH's inspection file is the only source here with
per-record attributes worth showing (cuisine, letter grade, inspection date,
and a derived active flag), and it covers exactly two categories -- restaurant
and cafe_bakery -- so `DETAIL_CATS` is READ FROM THE DB rather than hardcoded:
if DOHMH ever stops covering cafes, the export follows without an edit. Detail
is attached per dedup CLUSTER: a canonical Overture row and the DOHMH row that
dedup collapsed into it are the same restaurant, so the grade belongs to the
canonical point. Where a cluster has several DOHMH members the most recently
inspected one wins. Where it has none the DOHMH fields stay null and cuisine
falls back to Overture's `primary_category` / Foursquare's `labels` leaf,
LABELLED WITH ITS SOURCE -- an Overture "pizza_restaurant" is a taxonomy
string, not a health-department cuisine code, and the popup says so.

The detail rides in dictionary-encoded parallel arrays (`layer["detail"]`,
indexed by point) rather than per-feature objects: restaurant.json holds 40k
points, and a repeated `{"cuisine": "Coffee/Tea", ...}` per point would roughly
triple the file. Only DETAIL_CATS files carry a `detail` block at all, so the
other thirteen categories are byte-identical to before.

ALCOHOL OVERLAY (owner decision 2026-09-08). A THIRD file,
`alcohol.json`, holds every active NYS SLA licence in the exported boroughs,
classified on-premises / off-premises-liquor / off-premises-beer / other /
unknown by sources/cities/nyc/alcohol_licences.yaml. It is deliberately
separate from both layers above and from all 15 categories: the overlay
answers "where is alcohol licensed?", not "what is missing?", and 8,253 of
those NYC licences are restaurants DOHMH already anchors. Mixing it into a
category file would double-count supply. The table it reads
(`staging.alcohol_licences`, sql/007) is OPTIONAL -- an export run before
`loci ingest-alcohol` writes an empty layer and says so, rather than failing
the whole export.

BOROUGH. `analysis.address_gaps.borough` carries two-letter codes ("MN");
`analysis.hex.borough` carries full names ("Manhattan"). POIs have no borough
column at all, so they are labelled the same way the address layer labels
`nta_code`: H3 res-9 cell -> `analysis.hex`. `BOROUGH_NAMES` below is the only
bridge between the two vocabularies.
"""
from __future__ import annotations

import datetime
import json
import pathlib

from loci.categories import CATEGORIES
from loci.reach import load_reach
from loci.score.supply import DEFAULT_SUPPLY_SET, SUPPLY_SETS, supply_predicate

ALLCATS: list[str] = list(CATEGORIES)

# The only NYC-specific table in this module. address_gaps speaks codes,
# analysis.hex speaks names; the CLI takes codes.
BOROUGH_NAMES = {"MN": "Manhattan", "BX": "Bronx", "BK": "Brooklyn",
                 "QN": "Queens", "SI": "Staten Island"}

# Same palette the hex exporter and index.html already use -- kept in sync by
# hand in exactly these two places (viz/export_webmap.py and here).
COLORS = {"hardware": "#b5541f", "convenience": "#2f7d5c", "clinic": "#3d6fb4",
          "fitness": "#c69a1e", "childcare": "#9350a6", "laundry": "#1f9aa1",
          "pharmacy": "#cc4b63", "hair_barber": "#6d8b3a", "cafe_bakery": "#8a6d4b",
          "grocery": "#417a2f", "nails_beauty": "#b3689a", "bar": "#7a5cc0",
          "bank": "#4a7a8c", "tailor_repair": "#996a3a", "restaurant": "#a8443c"}

H3_RES = 9
COORD_DP = 5  # ~1 m at NYC latitude; halves the JSON size vs full float repr

# The alcohol overlay's own table and its draw order (legend order too). The
# classification vocabulary and its labels live with the adapter that produces
# them, so the map legend cannot drift from the ingest.
ALCOHOL_TABLE = ("staging", "alcohol_licences")

# DOHMH is the detail source; the two cuisine-ish fallbacks each store their
# taxonomy under a different attrs key, so the extraction is per source.
DOHMH_SOURCE = "nyc_dohmh_restaurants"
CUISINE_FALLBACK = {  # source_id -> JSON path, in preference order
    "overture_places": "$.primary_category",
    "foursquare_os_places": "$.labels[0]",
}


# ------------------------------------------------------------------ queries

def detail_cats(con) -> list[str]:
    """The categories DOHMH actually covers, read from the data (restaurant +
    cafe_bakery today). Only these get a `detail` block."""
    rows = con.execute(
        "SELECT DISTINCT category FROM staging.poi WHERE source_id = ?",
        [DOHMH_SOURCE]).fetchall()
    return [c for c in ALLCATS if c in {r[0] for r in rows}]


def _poi_sql(boroughs: list[str], dcats: list[str],
             supply_set: str = DEFAULT_SUPPLY_SET) -> tuple[str, list]:
    """Canonical POIs in `boroughs` (two-letter codes) with a derived source
    list. `list_sort(list(DISTINCT ...))` gives a stable source ordering so a
    re-export of unchanged data is byte-identical.

    Rows come from `analysis.poi_supply` (which already filters
    `is_canonical`), and the named supply set rides along as `in_set` rather
    than being applied as a WHERE clause: the excluded points are drawn as
    their own class, so the export needs them. `supply_predicate` is the same
    function model/address_gaps.py uses, so the map and the model cannot drift
    apart over what "a business exists here" means.

    The two detail CTEs are restricted to `dcats` on purpose: every Overture
    row has a `primary_category`, so an unrestricted cuisine fallback would
    hang "Grocery Store" off every grocery point and bloat all 15 files.
    """
    pred = supply_predicate(supply_set)
    names = [BOROUGH_NAMES[b] for b in boroughs]
    placeholders = ", ".join("?" for _ in names)
    dcat_ph = ", ".join("?" for _ in dcats) or "NULL"
    fb_when = "\n".join(
        f"WHEN '{sid}' THEN json_extract_string(p.attrs, '{path}')"
        for sid, path in CUISINE_FALLBACK.items())
    fb_rank = "\n".join(
        f"WHEN '{sid}' THEN {i}" for i, sid in enumerate(CUISINE_FALLBACK))
    sql = f"""
        WITH src AS (
            SELECT d.cluster_id,
                   list_sort(list(DISTINCT p.source_id)) AS sources
            FROM analysis.poi_dedup d
            JOIN staging.poi p ON p.poi_id = d.poi_id
            GROUP BY 1
        ),
        dohmh AS (
            SELECT * EXCLUDE (rn) FROM (
                SELECT d.cluster_id,
                       p.source_record_id AS camis,
                       json_extract_string(p.attrs, '$.cuisine') AS cuisine,
                       json_extract_string(p.attrs, '$.grade') AS grade,
                       json_extract_string(p.attrs, '$.grade_date') AS grade_date,
                       json_extract_string(p.attrs, '$.last_inspection_date') AS inspected_on,
                       json_extract_string(p.attrs, '$.active') AS active,
                       json_extract_string(p.attrs, '$.active_basis') AS active_basis,
                       row_number() OVER (
                           PARTITION BY d.cluster_id
                           ORDER BY json_extract_string(p.attrs, '$.last_inspection_date')
                                    DESC NULLS LAST, p.source_record_id) AS rn
                FROM analysis.poi_dedup d
                JOIN staging.poi p ON p.poi_id = d.poi_id
                WHERE p.source_id = '{DOHMH_SOURCE}'
                  AND d.category IN ({dcat_ph})
            ) WHERE rn = 1
        ),
        fb AS (
            SELECT * EXCLUDE (rn) FROM (
                SELECT cluster_id, fb_cuisine, fb_source,
                       row_number() OVER (PARTITION BY cluster_id
                                          ORDER BY pref, poi_id) AS rn
                FROM (
                    SELECT d.cluster_id, p.poi_id, p.source_id AS fb_source,
                           CASE p.source_id
                               {fb_when}
                           END AS fb_cuisine,
                           CASE p.source_id
                               {fb_rank}
                           END AS pref
                    FROM analysis.poi_dedup d
                    JOIN staging.poi p ON p.poi_id = d.poi_id
                    WHERE d.category IN ({dcat_ph})
                )
                WHERE fb_cuisine IS NOT NULL
            ) WHERE rn = 1
        )
        SELECT v.poi_id,
               v.category,
               v.name,
               round(ST_X(v.geom), {COORD_DP}) AS lon,
               round(ST_Y(v.geom), {COORD_DP}) AS lat,
               h.borough AS borough_name,
               s.sources,
               dh.camis, dh.cuisine, dh.grade, dh.grade_date, dh.inspected_on,
               dh.active, dh.active_basis,
               f.fb_cuisine, f.fb_source,
               v.{pred} AS in_set
        FROM analysis.poi_supply v
        JOIN src s ON s.cluster_id = v.cluster_id
        LEFT JOIN dohmh dh ON dh.cluster_id = v.cluster_id
        LEFT JOIN fb f ON f.cluster_id = v.cluster_id
        JOIN analysis.hex h
          ON h.h3_index = h3_latlng_to_cell_string(ST_Y(v.geom), ST_X(v.geom), {H3_RES})
        WHERE h.borough IN ({placeholders})
          AND v.category IN ({", ".join("?" for _ in ALLCATS)})
        ORDER BY v.category, v.poi_id
    """
    return sql, list(dcats) + list(dcats) + names + ALLCATS


def _gap_sql(cat: str, boroughs: list[str]) -> tuple[str, list]:
    """Eligible addresses whose `cat` is beyond its reach tier (ratio > 1) --
    model/address_gaps.py's own `n_missing` definition, one category at a
    time."""
    placeholders = ", ".join("?" for _ in boroughs)
    sql = f"""
        SELECT address_id,
               round(lon, {COORD_DP}) AS lon,
               round(lat, {COORD_DP}) AS lat,
               borough,
               units_capped,
               {cat}_ratio AS ratio,
               {cat}_nearest_m AS nearest_m,
               neighborhood
        FROM analysis.address_gaps
        WHERE eligible
          AND borough IN ({placeholders})
          AND {cat}_ratio > 1
        ORDER BY address_id
    """
    return sql, list(boroughs)


# ------------------------------------------------------------------ packing

def normalize_cuisine(value: str | None, source: str) -> str | None:
    """Reduce a fallback taxonomy string to something that reads like a
    cuisine, so it can share a dropdown with DOHMH's vocabulary.

    Overture: `pizza_restaurant` -> `Pizza`. Foursquare:
    `Dining and Drinking > Restaurant > Indian Restaurant` -> `Indian`.
    A bare `restaurant` / `Restaurant` carries no cuisine and becomes None --
    better an honest blank than a category named after itself.
    """
    if value is None or source == DOHMH_SOURCE:
        return value or None
    text = value.split(">")[-1].strip().replace("_", " ")
    for tail in (" restaurant", " place", " shop", " store"):
        if text.lower().endswith(tail):
            text = text[: -len(tail)]
    text = text.strip()
    if not text or text.lower() in {"restaurant", "dining and drinking", "food and beverage"}:
        return None
    return text.title() if text.islower() else text


class _Vocab:
    """Dictionary encoder: a repeated string becomes one small integer."""

    def __init__(self) -> None:
        self.items: list[str] = []
        self._idx: dict[str, int] = {}

    def index(self, value: str | None) -> int:
        if value is None or value == "":
            return -1
        i = self._idx.get(value)
        if i is None:
            i = self._idx[value] = len(self.items)
            self.items.append(value)
        return i


def pack_pois(rows, boroughs: list[str], sources: list[str],
              dcats: list[str] | None = None,
              supply_set: str = DEFAULT_SUPPLY_SET) -> dict[str, dict]:
    """rows -> {category: layer dict}. `pts` is a flat array of stride 5:
    lon, lat, borough index, source bitmask, in_set. Names and ids ride in
    parallel arrays so the numeric part stays a dense list of numbers.

    A point is corroborated iff popcount(source bitmask) >= 2 (D47).

    `in_set` is 1 when the point belongs to the named supply set and 0 when it
    was EXCLUDED from it (D52). It is a fifth slot in the same flat array
    rather than a parallel array so there is exactly one place a reader can
    get a point's numbers wrong; the UI reads `layer["stride"]`, never a
    literal 4.

    For `dcats` (the DOHMH-covered categories) each layer also gets `detail`:
    dictionary-encoded parallel arrays, one entry per point, holding cuisine,
    letter grade, grade date, last inspection date, the active flag and its
    basis, and the DOHMH CAMIS id so a point can be traced back to the
    inspection file. `active` is 1/0/-1 -- and -1 (no DOHMH member in the
    cluster) is NOT "inactive": the UI must not hide it as one.
    """
    dcats = list(dcats or [])
    bidx = {b: i for i, b in enumerate(boroughs)}
    sidx = {s: i for i, s in enumerate(sources)}
    out = {c: {"category": c, "label": CATEGORIES[c].label, "stride": 5,
               "supplySet": supply_set, "pts": [], "names": [], "ids": []}
           for c in ALLCATS}
    vocabs = {c: {k: _Vocab() for k in ("cuisine", "grade", "basis", "date", "src")}
              for c in dcats}
    for c in dcats:
        out[c]["detail"] = {k: [] for k in ("cuisine", "cuisineSrc", "grade",
                                            "gradeDate", "inspected", "active",
                                            "basis", "camis")}
    for (poi_id, cat, name, lon, lat, boro_name, srcs, camis, cuisine, grade,
         grade_date, inspected_on, active, active_basis, fb_cuisine, fb_source,
         in_set) in rows:
        layer = out.get(cat)
        if layer is None or lon is None or lat is None:
            continue
        code = _code_for(boro_name)
        if code not in bidx:
            continue
        mask = 0
        for s in srcs or []:
            mask |= 1 << sidx[s]
        layer["pts"].extend([lon, lat, bidx[code], mask, int(bool(in_set))])
        layer["names"].append(name or "")
        layer["ids"].append(poi_id)
        if cat not in vocabs:
            continue
        v, det = vocabs[cat], layer["detail"]
        # DOHMH's cuisine code wins; the taxonomy fallback fills the blanks and
        # is always labelled with the source it came from.
        cui_src = DOHMH_SOURCE if cuisine else (fb_source if fb_cuisine else None)
        cui = normalize_cuisine(cuisine or fb_cuisine, cui_src or DOHMH_SOURCE)
        det["cuisine"].append(v["cuisine"].index(cui))
        det["cuisineSrc"].append(v["src"].index(cui_src if cui else None))
        det["grade"].append(v["grade"].index(grade))
        det["gradeDate"].append(v["date"].index(grade_date))
        det["inspected"].append(v["date"].index(inspected_on))
        det["active"].append(-1 if active is None else int(active == "true"))
        det["basis"].append(v["basis"].index(active_basis))
        det["camis"].append(camis or "")
    for cat, v in vocabs.items():
        out[cat]["detail"]["vocab"] = {k: vv.items for k, vv in v.items()}
    for layer in out.values():
        layer["n"] = len(layer["names"])
        flags = layer["pts"][4::5]
        layer["nSet"] = sum(flags)              # the "known locations" count
        layer["nExcluded"] = len(flags) - layer["nSet"]
    return out


def pack_gaps(rows, boroughs: list[str], cat: str) -> dict:
    """rows -> one layer dict. `pts` stride 4: lon, lat, borough index,
    capped units. `ratio` is dropped from the payload deliberately -- the map
    shows presence/absence, and the continuous score is the model's output,
    not the map's."""
    bidx = {b: i for i, b in enumerate(boroughs)}
    pts, ids = [], []
    for address_id, lon, lat, boro, units, _ratio, _nearest, _nta in rows:
        if lon is None or lat is None or boro not in bidx:
            continue
        pts.extend([lon, lat, bidx[boro], round(float(units or 0))])
        ids.append(address_id)
    return {"category": cat, "label": CATEGORIES[cat].label, "stride": 4,
            "pts": pts, "ids": ids, "n": len(ids)}


def _code_for(borough_name: str | None) -> str | None:
    for code, name in BOROUGH_NAMES.items():
        if name == borough_name:
            return code
    return None


def alcohol_vocab() -> tuple[list[str], dict[str, str]]:
    """The overlay's classes and their human labels, read from the adapter's
    yaml. Imported lazily: viz/ must not require the NYC source package at
    import time, so a missing adapter degrades to no overlay, not an
    ImportError in the middle of an export."""
    from loci.sources.cities.nyc.nys_sla import CLASSIFICATIONS, load_classification
    return list(CLASSIFICATIONS), dict(load_classification()["labels"])


def has_alcohol(con) -> bool:
    """staging.alcohol_licences is optional -- `loci ingest-alcohol` may not
    have run yet, and an export must not fail because of that."""
    schema, table = ALCOHOL_TABLE
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, table]).fetchone()[0])


def _alcohol_sql(boroughs: list[str]) -> tuple[str, list]:
    """Active licences only, in `boroughs` (two-letter codes). The table
    already stores the borough code, so unlike the POI layer this needs no H3
    join -- SLA publishes the county on every row."""
    ph = ", ".join("?" for _ in boroughs)
    sql = f"""
        SELECT licence_id, classification, description, name, address,
               borough,
               round(ST_X(geom), {COORD_DP}) AS lon,
               round(ST_Y(geom), {COORD_DP}) AS lat,
               CAST(expires_on AS VARCHAR) AS expires
        FROM {'.'.join(ALCOHOL_TABLE)}
        WHERE active AND borough IN ({ph})
        ORDER BY licence_id
    """
    return sql, list(boroughs)


def pack_alcohol(rows, boroughs: list[str], classes: list[str],
                 labels: dict[str, str]) -> dict:
    """rows -> one overlay layer. `pts` is stride 4: lon, lat, class index,
    borough index. Name, address, description and expiry ride in parallel
    arrays; description and expiry are dictionary-encoded (55 licence types
    and a few hundred distinct dates across ~15k points) while name and
    address are nearly unique per row and stay literal.

    A row whose classification is not in `classes` is counted as `unknown`
    rather than dropped -- an unmapped licence type must be visible on the map,
    not silently absent from it.
    """
    cidx = {c: i for i, c in enumerate(classes)}
    bidx = {b: i for i, b in enumerate(boroughs)}
    unknown = cidx.get("unknown", len(classes) - 1)
    desc_v, exp_v = _Vocab(), _Vocab()
    pts, names, addrs, descs, exps, ids = [], [], [], [], [], []
    counts = {c: {b: 0 for b in boroughs} for c in classes}
    for licence_id, cls, desc, name, addr, boro, lon, lat, expires in rows:
        if lon is None or lat is None or boro not in bidx:
            continue
        ci = cidx.get(cls, unknown)
        pts.extend([lon, lat, ci, bidx[boro]])
        names.append(name or "")
        addrs.append(addr or "")
        descs.append(desc_v.index(desc))
        exps.append(exp_v.index(expires))
        ids.append(licence_id)
        counts[classes[ci]][boro] += 1
    return {"stride": 4, "pts": pts, "names": names, "addr": addrs,
            "desc": descs, "expires": exps, "ids": ids,
            "vocab": {"desc": desc_v.items, "expires": exp_v.items},
            "classes": classes, "classLabels": [labels.get(c, c) for c in classes],
            "boroughs": boroughs, "counts": counts, "n": len(ids)}


def empty_alcohol(boroughs: list[str]) -> dict:
    """The shape `pack_alcohol` returns, with nothing in it -- what an export
    writes when the ingest has not been run. The UI can then say "not loaded"
    instead of 404ing."""
    try:
        classes, labels = alcohol_vocab()
    except Exception:                     # adapter or yaml unavailable
        classes, labels = ["unknown"], {"unknown": "Unclassified"}
    return pack_alcohol([], boroughs, classes, labels)


def collect_alcohol(con, boroughs: list[str]) -> dict:
    """Read the alcohol overlay. Pure read, and never raises for a missing
    table -- see `has_alcohol`."""
    if not has_alcohol(con):
        layer = empty_alcohol(boroughs)
        layer["available"] = False
        return layer
    classes, labels = alcohol_vocab()
    sql, params = _alcohol_sql(boroughs)
    layer = pack_alcohol(con.execute(sql, params).fetchall(), boroughs, classes, labels)
    layer["available"] = True
    return layer


# ------------------------------------------------------------------- export

def gap_provenance(con, boroughs: list[str]) -> dict:
    """The supply set the EXPORTED gap rows were actually measured against,
    read from `analysis.address_gaps.supply_set/supply_hash` (sql/006).

    Restricted to the exported boroughs on purpose: the citywide table can hold
    pre-D52 NULL rows for boroughs this map never draws, and those must not
    raise a false alarm about the two it does.

    Returns supply_set/supply_hash of the DOMINANT variant plus every variant
    seen, and never raises: a database whose address_gaps predates the D52
    columns reports `supply_set=None`, which is itself the finding.
    """
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'address_gaps'").fetchall()}
    if not {"supply_set", "supply_hash"} <= cols:
        return {"supply_set": None, "supply_hash": None, "variants": [], "mixed": False}
    ph = ", ".join("?" for _ in boroughs)
    rows = con.execute(
        f"""SELECT supply_set, supply_hash, count(*) AS n
            FROM analysis.address_gaps
            WHERE borough IN ({ph})
            GROUP BY 1, 2 ORDER BY n DESC, 1, 2""", list(boroughs)).fetchall()
    variants = [{"supply_set": s, "supply_hash": h, "n": int(n)} for s, h, n in rows]
    top = variants[0] if variants else {"supply_set": None, "supply_hash": None}
    return {"supply_set": top["supply_set"], "supply_hash": top["supply_hash"],
            "variants": variants, "mixed": len(variants) > 1}


def supply_warning(supply_set: str, prov: dict) -> str | None:
    """None when the export's supply set matches what the gaps were measured
    against; otherwise the sentence to shout in the terminal AND to carry in
    meta.json so the map itself says it.

    This is the whole point of the D52 fix: a map whose gap layer was measured
    against one supply and whose known-location layer draws another is not a
    validation surface, it is a way to talk yourself out of a real gap."""
    got = prov.get("supply_set")
    if prov.get("mixed"):
        seen = ", ".join(f"{v['supply_set'] or 'unrecorded'} ({v['n']:,} rows)"
                         for v in prov["variants"])
        return (f"MIXED SUPPLY PROVENANCE: analysis.address_gaps holds more than one "
                f"supply set for these boroughs -- {seen}. The gap layers on this map "
                f"were not all measured against the same supply. Re-run "
                f"`loci address-gaps --supply-set {supply_set}` for every borough here.")
    if got is None:
        return (f"NO SUPPLY PROVENANCE: analysis.address_gaps records no supply_set for "
                f"these boroughs (rows written before D52). This export draws known "
                f"locations from the {supply_set!r} set, but what the gaps were measured "
                f"against is unrecorded -- the two layers may disagree and nothing here "
                f"can tell. Re-run `loci address-gaps --supply-set {supply_set}`.")
    if got != supply_set:
        return (f"SUPPLY-SET MISMATCH: the gaps in analysis.address_gaps were measured "
                f"against {got!r} (supply_hash {prov.get('supply_hash')}), but this export "
                f"draws known locations from {supply_set!r}. Every gap on the map would be "
                f"checked by eye against a supply the model never used. Either export with "
                f"--supply-set {got}, or re-run `loci address-gaps --supply-set {supply_set}`.")
    return None


def collect(con, boroughs: list[str], supply_set: str = DEFAULT_SUPPLY_SET) -> dict:
    """Read both layers out of the database. Pure read -- writes nothing, so
    `--dry-run` and a real export share this one code path and can never
    disagree about the counts."""
    for b in boroughs:
        if b not in BOROUGH_NAMES:
            raise ValueError(f"unknown borough {b!r}; expected one of {sorted(BOROUGH_NAMES)}")
    supply_predicate(supply_set)      # raises on a typo, before any query runs

    sources = [r[0] for r in con.execute(
        "SELECT DISTINCT source_id FROM staging.poi ORDER BY 1").fetchall()]
    dcats = detail_cats(con)
    sql, params = _poi_sql(boroughs, dcats, supply_set)
    poi_layers = pack_pois(con.execute(sql, params).fetchall(), boroughs, sources,
                           dcats, supply_set)

    gap_layers = {}
    for cat in ALLCATS:
        sql, params = _gap_sql(cat, boroughs)
        gap_layers[cat] = pack_gaps(con.execute(sql, params).fetchall(), boroughs, cat)

    # Navigation bounds, derived from the addresses themselves rather than a
    # separate boundary file -- a neighborhood the export cannot show is a
    # neighborhood the picker must not offer.
    ph = ", ".join("?" for _ in boroughs)
    nbhd = [
        {"name": n, "boro": b, "bounds": [round(v, COORD_DP) for v in (x0, y0, x1, y1)]}
        for n, b, x0, y0, x1, y1 in con.execute(
            f"""SELECT neighborhood, borough, min(lon), min(lat), max(lon), max(lat)
                FROM analysis.address_gaps
                WHERE borough IN ({ph}) AND neighborhood IS NOT NULL
                GROUP BY 1, 2 ORDER BY 1""", list(boroughs)).fetchall()
    ]
    boro_bounds = {}
    for row in nbhd:
        b = row["boro"]
        cur = boro_bounds.get(b)
        x0, y0, x1, y1 = row["bounds"]
        boro_bounds[b] = [x0, y0, x1, y1] if cur is None else [
            min(cur[0], x0), min(cur[1], y0), max(cur[2], x1), max(cur[3], y1)]

    prov = gap_provenance(con, boroughs)
    return {"boroughs": boroughs, "sources": sources, "detailCats": dcats,
            "pois": poi_layers, "gaps": gap_layers, "neighborhoods": nbhd,
            "boroBounds": boro_bounds, "alcohol": collect_alcohol(con, boroughs),
            "supplySet": supply_set, "supplyProvenance": prov,
            "supplyWarning": supply_warning(supply_set, prov)}


def summarize(bundle: dict) -> dict:
    """Counts per category per borough. This is what `--dry-run` prints and
    what the UI reads out of meta.json.

    `poi` counts ONLY points in the selected supply set -- that is what the
    sidebar calls "known locations", and it has to be the same number the gap
    layer was measured against. The dropped records are counted separately in
    `excluded` rather than as a fourth key inside `poi`, so no reader can add
    them into a supply total by accident."""
    boroughs = bundle["boroughs"]
    poi_counts, gap_counts, exc_counts = {}, {}, {}
    for cat in ALLCATS:
        layer = bundle["pois"][cat]
        det = layer.get("detail")
        stride = layer["stride"]
        per = {b: {"all": 0, "corroborated": 0, "single": 0} for b in boroughs}
        xper = {b: 0 for b in boroughs}
        if det:
            for v in per.values():
                # `graded`/`cuisine` count points with DOHMH detail; `active`
                # counts those DOHMH calls open. Points with no DOHMH member
                # are counted in neither -- unknown is not inactive.
                v.update({"dohmh": 0, "active": 0, "inactive": 0, "cuisine": 0})
        pts = layer["pts"]
        for i in range(0, len(pts), stride):
            b = boroughs[int(pts[i + 2])]
            if not pts[i + 4]:
                xper[b] += 1
                continue
            corroborated = bin(int(pts[i + 3])).count("1") >= 2
            per[b]["all"] += 1
            per[b]["corroborated" if corroborated else "single"] += 1
            if det:
                j = i // stride
                act = det["active"][j]
                per[b]["dohmh"] += int(act != -1)
                per[b]["active"] += int(act == 1)
                per[b]["inactive"] += int(act == 0)
                per[b]["cuisine"] += int(det["cuisine"][j] != -1)
        poi_counts[cat] = per
        exc_counts[cat] = xper
        gpts = bundle["gaps"][cat]["pts"]
        gper = {b: 0 for b in boroughs}
        for i in range(0, len(gpts), 4):
            gper[boroughs[int(gpts[i + 2])]] += 1
        gap_counts[cat] = gper
    return {"poi": poi_counts, "gap": gap_counts, "excluded": exc_counts}


def write(bundle: dict, out_dir: pathlib.Path) -> dict[str, int]:
    """Write meta.json + gaps/<cat>.json + pois/<cat>.json. Returns
    {relative path: bytes} so the caller can report file sizes without
    re-statting."""
    out_dir = pathlib.Path(out_dir)
    (out_dir / "pois").mkdir(parents=True, exist_ok=True)
    (out_dir / "gaps").mkdir(parents=True, exist_ok=True)
    counts = summarize(bundle)
    written: dict[str, int] = {}

    def _dump(rel: str, obj) -> None:
        p = out_dir / rel
        text = json.dumps(obj, separators=(",", ":"))
        p.write_text(text)
        written[rel] = len(text.encode())

    for cat in ALLCATS:
        _dump(f"pois/{cat}.json", bundle["pois"][cat])
        _dump(f"gaps/{cat}.json", bundle["gaps"][cat])

    # Its own file, fetched only when the overlay is switched on.
    alcohol = bundle.get("alcohol") or empty_alcohol(bundle["boroughs"])
    _dump("alcohol.json", alcohol)

    meta = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "boroughs": bundle["boroughs"],
        "boroughNames": {b: BOROUGH_NAMES[b] for b in bundle["boroughs"]},
        "sources": bundle["sources"],
        "detailCats": bundle.get("detailCats", []),
        "detailSource": DOHMH_SOURCE,
        "cats": ALLCATS,
        "catLabels": [CATEGORIES[c].label for c in ALLCATS],
        "colors": {c: COLORS[c] for c in ALLCATS},
        "reach_m": load_reach("tiers"),
        "poiCounts": counts["poi"],
        "gapCounts": counts["gap"],
        "excludedCounts": counts["excluded"],
        # D52 provenance. `set` is what THIS export drew; `gapsSet`/`gapsHash`
        # are what analysis.address_gaps says the gap layer was measured
        # against. `warning` is non-null exactly when the map must say on its
        # own face that its two layers disagree.
        "supply": {
            "set": bundle.get("supplySet", DEFAULT_SUPPLY_SET),
            "sets": sorted(SUPPLY_SETS),
            "gapsSet": (bundle.get("supplyProvenance") or {}).get("supply_set"),
            "gapsHash": (bundle.get("supplyProvenance") or {}).get("supply_hash"),
            "mixed": bool((bundle.get("supplyProvenance") or {}).get("mixed")),
            "warning": bundle.get("supplyWarning"),
        },
        # The overlay's legend and totals. `available` false means
        # `loci ingest-alcohol` has not run -- the UI says so rather than
        # showing a confident zero.
        "alcohol": {"available": bool(alcohol.get("available")),
                    "classes": alcohol["classes"],
                    "classLabels": alcohol["classLabels"],
                    "counts": alcohol["counts"],
                    "n": alcohol["n"]},
        "neighborhoods": bundle["neighborhoods"],
        "boroBounds": bundle["boroBounds"],
    }
    _dump("meta.json", meta)
    return written
