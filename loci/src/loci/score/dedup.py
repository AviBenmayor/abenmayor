"""Cross-source POI entity resolution (GTM-20).

The same real establishment appears in several sources — a nail salon in
Overture + NYS DOS + OSM, a restaurant in Overture + DOHMH. Counting all of
them inflates the DNCI exactly where source coverage overlaps, and overlap is
geographically biased (denser/richer areas are better covered), so the error is
NOT random — it would bias the residual. Dedup before scoring.

Two passes, one union-find (owner ruling 4, 2026-09-14): a CROSS-CATEGORY pass
for the same business filed under two categories by two sources (GTM-153), and
the within-category pass that has always run. See the CROSS_CATEGORY block.

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
# CROSS-CATEGORY MERGE (owner ruling 4, 2026-09-14; GTM-153)
# --------------------------------------------------------------------------
# Until now dedup ran strictly PER CATEGORY, so a business two sources filed
# under two different categories survived as two supply records. The motivating
# case: Lion's Milk at 104 Roebling is `nyc_dohmh_restaurants:50043137`
# (category restaurant, it holds a food-service permit) and
# `overture_places:41c0fc63-...` (category cafe_bakery, which is what it looks
# like from the sidewalk), 11 m apart, both open, the same normalized name --
# and never merged, because the two rows were never in the same call to
# `_dedup_category`. One café counted twice in the supply pool is exactly the
# defect GTM-153 opened.
#
# The rule, and why each clause is load-bearing:
#   DIFFERENT SOURCES -- the ordinary cross-source case. Two feeds seeing one
#                   storefront and disagreeing about its category is a
#                   TAXONOMY disagreement, not two businesses. See
#                   CROSS_CATEGORY_SAME_SOURCE for the same-source case, which
#                   is a different claim and is OFF by default.
#   NAMES MATCH   -- the same `names_match` the within-category rule uses, plus
#                   the minimum-shared-token guard below. Nothing here is
#                   name-blind; a name-blind cross-category collapse would fuse
#                   the bar and the barber next door.
#   MATCH_METERS  -- unchanged at 40 m. This pass only ADDS unions; it never
#                   prevents one, so every within-category cluster that existed
#                   before still exists, possibly with more members.
#
# THE NAME RULE IS TIGHTER ACROSS CATEGORIES THAN WITHIN ONE, AND IT IS
# CALIBRATED, NOT ASSERTED. The first cut reused `names_match` (Jaccard >= 0.5
# or containment of a 2-token name) and was HAND-AUDITED on 100 random merges
# drawn from the live table: 87 true, 2 ambiguous, 11 false -- precision 0.870,
# Wilson 95% [0.790, 0.922]. On 18,023 merges that is ~2,300 wrong ones, worse
# than the double-counting it fixes, so the rule was tightened against the same
# 100 labels. Candidates measured (precision / recall against the audit):
#
#   names_match as-is                      0.870 [0.790, 0.922] / 1.000
#   >= 2 shared distinctive tokens         0.892 [0.794, 0.947] / 0.667
#   norm-token EQUALITY                    0.972 [0.903, 0.992] / 0.793
#   core equality (norm minus venue words) 0.961 [0.892, 0.987] / 0.851
#   core equality + <= 25 m                0.970 [0.898, 0.992] / 0.747
#   core equality + <= 20 m                0.964 [0.877, 0.990] / 0.609
#   full-name equality                     0.984 [0.917, 0.997] / 0.724
#   CORE EQUALITY + disjoint-venue block   0.986 [0.927, 0.998] / 0.839  <= SHIPPED
#
# So the shipped rule is EQUALITY of the distinctive core, plus one veto:
#
#   CORE EQUALITY -- strip the corporate boilerplate (`_CORPORATE`), the
#                   category-type words (`_GENERIC`) and the venue words
#                   (`_VENUE_WORDS`), and require what is LEFT to be equal, not
#                   merely overlapping. "Soneros" == "Soneros Bar Restaurant
#                   Inc"; "Fulton Stall Market" != "The Fulton". Jaccard and
#                   containment both leak: containment is what let "Hudson
#                   Yards Grill" merge into "Mount Sinai Hudson Yards", and a
#                   0.5 Jaccard is what let "Big Red Lantern" merge into "New
#                   Red Lantern".
#   DISJOINT VENUE WORDS VETO -- if BOTH names carry category-type words and
#                   those sets share nothing, the pair does not merge even when
#                   the cores agree. "Totowa Food" / "Totowa Nails" and
#                   "Claire's Wine Bar" / "Claire's Kitchen Cafe" are two
#                   businesses with one brand word, which is an extremely
#                   common NYC naming pattern; the words the core strip threw
#                   away are the only evidence that separates them, so they are
#                   read back rather than discarded. Cost on the audit: one
#                   true merge ("Kutting Edge Barber Shop" / "Kutting Edge
#                   Barbershop Llc", where the tokenizer splits one side).
#
# DISTANCE IS NOT THE LEVER, measured: among the 100 audited merges the true
# ones run median 15.8 m (p75 20.9, p90 27.2; 28% beyond 20 m) and the false
# ones median 24.9 m, so the distributions overlap heavily. Capping the
# cross-category radius at 25 m costs ~10 points of recall and buys nothing on
# top of the name rule (0.970 vs 0.986). MATCH_METERS stays 40 m for both
# passes, and the guard stays purely a NAME rule.
#
# The guard applies ONLY to cross-category pairs -- widening it to the
# within-category rule would REMOVE existing unions, which is not what this
# ruling asked for.
CROSS_CATEGORY = True

#: Same-source cross-category pairs. A single feed listing one place under two
#: categories is a real pattern for the aggregators (Overture and Foursquare
#: both carry multi-category venues), but it is also how a genuine two-tenant
#: building looks when both tenants share a brand ("X Pharmacy" / "X
#: Convenience" in one row each). Measured before choosing: 1,741 such pairs
#: exist on the live table (foursquare 647, overture 584, nys_dos 385, dohmh
#: 123, snap 2). Default OFF -- cross-source only.
CROSS_CATEGORY_SAME_SOURCE = False

#: Venue-type words. `_GENERIC` already covers the food/retail category words;
#: these are the drinking-venue words that make a bar and its restaurant look
#: like two names ("X Tavern" vs "X"), which matters because bar<->restaurant
#: is the single largest cross-category merge class. Stripped from the core and
#: read back by the disjoint-venue veto.
_VENUE_WORDS = frozenset({
    "club", "lounge", "pub", "tavern", "inn", "wine", "beer", "ale",
    "cocktail", "cocktails", "saloon", "taproom", "brewery", "brew",
})

#: Which category a merged cluster carries.
#:   "finer_food" (B, DEFAULT -- owner ruling 2026-09-14, verbatim "go with B")
#:                -- where the canonical member's category is the coarse
#:                `_COARSE_FOOD` ("restaurant") and some other member carries a
#:                finer food category (`_FINER_FOOD`), the FINER one wins and
#:                the anchor row counts as corroboration. Lion's Milk ->
#:                cafe_bakery, still DOHMH-canonical. The reasoning: DOHMH
#:                files every permitted food service as a restaurant and cannot
#:                distinguish a cafe from a diner, so its label is a permit
#:                class, not a retail category; the aggregator that says
#:                "cafe_bakery" is the one carrying the finer fact, and the
#:                registry's authority over EXISTENCE does not extend to
#:                taxonomy.
#:   "anchor"     (A) -- the canonical member's category, i.e. the registry's
#:                classification. Lion's Milk -> restaurant. Kept because it is
#:                the BEFORE side of the measurement and a one-constant
#:                rollback.
#: CONSEQUENCES OF B, both measured in the GTM-153 dry run and both real:
#:   1. LEDGER KEYS MOVE. `model.poi_presence.mint_key` hashes the category, so
#:      every cluster B relabels re-mints, and pass B of `link_to_ledger`
#:      cannot rescue them because that pass requires the same category.
#:   2. THE SUPPLY VIEWS MUST READ `poi_dedup.category`. sql/003, 006 and 013
#:      select `staging.poi.category` off the canonical row, which equals the
#:      cluster label under A BY CONSTRUCTION and DIVERGES under B.
#:      sql/032_poi_supply_cluster_category.sql redefines them; without it a B
#:      relabel is invisible to every downstream count.
CATEGORY_PRECEDENCE = "finer_food"
_COARSE_FOOD = "restaurant"
_FINER_FOOD = ("cafe_bakery", "bar")

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
#   SAME CATEGORY-- was guaranteed by construction (_dedup_category ran per
#                   category); since ruling 4 made the pass global it is
#                   CHECKED EXPLICITLY in _dedup_all, so a barbershop and a
#                   nail salon in one building are still never fused.
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
    elif category == "pharmacy":
        # The NYS Medicaid enrolled-pharmacy roster is a government enrolment
        # registry (and enrolment requires a current NYSED establishment
        # registration), so it wins canonical selection over the aggregators
        # exactly as DOHMH does for food. Same trap as childcare in D65:
        # without this branch the source falls through to the `else` and
        # scores WORSE than Overture (rank 5 vs 0), so an aggregator's name
        # and geometry would stay canonical for every cluster the registry
        # anchors.
        #
        # Note this branch does NOT help where the legal name and the trade
        # name disagree -- those never enter the same cluster at all; see
        # sources/cities/nyc/nys_medicaid_pharmacy.py.
        order = ["nys_medicaid_pharmacies"] + _TAIL
    elif category == "laundry":
        # THE SAME TRAP, THIRD INSTANCE (owner ruling 2026-09-16, fix now).
        # D65 documents it for childcare and the pharmacy branch above documents
        # it again; nobody added the laundry branch, so laundry fell to the
        # `else` arm -- where `_TAIL` ENDS with `nyc_dcwp_licenses`, ranking the
        # DCWP roster (4) BELOW the DCWP inspections anchor (rank = len(order),
        # i.e. worst) and below every aggregator.
        #
        # Measured by wave two on the live file: with the roster ingested, an
        # EXPIRED roster licence became the canonical row of its cluster and its
        # `closed` status gated the whole cluster -- a live laundromat -- out of
        # supply. Five of six did exactly that: laundry supply 3,954 -> 3,949.
        # The roster row was outranking the 4,285-POI inspections anchor (D55,
        # confidence 0.9) that the category is actually built on.
        #
        # `nyc_dcwp_inspections` first, and the roster stays where `_TAIL` puts
        # it -- LAST -- so an expired licence can never speak for a cluster an
        # inspector has visited.
        order = ["nyc_dcwp_inspections"] + _TAIL
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


def full_tokens(name) -> frozenset[str]:
    """`norm_tokens` WITHOUT the category strip -- only the corporate
    boilerplate goes. The cross-category rule needs both halves of the name:
    the distinctive core, and the category-type words the core strip threw
    away (`venue_words`), which are the only thing separating "Totowa Food"
    from "Totowa Nails"."""
    if not isinstance(name, str) or not name:
        return frozenset()
    toks = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    return frozenset(t for t in toks if t and t not in _CORPORATE)


def cross_core(name) -> frozenset[str]:
    """The distinctive core: `norm_tokens` minus the venue words. This is what
    must be EQUAL for a cross-category merge."""
    return frozenset(t for t in norm_tokens(name) if t not in _VENUE_WORDS)


def venue_words(name) -> frozenset[str]:
    """The category-type words `cross_core` removed -- `_GENERIC` plus
    `_VENUE_WORDS` as they actually appear in this name. Read back by the
    disjoint-venue veto."""
    return full_tokens(name) - cross_core(name)


def cross_category_names_match(core_a: frozenset[str], core_b: frozenset[str],
                               venue_a: frozenset[str] = frozenset(),
                               venue_b: frozenset[str] = frozenset()) -> bool:
    """The cross-category name rule. Audited precision 0.986, Wilson 95%
    [0.927, 0.998] on 100 hand-labelled merges; see the CROSS_CATEGORY block
    for the whole candidate table and why equality beat Jaccard, containment
    and every distance cap.

    Two clauses, both load-bearing:
      1. the distinctive cores are EQUAL and non-empty;
      2. NOT (both names carry category-type words AND those sets are
         disjoint) -- one brand word under two different trade words is two
         businesses, not one.

    Note this is NOT `names_match` with an extra condition: equality is
    strictly stronger than `names_match`, so no cross-category pair the old
    within-category predicate refused can be admitted here."""
    if not core_a or core_a != core_b:
        return False
    return not (venue_a and venue_b and not (venue_a & venue_b))


def cross_category_names_match_raw(name_a, name_b) -> bool:
    """The same predicate from raw names, for callers with no precomputed token
    sets (tests, ad-hoc checks)."""
    return cross_category_names_match(cross_core(name_a), cross_core(name_b),
                                      venue_words(name_a), venue_words(name_b))


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


def _cluster_category(rows: list[dict], members: list[int], best: int,
                      precedence: str) -> str:
    """The label a merged cluster carries. See CATEGORY_PRECEDENCE.

    `best` is the canonical member and is NOT re-chosen here -- variant B moves
    the label only, so `is_canonical` is identical under both variants."""
    canon_cat = rows[best]["category"]
    if precedence == "anchor":
        return canon_cat
    if precedence != "finer_food":
        raise ValueError(f"unknown CATEGORY_PRECEDENCE {precedence!r}")
    if canon_cat != _COARSE_FOOD:
        return canon_cat
    finer = [i for i in members if rows[i]["category"] in _FINER_FOOD]
    if not finer:
        return canon_cat
    # the most authoritative finer-food member names the category
    pick = min(finer, key=lambda i: (
        source_rank(rows[i]["category"], rows[i]["source_id"]),
        -(rows[i]["confidence"] or 0),
        _FINER_FOOD.index(rows[i]["category"]),
        rows[i]["poi_id"]))
    return rows[pick]["category"]


def _dedup_all(rows: list[dict],
               booth_meters: float = BOOTH_METERS,
               cross_category: bool = CROSS_CATEGORY,
               cross_category_same_source: bool = CROSS_CATEGORY_SAME_SOURCE,
               precedence: str | None = None,
               ) -> list[tuple[str, int, bool, str]]:
    """rows: dicts with poi_id, source_id, name, category, lat, lon, confidence.
    Returns (poi_id, cluster_id, is_canonical, cluster_category).

    ONE pass over every category at once. Within a category the rule is
    unchanged (name match within MATCH_METERS, plus the booth-renter pass);
    across categories it is the cross-source name rule documented at the top of
    this module. Blocking, radius and the canonical-selection key are
    untouched, so a within-category cluster can only GAIN members, never lose
    them -- which is the ledger-key stability `sql/018` needs.

    ALMOST. Measured on the live table (308,366 staging rows, 227,548 clusters
    -> 216,170): 85 clusters DO change canonical member. Every one is a
    transitive bridge -- two same-category clusters joined through a
    cross-category member -- where the merged membership changes the NAME
    FREQUENCY tiebreak below and promotes a row that was previously
    non-canonical. 85 of 216,170 is 0.04%, and 15 of the 85 are carried
    forward anyway by pass B of `model.poi_presence.link_to_ledger` (same
    category, names_match, <= 40 m). The rest mint a new `location_key` for a
    location that did not move. That is the honest cost of a union-find; it is
    reported, not hidden.

    `booth_meters=0` disables the booth-renter pass and
    `cross_category=False` disables the new pass, which is how the
    before/after comparisons are measured without three copies of this
    function."""
    precedence = precedence or CATEGORY_PRECEDENCE
    n = len(rows)
    toks = [norm_tokens(r["name"]) for r in rows]
    core = ([cross_core(r["name"]) for r in rows]
            if cross_category else [frozenset()] * n)
    venue = ([venue_words(r["name"]) for r in rows]
             if cross_category else [frozenset()] * n)
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
            same_cat = rows[i]["category"] == rows[j]["category"]
            if same_cat:
                if not names_match(toks[i], toks[j]):
                    continue
            else:
                if not cross_category:
                    continue
                if (not cross_category_same_source
                        and rows[i]["source_id"] == rows[j]["source_id"]):
                    continue
                if not cross_category_names_match(core[i], core[j],
                                                   venue[i], venue[j]):
                    continue
            if haversine_m(rows[i]["lat"], rows[i]["lon"], rows[j]["lat"], rows[j]["lon"]) <= MATCH_METERS:
                uf.union(i, j)

    # Booth-renter pass: name-BLIND, but only within one source and one
    # category. The category clause used to be guaranteed by construction
    # (_dedup_category ran per category); this function sees every category at
    # once, so it is now CHECKED EXPLICITLY -- without it a DOS nail salon and
    # a DOS barbershop in one building would fuse name-blind, which is exactly
    # what the rule's comment says must never happen. Adds unions only.
    if booth_meters > 0:
        for i in range(n):
            src = rows[i]["source_id"]
            if src not in BOOTH_SOURCES:
                continue
            for c in h3.grid_disk(cell[i], 1):
                for j in by_cell.get(c, ()):
                    if j <= i or rows[j]["source_id"] != src:
                        continue
                    if rows[j]["category"] != rows[i]["category"]:
                        continue
                    if haversine_m(rows[i]["lat"], rows[i]["lon"],
                                   rows[j]["lat"], rows[j]["lon"]) <= booth_meters:
                        uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    out: list[tuple[str, int, bool, str]] = []
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
        cat = _cluster_category(rows, members, best, precedence)
        for i in members:
            out.append((rows[i]["poi_id"], cid, i == best, cat))
    return out


def _dedup_category(rows: list[dict],
                    booth_meters: float = BOOTH_METERS) -> list[tuple[str, int, bool]]:
    """The pre-ruling-4 behaviour: one category at a time, no cross-category
    pass. Kept because it is the BEFORE side of every comparison (and the unit
    under test for the within-category rule). `build_dedup` no longer calls
    it."""
    return [(pid, cid, canon)
            for pid, cid, canon, _cat in _dedup_all(rows, booth_meters=booth_meters,
                                                    cross_category=False)]


def build_dedup(con) -> dict:
    """One global pass (ruling 4): categories can no longer be resolved
    independently, because a cluster may span two of them.

    `analysis.poi_dedup.category` is now the CLUSTER's category (the canonical
    member's, per CATEGORY_PRECEDENCE), which for a cross-category cluster
    differs from `staging.poi.category` on the absorbed rows. Everything
    downstream reads poi_dedup, so the cluster label is the one that counts;
    the source's own label stays recoverable in staging.poi."""
    import pandas as pd

    rows = con.execute(
        """SELECT poi_id, source_id, name, category, confidence,
                  ST_Y(geom) AS lat, ST_X(geom) AS lon
           FROM staging.poi""").df().to_dict("records")
    result = _dedup_all(rows)

    con.execute("DELETE FROM analysis.poi_dedup")
    df = pd.DataFrame(result, columns=["poi_id", "cluster_id", "is_canonical", "category"])
    con.register("_dd", df)
    # Named on BOTH sides: DuckDB binds INSERT ... SELECT by POSITION, so the
    # SELECT list alone would not survive an ALTER on analysis.poi_dedup -- and
    # the audit's standing recommendation is to DROP `category` from this table
    # (it disagrees with staging.poi on 10,551 rows), which is exactly the kind
    # of shape change a positional write turns into silent column-swapping.
    con.execute("INSERT INTO analysis.poi_dedup "
                "(poi_id, cluster_id, is_canonical, category) "
                "SELECT poi_id, cluster_id, is_canonical, category FROM _dd")
    con.unregister("_dd")

    # report: raw rows by the SOURCE's category, canonical clusters by the
    # CLUSTER's category. The two denominators differ by exactly the rows a
    # cross-category merge relabelled, which is the number worth watching.
    raw = df.merge(pd.DataFrame(rows)[["poi_id", "category"]]
                   .rename(columns={"category": "src_category"}), on="poi_id")
    report: dict[str, tuple[int, int]] = {}
    for cat in sorted(set(raw["src_category"]) | set(df["category"])):
        report[cat] = (int((raw["src_category"] == cat).sum()),
                       int(((df["category"] == cat) & df["is_canonical"]).sum()))
    return report
