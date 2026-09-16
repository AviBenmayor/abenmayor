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
