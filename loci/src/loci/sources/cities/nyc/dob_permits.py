"""NYC DOB permit issuance + renewal -> the CONSTRUCTION-PROGRESS axis on
analysis.dev_pipeline (D62 caveats 3 and 9).

WHAT D62 LEFT OPEN
------------------
sql/011_dev_pipeline.sql's STAGE VOCABULARY block says, in as many words, that
`under_construction` is deliberately NOT emitted because nothing ingested
separated "permit issued, shovel not in the ground" from "topped out". D62
caveat 3 then measured the cost of that: 23% of permitted units citywide sit
behind permits older than five years that never produced a CO. The owner is
acting on Gowanus, where every large permitted job was permitted in 2022 --
the 421-a vesting year -- so "permitted" there is a single cohort whose members
have either been building for three years or have been sitting on a vested
permit doing nothing. Stall risk is the timing question.

This module answers it from the permit RENEWAL record, which is the only dated
evidence the city publishes that a job is still being worked: a contractor who
is building renews the permit; a contractor who is not, lets it expire.

    ipu4-2q9a   DOB Permit Issuance (BIS jobs)           daily
    rbx6-tga4   DOB NOW: Build - Approved Permits        daily

`stage` IS NOT TOUCHED. It stays DCP-derived, exactly as 011 defines it.
`activity_status` is a NEW, ORTHOGONAL AXIS on the same row: stage says what
DCP's QA believes about the job, activity_status says what the permit record
says about the last twelve months. A consumer that wants "permitted AND
building" reads both.

--------------------------------------------------------------------------
THE JOIN KEY, AND THE ONE PLACE IT IS NOT AN EQUALITY
--------------------------------------------------------------------------
DCP `job_number` carries two shapes (011's JOIN KEY block): a 9-digit BIS
number (`321590532`) and a DOB NOW number (`B00680917`).

  * BIS:     ipu4-2q9a `job__` IS the job number. Straight equality.
  * DOB NOW: rbx6-tga4 `job_filing_number` is the job number PLUS a work-type
             suffix -- `M00528469-I1`, `-S1`, `-S2`, `-S3`. One job has one
             permit row PER WORK TYPE (General Construction, Structural,
             Plumbing, Mechanical...), each renewed on its own clock. The join
             is therefore `substring(job_filing_number, 1, 9) = job_number`,
             which is a FAN-OUT: many permit rows per job, by design.

That fan-out is safe here and would not be safe anywhere else in this layer,
because every aggregate below is min()/max() and NEVER a sum. Summing permit
rows would multiply a job by its renewal count -- the same double-count bug
sql/011's CO dedup rule exists to prevent, one dataset over.

--------------------------------------------------------------------------
THE RULE (also stated in sql/014_dev_pipeline_activity.sql's header)
--------------------------------------------------------------------------
Evaluated in this order; the first match wins.

  complete  stage = 'complete', or the job already has a date_complete (a CO
            exists). Permit activity is irrelevant once people have moved in.
  n/a       stage in ('filed', 'withdrawn') -- there is no construction to be
            active or stalled about -- or no permit evidence of any kind and
            no DCP permit date old enough to call.
  active    last permit issued or renewed within ACTIVE_MONTHS (12) of asof,
            OR a permit whose expiration is still in the future. Either one is
            a live authorisation to build.
  lapsed    every permit expired, but the most recent expiry is within the
            last ACTIVE_MONTHS. Renewal is routine and cheap; 0-12 months
            expired is a gap, not yet a verdict.
  stalled   every permit expired more than ACTIVE_MONTHS ago and no CO, OR no
            expiry is known and the most recent permit evidence (DOB issuance,
            else DCP's own date_permitted) is older than ZOMBIE_YEARS (5).
            This is D62 caveat 3's zombie permit, now dated per job.

WHAT THIS RULE IS NOT. It is not an observation of construction. Nobody
publishes "this building is topped out". A renewed permit is evidence that
somebody paid a fee and filed a form; a builder who is 90% done and a builder
who is keeping a 421-a permit warm both renew. The rule separates ABANDONED
from NOT ABANDONED, which is the falsifiable half of the owner's question, and
it is stated as `activity_status`, not as a construction stage, for exactly
that reason. 011's objection to inventing `under_construction` from "permit
older than N months" still stands -- this is a different column, not that one.

--------------------------------------------------------------------------
A SIGN-OFF PRECURSOR EXISTS AND IS DELIBERATELY NOT INGESTED HERE
--------------------------------------------------------------------------
rbx6-tga4 carries `permit_status` in {'Permit Issued', 'Signed-off'} (636,322
of 997,137 rows citywide are Signed-off), and w9ak-ipjd (DOB NOW: Build - Job
Application Filings) carries a job-level `signoff_date` and a `first_permit_date`.
A signed-off General Construction permit on a job with no CO is a genuine
"topped out, awaiting CO" signal -- the TCO precursor the brief asked about.
It is NOT built here because it would be a fifth activity_status value whose
meaning ("nearly done") the screen has no consumer for yet, and because
sign-off is per WORK TYPE: a signed-off Plumbing permit on a job whose General
Construction permit is still open means nothing. Ticket it, don't smuggle it in.

WHAT DOES NOT EXIST: a "construction started" or "first inspection" date.
ipu4-2q9a's `job_start_date` is the date the permittee DECLARED work would
begin when the permit was pulled -- on the rows probed it is identical to
`issuance_date` on the initial permit and is then copied unchanged onto every
renewal, so it dates the paperwork, not the shovel. DOB NOW exposes no
equivalent at all. There is no observed construction-start date in NYC Open
Data, and this module does not pretend otherwise.

--------------------------------------------------------------------------
FAIL LOUD
--------------------------------------------------------------------------
`fetch_*` raises on a missing required column and on a batch that errors. It
does NOT raise on a job with no permit rows: that is a real and common state
(a DCP-permitted job whose permit predates the feed's coverage), and it lands
as permit_evidence_source IS NULL, activity_status 'n/a' or 'stalled' by the
DCP-date branch -- never as a silent 'active'. But a run in which NO job in
scope matched ANY permit row raises: that is a broken join, and it would read
downstream as "every permitted building in Brooklyn has been abandoned".
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

SOURCE_ID = "nyc_dob_permits"
DOMAIN = "https://data.cityofnewyork.us"
TIMEOUT = 300
PAGE = 50_000
BATCH = 200          # job numbers per $where ... in (...) clause
RETRIES = 6          # Socrata 500/503s on these two datasets are routine

BIS_DATASET = "ipu4-2q9a"      # DOB Permit Issuance
NOW_DATASET = "rbx6-tga4"      # DOB NOW: Build - Approved Permits

BIS_REQUIRED = ("job__", "job_type", "permit_type", "permit_status",
                "filing_status", "issuance_date", "expiration_date")
NOW_REQUIRED = ("job_filing_number", "work_type", "filing_reason",
                "permit_status", "issued_date", "expired_date")

#: The stages the activity axis is ABOUT. A `filed` job has no permit to be
#: active about and a `complete` job's permits are history; fetching evidence
#: for them would quadruple the request count to populate 'n/a' and 'complete'.
ACTIVITY_STAGES = ("permitted", "partially_complete")

#: The rule's two constants. Twelve months because a DOB permit runs one year
#: and renewal is the routine act of a live job; five years because that is the
#: window D62 caveat 3 measured the 23% zombie share over.
ACTIVE_MONTHS = 12
ZOMBIE_YEARS = 5

ACTIVITY_STATUSES = ("active", "lapsed", "stalled", "complete", "n/a")

#: A permit dated outside this window is a data-entry error, not a fact --
#: the same posture sql/011 takes to bs8b-p36w's `2105-11-05`. Issuance in the
#: future is dropped; EXPIRY in the future is the whole point and is kept, but
#: capped, because a 2099 expiry would make a dead job immortal.
PERMIT_MIN_DATE = dt.date(1990, 1, 1)
EXPIRY_MAX_YEARS = 10


# ------------------------------------------------------------------- fetch

def _columns(dataset_id: str, session: requests.Session) -> list[str]:
    resp = session.get(f"{DOMAIN}/api/views/{dataset_id}.json", timeout=TIMEOUT)
    resp.raise_for_status()
    return [c.get("fieldName") for c in resp.json().get("columns", [])]


def _assert_fields(dataset_id: str, present: list[str], required: tuple[str, ...]) -> None:
    missing = [f for f in required if f not in present]
    if missing:
        raise RuntimeError(
            f"dob_permits: dataset {dataset_id} no longer exposes {missing}. "
            f"Re-derive the column names from {DOMAIN}/api/views/{dataset_id}.json "
            f"before ingesting -- a NULL permit date here reads downstream as "
            f"'this building was abandoned', which is a confident false negative."
        )


def _get(session: requests.Session, dataset_id: str, params: dict) -> list[dict]:
    """One Socrata GET with bounded retry. These two datasets 500/503 under
    load often enough that a single failure must not abort a 25-batch run --
    but exhausting the retries RAISES, because a silently-skipped batch is a
    block of buildings that would all read as 'no permit evidence'."""
    import time

    last: object = None
    for attempt in range(RETRIES):
        try:
            resp = session.get(f"{DOMAIN}/resource/{dataset_id}.json",
                               params=params, timeout=TIMEOUT)
            if resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                time.sleep(3 + 4 * attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:   # pragma: no cover - network
            last = exc
            time.sleep(3 + 4 * attempt)
    raise RuntimeError(
        f"dob_permits: {dataset_id} failed after {RETRIES} attempts ({last}). "
        f"Refusing to continue -- a dropped batch would mark every job in it "
        f"as having no permit evidence."
    )


def _batched_fetch(session: requests.Session, dataset_id: str, key_expr: str,
                   keys: list[str], select: tuple[str, ...]) -> pd.DataFrame:
    """`SELECT select FROM dataset WHERE key_expr IN (batch)`, batched.

    `key_expr` is a SoQL expression, not necessarily a column: DOB NOW needs
    `substring(job_filing_number, 1, 9)` because its key carries a work-type
    suffix (see the module docstring's JOIN KEY block).
    """
    rows: list[dict] = []
    for start in range(0, len(keys), BATCH):
        chunk = keys[start:start + BATCH]
        inlist = ",".join("'" + k.replace("'", "") + "'" for k in chunk)
        offset = 0
        while True:
            batch = _get(session, dataset_id, {
                "$select": ",".join(select),
                "$where": f"{key_expr} in ({inlist})",
                "$limit": PAGE, "$offset": offset, "$order": ":id",
            })
            rows.extend(batch)
            if len(batch) < PAGE:
                break
            offset += PAGE
    return pd.DataFrame(rows)


def fetch_bis_permits(job_numbers: list[str],
                      session: requests.Session | None = None) -> pd.DataFrame:
    """ipu4-2q9a rows for BIS-shaped job numbers. `job__` is the join key."""
    sess = session or requests.Session()
    if not job_numbers:
        return pd.DataFrame(columns=list(BIS_REQUIRED))
    _assert_fields(BIS_DATASET, _columns(BIS_DATASET, sess), BIS_REQUIRED)
    return _batched_fetch(sess, BIS_DATASET, "job__", job_numbers, BIS_REQUIRED)


def fetch_now_permits(job_numbers: list[str],
                      session: requests.Session | None = None) -> pd.DataFrame:
    """rbx6-tga4 rows for DOB NOW job numbers, joined on the 9-character
    prefix of `job_filing_number` (the work-type suffix is stripped)."""
    sess = session or requests.Session()
    if not job_numbers:
        return pd.DataFrame(columns=list(NOW_REQUIRED))
    _assert_fields(NOW_DATASET, _columns(NOW_DATASET, sess), NOW_REQUIRED)
    return _batched_fetch(sess, NOW_DATASET, "substring(job_filing_number, 1, 9)",
                          job_numbers, NOW_REQUIRED)


# --------------------------------------------------------------- normalize

def _to_date_mixed(series: pd.Series) -> pd.Series:
    """ipu4-2q9a's date columns are TEXT and carry TWO formats in the same
    column -- `2014-09-09` on some rows and `09/30/2013` on others, verified on
    job 104869108. Parsed explicitly in both shapes rather than with a single
    inferred format: `format='mixed'` would silently read `09/10/2013` as a
    September date on one row and an October date on another if pandas' guess
    flipped between chunks, and these dates decide whether a building is called
    abandoned."""
    raw = series.astype(str).str.strip()
    us = pd.to_datetime(raw, errors="coerce", format="%m/%d/%Y")
    iso = pd.to_datetime(raw.str.slice(0, 10), errors="coerce", format="%Y-%m-%d")
    return us.fillna(iso)


def _to_date_iso(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", format="ISO8601")


def _clean_dates(frame: pd.DataFrame, asof: dt.date) -> pd.DataFrame:
    """Drop impossible dates rather than clamping them (sql/011's posture).

    An ISSUANCE in the future is a typo; keeping it would make a dead job look
    renewed. An EXPIRY in the future is the signal itself and is kept, but one
    more than EXPIRY_MAX_YEARS out is a typo too and is nulled -- otherwise a
    single fat-fingered `2125` makes a zombie permit permanently `active`.
    """
    cap = pd.Timestamp(dt.date(asof.year + EXPIRY_MAX_YEARS, asof.month,
                               min(asof.day, 28)))
    floor = pd.Timestamp(PERMIT_MIN_DATE)
    today = pd.Timestamp(asof)
    # datetime64 throughout, NOT datetime.date: the min()/max() in
    # permit_evidence run inside a groupby, and an object-dtype column of
    # datetime.date + None makes pandas fall back to a Python-level max that
    # raises on the None. Converted to date once, at the very end.
    issued = frame["issued"].where(
        frame["issued"].notna() & (frame["issued"] >= floor) & (frame["issued"] <= today))
    expires = frame["expires"].where(
        frame["expires"].notna() & (frame["expires"] >= floor) & (frame["expires"] <= cap))
    return frame.assign(issued=issued, expires=expires)


def permit_evidence(bis: pd.DataFrame, now: pd.DataFrame,
                    asof: dt.date | None = None) -> pd.DataFrame:
    """The two permit feeds -> ONE ROW PER job_number.

    Columns: job_number, last_permit_issued, last_permit_expires,
             first_permit_issued, n_permit_rows, permit_evidence_source.

    THE DOUBLE-COUNT GUARD. A DOB NOW job has one permit row per work type and
    a fresh row for every renewal (job M00528469 has 8 rows across 4 work
    types); a BIS job has one row per permit type per sequence number, and
    ipu4-2q9a additionally contains EXACT DUPLICATE rows (job 321590532
    appears twice, byte-identical). Every aggregate here is min(), max() or
    count-of-rows -- min/max are idempotent under duplication, so a duplicated
    feed cannot move a date. `n_permit_rows` is the one count and it is
    diagnostic only; nothing downstream multiplies units by it.

    `last_permit_expires` is a MAX over ALL of a job's permits, i.e. "is ANY
    authorisation still live", not "is every work type current". A job with a
    current General Construction permit and a long-expired Plumbing permit is
    active, which is the correct reading: the building is being built.
    """
    asof = asof or dt.date.today()
    frames = []

    if len(bis):
        frames.append(pd.DataFrame({
            "job_number": bis["job__"].astype(str).str.strip().str.upper(),
            "issued": _to_date_mixed(bis["issuance_date"]),
            "expires": _to_date_mixed(bis["expiration_date"]),
            "feed": "dob_bis_permits",
        }))

    if len(now):
        frames.append(pd.DataFrame({
            # the work-type suffix is dropped HERE, once, so nothing downstream
            # has to know rbx6-tga4's key shape.
            "job_number": now["job_filing_number"].astype(str).str.strip()
                             .str.upper().str.slice(0, 9),
            "issued": _to_date_iso(now["issued_date"]),
            "expires": _to_date_iso(now["expired_date"]),
            "feed": "dob_now_permits",
        }))

    cols = ["job_number", "last_permit_issued", "last_permit_expires",
            "first_permit_issued", "n_permit_rows", "permit_evidence_source"]
    if not frames:
        return pd.DataFrame(columns=cols)

    permits = pd.concat(frames, ignore_index=True)
    permits = permits[permits["job_number"].notna() & (permits["job_number"] != "")]
    permits = _clean_dates(permits, asof)
    # a row with neither a usable issuance nor a usable expiry carries nothing
    permits = permits[permits["issued"].notna() | permits["expires"].notna()]
    if permits.empty:
        return pd.DataFrame(columns=cols)

    grouped = permits.groupby("job_number", as_index=False).agg(
        last_permit_issued=("issued", "max"),
        first_permit_issued=("issued", "min"),
        last_permit_expires=("expires", "max"),
        n_permit_rows=("feed", "size"),
        n_feeds=("feed", "nunique"),
        one_feed=("feed", "first"),
    )
    grouped["permit_evidence_source"] = grouped.apply(
        lambda r: "both" if r["n_feeds"] > 1 else r["one_feed"], axis=1)
    for col in ("last_permit_issued", "first_permit_issued", "last_permit_expires"):
        grouped[col] = grouped[col].dt.date.where(grouped[col].notna())
    return grouped[cols]


# ------------------------------------------------------------ the rule

def _months_before(asof: dt.date, months: int) -> dt.date:
    """asof minus `months` calendar months. Duplicated from model/dev_pipeline
    deliberately: importing the model from a source adapter would invert the
    dependency direction every other adapter here respects."""
    total = asof.month - 1 - months
    year = asof.year + total // 12
    month = total % 12 + 1
    day = min(asof.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.date(year, month, day)


def classify_activity(jobs: pd.DataFrame, asof: dt.date | None = None) -> pd.Series:
    """activity_status for each row of `jobs`.

    Required columns: stage, date_complete, date_permitted, last_permit_issued,
    last_permit_expires. Pure: no database, no network, so the rule boundaries
    are unit-testable to the day.

    The order below IS the rule; see the module docstring. Note that `active`
    is checked before `lapsed` and `stalled`, so a job with one dead permit and
    one live one is active, and that the ZOMBIE_YEARS branch fires only when no
    expiry is known at all -- where an expiry exists it already decides, and
    a five-year-old job that renewed last month is active, not a zombie.
    """
    asof = asof or dt.date.today()
    fresh = _months_before(asof, ACTIVE_MONTHS)
    zombie = dt.date(asof.year - ZOMBIE_YEARS, asof.month, min(asof.day, 28))

    def _d(value):
        if value is None or value is pd.NaT:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.date()
        return value if isinstance(value, dt.date) else None

    out = []
    for row in jobs.itertuples(index=False):
        stage = getattr(row, "stage", None)
        complete = _d(getattr(row, "date_complete", None))
        issued = _d(getattr(row, "last_permit_issued", None))
        expires = _d(getattr(row, "last_permit_expires", None))
        permitted = _d(getattr(row, "date_permitted", None))

        if stage == "complete" or complete is not None:
            out.append("complete")
        elif stage in ("filed", "withdrawn"):
            out.append("n/a")
        elif (issued is not None and issued >= fresh) or \
             (expires is not None and expires >= asof):
            out.append("active")
        elif expires is not None and expires >= fresh:
            out.append("lapsed")
        elif expires is not None:
            out.append("stalled")
        elif (issued or permitted) is not None and (issued or permitted) < zombie:
            out.append("stalled")
        else:
            out.append("n/a")
    return pd.Series(out, index=jobs.index, dtype="object")


def build_activity(jobs: pd.DataFrame, evidence: pd.DataFrame,
                   asof: dt.date | None = None) -> pd.DataFrame:
    """analysis.dev_pipeline rows LEFT JOINed to the collapsed permit evidence,
    classified. Returns job_number + the four UPDATE columns + provenance.

    The join cannot fan out: `evidence` is one row per job_number by
    construction (permit_evidence groups on it) and `jobs` is the primary key
    of analysis.dev_pipeline. Asserted, not assumed.
    """
    asof = asof or dt.date.today()
    merged = jobs.merge(evidence, on="job_number", how="left")
    if len(merged) != len(jobs):
        raise RuntimeError(
            "dob_permits: the permit-evidence join fanned out -- permit_evidence() "
            "is not one row per job_number. Every activity verdict below would be "
            "assigned to a duplicated job."
        )
    merged["activity_status"] = classify_activity(merged, asof=asof)
    merged["permit_activity_provenance"] = (
        f"{BIS_DATASET} + {NOW_DATASET} DOB permit issuance/renewal as of "
        f"{asof.isoformat()}; rule active<={ACTIVE_MONTHS}mo / "
        f"zombie>{ZOMBIE_YEARS}y (sql/014_dev_pipeline_activity.sql)"
    )
    return merged[["job_number", "last_permit_issued", "last_permit_expires",
                   "permit_evidence_source", "activity_status",
                   "permit_activity_provenance"]]


# ----------------------------------------------------------------- persist

def write_activity(con, df: pd.DataFrame, boroughs: tuple[str, ...]) -> int:
    """UPDATE-only on analysis.dev_pipeline. Two passes, mirroring
    model/dev_pipeline.write_pipeline:

      1. RESET the five activity columns to NULL for every job in scope --
         without it a job that was 'stalled' last run and has since been
         restated away keeps last run's verdict forever.
      2. UPDATE ... FROM the classified frame on job_number.

    It never INSERTs and never DELETEs, so it cannot move `stage`, `net_units`,
    `date_complete` or any other DCP-derived column, and `loci
    ingest-dcp-housing` remains the only writer of the row itself.
    """
    if not boroughs:
        return 0
    holes = ", ".join("?" for _ in boroughs)
    con.execute(f"""
        UPDATE analysis.dev_pipeline
        SET last_permit_issued = NULL, last_permit_expires = NULL,
            permit_evidence_source = NULL, activity_status = NULL,
            permit_activity_asof = NULL
        WHERE borough IN ({holes})
    """, list(boroughs))
    if df.empty:
        return 0
    con.register("_pa", df)
    try:
        con.execute("""
            UPDATE analysis.dev_pipeline AS d
            SET last_permit_issued     = CAST(_pa.last_permit_issued AS DATE),
                last_permit_expires    = CAST(_pa.last_permit_expires AS DATE),
                permit_evidence_source = _pa.permit_evidence_source,
                activity_status        = _pa.activity_status,
                permit_activity_asof   = CAST(_pa.permit_activity_asof AS DATE),
                provenance             = CASE
                    WHEN d.provenance IS NULL THEN _pa.permit_activity_provenance
                    WHEN position(_pa.permit_activity_provenance IN d.provenance) > 0
                        THEN d.provenance
                    ELSE d.provenance || ' + ' || _pa.permit_activity_provenance
                END
            FROM _pa
            WHERE d.job_number = _pa.job_number
        """)
    finally:
        con.unregister("_pa")
    return len(df)


def load_jobs(con, boroughs: tuple[str, ...],
              stages: tuple[str, ...] = ACTIVITY_STAGES) -> pd.DataFrame:
    """The jobs whose activity is in question, read-only."""
    bh = ", ".join("?" for _ in boroughs)
    sh = ", ".join("?" for _ in stages)
    return con.execute(f"""
        SELECT job_number, borough, stage, net_units,
               date_permitted, date_complete
        FROM analysis.dev_pipeline
        WHERE borough IN ({bh}) AND stage IN ({sh})
        ORDER BY job_number
    """, list(boroughs) + list(stages)).fetchdf()


def build(con, boroughs: tuple[str, ...] = ("MN", "BK"), *,
          asof: dt.date | None = None, dry_run: bool = False,
          session: requests.Session | None = None,
          stages: tuple[str, ...] = ACTIVITY_STAGES) -> tuple[pd.DataFrame, dict]:
    """Fetch permit evidence for the in-scope jobs, classify, (optionally) write."""
    asof = asof or dt.date.today()
    sess = session or requests.Session()

    jobs = load_jobs(con, boroughs, stages)
    if jobs.empty:
        raise RuntimeError(
            f"dob_permits: analysis.dev_pipeline has no {list(stages)} jobs for "
            f"{list(boroughs)}. Run `loci ingest-dcp-housing` first -- there is "
            f"nothing whose construction progress could be measured."
        )

    ids = jobs["job_number"].astype(str).str.strip().str.upper()
    bis_ids = sorted(ids[ids.str.fullmatch(r"[0-9]{9}")].unique())
    now_ids = sorted(ids[ids.str.fullmatch(r"[A-Z][0-9]{8}")].unique())
    other = int(len(ids.unique()) - len(bis_ids) - len(now_ids))

    bis = fetch_bis_permits(bis_ids, session=sess)
    now = fetch_now_permits(now_ids, session=sess)
    evidence = permit_evidence(bis, now, asof=asof)

    matched = int(jobs["job_number"].isin(set(evidence["job_number"])).sum())
    if matched == 0:
        raise RuntimeError(
            f"dob_permits: NONE of {len(jobs):,} in-scope jobs matched a permit "
            f"row in {BIS_DATASET} or {NOW_DATASET}. That is a broken join, not a "
            f"city that stopped building -- every job would be classified from "
            f"DCP's date alone and most of them would read as 'stalled'."
        )

    out = build_activity(jobs, evidence, asof=asof)
    out["permit_activity_asof"] = asof

    joined = jobs.merge(out, on="job_number", how="left")
    report = {
        "asof": asof.isoformat(),
        "jobs_in_scope": len(jobs),
        "bis_jobs": len(bis_ids), "now_jobs": len(now_ids), "other_shape": other,
        "bis_permit_rows": len(bis), "now_permit_rows": len(now),
        "jobs_with_evidence": matched,
        "jobs_without_evidence": len(jobs) - matched,
        "by_status": joined.groupby("activity_status")["net_units"]
                           .agg(["count", "sum"]).to_dict("index"),
        "renewed_last_12mo": int((pd.to_datetime(out["last_permit_issued"])
                                  >= pd.Timestamp(_months_before(asof, ACTIVE_MONTHS))).sum()),
    }
    if not dry_run:
        report["_written"] = write_activity(con, out, boroughs)
    return out, report
