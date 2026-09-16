"""Lyft-operated bikeshare trip files, PARAMETERISED BY SYSTEM (GTM-168, D111).

WHAT THIS MODULE IS, AND WHAT IT IS NOT
---------------------------------------------------------------------------
Phase 1 shipped `sources/cities/nyc/citibike.py`: a trip-file reader that turns
a month of Lyft-schema CSVs into `station x month x day_type x daypart` cells.
Every constant in it was a New York constant, so the claim "this reader is a
reader, not a New York artefact" was untested. This module is the test: the
bucket URL, the key regexes, the bounding box, the dock-id pattern, the sibling
system excluded by key prefix, the trailing-underscore fusion, the dockless-end
policy and every threshold become fields of a `System`, and NEW YORK IS ONE
ENTRY IN `SYSTEMS` (`nyc_citibike`) beside Chicago's (`chicago_divvy`).

`citibike.py` keeps its name, its docstring, its public functions and its exact
SQL: it is now a thin NEW YORK BINDING over the functions here. That is checked
byte-for-byte in `tests/test_lyft_systems.py` against the committed version,
because a back-ingest was running from the old file while this was written.

WHAT PORTABLE MEANS HERE (and what it does not)
---------------------------------------------------------------------------
Portable = THE TRIP-FILE READER AND THE STATION-MONTH GRAIN TRAVEL. A second
Lyft city's month lands as station-month rows with the same day types, the same
five dayparts, the same calendar divisor and the same fail-loud guards.

It does NOT mean Loci runs in that city. There is no address frame, no walk
graph, no PLUTO, no supply set outside New York, so there are no address
measures, no growth feature and no claim whatsoever about Chicago retail. See
docs/PORTABILITY.md.

THE THREE HAZARDS THAT ARE REAL, NOT HYPOTHETICAL
---------------------------------------------------------------------------
1. DOCKLESS ENDS ARE LEGAL IN CHICAGO AND NOT IN NEW YORK. Divvy 2025-06
   publishes 23.1% of trips with a BLANK `end_station_id` -- an e-bike locked
   to a rack, not a dock. New York's share is a rounding error. Both systems
   exclude those rows from the station grain (there is no dock to attribute
   them to) and COUNT them in the report; what differs is the GATE, which is
   therefore `max_dockless_end_share` per system and not a constant. A gate
   tuned on New York would refuse every Chicago month, and "drop them quietly"
   would hand a 23% hole to whoever reads the panel next.
2. THE DOCK-ID SPACE IS PER SYSTEM. New York's public docks are numeric
   (`5905.14`), Chicago's are `CHI00474`, and the pre-2020 Divvy quarterly
   files key on a station NAME. `station_id_re` and `station_id_kind` carry
   that; the legacy schema is REFUSED, never mapped, in both systems, for the
   reason `citibike.refuse_legacy` states.
3. THE SIBLING-SYSTEM LEAK IS A NEW YORK FACT. `JC-*` keys are Jersey City and
   the New York file still carries JC/HB docks as the far end of a cross-river
   trip. Chicago has no sibling in its bucket, so `key_exclude_prefix` and
   `foreign_system_re` are None there -- and the out-of-system share, which in
   New York is the "wrong file" alarm, is a looser bound in Chicago because
   nothing is expected to leak in at all.

WHAT IS *NOT* PARAMETERISED, DELIBERATELY
---------------------------------------------------------------------------
The day types, the five dayparts and the federal-holiday list are ONE
definition for every system (`mta_ridership.DAYPARTS` and friends). Federal
holidays are national, so they travel; a CITY holiday would not, and neither
system's weekday mean depends on one. If a system ever needs its own calendar
it becomes a `System` field -- it is not one today because inventing a second
daypart vocabulary is exactly how two "comparable" panels stop being
comparable.
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
from dataclasses import dataclass

import pandas as pd

from loci.sources.cities.nyc.mta_ridership import (
    DAY_TYPES,
    DAYPART_NAMES,
    DAYPARTS,
    DOW_SATURDAY,
    DOW_SUNDAY,
)
from loci.sources.cities.nyc.mta_ridership import HOLIDAYS as HOLIDAYS_2025_2027

__all__ = [
    "DAYPART_NAMES",
    "DAY_TYPES",
    "HOLIDAYS",
    "HOLIDAYS_2013_2020",
    "HOLIDAYS_2021_2024",
    "HOLIDAY_COVERAGE",
    "LEGACY_ALIASES",
    "LEGACY_CANONICAL",
    "LEGACY_EXTRA_COLUMNS",
    "LEGACY_MARKERS",
    "LEGACY_READ_TYPES",
    "LEGACY_TS_FORMATS",
    "LYFT_COLUMNS",
    "MAX_UNPARSED_TIMESTAMP_SHARE",
    "READ_TYPES",
    "STATION_MONTH_WRITE_COLUMNS",
    "SYSTEMS",
    "BikeshareError",
    "System",
    "assert_holidays_cover",
    "assert_legacy_parses",
    "assert_month_complete",
    "assert_out_of_system_bounded",
    "assert_underscore_twins_agree",
    "audit_sql",
    "classify_header",
    "csv_members",
    "day_type_case_sql",
    "day_type_of_date",
    "dedupe_members",
    "daypart_case_sql",
    "days_by_type",
    "download",
    "extract_month",
    "holiday_predicate_sql",
    "is_public_station_sql",
    "legacy_header_map",
    "legacy_parse_audit_sql",
    "legacy_projection_sql",
    "legacy_read_csv_sql",
    "list_bucket",
    "month_bounds",
    "month_frame",
    "month_range",
    "month_sql",
    "plan",
    "read_csv_sql",
    "refuse_legacy",
    "station_id_sql",
    "station_month_ddl",
    "trips_sql",
    "twin_sql",
]

S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

TIMEOUT = 600
RETRIES = 4

#: The 2021+ header, in the feed's own order. Compared as a SET (a future
#: reordering is harmless; a rename is not). Identical in every Lyft city --
#: this is the whole reason one reader can serve them.
LYFT_COLUMNS = frozenset({
    "ride_id", "rideable_type", "started_at", "ended_at",
    "start_station_name", "start_station_id", "end_station_name",
    "end_station_id", "start_lat", "start_lng", "end_lat", "end_lng",
    "member_casual",
})
#: A few distinctive legacy names. Presence of any of these means a pre-Lyft
#: file, which is REFUSED with its reason rather than mapped. The NYC and the
#: Divvy legacy schemas share most of these names.
LEGACY_MARKERS = frozenset({
    "starttime", "stoptime", "start station id", "end station id",
    "usertype", "birth year", "tripduration",
})

#: The LEGACY header, canonicalised. New York published this shape from
#: 2013-06 to 2021-01 in THREE spellings, all seen in the archives:
#:   * bare lowercase      `tripduration,starttime,...`     (2013-06..2016-12,
#:                                                           2018..2020)
#:   * quoted lowercase    `"tripduration","starttime",...` (2013 flat copies,
#:                                                           2018 flat copies)
#:   * Title Case + spaces `Trip Duration,Start Time,...`   (2017)
#: `LEGACY_ALIASES` folds all three onto the first, which is why the reader can
#: hand DuckDB a fixed `columns={...}` map for every legacy month.
LEGACY_CANONICAL = (
    "tripduration", "starttime", "stoptime",
    "start station id", "start station name",
    "start station latitude", "start station longitude",
    "end station id", "end station name",
    "end station latitude", "end station longitude",
    "bikeid", "usertype", "birth year", "gender",
)

#: spelling -> canonical legacy name. Keys are already lowercased, unquoted and
#: BOM-stripped by `_norm_col`.
LEGACY_ALIASES: dict[str, str] = {
    **{c: c for c in LEGACY_CANONICAL},
    "trip duration": "tripduration",
    "start time": "starttime",
    "stop time": "stoptime",
    "bike id": "bikeid",
    "user type": "usertype",
    "birthyear": "birth year",
}

#: How the legacy columns are READ. Everything that can be dirty is read as
#: VARCHAR and cast in `legacy_projection_sql`, deliberately:
#:   * the timestamps come in three formats (`2013-06-01 00:00:01`,
#:     `2019-12-01 00:00:05.5640` with FOUR fractional digits, and
#:     `9/1/2014 00:00:25` with no zero padding). A TIMESTAMP column type makes
#:     DuckDB refuse the whole file on the second one.
#:   * the station ids arrive as `434` in one copy of a month and `434.0` in
#:     another. Reading them as VARCHAR and normalising ONCE is the only way the
#:     two copies agree.
LEGACY_READ_TYPES = {
    "tripduration": "VARCHAR",
    "starttime": "VARCHAR", "stoptime": "VARCHAR",
    "start station id": "VARCHAR", "start station name": "VARCHAR",
    "start station latitude": "DOUBLE", "start station longitude": "DOUBLE",
    "end station id": "VARCHAR", "end station name": "VARCHAR",
    "end station latitude": "DOUBLE", "end station longitude": "DOUBLE",
    "bikeid": "VARCHAR", "usertype": "VARCHAR",
    "birth year": "VARCHAR", "gender": "VARCHAR",
}

#: The timestamp spellings, tried in order. The fractional part is stripped
#: before the attempt (see `legacy_projection_sql`), so `%f` never appears.
LEGACY_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M",
)

#: Above this share of unparseable `starttime`/`stoptime` values a legacy month
#: is REFUSED rather than landed with a hole: an unparsed timestamp falls out of
#: the month predicate and reads downstream as a quiet dock.
MAX_UNPARSED_TIMESTAMP_SHARE = 0.001

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

#: Observed US FEDERAL holidays 2021-2024 that the transit module's list
#: (2025-2027) does not cover. Federal, therefore national: the same dates are
#: excluded in Chicago and in New York. Same convention: the OBSERVED date,
#: which is always Mon-Fri, so the exclusion touches the weekday mean only.
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

#: Observed US FEDERAL holidays 2013-2020 -- the LEGACY era (GTM-168 track L,
#: owner rule 2026-09-16 "never ever ever limit data pulls"). Generated with the
#: same convention as the block above and verified Mon-Fri: the statutory date
#: OBSERVED, i.e. a Saturday holiday moves to the Friday before and a Sunday
#: holiday to the Monday after. NO JUNETEENTH before 2021 -- it became a federal
#: holiday on 2021-06-17, and back-dating it would silently remove a real
#: working weekday from seven years of divisors.
#:
#: This list is what makes 2013-06..2020-12 INGESTABLE AT ALL:
#: `assert_holidays_cover` refuses any window outside HOLIDAY_COVERAGE rather
#: than counting July 4th as a Tuesday.
HOLIDAYS_2013_2020: frozenset[dt.date] = frozenset(
    dt.date(*d) for d in [
        (2013, 1, 1), (2013, 1, 21), (2013, 2, 18), (2013, 5, 27), (2013, 7, 4),
        (2013, 9, 2), (2013, 10, 14), (2013, 11, 11), (2013, 11, 28), (2013, 12, 25),
        (2014, 1, 1), (2014, 1, 20), (2014, 2, 17), (2014, 5, 26), (2014, 7, 4),
        (2014, 9, 1), (2014, 10, 13), (2014, 11, 11), (2014, 11, 27), (2014, 12, 25),
        (2015, 1, 1), (2015, 1, 19), (2015, 2, 16), (2015, 5, 25), (2015, 7, 3),
        (2015, 9, 7), (2015, 10, 12), (2015, 11, 11), (2015, 11, 26), (2015, 12, 25),
        (2016, 1, 1), (2016, 1, 18), (2016, 2, 15), (2016, 5, 30), (2016, 7, 4),
        (2016, 9, 5), (2016, 10, 10), (2016, 11, 11), (2016, 11, 24), (2016, 12, 26),
        (2017, 1, 2), (2017, 1, 16), (2017, 2, 20), (2017, 5, 29), (2017, 7, 4),
        (2017, 9, 4), (2017, 10, 9), (2017, 11, 10), (2017, 11, 23), (2017, 12, 25),
        (2018, 1, 1), (2018, 1, 15), (2018, 2, 19), (2018, 5, 28), (2018, 7, 4),
        (2018, 9, 3), (2018, 10, 8), (2018, 11, 12), (2018, 11, 22), (2018, 12, 25),
        (2019, 1, 1), (2019, 1, 21), (2019, 2, 18), (2019, 5, 27), (2019, 7, 4),
        (2019, 9, 2), (2019, 10, 14), (2019, 11, 11), (2019, 11, 28), (2019, 12, 25),
        (2020, 1, 1), (2020, 1, 20), (2020, 2, 17), (2020, 5, 25), (2020, 7, 3),
        (2020, 9, 7), (2020, 10, 12), (2020, 11, 11), (2020, 11, 26), (2020, 12, 25),
    ])

#: The union actually used. ONE holiday vocabulary for transit and every bike
#: system. EXTENDING THIS BACKWARD CANNOT MOVE THE 2021+ PANEL: every date added
#: lies outside it, and `holiday_predicate_sql` renders only the dates inside the
#: month it is called for -- which is why `tests/test_lyft_systems.py` still
#: compares the 2023-06 and 2026-04 SQL byte for byte.
HOLIDAYS: frozenset[dt.date] = (HOLIDAYS_2013_2020 | HOLIDAYS_2021_2024
                                | HOLIDAYS_2025_2027)
HOLIDAY_COVERAGE = (2013, 2027)


class BikeshareError(RuntimeError):
    """A fetch or a file that must not be mistaken for a quiet month.

    `citibike.CitibikeError` IS this class (an alias, not a subclass), so every
    existing `except CitibikeError` and every `pytest.raises(CitibikeError)`
    keeps catching exactly what it caught before the refactor.
    """


@dataclass(frozen=True)
class System:
    """One Lyft-operated bikeshare system's facts. Nothing here is a default.

    Every field is something that DIFFERS between two cities and would
    otherwise be hard-coded in the reader. The thresholds are included on
    purpose: `max_out_of_system_share` and `max_dockless_end_share` are
    calibrated on a system's own measured behaviour, and a New-York-tuned gate
    applied to Chicago is a refusal of every good month.
    """

    #: Key in `SYSTEMS`, and the value written to provenance.
    system_id: str
    #: The registry source id this system's files belong to.
    source_id: str
    #: Prefix on every raised message. NYC's is 'citibike', so the phase-1
    #: error strings are unchanged.
    log_prefix: str
    #: Human label used in messages ("New York", "Chicago").
    label: str

    #: Public S3 bucket, listed with `?list-type=2`.
    bucket_url: str
    #: Directory under `data/raw/` holding the zips and the cached listing.
    cache_dirname: str

    #: `^(\\d{4})(\\d{2})-<system>-tripdata(\\.csv)?\\.zip$` -- ONE MONTH.
    month_key_re: str
    #: The pre-monthly archives. NYC publishes one zip per YEAR for 2013-2023;
    #: Divvy published one per QUARTER through 2020-Q1. A NYC year archive is
    #: usable (it holds monthly Lyft-schema members); a Divvy quarterly archive
    #: is the legacy schema and is refused, which is why the two systems differ
    #: in `legacy_keys_are_usable`.
    legacy_key_re: str
    #: True when a key matched by `legacy_key_re` can still SERVE a month.
    legacy_keys_are_usable: bool
    #: Bucket keys AND zip members starting with this are a DIFFERENT system in
    #: the same bucket (NYC's 'JC-' is Jersey City / Hoboken). None where the
    #: bucket holds one system.
    key_exclude_prefix: str | None

    #: The system's own bounding box, applied to the docks that SURVIVE the id
    #: filter. A backstop, never the primary filter.
    bbox: dict
    #: A PUBLIC dock's id in the Lyft-era scheme, as a DuckDB regex.
    station_id_re: str
    #: Which column carries the station key in the Lyft-era files: 'id' for
    #: both systems today. 'name' exists because the pre-2020 Divvy quarterly
    #: files key on the station NAME, and a reader that assumed 'id' would
    #: silently read NULL there.
    station_id_kind: str
    #: Suffix that marks a valet/overflow corral belonging to the dock whose id
    #: is the prefix ('_' in New York). None disables the fusion entirely --
    #: fusing ids that are not twins is the dedup-fuses-distinct-storefronts
    #: bug in a new costume.
    twin_suffix: str | None
    #: How far apart a twin may sit before the fusion is refused.
    twin_max_m: float

    #: 'exclude_and_report': a trip with a blank station id has no dock to
    #: attribute, so it leaves the station grain and is COUNTED in the report.
    dockless_end_policy: str
    #: Refuse the month above this share of blank end-station ids. None =
    #: report only. NYC is None because phase 1 shipped with no such gate and
    #: the running back-ingest depends on that; Chicago is None because
    #: dockless ends are a legitimate 23% of the system, not a defect. The
    #: field exists so the number is a SYSTEM's, never a constant.
    max_dockless_end_share: float | None
    #: Refuse the month above this share of rows on ids that are not public
    #: docks of this system.
    max_out_of_system_share: float
    #: Ids counted separately as the known sibling system ('^(JC|HB)'), the
    #: audit column they land in, and how they are named in a message.
    foreign_system_re: str | None
    foreign_ends_alias: str
    foreign_label: str
    #: The comment block that annotates the out-of-system counters INSIDE the
    #: audit SQL. It is a field and not a literal because the SQL text is
    #: compared byte-for-byte against the committed NYC version, and because
    #: "the Jersey City/Hoboken leak" is a sentence about New York.
    foreign_note: str

    #: Below this a month's file is truncated rather than quiet.
    min_trips_per_month: int
    #: How many INTERIOR dates may carry no trip at all before the month is
    #: refused as a publication problem rather than an outage.
    max_zero_dates: int
    #: The first month published on the Lyft schema. Everything before it is
    #: the LEGACY schema: readable only where `legacy_schema_readable`, refused
    #: otherwise.
    schema_cutoff: tuple[int, int]

    # ---------------------------------------------------- the legacy era
    # GTM-168 track L, owner rule 2026-09-16 ("never ever ever limit data
    # pulls"). New York's pre-2021 months are no longer refused; they are landed
    # with their LEGACY station id in its own column. See `legacy_projection_sql`
    # and the crosswalk in `sources/cities/nyc/citibike.py`.

    #: True when this system's pre-cutoff files can be mapped onto the Lyft
    #: contract. New York: yes -- the legacy schema is a known, stable
    #: 15-column shape. Chicago: NO -- the pre-2020 Divvy files are QUARTERLY,
    #: keyed on a station NAME, and nobody has probed them; a `True` here would
    #: be a guess wearing a parameter's clothes.
    legacy_schema_readable: bool = False
    #: The first month the system ever published. `None` where the legacy era is
    #: not readable.
    legacy_start: tuple[int, int] | None = None
    #: The truncation floor for a LEGACY month. It cannot be
    #: `min_trips_per_month`: New York's smallest real legacy month is February
    #: 2014 at ~169k trips, well under the 300k floor the 2021+ panel uses, so
    #: the modern floor would refuse eight genuine winters.
    min_trips_per_month_legacy: int | None = None

    @property
    def cache_dir(self) -> pathlib.Path:
        return REPO_ROOT / "data" / "raw" / self.cache_dirname

    def station_col(self, side: str) -> str:
        """'start'|'end' -> the column carrying this system's station key."""
        kind = "id" if self.station_id_kind == "id" else "name"
        return f"{side}_station_{kind}"

    def era_of(self, year: int, month: int) -> str:
        """'lyft' | 'legacy' for one month of THIS system.

        The era is a property of the FILE's schema, not of a preference: it
        decides which header is expected, which column map DuckDB is handed and
        which truncation floor applies.
        """
        return "lyft" if (year, month) >= self.schema_cutoff else "legacy"

    def first_month(self) -> tuple[int, int]:
        """The earliest month this system can ingest. The LEGACY start where the
        legacy era is readable, the schema cutoff where it is not."""
        if self.legacy_schema_readable and self.legacy_start:
            return self.legacy_start
        return self.schema_cutoff

    def min_trips(self, era: str) -> int:
        if era == "legacy" and self.min_trips_per_month_legacy is not None:
            return self.min_trips_per_month_legacy
        return self.min_trips_per_month


SYSTEMS: dict[str, System] = {
    # ------------------------------------------------------------ New York
    # Phase 1's constants, moved verbatim. Changing ANY of these changes the
    # SQL the running panel was built from.
    "nyc_citibike": System(
        system_id="nyc_citibike",
        source_id="citibike_tripdata",
        log_prefix="citibike",
        label="New York",
        bucket_url="https://s3.amazonaws.com/tripdata/",
        cache_dirname="citibike",
        month_key_re=r"^(\d{4})(\d{2})-citibike-tripdata(?:\.csv)?\.zip$",
        legacy_key_re=r"^(\d{4})-citibike-tripdata(?:\.csv)?\.zip$",
        legacy_keys_are_usable=True,      # the YEAR archive holds monthly members
        key_exclude_prefix="JC-",         # Jersey City / Hoboken
        bbox={"lon_min": -74.05, "lon_max": -73.68,
              "lat_min": 40.5, "lat_max": 40.95},
        station_id_re=r"^[0-9]+(\.[0-9]+)?_?$",
        station_id_kind="id",
        twin_suffix="_",
        twin_max_m=60.0,
        dockless_end_policy="exclude_and_report",
        max_dockless_end_share=None,      # report only; measured well under 1%
        max_out_of_system_share=0.01,
        foreign_system_re="^(JC|HB)",
        foreign_ends_alias="jersey_city_ends",
        foreign_label="JC*/HB*",
        foreign_note=(
            "           -- Rows whose dock id is NOT a New York public dock: the Jersey\n"
            "           -- City/Hoboken leak and the operator's own shops and loading docks.\n"
            "           -- Counted by class so the exclusion is auditable rather than a\n"
            "           -- number that quietly shrinks."),
        min_trips_per_month=300_000,
        max_zero_dates=2,
        schema_cutoff=(2021, 2),
        # THE LEGACY ERA IS READ, NOT REFUSED (owner rule 2026-09-16).
        # 2013-06 is the first month in the bucket: the 2013 year archive holds
        # 201306..201312 and nothing earlier (the system opened 2013-05-27 and
        # those five days were never published as their own file).
        legacy_schema_readable=True,
        legacy_start=(2013, 6),
        # Measured floor: the smallest real legacy month is 2014-02 at ~169k
        # trips (2014-01 ~190k, 2013-12 ~300k). 50k sits three times below the
        # smallest real month and far above a truncated export.
        min_trips_per_month_legacy=50_000,
    ),
    # -------------------------------------------------------------- Chicago
    # Measured on 202506-divvy-tripdata.zip, 2026-09-15: 678,904 trips, 1,376
    # docks, every non-blank id of the form CHI00474, lat 41.649..42.070, lon
    # -87.890..-87.528, and 23.1% of trips ending nowhere at all.
    "chicago_divvy": System(
        system_id="chicago_divvy",
        source_id="divvy_tripdata",
        log_prefix="divvy",
        label="Chicago",
        bucket_url="https://divvy-tripdata.s3.amazonaws.com/",
        cache_dirname="divvy",
        month_key_re=r"^(\d{4})(\d{2})-divvy-tripdata(?:\.csv)?\.zip$",
        # Divvy_Trips_2019_Q1.zip, Divvy_Trips_2015-Q1Q2.zip,
        # Divvy_Stations_Trips_2014_Q3Q4.zip -- ALL legacy schema, all refused.
        legacy_key_re=r"^Divvy_(?:Stations_)?Trips_(\d{4})[-_]Q[1-4](?:Q[1-4])?\.zip$",
        legacy_keys_are_usable=False,     # quarterly AND pre-Lyft: refused
        key_exclude_prefix=None,          # one system in this bucket
        bbox={"lon_min": -88.05, "lon_max": -87.40,
              "lat_min": 41.55, "lat_max": 42.20},
        # Lyft-era Divvy ids are CHI00474 (2025+) and TA1307000039 / 13022
        # (2020-2024): alphanumeric, no spaces. The operator's own test and
        # warehouse entries ("Hubbard Bike-checking (LBS-WH-TEST)", "Base -
        # 2132 W Hubbard Warehouse", "DIVVY CASSETTE REPAIR MOBILE STATION")
        # carry spaces or punctuation and are excluded by that alone.
        station_id_re=r"^[A-Za-z0-9]+$",
        station_id_kind="id",
        twin_suffix=None,                 # no valet-corral twins in Chicago
        twin_max_m=60.0,
        dockless_end_policy="exclude_and_report",
        # NOT a gate. 23.1% of Divvy 2025-06 trips end off-dock; New York's
        # 1%-shaped intuition is simply wrong about this system.
        max_dockless_end_share=None,
        # Looser than NYC's 1%: nothing is expected to leak into this bucket at
        # all, so this is a "the id scheme changed under us" alarm, not a
        # "wrong file" one.
        max_out_of_system_share=0.05,
        foreign_system_re=None,
        foreign_ends_alias="foreign_system_ends",
        foreign_label="another system's",
        foreign_note=(
            "           -- Rows whose dock id is NOT a Chicago public dock: the operator's\n"
            "           -- own test rigs, charging stations and warehouse racks. Divvy has\n"
            "           -- no sibling system in this bucket, so there is no cross-river leak\n"
            "           -- to count -- which is why the foreign counter is a constant 0 and\n"
            "           -- not a filter pretending to look for one."),
        # 2026-01 is the smallest recent month at ~150k trips; a February that
        # halves would still clear this, a truncated file would not.
        min_trips_per_month=50_000,
        max_zero_dates=2,
        # Divvy's first Lyft-schema monthly key. Everything before is the
        # quarterly legacy schema on a different id space.
        schema_cutoff=(2020, 4),
    ),
}


def get(system_id: str) -> System:
    try:
        return SYSTEMS[system_id]
    except KeyError:
        raise BikeshareError(
            f"lyft_bikeshare: unknown system {system_id!r}; known systems are "
            f"{sorted(SYSTEMS)}. Add a SYSTEMS entry rather than passing a URL "
            f"-- every threshold in this reader is a per-system number.") from None


# ------------------------------------------------------------------ the bucket

def _http(sys: System, url: str, *, method: str = "GET") -> bytes:
    last: object = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(
                url, method=method, headers={"User-Agent": f"loci-{sys.log_prefix}"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as exc:                     # pragma: no cover - network
            last = exc
            time.sleep(3 + 5 * attempt)
    raise BikeshareError(
        f"{sys.log_prefix}: {url} failed after {RETRIES} attempts ({last}). Refusing to "
        f"continue -- a dropped month would read downstream as a stretch of the "
        f"city where nobody rode.")


def list_bucket(sys: System, *, refresh: bool = False) -> list[dict]:
    """[{key, size, last_modified}] for every object in the system's bucket.

    Cached to `<cache_dir>/_bucket.xml`; the listing is the only place the set
    of published months exists, so it is kept beside the zips it describes.
    """
    sys.cache_dir.mkdir(parents=True, exist_ok=True)
    cache = sys.cache_dir / "_bucket.xml"
    if cache.exists() and not refresh:
        raw = cache.read_bytes()
    else:
        raw = _http(sys, f"{sys.bucket_url}?list-type=2&max-keys=1000")
        cache.write_bytes(raw)
    root = ET.fromstring(raw)
    if root.findtext(f"{S3_NS}IsTruncated") == "true":   # pragma: no cover
        raise BikeshareError(
            f"{sys.log_prefix}: the bucket listing is TRUNCATED; paging is not implemented "
            f"and a truncated listing would silently hide the newest months.")
    out = []
    for c in root.findall(f"{S3_NS}Contents"):
        key = c.findtext(f"{S3_NS}Key") or ""
        if not key.endswith(".zip"):
            continue
        out.append({"key": key,
                    "size": int(c.findtext(f"{S3_NS}Size") or 0),
                    "last_modified": (c.findtext(f"{S3_NS}LastModified") or "")[:10]})
    if not out:                                          # pragma: no cover
        raise BikeshareError(f"{sys.log_prefix}: the bucket listing contains no zips.")
    return out


def month_range(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Inclusive (year, month) list, oldest first."""
    out, y, m = [], *start
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def plan(sys: System, start: tuple[int, int], end: tuple[int, int] | None = None,
         *, refresh: bool = False) -> tuple[list[dict], dict]:
    """Which bucket keys cover [start, end], one entry per MONTH.

    A month is served either by its own monthly key or -- where the system's
    pre-monthly archives are usable (`legacy_keys_are_usable`, true for NYC's
    YEAR zips, false for Divvy's legacy QUARTERLY ones) -- by the archive that
    contains it. `end=None` means "the latest month the bucket actually
    publishes", derived from the listing rather than from today's date: the
    file for a month lands days into the next one.

    RAISES on a month before the system's FIRST month, and on a month the
    bucket does not cover at all. A silently short window is a silently thin
    panel.

    A month before `schema_cutoff` is planned with `era='legacy'` where the
    system can read that schema (New York) and REFUSED where it cannot
    (Chicago's pre-2020 quarterly files, which nobody has probed).
    """
    floor = sys.first_month()
    if start < floor:
        if not sys.legacy_schema_readable:
            refuse_legacy(sys, f"{start[0]}-{start[1]:02d}")
        raise BikeshareError(
            f"{sys.log_prefix}: {start[0]}-{start[1]:02d} is before the first month "
            f"the bucket publishes ({floor[0]}-{floor[1]:02d}). There is no file "
            f"to read, and planning a window that starts earlier would put a "
            f"hole at the front of the panel.")
    month_key = re.compile(sys.month_key_re)
    year_key = re.compile(sys.legacy_key_re)
    listing = {e["key"]: e for e in list_bucket(sys, refresh=refresh)
               if not (sys.key_exclude_prefix
                       and e["key"].startswith(sys.key_exclude_prefix))}
    monthly = {}
    yearly = {}
    for key in listing:
        m = month_key.match(key)
        if m:
            monthly[(int(m.group(1)), int(m.group(2)))] = key
            continue
        y = year_key.match(key)
        if y and sys.legacy_keys_are_usable:
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
                    "era": sys.era_of(*ym),
                    "archive": "year" if key in yearly.values() and ym not in monthly
                               else "month"})
    if missing:
        raise BikeshareError(
            f"{sys.log_prefix}: the bucket publishes no file for {missing}. Refusing to "
            f"ingest a window with a hole in it -- a missing month reads "
            f"downstream as a month nobody rode.")
    return out, {"start": f"{start[0]}-{start[1]:02d}",
                 "end": f"{end[0]}-{end[1]:02d}",
                 "months": len(out),
                 "keys": sorted({e["key"] for e in out}),
                 "bytes": sum({e["key"]: e["size"] for e in out}.values()),
                 "legacy_months": sum(1 for e in out if e["era"] == "legacy"),
                 "lyft_months": sum(1 for e in out if e["era"] == "lyft")}


def download(sys: System, key: str, *, refresh: bool = False) -> pathlib.Path:
    """Fetch one bucket key into the system's cache dir, size-verified.

    The cache hit is conditioned on the bucket's own `Content-Length`, not on
    mere existence: a half-written zip from an interrupted run is exactly the
    shape of a month that quietly loses its last week.
    """
    sys.cache_dir.mkdir(parents=True, exist_ok=True)
    dest = sys.cache_dir / key
    expect = next((e["size"] for e in list_bucket(sys) if e["key"] == key), None)
    if expect is None:                                   # pragma: no cover
        raise BikeshareError(f"{sys.log_prefix}: {key} is not in the bucket listing.")
    if dest.exists() and not refresh and dest.stat().st_size == expect:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    data = _http(sys, sys.bucket_url + key)
    tmp.write_bytes(data)
    if tmp.stat().st_size != expect:                     # pragma: no cover
        tmp.unlink(missing_ok=True)
        raise BikeshareError(
            f"{sys.log_prefix}: {key} downloaded {len(data)} bytes, bucket says {expect}. "
            f"Refusing a partial month.")
    tmp.replace(dest)
    return dest


# ------------------------------------------------------------------ the schema

def _norm_col(c) -> str:
    """One column name, canonicalised for comparison.

    BOM FIRST, then quotes: the first column of a UTF-8-BOM file is
    `﻿"ride_id"`, and stripping quotes before the BOM leaves the quote in place
    and the whole header unrecognised.
    """
    return str(c).strip().lstrip("﻿").strip('"').strip().lower()


def legacy_header_map(columns) -> dict[int, str] | None:
    """Position -> canonical legacy name, or None if this is not a legacy header.

    Returns a POSITIONAL map rather than a set because the three published
    spellings differ only in case and spacing, and rewriting the header by
    position is what lets DuckDB read 2013, 2017 and 2020 with ONE column map.
    A legacy header is accepted only when every one of its columns is a known
    alias: an unknown column means the shape moved and must be looked at, not
    guessed past.
    """
    out: dict[int, str] = {}
    for i, c in enumerate(columns):
        name = LEGACY_ALIASES.get(_norm_col(c))
        if name is None:
            return None
        out[i] = name
    missing = set(LEGACY_CANONICAL) - set(out.values())
    return None if missing else out


def classify_header(sys: System, columns) -> str:
    """'lyft_2021' | 'legacy_pre2021' -- or RAISE on neither."""
    cols = {_norm_col(c) for c in columns}
    if LYFT_COLUMNS <= cols:
        return "lyft_2021"
    if cols & LEGACY_MARKERS:
        return "legacy_pre2021"
    raise BikeshareError(
        f"{sys.log_prefix}: unrecognised header {sorted(cols)[:8]}... -- it is neither the "
        f"2021+ Lyft schema nor the legacy one. Re-derive the columns before "
        f"ingesting; a missing column normalises to NULL, which reads downstream "
        f"as a dock nobody used.")


def refuse_legacy(sys: System, what: str) -> None:
    """The one place the pre-Lyft refusal is stated."""
    raise BikeshareError(
        f"{sys.log_prefix}: {what} is on the PRE-2021 schema. It is refused, not mapped: "
        f"its station ids are small integers on a different scheme from the 2021+ "
        f"ids (legacy '3002' is not modern '5905.14', and no published crosswalk "
        f"maps them), so joining the two panels would either split one dock into "
        f"two stations -- inventing a dock that opened in 2021-02 and a gap before "
        f"it -- or fuse two distinct docks. The ingest window starts "
        f"{sys.schema_cutoff[0]}-{sys.schema_cutoff[1]:02d}.")


def csv_members(sys: System, zf: zipfile.ZipFile) -> list[str]:
    """The trip CSVs inside a zip: no `__MACOSX`, no dotfiles, no sibling
    system's members."""
    out = []
    for n in zf.namelist():
        base = n.rsplit("/", 1)[-1]
        if n.startswith("__MACOSX/") or base.startswith(".") or n.endswith("/"):
            continue
        if sys.key_exclude_prefix and base.upper().startswith(
                sys.key_exclude_prefix.upper()):
            continue
        if base.lower().endswith(".csv"):
            out.append(n)
        elif base.lower().endswith(".zip"):
            out.append(n)                                # nested (year archives)
    if not out:
        raise BikeshareError(
            f"{sys.log_prefix}: {zf.filename} holds no CSV member "
            f"({zf.namelist()[:5]}). Refusing to ingest an empty month.")
    return out


def _month_of(name: str) -> tuple[int, int] | None:
    m = re.search(r"(20\d{2})[-_]?(0[1-9]|1[0-2])", name.rsplit("/", 1)[-1])
    return (int(m.group(1)), int(m.group(2))) if m else None


#: A member whose stem ends `_1`, `_2`, ... is ONE CHUNK of a month that was
#: split to fit an export limit. A member without that suffix is the WHOLE
#: month. See `dedupe_members`.
_CHUNK_SUFFIX = re.compile(r"_\d+$")


def _is_chunk(base: str) -> bool:
    stem = base[:-4] if base.lower().endswith(".csv") else base
    return bool(_CHUNK_SUFFIX.search(stem))


def dedupe_members(names: list[str]) -> tuple[list[str], list[str]]:
    """(kept, suppressed) -- THE SAME MONTH IS PUBLISHED TWICE IN SOME ARCHIVES.

    This is not hypothetical and it is not small. Measured on the bucket,
    2026-09-16:

      * `2013-citibike-tripdata.zip` holds June..December 2013 TWICE: once as a
        quoted flat CSV at the archive root (`201306-citibike-tripdata.csv`) and
        again, unquoted and chunked, under a month-named folder
        (`6_June/201306-citibike-tripdata_1.csv`). The first two data rows are
        the same two trips.
      * `2018-citibike-tripdata.zip` holds April 2018 THREE times: a flat
        `201804-citibike-tripdata.csv`, a chunked `201804-citibike-tripdata_1/2.csv`
        BESIDE it at the same depth, and the same chunks again under `4_April/`.

    The existing reader flattens every member onto `dest/<basename>`, so two
    copies with different basenames both land and the month is counted TWICE --
    a doubling of 2013 and of April 2018 with no error anywhere. That is the
    same class of bug as fusing two storefronts, run backwards.

    The rule, in two steps, both deterministic:

      1. keep only the SHALLOWEST depth at which the month appears. The
         month-named folders are a second copy of what sits at the root;
         where there is nothing at the root (2014-2017, 2019) the folder copy
         is the only copy and is kept.
      2. within that depth, if an UNSUFFIXED member exists, drop the `_N`
         chunked ones. The unsuffixed file is the whole month; the chunks are a
         second rendering of it. Where every member is chunked (every Lyft-era
         monthly zip) nothing is dropped and the behaviour is unchanged.

    For 2013 this picks the ROOT flat copy, which is also the better file: the
    folder copy writes station ids as `434.0` and birth years as `1983.0`,
    while the flat copy writes `434` and `1983`.
    """
    if len(names) <= 1:
        return list(names), []
    depth = min(n.count("/") for n in names)
    kept = [n for n in names if n.count("/") == depth]
    if any(not _is_chunk(n.rsplit("/", 1)[-1]) for n in kept):
        kept = [n for n in kept if not _is_chunk(n.rsplit("/", 1)[-1])]
    keep = set(kept)
    return kept, [n for n in names if n not in keep]


def extract_month(sys: System, zip_path: pathlib.Path, year: int, month: int,
                  dest: pathlib.Path) -> list[pathlib.Path]:
    """Extract the CSV members for (year, month) into `dest`, flat.

    Handles both shapes: a monthly zip (every member belongs to the month) and a
    YEAR archive, whose members are twelve monthly files -- or twelve nested
    monthly ZIPS, which are opened in memory. Returns the written paths.

    DUPLICATE PUBLICATIONS OF ONE MONTH ARE RESOLVED, NOT CONCATENATED. See
    `dedupe_members`: 2013 and April 2018 each ship the same trips twice, and
    flattening both onto `dest/` would double them.

    Every member's header is classified. A LEGACY header is rewritten to the
    canonical legacy column names where the system can read that schema (New
    York, owner rule 2026-09-16), and refused by name where it cannot.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written: list[pathlib.Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        members = csv_members(sys, zf)
        nested = [n for n in members if n.rsplit("/", 1)[-1].lower().endswith(".zip")]
        flat = [n for n in members if n not in nested
                and _month_of(n.rsplit("/", 1)[-1]) in (None, (year, month))]
        keep, _dropped = dedupe_members(flat)
        for name in keep:
            written.append(_write_member(sys, zf, name, dest,
                                         name.rsplit("/", 1)[-1]))
        for name in nested:
            base = name.rsplit("/", 1)[-1]
            if _month_of(base) not in (None, (year, month)):
                continue
            with zipfile.ZipFile(io.BytesIO(zf.read(name))) as inner:
                imembers = [n for n in csv_members(sys, inner)
                            if _month_of(n.rsplit("/", 1)[-1]) == (year, month)]
                ikeep, _idropped = dedupe_members(imembers)
                for iname in ikeep:
                    written.append(_write_member(sys, inner, iname, dest,
                                                 iname.rsplit("/", 1)[-1]))
    if not written:
        raise BikeshareError(
            f"{sys.log_prefix}: {zip_path.name} holds no member for "
            f"{year}-{month:02d}. Refusing to record an empty month.")
    return written


def _write_member(sys: System, zf: zipfile.ZipFile, name: str, dest: pathlib.Path,
                  base: str) -> pathlib.Path:
    with zf.open(name) as fh:
        raw = fh.readline()
        head = raw.decode("utf-8-sig", "replace").rstrip("\r\n")
        kind = classify_header(sys, head.split(","))
        if kind != "lyft_2021":
            if not sys.legacy_schema_readable:
                refuse_legacy(sys, f"{base} (header: {head[:60]}...)")
            # The legacy header is REWRITTEN, not reinterpreted. Three published
            # spellings of the same fifteen columns collapse onto
            # LEGACY_CANONICAL here, so `legacy_read_csv_sql` can hand DuckDB one
            # fixed column map for 2013, 2017 and 2020 alike. An unknown column
            # is refused rather than passed through: a shape that moved must be
            # looked at.
            cmap = legacy_header_map(head.split(","))
            if cmap is None:
                raise BikeshareError(
                    f"{sys.log_prefix}: {base} carries a pre-{sys.schema_cutoff[0]}-"
                    f"{sys.schema_cutoff[1]:02d} header this reader does not know "
                    f"({head[:120]}...). The legacy era is READ, not guessed: add "
                    f"the spelling to LEGACY_ALIASES after checking what the "
                    f"column means. Reading it as a near-match would put a "
                    f"silently wrong column into eight years of panel.")
            term = b"\r\n" if raw.endswith(b"\r\n") else b"\n"
            raw = ",".join(cmap[i] for i in sorted(cmap)).encode() + term
        out = dest / base
        with out.open("wb") as w:
            # The header is re-emitted with ITS OWN line terminator, minus any
            # BOM. Phase 1 wrote `head + b"\n"`, which is byte-identical for New
            # York (whose files are LF) and CORRUPTING for Chicago: Divvy ships
            # CRLF, so an LF header in front of 679k CRLF rows makes DuckDB's
            # sniffer read ZERO columns and refuse the file. A line ending is
            # exactly the kind of per-city fact a "portable" reader discovers
            # the hard way.
            line = raw.removeprefix(b"\xef\xbb\xbf")
            if not line.endswith(b"\n"):
                line += b"\n"
            w.write(line)
            while chunk := fh.read(8 << 20):
                w.write(chunk)
    return out


# --------------------------------------------------------------- the calendar

def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last)


def day_type_of_date(d: dt.date, holidays: frozenset[dt.date] = HOLIDAYS) -> str | None:
    """'weekday' | 'saturday' | 'sunday', or None for an excluded holiday.

    `dt.date.weekday()` is 0=Monday; the project's vocabulary (and Socrata's) is
    0=Sunday, so it is converted here rather than in five call sites.
    """
    if d in holidays:
        return None
    dow = (d.weekday() + 1) % 7
    if dow == DOW_SUNDAY:
        return "sunday"
    if dow == DOW_SATURDAY:
        return "saturday"
    return "weekday"


def days_by_type(year: int, month: int,
                 holidays: frozenset[dt.date] = HOLIDAYS) -> dict[str, int]:
    """Non-holiday dates of each day type in the month -- the DIVISOR.

    From the calendar, never from the data: a dock that saw no Tuesday rides
    must not thereby get a higher daily average.
    """
    first, last = month_bounds(year, month)
    out = dict.fromkeys(DAY_TYPES, 0)
    d = first
    while d <= last:
        t = day_type_of_date(d, holidays)
        if t:
            out[t] += 1
        d += dt.timedelta(days=1)
    return out


def assert_holidays_cover(sys: System, months: list[tuple[int, int]]) -> None:
    """Refuse a window outside the hand-maintained holiday list."""
    lo, hi = HOLIDAY_COVERAGE
    bad = sorted({y for y, _ in months if not lo <= y <= hi})
    if bad:
        raise BikeshareError(
            f"{sys.log_prefix}: the federal-holiday list covers {lo}-{hi}; the window "
            f"includes {bad}. Extend HOLIDAYS_2021_2024 (or mta_ridership.HOLIDAYS) "
            f"before ingesting -- otherwise July 4th is counted as a Tuesday and "
            f"every weekday average in that year is quietly ~1.5% low.")


# ----------------------------------------------------------------- the SQL bits

def daypart_case_sql(ts: str) -> str:
    """A CASE that maps `ts`'s clock hour onto a daypart name.

    RENDERED from `mta_ridership.DAYPARTS`, never retyped: the bike dayparts and
    the subway dayparts must be the same five intervals or `loci validate-bike`
    is comparing two different clocks. NOT per-system: two cities' panels are
    comparable only on one clock.
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


def holiday_predicate_sql(ts: str, year: int, month: int,
                          holidays: frozenset[dt.date] = HOLIDAYS) -> str:
    """`AND <ts>::DATE NOT IN (...)` for this month's holidays -- or the EMPTY
    STRING when the month has none.

    The empty string is the whole point. `NOT IN (NULL)` is NULL for every row,
    which SQL treats as false, so a "no holidays this month" placeholder of
    `NULL` silently deletes the entire month. That is precisely the silent-zero
    failure this reader refuses everywhere else, and it is one keystroke away.
    """
    first, last = month_bounds(year, month)
    hol = sorted(h for h in holidays if first <= h <= last)
    if not hol:
        return ""
    lst = ", ".join(f"DATE '{h.isoformat()}'" for h in hol)
    return f" AND {ts}::DATE NOT IN ({lst})"


def is_public_station_sql(sys: System, col: str) -> str:
    """`col` is a PUBLIC dock id of this system. See `System.station_id_re`."""
    return (f"{col} IS NOT NULL AND trim({col}) <> '' "
            f"AND regexp_matches(trim({col}), '{sys.station_id_re}')")


def station_id_sql(sys: System, col: str) -> str:
    """The canonical dock id: trimmed, with the system's twin suffix REMOVED.

    The fusion is deliberate and evidenced -- see `System.twin_suffix` and
    `assert_underscore_twins_agree`. It is applied here, at read time, so
    nothing downstream ever sees the two spellings. A system with no twin
    suffix gets a plain `trim`, never a speculative merge.
    """
    if not sys.twin_suffix:
        return f"trim({col})"
    return f"regexp_replace(trim({col}), '{sys.twin_suffix}+$', '')"


def read_csv_sql(glob: str) -> str:
    cols = ", ".join(f"'{k}': '{v}'" for k, v in READ_TYPES.items())
    return (f"read_csv('{glob}', header=true, columns={{{cols}}}, "
            f"ignore_errors=false, union_by_name=true)")


def legacy_read_csv_sql(glob: str) -> str:
    cols = ", ".join(f'"{k}": \'{v}\'' for k, v in LEGACY_READ_TYPES.items())
    return (f"read_csv('{glob}', header=true, columns={{{cols}}}, "
            f"ignore_errors=false, union_by_name=true)")


def _legacy_ts_sql(col: str) -> str:
    """One legacy timestamp column -> TIMESTAMP, or NULL if it parses as none.

    The fractional part is stripped FIRST (`2019-12-01 00:00:05.5640` carries
    four digits, which `%f` does not accept), then the published spellings are
    tried in order. NULL is deliberate and bounded: `assert_legacy_parses`
    refuses a month above MAX_UNPARSED_TIMESTAMP_SHARE rather than letting an
    unreadable row fall quietly out of the month predicate.
    """
    fmts = ", ".join(f"'{f}'" for f in LEGACY_TS_FORMATS)
    return (f"try_strptime(regexp_replace(trim({col}), '\\.[0-9]+$', ''), "
            f"[{fmts}])")


def legacy_projection_sql(glob: str) -> str:
    """The legacy file, PRESENTED AS THE LYFT CONTRACT.

    Everything downstream of this -- `month_sql`, `audit_sql`, `twin_sql`,
    `start_disposition_sql`, the OD pass -- reads `started_at`,
    `start_station_id`, `member_casual` and friends, and never learns which era
    it is on. That is the point: there is ONE aggregation, not a second one that
    can drift.

    WHAT IS MAPPED, AND WHAT IS REFUSED TO BE INVENTED
    -----------------------------------------------------------------------
      starttime/stoptime        -> started_at/ended_at   (three formats, above)
      start/end station id      -> start/end_station_id, NORMALISED: one copy of
                                   a 2013 month writes `434` and the other
                                   `434.0`, so a trailing `.0` is stripped. It is
                                   stripped ONLY when the fractional part is
                                   zero -- a modern id like `5905.14` must never
                                   be truncated by a rule written for the legacy
                                   era, and this expression is shared.
      latitude/longitude        -> start/end_lat, start/end_lng
      usertype                  -> member_casual: 'Subscriber' -> member,
                                   'Customer' -> casual. NOT resident/visitor;
                                   see the module docstring's caveat 5.
      ride_id                   -> NULL. The legacy file has no trip id; `bikeid`
                                   is the BIKE, and putting it in a column named
                                   ride_id would invent an identity that could
                                   later be de-duplicated on.
      rideable_type             -> NULL, never 'classic_bike'. The legacy feed
                                   does not publish it. Citi Bike's e-bikes
                                   launched in 2018, INSIDE this era, so a
                                   blanket 'classic_bike' would be a false
                                   statement about 2018-2020, not a harmless
                                   default. `electric_trips` therefore reads 0
                                   for every legacy month, which is the honest
                                   answer to "the feed does not say".

    THE STATION ID IS THE LEGACY ID AND IS NEVER TREATED AS A MODERN ONE. It
    flows through the shared aggregation under the same column name because the
    aggregation only needs a key; `month_frame` then moves it to
    `station_id_legacy` and leaves `station_id` NULL. Legacy `3002` and modern
    `3002` are two different docks, and this is the seam that keeps them apart.
    """
    def sid(col: str) -> str:
        # `434.0` -> `434`; `5905.14` untouched (the regexp anchors on `.0` at
        # the end and nothing else).
        return f"regexp_replace(trim(\"{col}\"), '\\.0+$', '')"

    return f"""
        SELECT CAST(NULL AS VARCHAR)                     AS ride_id,
               CAST(NULL AS VARCHAR)                     AS rideable_type,
               {_legacy_ts_sql('"starttime"')}           AS started_at,
               {_legacy_ts_sql('"stoptime"')}            AS ended_at,
               trim("start station name")                AS start_station_name,
               {sid('start station id')}                 AS start_station_id,
               trim("end station name")                  AS end_station_name,
               {sid('end station id')}                   AS end_station_id,
               "start station latitude"                  AS start_lat,
               "start station longitude"                 AS start_lng,
               "end station latitude"                    AS end_lat,
               "end station longitude"                   AS end_lng,
               CASE lower(trim("usertype"))
                    WHEN 'subscriber' THEN 'member'
                    WHEN 'customer'   THEN 'casual'
               END                                       AS member_casual
        FROM {legacy_read_csv_sql(glob)}
    """


def trips_sql(glob: str, era: str = "lyft") -> str:
    """The relation every aggregation reads, for either era.

    `era='lyft'` returns EXACTLY `read_csv_sql(glob)` -- byte for byte, because
    `tests/test_lyft_systems.py` compares the rendered New York SQL against the
    committed pre-refactor module character by character and a 2021+ back-ingest
    was built from that text.
    """
    if era == "lyft":
        return read_csv_sql(glob)
    if era == "legacy":
        return f"({legacy_projection_sql(glob)})"
    raise BikeshareError(
        f"unknown era {era!r}: the file is either on the Lyft schema or on the "
        f"legacy one, and guessing is how two id spaces get fused.")


def legacy_parse_audit_sql(glob: str) -> str:
    """Rows, and rows whose `starttime`/`stoptime` parse as no known format.

    Run BEFORE the aggregation on a legacy month: an unparsed timestamp is not a
    row that errors, it is a row that silently leaves the month.
    """
    return f"""
    SELECT count(*)                                              AS rows_in_file,
           count(*) FILTER ({_legacy_ts_sql('"starttime"')} IS NULL)
                                                                 AS unparsed_starttime,
           count(*) FILTER ({_legacy_ts_sql('"stoptime"')} IS NULL)
                                                                 AS unparsed_stoptime,
           -- COALESCE, not a bare NOT IN: `NULL NOT IN (...)` is NULL, which
           -- SQL treats as false, so a blank usertype would be counted as
           -- CLASSIFIED. Measured: 201701 has 767 blank ones out of 178,843.
           count(*) FILTER (COALESCE(lower(trim("usertype")), '')
                            NOT IN ('subscriber', 'customer'))
                                                                 AS unclassified_usertype
    FROM {legacy_read_csv_sql(glob)}
    """


def assert_legacy_parses(sys: System, audit: dict, year: int, month: int) -> None:
    """Refuse a legacy month whose timestamps did not read."""
    rows = max(int(audit.get("rows_in_file", 0)), 1)
    worst = max(int(audit.get("unparsed_starttime", 0)),
                int(audit.get("unparsed_stoptime", 0)))
    share = worst / rows
    audit["unparsed_timestamp_share"] = share
    if share > MAX_UNPARSED_TIMESTAMP_SHARE:
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} has {share:.3%} of rows whose "
            f"timestamp matches none of {list(LEGACY_TS_FORMATS)}. Those rows do "
            f"not error -- they become NULL, fall out of the month predicate and "
            f"read downstream as docks nobody used. Add the format to "
            f"LEGACY_TS_FORMATS before ingesting.")


def month_sql(sys: System, glob: str, year: int, month: int,
              holidays: frozenset[dt.date] = HOLIDAYS, era: str = "lyft") -> str:
    """The ONE query that turns a month of trips into station-month cells.

    Starts and ends are aggregated SEPARATELY and FULL-OUTER-joined, because a
    dock can be all arrivals and no departures in a cell and an inner join would
    delete exactly that -- the destination signal this source exists to add.

    Both sides are restricted to the file's own month (see the docstring on the
    end-of-month spill) and to non-holiday dates.
    """
    first, last = month_bounds(year, month)
    dp_s, dt_s = daypart_case_sql("started_at"), day_type_case_sql("started_at")
    dp_e, dt_e = daypart_case_sql("ended_at"), day_type_case_sql("ended_at")

    def in_month(ts: str) -> str:
        return (f"{ts}::DATE BETWEEN DATE '{first.isoformat()}' "
                f"AND DATE '{last.isoformat()}'"
                + holiday_predicate_sql(ts, year, month, holidays))

    s_col, e_col = sys.station_col("start"), sys.station_col("end")
    sid_s, sid_e = station_id_sql(sys, s_col), station_id_sql(sys, e_col)
    return f"""
    WITH trips AS (SELECT * FROM {trips_sql(glob, era)}),
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
        WHERE {is_public_station_sql(sys, s_col)}
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
        WHERE {is_public_station_sql(sys, e_col)}
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


def twin_sql(sys: System, glob: str, era: str = "lyft") -> str:
    """Raw (unfused) id, modal name and modal position per START dock.

    Feeds `assert_underscore_twins_agree`. It must read the id UNTRIMMED of its
    suffix -- the whole point is to compare `5303.06_` with `5303.06`.
    """
    s_col = sys.station_col("start")
    return f"""
    SELECT trim({s_col})        AS station_id,
           mode(trim(start_station_name)) AS station_name,
           mode(start_lng)               AS lon,
           mode(start_lat)               AS lat
    FROM {trips_sql(glob, era)}
    WHERE {is_public_station_sql(sys, s_col)}
      AND start_lat IS NOT NULL AND start_lng IS NOT NULL
    GROUP BY 1
    """


def audit_sql(sys: System, glob: str, year: int, month: int,
              era: str = "lyft") -> str:
    """The per-month facts the report must state, in one pass over the file."""
    first, last = month_bounds(year, month)
    s_col, e_col = sys.station_col("start"), sys.station_col("end")
    foreign = (
        f"""count(*) FILTER (regexp_matches(upper(COALESCE(trim({e_col}), '')),
                                           '{sys.foreign_system_re}'))        AS {sys.foreign_ends_alias},"""
        if sys.foreign_system_re else
        f"""0                                                  AS {sys.foreign_ends_alias},"""
    )
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
           count(*) FILTER ({s_col} IS NULL OR trim({s_col}) = '')
                                                               AS dockless_starts,
           count(*) FILTER ({e_col} IS NULL OR trim({e_col}) = '')
                                                               AS dockless_ends,
           count(*) FILTER (started_at::DATE < DATE '{first.isoformat()}'
                         OR started_at::DATE > DATE '{last.isoformat()}')
                                                               AS starts_outside_month,
           count(*) FILTER (ended_at::DATE > DATE '{last.isoformat()}')
                                                               AS end_events_after_month_end,
           count(*) FILTER (member_casual = 'member')          AS member_trips,
           count(*) FILTER (member_casual = 'casual')          AS casual_trips,
           count(*) FILTER (rideable_type = 'electric_bike')   AS electric_trips,
{sys.foreign_note}
           count(*) FILTER ({s_col} IS NOT NULL
                        AND trim({s_col}) <> ''
                        AND NOT regexp_matches(trim({s_col}), '{sys.station_id_re}'))
                                                               AS out_of_system_starts,
           count(*) FILTER ({e_col} IS NOT NULL
                        AND trim({e_col}) <> ''
                        AND NOT regexp_matches(trim({e_col}), '{sys.station_id_re}'))
                                                               AS out_of_system_ends,
           {foreign}
           count(DISTINCT trim({e_col})) FILTER (
               trim({e_col}) <> ''
               AND NOT regexp_matches(trim({e_col}), '{sys.station_id_re}'))
                                                               AS out_of_system_stations,
           -- the bounding box of the docks that SURVIVE the id filter
           min(start_lng) FILTER ({is_public_station_sql(sys, s_col)}) AS lon_min,
           max(start_lng) FILTER ({is_public_station_sql(sys, s_col)}) AS lon_max,
           min(start_lat) FILTER ({is_public_station_sql(sys, s_col)}) AS lat_min,
           max(start_lat) FILTER ({is_public_station_sql(sys, s_col)}) AS lat_max
    FROM {trips_sql(glob, era)}
    """


def _as_date(v) -> dt.date:
    """pandas Timestamp | datetime | date | ISO string -> date."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if hasattr(v, "to_pydatetime"):                          # pandas Timestamp
        return v.to_pydatetime().date()
    return dt.date.fromisoformat(str(v)[:10])


def assert_month_complete(sys: System, audit: dict, year: int, month: int,
                          min_trips: int | None = None,
                          era: str | None = None) -> None:
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
    # The floor is PER ERA. New York's 2021+ floor is 300k; the smallest real
    # legacy month is 2014-02 at ~169k, so applying the modern floor to the
    # legacy era would refuse eight genuine winters as "truncated".
    era = era or sys.era_of(year, month)
    floor = sys.min_trips(era) if min_trips is None else int(min_trips)
    if audit["rows_in_file"] < floor:
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} has only {audit['rows_in_file']:,} trips "
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
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} stops at {_as_date(tail)}, before the "
            f"month ends on {last}. That is a TRUNCATED publication: "
            f"`days_in_cell` is taken from the calendar, so the missing tail "
            f"would silently divide a partial month by a full one.")
    if missing > sys.max_zero_dates:
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} has NO trip at all on {missing} of "
            f"{expected} calendar dates. One or two is a system outage (a storm); "
            f"{missing} is a publication problem, and every one of them is "
            f"currently being divided into the average as a day the docks were "
            f"open. Establish which before ingesting.")


def assert_out_of_system_bounded(sys: System, audit: dict, year: int,
                                 month: int) -> None:
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
    if share > sys.max_out_of_system_share:
        wrong = (f"a {sys.key_exclude_prefix}* key read as a {sys.label} month"
                 if sys.key_exclude_prefix else
                 f"another system's file read as a {sys.label} month")
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} has {share:.2%} of rows on dock ids "
            f"that are not {sys.label} public docks "
            f"({audit['out_of_system_stations']} distinct, "
            f"{audit[sys.foreign_ends_alias]:,} of them {sys.foreign_label}). Above "
            f"{sys.max_out_of_system_share:.0%} that is not a cross-river leak, it is "
            f"the wrong FILE -- {wrong}.")
    if audit["lon_min"] is None:                             # pragma: no cover
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} has no {sys.label} dock at all after the "
            f"id filter. That is an empty month, not a quiet one.")
    bbox = sys.bbox
    if (audit["lon_min"] < bbox["lon_min"] or audit["lon_max"] > bbox["lon_max"]
            or audit["lat_min"] < bbox["lat_min"]
            or audit["lat_max"] > bbox["lat_max"]):
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} keeps a dock outside the {sys.label} "
            f"bounding box (lon {audit['lon_min']:.4f}..{audit['lon_max']:.4f}, "
            f"lat {audit['lat_min']:.4f}..{audit['lat_max']:.4f}) even after the "
            f"id filter -- so a NUMERIC-id dock is in the wrong place. Either a "
            f"coordinate is corrupt or the id scheme has been reused across "
            f"systems; do not ingest until it is known which.")


def assert_underscore_twins_agree(sys: System, df: pd.DataFrame,
                                  tol_m: float | None = None) -> dict:
    """The evidence behind fusing `5303.06_` into `5303.06`.

    Called on the RAW (unfused) name/coordinate pairs. Refuses the fusion if a
    twin's published name differs or the two points are more than `tol_m`
    apart: that would be two different docks, and merging them is the
    dedup-fuses-distinct-storefronts bug in a new costume.

    A system with no `twin_suffix` never fuses, so there is nothing to
    evidence and this returns `{"pairs": 0}` without inventing a comparison.
    """
    import numpy as np

    if not sys.twin_suffix:
        return {"pairs": 0}
    tol_m = sys.twin_max_m if tol_m is None else tol_m
    if df.empty:
        return {"pairs": 0}
    df = df.copy()
    df["base"] = df["station_id"].str.replace(
        rf"{sys.twin_suffix}+$", "", regex=True)
    df["is_twin"] = df["station_id"].str.endswith(sys.twin_suffix)
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
        raise BikeshareError(
            f"{sys.log_prefix}: {len(bad_name)} underscore-suffixed dock ids disagree with "
            f"their base id on NAME and {len(bad_dist)} are more than {tol_m:.0f} m "
            f"away (worst {twins['dist_m'].max():.0f} m). The trailing-underscore "
            f"fusion is evidenced on name AND position; without both it would be "
            f"merging two distinct docks into one and inventing a gap where the "
            f"second used to be. Investigate before ingesting: "
            f"{sorted(set(bad_name['station_id_t']) | set(bad_dist['station_id_t']))[:5]}")
    return {"pairs": int(len(twins)), "max_dist_m": float(twins["dist_m"].max())}


# ------------------------------------------------------------------ the frame

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

#: The two columns sql/044 adds for the LEGACY era. Kept separate from
#: STATION_MONTH_COLUMNS above because that list is the 034 grain and
#: `tests/test_lyft_systems.py` compares it against the committed module: the
#: panel the 2021+ back-ingest wrote must still be described by the same names.
LEGACY_EXTRA_COLUMNS = ["station_id_legacy", "era"]

#: What a writer that knows about sql/044 inserts.
STATION_MONTH_WRITE_COLUMNS = STATION_MONTH_COLUMNS + LEGACY_EXTRA_COLUMNS


def mem(tmp_dir: pathlib.Path):
    import duckdb
    m = duckdb.connect()
    m.execute(f"SET memory_limit='{MEM_MEMORY_LIMIT}'")
    m.execute(f"SET temp_directory='{tmp_dir}'")
    return m


def month_frame(sys: System, csv_glob: str, year: int, month: int,
                tmp_dir: pathlib.Path, min_trips: int | None = None,
                era: str | None = None):
    """(station-month cell frame, audit dict) for ONE month of CSVs.

    Pure with respect to any warehouse: it reads files and returns a frame. The
    assertions (timestamps parsed, complete month, plausible size, no foreign
    system) run here, so nothing that fails them can reach a writer.

    THE LEGACY ERA LANDS IN ITS OWN ID COLUMN. A legacy month is aggregated by
    exactly the same SQL -- `legacy_projection_sql` presents it as the Lyft
    contract -- and then its key is MOVED to `station_id_legacy` with
    `station_id` left NULL. Legacy `3002` and modern `3002` are two different
    docks and no published crosswalk maps them, so they never share a column.
    `sources/cities/nyc/citibike.build_crosswalk` fills `station_id` in
    afterwards, per row, only where name AND position agree.
    """
    era = era or sys.era_of(year, month)
    m = mem(tmp_dir)
    try:
        if era == "legacy":
            parse = m.execute(legacy_parse_audit_sql(csv_glob)).fetchdf() \
                     .to_dict("records")[0]
            parse = {k: (v.item() if hasattr(v, "item") else v)
                     for k, v in parse.items()}
            assert_legacy_parses(sys, parse, year, month)
        else:
            parse = {}
        audit = m.execute(audit_sql(sys, csv_glob, year, month, era)).fetchdf() \
                 .to_dict("records")[0]
        audit = {k: (v.item() if hasattr(v, "item") else v) for k, v in audit.items()}
        audit.update({k: v for k, v in parse.items() if k != "rows_in_file"})
        audit["era"] = era
        assert_month_complete(sys, audit, year, month, min_trips, era)
        assert_out_of_system_bounded(sys, audit, year, month)
        # The twin check runs on the RAW ids, BEFORE month_sql fuses
        # them -- afterwards the evidence for the fusion is gone.
        audit["underscore_twins"] = assert_underscore_twins_agree(
            sys, m.execute(twin_sql(sys, csv_glob, era)).fetchdf())
        df = m.execute(month_sql(sys, csv_glob, year, month,
                                 HOLIDAYS, era)).fetchdf()
    finally:
        m.close()
    if df.empty:                                         # pragma: no cover
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} aggregated to zero station cells from "
            f"{audit['rows_in_file']:,} trips. Refusing to write an empty month.")
    # The id space split. Nothing downstream ever sees a legacy id in
    # `station_id`; see the docstring and sql/044.
    df["era"] = era
    if era == "legacy":
        df["station_id_legacy"] = df["station_id"]
        df["station_id"] = None
    else:
        df["station_id_legacy"] = None
    days = days_by_type(year, month)
    df["days_in_cell"] = df["day_type"].map(days).astype("int16")
    unknown = df.loc[df["days_in_cell"].isna() if df["days_in_cell"].dtype.kind == "f"
                     else [], "day_type"]
    if len(unknown):                                     # pragma: no cover
        raise BikeshareError(f"{sys.log_prefix}: unknown day types {sorted(set(unknown))}")
    audit["cells"] = int(len(df))
    key = "station_id_legacy" if era == "legacy" else "station_id"
    audit["stations"] = int(df[key].nunique())
    audit["starts"] = int(df["starts"].sum())
    audit["ends"] = int(df["ends"].sum())
    audit["days_by_type"] = days
    # The dockless share is REPORTED for every system and gated only where a
    # system declares a gate. Chicago's 23% is the system working as designed;
    # dropping it silently would hand a quarter-sized hole to the next reader.
    rows = max(int(audit["rows_in_file"]), 1)
    audit["dockless_end_share"] = int(audit["dockless_ends"]) / rows
    audit["dockless_start_share"] = int(audit["dockless_starts"]) / rows
    audit["dockless_end_policy"] = sys.dockless_end_policy
    gate = sys.max_dockless_end_share
    if gate is not None and audit["dockless_end_share"] > gate:
        raise BikeshareError(
            f"{sys.log_prefix}: {year}-{month:02d} has {audit['dockless_end_share']:.1%} of "
            f"trips ending with NO station id, above this system's gate of "
            f"{gate:.1%}. Those rides are excluded from the station grain (there "
            f"is no dock to attribute them to), so a share this size means the "
            f"panel is missing that fraction of the system's arrivals.")
    return df, audit


# ------------------------------------------------------- a scratch station-month

#: The station-month grain, WITHOUT the New York table name or its comments.
#: This is the grain the portability claim is about: a second system's month
#: lands in exactly this shape. It is created only in a SCRATCH database by the
#: probe -- `staging.citibike_station_month` in the warehouse is still created
#: by `sql/034_citibike.sql` and written only by the NYC ingest.
def station_month_ddl(table: str) -> str:
    schema = table.rsplit(".", 1)[0] if "." in table else None
    ddl = (f"CREATE TABLE IF NOT EXISTS {table} (\n"
           "    station_id     VARCHAR,\n"
           "    station_name   VARCHAR,\n"
           "    lon            DOUBLE,     -- EPSG:4326 by convention\n"
           "    lat            DOUBLE,\n"
           "    month          DATE,\n"
           "    day_type       VARCHAR,\n"
           "    daypart        VARCHAR,\n"
           "    starts         BIGINT,\n"
           "    ends           BIGINT,\n"
           "    member_starts  BIGINT,\n"
           "    casual_starts  BIGINT,\n"
           "    member_ends    BIGINT,\n"
           "    casual_ends    BIGINT,\n"
           "    days_in_cell   SMALLINT,\n"
           "    ingested_at    TIMESTAMP,\n"
           "    station_id_legacy VARCHAR,  -- pre-Lyft id space; NULL on 2021+\n"
           "    era            VARCHAR      -- 'lyft' | 'legacy'\n"
           ")")
    return (f"CREATE SCHEMA IF NOT EXISTS {schema};\n{ddl}" if schema else ddl)


def write_station_month(con, table: str, df, year: int, month: int,
                        run_at: dt.datetime) -> int:
    """DELETE-then-INSERT one month into `table`. The month is the unit of
    idempotence, exactly as in the NYC ingest."""
    first, _ = month_bounds(year, month)
    out = df.copy()
    out["ingested_at"] = run_at
    con.execute(f"DELETE FROM {table} WHERE month = ?", [first])
    for c in LEGACY_EXTRA_COLUMNS:
        if c not in out.columns:
            out[c] = None
    con.register("_lyft_month", out[STATION_MONTH_WRITE_COLUMNS])
    try:
        cols = ", ".join(STATION_MONTH_WRITE_COLUMNS)
        # Named column lists, never SELECT * -- D72 records this exact shape
        # silently mis-mapping two type-compatible columns when a new one landed.
        con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _lyft_month")
    finally:
        con.unregister("_lyft_month")
    return len(out)


def start_disposition_sql(sys: System, glob: str, year: int, month: int,
                          holidays: frozenset[dt.date] = HOLIDAYS,
                          era: str = "lyft") -> str:
    """Where every trip in the file WENT, in mutually exclusive classes.

    The counted class is exactly `month_sql`'s start-side WHERE, in the same
    order, so `counted + every excluded class = rows in the file` is an
    IDENTITY and not a reconciliation. This is what turns "23% of Divvy trips
    end nowhere" from a number in a docstring into a number the probe prints:
    nothing is dropped quietly if every dropped row is named.
    """
    first, last = month_bounds(year, month)
    col = sys.station_col("start")
    hol = holiday_predicate_sql("started_at", year, month, holidays)
    # ' AND started_at::DATE NOT IN (...)' -> the positive membership test
    hol_test = (hol.replace(" AND ", "", 1).replace("NOT IN", "IN", 1)
                if hol else "FALSE")
    return f"""
    SELECT CASE
             WHEN {col} IS NULL OR trim({col}) = ''            THEN 'dockless'
             WHEN NOT regexp_matches(trim({col}), '{sys.station_id_re}')
                                                               THEN 'out_of_system'
             WHEN started_at IS NULL
               OR start_lat IS NULL OR start_lng IS NULL       THEN 'no_position'
             WHEN started_at::DATE < DATE '{first.isoformat()}'
               OR started_at::DATE > DATE '{last.isoformat()}' THEN 'outside_month'
             WHEN {hol_test}                                   THEN 'holiday'
             ELSE 'counted'
           END                                                 AS disposition,
           count(*)                                            AS trips
    FROM {trips_sql(glob, era)}
    GROUP BY 1
    ORDER BY 2 DESC
    """


#: What the probe PROVES, as SQL, on the scratch database it just wrote:
#:   1. station-month rows exist at all (> 0);
#:   2. the day_type x daypart partition SUMS TO THE TRIPS THAT WERE ON DOCKS --
#:      no cell double-counted, none dropped;
#:   3. days_in_cell is a calendar constant within (month, day_type).
PROBE_VALIDATION_SQL = """
SELECT month,
       count(*)                                        AS cells,
       count(DISTINCT station_id)                      AS stations,
       count(DISTINCT day_type)                        AS day_types,
       count(DISTINCT daypart)                         AS dayparts,
       count(DISTINCT day_type || '/' || daypart)      AS partition_cells,
       sum(starts)                                     AS starts,
       sum(ends)                                       AS ends,
       sum(member_starts + casual_starts)              AS classified_starts,
       count(DISTINCT days_in_cell || '@' || day_type) AS divisor_variants,
       max(days_in_cell) FILTER (day_type = 'weekday') AS weekdays
FROM {table}
GROUP BY month
ORDER BY month
"""


def probe_month(sys: System, year: int, month: int, *, db_path: pathlib.Path | None,
                table: str, workdir: pathlib.Path,
                refresh: bool = False, keep_csv: bool = False) -> dict:
    """ONE month of a system, end to end, into a SCRATCH database.

    This is the portability probe and nothing more: download -> extract ->
    classify header -> aggregate -> write station-month rows -> re-read them and
    prove the partition. It writes only where it is told to write and NEVER
    touches the warehouse; there is no address frame, no walk graph and no
    supply set outside New York, so a station-month table is the end of the
    line for a second city.
    """
    import shutil

    import duckdb

    months_plan, prep = plan(sys, (year, month), (year, month), refresh=refresh)
    assert_holidays_cover(sys, [(year, month)])
    entry = months_plan[0]
    zip_path = download(sys, entry["key"], refresh=refresh)
    scratch = pathlib.Path(workdir) / f"{sys.system_id}_{year}{month:02d}"
    if scratch.exists():
        shutil.rmtree(scratch)
    run_at = dt.datetime.now()
    try:
        files = extract_month(sys, zip_path, year, month, scratch)
        header = pathlib.Path(files[0]).read_text(
            encoding="utf-8-sig", errors="replace").split("\n", 1)[0]
        header_cols = {c.strip().strip('"').strip().lower()
                       for c in header.split(",")}
        era = entry.get("era") or sys.era_of(year, month)
        df, audit = month_frame(sys, str(scratch / "*.csv"), year, month,
                                pathlib.Path(workdir), era=era)
        report = {
            "system": sys.system_id, "month": f"{year}-{month:02d}",
            "era": era,
            "key": entry["key"], "bytes": entry["size"],
            "bucket": sys.bucket_url, "csv_members": len(files),
            "header_is_subset_of_lyft_columns": header_cols >= LYFT_COLUMNS,
            "header_extra_columns": sorted(header_cols - LYFT_COLUMNS),
            "header_missing_columns": sorted(LYFT_COLUMNS - header_cols),
            "rows_in_file": int(audit["rows_in_file"]),
            "member_trips": int(audit["member_trips"]),
            "casual_trips": int(audit["casual_trips"]),
            "member_casual_unpopulated": int(audit["rows_in_file"])
                                         - int(audit["member_trips"])
                                         - int(audit["casual_trips"]),
            "dockless_starts": int(audit["dockless_starts"]),
            "dockless_ends": int(audit["dockless_ends"]),
            "dockless_end_share": audit["dockless_end_share"],
            "dockless_end_policy": audit["dockless_end_policy"],
            "dockless_gate": sys.max_dockless_end_share,
            "out_of_system_share": audit["out_of_system_share"],
            "start_dates": int(audit["start_dates"]),
            "dates_with_no_trip": int(audit["dates_with_no_trip"]),
            "days_by_type": audit["days_by_type"],
            "cells": int(audit["cells"]), "stations": int(audit["stations"]),
            "bbox": {"lon_min": audit["lon_min"], "lon_max": audit["lon_max"],
                     "lat_min": audit["lat_min"], "lat_max": audit["lat_max"]},
            "prep": prep, "table": table, "db": str(db_path) if db_path else None,
            "written": 0,
        }
        # The partition identity, computed on the FRAME before anything is
        # written: every trip that started at a public dock inside the month
        # lands in exactly one (day_type, daypart) cell.
        report["frame_starts"] = int(df["starts"].sum())
        report["frame_ends"] = int(df["ends"].sum())
        m = mem(pathlib.Path(workdir))
        try:
            disp = m.execute(start_disposition_sql(
                sys, str(scratch / "*.csv"), year, month, HOLIDAYS, era)).fetchdf()
        finally:
            m.close()
        report["start_disposition"] = {r["disposition"]: int(r["trips"])
                                       for r in disp.to_dict("records")}
        report["disposition_total"] = int(disp["trips"].sum())
        report["disposition_reconciles"] = (
            report["disposition_total"] == report["rows_in_file"]
            and report["start_disposition"].get("counted", 0)
            == report["frame_starts"])
        if db_path is None:
            return report
        con = duckdb.connect(str(db_path))
        try:
            for stmt in station_month_ddl(table).split(";\n"):
                if stmt.strip():
                    con.execute(stmt)
            report["written"] = write_station_month(con, table, df, year, month,
                                                    run_at)
            v = con.execute(PROBE_VALIDATION_SQL.format(table=table)).fetchdf()
            report["validation"] = v.to_dict("records")
        finally:
            con.close()
        return report
    finally:
        if scratch.exists() and not keep_csv:
            shutil.rmtree(scratch, ignore_errors=True)
