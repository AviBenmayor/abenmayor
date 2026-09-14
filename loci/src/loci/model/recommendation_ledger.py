"""The recommendation ledger: what we said, when, and whether the market did it.

Owner's ask (2026-09-14): "start to track recommendations so that we can see how
long it takes for the free market to fill those gaps and if they do it well
(with our proposed solution)."

Two tables (sql/026_recommendation.sql), two questions:

    analysis.recommendation          one row per claim we made, frozen at issue.
    analysis.recommendation_outcome  one row per claim per monthly snapshot.

---------------------------------------------------------------------------
WHY THIS IS NOT A SCORECARD
---------------------------------------------------------------------------
Nobody reads our cards. A gap that fills says the market moved; it does not say
we moved it, and any causal reading of this table is D1's reverse-causality
error wearing a new costume (D87). What the ledger buys is CALIBRATION: of the
places we called thin, how many turned out to be openable, and how fast. That
is answerable, and nothing else in this project answers it.

The rows that grade D are the most valuable rows in the table. The 2026-09-11
Gowanus card said "do not act on this data" for thirteen of fifteen categories.
If those areas fill at the same rate as the ones we graded C, the screen
carries no information — and the ledger is the only instrument that would ever
tell us so. So `--record` records the WHOLE card, verdicts and non-verdicts
alike, and a row is an ASSESSMENT WE DATED, not an instruction to open a store.

---------------------------------------------------------------------------
APPEND-ONLY EXCEPT STATUS
---------------------------------------------------------------------------
DuckDB has no triggers, so the invariant lives here, in `MUTABLE_COLUMNS`, and
`tests/test_recommendation.py` asserts (a) that MUTABLE | IMMUTABLE covers every
column of the table, so a column added later must be classified before the suite
goes green, and (b) that the only UPDATE this module emits names nothing outside
MUTABLE_COLUMNS.

The reason is concrete. The 2026-09-11 Gowanus card graded restaurant **D**; the
2026-09-13 regeneration, after the D81 revenue model shipped, graded it **C**.
Both are true of their own date. A ledger that let the second overwrite the
first would erase the only evidence that the model moved, and every
retrodiction built on it would be circular.

A mistake is WITHDRAWN, never deleted: `status='withdrawn'` plus a
`status_reason`. The D73 laundry lead is in here as exactly that — issued
2026-09-10, withdrawn 2026-09-11 when the supply ratio came back 0.94x (normal,
not thin). A ledger holding only the leads that survived is the survivorship
bias this exercise exists to defeat.

---------------------------------------------------------------------------
THE MATCH: what counts as "the gap filled"
---------------------------------------------------------------------------
For every OPEN recommendation, in the snapshot month:

  1. THE FIRST-SEEN LEDGER (`analysis.poi_first_seen`, sql/018) — a deduped
     location of the SAME loci category whose first-seen date is on or after
     `issued_on` and within `radius_m` of the anchor. match_kind='opened'.
     Left-censored rows carry a NULL first-seen and cannot match, which is
     correct: they existed before we said anything.

  2. THE FILINGS PIPELINE (`analysis.storefront_pipeline`, sql/020) — same
     category, same radius. A row that is OPEN with `opened_on >= issued_on`
     is also an 'opened' match (the ledger has not necessarily observed it
     yet); a row that is NOT open with `entry_date >= issued_on` is
     'in_pipeline', carrying its stage.

  3. Otherwise 'none', and 'none' IS STORED. A month with no row would be
     indistinguishable from a month the job did not run, and the measurement
     is a duration: the months in which nothing happened are the measurement.

The earliest 'opened' match wins and flips the recommendation to 'filled'.
`days_to_fill` is issued_on -> opened_on for an 'opened' match and issued_on ->
entry_date for an 'in_pipeline' one; `quality_json['days_basis']` says which,
because a filing is an intention and conflating the two would report a
build-out that has not started as a gap that closed.

NOTHING AFTER THE SNAPSHOT MONTH IS VISIBLE TO THE CHECK. Every candidate query
is capped at the last day of `--month`, so re-running an old month reproduces
that month's answer rather than today's. That is what makes the DELETE/INSERT
re-run idempotent in the only sense that matters.

THE RADIUS IS A STRAIGHT LINE. Everywhere else in Loci "within reach" is 400 m
NETWORK distance; here there is no persisted anchor->POI pair set to read, and
a network radius from an arbitrary anchor costs a graph load and a Dijkstra for
a job with a handful of anchors. The bias has a known sign — network distance
>= straight-line distance, so the disc strictly CONTAINS the network catchment
— which means the check is over-inclusive and errs toward "the gap filled",
i.e. against us. `distance_m` is stored on every match so a tighter radius can
be re-cut after the fact.

---------------------------------------------------------------------------
"DID THEY DO IT WELL" — THE RUBRIC, AND WHAT IT CANNOT SEE
---------------------------------------------------------------------------
`solution_match_score` is 0..1, the sum of the components below that we could
CONFIRM. It is not a quality rating. It is "how much of what we proposed can be
checked against open data", and open data carries a name, sometimes a cuisine or
a licence class, and a count of sources. It cannot see hours, staffing, price,
fit-out or whether the place is any good.

    category        0.50   REQUIRED. A candidate of another category is not a
                           match at all, so this is earned by every match. It
                           is scored rather than assumed so that a bare
                           category match reads as what it is: half.
    format_hint     0.20   The proposal named an operating format ("24/7
                           staffed laundromat", "hardware with lumber") and a
                           keyword of it appears in the business name, the
                           DOHMH cuisine, the DCWP business category, the DOS
                           licence type, the SNAP store type or the SLA
                           description. UNAVAILABLE when the proposal named no
                           format — never redistributed to the other
                           components, because "we asked for nothing specific"
                           is not evidence that they delivered it.
    corroboration   0.15   More than one source sees the storefront (POI dedup
                           source count, or filing-feed count for a pipeline
                           match). One source is a place that might not exist.
    independent     0.10   The name does not resolve to a brand on the chains
                           watchlist or to a multi-location brand in
                           chains.brand_latest. A chain filling the gap is a
                           real outcome and is NOTED, not penalised to zero —
                           it simply is not the independent operator the cards
                           usually propose.
    still_open      0.05   `model.poi_presence.poi_is_open` (GTM-153) reads
                           'open' for the matched location. UNAVAILABLE when
                           the predicate reads 'unknown' (never scored as a
                           zero -- D79) or in the fill month itself: "open
                           the month it opened" is true by construction and
                           carries no information.

If only the category matches, the score is 0.50 and `quality_json` names every
component that was unavailable and why. NOTHING IS EVER INVENTED: an
unavailable component is recorded as unavailable, never as a zero and never as
a pass. `max_available` is stored beside the score so a 0.50 out of 0.65 is not
read as a 0.50 out of 1.00.

TO EXTEND IT: add an entry to `RUBRIC` with a `weight` and a `score` callable
taking (rec, cand, ctx) and returning (earned | None, evidence). The weights do
not have to sum to 1.0 — `max_available` is computed, not assumed — and
`tests/test_recommendation.py` asserts every component is exercised on a
fixture.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import pathlib
import re

from loci.db import METRES_SQL, SQL_DIR

SQL_026 = SQL_DIR / "026_recommendation.sql"

#: Straight-line default. score/access.THRESHOLDS[5] is the same 400 m, on the
#: walk graph; see the module docstring for why this one is not.
DEFAULT_RADIUS_M = 400.0

STATUSES = ("open", "filled", "withdrawn", "expired")
AREA_KINDS = ("nta", "address", "bbox")

#: THE APPEND-ONLY INVARIANT. The only columns any UPDATE in this project may
#: name on analysis.recommendation. Adding a column to sql/026 without
#: classifying it here fails tests/test_recommendation.py.
MUTABLE_COLUMNS = frozenset({
    "status", "status_reason", "status_changed_on", "status_changed_at",
})
IMMUTABLE_COLUMNS = frozenset({
    "rec_id", "issued_on", "issued_by", "area_kind", "area_id", "area_label",
    "anchor_address_id", "anchor_lon", "anchor_lat", "category",
    "proposed_solution", "format_hint", "grade", "supply_ratio_at_issue",
    "homes_400m_at_issue", "gap_score_at_issue", "evidence_json", "card_hash",
    "created_at",
})

INSERT_COLUMNS = (
    "rec_id", "issued_on", "issued_by", "area_kind", "area_id", "area_label",
    "anchor_address_id", "anchor_lon", "anchor_lat", "category",
    "proposed_solution", "format_hint", "grade", "supply_ratio_at_issue",
    "homes_400m_at_issue", "gap_score_at_issue", "evidence_json", "status",
    "status_reason", "status_changed_on", "status_changed_at", "card_hash",
    "created_at",
)

OUTCOME_COLUMNS = (
    "rec_id", "snapshot_month", "matched_location_key", "matched_pipeline_key",
    "match_kind", "opened_on", "entry_stage", "entry_date", "days_to_fill",
    "distance_m", "same_category", "solution_match_score", "still_open",
    "quality_json", "snapshot_at",
)

#: Words too generic to prove a format. "laundromat" proves something;
#: "store" proves nothing, and letting it through would score every bodega as
#: a match for "hardware store with lumber".
_FORMAT_STOPWORDS = frozenset({
    "a", "an", "and", "the", "with", "for", "of", "or", "shop", "store",
    "business", "small", "local", "new", "service", "services",
    # "independent" is a proposal's word for OWNERSHIP, not for a format -- the
    # `independent` rubric component measures it, and letting it through here
    # would score the same claim twice off a business that happens to be named
    # "Independent Deli".
    "independent",
})


# --------------------------------------------------------------- plumbing

def ensure_schema(con) -> None:
    """Apply sql/026_recommendation.sql. Idempotent, and WRITE-ONLY: DuckDB
    refuses CREATE TABLE IF NOT EXISTS on a read-only connection, so the read
    paths call `require_schema` instead."""
    con.execute(SQL_026.read_text())


def require_schema(con) -> None:
    """Fail with a runnable instruction rather than a DuckDB Catalog Error.

    The read paths (list / report / summary) must work on a READ-ONLY
    connection, which cannot create anything -- so they assert instead of
    creating."""
    try:
        con.execute("SELECT 1 FROM analysis.recommendation LIMIT 1")
    except Exception as exc:                # noqa: BLE001 -- duckdb raises several
        raise RuntimeError(
            "analysis.recommendation does not exist yet. Run "
            "`loci recommendations backfill` (or `loci recommend --record`), "
            "which applies sql/026_recommendation.sql.") from exc


def connect_write(path=None, retries: int = 20, wait_s: float = 30.0):
    """Open the warehouse READ-WRITE, waiting out a concurrent writer's lock.

    Re-exported from model/poi_presence rather than re-implemented: a second
    copy of the retry policy is how the two eventually disagree about how long
    to wait, and a ledger that gives up early is a ledger with a hole in it."""
    from loci.model.poi_presence import connect_write as _cw

    return _cw(path, retries=retries, wait_s=wait_s)


def current_month(today: dt.date | None = None) -> str:
    return (today or dt.date.today()).strftime("%Y-%m")


def validate_month(month: str) -> None:
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"--month must be YYYY-MM, got {month!r}") from exc


def month_end(month: str) -> dt.date:
    """The last day of `month`. The check looks at nothing after it."""
    validate_month(month)
    y, m = (int(p) for p in month.split("-"))
    return (dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1))


def _slug(text: str, n: int = 18) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:n] or "area")


def card_hash(*, issued_by: str, area_kind: str, area_id: str, category: str,
              issued_on: dt.date, grade: str | None,
              supply_ratio_at_issue: float | None,
              proposed_solution: str | None) -> str:
    """The idempotency key: a content hash of the CLAIM.

    Re-running `loci recommend --record` on an unchanged card must add nothing.
    Re-running it after the grade or the ratio MOVED must add a new row,
    because that is a different claim made on a different date — which is
    exactly what happened between the 2026-09-11 and 2026-09-13 Gowanus cards.
    """
    payload = json.dumps({
        "issued_by": issued_by, "area_kind": area_kind, "area_id": area_id,
        "category": category, "issued_on": str(issued_on), "grade": grade,
        "ratio": None if supply_ratio_at_issue is None
                 else round(float(supply_ratio_at_issue), 4),
        "solution": proposed_solution,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def mint_rec_id(*, issued_on: dt.date, area_label: str | None, area_id: str,
                category: str, chash: str) -> str:
    return (f"r-{issued_on:%Y%m%d}-{_slug(area_label or area_id)}-"
            f"{category}-{chash[:6]}")


# ------------------------------------------------------------- the ledger

@dataclasses.dataclass(frozen=True)
class RecordResult:
    n_offered: int
    n_written: int
    n_duplicate: int          # same card_hash already in the ledger
    rec_ids: tuple = ()
    dry_run: bool = False


def _row(*, issued_on, issued_by, area_kind, area_id, area_label, category,
         anchor_address_id=None, anchor_lon=None, anchor_lat=None,
         proposed_solution=None, format_hint=None, grade=None,
         supply_ratio_at_issue=None, homes_400m_at_issue=None,
         gap_score_at_issue=None, evidence=None, status="open",
         status_reason=None, status_changed_on=None, now=None) -> dict:
    if area_kind not in AREA_KINDS:
        raise ValueError(f"area_kind must be one of {AREA_KINDS}, got {area_kind!r}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    if status in ("withdrawn", "expired") and not status_reason:
        raise ValueError(f"status {status!r} needs a reason — a ledger row whose "
                         "retraction has no stated reason teaches nothing")
    if grade is not None and grade not in ("A", "B", "C", "D"):
        raise ValueError(f"grade must be A-D or None, got {grade!r}")
    from loci.categories import CATEGORIES
    if category not in CATEGORIES:
        raise ValueError(f"unknown Loci category {category!r}")

    now = now or dt.datetime.now()
    chash = card_hash(issued_by=issued_by, area_kind=area_kind, area_id=area_id,
                      category=category, issued_on=issued_on, grade=grade,
                      supply_ratio_at_issue=supply_ratio_at_issue,
                      proposed_solution=proposed_solution)
    return {
        "rec_id": mint_rec_id(issued_on=issued_on, area_label=area_label,
                              area_id=area_id, category=category, chash=chash),
        "issued_on": issued_on, "issued_by": issued_by, "area_kind": area_kind,
        "area_id": area_id, "area_label": area_label,
        "anchor_address_id": anchor_address_id,
        "anchor_lon": None if anchor_lon is None else float(anchor_lon),
        "anchor_lat": None if anchor_lat is None else float(anchor_lat),
        "category": category, "proposed_solution": proposed_solution,
        "format_hint": format_hint, "grade": grade,
        "supply_ratio_at_issue": (None if supply_ratio_at_issue is None
                                  else float(supply_ratio_at_issue)),
        "homes_400m_at_issue": (None if homes_400m_at_issue is None
                                else float(homes_400m_at_issue)),
        "gap_score_at_issue": (None if gap_score_at_issue is None
                               else float(gap_score_at_issue)),
        "evidence_json": json.dumps(evidence or {}, sort_keys=True, default=str),
        "status": status, "status_reason": status_reason,
        "status_changed_on": status_changed_on,
        "status_changed_at": now if status != "open" else None,
        "card_hash": chash, "created_at": now,
    }


def insert_rows(con, rows: list[dict], *, dry_run: bool = False) -> RecordResult:
    """INSERT, skipping any card_hash the ledger already holds.

    The skip is the whole idempotency contract and it is a SELECT-then-filter
    rather than an ON CONFLICT so the caller can be told how many were
    duplicates — a `--record` that silently wrote nothing would be
    indistinguishable from one that silently wrote everything."""
    ensure_schema(con)
    have = {r[0] for r in con.execute(
        "SELECT card_hash FROM analysis.recommendation").fetchall()}
    fresh, dupes = [], 0
    seen = set()
    for r in rows:
        if r["card_hash"] in have or r["card_hash"] in seen:
            dupes += 1
            continue
        seen.add(r["card_hash"])
        fresh.append(r)
    if not dry_run and fresh:
        holes = ", ".join("?" for _ in INSERT_COLUMNS)
        con.executemany(
            f"INSERT INTO analysis.recommendation ({', '.join(INSERT_COLUMNS)}) "
            f"VALUES ({holes})",
            [[r[c] for c in INSERT_COLUMNS] for r in fresh])
    return RecordResult(n_offered=len(rows), n_written=len(fresh),
                        n_duplicate=dupes,
                        rec_ids=tuple(r["rec_id"] for r in fresh),
                        dry_run=dry_run)


def set_status(con, rec_id: str, status: str, *, reason: str | None = None,
               on: dt.date | None = None, dry_run: bool = False) -> dict:
    """The ONLY mutation this module performs, and it names only
    MUTABLE_COLUMNS. See the docstring."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    if status in ("withdrawn", "expired") and not reason:
        raise ValueError(f"{status!r} needs a reason")
    ensure_schema(con)
    row = con.execute("SELECT rec_id, status FROM analysis.recommendation "
                      "WHERE rec_id = ?", [rec_id]).fetchone()
    if not row:
        raise ValueError(f"no recommendation {rec_id!r}")
    before = row[1]
    if not dry_run:
        con.execute(UPDATE_STATUS_SQL,
                    [status, reason, on or dt.date.today(), dt.datetime.now(), rec_id])
    return {"rec_id": rec_id, "from": before, "to": status, "reason": reason}


#: Written out as a module constant so the test can assert, by parsing it, that
#: the SET list is a subset of MUTABLE_COLUMNS. An invariant asserted against
#: the actual statement cannot drift from the statement.
UPDATE_STATUS_SQL = (
    "UPDATE analysis.recommendation SET status = ?, status_reason = ?, "
    "status_changed_on = ?, status_changed_at = ? WHERE rec_id = ?")


def withdraw(con, rec_id: str, reason: str, *, on: dt.date | None = None,
             dry_run: bool = False) -> dict:
    return set_status(con, rec_id, "withdrawn", reason=reason, on=on, dry_run=dry_run)


def list_recommendations(con, *, status: str | None = None,
                         category: str | None = None, limit: int = 0):
    require_schema(con)
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if category:
        where.append("category = ?")
        params.append(category)
    sql = ("SELECT * FROM analysis.recommendation_latest"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY issued_on, category")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql, params).fetchdf()


# ------------------------------------------------------ recording a card

def rows_from_cards(cards: list[dict], facts: dict, *, issued_on: dt.date,
                    issued_by: str, area_kind: str, area_id: str,
                    area_label: str | None = None,
                    anchor_lon: float | None = None,
                    anchor_lat: float | None = None,
                    anchor_address_id: str | None = None,
                    gap_score: float | None = None,
                    now: dt.datetime | None = None) -> list[dict]:
    """One ledger row per card. PURE — no database, so the shape of what gets
    recorded is testable without a warehouse."""
    out = []
    for c in cards:
        sections = {s["key"]: s["grade"] for s in c.get("sections", [])}
        out.append(_row(
            issued_on=issued_on, issued_by=issued_by, area_kind=area_kind,
            area_id=area_id, area_label=area_label or c.get("area"),
            anchor_address_id=anchor_address_id,
            anchor_lon=anchor_lon, anchor_lat=anchor_lat,
            category=c["category"],
            proposed_solution=c.get("verdict"),
            format_hint=None,
            grade=c.get("overall_grade"),
            supply_ratio_at_issue=c.get("supply_ratio_vs_base"),
            homes_400m_at_issue=facts.get("homes_400m_median"),
            gap_score_at_issue=gap_score,
            evidence={
                "verdict": c.get("verdict"),
                "regime": c.get("regime"),
                "section_grades": sections,
                "blockers": [b["section"] for b in c.get("blockers", [])],
                "n_addresses": facts.get("n_addresses"),
                "supply_hash": facts.get("live_hash"),
                "rules_version": c.get("rules_version"),
                "asof": facts.get("asof"),
            },
            now=now))
    return out


# ------------------------------------------------------------ the rubric

def _haystack(cand: dict) -> str:
    """Everything a feed says about WHAT this business is, lowercased.
    Deliberately not the address: a laundromat on Lumber Street is not a
    hardware store with lumber."""
    parts = [cand.get("display_name") or cand.get("business_name") or ""]
    for key in ("cuisine", "business_category", "license_type", "store_type",
                "description"):
        v = cand.get(key)
        if v:
            parts.append(str(v))
    return " ".join(parts).lower()


def format_keywords(format_hint: str | None) -> list[str]:
    """The tokens of a format hint that are specific enough to prove anything.
    A comma-separated hint is taken as a list of alternatives."""
    if not format_hint:
        return []
    toks = [t for t in re.split(r"[^a-z0-9/]+", format_hint.lower()) if t]
    return [t for t in toks if len(t) >= 3 and t not in _FORMAT_STOPWORDS]


def _score_category(rec, cand, ctx):
    return True, f"matched loci category {rec['category']!r}"


def _score_format(rec, cand, ctx):
    kws = format_keywords(rec.get("format_hint"))
    if not kws:
        return None, ("the proposal named no operating format, so there is "
                      "nothing to confirm")
    hay = _haystack(cand)
    hit = [k for k in kws if k in hay]
    if hit:
        return True, f"format keyword(s) {hit} appear in {hay[:120]!r}"
    return False, (f"none of the format keyword(s) {kws} appear in "
                   f"{hay[:120]!r} — keyword match only, never a format check")


def _score_corroboration(rec, cand, ctx):
    n = cand.get("n_sources")
    if n is None:
        return None, ("no source count available for this match (the ledger row's "
                      "cluster_id is stale, so the POI members cannot be counted)")
    if int(n) >= 2:
        return True, f"{int(n)} independent sources see this storefront"
    return False, "only one source sees this storefront"


def _score_independent(rec, cand, ctx):
    if not ctx.get("chains_available"):
        return None, "chains tables are absent, so chain membership is unknown"
    brand = cand.get("brand_key")
    chain = ctx.get("chain_brands", {}).get(brand) if brand else None
    if chain:
        return False, (f"resolves to chain {chain!r} — a real outcome, and not the "
                       f"independent operator the card proposed")
    return True, "no chain brand matches this name"


def _score_still_open(rec, cand, ctx):
    """'Still open' reads `model.poi_presence.poi_is_open` -- the ONE shared
    open/closed/unknown predicate (owner rule, GTM-153) -- not a bare
    `last_seen_month` comparison. 'unknown' (and any future 'stale' state the
    predicate grows) is UNAVAILABLE, never a zero: the rubric's own rule is
    that an unconfirmed component does not count against the match, and D79
    forbids reading silence as a closure in the first place."""
    status = cand.get("poi_status")
    newest = ctx.get("newest_ledger_month")
    if status is None:
        return None, "no ledger observation for this match yet"
    if cand.get("fill_month") == newest:
        return None, ("matched in the newest ledger month — 'still open the month "
                      "it opened' is true by construction and proves nothing")
    if status == "unknown":
        return None, ("poi_is_open returns 'unknown' for this match — no "
                      "published evidence either way")
    return status == "open", f"poi_is_open predicate: {status!r}"


#: The rubric. Extend by adding an entry: `weight` plus a `score(rec, cand, ctx)`
#: returning (True | False | None, evidence). None means UNAVAILABLE and is
#: excluded from `max_available` — never scored as a zero.
RUBRIC = {
    "category":      {"weight": 0.50, "required": True,  "score": _score_category},
    "format_hint":   {"weight": 0.20, "required": False, "score": _score_format},
    "corroboration": {"weight": 0.15, "required": False, "score": _score_corroboration},
    "independent":   {"weight": 0.10, "required": False, "score": _score_independent},
    "still_open":    {"weight": 0.05, "required": False, "score": _score_still_open},
}


def score_match(rec: dict, cand: dict, ctx: dict | None = None) -> tuple[float, dict]:
    """(score, quality dict). PURE: no database. See the module docstring."""
    ctx = ctx or {}
    components, score, available = {}, 0.0, 0.0
    for key, spec in RUBRIC.items():
        earned, why = spec["score"](rec, cand, ctx)
        components[key] = {"weight": spec["weight"],
                           "earned": earned, "evidence": why}
        if earned is None:
            continue
        available += spec["weight"]
        if earned:
            score += spec["weight"]
    unavailable = [k for k, v in components.items() if v["earned"] is None]
    return round(score, 4), {
        "score": round(score, 4),
        "max_available": round(available, 4),
        "max_possible": round(sum(s["weight"] for s in RUBRIC.values()), 4),
        "unavailable": unavailable,
        "components": components,
        "caveat": ("open data carries a name, sometimes a cuisine or licence "
                   "class, and a source count. It cannot see hours, staffing, "
                   "price or whether the place is any good."),
    }


# -------------------------------------------------------------- the check

def _dist_sql(lon_expr: str, lat_expr: str) -> str:
    return METRES_SQL.format(a=f"ST_Point({lon_expr}, {lat_expr})",
                             b="ST_Point(?, ?)")


#: `first_seen_on` when a source or a filing dated it, else the first day of
#: the observed month — the same convention chains/detect.py uses, so an
#: observed opening and a dated one fall in the same window. A censored row has
#: BOTH NULL and drops out, which is the point.
LEDGER_OPEN_DATE = ("coalesce(f.first_seen_on, "
                    "strptime(f.first_seen_month || '-01', '%Y-%m-%d')::DATE)")


def ledger_candidates(con, rec: dict, *, radius_m: float, until: dt.date):
    """Same-category ledger openings within radius. Carries `poi_status` --
    the shared open/closed/unknown predicate (model.poi_presence.poi_is_open,
    owner rule, GTM-153), LEFT JOINed on `poi_id_latest` -- so `still_open`
    (below) never has to invent its own definition of "still open" from
    `last_seen_month` alone."""
    from loci.model.poi_presence import poi_is_open

    d = _dist_sql("f.lon", "f.lat")
    status = poi_is_open("p", "f.closed_on")
    return con.execute(f"""
        SELECT f.location_key, f.display_name, f.category, f.lon, f.lat,
               {LEDGER_OPEN_DATE} AS opened_on, f.first_seen_kind,
               f.last_seen_month, f.cluster_id_latest, {d} AS distance_m,
               {status} AS poi_status
        FROM analysis.poi_first_seen f
        LEFT JOIN staging.poi p ON p.poi_id = f.poi_id_latest
        WHERE f.category = ?
          AND f.lon IS NOT NULL AND f.lat IS NOT NULL
          AND {LEDGER_OPEN_DATE} IS NOT NULL
          AND {LEDGER_OPEN_DATE} >= ?
          AND {LEDGER_OPEN_DATE} <= ?
          AND {d} <= ?
        ORDER BY opened_on, distance_m
    """, [rec["anchor_lon"], rec["anchor_lat"], rec["category"],
          rec["issued_on"], until,
          rec["anchor_lon"], rec["anchor_lat"], radius_m]).fetchdf()


def pipeline_candidates(con, rec: dict, *, radius_m: float, until: dt.date):
    d = _dist_sql("p.lon", "p.lat")
    return con.execute(f"""
        SELECT p.pipeline_id, p.business_name, p.business_name_key, p.loci_category,
               p.lon, p.lat, p.entry_stage, p.entry_date, p.furthest_stage,
               p.is_open, p.opened_on, p.opened_on_stage, p.n_sources,
               p.category_confidence, {d} AS distance_m
        FROM analysis.storefront_pipeline p
        WHERE p.loci_category = ?
          AND p.lon IS NOT NULL AND p.lat IS NOT NULL
          AND {d} <= ?
          AND ((p.is_open AND p.opened_on >= ? AND p.opened_on <= ?)
            OR (NOT p.is_open AND p.entry_date >= ? AND p.entry_date <= ?))
        ORDER BY coalesce(p.opened_on, p.entry_date), distance_m
    """, [rec["anchor_lon"], rec["anchor_lat"], rec["category"],
          rec["anchor_lon"], rec["anchor_lat"], radius_m,
          rec["issued_on"], until, rec["issued_on"], until]).fetchdf()


def _match_context(con) -> dict:
    """The things the rubric needs that are per-RUN, not per-candidate."""
    ctx = {"chains_available": False, "chain_brands": {},
           "newest_ledger_month": None}
    try:
        ctx["newest_ledger_month"] = con.execute(
            "SELECT max(last_seen_month) FROM analysis.poi_presence").fetchone()[0]
    except Exception:                       # noqa: BLE001 -- ledger may not exist yet
        pass
    try:
        rows = con.execute(
            "SELECT brand_key, display_name FROM chains.brand_latest "
            "WHERE locations_total >= 2").fetchall()
        ctx["chain_brands"] = {b: n for b, n in rows}
        ctx["chains_available"] = True
    except Exception:                       # noqa: BLE001 -- chains schema optional
        pass
    try:
        from loci.chains.watchlist import brands as _wl
        for b in _wl():
            key = b.get("brand_key")
            if key:
                ctx["chain_brands"].setdefault(key, b.get("display_name") or key)
        ctx["chains_available"] = True
    except Exception:                       # noqa: BLE001 -- watchlist optional
        pass
    return ctx


def _poi_sources(con, cluster_id) -> int | None:
    """Distinct feeds seeing one deduped location. NULL when `cluster_id_latest`
    is stale (sql/018: it is valid only for the newest snapshot month), because
    a stale join would count a DIFFERENT storefront's sources."""
    if cluster_id is None or cluster_id != cluster_id:
        return None
    try:
        row = con.execute(
            "SELECT count(DISTINCT p.source_id) FROM analysis.poi_dedup d "
            "JOIN staging.poi p ON p.poi_id = d.poi_id WHERE d.cluster_id = ?",
            [int(cluster_id)]).fetchone()
    except Exception:                       # noqa: BLE001
        return None
    return int(row[0]) if row and row[0] else None


def _cand_from_ledger(con, row, ctx) -> dict:
    from loci.chains.normalize import brand_key
    name = row.get("display_name")
    return {"kind": "ledger",
            "matched_location_key": row["location_key"],
            "display_name": name,
            "brand_key": brand_key(name) if name else None,
            "n_sources": _poi_sources(con, row.get("cluster_id_latest")),
            "last_seen_month": row.get("last_seen_month"),
            "poi_status": row.get("poi_status"),
            "fill_month": str(row["opened_on"])[:7],
            "opened_on": row["opened_on"],
            "distance_m": float(row["distance_m"]),
            "first_seen_kind": row.get("first_seen_kind")}


def _cand_from_pipeline(con, row, ctx) -> dict:
    from loci.chains.normalize import brand_key
    name = row.get("business_name")
    opened = row.get("opened_on")
    opened = None if opened is None or opened != opened else opened
    return {"kind": "pipeline",
            "matched_pipeline_key": row["pipeline_id"],
            "business_name": name,
            "brand_key": row.get("business_name_key") or (brand_key(name) if name else None),
            # For a pipeline row `n_sources` is the count of FILING FEEDS, not
            # POI feeds. Both answer "does more than one independent record
            # say this exists", which is what the component claims.
            "n_sources": None if row.get("n_sources") is None else int(row["n_sources"]),
            "last_seen_month": None,
            "fill_month": None if opened is None else str(opened)[:7],
            "opened_on": opened,
            "entry_stage": row.get("entry_stage"),
            "entry_date": row.get("entry_date"),
            "distance_m": float(row["distance_m"])}


def _enrich_ledger_attrs(con, cand: dict) -> dict:
    """Pull the WHAT-IS-THIS fields (DOHMH cuisine, DCWP business category, DOS
    licence type, SNAP store type, SLA description) off the cluster's members,
    for the format-hint component only."""
    key = cand.get("matched_location_key")
    if not key:
        return cand
    try:
        rows = con.execute("""
            SELECT p.attrs FROM analysis.poi_presence r
            JOIN analysis.poi_dedup d ON d.cluster_id = r.cluster_id_latest
            JOIN staging.poi p ON p.poi_id = d.poi_id
            WHERE r.location_key = ? AND r.cluster_id_latest IS NOT NULL
        """, [key]).fetchall()
    except Exception:                       # noqa: BLE001
        return cand
    for (attrs,) in rows:
        if not attrs:
            continue
        try:
            doc = json.loads(attrs)
        except (TypeError, ValueError):
            continue
        for f in ("cuisine", "business_category", "license_type", "store_type",
                  "description"):
            if doc.get(f) and not cand.get(f):
                cand[f] = doc[f]
    return cand


@dataclasses.dataclass(frozen=True)
class CheckResult:
    month: str
    radius_m: float
    n_checked: int
    n_opened: int
    n_in_pipeline: int
    n_none: int
    n_newly_filled: int
    dry_run: bool = False


def check(con, *, month: str | None = None, radius_m: float | None = None,
          today: dt.date | None = None, dry_run: bool = False) -> tuple[list[dict], CheckResult]:
    """One month of outcome for every LIVE recommendation (open or filled).

    DELETE + INSERT for the month: re-running 2026-09 replaces 2026-09 and
    touches no other month. Nothing dated after the month's last day is
    visible, so a re-run of an old month reproduces that month's answer rather
    than today's."""
    today = today or dt.date.today()
    month = month or current_month(today)
    validate_month(month)
    ensure_schema(con)
    until = min(month_end(month), today)

    # OPEN **AND FILLED**, not open alone. Two reasons, both load-bearing:
    #   * a filled recommendation still has to be observed every month, or
    #     `still_open` (did the thing that filled the gap survive?) is never
    #     measured after the fill month; and
    #   * re-running a month that flipped a row to 'filled' would otherwise
    #     find nothing open, DELETE the month and write nothing back --
    #     silently destroying the month it was asked to reproduce.
    # Withdrawn and expired rows are NOT re-checked: we retracted the claim,
    # and scoring ourselves on it afterwards would be marking our own homework.
    recs = con.execute(
        "SELECT * FROM analysis.recommendation "
        "WHERE status IN ('open', 'filled') AND issued_on <= ? "
        "ORDER BY issued_on, category", [until]).fetchdf()
    ctx = _match_context(con)
    now = dt.datetime.now()
    out: list[dict] = []
    newly_filled: list[str] = []

    for _, r in recs.iterrows():
        rec = r.to_dict()
        if rec.get("anchor_lon") is None or rec["anchor_lon"] != rec["anchor_lon"]:
            raise ValueError(
                f"{rec['rec_id']} has no anchor point — a recommendation with no "
                "geography cannot be checked, and writing 'none' for it would "
                "report an absence we never looked for.")
        led = ledger_candidates(con, rec, radius_m=radius_m or DEFAULT_RADIUS_M,
                                until=until)
        pipe = pipeline_candidates(con, rec, radius_m=radius_m or DEFAULT_RADIUS_M,
                                   until=until)

        cand, kind = None, "none"
        if len(led):
            cand = _enrich_ledger_attrs(con, _cand_from_ledger(con, led.iloc[0], ctx))
            kind = "opened"
        else:
            opened_pipe = pipe[pipe["is_open"].astype(bool)] if len(pipe) else pipe
            if len(opened_pipe):
                cand = _cand_from_pipeline(con, opened_pipe.iloc[0], ctx)
                kind = "opened"
            elif len(pipe):
                cand = _cand_from_pipeline(con, pipe.iloc[0], ctx)
                kind = "in_pipeline"

        if cand is None:
            quality = {"match": "none",
                       "note": ("no same-category opening or filing within "
                                f"{radius_m or DEFAULT_RADIUS_M:.0f} m (straight line) "
                                f"of the anchor since {rec['issued_on']}"),
                       "searched_until": str(until),
                       "ledger_left_censored": ("the first-seen ledger cannot report an "
                                                "opening it never observed; rows that "
                                                "predate 2026-09 carry a NULL first-seen")}
            out.append({"rec_id": rec["rec_id"], "snapshot_month": month,
                        "matched_location_key": None, "matched_pipeline_key": None,
                        "match_kind": "none", "opened_on": None, "entry_stage": None,
                        "entry_date": None, "days_to_fill": None, "distance_m": None,
                        "same_category": None, "solution_match_score": None,
                        "still_open": None,
                        "quality_json": json.dumps(quality, sort_keys=True, default=str),
                        "snapshot_at": now})
            continue

        score, quality = score_match(rec, cand, ctx)
        basis = "opened_on" if kind == "opened" else "entry_date"
        anchor_date = cand.get("opened_on") if kind == "opened" else cand.get("entry_date")
        days = None
        if anchor_date is not None and anchor_date == anchor_date:
            days = (anchor_date - rec["issued_on"]).days
        quality["days_basis"] = basis
        quality["match_source"] = cand["kind"]
        quality["searched_until"] = str(until)
        if kind == "in_pipeline":
            quality["note"] = ("A FILING IS AN INTENTION. days_to_fill counts days to "
                               "the filing, not to an opening; roughly a third of DOB "
                               "job filings never reach a permit.")

        # The predicate, not `last_seen_month`: 'closed' via a DCWP/DOHMH/
        # SLA/DOS basis is real evidence even in a month the ledger has not
        # re-observed the location. 'unknown' stays NULL/unavailable (D79) --
        # never coerced to a zero.
        still = None
        status = cand.get("poi_status")
        if status is not None and status != "unknown":
            still = (status == "open")

        out.append({
            "rec_id": rec["rec_id"], "snapshot_month": month,
            "matched_location_key": cand.get("matched_location_key"),
            "matched_pipeline_key": cand.get("matched_pipeline_key"),
            "match_kind": kind,
            "opened_on": cand.get("opened_on") if kind == "opened" else None,
            "entry_stage": cand.get("entry_stage"),
            "entry_date": cand.get("entry_date"),
            "days_to_fill": days,
            "distance_m": cand["distance_m"],
            "same_category": True,
            "solution_match_score": score,
            "still_open": still,
            "quality_json": json.dumps(quality, sort_keys=True, default=str),
            "snapshot_at": now})
        if kind == "opened" and rec["status"] == "open":
            newly_filled.append(rec["rec_id"])

    if not dry_run:
        con.execute("DELETE FROM analysis.recommendation_outcome "
                    "WHERE snapshot_month = ?", [month])
        if out:
            holes = ", ".join("?" for _ in OUTCOME_COLUMNS)
            con.executemany(
                f"INSERT INTO analysis.recommendation_outcome "
                f"({', '.join(OUTCOME_COLUMNS)}) VALUES ({holes})",
                [[r[c] for c in OUTCOME_COLUMNS] for r in out])
        for rec_id in newly_filled:
            set_status(con, rec_id, "filled",
                       reason=f"first same-category opening matched in {month}",
                       on=until)

    kinds = [r["match_kind"] for r in out]
    return out, CheckResult(
        month=month, radius_m=float(radius_m or DEFAULT_RADIUS_M),
        n_checked=len(out), n_opened=kinds.count("opened"),
        n_in_pipeline=kinds.count("in_pipeline"), n_none=kinds.count("none"),
        n_newly_filled=len(newly_filled), dry_run=dry_run)


# ------------------------------------------------------------- the report

def report_rows(con) -> list[dict]:
    """The ledger with status, days open and the latest match — the thing
    `loci recommendations report` prints."""
    require_schema(con)
    df = con.execute("""
        SELECT rec_id, issued_on, area_label, area_id, category, grade,
               supply_ratio_at_issue, status, status_reason, latest_month,
               match_kind, days_open, is_censored, opened_on, entry_stage,
               distance_m, solution_match_score, matched_location_key,
               matched_pipeline_key, proposed_solution, format_hint
        FROM analysis.recommendation_latest
        ORDER BY issued_on, supply_ratio_at_issue NULLS LAST, category
    """).fetchdf()
    return df.to_dict("records")


def category_summary(con):
    require_schema(con)
    return con.execute(
        "SELECT * FROM analysis.recommendation_category_summary "
        "ORDER BY n_open DESC, category").fetchdf()


# ---------------------------------------------------------------- backfill
# THE LEDGER'S FIRST ROWS ARE HISTORY, NOT LEADS.
#
# Transcribed from docs/recommendations/gowanus-core-2026-09-11.md (the D74
# card, grades and supply ratios exactly as printed there) and from decision
# D73 in docs/CHECKPOINT.md. They are in CODE rather than a data file so that
# the transcription is reviewable in a diff and testable.
#
# ONE DISCREPANCY, STATED. The CHECKPOINT phase line paraphrases the card as
# "14 of 15 do not act". The card itself says 13 of 15: hardware and
# tailor_repair reach grade C ("diligence") because the listings CSV held a
# couple of cash-flow rows. The CARD is the source of truth here, because the
# card is what was issued. Restaurant graded D on 2026-09-11 and C only in the
# 2026-09-13 regeneration, after the D81 revenue model shipped — recording the
# later grade against the earlier date is exactly the overwrite this ledger
# exists to prevent, so restaurant is recorded D.
# ---------------------------------------------------------------------------

GOWANUS_BBOX = "40.67,-73.995,40.682,-73.982"
GOWANUS_ANCHOR = (-73.9885, 40.676)          # (lon, lat) — the bbox centroid
GOWANUS_HOMES_400M = 3646.0                  # median address, from the card
GOWANUS_CARD_DOC = "docs/recommendations/gowanus-core-2026-09-11.md"

#: (category, supply ratio, grade, regime) — the card's summary table, in its
#: own order (thinnest ratio first).
D74_CARD_2026_09_11 = (
    ("pharmacy",      0.00, "D", "no_signal"),
    ("tailor_repair", 0.00, "C", "saturating"),
    ("convenience",   0.40, "D", "no_signal"),
    ("hardware",      0.72, "C", "no_signal"),
    ("laundry",       0.94, "D", "saturating"),
    ("childcare",     0.94, "D", "saturating"),
    ("hair_barber",   0.98, "D", "saturating"),
    ("grocery",       1.07, "D", "saturating"),
    ("clinic",        1.33, "D", "saturating"),
    ("nails_beauty",  1.75, "D", "saturating"),
    ("restaurant",    1.84, "D", "no_signal"),
    ("bank",          1.97, "D", "saturating"),
    ("cafe_bakery",   2.89, "D", "no_signal"),
    ("fitness",       3.39, "D", "saturating"),
    ("bar",           5.58, "D", "no_signal"),
)

#: The D73 thin leads. These three categories get a NAMED proposed solution and
#: a format hint; the other twelve carry the card's verdict text and no format,
#: which is honest — we proposed nothing specific for them.
D73_THIN_LEADS = {
    "pharmacy": (
        "An independent pharmacy in the Gowanus core. Supply ratio 0.00x of the "
        "MN+BK baseline at 400 m network distance on the principled set (D73): "
        "no pharmacy is reachable on foot from the median doorway here.",
        "independent pharmacy, chemist, drugstore, apothecary"),
    "convenience": (
        "A convenience store / bodega in the Gowanus core. Supply ratio 0.40x of "
        "the MN+BK baseline (D73) — the block carries well under half the "
        "convenience supply a comparable New York block carries.",
        "bodega, convenience, deli, grocery"),
    "hardware": (
        "A hardware store in the Gowanus core, ideally one carrying lumber and "
        "trade supply given the permitted-unit pipeline. Supply ratio 0.72x of "
        "the MN+BK baseline (D73).",
        "hardware, lumber, paint, plumbing, tools"),
}

D73_LAUNDRY_WITHDRAWN = {
    "issued_on": dt.date(2026, 9, 10),
    "issued_by": "D73 pre-ratio lead (laundry evidence: DCWP + LL84)",
    "proposed_solution": (
        "A laundromat in the Gowanus core, from the laundry evidence layer "
        "(DCWP retail-laundry inspections + LL84 in-building laundry) before "
        "the MN+BK supply ratio existed."),
    "format_hint": "laundromat, laundry, wash and fold",
    "withdrawn_on": dt.date(2026, 9, 11),
    "reason": (
        "WITHDRAWN (D73, 2026-09-11): the supply ratio against the MN+BK "
        "baseline came back 0.94x on the principled set at 400 m network "
        "distance — normal for this city, not thin. The lead had been built on "
        "a raw count with no baseline, which is the error the ratio exists to "
        "catch. Kept, not deleted: a ledger of only the leads that survived is "
        "the survivorship bias this table exists to defeat."),
}


def backfill_rows(now: dt.datetime | None = None) -> list[dict]:
    """The honest first rows. PURE — no database."""
    rows = []
    lon, lat = GOWANUS_ANCHOR
    common = dict(area_kind="bbox", area_id=GOWANUS_BBOX, area_label="Gowanus core",
                  anchor_lon=lon, anchor_lat=lat,
                  homes_400m_at_issue=GOWANUS_HOMES_400M, now=now)

    w = D73_LAUNDRY_WITHDRAWN
    rows.append(_row(
        issued_on=w["issued_on"], issued_by=w["issued_by"], category="laundry",
        proposed_solution=w["proposed_solution"], format_hint=w["format_hint"],
        grade=None, supply_ratio_at_issue=None,
        status="withdrawn", status_reason=w["reason"],
        status_changed_on=w["withdrawn_on"],
        evidence={"source": "D73 (docs/CHECKPOINT.md)",
                  "withdrawn_ratio": 0.94,
                  "note": "no card existed on 2026-09-10, so there is no grade"},
        **common))

    issued = dt.date(2026, 9, 11)
    for cat, ratio, grade, regime in D74_CARD_2026_09_11:
        lead = D73_THIN_LEADS.get(cat)
        solution, fmt = lead if lead else (
            ("Diligence: the card reached grade C — the supply reading is real "
             "but the economics are not verified. No specific format proposed."
             if grade == "C" else
             "No action proposed: the card graded this D — do not act on this "
             "data (blocker: economics, no cash-flow comps anywhere in the area)."),
            None)
        issued_by = ("loci recommend (D74 card, gowanus-core-2026-09-11.md)"
                     + (" + D73 thin lead" if lead else ""))
        rows.append(_row(
            issued_on=issued, issued_by=issued_by, category=cat,
            proposed_solution=solution, format_hint=fmt, grade=grade,
            supply_ratio_at_issue=ratio,
            status="open",
            evidence={"source_doc": GOWANUS_CARD_DOC,
                      "regime": regime,
                      "verdict": ("diligence" if grade == "C"
                                  else "do not act on this data"),
                      "blockers": ([] if grade == "C" else ["economics"]),
                      "n_addresses": 1831,
                      "supply_hash": "767b28674e30",
                      "rules_version": 1,
                      "is_d73_thin_lead": bool(lead)},
            **common))
    return rows


def backfill(con, *, dry_run: bool = False, now: dt.datetime | None = None) -> RecordResult:
    """Write the ledger's first rows. Idempotent on card_hash."""
    return insert_rows(con, backfill_rows(now=now), dry_run=dry_run)
