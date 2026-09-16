"""The FIRST-SEEN LEDGER (`analysis.poi_presence`) -- Loci's own observation
history for every deduplicated storefront location.

Owner's ask (2026-09-13): "make sure moving forward we have dates on which
month data was first seen for storefronts." The point is that this must NOT
depend on a source publishing an open date. Most do not: of the nine POI
feeds, four carry a usable first-seen and five carry none at all, which is why
`chains.brand_snapshot.locations_new_12m` has always been a floor over a 60%
subset. A ledger we write ourselves, every month, is the measure that needs no
source's cooperation.

sql/018_poi_presence.sql carries the schema rationale: why this is a new table
under the D61 inventory rule, why `location_key` is not `cluster_id`, what the
`first_seen_kind` values mean, and the five caveats the database cannot
enforce. Read it before changing anything here.

A FOURTH KIND, 'gov_filing', was added by sql/020_storefront_pipeline.sql. It
is written by model/storefront_pipeline.apply_gov_filing, never by `snapshot`:
a government filing that dated an opening earlier than any POI source could,
or dated a LEFT-CENSORED row at all. It carries a real `first_seen_src_date`,
so every invariant that used to test `kind = 'source_date'` now tests
membership of `DATED_KINDS`. 20,345 rows on the 2026-09-13 build, 17,574 of
them previously censored.

WHAT THIS MODULE GUARANTEES
---------------------------
1. IDEMPOTENCE. Re-running a month never moves `first_seen_month` and never
   double-counts `n_months_seen`: the upsert increments only when the
   snapshot's month is STRICTLY NEWER than the row's `last_seen_month`.
2. NO SILENT MIS-JOIN. `cluster_id` is not stable across dedup re-runs (see
   sql/018), so identity is carried by a content hash first and a
   name+distance link second, and every ledger row whose `last_seen_month` is
   behind the newest snapshot has its `cluster_id_latest` NULLed. A stale join
   returns nothing rather than the wrong storefront.
3. THE LINK IS NEVER LOOSER THAN THE DEDUP. It reuses
   `score.dedup.norm_tokens` / `names_match` / `MATCH_METERS`, the same rule
   that formed the cluster in the first place. Widening it here would fuse
   distinct storefronts and manufacture fake retail gaps downstream -- the
   failure score/dedup.py's own comments are about.
4. FAIL LOUD. `snapshot` raises if the warehouse has no deduped locations
   rather than writing an empty month, and refuses an out-of-order month
   without `force=True`.

`FIRST_SEEN_FIELDS` lives here, NOT in chains/detect.py, because two copies of
"which fields may be read as an opening date" is how `last_inspection_date`
eventually gets read as one. detect.py imports it from here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import pathlib
from dataclasses import dataclass, field

import h3

from loci.model.supply_asof import ASOF_SQL, default_today
from loci.score.dedup import BLOCK_RES, MATCH_METERS, haversine_m, names_match, norm_tokens

SQL_018 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "018_poi_presence.sql"

#: The month the ledger began. Documented, asserted by `check`, and NOT used to
#: decide censoring -- that is decided by "was the ledger empty before this
#: snapshot", which survives the constant drifting out of date.
LEDGER_START_MONTH = "2026-09"

#: The first month in which "new" is a real observation rather than an artefact
#: of the ledger starting. Nothing before this may be reported as an opening.
FIRST_HONEST_MONTH = "2026-10"

#: 'gov_filing' is written by model/storefront_pipeline.apply_gov_filing, NOT
#: by `snapshot` -- a government filing dated the opening earlier than any POI
#: source could, or dated a left-censored row at all. It carries a real
#: `first_seen_src_date` exactly as 'source_date' does, which is why the two
#: appear together in every invariant below and in the sql/020 reporting view.
#: `snapshot` never MINTS it and never overwrites it except by the same
#: one-way upgrade that already applies: a source date at or before the month
#: already held.
KINDS = ("source_date", "observed", "backfill_censored", "gov_filing")

#: The kinds that carry a DATE rather than a month of observation. Anything
#: reading `first_seen_src_date` must branch on this set, never on
#: `== 'source_date'`.
DATED_KINDS = frozenset({"source_date", "gov_filing"})

#: Decimal places for the coordinate component of the minted key. 4 dp is
#: ~11 m N-S and ~8.5 m E-W at NYC's latitude -- finer than dedup's 40 m match
#: radius, so two clusters the dedup deliberately kept apart will nearly always
#: round apart too. It is a GRID, though, so a cluster whose canonical member
#: changes can cross a boundary and hash differently; that is precisely what
#: the name+distance link pass exists to absorb, and why the hash is never the
#: only route to identity.
KEY_PRECISION = 4

#: Per-location first-seen candidates from the SOURCE, in no particular order:
#: the minimum over all of them wins. Each entry is (SQL expression over an
#: aliased `staging.poi` row `p`, label). `try_strptime` returns NULL instead
#: of raising on a format mismatch, which keeps one malformed attrs blob from
#: failing the whole run.
#:
#: `attrs.last_inspection_date` IS DELIBERATELY ABSENT AND MUST STAY ABSENT.
#: It is a LAST-seen date. Reading it as a first-seen would date every
#: long-established restaurant to its most recent inspection and label the
#: whole food tier newly opened. tests/test_poi_presence.py and
#: tests/test_chains_detect.py both assert it.
FIRST_SEEN_FIELDS: tuple[tuple[str, str], ...] = (
    ("p.opened_on", "opened_on"),
    ("try_cast(try_strptime(json_extract_string(p.attrs, '$.license_issue_date'),"
     " '%m/%d/%Y') AS DATE)", "license_issue_date"),
    ("try_cast(try_strptime(json_extract_string(p.attrs, '$.enrollment_begin_date'),"
     " '%Y-%m-%dT%H:%M:%S.%g') AS DATE)", "enrollment_begin_date"),
)



# ===========================================================================
# THE OPEN/CLOSED/UNKNOWN PREDICATE (owner ask 2026-09-14, GTM-153)
# ===========================================================================
# "Any time we have 2 businesses in the same address, we should do a check if
# one of them closed down."  GTM-153 is one cafe counted TWICE in the revenue
# supply pool: D36/GTM-121 established that score/dedup.py merges only
# NAME-MATCHED points within MATCH_METERS, so a departed tenant and its
# successor sharing one building coordinate are two DIFFERENT names and both
# survive as canonical supply.  Resolving such a pair needs one thing the
# warehouse never had: a single, documented answer to "is this POI still
# open".  That answer is here, and ONLY here, so that supply, retrodiction,
# the recommendations ledger and the forecast cannot each invent their own.
#
# THREE STATES, NEVER TWO.  'open' | 'closed' | 'unknown'.  Collapsing
# 'unknown' into 'closed' would delete supply on the strength of nothing and
# manufacture exactly the fake retail gaps this project exists to avoid;
# collapsing it into 'open' would keep the GTM-153 ghost.  Most of the POI
# universe is legitimately 'unknown' -- Overture, OSM, Foursquare's open cache
# and USDA SNAP publish no status field at all.
#
# ------------------------------------------------------------------ D79
# ABSENCE FROM A SNAPSHOT IS NEVER A CLOSURE.  Only a value the SOURCE
# PUBLISHED counts as evidence.  Two consequences that are easy to get wrong
# and are therefore spelled out:
#
#  (a) A DOHMH record that is ABSENT from the current pull is NOT a closure.
#      DOHMH publishes active establishments only, so "it stopped appearing"
#      is indistinguishable from a source outage, a geocode shift or a rename.
#      Only a published status/expiry value in `attrs` is evidence here.
#      For the same reason `attrs.last_inspection_date` is read ONLY as a
#      freshness stamp on an OPEN verdict.  It is a LAST-seen date and must
#      never be read as a first-seen date -- see FIRST_SEEN_FIELDS above,
#      tests/test_poi_presence.py and tests/test_chains_detect.py.
#
#  (b) DOHMH `active=false` with `active_basis LIKE 'stale_%'` is NOT a
#      closure either, and this predicate returns 'unknown' for it.  That
#      verdict is derived from the ABSENCE of a recent inspection (dohmh.py's
#      own caveat: "'not inspected in 24 months' is a proxy for 'closed', not
#      an observation of closure"), which is precisely what D79 forbids as
#      evidence.  It remains visible in the basis string so a co-located pair
#      split stale-vs-fresh can still be COUNTED (`loci colocation` reports
#      it) without being ACTED on.
#
# THIS PREDICATE NEVER DELETES OR MUTATES A LEDGER ROW.  A closed location
# stays in analysis.poi_presence / analysis.poi_first_seen with its
# closed_on / closed_src intact -- that is the closure ledger's whole point,
# and survival analysis needs those rows.  Exclusion happens ONLY in the
# supply set (score/supply.canonical_poi_sql), downstream of here.
#
# ------------------------------------------- WHAT EACH SOURCE PUBLISHES
# Keys are `staging.poi.attrs` unless stated.  Verified against the 2026-09-14
# warehouse by `SELECT source_id, unnest(json_keys(attrs)) ... GROUP BY`.
#
#  foursquare_os_places   the LEDGER's closed_on/closed_src (sql/027), from the
#                         source-published `date_closed`.  Read via the VIEW
#                         analysis.poi_first_seen, never the base table.
#                         -> CLOSED.  (The open cache itself carries no status:
#                         `attrs` is {labels, refreshed} only.)
#  nyc_dohmh_restaurants  active, active_basis, last_inspection_date,
#                         closed_at_last_inspection.
#                         basis 'closed_at_last_inspection' -> CLOSED (a
#                         published DOHMH action).  basis 'inspected_<n>d_ago'
#                         + a last_inspection_date inside the window -> OPEN.
#                         basis 'stale_<n>d' -> UNKNOWN (see (b)).
#                         basis 'never_inspected' -> UNKNOWN: active=true there
#                         is a DEFAULT, not a finding (sql/003's own warning).
#  nyc_dcwp_inspections   active, active_basis, latest_status,
#                         last_inspection_date.  basis 'out_of_business',
#                         'unable_to_locate', 'no_evidence_of_activity'
#                         -> CLOSED (DCWP publishes the inspector's verdict).
#                         'inspected_*' / 'dead_marker_overridden_same_day'
#                         + fresh last_inspection_date -> OPEN.
#                         'no_status' -> UNKNOWN.
#  nys_sla_liquor_licenses      expires (ISO date), active, active_basis.
#  nys_dos_appearance_enhancement  license_expiration_date (ISO date).
#                         expiry < today -> CLOSED (licence lapsed);
#                         expiry >= today -> OPEN (the expiry IS an as-of
#                         statement, so no extra freshness test).
#                         'no_expiration_date' -> UNKNOWN.
#  nys_medicaid_pharmacies      basis 'published_active_medicaid_ffs_roster'
#  nyc_dohmh_childcare          basis 'published_active_roster'
#                         The publisher's file IS the active roster, so
#                         presence is the observation -> OPEN while the row's
#                         `observed_on` is inside the window.  These two can
#                         NEVER say CLOSED: their only closure signal would be
#                         disappearance from the roster, which D79 forbids.
#  overture_places, osm_overpass, usda_snap_retailers, foursquare_os_places
#                         no status field -> always UNKNOWN.
#
# CAVEATS THE DATABASE CANNOT ENFORCE
#  1. THE EXPIRY BRANCH FIRES ON LICENCES THAT LAPSED SINCE THE PULL, and only
#     those.  Both nys_sla and nys_dos fetch an ACTIVE-ONLY file
#     (nys_dos.assert_active_only pins it), so no row is ingested already
#     expired and `active_basis` is 'valid_to_<date>' on every one of them.
#     The predicate therefore reads the EXPIRY DATE itself rather than the
#     ingest-time verdict: 30 canonical DOS rows on the 2026-09-14 build carry
#     'valid_to_<a past date>' -- the licence ran out after the extract, and
#     that is a published closure the moment it does.  Reading `active` alone
#     would have missed every one of them.
#  2. A DOHMH regulatory closure is usually TEMPORARY (a health closure, often
#     re-opened days later) -- dohmh.py says so explicitly.  102 rows carry it.
#     It is read as CLOSED because it is a published, dated, source-issued
#     statement that the establishment was not trading; the direction of the
#     error is a small over-count of closures, which for the supply gate is
#     the conservative direction ONLY if you believe the successor is present.
#     If a future run finds re-opened establishments being gated out, the fix
#     is to read the re-open action, not to widen the staleness window.
#  3. FRESHNESS IS A WINDOW, NOT A FACT.  OPEN_EVIDENCE_MAX_AGE_DAYS is the
#     same 24 months dohmh.py derived as ~1.4x the p90 inter-inspection gap.
#     A POI whose only evidence is older is 'unknown', not 'closed'.
#  4. "TODAY" IS A PINNED DATE, NOT THE WALL CLOCK (owner ruling 2026-09-16).
#     Two of the branches below are functions of the current date -- the
#     licence-expiry test and the two freshness windows -- so a `current_date`
#     here made the verdict, the supply set and `score/supply.supply_hash`
#     change at every midnight with no write to the warehouse.  They now read
#     `model/supply_asof.ASOF_SQL`, a scalar subquery over the one-row table
#     `analysis.supply_asof`, and the Python twin reads the same date through
#     `supply_asof.default_today()`.  Advancing that date is a NAMED,
#     ANNOUNCED step (`loci supply-asof advance`); see model/supply_asof.py
#     for the measured cost of one day (12 POIs, 9 of them leaving supply, on
#     the 2026-09-15 -> 2026-09-16 roll).

#: How old a source's own "still trading" evidence may be and still support an
#: OPEN verdict.  Deliberately the SAME number as dohmh.STALE_DAYS (24 months,
#: ~1.4x the empirical p90 inter-inspection gap) so that a DOHMH record cannot
#: be 'open' here and 'stale' there.  Imported rather than re-derived would be
#: a circular import (sources/ imports nothing from model/, but model/ importing
#: a city adapter would bind this city-agnostic predicate to NYC), so it is
#: restated and tests/test_poi_colocation.py asserts the two agree.
OPEN_EVIDENCE_MAX_AGE_DAYS = 731

#: `active_basis` values that are a SOURCE-PUBLISHED statement of NOT TRADING.
#: Membership here is the ONLY way a status field can produce 'closed'; a basis
#: not listed can at most produce 'unknown'.  Every one of these is a value the
#: publisher wrote, never something Loci inferred from a row's absence (D79).
PUBLISHED_CLOSED_BASES = frozenset({
    "out_of_business",              # nyc_dcwp_inspections -- DCWP's own verdict
    "unable_to_locate",             # nyc_dcwp_inspections
    "no_evidence_of_activity",      # nyc_dcwp_inspections
    "closed_at_last_inspection",    # nyc_dohmh_restaurants -- see caveat 2
})

#: `active_basis` values that are an INFERENCE FROM ABSENCE and therefore may
#: never produce 'closed' (D79).  Matched as a PREFIX because the DOHMH basis
#: carries the age: 'stale_1043d'.
ABSENCE_DERIVED_BASIS_PREFIXES = ("stale_",)

#: `active_basis` values that are a DEFAULT the adapter applied when it had no
#: evidence either way.  active=true on these is not a finding, so they yield
#: 'unknown' -- reading a default as a finding is the mistake sql/003's
#: `active_testable` column was added to make visible.
DEFAULTED_ACTIVE_BASES = frozenset({
    "never_inspected",          # nyc_dohmh_restaurants: permitted, not yet inspected
    "no_status",                # nyc_dcwp_inspections: no inspection outcome recorded
    "no_expiration_date",       # nys_sla / nys_dos: licence with no expiry published
})

#: `active_basis` values whose freshness stamp is `attrs.last_inspection_date`.
#: Prefix-matched ('inspected_412d_ago', 'inspected_pass', ...) plus the one
#: DCWP basis that does not start with the prefix.
INSPECTION_BASIS_PREFIXES = ("inspected_", "inspected")
INSPECTION_BASES_EXTRA = frozenset({"dead_marker_overridden_same_day"})

#: `active_basis` values whose freshness stamp is the ROW's `observed_on`,
#: because for these sources presence in the publisher's file IS the
#: observation.  They can never say 'closed' (D79).
ROSTER_ACTIVE_BASES = frozenset({
    "published_active_roster",                  # nyc_dohmh_childcare
    "published_active_medicaid_ffs_roster",     # nys_medicaid_pharmacies
})

#: `attrs` keys carrying a licence expiry, in the order they are coalesced.
EXPIRY_ATTR_KEYS = ("expires", "license_expiration_date")

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_UNKNOWN = "unknown"
STATUSES = (STATUS_OPEN, STATUS_CLOSED, STATUS_UNKNOWN)


def poi_status(attrs: dict | None, *,
               source_id: str | None = None,
               closed_on=None,
               observed_on=None,
               today: dt.date | None = None,
               max_age_days: int = OPEN_EVIDENCE_MAX_AGE_DAYS,
               ) -> tuple[str, str]:
    """(status, basis) for ONE POI, in pure Python. See the section header.

    `attrs` is the decoded `staging.poi.attrs`; `closed_on` is the LEDGER's
    closure date, read from the VIEW `analysis.poi_first_seen` (never the base
    table) so the D79 rule and the closure-precedence rule in sql/027 are
    applied exactly once, upstream. `observed_on` is the POI row's own
    observation date, used only as the freshness stamp for roster sources.

    This is the REFERENCE implementation; `poi_is_open()` emits the same rule
    as SQL and tests/test_poi_colocation.py runs both over the same fixture
    and asserts they agree row for row. Two copies of a rule is how a rule
    drifts, so they are tested as one.
    """
    today = today or default_today()
    src = source_id or "?"

    def _date(v):
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

    if _date(closed_on) is not None:
        return STATUS_CLOSED, f"ledger:closed_on_{_date(closed_on).isoformat()}"

    a = attrs or {}
    basis = a.get("active_basis")
    basis = str(basis) if basis is not None else None

    if basis in PUBLISHED_CLOSED_BASES:
        return STATUS_CLOSED, f"{src}:{basis}"

    expiry = None
    for key in EXPIRY_ATTR_KEYS:
        expiry = _date(a.get(key))
        if expiry is not None:
            break
    if expiry is not None and expiry < today:
        return STATUS_CLOSED, f"{src}:expired_{expiry.isoformat()}"

    if basis and basis.startswith(ABSENCE_DERIVED_BASIS_PREFIXES):
        # D79: derived from the absence of a recent inspection, not published.
        return STATUS_UNKNOWN, f"{src}:{basis}:absence_derived_not_a_closure"

    active = a.get("active")
    is_active = (active is True or str(active).lower() == "true")
    if not is_active:
        return STATUS_UNKNOWN, (f"{src}:{basis}" if basis else f"{src}:no_status_field")

    if basis in DEFAULTED_ACTIVE_BASES:
        return STATUS_UNKNOWN, f"{src}:{basis}:default_not_evidence"

    if expiry is not None:                       # and, by the branch above, >= today
        return STATUS_OPEN, f"{src}:valid_to_{expiry.isoformat()}"

    if basis and (basis.startswith(INSPECTION_BASIS_PREFIXES)
                  or basis in INSPECTION_BASES_EXTRA):
        seen = _date(a.get("last_inspection_date"))
        if seen is not None and (today - seen).days <= max_age_days:
            return STATUS_OPEN, f"{src}:{basis}"
        return STATUS_UNKNOWN, f"{src}:{basis}:evidence_older_than_{max_age_days}d"

    if basis in ROSTER_ACTIVE_BASES:
        seen = _date(observed_on)
        if seen is not None and (today - seen).days <= max_age_days:
            return STATUS_OPEN, f"{src}:{basis}"
        return STATUS_UNKNOWN, f"{src}:{basis}:evidence_older_than_{max_age_days}d"

    return STATUS_UNKNOWN, (f"{src}:{basis}" if basis else f"{src}:no_status_field")


def _sql_list(values) -> str:
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in sorted(values))


def poi_is_open(poi: str = "p", closed_on: str = "NULL",
                today: str = ASOF_SQL,
                max_age_days: int = OPEN_EVIDENCE_MAX_AGE_DAYS) -> str:
    """THE predicate, as a SQL CASE expression yielding 'open'/'closed'/'unknown'.

    It is named for the question it answers, but it is TRI-STATE on purpose --
    compare it with `= 'closed'` or `<> 'closed'`, never as a boolean, and
    never write `NOT poi_is_open(...)`.

    `poi` is the alias of a `staging.poi` row (needs `.attrs`, `.observed_on`,
    `.source_id`); `closed_on` is a SQL expression for the ledger's closure
    date -- pass `'f.closed_on'` when joined to the VIEW analysis.poi_first_seen
    (D79: read closures there, never from the base table). The default `NULL`
    makes the expression usable without the ledger, at the cost of losing the
    Foursquare closures, so callers that can join SHOULD.

    Emits the same rule as `poi_status()` above; see that docstring and the
    section header for the per-source keys and the D79 reasoning.
    """
    a = f"json_extract_string({poi}.attrs, '$.active')"
    b = f"json_extract_string({poi}.attrs, '$.active_basis')"
    insp = f"try_cast(json_extract_string({poi}.attrs, '$.last_inspection_date') AS DATE)"
    exp = "coalesce(" + ", ".join(
        f"try_cast(json_extract_string({poi}.attrs, '$.{k}') AS DATE)"
        for k in EXPIRY_ATTR_KEYS) + ")"
    obs = f"try_cast({poi}.observed_on AS DATE)"
    absence = " OR ".join(f"{b} LIKE '{p}%'" for p in ABSENCE_DERIVED_BASIS_PREFIXES)
    insp_pred = "(" + " OR ".join(
        [f"{b} LIKE '{p}%'" for p in INSPECTION_BASIS_PREFIXES]
        + [f"{b} IN ({_sql_list(INSPECTION_BASES_EXTRA)})"]) + ")"
    return f"""CASE
    WHEN {closed_on} IS NOT NULL THEN 'closed'
    WHEN {b} IN ({_sql_list(PUBLISHED_CLOSED_BASES)}) THEN 'closed'
    WHEN {exp} IS NOT NULL AND {exp} < {today} THEN 'closed'
    WHEN {absence} THEN 'unknown'
    WHEN NOT coalesce(lower({a}) = 'true', FALSE) THEN 'unknown'
    WHEN {b} IN ({_sql_list(DEFAULTED_ACTIVE_BASES)}) THEN 'unknown'
    WHEN {exp} IS NOT NULL THEN 'open'
    WHEN {insp_pred} THEN
        CASE WHEN {insp} IS NOT NULL
              AND date_diff('day', {insp}, {today}) <= {max_age_days}
             THEN 'open' ELSE 'unknown' END
    WHEN {b} IN ({_sql_list(ROSTER_ACTIVE_BASES)}) THEN
        CASE WHEN {obs} IS NOT NULL
              AND date_diff('day', {obs}, {today}) <= {max_age_days}
             THEN 'open' ELSE 'unknown' END
    ELSE 'unknown'
END"""


def poi_status_basis(poi: str = "p", closed_on: str = "NULL",
                     today: str = ASOF_SQL,
                     max_age_days: int = OPEN_EVIDENCE_MAX_AGE_DAYS) -> str:
    """The `basis` string that goes with `poi_is_open()`, as SQL. Provenance:
    every verdict says which source key produced it, so a reader can tell a
    published closure ('nyc_dcwp_inspections:out_of_business') from an
    absence-derived non-verdict ('nyc_dohmh_restaurants:stale_900d:...')."""
    a = f"json_extract_string({poi}.attrs, '$.active')"
    b = f"json_extract_string({poi}.attrs, '$.active_basis')"
    src = f"{poi}.source_id"
    insp = f"try_cast(json_extract_string({poi}.attrs, '$.last_inspection_date') AS DATE)"
    exp = "coalesce(" + ", ".join(
        f"try_cast(json_extract_string({poi}.attrs, '$.{k}') AS DATE)"
        for k in EXPIRY_ATTR_KEYS) + ")"
    obs = f"try_cast({poi}.observed_on AS DATE)"
    absence = " OR ".join(f"{b} LIKE '{p}%'" for p in ABSENCE_DERIVED_BASIS_PREFIXES)
    insp_pred = "(" + " OR ".join(
        [f"{b} LIKE '{p}%'" for p in INSPECTION_BASIS_PREFIXES]
        + [f"{b} IN ({_sql_list(INSPECTION_BASES_EXTRA)})"]) + ")"
    stale = f"{src} || ':' || {b} || ':absence_derived_not_a_closure'"
    return f"""CASE
    WHEN {closed_on} IS NOT NULL
        THEN 'ledger:closed_on_' || strftime({closed_on}, '%Y-%m-%d')
    WHEN {b} IN ({_sql_list(PUBLISHED_CLOSED_BASES)}) THEN {src} || ':' || {b}
    WHEN {exp} IS NOT NULL AND {exp} < {today}
        THEN {src} || ':expired_' || strftime({exp}, '%Y-%m-%d')
    WHEN {absence} THEN {stale}
    WHEN NOT coalesce(lower({a}) = 'true', FALSE)
        THEN {src} || ':' || coalesce({b}, 'no_status_field')
    WHEN {b} IN ({_sql_list(DEFAULTED_ACTIVE_BASES)})
        THEN {src} || ':' || {b} || ':default_not_evidence'
    WHEN {exp} IS NOT NULL THEN {src} || ':valid_to_' || strftime({exp}, '%Y-%m-%d')
    WHEN {insp_pred} THEN
        CASE WHEN {insp} IS NOT NULL
              AND date_diff('day', {insp}, {today}) <= {max_age_days}
             THEN {src} || ':' || {b}
             ELSE {src} || ':' || {b} || ':evidence_older_than_{max_age_days}d' END
    WHEN {b} IN ({_sql_list(ROSTER_ACTIVE_BASES)}) THEN
        CASE WHEN {obs} IS NOT NULL
              AND date_diff('day', {obs}, {today}) <= {max_age_days}
             THEN {src} || ':' || {b}
             ELSE {src} || ':' || {b} || ':evidence_older_than_{max_age_days}d' END
    ELSE {src} || ':' || coalesce({b}, 'no_status_field')
END"""



# --------------------------------------------------------------------------
# CO-LOCATION: "two businesses at the same address" (GTM-153)
# --------------------------------------------------------------------------
#: Decimal places the coordinate is rounded to before grouping. staging.poi has
#: NO address_id and NO bbl -- there is no address key in the contract -- so
#: "same address" has to be expressed geometrically. 5 dp is ~1.1 m N-S and
#: ~0.85 m E-W at NYC's latitude, i.e. an EXACT-COORDINATE match to the
#: precision the feeds publish: DOHMH, SLA, DCWP and the childcare roster all
#: geocode to the BUILDING (a rooftop/parcel centroid), so two tenants of one
#: building land on one identical point rather than on two nearby ones. A
#: looser radius would fuse genuinely distinct storefronts next door to each
#: other -- the failure score/dedup.py's comments are about, and the one that
#: manufactures fake retail gaps.
#:
#: CAVEAT THE DATABASE CANNOT ENFORCE: this is a GRID, not a radius. Two points
#: 0.3 m apart can straddle a cell boundary and NOT group (a false negative,
#: the safe direction); two points 1.4 m apart in the same cell do group. The
#: same trade poi_presence.KEY_PRECISION already makes, one decimal finer.
#: Coordinates are EPSG:4326 by convention -- DuckDB GEOMETRY carries no SRID,
#: and nothing here reprojects, because degrees are what is being rounded.
COORD_DP = 5

#: The four verdicts a co-located group can carry. 'unresolved' is the one that
#: matters: it is a group the published evidence CANNOT split, and it is
#: counted AS-IS in supply by default (see score/supply.COLLAPSE_UNRESOLVED).
RESOLUTIONS = ("one_closed", "all_closed", "both_open", "unresolved")


def _resolution_sql(n_closed: str, n_open: str, n_poi: str) -> str:
    """The resolution CASE, in ONE place, over three count expressions.

    Order is load-bearing: 'all_closed' must be tested before 'one_closed',
    and 'both_open' requires EVERY member to be positively open -- a group of
    one open and one unknown is UNRESOLVED, never 'both_open'. Collapsing
    unknown into open there would quietly re-assert the GTM-153 double count
    as a finding."""
    return (f"CASE WHEN {n_closed} = {n_poi} THEN 'all_closed'"
            f" WHEN {n_closed} > 0 THEN 'one_closed'"
            f" WHEN {n_open} = {n_poi} THEN 'both_open'"
            f" ELSE 'unresolved' END")


def colocation_view_sql(coord_dp: int = COORD_DP, *, evidence: bool = False) -> str:
    """The DDL for analysis.poi_supply_status + analysis.poi_colocation.

    GENERATED, for the same reason model/address_gaps.address_gaps_view_sql
    and model/address_character.create_views are generated: the open/closed
    rule must have ONE definition in the codebase, and a CASE expression
    copy-pasted into a .sql file is a second one waiting to drift.
    sql/029_poi_colocation.sql is the committed RENDERING of this function
    with `evidence=False` (the default) and
    tests/test_poi_colocation.py::test_sql_file_matches_generator fails if the
    two ever disagree -- so `loci colocation --emit-sql > src/loci/sql/029_...`
    is how the file is regenerated, never a hand edit.

    `evidence=True` (D98, GTM-170) layers `model/poi_evidence.py`'s
    precedence rule on top of the base predicate: a row in
    `analysis.poi_closure_evidence` -- a Google Places lookup or a classified
    web hit, from `loci verify-closures` or a report's on-demand check -- can
    override `poi_status`/`poi_status_basis` where it is newer than the base
    verdict's own evidence date (`poi_evidence.poi_status_date_sql`), and
    unconditionally where the base is 'unknown'. `db.init_schema` applies this
    rendering AFTER sql/033_poi_closure_evidence.sql creates that table (the
    021_address_character pattern -- a VIEW's query is bound at CREATE time,
    so it cannot reference a table that does not exist yet); a warehouse with
    033 not yet applied never asks for `evidence=True`. `evidence=False` is
    UNCHANGED byte-for-byte from before this parameter existed -- that is what
    keeps sql/029 and this function's default output identical, so a caller
    that never passes `evidence=` sees no behaviour change.

    Both objects are VIEWS. Nothing is materialised, so neither can go stale
    relative to staging.poi / analysis.poi_dedup / analysis.poi_presence, and
    no base table is added (owner rule: a pivot is a view).
    """
    status = poi_is_open("p", "f.closed_on")
    basis = poi_status_basis("p", "f.closed_on")
    extra_cols = ""
    evidence_cte = ""
    evidence_join = ""
    if evidence:
        # Local import: model/poi_evidence.py imports THIS module (for the
        # base predicate's constants), so a module-level import here would be
        # circular -- the same reason db.init_schema's own hooks import
        # model/address_gaps and model/address_character locally.
        from loci.model import poi_evidence as pe

        date_sql = pe.poi_status_date_sql("p", "f.closed_on")
        raw_status, raw_basis = status, basis
        status = pe.wrap_status_sql(raw_status, date_sql, ev="e")
        basis = pe.wrap_basis_sql(raw_status, raw_basis, date_sql, ev="e")
        evidence_cte = ",\n" + pe.evidence_cte_sql("ev")
        evidence_join = "\n    LEFT JOIN ev e ON e.poi_id = s.poi_id"
        extra_cols = (",\n           e.verdict AS evidence_verdict,"
                      "\n           e.url AS evidence_url,"
                      "\n           e.evidence_date AS evidence_date")
    key = (f"(s.category || '@' || printf('%.{coord_dp}f,%.{coord_dp}f', "
           f"round(ST_X(s.geom), {coord_dp}), round(ST_Y(s.geom), {coord_dp})))")
    res = _resolution_sql("g.n_closed", "g.n_open", "g.n_poi")
    res_agg = _resolution_sql(
        "count(*) FILTER (WHERE poi_status = 'closed')",
        "count(*) FILTER (WHERE poi_status = 'open')", "count(*)")
    return f"""
CREATE OR REPLACE VIEW analysis.poi_supply_status AS
WITH ledger AS (
    -- ONE row per poi_id. analysis.poi_first_seen is the D79 surface for
    -- closures (never the base table); two ledger rows could in principle
    -- point at one poi_id_latest, and a fan-out here would DOUBLE a supply
    -- row -- the double-count bug this whole exercise exists to remove. min()
    -- also matches sql/027's closure_precedence: the EARLIEST closure wins.
    SELECT poi_id_latest AS poi_id,
           min(closed_on)  AS closed_on,
           min(closed_src) AS closed_src
    FROM analysis.poi_first_seen
    WHERE poi_id_latest IS NOT NULL
    GROUP BY 1
){evidence_cte},
base AS (
    SELECT s.*,
           {key} AS colocation_key,
           f.closed_on  AS ledger_closed_on,
           f.closed_src AS ledger_closed_src,
           {status} AS poi_status,
           {basis} AS poi_status_basis{extra_cols}
    FROM analysis.poi_supply s
    JOIN staging.poi p ON p.poi_id = s.poi_id
    LEFT JOIN ledger f ON f.poi_id = s.poi_id{evidence_join}
),
g AS (
    SELECT colocation_key,
           count(*)                                      AS n_poi,
           count(*) FILTER (WHERE poi_status = 'closed')  AS n_closed,
           count(*) FILTER (WHERE poi_status = 'open')    AS n_open,
           count(*) FILTER (WHERE poi_status = 'unknown') AS n_unknown
    FROM base GROUP BY 1
)
SELECT base.*,
       g.n_poi                                   AS colocation_n,
       {res}                                     AS colocation_resolution,
       (g.n_poi >= 2 AND {res} = 'unresolved')   AS is_colocated_unresolved,
       (base.poi_status = 'closed')              AS is_evidenced_closed
FROM base JOIN g USING (colocation_key);

CREATE OR REPLACE VIEW analysis.poi_colocation AS
SELECT
    colocation_key                                  AS group_key,
    any_value(category)                             AS category,
    round(any_value(ST_X(geom)), {coord_dp})        AS lon,
    round(any_value(ST_Y(geom)), {coord_dp})        AS lat,
    count(*)                                        AS n_poi,
    list(poi_id ORDER BY poi_id)                    AS poi_ids,
    count(*) FILTER (WHERE poi_status = 'closed')   AS n_closed,
    count(*) FILTER (WHERE poi_status = 'open')     AS n_open,
    count(*) FILTER (WHERE poi_status = 'unknown')  AS n_unknown,
    {res_agg}                                       AS resolution,
    to_json(list(struct_pack(
        poi_id     := poi_id,
        source_id  := source_id,
        name       := name,
        status     := poi_status,
        basis      := poi_status_basis,
        closed_on  := ledger_closed_on,
        closed_src := ledger_closed_src
    ) ORDER BY poi_id))                             AS evidence
FROM analysis.poi_supply_status
GROUP BY colocation_key
HAVING count(*) >= 2;
""".strip() + "\n"


@dataclass
class SnapshotResult:
    month: str
    n_locations: int          # deduped locations seen this month
    n_matched_hash: int       # carried forward by an exact key match
    n_matched_link: int       # carried forward by the name+distance link
    n_new: int                # minted this month
    n_gone: int               # ledger rows NOT seen this month
    n_rows_total: int         # ledger size after the write
    kinds: dict = field(default_factory=dict)          # first_seen_kind -> count
    hash_collisions: int = 0  # live clusters sharing one minted key
    upgraded: int = 0         # censored/observed rows a source finally dated
    dry_run: bool = False
    closures: dict = field(default_factory=dict)   # poi_closure.apply_to_ledger report


def ensure_schema(con) -> None:
    """Apply sql/018_poi_presence.sql, then the later files that EXTEND the
    ledger. Idempotent.

    018 re-creates `analysis.poi_first_seen` in its ORIGINAL form, so applying
    it alone silently reverts the reporting view: `first_seen_on` would stop
    covering 'gov_filing' rows (as sql/020 fixed) and `closed_on` would vanish
    off the surface altogether (sql/027). 027 carries the current definition of
    that view -- 020's, plus the closure columns -- and only CREATE ... IF NOT
    EXISTS / ALTER ... IF NOT EXISTS / CREATE OR REPLACE VIEW, so re-applying it
    here costs nothing and keeps the view at the newest migration's shape."""
    from loci.model.supply_asof import ensure_table as _ensure_supply_asof
    _ensure_supply_asof(con)
    con.execute(SQL_018.read_text())
    sql_027 = SQL_018.parent / "027_poi_closure.sql"
    if sql_027.exists():
        con.execute(sql_027.read_text())


def connect_write(path=None, retries: int = 20, wait_s: float = 30.0):
    """Open the warehouse READ-WRITE, waiting out a concurrent writer's lock.

    Mirrors model/recommend.connect_read_only, with a longer patience because
    this one has to WAIT for the other writer to finish rather than merely for
    a window. Never kills anything: another session rebuilding the warehouse is
    the normal state here (D69), and working on a copy would mean the ledger --
    the one table whose whole value is being continuous -- got written
    somewhere that is thrown away."""
    import time

    from loci import db as locidb

    target = path or locidb.DEFAULT_PATH
    last = None
    for i in range(retries):
        try:
            return locidb.connect(target)
        except Exception as exc:            # noqa: BLE001 -- duckdb raises several
            last = exc
            if i < retries - 1:
                time.sleep(wait_s)
    raise RuntimeError(
        f"could not open {target} read-write after {retries} tries "
        f"({retries * wait_s / 60:.0f} min): {last}")


def current_month(today: dt.date | None = None) -> str:
    return (today or dt.date.today()).strftime("%Y-%m")


def validate_month(month: str) -> None:
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"--month must be YYYY-MM, got {month!r}") from exc


def first_seen_sql() -> tuple[str, str]:
    """(least-of-the-candidates, the label of whichever won) as two SQL
    expressions over an aliased `staging.poi` row `p`."""
    exprs = [e for e, _ in FIRST_SEEN_FIELDS]
    value = "least(" + ", ".join(exprs) + ")" if len(exprs) > 1 else exprs[0]
    branches = " ".join(
        f"WHEN {expr} IS NOT NULL AND {expr} = {value} THEN '{label}'"
        for expr, label in FIRST_SEEN_FIELDS)
    return value, f"CASE {branches} END"


def current_locations_sql() -> str:
    """One row per DEDUPLICATED LOCATION as the warehouse stands right now.

    Reads `analysis.poi_dedup` + `staging.poi` directly rather than
    `analysis.poi_supply`: the ledger records every location Loci observed,
    which is deliberately NOT the supply-set question (`in_principled`,
    `is_active`). Dropping a single-source storefront from the ledger would
    make it look like it opened later, when a second feed finally noticed it.
    Going through the base tables also means the ledger does not inherit
    poi_supply's dependency on analysis.category_anchor.

    The source date is the minimum over EVERY cluster member, not just the
    canonical one: a DOHMH-canonical restaurant whose Foursquare member
    carries the only `opened_on` still gets dated."""
    value, label = first_seen_sql()
    return f"""
    WITH member AS (
        SELECT d.cluster_id,
               p.source_id,
               {value} AS src_date,
               {label} AS src_field
        FROM analysis.poi_dedup d
        JOIN staging.poi p ON p.poi_id = d.poi_id
    ),
    dated AS (
        SELECT cluster_id,
               min(src_date)                    AS src_date,
               arg_min(src_field, src_date)     AS src_field,
               count(DISTINCT source_id)        AS n_sources
        FROM member
        GROUP BY 1
    ),
    canon AS (
        SELECT d.cluster_id,
               d.poi_id,
               d.category,
               p.name,
               ST_X(p.geom) AS lon,
               ST_Y(p.geom) AS lat
        FROM analysis.poi_dedup d
        JOIN staging.poi p ON p.poi_id = d.poi_id
        WHERE d.is_canonical
    )
    SELECT c.cluster_id, c.poi_id, c.category, c.name, c.lon, c.lat,
           h.borough,
           t.src_date, t.src_field, t.n_sources
    FROM canon c
    LEFT JOIN dated t ON t.cluster_id = c.cluster_id
    LEFT JOIN analysis.hex h
           ON h.h3_index = h3_latlng_to_cell_string(c.lat, c.lon, 9)
    """


def name_key_of(name) -> str:
    """The link key: `score.dedup.norm_tokens` sorted and joined. Empty for a
    nameless or wholly-generic POI, which means such a location can only ever
    be carried forward by the hash, never by the link. That is intentional --
    `names_match` refuses an empty token set for the same reason."""
    return " ".join(sorted(norm_tokens(name)))


def mint_key(category: str, name_key: str, lon: float, lat: float,
             poi_id: str | None = None) -> str:
    """The content hash. See KEY_PRECISION for why 4 dp, and sql/018 for why a
    hash alone is not identity.

    NAMELESS LOCATIONS ALSO HASH THEIR CANONICAL poi_id, and that clause is
    load-bearing. Measured on the live warehouse (227,548 clusters): every one
    of the 118 clusters that collided on `category | name | lon,lat` had an
    EMPTY `name_key` -- CJK and Arabic shopfront names, which `norm_tokens`
    strips to nothing because it keeps only `[a-z0-9]`, plus all-generic names
    like "Chicken Kitchen" whose every token is a stopword -- typically sitting
    on one fallback geocode. For those rows the hash carries no distinguishing
    content at all, so without this the same key would be minted for genuinely
    different storefronts.

    Disambiguating by a positional suffix instead was tried and is WRONG: the
    suffix depends on which collider is processed first, so the assignment
    changed between runs and the second snapshot minted 63 duplicate rows for
    locations it already held -- caught by `coverage_check`'s
    one-row-per-cluster assertion. `poi_id` is a deterministic function of
    cluster membership (the canonical pick is 100% reproducible under input
    reordering, measured), so hashing it is stable where a suffix is not.

    THE COST, stated plainly: for a nameless cluster the key moves if its
    CANONICAL MEMBER changes -- a feed dropping the winning row re-mints. The
    name+distance link cannot rescue those either, because `names_match`
    refuses an empty token set. So ~0.05% of locations have a weaker identity
    guarantee than the rest, and they are the ones we know least about anyway."""
    payload = (f"{category}|{name_key}|"
               f"{round(float(lon), KEY_PRECISION):.{KEY_PRECISION}f}|"
               f"{round(float(lat), KEY_PRECISION):.{KEY_PRECISION}f}")
    if not name_key:
        payload += f"|{poi_id}"
    return "loc_" + hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()


# ---------------------------------------------------------------------------
# the link
# ---------------------------------------------------------------------------
def link_to_ledger(cur, existing) -> tuple[list[str], dict]:
    """Resolve each current location to a ledger `location_key`.

    `cur` and `existing` are DataFrames. Returns (keys aligned to cur.index,
    stats). Three passes, in decreasing confidence:

      A. exact minted-key match (same category). O(1), and the whole ledger
         takes this path on a month where nothing upstream changed.
      B. name + distance link, H3 res-11 blocked, against ledger rows pass A
         did not claim: same category, `names_match`, within MATCH_METERS,
         nearest wins, one-to-one.
      C. mint.

    One-to-one is enforced by `claimed`: a ledger row can be carried forward by
    at most one current location. Two live clusters that both hash to one key
    (or both link to one row) are NOT merged -- the loser mints its own key and
    the collision is counted and reported. Merging them would be the
    fusing-distinct-storefronts bug."""
    import numpy as np

    n = len(cur)
    minted = [mint_key(c, nk, lon, lat, pid) for c, nk, lon, lat, pid in
              zip(cur["category"], cur["name_key"], cur["lon"], cur["lat"],
                  cur["poi_id"], strict=True)]

    out: list[str | None] = [None] * n
    claimed: set[str] = set()
    stats = {"hash": 0, "link": 0, "new": 0, "hash_collisions": 0}

    if existing is not None and len(existing):
        by_key = dict(zip(existing["location_key"], existing["category"], strict=True))
    else:
        by_key = {}

    # ---- pass A: exact key
    for i, k in enumerate(minted):
        if k in by_key and k not in claimed and by_key[k] == cur["category"].iat[i]:
            out[i] = k
            claimed.add(k)
            stats["hash"] += 1
        elif k in by_key or k in claimed:
            # Someone else already owns this hash. Not an error yet -- pass B
            # may still find this location its own ledger row.
            stats["hash_collisions"] += 1

    # ---- pass B: name + distance, against unclaimed ledger rows
    todo = [i for i in range(n) if out[i] is None]
    if todo and existing is not None and len(existing):
        ex_key = existing["location_key"].to_numpy()
        ex_cat = existing["category"].to_numpy()
        ex_lat = existing["lat"].to_numpy(dtype=float)
        ex_lon = existing["lon"].to_numpy(dtype=float)
        ex_tok = [norm_tokens(s) for s in existing["display_name"]]

        cells: dict[str, list[int]] = {}
        for j in range(len(existing)):
            if ex_key[j] in claimed:
                continue
            if not np.isfinite(ex_lat[j]) or not np.isfinite(ex_lon[j]):
                continue
            cells.setdefault(h3.latlng_to_cell(ex_lat[j], ex_lon[j], BLOCK_RES), []).append(j)

        for i in todo:
            lat_i, lon_i = float(cur["lat"].iat[i]), float(cur["lon"].iat[i])
            tok_i = norm_tokens(cur["name"].iat[i])
            cat_i = cur["category"].iat[i]
            best, best_d = None, MATCH_METERS + 1.0
            for cell in h3.grid_disk(h3.latlng_to_cell(lat_i, lon_i, BLOCK_RES), 1):
                for j in cells.get(cell, ()):
                    if ex_key[j] in claimed or ex_cat[j] != cat_i:
                        continue
                    if not names_match(tok_i, ex_tok[j]):
                        continue
                    d = haversine_m(lat_i, lon_i, ex_lat[j], ex_lon[j])
                    if d <= MATCH_METERS and d < best_d:
                        best, best_d = j, d
            if best is not None:
                out[i] = ex_key[best]
                claimed.add(ex_key[best])
                stats["link"] += 1

    # ---- pass C: mint, disambiguating a collision rather than merging
    #
    # Processed in canonical-poi_id order, NOT row order, so that if the suffix
    # path ever does fire the assignment is at least reproducible. It should
    # not fire: `mint_key` folds the poi_id in for exactly the population that
    # used to collide. A suffix here now means a genuine 64-bit hash collision.
    used = set(by_key) | {k for k in out if k}
    for i in sorted((i for i in range(n) if out[i] is None),
                    key=lambda i: str(cur["poi_id"].iat[i])):
        k = minted[i]
        if k in used:
            # A genuine 64-bit hash collision (mint_key already folds poi_id in
            # for the nameless population that used to collide on content).
            # Suffix, never merge: fusing two live storefronts would delete a
            # real one and manufacture a retail gap where none exists.
            stats["hash_collisions"] += 1
            suffix = 2
            while f"{k}-{suffix}" in used:
                suffix += 1
            k = f"{k}-{suffix}"
        out[i] = k
        used.add(k)
        stats["new"] += 1

    return [str(k) for k in out], stats


# ---------------------------------------------------------------------------
# the snapshot
# ---------------------------------------------------------------------------
#: THE ONE-WAY UPGRADE CONDITION, written once because it appears in four SET
#: clauses and four copies is how three of them eventually drift apart.
#:
#: A snapshot may replace the stored first-seen with a SOURCE date only when
#:   * the row is not already dated by a source, AND
#:   * the incoming date is not LATER than the month already held, AND
#:   * where a date is already held (a 'gov_filing' row, written by
#:     model/storefront_pipeline.apply_gov_filing), the incoming one is
#:     STRICTLY EARLIER.
#:
#: The third clause is what keeps a government filing's actual opening date
#: from being nudged later by a source date that merely falls in the same
#: month. Without it, a 'gov_filing' row dated 2025-03-02 would be overwritten
#: by a licence date of 2025-03-28 -- a later date, presented as an upgrade.
_UPGRADE_SQL = """pp.first_seen_kind <> 'source_date'
             AND excluded.first_seen_src_date IS NOT NULL
             AND strftime(excluded.first_seen_src_date, '%Y-%m') <= pp.first_seen_month
             AND (pp.first_seen_src_date IS NULL
                  OR excluded.first_seen_src_date < pp.first_seen_src_date)"""

#: THE TARGET COLUMN LIST IS EXPLICIT, and that is not style. Without it
#: DuckDB binds `excluded` to EVERY column of the table, so the day sql/027
#: added `closed_on` / `closed_src` the upsert died with "table excluded has 17
#: columns available but 19 columns specified" -- i.e. any later ALTER breaks
#: every snapshot. Naming the seventeen columns the snapshot actually writes
#: leaves the closure columns to `poi_closure.apply_to_ledger`, which owns them.
_UPSERT_TEMPLATE = """
INSERT INTO analysis.poi_presence AS pp
    (location_key, category, name_key, display_name, lon, lat, borough,
     first_seen_month, last_seen_month, first_seen_kind, first_seen_src_date,
     first_seen_src_field, n_months_seen, cluster_id_latest, poi_id_latest,
     ledger_started_month, last_snapshot_at)
SELECT location_key, category, name_key, display_name, lon, lat, borough,
       first_seen_month, last_seen_month, first_seen_kind, first_seen_src_date,
       first_seen_src_field, n_months_seen, cluster_id_latest, poi_id_latest,
       ledger_started_month, last_snapshot_at
FROM _presence_in
ON CONFLICT (location_key) DO UPDATE SET
    category         = excluded.category,
    name_key         = excluded.name_key,
    display_name     = excluded.display_name,
    lon              = excluded.lon,
    lat              = excluded.lat,
    borough          = excluded.borough,
    -- last_seen / n_months move only FORWARD. This is what makes re-running a
    -- month a no-op instead of a double count.
    last_seen_month  = greatest(pp.last_seen_month, excluded.last_seen_month),
    n_months_seen    = pp.n_months_seen
                       + CASE WHEN excluded.last_seen_month > pp.last_seen_month
                              THEN 1 ELSE 0 END,
    cluster_id_latest = excluded.cluster_id_latest,
    poi_id_latest     = excluded.poi_id_latest,
    -- ONE-WAY UPGRADE (_UPGRADE_SQL): a row we could only censor (or only
    -- observe) becomes 'source_date' if a source later publishes a date at or
    -- before the month we already had. Censoring can only ever shrink; it
    -- never reappears, and a later-than-known date is refused rather than
    -- allowed to move first_seen_month forward. `ledger_started_month` is
    -- untouched either way, so when we FIRST HELD the row is never lost.
    first_seen_kind = CASE
        WHEN {UPGRADE}
        THEN 'source_date' ELSE pp.first_seen_kind END,
    first_seen_month = CASE
        WHEN {UPGRADE}
        THEN strftime(excluded.first_seen_src_date, '%Y-%m') ELSE pp.first_seen_month END,
    first_seen_src_date = CASE
        WHEN {UPGRADE}
        THEN excluded.first_seen_src_date ELSE pp.first_seen_src_date END,
    first_seen_src_field = CASE
        WHEN {UPGRADE}
        THEN excluded.first_seen_src_field ELSE pp.first_seen_src_field END,
    last_snapshot_at = excluded.last_snapshot_at
"""

_UPSERT = _UPSERT_TEMPLATE.replace("{UPGRADE}", _UPGRADE_SQL)


def snapshot(con, *, month: str | None = None, dry_run: bool = False,
             today: dt.date | None = None, force: bool = False) -> SnapshotResult:
    """Record one month of observation for every deduplicated location.

    Idempotent: re-running a month changes no `first_seen_month` and no
    `n_months_seen`. `dry_run` computes everything and writes nothing."""
    import pandas as pd

    today = today or dt.date.today()
    month = month or current_month(today)
    validate_month(month)
    ensure_schema(con)
    # THE KEY-DRIFT GUARD (sql/035_poi_key_map.sql). Imported HERE and not at
    # module level because the migration module imports this one. It refuses
    # the snapshot when the dedup's key set has moved away from the ledger's
    # without an applied analysis.poi_key_map: a re-minted key is
    # indistinguishable from a new storefront, and first_seen_month is
    # write-once, so writing one is permanent. `force` bypasses it, exactly as
    # it bypasses the out-of-order-month refusal below.
    from loci.model.poi_key_migration import guard_snapshot
    guard_snapshot(con, month=month, force=force)

    newest = con.execute(
        "SELECT max(last_seen_month) FROM analysis.poi_presence").fetchone()[0]
    if newest and month < newest and not force:
        raise ValueError(
            f"refusing to snapshot {month}: the ledger already holds {newest}. "
            "Out-of-order months do not increment n_months_seen and cannot move "
            "last_seen_month backwards (sql/018 caveat 2). Pass force=True only "
            "if you understand that.")

    cur = con.execute(current_locations_sql()).fetchdf()
    if cur.empty:
        raise RuntimeError(
            "analysis.poi_dedup is empty -- refusing to write an empty month. "
            "Run `loci dedup` first; a silent zero here would mark every "
            "storefront in the city as disappeared.")

    cur["name_key"] = [name_key_of(s) for s in cur["name"]]

    # A source date is usable only if it is a real past date. A future date is
    # a data error, not an opening; taking it would let a location claim it
    # opened after we saw it.
    src = pd.to_datetime(cur["src_date"], errors="coerce").dt.date
    usable = src.notna() & (src <= today) & (src.map(
        lambda d: d.strftime("%Y-%m") if d is not None and d == d else "9999-99") <= month)
    cur["src_date_ok"] = src.where(usable)
    cur["src_field_ok"] = cur["src_field"].where(usable)

    existing = con.execute(
        "SELECT location_key, category, display_name, lon, lat, first_seen_month, "
        "first_seen_kind FROM analysis.poi_presence").fetchdf()
    first_ever = existing.empty

    keys, stats = link_to_ledger(cur, existing)
    cur["location_key"] = keys

    known = set(existing["location_key"]) if not first_ever else set()
    is_new = [k not in known for k in keys]

    # The mint-time kind. An existing row keeps its own (the upsert only ever
    # upgrades it to 'source_date'), so these values matter only for new rows;
    # they are computed for every row because the upsert needs a full frame.
    kinds, fs_month = [], []
    for i in range(len(cur)):
        d = cur["src_date_ok"].iat[i]
        if d is not None and d == d:
            kinds.append("source_date")
            fs_month.append(d.strftime("%Y-%m"))
        elif first_ever:
            kinds.append("backfill_censored")
            fs_month.append(month)
        else:
            kinds.append("observed")
            fs_month.append(month)

    now = dt.datetime.now()
    frame = pd.DataFrame({
        "location_key": cur["location_key"],
        "category": cur["category"],
        "name_key": cur["name_key"],
        "display_name": cur["name"],
        "lon": cur["lon"].astype(float),
        "lat": cur["lat"].astype(float),
        "borough": cur["borough"],
        "first_seen_month": fs_month,
        "last_seen_month": month,
        "first_seen_kind": kinds,
        "first_seen_src_date": cur["src_date_ok"],
        "first_seen_src_field": cur["src_field_ok"],
        "n_months_seen": 1,
        "cluster_id_latest": cur["cluster_id"].astype("int64"),
        "poi_id_latest": cur["poi_id"].astype(str),
        "ledger_started_month": month,
        "last_snapshot_at": now,
    })
    if frame["location_key"].duplicated().any():
        dup = frame.loc[frame["location_key"].duplicated(), "location_key"].tolist()[:5]
        raise RuntimeError(
            f"link_to_ledger produced duplicate location_keys ({dup}) -- that "
            "would fuse distinct storefronts. This is a bug, not a data issue.")

    n_gone = 0 if first_ever else int(
        (~existing["location_key"].isin(set(keys))).sum())

    result = SnapshotResult(
        month=month,
        n_locations=len(cur),
        n_matched_hash=stats["hash"],
        n_matched_link=stats["link"],
        n_new=int(sum(is_new)),
        n_gone=n_gone,
        n_rows_total=len(existing) + int(sum(is_new)),
        kinds={k: int((frame["first_seen_kind"] == k).sum()) for k in KINDS},
        hash_collisions=stats["hash_collisions"],
        dry_run=dry_run,
    )
    if dry_run:
        return result

    # UNDATED = not in DATED_KINDS. Written that way rather than
    # `!= "source_date"` because 'gov_filing' rows ARE dated (by
    # model/storefront_pipeline.apply_gov_filing) and counting them as
    # undated would report a phantom upgrade every month.
    before_censored = 0 if first_ever else int(
        (~existing["first_seen_kind"].isin(DATED_KINDS)).sum())

    con.execute("BEGIN")
    try:
        con.register("_presence_in", frame)
        con.execute(_UPSERT)
        # A stale cluster_id is worse than none: it would silently attach this
        # month's dedup numbering to a location we did not see this month.
        con.execute(
            "UPDATE analysis.poi_presence "
            "SET cluster_id_latest = NULL, poi_id_latest = NULL "
            "WHERE last_seen_month < ?", [month])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_presence_in")

    dated = ", ".join(f"'{k}'" for k in sorted(DATED_KINDS))
    after = con.execute(
        "SELECT count(*), "
        f"count(*) FILTER (WHERE first_seen_kind NOT IN ({dated})) "
        "FROM analysis.poi_presence").fetchone()
    result.n_rows_total = int(after[0])
    result.upgraded = max(0, before_censored - int(after[1])) if not first_ever else 0
    result.kinds = dict(con.execute(
        "SELECT first_seen_kind, count(*) FROM analysis.poi_presence "
        "GROUP BY 1 ORDER BY 1").fetchall())

    # THE OTHER END OF THE SPELL (sql/027). `closed_on` / `closed_src` are
    # re-derived from staging.poi_closure on EVERY snapshot, so a retracted
    # closure disappears instead of being frozen in.
    #
    # THEY ARE NEVER WRITTEN FROM THE ABSENCE OF A ROW IN THIS SNAPSHOT, and
    # that is D79, not a preference: `n_gone` above counts locations that
    # stopped appearing, and a source outage, a geocode shift past 40 m or a
    # rename past the name rule all produce that just as readily as a shutter.
    # Only a source-published `date_closed` closes a location. Imported here
    # rather than at module level because model/poi_closure imports THIS module.
    from loci.model import poi_closure as pc
    try:
        result.closures = pc.apply_to_ledger(con)
    except Exception as exc:        # noqa: BLE001 -- duckdb raises several
        # The closure table is optional: a warehouse that has never run
        # `loci poi-closures ingest` still snapshots. Reported, never silent.
        result.closures = {"error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# the guard
# ---------------------------------------------------------------------------
def coverage_check(con) -> tuple[list[str], dict]:
    """Assert the ledger covers the warehouse. Returns (errors, stats).

    The load-bearing one is (1): after an ingest + snapshot, EVERY current
    deduplicated location must have a ledger row. A location with no row is a
    location whose first-seen we will never be able to state."""
    errors: list[str] = []
    stats: dict = {}

    have = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'analysis' AND table_name = 'poi_presence'").fetchone()[0]
    if not have:
        return (["analysis.poi_presence does not exist -- run `loci poi-snapshot`"],
                stats)

    stats["ledger_rows"] = con.execute(
        "SELECT count(*) FROM analysis.poi_presence").fetchone()[0]
    stats["newest_month"] = con.execute(
        "SELECT max(last_seen_month) FROM analysis.poi_presence").fetchone()[0]
    stats["clusters"] = con.execute(
        "SELECT count(DISTINCT cluster_id) FROM analysis.poi_dedup").fetchone()[0]

    # (1) coverage: every current cluster is claimed by a ledger row that was
    #     seen in the newest month.
    uncovered = con.execute("""
        SELECT count(*) FROM (
            SELECT DISTINCT d.cluster_id FROM analysis.poi_dedup d
            WHERE NOT EXISTS (
                SELECT 1 FROM analysis.poi_presence pp
                WHERE pp.cluster_id_latest = d.cluster_id
                  AND pp.last_seen_month = (SELECT max(last_seen_month)
                                            FROM analysis.poi_presence))
        )""").fetchone()[0]
    stats["uncovered_clusters"] = uncovered
    stats["coverage_pct"] = (
        100.0 * (stats["clusters"] - uncovered) / stats["clusters"]
        if stats["clusters"] else 0.0)
    if uncovered:
        errors.append(
            f"{uncovered} of {stats['clusters']} deduped locations have no ledger "
            f"row in {stats['newest_month']} -- run `loci poi-snapshot` after ingest")

    # (2) one ledger row per live cluster, never two.
    dupes = con.execute(
        "SELECT count(*) FROM (SELECT cluster_id_latest FROM analysis.poi_presence "
        "WHERE cluster_id_latest IS NOT NULL GROUP BY 1 HAVING count(*) > 1)").fetchone()[0]
    if dupes:
        errors.append(f"{dupes} cluster_ids are claimed by more than one ledger row "
                      "-- two histories are fused onto one storefront")

    # (3) the kind invariants.
    holes = ", ".join("?" for _ in KINDS)
    bad_kind = con.execute(
        f"SELECT count(*) FROM analysis.poi_presence WHERE first_seen_kind "
        f"NOT IN ({holes})", list(KINDS)).fetchone()[0]
    if bad_kind:
        errors.append(f"{bad_kind} rows carry an unknown first_seen_kind")

    dated_holes = ", ".join(f"'{k}'" for k in sorted(DATED_KINDS))
    bad_src = con.execute(
        f"SELECT count(*) FROM analysis.poi_presence WHERE "
        f"(first_seen_kind IN ({dated_holes})) <> (first_seen_src_date IS NOT NULL)"
    ).fetchone()[0]
    if bad_src:
        errors.append(f"{bad_src} rows disagree about first_seen_src_date: it must be "
                      f"non-NULL for exactly the {sorted(DATED_KINDS)} rows")

    # A 'gov_filing' row's month must BE its date's month. The writer sets both
    # in one statement; a disagreement means something else wrote one of them.
    bad_gov = con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE "
        "first_seen_kind = 'gov_filing' AND (first_seen_src_date IS NULL "
        "OR strftime(first_seen_src_date, '%Y-%m') <> first_seen_month)"
    ).fetchone()[0]
    if bad_gov:
        errors.append(f"{bad_gov} 'gov_filing' rows have a first_seen_month that is "
                      "not their opening date's month")

    bad_order = con.execute(
        "SELECT count(*) FROM analysis.poi_presence "
        "WHERE first_seen_month > last_seen_month").fetchone()[0]
    if bad_order:
        errors.append(f"{bad_order} rows have first_seen_month after last_seen_month")

    # (4) censoring can only be a backfill-month artefact.
    bad_censor = con.execute(
        "SELECT count(*) FROM analysis.poi_presence WHERE "
        "first_seen_kind = 'backfill_censored' AND ledger_started_month <> ?",
        [con.execute("SELECT min(ledger_started_month) FROM analysis.poi_presence"
                     ).fetchone()[0] or LEDGER_START_MONTH]).fetchone()[0]
    if bad_censor:
        errors.append(f"{bad_censor} left-censored rows were minted after the ledger's "
                      "first month -- censoring is only ever a backfill artefact")

    stats["kinds"] = dict(con.execute(
        "SELECT first_seen_kind, count(*) FROM analysis.poi_presence "
        "GROUP BY 1 ORDER BY 1").fetchall())
    return errors, stats
