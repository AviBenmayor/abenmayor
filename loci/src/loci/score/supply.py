"""Supply sets — which canonical POIs count as evidence of a real business (D52).

THE SUPPLY-SET PRINCIPLE (owner decision, 2026-09-08). Where a category has a
registry/licence anchor actually loaded, a LONE AGGREGATOR RECORD — a dedup
cluster no registry feed and no second feed ever saw — is not evidence of a
business, and is excluded from supply. Where no anchor is loaded, every
canonical record stays and LOADING THE ANCHOR is the fix, not filtering.
This replaces both the global ALL set (which inherits every aggregator ghost)
and the global CORROBORATED set (which, as the D47/M9 run showed, silently
deletes 84-90% of convenience, childcare and clinic supply purely because
those categories have no anchor loaded — 0.16x / 0.15x / 0.10x of ZBP —
manufacturing exactly the fake retail gaps this project exists to avoid).

--------------------------------------------------------------------------
1. WHAT COUNTS AS AN ANCHOR IS MEASURED, NOT LABELLED.
--------------------------------------------------------------------------
registry.yaml calls DOHMH "a near-census" and NYS DOS "snapshot enrichment",
but a label cannot say whether the feed as INGESTED covers the category. A
registry that alone accounts for most of the Census establishment count can be
trusted to veto a record no other feed corroborates; a thin one cannot — it
would veto real businesses it simply never listed. So a source qualifies as an
anchor for a category only if

    anchor_coverage = (canonical POIs whose dedup cluster contains at least one
                       REGISTRY-source member) / (ZBP establishments)

reaches ANCHOR_COVERAGE_MIN over the comparable ZIPs (same population and
suppression filters as `loci zbp-compare`, so numerator and denominator share
one universe). The measurement is written to analysis.category_anchor and the
PRINCIPLED flag reads it there: an EMPTY analysis.category_anchor means NO
category is anchored, so PRINCIPLED degrades to ALL. Failing OPEN is
deliberate — a missing measurement must never silently delete supply.

--------------------------------------------------------------------------
2. CAVEATS THE DATABASE CANNOT ENFORCE
--------------------------------------------------------------------------
* anchor_coverage is a RATIO OF TWO IMPERFECT COUNTS. Its denominator (ZBP) is
  itself NAICS self-classification at ZIP grain and bleeds between adjacent
  categories (see zbp_naics.yaml). A coverage of 0.7 does not mean "70% of real
  businesses are licensed"; it means the registry accounts for 70% of the
  Census count of that category, which is the strongest evidence available
  that the registry is dense enough to veto.
* An anchored category still loses any genuine business the registry missed
  AND that only one aggregator saw. That is the trade D52 accepts: an
  aggregator ghost and a real unlicensed business are indistinguishable here.
* is_corroborated RESCUES a record two aggregators both saw. That is what
  keeps CORROBORATED a SUBSET of PRINCIPLED (see below); it is also the
  substantive reading of "a LONE aggregator record" — two independent feeds
  agreeing is corroboration, and dropping such a record would be STRICTER
  than the CORROBORATED set it is supposed to relax.
"""
from __future__ import annotations

import hashlib
import json

#: Coverage a registry source must reach, per category, to earn the right to
#: veto an uncorroborated aggregator record. 0.70 is a judgement, and it is a
#: constant here rather than a literal in a query so it can be moved in ONE
#: place and so tests can assert against it. The reasoning for the level:
#: below ~0.7 the registry is demonstrably missing a large share of the
#: category, so "no registry member" carries little information about whether
#: a business exists and the veto would mostly delete real supply; above it,
#: the registry is dense enough that absence from it is informative. The
#: observed distribution is bimodal — the loaded anchors sit near or above 1.0
#: and the unloaded categories sit at 0.0 — so no category is near the line and
#: the exact level is not load-bearing. If a future category lands in 0.5-0.9,
#: that is the signal to load a better anchor, not to move this number.
ANCHOR_COVERAGE_MIN = 0.70

#: Feeds that infer business existence from crowdsourced / scraped / licensed
#: third-party data rather than from a government act of registration. These
#: are the feeds that carry ghosts (a venue that closed is rarely marked
#: closed; it just stops being refreshed — see registry.yaml
#: foursquare_os_places). Everything NOT in this set is a REGISTRY source: a
#: government roster where the record exists because someone filed for a
#: permit, licence or inspection (DOHMH restaurants and childcare, NYS DOS
#: appearance enhancement, NYS SLA liquor, USDA SNAP, NYC DCWP, FDIC).
#: NOTE nyc_dcwp_licenses IS a registry by this definition even though
#: score/dedup.py's `_TAIL` ranks it last for CANONICAL SELECTION — that
#: ordering is about which row's name/geometry to keep, a different question
#: from whether the record is evidence the business exists.
AGGREGATOR_SOURCES = frozenset({
    "overture_places",
    "osm_overpass",
    "foursquare_os_places",
})

#: Named supply sets -> the boolean column on analysis.poi_supply
#: (sql/003_supply_sets.sql, extended by sql/006_principled_supply.sql).
SUPPLY_SETS: dict[str, str] = {
    "all": "in_all",
    "principled": "in_principled",
    "corroborated": "is_corroborated",
}

#: The default for anything that consumes supply downstream (the address
#: screen, the walk-distance step, the conveniences engine).
DEFAULT_SUPPLY_SET = "principled"


def supply_predicate(supply_set: str) -> str:
    """The analysis.poi_supply boolean column for a named set. Raises rather
    than silently defaulting: a typo'd set name must never quietly become
    'all' and change what the screen counts."""
    try:
        return SUPPLY_SETS[supply_set]
    except KeyError:
        raise ValueError(
            f"unknown supply set {supply_set!r}; expected one of "
            f"{', '.join(sorted(SUPPLY_SETS))}"
        ) from None


def canonical_poi_sql(supply_set: str = DEFAULT_SUPPLY_SET,
                      cols: str = "s.category, ST_X(s.geom), ST_Y(s.geom)") -> str:
    """The one SELECT every consumer of "the supply of businesses" should use.

    Replaces the hand-written `staging.poi JOIN analysis.poi_dedup ON ...
    AND d.is_canonical` that had been copy-pasted into six modules: they now
    all read the SAME view with the SAME predicate, so a supply-set change
    cannot reach one consumer and miss another. The view already filters
    is_canonical, so 'all' reproduces the old behaviour exactly.

    Geometry note: s.geom is EPSG:4326 by convention (DuckDB GEOMETRY carries
    no SRID); ST_X/ST_Y therefore return lon/lat degrees, which is what every
    caller here snaps to the walk graph with.
    """
    return f"SELECT {cols} FROM analysis.poi_supply s WHERE s.{supply_predicate(supply_set)}"


# --------------------------------------------------------------- measurement

def _registry_sources_by_category(con) -> dict[str, list[str]]:
    """{category: [registry source_ids present among cluster members]} — the
    sources that could act as an anchor for that category, measured from what
    is actually in staging.poi, not from registry.yaml's labels."""
    aggs = ", ".join(f"'{s}'" for s in sorted(AGGREGATOR_SOURCES))
    rows = con.execute(f"""
        SELECT category, source_id, count(*) AS n
        FROM staging.poi
        WHERE source_id NOT IN ({aggs})
        GROUP BY 1, 2
        ORDER BY 1, 3 DESC
    """).fetchall()
    out: dict[str, list[str]] = {}
    for cat, src, _n in rows:
        out.setdefault(cat, []).append(src)
    return out


def qualifies_as_anchor(anchor_poi, zbp_estab,
                        threshold: float = ANCHOR_COVERAGE_MIN) -> bool:
    """Does this category's registry coverage earn the right to veto?

    Pure and separate from the query so the RULE can be tested without a
    database: a THIN anchor (few registry records against a large Census
    count) must NOT qualify, and a category with no ZBP denominator at all
    must not qualify either -- an unmeasurable anchor is not a qualifying one,
    and treating it as one would delete supply on the strength of nothing.
    """
    if not zbp_estab or zbp_estab <= 0:
        return False
    return (float(anchor_poi) / float(zbp_estab)) >= threshold


def measure_anchor_coverage(con, year: int | None = None,
                            boroughs: tuple[str, ...] | None = None):
    """DataFrame(category, anchor_sources, anchor_poi, zbp_estab,
    anchor_coverage, qualifies) — step 1 of D52.

    Numerator and denominator come from the SAME `loci zbp-compare` machinery
    (majority-vote hex->ZIP crosswalk, population >= 1,000, ZBP row present),
    so a category's coverage is directly comparable to the ratios that report
    prints. `supply_set='registry_anchored'` counts canonical POIs whose
    cluster carries at least one registry-source member; nothing is persisted
    by that call.
    """
    import pandas as pd

    from loci.model.zbp_compare import build_coverage_check

    build_coverage_check(con, year, supply_set="registry_anchored",
                         boroughs=boroughs, write=False)
    df = con.execute("SELECT * FROM _zcc_last").df()
    g = (df.groupby("category")
           .agg(anchor_poi=("poi_count", "sum"),
                zbp_estab=("zbp_estab", "sum"),
                n_zips=("zipcode", "nunique"))
           .reset_index())
    g["anchor_coverage"] = g["anchor_poi"] / g["zbp_estab"].replace(0, pd.NA)
    g["qualifies"] = [qualifies_as_anchor(a, z) for a, z in zip(g["anchor_poi"], g["zbp_estab"])]
    srcs = _registry_sources_by_category(con)
    g["anchor_sources"] = g["category"].map(lambda c: ",".join(srcs.get(c, [])) or None)
    return g[["category", "anchor_sources", "anchor_poi", "zbp_estab",
              "n_zips", "anchor_coverage", "qualifies"]]


def build_category_anchor(con, year: int | None = None,
                          boroughs: tuple[str, ...] | None = None) -> int:
    """Measure and persist analysis.category_anchor. Returns rows written.

    analysis.poi_supply.in_principled JOINS this table, so this must be
    rebuilt whenever staging.poi or analysis.poi_dedup changes — i.e.
    immediately after `loci dedup`. Truncate-and-replace, never partial: a
    half-written table would anchor some categories and not others with no
    way to tell which run each row came from.
    """
    import datetime

    df = measure_anchor_coverage(con, year, boroughs)
    used_year = con.execute(
        "SELECT max(year) FROM analysis.zip_category_establishments"
    ).fetchone()[0] if year is None else year
    out = df.copy()
    out["year"] = used_year
    out["boroughs"] = ",".join(boroughs) if boroughs else "ALL"
    out["threshold"] = ANCHOR_COVERAGE_MIN
    out["run_at"] = datetime.datetime.now(datetime.timezone.utc)
    out = out[["category", "anchor_sources", "anchor_poi", "zbp_estab", "n_zips",
               "anchor_coverage", "threshold", "qualifies", "year", "boroughs", "run_at"]]
    con.execute("DELETE FROM analysis.category_anchor")
    con.register("_ca", out)
    try:
        cols = ", ".join(out.columns)
        con.execute(f"INSERT INTO analysis.category_anchor ({cols}) SELECT {cols} FROM _ca")
    finally:
        con.unregister("_ca")
    return len(out)


# ---------------------------------------------------------------- provenance

def supply_hash(con, supply_set: str = DEFAULT_SUPPLY_SET) -> str:
    """Short, stable hash of everything that decides WHICH POIs a run counted:
    the set name, the dedup rule parameters, the qualifying-anchor set, and
    the resulting per-category supply counts. Same rationale as
    address_gaps._reach_hash — two runs whose supply differs must be
    distinguishable once written, and the count alone would not catch a
    same-size but differently-composed set.
    """
    from loci.score.dedup import BOOTH_METERS, BOOTH_SOURCES, MATCH_METERS

    pred = supply_predicate(supply_set)
    counts = dict(con.execute(
        f"SELECT category, count(*) FROM analysis.poi_supply WHERE {pred} GROUP BY 1"
    ).fetchall())
    try:
        anchors = sorted(r[0] for r in con.execute(
            "SELECT category FROM analysis.category_anchor WHERE qualifies").fetchall())
    except Exception:                     # table not yet created -> no anchors
        anchors = []
    blob = json.dumps({
        "supply_set": supply_set,
        "match_m": MATCH_METERS,
        "booth_m": BOOTH_METERS,
        "booth_sources": sorted(BOOTH_SOURCES),
        "aggregators": sorted(AGGREGATOR_SOURCES),
        "anchor_min": ANCHOR_COVERAGE_MIN,
        "anchored": anchors,
        "counts": {k: int(v) for k, v in sorted(counts.items())},
    }, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]
