"""MTA subway ENTRIES per station complex, split across entrances (GTM-146).

WHAT THIS IS FOR
---------------------------------------------------------------------------
`analysis.address.transit_entries_400m` -- the average weekday daily subway
entries reachable within 400 m NETWORK metres of an address. It is the
daytime/passer-by half of demand that `homes_400m` cannot see: a Gowanus
address with 900 homes within reach and a Manhattan address with 900 homes
within reach are the same number on the residential measure and are not
remotely the same retail location, because one of them is 80 m from a station
complex that puts 30,000 people on the sidewalk every weekday.

NOT A POI ADAPTER, AND DELIBERATELY NOT A `SourceAdapter`
---------------------------------------------------------------------------
`sources/base.SourceAdapter` normalises into `staging.poi`, whose unit is an
ESTABLISHMENT (one row, one category, one tier, a dedup identity). A station
entrance is not an establishment and subway entries are not a category, so a
POIRecord would have to lie about both. This module follows the shape the
project already uses for non-POI city sources -- `ll84_laundry.py`
("This is NOT a POI adapter"), `dob_permits.py`, `dcp_housing.py`: plain
fetch/normalise functions with the same fail-loud contract, consumed by a
`model/` builder rather than by `SourceAdapter.load`.

THE TWO FEEDS
---------------------------------------------------------------------------
    5wq4-mkjj   MTA Subway Hourly Ridership: Beginning 2025   (data.ny.gov)
    i9wp-a4ja   MTA Subway Entrances and Exits: 2024          (data.ny.gov)

`5wq4-mkjj` is the CURRENT feed. `wujg-7c2s` (registry `mta_subway_ridership`,
used by grid/mta.build_subway_ridership for the hex-grain 2024 annual total)
ends at 2024-12-31 and is not extended; the two are the same schema with
disjoint date coverage and must never be summed.

`ridership` IS ENTRIES. `transfers` is a separate column and is deliberately
NOT added: a transfer is a rider already counted at the complex where they
entered the system, so adding it double-counts the network -- the same ruling
grid/mta.py records for the 2020-2024 feed. `transit_mode` is pinned to
'subway': the feed also carries Staten Island Railway and the Roosevelt Island
tram, which are not what this column means (and SIR therefore contributes
nothing on Staten Island -- correct, not a miss).

THE WINDOW, AND WHY IT IS A MEAN AND NOT A SUM
---------------------------------------------------------------------------
`weekday_entries` returns entries per AVERAGE WEEKDAY: the sum of `ridership`
over every weekday in the window divided by the number of distinct weekday
DATES actually present in the window. A sum would make the measure depend on
how many months were pulled, which is a property of this file rather than of
the station.

Federal holidays that fall on a weekday are EXCLUDED (`HOLIDAYS`). July 4th
ridership at a Midtown complex is not a weekday observation, and the mean over
~65 days is small enough that two holidays move it. Excluding them is cheap;
the alternative is a number that is quietly 3% low in any window containing a
holiday. The exclusion is by DATE, so it is auditable, and `report["n_days"]`
states how many weekdays actually went into the divisor.

SNAPPING: ENTRANCES, NOT THE COMPLEX POINT
---------------------------------------------------------------------------
The ridership feed carries one lat/lon per complex, and at 400 m that point is
materially wrong for a large interchange -- Atlantic Av-Barclays Ctr has 21
entrances spread over 400 m of Flatbush Avenue, so an address 350 m from the
nearest stair is either in or out depending on which of the 21 the feed happens
to publish. So each complex's average-weekday entries are split EVENLY across
its entrances (`entry_allowed = 'YES'` only -- an exit-only stair is not a way
into the system and putting entries on it would place demand on the wrong
corner).

Evenly, NOT by entrance volume, because no public source publishes per-entrance
counts. This is an explicit modelling choice with a known failure mode: a
complex with one busy main entrance and four little-used side stairs has its
demand spread too thin, which UNDERSTATES the corner outside the main entrance
and OVERSTATES the side streets. It is still strictly better than putting 100%
of the complex on one arbitrary published point. The choice is stamped per
address in `transit_entries_snap` so a reader can see which convention produced
the number.

A complex with no entrance rows falls back to its own published point and is
counted in `report["complexes_without_entrances"]` -- never silently dropped,
because a dropped complex reads downstream as "no subway here", the exact
confident false negative this project exists to avoid.

FAIL LOUD
---------------------------------------------------------------------------
* a month that returns zero rows RAISES (a silent zero month would deflate
  every station's mean by a third);
* an entrances fetch that returns nothing RAISES;
* fewer than `MIN_MATCH_SHARE` of ridership complexes matching an entrance
  `complex_id` RAISES -- that is the ID-space divergence grid/mta.py guards
  against, and it would otherwise land as every complex quietly falling back to
  its centroid.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. ENTRIES ARE NOT FOOTFALL. They count people entering the system, which is
   overwhelmingly the morning-outbound direction at a residential complex. The
   evening arrival flow -- the one that buys a bag of groceries on the way home
   -- is not published per station at all; it is only visible as entries at the
   OTHER end of the trip. So this measure is, at a residential station, a proxy
   for the resident commuter base, and at a job-centre station a proxy for the
   evening exodus. It is not a turnstile-neutral pedestrian count. The DOT
   pedestrian-count validation (registry `nyc_dot_pedestrian_counts`) exists
   precisely to say how big that gap is.
2. OMNY/MetroCard undercount: fare evasion and unpaid entry are invisible, and
   both are spatially correlated with income.
3. The entrance file is a 2024 snapshot; entrances close for construction.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import pathlib
import time

import requests

SOURCE_ID = "mta_subway_ridership_2025"
ENTRANCES_SOURCE_ID = "mta_subway_entrances"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
CACHE_DIR = REPO_ROOT / "data" / "raw" / "mta"

RIDERSHIP_URL = "https://data.ny.gov/resource/5wq4-mkjj.json"
RIDERSHIP_DATASET_ID = "5wq4-mkjj"
ENTRANCES_URL = "https://data.ny.gov/resource/i9wp-a4ja.json"
ENTRANCES_DATASET_ID = "i9wp-a4ja"

TIMEOUT = 300
PAGE = 5_000                 # 424 complexes; one page is always enough
DEFAULT_MONTHS = 3           # "the latest 3 full months"

#: Below this share of ridership complexes matching an entrance complex_id,
#: refuse to build: the two feeds' ID spaces have diverged.
MIN_MATCH_SHARE = 0.90

#: Federal holidays 2025-2027 that fall Mon-Fri. Excluded from the weekday
#: mean -- see the module docstring. Extend when the window moves past 2027.
HOLIDAYS: frozenset[dt.date] = frozenset(
    dt.date(*d) for d in [
        (2025, 1, 1), (2025, 1, 20), (2025, 2, 17), (2025, 5, 26), (2025, 6, 19),
        (2025, 7, 4), (2025, 9, 1), (2025, 10, 13), (2025, 11, 11), (2025, 11, 27),
        (2025, 12, 25),
        (2026, 1, 1), (2026, 1, 19), (2026, 2, 16), (2026, 5, 25), (2026, 6, 19),
        (2026, 7, 3), (2026, 9, 7), (2026, 10, 12), (2026, 11, 11), (2026, 11, 26),
        (2026, 12, 25),
        (2027, 1, 1), (2027, 1, 18), (2027, 2, 15), (2027, 5, 31), (2027, 6, 18),
        (2027, 7, 5), (2027, 9, 6), (2027, 10, 11), (2027, 11, 11), (2027, 11, 25),
        (2027, 12, 24),
    ])


# --------------------------------------------------------------- the window

def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """[first, last] calendar dates of `year`-`month`, inclusive."""
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last)


def latest_full_months(asof: dt.date, n: int = DEFAULT_MONTHS) -> list[tuple[int, int]]:
    """The `n` most recent CALENDAR months that ended on or before `asof`,
    oldest first. `asof` is the feed's max timestamp, not today: a feed that
    stops on the 2nd of a month has that month INCOMPLETE, and averaging two
    days of it into a three-month window would be a silent partial."""
    y, m = asof.year, asof.month
    _, last = month_bounds(y, m)
    if asof < last:                 # the current month is not finished
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    out: list[tuple[int, int]] = []
    for _ in range(n):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


def weekday_dates(first: dt.date, last: dt.date,
                  holidays: frozenset[dt.date] = HOLIDAYS) -> list[dt.date]:
    """Mon-Fri dates in [first, last] that are not federal holidays."""
    out, d = [], first
    step = dt.timedelta(days=1)
    while d <= last:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += step
    return out


# ----------------------------------------------------------------- the pull

def _get(url: str, params: dict, *, cache: pathlib.Path | None,
         refresh: bool = False) -> list[dict]:
    """One Socrata GET with retry/backoff, cached to `cache` as raw JSON.

    Retries then RAISES. A partial or empty return that came back quietly would
    look exactly like a shrinking transit system.
    """
    if cache is not None and cache.exists() and not refresh:
        return json.loads(cache.read_text())
    token = os.environ.get("SOCRATA_APP_TOKEN")
    headers = {"X-App-Token": token} if token else {}
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(5 * 2 ** attempt)
    rows = resp.json()
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows))
    return rows


def feed_max_timestamp(refresh: bool = False) -> dt.date:
    """The latest `transit_timestamp` in 5wq4-mkjj, as a date. Drives the
    window so the pipeline follows the feed rather than the wall clock."""
    # Deliberately NOT cached: this is the probe that decides WHICH months the
    # window covers, and a cached answer would pin the window to the first run
    # forever while the per-month files beneath it looked perfectly fresh.
    rows = _get(RIDERSHIP_URL, {"$select": "max(transit_timestamp)"}, cache=None)
    if not rows or not rows[0].get("max_transit_timestamp"):
        raise RuntimeError(
            f"{RIDERSHIP_URL}: max(transit_timestamp) returned nothing -- the feed "
            f"is unreachable or has changed shape; refusing to guess a window.")
    return dt.date.fromisoformat(rows[0]["max_transit_timestamp"][:10])


def fetch_month(year: int, month: int, *, refresh: bool = False) -> list[dict]:
    """Server-side sum(ridership) and distinct-day count per complex for the
    WEEKDAYS of one calendar month, holidays excluded.

    Chunked by calendar month for the reason grid/mta.py records: a whole-year
    server-side aggregation on this feed times out. Holidays are excluded with
    an explicit NOT IN on the date, not with a client-side pass, so the row the
    server returns is already the number that goes in the divisor's numerator.
    """
    first, last = month_bounds(year, month)
    hol = [d for d in HOLIDAYS if first <= d <= last and d.weekday() < 5]
    where = [
        f"transit_timestamp >= '{first.isoformat()}T00:00:00'",
        f"transit_timestamp < '{(last + dt.timedelta(days=1)).isoformat()}T00:00:00'",
        "transit_mode = 'subway'",
        "date_extract_dow(transit_timestamp) between 1 and 5",   # Mon..Fri
    ]
    for d in hol:
        where.append(f"date_trunc_ymd(transit_timestamp) <> '{d.isoformat()}T00:00:00'")
    rows = _get(RIDERSHIP_URL, {
        "$select": ("station_complex_id, station_complex, "
                    "sum(ridership) as riders, "
                    "count(distinct date_trunc_ymd(transit_timestamp)) as n_days, "
                    "max(latitude) as latitude, max(longitude) as longitude"),
        "$where": " AND ".join(where),
        "$group": "station_complex_id, station_complex",
        "$limit": PAGE,
    }, cache=CACHE_DIR / f"ridership_weekday_{year}{month:02d}.json", refresh=refresh)
    if not rows:
        raise RuntimeError(
            f"{RIDERSHIP_URL}: no weekday subway ridership rows for {year}-{month:02d}. "
            f"A silent zero month would deflate every station's weekday mean; refusing "
            f"to write.")
    return rows


def weekday_entries(months: list[tuple[int, int]], *, refresh: bool = False
                    ) -> tuple[dict[str, dict], dict]:
    """{complex_id: {entries_per_weekday, name, lon, lat}}, and a report.

    Divisor = the number of distinct weekday DATES the server actually saw,
    summed over months. Using the calendar's weekday count instead would divide
    by days the feed may not carry and quietly deflate every station.
    """
    riders: dict[str, float] = {}
    names: dict[str, str] = {}
    pts: dict[str, tuple[float, float]] = {}
    n_days = 0
    per_month = []
    for (y, m) in months:
        rows = fetch_month(y, m, refresh=refresh)
        days = max(int(float(r["n_days"])) for r in rows)
        expected = len(weekday_dates(*month_bounds(y, m)))
        per_month.append({"year": y, "month": m, "n_days": days,
                          "expected_weekdays": expected, "complexes": len(rows)})
        n_days += days
        for r in rows:
            cid = str(r["station_complex_id"])
            riders[cid] = riders.get(cid, 0.0) + float(r["riders"])
            names.setdefault(cid, r.get("station_complex") or "")
            try:
                pts.setdefault(cid, (float(r["longitude"]), float(r["latitude"])))
            except (KeyError, TypeError, ValueError):
                pass
    if n_days <= 0:
        raise RuntimeError("weekday_entries: zero weekday dates in the window")
    out = {cid: {"entries_per_weekday": v / n_days,
                 "name": names.get(cid, ""),
                 "lon": pts.get(cid, (None, None))[0],
                 "lat": pts.get(cid, (None, None))[1]}
           for cid, v in riders.items()}
    report = {
        "dataset_id": RIDERSHIP_DATASET_ID,
        "months": [f"{y}-{m:02d}" for y, m in months],
        "window_start": month_bounds(*months[0])[0].isoformat(),
        "window_end": month_bounds(*months[-1])[1].isoformat(),
        "n_weekdays": n_days,
        "per_month": per_month,
        "complexes": len(out),
        "total_entries_per_weekday": sum(v["entries_per_weekday"] for v in out.values()),
    }
    return out, report


def fetch_entrances(*, refresh: bool = False) -> list[dict]:
    """Every row of i9wp-a4ja. RAISES on an empty return."""
    rows = _get(ENTRANCES_URL, {"$limit": 50_000},
                cache=CACHE_DIR / "entrances.json", refresh=refresh)
    if not rows:
        raise RuntimeError(
            f"{ENTRANCES_URL}: returned no rows. Falling back to complex centroids "
            f"silently would change the meaning of every transit measure; raise "
            f"instead and let the caller pass snap='complex' on purpose.")
    return rows


# --------------------------------------------------------- the weight points

def entry_points(entries: dict[str, dict], entrances: list[dict] | None,
                 *, min_match_share: float = MIN_MATCH_SHARE
                 ) -> tuple[list[tuple[str, float, float, float]], dict]:
    """[(complex_id, lon, lat, entries_per_weekday_share)] and a report.

    With `entrances`, each complex's entries are split EVENLY over its
    entry-allowed entrances; without them (or for a complex that has none), the
    whole complex lands on its published point. Every complex in `entries`
    appears in the output exactly once in total weight -- the sum of the shares
    is the complex's entries_per_weekday, never more and never less. Pure: no
    network, no database, so the split arithmetic is tested on fixtures.
    """
    by_complex: dict[str, list[tuple[float, float]]] = {}
    if entrances:
        for e in entrances:
            if (e.get("entry_allowed") or "").strip().upper() != "YES":
                continue
            cid = str(e.get("complex_id") or "").strip()
            if not cid:
                continue
            try:
                lon = float(e["entrance_longitude"])
                lat = float(e["entrance_latitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if lon == 0.0 or lat == 0.0:       # null island, not a location
                continue
            by_complex.setdefault(cid, []).append((lon, lat))

    matched = sum(1 for cid in entries if cid in by_complex)
    if entrances and matched < min_match_share * len(entries):
        raise RuntimeError(
            f"only {matched} of {len(entries)} ridership complexes matched an entrance "
            f"complex_id ({matched / max(len(entries), 1):.1%} < {min_match_share:.0%}) "
            f"-- 5wq4-mkjj.station_complex_id and i9wp-a4ja.complex_id have diverged; "
            f"do not write.")

    pts: list[tuple[str, float, float, float]] = []
    no_entrance: list[str] = []
    for cid, v in entries.items():
        w = float(v["entries_per_weekday"])
        doors = by_complex.get(cid) or []
        if doors:
            share = w / len(doors)
            pts.extend((cid, lon, lat, share) for lon, lat in doors)
        else:
            lon, lat = v.get("lon"), v.get("lat")
            if lon is None or lat is None:
                raise RuntimeError(
                    f"complex {cid} ({v.get('name')}) has neither an entrance nor a "
                    f"published point; dropping it would read as 'no subway here'.")
            no_entrance.append(cid)
            pts.append((cid, float(lon), float(lat), w))

    report = {
        "snap": "entrances" if entrances else "complex",
        "entrances_dataset_id": ENTRANCES_DATASET_ID if entrances else None,
        "complexes": len(entries),
        "complexes_with_entrances": matched,
        "complexes_without_entrances": len(no_entrance),
        "complexes_without_entrances_ids": sorted(no_entrance),
        "weight_points": len(pts),
        "total_weight": sum(p[3] for p in pts),
    }
    return pts, report


def build_entry_points(*, months: int = DEFAULT_MONTHS, asof: dt.date | None = None,
                       use_entrances: bool = True, refresh: bool = False
                       ) -> tuple[list[tuple[str, float, float, float]], dict]:
    """The one call model/address_access.py makes: fetch, window, split, report."""
    asof = asof or feed_max_timestamp(refresh=refresh)
    window = latest_full_months(asof, months)
    entries, rep = weekday_entries(window, refresh=refresh)
    ent = fetch_entrances(refresh=refresh) if use_entrances else None
    pts, rep2 = entry_points(entries, ent)
    # Conservation: the split must not create or destroy riders.
    tot_in = sum(v["entries_per_weekday"] for v in entries.values())
    if abs(rep2["total_weight"] - tot_in) > 1e-6 * max(tot_in, 1.0):
        raise RuntimeError(
            f"entrance split changed the total from {tot_in:,.1f} to "
            f"{rep2['total_weight']:,.1f} entries/weekday -- the even split is "
            f"double-counting or losing complexes.")
    return pts, {**rep, **rep2, "feed_max_date": asof.isoformat(),
                 "source_id": SOURCE_ID}
