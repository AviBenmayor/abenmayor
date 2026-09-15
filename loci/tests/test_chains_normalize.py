"""brand_key() against real NYC business names.

Every string here was taken from, or is the exact shape of, a name that appears
in staging.poi (DOHMH `dba`, DCWP `business_name`, Overture/FSQ `name`). The
point of the table is that the two failure modes are OPPOSITE: over-merging
invents a chain, under-merging hides one. Both directions are asserted.
"""
from __future__ import annotations

import pytest

from loci.chains.normalize import brand_key, display_name

# (raw name, expected brand key) -- the tricky dozen, plus the junk cases.
CASES = [
    # --- the same brand, five filings ------------------------------------
    ("APOLLO BAGELS",                       "apollo bagels"),
    ("Apollo Bagels - Williamsburg",        "apollo bagels"),
    ("Apollo Bagels (Nolita)",              "apollo bagels"),
    ("apollo bagels llc",                   "apollo bagels"),
    ("Apollo Bagels NYC",                   "apollo bagels"),
    # --- legal suffixes ---------------------------------------------------
    ("VITAL CLIMBING GYM LLC",              "vital climbing gym"),
    ("Vital Climbing Gym",                  "vital climbing gym"),
    ("Lyfe Kitchen Corp.",                  "lyfe kitchen"),
    ("BANK OF AMERICA, N.A.",               "bank of america"),
    ("Joe Coffee Company",                  "joe coffee"),
    # --- store numbers ----------------------------------------------------
    ("STARBUCKS #9911",                     "starbucks"),
    ("Starbucks Coffee",                    "starbucks"),          # ALIAS
    ("Trader Joe's #542",                   "trader joes"),
    ("DUNKIN DONUTS #336012",               "dunkin"),             # ALIAS
    ("Dunkin'",                             "dunkin"),
    ("Chipotle Mexican Grill 2841",         "chipotle mexican grill"),
    # --- punctuation that must NOT split ----------------------------------
    ("7-Eleven",                            "7 eleven"),
    ("7 Eleven",                            "7 eleven"),
    ("Chick-fil-A",                         "chick fil a"),
    ("CVS/pharmacy #1234",                  "cvs"),                # ALIAS
    # --- accents, ampersands, articles ------------------------------------
    ("Café Grumpy",                         "cafe grumpy"),
    ("Joe & The Juice",                     "joe and the juice"),
    ("The Halal Guys",                      "halal guys"),
    ("McDonald's (Times Square)",           "mcdonalds"),
    ("D/B/A Sweetgreen",                    "sweetgreen"),
    ("Sweetgreen  —  Union Square",         "sweetgreen"),
]

JUNK = [
    "PARADISELAUNDROMATNY@GMAIL.COM",   # a real DCWP `business_name`
    "www.bagels.com",
    "N/A",
    "   ",
    None,
    "",
    "7",
    "1234",
]

#: Pairs that must stay APART. Over-merging is the failure that invents a chain.
DISTINCT = [
    ("Cafe 88", "Cafe 66"),                  # two digits is part of the name
    ("Brooklyn Bagel", "Bagel Brooklyn"),    # geography strips only from the end
    ("Joe's Pizza", "Joe Coffee"),
    ("Vital Climbing Gym", "Vital Kitchen"),
    ("Corp Bagels", "Bagels Corp"),          # legal words strip only from the end
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_brand_key(raw, expected):
    assert brand_key(raw) == expected


@pytest.mark.parametrize("raw", JUNK)
def test_junk_names_have_no_brand(raw):
    assert brand_key(raw) is None


@pytest.mark.parametrize("a,b", DISTINCT)
def test_distinct_brands_do_not_merge(a, b):
    ka, kb = brand_key(a), brand_key(b)
    assert ka is not None and kb is not None
    assert ka != kb, f"{a!r} and {b!r} both normalized to {ka!r}"


def test_normalization_is_idempotent():
    """A key fed back in must come out unchanged, or grouping is unstable
    across runs that mix raw names with already-normalized ones."""
    for raw, _ in CASES:
        key = brand_key(raw)
        assert brand_key(key) == key, f"{raw!r} -> {key!r} is not a fixed point"


def test_repeated_trailing_noise_is_fully_stripped():
    assert brand_key("Vital Climbing Gym LLC NYC") == "vital climbing gym"
    assert brand_key("Apollo Bagels Inc. New York City") == "apollo bagels"


def test_all_antico_vinaio_apostrophe_spellings_share_a_brand_key():
    """The tight spelling ("All'Antico Vinaio") and the apostrophe-with-space
    filing ("All' Antico Vinaio") normalized to two different keys before the
    ALIASES entry was added (detected 2026-09-13 as 14 vs. 4 locations, the
    smaller one auto-flagged). All three real-world spellings must collapse to
    one brand_key or the chain is invisible as a single growth signal."""
    keys = {brand_key(n) for n in
            ("All'Antico Vinaio", "All' Antico Vinaio", "Allantico Vinaio")}
    assert keys == {"allantico vinaio"}


def test_display_name_prefers_the_common_spelling():
    assert display_name(["APOLLO BAGELS", "APOLLO BAGELS", "Apollo Bagels - Wburg"]) \
        == "Apollo Bagels"
    assert display_name([None, "", "  "]) is None
    # a mixed-case spelling is left alone rather than re-title-cased
    assert display_name(["sweetgreen", "sweetgreen"]) == "sweetgreen"


def test_raising_canes_long_and_short_trade_names_share_a_brand_key():
    """"Raising Cane's Chicken Fingers" and "Raising Cane's" filed as two
    keys (17 vs. 14 locations on the 2026-09-13 snapshot) while the watchlist
    row keyed only on the short form. Both must collapse to the short key."""
    keys = {brand_key(n) for n in
            ("Raising Cane's Chicken Fingers", "Raising Cane's", "Raising Canes")}
    assert keys == {"raising canes"}


def test_short_and_full_trade_names_collapse_to_the_locator_spelling():
    """Five splits from the 2026-09-15 candidates preview: each brand filed
    under both its short and its full trade name and detected as two chains.
    The canonical key is the spelling the company's own locator uses."""
    assert brand_key("Blank Street") == brand_key("Blank Street Coffee") == "blank street coffee"
    assert brand_key("Chip City") == brand_key("Chip City Cookies") == "chip city cookies"
    assert brand_key("Dos Toros") == brand_key("Dos Toros Taqueria") == "dos toros taqueria"
    assert brand_key("Guacado Mexican Grill") == brand_key("Guacado") == "guacado"
    assert brand_key("Teriyaki One Japanese Grill") == brand_key("Teriyaki One") == "teriyaki one"


def test_moka_and_co_keeps_its_name_after_the_ampersand_and_suffix_rules():
    """"Moka & Co" would otherwise normalize to the conjunction "moka and"
    (&->and, then "Co" stripped as a legal suffix)."""
    assert brand_key("Moka & Co") == "moka and co"
    assert brand_key("Moka and Co") == "moka and co"
