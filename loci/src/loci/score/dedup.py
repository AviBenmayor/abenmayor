"""Cross-source POI entity resolution (GTM-20).

The same real establishment appears in several sources — a nail salon in
Overture + NYS DOS + OSM, a restaurant in Overture + DOHMH. Counting all of
them inflates the DNCI exactly where source coverage overlaps, and overlap is
geographically biased (denser/richer areas are better covered), so the error is
NOT random — it would bias the residual. Dedup per category before scoring.

Method (CONTEXT.md GTM-20): block candidates by H3 res-11 cell + its neighbors,
then union any pair within MATCH_METERS (40 m) whose normalized names match.
Pick one canonical
per cluster by source authority (the near-census anchor wins its category), and
record every row's cluster so counts stay auditable — a survivorship record, not
a destructive delete.

MATCH_METERS was 40 m against a docstring that said 25 m (drift noted in D36).
Reconciled in favour of the code, and the choice is now measured rather than
asserted: re-running this function at 25 / 40 / 60 / 100 m on the real NYC
staging table changes the canonical count by well under 1% above 40 m --
bar 12,823 / 12,516 / 12,422 / 12,402, nails_beauty 27,637 / 26,930 / 26,752 /
26,702, fitness 10,638 / 10,416 / 10,322 / 10,296. The radius is NOT the
binding constraint on the D47 residual overcount; the NAME rule is. Widening it
further only risks fusing genuinely adjacent storefronts and manufacturing
fake retail gaps, so 40 m stands.

City-agnostic: no NYC column names, consumes only staging.poi.
"""
from __future__ import annotations

import math
import re

import h3

BLOCK_RES = 11          # ~24 m edge; +neighbors covers the 25 m match radius
MATCH_METERS = 40.0

# --------------------------------------------------------------------------
# BOOTH RENTERS: a same-source, same-category, NAME-BLIND proximity collapse.
# --------------------------------------------------------------------------
# D47 ruled out licence staleness as the cause of the nails/hair POI-vs-ZBP
# overcount (nys_dos.py: zero expired licences statewide). The residual is
# this: NYS DOS licenses the BOOTH, not the storefront. New York's
# appearance-enhancement law issues a separate `DOSAERENTER` / `DOSBARRENTER`
# licence to each independent operator who rents a chair or table inside
# someone else's shop, on top of the shop's own `DOSAEBUSINESS` licence. One
# salon with four manicurists is five licences, all geocoded to the same
# storefront. 996 DOS nails licences -- 20% of the category -- sit within ~11 m
# of a DIFFERENTLY-NAMED DOS licence.
#
# The name rule cannot catch these, and that is not a fixable name rule: the
# booth renter's licence is in the RENTER'S OWN NAME ("Jing Li"), which is
# genuinely unrelated to the shop's ("Lucky Nails"). No string comparison
# should match them, and loosening `names_match` until it did would fuse real
# neighbouring storefronts everywhere else.
#
# So the rule is narrow, and every clause of it is load-bearing:
#   SAME SOURCE  -- only within nys_dos_appearance_enhancement. Two different
#                   feeds seeing two names at one address is the ordinary
#                   cross-source case, already handled by name matching;
#                   collapsing that name-blind would erase genuinely distinct
#                   neighbouring businesses that two aggregators both saw.
#   SAME CATEGORY-- guaranteed by construction: _dedup_category runs per
#                   category, so a barbershop and a nail salon in one building
#                   are never fused.
#   15 m         -- well inside MATCH_METERS (40 m). Two licences 15 m apart in
#                   NYC are the same doorway; a typical Brooklyn storefront is
#                   6-8 m wide, so 15 m spans at most two frontages while DOS
#                   geocoding jitter alone is ~11 m. Widening this toward 40 m
#                   would start fusing adjacent salons -- the exact
#                   fake-retail-gap failure the MATCH_METERS note warns about.
#
# MATCH_METERS and cross-source matching are UNCHANGED. This pass only adds
# unions; it never prevents one. A cluster that absorbs a booth renter keeps
# every licence id in analysis.poi_dedup (is_canonical = false), so the licence
# count stays recoverable and this is a survivorship record, not a delete.
#
# CAVEAT THE DATABASE CANNOT ENFORCE: a genuine second salon in the same
# building -- two suites at one address, a mall concourse, a Flushing or
# Sunset Park multi-tenant retail floor -- is indistinguishable from a booth
# renter at this resolution and WILL be collapsed. That undercounts supply in
# exactly the dense immigrant-neighbourhood retail formats where stacked
# storefronts are most common, which is the opposite direction from the
# overcount this fixes. The net effect on the POI/ZBP ratio is the evidence
# for whether the trade is worth it; it is not free.
BOOTH_SOURCES = frozenset({"nys_dos_appearance_enhancement"})
BOOTH_METERS = 15.0

# Source authority per category. The near-census anchor wins where it applies.
FOOD = {"restaurant", "cafe_bakery"}
SALON = {"hair_barber", "nails_beauty"}
SNAP = {"grocery", "convenience"}
# Every list ends with the same tail: the aggregators, most-conflated first.
_TAIL = ["overture_places", "osm_overpass", "foursquare_os_places", "nyc_dcwp_licenses"]


def source_rank(category: str, source_id: str) -> int:
    """Lower = more authoritative (preferred as canonical). The near-census
    anchor wins its category: DOHMH for food, SLA for bars, SNAP for
    grocery/convenience, NYS DOS for salons."""
    if category in FOOD:
        order = ["nyc_dohmh_restaurants"] + _TAIL
    elif category == "bar":
        order = ["nys_sla_liquor_licenses", "nyc_dohmh_restaurants"] + _TAIL
    elif category in SALON:
        order = ["nys_dos_appearance_enhancement"] + _TAIL
    elif category in SNAP:
        order = ["usda_snap_retailers"] + _TAIL
    elif category == "childcare":
        # D65: the DOHMH active child-care roster is a permit registry, so it
        # wins canonical selection over the aggregators exactly as DOHMH
        # restaurants do for food. Without this branch the source falls through
        # to the `else` and scores WORSE than Overture (rank 4 vs 0), which
        # would keep an aggregator's name and geometry for a cluster the
        # registry anchors -- the opposite of what source authority is for.
        order = ["nyc_dohmh_childcare"] + _TAIL
    else:
        order = _TAIL
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


def _name_key(name) -> str:
    """Case/whitespace-folded name for the frequency tiebreak, NaN-safe.

    build_dedup feeds these rows in via pandas `.to_dict("records")`, which
    renders a SQL NULL name as float('nan') -- and nan is TRUTHY, so the
    obvious `(name or "")` passes it straight through to .strip() and raises.
    Same isinstance guard as norm_tokens, for the same reason."""
    return name.strip().lower() if isinstance(name, str) else ""


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


def _dedup_category(rows: list[dict],
                    booth_meters: float = BOOTH_METERS) -> list[tuple[str, int, bool]]:
    """rows: dicts with poi_id, source_id, name, lat, lon, confidence.
    Returns (poi_id, cluster_id, is_canonical).

    `booth_meters=0` disables the booth-renter pass, which is how the
    before/after comparison is measured without two copies of this function."""
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

    # Booth-renter pass: name-BLIND, but only within one source and (by the
    # per-category call contract) one category. Adds unions only.
    if booth_meters > 0:
        for i in range(n):
            src = rows[i]["source_id"]
            if src not in BOOTH_SOURCES:
                continue
            for c in h3.grid_disk(cell[i], 1):
                for j in by_cell.get(c, ()):
                    if j <= i or rows[j]["source_id"] != src:
                        continue
                    if haversine_m(rows[i]["lat"], rows[i]["lon"],
                                   rows[j]["lat"], rows[j]["lon"]) <= booth_meters:
                        uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    out: list[tuple[str, int, bool]] = []
    for cid, members in enumerate(clusters.values()):
        # Canonical name = the MOST COMMON name in the cluster. A booth-renter
        # cluster is one shop name plus several individual operators' names, so
        # frequency recovers the storefront; where every name is distinct this
        # falls straight through to the pre-existing poi_id tiebreak. It sits
        # BELOW source authority and confidence, so it can never override the
        # anchor-source choice that source_rank exists to make.
        freq: dict[str, int] = {}
        for i in members:
            key = _name_key(rows[i]["name"])
            if key:
                freq[key] = freq.get(key, 0) + 1
        best = min(members, key=lambda i: (
            source_rank(rows[i]["category"], rows[i]["source_id"]),
            -(rows[i]["confidence"] or 0),
            -freq.get(_name_key(rows[i]["name"]), 0),
            rows[i]["poi_id"]))
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
