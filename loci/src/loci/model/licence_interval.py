"""DCWP licence numbers -> dated open/closed intervals (`analysis.licence_interval`).

The warehouse's first real firm-survival clock. Everything else it holds is a
2026 snapshot or an occupancy panel; a DCWP licence number is an IDENTITY that
carries a creation date, a status and an expiry, and licensing is mandatory, so
within the trades DCWP licenses the denominator is known rather than estimated
at 3% the way Foursquare's closures are.

WHAT THIS MODULE REFUSES TO DECIDE
----------------------------------
WHICH STATUSES ARE CLOSURES. All ten are carried verbatim. The rewind
pre-registration assigns them -- and assigns them DIFFERENTLY under its primary
and strict event definitions, which is exactly why a builder that pre-judged
them would quietly pick one arm of a check designed to be run both ways. See
sql/041_rewind_prerequisites.sql.

WHEN THE STATUS CHANGED. w7w3-xahh publishes `license_creation_date` and
`lic_expir_dd` and no status-change date at all. For a `Surrendered` licence the
warehouse knows THAT it ended and not WHEN. `status_date` is therefore always
NULL -- present as a column so a city whose feed does publish one can fill it --
and `end_kind` names what is actually known about `interval_end`. Inventing an
event time (the expiry, the pull date, a midpoint) would hand a survival model
a fabricated hazard shape it would then report with confidence intervals.

SOURCE. `staging.storefront_filing` where source = 'nyc_dcwp_licenses', which
after 2026-09-16 is the FULL HISTORY of w7w3-xahh (creation dates 1997-2026)
rather than a 24-month slice. Reading the staging table rather than re-hitting
Socrata means the BBL resolution, the name key and the match method are already
done, once, by the code that owns those rules.
"""
from __future__ import annotations

import datetime as dt

TABLE = "analysis.licence_interval"
SOURCE = "nyc_dcwp_licenses"

#: DCWP licence-roster `business_category` -> Loci category.
#:
#: DERIVED FROM THE ROSTER'S OWN 49 VALUES, measured live 2026-09-16. An
#: earlier draft of this map reused the vocabulary
#: sources/cities/nyc/dcwp.py froze for the INSPECTIONS feed ("Retail Laundry",
#: "Grocery-Retail - 808", "Restaurant - 818"). Those legacy "- NNN" codes do
#: not appear in w7w3-xahh at all, and the map matched 6 rows in 72,451. Two
#: DCWP datasets, two vocabularies; they are not interchangeable.
#:
#: THE HEADLINE, AND IT IS A CONSTRAINT ON THE SURVIVAL RUNG:
#: DCWP LICENSES ALMOST NONE OF LOCI'S FIFTEEN CATEGORIES. The roster's mass is
#: Home Improvement Contractor (18,931), Tobacco Retail Dealer (6,707),
#: Secondhand Dealer (6,356), Electronics Store (4,302), Sightseeing Guide
#: (3,974), Tow Truck Driver (3,170), Locksmith (2,995). Exactly one value maps
#: cleanly onto a Loci category, and it has six rows. A per-category survival
#: curve is NOT available from this vocabulary; it is available only for rows
#: that also join the POI ledger, which is where the category comes from.
CATEGORY_MAP: dict[str, str] = {
    # The consumer laundromat licence. Six rows -- DCWP effectively stopped
    # issuing this class, which dcwp.py already recorded ("Consumer 'Laundries'
    # has zero active licenses"). Kept because it is exact and because six
    # honest rows are better than six hundred guessed ones.
    "Laundries": "laundry",
}

#: Roster values that LOOK mappable and are deliberately NOT mapped, each with
#: the reason. Data, not a comment, so the omission is on the record and a
#: later session can argue with it instead of silently "fixing" it.
DELIBERATELY_UNMAPPED: dict[str, str] = {
    "Industrial Laundry":
        "B2B linen and uniform supply, not neighbourhood-serving; counting it "
        "would put false laundry access in industrial zones. Same exclusion "
        "dcwp.py:classify already applies.",
    "Industrial Laundry Delivery": "as Industrial Laundry.",
    "Tobacco Retail Dealer":
        "A LICENCE HELD BY a bodega or a smoke shop, not a trade. Mapping it to "
        "`convenience` would enter 6,707 licences as convenience supply, most "
        "of them held by stores the POI ledger already counts -- the "
        "double-count bug, entered through the category column.",
    "Electronic Cigarette Dealer": "as Tobacco Retail Dealer.",
    "Stoop Line Stand":
        "The sidewalk fruit-and-veg stand ATTACHED TO a bodega. The premises is "
        "already counted as the bodega; the stand is not a second store.",
    "Newsstand":
        "A sidewalk kiosk, not a walk-in convenience store. Loci's "
        "`convenience` category means a store a household shops at; conflating "
        "the two would inflate convenience supply on exactly the high-footfall "
        "corners where the screen is most consulted.",
    "Electronics Store":
        "Not one of the fifteen. Loci has no consumer-electronics category and "
        "inventing one here would put a category in the warehouse that "
        "score/ and model/ cannot read.",
    "Car Wash": "not one of the fifteen.",
    "Hotel": "not one of the fifteen.",
    "Pawnbroker": "not one of the fifteen.",
    "Locksmith": "not one of the fifteen; and 4 of 2,995 rows carry a point.",
    "Home Improvement Contractor":
        "Licensed at the CONTRACTOR'S HOME ADDRESS, frequently outside the "
        "city. Not a storefront in any sense, and the single largest block of "
        "rows in the roster.",
}

def category_of(business_category: str | None) -> tuple[str | None, str | None]:
    """(loci_category, confidence). Exact vocabulary match only.

    NO KEYWORD FALLBACK, on purpose. `classify()` in dcwp.py uses substring
    keywords and is right to for the laundry anchor, where a missed value is a
    missed storefront. Here a wrong map is worse than no map: it would put a
    licence's survival curve under a category it does not belong to, and a
    survival curve is quoted with an n. An unmapped licence is still in the
    table with `loci_category` NULL and is still counted in the row totals.
    """
    if not business_category:
        return None, None
    hit = CATEGORY_MAP.get(business_category.strip())
    return (hit, "high") if hit else (None, None)


def build(con, *, asof: dt.date | None = None) -> dict:
    """Populate analysis.licence_interval from staging.storefront_filing.

    Full DELETE-then-INSERT of the one source; idempotent. Returns the report
    `loci filings licence-intervals` prints.

    THE FAN-OUT GUARD. `staging.storefront_filing` is already one row per
    `filing_id` (= source:stage:license_nbr), collapsed to the earliest
    `filed_on` by `storefront_filing.assemble` -- DCWP repeats a licence number
    across address rows and a naive read would produce two intervals for one
    licence and then count one closure twice. The INSERT nonetheless goes
    through an explicit QUALIFY on licence_number so this table's primary key
    can never be the thing that discovers a change upstream.
    """
    asof = asof or dt.date.today()
    _register_name_key(con)
    cat_when = "\n".join(
        f"            WHEN {_lit(k)} THEN {_lit(v)}"
        for k, v in sorted(CATEGORY_MAP.items()))

    con.execute(f"DELETE FROM {TABLE} WHERE source = ?", [SOURCE])
    con.execute(f"""
        INSERT INTO {TABLE} (
            licence_number, business_name_key, poi_name_key, business_name, bbl,
            match_method,
            borough, address, lon, lat, geom, business_category, licence_type,
            loci_category, category_confidence, licence_creation_date,
            expiration_date, status, status_date, interval_end, end_kind,
            days_observed, pulled_asof, source, provenance, ingested_at)
        WITH src AS (
            SELECT raw_id                                  AS licence_number,
                   business_name_key, business_name, bbl, match_method,
                   borough,
                   NULLIF(trim(coalesce(house_number, '') || ' '
                               || coalesce(street_name, '')), '')  AS address,
                   lon, lat,
                   category_hint                           AS business_category,
                   license_type                            AS licence_type,
                   filed_on                                AS licence_creation_date,
                   status_date                             AS expiration_date,
                   status,
                   provenance
            FROM staging.storefront_filing
            WHERE source = ? AND stage = 'license_issued'
              AND raw_id IS NOT NULL AND filed_on IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (PARTITION BY raw_id
                                       ORDER BY filed_on, status) = 1
        ),
        typed AS (
            SELECT *,
                -- 'Active' is matched case-insensitively and trimmed because a
                -- status vocabulary is exactly the kind of thing a portal
                -- respells; everything else keeps DCWP's own spelling.
                upper(trim(coalesce(status, ''))) = 'ACTIVE'   AS is_active,
                CASE WHEN expiration_date IS NOT NULL
                      AND expiration_date <= DATE '{asof.isoformat()}'
                     THEN expiration_date END                  AS past_expiry
            FROM src
        )
        SELECT
            licence_number, business_name_key,
            -- The POI ledger's normaliser, registered as a UDF below. It is
            -- NOT interchangeable with brand_key (see sql/041's DDL comment).
            loci_poi_name_key(business_name)               AS poi_name_key,
            business_name, bbl, match_method,
            borough, address, lon, lat,
            CASE WHEN lon IS NOT NULL AND lat IS NOT NULL
                 THEN ST_Point(lon, lat) END                   AS geom,
            business_category, licence_type,
            CASE business_category
{cat_when}
            END                                                AS loci_category,
            CASE WHEN business_category IN (SELECT UNNEST(?::VARCHAR[]))
                 THEN 'high' END                               AS category_confidence,
            licence_creation_date, expiration_date, status,
            CAST(NULL AS DATE)                                 AS status_date,
            -- interval_end, then the kind that explains it. Clamped at BOTH
            -- ends: never after `asof` (we cannot observe the future) and
            -- never before creation (a licence whose published expiry precedes
            -- its creation date is a data error, and a negative duration would
            -- poison every median downstream).
            greatest(licence_creation_date,
                     CASE WHEN is_active THEN DATE '{asof.isoformat()}'
                          WHEN past_expiry IS NOT NULL THEN past_expiry
                          ELSE DATE '{asof.isoformat()}' END)  AS interval_end,
            CASE WHEN is_active                     THEN 'active_censored'
                 WHEN past_expiry IS NOT NULL       THEN 'expiry_observed'
                 WHEN expiration_date IS NOT NULL   THEN 'expiry_future'
                 ELSE 'no_expiry' END                          AS end_kind,
            CAST(date_diff('day', licence_creation_date,
                 greatest(licence_creation_date,
                          CASE WHEN is_active THEN DATE '{asof.isoformat()}'
                               WHEN past_expiry IS NOT NULL THEN past_expiry
                               ELSE DATE '{asof.isoformat()}' END))
                 AS INTEGER)                                   AS days_observed,
            DATE '{asof.isoformat()}'                          AS pulled_asof,
            ?                                                  AS source,
            provenance,
            now()                                              AS ingested_at
        FROM typed
    """, [SOURCE, sorted(CATEGORY_MAP), SOURCE])

    return report(con, asof=asof)


def _register_name_key(con) -> None:
    """Expose poi_presence.name_key_of to SQL as `loci_poi_name_key`.

    Registered rather than reimplemented in SQL: the ledger's key is
    `" ".join(sorted(norm_tokens(name)))` and norm_tokens carries a stopword
    list, accent folding and a generic-name rule. A SQL transliteration of it
    would be a SECOND definition of the join key, free to drift from the one
    the ledger actually minted -- and a drifted key produces a quiet
    under-match, which reads as a city where the licensed businesses are not
    the ones on the street.
    """
    from loci.model.poi_presence import name_key_of

    def _k(name):                      # DuckDB passes NULL through as None
        return name_key_of(name) if name else None

    # Ask the catalog rather than try/except: a bare except here would also
    # swallow a real signature error and leave the INSERT calling a UDF that is
    # not the one this function defines. `build()` is called twice on one
    # connection by the idempotency test and by any re-run.
    already = con.execute(
        "SELECT count(*) FROM duckdb_functions() WHERE function_name = ?",
        ["loci_poi_name_key"]).fetchone()[0]
    if not already:
        con.create_function("loci_poi_name_key", _k, ["VARCHAR"], "VARCHAR",
                            null_handling="special")


def _lit(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


# ------------------------------------------------------------------ reporting

def report(con, *, asof: dt.date | None = None) -> dict:
    rows = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return {
        "rows": rows,
        # The table is MULTI-SOURCE since 2026-09-16 (DCWP roster + the SLA
        # active/inactive pair). Every aggregate below pools them, which is
        # right for "how many dated intervals does the warehouse hold" and
        # WRONG for anything per-source: DCWP publishes no status-change date
        # and SLA's inactive file does, so their end_kind mixes are not
        # comparable. Split on this before quoting a survival number.
        "by_source": con.execute(f"""
            SELECT source, count(*) n,
                   min(licence_creation_date), max(licence_creation_date),
                   count(*) FILTER (WHERE loci_category IS NOT NULL) mapped,
                   count(*) FILTER (WHERE bbl IS NOT NULL) with_bbl
            FROM {TABLE} GROUP BY 1 ORDER BY 2 DESC""").fetchall(),
        "asof": (asof or dt.date.today()).isoformat(),
        "by_status": con.execute(f"""
            SELECT status, count(*) n,
                   min(licence_creation_date) first_created,
                   max(licence_creation_date) last_created
            FROM {TABLE} GROUP BY 1 ORDER BY 2 DESC""").fetchall(),
        "by_end_kind": con.execute(f"""
            SELECT end_kind, count(*) FROM {TABLE} GROUP BY 1 ORDER BY 2 DESC
        """).fetchall(),
        "by_year": con.execute(f"""
            SELECT year(licence_creation_date) y, count(*)
            FROM {TABLE} GROUP BY 1 ORDER BY 1""").fetchall(),
        "bbl_resolved": con.execute(f"""
            SELECT count(*) FROM {TABLE} WHERE bbl IS NOT NULL""").fetchone()[0],
        "bbl_resolved_mnbk": con.execute(f"""
            SELECT count(*) FROM {TABLE}
            WHERE bbl IS NOT NULL AND borough IN ('MN','BK')""").fetchone()[0],
        "mnbk": con.execute(f"""
            SELECT count(*) FROM {TABLE} WHERE borough IN ('MN','BK')
        """).fetchone()[0],
        "negative_durations": con.execute(f"""
            SELECT count(*) FROM {TABLE} WHERE days_observed < 0""").fetchone()[0],
    }


def match_rates(con) -> dict:
    """Join rate to the POI ledger, per Loci category. The P3 check's input.

    `loci_category` is NULL for most rows -- DCWP does not license most trades
    -- so the per-category table is reported over the mapped subset AND the
    unmapped remainder is reported as its own row rather than dropped. A match
    rate quoted over the mapped subset alone would describe 4% of the table.
    """
    per_cat = con.execute(f"""
        SELECT coalesce(li.loci_category, '(no loci category)') AS cat,
               count(*)                                          AS licences,
               count(m.location_key)                             AS matched,
               count(*) FILTER (WHERE m.join_method = 'licence_number') AS by_number,
               count(*) FILTER (WHERE m.join_method = 'name_key_50m')   AS by_name
        FROM {TABLE} li
        LEFT JOIN analysis.licence_interval_poi m USING (licence_number)
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    total = con.execute(f"""
        SELECT count(*), count(m.location_key)
        FROM {TABLE} li
        LEFT JOIN analysis.licence_interval_poi m USING (licence_number)
    """).fetchone()
    mnbk = con.execute(f"""
        SELECT count(*), count(m.location_key)
        FROM {TABLE} li
        LEFT JOIN analysis.licence_interval_poi m USING (licence_number)
        WHERE li.borough IN ('MN','BK')
    """).fetchone()
    # THE CEILING, AND IT IS NOT A MATCH RATE. How many geocoded MN+BK
    # licences have ANY ledger location within 50 m, ignoring the name
    # entirely. It bounds what any identity rule could achieve on this
    # geometry, and it is reported so the low name-match rate can be read as
    # what it is -- an identity problem, not a coverage problem.
    #
    # IT MUST NEVER BE USED AS A JOIN. Accepting the nearest POI regardless of
    # name is precisely the dedup-fusing-distinct-storefronts bug: the sample
    # that motivated this comment paired "CHAMPION DELI & GROCERY CORP" with
    # "Caffe Buon Gusto" and "BANANA SUPERMARKET INC." with "Jkl Laundromat",
    # which would have attributed a supermarket's survival to a laundromat.
    ceiling = con.execute(f"""
        WITH u AS (SELECT licence_number, geom FROM {TABLE}
                   WHERE geom IS NOT NULL AND borough IN ('MN','BK'))
        SELECT count(*),
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM analysis.poi_presence p
                   WHERE p.lon IS NOT NULL
                     AND ST_DWithin(
                           ST_Transform(u.geom, 'EPSG:4326', 'EPSG:2263'),
                           ST_Transform(ST_Point(p.lon, p.lat),
                                        'EPSG:4326', 'EPSG:2263'),
                           164.042)))
        FROM u
    """).fetchone()
    return {"per_category": per_cat, "total": total, "mnbk": mnbk,
            "proximity_ceiling_mnbk": ceiling}


# ==========================================================================
# THE SLA HALF (2026-09-16) -- the same table, two more sources
# ==========================================================================
#
# WHY HERE AND NOT IN A NEW TABLE. This module's grain is already "one licence,
# one dated interval, one end_kind that says what is known about the end". The
# SLA pair has exactly that grain. A second table would be the same grain under
# a different name, which is the table-proliferation failure the owner named
# on 2026-09-09: pivots and subsets are views, and a NEW MEASURE extends the
# grain rather than forking it.
#
# WHY TWO SOURCES AND NOT ONE. SLA publishes the two halves of the panel in two
# files and neither is usable alone:
#
#   9s3h-dpkz  Current ACTIVE licences.   A snapshot. A licence that lapsed
#              before the pull is simply absent, so this file's year histogram
#              is a RENEWAL CURVE, not a licensing history. It supplies the
#              right-censored (still-open) rows.
#   6dg3-2z7i  Current INACTIVE licences. 29,568 NYC rows, expiration_date
#              2015..2029. It supplies the ENDINGS, and it is the reason
#              `loci rewind checks` P2 can see SLA activity in 2016, 2018 and
#              2019 at all -- the active file has no row in any of them.
#
# THE CATEGORY WIN. Unlike the DCWP roster, whose 49 business categories map
# onto exactly ONE Loci category (6 rows), the SLA `description` vocabulary
# maps onto FOUR of the fifteen -- restaurant, bar, grocery, pharmacy -- through
# model/filing_categories.yaml, which is already the single definition of that
# mapping and is shared by anchor with the pending-licence feed. So this is the
# first source in the warehouse that gives a dated START and a dated END for
# categories the screen actually ranks.
#
# CAVEATS THE DATABASE CANNOT ENFORCE
#  1. A LICENCE END IS NOT A BUSINESS END. `expiration_date` is the last day
#     the licence was valid. A bar that surrendered early still shows its full
#     term; a bar that changed hands appears as one licence ending and another
#     beginning at the same address. Treat it as an UPPER BOUND on the closure
#     date -- tight for a lapse, loose for a surrender.
#  2. 1,147 NYC inactive rows carry an expiration_date in 2027-2029, i.e. in
#     the future. Those are licences made inactive for a reason SLA does not
#     publish (surrender, revocation, premises sold mid-term). They get
#     end_kind 'expiry_future' and MUST NOT be read as "ends in 2028".
#  3. BOTH FILES ARE "CURRENT". A licence that lapsed and was later reissued at
#     the same premises may leave the inactive file when the new licence
#     issues, so the panel is right-censored in both directions and is not an
#     archive. The same premises can also appear under several licence
#     numbers over time and NOTHING here links them -- a premises-level
#     survival curve needs the ledger join, not this table alone.
#  4. `original_issue_date` on a RENEWED licence is the date the FIRST licence
#     issued at that premises, which is the right field for "when did this bar
#     open" and the wrong one for "when did this licence term start". It is
#     also why filing_stages.OPEN_STAGES excludes `liquor_active`.

SLA_ACTIVE_SOURCE = "nys_sla_liquor_licenses"
SLA_INACTIVE_SOURCE = "nys_sla_inactive_licenses"


def _sla_category_case(source: str) -> str:
    """CASE mapping `category_hint` -> loci category, emitted from
    model/filing_categories.yaml so the SLA vocabulary has ONE definition."""
    from loci.model.storefront_pipeline import load_category_map

    block = load_category_map()["sources"][source]
    lines = "\n".join(f"            WHEN {_lit(k)} THEN {_lit(v)}"
                      for k, v in sorted(block["map"].items()))
    conf = "\n".join(
        f"            WHEN {_lit(k)} THEN {_lit(block['confidence'][k])}"
        for k in sorted(block["map"]))
    return lines, conf


def build_sla(con, *, asof: dt.date | None = None,
              use_cache: bool = True, session=None) -> dict:
    """Populate analysis.licence_interval for BOTH SLA sources.

    The active half is read from `staging.storefront_filing` (already BBL-
    resolved and name-keyed by model/storefront_filing.assemble). The inactive
    half is fetched live and run through the SAME `assemble()` -- so it gets
    the identical BBL ladder and name key -- and then landed HERE rather than
    in staging.storefront_filing, because a closure is not a rung on the
    opening ladder `filing_stages.STAGES` encodes and adding it there would
    make `furthest_stage` mean "it closed".

    Full DELETE-then-INSERT per source; idempotent.
    """
    from loci.model import storefront_filing as sf

    asof = asof or dt.date.today()
    _register_name_key(con)

    # The BBL ladder is a TEMP table built per connection, so it has to exist
    # before assemble() runs. Built here rather than assumed: the SLA inactive
    # rows publish no BBL of their own (bbl_raw is None on every row), so
    # every one of them resolves through the PLUTO address/proximity rungs or
    # not at all, and skipping this would land 29,568 rows at
    # match_method='unmatched' and then quietly halve the P3 BBL rate.
    sf.build_pluto_index(con)

    # ---- the INACTIVE half: fetch, BBL-match, land -----------------------
    frame, fetch_report = sf.assemble(
        con, [SLA_INACTIVE_SOURCE], asof=asof, use_cache=use_cache,
        session=session)
    if frame.empty:
        # Never ingest a silent zero. An empty inactive file is a fetch
        # failure, not a city in which no liquor licence has ever lapsed.
        raise RuntimeError(
            f"{SLA_INACTIVE_SOURCE}: 6dg3-2z7i returned no rows. Refusing to "
            f"ingest an empty closure history -- with no endings every bar in "
            f"the warehouse reads as still trading.")

    n_by_source = {}
    for source, df in ((SLA_INACTIVE_SOURCE, frame),):
        n_by_source[source] = _insert_sla_frame(con, df, source, asof)

    # ---- the ACTIVE half: already in staging.storefront_filing -----------
    n_by_source[SLA_ACTIVE_SOURCE] = _insert_sla_active(con, asof)

    rep = report(con, asof=asof)
    rep["sla_rows_by_source"] = n_by_source
    rep["sla_fetch"] = fetch_report
    return rep


def _insert_sla_frame(con, frame, source: str, asof: dt.date) -> int:
    """Land an assembled FEED_COLUMNS frame as licence intervals."""
    cat_when, conf_when = _sla_category_case(source)
    con.execute(f"DELETE FROM {TABLE} WHERE source = ?", [source])
    con.register("_sla_df", frame)
    try:
        con.execute(f"""
            INSERT INTO {TABLE} (
                licence_number, business_name_key, poi_name_key, business_name,
                bbl, match_method, borough, address, lon, lat, geom,
                business_category, licence_type, loci_category,
                category_confidence, licence_creation_date, expiration_date,
                status, status_date, interval_end, end_kind, days_observed,
                pulled_asof, source, provenance, ingested_at,
                business_unique_id)
            WITH src AS (
                SELECT raw_id AS licence_number, business_name_key,
                       business_name, bbl, match_method, borough,
                       NULLIF(trim(coalesce(house_number, '') || ' '
                                   || coalesce(street_name, '')), '') AS address,
                       lon, lat,
                       category_hint AS business_category,
                       license_type  AS licence_type,
                       CAST(filed_on AS DATE)    AS licence_creation_date,
                       CAST(status_date AS DATE) AS expiration_date,
                       status, provenance
                FROM _sla_df
                WHERE raw_id IS NOT NULL AND filed_on IS NOT NULL
                -- The PRIMARY KEY guard. One SLA licence id can legitimately
                -- appear twice (a premises relicensed under the same serial);
                -- the EARLIEST issue wins, matching the renewal collapse in
                -- storefront_filing.assemble.
                QUALIFY ROW_NUMBER() OVER (PARTITION BY raw_id
                                           ORDER BY filed_on, status) = 1
            ),
            typed AS (
                SELECT *,
                    upper(trim(coalesce(status, ''))) = 'ACTIVE' AS is_active,
                    CASE WHEN expiration_date IS NOT NULL
                          AND expiration_date <= DATE '{asof.isoformat()}'
                         THEN expiration_date END                AS past_expiry
                FROM src
            )
            SELECT licence_number, business_name_key,
                   loci_poi_name_key(business_name) AS poi_name_key,
                   business_name, bbl, match_method, borough, address, lon, lat,
                   CASE WHEN lon IS NOT NULL AND lat IS NOT NULL
                        THEN ST_Point(lon, lat) END              AS geom,
                   business_category, licence_type,
                   CASE business_category
{cat_when}
                   END                                           AS loci_category,
                   CASE business_category
{conf_when}
                   END                                           AS category_confidence,
                   licence_creation_date, expiration_date, status,
                   -- STATUS_DATE. For the inactive file the expiry IS the last
                   -- day the licence was valid, and membership in the file is
                   -- the statement that it is over -- so unlike DCWP (which
                   -- publishes no status-change date at all) there IS a dated
                   -- end here, for the rows whose expiry is in the past.
                   past_expiry                                   AS status_date,
                   greatest(licence_creation_date,
                            CASE WHEN is_active THEN DATE '{asof.isoformat()}'
                                 WHEN past_expiry IS NOT NULL THEN past_expiry
                                 ELSE DATE '{asof.isoformat()}' END)
                                                                 AS interval_end,
                   CASE WHEN is_active                   THEN 'active_censored'
                        WHEN past_expiry IS NOT NULL     THEN 'expiry_observed'
                        WHEN expiration_date IS NOT NULL THEN 'expiry_future'
                        ELSE 'no_expiry' END                     AS end_kind,
                   CAST(date_diff('day', licence_creation_date,
                        greatest(licence_creation_date,
                                 CASE WHEN is_active THEN DATE '{asof.isoformat()}'
                                      WHEN past_expiry IS NOT NULL THEN past_expiry
                                      ELSE DATE '{asof.isoformat()}' END))
                        AS INTEGER)                              AS days_observed,
                   DATE '{asof.isoformat()}'                     AS pulled_asof,
                   '{source}'                                    AS source,
                   provenance, now()                             AS ingested_at,
                   CAST(NULL AS VARCHAR)                         AS business_unique_id
            FROM typed
        """)
    finally:
        con.unregister("_sla_df")
    return con.execute(f"SELECT count(*) FROM {TABLE} WHERE source = ?",
                       [source]).fetchone()[0]


def _insert_sla_active(con, asof: dt.date) -> int:
    """The active half, read from staging.storefront_filing."""
    source = SLA_ACTIVE_SOURCE
    con.execute("CREATE OR REPLACE TEMP VIEW _sla_active AS "
                "SELECT * FROM staging.storefront_filing "
                f"WHERE source = '{source}' AND stage = 'liquor_active'")
    df = con.execute("SELECT * FROM _sla_active").fetchdf()
    if df.empty:
        raise RuntimeError(
            f"{source}: no rows in staging.storefront_filing. Run "
            f"`loci filings ingest --source {source}` first -- an SLA panel "
            f"with no open licences is a fetch failure, not a dry city.")
    return _insert_sla_frame(con, df, source, asof)
