"""Web search for closure evidence (D98, GTM-170) -- ONE client protocol,
shared with the allocator report (design-allocator-report.md's reconciliation
header: "ONE WebSearchClient protocol: src/loci/evidence/web_search.py ...
Report imports it; no second protocol in report/clients.py").

`Hit` is the normalized search result both `evidence.web_rules.classify` and
the (later) allocator report's rent/lease/news queries consume.
`TavilyWebSearch` is the paid implementation -- same dependency and client
pattern as `chains/research.py`'s `_client()`. `FakeWebSearch` is canned,
deterministic and injectable for tests.

NEVER INSTANTIATE `TavilyWebSearch` IN A TEST. Building it is safe (no network
call, no key check -- see `_get_client`'s docstring), but this codebase's
convention, exactly like `chains/research.py`, is to inject a fake instead so
no test path can ever spend real money by accident.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

#: env var read by `TavilyWebSearch`, same name `chains/research.py` uses.
ENV_KEY = "TAVILY_API_KEY"

#: Tavily basic-depth search credit price. Restated (not imported) from
#: design-closure-evidence.md §2 / design-allocator-report.md §3's cost
#: model -- the SAME number both callers (verify-closures and the allocator
#: report) charge to `analysis.spend_ledger`.
TAVILY_SEARCH_USD = 0.008


@dataclass
class Hit:
    url: str
    title: str | None
    snippet: str
    published: str | None      # raw source-published date string, or None
    domain: str | None


class WebSearchClient(Protocol):
    def search(self, query: str, *, max_results: int = 8) -> list[Hit]:
        ...


def domain_of(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return None
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


class TavilyWebSearch:
    """The paid implementation. Constructed WITHOUT touching the network or
    requiring `TAVILY_API_KEY` -- the real client is built lazily, on the
    first `search()` call, exactly like `chains/research.py`'s `_client()`.
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        key = self._api_key or os.environ.get(ENV_KEY)
        if not key:
            raise RuntimeError(
                f"{ENV_KEY} is not set. Add it to loci/.env (see .env.example) or "
                f"export it; get a key at https://app.tavily.com. `--dry-run` needs "
                f"no key.")
        try:
            from tavily import TavilyClient
        except ImportError as exc:        # pragma: no cover - dependency is pinned
            raise RuntimeError("tavily-python is not installed; run `uv sync`") from exc
        self._client = TavilyClient(api_key=key)
        return self._client

    def search(self, query: str, *, max_results: int = 8) -> list[Hit]:
        client = self._get_client()
        resp = client.search(query=query, search_depth="basic", max_results=max_results)
        out: list[Hit] = []
        for r in resp.get("results") or []:
            url = r.get("url")
            if not url:
                continue
            out.append(Hit(
                url=url,
                title=r.get("title"),
                snippet=(r.get("content") or "")[:1000],
                published=r.get("published_date") or r.get("published_time"),
                domain=domain_of(url),
            ))
        return out


@dataclass
class FakeWebSearch:
    """Canned results for tests, keyed by exact query string (`None` is a
    catch-all default). `.calls` records every query asked, in order, so a
    test can pin the exact number and content of searches a budget allowed."""
    hits_by_query: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def search(self, query: str, *, max_results: int = 8) -> list[Hit]:
        self.calls.append(query)
        hits = self.hits_by_query.get(query, self.hits_by_query.get(None, []))
        return list(hits[:max_results])
