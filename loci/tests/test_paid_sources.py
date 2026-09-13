"""Tests for the paid-source wishlist: schema, budget exemption, doc drift.

The three failure modes this file exists to pin:
  * a wishlist entry with no price or no licence note — the two fields that
    make it a line item rather than a wish — must not validate;
  * a $300k wishlist must not count against the $100 free-data budget, and
    must not silently blow the ceiling check that exists to catch an accidental
    paid dependency TODAY;
  * docs/PAID-SOURCES.md is GENERATED, so a hand edit must fail `check-sources`
    and a second render must be byte-identical to the first.
"""
from __future__ import annotations

import copy

import pytest

from loci import paid_sources, registry

# A minimal, valid wishlist entry. Every negative case below mutates one field
# of this, so a test that fails names exactly the field it is about.
GOOD = {
    "id": "paid_fixture",
    "name": "Fixture Feed",
    "vendor": "Fixture Co.",
    "tier": "universal",
    "role": "validation",
    "status": "wishlist",
    "category": "foot_traffic",
    "url": "https://example.invalid/",
    "price_tier": "1k_10k_yr",
    "cost": {"amount": 4200, "unit": "year"},
    "cost_basis": "verified",
    "priority": "P1",
    "priority_reason": "It is the fixture.",
    "integration_effort": "low",
    "confidence": "high",
    "price_note": "Published on the vendor's own pricing page.",
    "license_note": "Internal use only; a redistribution rider is required.",
    "closes_gap": "(a) Foot traffic — a measured visit count per storefront, "
                  "which is what D76's graduation test demands.",
    "bias": "A modelled panel, not a count; panel share is unpublished.",
    "evidence": [{"url": "https://example.invalid/pricing", "date": "2026-09-13"}],
}


def _entry(**overrides):
    e = copy.deepcopy(GOOD)
    for k, v in overrides.items():
        if v is _DROP:
            e.pop(k, None)
        else:
            e[k] = v
    return e


class _Drop:
    pass


_DROP = _Drop()


# --------------------------------------------------------------- schema


def test_good_wishlist_entry_validates():
    assert registry._validate_wishlist_entry(GOOD) == []


def test_wishlist_status_is_allowed():
    assert "wishlist" in registry.VALID_STATUS


@pytest.mark.parametrize("field", sorted(registry.WISHLIST_REQUIRED))
def test_every_required_field_is_required(field):
    errors = registry._validate_wishlist_entry(_entry(**{field: _DROP}))
    assert any(field in e for e in errors), f"dropping {field} raised nothing"


def test_missing_cost_is_an_error():
    errors = registry._validate_wishlist_entry(_entry(cost=_DROP))
    assert any("cost.amount" in e for e in errors)


def test_zero_cost_is_an_error():
    """A free source is not a purchase -- it belongs in the doc's appendix.

    This is the rule that keeps the wishlist total honest: a $0 line item
    disappears from every sum while still looking like a commitment.
    """
    errors = registry._validate_wishlist_entry(
        _entry(cost={"amount": 0, "unit": "year"}))
    assert any("0 is not allowed" in e for e in errors)


def test_cost_must_be_annual():
    errors = registry._validate_wishlist_entry(
        _entry(cost={"amount": 4200, "unit": "total"}))
    assert any("cost.unit" in e for e in errors)


def test_missing_license_note_is_an_error():
    errors = registry._validate_wishlist_entry(_entry(license_note=_DROP))
    assert any("license_note" in e for e in errors)


def test_quote_only_must_book_the_tier_floor():
    """Otherwise "quote only" becomes a place to park a guess."""
    off = _entry(price_tier="quote_only", cost_basis="quote_only",
                 cost={"amount": 37_500, "unit": "year"})
    assert any("floor" in e for e in registry._validate_wishlist_entry(off))

    ok = _entry(price_tier="quote_only", cost_basis="quote_only",
                cost={"amount": registry.PRICE_TIER_FLOOR["quote_only"], "unit": "year"})
    assert registry._validate_wishlist_entry(ok) == []


def test_a_verified_price_may_sit_below_its_tier_floor():
    """The band is the vendor's asking range; a signed contract is what was paid.

    Placer.ai is the live case: band $10-50k, verified public-sector orders at
    $8,000. Clamping that to the floor would overstate the wishlist.
    """
    low = _entry(price_tier="10k_50k_yr", cost_basis="verified",
                 cost={"amount": 8_000, "unit": "year"})
    assert registry._validate_wishlist_entry(low) == []


def test_closes_gap_needs_a_letter_and_a_sentence():
    assert any("gap letter" in e for e in registry._validate_wishlist_entry(
        _entry(closes_gap="foot traffic, obviously")))
    assert any("gap letter" in e for e in registry._validate_wishlist_entry(
        _entry(closes_gap="(z) not a gap letter, but a long enough sentence to pass")))
    assert any("the sentence" in e for e in registry._validate_wishlist_entry(
        _entry(closes_gap="(a) foot traffic")))


def test_evidence_needs_a_url_and_a_date():
    assert any("evidence" in e for e in registry._validate_wishlist_entry(
        _entry(evidence=[])))
    assert any("url and a date" in e for e in registry._validate_wishlist_entry(
        _entry(evidence=[{"url": "https://example.invalid/"}])))


@pytest.mark.parametrize("field,bad", [
    ("priority", "P0"), ("integration_effort", "trivial"),
    ("confidence", "certain"), ("cost_basis", "vibes"), ("price_tier", "cheap"),
])
def test_enumerated_fields_reject_junk(field, bad):
    assert registry._validate_wishlist_entry(_entry(**{field: bad}))


# --------------------------------------------- budget exemption


def test_wishlist_is_exempt_from_the_free_data_budget():
    """$300k of post-raise wishlist must not trip the $100 spend ceiling."""
    reg = registry.load()
    wishlist = [s for s in reg["sources"] if s["status"] == "wishlist"]
    assert wishlist, "the registry should carry wishlist entries"

    booked = sum(s["cost"]["amount"] for s in wishlist)
    assert booked > reg["budget"]["projected_max"] * 100, \
        "if the wishlist were this cheap the exemption would not be load-bearing"

    counted = sum(s["cost"].get("budgeted_total", 0) for s in reg["sources"]
                  if "cost" in s and s["status"] != "wishlist")
    assert counted <= reg["budget"]["projected_max"]
    assert registry.validate() == []


def test_wishlist_is_exempt_from_the_context_md_mirror():
    """Wishlist entries mirror PAID-SOURCES.md, not CONTEXT.md section 3."""
    ghost = _entry(dataset_id="zzzz-zzzz")
    assert not any("CONTEXT.md" in e for e in registry._validate_wishlist_entry(ghost))


# ------------------------------------------------- generator + drift


def test_render_is_deterministic():
    assert paid_sources.render() == paid_sources.render()


def test_generate_writes_exactly_what_render_returns():
    n, booked = paid_sources.generate()
    assert n == len(paid_sources.wishlist())
    assert booked == paid_sources.totals(paid_sources.wishlist())[0]
    assert paid_sources.DOC_PATH.read_text() == paid_sources.render()


def test_every_wishlist_entry_appears_in_the_doc():
    text = paid_sources.render()
    for s in paid_sources.wishlist():
        assert s["name"] in text, f"{s['id']} missing from PAID-SOURCES.md"
        assert s["vendor"] in text


def test_doc_drift_is_caught():
    """A hand edit to the generated doc must fail check-sources."""
    original = paid_sources.DOC_PATH.read_text()
    try:
        paid_sources.DOC_PATH.write_text(original + "\nHand-edited.\n")
        errors = registry.validate()
        assert any("PAID-SOURCES.md" in e for e in errors)
    finally:
        paid_sources.DOC_PATH.write_text(original)
    assert registry.validate() == []


def test_doc_carries_the_load_bearing_sections():
    text = paid_sources.render()
    assert "GENERATED — do not edit" in text
    for letter, name, _ in paid_sources.GAPS:
        assert f"### ({letter}) {name}" in text
    for label, _ in paid_sources.ALLOCATION:
        assert f"**At {label}.**" in text
    assert "Redistribution riders" in text          # the non-data line item
    assert "Free, or already ours" in text          # appendix: free
    assert "Defunct, renamed" in text               # appendix: defunct
    assert "strava_metro" in text                   # the two non-purchases
    assert "nyc_dot_vivacity_sensors" in text


def test_totals_are_a_lower_bound():
    """Booked >= floor: quote-only entries book the floor, verified may exceed it."""
    rows = paid_sources.wishlist()
    booked, floor, verified = paid_sources.totals(rows)
    assert floor > 0 and verified > 0
    assert booked >= verified
    quote = [s for s in rows if s["cost_basis"] == "quote_only"]
    assert all(s["cost"]["amount"] == registry.PRICE_TIER_FLOOR[s["price_tier"]]
               for s in quote)


def test_the_two_non_purchases_are_planned_not_wishlist():
    """A data-sharing ask and an ineligible free programme are not line items."""
    by_id = {s["id"]: s for s in registry.load()["sources"]}
    for sid in ("nyc_dot_vivacity_sensors", "strava_metro"):
        assert by_id[sid]["status"] == "planned"
        assert by_id[sid]["cost"]["amount"] == 0
        assert by_id[sid]["notes"]
    assert "does not qualify" in by_id["strava_metro"]["notes"].lower()
    assert "not a purchase" in by_id["nyc_dot_vivacity_sensors"]["notes"].lower()
