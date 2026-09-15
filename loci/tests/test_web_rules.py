"""evidence/web_rules.py -- classifying one search Hit against one POI (D98,
GTM-170, constraint "Closure rule").

THE ADVERSARIAL CASES ARE THE POINT. A phrase match in unstructured web text
is the noisiest evidence channel Loci has; this module exists to refuse
plausible-looking false positives, not just to accept true ones:
  * a negation in the same window ("temporarily closed") must refuse;
  * an aggregator domain (Yelp) must refuse even with a clean phrase match;
  * a chain POI needs its street token, or a citywide press hit about a
    DIFFERENT branch could flip this one;
  * an undated hit must refuse, even with everything else clean;
  * web evidence must NEVER produce 'open'.
"""
from __future__ import annotations

import datetime as dt

from loci.evidence.web_rules import PoiContext, classify, domain_class_of
from loci.evidence.web_search import Hit

POI = PoiContext(poi_id="p1", name="Windclimb", street="Richardson St")


def _hit(**kw):
    defaults = dict(url="https://ny.eater.com/2026/8/1/windclimb-closed",
                    title="Windclimb Has Closed on Richardson Street",
                    snippet="Windclimb, the Williamsburg coffee bar, has permanently closed "
                            "after five years on Richardson Street.",
                    published="2026-08-01", domain="ny.eater.com")
    defaults.update(kw)
    return Hit(**defaults)


def test_clean_first_party_closure_is_accepted():
    row = classify(_hit(), POI, query="q")
    assert row.verdict == "closed"
    assert row.dated_by == "published"
    assert row.evidence_date == dt.date(2026, 8, 1)
    assert row.domain_class == "news"


def test_negation_in_window_refuses():
    row = classify(_hit(title="Windclimb update",
                        snippet="Windclimb has permanently closed for renovation and will "
                                "reopen next month."),
                   POI, query="q")
    assert row.verdict is None
    assert "negation" in row.reason


def test_closed_on_mondays_is_a_negation_not_a_closure():
    row = classify(_hit(title="Hours", snippet="Windclimb is closed on Mondays; open all other days."),
                   POI, query="q")
    assert row.verdict is None


def test_aggregator_domain_refuses_even_with_a_clean_phrase():
    row = classify(_hit(url="https://www.yelp.com/biz/windclimb", domain="www.yelp.com"),
                   POI, query="q")
    assert row.verdict is None
    assert row.domain_class == "aggregator"
    assert "not_first_party_or_news" in row.reason


def test_mapquest_is_also_an_aggregator():
    assert domain_class_of("mapquest.com", POI) == "aggregator"


def test_other_domain_not_on_the_allowlist_refuses():
    row = classify(_hit(url="https://randomblog.example/x", domain="randomblog.example"),
                   POI, query="q")
    assert row.verdict is None
    assert row.domain_class == "other"


def test_undated_page_refuses_even_if_everything_else_is_clean():
    row = classify(_hit(published=None), POI, query="q")
    assert row.verdict is None
    assert row.reason == "undated"
    # still stored with a real evidence_date (retrieval-time), just not trusted as a verdict
    assert row.evidence_date is not None
    assert row.dated_by == "none"


def test_name_not_mentioned_refuses():
    row = classify(_hit(title="Some other cafe closed", snippet="Totally unrelated business."),
                   POI, query="q")
    assert row.verdict is None
    assert row.reason == "name_not_found_in_hit"


def test_chain_poi_requires_the_street_token():
    chain = PoiContext(poi_id="c1", name="Chock Full o Coffee", street="Bedford Ave", is_chain=True)
    hit = _hit(title="Chock Full o Coffee has permanently closed",
              snippet="The chain confirmed the closure of its location this week.")
    row = classify(hit, chain, query="q")
    assert row.verdict is None
    assert row.reason == "chain_needs_street_token"

    hit_with_street = _hit(
        title="Chock Full o Coffee has permanently closed on Bedford Ave",
        snippet="The Bedford Ave location shut its doors, has closed for good, the chain confirmed.")
    row2 = classify(hit_with_street, chain, query="q")
    assert row2.verdict == "closed"


def test_non_chain_poi_does_not_need_a_street_token():
    row = classify(_hit(), POI, query="q")     # POI.is_chain is False, no street in the hit
    assert row.verdict == "closed"


def test_web_evidence_never_yields_open():
    """Even a hit describing a reopening never sets verdict='open' -- web
    evidence's only sanctioned output is 'closed' or None."""
    row = classify(_hit(title="Windclimb reopens on Richardson Street",
                        snippet="Windclimb has reopened after a brief renovation."),
                   POI, query="q")
    assert row.verdict != "open"


def test_first_party_domain_via_website_match():
    poi = PoiContext(poi_id="p2", name="Bakeri", street="North 8th St",
                     website="https://bakeribrooklyn.com")
    row = classify(_hit(url="https://bakeribrooklyn.com/news/closing",
                        domain="bakeribrooklyn.com",
                        title="Bakeri has closed", snippet="After 15 years, Bakeri has closed "
                        "for good, permanently closed as of this month."),
                   poi, query="q")
    assert row.domain_class == "first_party"
    assert row.verdict == "closed"


def test_successor_name_is_captured_but_never_becomes_a_new_poi():
    row = classify(_hit(title="Windclimb has closed, replaced by Grab and Go",
                        snippet="The space has permanently closed and is now Grab and Go."),
                   POI, query="q")
    assert row.verdict == "closed"
    assert row.successor_name is not None
    assert "Grab and Go" in row.successor_name
    # EvidenceRow carries no poi-creation hook -- successor_name is text only.
    assert not hasattr(row, "successor_poi_id")


def test_inconclusive_lookups_are_still_stored_with_a_reason():
    """So a --recheck-days window sees this URL as already tried, rather
    than re-buying it next run."""
    row = classify(_hit(url="https://randomblog.example/x", domain="randomblog.example"),
                   POI, query="q")
    assert row.poi_id == "p1"
    assert row.url == "https://randomblog.example/x"
    assert row.reason is not None
