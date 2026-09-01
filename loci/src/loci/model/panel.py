"""LODES WAC retail-employment panel, block → hex (GTM-36/37).

Consumer-facing retail employment per hex per year, from LODES WAC:
CNS07 (retail trade, NAICS 44-45) + CNS18 (accommodation & food services,
NAICS 72). Blocks are placed via the LODES crosswalk's block centroid
(blklatdd/blklondd) and binned to H3 res-9 in-database (DuckDB h3 extension).

Caveat (threat §7.4): LODES counts JOBS, not establishments, and pre-2020 years
are stochastically area-allocated into 2020 blocks (GTM-63) — so the panel is a
retail-intensity proxy, strongest read as change over time within a hex.
"""
from __future__ import annotations

import pathlib

from loci import db as locidb

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
LODES = REPO_ROOT / "data" / "raw" / "lodes"
XWALK = LODES / "ny_xwalk.csv.gz"


def build_panel(con, years=(2013, 2023)) -> int:
    hexset = "SELECT h3_index FROM analysis.hex"
    total = 0
    for year in years:
        wac = LODES / f"ny_wac_S000_JT00_{year}.csv.gz"
        if not wac.exists():
            raise FileNotFoundError(wac)
        con.execute("DELETE FROM analysis.hex_panel WHERE year = ?", [year])
        con.execute(f"""
            INSERT INTO analysis.hex_panel (h3_index, year, naics, jobs)
            WITH agg AS (
              SELECT h3_h3_to_string(h3_latlng_to_cell(
                       TRY_CAST(x.blklatdd AS DOUBLE), TRY_CAST(x.blklondd AS DOUBLE), 9)) AS h3_index,
                     sum(TRY_CAST(w.CNS07 AS DOUBLE)) AS retail,
                     sum(TRY_CAST(w.CNS18 AS DOUBLE)) AS food
              FROM read_csv('{wac}', ALL_VARCHAR=TRUE) w
              JOIN read_csv('{XWALK}', ALL_VARCHAR=TRUE) x ON w.w_geocode = x.tabblk2020
              GROUP BY 1
            )
            SELECT h3_index, {year}, 'CNS07', retail FROM agg WHERE h3_index IN ({hexset})
            UNION ALL
            SELECT h3_index, {year}, 'CNS18', food FROM agg WHERE h3_index IN ({hexset})
        """)
        n = con.execute("SELECT count(*) FROM analysis.hex_panel WHERE year=? AND naics='CNS07'", [year]).fetchone()[0]
        print(f"  {year}: {n} hexes with retail employment")
        total += n
    return total
