"""`loci verify-closures` core -- budget-capped closure checks for 'unknown'
POIs (D98, GTM-170, AC-11). The CLI wrapper lives in cli.py (owned by another
session today, per this build's file allowlist); everything testable without
a CLI sits here.

WHY A SELECT-THEN-CHECK LOOP, PER POI, NOT A BATCH CALL. Both paid APIs are
priced per lookup (Google Places Text Search $0.032, Tavily basic search
$0.008 -- design-allocator-report.md's cost model, the SAME prices the
allocator report's `report/ledger.py` will charge against the SAME
`analysis.spend_ledger` table, per the D98/D100 reconciliation), so the
budget has to be enforced PER CALL, not per run: `Budget.reserve()` is
checked and an `analysis.spend_ledger` row is written BEFORE every network
call, exactly as `validation.google_places.GooglePlacesClient._charge()`
already does. A run that hits its cap mid-POI stops cleanly rather than
half-spending on one POI and silently skipping the rest.

PLACES FIRST, WEB SECOND, PER POI. A Places place_status lookup is one
structured answer; a web search returns several hits that must be classified.
If Places is conclusive (a place_status match -- see `PlaceStatus`), the
web call for that POI is skipped: the cheaper, more reliable source
shortcuts the noisier, pricier one.

THE PLACES CLIENT IS A PROTOCOL, ON PURPOSE. The task that owns
`validation/google_places.py` today is landing its real
`place_status(name, lat, lon) -> PlaceStatus` method in a later commit; this
module depends only on the small `PlaceStatusProtocol` shape below plus a
`FakePlaces` for tests, so it does not have to wait on that commit or touch
that file.

WHAT THIS DOES NOT DO: batch or citywide runs. `select_unknown` REQUIRES a
bbox (from `--bbox`, or `area_bbox`'s envelope of a named neighborhood) --
the constraint text is explicit: "Never citywide unbudgeted." A caller
wanting "every unknown POI in the city" has to say so with a budget that
could actually cover it; nothing here estimates that cost silently.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from loci.evidence.web_rules import PoiContext, classify
from loci.evidence.web_search import TAVILY_SEARCH_USD, WebSearchClient
from loci.model import poi_evidence as pe

#: Google Places Text Search SKU price. Restated (not imported) from
#: design-closure-evidence.md §2 -- `businessStatus` is a Pro field on the
#: Text Search SKU, and `validation.google_places.place_status` prices it at
#: this same number when it lands. A constant here keeps this module usable
#: before that method exists.
PLACES_TEXT_SEARCH_USD = 0.032

DEFAULT_RECHECK_DAYS = 30


@dataclass
class PlaceStatus:
    """What one Places lookup can say. `verdict` is None for
    CLOSED_TEMPORARILY, a no-result, or a name/distance mismatch (design §2)
    -- never a closure inferred from absence (D79)."""
    verdict: str | None          # 'open' | 'closed' | None
    place_id: str | None = None
    source_name: str = "Google Places"


class PlaceStatusProtocol(Protocol):
    def place_status(self, name: str, lat: float, lon: float,
                     radius_m: int = 50) -> PlaceStatus:
        ...


@dataclass
class FakePlaces:
    """Deterministic Places stand-in for tests, keyed by `name` -- the same
    shape `PlaceStatusProtocol.place_status(name, lat, lon)` actually
    receives; there is no `poi_id` to key on at that call site. `.calls`
    records every name looked up, in order."""
    status_by_poi: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def place_status(self, name: str, lat: float, lon: float,
                     radius_m: int = 50) -> PlaceStatus:
        self.calls.append(name)
        return self.status_by_poi.get(name, PlaceStatus(verdict=None))


@dataclass
class Budget:
    """The one gate every paid call must pass BEFORE it happens. `reserve()`
    never lets `spent` exceed `usd` -- a call whose cost would cross the cap
    is refused, not rounded or averaged away."""
    usd: float
    spent: float = 0.0

    def reserve(self, cost: float) -> bool:
        if self.spent + cost > self.usd + 1e-9:
            return False
        self.spent += cost
        return True

    @property
    def remaining(self) -> float:
        return max(0.0, self.usd - self.spent)


@dataclass
class Candidate:
    poi_id: str
    name: str
    category: str
    lon: float
    lat: float
    colocation_n: int
    cluster_id: int | None = None
    location_key: str | None = None
    street: str | None = None
    website: str | None = None
    is_chain: bool = False


@dataclass
class PlannedCall:
    poi_id: str
    provider: str
    usd: float


@dataclass
class VerifyResult:
    run_id: str
    checked: int = 0
    places_calls: int = 0
    web_calls: int = 0
    closed: int = 0
    opened: int = 0
    still_unknown: int = 0
    budget_hit: bool = False
    dry_run: bool = False
    plan: list[PlannedCall] = field(default_factory=list)
    spent_usd: float = 0.0

    @property
    def estimated_usd(self) -> float:
        return round(sum(p.usd for p in self.plan), 6)


def select_unknown(con, *, bbox: tuple[float, float, float, float],
                   supply_set: str = "principled",
                   recheck_days: int = DEFAULT_RECHECK_DAYS,
                   limit: int | None = None,
                   poi_ids: list[str] | None = None,
                   name: str | None = None) -> list["Candidate"]:
    """'unknown' canonical POIs inside `bbox` (min_lon, min_lat, max_lon,
    max_lat) not rechecked within `recheck_days`, ordered largest co-located
    groups first -- a resolvable ambiguity (GTM-153) is worth more than an
    isolated unknown POI with no double-count risk behind it -- then, WITHIN
    an equal `colocation_n`, nearer to the bbox centre first (same
    `_haversine_m_sql` the legality module uses, imported rather than
    copied, so the two modules can never drift on what "distance" means),
    then `poi_id` for a stable tie-break.

    `poi_ids` (GTM-170 targeting) restricts candidates to those ids exactly
    -- for re-running a check against specific POIs a human has flagged --
    and `name` ILIKE-filters by substring, case-insensitive. Both compose
    with the bbox/recheck/supply-set filters above them; neither replaces
    the bbox requirement (still "never citywide unbudgeted")."""
    from loci.model.address_legality import _haversine_m_sql
    from loci.score.supply import supply_predicate

    col = supply_predicate(supply_set)
    min_lon, min_lat, max_lon, max_lat = bbox
    centre_lon, centre_lat = (min_lon + max_lon) / 2, (min_lat + max_lat) / 2
    dist_sql = _haversine_m_sql("ST_X(s.geom)", "ST_Y(s.geom)",
                                str(centre_lon), str(centre_lat))
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    params: list = [min_lon, max_lon, min_lat, max_lat, recheck_days]
    extra_sql = ""
    if poi_ids:
        placeholders = ", ".join("?" for _ in poi_ids)
        extra_sql += f" AND s.poi_id IN ({placeholders})"
        params.extend(poi_ids)
    if name:
        extra_sql += " AND s.name ILIKE ?"
        params.append(f"%{name}%")
    rows = con.execute(f"""
        SELECT s.poi_id, s.name, s.category, ST_X(s.geom), ST_Y(s.geom),
               s.colocation_n, s.cluster_id
        FROM analysis.poi_supply_status s
        LEFT JOIN (
            SELECT poi_id, max(retrieved_at) AS last_checked
            FROM analysis.poi_closure_evidence GROUP BY 1
        ) c ON c.poi_id = s.poi_id
        WHERE s.poi_status = 'unknown'
          AND s.{col}
          AND ST_X(s.geom) BETWEEN ? AND ?
          AND ST_Y(s.geom) BETWEEN ? AND ?
          AND (c.last_checked IS NULL
               OR date_diff('day', CAST(c.last_checked AS DATE), current_date) >= ?)
          {extra_sql}
        ORDER BY s.colocation_n DESC, {dist_sql} ASC, s.poi_id
        {limit_sql}
    """, params).fetchall()
    return [Candidate(poi_id=r[0], name=r[1] or "", category=r[2], lon=r[3], lat=r[4],
                      colocation_n=r[5], cluster_id=r[6])
            for r in rows]


def area_bbox(con, area: str) -> tuple[float, float, float, float]:
    """Envelope of every `analysis.address_gaps` row whose `neighborhood`
    matches `area` (ILIKE), for `--area`."""
    row = con.execute(
        "SELECT min(lon), min(lat), max(lon), max(lat) FROM analysis.address_gaps "
        "WHERE neighborhood ILIKE ?", [f"%{area}%"]).fetchone()
    if not row or row[0] is None:
        raise ValueError(f"no addresses match neighborhood ILIKE '%{area}%'")
    return (float(row[0]), float(row[1]), float(row[2]), float(row[3]))


def _web_query(cand: Candidate) -> str:
    street = cand.street or ""
    return f'"{cand.name}" "{street}" NYC closed OR sold OR "permanently closed"'


def _ledger(con, run_id: str, kind: str, provider: str, usd: float,
           poi_id: str | None, detail: str | None) -> None:
    con.execute(
        "INSERT INTO analysis.spend_ledger (run_id, kind, provider, usd, ts, poi_id, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [run_id, kind, provider, usd, dt.datetime.now(), poi_id, detail])


def _tally(result: VerifyResult, verdict: str | None) -> None:
    if verdict == "closed":
        result.closed += 1
    elif verdict == "open":
        result.opened += 1
    else:
        result.still_unknown += 1


def verify(con, candidates: list[Candidate], *, budget: Budget,
          places: "PlaceStatusProtocol", web: WebSearchClient,
          run_id: str | None = None, dry_run: bool = False,
          today: dt.date | None = None) -> VerifyResult:
    """Check each candidate, cheapest-conclusive-source-first, until the
    budget refuses the next call. See the module docstring for the
    reserve -> ledger -> call -> evidence-row sequence.

    `dry_run` makes ZERO calls and ZERO writes -- `budget`, `con` and the two
    clients are not touched at all in that branch, only `result.plan` is
    filled with the calls this run WOULD have made and their estimated cost.
    """
    today = today or dt.date.today()
    run_id = run_id or uuid.uuid4().hex
    result = VerifyResult(run_id=run_id, dry_run=dry_run)

    if dry_run:
        for cand in candidates:
            result.plan.append(PlannedCall(cand.poi_id, "places", PLACES_TEXT_SEARCH_USD))
            result.plan.append(PlannedCall(cand.poi_id, "web", TAVILY_SEARCH_USD))
        return result

    for cand in candidates:
        if not budget.reserve(PLACES_TEXT_SEARCH_USD):
            result.budget_hit = True
            break
        _ledger(con, run_id, "verify", "places", PLACES_TEXT_SEARCH_USD, cand.poi_id,
               "places:searchText")
        status = places.place_status(cand.name, cand.lat, cand.lon)
        result.places_calls += 1

        if status.verdict is not None:
            row = pe.EvidenceRow(
                poi_id=cand.poi_id, verdict=status.verdict, source="places",
                source_name=status.source_name,
                url=f"https://www.google.com/maps/place/?q=place_id:{status.place_id}",
                evidence_date=today, dated_by="retrieval",
                retrieved_at=dt.datetime.now(), query="places:searchText",
                location_key=cand.location_key, cluster_id=cand.cluster_id, run_id=run_id)
            pe.insert_evidence(con, row)
            result.checked += 1
            _tally(result, row.verdict)
            continue

        if not budget.reserve(TAVILY_SEARCH_USD):
            result.budget_hit = True
            break
        query = _web_query(cand)
        _ledger(con, run_id, "verify", "tavily", TAVILY_SEARCH_USD, cand.poi_id, query)
        hits = web.search(query, max_results=8)
        result.web_calls += 1

        poi_ctx = PoiContext(poi_id=cand.poi_id, name=cand.name, street=cand.street,
                             website=cand.website, is_chain=cand.is_chain,
                             location_key=cand.location_key, cluster_id=cand.cluster_id)
        winning_verdict = None
        for hit in hits:
            row = classify(hit, poi_ctx, query=query, today=today)
            row.run_id = run_id
            pe.insert_evidence(con, row)
            if row.verdict == "closed" and winning_verdict is None:
                winning_verdict = row.verdict
        result.checked += 1
        _tally(result, winning_verdict)

    result.spent_usd = budget.spent
    return result
