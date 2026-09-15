"""Classify one web search Hit against one POI: is this actually closure
evidence, or a false-positive trap (D98, GTM-170, constraint "Closure rule").

FOUR GATES, ALL REQUIRED, before a Hit can produce `verdict='closed'`:
  (a) the POI's name is actually mentioned in the hit's title/snippet;
  (b) a closure phrase appears within WINDOW characters of that mention, with
      no negation in the SAME window;
  (c) the hit's domain is `first_party` (the business's own site) or `news`
      (the trade-press allowlist below) -- never `aggregator` or `other`;
  (d) for a CHAIN POI (>= 3 clusters of the same brand citywide), the street
      token must ALSO appear in the window -- a chain's own closure notice
      names a LOCATION, and without the street this hit could be reporting a
      different branch's closure.
A fifth, unconditional gate: the hit must carry a real PUBLISHED date. An
undated page is stored (verdict NULL, reason 'undated') rather than trusted,
even if every other gate passes -- deliberately more conservative than
`model.poi_evidence.resolve()`'s general precedence rule (which *can* let an
undated, `dated_by='none'` verdict resolve an 'unknown' base): a phrase match
in unstructured web text is noisy enough that this module chooses never to
mint a dateless verdict, full stop.

WEB EVIDENCE NEVER YIELDS 'open'. A page not saying "closed" is not evidence
a business is trading -- it is only evidence nobody has written a closure
notice, which is exactly the absence-is-not-evidence rule (D79) applied to
the web channel. Confirmation that a POI is open, if wanted at all, is a
Google Places job (`evidence.verify`), never web_rules'.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from loci.evidence.web_search import Hit, domain_of
from loci.model.poi_evidence import EvidenceRow

#: Window (characters) around a name mention that closure-phrase, negation
#: and (for chains) street-token checks all read within.
WINDOW = 200

#: A closure phrase within the window is necessary but not sufficient -- see
#: NEGATIONS. "is now " deliberately carries the trailing space: matches
#: "X is now a nail salon" (successor) but not "is nowhere near closing".
CLOSURE_PHRASES = (
    "permanently closed", "has closed", "closed its doors", "closed for good",
    "has been sold", "under new ownership", "is now ",
)

#: Any of these inside the SAME window as a closure phrase refuses the
#: verdict -- "temporarily closed", "closed today" (a same-day/holiday
#: closure, not a shutdown), "for renovation", "until" (a reopening date),
#: "reopened" (the closure already reversed).
#:
#: DEVIATION FROM design-closure-evidence.md §3's literal list: the design
#: names bare "closed on" as a negation (for "closed on Mondays"-style
#: regular-hours language). Matched as a literal substring, it also fires on
#: the single most common closure-headline construction there is -- "<name>
#: HAS CLOSED ON <street>" -- which defeats gate (b) on almost every real
#: local-news closure notice, including ones that also carry an unambiguous
#: phrase like "permanently closed" elsewhere in the same window. `NEGATIONS`
#: keeps every other literal phrase from the design; "closed on" is instead
#: matched by `_DAY_CLOSURE_RE` below, scoped to an actual day-of-week/weekend
#: word, which is what the design's own example ("closed on Mondays") needs.
NEGATIONS = (
    "temporarily", "reopened", "closed today", "for renovation", "until",
)

#: "closed on <day>" -- see the DEVIATION note on NEGATIONS above.
_DAY_WORDS = (
    "monday", "mondays", "tuesday", "tuesdays", "wednesday", "wednesdays",
    "thursday", "thursdays", "friday", "fridays", "saturday", "saturdays",
    "sunday", "sundays", "weekends", "weekdays", "holidays",
)
_DAY_CLOSURE_RE = re.compile(
    r"closed on (" + "|".join(_DAY_WORDS) + r")\b")

#: Trade-press domains a closure notice from is trusted at face value (design
#: §3's literal allowlist -- bare words, matched as substrings of the
#: hostname so a subdomain like ny.eater.com still matches "eater").
NEWS_DOMAIN_FRAGMENTS = (
    "eater", "gothamist", "thecity", "brooklynpaper", "greenpointers",
    "brownstoner", "patch", "nytimes", "timeout", "bkmag",
)

#: Aggregator/directory domains that are NEVER first-party or news, however
#: their content reads -- a Yelp listing marked "permanently closed" is Yelp's
#: crowd-sourced guess, not the business's own statement.
AGGREGATOR_DOMAIN_FRAGMENTS = ("yelp", "mapquest")

#: `[^.,;]{1,40}` (not `\w+`) so a multi-word successor name ("Grab and Go")
#: is captured whole rather than truncated at the first space; the character
#: class stops the match cleanly at the end of the enclosing sentence/clause.
_SUCCESSOR_PATTERNS = (
    re.compile(r"\bnow (?:called |known as )?([A-Z][^.,;]{1,40})"),
    re.compile(r"\breplaced by ([A-Z][^.,;]{1,40})"),
)


@dataclass
class PoiContext:
    """What `classify()` needs to know about the POI a Hit is being checked
    against. `is_chain` (>= 3 clusters of the brand citywide) is computed by
    the caller (`evidence.verify`), not here -- this module has no database
    access."""
    poi_id: str
    name: str
    street: str | None = None
    website: str | None = None
    is_chain: bool = False
    location_key: str | None = None
    cluster_id: int | None = None


def _parse_published(raw) -> dt.date | None:
    if not raw:
        return None
    s = str(raw)[:10]
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def _same_domain(hit_domain: str, website: str) -> bool:
    site_domain = domain_of(website) if "//" in website else website.lower()
    site_domain = (site_domain or "").lower()
    if not site_domain:
        return False
    return hit_domain == site_domain or hit_domain.endswith("." + site_domain)


def domain_class_of(domain: str | None, poi: PoiContext) -> str:
    """`first_party` | `news` | `aggregator` | `other`. See the module
    docstring's gate (c)."""
    if not domain:
        return "other"
    d = domain.lower()
    if any(frag in d for frag in AGGREGATOR_DOMAIN_FRAGMENTS):
        return "aggregator"
    if poi.website and _same_domain(d, poi.website):
        return "first_party"
    from loci.model.poi_presence import name_key_of
    name_key = (name_key_of(poi.name) or "").replace(" ", "")
    bare_domain = d.split(".")[0].replace("-", "")
    if name_key and len(name_key) >= 4 and name_key in bare_domain:
        return "first_party"
    if any(frag in d for frag in NEWS_DOMAIN_FRAGMENTS):
        return "news"
    return "other"


def _name_position(text: str, name: str) -> int | None:
    """Case-insensitive position of `name` in `text` (gate (a)), or of its
    longest normalized token if the literal string does not appear verbatim
    (headline punctuation, possessives, etc.)."""
    low = text.lower()
    idx = low.find(name.lower().strip())
    if idx >= 0:
        return idx
    from loci.score.dedup import norm_tokens
    toks = norm_tokens(name)
    if not toks:
        return None
    longest = max(toks, key=len)
    idx = low.find(longest)
    return idx if idx >= 0 else None


def _successor_name(text: str) -> str | None:
    for pat in _SUCCESSOR_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip().rstrip(".,;:")
    return None


def classify(hit: Hit, poi: PoiContext, *, query: str,
            today: dt.date | None = None,
            retrieved_at: dt.datetime | None = None) -> EvidenceRow:
    """One Hit against one POI -> an EvidenceRow, ALWAYS (never None) --
    inconclusive lookups are stored too (`verdict=None`, `reason` set), so a
    `--recheck-days` window sees this URL as already tried."""
    today = today or dt.date.today()
    retrieved_at = retrieved_at or dt.datetime.now()
    text = f"{hit.title or ''}. {hit.snippet or ''}"
    domain = hit.domain or domain_of(hit.url)
    dclass = domain_class_of(domain, poi)

    parsed = _parse_published(hit.published)
    ev_date = parsed or retrieved_at.date()
    dated_by = "published" if parsed else "none"
    raw = {"title": hit.title, "snippet": hit.snippet, "published": hit.published}

    def inconclusive(reason: str) -> EvidenceRow:
        return EvidenceRow(
            poi_id=poi.poi_id, verdict=None, source="web", source_name=domain or hit.url,
            url=hit.url, evidence_date=ev_date, dated_by=dated_by,
            retrieved_at=retrieved_at, query=query, domain_class=dclass,
            location_key=poi.location_key, cluster_id=poi.cluster_id, reason=reason, raw=raw)

    if dclass not in ("first_party", "news"):
        return inconclusive(f"domain_class={dclass}:not_first_party_or_news")

    idx = _name_position(text, poi.name)
    if idx is None:
        return inconclusive("name_not_found_in_hit")

    lo, hi = max(0, idx - WINDOW), idx + len(poi.name) + WINDOW
    window_text = text[lo:hi].lower()

    if poi.is_chain and not (poi.street and poi.street.lower() in window_text):
        return inconclusive("chain_needs_street_token")

    if not any(phrase in window_text for phrase in CLOSURE_PHRASES):
        return inconclusive("no_closure_phrase_in_window")

    if any(neg in window_text for neg in NEGATIONS) or _DAY_CLOSURE_RE.search(window_text):
        return inconclusive("negation_in_window")

    if parsed is None:
        return inconclusive("undated")

    return EvidenceRow(
        poi_id=poi.poi_id, verdict="closed", source="web", source_name=domain or hit.url,
        url=hit.url, evidence_date=ev_date, dated_by="published",
        retrieved_at=retrieved_at, query=query, domain_class=dclass,
        location_key=poi.location_key, cluster_id=poi.cluster_id,
        successor_name=_successor_name(text), raw=raw)
