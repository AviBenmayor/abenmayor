"""LEHD LODES8 WAC, rolled up from census blocks to ZCTA-year (RQ-001 DEMAND
pillar input). Reads the files `lodes_wac.py` already fetched to
`data/raw/lodes/` -- it does not download anything itself.

WHAT THIS BUILDS
---------------------------------------------------------------------------
One row per (zcta, year) with:
  * `c000`  -- total jobs (WAC column C000, all workers)
  * `cns07` -- Retail Trade jobs (NAICS sectors 44-45)
  * `cns18` -- Accommodation & Food Services jobs (NAICS sector 72)

filtered to census blocks in the 5 NYC counties (36005 Bronx, 36047 Kings,
36061 New York, 36081 Queens, 36085 Richmond), for EVERY vintage on disk
(2002-2023 as of 2026-09-16's full pull; see `lodes_wac.py`).

BLOCK -> ZCTA CROSSWALK: the LODES-native xwalk, not a separate Census file
---------------------------------------------------------------------------
The task that produced this module asked for the block aggregated "using the
Census 2020 block->ZCTA relationship file". `data/raw/lodes/ny_xwalk.csv.gz`
(fetched by `lodes_wac.py::download`) already IS that relationship, sourced
from the Census Bureau and shipped by LEHD alongside the WAC files: its
`zcta` column assigns every 2020 census block (`tabblk2020`) to its 2020
ZCTA, and its `cty` column gives the block's county FIPS directly. Verified
2026-09-22 by reading the file's own header and a sample of rows (see
`tests/test_rq001_lodes_pluto.py`): one row per `tabblk2020`, no duplicates,
`zcta` populated for all 37,984 NYC-county blocks (zero blanks). Downloading
a second, independently-sourced Census block/ZCTA relationship file (e.g.
`tab20_zcta520_tabblock20_natl.txt`) and joining through it instead would add
a second crosswalk that could silently disagree with LEHD's own geography
assignment for the same blocks -- worse, not better, for correctness. Using
the xwalk LEHD ships with its own data keeps the block vintage and the ZCTA
vintage internally consistent by construction.

NO BLOCK-VINTAGE BREAK (CONTEXT.md 7.4b) -- VERIFIED, NOT ASSUMED
---------------------------------------------------------------------------
`ny_xwalk.csv.gz` keys its rows by `tabblk2020` and is the SAME single file
LODES ships for every vintage (`lodes_wac.py` module docstring; reconfirmed
here by inspecting the file: one file, 288,819 NY blocks, `tabblk2020` as the
sole block-id column -- no `tabblk2010` or `tabblk2000` column exists to key
an older vintage against). That means every WAC year, 2002 through 2023,
joins against IDENTICAL 2020-block geography and so an IDENTICAL zcta
assignment: aggregating to ZCTA introduces no additional vintage break beyond
the one already documented for LODES itself (the pre-2020 area-retro-
allocation bias, `lodes_wac.py` and CONTEXT.md 7.4b). That bias still governs:
a 2002-2019 trend in this file is a trend in (jobs x allocation), not jobs.

OUTPUT
---------------------------------------------------------------------------
`data/interim/rq001/lodes/lodes_wac_zcta.parquet`, one row per (zcta, year),
plus a `block_geography` provenance string per year (observed vs
area-retro-allocated) so the caveat travels with the artifact and not only
with this docstring.
"""
from __future__ import annotations

import pathlib

import duckdb
import pandas as pd

from loci.sources.universal.lodes_wac import (
    LODES_DIR,
    block_vintage_note,
    vintages,
    wac_filename,
    xwalk_filename,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
OUT_PATH = REPO_ROOT / "data" / "interim" / "rq001" / "lodes" / "lodes_wac_zcta.parquet"

#: The 5 NYC counties (FIPS), matching the LODES xwalk's `cty` column format.
NYC_COUNTIES: tuple[str, ...] = ("36005", "36047", "36061", "36081", "36085")


class LodesZctaRollupError(RuntimeError):
    """Raised on anything that would otherwise silently ingest a hole -- a
    missing vintage file, an xwalk row with no ZCTA, a year producing zero
    NYC rows. Never caught and skipped: see the module the caller reads
    (CONTEXT.md 'fail loud, never ingest a silent zero')."""


def _require_files(years: tuple[int, ...], lodes_dir: pathlib.Path) -> None:
    xwalk_path = lodes_dir / xwalk_filename()
    if not xwalk_path.exists():
        raise LodesZctaRollupError(
            f"{xwalk_path} not found. Run `lodes_wac.download()` first -- "
            "this module only rolls up files already on disk.")
    missing = [y for y in years if not (lodes_dir / wac_filename(y)).exists()]
    if missing:
        raise LodesZctaRollupError(
            f"WAC files missing from {lodes_dir} for years {missing}. Run "
            "`lodes_wac.download()` first; refusing to build a panel with a "
            "silent hole in it.")


def build_zcta_year_panel(years=None, lodes_dir: pathlib.Path = LODES_DIR,
                           progress=None) -> pd.DataFrame:
    """Aggregate C000/CNS07/CNS18 from block to ZCTA, one row per (zcta, year),
    for every requested vintage (default: every vintage on disk, 2002-2023).
    Pure DuckDB SQL over the on-disk .csv.gz files -- no warehouse connection
    opened, `:memory:` only.
    """
    years = vintages(years)
    _require_files(years, lodes_dir)

    con = duckdb.connect(":memory:")
    try:
        xwalk_path = lodes_dir / xwalk_filename()
        # cty is TEXT ("36061"); tabblk2020 is a 15-digit block GEOID. Read
        # ALL_VARCHAR because a couple of xwalk columns mix blanks and
        # numbers (same reason grid/pluto.py reads PLUTO as ALL_VARCHAR).
        con.execute(
            """
            CREATE TEMP TABLE xwalk AS
            SELECT tabblk2020, cty, zcta
            FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
            WHERE cty IN (SELECT UNNEST(?::VARCHAR[]))
            """,
            [str(xwalk_path), list(NYC_COUNTIES)],
        )
        n_blocks, n_blank_zcta = con.execute(
            "SELECT count(*), sum(CASE WHEN zcta IS NULL OR zcta = '' THEN 1 ELSE 0 END) FROM xwalk"
        ).fetchone()
        if n_blocks == 0:
            raise LodesZctaRollupError(
                "xwalk join produced zero NYC-county blocks -- county filter "
                "or xwalk format has drifted from what this module expects.")
        if n_blank_zcta:
            raise LodesZctaRollupError(
                f"{n_blank_zcta} of {n_blocks} NYC-county blocks have no ZCTA "
                "assignment in the LODES xwalk. Previously verified zero "
                "(2026-09-22); refusing to silently drop jobs into an "
                "unassigned bucket -- re-check the xwalk before proceeding.")

        rows: list[pd.DataFrame] = []
        for y in years:
            wac_path = lodes_dir / wac_filename(y)
            df = con.execute(
                """
                SELECT
                    x.zcta AS zcta,
                    CAST(? AS INTEGER) AS year,
                    SUM(w.C000)  AS c000,
                    SUM(w.CNS07) AS cns07,
                    SUM(w.CNS18) AS cns18,
                    COUNT(*)     AS n_blocks
                FROM read_csv_auto(?, ALL_VARCHAR=FALSE) w
                JOIN xwalk x ON x.tabblk2020 = CAST(w.w_geocode AS VARCHAR)
                GROUP BY x.zcta
                """,
                [y, str(wac_path)],
            ).df()
            if df.empty:
                raise LodesZctaRollupError(
                    f"{y}: zero rows after the block->ZCTA join. A vintage "
                    "silently missing from the panel reads downstream as a "
                    "year nobody worked in NYC -- refusing to continue.")
            df["block_geography"] = block_vintage_note(y)
            rows.append(df)
            if progress is not None:
                progress(y, len(df))

        out = pd.concat(rows, ignore_index=True)
        out = out.sort_values(["zcta", "year"]).reset_index(drop=True)
        return out
    finally:
        con.close()


def main() -> None:
    def _progress(year, n_zctas):
        print(f"  {year}: {n_zctas} ZCTAs")

    print("Building LODES WAC ZCTA-year panel (2002-2023, 5 NYC counties)...")
    df = build_zcta_year_panel(progress=_progress)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"wrote {len(df)} rows ({df['zcta'].nunique()} ZCTAs x "
          f"{df['year'].nunique()} years) to {OUT_PATH}")


if __name__ == "__main__":
    main()
