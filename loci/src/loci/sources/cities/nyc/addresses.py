"""Residential address ingest for the address-level convenience check.

Source choice: NYC MapPLUTO tax-lot data (already ingested at
data/raw/pluto.csv -- see grid/pluto.py), NOT NYC DCP Address Points/PAD.
PLUTO is already on disk, already carries UnitsRes (the unit-weighting the
convenience report needs), and one tax lot with UnitsRes > 0 IS one
residential building/address for this purpose -- a second geocoded dataset
(Address Points) would add a BBL join for no benefit the way this project
uses "address." Recorded here per the ticket's request to record the choice.

City-specific: BBL, borocode, and the raw PLUTO column names live ONLY in this
module. src/loci/model/conveniences.py consumes plain
(address_id, lon, lat, units) tuples and never sees a PLUTO column name.
"""
from __future__ import annotations

import pathlib

import pandas as pd

from loci.grid.pluto import PLUTO_CSV

# NYC MapPLUTO borocode, per the PLUTO data dictionary (1=Manhattan, 2=Bronx,
# 3=Brooklyn, 4=Queens, 5=Staten Island).
BOROCODE = {"MN": "1", "BX": "2", "BK": "3", "QN": "4", "SI": "5"}

#: The SCREEN's scope, and only the screen's (D48, re-ruled by the owner as D78
#: 2026-09-13: "we are still focused on Manhattan and Brooklyn"). Manhattan and
#: Brooklyn are the two boroughs whose results are read; analysis.address,
#: analysis.address_category and everything derived from them hold these two and
#: nothing else. The DATA FOUNDATION stays citywide on purpose -- raw sources,
#: staging, poi_dedup/poi_supply, the hex tables and
#: analysis.address_demographics are all five boroughs, because a POI in Queens
#: is still the nearest pharmacy to an address in Brooklyn. Declared here, beside
#: BOROCODE, because "MN"/"BK" are NYC codes: model/ and score/ take the scope as
#: an argument and never name a borough.
SCREEN_BOROUGHS: tuple[str, ...] = ("MN", "BK")


def load_residential_addresses(con, borough: str = "MN",
                                pluto_csv: pathlib.Path | str = PLUTO_CSV) -> pd.DataFrame:
    """Every PLUTO tax lot in `borough` with UnitsRes > 0 and usable
    coordinates. FULL COVERAGE, not a sample -- every residential lot/address,
    not a representative draw; `--sample N` (drawn from this, units-weighted)
    lives at the CLI/report layer, downstream of this full set.

    Returns columns: address_id, bbl, lon, lat, units, address.
    address_id is the BBL (unique per tax lot by construction); a lot with a
    blank BBL falls back to a row-index id so it is never silently dropped.
    """
    if borough.upper() not in BOROCODE:
        raise ValueError(f"unknown borough {borough!r}; expected one of {sorted(BOROCODE)}")
    code = BOROCODE[borough.upper()]
    df = con.execute(
        """
        SELECT
            BBL AS bbl,
            address,
            TRY_CAST(latitude  AS DOUBLE) AS lat,
            TRY_CAST(longitude AS DOUBLE) AS lon,
            TRY_CAST(unitsres  AS DOUBLE) AS units
        FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
        WHERE borocode = ?
          AND TRY_CAST(unitsres AS DOUBLE) > 0
          AND TRY_CAST(latitude  AS DOUBLE) IS NOT NULL
          AND TRY_CAST(longitude AS DOUBLE) IS NOT NULL
        """,
        [str(pluto_csv), code],
    ).df()
    # Sanity bbox (five boroughs + a small margin) -- drops the rare bad geocode.
    df = df[df.lat.between(40.4, 41.0) & df.lon.between(-74.3, -73.6)].reset_index(drop=True)
    df["bbl"] = df["bbl"].fillna("").astype(str)
    df["address_id"] = df["bbl"].where(df["bbl"] != "", "row" + df.index.astype(str))
    n_before = len(df)
    df = df.drop_duplicates(subset="address_id").reset_index(drop=True)
    if len(df) != n_before:
        # BBL is unique per tax lot by construction; a collision means a data
        # defect, not an expected case -- worth knowing about, not silently
        # swallowed.
        import warnings
        warnings.warn(f"dropped {n_before - len(df)} duplicate address_id rows from PLUTO {borough}")
    return df[["address_id", "bbl", "lon", "lat", "units", "address"]]
