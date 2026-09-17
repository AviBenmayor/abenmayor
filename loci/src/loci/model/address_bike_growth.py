"""Citi Bike activity GROWTH at address grain (Citi Bike phase 3, GTM-168).

    analysis.address_bike_growth(address_id, borough, asof_month,
        activity_12m, activity_prior_12m, bike_growth_12m, bike_growth_12m_rel,
        n_docks_balanced, balanced_share, docks_added_24m, member_only,
        window_first, window_last, run_at)

WHAT THIS ANSWERS, IN ONE SENTENCE
---------------------------------------------------------------------------
Phase 1 (`model/address_bike.py`) says how busy the docks within a five-minute
walk ARE. This says whether they got busier -- and, because the system-wide
trend is subtracted, whether they got busier THAN THE REST OF THE CITY DID.
It is the first candidate LEADING indicator in the warehouse: everything else
the screen reads is a level today.

NO NEW GEOMETRY, NO NEW DIJKSTRA
---------------------------------------------------------------------------
The reachable dock set is `analysis.address_bike_station`, built once by phase 1
and reused verbatim. That table exists precisely so a different window is a JOIN
rather than another hour of Dijkstra, and this module is the second thing to
collect on that promise.

THE TWO WINDOWS, AND WHY THEY DO NOT OVERLAP
---------------------------------------------------------------------------
RECENT = [M-11, M], PRIOR = [M-23, M-12]. Twelve months each, adjacent, no
overlap: both contain one August and one February, so the comparison is
seasonally adjusted BY CONSTRUCTION rather than by a smoother. Citi Bike's
August runs ~2.5x its February, which is far more seasonality than the subway
has, and a trailing-3-months-vs-same-3-last-year form would be a summer reading.

The activity is the RAW WINDOW TOTAL, with no per-weekday divisor. Phase 1
divides because it publishes a level a human reads ("trips per average
weekday"); here the number is immediately differenced in logs, and the two
windows are twelve months each, so their calendar weekday counts differ by at
most a day or two and the divisor would cancel to under half a percent.

THE BALANCED DOCK SET IS THE LOAD-BEARING PART
---------------------------------------------------------------------------
A dock installed last year contributes nothing to the prior window and a full
year to the recent one. Left in, every address near a new dock reads as booming
and the feature becomes a map of Lyft's capital plan -- which is the D1 error
(dock siting is endogenous to retail) with a trend line drawn through it.

So both windows are summed over a BALANCED set only:

    staging.citibike_station.first_month <= M-23
AND staging.citibike_station.last_month  >= M

An unbalanced dock is excluded from BOTH windows, never from one. A dock born
mid-window contributes to NEITHER. A dock retired before M contributes to
NEITHER, even though it has a complete prior window -- dropping it from the
recent window only would manufacture a decline.

`docks_added_24m` counts the excluded-because-young ones separately and honestly.
It is a CONTROL for the model, never a predictor: "Lyft built a dock here" is not
a statement about retail demand.

NULL, NEVER ZERO
---------------------------------------------------------------------------
`balanced_share` is the share of the address's activity AT MONTH M that the
balanced docks carry -- how much of the present-day traffic the feature can see.
Below `BALANCED_SHARE_FLOOR`, or with no balanced dock at all, the four
value columns are NULL while `n_docks_balanced`, `balanced_share` and
`docks_added_24m` are still written.

A 0 would assert "the docks here did not get busier", a claim about a
neighbourhood. The truth is "most of the bike traffic here is at docks too young
to compare", a claim about a capital plan. Same convention as phase 1's two
shares and phase 2's NTA values -- and the reason for the NULL is stored beside
it, because a NULL whose reason is not recorded is a hole.

THE DETRENDED COLUMN IS THE FEATURE
---------------------------------------------------------------------------
`bike_growth_12m` is dominated by the system-wide trend: the e-bike rollout, the
post-COVID recovery, a fare change. That term is identical for every address and
carries no cross-sectional information whatsoever. `bike_growth_12m_rel`
subtracts the same log ratio computed over the WHOLE balanced set of the system,
and it is the only column downstream code may fit on.

Note what "sums to zero" does and does not mean. The system term is the log of a
TRIP-WEIGHTED aggregate while the address terms are per-address logs, so the
address values sum to zero only when the address panel is a faithful replica of
the system (`tests/test_address_bike_growth.py` builds exactly that case). In a
real panel a Jensen gap remains, and it is a property of the city, not a bug.

ASOF_MONTH IS THE UNIT OF IDEMPOTENCE
---------------------------------------------------------------------------
Together with `member_only`. The builder DELETEs (asof_month, member_only) and
re-INSERTs it, so recomputing the 2025-01 vintage can never rewrite 2023-01.
Two vintages are the entire point (owner ruling R1): if 2023-01 and 2025-01
disagree in sign the feature fails.

A VINTAGE IS REFUSED, NEVER TRUNCATED
---------------------------------------------------------------------------
`require_panel` raises, naming the missing months, when the staging panel does
not hold all twenty-four months [M-23, M]. A partial window would silently
compare eleven months with twelve and report the difference as growth.

CONTEXT ONLY (D76) UNTIL THE GATES PASS
---------------------------------------------------------------------------
Nothing here enters gap_score, supply_ratio_vs_base, a recommendation grade, or
the revenue model's lambda. It reaches `model/forecast.py` only if it clears the
R4 criterion in `validation/retrodiction.py`, and then only at the vintage's OWN
t0 -- reading a trailing window would be look-ahead.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

#: Exactly the columns of analysis.address_bike_growth, in DDL order (sql/038).
GROWTH_COLUMNS = [
    "address_id", "borough", "asof_month", "activity_12m", "activity_prior_12m",
    "bike_growth_12m", "bike_growth_12m_rel", "n_docks_balanced",
    "balanced_share", "docks_added_24m", "member_only", "window_first",
    "window_last", "run_at",
]

#: The columns that are NULL rather than 0 when the censoring gate fails.
VALUE_COLUMNS = ["activity_12m", "activity_prior_12m", "bike_growth_12m",
                 "bike_growth_12m_rel"]

#: Twelve months per window: one August and one February in each, which is what
#: makes the ratio seasonally adjusted without a smoother.
WINDOW_MONTHS = 12

#: Below this share of the address's activity AT MONTH M carried by balanced
#: docks, the feature is NULL. At 0.5 the number is at least a majority reading
#: of the traffic that is actually there; below it the growth of a minority of
#: old docks is being reported as the growth of the block.
BALANCED_SHARE_FLOOR = 0.5

#: Where the log ratio is formed. log1p, so a dock with no trips at all is
#: finite rather than -inf; on any dock with real traffic the +1 is noise.
_EPS = 1e-9


# ------------------------------------------------------------- the calendar

def add_months(month: dt.date, n: int) -> dt.date:
    """The first of the month `n` calendar months from `month`."""
    y, m = month.year, month.month + n
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return dt.date(y, m, 1)


def windows(asof: dt.date) -> tuple[dt.date, dt.date, dt.date, dt.date]:
    """(prior_first, prior_last, recent_first, recent_last) = M-23, M-12, M-11, M.

    Adjacent and non-overlapping. `prior_first` is also `window_first`, the
    month a dock must predate to be in the balanced set.
    """
    asof = month_floor(asof)
    return (add_months(asof, -(2 * WINDOW_MONTHS - 1)),
            add_months(asof, -WINDOW_MONTHS),
            add_months(asof, -(WINDOW_MONTHS - 1)),
            asof)


def month_floor(day: dt.date) -> dt.date:
    """Any date in a month -> the first of it. `asof_month` is always a first."""
    return dt.date(day.year, day.month, 1)


def window_label(asof: dt.date) -> str:
    """'2024-09..2026-08' -- the whole 24-month span, in phase 1's format."""
    first, _, _, last = windows(asof)
    return f"{first:%Y-%m}..{last:%Y-%m}"


def missing_months(con, asof: dt.date) -> list[dt.date]:
    """The months of [M-23, M] that staging.citibike_station_month does not hold."""
    first, _, _, last = windows(asof)
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT month FROM staging.citibike_station_month "
        "WHERE month BETWEEN ? AND ?", [first, last]).fetchall()}
    need = [add_months(last, -i) for i in range(2 * WINDOW_MONTHS - 1, -1, -1)]
    return [m for m in need if m not in have]


def require_panel(con, asof: dt.date) -> None:
    """RAISE unless the panel holds all twenty-four months the windows need.

    Computing on a partial window is the failure mode this exists to stop: eleven
    months against twelve is a -8% growth reading for the whole city, and nothing
    in the output would say so. The message NAMES the missing months, because the
    fix is a back-ingest of exactly those.
    """
    gaps = missing_months(con, asof)
    if not gaps:
        return
    first, _, _, last = windows(asof)
    shown = ", ".join(f"{m:%Y-%m}" for m in gaps[:6])
    more = f" (+{len(gaps) - 6} more)" if len(gaps) > 6 else ""
    raise RuntimeError(
        f"asof {asof:%Y-%m} needs all 24 months of {first:%Y-%m}..{last:%Y-%m} in "
        f"staging.citibike_station_month and {len(gaps)} are missing: {shown}{more}. "
        f"Refusing to compute a growth ratio on a partial window -- eleven months "
        f"against twelve reads as an 8% decline for every address in the city, and "
        f"nothing in the output would say so. Back-ingest them first: "
        f"`loci citibike ingest --start {gaps[0]:%Y-%m} --end {gaps[-1]:%Y-%m}`.")


# ------------------------------------------------------------- the dock panel

def station_activity_sql(member_only: bool) -> str:
    """One row per dock: its life span and its activity in each window and at M.

    The member/all-rider choice is a COLUMN choice, not a filter, so it is
    rendered rather than bound -- `member_starts` and `member_ends` are separate
    columns of staging.citibike_station_month (sql/034), not a rider-type
    dimension to select on.

    WEEKDAY ONLY, summed over all five dayparts, starts PLUS ends. A start and an
    end are different events at different times and both are activity at that
    dock; phase 1 keeps them apart because it publishes them separately, and this
    module adds them because growth in either is growth.

    The LEFT JOIN from the roster is deliberate: a dock with no trips at all in
    the span still needs a row, carrying zeroes, so that `first_month` and
    `last_month` reach the balance test. Dropping it would silently promote the
    address above the balanced-share floor.
    """
    starts = "member_starts" if member_only else "starts"
    ends = "member_ends" if member_only else "ends"
    return f"""
WITH a AS (
    SELECT station_id, month,
           sum(coalesce({starts}, 0) + coalesce({ends}, 0))
               FILTER (day_type = 'weekday')          AS act
    FROM staging.citibike_station_month
    WHERE month BETWEEN ? AND ?
    GROUP BY 1, 2
)
SELECT st.station_id, st.first_month, st.last_month,
       coalesce(sum(a.act) FILTER (a.month BETWEEN ? AND ?), 0) AS act_recent,
       coalesce(sum(a.act) FILTER (a.month BETWEEN ? AND ?), 0) AS act_prior,
       coalesce(sum(a.act) FILTER (a.month = ?), 0)             AS act_at_m
FROM staging.citibike_station st
LEFT JOIN a USING (station_id)
GROUP BY 1, 2, 3
"""


def station_panel(con, asof: dt.date, member_only: bool = True) -> pd.DataFrame:
    """(station_id, first_month, last_month, act_recent, act_prior, act_at_m,
    balanced, added_in_window). RAISES on an empty roster.

    `balanced` is the censoring rule, in ONE place: alive across both windows.
    `added_in_window` is its young complement -- born strictly inside (M-23, M].
    A dock with first_month exactly M-23 was there for the whole span and is
    balanced, not added; the two flags therefore never both hold.
    """
    p_first, p_last, r_first, r_last = windows(asof)
    df = con.execute(station_activity_sql(member_only),
                     [p_first, r_last, r_first, r_last, p_first, p_last,
                      r_last]).fetchdf()
    if df.empty:
        raise RuntimeError(
            "staging.citibike_station is empty: run `loci citibike ingest` first. "
            "Refusing to write a growth measure with no dock roster, which would "
            "NULL every address and read as a city with no bike share.")
    first = pd.to_datetime(df["first_month"])
    last = pd.to_datetime(df["last_month"])
    lo, hi = pd.Timestamp(p_first), pd.Timestamp(r_last)
    df["balanced"] = (first <= lo) & (last >= hi)
    df["added_in_window"] = (first > lo) & (first <= hi)
    for c in ("act_recent", "act_prior", "act_at_m"):
        df[c] = df[c].fillna(0).astype("float64")
    return df


def system_growth(panel: pd.DataFrame) -> float:
    """The system's own log ratio over the SAME balanced set, which is what
    `bike_growth_12m_rel` subtracts.

    Over the whole balanced set and not over the reachable docks of some average
    address: the detrending term has to be the same scalar for every address, or
    the column is not a detrend, it is a second measure.
    """
    bal = panel[panel["balanced"]]
    if bal.empty:
        raise RuntimeError(
            "no dock in the roster is present across both windows, so there is no "
            "system trend to detrend against. Either the panel is shorter than 24 "
            "months (run `loci citibike growth-stats`) or first_month/last_month "
            "were never derived by the ingest.")
    return float(np.log1p(bal["act_recent"].sum()) - np.log1p(bal["act_prior"].sum()))


# --------------------------------------------------------- the address frames

def address_universe(con, boroughs: list[str] | None,
                     frames: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Every address in scope, BOTH sampling frames -- the no-eligibility-gate
    rule (owner 2026-09-13). An address with no balanced dock gets a ROW with
    NULL values and a stored reason, never an absent row: "measured, nothing
    comparable within a five-minute walk" and "never computed" are different
    facts, and until 2026-09-16 every one of D84's 50,199 street midpoints was
    silently in the second category.

    Owner ruling 4 (2026-09-16) removed the `frame = 'lot'` filter that used to
    live here. `frames=('lot',)` reproduces the old universe and exists only so
    a test can prove the lot rows did not move; nothing in the build passes it.

    This function does NOT widen the geometry: the reachable dock set still
    comes from `analysis.address_bike_station`, which phase 1
    (`model/address_bike.py`) sweeps. If phase 1 has not been re-swept over the
    street frame, every street row here reads "no balanced dock" -- true of the
    pipeline, not of the city -- which is why `build_growth` compares the two
    universes and refuses to be quiet about the difference.
    """
    where: list[str] = []
    params: list = []
    if frames is not None:
        where.append(f"COALESCE(frame, 'lot') IN ({', '.join('?' for _ in frames)})")
        params += list(frames)
    if boroughs:
        where.append(f"borough IN ({', '.join('?' for _ in boroughs)})")
        params += list(boroughs)
    sql = "SELECT address_id, borough FROM analysis.address"
    if where:
        sql += f" WHERE {' AND '.join(where)}"
    df = con.execute(sql, params).fetchdf()
    if df.empty:
        raise RuntimeError(
            f"no addresses in analysis.address for boroughs={boroughs}, "
            f"frames={frames or 'ALL'}. Run `loci address-gaps` first; an empty "
            f"frame would write a vintage of zero rows that reads as a computed "
            f"absence.")
    return df


def load_reachable(con, boroughs: list[str] | None) -> pd.DataFrame:
    """The persisted phase-1 reachable set (address_id, station_id) in scope.

    RAISES when it is empty: phase 1's Dijkstra is the only source of this
    geometry, and an empty set would NULL every address for a reason that has
    nothing to do with growth.
    """
    where, params = "", []
    if boroughs:
        where = f"WHERE borough IN ({', '.join('?' for _ in boroughs)})"
        params = list(boroughs)
    df = con.execute(
        f"SELECT address_id, station_id FROM analysis.address_bike_station "
        f"{where}", params).fetchdf()
    if df.empty:
        raise RuntimeError(
            f"analysis.address_bike_station is empty for boroughs={boroughs}: run "
            f"`loci citibike address-measures` first. Without the reachable set "
            f"every address would read NULL for want of a dock, which is a "
            f"statement about this pipeline and not about the network.")
    return df


#: Aggregated in an in-memory DuckDB rather than in pandas, for the reason
#: `address_bike.measures` gives: the natural pandas route materialises the pair
#: table once per weight column, and this step must run identically against a
#: read-only snapshot.
#:
#: Two docks reachable from one address are SUMMED, not deduplicated -- they are
#: two docks and their trips are different trips.
MEASURE_SQL = """
SELECT u.address_id,
       u.borough,
       count(w.station_id) FILTER (w.balanced)           AS n_docks_balanced,
       count(w.station_id) FILTER (w.added_in_window)    AS docks_added_24m,
       sum(w.act_recent) FILTER (w.balanced)             AS activity_12m,
       sum(w.act_prior)  FILTER (w.balanced)             AS activity_prior_12m,
       sum(w.act_at_m)   FILTER (w.balanced)             AS balanced_at_m,
       sum(w.act_at_m)                                   AS all_at_m
FROM u
LEFT JOIN reach r ON r.address_id = u.address_id
LEFT JOIN w      ON w.station_id  = r.station_id
GROUP BY 1, 2
"""


def measures(universe: pd.DataFrame, reachable: pd.DataFrame,
             panel: pd.DataFrame, asof: dt.date, member_only: bool = True,
             system: float | None = None) -> pd.DataFrame:
    """One row per in-scope address, in GROWTH_COLUMNS order minus `run_at`.

    The censoring gate is applied HERE and nowhere else: the SQL above sums the
    balanced docks honestly and the gate decides whether that sum is allowed to
    become a number.
    """
    import duckdb

    if system is None:
        system = system_growth(panel)
    p_first, _, _, r_last = windows(asof)
    mem = duckdb.connect()
    try:
        mem.register("u", universe[["address_id", "borough"]])
        mem.register("reach", reachable[["address_id", "station_id"]])
        mem.register("w", panel[["station_id", "act_recent", "act_prior",
                                 "act_at_m", "balanced", "added_in_window"]])
        df = mem.execute(MEASURE_SQL).fetchdf()
    finally:
        mem.close()

    for c in ("n_docks_balanced", "docks_added_24m"):
        df[c] = df[c].fillna(0).astype("int64")
    for c in ("activity_12m", "activity_prior_12m", "balanced_at_m", "all_at_m"):
        df[c] = df[c].astype("float64")

    # NULL, not 0: a share of no traffic does not exist. An address whose docks
    # were all silent in month M has no denominator, and that is a censoring
    # failure exactly like a young dock -- we cannot see what share we can see.
    df["balanced_share"] = np.where(
        df["all_at_m"] > _EPS, df["balanced_at_m"] / df["all_at_m"], np.nan)

    measurable = ((df["n_docks_balanced"] > 0)
                  & df["balanced_share"].notna()
                  & (df["balanced_share"] >= BALANCED_SHARE_FLOOR))
    df["activity_12m"] = df["activity_12m"].where(measurable)
    df["activity_prior_12m"] = df["activity_prior_12m"].where(measurable)
    df["bike_growth_12m"] = (np.log1p(df["activity_12m"])
                             - np.log1p(df["activity_prior_12m"]))
    df["bike_growth_12m_rel"] = df["bike_growth_12m"] - system

    df["asof_month"] = r_last
    df["member_only"] = bool(member_only)
    df["window_first"] = p_first
    df["window_last"] = r_last
    return df[[c for c in GROWTH_COLUMNS if c != "run_at"]]


# --------------------------------------------------------------- the checks

def check_identity(meas: pd.DataFrame, system: float,
                   rtol: float = 1e-9) -> dict:
    """The log-ratio identity, asserted on the frame about to be written.

    Three things that a refactor can quietly break and that no downstream reader
    could detect: the ratio is formed from the two stored activity columns; the
    detrend is a SUBTRACTION of one scalar; and the four value columns are NULL
    together, never in part. A half-NULL row would let a join produce a growth
    with no activity behind it.
    """
    v = meas[meas["bike_growth_12m"].notna()]
    want = np.log1p(v["activity_12m"]) - np.log1p(v["activity_prior_12m"])
    bad = int((np.abs(v["bike_growth_12m"] - want)
               > rtol * np.maximum(np.abs(want), 1.0)).sum())
    bad_rel = int((np.abs(v["bike_growth_12m_rel"]
                          - (v["bike_growth_12m"] - system))
                   > rtol * max(abs(system), 1.0)).sum())
    nulls = meas[VALUE_COLUMNS].isna()
    ragged = int((nulls.any(axis=1) & ~nulls.all(axis=1)).sum())
    if bad or bad_rel or ragged:
        raise RuntimeError(
            f"the growth columns do not reproduce from the stored activity: "
            f"{bad} rows break log1p(recent) - log1p(prior), {bad_rel} break the "
            f"detrend, {ragged} are part-NULL. A part-NULL row is the dangerous "
            f"one: it lets a downstream join read a growth with no activity "
            f"behind it.")
    return {
        "rows": len(meas),
        "with_a_value": len(v),
        "null_no_balanced_dock": int((meas["n_docks_balanced"] == 0).sum()),
        "null_below_floor": int(((meas["n_docks_balanced"] > 0)
                                 & meas["bike_growth_12m"].isna()).sum()),
        "system_growth": float(system),
        "mean_rel": float(v["bike_growth_12m_rel"].mean()) if len(v) else float("nan"),
        "sum_rel": float(v["bike_growth_12m_rel"].sum()) if len(v) else float("nan"),
    }


# ---------------------------------------------------------------- the write

def has_vintage(con, asof: dt.date, member_only: bool,
                boroughs: list[str] | None = None) -> int:
    """How many rows the table already holds for this (asof_month, member_only)."""
    scope = (f" AND borough IN ({', '.join('?' for _ in boroughs)})"
             if boroughs else "")
    return int(con.execute(
        f"SELECT count(*) FROM analysis.address_bike_growth "
        f"WHERE asof_month = ? AND member_only = ?{scope}",
        [month_floor(asof), bool(member_only), *(boroughs or [])]).fetchone()[0])


def write_measures(con, meas: pd.DataFrame, asof: dt.date, member_only: bool,
                   run_at: dt.datetime,
                   boroughs: list[str] | None = None) -> dict:
    """DELETE this vintage, then INSERT it. (asof_month, member_only) is the key.

    The whole reason this table is keyed on the vintage is that two of them must
    coexist (owner ruling R1), so the DELETE is scoped to the one being rebuilt
    and can never reach 2023-01 while 2025-01 is recomputed. The borough clause
    only NARROWS a scoped run: a `--boroughs BK` rebuild must not wipe Manhattan.
    """
    asof = month_floor(asof)
    scope = (f" AND borough IN ({', '.join('?' for _ in boroughs)})"
             if boroughs else "")
    con.execute(
        f"DELETE FROM analysis.address_bike_growth "
        f"WHERE asof_month = ? AND member_only = ?{scope}",
        [asof, bool(member_only), *(boroughs or [])])
    out = meas.copy()
    out["run_at"] = run_at
    con.register("_bg", out[GROWTH_COLUMNS])
    try:
        con.execute(
            f"INSERT INTO analysis.address_bike_growth "
            f"({', '.join(GROWTH_COLUMNS)}) "
            f"SELECT {', '.join(GROWTH_COLUMNS)} FROM _bg")
    finally:
        con.unregister("_bg")
    rows, valued = con.execute(
        f"SELECT count(*), count(bike_growth_12m_rel) "
        f"FROM analysis.address_bike_growth "
        f"WHERE asof_month = ? AND member_only = ?{scope}",
        [asof, bool(member_only), *(boroughs or [])]).fetchone()
    return {"rows_written": int(rows), "rows_with_a_value": int(valued),
            "asof_month": f"{asof:%Y-%m}", "member_only": bool(member_only)}


# ---------------------------------------------------------------- the build

def frame_sweep_coverage(con, universe: pd.DataFrame, reachable: pd.DataFrame,
                         allow_unswept_frame: bool = False) -> dict:
    """Per sampling frame: how many in-scope addresses appear in the PERSISTED
    reachable set. Raises when a whole frame is missing from it.

    THE SILENT ZERO THIS EXISTS TO STOP. This module never touches the walk
    graph; the dock geometry is phase 1's `analysis.address_bike_station`. So
    widening the universe to the street frame (owner ruling 4) BEFORE phase 1
    has been re-swept over that frame produces 50,199 perfectly well-formed
    rows, every one saying "no balanced dock", every one NULL-with-a-reason --
    and the reason stored would be a fact about this pipeline, not about Citi
    Bike. Nothing downstream could tell that from a genuine dock desert.

    A frame with SOME coverage is fine and is only reported: a real address can
    legitimately have no dock within 400 m. A frame with ZERO coverage while
    another frame has some is a missed sweep, and raises.
    """
    have = set(reachable["address_id"].unique())
    frames = con.execute(
        "SELECT address_id, COALESCE(frame, 'lot') AS frame FROM analysis.address"
    ).fetchdf()
    u = universe[["address_id"]].merge(frames, on="address_id", how="left")
    u["frame"] = u["frame"].fillna("lot")
    u["swept"] = u["address_id"].isin(have)
    out = {str(f): {"addresses": int(len(g)), "in_reachable_set": int(g["swept"].sum())}
           for f, g in u.groupby("frame")}
    dead = sorted(f for f, v in out.items()
                  if v["addresses"] and v["in_reachable_set"] == 0)
    alive = [f for f, v in out.items() if v["in_reachable_set"] > 0]
    if dead and alive and not allow_unswept_frame:
        raise RuntimeError(
            f"frame(s) {dead} are in the universe but have ZERO rows in "
            f"analysis.address_bike_station, while {alive} do. Phase 1 has not "
            f"been swept over them: run `loci citibike address-measures "
            f"--re-sweep` first. Writing the vintage now would store "
            f"{sum(out[f]['addresses'] for f in dead):,} rows reading 'no balanced "
            f"dock' -- a statement about this pipeline that is indistinguishable "
            f"downstream from a real dock desert. Pass allow_unswept_frame=True "
            f"only if you intend to store that.")
    return out


def build_growth(con, asof: dt.date, boroughs: list[str] | None = None,
                 member_only: bool = True, re_sweep: bool = False,
                 dry_run: bool = False,
                 allow_unswept_frame: bool = False) -> tuple[pd.DataFrame, dict]:
    """(measures frame, report) for ONE vintage. READ-ONLY under `dry_run`.

    `--asof` is repeatable on the CLI and the loop lives there, so a refused
    vintage names itself rather than aborting a multi-vintage run anonymously.
    """
    asof = month_floor(asof)
    require_panel(con, asof)
    panel = station_panel(con, asof, member_only=member_only)
    system = system_growth(panel)
    universe = address_universe(con, boroughs)
    reachable = load_reachable(con, boroughs)
    swept = frame_sweep_coverage(con, universe, reachable,
                                 allow_unswept_frame=allow_unswept_frame)

    meas = measures(universe, reachable, panel, asof,
                    member_only=member_only, system=system)
    checks = check_identity(meas, system)

    p_first, p_last, r_first, r_last = windows(asof)
    run_at = dt.datetime.now()
    existing = has_vintage(con, asof, member_only, boroughs)
    report = {
        "asof_month": f"{asof:%Y-%m}",
        "member_only": bool(member_only),
        "window": window_label(asof),
        "prior_window": f"{p_first:%Y-%m}..{p_last:%Y-%m}",
        "recent_window": f"{r_first:%Y-%m}..{r_last:%Y-%m}",
        "boroughs": list(boroughs) if boroughs else "ALL",
        "docks_in_roster": len(panel),
        "docks_balanced": int(panel["balanced"].sum()),
        "docks_added_in_window": int(panel["added_in_window"].sum()),
        "balanced_share_of_system_at_m": float(
            panel.loc[panel["balanced"], "act_at_m"].sum()
            / max(panel["act_at_m"].sum(), 1.0)),
        "balanced_share_floor": BALANCED_SHARE_FLOOR,
        "addresses_in_scope": len(universe),
        "sweep_coverage_by_frame": swept,
        "median_balanced_share": float(meas["balanced_share"].median(skipna=True)),
        "median_growth": float(meas["bike_growth_12m"].median(skipna=True)),
        "existing_rows_for_this_vintage": existing,
        "re_sweep": bool(re_sweep),
        "run_at": run_at.isoformat(timespec="seconds"),
        **checks,
    }
    if not dry_run:
        if existing and not re_sweep:
            report["_written"] = {
                "skipped": f"{existing:,} rows already stored for asof "
                           f"{asof:%Y-%m} (member_only={member_only}); --re-sweep "
                           f"to rebuild the vintage"}
        else:
            report["_written"] = write_measures(con, meas, asof, member_only,
                                                run_at, boroughs)
    return meas, report


# ------------------------------------------------------------ the read-back

VALIDATION_SQL = """
-- Proves on the WAREHOUSE, not on the frame the run built:
--   1. every in-scope address -- BOTH sampling frames since owner ruling 4,
--      2026-09-16 -- has a ROW for the vintage, so the no-eligibility-gate
--      rule is visible rather than asserted. The row COUNT is the check: this
--      table carries no `frame` column, so compare `rows` against
--      `SELECT count(*) FROM analysis.address` for the same borough scope;
--   2. a censored address is NULL and never 0 (impossible_zero must be 0) --
--      a growth of exactly 0.0 with no balanced dock would be a fabricated
--      "the docks here did not change";
--   3. the four value columns are NULL together (part_null must be 0);
--   4. balanced_share is a share, in [0, 1];
--   5. docks_added_24m is stored and is NOT inside the feature -- it is
--      reported here so a reader can see how much network expansion the
--      vintage sat on top of.
SELECT g.asof_month,
       g.member_only,
       g.borough,
       count(*)                                              AS rows,
       count(g.bike_growth_12m_rel)                          AS with_a_value,
       count(*) FILTER (WHERE g.n_docks_balanced = 0)        AS no_balanced_dock,
       count(*) FILTER (WHERE g.n_docks_balanced > 0
                          AND g.bike_growth_12m IS NULL)     AS below_floor,
       count(*) FILTER (WHERE g.bike_growth_12m IS NULL
                          AND g.activity_12m IS NOT NULL)    AS part_null,
       count(*) FILTER (WHERE g.n_docks_balanced = 0
                          AND g.bike_growth_12m = 0)         AS impossible_zero,
       round(median(g.balanced_share), 4)                    AS p50_balanced_share,
       min(g.balanced_share)                                 AS min_balanced_share,
       max(g.balanced_share)                                 AS max_balanced_share,
       round(median(g.bike_growth_12m), 4)                   AS p50_growth,
       round(median(g.bike_growth_12m_rel), 4)               AS p50_growth_rel,
       round(avg(g.bike_growth_12m_rel), 6)                  AS mean_growth_rel,
       round(median(g.docks_added_24m), 1)                   AS p50_docks_added,
       max(g.docks_added_24m)                                AS max_docks_added
FROM analysis.address_bike_growth g
GROUP BY ROLLUP(g.asof_month, g.member_only, g.borough)
ORDER BY g.asof_month NULLS LAST, g.member_only NULLS LAST, g.borough NULLS LAST
"""

#: What the table holds, one row per stored vintage. Read-only; this is the
#: whole body of `loci citibike growth-stats`.
VINTAGE_SQL = """
SELECT asof_month, member_only,
       min(window_first)                        AS window_first,
       max(window_last)                         AS window_last,
       count(*)                                 AS addresses,
       count(bike_growth_12m_rel)               AS with_a_value,
       round(100.0 * count(bike_growth_12m_rel) / nullif(count(*), 0), 1)
                                                AS coverage_pct,
       count(*) FILTER (n_docks_balanced = 0)   AS no_balanced_dock,
       count(*) FILTER (n_docks_balanced > 0
                    AND bike_growth_12m IS NULL) AS below_floor,
       round(median(n_docks_balanced), 1)       AS p50_docks_balanced,
       round(median(docks_added_24m), 1)        AS p50_docks_added,
       round(median(balanced_share), 3)         AS p50_balanced_share,
       round(median(bike_growth_12m), 4)        AS p50_growth,
       round(median(bike_growth_12m_rel), 4)    AS p50_growth_rel,
       round(quantile_cont(bike_growth_12m_rel, 0.1), 4) AS p10_growth_rel,
       round(quantile_cont(bike_growth_12m_rel, 0.9), 4) AS p90_growth_rel,
       max(run_at)                              AS run_at
FROM analysis.address_bike_growth
GROUP BY 1, 2
ORDER BY 1, 2
"""


#: Rebuilds ONE address's vintage straight from the staging panel and the
#: persisted reachable set, independently of the frames the build used. The same
#: role RECONCILE_SQL plays in phase 1: it says the pipeline is arithmetic rather
#: than hope, and it re-applies the balance test in SQL so a change to the python
#: predicate cannot land quietly.
#:
#: Parameters: address_id, window_first, window_last (the balance test), then
#: recent_first, recent_last, prior_first, prior_last, asof.
RECONCILE_SQL = """
WITH r AS (
    SELECT station_id FROM analysis.address_bike_station WHERE address_id = ?
), bal AS (
    SELECT station_id FROM staging.citibike_station
    WHERE station_id IN (SELECT station_id FROM r)
      AND first_month <= ? AND last_month >= ?
), m AS (
    SELECT station_id, month,
           sum(coalesce(member_starts, 0) + coalesce(member_ends, 0))
               FILTER (day_type = 'weekday') AS act
    FROM staging.citibike_station_month
    WHERE station_id IN (SELECT station_id FROM bal)
    GROUP BY 1, 2
)
SELECT (SELECT count(*) FROM bal)                        AS n_docks_balanced,
       coalesce(sum(act) FILTER (month BETWEEN ? AND ?), 0) AS rebuilt_recent,
       coalesce(sum(act) FILTER (month BETWEEN ? AND ?), 0) AS rebuilt_prior,
       coalesce(sum(act) FILTER (month = ?), 0)             AS rebuilt_at_m
FROM m
"""


def reconcile(con, address_id: str, asof: dt.date,
              rtol: float = 1e-9) -> dict:
    """Re-derive one address's stored vintage and RAISE if it differs.

    Member series only -- that is the ruled base series and the one anything
    downstream may fit on. Cheap enough to run on every build.
    """
    asof = month_floor(asof)
    p_first, p_last, r_first, r_last = windows(asof)
    r = con.execute(RECONCILE_SQL,
                    [address_id, p_first, r_last, r_first, r_last,
                     p_first, p_last, r_last]).fetchdf()
    got = con.execute(
        "SELECT activity_12m, activity_prior_12m, bike_growth_12m, "
        "       n_docks_balanced "
        "FROM analysis.address_bike_growth "
        "WHERE address_id = ? AND asof_month = ? AND member_only",
        [address_id, asof]).fetchone()
    if got is None:
        raise RuntimeError(
            f"{address_id} has no member-series row at asof {asof:%Y-%m}. Every "
            f"in-scope address gets a row, in BOTH sampling frames since owner "
            f"ruling 4 (no eligibility gate); a missing one "
            f"means the vintage was built on a narrower scope than this query.")
    n_bal = int(r.at[0, "n_docks_balanced"])
    if int(got[3]) != n_bal:
        raise RuntimeError(
            f"{address_id}: stored n_docks_balanced={got[3]} but the balance test "
            f"re-applied in SQL finds {n_bal}. The python predicate and the SQL "
            f"one disagree about first_month <= {p_first} AND last_month >= "
            f"{r_last}.")
    if got[0] is None:                # censored: nothing to reconcile arithmetically
        return {"address_id": address_id, "asof_month": f"{asof:%Y-%m}",
                "n_docks_balanced": n_bal, "censored": True}
    pairs = [("activity_12m", float(got[0]), float(r.at[0, "rebuilt_recent"])),
             ("activity_prior_12m", float(got[1]), float(r.at[0, "rebuilt_prior"]))]
    bad = [(k, a, b) for k, a, b in pairs
           if abs(a - b) > rtol * max(abs(b), 1.0)]
    if bad:
        raise RuntimeError(
            f"the stored vintage for {address_id} does not reproduce from the "
            f"panel: {bad}. Either the window moved under the columns, or the "
            f"balanced-set rule changed without the vintage being rebuilt.")
    want = float(np.log1p(pairs[0][2]) - np.log1p(pairs[1][2]))
    if abs(float(got[2]) - want) > rtol * max(abs(want), 1.0):
        raise RuntimeError(
            f"{address_id}: stored bike_growth_12m={got[2]} but the activity "
            f"columns give {want}. The log ratio is not the ratio of the stored "
            f"numbers.")
    return {"address_id": address_id, "asof_month": f"{asof:%Y-%m}",
            "n_docks_balanced": n_bal, "censored": False,
            "activity_12m": pairs[0][1], "activity_prior_12m": pairs[1][1],
            "bike_growth_12m": float(got[2])}
