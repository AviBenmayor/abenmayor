"""The seven NYC/NYS filing feeds -> the staging.storefront_filing contract.

This is the ONLY module in the project that knows these feeds' raw column
names. Everything downstream reads `stage`, `filed_on`, `business_name_key`,
`bbl` -- never `owner_s_business_name` or `premisescounty`. Same contract
boundary sources/base.py draws for staging.poi.

THREE NEW SOURCES (registered in registry.yaml this pass)
---------------------------------------------------------
  nyc_sla_pending_licenses     f8i8-k2gm (data.ny.gov)   -> liquor_application
  nyc_dob_now_job_filings      w9ak-ipjd                 -> fitout_filing
  nyc_dcwp_license_applications ptev-4hud                -> license_application

FOUR ALREADY-INGESTED SOURCES, mapped onto the same table so it is the COMPLETE
lifecycle rather than only its front half
-----------------------------------------
  nyc_dob_permit_issuance      rbx6-tga4  -> permit_issued, sign_permit
  nyc_dcwp_licenses            w7w3-xahh  -> license_issued
  nyc_sla_liquor_licenses      9s3h-dpkz  -> liquor_active
  nyc_dohmh_restaurants        43nn-pn8j  -> first_inspection

--------------------------------------------------------------------------
NO TRAILING WINDOW (2026-09-16) -- SUPERSEDES THE 24-MONTH CLIP
--------------------------------------------------------------------------
Every feed is pulled in FULL HISTORY. `since=None` is the default on every
fetcher and it emits NO date predicate at all; `WINDOW_MONTHS` survives only
as the argument to `window_start()` for a caller that explicitly asks for a
window on the command line.

The clip it replaces was `WINDOW_MONTHS = 24`, justified by "the question is
who is opening NOW". That justification does not survive a backtest: a rewind
to t0 = 2020 needs the filings as they stood in 2020, and a 24-month window
anchored on today's date makes every pre-2024 cohort literally unobservable.
The probe measured `staging.storefront_filing` at ZERO rows before
2024-09-13 for DOB, DCWP and SLA -- a hole we cut, not one the city has.
DCWP's own file reaches 1997.

WHAT FULL HISTORY DOES AND DOES NOT BUY, per feed (measured 2026-09-16):

  w7w3-xahh  DCWP licences        72,452 rows, license_creation_date 1997-2026.
                                  Real history. This is the survival instrument.
  ipu4-2q9a  DOB BIS permits      3,990,436 rows; AL+SG = 439,700. Reaches the
                                  1990s and is the ONLY DOB permit source that
                                  covers 2020 -- see the BIS section below,
                                  which full history REVERSES.
  rbx6-tga4  DOB NOW permits      235,908 GC+Sign rows, but 2,817 in 2020 vs
                                  41,972 in 2023: DOB NOW rolled out over 2021.
                                  Its pre-2021 counts are a rollout curve, not
                                  a construction cycle, and must never be read
                                  as a trend.
  w9ak-ipjd  DOB NOW filings      194,244 storefront-filtered; same rollout
                                  caveat, same years.
  ptev-4hud  DCWP applications    65,932 rows, submission_date 2023-2026 ONLY.
                                  DCWP does not publish applications before
                                  2023. An UPSTREAM limit, not our clip.
  9s3h-dpkz  SLA active licences  24,853 NYC rows but originalissuedate is
                                  2023+ for 24,262 of them. This is a CURRENT
                                  ACTIVES snapshot: a licence that lapsed
                                  before today is simply not in the file, so
                                  "full history" of the feed is not history of
                                  licensing. It cannot support a 2020 rewind
                                  and nothing on the portal replaces it.
  f8i8-k2gm  SLA pending          1,572 NYC rows; a pending-application queue,
                                  by construction current-state only.
  43nn-pn8j  DOHMH                already the full current file. Unchanged.

So of the seven original feeds, full history genuinely reaches 2020 for DCWP
licences and (via the new BIS feed) DOB permits. The two SLA feeds and the
DCWP application feed are current-state or short-history AT SOURCE, and the
rewind must say so rather than let a thin year read as a quiet market.

--------------------------------------------------------------------------
BIS PERMITS (ipu4-2q9a) ARE NOW INGESTED -- THE OBJECTION WAS THE WINDOW
--------------------------------------------------------------------------
ipu4-2q9a's `issuance_date` is TEXT carrying TWO formats in one column
(`2014-09-09` and `09/30/2013`), so a Socrata `$where` on it compares
LEXICALLY and a server-side 24-month window is impossible -- the reason this
feed was excluded on 2026-09-13.

FULL HISTORY REMOVES THE OBJECTION ENTIRELY: with no date predicate there is
nothing to compare lexically. The dates are parsed client-side by
`_date_mixed`, which handles both formats and is the same rule
dob_permits._to_date_mixed already applies.

The feed is filtered server-side on `permit_type in ('AL','SG')` -- Alteration
and Sign. That is not a data cap; it is the SAME storefront rule already
applied to rbx6-tga4 (`work_type in ('General Construction','Sign')`),
expressed in BIS's own vocabulary. NB (new building) and DM (demolition) are
excluded for the reason EXCLUDED_JOB_TYPES gives; EW/PL/EQ (equipment,
plumbing, boilers) are excluded for the reason STOREFRONT_WORK_TYPES gives --
1.79M equipment permits are boiler swaps, and adding them would bury the
storefront signal rather than enlarge it.

BIS AND DOB NOW OVERLAP AND MUST NOT BE SUMMED WITHOUT THINKING. BIS accepts
no NEW job filings after the DOB NOW cutover, but it still issues permits
against old BIS jobs, so 2021-2024 contains both. They are separate `source`
values and `filing_id` carries the source, so nothing double-counts inside
staging.storefront_filing -- but a chart of "permits per year" that pools them
will show a hump at the cutover that is an artefact of two systems running in
parallel, not a building boom.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from loci.sources.cities.nyc import socrata
from loci.sources.cities.nyc.nys_sla import COUNTY_BOROUGH

#: The contract every fetcher in this module returns, in order. `bbl_raw` is
#: the feed's own BBL string before validation; model/storefront_filing.py
#: turns it into `bbl` + `match_method`.
FEED_COLUMNS = (
    "source", "stage", "business_name", "bbl_raw", "bin", "house_number",
    "street_name", "borough", "lon", "lat", "filed_on", "status",
    "status_date", "category_hint", "license_type", "raw_id", "provenance",
)

#: NOT a default any more. Kept for `window_start()`, which the CLI's explicit
#: `--window-months` opt-in calls. Every fetcher defaults to `since=None`,
#: which emits NO date predicate: full history. See the module docstring.
WINDOW_MONTHS = 24

#: NYC borough names as the several feeds spell them -> the project's codes.
BOROUGH_CODE = {
    "manhattan": "MN", "new york": "MN", "mn": "MN", "1": "MN",
    "bronx": "BX", "the bronx": "BX", "bx": "BX", "2": "BX",
    "brooklyn": "BK", "kings": "BK", "bk": "BK", "3": "BK",
    "queens": "QN", "qn": "QN", "4": "QN",
    "staten island": "SI", "richmond": "SI", "si": "SI", "5": "SI",
}

NYC_COUNTIES = ("Kings", "New York", "Bronx", "Queens", "Richmond")


def window_start(asof: dt.date, months: int = WINDOW_MONTHS) -> dt.date:
    """`asof` minus `months` calendar months, clamped to a valid day."""
    total = asof.month - 1 - months
    year = asof.year + total // 12
    month = total % 12 + 1
    return dt.date(year, month, min(asof.day, 28))


def _since_pred(column: str, since: dt.date | None) -> str | None:
    """The `>= since` half of a $where, or None when the pull is unclipped.

    Returning None rather than a tautology like `1=1` matters: the predicate is
    concatenated into provenance, and a row whose provenance says
    "filed_on >= 1900-01-01" is claiming a window that was never applied.
    """
    if since is None:
        return None
    return f"{column} >= '{since.isoformat()}T00:00:00'"


def _and(*parts: str | None) -> str | None:
    """Join the non-empty predicates, or None if there are none at all.

    None must reach socrata.fetch as `where=None` so no `$where` is sent --
    an empty string would become `$where=` and Socrata answers that with a 400.
    """
    kept = [p for p in parts if p]
    return " AND ".join(kept) if kept else None


def _window_note(since: dt.date | None) -> str:
    return (f"{since.isoformat()} onward" if since else "FULL HISTORY (no clip)")


def _boro(value) -> str | None:
    return BOROUGH_CODE.get(str(value or "").strip().lower())


def _date(value) -> dt.date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _date_mixed(value) -> dt.date | None:
    """BIS publishes `2014-09-09` and `09/30/2013` in the SAME TEXT COLUMN.

    Both are parsed here; anything else becomes NULL and is counted by the
    caller rather than guessed at. Same rule as dob_permits._to_date_mixed --
    duplicated rather than imported because that module owns a different
    contract and importing across it for four lines would couple them.
    """
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    try:
        return dt.date.fromisoformat(v[:10])
    except ValueError:
        pass
    parts = v[:10].split("/")
    if len(parts) == 3:
        try:
            m, d, y = (int(x) for x in parts)
            return dt.date(y, m, d)
        except ValueError:
            return None
    return None


def _float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # The five-borough bbox, plus margin. A literal (0, 0) null island -- which
    # DOHMH, DCWP and the SLA all publish -- must become NULL, not a point off
    # the coast of Africa that the nearest-lot matcher would then try to place.
    return f if f != 0.0 else None


def _point_ok(lon, lat) -> tuple[float | None, float | None]:
    if lon is None or lat is None:
        return None, None
    if not (40.4 <= lat <= 41.0 and -74.3 <= lon <= -73.6):
        return None, None
    return lon, lat


def _frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records, columns=list(FEED_COLUMNS))
    return df


# --------------------------------------------------------------- 1. SLA pending

SLA_PENDING_DATASET = "f8i8-k2gm"
SLA_PENDING_REQUIRED = ("application_id", "premises_county", "description",
                        "legalname", "dba", "actual_address_of_premises",
                        "received_date", "status", "georeference", "class",
                        "type")


def fetch_sla_pending(*, asof: dt.date | None = None, limit: int | None = None,
                      since: dt.date | None = None,
                      use_cache: bool = True, session=None) -> pd.DataFrame:
    """SLA Pending Licenses -> stage `liquor_application`.

    THE EARLIEST SIGNAL IN THE WHOLE TABLE. An SLA application requires a
    signed lease and a 30-day notice to the community board; it is filed months
    before a bar or restaurant opens, and (unlike a DOB filing) it names the
    TENANT, not the landlord.

    Statewide file -- 2,925 rows on the 2026-09-13 extract, of which 1,574 are
    NYC. Filtered server-side on `premises_county`, the SLA's own county field,
    the same five values nys_sla.py already uses.

    NO BBL, NO BIN, NO HOUSE/STREET SPLIT. One free-text
    `actual_address_of_premises` and a `georeference` point. So every row of
    this feed reaches the BBL matcher through the point ladder, and its match
    rate is structurally lower than the feeds that publish a BBL.
    """
    asof = asof or dt.date.today()
    counties = ", ".join(f"'{c}'" for c in NYC_COUNTIES)
    where = _and(f"premises_county in ({counties})",
                 _since_pred("received_date", since))
    socrata.assert_fields(socrata.NYS_DOMAIN, SLA_PENDING_DATASET,
                          SLA_PENDING_REQUIRED, session=session)
    rows = socrata.fetch(
        "nyc_sla_pending_licenses", socrata.NYS_DOMAIN, SLA_PENDING_DATASET,
        select=",".join(SLA_PENDING_REQUIRED), where=where, limit=limit,
        asof=asof, use_cache=use_cache, session=session)

    prov = (f"{SLA_PENDING_DATASET} (NYS SLA Current Pending Licenses), "
            f"received_date {_window_note(since)}, NYC counties, "
            f"asof {asof.isoformat()}")
    out = []
    for r in rows:
        geo = r.get("georeference") or {}
        coords = geo.get("coordinates") or [None, None]
        lon, lat = _point_ok(_float(coords[0]), _float(coords[1]))
        out.append({
            "source": "nyc_sla_pending_licenses", "stage": "liquor_application",
            # DBA is the awning; legalname is the LLC. Prefer the awning, fall
            # back to the entity, because a blank DBA is common on a brand-new
            # application that has not chosen its signage yet.
            "business_name": (r.get("dba") or r.get("legalname") or "").strip() or None,
            "bbl_raw": None, "bin": None,
            "house_number": None,
            "street_name": (r.get("actual_address_of_premises") or "").strip() or None,
            "borough": COUNTY_BOROUGH.get(
                (r.get("premises_county") or "").strip().lower()),
            "lon": lon, "lat": lat,
            "filed_on": _date(r.get("received_date")),
            "status": (r.get("status") or "").strip() or None,
            "status_date": None,      # the feed publishes no status-change date
            "category_hint": (r.get("description") or "").strip() or None,
            "license_type": f"type {r.get('type')} class {r.get('class')}",
            "raw_id": r.get("application_id"),
            "provenance": prov,
        })
    return _frame(out)


# ------------------------------------------------------- 2. DOB NOW job filings

DOB_NOW_DATASET = "w9ak-ipjd"
DOB_NOW_FIELDS = ("job_filing_number", "job_type", "building_type",
                  "filing_status", "house_no", "street_name", "borough",
                  "bin", "bbl", "latitude", "longitude",
                  "owner_s_business_name", "job_description",
                  "general_construction_work_type_", "sign",
                  "place_of_assembly_work_type_", "filing_date",
                  "current_status_date", "first_permit_date")

#: Job types that cannot be a storefront fit-out.
#:   New Building / ALT-CO - New Building with Existing Elements to Remain
#:       -- the ground floor does not exist yet. A retail tenant fitting out a
#:          brand-new base files a SEPARATE Alteration once the shell is up,
#:          and that filing is what this table wants.
#:   Full Demolition -- the opposite event.
#:   No Work -- a paperwork-only filing (a letter of completion, a withdrawal).
#: `ALT-CO - New Building...` is excluded for the same reason as New Building;
#: `Alteration CO` is KEPT, because a change of certificate of occupancy on an
#: EXISTING building is precisely a conversion to (or between) commercial uses.
EXCLUDED_JOB_TYPES = ("New Building", "Full Demolition", "No Work",
                      "ALT-CO - New Building with Existing Elements to Remain")

#: Building types that are pure residential. DOB NOW's `building_type` is a
#: coarse four-value field: 1/2/3 Family, or 'Other'. 'Other' is everything
#: else INCLUDING mixed-use, which is where ground-floor retail lives, so the
#: filter can only remove the small-house tail -- it cannot isolate commercial.
EXCLUDED_BUILDING_TYPES = ("1 Family", "2 Family", "3 Family")

#: At least one of these work types must be declared. Rationale per column:
#:   general_construction -- the interior build-out itself. Any fit-out has it.
#:   sign                 -- an awning. The single most storefront-specific
#:                           thing DOB permits, and it is filed by the TENANT.
#:   place_of_assembly    -- an occupancy >74 persons: a bar, a restaurant, a
#:                           gym, a place of worship. Never an apartment.
#: Plumbing / mechanical / sprinkler are deliberately NOT in the list: they are
#: the most common filings in the city (a boiler swap, a bathroom) and adding
#: them would triple the row count with overwhelmingly residential work.
STOREFRONT_WORK_TYPES = ("general_construction_work_type_", "sign",
                         "place_of_assembly_work_type_")


def dob_now_where(asof: dt.date, since: dt.date | None = None) -> str | None:
    """The storefront filter, as one server-side SoQL predicate.

    Applied at the portal, not in pandas, because the unfiltered 24-month
    window is 314,822 rows and the filtered set is 68,678 (measured
    2026-09-13). Cascade, same extract:

        filing_date >= asof-24mo                     314,822
        ... and job_type not excluded                275,771   (-39,051)
        ... and building_type not 1/2/3 family       203,386   (-72,385)
        ... and >=1 storefront work type              68,678  (-134,708)

    i.e. the rule drops 246,144 of 314,822 filings, 78.2%.
    """
    jobs = ", ".join(f"'{j}'" for j in EXCLUDED_JOB_TYPES)
    bldgs = ", ".join(f"'{b}'" for b in EXCLUDED_BUILDING_TYPES)
    work = " OR ".join(f"{c}='YES'" for c in STOREFRONT_WORK_TYPES)
    return _and(_since_pred("filing_date", since),
                f"job_type not in ({jobs})",
                f"building_type not in ({bldgs})",
                f"({work})")


def fetch_dob_now_filings(*, asof: dt.date | None = None,
                          limit: int | None = None,
                          since: dt.date | None = None, use_cache: bool = True,
                          session=None) -> tuple[pd.DataFrame, dict]:
    """DOB NOW Job Application Filings -> stage `fitout_filing`.

    Returns (frame, drop_report). The report carries the cascade counts so
    `loci filings ingest` can print exactly how many rows the storefront rule
    removed -- the rule is a judgement call and must be auditable.

    CAVEAT THE DATABASE CANNOT ENFORCE: `owner_s_business_name` is the OWNER,
    which on a commercial fit-out is usually the LANDLORD, not the tenant
    ("AVERY HALL INVESTMENTS", "637 WILSON MGT.", and a literal "N/A" on the
    2026-09-13 extract). So this stage's `business_name_key` joins to the
    chains table far worse than the licence feeds do, and a fit-out filing is
    best used as a PLACE signal (this BBL is being built out) rather than a
    NAME signal. `job_description` is carried as `category_hint` so a later
    pass can read the intent out of the free text.
    """
    asof = asof or dt.date.today()
    where = dob_now_where(asof, since)
    socrata.assert_fields(socrata.NYC_DOMAIN, DOB_NOW_DATASET,
                          DOB_NOW_FIELDS, session=session)
    rows = socrata.fetch(
        "nyc_dob_now_job_filings", socrata.NYC_DOMAIN, DOB_NOW_DATASET,
        select=",".join(DOB_NOW_FIELDS), where=where, limit=limit,
        asof=asof, use_cache=use_cache, session=session)

    prov = (f"{DOB_NOW_DATASET} (DOB NOW: Build - Job Application Filings), "
            f"filing_date {_window_note(since)}, storefront filter "
            f"(job_type/building_type/work-type), asof {asof.isoformat()}")
    out = []
    for r in rows:
        lon, lat = _point_ok(_float(r.get("longitude")), _float(r.get("latitude")))
        work = [c for c in STOREFRONT_WORK_TYPES
                if (r.get(c) or "").strip().upper() == "YES"]
        out.append({
            "source": "nyc_dob_now_job_filings", "stage": "fitout_filing",
            "business_name": (r.get("owner_s_business_name") or "").strip() or None,
            "bbl_raw": (r.get("bbl") or "").strip() or None,
            "bin": (r.get("bin") or "").strip() or None,
            "house_number": (r.get("house_no") or "").strip() or None,
            "street_name": (r.get("street_name") or "").strip() or None,
            "borough": _boro(r.get("borough")),
            "lon": lon, "lat": lat,
            "filed_on": _date(r.get("filing_date")),
            "status": (r.get("filing_status") or "").strip() or None,
            "status_date": _date(r.get("current_status_date")),
            "category_hint": (r.get("job_description") or "").strip()[:400] or None,
            "license_type": f"{r.get('job_type')} / " + "+".join(work),
            "raw_id": r.get("job_filing_number"),
            "provenance": prov,
        })
    report = {"kept": len(out), "where": where}
    return _frame(out), report


# --------------------------------------------------- 3. DCWP license applications

DCWP_APPS_DATASET = "ptev-4hud"
DCWP_APPS_FIELDS = ("application_id", "license_number", "business_name",
                    "dba_trade_name", "business_category", "application_type",
                    "license_type", "submission_date", "date_closed", "status",
                    "building_number", "street", "borough", "bin", "bbl",
                    "latitude", "longitude")


def fetch_dcwp_applications(*, asof: dt.date | None = None,
                            limit: int | None = None,
                            since: dt.date | None = None,
                            use_cache: bool = True,
                            session=None) -> pd.DataFrame:
    """DCWP License Applications -> stage `license_application`.

    The APPLICATION side of w7w3-xahh (which holds only issued licences). This
    is where a laundromat, a garage, a newsstand, a sidewalk cafe or a
    second-hand dealer declares itself before it opens, and unlike DOB it names
    the operator and carries a real category.

    `address_type` is not filtered: a business whose licence address is a
    mailing address geocodes to the wrong place, but DCWP publishes BBL and
    lat/lon per row, and dropping non-premises rows would silently delete
    every home-based applicant. Flagged by `match_method` instead.
    """
    asof = asof or dt.date.today()
    where = _since_pred("submission_date", since)
    socrata.assert_fields(socrata.NYC_DOMAIN, DCWP_APPS_DATASET,
                          DCWP_APPS_FIELDS, session=session)
    rows = socrata.fetch(
        "nyc_dcwp_license_applications", socrata.NYC_DOMAIN, DCWP_APPS_DATASET,
        select=",".join(DCWP_APPS_FIELDS), where=where, limit=limit,
        asof=asof, use_cache=use_cache, session=session)

    prov = (f"{DCWP_APPS_DATASET} (NYC DCWP License Applications), "
            f"submission_date {_window_note(since)}, asof {asof.isoformat()}")
    out = []
    for r in rows:
        lon, lat = _point_ok(_float(r.get("longitude")), _float(r.get("latitude")))
        out.append({
            "source": "nyc_dcwp_license_applications",
            "stage": "license_application",
            "business_name": (r.get("dba_trade_name")
                              or r.get("business_name") or "").strip() or None,
            "bbl_raw": (r.get("bbl") or "").strip() or None,
            "bin": (r.get("bin") or "").strip() or None,
            "house_number": (r.get("building_number") or "").strip() or None,
            "street_name": (r.get("street") or "").strip() or None,
            "borough": _boro(r.get("borough")),
            "lon": lon, "lat": lat,
            "filed_on": _date(r.get("submission_date")),
            "status": (r.get("status") or "").strip() or None,
            "status_date": _date(r.get("date_closed")),
            "category_hint": (r.get("business_category") or "").strip() or None,
            "license_type": (r.get("license_type") or "").strip() or None,
            "raw_id": r.get("application_id"),
            "provenance": prov,
        })
    return _frame(out)


# ------------------------------------------- 4/5. DOB NOW approved permits

DOB_PERMITS_DATASET = "rbx6-tga4"
DOB_PERMITS_FIELDS = ("job_filing_number", "work_type", "filing_reason",
                      "permit_status", "issued_date", "expired_date",
                      "house_no", "street_name", "borough", "bin", "bbl",
                      "latitude", "longitude", "owner_business_name",
                      "job_description")

#: work_type -> stage. Only these two are ingested: a Sidewalk Shed permit is
#: not a business opening, and mapping every work type would put 300k rows of
#: scaffolding into a table about storefronts.
PERMIT_WORK_STAGE = {"General Construction": "permit_issued",
                     "Sign": "sign_permit"}


def fetch_dob_permits(*, asof: dt.date | None = None, limit: int | None = None,
                      since: dt.date | None = None,
                      use_cache: bool = True, session=None) -> pd.DataFrame:
    """DOB NOW Approved Permits -> stages `permit_issued` and `sign_permit`.

    ONE SOURCE ROW PRODUCES EXACTLY ONE STAGE, chosen by `work_type` -- this is
    why `filing_id` carries the stage (see sql/019). The two are kept apart
    rather than merged because they mean different things: General Construction
    is "the build-out is authorised", Sign is "the awning is going up", and the
    second is both later and far more specific to a storefront.

    No fan-out guard is needed here because nothing is aggregated: every source
    row becomes one filing row, keyed on its own `job_filing_number` (WITH the
    work-type suffix, which is what makes it unique).
    """
    asof = asof or dt.date.today()
    types = ", ".join(f"'{t}'" for t in PERMIT_WORK_STAGE)
    where = _and(_since_pred("issued_date", since), f"work_type in ({types})")
    socrata.assert_fields(socrata.NYC_DOMAIN, DOB_PERMITS_DATASET,
                          DOB_PERMITS_FIELDS, session=session)
    rows = socrata.fetch(
        "nyc_dob_permit_issuance", socrata.NYC_DOMAIN, DOB_PERMITS_DATASET,
        select=",".join(DOB_PERMITS_FIELDS), where=where, limit=limit,
        asof=asof, use_cache=use_cache, session=session)

    prov = (f"{DOB_PERMITS_DATASET} (DOB NOW: Build - Approved Permits), "
            f"issued_date {_window_note(since)}, "
            f"work_type in {sorted(PERMIT_WORK_STAGE)}, "
            f"asof {asof.isoformat()}; BIS ipu4-2q9a now ingested separately "
            f"as nyc_dob_bis_permits -- the two overlap at the DOB NOW cutover "
            f"and must not be summed as one series")
    out = []
    for r in rows:
        stage = PERMIT_WORK_STAGE.get((r.get("work_type") or "").strip())
        if stage is None:
            continue
        lon, lat = _point_ok(_float(r.get("longitude")), _float(r.get("latitude")))
        out.append({
            "source": "nyc_dob_permit_issuance", "stage": stage,
            "business_name": (r.get("owner_business_name") or "").strip() or None,
            "bbl_raw": (r.get("bbl") or "").strip() or None,
            "bin": (r.get("bin") or "").strip() or None,
            "house_number": (r.get("house_no") or "").strip() or None,
            "street_name": (r.get("street_name") or "").strip() or None,
            "borough": _boro(r.get("borough")),
            "lon": lon, "lat": lat,
            "filed_on": _date(r.get("issued_date")),
            "status": (r.get("permit_status") or "").strip() or None,
            "status_date": _date(r.get("expired_date")),
            "category_hint": (r.get("job_description") or "").strip()[:400] or None,
            "license_type": (r.get("work_type") or "").strip() or None,
            "raw_id": r.get("job_filing_number"),
            "provenance": prov,
        })
    return _frame(out)


# ------------------------------------------------ 6. DCWP issued licences

DCWP_LIC_DATASET = "w7w3-xahh"
DCWP_LIC_FIELDS = ("license_nbr", "business_name", "dba_trade_name",
                   "business_category", "license_type", "license_status",
                   "license_creation_date", "lic_expir_dd", "address_building",
                   "address_street_name", "address_borough", "bin", "bbl",
                   "latitude", "longitude")


def fetch_dcwp_licenses(*, asof: dt.date | None = None, limit: int | None = None,
                        since: dt.date | None = None,
                        use_cache: bool = True, session=None) -> pd.DataFrame:
    """DCWP Issued Licenses -> stage `license_issued`.

    `license_creation_date` is the date the LICENCE record was created, which
    for a first-time licensee is the date they were licensed. CAVEAT THE
    DATABASE CANNOT ENFORCE: for a RENEWAL DCWP sometimes creates a new record,
    so an old business can appear with a recent creation date and read as a new
    opening. The lead-time query in model/storefront_filing.py guards against
    the worst of it by requiring an EARLIER early-stage filing for the same
    name key -- a renewal has no matching application in the window -- but a
    long-established business that happened to also file a DOB permit could
    still pair.
    """
    asof = asof or dt.date.today()
    where = _since_pred("license_creation_date", since)
    socrata.assert_fields(socrata.NYC_DOMAIN, DCWP_LIC_DATASET,
                          DCWP_LIC_FIELDS, session=session)
    rows = socrata.fetch(
        "nyc_dcwp_licenses", socrata.NYC_DOMAIN, DCWP_LIC_DATASET,
        select=",".join(DCWP_LIC_FIELDS), where=where, limit=limit,
        asof=asof, use_cache=use_cache, session=session)

    prov = (f"{DCWP_LIC_DATASET} (NYC DCWP Legally Operating Businesses), "
            f"license_creation_date {_window_note(since)}, "
            f"asof {asof.isoformat()}")
    out = []
    for r in rows:
        lon, lat = _point_ok(_float(r.get("longitude")), _float(r.get("latitude")))
        out.append({
            "source": "nyc_dcwp_licenses", "stage": "license_issued",
            "business_name": (r.get("dba_trade_name")
                              or r.get("business_name") or "").strip() or None,
            "bbl_raw": (r.get("bbl") or "").strip() or None,
            "bin": (r.get("bin") or "").strip() or None,
            "house_number": (r.get("address_building") or "").strip() or None,
            "street_name": (r.get("address_street_name") or "").strip() or None,
            "borough": _boro(r.get("address_borough")),
            "lon": lon, "lat": lat,
            "filed_on": _date(r.get("license_creation_date")),
            "status": (r.get("license_status") or "").strip() or None,
            "status_date": _date(r.get("lic_expir_dd")),
            "category_hint": (r.get("business_category") or "").strip() or None,
            "license_type": (r.get("license_type") or "").strip() or None,
            "raw_id": r.get("license_nbr"),
            "provenance": prov,
        })
    return _frame(out)


# --------------------------------------------------- 7. SLA active licences

SLA_ACTIVE_DATASET = "9s3h-dpkz"
SLA_ACTIVE_FIELDS = ("licensepermitid", "premisescounty", "description",
                     "legalname", "dba", "actualaddressofpremises",
                     "originalissuedate", "effectivedate", "expirationdate",
                     "georeference", "class", "type")


def fetch_sla_active(*, asof: dt.date | None = None, limit: int | None = None,
                     since: dt.date | None = None,
                     use_cache: bool = True, session=None) -> pd.DataFrame:
    """NYS SLA Active Licenses -> stage `liquor_active`.

    `filed_on` is `originalissuedate`, the date the FIRST licence issued at
    this premises -- NOT the current term's start. That is the right choice for
    "when did this bar open" and the wrong one for "is this licence current",
    and it is why `liquor_active` is excluded from OPEN_STAGES in
    filing_stages.py: pairing it as a terminal event against a 24-month-old
    application would produce negative lead times for any renewed licence.

    Windowed on originalissuedate so the ingest stays proportionate; the full
    active file is already ingested as staging.alcohol_licences and nothing
    here replaces it.
    """
    asof = asof or dt.date.today()
    counties = ", ".join(f"'{c}'" for c in NYC_COUNTIES)
    where = _and(f"premisescounty in ({counties})",
                 _since_pred("originalissuedate", since))
    socrata.assert_fields(socrata.NYS_DOMAIN, SLA_ACTIVE_DATASET,
                          SLA_ACTIVE_FIELDS, session=session)
    rows = socrata.fetch(
        "nyc_sla_liquor_licenses", socrata.NYS_DOMAIN, SLA_ACTIVE_DATASET,
        select=",".join(SLA_ACTIVE_FIELDS), where=where, limit=limit,
        asof=asof, use_cache=use_cache, session=session)

    prov = (f"{SLA_ACTIVE_DATASET} (NYS SLA Active Licenses), "
            f"originalissuedate {_window_note(since)}, NYC counties, "
            f"asof {asof.isoformat()}; CURRENT-ACTIVES SNAPSHOT -- a licence "
            f"that lapsed before this as-of is absent, so the year histogram "
            f"of this feed is a renewal curve, not a licensing history")
    out = []
    for r in rows:
        geo = r.get("georeference") or {}
        coords = geo.get("coordinates") or [None, None]
        lon, lat = _point_ok(_float(coords[0]), _float(coords[1]))
        out.append({
            "source": "nyc_sla_liquor_licenses", "stage": "liquor_active",
            "business_name": (r.get("dba") or r.get("legalname") or "").strip() or None,
            "bbl_raw": None, "bin": None, "house_number": None,
            "street_name": (r.get("actualaddressofpremises") or "").strip() or None,
            "borough": COUNTY_BOROUGH.get(
                (r.get("premisescounty") or "").strip().lower()),
            "lon": lon, "lat": lat,
            "filed_on": _date(r.get("originalissuedate")),
            "status": "Active",
            "status_date": _date(r.get("expirationdate")),
            "category_hint": (r.get("description") or "").strip() or None,
            "license_type": f"type {r.get('type')} class {r.get('class')}",
            "raw_id": r.get("licensepermitid"),
            "provenance": prov,
        })
    return _frame(out)


# ------------------------------------------------ 8. DOHMH first inspection

DOHMH_DATASET = "43nn-pn8j"
DOHMH_GROUP = ("camis", "dba", "boro", "building", "street", "bbl", "bin",
               "latitude", "longitude", "cuisine_description")

#: DOHMH's "permitted but never inspected" sentinel. Rows carrying it are
#: excluded from the min() so the sentinel cannot become a 1900 opening date.
SENTINEL = "1900-01-02T00:00:00"


def fetch_dohmh_first_inspection(*, asof: dt.date | None = None,
                                 limit: int | None = None,
                                 since: dt.date | None = None,
                                 use_cache: bool = True,
                                 session=None) -> pd.DataFrame:
    """DOHMH Restaurant Inspections -> stage `first_inspection`.

    THE FULL CURRENT FILE, but AGGREGATED SERVER-SIDE: the dataset is one row
    per violation (~295k rows) and what this table needs is one row per CAMIS
    with min(inspection_date). Socrata does the group-by, so ~31k rows cross
    the wire instead of 295k. Nothing is summed, so the one-row-per-violation
    fan-out cannot double anything -- min() is idempotent under duplication.

    THIS IS THE POINT OF THE WHOLE EXERCISE. For food service, DOHMH's first
    real inspection is the closest thing New York publishes to an opening date:
    a new establishment is inspected within weeks of opening, and the
    pre-opening state is visible as the 1900-01-01 sentinel.

    CAVEAT THE DATABASE CANNOT ENFORCE: the published file is a rolling
    multi-year window (dohmh.py's D36/D47 note). An establishment that opened
    and closed before the window is absent, and one whose earliest inspection
    fell out of the window has a first_inspection LATER than its true opening.
    The second case biases measured lead times DOWNWARD for old businesses and
    not at all for the new ones this table is about -- but it is a bias, not
    noise.
    """
    asof = asof or dt.date.today()
    socrata.assert_fields(socrata.NYC_DOMAIN, DOHMH_DATASET,
                          DOHMH_GROUP + ("inspection_date",), session=session)
    select = ",".join(DOHMH_GROUP) + ",min(inspection_date) AS first_inspection"
    rows = socrata.fetch(
        "nyc_dohmh_restaurants", socrata.NYC_DOMAIN, DOHMH_DATASET,
        select=select,
        where=_and(f"inspection_date > '{SENTINEL}'",
                   _since_pred("inspection_date", since)),
        group=",".join(DOHMH_GROUP), order="camis", limit=limit,
        asof=asof, use_cache=use_cache, session=session)

    prov = (f"{DOHMH_DATASET} (DOHMH Restaurant Inspections), full current "
            f"file, min(inspection_date) per CAMIS excluding the 1900 sentinel, "
            f"asof {asof.isoformat()}")

    # The group-by key includes dba/address, so a CAMIS that changed its DBA
    # mid-window yields several rows. Collapse to the EARLIEST per CAMIS --
    # the first inspection is a property of the establishment, not of a name.
    best: dict[str, dict] = {}
    for r in rows:
        camis = r.get("camis")
        first = _date(r.get("first_inspection"))
        if not camis or first is None:
            continue
        prev = best.get(camis)
        if prev is None or first < prev["_first"]:
            lon, lat = _point_ok(_float(r.get("longitude")),
                                 _float(r.get("latitude")))
            best[camis] = {
                "_first": first,
                "source": "nyc_dohmh_restaurants", "stage": "first_inspection",
                "business_name": (r.get("dba") or "").strip() or None,
                "bbl_raw": (r.get("bbl") or "").strip() or None,
                "bin": (r.get("bin") or "").strip() or None,
                "house_number": (r.get("building") or "").strip() or None,
                "street_name": (r.get("street") or "").strip() or None,
                "borough": _boro(r.get("boro")),
                "lon": lon, "lat": lat,
                "filed_on": first,
                "status": None, "status_date": None,
                "category_hint": (r.get("cuisine_description") or "").strip() or None,
                "license_type": "DOHMH food service establishment",
                "raw_id": camis,
                "provenance": prov,
            }
    out = [{k: v for k, v in rec.items() if k != "_first"}
           for rec in best.values()]
    return _frame(out)


# ------------------------------------------------ 9. DOB BIS permits (legacy)

BIS_PERMITS_DATASET = "ipu4-2q9a"
BIS_PERMITS_FIELDS = ("job__", "permit_si_no", "permit_type", "permit_subtype",
                      "permit_status", "permit_sequence__", "issuance_date",
                      "expiration_date", "filing_date", "job_type",
                      "house__", "street_name", "borough", "bin__", "bbl",
                      "gis_latitude", "gis_longitude", "owner_s_business_name",
                      "work_type")

#: BIS `permit_type` -> stage, the BIS spelling of PERMIT_WORK_STAGE.
#:   AL  Alteration          -- the interior build-out. rbx6-tga4's
#:                              'General Construction'.
#:   SG  Sign                -- the awning. rbx6-tga4's 'Sign'.
#: Deliberately absent: NB (new building) and DM (demolition), for the reason
#: EXCLUDED_JOB_TYPES gives; EW / PL / EQ / FO (equipment, plumbing, boilers,
#: foundations, 2.4M rows between them), for the reason STOREFRONT_WORK_TYPES
#: gives. This is the module's storefront rule in BIS vocabulary, not a cap on
#: how much history is pulled -- the pull is unclipped in time.
BIS_PERMIT_STAGE = {"AL": "permit_issued", "SG": "sign_permit"}


def fetch_bis_permits(*, asof: dt.date | None = None, limit: int | None = None,
                      since: dt.date | None = None,
                      use_cache: bool = True, session=None) -> pd.DataFrame:
    """DOB BIS Permit Issuance -> stages `permit_issued` and `sign_permit`.

    THE ONLY DOB SOURCE THAT COVERS 2020. DOB NOW rolled out across 2021
    (2,817 storefront permits in 2020 against 41,972 in 2023), so a rewind that
    reads rbx6-tga4 alone sees a construction collapse that is a software
    migration. BIS carries the pre-cutover permits and reaches the 1990s.

    `issuance_date` is TEXT in two formats in the same column, parsed here by
    `_date_mixed`. NO SERVER-SIDE DATE PREDICATE IS EVER SENT against it, even
    when `since` is given -- a SoQL comparison on that column is LEXICAL and
    would silently drop every `09/30/2013`-style row. `since` is applied
    CLIENT-SIDE instead, after parsing, and the docstring of `--since` says so.

    CAVEATS THE DATABASE CANNOT ENFORCE:
      * BIS and DOB NOW OVERLAP 2021-2024. Both are ingested, under different
        `source` values; pooling them into one "permits per year" series shows
        a cutover hump that is two systems running in parallel.
      * `owner_s_business_name` is the OWNER -- on a commercial fit-out usually
        the landlord. Same NAME-vs-PLACE caveat as fetch_dob_now_filings.
      * BIS publishes one row PER PERMIT SEQUENCE (renewals), so a job number
        recurs. Collapsed to the earliest `filed_on` per `filing_id` by
        model/storefront_filing.assemble, the same way rbx6-tga4 is.
    """
    asof = asof or dt.date.today()
    types = ", ".join(f"'{t}'" for t in BIS_PERMIT_STAGE)
    where = f"permit_type in ({types})"
    socrata.assert_fields(socrata.NYC_DOMAIN, BIS_PERMITS_DATASET,
                          BIS_PERMITS_FIELDS, session=session)
    rows = socrata.fetch(
        "nyc_dob_permit_issuance", socrata.NYC_DOMAIN, BIS_PERMITS_DATASET,
        select=",".join(BIS_PERMITS_FIELDS), where=where, limit=limit,
        asof=asof, use_cache=use_cache, session=session)

    prov = (f"{BIS_PERMITS_DATASET} (DOB Permit Issuance, legacy BIS), "
            f"permit_type in {sorted(BIS_PERMIT_STAGE)}, "
            f"issuance_date {_window_note(since)} (client-side: the column is "
            f"TEXT in two formats and a SoQL predicate on it compares "
            f"lexically), asof {asof.isoformat()}")
    out = []
    for r in rows:
        stage = BIS_PERMIT_STAGE.get((r.get("permit_type") or "").strip().upper())
        if stage is None:
            continue
        filed = _date_mixed(r.get("issuance_date"))
        if filed is None:
            continue                      # counted downstream as no-date drop
        if since is not None and filed < since:
            continue
        lon, lat = _point_ok(_float(r.get("gis_longitude")),
                             _float(r.get("gis_latitude")))
        out.append({
            # ONE LOGICAL SOURCE, TWO DATASETS -- registry.yaml:822 says so
            # (`dataset_ids: [ipu4-2q9a, rbx6-tga4]`). Emitting a second source
            # id here would put an unregistered value in
            # staging.storefront_filing AND arm a footgun: `write()` DELETEs by
            # source, so `--source <bis>` would erase the DOB NOW rows. The
            # dataset is recoverable from `license_type` ('BIS ...') and from
            # provenance.
            "source": "nyc_dob_permit_issuance", "stage": stage,
            "business_name": (r.get("owner_s_business_name") or "").strip() or None,
            "bbl_raw": (r.get("bbl") or "").strip() or None,
            "bin": (r.get("bin__") or "").strip() or None,
            "house_number": (r.get("house__") or "").strip() or None,
            "street_name": (r.get("street_name") or "").strip() or None,
            "borough": _boro(r.get("borough")),
            "lon": lon, "lat": lat,
            "filed_on": filed,
            "status": (r.get("permit_status") or "").strip() or None,
            "status_date": _date_mixed(r.get("expiration_date")),
            "category_hint": (r.get("job_type") or "").strip() or None,
            "license_type": (f"BIS {r.get('permit_type')}"
                             f"/{(r.get('permit_subtype') or '').strip()}"),
            # job__ alone is NOT unique -- one job issues many permits. The
            # permit serial is the row's own identity.
            "raw_id": (r.get("permit_si_no") or "").strip() or None,
            "provenance": prov,
        })
    return _frame(out)


def fetch_dob_permits_all(*, asof: dt.date | None = None,
                          limit: int | None = None,
                          since: dt.date | None = None,
                          use_cache: bool = True, session=None) -> pd.DataFrame:
    """BOTH DOB permit datasets as the one registered source they are.

    registry.yaml:820-822 already declares `nyc_dob_permit_issuance` as two
    datasets split by the BIS / DOB NOW namespace boundary. Before 2026-09-16
    only the DOB NOW half was fetched, which is why the warehouse had 2,817
    storefront permits for 2020 and 41,972 for 2023 -- a rollout curve wearing
    the costume of a construction cycle.

    THEY OVERLAP, ON PURPOSE. BIS accepts no new job filings after the cutover
    but still issues permits against old BIS jobs, so 2021-2024 legitimately
    contains rows from both. Nothing double-counts: the two datasets' row ids
    live in disjoint namespaces (DOB NOW `M00528469-I1`, BIS a numeric permit
    serial) and `filing_id` is source:stage:raw_id, so the renewal collapse in
    model/storefront_filing.assemble keys them apart. What a CONSUMER must not
    do is read a year-over-year permit count across the cutover as a trend --
    `license_type` starts with 'BIS ' on the legacy half precisely so that
    split is one predicate away.
    """
    now = fetch_dob_permits(asof=asof, limit=limit, since=since,
                            use_cache=use_cache, session=session)
    bis = fetch_bis_permits(asof=asof, limit=limit, since=since,
                            use_cache=use_cache, session=session)
    return _frame(pd.concat([now, bis], ignore_index=True).to_dict("records"))


#: source id -> fetcher. The ingest's dispatch table; the CLI's --source flag
#: validates against its keys. Every key is a registry.yaml source id.
FEEDS = {
    "nyc_sla_pending_licenses": fetch_sla_pending,
    "nyc_dob_now_job_filings": lambda **kw: fetch_dob_now_filings(**kw)[0],
    "nyc_dcwp_license_applications": fetch_dcwp_applications,
    "nyc_dob_permit_issuance": fetch_dob_permits_all,
    "nyc_dcwp_licenses": fetch_dcwp_licenses,
    "nyc_sla_liquor_licenses": fetch_sla_active,
    "nyc_dohmh_restaurants": fetch_dohmh_first_inspection,
}
