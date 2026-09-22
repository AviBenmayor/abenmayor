"""NYC DOF Property Assessment Roll — citywide assessment HISTORY, every fiscal
year the free Socrata feeds carry -> data/interim/rq002/dof_assessment/fy=<yr>/.

Built for RQ-002 (docs/research/RQ-002-greenpoint-towers-retail/): a FREE
proxy for commercial (storefront) rent history. The notebook stage takes the
market value (and assessed value, and gross/retail square footage where
present) of ground-floor-retail lots (tax class 4, building classes K*/S*/O*,
and mixed-use lots) in ZIP 11222 and candidate control ZIPs, and follows it
through the years. This module does the CITYWIDE, UNFILTERED pull only — no
ZIP/borough restriction at ingest time (owner standing rule 2026-09-16:
"never ever ever limit data pulls"). ZIP filtering happens downstream, in the
RQ-002 notebook.

SOURCES FOUND, AND WHAT REALLY EXISTS
--------------------------------------------------------------------------
`grep -rli dof src/loci` turns up ONLY the DOF Storefront Registry (Local Law
157 vacancy filings, GTM-137, `nyc_dof_storefront_registry` / analysis.storefront)
— a vacancy proxy with no dollar figure. Nothing DOF-valuation-shaped exists
anywhere in the registry or warehouse yet; this module is new ground.

Checked via the Socrata catalog API (`api.us.socrata.com/api/catalog/v1?
q=Property+Valuation+and+Assessment&domains=data.cityofnewyork.us`), which
returns exactly 8 DOF assessment-roll assets. Four are queryable tables; two
(`qpsp-bm9z`, `cqds-77ys`) are Socrata "non-tabular" stubs (no queryable rows);
one (`rgy2-tti8`) is a `viewType: blobby` file page — a single 2011 `AVROLL.zip`
attachment, not a live table, and superseded by the tabular ones below, so it
is NOT used. The three used, verified live 2026-09-22 by querying each
dataset's own `year`/`year4` distribution:

  m8p6-tp4b  "...Tax Class 1"           FY2010-FY2017 (`year4`), ~708k rows/yr
  kevu-8hby  "...Tax Classes 2,3,4"     FY2010-FY2017 (`year4`), ~372k-408k rows/yr
  yjxr-fw8i  "Property Valuation and    FY2011-FY2019 (`year`, "2010/11".."2018/19"),
             Assessment Data" (condensed all tax classes combined) ~1.07-1.12M rows/yr
  8y4t-faws  "...Tax Classes 1,2,3,4"   FY2023-FY2027 (`year`, 4-digit),
             (current rolling file, richest schema incl. sqft-by-use)

Picked ONE authoritative source per fiscal year, never pooled across sources
for the same year (that would double every lot): m8p6+kevu together for
FY2010 only (the one year yjxr-fw8i does not cover), yjxr-fw8i alone for
FY2011-FY2019 (it already combines all tax classes — using m8p6/kevu there
too would double-count), 8y4t-faws alone for FY2023-FY2027.

**GAP: FY2020, FY2021, FY2022 are NOT available from any live Socrata table.**
yjxr-fw8i stops at FY2019 and 8y4t-faws starts at FY2023; the catalog has no
third tabular dataset filling the middle three years. DOF's nyc.gov archive
page (zipped fixed-width "Final Assessment Roll" text files back to the
1980s) likely has these years as flat files, but pulling and parsing that
fixed-width format is out of scope for this pass — flagged as a follow-up,
not silently interpolated.

**NOT free / not pulled**: DOF "Notice of Property Value" (NOPV) and the
"Revised NOPV" (`8vgb-zm6e`) datasets are property-level dollar notices but
do not carry income/expense data. RPIE (Real Property Income and Expense)
filings — the one DOF product that would give actual commercial income per
sq ft — are NOT public: DOF collects RPIE from owners of income-producing
properties over ~$40k/yr assessed value but publishes no dataset of the
underlying figures, only aggregate income-capitalization worksheets used
internally for valuation. Checked the Socrata catalog and nyc.gov/finance
for "income and expense" / "RPIE" — nothing free and record-level exists.
Noted here per the RQ-002 brief; not built.

--------------------------------------------------------------------------
A DOUBLE-COUNT TRAP CAUGHT BEFORE THE PULL (guard the invariants)
--------------------------------------------------------------------------
`8y4t-faws` carries roughly 2x the expected ~1.15M-lot citywide count per
year because it publishes BOTH the Tentative roll (`period='1'`) and the
Final roll (`period='3'`) as separate rows for the same BBL in the same
fiscal year. Pooling both would silently double every market/assessed value
row for FY2023-FY2027. **This module selects `period='3'` (FINAL) only**,
matching `yjxr-fw8i` (which publishes only `period='FINAL'`, one stage). A
second, smaller trap: `8y4t-faws` also carries `rectype='3'` sub-account rows
(~1% of rows; verified on a sample: `roll_section='5'`, `bldg_class='U0'`
[utility], `parid` values with a trailing " NNN" suffix) — these are utility
special-franchise sub-accounts keyed under the SAME BBL as their parent lot,
not additional retail lots, and are excluded (`rectype='1'` only) rather than
fused into the parent's totals.

--------------------------------------------------------------------------
SCHEMA DRIFT ACROSS YEARS (why a per-source mapper, not one shared $select)
--------------------------------------------------------------------------
Each of the three sources uses different field names for the same concept
(verified live against each dataset's own `/api/views/<id>.json` column
list before writing the mapping below):

  concept                 m8p6/kevu (FY2010)   yjxr-fw8i (FY2011-19)  8y4t-faws (FY2023-27)
  BBL parts                boro/block/lot        boro/block/lot         boro/block/lot
  building class            bldgcl                bldgcl                 bldg_class
  tax class                 txcl                  taxclass               curtaxclass
  market value, total       cur_fv_t              fullval                curmkttot
  market value, land        cur_fv_l              (none)                 curmktland
  assessed value, actual    curavt / curavl       avtot / avland         curacttot / curactland
  assessed value,           (none — no             avtot2 / avland2      curtrntot / curtrnland
    transitional             transitional field                        (`trn` = transitional,
                              published pre-2018)                        confirmed against
                                                                          8y4t-faws' own py/ten/
                                                                          cbn/fin/cur × act/trn
                                                                          naming convention)
  gross sqft                gr_sqft               (none)                 gross_sqft
  retail sqft                (none)                (none)                retail_area_gross
  residential units          res_unit              (none)                units (total; no
                                                                          residential/commercial
                                                                          split published)
  total units                tot_unit              (none)                units
  lat/lon                    (none)                latitude/longitude    (none)

`avtot2`/`avland2` on yjxr-fw8i are mapped to "transitional" on the strength
of DOF's own published Condensed Value Assessment Roll ("AVROLL") layout,
where the `2`-suffixed fields are the transitional (phase-in-capped) AV
counterparts to `avtot`/`avland` — this is the DOCUMENTED file layout, not
a guess, but it is NOT independently re-verified against a DOF glossary PDF
in this pass, so the DATA-AUDIT / registry draft records it as
`mapping_confidence: medium`. Everywhere a concept has no source field, the
output column is NULL — never zero, never inferred.

--------------------------------------------------------------------------
FAIL LOUD / HEARTBEAT / RESUME
--------------------------------------------------------------------------
Each (dataset, fiscal year) pull raises on: a non-2xx response after
`RETRIES` attempts, an empty page where more were expected (a page shorter
than `PAGE` ends the pull for that year — normal), or a `$where` filter that
returns zero rows for a source's OWN reported year value (a renamed field,
not a real gap). `build()` skips any fiscal year whose output parquet already
exists unless `force=True`, so a killed/restarted run resumes. A progress
line is printed per page fetched and per fiscal year completed.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib
import time

import pandas as pd
import requests

REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
RAW_DIR = REPO_ROOT / "data" / "raw" / "nyc_dof_assessment_history"
INTERIM_DIR = REPO_ROOT / "data" / "interim" / "rq002" / "dof_assessment"
PROGRESS_LOG = INTERIM_DIR / "_progress.log"

SOURCE_ID = "nyc_dof_assessment_history"
DOMAIN = "https://data.cityofnewyork.us"
PAGE = 50_000
TIMEOUT = 300
RETRIES = 5

#: The gap this module does NOT fill (see module docstring). Downstream
#: consumers should read this rather than assume "missing = zero rows filed".
KNOWN_GAP_FISCAL_YEARS = (2020, 2021, 2022)


class DofAssessmentError(RuntimeError):
    """A fetch or normalisation failure that must not read as a real zero."""


def _log(msg: str) -> None:
    line = f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_LOG, "a") as fh:
        fh.write(line + "\n")


def _headers() -> dict:
    import os
    token = os.environ.get("SOCRATA_APP_TOKEN")
    return {"X-App-Token": token} if token else {}


@dataclasses.dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    label: str
    select: str
    year_field: str          # the field carrying the fiscal-year value
    year_values: dict        # {fiscal_year_int: raw_value_for_$where}
    where_extra: str | None  # additional $where clause (period/rectype filters)
    mapper: str              # name of the normalize_* function to apply


REQUIRED_COLUMNS = {
    "m8p6-tp4b": ("bble", "boro", "block", "lot", "bldgcl", "txcl",
                  "cur_fv_l", "cur_fv_t", "curavl", "curavt",
                  "tot_unit", "res_unit", "gr_sqft",
                  "hnum_lo", "hnum_hi", "str_name", "zip", "year4"),
    "kevu-8hby": ("bble", "boro", "block", "lot", "bldgcl", "txcl",
                  "cur_fv_l", "cur_fv_t", "curavl", "curavt",
                  "tot_unit", "res_unit", "gr_sqft",
                  "hnum_lo", "hnum_hi", "str_name", "zip", "year4"),
    "yjxr-fw8i": ("bble", "boro", "block", "lot", "bldgcl", "taxclass",
                  "fullval", "avland", "avtot", "avland2", "avtot2",
                  "staddr", "zip", "year", "period", "latitude", "longitude"),
    "8y4t-faws": ("parid", "boro", "block", "lot", "bldg_class", "curtaxclass",
                  "curmktland", "curmkttot", "curactland", "curacttot",
                  "curtrnland", "curtrntot", "gross_sqft", "retail_area_gross",
                  "units", "housenum_lo", "housenum_hi", "street_name",
                  "zip_code", "year", "period", "rectype"),
}

# Class 1 (m8p6) and classes 2/3/4 (kevu) share one schema and one $where shape.
_TC1_TC234_SELECT = ",".join(REQUIRED_COLUMNS["m8p6-tp4b"])

DATASETS: list[DatasetSpec] = [
    DatasetSpec(
        dataset_id="m8p6-tp4b", label="dof_tax_class_1_fy2010_2017",
        select=_TC1_TC234_SELECT, year_field="year4",
        year_values={2010: "2010"}, where_extra=None, mapper="normalize_tc1_tc234",
    ),
    DatasetSpec(
        dataset_id="kevu-8hby", label="dof_tax_class_234_fy2010_2017",
        select=_TC1_TC234_SELECT, year_field="year4",
        year_values={2010: "2010"}, where_extra=None, mapper="normalize_tc1_tc234",
    ),
    DatasetSpec(
        dataset_id="yjxr-fw8i", label="dof_condensed_fy2011_2019",
        select=",".join(REQUIRED_COLUMNS["yjxr-fw8i"]), year_field="year",
        year_values={
            2011: "2010/11", 2012: "2011/12", 2013: "2012/13", 2014: "2013/14",
            2015: "2014/15", 2016: "2015/16", 2017: "2016/17", 2018: "2017/18",
            2019: "2018/19",
        },
        where_extra="period='FINAL'", mapper="normalize_condensed",
    ),
    DatasetSpec(
        dataset_id="8y4t-faws", label="dof_current_fy2023_2027",
        select=",".join(REQUIRED_COLUMNS["8y4t-faws"]), year_field="year",
        year_values={2023: "2023", 2024: "2024", 2025: "2025", 2026: "2026",
                     2027: "2027"},
        where_extra="period='3' AND rectype='1'", mapper="normalize_current",
    ),
]


def dataset_columns(dataset_id: str, session: requests.Session | None = None) -> list[str]:
    sess = session or requests.Session()
    resp = sess.get(f"{DOMAIN}/api/views/{dataset_id}.json",
                     headers=_headers(), timeout=TIMEOUT)
    resp.raise_for_status()
    return [c.get("fieldName") for c in resp.json().get("columns", [])]


def assert_schema(spec: DatasetSpec, session: requests.Session | None = None) -> None:
    """Pre-flight schema check: raise before pulling a single row if the live
    dataset no longer exposes a column this module's $select depends on."""
    present = set(dataset_columns(spec.dataset_id, session=session))
    required = set(REQUIRED_COLUMNS[spec.dataset_id])
    missing = required - present
    if missing:
        raise DofAssessmentError(
            f"{spec.dataset_id}: live schema is missing {sorted(missing)} — "
            f"re-derive REQUIRED_COLUMNS from {DOMAIN}/api/views/{spec.dataset_id}.json "
            f"before pulling."
        )


def _fetch_page(session: requests.Session, url: str, params: dict) -> list[dict]:
    last: object = None
    for attempt in range(RETRIES):
        try:
            resp = session.get(url, params=params, headers=_headers(), timeout=TIMEOUT)
            if resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                time.sleep(3 + 4 * attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:   # pragma: no cover - network
            last = exc
            time.sleep(3 + 4 * attempt)
    raise DofAssessmentError(
        f"GET {url} failed after {RETRIES} attempts ({last}). Refusing to "
        f"continue — a dropped page here would read downstream as a stretch "
        f"of the city where no lot has a value."
    )


def fetch_year(spec: DatasetSpec, fiscal_year: int, *, limit: int | None = None,
               session: requests.Session | None = None) -> list[dict]:
    """Page through one (dataset, fiscal year), logging a line per page.

    `limit` caps total rows for the pre-flight sample only — never pass it
    for a real ingest (the owner standing rule is no caps on free pulls)."""
    if fiscal_year not in spec.year_values:
        raise DofAssessmentError(
            f"{spec.dataset_id}: fiscal year {fiscal_year} not in this "
            f"dataset's coverage {sorted(spec.year_values)}"
        )
    sess = session or requests.Session()
    url = f"{DOMAIN}/resource/{spec.dataset_id}.json"
    raw_year = spec.year_values[fiscal_year]
    where = f"{spec.year_field}='{raw_year}'"
    if spec.where_extra:
        where = f"{where} AND {spec.where_extra}"
    base = {"$select": spec.select, "$where": where, "$order": ":id"}

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"{spec.dataset_id}_fy{fiscal_year}.json"
    if cache_path.exists() and limit is None:
        cached = json.loads(cache_path.read_text())
        _log(f"{spec.label} FY{fiscal_year}: reusing cached raw pull "
             f"({len(cached)} rows) from {cache_path}")
        return cached

    rows: list[dict] = []
    offset = 0
    page_num = 0
    while True:
        page_size = PAGE if limit is None else min(PAGE, limit - len(rows))
        if page_size <= 0:
            break
        batch = _fetch_page(sess, url, {**base, "$limit": page_size, "$offset": offset})
        rows.extend(batch)
        page_num += 1
        _log(f"{spec.label} FY{fiscal_year}: page {page_num} "
             f"({len(batch)} rows, {len(rows)} total so far)")
        if len(batch) < page_size:
            break
        offset += len(batch)
        if limit is not None and len(rows) >= limit:
            break

    if not rows:
        raise DofAssessmentError(
            f"{spec.dataset_id} returned ZERO rows for $where={where!r}. That "
            f"is a renamed field or a changed value format, not a fiscal year "
            f"where the city assessed nothing. Refusing to write a silent zero."
        )
    if limit is None:
        cache_path.write_text(json.dumps(rows))
    return rows


# --------------------------------------------------------------------------
# Normalisation. One function per source shape -> the shared output schema.
# --------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "bbl", "fiscal_year", "source_dataset", "borough", "block", "lot",
    "building_class", "tax_class", "zip_code", "address",
    "market_value_total", "market_value_land",
    "assessed_value_actual_total", "assessed_value_actual_land",
    "assessed_value_transitional_total", "assessed_value_transitional_land",
    "gross_sqft", "retail_sqft", "residential_units", "total_units",
    "latitude", "longitude", "ingested_at",
]


def _bbl(boro, block, lot) -> str | None:
    try:
        b = int(str(boro).strip())
        bl = int(str(block).strip())
        lt = int(str(lot).strip())
    except (TypeError, ValueError):
        return None
    return f"{b:01d}{bl:05d}{lt:04d}"


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _skeleton(fiscal_year: int, source_dataset: str, now: str) -> dict:
    return {c: None for c in OUTPUT_COLUMNS} | {
        "fiscal_year": fiscal_year, "source_dataset": source_dataset, "ingested_at": now,
    }


def normalize_tc1_tc234(rows: list[dict], fiscal_year: int, dataset_id: str) -> pd.DataFrame:
    now = dt.datetime.now().isoformat()
    out = []
    for r in rows:
        rec = _skeleton(fiscal_year, dataset_id, now)
        rec.update({
            "bbl": _bbl(r.get("boro"), r.get("block"), r.get("lot")),
            "borough": r.get("boro"), "block": r.get("block"), "lot": r.get("lot"),
            "building_class": r.get("bldgcl"), "tax_class": r.get("txcl"),
            "zip_code": r.get("zip"),
            "address": " ".join(x for x in [r.get("hnum_lo"), r.get("str_name")] if x) or None,
            "market_value_total": _num(r.get("cur_fv_t")),
            "market_value_land": _num(r.get("cur_fv_l")),
            "assessed_value_actual_total": _num(r.get("curavt")),
            "assessed_value_actual_land": _num(r.get("curavl")),
            "gross_sqft": _num(r.get("gr_sqft")),
            "residential_units": _num(r.get("res_unit")),
            "total_units": _num(r.get("tot_unit")),
        })
        out.append(rec)
    return pd.DataFrame(out, columns=OUTPUT_COLUMNS)


def normalize_condensed(rows: list[dict], fiscal_year: int, dataset_id: str) -> pd.DataFrame:
    now = dt.datetime.now().isoformat()
    out = []
    for r in rows:
        rec = _skeleton(fiscal_year, dataset_id, now)
        rec.update({
            "bbl": _bbl(r.get("boro"), r.get("block"), r.get("lot")),
            "borough": r.get("boro"), "block": r.get("block"), "lot": r.get("lot"),
            "building_class": r.get("bldgcl"), "tax_class": r.get("taxclass"),
            "zip_code": r.get("zip"), "address": r.get("staddr"),
            "market_value_total": _num(r.get("fullval")),
            "assessed_value_actual_total": _num(r.get("avtot")),
            "assessed_value_actual_land": _num(r.get("avland")),
            "assessed_value_transitional_total": _num(r.get("avtot2")),
            "assessed_value_transitional_land": _num(r.get("avland2")),
            "latitude": _num(r.get("latitude")), "longitude": _num(r.get("longitude")),
        })
        out.append(rec)
    return pd.DataFrame(out, columns=OUTPUT_COLUMNS)


def normalize_current(rows: list[dict], fiscal_year: int, dataset_id: str) -> pd.DataFrame:
    now = dt.datetime.now().isoformat()
    out = []
    for r in rows:
        rec = _skeleton(fiscal_year, dataset_id, now)
        rec.update({
            "bbl": _bbl(r.get("boro"), r.get("block"), r.get("lot")),
            "borough": r.get("boro"), "block": r.get("block"), "lot": r.get("lot"),
            "building_class": r.get("bldg_class"), "tax_class": r.get("curtaxclass"),
            "zip_code": r.get("zip_code"),
            "address": " ".join(x for x in [r.get("housenum_lo"), r.get("street_name")] if x) or None,
            "market_value_total": _num(r.get("curmkttot")),
            "market_value_land": _num(r.get("curmktland")),
            "assessed_value_actual_total": _num(r.get("curacttot")),
            "assessed_value_actual_land": _num(r.get("curactland")),
            "assessed_value_transitional_total": _num(r.get("curtrntot")),
            "assessed_value_transitional_land": _num(r.get("curtrnland")),
            "gross_sqft": _num(r.get("gross_sqft")),
            "retail_sqft": _num(r.get("retail_area_gross")),
            "total_units": _num(r.get("units")),
        })
        out.append(rec)
    return pd.DataFrame(out, columns=OUTPUT_COLUMNS)


MAPPERS = {
    "normalize_tc1_tc234": normalize_tc1_tc234,
    "normalize_condensed": normalize_condensed,
    "normalize_current": normalize_current,
}


def year_partition_path(fiscal_year: int) -> pathlib.Path:
    return INTERIM_DIR / f"fy={fiscal_year}"


def build_year(fiscal_year: int, *, force: bool = False, limit: int | None = None,
               session: requests.Session | None = None) -> pathlib.Path | None:
    """Fetch + normalize every dataset that covers `fiscal_year`, write one
    parquet per (year, dataset) under fy=<year>/. Returns the partition dir,
    or None if the year is a known gap and nothing was written."""
    specs = [s for s in DATASETS if fiscal_year in s.year_values]
    if not specs:
        _log(f"FY{fiscal_year}: no dataset covers this year "
             f"(known gap: {fiscal_year in KNOWN_GAP_FISCAL_YEARS})")
        return None
    part_dir = year_partition_path(fiscal_year)
    part_dir.mkdir(parents=True, exist_ok=True)
    sess = session or requests.Session()
    for spec in specs:
        out_path = part_dir / f"{spec.dataset_id}.parquet"
        if out_path.exists() and not force:
            _log(f"FY{fiscal_year} {spec.label}: partition exists, skipping "
                 f"({out_path})")
            continue
        assert_schema(spec, session=sess)
        rows = fetch_year(spec, fiscal_year, limit=limit, session=sess)
        df = MAPPERS[spec.mapper](rows, fiscal_year, spec.dataset_id)
        df.to_parquet(out_path, index=False)
        _log(f"FY{fiscal_year} {spec.label}: wrote {len(df)} rows -> {out_path}")
    return part_dir


def build(*, force: bool = False, years: list[int] | None = None) -> list[pathlib.Path]:
    """Full citywide pull, every fiscal year across all three datasets, no
    borough/ZIP filter. Resumable: a year whose partition files already exist
    is skipped unless force=True. Call from a background process — this can
    take a long time across ~14 fiscal years x ~1-2.3M rows each."""
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    all_years = sorted({y for s in DATASETS for y in s.year_values})
    target_years = years if years is not None else all_years
    _log(f"build: {len(target_years)} fiscal years targeted: {target_years}")
    _log(f"build: known unfillable gap years (no live Socrata source): "
         f"{list(KNOWN_GAP_FISCAL_YEARS)}")
    written = []
    session = requests.Session()
    for fy in target_years:
        path = build_year(fy, force=force, session=session)
        if path is not None:
            written.append(path)
    _log(f"build: done. {len(written)} fiscal-year partitions on disk under {INTERIM_DIR}")
    return written


if __name__ == "__main__":
    build()
