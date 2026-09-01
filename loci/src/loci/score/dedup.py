"""Cross-source POI entity resolution (GTM-20).

The same real establishment appears in several sources — a nail salon in
Overture + NYS DOS + OSM, a restaurant in Overture + DOHMH. Counting all of
them inflates the DNCI exactly where source coverage overlaps, and overlap is
geographically biased (denser/richer areas are better covered), so the error is
NOT random — it would bias the residual. Dedup per category before scoring.

Method (CONTEXT.md GTM-20): block candidates by H3 res-11 cell + its neighbors,
then union any pair within 25 m whose normalized names match. Pick one canonical
per cluster by source authority (the near-census anchor wins its category), and
record every row's cluster so counts stay auditable — a survivorship record, not
a destructive delete.

City-agnostic: no NYC column names, consumes only staging.poi.
"""
from __future__ import annotations

import math
import re

import h3

BLOCK_RES = 11          # ~24 m edge; +neighbors covers the 25 m match radius
MATCH_METERS = 40.0

# Source authority per category. The near-census anchor wins where it applies.
FOOD = {"restaurant", "cafe_bakery", "bar"}
SALON = {"hair_barber", "nails_beauty"}


def source_rank(category: str, source_id: str) -> int:
    """Lower = more authoritative (preferred as canonical)."""
    if category in FOOD:
        order = ["nyc_dohmh_restaurants", "overture_places", "osm_overpass"]
    elif category in SALON:
        order = ["nys_dos_appearance_enhancement", "overture_places", "osm_overpass"]
    else:
        order = ["overture_places", "osm_overpass", "nyc_dcwp_licenses"]
    return order.index(source_id) if source_id in order else len(order)


_CORPORATE = {"the", "inc", "llc", "corp", "co", "ltd", "nyc", "ny", "and", "of",
              "company", "group", "ii", "iii", "corporation", "enterprises"}
# Category-generic descriptors — common to many distinct businesses, so they must
# not drive a match. Stripped before comparison; the distinctive name remains.
_GENERIC = {"restaurant", "pizza", "pizzeria", "deli", "delicatessen", "cafe",
            "coffee", "bar", "grill", "grille", "kitchen", "food", "foods",
            "shop", "store", "market", "salon", "nails", "nail", "spa", "beauty",
            "hair", "barber", "barbershop", "laundromat", "laundry", "cleaners",
            "cleaner", "pharmacy", "drugs", "bakery", "bagel", "bagels", "diner",
            "bistro", "grocery", "gourmet", "express", "fried", "chicken",
            "juice", "tea", "sushi", "thai", "chinese", "mexican", "italian"}
_STOP = _CORPORATE | _GENERIC


def norm_tokens(name) -> frozenset[str]:
    if not isinstance(name, str) or not name:
        return frozenset()
    toks = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    return frozenset(t for t in toks if t and t not in _STOP)


def names_match(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    if inter / len(a | b) >= 0.5:               # Jaccard
        return True
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    return len(small) >= 2 and small <= large    # containment of a distinctive name


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class _UF:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def _dedup_category(rows: list[dict]) -> list[tuple[str, int, bool]]:
    """rows: dicts with poi_id, source_id, name, lat, lon, confidence.
    Returns (poi_id, cluster_id, is_canonical)."""
    n = len(rows)
    toks = [norm_tokens(r["name"]) for r in rows]
    cell = [h3.latlng_to_cell(r["lat"], r["lon"], BLOCK_RES) for r in rows]
    by_cell: dict[str, list[int]] = {}
    for i, c in enumerate(cell):
        by_cell.setdefault(c, []).append(i)

    uf = _UF(n)
    for i in range(n):
        cand: list[int] = []
        for c in h3.grid_disk(cell[i], 1):
            cand.extend(by_cell.get(c, ()))
        for j in cand:
            if j <= i:
                continue
            if not names_match(toks[i], toks[j]):
                continue
            if haversine_m(rows[i]["lat"], rows[i]["lon"], rows[j]["lat"], rows[j]["lon"]) <= MATCH_METERS:
                uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    out: list[tuple[str, int, bool]] = []
    for cid, members in enumerate(clusters.values()):
        best = min(members, key=lambda i: (source_rank(rows[i]["category"], rows[i]["source_id"]),
                                           -(rows[i]["confidence"] or 0), rows[i]["poi_id"]))
        for i in members:
            out.append((rows[i]["poi_id"], cid, i == best))
    return out


def build_dedup(con) -> dict:
    cats = [r[0] for r in con.execute(
        "SELECT DISTINCT category FROM staging.poi ORDER BY 1").fetchall()]
    con.execute("DELETE FROM analysis.poi_dedup")
    report: dict[str, tuple[int, int]] = {}
    offset = 0
    for cat in cats:
        rows = con.execute(
            """SELECT poi_id, source_id, name, category, confidence,
                      ST_Y(geom) AS lat, ST_X(geom) AS lon
               FROM staging.poi WHERE category = ?""", [cat]).df().to_dict("records")
        result = _dedup_category(rows)
        # globally-unique cluster ids
        result = [(pid, cid + offset, canon) for pid, cid, canon in result]
        offset = max((cid for _, cid, _ in result), default=offset - 1) + 1
        import pandas as pd
        df = pd.DataFrame(result, columns=["poi_id", "cluster_id", "is_canonical"])
        df["category"] = cat
        con.register("_dd", df)
        con.execute("INSERT INTO analysis.poi_dedup SELECT poi_id, cluster_id, is_canonical, category FROM _dd")
        con.unregister("_dd")
        report[cat] = (len(rows), int(df["is_canonical"].sum()))
    return report
