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

THE SCHEMA CUTOFF IS 2021-02, AND PRE-2021 IS NOW READ -- IN ITS OWN ID COLUMN
---------------------------------------------------------------------------
Since 2021-02 the file is the Lyft schema: `ride_id, rideable_type, started_at,
ended_at, start_station_name, start_station_id, end_station_name,
end_station_id, start_lat, start_lng, end_lat, end_lng, member_casual`, with
station ids like `'5905.14'`.

The pre-2021 files are the legacy schema (`starttime`, `stoptime`,
`start station id`, `usertype`, ...) and their station ids are SMALL INTEGERS on
a completely different scheme -- legacy id `3002` and modern id `'5905.14'` are
not two spellings of one dock, and no published crosswalk maps them.

Phase 1 answered that by REFUSING every pre-2021 month, and the default window
started 2023-01. Both caps are gone (owner rule 2026-09-16: "never ever ever
limit data pulls"). WHAT DOES NOT CHANGE is the thing the refusal was protecting:
the two id spaces are still never fused. A legacy month is aggregated by exactly
the same SQL -- `lyft_bikeshare.legacy_projection_sql` presents the old columns
as the Lyft contract -- and then lands with its key in `station_id_legacy` and
`station_id` NULL (sql/044). `citibike_crosswalk.py` fills `station_id` in
afterwards, per row, only where NAME AND POSITION agree under a tiered,
one-to-one, 150 m-ceilinged rule that records a confidence for every row.

If the crosswalk matches under 90% of legacy docks, the legacy months are landed
ANYWAY with `station_id` NULL. A missing crosswalk row costs a join; a dropped
month costs the data.

The default ingest window is therefore 2013-06 -- the first month the bucket
publishes -- to the latest month it publishes.

THE SAME MONTH IS PUBLISHED TWICE IN TWO OF THE YEAR ARCHIVES
---------------------------------------------------------------------------
`2013-citibike-tripdata.zip` holds June..December 2013 as BOTH a quoted flat CSV
at the archive root and an unquoted chunked copy under a month-named folder;
`2018-citibike-tripdata.zip` holds April 2018 three times. Flattening every
member onto one directory -- which is what the phase-1 extractor did -- would
have counted those months twice, with no error anywhere.
`lyft_bikeshare.dedupe_members` resolves it: shallowest depth wins, and an
unsuffixed member beats the `_N` chunks beside it.

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
UNIONed with `HOLIDAYS_2021_2024` and `HOLIDAYS_2013_2020`; `assert_holidays_cover`
refuses a window that runs outside the union rather than quietly treating July
4th as a Tuesday. The 2013-2020 block is what makes the legacy era ingestable at
all, and it carries NO JUNETEENTH: that became a federal holiday on 2021-06-17,
and back-dating it would silently delete a real working weekday from seven years
of divisors.

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

import datetime as dt
import pathlib
import re

import pandas as pd

from loci.sources.cities import lyft_bikeshare as lyft
from loci.sources.cities.lyft_bikeshare import SYSTEMS

#: Re-exported, not redefined: `DAY_TYPES` and `DAYPART_NAMES` are in this
#: module's `__all__` and several callers read the vocabulary from here.
from loci.sources.cities.nyc.mta_ridership import (
    DAY_TYPES,
    DAYPART_NAMES,
)

# ---------------------------------------------------------------------------
# THIS MODULE IS NOW A NEW YORK *BINDING* (GTM-168 track P, D111)
#
# Every constant below used to be a literal here. They are now fields of
# `lyft_bikeshare.SYSTEMS["nyc_citibike"]`, and every function below delegates
# to the parameterised reader with that system bound. Nothing about the New
# York behaviour changed: `tests/test_lyft_systems.py` compares `month_sql`,
# `audit_sql` and `twin_sql` BYTE FOR BYTE against the committed pre-refactor
# module, because a 2021-02..2022-12 back-ingest was running from that file
# while this was written and the panel it writes must be one panel.
#
# The names, signatures and docstrings are kept because `citibike_od.py`,
# `model/address_bike.py`, `validation/bike_counts.py`, `cli.py` and the tests
# import them. Read the parameterised versions in
# `sources/cities/lyft_bikeshare.py`; read the WHY in the module docstring
# above, which is still a New York document.
# ---------------------------------------------------------------------------

#: The system this module binds. Everything else here reads from it.
SYSTEM = SYSTEMS["nyc_citibike"]

SOURCE_ID = SYSTEM.source_id

BUCKET_URL = SYSTEM.bucket_url
S3_NS = lyft.S3_NS

REPO_ROOT = lyft.REPO_ROOT
CACHE_DIR = SYSTEM.cache_dir

TIMEOUT = lyft.TIMEOUT
RETRIES = lyft.RETRIES

#: The first month published on the Lyft schema. Everything before this is the
#: legacy schema on a DIFFERENT station-id space -- READ since 2026-09-16, into
#: `station_id_legacy`, and never fused into `station_id`. See the docstring.
SCHEMA_CUTOFF = SYSTEM.schema_cutoff

#: The first month the bucket publishes at all, and the DEFAULT ingest start.
#: The 2013 year archive holds 201306..201312 and nothing earlier: the system
#: opened 2013-05-27 and those five days were never published as their own file.
LEGACY_START = SYSTEM.legacy_start
DEFAULT_START = LEGACY_START

#: The truncation floor for a LEGACY month. It cannot be MIN_TRIPS_PER_MONTH:
#: the smallest real legacy month is 2014-02 at ~169k trips, so the modern 300k
#: floor would refuse eight genuine winters as "truncated publications".
MIN_TRIPS_PER_MONTH_LEGACY = SYSTEM.min_trips_per_month_legacy

#: The 2021+ header and the legacy markers: SHARED across Lyft systems, which
#: is the fact that makes one reader possible at all.
LYFT_COLUMNS = lyft.LYFT_COLUMNS
LEGACY_MARKERS = lyft.LEGACY_MARKERS

#: Below this, a month's file is truncated rather than quiet: the smallest real
#: month in the 2021+ era is a January/February around 1.0-1.5M trips.
MIN_TRIPS_PER_MONTH = SYSTEM.min_trips_per_month

#: The New York system's own bounding box, applied to the docks that SURVIVE
#: the id filter below. -74.05 is west of every Bay Ridge dock and east of
#: every Jersey City one. It is a backstop, not the primary filter: Hoboken
#: sits at about -74.027, INSIDE this box and at the same longitude as Bay
#: Ridge, so a bounding box alone cannot separate the two systems. The id
#: pattern can.
NY_BBOX = SYSTEM.bbox

#: A New York public dock's id in the 2021+ scheme: digits, optionally a
#: decimal part, optionally ONE trailing underscore. See the module docstring
#: for the three classes of id this removes (JC*/HB*, SYS*/shops, pre-2021).
NY_STATION_ID = SYSTEM.station_id_re

#: The TRAILING UNDERSCORE IS THE SAME DOCK -- and the fusion carries its
#: evidence (`assert_underscore_twins_agree`). See the module docstring.
TWIN_MAX_M = SYSTEM.twin_max_m

#: Observed US federal holidays 2021-2024 that the transit module's list
#: (2025-2027) does not cover; federal, therefore shared with every system.
HOLIDAYS_2021_2024 = lyft.HOLIDAYS_2021_2024

#: The union actually used. ONE holiday vocabulary for transit and bike.
HOLIDAYS = lyft.HOLIDAYS
HOLIDAY_COVERAGE = lyft.HOLIDAY_COVERAGE

#: The error type. An ALIAS, not a subclass: every `except CitibikeError` and
#: every `pytest.raises(CitibikeError)` in the tree keeps catching exactly what
#: it caught before, including the raises that now happen inside the generic
#: reader.
CitibikeError = lyft.BikeshareError

MONTH_KEY = re.compile(SYSTEM.month_key_re)
YEAR_KEY = re.compile(SYSTEM.legacy_key_re)

#: Every column the aggregation reads, so a renamed column is a hard error at
#: the CSV reader rather than a silent NULL.
READ_TYPES = lyft.READ_TYPES

#: How many INTERIOR dates may carry no trip at all before the month is refused.
#: A day on which the whole system carried nobody is a real event -- 2026-02-23
#: is one, a storm -- but three of them in one month is a publication problem.
MAX_ZERO_DATES = SYSTEM.max_zero_dates

#: A whole Jersey City file read by mistake would be ~100% out-of-system. The
#: measured leak inside a NEW YORK file is ~200 rides a month out of ~4M, i.e.
#: 0.005%. 1% sits three orders of magnitude above the observed leak and two
#: below a wrong file, which is the gap a threshold wants to sit in.
MAX_OUT_OF_SYSTEM_SHARE = SYSTEM.max_out_of_system_share

MEM_MEMORY_LIMIT = lyft.MEM_MEMORY_LIMIT
STATION_MONTH_COLUMNS = lyft.STATION_MONTH_COLUMNS

#: The two columns sql/044 adds, and what the writer actually inserts.
#: STATION_MONTH_COLUMNS itself is UNCHANGED on purpose: it is the 034 grain and
#: `tests/test_lyft_systems.py` compares it against the committed module.
LEGACY_EXTRA_COLUMNS = lyft.LEGACY_EXTRA_COLUMNS
STATION_MONTH_WRITE_COLUMNS = lyft.STATION_MONTH_WRITE_COLUMNS


def era_of(year: int, month: int) -> str:
    """'lyft' | 'legacy' for one New York month. A property of the FILE."""
    return SYSTEM.era_of(year, month)


# ------------------------------------------------------------------ the bucket

def _http(url: str, *, method: str = "GET") -> bytes:
    return lyft._http(SYSTEM, url, method=method)


def list_bucket(*, refresh: bool = False) -> list[dict]:
    """[{key, size, last_modified}] for every object in the tripdata bucket.

    Cached to `data/raw/citibike/_bucket.xml`; the listing is the only place the
    set of published months exists, so it is kept beside the zips it describes.
    """
    return lyft.list_bucket(SYSTEM, refresh=refresh)


def month_range(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Inclusive (year, month) list, oldest first."""
    return lyft.month_range(start, end)


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
    return lyft.plan(SYSTEM, start, end, refresh=refresh)


def download(key: str, *, refresh: bool = False) -> pathlib.Path:
    """Fetch one bucket key into `data/raw/citibike/`, size-verified.

    The cache hit is conditioned on the bucket's own `Content-Length`, not on
    mere existence: a half-written zip from an interrupted run is exactly the
    shape of a month that quietly loses its last week.
    """
    return lyft.download(SYSTEM, key, refresh=refresh)


# ------------------------------------------------------------------ the schema

def classify_header(columns) -> str:
    """'lyft_2021' | 'legacy_pre2021' -- or RAISE on neither."""
    return lyft.classify_header(SYSTEM, columns)


def refuse_legacy(what: str) -> None:
    """The refusal text, kept for the systems that still need it.

    NEW YORK NO LONGER REFUSES ITS LEGACY ERA (owner rule 2026-09-16): the
    pre-2021 months are read into `station_id_legacy`. This function stays
    because it is the one place the ID-SPACE argument is written down, it is
    still what Chicago's unprobed quarterly files hit, and `citibike_od.py` and
    the tests import it by name. Calling it always raises.
    """
    lyft.refuse_legacy(SYSTEM, what)


def csv_members(zf) -> list[str]:
    """The trip CSVs inside a zip: no `__MACOSX`, no dotfiles, no JC members."""
    return lyft.csv_members(SYSTEM, zf)


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
    return lyft.extract_month(SYSTEM, zip_path, year, month, dest)


# --------------------------------------------------------------- the calendar

def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    return lyft.month_bounds(year, month)


def day_type_of_date(d: dt.date) -> str | None:
    """'weekday' | 'saturday' | 'sunday', or None for an excluded holiday.

    `dt.date.weekday()` is 0=Monday; the project's vocabulary (and Socrata's) is
    0=Sunday, so it is converted here rather than in five call sites.
    """
    return lyft.day_type_of_date(d, HOLIDAYS)


def days_by_type(year: int, month: int) -> dict[str, int]:
    """Non-holiday dates of each day type in the month -- the DIVISOR.

    From the calendar, never from the data: a dock that saw no Tuesday rides
    must not thereby get a higher daily average.
    """
    return lyft.days_by_type(year, month, HOLIDAYS)


def assert_holidays_cover(months: list[tuple[int, int]]) -> None:
    """Refuse a window outside the hand-maintained holiday list."""
    lyft.assert_holidays_cover(SYSTEM, months)


# ----------------------------------------------------------------- the SQL bits

def daypart_case_sql(ts: str) -> str:
    """A CASE that maps `ts`'s clock hour onto a daypart name.

    RENDERED from `mta_ridership.DAYPARTS`, never retyped: the bike dayparts and
    the subway dayparts must be the same five intervals or `loci validate-bike`
    is comparing two different clocks.
    """
    return lyft.daypart_case_sql(ts)


def day_type_case_sql(ts: str) -> str:
    """A CASE that maps `ts`'s date onto a day type. DuckDB's `dayofweek` is
    0=Sunday..6=Saturday, the same convention `mta_ridership.day_type_of` uses."""
    return lyft.day_type_case_sql(ts)


def holiday_predicate_sql(ts: str, year: int, month: int) -> str:
    """`AND <ts>::DATE NOT IN (...)` for this month's holidays -- or the EMPTY
    STRING when the month has none.

    The empty string is the whole point. `NOT IN (NULL)` is NULL for every row,
    which SQL treats as false, so a "no holidays this month" placeholder of
    `NULL` silently deletes the entire month. That is precisely the silent-zero
    failure this module refuses everywhere else, and it is one keystroke away.
    """
    return lyft.holiday_predicate_sql(ts, year, month, HOLIDAYS)


def is_ny_station_sql(col: str) -> str:
    """`col` is a New York PUBLIC dock id. See `NY_STATION_ID`."""
    return lyft.is_public_station_sql(SYSTEM, col)


def station_id_sql(col: str) -> str:
    """The canonical dock id: trimmed, with a trailing `_` REMOVED.

    The fusion is deliberate and evidenced -- see `TWIN_MAX_M`. It is applied
    here, at read time, so nothing downstream ever sees the two spellings.
    """
    return lyft.station_id_sql(SYSTEM, col)


def read_csv_sql(glob: str) -> str:
    return lyft.read_csv_sql(glob)


def trips_sql(glob: str, era: str = "lyft") -> str:
    """The relation the aggregations read, for either era.

    `era='lyft'` is byte-for-byte `read_csv_sql(glob)`; `era='legacy'` is the
    legacy file PRESENTED AS the Lyft contract, so there is one aggregation and
    not a second one that can drift. See `lyft_bikeshare.legacy_projection_sql`.
    """
    return lyft.trips_sql(glob, era)


def month_sql(glob: str, year: int, month: int, era: str = "lyft") -> str:
    """The ONE query that turns a month of trips into station-month cells.

    Starts and ends are aggregated SEPARATELY and FULL-OUTER-joined, because a
    dock can be all arrivals and no departures in a cell and an inner join would
    delete exactly that -- the destination signal this source exists to add.

    Both sides are restricted to the file's own month (see the module docstring
    on the end-of-month spill) and to non-holiday dates.
    """
    return lyft.month_sql(SYSTEM, glob, year, month, HOLIDAYS, era)


def twin_sql(glob: str, era: str = "lyft") -> str:
    """Raw (unfused) id, modal name and modal position per START dock.

    Feeds `assert_underscore_twins_agree`. It must read the id UNTRIMMED of its
    suffix -- the whole point is to compare `5303.06_` with `5303.06`.
    """
    return lyft.twin_sql(SYSTEM, glob, era)


def audit_sql(glob: str, year: int, month: int, era: str = "lyft") -> str:
    """The per-month facts the report must state, in one pass over the file."""
    return lyft.audit_sql(SYSTEM, glob, year, month, era)


def _as_date(v) -> dt.date:
    """pandas Timestamp | datetime | date | ISO string -> date."""
    return lyft._as_date(v)


def assert_month_complete(audit: dict, year: int, month: int,
                          min_trips: int | None = None,
                          era: str | None = None) -> None:
    """The month is whole: not truncated, and not missing a run of dates.

    A TRUNCATED file loses a contiguous SUFFIX and is refused (the calendar
    divisor would deflate every dock); an OUTAGE removes an INTERIOR date and is
    KEPT IN THE DIVISOR, because an average weekday in February 2026 really did
    include a day the system did not run and dropping days BECAUSE ridership was
    low is selecting on the outcome. Holidays are excluded and weather is not,
    precisely because the holiday list is a known, enumerable, recurring set
    fixed in advance. The full argument is in `lyft_bikeshare`.

    `min_trips` is a parameter only so a TEST can drive the real aggregation on
    a hand-built twenty-row month. Production never passes it.
    """
    lyft.assert_month_complete(SYSTEM, audit, year, month, min_trips, era)


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
    lyft.assert_out_of_system_bounded(SYSTEM, audit, year, month)


def assert_underscore_twins_agree(df: pd.DataFrame, tol_m: float = TWIN_MAX_M) -> dict:
    """The evidence behind fusing `5303.06_` into `5303.06`.

    Called on the RAW (unfused) name/coordinate pairs. Refuses the fusion if a
    twin's published name differs or the two points are more than `tol_m`
    apart: that would be two different docks, and merging them is the
    dedup-fuses-distinct-storefronts bug in a new costume.
    """
    return lyft.assert_underscore_twins_agree(SYSTEM, df, tol_m)


# ------------------------------------------------------------------ the ingest

def _mem(tmp_dir: pathlib.Path):
    return lyft.mem(tmp_dir)


def month_frame(csv_glob: str, year: int, month: int, tmp_dir: pathlib.Path,
                min_trips: int | None = None, era: str | None = None):
    """(station-month cell frame, audit dict) for ONE month of CSVs.

    Pure with respect to the warehouse: it reads files and returns a frame. The
    three assertions (complete month, plausible size, no Jersey City) run here,
    so nothing that fails them can reach a writer.
    """
    return lyft.month_frame(SYSTEM, csv_glob, year, month, tmp_dir, min_trips,
                            era)


def write_month(con, df, year: int, month: int, run_at: dt.datetime) -> int:
    """DELETE-then-INSERT one month. The month is the unit of idempotence.

    The DELETE is by MONTH and therefore covers both eras: a month belongs to
    exactly one of them, so re-ingesting 2016-03 can never leave half of it
    behind, and re-ingesting 2024-03 can never touch a legacy row.
    """
    first, _ = month_bounds(year, month)
    out = df.copy()
    out["ingested_at"] = run_at
    for c in LEGACY_EXTRA_COLUMNS:
        if c not in out.columns:
            out[c] = None
    con.execute("DELETE FROM staging.citibike_station_month WHERE month = ?",
                [first])
    con.register("_cb_month", out[STATION_MONTH_WRITE_COLUMNS])
    try:
        cols = ", ".join(STATION_MONTH_WRITE_COLUMNS)
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
    WHERE era = 'lyft'
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
    """staging.citibike_station, derived wholly from the LYFT rows of the month
    table.

    Name and position come from the dock's MOST RECENT ACTIVE month (see 034):
    the address measures are a present-day walk distance, so a dock that moved
    must be measured where it is now, not at the average of where it has been.

    `WHERE era = 'lyft'` IS DELIBERATE AND IS NOT TIMIDITY. The legacy era is
    landed in full, but this roster is the one every built measure reads, and
    two of them are defined on the 2021+ panel:

      * the address measures (034) pool the LATEST 12 MONTHS, which never
        touches 2013-2020, so a legacy row can only add noise to the roster's
        first_month;
      * `model/address_bike_growth.py` GATES on `first_month <= M-23`. Letting
        a crosswalked dock's first_month slide to 2013 would silently change
        which docks are eligible for a measure that is already built and
        published -- a different population wearing the same column name.

    The legacy roster lives in `staging.citibike_station_legacy` and is read
    explicitly by whoever wants it (`citibike_crosswalk.rebuild_legacy_roster`).
    """
    for stmt in ROSTER_SQL.strip().split(";\n"):
        if stmt.strip():
            con.execute(stmt)
    return con.execute("SELECT count(*) FROM staging.citibike_station").fetchone()[0]


def ingest(con, start: tuple[int, int] = DEFAULT_START,
           end: tuple[int, int] | None = None, *,
           workdir: pathlib.Path | None = None,
           refresh: bool = False, dry_run: bool = False,
           keep_csv: bool = False, skip_existing: bool = False,
           on_month=None) -> dict:
    """Download -> extract -> aggregate -> write, one calendar month at a time.

    THE DEFAULT WINDOW IS THE WHOLE FEED: 2013-06 (the first month the bucket
    publishes) to the latest month it publishes. The old default of 2023-01 and
    the 2021-02 refusal were both caps, and the owner's standing rule is that
    free sources are pulled in full.

    One month is the unit of work AND of idempotence: its CSVs are extracted,
    aggregated, written and DELETED before the next month is touched, so peak
    disk is one month (~4 GB uncompressed) rather than the ~90 GB the whole
    window would be.

    `skip_existing` leaves months already present in the table alone, which is
    what makes an interrupted run resumable without re-reading 32 GB.
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
            era = e.get("era") or era_of(y, m)
            df, audit = month_frame(str(scratch / "*.csv"), y, m, work, era=era)
            audit.update({"month": f"{y}-{m:02d}", "key": e["key"],
                          "era": era, "csv_members": len(files)})
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
                  x["month"] for x in months if x.get("dates_with_no_trip")),
              "legacy_months_ingested":
                  sum(1 for x in months
                      if "skipped" not in x and x.get("era") == "legacy"),
              "lyft_months_ingested":
                  sum(1 for x in months
                      if "skipped" not in x and x.get("era") == "lyft")}
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
    "DEFAULT_START",
    "HOLIDAYS",
    "LEGACY_EXTRA_COLUMNS",
    "LEGACY_START",
    "MIN_TRIPS_PER_MONTH_LEGACY",
    "NY_STATION_ID",
    "SCHEMA_CUTOFF",
    "SOURCE_ID",
    "STATION_MONTH_COLUMNS",
    "STATION_MONTH_WRITE_COLUMNS",
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
    "era_of",
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
    "trips_sql",
    "twin_sql",
    "write_month",
]
