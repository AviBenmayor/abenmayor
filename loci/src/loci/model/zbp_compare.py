"""Compare Loci's deduped POI coverage against Census ZBP establishment
counts, per category and NYC ZIP (`loci zbp-compare`; docs/CHECKPOINT.md
ZBP-validation ticket). VALIDATION ONLY -- this never writes to or reads from
analysis.hex_gaps / analysis.hex_gaps_reach, and nothing here feeds the gap
flag. See src/loci/sources/universal/census_zbp.py and src/loci/zbp_naics.yaml
for the source and the NAICS crosswalk.

POI -> ZIP assignment (documented per the ticket's requirement to record
which method was used): NYC has no ZCTA polygon layer in the database yet
(`nyc_boundaries` in registry.yaml is still `status: planned`), so this uses
the PLUTO-lot fallback the ticket names -- but as a MAJORITY-VOTE HEX
CROSSWALK rather than a per-POI nearest-lot search (a per-POI nearest-lot
join would be an O(n_poi x n_lots) spatial search with ~2.2e5 POIs x ~8.6e5
PLUTO lots, which is not worth the runtime for a validation-only check):

    1. Every PLUTO lot already carries (postcode, lat, lon). Bin each lot to
       its H3 res-9 cell (same resolution as analysis.hex) and take the
       MAJORITY postcode among lots in that cell -- a res-9 hex is small
       enough (~0.1 km^2) that a ZIP boundary splitting one is rare, and where
       it happens the majority vote is a defensible single answer.
    2. Bin each CANONICAL POI (analysis.poi_dedup.is_canonical) to its own H3
       res-9 cell from its own (lon, lat), via DuckDB's h3_latlng_to_cell --
       no PLUTO join needed for the POI side at all.
    3. Join POI hex -> crosswalk hex -> zip. A POI hex with no PLUTO lots at
       all (POI in a park/institutional site) has no zip and is dropped from
       the comparison, not silently assigned zip=NULL's counts.

Population per ZIP (for the "population < 1,000" exclusion) is likewise
approximated by summing analysis.hex_demographics.population (dasymetric ACS,
latest acs_year) over the hexes the SAME crosswalk assigns to that ZIP --
there is no ZIP-level ACS table in the database, so this reuses the hex->zip
mapping already built for the POI side rather than adding a second, possibly
inconsistent, geography.
"""
from __future__ import annotations

import h3
import pandas as pd

from loci.grid.pluto import PLUTO_CSV

RES = 9
LOW_POP_CUTOFF = 1_000
UNDERCOVER_RATIO = 0.5
OVERCOUNT_RATIO = 2.0
FLAGGED_CATEGORIES = ("hardware", "fitness", "clinic")   # M1 validation flagged these


def _hex_zip_crosswalk(con, pluto_csv=PLUTO_CSV) -> pd.DataFrame:
    """Majority-vote (h3_index -> zipcode) from PLUTO lots. See module docstring."""
    lots = con.execute(
        """
        SELECT postcode AS zipcode,
               TRY_CAST(latitude AS DOUBLE)  AS lat,
               TRY_CAST(longitude AS DOUBLE) AS lon
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE postcode SIMILAR TO '[0-9]{5}'
          AND TRY_CAST(latitude AS DOUBLE) IS NOT NULL
          AND TRY_CAST(longitude AS DOUBLE) IS NOT NULL
        """,
        [str(pluto_csv)],
    ).df()
    lots["h3_index"] = [h3.latlng_to_cell(la, lo, RES) for la, lo in zip(lots.lat, lots.lon)]
    counts = lots.groupby(["h3_index", "zipcode"]).size().reset_index(name="n")
    majority = counts.sort_values("n", ascending=False).drop_duplicates("h3_index")
    return majority[["h3_index", "zipcode"]]


def _poi_counts_by_zip_category(con, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Canonical POI count per (zipcode, category), via the hex crosswalk."""
    con.register("_hex_zip_xwalk", crosswalk)
    try:
        df = con.execute("""
            WITH canonical AS (
                SELECT p.poi_id, p.category,
                       h3_h3_to_string(h3_latlng_to_cell(ST_Y(p.geom), ST_X(p.geom), 9)) AS h3_index
                FROM staging.poi p
                JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id
                WHERE d.is_canonical
            )
            SELECT x.zipcode, c.category, count(*) AS poi_count
            FROM canonical c
            JOIN _hex_zip_xwalk x ON x.h3_index = c.h3_index
            GROUP BY 1, 2
        """).df()
    finally:
        con.unregister("_hex_zip_xwalk")
    return df


def _population_by_zip(con, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Approximate ZIP population by summing hex_demographics.population
    (latest acs_year) over hexes the crosswalk assigns to that ZIP."""
    year = con.execute("SELECT max(acs_year) FROM analysis.hex_demographics").fetchone()[0]
    con.register("_hex_zip_xwalk2", crosswalk)
    try:
        df = con.execute("""
            SELECT x.zipcode, sum(d.population) AS population
            FROM analysis.hex_demographics d
            JOIN _hex_zip_xwalk2 x ON x.h3_index = d.h3_index
            WHERE d.acs_year = ?
            GROUP BY 1
        """, [year]).df()
    finally:
        con.unregister("_hex_zip_xwalk2")
    return df


def build_coverage_check(con, year: int | None = None) -> int:
    """Build analysis.zip_coverage_check for `year` (the ZBP vintage; defaults
    to the latest ingested). Applies the population >= 1,000 and
    "ZBP row present" (not-suppressed) exclusions AT WRITE TIME, so the table
    itself is already the clean comparison set. Returns the row count written.
    """
    if year is None:
        year = con.execute("SELECT max(year) FROM analysis.zip_category_establishments").fetchone()[0]
        if year is None:
            raise RuntimeError("analysis.zip_category_establishments is empty -- run `loci ingest-zbp` first.")

    crosswalk = _hex_zip_crosswalk(con)
    poi = _poi_counts_by_zip_category(con, crosswalk)
    pop = _population_by_zip(con, crosswalk)

    zbp = con.execute(
        "SELECT zipcode, category, estab_total FROM analysis.zip_category_establishments WHERE year = ?",
        [year],
    ).df()

    merged = zbp.merge(pop, on="zipcode", how="left").merge(
        poi, on=["zipcode", "category"], how="left"
    )
    merged["poi_count"] = merged["poi_count"].fillna(0).astype(int)
    merged = merged[merged["population"].fillna(0) >= LOW_POP_CUTOFF].copy()
    # "ZBP estab suppressed" for our purposes: no estab_total in the response
    # for this (zip, category) -- see census_zbp.py's suppression note.
    merged = merged[merged["estab_total"].notna()].copy()
    merged["ratio"] = merged["poi_count"] / merged["estab_total"].replace(0, pd.NA)

    out = merged[["zipcode", "category", "poi_count", "estab_total", "ratio"]].rename(
        columns={"estab_total": "zbp_estab"}
    )
    out.insert(0, "year", year)

    con.execute("DELETE FROM analysis.zip_coverage_check WHERE year = ?", [year])
    con.register("_zcc", out)
    try:
        con.execute("""
            INSERT INTO analysis.zip_coverage_check (year, zipcode, category, poi_count, zbp_estab, ratio)
            SELECT year, zipcode, category, poi_count, zbp_estab, ratio FROM _zcc
        """)
    finally:
        con.unregister("_zcc")
    return len(out)


def run_comparison(con, year: int | None = None, console=None) -> pd.DataFrame:
    """Build (or rebuild) analysis.zip_coverage_check and print the per-
    category summary + the top-5 undercovered ZIPs for hardware/fitness/clinic.
    Returns the underlying DataFrame for programmatic use (e.g. tests)."""
    n = build_coverage_check(con, year)
    used_year = con.execute("SELECT max(year) FROM analysis.zip_coverage_check").fetchone()[0]
    df = con.execute("SELECT * FROM analysis.zip_coverage_check WHERE year = ?", [used_year]).df()

    def emit(line: str) -> None:
        if console is not None:
            console.print(line)
        else:
            print(line)

    emit(f"analysis.zip_coverage_check: {n} rows (year={used_year})")
    emit(f"{'category':14} {'n_zips':>7} {'median':>8} {'IQR':>16} {'<0.5':>8} {'>2.0':>8}")
    for cat, g in df.groupby("category"):
        r = g["ratio"].dropna()
        if r.empty:
            emit(f"{cat:14} {'(no comparable ZIPs)':>50}")
            continue
        q1, med, q3 = r.quantile([0.25, 0.5, 0.75])
        share_under = (r < UNDERCOVER_RATIO).mean()
        share_over = (r > OVERCOUNT_RATIO).mean()
        emit(f"{cat:14} {len(r):>7} {med:>8.2f} {f'[{q1:.2f}, {q3:.2f}]':>16} "
             f"{share_under:>7.0%} {share_over:>7.0%}")

    for cat in FLAGGED_CATEGORIES:
        g = df[(df["category"] == cat) & df["ratio"].notna()].sort_values("ratio")
        emit(f"\ntop-5 undercovered ZIPs -- {cat}:")
        if g.empty:
            emit("  (no comparable ZIPs)")
            continue
        for _, row in g.head(5).iterrows():
            emit(f"  {row['zipcode']}  poi={int(row['poi_count']):>3}  "
                 f"zbp={int(row['zbp_estab']):>4}  ratio={row['ratio']:.2f}")

    return df
