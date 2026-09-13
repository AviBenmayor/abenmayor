"""`loci chains research` -- press enrichment via Tavily.

The only part of `loci chains` that costs money and touches the network, so it
is the only part with a budget, and the budget is ENFORCED IN CODE (cross-project
standard): `MAX_QUERIES` is counted down inside the loop and the run stops, it
is not a note in a comment. `--dry-run` prints the exact query list and spends
nothing.

--------------------------------------------------------------------------
WHY TWO KINDS OF QUERY
--------------------------------------------------------------------------
BRAND queries ("Apollo Bagels new location NYC") confirm what is already on the
watchlist. They can only ever tell you about brands you already named.

DISCOVERY queries are the standing ones -- "opening new location NYC",
"expands to Brooklyn" -- restricted to the trade press that actually covers NYC
retail leasing. They are how a brand nobody on the list has heard of arrives.
A discovery hit lands with `brand_key = ''` and `query_kind = 'discovery'`;
matching it to a brand is a human read of docs/CHAINS.md, deliberately, because
an automatic brand extraction from a headline is exactly the kind of plausible
wrong answer that would quietly pollute the watchlist.

--------------------------------------------------------------------------
WHAT THIS IS NOT
--------------------------------------------------------------------------
It is not evidence. A press hit is a headline and a date; `chains.press_hits`
is a reading queue. Nothing in it is promoted to the watchlist without a person
putting it there, which is why `watchlist.yaml` carries `confidence` and
`evidence` and this table carries neither.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

#: Hard ceiling on one run. Tavily bills per query; `basic` depth is 1 credit,
#: `advanced` is 2. At the default 60 queries on basic depth a monthly refresh
#: costs 60 credits.
MAX_QUERIES = 60

#: Press window. 45 days rather than 30: a monthly cron that slips by a week
#: must not leave a hole in the record.
DEFAULT_DAYS = 45

ENV_KEY = "TAVILY_API_KEY"

#: The NYC retail/real-estate trade press. Restricting to these is what keeps
#: "opening new location NYC" from returning a national franchise-blog farm.
PRESS_DOMAINS = (
    "ny.eater.com",
    "therealdeal.com",
    "commercialobserver.com",
    "crainsnewyork.com",
    "timeout.com",
    "nypost.com",
    "brooklynpaper.com",
    "amny.com",
)

#: Standing queries. Each is a way a new-store announcement is usually worded.
DISCOVERY_QUERIES = (
    "restaurant chain opening new location NYC",
    "retail chain expands to Brooklyn",
    "signs lease for first Manhattan location",
    "opening second NYC location",
    "fitness studio opening new NYC location",
    "grocery chain new store New York City",
    "coffee chain expansion New York",
    "retailer signs Manhattan retail lease expansion",
)


@dataclass
class ResearchPlan:
    """The exact spend, decided before anything is sent."""
    queries: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, brand_key, q)
    budget: int = MAX_QUERIES
    truncated: int = 0

    @property
    def n_queries(self) -> int:
        return len(self.queries)


def build_plan(brand_keys, brand_names=None, *, max_queries: int = MAX_QUERIES,
               include_discovery: bool = True) -> ResearchPlan:
    """Queries for this run, discovery FIRST.

    Discovery goes first on purpose: when the budget truncates, the thing worth
    keeping is the channel that finds brands nobody listed. Confirming a brand
    already on the watchlist can wait a month."""
    names = dict(brand_names or {})
    plan = ResearchPlan(budget=max_queries)
    wanted: list[tuple[str, str, str]] = []
    if include_discovery:
        wanted += [("discovery", "", q) for q in DISCOVERY_QUERIES]
    for key in brand_keys:
        label = names.get(key) or key
        wanted.append(("brand", key, f'"{label}" new location opening New York City'))
    plan.queries = wanted[:max_queries]
    plan.truncated = max(0, len(wanted) - max_queries)
    return plan


def _client():
    """The Tavily client, or a clear failure naming the env var."""
    key = os.environ.get(ENV_KEY)
    if not key:
        raise RuntimeError(
            f"{ENV_KEY} is not set. Add it to loci/.env (see .env.example) or export "
            f"it; get a key at https://app.tavily.com. `--dry-run` needs no key.")
    try:
        from tavily import TavilyClient
    except ImportError as exc:      # pragma: no cover - dependency is pinned
        raise RuntimeError("tavily-python is not installed; run `uv sync`") from exc
    return TavilyClient(api_key=key)


def _published(result: dict) -> dt.date | None:
    raw = result.get("published_date") or result.get("published_time")
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        try:
            return dt.datetime.strptime(str(raw)[:16], "%a, %d %b %Y").date()
        except ValueError:
            return None


def run(con, plan: ResearchPlan, *, days: int = DEFAULT_DAYS,
        max_results: int = 8, search_depth: str = "basic",
        today: dt.date | None = None, client=None) -> dict:
    """Execute the plan and upsert `chains.press_hits`. Returns run counts.

    `client` is injectable so the test can exercise the budget and the upsert
    without a network call or an API key."""
    from loci.chains.detect import ensure_schema

    today = today or dt.date.today()
    start = (today - dt.timedelta(days=days)).isoformat()
    api = client or _client()
    ensure_schema(con)

    rows: list[tuple] = []
    spent = errors = 0
    for kind, key, query in plan.queries:
        if spent >= plan.budget:
            break
        spent += 1
        try:
            resp = api.search(query=query, topic="news", search_depth=search_depth,
                              max_results=max_results, start_date=start,
                              include_domains=list(PRESS_DOMAINS))
        except Exception:               # noqa: BLE001 -- one bad query must not
            errors += 1                 # abandon the credits already spent
            continue
        for r in resp.get("results") or []:
            url = r.get("url")
            if not url:
                continue
            rows.append((key, url, r.get("title"), _published(r),
                         (r.get("content") or "")[:1000], r.get("score"),
                         query, kind, dt.datetime.now()))

    written = _upsert(con, rows)
    return {"queries_spent": spent, "queries_planned": plan.n_queries,
            "errors": errors, "hits": len(rows), "written": written,
            "since": start}


def _upsert(con, rows: list[tuple]) -> int:
    """INSERT OR REPLACE on (brand_key, url). Re-running a query that returns
    the same article refreshes it instead of duplicating it."""
    if not rows:
        return 0
    seen: dict[tuple[str, str], tuple] = {}
    for row in rows:
        seen[(row[0], row[1])] = row      # last write wins within a run
    con.executemany(
        "INSERT OR REPLACE INTO chains.press_hits "
        "(brand_key, url, title, published_on, snippet, score, matched_query, "
        " query_kind, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
        list(seen.values()))
    return len(seen)


def recent_hits(con, *, days: int = DEFAULT_DAYS, limit: int = 40,
                today: dt.date | None = None) -> list[dict]:
    """Press hits for the generated doc. Undated hits are kept (trade press
    often omits a date) and sorted last rather than dropped."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    return con.execute("""
        SELECT brand_key, url, title, published_on, query_kind, matched_query
        FROM chains.press_hits
        WHERE published_on IS NULL OR published_on >= CAST(? AS DATE)
        ORDER BY published_on DESC NULLS LAST, brand_key, url
        LIMIT ?
    """, [cutoff, int(limit)]).fetchdf().to_dict("records")
