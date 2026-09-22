"""Budget-guarded Google Places (New) Nearby Search client (GTM-11).

Every call is counted in a persisted ledger; when the ledger reaches
LOCI_GOOGLE_CALL_BUDGET the client refuses, and it refuses outright when the
budget is unset. Field mask is the minimum that still tells us what a result is
and where it sits: id, location, types, primaryType. primaryType sits in the
same Basic Data SKU as types (GTM-11), so adding it does not reprice the call.
Adding displayName/rating/hours would reprice the SKU, so do not widen it
casually beyond that.

Primary-type filtering (GTM-105 finding A): the request uses
`includedPrimaryTypes`, not `includedTypes`. `includedTypes`/`excludedTypes`
match a place's full, multi-label `types` array; only
`includedPrimaryTypes`/`excludedPrimaryTypes` match the single `primaryType`.
Loci's own categories are single-label per place (see osm_overpass.py,
overture_places.py::_category_for), so matching Google on ANY type
double-counts a place across every category one of its secondary types
happens to hit (a bakery-cafe under both `restaurant` and `cafe_bakery`, a
bodega under both `grocery` and `convenience`, etc.). Filtering on the primary
type only is what makes the two sides comparable.

Result cap: Nearby Search (New) returns at most 20 places per call and has NO
nextPageToken — unlike Text Search, there is no way to page past it. A count
of exactly 20 is therefore right-censored, not necessarily the true count.
`nearby_count` reports this via `NearbyResult.at_cap` so callers can exclude
censored rows from any mean/ratio/undercount statistic (GTM-105 finding C);
it does NOT hold merely for "Google found nothing" presence checks.

Search radius: see RADIUS_M below -- derived from reach_tiers.yaml's
`validation` block (network threshold / measured circuity), not hardcoded
(QUESTIONS M8, CHECKPOINT D53).

CLOSURE EVIDENCE (D98, GTM-170): `place_status` is a SECOND, UNRELATED
lookup -- Text Search (New), not Nearby Search -- added alongside
`nearby_count` rather than folded into it. It answers "is THIS named
business still open" for one POI (`evidence.verify`'s closure-check loop),
not "how many places of a category sit in a circle" (`nearby_count`'s
coverage-validation job); the two never share a field mask, a price, or a
result-shape. See `place_status`'s own docstring for the match rule and the
budget it goes through.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
from dataclasses import dataclass, field

import requests

from loci.reach import validation_radius_m

ENDPOINT = "https://places.googleapis.com/v1/places:searchNearby"
FIELD_MASK = "places.id,places.location,places.types,places.primaryType"
MAX_RESULT_COUNT = 20  # Nearby Search (New) hard cap; no pagination exists.
LEDGER_PATH = pathlib.Path("data/interim/google_calls.json")

# ---- closure evidence (D98, GTM-170) -- Text Search (New), NOT Nearby Search
TEXT_SEARCH_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
#: displayName + businessStatus are on the PRO Data SKU (unlike FIELD_MASK's
#: Basic-only fields above) -- design-closure-evidence.md §2's own note.
TEXT_SEARCH_FIELD_MASK = "places.id,places.displayName,places.location,places.businessStatus"
#: Text Search (New) Pro-SKU price. THE SAME number `evidence.verify.
#: PLACES_TEXT_SEARCH_USD` restates (that module cannot import this one --
#: see its own docstring on why the Places client is a Protocol there) and
#: the allocator report's `report/ledger.py` (D100) will restate again against
#: the shared `analysis.spend_ledger` table. tests/test_google_places.py pins
#: the two closure-evidence constants against each other.
PLACES_TEXT_SEARCH_USD = 0.032
#: How close a returned place must be to the (lat, lon) asked about to count
#: as a match -- independent of, and tighter than, nearby_count's
#: category-search RADIUS_M, because Text Search returns whatever it judges
#: the best free-text match, not everything within a circle.
PLACE_STATUS_RADIUS_M = 50

#: Text Search businessStatus -> the closure-evidence verdict. Anything not a
#: key here (CLOSED_TEMPORARILY, or a missing field) yields verdict=None --
#: never a closure inferred from a status Google itself calls temporary.
_BUSINESS_STATUS_VERDICT = {"CLOSED_PERMANENTLY": "closed", "OPERATIONAL": "open"}

# Straight-line search radius, in metres. DERIVED, never hardcoded: the
# `validation` block of src/loci/reach_tiers.yaml carries the gap screen's
# 800 m NETWORK threshold and NYC's measured circuity (1.233, from
# analysis.hex_poi_distance), and radius = round(threshold / circuity).
# QUESTIONS M8 / CHECKPOINT D53; GTM-105 audit finding D. Nearby Search takes a
# circular locationRestriction and nothing else, so the validator cannot be
# made network-shaped -- the best available fix is to pick the disc that most
# nearly matches the network catchment. Rows written before this change used
# 800 m and are recorded as such in analysis.coverage_validation.radius_m.
RADIUS_M: int = validation_radius_m()

# Loci category -> Google Places (New) Table A types. Mirrors webmap/server.js
# (see tests/test_google_types_drift.py).
#
# Owner-approved mapping fixes per the 2026-09-08 GTM-105 audit's ranked item
# 4 (docstring history: the original lists were catalogue-based guesses;
# these are corrected against Table A and loci's NAICS anchors):
#   - nails_beauty dropped `beauty_salon` (NAICS 812112, hair_barber's anchor
#     -- the same salon was being double counted under both categories).
#   - hair_barber gained `hair_care` (broad-primary salons) and `beauty_salon`.
#   - cafe_bakery gained donut/bagel/ice-cream/juice/dessert/tea shops --
#     Google's own taxonomy was narrower than DOHMH's CAFE_KEYWORDS, which
#     biased toward "Google found nothing -> gap survives" (the dangerous
#     direction).
#   - fitness gained yoga_studio/sports_club (both 713940, loci's own anchor).
#     sports_club REVERSED 2026-09-14 by owner ruling -- see the fitness entry.
#   - restaurant gained fast_food_restaurant/meal_takeaway/bar_and_grill plus
#     the Table A cuisine-specific `*_restaurant` family (mirrors Overture's
#     suffix rule); stays well under the 50-type includedPrimaryTypes cap
#     (finding E) -- see test_no_category_exceeds_primary_types_cap.
#   - bar gained wine_bar/night_club and explicitly excludes `bar_and_grill`
#     (NAICS 722511, restaurant's anchor, not 722410).
#   - clinic REMOVED entirely: `doctor` is every solo physician's office (also
#     secondary on hospitals) and `medical_lab` is NAICS 621511, outside both
#     of clinic's anchor codes (621111, 621493) -- confirms D30. Callers must
#     not KeyError on a category with no mapping; see sample.run()'s filter
#     and test_sample.py::test_run_skips_categories_with_no_google_mapping.
#
# tailor_repair (`tailor` only) is NOT fixed by this pass and is not usable
# for headline claims: Table A has no `shoe_repair` type, and `tailor`
# (clothing alteration, ~811490/812320) is near-disjoint from the 811430
# anchor (Footwear & Leather Goods Repair). Kept only because nothing better
# exists in Table A. GTM-48 measured what that costs: a 37.5% [31.1-44.4]
# true-coverage-hole rate, a FLOOR, and the category now carries
# `headline: false` in categories.yaml (owner ruling 2026-09-14).
#
# hair_barber's `beauty_salon` is CONTESTED but deliberately UNCHANGED. The
# statistician's on-type recount drops it to read hair at 34.5% [28.3-41.3]
# instead of 44.5% (docs/coverage-validation-2026-09.md §4), on the argument
# that a broad-primary beauty salon is not hair's 812111/812112 anchor. The
# owner did NOT rule on it 2026-09-14, and it stays: 812112 (Beauty Salons) IS
# one of hair_barber's two anchor codes (categories.yaml), so dropping the type
# would narrow Google below loci's own definition -- the exact bias the D50
# cafe_bakery fix went the other way to remove. Either way hair grades C, so
# nothing downstream turns on it; re-open it with an owner ruling, not a
# silent edit.
GOOGLE_TYPES: dict[str, list[str]] = {
    "grocery": ["grocery_store", "supermarket"],
    "convenience": ["convenience_store"],
    "pharmacy": ["pharmacy", "drugstore"],
    "laundry": ["laundry"],
    "hair_barber": ["hair_salon", "barber_shop", "hair_care", "beauty_salon"],
    "nails_beauty": ["nail_salon"],
    "tailor_repair": ["tailor"],
    "restaurant": [
        "restaurant", "fast_food_restaurant", "meal_takeaway", "bar_and_grill",
        "american_restaurant", "chinese_restaurant", "italian_restaurant", "japanese_restaurant",
        "mexican_restaurant", "indian_restaurant", "thai_restaurant", "korean_restaurant",
        "vietnamese_restaurant", "greek_restaurant", "french_restaurant", "spanish_restaurant",
        "turkish_restaurant", "lebanese_restaurant", "middle_eastern_restaurant",
        "mediterranean_restaurant", "brazilian_restaurant", "ramen_restaurant", "sushi_restaurant",
        "pizza_restaurant", "seafood_restaurant", "steak_house", "hamburger_restaurant",
        "sandwich_shop", "vegan_restaurant", "vegetarian_restaurant", "breakfast_restaurant",
        "brunch_restaurant", "barbecue_restaurant", "indonesian_restaurant", "african_restaurant",
        "afghani_restaurant", "asian_restaurant",
        # confident-but-not-explicitly-requested Table A additions:
        "buffet_restaurant", "fine_dining_restaurant",
    ],
    "cafe_bakery": ["cafe", "coffee_shop", "bakery", "donut_shop", "bagel_shop", "ice_cream_shop",
                    "juice_shop", "dessert_shop", "tea_house"],
    "bar": ["bar", "pub", "wine_bar", "night_club"],
    "childcare": ["child_care_agency", "preschool"],
    # `sports_club` REMOVED 2026-09-14 (owner ruling; GTM-48,
    # docs/coverage-validation-2026-09.md §4/§8/§9(3)). Fitness read a 35.6%
    # [28.9-42.8] true-coverage-hole rate -- the worst of any anchored
    # category -- and every one of those 64 "holes" was a sports_club or (never
    # requested, leaked by `includedPrimaryTypes`) marina return, with ZERO
    # `gym` or `fitness_center` hits. It was a type-map defect, not missing
    # data: on-type, fitness is 0.6% (1/180). NAICS 713940 covers both, but a
    # yacht club and a boat basin are not the walk-to gym the screen's fitness
    # gaps are about, so the validator's type must be the narrower one.
    # VALIDATOR-ONLY: loci's own fitness category (categories.yaml) is
    # untouched. `marina` never appeared in this map and is not removable here
    # -- it arrived on the response side, which is why the grade in
    # model/recommend.py recounts stored rows against THIS list.
    "fitness": ["gym", "fitness_center", "yoga_studio"],
    "bank": ["bank"],
    "hardware": ["hardware_store"],
    # bathhouse_sauna (GTM-198, 2026-09-17): Table A has BOTH `sauna` and
    # `public_bath` (verified on the place-types page, Table A span). `spa` is
    # deliberately excluded -- it is Google's day-spa/nail-spa catch-all, the
    # population nails_beauty already carries, and adding it would make this
    # validator count a nail spa as a bathhouse. `massage`/`massage_spa` and
    # `wellness_center` are 812199 neighbours, not the category.
    "bathhouse_sauna": ["sauna", "public_bath"],
    # brewery (D137, 2026-09-22): Table A has BOTH `brewery` and `brewpub` as
    # distinct types (verified on the place-types page). Both are included --
    # unlike the SLA "Restaurant Brewer" carve-out (model/filing_categories.yaml),
    # this validator checks against the full WIDE category definition
    # (taprooms, brewpubs-as-breweries, production-only brewers all count).
    "brewery": ["brewery", "brewpub"],
}


@dataclass
class NearbyResult:
    """Structured result of one Nearby Search (New) call.

    count   — number of places returned (<= MAX_RESULT_COUNT).
    at_cap  — True when count == MAX_RESULT_COUNT. There is no
              nextPageToken on this endpoint, so a capped count is
              right-censored: the true count could be higher. Exclude
              at_cap rows from any mean/ratio/undercount statistic
              (GTM-105 finding C).
    places  — (primaryType, types) per returned place, read off fields
               already in FIELD_MASK at no extra API cost (finding G).
               primaryType is None if Google omitted it for a place.
    """
    count: int
    at_cap: bool
    places: list[tuple[str | None, list[str]]] = field(default_factory=list)


class BudgetExhausted(RuntimeError):
    pass


class GooglePlacesClient:
    def __init__(self, api_key: str | None = None, budget: int | None = None,
                 ledger_path: pathlib.Path = LEDGER_PATH, session: requests.Session | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get("GOOGLE_PLACES_KEY", "")
        env_budget = os.environ.get("LOCI_GOOGLE_CALL_BUDGET")
        self.budget = budget if budget is not None else (int(env_budget) if env_budget else 0)
        self.ledger_path = pathlib.Path(ledger_path)
        self.session = session or requests.Session()
        self._ledger = self._load()

    # ---- ledger --------------------------------------------------------------
    def _load(self) -> dict:
        if self.ledger_path.exists():
            return json.loads(self.ledger_path.read_text())
        return {"calls": 0, "first_call": None, "last_call": None}

    def _save(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(self._ledger, indent=1))

    @property
    def calls_used(self) -> int:
        return int(self._ledger.get("calls", 0))

    @property
    def calls_left(self) -> int:
        return max(0, self.budget - self.calls_used)

    def _charge(self) -> None:
        if self.budget <= 0:
            raise BudgetExhausted("LOCI_GOOGLE_CALL_BUDGET is unset or 0 — refusing to call Google.")
        if self.calls_used >= self.budget:
            raise BudgetExhausted(f"Google call budget exhausted: {self.calls_used}/{self.budget}.")
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self._ledger["calls"] = self.calls_used + 1
        self._ledger["first_call"] = self._ledger.get("first_call") or now
        self._ledger["last_call"] = now
        self._save()

    # ---- API ------------------------------------------------------------------
    def nearby_count(self, lat: float, lon: float, category: str,
                     radius_m: int = RADIUS_M) -> NearbyResult:
        """Places of `category` within `radius_m`, primary-type-matched (see module docstring).

        `radius_m` defaults to the circuity-corrected RADIUS_M above, not to
        the pre-D53 circle: the caller must record the radius it used
        alongside the count, because a count is only interpretable against
        the circle it was taken in.

        Returns a NearbyResult: count (<= 20, the API's hard cap), at_cap
        (True iff count == 20, meaning the true count may be higher and is
        right-censored), and the per-place (primaryType, types) pairs.
        """
        types = GOOGLE_TYPES[category]
        if not self.api_key:
            raise RuntimeError("GOOGLE_PLACES_KEY is not set.")
        self._charge()   # charge BEFORE the request so a crash can't under-count
        body = {"includedPrimaryTypes": types, "maxResultCount": MAX_RESULT_COUNT,
                "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                                   "radius": radius_m}}}
        resp = self.session.post(ENDPOINT, json=body, timeout=30,
                                 headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK})
        resp.raise_for_status()
        places = resp.json().get("places", [])
        count = len(places)
        return NearbyResult(
            count=count,
            at_cap=count >= MAX_RESULT_COUNT,
            places=[(p.get("primaryType"), p.get("types", [])) for p in places],
        )

    # ---- closure evidence (D98, GTM-170) --------------------------------------
    def place_status(self, name: str, lat: float, lon: float,
                     radius_m: int = PLACE_STATUS_RADIUS_M) -> "PlaceStatus":
        """Text Search (New) lookup for ONE named business near (lat, lon) --
        the closure-evidence channel `evidence.verify.verify()` calls through
        the `PlaceStatusProtocol` shape, distinct from `nearby_count`'s
        category-count scan above.

        Returns `PlaceStatus(verdict=None, ...)` -- never raises for "no
        usable result" -- when: Google returns nothing; the top result's
        `displayName` does not NAME-KEY MATCH `name` (`poi_presence.
        name_key_of`, the same normalizer `score.dedup` clusters POIs with);
        the match is farther than `radius_m`; or `businessStatus` is
        CLOSED_TEMPORARILY or absent. `CLOSED_PERMANENTLY` -> 'closed',
        `OPERATIONAL` -> 'open' -- see `_BUSINESS_STATUS_VERDICT`. A caller
        turns a non-None verdict into an `EvidenceRow` with `dated_by=
        'retrieval'` (Google publishes no date for this field) and
        `url='https://www.google.com/maps/place/?q=place_id:<id>'`.

        BUDGET: goes through THIS client's own call-count ledger
        (`self._charge()`, `LOCI_GOOGLE_CALL_BUDGET`) -- charged BEFORE the
        request, exactly like `nearby_count`. The separate DOLLAR ledger
        (`analysis.spend_ledger`) is the CALLER's job: `evidence.verify.
        verify()` reserves against its own `Budget` and writes that row
        BEFORE invoking this method (its module docstring's "reserve ->
        ledger row -> call" sequence) -- this method has no database
        connection to write one itself.
        """
        from loci.evidence.verify import PlaceStatus
        from loci.model.poi_presence import name_key_of
        from loci.score.dedup import haversine_m

        if not self.api_key:
            raise RuntimeError("GOOGLE_PLACES_KEY is not set.")
        self._charge()   # charge BEFORE the request so a crash can't under-count
        body = {
            "textQuery": name,
            "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                        "radius": radius_m}},
            "maxResultCount": 1,
        }
        resp = self.session.post(
            TEXT_SEARCH_ENDPOINT, json=body, timeout=30,
            headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": TEXT_SEARCH_FIELD_MASK})
        resp.raise_for_status()
        places = resp.json().get("places", [])
        if not places:
            return PlaceStatus(verdict=None, place_id=None)

        place = places[0]
        place_id = place.get("id")
        display = (place.get("displayName") or {}).get("text") or ""
        if name_key_of(display) != name_key_of(name):
            return PlaceStatus(verdict=None, place_id=place_id)

        loc = place.get("location") or {}
        p_lat, p_lon = loc.get("latitude"), loc.get("longitude")
        if p_lat is None or p_lon is None or haversine_m(lat, lon, p_lat, p_lon) > radius_m:
            return PlaceStatus(verdict=None, place_id=place_id)

        verdict = _BUSINESS_STATUS_VERDICT.get(place.get("businessStatus"))
        return PlaceStatus(verdict=verdict, place_id=place_id)
