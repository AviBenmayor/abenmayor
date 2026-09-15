"""Citi Bike trip data -> `staging.citibike_station_month` (GTM Citi Bike phase 1).

WHAT THIS IS FOR
---------------------------------------------------------------------------
`transit_entries_400m` is the only foot-traffic proxy Loci has, and D76 records
exactly what is wrong with it: it is ENTRIES, i.e. the tap-IN direction only,
so the evening ARRIVAL flow -- the one that buys a bag of groceries on the way
home -- is invisible; and it is zero for 65% of Brooklyn addresses, which makes
it a station on/off flag over most of the borough.

Citi Bike trip data is the one free, public, address-scale movement series that
fixes BOTH of those. It is two-directional by construction (every trip is a
start at one dock and an END at another, and the end is published), and its
2,236-station network covers a materially different footprint from the 424
subway complexes -- Bay Ridge, Greenpoint, Bed-Stuy, Red Hook all have docks
and no station within 400 m.

It is NOT a pedestrian count and must never be read as one. See CAVEATS.

NOT A POI ADAPTER, AND DELIBERATELY NOT A `SourceAdapter`
---------------------------------------------------------------------------
Same reasoning as `mta_ridership.py` and `ll84_laundry.py`: a dock is not an
establishment and a trip is not a category, so a `POIRecord` would have to lie
about both. This module is plain fetch/normalise functions with the same
fail-loud contract, consumed by `model/address_bike.py`.

THE FEED
---------------------------------------------------------------------------
    https://s3.amazonaws.com/tripdata/   (public bucket, no key, no auth)

One zip per calendar month from 2024-01 onward (`YYYYMM-citibike-tripdata.zip`)
and one per YEAR for 2013..2023 (`YYYY-citibike-tripdata.zip`, holding the
twelve monthly files). Each zip holds one or more `*-partN.csv` members, EACH
WITH ITS OWN HEADER ROW -- which is why every read here goes through DuckDB's
`read_csv` over a directory GLOB (it strips a header per file) and never through
`cat` or a single stdin stream (which would ingest three header rows as data).

JERSEY CITY IS NOT EXCLUDED BY FILE NAME, BECAUSE THAT IS NOT ENOUGH
---------------------------------------------------------------------------
`JC-*` keys are the Jersey City / Hoboken system and are never fetched -- but
the NEW YORK file still carries JC and HB docks, as the far end of a cross-river
trip. Measured: 2023-06 has eight JC docks and thirteen rides; 2026-04 has JC
and HB docks among its arrivals. A bounding box cannot separate them either,
because Hoboken sits at about -74.027, INSIDE any New York box and at the same
longitude as Bay Ridge.

So the filter is the ID PATTERN (`NY_STATION_ID`): a New York public dock is
digits, optionally a decimal part, optionally one trailing underscore. That one
rule also removes the operator's own SHOPS AND LOADING DOCKS (`SYS033` "Pier 40
X2", `SYS016` "Morgan Bike Mechanics", `Shop Morgan`, `MTL-LAB-BKN`), which are
where bikes are serviced rather than where a member takes one out, and which sit
on industrial blocks where phantom demand would be most misleading. Everything
excluded is COUNTED by class, and `assert_out_of_system_bounded` raises if the
excluded share exceeds 1% -- a leak stays a leak, a wrong file is refused.

THE TRAILING UNDERSCORE IS THE SAME DOCK, AND THE FUSION CARRIES ITS EVIDENCE
---------------------------------------------------------------------------
`5303.06_` publishes the same station NAME as `5303.06` and a coordinate 15 m
away: a valet or overflow corral beside its dock. Left unfused, one dock's
activity is split across two rows and the busier corner reads low. Fused
blindly, two genuinely different docks could be merged -- the
dedup-fuses-distinct-storefronts bug in a new costume. So the fusion is applied
(`station_id_sql`) and CHECKED (`assert_underscore_twins_agree`): a pair whose
names differ, or whose points are more than `TWIN_MAX_M` apart, raises instead
of merging.

THE SCHEMA CUTOFF IS 2021-02, AND PRE-2021 IS REFUSED RATHER THAN MAPPED
---------------------------------------------------------------------------
Since 2021-02 the file is the Lyft schema: `ride_id, rideable_type, started_at,
ended_at, start_station_name, start_station_id, end_station_name,
end_station_id, start_lat, start_lng, end_lat, end_lng, member_casual`, with
station ids like `'5905.14'`.

The pre-2021 files are the legacy schema (`starttime`, `stoptime`,
`start station id`, `usertype`, ...) and their station ids are SMALL INTEGERS on
a completely different scheme -- legacy id `3002` and modern id `'5905.14'` are
not two spellings of one dock, and no published crosswalk maps them. Mapping the
columns is easy; fusing the two ID SPACES is the double-count/false-gap bug this
project keeps getting bitten by, in its purest form: either one station becomes
two rows in the panel (a fake new dock, a fake gap before it) or two stations
collapse into one (a fake doubling). So `classify_header` NAMES the legacy
schema and `refuse_legacy` RAISES with that reason. The ingest window starts at
2021-02; everything Loci actually needs (2023-01 onward) is inside it.

DAY TYPES AND DAYPARTS ARE THE TRANSIT ONES, IMPORTED NOT RETYPED
---------------------------------------------------------------------------
`DAY_TYPES`, `DAYPARTS`, `day_type_of` and `daypart_of` all come from
`mta_ridership`. There is exactly one definition of "am_peak is 06-10" in this
codebase, and `daypart_case_sql()` RENDERS the SQL from that tuple rather than
restating it, so a future edit to the boundaries moves transit and bike
together or trips the partition assertion. That is what makes
`loci validate-bike` able to put a DOT count window, a subway daypart and a bike
daypart in one row.

Federal holidays are excluded by DATE, exactly as the transit profile excludes
them, and belong to NO day type. The list is `mta_ridership.HOLIDAYS` (2025-2027)
UNIONed with `HOLIDAYS_2021_2024` here; `assert_holidays_cover` refuses a window
that runs outside the union rather than quietly treating July 4th as a Tuesday.

TIMESTAMPS ARE NAIVE NEW YORK WALL CLOCK
---------------------------------------------------------------------------
`started_at`/`ended_at` carry no timezone and are local civil time. That is what
we want -- a daypart is a fact about the clock on the wall, not about UTC -- so
nothing is converted. The two DST days are the only wrinkle: the spring-forward
day has no 02:00 hour and the fall-back day has two 01:00 hours. Both sit inside
`early` (00-06), so no daypart boundary is crossed and no cell is distorted
beyond one hour of the year's quietest window.

STARTS, ENDS, AND THE MONTH BOUNDARY
---------------------------------------------------------------------------
A start is counted at `start_station_id` in the day type and daypart of
`started_at`. An end is counted at `end_station_id` in the day type and daypart
of `ENDED_at` -- the arrival is the event, and dating it by the departure would
smear every after-midnight arrival back into the previous evening, which is
precisely the cell the destination signal lives in.

The file is keyed on `started_at`, so a ride that departs 23:50 on the last day
of the month ARRIVES in the next month's first minutes but lives in this month's
file. Those end events are DROPPED (the month's own file is the unit of an
idempotent DELETE-then-INSERT, and letting them through would make a re-ingest
of March silently rewrite April) and COUNTED in the report as
`end_events_after_month_end`. Measured at ~0.01% of ends; the symmetric
spill-IN from the previous month is missing for the same reason, so the two
roughly cancel across a contiguous panel. It is a real, named, bounded loss, not
a silent one.

Rides with a blank `start_station_id` (or `end_station_id`) are dockless
e-bike events with no dock to attribute -- excluded from the station grain and
counted in the report, never silently folded onto a nearby station.

`days_in_cell` COMES FROM THE CALENDAR, NOT FROM THE DATA
---------------------------------------------------------------------------
The divisor for "per average weekday" is the number of non-holiday weekdays IN
THE MONTH, computed from the calendar and identical for every station. Counting
the dates a STATION was observed would turn a dock that saw no Tuesday rides
into a dock with a higher daily average -- the same ruling `mta_ridership`
records for its citywide day-count divisor. A dock installed mid-month therefore
reads LOW for that month, correctly: it was not there.

And because that divisor assumes the month is complete, `assert_month_complete`
RAISES if any calendar date of the month is absent from the file citywide. A
half-published month would otherwise halve every station's average with no
error anywhere.

FAIL LOUD
---------------------------------------------------------------------------
* a key whose downloaded size does not match the bucket's `Content-Length` RAISES;
* a zip with no CSV member RAISES;
* a header that is not the 2021+ schema RAISES, naming the legacy schema;
* a month missing a calendar date RAISES;
* a month whose trip count is < `MIN_TRIPS_PER_MONTH` RAISES (a truncated file);
* more than 1% of rows on non-New-York dock ids RAISES (a JC file was read
  as a New York month);
* an underscore-suffixed dock id that disagrees with its base id on name or
  position RAISES rather than being fused.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. THIS IS NOT A PEDESTRIAN COUNT. It counts people who chose a bike, had a
   membership or a card, and found a free dock. Citi Bike's rider base skews
   younger, higher-income, and male relative to the city, and the system's
   own DOCK PLACEMENT is the dominant term in any geographic comparison: a
   neighbourhood with no docks reads zero because Lyft and DOT have not built
   there, not because nobody walks there. Coverage is an operator's decision
   and it is correlated with income. Read a bike number as RELATIVE busyness
   where there are docks, never as a headcount and never as evidence of absence.
2. DOCK CAPACITY CENSORS THE COUNT. A full dock at 09:00 turns an arrival into
   an arrival somewhere else; an empty dock turns a departure into no trip.
   Both are invisible here, and both bite hardest exactly at the busiest
   station-hours, so the top of the distribution is compressed.
3. REBALANCING TRUCKS ARE NOT TRIPS AND ARE NOT IN THE FEED -- so a dock that
   is emptied by truck every morning shows starts it did not "cause", and the
   starts/ends asymmetry at a commuter dock is partly an operational artefact.
4. E-BIKES CHANGED THE GEOGRAPHY MID-PANEL. 72% of 2026-04 trips were electric.
   Electric bikes lengthened trips and pushed the network outward, so a
   2023-vs-2026 comparison at one station mixes a demand change with a fleet
   change. This is why the address measures use the LATEST 12 MONTHS and not
   the whole panel.
5. `member_casual` IS NOT RESIDENT/VISITOR. A member is anyone with a
   subscription, including a commuting student; a casual rider is anyone on a
   single ride or day pass, including a local without a subscription. The
   casual share reads high in tourist geography, which is a signal, but it is
   not a tourist count.
"""
from __future__ import annotations

import calendar
import datetime as dt
import io
import pathlib
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from loci.sources.cities.nyc.mta_ridership import (
    DAY_TYPES,
    DAYPART_NAMES,
    DAYPARTS,
    DOW_SATURDAY,
    DOW_SUNDAY,
)
from loci.sources.cities.nyc.mta_ridership import HOLIDAYS as HOLIDAYS_2025_2027

SOURCE_ID = "citibike_tripdata"

BUCKET_URL = "https://s3.amazonaws.com/tripdata/"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
CACHE_DIR = REPO_ROOT / "data" / "raw" / "citibike"

TIMEOUT = 600
RETRIES = 4

#: The first month published on the Lyft schema. Everything before this is the
#: legacy schema on a DIFFERENT station-id space and is refused, not mapped.
SCHEMA_CUTOFF = (2021, 2)

#: The 2021+ header, in the feed's own order. Compared as a SET (a future
#: reordering is harmless; a rename is not).
LYFT_COLUMNS = frozenset({
    "ride_id", "rideable_type", "started_at", "ended_at",
    "start_station_name", "start_station_id", "end_station_name",
    "end_station_id", "start_lat", "start_lng", "end_lat", "end_lng",
    "member_casual",
})
#: A few distinctive legacy names. Presence of any of these means a pre-2021
#: file, which is REFUSED with its reason rather than mapped.
LEGACY_MARKERS = frozenset({
    "starttime", "stoptime", "start station id", "end station id",
    "usertype", "birth year", "tripduration",
})

#: Below this, a month's file is truncated rather than quiet: the smallest real
#: month in the 2021+ era is a January/February around 1.0-1.5M trips.
MIN_TRIPS_PER_MONTH = 300_000

#: The New York system's own bounding box, applied to the docks that SURVIVE
#: the id filter below. -74.05 is west of every Bay Ridge dock and east of
#: every Jersey City one. It is a backstop, not the primary filter: Hoboken
#: sits at about -74.027, INSIDE this box and at the same longitude as Bay
#: Ridge, so a bounding box alone cannot separate the two systems. The id
#: pattern can.
NY_BBOX = {"lon_min": -74.05, "lon_max": -73.68, "lat_min": 40.5, "lat_max": 40.95}

#: A New York public dock's id in the 2021+ scheme: digits, optionally a
#: decimal part, optionally ONE trailing underscore. Measured on 2026-04 and
#: 2023-06, everything that does NOT match is one of three things, and all
#: three must go:
#:
#:   JC*/HB*   Jersey City and Hoboken docks. They appear in the NEW YORK file
#:             as the far end of a cross-river trip (~200 rides a month), so
#:             "never fetch the JC-* key" is NOT sufficient -- the leak is
#:             inside the NY file. They are a separate operator on a separate
#:             id space and a separate capital plan; a Hoboken dock inside a
#:             Manhattan address's 400 m walk is impossible anyway (there is no
#:             walk across the Hudson), but it would still inflate the dock
#:             roster and the citywide totals.
#:
#:   SYS*, "Shop Morgan", "MTL-LAB-BKN"
#:             OPERATIONAL locations: bike shops, loading docks, mechanics'
#:             bays, a test lab. They are where the operator services bikes,
#:             not where a member takes one out, and they sit on industrial
#:             blocks. Counting them would put phantom pedestrian demand on
#:             exactly the kind of block this project is trying to read
#:             correctly.
#:
#:   pre-2021 integer ids
#:             refused by `classify_header` long before this.
NY_STATION_ID = r"^[0-9]+(\.[0-9]+)?_?$"

#: The TRAILING UNDERSCORE IS THE SAME DOCK. `5303.06_` and `5303.06` publish
#: the SAME station name and coordinates 15 m apart -- a valet or overflow
#: corral beside the dock it belongs to. Measured 2026-04: three such pairs,
#: every one name-identical and under 20 m apart.
#:
#: This is the one place in this module where two ids are deliberately FUSED,
#: so it carries its own evidence test: `assert_underscore_twins_agree` refuses
#: the fusion if a pair's published names differ or the two points are more
#: than `TWIN_MAX_M` apart. Left unfused, one dock's activity is split across
#: two rows and the busier corner reads ~25% low; fused without the check, two
#: genuinely different docks could be merged. The check is what makes the fusion
#: an observation rather than an assumption.
TWIN_MAX_M = 60.0

#: Observed US federal holidays 2021-2024 that the transit module's list
#: (2025-2027) does not cover. Same convention: the OBSERVED date, which is
#: always Mon-Fri, so the exclusion touches the weekday mean only.
HOLIDAYS_2021_2024: frozenset[dt.date] = frozenset(
    dt.date(*d) for d in [
        (2021, 1, 1), (2021, 1, 18), (2021, 2, 15), (2021, 5, 31), (2021, 6, 18),
        (2021, 7, 5), (2021, 9, 6), (2021, 10, 11), (2021, 11, 11), (2021, 11, 25),
        (2021, 12, 24), (2021, 12, 31),
        (2022, 1, 17), (2022, 2, 21), (2022, 5, 30), (2022, 6, 20), (2022, 7, 4),
        (2022, 9, 5), (2022, 10, 10), (2022, 11, 11), (2022, 11, 24), (2022, 12, 26),
        (2023, 1, 2), (2023, 1, 16), (2023, 2, 20), (2023, 5, 29), (2023, 6, 19),
        (2023, 7, 4), (2023, 9, 4), (2023, 10, 9), (2023, 11, 10), (2023, 11, 23),
        (2023, 12, 25),
        (2024, 1, 1), (2024, 1, 15), (2024, 2, 19), (2024, 5, 27), (2024, 6, 19),
        (2024, 7, 4), (2024, 9, 2), (2024, 10, 14), (2024, 11, 11), (2024, 11, 28),
        (2024, 12, 25),
    ])

#: The union actually used. ONE holiday vocabulary for transit and bike.
HOLIDAYS: frozenset[dt.date] = HOLIDAYS_2021_2024 | HOLIDAYS_2025_2027
HOLIDAY_COVERAGE = (2021, 2027)


class CitibikeError(RuntimeError):
    """A fetch or a file that must not be mistaken for a quiet month."""


# ------------------------------------------------------------------ the bucket

def _http(url: str, *, method: str = "GET") -> bytes:
    last: object = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(
                url, method=method, headers={"User-Agent": "loci-citibike"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as exc:                     # pragma: no cover - network
            last = exc
            time.sleep(3 + 5 * attempt)
    raise CitibikeError(
        f"citibike: {url} failed after {RETRIES} attempts ({last}). Refusing to "
        f"continue -- a dropped month would read downstream as a stretch of the "
        f"city where nobody rode.")


def list_bucket(*, refresh: bool = False) -> list[dict]:
    """[{key, size, last_modified}] for every object in the tripdata bucket.

    Cached to `data/raw/citibike/_bucket.xml`; the listing is the only place the
    set of published months exists, so it is kept beside the zips it describes.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "_bucket.xml"
    if cache.exists() and not refresh:
        raw = cache.read_bytes()
    else:
        raw = _http(f"{BUCKET_URL}?list-type=2&max-keys=1000")
        cache.write_bytes(raw)
    root = ET.fromstring(raw)
    if root.findtext(f"{S3_NS}IsTruncated") == "true":   # pragma: no cover
        raise CitibikeError(
            "citibike: the bucket listing is TRUNCATED; paging is not implemented "
            "and a truncated listing would silently hide the newest months.")
    out = []
    for c in root.findall(f"{S3_NS}Contents"):
        key = c.findtext(f"{S3_NS}Key") or ""
        if not key.endswith(".zip"):
            continue
        out.append({"key": key,
                    "size": int(c.findtext(f"{S3_NS}Size") or 0),
                    "last_modified": (c.findtext(f"{S3_NS}LastModified") or "")[:10]})
    if not out:                                          # pragma: no cover
        raise CitibikeError("citibike: the bucket listing contains no zips.")
    return out


MONTH_KEY = re.compile(r"^(\d{4})(\d{2})-citibike-tripdata(?:\.csv)?\.zip$")
YEAR_KEY = re.compile(r"^(\d{4})-citibike-tripdata(?:\.csv)?\.zip$")


def month_range(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Inclusive (year, month) list, oldest first."""
    out, y, m = [], *start
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def plan(start: tuple[int, int], end: tuple[int, int] | None = None,
         *, refresh: bool = False) -> tuple[list[dict], dict]:
    """Which bucket keys cover [start, end], one entry per MONTH.

    A month is served either by its own monthly key or by the YEAR archive that
    contains it (2023 and earlier are published annually). `end=None` means "the
    latest month the bucket actually publishes", derived from the listing rather
    than from today's date -- the file for a month lands days into the next one.

    RAISES on a month before the schema cutoff, and on a month the bucket does
    not cover at all. A silently short window is a silently thin panel.
    """
    if start < SCHEMA_CUTOFF:
        refuse_legacy(f"{start[0]}-{start[1]:02d}")
    listing = {e["key"]: e for e in list_bucket(refresh=refresh)
               if not e["key"].startswith("JC-")}
    monthly = {}
    yearly = {}
    for key in listing:
        m = MONTH_KEY.match(key)
        if m:
            monthly[(int(m.group(1)), int(m.group(2)))] = key
            continue
        y = YEAR_KEY.match(key)
        if y:
            yearly[int(y.group(1))] = key
    if end is None:
        end = max(monthly) if monthly else start
    want = month_range(start, end)
    out, missing = [], []
    for ym in want:
        key = monthly.get(ym) or yearly.get(ym[0])
        if key is None:
            missing.append(f"{ym[0]}-{ym[1]:02d}")
            continue
        out.append({"year": ym[0], "month": ym[1], "key": key,
                    "size": listing[key]["size"],
                    "archive": "year" if key in yearly.values() and ym not in monthly
                               else "month"})
    if missing:
        raise CitibikeError(
            f"citibike: the bucket publishes no file for {missing}. Refusing to "
            f"ingest a window with a hole in it -- a missing month reads "
            f"downstream as a month nobody rode.")
    return out, {"start": f"{start[0]}-{start[1]:02d}",
                 "end": f"{end[0]}-{end[1]:02d}",
                 "months": len(out),
                 "keys": sorted({e["key"] for e in out}),
                 "bytes": sum({e["key"]: e["size"] for e in out}.values())}


def download(key: str, *, refresh: bool = False) -> pathlib.Path:
    """Fetch one bucket key into `data/raw/citibike/`, size-verified.

    The cache hit is conditioned on the bucket's own `Content-Length`, not on
    mere existence: a half-written zip from an interrupted run is exactly the
    shape of a month that quietly loses its last week.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / key
    expect = next((e["size"] for e in list_bucket() if e["key"] == key), None)
    if expect is None:                                   # pragma: no cover
        raise CitibikeError(f"citibike: {key} is not in the bucket listing.")
    if dest.exists() and not refresh and dest.stat().st_size == expect:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    data = _http(BUCKET_URL + key)
    tmp.write_bytes(data)
    if tmp.stat().st_size != expect:                     # pragma: no cover
        tmp.unlink(missing_ok=True)
        raise CitibikeError(
            f"citibike: {key} downloaded {len(data)} bytes, bucket says {expect}. "
            f"Refusing a partial month.")
    tmp.replace(dest)
    return dest


# ------------------------------------------------------------------ the schema

def classify_header(columns) -> str:
    """'lyft_2021' | 'legacy_pre2021' -- or RAISE on neither."""
    # BOM FIRST, then quotes: the first column of a UTF-8-BOM file is
    # `\ufeff"ride_id"`, and stripping quotes before the BOM leaves the quote in
    # place and the whole header unrecognised.
    cols = {str(c).strip().lstrip("\ufeff").strip('"').strip().lower()
            for c in columns}
    if LYFT_COLUMNS <= cols:
        return "lyft_2021"
    if cols & LEGACY_MARKERS:
        return "legacy_pre2021"
    raise CitibikeError(
        f"citibike: unrecognised header {sorted(cols)[:8]}... -- it is neither the "
        f"2021+ Lyft schema nor the legacy one. Re-derive the columns before "
        f"ingesting; a missing column normalises to NULL, which reads downstream "
        f"as a dock nobody used.")


def refuse_legacy(what: str) -> None:
    """The one place the pre-2021 refusal is stated."""
    raise CitibikeError(
        f"citibike: {what} is on the PRE-2021 schema. It is refused, not mapped: "
        f"its station ids are small integers on a different scheme from the 2021+ "
        f"ids (legacy '3002' is not modern '5905.14', and no published crosswalk "
        f"maps them), so joining the two panels would either split one dock into "
        f"two stations -- inventing a dock that opened in 2021-02 and a gap before "
        f"it -- or fuse two distinct docks. The ingest window starts "
        f"{SCHEMA_CUTOFF[0]}-{SCHEMA_CUTOFF[1]:02d}.")


def csv_members(zf: zipfile.ZipFile) -> list[str]:
    """The trip CSVs inside a zip: no `__MACOSX`, no dotfiles, no JC members."""
    out = []
    for n in zf.namelist():
        base = n.rsplit("/", 1)[-1]
        if n.startswith("__MACOSX/") or base.startswith(".") or n.endswith("/"):
            continue
        if base.upper().startswith("JC-"):
            continue
        if base.lower().endswith(".csv"):
            out.append(n)
        elif base.lower().endswith(".zip"):
            out.append(n)                                # nested (year archives)
    if not out:
        raise CitibikeError(
            f"citibike: {zf.filename} holds no CSV member "
            f"({zf.namelist()[:5]}). Refusing to ingest an empty month.")
    return out


def _month_of(name: str) -> tuple[int, int] | None:
    m = re.search(r"(20\d{2})[-_]?(0[1-9]|1[0-2])", name.rsplit("/", 1)[-1])
    return (int(m.group(1)), int(m.group(2))) if m else None


def extract_month(zip_path: pathlib.Path, year: int, month: int,
                  dest: pathlib.Path) -> list[pathlib.Path]:
    """Extract the CSV members for (year, month) into `dest`, flat.

    Handles both shapes: a monthly zip (every member belongs to the month) and a
    YEAR archive, whose members are twelve monthly files -- or twelve nested
    monthly ZIPS, which are opened in memory. Returns the written paths.

    Every member's header is classified, so a legacy file inside an archive is
    refused by name instead of being read as if its columns meant what the 2021
    columns mean.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written: list[pathlib.Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in csv_members(zf):
            base = name.rsplit("/", 1)[-1]
            if base.lower().endswith(".zip"):
                if _month_of(base) not in (None, (year, month)):
                    continue
                with zipfile.ZipFile(io.BytesIO(zf.read(name))) as inner:
                    for iname in csv_members(inner):
                        ibase = iname.rsplit("/", 1)[-1]
                        if _month_of(ibase) != (year, month):
                            continue
                        written.append(_write_member(inner, iname, dest, ibase))
                continue
            got = _month_of(base)
            if got is not None and got != (year, month):
                continue
            written.append(_write_member(zf, name, dest, base))
    if not written:
        raise CitibikeError(
            f"citibike: {zip_path.name} holds no member for "
            f"{year}-{month:02d}. Refusing to record an empty month.")
    return written


def _write_member(zf: zipfile.ZipFile, name: str, dest: pathlib.Path,
                  base: str) -> pathlib.Path:
    with zf.open(name) as fh:
        head = fh.readline().decode("utf-8-sig", "replace").rstrip("\r\n")
        kind = classify_header(head.split(","))
        if kind != "lyft_2021":
            refuse_legacy(f"{base} (header: {head[:60]}...)")
        out = dest / base
        with out.open("wb") as w:
            w.write(head.encode() + b"\n")
            while chunk := fh.read(8 << 20):
                w.write(chunk)
    return out


# --------------------------------------------------------------- the calendar

def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last)


def day_type_of_date(d: dt.date) -> str | None:
    """'weekday' | 'saturday' | 'sunday', or None for an excluded holiday.

    `dt.date.weekday()` is 0=Monday; the project's vocabulary (and Socrata's) is
    0=Sunday, so it is converted here rather than in five call sites.
    """
    if d in HOLIDAYS:
        return None
    dow = (d.weekday() + 1) % 7
    if dow == DOW_SUNDAY:
        return "sunday"
    if dow == DOW_SATURDAY:
        return "saturday"
    return "weekday"


def days_by_type(year: int, month: int) -> dict[str, int]:
    """Non-holiday dates of each day type in the month -- the DIVISOR.

    From the calendar, never from the data: a dock that saw no Tuesday rides
    must not thereby get a higher daily average.
    """
    first, last = month_bounds(year, month)
    out = dict.fromkeys(DAY_TYPES, 0)
    d = first
    while d <= last:
        t = day_type_of_date(d)
        if t:
            out[t] += 1
        d += dt.timedelta(days=1)
    return out


def assert_holidays_cover(months: list[tuple[int, int]]) -> None:
    """Refuse a window outside the hand-maintained holiday list."""
    lo, hi = HOLIDAY_COVERAGE
    bad = sorted({y for y, _ in months if not lo <= y <= hi})
    if bad:
        raise CitibikeError(
            f"citibike: the federal-holiday list covers {lo}-{hi}; the window "
            f"includes {bad}. Extend HOLIDAYS_2021_2024 (or mta_ridership.HOLIDAYS) "
            f"before ingesting -- otherwise July 4th is counted as a Tuesday and "
            f"every weekday average in that year is quietly ~1.5% low.")


# ----------------------------------------------------------------- the SQL bits

def daypart_case_sql(ts: str) -> str:
    """A CASE that maps `ts`'s clock hour onto a daypart name.

    RENDERED from `mta_ridership.DAYPARTS`, never retyped: the bike dayparts and
    the subway dayparts must be the same five intervals or `loci validate-bike`
    is comparing two different clocks.
    """
    arms = " ".join(
        f"WHEN hour({ts}) >= {a} AND hour({ts}) < {b} THEN '{name}'"
        for name, a, b in DAYPARTS)
    return f"CASE {arms} END"


def day_type_case_sql(ts: str) -> str:
    """A CASE that maps `ts`'s date onto a day type. DuckDB's `dayofweek` is
    0=Sunday..6=Saturday, the same convention `mta_ridership.day_type_of` uses."""
    return (f"CASE WHEN dayofweek({ts}) = {DOW_SUNDAY} THEN 'sunday' "
            f"WHEN dayofweek({ts}) = {DOW_SATURDAY} THEN 'saturday' "
            f"ELSE 'weekday' END")


def holiday_predicate_sql(ts: str, year: int, month: int) -> str:
    """`AND <ts>::DATE NOT IN (...)` for this month's holidays -- or the EMPTY
    STRING when the month has none.

    The empty string is the whole point. `NOT IN (NULL)` is NULL for every row,
    which SQL treats as false, so a "no holidays this month" placeholder of
    `NULL` silently deletes the entire month. That is precisely the silent-zero
    failure this module refuses everywhere else, and it is one keystroke away.
    """
    first, last = month_bounds(year, month)
    hol = sorted(h for h in HOLIDAYS if first <= h <= last)
    if not hol:
        return ""
    lst = ", ".join(f"DATE '{h.isoformat()}'" for h in hol)
    return f" AND {ts}::DATE NOT IN ({lst})"


#: Every column the aggregation reads, so a renamed column is a hard error at
#: the CSV reader rather than a silent NULL.
READ_TYPES = {
    "ride_id": "VARCHAR", "rideable_type": "VARCHAR",
    "started_at": "TIMESTAMP", "ended_at": "TIMESTAMP",
    "start_station_name": "VARCHAR", "start_station_id": "VARCHAR",
    "end_station_name": "VARCHAR", "end_station_id": "VARCHAR",
    "start_lat": "DOUBLE", "start_lng": "DOUBLE",
    "end_lat": "DOUBLE", "end_lng": "DOUBLE",
    "member_casual": "VARCHAR",
}


def is_ny_station_sql(col: str) -> str:
    """`col` is a New York PUBLIC dock id. See `NY_STATION_ID`."""
    return (f"{col} IS NOT NULL AND trim({col}) <> '' "
            f"AND regexp_matches(trim({col}), '{NY_STATION_ID}')")


def station_id_sql(col: str) -> str:
    """The canonical dock id: trimmed, with a trailing `_` REMOVED.

    The fusion is deliberate and evidenced -- see `TWIN_MAX_M`. It is applied
    here, at read time, so nothing downstream ever sees the two spellings.
    """
    return f"regexp_replace(trim({col}), '_+$', '')"


def read_csv_sql(glob: str) -> str:
    cols = ", ".join(f"'{k}': '{v}'" for k, v in READ_TYPES.items())
    return (f"read_csv('{glob}', header=true, columns={{{cols}}}, "
            f"ignore_errors=false, union_by_name=true)")


def month_sql(glob: str, year: int, month: int) -> str:
    """The ONE query that turns a month of trips into station-month cells.

    Starts and ends are aggregated SEPARATELY and FULL-OUTER-joined, because a
    dock can be all arrivals and no departures in a cell and an inner join would
    delete exactly that -- the destination signal this source exists to add.

    Both sides are restricted to the file's own month (see the module docstring
    on the end-of-month spill) and to non-holiday dates.
    """
    first, last = month_bounds(year, month)
    dp_s, dt_s = daypart_case_sql("started_at"), day_type_case_sql("started_at")
    dp_e, dt_e = daypart_case_sql("ended_at"), day_type_case_sql("ended_at")

    def in_month(ts: str) -> str:
        return (f"{ts}::DATE BETWEEN DATE '{first.isoformat()}' "
                f"AND DATE '{last.isoformat()}'"
                + holiday_predicate_sql(ts, year, month))

    sid_s, sid_e = station_id_sql("start_station_id"), station_id_sql("end_station_id")
    return f"""
    WITH trips AS (SELECT * FROM {read_csv_sql(glob)}),
    s AS (
        SELECT {sid_s}                  AS station_id,
               {dt_s}                   AS day_type,
               {dp_s}                   AS daypart,
               mode(trim(start_station_name)) AS station_name,
               mode(start_lng)          AS lon,
               mode(start_lat)          AS lat,
               count(*)                 AS starts,
               count(*) FILTER (member_casual = 'member') AS member_starts,
               count(*) FILTER (member_casual = 'casual') AS casual_starts
        FROM trips
        WHERE {is_ny_station_sql('start_station_id')}
          AND started_at IS NOT NULL
          AND start_lat IS NOT NULL AND start_lng IS NOT NULL
          AND {in_month('started_at')}
        GROUP BY 1, 2, 3
    ),
    e AS (
        SELECT {sid_e}                  AS station_id,
               {dt_e}                   AS day_type,
               {dp_e}                   AS daypart,
               mode(trim(end_station_name)) AS station_name,
               mode(end_lng)            AS lon,
               mode(end_lat)            AS lat,
               count(*)                 AS ends,
               count(*) FILTER (member_casual = 'member') AS member_ends,
               count(*) FILTER (member_casual = 'casual') AS casual_ends
        FROM trips
        WHERE {is_ny_station_sql('end_station_id')}
          AND ended_at IS NOT NULL
          AND end_lat IS NOT NULL AND end_lng IS NOT NULL
          AND {in_month('ended_at')}
        GROUP BY 1, 2, 3
    )
    SELECT COALESCE(s.station_id, e.station_id)   AS station_id,
           COALESCE(s.station_name, e.station_name) AS station_name,
           COALESCE(s.lon, e.lon)                 AS lon,
           COALESCE(s.lat, e.lat)                 AS lat,
           DATE '{first.isoformat()}'             AS month,
           COALESCE(s.day_type, e.day_type)       AS day_type,
           COALESCE(s.daypart, e.daypart)         AS daypart,
           COALESCE(s.starts, 0)                  AS starts,
           COALESCE(e.ends, 0)                    AS ends,
           COALESCE(s.member_starts, 0)           AS member_starts,
           COALESCE(s.casual_starts, 0)           AS casual_starts,
           COALESCE(e.member_ends, 0)             AS member_ends,
           COALESCE(e.casual_ends, 0)             AS casual_ends
    FROM s FULL OUTER JOIN e
      ON s.station_id = e.station_id
     AND s.day_type   = e.day_type
     AND s.daypart    = e.daypart
    """


def twin_sql(glob: str) -> str:
    """Raw (unfused) id, modal name and modal position per START dock.

    Feeds `assert_underscore_twins_agree`. It must read the id UNTRIMMED of its
    suffix -- the whole point is to compare `5303.06_` with `5303.06`.
    """
    return f"""
    SELECT trim(start_station_id)        AS station_id,
           mode(trim(start_station_name)) AS station_name,
           mode(start_lng)               AS lon,
           mode(start_lat)               AS lat
    FROM {read_csv_sql(glob)}
    WHERE {is_ny_station_sql('start_station_id')}
      AND start_lat IS NOT NULL AND start_lng IS NOT NULL
    GROUP BY 1
    """


def audit_sql(glob: str, year: int, month: int) -> str:
    """The per-month facts the report must state, in one pass over the file."""
    first, last = month_bounds(year, month)
    return f"""
    SELECT count(*)                                            AS rows_in_file,
           -- dates INSIDE the month, not dates in the file. The 2023 archive's
           -- January member carries 276 trips that started in December 2022, so
           -- a bare DISTINCT count reads 35 of 31 and would mask a missing day.
           count(DISTINCT started_at::DATE) FILTER (
               started_at::DATE BETWEEN DATE '{first.isoformat()}'
                                    AND DATE '{last.isoformat()}')
                                                               AS start_dates,
           min(started_at::DATE)                               AS first_date,
           max(started_at::DATE)                               AS last_date,
           -- the latest date INSIDE the month that carries a trip. The bare
           -- max() above can sit outside it (the 2023 archive's January member
           -- carries December departures), which is exactly the wrong number
           -- for the suffix test.
           max(started_at::DATE) FILTER (
               started_at::DATE BETWEEN DATE '{first.isoformat()}'
                                    AND DATE '{last.isoformat()}')
                                                               AS last_date_in_month,
           count(*) FILTER (start_station_id IS NULL OR trim(start_station_id) = '')
                                                               AS dockless_starts,
           count(*) FILTER (end_station_id IS NULL OR trim(end_station_id) = '')
                                                               AS dockless_ends,
           count(*) FILTER (started_at::DATE < DATE '{first.isoformat()}'
                         OR started_at::DATE > DATE '{last.isoformat()}')
                                                               AS starts_outside_month,
           count(*) FILTER (ended_at::DATE > DATE '{last.isoformat()}')
                                                               AS end_events_after_month_end,
           count(*) FILTER (member_casual = 'member')          AS member_trips,
           count(*) FILTER (member_casual = 'casual')          AS casual_trips,
           count(*) FILTER (rideable_type = 'electric_bike')   AS electric_trips,
           -- Rows whose dock id is NOT a New York public dock: the Jersey
           -- City/Hoboken leak and the operator's own shops and loading docks.
           -- Counted by class so the exclusion is auditable rather than a
           -- number that quietly shrinks.
           count(*) FILTER (start_station_id IS NOT NULL
                        AND trim(start_station_id) <> ''
                        AND NOT regexp_matches(trim(start_station_id), '{NY_STATION_ID}'))
                                                               AS out_of_system_starts,
           count(*) FILTER (end_station_id IS NOT NULL
                        AND trim(end_station_id) <> ''
                        AND NOT regexp_matches(trim(end_station_id), '{NY_STATION_ID}'))
                                                               AS out_of_system_ends,
           count(*) FILTER (regexp_matches(upper(COALESCE(trim(end_station_id), '')),
                                           '^(JC|HB)'))        AS jersey_city_ends,
           count(DISTINCT trim(end_station_id)) FILTER (
               trim(end_station_id) <> ''
               AND NOT regexp_matches(trim(end_station_id), '{NY_STATION_ID}'))
                                                               AS out_of_system_stations,
           -- the bounding box of the docks that SURVIVE the id filter
           min(start_lng) FILTER ({is_ny_station_sql('start_station_id')}) AS lon_min,
           max(start_lng) FILTER ({is_ny_station_sql('start_station_id')}) AS lon_max,
           min(start_lat) FILTER ({is_ny_station_sql('start_station_id')}) AS lat_min,
           max(start_lat) FILTER ({is_ny_station_sql('start_station_id')}) AS lat_max
    FROM {read_csv_sql(glob)}
    """


#: How many INTERIOR dates may carry no trip at all before the month is refused.
#: A day on which the whole system carried nobody is a real event -- 2026-02-23
#: is one, a storm, with 2026-02-22 at 19k and 2026-02-24 at 13k against a ~60k
#: February norm -- but three of them in one month is a publication problem.
MAX_ZERO_DATES = 2


def _as_date(v) -> dt.date:
    """pandas Timestamp | datetime | date | ISO string -> date."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if hasattr(v, "to_pydatetime"):                          # pandas Timestamp
        return v.to_pydatetime().date()
    return dt.date.fromisoformat(str(v)[:10])


def assert_month_complete(audit: dict, year: int, month: int,
                          min_trips: int | None = None) -> None:
    """The month is whole: not truncated, and not missing a run of dates.

    TRUNCATION VERSUS AN OUTAGE, AND HOW THEY ARE TOLD APART
    -----------------------------------------------------------------------
    Both look like "fewer dates than the calendar has", and they need opposite
    answers, so the distinction is made on SHAPE rather than on count:

      * a TRUNCATED file loses a contiguous SUFFIX -- the publisher's export
        stopped early -- so its last date is before the month's last date. That
        is refused: `days_in_cell` comes from the calendar, and dividing a
        three-week month by a four-week divisor deflates every dock by a
        quarter with no error anywhere.

      * an OUTAGE removes an INTERIOR date. 2026-02-23 is the measured case: a
        winter storm, with the 22nd collapsing to 19k rides and the 24th still
        at 13k against a ~60k norm. The system genuinely carried nobody. That
        date is KEPT IN THE DIVISOR, because an average weekday in February
        2026 really did include a day the system did not run, and removing it
        would be selecting on the outcome -- a rule that drops days BECAUSE
        ridership was low biases every average upward and makes months
        incomparable. Holidays are excluded and weather is not, precisely
        because the holiday list is a known, enumerable, recurring set fixed in
        advance, while "it snowed" is a property of the data.

    `min_trips` is a parameter only so a TEST can drive the real aggregation on
    a hand-built twenty-row month. Production never passes it.
    """
    first, last = month_bounds(year, month)
    expected = (last - first).days + 1
    floor = MIN_TRIPS_PER_MONTH if min_trips is None else int(min_trips)
    if audit["rows_in_file"] < floor:
        raise CitibikeError(
            f"citibike: {year}-{month:02d} has only {audit['rows_in_file']:,} trips "
            f"(floor {floor:,}). That is a truncated publication, not a "
            f"quiet month; ingesting it would deflate every station's average.")

    missing = expected - int(audit["start_dates"])
    audit["dates_with_no_trip"] = missing
    if missing <= 0:
        return

    # The suffix test. `last_date_in_month` is the latest date INSIDE the month
    # that carries a trip; if it is not the month's own last day, the tail is
    # gone and this is truncation.
    tail = audit.get("last_date_in_month")
    if tail is not None and _as_date(tail) < last:
        raise CitibikeError(
            f"citibike: {year}-{month:02d} stops at {_as_date(tail)}, before the "
            f"month ends on {last}. That is a TRUNCATED publication: "
            f"`days_in_cell` is taken from the calendar, so the missing tail "
            f"would silently divide a partial month by a full one.")
    if missing > MAX_ZERO_DATES:
        raise CitibikeError(
            f"citibike: {year}-{month:02d} has NO trip at all on {missing} of "
            f"{expected} calendar dates. One or two is a system outage (a storm); "
            f"{missing} is a publication problem, and every one of them is "
            f"currently being divided into the average as a day the docks were "
            f"open. Establish which before ingesting.")


#: A whole Jersey City file read by mistake would be ~100% out-of-system. The
#: measured leak inside a NEW YORK file is ~200 rides a month out of ~4M, i.e.
#: 0.005%. 1% sits three orders of magnitude above the observed leak and two
#: below a wrong file, which is the gap a threshold wants to sit in.
MAX_OUT_OF_SYSTEM_SHARE = 0.01


def assert_out_of_system_bounded(audit: dict, year: int, month: int) -> None:
    """The out-of-system rows are a LEAK, not a file mix-up.

    This used to be a hard "no dock west of the Hudson" test, and it was wrong
    in both directions. It fired on 2023-06 over EIGHT Jersey City docks and
    thirteen rides -- a real leak, correctly detected, but not a reason to
    refuse 3.45M good trips -- and it would have MISSED Hoboken entirely, which
    sits at about -74.027, inside any New York bounding box and at the same
    longitude as Bay Ridge. The id pattern does the separating now; this
    asserts only that the leak is small enough to be a leak.
    """
    rows = max(int(audit["rows_in_file"]), 1)
    share = max(int(audit["out_of_system_starts"]),
                int(audit["out_of_system_ends"])) / rows
    audit["out_of_system_share"] = share
    if share > MAX_OUT_OF_SYSTEM_SHARE:
        raise CitibikeError(
            f"citibike: {year}-{month:02d} has {share:.2%} of rows on dock ids "
            f"that are not New York public docks "
            f"({audit['out_of_system_stations']} distinct, "
            f"{audit['jersey_city_ends']:,} of them JC*/HB*). Above "
            f"{MAX_OUT_OF_SYSTEM_SHARE:.0%} that is not a cross-river leak, it is "
            f"the wrong FILE -- a JC-* key read as a New York month.")
    if audit["lon_min"] is None:                             # pragma: no cover
        raise CitibikeError(
            f"citibike: {year}-{month:02d} has no New York dock at all after the "
            f"id filter. That is an empty month, not a quiet one.")
    if (audit["lon_min"] < NY_BBOX["lon_min"] or audit["lon_max"] > NY_BBOX["lon_max"]
            or audit["lat_min"] < NY_BBOX["lat_min"]
            or audit["lat_max"] > NY_BBOX["lat_max"]):
        raise CitibikeError(
            f"citibike: {year}-{month:02d} keeps a dock outside the New York "
            f"bounding box (lon {audit['lon_min']:.4f}..{audit['lon_max']:.4f}, "
            f"lat {audit['lat_min']:.4f}..{audit['lat_max']:.4f}) even after the "
            f"id filter -- so a NUMERIC-id dock is in the wrong place. Either a "
            f"coordinate is corrupt or the id scheme has been reused across "
            f"systems; do not ingest until it is known which.")


def assert_underscore_twins_agree(df: pd.DataFrame, tol_m: float = TWIN_MAX_M) -> dict:
    """The evidence behind fusing `5303.06_` into `5303.06`.

    Called on the RAW (unfused) name/coordinate pairs. Refuses the fusion if a
    twin's published name differs or the two points are more than `tol_m`
    apart: that would be two different docks, and merging them is the
    dedup-fuses-distinct-storefronts bug in a new costume.
    """
    import numpy as np

    if df.empty:
        return {"pairs": 0}
    df = df.copy()
    df["base"] = df["station_id"].str.replace(r"_+$", "", regex=True)
    df["is_twin"] = df["station_id"].str.endswith("_")
    twins = df[df["is_twin"]].merge(
        df[~df["is_twin"]], on="base", suffixes=("_t", "_b"))
    if twins.empty:
        return {"pairs": 0}
    dy = (twins["lat_t"] - twins["lat_b"]) * 111_320.0
    dx = ((twins["lon_t"] - twins["lon_b"]) * 111_320.0
          * np.cos(np.radians(twins["lat_b"])))
    twins["dist_m"] = np.hypot(dx, dy)
    bad_name = twins[twins["station_name_t"].str.strip()
                     != twins["station_name_b"].str.strip()]
    bad_dist = twins[twins["dist_m"] > tol_m]
    if len(bad_name) or len(bad_dist):
        raise CitibikeError(
            f"citibike: {len(bad_name)} underscore-suffixed dock ids disagree with "
            f"their base id on NAME and {len(bad_dist)} are more than {tol_m:.0f} m "
            f"away (worst {twins['dist_m'].max():.0f} m). The trailing-underscore "
            f"fusion is evidenced on name AND position; without both it would be "
            f"merging two distinct docks into one and inventing a gap where the "
            f"second used to be. Investigate before ingesting: "
            f"{sorted(set(bad_name['station_id_t']) | set(bad_dist['station_id_t']))[:5]}")
    return {"pairs": int(len(twins)), "max_dist_m": float(twins["dist_m"].max())}


# ------------------------------------------------------------------ the ingest

#: The month aggregation runs in an IN-MEMORY DuckDB, not on the warehouse
#: connection. Two reasons, both operational: a 4 GB CSV scan must not hold the
#: warehouse's single writer lock for half a minute while another builder is
#: rebuilding analysis.address, and the aggregation must be runnable against a
#: read-only snapshot. Only the ~34,500-row result touches the warehouse.
#: Kept well under the machine's RAM on purpose: this runs alongside other
#: builders on the same laptop, and a scan that wins an out-of-memory race
#: takes their work with it. DuckDB spills to `temp_directory` instead.
MEM_MEMORY_LIMIT = "3GB"

STATION_MONTH_COLUMNS = [
    "station_id", "station_name", "lon", "lat", "month", "day_type", "daypart",
    "starts", "ends", "member_starts", "casual_starts", "member_ends",
    "casual_ends", "days_in_cell", "ingested_at",
]


def _mem(tmp_dir: pathlib.Path):
    import duckdb
    m = duckdb.connect()
    m.execute(f"SET memory_limit='{MEM_MEMORY_LIMIT}'")
    m.execute(f"SET temp_directory='{tmp_dir}'")
    return m


def month_frame(csv_glob: str, year: int, month: int, tmp_dir: pathlib.Path,
                min_trips: int | None = None):
    """(station-month cell frame, audit dict) for ONE month of CSVs.

    Pure with respect to the warehouse: it reads files and returns a frame. The
    three assertions (complete month, plausible size, no Jersey City) run here,
    so nothing that fails them can reach a writer.
    """
    mem = _mem(tmp_dir)
    try:
        audit = mem.execute(audit_sql(csv_glob, year, month)).fetchdf() \
                   .to_dict("records")[0]
        audit = {k: (v.item() if hasattr(v, "item") else v) for k, v in audit.items()}
        assert_month_complete(audit, year, month, min_trips)
        assert_out_of_system_bounded(audit, year, month)
        # The twin check runs on the RAW ids, BEFORE month_sql fuses
        # them -- afterwards the evidence for the fusion is gone.
        audit["underscore_twins"] = assert_underscore_twins_agree(
            mem.execute(twin_sql(csv_glob)).fetchdf())
        df = mem.execute(month_sql(csv_glob, year, month)).fetchdf()
    finally:
        mem.close()
    if df.empty:                                         # pragma: no cover
        raise CitibikeError(
            f"citibike: {year}-{month:02d} aggregated to zero station cells from "
            f"{audit['rows_in_file']:,} trips. Refusing to write an empty month.")
    days = days_by_type(year, month)
    df["days_in_cell"] = df["day_type"].map(days).astype("int16")
    unknown = df.loc[df["days_in_cell"].isna() if df["days_in_cell"].dtype.kind == "f"
                     else [], "day_type"]
    if len(unknown):                                     # pragma: no cover
        raise CitibikeError(f"citibike: unknown day types {sorted(set(unknown))}")
    audit["cells"] = int(len(df))
    audit["stations"] = int(df["station_id"].nunique())
    audit["starts"] = int(df["starts"].sum())
    audit["ends"] = int(df["ends"].sum())
    audit["days_by_type"] = days
    return df, audit


def write_month(con, df, year: int, month: int, run_at: dt.datetime) -> int:
    """DELETE-then-INSERT one month. The month is the unit of idempotence."""
    first, _ = month_bounds(year, month)
    out = df.copy()
    out["ingested_at"] = run_at
    con.execute("DELETE FROM staging.citibike_station_month WHERE month = ?",
                [first])
    con.register("_cb_month", out[STATION_MONTH_COLUMNS])
    try:
        cols = ", ".join(STATION_MONTH_COLUMNS)
        # Named column lists, never SELECT * -- D72 records this exact shape
        # silently mis-mapping two type-compatible columns when a new one landed.
        con.execute(f"INSERT INTO staging.citibike_station_month ({cols}) "
                    f"SELECT {cols} FROM _cb_month")
    finally:
        con.unregister("_cb_month")
    return len(out)


ROSTER_SQL = """
DELETE FROM staging.citibike_station;
INSERT INTO staging.citibike_station
    (station_id, name, lon, lat, first_month, last_month, months_active, ingested_at)
WITH m AS (
    SELECT station_id, month,
           any_value(station_name) AS name,
           any_value(lon) AS lon, any_value(lat) AS lat,
           sum(starts) + sum(ends) AS trips
    FROM staging.citibike_station_month
    GROUP BY 1, 2
), last_seen AS (
    SELECT station_id, max(month) AS last_month FROM m WHERE trips > 0 GROUP BY 1
)
SELECT m.station_id,
       any_value(m.name)  FILTER (m.month = l.last_month) AS name,
       any_value(m.lon)   FILTER (m.month = l.last_month) AS lon,
       any_value(m.lat)   FILTER (m.month = l.last_month) AS lat,
       min(m.month) FILTER (m.trips > 0)                  AS first_month,
       l.last_month,
       count(*) FILTER (m.trips > 0)                      AS months_active,
       now()::TIMESTAMP                                   AS ingested_at
FROM m JOIN last_seen l USING (station_id)
GROUP BY m.station_id, l.last_month
"""


def rebuild_roster(con) -> int:
    """staging.citibike_station, derived wholly from the month table.

    Name and position come from the dock's MOST RECENT ACTIVE month (see 034):
    the address measures are a present-day walk distance, so a dock that moved
    must be measured where it is now, not at the average of where it has been.
    """
    for stmt in ROSTER_SQL.strip().split(";\n"):
        if stmt.strip():
            con.execute(stmt)
    return con.execute("SELECT count(*) FROM staging.citibike_station").fetchone()[0]


def ingest(con, start: tuple[int, int] = (2023, 1),
           end: tuple[int, int] | None = None, *,
           workdir: pathlib.Path | None = None,
           refresh: bool = False, dry_run: bool = False,
           keep_csv: bool = False, skip_existing: bool = False,
           on_month=None) -> dict:
    """Download -> extract -> aggregate -> write, one calendar month at a time.

    One month is the unit of work AND of idempotence: its CSVs are extracted,
    aggregated, written and DELETED before the next month is touched, so peak
    disk is one month (~4 GB) rather than the ~25 GB the whole window would be.

    `skip_existing` leaves months already present in the table alone, which is
    what makes an interrupted run resumable without re-reading 20 GB.
    """
    import shutil

    months_plan, prep = plan(start, end, refresh=refresh)
    assert_holidays_cover([(e["year"], e["month"]) for e in months_plan])
    work = pathlib.Path(workdir) if workdir else (CACHE_DIR / "_work")
    work.mkdir(parents=True, exist_ok=True)
    run_at = dt.datetime.now()

    have: set[dt.date] = set()
    if skip_existing:
        have = {r[0] for r in con.execute(
            "SELECT DISTINCT month FROM staging.citibike_station_month").fetchall()}

    months, rows = [], 0
    for e in months_plan:
        y, m = e["year"], e["month"]
        first, _ = month_bounds(y, m)
        if first in have:
            months.append({"month": f"{y}-{m:02d}", "skipped": "already ingested"})
            continue
        zip_path = download(e["key"], refresh=False)
        scratch = work / f"{y}{m:02d}"
        if scratch.exists():
            shutil.rmtree(scratch)
        try:
            files = extract_month(zip_path, y, m, scratch)
            df, audit = month_frame(str(scratch / "*.csv"), y, m, work)
            audit.update({"month": f"{y}-{m:02d}", "key": e["key"],
                          "csv_members": len(files)})
            if not dry_run:
                rows += write_month(con, df, y, m, run_at)
            months.append(audit)
            if on_month:
                on_month(audit)
        finally:
            if scratch.exists() and not keep_csv:
                shutil.rmtree(scratch, ignore_errors=True)

    report = {**prep, "run_at": run_at.isoformat(timespec="seconds"),
              "rows_written": rows, "months_detail": months,
              "months_ingested": sum(1 for x in months if "skipped" not in x),
              "trips_in_files": sum(x.get("rows_in_file", 0) for x in months),
              "dockless_starts": sum(x.get("dockless_starts", 0) for x in months),
              "dockless_ends": sum(x.get("dockless_ends", 0) for x in months),
              "end_events_after_month_end":
                  sum(x.get("end_events_after_month_end", 0) for x in months),
              # Dates on which the whole system carried nobody -- a storm, not a
              # missing file (see assert_month_complete). Surfaced because they
              # ARE in the divisor: an average weekday in that month really did
              # include a day the docks were shut.
              "dates_with_no_trip":
                  sum(x.get("dates_with_no_trip", 0) for x in months),
              "months_with_a_zero_date": sorted(
                  x["month"] for x in months if x.get("dates_with_no_trip"))}
    if not dry_run:
        report["stations"] = rebuild_roster(con)
    return report


# -------------------------------------------------------------- the read-back

VALIDATION_SQL = """
-- Proves on the WAREHOUSE (not on the frames this run built):
--   1. every month has exactly 15 cells per station that appears in it, or
--      fewer ONLY where a dock genuinely saw no trip in that cell -- reported
--      as `station_months` vs `cells / 15` rather than asserted, because a dock
--      with zero arrivals at 03:00 legitimately has no row;
--   2. the panel is CONTIGUOUS: n_months equals the month span, so a silently
--      dropped month is visible as a gap;
--   3. starts and ends BALANCE citywide per month. Every trip is one start and
--      one end, both inside the New York system, so the two totals must agree
--      to within the dockless rides and the month-boundary spill -- a gross
--      imbalance means a station-id space problem or a dropped part file;
--   4. days_in_cell is constant within (month, day_type), which is what makes
--      it a calendar divisor rather than an observed one.
SELECT month,
       count(*)                                    AS cells,
       count(DISTINCT station_id)                  AS stations,
       sum(starts)                                 AS starts,
       sum(ends)                                   AS ends,
       round(100.0 * (sum(starts) - sum(ends)) / nullif(sum(starts), 0), 3)
                                                   AS start_end_gap_pct,
       sum(member_starts + casual_starts)          AS classified_starts,
       count(DISTINCT day_type || '/' || daypart)  AS distinct_cells,
       count(DISTINCT days_in_cell || '@' || day_type) AS divisor_variants,
       max(days_in_cell) FILTER (day_type = 'weekday') AS weekdays
FROM staging.citibike_station_month
GROUP BY ROLLUP(month)
ORDER BY month NULLS LAST
"""


__all__ = [
    "CACHE_DIR",
    "DAYPART_NAMES",
    "DAY_TYPES",
    "HOLIDAYS",
    "NY_STATION_ID",
    "SCHEMA_CUTOFF",
    "SOURCE_ID",
    "STATION_MONTH_COLUMNS",
    "VALIDATION_SQL",
    "CitibikeError",
    "assert_holidays_cover",
    "assert_month_complete",
    "assert_out_of_system_bounded",
    "assert_underscore_twins_agree",
    "audit_sql",
    "classify_header",
    "csv_members",
    "day_type_case_sql",
    "day_type_of_date",
    "daypart_case_sql",
    "days_by_type",
    "download",
    "extract_month",
    "ingest",
    "is_ny_station_sql",
    "list_bucket",
    "month_bounds",
    "month_frame",
    "month_range",
    "month_sql",
    "plan",
    "rebuild_roster",
    "refuse_legacy",
    "station_id_sql",
    "twin_sql",
    "write_month",
]
