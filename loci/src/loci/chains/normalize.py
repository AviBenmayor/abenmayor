"""Business name -> brand key. The load-bearing function of `loci chains`.

Everything downstream groups on `brand_key`. A normalizer that is too timid
splits one chain into ten brands and the growth signal vanishes; one that is
too aggressive merges unrelated businesses and manufactures a chain that does
not exist. Both failures are silent in the output table, which is why this
module is pure, city-agnostic, and unit-tested against real NYC names rather
than invented ones.

THE PIPELINE, in order (order matters -- each step assumes the previous ran):

  1. unicode NFKD + accent strip          "Cafe Grumpy"  <- "Café Grumpy"
  2. lowercase
  3. reject junk                          emails, all-digits, "n/a", 1 char
  4. drop a leading "dba " / "d/b/a "     the filing prefix, not the brand
  5. cut at a SPACED separator            " - ", " – ", " — ", " @ ", " | "
     and drop parentheticals              "Apollo Bagels - Williamsburg"
  6. "&" -> " and "
  7. drop apostrophes WITHOUT a space     "Dunkin'" -> "dunkin", "Joe's" -> "joes"
  8. every other punctuation -> space     "7-Eleven" -> "7 eleven", "CVS/pharmacy"
  9. strip store numbers                  "#9911", "no. 12", trailing 3+ digits
 10. strip trailing legal suffixes        llc inc corp co ltd lp llp pllc pc na
 11. strip trailing geography tokens      nyc, ny, new york, the five boroughs
 12. drop a leading "the "
 13. collapse whitespace
 14. apply ALIASES                        "dunkin donuts" -> "dunkin"

WHERE IT IS KNOWINGLY WRONG -- also documented in docs/chains-process.md, because
the database cannot catch them:

  * **Store numbers vs. real numbers.** Step 9 strips a trailing numeric token
    only when it carries a `#`/`no.` marker or has THREE OR MORE digits.
    "Chipotle 1234" loses its number; "Cafe 88" and "Bar 66" keep theirs. A
    brand whose own name ends in three digits (rare) would be mangled.
  * **The dash rule is unconditional.** "Dunkin - Baskin Robbins" becomes
    "dunkin". Co-branded locations collapse into the first brand. Splitting
    only on a KNOWN neighbourhood vocabulary was considered and rejected: NYC
    micro-neighbourhood names are open-ended and a miss there splits a chain,
    which is the worse error. NOTE the separator must be SPACED -- "7-Eleven"
    and "Chick-fil-A" survive intact.
  * **Franchisee filings.** DCWP/DOHMH names are often the operating company
    ("PRIYA FOODS INC" running a Dunkin'), which this cannot recover. Those
    locations are invisible to the brand, so `locations_total` is a FLOOR.
  * **`co` is stripped as a legal suffix.** "Joe Coffee Co" -> "joe coffee",
    which is right; a brand genuinely named "... Co" as its distinguishing
    word would be merged with its non-Co spelling, which is also usually right.

ALIASES is the escape hatch for collapses that no rule produces -- a brand that
files under two genuinely different strings. Keep it SHORT and cited; it is
manual judgement, not normalization, and every entry is a claim someone must be
able to check.
"""
from __future__ import annotations

import re
import unicodedata

#: Legal-entity words stripped from the END of a name, repeatedly. Only the
#: end: "Corp Bagels" is a brand, "Bagels Corp" is a filing.
LEGAL_SUFFIXES = frozenset({
    "llc", "lc", "inc", "incorporated", "corp", "corporation", "co", "company",
    "ltd", "limited", "lp", "llp", "plc", "pllc", "pc", "na", "nfp",
    "enterprises", "enterprise", "holdings", "holding",
})

#: Geography words stripped from the END of a name. Deliberately short: only
#: tokens that are unambiguously a location tag when they come LAST. A leading
#: "Brooklyn Bagel" keeps its Brooklyn.
GEO_SUFFIXES = frozenset({
    "nyc", "ny", "usa", "brooklyn", "manhattan", "queens", "bronx",
})

#: Multi-word geography tails, checked before the single-token pass.
GEO_PHRASE_SUFFIXES = (
    ("new", "york", "city"),
    ("new", "york"),
    ("staten", "island"),
)

#: Names that are not names. Returning None here is what keeps DCWP's
#: "PARADISELAUNDROMATNY@GMAIL.COM" out of the brand table.
#:
#: "nan" and "not applicable" were added 2026-09-13 on evidence from
#: staging.storefront_filing: 2,997 filings carried the literal string "nan"
#: as a brand key and 6,573 carried "not applicable", which between them were
#: the second and third largest "brands" in New York. The first came from a
#: pandas NaN reaching this function (see the guard in `brand_key`), the
#: second from DOB filers typing it into the owner-name field.
_JUNK_EXACT = frozenset({"na", "n a", "nan", "none", "null", "unknown",
                         "no name", "not applicable", "tbd"})

#: Manual brand collapses. One line of evidence per entry, in the comment.
ALIASES: dict[str, str] = {
    "dunkin donuts": "dunkin",          # rebranded 2019; both spellings still file
    "dunkin donuts baskin robbins": "dunkin",
    "mcdonalds restaurant": "mcdonalds",
    "starbucks coffee": "starbucks",
    "cvs pharmacy": "cvs",
    "duane reade by walgreens": "duane reade",
    "subway sandwiches": "subway",
    "7 11": "7 eleven",
    # apostrophe-with-space filings ("All' Antico Vinaio") normalize to "all
    # antico vinaio" while the tight spelling ("All'Antico Vinaio") normalizes
    # to "allantico vinaio" -- same chain, split by a space DOHMH/DCWP filers
    # add after the apostrophe. Detected 2026-09-13 as two brand_keys (14 vs 4
    # locations, the smaller one auto-flagged "2 new of only 4"). Canonical key
    # is the tight spelling because it is the larger, first-seen key.
    "all antico vinaio": "allantico vinaio",
    # The full trade name ("Raising Cane's Chicken Fingers") and the short one
    # ("Raising Cane's") file under both; the watchlist row keys on the short
    # form, so the 2026-09-13 snapshot showed the curated brand at 14 detected
    # while 17 more sat under the long key, unlisted. Same chain.
    "raising canes chicken fingers": "raising canes",
    # Short-vs-full trade-name splits surfaced by the 2026-09-15 candidates
    # preview (each pair filed under both spellings; the watchlist row keys on
    # the spelling the company uses on its own locator, so that one is
    # canonical). Blank Street, Chip City, Dos Toros keep the full name;
    # Guacado and Teriyaki One keep the short one.
    "blank street": "blank street coffee",
    "chip city": "chip city cookies",
    "dos toros": "dos toros taqueria",
    "guacado mexican grill": "guacado",
    "teriyaki one japanese grill": "teriyaki one",
    # "Moka & Co" (Yemeni coffee, 10 NYC units) collapses to the bare key
    # "moka and": the &->and rule fires and then "Co" is stripped as a legal
    # suffix. Pin the full name so the key is a brand, not a conjunction.
    "moka and": "moka and co",
    # --- key-splits from the 2026-09-15 auto-admit dry run ------------------
    # Each pair below is one chain filed under two spellings and detected as
    # two brands. Canonical is the spelling the company's own locator/website
    # uses (checked one-by-one, cited in each comment), except where the
    # watchlist already keys on one spelling -- then that one wins so the
    # curated row and the detected row agree.
    #
    # Co-branded / practice-line collapses (same pattern as "dunkin donuts
    # baskin robbins" above: a second brand named on the sign does not make it
    # a different chain).
    "dunkin baskin robbins": "dunkin",             # 109 loc; co-branded Dunkin' store
    "auntie annes pretzels": "auntie annes",       # 10 loc vs 93; "Pretzels" is a descriptor
    "auntie annes cinnabon carvel": "auntie annes",  # 5 loc; triple co-branded kiosk
    # Trade-name splits where the shorter form is the registered trade name
    # (Wikipedia infobox "Trade name:", checked 2026-09-15) even though the
    # longer form has more raw filings.
    "popeyes louisiana kitchen": "popeyes",         # 261 loc vs 235; trade name is "Popeyes"
    "dominos pizza": "dominos",                     # 193 loc vs 182; rebranded to "Domino's" 2012
    "little caesars pizza": "little caesars",       # 70 loc vs 40; trade name is "Little Caesars"
    "chopt creative salad": "chopt",                # 14 loc vs 49; "commonly referred to as Chopt"
    # Trade-name splits where the LONGER form is the registered trade name.
    "jersey mikes": "jersey mikes subs",            # 20 loc vs 57; trade name is "Jersey Mike's Subs"
    "golden krust": "golden krust caribbean restaurant",  # 20 loc vs 59; goldenkrust.com header
    "sonic": "sonic drive in",                      # 7 loc vs 16; trade name is "Sonic Drive-In"
    "panera": "panera bread",                       # 3 loc vs 104; panerabread.com header default
    # A sub-format's name folds into the parent brand, not the reverse --
    # same call as "dunkin baskin robbins": a format variant is not a new chain.
    "pizza hut express": "pizza hut",               # 52 loc vs 95; express is a kiosk format
    "buffalo wild wings go": "buffalo wild wings",  # 22 loc vs 43; Go is a to-go-only format
    "guac time mexican grill": "guac time",         # 11 loc vs 20; descriptor, not the sign name
    # Quasi-independent NYC storefronts sharing a name are still one detected
    # "chain" for this table's purpose -- the count is a NAME, not a common
    # operator. See docs/chains-process.md if that distinction needs revisiting.
    "kennedy chicken": "kennedy fried chicken",             # 21 loc
    "kennedy chicken and burger": "kennedy fried chicken",  # 4 loc
    "kennedy chicken and pizza": "kennedy fried chicken",   # 9 loc
    # Splits against a spelling already curated on the watchlist -- alias the
    # non-watchlist spelling so the detected row and the curated row agree.
    "bonchon chicken": "bonchon",
    "crumbl": "crumbl cookies",
    "lidl": "lidl us",
    "pura vida": "pura vida miami",
    "tobys estate": "tobys estate coffee",
    "walgreens": "walgreens duane reade",
    "cvs photo": "cvs",
    # NOT aliased, on purpose:
    #   "eataly" / "eataly caffe" -- different concepts (marketplace vs. cafe
    #     format), not a filing split.
    #   "teppanyaki one" / "teriyaki one" -- same operator, different trade
    #     name for a different concept; leave apart.
    #   "whole foods market daily shop" -- a real distinct smaller format;
    #     leave apart from "whole foods market".
    # "home", "hudson", "little italy", and "club" are too ambiguous to alias
    # at all (a generic word, an ambiguous brand token, a neighborhood name, a
    # generic word) -- stoplisted in generic_keys.txt instead of aliased.
    # --- supermarket co-op banner spelling splits (owner ruling, 2026-09-15) --
    # A "co-op banner" is a buying group (Krasdale/Western Beef/Associated
    # Grocers style) that licenses its name to independently owned
    # supermarkets: the count is a BANNER over many separate owners, not one
    # operator's footprint, which is why `candidates.COOP_BANNERS` forces
    # `sales_role: incumbent` on these regardless of location count rather
    # than excluding them outright (they are real supply). Each alias below
    # collapses that banner's filing-spelling variants to its single largest
    # spelling in the 2026-09 snapshot, so the banner is one row.
    "key food supermarkets": "key food",              # 22 loc vs 122
    "key food supermarket": "key food",               # 5 loc vs 122
    "key food stores co op": "key food",              # 14 loc vs 122
    "associated": "associated supermarket",           # 9 loc vs 51
    "associated fresh": "associated supermarket",     # 9 loc vs 51
    "fine fare": "fine fare supermarkets",            # 36 loc vs 40
    "fine fare supermarket": "fine fare supermarkets",  # 24 loc vs 40
    "pioneer": "pioneer supermarket",                 # 5 loc vs 18
    "pioneer supermarkets": "pioneer supermarket",    # 14 loc vs 18
    "bravo supermarket": "bravo supermarkets",        # 12 loc vs 48
    "c town supermarket": "c town",                   # 13 loc vs 33
    "met fresh": "met fresh supermarket",             # 3 loc vs 7
    "food universe": "food universe marketplace",     # 16 loc vs 45
    # "met food" (10 loc) is left apart from "met fresh"/"met fresh
    # supermarket" -- the owner ruling named only the "met fresh*" spellings
    # as one banner; "Met Food" is a distinct, if related, banner name.
}

_SEPARATOR = re.compile(r"\s+[-–—|@]\s+|\s+\bat\b\s+(?=\w)")
_PARENTHETICAL = re.compile(r"\s*[(\[{][^)\]}]*[)\]}]")
_STORE_NO = re.compile(r"(?:#|\bno\.?\s*|\bnum(?:ber)?\.?\s*|\bstore\s*#?\s*|\bunit\s*#?\s*)\d+")
_APOSTROPHE = re.compile(r"['‘’ʼ´`]")
#: "N.A." / "L.L.C." / "P.C." -- dotted initialisms, collapsed BEFORE the
#: punctuation pass, or they tokenize to "n a" and no suffix rule can see them.
_DOTTED_INITIALISM = re.compile(r"\b(?:[a-z]\.){2,}")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_EMAILISH = re.compile(r"[\w.+-]+@[\w-]+\.\w+|\bwww\.|\.com\b|\.net\b|\.org\b")


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))


def _is_store_number(token: str) -> bool:
    """A trailing numeric token is a STORE NUMBER only at 3+ digits.

    Two digits is as often part of the brand ("Cafe 88", "Bar 66", "Studio 54")
    as it is a store id, and merging two unrelated two-digit bars is worse than
    leaving one chain split by its store numbers -- the split shows up as a
    small count, the merge shows up as a fake chain."""
    return token.isdigit() and len(token) >= 3


def brand_key(name: str | None) -> str | None:
    """Normalize one business name to its brand key, or None if it is junk.

    Pure and deterministic. See the module docstring for the pipeline and for
    the cases where it is knowingly wrong."""
    if not name:
        return None
    # A pandas NaN is a FLOAT, and a float NaN is TRUTHY, so `not name` does
    # not catch it and `str(nan)` is the string "nan". Measured 2026-09-13:
    # 2,997 rows of staging.storefront_filing carry `business_name_key = 'nan'`
    # because of exactly this -- the third-largest "brand" in the city. Caught
    # here rather than at every call site, because every call site is a frame
    # column and they will not all remember.
    if isinstance(name, float) and name != name:
        return None
    text = _strip_accents(str(name)).lower().strip()
    if not text or _EMAILISH.search(text):
        return None

    # 4 — the filing prefix
    text = re.sub(r"^d\s*/?\s*b\s*/?\s*a[\s.:-]+", "", text)

    # 5 — location tails
    text = _PARENTHETICAL.sub(" ", text)
    text = _SEPARATOR.split(text, maxsplit=1)[0]

    # 6-8 — punctuation
    text = text.replace("&", " and ")
    text = _DOTTED_INITIALISM.sub(lambda m: m.group(0).replace(".", ""), text)
    text = _STORE_NO.sub(" ", text)          # before apostrophes eat the "no."
    text = _APOSTROPHE.sub("", text)
    text = _NON_ALNUM.sub(" ", text)

    tokens = text.split()

    # 9-11 — trailing noise, repeatedly: "Vital Climbing Gym LLC NYC" needs two passes
    changed = True
    while changed and tokens:
        changed = False
        for phrase in GEO_PHRASE_SUFFIXES:
            n = len(phrase)
            if len(tokens) > n and tuple(tokens[-n:]) == phrase:
                tokens = tokens[:-n]
                changed = True
                break
        if changed:
            continue
        last = tokens[-1]
        if len(tokens) > 1 and (last in LEGAL_SUFFIXES or last in GEO_SUFFIXES
                                or _is_store_number(last)):
            tokens = tokens[:-1]
            changed = True

    # 12 — a leading article carries no identity
    if len(tokens) > 1 and tokens[0] == "the":
        tokens = tokens[1:]

    key = " ".join(tokens).strip()
    if not key or key in _JUNK_EXACT or len(key) < 2:
        return None
    if key.isdigit():
        return None
    return ALIASES.get(key, key)


def display_name(names: list[str | None]) -> str | None:
    """The label to show for a brand key: the most common raw spelling, title-cased.

    Ties break on the longest string, so "Apollo Bagels" wins over "Apollo" when
    both occur twice -- the longer spelling is the more identifiable one."""
    counts: dict[str, int] = {}
    for n in names:
        if not n:
            continue
        clean = " ".join(str(n).split())
        if clean:
            counts[clean] = counts.get(clean, 0) + 1
    if not counts:
        return None
    best = max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))[0]
    return best if any(c.islower() for c in best) else best.title()
