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
import pickle

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


def build_address_convenience(
    con,
    addresses_df,
    borough: str,
    graph_path: pathlib.Path = GRAPH_PATH,
    conveniences_path: pathlib.Path = CONVENIENCES_PATH,
) -> int:
    """Persist analysis.address_convenience for `addresses_df` (columns:
    address_id, bbl, lon, lat, units, address -- see
    sources/cities/nyc/addresses.py). Deletes existing rows for `borough`
    first (idempotent per-borough rebuild). Returns rows written.
    """
    import datetime
    import pandas as pd

    conveniences = load_conveniences(conveniences_path)
    conv_hash = conveniences_hash(conveniences)
    gver = graph_version(graph_path)
    run_at = datetime.datetime.now(datetime.timezone.utc)

    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)

    pois = con.execute(
        """SELECT p.category, ST_X(p.geom), ST_Y(p.geom)
           FROM staging.poi p JOIN analysis.poi_dedup d
             ON d.poi_id = p.poi_id AND d.is_canonical"""
    ).fetchall()

    addr_tuples = list(zip(addresses_df["address_id"], addresses_df["lon"], addresses_df["lat"]))
    results = compute_address_convenience(G, addr_tuples, pois, conveniences)

    # h3 res-9 cell -> analysis.hex (borough, nta_code), same join address_gaps.py
    # already uses for demand data. A resolution mismatch between the grid this
    # was built at and RES here would silently return NULLs, not wrong values,
    # because the join key is a full h3_index string.
    import h3

    RES = 9
    h3_index = [h3.latlng_to_cell(lat, lon, RES) for lat, lon in zip(addresses_df["lat"], addresses_df["lon"])]
    hex_lookup = {r[0]: (r[1], r[2]) for r in con.execute("SELECT h3_index, borough, nta_code FROM analysis.hex").fetchall()}

    names_path = pathlib.Path(graph_path).resolve().parents[1] / "interim" / "nta_names.json"
    nta_names: dict[str, str] = {}
    if names_path.exists():
        import json
        nta_names = json.loads(names_path.read_text())

    units_by_id = dict(zip(addresses_df["address_id"], addresses_df["units"]))
    bbl_by_id = dict(zip(addresses_df["address_id"], addresses_df["bbl"]))
    lonlat_by_id = dict(zip(addresses_df["address_id"], zip(addresses_df["lon"], addresses_df["lat"])))
    hex_by_id = dict(zip(addresses_df["address_id"], h3_index))

    rows = []
    for r in results:
        aid = r["address_id"]
        h3idx = hex_by_id[aid]
        borough_col, nta_code = hex_lookup.get(h3idx, (None, None))
        neighborhood = nta_names.get(nta_code, nta_code) if nta_code else None
        lon, lat = lonlat_by_id[aid]
        row = [aid, bbl_by_id[aid] or None, lon, lat, units_by_id[aid], nta_code, neighborhood]
        for cat in ALLCATS:
            row.append(r["distance_m"][cat])
            row.append(r["satisfied"][cat])
        row += [r["n_unsatisfied"], conv_hash, gver, run_at, borough.upper()]
        rows.append(row)

    cols = ["address_id", "bbl", "lon", "lat", "units", "nta_code", "neighborhood"]
    for cat in ALLCATS:
        cols += [f"{cat}_distance_m", f"{cat}_satisfied"]
    cols += ["n_unsatisfied", "conveniences_hash", "graph_version", "run_at", "borough"]

    df = pd.DataFrame(rows, columns=cols)
    con.execute("DELETE FROM analysis.address_convenience WHERE borough = ?", [borough.upper()])
    con.register("_addr_conv", df)
    try:
        placeholders = ", ".join(cols)
        con.execute(f"INSERT INTO analysis.address_convenience ({placeholders}) SELECT {placeholders} FROM _addr_conv")
    finally:
        con.unregister("_addr_conv")
    return len(df)


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


def convenience_summary(
    con,
    addresses_df,
    graph_path: pathlib.Path = GRAPH_PATH,
    conveniences_path: pathlib.Path = CONVENIENCES_PATH,
) -> dict:
    """Run compute_address_convenience for `addresses_df` and summarize --
    no DB write, no hex/NTA join, no provenance columns. This is the
    `loci conveniences --dry-run` path: it pays the ~90s graph load + 15
    Dijkstra passes but leaves analysis.address_convenience untouched."""
    conveniences = load_conveniences(conveniences_path)
    with pathlib.Path(graph_path).open("rb") as fh:
        G = pickle.load(fh)
    pois = con.execute(
        """SELECT p.category, ST_X(p.geom), ST_Y(p.geom)
           FROM staging.poi p JOIN analysis.poi_dedup d
             ON d.poi_id = p.poi_id AND d.is_canonical"""
    ).fetchall()
    addr_tuples = list(zip(addresses_df["address_id"], addresses_df["lon"], addresses_df["lat"]))
    results = compute_address_convenience(G, addr_tuples, pois, conveniences)
    return summarize_results(results, addresses_df)


def _weighted_share(con, borough: str, category: str) -> float:
    """Unit-weighted share of `borough` residential units UNSATISFIED for `category`."""
    row = con.execute(
        f"""SELECT sum(CASE WHEN NOT {category}_satisfied THEN units ELSE 0 END) / sum(units)
            FROM analysis.address_convenience WHERE borough = ?""",
        [borough.upper()],
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def category_unsatisfied_shares(con, borough: str) -> list[tuple[str, float]]:
    """[(category, unit-weighted unsatisfied share)] for all 15 categories,
    worst (highest unsatisfied share) first."""
    out = [(c, _weighted_share(con, borough, c)) for c in ALLCATS]
    return sorted(out, key=lambda t: -t[1])


def n_unsatisfied_distribution(con, borough: str) -> list[tuple[int, float, float]]:
    """[(n_unsatisfied, share_of_addresses, share_of_units)] -- the distribution
    of how many of the 15 categories are unsatisfied, both per-address and
    UNIT-weighted (a 200-unit tower counts 200x an SRO in the unit-weighted
    view, which is the one the report leads with per the brief)."""
    df = con.execute(
        """SELECT n_unsatisfied, count(*) n_addr, sum(units) n_units
           FROM analysis.address_convenience WHERE borough = ?
           GROUP BY 1 ORDER BY 1""",
        [borough.upper()],
    ).fetchall()
    total_addr = sum(r[1] for r in df) or 1
    total_units = sum(r[2] for r in df) or 1.0
    return [(n, n_addr / total_addr, n_units / total_units) for n, n_addr, n_units in df]


def top_ntas_for_category(con, borough: str, category: str, n: int = 10) -> list[tuple[str, str, float, float]]:
    """[(nta_code, neighborhood, unit-weighted unsatisfied share, total units)]
    for the `n` NTAs with the highest unit-weighted unsatisfied share for
    `category`, restricted to NTAs with at least 50 residential units (avoids
    a single-lot NTA fragment reading as 100% unsatisfied)."""
    rows = con.execute(
        f"""SELECT nta_code, any_value(neighborhood),
                   sum(CASE WHEN NOT {category}_satisfied THEN units ELSE 0 END) / sum(units) AS share,
                   sum(units) AS total_units
            FROM analysis.address_convenience
            WHERE borough = ? AND nta_code IS NOT NULL
            GROUP BY nta_code
            HAVING sum(units) >= 50
            ORDER BY share DESC
            LIMIT ?""",
        [borough.upper(), n],
    ).fetchall()
    return rows
