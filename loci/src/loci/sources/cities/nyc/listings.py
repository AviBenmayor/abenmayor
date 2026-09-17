"""Advertised in-building laundry from rental/sale listing pages (D51(d)).

An ATTRIBUTE source, like PLUTO or ACS -- not a POI source. Nothing here
reaches ``staging.poi``; it does not subclass ``SourceAdapter``. The output is
``staging.listings`` and this source's own (bbl, 'listing') rows of the
shared BBL rollup ``analysis.address_laundry_evidence`` (D58 merge with
sources/cities/nyc/ll84_laundry.py's 'll84' rows;
``loci/sql/010_address_laundry_evidence.sql``). DDL for ``staging.listings``
and the full caveat list live in ``loci/sql/005_listings_laundry.sql``.

Fetching goes through the Tavily API (search + extract), which renders the page
server-side. Direct ``requests`` fetches of all four candidate sites are
blocked (403 / Cloudflare / Access Denied), so Tavily is the access path, not a
convenience.

PROBE, 2026-09-08, 26 Tavily calls
==================================

Tavily ``extract`` with ``extract_depth="advanced"``, ``format="markdown"``,
three Brooklyn URLs per site (search-discovered), plus one ``map`` call:

===============  ========  ==========  =======  =============  ==============
site             renders?  amenities?  address  past listings  calls (credits)
===============  ========  ==========  =======  =============  ==============
StreetEasy unit  3/3       **3/3**     3/3      **3/3**        1 (1)
StreetEasy bldg  2/2       0/2         2/2      0/2            1 (1)
Zillow           3/3       0/3         3/3      0/3            1 (1)
RentHop          2/2       0/2         1/2      0/2            1 (1)
Apartments.com   **0/3**   --          --       --             1 (1)
StreetEasy map   --        --          --       0 URLs         1 (0)
===============  ========  ==========  =======  =============  ==============

Only StreetEasy **unit** pages (``/building/<slug>/<unit>``) carry a
machine-readable amenity block. They render as::

    ## Home features
    *   Dishwasher
    *   Washer/dryer                     <- laundry_in_unit
    ## Building amenities
    Services and facilities
    *   Laundry in building              <- laundry_in_building
    *   Live-in super
    ## About the building
    ###### 51 Schermerhorn Street
    51 Schermerhorn Street, Brooklyn, NY 11201
    14 units / 4 stories / 1890 built    <- PLUTO cross-check
    ## Property history
    | 6/5/2025 | $3,150 | Rented by ... | <- status + listed_date

...plus a Google static-map URL whose ``center=`` parameter carries the
building's lat/lon in EPSG:4326, used to verify the BBL attribution.

StreetEasy **building root** pages render but say "No info on amenities" even
when their own unit pages list "Laundry in building" -- so the root page is not
a usable substitute. Tavily ``map`` returns 0 URLs and 0 credits on
streeteasy.com, and the root page's outbound links are to *nearby* buildings,
not its own units. Past listings are therefore reachable only through the unit
pages a ``search`` surfaces, which is why every address costs a search credit.

THE FINDING THAT SHAPES THE SCHEMA
==================================

42 Carlton Avenue, Brooklyn: four unit listings. **4A** lists "Laundry in
building". **1R, 3L and 4R** list "Doorman" and "Live-in super" under the same
"Services and facilities" heading and omit laundry entirely. Same building,
same laundry room, three of four listings silent about it.

So absence of the phrase is not evidence of absence of the laundry. This module
therefore emits laundry booleans as **TRUE or NULL, never FALSE-by-omission**.
Only an explicit negative phrase sets ``laundry_none``. See CAVEAT ZERO in the
SQL file.

THE FINDING THAT SHAPES THE EXPECTATIONS
========================================

Coverage, not parsing, is the binding constraint. Measured the same day against
``analysis.address_gaps`` Brooklyn laundry leads:

* 7 of 7 head-of-ranking lots (highest ``gap_score``, 1-3 units): building page
  exists, **zero** listings, **zero** amenity data.
* 1 of 10 randomly sampled lots with >=6 residential units had any listing at
  all; **0 of 10** carried a laundry answer.

StreetEasy auto-generates a building page for essentially every NYC address
from city parcel data, so "the page rendered" means nothing. ``amenities_present``
is the only honest denominator.

PILOT, Bay Ridge, 2026-09-09, run ``a48a0a69650a``, 197 calls / 223 credits
==========================================================================

All 119 Bay Ridge laundry-lead lots with >=6 residential units, one search
each, then one advanced extract per address over its slug-gated unit pages:

* 78 of 119 addresses (66%) yielded at least one unit page -- an order of
  magnitude better than the citywide random sample above, because the >=6-unit
  filter selects exactly the stock StreetEasy covers.
* 146 of 150 rendered pages carried a broker amenity block. Once a UNIT page
  exists, parsing is not the problem; reaching one is.
* COVERAGE IS SIZE-SELECTED, hard. Median residential units among Bay Ridge
  >=6u leads that produced a listing: 38. Among those that did not: 14.5. The
  source is blind to precisely the small walk-ups the gap ranking is made of.
* 213 of 222 stored pages are PAST listings; 9 are active. This is an archive,
  not a current-market read -- listing dates run 2014-07-15 to 2026-09-08.

THROTTLING IS A COST, NOT AN ERROR
==================================

Tavily bills the URLs it fails to render. In the pilot, ``extract`` failure was
all-or-nothing per call (37 of 78 calls returned zero results) and grew with
elapsed time: 23% of URLs failed in the first half of the run, 82% in the
second, 151 of 301 overall. An earlier 154-URL run the previous day failed 3.
So the binding constraint on a large sweep is pacing, and any projection built
on the pilot's credits-per-address understates the real cost of a long run.
``TavilyFetcher.pace_s`` throttles, and ``TavilyFetcher.failed_urls`` records
what to re-drive so a retry pass does not re-buy the pages that worked.

THE FULL MN+BK SWEEP, 2026-09-09 (owner-approved)
=================================================

29,737 eligible laundry leads (BK 28,995 / MN 742), run with ``--sweep
--sink``. Three things about its shape:

1. **Parquet sink, not the database.** DuckDB allows one writer and other work
   runs against ``data/loci.duckdb`` for the sweep's whole duration. The fetch
   therefore reads its target list from a READ-ONLY connection, closes it, and
   writes part files plus a ``progress.json`` to disk. ``merge_sink`` lands the
   lot at the end in one short write transaction, deduped on ``listing_url``
   (a resumed run legitimately re-fetches pages, and inserting them twice
   would inflate ``n_listings`` into fabricated evidence).
2. **Ordered, not filtered.** ``select_sweep_targets`` runs the >=6-unit
   stratum first, then 3-5, then 1-2, because yield is size-selected (pilot
   medians: 38 units among leads that produced a listing, 14.5 among those that
   did not). A run stopped at any point has finished the informative stratum.
   Nothing is excluded, so the low-yield stratum's coverage stays MEASURED
   rather than assumed.
3. **The call cap is not a credit cap.** ``--max-calls`` counts calls; Tavily
   bills credits, ~1.13 per call in the pilot, and bills failed URLs too. A
   40,000-call cap is roughly 45,000 credits at the pilot rate. Read the real
   number out of ``staging.listings_fetch_log``, never off the cap.

MANHATTAN SLUGS. ``slug_for`` returns the bare form for MN; StreetEasy also
uses ``<addr>-manhattan``. ``slugs_for`` returns both and ``unit_urls_for``
accepts a list, because gating on one form would have reported the Manhattan
half of the sweep as zero coverage -- a fabricated gap, not a measured one.

TERMS
=====

StreetEasy's ``robots.txt`` disallows ``/rental/*`` and ``/building/*/floorplans``
for generic agents; ``/building/<slug>`` and ``/building/<slug>/<unit>`` are not
in the disallow list. This module never fetches a disallowed path and never
fetches the sites directly -- Tavily is the fetching party and applies its own
robots policy (its ``map`` call declining to enumerate streeteasy.com, at zero
credits, is that policy visible). Apartments.com refuses Tavily outright. None
of this is a licence to redistribute page content: ``raw_amenities`` is stored
for re-parsing without re-fetching, and is internal-use provenance only.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time
import uuid
from dataclasses import dataclass, field

import requests

from loci.db import METRES_SQL

API = "https://api.tavily.com"
SITE = "streeteasy"

#: Tavily extract batches up to 20 URLs per call and bills per 5 URLs.
EXTRACT_BATCH = 20

#: Hard ceiling. `loci ingest-listings --max-calls` may lower it, never raise it.
#: Raised from 300 to 40,000 on 2026-09-09 for the owner-approved full MN+BK
#: laundry sweep (~29.7k leads x 1.66 calls/address; ~$0.008/credit). The
#: ceiling is a spend guard, not a target: the run is expected to STOP at the
#: cap partway through the 1-2 unit stratum, which is why `select_sweep_targets`
#: orders the high-yield stratum first.
MAX_CALLS_CEILING = 40_000

# --------------------------------------------------------------------------
# Phrase tables. Positive phrases set TRUE; NOTHING sets FALSE except an
# explicit negative. Keep these narrow -- a loose pattern here silently
# converts marketing noise into supply.
# --------------------------------------------------------------------------
IN_BUILDING_PHRASES = (
    "laundry in building",
    "laundry room",
    "laundry facilities",
    "common laundry",
    "laundry on site",
    "on-site laundry",
    "shared laundry",
)
IN_UNIT_PHRASES = (
    "washer/dryer",
    "washer / dryer",
    "washer and dryer",
    "in-unit laundry",
    "laundry in unit",
    "w/d in unit",
)
#: "hookup" is plumbing, not a machine -- the same distinction LL84 forces.
IN_UNIT_EXCLUDE = ("hookup", "hook-up", "allowed", "permitted")

EXPLICIT_NEGATIVES = (
    "no laundry",
    "laundry: none",
    "without laundry",
    "no washer",
)

#: NOT a negative -- it means StreetEasy holds no amenity record for the page.
#: Matched as a PATTERN, not a phrase list: the site emits "No info on building
#: amenities", "...on amenities", "...on unit features", "...on services and
#: facilities", "...on policies", and a fixed list silently lets an unlisted
#: variant count as a real amenity block. Found by test, 2026-09-08.
NO_INFO_RE = re.compile(r"^\s*no info on\b", re.I | re.M)

BOROUGH_SLUG = {"BK": "brooklyn", "BX": "bronx", "QN": "queens", "SI": "staten-island"}

_HEAD_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
_MAP_RE = re.compile(r"center=(-?\d+\.\d+)%2C(-?\d+\.\d+)")
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
_ADDR_LINE_RE = re.compile(
    r"^(\d[\w\- ]*?,\s*(?:Brooklyn|Manhattan|New York|Queens|Bronx|Staten Island),\s*NY\s*\d{5})\s*$",
    re.M,
)
_UNIT_URL_RE = re.compile(r"^https://streeteasy\.com/building/([a-z0-9\-]+)(?:/([a-z0-9\-]+))?/?$")


class BudgetExceeded(RuntimeError):
    """Raised the moment a call would exceed the run's call cap."""


class SourceUnavailable(RuntimeError):
    """Raised when every call in a run failed -- never ingest a silent zero."""


@dataclass
class ParsedListing:
    """One listing page, parsed. Laundry fields are TRUE or None -- never False
    by omission. See CAVEAT ZERO in 005_listings_laundry.sql."""
    listing_url: str
    site: str = SITE
    address_raw: str | None = None
    unit: str | None = None
    borough: str | None = None
    listing_type: str | None = None
    status: str | None = None
    listed_date: dt.date | None = None
    laundry_in_unit: bool | None = None
    laundry_in_building: bool | None = None
    laundry_none: bool | None = None
    amenities_present: bool = False
    raw_amenities: str | None = None
    page_lon: float | None = None
    page_lat: float | None = None


@dataclass
class TavilyBudget:
    """Call-count budget, enforced before the request leaves the process.

    Counts CALLS (what the caller controls) and records CREDITS (what Tavily
    bills). One extract call covering 20 URLs is one call and four credits, so
    the two are not interchangeable and both are tracked.
    """
    max_calls: int
    calls: int = 0
    credits: float = 0.0
    log: list[dict] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self) -> None:
        if self.max_calls > MAX_CALLS_CEILING:
            raise ValueError(
                f"max_calls={self.max_calls} exceeds the hard ceiling {MAX_CALLS_CEILING}"
            )

    def reserve(self, endpoint: str, n_urls: int = 1) -> None:
        if self.calls + 1 > self.max_calls:
            raise BudgetExceeded(
                f"call cap reached: {self.calls}/{self.max_calls} calls, "
                f"{self.credits:g} credits spent; refusing {endpoint}"
            )
        self.calls += 1

    def record(self, *, endpoint: str, n_urls: int, credits: float | None,
               http_status: int, n_ok: int, n_failed: int, note: str = "") -> None:
        self.credits += credits or 0.0
        self.log.append({
            "run_id": self.run_id, "seq": len(self.log) + 1,
            "called_at": dt.datetime.now(dt.UTC).replace(tzinfo=None),
            "endpoint": endpoint, "n_urls": n_urls, "credits": credits,
            "http_status": http_status, "n_ok": n_ok, "n_failed": n_failed,
            "note": note[:500],
        })


# --------------------------------------------------------------------------
# URL construction
# --------------------------------------------------------------------------
def slug_for(address: str, borough: str) -> str:
    """PLUTO address + borough -> StreetEasy building slug.

    >>> slug_for("1156 BERGEN AVENUE", "BK")
    '1156-bergen-avenue-brooklyn'
    >>> slug_for("1103 EAST 72 STREET", "BK")
    '1103-east-72-street-brooklyn'

    Manhattan slugs frequently OMIT the borough suffix
    (``/building/100-west-57-street``) and named buildings replace the slug
    entirely (``/building/park-royal/1107``, ``/building/8-marcy/2h``). Both
    are unverified outside Brooklyn; ``candidate_urls`` emits both forms for MN
    and the search fallback covers named buildings.
    """
    base = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    if not base:
        raise ValueError(f"address {address!r} normalizes to an empty slug")
    suffix = BOROUGH_SLUG.get(borough.upper())
    return f"{base}-{suffix}" if suffix else base


def slugs_for(address: str, borough: str) -> tuple[str, ...]:
    """Every slug form StreetEasy may use for this address -- the ACCEPT LIST
    for ``unit_urls_for``.

    Brooklyn is one form (``<addr>-brooklyn``). Manhattan is two: StreetEasy
    usually omits the borough (``/building/100-west-57-street``) but does not
    always. ``slug_for`` returns only the bare form for MN, so gating the
    search hits on it alone would silently reject every ``-manhattan`` unit
    page and report the Manhattan half of a sweep as zero coverage -- a
    fabricated gap, not a measured one.
    """
    base = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    if not base:
        raise ValueError(f"address {address!r} normalizes to an empty slug")
    if borough.upper() == "MN":
        return (base, f"{base}-manhattan")
    return (slug_for(address, borough),)


def candidate_urls(address: str, borough: str) -> list[str]:
    """Deterministic building-page URLs to try before spending a search credit."""
    base = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    if borough.upper() == "MN":
        return [f"https://streeteasy.com/building/{base}",
                f"https://streeteasy.com/building/{base}-manhattan"]
    return [f"https://streeteasy.com/building/{slug_for(address, borough)}"]


def unit_urls_for(slug: str | tuple[str, ...] | list[str], hits: list[dict], *,
                  min_score: float = 0.55) -> list[str]:
    """Filter Tavily search hits down to UNIT pages of exactly this building.

    ``slug`` is one slug or the accept list from ``slugs_for`` (Manhattan has
    two legitimate forms). The slug gate is the whole point. Searching
    "78 Marcy Avenue Brooklyn" returns ``/building/78-division-avenue-brooklyn``
    at score 0.63 -- a different street. Accepting it would attach one
    building's amenities to another's BBL. Only an exact slug match survives.
    """
    allowed = {slug} if isinstance(slug, str) else set(slug)
    out = []
    for h in hits:
        if h.get("score", 0) < min_score:
            continue
        m = _UNIT_URL_RE.match(h.get("url", "").rstrip("/"))
        if m and m.group(1) in allowed and m.group(2):
            out.append(h["url"].rstrip("/"))
    return out


def fallback_unit_urls(hits: list[dict], *, min_score: float = 0.75,
                       cap: int = 6) -> list[str]:
    """Unit pages on ANY building slug -- the NAMED-BUILDING case.

    Measured 2026-09-09 while launching the MN+BK sweep: 1515 Surf Avenue, a
    324-unit Coney Island building, lives at ``/building/1515-surf/1325``. The
    strict slug gate rejects all eight of its unit pages, so the address costs
    a search credit and records as zero coverage -- a FABRICATED gap in exactly
    the large buildings the sweep runs first. Manhattan is worse (``park-royal``,
    ``8-marcy``).

    This is not a relaxation of the slug gate. Pages reached this way are
    attributed to a BBL only if ``page_matches`` confirms the PAGE ITSELF names
    the address we asked for; otherwise the row is discarded. The gate exists
    because "78 Marcy Avenue" returns ``78-division-avenue-brooklyn`` at 0.63,
    and attributing one building's amenities to another's BBL is the worst
    error this source can make. Verifying after the fetch is a different
    control, not a weaker one -- and the score threshold here is higher.
    """
    out = []
    for h in hits:
        if h.get("score", 0) < min_score:
            continue
        m = _UNIT_URL_RE.match(h.get("url", "").rstrip("/"))
        if m and m.group(2):
            out.append(h["url"].rstrip("/"))
        if len(out) >= cap:
            break
    return out


def _tokens(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).split()


def page_matches(p: ParsedListing, address: str, offset_m: float | None) -> bool:
    """Does the PAGE agree that it is the address we asked for?

    The house number must appear as a whole token (``78`` must not be satisfied
    by ``782``); the remaining words are matched as substrings so ``15 STREET``
    accepts the page's ``15th Street``. A page that states a DIFFERENT address
    is rejected outright -- geography is not a tie-breaker there, because two
    buildings 40 m apart are still two buildings. Only when the page states no
    address at all does the 150 m point check stand in.
    """
    want = _tokens(address)
    if not want:
        return False
    if p.address_raw:
        got = _tokens(p.address_raw)
        got_str = " ".join(got)
        if want[0].isdigit() and want[0] not in got:
            return False
        return all(w in got_str for w in want[1:])
    return offset_m is not None and offset_m <= 150


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _section(md: str, heading: str) -> str | None:
    """Text under ``## <heading>`` up to the next ``## `` heading."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$", md, re.M)
    if not m:
        return None
    nxt = _HEAD_RE.search(md, m.end())
    return md[m.end(): nxt.start() if nxt else len(md)].strip()


#: Category headings StreetEasy prints whether or not the category has content.
#: A block containing only these plus "No info on ..." lines is an EMPTY block.
GROUP_HEADINGS = {
    "services and facilities", "wellness and recreation", "shared outdoor space",
    "building type", "pet policy", "amenities", "unit features", "home features",
}


def _has_any(text: str, phrases) -> bool:
    low = text.lower()
    return any(p in low for p in phrases)


def _content_lines(block: str) -> list[str]:
    """Substantive lines in an amenity block: not blank, not a bare image, not a
    'No info on ...' placeholder, not a category heading that StreetEasy prints
    unconditionally. ``amenities_present`` is exactly ``bool(_content_lines(...))``
    -- the difference between "a broker filled in an amenity list" and "the page
    rendered", which is the only honest denominator this source has.
    """
    out = []
    for raw in block.splitlines():
        line = raw.strip().lstrip("*").strip()
        if not line or line.startswith("!["):
            continue
        if NO_INFO_RE.match(line):
            continue
        if line.lower().rstrip(":") in GROUP_HEADINGS:
            continue
        out.append(line)
    return out


def _in_unit_hit(text: str) -> bool:
    """In-unit laundry, with the hookup/allowed exclusions applied per LINE so a
    'Washer/dryer hookup' bullet cannot be rescued by a 'Washer/dryer' bullet
    elsewhere in the same block."""
    for line in text.splitlines():
        low = line.lower()
        if _has_any(low, IN_UNIT_PHRASES) and not _has_any(low, IN_UNIT_EXCLUDE):
            return True
    return False


def parse_streeteasy(url: str, markdown: str) -> ParsedListing:
    """Parse one StreetEasy page's Tavily markdown.

    Emits TRUE or None for every laundry field. Nothing in this function can
    write False except an explicit negative phrase.
    """
    p = ParsedListing(listing_url=url.rstrip("/"))

    m = _UNIT_URL_RE.match(p.listing_url)
    if m and m.group(2) and m.group(2) not in ("documents",):
        p.unit = m.group(2).upper()

    # -- address, as the PAGE states it (never as we asked for it) ----------
    about = _section(markdown, "About the building")
    hunt = about if about else markdown
    a = _ADDR_LINE_RE.search(hunt) or _ADDR_LINE_RE.search(markdown)
    if a:
        p.address_raw = a.group(1).strip()
        for b in ("Brooklyn", "Manhattan", "Queens", "Bronx", "Staten Island"):
            if f", {b}," in p.address_raw:
                p.borough = b
                break
        if p.borough is None and ", New York," in p.address_raw:
            p.borough = "Manhattan"

    # -- coordinates from the page's own static map ------------------------
    mm = _MAP_RE.search(markdown)
    if mm:                                   # center=<lat>,<lon> -- NOT lon,lat
        p.page_lat, p.page_lon = float(mm.group(1)), float(mm.group(2))

    # -- amenity blocks ----------------------------------------------------
    building = _section(markdown, "Building amenities") or _section(markdown, "Amenities")
    home = _section(markdown, "Home features") or _section(markdown, "Unit features")
    blocks = [b for b in (building, home) if b]
    p.raw_amenities = "\n".join(blocks)[:4000] or None
    p.amenities_present = any(_content_lines(b) for b in blocks)

    if building and _has_any("\n".join(_content_lines(building)), IN_BUILDING_PHRASES):
        p.laundry_in_building = True
    if home and _in_unit_hit("\n".join(_content_lines(home))):
        p.laundry_in_unit = True
    # A page-wide explicit negative is the ONLY thing that may say "no".
    if _has_any(markdown, EXPLICIT_NEGATIVES):
        p.laundry_none = True

    # -- status and vintage from the property-history table ----------------
    low = markdown.lower()
    if "no units available" in low:
        p.status = "no_listing"
    elif re.search(r"\b(rented on|sold on|delisted by|no longer available|unavailable)\b", low):
        p.status = "past"
    elif p.amenities_present or "listed by" in low:
        p.status = "active"

    hist = _section(markdown, "Property history")
    dates = [dt.date(int(y), int(mo), int(d)) for mo, d, y in _DATE_RE.findall(hist or markdown)]
    if dates:
        p.listed_date = max(dates)

    if re.search(r"\brental unit\b|\bfor rent\b|\brented by\b", low):
        p.listing_type = "rental"
    elif re.search(r"\bfor sale\b|\bsold by\b|\bin contract\b", low):
        p.listing_type = "sale"

    return p


def _confidence(p: ParsedListing, address: str, lon: float, lat: float,
                method: str, offset_m: float | None) -> float:
    """0..1. Starts from the match METHOD, then is penalised by disagreement
    between the page and PLUTO. A constructed slug that the page confirms is
    the strongest evidence available without a geocoder."""
    score = {"slug_exact": 0.9, "search": 0.7}.get(method, 0.3)
    if p.address_raw:
        want = re.sub(r"[^a-z0-9]+", " ", address.lower()).split()
        got = re.sub(r"[^a-z0-9]+", " ", p.address_raw.lower())
        score += 0.1 if all(w in got for w in want) else -0.3
    if offset_m is not None:
        if offset_m > 150:
            score -= 0.4
        elif offset_m > 50:
            score -= 0.1
    return max(0.0, min(1.0, round(score, 3)))


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------
class TavilyFetcher:
    """Tavily client with a pacing throttle.

    ``pace_s`` exists because of a MEASURED degradation, not caution. Bay Ridge
    pilot, 2026-09-09, run a48a0a69650a: 78 unpaced ``extract`` calls, 301 URLs.
    Failure is all-or-nothing per CALL (37 of 78 calls returned zero results)
    and rises with elapsed time -- 23% of URLs failed in the first half of the
    run, 82% in the second. That is throttling, not bad URLs, and Tavily bills
    the credits either way. Anything larger than a single NTA must pace, and
    must re-drive the failed URLs in a later pass rather than re-running the
    whole sweep.
    """

    def __init__(self, budget: TavilyBudget, api_key: str | None = None,
                 session: requests.Session | None = None,
                 pace_s: float = 0.0, cooldown_s: float = 0.0,
                 max_pace_s: float | None = None) -> None:
        key = api_key or os.environ.get("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY is not set")
        self.budget = budget
        self.pace_s = pace_s
        #: Adaptive throttle. Starts at ``pace_s`` and BACKS OFF when an
        #: ``extract`` call comes back all-failed, because that is the measured
        #: signature of Tavily throttling (pilot a48a0a69650a: failure is
        #: all-or-nothing per call and climbed 23% -> 82% with elapsed time).
        #: Every failed URL is a billed credit with nothing to show for it, so
        #: slowing down is cheaper than pressing on.
        self.cooldown_s = cooldown_s
        self.max_pace_s = max_pace_s if max_pace_s is not None else max(pace_s * 16, 30.0)
        self._pace_now = pace_s
        self.n_backoffs = 0
        #: URLs Tavily accepted, billed and then failed to render. Kept so a
        #: retry pass costs only the pages that are actually missing.
        self.failed_urls: list[str] = []
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {key}",
                               "Content-Type": "application/json"})

    def _throttled(self) -> None:
        """One extract call rendered nothing: back off, and pay a cooldown."""
        self.n_backoffs += 1
        self._pace_now = min(max(self._pace_now * 2, 1.0), self.max_pace_s)
        if self.cooldown_s:
            time.sleep(self.cooldown_s)

    def _recovered(self) -> None:
        """A clean call: decay back toward the base pace, never below it."""
        self._pace_now = max(self.pace_s, self._pace_now * 0.9)

    def _post(self, endpoint: str, payload: dict, n_urls: int, note: str) -> dict:
        self.budget.reserve(endpoint, n_urls)
        if self._pace_now and self.budget.calls > 1:
            time.sleep(self._pace_now)
        # 90 s, not 240: an advanced extract that has not answered in 90 s is
        # throttled, and every extra second is time the sweep spends producing
        # nothing (2026-09-10: attempts crawled 1-2 h through 240 s waits with
        # no progress line, then died on the first ConnectionError).
        try:
            r = self.s.post(f"{API}/{endpoint}", json=payload, timeout=90)
        except requests.RequestException as e:
            # A network failure is a failed, unbilled call -- not the end of
            # the sweep. Record it, back off, and let the caller see an empty
            # body (search: no results; extract: every URL failed).
            self.budget.record(endpoint=endpoint, n_urls=n_urls, credits=0,
                               http_status=0, n_ok=0, n_failed=n_urls,
                               note=f"{note} | {type(e).__name__}")
            if endpoint == "extract":
                self.failed_urls.extend(str(u).rstrip("/") for u in payload.get("urls", []))
            self._throttled()
            return {"results": [], "failed_results": [
                {"url": u, "error": type(e).__name__} for u in payload.get("urls", [])]}
        body = {}
        try:
            body = r.json()
        except ValueError:
            pass
        self.budget.record(
            endpoint=endpoint, n_urls=n_urls,
            credits=(body.get("usage") or {}).get("credits"),
            http_status=r.status_code,
            n_ok=len(body.get("results") or []),
            n_failed=len(body.get("failed_results") or []),
            note=note,
        )
        return body

    def search_building(self, address: str, borough: str) -> list[dict]:
        b = {"BK": "Brooklyn", "MN": "Manhattan"}.get(borough.upper(), borough)
        body = self._post("search", {
            "query": f'"{address.title()}" {b} apartment',
            "max_results": 8, "search_depth": "basic",
            "include_domains": ["streeteasy.com"], "include_usage": True,
        }, 1, note=address)
        return body.get("results") or []

    def extract(self, urls: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(urls), EXTRACT_BATCH):
            chunk = urls[i: i + EXTRACT_BATCH]
            body = self._post("extract", {
                "urls": chunk, "extract_depth": "advanced",
                "format": "markdown", "include_usage": True,
            }, len(chunk), note=f"{len(chunk)} urls")
            results = body.get("results") or []
            failed = body.get("failed_results") or []
            for res in results:
                out[res["url"].rstrip("/")] = res.get("raw_content") or ""
            # Billed-but-empty URLs. Recorded so a retry pass does not re-spend
            # credits on the pages that already rendered.
            for f in failed:
                u = f.get("url") if isinstance(f, dict) else f
                if u:
                    self.failed_urls.append(str(u).rstrip("/"))
            if failed and not results:
                self._throttled()
            elif results and not failed:
                self._recovered()
        return out


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def select_targets(con, *, borough: str = "BK", neighborhood: str | None = None,
                   limit: int = 50, min_units: int = 0) -> list[dict]:
    """Laundry-lead addresses to fetch, highest ``gap_score`` first.

    The street address comes from PLUTO (``addresses.load_residential_addresses``),
    joined to ``analysis.address_gaps`` on BBL. address_gaps carries lon/lat but
    no street address, and a listing site can only be queried by address.
    """
    from loci.sources.cities.nyc.addresses import load_residential_addresses

    pluto = load_residential_addresses(con, borough=borough)
    con.register("_pluto_addr", pluto)
    try:
        rows = con.execute(f"""
            SELECT g.bbl, p.address, g.borough, g.lon, g.lat, g.units,
                   g.neighborhood, g.gap_score
            FROM analysis.address_gaps g
            JOIN _pluto_addr p ON p.bbl = g.bbl
            WHERE g.borough = ? AND g.eligible
              AND g.lead_category = 'laundry' AND g.laundry_ratio > 1
              AND g.units >= ?
              AND p.address IS NOT NULL AND trim(p.address) <> ''
              {"AND g.neighborhood = ?" if neighborhood else ""}
            ORDER BY g.gap_score DESC
            LIMIT ?
        """, [borough, min_units] + ([neighborhood] if neighborhood else []) + [limit]).fetchdf()
    finally:
        con.unregister("_pluto_addr")
    return rows.to_dict("records")


#: Sweep order. Yield is SIZE-SELECTED, hard: in the Bay Ridge pilot the median
#: unit count among leads that produced a listing was 38 vs 14.5 among those
#: that did not. So the sweep runs the >=6-unit stratum first and the 1-2 unit
#: stratum last, and a run stopped at any point -- by the call cap, by a kill,
#: by an outage -- has still finished the stratum that carries the information.
#: This is ordering, NOT filtering: nothing is excluded, so the low-yield
#: stratum's near-zero coverage stays measurable rather than becoming an
#: unexamined assumption.
SWEEP_STRATA = ("6+ units", "3-5 units", "1-2 units")


def select_sweep_targets(con, *, boroughs: tuple[str, ...] = ("MN", "BK"),
                         min_units: int = 1, limit: int | None = None) -> list[dict]:
    """Every eligible laundry lead in `boroughs`, ordered by stratum then
    gap_score. One row per BBL: ``load_residential_addresses`` is deduped on
    address_id (== BBL) before the join, so this join cannot fan out and
    double-count an address into two fetches.
    """
    import pandas as pd

    from loci.sources.cities.nyc.addresses import load_residential_addresses

    pluto = pd.concat([load_residential_addresses(con, borough=b) for b in boroughs],
                      ignore_index=True)
    con.register("_pluto_addr", pluto)
    try:
        placeholders = ",".join("?" for _ in boroughs)
        rows = con.execute(f"""
            SELECT g.bbl, p.address, g.borough, g.lon, g.lat, g.units,
                   g.neighborhood, g.gap_score,
                   CASE WHEN g.units >= 6 THEN 0
                        WHEN g.units >= 3 THEN 1 ELSE 2 END AS stratum
            FROM analysis.address_gaps g
            JOIN _pluto_addr p ON p.bbl = g.bbl
            WHERE g.borough IN ({placeholders}) AND g.eligible
              AND g.lead_category = 'laundry' AND g.laundry_ratio > 1
              AND g.units >= ?
              -- A lot with no PLUTO street address cannot be searched; it
              -- reached the slug builder as NaN and crashed the sweep before
              -- its search was logged, so every relaunch hit it again
              -- (2026-09-10 15:05). Excluded here, never silently coerced.
              AND p.address IS NOT NULL AND trim(p.address) <> ''
            ORDER BY stratum, g.gap_score DESC
            {"LIMIT ?" if limit else ""}
        """, list(boroughs) + [min_units] + ([limit] if limit else [])).fetchdf()
    finally:
        con.unregister("_pluto_addr")
    return rows.to_dict("records")


def plan(targets: list[dict], *, units_per_address: int = 4) -> dict:
    """--dry-run: the call plan, with NO network access.

    One search call per address (the only way to reach unit pages -- see the
    module docstring on map/crawl), then one extract call per EXTRACT_BATCH
    unit pages. Credits are the billed unit: search basic = 1, advanced
    extract = 2 per 5 URLs.
    """
    n = len(targets)
    n_unit_urls = n * units_per_address
    extract_calls = -(-n_unit_urls // EXTRACT_BATCH)
    return {
        "addresses": n,
        "search_calls": n,
        "extract_calls": extract_calls,
        "calls": n + extract_calls,
        "search_credits": n,
        "extract_credits": 2 * (-(-n_unit_urls // 5)),
        "credits": n + 2 * (-(-n_unit_urls // 5)),
        "assumed_unit_pages_per_address": units_per_address,
    }


#: staging.listings, in DDL order. The parquet sink writes exactly these, so a
#: column added to 005_listings_laundry.sql without adding it here fails loudly
#: at merge time rather than shifting every value one position to the left.
LISTING_COLS = (
    "listing_url", "site", "bbl", "address_raw", "unit", "borough",
    "listing_type", "status", "listed_date", "laundry_in_unit",
    "laundry_in_building", "laundry_none", "amenities_present", "raw_amenities",
    "page_lon", "page_lat", "match_method", "match_confidence", "match_offset_m",
    "fetched_at",
)
LOG_COLS = ("run_id", "seq", "called_at", "endpoint", "n_urls", "credits",
            "http_status", "n_ok", "n_failed", "note")


def _listing_schema():
    """Explicit pyarrow schema. Without it, a part file in which every laundry
    value happens to be None infers as null-typed and the merge's UNION ALL of
    part files fails on a type mismatch -- or worse, coerces. The BOOLEAN
    columns are nullable by design (CAVEAT ZERO); the schema must say so."""
    import pyarrow as pa
    return pa.schema([
        ("listing_url", pa.string()), ("site", pa.string()), ("bbl", pa.string()),
        ("address_raw", pa.string()), ("unit", pa.string()), ("borough", pa.string()),
        ("listing_type", pa.string()), ("status", pa.string()),
        ("listed_date", pa.date32()),
        ("laundry_in_unit", pa.bool_()), ("laundry_in_building", pa.bool_()),
        ("laundry_none", pa.bool_()), ("amenities_present", pa.bool_()),
        ("raw_amenities", pa.string()),
        ("page_lon", pa.float64()), ("page_lat", pa.float64()),
        ("match_method", pa.string()), ("match_confidence", pa.float64()),
        ("match_offset_m", pa.float64()), ("fetched_at", pa.timestamp("us")),
    ])


def offset_m(con, t: dict, p: ParsedListing) -> float | None:
    """Metres between the page's own point and PLUTO's, via db.METRES_SQL,
    which flips coordinates -- DuckDB's ST_Distance_Sphere reads POINT as
    (lat, lon) while our geometry is (lon, lat). Decision D16. Both points are
    EPSG:4326 by convention; the DB carries no SRID and will not catch a
    violation, so the flip has to be held in code.

    ``con`` may be an in-memory connection: this needs DuckDB's spatial
    functions, not the project database, so the sweep never touches the file
    lock to compute a distance.
    """
    if p.page_lon is None or t.get("lon") is None:
        return None
    dist = METRES_SQL.format(a="ST_Point(?, ?)", b="ST_Point(?, ?)")
    return con.execute(f"SELECT {dist}",
                       [p.page_lon, p.page_lat, t["lon"], t["lat"]]).fetchone()[0]


def _payload_row(con, t: dict, p: ParsedListing, now: dt.datetime,
                 method: str = "slug_exact", offset: float | None = ...) -> tuple:
    """One staging.listings row, carrying HOW the BBL was attributed."""
    if offset is ...:
        offset = offset_m(con, t, p)
    return (
        p.listing_url, p.site, str(t["bbl"]), p.address_raw, p.unit, p.borough,
        p.listing_type, p.status, p.listed_date, p.laundry_in_unit,
        p.laundry_in_building, p.laundry_none, p.amenities_present,
        p.raw_amenities, p.page_lon, p.page_lat, method,
        _confidence(p, t["address"], t.get("lon"), t.get("lat"), method, offset),
        offset, now,
    )


def write_part(sink_dir, part_no: int, payload: list[tuple], log: list[dict],
               run_id: str = "run") -> dict:
    """Append one part file pair to the sink. Returns the paths written.

    Parts are IMMUTABLE once written, and the filename carries the RUN ID: a
    resumed sweep is a new run writing into the same directory, and numbering
    parts from 1 each time would silently overwrite the first run's parquet --
    losing pages whose credits were already spent.

    The sweep can be killed between any two parts and lose at most
    `part_every` addresses of fetching, never a credit already spent, because
    the fetch log is flushed in the same call.
    """
    import pathlib

    import pyarrow as pa
    import pyarrow.parquet as pq

    d = pathlib.Path(sink_dir)
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    if payload:
        tbl = pa.Table.from_pydict(
            {c: [r[i] for r in payload] for i, c in enumerate(LISTING_COLS)},
            schema=_listing_schema())
        out["listings"] = str(d / f"listings-{run_id}-{part_no:05d}.parquet")
        pq.write_table(tbl, out["listings"])
    if log:
        out["log"] = str(d / f"log-{run_id}-{part_no:05d}.parquet")
        pq.write_table(
            pa.Table.from_pydict({c: [e[c] for e in log] for c in LOG_COLS}),
            out["log"])
    return out


def _progress(sink_dir, payload: dict) -> None:
    import json
    import pathlib

    p = pathlib.Path(sink_dir) / "progress.json"
    tmp = p.with_suffix(".json.tmp")          # atomic: a reader never sees half a file
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(p)


def fetched_bbls(sink_dir) -> set[str]:
    """BBLs already covered by part files in `sink_dir` -- the resume key.

    Note this is BBLs with a RESULT, not addresses attempted: an address whose
    search returned no unit page leaves no row and will be re-searched on a
    resume (1 credit). Recording attempts separately would be cheaper; it is
    also a second source of truth about what was spent, and the fetch-log
    parquet already answers that question exactly.
    """
    import pathlib

    import pyarrow.parquet as pq

    out: set[str] = set()
    for f in sorted(pathlib.Path(sink_dir).glob("listings-*.parquet")):
        out.update(str(b) for b in pq.read_table(f, columns=["bbl"])["bbl"].to_pylist())
    return out


def searched_addresses(sink_dir) -> set[str]:
    """Addresses whose building SEARCH already ran, from the fetch-log parts --
    the second half of the resume key.

    ``fetched_bbls`` only knows BBLs with a RESULT; an address whose search
    found no unit page leaves no listing row, so a resumed sweep re-searched
    it (1 credit) -- and with ~2/3 of six-plus-unit addresses yielding nothing,
    every crash re-spent a credit on each of them (observed 2026-09-09: a
    restart at ~300 addresses re-searched ~190). The fetch log records every
    search call with the address in ``note``, so it answers "attempted?"
    exactly and without a second source of truth about spend.
    """
    import pathlib

    import pyarrow.parquet as pq

    out: set[str] = set()
    for f in sorted(pathlib.Path(sink_dir).glob("log-*.parquet")):
        t = pq.read_table(f, columns=["endpoint", "note"])
        for ep, note in zip(t["endpoint"].to_pylist(), t["note"].to_pylist()):
            if ep == "search" and note:
                out.add(_addr_key(note))
    return out


def _addr_key(address: str) -> str:
    """Normalised address string used as the resume key for searches."""
    import re as _re
    return _re.sub(r"\s+", " ", str(address)).strip().upper()


def build_listings(con, targets: list[dict], *, max_calls: int = 200,
                   dry_run: bool = False, fetcher: TavilyFetcher | None = None,
                   pace_s: float = 0.0, cooldown_s: float = 0.0,
                   sink_dir=None, part_every: int = 25,
                   progress_every: int = 5, log=print,
                   throttle_after: int = 60, throttle_frac: float = 0.95) -> dict:
    """Fetch and land listing pages for ``targets`` (dicts with bbl, address,
    borough, lon, lat). Returns a report; raises SourceUnavailable if every
    call failed, so a total outage can never land as a silent zero.

    With ``sink_dir`` set, NOTHING is written to the project database: rows go
    to parquet part files and a progress json, and ``merge_sink`` lands them
    later in one short write transaction. DuckDB is single-writer, and a sweep
    of this length must not hold the file lock while other work runs. In sink
    mode ``con`` is used only for spatial arithmetic and may be ``:memory:``.
    """
    if dry_run:
        return {"dry_run": True, **plan(targets)}

    budget = TavilyBudget(max_calls=max_calls)
    f = fetcher or TavilyFetcher(budget, pace_s=pace_s, cooldown_s=cooldown_s)
    f.budget = budget
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    started = time.time()
    rows, stats = [], {"addresses": 0, "searched": 0, "unit_pages": 0,
                       "parsed": 0, "with_amenities": 0, "budget_stopped": False,
                       "addresses_with_unit_pages": 0, "fallback_addresses": 0,
                       "fallback_rejected": 0, "aborted": None}
    part_no, part_payload, logged = 0, [], 0
    rows_flushed = 0

    def flush(final: bool = False) -> None:
        nonlocal part_no, part_payload, logged, rows_flushed
        if not part_payload and logged == len(budget.log) and not final:
            return
        part_no += 1
        write_part(sink_dir, part_no, part_payload, budget.log[logged:], budget.run_id)
        rows_flushed += len(part_payload)
        logged = len(budget.log)
        part_payload = []

    def snapshot(**extra) -> None:
        if sink_dir is None:
            return
        el = time.time() - started
        _progress(sink_dir, {
            "run_id": budget.run_id, "updated_at": dt.datetime.now(),
            "targets_total": len(targets), **stats,
            "calls": budget.calls, "max_calls": budget.max_calls,
            "credits": budget.credits,
            "credits_per_address": round(budget.credits / stats["addresses"], 3)
                                   if stats["addresses"] else None,
            "urls_failed": len(f.failed_urls), "backoffs": f.n_backoffs,
            "pace_now_s": round(getattr(f, "_pace_now", 0.0), 2),
            "elapsed_s": round(el), "s_per_address": round(el / stats["addresses"], 2)
                                    if stats["addresses"] else None,
            "rows_flushed": rows_flushed, "parts": part_no, **extra})

    for t in targets:
        stats["addresses"] += 1
        try:
            slugs = slugs_for(t["address"], t["borough"])
            hits = f.search_building(t["address"], t["borough"])
            stats["searched"] += 1
            urls = unit_urls_for(slugs, hits)
            method = "slug_exact"
            if not urls:
                # Named-building slug (/building/1515-surf/1325). Fetched, then
                # verified against the page's own address -- see fallback_unit_urls.
                urls = fallback_unit_urls(hits)
                method = "search_verified"
                stats["fallback_addresses"] += bool(urls)
            if urls:
                stats["addresses_with_unit_pages"] += 1
                stats["unit_pages"] += len(urls)
                pages = f.extract(urls[:EXTRACT_BATCH])
            else:
                pages = {}
        except BudgetExceeded as e:
            stats["budget_stopped"] = True
            if log:
                log(f"BUDGET STOP: {e}", flush=True)
            break
        # Circuit breaker. Tavily BILLS every URL it fails to render, so a
        # sustained all-failure regime spends the whole cap and returns
        # nothing. Adaptive pacing handles a burst; this catches the case
        # where backing off is not working, and stops rather than paying to
        # discover that 30,000 more times.
        if (stats["unit_pages"] >= throttle_after
                and len(f.failed_urls) >= throttle_frac * stats["unit_pages"]):
            stats["aborted"] = "throttled"
            break
        for url, md in pages.items():
            p = parse_streeteasy(url, md)
            stats["parsed"] += 1
            off = offset_m(con, t, p)
            if method == "search_verified" and not page_matches(p, t["address"], off):
                # The page names a different building. Dropping it is the whole
                # point of the fallback being verified rather than trusted.
                stats["fallback_rejected"] += 1
                continue
            stats["with_amenities"] += bool(p.amenities_present)
            if sink_dir is None:
                rows.append((t, p, method, off))
            else:
                part_payload.append(_payload_row(con, t, p, now, method, off))
        if sink_dir is not None:
            if log and stats["addresses"] % progress_every == 0:
                log(f"  [{stats['addresses']:>6}/{len(targets)}] {t['borough']} "
                    f"{t['address']:<28} {t['units']:>5.0f}u  pages={len(pages)} "
                    f"calls={budget.calls} credits={budget.credits:g} "
                    f"failed_urls={len(f.failed_urls)} pace={f._pace_now:g}s", flush=True)
            if stats["addresses"] % part_every == 0:
                flush()
                snapshot()

    if stats["searched"] == 0 and stats["addresses"] > 0:
        raise SourceUnavailable("no Tavily call succeeded; refusing to write")
    if budget.log and all(e["http_status"] >= 400 for e in budget.log):
        raise SourceUnavailable(
            f"every Tavily call failed (n={len(budget.log)}); refusing to write")

    if sink_dir is not None:
        flush(final=True)
        written = rows_flushed
        snapshot(finished=True)
    else:
        written = _write(con, rows, budget)
    if stats["aborted"] == "throttled":
        # Everything fetched so far is already durable in the sink; this is a
        # loud stop, not a data loss. Resume with the same --sink.
        raise SourceUnavailable(
            f"{len(f.failed_urls)}/{stats['unit_pages']} extract URLs failed and "
            f"backing off to {f._pace_now:g}s did not recover; stopped after "
            f"{budget.calls} calls / {budget.credits:g} credits rather than "
            f"paying for a run that renders nothing")
    stats.update(calls=budget.calls, credits=budget.credits,
                 run_id=budget.run_id, rows_written=written,
                 urls_failed=len(getattr(f, "failed_urls", [])),
                 backoffs=getattr(f, "n_backoffs", 0),
                 sink_dir=str(sink_dir) if sink_dir else None)
    return stats


def merge_sink(con, sink_dir) -> dict:
    """Land a sink directory into staging.listings + the fetch log, then
    rebuild the BBL rollup. ONE short write transaction, so the sweep's hours
    of fetching cost the single-writer database only seconds of lock.

    Deduped on listing_url keeping the newest fetched_at, because part files
    from a resumed run legitimately overlap. Without that, the same page would
    insert twice and n_listings would double-count a building's evidence.
    """
    import pathlib

    d = pathlib.Path(sink_dir)
    parts = sorted(d.glob("listings-*.parquet"))
    logs = sorted(d.glob("log-*.parquet"))
    if not parts and not logs:
        raise SourceUnavailable(f"{d} holds no part files; refusing to merge nothing")

    cols = ", ".join(LISTING_COLS)
    out = {"sink_dir": str(d), "listing_parts": len(parts), "log_parts": len(logs)}
    con.execute("BEGIN TRANSACTION")
    try:
        if parts:
            con.execute(
                "CREATE OR REPLACE TEMP TABLE _sink AS "
                f"SELECT {cols} FROM ("
                f"  SELECT {cols}, row_number() OVER "
                "     (PARTITION BY listing_url ORDER BY fetched_at DESC) AS rn "
                "  FROM read_parquet(?)) WHERE rn = 1",
                [[str(p) for p in parts]])
            out["rows_in_sink"] = con.execute("SELECT count(*) FROM _sink").fetchone()[0]
            out["rows_replaced"] = con.execute(
                "SELECT count(*) FROM staging.listings "
                "WHERE listing_url IN (SELECT listing_url FROM _sink)").fetchone()[0]
            con.execute("DELETE FROM staging.listings WHERE listing_url IN "
                        "(SELECT listing_url FROM _sink)")
            con.execute(f"INSERT INTO staging.listings ({cols}) SELECT {cols} FROM _sink")
        if logs:
            con.execute(
                "CREATE OR REPLACE TEMP TABLE _sinklog AS "
                f"SELECT DISTINCT {', '.join(LOG_COLS)} FROM read_parquet(?)",
                [[str(p) for p in logs]])
            out["log_rows"] = con.execute("SELECT count(*) FROM _sinklog").fetchone()[0]
            # Whole-run replace: seq is unique within run_id, and a sink holds
            # exactly one run's spend record, so this is idempotent re-merge
            # rather than a partial overwrite.
            con.execute("DELETE FROM staging.listings_fetch_log WHERE run_id IN "
                        "(SELECT DISTINCT run_id FROM _sinklog)")
            # Named on BOTH sides. `_sinklog` is already built by SELECTing
            # LOG_COLS in order, so nothing is mis-written today -- but DuckDB
            # binds INSERT ... SELECT by POSITION, and only the TARGET column
            # list survives an ALTER on the log table.
            log_cols = ", ".join(LOG_COLS)
            con.execute(f"INSERT INTO staging.listings_fetch_log ({log_cols}) "
                        f"SELECT {log_cols} FROM _sinklog")
        out["bbl_rows"] = build_address_listing_laundry(con)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    out["staging_rows"] = con.execute("SELECT count(*) FROM staging.listings").fetchone()[0]
    return out


def _write(con, rows, budget: TavilyBudget) -> int:
    """Land rows + the spend log directly (non-sink path)."""
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    payload = [_payload_row(con, t, p, now, m, off) for t, p, m, off in rows]
    if payload:
        con.executemany(
            "DELETE FROM staging.listings WHERE listing_url = ?",
            [(r[0],) for r in payload])
        # LISTING_COLS, not a bare count of placeholders: `_payload_row` builds
        # its tuple in that order, and a column added to sql/005 without adding
        # it there must fail loudly rather than shift every value one left.
        con.executemany(
            "INSERT INTO staging.listings (" + ", ".join(LISTING_COLS) + ") VALUES ("
            + ",".join(["?"] * len(LISTING_COLS)) + ")", payload)
    if budget.log:
        # LOG_COLS, and the values are pulled BY KEY rather than by dict order
        # -- `budget.log` entries are built literally in LOG_COLS order today,
        # but relying on that couples the spend ledger to a dict literal's
        # layout.
        con.executemany(
            "INSERT OR REPLACE INTO staging.listings_fetch_log ("
            + ", ".join(LOG_COLS) + ") VALUES ("
            + ",".join(["?"] * len(LOG_COLS)) + ")",
            [tuple(e[c] for c in LOG_COLS) for e in budget.log])
    return len(payload)


def build_address_listing_laundry(con) -> int:
    """Roll staging.listings up to one row per BBL. Writes analysis.address_
    laundry_evidence with source='listing' (D58 merge of address_listing_
    laundry into the shared evidence table; sql/010_address_laundry_evidence.sql)
    -- only this source's own (bbl, 'listing') rows are touched, never the
    'll84' rows sources/cities/nyc/ll84_laundry.py writes there.

    ``any_laundry_advertised`` is TRUE or NULL and NEVER FALSE: a NULL result
    for a BBL whose listings were all silent is the honest answer, because
    silence demonstrably does not mean absence (42 Carlton Avenue, 1 of 4).
    ``n_silent`` sizes that unusable stratum instead of laundering it to zero.
    """
    con.execute("DELETE FROM analysis.address_laundry_evidence WHERE source = 'listing'")
    con.execute("""
        INSERT INTO analysis.address_laundry_evidence (
            bbl, source, n_listings, n_with_amenities, n_in_unit, n_in_building,
            n_none, n_silent, latest_listed, any_laundry_advertised,
            best_match_confidence, sites, built_at
        )
        SELECT
            bbl,
            'listing',
            count(*)                                                      AS n_listings,
            count(*) FILTER (WHERE amenities_present)                     AS n_with_amenities,
            count(*) FILTER (WHERE laundry_in_unit)                       AS n_in_unit,
            count(*) FILTER (WHERE laundry_in_building)                   AS n_in_building,
            count(*) FILTER (WHERE laundry_none)                          AS n_none,
            count(*) FILTER (WHERE amenities_present
                             AND laundry_in_unit IS NULL
                             AND laundry_in_building IS NULL
                             AND laundry_none IS NULL)                    AS n_silent,
            max(listed_date)                                              AS latest_listed,
            CASE WHEN count(*) FILTER (WHERE laundry_in_unit OR laundry_in_building) > 0
                 THEN TRUE ELSE NULL END                                  AS any_laundry_advertised,
            max(match_confidence)                                         AS best_match_confidence,
            string_agg(DISTINCT site, ',')                                AS sites,
            now()::TIMESTAMP                                              AS built_at
        FROM staging.listings
        WHERE bbl IS NOT NULL
        GROUP BY bbl
    """)
    return con.execute(
        "SELECT count(*) FROM analysis.address_laundry_evidence WHERE source = 'listing'"
    ).fetchone()[0]
