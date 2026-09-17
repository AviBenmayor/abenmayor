"""The bathhouse_sauna NAME-TERM RULE (GTM-198 / GTM-199, 2026-09-17).

Every real NYC bathhouse Overture carries is tagged `spas` / `health_spa` /
`day_spa` (nails_beauty's population) and every Foursquare one sits in the
"Spa" leaf, so the narrow definition can only be applied inside those sub-tags
by NAME. Three things are pinned:

  (a) the pattern and the sub-tag list in src/loci/categories.yaml are byte-
      identical to sources/base.py's constants -- one rule, two readers;
  (b) both adapters route a spa-sub-tagged record whose name says bathhouse/
      banya/sauna to `bathhouse_sauna`, and leave a nail spa in nails_beauty;
  (c) the rule NEVER fires outside the listed sub-tags ("bath" is a shop,
      "sauna" a gym room), and Overture `public_bath_houses` (NYC Parks
      comfort stations, 63 of 63 in MN+BK per GTM-199) is never mapped.
"""
from __future__ import annotations

import pathlib

import yaml

from loci.sources.base import (
    BATHHOUSE_NAME_EXCLUDE,
    BATHHOUSE_NAME_SUBTAGS,
    BATHHOUSE_NAME_TERMS,
    bathhouse_by_name,
    bathhouse_name_excluded,
)
from loci.sources.universal.foursquare_places import map_leaf
from loci.sources.universal.overture_places import OverturePlacesAdapter

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "loci"


def _yaml_row() -> dict:
    return yaml.safe_load((PKG / "categories.yaml").read_text())["categories"]["bathhouse_sauna"]


# --------------------------------------------------------------------- (a)
def test_yaml_pattern_and_subtags_mirror_the_code_constants():
    row = _yaml_row()
    assert row["name_terms"] == BATHHOUSE_NAME_TERMS
    assert row["name_terms_exclude"] == BATHHOUSE_NAME_EXCLUDE
    assert {k: set(v) for k, v in row["name_terms_apply_to"].items()} == {
        k: set(v) for k, v in BATHHOUSE_NAME_SUBTAGS.items()}


# --------------------------------------------------------------------- (b)
def test_overture_spa_subtag_with_a_bathhouse_name_is_the_bathhouse():
    cat = OverturePlacesAdapter._category_for
    assert cat("spas", "Othership") == "bathhouse_sauna"
    assert cat("health_spa", "Bathhouse") == "bathhouse_sauna"
    assert cat("spas", "Russian & Turkish Baths") == "bathhouse_sauna"
    assert cat("day_spa", "World Spa") == "bathhouse_sauna"
    assert cat("spas", "Brooklyn Banya") == "bathhouse_sauna"
    # owner 2026-09-17: "day spa out UNLESS bathing is the primary offer" --
    # these three are day-spa-tagged and count, so they are brand include terms
    assert cat("day_spa", "Juvenex Spa") == "bathhouse_sauna"
    assert cat("spas", "Great Jones Spa") == "bathhouse_sauna"
    assert cat("day_spa", "Fountain of Youth Spa") == "bathhouse_sauna"
    # a nail spa stays where it was
    assert cat("spas", "Lotus Nail Spa") == "nails_beauty"
    assert cat("day_spa", "Serenity Day Spa") == "nails_beauty"
    # the two native tags map without a name at all
    assert cat("sauna", None) == "bathhouse_sauna"
    assert cat("onsen", None) == "bathhouse_sauna"
    assert cat("sauna", "Akari Sauna") is None            # private-suite studio: excluded
    assert cat("sauna", "HigherDOSE") is None
    assert cat("spas", "Perspire Sauna Studio Flatiron") == "nails_beauty"   # excluded from the slug; the sub-tag keeps its old home
    assert cat("spas", "Bath & Body Works") == "nails_beauty"   # the retail false positive stays put
    assert cat("spas", "Bella Bath and Body") == "nails_beauty"


def test_foursquare_spa_leaf_with_a_bathhouse_name_is_the_bathhouse():
    spa = ["Business and Professional Services > Health and Beauty Service > Spa"]
    assert map_leaf(spa, "World Spa") == "bathhouse_sauna"
    assert map_leaf(spa, "Bathhouse Flatiron") == "bathhouse_sauna"
    assert map_leaf(spa, "QC NY") == "bathhouse_sauna"
    assert map_leaf(spa, "Polished Nail Spa") == "nails_beauty"
    assert map_leaf(spa) == "nails_beauty"          # no name: unchanged behaviour
    # the two leaves that were unmapped before 2026-09-17 (Brooklyn Bathhouse,
    # Lore, Othership Williamsburg never entered staging.poi -- GTM-199 §3)
    assert map_leaf(["Sports and Recreation > Sauna"], "Othership") == "bathhouse_sauna"
    assert map_leaf(["Business and Professional Services > Health and Beauty Service > Bath House"],
                    "Brooklyn Bathhouse") == "bathhouse_sauna"


# --------------------------------------------------------------------- (c)
def test_the_exclusion_list_marks_what_the_definition_does_not_count():
    for name in ("HigherDOSE", "Perspire Sauna Studio", "beem Light Sauna - Park Slope",
                 "Sauna at Equinox Rockefeller Center", "Crunch Sauna Room",
                 "Barclay Tower Pool, Hot Tub & Sauna", "Nuru Massage NYC",
                 "Bath & Body Works", "Area Infrared Sauna", "HotBox Mobile Sauna"):
        assert bathhouse_name_excluded(name), name
    for name in ("Bathhouse Flatiron", "Russian & Turkish Baths", "World Spa", "Othership",
                 "Brooklyn Banya", "Spa Castle", "AIRE Ancient Baths", "Mermaid Spa"):
        assert not bathhouse_name_excluded(name), name
    spa = ["Business and Professional Services > Health and Beauty Service > Spa"]
    assert map_leaf(["Sports and Recreation > Sauna"], "Sauna at Equinox Rockefeller Center") is None
    assert map_leaf(spa, "HigherDOSE") == "nails_beauty"   # excluded from the slug, unchanged otherwise


def test_the_rule_never_fires_outside_the_listed_subtags():
    assert not bathhouse_by_name("overture", "cosmetics_store", "Bath & Body Works")
    assert not bathhouse_by_name("overture", "gym", "Equinox Sauna Level")
    assert not bathhouse_by_name("foursquare", "gym", "Crunch Sauna Room")
    assert not bathhouse_by_name("overture", "spas", None)
    assert OverturePlacesAdapter._category_for("gym", "Equinox Sauna") == "fitness"
    assert OverturePlacesAdapter._category_for("hair_salon", "Banya Cuts") == "hair_barber"


def test_public_bath_houses_is_never_mapped():
    assert OverturePlacesAdapter._category_for("public_bath_houses", "Public Restroom") is None
    assert OverturePlacesAdapter._category_for("public_bath_houses", "Shore Road Field House") is None
    assert OverturePlacesAdapter._category_for("private_association", "Lore Bathing Club") is None
