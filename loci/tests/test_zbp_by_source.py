"""Tests for `loci zbp-compare --by-source` (QUESTIONS.md M9 follow-up):
analysis.zip_coverage_by_source must attribute analysis.zip_coverage_check's
poi_count across sources without losing or double-counting rows, and
poi_count_single_source must never exceed poi_count.

Uses a fixture crosswalk (monkeypatched over the real PLUTO-lot majority-vote
crosswalk in src/loci/model/zbp_compare.py) so the test never touches the real
PLUTO CSV -- only the join logic and dedup-cluster arithmetic are exercised.
"""
from __future__ import annotations

import h3
import pandas as pd
import pytest

from loci import db as locidb
from loci.model import zbp_compare as zc

RES = 9
# Two points inside the same H3 res-9 cell so both zips get a stable single-hex
# crosswalk entry without relying on real geography.
LAT_A, LON_A = 40.750, -73.995   # zip 10001 (population qualifies)
LAT_B, LON_B = 40.720, -73.985   # zip 10002 (population below the 1,000 cutoff)
HEX_A = h3.latlng_to_cell(LAT_A, LON_A, RES)
HEX_B = h3.latlng_to_cell(LAT_B, LON_B, RES)


@pytest.fixture
def con(monkeypatch):
    c = locidb.connect(":memory:")
    locidb.init_schema(c)

    # ---- fixture crosswalk: bypass the real PLUTO-lot majority vote ----
    crosswalk = pd.DataFrame({"h3_index": [HEX_A, HEX_B], "zipcode": ["10001", "10002"]})
    monkeypatch.setattr(zc, "_hex_zip_crosswalk", lambda con, pluto_csv=None: crosswalk)

    # ---- population: 10001 qualifies (>= 1,000), 10002 does not ----
    # analysis.hex_demographics FKs to analysis.hex, so a minimal hex row is
    # needed too even though _population_by_zip never reads analysis.hex itself.
    c.execute("""
        INSERT INTO analysis.hex (h3_index, resolution, geom, centroid, land_fraction)
        VALUES (?, 9, ST_Point(?, ?), ST_Point(?, ?), 1.0),
               (?, 9, ST_Point(?, ?), ST_Point(?, ?), 1.0)
    """, [HEX_A, LON_A, LAT_A, LON_A, LAT_A, HEX_B, LON_B, LAT_B, LON_B, LAT_B])
    c.execute("""
        INSERT INTO analysis.hex_demographics (h3_index, acs_year, population)
        VALUES (?, 2023, 5000.0), (?, 2023, 50.0)
    """, [HEX_A, HEX_B])

    # ---- ZBP: nails_beauty has 2 establishments in 10001, none tracked for 10002 ----
    c.execute("""
        INSERT INTO analysis.zip_category_establishments (year, zipcode, category, estab_total)
        VALUES (2023, '10001', 'nails_beauty', 2)
    """)

    # ---- POIs: three canonical nail salons in zip 10001 ----
    # Cluster A: one record, nys_dos only -> single-source, canonical source = nys_dos.
    # Cluster B: two records (nys_dos + overture) -> corroborated; canonical = nys_dos
    #            (source_rank ranks the NYS DOS anchor ahead of overture for nails_beauty).
    # Cluster C: one record, overture only -> single-source, canonical source = overture.
    rows = [
        ("poi_a1", "nys_dos_appearance_enhancement", "cluster_a", True),
        ("poi_b1", "nys_dos_appearance_enhancement", "cluster_b", True),
        ("poi_b2", "overture_places", "cluster_b", False),
        ("poi_c1", "overture_places", "cluster_c", True),
    ]
    for poi_id, source_id, _cluster, _canon in rows:
        c.execute("""
            INSERT INTO staging.poi (poi_id, source_id, category, tier, name, geom, confidence)
            VALUES (?, ?, 'nails_beauty', 1, ?, ST_Point(?, ?), 0.8)
        """, [poi_id, source_id, poi_id, LON_A, LAT_A])
    cluster_ids = {"cluster_a": 1, "cluster_b": 2, "cluster_c": 3}
    for poi_id, _source_id, cluster, canon in rows:
        c.execute("""
            INSERT INTO analysis.poi_dedup (poi_id, cluster_id, is_canonical, category)
            VALUES (?, ?, ?, 'nails_beauty')
        """, [poi_id, cluster_ids[cluster], canon])

    yield c
    c.close()


def test_by_source_sums_to_base_poi_count(con):
    zc.run_comparison(con, year=2023, by_source=True)

    base = con.execute("""
        SELECT zipcode, category, poi_count FROM analysis.zip_coverage_check
        WHERE year = 2023
    """).df()
    by_source = con.execute("""
        SELECT zipcode, category, source, poi_count, poi_count_single_source
        FROM analysis.zip_coverage_by_source WHERE year = 2023
    """).df()

    # Only zip 10001 clears the population >= 1,000 cutoff.
    assert set(base["zipcode"]) == {"10001"}
    assert set(by_source["zipcode"]) == {"10001"}

    base_poi = int(base.loc[base["category"] == "nails_beauty", "poi_count"].iloc[0])
    assert base_poi == 3   # cluster A canonical + cluster B canonical + cluster C canonical

    grouped = by_source.groupby(["zipcode", "category"])["poi_count"].sum()
    for (zipcode, category), total in grouped.items():
        base_row = base[(base["zipcode"] == zipcode) & (base["category"] == category)]
        assert total == int(base_row["poi_count"].iloc[0])


def test_single_source_never_exceeds_poi_count(con):
    df = zc.run_comparison(con, year=2023, by_source=True)
    assert (df["poi_count_single_source"] <= df["poi_count"]).all()


def test_single_source_attribution_by_source(con):
    zc.run_comparison(con, year=2023, by_source=True)
    by_source = con.execute("""
        SELECT source, poi_count, poi_count_single_source
        FROM analysis.zip_coverage_by_source
        WHERE year = 2023 AND zipcode = '10001' AND category = 'nails_beauty'
    """).df().set_index("source")

    dos = by_source.loc["nys_dos_appearance_enhancement"]
    assert int(dos["poi_count"]) == 2             # cluster A + cluster B's canonical
    assert int(dos["poi_count_single_source"]) == 1   # cluster A only (cluster B is corroborated)

    overture = by_source.loc["overture_places"]
    assert int(overture["poi_count"]) == 1            # cluster C's canonical
    assert int(overture["poi_count_single_source"]) == 1   # cluster C is single-source
