from loci.score.dedup import norm_tokens, names_match, source_rank, _dedup_category


def test_distinctive_token_matching():
    # true twins across sources with different generic words -> match
    assert names_match(norm_tokens("Tom's Restaurant"), norm_tokens("Tom's Diner"))
    # containment of a distinctive multi-token name
    assert names_match(norm_tokens("The Starlight"), norm_tokens("The Starlight Tavern"))
    # generic-word overlap must NOT match distinct businesses
    assert not names_match(norm_tokens("Kennedy Fried Chicken"), norm_tokens("Crown Fried Chicken"))
    assert not names_match(norm_tokens("Joe's Pizza"), norm_tokens("Ray's Pizza"))
    # empty after stripping generics -> no match
    assert not names_match(norm_tokens("Restaurant"), norm_tokens("Pizza Place"))


def test_source_rank_prefers_anchor():
    assert source_rank("restaurant", "nyc_dohmh_restaurants") < source_rank("restaurant", "overture_places")
    assert source_rank("nails_beauty", "nys_dos_appearance_enhancement") < source_rank("nails_beauty", "osm_overpass")


def test_dedup_category_merges_twins_not_neighbors():
    rows = [
        {"poi_id": "overture_places:a", "source_id": "overture_places", "name": "Tom's Restaurant",
         "category": "restaurant", "confidence": 0.7, "lat": 40.7000, "lon": -73.9000},
        {"poi_id": "nyc_dohmh_restaurants:b", "source_id": "nyc_dohmh_restaurants", "name": "Tom's Diner",
         "category": "restaurant", "confidence": 0.95, "lat": 40.70005, "lon": -73.90005},  # ~7m, same
        {"poi_id": "overture_places:c", "source_id": "overture_places", "name": "Ruby's Grill",
         "category": "restaurant", "confidence": 0.7, "lat": 40.70010, "lon": -73.90010},  # ~14m, different
    ]
    out = {pid: (cid, canon) for pid, cid, canon in _dedup_category(rows)}
    # a and b merge (same distinctive token), c stays separate
    assert out["overture_places:a"][0] == out["nyc_dohmh_restaurants:b"][0]
    assert out["overture_places:c"][0] != out["overture_places:a"][0]
    # canonical of the twin cluster is the DOHMH anchor
    assert out["nyc_dohmh_restaurants:b"][1] is True
    assert out["overture_places:a"][1] is False


def test_source_rank_new_anchors_win_their_category():
    assert source_rank("convenience", "usda_snap_retailers") < source_rank("convenience", "overture_places")
    assert source_rank("bar", "nys_sla_liquor_licenses") < source_rank("bar", "nyc_dohmh_restaurants")
    assert source_rank("hardware", "foursquare_os_places") > source_rank("hardware", "overture_places")
    # anchors carry no authority outside their category
    assert source_rank("hardware", "usda_snap_retailers") == source_rank("hardware", "some_unknown_source")


# ---------------------------------------------------------------- booth renters

def _dos(pid, name, lat, lon, cat="nails_beauty"):
    return {"poi_id": f"nys_dos_appearance_enhancement:{pid}",
            "source_id": "nys_dos_appearance_enhancement", "name": name,
            "category": cat, "confidence": 0.85, "lat": lat, "lon": lon}


def test_booth_renters_collapse_despite_unrelated_names():
    """One storefront, one shop licence + two chair-renter licences in the
    renters' own names, all geocoded to the same door (~5-11 m apart). No name
    rule can match 'Lucky Nails' to 'Jing Li', so the collapse must be
    name-blind -- but only within NYS DOS and within the category."""
    rows = [
        _dos("A1", "Lucky Nails Inc", 40.700000, -73.900000),
        _dos("A2", "Jing Li", 40.700040, -73.900010),          # ~4.5 m
        _dos("A3", "Maria Rodriguez", 40.700000, -73.900110),  # ~9.3 m
    ]
    out = {pid: (cid, canon) for pid, cid, canon in _dedup_category(rows)}
    cids = {v[0] for v in out.values()}
    assert len(cids) == 1, "three licences at one storefront must be one location"
    # every licence id is retained, exactly one is canonical
    assert len(out) == 3
    assert sum(1 for _, canon in out.values() if canon) == 1
    # ...and with the pass disabled they stay three separate "businesses"
    before = {cid for _, cid, _ in _dedup_category(rows, booth_meters=0)}
    assert len(before) == 3


def test_two_dos_salons_50m_apart_stay_separate():
    """The negative case. 50 m is beyond both BOOTH_METERS and MATCH_METERS,
    and the names share nothing distinctive, so these are two businesses."""
    rows = [
        _dos("B1", "Lucky Nails Inc", 40.700000, -73.900000),
        _dos("B2", "Sunshine Spa", 40.700000, -73.900592),   # ~50 m
    ]
    out = {pid: cid for pid, cid, _ in _dedup_category(rows)}
    assert len(set(out.values())) == 2


def test_booth_rule_does_not_reach_across_sources_or_categories():
    # Different SOURCE at the same spot with an unrelated name: still two.
    cross_source = [
        _dos("C1", "Lucky Nails Inc", 40.700000, -73.900000),
        {"poi_id": "overture_places:C2", "source_id": "overture_places",
         "name": "Ravenwood Apothecary", "category": "nails_beauty",
         "confidence": 0.7, "lat": 40.700040, "lon": -73.900010},
    ]
    assert len({cid for _, cid, _ in _dedup_category(cross_source)}) == 2

    # Same source, same spot, but _dedup_category is called PER CATEGORY, so a
    # barbershop and a nail salon in one building are never fed in together.
    hair = [_dos("D1", "Fades Barbershop", 40.700000, -73.900000, cat="hair_barber"),
            _dos("D2", "Andre Smith", 40.700040, -73.900010, cat="hair_barber")]
    assert len({cid for _, cid, _ in _dedup_category(hair)}) == 1


def test_canonical_name_is_the_most_common_in_the_cluster():
    """Two DOS records carry the shop name and one carries a renter's name;
    the storefront name must win the canonical slot."""
    rows = [
        _dos("E1", "Jing Li", 40.700000, -73.900000),
        _dos("E2", "Lucky Nails", 40.700030, -73.900000),
        _dos("E3", "Lucky Nails", 40.700060, -73.900000),
    ]
    by_pid = {r["poi_id"]: r for r in rows}
    canon = [pid for pid, _, is_c in _dedup_category(rows) if is_c]
    assert len(canon) == 1
    assert by_pid[canon[0]]["name"] == "Lucky Nails"


def test_booth_pass_never_prevents_a_cross_source_union():
    """The pass only ADDS unions. A DOHMH/Overture name match must still merge,
    and the anchor source must still win the canonical slot."""
    rows = [
        {"poi_id": "overture_places:a", "source_id": "overture_places", "name": "Tom's Restaurant",
         "category": "restaurant", "confidence": 0.7, "lat": 40.7000, "lon": -73.9000},
        {"poi_id": "nyc_dohmh_restaurants:b", "source_id": "nyc_dohmh_restaurants", "name": "Tom's Diner",
         "category": "restaurant", "confidence": 0.95, "lat": 40.70005, "lon": -73.90005},
    ]
    out = {pid: (cid, canon) for pid, cid, canon in _dedup_category(rows)}
    assert out["overture_places:a"][0] == out["nyc_dohmh_restaurants:b"][0]
    assert out["nyc_dohmh_restaurants:b"][1] is True


def test_a_null_name_does_not_crash_the_frequency_tiebreak():
    """REGRESSION. build_dedup feeds rows in via pandas `.to_dict("records")`,
    which renders a SQL NULL name as float('nan') -- and nan is TRUTHY, so the
    obvious `(name or "")` guard passes it through to .strip() and the whole
    `loci dedup` run dies partway. ~1 in 10^3 staging rows has no name."""
    rows = [
        _dos("F1", float("nan"), 40.700000, -73.900000),
        _dos("F2", "Lucky Nails", 40.700030, -73.900000),
        _dos("F3", None, 40.700060, -73.900000),
    ]
    out = {pid: (cid, canon) for pid, cid, canon in _dedup_category(rows)}
    assert len({c for c, _ in out.values()}) == 1
    canon = [pid for pid, (_, is_c) in out.items() if is_c]
    # the only NAMED record wins the canonical slot; an unnamed one contributes
    # no frequency and must never outrank it.
    assert canon == ["nys_dos_appearance_enhancement:F2"]
