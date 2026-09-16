"""The D109 CANDIDATE predicate -- which brands reach the queue, and why.

`docs/chains-process.md` "Sourcing and admission" is the specification; this
module is the executable copy of it. A brand enters CANDIDATE when ALL hold:

    n_sources >= 2                          after aliasing: two spellings of
                                            one chain are one two-source brand
    locations_total >= 5  OR  flagged       `flag_for` catches the small-fast
                                            mover a size floor never sees
    not in an excluded class                chains/exclusions.py
    movement in the last 12 months          an opening, a press hit, or a
                                            filing. A brand that has not moved
                                            is a logo, not a lead.
    not already admitted, not rejected      a rejection has to stick, or the
                                            same brands return every month

THE ESCAPE HATCH, and why it is not optional. A rejection that never expires
turns a correct decision made on thin data into a permanent blind spot: a
brand rejected at 5 locations that is now at 20 is exactly the lead the list
exists to produce, and nobody will ever re-read a rejected row by hand. So a
rejected key RE-SURFACES when `locations_total` has at least DOUBLED since the
count recorded at the decision (`locations_at_decision` in watchlist.yaml), or
when a `capital_events` entry on the row is dated AFTER `decided_on` -- news
the rejection did not have. Doubling, not a fixed step, because the useful
signal is proportional -- 5 -> 10 and 40 -> 80 are both "this is a different
company now", while "+5 locations" is noise on a 400-store chain.

A rejected row with NO `locations_at_decision` cannot re-surface on the
doubling arm at all -- there is nothing to double. That is reported rather
than silently treated as zero, because a silent zero would make every old
rejection re-surface forever.

WHAT THIS MODULE DOES NOT DO. It does not rank by quality, and the reason
string is not a recommendation. It says which clause fired. Under the
2026-09-15 owner ruling the monthly job auto-admits everything that clears
this predicate, so the string is what the owner reads when deciding whether to
reject after the fact -- it has to name the evidence, not summarize it.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field

from loci.chains import detect as detect_mod
from loci.chains.exclusions import CLASS_NAMES, exclude_rule

#: Distinct staging.poi sources a brand needs. One source is one dataset's
#: opinion; the same storefront in two independent datasets is a fact.
MIN_SOURCES = 2

#: The size arm of the floor. The OR with `flagged` does the real work -- see
#: the module docstring and D109.
MIN_LOCATIONS = 5

#: `sales_role: incumbent` at and above this count. Not an exclusion: an
#: incumbent is off the broker lead list's default sort but IS the "brand X is
#: opening nearby" signal on a D19 recommend card.
INCUMBENT_LOCATIONS = 100

#: Supermarket co-op banners (owner ruling, 2026-09-15): a banner licensed by
#: a buying group (Key Food, Associated, etc.) to many INDEPENDENTLY OWNED
#: supermarkets. `locations_total` here counts stores under one sign, not one
#: company's footprint, so treating a 122-location banner as a single fast-
#: growing prospect would be wrong in the other direction from `exclude` --
#: these are real, countable supply, just never a single site-selection lead.
#: They are therefore never excluded (unlike `bank_clinic_category` etc. in
#: `exclusions.py`); they are ADMITTED and pinned to `incumbent` regardless of
#: count, so they sort off the broker lead list without disappearing from it.
#: Keys are post-alias (see the "supermarket co-op banner" block in
#: `normalize.ALIASES`) plus the handful of banners that had only one filing
#: spelling in the 2026-09 snapshot.
COOP_BANNERS: frozenset[str] = frozenset({
    "key food", "associated supermarket", "fine fare supermarkets",
    "pioneer supermarket", "bravo supermarkets", "c town", "met food",
    "met fresh supermarket", "foodtown", "food bazaar", "ideal food basket",
    "food emporium", "compare foods", "superfresh", "food universe marketplace",
})

#: The prose appended to a co-op banner's candidate reason (and, via
#: `auto_admit`, its `admission_reason`), so the WHY behind the forced
#: `incumbent` role travels with the row instead of only living in this file.
COOP_BANNER_NOTE = "co-op banner: no single site-selector"

#: A rejected brand re-surfaces when its count has grown by this multiple.
RESURFACE_MULTIPLE = 2

#: The press window, in days. `chains.press_hits` only holds a 45-day live
#: queue today (D110), so `press_hits_12m` is a FLOOR and will undercount
#: older coverage until the table accrues a year of history.
PRESS_WINDOW_DAYS = 365


def sales_role_for(row: Mapping) -> str:
    """`incumbent` at 100+ NYC locations, else `prospect` -- except a
    supermarket co-op banner (`COOP_BANNERS`), which is `incumbent` at ANY
    count: the number is a banner over many independent owners, never one
    operator's growth, so it never earns `prospect`'s "sell this" framing.

    `contraction` and `excluded` exist in the vocabulary but are never derived
    here: contraction needs a cross-snapshot delta (NULL until two snapshots)
    and `excluded` is what the exclusion rule set already expresses by keeping
    the row out of the queue entirely."""
    if row.get("brand_key") in COOP_BANNERS:
        return "incumbent"
    total = row.get("locations_total") or 0
    return "incumbent" if int(total) >= INCUMBENT_LOCATIONS else "prospect"


def _as_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _capital_event_reason(rejected_row: Mapping) -> str | None:
    """The capital-event arm, armed 2026-09-16 (GTM-189).

    SINCE, not ever. A rejected row keeps whatever `capital_events` a curator
    had already recorded about the brand -- the funding round that was public
    BEFORE the rejection was part of what the rejection was made on, and
    re-surfacing on it would mean the rejection never sticks at all. Only an
    event dated AFTER `decided_on` is news the decision did not have.

    An undated event is ignored here and rejected by `watchlist.validate`, so
    the two halves cannot disagree about what "since" means. A rejection with
    no `decided_on` (hand-written into the YAML rather than through
    `loci chains reject`) has no "since" to measure against, so any dated
    event re-opens it -- the conservative direction: the cost is one row back
    in a review queue, against a brand that stays invisible after the news
    that should have re-opened it."""
    decided_on = _as_date(rejected_row.get("decided_on"))
    for ev in rejected_row.get("capital_events") or []:
        if not isinstance(ev, Mapping):
            continue
        when = _as_date(ev.get("date"))
        if when is None:
            continue
        if decided_on is None or when > decided_on:
            kind = ev.get("kind") or "capital event"
            return f"{kind} dated {when.isoformat()} since rejection"
    return None


def _resurface_reason(row: Mapping, rejected_row: Mapping) -> str | None:
    """Why a rejected brand comes back, or None if the rejection still holds."""
    capital = _capital_event_reason(rejected_row)
    if capital:
        return capital
    at_decision = rejected_row.get("locations_at_decision")
    if at_decision in (None, "", 0):
        return None
    try:
        at_decision = int(at_decision)
        total = int(row.get("locations_total") or 0)
    except (TypeError, ValueError):
        return None
    if at_decision > 0 and total >= RESURFACE_MULTIPLE * at_decision:
        return (f"rejected at {at_decision} locations, now {total} "
                f"({RESURFACE_MULTIPLE}x)")
    return None


def candidate_reason(row: Mapping, *, press_hits_12m: int = 0,
                     pipeline_open: int = 0,
                     admitted: set[str] | frozenset[str] = frozenset(),
                     rejected: dict[str, dict] | None = None) -> str | None:
    """The D109 predicate. Returns the reason it fired, or None.

    Pure: every input the predicate reads is an argument, so the whole rule is
    testable without a warehouse. `row` is one `chains.brand_latest` record."""
    rejected = rejected or {}
    key = row.get("brand_key")
    if not key:
        return None

    if int(row.get("n_sources") or 0) < MIN_SOURCES:
        return None

    total = int(row.get("locations_total") or 0)
    flagged = bool(row.get("flagged"))
    if total < MIN_LOCATIONS and not flagged:
        return None

    if exclude_rule(row) is not None:
        return None

    new_12m = int(row.get("locations_new_12m") or 0)
    press = int(press_hits_12m or 0)
    pipeline = int(pipeline_open or 0)
    if new_12m < 1 and press < 1 and pipeline < 1:
        return None

    if key in admitted:
        return None

    resurfaced = None
    if key in rejected:
        resurfaced = _resurface_reason(row, rejected[key])
        if resurfaced is None:
            return None

    parts: list[str] = []
    if resurfaced:
        parts.append(f"RE-SURFACED: {resurfaced}")
    if total >= MIN_LOCATIONS:
        parts.append(f"{total} locations (5+ floor)")
    if flagged:
        # `flag_reason` already spells the 12-month count out ("42 new
        # locations in 12 months"), so a separate "42 new in 12m" clause said
        # the same number twice on every flagged row -- and 799 of 799 rows in
        # the first live run were flagged.
        parts.append(str(row.get("flag_reason") or "flagged by detect"))
    elif new_12m >= 1:
        parts.append(f"{new_12m} new in 12m")
    if press >= 1:
        parts.append(f"{press} press hit{'s' if press > 1 else ''} in 12m")
    if pipeline >= 1:
        parts.append(f"{pipeline} not-yet-open filing{'s' if pipeline > 1 else ''}")
    if key in COOP_BANNERS:
        parts.append(COOP_BANNER_NOTE)
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# The SQL: brand_latest for one month, plus the two movement signals detect
# cannot see.
# ---------------------------------------------------------------------------

def _table_exists(con, schema: str, name: str) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, name]).fetchone()[0])


def _has_column(con, relation: str, column: str) -> bool:
    """Whether `schema.relation` exposes `column`. Views are included, and a
    STALE view is the case this guards: chains.brand_latest is `SELECT s.*` and
    DuckDB binds a view's columns at CREATE time, so a warehouse whose sql/039
    has been applied to the table but whose view was never re-created would
    otherwise be asked for a column it cannot produce."""
    schema, _, name = relation.partition(".")
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ? AND column_name = ?",
        [schema, name, column]).fetchone()[0])


def _base_relation(con, month: str) -> str:
    """`chains.brand_latest` where it applies, `chains.brand_snapshot` otherwise.

    brand_latest is pinned to `max(snapshot_month)` by its own definition, so
    asking it for an older month returns nothing at all -- which would read as
    "no candidates" rather than as "wrong relation". Re-reading an older month
    loses `locations_delta_since` and `months_observed`, which is correct: they
    are computed against the newest snapshot."""
    return ("chains.brand_latest" if month == detect_mod.latest_month(con)
            else "chains.brand_snapshot")


def rows_sql(con, month: str, since: dt.date) -> tuple[str, list]:
    """(sql, params) for one month of candidate INPUT rows.

    Degrades rather than raising when `chains.press_hits` or
    `analysis.storefront_pipeline` has not been built: the movement test then
    rests on `locations_new_12m` alone, which is the honest reading of "we did
    not measure that channel" -- not of "there was no press".

    Params are positional and the CTEs are emitted in a fixed order (base, then
    press, then pipe), so the params list is built in that same order here and
    nowhere else.

    `press_hits_12m` PREFERS THE SNAPSHOT'S OWN COLUMN where sql/039 has been
    applied (GTM-189): that number was measured with the snapshot, in the
    snapshot's twelve calendar months, and re-deriving it live against a press
    table that has moved since would mean the reason a brand was admitted can
    no longer be reproduced. The live join stays as the fallback, for a
    pre-migration snapshot and for the case where the column is NULL because
    `chains.press_hits` did not exist when detect ran.

    `pipeline_open` IS NOT REPLACED by the snapshot's `pipeline_filings_12m`.
    They are different measures and substituting one would change the
    predicate: `pipeline_filings_12m` counts ALL filings in twelve months,
    `pipeline_open` counts only NOT-yet-open ones, because an open filing is a
    store detect has already counted and is not movement. The snapshot's count
    is carried through as a reporting column beside it."""
    params: list = [month]
    if _table_exists(con, "chains", "press_hits"):
        press = """
        press AS (
            SELECT brand_key, count(*) AS press_hits_12m
            FROM chains.press_hits
            WHERE brand_key <> '' AND published_on IS NOT NULL
              AND published_on >= ?
            GROUP BY 1
        )"""
        params.append(since.isoformat())
    else:
        press = """
        press AS (SELECT '' AS brand_key, 0 AS press_hits_12m WHERE FALSE)"""

    if _table_exists(con, "analysis", "storefront_pipeline"):
        # NOT-YET-OPEN rows only: an open filing is a store that already
        # exists and is already counted by detect. `business_name_key` IS
        # `chains.normalize.brand_key` (model/storefront_pipeline.py imports
        # the same function), so this join is exact, not approximate.
        pipe = """
        pipe AS (
            SELECT business_name_key AS brand_key, count(*) AS pipeline_open
            FROM analysis.storefront_pipeline
            WHERE NOT is_open AND business_name_key IS NOT NULL
            GROUP BY 1
        )"""
    else:
        pipe = """
        pipe AS (SELECT '' AS brand_key, 0 AS pipeline_open WHERE FALSE)"""

    relation = _base_relation(con, month)
    if _has_column(con, relation, "press_hits_12m"):
        # EXCLUDE so the snapshot's column and the joined one do not collide;
        # COALESCE so the snapshot wins where it has a value and the live join
        # still answers for a pre-migration month.
        select = """
        SELECT b.* EXCLUDE (press_hits_12m),
               COALESCE(b.press_hits_12m, p.press_hits_12m, 0) AS press_hits_12m,
               COALESCE(q.pipeline_open, 0)  AS pipeline_open"""
    else:
        select = """
        SELECT b.*,
               COALESCE(p.press_hits_12m, 0) AS press_hits_12m,
               COALESCE(q.pipeline_open, 0)  AS pipeline_open"""

    sql = f"""
        WITH base AS (
            SELECT * FROM {relation} WHERE snapshot_month = ?
        ),{press},{pipe}{select}
        FROM base b
        LEFT JOIN press p ON p.brand_key = b.brand_key
        LEFT JOIN pipe  q ON q.brand_key = b.brand_key
    """
    return sql, params


def fetch(con, *, month: str | None = None,
          today: dt.date | None = None) -> tuple[str | None, list[dict]]:
    """(month, rows). Read-only. Returns (None, []) when no snapshot exists."""
    today = today or dt.date.today()
    month = month or detect_mod.latest_month(con)
    if month is None:
        return None, []
    since = today - dt.timedelta(days=PRESS_WINDOW_DAYS)
    sql, params = rows_sql(con, month, since)
    return month, con.execute(sql, params).fetchdf().to_dict("records")


# ---------------------------------------------------------------------------
# Selection and counts
# ---------------------------------------------------------------------------

@dataclass
class CandidateRun:
    """One month's queue, with the counts that make the number auditable."""
    month: str | None
    rows: list[dict] = field(default_factory=list)
    n_rows: int = 0
    n_predicate: int = 0
    n_excluded: int = 0
    excluded_by_class: dict[str, int] = field(default_factory=dict)
    n_admitted: int = 0
    n_rejected: int = 0
    n_resurfaced: int = 0

    @property
    def n_candidates(self) -> int:
        return len(self.rows)


def select(rows: list[dict], *, month: str | None = None,
           admitted: set[str] | frozenset[str] = frozenset(),
           rejected: dict[str, dict] | None = None) -> CandidateRun:
    """Apply the predicate to a month of rows and count every stage.

    The counts are the point as much as the list is: "892 candidates" is not
    reviewable, "1,014 met the predicate, 72 excluded (68 bank/clinic, 4 fuel),
    50 already admitted" is. Sorted by `locations_new_12m` then
    `locations_total`, both descending -- the fast mover above the big one."""
    rejected = rejected or {}
    run = CandidateRun(month=month, n_rows=len(rows),
                       excluded_by_class={n: 0 for n in CLASS_NAMES})

    for row in rows:
        key = row.get("brand_key")
        if not key:
            continue
        if int(row.get("n_sources") or 0) < MIN_SOURCES:
            continue
        total = int(row.get("locations_total") or 0)
        if total < MIN_LOCATIONS and not bool(row.get("flagged")):
            continue
        press = int(row.get("press_hits_12m") or 0)
        pipeline = int(row.get("pipeline_open") or 0)
        if int(row.get("locations_new_12m") or 0) < 1 and press < 1 and pipeline < 1:
            continue

        # Everything below this line met the NUMERIC predicate. The stages are
        # counted separately so the drop from each one is readable.
        run.n_predicate += 1

        rule = exclude_rule(row)
        if rule is not None:
            run.n_excluded += 1
            run.excluded_by_class[rule.name] = run.excluded_by_class.get(rule.name, 0) + 1
            continue
        if key in admitted:
            run.n_admitted += 1
            continue

        reason = candidate_reason(row, press_hits_12m=press, pipeline_open=pipeline,
                                  admitted=admitted, rejected=rejected)
        if reason is None:
            run.n_rejected += 1
            continue
        if key in rejected:
            run.n_resurfaced += 1

        out = dict(row)
        out["reason"] = reason
        out["sales_role"] = sales_role_for(row)
        run.rows.append(out)

    run.rows.sort(key=lambda r: (int(r.get("locations_new_12m") or 0),
                                 int(r.get("locations_total") or 0)),
                  reverse=True)
    return run


def run(con, *, month: str | None = None, doc: dict | None = None,
        today: dt.date | None = None) -> CandidateRun:
    """Fetch + select, reading the admitted/rejected sets from watchlist.yaml."""
    from loci.chains import watchlist as wl

    doc = doc if doc is not None else wl.load()
    month, rows = fetch(con, month=month, today=today)
    return select(rows, month=month, admitted=wl.admitted_keys(doc),
                  rejected=wl.rejected_rows(doc))
