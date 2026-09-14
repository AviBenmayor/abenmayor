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

    # (d2) the ledger's own closed_on, once a source publishes one. Added
    # 2026-09-14 after the Foursquare open-only filter was removed upstream.
    # It puts EVENTS on the cohort for the first time -- and immediately runs
    # into the harder problem, which is not identification but ASCERTAINMENT.
    has_closed = con.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'analysis' AND table_name = 'poi_presence' "
        "AND column_name = 'closed_on'").fetchone()[0]
    if has_closed:
        n_ledger, n_cohort_events = con.execute(
            f"""SELECT count(closed_on),
                      count(*) FILTER (
                        WHERE closed_on IS NOT NULL
                          AND first_seen_kind IN ('source_date', 'gov_filing')
                          AND first_seen_src_date BETWEEN ? AND ?
                          AND closed_on >= first_seen_src_date
                          AND borough IN ({", ".join(f"'{b}'" for b in BOROUGHS_FULL)}))
               FROM analysis.poi_presence""", [start, end]).fetchone()
        out.append(ClosureInstrument(
            "poi_presence.closed_on (Foursquare)", True, int(n_cohort_events),
            f"{int(n_ledger):,} ledger rows now carry a source-published "
            f"closing date; {int(n_cohort_events):,} of them are cohort "
            f"openings that closed after they opened. ABOVE the "
            f"{MIN_EVENTS_FOR_HAZARD}-event floor -- and still not a survival "
            f"outcome. {int(n_cohort_events):,} events on a cohort of this "
            f"size implies roughly 99% two-year survival, against a true NYC "
            f"food-service rate near 75-80%: Foursquare ascertains on the "
            f"order of 3% of closures, and not at random (a bar closing is "
            f"announced, a tailor closing is not). Any hazard ratio fitted "
            f"here is a statement about Foursquare's editorial pipeline. It "
            f"is a lead, not an outcome, until an ascertainment model exists."))

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
                include_censored: bool = True) -> pd.DataFrame:
    """address x category, scored as of t0, with the 2023-24 openings as the
    dependent variable.

    Deterministic sampling by `hash(address_id)` so a rerun is a rerun. Lot
    frame only (D84: a street midpoint has no residents and the homes
    denominator would be structurally zero)."""
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
             .merge(pts.drop(columns=["lon", "lat"]), on="point_id", how="left"))
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
    panel["t0"] = t0
    panel["window_end"] = window_end
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
                   seed: int = RNG_SEED) -> tuple[float, np.ndarray]:
    """Out-of-sample AUC with WHOLE NTAs held out.

    A random split leaks: two addresses 150 m apart share nearly the same 400 m
    disc, the same supply, the same openings. Holding out NTAs forces the model
    to generalise to a neighbourhood it has never seen, which is the only
    version of "predicts" an allocator should accept."""
    import statsmodels.api as sm
    rng = np.random.default_rng(seed)
    ntas = np.asarray(panel["nta_code"].fillna("NA").unique(), dtype=object)
    rng.shuffle(ntas)
    folds = np.array_split(ntas, n_folds)
    preds = np.full(len(panel), np.nan)
    idx = panel.reset_index(drop=True)
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
    params: dict = field(default_factory=dict)


def run(*, window: str | None = None, radius_m: float = RADIUS_M,
        sample_n: int = DEFAULT_SAMPLE_N, permutations: int = PERMUTATIONS,
        out: pathlib.Path | str | None = None, strict_dated: bool = True) -> dict:
    """Cohort -> closure audit -> gated survival -> entry retrodiction."""
    start, end = WINDOW_START, WINDOW_END
    if window:
        a, b = window.split(":")
        start = dt.date(int(a[:4]), int(a[5:7]), 1)
        y, m = int(b[:4]), int(b[5:7])
        end = (dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1))

    out_dir = pathlib.Path(out) if out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)

    cohort = build_cohort(con, start, end)
    sel = cohort_selection(con, start, end)
    audit = closure_audit(con, start, end)
    n_events = observable_closures(audit)

    cohort["duration_months"] = cohort["exposure_days"] / 30.44
    cohort["event"] = 0                      # no closure is observable; see audit
    gate = survival_gate(cohort, n_events)
    gate["km_if_events_existed"] = kaplan_meier(
        cohort["duration_months"].to_numpy(), cohort["event"].to_numpy())

    panel = build_panel(con, sample_n=sample_n, radius_m=radius_m, t0=start,
                        window_end=end, include_censored=True)
    entry = fit_entry(panel, permutations=permutations)

    entry_strict = {}
    if strict_dated:
        panel_s = build_panel(con, sample_n=sample_n, radius_m=radius_m, t0=start,
                              window_end=end, include_censored=False)
        entry_strict = fit_entry(panel_s, permutations=max(50, permutations // 4))

    cohort.to_parquet(out_dir / "cohort.parquet", index=False)
    panel.to_parquet(out_dir / "entry_panel.parquet", index=False)
    rep = RunReport(cohort_n=len(cohort), selection=sel,
                    closure=[asdict(i) for i in audit], survival=gate,
                    entry=entry, entry_strict=entry_strict,
                    params={"window": f"{start}:{end}", "radius_m": radius_m,
                            "sample_n": sample_n, "permutations": permutations,
                            "distance": "straight-line EPSG:32618",
                            "snapshot": str(SNAPSHOT), "seed": RNG_SEED,
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
