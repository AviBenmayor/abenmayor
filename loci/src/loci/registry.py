"""The data source registry: load it, and guard it against drift.

`registry.yaml` is the machine-readable mirror of docs/CONTEXT.md section 3.
`validate()` asserts the two agree, so the human doc and the machine registry
cannot silently diverge. Exposed as `loci check-sources`.

Status `wishlist` is the one exception to both rules. A wishlist entry is a PAID
source Loci would buy post-raise — it is not ingested, not budgeted, and not a
row in CONTEXT.md section 3 (41 vendor rows would drown the 40 sources actually
in the pipeline). It mirrors docs/PAID-SOURCES.md instead, which `loci
gen-paid-sources` renders from these entries; the drift check below asserts the
doc is a byte-identical render, so the doc can never be hand-edited into a lie
about what we would buy or what it costs.
"""
from __future__ import annotations

import pathlib

import yaml

PKG = pathlib.Path(__file__).resolve().parent
ROOT = PKG.parents[1]
REGISTRY_PATH = PKG / "registry.yaml"
REQUIRED = {"id", "name", "tier", "role", "status", "url", "cost", "bias"}
VALID_TIERS = {"universal", "city"}
VALID_ROLES = {"poi", "panel", "outcome", "control", "validation", "excluded"}
VALID_STATUS = {"planned", "verified", "deferred", "excluded", "wishlist"}

# A wishlist entry must carry the whole purchasing case, not just a name and a
# URL: what it costs, what the licence forbids, which named gap it closes, and
# the dated evidence behind the price. Anything less is a wish, not a line item.
WISHLIST_REQUIRED = {
    "category", "vendor", "price_tier", "price_note", "license_note",
    "closes_gap", "priority", "priority_reason", "integration_effort",
    "confidence", "evidence", "cost_basis",
}
VALID_PRIORITY = {"P1", "P2", "P3"}
VALID_EFFORT = {"low", "med", "high"}
VALID_CONFIDENCE = {"low", "med", "high"}
VALID_COST_BASIS = {"verified", "reported", "quote_only"}
GAP_LETTERS = set("abcdefghi")

# The floor of each published price band, in annual USD. A wishlist `cost` is
# never 0 -- "free" is not a purchase, and a $0 line item silently disappears
# from every total. Where the vendor publishes no number at all (`quote_only`)
# the entry books the band floor, so the wishlist total is honestly a LOWER
# BOUND rather than a guess dressed as a forecast. `under_1k_yr` books $100
# because the band's true floor is 0; `quote_only` books $10k because no vendor
# in the 2026-09-13 survey quoted a four-figure enterprise deal.
PRICE_TIER_FLOOR = {
    "under_1k_yr": 100,
    "1k_10k_yr": 1_000,
    "10k_50k_yr": 10_000,
    "quote_only": 10_000,
    "hardware": 1_000,
}


def load() -> dict:
    """Parse registry.yaml."""
    return yaml.safe_load(REGISTRY_PATH.read_text())


def validate(check_urls: bool = False) -> list[str]:
    """Return a list of problems. Empty list means the registry is sound."""
    reg = load()
    context = (ROOT / "docs" / "CONTEXT.md").read_text()
    sources = reg["sources"]
    errors: list[str] = []

    ids = [s["id"] for s in sources]
    if len(ids) != len(set(ids)):
        errors.append("duplicate source ids")
    wishlist = [s for s in sources if s.get("status") == "wishlist"]

    for s in sources:
        missing = REQUIRED - s.keys()
        if missing:
            errors.append(f"{s.get('id', '?')}: missing {sorted(missing)}")
        if s.get("tier") not in VALID_TIERS:
            errors.append(f"{s['id']}: bad tier {s.get('tier')!r}")
        if s.get("role") not in VALID_ROLES:
            errors.append(f"{s['id']}: bad role {s.get('role')!r}")
        if s.get("status") not in VALID_STATUS:
            errors.append(f"{s['id']}: bad status {s.get('status')!r}")
        if s.get("tier") == "city" and "city" not in s:
            errors.append(f"{s['id']}: tier=city requires a `city` key")
        # Drift check: every dataset_id in the registry must appear in CONTEXT.md.
        # Wishlist entries are exempt -- they mirror docs/PAID-SOURCES.md instead.
        did = s.get("dataset_id")
        if did and s.get("status") != "wishlist" and did not in context:
            errors.append(f"{s['id']}: dataset_id {did} absent from docs/CONTEXT.md section 3")
        if s.get("status") == "wishlist":
            errors += _validate_wishlist_entry(s)

    # Budget consistency: paid sources must not exceed the stated ceiling.
    # Wishlist costs are deliberately EXCLUDED: they are post-raise purchases,
    # not spend against the $100 free-data budget, and folding them in would
    # blow the ceiling by three orders of magnitude and make the check useless
    # for the thing it exists to catch -- an accidental paid dependency today.
    budgeted = sum(s["cost"].get("budgeted_total", 0) for s in sources
                   if "cost" in s and s.get("status") != "wishlist")
    if budgeted > reg["budget"]["projected_max"]:
        errors.append(f"budgeted spend {budgeted} exceeds projected_max {reg['budget']['projected_max']}")

    errors += _validate_paid_sources_doc(wishlist)

    if check_urls:
        import urllib.error
        import urllib.request
        # Wishlist URLs are vendor marketing sites behind bot protection; they
        # are evidence of a price, not an ingest endpoint, and sweeping them
        # adds 35 flaky requests to every `make check`.
        for s in (s for s in sources if s.get("status") != "wishlist"):
            req = urllib.request.Request(s["url"], method="HEAD",
                                         headers={"User-Agent": "loci-source-check"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    code = r.status
            except urllib.error.HTTPError as exc:   # 4xx/5xx still means "present"
                code = exc.code
            except Exception as exc:  # noqa: BLE001 - report, don't raise
                code = f"ERR {exc}"
            ok = code in (200, 202, 301, 302, 403)  # 403 = bot-blocked, 202 = challenge page; both mean present
            print(f"{'ok ' if ok else 'FAIL'} {code:<24} {s['id']}")
            if not ok:
                errors.append(f"{s['id']}: url {s['url']} -> {code}")

    if not errors:
        wish_total = sum(s["cost"]["amount"] for s in wishlist)
        print(f"ok — {len(sources) - len(wishlist)} sources, ${budgeted} budgeted, "
              f"no CONTEXT.md drift; {len(wishlist)} wishlist entries "
              f"(${wish_total:,}/yr post-raise), no PAID-SOURCES.md drift")
    return errors


def _validate_wishlist_entry(s: dict) -> list[str]:
    """Schema for status=wishlist. Returns problems for one entry."""
    sid = s.get("id", "?")
    errors = []

    missing = WISHLIST_REQUIRED - s.keys()
    if missing:
        errors.append(f"{sid}: wishlist entry missing {sorted(missing)}")

    cost = s.get("cost")
    if not isinstance(cost, dict) or not isinstance(cost.get("amount"), (int, float)):
        errors.append(f"{sid}: wishlist `cost.amount` must be a number (annual USD)")
    elif cost["amount"] <= 0:
        errors.append(f"{sid}: wishlist cost of {cost['amount']} — 0 is not allowed; "
                      "use the verified price or the tier floor (a free source is not "
                      "a wishlist entry, it belongs in the PAID-SOURCES.md appendix)")
    elif cost.get("unit") != "year":
        errors.append(f"{sid}: wishlist `cost.unit` must be `year`, got {cost.get('unit')!r}")

    tier = s.get("price_tier")
    if tier not in PRICE_TIER_FLOOR:
        errors.append(f"{sid}: bad price_tier {tier!r}")
    elif s.get("cost_basis") == "quote_only" and isinstance(cost, dict):
        floor = PRICE_TIER_FLOOR[tier]
        if cost.get("amount") != floor:
            errors.append(f"{sid}: cost_basis=quote_only must book the {tier} floor "
                          f"${floor}, got ${cost.get('amount')}")

    if s.get("cost_basis") not in VALID_COST_BASIS:
        errors.append(f"{sid}: bad cost_basis {s.get('cost_basis')!r}")
    if s.get("priority") not in VALID_PRIORITY:
        errors.append(f"{sid}: bad priority {s.get('priority')!r}")
    if s.get("integration_effort") not in VALID_EFFORT:
        errors.append(f"{sid}: bad integration_effort {s.get('integration_effort')!r}")
    if s.get("confidence") not in VALID_CONFIDENCE:
        errors.append(f"{sid}: bad confidence {s.get('confidence')!r}")

    gap = s.get("closes_gap", "")
    if not (isinstance(gap, str) and gap.startswith("(") and gap[1:2] in GAP_LETTERS):
        errors.append(f"{sid}: closes_gap must start with a gap letter in (a)..(i)")
    elif len(gap) < 40:
        errors.append(f"{sid}: closes_gap needs the sentence, not just the letter")

    ev = s.get("evidence")
    if not isinstance(ev, list) or not ev:
        errors.append(f"{sid}: evidence must be a non-empty list of {{url, date}}")
    else:
        for e in ev:
            if not (isinstance(e, dict) and e.get("url") and e.get("date")):
                errors.append(f"{sid}: every evidence item needs a url and a date")
                break
    return errors


def _validate_paid_sources_doc(wishlist: list[dict]) -> list[str]:
    """Wishlist entries mirror docs/PAID-SOURCES.md the way the rest mirror CONTEXT.md.

    Same contract as `loci gen-tickets`: the doc is GENERATED, so the check is
    byte-identity against a fresh render, not a fuzzy match. The per-entry name
    check runs too, so a render that silently drops a row names the row.
    """
    if not wishlist:
        return []
    from loci import paid_sources  # local import: paid_sources reads the registry

    doc = ROOT / "docs" / "PAID-SOURCES.md"
    if not doc.exists():
        return ["docs/PAID-SOURCES.md missing — run `loci gen-paid-sources`"]

    errors = []
    text = doc.read_text()
    for s in wishlist:
        if s["name"] not in text:
            errors.append(f"{s['id']}: {s['name']!r} absent from docs/PAID-SOURCES.md")
    if text != paid_sources.render():
        errors.append("docs/PAID-SOURCES.md differs from a fresh render — "
                      "it is GENERATED; run `loci gen-paid-sources`")
    return errors
