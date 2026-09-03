"""_local_counts / recount_local (GTM-48 bug fix): the coverage-validation local
side must count CANONICAL POIs across ALL ingested sources, not un-deduped
staging.poi restricted to two hardcoded source ids (see sample.py docstring)."""
import datetime as dt

from loci import db as locidb
from loci.validation.sample import _local_counts, recount_local

LAT, LON = 40.7000, -73.9000  # test point; ~0 m from itself


def _fixture():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("""INSERT INTO analysis.hex (h3_index, geom, centroid, land_fraction)
        VALUES ('h1', ST_Point(?, ?), ST_Point(?, ?), 1.0)""", [LON, LAT, LON, LAT])
    return con


def _add_poi(con, poi_id, source_id, category, canonical, lat=LAT, lon=LON):
    con.execute("""INSERT INTO staging.poi (poi_id, source_id, category, tier, geom)
        VALUES (?, ?, ?, 1, ST_Point(?, ?))""", [poi_id, source_id, category, lon, lat])
    con.execute("""INSERT INTO analysis.poi_dedup (poi_id, cluster_id, is_canonical, category)
        VALUES (?, ?, ?, ?)""", [poi_id, hash(poi_id) % 10_000, canonical, category])


def test_canonical_total_spans_all_sources_and_excludes_duplicates():
    con = _fixture()
    # two DIFFERENT businesses, canonical, from two different ingested sources
    _add_poi(con, "overture_places:1", "overture_places", "clinic", True)
    _add_poi(con, "foursquare_os_places:2", "foursquare_os_places", "clinic", True)
    # a THIRD poi that duplicates one of the above (same underlying business),
    # marked non-canonical by dedup -> must NOT be counted
    _add_poi(con, "osm_overpass:3", "osm_overpass", "clinic", False)
    # a fourth, canonical, but a DIFFERENT category -> must not leak in
    _add_poi(con, "overture_places:4", "overture_places", "grocery", True)

    n_ov, n_osm, n_city, n_canon = _local_counts(con, LAT, LON, "clinic")
    assert n_canon == 2                 # both canonical clinics, across both sources
    assert n_ov == 1                    # legacy per-source columns still per-source
    assert n_osm == 1                   # (the duplicate, un-deduped, still shows here)


def test_canonical_total_is_zero_when_nothing_canonical_nearby():
    con = _fixture()
    _add_poi(con, "overture_places:1", "overture_places", "clinic", False)
    _, _, _, n_canon = _local_counts(con, LAT, LON, "clinic")
    assert n_canon == 0


def test_recount_local_backfills_existing_rows_without_touching_ground_truth():
    con = _fixture()
    _add_poi(con, "overture_places:1", "overture_places", "clinic", True)
    _add_poi(con, "foursquare_os_places:2", "foursquare_os_places", "clinic", True)
    con.execute("""INSERT INTO analysis.coverage_validation
        (h3_index, category, income_decile, n_ground_truth, n_overture, n_osm, sampled_on)
        VALUES ('h1', 'clinic', 5, 7, 0, 0, ?)""", [dt.date.today()])

    n = recount_local(con)
    assert n == 1
    row = con.execute("""SELECT n_ground_truth, n_local_canonical FROM analysis.coverage_validation
        WHERE h3_index = 'h1' AND category = 'clinic'""").fetchone()
    assert row[0] == 7            # n_ground_truth (Google) untouched
    assert row[1] == 2            # backfilled from the canonical layer, both sources
