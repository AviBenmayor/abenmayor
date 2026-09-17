"""The three 2026-09-17 card context lines (report/render._context_lines):
licence non-renewal, premises tenure, filing activity. Each prints its n and
the 'context, not a grade' tag; a measure that has not been run prints
nothing rather than a zero; none of them touches a grade."""
from __future__ import annotations

import datetime as dt

from loci.report import render
from loci.report.evidence import EvidencePack


def _pack(demand: dict, category="restaurant") -> EvidencePack:
    return EvidencePack(
        address={"address_id": "A1", "borough": "BK", "lon": -73.95, "lat": 40.68},
        scores={}, grades=[{"category": category, "grade": "C"}], forecast=None,
        supply=[], demand=demand, legality={}, context={"catchment_m": 400},
        provenance={}, vacant_storefronts=[], pipeline=[], chains_watch=[])


def test_nothing_is_printed_when_no_measure_has_run():
    assert render._context_lines(_pack({})) == []


def test_licence_line_carries_n_borough_rate_and_the_tag():
    lines = render._context_lines(_pack({
        "n_licences_400m": 12, "n_nonrenewed_400m": 4, "nonrenewal_rate_5y_400m": 4 / 12,
        "nonrenewal_rate_5y_borough": 0.28, "nonrenewal_n_borough": 3210}))
    line = next(x for x in lines if x.startswith("- Licence non-renewal"))
    assert "4 of 12 SLA restaurant licences within 400 m" in line
    assert "33.3%" in line and "vs 28.0% across the borough (n = 3,210)" in line
    assert render.CONTEXT_TAG in line and "upper bound" in line


def test_licence_line_with_zero_licences_says_so_without_a_rate():
    lines = render._context_lines(_pack({"n_licences_400m": 0, "n_nonrenewed_400m": 0,
                                         "nonrenewal_rate_5y_400m": None}))
    assert any("no SLA restaurant licence within 400 m" in x for x in lines)


def test_tenure_and_filing_lines():
    lines = render._context_lines(_pack({
        "n_premises_400m": 57, "premises_turnover_400m": 0.2,
        "median_tenure_years_400m": 3.0,
        "sign_permit_400m_12m": 5, "fitout_400m_12m": 40, "permit_issued_400m_12m": 30,
        "liquor_application_400m_12m": 2, "filings_blind_asof": dt.date(2026, 9, 17)}))
    tenure = next(x for x in lines if x.startswith("- Tenure"))
    assert "57 LL157 storefront premises" in tenure and "median occupancy run 3 years" in tenure
    assert "every 5.0 premises-years" in tenure and render.CONTEXT_TAG in tenure
    filing = next(x for x in lines if x.startswith("- Filing activity"))
    assert "5 sign permits, 40 DOB fit-out filings, 30 permits issued, 2 SLA applications" in filing
    assert "(as of 2026-09-17)" in filing and "D88" in filing and render.CONTEXT_TAG in filing


def test_context_lines_do_not_change_the_grade():
    pack = _pack({"n_licences_400m": 12, "n_nonrenewed_400m": 4,
                  "nonrenewal_rate_5y_400m": 1 / 3})
    before = [dict(g) for g in pack.grades]
    render._context_lines(pack)
    assert pack.grades == before
