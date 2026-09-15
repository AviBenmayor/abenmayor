"""Cross-category dedup (owner rulings 2026-09-14; GTM-153).

Two rulings are pinned here.

RULING 4 -- run a cross-category name+distance pass BEFORE the per-category
one. The motivating case is Lion's Milk at 104 Roebling: DOHMH files it as a
`restaurant` (it holds a food-service permit), Overture as a `cafe_bakery`
(what it looks like from the sidewalk), 12 m apart, both open -- and before
this rule the two rows were never in the same call to the deduper, so one cafe
was counted twice in the supply pool.

RULING "go with B" -- the merged cluster carries the FINER food category, not
the anchor's. DOHMH cannot tell a cafe from a diner; its label is a permit
class, so the registry's authority over EXISTENCE does not extend to taxonomy.

Every test here pins a clause that, if it silently flipped, would either
resurrect the double-count or start fusing separate storefronts (the
fake-retail-gap failure `score/dedup.py` exists to avoid).
"""
import pytest

from loci.score.dedup import (
    _dedup_all, _dedup_category, cross_category_names_match,
    cross_category_names_match_raw, cross_core, venue_words,
)


def _row(pid, source, name, cat, lat, lon, conf=0.7):
    return {"poi_id": f"{source}:{pid}", "source_id": source, "name": name,
            "category": cat, "confidence": conf, "lat": lat, "lon": lon}


# Lion's Milk, 104 Roebling St, Williamsburg -- the real poi_ids, names and
# coordinates out of staging.poi. 12 m apart; note the two feeds even disagree
# about the capital S, which is why the comparison is on normalized tokens.
LIONS_MILK_DOHMH = _row("50043137", "nyc_dohmh_restaurants", "Lion'S Milk",
                        "restaurant", 40.715826, -73.955652, conf=0.95)
LIONS_MILK_OVERTURE = _row("41c0fc63-fe42-4704-8215-133e2db67a98",
                           "overture_places", "Lion's Milk", "cafe_bakery",
                           40.715887, -73.955777)


def _by_pid(out):
    return {pid: (cid, canon, cat) for pid, cid, canon, cat in out}


# --------------------------------------------------------------- the merge

def test_lions_milk_merges_into_one_cluster_labelled_by_the_finer_category():
    """Ruling 4 + ruling B in one assertion. One cluster; the DOHMH row is
    canonical (source authority over existence); the LABEL is the aggregator's
    finer `cafe_bakery` (ruling B)."""
    out = _by_pid(_dedup_all([LIONS_MILK_DOHMH, LIONS_MILK_OVERTURE]))
    dohmh = out["nyc_dohmh_restaurants:50043137"]
    overture = out["overture_places:41c0fc63-fe42-4704-8215-133e2db67a98"]
    assert dohmh[0] == overture[0], "one business, one cluster"
    assert dohmh[1] is True and overture[1] is False
    assert dohmh[2] == overture[2] == "cafe_bakery"


def test_variant_a_is_one_constant_away_and_still_labels_it_restaurant():
    """The rollback path. Variant A takes the canonical member's own category,
    so the same cluster reads `restaurant`; membership and the canonical pick
    are identical under both."""
    out = _by_pid(_dedup_all([LIONS_MILK_DOHMH, LIONS_MILK_OVERTURE],
                             precedence="anchor"))
    dohmh = out["nyc_dohmh_restaurants:50043137"]
    assert dohmh[1] is True
    assert dohmh[2] == "restaurant"


def test_the_old_per_category_pass_still_counts_lions_milk_twice():
    """The BEFORE side, so a regression that silently disables the new pass is
    visible as a test failure and not as a quiet doubling of cafe supply."""
    out = _dedup_category([LIONS_MILK_DOHMH, LIONS_MILK_OVERTURE])
    assert len({cid for _, cid, _ in out}) == 2


def test_a_bar_and_its_restaurant_permit_land_on_bar_whoever_wins_canonical():
    """SLA and DOHMH are BOTH rank 0 -- each is the anchor of its own category
    -- so a bar+restaurant cluster ties on source authority and the canonical
    member is decided by confidence. Under ruling B the LABEL is `bar` either
    way, which is the point: the outcome no longer depends on a tiebreak."""
    sla = _row("0267-24-102259", "nys_sla_liquor_licenses", "The Hairy Lemon",
               "bar", 40.700000, -73.900000, conf=0.9)
    dohmh = _row("50187235", "nyc_dohmh_restaurants", "The Hairy Lemon",
                 "restaurant", 40.700030, -73.900000, conf=0.8)
    out = _by_pid(_dedup_all([sla, dohmh]))
    assert out[sla["poi_id"]][0] == out[dohmh["poi_id"]][0]
    assert out[sla["poi_id"]][1] is True                    # SLA wins on conf
    assert {v[2] for v in out.values()} == {"bar"}

    flipped = _by_pid(_dedup_all([{**sla, "confidence": 0.5}, dohmh]))
    assert flipped[dohmh["poi_id"]][1] is True              # DOHMH wins on conf
    assert {v[2] for v in flipped.values()} == {"bar"}


def test_a_restaurant_only_cluster_keeps_restaurant():
    """Ruling B moves a label only when a finer-food member exists. Two
    restaurant rows stay `restaurant`, so the vast majority of food clusters
    are untouched and their ledger keys do not move."""
    a = _row("50043137", "nyc_dohmh_restaurants", "Tom's Diner", "restaurant",
             40.700000, -73.900000, conf=0.95)
    b = _row("f1", "foursquare_os_places", "Tom's Diner", "restaurant",
             40.700030, -73.900000)
    out = _by_pid(_dedup_all([a, b]))
    assert {v[2] for v in out.values()} == {"restaurant"}


def test_unknown_precedence_raises_rather_than_defaulting():
    with pytest.raises(ValueError):
        _dedup_all([LIONS_MILK_DOHMH, LIONS_MILK_OVERTURE], precedence="whatever")


# ------------------------------------------------------------- the negatives

def test_same_name_different_category_at_60m_does_not_merge():
    """MATCH_METERS is unchanged at 40 m for both passes. The audit measured
    why a TIGHTER cross-category cap was not adopted either: true merges run to
    a p90 of 27 m, so a 20-25 m cap costs ~10 points of recall and buys no
    precision once the name rule is equality-based."""
    a = _row("a", "overture_places", "Ceremony Coffee", "cafe_bakery",
             40.700000, -73.900000)
    b = _row("b", "foursquare_os_places", "Ceremony Coffee", "restaurant",
             40.700000, -73.900711)          # ~60 m
    out = _by_pid(_dedup_all([a, b]))
    assert out[a["poi_id"]][0] != out[b["poi_id"]][0]


def test_different_names_at_the_same_coordinate_do_not_merge():
    """Nothing in this rule is name-blind. Two tenants at one geocode -- a bar
    upstairs and a barber downstairs, or a fallback centroid -- stay two."""
    a = _row("a", "overture_places", "Ravenwood Apothecary", "pharmacy",
             40.700000, -73.900000)
    b = _row("b", "foursquare_os_places", "Kettlebridge Fitness", "fitness",
             40.700000, -73.900000)
    out = _by_pid(_dedup_all([a, b]))
    assert out[a["poi_id"]][0] != out[b["poi_id"]][0]


def test_same_source_cross_category_does_not_merge_by_default():
    """One feed listing two categories at one address is as likely to be two
    tenants sharing a brand as one venue filed twice. 1,741 such pairs exist on
    the live table; the default is cross-source only, one flag away."""
    a = _row("a", "overture_places", "Kettlebridge Provisions", "grocery",
             40.700000, -73.900000)
    b = _row("b", "overture_places", "Kettlebridge Provisions", "convenience",
             40.700050, -73.900000)          # ~5.5 m
    out = _by_pid(_dedup_all([a, b]))
    assert out[a["poi_id"]][0] != out[b["poi_id"]][0]
    on = _by_pid(_dedup_all([a, b], cross_category_same_source=True))
    assert on[a["poi_id"]][0] == on[b["poi_id"]][0]


# ------------------------------------------------ the calibrated name rule

def test_the_core_must_be_EQUAL_not_merely_overlapping():
    """The first cut used `names_match` (Jaccard >= 0.5, or containment of a
    2-token name) and audited at 0.870 precision -- ~2,300 wrong merges on the
    live table. Containment is what admitted "Hudson Yards Grill" into "Mount
    Sinai Hudson Yards"; a 0.5 Jaccard is what admitted "Big Red Lantern" into
    "New Red Lantern". Equality refuses both."""
    assert not cross_category_names_match_raw("Hudson Yards Grill",
                                              "Mount Sinai Hudson Yards")
    assert not cross_category_names_match_raw("Big Red Lantern",
                                              "New Red Lantern Inc")
    assert not cross_category_names_match_raw("Fulton Stall Market", "The Fulton")
    assert not cross_category_names_match_raw("Inwood Nail", "Inwood Local")
    assert not cross_category_names_match_raw("Bushwick Minimart Inc.",
                                              "Bushwick Grocery Food Corp")
    # ...while the true merges the audit found all survive
    assert cross_category_names_match_raw("Lion'S Milk", "Lion's Milk")
    assert cross_category_names_match_raw("Soneros", "Soneros Bar Restaurant Inc")
    assert cross_category_names_match_raw("B66 Club", "B66")
    assert cross_category_names_match_raw("Corner Bistro", "Corner Bistro")


def test_disjoint_category_words_veto_the_merge():
    """One brand word under two different trade words is two businesses -- an
    extremely common NYC naming pattern. The words the core strip discards are
    the only evidence that separates them, so they are read back."""
    assert cross_core("Totowa Food") == cross_core("Totowa Nails") == {"totowa"}
    assert venue_words("Totowa Food") == {"food"}
    assert venue_words("Totowa Nails") == {"nails"}
    assert not cross_category_names_match_raw("Totowa Food", "Totowa Nails")
    assert not cross_category_names_match_raw("CLAIRE'S WINE BAR",
                                              "Claire's Kitchen Cafe")
    assert not cross_category_names_match_raw("Brooklyn Bagels", "Brooklyn Cleaners")
    # one side carrying no trade word at all is not a contradiction
    assert cross_category_names_match_raw("Tabu", "tabu cafe & wine")
    # nor is an overlapping one
    assert cross_category_names_match_raw("Ostro Cafe", "Ostro Cafe")


def test_the_veto_blocks_a_pair_the_looser_rule_would_have_merged():
    """End to end, not just on the predicate: 5.5 m apart, one shared
    distinctive token, contradicting trade words -> two clusters."""
    a = _row("a", "overture_places", "Roebling Cafe", "cafe_bakery",
             40.700000, -73.900000)
    b = _row("b", "nyc_dohmh_restaurants", "Roebling Kitchen", "restaurant",
             40.700050, -73.900000, conf=0.95)
    out = _by_pid(_dedup_all([a, b]))
    assert out[a["poi_id"]][0] != out[b["poi_id"]][0]


def test_venue_words_are_stripped_from_the_core_so_a_bar_matches_its_kitchen():
    """bar<->restaurant is the largest cross-category merge class, and it is
    where one feed writes "X Tavern" and the other writes "X"."""
    assert cross_core("The Hairy Lemon") == cross_core("The Hairy Lemon Pub")
    assert cross_category_names_match_raw("Sundays Well", "Sundays Well Bar & Lounge")


def test_an_empty_core_can_never_merge_anything():
    """A wholly generic name ("Deli", "Pharmacy") strips to nothing, and two
    nothings must not be equal-and-merged. Same reason `names_match` refuses an
    empty token set."""
    assert cross_core("Deli") == frozenset()
    assert not cross_category_names_match_raw("Deli", "Pharmacy")
    assert not cross_category_names_match_raw("Restaurant", "Bar")
    assert not cross_category_names_match(frozenset(), frozenset())


# -------------------------------------------------- canonical-member stability

def test_absorbing_a_cross_category_duplicate_keeps_the_existing_canonical():
    """LEDGER KEY STABILITY (sql/018). A cluster that already existed must not
    change which member is canonical when it absorbs a cross-category
    duplicate. Under variant A that leaves the key untouched; under the ruling
    B default the key still moves because the LABEL moves, which is the
    migration cost the dry run counts."""
    pre = [
        _row("d1", "nyc_dohmh_restaurants", "Lion'S Milk", "restaurant",
             40.715826, -73.955652, conf=0.95),
        _row("f1", "foursquare_os_places", "Lion's Milk", "restaurant",
             40.715830, -73.955660),
    ]
    before = _by_pid(_dedup_all(pre, cross_category=False))
    canon_before = [pid for pid, (_, c, _) in before.items() if c]
    assert canon_before == ["nyc_dohmh_restaurants:d1"]

    after = _by_pid(_dedup_all([*pre, LIONS_MILK_OVERTURE]))
    canon_after = [pid for pid, (_, c, _) in after.items() if c]
    assert canon_after == canon_before, "the absorbed duplicate must not take over"
    assert len({cid for cid, _, _ in after.values()}) == 1
    # the absorbed row keeps its id in the survivorship record
    assert after["overture_places:41c0fc63-fe42-4704-8215-133e2db67a98"][1] is False
    # variant A leaves the label -- and therefore the key -- exactly as it was
    anchor = _by_pid(_dedup_all([*pre, LIONS_MILK_OVERTURE], precedence="anchor"))
    assert anchor["nyc_dohmh_restaurants:d1"][2] == "restaurant"


def test_booth_pass_never_reaches_across_categories_in_the_global_run():
    """The booth-renter collapse is name-BLIND. It used to be confined to one
    category by the per-category call contract; the global pass must check the
    category explicitly or a DOS nail salon and a DOS barbershop in one
    building would fuse on nothing but proximity."""
    nails = _row("N1", "nys_dos_appearance_enhancement", "Lucky Nails Inc",
                 "nails_beauty", 40.700000, -73.900000, conf=0.85)
    hair = _row("H1", "nys_dos_appearance_enhancement", "Andre Smith",
                "hair_barber", 40.700040, -73.900010, conf=0.85)   # ~4.5 m
    out = _by_pid(_dedup_all([nails, hair]))
    assert out[nails["poi_id"]][0] != out[hair["poi_id"]][0]


def test_cross_category_pass_only_adds_unions():
    """Monotonicity: turning the pass on may only merge clusters, never split
    one. Checked on a mixed fixture rather than asserted in a comment."""
    rows = [
        LIONS_MILK_DOHMH, LIONS_MILK_OVERTURE,
        _row("x", "overture_places", "Ravenwood Apothecary", "pharmacy",
             40.715900, -73.955800),
        _row("y", "foursquare_os_places", "Ravenwood Apothecary", "pharmacy",
             40.715905, -73.955805),
        _row("z", "foursquare_os_places", "Kettlebridge Fitness", "fitness",
             40.716000, -73.955900),
    ]
    before = {pid: cid for pid, cid, _ in _dedup_category(rows)}
    after = {pid: cid for pid, cid, _, _ in _dedup_all(rows)}
    for a in rows:
        for b in rows:
            if before[a["poi_id"]] == before[b["poi_id"]]:
                assert after[a["poi_id"]] == after[b["poi_id"]], (
                    "a pre-existing cluster was split")
    assert len(set(after.values())) < len(set(before.values()))


# ------------------------------------------------------------- the write path

def _memdb_with_lions_milk():
    from loci import db as locidb
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    for r in (LIONS_MILK_DOHMH, LIONS_MILK_OVERTURE):
        con.execute(
            "INSERT INTO staging.poi (poi_id, source_id, category, name, geom, "
            "confidence, tier, attrs) VALUES (?, ?, ?, ?, ST_Point(?, ?), ?, 1, '{}')",
            [r["poi_id"], r["source_id"], r["category"], r["name"],
             r["lon"], r["lat"], r["confidence"]])
    return con


def test_build_dedup_writes_the_cluster_category_not_the_source_category():
    """`analysis.poi_dedup.category` used to be the loop variable -- one
    category per INSERT. It is now the cluster's label, which for a
    cross-category cluster differs from `staging.poi.category` on every member,
    the canonical one included (ruling B).

    Also pins the report shape `cli.dedup` prints: raw rows counted by the
    SOURCE's category, canonical clusters by the CLUSTER's category."""
    from loci.score.dedup import build_dedup

    con = _memdb_with_lions_milk()
    report = build_dedup(con)
    rows = con.execute("SELECT poi_id, cluster_id, is_canonical, category "
                       "FROM analysis.poi_dedup ORDER BY poi_id").fetchall()
    assert len(rows) == 2, "every member is retained -- survivorship, not delete"
    assert len({r[1] for r in rows}) == 1
    assert sum(1 for r in rows if r[2]) == 1
    assert {r[3] for r in rows} == {"cafe_bakery"}
    # the DOHMH row is still the canonical one; only the LABEL moved
    canon = [r for r in rows if r[2]][0]
    assert canon[0] == "nyc_dohmh_restaurants:50043137"
    # staging keeps each source's own label, unchanged
    assert con.execute("SELECT category FROM staging.poi WHERE poi_id = ?",
                       [LIONS_MILK_DOHMH["poi_id"]]).fetchone()[0] == "restaurant"
    assert report["restaurant"] == (1, 0)
    assert report["cafe_bakery"] == (1, 1)


def test_poi_supply_reports_the_cluster_category_not_the_source_one():
    """sql/032. Without it the ruling is a no-op downstream: the view would
    keep reading DOHMH's permit class off the canonical row while poi_dedup
    said cafe_bakery -- two disagreeing answers to "what category is this".

    Also pins the join that goes with it: `analysis.category_anchor` must be
    matched on the CLUSTER's category, or a row counted as a cafe would carry
    the restaurant supply rule."""
    from loci.score.dedup import build_dedup

    con = _memdb_with_lions_milk()
    build_dedup(con)
    supply = con.execute(
        "SELECT poi_id, category FROM analysis.poi_supply").fetchall()
    assert supply == [("nyc_dohmh_restaurants:50043137", "cafe_bakery")]

    con.execute("INSERT INTO analysis.category_anchor (category, anchor_poi, "
                "zbp_estab, anchor_coverage, threshold, qualifies, run_at) "
                "VALUES ('cafe_bakery', 1, 1, 1.0, 1.0, TRUE, now())")
    row = con.execute("SELECT is_anchored_category, in_principled "
                      "FROM analysis.poi_supply").fetchone()
    assert row[0] is True, "the anchor must be joined on the cluster category"
    assert row[1] is True, "one registry member -> principled"
