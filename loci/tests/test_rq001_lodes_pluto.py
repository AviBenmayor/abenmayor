"""Offline tests for the RQ-001 LODES-WAC-ZCTA and PLUTO-vintage adapters
(src/loci/sources/universal/lodes_wac_zcta.py,
src/loci/sources/universal/pluto_vintages.py). No network access: LODES
inputs are tiny synthetic .csv.gz fixtures written to a tmp_path standing in
for data/raw/lodes/; PLUTO inputs are synthetic in-memory zips, and network
fetches are replaced with an injected `fetch` callable, mirroring the
fetch-injection pattern in tests exercising lodes_wac/census_zbp/macro.
"""
from __future__ import annotations

import gzip
import io
import pathlib
import zipfile

import duckdb
import pandas as pd
import pytest

from loci.sources.universal import lodes_wac_zcta as lwz
from loci.sources.universal import pluto_vintages as pv


# =========================================================================
# lodes_wac_zcta
# =========================================================================

XWALK_HEADER = "tabblk2020,st,cty,zcta\n"


def _write_gz(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        f.write(text)


def _make_lodes_dir(tmp_path, *, blank_zcta_row=False, drop_year=None,
                     years=(2002, 2023)):
    lodes_dir = tmp_path / "lodes"
    # Two NYC blocks (New York + Kings county) and one non-NYC block
    # (Albany, 36001) that must be filtered OUT by the county list.
    xwalk_rows = [
        "360610001001001,36,36061,10001",
        "360470001001001,36,36047,11201",
        "360010001001001,36,36001,12345",  # non-NYC county -- must be excluded
    ]
    if blank_zcta_row:
        xwalk_rows.append("360610002001001,36,36061,")
    _write_gz(lodes_dir / lwz.xwalk_filename(), XWALK_HEADER + "\n".join(xwalk_rows) + "\n")

    wac_header = "w_geocode,C000,CNS07,CNS18\n"
    for y in years:
        if y == drop_year:
            continue
        rows = [
            f"360610001001001,{10 + y % 100},{2},{1}",
            f"360470001001001,{20 + y % 100},{3},{4}",
        ]
        if blank_zcta_row:
            rows.append(f"360610002001001,{5},{0},{0}")
        _write_gz(lodes_dir / lwz.wac_filename(y), wac_header + "\n".join(rows) + "\n")
    return lodes_dir


def test_zcta_rollup_filters_counties_and_sums_correctly(tmp_path):
    lodes_dir = _make_lodes_dir(tmp_path, years=(2002,))
    df = lwz.build_zcta_year_panel(years=[2002], lodes_dir=lodes_dir)

    assert set(df["zcta"]) == {"10001", "11201"}  # 12345 (Albany) excluded
    row = df.set_index("zcta").loc["10001"]
    assert row["c000"] == 12  # 10 + 2002 % 100 = 10 + 2
    assert row["cns07"] == 2
    assert row["cns18"] == 1
    assert row["year"] == 2002


def test_zcta_rollup_raises_on_missing_year_file(tmp_path):
    lodes_dir = _make_lodes_dir(tmp_path, years=(2002, 2023), drop_year=2023)
    with pytest.raises(lwz.LodesZctaRollupError, match="missing"):
        lwz.build_zcta_year_panel(years=[2002, 2023], lodes_dir=lodes_dir)


def test_zcta_rollup_raises_on_blank_zcta_in_nyc_county(tmp_path):
    lodes_dir = _make_lodes_dir(tmp_path, years=(2002,), blank_zcta_row=True)
    with pytest.raises(lwz.LodesZctaRollupError, match="no ZCTA"):
        lwz.build_zcta_year_panel(years=[2002], lodes_dir=lodes_dir)


def test_zcta_rollup_carries_block_vintage_note_across_2020_boundary(tmp_path):
    lodes_dir = _make_lodes_dir(tmp_path, years=(2019, 2020))
    df = lwz.build_zcta_year_panel(years=[2019, 2020], lodes_dir=lodes_dir)
    note_2019 = df.loc[df["year"] == 2019, "block_geography"].iloc[0]
    note_2020 = df.loc[df["year"] == 2020, "block_geography"].iloc[0]
    assert "AREA-RETRO-ALLOCATED" in note_2019
    assert "OBSERVED" in note_2020
    assert note_2019 != note_2020


def test_zcta_rollup_no_upstream_vintage_gap_is_asserted():
    """The module docstring claims every WAC year joins against the SAME
    2020-block xwalk (one file, tabblk2020 only, no tabblk2010/2000 column).
    Pin that claim against the real crosswalk shipped in the repo, if
    present -- this is the 'verify, don't assume' check the task asked for.
    Skips cleanly if the real file has not been fetched in this environment.
    """
    xwalk_path = lwz.LODES_DIR / lwz.xwalk_filename()
    if not xwalk_path.exists():
        pytest.skip("data/raw/lodes/ny_xwalk.csv.gz not present in this environment")
    con = duckdb.connect(":memory:")
    cols = [c[0] for c in con.execute(
        f"SELECT * FROM read_csv_auto('{xwalk_path}', ALL_VARCHAR=TRUE) LIMIT 0"
    ).description]
    assert "tabblk2020" in cols
    assert "tabblk2010" not in cols
    assert "tabblk2000" not in cols


# =========================================================================
# pluto_vintages
# =========================================================================

def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


OLD_ERA_CSV = (
    b'"Borough","ZipCode","LotArea","BldgArea","ComArea","RetailArea",'
    b'"AssessTot","UnitsRes","BBL"\n'
    b'"MN",10001,1000,2000,500,100,300000,3,1000010001\n'
    b'"MN",10001,2000,3000,0,0,400000,5,1000010002\n'
    b'"MN",,500,500,0,0,10000,0,1000010003\n'  # blank ZipCode -> dropped
)

NEW_ERA_CSV = (
    b"borough,zipcode,lotarea,bldgarea,comarea,retailarea,assesstot,unitsres,bbl\n"
    b"MN,10001,1000,2000,500,100,300000,3,1000010001\n"
    b"MN,10001,2000,3000,0,0,400000,5,1000010002\n"
    b"MN,0,500,500,0,0,10000,0,1000010003\n"  # zero ZipCode -> dropped
)


def test_extract_data_files_handles_per_borough_zip(tmp_path):
    blob = _zip_bytes({
        "MN09v2.txt": OLD_ERA_CSV,
        "BK09v2.txt": OLD_ERA_CSV,
        "PlutoDD09v2.pdf": b"%PDF-not-real",
    })
    zpath = tmp_path / "nyc_pluto_09v2.zip"
    zpath.write_bytes(blob)
    workdir = tmp_path / "work"
    workdir.mkdir()
    files = pv._extract_data_files(zpath, workdir)
    names = sorted(f.name for f in files)
    assert names == ["BK09v2.txt", "MN09v2.txt"]  # pdf excluded


def test_extract_data_files_handles_unified_csv(tmp_path):
    blob = _zip_bytes({
        "pluto_26v2.csv": NEW_ERA_CSV,
        "pluto_readme.pdf": b"%PDF-not-real",
    })
    zpath = tmp_path / "nyc_pluto_26v2_csv.zip"
    zpath.write_bytes(blob)
    workdir = tmp_path / "work"
    workdir.mkdir()
    files = pv._extract_data_files(zpath, workdir)
    assert [f.name for f in files] == ["pluto_26v2.csv"]


def test_extract_data_files_excludes_bundled_change_file(tmp_path):
    """Regression for the 2020v4 contamination found 2026-09-22: some
    vintages bundle a PLUTOChangeFile*.csv alongside the real PLUTO csv in
    the same zip. It must never be read as lot data."""
    blob = _zip_bytes({
        "pluto_20v4.csv": NEW_ERA_CSV,
        "PLUTOChangeFile20v4.csv": b"bbl,fieldname,oldvalue,newvalue\n1,ZipCode,10001,10002\n",
        "PLUTODD20v4.pdf": b"%PDF-not-real",
    })
    zpath = tmp_path / "nyc_pluto_20v4_arc_csv.zip"
    zpath.write_bytes(blob)
    workdir = tmp_path / "work"
    workdir.mkdir()
    files = pv._extract_data_files(zpath, workdir)
    assert [f.name for f in files] == ["pluto_20v4.csv"]


def test_extract_data_files_raises_if_no_data_files(tmp_path):
    blob = _zip_bytes({"readme.pdf": b"%PDF-not-real"})
    zpath = tmp_path / "empty.zip"
    zpath.write_bytes(blob)
    workdir = tmp_path / "work"
    workdir.mkdir()
    with pytest.raises(pv.PlutoVintageError, match="no PLUTO lot-data"):
        pv._extract_data_files(zpath, workdir)


@pytest.mark.parametrize("content,label", [(OLD_ERA_CSV, "pascal-case"),
                                            (NEW_ERA_CSV, "lowercase")])
def test_aggregate_vintage_is_case_insensitive_and_sums_correctly(tmp_path, content, label):
    csv_path = tmp_path / f"{label}.csv"
    csv_path.write_bytes(content)
    con = duckdb.connect(":memory:")
    agg = pv._aggregate_vintage(con, [csv_path], 2020)

    assert len(agg) == 1  # single zipcode, 10001
    row = agg.iloc[0]
    assert row["zipcode"] == 10001
    assert row["year"] == 2020
    assert row["n_lots"] == 2  # the null/zero-zip row is excluded
    assert row["bldgarea_total"] == pytest.approx(5000)
    assert row["comarea_total"] == pytest.approx(500)
    assert row["retailarea_total"] == pytest.approx(100)
    assert row["assesstot_total"] == pytest.approx(700_000)
    assert row["unitsres_total"] == pytest.approx(8)
    assert row["n_lots_with_retail"] == 1  # only the first lot has RetailArea > 0
    assert row["dropped_no_zip"] == 1


def test_aggregate_vintage_unions_multiple_borough_files(tmp_path):
    mn = tmp_path / "MN.txt"
    bk = tmp_path / "BK.txt"
    mn.write_bytes(OLD_ERA_CSV)
    bk.write_bytes(OLD_ERA_CSV)
    con = duckdb.connect(":memory:")
    agg = pv._aggregate_vintage(con, [mn, bk], 2009)
    row = agg.iloc[0]
    # Same fixture read twice (once per borough file) -> everything doubles.
    assert row["n_lots"] == 4
    assert row["bldgarea_total"] == pytest.approx(10000)
    assert row["dropped_no_zip"] == 2


def test_download_vintage_tries_templates_in_order_and_uses_cache(tmp_path):
    calls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        calls.append(url)
        if url.endswith("_arc_csv.zip") or url.endswith("nyc_pluto_09v2_csv.zip"):
            raise pv.PlutoVintageError(f"{url} -> HTTP 404")
        return b"PK\x03\x04fake-zip-bytes"

    dest = pv.download_vintage(2009, "09v2", tmp_path, fetch=fake_fetch)
    assert dest.name == "nyc_pluto_09v2.zip"  # third template, the only one that "succeeded"
    assert dest.exists()
    assert len(calls) == 3  # both 404s tried before the one that worked

    # Second call with the same version: cached, fetch not called again.
    calls.clear()
    dest2 = pv.download_vintage(2009, "09v2", tmp_path, fetch=fake_fetch)
    assert dest2 == dest
    assert calls == []


def test_download_vintage_raises_when_every_template_404s(tmp_path):
    def fake_fetch(url: str) -> bytes:
        raise pv.PlutoVintageError(f"{url} -> HTTP 404")

    with pytest.raises(pv.PlutoVintageError, match="none of"):
        pv.download_vintage(2009, "09v2", tmp_path, fetch=fake_fetch)


def test_download_vintage_raises_on_empty_body(tmp_path):
    def fake_fetch(url: str) -> bytes:
        if url.endswith("_arc_csv.zip") or "_csv.zip" in url.rsplit("/", 1)[-1] and "arc" not in url:
            raise pv.PlutoVintageError(f"{url} -> HTTP 404")
        return b""

    with pytest.raises(pv.PlutoVintageError, match="empty body"):
        pv.download_vintage(2009, "09v2", tmp_path, fetch=fake_fetch)


def test_build_zip_vintage_panel_heartbeats_past_a_failed_vintage(tmp_path, monkeypatch):
    """One vintage fails outright (simulating an upstream 404/timeout on every
    template); the run must continue to the next vintage rather than aborting
    the whole panel -- the task's explicit heartbeat requirement -- and the
    failure must be visible in the printed progress, not swallowed."""
    good_zip = tmp_path / "good.zip"
    good_zip.write_bytes(_zip_bytes({"pluto_x.csv": NEW_ERA_CSV}))

    def fake_download_vintage(year, version, pluto_dir, refresh=False, fetch=None):
        if year == 2010:
            raise pv.PlutoVintageError("simulated total failure for 2010")
        return good_zip

    monkeypatch.setattr(pv, "download_vintage", fake_download_vintage)

    messages: list[str] = []
    df = pv.build_zip_vintage_panel(
        years=[2009, 2010], pluto_dir=tmp_path,
        progress=lambda year, msg: messages.append(msg))

    assert df["year"].tolist() == [2009]  # 2010 excluded, run did not abort
    assert any("2010" in m and "FAILED" in m for m in messages)
    assert any("2009" in m and "FAILED" not in m for m in messages)


def test_build_zip_vintage_panel_raises_if_every_vintage_fails(tmp_path, monkeypatch):
    def always_fails(year, version, pluto_dir, refresh=False, fetch=None):
        raise pv.PlutoVintageError("simulated total failure")

    monkeypatch.setattr(pv, "download_vintage", always_fails)
    with pytest.raises(pv.PlutoVintageError, match="every requested vintage failed"):
        pv.build_zip_vintage_panel(years=[2009], pluto_dir=tmp_path)


def test_build_zip_vintage_panel_rejects_years_with_no_canonical_vintage(tmp_path):
    with pytest.raises(pv.PlutoVintageError, match="No canonical vintage"):
        pv.build_zip_vintage_panel(years=[2005], pluto_dir=tmp_path)


def test_vintage_by_year_covers_2009_through_present_only():
    """Pin the probe result (task asked to VERIFY '2002->present', not assume
    it): every year 2009-2026 has a canonical vintage, and 2002-2008 are
    deliberately absent -- not a bug if someone later adds them, but a
    regression if the lower bound silently creeps without a matching adapter
    change and docstring update."""
    assert pv.FIRST_VINTAGE == 2009
    assert set(pv.VINTAGE_BY_YEAR) == set(range(2009, pv.LAST_VINTAGE + 1))
    assert all(y not in pv.VINTAGE_BY_YEAR for y in range(2002, 2009))
