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

import json

import h3
import pytest

from loci import db
from loci.viz import webmap_export as wx

# Three real NYC points, one per borough, so the h3 -> analysis.hex join has
# something true to resolve against.
PLACES = {
    "MN": (-73.9857, 40.7484),   # Empire State Building
    "BK": (-73.9442, 40.6782),   # central Brooklyn
    "QN": (-73.7949, 40.7282),   # central Queens
}


@pytest.fixture()
def con():
    c = db.connect(":memory:")
    c.execute("CREATE SCHEMA staging; CREATE SCHEMA analysis;")
    # Column subset of the real staging.poi (sql/002_schema.sql), in the real
    # relative order. `source_record_id` and `attrs` are here because the
    # restaurant detail rides in them -- a fixture missing them would let the
    # detail query break against a green test suite. `tier` is here because
    # analysis.poi_supply selects it.
    c.execute("""CREATE TABLE staging.poi (
        poi_id VARCHAR, source_id VARCHAR, source_record_id VARCHAR,
        category VARCHAR, tier SMALLINT, name VARCHAR, geom GEOMETRY, attrs JSON)""")
    c.execute("CREATE TABLE analysis.poi_dedup (poi_id VARCHAR, cluster_id BIGINT, "
              "is_canonical BOOLEAN, category VARCHAR)")
    c.execute("CREATE TABLE analysis.hex (h3_index VARCHAR, borough VARCHAR, nta_code VARCHAR)")
    cols = ", ".join(f"{cat}_ratio FLOAT, {cat}_nearest_m FLOAT" for cat in wx.ALLCATS)
    c.execute(f"""CREATE TABLE analysis.address_gaps (
        address_id VARCHAR, lon DOUBLE, lat DOUBLE, borough VARCHAR,
        units_capped FLOAT, neighborhood VARCHAR, eligible BOOLEAN, {cols})""")
    # The REAL supply-set definitions, not a restatement of them: 006 also
    # creates analysis.category_anchor and adds address_gaps.supply_set /
    # supply_hash, which is where the provenance check reads from.
    for name in ("003_supply_sets.sql", "006_principled_supply.sql"):
        c.execute((db.SQL_DIR / name).read_text())
    for code, (lon, lat) in PLACES.items():
        c.execute("INSERT INTO analysis.hex VALUES (?, ?, ?)",
                  [h3.latlng_to_cell(lat, lon, wx.H3_RES), wx.BOROUGH_NAMES[code], code + "0001"])
    return c


def _add_poi(con, poi_id, source, cluster, boro, canonical=True, cat="laundry",
             name="Suds", record_id=None, attrs=None):
    lon, lat = PLACES[boro]
    con.execute("INSERT INTO staging.poi VALUES (?, ?, ?, ?, ?, ?, ST_Point(?, ?), ?)",
                [poi_id, source, record_id, cat, 1, name, lon, lat,
                 None if attrs is None else json.dumps(attrs)])
    con.execute("INSERT INTO analysis.poi_dedup VALUES (?, ?, ?, ?)",
                [poi_id, cluster, canonical, cat])


def _anchor(con, cat, qualifies=True):
    """Mark a category as having a registry anchor dense enough to veto an
    uncorroborated aggregator record -- what score/supply.build_category_anchor
    measures. Only an ANCHORED category can exclude anything: for an unanchored
    one PRINCIPLED is ALL by construction (sql/006)."""
    con.execute("INSERT INTO analysis.category_anchor VALUES "
                "(?, 'nyc_dohmh_restaurants', 100, 100, 5, 1.0, 0.7, ?, 2023, "
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


def _add_gap(con, address_id, boro, cat="laundry", ratio=2.0, eligible=True):
    # Columns are named, not positional: sql/006 ALTERs supply_set/supply_hash
    # onto this table, and a positional INSERT would break every time a
    # migration adds a column.
    ratios = {c: (ratio if c == cat else 0.5) for c in wx.ALLCATS}
    lon, lat = PLACES[boro]
    cols = ["address_id", "lon", "lat", "borough", "units_capped", "neighborhood", "eligible"]
    vals = [address_id, lon, lat, boro, 10.0, "Somewhere", eligible]
    for c in wx.ALLCATS:
        cols += [f"{c}_ratio", f"{c}_nearest_m"]
        vals += [ratios[c], 100.0]
    con.execute(f"INSERT INTO analysis.address_gaps ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(vals))})", vals)


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


def test_gap_layer_uses_ratio_and_eligibility(con):
    """A gap point is an ELIGIBLE address whose category ratio exceeds 1 --
    model/address_gaps.py's own n_missing definition. Ineligible addresses and
    ratio <= 1 addresses are not gaps."""
    _add_gap(con, "gap", "MN", ratio=1.4)
    _add_gap(con, "reached", "MN", ratio=0.9)
    _add_gap(con, "ineligible", "MN", ratio=3.0, eligible=False)

    bundle = wx.collect(con, ["MN"])
    assert bundle["gaps"]["laundry"]["ids"] == ["gap"]
    # The same address is not a gap for a category it can reach.
    assert bundle["gaps"]["grocery"]["ids"] == []


def test_write_emits_one_file_per_category_per_layer(con, tmp_path):
    """One gaps file and one pois file per category, plus exactly two
    non-category files: meta.json and the alcohol overlay. The overlay is
    counted here on purpose -- it is a STANDALONE layer, so if it ever became a
    16th category this count would move and the test would say so."""
    _add_poi(con, "a", "overture_places", 1, "MN")
    _add_gap(con, "addr_mn", "MN")
    written = wx.write(wx.collect(con, ["MN", "BK"]), tmp_path)

    # gaps + pois, then meta.json and alcohol.json.
    assert set(written) == (
        {f"gaps/{c}.json" for c in wx.ALLCATS}
        | {f"pois/{c}.json" for c in wx.ALLCATS}
        | {"meta.json", "alcohol.json"})
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
