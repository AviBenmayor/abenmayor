"""The three paid clients a report can call, as Protocols, plus the fakes
every test in this package uses and the real-client wiring `default_clients()`
assembles for an actual run.

NO TEST in `loci/tests/test_report_*.py` may construct a real client -- every
test passes a `Fake*` from this module (or `enrich.py`'s own) and asserts on
its `.calls` list. That is what makes AC-17..AC-21 (call-counting) provable
without spending money or needing network access.

WHY PROTOCOLS, NOT ABCs: `evidence.py`/`enrich.py`/`prose.py` type-hint
against these Protocols, never against a concrete client, so a fake with the
right shape satisfies them with zero inheritance -- the same pattern
`chains/research.py`'s `client=None` injection point and
`validation/google_places.py`'s `_FakeSession` already use in this codebase.

`WebSearchClient`/`Hit` are NOT redefined here (RECONCILED header,
design-allocator-report.md line 4): the ONE protocol lives in
`loci.evidence.web_search`, built by the closure-evidence session. This
module imports it lazily (inside functions, not at module load) so that
`loci.report.clients` itself stays importable while that module is still
landing -- only `default_clients()` and anything that actually needs a real
web client pays for the import, and it fails with a clear ImportError rather
than at `import loci.report.clients` time.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# ----------------------------------------------------------------- Places

@dataclass
class PlaceStatusResult:
    """What a Places lookup tells us, already shaped for
    `model.poi_evidence.EvidenceRow` -- `enrich.py` builds one of those
    straight from this dataclass's fields plus the POI id.

    `verdict is None` is a legitimate, inconclusive result (no name match, or
    CLOSED_TEMPORARILY per design-closure-evidence.md section 2) -- it is
    still WORTH a stored row (so a re-check within `--recheck-days` is
    skipped), just not one that moves `poi_status`.
    """
    verdict: str | None          # 'open' | 'closed' | None
    url: str
    source_name: str = "Google Places"
    evidence_date: dt.date | None = None   # None -> dated_by='retrieval', today's date used
    dated_by: str = "retrieval"            # Places publishes no date of its own
    domain_class: str | None = None        # Places has no notion of this; web-only
    reason: str | None = None
    raw: dict | None = None


@runtime_checkable
class PlacesClient(Protocol):
    def business_status(self, name: str, lat: float, lon: float) -> PlaceStatusResult:
        """One Places Text Search lookup near (lat, lon) for `name`. The
        caller charges the budget BEFORE calling this -- this method itself
        never touches `analysis.spend_ledger`."""
        ...


class FakePlaces:
    """Canned by (name, round(lat,5), round(lon,5)) -> PlaceStatusResult;
    a miss returns a `verdict=None` "no result" row rather than raising, which
    is what a real inconclusive lookup does too."""

    def __init__(self, by_name: dict[str, PlaceStatusResult] | None = None):
        self.by_name = by_name or {}
        self.calls: list[tuple[str, float, float]] = []

    def business_status(self, name: str, lat: float, lon: float) -> PlaceStatusResult:
        self.calls.append((name, lat, lon))
        return self.by_name.get(name, PlaceStatusResult(
            verdict=None, url="", reason="fake:no_match"))


def _google_places_adapter():
    """Wrap `validation.google_places.GooglePlacesClient.place_status` as a
    `PlacesClient`, once that method lands (it is being built in the SAME
    closure-evidence session that owns `validation/google_places.py` this
    session must not touch). `AttributeError`/`ImportError` -> None so
    `default_clients()` degrades the same way it does for a missing
    ANTHROPIC_API_KEY, rather than crashing report generation for everyone
    while that build is in flight."""
    try:
        from loci.validation.google_places import GooglePlacesClient
    except ImportError:
        return None
    try:
        client = GooglePlacesClient()
    except Exception:      # noqa: BLE001 -- e.g. no GOOGLE_PLACES_KEY / no budget
        return None
    if not hasattr(client, "place_status"):
        return None

    class _Adapter:
        def business_status(self, name: str, lat: float, lon: float) -> PlaceStatusResult:
            ps = client.place_status(name, lat, lon)
            return PlaceStatusResult(
                verdict=getattr(ps, "verdict", None),
                url=getattr(ps, "url", "") or "",
                source_name="Google Places",
                evidence_date=getattr(ps, "evidence_date", None),
                dated_by=getattr(ps, "dated_by", "retrieval"),
                raw=getattr(ps, "raw", None))

    return _Adapter()


# ------------------------------------------------------------------ Prose

@dataclass
class ProseResult:
    text: str
    input_tokens: int
    output_tokens: int
    #: True for a call billed to the owner's Claude subscription (the CLI
    #: client below) rather than metered per-token against ANTHROPIC_API_KEY
    #: -- `prose.write_prose` reads this to charge `ledger.Budget` $0.00 for
    #: the call instead of estimating a dollar cost that was never incurred.
    plan_billed: bool = False


@runtime_checkable
class ProseClient(Protocol):
    def complete(self, system: str, user: str, *, model: str,
                max_tokens: int) -> ProseResult:
        ...


class FakeProse:
    """Returns `text` verbatim (or a template filled with the user prompt's
    length, if the caller wants something that varies) and pins fake token
    counts so `ledger.Budget.estimate_anthropic`'s true-up logic is
    exercisable without a real API response."""

    def __init__(self, text: str = "Fake prose.", input_tokens: int = 1000,
                output_tokens: int = 500):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, model: str,
                max_tokens: int) -> ProseResult:
        self.calls.append((system, user))
        return ProseResult(text=self.text, input_tokens=self.input_tokens,
                           output_tokens=self.output_tokens)


class AnthropicProse:
    """The real client. `anthropic>=1.0` is a `pyproject.toml` dependency
    added by this session (D100); `ANTHROPIC_API_KEY` is read by the SDK
    itself from the environment. Never constructed by a test."""

    def __init__(self, api_key: str | None = None):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, user: str, *, model: str,
                max_tokens: int) -> ProseResult:
        resp = self._client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}])
        text = "".join(getattr(b, "text", "") for b in resp.content)
        usage = getattr(resp, "usage", None)
        return ProseResult(
            text=text,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0))


class ClaudeCliProse:
    """The real client for an owner who has a Claude subscription but no
    `ANTHROPIC_API_KEY` (GTM-172). Shells out to the Claude Code CLI's
    headless mode -- `claude -p "<prompt>" --output-format text
    [--model <id>]` -- which the CLI bills to that subscription, not to a
    metered API key. There is no usage response to true up against (the CLI
    prints plain text, nothing else), so token counts are ESTIMATED from
    character counts (chars/4, the same rough heuristic Anthropic's own docs
    use) purely for cost-model bookkeeping; `ProseResult.plan_billed=True`
    tells `prose.write_prose` this call cost the run's spend cap $0.00 by
    construction, not that it happened to be free.

    `system` and `user` are concatenated into ONE prompt text (the CLI takes
    a single prompt argument, not separate system/user turns) and passed as
    the `-p` argument rather than piped on stdin -- simpler subprocess
    plumbing, and `claude --help` documents `-p <prompt>` as the primary
    non-interactive form; stdin (`--input-format text` with no argument) is
    the fallback form `claude -p` also accepts but is not needed here since
    the assembled prompt is well under any shell argument-length limit.

    Timeout defaults to 300s (`LOCI_REPORT_CLI_TIMEOUT` overrides) -- a
    headless CLI invocation with no tool access should return quickly, but a
    slow or hung subprocess must not block a report run forever. Never
    constructed by a test with a real subprocess -- `subprocess.run` is
    monkeypatched in every test that touches this class."""

    plan_billed = True

    def __init__(self, binary: str = "claude", timeout: float | None = None):
        self._binary = binary
        self._timeout = (
            float(os.environ.get("LOCI_REPORT_CLI_TIMEOUT", "300"))
            if timeout is None else timeout)

    def complete(self, system: str, user: str, *, model: str,
                max_tokens: int) -> ProseResult:
        prompt = f"{system}\n\n{user}"
        cmd = [self._binary, "-p", prompt, "--output-format", "text"]
        if model:
            cmd += ["--model", model]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=self._timeout, check=True)
        text = proc.stdout
        return ProseResult(
            text=text,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
            plan_billed=True)


# --------------------------------------------------------------- wiring

def default_clients():
    """`(places, web, prose)` for a REAL run. Each is `None` when its
    dependency is not yet ready or its key is unset -- `run.generate()` must
    still produce a report (AC-16) with `places=None`/`web=None` meaning "no
    on-demand closure checks or web enrichment this run" and `prose=None`
    meaning "prose unavailable" (the one case the seed requires by name).
    Never called by a test."""
    return _default_places(), _default_web(), _default_prose()


def _default_places() -> PlacesClient | None:
    if not os.environ.get("GOOGLE_PLACES_KEY"):
        return None
    return _google_places_adapter()


def _default_web():
    if not os.environ.get("TAVILY_API_KEY"):
        return None
    try:
        from loci.evidence.web_search import TavilyWebSearch
    except ImportError:
        return None
    try:
        return TavilyWebSearch()
    except Exception:      # noqa: BLE001
        return None


def _default_prose() -> ProseClient | None:
    """API key present -> the metered `AnthropicProse`. No key but `claude`
    is on PATH (GTM-172) -> `ClaudeCliProse`, billed to the owner's Claude
    subscription instead. Neither -> `None`, same "prose unavailable"
    degrade `run.generate()` already handles."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicProse()
        except Exception:      # noqa: BLE001 -- e.g. `anthropic` not installed yet
            return None
    if shutil.which("claude"):
        try:
            return ClaudeCliProse()
        except Exception:      # noqa: BLE001
            return None
    return None
