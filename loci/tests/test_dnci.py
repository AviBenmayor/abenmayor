import math
from loci.score.dnci import dnci_from_counts, category_score, W, K
from loci.categories import CATEGORIES


def test_weights_sum_to_one():
    assert abs(sum(W.values()) - 1.0) < 1e-9


def test_first_establishment_scores_around_055_for_essentials():
    # k=1.25 for essentials -> 1-exp(-1/1.25) = ~0.55
    assert 0.53 < category_score("grocery", 1) < 0.57


def test_geometric_mean_punishes_missing_essentials():
    """THE crux. A hex with 50 restaurants but no grocery/pharmacy/laundry/etc
    must score LOW — far below a balanced hex with one of everything."""
    restaurants_only = dnci_from_counts({"restaurant": 50})
    balanced = dnci_from_counts({c: 1 for c in K})    # one of every category
    well_served = dnci_from_counts({c: 5 for c in K}) # a genuinely complete area
    assert restaurants_only < 0.2
    assert balanced > 0.4          # one of everything is moderately complete
    assert well_served > 0.6       # completeness scores high
    assert restaurants_only < balanced < well_served

    # Prove the geometric form is doing the work. Take a hex with 5 of EVERY
    # category EXCEPT the four essentials (grocery/convenience/pharmacy/laundry).
    # An arithmetic mean rates it well-served; the geometric mean correctly tanks
    # it because the missing essentials are near-zero factors. This is the whole
    # reason the index is geometric (CONTEXT.md §4.4 / decision D7).
    gap = {c: 5 for c in K if CATEGORIES[c].tier != 1}
    geom = dnci_from_counts(gap)
    arith = sum(W[c] * category_score(c, gap.get(c, 0)) for c in W)
    assert geom < 0.25       # geometric mean punishes the essentials gap hard
    assert arith > 0.45      # arithmetic mean would call this hex well-served
    assert geom < arith


def test_more_of_one_category_saturates():
    assert dnci_from_counts({c: 1 for c in K}) < dnci_from_counts({c: 5 for c in K})
    # but the marginal gain shrinks (saturation)
    d1 = category_score("grocery", 1)
    d5 = category_score("grocery", 5)
    d10 = category_score("grocery", 10)
    assert (d5 - d1) > (d10 - d5)
