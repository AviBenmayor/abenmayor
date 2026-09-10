"""NYC DCP Housing Database (project-level) + DOB Certificates of Occupancy
-> analysis.dev_pipeline, one row per DOB job.

Owner's ask (2026-09-09): "build the pipeline layer with DOB permits and CO
dates" -- so an operator can see which gap addresses are about to gain hundreds
of residents, and which gained them in the last two years.

This is NOT a POI adapter. It emits no POIRecords and never touches
staging.poi: a development job is not an establishment. Read
sql/011_dev_pipeline.sql before changing anything here -- the dedup rule, the
stage vocabulary and every caveat live in that file's header.

--------------------------------------------------------------------------
THREE DATASETS, ONE JOIN KEY
--------------------------------------------------------------------------
    br6q-ssj3   DCP Housing Database, Project-Level Files   SPINE, semiannual
    bs8b-p36w   DOB Certificate of Occupancy (BIS)          freshness, daily
    pkdm-hqz6   DOB NOW: Certificate of Occupancy           freshness, daily

`hg8x-zxpr` is NOT this dataset -- it is HPD's "Affordable Housing Production
by Building", a different universe (subsidised units only) at a different
grain. Verified 2026-09-09 against /api/views/.

The join key is the DOB job number, which appears as `job_number` in DCP and
in bs8b-p36w and as `job_filing_name` in pkdm-hqz6. Two shapes coexist in all
three: a 9-digit BIS number and a DOB NOW number (borough letter + 8 digits).
`normalize_job_number` upper-cases and strips; it never reformats, because a
BIS number and a DOB NOW number are different namespaces and coercing one into
the other would fuse two unrelated jobs.

--------------------------------------------------------------------------
FAIL LOUD
--------------------------------------------------------------------------
`fetch_*` raises when a dataset returns zero rows or when a required column is
absent. A pipeline layer that silently ingested nothing would look exactly like
a city that stopped building -- and would read, downstream, as "no new
residents are coming to any gap address", which is the most confident possible
version of being wrong.

Field names here ARE resolved positionally by Socrata `fieldName`, unlike
ll84_laundry.py: these three datasets have a single vintage each (no
cross-vintage column-meaning drift to defend against), and `REQUIRED_FIELDS`
is asserted against the live column list before any row is read, so a rename
raises rather than yielding a column of nulls.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

SOURCE_ID = "nyc_dcp_housing_db"
DOMAIN = "https://data.cityofnewyork.us"
PAGE = 50_000
TIMEOUT = 300

DCP_DATASET = "br6q-ssj3"
CO_BIS_DATASET = "bs8b-p36w"
CO_NOW_DATASET = "pkdm-hqz6"

#: DCP `Boro` is a 1-digit code; analysis.address speaks MN/BX/BK/QN/SI.
BORO_CODE = {"1": "MN", "2": "BX", "3": "BK", "4": "QN", "5": "SI"}
DEFAULT_BOROUGHS = ("MN", "BK")   # D48

#: DCP Job_Status -> stage. See sql/011's STAGE VOCABULARY block for why
#: `under_construction` is deliberately absent.
STAGE_FROM_DCP = {
    "1. Filed Application": "filed",
    "2. Approved Application": "filed",
    "3. Permitted for Construction": "permitted",
    "4. Partially Completed Construction": "partially_complete",
    "5. Completed Construction": "complete",
    "9. Withdrawn": "withdrawn",
}
#: The only stages a CO may override. DCP's own QA wins on 4/5/9.
CO_OVERRIDABLE = {"filed", "permitted"}

STAGES = ("filed", "permitted", "partially_complete", "complete", "withdrawn")

DCP_REQUIRED = (
    "job_number", "job_type", "job_status", "boro", "bbl", "bin",
    "classanet", "classainit", "classaprop", "units_co",
    "datefiled", "datepermit", "datecomplt",
    "latitude", "longitude", "nta2020", "ntaname20", "version",
)
CO_BIS_REQUIRED = ("job_number", "issue_type", "c_o_issue_date", "pr_dwelling_unit")
CO_NOW_REQUIRED = ("job_filing_name", "c_of_o_status", "c_of_o_filing_type",
                   "c_of_o_issuance_date", "number_of_dwelling_units")

#: A CO dated outside this window is a data-entry error, not a fact.
#: bs8b-p36w carries a literal `2105-11-05`. Dropped, never clamped -- clamping
#: a typo to today would invent a completion in the 24-month window.
CO_MIN_DATE = dt.date(2010, 1, 1)


# ------------------------------------------------------------------- fetch

def _columns(dataset_id: str, session: requests.Session | None = None) -> list[str]:
    sess = session or requests.Session()
    resp = sess.get(f"{DOMAIN}/api/views/{dataset_id}.json", timeout=TIMEOUT)
    resp.raise_for_status()
    return [c.get("fieldName") for c in resp.json().get("columns", [])]


def _assert_fields(dataset_id: str, present: list[str], required: tuple[str, ...]) -> None:
    missing = [f for f in required if f not in present]
    if missing:
        raise RuntimeError(
            f"dcp_housing: dataset {dataset_id} no longer exposes {missing}. "
            f"Re-derive the column names from {DOMAIN}/api/views/{dataset_id}.json "
            f"before ingesting -- a NULL column here reads downstream as "
            f"'no development near this address', which is a confident false negative."
        )


def fetch_socrata(dataset_id: str, required: tuple[str, ...], *,
                  where: str | None = None, limit: int | None = None,
                  session: requests.Session | None = None) -> pd.DataFrame:
    """Page a Socrata dataset into a DataFrame of strings. Raises on an empty
    result or a missing required column."""
    sess = session or requests.Session()
    _assert_fields(dataset_id, _columns(dataset_id, sess), required)
    rows: list[dict] = []
    offset = 0
    page = PAGE if limit is None else min(PAGE, limit)
    while True:
        params = {"$limit": page, "$offset": offset, "$order": ":id"}
        if where:
            params["$where"] = where
        resp = sess.get(f"{DOMAIN}/resource/{dataset_id}.json", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < page or (limit is not None and len(rows) >= limit):
            break
        offset += page
    if not rows:
        raise RuntimeError(
            f"dcp_housing: dataset {dataset_id} returned ZERO rows"
            + (f" for where={where!r}" if where else "")
            + ". Refusing to ingest -- an empty pipeline is indistinguishable "
              "from a city that stopped building."
        )
    df = pd.DataFrame(rows)
    for col in required:
        if col not in df.columns:
            df[col] = None
    return df.head(limit) if limit is not None else df


# --------------------------------------------------------------- normalize

def normalize_job_number(raw) -> str | None:
    """Upper-case, strip. Never reformats: a 9-digit BIS number and a
    letter-prefixed DOB NOW number are separate namespaces."""
    if raw is None:
        return None
    text = str(raw).strip().upper()
    return text or None


def _to_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", format="mixed").dt.date


def _to_int(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def co_evidence(bis: pd.DataFrame, now: pd.DataFrame,
                asof: dt.date | None = None) -> pd.DataFrame:
    """The two CO feeds -> ONE ROW PER job_number.

    Columns: job_number, co_first_date, co_type, co_units, co_source.

    This is the function the double-count bug would live in. A job has an
    initial TCO plus a renewal every 90 days until its final CO, and the same
    physical CO can appear in both feeds; so every aggregate here is
    min()/max(), which is idempotent under duplication. `co_units` is a MAX,
    never a SUM -- summing would multiply a 300-unit tower by its renewal count.
    """
    asof = asof or dt.date.today()
    frames = []

    if len(bis):
        b = pd.DataFrame({
            "job_number": bis["job_number"].map(normalize_job_number),
            "co_date": _to_date(bis["c_o_issue_date"]),
            "co_type": bis["issue_type"].astype(str).str.strip().str.lower()
                        .map(lambda v: "final" if v == "final" else "temporary"),
            "co_units": _to_int(bis["pr_dwelling_unit"]),
            "feed": "dob_bis_co",
        })
        frames.append(b)

    if len(now):
        issued = now[now["c_of_o_status"].astype(str).str.strip() == "CO Issued"]
        n = pd.DataFrame({
            "job_number": issued["job_filing_name"].map(normalize_job_number),
            # TEXT column, "MM/DD/YY H:MM:SS AM" -- NOT a Socrata calendar_date.
            # Parsed explicitly; an unparsable value becomes NaT and is dropped
            # below rather than defaulting to today.
            "co_date": pd.to_datetime(issued["c_of_o_issuance_date"], errors="coerce",
                                      format="%m/%d/%y %I:%M:%S %p").dt.date,
            "co_type": issued["c_of_o_filing_type"].astype(str).str.strip()
                        .map(lambda v: "final" if v == "Final" else "temporary"),
            "co_units": _to_int(issued["number_of_dwelling_units"]),
            "feed": "dob_now_co",
        })
        frames.append(n)

    if not frames:
        return pd.DataFrame(columns=["job_number", "co_first_date", "co_type",
                                     "co_units", "co_source"])

    co = pd.concat(frames, ignore_index=True)
    co = co[co["job_number"].notna() & co["co_date"].notna()]
    co = co[(co["co_date"] >= CO_MIN_DATE) & (co["co_date"] <= asof)]

    grouped = co.groupby("job_number", as_index=False).agg(
        co_first_date=("co_date", "min"),
        co_units=("co_units", "max"),
        n_final=("co_type", lambda s: int((s == "final").sum())),
        n_feeds=("feed", "nunique"),
        one_feed=("feed", "first"),
    )
    grouped["co_type"] = grouped["n_final"].map(lambda n: "final" if n > 0 else "temporary")
    grouped["co_source"] = grouped.apply(
        lambda r: "both" if r["n_feeds"] > 1 else r["one_feed"], axis=1)
    return grouped[["job_number", "co_first_date", "co_type", "co_units", "co_source"]]


def build_rows(dcp: pd.DataFrame, co: pd.DataFrame, boroughs: tuple[str, ...],
               asof: dt.date | None = None) -> pd.DataFrame:
    """DCP spine LEFT JOINed to the collapsed CO evidence -> analysis.dev_pipeline rows.

    The join is 1:1 by construction: `dcp.job_number` is unique (asserted here,
    not assumed) and `co` was already collapsed to one row per job_number, so
    this merge cannot fan out and cannot double-count a single tower.
    """
    asof = asof or dt.date.today()
    d = dcp.copy()
    d["job_number"] = d["job_number"].map(normalize_job_number)
    d = d[d["job_number"].notna()]
    dup = int(d["job_number"].duplicated().sum())
    if dup:
        raise RuntimeError(
            f"dcp_housing: DCP returned {dup} duplicate job_number values. The "
            f"spine must be one row per job or every catchment sum below "
            f"double-counts those jobs. Investigate before ingesting."
        )

    d["borough"] = d["boro"].astype(str).str.strip().map(BORO_CODE)
    d = d[d["borough"].isin(boroughs)]
    if d.empty:
        raise RuntimeError(f"dcp_housing: no DCP rows for boroughs {boroughs}.")

    d["net_units"] = _to_int(d["classanet"]).fillna(0)
    d["units_init"] = _to_int(d["classainit"])
    d["units_prop"] = _to_int(d["classaprop"])
    d["dcp_units_co"] = _to_int(d["units_co"])
    d["date_filed"] = _to_date(d["datefiled"])
    d["date_permitted"] = _to_date(d["datepermit"])
    d["dcp_date_complete"] = _to_date(d["datecomplt"])
    d["lon"] = pd.to_numeric(d["longitude"], errors="coerce")
    d["lat"] = pd.to_numeric(d["latitude"], errors="coerce")

    unknown = sorted(set(d["job_status"].dropna()) - set(STAGE_FROM_DCP))
    if unknown:
        raise RuntimeError(
            f"dcp_housing: unmapped DCP Job_Status {unknown}. The stage vocabulary "
            f"is load-bearing (units_permitted counts stage='permitted'); a new "
            f"status silently mapped to NULL would drop those units from the "
            f"pipeline. Extend STAGE_FROM_DCP deliberately."
        )
    d["dcp_stage"] = d["job_status"].map(STAGE_FROM_DCP)

    m = d.merge(co, on="job_number", how="left")
    assert len(m) == len(d), "CO join fanned out -- co_evidence() is not one row per job"

    has_co = m["co_first_date"].notna()
    m["stage"] = m["dcp_stage"].where(
        ~(has_co & m["dcp_stage"].isin(CO_OVERRIDABLE)), "complete")

    # date_complete: the EARLIEST of DCP's own completion date and the earliest
    # CO in either feed. DCP derives its date from a CO too, but only up to its
    # own release cutoff; taking the min keeps pre-2012 jobs (before bs8b-p36w
    # begins) while letting the daily feeds correct anything newer.
    m["date_complete"] = [
        min([x for x in (a, b) if pd.notna(x)], default=None)
        for a, b in zip(m["dcp_date_complete"], m["co_first_date"])
    ]
    m["date_complete"] = m["date_complete"].where(m["stage"] != "withdrawn", m["date_complete"])
    # A job DCP calls complete with no CO row keeps DCP as its completion source.
    m["co_source"] = m["co_source"].where(
        has_co, m["dcp_date_complete"].notna().map({True: "dcp", False: None}))
    m["units_complete"] = m["dcp_units_co"].where(m["dcp_units_co"].notna(), m["co_units"])

    vintage = str(d["version"].dropna().iloc[0]) if d["version"].notna().any() else None
    provenance = (f"{DCP_DATASET}@{vintage or '?'} (DCP project-level, semiannual)"
                  f" + {CO_BIS_DATASET} + {CO_NOW_DATASET} CO feeds as of {asof.isoformat()}")

    out = pd.DataFrame({
        "job_number": m["job_number"],
        "bbl": m["bbl"].astype(str).str.strip().replace({"": None, "nan": None}),
        "bin": m["bin"].astype(str).str.strip().replace({"": None, "nan": None}),
        "lon": m["lon"], "lat": m["lat"],
        "borough": m["borough"],
        "nta_code": m["nta2020"],
        "neighborhood": m["ntaname20"],
        "job_type": m["job_type"],
        "net_units": m["net_units"].astype("Int64"),
        "units_init": m["units_init"].astype("Int64"),
        "units_prop": m["units_prop"].astype("Int64"),
        "stage": m["stage"],
        "dcp_status": m["job_status"],
        "date_filed": m["date_filed"],
        "date_permitted": m["date_permitted"],
        "date_complete": m["date_complete"],
        "co_type": m["co_type"],
        "co_source": m["co_source"],
        "units_complete": m["units_complete"].astype("Int64"),
        "source": SOURCE_ID,
        "source_vintage": vintage,
        "provenance": provenance,
        "ingested_at": pd.Timestamp(asof),
    })
    return out.reset_index(drop=True)


# ----------------------------------------------------------------- persist

def write_dev_pipeline(con, df: pd.DataFrame, boroughs: tuple[str, ...]) -> int:
    """DELETE the boroughs in scope, then INSERT. Idempotent: re-running for
    MN,BK replaces exactly those rows and leaves any other borough's rows
    alone, so a `--boroughs MN` smoke run cannot silently delete Brooklyn.

    Geometry is built with ST_Point(lon, lat) -- (x, y) order, EPSG:4326 by
    project convention (db.py). Rows with no coordinate get a NULL geom and are
    kept: they still carry units and dates, and model/dev_pipeline.py drops
    them from the spatial measures explicitly rather than by accident.
    """
    holes = ", ".join("?" for _ in boroughs)
    con.execute(f"DELETE FROM analysis.dev_pipeline WHERE borough IN ({holes})", list(boroughs))
    con.register("_dp", df)
    try:
        con.execute("""
            INSERT INTO analysis.dev_pipeline
            SELECT job_number, bbl, bin,
                   CASE WHEN lon IS NULL OR lat IS NULL THEN NULL
                        ELSE ST_Point(lon, lat) END AS geom,
                   borough, nta_code, neighborhood, job_type,
                   CAST(net_units AS INTEGER), CAST(units_init AS INTEGER),
                   CAST(units_prop AS INTEGER),
                   stage, dcp_status,
                   CAST(date_filed AS DATE), CAST(date_permitted AS DATE),
                   CAST(date_complete AS DATE),
                   co_type, co_source, CAST(units_complete AS INTEGER),
                   source, source_vintage, provenance, ingested_at
            FROM _dp
        """)
    finally:
        con.unregister("_dp")
    return len(df)


def build(con, boroughs: tuple[str, ...] = DEFAULT_BOROUGHS, *,
          limit: int | None = None, dry_run: bool = False,
          asof: dt.date | None = None,
          session: requests.Session | None = None) -> tuple[pd.DataFrame, dict]:
    """Fetch, normalize, (optionally) write. Returns (rows, report)."""
    asof = asof or dt.date.today()
    sess = session or requests.Session()
    boro_codes = [c for c, b in BORO_CODE.items() if b in boroughs]
    where = "boro in (" + ", ".join(f"'{c}'" for c in sorted(boro_codes)) + ")"

    dcp = fetch_socrata(DCP_DATASET, DCP_REQUIRED, where=where, limit=limit, session=sess)
    bis = fetch_socrata(CO_BIS_DATASET, CO_BIS_REQUIRED, limit=limit, session=sess)
    now = fetch_socrata(CO_NOW_DATASET, CO_NOW_REQUIRED, limit=limit, session=sess)

    co = co_evidence(bis, now, asof=asof)
    rows = build_rows(dcp, co, boroughs, asof=asof)

    report = {
        "dcp_rows": len(dcp),
        "co_bis_rows": len(bis),
        "co_now_rows": len(now),
        "co_jobs": len(co),
        "rows": len(rows),
        "vintage": rows["source_vintage"].iloc[0] if len(rows) else None,
        "by_stage": rows.groupby("stage")["net_units"].agg(["count", "sum"]).to_dict("index"),
        "co_overrode_dcp": int(((rows["stage"] == "complete")
                                & rows["co_source"].isin(["dob_bis_co", "dob_now_co", "both"])
                                & (rows["dcp_status"] != "5. Completed Construction")).sum()),
        "no_geom": int(rows["lon"].isna().sum()),
    }
    if not dry_run:
        report["_written"] = write_dev_pipeline(con, rows, boroughs)
    return rows, report
