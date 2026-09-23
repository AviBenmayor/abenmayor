"""Loader for RQ-001 (regime durability) staged parquet panels (GTM-224).

Lands the parquet under `data/interim/rq001/{macro,zillow,acs_zcta,lodes,
pluto,irs_soi}/` -- produced by the RQ-001 data-audit adapters and already
validated caveat-by-caveat in
`docs/research/RQ-001-regime-durability/drafts/*.sql.draft` -- into the six
tables declared by migrations `sql/060_rq001_macro_income.sql`,
`sql/061_rq001_cost_landuse.sql`, and `sql/062_rq001_demand.sql`.

There is no `loci` CLI subcommand for this yet (GTM-217/GTM-224 will add
one); run it directly:

    uv run python -c "from loci.sources.rq001_load import main; main()"

`load_all(con)` replaces each table's contents from its parquet file
(DELETE + INSERT, matching the CREATE ... IF NOT EXISTS / idempotent
convention the rest of `sql/` uses -- see `db.init_schema`) and prints a row
count per table. It does not call `db.init_schema` itself; `main()` does
that first so the tables exist.
"""
from __future__ import annotations

import pathlib

import duckdb

from loci import db

RQ001_DIR = db.REPO_ROOT / "data" / "interim" / "rq001"

# (table, parquet path, SELECT expression -- casts/renames applied at load
# time so the parquet's native dtypes don't have to match the warehouse
# schema exactly; e.g. Zillow's monthly `month` column is TIMESTAMP_NS
# upstream and DATE in the warehouse, LODES's job counts are DOUBLE upstream
# and BIGINT in the warehouse per sql/062's grain note).
_LOADS: list[tuple[str, pathlib.Path, str]] = [
    (
        "raw.fred_macro_monthly",
        RQ001_DIR / "macro" / "macro_monthly.parquet",
        "SELECT series_id, date, value, freq, units, title, covid_window, "
        "current_timestamp AS loaded_at FROM src",
    ),
    (
        "raw.fred_macro_annual",
        RQ001_DIR / "macro" / "macro_annual.parquet",
        "SELECT series_id, year, value, units, title, rollup, covid_window, "
        "current_timestamp AS loaded_at FROM src",
    ),
    (
        "raw.irs_zip_income_panel",
        RQ001_DIR / "irs_soi" / "irs_zip_income_panel.parquet",
        "SELECT zip, CAST(tax_year AS INTEGER) AS tax_year, "
        "CAST(agi_stub AS INTEGER) AS agi_stub, n1, agi, n_wages, a_wages, "
        "any_suppressed, current_timestamp AS loaded_at FROM src",
    ),
    (
        "raw.zillow_zip_monthly",
        RQ001_DIR / "zillow" / "zillow_nyc_monthly.parquet",
        "SELECT zip, CAST(month AS DATE) AS month, index, value, county_name, "
        "current_timestamp AS loaded_at FROM src",
    ),
    (
        "raw.zillow_zip_annual",
        RQ001_DIR / "zillow" / "zillow_nyc_annual.parquet",
        "SELECT zip, year, index, value_mean, CAST(n_months AS INTEGER) AS n_months, "
        "current_timestamp AS loaded_at FROM src",
    ),
    (
        "analysis.rq001_pluto_zip_vintage",
        RQ001_DIR / "pluto" / "pluto_zip_vintage.parquet",
        "SELECT zipcode, CAST(year AS INTEGER) AS year, pluto_version, "
        "CAST(n_lots AS INTEGER) AS n_lots, bldgarea_total, comarea_total, "
        "retailarea_total, assesstot_total, unitsres_total, "
        "CAST(n_lots_with_retail AS INTEGER) AS n_lots_with_retail, "
        "CAST(dropped_no_zip AS INTEGER) AS dropped_no_zip FROM src",
    ),
    (
        "raw.acs_zcta_panel",
        RQ001_DIR / "acs_zcta" / "acs_zcta_panel.parquet",
        "SELECT zcta, CAST(acs_year AS INTEGER) AS acs_year, "
        "CAST(zcta_geography_vintage AS INTEGER) AS zcta_geography_vintage, "
        "education_table, population_e, population_m, median_hh_income_e, "
        "median_hh_income_m, per_capita_income_e, per_capita_income_m, "
        "workers_16plus_e, workers_16plus_m, occupied_housing_units_e, "
        "occupied_housing_units_m, median_gross_rent_e, median_gross_rent_m, "
        "age_20_34_e, age_20_34_m, age_20_34_share, age_20_34_share_m, "
        "bachelors_plus_denom_e, bachelors_plus_denom_m, bachelors_plus_e, "
        "bachelors_plus_m, bachelors_plus_share, bachelors_plus_share_m, "
        "current_timestamp AS loaded_at FROM src",
    ),
    (
        "analysis.rq001_lodes_wac_zcta",
        RQ001_DIR / "lodes" / "lodes_wac_zcta.parquet",
        "SELECT zcta, year, CAST(c000 AS BIGINT) AS c000, "
        "CAST(cns07 AS BIGINT) AS cns07, CAST(cns18 AS BIGINT) AS cns18, "
        "CAST(n_blocks AS INTEGER) AS n_blocks, block_geography FROM src",
    ),
]


def load_all(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Replace each RQ-001 table's contents from its parquet file.

    DELETE + INSERT per table (not DROP/CREATE -- the tables are created by
    `db.init_schema` via sql/060-062, which this function does not call).
    Returns {table: row_count} and prints the same. Raises (via DuckDB) if a
    parquet file is missing or a row count comes back 0 for a source that
    should not be empty -- this is a one-time land of a fixed 2026-09-22
    pull, not a live API, so failing loud here means failing on any file
    that did not make it to disk, not silently loading a partial table.
    """
    counts: dict[str, int] = {}
    for table, path, select_sql in _LOADS:
        if not path.exists():
            raise FileNotFoundError(f"RQ-001 parquet missing for {table}: {path}")
        con.execute(f"DELETE FROM {table}")
        con.execute(
            f"INSERT INTO {table} {select_sql.replace('FROM src', f'FROM read_parquet(?) AS src')}",
            [str(path)],
        )
        n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if n == 0:
            raise RuntimeError(f"{table} loaded 0 rows from {path} -- refusing a silent empty load")
        counts[table] = n
        print(f"{table}: {n:,} rows")
    return counts


def main() -> None:
    """Apply sql/060-062 (via db.init_schema) then load_all, against the
    default warehouse (data/loci.duckdb, or $LOCI_DB). Opens a single
    short-lived write connection: connect -> init_schema -> load_all ->
    close, per the concurrent-session convention (CHECKPOINT.md) that a
    write connection stays open only as long as it takes to do the write,
    so a peer holding a read-only connection is not blocked longer than
    necessary.
    """
    con = db.connect()
    try:
        db.init_schema(con)
        load_all(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
