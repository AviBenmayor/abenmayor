"""Development-pipeline exposure at ADDRESS grain (D38/D56/D61).

Reads analysis.dev_pipeline (one row per DOB job, sql/011_dev_pipeline.sql) and
writes fourteen columns onto analysis.address by UPDATE:

    units_permitted_400m / _800m            coming: permitted, not yet occupied
    units_completed_24mo_400m / _800m       arrived: CO in the last 24 months
    units_completed_60mo_400m / _800m       arrived: CO in the last 60 months
    nearest_large_project_{id,m,units,stage,date}   the nearest net>=50 job
    pipeline_asof                           the run date the windows count back from
    units_active_400m                       of the permitted: permit live/renewed
    units_stalled_400m                      of the permitted: permit dead >12 mo

THE ACTIVITY SPLIT (D62 caveats 3 and 9, sql/014_dev_pipeline_activity.sql)
---------------------------------------------------------------------------
`units_permitted_400m` mixes "800 neighbours arriving in 18 months" with "800
neighbours who have not arrived since 2017" -- 23% of permitted units citywide
sit behind permits older than five years that never produced a CO. The last two
columns split it using analysis.dev_pipeline.activity_status, which
`loci pipeline-activity` derives from the DOB permit-renewal record.

They are NOT a partition: active + stalled <= permitted, because `lapsed` and
`n/a` units are in the permitted total and in neither column. Never add the
three. And when no activity evidence has been ingested they are written NULL,
never 0 -- see activity_weights().

WHY analysis.address AND NOT analysis.address_category
------------------------------------------------------
Pipeline exposure is CATEGORY-INDEPENDENT. A 400-unit building rising two
blocks away brings the same households whether the address's lead gap is
laundry or a pharmacy; there is no per-category variation to store, so putting
these on address_category would write 15 identical copies of every number --
11.5M rows to say 767k things. That is exactly the pivot-shaped duplication
D61 removed. The category-specific reading ("those households need a laundromat
and the nearest is 900 m away") is a JOIN at query time, not a stored column.

NON-FILTERING GUARANTEE (mirrors model/address_demand.py, D57/D58)
------------------------------------------------------------------
`write_pipeline` issues ONLY `UPDATE analysis.address SET <PIPELINE_COLUMNS>`.
It never INSERTs, never DELETEs, and PIPELINE_COLUMNS is asserted disjoint from
ADDRESS_SCREEN_COLUMNS by tests/test_dev_pipeline.py. Nothing computed here can
move gap_score, lead_category, n_missing, eligible or cluster_id. A block about
to gain 800 residents does not become a gap, and a block with no pipeline does
not stop being one -- the pipeline is an annotation on the screen, in the same
sense D48 makes leads graded rather than filtered.

THE SPATIAL METHOD -- reused, not re-implemented
------------------------------------------------
Same engine as the gap screen's nearest_m: `score/access._prune` +
`_to_csr` build one undirected CSR walk graph (that function's comment on NOT
mirroring edges manually is the bug this project has already been bitten by --
csr_matrix SUMS duplicate (row, col) entries, which doubles every length), then
scipy Dijkstra, then each address reads off its own nearest graph node --
`ox.distance.nearest_nodes`, exactly as model/conveniences.py and
model/address_gaps.py do.

Two passes, both bounded:

  1. SUMS. Dijkstra is sourced FROM THE JOBS, not from the addresses. A
     multi-source `min_only` pass gives each node its distance to the NEAREST
     job, which is the wrong quantity -- these measures are SUMS. So each batch
     of ~64 job nodes gets its own row of the distance matrix, and the units are
     accumulated onto every node inside the radius. Sourcing from ~10k jobs is
     two orders of magnitude cheaper than sourcing from 282k addresses, and one
     pass at the 800 m limit yields both radii by masking.
  2. NEAREST LARGE PROJECT. One `min_only=True, return_predecessors=True` pass
     over the >=50-unit jobs; scipy's `sources` array names the winning source
     node directly. Right-censored at DIST_LIMIT (2400 m), the same cap
     nearest_m uses, so the two distances are comparable.

A job with no coordinate is dropped from the spatial measures EXPLICITLY (and
counted in the report) rather than vanishing into a NULL geom.

DOUBLE-COUNT WATCH. One DOB job = one point = one contribution. A job whose
units are counted in `units_permitted` is by construction not in either
completed window (stage is a partition), but the 24-month window IS a subset of
the 60-month window -- 24mo and 60mo must never be added together. Jobs sharing
a graph node contribute independently and correctly (the accumulator is a sum
over jobs, not over nodes).
"""
from __future__ import annotations

import datetime as dt
import pathlib

import numpy as np
import osmnx as ox
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from loci.model.conveniences import graph_version
from loci.score.access import DIST_LIMIT, MIN_COMPONENT, THRESHOLDS, _prune, _to_csr
from loci.score.walkgraph import OUT as GRAPH_PATH

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
INTERIM_DIR = REPO_ROOT / "data" / "interim"

#: 5-minute walk. THRESHOLDS[5] is the project's tightest reach tier; the
#: pipeline radius is pinned to it rather than to a new constant so "within a
#: 5-minute walk" means one distance everywhere in the project.
DEFAULT_RADIUS_M = THRESHOLDS[5]      # 400.0
WIDE_RADIUS_M = THRESHOLDS[10]        # 800.0

#: A "large project" -- the one a leasing decision would actually be made
#: against. A QUERY threshold, never an ingest threshold: analysis.dev_pipeline
#: holds every job with net_units >= 1.
LARGE_UNITS = 50

#: Completion look-back windows, in months.
RECENT_MONTHS = (24, 60)

BATCH = 64   # job nodes per Dijkstra call; (BATCH, n_nodes) float64 is the peak

#: Activity measures are emitted at the TIGHT radius ONLY. The question they
#: answer -- "are the neighbours I am underwriting actually coming?" -- is a
#: 5-minute-walk question; a stalled tower 800 m away is not a leasing input,
#: and two more columns on 767k rows to say so is the pivot-shaped duplication
#: D61 removed. Labels in this set get no `_800m` twin.
TIGHT_ONLY_LABELS = ("active", "stalled")

#: The ONLY columns write_pipeline may name in a SET clause.
PIPELINE_COLUMNS = [
    "units_permitted_400m", "units_permitted_800m",
    "units_completed_24mo_400m", "units_completed_24mo_800m",
    "units_completed_60mo_400m", "units_completed_60mo_800m",
    "nearest_large_project_id", "nearest_large_project_m",
    "nearest_large_project_units", "nearest_large_project_stage",
    "nearest_large_project_date", "pipeline_asof",
    # D62 caveats 3/9, sql/014_dev_pipeline_activity.sql. NOT a partition of
    # units_permitted_400m: active + stalled <= permitted, because `lapsed`
    # and `n/a` units are in the permitted total and in neither of these.
    "units_active_400m", "units_stalled_400m",
]

#: analysis.address's screen-owned columns (model/address_gaps.ADDRESS_COLUMNS).
#: PIPELINE_COLUMNS must stay disjoint from this; the test pins it.
ADDRESS_SCREEN_COLUMNS = [
    "address_id", "bbl", "lon", "lat", "units", "units_capped",
    "nta_code", "neighborhood", "borough", "h3_index",
    "present_count", "eligible", "gap_score", "lead_category",
    "lead_excess_m", "n_missing", "cluster_id",
    "reach_source", "reach_hash", "graph_version",
    "supply_set", "supply_hash", "run_at",
]

#: Stages whose units are "coming": permitted or actively building, not
#: occupied. `withdrawn` is excluded -- 259 MN+BK jobs were permitted and then
#: withdrawn; a permitted unit is not a delivered unit. `filed` is excluded
#: because a filing is not a commitment and the 18-month question is about
#: buildings that will actually top out.
PERMITTED_STAGES = ("permitted", "partially_complete")


def _months_before(asof: dt.date, months: int) -> dt.date:
    """asof minus `months` calendar months, clamped to a valid day-of-month."""
    total = asof.month - 1 - months
    year = asof.year + total // 12
    month = total % 12 + 1
    day = min(asof.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.date(year, month, day)


# --------------------------------------------------------------- read side

def load_projects(con, boroughs: list[str]) -> pd.DataFrame:
    """analysis.dev_pipeline rows in scope, net_units >= 1, withdrawn dropped.

    net_units >= 1 is the measure's filter, not the table's: demolitions and
    down-converting alterations carry net_units < 0 and are ingested, but
    "units arriving near this address" is not a net-of-demolition quantity on
    the timescale of a lease -- a demolition three blocks away does not cancel
    a tower next door. The sql/011 header carries this as caveat 4.
    """
    holes = ", ".join("?" for _ in boroughs)
    return con.execute(f"""
        SELECT job_number, borough, stage, net_units,
               date_filed, date_permitted, date_complete, co_type,
               activity_status,
               neighborhood,
               ST_X(geom) AS lon, ST_Y(geom) AS lat
        FROM analysis.dev_pipeline
        WHERE borough IN ({holes})
          AND net_units >= 1
          AND stage <> 'withdrawn'
        ORDER BY job_number
    """, list(boroughs)).fetchdf()


def weight_matrix(projects: pd.DataFrame, asof: dt.date) -> tuple[np.ndarray, list[str]]:
    """(3, n_projects) unit weights: permitted, completed-24mo, completed-60mo.

    The three rows are NOT mutually exclusive: 24mo is a strict subset of 60mo
    by construction, so a caller must never add those two columns. Permitted is
    disjoint from both (stage partitions the jobs)."""
    units = projects["net_units"].to_numpy(dtype=np.float64)
    stage = projects["stage"].to_numpy()
    complete = stage == "complete"
    dc = pd.to_datetime(projects["date_complete"], errors="coerce")

    rows = [np.where(np.isin(stage, PERMITTED_STAGES), units, 0.0)]
    labels = ["permitted"]
    for months in RECENT_MONTHS:
        cutoff = pd.Timestamp(_months_before(asof, months))
        inwin = complete & dc.notna().to_numpy() & (dc >= cutoff).to_numpy()
        rows.append(np.where(inwin, units, 0.0))
        labels.append(f"completed_{months}mo")
    return np.vstack(rows), labels


def activity_weights(projects: pd.DataFrame) -> tuple[np.ndarray | None, list[str]]:
    """(2, n_projects) unit weights for the CONSTRUCTION-PROGRESS split, or
    (None, []) when analysis.dev_pipeline carries no activity evidence yet.

    Returns weights for `active` and `stalled` restricted to PERMITTED_STAGES,
    so both are strict subsets of the `permitted` row of weight_matrix(). They
    do NOT sum to it: a job whose activity_status is 'lapsed' (expired 0-12
    months) or 'n/a' (no permit row matched) is in the permitted total and in
    neither of these. Adding active + stalled + permitted triple-counts.

    THE NULL CASE IS THE POINT. `loci pipeline` must run before, after, or
    without `loci pipeline-activity`. When the column is absent or entirely
    NULL this returns None and the caller writes NULL into both address
    columns -- never 0, because "we have not looked" and "every nearby
    building is abandoned" are different claims and the screen must not
    conflate them.
    """
    if "activity_status" not in projects.columns:
        return None, []
    status = projects["activity_status"]
    if status.isna().all():
        return None, []
    units = projects["net_units"].to_numpy(dtype=np.float64)
    permitted = np.isin(projects["stage"].to_numpy(), PERMITTED_STAGES)
    rows = [np.where(permitted & (status == label).to_numpy(), units, 0.0)
            for label in TIGHT_ONLY_LABELS]
    return np.vstack(rows), list(TIGHT_ONLY_LABELS)


# ------------------------------------------------------------- the engine

def node_pipeline_matrix(G, projects: pd.DataFrame, W: np.ndarray,
                         radii: tuple[float, float] = (DEFAULT_RADIUS_M, WIDE_RADIUS_M),
                         min_component: int = MIN_COMPONENT):
    """Per-NODE pipeline sums and nearest-large-project, on a pruned walk graph.

    Returns (idx, acc, near) where
      idx  : {osmid -> node index}
      acc  : {radius_m: (3, n_nodes) unit sums, in W's row order}
      near : (dist[n_nodes], src_pos[n_nodes]) -- network metres to the nearest
             large project and its POSITION in `projects`, censored at
             DIST_LIMIT with src_pos = -1 where nothing is reachable.

    Pure-ish: takes a graph and a frame, touches no database and no cache, so
    tests exercise it on a tiny synthetic graph.
    """
    G = _prune(G, min_component)
    A, idx = _to_csr(G)
    n_nodes = A.shape[0]
    rmax = float(max(radii))

    geo = projects["lon"].notna().to_numpy() & projects["lat"].notna().to_numpy()
    pos = np.flatnonzero(geo)
    acc = {r: np.zeros((W.shape[0], n_nodes), dtype=np.float64) for r in radii}
    near_d = np.full(n_nodes, float(DIST_LIMIT))
    near_p = np.full(n_nodes, -1, dtype=np.int64)
    if pos.size == 0:
        return idx, acc, (near_d, near_p)

    nodes = ox.distance.nearest_nodes(
        G,
        X=projects["lon"].to_numpy()[pos].tolist(),
        Y=projects["lat"].to_numpy()[pos].tolist(),
    )
    nidx = np.array([idx[n] for n in np.atleast_1d(nodes)], dtype=np.int64)

    # ---- pass 1: catchment sums, sourced FROM the jobs
    Wg = W[:, pos]                                   # (3, n_geo)
    for s in range(0, nidx.size, BATCH):
        chunk = nidx[s:s + BATCH]
        D = dijkstra(A, directed=False, indices=chunk, limit=rmax)   # (b, n_nodes)
        Wb = Wg[:, s:s + BATCH]
        for r in radii:
            acc[r] += Wb @ (D <= r).astype(np.float64)

    # ---- pass 2: nearest LARGE project, one min_only pass
    big = np.flatnonzero(projects["net_units"].to_numpy()[pos] >= LARGE_UNITS)
    if big.size:
        # Several large jobs can snap to one graph node. scipy's `sources`
        # names the NODE, so a node hosting more than one job is resolved to
        # the LARGEST of them -- stated here rather than left to whichever row
        # np.unique happened to keep.
        order = np.argsort(-projects["net_units"].to_numpy()[pos][big], kind="stable")
        node_owner: dict[int, int] = {}
        for b in big[order]:
            node_owner.setdefault(int(nidx[b]), int(pos[b]))
        src = np.array(sorted(node_owner), dtype=np.int64)
        d, _pred, sources = dijkstra(A, directed=False, indices=src, min_only=True,
                                     limit=float(DIST_LIMIT), return_predecessors=True)
        ok = np.isfinite(d)
        near_d = np.where(ok, d, float(DIST_LIMIT))
        owner = np.array([node_owner.get(int(s0), -1) for s0 in np.maximum(sources, 0)])
        near_p = np.where(ok & (sources >= 0), owner, -1)

    return idx, acc, (near_d, near_p)


def compute_pipeline(con, boroughs: list[str], asof: dt.date | None = None,
                     graph_path: pathlib.Path = GRAPH_PATH,
                     radius_m: float = DEFAULT_RADIUS_M) -> tuple[pd.DataFrame, dict]:
    """(frame of address_id/borough + PIPELINE_COLUMNS, report). READ-ONLY on
    analysis.address -- it selects address_id, borough, lon, lat and nothing else."""
    import pickle

    asof = asof or dt.date.today()
    radii = (float(radius_m), float(WIDE_RADIUS_M))
    if radii[0] > radii[1]:
        radii = (radii[1], radii[0])

    projects = load_projects(con, boroughs)
    if projects.empty:
        raise RuntimeError(
            f"dev_pipeline: analysis.dev_pipeline has no rows for {boroughs}. "
            f"Run `loci ingest-dcp-housing` first -- writing zeros onto every "
            f"address would read as 'nothing is being built anywhere', which is "
            f"a confident false negative, not a missing value."
        )
    W, labels = weight_matrix(projects, asof)
    Wa, alabels = activity_weights(projects)
    if Wa is not None:
        W = np.vstack([W, Wa])
        labels = labels + alabels

    holes = ", ".join("?" for _ in boroughs)
    addr = con.execute(
        f"SELECT address_id, borough, lon, lat FROM analysis.address "
        f"WHERE borough IN ({holes}) ORDER BY borough, address_id", list(boroughs)
    ).fetchdf()

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    idx, acc, (near_d, near_p) = node_pipeline_matrix(Gp, projects, W, radii=radii,
                                                      min_component=0)

    anodes = ox.distance.nearest_nodes(Gp, X=addr["lon"].tolist(), Y=addr["lat"].tolist())
    anidx = np.array([idx[n] for n in np.atleast_1d(anodes)], dtype=np.int64)

    out = pd.DataFrame({"address_id": addr["address_id"], "borough": addr["borough"]})
    tight, wide = radii
    for li, label in enumerate(labels):
        out[f"units_{label}_{int(tight)}m"] = acc[tight][li][anidx].round().astype("int64")
        if label not in TIGHT_ONLY_LABELS:
            out[f"units_{label}_{int(wide)}m"] = acc[wide][li][anidx].round().astype("int64")
    if Wa is None:
        # No activity evidence in analysis.dev_pipeline: NULL, never 0.
        for label in TIGHT_ONLY_LABELS:
            out[f"units_{label}_{int(tight)}m"] = pd.Series(
                [pd.NA] * len(out), index=out.index, dtype="Int64")

    p = near_p[anidx]
    has = p >= 0
    cols = projects.iloc[np.maximum(p, 0)].reset_index(drop=True)
    out["nearest_large_project_id"] = np.where(has, cols["job_number"], None)
    out["nearest_large_project_m"] = np.where(has, near_d[anidx], np.nan)
    out["nearest_large_project_units"] = pd.Series(
        np.where(has, cols["net_units"], np.nan)).astype("Int64")
    out["nearest_large_project_stage"] = np.where(has, cols["stage"], None)
    ndate = pd.to_datetime(cols["date_complete"]).fillna(
        pd.to_datetime(cols["date_permitted"])).fillna(pd.to_datetime(cols["date_filed"]))
    out["nearest_large_project_date"] = pd.Series(ndate).where(pd.Series(has))
    out["pipeline_asof"] = asof

    report = {
        "asof": asof.isoformat(),
        "radii_m": list(radii),
        "projects": len(projects),
        "projects_no_geom": int(projects["lon"].isna().sum()),
        "large_projects": int((projects["net_units"] >= LARGE_UNITS).sum()),
        "addresses": len(addr),
        "units_by_measure": {lab: float(W[i].sum()) for i, lab in enumerate(labels)},
        "addresses_with_large_project": int(has.sum()),
        "activity_evidence": Wa is not None,
    }
    return out, report


# -------------------------------------------------------------- write side

def write_pipeline(con, df: pd.DataFrame, boroughs: list[str]) -> int:
    """UPDATE-only annotation of analysis.address (see the module docstring's
    non-filtering note). Two passes, both UPDATE:

      1. RESET every in-scope row's PIPELINE_COLUMNS to NULL. Without this, an
         address that had a permitted project nearby on the last run and does
         not on this one (the job completed, or DCP restated it away) would
         keep last run's number forever -- UPDATE has no DELETE to fall back on.
      2. UPDATE ... FROM the computed frame on (address_id, borough).

    `boroughs` is passed explicitly rather than inferred from `df`, so an
    empty-frame run still resets instead of leaving stale annotations behind.
    """
    if not boroughs:
        return 0
    overlap = sorted(set(PIPELINE_COLUMNS) & set(ADDRESS_SCREEN_COLUMNS))
    if overlap:   # belt and braces; the test is the real guard
        raise RuntimeError(f"dev_pipeline would clobber screen columns: {overlap}")
    holes = ", ".join("?" for _ in boroughs)
    reset = ", ".join(f"{c} = NULL" for c in PIPELINE_COLUMNS)
    con.execute(f"UPDATE analysis.address SET {reset} WHERE borough IN ({holes})",
                list(boroughs))
    if df.empty:
        return 0
    absent = [c for c in PIPELINE_COLUMNS if c not in df.columns]
    if absent:
        raise RuntimeError(
            f"dev_pipeline: the computed frame is missing {absent}. Every column "
            f"in PIPELINE_COLUMNS is reset to NULL above, so a partial frame would "
            f"leave those addresses blank rather than raising -- which reads as "
            f"'no development near here'. Emit the column (NULL is fine) or drop "
            f"it from PIPELINE_COLUMNS."
        )
    con.register("_pl", df)
    try:
        sets = ", ".join(f"{c} = _pl.{c}" for c in PIPELINE_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address AS a
            SET {sets}
            FROM _pl
            WHERE a.address_id = _pl.address_id AND a.borough = _pl.borough
        """)
    finally:
        con.unregister("_pl")
    return len(df)


def build_pipeline(con, boroughs: list[str], asof: dt.date | None = None,
                   radius_m: float = DEFAULT_RADIUS_M,
                   graph_path: pathlib.Path = GRAPH_PATH,
                   dry_run: bool = False) -> tuple[pd.DataFrame, dict]:
    df, report = compute_pipeline(con, boroughs, asof=asof, graph_path=graph_path,
                                  radius_m=radius_m)
    report["graph_version"] = graph_version(graph_path)
    if not dry_run:
        report["_written"] = write_pipeline(con, df, boroughs)
    return df, report
