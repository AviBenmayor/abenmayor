"""Build staging.storefront_filing: geocode every filing to a BBL, key every
business name with the SAME normalizer `loci chains` uses, and write.

The feed-specific half lives in sources/cities/nyc/filing_feeds.py; nothing in
this module names a raw source column. The one NYC-specific fact it does know
is PLUTO -- the tax-lot file that is already on disk and is already this
project's address spine (sources/cities/nyc/addresses.py).

--------------------------------------------------------------------------
WHY PLUTO AND NOT analysis.address
--------------------------------------------------------------------------
analysis.address is being rebuilt in a concurrent session and holds only the
SCREEN's boroughs (MN+BK, D48/D78) and only RESIDENTIAL lots (UnitsRes > 0).
A storefront filing is citywide by nature and frequently sits on a commercial
lot with zero residential units, so joining to analysis.address would drop
exactly the lots this table is about. PLUTO is read straight from
data/raw/pluto.csv, all five boroughs, all lots.

--------------------------------------------------------------------------
THE NAME KEY
--------------------------------------------------------------------------
`business_name_key` is `loci.chains.normalize.brand_key`, IMPORTED, never
reimplemented. That function is what `chains.brand_location` groups on, so a
second normalizer here would mean a filing and a chain location for the same
business sat under two different keys and the stage-two join would find
nothing. Its known failure modes (franchisee filings under an operating-company
name, unconditional dash-splitting) are documented in that module and apply
here unchanged -- and they bite HARDER on the filing feeds, because a licence
application is filed by the legal entity far more often than a POI is.

--------------------------------------------------------------------------
THE LEAD TIME -- WHAT THE NUMBER IS AND IS NOT
--------------------------------------------------------------------------
`lead_times()` pairs, within ONE BBL, the earliest EARLY_STAGES filing for a
name key against its earliest OPEN_STAGES filing, and reports the gap in days.
Pairing is on (business_name_key, bbl), NOT on the name key alone: "joes pizza"
is a hundred different businesses in New York and a citywide name join would
pair a Bronx application with a Brooklyn inspection and call the difference a
lead time.

FOUR THINGS THE NUMBER IS NOT:

  1. Not a sample of openings. It is conditioned on a business having filed
     something early AND reached a terminal stage AND both rows resolving to
     the SAME BBL. A business that opens with no permit and no licence is
     invisible; one whose application geocoded 40 m off is dropped.
  2. Not a survival estimate. Applications that never opened contribute
     nothing, so the median is the median among SUCCESSES -- it answers "how
     long did it take the ones that made it", not "how long until this one
     opens".
  3. Right-censored at the window. A 24-month application window means a
     lead time longer than the elapsed window cannot be observed, so the tail
     is clipped and the median is biased DOWNWARD. The censoring fraction is
     reported beside the median for exactly this reason.
  4. Not causal, and not a schedule. `category_hint` is the feed's own text,
     unmapped; the per-category medians are descriptive.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import pandas as pd

from loci.chains.normalize import brand_key
from loci.db import METRES_SQL
from loci.filing_stages import (EARLY_STAGES, OPEN_STAGES, STAGES,
                                UNPOPULATED_STAGES)
from loci.grid.pluto import PLUTO_CSV
from loci.sources.cities.nyc.filing_feeds import FEED_COLUMNS, FEEDS

TABLE = "staging.storefront_filing"

#: The nearest-lot radius. 30 m is ~ half a Brooklyn lot frontage: far enough
#: to bridge the offset between a published storefront point and its lot
#: centroid, close enough that it cannot jump the street.
NEAREST_M = 30.0

#: Degrees of latitude / longitude per NEAREST_M at NYC's latitude, rounded UP,
#: used only to PRE-FILTER candidates. The exact test is always METRES_SQL --
#: a degree box is not a circle and 1 deg of longitude is 84 km here, not 111.
_DLAT = 0.00030
_DLON = 0.00040

#: PLUTO borocode -> the project's two-letter codes (addresses.BOROCODE inverted).
BOROCODE_TO_BOROUGH = {"1": "MN", "2": "BX", "3": "BK", "4": "QN", "5": "SI"}
BOROUGH_TO_BOROCODE = {v: k for k, v in BOROCODE_TO_BOROUGH.items()}

#: Street-type abbreviations seen in the filing feeds, mapped to the long form
#: PLUTO uses. Applied to the LAST token only: "ST MARKS PLACE" must keep its
#: leading ST. Deliberately short -- an over-eager expansion that rewrites a
#: street name is a wrong BBL, which is worse than an unmatched row.
_STREET_SUFFIX = {
    "ST": "STREET", "STR": "STREET", "AVE": "AVENUE", "AV": "AVENUE",
    "RD": "ROAD", "BLVD": "BOULEVARD", "PL": "PLACE", "DR": "DRIVE",
    "LN": "LANE", "CT": "COURT", "PKWY": "PARKWAY", "PKY": "PARKWAY",
    "TER": "TERRACE", "PLZ": "PLAZA", "SQ": "SQUARE", "EXPY": "EXPRESSWAY",
    "HWY": "HIGHWAY", "BRDG": "BRIDGE", "CIR": "CIRCLE",
}

#: The SQL expression that turns a raw address string into the join key. Used
#: on BOTH sides -- PLUTO's combined `address` and the feeds' house+street --
#: so any change here changes both and they cannot drift.
_ADDR_KEY_SQL = """
    regexp_replace(
        regexp_replace(upper(trim({expr})), '[^A-Z0-9 ]', ' ', 'g'),
        '\\s+', ' ', 'g')
"""


def _addr_key_sql(expr: str) -> str:
    return _ADDR_KEY_SQL.format(expr=expr).strip()


def _suffix_case_sql(column: str) -> str:
    """Expand a trailing street-type abbreviation, in SQL, on `column`."""
    whens = "\n".join(
        f"        WHEN {column} LIKE '% {abbr}' THEN "
        f"regexp_replace({column}, ' {abbr}$', ' {full}')"
        for abbr, full in _STREET_SUFFIX.items())
    return f"CASE\n{whens}\n        ELSE {column} END"


# --------------------------------------------------------------- PLUTO index

def build_pluto_index(con, pluto_csv: pathlib.Path | str = PLUTO_CSV, *,
                      min_lots: int = 500_000) -> int:
    """A temp table of every PLUTO lot: bbl, borough, address key, lon, lat.

    ALL FIVE BOROUGHS AND ALL LOTS -- no UnitsRes filter, unlike
    addresses.load_residential_addresses. A storefront sits on a commercial lot
    as often as not.

    `addr_unique` marks address keys that occur exactly once within a borough.
    The address ladder rung uses ONLY those: a normalised address shared by two
    lots (a corner building filed under both frontages, a campus) would
    otherwise attach the filing to whichever row the join happened to pick.
    """
    key = _addr_key_sql("address")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _pluto_lot AS
        WITH raw AS (
            SELECT
                nullif(trim(BBL), '')              AS bbl,
                borocode                            AS borocode,
                {key}                               AS addr_key_raw,
                TRY_CAST(longitude AS DOUBLE)       AS lon,
                TRY_CAST(latitude  AS DOUBLE)       AS lat
            FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
            WHERE borocode IN ('1','2','3','4','5')
        ), keyed AS (
            SELECT bbl, borocode, lon, lat,
                   {_suffix_case_sql('addr_key_raw')} AS addr_key
            FROM raw
            WHERE bbl IS NOT NULL
              AND lat BETWEEN 40.4 AND 41.0
              AND lon BETWEEN -74.3 AND -73.6
        )
        SELECT bbl, borocode, addr_key, lon, lat,
               ST_Point(lon, lat) AS geom
        FROM keyed
        QUALIFY row_number() OVER (PARTITION BY bbl ORDER BY addr_key) = 1
    """, [str(pluto_csv)])

    con.execute("""
        CREATE OR REPLACE TEMP TABLE _pluto_addr AS
        SELECT borocode, addr_key, any_value(bbl) AS bbl
        FROM _pluto_lot
        WHERE addr_key IS NOT NULL AND addr_key <> ''
        GROUP BY borocode, addr_key
        HAVING count(DISTINCT bbl) = 1
    """)
    n = con.execute("SELECT count(*) FROM _pluto_lot").fetchone()[0]
    # `min_lots` is a floor, not a tuning knob: the only caller that lowers it
    # is the unit test, which builds a four-lot synthetic PLUTO.
    if n < min_lots:
        raise RuntimeError(
            f"storefront_filing: the PLUTO index holds only {n:,} lots. NYC has "
            f"~860k. Refusing to geocode against a truncated spine -- every "
            f"unmatched filing would read as a business nobody can place."
        )
    return n


#: Columns that must reach DuckDB as VARCHAR even when the feed left every one
#: of them NULL. See match_bbl's note.
_TEXT_COLUMNS = ("filing_id", "source", "stage", "business_name",
                 "business_name_key", "bbl_raw", "bin", "house_number",
                 "street_name", "borough", "status", "category_hint",
                 "license_type", "raw_id", "provenance")


# ------------------------------------------------------------- the BBL ladder

def match_bbl(con, frame: pd.DataFrame) -> pd.DataFrame:
    """Resolve every filing to a BBL, recording HOW. Never drops a row.

    The ladder is strictly ordered and each rung sees only what the previous
    one could not place, so a row cannot be matched twice and the row count is
    invariant -- asserted below, because a fan-out here would duplicate filings
    and inflate every count downstream.
    """
    if frame.empty:
        out = frame.copy()
        out["bbl"] = None
        out["match_method"] = "unmatched"
        return out

    # An all-NULL object column registers as INT32, and the BBL join then
    # tries to cast '3000010004' to an integer and raises. Pin the text columns
    # explicitly -- a feed that publishes no BBL at all (the SLA files) has
    # exactly that shape, so this is the normal case, not an edge one.
    frame = frame.copy()
    for col in _TEXT_COLUMNS:
        if col in frame.columns:
            frame[col] = frame[col].astype("string")
    for col in ("lon", "lat"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float64")

    con.register("_filings_raw", frame)
    try:
        key = _addr_key_sql("coalesce(house_number,'') || ' ' || coalesce(street_name,'')")

        # Two statements rather than one nested CASE: the suffix expansion has
        # to run on the ALREADY-normalised key, and DuckDB will not let a
        # SELECT reference an alias defined in the same select list.
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _filings_k0 AS
            SELECT *,
                   CASE WHEN regexp_matches(coalesce(bbl_raw,''), '^[1-5][0-9]{{9}}$')
                        THEN bbl_raw END AS bbl_clean,
                   {key} AS addr_key_raw
            FROM _filings_raw
        """)
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _filings_keyed AS
            SELECT * EXCLUDE (addr_key_raw),
                   nullif(trim({_suffix_case_sql('addr_key_raw')}), '') AS addr_key
            FROM _filings_k0
        """)

        # Rung 1+2 -- the feed's own BBL, verified against PLUTO or not.
        con.execute("""
            CREATE OR REPLACE TEMP TABLE _m1 AS
            SELECT f.*,
                   f.bbl_clean AS bbl,
                   CASE WHEN p.bbl IS NOT NULL THEN 'feed_bbl'
                        ELSE 'feed_bbl_unverified' END AS match_method
            FROM _filings_keyed f
            LEFT JOIN _pluto_lot p ON p.bbl = f.bbl_clean
            WHERE f.bbl_clean IS NOT NULL
        """)

        # Rung 3 -- house + street + borough, unique within the borough.
        con.execute("""
            CREATE OR REPLACE TEMP TABLE _m2 AS
            SELECT f.*, a.bbl AS bbl, 'pluto_address' AS match_method
            FROM _filings_keyed f
            JOIN _pluto_addr a
              ON a.borocode = CASE f.borough
                     WHEN 'MN' THEN '1' WHEN 'BX' THEN '2' WHEN 'BK' THEN '3'
                     WHEN 'QN' THEN '4' WHEN 'SI' THEN '5' END
             AND a.addr_key = f.addr_key
            WHERE f.bbl_clean IS NULL AND f.addr_key IS NOT NULL
        """)

        # Rung 4 -- nearest PLUTO lot centroid within NEAREST_M.
        # The degree box is a PREFILTER; the metric test is METRES_SQL, which
        # flips (lon, lat) to (lat, lon) because ST_Distance_Sphere reads it
        # that way (D16). Ties broken on bbl so the result is deterministic and
        # the join can never fan out.
        metres = METRES_SQL.format(a="p.geom", b="ST_Point(f.lon, f.lat)")
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _m3 AS
            SELECT * EXCLUDE (d, rn) FROM (
                SELECT f.*, p.bbl AS bbl, 'pluto_nearest_30m' AS match_method,
                       {metres} AS d,
                       row_number() OVER (PARTITION BY f.filing_id
                                          ORDER BY {metres}, p.bbl) AS rn
                FROM _filings_keyed f
                JOIN _pluto_lot p
                  ON p.lat BETWEEN f.lat - {_DLAT} AND f.lat + {_DLAT}
                 AND p.lon BETWEEN f.lon - {_DLON} AND f.lon + {_DLON}
                WHERE f.bbl_clean IS NULL AND f.lon IS NOT NULL AND f.lat IS NOT NULL
                  AND f.filing_id NOT IN (SELECT filing_id FROM _m2)
            ) WHERE rn = 1 AND d <= {NEAREST_M}
        """)

        con.execute("""
            CREATE OR REPLACE TEMP TABLE _matched AS
            SELECT * FROM _m1
            UNION ALL SELECT * FROM _m2
            UNION ALL SELECT * FROM _m3
            UNION ALL
            SELECT f.*, NULL AS bbl, 'unmatched' AS match_method
            FROM _filings_keyed f
            WHERE f.filing_id NOT IN (SELECT filing_id FROM _m1)
              AND f.filing_id NOT IN (SELECT filing_id FROM _m2)
              AND f.filing_id NOT IN (SELECT filing_id FROM _m3)
        """)
        out = con.execute(
            "SELECT * EXCLUDE (bbl_clean, addr_key) FROM _matched").fetchdf()
    finally:
        con.unregister("_filings_raw")

    if len(out) != len(frame):
        raise RuntimeError(
            f"storefront_filing: the BBL ladder changed the row count "
            f"({len(frame):,} -> {len(out):,}). A rung fanned out or dropped "
            f"rows; every count in this table would be wrong."
        )
    return out


# ------------------------------------------------------------------- assemble

def assemble(con, sources: list[str] | None = None, *,
             asof: dt.date | None = None, limit: int | None = None,
             use_cache: bool = True, session=None) -> tuple[pd.DataFrame, dict]:
    """Fetch every requested feed, key the names, resolve the BBLs.

    Returns (frame ready for `write`, report). Raises on an unknown source id
    rather than silently ingesting nothing.
    """
    asof = asof or dt.date.today()
    wanted = list(sources or FEEDS)
    unknown = [s for s in wanted if s not in FEEDS]
    if unknown:
        raise ValueError(
            f"storefront_filing: unknown source(s) {unknown}; "
            f"expected from {sorted(FEEDS)}")

    frames, per_source = [], {}
    for sid in wanted:
        df = FEEDS[sid](asof=asof, limit=limit, use_cache=use_cache,
                        session=session)
        per_source[sid] = len(df)
        frames.append(df)

    raw = (pd.concat(frames, ignore_index=True) if frames
           else pd.DataFrame(columns=list(FEED_COLUMNS)))

    # Rows with no event date carry no information this table is about, and a
    # NULL filed_on would silently poison every lead-time median. Counted, not
    # swallowed.
    n_before = len(raw)
    raw = raw[raw["filed_on"].notna() & raw["raw_id"].notna()].reset_index(drop=True)
    n_no_date = n_before - len(raw)

    raw["business_name_key"] = raw["business_name"].map(brand_key)
    raw["filing_id"] = (raw["source"] + ":" + raw["stage"] + ":"
                        + raw["raw_id"].astype(str))

    # THE RENEWAL COLLAPSE. The source's own id is not unique inside every feed:
    # rbx6-tga4 issues one ROW PER PERMIT SEQUENCE, so a job_filing_number
    # renewed four times appears four times, and DCWP repeats a licence number
    # across address rows. Collapsed to the EARLIEST `filed_on` per filing_id,
    # not to an arbitrary row, because the lifecycle question is "when did this
    # permit FIRST issue" -- keeping the latest renewal would date a 2024
    # build-out to 2026 and erase the very lead time this table measures.
    # Sorted on (filing_id, filed_on, raw_id) so the survivor is deterministic
    # across runs; raw_id breaks a same-day tie.
    n_dupe = int(raw.duplicated(subset="filing_id").sum())
    dupe_by_source = (raw[raw.duplicated(subset="filing_id", keep=False)]
                      .groupby("source").size().to_dict())
    raw = (raw.sort_values(["filing_id", "filed_on", "raw_id"])
              .drop_duplicates(subset="filing_id", keep="first")
              .reset_index(drop=True))

    matched = match_bbl(con, raw)
    matched["ingested_at"] = pd.Timestamp(dt.datetime.now())

    report = {
        "asof": asof.isoformat(),
        "rows_per_source": per_source,
        "dropped_no_date_or_id": n_no_date,
        "dropped_duplicate_filing_id": n_dupe,
        "duplicate_rows_by_source": dupe_by_source,
        "rows": len(matched),
        "name_key_null": int(matched["business_name_key"].isna().sum()),
        "match_counts": (matched.groupby(["source", "match_method"])
                                .size().rename("n").reset_index()
                                .to_dict("records")),
        "stage_counts": (matched.groupby(["source", "stage"])
                                .size().rename("n").reset_index()
                                .to_dict("records")),
    }
    return matched, report


def write(con, frame: pd.DataFrame, sources: list[str]) -> int:
    """Replace exactly the named sources' rows. Idempotent per source.

    DELETE-then-INSERT scoped to `sources`, never a TRUNCATE: `loci filings
    ingest --source nyc_sla_pending_licenses` must not delete the other six
    feeds' rows.
    """
    holes = ", ".join("?" for _ in sources)
    con.execute(f"DELETE FROM {TABLE} WHERE source IN ({holes})", list(sources))
    if frame.empty:
        return 0
    con.register("_sf", frame)
    try:
        con.execute(f"""
            INSERT INTO {TABLE}
                (filing_id, source, stage, business_name, business_name_key,
                 bbl, bin, house_number, street_name, borough, lon, lat, geom,
                 filed_on, status, status_date, category_hint, license_type,
                 match_method, raw_id, ingested_at, provenance)
            SELECT filing_id, source, stage, business_name, business_name_key,
                   bbl, bin, house_number, street_name, borough, lon, lat,
                   CASE WHEN lon IS NOT NULL AND lat IS NOT NULL
                        THEN ST_Point(lon, lat) END,
                   CAST(filed_on AS DATE), status, CAST(status_date AS DATE),
                   category_hint, license_type, match_method, raw_id,
                   ingested_at, provenance
            FROM _sf
        """)
    finally:
        con.unregister("_sf")
    return len(frame)


# ---------------------------------------------------------------- validation

def validate(con, frame: pd.DataFrame, sources: list[str]) -> list[str]:
    """Prove the write: row counts and per-stage totals agree with the frame.

    Returns a list of problems; empty means the table matches what was built.
    """
    problems: list[str] = []
    holes = ", ".join("?" for _ in sources)

    db = con.execute(
        f"SELECT source, stage, count(*) n FROM {TABLE} "
        f"WHERE source IN ({holes}) GROUP BY 1, 2 ORDER BY 1, 2",
        list(sources)).fetchdf()
    mem = (frame.groupby(["source", "stage"]).size().rename("n")
                .reset_index().sort_values(["source", "stage"])
                .reset_index(drop=True))
    if len(db) != len(mem) or not db.reset_index(drop=True).equals(mem):
        problems.append(f"source x stage totals disagree:\nDB\n{db}\nframe\n{mem}")

    total_db = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE source IN ({holes})",
        list(sources)).fetchone()[0]
    if total_db != len(frame):
        problems.append(f"row count {total_db:,} != frame {len(frame):,}")

    bad_stage = con.execute(
        f"SELECT DISTINCT stage FROM {TABLE} WHERE stage NOT IN "
        f"({', '.join('?' for _ in STAGES)})", list(STAGES)).fetchall()
    if bad_stage:
        problems.append(f"stages outside the vocabulary: {bad_stage}")

    # A stage that should be populated and is empty is a broken adapter, not a
    # quiet city. UNPOPULATED_STAGES are exempt and expected to be empty.
    present = {r[0] for r in con.execute(
        f"SELECT DISTINCT stage FROM {TABLE}").fetchall()}
    expected = {s for s in frame["stage"].unique()}
    missing = expected - present
    if missing:
        problems.append(f"stages built but absent from the table: {sorted(missing)}")
    unexpected_empty = (set(STAGES) - present - UNPOPULATED_STAGES) & expected
    if unexpected_empty:
        problems.append(f"stages silently empty: {sorted(unexpected_empty)}")

    dupes = con.execute(
        f"SELECT count(*) FROM (SELECT filing_id FROM {TABLE} "
        f"GROUP BY 1 HAVING count(*) > 1)").fetchone()[0]
    if dupes:
        problems.append(f"{dupes:,} duplicated filing_id -- the grain is broken")

    return problems


# ----------------------------------------------------------------- statistics

def stats(con) -> dict:
    """Rows per source x stage, match rates, and the lead-time distribution."""
    census = con.execute(f"""
        SELECT source, stage, count(*) AS n_filings,
               count(DISTINCT business_name_key) AS n_name_keys,
               count(DISTINCT bbl) AS n_bbl,
               min(filed_on) AS first_filed_on, max(filed_on) AS last_filed_on
        FROM {TABLE} GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchdf()

    match = con.execute(f"""
        SELECT source, match_method, count(*) AS n,
               round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY source), 1)
                   AS pct_of_source
        FROM {TABLE} GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchdf()

    rate = con.execute(f"""
        SELECT source, count(*) AS n,
               sum(CASE WHEN bbl IS NOT NULL THEN 1 ELSE 0 END) AS n_bbl,
               round(100.0 * sum(CASE WHEN bbl IS NOT NULL THEN 1 ELSE 0 END)
                     / count(*), 1) AS pct_bbl,
               sum(CASE WHEN business_name_key IS NOT NULL THEN 1 ELSE 0 END)
                   AS n_name_key
        FROM {TABLE} GROUP BY 1 ORDER BY 1
    """).fetchdf()

    return {"census": census, "match": match, "match_rate": rate,
            "lead": lead_times(con, pair_kind="cross_agency"),
            "lead_same_agency": lead_times(con,
                                           pair_kind="same_agency_processing"),
            "lead_pairs": lead_by_stage_pair(con)}


#: The one (early, terminal) pair that is NOT a go-live lead time: a DCWP
#: application followed by a DCWP licence is the SAME AGENCY's own processing
#: clock. Measured on the 2026-09-13 build it is 1-57 days and it dominates the
#: pair count 5,600 to 100, so pooling it with the cross-agency pairs would
#: report "New York opens a storefront in 38 days" when what was measured is
#: how fast DCWP stamps a form. Reported separately, never merged.
SAME_AGENCY_PAIRS = (("license_application", "license_issued"),)


def _lead_pairs_sql() -> str:
    early = ", ".join(f"'{s}'" for s in sorted(EARLY_STAGES))
    open_ = ", ".join(f"'{s}'" for s in sorted(OPEN_STAGES))
    return f"""
        WITH e AS (
            SELECT business_name_key, bbl,
                   min(filed_on) AS first_filed,
                   arg_min(stage, filed_on) AS first_stage
            FROM {TABLE}
            WHERE stage IN ({early})
              AND business_name_key IS NOT NULL AND bbl IS NOT NULL
            GROUP BY 1, 2
        ), o AS (
            SELECT business_name_key, bbl,
                   min(filed_on) AS opened_on,
                   arg_min(stage, filed_on) AS open_stage,
                   arg_min(category_hint, filed_on) AS category_hint
            FROM {TABLE}
            WHERE stage IN ({open_})
              AND business_name_key IS NOT NULL AND bbl IS NOT NULL
            GROUP BY 1, 2
        ), pairs AS (
            SELECT coalesce(o.category_hint, '(none)') AS category_hint,
                   e.first_stage, o.open_stage,
                   CASE WHEN e.first_stage = 'license_application'
                         AND o.open_stage = 'license_issued'
                        THEN 'same_agency_processing' ELSE 'cross_agency'
                   END AS pair_kind,
                   date_diff('day', e.first_filed, o.opened_on) AS lead_days
            FROM e JOIN o USING (business_name_key, bbl)
            -- a terminal event BEFORE the application is a renewal or a name
            -- collision on one lot, never a lead time.
            WHERE o.opened_on >= e.first_filed
        )
    """


def lead_times(con, *, pair_kind: str | None = None,
               min_n: int = 5) -> pd.DataFrame:
    """Days from the earliest EARLY_STAGES filing to the earliest OPEN_STAGES
    filing, per (business_name_key, bbl), summarised by the OPEN row's
    `category_hint`.

    `pair_kind` filters to 'cross_agency' (a DOB/SLA filing followed by a DCWP
    licence or a DOHMH inspection -- the real go-live lead time) or
    'same_agency_processing' (DCWP application -> DCWP licence, which measures
    the agency, not the build-out). Pooling them is the trap; see
    SAME_AGENCY_PAIRS.

    Read the module docstring before quoting any of these numbers: the pairing
    is conditioned on both rows resolving to the same BBL, applications that
    never opened contribute nothing, and the window right-censors the tail.
    """
    where = f"WHERE pair_kind = '{pair_kind}'" if pair_kind else ""
    return con.execute(f"""
        {_lead_pairs_sql()}
        SELECT category_hint, any_value(pair_kind) AS pair_kind,
               count(*)                       AS n,
               median(lead_days)              AS median_days,
               quantile_cont(lead_days, 0.25) AS p25_days,
               quantile_cont(lead_days, 0.75) AS p75_days,
               min(lead_days) AS min_days, max(lead_days) AS max_days
        FROM pairs
        {where}
        GROUP BY category_hint
        HAVING count(*) >= {min_n}
        ORDER BY n DESC
    """).fetchdf()


def lead_by_stage_pair(con) -> pd.DataFrame:
    """The same pairs, cut by (first stage -> terminal stage) instead of by
    category. This is the table that shows WHY the pooled median is misleading:
    the DCWP->DCWP cell is an agency clock and every other cell is a build-out.
    """
    return con.execute(f"""
        {_lead_pairs_sql()}
        SELECT pair_kind, first_stage, open_stage,
               count(*)                       AS n,
               median(lead_days)              AS median_days,
               quantile_cont(lead_days, 0.25) AS p25_days,
               quantile_cont(lead_days, 0.75) AS p75_days
        FROM pairs
        GROUP BY 1, 2, 3
        ORDER BY n DESC
    """).fetchdf()
