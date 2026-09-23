"""Unit tests for RQ-002 v1 fixes -- NAICS-2012 crosswalk (Fix A/B) and the
pioneer/incumbent/follower interval logic (Fix E). Fixtures only, no network, no
live warehouse -- an in-memory DuckDB connection stands in for
`analysis.zip_establishments` for the NAICS tests."""
from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from loci import research_rq002 as rq


# --------------------------------------------------------------------- fixtures

@pytest.fixture
def fake_con():
    """In-memory DuckDB with a fixture `analysis.zip_establishments` table: one ZIP,
    both NAICS eras, WITH the emp_size_band sub-band rows present (so a test can
    catch a Fix B regression -- summing 'All establishments' plus its own sub-bands
    would double the count)."""
    con = duckdb.connect(":memory:")
    con.execute("create schema analysis")
    con.execute("""
        create table analysis.zip_establishments (
            year smallint, zipcode varchar, naics varchar, naics_label varchar,
            emp_size_band varchar, estab integer
        )
    """)
    rows = [
        # 2011 (pre-2012 codes): 10 full-service + 5 limited-service + 2 snack bars = 17 restaurants total.
        (2011, "99999", "722110", "Full-service restaurants", "All establishments", 10),
        (2011, "99999", "722110", "Full-service restaurants", "Establishments with less than 5 employees", 8),
        (2011, "99999", "722110", "Full-service restaurants", "Establishments with 5 to 9 employees", 2),
        (2011, "99999", "722211", "Limited-service restaurants", "All establishments", 5),
        (2011, "99999", "722213", "Snack & nonalcoholic beverage bars", "All establishments", 2),
        (2011, "99999", "722410", "Drinking places (alcoholic beverages)", "All establishments", 3),
        # 2012 (post-2012 codes): same real-world level, new codes.
        (2012, "99999", "722511", "Full-service restaurants", "All establishments", 11),
        (2012, "99999", "722513", "Limited-service restaurants", "All establishments", 5),
        (2012, "99999", "722515", "Snack and nonalcoholic beverage bars", "All establishments", 2),
        (2012, "99999", "722410", "Drinking places (alcoholic beverages)", "All establishments", 3),
        # noise the crosswalk must NOT pick up: caterers/mobile food (excluded NAICS).
        (2012, "99999", "722320", "Caterers", "All establishments", 4),
    ]
    con.executemany("insert into analysis.zip_establishments values (?,?,?,?,?,?)", rows)
    yield con
    con.close()


# ------------------------------------------------------- Fix A/B: NAICS crosswalk

def test_food_drink_corrected_covers_pre_2012_codes(fake_con):
    """The pre-2012 codes (722110/722211/722213) must resolve to real counts, not
    zero -- this is the exact bug (zbp_naics.yaml only recognizes post-2012 codes)
    that made v0's food_drink series collapse before 2012."""
    out = rq.load_food_drink_corrected(fake_con, ["99999"])
    row_2011 = out[out["year"] == 2011].iloc[0]
    assert row_2011["restaurant"] == 15   # 10 (722110) + 5 (722211), 'All establishments' rows only
    assert row_2011["cafe_bakery"] == 2   # 722213
    assert row_2011["bar"] == 3           # 722410
    assert row_2011["food_drink_corrected"] == 20


def test_food_drink_corrected_no_2012_discontinuity(fake_con):
    """The fixture's 2011 and 2012 rows represent the SAME real-world level (17 vs.
    18 total restaurant+cafe establishments) under different NAICS eras -- the
    corrected series must show an ordinary year-over-year change, not a cliff."""
    out = rq.load_food_drink_corrected(fake_con, ["99999"])
    v2011 = out.loc[out["year"] == 2011, "food_drink_corrected"].iloc[0]
    v2012 = out.loc[out["year"] == 2012, "food_drink_corrected"].iloc[0]
    pct_change = abs(v2012 - v2011) / v2011 * 100
    assert pct_change < 25, f"discontinuity at 2012: {v2011} -> {v2012} ({pct_change:.0f}%)"


def test_food_drink_corrected_does_not_double_count_emp_size_bands(fake_con):
    """Fix B: `emp_size_band='All establishments'` is the ONLY band load_naics_raw
    should read. If a future edit accidentally summed the sub-bands too, 2011's
    722110 count would come back as 10 (total) + 8 + 2 (sub-bands) = 20 instead of
    10 -- this test fails loudly if that regression is reintroduced."""
    raw = rq.load_naics_raw(fake_con, ["99999"], naics_codes=["722110"])
    row_2011 = raw[raw["year"] == 2011].iloc[0]
    assert row_2011["estab"] == 10, (
        f"expected 10 ('All establishments' only), got {row_2011['estab']} -- "
        "looks like sub-bands got summed in too (Fix B regression)")


def test_food_drink_excludes_caterers_and_mobile_food(fake_con):
    """722320 (caterers) is fixture-present at 2012 with estab=4 but must NOT show up
    anywhere in the corrected total -- it is deliberately excluded (not a walk-in
    storefront)."""
    out = rq.load_food_drink_corrected(fake_con, ["99999"])
    v2012 = out.loc[out["year"] == 2012, "food_drink_corrected"].iloc[0]
    # food_drink_corrected sums all three buckets (restaurant+cafe_bakery+bar);
    # 722320 (caterers, estab=4 in the fixture) must NOT be part of this sum.
    assert v2012 == 11 + 5 + 2 + 3
    assert "722320" not in rq.FOOD_DRINK_NAICS_XWALK


def test_naics_2012_discontinuity_check_flags_a_broken_series():
    """naics_2012_discontinuity_check must clearly show a v0-style broken series
    (near-zero pre-2012, cliff at 2012) as different from a corrected one, so the
    notebook's own verification step (Section 3) has something real to compare."""
    corrected = pd.DataFrame({
        "zip": ["99999", "99999"], "year": [2011, 2012],
        "restaurant": [15, 16], "cafe_bakery": [2, 2], "bar": [3, 3],
        "food_drink_corrected": [20, 21],
    })
    broken = pd.DataFrame({
        "zip": ["99999", "99999"], "year": [2011, 2012],
        "food_drink": [2, 21],   # v0-style: nearly all pre-2012 restaurants missing, cliff at 2012
    })
    check = rq.naics_2012_discontinuity_check(corrected, broken, zip_="99999")
    row_2012 = check[check["year"] == 2012].iloc[0]
    assert abs(row_2012["corrected_pct_chg"]) < 25
    assert row_2012["broken_pct_chg"] > 100   # the cliff v0 actually had (+332% in the live data)


# --------------------------------------------------- Fix E: pioneer/interval logic

def _poi_row(name, category, first_seen_on=None, first_seen_kind="source_date",
             is_left_censored=False, is_closed=False):
    return {"display_name": name, "category": category, "first_seen_on": first_seen_on,
            "first_seen_month": None, "first_seen_kind": first_seen_kind,
            "is_left_censored": is_left_censored, "is_closed": is_closed}


@pytest.fixture
def poi_fixture():
    rows = [
        # a genuine pioneer (dated, before the 2013 cutoff)
        _poi_row("Cafe Grumpy", "cafe_bakery", pd.Timestamp("2005-12-15")),
        _poi_row("Glasserie", "restaurant", pd.Timestamp("2013-05-18")),
        # a genuine follower (dated, at/after the 2018 cutoff)
        _poi_row("Oxomoco", "restaurant", pd.Timestamp("2018-05-01")),
        _poi_row("Wenwen", "restaurant", pd.Timestamp("2022-03-11")),
        # a transitional-window business (2014-2017)
        _poi_row("Fourfivesix", "cafe_bakery", pd.Timestamp("2015-06-01")),
        # left-censored -- must be UNDATED, excluded from any dated claim
        _poi_row("Achilles Heel", "bar", None, first_seen_kind="backfill_censored", is_left_censored=True, is_closed=True),
        # 'observed' kind -- must ALSO be UNDATED even though a date is present
        _poi_row("Some Observed Spot", "bar", pd.Timestamp("2019-01-01"), first_seen_kind="observed"),
        # a shared-artifact-date cluster: 5 unrelated POIs on the same day, not censored
        *[_poi_row(f"Artifact Spot {i}", "restaurant", pd.Timestamp("2012-02-08")) for i in range(5)],
        # a non-food category row that must be excluded entirely (not bar/cafe_bakery/restaurant)
        {"display_name": "Some Grocery", "category": "grocery", "first_seen_on": pd.Timestamp("2010-01-01"),
         "first_seen_month": None, "first_seen_kind": "source_date", "is_left_censored": False, "is_closed": False},
    ]
    return pd.DataFrame(rows)


def test_classify_new_wave_pioneer_follower_transitional(poi_fixture):
    out = rq.classify_new_wave(poi_fixture)
    by_name = out.set_index("display_name")["wave_class"]
    assert by_name["Cafe Grumpy"] == "NEW_WAVE-PIONEER"
    assert by_name["Glasserie"] == "NEW_WAVE-PIONEER"          # 2013 == cutoff, inclusive
    assert by_name["Oxomoco"] == "NEW_WAVE-FOLLOWER"
    assert by_name["Wenwen"] == "NEW_WAVE-FOLLOWER"
    assert by_name["Fourfivesix"] == "NEW_WAVE-TRANSITIONAL"
    # non-food category never enters the classified frame at all
    assert "Some Grocery" not in by_name.index


def test_classify_new_wave_excludes_censored_and_observed(poi_fixture):
    out = rq.classify_new_wave(poi_fixture)
    by_name = out.set_index("display_name")["wave_class"]
    assert by_name["Achilles Heel"] == "UNDATED"
    assert by_name["Some Observed Spot"] == "UNDATED", (
        "'observed' first_seen_kind must be excluded from dated claims even though a date is present")


def test_classify_new_wave_flags_shared_artifact_dates(poi_fixture):
    """5 unrelated POIs sharing one first_seen_on date (not censored) must be flagged
    as an ingestion-artifact, not trusted as 5 real synchronized openings."""
    out = rq.classify_new_wave(poi_fixture)
    artifact_rows = out[out["display_name"].str.startswith("Artifact Spot")]
    assert (artifact_rows["wave_class"] == "INCUMBENT (dataset-start artifact)").all()


def test_classify_new_wave_does_not_flag_dates_shared_by_only_two(poi_fixture):
    """Below the min_group_size threshold (default 5), a shared date must NOT be
    auto-flagged -- this is the Warsaw/Thai Cafe case (2 businesses, same date):
    the general rule should NOT catch them; only the owner's named-seed override
    (in the notebook, not this function) does."""
    two_row_fixture = pd.DataFrame([
        _poi_row("Warsaw", "restaurant", pd.Timestamp("2003-12-10")),
        _poi_row("Thai Cafe", "restaurant", pd.Timestamp("2003-12-10")),
    ])
    out = rq.classify_new_wave(two_row_fixture)
    assert not (out["wave_class"] == "INCUMBENT (dataset-start artifact)").any()
    # both fall before the pioneer cutoff and so are (incorrectly, if trusted) NEW_WAVE-PIONEER --
    # exactly why the notebook's named-list override exists.
    assert (out["wave_class"] == "NEW_WAVE-PIONEER").all()


def test_pioneer_follower_interval_bounds_and_shares(poi_fixture):
    classified = rq.classify_new_wave(poi_fixture)
    interval = rq.pioneer_follower_interval(classified)
    n_total = len(classified)  # 12 food/drink/bar rows (grocery excluded): 2 pioneer + 2 follower
    assert n_total == 12       # + 1 transitional + 1 censored + 1 observed + 5 artifact-date
    assert interval["n_undated"] == 2   # Achilles Heel + the observed row
    assert interval["NEW_WAVE-PIONEER"]["certain"] == 2      # Cafe Grumpy, Glasserie
    assert interval["NEW_WAVE-FOLLOWER"]["certain"] == 2      # Oxomoco, Wenwen
    assert interval["NEW_WAVE-TRANSITIONAL"]["certain"] == 1  # Fourfivesix
    assert interval["INCUMBENT (dataset-start artifact)"]["certain"] == 5
    # pioneer count is a LOWER bound: certain, up to certain + all undated rows
    assert interval["NEW_WAVE-PIONEER"]["upper_bound_with_censored"] == 2 + interval["n_undated"]
    # open/closed split: Achilles Heel is the only closed UNDATED row
    assert interval["UNDATED"]["n_closed"] == 1
    assert interval["UNDATED"]["n_open"] == 1
