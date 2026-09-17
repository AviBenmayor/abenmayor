"""Premises tenure prior from LL157 (`analysis.storefront_tenure`,
`analysis.nta_tenure`, three columns on `analysis.address`).

sql/051_storefront_tenure.sql carries the run/turnover definitions and the
two caveats that matter (12-month interval censoring; same-class tenant swaps
are invisible). Read it first.

WHAT IS COMPUTED, per premises, from analysis.storefront_year:
  * the sequence of observed years (vacant IS NOT NULL) with their class;
  * OCCUPANCY RUNS: maximal stretches of observed years that are occupied
    with the same `activity_canonical`, bridging a missing year only when the
    class matches on both sides;
  * TURNOVERS: occupant changes between consecutive observed years
    (occupied->vacant, vacant->occupied, class A->class B);
  * left/right censoring flags for the runs touching the panel's edges.

THE ADDRESS MEASURE (400 m NETWORK, model/walk_catchment.py):
  n_premises_400m           premises with >= 1 observed year
  premises_turnover_400m    sum(turnovers) / sum(premises-years observed)
  median_tenure_years_400m  run-weighted median run length, from a histogram
                            of run lengths (runs are whole years, so the
                            histogram IS the exact distribution)

CONTEXT, NOT A GRADE. Nothing here moves gap_score. D88: LL157 self-reports
lag a year and cluster where retail is thick; a longer median tenure on a
strip is as likely a landlord's lease policy as a tenant's success.
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

TABLE = "analysis.storefront_tenure"
NTA_VIEW = "analysis.nta_tenure"
SOURCE_VIEW = "analysis.storefront_year"

#: Longest run the panel can hold; 2019-2024 is six, 2025 supplements make
#: seven possible in principle. The histogram covers 1..MAX_RUN_YEARS.
MAX_RUN_YEARS = 8

ADDRESS_COLUMNS = ["n_premises_400m", "premises_turnover_400m",
                   "median_tenure_years_400m", "tenure_run_at"]


# ---------------------------------------------------------------------------
# 1. the premises table
# ---------------------------------------------------------------------------
def runs_of(years: list[int], vacant: list[bool | None],
            activity: list[str | None]) -> dict:
    """Pure: one premises' observed (year, vacant, class) -> its runs and
    turnovers. Rows whose `vacant` is None (never observed at 12/31) are
    dropped BEFORE anything is computed -- an unobserved year is not a
    vacant one (sql/045)."""
    obs = [(int(y), bool(v), (a.strip().upper() or None) if isinstance(a, str) else None)
           for y, v, a in zip(years, vacant, activity, strict=True) if v is not None]
    obs.sort()
    if not obs:
        return {"n_years_observed": 0, "n_years_occupied": 0, "n_years_vacant": 0,
                "n_runs": 0, "n_turnovers": 0, "runs": [], "first_year": None,
                "last_year": None, "current_activity": None, "current_vacant": None}
    first_year, last_year = obs[0][0], obs[-1][0]
    runs: list[dict] = []
    turnovers = 0
    cur = None
    prev = None
    for y, vac, act in obs:
        state = None if vac else (act or "OCCUPIED")
        if prev is not None:
            _py, pstate = prev
            if pstate != state:
                turnovers += 1
        if state is None:
            if cur is not None:
                runs.append(cur)
                cur = None
        else:
            if cur is not None and cur["activity"] == state:
                cur["to"] = y
                cur["years"] += 1
            else:
                if cur is not None:
                    runs.append(cur)
                cur = {"activity": state, "from": y, "to": y, "years": 1}
        prev = (y, state)
    if cur is not None:
        runs.append(cur)
    for r in runs:
        r["left"] = r["from"] == first_year
        r["right"] = r["to"] == last_year
    n_occ = sum(1 for _, v, _ in obs if not v)
    last_state = obs[-1]
    current = runs[-1] if runs and runs[-1]["to"] == last_year else None
    return {
        "n_years_observed": len(obs), "n_years_occupied": n_occ,
        "n_years_vacant": len(obs) - n_occ, "n_runs": len(runs),
        "n_turnovers": turnovers, "runs": runs,
        "first_year": first_year, "last_year": last_year,
        "current_activity": None if last_state[1] else last_state[2],
        "current_vacant": last_state[1],
        "current_run_years": current["years"] if current else 0,
        "left_censored": any(r["left"] for r in runs),
        "right_censored": any(r["right"] for r in runs),
        "mean_run_years": (sum(r["years"] for r in runs) / len(runs)) if runs else None,
        "max_run_years": max((r["years"] for r in runs), default=None),
    }


def compute(con) -> pd.DataFrame:
    """One row per premises. READ-ONLY."""
    df = con.execute(f"""
        SELECT premises_id, reporting_year, vacant, activity_canonical,
               any_value(borough) OVER w AS borough, any_value(bbl) OVER w AS bbl,
               any_value(nta_code) OVER w AS nta_code,
               avg(lon) OVER w AS lon, avg(lat) OVER w AS lat
        FROM {SOURCE_VIEW}
        WINDOW w AS (PARTITION BY premises_id)
        ORDER BY premises_id, reporting_year
    """).fetchdf()
    if df.empty:
        raise RuntimeError(f"{SOURCE_VIEW} is empty -- run the LL157 ingest first; an "
                           f"empty tenure table would read as a city with no storefronts.")
    rows = []
    for pid, g in df.groupby("premises_id", sort=False):
        vac = [None if pd.isna(v) else bool(v) for v in g["vacant"]]
        r = runs_of(g["reporting_year"].tolist(), vac, g["activity_canonical"].tolist())
        if r["n_years_observed"] == 0:
            continue
        head = g.iloc[0]
        rows.append({
            "premises_id": pid,
            "borough": head["borough"] if isinstance(head["borough"], str) else None,
            "bbl": head["bbl"] if isinstance(head["bbl"], str) else None,
            "nta_code": head["nta_code"] if isinstance(head["nta_code"], str) else None,
            "lon": None if pd.isna(head["lon"]) else float(head["lon"]),
            "lat": None if pd.isna(head["lat"]) else float(head["lat"]),
            "first_year": r["first_year"], "last_year": r["last_year"],
            "n_years_observed": r["n_years_observed"],
            "n_years_occupied": r["n_years_occupied"],
            "n_years_vacant": r["n_years_vacant"],
            "n_runs": r["n_runs"], "n_turnovers": r["n_turnovers"],
            "mean_run_years": r["mean_run_years"], "max_run_years": r["max_run_years"],
            "current_run_years": r["current_run_years"],
            "current_activity": r["current_activity"],
            "current_vacant": r["current_vacant"],
            "left_censored": r["left_censored"], "right_censored": r["right_censored"],
            "runs_json": json.dumps(r["runs"]),
        })
    out = pd.DataFrame(rows)
    out["built_at"] = pd.Timestamp(dt.datetime.now())
    return out


COLUMNS = ["premises_id", "borough", "bbl", "nta_code", "lon", "lat", "first_year",
           "last_year", "n_years_observed", "n_years_occupied", "n_years_vacant",
           "n_runs", "n_turnovers", "mean_run_years", "max_run_years",
           "current_run_years", "current_activity", "current_vacant",
           "left_censored", "right_censored", "runs_json", "built_at"]


def write(con, frame: pd.DataFrame) -> int:
    payload = frame[COLUMNS]
    con.execute("BEGIN")
    try:
        con.execute(f"DELETE FROM {TABLE}")
        con.register("_st", payload)
        con.execute(f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) "
                    f"SELECT {', '.join(COLUMNS)} FROM _st")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_st")
    return len(payload)


def validate(con) -> list[str]:
    problems: list[str] = []
    n_src = con.execute(
        f"SELECT count(DISTINCT premises_id) FROM {SOURCE_VIEW} WHERE vacant IS NOT NULL"
    ).fetchone()[0]
    n_tab = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    if n_src != n_tab:
        problems.append(f"{n_tab:,} premises in {TABLE} but {n_src:,} observed premises in "
                        f"{SOURCE_VIEW} -- rows dropped or duplicated")
    y_src = con.execute(
        f"SELECT count(*) FROM {SOURCE_VIEW} WHERE vacant IS NOT NULL").fetchone()[0]
    y_tab = con.execute(f"SELECT sum(n_years_observed) FROM {TABLE}").fetchone()[0] or 0
    if int(y_src) != int(y_tab):
        problems.append(f"premises-years {int(y_tab):,} != observed rows {int(y_src):,}")
    bad = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE n_turnovers > n_years_observed - 1 "
        f"OR n_years_occupied + n_years_vacant <> n_years_observed").fetchone()[0]
    if bad:
        problems.append(f"{bad:,} rows have impossible turnover/occupancy counts")
    return problems


def build(con, *, dry_run: bool = False) -> tuple[pd.DataFrame, dict]:
    df = compute(con)
    rep = {"premises": len(df),
           "premises_years": int(df["n_years_observed"].sum()),
           "turnovers": int(df["n_turnovers"].sum()),
           "runs": int(df["n_runs"].sum()),
           "mean_run_years": float(df["mean_run_years"].mean()),
           "by_borough": df.groupby("borough", dropna=False).size().to_dict()}
    if not dry_run:
        rep["_written"] = write(con, df)
        rep["_problems"] = validate(con)
    return df, rep


# ---------------------------------------------------------------------------
# 2. the address measure
# ---------------------------------------------------------------------------
def _guard(cols: list[str]) -> None:
    from loci.model.storefront_pipeline import _guard as pipeline_guard
    pipeline_guard(cols)


def compute_measure(con, boroughs: list[str] | None, *, radius_m=None,
                    graph_path=None) -> tuple[pd.DataFrame, dict]:
    from loci.model.walk_catchment import load_addresses, network_sums

    pts = con.execute(f"""
        SELECT lon, lat, 1.0 AS n_prem, n_years_observed::DOUBLE AS prem_years,
               n_turnovers::DOUBLE AS turnovers, runs_json
        FROM {TABLE} WHERE lon IS NOT NULL AND lat IS NOT NULL
    """).fetchdf()
    if pts.empty:
        raise RuntimeError(f"{TABLE} has no placed premises -- run `loci storefront-tenure "
                           f"build` first; zeros everywhere would read as a city with no shops.")
    hist_cols = [f"run_{k}" for k in range(1, MAX_RUN_YEARS + 1)]
    for c in hist_cols:
        pts[c] = 0.0
    for i, rj in enumerate(pts["runs_json"]):
        for r in json.loads(rj):
            k = min(int(r["years"]), MAX_RUN_YEARS)
            pts.at[i, f"run_{k}"] += 1.0
    weight_cols = ["n_prem", "prem_years", "turnovers", *hist_cols]
    addr = load_addresses(con, boroughs)
    sums, rep = network_sums(pts, weight_cols, addr, radius_m=radius_m, graph_path=graph_path)

    import numpy as np
    H = np.rint(sums[hist_cols].to_numpy()).astype("int64")
    total = H.sum(axis=1)
    cum = np.cumsum(H, axis=1)
    # run-weighted median: the smallest k whose cumulative count reaches half
    half = (total + 1) / 2.0
    med = np.full(len(total), np.nan)
    has = total > 0
    if has.any():
        idx = (cum[has] >= half[has, None]).argmax(axis=1)
        med[has] = idx + 1
    n_prem = np.rint(sums["n_prem"].to_numpy()).astype("int64")
    prem_years = np.rint(sums["prem_years"].to_numpy())
    turn = np.rint(sums["turnovers"].to_numpy())
    out = pd.DataFrame({
        "address_id": sums["address_id"], "borough": sums["borough"],
        "n_premises_400m": n_prem,
        "premises_turnover_400m": np.where(
            prem_years > 0, turn / np.where(prem_years > 0, prem_years, 1), np.nan),
        "median_tenure_years_400m": med,
        "tenure_run_at": pd.Timestamp(dt.datetime.now()),
    })
    rep.update({"rows": len(out), "boroughs": list(boroughs) if boroughs else "ALL",
                "addresses_with_premises": int((n_prem > 0).sum()),
                "max_n_premises_400m": int(n_prem.max())})
    return out, rep


def write_measure(con, df: pd.DataFrame, boroughs: list[str] | None) -> int:
    _guard(ADDRESS_COLUMNS)
    reset = ", ".join(f"{c} = NULL" for c in ADDRESS_COLUMNS)
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        con.execute(f"UPDATE analysis.address SET {reset} WHERE borough IN ({holes})",
                    list(boroughs))
    else:
        con.execute(f"UPDATE analysis.address SET {reset}")
    payload = df[["address_id", "borough", *ADDRESS_COLUMNS]]
    con.register("_tm", payload)
    try:
        sets = ", ".join(f"{c} = _tm.{c}" for c in ADDRESS_COLUMNS)
        con.execute(f"UPDATE analysis.address AS a SET {sets} FROM _tm "
                    f"WHERE a.address_id = _tm.address_id AND a.borough = _tm.borough")
    finally:
        con.unregister("_tm")
    return len(payload)


def validate_measure(con, boroughs: list[str] | None) -> list[str]:
    problems: list[str] = []
    scope, params = "", []
    if boroughs:
        holes = ", ".join("?" for _ in boroughs)
        scope, params = f"WHERE borough IN ({holes})", list(boroughs)
    n, have = con.execute(
        f"SELECT count(*), count(n_premises_400m) FROM analysis.address {scope}", params
    ).fetchone()
    if n != have:
        problems.append(f"{n - have:,} addresses carry NULL n_premises_400m; 0 is a value")
    total = con.execute(f"SELECT count(*) FROM {TABLE} WHERE lon IS NOT NULL").fetchone()[0]
    mx = con.execute(f"SELECT max(n_premises_400m) FROM analysis.address {scope}",
                     params).fetchone()[0]
    if mx is not None and mx > total:
        problems.append(f"max n_premises_400m {mx} exceeds the {total} placed premises")
    bad = con.execute(
        f"SELECT count(*) FROM analysis.address {scope} {'AND' if scope else 'WHERE'} "
        f"(n_premises_400m = 0 AND median_tenure_years_400m IS NOT NULL)", params).fetchone()[0]
    if bad:
        problems.append(f"{bad:,} addresses have a median tenure with no premises")
    return problems


def build_measure(con, boroughs: list[str] | None, *, radius_m=None, graph_path=None,
                  dry_run: bool = False) -> tuple[pd.DataFrame, dict]:
    df, rep = compute_measure(con, boroughs, radius_m=radius_m, graph_path=graph_path)
    if not dry_run:
        rep["_written"] = write_measure(con, df, boroughs)
        rep["_problems"] = validate_measure(con, boroughs)
    return df, rep
