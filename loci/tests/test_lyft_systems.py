"""The regression guard for GTM-168 track P: parameterising the Lyft trip-file
reader must not have moved ONE BYTE of the New York SQL.

WHY THIS TEST IS SHAPED THE WAY IT IS
---------------------------------------------------------------------------
`sources/cities/nyc/citibike.py` became a thin binding over
`sources/cities/lyft_bikeshare.py` WHILE A BACK-INGEST WAS RUNNING
(`loci citibike ingest --start 2021-02 --end 2022-12`). That process holds the
pre-refactor module in memory, so editing the file could not disturb it -- but
the panel it is writing and the panel the refactored reader writes must be ONE
panel, or `staging.citibike_station_month` silently mixes two aggregations.

So the comparison is not "does it look the same". The COMMITTED version is read
out of git (`git show HEAD:...citibike.py`), loaded as a separate module under a
different name, and its `month_sql` / `audit_sql` / `twin_sql` output is compared
character for character against the refactored module's, for a fixed glob and a
fixed month. `git stash` is deliberately NOT used: stashing would disturb the
working tree the running ingest reads its cache from.

The second half asserts what `SYSTEMS` is FOR: that the two entries actually
differ on the things that are per-system facts, and that Chicago's dockless-end
policy is a parameter rather than New York's 1% intuition applied to a system
where a quarter of trips legitimately end off-dock.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import types

import pytest

from loci.sources.cities import lyft_bikeshare as lyft
from loci.sources.cities.nyc import citibike as cb

REPO = pathlib.Path(__file__).resolve().parents[2]
COMMITTED = "HEAD:loci/src/loci/sources/cities/nyc/citibike.py"

#: A fixed glob and a fixed month. Both are pure inputs to the SQL builders --
#: nothing is read from disk -- so the comparison is deterministic and offline.
GLOB = "/tmp/citibike/202306/*.csv"
YEAR, MONTH = 2023, 6
#: A month with NO federal holiday, so the `holiday_predicate_sql` empty-string
#: branch is exercised too (the branch whose failure mode is deleting a month).
GLOB2, YEAR2, MONTH2 = "/tmp/citibike/202604/*.csv", 2026, 4


@pytest.fixture(scope="module")
def committed() -> types.ModuleType:
    """The pre-refactor `citibike.py`, loaded from git as its own module."""
    try:
        src = subprocess.run(["git", "show", COMMITTED], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        pytest.skip(f"cannot read {COMMITTED} from git: {exc}")
    if "def month_sql" not in src:                       # pragma: no cover
        pytest.skip(f"{COMMITTED} does not look like the phase-1 module")
    path = pathlib.Path(__file__).parent / "_citibike_committed_tmp.py"
    path.write_text(src)
    try:
        spec = importlib.util.spec_from_file_location("_citibike_committed", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_citibike_committed"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        path.unlink(missing_ok=True)
        sys.modules.pop("_citibike_committed", None)


# --------------------------------------------------- the byte-identity guard

@pytest.mark.parametrize("glob,year,month", [(GLOB, YEAR, MONTH),
                                             (GLOB2, YEAR2, MONTH2)])
def test_month_sql_is_byte_identical_to_the_committed_module(committed, glob,
                                                             year, month):
    assert cb.month_sql(glob, year, month) == committed.month_sql(glob, year, month)


@pytest.mark.parametrize("glob,year,month", [(GLOB, YEAR, MONTH),
                                             (GLOB2, YEAR2, MONTH2)])
def test_audit_sql_is_byte_identical_to_the_committed_module(committed, glob,
                                                             year, month):
    assert cb.audit_sql(glob, year, month) == committed.audit_sql(glob, year, month)


def test_twin_sql_is_byte_identical_to_the_committed_module(committed):
    assert cb.twin_sql(GLOB) == committed.twin_sql(GLOB)


def test_the_small_sql_builders_are_byte_identical(committed):
    """The pieces the three big queries are assembled from, separately -- so a
    failure names the piece rather than a 60-line diff."""
    for col in ("start_station_id", "end_station_id"):
        assert cb.is_ny_station_sql(col) == committed.is_ny_station_sql(col)
        assert cb.station_id_sql(col) == committed.station_id_sql(col)
    for ts in ("started_at", "ended_at"):
        assert cb.daypart_case_sql(ts) == committed.daypart_case_sql(ts)
        assert cb.day_type_case_sql(ts) == committed.day_type_case_sql(ts)
        assert (cb.holiday_predicate_sql(ts, 2023, 6)
                == committed.holiday_predicate_sql(ts, 2023, 6))
        # 2026-04 has no federal holiday: the EMPTY-STRING branch.
        assert cb.holiday_predicate_sql(ts, 2026, 4) == ""
        assert (cb.holiday_predicate_sql(ts, 2026, 4)
                == committed.holiday_predicate_sql(ts, 2026, 4))
    assert cb.read_csv_sql(GLOB) == committed.read_csv_sql(GLOB)


def test_the_constants_the_panel_was_built_from_did_not_move(committed):
    for name in ("SOURCE_ID", "BUCKET_URL", "SCHEMA_CUTOFF", "NY_STATION_ID",
                 "TWIN_MAX_M", "MIN_TRIPS_PER_MONTH", "MAX_ZERO_DATES",
                 "MAX_OUT_OF_SYSTEM_SHARE", "NY_BBOX", "LYFT_COLUMNS",
                 "LEGACY_MARKERS", "READ_TYPES", "HOLIDAYS", "HOLIDAY_COVERAGE",
                 "STATION_MONTH_COLUMNS", "MEM_MEMORY_LIMIT"):
        assert getattr(cb, name) == getattr(committed, name), name
    # Only the TAIL: the committed copy is executed from tests/, so its
    # `parents[N]` walk lands somewhere else. The part that matters is that the
    # zips and the cached bucket listing still live in data/raw/citibike.
    assert cb.CACHE_DIR.parts[-3:] == committed.CACHE_DIR.parts[-3:]
    assert cb.CACHE_DIR == REPO / "loci" / "data" / "raw" / "citibike"
    assert cb.days_by_type(2026, 7) == committed.days_by_type(2026, 7)
    assert cb.month_range((2021, 2), (2021, 5)) == committed.month_range(
        (2021, 2), (2021, 5))


def test_the_public_surface_is_unchanged(committed):
    """Nothing that another module imports may have disappeared."""
    assert cb.__all__ == committed.__all__
    missing = [n for n in committed.__all__ if not hasattr(cb, n)]
    assert missing == []
    # citibike_od.py and validation/bike_counts.py reach for these by name.
    for n in ("_mem", "read_csv_sql", "holiday_predicate_sql", "month_frame"):
        assert hasattr(cb, n), n


def test_the_error_type_still_catches_what_it_caught():
    """`CitibikeError` is an ALIAS of the generic error, so a raise from inside
    the parameterised reader is caught by every existing handler."""
    assert cb.CitibikeError is lyft.BikeshareError
    with pytest.raises(cb.CitibikeError, match="PRE-2021"):
        cb.refuse_legacy("2020-12")


# --------------------------------------------------------- what SYSTEMS is for

def test_nyc_is_one_entry_and_the_module_reads_from_it():
    assert cb.SYSTEM is lyft.SYSTEMS["nyc_citibike"]
    assert cb.NY_STATION_ID == cb.SYSTEM.station_id_re
    assert cb.NY_BBOX is cb.SYSTEM.bbox
    assert cb.MAX_OUT_OF_SYSTEM_SHARE == cb.SYSTEM.max_out_of_system_share


def test_the_two_systems_differ_on_every_per_system_fact():
    ny, chi = lyft.SYSTEMS["nyc_citibike"], lyft.SYSTEMS["chicago_divvy"]
    for field in ("bucket_url", "cache_dirname", "month_key_re", "legacy_key_re",
                  "bbox", "station_id_re", "min_trips_per_month",
                  "max_out_of_system_share", "schema_cutoff", "log_prefix",
                  "source_id", "label"):
        assert getattr(ny, field) != getattr(chi, field), field
    # The sibling-system exclusion is a NEW YORK fact: Divvy's bucket holds one
    # system, so inventing a prefix for it would be a filter with nothing to do.
    assert ny.key_exclude_prefix == "JC-"
    assert chi.key_exclude_prefix is None
    # The trailing-underscore fusion is likewise New York's. A system with no
    # twins must never fuse -- that is the dedup-fuses-distinct-storefronts bug.
    assert ny.twin_suffix == "_" and chi.twin_suffix is None
    assert lyft.station_id_sql(chi, "end_station_id") == "trim(end_station_id)"
    assert "regexp_replace" in lyft.station_id_sql(ny, "end_station_id")


def test_the_dockless_gate_is_a_per_system_parameter_and_never_a_silent_drop():
    """Divvy's blank-end share (23% in 2025-06) is the system working as
    designed. It must be REPORTED, and the threshold that would refuse a month
    must belong to the system, not to the reader."""
    for s in lyft.SYSTEMS.values():
        assert s.dockless_end_policy == "exclude_and_report"
        assert "max_dockless_end_share" in s.__dataclass_fields__
    # Not a constant hiding in the code: nothing outside SYSTEMS names a
    # dockless threshold.
    src = pathlib.Path(lyft.__file__).read_text()
    assert "MAX_DOCKLESS" not in src


def test_a_month_before_a_systems_own_cutoff_is_refused_not_mapped():
    """Each system has its OWN schema cutoff; Divvy's legacy quarterly archives
    are on a different id space exactly as NYC's pre-2021 files are."""
    with pytest.raises(lyft.BikeshareError, match="PRE-2021"):
        lyft.plan(lyft.SYSTEMS["chicago_divvy"], (2019, 6))
    with pytest.raises(lyft.BikeshareError, match="PRE-2021"):
        lyft.plan(lyft.SYSTEMS["nyc_citibike"], (2020, 12))


def test_divvy_keys_parse_and_the_legacy_ones_are_not_usable():
    import re

    chi = lyft.SYSTEMS["chicago_divvy"]
    m = re.match(chi.month_key_re, "202506-divvy-tripdata.zip")
    assert m and (int(m.group(1)), int(m.group(2))) == (2025, 6)
    assert re.match(chi.legacy_key_re, "Divvy_Trips_2019_Q1.zip")
    assert re.match(chi.legacy_key_re, "Divvy_Stations_Trips_2014_Q3Q4.zip")
    assert re.match(chi.legacy_key_re, "Divvy_Trips_2015-Q1Q2.zip")
    assert chi.legacy_keys_are_usable is False      # quarterly AND pre-Lyft
    assert lyft.SYSTEMS["nyc_citibike"].legacy_keys_are_usable is True
    # A NYC key must not parse as a Divvy month, and vice versa.
    assert not re.match(chi.month_key_re, "202506-citibike-tripdata.zip")
    assert not re.match(lyft.SYSTEMS["nyc_citibike"].month_key_re,
                        "202506-divvy-tripdata.zip")


def test_the_chicago_sql_is_the_same_shape_with_chicago_constants():
    """The portability claim, as text: the same builder, the same grain, only
    the system's own facts substituted."""
    chi = lyft.SYSTEMS["chicago_divvy"]
    sql = lyft.month_sql(chi, GLOB, 2025, 6)
    assert chi.station_id_re in sql
    assert lyft.SYSTEMS["nyc_citibike"].station_id_re not in sql
    assert "FULL OUTER JOIN" in sql and "member_casual = 'member'" in sql
    audit = lyft.audit_sql(chi, GLOB, 2025, 6)
    assert "AS foreign_system_ends" in audit and "jersey_city_ends" not in audit
    assert "AS dockless_ends" in audit


def test_divvy_station_ids_match_chicagos_pattern_and_nycs_do_not():
    import duckdb

    chi, ny = lyft.SYSTEMS["chicago_divvy"], lyft.SYSTEMS["nyc_citibike"]
    con = duckdb.connect()
    def matches(system, value):
        return con.execute(
            f"SELECT regexp_matches('{value}', '{system.station_id_re}')").fetchone()[0]
    for good in ("CHI00474", "TA1307000039", "13022"):
        assert matches(chi, good), good
    # The operator's own rigs carry spaces and punctuation; they are excluded by
    # the id pattern alone, exactly as NYC's SYS*/Shop entries are.
    for bad in ("Hubbard Bike-checking (LBS-WH-TEST)",
                "Base - 2132 W Hubbard Warehouse",
                "DIVVY CASSETTE REPAIR MOBILE STATION"):
        assert not matches(chi, bad), bad
    assert matches(ny, "5905.14") and not matches(ny, "CHI00474")
    con.close()
