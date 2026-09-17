"""Per-category comps model: expected revenue, supportable rent, and cushion
for existing businesses, built on business-for-sale listing comps.

Inputs: data/benchmarks/bizbuysell_nyc_listings.csv (raw listing rows) and
src/loci/benchmarks.yaml (per-category occupancy-cost-ratio fallback, plus the
collection provenance/caveats). This is its OWN fair-value model -- NOT a
reality check on analysis.site_fairvalue (the household-spend fair-value model
another session is building concurrently). Keep the two separate; this module
does not import or reference that one.

COLLECTION STATUS (2026-09-05): BizBuySell returned HTTP 403 on robots.txt and
on all three index URLs tried (a Cloudflare-class bot block); the BizQuest and
LoopNet fallbacks also 403'd. Zero real listings were collected -- see
benchmarks.yaml's `collection` block and its manual-export procedure. Every
comps_for() call today therefore falls through every geography level to
n_comps=0, thin=True, rent_source="no_data". The pipeline below is built and
tested against a synthetic fixture (tests/test_comps.py) so it activates the
moment a human pastes real rows into data/benchmarks/bizbuysell_nyc_listings.csv
-- no code changes needed.

Fallback ordering for the comp set behind (category, borough, neighborhood):
    neighborhood -> borough -> citywide
-- the first level (most specific first) with >=1 matching listing wins;
`level_used` records which one. n_comps < THIN_N flags `thin`.

Supportable rent, in order:
    1. `rent_source="listed"` -- median of the LISTED rent among the matched
       comps, where any report one. The CSV's `rent` field is the listing's
       MONTHLY asking rent; it is annualized (x12) before use so it is on the
       same annual basis as gross_revenue/cash_flow_sde everywhere below.
    2. `rent_source="cash_flow_before_rent_addback"` -- some listings
       separately break out "cash flow before rent" (a seller/broker add-back,
       `cash_flow_before_rent` in the CSV); implied rent is the median of
       (cash_flow_before_rent - cash_flow_sde) across comps reporting both.
    3. `rent_source="occupancy_ratio_fallback"` -- benchmarks.yaml's
       category occupancy_cost_ratio (rent as a fraction of revenue) times
       expected_revenue. A generic small-business rule of thumb, NOT derived
       from any listing -- see benchmarks.yaml's caveat on that block.
    4. `rent_source="no_data"` -- no revenue at all to fall back on either
       (e.g. n_comps == 0).

Cushion (the downside signal on top of supportable rent):
    - tiers 1-2 (a real rent number): (cash_flow_p50 - supportable_rent) / supportable_rent
      -- `cushion_basis="cash_flow_vs_rent"`.
    - tier 3 (no real rent, occupancy-ratio estimate only): the 25th-percentile
      cash-flow MARGIN across comps (cash_flow / gross_revenue) stands in as
      the downside, since there is no real rent figure to net against --
      `cushion_basis="cash_flow_margin_p25"`.
    - tier 4: `cushion=None`, `cushion_basis="no_data"`.
"""
from __future__ import annotations

import copy
import csv
import hashlib

import numpy as np
import yaml

from loci.categories import CATEGORIES
from loci.db import PKG as _LOCI_PKG
from loci.db import REPO_ROOT as _REPO_ROOT

BENCHMARKS_PATH = _LOCI_PKG / "benchmarks.yaml"
LISTINGS_CSV = _REPO_ROOT / "data" / "benchmarks" / "bizbuysell_nyc_listings.csv"

THIN_N = 8
FALLBACK_LEVELS = ("neighborhood", "borough", "citywide")
# bank: not listable as a small-business comp (task scope) -- excluded from
# the default sweep in all_comps(), though comps_for("bank", ...) still works
# (it will just always return n_comps=0 since bank never appears in the CSV).
LISTABLE_CATEGORIES = [c for c in CATEGORIES if c != "bank"]


def _stamp(path) -> tuple:
    """(resolved path, mtime_ns, size) -- the cache key for a parsed file.

    THE PATH ALONE IS NOT A KEY. `data/benchmarks/bizbuysell_nyc_listings.csv`
    is the file a human pastes real listings into the moment the BizBuySell
    403 is worked around (see the module docstring); a cache keyed on its name
    would keep serving the empty parse through that refresh, and every card in
    the run would grade economics D against listings that are sitting on disk.
    A stale comps cache is worse than the N+1 it removes. mtime AND size,
    because a same-second rewrite can leave mtime unchanged on a coarse
    filesystem clock while the length moves; a missing file is its own key.
    """
    try:
        st = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), st.st_mtime_ns, st.st_size)


#: {stamp: parsed payload}. Small and bounded: two files, one entry each per
#: distinct (mtime, size) seen in this process.
_PARSE_CACHE: dict[tuple, object] = {}


def clear_parse_cache() -> None:
    """Drop the memoised parses. Tests that rewrite a fixture within one
    mtime tick call this; nothing in production needs it."""
    _PARSE_CACHE.clear()


def load_listings(csv_path=None) -> list[dict]:
    """Raw listing rows from the CSV. Numeric fields parse to float where
    present; a blank/absent field stays None (never 0.0 -- $0 revenue would be
    a real, if strange, value, and must not be confused with "not reported").

    MEMOISED on `_stamp(path)`. `build_cards` called this once per category,
    so one fifteen-category report re-parsed the CSV fifteen times; the rows
    are handed back as fresh dicts so a caller that mutates one cannot poison
    the next card's comp set."""
    path = csv_path or LISTINGS_CSV
    key = ("listings", _stamp(path))
    hit = _PARSE_CACHE.get(key)
    if hit is not None:
        return [dict(r) for r in hit]
    rows = _parse_listings(path)
    _PARSE_CACHE[key] = rows
    return [dict(r) for r in rows]


def _parse_listings(path) -> list[dict]:
    if not path.exists():
        return []
    numeric = {"asking_price", "gross_revenue", "cash_flow_sde",
               "cash_flow_before_rent", "rent", "sqft"}
    out: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rec = dict(row)
            for k in numeric:
                v = (rec.get(k) or "").strip()
                rec[k] = float(v) if v else None
            rec["self_reported"] = (rec.get("self_reported") or "").strip().lower() in ("true", "1", "yes")
            out.append(rec)
    return out


def load_benchmarks() -> dict:
    """The checked-in benchmarks.yaml: occupancy_cost_ratio fallback table,
    collection provenance/caveats, and the raw per-category listing snapshot.

    MEMOISED on `_stamp(BENCHMARKS_PATH)`, same reasoning as `load_listings`.
    Returns a deep copy: the doc is nested and `_occupancy_ratio` reaches into
    it, so handing out the cached object itself would let one caller's edit
    change another card's occupancy ratio."""
    key = ("benchmarks", _stamp(BENCHMARKS_PATH))
    hit = _PARSE_CACHE.get(key)
    if hit is None:
        hit = yaml.safe_load(BENCHMARKS_PATH.read_text())
        _PARSE_CACHE[key] = hit
    return copy.deepcopy(hit)


def benchmarks_hash() -> str:
    """Short, stable hash of the checked-in benchmarks.yaml BYTES, so a row
    written to analysis.comps_fairvalue can be tied to the exact
    occupancy-ratio table (and collection status) that produced it -- same
    provenance pattern as loci.model.gaps._reach_hash for reach.yaml."""
    return hashlib.sha256(BENCHMARKS_PATH.read_bytes()).hexdigest()[:12]


def _occupancy_ratio(category: str, benchmarks: dict) -> float:
    ratios = benchmarks.get("occupancy_cost_ratio", {})
    if category not in ratios:
        raise ValueError(
            f"no occupancy_cost_ratio fallback for category '{category}' in benchmarks.yaml"
        )
    return float(ratios[category])


def _q(values: list[float], q: float):
    """q-th quantile of `values`, or None if empty. numpy.quantile, same
    convention as loci.model.spacing._quantile."""
    return float(np.quantile(np.asarray(values, dtype=float), q)) if values else None


def _match(listings: list[dict], category: str, level: str,
           borough, neighborhood) -> list[dict]:
    rows = [r for r in listings if r.get("loci_category") == category]
    if level == "citywide":
        return rows
    if level == "borough":
        if not borough:
            return []
        return [r for r in rows if (r.get("borough") or "").strip().lower() == borough.strip().lower()]
    if level == "neighborhood":
        if not neighborhood:
            return []
        return [r for r in rows
                if (r.get("neighborhood") or "").strip().lower() == neighborhood.strip().lower()]
    raise ValueError(f"unknown fallback level {level!r}")


def comps_for(category: str, borough: str | None = None, neighborhood: str | None = None,
              listings: list[dict] | None = None, benchmarks: dict | None = None) -> dict:
    """The comp set and derived fair-value numbers for one category, at the
    most specific geography that has >=1 matching listing (neighborhood ->
    borough -> citywide, falling back automatically). Always returns a
    result -- n_comps may be 0 and every derived field None."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown Loci category {category!r}")
    listings = load_listings() if listings is None else listings
    benchmarks = load_benchmarks() if benchmarks is None else benchmarks

    levels = [lv for lv in FALLBACK_LEVELS
              if (lv != "neighborhood" or neighborhood) and (lv != "borough" or borough)]
    if "citywide" not in levels:
        levels.append("citywide")

    comps: list[dict] = []
    level_used = levels[-1]
    for lv in levels:
        matched = _match(listings, category, lv, borough, neighborhood)
        if matched:
            comps, level_used = matched, lv
            break

    n = len(comps)
    revenue = [r["gross_revenue"] for r in comps if r.get("gross_revenue") is not None]
    cashflow = [r["cash_flow_sde"] for r in comps if r.get("cash_flow_sde") is not None]
    # CSV `rent` is the listing's monthly asking rent (benchmarks.yaml's collection
    # notes: listings state "$X/mo rent"); annualize x12 here so rent_p50 and
    # supportable_rent are on the same annual basis as gross_revenue/cash_flow_sde.
    rents = [r["rent"] * 12 for r in comps if r.get("rent") is not None]
    addback_implied = [r["cash_flow_before_rent"] - r["cash_flow_sde"] for r in comps
                        if r.get("cash_flow_before_rent") is not None and r.get("cash_flow_sde") is not None]
    margins = [r["cash_flow_sde"] / r["gross_revenue"] for r in comps
               if r.get("cash_flow_sde") is not None and r.get("gross_revenue")]

    rev_p25, rev_p50, rev_p75 = _q(revenue, .25), _q(revenue, .50), _q(revenue, .75)
    cf_p25, cf_p50, cf_p75 = _q(cashflow, .25), _q(cashflow, .50), _q(cashflow, .75)
    rent_p50 = _q(rents, .50)
    expected_revenue = rev_p50

    if rents:
        supportable_rent, rent_source = rent_p50, "listed"
    elif addback_implied:
        supportable_rent, rent_source = _q(addback_implied, .50), "cash_flow_before_rent_addback"
    elif expected_revenue is not None:
        supportable_rent = expected_revenue * _occupancy_ratio(category, benchmarks)
        rent_source = "occupancy_ratio_fallback"
    else:
        supportable_rent, rent_source = None, "no_data"

    if rent_source in ("listed", "cash_flow_before_rent_addback") and supportable_rent and cf_p50 is not None:
        cushion = (cf_p50 - supportable_rent) / supportable_rent
        cushion_basis = "cash_flow_vs_rent"
    elif margins:
        cushion = _q(margins, .25)
        cushion_basis = "cash_flow_margin_p25"
    else:
        cushion, cushion_basis = None, "no_data"

    geo_value = (neighborhood if level_used == "neighborhood"
                 else borough if level_used == "borough"
                 else "(all)")

    return {
        "category": category, "borough": borough, "neighborhood": neighborhood,
        "level_used": level_used, "geo_value": geo_value,
        "n_comps": n, "thin": n < THIN_N,
        "gross_revenue_p25": rev_p25, "gross_revenue_p50": rev_p50, "gross_revenue_p75": rev_p75,
        "cash_flow_p25": cf_p25, "cash_flow_p50": cf_p50, "cash_flow_p75": cf_p75,
        "rent_p50": rent_p50, "n_rent_comps": len(rents), "rent_source": rent_source,
        "expected_revenue": expected_revenue, "supportable_rent": supportable_rent,
        "cushion": cushion, "cushion_basis": cushion_basis,
    }


def all_comps(listings: list[dict] | None = None, benchmarks: dict | None = None,
              categories: list[str] | None = None) -> list[dict]:
    """comps_for() for every (category, geography) combo worth persisting:
    each listable category citywide, plus each category x borough for every
    borough that actually has >=1 listing for it (an empty sweep today, since
    zero listings are collected -- see module docstring)."""
    listings = load_listings() if listings is None else listings
    benchmarks = load_benchmarks() if benchmarks is None else benchmarks
    cats = categories or LISTABLE_CATEGORIES
    boroughs_present = sorted({r["borough"] for r in listings if r.get("borough")})

    out = []
    for cat in cats:
        out.append(comps_for(cat, listings=listings, benchmarks=benchmarks))
        for b in boroughs_present:
            out.append(comps_for(cat, borough=b, listings=listings, benchmarks=benchmarks))
    return out


_COMPS_FAIRVALUE_COLS = [
    "category", "geo_level", "geo_value", "n_comps", "thin",
    "gross_revenue_p25", "gross_revenue_p50", "gross_revenue_p75",
    "cash_flow_p25", "cash_flow_p50", "cash_flow_p75",
    "rent_p50", "n_rent_comps", "rent_source",
    "expected_revenue", "supportable_rent", "cushion", "cushion_basis",
    "benchmarks_hash", "collected_on", "computed_on",
]


def write_comps_fairvalue(con, listings: list[dict] | None = None) -> int:
    """Computes all_comps() and REPLACES analysis.comps_fairvalue (full
    replace -- category/geo_level/geo_value is not a natural incremental
    key, same pattern as analysis.hex_gaps_reach)."""
    import datetime

    import pandas as pd

    listings = load_listings() if listings is None else listings
    benchmarks = load_benchmarks()
    rows = all_comps(listings=listings, benchmarks=benchmarks)
    bhash = benchmarks_hash()
    collected_on = benchmarks.get("collected_on")
    computed_on = datetime.date.today().isoformat()

    df = pd.DataFrame(rows)
    df["geo_level"] = df["level_used"]
    df["benchmarks_hash"] = bhash
    df["collected_on"] = collected_on
    df["computed_on"] = computed_on
    df = df[_COMPS_FAIRVALUE_COLS]

    con.execute("DELETE FROM analysis.comps_fairvalue")
    con.register("_comps", df)
    cols_sql = ", ".join(_COMPS_FAIRVALUE_COLS)
    con.execute(f"INSERT INTO analysis.comps_fairvalue ({cols_sql}) SELECT {cols_sql} FROM _comps")
    con.unregister("_comps")
    return len(df)
