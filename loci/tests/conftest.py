"""Shared test fixtures.

The one autouse fixture here pins the citywide mean household income that
`model/gaps._income_context` uses as the demand-caveat denominator (GTM-109).

Why it must be pinned: the real value comes from a live ACS call
(`loci.grid.acs.load_citywide_mean_hh_income`, B19025/B11001 over the five NYC
counties) behind a cache in `data/interim/`, and `data/` is gitignored. Without
this fixture every test that touches `compute_gaps` would either hit the Census
API or fail on a fresh clone, and the gap fixtures' assertions would drift with
each ACS vintage. Production still fails closed -- the loader raises rather than
guessing a dollar figure -- which is exactly why the tests have to inject one.

The pinned numbers are the real ACS 2019-2023 5-year values, rounded, so the
fixtures exercise the same magnitudes the screen sees in production.
"""
from __future__ import annotations

import pytest

#: ACS 2023 5-year: sum(B19025_001E) / sum(B11001_001E) over 36005/36047/36061/
#: 36081/36085 = $127,894 (±$988 at 90%). At demand.yaml's 0.80 cutoff the
#: low-income line sits at $102,315.
TEST_CITYWIDE_MEAN_HH_INCOME = 127_894.0
TEST_CITYWIDE_MEAN_HH_INCOME_MOE = 988.0


@pytest.fixture(autouse=True)
def pinned_citywide_income(monkeypatch):
    monkeypatch.setattr(
        "loci.model.gaps._citywide_income",
        lambda: (TEST_CITYWIDE_MEAN_HH_INCOME, TEST_CITYWIDE_MEAN_HH_INCOME_MOE),
    )
