"""The D109 exclusion rule set.

Every rule gets ONE KNOWN EXAMPLE, and the suite asserts BOTH directions:
the class fires on the thing it was written for, and a real chain survives.
The second direction is the one that matters now. Under the 2026-09-15
auto-admission ruling nothing stands between this rule set and the list, so an
over-broad pattern does not cost a reviewer ten seconds -- it deletes a real
lead and reports a tidy count, which is the failure mode nobody notices.

The two data-quality guards are tested on the exact rows that motivated them:
"Cafe" at 60 locations across four boroughs and four sources (a normalizer
collapse, not a chain) and Chestnut Market at 13 locations with `n_boroughs =
0` (an address-resolution gap, not a footprint). Both cleared the numeric
predicate in the 2026-09 candidates preview.
"""
from __future__ import annotations

import pytest

from loci.chains import exclusions as ex
from loci.chains.normalize import brand_key


def _row(key, **kw):
    base = {"brand_key": key, "display_name": key.title(), "loci_category": None,
            "locations_total": 12, "locations_new_12m": 3, "n_boroughs": 3,
            "n_sources": 2, "flagged": True}
    base.update(kw)
    return base


# --------------------------------------------------------------- one per class

EXCLUDED = [
    # (row, expected class name)
    (_row("chase bank", loci_category="bank"),            "bank_clinic_category"),
    (_row("citymd urgent care", loci_category="clinic"),  "bank_clinic_category"),
    (_row("northwell health physician partners"),         "health_systems"),
    (_row("moneygram"),                                   "agent_networks"),
    (_row("western union"),                               "agent_networks"),
    (_row("t mobile"),                                    "wireless_carriers"),
    (_row("at and t"),                                    "wireless_carriers"),
    (_row("icon parking"),                                "parking"),
    (_row("sp"),                                          "parking"),
    (_row("cardtronics atm"),                             "atms"),
    (_row("usps"),                                        "gov_postal"),
    (_row("new york public library"),                     "gov_postal"),
    (_row("shell"),                                       "fuel"),
    (_row("speedway"),                                    "fuel"),
    # --- the data-quality guards, on the rows that motivated them ------------
    (_row("cafe", locations_total=60, n_boroughs=4, n_sources=4), "generic_key"),
    (_row("bar", locations_total=57, n_boroughs=4, n_sources=4),  "generic_key"),
    (_row("food", locations_total=8, n_boroughs=2),               "generic_key"),
    (_row("market plate", locations_total=22, n_boroughs=2),      "generic_key"),
    (_row("chestnut market", locations_total=13, n_boroughs=0),   "geocode_defect"),
]


@pytest.mark.parametrize("row,expected", EXCLUDED,
                         ids=[r["brand_key"] + ":" + c for r, c in EXCLUDED])
def test_each_class_excludes_its_known_example(row, expected):
    rule = ex.exclude_rule(row)
    assert rule is not None, f"{row['brand_key']} was not excluded at all"
    assert rule.name == expected
    assert ex.exclude_reason(row) == rule.reason
    assert rule.reason.strip(), "every class must say WHY in words"


#: Real chains, every one of them from the 2026-09 candidates preview or the
#: shipped watchlist. Not one may be excluded.
KEPT = [
    "raising canes", "super burrito", "shake shack", "sweetgreen",
    "blank street coffee", "chip city cookies", "dos toros taqueria",
    "guacado", "teriyaki one", "moka and co", "allantico vinaio",
    "juici patties", "baya bar", "club pilates", "puregym", "cotti coffee",
    "shahs halal food", "earthbar", "wonder", "vital climbing gym",
    "just salad", "xian famous foods", "toby s estate coffee",
]


@pytest.mark.parametrize("key", KEPT)
def test_real_chains_are_not_excluded(key):
    assert ex.exclude_reason(_row(key)) is None


#: The exact false positives the `exact`-vs-`contains` split exists to prevent.
#: "Shell", "BP" and "Gulf" are ordinary English words, and a substring rule on
#: the fuel class would delete these three restaurants with a gas-station
#: reason -- a wrong answer wearing a correct-looking explanation.
@pytest.mark.parametrize("key", ["gulf coast seafood", "shell cafe and grill",
                                 "bp deli grocery", "spar natural market",
                                 "atmosphere cafe"])
def test_ambiguous_words_do_not_trip_a_class(key):
    reason = ex.exclude_reason(_row(key))
    assert reason is None, f"{key} excluded as {reason!r}"


# ----------------------------------------------------------- the guards, sharply

def test_geocode_guard_needs_locations_not_just_a_zero():
    """A brand with no locations at all is not a geocoding defect -- it is an
    empty row, and labelling it one would put a false diagnosis in the count."""
    assert ex.exclude_reason(_row("empty brand", locations_total=0,
                                  n_boroughs=0)) is None


def test_one_unlocatable_location_is_not_a_defect():
    """analysis.hex is shoreline-clipped, so a pier or an airport terminal
    legitimately has a NULL borough. The guard fires only when NONE resolved."""
    assert ex.exclude_reason(_row("pier brand", locations_total=9,
                                  n_boroughs=1)) is None


def test_generic_plural_of_a_category_word_is_generic():
    assert ex.exclude_rule(_row("cafes")).name == "generic_key"
    assert ex.exclude_rule(_row("delis")).name == "generic_key"


def test_a_generic_word_with_a_modifier_is_a_brand():
    """"Cafe" is a collapse; "Cafe Grumpy" is a company. The rule is about
    BARE category words, and a stoplist that matched any name containing one
    would take out most of the food tier."""
    for key in ("cafe grumpy", "joe coffee", "gristedes", "chestnut market"):
        assert ex.exclude_reason(_row(key, n_boroughs=3)) is None


def test_generic_keys_file_is_the_extension_point():
    """The stoplist is package data so it can be extended without a code
    change, and reading it is a pure function of the file."""
    assert "cafe" in ex.GENERIC_KEYS and "market plate" in ex.GENERIC_KEYS
    assert ex.load_generic_keys(ex.GENERIC_KEYS_PATH) == ex.GENERIC_KEYS


# ------------------------------------------------------------------ drift checks

def test_every_pattern_is_its_own_normalization():
    """A pattern the normalizer would never produce matches NOTHING and
    silently disables its own class. Matching is on `brand_key`, so every
    literal here has to be a fixed point of `brand_key`."""
    bad = [p for p in ex.all_patterns() if brand_key(p) != p]
    assert not bad, f"patterns that brand_key() would not produce: {bad}"


def test_every_generic_key_is_its_own_normalization():
    bad = [k for k in sorted(ex.GENERIC_KEYS) if brand_key(k) != k]
    assert not bad, f"generic keys the normalizer would never produce: {bad}"


def test_every_rule_has_a_distinct_name_and_a_reason():
    names = [r.name for r in ex.RULES]
    assert len(names) == len(set(names)) == len(ex.CLASS_NAMES)
    assert all(r.reason and not r.reason.endswith(".") for r in ex.RULES)


#: Brands ALREADY ON the watchlist that this rule set would have kept out.
#: Pinned rather than asserted away, because the disagreement is a finding and
#: not a bug: D109 excludes `loci_category in {bank, clinic}` outright, and
#: seven of these nine are boutique wellness brands (LaserAway, Ever/Body,
#: Peachy) that a person deliberately admitted as retail tenants. The two banks
#: are correctly excluded. Nothing is lost today -- an exclusion gates ENTRY to
#: the queue and never removes a row already on the list (see the test below) --
#: but the moment somebody relaxes the clinic rule, or admits another med-spa,
#: this list moves and the diff says so.
ADMITTED_AND_EXCLUDED = {
    "chase", "municipal credit union",                      # genuinely banks
    "laseraway", "ever body", "peachy",                     # med-spa / boutique
    "bespoke physical therapy", "lenox hill radiology",
    "callen lorde community health center",
    "quantum physical therapy and chiropractic care",
}


def test_the_rule_set_disagrees_with_exactly_these_admitted_rows():
    from loci.chains import watchlist as wl

    excluded = {r["brand_key"] for r in wl.brands()
                if ex.exclude_reason({"brand_key": r["brand_key"],
                                      "loci_category": r.get("loci_category"),
                                      "locations_total": 1, "n_boroughs": 1})}
    assert excluded == ADMITTED_AND_EXCLUDED


def test_an_exclusion_gates_entry_and_never_removes_an_admitted_row():
    """The reason the disagreement above is survivable. `admitted` outranks the
    predicate: a brand a person put on the list stays on it whatever the rule
    set thinks, because the rules decide what ENTERS the queue, not what the
    watchlist holds."""
    from loci.chains import candidates as cand

    row = _row("laseraway", loci_category="clinic")
    assert ex.exclude_reason(row) is not None
    # It is not offered as a NEW candidate ...
    assert cand.candidate_reason(row, admitted={"laseraway"}) is None
    # ... and nothing in the rule set can take it off the watchlist: the only
    # writers of `tier` are `admit` / `reject` / `auto-admit`.
    from loci.chains import watchlist as wl

    keep = [r for r in wl.brands() if r["brand_key"] == "laseraway"]
    assert keep and wl.tier_of(keep[0]) == "admitted"
