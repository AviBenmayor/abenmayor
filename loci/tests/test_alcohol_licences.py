"""Unit tests for the ALCOHOL OVERLAY (owner decision 2026-09-08).

The overlay draws every active NYS SLA licence as its own map layer, classified
on-premises / off-premises-liquor / off-premises-beer. Three things can go
wrong silently and each gets a test:

  (a) CLASSIFICATION DRIFT. `classify()` degrades an unseen licence type to
      'unknown' on purpose -- an unmapped type must still be a visible dot, not
      a silent drop. That safety net means the pipeline would NEVER fail when
      SLA adds a licence class; it would just quietly grow an "Unclassified"
      pile on the map. This file is the thing that fails instead, against the
      captured NYC vocabulary in fixtures/alcohol/nyc_descriptions.json.

  (b) BOROUGH. The overlay is a separate layer but it still honours the borough
      selector, so the export must filter it the same way as the other two --
      here on the SLA-published county code, no H3 join needed.

  (c) SCOPE. An MN+BK export must contain no Queens/Bronx/Staten Island
      licence. A leak here would put a licence dot next to a gap it has no
      business being near.

Plus the invariant the overlay exists to protect: it is NOT a category, so it
must never appear in staging.poi's category vocabulary or in the 15 exported
category files.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from loci.sources.cities.nyc import nys_sla
from loci.viz import webmap_export as wx

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "alcohol"
NYC_DESCRIPTIONS = json.loads((FIXTURES / "nyc_descriptions.json").read_text())


# ------------------------------------------------------- classification drift

def test_every_live_nyc_licence_type_is_named_by_the_yaml():
    """The drift check. Every licence type observed in the NYC feed must be
    classified BY NAME in alcohol_licences.yaml. When SLA adds a type this
    fails, and the fix is a deliberate on/off-premises call in the yaml -- not
    a shrug into the 'Unclassified' bucket."""
    assert nys_sla.unmapped_descriptions(NYC_DESCRIPTIONS) == set()


def test_drift_check_catches_an_unseen_description():
    """The adversarial half: a test that only ever sees a complete vocabulary
    proves nothing. Inject a type SLA has never issued and the check must name
    it -- as published, so the yaml entry can be pasted from the failure."""
    injected = "Zeppelin Tasting Room"
    assert nys_sla.unmapped_descriptions(
        [*NYC_DESCRIPTIONS, injected]) == {injected}
    # ...and it is still DRAWN, under the honest label, rather than dropped.
    assert nys_sla.classify(injected) == "unknown"


def test_classification_is_case_and_whitespace_insensitive():
    """The feed publishes the same type under several capitalisations
    ("Legitimate theatre" / "Legitimate Theatre"), which is why the lowercased
    description -- not the numeric class code -- is the join key."""
    for variant in ("Legitimate theatre", "Legitimate Theatre",
                    "  legitimate theatre  "):
        assert nys_sla.classify(variant) == "on_premises"


def test_yaml_only_emits_declared_classifications():
    """A typo'd classification would reach the map as a legend entry with no
    label and no colour. load_classification() raises instead."""
    doc = nys_sla.load_classification()
    assert set(doc["descriptions"].values()) <= set(nys_sla.CLASSIFICATIONS)
    assert set(doc["labels"]) == set(nys_sla.CLASSIFICATIONS)


def test_the_three_public_facing_classes_are_populated():
    """The overlay's whole point is on-premises vs off-premises liquor vs
    off-premises beer. If the yaml ever collapsed two of them the map would
    still render -- with one legend row silently empty."""
    by_class: dict[str, int] = {}
    for desc, n in NYC_DESCRIPTIONS.items():
        by_class[nys_sla.classify(desc)] = by_class.get(nys_sla.classify(desc), 0) + n
    for cls in ("on_premises", "off_premises_liquor", "off_premises_beer"):
        assert by_class.get(cls, 0) > 0, cls
    # Grocery/drug stores may sell beer and cider ONLY in NY -- they are not
    # liquor stores, and folding them together would triple the liquor-store
    # count on the map.
    assert nys_sla.classify("Grocery Store") == "off_premises_beer"
    assert nys_sla.classify("Liquor Store") == "off_premises_liquor"


def test_restaurant_licences_are_on_premises_but_still_not_bars():
    """The overlay reclassifies nothing upstream: `Restaurant` is an
    on-premises licence for the overlay AND still outside BAR_DESCRIPTIONS, so
    staging.poi's bar count cannot move because the overlay shipped."""
    assert nys_sla.classify("Restaurant") == "on_premises"
    assert "restaurant" not in nys_sla.BAR_DESCRIPTIONS
    assert nys_sla.BAR_DESCRIPTIONS == {
        "food & beverage business", "summer food & beverage business",
        "club", "cabaret", "bottle club"}


# --------------------------------------------------------------- normalizing

def _row(lid, desc="Restaurant", county="New York", lon=-73.9857, lat=40.7484,
         expires="2030-01-01T00:00:00.000", dba="Joe'S"):
    return {"licensepermitid": lid, "description": desc, "class": "0340",
            "dba": dba, "legalname": "Joe Inc", "premisescounty": county,
            "actualaddressofpremises": "350 5Th Ave", "zipcode": "10118-0110",
            "expirationdate": expires,
            "georeference": {"type": "Point", "coordinates": [lon, lat]}}


def test_normalize_keeps_every_licence_type_and_maps_the_county():
    """Unlike the bar adapter, which keeps five licence types, the overlay keeps
    all of them -- and rewrites SLA's county into the two-letter borough code
    the rest of the project speaks."""
    recs = list(nys_sla.normalize_licences([
        _row("A", "Restaurant", "New York"),
        _row("B", "Liquor Store", "Kings"),
        _row("C", "Wholesale Beer", "Queens"),
    ]))
    assert [(r.licence_id, r.borough, r.classification) for r in recs] == [
        ("A", "MN", "on_premises"), ("B", "BK", "off_premises_liquor"),
        ("C", "QN", "other")]
    assert recs[0].zip == "10118"


def test_normalize_drops_only_what_cannot_be_drawn():
    """No georeference, the (0, 0) sentinel and a duplicate licence id are the
    only reasons to drop a row. Nothing is dropped for its licence TYPE."""
    rows = [_row("A"), _row("A"),                       # duplicate id
            {**_row("B"), "georeference": None},        # no point
            _row("C", lon=0.0, lat=0.0)]                # null island
    assert [r.licence_id for r in nys_sla.normalize_licences(rows)] == ["A"]


def test_active_is_the_expiry_date_not_a_default():
    import datetime as dt
    today = dt.date(2026, 9, 9)
    recs = {r.licence_id: r for r in nys_sla.normalize_licences([
        _row("live", expires="2027-01-01T00:00:00.000"),
        _row("dead", expires="2024-01-01T00:00:00.000"),
        _row("undated", expires=None)], today=today)}
    assert recs["live"].active is True
    assert recs["dead"].active is False
    assert recs["undated"].active is True and recs["undated"].expires_on is None


# --------------------------------------------------------------- the export

@pytest.fixture()
def alccon():
    """A scratch DB holding only what the overlay reads. Deliberately NOT the
    webmap-export fixture: the overlay must be readable without staging.poi,
    analysis.hex or analysis.address_gaps existing at all."""
    from loci import db
    c = db.connect(":memory:")
    c.execute("CREATE SCHEMA staging;")
    c.execute((__import__("loci.db", fromlist=["SQL_DIR"]).SQL_DIR
               / "007_alcohol_licences.sql").read_text())
    return c


def _insert(con, lid, cls, boro, lon=-73.9857, lat=40.7484, active=True,
            desc="Restaurant", name="Joe's", addr="350 5th Ave",
            expires="2030-01-01"):
    con.execute("""INSERT INTO staging.alcohol_licences VALUES
        (?, ?, '0340', ?, ?, ?, '10118', ?, ST_Point(?, ?), CAST(? AS DATE), ?,
         CAST('2026-09-08' AS DATE))""",
        [lid, desc, cls, name, addr, boro, lon, lat, expires, active])


def test_export_respects_the_borough_selector(alccon):
    """MN+BK in, MN+BK out. A Queens licence must not reach the file."""
    _insert(alccon, "mn", "on_premises", "MN")
    _insert(alccon, "bk", "off_premises_beer", "BK", lon=-73.9442, lat=40.6782)
    _insert(alccon, "qn", "on_premises", "QN", lon=-73.7949, lat=40.7282)

    layer = wx.collect_alcohol(alccon, ["MN", "BK"])
    assert layer["available"] is True
    assert layer["ids"] == ["bk", "mn"]          # ORDER BY licence_id
    assert layer["counts"]["on_premises"] == {"MN": 1, "BK": 0}
    assert layer["counts"]["off_premises_beer"] == {"MN": 0, "BK": 1}

    # Widening the filter is the same code path and must pick Queens back up.
    assert wx.collect_alcohol(alccon, ["MN", "BK", "QN"])["ids"] == ["bk", "mn", "qn"]


def test_export_keeps_only_active_licences(alccon):
    """An expired licence is not a place you can buy a drink. The `active`
    column is computed at ingest from the expiry date, and the export trusts
    it -- so this is the test that the filter is actually applied."""
    _insert(alccon, "live", "on_premises", "MN", active=True)
    _insert(alccon, "dead", "on_premises", "MN", active=False, expires="2024-01-01")
    assert wx.collect_alcohol(alccon, ["MN"])["ids"] == ["live"]


def test_export_packs_the_fields_the_popup_needs(alccon):
    """Name, description, address and expiry, decoded the way index.html's
    alcHTML() decodes them."""
    _insert(alccon, "a", "off_premises_liquor", "MN", desc="Liquor Store",
            name="Astor Wines", addr="399 Lafayette St", expires="2028-05-31")
    layer = wx.collect_alcohol(alccon, ["MN"])
    assert layer["names"] == ["Astor Wines"]
    assert layer["addr"] == ["399 Lafayette St"]
    assert layer["vocab"]["desc"][layer["desc"][0]] == "Liquor Store"
    assert layer["vocab"]["expires"][layer["expires"][0]] == "2028-05-31"
    # stride 4: lon, lat, class index, borough index
    assert layer["pts"][2] == layer["classes"].index("off_premises_liquor")
    assert layer["pts"][3] == 0


def test_an_unmapped_classification_is_drawn_as_unknown_not_dropped(alccon):
    """Belt and braces for (a): even if a row reaches the table with a class
    the vocabulary does not carry, the point survives -- as `unknown`."""
    classes = ["on_premises", "unknown"]
    rows = [("x", "brand_new_class", "Zeppelin Tasting Room", "Z", "1 Sky Rd",
             "MN", -73.98, 40.74, "2030-01-01")]
    layer = wx.pack_alcohol(rows, ["MN"], classes, {"unknown": "Unclassified"})
    assert layer["n"] == 1
    assert layer["pts"][2] == classes.index("unknown")


def test_missing_table_degrades_to_an_empty_overlay():
    """`loci ingest-alcohol` is optional and runs separately. An export before
    it must write an empty overlay that says so, not fail the whole export --
    the data-engineer's pipeline run cannot be held hostage by this layer."""
    from loci import db
    c = db.connect(":memory:")
    c.execute("CREATE SCHEMA staging;")
    layer = wx.collect_alcohol(c, ["MN", "BK"])
    assert layer["available"] is False and layer["n"] == 0
    assert layer["classes"] == list(nys_sla.CLASSIFICATIONS)


def test_the_overlay_is_not_a_sixteenth_category():
    """The invariant the whole design rests on: the overlay is a separate file
    and a separate layer, so no category vocabulary anywhere gains an
    alcohol entry and no score, gap or reach number can move."""
    from loci.categories import CATEGORIES
    assert "alcohol" not in CATEGORIES
    assert not set(nys_sla.CLASSIFICATIONS) & set(CATEGORIES)
    assert wx.ALCOHOL_TABLE == ("staging", "alcohol_licences")
