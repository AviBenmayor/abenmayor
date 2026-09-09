"""Validation geometry: the Google validator's straight-line radius is DERIVED
from the gap screen's network threshold and NYC's measured circuity, never
hardcoded (QUESTIONS M8, CHECKPOINT D53; GTM-105 audit finding D).

Two failure modes these tests exist to catch:
  (a) someone edits the derivation and the radius silently changes;
  (b) someone edits src/loci/reach_tiers.yaml and the code no longer agrees
      with it (or vice versa), so runs are measured at a radius the config
      does not describe.
"""
import datetime as dt

import yaml

from loci import db as locidb
from loci.reach import REACH_TIERS_PATH, load_validation_geometry, validation_radius_m
from loci.validation import google_places
from loci.validation import sample as smp


def _yaml_validation_block() -> dict:
    return yaml.safe_load(REACH_TIERS_PATH.read_text())["validation"]


# ---- (a) the derivation is pinned -------------------------------------------

def test_derivation_is_network_threshold_over_circuity():
    """radius = round(network_threshold_m / circuity). Pinned at the values
    adopted by D53: an 800 m NETWORK threshold and a circuity of 1.233
    measured on analysis.hex_poi_distance (median network_m / straight_line_m
    over the 949,334 hex-POI pairs in the 700-900 m network band), giving
    649 m. If this test fails, the validator is about to measure a different
    circle than every row already in analysis.coverage_validation."""
    v = load_validation_geometry()
    assert v["network_threshold_m"] == 800.0
    assert v["circuity"] == 1.233
    assert v["radius_m"] == round(800.0 / 1.233) == 649
    assert validation_radius_m() == 649


def test_radius_is_strictly_inside_the_network_threshold():
    """A straight-line disc must be SMALLER than the network threshold it
    stands in for -- the whole point of the correction. A circuity of 1.0
    would reinstate the pre-D53 bug (800 m straight-line vs an 800 m network
    screen), so the loader refuses it."""
    v = load_validation_geometry()
    assert v["circuity"] >= 1.0
    assert 0 < v["radius_m"] < v["network_threshold_m"]


def test_loader_rejects_a_circuity_below_one(tmp_path, monkeypatch):
    import loci.reach as reach
    doc = yaml.safe_load(REACH_TIERS_PATH.read_text())
    doc["validation"]["circuity"] = 0.9
    doc["validation"].pop("derived_radius_m", None)
    bad = tmp_path / "reach_tiers.yaml"
    bad.write_text(yaml.safe_dump(doc))
    monkeypatch.setattr(reach, "REACH_TIERS_PATH", bad)
    try:
        reach.load_validation_geometry()
    except ValueError as e:
        assert "circuity" in str(e)
    else:
        raise AssertionError("a circuity below 1.0 must be rejected")


def test_loader_rejects_a_pinned_radius_that_disagrees_with_the_derivation(tmp_path, monkeypatch):
    """The yaml carries derived_radius_m as a human-readable expectation.
    Editing circuity without editing it (or the reverse) must fail loudly."""
    import loci.reach as reach
    doc = yaml.safe_load(REACH_TIERS_PATH.read_text())
    doc["validation"]["derived_radius_m"] = 800
    bad = tmp_path / "reach_tiers.yaml"
    bad.write_text(yaml.safe_dump(doc))
    monkeypatch.setattr(reach, "REACH_TIERS_PATH", bad)
    try:
        reach.load_validation_geometry()
    except ValueError as e:
        assert "derived_radius_m" in str(e)
    else:
        raise AssertionError("a pinned radius contradicting the derivation must be rejected")


# ---- (b) yaml and code must agree -------------------------------------------

def test_yaml_and_code_agree_on_the_radius():
    """Fails if src/loci/reach_tiers.yaml and the constants the validator
    actually uses drift apart. Every call site must resolve to the one derived
    value: google_places.RADIUS_M (the Nearby Search circle),
    sample.RADIUS_M (the local-side counts), nearby_count's default argument,
    and plan()'s reported radius."""
    v = _yaml_validation_block()
    derived = round(float(v["network_threshold_m"]) / float(v["circuity"]))
    assert int(v["derived_radius_m"]) == derived
    assert validation_radius_m() == derived
    assert google_places.RADIUS_M == derived
    assert smp.RADIUS_M == derived
    assert smp.plan([], [])["radius_m"] == derived

    import inspect
    default = inspect.signature(google_places.GooglePlacesClient.nearby_count).parameters["radius_m"].default
    assert default == derived


def test_no_literal_radius_left_in_the_validator():
    """The radius must not be re-hardcoded anywhere in the validation package.
    800 survives only as LEGACY_RADIUS_M -- what PRE-D53 rows were measured at,
    used by recount_local, never by a new call."""
    src = (smp.__file__, google_places.__file__)
    for path in src:
        with open(path) as fh:
            for i, line in enumerate(fh, 1):
                code = line.split("#")[0]
                if "radius" in code.lower() and "800" in code:
                    assert "LEGACY_RADIUS_M" in code, f"{path}:{i} hardcodes a radius: {line!r}"


def test_webmap_reads_the_same_derived_radius():
    """webmap/server.js's "check with Google" button must use the validator's
    disc, not its own literal (D53 flagged radius:800 as drift)."""
    import re
    from pathlib import Path
    js = Path(smp.__file__).resolve().parents[3] / "webmap" / "server.js"
    text = js.read_text()
    assert "radius:800" not in text, "server.js re-hardcodes the legacy 800 m radius"
    assert "radius:RADIUS_M" in text
    assert re.search(r"derived_radius_m", text), "server.js must read derived_radius_m from reach_tiers.yaml"


def test_yaml_records_how_the_circuity_was_obtained():
    """A parameter that changes what every future validation run measures has
    to say where it came from (CLAUDE.md: machine-check the docs against the
    code)."""
    v = _yaml_validation_block()
    assert v.get("circuity_basis") in {"measured", "literature"}
    assert len(str(v.get("circuity_source", ""))) > 200
    assert v.get("measured_on")


# ---- the radius reaches the database ----------------------------------------

class _FakeResp:
    def __init__(self, places): self._places = places
    def raise_for_status(self): pass
    def json(self): return {"places": self._places}


class _FakeSession:
    def __init__(self): self.bodies = []
    def post(self, url, json=None, timeout=None, headers=None):
        self.bodies.append(json)
        return _FakeResp([{"id": "x", "primaryType": "hardware_store", "types": ["hardware_store"]}])


LAT, LON = 40.7000, -73.9000


def test_run_records_the_radius_on_every_row(tmp_path):
    """Rows must be self-describing: an 800 m row and a 649 m row are not
    poolable, and the pre-D53 rows read NULL rather than a wrong default."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("""INSERT INTO analysis.hex (h3_index, geom, centroid, land_fraction)
        VALUES ('h1', ST_Point(?, ?), ST_Point(?, ?), 1.0)""", [LON, LAT, LON, LAT])
    # a legacy row, written before radius_m existed
    con.execute("""INSERT INTO analysis.coverage_validation
        (h3_index, category, income_decile, n_ground_truth, n_overture, n_osm, sampled_on)
        VALUES ('h1', 'grocery', 5, 3, 1, 1, ?)""", [dt.date(2026, 9, 2)])

    sess = _FakeSession()
    client = google_places.GooglePlacesClient(api_key="k", budget=10,
                                              ledger_path=tmp_path / "l.json", session=sess)
    smp.run(con, client, [{"h3_index": "h1", "lat": LAT, "lon": LON, "income_decile": 5}],
            ["hardware"], dry_run=False)

    new = con.execute("SELECT radius_m FROM analysis.coverage_validation "
                      "WHERE category = 'hardware'").fetchone()[0]
    legacy = con.execute("SELECT radius_m FROM analysis.coverage_validation "
                         "WHERE category = 'grocery'").fetchone()[0]
    assert new == validation_radius_m()
    assert legacy is None, "pre-D53 rows must stay NULL, not inherit today's radius"
    # and the circle actually sent to Google is the same number
    assert sess.bodies[0]["locationRestriction"]["circle"]["radius"] == validation_radius_m()


def test_recount_local_re_measures_each_row_at_its_own_radius():
    """recount_local must not shrink the local side of an 800 m row to today's
    radius -- that would manufacture an undercount that never happened. A NULL
    radius_m means a pre-D53 row and is re-measured at LEGACY_RADIUS_M."""
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    con.execute("""INSERT INTO analysis.hex (h3_index, geom, centroid, land_fraction)
        VALUES ('h1', ST_Point(?, ?), ST_Point(?, ?), 1.0)""", [LON, LAT, LON, LAT])
    # a POI ~700 m north: inside the legacy 800 m disc, outside the 649 m one.
    far_lat = LAT + 700.0 / 111_320.0
    con.execute("""INSERT INTO staging.poi (poi_id, source_id, category, tier, geom)
        VALUES ('p1', 'osm_overpass', 'hardware', 1, ST_Point(?, ?))""", [LON, far_lat])
    con.execute("""INSERT INTO analysis.poi_dedup (poi_id, cluster_id, is_canonical, category)
        VALUES ('p1', 1, true, 'hardware')""")

    con.execute("""INSERT INTO analysis.coverage_validation
        (h3_index, category, income_decile, n_ground_truth, n_overture, n_osm, sampled_on, radius_m)
        VALUES ('h1', 'hardware', 5, 1, 0, 0, ?, NULL)""", [dt.date(2026, 9, 2)])
    smp.recount_local(con)
    assert con.execute("SELECT n_local_canonical FROM analysis.coverage_validation").fetchone()[0] == 1

    con.execute("UPDATE analysis.coverage_validation SET radius_m = ?", [validation_radius_m()])
    smp.recount_local(con)
    assert con.execute("SELECT n_local_canonical FROM analysis.coverage_validation").fetchone()[0] == 0
