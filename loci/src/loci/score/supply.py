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

--------------------------------------------------------------------------
3. THE FLOOR-ANCHOR EXCEPTION (D69, owner, 2026-09-11)
--------------------------------------------------------------------------
D52's veto rests on one assumption: that a dense registry which never listed a
record is EVIDENCE the record is not a business. That assumption fails for a
registry whose scope is narrower than the category — one that could not have
listed the record however real it is. For `childcare` the DOHMH roster covers
GROUP settings only (Health Code Article 47 and Article 43); home-based Family
and Group Family Day Care is licensed by NYS OCFS and is in no NYC feed. So
"no registry member" there carries no information at all, and the veto deletes
supply precisely where home-based care dominates.

A category may therefore declare `anchor_is_floor: true` in categories.yaml.
Its anchor still ranks first for canonical geometry and name, still counts
toward anchor_coverage and still qualifies — the ONLY thing that changes is
that its lone-aggregator records are RETAINED in `in_principled`. Every other
category is untouched; this is an exception per category, declared in the
config a human reads, not a softening of the rule.

The flag is only meaningful where an anchor is actually loaded (a floor is a
floor UNDER something), so `check_floor_anchors` refuses a flagged category
with no registry source measured in it — the drift check for someone who
flags a category and forgets to ingest its roster.
"""
from __future__ import annotations

import functools
import hashlib
import json
import pathlib

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
#: AMENDED 2026-09-11 (D69): childcare landed in that band at 0.85 and there IS
#: no better anchor — the half the DOHMH roster misses (OCFS home-based care) is
#: published by nobody. That is what `anchor_is_floor` below is for, and it is
#: the only sanctioned answer to "the band says load a better anchor and none
#: exists". Moving this number is still never the answer.
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

#: The categories.yaml key that declares a category's anchor a FLOOR (D69).
#: The flag lives with the rest of the per-category config, beside the NAICS
#: codes and the source vocabularies, because it is a statement about what the
#: category's registry COVERS — not a tuning knob for the screen.
FLOOR_ANCHOR_KEY = "anchor_is_floor"

_CATEGORIES_YAML = pathlib.Path(__file__).resolve().parents[1] / "categories.yaml"


@functools.cache
def floor_anchor_categories(path: pathlib.Path | None = None) -> frozenset[str]:
    """Categories whose registry anchor is a FLOOR, from categories.yaml.

    A floor anchor closes gaps but never opens them: absence from the registry
    is not evidence of absence, because the registry's scope is narrower than
    the category by construction (see §3). Cached, because the view is rebuilt
    per run and the file cannot change mid-process."""
    import yaml

    with open(path or _CATEGORIES_YAML) as f:
        cats = yaml.safe_load(f)["categories"]
    return frozenset(slug for slug, entry in cats.items()
                     if bool((entry or {}).get(FLOOR_ANCHOR_KEY)))


def check_floor_anchors(coverage, floors: frozenset[str] | None = None) -> None:
    """Refuse a floor flag on a category with no registry anchor measured.

    Pure, so the drift check can run against a synthetic measurement. A floor
    is a floor UNDER something: flagging a category whose roster was never
    ingested would silently declare "the veto does not apply here" for a
    category where the veto was never going to fire anyway (an unanchored
    category already keeps everything), and would then go on being wrong once
    an anchor DID land. `coverage` is measure_anchor_coverage's frame or any
    iterable of mappings carrying `category`, `anchor_sources` and
    `anchor_poi`."""
    floors = floor_anchor_categories() if floors is None else floors
    rows = (coverage.to_dict("records") if hasattr(coverage, "to_dict")
            else list(coverage))
    seen = {str(r["category"]): r for r in rows}
    bad: list[str] = []
    for cat in sorted(floors):
        row = seen.get(cat)
        if row is None:
            bad.append(f"{cat} (not measured at all)")
        elif not row.get("anchor_sources") or not (row.get("anchor_poi") or 0) > 0:
            bad.append(f"{cat} (no registry source in staging.poi)")
    if bad:
        raise ValueError(
            f"{FLOOR_ANCHOR_KEY} is set in categories.yaml for a category with "
            "no registry anchor loaded, which is meaningless — a floor anchor "
            "is a floor UNDER a roster: " + "; ".join(bad)
            + ". Ingest the anchor, or drop the flag.")


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


#: --------------------------------------------------------------------------
#: THE CLOSURE GATE (owner ask 2026-09-14, GTM-153; cause D36 / GTM-121)
#: --------------------------------------------------------------------------
#: A canonical POI whose documented predicate
#: (model/poi_presence.poi_is_open) says CLOSED is not supply. ON by default:
#: counting a shut storefront as supply erases the very gap the screen exists
#: to find, and GTM-153 is exactly that -- one cafe counted twice in the
#: revenue pool because its departed predecessor at the same coordinate was
#: still canonical.
#:
#: The gate fires ONLY on 'closed'. 'unknown' -- which is most of the universe,
#: because Overture / OSM / Foursquare's open cache / USDA SNAP publish no
#: status at all -- is KEPT. Collapsing unknown into closed would delete supply
#: on the strength of nothing, which is the D52/M9 failure this codebase
#: already has scar tissue for.
GATE_CLOSED = True

#: Collapse a same-category co-located group the evidence CANNOT split
#: (resolution 'unresolved') down to ONE row. OFF, and it stays off pending an
#: OWNER RULING, because the two readings are genuinely indistinguishable from
#: here: a large building legitimately holds two restaurants at one geocoded
#: point, and it equally legitimately holds one restaurant plus its
#: unrecorded-closed predecessor. Turning this on trades a known over-count for
#: an unknown under-count; `loci colocation --collapse-unresolved` prints what
#: it would cost, without applying it.
#:
#: MEASURED REASON TO LEAVE IT OFF (2026-09-14 warehouse, principled set): the
#: five largest "unresolved" groups hold 72, 39, 38, 36 and 36 restaurants at a
#: SINGLE coordinate, and their coordinates are Penn Station, JFK and Port
#: Authority — GEOCODE SINKS, where a whole terminal's food hall is published
#: at one building point. Collapsing those would delete 71 real restaurants in
#: one group. Any future ruling to turn this on should first exclude sinks
#: (e.g. cap the group size, or drop groups whose members span many source
#: addresses), not flip the flag.
COLLAPSE_UNRESOLVED = False

#: The view canonical_poi_sql reads. analysis.poi_supply_status is
#: analysis.poi_supply with the status + co-location columns bolted on
#: (sql/029_poi_colocation.sql, generated by
#: model/poi_presence.colocation_view_sql). It is a VIEW over the same
#: staging.poi / analysis.poi_dedup join, row-for-row identical in COUNT to
#: analysis.poi_supply -- tests/test_poi_colocation.py pins that, because a
#: fan-out here would double supply, the exact bug being fixed.
SUPPLY_VIEW = "analysis.poi_supply_status"


def canonical_poi_sql(supply_set: str = DEFAULT_SUPPLY_SET,
                      cols: str = "s.category, ST_X(s.geom), ST_Y(s.geom)",
                      *,
                      gate_closed: bool | None = None,
                      collapse_unresolved: bool | None = None,
                      view: str | None = None,
                      where: str | None = None) -> str:
    """The one SELECT every consumer of "the supply of businesses" should use.

    Replaces the hand-written `staging.poi JOIN analysis.poi_dedup ON ...
    AND d.is_canonical` that had been copy-pasted into six modules: they now
    all read the SAME view with the SAME predicate, so a supply-set change
    cannot reach one consumer and miss another. The view already filters
    is_canonical, so 'all' reproduces the old behaviour exactly.

    Since 2026-09-14 it also applies the CLOSURE GATE: `poi_status <>
    'closed'`, where poi_status is model/poi_presence.poi_is_open evaluated in
    analysis.poi_supply_status. Pass `gate_closed=False` to reproduce the
    pre-gate set exactly (that is how `loci colocation` prints the delta), and
    `collapse_unresolved=True` to additionally keep one row per unresolved
    co-located group -- the alternative the owner has not yet ruled on.

    `where` ANDs an extra predicate onto the supply predicate -- the one way
    to read a SCOPED slice of the supply set without hand-writing the view
    read and losing the gate. It exists for the report path, which wants the
    ~300 POIs inside one 500 m catchment and was pulling all 136,563 rows of
    `analysis.poi_supply_status` into pandas to throw 99.8% of them away. It
    is a SQL fragment, not a parameter list: `con.execute()` takes this string
    with no params, so a caller interpolates its own numeric literals (never
    user text) into it -- see `report/evidence._bbox_sql`.

    `where` MUST be a superset filter on anything the caller then refines in
    Python. Narrowing it below the caller's own test silently deletes supply,
    which is the same class of bug as the closure gate hiding an open
    storefront.

    Geometry note: s.geom is EPSG:4326 by convention (DuckDB GEOMETRY carries
    no SRID); ST_X/ST_Y therefore return lon/lat degrees, which is what every
    caller here snaps to the walk graph with. A `where` fragment that bounds
    a distance therefore bounds it in DEGREES, not metres, and the metre-true
    test stays on `haversine_m` in the caller.
    """
    gate = GATE_CLOSED if gate_closed is None else gate_closed
    collapse = COLLAPSE_UNRESOLVED if collapse_unresolved is None else collapse_unresolved
    # `view` exists for ONE caller: model/supply_asof.pinned_supply_view, which
    # renders the same view at another as-of date so `supply_hash(asof=...)`
    # can answer "what would tomorrow cost" WITHOUT writing. It is not a knob:
    # anything else passing a view here is reading a different supply set under
    # the same name.
    src_view = view or SUPPLY_VIEW
    preds = [f"s.{supply_predicate(supply_set)}"]
    if gate:
        # `<> 'closed'` and never `= 'open'`: the predicate is TRI-STATE and
        # 'unknown' must survive (see GATE_CLOSED).
        preds.append("s.poi_status <> 'closed'")
    if where:
        preds.append(f"({where})")
    sql = f"SELECT {cols} FROM {src_view} s WHERE " + " AND ".join(preds)
    if collapse:
        # Deterministic survivor: a positively-open member beats an unknown one
        # ('open' < 'unknown' lexically), then the lowest poi_id, so two runs
        # collapse to the SAME row and supply_hash stays comparable.
        sql += (" QUALIFY NOT s.is_colocated_unresolved"
                " OR row_number() OVER (PARTITION BY s.colocation_key"
                " ORDER BY s.poi_status, s.poi_id) = 1")
    return sql


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
    # D69: the flag is config, but it is PERSISTED beside the measurement so
    # sql/013's view stays self-contained SQL and so a written row says which
    # rule produced the supply it describes.
    check_floor_anchors(df)
    floors = floor_anchor_categories()
    used_year = con.execute(
        "SELECT max(year) FROM analysis.zip_category_establishments"
    ).fetchone()[0] if year is None else year
    out = df.copy()
    out["anchor_is_floor"] = out["category"].isin(floors)
    out["year"] = used_year
    out["boroughs"] = ",".join(boroughs) if boroughs else "ALL"
    out["threshold"] = ANCHOR_COVERAGE_MIN
    out["run_at"] = datetime.datetime.now(datetime.timezone.utc)
    out = out[["category", "anchor_sources", "anchor_poi", "zbp_estab", "n_zips",
               "anchor_coverage", "threshold", "qualifies", "anchor_is_floor",
               "year", "boroughs", "run_at"]]
    con.execute("DELETE FROM analysis.category_anchor")
    con.register("_ca", out)
    try:
        cols = ", ".join(out.columns)
        con.execute(f"INSERT INTO analysis.category_anchor ({cols}) SELECT {cols} FROM _ca")
    finally:
        con.unregister("_ca")
    return len(out)


# ---------------------------------------------------------------- provenance

def supply_hash(con, supply_set: str = DEFAULT_SUPPLY_SET, *, asof=None) -> str:
    """Short, stable hash of everything that decides WHICH POIs a run counted:
    the set name, the dedup rule parameters, the qualifying-anchor set, and
    the resulting per-category supply counts. Same rationale as
    address_gaps._reach_hash — two runs whose supply differs must be
    distinguishable once written, and the count alone would not catch a
    same-size but differently-composed set.

    `asof` computes the hash at ANOTHER as-of date than the one pinned in
    `analysis.supply_asof`, by rendering the live view against a date literal
    in a TEMP VIEW (so it works read-only and writes nothing). That is how the
    drift test pins the baseline's own date and how `loci supply-asof advance`
    prices a day. `asof=None` -- every existing caller -- reads the pin, which
    is what the warehouse itself uses.

    THE AS-OF DATE IS NOT IN THE BLOB, deliberately (model/supply_asof.py
    caveat 3): adding it would change every historical hash, and
    `ba944e18c57b` reproducing at asof 2026-09-15 is the whole proof that the
    pin is inert.
    """
    from loci.score.dedup import BOOTH_METERS, BOOTH_SOURCES, MATCH_METERS

    view = None
    if asof is not None:
        from loci.model.supply_asof import pinned_supply_view
        view = pinned_supply_view(con, asof)

    # Through canonical_poi_sql, so the hash describes the set actually
    # counted (gate and collapse included) rather than the ungated view.
    # Wrapped in a subquery because the collapse adds a QUALIFY clause that
    # must not land after a GROUP BY.
    counts = dict(con.execute(
        "SELECT category, count(*) FROM ("
        + canonical_poi_sql(supply_set, "s.category", view=view) + ") GROUP BY 1"
    ).fetchall())
    def _cats(predicate: str) -> list[str]:
        try:
            return sorted(r[0] for r in con.execute(
                f"SELECT category FROM analysis.category_anchor WHERE {predicate}"
            ).fetchall())
        except Exception:                 # table/column not yet created
            return []

    anchors = _cats("qualifies")
    # Read from the TABLE, not from categories.yaml: the hash has to describe
    # the rule the view actually applied on this database, and a config edit
    # that has not been re-measured has not applied anything.
    floors = _cats("anchor_is_floor")
    blob = json.dumps({
        "supply_set": supply_set,
        "match_m": MATCH_METERS,
        "booth_m": BOOTH_METERS,
        "booth_sources": sorted(BOOTH_SOURCES),
        "aggregators": sorted(AGGREGATOR_SOURCES),
        "anchor_min": ANCHOR_COVERAGE_MIN,
        # GTM-153: two runs that differ only in whether evidenced closures were
        # gated out must be distinguishable once written.
        "gate_closed": bool(GATE_CLOSED),
        "collapse_unresolved": bool(COLLAPSE_UNRESOLVED),
        "open_evidence_max_age_days": _open_evidence_window(),
        "anchored": anchors,
        "floor_anchors": floors,
        "counts": {k: int(v) for k, v in sorted(counts.items())},
    }, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


# ------------------------------------------------------- the closure gate (GTM-153)

def _open_evidence_window() -> int:
    """model/poi_presence.OPEN_EVIDENCE_MAX_AGE_DAYS, imported lazily so that
    score/ keeps no import-time dependency on model/ (model.poi_presence
    already imports score.dedup; a module-level import here would invert the
    layering and risk a cycle)."""
    from loci.model.poi_presence import OPEN_EVIDENCE_MAX_AGE_DAYS
    return int(OPEN_EVIDENCE_MAX_AGE_DAYS)


def colocation_report(con, supply_set: str = DEFAULT_SUPPLY_SET):
    """Per-category co-location and gate accounting. READ-ONLY -- it executes
    only SELECTs and is safe on a read_only connection.

    Returns (per_category_df, totals_dict). Columns, per category:

      n_canonical           canonical POIs in this supply set, UNGATED
      n_closed              ...that the predicate says are CLOSED (the gate's
                            removal; evidenced closures only -- a ledger
                            closed_on or a source-published status)
      n_gated               n_canonical - n_closed, i.e. what supply becomes
      groups_*              co-located same-category groups by resolution
      n_collapse_would_drop rows `--collapse-unresolved` would additionally
                            remove (sum over unresolved groups of n_poi - 1),
                            reported WITHOUT applying it

    `share_affected` is the share of ungated canonical POIs sitting in ANY
    co-located group -- the blast radius of the question, not of the fix.
    """
    import pandas as pd

    pred = supply_predicate(supply_set)
    per_cat = con.execute(f"""
        WITH s AS (SELECT * FROM {SUPPLY_VIEW} WHERE {pred})
        SELECT category,
               count(*)                                            AS n_canonical,
               count(*) FILTER (WHERE poi_status = 'closed')        AS n_closed,
               count(*) FILTER (WHERE poi_status = 'open')          AS n_open,
               count(*) FILTER (WHERE poi_status = 'unknown')       AS n_unknown,
               count(*) FILTER (WHERE colocation_n >= 2)            AS n_colocated,
               count(*) FILTER (WHERE is_colocated_unresolved)      AS n_unresolved_poi
        FROM s GROUP BY 1 ORDER BY 1
    """).df()
    groups = con.execute(f"""
        WITH s AS (SELECT * FROM {SUPPLY_VIEW} WHERE {pred}),
        g AS (
            SELECT colocation_key, any_value(category) AS category, count(*) AS n_poi,
                   any_value(colocation_resolution) AS resolution
            FROM s GROUP BY colocation_key HAVING count(*) >= 2
        )
        SELECT category,
               count(*)                                          AS n_groups,
               count(*) FILTER (WHERE resolution = 'one_closed')  AS groups_one_closed,
               count(*) FILTER (WHERE resolution = 'all_closed')  AS groups_all_closed,
               count(*) FILTER (WHERE resolution = 'both_open')   AS groups_both_open,
               count(*) FILTER (WHERE resolution = 'unresolved')  AS groups_unresolved,
               coalesce(sum(CASE WHEN resolution = 'unresolved'
                                 THEN n_poi - 1 ELSE 0 END), 0)   AS n_collapse_would_drop
        FROM g GROUP BY 1
    """).df()
    df = per_cat.merge(groups, on="category", how="left").fillna(
        {c: 0 for c in groups.columns if c != "category"})
    for c in df.columns:
        if c != "category":
            df[c] = df[c].astype(int)
    df["n_gated"] = df["n_canonical"] - df["n_closed"]
    totals = {c: int(df[c].sum()) for c in df.columns if c != "category"}
    totals["share_affected"] = (totals["n_colocated"] / totals["n_canonical"]
                                if totals["n_canonical"] else 0.0)
    totals["share_removed"] = (totals["n_closed"] / totals["n_canonical"]
                               if totals["n_canonical"] else 0.0)
    return df, totals
