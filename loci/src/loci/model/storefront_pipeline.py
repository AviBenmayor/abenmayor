"""analysis.storefront_pipeline -- the filing EVENT LOG rolled up into one row
per business trying to open at a lot, plus the three things that roll-up makes
possible: a cross-agency name reconciliation, a government-filing first-seen
for the ledger, and a coming-supply context measure at address x category.

sql/020_storefront_pipeline.sql carries the schema rationale -- the grain and
the two D75 carry rules, why `furthest_stage` is a string and never a stored
rank, the `liquor_active` caveat on `opened_on`, why the reconciliation must be
one-to-one, and the caveats the database cannot enforce. Read it before
changing anything here.

WHAT THIS MODULE GUARANTEES
---------------------------
1. NO FUSION. The grain never groups on a name key without a BBL, and never on
   a BBL without a name key. The reconciliation is one-to-one and greedy, so
   one build-out can produce at most one lead time. Both rules exist because
   fusing distinct storefronts manufactures fake gaps downstream, which is the
   failure score/dedup.py and sql/018 are both about.
2. NO SILENT MAPPING. A `category_hint` from a controlled-vocabulary feed that
   model/filing_categories.yaml has never seen RAISES at build time. A value
   nobody classified is a decision nobody made, not a default.
3. ONLY AN OPEN SIGNAL DATES A STOREFRONT. `apply_gov_filing` reads
   `opened_on` and nothing else, moves a first-seen only EARLIER, and is
   idempotent by strict inequality.
4. CONTEXT, NOT SCORE. `openings_pipeline_400m` / `openings_recent_400m` are
   written by UPDATE onto analysis.address_category and are asserted disjoint
   from every column the screen, the supply ratio, the demand annotation or the
   age fit owns. Nothing here can move gap_score, supply_ratio_vs_base or a
   recommendation grade.
5. EVERY ADDRESS GETS A VALUE. 0 is a value (owner rule 2026-09-13: no
   eligibility gate, every street represented). NULL means "not run", and
   `openings_run_at IS NULL` is that flag.
"""
from __future__ import annotations

import datetime as dt
import functools
import math
import pathlib

import pandas as pd
import yaml

from loci.categories import CATEGORIES
from loci.chains.normalize import brand_key
from loci.db import METRES_SQL
from loci.filing_stages import EARLY_STAGES, STAGES, stage_rank

PKG = pathlib.Path(__file__).resolve().parents[1]
SQL_020 = PKG / "sql" / "020_storefront_pipeline.sql"
CATEGORY_MAP_PATH = pathlib.Path(__file__).resolve().parent / "filing_categories.yaml"

TABLE = "analysis.storefront_pipeline"
FILING_TABLE = "staging.storefront_filing"

#: Stages that mean "a regulator has seen a business that EXISTS at this
#: address". Owner's stage-two definition of `is_open`, and deliberately WIDER
#: than filing_stages.OPEN_STAGES, which excludes `liquor_active` because SLA's
#: `originalissuedate` is the premises' FIRST licence date. It is safe here
#: only because the SLA fetch is windowed on that date (sql/020 header, and
#: `validate` re-measures it every run). Read `opened_on_stage` before quoting
#: an opening date.
OPEN_EVIDENCE_STAGES: tuple[str, ...] = (
    "license_issued", "liquor_active", "first_inspection")

#: The reconciliation window. 540 days ~ 18 months: the 75th percentile of the
#: strict fitout -> first_inspection lead time is 415 days on the 2026-09-13
#: build, so 540 covers the observed distribution with room, while staying far
#: short of the 24-month ingest window (a wider link window than the data
#: window would pair filings across unrelated tenancies at a churning address).
LINK_WINDOW_DAYS = 540

#: A token is RARE enough to identify one business inside one lot when its
#: document idf over the whole name vocabulary clears this. Measured on the
#: 2026-09-13 build: 76,706 distinct `business_name_key` values, so idf 7.0 is
#: a token appearing in <= 70 of them (0.09%). "deli" (df 2,786, idf 3.3),
#: "restaurant" (2,357) and "grocery" (1,777) are nowhere near it, which is the
#: point -- those tokens are what a generic-name collision is made of.
RARE_TOKEN_MIN_IDF = 7.0

#: Tokens shorter than this never count as rare however low their df: a
#: two-character token is an initial or a typo, and a shared initial inside one
#: lot is not evidence.
RARE_TOKEN_MIN_LEN = 3

#: Windows for the address measures, in months back from `asof`.
OPENINGS_PIPELINE_MONTHS = 18
OPENINGS_RECENT_MONTHS = 12

#: The ONLY columns write_openings may name in a SET clause.
OPENINGS_COLUMNS = [
    "openings_pipeline_400m",
    "openings_recent_400m",
    "openings_radius_m",
    "openings_asof",
    "openings_run_at",
]

#: The ledger kind this module writes. Mirrored in poi_presence.KINDS; the test
#: pins that the two agree.
GOV_FILING_KIND = "gov_filing"
GOV_FILING_FIELD = "storefront_pipeline.opened_on"

#: How a ledger row was matched to a pipeline row, best first.
LEDGER_MATCH_METHODS = ("bbl_name", "name_dist")

#: Straight-line metres inside which a name-only ledger match is accepted. Only
#: used when the ledger POI could not be placed on a PLUTO lot; 100 m is about
#: one short NYC block face, and the test is METRES_SQL (flipped coordinates,
#: D16), never a degree box.
LEDGER_NAME_DIST_M = 100.0

#: An `opened_on` outside this range is refused by `apply_gov_filing`. Not a
#: real bound on retail history -- a bound on DATA. A 1901 licence date in a
#: 2026 extract is a sentinel, and a future date is a typo.
GOV_FILING_MIN_DATE = dt.date(1980, 1, 1)


# ---------------------------------------------------------------------------
# the category mapping
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def load_category_map(path: pathlib.Path | None = None) -> dict:
    """Parse model/filing_categories.yaml and check it against the taxonomy.

    Fails loudly on a slug that is not one of the 15 Loci categories, on an
    unknown vocabulary kind, and on a value listed in both `map` and
    `unmapped` -- each of which would otherwise show up as a quietly wrong
    category on a storefront.
    """
    doc = yaml.safe_load((path or CATEGORY_MAP_PATH).read_text())
    sources: dict[str, dict] = {}
    for sid, block in (doc.get("sources") or {}).items():
        vocab = block.get("vocabulary")
        if vocab not in ("controlled", "free_text"):
            raise ValueError(
                f"filing_categories.yaml: source {sid!r} has vocabulary "
                f"{vocab!r}; expected 'controlled' or 'free_text'")
        if vocab == "free_text":
            if not (block.get("reason") or "").strip():
                raise ValueError(
                    f"filing_categories.yaml: source {sid!r} is declared "
                    f"free_text with no `reason`. Declaring a whole feed "
                    f"unmappable is a claim; it has to carry its evidence.")
            sources[sid] = {"vocabulary": "free_text", "map": {},
                            "unmapped": set(), "confidence": {},
                            "reason": block["reason"]}
            continue
        mapping = {str(k): str(v) for k, v in (block.get("map") or {}).items()}
        bad = sorted(set(mapping.values()) - set(CATEGORIES))
        if bad:
            raise ValueError(
                f"filing_categories.yaml: source {sid!r} maps onto {bad}, "
                f"which are not Loci categories (loci/categories.py)")
        unmapped = {str(v) for v in (block.get("unmapped") or [])}
        both = sorted(set(mapping) & unmapped)
        if both:
            raise ValueError(
                f"filing_categories.yaml: source {sid!r} lists {both} in BOTH "
                f"`map` and `unmapped`")
        default_conf = str(block.get("confidence", "high"))
        overrides = {str(k): str(v) for k, v
                     in (block.get("confidence_overrides") or {}).items()}
        stray = sorted(set(overrides) - set(mapping))
        if stray:
            raise ValueError(
                f"filing_categories.yaml: source {sid!r} sets a confidence for "
                f"{stray}, which it does not map")
        bad_conf = sorted({default_conf, *overrides.values()} - {"high", "medium"})
        if bad_conf:
            raise ValueError(
                f"filing_categories.yaml: source {sid!r} uses confidence "
                f"{bad_conf}; expected 'high' or 'medium'")
        sources[sid] = {
            "vocabulary": "controlled",
            "map": mapping,
            "unmapped": unmapped,
            "confidence": {k: overrides.get(k, default_conf) for k in mapping},
        }
    return {"version": doc.get("version"), "sources": sources,
            "dohmh_classify_exceptions": doc.get("dohmh_classify_exceptions") or {}}


def loci_category_of(source: str, hint: str | None,
                     path: pathlib.Path | None = None) -> tuple[str | None, str]:
    """(loci category or None, confidence) for one (source, category_hint).

    RAISES on a value a controlled-vocabulary source has never declared. That
    is the fail-loud rule: an unclassified licence type silently becoming
    `unmapped` is indistinguishable from a real absence of that trade, and the
    whole point of this project is telling those two apart.
    """
    doc = load_category_map(path)
    block = doc["sources"].get(source)
    if block is None:
        raise KeyError(
            f"filing_categories.yaml does not know source {source!r}. A feed "
            f"added to filing_feeds.FEEDS must be declared here -- as a "
            f"controlled vocabulary or explicitly as free_text -- before its "
            f"rows can be rolled up.")
    if block["vocabulary"] == "free_text":
        return None, "unmapped"
    key = "" if hint is None else str(hint)
    if key in block["map"]:
        return block["map"][key], block["confidence"][key]
    if key in block["unmapped"] or key == "":
        return None, "unmapped"
    raise ValueError(
        f"filing_categories.yaml: {source!r} published category_hint {key!r}, "
        f"which is in neither `map` nor `unmapped`. Classify it explicitly "
        f"(map it, or list it under `unmapped` with a reason) -- a value that "
        f"defaults to unmapped is a supply gap wearing a costume.")


def category_frame(con, path: pathlib.Path | None = None) -> pd.DataFrame:
    """(source, category_hint, loci_category, category_confidence) for every
    DISTINCT pair in the live filing table that a controlled vocabulary covers.

    Free-text sources are excluded entirely rather than emitted as 105,000 rows
    of NULL: the join that consumes this is a LEFT JOIN, so an absent row and a
    NULL row mean the same thing and the absent one costs nothing.
    """
    doc = load_category_map(path)
    controlled = [s for s, b in doc["sources"].items()
                  if b["vocabulary"] == "controlled"]
    if not controlled:
        return pd.DataFrame(columns=["source", "category_hint", "loci_category",
                                     "category_confidence"])
    holes = ", ".join("?" for _ in controlled)
    pairs = con.execute(
        f"SELECT DISTINCT source, category_hint FROM {FILING_TABLE} "
        f"WHERE source IN ({holes})", controlled).fetchall()
    rows = []
    for src, hint in pairs:
        cat, conf = loci_category_of(src, hint, path)
        rows.append({"source": src, "category_hint": hint,
                     "loci_category": cat, "category_confidence": conf})
    return pd.DataFrame(rows, columns=["source", "category_hint",
                                       "loci_category", "category_confidence"])


def unmapped_hints(con, path: pathlib.Path | None = None) -> dict[str, list[str]]:
    """{source: [values the yaml does not name]} over the live table. THE DRIFT
    CHECK -- tests/test_storefront_pipeline.py runs it, and `build` raises
    through `loci_category_of` before ever writing a row."""
    doc = load_category_map(path)
    out: dict[str, list[str]] = {}
    for sid, block in doc["sources"].items():
        if block["vocabulary"] != "controlled":
            continue
        seen = {r[0] for r in con.execute(
            f"SELECT DISTINCT category_hint FROM {FILING_TABLE} WHERE source = ?",
            [sid]).fetchall() if r[0] is not None}
        missing = sorted(seen - set(block["map"]) - block["unmapped"])
        if missing:
            out[sid] = missing
    return out


# ---------------------------------------------------------------------------
# the roll-up
# ---------------------------------------------------------------------------
def ensure_schema(con) -> None:
    """Apply sql/020_storefront_pipeline.sql. Idempotent."""
    con.execute(SQL_020.read_text())


def stage_rank_sql() -> str:
    """A VALUES table of (stage, rank) generated from filing_stages.STAGES.

    Generated, never written out by hand and never stored: sql/020 and
    filing_stages caveat 3 both turn on the rank being a BUILD-TIME fact, so
    that inserting `outdoor_dining` in the middle later renumbers nothing that
    lives on disk.
    """
    vals = ", ".join(f"('{s}', {stage_rank(s)})" for s in STAGES)
    return f"(VALUES {vals}) AS sr(stage, stage_rank)"


def _rollup_sql() -> str:
    """One row per pipeline group, straight out of the event log.

    The ordering expressions are arithmetic on purpose:
      `day_key`  = days since 1900-01-01, so a (date, rank) composite can be a
                   single number that arg_min/arg_max can order on;
      entry      = min over (date, then rank) -- a same-day liquor application
                   and fit-out resolve to the earlier-ranked stage, always;
      furthest   = max over (rank, then EARLIEST date within that rank), which
                   is `rank * 1e6 - day_key`. day_key is < 50,000 for any date
                   this century, so the two fields cannot collide.
    """
    open_list = ", ".join(f"'{s}'" for s in OPEN_EVIDENCE_STAGES)
    return f"""
    WITH ranked AS (
        SELECT f.*,
               sr.stage_rank,
               date_diff('day', DATE '1900-01-01', f.filed_on) AS day_key
        FROM {FILING_TABLE} f
        JOIN {stage_rank_sql()} ON sr.stage = f.stage
    ),
    keyed AS (
        SELECT *,
               (bbl IS NOT NULL AND business_name_key IS NOT NULL) AS keyed_ok,
               CASE WHEN bbl IS NOT NULL AND business_name_key IS NOT NULL
                    THEN 'bbl:' || bbl || '|name:' || business_name_key
                    ELSE 'filing:' || filing_id END AS pipeline_id
        FROM ranked
    ),
    hinted AS (
        SELECT k.*, c.loci_category, c.category_confidence
        FROM keyed k
        LEFT JOIN _filing_cat c
               ON c.source = k.source
              AND c.category_hint IS NOT DISTINCT FROM k.category_hint
    )
    SELECT
        pipeline_id,
        CASE WHEN bool_and(keyed_ok) THEN 'bbl_name' ELSE 'filing' END AS group_kind,
        -- Every text aggregate is CAST explicitly. An aggregate over a column
        -- that is NULL in every row of every group comes back typed INT32, and
        -- the frame then rejects a string the moment one appears -- which is
        -- the normal case on a single-source build, not an edge one.
        CAST(min(bbl) AS VARCHAR)                       AS bbl,
        CAST(min(business_name_key) AS VARCHAR)         AS business_name_key,
        CAST(mode(business_name) AS VARCHAR)            AS business_name,
        CAST(mode(borough) AS VARCHAR)                  AS borough,
        arg_min(lon, day_key) FILTER (WHERE lon IS NOT NULL)  AS lon_filing,
        arg_min(lat, day_key) FILTER (WHERE lat IS NOT NULL)  AS lat_filing,
        CAST(arg_min(stage, day_key * 100 + stage_rank) AS VARCHAR) AS entry_stage,
        min(filed_on)                                   AS entry_date,
        CAST(arg_max(stage, stage_rank) AS VARCHAR)     AS furthest_stage,
        arg_max(filed_on,  stage_rank * 1000000 - day_key) AS furthest_date,
        count(*)                                        AS n_filings,
        count(DISTINCT source)                          AS n_sources,
        list_distinct(list(source))                     AS source_list,
        list_distinct(list(stage))                      AS stage_list,
        -- The category comes from the FURTHEST-ALONG filing that has one: a
        -- DOHMH inspection knows the trade, a DOB fit-out filing does not.
        -- Ties inside one stage break on the earliest date, deterministically.
        CAST(arg_max(loci_category, stage_rank * 1000000 - day_key)
             FILTER (WHERE loci_category IS NOT NULL) AS VARCHAR)
                                                        AS loci_category,
        CAST(arg_max(category_confidence, stage_rank * 1000000 - day_key)
             FILTER (WHERE loci_category IS NOT NULL) AS VARCHAR)
                                                        AS category_confidence,
        CAST(arg_max(category_hint, stage_rank * 1000000 - day_key)
             FILTER (WHERE loci_category IS NOT NULL) AS VARCHAR)
                                                        AS category_hint,
        count(*) FILTER (WHERE stage IN ({open_list})) > 0   AS is_open,
        min(filed_on) FILTER (WHERE stage IN ({open_list}))  AS opened_on,
        CAST(arg_min(stage, day_key) FILTER (WHERE stage IN ({open_list}))
             AS VARCHAR)                                AS opened_on_stage,
        bool_or(bbl IS NULL)                            AS bbl_missing,
        bool_or(business_name_key IS NULL)              AS name_key_missing
    FROM hinted
    GROUP BY pipeline_id
    """


def _pluto_centroids(con, bbls: list[str]) -> pd.DataFrame:
    """(bbl, lon, lat) for the lots named, from the PLUTO index temp table.

    The index is built by model/storefront_filing.build_pluto_index, which is
    the ONE place PLUTO is read -- a second reader with its own filters would
    be a second spine, and the two would diverge silently.
    """
    if not bbls:
        return pd.DataFrame(columns=["bbl", "lon", "lat"])
    frame = pd.DataFrame({"bbl": pd.Series(bbls, dtype="string")})
    con.register("_want_bbl", frame)
    try:
        return con.execute("""
            SELECT p.bbl, p.lon, p.lat
            FROM _pluto_lot p JOIN _want_bbl w ON w.bbl = p.bbl
            WHERE p.lon IS NOT NULL AND p.lat IS NOT NULL
        """).fetchdf()
    finally:
        con.unregister("_want_bbl")


def compute_pipeline(con, *, asof: dt.date | None = None,
                     category_path: pathlib.Path | None = None,
                     pluto: bool = True) -> tuple[pd.DataFrame, dict]:
    """Roll the event log up. READ-ONLY on the warehouse.

    `pluto=True` fills a representative point for groups no feed geocoded, from
    the lot centroid. `pluto=False` skips that (tests, and any run that does
    not need the address measures).
    """
    asof = asof or dt.date.today()
    n_filings = con.execute(f"SELECT count(*) FROM {FILING_TABLE}").fetchone()[0]
    if not n_filings:
        raise RuntimeError(
            f"{FILING_TABLE} is empty -- refusing to build an empty pipeline. "
            f"Run `loci filings ingest` first; a zero here would read as "
            f"'nobody is opening anything in New York'.")

    cat = category_frame(con, category_path)          # raises on an unknown hint
    con.register("_filing_cat", cat)
    try:
        df = con.execute(_rollup_sql()).fetchdf()
    finally:
        con.unregister("_filing_cat")

    rank = {s: stage_rank(s) for s in STAGES}
    df["sources"] = [",".join(sorted(v)) for v in df["source_list"]]
    df["stages"] = [",".join(sorted(v, key=lambda s: rank[s]))
                    for v in df["stage_list"]]
    df = df.drop(columns=["source_list", "stage_list"])

    df["is_open"] = df["is_open"].astype(bool)
    df["bbl_missing"] = df["bbl_missing"].astype(bool)
    df["name_key_missing"] = df["name_key_missing"].astype(bool)
    df["category_confidence"] = df["category_confidence"].astype(object).where(
        df["category_confidence"].notna(), "unmapped")

    # LEAD DAYS. NULL -- never 0 -- when the earliest thing we saw is already a
    # terminal stage: a restaurant that first appears at its DOHMH inspection
    # has no measured lead time, and a zero would claim it opened the day it
    # filed. (sql/020 header.)
    entry_is_early = df["entry_stage"].isin(EARLY_STAGES)
    gap = (pd.to_datetime(df["opened_on"]) - pd.to_datetime(df["entry_date"])).dt.days
    df["lead_days"] = gap.where(entry_is_early & gap.notna() & (gap >= 0)).astype("Int64")

    # THE POINT. The feed's own coordinate first -- it is a published address
    # point, not a lot centroid -- and the PLUTO lot centroid only where no
    # feed geocoded the group at all. `point_source` says which, because the
    # two are not the same measurement (sql/020 caveat 3).
    df["lon"] = df["lon_filing"]
    df["lat"] = df["lat_filing"]
    has_filing_point = df["lon"].notna() & df["lat"].notna()
    df["point_source"] = None
    df.loc[has_filing_point, "point_source"] = "filing"
    n_from_pluto = 0
    if pluto:
        need = ~has_filing_point & df["bbl"].notna()
        if need.any():
            from loci.model import storefront_filing as sf
            if not con.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name = '_pluto_lot'").fetchone()[0]:
                sf.build_pluto_index(con)
            cent = _pluto_centroids(con, sorted(set(df.loc[need, "bbl"].dropna())))
            if len(cent):
                lut = cent.drop_duplicates("bbl").set_index("bbl")
                lon_fill = df["bbl"].map(lut["lon"]).where(need)
                lat_fill = df["bbl"].map(lut["lat"]).where(need)
                filled = need & lon_fill.notna() & lat_fill.notna()
                df.loc[filled, "lon"] = lon_fill[filled]
                df.loc[filled, "lat"] = lat_fill[filled]
                df.loc[filled, "point_source"] = "pluto_lot"
                n_from_pluto = int(filled.sum())
    df = df.drop(columns=["lon_filing", "lat_filing"])

    df["link_group_id"] = None
    df["link_method"] = None
    df["link_partner_id"] = None
    df["link_lead_days"] = pd.Series([pd.NA] * len(df), dtype="Int64")
    df["asof_date"] = asof
    df["built_at"] = pd.Timestamp(dt.datetime.now())

    # THE ROW-COUNT PROOF, computed here rather than trusted later: every
    # filing lands in exactly one group, so the group sizes must sum to the
    # event count. A fan-out in the roll-up would inflate every count below.
    if int(df["n_filings"].sum()) != n_filings:
        raise RuntimeError(
            f"storefront_pipeline: the roll-up covers {int(df['n_filings'].sum()):,} "
            f"filings but {FILING_TABLE} holds {n_filings:,}. A group fanned out "
            f"or dropped rows; every count downstream would be wrong.")

    report = {
        "asof": asof.isoformat(),
        "filings": int(n_filings),
        "rows": len(df),
        "by_group_kind": df["group_kind"].value_counts().to_dict(),
        "open": int(df["is_open"].sum()),
        "not_open": int((~df["is_open"]).sum()),
        "bbl_missing": int(df["bbl_missing"].sum()),
        "name_key_missing": int(df["name_key_missing"].sum()),
        "categorised": int(df["loci_category"].notna().sum()),
        "category_confidence": df["category_confidence"].value_counts().to_dict(),
        "points_from_pluto": n_from_pluto,
        "points_missing": int(df["lon"].isna().sum()),
        "with_lead_days": int(df["lead_days"].notna().sum()),
        "category_map_version": load_category_map(category_path)["version"],
    }
    return df, report


# ---------------------------------------------------------------------------
# the cross-agency reconciliation
# ---------------------------------------------------------------------------
def token_idf(name_keys) -> dict[str, float]:
    """Document idf of every token over the name-key vocabulary.

    The DOCUMENT here is a distinct `business_name_key`, not a filing: a chain
    that files 400 times must not make its own name look common, and a lot that
    files twice must not make its name look rare.
    """
    import collections
    docs = {k for k in name_keys if k}
    df = collections.Counter()
    for k in docs:
        for tok in set(str(k).split()):
            df[tok] += 1
    n = max(len(docs), 1)
    return {tok: math.log(n / c) for tok, c in df.items()}


def rare_shared_tokens(a: str | None, b: str | None, idf: dict[str, float],
                       min_idf: float = RARE_TOKEN_MIN_IDF) -> list[str]:
    """Tokens shared by two name keys that are rare enough to identify one
    business. Sorted rarest first, so a report can show WHY a link was made."""
    if not a or not b:
        return []
    shared = set(str(a).split()) & set(str(b).split())
    hits = [t for t in shared
            if len(t) >= RARE_TOKEN_MIN_LEN and not t.isdigit()
            and idf.get(t, 0.0) >= min_idf]
    return sorted(hits, key=lambda t: -idf.get(t, 0.0))


def reconcile(df: pd.DataFrame, *, window_days: int = LINK_WINDOW_DAYS,
              min_idf: float = RARE_TOKEN_MIN_IDF) -> tuple[pd.DataFrame, dict]:
    """Link an unopened early row to an opened row on the SAME BBL.

    Pure: takes and returns a frame, touches no database, so the tests drive it
    on a handful of synthetic rows where every pairing is known by construction.

    ONE-TO-ONE, GREEDY, AND IN THAT ORDER OF PREFERENCE:
      1. `rare_token`       -- the two names share a token whose document idf
                               over the whole name vocabulary clears `min_idf`.
      2. `sole_pair_in_bbl` -- the BBL offers exactly one candidate on each
                               side inside the window, so there is no ambiguity
                               to resolve.
    Ties inside a method break on the SHORTEST gap, then on the two
    pipeline_ids, so the assignment is reproducible under input reordering. A
    row already claimed is never claimed again: a many-to-many link would turn
    one build-out into several lead times and inflate every median, and fusing
    two businesses would manufacture a storefront that never existed.

    THE TERMINAL SIDE EXCLUDES ROWS THAT ALREADY HAVE A STRICT LEAD TIME.
    A row carrying both its own early filing and its own open signal is already
    measured (`lead_days`); linking it to a DIFFERENT name's early filing on the
    same lot would count one build-out twice -- once strict, once reconciled --
    and the reconciled N would rise without a single new business being
    measured. That is the double-count this project keeps being bitten by, so
    the reconciliation only ever ADDS pairs, never re-measures one.
    """
    import numpy as np

    out = df.reset_index(drop=True).copy()
    idf = token_idf(out["business_name_key"])

    bbl = out["bbl"].to_numpy(dtype=object)
    pid = out["pipeline_id"].to_numpy(dtype=object)
    names = out["business_name_key"].to_numpy(dtype=object)
    entry = pd.to_datetime(out["entry_date"]).to_numpy("datetime64[D]")
    opened = pd.to_datetime(out["opened_on"]).to_numpy("datetime64[D]")
    is_open = out["is_open"].to_numpy(dtype=bool)
    has_strict = out["lead_days"].notna().to_numpy()

    is_early = (out["bbl"].notna().to_numpy() & ~is_open
                & out["entry_date"].notna().to_numpy())
    is_term = (out["bbl"].notna().to_numpy() & is_open
               & out["opened_on"].notna().to_numpy() & ~has_strict)

    e_by_bbl: dict[object, list[int]] = {}
    for i in np.flatnonzero(is_early):
        e_by_bbl.setdefault(bbl[i], []).append(int(i))
    t_by_bbl: dict[object, list[int]] = {}
    for j in np.flatnonzero(is_term):
        t_by_bbl.setdefault(bbl[j], []).append(int(j))

    candidates: list[tuple[int, int, str, int, int, str]] = []
    n_bbl_both = 0
    for b, eidx in e_by_bbl.items():
        tidx = t_by_bbl.get(b)
        if not tidx:
            continue
        n_bbl_both += 1
        in_window = [(i, j, int((opened[j] - entry[i]).astype(int)))
                     for i in eidx for j in tidx
                     if 0 <= int((opened[j] - entry[i]).astype(int)) <= window_days]
        if not in_window:
            continue
        sole = (len({i for i, _, _ in in_window}) == 1
                and len({j for _, j, _ in in_window}) == 1)
        for i, j, gap in in_window:
            toks = rare_shared_tokens(names[i], names[j], idf, min_idf)
            if toks:
                candidates.append((0, gap, "rare_token", i, j, toks[0]))
            elif sole:
                candidates.append((1, gap, "sole_pair_in_bbl", i, j, ""))

    candidates.sort(key=lambda c: (c[0], c[1], str(pid[c[3]]), str(pid[c[4]])))

    claimed_e: set[int] = set()
    claimed_t: set[int] = set()
    links: list[tuple[int, int, str, int]] = []
    for _prio, gap, method, i, j in ((c[0], c[1], c[2], c[3], c[4])
                                     for c in candidates):
        if i in claimed_e or j in claimed_t:
            continue
        claimed_e.add(i)
        claimed_t.add(j)
        links.append((i, j, method, gap))

    out["link_group_id"] = None
    out["link_method"] = None
    out["link_partner_id"] = None
    out["link_lead_days"] = pd.Series([pd.NA] * len(out), index=out.index,
                                      dtype="Int64")
    by_method: dict[str, int] = {}
    for i, j, method, gap in links:
        gid = f"link:{pid[i]}~{pid[j]}"
        out.at[i, "link_group_id"] = gid
        out.at[j, "link_group_id"] = gid
        out.at[i, "link_method"] = method
        out.at[j, "link_method"] = method
        out.at[i, "link_partner_id"] = pid[j]
        out.at[j, "link_partner_id"] = pid[i]
        out.at[i, "link_lead_days"] = gap
        by_method[method] = by_method.get(method, 0) + 1

    report = {
        "bbls_with_both_sides": n_bbl_both,
        "candidate_pairs": len(candidates),
        "links": len(links),
        "links_by_method": by_method,
        "window_days": window_days,
        "min_idf": min_idf,
        "early_rows": int(is_early.sum()),
        "terminal_rows_available": int(is_term.sum()),
        "terminal_rows_already_strict": int((is_open & has_strict).sum()),
    }
    return out, report


# ---------------------------------------------------------------------------
# write + validate
# ---------------------------------------------------------------------------
COLUMNS = [
    "pipeline_id", "group_kind", "bbl", "business_name_key", "business_name",
    "borough", "lon", "lat", "point_source", "entry_stage", "entry_date",
    "furthest_stage", "furthest_date", "n_filings", "n_sources", "sources",
    "stages", "loci_category", "category_confidence", "category_hint",
    "is_open", "opened_on", "opened_on_stage", "lead_days", "bbl_missing",
    "name_key_missing", "link_group_id", "link_method", "link_partner_id",
    "link_lead_days", "asof_date", "built_at",
]


def write(con, frame: pd.DataFrame) -> int:
    """Replace the whole table. DELETE + INSERT inside one transaction.

    A full replace, unlike staging.storefront_filing's per-source write,
    because this table is a roll-up OVER ALL SOURCES: a partial rebuild would
    leave groups assembled from a stale half of the event log, and the link
    pass is global by construction.
    """
    ensure_schema(con)
    absent = [c for c in COLUMNS if c not in frame.columns]
    if absent:
        raise RuntimeError(f"storefront_pipeline: frame is missing {absent}")
    payload = frame[COLUMNS]
    # `geom` is derived at write time from (lon, lat) and is NOT in COLUMNS: it
    # is EPSG:4326 BY CONVENTION, like everything else in this warehouse --
    # DuckDB GEOMETRY carries no SRID and will not catch a violation.
    insert_cols = ", ".join([*COLUMNS, "geom"])
    select_cols = ", ".join([
        *COLUMNS,
        "CASE WHEN lon IS NOT NULL AND lat IS NOT NULL "
        "THEN ST_Point(lon, lat) END",
    ])
    con.execute("BEGIN")
    try:
        con.execute(f"DELETE FROM {TABLE}")
        con.register("_sp", payload)
        con.execute(f"INSERT INTO {TABLE} ({insert_cols}) "
                    f"SELECT {select_cols} FROM _sp")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_sp")
    return len(payload)


def validate(con, frame: pd.DataFrame) -> list[str]:
    """Prove the write on the WAREHOUSE, not on the frame. Returns problems."""
    problems: list[str] = []

    n_db = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    if n_db != len(frame):
        problems.append(f"row count {n_db:,} != frame {len(frame):,}")

    # (1) The conservation law: every filing is in exactly one group.
    n_filings = con.execute(f"SELECT count(*) FROM {FILING_TABLE}").fetchone()[0]
    n_covered = con.execute(f"SELECT sum(n_filings) FROM {TABLE}").fetchone()[0] or 0
    if int(n_covered) != int(n_filings):
        problems.append(
            f"n_filings sums to {int(n_covered):,} but {FILING_TABLE} holds "
            f"{int(n_filings):,} -- the roll-up dropped or duplicated events")

    # (2) The grain.
    dupes = con.execute(
        f"SELECT count(*) FROM (SELECT pipeline_id FROM {TABLE} "
        f"GROUP BY 1 HAVING count(*) > 1)").fetchone()[0]
    if dupes:
        problems.append(f"{dupes:,} duplicated pipeline_id -- the grain is broken")

    # (3) The D75 carry rules: a 'bbl_name' row has both keys, a 'filing' row
    #     is missing at least one, and NOTHING was dropped.
    bad = con.execute(f"""
        SELECT count(*) FROM {TABLE}
        WHERE (group_kind = 'bbl_name'
               AND (bbl IS NULL OR business_name_key IS NULL))
           OR (group_kind = 'filing' AND bbl IS NOT NULL
               AND business_name_key IS NOT NULL)
    """).fetchone()[0]
    if bad:
        problems.append(f"{bad:,} rows disagree with their group_kind")

    # (4) is_open and opened_on are the same fact stated twice.
    bad_open = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE is_open <> (opened_on IS NOT NULL)"
    ).fetchone()[0]
    if bad_open:
        problems.append(f"{bad_open:,} rows have is_open disagreeing with opened_on")

    # (5) A lead time can never be negative, and never exists without an open.
    bad_lead = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE lead_days < 0 "
        f"OR (lead_days IS NOT NULL AND opened_on IS NULL)").fetchone()[0]
    if bad_lead:
        problems.append(f"{bad_lead:,} rows carry an impossible lead_days")

    # (6) THE LINK IS ONE-TO-ONE. This is the double-count guard: a partner id
    #     claimed twice would multiply one build-out into several lead times.
    dup_partner = con.execute(
        f"SELECT count(*) FROM (SELECT link_partner_id FROM {TABLE} "
        f"WHERE link_partner_id IS NOT NULL GROUP BY 1 HAVING count(*) > 1)"
    ).fetchone()[0]
    if dup_partner:
        problems.append(
            f"{dup_partner:,} link_partner_ids are claimed by more than one row "
            f"-- one build-out would produce several lead times")

    # (7) The link is symmetric: if A points at B, B points back at A.
    asym = con.execute(f"""
        SELECT count(*) FROM {TABLE} a
        WHERE a.link_partner_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM {TABLE} b
                          WHERE b.pipeline_id = a.link_partner_id
                            AND b.link_partner_id = a.pipeline_id)
    """).fetchone()[0]
    if asym:
        problems.append(f"{asym:,} links are not symmetric")

    # (8) A link never crosses a lot line.
    cross = con.execute(f"""
        SELECT count(*) FROM {TABLE} a
        JOIN {TABLE} b ON b.pipeline_id = a.link_partner_id
        WHERE a.bbl IS DISTINCT FROM b.bbl
    """).fetchone()[0]
    if cross:
        problems.append(f"{cross:,} links join two different BBLs")

    # (9) Every stage string is in the vocabulary.
    holes = ", ".join("?" for _ in STAGES)
    bad_stage = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE entry_stage NOT IN ({holes}) "
        f"OR furthest_stage NOT IN ({holes})",
        [*STAGES, *STAGES]).fetchone()[0]
    if bad_stage:
        problems.append(f"{bad_stage:,} rows carry a stage outside the vocabulary")

    # (10) THE liquor_active WINDOW, re-measured. sql/020's whole defence of
    #      including liquor_active in `opened_on` is that SLA's fetch is
    #      windowed, so no decades-old renewal is present. If that stops being
    #      true this is where it shows.
    row = con.execute(
        f"SELECT min(opened_on) FROM {TABLE} WHERE opened_on_stage = 'liquor_active'"
    ).fetchone()
    oldest = row[0] if row else None
    if oldest is not None:
        asof = con.execute(f"SELECT max(asof_date) FROM {TABLE}").fetchone()[0]
        if asof and (asof - oldest).days > 365 * 4:
            problems.append(
                f"the oldest liquor_active opened_on is {oldest} ({(asof - oldest).days} "
                f"days before asof). SLA's originalissuedate is the premises' FIRST "
                f"licence date; a window this wide means `opened_on` is dating "
                f"renewals as openings (sql/020 header).")
    return problems


def build(con, *, asof: dt.date | None = None, dry_run: bool = False,
          category_path: pathlib.Path | None = None,
          reconcile_links: bool = True,
          pluto: bool = True) -> tuple[pd.DataFrame, dict]:
    """Roll up, reconcile, write, validate."""
    df, report = compute_pipeline(con, asof=asof, category_path=category_path,
                                  pluto=pluto)
    if reconcile_links:
        df, link_report = reconcile(df)
        report["reconcile"] = link_report
    if dry_run:
        report["_written"] = 0
        return df, report
    report["_written"] = write(con, df)
    report["_problems"] = validate(con, df)
    return df, report


# ---------------------------------------------------------------------------
# the lead-time table
# ---------------------------------------------------------------------------
#: (early, terminal) pairs that are NOT a go-live lead time: both filings are
#: the SAME AGENCY's own processing clock, not a build-out.
#:
#:   license_application -> license_issued   DCWP application -> DCWP licence.
#:       Mirrors model/storefront_filing.SAME_AGENCY_PAIRS; 5,206 pairs at a
#:       median of 11 days. Pooling it reports "New York opens a storefront in
#:       38 days" when what was measured is how fast DCWP stamps a form.
#:
#:   liquor_application -> liquor_active     SLA pending -> SLA active. ADDED
#:       HERE, not present in storefront_filing, because `liquor_active` is not
#:       in OPEN_STAGES there and so the pair could not arise. It arises the
#:       moment `is_open` widens to the three open-evidence stages, and it is
#:       the same artefact: 560 strict pairs at a median of 26 days is the
#:       State Liquor Authority's queue, not a fit-out.
SAME_AGENCY_PAIRS = (
    ("license_application", "license_issued"),
    ("liquor_application", "liquor_active"),
)


def _same_agency_sql(alias_first: str, alias_open: str) -> str:
    tests = " OR ".join(
        f"({alias_first} = '{a}' AND {alias_open} = '{b}')"
        for a, b in SAME_AGENCY_PAIRS)
    return f"CASE WHEN {tests} THEN 'same_agency_processing' ELSE 'cross_agency' END"


def lead_table(con, *, match: str = "strict", min_n: int = 1) -> pd.DataFrame:
    """(first_stage -> open_stage) lead times, cut by how the pair was made.

    `match='strict'`      only pairs whose two filings shared a name key on one
                          BBL -- an OBSERVATION, and the REFERENCE number.
    `match='reconciled'`  strict pairs PLUS the cross-agency links -- strict
                          plus an INFERENCE. Reported beside the reference,
                          never instead of it.

    Both exclude `same_agency_processing` pairs; `lead_table_same_agency` has
    those on their own.
    """
    if match not in ("strict", "reconciled"):
        raise ValueError(f"match must be 'strict' or 'reconciled', got {match!r}")
    where = "" if match == "reconciled" else "WHERE match_kind = 'strict'"
    kind = _same_agency_sql("first_stage", "open_stage")
    return con.execute(f"""
        WITH p AS (
            SELECT *, {kind} AS pair_kind
            FROM analysis.storefront_pipeline_lead
            {where}
        )
        SELECT first_stage, open_stage,
               count(*)                                     AS n,
               count(*) FILTER (WHERE match_kind = 'strict')  AS n_strict,
               count(*) FILTER (WHERE match_kind <> 'strict') AS n_linked,
               median(lead_days)                            AS median_days,
               quantile_cont(lead_days, 0.25)               AS p25_days,
               quantile_cont(lead_days, 0.75)               AS p75_days
        FROM p
        WHERE pair_kind = 'cross_agency'
        GROUP BY 1, 2
        HAVING count(*) >= {int(min_n)}
        ORDER BY n DESC
    """).fetchdf()


#: The three pairs the owner named. Reported strict vs reconciled side by side.
HEADLINE_PAIRS = (
    ("fitout_filing", "first_inspection"),
    ("liquor_application", "first_inspection"),
    ("fitout_filing", "license_issued"),
)


def headline_leads(con) -> pd.DataFrame:
    """One row per HEADLINE_PAIRS entry: N and median, strict and reconciled.

    `delta_n` is the whole point of the reconciliation and is printed beside
    `median_strict` so the two can never be quoted as one number.
    """
    strict = lead_table(con, match="strict").set_index(["first_stage", "open_stage"])
    recon = lead_table(con, match="reconciled").set_index(["first_stage", "open_stage"])
    rows = []
    for first, open_ in HEADLINE_PAIRS:
        s = strict.loc[(first, open_)] if (first, open_) in strict.index else None
        r = recon.loc[(first, open_)] if (first, open_) in recon.index else None
        rows.append({
            "first_stage": first, "open_stage": open_,
            "n_strict": int(s["n"]) if s is not None else 0,
            "median_strict": float(s["median_days"]) if s is not None else None,
            "n_reconciled": int(r["n"]) if r is not None else 0,
            "median_reconciled": float(r["median_days"]) if r is not None else None,
            "n_linked": int(r["n_linked"]) if r is not None else 0,
        })
    out = pd.DataFrame(rows)
    out["delta_n"] = out["n_reconciled"] - out["n_strict"]
    return out


# ---------------------------------------------------------------------------
# the first-seen ledger: kind 'gov_filing'
# ---------------------------------------------------------------------------
def _ledger_candidates(con, *, asof: dt.date) -> pd.DataFrame:
    """Ledger rows matched to a pipeline row, with the pipeline's opened_on.

    THE TWO JOINS, and why neither is the obvious one:

      `bbl_name`  the ledger POI's own coordinate, snapped to the nearest PLUTO
                  lot centroid within 30 m (model/storefront_filing's ladder,
                  the SAME rung and the SAME METRES_SQL), joined to the pipeline
                  BBL, AND the brand keys equal.
      `name_dist` brand keys equal and the two points within
                  LEDGER_NAME_DIST_M. Rescues the big mixed-use lots where the
                  centroid is further from the door than 30 m -- which is
                  exactly where ground-floor retail concentrates.

    THE BRAND KEY IS RECOMPUTED, NOT JOINED FROM `poi_presence.name_key`.
    The ledger's `name_key` is `score.dedup.norm_tokens` sorted and joined; the
    pipeline's is `chains.normalize.brand_key`. They are DIFFERENT NORMALIZERS
    and joining them would match almost nothing while reporting a clean run.
    `chains/detect.py` applies brand_key in Python for the same reason.
    """
    led = con.execute("""
        SELECT location_key, category, display_name, lon, lat,
               first_seen_kind, first_seen_month, first_seen_src_date
        FROM analysis.poi_presence
        WHERE lon IS NOT NULL AND lat IS NOT NULL
    """).fetchdf()
    if led.empty:
        return led.assign(bbl=None, brand=None, opened_on=None, match_method=None)
    led["brand"] = [brand_key(n) for n in led["display_name"]]
    led = led[led["brand"].notna()].reset_index(drop=True)

    metres = METRES_SQL.format(a="p.geom", b="ST_Point(l.lon, l.lat)")
    con.register("_led", led[["location_key", "brand", "lon", "lat"]])
    try:
        # Rung 1: nearest PLUTO lot within 30 m -- the SAME rung and the SAME
        # METRES_SQL as model/storefront_filing's ladder, but BLOCKED ON A GRID
        # rather than joined on two BETWEENs. The degree-box form is an
        # inequality join, and 227k ledger points against 859k lots does not
        # finish in useful time; bucketing both sides into 0.0005-degree cells
        # (~55 m N-S, ~42 m E-W at this latitude) and expanding the ledger side
        # over its 3x3 neighbourhood turns it into a hash join that does.
        #
        # THE BLOCKING IS A PREFILTER AND NOTHING ELSE. A 3x3 neighbourhood of
        # 42 m cells reaches at least 42 m in every direction from any point in
        # the centre cell, so no lot inside the 30 m radius can be outside the
        # block. The exact test is still METRES_SQL, which flips (lon, lat) to
        # (lat, lon) because ST_Distance_Sphere reads it that way (D16) -- a
        # degree box is not a circle and 1 degree of longitude is 84 km here,
        # not 111.
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _led_bbl AS
            WITH lot AS (
                SELECT bbl, geom,
                       CAST(floor(lat / 0.0005) AS BIGINT) AS cy,
                       CAST(floor(lon / 0.0005) AS BIGINT) AS cx
                FROM _pluto_lot
                WHERE lat IS NOT NULL AND lon IS NOT NULL
            ), led AS (
                SELECT l.location_key, l.lon, l.lat,
                       CAST(floor(l.lat / 0.0005) AS BIGINT) + dy AS cy,
                       CAST(floor(l.lon / 0.0005) AS BIGINT) + dx AS cx
                FROM _led l,
                     (VALUES (-1), (0), (1)) AS ny(dy),
                     (VALUES (-1), (0), (1)) AS nx(dx)
            )
            SELECT * EXCLUDE (d, rn) FROM (
                SELECT l.location_key, p.bbl, {metres} AS d,
                       row_number() OVER (PARTITION BY l.location_key
                                          ORDER BY {metres}, p.bbl) AS rn
                FROM led l JOIN lot p USING (cy, cx)
            ) WHERE rn = 1 AND d <= 30.0
        """)
        pipe_metres = METRES_SQL.format(a="ST_Point(s.lon, s.lat)",
                                        b="ST_Point(l.lon, l.lat)")
        matched = con.execute(f"""
            WITH cand AS (
                SELECT l.location_key, s.pipeline_id, s.opened_on,
                       'bbl_name' AS match_method, 0 AS prio
                FROM _led l
                JOIN _led_bbl b ON b.location_key = l.location_key
                JOIN {TABLE} s ON s.bbl = b.bbl
                                AND s.business_name_key = l.brand
                WHERE s.opened_on IS NOT NULL
                UNION ALL
                SELECT l.location_key, s.pipeline_id, s.opened_on,
                       'name_dist' AS match_method, 1 AS prio
                FROM _led l
                JOIN {TABLE} s ON s.business_name_key = l.brand
                WHERE s.opened_on IS NOT NULL
                  AND s.lon IS NOT NULL AND s.lat IS NOT NULL
                  AND s.lat BETWEEN l.lat - 0.0010 AND l.lat + 0.0010
                  AND s.lon BETWEEN l.lon - 0.0013 AND l.lon + 0.0013
                  AND {pipe_metres} <= {LEDGER_NAME_DIST_M}
            )
            SELECT location_key,
                   min(opened_on)                          AS opened_on,
                   arg_min(match_method, prio * 1000000
                           + date_diff('day', DATE '1900-01-01', opened_on))
                                                           AS match_method,
                   arg_min(pipeline_id, prio * 1000000
                           + date_diff('day', DATE '1900-01-01', opened_on))
                                                           AS pipeline_id,
                   count(DISTINCT pipeline_id)             AS n_pipeline_rows
            FROM cand
            GROUP BY location_key
        """).fetchdf()
    finally:
        con.unregister("_led")
    if matched.empty:
        return matched
    out = led.merge(matched, on="location_key", how="inner")
    # THE DATA BOUND, not a claim about retail history: a sentinel date or a
    # typo must never become a first-seen.
    ok = (pd.to_datetime(out["opened_on"]).dt.date >= GOV_FILING_MIN_DATE) & \
         (pd.to_datetime(out["opened_on"]).dt.date <= asof)
    return out[ok].reset_index(drop=True)


def apply_gov_filing(con, *, asof: dt.date | None = None,
                     dry_run: bool = False) -> dict:
    """Set `first_seen_kind = 'gov_filing'` where a filing dates a storefront
    earlier than the ledger could, or dates a LEFT-CENSORED row at all.

    ONLY EARLIER, EVER. The WHERE clause below requires either
    `first_seen_kind = 'backfill_censored'` (the date was unknown and unbounded
    below) or a STRICTLY earlier date than the one held. That strict inequality
    is also what makes this idempotent: after one run the condition is false
    for every row it wrote, so a second run updates nothing.

    NEVER AN APPLICATION DATE. The join reads `opened_on`, which exists only
    for rows carrying a `license_issued`, `liquor_active` or `first_inspection`
    filing. An application, a permit and a fit-out filing are dates on which
    somebody INTENDED to open; using one would date a storefront to a year
    before it existed.
    """
    from loci.model import poi_presence as pp
    from loci.model import storefront_filing as sf

    asof = asof or dt.date.today()
    have = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = "
        "'analysis' AND table_name = 'poi_presence'").fetchone()[0]
    if not have:
        raise RuntimeError(
            "analysis.poi_presence does not exist. Run `loci poi-snapshot` "
            "before dating the ledger from filings.")
    if not con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]:
        raise RuntimeError(
            f"{TABLE} is empty -- run `loci storefront-pipeline build` first. "
            f"Reporting 'no censored rows resolved' off an empty table would be "
            f"a finding about the city rather than about the run.")
    if not dry_run:
        ensure_schema(con)

    before = dict(con.execute(
        "SELECT first_seen_kind, count(*) FROM analysis.poi_presence "
        "GROUP BY 1 ORDER BY 1").fetchall())

    sf.build_pluto_index(con)
    cand = _ledger_candidates(con, asof=asof)
    report = {
        "asof": asof.isoformat(),
        "ledger_rows": sum(before.values()),
        "kinds_before": before,
        "matched_locations": len(cand),
        "match_methods": (cand["match_method"].value_counts().to_dict()
                          if len(cand) else {}),
    }
    if cand.empty:
        report["kinds_after"] = before
        report["updated"] = 0
        report["censored_resolved"] = 0
        return report

    con.register("_gov", cand[["location_key", "opened_on", "match_method",
                               "pipeline_id"]])
    try:
        # Which rows WOULD move, counted before the write so the report is a
        # statement about this run rather than a diff of two counts.
        eligible = con.execute(f"""
            SELECT g.location_key, pp.first_seen_kind
            FROM _gov g JOIN analysis.poi_presence pp USING (location_key)
            WHERE pp.first_seen_kind = 'backfill_censored'
               OR (pp.first_seen_src_date IS NOT NULL
                   AND g.opened_on < pp.first_seen_src_date)
               OR (pp.first_seen_src_date IS NULL
                   AND strftime(g.opened_on, '%Y-%m') < pp.first_seen_month)
        """).fetchdf()
        report["eligible"] = len(eligible)
        report["eligible_by_prior_kind"] = (
            eligible["first_seen_kind"].value_counts().to_dict() if len(eligible) else {})
        if dry_run:
            report["updated"] = 0
            report["kinds_after"] = before
            report["censored_resolved"] = 0
            return report
        con.execute("BEGIN")
        try:
            con.execute(f"""
                UPDATE analysis.poi_presence AS pp
                SET first_seen_kind      = '{GOV_FILING_KIND}',
                    first_seen_src_date  = g.opened_on,
                    first_seen_src_field = '{GOV_FILING_FIELD}',
                    first_seen_month     = strftime(g.opened_on, '%Y-%m')
                FROM _gov g
                WHERE g.location_key = pp.location_key
                  AND (pp.first_seen_kind = 'backfill_censored'
                       OR (pp.first_seen_src_date IS NOT NULL
                           AND g.opened_on < pp.first_seen_src_date)
                       OR (pp.first_seen_src_date IS NULL
                           AND strftime(g.opened_on, '%Y-%m') < pp.first_seen_month))
            """)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.unregister("_gov")

    after = dict(con.execute(
        "SELECT first_seen_kind, count(*) FROM analysis.poi_presence "
        "GROUP BY 1 ORDER BY 1").fetchall())
    report["kinds_after"] = after
    report["updated"] = after.get(GOV_FILING_KIND, 0) - before.get(GOV_FILING_KIND, 0)
    report["censored_resolved"] = (before.get("backfill_censored", 0)
                                   - after.get("backfill_censored", 0))
    report["kinds_vocabulary"] = list(pp.KINDS)
    return report


# ---------------------------------------------------------------------------
# the address measures
# ---------------------------------------------------------------------------
def _months_before(asof: dt.date, months: int) -> dt.date:
    """asof minus `months` calendar months, clamped to a valid day-of-month.
    Same arithmetic as model/dev_pipeline._months_before, so two windows named
    '18 months' in this project mean the same 18 months."""
    total = asof.month - 1 - months
    year = asof.year + total // 12
    month = total % 12 + 1
    leap = year % 4 == 0 and (year % 100 or year % 400 == 0)
    day = min(asof.day, [31, 29 if leap else 28, 31, 30, 31, 30,
                         31, 31, 30, 31, 30, 31][month - 1])
    return dt.date(year, month, day)


def load_pipeline_points(con, asof: dt.date) -> tuple[pd.DataFrame, dict]:
    """Pipeline rows that carry BOTH a Loci category and a point, with the two
    window flags. Everything else contributes to nothing and is counted."""
    pipeline_cut = _months_before(asof, OPENINGS_PIPELINE_MONTHS)
    recent_cut = _months_before(asof, OPENINGS_RECENT_MONTHS)
    df = con.execute(f"""
        SELECT pipeline_id, loci_category AS category, lon, lat, point_source,
               (NOT is_open AND entry_date >= DATE '{pipeline_cut}'
                            AND entry_date <= DATE '{asof}')       AS w_pipeline,
               (opened_on IS NOT NULL AND opened_on >= DATE '{recent_cut}'
                                     AND opened_on <= DATE '{asof}') AS w_recent
        FROM {TABLE}
        WHERE loci_category IS NOT NULL
          AND lon IS NOT NULL AND lat IS NOT NULL
    """).fetchdf()
    total, categorised, placed = con.execute(f"""
        SELECT count(*),
               count(*) FILTER (WHERE loci_category IS NOT NULL),
               count(*) FILTER (WHERE loci_category IS NOT NULL
                                  AND lon IS NOT NULL)
        FROM {TABLE}""").fetchone()
    report = {
        "pipeline_rows": int(total),
        "categorised": int(categorised),
        "categorised_and_placed": int(placed),
        "in_pipeline_window": int(df["w_pipeline"].sum()) if len(df) else 0,
        "in_recent_window": int(df["w_recent"].sum()) if len(df) else 0,
        "pipeline_window_from": pipeline_cut.isoformat(),
        "recent_window_from": recent_cut.isoformat(),
        "point_source": (df["point_source"].value_counts().to_dict()
                         if len(df) else {}),
    }
    if df.empty or not (df["w_pipeline"].any() or df["w_recent"].any()):
        raise RuntimeError(
            "no categorised, placed pipeline rows fall in either window. "
            "Writing zeros onto every address would read as 'nothing is "
            "opening anywhere in New York', which is a confident false "
            "negative, not a missing value. Check `loci storefront-pipeline "
            "stats` first.")
    return df, report


def compute_openings(con, boroughs: list[str] | None, *,
                     asof: dt.date | None = None,
                     radius_m: float | None = None,
                     graph_path: pathlib.Path | None = None,
                     batch: int | None = None) -> tuple[pd.DataFrame, dict]:
    """(long frame of address_id/borough/category + OPENINGS_COLUMNS, report).

    READ-ONLY on the warehouse. ONE sweep for BOTH measures and all fifteen
    categories: the query nodes and the radius are identical, so a second pass
    would buy a second Dijkstra to compute a column the first pass could have
    produced as another weight vector (model/address_access makes the same
    choice for the same reason).

    THE ENGINE IS REUSED, NOT RE-IMPLEMENTED. `score/access._prune` + `_to_csr`
    build the undirected CSR walk graph -- read that function's comment on NOT
    mirroring edges manually, which is the bug that doubled every distance once
    already -- and `model/supply_ratio.catchment_sums` does the bounded sweep.
    No ST_DWithin, no straight lines: 400 m NETWORK is the project's one
    definition of within reach.
    """
    import pickle

    import numpy as np
    import osmnx as ox

    from loci.model.conveniences import graph_version
    from loci.model.supply_ratio import BATCH, catchment_sums, node_weights
    from loci.score.access import MIN_COMPONENT, THRESHOLDS, _prune, _to_csr
    from loci.score.walkgraph import OUT as GRAPH_PATH

    asof = asof or dt.date.today()
    radius_m = float(radius_m if radius_m is not None else THRESHOLDS[5])
    graph_path = pathlib.Path(graph_path or GRAPH_PATH)
    batch = int(batch or BATCH)

    pts, report = load_pipeline_points(con, asof)

    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        addr = con.execute(
            f"SELECT address_id, borough, lon, lat FROM analysis.address "
            f"WHERE borough IN ({holes}) ORDER BY borough, address_id",
            list(boroughs)).fetchdf()
    else:
        addr = con.execute(
            "SELECT address_id, borough, lon, lat FROM analysis.address "
            "ORDER BY borough, address_id").fetchdf()
    if addr.empty:
        raise RuntimeError(
            f"no addresses in analysis.address for boroughs={boroughs}. Run "
            f"`loci address-gaps` first; an empty frame would RESET every "
            f"column to NULL and write nothing back.")

    with graph_path.open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)
    n_nodes = A.shape[0]

    p_nodes = ox.distance.nearest_nodes(
        Gp, X=pts["lon"].tolist(), Y=pts["lat"].tolist())
    p_nidx = np.array([idx[n] for n in np.atleast_1d(p_nodes)], dtype=np.int64)

    # One weight column per (category, measure). Points are ACCUMULATED, never
    # deduplicated: two filings on one corner are two filings, and two pipeline
    # rows snapped to one graph node are two businesses.
    cats = sorted(CATEGORIES)
    keys = [(c, m) for c in cats for m in ("pipeline", "recent")]
    nodes_of, weights = {}, {}
    for c, m in keys:
        sel = ((pts["category"] == c)
               & (pts["w_pipeline"] if m == "pipeline" else pts["w_recent"])).to_numpy()
        nodes_of[(c, m)] = p_nidx[sel]
        weights[(c, m)] = np.ones(int(sel.sum()), dtype=np.float64)
    W = node_weights(idx, nodes_of, weights, n_nodes)

    a_nodes = ox.distance.nearest_nodes(
        Gp, X=addr["lon"].tolist(), Y=addr["lat"].tolist())
    a_nidx = np.array([idx[n] for n in np.atleast_1d(a_nodes)], dtype=np.int64)
    uniq, inv = np.unique(a_nidx, return_inverse=True)
    acc = catchment_sums(A, uniq, W, radius_m=radius_m, batch=batch)[inv]

    run_at = dt.datetime.now()
    frames = []
    for ci, c in enumerate(cats):
        frames.append(pd.DataFrame({
            "address_id": addr["address_id"].to_numpy(),
            "borough": addr["borough"].to_numpy(),
            "category": c,
            "openings_pipeline_400m": np.rint(acc[:, keys.index((c, "pipeline"))]).astype("int64"),
            "openings_recent_400m": np.rint(acc[:, keys.index((c, "recent"))]).astype("int64"),
        }))
    out = pd.concat(frames, ignore_index=True)
    out["openings_radius_m"] = radius_m
    out["openings_asof"] = asof
    out["openings_run_at"] = run_at

    report.update({
        "boroughs": list(boroughs) if boroughs else "ALL",
        "radius_m": radius_m,
        "graph_version": graph_version(graph_path),
        "addresses": len(addr),
        "query_nodes": int(uniq.size),
        "rows": len(out),
        "asof": asof.isoformat(),
        "run_at": run_at.isoformat(timespec="seconds"),
        # Coverage, stated rather than assumed. A zero is a real observation.
        "address_categories_with_pipeline": int((out["openings_pipeline_400m"] > 0).sum()),
        "address_categories_with_recent": int((out["openings_recent_400m"] > 0).sum()),
        "max_pipeline_400m": int(out["openings_pipeline_400m"].max()),
        "max_recent_400m": int(out["openings_recent_400m"].max()),
    })
    return out, report


def _guard(cols: list[str]) -> None:
    """Refuse to write if the SET list touches a column another module owns.
    Belt and braces; tests/test_storefront_pipeline.py is the real guard."""
    forbidden: set[str] = set()
    try:
        from loci.model.address_access import ACCESS_COLUMNS
        from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
        from loci.model.address_gaps import (
            ADDRESS_CATEGORY_SCREEN_COLUMNS,
            ADDRESS_COLUMNS,
        )
        from loci.model.dev_pipeline import PIPELINE_COLUMNS
        from loci.model.storefronts import AGE_FIT_COLUMNS, STOREFRONT_COLUMNS
        from loci.model.supply_ratio import (
            ADDRESS_RATIO_COLUMNS,
            CATEGORY_RATIO_COLUMNS,
        )
        forbidden |= set(ADDRESS_COLUMNS) | set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
        forbidden |= set(PIPELINE_COLUMNS) | set(STOREFRONT_COLUMNS)
        forbidden |= set(AGE_FIT_COLUMNS) | set(DEMAND_ANNOTATION_COLUMNS)
        forbidden |= set(ADDRESS_RATIO_COLUMNS) | set(CATEGORY_RATIO_COLUMNS)
        forbidden |= set(ACCESS_COLUMNS)
    except ImportError:                                     # pragma: no cover
        pass
    overlap = sorted(set(cols) & forbidden)
    if overlap:
        raise RuntimeError(
            f"storefront-pipeline would clobber analysis.address_category "
            f"columns another module owns: {overlap}")


def write_openings(con, df: pd.DataFrame, boroughs: list[str] | None) -> int:
    """UPDATE-only on analysis.address_category. RESET then UPDATE, in scope.

    RESET first for the reason every sibling annotation resets: an address that
    had a filing nearby on the last run and does not on this one (the window
    rolled, the filing opened) would otherwise keep last run's number forever
    -- UPDATE has no DELETE to fall back on.
    """
    _guard(OPENINGS_COLUMNS)
    absent = [c for c in OPENINGS_COLUMNS if c not in df.columns]
    if absent:
        raise RuntimeError(
            f"frame is missing {absent}; every column in OPENINGS_COLUMNS is "
            f"reset to NULL below, so a partial frame would blank them.")
    reset = ", ".join(f"{c} = NULL" for c in OPENINGS_COLUMNS)
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        con.execute(f"UPDATE analysis.address_category SET {reset} "
                    f"WHERE borough IN ({holes})", list(boroughs))
    else:
        con.execute(f"UPDATE analysis.address_category SET {reset}")
    if df.empty:
        return 0
    payload = df[["address_id", "borough", "category", *OPENINGS_COLUMNS]]
    con.register("_op", payload)
    try:
        sets = ", ".join(f"{c} = _op.{c}" for c in OPENINGS_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address_category AS ac SET {sets}
            FROM _op
            WHERE ac.address_id = _op.address_id
              AND ac.borough = _op.borough
              AND ac.category = _op.category
        """)
    finally:
        con.unregister("_op")
    return len(payload)


def build_openings(con, boroughs: list[str] | None, *,
                   asof: dt.date | None = None, radius_m: float | None = None,
                   graph_path: pathlib.Path | None = None,
                   dry_run: bool = False) -> tuple[pd.DataFrame, dict]:
    """compute + write."""
    ensure_schema(con)
    df, report = compute_openings(con, boroughs, asof=asof, radius_m=radius_m,
                                  graph_path=graph_path)
    if not dry_run:
        report["_written"] = write_openings(con, df, boroughs)
        report["_problems"] = validate_openings(con, boroughs)
    return df, report


OPENINGS_VALIDATION_SQL = """
-- Proves it on the WAREHOUSE, not on the frame. The no-missing rule is the
-- load-bearing one: EVERY in-scope address x category must carry BOTH numbers,
-- because 0 is a value and a NULL would be read as a zero by anything that
-- COALESCEs. A pipeline row within 400 m of N addresses is counted N times BY
-- DESIGN -- these are per-address catchments, not a partition -- so the right
-- check is not "does the sum match the pipeline", it is "is the MAX per
-- address below the citywide total", which a double-count inside one catchment
-- would break.
SELECT borough,
       category,
       count(*)                                            AS rows,
       count(openings_pipeline_400m)                       AS have_pipeline,
       count(openings_recent_400m)                         AS have_recent,
       sum(CASE WHEN openings_pipeline_400m > 0 THEN 1 ELSE 0 END) AS pipeline_nonzero,
       sum(CASE WHEN openings_recent_400m   > 0 THEN 1 ELSE 0 END) AS recent_nonzero,
       median(openings_pipeline_400m)                      AS med_pipeline,
       max(openings_pipeline_400m)                         AS max_pipeline,
       median(openings_recent_400m)                        AS med_recent,
       max(openings_recent_400m)                           AS max_recent
FROM analysis.address_category
WHERE openings_run_at IS NOT NULL
GROUP BY ROLLUP(borough, category)
ORDER BY borough NULLS LAST, category NULLS LAST
"""


def validate_openings(con, boroughs: list[str] | None) -> list[str]:
    """Row counts and the no-missing rule, on the warehouse."""
    problems: list[str] = []
    scope = ""
    params: list = []
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        scope = f"WHERE borough IN ({holes})"
        params = list(boroughs)

    n_rows, n_pipe, n_recent = con.execute(
        f"SELECT count(*), count(openings_pipeline_400m), "
        f"count(openings_recent_400m) FROM analysis.address_category {scope}",
        params).fetchone()
    if n_pipe != n_rows or n_recent != n_rows:
        problems.append(
            f"{n_rows - n_pipe:,} address x category rows have NULL "
            f"openings_pipeline_400m and {n_rows - n_recent:,} have NULL "
            f"openings_recent_400m. Every in-scope row must carry a number; "
            f"0 is a value, NULL is 'not run'.")

    n_addr, n_cat = con.execute(
        f"SELECT count(DISTINCT address_id), count(DISTINCT category) "
        f"FROM analysis.address_category {scope}", params).fetchone()
    if n_rows != n_addr * n_cat:
        problems.append(
            f"{n_rows:,} rows != {n_addr:,} addresses x {n_cat} categories -- "
            f"the grain is not complete")

    neg = con.execute(
        f"SELECT count(*) FROM analysis.address_category {scope} "
        f"{'AND' if scope else 'WHERE'} (openings_pipeline_400m < 0 "
        f"OR openings_recent_400m < 0)", params).fetchone()[0]
    if neg:
        problems.append(f"{neg:,} rows carry a negative count")

    # A per-address catchment can never hold more of a category than the city
    # has of it. A double-count inside one catchment breaks exactly this.
    totals = con.execute(f"""
        SELECT loci_category,
               count(*) FILTER (WHERE NOT is_open)   AS n_pipeline,
               count(*) FILTER (WHERE is_open)       AS n_open
        FROM {TABLE} WHERE loci_category IS NOT NULL GROUP BY 1
    """).fetchdf().set_index("loci_category")
    worst = con.execute(
        f"SELECT category, max(openings_pipeline_400m), max(openings_recent_400m) "
        f"FROM analysis.address_category {scope} GROUP BY 1", params).fetchall()
    for cat, mx_p, mx_r in worst:
        if cat in totals.index:
            if mx_p is not None and mx_p > int(totals.at[cat, "n_pipeline"]):
                problems.append(
                    f"{cat}: max openings_pipeline_400m {mx_p} exceeds the "
                    f"{int(totals.at[cat, 'n_pipeline'])} such rows in the whole "
                    f"table -- a catchment is counting a filing twice")
            if mx_r is not None and mx_r > int(totals.at[cat, "n_open"]):
                problems.append(
                    f"{cat}: max openings_recent_400m {mx_r} exceeds the "
                    f"{int(totals.at[cat, 'n_open'])} open rows in the table")
    return problems


# ---------------------------------------------------------------------------
# chains: the per-brand pipeline count
# ---------------------------------------------------------------------------
#: The two feeds whose `business_name` is the OWNER, not the tenant. DOB NOW
#: publishes `owner_s_business_name` and BIS `owner_business_name`
#: (sources/cities/nyc/filing_feeds.py says so in its own caveat), so a
#: pipeline row assembled from those feeds ALONE is keyed on a property manager
#: -- AKAM Associates, FirstService Residential, the NYC School Construction
#: Authority -- and not on a business anybody will shop at.
OWNER_NAME_SOURCES = ("nyc_dob_now_job_filings", "nyc_dob_permit_issuance")


def brand_pipeline(con, brand_keys: list[str] | None = None,
                   limit: int = 0,
                   tenant_names_only: bool | None = None) -> pd.DataFrame:
    """Per brand: how many pipeline rows are NOT YET OPEN, where, and when.

    Joined on `business_name_key`, which IS `chains.normalize.brand_key` -- the
    same function `chains.brand_location` groups on, imported and never
    reimplemented. Its known failure mode applies and bites HARDER here:
    franchisee filings go in under the operating company ("PRIYA FOODS INC"
    running a Dunkin'), so this count is a FLOOR, and a brand with zero
    pipeline rows may simply be one whose franchisees file under their own
    names.

    `tenant_names_only` drops rows whose ONLY filings come from the two feeds
    that publish the owner's name (OWNER_NAME_SOURCES). It defaults to TRUE
    for an open-ended ranking, where otherwise the top twenty brands in New
    York are twenty property managers, and to FALSE when the caller NAMES the
    brands it wants: a watchlist brand that has so far only pulled a DOB permit
    is the earliest signal this table can give, and dropping it to tidy a
    ranking would throw away the one row worth having.
    """
    if tenant_names_only is None:
        tenant_names_only = not brand_keys
    where = "WHERE NOT is_open AND business_name_key IS NOT NULL"
    params: list = []
    if tenant_names_only:
        # `sources` is the sorted comma-joined set for the row, so "every
        # source is an owner-name feed" is "the string equals the sorted join
        # of some non-empty subset". Spelled out rather than a LIKE, because a
        # LIKE would also drop a row that has an SLA filing AND a DOB one --
        # which is precisely a row whose name IS the tenant's.
        subsets = ["nyc_dob_now_job_filings", "nyc_dob_permit_issuance",
                   "nyc_dob_now_job_filings,nyc_dob_permit_issuance"]
        holes = ", ".join("?" for _ in subsets)
        where += f" AND sources NOT IN ({holes})"
        params += subsets
    if brand_keys:
        holes = ", ".join("?" for _ in brand_keys)
        where += f" AND business_name_key IN ({holes})"
        params += list(brand_keys)
    sql = f"""
        SELECT business_name_key                                   AS brand_key,
               count(*)                                            AS pipeline_rows,
               count(DISTINCT bbl)                                 AS pipeline_bbls,
               -- NULLs filtered explicitly: a filing outside the five boroughs'
               -- own spellings has a NULL borough, and `array_to_string` over a
               -- list containing one produces a stray separator that reads as a
               -- borough nobody can name.
               array_to_string(list_sort(list_distinct(
                   list(borough) FILTER (WHERE borough IS NOT NULL))), ',')
                                                                   AS boroughs,
               min(entry_date)                                     AS first_entry,
               max(entry_date)                                     AS last_entry,
               array_to_string(list_sort(list_distinct(
                   list(furthest_stage) FILTER (WHERE furthest_stage IS NOT NULL))), ',')
                                                                   AS stages
        FROM {TABLE}
        {where}
        GROUP BY 1
        ORDER BY pipeline_rows DESC, brand_key
    """
    out = con.execute(sql, params).fetchdf()
    if len(out):
        # RE-RUN THE NORMALIZER OVER THE STORED KEY. `brand_key` gained two
        # junk rules on 2026-09-13 ("nan" from a pandas NaN reaching it, "not
        # applicable" typed into DOB's owner field), and the keys on disk were
        # written by the ingest BEFORE that fix. Re-applying it here means the
        # ranking is right today instead of after the next full re-ingest, and
        # becomes a no-op once the stored keys are rebuilt.
        out = out[[brand_key(k) is not None for k in out["brand_key"]]]
    if limit:
        out = out.head(int(limit))
    return out.reset_index(drop=True)


def has_pipeline_table(con) -> bool:
    """True when analysis.storefront_pipeline exists. Callers that merely
    ENRICH a document (chains/render.py) degrade to a dash rather than raising:
    a missing optional column is not a reason to fail a monthly doc build."""
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = "
        "'analysis' AND table_name = 'storefront_pipeline'").fetchone()[0])


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------
def area_openings(con, *, bbox: tuple[float, float, float, float] | None = None,
                  nta_code: str | None = None, label: str = "area") -> pd.DataFrame:
    """Per-category openings totals for one area, address-weighted.

    `n_addresses` is the denominator and is printed with every number: a mean
    over 1,831 Gowanus addresses and a mean over 1,927 East Village addresses
    are comparable; the SUMS are not, because a filing within 400 m of N
    addresses is counted N times.
    """
    if (bbox is None) == (nta_code is None):
        raise ValueError("pass exactly one of bbox or nta_code")
    if bbox is not None:
        lat0, lon0, lat1, lon1 = bbox
        scope = (f"a.lat BETWEEN {min(lat0, lat1)} AND {max(lat0, lat1)} "
                 f"AND a.lon BETWEEN {min(lon0, lon1)} AND {max(lon0, lon1)}")
        params: list = []
    else:
        scope = "a.nta_code = ?"
        params = [nta_code]
    return con.execute(f"""
        SELECT '{label}'                            AS area,
               ac.category,
               count(*)                             AS n_addresses,
               round(avg(ac.openings_pipeline_400m), 2) AS mean_pipeline_400m,
               median(ac.openings_pipeline_400m)    AS med_pipeline_400m,
               max(ac.openings_pipeline_400m)       AS max_pipeline_400m,
               round(avg(ac.openings_recent_400m), 2)   AS mean_recent_400m,
               median(ac.openings_recent_400m)      AS med_recent_400m,
               max(ac.openings_recent_400m)         AS max_recent_400m
        FROM analysis.address a
        JOIN analysis.address_category ac
          ON ac.address_id = a.address_id AND ac.borough = a.borough
        WHERE {scope} AND ac.openings_run_at IS NOT NULL
        GROUP BY 1, 2
        ORDER BY mean_pipeline_400m DESC, ac.category
    """, params).fetchdf()


#: The two areas `stats` reports, as the recommendation cards define them.
#: Gowanus core is the bbox docs/recommendations/gowanus-core-2026-09-13.md
#: was generated with; East Village is NTA MN0303.
GOWANUS_CORE_BBOX = (40.67, -73.995, 40.682, -73.982)
EAST_VILLAGE_NTA = "MN0303"


def stats(con) -> dict:
    """Everything `loci storefront-pipeline stats` prints."""
    out: dict = {}
    out["census"] = con.execute(f"""
        SELECT group_kind, entry_stage, is_open,
               count(*) AS n_rows, sum(n_filings) AS n_filings,
               count(*) FILTER (WHERE loci_category IS NOT NULL) AS n_categorised
        FROM {TABLE} GROUP BY 1, 2, 3 ORDER BY n_rows DESC
    """).fetchdf()
    out["furthest"] = con.execute(f"""
        SELECT furthest_stage, count(*) AS n_rows,
               count(*) FILTER (WHERE is_open) AS n_open,
               median(lead_days) AS median_lead_days
        FROM {TABLE} GROUP BY 1 ORDER BY n_rows DESC
    """).fetchdf()
    out["categories"] = con.execute(f"""
        SELECT coalesce(loci_category, '(unmapped)') AS loci_category,
               category_confidence,
               count(*) AS n_rows, sum(n_filings) AS n_filings,
               count(*) FILTER (WHERE NOT is_open) AS n_not_open
        FROM {TABLE} GROUP BY 1, 2 ORDER BY n_filings DESC
    """).fetchdf()
    out["headline"] = headline_leads(con)
    out["lead_strict"] = lead_table(con, match="strict")
    out["lead_reconciled"] = lead_table(con, match="reconciled")
    out["links"] = con.execute(f"""
        SELECT link_method, count(*) / 2 AS n_links,
               median(link_lead_days) AS median_lead_days
        FROM {TABLE} WHERE link_method IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchdf()
    out["brands"] = brand_pipeline(con, limit=20)
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE "
                   "table_schema = 'analysis' AND table_name = 'poi_presence'"
                   ).fetchone()[0]:
        out["kinds"] = con.execute(
            "SELECT first_seen_kind, count(*) AS n FROM analysis.poi_presence "
            "GROUP BY 1 ORDER BY 2 DESC").fetchdf()
    have_openings = con.execute(
        "SELECT count(*) FROM analysis.address_category "
        "WHERE openings_run_at IS NOT NULL").fetchone()[0]
    if have_openings:
        out["gowanus"] = area_openings(con, bbox=GOWANUS_CORE_BBOX,
                                       label="Gowanus core")
        out["east_village"] = area_openings(con, nta_code=EAST_VILLAGE_NTA,
                                            label="East Village")
    return out
