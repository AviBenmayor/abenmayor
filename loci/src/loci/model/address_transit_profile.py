"""Walkable subway entries at address grain, BY DAY TYPE AND TIME OF DAY.

    analysis.address_transit_profile(address_id, day_type, daypart,
                                     transit_entries_400m)
    analysis.address_entrance(address_id, entrance_id, complex_id, dist_m)
    analysis.address.transit_am_pm_share_400m

WHY THIS EXISTS (owner request, 2026-09-13)
---------------------------------------------------------------------------
"Foot traffic must be available per day and time of day, not a single daily
total." `analysis.address.transit_entries_400m` is one average-weekday number,
and one number cannot answer the question a retail lead actually asks. A
laundromat and a breakfast counter and a wine shop are three different bets on
three different hours, and a Saturday-dominant corner is a different business
from a Tuesday-morning one. The MTA feed has been hourly the whole time; the
build was throwing the hour away at the query (contrarian memo, section 3).

WHAT IS AND IS NOT NEW HERE
---------------------------------------------------------------------------
NOTHING about the geography changes. Same walk graph, same `_prune` + `_to_csr`
CSR, same scipy Dijkstra, same 400 m NETWORK radius, same entry-allowed
entrance set, same EVEN split of a complex's entries across its doors. The only
new thing is that the per-complex weight is now a 3 x 5 grid (weekday /
saturday / sunday x five dayparts) instead of a scalar.

THE GRAIN, AND WHY A NEW TABLE IS THE RIGHT ANSWER HERE (D61 inventory rule)
---------------------------------------------------------------------------
The owner's rule is: inventory before adding a table; a PIVOT of an existing
grain is a view, and a new MEASURE at an existing grain extends that grain.
This is neither. `address x day_type x daypart` is a GRAIN THAT DOES NOT EXIST
in the warehouse -- `analysis.address` is one row per address and
`analysis.address_category` is one row per address per category -- so the
fifteen cells cannot extend either without becoming fifteen columns, which is
the pivot-shaped duplication D61 removed, in a wider costume. So: one LONG
table, and `analysis.address_transit_profile_wide` is the view for anyone who
wants the pivot.

`transit_am_pm_share_400m` IS a new measure at an existing grain -- one number
per address -- so it extends `analysis.address`, per the same rule.

SPARSE, AND WHY THAT IS NOT AN ELIGIBILITY GATE (D75)
---------------------------------------------------------------------------
Rows are written ONLY for addresses with at least one reachable entrance.
An address absent from this table has 0.0 in all fifteen cells -- a REAL
observation, "no station within a five-minute walk", exactly the convention
`transit_entries_400m` already uses. Materialising those zeros would be 11.5M
rows to say what an absence already says, on a measure that is zero for 65% of
Brooklyn. The universe is NOT reduced: `analysis.address_transit_profile_wide`
LEFT JOINs `analysis.address` and COALESCEs to 0.0, so every address in the
screen appears there with a value, and nothing is ever ranked or filtered by
presence in the long table. Read the VIEW when you need the universe; read the
TABLE when you need the rows that carry signal.

THE PERSISTED REACHABLE SET -- THE POINT OF `analysis.address_entrance`
---------------------------------------------------------------------------
The expensive object in this pipeline is not the ridership feed (90 seconds);
it is the Dijkstra sweep over every address (tens of minutes). Every variant
anybody will want next -- a different window, a sixth daypart, a school-year
comparison, a non-even split once per-entrance volumes exist -- is the SAME
sweep with different weights. So the sweep's output is persisted at its
natural grain, (address_id, entrance_id, dist_m), and the weights are kept out
of it: `analysis.address_entrance` says which doors an address can walk to and
how far, `entrance_table` says how many doors each complex has, and
`profile_entries` says how many people used each complex in each cell. Any
future question is then a JOIN, not an hour of Dijkstra.

`dist_m` is carried even though nothing reads it yet, because it is free at
sweep time and is the only thing that makes a distance-decay kernel (the
contrarian's section 5 graduation test) possible without re-sweeping.

BIASES THIS INHERITS AND DOES NOT FIX
---------------------------------------------------------------------------
1. EVEN SPLIT ACROSS ENTRANCES. A complex's entries are divided equally over
   its entry-allowed doors because no public source publishes per-entrance
   volume. 59.7% of all weekday entries sit at complexes with >= 6 entrances,
   so for a third of the system each door gets <= 1/6 of the complex: the busy
   corner is UNDERSTATED and the side streets are CREDITED with demand they do
   not see. `analysis.address_entrance` is exactly the artefact that makes
   fixing this a re-weight rather than a re-sweep, if per-entrance counts ever
   appear.
2. ENTRIES, NOT FOOTFALL, AND STILL ONLY ONE DIRECTION. Splitting by daypart
   does NOT recover the evening ARRIVAL flow: arrivals are not published per
   station at all. What the split buys is the ability to tell a
   morning-dominant (residential) complex from an evening-dominant (job-centre)
   one -- which is what `transit_am_pm_share_400m` is for -- not a two-way
   count. Do not read `pm_peak` as "people on the sidewalk at 6pm".
3. THE WINDOW IS THREE SUMMER MONTHS. School is out. A school-adjacent complex
   reads low, and the saturday/sunday split is a summer weekend.
4. 400 m IS BINARY IN BROOKLYN. 65% of Brooklyn addresses have no entrance
   within 400 m network, so every daypart column is zero for them too. A
   daypart split does not make a degenerate variable non-degenerate.

NOT A SCORE INPUT
---------------------------------------------------------------------------
Like its parent, nothing here enters `gap_score`, `supply_ratio_vs_base` or any
recommendation grade. `PROFILE_ADDRESS_COLUMNS` is asserted disjoint from every
sibling annotation before the UPDATE runs.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import pickle

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from loci.model.address_access import (
    DEFAULT_RADIUS_M,
    load_address_points,
)
from loci.model.conveniences import graph_version
from loci.model.supply_ratio import BATCH
from loci.score.access import MIN_COMPONENT, _prune, _to_csr
from loci.score.walkgraph import OUT as GRAPH_PATH
from loci.sources.cities.nyc.mta_ridership import (
    DAY_TYPES,
    DAYPART_NAMES,
)

#: The ONLY columns this module may name in a SET clause on analysis.address.
#: Deliberately NOT folded into address_access.ACCESS_COLUMNS: that list is
#: RESET to NULL by `loci address-access`, which does not compute these, so a
#: shared list would blank the share on every access re-run.
PROFILE_ADDRESS_COLUMNS = [
    "transit_am_pm_share_400m",
    "transit_profile_run_at",
]

#: Tolerance on "the weekday dayparts must re-sum to the column already on
#: analysis.address". Both sides are float sums of the same entrance weights in
#: a different order, so this is float associativity and nothing else.
REBUILD_RTOL = 1e-6


# ---------------------------------------------------------------- the sweep

def catchment_pairs(A, query_nidx: np.ndarray, target_nidx: np.ndarray,
                    radius_m: float = DEFAULT_RADIUS_M,
                    batch: int = BATCH) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(query_pos, target_pos, dist_m) for every (query node, target point)
    pair within `radius_m` NETWORK metres.

    The membership version of `model/supply_ratio.catchment_sums`: same CSR,
    same bounded scipy Dijkstra sourced FROM the query nodes, same
    `<= radius_m` test. The only difference is that the mask is returned as
    pairs instead of being multiplied into a weight vector, which is what lets
    the weights change later without re-running the sweep.

    `target_nidx` is one entry PER TARGET POINT, not per node: two entrances
    that snap to the same graph node are two rows here, exactly as
    `node_weights` would have added both their weights onto that node. Nothing
    is deduplicated.

    Pure: a CSR matrix and two index arrays in, three arrays out. No database,
    no graph pickle, no cache -- tests drive it on a synthetic line graph.
    """
    qs: list[np.ndarray] = []
    ts: list[np.ndarray] = []
    ds: list[np.ndarray] = []
    if len(query_nidx) == 0 or len(target_nidx) == 0:
        z = np.empty(0, dtype=np.int64)
        return z, z, np.empty(0, dtype=np.float64)
    cols = np.asarray(target_nidx, dtype=np.int64)
    for s in range(0, len(query_nidx), batch):
        chunk = np.asarray(query_nidx[s:s + batch])
        D = dijkstra(A, directed=False, indices=chunk, limit=float(radius_m))
        sub = D[:, cols]
        qi, ti = np.nonzero(sub <= radius_m)
        qs.append(qi.astype(np.int64) + s)
        ts.append(ti.astype(np.int64))
        ds.append(sub[qi, ti])
    return np.concatenate(qs), np.concatenate(ts), np.concatenate(ds)


def build_reachable(con, boroughs: list[str] | None, entrances: list[dict],
                    radius_m: float = DEFAULT_RADIUS_M,
                    graph_path: pathlib.Path = GRAPH_PATH,
                    batch: int = BATCH) -> tuple[pd.DataFrame, dict]:
    """(address_id, borough, entrance_id, complex_id, dist_m) for every address
    in scope and every entry-allowed entrance it can walk to inside `radius_m`.

    READ-ONLY on the warehouse. `entrances` is `mta_ridership.entrance_table`'s
    first return, i.e. the SAME door set `entry_points` weights, so the two can
    never disagree about which doors exist.
    """
    import osmnx as ox

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)

    e_nodes = ox.distance.nearest_nodes(
        Gp, X=[e["lon"] for e in entrances], Y=[e["lat"] for e in entrances])
    e_nidx = np.array([idx[n] for n in np.atleast_1d(e_nodes)], dtype=np.int64)

    addr = load_address_points(con, boroughs)
    if addr.empty:
        raise RuntimeError(
            f"no addresses in analysis.address for boroughs={boroughs}. Run "
            f"`loci address-gaps` first; an empty frame would DELETE the profile "
            f"for that scope and write nothing back.")
    a_nodes = ox.distance.nearest_nodes(
        Gp, X=addr["lon"].tolist(), Y=addr["lat"].tolist())
    a_nidx = np.array([idx[n] for n in np.atleast_1d(a_nodes)], dtype=np.int64)
    # Identical collapse to compute_access: a 400 m catchment cannot tell two
    # doorways on one block apart, so the sweep runs once per distinct NODE and
    # the result is broadcast back to the addresses on it.
    uniq, inv = np.unique(a_nidx, return_inverse=True)

    qi, ti, dist = catchment_pairs(A, uniq, e_nidx, radius_m=radius_m, batch=batch)
    node_pairs = pd.DataFrame({"q": qi, "e": ti, "dist_m": dist})
    ent = pd.DataFrame(entrances)[["entrance_id", "complex_id"]]
    ent["e"] = np.arange(len(ent), dtype=np.int64)
    node_pairs = node_pairs.merge(ent, on="e", how="inner")

    left = pd.DataFrame({"address_id": addr["address_id"].to_numpy(),
                         "borough": addr["borough"].to_numpy(),
                         "q": inv.astype(np.int64)})
    out = left.merge(node_pairs[["q", "entrance_id", "complex_id", "dist_m"]],
                     on="q", how="inner")
    out = out.drop(columns=["q"])

    report = {
        "boroughs": list(boroughs) if boroughs else "ALL",
        "radius_m": float(radius_m),
        "graph_version": graph_version(graph_path),
        "addresses_in_scope": int(len(addr)),
        "query_nodes": int(uniq.size),
        "entrance_points": int(len(entrances)),
        "pairs": int(len(out)),
        "addresses_with_an_entrance": int(out["address_id"].nunique()),
    }
    return out, report


# ------------------------------------------------------------ the weighting

def entrance_weights(profile: dict[str, dict[tuple[str, str], float]],
                     entrances: list[dict]) -> pd.DataFrame:
    """(entrance_id, complex_id, day_type, daypart, entries_per_day) -- the
    EVEN split applied at the last possible moment.

    Every entrance of a complex carries `complex entries / n_doors` in each of
    the fifteen cells. Kept out of `analysis.address_entrance` on purpose (see
    the module docstring): the persisted geometry must outlive this particular
    window and this particular split convention.

    RAISES if a complex in the entrance table has no profile row. That would be
    a complex silently contributing zero entries at every hour -- the confident
    false negative ("no subway here") this pipeline exists to refuse.
    """
    missing = sorted({e["complex_id"] for e in entrances} - set(profile))
    if missing:
        raise RuntimeError(
            f"{len(missing)} complexes in the entrance table have no ridership "
            f"profile ({missing[:5]}); they would contribute 0 entries in every "
            f"daypart, which reads downstream as 'no subway here'.")
    rows = []
    for e in entrances:
        cell = profile[e["complex_id"]]
        n = int(e["n_doors"])
        if n <= 0:                                          # pragma: no cover
            raise RuntimeError(f"entrance {e['entrance_id']} has n_doors={n}")
        for d in DAY_TYPES:
            for p in DAYPART_NAMES:
                rows.append((e["entrance_id"], e["complex_id"], d, p,
                             float(cell[(d, p)]) / n))
    return pd.DataFrame(rows, columns=["entrance_id", "complex_id", "day_type",
                                       "daypart", "entries_per_day"])


def profile_long(reachable: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """(address_id, day_type, daypart, transit_entries_400m), long form.

    Aggregated in an IN-MEMORY DuckDB rather than pandas: the natural pandas
    route materialises pairs x 15 rows, and the join is a group-by that DuckDB
    does out of core. The warehouse connection is deliberately not used -- this
    step must run identically against a read-only snapshot.

    Two entrances of the SAME complex reachable from one address are summed,
    not deduplicated: each carries 1/n of that complex, so an address that can
    reach 3 of a complex's 12 doors is credited 3/12 of it. That is the even
    split's own arithmetic, not a double count.
    """
    import duckdb

    mem = duckdb.connect()
    try:
        mem.register("reach", reachable[["address_id", "entrance_id"]])
        mem.register("w", weights)
        return mem.execute("""
            SELECT r.address_id,
                   w.day_type,
                   w.daypart,
                   sum(w.entries_per_day) AS transit_entries_400m
            FROM reach r
            JOIN w USING (entrance_id)
            GROUP BY 1, 2, 3
        """).fetchdf()
    finally:
        mem.close()


def am_pm_share_frame(long_df: pd.DataFrame, day_type: str = "weekday"
                      ) -> pd.DataFrame:
    """(address_id, transit_am_pm_share_400m) -- weekday am_peak / pm_peak,
    ENTRIES-WEIGHTED over the address's reachable entrances by construction
    (both sides are already the entries-weighted sums).

    NULL where pm_peak is 0. A station-type classifier, not a level: > 1 is a
    residential (morning-outbound) catchment, < 1 a job-centre one.
    """
    w = long_df[long_df["day_type"] == day_type]
    piv = w.pivot_table(index="address_id", columns="daypart",
                        values="transit_entries_400m", aggfunc="sum").fillna(0.0)
    am = piv.get("am_peak", pd.Series(0.0, index=piv.index))
    pm = piv.get("pm_peak", pd.Series(0.0, index=piv.index))
    share = np.where(pm > 0, am / pm.where(pm > 0, 1.0), np.nan)
    return pd.DataFrame({"address_id": piv.index,
                         "transit_am_pm_share_400m": share}).reset_index(drop=True)


def check_rebuilds_the_daily_total(con, long_df: pd.DataFrame,
                                   boroughs: list[str] | None,
                                   rtol: float = REBUILD_RTOL) -> dict:
    """The weekday dayparts must re-sum to `analysis.address.transit_entries_400m`.

    This is the invariant the owner asked for in so many words -- "keep the
    existing column equal to the weekday all-day sum so nothing already written
    diverges" -- and it is checked against the WAREHOUSE, not against the frame
    this run built, so it catches a graph that moved, a window that moved, an
    entrance set that moved, and a concurrent `loci address-gaps` that replaced
    the rows underneath. Addresses absent from `long_df` must be exactly the
    addresses whose stored column is 0.
    """
    wd = (long_df[long_df["day_type"] == "weekday"]
          .groupby("address_id", as_index=False)["transit_entries_400m"].sum()
          .rename(columns={"transit_entries_400m": "rebuilt"}))
    scope = ""
    params: list = []
    if boroughs:
        scope = f"AND borough IN ({', '.join('?' for _ in boroughs)})"
        params = list(boroughs)
    # A borough whose access_run_at has been NULLed by a concurrent
    # `loci address-gaps` (which DELETE/INSERTs analysis.address) would silently
    # drop OUT of the comparison below and then get profile rows written beside
    # a NULL scalar column -- the two diverging in the direction the owner
    # explicitly asked to prevent. Name it and refuse it instead.
    cov = con.execute(
        f"SELECT borough, count(*) AS n, count(access_run_at) AS acc "
        f"FROM analysis.address WHERE 1=1 {scope} GROUP BY 1", params).fetchdf()
    bare = sorted(cov.loc[cov["acc"] == 0, "borough"].astype(str))
    if bare:
        raise RuntimeError(
            f"boroughs {bare} have access_run_at NULL on every row: "
            f"`loci address-access` has not been run for them, or a concurrent "
            f"`loci address-gaps` destroyed the rows it wrote. Writing a daypart "
            f"profile beside a NULL transit_entries_400m would be exactly the "
            f"divergence this check exists to prevent. Run "
            f"`loci address-access --boroughs {','.join(bare)}` first, or re-run this "
            f"with --boroughs limited to the covered ones.")
    partial = cov[(cov["acc"] > 0) & (cov["acc"] < cov["n"])]
    stored = con.execute(
        f"SELECT address_id, transit_entries_400m AS stored FROM analysis.address "
        f"WHERE access_run_at IS NOT NULL {scope}", params).fetchdf()
    if stored.empty:
        raise RuntimeError(
            "analysis.address has no rows with access_run_at set for this scope: "
            "`loci address-access` has not been run (or a concurrent screen re-run "
            "has NULLed it). Refusing to claim the daypart split reproduces a "
            "column that is not there.")
    m = stored.merge(wd, on="address_id", how="left")
    m["rebuilt"] = m["rebuilt"].fillna(0.0)
    denom = m["stored"].abs().clip(lower=1.0)
    rel = (m["rebuilt"] - m["stored"]).abs() / denom
    worst = int(rel.idxmax()) if len(rel) else None
    rep = {
        "addresses_compared": int(len(m)),
        "stored_total": float(m["stored"].sum()),
        "rebuilt_total": float(m["rebuilt"].sum()),
        "worst_relative_error": float(rel.max()) if len(rel) else 0.0,
        "worst_address_id": None if worst is None else str(m.loc[worst, "address_id"]),
        "stored_zero_and_absent": int(((m["stored"] == 0) & (m["rebuilt"] == 0)).sum()),
        "boroughs_partially_covered": {r.borough: f"{r.acc}/{r.n}"
                                       for r in partial.itertuples()},
        "rtol": rtol,
    }
    if len(rel) and rel.max() > rtol:
        raise RuntimeError(
            f"the weekday daypart sum does not reproduce "
            f"analysis.address.transit_entries_400m: worst relative error "
            f"{rel.max():.3%} at address {rep['worst_address_id']} (tolerance "
            f"{rtol:.1e}). Either the sweep used a different graph/radius/window "
            f"than the stored column, or a concurrent screen re-run replaced the "
            f"rows. Do NOT write: the two would silently disagree.")
    return rep


# --------------------------------------------------------------- the write

def _guard(cols: list[str]) -> None:
    """Refuse to write if the SET list touches a column another module owns."""
    from loci.model.address_access import ACCESS_COLUMNS
    from loci.model.address_access import _guard as access_guard

    access_guard(cols)                       # every sibling annotation
    overlap = sorted(set(cols) & set(ACCESS_COLUMNS))
    if overlap:
        raise RuntimeError(
            f"transit-profile would clobber address-access columns: {overlap}")


def write_profile(con, reachable: pd.DataFrame, long_df: pd.DataFrame,
                  shares: pd.DataFrame, boroughs: list[str] | None,
                  meta: dict) -> dict:
    """DELETE-then-INSERT the two tables IN SCOPE, then UPDATE the two columns
    on analysis.address IN SCOPE. Scoped by borough, exactly as every sibling
    builder is, so running MN does not destroy BK.

    `analysis.address_entrance` carries `borough` for no other reason than to
    make this DELETE scoped; nothing reads it.
    """
    _guard(PROFILE_ADDRESS_COLUMNS)
    run_at = meta["run_at"]
    where, params = "", []
    if boroughs:
        where = f"WHERE borough IN ({', '.join('?' for _ in boroughs)})"
        params = list(boroughs)

    con.execute(f"DELETE FROM analysis.address_entrance {where}", params)
    con.execute(f"DELETE FROM analysis.address_transit_profile {where}", params)

    ent = reachable.copy()
    ent["radius_m"] = float(meta["radius_m"])
    ent["graph_version"] = meta["graph_version"]
    ent["run_at"] = run_at
    con.register("_ent", ent[["address_id", "borough", "entrance_id", "complex_id",
                              "dist_m", "radius_m", "graph_version", "run_at"]])
    prof = long_df.merge(reachable[["address_id", "borough"]].drop_duplicates(),
                         on="address_id", how="left")
    if prof["borough"].isna().any():                        # pragma: no cover
        raise RuntimeError("a profile row has no borough; the scoped DELETE "
                           "would not be able to remove it on the next run.")
    prof["radius_m"] = float(meta["radius_m"])
    prof["transit_entries_window"] = meta["window"]
    prof["transit_entries_snap"] = meta["snap"]
    prof["profile_run_at"] = run_at
    con.register("_prof", prof[["address_id", "borough", "day_type", "daypart",
                                "transit_entries_400m", "radius_m",
                                "transit_entries_window", "transit_entries_snap",
                                "profile_run_at"]])
    sh = shares.copy()
    sh["transit_profile_run_at"] = run_at
    con.register("_sh", sh[["address_id", *PROFILE_ADDRESS_COLUMNS]])
    try:
        # Named column lists, never a positional SELECT *: D72 records exactly
        # this shape silently mis-mapping two type-compatible columns when a
        # new one landed in the table.
        con.execute(
            "INSERT INTO analysis.address_entrance "
            "(address_id, borough, entrance_id, complex_id, dist_m, radius_m, "
            " graph_version, run_at) "
            "SELECT address_id, borough, entrance_id, complex_id, dist_m, radius_m, "
            "       graph_version, run_at FROM _ent")
        con.execute(
            "INSERT INTO analysis.address_transit_profile "
            "(address_id, borough, day_type, daypart, transit_entries_400m, radius_m, "
            " transit_entries_window, transit_entries_snap, profile_run_at) "
            "SELECT address_id, borough, day_type, daypart, transit_entries_400m, "
            "       radius_m, transit_entries_window, transit_entries_snap, "
            "       profile_run_at FROM _prof")
        reset = ", ".join(f"{c} = NULL" for c in PROFILE_ADDRESS_COLUMNS)
        if boroughs:
            con.execute(
                f"UPDATE analysis.address SET {reset} "
                f"WHERE borough IN ({', '.join('?' for _ in boroughs)})", list(boroughs))
        else:
            con.execute(f"UPDATE analysis.address SET {reset}")
        sets = ", ".join(f"{c} = _sh.{c}" for c in PROFILE_ADDRESS_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address AS a SET {sets}
            FROM _sh WHERE a.address_id = _sh.address_id
        """)
        # An address with a reachable entrance but no pm_peak entries keeps a
        # NULL share and a non-NULL run_at: the run happened, the ratio does
        # not exist. Stamp run_at on every in-scope address so "has this been
        # re-applied since the last screen re-run" is answerable.
        if boroughs:
            con.execute(
                f"UPDATE analysis.address SET transit_profile_run_at = ? "
                f"WHERE borough IN ({', '.join('?' for _ in boroughs)})",
                [run_at, *boroughs])
        else:
            con.execute("UPDATE analysis.address SET transit_profile_run_at = ?",
                        [run_at])
    finally:
        for v in ("_ent", "_prof", "_sh"):
            con.unregister(v)
    return {"address_entrance_rows": int(len(ent)),
            "address_transit_profile_rows": int(len(prof)),
            "addresses_with_share": int(sh["transit_am_pm_share_400m"].notna().sum())}


# ------------------------------------------------------------- the read-back

VALIDATION_SQL = """
-- Proves on the WAREHOUSE (not on the frame this run built):
--   1. every profile row belongs to an address that exists;
--   2. every address with rows has exactly 15 of them (3 day types x 5
--      dayparts) -- a missing cell would read as a zero hour that was never
--      measured;
--   3. the five WEEKDAY dayparts re-sum to analysis.address.transit_entries_400m,
--      the invariant that keeps the single-number column and the profile from
--      diverging;
--   4. an address ABSENT from the profile has transit_entries_400m = 0 -- the
--      sparse table is not dropping anyone.
WITH wd AS (
    SELECT address_id, sum(transit_entries_400m) AS rebuilt
    FROM analysis.address_transit_profile
    WHERE day_type = 'weekday'
    GROUP BY 1
), cells AS (
    SELECT address_id, count(*) AS n_cells
    FROM analysis.address_transit_profile GROUP BY 1
)
SELECT a.borough,
       count(*)                                                   AS addresses,
       count(wd.address_id)                                       AS in_profile,
       sum(CASE WHEN wd.address_id IS NULL AND a.transit_entries_400m > 0
                THEN 1 ELSE 0 END)                                AS absent_but_nonzero,
       sum(CASE WHEN cells.n_cells IS NOT NULL AND cells.n_cells <> 15
                THEN 1 ELSE 0 END)                                AS wrong_cell_count,
       max(abs(COALESCE(wd.rebuilt, 0) - a.transit_entries_400m)) AS max_abs_diff,
       round(sum(a.transit_entries_400m))                         AS stored_total,
       round(sum(COALESCE(wd.rebuilt, 0)))                        AS rebuilt_total,
       count(a.transit_am_pm_share_400m)                          AS have_share,
       round(median(a.transit_am_pm_share_400m), 3)               AS med_share,
       count(*) FILTER (WHERE a.transit_profile_run_at IS NULL)   AS never_run
FROM analysis.address a
LEFT JOIN wd    ON wd.address_id = a.address_id
LEFT JOIN cells ON cells.address_id = a.address_id
WHERE a.access_run_at IS NOT NULL
GROUP BY ROLLUP(a.borough)
ORDER BY a.borough NULLS LAST
"""


# ---------------------------------------------------------------- the build

def build_transit_profile(
    con,
    boroughs: list[str] | None,
    radius_m: float = DEFAULT_RADIUS_M,
    graph_path: pathlib.Path = GRAPH_PATH,
    months: int = 3,
    use_entrances: bool = True,
    refresh: bool = False,
    reachable: pd.DataFrame | None = None,
    dry_run: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(long profile frame, reachable frame, report).

    `reachable` short-circuits the Dijkstra sweep: pass the frame recovered
    from `analysis.address_entrance` and the whole rebuild is weights and SQL.
    That is the entire reason that table exists.
    """
    from loci.sources.cities.nyc import mta_ridership as mr

    profile, entrances, prep = mr.build_profile(
        months=months, use_entrances=use_entrances, refresh=refresh)

    if reachable is None:
        reachable, rrep = build_reachable(
            con, boroughs, entrances, radius_m=radius_m, graph_path=graph_path)
        rrep["source"] = "dijkstra sweep"
    else:
        known = {e["entrance_id"] for e in entrances}
        unknown = sorted(set(reachable["entrance_id"]) - known)
        if unknown:
            raise RuntimeError(
                f"{len(unknown)} entrance_ids in the persisted reachable set are not "
                f"in the current entrance feed ({unknown[:3]}) -- i9wp-a4ja has moved "
                f"or renamed doors, so the persisted distances no longer describe the "
                f"door set being weighted. Re-run the sweep.")
        rrep = {"boroughs": list(boroughs) if boroughs else "ALL",
                "radius_m": float(radius_m), "pairs": int(len(reachable)),
                "addresses_with_an_entrance": int(reachable["address_id"].nunique()),
                "entrance_points": len(entrances), "source": "analysis.address_entrance"}

    weights = entrance_weights(profile, entrances)
    long_df = profile_long(reachable, weights)
    shares = am_pm_share_frame(long_df)
    rebuilt = check_rebuilds_the_daily_total(con, long_df, boroughs)

    run_at = dt.datetime.now()
    meta = {"run_at": run_at, "radius_m": float(radius_m),
            "graph_version": rrep.get("graph_version", graph_version(graph_path)),
            "window": f"{prep['window_start']}..{prep['window_end']}",
            "snap": prep["snap"]}
    report = {**rrep, "transit": prep, "window": meta["window"], "snap": meta["snap"],
              "profile_rows": int(len(long_df)),
              "run_at": run_at.isoformat(timespec="seconds"),
              "conservation": prep["conservation"], "rebuild": rebuilt}
    if not dry_run:
        report["_written"] = write_profile(
            con, reachable, long_df, shares, boroughs, meta)
    return long_df, reachable, report


def load_reachable(con, boroughs: list[str] | None) -> pd.DataFrame | None:
    """The persisted reachable set for `boroughs`, or None if it is absent or
    partial. Partial counts as absent: a half-populated scope would silently
    zero every address the previous run did not cover."""
    try:
        where, params = "", []
        if boroughs:
            where = f"WHERE borough IN ({', '.join('?' for _ in boroughs)})"
            params = list(boroughs)
        df = con.execute(
            f"SELECT address_id, borough, entrance_id, complex_id, dist_m "
            f"FROM analysis.address_entrance {where}", params).fetchdf()
    except Exception:
        return None
    if df.empty:
        return None
    return df
