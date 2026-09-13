"""Address-level convenience check (docs/CHECKPOINT.md D-conveniences): for
every residential address, which of the 15 Loci categories sit within ITS
OWN owner-set walk distance (src/loci/conveniences.yaml), and which don't.

Distinct from model/gaps.py and reach.py (do not touch, do not import from):
gaps/reach ask "is category c conspicuously missing from this HEX, relative
to what comparable hexes have" -- a relative, data-derived question. This
module asks "is category c within the OWNER'S norm of this ADDRESS" -- an
absolute, address-level question with no comparison to other places at all.
The two never disagree by construction because they are not the same claim;
this module does not read hex_gaps/hex_gaps_reach and gaps.py does not read
analysis.address_convenience.

Method (reuses the score/access.py multi-source Dijkstra code path, same as
model/address_gaps.py already does): one Dijkstra per category, sourced from
every canonical POI of that category at once (`min_only=True`), gives every
graph node its network distance to the nearest business of that category in a
single pass; each address then reads off its own nearest node's distance.
Fifteen Dijkstra runs total, independent of how many addresses there are --
cheaper than one Dijkstra per address batch when there are tens of thousands
of addresses and a few hundred POIs per category.

City-agnostic: this module takes a graph, a list of (address_id, lon, lat,
units) tuples, and canonical POIs from staging.poi. No NYC column names here
-- those live only in sources/cities/nyc/addresses.py.
"""
from __future__ import annotations

import hashlib
import pathlib

import numpy as np
import osmnx as ox
import yaml
from scipy.sparse.csgraph import dijkstra

from loci.categories import CATEGORIES
from loci.score.access import DIST_LIMIT, MIN_COMPONENT, _prune, _to_csr
from loci.score.walkgraph import OUT as GRAPH_PATH

PKG = pathlib.Path(__file__).resolve().parents[1]  # src/loci
CONVENIENCES_PATH = PKG / "conveniences.yaml"

ALLCATS = list(CATEGORIES)  # fixed column/report order, tier order from categories.py


def load_conveniences(path: pathlib.Path = CONVENIENCES_PATH) -> dict[str, float]:
    """{category: distance_m}, the owner-set convenience norm. Fails closed: a
    category missing from conveniences.yaml raises rather than silently
    defaulting to 'never satisfied' or 'always satisfied' -- either default
    would quietly change the citywide unsatisfied share for that category."""
    doc = yaml.safe_load(pathlib.Path(path).read_text())
    dist_m = doc.get("distance_m") or {}
    missing = sorted(set(ALLCATS) - set(dist_m))
    if missing:
        raise ValueError(
            f"conveniences.yaml is missing distance_m for: {', '.join(missing)}"
        )
    return {c: float(dist_m[c]) for c in ALLCATS}


def conveniences_hash(conveniences: dict[str, float]) -> str:
    """Stable short hash of the {category: distance_m} actually used for a
    run -- provenance so two runs are comparable even after the yaml changes."""
    canon = ",".join(f"{c}:{conveniences[c]:.1f}" for c in sorted(conveniences))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def graph_version(path: pathlib.Path = GRAPH_PATH) -> str:
    """Lightweight provenance tag for the pickled walk graph: name + mtime +
    size. Not a content hash -- the graph file is ~300 MB and hashing it on
    every build would dominate runtime for no benefit over the OS mtime."""
    p = pathlib.Path(path)
    st = p.stat()
    return f"{p.name}:{int(st.st_mtime)}:{st.st_size}"


def compute_address_convenience(
    G,
    addresses: list[tuple[str, float, float]],
    pois: list[tuple[str, float, float]],
    conveniences: dict[str, float],
    cap_m: float = DIST_LIMIT,
    min_component: int = MIN_COMPONENT,
) -> list[dict]:
    """addresses: [(address_id, lon, lat)]. pois: [(category, lon, lat)].
    Returns one dict per address: {"address_id", "distance_m": {cat: m|None},
    "satisfied": {cat: bool}, "n_unsatisfied": int}. distance_m is None when
    no business of that category is reachable within `cap_m` (the 30-minute
    walk cap, matching hex_poi_distance's convention) -- always unsatisfied.
    """
    missing = sorted(set(ALLCATS) - set(conveniences))
    if missing:
        raise ValueError(f"conveniences is missing: {', '.join(missing)}")

    G = _prune(G, min_component)
    A, idx = _to_csr(G)
    N = A.shape[0]

    addr_nodes = ox.distance.nearest_nodes(G, X=[a[1] for a in addresses], Y=[a[2] for a in addresses])
    addr_nidx = np.array([idx[n] for n in addr_nodes])

    by_cat: dict[str, list[tuple[float, float]]] = {c: [] for c in ALLCATS}
    for cat, lon, lat in pois:
        if cat in by_cat:
            by_cat[cat].append((lon, lat))

    dist_by_cat: dict[str, np.ndarray] = {}
    for cat in ALLCATS:
        pts = by_cat[cat]
        if not pts:
            dist_by_cat[cat] = np.full(N, np.inf)
            continue
        nodes = ox.distance.nearest_nodes(G, X=[p[0] for p in pts], Y=[p[1] for p in pts])
        src = np.unique([idx[n] for n in nodes])
        dist_by_cat[cat] = dijkstra(A, directed=False, indices=src, min_only=True, limit=cap_m)

    rows = []
    for i, (aid, _lon, _lat) in enumerate(addresses):
        ni = addr_nidx[i]
        distance_m: dict[str, float | None] = {}
        satisfied: dict[str, bool] = {}
        n_unsat = 0
        for cat in ALLCATS:
            d = float(dist_by_cat[cat][ni])
            d = d if np.isfinite(d) else None
            ok = d is not None and d <= conveniences[cat]
            distance_m[cat] = d
            satisfied[cat] = ok
            if not ok:
                n_unsat += 1
        rows.append({"address_id": aid, "distance_m": distance_m, "satisfied": satisfied, "n_unsatisfied": n_unsat})
    return rows


def _threshold_case_sql(conveniences: dict[str, float]) -> str:
    """A SQL `CASE category WHEN 'grocery' THEN 400.0 ... END` expression
    evaluating to the owner-set norm for whichever category a row names --
    generated from conveniences.yaml so the report's SQL and
    compute_address_convenience's python dict can never define a norm two
    different ways."""
    arms = " ".join(f"WHEN '{c}' THEN {v!r}" for c, v in conveniences.items())
    return f"CASE category {arms} END"


def convenience_report(
    con,
    borough: str,
    conveniences_path: pathlib.Path = CONVENIENCES_PATH,
) -> dict:
    """READ-ONLY report: applies conveniences.yaml's owner-set norm to
    analysis.address_category.nearest_m for `borough` -- the SAME per-category
    network distances model/address_gaps.py already computed and wrote, via
    the SAME multi-source-Dijkstra engine this module's own
    `compute_address_convenience` is the reference implementation for. No
    second Dijkstra pass, no persisted table (D58: analysis.address_convenience,
    a 200-row prototype duplicating that column under a different name, is
    dropped -- see sql/002_schema.sql and sql/009_retire_split_tables.sql).

    Requires `loci address-gaps` to have already populated
    analysis.address_category for `borough`; raises ValueError otherwise, so a
    forgotten prerequisite reads as "run address-gaps first", not a silent
    empty report.
    """
    conveniences = load_conveniences(conveniences_path)
    b = borough.upper()
    # D84: LOT frame only, everywhere in this report. Its two headline
    # statistics are unit-weighted (a street point's units are 0, so those are
    # unchanged either way) but its ADDRESS counts and the per-address
    # n_unsatisfied distribution are not: a street midpoint is not an address
    # whose residents are or are not served, and pooling the frames would
    # rewrite "what share of addresses have everything within a walk" into a
    # statement about the street network's geometry.
    n_addr = con.execute(
        "SELECT count(*) FROM analysis.address "
        "WHERE borough = ? AND COALESCE(frame, 'lot') = 'lot'", [b]).fetchone()[0]
    if not n_addr:
        raise ValueError(
            f"analysis.address has no rows for borough={b} -- run `loci address-gaps` first")

    case_sql = _threshold_case_sql(conveniences)
    row = con.execute(
        f"""SELECT count(*), sum(a.units)
            FROM analysis.address a
            WHERE a.borough = ? AND COALESCE(a.frame, 'lot') = 'lot'""", [b]).fetchone()
    total_addr, total_units = row[0], (row[1] or 0.0)

    cat_rows = con.execute(
        f"""SELECT c.category,
                   sum(CASE WHEN c.nearest_m IS NULL OR c.nearest_m > {case_sql}
                            THEN a.units ELSE 0 END) AS unsat_units
            FROM analysis.address_category c
            JOIN analysis.address a ON a.address_id = c.address_id AND a.borough = c.borough
            WHERE c.borough = ?
            GROUP BY c.category""", [b]).fetchall()
    unsat_units_by_cat = {cat: float(u or 0.0) for cat, u in cat_rows}
    cat_share = {c: 1.0 - unsat_units_by_cat.get(c, 0.0) / total_units if total_units else 0.0
                for c in ALLCATS}

    fully_units = con.execute(
        f"""WITH per_addr AS (
                SELECT c.address_id,
                       sum(CASE WHEN c.nearest_m IS NULL OR c.nearest_m > {case_sql}
                                THEN 1 ELSE 0 END) AS n_unsatisfied
                FROM analysis.address_category c
                WHERE c.borough = ? AND COALESCE(c.frame, 'lot') = 'lot'
                GROUP BY c.address_id
            )
            SELECT sum(a.units) FROM per_addr p
            JOIN analysis.address a ON a.address_id = p.address_id AND a.borough = ?
            WHERE p.n_unsatisfied = 0""", [b, b]).fetchone()[0] or 0.0

    return {
        "n_addresses": total_addr,
        "n_units": total_units,
        "category_satisfied_share": cat_share,
        "share_fully_satisfied": fully_units / total_units if total_units else 0.0,
    }


def summarize_results(results: list[dict], addresses_df) -> dict:
    """Pure, DB-free summary of compute_address_convenience() output:
    unit-weighted per-category satisfied share and the unit-weighted share of
    addresses with n_unsatisfied == 0. Shared by `convenience_summary` (the
    --dry-run path, nothing persisted) and the CLI's post-write summary,
    so both print the same statistic computed the same way."""
    units_by_id = dict(zip(addresses_df["address_id"], addresses_df["units"]))
    total_units = float(sum(units_by_id.values())) or 1.0
    cat_share = {}
    for cat in ALLCATS:
        unsat_units = sum(units_by_id[r["address_id"]] for r in results if not r["satisfied"][cat])
        cat_share[cat] = 1.0 - unsat_units / total_units
    fully_units = sum(units_by_id[r["address_id"]] for r in results if r["n_unsatisfied"] == 0)
    return {
        "n_addresses": len(results),
        "n_units": total_units,
        "category_satisfied_share": cat_share,
        "share_fully_satisfied": fully_units / total_units,
    }


def _weighted_share(con, borough: str, category: str, conveniences: dict[str, float]) -> float:
    """Unit-weighted share of `borough` residential units UNSATISFIED for
    `category`, off analysis.address_category.nearest_m (D58) -- no
    persisted address_convenience table."""
    threshold = conveniences[category]
    row = con.execute(
        """SELECT sum(CASE WHEN c.nearest_m IS NULL OR c.nearest_m > ? THEN a.units ELSE 0 END)
                  / sum(a.units)
            FROM analysis.address_category c
            JOIN analysis.address a ON a.address_id = c.address_id AND a.borough = c.borough
            WHERE c.borough = ? AND c.category = ?""",
        [threshold, borough.upper(), category],
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def category_unsatisfied_shares(
    con, borough: str, conveniences_path: pathlib.Path = CONVENIENCES_PATH,
) -> list[tuple[str, float]]:
    """[(category, unit-weighted unsatisfied share)] for all 15 categories,
    worst (highest unsatisfied share) first."""
    conveniences = load_conveniences(conveniences_path)
    out = [(c, _weighted_share(con, borough, c, conveniences)) for c in ALLCATS]
    return sorted(out, key=lambda t: -t[1])


def n_unsatisfied_distribution(
    con, borough: str, conveniences_path: pathlib.Path = CONVENIENCES_PATH,
) -> list[tuple[int, float, float]]:
    """[(n_unsatisfied, share_of_addresses, share_of_units)] -- the distribution
    of how many of the 15 categories are unsatisfied, both per-address and
    UNIT-weighted (a 200-unit tower counts 200x an SRO in the unit-weighted
    view, which is the one the report leads with per the brief). The
    per-category threshold is a generated SQL CASE (`_threshold_case_sql`):
    each category has a DIFFERENT owner-set norm, so "unsatisfied" cannot be
    one WHERE predicate the way `_weighted_share`'s single-category query
    can use one."""
    conveniences = load_conveniences(conveniences_path)
    case_sql = _threshold_case_sql(conveniences)
    df = con.execute(
        f"""WITH per_addr AS (
                SELECT c.address_id,
                       sum(CASE WHEN c.nearest_m IS NULL OR c.nearest_m > {case_sql}
                                THEN 1 ELSE 0 END) AS n_unsatisfied
                FROM analysis.address_category c
                WHERE c.borough = ? AND COALESCE(c.frame, 'lot') = 'lot'
                GROUP BY c.address_id
            )
            SELECT p.n_unsatisfied, count(*) n_addr, sum(a.units) n_units
            FROM per_addr p
            JOIN analysis.address a ON a.address_id = p.address_id AND a.borough = ?
            GROUP BY 1 ORDER BY 1""",
        [borough.upper(), borough.upper()],
    ).fetchall()
    total_addr = sum(r[1] for r in df) or 1
    total_units = sum(r[2] for r in df) or 1.0
    return [(n, n_addr / total_addr, n_units / total_units) for n, n_addr, n_units in df]


def top_ntas_for_category(
    con, borough: str, category: str, n: int = 10,
    conveniences_path: pathlib.Path = CONVENIENCES_PATH,
) -> list[tuple[str, str, float, float]]:
    """[(nta_code, neighborhood, unit-weighted unsatisfied share, total units)]
    for the `n` NTAs with the highest unit-weighted unsatisfied share for
    `category`, restricted to NTAs with at least 50 residential units (avoids
    a single-lot NTA fragment reading as 100% unsatisfied)."""
    threshold = load_conveniences(conveniences_path)[category]
    rows = con.execute(
        """SELECT a.nta_code, any_value(a.neighborhood),
                  sum(CASE WHEN c.nearest_m IS NULL OR c.nearest_m > ? THEN a.units ELSE 0 END)
                  / sum(a.units) AS share,
                  sum(a.units) AS total_units
           FROM analysis.address_category c
           JOIN analysis.address a ON a.address_id = c.address_id AND a.borough = c.borough
           WHERE c.borough = ? AND c.category = ? AND a.nta_code IS NOT NULL
           GROUP BY a.nta_code
           HAVING sum(a.units) >= 50
           ORDER BY share DESC
           LIMIT ?""",
        [threshold, borough.upper(), category, n],
    ).fetchall()
    return rows
