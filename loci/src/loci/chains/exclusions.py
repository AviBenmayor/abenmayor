"""The D109 exclusion rule set -- classes that never reach the candidate queue.

A named, tested rule set, because the monthly job now AUTO-ADMITS every brand
that clears the candidate predicate (owner ruling, 2026-09-15) and the owner
rejects after the fact. Under a hand-review process a bad exclusion cost a
reviewer ten seconds; under auto-admission it costs a row in the sales list
that a person has to notice and undo. The rules are therefore the load-bearing
half of the predicate, not a tidy-up pass, and every one of them carries the
reason it exists in one line of prose that is printed beside the row.

TWO KINDS OF RULE, and they are different in kind:

  * **Class exclusions** (D109's table): banks, health-system practice lines,
    agent networks, wireless carriers, parking, ATMs, government/postal, fuel.
    These say "this is a real multi-location operator and it is not a retail
    tenant a broker can sell to". MoneyGram is the canonical case -- the
    fastest-"growing" name in the first raw detect run, and every one of those
    locations is a counter inside somebody else's bodega.

  * **Data-quality guards** (added 2026-09-15 on the candidates preview).
    These say "this row is not a brand at all". `GENERIC_KEYS` catches the
    normalizer collapsing dozens of unrelated storefronts onto a common noun
    ("Cafe", 60 locations, 4 boroughs); the `n_boroughs = 0` guard catches a
    geocoding defect being read as a footprint. Both cleared the D109
    predicate on the numbers in the 2026-09 preview. A predicate that only
    reads counts cannot tell either of them from a chain.

MATCHING IS ON THE NORMALIZED KEY, never on the raw display name: the key is
what detect grouped on, so the pattern and the row agree by construction. Each
pattern is written already-normalized and
`tests/test_chains_exclusions.py::test_every_pattern_is_its_own_normalization`
asserts it -- a hand-typed pattern the normalizer would never produce matches
nothing and silently disables its own class.

Two match modes, deliberately separate:

  `exact`     the whole key must equal the pattern. Used for SHORT, AMBIGUOUS
              brand tokens: `bp`, `gulf`, `shell`, `sp`. "Gulf Coast Seafood"
              and "Shell Cafe" are restaurants, and a substring rule on those
              tokens would delete them from the list with a gas-station reason.
  `contains`  the pattern must appear as a whole-token run inside the key.
              Used where the brand token is unambiguous and the practice-line
              suffix varies without limit -- "northwell health physician
              partners", "northwell go", "northwell urgent care" are one
              excluded thing and no exact list ever finishes.

ORDER MATTERS only for the REASON that gets reported (the first matching rule
wins) and therefore for the per-class counts `loci chains candidates` prints.
Category first because it is the cheapest and most certain signal; the
data-quality guards last, so a MoneyGram row with a broken borough count is
reported as an agent network rather than as a geocoding defect.
"""
from __future__ import annotations

import pathlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from loci.categories import CATEGORIES

#: The stoplist of generic keys. Package data, next to the code that reads it.
GENERIC_KEYS_PATH = pathlib.Path(__file__).resolve().parent / "generic_keys.txt"

#: `loci_category` values that are never a retail tenant a site-selection
#: product is sold to. Both are in the fifteen daily-needs categories and both
#: are real supply -- a bank branch counts on the address screen. They are
#: excluded from the SALES list, not from the city.
EXCLUDED_CATEGORIES = frozenset({"bank", "clinic"})

#: A category slug that is not one of the fifteen would match nothing and
#: silently disable the cheapest rule in the set, so it is checked at import.
assert EXCLUDED_CATEGORIES <= set(CATEGORIES), sorted(EXCLUDED_CATEGORIES - set(CATEGORIES))


def load_generic_keys(path: pathlib.Path | None = None) -> frozenset[str]:
    """Read generic_keys.txt. One key per line, `#` comments, blanks ignored."""
    text = (path or GENERIC_KEYS_PATH).read_text()
    keys = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            keys.add(" ".join(line.lower().split()))
    return frozenset(keys)


GENERIC_KEYS: frozenset[str] = load_generic_keys()

#: The single-token entries double as the "plain English category word" rule:
#: a one-token key whose singular form is listed is generic even when the
#: exact plural is not written out.
GENERIC_SINGLE_TOKENS: frozenset[str] = frozenset(
    k for k in GENERIC_KEYS if " " not in k)


@dataclass(frozen=True)
class Rule:
    """One exclusion class: a name for the counts, a reason for the reader."""
    name: str
    reason: str
    exact: frozenset[str] = frozenset()
    contains: tuple[str, ...] = ()
    #: An arbitrary row predicate, for the rules that read numbers rather than
    #: names (the geocoding guard). Takes the row, returns bool.
    predicate: Callable[[Mapping], bool] | None = field(default=None, repr=False)

    def matches(self, row: Mapping) -> bool:
        if self.predicate is not None and self.predicate(row):
            return True
        key = _key_of(row)
        if not key:
            return False
        if key in self.exact:
            return True
        padded = f" {key} "
        return any(f" {p} " in padded for p in self.contains)

    def patterns(self) -> tuple[str, ...]:
        return tuple(sorted(self.exact)) + tuple(self.contains)


def _key_of(row: Mapping) -> str:
    key = row.get("brand_key") or ""
    return " ".join(str(key).lower().split())


def _is_generic(row: Mapping) -> bool:
    key = _key_of(row)
    if not key:
        return False
    if key in GENERIC_KEYS:
        return True
    tokens = key.split()
    if len(tokens) != 1:
        return False
    # A single-token key that is a plain English category word, including its
    # regular plural: "cafes" is no more a brand than "cafe" is. The plural
    # arms fire ONLY on a key that actually ends in "s", or "SPAR" (a real
    # grocery brand) would be stripped to "spa" and excluded as a nail salon.
    token = tokens[0]
    candidates = [token]
    if token.endswith("s"):
        candidates += [token[:-1], token[:-2]]
    return any(len(c) >= 3 and c in GENERIC_SINGLE_TOKENS for c in candidates)


def _is_geocode_defect(row: Mapping) -> bool:
    """`n_boroughs = 0` while the brand has locations.

    Every location in `chains.brand_location` gets its borough from an H3
    res-9 join to `analysis.hex`, which is shoreline-clipped -- so ONE
    location outside the grid (a pier, an airport terminal) legitimately has a
    NULL borough. A brand where NONE of thirteen locations resolved to a
    borough is not a brand that opened thirteen stores offshore; it is an
    address-resolution gap upstream, and the 2026-09 preview surfaced two of
    them (Chestnut Market at 13 locations, Universal Food Markets at 7) sitting
    among genuine fast movers. Read the count as unmeasured, never as growth.
    """
    total = row.get("locations_total")
    boroughs = row.get("n_boroughs")
    if total is None or boroughs is None:
        return False
    try:
        return int(boroughs) == 0 and int(total) > 0
    except (TypeError, ValueError):
        return False


def _is_excluded_category(row: Mapping) -> bool:
    return (row.get("loci_category") or "") in EXCLUDED_CATEGORIES


#: The rule set, in evaluation order. Every entry is a class D109 named, plus
#: the two data-quality guards the 2026-09 preview proved necessary.
RULES: tuple[Rule, ...] = (
    Rule(
        name="bank_clinic_category",
        reason="bank or clinic category — not a retail tenant a broker leases to",
        predicate=_is_excluded_category,
    ),
    Rule(
        name="health_systems",
        reason="health-system practice line — site-specific names collapsing to "
               "one key; a clinic network, not a storefront brand",
        contains=("northwell", "mount sinai", "mt sinai", "nyu langone",
                  "montefiore", "citymd", "one medical", "nyc health hospitals",
                  "nyc health and hospitals", "weill cornell",
                  "hospital for special surgery", "memorial sloan kettering"),
    ),
    Rule(
        name="agent_networks",
        reason="money-transfer agent network — a counter inside somebody else's "
               "bodega, and the fastest-'growing' name in the first raw detect run",
        contains=("moneygram", "western union", "ria money transfer"),
    ),
    Rule(
        name="wireless_carriers",
        reason="wireless carrier — a kiosk format, not a site-selection lead",
        exact=frozenset({"att", "at and t", "metropcs", "metro pcs"}),
        contains=("verizon", "t mobile", "tmobile", "metro by t mobile",
                  "boost mobile", "cricket wireless", "spectrum mobile"),
    ),
    Rule(
        name="parking",
        reason="parking operator — not a commercial tenant",
        exact=frozenset({"sp", "sp plus"}),
        contains=("icon parking", "quik park", "edison parkfast", "laz parking",
                  "sp plus parking", "parking garage", "municipal parking"),
    ),
    Rule(
        name="atms",
        reason="ATM estate — a machine in someone else's store, not a storefront",
        contains=("atm", "atms", "cardtronics", "allpoint", "moneypass",
                  "money pass"),
    ),
    Rule(
        name="gov_postal",
        reason="government or postal — not a commercial tenant",
        exact=frozenset({"usps", "nypl", "dmv", "post office"}),
        contains=("usps", "united states postal", "us postal service",
                  "post office", "nyc dept", "nyc department",
                  "department of motor vehicles", "new york public library",
                  "nypd", "fdny", "board of elections"),
    ),
    Rule(
        name="fuel",
        # EXACT ONLY for the short brand tokens. "Shell", "BP" and "Gulf" are
        # also ordinary English words that head real restaurant names, and a
        # substring rule would silently delete them under a gas-station reason
        # -- the exact failure this rule set exists to avoid making cheap.
        reason="fuel-branded convenience — the storefront is a gas station, "
               "not the brand",
        exact=frozenset({"shell", "bp", "mobil", "exxon", "exxonmobil", "gulf",
                         "citgo", "sunoco", "speedway", "valero"}),
        contains=("shell gas", "bp gas", "exxon mobil", "sunoco", "citgo",
                  "speedway", "gas station", "service station"),
    ),
    Rule(
        name="generic_key",
        reason="generic noun, not a brand — the normalizer collapsed unrelated "
               "storefronts onto one key (see chains/generic_keys.txt)",
        predicate=_is_generic,
    ),
    Rule(
        name="geocode_defect",
        reason="n_boroughs = 0 with locations in the snapshot — an "
               "address-resolution gap upstream, not a footprint",
        predicate=_is_geocode_defect,
    ),
)

RULES_BY_NAME: dict[str, Rule] = {r.name: r for r in RULES}

#: For the per-class count table, so a class that matched nothing this month
#: still prints a zero rather than vanishing.
CLASS_NAMES: tuple[str, ...] = tuple(r.name for r in RULES)


def exclude_rule(row: Mapping) -> Rule | None:
    """The FIRST rule that fires, or None. Order is documented in the module
    docstring: the reported class is the most certain one, not the last one."""
    for rule in RULES:
        if rule.matches(row):
            return rule
    return None


def exclude_reason(row: Mapping) -> str | None:
    """One line of prose saying why this brand never reaches the queue, or
    None if it is not excluded."""
    rule = exclude_rule(row)
    return rule.reason if rule else None


def all_patterns() -> tuple[str, ...]:
    """Every literal pattern in the rule set, for the normalization drift test."""
    out: list[str] = []
    for rule in RULES:
        out.extend(rule.patterns())
    return tuple(out)
