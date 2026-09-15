"""RETRODICTION — does the screen's score, at the moment a storefront opened,
tell you anything about what happened next?

THE QUESTION (GTM-158, QUESTIONS T11, gating D87)
---------------------------------------------------------------------------
docs/GTM.md claims Loci lowers an operator's *cost of search*, and the
contrarian red-team refused to let it claim *decision value* until this test
ran. D87's attack, stated exactly:

    "Loci measures supply thinness, not site quality — an address with no
     competitors may have none because the market said no."

That is D1's reverse-causality error wearing a new costume. There is exactly
one way to settle it: take storefronts that opened at a KNOWN date, score them
with the screen AS IT WOULD HAVE READ ON THAT DATE, and check the outcome. If
the score cannot separate "underserved" from "unviable", it will not predict
survival, or it will predict it backwards.

WHAT THIS MODULE FOUND, AND WHY IT HAS TWO HALVES
---------------------------------------------------------------------------
The survival test is **not identifiable in Loci's data today**, and the reason
is structural, not a shortage of rows. Every closure instrument in the
warehouse is a CURRENT-STATE extract:

  * `analysis.poi_presence` — one snapshot month (2026-09). Every one of the
    227,548 locations has `last_seen_month = '2026-09'` and `n_months_seen = 1`.
    D79's own rule says `last_seen_month` falling behind is not evidence of
    closure; with one month it cannot fall behind at all.
  * DOHMH 43nn-pn8j — the portal publishes establishments "in an active status
    as of the date of the data pull". A restaurant that opened in 2023 and
    closed in 2025 is not a row with a stale date; it is ABSENT.
  * Foursquare OS Places — the cached NYC slice has `date_closed` NULL on all
    821,397 rows: the fetch filtered to open venues. The upstream release does
    publish closures. This is the cheapest unlock in the project (see
    `closure_audit`).
  * SLA — the cached pull's minimum `expirationdate` is in the future. Current
    licences only.
  * `analysis.storefront_pipeline.is_open` — means EVER reached an open-evidence
    stage, and `storefront_pipeline.validate` enforces
    `is_open <=> (opened_on IS NOT NULL)`. Using it as a survival outcome is a
    tautology that returns 100% survival by construction.
  * DCWP `w7w3-xahh` DOES retain non-Active statuses, and is the only real
    closure signal in the warehouse — but in MN+BK inside the window it is
    ~100 licences whose categories are tow-truck drivers, pedicabs and hotels.
    Effectively zero overlap with the fifteen daily-needs categories.
  * DOF Storefront Registry (LL157) carries per-year vacancy through 2024 — but
    at the PREMISES grain with no business identity. A cohort POI has a median
    of tens of registry premises within 30 m; "some storefront in this building
    is vacant" is not "this business closed".

So the cohort assembled from the ledger is ~100% survivors **by construction**,
the outcome variable has no variance, and any survival curve drawn from it
would be an artefact of the extract, not a fact about New York. That is the
finding, and `survival_gate` refuses to fit rather than print a flattering
number. The Kaplan-Meier and Cox code paths are written and gated so that the
moment a second snapshot exists they run unchanged.

The second half is the test that IS identifiable today, and it attacks D87
directly at the other margin. If the screen's gaps are *unviable* rather than
*underserved*, operators — who know the street — will avoid them:

    ENTRY RETRODICTION. Freeze the screen at t0 = 2023-01-01 by rebuilding
    supply from the first-seen ledger. Ask whether the counterfactual score at
    t0 predicts WHERE the 2023-24 openings actually landed, out of sample,
    against a homes-only baseline and a within-category permutation null.

Entry is not survival and this module never says it is. Entry says where
capital chose to go; survival says whether it was right. But the SIGN of the
entry coefficient is exactly D87's question: if openings cluster where supply
is already thick, then thin supply marks places the market declined, and the
gap score is pointing at the wrong doors.

THE HONESTY GUARDRAIL (D1, kept)
---------------------------------------------------------------------------
Retail is the DEPENDENT read here, never a predictor of growth. Nothing in this
module regresses anything on future retail. Openings are the left-hand side.

MEASUREMENT DECISIONS, STATED BEFORE THEY ARE USED
---------------------------------------------------------------------------
1. **Straight-line 400 m in EPSG:32618, everywhere in this module.** The
   persisted Dijkstra artefacts (`data/interim/node_nearest_m_*.parquet`) are
   nearest-distance-per-node for ONE frozen supply set; a historical supply set
   cannot be read off them, and re-running the graph per month is not worth it
   for a test whose outcome variable is the binding constraint. D85's rule —
   never compare a straight-line measure to a network one — is respected by
   never mixing them: the t0 supply, the t0 homes, the baseline median and the
   outcome radius are ALL straight-line, so the comparison inside this module
   is internally consistent. The numbers here are therefore NOT comparable to
   `analysis.address_category.supply_ratio_vs_base`, and are never reported as
   if they were.

2. **Present-at-t0 rule.** A location counts as supply at t0 when
   `first_seen_src_date <= t0`, OR when `first_seen_kind = 'backfill_censored'`
   (D79: no date at all). Counting the censored ones as present is the
   CONSERVATIVE choice — it inflates t0 supply and so shrinks the measured
   gap — and `--strict-dated` runs the model again with them dropped, which is
   the aggressive choice. Both are reported. There is no third option: the
   censored rows are 40% of the ledger and dropping them silently would make
   2023 New York look empty.

3. **`first_seen_src_date` is not an opening date.** For the 4,501 Foursquare
   rows it is `date_created` — when Foursquare minted the record. For the 7,026
   `gov_filing` rows it is `storefront_pipeline.opened_on`, a licence or first
   inspection, which D80 measures at a 221-259 day lead from fitout. Both lag
   and lead a real opening. This is measurement error in the timing variable,
   it is non-classical, and it is the single largest caveat on the cohort.

4. **Anachronistic controls.** `homes` comes from present-day PLUTO `UnitsRes`,
   `jobs_400m` from LODES 2023, `transit_entries_400m` from 2026 ridership,
   `retail_index` from present-day PLUTO/LODES (D82). None of them is a 2023
   reading. They enter as controls, never as the tested variable, and the
   direction of the bias (2023-24 construction credited to 2023) is stated.

5. **Out-of-sample, blocked by NTA.** Addresses 200 m apart share almost their
   whole 400 m disc; a random k-fold split would put the same catchment on both
   sides of the split and report a leak as skill. Folds are whole NTAs, and
   every standard error is clustered on NTA.

OUTPUT
---------------------------------------------------------------------------
`run()` writes `data/retrodiction/*.parquet` + `summary.json`; `report()`
renders it. Nothing here writes to the warehouse — it opens read-only, so it is
safe beside a session rebuilding `analysis.address_category`.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "data" / "retrodiction"

#: The opening window. 2023-01 is the earliest month where the ledger's dated
#: coverage is dense enough to be a cohort rather than a curiosity; 2024-12 is
#: the latest month that leaves any exposure at all before the 2026-09 snapshot.
WINDOW_START = dt.date(2023, 1, 1)
WINDOW_END = dt.date(2024, 12, 31)

#: The single snapshot month the ledger has (D79). Everything downstream of it
#: is censored at this date, for every location, identically.
SNAPSHOT = dt.date(2026, 9, 1)

RADIUS_M = 400.0
CRS_METRIC = "EPSG:32618"
BOROUGHS_FULL = ("Manhattan", "Brooklyn")
BOROUGHS_CODE = ("MN", "BK")

#: Categories reported individually. The rest are pooled into the category
#: fixed effect: below a few hundred openings a per-category AUC is noise.
FOCAL_CATEGORIES = ("restaurant", "cafe_bakery", "bar", "nails_beauty",
                    "hair_barber", "grocery")

#: Events needed before a hazard model is worth fitting. Two-sided alpha .05,
#: 80% power, hazard ratio 1.5 per SD of the score:
#:     n_events >= (1.96 + 0.8416)^2 / ln(1.5)^2 = 7.849 / 0.16440 = 47.7
#: Schoenfeld's formula. Rounded up, and it is a FLOOR, not a target: it
#: assumes one covariate and no censoring pathology.
MIN_EVENTS_FOR_HAZARD = 48

#: Sampled addresses for the entry panel. The lot frame is 281,842 addresses in
#: MN+BK and their 400 m discs overlap almost completely, so the marginal
#: information in address 12,001 is close to zero while the join cost is not.
#: Deterministic: ordered by hash(address_id), never by RANDOM().
DEFAULT_SAMPLE_N = 12_000
PERMUTATIONS = 200
N_FOLDS = 5
BOOTSTRAP_DRAWS = 400
RNG_SEED = 20260914

# --- D111 / GTM-168: the Citi Bike activity-growth feature test -------------
#: The pre-registration's own numbers. Changing one of these changes the ship
#: criterion, which is exactly what a pre-registration exists to prevent: they
#: are constants, not options, and no CLI flag reaches them.
NTA_PLACEBO_DRAWS = 200          # P5
DECILE_PLACEBO_DRAWS = 100       # P5, the secondary address-level swap
FOLD_SEEDS = 20                  # P8
DELTA_FLOOR = 0.005              # P3, the absolute floor
DELTA_CI_FLOOR = 0.002           # P3, lower limit of the two-sided 95% CI
AUX_R2_CEILING = 0.80            # P6
BH_Q = 0.10                      # P10
MORAN_K = 8                      # P11
MORAN_PERMUTATIONS = 199         # P11
BIKE_FEATURE = "bike_growth_12m_rel"
BIKE_GROWTH_TABLE = ("analysis", "address_bike_growth")
#: P7's ascertainment rule, fixed here rather than chosen after looking: keep
#: the longest prefix of the outcome window whose monthly dated-opening count
#: stays at or above this fraction of the window's OWN first-12-month median.
ASCERTAINMENT_FLOOR_FRAC = 0.60


# --------------------------------------------------------------------------
# connection
# --------------------------------------------------------------------------
def connect(read_only: bool = True):
    """Read-only warehouse handle, retrying the lock a peer session holds.

    Same posture as `_filings_connect` in the CLI: another session rebuilding
    `analysis.address_category` is the normal state of this project, not an
    error. This module never writes to the database, so read_only is the
    default and the retry exists only for the brief windows when a writer holds
    the file exclusively."""
    import time

    import duckdb

    from loci import db as locidb

    last = None
    for attempt in range(6):
        try:
            return locidb.connect(read_only=read_only)
        except duckdb.IOException as exc:
            last = exc
            time.sleep(3 * 2 ** attempt)
    raise RuntimeError(
        f"retrodiction: the DuckDB file stayed locked across 6 attempts ({last}). "
        f"A peer session is holding it; retry when it finishes.")


# --------------------------------------------------------------------------
# 1. cohort
# --------------------------------------------------------------------------
COHORT_SQL = """
SELECT p.location_key,
       p.category,
       p.display_name,
       p.lon,
       p.lat,
       p.borough,
       p.first_seen_kind,
       p.first_seen_src_field,
       p.first_seen_src_date        AS opened_on,
       (s.poi_id IS NOT NULL)       AS in_principled
FROM analysis.poi_presence p
LEFT JOIN analysis.poi_supply s
       ON s.poi_id = p.poi_id_latest AND s.in_principled
WHERE p.first_seen_kind IN ('source_date', 'gov_filing')
  AND p.first_seen_src_date >= ?
  AND p.first_seen_src_date <= ?
  AND p.borough IN ({boroughs})
"""


def build_cohort(con, start: dt.date = WINDOW_START, end: dt.date = WINDOW_END,
                 boroughs: tuple[str, ...] = BOROUGHS_FULL) -> pd.DataFrame:
    """Storefronts with a KNOWN opening date inside the window.

    `first_seen_kind` is the whole selection story. `source_date` means a
    source published a date (Foursquare `date_created`, a DCWP licence issue
    date, a Medicaid enrolment date); `gov_filing` means D80's pipeline dated it
    off a licence or first inspection. `backfill_censored` — 40% of the ledger —
    is EXCLUDED because it carries no date at all, and that exclusion is the
    cohort's selection bias, quantified by `cohort_selection`."""
    sql = COHORT_SQL.format(boroughs=", ".join(f"'{b}'" for b in boroughs))
    df = con.execute(sql, [start, end]).fetchdf()
    df["opened_on"] = pd.to_datetime(df["opened_on"]).dt.date
    df["exposure_days"] = df["opened_on"].map(lambda d: (SNAPSHOT - d).days)
    return df


def cohort_selection(con, start: dt.date = WINDOW_START, end: dt.date = WINDOW_END,
                     boroughs: tuple[str, ...] = BOROUGHS_FULL) -> dict:
    """How the dated subset differs from the censored population it came from.

    The honest version of "N = 12,572": which sources hand out dates decides
    which businesses can be in the cohort at all, and the answer is food. A
    restaurant is inspected by DOHMH and licensed by DCWP; a hardware store
    declares nothing to anybody."""
    blist = ", ".join(f"'{b}'" for b in boroughs)
    whole = con.execute(
        f"""SELECT category, first_seen_kind, count(*) AS n
            FROM analysis.poi_presence WHERE borough IN ({blist})
            GROUP BY 1, 2""").fetchdf()
    coh = build_cohort(con, start, end, boroughs)

    pivot = whole.pivot_table(index="category", columns="first_seen_kind",
                              values="n", aggfunc="sum").fillna(0)
    for col in ("source_date", "gov_filing", "backfill_censored"):
        if col not in pivot:
            pivot[col] = 0.0
    pivot["total"] = pivot.sum(axis=1)
    pivot["dated_share"] = (pivot["source_date"] + pivot["gov_filing"]) / pivot["total"]
    pivot["in_cohort"] = coh.groupby("category").size().reindex(pivot.index).fillna(0)
    pivot["cohort_share_of_category"] = pivot["in_cohort"] / pivot["total"]

    return {
        "n_cohort": int(len(coh)),
        "n_cohort_principled": int(coh["in_principled"].sum()),
        "by_category": pivot.reset_index().to_dict("records"),
        "by_source_field": coh.groupby(
            ["first_seen_kind", "first_seen_src_field"]).size()
            .rename("n").reset_index().to_dict("records"),
        "food_share": float(
            coh["category"].isin(("restaurant", "cafe_bakery", "bar")).mean()),
    }


# --------------------------------------------------------------------------
# 2. closure audit — the identifiability question, answered with counts
# --------------------------------------------------------------------------
@dataclass
class ClosureInstrument:
    """One candidate way of observing that a business stopped existing."""
    name: str
    available: bool
    observable_closures: int
    reason: str


def cohort_closure_events(con, start: dt.date = WINDOW_START, end: dt.date = WINDOW_END,
                          boroughs: tuple[str, ...] = BOROUGHS_FULL) -> dict:
    """Cohort openings (source_date/gov_filing, in-window) whose CURRENT status
    under the shared open/closed/unknown predicate
    (`model.poi_presence.poi_is_open`, owner rule, GTM-153) reads 'closed'.

    Replaces the ad hoc `closed_on IS NOT NULL` check this module used before
    2026-09-14: the predicate is the ONE source of truth for "is this POI
    still open" and folds in DCWP/DOHMH/SLA/DOS evidence the old check never
    read, not just Foursquare's ledger `closed_on`. 'unknown' -- and any
    future 'stale' state the predicate grows -- is NEVER an event (D79): this
    reads only the `= 'closed'` branch, exactly as `poi_is_open`'s own
    docstring warns never to write `NOT poi_is_open(...)`.

    LEFT JOIN, not INNER: a closed location's `poi_id_latest` is routinely
    NULL (`snapshot()` nulls it the month a location is no longer seen, D79),
    and the predicate's FIRST branch reads the ledger's own `closed_on`
    before it ever touches the joined POI row, so a missing join still
    resolves correctly rather than silently dropping the row.

    Cheap enough to call directly, read-only, without a full `run()` --
    `loci retrodiction events` does exactly that."""
    from loci.model.poi_presence import poi_is_open

    status = poi_is_open("p", "pp.closed_on")
    blist = ", ".join(f"'{b}'" for b in boroughs)
    n_total, n_cohort, n_events = con.execute(f"""
        WITH scored AS (
            SELECT pp.first_seen_kind, pp.first_seen_src_date, pp.borough,
                   {status} AS status
            FROM analysis.poi_presence pp
            LEFT JOIN staging.poi p ON p.poi_id = pp.poi_id_latest
        )
        SELECT count(*) FILTER (WHERE status = 'closed'),
               count(*) FILTER (
                   WHERE first_seen_kind IN ('source_date', 'gov_filing')
                     AND first_seen_src_date BETWEEN ? AND ?
                     AND borough IN ({blist})),
               count(*) FILTER (
                   WHERE status = 'closed'
                     AND first_seen_kind IN ('source_date', 'gov_filing')
                     AND first_seen_src_date BETWEEN ? AND ?
                     AND borough IN ({blist}))
        FROM scored
    """, [start, end, start, end]).fetchone()
    return {"n_predicate_closed_total": int(n_total),
            "n_cohort": int(n_cohort),
            "n_cohort_events": int(n_events)}


def closure_audit(con, start: dt.date = WINDOW_START,
                  end: dt.date = WINDOW_END) -> list[ClosureInstrument]:
    """Enumerate every closure signal in the warehouse and COUNT it.

    This is the load-bearing function of the module. "Survival is hard to
    measure" is an excuse; "there are N observable closures and N is 0" is a
    finding, and it is the one that decides whether docs/GTM.md may claim
    decision value."""
    out: list[ClosureInstrument] = []

    # (a) the ledger's own last_seen — D79's intended instrument
    months = con.execute(
        "SELECT count(DISTINCT last_seen_month), max(n_months_seen) "
        "FROM analysis.poi_presence").fetchone()
    behind = con.execute(
        "SELECT count(*) FROM analysis.poi_presence "
        "WHERE last_seen_month < (SELECT max(last_seen_month) "
        "                         FROM analysis.poi_presence)").fetchone()[0]
    out.append(ClosureInstrument(
        "poi_presence.last_seen_month", months[0] > 1, int(behind),
        f"{months[0]} distinct snapshot month(s), max n_months_seen "
        f"{months[1]}. A location can only fall behind if there is a later "
        f"month to fall behind of. D79: a skipped month is a permanent hole."))

    # (b) storefront_pipeline.is_open — the tautology
    tot, opened, isopen = con.execute(
        "SELECT count(*), count(opened_on), sum(CASE WHEN is_open THEN 1 ELSE 0 END) "
        "FROM analysis.storefront_pipeline").fetchone()
    out.append(ClosureInstrument(
        "storefront_pipeline.is_open", False, 0,
        f"opened_on non-null {opened:,} vs is_open {int(isopen):,} of {tot:,} rows. "
        f"The pipeline's own validate() enforces is_open <=> (opened_on IS NOT "
        f"NULL), so every dated opening 'survives' by construction. is_open "
        f"means EVER OPENED, not OPEN TODAY."))

    # (c) DCWP licence status — the only genuine closure signal in the warehouse
    dcwp = con.execute(
        f"""SELECT count(*) FILTER (WHERE status NOT IN ('Active','Ready for Renewal'))
            FROM staging.storefront_filing
            WHERE source = 'nyc_dcwp_licenses'
              AND borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_CODE)})
              AND filed_on BETWEEN ? AND ?""", [start, end]).fetchone()[0]
    hints = con.execute(
        """SELECT category_hint, count(*) n FROM staging.storefront_filing
           WHERE source = 'nyc_dcwp_licenses'
             AND status NOT IN ('Active', 'Ready for Renewal')
           GROUP BY 1 ORDER BY 2 DESC LIMIT 5""").fetchdf()
    out.append(ClosureInstrument(
        "dcwp_licenses.license_status", int(dcwp) > 0, int(dcwp),
        f"Expired/Surrendered/Voided/Revoked/Failed-to-Renew licences issued in "
        f"the window, MN+BK. Real closures, wrong businesses: the top "
        f"non-Active categories are "
        f"{', '.join(hints['category_hint'].astype(str).head(5))} — DCWP "
        f"licenses trades, not the fifteen daily-needs categories."))

    # (d) Foursquare date_closed — present upstream, filtered out of the cache
    fsq = REPO_ROOT / "data" / "raw" / "fsq_places_nyc.parquet"
    if fsq.exists():
        n, nclosed = con.execute(
            f"SELECT count(*), count(date_closed) FROM read_parquet('{fsq}')"
        ).fetchone()
        out.append(ClosureInstrument(
            "foursquare.date_closed", int(nclosed) > 0, int(nclosed),
            f"{int(nclosed):,} of {int(n):,} cached NYC rows carry date_closed. "
            f"The column exists; the fetch filtered to open venues. Foursquare "
            f"OS Places publishes closed places upstream — re-pulling without "
            f"the open-only filter is the cheapest closure panel available to "
            f"this project and needs no new vendor."))

    # (d2) the PREDICATE's verdict (model.poi_presence.poi_is_open, GTM-153),
    # once a source publishes evidence either way. Added 2026-09-14 after the
    # Foursquare open-only filter was removed upstream; extended the same day
    # to read the shared open/closed/unknown predicate rather than a bare
    # `closed_on IS NOT NULL` -- the predicate also reads DCWP's
    # 'out_of_business' family, DOHMH's 'closed_at_last_inspection', and a
    # lapsed SLA/DOS expiry, none of which ever set `closed_on` (that column
    # is Foursquare-only, sql/027). It puts EVENTS on the cohort for the first
    # time -- and immediately runs into the harder problem, which is not
    # identification but ASCERTAINMENT.
    has_closed = con.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'poi_presence' "
        "AND column_name = 'closed_on'").fetchone()[0]
    if has_closed:
        counts = cohort_closure_events(con, start, end, BOROUGHS_FULL)
        n_ledger = counts["n_predicate_closed_total"]
        n_cohort_events = counts["n_cohort_events"]
        out.append(ClosureInstrument(
            "poi_presence.poi_is_open (predicate)", True, int(n_cohort_events),
            f"{int(n_ledger):,} warehouse rows now read 'closed' under the "
            f"shared open/closed/unknown predicate (Foursquare's ledger "
            f"closed_on, plus DCWP/DOHMH/SLA/DOS published closures the old "
            f"closed_on-only check never saw); {int(n_cohort_events):,} of "
            f"them are cohort openings. ABOVE the {MIN_EVENTS_FOR_HAZARD}-event "
            f"floor -- and still not a survival outcome: the implied two-year "
            f"survival at this event count is far above New York's true "
            f"food-service rate, so ascertainment stays low and categorically "
            f"non-random (a bar closing is announced or licensed away, a "
            f"tailor closing is not). Any hazard ratio fitted here is a "
            f"statement about which sources publish closures, not about New "
            f"York. It is a lead, not an outcome, until an ascertainment "
            f"model exists. 'unknown' is never counted as an event (D79) -- "
            f"only the predicate's 'closed' branch is."))

    # (e) DOHMH — active-only by publication policy
    dohmh = con.execute(
        "SELECT count(*) FROM staging.poi WHERE source_id = 'nyc_dohmh_restaurants'"
    ).fetchone()[0]
    out.append(ClosureInstrument(
        "dohmh_restaurants", False, 0,
        f"{int(dohmh):,} establishments staged, all with observed_on = the "
        f"extract date. 43nn-pn8j publishes establishments 'in an active status "
        f"as of the date of the data pull': a closed restaurant is ABSENT, not "
        f"stale. This is survivorship by publication policy and no amount of "
        f"re-reading the cached file fixes it."))

    # (f) DOF storefront registry — vacancy, but at the premises grain
    reg = con.execute(
        """SELECT max(reporting_year),
                  count(*) FILTER (WHERE reporting_year = 2024),
                  count(*) FILTER (WHERE reporting_year = 2025)
           FROM analysis.storefront""").fetchone()
    out.append(ClosureInstrument(
        "dof_storefront_registry.vacant_1231", False, 0,
        f"LL157 vacancy runs to {reg[0]} ({int(reg[1]):,} rows in 2024, only "
        f"{int(reg[2]):,} filed for 2025). It is the best independent signal in "
        f"the city, and it is unusable AS AN OUTCOME here: premises grain with "
        f"no business identity, so a cohort POI sits within 30 m of tens of "
        f"registry units and 'some storefront in this building is vacant' is "
        f"not 'this business closed'."))

    return out


def observable_closures(audit: list[ClosureInstrument]) -> int:
    """Closures usable as a survival outcome for the daily-needs cohort.

    DCWP's are real closures of businesses that are not in any of the fifteen
    categories, so they are counted at zero HERE while being reported honestly
    in the audit — a closure of a pedicab licence is not an observation of a
    café's survival."""
    # `poi_presence.closed_on` is deliberately NOT in this set. It carries real
    # events, but at ~3% ascertainment and categorically non-random, counting
    # them would open the hazard gate on a panel that measures Foursquare, not
    # New York. It is reported in the audit and excluded from the gate.
    usable = {"poi_presence.last_seen_month", "foursquare.date_closed"}
    return sum(i.observable_closures for i in audit if i.name in usable)


# --------------------------------------------------------------------------
# 3. survival — implemented, and gated
# --------------------------------------------------------------------------
def kaplan_meier(durations: np.ndarray, events: np.ndarray,
                 at: tuple[int, ...] = (12, 24)) -> dict:
    """Survival probability at the given month marks. Plain KM, no dependency.

    durations in MONTHS, events 1 = closed, 0 = still open at the snapshot.
    Written out longhand because the estimator is four lines and importing a
    library to run it on a cohort with zero events would be theatre."""
    order = np.argsort(durations)
    d, e = np.asarray(durations)[order], np.asarray(events)[order]
    n = len(d)
    surv, curve = 1.0, {}
    for t in np.unique(d[e == 1]):
        died = int(((d == t) & (e == 1)).sum())
        risk = int((d >= t).sum())
        if risk > 0:
            surv *= (1.0 - died / risk)
        curve[float(t)] = surv
    out = {}
    for mark in at:
        s = 1.0
        for t, v in sorted(curve.items()):
            if t <= mark:
                s = v
        out[f"s_{mark}m"] = float(s)
        out[f"at_risk_{mark}m"] = int((np.asarray(durations) >= mark).sum())
    out["n"] = int(n)
    out["events"] = int(np.asarray(events).sum())
    return out


def survival_gate(cohort: pd.DataFrame, n_events: int) -> dict:
    """Refuse to fit a hazard model that has nothing to fit on, and say why.

    The failure criterion, written down before the run: fewer than
    MIN_EVENTS_FOR_HAZARD observable closures means no Kaplan-Meier curve, no
    Cox model, no AUC on survival, and no decision-value claim in docs/GTM.md.
    A survival curve estimated from a cohort that is 100% survivors by
    construction is a picture of the extract, not of New York."""
    exposure = cohort["exposure_days"].dropna().to_numpy() / 30.44
    return {
        "n_cohort": int(len(cohort)),
        "n_events_observable": int(n_events),
        "min_events_required": MIN_EVENTS_FOR_HAZARD,
        "power_basis": ("Schoenfeld: (z_{1-a/2} + z_{1-b})^2 / ln(HR)^2 with "
                        "alpha .05, power .80, HR 1.5 per SD => 47.7 events."),
        "identified": bool(n_events >= MIN_EVENTS_FOR_HAZARD),
        "exposure_months_p25_p50_p75": [
            float(np.percentile(exposure, q)) for q in (25, 50, 75)] if len(exposure) else [],
        "censoring": ("Administrative and IDENTICAL for every row: the single "
                      "snapshot is 2026-09, so every location is censored at "
                      f"{SNAPSHOT}. Exposure varies (a 2023-01 opening has 44 "
                      "months, a 2024-12 opening 21) but the censoring "
                      "indicator does not vary at all — it is 1 everywhere."),
        "verdict": ("NOT IDENTIFIED — no hazard model fitted." if
                    n_events < MIN_EVENTS_FOR_HAZARD else "identified"),
        "what_a_second_snapshot_adds": (
            "One more monthly `loci poi-snapshot` turns `last_seen_month` into "
            "a real variable: a location present in 2026-09 and absent in the "
            "next month is the FIRST observable closure this project has ever "
            "had. But a snapshot only observes closures from that month "
            "FORWARD, so the 2023-24 cohort's exits between 2023 and 2026 stay "
            "permanently invisible (D79: an observation cannot be reconstructed "
            "after the fact). To retrodict THIS cohort you need a historical "
            "panel, not a future one: Foursquare OS Places re-pulled with "
            "date_closed (free, in hand), or Google Places Insights' monthly "
            "snapshots back to 2024-01 (D86 P1, GTM-159). Twelve forward "
            "months at the ledger's dated volume would yield roughly "
            "0.05-0.12 x 12,572 ~ 600-1,500 exits — far past the 48-event "
            "floor — but not until 2027-09."),
    }


def fit_cox(panel: pd.DataFrame, score_col: str):           # pragma: no cover
    """Cox PH with category fixed effects, clustered on NTA.

    Lazily imported and deliberately NOT added to pyproject: adding `lifelines`
    for a model that provably cannot be fitted on today's data would be a
    dependency bought with no observation behind it. When a closure panel
    exists, `uv add lifelines` and this runs unchanged."""
    from lifelines import CoxPHFitter

    df = panel[["duration_months", "event", score_col, "log_homes",
                "category", "nta_code"]].dropna()
    design = pd.get_dummies(df, columns=["category"], drop_first=True)
    cph = CoxPHFitter()
    cph.fit(design.drop(columns=["nta_code"]), duration_col="duration_months",
            event_col="event", cluster_col=None, robust=True)
    return cph


# --------------------------------------------------------------------------
# 4. supply as of t — the counterfactual score
# --------------------------------------------------------------------------
def _project(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", CRS_METRIC, always_xy=True)
    return tr.transform(np.asarray(lon), np.asarray(lat))


def supply_as_of(con, points: pd.DataFrame, asof: dt.date,
                 radius_m: float = RADIUS_M, include_censored: bool = True,
                 categories: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Principled supply within `radius_m` straight-line metres of each point,
    counting only what existed at `asof`.

    THE LEAKAGE RULE, and the one the tests pin: a competitor whose
    `first_seen_src_date` is AFTER `asof` must not be counted. If it were, the
    "score at opening" would already know about openings that had not happened,
    and the entry model would be predicting its own right-hand side.

    `include_censored` decides what to do with D79's 40% undated rows. True (the
    default) treats them as present at any date, which INFLATES t0 supply and
    SHRINKS the measured gap — conservative with respect to the claim the screen
    wants to make. False drops them, which is the aggressive reading. Both are
    run; neither is hidden.
    """
    cats = tuple(categories) if categories else None
    censor_clause = ("OR p.first_seen_kind = 'backfill_censored'"
                     if include_censored else "")
    cat_clause = ""
    if cats:
        cat_clause = "AND p.category IN (" + ", ".join(f"'{c}'" for c in cats) + ")"

    sup = con.execute(f"""
        SELECT p.location_key, p.category, p.lon, p.lat
        FROM analysis.poi_presence p
        JOIN analysis.poi_supply s
          ON s.poi_id = p.poi_id_latest AND s.in_principled
        WHERE p.borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_FULL)})
          {cat_clause}
          AND (p.first_seen_src_date <= DATE '{asof.isoformat()}' {censor_clause})
    """).fetchdf()

    sx, sy = _project(sup["lon"].to_numpy(), sup["lat"].to_numpy())
    # `sup` and `pts` are read by DuckDB's replacement scan straight out of
    # this frame's locals -- they look unused to a linter and are not.
    sup = sup.assign(x=sx, y=sy)                                    # noqa: F841
    px, py = _project(points["lon"].to_numpy(), points["lat"].to_numpy())
    pts = points.assign(x=px, y=py)                                 # noqa: F841

    con.execute("CREATE OR REPLACE TEMP TABLE _rd_sup AS SELECT * FROM sup")
    con.execute("CREATE OR REPLACE TEMP TABLE _rd_pts AS SELECT * FROM pts")
    return con.execute(f"""
        SELECT t.point_id, s.category, count(*) AS supply
        FROM _rd_pts t JOIN _rd_sup s
          ON s.x BETWEEN t.x - {radius_m} AND t.x + {radius_m}
         AND s.y BETWEEN t.y - {radius_m} AND t.y + {radius_m}
         AND (s.x - t.x) * (s.x - t.x) + (s.y - t.y) * (s.y - t.y)
             <= {radius_m * radius_m}
        GROUP BY 1, 2
    """).fetchdf()


def count_within(con, points: pd.DataFrame, targets: pd.DataFrame,
                 radius_m: float = RADIUS_M, by: str = "category") -> pd.DataFrame:
    """Generic straight-line counter — used for the outcome (openings in the
    window) and for the homes denominator, so both share one definition of
    "within 400 m" with the supply reconstruction."""
    tx, ty = _project(targets["lon"].to_numpy(), targets["lat"].to_numpy())
    tg = targets.assign(x=tx, y=ty)
    if "weight" not in tg:
        tg = tg.assign(weight=1.0)                                  # noqa: F841
    px, py = _project(points["lon"].to_numpy(), points["lat"].to_numpy())
    pts = points.assign(x=px, y=py)                                 # noqa: F841
    con.execute("CREATE OR REPLACE TEMP TABLE _rd_tg AS SELECT * FROM tg")
    con.execute("CREATE OR REPLACE TEMP TABLE _rd_pt2 AS SELECT * FROM pts")
    grp = f"t.point_id, g.{by}" if by else "t.point_id"
    sel = f"{grp}, count(*) AS n, sum(COALESCE(g.weight, 1)) AS wsum"
    return con.execute(f"""
        SELECT {sel}
        FROM _rd_pt2 t JOIN _rd_tg g
          ON g.x BETWEEN t.x - {radius_m} AND t.x + {radius_m}
         AND g.y BETWEEN t.y - {radius_m} AND t.y + {radius_m}
         AND (g.x - t.x) * (g.x - t.x) + (g.y - t.y) * (g.y - t.y)
             <= {radius_m * radius_m}
        GROUP BY {grp}
    """).fetchdf()


# --------------------------------------------------------------------------
# 5. the entry panel
# --------------------------------------------------------------------------
def build_panel(con, *, sample_n: int = DEFAULT_SAMPLE_N,
                categories: tuple[str, ...] = FOCAL_CATEGORIES,
                radius_m: float = RADIUS_M,
                t0: dt.date = WINDOW_START,
                window_end: dt.date = WINDOW_END,
                include_censored: bool = True,
                bike_growth: bool = False,
                member_only: bool = True,
                bike_growth_lag_asof: dt.date | None = None) -> pd.DataFrame:
    """address x category, scored as of t0, with the 2023-24 openings as the
    dependent variable.

    Deterministic sampling by `hash(address_id)` so a rerun is a rerun. Lot
    frame only (D84: a street midpoint has no residents and the homes
    denominator would be structurally zero).

    `bike_growth=True` left-joins `analysis.address_bike_growth` (D111,
    GTM-168) at `asof_month = t0` and the requested `member_only` flag. It is a
    LEFT join on purpose: the growth table NULLs the feature wherever the
    balanced dock set is too thin (`balanced_share < 0.5`), and those rows have
    to stay in the frame long enough for `bike_attrition()` to count them and
    compare them to the rows that survive (P2). The row DROP happens once,
    inside `fit_growth_test`, so the baseline and the treatment model are fitted
    on the identical subsample.

    `bike_growth_lag_asof` joins a SECOND vintage of the same feature as
    `bike_growth_12m_rel_lag` — P9's pre-trend. Default for a t0 of 2025-01 is
    2023-12 (windows ending 2023-12), i.e. t0 minus 13 months."""
    pts = con.execute(f"""
        SELECT a.address_id AS point_id, a.lon, a.lat, a.nta_code, a.borough,
               a.units_capped, a.jobs_400m, a.transit_entries_400m,
               c.retail_index,
               a.homes_400m AS homes_400m_network
        FROM analysis.address a
        LEFT JOIN analysis.address_character c USING (address_id)
        WHERE a.frame = 'lot'
          AND a.borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_CODE)})
          AND a.lon IS NOT NULL AND a.lat IS NOT NULL
        ORDER BY hash(a.address_id)
        LIMIT {int(sample_n)}
    """).fetchdf()

    # homes at t0, straight-line, from the SAME lot register the screen uses.
    # Anachronism, stated: PLUTO UnitsRes is present-day, so 2023-24 completions
    # are credited to 2023. That biases the control toward the growth areas,
    # i.e. AGAINST finding that openings follow existing supply -- it works
    # against this module's headline, not for it.
    homes_src = con.execute(f"""
        SELECT lon, lat, units_capped AS weight FROM analysis.address
        WHERE frame = 'lot' AND borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_CODE)})
          AND units_capped > 0 AND lon IS NOT NULL
    """).fetchdf()
    homes = count_within(con, pts[["point_id", "lon", "lat"]], homes_src,
                         radius_m=radius_m, by="")
    homes = homes.rename(columns={"wsum": "homes_t0"})[["point_id", "homes_t0"]]

    sup = supply_as_of(con, pts[["point_id", "lon", "lat"]],
                       asof=t0, radius_m=radius_m,
                       include_censored=include_censored, categories=categories)

    cohort = build_cohort(con)
    cohort = cohort[cohort["in_principled"] & cohort["category"].isin(categories)]
    opens = count_within(con, pts[["point_id", "lon", "lat"]],
                         cohort[["lon", "lat", "category"]], radius_m=radius_m)
    opens = opens.rename(columns={"n": "openings"})[["point_id", "category", "openings"]]

    grid = pts[["point_id"]].merge(pd.DataFrame({"category": list(categories)}),
                                   how="cross")
    panel = (grid
             .merge(sup, on=["point_id", "category"], how="left")
             .merge(opens, on=["point_id", "category"], how="left")
             .merge(homes, on="point_id", how="left")
             .merge(pts, on="point_id", how="left"))
    panel[["supply", "openings", "homes_t0"]] = \
        panel[["supply", "openings", "homes_t0"]].fillna(0.0)

    panel = panel[panel["homes_t0"] > 0].copy()
    panel["supply_per_1k_t0"] = panel["supply"] / panel["homes_t0"] * 1000.0
    base = (panel.groupby("category")["supply_per_1k_t0"].median()
            .rename("base_median").reset_index())
    panel = panel.merge(base, on="category", how="left")
    # A category whose sample median is 0 has no scale to divide by; leave the
    # ratio NULL rather than minting an infinity.
    panel["supply_ratio_t0"] = np.where(
        panel["base_median"] > 0, panel["supply_per_1k_t0"] / panel["base_median"], np.nan)
    panel["own_gap_flag"] = (panel["supply"] == 0).astype(int)
    panel["log_homes"] = np.log(panel["homes_t0"] + 1.0)
    panel["log_jobs"] = np.log(panel["jobs_400m"].fillna(0) + 1.0)
    panel["log_transit"] = np.log(panel["transit_entries_400m"].fillna(0) + 1.0)
    panel["retail_index"] = panel["retail_index"].fillna(panel["retail_index"].median())
    panel["log_score"] = np.log1p(panel["supply_ratio_t0"])
    panel["y"] = (panel["openings"] > 0).astype(int)
    # A second, harder outcome. "Any opening within 400 m in two years" is
    # nearly degenerate for restaurants (91% of sampled addresses), and an AUC
    # on a 91/9 split is dominated by the rare side. `y_hi` = openings at or
    # above the category's own 75th percentile asks the sharper question: did
    # the score find the blocks where openings CONCENTRATED?
    q75 = panel.groupby("category")["openings"].transform(lambda s: s.quantile(0.75))
    panel["y_hi"] = (panel["openings"] > np.maximum(q75, 0)).astype(int)
    # "is this a retail street" in two columns, needed by P6's auxiliary R2 and
    # by the separating check the spec asks for. Own- and OTHER-category t0
    # supply in the same disc; `supply_other` is the sum over the other five
    # focal categories, so it varies by row, not just by address.
    panel["supply_other"] = (panel.groupby("point_id")["supply"].transform("sum")
                             - panel["supply"])
    panel["log_supply_own"] = np.log1p(panel["supply"])
    panel["log_supply_other"] = np.log1p(panel["supply_other"])
    panel["t0"] = t0
    panel["window_end"] = window_end
    panel["cd_code"] = panel["nta_code"].map(cd_code)
    if bike_growth:
        panel = attach_bike_growth(con, panel, asof=t0, member_only=member_only)
        lag = bike_growth_lag_asof or _months_before(t0, 13)
        panel = attach_bike_growth(con, panel, asof=lag, member_only=member_only,
                                   suffix="_lag", required=False)
        panel["bike_growth_asof"] = t0
        panel["bike_growth_lag_asof"] = lag
        panel["bike_member_only"] = bool(member_only)
    return panel


# --------------------------------------------------------------------------
# 6. the entry model, its baseline, its placebo
# --------------------------------------------------------------------------
def _auc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    if y.min() == y.max():
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    sp = np.asarray(p)[order]
    ranks[order] = np.arange(1, len(p) + 1, dtype=float)
    # average ranks over ties
    i = 0
    while i < len(sp):
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    n1, n0 = y.sum(), len(y) - y.sum()
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def _design(panel: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, list[str]]:
    import pandas as _pd
    X = panel[cols].copy()
    dummies = _pd.get_dummies(panel["category"], prefix="cat", drop_first=True)
    X = _pd.concat([X, dummies.astype(float)], axis=1)
    X.insert(0, "const", 1.0)
    return X.to_numpy(dtype=float), list(X.columns)


def _fit_logit(panel: pd.DataFrame, cols: list[str], cluster: str = "nta_code"):
    import statsmodels.api as sm
    X, names = _design(panel, cols)
    y = panel["y"].to_numpy(dtype=float)
    groups = panel[cluster].fillna("NA").to_numpy()
    res = sm.Logit(y, X).fit(disp=0, maxiter=200, cov_type="cluster",
                             cov_kwds={"groups": groups, "use_correction": True})
    return res, names


def blocked_cv_auc(panel: pd.DataFrame, cols: list[str], n_folds: int = N_FOLDS,
                   seed: int = RNG_SEED,
                   fold_map: dict | None = None,
                   y_col: str = "y") -> tuple[float, np.ndarray]:
    """Out-of-sample AUC with WHOLE NTAs held out.

    A random split leaks: two addresses 150 m apart share nearly the same 400 m
    disc, the same supply, the same openings. Holding out NTAs forces the model
    to generalise to a neighbourhood it has never seen, which is the only
    version of "predicts" an allocator should accept.

    `fold_map` (P2, GTM-168) is an EXPLICIT NTA -> fold assignment. Without it
    the folds are derived from `panel["nta_code"].unique()`, which is row-order
    and row-SET dependent: the same seed gives different folds once NULL
    filtering removes an NTA, so a "paired" comparison between two models fitted
    on different frames is not paired at all. Derive the map once from the
    shared row set with `nta_fold_map()` and hand it to both fits."""
    import statsmodels.api as sm
    if fold_map is not None:
        folds = [np.asarray([k for k, v in fold_map.items() if v == f], dtype=object)
                 for f in sorted(set(fold_map.values()))]
    else:
        rng = np.random.default_rng(seed)
        ntas = np.asarray(panel["nta_code"].fillna("NA").unique(), dtype=object)
        rng.shuffle(ntas)
        folds = np.array_split(ntas, n_folds)
    preds = np.full(len(panel), np.nan)
    idx = panel.reset_index(drop=True)
    if y_col != "y":
        idx = idx.assign(y=idx[y_col])
    for fold in folds:
        te = idx["nta_code"].fillna("NA").isin(fold).to_numpy()
        tr = ~te
        if idx.loc[tr, "y"].nunique() < 2 or te.sum() == 0:
            continue
        Xtr, _ = _design(idx[tr], cols)
        Xte, _ = _design(idx[te], cols)
        try:
            m = sm.Logit(idx.loc[tr, "y"].to_numpy(dtype=float), Xtr).fit(disp=0, maxiter=200)
            preds[te] = m.predict(Xte)
        except Exception:                                   # separation in a fold
            continue
    ok = ~np.isnan(preds)
    return _auc(idx.loc[ok, "y"].to_numpy(), preds[ok]), preds


def cluster_bootstrap_auc(panel: pd.DataFrame, cols: list[str],
                          draws: int = BOOTSTRAP_DRAWS,
                          seed: int = RNG_SEED) -> tuple[float, float]:
    """95% CI on the out-of-sample AUC, resampling NTAs not rows.

    Resampling rows would treat 12,000 overlapping discs as 12,000 independent
    observations and return an interval several times too narrow."""
    rng = np.random.default_rng(seed)
    _, preds = blocked_cv_auc(panel, cols, seed=seed)
    idx = panel.reset_index(drop=True)
    ok = ~np.isnan(preds)
    sub = idx[ok].assign(_p=preds[ok])
    groups = sub.groupby("nta_code").indices
    keys = list(groups)
    vals = []
    for _ in range(draws):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        rows = np.concatenate([groups[keys[k]] for k in pick])
        a = _auc(sub["y"].to_numpy()[rows], sub["_p"].to_numpy()[rows])
        if not np.isnan(a):
            vals.append(a)
    if not vals:
        return float("nan"), float("nan")
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def permutation_null(panel: pd.DataFrame, cols: list[str], score_col: str,
                     draws: int = PERMUTATIONS, seed: int = RNG_SEED) -> dict:
    """Null AUC distribution from permuting the score WITHIN category.

    Within-category because the category fixed effects alone carry real signal
    (a restaurant opens somewhere far more often than a hardware store does),
    and a null that destroyed that too would be trivially easy to beat."""
    rng = np.random.default_rng(seed + 1)
    aucs = []
    for _ in range(draws):
        p = panel.copy()
        p[score_col] = (p.groupby("category")[score_col]
                        .transform(lambda s: rng.permutation(s.to_numpy())))
        a, _ = blocked_cv_auc(p, cols, seed=seed)
        if not np.isnan(a):
            aucs.append(a)
    arr = np.asarray(aucs)
    return {"draws": int(len(arr)),
            "mean": float(arr.mean()) if len(arr) else float("nan"),
            "p95": float(np.percentile(arr, 95)) if len(arr) else float("nan"),
            "max": float(arr.max()) if len(arr) else float("nan")}


def fit_entry(panel: pd.DataFrame, *, permutations: int = PERMUTATIONS) -> dict:
    """The whole entry test: full model, homes-only baseline, placebo, D1 sign.

    THE FAILURE CRITERION, fixed before the run:
      * the score adds nothing unless its blocked-CV AUC clears the homes-only
        baseline AND clears the 95th percentile of the permutation null;
      * the D1 sign is whatever it is, and a POSITIVE coefficient on the t0
        supply ratio (openings follow existing supply) is reported as such, not
        re-parameterised until it changes sign.
    """
    full_cols = ["log_score", "own_gap_flag", "log_homes", "log_jobs",
                 "log_transit", "retail_index"]
    base_cols = ["log_homes"]
    p = panel.dropna(subset=["log_score"]).copy()

    rob, names = _fit_logit(p, full_cols)
    coefs = {n: {"coef": float(rob.params[i]), "se": float(rob.bse[i]),
                 "z": float(rob.tvalues[i]), "p": float(rob.pvalues[i]),
                 "ci_lo": float(rob.conf_int()[i][0]),
                 "ci_hi": float(rob.conf_int()[i][1])}
             for i, n in enumerate(names)}

    auc_full, _ = blocked_cv_auc(p, full_cols)
    auc_base, _ = blocked_cv_auc(p, base_cols)
    ci_lo, ci_hi = cluster_bootstrap_auc(p, full_cols)
    ci_lo_b, ci_hi_b = cluster_bootstrap_auc(p, base_cols)
    null = permutation_null(p, full_cols, "log_score", draws=permutations)

    per_cat = {}
    for cat, g in p.groupby("category"):
        if g["y"].nunique() < 2 or len(g) < 500:
            per_cat[cat] = {"n": int(len(g)), "skipped": "no variance or n < 500"}
            continue
        try:
            r, nm = _fit_logit(g, ["log_score", "own_gap_flag", "log_homes"])
            i = nm.index("log_score")
            j = nm.index("own_gap_flag")
            a, _ = blocked_cv_auc(g, ["log_score", "own_gap_flag", "log_homes"])
            ab, _ = blocked_cv_auc(g, base_cols)
            per_cat[cat] = {
                "n": int(len(g)), "opening_rate": float(g["y"].mean()),
                "log_score_coef": float(r.params[i]),
                "log_score_ci": [float(r.conf_int()[i][0]), float(r.conf_int()[i][1])],
                "own_gap_coef": float(r.params[j]),
                "own_gap_ci": [float(r.conf_int()[j][0]), float(r.conf_int()[j][1])],
                "auc": float(a), "auc_homes_only": float(ab)}
        except Exception as exc:
            per_cat[cat] = {"n": int(len(g)), "skipped": str(exc)[:120]}

    # the harder outcome, same design, same folds
    hard = p.assign(y=p["y_hi"])
    auc_hi, _ = blocked_cv_auc(hard, full_cols)
    auc_hi_base, _ = blocked_cv_auc(hard, base_cols)
    rob_hi, names_hi = _fit_logit(hard, full_cols)
    i_hi = names_hi.index("log_score")
    hi_block = {
        "outcome": "openings > category 75th percentile",
        "rate": float(hard["y"].mean()),
        "auc_full": float(auc_hi), "auc_homes_only": float(auc_hi_base),
        "log_score_coef": float(rob_hi.params[i_hi]),
        "log_score_ci": [float(rob_hi.conf_int()[i_hi][0]),
                         float(rob_hi.conf_int()[i_hi][1])]}

    sc = coefs["log_score"]
    gp = coefs["own_gap_flag"]
    sign = ("POSITIVE — openings go where supply is ALREADY THICK"
            if sc["ci_lo"] > 0 else
            "NEGATIVE — openings go where supply is THIN"
            if sc["ci_hi"] < 0 else "INDISTINGUISHABLE FROM ZERO")

    return {
        "n_rows": int(len(p)), "n_addresses": int(p["point_id"].nunique()),
        "n_ntas": int(p["nta_code"].nunique()),
        "opening_rate": float(p["y"].mean()),
        "coefficients": coefs,
        "auc_full": auc_full, "auc_full_ci": [ci_lo, ci_hi],
        "auc_homes_only": auc_base, "auc_homes_only_ci": [ci_lo_b, ci_hi_b],
        "auc_lift": float(auc_full - auc_base),
        "permutation_null": null,
        # THE HONEST BASELINE (statistician, 2026-09-14). Permuting the score
        # inside the FULL model refits everything-but-the-score, so the null's
        # mean IS the no-score AUC -- confirmed by refitting directly (0.8537).
        # The homes-only comparator flatters the result: density + retail_index
        # + category fixed effects alone reach 0.854, so the score's real
        # marginal contribution is ~+0.013, not the +0.048 against homes-only.
        "auc_no_score": float(null["mean"]),
        "auc_lift_vs_no_score": float(auc_full - null["mean"]),
        "hard_outcome": hi_block,
        "beats_baseline": bool(auc_full > auc_base and ci_lo > auc_base),
        "beats_placebo": bool(auc_full > null["p95"]),
        "d1_sign": sign,
        "d1_score_ci": [sc["ci_lo"], sc["ci_hi"]],
        "d1_own_gap_ci": [gp["ci_lo"], gp["ci_hi"]],
        "by_category": per_cat,
    }


# --------------------------------------------------------------------------
# 7. run / report
# --------------------------------------------------------------------------
@dataclass
class RunReport:
    cohort_n: int = 0
    selection: dict = field(default_factory=dict)
    closure: list = field(default_factory=list)
    survival: dict = field(default_factory=dict)
    entry: dict = field(default_factory=dict)
    entry_strict: dict = field(default_factory=dict)
    bike_growth: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)


def run(*, window: str | None = None, radius_m: float = RADIUS_M,
        sample_n: int = DEFAULT_SAMPLE_N, permutations: int = PERMUTATIONS,
        out: pathlib.Path | str | None = None, strict_dated: bool = True,
        bike_growth: bool = False, asof: str | None = None,
        member_only: bool = True,
        truncate_outcome: bool = True, truncate_at: str | None = None,
        growth_placebo_draws: int = NTA_PLACEBO_DRAWS,
        growth_bootstrap_draws: int = BOOTSTRAP_DRAWS,
        growth_seeds: int = FOLD_SEEDS,
        confirmatory_out: pathlib.Path | str | None = None) -> dict:
    """Cohort -> closure audit -> gated survival -> entry retrodiction, and
    (D111, GTM-168) the Citi Bike activity-growth feature test."""
    t_start = dt.datetime.now()
    start, end = WINDOW_START, WINDOW_END
    if window:
        a, b = window.split(":")
        start = dt.date(int(a[:4]), int(a[5:7]), 1)
        y, m = int(b[:4]), int(b[5:7])
        end = (dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1))
    t0 = _parse_month(asof) if asof else start

    out_dir = pathlib.Path(out) if out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)

    # P7's truncation, decided BEFORE the outcome is counted. The 2025-01
    # vintage's nominal window runs to 2026-06, but the filing lead is 221-259
    # days (D80), so the last months are ascertainment, not New York.
    ascertainment = ascertainment_by_month(con, start, end)
    if truncate_at:
        end = _month_end(_parse_month(truncate_at))
        ascertainment["applied"] = str(end)
        ascertainment["rule_applied"] = "explicit --truncate-at"
    elif truncate_outcome and ascertainment.get("truncate_at"):
        cut = _month_end(_parse_month(ascertainment["truncate_at"]))
        if cut < end:
            end = cut
            ascertainment["applied"] = str(end)
            ascertainment["rule_applied"] = ascertainment["rule"]
    ascertainment.setdefault("applied", None)

    cohort = build_cohort(con, start, end)
    sel = cohort_selection(con, start, end)
    audit = closure_audit(con, start, end)
    n_events = observable_closures(audit)

    cohort["duration_months"] = cohort["exposure_days"] / 30.44
    cohort["event"] = 0                      # no closure is observable; see audit
    gate = survival_gate(cohort, n_events)
    gate["km_if_events_existed"] = kaplan_meier(
        cohort["duration_months"].to_numpy(), cohort["event"].to_numpy())

    panel = build_panel(con, sample_n=sample_n, radius_m=radius_m, t0=t0,
                        window_end=end, include_censored=True,
                        bike_growth=bike_growth, member_only=member_only)
    entry = fit_entry(panel, permutations=permutations)

    growth: dict = {}
    if bike_growth:
        growth = fit_growth_test(
            panel, con=con, placebo_draws=growth_placebo_draws,
            bootstrap_draws=growth_bootstrap_draws, seeds=growth_seeds)
        oof = growth.pop("_oof")
        oof.to_parquet(out_dir / "bike_growth_oof.parquet", index=False)
        growth["ascertainment"] = ascertainment
        conf = None
        if confirmatory_out:
            # P7 needs the OTHER vintage's fixed out-of-fold predictions, not
            # its summary numbers: the CI on (delta1 - delta2) is computed on
            # JOINTLY resampled clusters and cannot be reconstructed from two
            # published intervals.
            try:
                conf = load_bike_growth(confirmatory_out) or None
            except FileNotFoundError:
                conf = None
        growth["verdict"] = bike_growth_verdict(growth, conf, oof=oof)
        if conf is not None:
            conf.pop("_oof", None)

    entry_strict = {}
    if strict_dated:
        panel_s = build_panel(con, sample_n=sample_n, radius_m=radius_m, t0=t0,
                              window_end=end, include_censored=False)
        entry_strict = fit_entry(panel_s, permutations=max(50, permutations // 4))

    cohort.to_parquet(out_dir / "cohort.parquet", index=False)
    panel.to_parquet(out_dir / "entry_panel.parquet", index=False)
    rep = RunReport(cohort_n=len(cohort), selection=sel,
                    closure=[asdict(i) for i in audit], survival=gate,
                    entry=entry, entry_strict=entry_strict, bike_growth=growth,
                    params={"window": f"{start}:{end}", "radius_m": radius_m,
                            "sample_n": sample_n, "permutations": permutations,
                            "distance": "straight-line EPSG:32618",
                            "snapshot": str(SNAPSHOT), "seed": RNG_SEED,
                            "t0": str(t0), "member_only": bool(member_only),
                            "bike_growth": bool(bike_growth),
                            "supply_hash": _supply_hash(con),
                            "runtime_s": round(
                                (dt.datetime.now() - t_start).total_seconds(), 1),
                            "ran_at": dt.datetime.now().isoformat(timespec="seconds")})
    payload = asdict(rep)
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2, default=str))
    con.close()
    return payload


def load(out: pathlib.Path | str | None = None) -> dict:
    path = (pathlib.Path(out) if out else OUT_DIR) / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"no run at {path} — run `loci retrodiction run` first")
    return json.loads(path.read_text())


# ===========================================================================
# 8. LL157 GO-DARK — the outcome the first pass wrongly rejected
# ===========================================================================
# The first version of this module dismissed the DOF Storefront Registry as
# "premises grain with no business identity". That objection is correct about
# ATTRIBUTING a closure to a particular cohort POI. It is wrong about the
# OUTCOME. `analysis.storefront` is a premises x reporting-year panel carrying
# `vacant_1231`, and in MN+BK, keyed on `premises_id` with `bool_or` within a
# year:
#
#     occupied 2022-12-31 -> VACANT 2024-12-31        1,080   <- events
#     occupied 2022-12-31 -> occupied 2024-12-31     11,641
#     occupied 2022-12-31 -> no 2024 filing           3,510   <- attrition
#     vacant  2022-12-31 -> occupied 2024-12-31       1,050
#
# 1,080 go-dark events is 22x the 48-event floor, inside the exact window, with
# no new data. So the honest statement is NOT "survival is unidentified" but:
# **business-level survival for the 12,572-POI cohort is not identified;
# premises-level go-dark is.**
#
# What it can and cannot resolve, stated before it is used:
#   * It is LANDLORD SELF-REPORT under Local Law 157. The filing universe is
#     selected, and the 3,510 premises that stop filing are plausibly the
#     distressed ones, so attrition is modelled BOTH ways and both are reported.
#   * Vacancy is not failure. A unit can go dark for a gut renovation, so the
#     model is also split on `construction_reported`.
#   * `bool_or(vacant_1231)` within a premises means ANY unit in the building
#     went dark, not all of them. A premises is a building address, not a shop.
#   * `primary_business_activity` is far too coarse for the fifteen categories
#     — RETAIL / FOOD SERVICES / OTHER is the finest honest split, so the
#     per-category view is three groups, Bonferroni-corrected over three tests,
#     not fifteen.

GO_DARK_BASE_YEAR = 2022
GO_DARK_OUTCOME_YEAR = 2024
#: Coarser than NTA, for the blocking robustness the statistician asked for.
#: A 6 x 5 quantile tiling of projected NTA centroids -- deterministic, needs no
#: clustering dependency, and is by construction coarser than the 103 NTAs.
GO_DARK_BLOCKS_X = 6
GO_DARK_BLOCKS_Y = 5

ACTIVITY_GROUPS = {
    "FOOD SERVICES": "food",
    "RETAIL": "retail",
}


def _activity_group(raw: str | None) -> str:
    return ACTIVITY_GROUPS.get((raw or "").strip().upper(), "other")


def go_dark_panel(con, *, base_year: int = GO_DARK_BASE_YEAR,
                  outcome_year: int = GO_DARK_OUTCOME_YEAR,
                  t0: dt.date = WINDOW_START, radius_m: float = RADIUS_M,
                  attrition_is_event: bool = False,
                  include_censored: bool = True) -> pd.DataFrame:
    """Premises occupied at `base_year`-12-31, scored at t0, outcome at
    `outcome_year`-12-31.

    THE BOUNDARY THE TESTS PIN: a premises already VACANT at base year is not
    at risk and cannot be an event — including it would count landlords who
    were already dark as failures of the screen. `attrition_is_event` decides
    what "stopped filing" means, and the two answers are reported side by side
    because the direction of that bias is unknowable from inside the data.
    """
    rows = con.execute(f"""
        WITH yr AS (
          SELECT premises_id, reporting_year,
                 bool_or(vacant_1231)             AS vacant,
                 bool_or(COALESCE(construction_reported, FALSE)) AS constr,
                 any_value(bbl)                   AS bbl,
                 any_value(nta_code)              AS nta_code,
                 any_value(borough)               AS borough,
                 any_value(primary_business_activity) AS activity,
                 avg(ST_X(geom))                  AS lon,
                 avg(ST_Y(geom))                  AS lat
          FROM analysis.storefront
          WHERE borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_CODE)})
            AND geom IS NOT NULL
          GROUP BY 1, 2)
        SELECT b.premises_id, b.lon, b.lat, b.nta_code, b.borough, b.bbl,
               b.activity, (b.constr OR COALESCE(o.constr, FALSE)) AS constr,
               o.vacant AS vacant_out,
               (o.premises_id IS NULL) AS no_outcome_filing
        FROM yr b LEFT JOIN yr o
          ON o.premises_id = b.premises_id AND o.reporting_year = {int(outcome_year)}
        WHERE b.reporting_year = {int(base_year)} AND b.vacant IS NOT DISTINCT FROM FALSE
    """).fetchdf()

    rows["activity_group"] = rows["activity"].map(_activity_group)
    rows["point_id"] = rows["premises_id"]
    ev = rows["vacant_out"].fillna(False).astype(bool)
    if attrition_is_event:
        rows["event"] = (ev | rows["no_outcome_filing"]).astype(int)
    else:
        rows = rows[~rows["no_outcome_filing"]].copy()
        rows["event"] = ev[rows.index].astype(int)

    pts = rows[["point_id", "lon", "lat"]].dropna()
    homes_src = con.execute(f"""
        SELECT lon, lat, units_capped AS weight FROM analysis.address
        WHERE frame = 'lot' AND borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_CODE)})
          AND units_capped > 0 AND lon IS NOT NULL""").fetchdf()
    homes = (count_within(con, pts, homes_src, radius_m=radius_m, by="")
             .rename(columns={"wsum": "homes_t0"})[["point_id", "homes_t0"]])

    from loci.categories import CATEGORIES
    cats = tuple(CATEGORIES)
    sup = supply_as_of(con, pts, asof=t0, radius_m=radius_m,
                       include_censored=include_censored, categories=cats)
    total = sup.groupby("point_id")["supply"].sum().rename("supply_all_t0").reset_index()
    food = (sup[sup["category"].isin(("restaurant", "cafe_bakery", "bar"))]
            .groupby("point_id")["supply"].sum().rename("supply_food_t0").reset_index())

    char = con.execute(f"""
        SELECT a.lon, a.lat, c.retail_index AS weight
        FROM analysis.address a JOIN analysis.address_character c USING (address_id)
        WHERE a.frame = 'lot' AND a.borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_CODE)})
          AND c.retail_index IS NOT NULL AND a.lon IS NOT NULL""").fetchdf()
    ri = count_within(con, pts, char, radius_m=200.0, by="")
    ri["retail_index"] = ri["wsum"] / ri["n"]
    ri = ri[["point_id", "retail_index"]]

    p = (rows.merge(homes, on="point_id", how="left")
             .merge(total, on="point_id", how="left")
             .merge(food, on="point_id", how="left")
             .merge(ri, on="point_id", how="left"))
    p[["supply_all_t0", "supply_food_t0"]] = p[["supply_all_t0", "supply_food_t0"]].fillna(0.0)
    p = p[(p["homes_t0"].fillna(0) > 0) & p["nta_code"].notna()].copy()

    p["supply_per_1k_t0"] = p["supply_all_t0"] / p["homes_t0"] * 1000.0
    p["score_t0"] = p["supply_per_1k_t0"] / p["supply_per_1k_t0"].median()
    p["log_score"] = np.log1p(p["score_t0"])
    p["log_homes"] = np.log(p["homes_t0"] + 1.0)
    p["retail_index"] = p["retail_index"].fillna(p["retail_index"].median())
    p["construction_reported"] = p["constr"].fillna(False).astype(bool)
    p["block"] = _spatial_blocks(p)
    p["attrition_is_event"] = attrition_is_event
    p["t0"] = t0
    return p.reset_index(drop=True)


def _spatial_blocks(panel: pd.DataFrame, nx: int = GO_DARK_BLOCKS_X,
                    ny: int = GO_DARK_BLOCKS_Y) -> pd.Series:
    """Blocks coarser than NTA, for the coarser-blocking robustness check.

    A quantile tiling of projected NTA CENTROIDS, so whole NTAs always land in
    one block and a fold never splits a neighbourhood. Deterministic and
    dependency-free; the point is only that the folds are coarser than NTAs,
    not that the tiles are administrative units."""
    cen = panel.groupby("nta_code")[["lon", "lat"]].mean()
    x, y = _project(cen["lon"].to_numpy(), cen["lat"].to_numpy())
    bx = pd.qcut(pd.Series(x, index=cen.index), nx, labels=False, duplicates="drop")
    by = pd.qcut(pd.Series(y, index=cen.index), ny, labels=False, duplicates="drop")
    key = (bx.astype(str) + ":" + by.astype(str))
    return panel["nta_code"].map(key)


def _gd_design(panel: pd.DataFrame, cols: list[str], nta_fe: bool) -> np.ndarray:
    X = panel[cols].copy().astype(float)
    if nta_fe:
        d = pd.get_dummies(panel["nta_code"], prefix="nta", drop_first=True)
        # An NTA with no variation in the outcome separates perfectly and the
        # fit will not converge; drop those columns rather than the rows, so
        # the sample stays the sample.
        keep = [c for c in d.columns if d[c].sum() >= 10]
        X = pd.concat([X, d[keep].astype(float)], axis=1)
    X.insert(0, "const", 1.0)
    return X


def _gd_fit(panel: pd.DataFrame, cols: list[str], nta_fe: bool = True):
    import statsmodels.api as sm
    X = _gd_design(panel, cols, nta_fe)
    return sm.Logit(panel["event"].to_numpy(dtype=float), X.to_numpy()).fit(
        disp=0, maxiter=300, cov_type="cluster",
        cov_kwds={"groups": panel["nta_code"].to_numpy(), "use_correction": True}), list(X.columns)


def _gd_cv_auc(panel: pd.DataFrame, cols: list[str], nta_fe: bool = True) -> float:
    """Out-of-sample AUC with whole SPATIAL BLOCKS held out (coarser than NTA)."""
    import statsmodels.api as sm
    idx = panel.reset_index(drop=True)
    preds = np.full(len(idx), np.nan)
    for blk in sorted(idx["block"].dropna().unique()):
        te = (idx["block"] == blk).to_numpy()
        tr = ~te
        if idx.loc[tr, "event"].nunique() < 2 or te.sum() == 0:
            continue
        Xtr = _gd_design(idx[tr], cols, nta_fe)
        Xte = _gd_design(idx[te], cols, nta_fe).reindex(columns=Xtr.columns, fill_value=0.0)
        try:
            m = sm.Logit(idx.loc[tr, "event"].to_numpy(dtype=float),
                         Xtr.to_numpy()).fit(disp=0, maxiter=300)
            preds[te] = m.predict(Xte.to_numpy())
        except Exception:
            continue
    ok = ~np.isnan(preds)
    return _auc(idx.loc[ok, "event"].to_numpy(), preds[ok]) if ok.sum() else float("nan")


def _calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    q = pd.qcut(pd.Series(p), bins, labels=False, duplicates="drop")
    out = []
    for b in sorted(pd.Series(q).dropna().unique()):
        m = (q == b).to_numpy()
        out.append({"decile": int(b) + 1, "n": int(m.sum()),
                    "predicted": float(np.mean(p[m])), "observed": float(np.mean(y[m]))})
    return out


def fit_go_dark(panel: pd.DataFrame, *, nta_fe: bool = True) -> dict:
    """Does a THIN-supply score at t0 predict a storefront going dark by 2024?

    THE SIGN IS THE WHOLE POINT. `log_score` rises with supply per resident, so
    a NEGATIVE coefficient means thin supply predicts going dark — the screen's
    gaps are places the market has already judged, which is D87's attack
    landing on the outcome margin. A POSITIVE coefficient means churn is
    concentrated where retail is thick. Zero means the screen is silent about
    survival, which is its own answer."""
    cols = ["log_score", "log_homes", "retail_index"]
    p = panel.dropna(subset=cols + ["event", "nta_code", "block"]).copy()

    res, names = _gd_fit(p, cols, nta_fe)
    i = names.index("log_score")
    ci = res.conf_int()
    auc_full = _gd_cv_auc(p, cols, nta_fe)
    auc_nos = _gd_cv_auc(p, ["log_homes", "retail_index"], nta_fe)

    import statsmodels.api as sm
    X = _gd_design(p, cols, nta_fe)
    fitted = sm.Logit(p["event"].to_numpy(dtype=float), X.to_numpy()).fit(
        disp=0, maxiter=300).predict(X.to_numpy())

    groups = {}
    tests = 3
    for g, sub in p.groupby("activity_group"):
        if len(sub) < 300 or sub["event"].nunique() < 2:
            groups[g] = {"n": int(len(sub)), "skipped": "n < 300 or no variance"}
            continue
        try:
            r, nm = _gd_fit(sub, cols, nta_fe=False)
            j = nm.index("log_score")
            groups[g] = {
                "n": int(len(sub)), "events": int(sub["event"].sum()),
                "rate": float(sub["event"].mean()),
                "log_score_coef": float(r.params[j]),
                "log_score_ci": [float(r.conf_int()[j][0]), float(r.conf_int()[j][1])],
                "p": float(r.pvalues[j]),
                "survives_bonferroni": bool(r.pvalues[j] < 0.05 / tests)}
        except Exception as exc:
            groups[g] = {"n": int(len(sub)), "skipped": str(exc)[:100]}

    splits = {}
    for label, sub in (("construction_reported", p[p["construction_reported"]]),
                       ("no_construction_reported", p[~p["construction_reported"]])):
        if len(sub) < 300 or sub["event"].nunique() < 2:
            splits[label] = {"n": int(len(sub)), "skipped": "n < 300 or no variance"}
            continue
        r, nm = _gd_fit(sub, cols, nta_fe=False)
        j = nm.index("log_score")
        splits[label] = {"n": int(len(sub)), "events": int(sub["event"].sum()),
                         "rate": float(sub["event"].mean()),
                         "log_score_coef": float(r.params[j]),
                         "log_score_ci": [float(r.conf_int()[j][0]),
                                          float(r.conf_int()[j][1])]}

    coef = float(res.params[i])
    lo, hi = float(ci[i][0]), float(ci[i][1])
    sign = ("NEGATIVE — thin supply at t0 predicts going dark" if hi < 0 else
            "POSITIVE — thick supply at t0 predicts going dark" if lo > 0 else
            "INDISTINGUISHABLE FROM ZERO — the score is silent about going dark")

    return {
        "n": int(len(p)), "events": int(p["event"].sum()),
        "event_rate": float(p["event"].mean()),
        "n_ntas": int(p["nta_code"].nunique()), "n_blocks": int(p["block"].nunique()),
        "attrition_is_event": bool(panel["attrition_is_event"].iloc[0]),
        "nta_fixed_effects": bool(nta_fe),
        "log_score_coef": coef, "log_score_ci": [lo, hi],
        "log_score_p": float(res.pvalues[i]),
        "auc_full": float(auc_full), "auc_no_score": float(auc_nos),
        "auc_lift": float(auc_full - auc_nos),
        "calibration": _calibration(p["event"].to_numpy(dtype=float), fitted),
        "by_activity_group": groups, "by_construction": splits,
        "sign": sign,
    }


def run_go_dark(*, base_year: int = GO_DARK_BASE_YEAR,
                outcome_year: int = GO_DARK_OUTCOME_YEAR,
                radius_m: float = RADIUS_M,
                out: pathlib.Path | str | None = None) -> dict:
    """Both attrition variants, written beside the entry run."""
    out_dir = pathlib.Path(out) if out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)
    payload = {"params": {"base_year": base_year, "outcome_year": outcome_year,
                          "radius_m": radius_m, "distance": "straight-line EPSG:32618",
                          "ran_at": dt.datetime.now().isoformat(timespec="seconds")}}
    for label, attr in (("strict", False), ("attrition_as_event", True)):
        panel = go_dark_panel(con, base_year=base_year, outcome_year=outcome_year,
                              radius_m=radius_m, attrition_is_event=attr)
        panel.to_parquet(out_dir / f"go_dark_{label}.parquet", index=False)
        payload[label] = fit_go_dark(panel)
    (out_dir / "go_dark.json").write_text(json.dumps(payload, indent=2, default=str))
    con.close()
    return payload


def load_go_dark(out: pathlib.Path | str | None = None) -> dict:
    path = (pathlib.Path(out) if out else OUT_DIR) / "go_dark.json"
    if not path.exists():
        raise FileNotFoundError(f"no go-dark run at {path} — "
                                f"run `loci retrodiction go-dark` first")
    return json.loads(path.read_text())


# ===========================================================================
# 9. BIKE ACTIVITY GROWTH (D111, GTM-168) — the pre-registered feature test
# ===========================================================================
# Citi Bike phase 3 asks one question: does the CHANGE in bike activity around
# an address, measured before t0, add anything to the retrodiction model that
# the retrodiction model does not already have?
#
# The honesty guardrail is unchanged and load-bearing (D1, P12). Retail
# openings stay on the LEFT-hand side. Bike growth is a right-hand-side
# co-movement term, never "demand", and a positive coefficient is reported as
# "activity grew where openings later landed", never as "riders cause shops".
#
# Everything below implements the statistician's ratified pre-registration
# verbatim. The numbers in P3, P5, P7 and P8 are module constants, not
# parameters with defaults, because a ship criterion you can pass a flag to is
# not a ship criterion. `--placebo-draws` does not exist on purpose.

PREREGISTRATION = """\
GTM-168 / D111 — ratified ship criterion (statistician, 2026-09-15, BEFORE any fit).

P0  One primary test: pooled 6 categories (category FE), vintage t0 = 2023-01,
    member-only, direct specification, censored-included, NTA-blocked CV.
P1  Baseline is FULL + docks_added_24m, not FULL. Dock siting is endogenous to
    retail. FULL alone is reported only for comparability with D88's 0.8663.
P2  Identical rows, identical folds: one NTA->fold map derived from the shared
    row set and passed to BOTH fits. Report rows lost to balanced_share < 0.5;
    > 20% lost means the claim is about the dock-mature inner core.
P3  Ship iff point delta-AUC >= max(+0.005, placebo p95) AND the two-sided 95%
    cluster-bootstrap CI on delta has lower limit > +0.002.
P4  400 draws, resample CLUSTERS, both AUCs recomputed on the same resampled
    rows from FIXED out-of-fold predictions. NTA- and CD-clustered; the gate
    binds on the CD-clustered (wider) CI.
P5  Placebo unit is the NTA: donate whole NTAs' growth vectors between NTAs
    matched on borough x median-activity tercile, assigned by within-NTA rank.
    200 draws, null computed on delta. Decile-matched address swap is secondary.
P6  Separating check is a DIAGNOSTIC. Primary = growth enters alongside the
    controls. Report auxiliary R2 of growth on the controls; R2 > 0.80 means the
    feature carries little independent variation. A residualised lift LARGER
    than the direct one is a red flag.
P7  2023-01 primary, 2025-01 confirmatory. Ship requires 2023-01 clears every
    gate AND 2025-01's delta is positive with a bootstrap CI on
    (delta2023 - delta2025) containing zero, or 2025-01 independently clears the
    floor. Truncate the 2025-01 outcome window where ascertainment falls off.
P8  Fold-seed stability over 20 seeds: median delta >= floor and delta > 0 in
    >= 18/20.
P9  Pre-trend (2025-01 only): lagged growth (windows ending 2023-12) run through
    the same paired test. If it predicts about as well, the feature is a
    persistent location marker and fails.
P10 Family: 6 categories x 2 vintages x {direct, residualised} x {member,
    all-rider} x {strict-dated y/n}. Only P0 is confirmatory; every secondary
    carries BH q = 0.10 and prints "not a finding" without a surviving p.
P11 Spatial diagnostics before: distinct reachable-dock-sets (the effective n),
    Moran's I of the feature (k = 8, 199 perms), across-NTA Moran's I. After:
    Moran's I on OOS residuals baseline vs +growth; no reduction means the
    feature adds smooth noise, not information.
P12 Co-movement, never demand. Retail stays the left-hand side. Failure ships
    as a finding.
"""


# --------------------------------------------------------------------------
# 9a. small shared utilities
# --------------------------------------------------------------------------
def _parse_month(s: str) -> dt.date:
    """'2025-01' or '2025-01-01' -> the first of that month."""
    s = str(s).strip()
    return dt.date(int(s[:4]), int(s[5:7]), 1)


def _month_end(d: dt.date) -> dt.date:
    return (dt.date(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1)
            - dt.timedelta(days=1))


def _months_before(d: dt.date, n: int) -> dt.date:
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, 1)


def cd_code(nta: str | None) -> str | None:
    """Community district from an NTA2020 code.

    NTA2020 codes are borough-letters + two-digit community district + two-digit
    NTA ('BK0101' = Brooklyn CD 1, NTA 01). MN+BK carry 33 of them including the
    park/airport pseudo-districts, which is the '36 community districts' the
    pre-registration's P4 names as the coarser clustering. There is no community
    district column on `analysis.address`; this derivation IS the CD, and it is
    deterministic rather than a spatial join."""
    if nta is None or (isinstance(nta, float) and np.isnan(nta)):
        return None
    s = str(nta)
    return s[:4] if len(s) >= 4 else s


def _supply_hash(con) -> str | None:
    """The live supply-set hash, recorded for provenance (spec §Retrodiction
    re-run). A run whose hash differs from the one in CHECKPOINT is a run
    against a different supply set and its numbers are not comparable."""
    try:
        row = con.execute("SELECT supply_hash FROM analysis.address "
                          "WHERE supply_hash IS NOT NULL LIMIT 1").fetchone()
        return str(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _table_exists(con, schema: str, table: str) -> bool:
    try:
        return bool(con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = ? AND table_name = ?", [schema, table]).fetchone()[0])
    except Exception:
        return False


def _columns(con, schema: str, table: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
        [schema, table]).fetchall()]


# --------------------------------------------------------------------------
# 9b. P7 — ascertainment, and where the outcome window has to stop
# --------------------------------------------------------------------------
def ascertainment_by_month(con, start: dt.date, end: dt.date,
                           frac: float = ASCERTAINMENT_FLOOR_FRAC) -> dict:
    """Dated openings per month across the outcome window, and the month the
    window has to be truncated at.

    P7's reason, stated before the count is looked at: the ledger's dates are
    licences and first inspections at a 221-259 day lead (D80), so the last
    months of any window are not months with few openings — they are months
    whose openings have not been filed yet. Extending a window into that region
    adds rows that are zero BY CONSTRUCTION and biases every AUC toward
    whatever predicts "nothing happened here".

    The rule is fixed in `ASCERTAINMENT_FLOOR_FRAC` and applied without looking:
    keep the longest PREFIX of the window whose every month stays at or above
    60% of the window's own first-12-month median."""
    try:
        counts = con.execute(f"""
            SELECT date_trunc('month', first_seen_src_date) AS month, count(*) AS n
            FROM analysis.poi_presence
            WHERE first_seen_kind IN ('source_date', 'gov_filing')
              AND first_seen_src_date BETWEEN ? AND ?
              AND borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_FULL)})
            GROUP BY 1 ORDER BY 1""", [start, end]).fetchdf()
    except Exception as exc:
        return {"by_month": [], "truncate_at": None, "rule": f"unavailable: {exc}"}
    if counts.empty:
        return {"by_month": [], "truncate_at": None, "rule": "no dated openings"}

    counts["month"] = pd.to_datetime(counts["month"]).dt.strftime("%Y-%m")
    n = counts["n"].to_numpy(dtype=float)
    ref = float(np.median(n[:min(12, len(n))]))
    floor = frac * ref
    keep = len(n)
    for i, v in enumerate(n):
        if v < floor:
            keep = i
            break
    rule = (f"longest prefix with monthly dated openings >= {frac:.0%} of the "
            f"first-12-month median ({ref:.0f} -> floor {floor:.0f})")
    return {"by_month": counts.to_dict("records"),
            "first_12m_median": ref, "floor": floor,
            "truncate_at": counts["month"].iloc[keep - 1] if keep else None,
            "months_dropped": int(len(n) - keep), "rule": rule}


# --------------------------------------------------------------------------
# 9c. the join, and P2's attrition report
# --------------------------------------------------------------------------
#: The columns `analysis.address_bike_growth` owes this module (spec §Table,
#: built by track G in `src/loci/model/address_bike_growth.py`). Kept here as a
#: contract so this module fails loudly on a schema drift rather than silently
#: filling a feature with NULLs.
BIKE_GROWTH_COLUMNS = ("address_id", "borough", "asof_month", "activity_12m",
                       "activity_prior_12m", "bike_growth_12m",
                       "bike_growth_12m_rel", "n_docks_balanced",
                       "balanced_share", "docks_added_24m", "member_only",
                       "window_first", "window_last", "run_at")

_BIKE_JOIN_COLUMNS = ("bike_growth_12m_rel", "bike_growth_12m", "balanced_share",
                      "docks_added_24m", "n_docks_balanced", "activity_12m")


def attach_bike_growth(con, panel: pd.DataFrame, *, asof: dt.date,
                       member_only: bool = True, suffix: str = "",
                       required: bool = True) -> pd.DataFrame:
    """LEFT-join `analysis.address_bike_growth` at (address_id, asof_month=asof,
    member_only) onto the entry panel.

    LEFT, never INNER: the growth table NULLs the feature where the balanced
    dock set is thin, and P2 needs those rows present to count what was lost and
    to compare the retained addresses with the lost ones. `fit_growth_test`
    drops them once, for both models at the same time.

    `suffix='_lag'` attaches only `bike_growth_12m_rel` under a suffixed name —
    P9's pre-trend vintage — and is never required to exist."""
    schema, table = BIKE_GROWTH_TABLE
    if not _table_exists(con, schema, table):
        msg = (f"{schema}.{table} does not exist. It is built by "
               f"`loci citibike growth-measures --asof {asof:%Y-%m}` "
               f"(GTM-168 track G, migration 038). Columns this module reads: "
               f"{', '.join(_BIKE_JOIN_COLUMNS)}.")
        if required:
            raise RuntimeError(msg)
        for c in _BIKE_JOIN_COLUMNS:
            if suffix and c != "bike_growth_12m_rel":
                continue
            panel[c + suffix] = np.nan
        return panel

    have = set(_columns(con, schema, table))
    missing = [c for c in BIKE_GROWTH_COLUMNS if c not in have]
    if missing:
        raise RuntimeError(
            f"{schema}.{table} is missing {missing}; the contract in "
            f"BIKE_GROWTH_COLUMNS (spec §Table) has drifted.")

    want = [c for c in _BIKE_JOIN_COLUMNS
            if not suffix or c == "bike_growth_12m_rel"]
    g = con.execute(f"""
        SELECT address_id AS point_id, {", ".join(want)}
        FROM {schema}.{table}
        WHERE asof_month = DATE '{asof.isoformat()}'
          AND member_only = {"TRUE" if member_only else "FALSE"}
    """).fetchdf()
    dupes = int(len(g) - g["point_id"].nunique())
    if dupes:
        raise RuntimeError(
            f"{schema}.{table} has {dupes} duplicate address rows at "
            f"asof_month {asof} member_only={member_only}. The grain is "
            f"address x asof_month x member_only; a duplicate would multiply "
            f"panel rows and inflate every n in this module.")
    if suffix:
        g = g.rename(columns={c: c + suffix for c in want})
    return panel.merge(g, on="point_id", how="left")


def bike_attrition(panel: pd.DataFrame, feature: str = BIKE_FEATURE) -> dict:
    """P2 — what the balanced-dock NULLing costs, and whether the survivors are
    a different city from the rows it removed.

    Two numbers decide how the result may be described. If more than 20% of
    rows are lost, the honest claim is "evaluated on the dock-mature inner
    core", not "MN+BK". If the retained rows differ materially in `retail_index`
    or `log_homes`, the comparison is against a richer, denser subsample and the
    lift is not transportable."""
    n = int(len(panel))
    have = panel[feature].notna()
    lost = ~have
    out = {
        "feature": feature,
        "n_rows": n,
        "n_rows_with_feature": int(have.sum()),
        "n_rows_lost": int(lost.sum()),
        "share_lost": float(lost.mean()) if n else float("nan"),
        "n_addresses": int(panel["point_id"].nunique()),
        "n_addresses_with_feature": int(panel.loc[have, "point_id"].nunique()),
    }
    if "balanced_share" in panel:
        bs = panel["balanced_share"]
        out["n_lost_below_balanced_share_floor"] = int((bs < 0.5).sum())
        out["n_lost_no_growth_row"] = int(bs.isna().sum())
    cmp_ = {}
    for col in ("retail_index", "log_homes"):
        if col not in panel:
            continue
        a = panel.loc[have, col].astype(float)
        b = panel.loc[lost, col].astype(float)
        sd = float(np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2.0)) if len(b) > 1 else float("nan")
        cmp_[col] = {
            "retained_mean": float(a.mean()) if len(a) else float("nan"),
            "lost_mean": float(b.mean()) if len(b) else float("nan"),
            "retained_median": float(a.median()) if len(a) else float("nan"),
            "lost_median": float(b.median()) if len(b) else float("nan"),
            "std_diff": (float((a.mean() - b.mean()) / sd)
                         if sd and np.isfinite(sd) and sd > 0 else float("nan")),
        }
    out["retained_vs_lost"] = cmp_
    out["exceeds_20pct"] = bool(out["share_lost"] > 0.20)
    out["claim"] = (
        "evaluated on the DOCK-MATURE INNER CORE, not MN+BK — more than 20% of "
        "rows have no balanced 24-month dock set"
        if out["exceeds_20pct"] else
        "the balanced-dock requirement removes less than 20% of rows; the claim "
        "is about MN+BK as sampled")
    return out


# --------------------------------------------------------------------------
# 9d. folds, out-of-fold predictions, AUC deltas
# --------------------------------------------------------------------------
def nta_fold_map(panel: pd.DataFrame, n_folds: int = N_FOLDS,
                 seed: int = RNG_SEED) -> dict:
    """P2 — the ONE NTA -> fold assignment both fits are given.

    Sorted before shuffling on purpose: `unique()` returns NTAs in row order, so
    two frames holding the same NTAs in a different order get different folds
    from the same seed. Sorting makes the map a function of the NTA SET alone."""
    ntas = np.array(sorted(panel["nta_code"].fillna("NA").unique()), dtype=object)
    rng = np.random.default_rng(seed)
    rng.shuffle(ntas)
    return {n: int(f) for f, part in enumerate(np.array_split(ntas, n_folds))
            for n in part}


def _oof_frame(panel: pd.DataFrame, fold_map: dict,
               preds: dict[str, np.ndarray]) -> pd.DataFrame:
    """One frame holding the outcome, the cluster keys and EVERY model's
    out-of-fold prediction for the SAME rows.

    P4's requirement in a data structure: the bootstrap must recompute both
    AUCs on the same resampled rows from FIXED predictions, which is only
    meaningful if the predictions were produced on one row set with one fold
    map. Anything that wants a delta reads it from here."""
    idx = panel.reset_index(drop=True)
    out = pd.DataFrame({
        "point_id": idx["point_id"].to_numpy(),
        "category": idx["category"].to_numpy(),
        "y": idx["y"].to_numpy(dtype=float),
        "nta_code": idx["nta_code"].fillna("NA").to_numpy(),
        "fold": idx["nta_code"].fillna("NA").map(fold_map).to_numpy(),
    })
    out["cd_code"] = [cd_code(v) for v in out["nta_code"]]
    for name, p in preds.items():
        out[name] = np.asarray(p, dtype=float)
    return out


def _delta_draws(oof: pd.DataFrame, treat: str, base: str, cluster: str,
                 draws: int = BOOTSTRAP_DRAWS, seed: int = RNG_SEED) -> np.ndarray:
    """Cluster bootstrap of the AUC DELTA from fixed out-of-fold predictions."""
    sub = oof.dropna(subset=[treat, base, "y"])
    groups = sub.groupby(cluster).indices
    keys = list(groups)
    if len(keys) < 2:
        return np.asarray([], dtype=float)
    y = sub["y"].to_numpy(dtype=float)
    pt, pb = sub[treat].to_numpy(dtype=float), sub[base].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(draws):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        rows = np.concatenate([groups[keys[k]] for k in pick])
        a, b = _auc(y[rows], pt[rows]), _auc(y[rows], pb[rows])
        if not (np.isnan(a) or np.isnan(b)):
            vals.append(a - b)
    return np.asarray(vals, dtype=float)


def _boot_p(arr: np.ndarray) -> float:
    """Two-sided bootstrap-percentile p on a delta. P3 forbids a one-sided
    licence ("the one-sided licence is where p-hacking lives")."""
    arr = np.asarray(arr, dtype=float)
    if not len(arr):
        return float("nan")
    p = 2.0 * min(float((arr <= 0).mean()), float((arr >= 0).mean()))
    return float(min(1.0, max(1.0 / (len(arr) + 1), p)))


def summarise_draws(arr: np.ndarray, cluster: str = "") -> dict:
    arr = np.asarray(arr, dtype=float)
    if not len(arr):
        return {"draws": 0, "mean": float("nan"), "sd": float("nan"),
                "ci": [float("nan"), float("nan")], "p_two_sided": float("nan"),
                "cluster": cluster}
    return {"draws": int(len(arr)), "mean": float(arr.mean()),
            "sd": float(arr.std(ddof=1)) if len(arr) > 1 else float("nan"),
            "ci": [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))],
            "p_two_sided": _boot_p(arr), "cluster": cluster}


def bootstrap_delta(oof: pd.DataFrame, *, treat: str = "p_treat",
                    base: str = "p_base", cluster: str = "nta_code",
                    draws: int = BOOTSTRAP_DRAWS, seed: int = RNG_SEED) -> dict:
    """P4 — 400 draws, clusters resampled, CI on the DELTA."""
    return summarise_draws(_delta_draws(oof, treat, base, cluster, draws, seed),
                           cluster)


def paired_vintage_delta_ci(oof_a: pd.DataFrame, oof_b: pd.DataFrame, *,
                            cluster: str = "cd_code",
                            draws: int = BOOTSTRAP_DRAWS,
                            seed: int = RNG_SEED) -> dict:
    """P7's CI on (delta_primary - delta_confirmatory), on JOINTLY resampled
    clusters.

    Differencing two independently bootstrapped intervals would be wrong here in
    the permissive direction: the two vintages are the same city, their cluster
    draws are positively correlated, and treating them as independent inflates
    the variance of the difference — which makes "the CI contains zero" easier
    to satisfy, i.e. makes shipping easier. Resampling one list of clusters and
    evaluating BOTH vintages on it removes that."""
    sa = oof_a.dropna(subset=["p_treat", "p_base", "y"])
    sb = oof_b.dropna(subset=["p_treat", "p_base", "y"])
    ga, gb = sa.groupby(cluster).indices, sb.groupby(cluster).indices
    keys = sorted(set(ga) | set(gb))
    if len(keys) < 2:
        return {"draws": 0, "ci": [float("nan"), float("nan")],
                "contains_zero": False, "note": "too few clusters"}
    ya, pta, pba = (sa["y"].to_numpy(float), sa["p_treat"].to_numpy(float),
                    sa["p_base"].to_numpy(float))
    yb, ptb, pbb = (sb["y"].to_numpy(float), sb["p_treat"].to_numpy(float),
                    sb["p_base"].to_numpy(float))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(draws):
        pick = [keys[k] for k in rng.choice(len(keys), size=len(keys), replace=True)]
        ra = np.concatenate([ga[k] for k in pick if k in ga]) if any(k in ga for k in pick) else None
        rb = np.concatenate([gb[k] for k in pick if k in gb]) if any(k in gb for k in pick) else None
        if ra is None or rb is None:
            continue
        da = _auc(ya[ra], pta[ra]) - _auc(ya[ra], pba[ra])
        db = _auc(yb[rb], ptb[rb]) - _auc(yb[rb], pbb[rb])
        if not (np.isnan(da) or np.isnan(db)):
            vals.append(da - db)
    s = summarise_draws(np.asarray(vals), cluster)
    s["contains_zero"] = bool(s["draws"] and s["ci"][0] <= 0.0 <= s["ci"][1])
    return s


# --------------------------------------------------------------------------
# 9e. P5 — the placebo, and it runs FIRST
# --------------------------------------------------------------------------
def _address_frame(panel: pd.DataFrame, feature: str) -> pd.DataFrame:
    """One row per address: the feature is an ADDRESS measurement repeated
    across the six category rows, so every spatial diagnostic and every placebo
    has to operate on addresses or it will count each address six times."""
    cols = [c for c in ("point_id", "nta_code", "borough", "lon", "lat",
                        "activity_12m", "n_docks_balanced", feature)
            if c in panel]
    return (panel[cols].drop_duplicates(subset=["point_id"])
            .reset_index(drop=True))


def _activity_column(addr: pd.DataFrame) -> str | None:
    for c in ("activity_12m", "n_docks_balanced"):
        if c in addr and addr[c].notna().any():
            return c
    return None


def nta_strata(addr: pd.DataFrame) -> dict:
    """P5's donor pool: borough x tercile of the NTA's MEDIAN activity.

    Matching on level is the whole point. A placebo that donated a quiet
    outer-Brooklyn NTA's growth vector to Midtown would destroy the level as
    well as the location, and clearing it would prove only that level matters —
    which nobody disputes."""
    act = _activity_column(addr)
    agg = {"borough": ("borough", "first")}
    if act:
        agg["act"] = (act, "median")
    med = addr.groupby("nta_code").agg(**agg)
    if act is None:
        med["act"] = 0.0
    def _terc(s: pd.Series) -> pd.Series:
        try:
            return pd.qcut(s.rank(method="first"), 3, labels=False, duplicates="drop")
        except (ValueError, IndexError):
            return pd.Series(0, index=s.index)
    med["tercile"] = med.groupby("borough")["act"].transform(_terc).fillna(0).astype(int)
    return (med["borough"].astype(str) + ":t" + med["tercile"].astype(str)).to_dict()


def nta_block_donation(values: np.ndarray, ntas: np.ndarray, strata: dict,
                       rng: np.random.Generator,
                       max_tries: int = 25) -> tuple[np.ndarray, int]:
    """Donate whole NTAs' growth VECTORS between NTAs in the same stratum,
    assigned by within-NTA rank.

    What is preserved: every NTA's vector of values survives intact (it moves to
    another NTA), the within-NTA ordering of addresses survives, and when donor
    and recipient are the same size the multiset of values over the whole panel
    is preserved EXACTLY. What is destroyed: which NTA a value belongs to. That
    is the null the pre-registration wants — spatially structured noise with the
    right marginal — and it is far harder to beat than an i.i.d. shuffle."""
    values = np.asarray(values, dtype=float)
    out = values.copy()
    fixed = 0
    by_stratum: dict[str, list] = {}
    for nta in pd.unique(ntas):
        by_stratum.setdefault(strata.get(nta, "NA"), []).append(nta)
    for members in by_stratum.values():
        m = sorted(members, key=str)
        if len(m) < 2:
            fixed += len(m)
            continue
        perm = list(m)
        for _ in range(max_tries):
            rng.shuffle(perm)
            if all(a != b for a, b in zip(m, perm)):
                break
        for recip, donor in zip(m, perm):
            if recip == donor:
                fixed += 1
            ri = np.flatnonzero(ntas == recip)
            di = np.flatnonzero(ntas == donor)
            if not len(ri) or not len(di):
                continue
            donor_sorted = np.sort(values[di])
            rank = np.argsort(np.argsort(values[ri], kind="mergesort"), kind="mergesort")
            if len(di) == len(ri):
                out[ri] = donor_sorted[rank]
            else:
                q = rank / max(len(ri) - 1, 1)
                out[ri] = donor_sorted[np.rint(q * (len(di) - 1)).astype(int)]
    return out, fixed


def decile_swap(values: np.ndarray, borough: np.ndarray, activity: np.ndarray,
                rng: np.random.Generator) -> np.ndarray:
    """P5's SECONDARY placebo: each address receives another address's growth
    from the same borough AND the same activity decile.

    Preserves the marginal and the level and destroys location — but at the
    address grain, so it also destroys the smoothness that real spatial features
    have. It is reported, never the gate: an i.i.d.-within-stratum null is too
    easy for any spatially smooth feature to beat."""
    out = np.asarray(values, dtype=float).copy()
    df = pd.DataFrame({"b": borough, "a": np.asarray(activity, dtype=float)})
    try:
        dec = df.groupby("b")["a"].transform(
            lambda s: pd.qcut(s.rank(method="first"), 10, labels=False, duplicates="drop"))
    except (ValueError, IndexError):
        dec = pd.Series(0, index=df.index)
    key = df["b"].astype(str) + ":" + dec.fillna(-1).astype(int).astype(str)
    for _, idx in key.groupby(key).groups.items():
        pos = np.asarray(idx, dtype=int)
        if len(pos) > 1:
            out[pos] = out[rng.permutation(pos)]
    return out


def placebo_delta(panel: pd.DataFrame, base_cols: list[str], feature: str,
                  fold_map: dict, auc_base: float, *,
                  draws: int = NTA_PLACEBO_DRAWS, seed: int = RNG_SEED,
                  mode: str = "nta_block") -> dict:
    """The null distribution of the DELTA, not of the AUC level (P5).

    The baseline AUC does not move under the placebo — the placebo only touches
    the feature column — so it is computed once and subtracted, and each draw
    costs one refit of the treatment model rather than two."""
    addr = _address_frame(panel, feature)
    ntas = addr["nta_code"].fillna("NA").to_numpy(dtype=object)
    vals = addr[feature].to_numpy(dtype=float)
    strata = nta_strata(addr) if mode == "nta_block" else {}
    act_col = _activity_column(addr)
    act = (addr[act_col].to_numpy(dtype=float) if act_col
           else np.zeros(len(addr), dtype=float))
    cols = list(base_cols) + [feature]
    deltas, fixed_total = [], 0
    for d in range(draws):
        rng = np.random.default_rng(seed + 1000 + d)
        if mode == "nta_block":
            swapped, fixed = nta_block_donation(vals, ntas, strata, rng)
            fixed_total += fixed
        else:
            swapped = decile_swap(vals, addr["borough"].to_numpy(dtype=object), act, rng)
            fixed = 0
        mapping = dict(zip(addr["point_id"].to_numpy(), swapped))
        p = panel.copy()
        p[feature] = p["point_id"].map(mapping).astype(float)
        a, _ = blocked_cv_auc(p, cols, fold_map=fold_map)
        if not np.isnan(a):
            deltas.append(a - auc_base)
    arr = np.asarray(deltas, dtype=float)
    return {"mode": mode, "draws": int(len(arr)),
            "mean": float(arr.mean()) if len(arr) else float("nan"),
            "sd": float(arr.std(ddof=1)) if len(arr) > 1 else float("nan"),
            "p95": float(np.percentile(arr, 95)) if len(arr) else float("nan"),
            "max": float(arr.max()) if len(arr) else float("nan"),
            "fixed_point_donations": int(fixed_total),
            "ran_at": dt.datetime.now().isoformat(timespec="seconds")}


# --------------------------------------------------------------------------
# 9f. P11 — spatial diagnostics
# --------------------------------------------------------------------------
def _knn_index(xy: np.ndarray, k: int) -> np.ndarray | None:
    from scipy.spatial import cKDTree
    n = len(xy)
    kk = min(k, n - 1)
    if kk < 1:
        return None
    _, idx = cKDTree(np.asarray(xy, dtype=float)).query(np.asarray(xy, dtype=float),
                                                        k=kk + 1)
    idx = np.atleast_2d(idx)
    return idx[:, 1:]


def morans_i_knn(values, xy, *, k: int = MORAN_K,
                 permutations: int = MORAN_PERMUTATIONS, seed: int = 0) -> dict:
    """Moran's I on a row-standardised k-nearest-neighbour graph, with a
    permutation p-value.

    kNN rather than the Bartlett kernel `model/density_elasticity.py` uses: that
    one materialises an n x n matrix, and n here is 12,000 addresses (1.2 GB).
    With W row-standardised, S0 = n and I collapses to the correlation between
    z and the neighbour-mean of z, which is four lines and exact."""
    v = np.asarray(values, dtype=float)
    xy = np.asarray(xy, dtype=float)
    ok = np.isfinite(v) & np.isfinite(xy).all(axis=1)
    v, xy = v[ok], xy[ok]
    n = len(v)
    if n < k + 2:
        return {"i": None, "p_perm": None, "n": int(n), "note": "too few points"}
    nb = _knn_index(xy, k)
    if nb is None:
        return {"i": None, "p_perm": None, "n": int(n), "note": "no neighbours"}
    z = v - v.mean()
    if float(z @ z) == 0.0:
        return {"i": 0.0, "p_perm": 1.0, "n": int(n), "note": "constant"}

    def stat(zz: np.ndarray) -> float:
        return float((zz * zz[nb].mean(axis=1)).sum() / (zz @ zz))

    obs = stat(z)
    rng = np.random.default_rng(seed)
    null = np.asarray([stat(rng.permutation(z)) for _ in range(permutations)])
    return {"i": obs, "n": int(n), "k": int(k), "permutations": int(permutations),
            "p_perm": float((1 + int((np.abs(null) >= abs(obs)).sum()))
                            / (permutations + 1))}


def effective_dock_sets(con, panel: pd.DataFrame,
                        feature: str = BIKE_FEATURE) -> dict:
    """P11(a) — the feature's EFFECTIVE n: how many DISTINCT reachable dock sets
    the panel's addresses have.

    12,000 addresses do not carry 12,000 independent readings of bike growth.
    Two addresses on the same block reach the same docks and therefore hold the
    same number by construction; the number of distinct dock sets is the real
    sample size behind every interval in this section."""
    addr = _address_frame(panel, feature)
    ids = addr.loc[addr[feature].notna(), "point_id"].unique()
    if con is not None and _table_exists(con, "analysis", "address_bike_station"):
        _rd_ids_df = pd.DataFrame({"address_id": ids})                  # noqa: F841
        con.execute("CREATE OR REPLACE TEMP TABLE _rd_ids AS "
                    "SELECT * FROM _rd_ids_df")
        n_addr, n_sets = con.execute("""
            SELECT count(*), count(DISTINCT dockset) FROM (
              SELECT s.address_id,
                     string_agg(s.station_id, ',' ORDER BY s.station_id) AS dockset
              FROM analysis.address_bike_station s
              JOIN _rd_ids i ON i.address_id = s.address_id
              GROUP BY 1)""").fetchone()
        return {"method": "analysis.address_bike_station",
                "n_addresses_with_docks": int(n_addr),
                "n_distinct_dock_sets": int(n_sets),
                "n_panel_addresses": int(len(ids)),
                "ratio": float(n_sets) / max(int(len(ids)), 1)}
    stand_in = int(addr.loc[addr[feature].notna(), "n_docks_balanced"].nunique()) \
        if "n_docks_balanced" in addr else 0
    return {"method": "n_docks_balanced STAND-IN",
            "n_distinct_dock_sets": stand_in,
            "n_panel_addresses": int(len(ids)),
            "ratio": float(stand_in) / max(int(len(ids)), 1),
            "note": ("analysis.address_bike_station was not available, so this "
                     "counts DISTINCT VALUES of n_docks_balanced, not distinct "
                     "dock SETS. It is an upper bound on nothing and a lower "
                     "bound on the true count; read it as a placeholder and "
                     "re-run the diagnostic against the dock table.")}


def spatial_pre_diagnostics(con, panel: pd.DataFrame,
                            feature: str = BIKE_FEATURE,
                            seed: int = RNG_SEED) -> dict:
    """P11 before the fit: effective n, Moran's I of the feature, across-NTA
    Moran's I. Read together they say whether a CD-blocked design should be
    primary ("if across-NTA Moran's I of the feature is material, CD blocking
    becomes primary")."""
    addr = _address_frame(panel, feature).dropna(subset=[feature])
    xy = np.column_stack(_project(addr["lon"].to_numpy(), addr["lat"].to_numpy())) \
        if {"lon", "lat"} <= set(addr) else np.zeros((len(addr), 2))
    own = morans_i_knn(addr[feature].to_numpy(), xy, seed=seed)

    nta = addr.groupby("nta_code").agg(
        v=(feature, "mean"), lon=("lon", "mean"), lat=("lat", "mean")).dropna()
    nxy = np.column_stack(_project(nta["lon"].to_numpy(), nta["lat"].to_numpy())) \
        if len(nta) else np.zeros((0, 2))
    across = morans_i_knn(nta["v"].to_numpy(), nxy,
                          k=min(MORAN_K, max(len(nta) - 2, 1)), seed=seed)
    material = bool(across.get("i") is not None and across["i"] >= 0.20
                    and (across.get("p_perm") or 1.0) < 0.05)
    return {"effective_n": effective_dock_sets(con, panel, feature),
            "morans_i_feature": own,
            "morans_i_across_nta": across,
            "across_nta_material": material,
            "blocking_note": (
                "across-NTA Moran's I is material -> the pre-registration makes "
                "CD blocking PRIMARY, not just the wider CI"
                if material else
                "across-NTA Moran's I is not material; NTA blocking stays "
                "primary and the CD-clustered CI stays the binding interval")}


def residual_morans_i(panel: pd.DataFrame, oof: pd.DataFrame, *,
                      pred_cols=("p_base", "p_treat"), seed: int = RNG_SEED) -> dict:
    """P11 after the fit: does adding growth REDUCE out-of-sample residual
    spatial autocorrelation?

    D88's baseline is 0.64-0.77 per category. A feature that lifts the AUC
    without touching residual autocorrelation is adding a smooth surface that
    happens to correlate with the outcome — decoration, not information."""
    xy_src = (panel[["point_id", "lon", "lat"]].drop_duplicates("point_id")
              if {"lon", "lat"} <= set(panel) else None)
    if xy_src is None:
        return {"note": "panel carries no lon/lat; residual Moran's I skipped"}
    m = oof.merge(xy_src, on="point_id", how="left")
    out: dict = {"by_category": {}}
    for cat, g in m.groupby("category"):
        g = g.dropna(subset=["lon", "lat"] + list(pred_cols))
        if len(g) < MORAN_K + 2:
            continue
        xy = np.column_stack(_project(g["lon"].to_numpy(), g["lat"].to_numpy()))
        row = {}
        for c in pred_cols:
            row[c] = morans_i_knn(g["y"].to_numpy() - g[c].to_numpy(), xy, seed=seed)
        out["by_category"][str(cat)] = row
    def _mean(c):
        vals = [v[c]["i"] for v in out["by_category"].values() if v[c]["i"] is not None]
        return float(np.mean(vals)) if vals else float("nan")
    out["mean_base"] = _mean(pred_cols[0])
    out["mean_treat"] = _mean(pred_cols[1])
    out["reduction"] = float(out["mean_base"] - out["mean_treat"])
    out["reduces_residual_autocorrelation"] = bool(
        np.isfinite(out["reduction"]) and out["reduction"] > 0)
    out["verdict"] = ("growth reduces residual spatial autocorrelation"
                      if out["reduces_residual_autocorrelation"] else
                      "growth does NOT reduce residual spatial autocorrelation — "
                      "it is adding smooth noise, not information (P11)")
    return out


# --------------------------------------------------------------------------
# 9g. P6 — the separating check, as a diagnostic
# --------------------------------------------------------------------------
AUX_CONTROLS = ("retail_index", "log_homes", "log_transit", "log_supply_own",
                "log_supply_other", "docks_added_24m")


def auxiliary_r2(panel: pd.DataFrame, feature: str = BIKE_FEATURE,
                 controls: tuple[str, ...] = AUX_CONTROLS) -> tuple[dict, np.ndarray]:
    """Regress the feature on the controls and report R^2 — and hand back the
    residual for the robustness column.

    P6 is explicit that this is NOT the specification. The outcome model is
    `sm.Logit`, Frisch-Waugh does not apply to it, and partialling the feature
    out before a non-linear fit answers a different question. The R^2 is here to
    say how much INDEPENDENT variation the feature has; above 0.80 the honest
    sentence is "this feature is mostly the controls in a bike costume"."""
    cols = [c for c in controls if c in panel and panel[c].notna().any()
            and panel[c].nunique(dropna=True) > 1]
    d = panel[[feature] + cols].astype(float)
    d = d.dropna()
    if len(d) < len(cols) + 2 or not cols:
        resid = np.full(len(panel), np.nan)
        return ({"r2": float("nan"), "n": int(len(d)), "controls": cols,
                 "note": "not enough variation to fit the auxiliary regression"},
                resid)
    X = np.column_stack([np.ones(len(d))] + [d[c].to_numpy() for c in cols])
    yv = d[feature].to_numpy()
    beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
    fit = X @ beta
    ss_res = float(((yv - fit) ** 2).sum())
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    resid = pd.Series(yv - fit, index=d.index).reindex(panel.index).to_numpy()
    info = {"r2": float(r2), "n": int(len(d)), "controls": cols,
            "coefficients": {c: float(b) for c, b in zip(["const"] + cols, beta)},
            "carries_little_independent_variation": bool(
                np.isfinite(r2) and r2 > AUX_R2_CEILING),
            "ceiling": AUX_R2_CEILING}
    return info, resid


def growth_by_retail_quintile(panel: pd.DataFrame, cols: list[str],
                              feature: str = BIKE_FEATURE) -> dict:
    """The spec's own separating check: the growth coefficient WITHIN
    `retail_index` quintiles.

    "Lift only in the top quintile = a retail-corridor effect D88 already
    ranks." If growth only moves the model on the streets the screen already
    scores highly, the feature is re-reading `retail_index` through a dock."""
    out: dict = {}
    try:
        q = pd.qcut(panel["retail_index"].rank(method="first"), 5, labels=False,
                    duplicates="drop")
    except (ValueError, IndexError):
        return {"note": "retail_index has too few distinct values to quintile"}
    for qi, g in panel.assign(_q=q).groupby("_q"):
        if len(g) < 500 or g["y"].nunique() < 2 or g[feature].nunique() < 5:
            out[f"q{int(qi) + 1}"] = {"n": int(len(g)), "skipped": "n < 500 or no variance"}
            continue
        try:
            r, nm = _fit_logit(g, cols)
            i = nm.index(feature)
            out[f"q{int(qi) + 1}"] = {
                "n": int(len(g)),
                "coef": float(r.params[i]),
                "ci": [float(r.conf_int()[i][0]), float(r.conf_int()[i][1])],
                "p": float(r.pvalues[i])}
        except Exception as exc:
            out[f"q{int(qi) + 1}"] = {"n": int(len(g)), "skipped": str(exc)[:100]}
    sig = [k for k, v in out.items() if "ci" in v and v["ci"][0] > 0]
    out["top_quintile_only"] = bool(sig == ["q5"])
    return out


# --------------------------------------------------------------------------
# 9h. P8 — fold-seed stability, P10 — Benjamini-Hochberg
# --------------------------------------------------------------------------
def fold_seed_stability(panel: pd.DataFrame, base_cols: list[str],
                        treat_cols: list[str], *, seeds: int = FOLD_SEEDS,
                        n_folds: int = N_FOLDS, seed: int = RNG_SEED,
                        floor: float = DELTA_FLOOR) -> dict:
    """P8 — re-run the paired comparison over `seeds` fold assignments.

    P4's bootstrap captures EVALUATION-sample variability only: the folds are
    fixed inside it. Re-drawing the folds captures the estimation variability
    that a single lucky partition of 103 NTAs can manufacture."""
    deltas = []
    for s in range(seeds):
        fm = nta_fold_map(panel, n_folds, seed + 100 * (s + 1))
        ab, _ = blocked_cv_auc(panel, base_cols, fold_map=fm)
        at, _ = blocked_cv_auc(panel, treat_cols, fold_map=fm)
        if not (np.isnan(ab) or np.isnan(at)):
            deltas.append(at - ab)
    arr = np.asarray(deltas, dtype=float)
    n_pos = int((arr > 0).sum())
    return {"seeds": int(len(arr)),
            "median": float(np.median(arr)) if len(arr) else float("nan"),
            "sd": float(arr.std(ddof=1)) if len(arr) > 1 else float("nan"),
            "min": float(arr.min()) if len(arr) else float("nan"),
            "max": float(arr.max()) if len(arr) else float("nan"),
            "n_positive": n_pos,
            "required_positive": int(np.ceil(0.9 * seeds)),
            "floor": float(floor),
            "passes": bool(len(arr) and float(np.median(arr)) >= floor
                           and n_pos >= int(np.ceil(0.9 * seeds)))}


def benjamini_hochberg(pvals, q: float = BH_Q) -> tuple[np.ndarray, float]:
    """Step-up BH. Returns the rejection mask and the critical p."""
    p = np.asarray(list(pvals), dtype=float)
    n = len(p)
    rej = np.zeros(n, dtype=bool)
    if not n:
        return rej, 0.0
    order = np.argsort(p, kind="mergesort")
    ranked = p[order]
    passed = ranked <= q * np.arange(1, n + 1) / n
    if not passed.any():
        return rej, 0.0
    k = int(np.flatnonzero(passed).max()) + 1
    rej[order[:k]] = True
    return rej, float(ranked[k - 1])


def bh_label(family: dict, q: float = BH_Q) -> dict:
    """P10 — BH over the DECLARED family, with the labelling the memo prints.

    The family is declared in the pre-registration and does not grow after the
    fact: 6 categories x 2 vintages x {direct, residualised} x {member,
    all-rider} x {strict-dated y/n}. Anything in it without a surviving p prints
    as "not a finding" (the D88 precedent), never as a smaller finding."""
    keys = sorted(family)
    rej, crit = benjamini_hochberg([family[k] for k in keys], q)
    return {"q": float(q), "n_tests": len(keys), "critical_p": crit,
            "family_declared": ("6 categories x 2 vintages x {direct, "
                                "residualised} x {member, all-rider} x "
                                "{strict-dated y/n}"),
            "results": {k: {"p": float(family[k]), "survives_bh": bool(r),
                            "label": "finding" if r else "not a finding"}
                        for k, r in zip(keys, rej)}}


# --------------------------------------------------------------------------
# 9i. the test itself
# --------------------------------------------------------------------------
FULL_COLS = ["log_score", "own_gap_flag", "log_homes", "log_jobs",
             "log_transit", "retail_index"]


def fit_growth_test(panel: pd.DataFrame, *, con=None,
                    feature: str = BIKE_FEATURE,
                    placebo_draws: int = NTA_PLACEBO_DRAWS,
                    decile_placebo_draws: int = DECILE_PLACEBO_DRAWS,
                    bootstrap_draws: int = BOOTSTRAP_DRAWS,
                    seeds: int = FOLD_SEEDS, n_folds: int = N_FOLDS,
                    seed: int = RNG_SEED, per_category: bool = True) -> dict:
    """P0-P11 in execution order, and the order is part of the design.

    The placebo is computed BEFORE anything that touches the real feature is
    fitted, exactly as the pre-registration demands ("run the NTA-block placebo
    first, record its delta p95 and sd, THEN fit the real feature"). The
    baseline model can be fitted first without unblinding anything, because the
    baseline does not contain the feature; the placebo needs its out-of-fold
    predictions to form a delta, and the sequence is recorded in the timestamps
    so the claim is auditable rather than asserted.

    Returns a dict plus `_oof`, the fixed out-of-fold prediction frame every
    bootstrap in this section reads. `run()` pops it and writes it to parquet:
    the P7 cross-vintage comparison needs BOTH vintages' predictions, and
    recomputing them from a summary is not possible."""
    t_start = dt.datetime.now()
    base_cols = FULL_COLS + ["docks_added_24m"]          # P1
    treat_cols = base_cols + [feature]

    attrition = bike_attrition(panel, feature)           # P2
    p = panel.dropna(subset=[feature] + base_cols).copy()
    if p["y"].nunique() < 2 or p["nta_code"].nunique() < n_folds:
        return {"fitted": False,
                "reason": f"only {len(p)} usable rows / "
                          f"{p['nta_code'].nunique()} NTAs after the shared-row "
                          f"filter; no paired test is possible",
                "attrition_P2": attrition, "_oof": pd.DataFrame()}
    fold_map = nta_fold_map(p, n_folds, seed)            # P2: ONE map, both fits

    pre = spatial_pre_diagnostics(con, p, feature, seed=seed)   # P11 before

    # P1's comparability line and the real baseline, on the shared rows/folds.
    auc_full_only, _ = blocked_cv_auc(p, FULL_COLS, fold_map=fold_map)
    auc_base, pred_base = blocked_cv_auc(p, base_cols, fold_map=fold_map)

    # ---- P5/P3: the placebo, FIRST. Nothing above reads `feature`. ----------
    placebo = placebo_delta(p, base_cols, feature, fold_map, auc_base,
                            draws=placebo_draws, seed=seed, mode="nta_block")
    placebo_secondary = placebo_delta(p, base_cols, feature, fold_map, auc_base,
                                      draws=decile_placebo_draws, seed=seed,
                                      mode="decile_swap")
    floor = float(max(DELTA_FLOOR, placebo["p95"]
                      if np.isfinite(placebo["p95"]) else DELTA_FLOOR))

    # ---- the real fit ------------------------------------------------------
    t_fit = dt.datetime.now()
    auc_treat, pred_treat = blocked_cv_auc(p, treat_cols, fold_map=fold_map)
    delta = float(auc_treat - auc_base)
    preds = {"p_base": pred_base, "p_treat": pred_treat}

    # ---- P6: auxiliary R2 and the residualised robustness column -----------
    aux, resid = auxiliary_r2(p, feature)
    p = p.assign(_growth_resid=resid)
    auc_resid, pred_resid = blocked_cv_auc(
        p.dropna(subset=["_growth_resid"]), base_cols + ["_growth_resid"],
        fold_map=fold_map)
    delta_resid = float(auc_resid - auc_base)
    if len(pred_resid) == len(p):
        preds["p_resid"] = pred_resid

    # ---- P9: the pre-trend, when a lagged vintage was joined ---------------
    lag_col = feature + "_lag"
    pre_trend = {"available": False,
                 "note": f"no {lag_col} column on the panel; P9 applies to the "
                         f"2025-01 vintage only"}
    if lag_col in p and p[lag_col].notna().sum() > 100:
        q = p.dropna(subset=[lag_col])
        fm_lag = fold_map
        a_lag, pred_lag = blocked_cv_auc(q, base_cols + [lag_col], fold_map=fm_lag)
        a_base_lag, _ = blocked_cv_auc(q, base_cols, fold_map=fm_lag)
        pre_trend = {"available": True, "n_rows": int(len(q)),
                     "auc_lagged": float(a_lag), "auc_base_same_rows": float(a_base_lag),
                     "delta_lagged": float(a_lag - a_base_lag)}
        if len(q) == len(p):
            preds["p_lag"] = pred_lag

    oof = _oof_frame(p, fold_map, preds)

    # ---- P4: the bootstrap, from the FIXED out-of-fold predictions ---------
    boot_nta = bootstrap_delta(oof, cluster="nta_code", draws=bootstrap_draws, seed=seed)
    boot_cd = bootstrap_delta(oof, cluster="cd_code", draws=bootstrap_draws, seed=seed)
    boot_resid = (bootstrap_delta(oof, treat="p_resid", cluster="cd_code",
                                  draws=bootstrap_draws, seed=seed)
                  if "p_resid" in oof else {})
    if "p_lag" in oof:
        pre_trend["bootstrap_cd"] = bootstrap_delta(
            oof, treat="p_lag", cluster="cd_code", draws=bootstrap_draws, seed=seed)
        diff = _delta_draws(oof, "p_treat", "p_lag", "cd_code", bootstrap_draws, seed)
        s = summarise_draws(diff, "cd_code")
        s["contains_zero"] = bool(s["draws"] and s["ci"][0] <= 0.0 <= s["ci"][1])
        pre_trend["contemporaneous_minus_lagged"] = s
        pre_trend["persistent_location_marker"] = bool(
            pre_trend["delta_lagged"] >= floor and s.get("contains_zero"))
        pre_trend["verdict"] = (
            "FAILS P9 — lagged growth predicts about as well, so the feature is "
            "a persistent location marker, not a change signal"
            if pre_trend["persistent_location_marker"] else
            "passes P9 — contemporaneous growth beats its own lag")

    # ---- P8 ----------------------------------------------------------------
    stability = fold_seed_stability(p, base_cols, treat_cols, seeds=seeds,
                                    n_folds=n_folds, seed=seed, floor=floor)

    # ---- P11 after ---------------------------------------------------------
    post = residual_morans_i(p, oof, seed=seed)

    # ---- the coefficient, reported as co-movement (P12) --------------------
    try:
        res, names = _fit_logit(p, treat_cols)
        i = names.index(feature)
        ci = res.conf_int()
        coef = {"coef": float(res.params[i]), "se": float(res.bse[i]),
                "p": float(res.pvalues[i]),
                "ci": [float(ci[i][0]), float(ci[i][1])]}
        coef["sign"] = (
            "POSITIVE co-movement — openings landed where bike activity had been "
            "GROWING (co-movement, never demand: D1/P12)" if coef["ci"][0] > 0 else
            "NEGATIVE co-movement — openings landed where bike activity had been "
            "SHRINKING" if coef["ci"][1] < 0 else
            "INDISTINGUISHABLE FROM ZERO")
    except Exception as exc:
        coef = {"skipped": str(exc)[:160]}

    quintiles = growth_by_retail_quintile(p, treat_cols, feature)

    # ---- per-category secondaries, each with a bootstrap p (P10) -----------
    by_cat: dict = {}
    if per_category:
        for cat, g in oof.groupby("category"):
            g = g.dropna(subset=["p_base", "p_treat"])
            if g["y"].nunique() < 2 or len(g) < 500:
                by_cat[str(cat)] = {"n": int(len(g)), "skipped": "n < 500 or no variance"}
                continue
            a_t, a_b = _auc(g["y"].to_numpy(), g["p_treat"].to_numpy()), \
                _auc(g["y"].to_numpy(), g["p_base"].to_numpy())
            d = _delta_draws(g, "p_treat", "p_base", "cd_code",
                             max(100, bootstrap_draws // 4), seed)
            s = summarise_draws(d, "cd_code")
            by_cat[str(cat)] = {"n": int(len(g)), "auc_base": float(a_b),
                                "auc_treat": float(a_t), "delta": float(a_t - a_b),
                                "ci": s["ci"], "p": s["p_two_sided"]}

    family = {f"category:{k}": v["p"] for k, v in by_cat.items() if "p" in v}
    family["residualised"] = boot_resid.get("p_two_sided", float("nan")) \
        if boot_resid else float("nan")
    family = {k: v for k, v in family.items() if np.isfinite(v)}
    bh = bh_label(family) if family else {"n_tests": 0, "results": {},
                                          "note": "no secondary p-values"}

    passes_floor = bool(delta >= floor)
    passes_ci = bool(np.isfinite(boot_cd.get("ci", [np.nan])[0])
                     and boot_cd["ci"][0] > DELTA_CI_FLOOR)
    return {
        "fitted": True,
        "feature": feature,
        "t0": str(panel["t0"].iloc[0]) if "t0" in panel else None,
        "member_only": bool(panel["bike_member_only"].iloc[0])
        if "bike_member_only" in panel else None,
        "n_rows": int(len(p)), "n_addresses": int(p["point_id"].nunique()),
        "n_ntas": int(p["nta_code"].nunique()),
        "n_cds": int(oof["cd_code"].nunique()),
        "attrition_P2": attrition,
        "folds_P2": {"n_folds": int(n_folds), "seed": int(seed),
                     "n_ntas_mapped": len(fold_map),
                     "identical_for_both_fits": True,
                     "fold_sizes": pd.Series(list(fold_map.values()))
                     .value_counts().sort_index().to_dict()},
        "spatial_before_P11": pre,
        "auc_full_only_P1": float(auc_full_only),
        "auc_baseline_P1": float(auc_base),
        "auc_with_growth_P0": float(auc_treat),
        "delta_P0": delta,
        "placebo_P5": placebo,
        "placebo_secondary_P5": placebo_secondary,
        "floor_P3": floor,
        "floor_basis_P3": ("placebo p95" if floor > DELTA_FLOOR
                           else f"the absolute floor {DELTA_FLOOR}"),
        "bootstrap_nta_P4": boot_nta,
        "bootstrap_cd_P4": boot_cd,
        "auxiliary_r2_P6": aux,
        "residualised_P6": {
            "auc": float(auc_resid), "delta": delta_resid,
            "bootstrap_cd": boot_resid,
            "red_flag_larger_than_direct": bool(delta_resid > delta),
            "note": ("a residualised lift LARGER than the direct one is a red "
                     "flag (P6): it would mean the controls were absorbing "
                     "signal the feature only carries once they are removed")},
        "retail_quintiles": quintiles,
        "pre_trend_P9": pre_trend,
        "stability_P8": stability,
        "spatial_after_P11": post,
        "coefficient_P12": coef,
        "by_category": by_cat,
        "multiple_testing_P10": bh,
        "passes_floor_P3": passes_floor,
        "passes_ci_P3": passes_ci,
        "passes_P3": bool(passes_floor and passes_ci),
        "timing": {"placebo_ran_at": placebo["ran_at"],
                   "real_fit_ran_at": t_fit.isoformat(timespec="seconds"),
                   "placebo_before_real_fit": bool(
                       dt.datetime.fromisoformat(placebo["ran_at"]) <= t_fit),
                   "runtime_s": round((dt.datetime.now() - t_start).total_seconds(), 1)},
        "_oof": oof,
    }


# --------------------------------------------------------------------------
# 9j. the verdict — P3 + P7 + P8, and nothing else
# --------------------------------------------------------------------------
def bike_growth_verdict(primary: dict, confirmatory: dict | None = None, *,
                        oof: pd.DataFrame | None = None,
                        draws: int = BOOTSTRAP_DRAWS, seed: int = RNG_SEED) -> dict:
    """Apply P3, P7 and P8 exactly, and print the block the result was judged
    against.

    Nothing else enters. P6's auxiliary R2, P9's pre-trend, P11's Moran's I and
    P10's BH labelling are DIAGNOSTICS that decide how the result is described,
    not whether it ships — with one exception the pre-registration writes into
    P9 itself, which is that a feature indistinguishable from its own lag is a
    location marker and fails. That exception is applied here for the vintage
    P9 covers."""
    reasons: list[str] = []
    if not primary.get("fitted"):
        return {"ship": False, "reason": primary.get("reason", "primary not fitted"),
                "judged_against": PREREGISTRATION}

    floor = float(primary["floor_P3"])
    delta = float(primary["delta_P0"])
    ci = primary["bootstrap_cd_P4"].get("ci", [float("nan"), float("nan")])
    p3 = bool(primary.get("passes_P3"))
    if not primary.get("passes_floor_P3"):
        reasons.append(f"P3: delta {delta:+.4f} below the floor {floor:+.4f} "
                       f"({primary['floor_basis_P3']})")
    if not primary.get("passes_ci_P3"):
        reasons.append(f"P3: CD-clustered 95% CI lower limit {ci[0]:+.4f} is not "
                       f"above {DELTA_CI_FLOOR:+.4f}")

    p8 = bool(primary["stability_P8"]["passes"])
    if not p8:
        s = primary["stability_P8"]
        reasons.append(f"P8: median delta {s['median']:+.4f} over {s['seeds']} fold "
                       f"seeds, positive in {s['n_positive']}/{s['seeds']} "
                       f"(need {s['required_positive']})")

    pt = primary.get("pre_trend_P9") or {}
    if pt.get("available") and pt.get("persistent_location_marker"):
        reasons.append("P9: lagged growth predicts about as well as "
                       "contemporaneous growth — persistent location marker")

    # ---- P7 ---------------------------------------------------------------
    p7: dict = {"confirmatory_run": bool(confirmatory and confirmatory.get("fitted"))}
    if not p7["confirmatory_run"]:
        p7["passes"] = False
        p7["reason"] = ("the 2025-01 confirmatory vintage has not been run; P7 "
                        "requires it and there is no ship without it")
        reasons.append("P7: " + p7["reason"])
    else:
        d2 = float(confirmatory["delta_P0"])
        p7["delta_confirmatory"] = d2
        p7["positive"] = bool(d2 > 0)
        conf_ci = confirmatory["bootstrap_cd_P4"].get("ci", [float("nan")])
        p7["independently_clears"] = bool(
            d2 >= float(confirmatory["floor_P3"])
            and np.isfinite(conf_ci[0]) and conf_ci[0] > DELTA_CI_FLOOR)
        diff = {}
        if oof is not None and isinstance(confirmatory.get("_oof"), pd.DataFrame) \
                and len(confirmatory["_oof"]):
            diff = paired_vintage_delta_ci(oof, confirmatory["_oof"],
                                           draws=draws, seed=seed)
            p7["delta_difference_ci"] = diff
        p7["compatible"] = bool(p7["positive"] and diff.get("contains_zero"))
        p7["passes"] = bool(p7["positive"]
                            and (p7["compatible"] or p7["independently_clears"]))
        if not p7["passes"]:
            reasons.append(
                f"P7: confirmatory delta {d2:+.4f}; positive={p7['positive']}, "
                f"compatible={p7['compatible']}, "
                f"independently_clears={p7['independently_clears']}")

    ship = bool(p3 and p8 and p7["passes"]
                and not (pt.get("available") and pt.get("persistent_location_marker")))
    return {
        "ship": ship,
        "P3": {"passes": p3, "delta": delta, "floor": floor,
               "floor_basis": primary["floor_basis_P3"], "cd_ci": ci},
        "P7": p7,
        "P8": {"passes": p8, **{k: primary["stability_P8"][k]
                                for k in ("median", "sd", "n_positive", "seeds")}},
        "reasons": reasons,
        "disposition": (
            "SHIP — bike_growth_12m_rel enters the 2026-10 forecast vintage as "
            "model 0.2.0 with its own retention chain (R2)"
            if ship else
            "CONTEXT ONLY — the feature does not enter the forecast; it is "
            "reported like phases 1 and 2 (D76). Failure ships as a finding "
            "(P12), not as silence."),
        "language": ("Co-movement, never demand. Retail stays the left-hand "
                     "side. (P12, D1)"),
        "judged_against": PREREGISTRATION,
    }


# --------------------------------------------------------------------------
# 9k. the report section
# --------------------------------------------------------------------------
def report_bike_growth(rep: dict, console=None) -> None:
    """Render the "bike growth (D111)" section of `loci retrodiction report`.

    Lives here rather than in the CLI so the P-numbers and the code that
    produced them stay in one file; `cli.py` calls it with the loaded summary."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = console or Console()
    g = rep.get("bike_growth") or {}
    if not g:
        return
    console.print("\n[bold]bike growth (D111 · GTM-168)[/] — does the CHANGE in "
                  "Citi Bike activity before t0 add anything the entry model "
                  "does not already have?")
    if not g.get("fitted"):
        console.print(Panel.fit(f"NOT FITTED — {g.get('reason', 'unknown')}",
                                title="bike growth", border_style="red"))
        return

    a = g["attrition_P2"]
    console.print(
        f"[bold]P2 attrition[/] — {a['n_rows_with_feature']:,} of {a['n_rows']:,} "
        f"rows carry {a['feature']} ({a['share_lost']:.1%} lost); "
        f"{a['n_addresses_with_feature']:,} of {a['n_addresses']:,} addresses. "
        f"{a['claim']}")
    if a["n_rows_lost"]:
        t = Table(show_header=True, header_style="bold")
        for c in ("control", "retained mean", "lost mean", "std diff"):
            t.add_column(c, overflow="fold")
        for col, v in a["retained_vs_lost"].items():
            t.add_row(col, f"{v['retained_mean']:.3f}", f"{v['lost_mean']:.3f}",
                      f"{v['std_diff']:+.3f}")
        console.print(t)

    pre = g["spatial_before_P11"]
    en = pre["effective_n"]
    console.print(
        f"[bold]P11 before[/] — effective n: {en['n_distinct_dock_sets']:,} distinct "
        f"dock sets behind {en['n_panel_addresses']:,} panel addresses "
        f"({en['ratio']:.2f} per address, via {en['method']}). "
        f"Moran's I of the feature "
        f"{_fmt_i(pre['morans_i_feature'])}; across NTAs "
        f"{_fmt_i(pre['morans_i_across_nta'])}. {pre['blocking_note']}")
    if "note" in en:
        console.print(f"[yellow]{en['note']}[/]")

    t = Table(show_header=True, header_style="bold")
    for c in ("P", "measure", "value"):
        t.add_column(c, overflow="fold")
    t.add_row("P1", "blocked-CV AUC, FULL alone (comparability only)",
              f"{g['auc_full_only_P1']:.4f}")
    t.add_row("P1", "blocked-CV AUC, BASELINE = FULL + docks_added_24m",
              f"{g['auc_baseline_P1']:.4f}")
    t.add_row("P0", "blocked-CV AUC, baseline + growth",
              f"{g['auc_with_growth_P0']:.4f}")
    t.add_row("P0", "[bold]delta-AUC (THE number)[/]", f"[bold]{g['delta_P0']:+.4f}[/]")
    pl = g["placebo_P5"]
    t.add_row("P5", f"NTA-block donation placebo on delta ({pl['draws']} draws)",
              f"mean {pl['mean']:+.4f}  sd {pl['sd']:.4f}  p95 {pl['p95']:+.4f}  "
              f"max {pl['max']:+.4f}")
    ps = g["placebo_secondary_P5"]
    t.add_row("P5", f"decile-matched address swap (secondary, {ps['draws']} draws)",
              f"p95 {ps['p95']:+.4f}")
    t.add_row("P3", "floor = max(+0.005, placebo p95)",
              f"{g['floor_P3']:+.4f}  ({g['floor_basis_P3']})")
    bn, bc = g["bootstrap_nta_P4"], g["bootstrap_cd_P4"]
    t.add_row("P4", f"NTA-clustered 95% CI on delta ({bn['draws']} draws)",
              f"[{bn['ci'][0]:+.4f}, {bn['ci'][1]:+.4f}]")
    t.add_row("P4", "[bold]CD-clustered 95% CI on delta (binds)[/]",
              f"[bold][{bc['ci'][0]:+.4f}, {bc['ci'][1]:+.4f}][/]")
    aux = g["auxiliary_r2_P6"]
    t.add_row("P6", "auxiliary R2 of growth on the controls",
              f"{aux.get('r2', float('nan')):.3f}"
              + ("  — carries little independent variation"
                 if aux.get("carries_little_independent_variation") else ""))
    rr = g["residualised_P6"]
    t.add_row("P6", "residualised robustness column (delta)",
              f"{rr['delta']:+.4f}"
              + ("  [red]RED FLAG: larger than the direct lift[/]"
                 if rr["red_flag_larger_than_direct"] else ""))
    st = g["stability_P8"]
    t.add_row("P8", f"fold-seed stability over {st['seeds']} seeds",
              f"median {st['median']:+.4f}  sd {st['sd']:.4f}  positive "
              f"{st['n_positive']}/{st['seeds']} (need {st['required_positive']})")
    pt = g["pre_trend_P9"]
    t.add_row("P9", "lagged-growth pre-trend",
              (f"delta_lagged {pt['delta_lagged']:+.4f}; {pt.get('verdict', '')}"
               if pt.get("available") else pt.get("note", "not run")))
    post = g["spatial_after_P11"]
    t.add_row("P11", "OOS residual Moran's I, baseline -> +growth",
              (f"{post.get('mean_base', float('nan')):.3f} -> "
               f"{post.get('mean_treat', float('nan')):.3f}  "
               f"({post.get('verdict', '')})" if "mean_base" in post
               else post.get("note", "skipped")))
    co = g["coefficient_P12"]
    t.add_row("P12", "growth coefficient (co-movement, never demand)",
              (f"{co['coef']:+.3f} [{co['ci'][0]:+.3f}, {co['ci'][1]:+.3f}] — "
               f"{co['sign']}" if "coef" in co else co.get("skipped", "—")))
    console.print(t)

    bh = g["multiple_testing_P10"]
    t = Table(show_header=True, header_style="bold")
    for c in ("secondary (P10 family)", "n", "delta", "95% CI", "p", "BH q=0.10"):
        t.add_column(c, overflow="fold")
    for cat, r in sorted(g["by_category"].items()):
        if "skipped" in r:
            t.add_row(cat, f"{r['n']:,}", "—", "—", "—", r["skipped"])
            continue
        lab = bh.get("results", {}).get(f"category:{cat}", {})
        t.add_row(cat, f"{r['n']:,}", f"{r['delta']:+.4f}",
                  f"[{r['ci'][0]:+.4f}, {r['ci'][1]:+.4f}]", f"{r['p']:.3f}",
                  lab.get("label", "—"))
    console.print(t)
    console.print(f"[dim]BH over the declared family: {bh.get('n_tests', 0)} tests, "
                  f"critical p {bh.get('critical_p', 0):.4f}. "
                  f"{bh.get('family_declared', '')}[/]")

    q = g.get("retail_quintiles") or {}
    if "top_quintile_only" in q:
        console.print(f"[dim]retail_index quintiles: lift confined to the top "
                      f"quintile = {q['top_quintile_only']} — if True the feature "
                      f"is a retail-corridor effect D88 already ranks.[/]")

    asc = g.get("ascertainment") or {}
    if asc.get("by_month"):
        console.print(f"[dim]P7 ascertainment: {asc['rule']}; truncate at "
                      f"{asc.get('truncate_at')} "
                      f"({asc.get('months_dropped', 0)} months dropped); "
                      f"applied {asc.get('applied')}[/]")

    v = g.get("verdict") or {}
    if v:
        style = "green" if v.get("ship") else "yellow"
        body = (f"{v['disposition']}\n\n"
                + ("\n".join(f"  · {r}" for r in v.get("reasons", []))
                   or "  · every gate cleared")
                + f"\n\n{v.get('language', '')}\n\n"
                  f"--- judged against ---\n{v['judged_against']}")
        console.print(Panel.fit(body, title="bike growth verdict (P3 + P7 + P8)",
                                border_style=style))


def _fmt_i(m: dict) -> str:
    if not m or m.get("i") is None:
        return m.get("note", "—") if m else "—"
    p = m.get("p_perm")
    return f"{m['i']:+.3f}" + (f" (p={p:.3f})" if p is not None else "")


def load_bike_growth(out: pathlib.Path | str | None = None) -> dict:
    """The growth section plus its out-of-fold frame, for a cross-vintage P7."""
    rep = load(out)
    g = rep.get("bike_growth") or {}
    path = (pathlib.Path(out) if out else OUT_DIR) / "bike_growth_oof.parquet"
    if g and path.exists():
        g["_oof"] = pd.read_parquet(path)
    return g
