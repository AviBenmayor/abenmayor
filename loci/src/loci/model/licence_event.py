"""SLA licence NON-RENEWAL label + its 400 m descriptive baseline
(`analysis.licence_event`, `analysis.licence_event_baseline`, and three columns
on `analysis.address_category`).

sql/047_licence_event.sql carries the schema rationale and the five caveats
the database cannot enforce. Read it first.

WHAT THIS MODULE DOES
---------------------
1. `build()` applies the rewind pre-registration v2 event definition (§1.2)
   to the SLA half of `analysis.licence_interval`, once, for restaurant / bar
   / grocery / pharmacy. Both event arms land on one row:

       event_premises  = ended AND no successor SLA licence at the BBL
                         within 180 days (any category, any name)
       event_business  = ended AND (no successor OR the successor's name key
                         is materially different)

   A successor is another SLA serial at the SAME BBL whose original issue date
   is within +/-180 days of this licence's expiry (a transfer on sale often
   issues BEFORE the old licence lapses, so the window is two-sided) and later
   than this licence's own issue date. Ties break on the smallest gap.

2. `checks()` runs the pre-registration's prerequisites that this table can
   answer -- P3' (BBL -> scored address), P5 (expiry -> independent closure
   PPV) and the >= 200 events count -- and returns PASS/FAIL with numbers.
   Nothing here fits a hazard. The fit is a later, separately pre-registered
   run; a build that also fit the model would be the un-pre-registered run
   the charter forbids.

3. `build_measure()` writes `n_licences_400m`, `n_nonrenewed_400m` and
   `nonrenewal_rate_5y_400m` onto analysis.address_category through the one
   walk-network engine (model/walk_catchment.py), so the card can print
   "N of M licences within 400 m ended without a successor in 5 years, vs the
   borough rate". CONTEXT, NOT A GRADE: the columns are asserted disjoint from
   every column the screen owns and nothing here moves gap_score.

THE WINDOW. "In 5 years" means: at risk = the interval overlaps
[asof - 5y, asof]; event = the end falls inside it. Both flags are stamped on
the row at build (`at_risk_5y`, `event_5y_*`) so the address measure and the
baseline view read ONE definition.

WHY `name_key` IS THE LEDGER'S KEY. `poi_presence.name_key_of` strips
corporate suffixes and generic tokens ("BANANA SUPERMARKET INC." ->
"banana supermarket"), which is what "materially different" has to mean for
an SLA legal name against a d/b/a. The filing feed's `business_name_key`
does not do that and would read a re-incorporation as a new business.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

TABLE = "analysis.licence_event"
BASELINE_VIEW = "analysis.licence_event_baseline"
INTERVAL_TABLE = "analysis.licence_interval"

SLA_SOURCES = ("nys_sla_liquor_licenses", "nys_sla_inactive_licenses")

#: Pre-registration v2 §1.1: in, primary; pharmacy provisional.
PRIMARY_CATEGORIES = ("restaurant", "bar", "grocery")
PROVISIONAL_CATEGORIES = ("pharmacy",)
CATEGORIES = PRIMARY_CATEGORIES + PROVISIONAL_CATEGORIES

#: §1.2: successor licence at the same BBL within this many days of the end.
SUCCESSOR_WINDOW_DAYS = 180
#: The DCWP/DOHMH "no date" sentinel. SLA has none today (0 rows measured
#: 2026-09-17); the guard is here so a re-pull that grows one cannot start a
#: clock in 1900.
SENTINEL_ISSUE_DATE = dt.date(1900, 12, 31)
#: The descriptive window the card quotes.
WINDOW_YEARS = 5

#: §1.5 cohort rule, used ONLY by the >= 200-events count in `checks()`.
COHORT_START = dt.date(2016, 1, 1)
COHORT_END = dt.date(2021, 12, 31)
COHORT_FOLLOWUP_MONTHS = 36
MIN_EVENTS = 200
P3_FLOOR = 0.70
P3_NO_RUN = 0.50
P5_FLOOR = 0.50
P5_WINDOW_DAYS = 365
P5_JOIN_M = 50.0

MEASURE_COLUMNS = ["n_licences_400m", "n_nonrenewed_400m",
                   "nonrenewal_rate_5y_400m", "licence_asof", "licence_run_at"]

SCREEN_BOROUGHS = ("MN", "BK")


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _cats_sql(cats=CATEGORIES) -> str:
    return ", ".join(_lit(c) for c in cats)


def _years_before(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:                       # 29 Feb
        return d.replace(year=d.year - years, day=28)


# ---------------------------------------------------------------------------
# 1. the label
# ---------------------------------------------------------------------------
def build(con, *, asof: dt.date | None = None) -> dict:
    """Populate analysis.licence_event from the SLA rows of licence_interval.

    Full DELETE-then-INSERT; idempotent. Returns the report the CLI prints.
    Raises on an empty SLA panel: a table with no licences is a fetch failure,
    not a city with no bars.
    """
    asof = asof or dt.date.today()
    window_start = _years_before(asof, WINDOW_YEARS)
    srcs = ", ".join(_lit(s) for s in SLA_SOURCES)

    n_sla = con.execute(
        f"SELECT count(*) FROM {INTERVAL_TABLE} WHERE source IN ({srcs})").fetchone()[0]
    if not n_sla:
        raise RuntimeError(
            f"{INTERVAL_TABLE} holds no SLA rows. Run `loci rewind "
            f"licence-intervals --sla` first; an empty label would read as a "
            f"city where no licence ever lapsed.")

    dropped = dict(con.execute(f"""
        SELECT CASE WHEN licence_creation_date IS NULL THEN 'no_issue_date'
                    WHEN licence_creation_date <= DATE '{SENTINEL_ISSUE_DATE}'
                         THEN 'sentinel_issue_date'
                    ELSE end_kind END AS why, count(*)
        FROM {INTERVAL_TABLE}
        WHERE source IN ({srcs}) AND loci_category IN ({_cats_sql()})
          AND (licence_creation_date IS NULL
               OR licence_creation_date <= DATE '{SENTINEL_ISSUE_DATE}'
               OR end_kind NOT IN ('active_censored', 'expiry_observed'))
        GROUP BY 1
    """).fetchall())

    con.execute("BEGIN")
    try:
        con.execute(f"DELETE FROM {TABLE}")
        con.execute(f"""
            INSERT INTO {TABLE} (
                licence_number, source, category, category_confidence,
                licence_type, licence_class, business_name, name_key, bbl,
                match_method, borough, lon, lat, geom, issue_date, end_date,
                censor_date, interval_end, interval_censored_month, ended,
                days_since_issue, successor_checkable,
                successor_licence_number, successor_issue_date,
                successor_gap_days, successor_same_name, event_business,
                event_premises, at_risk_5y, event_5y_business,
                event_5y_premises, label_asof, pulled_asof, built_at)
            WITH sla AS (
                SELECT licence_number, source, loci_category, category_confidence,
                       licence_type,
                       TRY_CAST(regexp_extract(licence_type, 'class 0*([0-9]+)', 1)
                                AS INTEGER)                        AS licence_class,
                       business_name, poi_name_key AS name_key, bbl, match_method,
                       borough, lon, lat, geom,
                       licence_creation_date                       AS issue_date,
                       expiration_date, end_kind, pulled_asof
                FROM {INTERVAL_TABLE}
                WHERE source IN ({srcs})
            ),
            -- EVERY SLA licence is a successor candidate, whatever its
            -- category: a restaurant licence replaced by a bar licence at the
            -- same lot is still a premises that kept trading.
            cand AS (
                SELECT licence_number, bbl, issue_date, name_key
                FROM sla WHERE bbl IS NOT NULL AND issue_date IS NOT NULL
            ),
            lab AS (
                SELECT *,
                       end_kind = 'expiry_observed'                 AS ended,
                       CASE WHEN end_kind = 'expiry_observed'
                            THEN expiration_date END                AS end_date,
                       CASE WHEN end_kind <> 'expiry_observed'
                            THEN pulled_asof END                    AS censor_date
                FROM sla
                WHERE loci_category IN ({_cats_sql()})
                  AND issue_date IS NOT NULL
                  AND issue_date > DATE '{SENTINEL_ISSUE_DATE}'
                  AND end_kind IN ('active_censored', 'expiry_observed')
            ),
            succ AS (
                SELECT l.licence_number,
                       c.licence_number                             AS successor_licence_number,
                       c.issue_date                                 AS successor_issue_date,
                       date_diff('day', l.end_date, c.issue_date)   AS successor_gap_days,
                       CASE WHEN l.name_key IS NULL OR c.name_key IS NULL
                                 OR l.name_key = '' OR c.name_key = '' THEN NULL
                            ELSE l.name_key = c.name_key END        AS successor_same_name
                FROM lab l
                JOIN cand c
                  ON c.bbl = l.bbl
                 AND c.licence_number <> l.licence_number
                 AND c.issue_date > l.issue_date
                 AND abs(date_diff('day', l.end_date, c.issue_date)) <= {SUCCESSOR_WINDOW_DAYS}
                WHERE l.ended
                QUALIFY row_number() OVER (
                    PARTITION BY l.licence_number
                    ORDER BY abs(date_diff('day', l.end_date, c.issue_date)),
                             c.licence_number) = 1
            )
            SELECT l.licence_number, l.source, l.loci_category, l.category_confidence,
                   l.licence_type, l.licence_class, l.business_name, l.name_key,
                   l.bbl, l.match_method, l.borough, l.lon, l.lat, l.geom,
                   l.issue_date, l.end_date, l.censor_date,
                   coalesce(l.end_date, l.censor_date)               AS interval_end,
                   FALSE                                             AS interval_censored_month,
                   l.ended,
                   greatest(0, date_diff('day', l.issue_date,
                                         coalesce(l.end_date, l.censor_date)))
                                                                     AS days_since_issue,
                   l.bbl IS NOT NULL                                 AS successor_checkable,
                   s.successor_licence_number, s.successor_issue_date,
                   s.successor_gap_days, s.successor_same_name,
                   CASE WHEN l.bbl IS NULL THEN NULL
                        WHEN NOT l.ended THEN FALSE
                        WHEN s.successor_licence_number IS NULL THEN TRUE
                        WHEN s.successor_same_name IS FALSE THEN TRUE
                        ELSE FALSE END                                AS event_business,
                   CASE WHEN l.bbl IS NULL THEN NULL
                        WHEN NOT l.ended THEN FALSE
                        WHEN s.successor_licence_number IS NULL THEN TRUE
                        ELSE FALSE END                                AS event_premises,
                   (l.issue_date <= DATE '{asof}'
                    AND coalesce(l.end_date, l.censor_date) >= DATE '{window_start}')
                                                                     AS at_risk_5y,
                   CASE WHEN l.bbl IS NULL THEN NULL
                        ELSE (l.ended AND l.end_date BETWEEN DATE '{window_start}' AND DATE '{asof}'
                              AND (s.successor_licence_number IS NULL
                                   OR s.successor_same_name IS FALSE)) END
                                                                     AS event_5y_business,
                   CASE WHEN l.bbl IS NULL THEN NULL
                        ELSE (l.ended AND l.end_date BETWEEN DATE '{window_start}' AND DATE '{asof}'
                              AND s.successor_licence_number IS NULL) END
                                                                     AS event_5y_premises,
                   DATE '{asof}'                                     AS label_asof,
                   l.pulled_asof,
                   now()                                             AS built_at
            FROM lab l
            LEFT JOIN succ s USING (licence_number)
        """)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    rep = report(con)
    rep["dropped"] = {k: int(v) for k, v in dropped.items()}
    rep["window"] = [window_start.isoformat(), asof.isoformat()]
    return rep


def report(con) -> dict:
    df = con.execute(f"""
        SELECT category,
               count(*)                                          AS n,
               count(*) FILTER (WHERE ended)                     AS n_ended,
               count(*) FILTER (WHERE NOT successor_checkable)   AS n_unchecked,
               count(*) FILTER (WHERE event_business)            AS ev_business,
               count(*) FILTER (WHERE event_premises)            AS ev_premises,
               count(*) FILTER (WHERE successor_licence_number IS NOT NULL) AS with_successor,
               count(*) FILTER (WHERE successor_same_name IS NULL
                                  AND successor_licence_number IS NOT NULL)
                                                                 AS successor_name_unknown,
               count(*) FILTER (WHERE borough IN ('MN', 'BK'))   AS mnbk
        FROM {TABLE} GROUP BY 1 ORDER BY 1
    """).fetchdf()
    total = int(con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0])
    return {"rows": total,
            "by_category": {r["category"]: {k: int(r[k]) for k in df.columns if k != "category"}
                            for _, r in df.iterrows()}}


# ---------------------------------------------------------------------------
# 2. the pre-registration checks this table can answer
# ---------------------------------------------------------------------------
def p3_prime(con) -> dict:
    """Share of included-category licences (MN+BK universe) whose BBL is a
    Loci-scored lot. `gap_score IS NOT NULL` on analysis.address at frame=lot
    stands in for "carries a Loci score at t0": no historical score table
    exists yet, so this is the CURRENT score and is labelled as such.

    DENOMINATOR: rows whose borough is MN or BK PLUS rows with no borough at
    all (an unresolved row is not evidence it sits in Queens). Numerator: BBL
    resolved AND that BBL scored.
    """
    df = con.execute(f"""
        WITH scored AS (
            SELECT DISTINCT bbl FROM analysis.address
            WHERE frame = 'lot' AND gap_score IS NOT NULL AND bbl IS NOT NULL
        )
        SELECT e.category,
               count(*)                                             AS n_universe,
               count(*) FILTER (WHERE e.bbl IS NOT NULL)            AS n_bbl,
               count(*) FILTER (WHERE s.bbl IS NOT NULL)            AS n_scored
        FROM {TABLE} e
        LEFT JOIN scored s ON s.bbl = e.bbl
        WHERE e.borough IN ('MN', 'BK') OR e.borough IS NULL
        GROUP BY ROLLUP (e.category)
        ORDER BY e.category NULLS LAST
    """).fetchdf()
    # THE IMPUTATION THE FIT WOULD HAVE TO DECLARE (pre-registration §1.6:
    # "below 70%, the fit scores licence rows whose site score is imputed and
    # must say so"). A licence on a purely commercial lot has no residential
    # address row and so no score OF ITS OWN; the nearest scored address
    # within 50 m straight-line is the imputation. Counted separately, never
    # folded into `share_scored`.
    from loci.db import METRES_SQL
    metres = METRES_SQL.format(a="ST_Point(u.lon, u.lat)", b="ST_Point(a.lon, a.lat)")
    imp = con.execute(f"""
        WITH scored AS (
            SELECT DISTINCT bbl FROM analysis.address
            WHERE frame = 'lot' AND gap_score IS NOT NULL AND bbl IS NOT NULL
        ),
        unscored AS (
            SELECT e.licence_number, e.category, e.lon, e.lat
            FROM {TABLE} e LEFT JOIN scored s ON s.bbl = e.bbl
            WHERE (e.borough IN ('MN', 'BK') OR e.borough IS NULL)
              AND s.bbl IS NULL AND e.lon IS NOT NULL AND e.lat IS NOT NULL
        )
        SELECT u.category, count(DISTINCT u.licence_number)
        FROM unscored u
        JOIN analysis.address a
          ON a.gap_score IS NOT NULL
         AND a.lon BETWEEN u.lon - 0.001 AND u.lon + 0.001
         AND a.lat BETWEEN u.lat - 0.001 AND u.lat + 0.001
         AND {metres} <= 50.0
        GROUP BY ROLLUP (u.category)
    """).fetchall()
    imputable = {(k if isinstance(k, str) else "ALL"): int(v) for k, v in imp}
    out = {}
    for _, r in df.iterrows():
        key = r["category"] if isinstance(r["category"], str) else "ALL"
        n, nb, ns = int(r["n_universe"]), int(r["n_bbl"]), int(r["n_scored"])
        ni = imputable.get(key, 0)
        out[key] = {"n": n, "bbl_resolved": nb, "scored": ns,
                    "share_scored": (ns / n) if n else None,
                    "imputable_within_50m": ni,
                    "share_scored_or_imputed": ((ns + ni) / n) if n else None,
                    "pass": (ns / n >= P3_FLOOR) if n else False,
                    "no_run": (ns / n < P3_NO_RUN) if n else True}
    return out


def _register_name_key(con) -> None:
    from loci.model.licence_interval import _register_name_key
    _register_name_key(con)


def p5_ppv(con) -> dict:
    """P5: PPV of an SLA expiry EVENT (business arm) against an INDEPENDENT
    closure signal within +/-12 months, per category.

    THE INDEPENDENT SIGNALS, and why the loaded-source status predicate is
    NOT one of them: `poi_supply_status.poi_status = 'closed'` includes the
    branch "licence expiry date < as-of", which is the SLA expiry itself
    wearing a different column. Using it would score the label against
    itself. What is used:
      * Foursquare `date_closed`  -- staging.poi_closure (228k venues, all
        closures Foursquare has ever published for NYC), and the
        first-seen ledger's `closed_on` where closed_src starts 'foursquare';
      * DOHMH `closed_at_last_inspection` -- staging.poi attrs, dated by the
        last inspection;
      * web/places evidence with verdict 'closed' (analysis.poi_closure_evidence).

    THE JOIN: name key (poi_presence.name_key_of on both sides) + same Loci
    category + within P5_JOIN_M straight-line metres. That is rung B's
    weakness stated in the pre-registration (7.3% identity, 42.6% proximity
    ceiling), so TWO denominators are reported:
      * `ppv_joinable`   events with ANY Foursquare/DOHMH venue of that name
                         and category within 50 m (the business is KNOWN to an
                         independent source, so a closure could have been
                         observed) -- closure within +/-12 m over those;
      * `ppv_determined` closure within +/-12 m over (closure within +/-12 m +
                         events whose matched venue was REFRESHED by Foursquare
                         more than 12 months AFTER the expiry with no closure,
                         i.e. observed trading after the licence lapsed).
    `ppv_joinable` is the pre-registered statistic. `ppv_determined` is
    printed beside it because Foursquare's ~3% closure ascertainment makes the
    first a floor; both are reported, neither is hidden.
    """
    _register_name_key(con)
    con.execute("CREATE OR REPLACE TEMP TABLE _p5_ev AS "
                f"SELECT licence_number, category, name_key, lon, lat, end_date "
                f"FROM {TABLE} WHERE event_business AND lon IS NOT NULL "
                f"AND name_key IS NOT NULL AND name_key <> ''")
    # Independent venues: Foursquare closed partition, Foursquare open cache,
    # Foursquare stale hold-backs, DOHMH closures, web evidence via presence.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _p5_venue AS
        SELECT loci_poi_name_key(name) AS name_key, category, lon, lat,
               date_closed AS closed_on, NULL::DATE AS refreshed_on, 'fsq_closed' AS kind
        FROM staging.poi_closure WHERE category IS NOT NULL AND name IS NOT NULL
        UNION ALL
        SELECT loci_poi_name_key(name), category, ST_X(geom), ST_Y(geom),
               NULL::DATE,
               TRY_CAST(json_extract_string(attrs, '$.refreshed') AS DATE), 'fsq_open'
        FROM staging.poi WHERE source_id = 'foursquare_os_places' AND name IS NOT NULL
        UNION ALL
        SELECT loci_poi_name_key(name), category, ST_X(geom), ST_Y(geom),
               NULL::DATE, date_refreshed, 'fsq_stale'
        FROM staging.poi_stale WHERE name IS NOT NULL
        UNION ALL
        SELECT loci_poi_name_key(name), category, ST_X(geom), ST_Y(geom),
               TRY_CAST(json_extract_string(attrs, '$.last_inspection_date') AS DATE),
               NULL::DATE, 'dohmh_closed'
        FROM staging.poi
        WHERE json_extract_string(attrs, '$.active_basis') = 'closed_at_last_inspection'
          AND name IS NOT NULL
        UNION ALL
        SELECT p.name_key, p.category, p.lon, p.lat, e.evidence_date, NULL::DATE, 'web_closed'
        FROM analysis.poi_closure_evidence e
        JOIN analysis.poi_presence p ON p.poi_id_latest = e.poi_id
        WHERE e.verdict = 'closed' AND e.evidence_date IS NOT NULL
    """)
    from loci.db import METRES_SQL
    metres = METRES_SQL.format(a="ST_Point(e.lon, e.lat)", b="ST_Point(v.lon, v.lat)")
    df = con.execute(f"""
        WITH pairs AS (
            SELECT e.licence_number, e.category, e.end_date,
                   v.kind, v.closed_on, v.refreshed_on
            FROM _p5_ev e
            JOIN _p5_venue v
              ON v.name_key = e.name_key AND v.category = e.category
             AND v.lon BETWEEN e.lon - 0.001 AND e.lon + 0.001
             AND v.lat BETWEEN e.lat - 0.001 AND e.lat + 0.001
             AND {metres} <= {P5_JOIN_M}
        ),
        per AS (
            SELECT licence_number, category,
                   bool_or(closed_on IS NOT NULL
                           AND abs(date_diff('day', end_date, closed_on)) <= {P5_WINDOW_DAYS})
                                                                   AS closed_within,
                   bool_or(closed_on IS NOT NULL)                  AS closed_ever,
                   bool_or(refreshed_on IS NOT NULL
                           AND date_diff('day', end_date, refreshed_on) > {P5_WINDOW_DAYS}
                           AND closed_on IS NULL)                  AS seen_after
            FROM pairs GROUP BY 1, 2
        )
        SELECT e.category,
               count(*)                                            AS n_events,
               count(p.licence_number)                             AS n_joinable,
               count(*) FILTER (WHERE p.closed_within)             AS n_closed_within,
               count(*) FILTER (WHERE p.closed_ever)               AS n_closed_ever,
               count(*) FILTER (WHERE p.seen_after AND NOT p.closed_within) AS n_seen_after
        FROM _p5_ev e LEFT JOIN per p USING (licence_number)
        GROUP BY 1 ORDER BY 1
    """).fetchdf()
    out = {}
    for _, r in df.iterrows():
        nj, nc, ns = int(r["n_joinable"]), int(r["n_closed_within"]), int(r["n_seen_after"])
        ppv_j = nc / nj if nj else None
        ppv_d = nc / (nc + ns) if (nc + ns) else None
        out[r["category"]] = {
            "n_events": int(r["n_events"]), "n_joinable": nj,
            "n_closed_within_12m": nc, "n_closed_ever": int(r["n_closed_ever"]),
            "n_seen_trading_after_12m": ns,
            "ppv_joinable": ppv_j, "ppv_determined": ppv_d,
            "pass_joinable": (ppv_j is not None and ppv_j >= P5_FLOOR),
            "pass_determined": (ppv_d is not None and ppv_d >= P5_FLOOR),
        }
    return out


def event_counts(con) -> dict:
    """>= 200 events per category, under the §1.5 cohort rule (issued
    2016-2021, followed 36 months) AND the raw total, both arms."""
    df = con.execute(f"""
        SELECT category,
               count(*) FILTER (WHERE event_business)                         AS raw_business,
               count(*) FILTER (WHERE event_premises)                         AS raw_premises,
               count(*) FILTER (WHERE issue_date BETWEEN DATE '{COHORT_START}'
                                                     AND DATE '{COHORT_END}')
                                                                              AS cohort_n,
               count(*) FILTER (WHERE event_business
                                  AND issue_date BETWEEN DATE '{COHORT_START}'
                                                     AND DATE '{COHORT_END}'
                                  AND end_date <= issue_date
                                      + INTERVAL '{COHORT_FOLLOWUP_MONTHS} months')
                                                                              AS cohort_business,
               count(*) FILTER (WHERE event_premises
                                  AND issue_date BETWEEN DATE '{COHORT_START}'
                                                     AND DATE '{COHORT_END}'
                                  AND end_date <= issue_date
                                      + INTERVAL '{COHORT_FOLLOWUP_MONTHS} months')
                                                                              AS cohort_premises
        FROM {TABLE}
        WHERE borough IN ('MN', 'BK')
        GROUP BY 1 ORDER BY 1
    """).fetchdf()
    out = {}
    for _, r in df.iterrows():
        cb, cp = int(r["cohort_business"]), int(r["cohort_premises"])
        out[r["category"]] = {
            "raw_business": int(r["raw_business"]), "raw_premises": int(r["raw_premises"]),
            "cohort_n": int(r["cohort_n"]), "cohort_business": cb, "cohort_premises": cp,
            "pass": cb >= MIN_EVENTS and cp >= MIN_EVENTS,
            "provisional": r["category"] in PROVISIONAL_CATEGORIES,
        }
    return out


def checks(con) -> dict:
    """P3', P5 and the >= 200 count, in one dict. Nothing is fit."""
    return {"p3_prime": p3_prime(con), "p5": p5_ppv(con), "events": event_counts(con)}


def coverage(con) -> dict:
    """§2 coverage rule: SLA-licensed count / canonical Loci supply, per
    category. Below 25% no category-wide claim is permitted."""
    from loci.score.supply import DEFAULT_SUPPLY_SET, canonical_poi_sql
    sup = dict(con.execute(
        f"SELECT category, count(*) FROM ({canonical_poi_sql(DEFAULT_SUPPLY_SET)}) "
        f"WHERE category IN ({_cats_sql()}) GROUP BY 1").fetchall())
    lic = dict(con.execute(
        f"SELECT category, count(*) FROM {TABLE} WHERE NOT ended "
        f"AND borough IN ('MN', 'BK') GROUP BY 1").fetchall())
    return {c: {"sla_active": int(lic.get(c, 0)), "canonical": int(sup.get(c, 0)),
                "share": (lic.get(c, 0) / sup[c]) if sup.get(c) else None}
            for c in CATEGORIES}


# ---------------------------------------------------------------------------
# 3. the 400 m address measure
# ---------------------------------------------------------------------------
def _guard(cols: list[str]) -> None:
    from loci.model.storefront_pipeline import _guard as pipeline_guard
    pipeline_guard(cols)


def compute_measure(con, boroughs: list[str] | None, *,
                    radius_m: float | None = None,
                    graph_path=None) -> tuple[pd.DataFrame, dict]:
    """(long frame address_id/borough/category + MEASURE_COLUMNS, report).
    READ-ONLY. One network sweep for all four categories x two weights."""
    from loci.model.walk_catchment import load_addresses, network_sums

    asof = con.execute(f"SELECT max(label_asof) FROM {TABLE}").fetchone()[0]
    if asof is None:
        raise RuntimeError(f"{TABLE} is empty -- run `loci licence-events build` first")
    pts = con.execute(f"""
        SELECT category, lon, lat,
               1.0 AS n, CASE WHEN event_5y_business THEN 1.0 ELSE 0.0 END AS ev
        FROM {TABLE}
        WHERE at_risk_5y AND successor_checkable AND lon IS NOT NULL AND lat IS NOT NULL
    """).fetchdf()
    if pts.empty:
        raise RuntimeError(
            "no at-risk, checkable, placed licences -- writing zeros onto every "
            "address would read as 'no bar in New York holds a licence'.")
    weight_cols = []
    for c in CATEGORIES:
        for m in ("n", "ev"):
            col = f"{m}__{c}"
            pts[col] = pts[m].where(pts["category"] == c, 0.0)
            weight_cols.append(col)
    addr = load_addresses(con, boroughs)
    sums, rep = network_sums(pts, weight_cols, addr, radius_m=radius_m,
                             graph_path=graph_path)
    run_at = dt.datetime.now()
    frames = []
    for c in CATEGORIES:
        n = sums[f"n__{c}"].round().astype("int64")
        ev = sums[f"ev__{c}"].round().astype("int64")
        frames.append(pd.DataFrame({
            "address_id": sums["address_id"], "borough": sums["borough"],
            "category": c, "n_licences_400m": n, "n_nonrenewed_400m": ev,
            "nonrenewal_rate_5y_400m": (ev / n.where(n > 0)).astype(float),
        }))
    out = pd.concat(frames, ignore_index=True)
    out["licence_asof"] = asof
    out["licence_run_at"] = run_at
    rep.update({"asof": asof.isoformat(), "rows": len(out),
                "boroughs": list(boroughs) if boroughs else "ALL",
                "address_categories_with_licences": int((out["n_licences_400m"] > 0).sum()),
                "max_n_400m": int(out["n_licences_400m"].max()),
                "max_nonrenewed_400m": int(out["n_nonrenewed_400m"].max())})
    return out, rep


def write_measure(con, df: pd.DataFrame, boroughs: list[str] | None) -> int:
    """RESET then UPDATE analysis.address_category, in scope. The eleven
    categories with no SLA vocabulary stay NULL: NULL = no licence source,
    0 = a licence source that saw nothing within 400 m."""
    _guard(MEASURE_COLUMNS)
    reset = ", ".join(f"{c} = NULL" for c in MEASURE_COLUMNS)
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        con.execute(f"UPDATE analysis.address_category SET {reset} "
                    f"WHERE borough IN ({holes})", list(boroughs))
    else:
        con.execute(f"UPDATE analysis.address_category SET {reset}")
    payload = df[["address_id", "borough", "category", *MEASURE_COLUMNS]]
    con.register("_le", payload)
    try:
        sets = ", ".join(f"{c} = _le.{c}" for c in MEASURE_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address_category AS ac SET {sets}
            FROM _le
            WHERE ac.address_id = _le.address_id AND ac.borough = _le.borough
              AND ac.category = _le.category
        """)
    finally:
        con.unregister("_le")
    return len(payload)


def validate_measure(con, boroughs: list[str] | None) -> list[str]:
    problems: list[str] = []
    scope, params = "", []
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        scope, params = f"AND borough IN ({holes})", list(boroughs)
    n_rows, n_have = con.execute(
        f"SELECT count(*), count(n_licences_400m) FROM analysis.address_category "
        f"WHERE category IN ({_cats_sql()}) {scope}", params).fetchone()
    if n_have != n_rows:
        problems.append(f"{n_rows - n_have:,} address x licence-category rows carry NULL "
                        f"n_licences_400m; 0 is a value, NULL is 'not run'")
    bad = con.execute(
        f"SELECT count(*) FROM analysis.address_category "
        f"WHERE n_nonrenewed_400m > n_licences_400m {scope}", params).fetchone()[0]
    if bad:
        problems.append(f"{bad:,} rows have more non-renewals than licences")
    totals = dict(con.execute(
        f"SELECT category, count(*) FROM {TABLE} WHERE at_risk_5y AND successor_checkable "
        f"GROUP BY 1").fetchall())
    for cat, mx in con.execute(
            f"SELECT category, max(n_licences_400m) FROM analysis.address_category "
            f"WHERE n_licences_400m IS NOT NULL {scope} GROUP BY 1", params).fetchall():
        if mx is not None and cat in totals and mx > totals[cat]:
            problems.append(f"{cat}: max n_licences_400m {mx} exceeds the {totals[cat]} "
                            f"at-risk licences in the whole table -- a catchment counts twice")
    return problems


def build_measure(con, boroughs: list[str] | None, *, radius_m=None,
                  graph_path=None, dry_run: bool = False) -> tuple[pd.DataFrame, dict]:
    df, rep = compute_measure(con, boroughs, radius_m=radius_m, graph_path=graph_path)
    if not dry_run:
        rep["_written"] = write_measure(con, df, boroughs)
        rep["_problems"] = validate_measure(con, boroughs)
    return df, rep
