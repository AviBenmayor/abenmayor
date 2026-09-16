"""NYC DOF Storefront Registry (Local Law 157 of 2019) -> analysis.storefront,
one row per storefront per filing.

Owner's ask (2026-09-10): make "this block is missing a bodega" into "and this
specific ground floor nearby is vacant, with its lease expired."

This is NOT a POI adapter. It emits no POIRecords and never touches
staging.poi: a vacant storefront is the ABSENCE of an establishment, and
letting it into the supply set would delete the very gap it is evidence for.
Read sql/012_storefront_registry.sql before changing anything here -- the
identity rule, the filing calendar, the vocabularies and every caveat live in
that file's header.

--------------------------------------------------------------------------
ONE DATASET, STREAMED TO DISK, TRANSFORMED IN DUCKDB
--------------------------------------------------------------------------
    92iy-9c3n   "Storefronts Reported Vacant or Not"   DOF, annual + supplements

414,884 rows / 99 MB. The CSV export is streamed to `data/raw/` in chunks and
never held in Python memory; the whole normalisation is one `INSERT ... SELECT
FROM read_csv(...)` executed inside DuckDB. Nothing here builds a DataFrame of
the source, and the only frame that exists is the small report.

--------------------------------------------------------------------------
FAIL LOUD
--------------------------------------------------------------------------
`fetch` raises when the download is empty, when a required column is absent
from the live column list, and when the transform selects zero rows for the
requested boroughs. A vacancy layer that silently ingested nothing would read
downstream as "there is no empty ground floor anywhere in Manhattan" -- the
most confident possible version of being wrong, and indistinguishable from a
market with no space to lease.

--------------------------------------------------------------------------
IDENTITY -- THE ONE THING THIS SOURCE DOES NOT GIVE US
--------------------------------------------------------------------------
DOF assigns no storefront identifier and `unit` is blank on 87% of rows, so
BBL+unit fuses 52% of the file. Nothing is ever collapsed: one output row per
source row. `premises_id` (BBL|unit) is stable; `storefront_id`
(premises_id#seq) is an ordinal WITHIN a filing and renumbers between filings.
Longitudinal questions are premises-level. See sql/012's identity block.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import requests

SOURCE_ID = "nyc_dof_storefront_registry"
DOMAIN = "https://data.cityofnewyork.us"
DATASET = "92iy-9c3n"
TIMEOUT = 900
CHUNK = 1 << 20   # 1 MiB; the file is streamed, never read whole into memory

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
RAW_DIR = REPO_ROOT / "data" / "raw"
RAW_CSV = RAW_DIR / "nyc_storefront_registry.csv"
PLUTO_CSV = REPO_ROOT / "data" / "raw" / "pluto.csv"

#: DOF spells the borough out; analysis.address speaks MN/BX/BK/QN/SI.
BORO_NAME = {
    "MANHATTAN": "MN", "BRONX": "BX", "BROOKLYN": "BK",
    "QUEENS": "QN", "STATEN ISLAND": "SI",
}
#: WHAT IS INGESTED vs WHAT IS SCREENED. The registry file is city-wide and
#: already downloaded whole, so all five boroughs land in analysis.storefront
#: (owner rule 2026-09-16: never limit a data pull). D48's MN+BK SCREEN is
#: unchanged and lives at QUERY time -- `loci storefronts` still defaults to
#: MN,BK and is the only thing that writes storefront columns onto
#: analysis.address, so no QN/BX/SI row can reach a screen table by widening
#: this tuple. Anything that reads analysis.storefront WITHOUT a borough
#: predicate now sees five boroughs; the three such readers are
#: report/evidence._vacant_storefront_rows (spatially filtered by the caller),
#: model/revenue._demise_sqft (LEFT JOIN from MN+BK lots, so unmatched BBLs
#: drop) and the narrative row count in validation/retrodiction.
DEFAULT_BOROUGHS = ("MN", "BX", "BK", "QN", "SI")   # D48 screen stays MN+BK

#: Socrata `fieldName`s, asserted against the live column list before any row
#: is read. A rename raises rather than yielding a column of NULLs -- a NULL
#: vacancy flag reads downstream as "not vacant", which is a silent zero.
REQUIRED_FIELDS = (
    "filing_due_date", "reporting_year", "borough_block_lot",
    "property_street_address_or", "borough", "zip_code", "sold_date",
    "vacant_on_12_31", "construction_reported", "vacant_6_30_or_date_sold",
    "primary_business_activity", "expir_dt_of_most_recent_lease",
    "property_number", "property_street", "unit",
    "latitude", "longitude", "census_tract", "bin", "bbl", "nta",
)

#: CSV header names, in the export's own order. read_csv sees these, not the
#: API fieldNames; both are asserted so a rename on either side raises.
CSV_HEADERS = {
    "filing_due": "Filing Due Date",
    "reporting_period": "Reporting Year",
    "bbl": "Borough Block Lot",
    "address": "Property Street Address or Storefront Address",
    "borough": "Borough",
    "zip": "Zip Code",
    "sold_date": "Sold Date",
    "vacant_1231": "Vacant on 12/31",
    "construction": "Construction Reported",
    "vacant_0630": "Vacant 6/30 or Date Sold",
    "pba": "Primary Business Activity",
    "lease_expiry": "Expiration date of the most recent lease",
    "street_number": "Property Number",
    "street_name": "Property Street",
    "unit": "Unit",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "census_tract": "Census Tract",
    "bin": "BIN",
    "nta": "NTA",
}

#: Five-borough bounding box. A coordinate outside it is a geocode failure, not
#: a fact. The file's poison value -- latitude AND longitude of literal 0, on
#: 4,780 MN+BK rows -- is caught here rather than landing in the Atlantic.
BBOX = (40.4, 41.0, -74.3, -73.6)   # lat_min, lat_max, lon_min, lon_max

#: A lease expiring outside this window is a data-entry error (the file carries
#: a literal 1969-01-01 and a 2099-12-31). DROPPED, never clamped: clamping a
#: typo to today would invent an expiry, and `lease_expired` is a decision
#: input.
LEASE_MIN = dt.date(1990, 1, 1)
LEASE_MAX = dt.date(2100, 1, 1)


# ------------------------------------------------------------------- fetch

def dataset_metadata(session: requests.Session | None = None) -> dict:
    """Socrata `/api/views/` for the dataset: column list + rowsUpdatedAt."""
    sess = session or requests.Session()
    resp = sess.get(f"{DOMAIN}/api/views/{DATASET}.json", timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def assert_fields(meta: dict) -> str:
    """Raise unless every REQUIRED_FIELD is still published. Returns the
    dataset vintage (rowsUpdatedAt as an ISO date)."""
    present = {c.get("fieldName") for c in meta.get("columns", [])}
    missing = sorted(f for f in REQUIRED_FIELDS if f not in present)
    if missing:
        raise RuntimeError(
            f"storefront_registry: dataset {DATASET} no longer exposes {missing}. "
            f"Re-derive the column names from {DOMAIN}/api/views/{DATASET}.json "
            f"before ingesting -- a NULL vacancy column here reads downstream as "
            f"'no empty ground floor near this address', a confident false negative."
        )
    stamp = meta.get("rowsUpdatedAt")
    return dt.date.fromtimestamp(int(stamp)).isoformat() if stamp else "unknown"


def download_csv(dest: pathlib.Path = RAW_CSV, *,
                 session: requests.Session | None = None,
                 force: bool = False) -> pathlib.Path:
    """Stream the full CSV export to `dest` in 1 MiB chunks.

    Never loads the response body into memory (`stream=True` + `iter_content`),
    which matters: the export is ~99 MB and this machine runs several sessions
    plus a resident DuckDB. Writes to a `.part` file and renames, so an
    interrupted download can never be mistaken for a complete one.
    """
    dest = pathlib.Path(dest)
    if dest.exists() and not force and dest.stat().st_size > 1_000_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    sess = session or requests.Session()
    url = f"{DOMAIN}/api/views/{DATASET}/rows.csv?accessType=DOWNLOAD"
    written = 0
    with sess.get(url, stream=True, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK):
                if chunk:
                    fh.write(chunk)
                    written += len(chunk)
    if written < 1_000_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"storefront_registry: {DATASET} download returned {written} bytes. "
            f"Refusing to ingest -- an empty storefront registry is "
            f"indistinguishable from a city with no vacant ground floors."
        )
    tmp.replace(dest)
    return dest


# --------------------------------------------------------------- transform

def _assert_csv_headers(con, csv_path: pathlib.Path) -> None:
    cols = {c.lower() for c in con.execute(
        f"SELECT * FROM read_csv('{csv_path}', header=true, all_varchar=true, "
        f"sample_size=1000) LIMIT 0").df().columns}
    missing = sorted(h for h in CSV_HEADERS.values() if h.lower() not in cols)
    if missing:
        raise RuntimeError(
            f"storefront_registry: CSV export no longer carries {missing}. "
            f"CSV_HEADERS is out of date with {DATASET}."
        )


def _boro_case() -> str:
    """DOF's spelled-out borough -> the project's two-letter code, as SQL.
    Generated from BORO_NAME so the mapping is declared once."""
    arms = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in BORO_NAME.items())
    return f"CASE borough_name {arms} END"


def staging_sql(csv_path: pathlib.Path, boroughs: tuple[str, ...],
                pluto_csv: pathlib.Path | None, vintage: str,
                asof: dt.date) -> str:
    """The whole normalisation, as ONE DuckDB query over `read_csv`.

    Everything the sql/012 header specifies happens here and nowhere else:
    the boolean vocabularies, the data-derived filing calendar and `universe`
    flag, the coordinate poison-value and bbox guards, the three-step geometry
    fallback, the lease-expiry range guard, and the deterministic `seq` that
    makes (storefront_id, filing_due_date) a key WITHOUT collapsing any row.

    Written as SQL rather than pandas on purpose: 414,884 rows never enter
    Python.
    """
    h = CSV_HEADERS
    boro_list = ", ".join(f"'{b}'" for b in boroughs)
    pluto = (f"""
        , pluto AS (
            SELECT bbl AS pbbl,
                   TRY_CAST(latitude  AS DOUBLE) AS plat,
                   TRY_CAST(longitude AS DOUBLE) AS plon
            FROM read_csv_auto('{pluto_csv}', ALL_VARCHAR=TRUE)
            WHERE TRY_CAST(latitude AS DOUBLE) IS NOT NULL
              AND TRY_CAST(latitude AS DOUBLE) <> 0
        )""" if pluto_csv else "")
    pluto_join = ("LEFT JOIN pluto ON pluto.pbbl = g.bbl" if pluto_csv else "")
    pluto_lat = "pluto.plat" if pluto_csv else "CAST(NULL AS DOUBLE)"
    pluto_lon = "pluto.plon" if pluto_csv else "CAST(NULL AS DOUBLE)"

    return f"""
WITH raw AS (
    SELECT
        TRY_STRPTIME("{h['filing_due']}", '%m/%d/%Y')::DATE      AS filing_due_date,
        NULLIF(TRIM("{h['reporting_period']}"), '')              AS reporting_period,
        NULLIF(TRIM("{h['bbl']}"), '')                           AS bbl,
        NULLIF(TRIM("{h['address']}"), '')                       AS address,
        UPPER(TRIM("{h['borough']}"))                            AS borough_name,
        NULLIF(TRIM("{h['zip']}"), '')                           AS zip,
        TRY_STRPTIME("{h['sold_date']}", '%m/%d/%Y')::DATE       AS sold_date,
        UPPER(TRIM("{h['vacant_1231']}"))                        AS v1231_raw,
        UPPER(TRIM("{h['construction']}"))                       AS constr_raw,
        UPPER(TRIM("{h['vacant_0630']}"))                        AS v0630_raw,
        NULLIF(TRIM("{h['pba']}"), '')                           AS primary_business_activity,
        TRY_STRPTIME("{h['lease_expiry']}", '%m/%d/%Y')::DATE    AS lease_raw,
        NULLIF(TRIM("{h['street_number']}"), '')                 AS street_number,
        NULLIF(TRIM("{h['street_name']}"), '')                   AS street_name,
        UPPER(TRIM(COALESCE("{h['unit']}", '')))                 AS unit_norm,
        NULLIF(TRIM("{h['unit']}"), '')                          AS unit,
        TRY_CAST("{h['latitude']}"  AS DOUBLE)                   AS lat_raw,
        TRY_CAST("{h['longitude']}" AS DOUBLE)                   AS lon_raw,
        NULLIF(TRIM("{h['census_tract']}"), '')                  AS census_tract,
        NULLIF(TRIM("{h['bin']}"), '')                           AS bin,
        NULLIF(TRIM("{h['nta']}"), '')                           AS nta_code,
        ROW_NUMBER() OVER ()                                     AS src_row
    FROM read_csv('{csv_path}', header=true, all_varchar=true, sample_size=-1)
),
typed AS (
    SELECT *,
        {_boro_case()}                                           AS borough,
        -- VOCABULARY: {{YES,Y}} -> TRUE, {{NO,N}} -> FALSE, anything else NULL.
        -- NULL is never read as FALSE: on a vacant-only filing a NULL 12/31
        -- flag means "this filing did not ask", not "not vacant".
        CASE WHEN v1231_raw IN ('YES','Y') THEN TRUE
             WHEN v1231_raw IN ('NO','N')  THEN FALSE END        AS vacant_1231,
        CASE WHEN v0630_raw IN ('YES','Y') THEN TRUE
             WHEN v0630_raw IN ('NO','N')  THEN FALSE END        AS vacant_0630,
        CASE WHEN constr_raw IN ('YES','Y') THEN TRUE
             WHEN constr_raw IN ('NO','N')  THEN FALSE END       AS construction_reported,
        -- Out-of-range lease dates DROPPED, never clamped (sql/012 caveat 5).
        CASE WHEN lease_raw >= DATE '{LEASE_MIN.isoformat()}'
              AND lease_raw <  DATE '{LEASE_MAX.isoformat()}'
             THEN lease_raw END                                  AS lease_expiry,
        -- Coordinate guards: the literal (0, 0) poison value and anything
        -- outside the five-borough bbox become NULL, not a point at sea.
        CASE WHEN lat_raw BETWEEN {BBOX[0]} AND {BBOX[1]}
              AND lon_raw BETWEEN {BBOX[2]} AND {BBOX[3]}
             THEN lat_raw END                                    AS lat_ok,
        CASE WHEN lat_raw BETWEEN {BBOX[0]} AND {BBOX[1]}
              AND lon_raw BETWEEN {BBOX[2]} AND {BBOX[3]}
             THEN lon_raw END                                    AS lon_ok
    FROM raw
    WHERE filing_due_date IS NOT NULL
),
-- THE FILING CALENDAR, DERIVED FROM THE DATA, NOT HARD-CODED. A filing that
-- reports the 12/31 field at all observes 12/31 of the PRIOR year; one that
-- reports the 6/30 field observes 6/30 of the filing year. A filing with no
-- reported-NOT-vacant row anywhere is a vacant-only supplement.
filing AS (
    SELECT filing_due_date,
           COUNT(vacant_1231) > 0                                AS asks_1231,
           COUNT(vacant_0630) > 0                                AS asks_0630,
           CASE WHEN COUNT(*) FILTER (WHERE vacant_1231 = FALSE
                                         OR vacant_0630 = FALSE) > 0
                THEN 'full' ELSE 'vacant_only' END               AS universe
    FROM typed GROUP BY filing_due_date
),
dated AS (
    SELECT t.*, f.universe,
           CASE WHEN f.asks_1231
                THEN MAKE_DATE(YEAR(t.filing_due_date) - 1, 12, 31) END AS observed_1231,
           CASE WHEN f.asks_0630
                THEN MAKE_DATE(YEAR(t.filing_due_date),      6, 30) END AS observed_0630
    FROM typed t JOIN filing f USING (filing_due_date)
),
scoped AS (
    SELECT *, COALESCE(bbl, '?') || '|' || unit_norm AS premises_id
    FROM dated WHERE borough IN ({boro_list})
),
-- GEOMETRY FALLBACK, step 2: a valid coordinate reported for the SAME premises
-- in another filing, most recent filing winning. Rescues the 2020-08-15 filing,
-- which was geocoded later. This is a CARRY, never a merge: it moves a
-- coordinate onto a row, and touches no other field.
carry AS (
    SELECT premises_id,
           ARG_MAX(lat_ok, filing_due_date) AS clat,
           ARG_MAX(lon_ok, filing_due_date) AS clon
    FROM scoped WHERE lat_ok IS NOT NULL GROUP BY premises_id
),
g AS (
    SELECT s.*, carry.clat, carry.clon
    FROM scoped s LEFT JOIN carry USING (premises_id)
){pluto}
SELECT
    g.premises_id || '#' || CAST(
        ROW_NUMBER() OVER (PARTITION BY g.premises_id, g.filing_due_date
                           ORDER BY g.primary_business_activity NULLS LAST,
                                    g.lease_expiry NULLS LAST,
                                    g.address NULLS LAST,
                                    g.src_row) AS VARCHAR)       AS storefront_id,
    g.premises_id,
    g.filing_due_date,
    CAST(YEAR(COALESCE(g.observed_1231, g.observed_0630)) AS INTEGER) AS reporting_year,
    g.reporting_period,
    g.universe,
    g.observed_1231,
    g.observed_0630,
    g.bbl, g.bin, g.borough, g.address, g.street_number, g.street_name,
    g.unit, g.zip, g.nta_code, g.census_tract,
    CASE WHEN g.lat_ok IS NOT NULL THEN ST_Point(g.lon_ok, g.lat_ok)
         WHEN g.clat  IS NOT NULL THEN ST_Point(g.clon,  g.clat)
         WHEN {pluto_lat} IS NOT NULL THEN ST_Point({pluto_lon}, {pluto_lat})
    END                                                          AS geom,
    CASE WHEN g.lat_ok IS NOT NULL THEN 'filing'
         WHEN g.clat  IS NOT NULL THEN 'premises_carry'
         WHEN {pluto_lat} IS NOT NULL THEN 'pluto_lot'
    END                                                          AS geom_source,
    g.vacant_1231, g.vacant_0630, g.construction_reported,
    g.primary_business_activity, g.lease_expiry, g.sold_date,
    '{SOURCE_ID}'                                                AS source,
    '{vintage}'                                                  AS source_vintage,
    '{DATASET}@{vintage} (NYC DOF Storefront Registry, Local Law 157) as of {asof.isoformat()}'
                                                                 AS provenance,
    TIMESTAMP '{asof.isoformat()} 00:00:00'                      AS ingested_at
FROM g {pluto_join}
"""


# ----------------------------------------------------------------- persist

def write_storefronts(con, csv_path: pathlib.Path, boroughs: tuple[str, ...],
                      vintage: str, asof: dt.date,
                      pluto_csv: pathlib.Path | None = PLUTO_CSV) -> int:
    """DELETE the boroughs in scope, then INSERT the transform's output.

    Idempotent: re-running for MN,BK replaces exactly those rows and leaves any
    other borough alone, so a `--boroughs MN` smoke run cannot silently delete
    Brooklyn. NOTHING is collapsed on the way in -- see sql/012's dedup block:
    identical rows are indistinguishable from identical storefronts, and fusing
    them would delete real ground floors.

    Geometry is ST_Point(lon, lat) -- (x, y) order, EPSG:4326 by project
    convention (db.py). DuckDB stores no SRID; the convention is held here.
    """
    pl = pathlib.Path(pluto_csv) if pluto_csv else None
    if pl is not None and not pl.exists():
        pl = None
    sql = staging_sql(pathlib.Path(csv_path), boroughs, pl, vintage, asof)
    holes = ", ".join("?" for _ in boroughs)
    con.execute(f"DELETE FROM analysis.storefront WHERE borough IN ({holes})",
                list(boroughs))
    # A NAMED-COLUMN INSERT, not a positional one. `activity_canonical` was
    # added by sql/041 as an ALTER, so on an existing warehouse it lands at the
    # END of the table while a fresh CREATE from sql/012 puts it beside
    # `primary_business_activity` -- two different column orders for the same
    # table. A positional INSERT is correct under exactly one of them, and
    # under the other it either fails (which is what happened, 2026-09-16) or,
    # worse, writes a lease date into a business-activity column.
    from loci.model.activity_recode import canonical_sql
    con.execute(f"""
        INSERT INTO analysis.storefront (
            storefront_id, premises_id, filing_due_date, reporting_year,
            reporting_period, universe, observed_1231, observed_0630,
            bbl, bin, borough, address, street_number, street_name, unit,
            zip, nta_code, census_tract, geom, geom_source,
            vacant_1231, vacant_0630, construction_reported,
            primary_business_activity, activity_canonical, lease_expiry,
            sold_date, source, source_vintage, provenance, ingested_at)
        SELECT storefront_id, premises_id, filing_due_date, reporting_year,
               reporting_period, universe, observed_1231, observed_0630,
               bbl, bin, borough, address, street_number, street_name, unit,
               zip, nta_code, census_tract, geom, geom_source,
               vacant_1231, vacant_0630, construction_reported,
               primary_business_activity,
               -- Derived AT INGEST so a fresh `loci storefronts` run never
               -- leaves the canonical column NULL and silently degrades every
               -- longitudinal reader to "no prior use on file".
               {canonical_sql()} AS activity_canonical,
               lease_expiry, sold_date,
               source, source_vintage, provenance, ingested_at
        FROM ({sql})
    """)
    return con.execute(
        f"SELECT count(*) FROM analysis.storefront WHERE borough IN ({holes})",
        list(boroughs)).fetchone()[0]


def profile(con, csv_path: pathlib.Path, boroughs: tuple[str, ...],
            vintage: str, asof: dt.date,
            pluto_csv: pathlib.Path | None = PLUTO_CSV) -> dict:
    """Run the transform WITHOUT writing and return the run report. Used by
    --dry-run and, after the write, to describe what landed."""
    pl = pathlib.Path(pluto_csv) if pluto_csv else None
    if pl is not None and not pl.exists():
        pl = None
    sql = staging_sql(pathlib.Path(csv_path), boroughs, pl, vintage, asof)
    con.execute(f"CREATE OR REPLACE TEMP VIEW _sf_stage AS {sql}")
    try:
        n = con.execute("SELECT count(*) FROM _sf_stage").fetchone()[0]
        if not n:
            raise RuntimeError(
                f"storefront_registry: the transform selected ZERO rows for "
                f"{boroughs}. Refusing to ingest -- an empty registry is "
                f"indistinguishable from a city with no vacant ground floors."
            )
        by_filing = con.execute("""
            SELECT filing_due_date, ANY_VALUE(reporting_period) AS period,
                   ANY_VALUE(universe) AS universe,
                   ANY_VALUE(observed_1231) AS obs_1231,
                   ANY_VALUE(observed_0630) AS obs_0630,
                   count(*) AS rows_in,
                   count(DISTINCT premises_id) AS premises,
                   count(*) FILTER (WHERE vacant_1231) AS vac_1231,
                   count(*) FILTER (WHERE vacant_0630) AS vac_0630,
                   count(lease_expiry) AS with_lease
            FROM _sf_stage GROUP BY filing_due_date ORDER BY filing_due_date
        """).fetchdf()
        by_boro = con.execute("""
            SELECT borough, reporting_year, count(*) AS rows_in,
                   count(*) FILTER (WHERE vacant_1231) AS vac_1231
            FROM _sf_stage GROUP BY 1, 2 ORDER BY 1, 2
        """).fetchdf()
        geom = con.execute("""
            SELECT COALESCE(geom_source, '(none)') AS src, count(*) AS n
            FROM _sf_stage GROUP BY 1 ORDER BY 2 DESC
        """).fetchdf()
        return {
            "rows": int(n),
            "premises": int(con.execute(
                "SELECT count(DISTINCT premises_id) FROM _sf_stage").fetchone()[0]),
            "filings": int(len(by_filing)),
            "vintage": vintage,
            "by_filing": by_filing,
            "by_borough_year": by_boro,
            "geom_source": geom,
            "no_geom": int(con.execute(
                "SELECT count(*) FROM _sf_stage WHERE geom IS NULL").fetchone()[0]),
        }
    finally:
        con.execute("DROP VIEW IF EXISTS _sf_stage")


def build(con, boroughs: tuple[str, ...] = DEFAULT_BOROUGHS, *,
          dry_run: bool = False, asof: dt.date | None = None,
          csv_path: pathlib.Path | None = None,
          force_download: bool = False,
          session: requests.Session | None = None) -> dict:
    """Download (streamed), transform in DuckDB, (optionally) write.

    `con` is required even for --dry-run: the transform runs inside DuckDB, so
    a connection is the execution engine, not just the destination. A dry run
    opens it read-only at the CLI layer and writes nothing.
    """
    asof = asof or dt.date.today()
    sess = session or requests.Session()
    meta = dataset_metadata(sess)
    vintage = assert_fields(meta)
    path = pathlib.Path(csv_path) if csv_path else download_csv(
        session=sess, force=force_download)
    _assert_csv_headers(con, path)

    report = profile(con, path, boroughs, vintage, asof)
    report["csv_path"] = str(path)
    report["csv_bytes"] = path.stat().st_size
    if not dry_run:
        report["_written"] = write_storefronts(con, path, boroughs, vintage, asof)
    return report


def latest_full_observation(con, boroughs: tuple[str, ...] | list[str]) -> dt.date | None:
    """The most recent 12/31 observation from a FULL-universe filing in scope.

    This is the default snapshot the address measures run on, and the reason is
    sql/012 caveat 4: the vacant-only supplements are fresher but carry no
    denominator, so a count over them is a numerator with nothing to divide by.
    Returns None when nothing has been ingested.
    """
    holes = ", ".join("?" for _ in boroughs)
    row = con.execute(
        f"SELECT max(observed_1231) FROM analysis.storefront "
        f"WHERE borough IN ({holes}) AND universe = 'full' "
        f"AND observed_1231 IS NOT NULL", list(boroughs)).fetchone()
    return row[0] if row and row[0] else None
