"""CLOSURE EVIDENCE from the web and Google Places -- the THIRD channel that
can move `model/poi_presence.poi_status()` off 'unknown' (D98, GTM-170).

sql/029's predicate reads only what the LOADED SOURCES already publish.
Overture, OSM, the Foursquare open cache and USDA SNAP publish no status
field at all, so most of the universe reads 'unknown' forever from that
predicate alone. This module is the precedence rule that lets a POSITIVE,
PROVENANCED lookup -- `loci verify-closures`, or a report's on-demand check --
override that base verdict, or override an older one with a newer one.

sql/033_poi_closure_evidence.sql carries the schema rationale (D79 compliance,
why `location_key`/`cluster_id` are informational only, the spend ledger
reconciliation with the allocator-report design). Read it before changing
anything here.

THE PRECEDENCE RULE, STATED ONCE (constraint text): "newest evidence date wins,
regardless of source type." Concretely:

  * Evidence with a verdict may override an 'unknown' base UNCONDITIONALLY --
    there is nothing to be newer than.
  * Evidence may override a DATED base ('open' or 'closed', from a loaded
    source) only if the evidence itself carries a real date (`dated_by !=
    'none'`) AND that date is STRICTLY NEWER than the base's own date. A tie
    keeps the base -- an undated web hit or a same-day observation is not
    grounds to flip a dated verdict.
  * `dated_by == 'none'` evidence (an undated web page) can therefore ONLY
    ever resolve an 'unknown' base. It can never overturn a dated 'open' or
    'closed'.

TWO RENDERINGS, ONE RULE. `resolve()` (Python) and `wrap_status_sql()` /
`wrap_basis_sql()` (SQL, composed with `poi_presence.poi_is_open()` /
`poi_status_basis()`) must agree row for row -- tests/test_poi_evidence.py
runs both over one fixture and asserts they do, exactly as
tests/test_poi_colocation.py already does for the base predicate. Two copies
of a precedence rule is how a rule drifts.

`poi_status_date()` / `poi_status_date_sql()` are the base predicate's date
twin: for each branch of `poi_status()`/`poi_is_open()`, WHICH date is that
verdict's own evidence date, for the "strictly newer" comparison above. It is
a SEPARATE function from `poi_status()` (not `poi_status()`'s third return
value) because most existing callers of `poi_status()`/`poi_is_open()` have no
use for it and a third element would be a silent breaking change to every one
of them.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field

from loci.model import poi_presence as pp

STATUS_OPEN = pp.STATUS_OPEN
STATUS_CLOSED = pp.STATUS_CLOSED
STATUS_UNKNOWN = pp.STATUS_UNKNOWN

#: `source` values on analysis.poi_closure_evidence.
SOURCE_PLACES = "places"
SOURCE_WEB = "web"
SOURCES = (SOURCE_PLACES, SOURCE_WEB)

#: `dated_by` values -- see the module docstring's precedence rule.
DATED_PUBLISHED = "published"
DATED_RETRIEVAL = "retrieval"
DATED_NONE = "none"
DATED_BY = (DATED_PUBLISHED, DATED_RETRIEVAL, DATED_NONE)


def _parse_date(v) -> dt.date | None:
    """Same coercion as `poi_presence.poi_status()`'s private `_date` --
    restated rather than imported because that one is a closure, not a
    module-level name."""
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


@dataclass
class EvidenceRow:
    """One row of `analysis.poi_closure_evidence`, before it is written.

    `evidence_id()` is `sha1(poi_id|source|url)` -- the same (poi, source,
    url) lookup re-run later REPLACES its row (`insert_evidence` does
    `INSERT OR REPLACE`) rather than accumulating a duplicate, so a
    `--recheck-days` re-check is a refresh, not a growing history.
    """
    poi_id: str
    verdict: str | None       # 'open' | 'closed' | None (stored, inconclusive)
    source: str               # 'places' | 'web'
    source_name: str
    url: str
    evidence_date: dt.date
    dated_by: str             # 'published' | 'retrieval' | 'none'
    retrieved_at: dt.datetime
    query: str
    domain_class: str | None = None
    location_key: str | None = None
    cluster_id: int | None = None
    reason: str | None = None
    successor_name: str | None = None
    raw: dict | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        if self.verdict is not None and self.verdict not in (STATUS_OPEN, STATUS_CLOSED):
            raise ValueError(f"EvidenceRow.verdict must be 'open', 'closed' or None, "
                              f"got {self.verdict!r}")
        if self.source not in SOURCES:
            raise ValueError(f"EvidenceRow.source must be one of {SOURCES}, got {self.source!r}")
        if self.dated_by not in DATED_BY:
            raise ValueError(f"EvidenceRow.dated_by must be one of {DATED_BY}, got {self.dated_by!r}")

    def evidence_id(self) -> str:
        payload = f"{self.poi_id}|{self.source}|{self.url}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def basis(self) -> str:
        """The provenance string `resolve()` writes into `poi_status_basis`
        when this row wins. Kept as a method (not a free function) so the SQL
        rendering (`_BASIS_SQL` below) has one literal source of truth to be
        tested against."""
        date_s = self.evidence_date.isoformat()
        if self.source == SOURCE_WEB:
            return f"web_evidence:{self.verdict}:{self.domain_class or 'unknown'}:{date_s}:{self.url}"
        return f"google_places:{self.verdict}:{date_s}:{self.url}"


def insert_evidence(con, row: EvidenceRow) -> str:
    """Write one evidence row (INSERT OR REPLACE on `evidence_id`). Returns
    the evidence_id. THE shared insert -- `loci verify-closures` and the
    allocator report's on-demand checks (D100) both call this, so a closure
    verdict is provenanced identically regardless of which caller found it."""
    eid = row.evidence_id()
    con.execute(
        "INSERT OR REPLACE INTO analysis.poi_closure_evidence "
        "(evidence_id, poi_id, location_key, cluster_id, verdict, source, source_name, "
        " domain_class, url, evidence_date, dated_by, retrieved_at, query, reason, "
        " successor_name, raw, run_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [eid, row.poi_id, row.location_key, row.cluster_id, row.verdict, row.source,
         row.source_name, row.domain_class, row.url, row.evidence_date, row.dated_by,
         row.retrieved_at, row.query, row.reason, row.successor_name,
         _to_json(row.raw), row.run_id])
    return eid


def _to_json(raw):
    if raw is None:
        return None
    import json
    return json.dumps(raw)


# ===========================================================================
# THE BASE PREDICATE'S DATE TWIN
# ===========================================================================
# For each branch of poi_presence.poi_status()/poi_is_open(), which date is
# THAT verdict's own evidence date -- i.e. what "newer than the base" means.
# Branch -> date, in the order poi_status() tests them:
#   ledger closed_on            -> the ledger's closed_on itself
#   published-closed basis      -> last_inspection_date (the DCWP/DOHMH action's date)
#   licence expired             -> the expiry date itself
#   absence-derived / inactive / defaulted-active / else -> unknown, no date
#   open via a valid (unexpired) licence -> observed_on (when we last pulled it,
#       not the FUTURE expiry -- a future date would beat any real evidence)
#   open via a fresh inspection  -> last_inspection_date
#   open via a roster            -> observed_on
def poi_status_date(attrs: dict | None, *, closed_on=None, observed_on=None,
                    today: dt.date | None = None,
                    max_age_days: int = pp.OPEN_EVIDENCE_MAX_AGE_DAYS) -> dt.date | None:
    """The date twin of `poi_presence.poi_status()`. See the section header."""
    today = today or dt.date.today()

    cd = _parse_date(closed_on)
    if cd is not None:
        return cd

    a = attrs or {}
    basis = a.get("active_basis")
    basis = str(basis) if basis is not None else None

    if basis in pp.PUBLISHED_CLOSED_BASES:
        return _parse_date(a.get("last_inspection_date"))

    expiry = None
    for key in pp.EXPIRY_ATTR_KEYS:
        expiry = _parse_date(a.get(key))
        if expiry is not None:
            break
    if expiry is not None and expiry < today:
        return expiry

    if basis and basis.startswith(pp.ABSENCE_DERIVED_BASIS_PREFIXES):
        return None

    active = a.get("active")
    is_active = (active is True or str(active).lower() == "true")
    if not is_active:
        return None

    if basis in pp.DEFAULTED_ACTIVE_BASES:
        return None

    if expiry is not None:                        # and, by the branch above, >= today
        return _parse_date(observed_on)

    if basis and (basis.startswith(pp.INSPECTION_BASIS_PREFIXES)
                  or basis in pp.INSPECTION_BASES_EXTRA):
        seen = _parse_date(a.get("last_inspection_date"))
        if seen is not None and (today - seen).days <= max_age_days:
            return seen
        return None

    if basis in pp.ROSTER_ACTIVE_BASES:
        seen = _parse_date(observed_on)
        if seen is not None and (today - seen).days <= max_age_days:
            return seen
        return None

    return None


def poi_status_date_sql(poi: str = "p", closed_on: str = "NULL",
                        today: str = "current_date",
                        max_age_days: int = pp.OPEN_EVIDENCE_MAX_AGE_DAYS) -> str:
    """SQL twin of `poi_status_date()`. Same branch order and semantics as
    `poi_presence.poi_is_open()`; see that function and the section header."""
    a = f"json_extract_string({poi}.attrs, '$.active')"
    b = f"json_extract_string({poi}.attrs, '$.active_basis')"
    insp = f"try_cast(json_extract_string({poi}.attrs, '$.last_inspection_date') AS DATE)"
    exp = "coalesce(" + ", ".join(
        f"try_cast(json_extract_string({poi}.attrs, '$.{k}') AS DATE)"
        for k in pp.EXPIRY_ATTR_KEYS) + ")"
    obs = f"try_cast({poi}.observed_on AS DATE)"
    absence = " OR ".join(f"{b} LIKE '{prefix}%'" for prefix in pp.ABSENCE_DERIVED_BASIS_PREFIXES)
    insp_pred = "(" + " OR ".join(
        [f"{b} LIKE '{prefix}%'" for prefix in pp.INSPECTION_BASIS_PREFIXES]
        + [f"{b} IN ({pp._sql_list(pp.INSPECTION_BASES_EXTRA)})"]) + ")"
    return f"""CASE
    WHEN {closed_on} IS NOT NULL THEN {closed_on}
    WHEN {b} IN ({pp._sql_list(pp.PUBLISHED_CLOSED_BASES)}) THEN {insp}
    WHEN {exp} IS NOT NULL AND {exp} < {today} THEN {exp}
    WHEN {absence} THEN NULL
    WHEN NOT coalesce(lower({a}) = 'true', FALSE) THEN NULL
    WHEN {b} IN ({pp._sql_list(pp.DEFAULTED_ACTIVE_BASES)}) THEN NULL
    WHEN {exp} IS NOT NULL THEN {obs}
    WHEN {insp_pred} THEN
        CASE WHEN {insp} IS NOT NULL
              AND date_diff('day', {insp}, {today}) <= {max_age_days}
             THEN {insp} ELSE NULL END
    WHEN {b} IN ({pp._sql_list(pp.ROSTER_ACTIVE_BASES)}) THEN
        CASE WHEN {obs} IS NOT NULL
              AND date_diff('day', {obs}, {today}) <= {max_age_days}
             THEN {obs} ELSE NULL END
    ELSE NULL
END"""


# ===========================================================================
# THE PRECEDENCE RULE
# ===========================================================================
def resolve(base: tuple[str, str], base_date: dt.date | None,
           ev: EvidenceRow | None) -> tuple[str, str]:
    """(status, basis) after applying at most one evidence row on top of the
    base (status, basis) from `poi_presence.poi_status()`.

    `base_date` is `poi_status_date()` evaluated over the SAME attrs that
    produced `base` -- the date the base verdict is "as of". See the module
    docstring for the precedence rule this implements; `wrap_status_sql()` /
    `wrap_basis_sql()` below must agree with this row for row.
    """
    status, basis = base
    if ev is None or ev.verdict is None:
        return base
    applies = (status == STATUS_UNKNOWN) or (
        ev.dated_by != DATED_NONE
        and (base_date is None or ev.evidence_date > base_date))
    if not applies:
        return base
    return ev.verdict, ev.basis()


def evidence_cte_sql(name: str = "ev") -> str:
    """The newest verdict-carrying evidence row per `poi_id`, as a CTE body
    (no leading `WITH`). Ties broken 'closed' first, then most recently
    retrieved -- an evidence source rarely disagrees with itself on one day,
    but a closed verdict is the conservative one to surface if it ever does."""
    return (f"{name} AS (\n"
            "    SELECT *\n"
            "    FROM analysis.poi_closure_evidence\n"
            "    WHERE verdict IS NOT NULL\n"
            "    QUALIFY row_number() OVER (\n"
            "        PARTITION BY poi_id\n"
            "        ORDER BY evidence_date DESC, retrieved_at DESC, (verdict = 'closed') DESC\n"
            "    ) = 1\n"
            ")")


#: The SQL rendering of `EvidenceRow.basis()`. A CASE over `ev.source` rather
#: than a per-source call so `wrap_basis_sql` stays one expression; kept next
#: to `EvidenceRow.basis()` because the two MUST agree
#: (tests/test_poi_evidence.py checks it) and a hand-edit here that drifts
#: from the Python string format is exactly the two-copies failure this
#: module's docstring warns about.
def _basis_sql(ev: str = "e") -> str:
    return (f"CASE WHEN {ev}.source = 'web' THEN "
            f"'web_evidence:' || {ev}.verdict || ':' || coalesce({ev}.domain_class, 'unknown') "
            f"|| ':' || strftime({ev}.evidence_date, '%Y-%m-%d') || ':' || {ev}.url "
            f"ELSE 'google_places:' || {ev}.verdict || ':' "
            f"|| strftime({ev}.evidence_date, '%Y-%m-%d') || ':' || {ev}.url END")


def _applies_sql(status_sql: str, date_sql: str, ev: str) -> str:
    return (f"({ev}.verdict IS NOT NULL AND (\n"
            f"        ({status_sql}) = 'unknown'\n"
            f"        OR ({ev}.dated_by <> 'none' AND (\n"
            f"            ({date_sql}) IS NULL OR {ev}.evidence_date > ({date_sql})))\n"
            f"    ))")


def wrap_status_sql(status_sql: str, date_sql: str, ev: str = "e") -> str:
    """`status_sql` (e.g. `poi_presence.poi_is_open(...)`) with the evidence
    override applied on top, per `resolve()`. `date_sql` is
    `poi_status_date_sql(...)` over the SAME `poi`/`closed_on` arguments."""
    applies = _applies_sql(status_sql, date_sql, ev)
    return f"CASE WHEN {applies} THEN {ev}.verdict ELSE ({status_sql}) END"


def wrap_basis_sql(status_sql: str, basis_sql: str, date_sql: str, ev: str = "e") -> str:
    """`basis_sql` (e.g. `poi_presence.poi_status_basis(...)`) with the
    evidence override applied on top, per `resolve()`."""
    applies = _applies_sql(status_sql, date_sql, ev)
    return f"CASE WHEN {applies} THEN {_basis_sql(ev)} ELSE ({basis_sql}) END"
