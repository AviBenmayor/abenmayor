"""NYC LL84/LL133 energy-benchmarking disclosure -> in-building laundry supply.

Owner decision D51(d): in-building laundry is a laundry-category supply input.
LL84 is the ONLY measured, address-level source for it that exists in public
data (a full Socrata catalogue sweep on `q=laundry` returns 13 hits, all of
them LL84 vintages).

This is NOT a POI adapter. It emits no POIRecords and never touches
staging.poi: a laundry hookup is a BUILDING ATTRIBUTE keyed to a tax lot, not
an establishment with a location. It writes `staging.ll84_laundry` (bbl x
vintage, sql/004_ll84_laundry.sql) and its own (bbl, 'll84') rows of the
shared `analysis.address_laundry_evidence` table (D58 merge,
sql/010_address_laundry_evidence.sql) -- never touching the 'listing' rows
sources/cities/nyc/listings.py writes there.

--------------------------------------------------------------------------
FIELD NAMES MUST BE RESOLVED BY HUMAN-READABLE NAME. NEVER BY fieldName.
--------------------------------------------------------------------------
Socrata's machine `fieldName` for these two columns is positionally derived and
IT SWAPS MEANING BETWEEN VINTAGES. Verified against /api/views/<id>.json on
2026-09-08:

    dataset      multifamily_housing_number_1  _number_2     _number_3
    5zyy-y8am    -                             ALL UNITS     COMMON AREA
    7x5e-2fxh    -                             ALL UNITS     COMMON AREA
    wcm8-aq5w    -                             ALL UNITS     COMMON AREA
    4tys-3tzj    ALL UNITS                     COMMON AREA   -
    4t62-jm4m    ALL UNITS                     COMMON AREA   -
    77q4-nkfh    ALL UNITS                     COMMON AREA   -
    r6ub-zhff    COMMON AREA                   ALL UNITS     -
    usc3-8zwd    (spelled-out fieldNames, no positional suffix at all)

So `multifamily_housing_number_2` is "in all units" in four datasets and "in
common area(s)" in three. Hard-coding it -- the obvious thing to do -- would
silently transpose in-unit and common-area laundry for half the panel, and
nothing downstream could detect it: both are small non-negative integers on
the same rows. Everything here resolves through `resolve_fields`, which reads
the dataset's own column metadata and matches on the display name. If a name
stops resolving, ingestion RAISES rather than writing a column of nulls.

--------------------------------------------------------------------------
BBL NORMALIZATION
--------------------------------------------------------------------------
The BBL column is free text and filers enter it eight different ways. Observed
in a 50,000-row sample of 5zyy-y8am (35% of values are not a plain 10 digits):

    4026780001              canonical
    1- 02090-0024           borough-block-lot, dashes, stray spaces
    02-02452-0029           same, two-digit borough
    02-03220-0040;02-03220-0051   MULTI-BBL, semicolon
    0000000001, 0000000002        MULTI-BBL, comma  (and junk)
    00847-0027;00847-7501         block-lot only -- NO BOROUGH, unattributable
    072610008                     9 digits -- ambiguous, unattributable
    0-00000-0000 / 01791          junk

`normalize_bbl` returns a LIST because multi-BBL campus filings are real: a
NYCHA or Mitchell-Lama development files once for several tax lots. Keeping
only the first BBL under-attributes exactly those developments. Exploding
over-attributes instead -- the campus laundry room is credited to every lot --
and `any_multi_bbl` marks every row so the choice stays visible rather than
becoming an invisible assumption. Unparsable values are DROPPED and counted,
never coerced: a guessed BBL is a wrong join, and a wrong join here deletes a
real retail gap.

--------------------------------------------------------------------------
FAIL LOUD
--------------------------------------------------------------------------
`build_ll84_laundry` raises if a vintage returns zero rows or if either laundry
field fails to resolve. A live-API source that silently ingests nothing looks
identical to a building stock with no laundry, and would read as a citywide
laundromat opportunity. See CONTEXT.md 7.4.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Iterable, Iterator

import requests

SOURCE_ID = "nyc_ll84_benchmarking"
DOMAIN = "https://data.cityofnewyork.us"
PAGE = 50_000

# Socrata 4x4 -> LL84 report year, oldest last. The report year is the year the
# disclosure is published; the energy data it carries is the prior calendar
# year. 5zyy-y8am is a rolling "2023 to present" file and carries several
# report years at once, so its vintage comes from the row, not this table.
# k7nh-aufb (LL84 2012 / CY2011) is DELIBERATELY EXCLUDED: it predates the two
# hookup fields entirely -- its only laundry columns are the hotel and hospital
# ones, which are a different question about a different building type.
VINTAGES: tuple[tuple[str, int], ...] = (
    ("5zyy-y8am", 2024),   # rolling, CY2022-present; per-row year_ending governs
    ("7x5e-2fxh", 2022),
    ("usc3-8zwd", 2021),
    ("wcm8-aq5w", 2020),
    ("4tys-3tzj", 2019),
    ("4t62-jm4m", 2018),
    ("77q4-nkfh", 2016),
    ("r6ub-zhff", 2013),
)

# Logical field -> accepted display names, lowercased and whitespace-collapsed.
# First match wins. `required=True` fields raise when unresolved.
FIELD_NAMES: dict[str, tuple[str, ...]] = {
    "common_area_hookups": (
        "multifamily housing - number of laundry hookups in common area(s)",
        "multifamily housing - number of laundry hookups in common areas",
    ),
    "in_unit_hookups": (
        "multifamily housing - number of laundry hookups in all units",
        "multifamily housing - number of laundry hookups in each unit",
    ),
    "bbl": (
        "nyc borough, block and lot (bbl)",
        "nyc borough, block, and lot (bbl)",
        "bbl",
    ),
    "units_reported": (
        "multifamily housing - total number of residential living units",
        "multifamily housing - number of residential living units",
    ),
    "year_ending": ("year ending",),
    "calendar_year": ("calendar year",),
}
REQUIRED_FIELDS = ("common_area_hookups", "in_unit_hookups", "bbl")

# Values Portfolio Manager uses for "the filer did not answer".
_BLANKS = {"", "not available", "n/a", "na", "not applicable", "unavailable", "-"}

# Separators BETWEEN BBLs. `-` is excluded on purpose: it separates the
# borough/block/lot PARTS of a single BBL, not one BBL from the next.
_MULTI_SPLIT = re.compile(r"[;,/|&]|\s+and\s+", re.I)
_PARTS = re.compile(r"^\s*(\d{1,2})\s*[-\s]\s*(\d{1,5})\s*[-\s]\s*(\d{1,4})\s*$")


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def resolve_fields(dataset_id: str, *, session: requests.Session | None = None,
                   columns: list[dict] | None = None) -> dict[str, str]:
    """Map logical field -> this dataset's Socrata fieldName, BY DISPLAY NAME.

    `columns` is injectable so the resolution logic is testable without a
    network call. Raises if a REQUIRED_FIELDS entry cannot be resolved -- see
    the module docstring for why silently proceeding is unacceptable here.
    """
    if columns is None:
        sess = session or requests.Session()
        resp = sess.get(f"{DOMAIN}/api/views/{dataset_id}.json", timeout=120)
        resp.raise_for_status()
        columns = resp.json().get("columns", [])

    by_name = {_key(c.get("name")): c.get("fieldName") for c in columns}
    out: dict[str, str] = {}
    for logical, candidates in FIELD_NAMES.items():
        for cand in candidates:
            if by_name.get(cand):
                out[logical] = by_name[cand]
                break

    missing = [f for f in REQUIRED_FIELDS if f not in out]
    if missing:
        raise RuntimeError(
            f"ll84_laundry: dataset {dataset_id} no longer exposes {missing} under any "
            f"known display name. Do NOT fall back to a positional fieldName -- "
            f"multifamily_housing_number_2 means 'in all units' in some vintages and "
            f"'in common area(s)' in others. Re-derive the names from "
            f"{DOMAIN}/api/views/{dataset_id}.json before ingesting."
        )
    return out


def normalize_bbl(raw) -> list[str]:
    """One raw BBL cell -> zero or more 10-digit zero-padded BBLs.

    Zero results means unattributable (no borough digit, junk, or all-zero) and
    the caller must DROP the row, not guess. More than one means a multi-BBL
    campus filing, which is exploded."""
    if raw is None:
        return []
    text = str(raw)
    out: list[str] = []
    seen: set[str] = set()
    for chunk in _MULTI_SPLIT.split(text):
        bbl = _one_bbl(chunk)
        if bbl and bbl not in seen:
            seen.add(bbl)
            out.append(bbl)
    return out


def _one_bbl(chunk: str) -> str | None:
    chunk = (chunk or "").strip()
    if not chunk:
        return None

    digits_only = re.sub(r"\D", "", chunk)
    if re.fullmatch(r"\s*\d{10}\s*", chunk):
        bbl = chunk.strip()
    else:
        m = _PARTS.match(chunk)
        if m:
            boro, block, lot = m.group(1), m.group(2), m.group(3)
            bbl = f"{int(boro)}{int(block):05d}{int(lot):04d}"
        elif len(digits_only) == 10 and not re.search(r"\d[-\s]\d", chunk[:0] or ""):
            # A 10-digit run with decorative punctuation but no part structure.
            bbl = digits_only
        else:
            # 9 digits, 5 digits, block-lot with no borough: ambiguous. Drop.
            return None

    if len(bbl) != 10 or bbl[0] not in "12345":
        return None
    if bbl[1:6] == "00000" or bbl[6:] == "0000":   # block 0 or lot 0 is not a real lot
        return None
    return bbl


def parse_count(raw) -> int | None:
    """A hookup count. `Not Available` -> None. **0 is an affirmative NONE and
    must survive as 0**, which is why this cannot be `int(x or 0) or None`."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw) if raw == raw else None   # NaN guard
    text = str(raw).strip()
    if _key(text) in _BLANKS:
        return None
    text = text.replace(",", "")
    m = re.match(r"^-?\d+(\.\d+)?$", text)
    if not m:
        return None
    val = int(float(text))
    return val if val >= 0 else None


def _vintage_from_row(row: dict, fields: dict[str, str], default: int) -> int:
    """LL84 report year = the calendar year covered + 1. `Year Ending` is a
    timestamp on the last day of the covered year."""
    ye = row.get(fields.get("year_ending", ""))
    if isinstance(ye, str) and len(ye) >= 4 and ye[:4].isdigit():
        return int(ye[:4]) + 1
    cy = row.get(fields.get("calendar_year", ""))
    if cy is not None:
        text = str(cy).strip()
        if len(text) >= 4 and text[:4].isdigit():
            return int(text[:4]) + 1
    return default


def fetch_vintage(dataset_id: str, fields: dict[str, str], *,
                  session: requests.Session | None = None,
                  limit: int | None = None) -> Iterator[dict]:
    """Page one Socrata dataset, selecting only the resolved columns."""
    sess = session or requests.Session()
    token = os.environ.get("SOCRATA_APP_TOKEN")
    headers = {"X-App-Token": token} if token else {}
    select = ",".join(sorted(set(fields.values())))
    offset, seen = 0, 0
    while True:
        page = PAGE if limit is None else min(PAGE, limit - seen)
        if page <= 0:
            return
        resp = sess.get(f"{DOMAIN}/resource/{dataset_id}.json",
                        params={"$select": select, "$limit": page, "$offset": offset},
                        headers=headers, timeout=180)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return
        yield from rows
        seen += len(rows)
        offset += len(rows)
        if len(rows) < page or (limit is not None and seen >= limit):
            return


def normalize_vintage(rows: Iterable[dict], fields: dict[str, str], *,
                      dataset_id: str, default_year: int) -> tuple[list[dict], dict]:
    """Raw Socrata rows -> exploded (bbl, filed_year, counts) records + a stats
    dict. Stats carry the drop reasons, so a coverage change is visible in the
    CLI output rather than only in a row count."""
    recs: list[dict] = []
    stats = {"rows": 0, "bbl_unparsable": 0, "multi_bbl_rows": 0,
             "exploded_rows": 0, "answered": 0}
    for row in rows:
        stats["rows"] += 1
        bbls = normalize_bbl(row.get(fields["bbl"]))
        if not bbls:
            stats["bbl_unparsable"] += 1
            continue
        if len(bbls) > 1:
            stats["multi_bbl_rows"] += 1
        common = parse_count(row.get(fields["common_area_hookups"]))
        in_unit = parse_count(row.get(fields["in_unit_hookups"]))
        units = parse_count(row.get(fields.get("units_reported", "")))
        if common is not None or in_unit is not None:
            stats["answered"] += 1
        year = _vintage_from_row(row, fields, default_year)
        for bbl in bbls:
            stats["exploded_rows"] += 1
            recs.append({"bbl": bbl, "filed_year": year, "dataset_id": dataset_id,
                         "common_area_hookups": common, "in_unit_hookups": in_unit,
                         "units_reported": units, "multi_bbl": len(bbls) > 1})
    return recs, stats


def build_ll84_laundry(con, *, limit: int | None = None,
                       dry_run: bool = False) -> dict:
    """Fetch every vintage, write staging.ll84_laundry. Returns per-vintage stats.

    Fails loud on a vintage that returns nothing -- see module docstring."""
    import pandas as pd

    session = requests.Session()
    all_recs: list[dict] = []
    report: dict[str, dict] = {}

    for dataset_id, default_year in VINTAGES:
        fields = resolve_fields(dataset_id, session=session)
        rows = list(fetch_vintage(dataset_id, fields, session=session, limit=limit))
        if not rows:
            raise RuntimeError(
                f"ll84_laundry: dataset {dataset_id} returned ZERO rows. Refusing to "
                "ingest a silent zero -- an empty laundry table is indistinguishable "
                "from a city with no in-building laundry, which would read as a "
                "citywide laundromat opportunity. Check the Socrata endpoint."
            )
        recs, stats = normalize_vintage(rows, fields, dataset_id=dataset_id,
                                        default_year=default_year)
        stats["resolved_common"] = fields["common_area_hookups"]
        stats["resolved_in_unit"] = fields["in_unit_hookups"]
        report[dataset_id] = stats
        all_recs.extend(recs)

    if dry_run:
        return report

    df = pd.DataFrame(all_recs)
    con.execute("DELETE FROM staging.ll84_laundry")
    con.register("_ll84", df)
    # Collapse several filings on one lot in one vintage: max() takes the
    # affirmative answer over a 0 or a blank, and ignores NULLs by definition.
    con.execute("""
        INSERT INTO staging.ll84_laundry
        SELECT bbl,
               CAST(filed_year AS SMALLINT),
               any_value(dataset_id),
               CAST(max(common_area_hookups) AS INTEGER),
               CAST(max(in_unit_hookups)     AS INTEGER),
               CAST(max(units_reported)      AS INTEGER),
               CAST(count(*) AS SMALLINT),
               bool_or(multi_bbl),
               now()
        FROM _ll84
        GROUP BY bbl, filed_year
    """)
    con.unregister("_ll84")
    report["_written"] = {"rows": con.execute(
        "SELECT count(*) FROM staging.ll84_laundry").fetchone()[0]}
    return report


def build_address_laundry(con) -> int:
    """Pool staging.ll84_laundry to one row per BBL. Latest non-null wins, per
    field independently. Writes analysis.address_laundry_evidence with
    source='ll84' (D58 merge of address_laundry into the shared evidence
    table; sql/010_address_laundry_evidence.sql) -- only this source's own
    (bbl, 'll84') rows are touched, never the 'listing' rows written by
    sources/cities/nyc/listings.py."""
    con.execute("DELETE FROM analysis.address_laundry_evidence WHERE source = 'll84'")
    con.execute("""
        INSERT INTO analysis.address_laundry_evidence (
            bbl, source, has_common_laundry, has_in_unit_laundry, laundry_measured,
            latest_vintage, n_vintages, n_vintages_disagree,
            common_area_hookups, in_unit_hookups, units_reported, any_multi_bbl, built_at
        )
        WITH latest_common AS (
            SELECT bbl, filed_year, common_area_hookups,
                   row_number() OVER (PARTITION BY bbl ORDER BY filed_year DESC) AS rn
            FROM staging.ll84_laundry WHERE common_area_hookups IS NOT NULL
        ),
        latest_in_unit AS (
            SELECT bbl, filed_year, in_unit_hookups,
                   row_number() OVER (PARTITION BY bbl ORDER BY filed_year DESC) AS rn
            FROM staging.ll84_laundry WHERE in_unit_hookups IS NOT NULL
        ),
        latest_units AS (
            SELECT bbl, units_reported,
                   row_number() OVER (PARTITION BY bbl ORDER BY filed_year DESC) AS rn
            FROM staging.ll84_laundry WHERE units_reported IS NOT NULL
        ),
        winner AS (
            SELECT s.bbl,
                   c.common_area_hookups,
                   u.in_unit_hookups,
                   n.units_reported,
                   greatest(coalesce(c.filed_year, 0), coalesce(u.filed_year, 0)) AS latest_vintage,
                   count(*)                                   AS n_vintages,
                   bool_or(s.any_multi_bbl)                   AS any_multi_bbl
            FROM staging.ll84_laundry s
            LEFT JOIN latest_common  c ON c.bbl = s.bbl AND c.rn = 1
            LEFT JOIN latest_in_unit u ON u.bbl = s.bbl AND u.rn = 1
            LEFT JOIN latest_units   n ON n.bbl = s.bbl AND n.rn = 1
            GROUP BY 1, 2, 3, 4, 5
        ),
        -- A vintage DISAGREES when its own yes/no verdict on a field differs
        -- from the winning vintage's verdict on that field. Blanks are not
        -- disagreement; only an answered vintage can dissent.
        disagree AS (
            SELECT s.bbl, count(*) AS n_disagree
            FROM staging.ll84_laundry s
            JOIN winner w ON w.bbl = s.bbl
            WHERE (s.common_area_hookups IS NOT NULL AND w.common_area_hookups IS NOT NULL
                   AND (s.common_area_hookups > 0) <> (w.common_area_hookups > 0))
               OR (s.in_unit_hookups IS NOT NULL AND w.in_unit_hookups IS NOT NULL
                   AND (s.in_unit_hookups > 0) <> (w.in_unit_hookups > 0))
            GROUP BY 1
        )
        SELECT w.bbl,
               'll84',
               CASE WHEN w.common_area_hookups IS NULL THEN NULL
                    ELSE w.common_area_hookups > 0 END,
               CASE WHEN w.in_unit_hookups IS NULL THEN NULL
                    ELSE w.in_unit_hookups > 0 END,
               (w.common_area_hookups IS NOT NULL OR w.in_unit_hookups IS NOT NULL),
               CASE WHEN w.latest_vintage = 0 THEN NULL
                    ELSE CAST(w.latest_vintage AS SMALLINT) END,
               CAST(w.n_vintages AS SMALLINT),
               CAST(coalesce(d.n_disagree, 0) AS SMALLINT),
               w.common_area_hookups,
               w.in_unit_hookups,
               w.units_reported,
               w.any_multi_bbl,
               now()
        FROM winner w
        LEFT JOIN disagree d ON d.bbl = w.bbl
    """)
    return con.execute(
        "SELECT count(*) FROM analysis.address_laundry_evidence WHERE source = 'll84'"
    ).fetchone()[0]
