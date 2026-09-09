"""DOHMH restaurant inspections — the ANCHOR source (GTM-17).

Dataset 43nn-pn8j on NYC Open Data (Socrata). One row per violation, so many
rows per establishment; CAMIS is the unique establishment id. This is a
near-census of food service — every food establishment is inspected — which is
why it anchors the coverage-bias calibration (CONTEXT.md §7.1). Treat its counts
as ground truth for the food tier.

Scope decision (recorded): DOHMH cleanly identifies restaurant vs cafe/bakery by
cuisine, but does NOT reliably separate bars. Bars are left to OSM (amenity=bar),
which tags them explicitly. So this adapter emits `restaurant` and `cafe_bakery`
only, never `bar`. Documenting rather than guessing.

--------------------------------------------------------------------------
ACTIVE FILTER (D36 / D47 follow-up)
--------------------------------------------------------------------------
D36 found the residual same-coordinate duplication in this feed is closed-
establishment TURNOVER: DOHMH publishes a rolling multi-year window keyed on
inspection activity, so a departed tenant and its successor at one address can
both survive as points. Testing that required date fields the adapter never
fetched (D47). It now fetches `inspection_date`, `action`, `grade`,
`grade_date` and derives, per CAMIS, two activity signals stored in `attrs`:

  last_inspection_date       max(inspection_date) over the CAMIS, or None
  closed_at_last_inspection  the most recent inspection carried a DOHMH
                             closure action and no re-open on the same date
  active                     the ACTIVE filter's verdict (bool)
  active_basis               why, in words — for provenance

**Why the date and not a status column: DOHMH publishes no open/closed status.**
The only closure marker is the `action` text, and it means a *regulatory*
closure for health violations — usually temporary, normally followed by
"Establishment re-opened by DOHMH" days later. It is NOT "out of business".
Statewide counts on the 2026-09-07 extract: 10,839 closure rows across 294,829
rows, but only 146 of 31,293 CAMIS are closed *at their most recent
inspection*. So closure alone cannot carry the filter; permanent departure
shows up as the establishment simply ceasing to be inspected.

**Why N = 24 months.** Every food establishment is on a recurring inspection
cycle (roughly annual for grade A, more often below). The empirical
distribution of "days since last inspection" per CAMIS on the 2026-09-07
extract is median 216 d, p90 525 d (17.3 months). 24 months is ~1.4x p90, so a
record past it has missed its cycle by a clear margin rather than sitting in
the tail of normal cadence variation. Cutting at 12 months would drop 21.9% of
CAMIS — most of them ordinary A-graded restaurants on a stretched cycle — and
would manufacture supply gaps, the exact failure mode this project exists to
avoid. Cut shares on that extract: >12m 21.9%, >18m 7.6%, >24m 2.9%, >36m 1.4%.
STALE_MONTHS is a parameter so the 18-month sensitivity can be run without an
edit.

**Never-inspected CAMIS are treated as ACTIVE, not stale.** 3,742 of 31,293
(12.0%) carry only DOHMH's 1900-01-01 sentinel inspection date, i.e. permitted
but not yet inspected — new establishments. Marking them stale would delete
exactly the newest supply. They are flagged `active_basis="never_inspected"`
so the assumption is visible.

`record_date` is NOT a freshness signal: it is the extract timestamp and is
identical on every row (2026-09-07T06:00:17 on the probed extract). Do not use it.

CAVEAT THE DATABASE CANNOT ENFORCE: "not inspected in 24 months" is a proxy for
"closed", not an observation of closure. It will keep a closed restaurant whose
successor has not yet opened, and (rarely) drop a long-dormant-but-licensed one.
"""
from __future__ import annotations

import datetime as dt
import os
import time
from collections.abc import Iterable, Iterator

import requests

from loci.sources.base import POIRecord, SourceAdapter

ENDPOINT = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
PAGE = 50_000

#: DOHMH's un-inspected sentinel in `inspection_date`.
SENTINEL_DATE = dt.date(1900, 1, 1)

#: Months without an inspection after which an establishment is presumed
#: closed. See the module docstring for the derivation (~1.4x the empirical
#: p90 inter-inspection gap). Days, so the test is calendar-free.
STALE_MONTHS = 24
STALE_DAYS = int(STALE_MONTHS * 30.44)

CAFE_KEYWORDS = ("coffee", "tea", "bakery", "donut", "doughnut", "dessert",
                 "juice", "ice cream", "bagel", "café", "cafe")

_CLOSED_MARKERS = ("establishment closed by dohmh", "establishment re-closed by dohmh")
_REOPEN_MARKER = "establishment re-opened by dohmh"


def classify(cuisine: str | None) -> str:
    c = (cuisine or "").lower()
    return "cafe_bakery" if any(k in c for k in CAFE_KEYWORDS) else "restaurant"


def _parse_date(raw) -> dt.date | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def active_state(last_inspection: dt.date | None,
                 closed_at_last_inspection: bool,
                 *, today: dt.date, stale_days: int = STALE_DAYS) -> tuple[bool, str]:
    """The ACTIVE verdict for one establishment, and why.

    Inactive iff (a) the most recent inspection is older than `stale_days`, or
    (b) the most recent inspection left it closed by DOHMH with no same-day
    re-open. Never-inspected (no real inspection date) is ACTIVE — see the
    module docstring. Returns (active, basis)."""
    if last_inspection is None:
        return True, "never_inspected"
    age = (today - last_inspection).days
    if age > stale_days:
        return False, f"stale_{age}d"
    if closed_at_last_inspection:
        return False, "closed_at_last_inspection"
    return True, f"inspected_{age}d_ago"


class DohmhAdapter(SourceAdapter):
    source_id = "nyc_dohmh_restaurants"

    def fetch(self, *, limit: int | None = None) -> Iterable[dict]:
        session = requests.Session()
        token = os.environ.get("SOCRATA_APP_TOKEN")
        headers = {"X-App-Token": token} if token else {}
        # inspection_date / action / grade / grade_date added for the ACTIVE
        # filter (D47). record_date is deliberately NOT selected: it is the
        # extract timestamp, identical on every row.
        select = ("camis,dba,cuisine_description,latitude,longitude,boro,"
                  "inspection_date,action,grade,grade_date")
        offset, seen = 0, 0
        while True:
            page = PAGE if limit is None else min(PAGE, limit - seen)
            if page <= 0:
                break
            params = {"$select": select, "$order": "camis",
                      "$limit": page, "$offset": offset}
            # Socrata read-times-out intermittently on wide 50k pages. Retry
            # with backoff, then RAISE -- a partial fetch that returned quietly
            # would look exactly like a shrinking city.
            for attempt in range(4):
                try:
                    resp = session.get(ENDPOINT, params=params,
                                       headers=headers, timeout=300)
                    resp.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt == 3:
                        raise
                    time.sleep(5 * 2 ** attempt)
            rows = resp.json()
            if not rows:
                break
            yield from rows
            seen += len(rows)
            offset += len(rows)
            if len(rows) < page or (limit is not None and seen >= limit):
                break

    def normalize(self, rows: Iterable[dict]) -> Iterator[POIRecord]:
        """One POIRecord per CAMIS. The identity fields come from the FIRST
        usable row for that CAMIS (unchanged behaviour); the activity fields
        are aggregated over ALL of its rows, because the feed is one row per
        violation and only the maximum inspection_date is meaningful."""
        today = dt.date.today()
        first: dict[str, dict] = {}          # camis -> the identity row
        last_insp: dict[str, dt.date] = {}   # camis -> max real inspection_date
        acts: dict[str, list[str]] = {}      # camis -> actions on that max date
        grade: dict[str, tuple[dt.date | None, str | None]] = {}
        n_rows: dict[str, int] = {}

        for r in rows:
            camis = r.get("camis")
            if not camis:
                continue
            n_rows[camis] = n_rows.get(camis, 0) + 1

            if camis not in first:
                lat, lon = r.get("latitude"), r.get("longitude")
                try:
                    latf, lonf = float(lat), float(lon)
                except (TypeError, ValueError):
                    latf = lonf = 0.0
                # DOHMH uses (0,0) for un-geocoded; keep looking for a usable row.
                if latf != 0.0 and lonf != 0.0:
                    first[camis] = {"row": r, "lat": latf, "lon": lonf}

            insp = _parse_date(r.get("inspection_date"))
            if insp is not None and insp != SENTINEL_DATE:
                prev = last_insp.get(camis)
                if prev is None or insp > prev:
                    last_insp[camis] = insp
                    acts[camis] = [r.get("action") or ""]
                elif insp == prev:
                    acts[camis].append(r.get("action") or "")

            gd = _parse_date(r.get("grade_date"))
            if gd is not None:
                prev_gd = grade.get(camis, (None, None))[0]
                if prev_gd is None or gd > prev_gd:
                    grade[camis] = (gd, r.get("grade"))

        for camis, ident in first.items():
            r = ident["row"]
            insp = last_insp.get(camis)
            same_day = [a.lower() for a in acts.get(camis, [])]
            closed = (any(m in a for a in same_day for m in _CLOSED_MARKERS)
                      and not any(_REOPEN_MARKER in a for a in same_day))
            active, basis = active_state(insp, closed, today=today)
            gd, g = grade.get(camis, (None, None))

            yield POIRecord(
                source_id=self.source_id,
                source_record_id=camis,
                category=classify(r.get("cuisine_description")),
                name=(r.get("dba") or "").strip().title() or None,
                lon=ident["lon"], lat=ident["lat"],
                observed_on=today,
                confidence=0.95,   # anchor source: high confidence
                attrs={
                    "cuisine": r.get("cuisine_description"),
                    "boro": r.get("boro"),
                    "last_inspection_date": insp.isoformat() if insp else None,
                    "closed_at_last_inspection": closed,
                    "grade": g,
                    "grade_date": gd.isoformat() if gd else None,
                    "n_inspection_rows": n_rows.get(camis, 0),
                    "active": active,
                    "active_basis": basis,
                },
            )
