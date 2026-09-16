"""Full-history filing ingest (sources/cities/nyc/filing_feeds.py).

The clip these tests replace was `WINDOW_MONTHS = 24`, applied on every feed,
which put ZERO rows before 2024-09-13 into staging.storefront_filing. Nothing
failed: a 24-month window returns plenty of rows, so the hole was invisible to
every count, every constraint and every existing test. It only became visible
when somebody asked a question about 2020.

Four things under test:

(a) NO PREDICATE MEANS NO PREDICATE. `since=None` -- the default on every
    fetcher -- must send NO `$where` date clause at all. An empty string or a
    `>= 1900-01-01` tautology would both "work" while making the provenance
    string lie about what was pulled, and `$where=` is an HTTP 400.

(b) THE OPT-IN CLIP STILL CLIPS. `--since` and `--window-months` must produce
    the predicate they claim, so reproducing an older extract stays possible.

(c) BIS DATES. ipu4-2q9a publishes `2014-09-09` and `09/30/2013` in the same
    TEXT column. Both must parse; a lexical `$where` must never be sent
    against that column even when `since` is given, because it would silently
    drop every row in the second format.

(d) THE TWO DOB DATASETS DO NOT DOUBLE-COUNT. BIS and DOB NOW overlap at the
    cutover and are ingested as one registered source; their row ids must stay
    in disjoint namespaces so `filing_id` keeps them apart.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from loci.sources.cities.nyc import filing_feeds as ff

# --------------------------------------------------------------- (a) no clip

def _captured(monkeypatch) -> list[dict]:
    """Stub socrata so the fetchers run without a network, recording the call."""
    calls: list[dict] = []

    def fake_fetch(source_id, domain, dataset, **kw):
        calls.append({"dataset": dataset, **kw})
        return []

    monkeypatch.setattr(ff.socrata, "fetch", fake_fetch)
    monkeypatch.setattr(ff.socrata, "assert_fields",
                        lambda *a, **k: None)
    return calls


@pytest.mark.parametrize("fetcher,datecol", [
    (ff.fetch_dcwp_licenses, "license_creation_date"),
    (ff.fetch_dcwp_applications, "submission_date"),
    (ff.fetch_dob_permits, "issued_date"),
    (ff.fetch_sla_pending, "received_date"),
    (ff.fetch_sla_active, "originalissuedate"),
])
def test_default_sends_no_date_predicate(monkeypatch, fetcher, datecol):
    calls = _captured(monkeypatch)
    fetcher(asof=dt.date(2026, 9, 16))
    where = calls[0]["where"]
    assert where is None or datecol not in where, (
        f"{fetcher.__name__} still clips on {datecol} by default: {where!r}")


def test_a_feed_with_no_other_filter_sends_where_none(monkeypatch):
    """Not an empty string. `$where=` is a 400, and `$where=1=1` is a lie."""
    calls = _captured(monkeypatch)
    ff.fetch_dcwp_licenses(asof=dt.date(2026, 9, 16))
    assert calls[0]["where"] is None


def test_the_county_filter_survives_when_the_date_clip_goes(monkeypatch):
    """Dropping the window must not drop the five-borough scope with it."""
    calls = _captured(monkeypatch)
    ff.fetch_sla_active(asof=dt.date(2026, 9, 16))
    assert "premisescounty in" in calls[0]["where"]
    assert "originalissuedate" not in calls[0]["where"]


def test_dohmh_keeps_its_1900_sentinel_guard(monkeypatch):
    """The sentinel exclusion is not a date window and must not be removed:
    without it DOHMH's 'permitted, never inspected' rows date every such
    establishment to 1900."""
    calls = _captured(monkeypatch)
    ff.fetch_dohmh_first_inspection(asof=dt.date(2026, 9, 16))
    assert ff.SENTINEL in calls[0]["where"]


# ----------------------------------------------------------- (b) opt-in clip

def test_since_reinstates_the_predicate(monkeypatch):
    calls = _captured(monkeypatch)
    ff.fetch_dcwp_licenses(asof=dt.date(2026, 9, 16), since=dt.date(2020, 1, 1))
    assert calls[0]["where"] == "license_creation_date >= '2020-01-01T00:00:00'"


def test_window_start_still_computes_the_old_24_month_clip():
    assert ff.window_start(dt.date(2026, 9, 16), 24) == dt.date(2024, 9, 16)
    assert ff.WINDOW_MONTHS == 24


def test_dob_now_where_is_none_free_and_still_filters_storefronts():
    unclipped = ff.dob_now_where(dt.date(2026, 9, 16))
    assert "filing_date" not in unclipped
    assert "general_construction_work_type_='YES'" in unclipped
    clipped = ff.dob_now_where(dt.date(2026, 9, 16), dt.date(2020, 1, 1))
    assert clipped.startswith("filing_date >= '2020-01-01T00:00:00'")


# -------------------------------------------------------------- (c) BIS dates

@pytest.mark.parametrize("raw,expect", [
    ("2014-09-09", dt.date(2014, 9, 9)),
    ("2014-09-09T00:00:00.000", dt.date(2014, 9, 9)),
    ("09/30/2013", dt.date(2013, 9, 30)),
    ("1/2/2013", dt.date(2013, 1, 2)),   # unpadded m/d/y is unambiguous here
    ("", None),
    (None, None),
    ("not a date", None),
    ("13/45/2013", None),        # parses as m/d/y and is out of range
])
def test_bis_mixed_date_formats(raw, expect):
    assert ff._date_mixed(raw) == expect


def test_bis_never_sends_a_lexical_date_predicate(monkeypatch):
    """Even WITH `since`. A SoQL comparison on ipu4-2q9a's TEXT issuance_date
    sorts '09/30/2013' after '2014-09-09' and would drop the whole
    slash-format era without any error."""
    calls = _captured(monkeypatch)
    ff.fetch_bis_permits(asof=dt.date(2026, 9, 16), since=dt.date(2020, 1, 1))
    assert "issuance_date" not in calls[0]["where"]
    assert calls[0]["where"] == "permit_type in ('AL', 'SG')"


def test_bis_applies_since_client_side(monkeypatch):
    rows = [
        {"permit_si_no": "1", "permit_type": "AL", "issuance_date": "09/30/2013"},
        {"permit_si_no": "2", "permit_type": "AL", "issuance_date": "2021-06-01"},
        {"permit_si_no": "3", "permit_type": "SG", "issuance_date": ""},
    ]
    monkeypatch.setattr(ff.socrata, "assert_fields", lambda *a, **k: None)
    monkeypatch.setattr(ff.socrata, "fetch", lambda *a, **k: rows)
    out = ff.fetch_bis_permits(asof=dt.date(2026, 9, 16), since=dt.date(2020, 1, 1))
    assert list(out["raw_id"]) == ["2"]          # 2013 clipped, undated dropped

    everything = ff.fetch_bis_permits(asof=dt.date(2026, 9, 16))
    assert sorted(everything["raw_id"]) == ["1", "2"]   # undated still dropped


def test_bis_rows_are_stage_typed_and_carry_the_bis_marker(monkeypatch):
    rows = [
        {"permit_si_no": "1", "permit_type": "AL", "permit_subtype": "OT",
         "issuance_date": "2021-06-01"},
        {"permit_si_no": "2", "permit_type": "SG", "issuance_date": "2021-06-01"},
        {"permit_si_no": "3", "permit_type": "NB", "issuance_date": "2021-06-01"},
    ]
    monkeypatch.setattr(ff.socrata, "assert_fields", lambda *a, **k: None)
    monkeypatch.setattr(ff.socrata, "fetch", lambda *a, **k: rows)
    out = ff.fetch_bis_permits(asof=dt.date(2026, 9, 16))
    assert dict(zip(out["raw_id"], out["stage"])) == {
        "1": "permit_issued", "2": "sign_permit"}      # NB never mapped
    assert all(t.startswith("BIS ") for t in out["license_type"])


# --------------------------------------------------- (d) the two DOB datasets

def test_both_dob_datasets_land_under_the_one_registered_source(monkeypatch):
    """registry.yaml:822 declares ipu4-2q9a and rbx6-tga4 as ONE source. A
    second source id here would be unregistered AND would arm write()'s
    DELETE-by-source to erase the other dataset's rows."""
    monkeypatch.setattr(ff.socrata, "assert_fields", lambda *a, **k: None)

    def fake(source_id, domain, dataset, **kw):
        if dataset == ff.BIS_PERMITS_DATASET:
            return [{"permit_si_no": "B1", "permit_type": "AL",
                     "issuance_date": "2015-01-05"}]
        return [{"job_filing_number": "M00528469-I1",
                 "work_type": "General Construction",
                 "issued_date": "2025-01-05T00:00:00"}]

    monkeypatch.setattr(ff.socrata, "fetch", fake)
    out = ff.fetch_dob_permits_all(asof=dt.date(2026, 9, 16))
    assert set(out["source"]) == {"nyc_dob_permit_issuance"}
    # Disjoint id namespaces: filing_id = source:stage:raw_id must not collide.
    assert len(set(out["raw_id"])) == len(out) == 2
    assert set(out["filed_on"]) == {dt.date(2015, 1, 5), dt.date(2025, 1, 5)}


def test_every_feeds_key_is_a_registered_source_id():
    """The dispatch table's keys ARE registry.yaml source ids. A key that is
    not one puts an untraceable value in staging.storefront_filing.source."""
    import yaml

    from loci import db as locidb
    reg = yaml.safe_load(
        (locidb.PKG / "registry.yaml").read_text())
    ids = {s["id"] for s in reg["sources"]}

    # ONE PRE-EXISTING EXCEPTION, pinned rather than fixed. The FEEDS key is
    # `nyc_sla_liquor_licenses`; registry.yaml:251 calls the same dataset
    # (9s3h-dpkz) `nys_sla_liquor_licenses` -- NYS, not NYC, because the State
    # Liquor Authority is a state agency. The two names differ by ONE LETTER
    # and mean the same thing, which is the failure mode CLAUDE.md's naming
    # rule exists to prevent, read in reverse.
    #
    # NOT renamed here, deliberately: `source` is a stored column and
    # staging.storefront_filing already holds 24,850 rows under the FEEDS
    # spelling. Renaming is a data migration with a DELETE-by-source in it, it
    # belongs in its own ticket, and doing it inside a backfill would mean a
    # single change moved both the row population and the row identity.
    known = {"nyc_sla_liquor_licenses"}
    assert set(ff.FEEDS) - known <= ids, sorted(set(ff.FEEDS) - known - ids)
    assert "nys_sla_liquor_licenses" in ids, (
        "the registry entry this exception points at is gone; either the "
        "rename happened and `known` should shrink, or the source was dropped")


def test_a_feed_returning_nothing_is_still_a_frame_with_the_contract():
    """An empty pull must not change the column contract downstream reads."""
    assert list(ff._frame([]).columns) == list(ff.FEED_COLUMNS)


def test_provenance_says_full_history_when_it_is(monkeypatch):
    """Provenance is what a later reader uses to know what a row count means.
    'FULL HISTORY' and 'since 2024-09-16' must not be confusable."""
    monkeypatch.setattr(ff.socrata, "assert_fields", lambda *a, **k: None)
    monkeypatch.setattr(ff.socrata, "fetch", lambda *a, **k: [
        {"license_nbr": "1-DCA", "license_creation_date": "2001-03-04T00:00:00",
         "license_status": "Active"}])
    full = ff.fetch_dcwp_licenses(asof=dt.date(2026, 9, 16))
    assert "FULL HISTORY" in full["provenance"].iloc[0]
    clipped = ff.fetch_dcwp_licenses(asof=dt.date(2026, 9, 16),
                                     since=dt.date(2024, 9, 16))
    assert "2024-09-16 onward" in clipped["provenance"].iloc[0]
    assert "FULL HISTORY" not in clipped["provenance"].iloc[0]


def test_and_helper_drops_empties_and_returns_none_when_all_empty():
    assert ff._and(None, None) is None
    assert ff._and("a", None, "b") == "a AND b"
    assert ff._and("") is None


def test_pandas_nan_business_name_does_not_become_a_brand(monkeypatch):
    """Regression guard carried from the 'nan' brand bug: a NaN name must not
    survive the frame as the string 'nan'."""
    monkeypatch.setattr(ff.socrata, "assert_fields", lambda *a, **k: None)
    monkeypatch.setattr(ff.socrata, "fetch", lambda *a, **k: [
        {"permit_si_no": "1", "permit_type": "AL",
         "issuance_date": "2021-01-01", "owner_s_business_name": "  "}])
    out = ff.fetch_bis_permits(asof=dt.date(2026, 9, 16))
    assert pd.isna(out["business_name"].iloc[0]) or out["business_name"].iloc[0] is None
