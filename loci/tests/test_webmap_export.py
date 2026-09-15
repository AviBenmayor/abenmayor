"""Unit tests for the webmap point-layer export (viz/webmap_export.py).

Two things are load-bearing and both are easy to get silently wrong:

  (a) the BOROUGH filter -- POIs carry no borough column, so the layer is
      labelled by an H3 res-9 join to analysis.hex. A bug there quietly leaks
      Queens/Bronx supply into a Manhattan+Brooklyn map, which would make gaps
      look closed by businesses that are nowhere near them.

  (b) the CORROBORATED flag (CHECKPOINT D47) -- derived from dedup cluster
      membership, not stored. The adversarial case is a cluster holding two
      rows from the SAME source: that is one source double-listing a place,
      NOT independent corroboration, and it must stay single-source.

  (c) RESTAURANT DETAIL -- cuisine/grade/inspection date are loaded on the
      DOHMH row but must surface on the CANONICAL point of its dedup cluster
      (usually an Overture row). Two ways this goes wrong quietly: detail that
      never crosses the cluster, and `active` collapsing "no DOHMH record"
      (-1) into "closed" (0), which would make the active-only toggle delete
      every un-matched restaurant on the map.

  (d) THE SUPPLY SET (D52) -- the layer the owner validates gaps against must
      be the layer the gaps were MEASURED against. Two failures are silent and
      both were real: reading `analysis.poi_dedup.is_canonical` directly (which
      drew 100,213 known locations beside gaps computed from 64,303), and an
      export whose `--supply-set` disagrees with what `analysis.address_gaps`
      recorded. The excluded records must still be exported and flagged --
      deleting them from the file would hide a supply decision instead of
      making it inspectable.

Runs against a scratch in-memory DuckDB built by `loci.db.connect(":memory:")`
so the real spatial/h3 extensions are exercised -- the h3 call is the part
being tested. The fixture executes the REAL sql/003 + sql/006 text rather than
restating the view, so a change to the PRINCIPLED definition reaches these
tests instead of passing them.
"""
from __future__ import annotations

import datetime as dt
import json

import h3
import pytest

from loci import db
from loci.model import poi_evidence as pe
from loci.model import poi_presence as pp
from loci.viz import webmap_export as wx

# Three real NYC points, one per borough, so the h3 -> analysis.hex join has
# something true to resolve against.
PLACES = {
    "MN": (-73.9857, 40.7484),   # Empire State Building
    "BK": (-73.9442, 40.6782),   # central Brooklyn
    "QN": (-73.7949, 40.7282),   # central Queens
}


#: SQL types for wx.PIPELINE_GAP_COLUMNS, in that order. A dict rather than a
#: list so the fixture cannot silently declare six of seven.
PIPE_TYPES = {
    "units_permitted_400m": "INTEGER",
    "units_completed_24mo_400m": "INTEGER",
    "nearest_large_project_id": "VARCHAR",
    "nearest_large_project_m": "DOUBLE",
    "nearest_large_project_units": "INTEGER",
    "nearest_large_project_stage": "VARCHAR",
    "nearest_large_project_date": "DATE",
}
assert list(PIPE_TYPES) == wx.PIPELINE_GAP_COLUMNS

#: SQL types for wx.STOREFRONT_GAP_COLUMNS, in that order. Same shape and same
#: reason as PIPE_TYPES: a fixture that declared four of five would let the
#: export's vacancy reading be skipped by `has_storefront_columns` and every
#: assertion below would pass against nulls.
SHOP_TYPES = {
    "vacant_storefronts_400m": "BIGINT",
    "storefronts_400m": "BIGINT",
    "nearest_vacant_storefront_m": "DOUBLE",
    "nearest_vacant_storefront_id": "VARCHAR",
    "nearest_vacant_lease_expired": "BOOLEAN",
}
assert list(SHOP_TYPES) == wx.STOREFRONT_GAP_COLUMNS

#: SQL types for wx.AGE_FIT_GAP_COLUMNS (D63/D69), in that order. Same shape
#: and same reason again: a fixture declaring two of three would let
#: `has_age_fit_columns` skip the whole ranking block and every assertion
#: below would pass against nulls it never had to produce.
AGE_TYPES = {
    "age_fit_lead": "REAL",
    "age_fit_lead_moe": "REAL",
    "gap_score_fit": "REAL",
}
assert list(AGE_TYPES) == wx.AGE_FIT_GAP_COLUMNS


@pytest.fixture()
def con():
    c = db.connect(":memory:")
    c.execute("CREATE SCHEMA staging; CREATE SCHEMA analysis;")
    # Column subset of the real staging.poi (sql/002_schema.sql), in the real
    # relative order. `source_record_id` and `attrs` are here because the
    # restaurant detail rides in them -- a fixture missing them would let the
    # detail query break against a green test suite. `tier` is here because
    # analysis.poi_supply selects it.
    # `observed_on` is here (real relative position, right after `geom`) only
    # because `model/poi_presence.poi_is_open` -- now reached through
    # `analysis.poi_supply_status`, D98/GTM-170 -- references `p.observed_on`
    # unconditionally in its CASE expression; DuckDB has to bind the column at
    # CREATE VIEW time even though every fixture POI below leaves it NULL.
    c.execute("""CREATE TABLE staging.poi (
        poi_id VARCHAR, source_id VARCHAR, source_record_id VARCHAR,
        category VARCHAR, tier SMALLINT, name VARCHAR, geom GEOMETRY,
        observed_on DATE, attrs JSON)""")
    c.execute("CREATE TABLE analysis.poi_dedup (poi_id VARCHAR, cluster_id BIGINT, "
              "is_canonical BOOLEAN, category VARCHAR)")
    c.execute("CREATE TABLE analysis.hex (h3_index VARCHAR, borough VARCHAR, nta_code VARCHAR)")
    cols = ", ".join(f"{cat}_ratio FLOAT, {cat}_nearest_m FLOAT" for cat in wx.ALLCATS)
    # ...and the D75 censoring flags the real view appends: the address-grain
    # `lead_censored` plus one `{cat}_censored` per category. Declared here so
    # the export's censoring reading is exercised rather than skipped by
    # `has_censoring_columns`.
    cens = ", ".join(f"{cat}_censored BOOLEAN" for cat in wx.ALLCATS)
    # supply_set/supply_hash are native columns on the real analysis.address
    # (sql/002_schema.sql) as of D58, not an ALTER 006 bolts onto address_gaps
    # -- address_gaps is a VIEW now, and ALTER TABLE against a view errors.
    # This fixture's own mini address_gaps stands in for that view, so it
    # declares them directly.
    # The seven pipeline columns model/dev_pipeline.py writes onto
    # analysis.address and the address_gaps view re-exports (sql/011). Declared
    # here so the export's pipeline reading is exercised rather than skipped by
    # `has_pipeline_columns`.
    pipe = ", ".join(f"{c} {t}" for c, t in PIPE_TYPES.items())
    # ...and the five storefront columns model/storefronts.py writes (sql/012),
    # APPENDED after the pipeline block exactly as the real view exposes them.
    shop = ", ".join(f"{c} {t}" for c, t in SHOP_TYPES.items())
    # ...and the three age-fit ranking columns model/age_fit.py writes onto
    # analysis.address (sql/002 D63 block), APPENDED after the storefront block
    # exactly as the real view exposes them.
    age = ", ".join(f"{c} {t}" for c, t in AGE_TYPES.items())
    c.execute(f"""CREATE TABLE analysis.address_gaps (
        address_id VARCHAR, lon DOUBLE, lat DOUBLE, borough VARCHAR,
        units_capped FLOAT, nta_code VARCHAR, neighborhood VARCHAR,
        eligible BOOLEAN, gap_score FLOAT, lead_category VARCHAR,
        supply_set VARCHAR, supply_hash VARCHAR, lead_censored BOOLEAN,
        {pipe}, {shop}, {age}, {cols}, {cens})""")
    # The per-category table the LEAD category's `age_fit_source` is joined
    # from. Column subset of the real analysis.address_category (sql/002) in
    # the real relative order -- `age_fit_source` is per CATEGORY, so it cannot
    # be read off the address_gaps view.
    c.execute("CREATE TABLE analysis.address_category (address_id VARCHAR, "
              "borough VARCHAR, category VARCHAR, age_fit REAL, "
              "age_fit_moe REAL, age_fit_source VARCHAR)")
    # analysis.address carries the two run stamps the overlays count from;
    # analysis.dev_pipeline and analysis.storefront are the overlays' own
    # tables.
    c.execute("CREATE TABLE analysis.address (address_id VARCHAR, "
              "pipeline_asof DATE, storefront_asof DATE)")
    c.execute("""CREATE TABLE analysis.dev_pipeline (
        job_number VARCHAR, bbl VARCHAR, geom GEOMETRY, borough VARCHAR,
        nta_code VARCHAR, neighborhood VARCHAR, job_type VARCHAR,
        net_units INTEGER, stage VARCHAR, date_filed DATE, date_permitted DATE,
        date_complete DATE, co_type VARCHAR, source VARCHAR,
        source_vintage VARCHAR, provenance VARCHAR)""")
    # Column subset of the real analysis.storefront (sql/012), in the real
    # relative order. `universe` and `observed_1231` are the two the snapshot
    # pick turns on: five of DOF's eleven filings are vacant-only, and pooling
    # one with the annual filing double-counts every premises that filed both.
    c.execute("""CREATE TABLE analysis.storefront (
        storefront_id VARCHAR, premises_id VARCHAR, filing_due_date DATE,
        reporting_year INTEGER, universe VARCHAR, observed_1231 DATE,
        borough VARCHAR, address VARCHAR, geom GEOMETRY, vacant_1231 BOOLEAN,
        construction_reported BOOLEAN, primary_business_activity VARCHAR,
        lease_expiry DATE, source VARCHAR, source_vintage VARCHAR,
        provenance VARCHAR)""")
    # The REAL supply-set definitions, not a restatement of them: 006 also
    # creates analysis.category_anchor, which is where the corroboration
    # check reads from.
    for name in ("003_supply_sets.sql", "006_principled_supply.sql",
                 "013_floor_anchor.sql"):
        c.execute((db.SQL_DIR / name).read_text())
    # analysis.poi_supply_status (D98/GTM-170 closure gate, sql/029/033) reads
    # analysis.poi_first_seen for the ledger closure date -- a STUB here, not
    # the real view, because this fixture never exercises the snapshot ledger
    # itself, only the closure-EVIDENCE channel `_poi_sql`/`_nta_poi_sql` now
    # read. 033 (poi_closure_evidence + spend_ledger) applies next, then
    # colocation_view_sql(evidence=True) builds the gated view on top, exactly
    # as `db.init_schema` does for a real warehouse (see db.py's own comment
    # on the 021_address_character-style re-render).
    c.execute("CREATE TABLE analysis.poi_first_seen "
              "(poi_id_latest VARCHAR, closed_on DATE, closed_src VARCHAR)")
    c.execute((db.SQL_DIR / "033_poi_closure_evidence.sql").read_text())
    c.execute(pp.colocation_view_sql(evidence=True))
    for code, (lon, lat) in PLACES.items():
        c.execute("INSERT INTO analysis.hex VALUES (?, ?, ?)",
                  [h3.latlng_to_cell(lat, lon, wx.H3_RES), wx.BOROUGH_NAMES[code], code + "0001"])
    return c


def _add_poi(con, poi_id, source, cluster, boro, canonical=True, cat="laundry",
             name="Suds", record_id=None, attrs=None):
    lon, lat = PLACES[boro]
    con.execute("INSERT INTO staging.poi VALUES (?, ?, ?, ?, ?, ?, ST_Point(?, ?), ?, ?)",
                [poi_id, source, record_id, cat, 1, name, lon, lat, None,
                 None if attrs is None else json.dumps(attrs)])
    con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                [poi_id, cluster, canonical, cat])


def _anchor(con, cat, qualifies=True):
    """Mark a category as having a registry anchor dense enough to veto an
    uncorroborated aggregator record -- what score/supply.build_category_anchor
    measures. Only an ANCHORED category can exclude anything: for an unanchored
    one PRINCIPLED is ALL by construction (sql/006)."""
    con.execute(
        "INSERT INTO analysis.category_anchor (category, anchor_sources, anchor_poi, "
        "zbp_estab, n_zips, anchor_coverage, threshold, qualifies, anchor_is_floor, "
        "year, boroughs, run_at) VALUES "
        "(?, 'nyc_dohmh_restaurants', 100, 100, 5, 1.0, 0.7, ?, FALSE, 2023, "
        "'Manhattan,Brooklyn', now())", [cat, qualifies])


def _set_provenance(con, supply_set="principled", supply_hash="deadbeef1234"):
    """Stamp every address_gaps row with the supply set the gaps were measured
    against, the way model/address_gaps.py does."""
    con.execute("UPDATE analysis.address_gaps SET supply_set = ?, supply_hash = ?",
                [supply_set, supply_hash])


def _flags(bundle, cat):
    """{poi_id: in_set} -- the fifth slot of the stride-5 point array."""
    layer = bundle["pois"][cat]
    st = layer["stride"]
    return {pid: layer["pts"][i * st + 4] for i, pid in enumerate(layer["ids"])}


def _add_dohmh(con, poi_id, cluster, boro, canonical=False, cat="restaurant",
               name="Suds", camis="40001", cuisine="Thai", grade="A",
               grade_date="2025-06-01", inspected="2025-06-01", active="true",
               basis="inspected_90d_ago"):
    """A DOHMH row shaped like the real loader's output -- the detail the
    exporter reads lives entirely in `attrs`, keyed exactly as sources/cities/
    nyc/dohmh.py writes it."""
    _add_poi(con, poi_id, wx.DOHMH_SOURCE, cluster, boro, canonical=canonical,
             cat=cat, name=name, record_id=camis,
             attrs={"cuisine": cuisine, "grade": grade, "grade_date": grade_date,
                    "last_inspection_date": inspected, "active": active,
                    "active_basis": basis})


def _add_job(con, job, boro, net_units=100, stage="permitted", co_type=None,
             date_permitted="2025-03-01", date_complete=None, date_filed="2023-01-01",
             job_type="New Building", nbhd=None, vintage="25Q4"):
    """One analysis.dev_pipeline row, shaped like the real loader's output."""
    lon, lat = PLACES[boro]
    con.execute(
        "INSERT INTO analysis.dev_pipeline VALUES "
        "(?, ?, ST_Point(?, ?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [job, "1000" + job, lon, lat, boro, boro + "0001",
         nbhd or ("Somewhere in " + boro), job_type, net_units, stage,
         date_filed, date_permitted, date_complete, co_type,
         "nyc_dcp_housing_db", vintage, "br6q-ssj3@" + vintage])


def _set_asof(con, asof="2026-09-09", sf_asof=None):
    """The run stamps `loci pipeline` and `loci storefronts` leave on
    analysis.address. `sf_asof=None` is the state of a database whose
    `loci storefronts` has never run -- the export then falls back to the
    newest FULL-universe observation in the registry, which is the path
    test_storefront_asof_falls_back_to_the_registry exercises."""
    con.execute("DELETE FROM analysis.address")
    con.execute("INSERT INTO analysis.address VALUES ('a', CAST(? AS DATE), CAST(? AS DATE))",
                [asof, sf_asof])


#: DOF's filing calendar, as sql/012 documents it: the 2025-06-03 annual filing
#: and the 2025-02-15 vacant-only supplement BOTH observe 2024-12-31.
SNAP_FILING, SNAP_OBSERVED = "2025-06-03", "2024-12-31"
SUPPLEMENT = "2025-02-15"


def _add_storefront(con, premises, boro, seq=1, filing=SNAP_FILING,
                    universe="full", observed=SNAP_OBSERVED, vacant=True,
                    address=None, business="NO BUSINESS ACTIVITY IDENTIFIED",
                    lease=None, construction=None, geom=True,
                    vintage="2026-04-09"):
    """One analysis.storefront row, shaped like the real loader's output.

    `premises` is the stable key (BBL||unit); `storefront_id` is premises#seq
    and is NOT stable across filings, which is why every longitudinal question
    here is asked at premises level."""
    lon, lat = PLACES[boro]
    con.execute(
        "INSERT INTO analysis.storefront VALUES "
        "(?, ?, CAST(? AS DATE), ?, ?, CAST(? AS DATE), ?, ?, "
        + ("ST_Point(?, ?)" if geom else "NULL") +
        ", ?, ?, ?, CAST(? AS DATE), ?, ?, ?)",
        [f"{premises}#{seq}", premises, filing, int(observed[:4]), universe,
         observed, boro, address or f"{premises} MAIN ST"]
        + ([lon, lat] if geom else [])
        + [vacant, construction, business, lease,
           "nyc_dof_storefront_registry", vintage, f"92iy-9c3n@{vintage}"])


def _add_gap(con, address_id, boro, cat="laundry", ratio=2.0, eligible=True,
             extra=(), units=10.0, score=1.5, pipe=None, shop=None,
             age=None, age_source=None, lead=None, censored=(),
             lead_censored=False):
    """One address row. `cat` (plus anything in `extra`) is beyond reach at
    `ratio`; every other category sits at 0.5, comfortably inside it.

    `extra` exists for the all-opportunities layers, which are about the
    address's whole missing LIST rather than one category at a time.
    """
    # Columns are named, not positional: sql/006 ALTERs supply_set/supply_hash
    # onto this table, and a positional INSERT would break every time a
    # migration adds a column.
    missing = {cat, *extra}
    ratios = {c: (ratio if c in missing else 0.5) for c in wx.ALLCATS}
    lon, lat = PLACES[boro]
    cols = ["address_id", "lon", "lat", "borough", "units_capped", "nta_code",
            "neighborhood", "eligible", "gap_score", "lead_category",
            "lead_censored"]
    vals = [address_id, lon, lat, boro, units, boro + "0001",
            "Somewhere in " + boro, eligible, score, lead or cat, lead_censored]
    # `pipe` is the seven PIPELINE_GAP_COLUMNS as a dict; anything not named
    # stays NULL, which is the state of a database whose `loci pipeline` has
    # not run for that address.
    pipe = dict(pipe or {})
    cols += list(PIPE_TYPES)
    vals += [pipe.get(c) for c in PIPE_TYPES]
    # `shop` is the five STOREFRONT_GAP_COLUMNS as a dict; anything not named
    # stays NULL, the state of a database whose `loci storefronts` has not run.
    shop = dict(shop or {})
    cols += list(SHOP_TYPES)
    vals += [shop.get(c) for c in SHOP_TYPES]
    # `age` is the three AGE_FIT_GAP_COLUMNS as a dict; anything not named
    # stays NULL, the state of a category with no live curve. NULL is the
    # DEFAULT here on purpose -- eleven of the fifteen categories are in it.
    age = dict(age or {})
    cols += list(AGE_TYPES)
    vals += [age.get(c) for c in AGE_TYPES]
    # `censored` names the categories whose nearest_m sits AT the 2,400 m
    # Dijkstra cap (D75) -- their distance is a floor, not a measurement.
    censored = set(censored)
    for c in wx.ALLCATS:
        cols += [f"{c}_ratio", f"{c}_nearest_m", f"{c}_censored"]
        vals += [ratios[c], wx.GAP_CAP_M if c in censored else 100.0, c in censored]
    con.execute(f"INSERT INTO analysis.address_gaps ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(vals))})", vals)
    # The per-category row the lead category's age_fit_source is joined from.
    # Written only when asked: an address with no address_category row is the
    # normal state for a category that was never fitted.
    if age_source is not None:
        con.execute("INSERT INTO analysis.address_category "
                    "(address_id, borough, category, age_fit_source) VALUES (?, ?, ?, ?)",
                    [address_id, boro, lead or cat, age_source])


def test_borough_filter_excludes_other_boroughs(con):
    """A Queens laundromat and a Queens gap address must not reach an MN+BK
    export -- for the POI layer that is an h3 -> analysis.hex join, for the gap
    layer a plain borough-code predicate."""
    _add_poi(con, "a", "overture_places", 1, "MN")
    _add_poi(con, "b", "overture_places", 2, "BK")
    _add_poi(con, "c", "overture_places", 3, "QN")
    _add_gap(con, "addr_mn", "MN")
    _add_gap(con, "addr_qn", "QN")

    bundle = wx.collect(con, ["MN", "BK"])
    counts = wx.summarize(bundle)

    assert bundle["pois"]["laundry"]["ids"] == ["a", "b"]
    assert counts["poi"]["laundry"] == {"MN": {"all": 1, "corroborated": 0, "single": 1},
                                        "BK": {"all": 1, "corroborated": 0, "single": 1}}
    assert bundle["gaps"]["laundry"]["ids"] == ["addr_mn"]
    assert counts["gap"]["laundry"] == {"MN": 1, "BK": 0}

    # Widening the filter is the same code path, and must pick Queens back up.
    wide = wx.collect(con, ["MN", "BK", "QN"])
    assert wide["pois"]["laundry"]["ids"] == ["a", "b", "c"]
    assert wide["gaps"]["laundry"]["ids"] == ["addr_mn", "addr_qn"]


def test_corroborated_needs_two_distinct_sources(con):
    """D47: 2+ DISTINCT sources in the dedup cluster is corroboration. Two rows
    from the SAME source is not -- that is one source listing a place twice."""
    # cluster 1: canonical row + a second row from a DIFFERENT source -> corroborated
    _add_poi(con, "c1_overture", "overture_places", 1, "MN")
    _add_poi(con, "c1_osm", "osm_overpass", 1, "MN", canonical=False)
    # cluster 2: canonical row alone -> single-source
    _add_poi(con, "c2_overture", "overture_places", 2, "MN")
    # cluster 3: two rows, SAME source -> still single-source (the adversarial case)
    _add_poi(con, "c3_a", "overture_places", 3, "MN")
    _add_poi(con, "c3_b", "overture_places", 3, "MN", canonical=False)

    bundle = wx.collect(con, ["MN"])
    layer = bundle["pois"]["laundry"]
    # Only canonical rows are exported, one per cluster.
    assert layer["ids"] == ["c1_overture", "c2_overture", "c3_a"]

    masks = [layer["pts"][i + 3] for i in range(0, len(layer["pts"]), layer["stride"])]
    popcount = [bin(m).count("1") for m in masks]
    assert popcount == [2, 1, 1]

    counts = wx.summarize(bundle)["poi"]["laundry"]["MN"]
    assert counts == {"all": 3, "corroborated": 1, "single": 2}


def test_closure_evidence_excludes_a_poi_from_the_export(con):
    """AC-12 (D98, GTM-170): a canonical POI whose newest closure-evidence
    verdict is 'closed' must not reach the exported POI layer -- `_poi_sql`
    and `_nta_poi_sql` now read `analysis.poi_supply_status`
    (score.supply.SUPPLY_VIEW) and exclude `poi_status = 'closed'`, never
    require `= 'open'` (poi_status is TRI-STATE). A same-borough,
    same-category sibling with NO evidence row (poi_status stays 'unknown')
    must still be exported -- this proves the filter discriminates rather
    than emptying the layer."""
    _add_poi(con, "still_open", "overture_places", 1, "MN")
    _add_poi(con, "closed_shop", "overture_places", 2, "MN")
    pe.insert_evidence(con, pe.EvidenceRow(
        poi_id="closed_shop", verdict="closed", source="web",
        source_name="Eater NY", url="https://ny.eater.com/closed-shop",
        evidence_date=dt.date(2026, 9, 1), dated_by="published",
        retrieved_at=dt.datetime(2026, 9, 1, 12, 0), query="test query",
        domain_class="news", run_id="test-run"))

    bundle = wx.collect(con, ["MN"])
    assert bundle["pois"]["laundry"]["ids"] == ["still_open"]
    assert "closed_shop" not in bundle["pois"]["laundry"]["ids"]

    nta = wx.collect_nta(con, ["MN"], "principled", None, {}, {}, {})
    for layer in nta.values():
        assert "closed_shop" not in layer.get("ids", [])


def test_gap_layer_uses_ratio_and_ignores_the_retired_gate(con):
    """A gap point is ANY address whose category ratio exceeds 1 --
    model/address_gaps.py's own n_missing definition. The eligibility gate is
    retired (D75, owner ruling), so a row carrying the retired flag as FALSE
    is exported like any other: only `ratio > 1` decides. The only thing that
    keeps an address out is reaching the category."""
    _add_gap(con, "gap", "MN", ratio=1.4)
    _add_gap(con, "reached", "MN", ratio=0.9)
    _add_gap(con, "was_ineligible", "MN", ratio=3.0, eligible=False)

    bundle = wx.collect(con, ["MN"])
    assert bundle["gaps"]["laundry"]["ids"] == ["gap", "was_ineligible"]
    # The same address is not a gap for a category it can reach.
    assert bundle["gaps"]["grocery"]["ids"] == []


def test_gap_layer_carries_the_censoring_flags(con):
    """D75: a nearest_m AT the 2,400 m Dijkstra cap is a FLOOR, not a walk, and
    the map has to be able to say so. Three states travel per point -- 1
    censored, 0 measured, null "this file cannot say" -- for the layer's own
    category and for the address's lead, plus the cap in metres so the UI never
    hard-codes 2400."""
    _add_gap(con, "measured", "MN", ratio=1.4)
    _add_gap(con, "at_the_cap", "MN", ratio=6.0, censored=("laundry",),
             lead_censored=True)

    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert layer["ids"] == ["at_the_cap", "measured"]
    cens = layer["censoring"]
    assert cens["capM"] == wx.GAP_CAP_M == 2400.0
    assert cens["cat"] == [1, 0]
    assert cens["lead"] == [1, 0]


def test_a_pre_d75_database_exports_null_censoring_rather_than_a_confident_zero(con):
    """The degrade-don't-lie contract, same as the pipeline/storefront/age-fit
    blocks: a database written before the flags landed must not export 0
    ("measured") for a distance nobody flagged. It exports null, and the UI
    says nothing."""
    _add_gap(con, "gap", "MN", ratio=1.4)
    con.execute("ALTER TABLE analysis.address_gaps DROP COLUMN lead_censored")
    for c in wx.ALLCATS:
        con.execute(f"ALTER TABLE analysis.address_gaps DROP COLUMN {c}_censored")
    assert wx.has_censoring_columns(con) is False

    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert layer["ids"] == ["gap"]
    assert layer["censoring"]["cat"] == [None]
    assert layer["censoring"]["lead"] == [None]


def test_write_emits_one_file_per_category_per_layer(con, tmp_path):
    """One gaps file and one pois file per category, plus exactly two
    non-category files: meta.json and the alcohol overlay. The overlay is
    counted here on purpose -- it is a STANDALONE layer, so if it ever became a
    16th category this count would move and the test would say so.

    The all-opportunities files are counted the same way: one per NTA THAT HAS
    A GAP ADDRESS, plus one index. An NTA file for a neighborhood with nothing
    missing is a file the picker would offer and the map could not draw."""
    _add_poi(con, "a", "overture_places", 1, "MN")
    _add_gap(con, "addr_mn", "MN")
    written = wx.write(wx.collect(con, ["MN", "BK"]), tmp_path)

    # gaps + pois, then meta.json and the six standalone overlays (the fifth
    # being the ranked cluster list, owner ruling 2026-09-13; the sixth the
    # modeled/realized/surprise mode, owner framing 2026-09-14), then one NTA +
    # its index.
    assert set(written) == (
        {f"gaps/{c}.json" for c in wx.ALLCATS}
        | {f"pois/{c}.json" for c in wx.ALLCATS}
        | {"meta.json", "alcohol.json", "pipeline.json", "storefronts.json",
           "character.json", "clusters.json", "forecast.json",
           "nta/MN0001.json", "nta/index.json"})
    import json
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["boroughs"] == ["MN", "BK"]
    assert meta["cats"] == wx.ALLCATS
    assert set(meta["colors"]) == set(wx.ALLCATS)
    assert meta["poiCounts"]["laundry"]["MN"]["all"] == 1
    # No alcohol table in this fixture -> an empty overlay that SAYS it is
    # empty, and a category list the overlay is absent from.
    assert meta["alcohol"]["available"] is False and meta["alcohol"]["n"] == 0
    assert "alcohol" not in meta["cats"]


def test_unknown_borough_fails_loud(con):
    with pytest.raises(ValueError, match="unknown borough"):
        wx.collect(con, ["ZZ"])


# ------------------------------------------------------- restaurant detail

def _detail_at(bundle, cat, poi_id):
    """The detail block is dictionary-encoded parallel arrays indexed by point;
    decode one point back into a plain dict the way index.html's look() does."""
    layer = bundle["pois"][cat]
    j = layer["ids"].index(poi_id)
    d, vocab = layer["detail"], layer["detail"]["vocab"]

    def s(key, vkey):
        i = d[key][j]
        return None if i < 0 else vocab[vkey][i]

    return {"cuisine": s("cuisine", "cuisine"), "cuisineSrc": s("cuisineSrc", "src"),
            "grade": s("grade", "grade"), "gradeDate": s("gradeDate", "date"),
            "inspected": s("inspected", "date"), "basis": s("basis", "basis"),
            "active": d["active"][j], "camis": d["camis"][j]}


def test_detail_attaches_from_the_dohmh_member_of_the_cluster(con):
    """The canonical point is usually the Overture row; the DOHMH row that dedup
    collapsed into it is the SAME restaurant, so its cuisine, grade and CAMIS
    belong to the canonical point. Detail must travel across the cluster, not
    stop at the row it was loaded on."""
    _add_poi(con, "canon", "overture_places", 1, "MN", cat="restaurant",
             name="Sri Thai", attrs={"primary_category": "thai_restaurant"})
    _add_dohmh(con, "dohmh", 1, "MN", cat="restaurant", camis="41234",
               cuisine="Thai", grade="A", grade_date="2025-06-04",
               inspected="2025-06-04", active="true", basis="inspected_90d_ago")

    bundle = wx.collect(con, ["MN"])
    layer = bundle["pois"]["restaurant"]
    assert layer["ids"] == ["canon"]          # only the canonical row is a point
    assert _detail_at(bundle, "restaurant", "canon") == {
        "cuisine": "Thai", "cuisineSrc": wx.DOHMH_SOURCE, "grade": "A",
        "gradeDate": "2025-06-04", "inspected": "2025-06-04",
        "basis": "inspected_90d_ago", "active": 1, "camis": "41234"}

    # Both sources are still counted for corroboration, and the summary counts
    # the point as DOHMH-backed and active.
    assert wx.summarize(bundle)["poi"]["restaurant"]["MN"] == {
        "all": 1, "corroborated": 1, "single": 0,
        "dohmh": 1, "active": 1, "inactive": 0, "cuisine": 1}


def test_most_recently_inspected_dohmh_member_wins(con):
    """Where dedup collapsed several DOHMH rows into one cluster the freshest
    inspection is the truth -- a 2019 grade must not outrank a 2025 one."""
    _add_poi(con, "canon", "overture_places", 1, "MN", cat="restaurant")
    _add_dohmh(con, "old", 1, "MN", camis="1", cuisine="Pizza", grade="C",
               grade_date="2019-02-01", inspected="2019-02-01")
    _add_dohmh(con, "new", 1, "MN", camis="2", cuisine="Italian", grade="A",
               grade_date="2025-07-09", inspected="2025-07-09")

    det = _detail_at(wx.collect(con, ["MN"]), "restaurant", "canon")
    assert (det["cuisine"], det["grade"], det["camis"]) == ("Italian", "A", "2")


def test_cuisine_falls_back_labelled_with_its_source(con):
    """No DOHMH member -> the taxonomy fallback fills cuisine, but it is
    ALWAYS labelled with the source it came from: an Overture
    `pizza_restaurant` is a taxonomy string, not a health-department cuisine
    code, and `active` stays -1 (unknown), never 0 (closed).

    The DOHMH row here sits on a DIFFERENT cluster on purpose: it is what makes
    restaurant a detail category at all (`detail_cats` reads that from the
    data), while leaving `canon` with no DOHMH member of its own."""
    _add_poi(con, "canon", "overture_places", 1, "MN", cat="restaurant",
             attrs={"primary_category": "pizza_restaurant"})
    _add_poi(con, "elsewhere", "overture_places", 2, "MN", cat="restaurant")
    _add_dohmh(con, "elsewhere_d", 2, "MN", camis="9")

    det = _detail_at(wx.collect(con, ["MN"]), "restaurant", "canon")
    assert det["cuisine"] == "Pizza"
    assert det["cuisineSrc"] == "overture_places"
    assert det["grade"] is None and det["camis"] == ""
    assert det["active"] == -1, "no DOHMH record is UNKNOWN, not inactive"


def test_inactive_and_unknown_are_distinct_in_the_summary(con):
    """The active-only toggle hides `active == 0` and nothing else, so the
    export must keep 0 (DOHMH says closed) apart from -1 (no DOHMH row). If
    these ever collapse, the toggle silently deletes every un-matched point."""
    _add_poi(con, "open", "overture_places", 1, "MN", cat="restaurant")
    _add_dohmh(con, "open_d", 1, "MN", camis="1", active="true")
    _add_poi(con, "shut", "overture_places", 2, "MN", cat="restaurant")
    _add_dohmh(con, "shut_d", 2, "MN", camis="2", active="false",
               basis="closed_at_last_inspection")
    _add_poi(con, "unknown", "overture_places", 3, "MN", cat="restaurant")

    bundle = wx.collect(con, ["MN"])
    actives = {i: _detail_at(bundle, "restaurant", i)["active"]
               for i in bundle["pois"]["restaurant"]["ids"]}
    assert actives == {"open": 1, "shut": 0, "unknown": -1}
    counts = wx.summarize(bundle)["poi"]["restaurant"]["MN"]
    assert (counts["all"], counts["dohmh"], counts["active"], counts["inactive"]) == (3, 2, 1, 1)


def test_detail_rides_only_on_dohmh_covered_categories(con):
    """`detail_cats` is read from the data, not hardcoded. A category DOHMH
    does not cover must stay byte-identical to a pre-detail export -- no
    `detail` key at all, so the other thirteen files do not grow."""
    _add_poi(con, "canon", "overture_places", 1, "MN", cat="restaurant")
    _add_dohmh(con, "dohmh", 1, "MN", cat="restaurant")
    _add_poi(con, "wash", "overture_places", 2, "MN", cat="laundry",
             attrs={"primary_category": "laundromat"})

    bundle = wx.collect(con, ["MN"])
    assert bundle["detailCats"] == ["restaurant"]
    assert "detail" in bundle["pois"]["restaurant"]
    assert "detail" not in bundle["pois"]["laundry"]


def test_detail_never_reaches_the_gap_layer(con):
    """The cuisine and active-only filters are KNOWN-LOCATION filters. The gap
    layer is model output (analysis.address_gaps) and must be untouched by
    anything DOHMH: hiding a Thai restaurant cannot open or close a gap. The
    export-side guarantee is that gap layers carry no detail and are identical
    whether or not DOHMH rows exist."""
    _add_gap(con, "addr", "MN", cat="restaurant")
    before = wx.collect(con, ["MN"])["gaps"]

    _add_poi(con, "canon", "overture_places", 1, "MN", cat="restaurant")
    _add_dohmh(con, "dohmh", 1, "MN", cat="restaurant", cuisine="Thai", active="false")
    after = wx.collect(con, ["MN"])

    assert after["gaps"] == before
    assert after["gaps"]["restaurant"]["ids"] == ["addr"]
    assert all("detail" not in layer for layer in after["gaps"].values())
    # ...while the POI layer for the same category did change.
    assert after["pois"]["restaurant"]["ids"] == ["canon"]


@pytest.mark.parametrize("value,source,expected", [
    ("Thai", wx.DOHMH_SOURCE, "Thai"),
    ("Coffee/Tea", wx.DOHMH_SOURCE, "Coffee/Tea"),          # DOHMH passes through
    ("pizza_restaurant", "overture_places", "Pizza"),
    ("Dining and Drinking > Restaurant > Indian Restaurant",
     "foursquare_os_places", "Indian"),
    ("restaurant", "overture_places", None),                # named after itself
    ("Dining and Drinking", "foursquare_os_places", None),
    (None, "overture_places", None),
])
def test_normalize_cuisine(value, source, expected):
    """A fallback taxonomy string has to read like a cuisine to share a dropdown
    with DOHMH's vocabulary -- and a bare `restaurant` carries no cuisine at
    all, so it must come back blank rather than becoming a 'Restaurant' bucket
    that swallows a fifth of the map."""
    assert wx.normalize_cuisine(value, source) == expected


# ------------------------------------------------------- supply sets (D52)

def test_principled_is_the_default_and_excludes_lone_aggregator_records(con):
    """THE BUG THIS FILE EXISTS TO PREVENT COMING BACK. The gaps in
    analysis.address_gaps are measured against the PRINCIPLED supply set, so
    the "known locations" the owner checks them against must be the same set.

    In an ANCHORED category (a registry dense enough to veto — sql/006), a lone
    aggregator record is not evidence of a business. It must:
      * still be exported, flagged `in_set = 0`, so the drop is inspectable;
      * NOT appear in poiCounts, which is what the sidebar calls "known
        locations" and what has to match the gap layer.
    A record a registry saw, and a record two aggregators both saw, stay in.
    """
    _anchor(con, "laundry")
    _add_poi(con, "ghost", "overture_places", 1, "MN")                 # lone aggregator
    _add_poi(con, "licensed", "nyc_dcwp_licenses", 2, "MN")            # a registry saw it
    _add_poi(con, "twice", "overture_places", 3, "MN")                 # two aggregators
    _add_poi(con, "twice_b", "osm_overpass", 3, "MN", canonical=False)

    bundle = wx.collect(con, ["MN"])                    # no supply_set argument
    assert bundle["supplySet"] == "principled"

    # Every canonical record is still in the file — nothing is deleted.
    assert bundle["pois"]["laundry"]["ids"] == ["ghost", "licensed", "twice"]
    assert _flags(bundle, "laundry") == {"ghost": 0, "licensed": 1, "twice": 1}
    assert bundle["pois"]["laundry"]["nSet"] == 2
    assert bundle["pois"]["laundry"]["nExcluded"] == 1

    counts = wx.summarize(bundle)
    # ...but only the in-set records are "known locations".
    assert counts["poi"]["laundry"]["MN"] == {"all": 2, "corroborated": 1, "single": 1}
    assert counts["excluded"]["laundry"]["MN"] == 1


def test_unanchored_category_keeps_everything(con):
    """PRINCIPLED = ALL for a category with no anchor loaded (sql/006 fails
    open on purpose). A forgotten `loci anchor-coverage` must degrade to
    counting everything, never to silently deleting supply — and the map must
    show the same thing the model counted."""
    _add_poi(con, "lonely", "overture_places", 1, "MN")

    bundle = wx.collect(con, ["MN"])
    assert _flags(bundle, "laundry") == {"lonely": 1}
    assert wx.summarize(bundle)["excluded"]["laundry"]["MN"] == 0


def test_supply_set_flag_selects_the_membership(con):
    """`--supply-set` picks the boolean on analysis.poi_supply, via the SAME
    score/supply.supply_predicate the address screen uses. ALL excludes
    nothing; CORROBORATED excludes every single-source record, PRINCIPLED only
    the unanchored-by-a-registry ones."""
    _anchor(con, "laundry")
    _add_poi(con, "ghost", "overture_places", 1, "MN")
    _add_poi(con, "licensed", "nyc_dcwp_licenses", 2, "MN")
    _add_poi(con, "twice", "overture_places", 3, "MN")
    _add_poi(con, "twice_b", "osm_overpass", 3, "MN", canonical=False)

    assert _flags(wx.collect(con, ["MN"], "all"), "laundry") == {
        "ghost": 1, "licensed": 1, "twice": 1}
    assert _flags(wx.collect(con, ["MN"], "principled"), "laundry") == {
        "ghost": 0, "licensed": 1, "twice": 1}
    # CORROBORATED is a SUBSET of PRINCIPLED: the licensed-but-single-source
    # record falls out too.
    assert _flags(wx.collect(con, ["MN"], "corroborated"), "laundry") == {
        "ghost": 0, "licensed": 0, "twice": 1}


def test_unknown_supply_set_fails_loud(con):
    """A typo must never quietly become 'all' and silently restore 36k
    aggregator ghosts to the map."""
    with pytest.raises(ValueError, match="unknown supply set"):
        wx.collect(con, ["MN"], "principaled")


def test_mismatch_warning_fires_when_the_flag_differs_from_provenance(con):
    """The whole failure mode: a map whose gap layer was measured against one
    supply and whose known-location layer draws another. It must be impossible
    to produce that quietly."""
    _add_poi(con, "a", "overture_places", 1, "MN")
    _add_gap(con, "addr", "MN")
    _set_provenance(con, "principled", "c4b847b82ffd")

    ok = wx.collect(con, ["MN"], "principled")
    assert ok["supplyWarning"] is None
    assert ok["supplyProvenance"]["supply_hash"] == "c4b847b82ffd"

    bad = wx.collect(con, ["MN"], "all")
    assert "SUPPLY-SET MISMATCH" in bad["supplyWarning"]
    assert "'principled'" in bad["supplyWarning"] and "'all'" in bad["supplyWarning"]


def test_missing_provenance_warns_rather_than_passing_silently(con):
    """address_gaps rows written before D52 carry a NULL supply_set. That is
    not 'fine by default' — nothing can then tell whether the two layers agree,
    and the export has to say so."""
    _add_poi(con, "a", "overture_places", 1, "MN")
    _add_gap(con, "addr", "MN")                        # provenance left NULL

    bundle = wx.collect(con, ["MN"], "principled")
    assert "NO SUPPLY PROVENANCE" in bundle["supplyWarning"]


def test_mixed_provenance_warns(con):
    """Two boroughs measured against different supply sets is a mismatch even
    when one of them matches the flag."""
    _add_gap(con, "mn", "MN")
    _add_gap(con, "bk", "BK")
    _set_provenance(con, "principled", "aaa")
    con.execute("UPDATE analysis.address_gaps SET supply_set = 'all', supply_hash = 'bbb' "
                "WHERE borough = 'BK'")

    bundle = wx.collect(con, ["MN", "BK"], "principled")
    assert "MIXED SUPPLY PROVENANCE" in bundle["supplyWarning"]
    assert bundle["supplyProvenance"]["mixed"] is True


def test_provenance_ignores_boroughs_this_map_does_not_draw(con):
    """The citywide table holds pre-D52 NULL rows for boroughs the MN+BK map
    never draws. Those must not raise a false alarm about the two it does."""
    _add_gap(con, "mn", "MN")
    _add_gap(con, "qn", "QN")
    _set_provenance(con, "principled", "aaa")
    con.execute("UPDATE analysis.address_gaps SET supply_set = NULL, supply_hash = NULL "
                "WHERE borough = 'QN'")

    assert wx.collect(con, ["MN"], "principled")["supplyWarning"] is None


def test_meta_carries_the_supply_set_and_hash(con, tmp_path):
    """meta.json is what the map itself reads, so the provenance has to reach
    it: the set drawn, the set the gaps were measured against, its hash, and
    the warning if they differ."""
    _anchor(con, "laundry")
    _add_poi(con, "ghost", "overture_places", 1, "MN")
    _add_poi(con, "twice", "overture_places", 2, "MN")
    _add_poi(con, "twice_b", "osm_overpass", 2, "MN", canonical=False)
    _add_gap(con, "addr", "MN")
    _set_provenance(con, "principled", "c4b847b82ffd")

    wx.write(wx.collect(con, ["MN"], "principled"), tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["supply"] == {"set": "principled", "sets": ["all", "corroborated", "principled"],
                              "gapsSet": "principled", "gapsHash": "c4b847b82ffd",
                              "mixed": False, "warning": None}
    assert meta["poiCounts"]["laundry"]["MN"]["all"] == 1     # known locations
    assert meta["excludedCounts"]["laundry"]["MN"] == 1       # and what was dropped

    # A mismatched export writes the warning INTO the file, so the page can say
    # it even when nobody read the terminal.
    wx.write(wx.collect(con, ["MN"], "all"), tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert "SUPPLY-SET MISMATCH" in meta["supply"]["warning"]
    assert meta["poiCounts"]["laundry"]["MN"]["all"] == 2     # ghost counted again


# ------------------------------------------------- all opportunities (by NTA)
#
# The mode answers "what is missing HERE", so the two things that can go wrong
# quietly are both about the SET of addresses in a neighborhood: an index whose
# counts do not match the table the map is drawn from (the sidebar would print
# a number the map cannot show), and a file that carries an address with
# nothing missing or an ineligible one (a "gap" the model never found).


def _nta(con, boroughs=("MN", "BK"), supply_set="principled"):
    return wx.collect_nta(con, list(boroughs), supply_set, "deadbeef1234")


def test_nta_index_counts_match_a_direct_query(con):
    """Per-category gap counts in the index must equal counting the table
    directly, for every NTA and every category. Two NTAs here because a
    single-NTA fixture would pass with a bug that ignores the grouping."""
    # MN: three addresses, two missing laundry (one of them also bar), one
    # missing only pharmacy. BK: two, both missing bar.
    _add_gap(con, "mn1", "MN", cat="laundry")
    _add_gap(con, "mn2", "MN", cat="laundry", extra=("bar",))
    _add_gap(con, "mn3", "MN", cat="pharmacy")
    _add_gap(con, "bk1", "BK", cat="bar")
    _add_gap(con, "bk2", "BK", cat="bar")
    layers = _nta(con)
    index = wx.nta_index(layers, ["MN", "BK"], "principled", "deadbeef1234")
    rows = {r["nta"]: r for r in index["ntas"]}
    assert set(rows) == {"MN0001", "BK0001"}

    for code, row in rows.items():
        boro = code[:2]
        assert row["n"] == con.execute(
            "SELECT count(*) FROM analysis.address_gaps "
            "WHERE nta_code = ?", [code]).fetchone()[0]
        for cat in wx.ALLCATS:
            direct = con.execute(
                f"SELECT count(*) FROM analysis.address_gaps "
                f"WHERE nta_code = ? AND {cat}_ratio > 1",
                [code]).fetchone()[0]
            assert row["gapCounts"][cat] == direct, (code, cat)
        assert row["boro"] == boro
    # Sorted biggest-first: the picker shows the neighborhoods worth opening.
    assert [r["nta"] for r in index["ntas"]] == ["MN0001", "BK0001"]


def test_nta_file_holds_every_address_that_misses_something(con):
    """Two ways an address must NOT reach a neighborhood file: nothing over its
    reach tier, and (the adversarial one) a NULL ratio, which is unmeasured
    rather than missing -- treating it as a gap would invent an opportunity out
    of a hole in the data. The third way used to be the eligibility gate; D75
    retired it, so a row carrying the retired flag as FALSE is kept."""
    _add_gap(con, "keep", "MN", cat="laundry", ratio=2.0)
    _add_gap(con, "was_ineligible", "MN", cat="laundry", ratio=2.0, eligible=False)
    _add_gap(con, "nothing_missing", "MN", cat="laundry", ratio=0.9)
    _add_gap(con, "unmeasured", "MN", cat="laundry", ratio=2.0)
    con.execute("UPDATE analysis.address_gaps SET laundry_ratio = NULL "
                "WHERE address_id = 'unmeasured'")
    layer = _nta(con)["MN0001"]
    assert layer["ids"] == ["keep", "was_ineligible"]
    assert layer["n"] == 2


def test_nta_missing_list_is_walkable_and_worst_first(con):
    """`miss` is one flat array with no offsets: point j consumes the next
    pts[j*6+5] pairs. If n_missing and the list ever disagree every popup after
    the first is wrong, so the walk is the test."""
    _add_gap(con, "a", "MN", cat="laundry", ratio=2.5, extra=("bar",))
    _add_gap(con, "b", "MN", cat="pharmacy", ratio=1.4)
    layer = _nta(con)["MN0001"]
    st, cur, seen = layer["stride"], 0, {}
    for j, aid in enumerate(layer["ids"]):
        n = layer["pts"][j * st + 5]
        pairs = [(wx.ALLCATS[layer["miss"][cur + 2 * k]], layer["miss"][cur + 2 * k + 1])
                 for k in range(n)]
        cur += 2 * n
        seen[aid] = pairs
        assert [r for _, r in pairs] == sorted((r for _, r in pairs), reverse=True)
    assert cur == len(layer["miss"])
    assert dict(seen["a"]) == {"laundry": 2.5, "bar": 2.5}
    assert seen["b"] == [("pharmacy", 1.4)]


def test_nta_carries_the_supply_provenance(con):
    """Same rows, same supply set: a neighborhood view that could not say what
    supply it was measured against is the one place on this map D52 would not
    reach. The POI block is filtered by the same predicate, so an excluded
    record ships flagged rather than deleted."""
    _anchor(con, "laundry")
    _add_gap(con, "a", "MN", cat="laundry")
    _add_poi(con, "kept", "overture_places", 1, "MN")
    _add_poi(con, "kept2", "nyc_dohmh_restaurants", 1, "MN",   # corroborates it
             canonical=False)
    _add_poi(con, "dropped", "overture_places", 2, "MN")       # lone aggregator
    layer = _nta(con)["MN0001"]
    assert layer["supplySet"] == "principled"
    assert layer["supplyHash"] == "deadbeef1234"
    pois = layer["pois"]
    # Two canonical points; the lone aggregator record is exported flagged
    # out of the set (D52), never deleted, so nSet is 1 of 2.
    assert pois["n"] == 2 and pois["nSet"] == 1
    corr = {pois["pts"][i * 5 + 3] for i in range(pois["n"]) if pois["pts"][i * 5 + 4]}
    assert corr == {1}                       # the kept point is attested twice


def test_nta_meta_and_index_agree_with_the_files(con, tmp_path):
    """meta.json advertises the mode; the index must describe files that exist
    and count what they hold."""
    _add_gap(con, "mn1", "MN", cat="laundry", units=12.0)
    _add_gap(con, "bk1", "BK", cat="bar", units=4.0)
    bundle = wx.collect(con, ["MN", "BK"])
    wx.write(bundle, tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["nta"] == {"available": True, "dir": "nta", "n": 2, "addresses": 2}
    # The picker turns a typed name into a file name via `nta`.
    assert {n["nta"] for n in meta["neighborhoods"]} == {"MN0001", "BK0001"}
    index = json.loads((tmp_path / "nta" / "index.json").read_text())
    for row in index["ntas"]:
        layer = json.loads((tmp_path / "nta" / f"{row['nta']}.json").read_text())
        assert layer["n"] == row["n"] == len(layer["ids"])
        assert layer["gapCounts"] == row["gapCounts"]
        assert layer["units"] == row["units"]


# ------------------------------------------------ development pipeline (D62)
#
# Three things are load-bearing and each has already gone wrong somewhere in
# this project's history:
#
#  (a) THE MAP FILTER IS NOT THE INGEST FILTER. analysis.dev_pipeline holds
#      every job with a unit change, demolitions included; the overlay draws
#      net_units >= 50 in three stages. If a `filed` job ever reaches the file,
#      a developer's wish becomes a tower on someone's map -- and 259 MN+BK
#      jobs were permitted and then withdrawn, so `withdrawn` is the same bug
#      wearing a later date.
#
#  (b) DRIFT AGAINST THE MODEL. model/dev_pipeline.PIPELINE_COLUMNS is the
#      contract; this export carries seven of the twelve and must account for
#      the other five explicitly. A thirteenth column added to the model has to
#      break a test here, not silently never ship.
#
#  (c) THE SLOTS ARE APPENDED, NEVER INSERTED. Both gap layers are flat numeric
#      arrays read by position, and the NTA layer walks its `miss` array off
#      slot 5. Inserting a pipeline number ahead of those would relabel every
#      dot on the map with no error anywhere.


def _pipeline(con, boroughs=("MN", "BK")):
    return wx.collect_pipeline(con, list(boroughs))


def _jobs(layer):
    """{job_number: (stage, co, net_units)} out of the packed overlay."""
    st = layer["stride"]
    return {job: (layer["stages"][layer["pts"][i * st + 3]],
                  layer["co"][layer["pts"][i * st + 4]],
                  layer["pts"][i * st + 5])
            for i, job in enumerate(layer["ids"])}


def test_pipeline_gap_columns_account_for_every_model_column():
    """DRIFT TEST. The seven columns this export carries plus the five it
    deliberately drops must EXACTLY cover model/dev_pipeline.PIPELINE_COLUMNS.
    Adding a thirteenth column to the model then fails here until someone
    decides whether the map should show it -- which is the point."""
    from loci.model.dev_pipeline import PIPELINE_COLUMNS

    carried, dropped = set(wx.PIPELINE_GAP_COLUMNS), set(wx.PIPELINE_NOT_EXPORTED)
    assert not carried & dropped, "a column cannot be both exported and not exported"
    assert carried | dropped == set(PIPELINE_COLUMNS)
    # Every dropped column carries a REASON, not just a name.
    assert all(v.strip() for v in wx.PIPELINE_NOT_EXPORTED.values())


def test_gap_layer_advertises_exactly_the_columns_it_packs(con):
    """The exported layer names every contract it carries -- pipeline,
    storefront and age-fit -- and the pipeline slots are APPENDED to the
    original four: lon/lat/borough/units keep indices 0..3 or every existing
    reader breaks silently.

    The D63/D69 ranking block must NOT have moved the stride: it rides in its
    own parallel arrays precisely so `pts` stays a pure numeric array of 12."""
    _add_gap(con, "a", "MN", pipe={"units_permitted_400m": 250,
                                   "units_completed_24mo_400m": 40})
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert layer["pipelineColumns"] == wx.PIPELINE_GAP_COLUMNS
    assert layer["storefrontColumns"] == wx.STOREFRONT_GAP_COLUMNS
    assert layer["ageFitColumns"] == wx.AGE_FIT_GAP_COLUMNS
    assert layer["stride"] == 12
    assert layer["pts"][:4] == [PLACES["MN"][0], PLACES["MN"][1], 0, 10]
    assert layer["pts"][4:6] == [250, 40]
    # One entry per point in every ranking array, and no ranking value in pts.
    fit = layer["ageFit"]
    for key in ("score", "value", "moe", "scoreFit", "lead", "source"):
        assert len(fit[key]) == layer["n"], key


def test_gap_layer_carries_the_pipeline_reading(con):
    """Units and the nearest large project round-trip, with the project
    dictionary-encoded: ~1,400 jobs stand behind 267k addresses, so two
    addresses nearest the same job must share ONE entry."""
    p = {"units_permitted_400m": 600, "units_completed_24mo_400m": 120,
         "nearest_large_project_id": "B00680917", "nearest_large_project_m": 214.0,
         "nearest_large_project_units": 430, "nearest_large_project_stage": "permitted",
         "nearest_large_project_date": "2025-03-01"}
    _add_gap(con, "a", "MN", pipe=p)
    _add_gap(con, "b", "MN", pipe=p)
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    st = layer["stride"]
    assert layer["projects"]["ids"] == ["B00680917"]          # ONE entry, two users
    assert layer["projects"]["units"] == [430]
    assert layer["projects"]["stage"] == ["permitted"]
    assert layer["projects"]["date"] == ["2025-03-01"]
    for j in (0, 1):
        assert layer["pts"][j * st + 6] == 0                 # project index
        assert layer["pts"][j * st + 7] == 210               # metres, rounded to 10


def test_gap_layer_packs_nulls_as_no_project_not_as_zero(con):
    """An address the model never scored must read as "no project", never as a
    project at 0 m with 0 homes -- inventing a project out of a null is the
    "data gap wearing a costume" this project exists to avoid."""
    _add_gap(con, "a", "MN")
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert layer["pts"][4:8] == [0, 0, -1, -1]
    assert layer["projects"]["ids"] == []


def test_overlay_holds_no_filed_withdrawn_or_small_job(con):
    """THE ADVERSARIAL CASE. A filing is a developer's wish; a withdrawn job is
    attrition; a 12-unit job is not a wave of residents. None of the three may
    reach the map, whatever the query did."""
    _set_asof(con)
    _add_job(con, "keep_permit", "MN", net_units=120, stage="permitted")
    _add_job(con, "keep_partial", "BK", net_units=300, stage="partially_complete",
             co_type="temporary", date_complete="2026-01-01")
    _add_job(con, "drop_filed", "MN", net_units=800, stage="filed")
    _add_job(con, "drop_withdrawn", "MN", net_units=800, stage="withdrawn")
    _add_job(con, "drop_small", "MN", net_units=49, stage="permitted")
    _add_job(con, "drop_negative", "MN", net_units=-200, stage="permitted")
    layer = _pipeline(con)
    assert set(layer["ids"]) == {"keep_permit", "keep_partial"}
    assert all(u >= wx.PIPELINE_MIN_UNITS for u in layer["pts"][5::layer["stride"]])
    assert set(layer["stages"]) == set(wx.PIPELINE_MAP_STAGES)
    assert "filed" not in layer["stages"] and "withdrawn" not in layer["stages"]


def test_overlay_written_file_holds_no_filed_or_undersized_job(con, tmp_path):
    """The same guarantee, asserted against the JSON the browser actually
    fetches rather than against the object in memory."""
    _set_asof(con)
    _add_gap(con, "a", "MN")
    _add_job(con, "keep", "MN", net_units=90, stage="permitted")
    _add_job(con, "filed", "MN", net_units=900, stage="filed")
    _add_job(con, "old", "BK", net_units=900, stage="complete",
             co_type="final", date_complete="2015-06-01")
    wx.write(wx.collect(con, ["MN", "BK"]), tmp_path)
    layer = json.loads((tmp_path / "pipeline.json").read_text())
    assert layer["ids"] == ["keep"]
    st = layer["stride"]
    for i in range(0, len(layer["pts"]), st):
        assert layer["stages"][layer["pts"][i + 3]] in wx.PIPELINE_MAP_STAGES
        assert layer["pts"][i + 5] >= wx.PIPELINE_MIN_UNITS


def test_completions_outside_the_window_are_dropped(con):
    """"Recently arrived" is a window, not a synonym for "complete". A 2013
    tower's residents are in ACS already; the map is about the ones who are
    not."""
    _set_asof(con, "2026-09-09")
    _add_job(con, "recent", "MN", net_units=200, stage="complete",
             co_type="final", date_complete="2024-02-01")
    _add_job(con, "edge", "BK", net_units=200, stage="complete",
             co_type="temporary", date_complete="2021-10-01")   # 59 months back
    _add_job(con, "ancient", "MN", net_units=200, stage="complete",
             co_type="final", date_complete="2013-05-01")
    jobs = _jobs(_pipeline(con))
    assert set(jobs) == {"recent", "edge"}
    assert jobs["recent"][1] == "final" and jobs["edge"][1] == "temporary"


def test_permitted_job_with_no_co_is_none_not_temporary(con):
    """The CO slot has three states and the map draws two marks off it. A
    permitted job has NO certificate of occupancy; collapsing that into
    "temporary" would draw a hollow ring meaning "occupied but unfinished" over
    a hole in the ground."""
    _set_asof(con)
    _add_job(con, "p", "MN", net_units=200, stage="permitted")
    assert _jobs(_pipeline(con))["p"][1] == "none"


def test_bands_come_from_one_definition(con):
    """The UI sizes its marks off the band edges in the file and the dry-run
    counts off `pipeline_band`. Both must be the same edges, or the map draws
    something it did not count."""
    _set_asof(con)
    for job, units in (("small", 50), ("mid", 100), ("big", 300), ("huge", 1200)):
        _add_job(con, job, "MN", net_units=units, stage="permitted")
    layer = _pipeline(con)
    summary = wx.pipeline_summary(layer, ["MN", "BK"])
    assert [b[0] for b in layer["bands"]] == [50, 100, 300]
    assert summary["bands"]["50–99 homes"]["MN"] == 1
    assert summary["bands"]["100–299 homes"]["MN"] == 1
    assert summary["bands"]["300+ homes"]["MN"] == 2
    assert summary["bandUnits"]["300+ homes"] == 1500
    assert wx.pipeline_band(49) == -1


def test_overlay_obeys_the_borough_filter(con):
    """Every layer on this map obeys the borough selector; a Queens tower must
    not reach a Manhattan+Brooklyn export."""
    _set_asof(con)
    _add_job(con, "mn", "MN", net_units=200, stage="permitted")
    _add_job(con, "qn", "QN", net_units=200, stage="permitted")
    assert _pipeline(con, ("MN", "BK"))["ids"] == ["mn"]


def test_missing_pipeline_table_degrades_to_an_empty_overlay(con):
    """`loci ingest-dcp-housing` is optional -- an export must not fail because
    of it, and the UI must be able to say "not loaded" rather than show a
    confident zero."""
    con.execute("DROP TABLE analysis.dev_pipeline")
    layer = _pipeline(con)
    assert layer["available"] is False and layer["n"] == 0
    assert layer["stages"] == list(wx.PIPELINE_MAP_STAGES)   # legend still renderable


def test_meta_carries_the_vintage_and_the_forward_cutoff(con, tmp_path):
    """THE VINTAGE HAS TO RIDE WITH THE DATA. DCP publishes semiannually, so a
    layer that says "40,587 homes coming" without saying as-of-when ages into a
    lie. `cutoff` is DERIVED from the newest filing/permit date in the table,
    so it cannot drift from the rows actually loaded."""
    _set_asof(con, "2026-09-09")
    _add_gap(con, "a", "MN")
    _add_job(con, "p", "MN", net_units=200, stage="permitted",
             date_filed="2025-06-01", date_permitted="2026-01-20")
    wx.write(wx.collect(con, ["MN", "BK"]), tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text())["pipeline"]
    assert meta["available"] is True
    assert meta["asof"] == "2026-09-09"
    assert meta["asofSource"] == "analysis.address.pipeline_asof"
    assert meta["vintage"] == "25Q4"
    assert meta["cutoff"] == "2026-01-20"
    assert meta["minUnits"] == wx.PIPELINE_MIN_UNITS
    assert meta["completeMonths"] == wx.PIPELINE_COMPLETE_MONTHS
    assert meta["gapColumns"] == wx.PIPELINE_GAP_COLUMNS
    assert meta["counts"]["permitted"]["MN"] == 1


def test_nta_layer_carries_pipeline_without_moving_the_missing_walk(con):
    """The all-opportunities layer reads `lead`, `gap_score` and `n_missing` by
    position and walks its `miss` array off slot 5. The four pipeline slots are
    APPENDED, so all of that must still hold with a stride of 10."""
    _add_gap(con, "a", "MN", cat="laundry", extra=("bar",),
             pipe={"units_permitted_400m": 900, "units_completed_24mo_400m": 15,
                   "nearest_large_project_id": "321590532",
                   "nearest_large_project_m": 88.0,
                   "nearest_large_project_units": 512,
                   "nearest_large_project_stage": "filed",
                   "nearest_large_project_date": "2026-01-02"})
    layer = wx.collect_nta(con, ["MN"], "principled", "deadbeef1234")["MN0001"]
    st = layer["stride"]
    assert st == 14
    assert layer["pts"][5] == 2                       # n_missing still slot 5
    assert len(layer["miss"]) == 4                    # two (category, ratio) pairs
    assert layer["pts"][6:10] == [900, 15, 0, 90]
    # The model's nearest-large-project column CAN name a filed job even though
    # the overlay refuses to draw one. It ships labelled with its stage so the
    # popup can say the project is not on the map.
    assert layer["projects"]["stage"] == ["filed"]
    assert layer["pipelineColumns"] == wx.PIPELINE_GAP_COLUMNS


def test_export_survives_a_database_without_the_pipeline_columns(con):
    """A database built before `loci pipeline` still exports: the slots ship
    empty so the browser never has to branch on which vintage of file it
    fetched."""
    _add_gap(con, "a", "MN")
    for c in wx.PIPELINE_GAP_COLUMNS:
        con.execute(f"ALTER TABLE analysis.address_gaps DROP COLUMN {c}")
    assert wx.has_pipeline_columns(con) is False
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert layer["stride"] == 12 and layer["pts"][4:8] == [0, 0, -1, -1]


# ----------------------------------------------- vacant storefronts (2026-09-10)
#
# Four things are load-bearing and every one of them has a documented way of
# going quietly wrong (sql/012's caveat block):
#
#  (a) THE SNAPSHOT IS ONE FILING. Five of DOF's eleven filings hold vacant
#      rows ONLY, and two filings can observe the same 12/31 -- the 2025-06-03
#      annual and the 2025-02-15 supplement both observe 2024-12-31. Pooling
#      them counts the premises that filed both twice and lifts the MN+BK
#      vacancy rate from 9.94% to 13.79%: a plausible-looking wrong number.
#
#  (b) ONE POINT PER PREMISES, NOT PER STOREFRONT. `storefront_id` renumbers
#      between filings and one premises can file thirty storefronts. Drawing
#      one square each would show thirty empty buildings where there is one.
#
#  (c) PRIOR USE IS NOT THE ROW'S OWN COLUMN. A vacant row necessarily reports
#      'NO BUSINESS ACTIVITY IDENTIFIED', so a popup reading the row would say
#      that for every point. The answer is a premises-level ARG_MAX over
#      EARLIER filings, and where there is none the honest word is "unknown".
#
#  (d) THE DENOMINATOR TRAVELS WITH THE COUNT. The registry is self-reported:
#      "no vacancy within 400 m" and "nobody within 400 m filed" are the same
#      observation, and only the registered total tells them apart.


def _shops(con, boroughs=("MN", "BK")):
    return wx.collect_storefronts(con, list(boroughs))


def _premises(layer):
    """{premises_id: (band label, construction, vacant storefronts here)}."""
    st = layer["stride"]
    return {pid: (layer["bandLabels"][layer["pts"][i * st + 3]],
                  bool(layer["pts"][i * st + 4]),
                  layer["storefronts"][i])
            for i, pid in enumerate(layer["ids"])}


def test_storefront_gap_columns_account_for_every_model_column():
    """DRIFT TEST. The five columns this export carries plus the two it
    deliberately drops must EXACTLY cover model/storefronts.STOREFRONT_COLUMNS.
    An eighth column added to the model then fails here until someone decides
    whether the map should show it -- which is the point."""
    from loci.model.storefronts import STOREFRONT_COLUMNS

    carried, dropped = set(wx.STOREFRONT_GAP_COLUMNS), set(wx.STOREFRONT_NOT_EXPORTED)
    assert not carried & dropped, "a column cannot be both exported and not exported"
    assert carried | dropped == set(STOREFRONT_COLUMNS)
    # Every dropped column carries a REASON, not just a name.
    assert all(v.strip() for v in wx.STOREFRONT_NOT_EXPORTED.values())


def test_storefront_radius_is_the_projects_own_five_minute_tier():
    """The legend says "within 400 m" and the model computed the column over
    THRESHOLDS[5]. The constant is restated in viz/ only because importing
    score.access would drag osmnx into the exporter, so it has to be pinned."""
    from loci.model.storefronts import DEFAULT_RADIUS_M

    assert wx.STOREFRONT_RADIUS_M == DEFAULT_RADIUS_M


def test_gap_layer_advertises_exactly_the_storefront_columns_it_packs(con):
    """The four storefront slots are APPENDED after the four pipeline ones:
    lon/lat/borough/units keep 0..3 and the pipeline block keeps 4..7, or every
    existing reader silently relabels its dots."""
    _add_gap(con, "a", "MN",
             pipe={"units_permitted_400m": 250, "units_completed_24mo_400m": 40},
             shop={"vacant_storefronts_400m": 3, "storefronts_400m": 48,
                   "nearest_vacant_storefront_m": 137.0,
                   "nearest_vacant_storefront_id": "1000#1",
                   "nearest_vacant_lease_expired": True})
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert layer["storefrontColumns"] == wx.STOREFRONT_GAP_COLUMNS
    assert layer["stride"] == 12
    assert layer["pts"][:4] == [PLACES["MN"][0], PLACES["MN"][1], 0, 10]
    assert layer["pts"][4:8] == [250, 40, -1, -1]          # pipeline block, untouched
    assert layer["pts"][8:12] == [3, 48, 0, 140]           # vacancy block, rounded to 10


def test_gap_layer_dictionary_encodes_the_nearest_vacant_storefront(con):
    """~2,750 vacant premises stand behind 282k addresses, so two addresses
    nearest the same storefront must share ONE entry -- carrying its address,
    its premises-level prior use and its lease state once."""
    _add_storefront(con, "1000", "MN", business="RETAIL",
                    filing="2023-08-15", observed="2022-12-31", vacant=False)
    _add_storefront(con, "1000", "MN", address="12 SPRING ST")
    shop = {"vacant_storefronts_400m": 2, "storefronts_400m": 30,
            "nearest_vacant_storefront_m": 214.0,
            "nearest_vacant_storefront_id": "1000#1",
            "nearest_vacant_lease_expired": True}
    _add_gap(con, "a", "MN", shop=shop)
    _add_gap(con, "b", "MN", shop=shop)
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    v, st = layer["vacants"], layer["stride"]
    assert v["ids"] == ["1000#1"]                  # ONE entry, two users
    assert v["addr"] == ["12 SPRING ST"]
    assert v["business"] == ["RETAIL"]             # the ARG_MAX, not the vacant row
    assert v["lease"] == [1]
    for j in (0, 1):
        assert layer["pts"][j * st + 10] == 0      # dictionary index
        assert layer["pts"][j * st + 11] == 210    # metres, rounded to 10


def test_gap_layer_packs_no_vacancy_as_absence_not_as_zero_metres(con):
    """An address the model never scored must read as "no vacancy known", never
    as a storefront at 0 m -- and an unreported lease must be -1, never 0. A
    filing that reported no lease has NOT told us the lease is running."""
    _add_gap(con, "a", "MN", shop={"vacant_storefronts_400m": 0,
                                   "storefronts_400m": 0,
                                   "nearest_vacant_storefront_id": None})
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert layer["pts"][8:12] == [0, 0, -1, -1]
    assert layer["vacants"]["ids"] == []
    _add_gap(con, "b", "BK", shop={"vacant_storefronts_400m": 1,
                                   "storefronts_400m": 9,
                                   "nearest_vacant_storefront_m": 88.0,
                                   "nearest_vacant_storefront_id": "2000#1",
                                   "nearest_vacant_lease_expired": None})
    layer = wx.collect(con, ["MN", "BK"])["gaps"]["laundry"]
    assert layer["vacants"]["lease"] == [-1]


def test_overlay_draws_one_point_per_premises_not_per_storefront(con):
    """THE FUSION BUG'S MIRROR IMAGE. A premises filing four vacant storefronts
    is ONE empty building; four coincident squares would read as four."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    for seq in (1, 2, 3, 4):
        _add_storefront(con, "1000", "MN", seq=seq)
    layer = _shops(con)
    assert layer["ids"] == ["1000"]
    assert _premises(layer)["1000"][2] == 4      # the count rides in the popup


def test_overlay_holds_only_premises_vacant_in_the_snapshot(con):
    """THE ADVERSARIAL CASE. An occupied premises, a premises vacant only in an
    OLDER filing, and a premises with no coordinate must none of them reach the
    map -- the last one is dropped explicitly and counted, never lost."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_storefront(con, "vacant_now", "MN")
    _add_storefront(con, "occupied", "MN", vacant=False,
                    business="FOOD SERVICES")
    _add_storefront(con, "vacant_then", "BK", filing="2023-08-15",
                    observed="2022-12-31")
    _add_storefront(con, "no_geom", "MN", geom=False)
    layer = _shops(con)
    assert set(layer["ids"]) == {"vacant_now"}
    assert layer["totals"]["MN"]["vacantPremises"] == 2      # the no-geom one counts
    assert layer["totals"]["MN"]["noGeom"] == 1              # ...and is reported


def test_overlay_never_pools_the_vacant_only_supplement(con):
    """THE DOUBLE-COUNT BUG, exactly as sql/012 describes it. The 2025-02-15
    supplement and the 2025-06-03 annual filing BOTH observe 2024-12-31. The
    full filing wins; the supplement's rows must add neither a point nor a
    storefront to the denominator, or the vacancy rate reads 13.79% instead of
    9.94%."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_storefront(con, "1000", "MN")
    _add_storefront(con, "1000", "MN", filing=SUPPLEMENT, universe="vacant_only")
    _add_storefront(con, "2000", "MN", vacant=False)
    layer = _shops(con)
    assert layer["filingDate"] == SNAP_FILING and layer["universe"] == "full"
    assert layer["ids"] == ["1000"]
    assert _premises(layer)["1000"][2] == 1
    assert layer["totals"]["MN"]["storefronts"] == 2          # the filing's universe
    assert layer["totals"]["MN"]["vacantStorefronts"] == 1


def test_consecutive_years_are_counted_back_from_the_snapshot(con):
    """The run is anchored at the SNAPSHOT year, not at the premises' own last
    observation (which for many is a 2025 vacant-only supplement answering a
    different question). A skipped or occupied year ends the run."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    for yr, filing in (("2022-12-31", "2023-08-15"), ("2023-12-31", "2024-06-03")):
        _add_storefront(con, "chronic", "MN", filing=filing, observed=yr)
        _add_storefront(con, "broken", "MN", filing=filing, observed=yr,
                        vacant=(yr == "2022-12-31"))
    _add_storefront(con, "chronic", "MN")
    _add_storefront(con, "broken", "MN")
    _add_storefront(con, "fresh", "BK")
    prem = _premises(_shops(con))
    assert prem["chronic"][0] == wx.STOREFRONT_YEAR_LABELS[1]   # 3 consecutive
    assert prem["broken"][0] == wx.STOREFRONT_YEAR_LABELS[0]    # 2023 was occupied
    assert prem["fresh"][0] == wx.STOREFRONT_YEAR_LABELS[0]
    assert wx.storefront_band(0) == -1


def test_vacant_since_is_derived_from_the_run_not_stored(con):
    """"Vacant since" is the first year of the run rendered as that year's
    12/31. Deriving it means a re-banding cannot leave a stale date behind."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_storefront(con, "chronic", "MN", filing="2024-06-03", observed="2023-12-31")
    _add_storefront(con, "chronic", "MN")
    layer = _shops(con)
    since = layer["vocab"]["date"][layer["since"][0]]
    assert since == "2023-12-31"


def test_prior_use_is_the_premises_argmax_and_unknown_when_absent(con):
    """A vacant row necessarily reports 'NO BUSINESS ACTIVITY IDENTIFIED'
    (sql/012 caveat 7b), so the popup must read the premises-level ARG_MAX over
    earlier filings -- and say nothing at all where there is none, rather than
    printing DOF's placeholder as a business."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_storefront(con, "known", "MN", filing="2022-08-15", observed="2021-12-31",
                    vacant=False, business="LAUNDRY SERVICES")
    _add_storefront(con, "known", "MN", filing="2024-06-03", observed="2023-12-31",
                    vacant=False, business="FOOD SERVICES")
    _add_storefront(con, "known", "MN")
    _add_storefront(con, "never", "BK")
    layer = _shops(con)
    biz = {pid: (None if layer["business"][i] < 0
                 else layer["vocab"]["business"][layer["business"][i]])
           for i, pid in enumerate(layer["ids"])}
    assert biz["known"] == "FOOD SERVICES"      # the LATEST non-placeholder use
    assert biz["never"] is None                 # the UI prints "unknown"


def test_construction_is_flagged_not_dropped(con):
    """A ground floor empty because it is being gut-renovated is still a
    reported vacancy (sql/012 caveat 6) -- it gets its own mark, not a
    deletion, so a consumer who wants leasable-now can filter and a consumer
    counting vacancies still sees it."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_storefront(con, "building", "MN", construction=True)
    _add_storefront(con, "empty", "MN")
    layer = _shops(con)
    assert set(layer["ids"]) == {"building", "empty"}
    assert _premises(layer)["building"][1] is True
    assert layer["construction"]["MN"] == 1


def test_storefront_overlay_obeys_the_borough_filter(con):
    """Every layer on this map obeys the borough selector; a Queens vacancy
    must not reach a Manhattan+Brooklyn export. Named apart from the pipeline
    overlay's identical guarantee on purpose -- one `def` shadowing the other
    would silently delete a test rather than fail one."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_storefront(con, "mn", "MN")
    _add_storefront(con, "qn", "QN")
    assert _shops(con, ("MN", "BK"))["ids"] == ["mn"]


def test_storefront_asof_falls_back_to_a_full_filing_never_a_supplement(con):
    """`loci storefronts` may not have run. The fallback is the newest
    FULL-universe observation, never simply the newest one: the freshest
    filings are vacant-only supplements, and taking one as the snapshot gives a
    numerator with no denominator (sql/012 caveat 4)."""
    _add_storefront(con, "1000", "MN")
    _add_storefront(con, "1000", "MN", filing="2026-02-15", universe="vacant_only",
                    observed="2025-12-31", seq=2)
    asof, source = wx.storefront_asof(con, ["MN", "BK"])
    assert asof == SNAP_OBSERVED
    assert "observed_1231" in source
    layer = _shops(con)
    assert layer["asof"] == SNAP_OBSERVED and layer["filingDate"] == SNAP_FILING


def test_missing_storefront_table_degrades_to_an_empty_overlay(con):
    """`loci ingest-storefronts` is optional -- an export must not fail because
    of it, and the UI must be able to say "not loaded" rather than show a
    confident zero."""
    con.execute("DROP TABLE analysis.storefront")
    layer = _shops(con)
    assert layer["available"] is False and layer["n"] == 0
    assert layer["bandLabels"] == list(wx.STOREFRONT_YEAR_LABELS)  # legend renderable
    assert wx.collect_vacant_detail(con, ["MN", "BK"]) == {}


def test_export_survives_a_database_without_the_storefront_columns(con):
    """A database built before `loci storefronts` still exports: the slots ship
    empty so the browser never has to branch on which vintage of file it
    fetched."""
    _add_gap(con, "a", "MN")
    for c in wx.STOREFRONT_GAP_COLUMNS:
        con.execute(f"ALTER TABLE analysis.address_gaps DROP COLUMN {c}")
    assert wx.has_storefront_columns(con) is False
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert layer["stride"] == 12 and layer["pts"][8:12] == [0, 0, -1, -1]


def test_written_overlay_holds_only_snapshot_vacancies(con, tmp_path):
    """The same guarantee, asserted against the JSON the browser actually
    fetches rather than against the object in memory."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_gap(con, "a", "MN")
    _add_storefront(con, "keep", "MN")
    _add_storefront(con, "supplement", "MN", filing=SUPPLEMENT,
                    universe="vacant_only")
    _add_storefront(con, "occupied", "BK", vacant=False)
    wx.write(wx.collect(con, ["MN", "BK"]), tmp_path)
    layer = json.loads((tmp_path / "storefronts.json").read_text())
    assert layer["ids"] == ["keep"]
    st = layer["stride"]
    for i in range(0, len(layer["pts"]), st):
        assert 0 <= layer["pts"][i + 3] < len(layer["bandLabels"])


def test_meta_carries_the_snapshot_dates_and_the_denominator(con, tmp_path):
    """THE DATES AND THE DENOMINATOR RIDE WITH THE DATA. A legend saying "2,751
    empty storefronts" without the observation date, the filing date and the
    registered total is a legend that ages into a lie inside a year -- and in a
    self-reported registry a bare count cannot be read as a rate at all."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_gap(con, "a", "MN")
    _add_storefront(con, "1000", "MN")
    _add_storefront(con, "2000", "MN", vacant=False)
    wx.write(wx.collect(con, ["MN", "BK"]), tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text())["storefront"]
    assert meta["available"] is True
    assert meta["asof"] == SNAP_OBSERVED
    assert meta["asofSource"] == "analysis.address.storefront_asof"
    assert meta["filingDate"] == SNAP_FILING
    assert meta["universe"] == "full"
    assert meta["vintage"] == "2026-04-09"
    assert meta["radiusM"] == wx.STOREFRONT_RADIUS_M
    assert meta["bandLabels"] == list(wx.STOREFRONT_YEAR_LABELS)
    assert meta["gapColumns"] == wx.STOREFRONT_GAP_COLUMNS
    assert meta["totals"]["MN"] == {"storefronts": 2, "premises": 2,
                                    "vacantStorefronts": 1, "vacantPremises": 1,
                                    "noGeom": 0}
    assert meta["counts"][wx.STOREFRONT_YEAR_LABELS[0]]["MN"] == 1


def test_dry_run_counts_come_off_the_packed_layer(con):
    """What `--dry-run` prints is counted off the PACKED overlay, not
    re-queried, so the terminal and the file cannot disagree."""
    _set_asof(con, sf_asof=SNAP_OBSERVED)
    _add_storefront(con, "a", "MN")
    _add_storefront(con, "b", "MN", construction=True)
    _add_storefront(con, "c", "BK", filing="2024-06-03", observed="2023-12-31")
    _add_storefront(con, "c", "BK")
    summary = wx.summarize(wx.collect(con, ["MN", "BK"]))["storefront"]
    assert summary["available"] is True and summary["n"] == 3
    assert summary["bands"][wx.STOREFRONT_YEAR_LABELS[0]]["MN"] == 2
    assert summary["bands"][wx.STOREFRONT_YEAR_LABELS[1]]["BK"] == 1
    assert summary["construction"]["MN"] == 1
    assert summary["totals"]["BK"]["storefronts"] == 1
    assert summary["asof"] == SNAP_OBSERVED and summary["filingDate"] == SNAP_FILING


def test_nta_layer_carries_vacancy_without_moving_the_missing_walk(con):
    """The all-opportunities layer reads `lead`, `gap_score` and `n_missing` by
    position and walks its `miss` array off slot 5. Both annotation blocks are
    APPENDED, so all of that must still hold at a stride of 14."""
    _add_storefront(con, "1000", "MN", address="7 BOND ST", business="RETAIL",
                    filing="2023-08-15", observed="2022-12-31", vacant=False)
    _add_storefront(con, "1000", "MN", address="7 BOND ST")
    _add_gap(con, "a", "MN", cat="laundry", extra=("bar",),
             pipe={"units_permitted_400m": 900, "units_completed_24mo_400m": 15},
             shop={"vacant_storefronts_400m": 4, "storefronts_400m": 61,
                   "nearest_vacant_storefront_m": 121.0,
                   "nearest_vacant_storefront_id": "1000#1",
                   "nearest_vacant_lease_expired": False})
    layer = wx.collect_nta(con, ["MN"], "principled", "deadbeef1234")["MN0001"]
    assert layer["stride"] == 14
    assert layer["pts"][5] == 2                       # n_missing still slot 5
    assert len(layer["miss"]) == 4                    # two (category, ratio) pairs
    assert layer["pts"][6:10] == [900, 15, -1, -1]    # pipeline block, untouched
    assert layer["pts"][10:14] == [4, 61, 0, 120]
    assert layer["vacants"]["addr"] == ["7 BOND ST"]
    assert layer["vacants"]["business"] == ["RETAIL"]
    assert layer["vacants"]["lease"] == [0]
    assert layer["storefrontColumns"] == wx.STOREFRONT_GAP_COLUMNS


# ------------------------------------------------ age fit (D63/D64/D69, 2026-09-11)
#
# The age-fit multiplier is a SEPARATE RANKING COLUMN, never a filter, and
# three of its failure modes are silent:
#
#  (a) NULL BECOMING 1.0. Eleven of the fifteen categories have no curve at
#      all. `age_fit_lead IS NULL` means "never fitted"; 1.0 means "fitted, and
#      neutral". Collapsing the two would let the map claim a curve the model
#      never estimated -- and `float(None or 0)` / a numeric stride slot is
#      exactly how it happens. The block therefore rides in parallel arrays and
#      the written JSON must contain literal nulls.
#
#  (b) A MULTIPLIER WITHOUT ITS MOE. Childcare's F4 band is three times bar's
#      (D69), so the MOE travels with the value in the file. A file that
#      shipped the value alone would let a renderer show 2.31 as if it were
#      2.31 +/- 0.06.
#
#  (c) A CAVEAT THAT IS NOT THE MODEL'S. The text in meta.json must be
#      model/age_fit.AGE_FIT_DISCLAIMER VERBATIM -- a paraphrase is how a
#      caveat gets softer than the finding it guards.


def _write_curve(d, category, spec="poi_composition_v1",
                 fitted_at="2026-09-11T15:11:46+00:00", supply_hash="06bb6f357cc1",
                 median_moe=0.178):
    """One `data/interim/age_fit_<category>.json`, shaped like the real fit
    writer's output -- the keys the export actually reads."""
    d.mkdir(parents=True, exist_ok=True)
    (d / f"age_fit_{category}.json").write_text(json.dumps({
        "category": category, "spec": spec, "fitted_at": fitted_at,
        "radius_m": 400.0, "primary_age_term": "under_18_share",
        "inputs": {"acs_year": 2023, "supply_hash": supply_hash,
                   "screen_supply_hash": supply_hash, "n_target": 2657,
                   "hash": "9be7c7581046"},
        "multiplier": {"median_moe": median_moe, "p10": 0.9, "p50": 1.03, "p90": 1.21},
    }))
    return d


def test_age_fit_gap_columns_match_the_model_writer():
    """DRIFT TEST. The three columns this export carries are exactly the three
    model/age_fit.py writes onto analysis.address, and the directory it reads
    curves from is the one the fitter writes them to. Both are held as literals
    here because model/age_fit.py pulls in osmnx and this module must stay
    importable without it -- so the only thing keeping them honest is this."""
    from loci.model import age_fit as af

    assert wx.AGE_FIT_GAP_COLUMNS == af.ADDRESS_AGE_FIT_COLUMNS
    assert wx.AGE_FIT_DIR == af.INTERIM_DIR
    assert wx.AGE_FIT_SOURCE_COLUMN in af.AGE_FIT_COLUMNS
    # One score, two views: the gap layer and the all-opportunities layer must
    # round gap_score the same way or the same address reads two values.
    assert wx.GAP_SCORE_DP == wx.SCORE_DP


def test_gap_layer_carries_the_age_adjusted_ranking(con):
    """Both scores, the multiplier, its MOE, whose curve it is and what spec
    that curve was fitted under, all for one address.

    The lead category is deliberately NOT the file's category: in
    `gaps/laundry.json` an address's age_fit_lead can belong to `bar`, and the
    export has to carry the lead so the popup can say so."""
    _add_gap(con, "a", "MN", cat="laundry", lead="bar", score=2.0,
             age={"age_fit_lead": 1.2345, "age_fit_lead_moe": 0.0554,
                  "gap_score_fit": 2.469},
             age_source="sla_composition_v1")
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    fit = layer["ageFit"]
    assert fit["score"] == [2.0]
    assert fit["value"] == [1.235]          # rounded to AGE_FIT_DP, never truncated
    assert fit["moe"] == [0.055]            # the MOE travels with the value
    assert fit["scoreFit"] == [2.469]
    assert fit["lead"] == [wx.ALLCATS.index("bar")]
    assert fit["sources"] == ["sla_composition_v1"]
    assert fit["source"] == [0]


def test_null_age_fit_exports_as_json_null_never_a_neutral_one(con, tmp_path):
    """THE ADVERSARIAL CASE. An address in a category with no curve must export
    `null` for the multiplier, its MOE and the age-adjusted score -- never 1.0
    (which would claim a curve that says "neutral"), never 0 (which would claim
    a curve that says "nobody here"), and never the un-multiplied gap_score
    under an age-adjusted label.

    Asserted against the WRITTEN FILE as well as the packed layer, because the
    distinction only survives if `json.dumps` emits a literal null."""
    _add_gap(con, "a", "MN", score=1.5)              # no age= at all
    bundle = wx.collect(con, ["MN"])
    fit = bundle["gaps"]["laundry"]["ageFit"]
    assert fit["value"] == [None] and fit["moe"] == [None]
    assert fit["scoreFit"] == [None]
    assert fit["source"] == [None] and fit["sources"] == []
    assert fit["score"] == [1.5]                     # the un-adjusted score still ships
    wx.write(bundle, tmp_path)
    raw = (tmp_path / "gaps" / "laundry.json").read_text()
    assert '"value":[null]' in raw and '"moe":[null]' in raw
    assert '"scoreFit":[null]' in raw
    on_disk = json.loads(raw)["ageFit"]
    assert on_disk["value"] == [None] and on_disk["scoreFit"] == [None]


def test_meta_age_fit_lists_exactly_the_live_curves_and_the_caveat(con, tmp_path):
    """A curve is LIVE when its JSON is on disk -- that is the state D69 used
    to retire pharmacy's, by MOVING the file out rather than editing a flag. So
    the block must list exactly the files present, carry each one's fit
    timestamp and supply hash, and carry the caveat VERBATIM."""
    from loci.model.age_fit import AGE_FIT_DISCLAIMER

    curves = _write_curve(tmp_path / "interim", "childcare")
    _write_curve(curves, "bar", spec="sla_composition_v1",
                 fitted_at="2026-09-11T15:11:45+00:00", median_moe=0.055)
    _add_gap(con, "a", "MN")
    _set_provenance(con, supply_hash="06bb6f357cc1")
    out = tmp_path / "out"
    wx.write(wx.collect(con, ["MN"], curve_dir=curves), out)
    meta = json.loads((out / "meta.json").read_text())["ageFit"]

    assert meta["categories"] == ["bar", "childcare"]      # exactly the files present
    assert "pharmacy" not in meta["curves"]                # retired == no file
    assert meta["curves"]["childcare"]["fittedAt"] == "2026-09-11T15:11:46+00:00"
    assert meta["curves"]["childcare"]["supplyHash"] == "06bb6f357cc1"
    assert meta["curves"]["childcare"]["spec"] == "poi_composition_v1"
    # The band the D69 next action is about: childcare's is three times bar's,
    # and a renderer that cannot read it cannot obey "never without its MOE".
    assert meta["curves"]["childcare"]["medianMoe"] == 0.178
    assert meta["curves"]["bar"]["medianMoe"] == 0.055
    assert meta["caveat"] == AGE_FIT_DISCLAIMER            # verbatim, not a paraphrase
    assert meta["available"] is True and meta["stale"] == [] and meta["warning"] is None


def test_meta_age_fit_is_empty_when_no_curve_is_live(con, tmp_path):
    """No file on disk means no category may be offered the age-adjusted
    ranking -- and the caveat still ships, because the columns can still hold a
    multiplier a previous run applied."""
    from loci.model.age_fit import AGE_FIT_DISCLAIMER

    _add_gap(con, "a", "MN")
    meta = wx.collect(con, ["MN"], curve_dir=tmp_path / "nothing-here")["ageFit"]
    assert meta["categories"] == [] and meta["curves"] == {}
    assert meta["available"] is False
    assert meta["caveat"] == AGE_FIT_DISCLAIMER


def test_meta_age_fit_warns_when_the_curve_was_fitted_on_another_supply(con, tmp_path):
    """Same class of error as the D52 supply-set mismatch: a multiplier
    estimated on one supply, applied to gaps measured against another, is a
    number the model never fitted for these addresses. The map has to say so on
    its own face, not only in a terminal nobody kept."""
    curves = _write_curve(tmp_path / "interim", "childcare", supply_hash="deadbeef0000")
    _add_gap(con, "a", "MN")
    _set_provenance(con, supply_hash="06bb6f357cc1")
    meta = wx.collect(con, ["MN"], curve_dir=curves)["ageFit"]
    assert meta["stale"] == ["childcare"]
    assert "AGE-FIT SUPPLY MISMATCH" in meta["warning"]
    assert "06bb6f357cc1" in meta["warning"]


def test_export_survives_a_database_without_the_age_fit_columns(con, tmp_path):
    """A database built before `loci age-fit apply` still exports: the ranking
    arrays ship null so the browser never has to branch on which vintage of
    file it fetched -- and `columnsPresent` false says WHY they are null, so a
    reader cannot mistake "never applied" for "every curve says neutral"."""
    _add_gap(con, "a", "MN", score=1.5)
    for c in wx.AGE_FIT_GAP_COLUMNS:
        con.execute(f"ALTER TABLE analysis.address_gaps DROP COLUMN {c}")
    assert wx.has_age_fit_columns(con) is False
    bundle = wx.collect(con, ["MN"])
    layer = bundle["gaps"]["laundry"]
    assert layer["stride"] == 12                     # unchanged, as ever
    fit = layer["ageFit"]
    assert fit["value"] == [None] and fit["moe"] == [None] and fit["scoreFit"] == [None]
    assert fit["score"] == [1.5]                     # gap_score is not an age-fit column
    assert bundle["ageFit"]["columnsPresent"] is False
    assert bundle["ageFit"]["available"] is False
    wx.write(bundle, tmp_path)                       # and the whole export still writes


def test_export_survives_a_database_with_no_address_category_table(con):
    """`age_fit_source` is per CATEGORY, so it is joined rather than read off
    the view. A database with no analysis.address_category must export a null
    source and SAY the join was skipped -- never fail the whole map on a
    missing table."""
    _add_gap(con, "a", "MN", age={"age_fit_lead": 1.1, "age_fit_lead_moe": 0.2,
                                  "gap_score_fit": 1.65})
    con.execute("DROP TABLE analysis.address_category")
    assert wx.has_age_fit_source(con) is False
    bundle = wx.collect(con, ["MN"])
    fit = bundle["gaps"]["laundry"]["ageFit"]
    assert fit["value"] == [1.1] and fit["moe"] == [0.2]     # the multiplier survives
    assert fit["source"] == [None] and fit["sources"] == []
    assert bundle["ageFit"]["sourceJoined"] is False


def test_age_fit_is_never_a_filter(con):
    """D63's non-filtering rule, at the export. Two addresses with the same
    ratio, one with a curve and one without, must BOTH be drawn -- a
    multiplier changes the order of the gap layer, never its membership."""
    _add_gap(con, "with_curve", "MN", age={"age_fit_lead": 0.4,
                                           "age_fit_lead_moe": 0.1,
                                           "gap_score_fit": 0.6})
    _add_gap(con, "no_curve", "MN")
    layer = wx.collect(con, ["MN"])["gaps"]["laundry"]
    assert sorted(layer["ids"]) == ["no_curve", "with_curve"]
    assert layer["n"] == 2


def test_identity_multiplier_is_distinguishable_from_a_fitted_neutral_one(con):
    """THE SECOND ADVERSARIAL CASE, and the reason the source is joined at all.

    sql/002's D63 block writes `age_fit_lead = 1.0` with a NULL MOE when the
    address's LEAD category has no fitted curve -- the identity multiplier, so
    gap_score_fit == gap_score exactly. That is NOT a curve that says "this
    block is exactly average", and the file has to let a renderer tell the two
    apart. `age_fit_source` is that discriminator: absent on the identity row,
    present on the fitted one."""
    _add_gap(con, "identity", "MN", score=1.5,
             age={"age_fit_lead": 1.0, "age_fit_lead_moe": None,
                  "gap_score_fit": 1.5})                       # no age_source
    _add_gap(con, "fitted", "MN", score=1.5, lead="bar",
             age={"age_fit_lead": 1.0, "age_fit_lead_moe": 0.06,
                  "gap_score_fit": 1.5},
             age_source="sla_composition_v1")
    fit = wx.collect(con, ["MN"])["gaps"]["laundry"]["ageFit"]
    j = {a: i for i, a in enumerate(wx.collect(con, ["MN"])["gaps"]["laundry"]["ids"])}
    assert fit["value"][j["identity"]] == 1.0
    assert fit["moe"][j["identity"]] is None
    assert fit["source"][j["identity"]] is None       # "no curve", not "neutral curve"
    assert fit["value"][j["fitted"]] == 1.0
    assert fit["moe"][j["fitted"]] == 0.06
    assert fit["source"][j["fitted"]] == 0            # a real curve that reads 1.0
