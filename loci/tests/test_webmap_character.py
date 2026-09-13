"""Unit tests for the neighbourhood-character webmap layer (viz/webmap_export.py).

Owner request 2026-09-13: "give color to neighborhoods for whether they are
retail- or corporate-dominated." Four things here are load-bearing and every
one of them fails SILENTLY -- the map still draws, it just draws something
untrue:

  (a) NULL IS A CLASS. An address the character build has not reached has no
      label. If that null is packed as a number it arrives in the browser as 0
      and is drawn as the FIRST label at zero intensity -- a class the address
      was never assigned, on a map whose whole subject is not inventing data.
      The adversarial case is therefore an address MISSING from the character
      detail: it must export as JSON `null`, must not raise, and must reach the
      UI's no-data key.

  (b) THE LEGEND'S THRESHOLDS ARE THE MODEL'S. `character_rules` FORMATS
      model/address_character.py's constants. A retyped "35%" outlives the
      constant it was copied from by exactly one retune, so the test moves the
      constant and requires the legend text to move with it.

  (c) `domShare` HAS NO COLUMN. analysis.nta_character exposes per-label
      shares and a dominant label but no dominant SHARE, so the export derives
      it from the same `shares` dict the popup prints. The headline number and
      the breakdown must come from one place or they will disagree on screen.

  (d) THE LAYER IS CONTEXT, NEVER A FILTER (sql/021 caveat 4). Switching it on
      must not change how many addresses are in a file.

Runs against a scratch in-memory DuckDB built by `loci.db.connect(":memory:")`
so the spatial extension the dissolved NTA outlines need is really there.
"""
from __future__ import annotations

import itertools
import json

import pytest

from loci import db
from loci.model import address_character as acm
from loci.viz import webmap_export as wx

LABELS = list(wx.character_labels())

#: The four `analysis.nta_character` columns the block reads by name, plus the
#: per-label shares and the two mean blocks. Built from the export's own dicts
#: so a rename there cannot pass this fixture by accident.
NTA_COLS = (["nta_code", "borough"]
            + [wx.CHARACTER_NTA_COLUMNS[k] for k in ("n", "dom", "intensity", "ampm", "nAmPm")]
            + [wx.CHARACTER_SHARE_COLUMNS[lab] for lab in LABELS]
            + [wx.CHARACTER_AREA_COLUMNS[k] for k in ("res", "retail", "office", "factory")]
            + [wx.CHARACTER_JOBS_COLUMNS[k] for k in ("retail", "office", "other")]
            + [wx.CHARACTER_RETAIL_NTA_COLUMNS[k]
               for k in ("ri", "riMed", "sup", "ovlBlock", "ovlShare")])


@pytest.fixture()
def con():
    c = db.connect(":memory:")
    c.execute("CREATE SCHEMA analysis;")
    # analysis.hex WITH geometry: the NTA outline is the dissolved H3 cover of
    # it, so a fixture without geom would exercise the degraded path only.
    c.execute("CREATE TABLE analysis.hex (h3_index VARCHAR, geom GEOMETRY, "
              "borough VARCHAR, nta_code VARCHAR)")
    c.execute("CREATE TABLE analysis.address (address_id VARCHAR, borough VARCHAR, "
              "character_radius_m REAL, character_pluto_version VARCHAR, "
              "character_jobs_vintage SMALLINT, character_run_at TIMESTAMP)")
    cols = ", ".join(f"{name} " + ("VARCHAR" if name in
                                   ("nta_code", "borough",
                                    wx.CHARACTER_NTA_COLUMNS["dom"]) else "DOUBLE")
                     for name in NTA_COLS)
    c.execute(f"CREATE TABLE analysis.nta_character ({cols})")
    c.execute("CREATE TABLE analysis.address_character (address_id VARCHAR, "
              "borough VARCHAR, character VARCHAR, character_intensity DOUBLE, "
              "retail_index DOUBLE, commercial_overlay_100m INTEGER, "
              "commercial_overlay_share_400m DOUBLE)")
    return c


def _nta(con, code, dom, shares, *, boro="BK", n=100, intensity=0.5,
         ampm=0.6, n_ampm=40, area=(0.6, 0.1, 0.25, 0.05), jobs=(0.3, 0.5, 0.2),
         ri=0.30, ri_med=0.33, suppressed=False, ovl_block=0.25, ovl_share=0.18):
    """One analysis.nta_character row. `shares` is {label: share}."""
    vals = ([code, boro, n, dom, intensity, ampm, n_ampm]
            + [shares.get(lab, 0.0) for lab in LABELS] + list(area) + list(jobs)
            + [ri, ri_med, suppressed, ovl_block, ovl_share])
    con.execute(f"INSERT INTO analysis.nta_character VALUES "
                f"({', '.join('?' for _ in vals)})", vals)


def _hexes(con, code, lon=-73.94, lat=40.68, boro="Brooklyn", n=3):
    """A little run of real H3 res-9 cells so ST_Union_Agg has something to
    dissolve into one polygon."""
    import h3
    cell = h3.latlng_to_cell(lat, lon, wx.H3_RES)
    for h in [cell] + list(h3.grid_ring(cell, 1))[:n - 1]:
        ring = [(lng, la) for la, lng in h3.cell_to_boundary(h)]
        wkt = "POLYGON((" + ", ".join(f"{x} {y}" for x, y in ring + ring[:1]) + "))"
        con.execute("INSERT INTO analysis.hex VALUES (?, ST_GeomFromText(?), ?, ?)",
                    [h, wkt, boro, code])


def _addr(con, address_id, label, intensity, boro="BK", retail=0.4):
    con.execute("INSERT INTO analysis.address_character VALUES (?, ?, ?, ?, ?, 1, 0.2)",
                [address_id, boro, label, intensity, retail])


# --- the shape of the payload ----------------------------------------------

def test_nta_block_carries_every_field_the_popup_prints(con):
    _nta(con, "BK0101", "corporate",
         {"corporate": 0.62, "retail_mixed": 0.19, "residential": 0.17, "industrial": 0.02},
         area=(0.38, 0.09, 0.48, 0.05), jobs=(0.09, 0.71, 0.20), ampm=0.6, n_ampm=540)
    _hexes(con, "BK0101")
    layer = wx.collect_character(con, ["BK"])
    b = layer["ntas"]["BK0101"]
    assert b["dom"] == "corporate"
    assert set(b["shares"]) == set(LABELS)
    assert b["area"] == {"res": 0.38, "retail": 0.09, "office": 0.48, "factory": 0.05}
    assert b["jobs"] == {"retail": 0.09, "office": 0.71, "other": 0.20}
    assert b["ampm"] == 0.6 and b["nAmPm"] == 540 and b["n"] == 100
    # ...and an outline to paint it with, drawn from analysis.hex.
    assert layer["nShapes"] == 1
    assert layer["shapes"]["features"][0]["properties"] == {
        "nta": "BK0101", "dom": "corporate", "domShare": 0.62, "ri": 0.3, "sup": 0}


def test_shares_are_rounded_to_two_decimals(con):
    """`48%` is a map fact; `0.4812734` is not, and the difference is ~40% of
    the bytes in the block."""
    _nta(con, "BK0101", "residential", {"residential": 0.876543},
         area=(0.123456, 0.1, 0.1, 0.1), jobs=(0.987654, 0.0, 0.0), ampm=0.61234)
    layer = wx.collect_character(con, ["BK"])
    b = layer["ntas"]["BK0101"]
    assert b["shares"]["residential"] == 0.88
    assert b["area"]["res"] == 0.12
    assert b["jobs"]["retail"] == 0.99
    assert b["ampm"] == 0.61


def test_dominant_share_is_read_off_the_same_shares_the_popup_prints(con):
    """analysis.nta_character has no dominant_share column. The headline
    percentage and the breakdown under it must be one number, not two."""
    _nta(con, "BK0101", "retail_mixed",
         {"retail_mixed": 0.44, "residential": 0.40, "corporate": 0.16})
    b = wx.collect_character(con, ["BK"])["ntas"]["BK0101"]
    assert b["domShare"] == b["shares"]["retail_mixed"] == 0.44


def test_a_dominant_label_this_map_cannot_paint_reads_as_no_data(con):
    """A fifth class learned upstream must not be drawn in somebody else's
    colour, and must not index past the end of the palette."""
    _nta(con, "BK0101", "institutional", {"residential": 0.9})
    _hexes(con, "BK0101")
    layer = wx.collect_character(con, ["BK"])
    b = layer["ntas"]["BK0101"]
    assert b["dom"] is None and b["domShare"] is None
    assert layer["counts"]["none"] == 1
    assert layer["shapes"]["features"][0]["properties"]["dom"] is None


# --- the adversarial case: an address with no label ------------------------

def _gap_row(address_id, boro="BK"):
    """One analysis.address_gaps row shaped the way `_gap_sql` returns it:
    head(8) + pipeline(7) + storefront(5) + ranking(6) + censoring(2)."""
    return ([address_id, -73.94, 40.68, boro, 10.0, 2.0, 900.0, "Greenpoint"]
            + [None] * len(wx.PIPELINE_GAP_COLUMNS)
            + [None] * len(wx.STOREFRONT_GAP_COLUMNS)
            + [0.5, "laundry", None, None, None, None] + [None, None])


def test_an_address_with_no_label_packs_as_null_never_as_a_label():
    """The whole failure mode: a null dropped into a numeric stride arrives in
    the browser as 0 and is drawn as LABELS[0]. It has to survive as a null."""
    layer = wx.pack_gaps([_gap_row("a"), _gap_row("b")], ["MN", "BK"], "laundry",
                         character_detail={"a": (0, 81, 55)})
    assert layer["character"]["label"] == [0, None]
    assert layer["character"]["pct"] == [81, None]
    assert layer["character"]["ri"] == [55, None]
    # ...and it has to survive SERIALISATION as a null too.
    round_trip = json.loads(json.dumps(layer))
    assert round_trip["character"]["label"][1] is None
    assert round_trip["character"]["pct"][1] is None


def test_an_export_with_no_character_at_all_still_packs_every_address():
    """A database predating sql/021 exports a column of nulls, not a short
    array the browser would index off the end of."""
    layer = wx.pack_gaps([_gap_row("a"), _gap_row("b")], ["MN", "BK"], "laundry")
    assert layer["character"]["label"] == [None, None]
    assert layer["character"]["ri"] == [None, None]
    assert len(layer["character"]["pct"]) == layer["n"] == 2


def test_character_is_context_and_never_a_filter():
    """sql/021 caveat 4. Switching the layer on must not change which
    addresses are in the file."""
    rows = [_gap_row("a"), _gap_row("b"), _gap_row("c")]
    without = wx.pack_gaps(rows, ["MN", "BK"], "laundry")
    with_ = wx.pack_gaps(rows, ["MN", "BK"], "laundry", character_detail={"a": (2, 40, 12)})
    assert with_["n"] == without["n"] == 3
    assert with_["pts"] == without["pts"]
    assert with_["ids"] == without["ids"]


def test_the_dry_run_counts_the_unlabelled_addresses_off_the_packed_layer():
    """The size of the grey class is the number to look at before shipping: a
    big one means the build has not finished, not that the city has no
    character."""
    gaps = {"laundry": wx.pack_gaps([_gap_row("a"), _gap_row("b"), _gap_row("c")],
                                    ["MN", "BK"], "laundry",
                                    character_detail={"a": (0, 10, 5), "b": (1, 20, 60)})}
    summary = wx.character_summary(wx.empty_character("not built"), gaps)
    assert summary["gapAddressesLabelled"] == 2
    assert summary["gapAddressesUnlabelled"] == 1
    assert summary["available"] is False and summary["reason"] == "not built"


def test_intensity_is_carried_as_an_integer_percent(con):
    """Two decimals on a 0-1 scale is what a tint can honestly show, and the
    integer costs two bytes a point less across sixteen files."""
    _addr(con, "a", LABELS[0], 0.8149, retail=0.4049)
    _addr(con, "b", LABELS[1], 0.0, retail=0.4049)
    _nta(con, "BK0101", LABELS[0], {LABELS[0]: 1.0})      # so the views read as present
    detail = wx.collect_character_detail(con, ["BK"])
    assert detail["a"] == (0, 81, 40)
    # 0.0 is a MEASUREMENT -- an address sitting exactly on its threshold --
    # and must not be collapsed into the no-data case.
    assert detail["b"] == (1, 0, 40)


def test_an_unrun_address_is_absent_from_the_detail_not_present_as_a_default(con):
    _addr(con, "a", None, None)
    _nta(con, "BK0101", LABELS[0], {LABELS[0]: 1.0})
    assert wx.collect_character_detail(con, ["BK"]) == {}


# --- the NTA ("all opportunities") files ------------------------------------

def _nta_gap_row(address_id, code="BK0101"):
    """One `_nta_gap_sql` row: head(9) + pipeline(7) + storefront(5) + 15 ratios."""
    return ([code, "Greenpoint", "BK", address_id, -73.94, 40.68, 10.0, 0.5, "laundry"]
            + [None] * len(wx.PIPELINE_GAP_COLUMNS)
            + [None] * len(wx.STOREFRONT_GAP_COLUMNS)
            + [2.0] + [None] * (len(wx.ALLCATS) - 1))


def test_nta_file_carries_both_the_neighbourhood_block_and_the_address_tint():
    block = {"dom": "corporate", "domShare": 0.62, "n": 2}
    layers = wx.pack_nta([_nta_gap_row("a"), _nta_gap_row("b")], [],
                         character_detail={"a": (0, 55, 71)},
                         character_ntas={"BK0101": block})
    layer = layers["BK0101"]
    assert layer["character"] == block
    assert layer["addressCharacter"]["label"] == [0, None]
    assert layer["addressCharacter"]["pct"] == [55, None]
    assert layer["addressCharacter"]["ri"] == [71, None]
    # The stride is UNTOUCHED: the tint rides in parallel arrays precisely so
    # every existing offset into `pts` keeps meaning what it meant.
    assert layer["stride"] == 14
    assert len(layer["pts"]) == 2 * 14


def test_the_two_character_blocks_in_an_nta_file_stay_distinguishable():
    """An NTA file carries TWO character things: `character`, the
    neighbourhood's own reading (a dict of shares), and `addressCharacter`, the
    per-address parallel arrays. The browser has to tell them apart by shape --
    reading the first as the second is a crash, not a wrong answer, and it was
    a real one. This pins the contract the UI's `charAt` checks."""
    layers = wx.pack_nta([_nta_gap_row("a")], [],
                         character_detail={"a": (1, 30, 90)},
                         character_ntas={"BK0101": {"dom": "industrial",
                                                    "domShare": 0.51, "n": 1}})
    layer = layers["BK0101"]
    assert "label" not in layer["character"]          # the neighbourhood block
    assert isinstance(layer["addressCharacter"]["label"], list)   # the address block
    assert isinstance(layer["addressCharacter"]["pct"], list)
    # ...and the per-category gap files use the OTHER name for the address
    # block, which is why the accessor tries `addressCharacter` first.
    gap = wx.pack_gaps([_gap_row("a")], ["MN", "BK"], "laundry",
                       character_detail={"a": (1, 30, 90)})
    assert "addressCharacter" not in gap
    assert isinstance(gap["character"]["label"], list)


def test_an_nta_the_character_build_never_reached_carries_a_null_block():
    layers = wx.pack_nta([_nta_gap_row("a")], [], character_ntas={})
    assert layers["BK0101"]["character"] is None
    assert layers["BK0101"]["addressCharacter"]["label"] == [None]


def test_the_neighbourhood_index_carries_only_the_dominant_label():
    """The index is the SMALL file the picker reads; the four shares belong in
    the file it opens next."""
    layers = wx.pack_nta([_nta_gap_row("a")], [],
                         character_ntas={"BK0101": {"dom": "industrial",
                                                    "domShare": 0.51, "n": 1}})
    row = wx.nta_index(layers, ["BK"], "principled", "abc")["ntas"][0]
    assert row["char"] == "industrial" and row["charShare"] == 0.51
    assert "shares" not in row


# --- the legend comes from the model ----------------------------------------

def test_legend_rules_are_formatted_from_the_model_constants(monkeypatch):
    """Move the constant; the legend must move with it. This is the check that
    makes "pulled from the model, not retyped" true rather than aspirational."""
    before = wx.character_rules()["corporate"]
    assert f"{round(acm.CORPORATE_OFFICE_AREA_SHARE * 100)}%" in before
    monkeypatch.setattr(acm, "CORPORATE_OFFICE_AREA_SHARE", 0.42)
    after = wx.character_rules()["corporate"]
    assert "42%" in after and after != before


def test_every_label_the_model_emits_has_a_colour_and_a_name():
    labels = set(wx.character_labels())
    assert labels == set(acm.LABEL_ORDER)
    assert labels <= set(wx.CHARACTER_COLORS)
    assert labels <= set(wx.CHARACTER_COLORS_DARK)
    assert labels <= set(wx.CHARACTER_LABEL_TEXT)
    assert labels <= set(wx.CHARACTER_SHARE_COLUMNS)
    assert wx.character_label_drift() is None


def test_a_class_the_palette_cannot_paint_disables_the_whole_layer(con, monkeypatch):
    """Better a hidden toggle than four colours quietly standing for five
    classes."""
    _nta(con, "BK0101", "corporate", {"corporate": 1.0})
    monkeypatch.setattr(acm, "LABEL_ORDER", tuple(acm.LABEL_ORDER) + ("institutional",))
    layer = wx.collect_character(con, ["BK"])
    assert layer["available"] is False
    assert "institutional" in layer["reason"]


def test_the_character_palette_is_not_a_category_colour():
    """The fifteen category dots are drawn ON TOP of these areas. Exact reuse
    of one of their hues would make an area read as a business."""
    assert not (set(wx.CHARACTER_COLORS.values()) & set(wx.COLORS.values()))
    assert wx.CHARACTER_NODATA_COLOR not in set(wx.COLORS.values())


# --- degradation -------------------------------------------------------------

def test_a_database_without_the_views_degrades_to_an_unavailable_layer():
    c = db.connect(":memory:")
    c.execute("CREATE SCHEMA analysis;")
    layer = wx.collect_character(c, ["BK"])
    assert layer["available"] is False
    assert "address_character" in layer["reason"]
    # The legend still ships, so the UI can say WHY the toggle is off.
    assert layer["rules"] and layer["colors"] and layer["caveat"]
    assert layer["shapes"] == {"type": "FeatureCollection", "features": []}


def test_a_missing_column_is_named_rather_than_raised(con):
    con.execute(f"ALTER TABLE analysis.nta_character "
                f"DROP COLUMN {wx.CHARACTER_JOBS_COLUMNS['office']}")
    layer = wx.collect_character(con, ["BK"])
    assert layer["available"] is False
    assert wx.CHARACTER_JOBS_COLUMNS["office"] in layer["reason"]


def test_an_nta_with_no_character_row_gets_no_polygon(con):
    """A grey polygon over a neighbourhood the roll-up has never seen would be
    a claim; an absent polygon is the truth."""
    _nta(con, "BK0101", "residential", {"residential": 1.0})
    _hexes(con, "BK0101")
    _hexes(con, "BK9999", lon=-73.99, lat=40.70)
    layer = wx.collect_character(con, ["BK"])
    assert [f["properties"]["nta"] for f in layer["shapes"]["features"]] == ["BK0101"]


def test_provenance_carries_the_vintages_the_legend_must_print(con):
    con.execute("INSERT INTO analysis.address VALUES "
                "('a', 'BK', 400, '24v4', 2023, now()), "
                "('b', 'BK', NULL, NULL, NULL, NULL)")
    prov = wx.character_provenance(con, ["BK"])
    assert prov["radiusM"] == 400
    assert prov["plutoVersion"] == "24v4"
    assert prov["jobsVintage"] == 2023
    # The addresses the build never reached are COUNTED, not hidden.
    assert prov["unrunAddresses"] == 1


# --- the continuous ramp (urban-planner review, 2026-09-13) ------------------

def test_the_ramp_is_the_default_and_carries_its_own_domain(con):
    """Under the four labels Brooklyn is ~90% residential, so the categorical
    map is a monochrome. The fill is `retail_index`, and the legend's ends are
    the DATA's ends -- a hard-coded 0..1 would wash out every neighbourhood if
    the index never approaches 1."""
    _nta(con, "BK0101", "residential", {"residential": 0.9}, ri=0.11)
    _nta(con, "BK0102", "retail_mixed", {"retail_mixed": 0.6}, ri=0.64)
    layer = wx.collect_character(con, ["BK"])
    assert layer["ramp"] is True and layer["rampReason"] is None
    assert layer["riRange"] == [0.11, 0.64]
    assert layer["rampColors"] == list(wx.CHARACTER_RAMP)
    assert layer["ntas"]["BK0102"]["ri"] == 0.64


def test_the_ramp_is_one_hue_light_to_dark():
    """Sequential encodes MAGNITUDE, so it is one hue with monotone lightness.
    A second hue anywhere in the ramp turns "how much" back into "which kind"."""
    import colorsys

    def hsl(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hue, light, _sat = colorsys.rgb_to_hls(r, g, b)
        return hue * 360, light

    steps = [hsl(c) for c in wx.CHARACTER_RAMP]
    lights = [s[1] for s in steps]
    assert lights == sorted(lights, reverse=True)          # light -> dark
    hues = [s[0] for s in steps]
    assert max(hues) - min(hues) < 20                      # one hue family


def test_a_database_without_retail_index_still_exports_the_labels(con):
    """The labels shipped first and `retail_index` follows. Between those two
    exports the map draws the four-class fill and SAYS so -- it does not go
    dark, and it does not draw an empty ramp."""
    _nta(con, "BK0101", "residential", {"residential": 1.0})
    con.execute(f"ALTER TABLE analysis.nta_character "
                f"DROP COLUMN {wx.CHARACTER_RETAIL_NTA_COLUMNS['ri']}")
    layer = wx.collect_character(con, ["BK"])
    assert layer["available"] is True          # the layer still works
    assert layer["ramp"] is False              # ...but not as a ramp
    assert wx.CHARACTER_RETAIL_NTA_COLUMNS["ri"] in layer["rampReason"]
    assert layer["ntas"]["BK0101"]["ri"] is None


def test_a_suppressed_neighbourhood_is_drawn_as_no_data_not_as_zero_retail(con):
    """A retail index over eleven addresses in a cemetery is a number, not a
    reading -- and on a light-to-dark ramp it would draw as the palest, most
    confident "no retail here" polygon on the map."""
    _nta(con, "BK0801", "residential", {"residential": 1.0}, ri=0.02, suppressed=True)
    _nta(con, "BK0101", "residential", {"residential": 1.0}, ri=0.30)
    _hexes(con, "BK0801")
    _hexes(con, "BK0101", lon=-73.99, lat=40.70)
    layer = wx.collect_character(con, ["BK"])
    assert layer["suppressed"] == 1
    props = {f["properties"]["nta"]: f["properties"] for f in layer["shapes"]["features"]}
    assert props["BK0801"]["sup"] == 1 and props["BK0801"]["ri"] is None
    assert props["BK0101"]["sup"] == 0 and props["BK0101"]["ri"] == 0.30
    # ...and a suppressed NTA must not stretch the legend's domain either.
    assert layer["riRange"] == [0.30, 0.30]


def test_the_two_sparse_classes_are_overlays_not_ramp_steps(con):
    """`corporate` and `industrial` are not "more retail" or "less retail", so
    they cannot be positions on a retail ramp. They ride as categorical
    overlays with their own hue and their own texture."""
    _nta(con, "MN0101", "corporate", {"corporate": 0.7}, ri=0.20, boro="MN")
    _hexes(con, "MN0101", lon=-73.9857, lat=40.7484, boro="Manhattan")
    layer = wx.collect_character(con, ["MN"])
    assert layer["overlayLabels"] == ["corporate", "industrial"]
    # The overlay hues must not be steps of the ramp they sit on.
    assert not ({wx.CHARACTER_COLORS[lab] for lab in layer["overlayLabels"]}
                & set(wx.CHARACTER_RAMP))
    # ...and the polygon still carries its retail index underneath, so the
    # hatch is an annotation on the ramp rather than a hole in it.
    assert layer["ntas"]["MN0101"]["ri"] == 0.20
    props = layer["shapes"]["features"][0]["properties"]
    assert props["dom"] == "corporate" and props["ri"] == 0.20


def test_corporate_is_renamed_by_the_model_never_by_this_module():
    """`corporate` is what the RULE computes; it is not what a reader should be
    told, because the label's plain-English reading ("nobody lives here, don't
    open a laundromat") is the opposite of what the data says. The wording and
    the sentence that must travel with it are the model's
    (CHARACTER_COPY / CHARACTER_CAVEAT), so a card and a map legend cannot
    drift apart."""
    copy = wx.character_copy()
    assert copy["corporate"]["text"] == acm.CHARACTER_COPY["corporate"]
    assert copy["corporate"]["caveat"] == acm.CHARACTER_CAVEAT["corporate"]
    # ...and the legend gets a capitalised form of the same phrase, not a
    # second string somebody has to keep in sync.
    assert copy["corporate"]["title"].lower() == copy["corporate"]["text"].lower()
    assert set(copy) == set(wx.character_labels())


def test_moving_the_copy_constant_moves_the_legend(monkeypatch):
    monkeypatch.setattr(acm, "CHARACTER_COPY",
                        dict(acm.CHARACTER_COPY, corporate="desk-work district"))
    assert wx.character_copy()["corporate"]["text"] == "desk-work district"


def test_a_label_the_copy_says_nothing_about_still_gets_a_name(monkeypatch):
    """A checkout whose model predates the copy constant must still draw a
    legend -- with the plain display name, never a blank key."""
    monkeypatch.setattr(acm, "CHARACTER_COPY", {}, raising=False)
    monkeypatch.setattr(acm, "CHARACTER_CAVEAT", {}, raising=False)
    copy = wx.character_copy()
    assert copy["residential"]["text"] == wx.CHARACTER_LABEL_TEXT["residential"]
    assert copy["residential"]["caveat"] is None


def test_copy_accepts_either_shape_the_model_may_use(monkeypatch):
    """Flat `{label: "text"}` today, `{label: {"text":..., "caveat":...}}` if the
    model ever folds the two dicts together. A legend that crashed on a
    constant's SHAPE would be a worse failure than one that read a bare
    string."""
    monkeypatch.setattr(acm, "CHARACTER_COPY",
                        {"corporate": {"text": "weekday-office catchment",
                                       "caveat": "a daytime reading"}})
    monkeypatch.setattr(acm, "CHARACTER_CAVEAT", {}, raising=False)
    assert wx.character_copy()["corporate"] == {
        "text": "weekday-office catchment", "title": "Weekday-office catchment",
        "caveat": "a daytime reading"}


def test_the_commercial_overlay_reading_rides_beside_the_index(con):
    """Zoning PERMITS a storefront; the index is what one IS. The popup prints
    both so a reader can see them disagree."""
    _nta(con, "BK0101", "residential", {"residential": 1.0},
         ovl_block=0.3349, ovl_share=0.2149)
    b = wx.collect_character(con, ["BK"])["ntas"]["BK0101"]
    assert b["ovlBlock"] == 0.33
    assert b["ovlShare"] == 0.21


def test_the_address_tint_carries_the_index_as_well_as_the_label(con):
    """The dots are tinted by the INDEX once the ramp is the default view, but
    the four-class label stays in the payload because the recommendation card
    reads the label, not the index."""
    _addr(con, "a", LABELS[0], 0.5, retail=0.6666)
    _nta(con, "BK0101", LABELS[0], {LABELS[0]: 1.0})
    layer = wx.pack_gaps([_gap_row("a")], ["MN", "BK"], "laundry",
                         character_detail=wx.collect_character_detail(con, ["BK"]))
    assert layer["character"]["label"] == [0]
    assert layer["character"]["ri"] == [67]


def test_the_shade_is_the_mean_not_the_median(con):
    """`retail_index` is per address a capped MAX over three witnesses, so at
    the NTA MEDIAN 52% of live MN+BK neighbourhoods saturate at exactly 1.00 --
    a light-to-dark ramp on that is a dark monochrome, which is the same
    failure the four-class map had at the other end of the scale. The mean of
    the same index keeps the spread. Both ship; the fill reads the mean."""
    assert wx.CHARACTER_RETAIL_NTA_COLUMNS["ri"] == "mean_retail_index"
    assert wx.CHARACTER_RETAIL_NTA_COLUMNS["riMed"] == "med_retail_index"
    _nta(con, "BK0101", "retail_mixed", {"retail_mixed": 0.7}, ri=0.55, ri_med=1.0)
    _hexes(con, "BK0101")
    layer = wx.collect_character(con, ["BK"])
    assert layer["ntas"]["BK0101"]["ri"] == 0.55       # the mean drives the fill
    assert layer["ntas"]["BK0101"]["riMed"] == 1.0     # the median still ships
    assert layer["shapes"]["features"][0]["properties"]["ri"] == 0.55


# --- the quantile stretch (the index saturates) ------------------------------

def test_the_ramp_stops_are_quantiles_not_even_spacing():
    """`retail_index` is a capped MAX over three witnesses, so it saturates:
    Manhattan below 96th St sits at a p50 of 1.0 and Brooklyn at 0.68. An
    evenly-spaced ramp spends most of its resolution on a range almost nothing
    occupies and crushes the 0.5-1.0 band the whole city lives in."""
    # 70% of the mass at the top, exactly the real shape.
    vals = [0.30, 0.45, 0.55] + [0.90 + i * 0.001 for i in range(7)]
    stops = wx.quantile_stops(vals, len(wx.CHARACTER_RAMP))
    assert len(stops) == len(wx.CHARACTER_RAMP)
    assert stops == sorted(stops)
    # An even ramp would put three of six stops below 0.6; the quantile ramp
    # puts the resolution where the neighbourhoods actually are.
    assert sum(1 for v in stops if v >= 0.85) >= 3
    assert stops[0] == min(vals) and stops[-1] == max(vals)


def test_stops_are_strictly_increasing_even_when_the_index_is_saturated():
    """MapLibre's `interpolate` rejects a repeated stop, and a fully saturated
    tail produces plenty of them — which is exactly the case this ramp exists
    to survive."""
    stops = wx.quantile_stops([1.0] * 40 + [0.3, 0.5], len(wx.CHARACTER_RAMP))
    assert all(b > a for a, b in itertools.pairwise(stops))
    assert len(stops) == len(wx.CHARACTER_RAMP)


def test_no_values_means_no_stops_rather_than_a_fabricated_scale():
    assert wx.quantile_stops([], 6) == []
    assert wx.quantile_stops([0.4], 2) == [0.4, 0.4001]


def test_the_exported_stops_cover_the_exported_range(con):
    _nta(con, "BK0101", "retail_mixed", {"retail_mixed": 1.0}, ri=0.32)
    _nta(con, "BK0102", "retail_mixed", {"retail_mixed": 1.0}, ri=0.90)
    _nta(con, "BK0103", "residential", {"residential": 1.0}, ri=0.95)
    layer = wx.collect_character(con, ["BK"])
    assert layer["riScale"] == "quantile"
    assert layer["riStops"][0] == layer["riRange"][0]
    assert layer["riStops"][-1] >= layer["riRange"][1]
    assert len(layer["riStops"]) == len(wx.CHARACTER_RAMP)


# --- suppressed rows are EMITTED with NULL shares, not dropped ---------------

def test_a_suppressed_row_with_null_shares_does_not_crash_and_draws_as_no_data(con):
    """The model EMITS suppressed NTAs (parks, cemeteries, airports, and any
    NTA under its address floor) with NULL shares rather than dropping them --
    so the export has to tolerate a row that is almost entirely null, and the
    map has to draw it as no-data rather than as the palest, most confident
    "no retail anywhere" polygon on the scale."""
    nulls = [None] * len(LABELS)
    vals = (["BK0261", "BK", 11, None, None, None, 0] + nulls
            + [None] * 4 + [None] * 3 + [None, None, True, None, None])
    con.execute(f"INSERT INTO analysis.nta_character VALUES "
                f"({', '.join('?' for _ in vals)})", vals)
    _nta(con, "BK0101", "residential", {"residential": 1.0}, ri=0.40)
    _hexes(con, "BK0261")
    _hexes(con, "BK0101", lon=-73.99, lat=40.70)
    layer = wx.collect_character(con, ["BK"])

    b = layer["ntas"]["BK0261"]
    assert b["sup"] is True
    assert b["dom"] is None and b["domShare"] is None
    assert b["ri"] is None and b["riMed"] is None
    assert set(b["shares"].values()) == {None}
    assert set(b["area"].values()) == {None} and set(b["jobs"].values()) == {None}
    # The polygon still ships -- a hole in the map would read as "no
    # neighborhood here" -- but it carries no index for the ramp to shade.
    props = {f["properties"]["nta"]: f["properties"] for f in layer["shapes"]["features"]}
    assert props["BK0261"] == {"nta": "BK0261", "dom": None, "domShare": None,
                               "ri": None, "sup": 1}
    # ...and it must not stretch the scale the live neighbourhoods are ranked on.
    assert layer["riRange"] == [0.40, 0.40]
    assert layer["counts"]["none"] == 1 and layer["suppressed"] == 1
    # The whole file still serialises -- nulls, not NaNs.
    assert json.loads(json.dumps(layer))["ntas"]["BK0261"]["ri"] is None
