"""Storefront-vacancy exposure at ADDRESS grain (D38/D56/D61).

Reads analysis.storefront (one row per storefront per filing,
sql/012_storefront_registry.sql) and writes seven columns onto
analysis.address by UPDATE:

    vacant_storefronts_400m           vacant on the snapshot's 12/31, within 400 m
    storefronts_400m                  every registered storefront in the same
                                      filing, within 400 m -- the DENOMINATOR
    nearest_vacant_storefront_m       network metres to the nearest vacant one
    nearest_vacant_storefront_id      its storefront_id (join with storefront_asof)
    nearest_vacant_storefront_business its last reported primary_business_activity
    nearest_vacant_lease_expired      its lease expiry is before `asof` (see below)
    storefront_asof                   the observation date the snapshot is taken at

WHY analysis.address AND NOT analysis.address_category
------------------------------------------------------
A vacant ground floor is CATEGORY-INDEPENDENT. The same empty storefront is
the place a laundromat, a pharmacy or a bodega could go; there is no
per-category variation to store, so putting these on address_category would
write 15 identical copies of every number -- 11.5M rows to say 767k things.
That is exactly the pivot-shaped duplication D61 removed. The category reading
("the lead gap here is laundry AND there is an empty ground floor 120 m away")
is a JOIN at query time, not a stored column.

NON-FILTERING GUARANTEE (mirrors model/dev_pipeline.py, D57/D58/D62)
--------------------------------------------------------------------
`write_storefronts` issues ONLY `UPDATE analysis.address SET
<STOREFRONT_COLUMNS>`. It never INSERTs, never DELETEs, and STOREFRONT_COLUMNS
is asserted disjoint from ADDRESS_SCREEN_COLUMNS, from D62's PIPELINE_COLUMNS
and from D63's AGE_FIT_COLUMNS by tests/test_storefront_registry.py. Nothing
computed here can move gap_score, lead_category, n_missing, eligible or
cluster_id. A block with an empty ground floor does not become a gap; a gap
block with no vacancy does not stop being one. Vacancy is an ACTIONABILITY
annotation on a graded screen (D48), never a filter.

THE SPATIAL METHOD -- reused, not re-implemented
------------------------------------------------
Same engine as the gap screen's nearest_m and the pipeline's catchments:
`score/access._prune` + `_to_csr` build one undirected CSR walk graph (that
function's comment on NOT mirroring edges manually is the bug this project has
already been bitten by -- csr_matrix SUMS duplicate (row, col) entries, which
doubles every length), then scipy Dijkstra, then each address reads off its own
nearest graph node via `ox.distance.nearest_nodes`, exactly as
model/conveniences.py, model/address_gaps.py and model/dev_pipeline.py do.

Two passes, both bounded:

  1. COUNTS. Dijkstra is sourced FROM THE STOREFRONTS, not from the addresses.
     A multi-source `min_only` pass would give each node its distance to the
     NEAREST storefront, which is the wrong quantity -- these are COUNTS. So
     each batch of ~64 storefront nodes gets its own row of the distance
     matrix and its weights are accumulated onto every node inside the radius.
     Sourcing from ~20k storefronts is an order of magnitude cheaper than
     sourcing from 282k addresses.
  2. NEAREST VACANT. One `min_only=True, return_predecessors=True` pass over
     the vacant storefronts; scipy's `sources` array names the winning source
     node directly. Right-censored at DIST_LIMIT (2400 m), the same cap
     nearest_m and nearest_large_project_m use, so the three are comparable.

DOUBLE-COUNT WATCH. One filing row = one storefront = one contribution, and the
snapshot is a SINGLE filing date, so a premises that filed in seven years
contributes exactly once. Several storefronts at one premises snap to the same
graph node and are counted separately, which is correct: the accumulator sums
over STOREFRONTS, not over nodes. Nothing here is ever deduplicated -- see
sql/012's dedup block for why fusing identical rows would delete real ground
floors.

WHAT `nearest_vacant_lease_expired` CAN AND CANNOT SAY
-----------------------------------------------------
It is `lease_expiry < asof` on the nearest vacant storefront's OWN filing row,
and NULL when that row reported no lease -- never FALSE. On the default
2024-12-31 snapshot that is most of them: DOF published the lease field on
38,785 of 38,866 MN+BK rows in the 2024-06-03 filing and then stopped, leaving
71 of 38,318 on 2025-06-03 (sql/012 caveat 5). `--asof 2023-12-31` is the
lease-complete view, one year staler. No lease is ever carried between rows to
fill the gap: two storefronts at one premises are not interchangeable, and
guessing which lease belongs to which would be the fusion bug wearing a
coalesce.
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

#: 5-minute walk. THRESHOLDS[5] is the project's tightest reach tier; pinned to
#: it rather than to a new constant so "within a 5-minute walk" means one
#: distance everywhere in the project (D62 pinned the pipeline radius the same
#: way).
DEFAULT_RADIUS_M = THRESHOLDS[5]      # 400.0

BATCH = 64   # storefront nodes per Dijkstra call; (BATCH, n_nodes) float64 is the peak

#: The ONLY columns write_storefronts may name in a SET clause.
STOREFRONT_COLUMNS = [
    "vacant_storefronts_400m",
    "storefronts_400m",
    "nearest_vacant_storefront_m",
    "nearest_vacant_storefront_id",
    "nearest_vacant_storefront_business",
    "nearest_vacant_lease_expired",
    "storefront_asof",
]

#: analysis.address's screen-owned columns (model/address_gaps.ADDRESS_COLUMNS).
ADDRESS_SCREEN_COLUMNS = [
    "address_id", "bbl", "lon", "lat", "units", "units_capped",
    "nta_code", "neighborhood", "borough", "h3_index",
    "present_count", "eligible", "gap_score", "lead_category",
    "lead_excess_m", "n_missing", "cluster_id",
    "reach_source", "reach_hash", "graph_version",
    "supply_set", "supply_hash", "run_at",
    "lead_censored",          # D75, appended
]

#: D63's age-fit annotation columns at analysis.address grain
#: (model/age_fit.py). STOREFRONT_COLUMNS must stay disjoint from these too;
#: the test pins all three sets together.
AGE_FIT_COLUMNS = ["age_fit_lead", "age_fit_lead_moe", "gap_score_fit"]


# --------------------------------------------------------------- read side

def snapshot_filing(con, boroughs: list[str], asof: dt.date) -> tuple[dt.date, str] | None:
    """The ONE filing the snapshot reads: (filing_due_date, universe).

    TWO FILINGS SHARE AN OBSERVATION DATE and they must never be pooled. The
    2025-06-03 annual filing and the 2025-02-15 vacant-only supplement BOTH
    observe 2024-12-31, and a premises that filed the supplement also appears
    in the annual file -- as vacant, in both. Selecting on `observed_1231`
    alone counts those storefronts twice and lifts the MN+BK vacancy rate from
    9.94% to 13.79%: the double-count bug CLAUDE.md warns about, with a
    plausible-looking number as its output.

    So: the FULL-universe filing at `asof` wins, because it carries a
    denominator. If none exists at that date (the 2025-12-31 and 2025-06-30
    observations are supplement-only), the supplement is used and the caller is
    told, so `storefronts_400m` is not mistaken for a universe count.
    """
    holes = ", ".join("?" for _ in boroughs)
    row = con.execute(f"""
        SELECT filing_due_date, universe
        FROM analysis.storefront
        WHERE borough IN ({holes}) AND observed_1231 = ?
        GROUP BY filing_due_date, universe
        ORDER BY (universe = 'full') DESC, filing_due_date DESC
        LIMIT 1
    """, [*boroughs, asof]).fetchone()
    return (row[0], row[1]) if row else None


def load_storefronts(con, boroughs: list[str], asof: dt.date) -> pd.DataFrame:
    """The snapshot: every analysis.storefront row from the ONE filing
    `snapshot_filing` selects, in scope, with a coordinate.

    One filing, so a premises that has filed in seven years appears exactly
    once and no catchment count can double it. Rows with no geometry are
    dropped HERE, explicitly and countably, rather than vanishing into a NULL
    later.
    """
    pick = snapshot_filing(con, boroughs, asof)
    if pick is None:
        return pd.DataFrame(columns=[
            "storefront_id", "premises_id", "borough", "address", "unit",
            "universe", "reporting_year", "observed_1231", "vacant",
            "construction_reported", "primary_business_activity",
            "lease_expiry", "lon", "lat"])
    holes = ", ".join("?" for _ in boroughs)
    return con.execute(f"""
        SELECT storefront_id, premises_id, borough, address, unit,
               universe, reporting_year, observed_1231,
               COALESCE(vacant_1231, FALSE) AS vacant,
               construction_reported,
               primary_business_activity, lease_expiry,
               ST_X(geom) AS lon, ST_Y(geom) AS lat
        FROM analysis.storefront
        WHERE borough IN ({holes})
          AND filing_due_date = ?
          AND geom IS NOT NULL
        ORDER BY storefront_id
    """, [*boroughs, pick[0]]).fetchdf()


def weight_matrix(storefronts: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """(2, n) storefront weights: vacant, all.

    `all` is the DENOMINATOR and is deliberately every registered storefront in
    the snapshot, vacant or not -- without it "0 vacant within 400 m" cannot be
    told apart from "nobody near here filed" (sql/012 caveat 1). The two rows
    are NESTED, not disjoint: vacant is a subset of all, so they must never be
    added.
    """
    vacant = storefronts["vacant"].fillna(False).to_numpy(dtype=bool)
    return (np.vstack([vacant.astype(np.float64), np.ones(len(storefronts))]),
            ["vacant_storefronts", "storefronts"])


# ------------------------------------------------------------- the engine

def node_storefront_matrix(G, storefronts: pd.DataFrame, W: np.ndarray,
                           radius_m: float = DEFAULT_RADIUS_M,
                           min_component: int = MIN_COMPONENT):
    """Per-NODE storefront counts and nearest-vacant, on a pruned walk graph.

    Returns (idx, acc, near) where
      idx  : {osmid -> node index}
      acc  : (2, n_nodes) counts in W's row order
      near : (dist[n_nodes], src_pos[n_nodes]) -- network metres to the nearest
             VACANT storefront and its POSITION in `storefronts`, censored at
             DIST_LIMIT with src_pos = -1 where nothing is reachable.

    Pure-ish: takes a graph and a frame, touches no database and no cache, so
    tests exercise it on a tiny synthetic line graph where every distance is
    known by construction.
    """
    G = _prune(G, min_component)
    A, idx = _to_csr(G)
    n_nodes = A.shape[0]

    acc = np.zeros((W.shape[0], n_nodes), dtype=np.float64)
    near_d = np.full(n_nodes, float(DIST_LIMIT))
    near_p = np.full(n_nodes, -1, dtype=np.int64)

    geo = storefronts["lon"].notna().to_numpy() & storefronts["lat"].notna().to_numpy()
    pos = np.flatnonzero(geo)
    if pos.size == 0:
        return idx, acc, (near_d, near_p)

    nodes = ox.distance.nearest_nodes(
        G,
        X=storefronts["lon"].to_numpy()[pos].tolist(),
        Y=storefronts["lat"].to_numpy()[pos].tolist(),
    )
    nidx = np.array([idx[n] for n in np.atleast_1d(nodes)], dtype=np.int64)

    # ---- pass 1: catchment counts, sourced FROM the storefronts
    Wg = W[:, pos]
    for s in range(0, nidx.size, BATCH):
        chunk = nidx[s:s + BATCH]
        D = dijkstra(A, directed=False, indices=chunk, limit=float(radius_m))
        acc += Wg[:, s:s + BATCH] @ (D <= radius_m).astype(np.float64)

    # ---- pass 2: nearest VACANT storefront, one min_only pass
    vac = np.flatnonzero(storefronts["vacant"].fillna(False).to_numpy()[pos])
    if vac.size:
        # Several vacant storefronts can snap to one graph node. scipy's
        # `sources` names the NODE, so a node hosting more than one is resolved
        # deterministically to the first by storefront_id -- stated here rather
        # than left to whichever row np.unique happened to keep.
        order = np.argsort(storefronts["storefront_id"].to_numpy()[pos][vac], kind="stable")
        node_owner: dict[int, int] = {}
        for b in vac[order]:
            node_owner.setdefault(int(nidx[b]), int(pos[b]))
        src = np.array(sorted(node_owner), dtype=np.int64)
        d, _pred, sources = dijkstra(A, directed=False, indices=src, min_only=True,
                                     limit=float(DIST_LIMIT), return_predecessors=True)
        ok = np.isfinite(d)
        near_d = np.where(ok, d, float(DIST_LIMIT))
        owner = np.array([node_owner.get(int(s0), -1) for s0 in np.maximum(sources, 0)])
        near_p = np.where(ok & (sources >= 0), owner, -1)

    return idx, acc, (near_d, near_p)


def compute_storefronts(con, boroughs: list[str], asof: dt.date,
                        graph_path: pathlib.Path = GRAPH_PATH,
                        radius_m: float = DEFAULT_RADIUS_M
                        ) -> tuple[pd.DataFrame, dict]:
    """(frame of address_id/borough + STOREFRONT_COLUMNS, report). READ-ONLY on
    analysis.address -- it selects address_id, borough, lon, lat and nothing
    else."""
    import pickle

    shops = load_storefronts(con, boroughs, asof)
    if shops.empty:
        raise RuntimeError(
            f"storefronts: analysis.storefront has no rows for {boroughs} at "
            f"observation date {asof}. Run `loci ingest-storefronts` first -- "
            f"writing zeros onto every address would read as 'there is no empty "
            f"ground floor anywhere', a confident false negative, not a missing "
            f"value."
        )
    W, labels = weight_matrix(shops)

    holes = ", ".join("?" for _ in boroughs)
    addr = con.execute(
        f"SELECT address_id, borough, lon, lat FROM analysis.address "
        f"WHERE borough IN ({holes}) ORDER BY borough, address_id", list(boroughs)
    ).fetchdf()

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    idx, acc, (near_d, near_p) = node_storefront_matrix(
        Gp, shops, W, radius_m=radius_m, min_component=0)

    anodes = ox.distance.nearest_nodes(Gp, X=addr["lon"].tolist(), Y=addr["lat"].tolist())
    anidx = np.array([idx[n] for n in np.atleast_1d(anodes)], dtype=np.int64)

    out = pd.DataFrame({"address_id": addr["address_id"], "borough": addr["borough"]})
    # The DDL column names carry `400m` because 400 m is THRESHOLDS[5] and the
    # default. `--radius-m` still varies the QUANTITY, so the run's actual
    # radius is stamped in the report and printed by the CLI rather than
    # encoded in a column name that the schema cannot change. A non-default
    # radius therefore produces columns whose NAME says 400 and whose VALUE
    # does not -- the CLI warns, and this is the caveat the database cannot
    # enforce.
    for li, _label in enumerate(labels):
        out[STOREFRONT_COLUMNS[li]] = acc[li][anidx].round().astype("int64")

    p = near_p[anidx]
    has = p >= 0
    cols = shops.iloc[np.maximum(p, 0)].reset_index(drop=True)
    out["nearest_vacant_storefront_m"] = np.where(has, near_d[anidx], np.nan)
    out["nearest_vacant_storefront_id"] = np.where(has, cols["storefront_id"], None)
    out["nearest_vacant_storefront_business"] = np.where(
        has, cols["primary_business_activity"], None)
    lease = pd.to_datetime(cols["lease_expiry"], errors="coerce")
    # NULL when the nearest vacant storefront reported no lease -- never FALSE.
    expired = pd.Series(np.where(lease.notna(), lease < pd.Timestamp(asof), None),
                        dtype="object")
    out["nearest_vacant_lease_expired"] = expired.where(pd.Series(has), None)
    out["storefront_asof"] = asof
    out = out[["address_id", "borough", *STOREFRONT_COLUMNS]]

    n_vac = int(W[0].sum())
    pick = snapshot_filing(con, boroughs, asof)
    report = {
        "asof": asof.isoformat(),
        "filing_due_date": pick[0].isoformat() if pick else None,
        "radius_m": float(radius_m),
        "storefronts": len(shops),
        "storefronts_vacant": n_vac,
        "vacancy_rate": (n_vac / len(shops)) if len(shops) else None,
        "premises": int(shops["premises_id"].nunique()),
        "universe": pick[1] if pick else None,
        "construction_reported": int(
            shops["construction_reported"].fillna(False).astype(bool).sum()),
        "vacant_with_lease": int(
            shops.loc[shops["vacant"].fillna(False), "lease_expiry"].notna().sum()),
        "addresses": len(addr),
        "addresses_with_vacant": int(has.sum()),
    }
    return out, report


# -------------------------------------------------------------- write side

def write_storefronts(con, df: pd.DataFrame, boroughs: list[str]) -> int:
    """UPDATE-only annotation of analysis.address (see the module docstring's
    non-filtering note). Two passes, both UPDATE:

      1. RESET every in-scope row's STOREFRONT_COLUMNS to NULL. Without this an
         address that had a vacant storefront nearby on the last run and does
         not on this one (it got leased, or the owner stopped filing) would keep
         last run's number forever -- UPDATE has no DELETE to fall back on.
      2. UPDATE ... FROM the computed frame on (address_id, borough).

    `boroughs` is passed explicitly rather than inferred from `df`, so an
    empty-frame run still resets instead of leaving stale annotations behind.
    """
    if not boroughs:
        return 0
    forbidden = set(ADDRESS_SCREEN_COLUMNS) | set(AGE_FIT_COLUMNS)
    try:
        from loci.model.dev_pipeline import PIPELINE_COLUMNS
        forbidden |= set(PIPELINE_COLUMNS)
    except ImportError:                                   # pragma: no cover
        pass
    overlap = sorted(set(STOREFRONT_COLUMNS) & forbidden)
    if overlap:   # belt and braces; the test is the real guard
        raise RuntimeError(f"storefronts would clobber existing columns: {overlap}")
    holes = ", ".join("?" for _ in boroughs)
    reset = ", ".join(f"{c} = NULL" for c in STOREFRONT_COLUMNS)
    con.execute(f"UPDATE analysis.address SET {reset} WHERE borough IN ({holes})",
                list(boroughs))
    if df.empty:
        return 0
    con.register("_sf", df)
    try:
        sets = ", ".join(f"{c} = _sf.{c}" for c in STOREFRONT_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address AS a
            SET {sets}
            FROM _sf
            WHERE a.address_id = _sf.address_id AND a.borough = _sf.borough
        """)
    finally:
        con.unregister("_sf")
    return len(df)


def build_storefronts(con, boroughs: list[str], asof: dt.date,
                      radius_m: float = DEFAULT_RADIUS_M,
                      graph_path: pathlib.Path = GRAPH_PATH,
                      dry_run: bool = False) -> tuple[pd.DataFrame, dict]:
    df, report = compute_storefronts(con, boroughs, asof, graph_path=graph_path,
                                     radius_m=radius_m)
    report["graph_version"] = graph_version(graph_path)
    if not dry_run:
        report["_written"] = write_storefronts(con, df, boroughs)
    return df, report
