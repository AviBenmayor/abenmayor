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

#: Band the PRINCIPLED set's category-level POI/ZBP ratio must sit inside for
#: the screen to be trusted on that category. Outside it, a "gap" is at least
#: as likely to be a coverage artefact as a real absence: below 0.5 the supply
#: is thin enough that ordinary businesses are missing, above 2.5 something is
#: being counted more than once (booth renters, franchise chains registered per
#: outlet, NAICS bleed between adjacent categories). These are REPORTING flags
#: -- nothing is filtered on them; the screen still runs and the caveat travels
#: with the number.
PRINCIPLED_UNDER = 0.5
PRINCIPLED_OVER = 2.5

#: The sets anyone may actually SCREEN on -- score/supply.SUPPLY_SETS, in
#: nesting order (CORROBORATED subset of PRINCIPLED subset of ALL). The
#: registry_anchored / active variants in SUPPLY_SETS below are measurement
#: aids and are deliberately absent from the comparison table.
SCREENING_SETS = ("all", "principled", "corroborated")
FLAGGED_CATEGORIES = ("hardware", "fitness", "clinic")   # M1 validation flagged these

#: Supply sets, as columns on analysis.poi_supply (sql/003_supply_sets.sql).
#: Selecting one changes only WHICH canonical POIs are counted on the Loci
#: side; the ZBP side, the population cutoff and the crosswalk are identical
#: across sets, so the ratios are comparable by construction.
#: The three D52 sets (all / principled / corroborated) come from
#: score/supply.SUPPLY_SETS so there is ONE definition of what each name means;
#: the two ACTIVE variants are validation-only slices that live here alone.
SUPPLY_SETS = {
    "all": "in_all",
    "principled": "in_principled",
    "corroborated": "is_corroborated",
    # not a supply set anyone should screen on -- the anchor-coverage
    # NUMERATOR (score/supply.measure_anchor_coverage), exposed here so it is
    # computed by the same crosswalk and filters as its ZBP denominator.
    "registry_anchored": "has_registry_member",
    "active": "is_active",
    "active_corroborated": "is_active_corroborated",
}


def _supply_predicate(supply_set: str) -> str:
    try:
        return SUPPLY_SETS[supply_set]
    except KeyError:
        raise ValueError(
            f"unknown supply set {supply_set!r}; expected one of "
            f"{', '.join(sorted(SUPPLY_SETS))}"
        ) from None


def _zip_boroughs(con, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """(zipcode -> borough) by majority vote over the crosswalk's hexes.

    Assigning the BOROUGH TO THE WHOLE ZIP, rather than filtering POIs by
    borough, is the only join that keeps the ratio honest: zbp_estab is a
    whole-ZIP count from the Census and cannot be split, so filtering only the
    Loci side of a borough-straddling ZIP would invent an undercount. A ZIP
    that straddles a borough line is therefore counted entirely in its majority
    borough or not at all."""
    con.register("_hex_zip_xwalk4", crosswalk)
    try:
        df = con.execute("""
            SELECT x.zipcode, h.borough, count(*) AS n
            FROM analysis.hex h
            JOIN _hex_zip_xwalk4 x ON x.h3_index = h.h3_index
            WHERE h.borough IS NOT NULL
            GROUP BY 1, 2
        """).df()
    finally:
        con.unregister("_hex_zip_xwalk4")
    return (df.sort_values("n", ascending=False)
              .drop_duplicates("zipcode")[["zipcode", "borough"]])


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


def _poi_counts_by_zip_category(con, crosswalk: pd.DataFrame,
                                supply_set: str = "all") -> pd.DataFrame:
    """Canonical POI count per (zipcode, category), via the hex crosswalk.
    `supply_set` selects a boolean column on analysis.poi_supply; "all"
    reproduces the pre-D47 behaviour exactly (in_all is TRUE on every row)."""
    pred = _supply_predicate(supply_set)
    con.register("_hex_zip_xwalk", crosswalk)
    try:
        df = con.execute(f"""
            WITH canonical AS (
                SELECT s.poi_id, s.category,
                       h3_h3_to_string(h3_latlng_to_cell(ST_Y(s.geom), ST_X(s.geom), 9)) AS h3_index
                FROM analysis.poi_supply s
                WHERE s.{pred}
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


def _poi_counts_by_zip_category_source(con, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Canonical POI count per (zipcode, category, source), plus how many of
    those canonical POIs sit in a dedup cluster with only ONE distinct
    source_id among ALL its members (canonical or not) -- a record no other
    feed corroborates. `source` is the canonical row's own source_id, which
    is always the cluster's highest-ranked member per score/dedup.py
    source_rank() (analysis.poi_dedup.is_canonical is defined that way)."""
    con.register("_hex_zip_xwalk3", crosswalk)
    try:
        df = con.execute("""
            WITH canonical AS (
                SELECT p.poi_id, p.category, p.source_id, d.cluster_id,
                       h3_h3_to_string(h3_latlng_to_cell(ST_Y(p.geom), ST_X(p.geom), 9)) AS h3_index
                FROM staging.poi p
                JOIN analysis.poi_dedup d ON d.poi_id = p.poi_id
                WHERE d.is_canonical
            ),
            cluster_sources AS (
                -- distinct source_id count across EVERY member of the cluster,
                -- not just the canonical row -- this is what "corroborated by
                -- another feed" means.
                SELECT d.cluster_id, count(DISTINCT p.source_id) AS n_sources
                FROM analysis.poi_dedup d
                JOIN staging.poi p ON p.poi_id = d.poi_id
                GROUP BY 1
            )
            SELECT x.zipcode, c.category, c.source_id AS source,
                   count(*) AS poi_count,
                   sum(CASE WHEN cs.n_sources = 1 THEN 1 ELSE 0 END) AS poi_count_single_source
            FROM canonical c
            JOIN _hex_zip_xwalk3 x ON x.h3_index = c.h3_index
            JOIN cluster_sources cs ON cs.cluster_id = c.cluster_id
            GROUP BY 1, 2, 3
        """).df()
    finally:
        con.unregister("_hex_zip_xwalk3")
    return df


def build_coverage_by_source(con, year: int | None = None) -> int:
    """Build (or rebuild) analysis.zip_coverage_by_source for `year`. Reuses
    analysis.zip_coverage_check (built/rebuilt first) as the already-filtered
    (population >= 1,000, ZBP not suppressed) whitelist of (zipcode, category)
    pairs, then attributes each one's poi_count across sources. Returns the
    row count written.

    zip_coverage_check stays a base table, not a view derived from this one
    (considered under the 2026-09-09 consolidation pass; see
    sql/002_schema.sql's zip_coverage_check header): this table only ever
    gets a row for a (zipcode, category) with at least one canonical POI
    (the inner join below), so 12 of zip_coverage_check's 2,034 rows --
    every poi_count=0 "Census sees establishments, Loci found none" row --
    would silently vanish from a view built by summing this table instead.
    """
    n_base = build_coverage_check(con, year)
    used_year = con.execute("SELECT max(year) FROM analysis.zip_coverage_check").fetchone()[0]

    crosswalk = _hex_zip_crosswalk(con)
    poi_src = _poi_counts_by_zip_category_source(con, crosswalk)

    base = con.execute(
        "SELECT zipcode, category, zbp_estab FROM analysis.zip_coverage_check WHERE year = ?",
        [used_year],
    ).df()
    # inner join: a (zipcode, category) with poi_count 0 in the base table has
    # no source rows to attribute, and correctly contributes none here.
    merged = base.merge(poi_src, on=["zipcode", "category"], how="inner")
    merged["ratio"] = merged["poi_count"] / merged["zbp_estab"].replace(0, pd.NA)

    out = merged[["zipcode", "category", "source", "poi_count",
                  "poi_count_single_source", "zbp_estab", "ratio"]].copy()
    out.insert(0, "year", used_year)

    con.execute("DELETE FROM analysis.zip_coverage_by_source WHERE year = ?", [used_year])
    con.register("_zcbs", out)
    try:
        con.execute("""
            INSERT INTO analysis.zip_coverage_by_source
                (year, zipcode, category, source, poi_count, poi_count_single_source, zbp_estab, ratio)
            SELECT year, zipcode, category, source, poi_count, poi_count_single_source, zbp_estab, ratio
            FROM _zcbs
        """)
    finally:
        con.unregister("_zcbs")
    del n_base
    return len(out)


def print_by_source_report(con, year: int | None = None, console=None) -> pd.DataFrame:
    """Print, per category: total Loci POIs vs ZBP, then per source: POI
    count, share of the category's POIs, share that are single-source, and
    the ratio that would remain if that source's SINGLE-SOURCE records were
    dropped -- (category_total_poi - that_source's_single_source_poi) /
    category_total_zbp. Returns the analysis.zip_coverage_by_source DataFrame
    for `year` (or the latest year, if not given)."""
    build_coverage_by_source(con, year)
    used_year = con.execute("SELECT max(year) FROM analysis.zip_coverage_by_source").fetchone()[0]
    df = con.execute(
        "SELECT * FROM analysis.zip_coverage_by_source WHERE year = ?", [used_year]
    ).df()
    base = con.execute(
        "SELECT * FROM analysis.zip_coverage_check WHERE year = ?", [used_year]
    ).df()

    def emit(line: str) -> None:
        if console is not None:
            console.print(line)
        else:
            print(line)

    emit(f"analysis.zip_coverage_by_source: {len(df)} rows (year={used_year})")
    for cat, cat_base in base.groupby("category"):
        total_poi = int(cat_base["poi_count"].sum())
        total_zbp = int(cat_base["zbp_estab"].sum())
        overall_ratio = total_poi / total_zbp if total_zbp else float("nan")
        emit(f"\n{cat}: total_poi={total_poi}  total_zbp={total_zbp}  ratio={overall_ratio:.2f}")
        emit(f"  {'source':32} {'poi':>7} {'share':>7} {'single-src':>11} "
             f"{'ratio_if_dropped':>16}")
        cat_src = df[df["category"] == cat]
        by_source = cat_src.groupby("source").agg(
            poi_count=("poi_count", "sum"),
            single_source=("poi_count_single_source", "sum"),
        ).reset_index().sort_values("poi_count", ascending=False)
        for _, row in by_source.iterrows():
            share = row["poi_count"] / total_poi if total_poi else float("nan")
            single_share = row["single_source"] / row["poi_count"] if row["poi_count"] else float("nan")
            ratio_dropped = (total_poi - row["single_source"]) / total_zbp if total_zbp else float("nan")
            emit(f"  {row['source']:32} {int(row['poi_count']):>7} {share:>7.0%} "
                 f"{single_share:>11.0%} {ratio_dropped:>16.2f}")

    return df


def build_coverage_check(con, year: int | None = None, *,
                         supply_set: str = "all",
                         boroughs: tuple[str, ...] | None = None,
                         write: bool = True) -> int:
    """Build analysis.zip_coverage_check for `year` (the ZBP vintage; defaults
    to the latest ingested). Applies the population >= 1,000 and
    "ZBP row present" (not-suppressed) exclusions AT WRITE TIME, so the table
    itself is already the clean comparison set. Returns the row count written.

    `supply_set` (sql/003_supply_sets.sql) and `boroughs` narrow the Loci side
    for the D47 supply-set comparison. **They are only ever computed, never
    persisted** -- `write` is forced FALSE for any non-default combination, so
    analysis.zip_coverage_check keeps meaning exactly what its schema comment
    says (all canonical POIs, citywide). A per-set variant written into that
    table would be indistinguishable from the canonical one downstream.
    """
    if supply_set != "all" or boroughs:
        write = False
    if year is None:
        year = con.execute("SELECT max(year) FROM analysis.zip_category_establishments").fetchone()[0]
        if year is None:
            raise RuntimeError("analysis.zip_category_establishments is empty -- run `loci ingest-zbp` first.")

    crosswalk = _hex_zip_crosswalk(con)
    poi = _poi_counts_by_zip_category(con, crosswalk, supply_set)
    pop = _population_by_zip(con, crosswalk)

    zbp = con.execute(
        "SELECT zipcode, category, estab_total FROM analysis.zip_category_establishments WHERE year = ?",
        [year],
    ).df()

    merged = zbp.merge(pop, on="zipcode", how="left").merge(
        poi, on=["zipcode", "category"], how="left"
    )
    merged["poi_count"] = merged["poi_count"].fillna(0).astype(int)
    if boroughs:
        bor = _zip_boroughs(con, crosswalk)
        keep = set(bor[bor["borough"].isin(boroughs)]["zipcode"])
        merged = merged[merged["zipcode"].isin(keep)].copy()
    merged = merged[merged["population"].fillna(0) >= LOW_POP_CUTOFF].copy()
    # "ZBP estab suppressed" for our purposes: no estab_total in the response
    # for this (zip, category) -- see census_zbp.py's suppression note.
    merged = merged[merged["estab_total"].notna()].copy()
    merged["ratio"] = merged["poi_count"] / merged["estab_total"].replace(0, pd.NA)

    out = merged[["zipcode", "category", "poi_count", "estab_total", "ratio"]].rename(
        columns={"estab_total": "zbp_estab"}
    )
    out.insert(0, "year", year)

    if not write:
        # Hand the caller the frame without touching the persisted table.
        con.register("_zcc_scratch", out)
        try:
            con.execute("CREATE OR REPLACE TEMP TABLE _zcc_last AS SELECT * FROM _zcc_scratch")
        finally:
            con.unregister("_zcc_scratch")
        return len(out)

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


def supply_set_table(con, year: int | None = None, *,
                     boroughs: tuple[str, ...] | None = None,
                     sets: tuple[str, ...] = tuple(SUPPLY_SETS)) -> pd.DataFrame:
    """category x supply_set -> (poi_count, zbp_estab, ratio), summed over the
    comparable ZIPs. The ZBP side is IDENTICAL across sets by construction (the
    same population and suppression filters run before the supply predicate is
    applied), so differences in `ratio` are attributable to the supply set
    alone. Writes nothing."""
    rows = []
    for s in sets:
        build_coverage_check(con, year, supply_set=s, boroughs=boroughs, write=False)
        df = con.execute("SELECT * FROM _zcc_last").df()
        g = df.groupby("category").agg(poi_count=("poi_count", "sum"),
                                       zbp_estab=("zbp_estab", "sum"),
                                       n_zips=("zipcode", "nunique")).reset_index()
        g["supply_set"] = s
        rows.append(g)
    out = pd.concat(rows, ignore_index=True)
    out["ratio"] = out["poi_count"] / out["zbp_estab"].replace(0, pd.NA)
    return out[["category", "supply_set", "poi_count", "zbp_estab", "ratio", "n_zips"]]


def run_comparison(con, year: int | None = None, console=None, by_source: bool = False,
                   supply_set: str = "all", boroughs: tuple[str, ...] | None = None,
                   supply_sets: bool = False) -> pd.DataFrame:
    """Build (or rebuild) analysis.zip_coverage_check and print the per-
    category summary + the top-5 undercovered ZIPs for hardware/fitness/clinic.
    With by_source=True, also build analysis.zip_coverage_by_source and print
    the per-category x per-source attribution report (returns THAT DataFrame
    instead). Returns the underlying DataFrame for programmatic use (e.g. tests)."""
    persisted = supply_set == "all" and not boroughs
    n = build_coverage_check(con, year, supply_set=supply_set, boroughs=boroughs)
    if persisted:
        used_year = con.execute("SELECT max(year) FROM analysis.zip_coverage_check").fetchone()[0]
        df = con.execute("SELECT * FROM analysis.zip_coverage_check WHERE year = ?",
                         [used_year]).df()
    else:
        df = con.execute("SELECT * FROM _zcc_last").df()
        used_year = int(df["year"].iloc[0]) if len(df) else year

    def emit(line: str) -> None:
        if console is not None:
            console.print(line)
        else:
            print(line)

    scope = f"supply_set={supply_set}" + (f" boroughs={'+'.join(boroughs)}" if boroughs else "")
    emit(f"zip coverage check: {n} rows (year={used_year}, {scope}"
         f"{'' if persisted else ', NOT persisted'})")
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

    if supply_sets:
        emit("")
        tbl = supply_set_table(con, used_year, boroughs=boroughs, sets=SCREENING_SETS)
        emit(f"{'category':14} {'all':>8} {'principled':>11} {'corrob':>8}   "
             f"{'r_all':>6} {'r_prin':>7} {'r_corr':>7}  {'zbp':>6}  flag")
        wide = tbl.pivot(index="category", columns="supply_set",
                         values=["poi_count", "ratio"])
        zbp = tbl.groupby("category")["zbp_estab"].max()
        flagged = []
        for cat in sorted(wide.index):
            rp = wide.loc[cat, ("ratio", "principled")]
            # PRINCIPLED is the set the screen runs on, so it is the only one
            # whose distance from the Census count is a finding rather than a
            # diagnostic. 0.5 / 2.5 are the bands D47 used, widened on the top
            # side because ZBP's NAICS grain is known to under-split the
            # personal-services and food categories.
            flag = ("UNDER" if rp < PRINCIPLED_UNDER
                    else "OVER" if rp > PRINCIPLED_OVER else "")
            if flag:
                flagged.append((cat, flag, rp))
            emit(f"{cat:14} "
                 f"{int(wide.loc[cat, ('poi_count', 'all')]):>8} "
                 f"{int(wide.loc[cat, ('poi_count', 'principled')]):>11} "
                 f"{int(wide.loc[cat, ('poi_count', 'corroborated')]):>8}   "
                 f"{wide.loc[cat, ('ratio', 'all')]:>6.2f} "
                 f"{rp:>7.2f} "
                 f"{wide.loc[cat, ('ratio', 'corroborated')]:>7.2f}  "
                 f"{int(zbp[cat]):>6}  {flag}")
        # NESTING IS A PROPERTY, NOT A HOPE: assert it on the real numbers so a
        # future edit to the view cannot quietly make PRINCIPLED stricter than
        # CORROBORATED (which would delete supply instead of relaxing a filter).
        bad = [c for c in wide.index
               if not (wide.loc[c, ("poi_count", "corroborated")]
                       <= wide.loc[c, ("poi_count", "principled")]
                       <= wide.loc[c, ("poi_count", "all")])]
        if bad:
            raise RuntimeError(
                "supply-set nesting violated (CORROBORATED <= PRINCIPLED <= ALL) "
                f"for: {', '.join(sorted(bad))} -- sql/006_principled_supply.sql")
        emit(f"\nnesting CORROBORATED <= PRINCIPLED <= ALL holds for all "
             f"{len(wide)} categories.")
        if flagged:
            emit(f"flagged (PRINCIPLED/ZBP outside [{PRINCIPLED_UNDER}, "
                 f"{PRINCIPLED_OVER}]):")
            for cat, flag, rp in flagged:
                emit(f"  {cat:14} {flag:5} ratio={rp:.2f}")
        else:
            emit("no category outside the PRINCIPLED/ZBP band.")
        return tbl

    if by_source:
        emit("")
        # --by-source persists analysis.zip_coverage_by_source, which is only
        # defined for the canonical citywide all-POI set.
        if not persisted:
            raise ValueError(
                "--by-source is defined only for the default supply set and citywide "
                "scope (it writes analysis.zip_coverage_by_source, whose schema comment "
                "says 'all canonical POIs'). Drop --supply-set/--borough, or use "
                "--supply-sets for the comparison table."
            )
        return print_by_source_report(con, used_year, console=console)

    return df
