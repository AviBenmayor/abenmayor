"""Went-dark triangulation: stale Foursquare venues x LL157 vacancy flips x
SLA licence ends -> `analysis.closure_triangulation` (STAGED, never promoted
here).

sql/052_closure_triangulation.sql carries the rationale, the D79 rule as a
CHECK, and why these rows are not evidence rows yet. Read it first.

THE RULE, restated once: a stale venue alone writes NOTHING. It is written
only when at least one INDEPENDENT premises signal agrees:

  ll157_vacancy_flip  a storefront_year premises within RADIUS_M whose
                      occupancy went occupied -> vacant between two
                      consecutive OBSERVED reporting years, the vacant
                      observation on or after (date_refreshed - LOOKBACK_DAYS).
                      The EARLIEST such flip per venue is kept: it is the
                      tightest upper bound.
  licence_end         a licence_event row of the same category and name key
                      within RADIUS_M with event_premises = TRUE (no successor
                      of any kind at the BBL), end on or after the same
                      look-back. Earliest end kept.

`would_flip` is what promotion would move: the stale venue matched to a
poi_presence location (same category, same name key, within RADIUS_M) whose
`poi_supply_status.poi_status` is not already 'closed'. It is an UPPER BOUND
on the hash move -- the evidence-precedence rule (model/poi_evidence.py) only
lets dated evidence overturn a dated 'open', so the realised flip count can be
smaller, never larger.

Never writes 'open'. Never touches staging.poi, poi_status or the evidence
ledger.
"""
from __future__ import annotations

import datetime as dt

TABLE = "analysis.closure_triangulation"
STALE_TABLE = "staging.poi_stale"

RADIUS_M = 30.0
LOOKBACK_DAYS = 365
#: When LL157 and a licence end both speak, the licence end must fall inside
#: the LL157 window widened by this many days on each side.
AGREE_DAYS = 180

KIND_STALE = "stale"
KIND_FLIP = "ll157_vacancy_flip"
KIND_LICENCE = "licence_end"

#: Which LL157 `activity_canonical` classes a stale venue of each Loci
#: category may be corroborated by. THE FAN-OUT GUARD: 30 m of a Manhattan
#: premises holds several stale venues, and without this filter one FOOD
#: SERVICES unit going dark "corroborated" the nail salon, the bank and the
#: cafe next door alike (measured 2026-09-17: 4,125 flips for 9,900 rows).
#: A premises flip only speaks for a venue whose trade it could have housed.
#: The classes are DOF's twelve, post-recode (sql/012_activity_recode.yaml);
#: NULL and the two "no activity" labels are treated as unknown and ALLOWED --
#: an unknown class is not evidence the trade differed.
ACTIVITY_COMPATIBLE: dict[str, tuple[str, ...]] = {
    "restaurant":    ("FOOD SERVICES",),
    "cafe_bakery":   ("FOOD SERVICES", "RETAIL"),
    "bar":           ("FOOD SERVICES",),
    "grocery":       ("RETAIL", "FOOD SERVICES"),
    "convenience":   ("RETAIL", "FOOD SERVICES"),
    "pharmacy":      ("RETAIL", "HEALTH CARE OR SOCIAL ASSISTANCE"),
    "hardware":      ("RETAIL",),
    "hair_barber":   ("MISCELLANEOUS OTHER SERVICE", "OTHER", "RETAIL"),
    "nails_beauty":  ("MISCELLANEOUS OTHER SERVICE", "OTHER", "RETAIL"),
    "laundry":       ("MISCELLANEOUS OTHER SERVICE", "OTHER"),
    "tailor_repair": ("MISCELLANEOUS OTHER SERVICE", "OTHER", "RETAIL"),
    "clinic":        ("HEALTH CARE OR SOCIAL ASSISTANCE", "OTHER"),
    "childcare":     ("HEALTH CARE OR SOCIAL ASSISTANCE", "EDUCATIONAL SERVICES", "OTHER"),
    "fitness":       ("OTHER", "MISCELLANEOUS OTHER SERVICE", "EDUCATIONAL SERVICES"),
    "bank":          ("FINANCE & INSURANCE",),
}
UNKNOWN_ACTIVITY = ("NO BUSINESS ACTIVITY IDENTIFIED", "NO BUSINESS ACTIVITY REPORTED")


def _compat_sql() -> str:
    """A VALUES table (category, activity) of the compatible pairs."""
    rows = ", ".join(
        f"('{c}', '{a}')" for c, acts in sorted(ACTIVITY_COMPATIBLE.items()) for a in acts)
    return f"(VALUES {rows}) AS compat(category, activity)"


def _register_name_key(con) -> None:
    from loci.model.licence_interval import _register_name_key
    _register_name_key(con)


def build(con, *, asof: dt.date | None = None) -> dict:
    """Full DELETE-then-INSERT; idempotent. Returns the report."""
    from loci.db import METRES_SQL
    from loci.model.licence_event import TABLE as LICENCE_TABLE

    asof = asof or dt.date.today()
    _register_name_key(con)
    n_stale = con.execute(f"SELECT count(*) FROM {STALE_TABLE}").fetchone()[0]
    if not n_stale:
        raise RuntimeError(
            f"{STALE_TABLE} is empty -- nothing to triangulate. An empty stale "
            f"set is an ingest that never ran, not a city where every venue "
            f"is fresh.")

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _tri_stale AS
        SELECT poi_id, source_id, category, name, loci_poi_name_key(name) AS name_key,
               ST_X(geom) AS lon, ST_Y(geom) AS lat, geom, date_refreshed, opened_on,
               coalesce(date_refreshed, DATE '1900-01-01') - INTERVAL '{LOOKBACK_DAYS} days'
                   AS lookback_from
        FROM {STALE_TABLE}
    """)

    # ---- kind A: LL157 vacancy flip within RADIUS_M, compatible trade ------
    m_flip = METRES_SQL.format(a="s.geom", b="ST_Point(f.lon, f.lat)")
    unknown = ", ".join(f"'{u}'" for u in UNKNOWN_ACTIVITY)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _tri_flip AS
        WITH yr AS (
            SELECT premises_id, reporting_year, vacant, activity_canonical, lon, lat,
                   coalesce(observed_1231, filing_due_date) AS observed_on,
                   lead(reporting_year) OVER w AS next_year,
                   lead(vacant) OVER w AS next_vacant,
                   lead(coalesce(observed_1231, filing_due_date)) OVER w AS next_observed_on
            FROM analysis.storefront_year
            WHERE lon IS NOT NULL AND lat IS NOT NULL
            WINDOW w AS (PARTITION BY premises_id ORDER BY reporting_year)
        ),
        flips AS (
            SELECT premises_id, activity_canonical, lon, lat,
                   observed_on AS last_occupied_on, next_observed_on AS first_vacant_on
            FROM yr
            WHERE vacant IS FALSE AND next_vacant IS TRUE
              AND next_year = reporting_year + 1
        )
        SELECT s.poi_id, f.premises_id, f.activity_canonical,
               f.last_occupied_on, f.first_vacant_on, {m_flip} AS metres
        FROM _tri_stale s
        JOIN flips f
          ON f.lon BETWEEN s.lon - 0.0006 AND s.lon + 0.0006
         AND f.lat BETWEEN s.lat - 0.0005 AND s.lat + 0.0005
         AND {m_flip} <= {RADIUS_M}
         AND f.first_vacant_on >= s.lookback_from
        LEFT JOIN {_compat_sql()}
          ON compat.category = s.category AND compat.activity = f.activity_canonical
        WHERE compat.category IS NOT NULL
           OR f.activity_canonical IS NULL
           OR f.activity_canonical IN ({unknown})
        QUALIFY row_number() OVER (PARTITION BY s.poi_id
                                   ORDER BY f.first_vacant_on, {m_flip}, f.premises_id) = 1
    """)

    # ---- kind B: licence end, premises arm, same name key ------------------
    m_lic = METRES_SQL.format(a="s.geom", b="ST_Point(l.lon, l.lat)")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _tri_lic AS
        SELECT s.poi_id, l.licence_number, l.end_date, {m_lic} AS metres
        FROM _tri_stale s
        JOIN {LICENCE_TABLE} l
          ON l.category = s.category
         AND l.event_premises
         AND l.name_key IS NOT NULL AND l.name_key <> ''
         AND l.name_key = s.name_key
         AND l.lon BETWEEN s.lon - 0.0006 AND s.lon + 0.0006
         AND l.lat BETWEEN s.lat - 0.0005 AND s.lat + 0.0005
         AND {m_lic} <= {RADIUS_M}
         AND l.end_date >= s.lookback_from
        QUALIFY row_number() OVER (PARTITION BY s.poi_id
                                   ORDER BY l.end_date, {m_lic}, l.licence_number) = 1
    """)

    # ---- the presence match: what promotion would touch --------------------
    m_pres = METRES_SQL.format(a="s.geom", b="ST_Point(p.lon, p.lat)")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _tri_match AS
        SELECT s.poi_id, p.location_key, p.poi_id_latest, st.poi_status
        FROM _tri_stale s
        JOIN analysis.poi_presence p
          ON p.category = s.category
         AND p.name_key = s.name_key AND s.name_key IS NOT NULL AND s.name_key <> ''
         AND p.lon BETWEEN s.lon - 0.0006 AND s.lon + 0.0006
         AND p.lat BETWEEN s.lat - 0.0005 AND s.lat + 0.0005
         AND {m_pres} <= {RADIUS_M}
        LEFT JOIN analysis.poi_supply_status st ON st.poi_id = p.poi_id_latest
        QUALIFY row_number() OVER (PARTITION BY s.poi_id
                                   ORDER BY {m_pres}, p.location_key) = 1
    """)

    # TWO KINDS MUST DESCRIBE THE SAME CLOSURE. A licence that ended in 2017
    # at a premises LL157 saw occupied through 2020 is not evidence for the
    # 2021 vacancy -- the business traded on after the lapse, or a successor
    # did. When both kinds are present the licence end has to fall inside
    # the LL157 window widened by AGREE_DAYS on each side, or it is dropped
    # from that row (the flip alone still corroborates). With both kept, the
    # bound is LL157's observed window; the licence is corroboration, not a
    # tighter bound.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _tri_lic2 AS
        SELECT l.* FROM _tri_lic l
        LEFT JOIN _tri_flip f USING (poi_id)
        WHERE f.poi_id IS NULL
           OR l.end_date BETWEEN f.last_occupied_on - INTERVAL '{AGREE_DAYS} days'
                             AND f.first_vacant_on + INTERVAL '{AGREE_DAYS} days'
    """)
    n_lic_dropped = con.execute(
        "SELECT (SELECT count(*) FROM _tri_lic) - (SELECT count(*) FROM _tri_lic2)").fetchone()[0]

    con.execute("BEGIN")
    try:
        con.execute(f"DELETE FROM {TABLE}")
        con.execute(f"""
            INSERT INTO {TABLE} (
                stale_poi_id, source_id, category, name, name_key, lon, lat, geom,
                date_refreshed, opened_on, kinds, n_kinds,
                flip_premises_id, flip_activity, flip_last_occupied_on,
                flip_first_vacant_on, flip_m, flip_shared_by,
                licence_number, licence_end_on, licence_m,
                closed_after, closed_before,
                matched_location_key, matched_poi_id, matched_status_now, would_flip,
                asof_date, built_at)
            SELECT s.poi_id, s.source_id, s.category, s.name, s.name_key, s.lon, s.lat,
                   s.geom, s.date_refreshed, s.opened_on,
                   '{KIND_STALE}'
                     || CASE WHEN f.poi_id IS NOT NULL THEN ',{KIND_FLIP}' ELSE '' END
                     || CASE WHEN l.poi_id IS NOT NULL THEN ',{KIND_LICENCE}' ELSE '' END,
                   1 + (f.poi_id IS NOT NULL)::SMALLINT + (l.poi_id IS NOT NULL)::SMALLINT,
                   f.premises_id, f.activity_canonical, f.last_occupied_on,
                   f.first_vacant_on, f.metres,
                   CASE WHEN f.poi_id IS NOT NULL THEN count(*) OVER (
                        PARTITION BY f.premises_id, f.first_vacant_on) END,
                   l.licence_number, l.end_date, l.metres,
                   f.last_occupied_on,
                   coalesce(f.first_vacant_on, l.end_date),
                   m.location_key, m.poi_id_latest, m.poi_status,
                   (m.poi_id_latest IS NOT NULL
                    AND coalesce(m.poi_status, 'unknown') <> 'closed'),
                   DATE '{asof}', now()
            FROM _tri_stale s
            LEFT JOIN _tri_flip f USING (poi_id)
            LEFT JOIN _tri_lic2 l USING (poi_id)
            LEFT JOIN _tri_match m USING (poi_id)
            WHERE f.poi_id IS NOT NULL OR l.poi_id IS NOT NULL
        """)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    rep = report(con, n_stale=int(n_stale))
    rep["licence_kind_dropped_as_inconsistent"] = int(n_lic_dropped)
    return rep


def report(con, *, n_stale: int | None = None) -> dict:
    n_stale = n_stale if n_stale is not None else int(
        con.execute(f"SELECT count(*) FROM {STALE_TABLE}").fetchone()[0])
    by_kinds = {int(k): int(v) for k, v in con.execute(
        f"SELECT n_kinds, count(*) FROM {TABLE} GROUP BY 1").fetchall()}
    by_combo = {k: int(v) for k, v in con.execute(
        f"SELECT kinds, count(*) FROM {TABLE} GROUP BY 1 ORDER BY 1").fetchall()}
    written, matched, flip_any, flip_unknown, flip_open = con.execute(f"""
        SELECT count(*), count(matched_poi_id),
               count(*) FILTER (WHERE would_flip),
               count(*) FILTER (WHERE would_flip
                                  AND coalesce(matched_status_now, 'unknown') = 'unknown'),
               count(*) FILTER (WHERE would_flip AND matched_status_now = 'open')
        FROM {TABLE}""").fetchone()
    by_cat = {k: int(v) for k, v in con.execute(
        f"SELECT category, count(*) FROM {TABLE} GROUP BY 1 ORDER BY 2 DESC").fetchall()}
    shared = con.execute(
        f"SELECT count(*) FILTER (WHERE flip_shared_by = 1), "
        f"count(*) FILTER (WHERE flip_shared_by > 1), "
        f"count(DISTINCT flip_premises_id) FILTER (WHERE flip_premises_id IS NOT NULL) "
        f"FROM {TABLE}").fetchone()
    return {
        "flip_sole_venue": int(shared[0]),
        "flip_shared_with_other_stale_venues": int(shared[1]),
        "distinct_flip_premises": int(shared[2]),
        "stale_venues": n_stale,
        "written": int(written),
        "not_written_stale_only": n_stale - int(written),
        "by_n_kinds": by_kinds,
        "by_kinds": by_combo,
        "by_category": by_cat,
        "matched_to_presence": int(matched),
        "would_flip_poi_status": int(flip_any),
        "would_flip_from_unknown": int(flip_unknown),
        "would_flip_from_open": int(flip_open),
    }


def validate(con) -> list[str]:
    problems: list[str] = []
    bad = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE kinds NOT LIKE '{KIND_STALE},%'").fetchone()[0]
    if bad:
        problems.append(f"{bad:,} rows are not anchored on a stale venue")
    bad = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE n_kinds <> 1 + (flip_premises_id IS NOT NULL)::INT "
        f"+ (licence_number IS NOT NULL)::INT").fetchone()[0]
    if bad:
        problems.append(f"{bad:,} rows have n_kinds disagreeing with their columns")
    bad = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE closed_after IS NOT NULL "
        f"AND closed_after > closed_before").fetchone()[0]
    if bad:
        problems.append(f"{bad:,} rows have closed_after later than closed_before")
    bad = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE would_flip AND matched_poi_id IS NULL").fetchone()[0]
    if bad:
        problems.append(f"{bad:,} rows claim a flip with no matched POI")
    return problems
