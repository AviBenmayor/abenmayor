"""The three sources that used to pull ONE vintage now pull the whole series.

Owner rule, 2026-09-16: "your goal is to have AS MUCH AS DATA AS POSSIBLE" and
"never ever ever limit data pulls". Three adapters carried a cap that was ours
rather than the publisher's:

    census_cbp_national.DEFAULT_YEAR = 2023   -> 1986-2023 (three shapes)
    census_zbp.DEFAULT_YEAR          = 2023   -> 1998-2023 ingested, 1994+ served
    LODES: three hand-downloaded files        -> every vintage 2002-2023

These tests pin the two things a year loop can get wrong and that no amount of
row counting would reveal:

  1. The ERA TABLES. Every one of these endpoints renames its industry
     variable, its label variable and sometimes its geography partway through
     the series. A wrong name is an HTTP 400 and a wrong era table is a
     26-year table with 5 years of data in it.
  2. The ABSENCE CONTRACT. A year or a code that did not come back must be
     recorded with a reason, never emitted as zero. A renumbered NAICS code
     and "nobody in America ran a restaurant in 2008" are the same number and
     opposite facts.

Pure: no network, no warehouse file. Fetchers are monkeypatched and the only
database is `:memory:`.
"""
from __future__ import annotations

import json
import pathlib

import pandas as pd
import pytest

from loci.sources.universal import census_cbp_national as C
from loci.sources.universal import census_zbp as Z
from loci.sources.universal import lodes_wac as L


# ===========================================================================
# CAP 7 -- census_cbp_national
# ===========================================================================

@pytest.mark.parametrize("year,expected", [
    (1986, "SIC"), (1997, "SIC"),
    (1998, "NAICS1997"), (2002, "NAICS1997"),
    (2003, "NAICS2002"), (2007, "NAICS2002"),
    (2008, "NAICS2007"), (2011, "NAICS2007"),
    (2012, "NAICS2012"), (2016, "NAICS2012"),
    (2017, "NAICS2017"), (2023, "NAICS2017"),
])
def test_cbp_classification_variable_per_era(year, expected):
    """Each boundary year, both sides. Probed live 2026-09-16; a request with
    the wrong variable is answered `unknown variable`, HTTP 400."""
    assert C.classification_for(year) == expected


@pytest.mark.parametrize("year", [1985, 2024, 1900])
def test_cbp_year_outside_the_served_range_names_the_upstream_limit(year):
    with pytest.raises(C.CensusYearUnavailable) as exc:
        C.classification_for(year)
    assert "UPSTREAM" in exc.value.reason


@pytest.mark.parametrize("year,expected", [
    (1986, "GEO_TTL"), (2016, "GEO_TTL"), (2017, "NAME"), (2023, "NAME")])
def test_cbp_geography_name_variable_also_moves(year, expected):
    """`NAME` is a 2017+ spelling; 1986-2016 want GEO_TTL. This is the second
    400 the single-year version would have walked into."""
    assert C.name_var_for(year) == expected


def test_cbp_spans_are_the_verified_ones_not_one_vintage():
    assert C.cbp_county_totals_years() == tuple(range(1986, 2024))   # 38 years
    assert C.CBP_NAICS_YEARS == tuple(range(1998, 2024))             # 26 years
    assert C.CBP_ZIP_YEARS == tuple(range(2018, 2024))               # 6 years
    assert C.CBP_SIC_YEARS == tuple(range(1986, 1998))


def test_cbp_sic_years_are_refused_by_category_with_our_reason_not_a_zero():
    """1986-1997 ARE served by Census. They are not pulled per category because
    this repo holds one industry crosswalk and it is NAICS (D42). The error has
    to say that, so a later session does not read it as "Census has no 1995"."""
    with pytest.raises(C.CensusYearUnavailable) as exc:
        C._require_naics_year(1995)
    assert "not NAICS" in exc.value.reason
    assert "D42" in exc.value.reason


def test_cbp_zip_geography_before_2018_names_the_upstream_limit():
    with pytest.raises(C.CensusYearUnavailable) as exc:
        C.fetch_zbp_zcta(2017)
    assert "UPSTREAM" in exc.value.reason


def _fake_api(served: set[str]):
    """Stand-in for `_api_optional`: 200 for codes in `served`, HTTP 204 (None)
    for everything else -- the exact shape the live API uses."""
    def call(dataset, params):
        code = next(v for k, v in params.items() if k.startswith(("NAICS", "SIC")))
        if code not in served:
            return None
        return [["ESTAB", "EMP", "GEO_TTL", "state", "county"],
                ["7", "42", "Kings County, New York", "36", "047"]]
    return call


def test_a_204_is_recorded_as_absent_and_never_written_as_zero(monkeypatch):
    """The NAICS-renumbering trap. Three crosswalk codes were introduced in
    NAICS 2012; for 1998-2011 the API answers 204 for them. If that became an
    `estab = 0` row, the panel would assert something false about the world."""
    codes = set(C.naics_codes())
    dropped = set(sorted(codes)[:3])
    monkeypatch.setattr(C, "_api_optional", _fake_api(codes - dropped))

    rows, absent = C._pull_by_code(2008, "county:*", "ESTAB,EMP,GEO_TTL")

    assert set(absent["naics"]) == dropped
    assert set(rows["naics"]).isdisjoint(dropped), "a 204 leaked in as a row"
    assert (absent["reason"].str.contains("204")).all()
    assert (absent["naics_vintage"] == "NAICS2007").all()
    assert (rows["year"] == 2008).all() and (rows["naics_vintage"] == "NAICS2007").all()


def test_a_year_where_every_code_204s_raises_instead_of_caching_an_empty_year(monkeypatch):
    monkeypatch.setattr(C, "_api_optional", _fake_api(set()))
    with pytest.raises(C.CensusPullError, match="refusing to cache an empty year"):
        C._pull_by_code(2008, "county:*", "ESTAB")


def test_year_loop_records_named_absences_and_re_raises_everything_else():
    """The distinction the loop exists for: "2011 does not exist" is skippable
    and recorded; "the network flaked on 2011" is not."""
    def one(year):
        if year == 2000:
            raise C.CensusYearUnavailable(2000, "SIC era, our limit")
        return pd.DataFrame({"year": [year]})

    out, skipped = C._loop_years([1999, 2000, 2001], one, "test")
    assert list(out["year"]) == [1999, 2001]
    assert skipped == [{"year": 2000, "reason": "SIC era, our limit"}]

    def flaky(year):
        raise TimeoutError("connection reset")

    with pytest.raises(TimeoutError):
        C._loop_years([1999, 2000], flaky, "test")


def test_year_loop_refuses_to_report_success_when_nothing_came_back():
    def never(year):
        raise C.CensusYearUnavailable(year, "nope")
    with pytest.raises(C.CensusPullError, match="no year"):
        C._loop_years([2000, 2001], never, "test")


def test_default_year_is_no_longer_a_cap():
    """DEFAULT_YEAR survives for callers that pass no year, but it must be the
    latest served vintage and it must not be what the series pullers use."""
    assert C.DEFAULT_YEAR == C.CBP_LAST_YEAR == 2023
    assert len(C.cbp_county_years()) > 1
    assert C.DEFAULT_YEAR in C.cbp_county_years()


# ===========================================================================
# CAP 8 -- census_zbp
# ===========================================================================

@pytest.mark.parametrize("year,dataset,cls,label,geo", [
    (1994, "zbp", "SIC", "SIC_TTL", "zipcode"),
    (1997, "zbp", "SIC", "SIC_TTL", "zipcode"),
    (1998, "zbp", "NAICS1997", "NAICS_TTL", "zipcode"),
    (2002, "zbp", "NAICS1997", "NAICS_TTL", "zipcode"),
    (2003, "zbp", "NAICS2002", "NAICS_TTL", "zipcode"),
    (2007, "zbp", "NAICS2002", "NAICS_TTL", "zipcode"),
    (2008, "zbp", "NAICS2007", "NAICS_TTL", "zipcode"),
    (2011, "zbp", "NAICS2007", "NAICS_TTL", "zipcode"),
    (2012, "zbp", "NAICS2012", None, "zip code"),
    (2016, "zbp", "NAICS2012", None, "zip code"),
    (2017, "zbp", "NAICS2017", None, "zip code"),
    (2018, "zbp", "NAICS2017", None, "zip code"),
    (2019, "cbp", "NAICS2017", "NAICS2017_LABEL", "zipcode"),
    (2023, "cbp", "NAICS2017", "NAICS2017_LABEL", "zipcode"),
])
def test_zbp_era_table_matches_the_live_probe(year, dataset, cls, label, geo):
    """Every boundary year, both sides, verified against a live 3-ZIP request
    on 2026-09-16. Note 2018 comes from `zbp`, not `cbp`: Census says CBP
    carries ZBP only "starting with reference year 2019"."""
    spec = Z.era(year)
    assert spec == {"dataset": dataset, "classification": cls,
                    "label": label, "geo": geo}


@pytest.mark.parametrize("year", [1993, 2024])
def test_zbp_outside_the_served_range_names_the_upstream_limit(year):
    with pytest.raises(Z.ZbpYearUnavailable) as exc:
        Z.era(year)
    assert "UPSTREAM" in exc.value.reason


def test_zbp_getvars_omits_the_label_variable_where_none_exists():
    """2012-2018 publish no label variable at all. Asking for one is a 400."""
    assert "NAICS_TTL" not in Z.getvars(2016)
    assert Z.getvars(2016) == ["ESTAB", "EMPSZES", "NAICS2012"]
    assert Z.getvars(2008) == ["ESTAB", "EMPSZES", "NAICS2007", "NAICS_TTL"]
    assert Z.getvars(2023) == ["ESTAB", "EMPSZES", "NAICS2017", "NAICS2017_LABEL"]


def test_zbp_spans_separate_what_is_served_from_what_we_can_land():
    assert Z.served_years() == tuple(range(1994, 2024))        # 30 years served
    assert Z.ingestable_years() == tuple(range(1998, 2024))    # 26 years landed
    assert Z.DEFAULT_YEAR == Z.ZBP_LAST_YEAR == 2023


@pytest.mark.parametrize("year", [1994, 1995, 1996, 1997])
def test_zbp_sic_years_are_refused_with_our_reason_named_as_ours(year):
    with pytest.raises(Z.ZbpYearUnavailable) as exc:
        Z._require_ingestable(year)
    assert "SIC" in exc.value.reason and "D42" in exc.value.reason


def test_the_2017_band_code_break_is_folded_deliberately_and_not_dropped():
    """1994-2016 publish band 212 ("1 to 4 employees"); 2017+ publish 210
    ("less than 5"). Both land under one label so the series joins -- and the
    raw codes stay in BAND_ERAS so the definition break stays greppable."""
    assert Z._band_label("212") == Z._band_label("210") == Z._LABEL_1_4
    assert Z.BAND_ERAS["1994-2016"]["smallest_band_code"] == "212"
    assert Z.BAND_ERAS["2017-2023"]["smallest_band_code"] == "210"
    assert Z.BAND_ERAS["1994-2016"]["published_label"] != Z._LABEL_1_4


def test_an_unknown_band_code_raises_rather_than_dropping_the_row():
    with pytest.raises(RuntimeError, match="EMPSZES"):
        Z._band_label("999")


def _rows(header, *data):
    return [dict(zip(header, row)) for row in data]


def test_finest_level_reads_the_1998_era_shape():
    """NAICS1997 + NAICS_TTL + `zipcode`, and codes right-padded with spaces.
    The all-industries total comes back as '00    ' -- six characters, and not
    an industry. A bare `len == 6` filter would land it as a NAICS code."""
    rows = _rows(
        ["ESTAB", "EMPSZES", "NAICS1997", "NAICS_TTL", "zipcode"],
        ["31", "001", "00    ", "Total", "11206"],
        ["18", "001", "445110", "Grocery stores", "11206"],
        ["7", "212", "445110", "Grocery stores", "11206"],
        ["4", "001", "4451  ", "Grocery stores rollup", "11206"],
    )
    df = Z._finest_level(rows, 1998)
    assert list(df.columns) == ["zipcode", "naics", "naics_label",
                                "emp_size_band", "estab"]
    assert set(df["naics"]) == {"445110"}
    assert set(df["emp_size_band"]) == {"All establishments", Z._LABEL_1_4}


def test_finest_level_reads_the_2012_era_shape_with_no_label_column():
    rows = _rows(
        ["ESTAB", "EMPSZES", "NAICS2012", "zip code"],
        ["18", "001", "445110", "11206"],
        ["7", "212", "445110", "11206"],
    )
    df = Z._finest_level(rows, 2012)
    assert df["naics_label"].isna().all()
    assert df["emp_size_band"].tolist() == ["All establishments", Z._LABEL_1_4]
    assert df["estab"].tolist() == [18, 7]


def test_finest_level_refuses_a_header_only_response():
    with pytest.raises(RuntimeError, match="refusing to land zero rows"):
        Z._finest_level([], 2023)


def test_categories_absent_names_the_renumbering_instead_of_writing_a_zero():
    """The three eating-and-drinking codes arrive in NAICS 2012. For 1998-2011
    the rollup has no restaurant row from this source, and the ingest has to
    SAY so -- an absent row and a zero row read identically downstream."""
    from loci.zbp import naics_to_category

    flat = naics_to_category()
    restaurant = {c for c, cat in flat.items() if cat == "restaurant"}
    kept = sorted(set(flat) - restaurant)
    df = pd.DataFrame({"naics": kept})

    absent = Z.categories_absent(df)
    assert "restaurant" in absent
    assert sorted(absent["restaurant"]) == sorted(restaurant)
    assert "grocery" not in absent


def test_categories_absent_does_not_flag_a_category_that_merely_lost_one_code():
    """laundry has two codes. One missing makes it thinner, not missing."""
    from loci.zbp import naics_to_category

    flat = naics_to_category()
    laundry = sorted(c for c, cat in flat.items() if cat == "laundry")
    assert len(laundry) > 1
    df = pd.DataFrame({"naics": [c for c in flat if c != laundry[0]]})
    assert "laundry" not in Z.categories_absent(df)


def test_build_all_years_records_skipped_years_rather_than_omitting_them(monkeypatch):
    seen = []

    def fake_build(con, year, *, dry_run=False):
        seen.append(year)
        return {"classification": Z.era(year)["classification"],
                "rows_finest_level": 10, "n_naics_codes": 2,
                "empszes_codes": ["001"], "categories_absent": {},
                "rows_written": 10}

    monkeypatch.setattr(Z, "build_zip_establishments", fake_build)
    report = Z.build_all_years(None, [1996, 1997, 1998, 1999], dry_run=True)

    assert seen == [1998, 1999]
    assert report["years_written"] == [1998, 1999]
    assert [s["year"] for s in report["skipped"]] == [1996, 1997]
    assert all("SIC" in s["reason"] for s in report["skipped"])


def test_build_all_years_refuses_to_report_success_on_an_all_sic_request():
    with pytest.raises(RuntimeError, match="Refusing to report success"):
        Z.build_all_years(None, [1994, 1995], dry_run=True)


def test_build_all_years_lets_a_real_failure_through(monkeypatch):
    """A transport failure must NOT be downgraded to a skipped year."""
    def boom(con, year, *, dry_run=False):
        raise RuntimeError("Census CBP API request failed after 3 attempts")

    monkeypatch.setattr(Z, "build_zip_establishments", boom)
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        Z.build_all_years(None, [2022, 2023], dry_run=True)


# ===========================================================================
# CAP 9 -- LODES8 WAC
# ===========================================================================

def test_lodes_publishes_every_year_2002_2023_not_three_vintages():
    assert L.VINTAGES == tuple(range(2002, 2024))
    assert len(L.VINTAGES) == 22


def test_lodes_filename_matches_what_the_readers_already_expect():
    """model/panel.py and model/address_character.py build this name
    themselves. If the fetcher and the readers disagree the files land where
    nothing looks for them."""
    assert L.wac_filename(2013) == "ny_wac_S000_JT00_2013.csv.gz"
    assert L.xwalk_filename() == "ny_xwalk.csv.gz"
    assert L.wac_url(2013).endswith("/LODES8/ny/wac/ny_wac_S000_JT00_2013.csv.gz")


@pytest.mark.parametrize("year", [2002, 2010, 2019])
def test_pre_2020_vintages_are_labelled_a_bias_not_noise(year):
    """CONTEXT.md 7.4b. The note travels with every downloaded file, because a
    caveat that lives only in a docstring is a caveat nobody reads next to the
    number."""
    note = L.block_vintage_note(year)
    assert "BIAS" in note and "ALLOCATED" in note and "not noise" in note


@pytest.mark.parametrize("year", [2020, 2021, 2023])
def test_2020_and_later_are_labelled_observed(year):
    assert L.block_vintage_note(year) == "2020 census blocks, OBSERVED"


def test_lodes_rejects_a_vintage_the_publisher_does_not_have():
    with pytest.raises(L.LodesFetchError, match="UPSTREAM"):
        L.vintages([2001, 2002])
    with pytest.raises(L.LodesFetchError, match="UPSTREAM"):
        L.vintages([2024])


def test_download_fetches_every_vintage_and_records_the_bias_per_file(tmp_path,
                                                                     monkeypatch):
    monkeypatch.setattr(L, "MANIFEST", tmp_path / "manifest.json")
    calls = []

    def fake_fetch(url, timeout=300):
        calls.append(url)
        return b"gzipped-bytes-for-" + url.rsplit("/", 1)[-1].encode()

    report = L.download(L.VINTAGES, lodes_dir=tmp_path, fetch=fake_fetch)

    assert report["years_on_disk"] == list(range(2002, 2024))
    assert len(calls) == 23                       # 22 vintages + the crosswalk
    for y in L.VINTAGES:
        assert (tmp_path / L.wac_filename(y)).exists()
    assert (tmp_path / L.xwalk_filename()).exists()

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert len(manifest) == 23
    assert all("sha256" in r and "blocks" in r for r in manifest.values())
    assert "BIAS" in manifest[L.wac_filename(2010)]["blocks"]
    assert manifest[L.wac_filename(2022)]["blocks"] == "2020 census blocks, OBSERVED"
    assert "BIAS" in report["block_geography"]


def test_download_skips_what_is_on_disk_and_says_so(tmp_path, monkeypatch):
    """"22 files present" and "22 files fetched" must not look alike."""
    monkeypatch.setattr(L, "MANIFEST", tmp_path / "manifest.json")
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / L.wac_filename(2002)).write_bytes(b"already here")
    (tmp_path / L.xwalk_filename()).write_bytes(b"already here")

    report = L.download([2002, 2003], lodes_dir=tmp_path,
                        fetch=lambda url, timeout=300: b"new-bytes")

    assert [s.get("year") for s in report["skipped"]] == [None, 2002]
    assert [r.get("year") for r in report["fetched"]] == [2003]
    assert report["years_on_disk"] == [2002, 2003]


def test_an_empty_body_raises_rather_than_landing_a_zero_byte_vintage(tmp_path,
                                                                     monkeypatch):
    """A zero-byte gzip makes every job count in that vintage read as zero."""
    monkeypatch.setattr(L, "MANIFEST", tmp_path / "manifest.json")
    with pytest.raises(L.LodesFetchError, match="refusing"):
        L.download([2002], lodes_dir=tmp_path, fetch=lambda url, timeout=300: b"")


def test_plan_is_offline_and_carries_the_caveat_on_every_row(tmp_path):
    rows = L.plan(lodes_dir=tmp_path)
    assert len(rows) == 23
    assert all(r["blocks"] for r in rows)
    assert not any(r["on_disk"] for r in rows)
    wac = [r for r in rows if r["kind"] == "wac"]
    assert [r["year"] for r in wac] == list(range(2002, 2024))


def test_registry_temporal_matches_the_code_for_all_three_sources():
    """The machine-check CLAUDE.md asks for: a human-readable range in
    registry.yaml that drifts from the adapter is exactly the failure the
    generated-docs rule exists to prevent."""
    from loci import registry

    by_id = {s["id"]: s for s in registry.load()["sources"]}

    cbp = by_id["census_cbp"]["temporal"]
    assert (cbp["start"], cbp["end"]) == (C.CBP_FIRST_YEAR, C.CBP_LAST_YEAR)

    zbp = by_id["census_zbp"]["temporal"]
    assert (zbp["start"], zbp["end"]) == (Z.ZBP_FIRST_YEAR, Z.ZBP_LAST_YEAR)

    lodes = by_id["lodes_wac"]["temporal"]
    assert (lodes["start"], lodes["end"]) == (L.FIRST_VINTAGE, L.LAST_VINTAGE)
    assert lodes["grain"] == "annual", (
        "registry.yaml called LODES a 'vintage' source because three files had "
        "been downloaded by hand; it is an annual series")
