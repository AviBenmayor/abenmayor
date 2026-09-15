"""Commercial LEGALITY at address grain: is a storefront here allowed, or only
tolerated (D82).

Owner's ask, folded into the 2026-09-14 seed: the map already shows a "gap" at
a Washington Square rowhouse zoned pure residential, and a capital allocator
reading that dot as investable is a worse failure than a gap the map never
drew. Zoning must therefore label and filter recommendation OUTPUTS -- it must
NEVER enter gap_score, supply_ratio, the revenue model or any grade (D82,
"character enters no grade"). The precedent is `model/address_character.py`,
which keeps its own zoning read (`_commercial_lot_sql`) out of every score for
exactly this reason.

--------------------------------------------------------------------------
THE RULE -- REVISED 2026-09-14, contrarian review (D97/GTM-169)
--------------------------------------------------------------------------
    Ineligible = (R district with no C1/C2 overlay OR park/open-space land use
    OR institutional owner type) AND NOT grandfathered_evidence, decided ONLY
    for a lot that is not itself commercially zoned (see branch order below).
    Grandfathered = PLUTO's own retail record on the lot (retailarea > 0 OR a
    K*/S* building class) OR a commercial-category POI within
    POI_MATCH_RADIUS_M whose status is NOT 'closed' (open OR unknown -- D79:
    absence/uncertainty is never evidence of closure, so an unresolved POI
    must not read as "nothing here" for a grandfathering test). Historic
    district and individual landmark are card labels only (fit-out cost
    warning). They never cause exclusion.

FOUR branches, in this priority order (`legality_case_sql()` is the ONE
place this is expressed; tests and the build step both read it from here,
never re-derive it):

    0. zonedist1 IS NULL (no BBL match)                     -> 'unknown'
    1. commercially_zoned (C-prefix zonedist1, or a C1-/C2- -> 'commercial'
       overlay on an R lot)
    2. r_no_overlay      AND     grandfathered_evidence      -> 'grandfathered'
    3. zoning_ineligible AND NOT grandfathered_evidence       -> 'ineligible'
    4. everything else                                        -> 'commercial'

Branch 1 is decided FIRST and unconditionally: a lot the city itself zoned
for commerce is never downgraded by ownertype or park landuse, and
grandfathering evidence is irrelevant there -- institutional ownertype and
park landuse can only make an address ineligible when it is NOT commercially
zoned (a city-owned lot on a commercial avenue is 'commercial', not
'ineligible'; contrast 51 Washington Square South, R7-2 with no overlay, where
the same ownertype test still applies because the lot itself is R-zoned).

Branch 2 is deliberately narrower than branch 3's `zoning_ineligible`: only
the R-no-overlay case is "grandfathered" (a shop that outlasted a rezoning or
was never legal but persists). A park lot or an institutional campus with
grandfathering evidence on it (a concession stand, a hospital gift shop, a
PLUTO retail-area record) is not a grandfathered storefront in that sense --
it falls through to 'commercial', which is the honest reading of "a real
business record exists here." When a lot is BOTH r_no_overlay AND
park/institutional (a park that happens to also be zoned R, with no separate
park district), branch 2 is checked first and wins if evidence is present --
this is pre-existing, pinned behaviour
(`test_r_no_overlay_open_poi_beats_park_and_institutional_priority`), not a
new decision.

Branch 0 ('unknown') is new (item 5, D97): a street-frame point with no BBL
match (no PLUTO lot at all -- 50,199 of these in the 2026-09-14 warehouse) was
previously defaulted to 'commercial' with a basis explaining the missing
match. That default was quietly indistinguishable from "we checked and it is
commercially zoned" -- a card or map label that cannot tell "the city says
this is zoned for commerce" from "we have no idea" is not honest about what
it knows. 'unknown' is a FOURTH first-class value, never excluded from
recommendations and never greyed on the map (same D75 "nothing leaves the
universe" contract 'ineligible' does NOT get) -- see LEGALITY_VALUES.

--------------------------------------------------------------------------
STORED COLUMNS, NOT A LIVE VIEW -- REVISED 2026-09-14 ON MEASUREMENT
--------------------------------------------------------------------------
The first cut here made `legality`/`legality_basis` a `CREATE OR REPLACE
VIEW` joining `analysis.poi_supply_status` by an EXACT rounded-coordinate
match (the same grid `poi_presence.COORD_DP` uses for co-location). Measured
against the real warehouse it matched 62 of 44,002 open commercial POIs to
any address at all -- co-location's exact-grid match works because it
compares POI records to OTHER POI records that mostly share a government
geocoder; PLUTO's own lot centroid is a DIFFERENT geocode of the same
building and is commonly 5-15 m off a POI's point (measured: median 8 m,
p90 15 m, max 31 m over the pairs that DID fall in a 111 m box). A live view
built on that match is not just slightly stale, it is nearly empty.

Widening the match to a real distance test (`POI_MATCH_RADIUS_M`, see below)
fixed the join (14,736 addresses gain an open-commercial-POI within 20 m) but
made the computation genuinely expensive: ~90 s over the full MN+BK address
set on the real warehouse (and it grew from there -- 178 s measured
2026-09-15 over 332,041 addresses x 204,437 not-closed commercial POIs, the
nested-loop join GTM-169 then fixed; see `open_poi_match_sql`). A
`CREATE OR REPLACE VIEW` re-runs that on EVERY read -- the webmap export,
every `recs add`, every `address-legality stats` call -- which is not
acceptable for a read path. The GTM-169 bucket brought the SELECT to ~1 s,
which does NOT reopen the question: the stored-column contract is what the
rest of the pipeline (and the `legality_run_at` re-apply sentinel) is built
on, and a live view would still re-evaluate the four-CTE
`poi_supply_status` on every read.

So `has_open_commercial_poi`, `legality` and `legality_basis` are STORED
columns on `analysis.address` (sql/031's ALTERs), computed once by
`build_legality_columns()` and read cheaply thereafter -- the SAME contract
every other derived-but-expensive address column already uses
(`address_character`'s twelve floor-area/jobs columns, the access columns,
the transit profile): compute in a batch step, stamp a `*_run_at`
provenance column, and RE-APPLY after `loci address-gaps` DELETEs and
re-INSERTs `analysis.address` (D78) -- exactly like `character_run_at`. A row
whose `legality_run_at IS NULL` has not been through this build since the
last address-gaps rebuild, the same sentinel `address_character` uses.

`analysis.address_legality` stays as a VIEW, but now a CHEAP passthrough over
the stored columns (sql/031) -- a stable read name for consumers (the webmap
export, the recommendation-ledger gate, `address-legality stats`) that does
not care whether the columns are computed live or stored.

--------------------------------------------------------------------------
DECISIONS THE SEED LEFT OPEN (recorded here, not re-litigated per session)
--------------------------------------------------------------------------
* PARK_LANDUSE_CODES = {'09'} only. PLUTO LandUse '09' is "Open Space &
  Outdoor Recreation" -- parks, cemeteries, playgrounds. '10' (Parking
  Facilities) is explicitly EXCLUDED per the seed's own note ("only open
  space") -- a parking lot is not off-limits to a storefront the way a park
  is; it is frequently the FRONT half of a commercial lot.
* INSTITUTIONAL_OWNERTYPES = {'C', 'O', 'P', 'X'}, taken verbatim from the
  seed's own gloss (the earlier dig's finding, not re-derived here): 'C' city
  ownership, 'O' other public authority, 'P' Parks Dept property, 'X' mixed
  city/state/federal/institutional. This is DOF's OwnerType code, not a
  richer classification -- a private nonprofit hospital on privately-owned
  land reads blank/'P'(private) here and is caught (if at all) by the
  R-no-overlay branch, not this one. 51 Washington Square South (NYU, X) is
  the seed's own pinned check for this branch.
* "Commercial POI" = any POI in the 15-category registry (`loci.categories`).
  Every registered category (grocery ... hardware) is retail/food/personal-
  service; the registry carries no residential or purely-institutional
  category, so `COMMERCIAL_POI_CATEGORIES` is currently the full set. It is
  still named and filtered explicitly (not "any POI at all") so a future
  category that is NOT retail-facing does not silently start granting
  'grandfathered' status.
* GRANDFATHERING EVIDENCE (item 3, D97, owner-ruled reading of D79) is now
  TWO independent sources, either sufficient alone: (a) PLUTO's own retail
  record on the lot -- `retailarea > 0` OR a `K*`/`S*` building class (store
  buildings; mixed residential-with-retail) -- and (b) a commercial-category
  POI within POI_MATCH_RADIUS_M whose `poi_status <> 'closed'` (open OR
  UNKNOWN, not just open). The POI test was widened from open-only to
  not-closed for the same D79 reason branch (b) always used: a POI this
  project has not yet resolved is UNCERTAIN, not evidence of absence, and
  treating "unknown" as "not there" for a grandfathering test would be
  exactly the silent-absence error D79 exists to forbid. PLUTO retail
  evidence is independent of any POI feed entirely -- a lot DOF itself
  records as retail is affirmative evidence even when no POI source
  currently lists an open business on it.
* POI_MATCH_RADIUS_M = 20.0. "At the address" cannot be an exact-coordinate
  test (see above) because PLUTO and the POI feeds are different geocodes of
  the same building. 20 m is chosen from the measured distribution of
  open-commercial-POI-to-nearest-residential-address distances on the real
  2026-09-14 warehouse (median 8 m, p90 15 m, max 31 m among matches found
  within a generous 111 m box) -- wide enough to catch the geocode offset,
  narrow enough that it still reads as "this building", not "this block"
  (an NYC lot frontage is commonly 6-8 m; 20 m is roughly two to three lots).
  STRAIGHT-LINE (haversine) distance, not network distance: this is a
  same-building test, not a walk-catchment sweep.

  RADIUS_SENSITIVITY (contrarian review, D97/GTM-169): how many
  zoning-ineligible-candidate addresses (R-no-overlay OR park OR
  institutional) gain a qualifying POI as the radius widens, open-only vs
  the now-adopted not-closed test --

      radius (m)         15      20      25      30      50
      open-only         311    1151    5489   12233   31674
      not-closed       10265   15375   23248   33854   81408

  20 m was KEPT, not widened, even though not-closed at 30 m nearly triples
  the count: a typical NYC lot frontage is 6-8 m, so 20 m already spans two
  to three lots either side of the address point (absorbing the PLUTO/POI
  geocode offset this module's join exists to handle); 30 m spans roughly
  three lots' worth of ADDITIONAL reach beyond that and starts reading as
  "this block", not "this building" -- the same "block, not building"
  argument that fixed POI_MATCH_RADIUS_M at 20 rather than a rounder 25 or
  30 the first time. Widening the radius to admit more matches is a decision
  about what "at this address" MEANS, not a free way to grandfather more
  lots; the not-closed broadening (this session) already does the latter
  through evidence quality, not distance.
"""
from __future__ import annotations

import pathlib

from loci.grid.pluto import PLUTO_CSV
from loci.model.address_character import COMMERCIAL_OVERLAY_PREFIXES

#: PLUTO LandUse codes that are park / open space. See module docstring:
#: '10' (parking) is deliberately excluded.
PARK_LANDUSE_CODES: tuple[str, ...] = ("09",)

#: PLUTO OwnerType codes read as institutional/public (seed's own gloss).
INSTITUTIONAL_OWNERTYPES: tuple[str, ...] = ("C", "O", "P", "X")

#: The raw PLUTO columns this module adds to `analysis.address` (sql/031).
#: `retailarea` and `bldgclass` were added 2026-09-14 (D97 item 3, contrarian
#: review) for the PLUTO-retail-evidence half of the grandfathering test --
#: the column SET is this module's; extending sql/031's ALTERs to match is
#: part of this same change. `spdist1` was added 2026-09-15 (investor review,
#: GTM-172 item 6) for the allocator report's legality section -- PLUTO's
#: primary Special Purpose District (e.g. the Special Gowanus Mixed Use
#: District). LABEL ONLY, exactly like `histdist`/`landmark`: it never enters
#: `legality_case_sql()` or any branch of the eligibility rule above, it is
#: carried through for the report to print (or print "not loaded" when NULL).
PLUTO_LEGALITY_COLUMNS: tuple[str, ...] = (
    "zonedist1", "overlay1", "overlay2", "landuse", "ownertype",
    "histdist", "landmark", "retailarea", "bldgclass", "spdist1",
)

#: PLUTO building-class prefixes read as retail evidence (D97 item 3): 'K'
#: (store buildings) and 'S' (primarily residential WITH some commercial /
#: retail space, e.g. a corner mixed-use building) -- see module docstring's
#: GRANDFATHERING EVIDENCE note.
RETAIL_BLDGCLASS_PREFIXES: tuple[str, ...] = ("K", "S")

#: "At the address" match radius, straight-line metres. See module docstring
#: for the measurement this was chosen from, and RADIUS_SENSITIVITY for why
#: it was kept rather than widened when the POI test broadened to not-closed.
POI_MATCH_RADIUS_M = 20.0

#: Metres per degree of LATITUDE (fixed: 111,320 m/degree everywhere). Used
#: directly for the latitude pre-filter pad and, divided by cos(latitude),
#: for the longitude pad -- see `open_poi_match_sql`. Longitude degrees are
#: SHORTER than latitude degrees away from the equator (by a factor of
#: cos(latitude) -- about 0.757 at NYC's ~40.7N), so a bounding-box
#: pre-filter that pads both axes by this SAME latitude-rate value is not
#: conservative on the east-west axis, it is too NARROW there: a pre-filter
#: is only safe to widen the real test's candidate set, never to narrow it,
#: and the unfixed version measurably narrowed it (D97 item 2: 15.1 m of
#: actual east-west coverage for a nominal 20 m radius at 40.72N -- a true
#: match up to ~4.9 m further east or west than that was silently dropped
#: before the real haversine test ever ran on it).
METRES_PER_DEGREE = 111_320.0

#: Side of the square lon/lat cell both sides of the POI match are bucketed
#: into before the exact test (GTM-169, 2026-09-15). See
#: `open_poi_match_sql` for why the bucket exists at all; the ONE correctness
#: invariant it has to satisfy is
#:
#:     grid_deg >= pad_lat  AND  grid_deg >= pad_lon(lat)   for every row
#:
#: because the bucket join only looks at the 3x3 neighbourhood of a cell. If a
#: pad were WIDER than a cell, a true match two cells away would be dropped
#: before the haversine test ever ran -- exactly the east-west under-coverage
#: failure D97 item 2 fixed once already, which is why this is guarded in code
#: (`assert_grid_covers_pad`, called from `build_legality_columns`) rather than
#: left as a comment. At POI_MATCH_RADIUS_M = 20 m the pads are 1.797e-4 deg
#: (lat) and 2.371e-4 deg (lon at 40.7N), so 1e-3 clears the wider one by 4.2x
#: -- and the guard proves it for whatever latitudes the frame actually holds,
#: which is the city-agnostic form of the claim.
POI_GRID_DEG = 0.001

VIEW_NAME = "analysis.address_legality"
#: 'unknown' (D97 item 5) is a FOURTH first-class value, not a fallback: a
#: street-frame point with no BBL match gets it. Like the other three, it is
#: never dropped from the universe (D75) -- but unlike 'ineligible', it is
#: never excluded from recommendations and never greyed on the map, because
#: "we don't know" is not the same claim as "we checked and it's not
#: commercially eligible".
LEGALITY_VALUES = ("commercial", "grandfathered", "ineligible", "unknown")


def commercial_poi_categories() -> frozenset[str]:
    """The category slugs that count as a "commercial POI" for the
    grandfathering test. See module docstring -- currently the full registry,
    but named explicitly rather than left as "any POI" so a future
    non-retail-facing category cannot silently start granting eligibility."""
    from loci.categories import CATEGORIES

    return frozenset(CATEGORIES)


def _up(alias: str, col: str) -> str:
    return f"UPPER(TRIM(COALESCE({alias}.{col}, '')))"


def r_no_overlay_sql(alias: str = "a") -> str:
    """R-prefixed zonedist1 with no C1-/C2- commercial overlay. The seed's
    "R district with no C1/C2 overlay" clause, and the sole gate on the
    'grandfathered' branch."""
    has_overlay = " OR ".join(
        f"{_up(alias, ov)} LIKE '{pre}%'"
        for ov in ("overlay1", "overlay2")
        for pre in COMMERCIAL_OVERLAY_PREFIXES
    )
    return f"({_up(alias, 'zonedist1')} LIKE 'R%' AND NOT ({has_overlay}))"


def park_landuse_sql(alias: str = "a") -> str:
    """PLUTO LandUse in PARK_LANDUSE_CODES. LPAD to 2 because LandUse exports
    as '9' in some vintages and '09' in others (same caveat address_character
    already carries for this column)."""
    lu = f"LPAD(TRIM(COALESCE({alias}.landuse, '')), 2, '0')"
    codes = ", ".join(f"'{c}'" for c in PARK_LANDUSE_CODES)
    return f"({lu} IN ({codes}))"


def institutional_owner_sql(alias: str = "a") -> str:
    """PLUTO OwnerType in INSTITUTIONAL_OWNERTYPES."""
    codes = ", ".join(f"'{c}'" for c in INSTITUTIONAL_OWNERTYPES)
    return f"({_up(alias, 'ownertype')} IN ({codes}))"


def zoning_ineligible_sql(alias: str = "a") -> str:
    """The seed's full ineligibility test, zoning half only (the
    grandfathering-evidence half is applied separately so the SAME expression
    can also gate 'grandfathered'). Only reached when `commercially_zoned_sql`
    is false (D97 item 4: branch order) -- callers that check both must check
    `commercially_zoned_sql` FIRST."""
    return (f"({r_no_overlay_sql(alias)} OR {park_landuse_sql(alias)} "
            f"OR {institutional_owner_sql(alias)})")


def commercially_zoned_sql(alias: str = "a") -> str:
    """C-prefixed zonedist1, OR a C1-/C2- commercial overlay (on an R lot or
    otherwise). D97 item 4: decided FIRST and unconditionally -- a lot the
    city itself zoned for commerce is never downgraded by ownertype or park
    landuse. This test and `r_no_overlay_sql` are mutually exclusive by
    construction (the overlay clause here is exactly what `r_no_overlay_sql`
    requires to be ABSENT), so their relative check order never matters.
    What DOES matter is checking this BEFORE `park_landuse_sql` /
    `institutional_owner_sql`: a commercially-zoned lot can still be
    city-owned or sit on parkland-coded land (a park lot fronting a
    commercial avenue), and must read 'commercial', not 'ineligible', in
    that case."""
    has_overlay = " OR ".join(
        f"{_up(alias, ov)} LIKE '{pre}%'"
        for ov in ("overlay1", "overlay2")
        for pre in COMMERCIAL_OVERLAY_PREFIXES
    )
    return f"({_up(alias, 'zonedist1')} LIKE 'C%' OR {has_overlay})"


def retail_evidence_sql(alias: str = "a") -> str:
    """PLUTO's own retail record on the lot (D97 item 3, half of
    'grandfathering evidence'): `retailarea > 0` (DOF's own square-footage
    figure for retail floor area) OR a `RETAIL_BLDGCLASS_PREFIXES` building
    class. `retailarea` is read `ALL_VARCHAR` off the CSV (see
    `build_legality_columns`) and stored as VARCHAR (sql/031), so it needs a
    TRY_CAST here rather than a bare numeric comparison -- TRY_CAST rather
    than CAST because a malformed or missing value must read as "no
    evidence", never raise and abort the whole UPDATE."""
    ra = f"TRY_CAST({alias}.retailarea AS DOUBLE)"
    bc = _up(alias, "bldgclass")
    cls = " OR ".join(f"{bc} LIKE '{p}%'" for p in RETAIL_BLDGCLASS_PREFIXES)
    return f"(COALESCE({ra}, 0) > 0 OR {cls})"


def grandfathering_evidence_sql(alias: str = "a",
                                open_col: str = "has_open_commercial_poi") -> str:
    """The full grandfathering-evidence test (D97 item 3): PLUTO retail
    evidence OR a nearby commercial POI whose stored status is not 'closed'
    (`open_col`, populated by `open_poi_match_sql` -- which now matches on
    `poi_status <> 'closed'`, not `= 'open'`; see that function and the
    module docstring). `open_col` is a BOOLEAN column/expression already on
    the row -- this function does not know or care how it was computed,
    which is what lets `tests/test_address_legality.py` exercise the branch
    logic on a tiny synthetic table with no spatial join at all."""
    return f"({retail_evidence_sql(alias)} OR COALESCE({alias}.{open_col}, FALSE))"


def legality_case_sql(alias: str = "a", open_col: str = "has_open_commercial_poi"
                      ) -> tuple[str, str]:
    """(legality_expr, legality_basis_expr) -- the ONE definition of the
    four-branch rule (AC-2, revised D97 items 3-5). `open_col` is a BOOLEAN
    column/expression already on the row (a stored column in production, a
    synthetic fixture column in tests) -- this function does not know or
    care how it was computed, which is what lets
    `tests/test_address_legality.py` exercise the branch logic on a tiny
    synthetic table with no spatial join at all.
    """
    r_no_ov = r_no_overlay_sql(alias)
    park = park_landuse_sql(alias)
    inst = institutional_owner_sql(alias)
    commercial_zoned = commercially_zoned_sql(alias)
    ineligible_zoning = zoning_ineligible_sql(alias)
    ev = grandfathering_evidence_sql(alias, open_col)
    retail_ev = retail_evidence_sql(alias)
    op = f"COALESCE({alias}.{open_col}, FALSE)"
    z = f"{alias}.zonedist1"
    lu = f"{alias}.landuse"
    ot = f"{alias}.ownertype"
    ra = f"{alias}.retailarea"
    bc = f"{alias}.bldgclass"

    # D97 item 4: commercial zoning is decided FIRST and unconditionally;
    # item 5: no BBL match reads 'unknown', not a silent 'commercial' default.
    legality = f"""CASE
        WHEN {z} IS NULL THEN 'unknown'
        WHEN {commercial_zoned} THEN 'commercial'
        WHEN {r_no_ov} AND {ev} THEN 'grandfathered'
        WHEN {ineligible_zoning} AND NOT {ev} THEN 'ineligible'
        ELSE 'commercial'
    END"""

    evidence_desc = f"""CASE
        WHEN {retail_ev} AND {op}
            THEN 'PLUTO retail evidence and a nearby non-closed commercial POI'
        WHEN {retail_ev}
            THEN 'PLUTO retail evidence (retailarea ' || COALESCE(CAST({ra} AS VARCHAR), '0')
                 || ', bldgclass ' || COALESCE({bc}, '?') || ')'
        ELSE 'a nearby non-closed (open or unknown) commercial POI'
    END"""

    basis = f"""CASE
        WHEN {z} IS NULL THEN 'no PLUTO lot'
        WHEN {commercial_zoned} THEN 'commercially zoned (' || COALESCE({z}, '?') || ')'
        WHEN {r_no_ov} AND {ev}
            THEN {z} || ' zoned, no C1/C2 overlay, grandfathered by ' || ({evidence_desc})
        WHEN {r_no_ov} AND NOT {ev}
            THEN {z} || ' zoned, no C1/C2 overlay, no grandfathering evidence'
        WHEN {park} AND NOT {ev}
            THEN 'PLUTO landuse ' || COALESCE({lu}, '?') || ' (open space/outdoor recreation), no grandfathering evidence'
        WHEN {park} AND {ev}
            THEN 'PLUTO landuse ' || COALESCE({lu}, '?') || ' (open space) but grandfathering evidence is present'
        WHEN {inst} AND NOT {ev}
            THEN 'PLUTO ownertype ' || {ot} || ' (institutional/public), no grandfathering evidence'
        WHEN {inst} AND {ev}
            THEN 'PLUTO ownertype ' || {ot} || ' (institutional/public) but grandfathering evidence is present'
        ELSE 'commercially zoned (' || COALESCE({z}, '?') || ')'
    END"""
    return legality, basis


#: Earth radius, metres -- the one constant `_haversine_m_sql` needs.
EARTH_RADIUS_M = 6_371_000.0


def _haversine_m_sql(lon1: str, lat1: str, lon2: str, lat2: str) -> str:
    """Equirectangular-approximation great-circle distance, metres, between
    two (lon, lat) pairs given as SQL expressions. Accurate to well under 1%
    at the ~20 m scale this module uses it at (it is the small-angle
    approximation to Haversine, exact in the limit and verified below).

    A PLAIN CHOICE, NOT A WORKAROUND FOR A BROKEN EXTENSION -- RETRACTED
    CLAIM, 2026-09-14 contrarian review (D97 item 1): an earlier draft of
    this docstring claimed DuckDB spatial's `ST_Distance_Sphere` was broken
    in this environment, citing a peer-reported miss on `analysis.address`
    1004710039 ("379 Broome St") where the raw call returned 8.88 m for a
    pair whose true great-circle distance is 32.21 m. That reading was
    wrong: `db.py`'s own D16 comment already documents exactly this gotcha
    -- `ST_Distance_Sphere` reads a bare `ST_Point(x, y)` as (LATITUDE,
    LONGITUDE), the reverse of this project's (lon, lat) convention, so the
    unflipped call the peer report used was always going to be wrong at
    NYC's latitude. Wrapping both points in `ST_FlipCoordinates` (`db.py`'s
    `METRES_SQL`, D16) reproduces 32.21 m exactly --
    `test_st_distance_sphere_with_flip_matches_haversine_within_1pct` pins
    this. The extension is not broken; this module simply keeps its OWN
    formula rather than depending on `db.METRES_SQL` / the spatial
    extension at all, which is a legitimate, independently-checkable choice
    on its own terms: one fewer moving part (no `ST_Point`, no
    `ST_FlipCoordinates`, no spatial extension load) in a module that
    already does its own bounding-box pre-filter in plain lon/lat degrees,
    and a formula that is checkable against a hand haversine calculation
    with no DuckDB spatial functions in the loop at all (see
    `tests/test_address_legality.py::test_haversine_matches_a_reference_calculation`).
    """
    return (f"({EARTH_RADIUS_M} * sqrt("
            f"pow(radians({lat2} - {lat1}), 2) + "
            f"pow(radians({lon2} - {lon1}) * cos(radians(({lat2} + {lat1}) / 2)), 2)"
            f"))")


def pad_lat_deg(radius_m: float = POI_MATCH_RADIUS_M) -> float:
    """Half-height of the bounding-box pre-filter, degrees of latitude."""
    return radius_m / METRES_PER_DEGREE


def pad_lon_deg(lat_deg: float, radius_m: float = POI_MATCH_RADIUS_M) -> float:
    """Half-width of the bounding-box pre-filter at `lat_deg`, degrees of
    longitude -- the `cos(latitude)` correction of D97 item 2, in Python, so
    the grid guard can be evaluated without a database."""
    import math

    return radius_m / (METRES_PER_DEGREE * math.cos(math.radians(lat_deg)))


def assert_grid_covers_pad(max_abs_lat_deg: float, *,
                           radius_m: float = POI_MATCH_RADIUS_M,
                           grid_deg: float = POI_GRID_DEG) -> None:
    """Fail LOUD if `POI_GRID_DEG` is too fine for `radius_m` at the widest
    latitude the address frame actually contains.

    `open_poi_match_sql`'s bucket join only inspects the 3x3 cell
    neighbourhood, which is a superset of the bounding box ONLY while a cell
    is at least as wide as the pad. If that ever stops holding -- a bigger
    radius, or a city far enough from the equator that the cos(latitude)
    blow-up in `pad_lon_deg` bites -- true matches would be silently dropped,
    and a silently-narrowed spatial join is precisely the failure D97 item 2
    already cost this module once. Raises rather than warns: a legality label
    that quietly loses grandfathering evidence is worse than a build that
    stops."""
    need = max(pad_lat_deg(radius_m), pad_lon_deg(max_abs_lat_deg, radius_m))
    if grid_deg < need:
        raise ValueError(
            f"POI_GRID_DEG={grid_deg} is narrower than the "
            f"{radius_m} m pre-filter pad ({need:.3e} deg) at latitude "
            f"{max_abs_lat_deg}. The 3x3 bucket neighbourhood in "
            "open_poi_match_sql would drop true matches. Widen POI_GRID_DEG "
            "(a wider cell is always correct, only slower) before building.")


def open_poi_match_sql(*, address_table: str = "analysis.address",
                       poi_view: str = "analysis.poi_supply_status",
                       radius_m: float = POI_MATCH_RADIUS_M,
                       grid_deg: float = POI_GRID_DEG) -> str:
    """Addresses within `radius_m` straight-line metres of a NOT-CLOSED
    commercial POI (`poi_status <> 'closed'` -- open OR unknown, D97 item 3:
    D79 forbids reading an unresolved POI as "nothing here") -- one
    `address_id` per row, the semi-join `build_legality_columns` UPDATEs
    against.

    THREE stages since 2026-09-15 (GTM-169), and the middle one is new:

      1. a GRID-BUCKET equi-join -- both sides floored to a `grid_deg` cell,
         the POI side fanned out to its 3x3 cell neighbourhood, joined on
         cell equality;
      2. the bounding-box pre-filter on raw lon/lat degrees (cheap, wide,
         and -- unlike the pre-2026-09-14 version -- actually conservative:
         see `METRES_PER_DEGREE` for the east-west under-coverage bug of
         D97 item 2);
      3. `_haversine_m_sql`, the real verified distance test.

    Stages 2 and 3 are BYTE-FOR-BYTE the old predicate, so the result set is
    unchanged; stage 1 only decides which pairs stage 2 ever sees, and the
    3x3 neighbourhood is a strict superset of the stage-2 box whenever
    `assert_grid_covers_pad` holds (guarded, not assumed).

    WHY IT EXISTS. Stages 2+3 alone gave DuckDB four inequality conditions
    and no equality, over a `poi_view` whose cardinality the planner cannot
    estimate through (`analysis.poi_supply_status` is a four-CTE view over
    3.8M `poi_dedup` rows; the plan estimated it at ~1 row). The planner
    therefore chose a NESTED_LOOP_JOIN: 332,041 addresses x 204,437
    not-closed commercial POIs = 6.8e10 pair evaluations, ~2,000 s, and the
    single longest step in the whole canonical order (3,449 s for
    `address-legality build` against 345 s for the next longest, D106).
    One equality condition turns it into a HASH_JOIN.

    WHY `AS MATERIALIZED` ON THE POI CTE -- NOT COSMETIC. Without it DuckDB
    inlines the CTE into each arm of the 3x3 fan-out and re-evaluates that
    entire four-CTE view NINE times; measured, that was SLOWER than the
    nested loop it replaced (561 s vs 296 s on a 50k-address sample, against
    0.9 s with the hint). Do not remove it."""
    cats = ", ".join(f"'{c}'" for c in sorted(commercial_poi_categories()))
    pad_lat = pad_lat_deg(radius_m)
    # Longitude degrees are shorter than latitude degrees by cos(latitude);
    # padding by the same fixed value used for latitude under-covers the
    # east-west axis (D97 item 2). Computed PER ROW from that address's own
    # latitude -- there is no single constant that is correct for every row.
    pad_lon = f"({radius_m} / ({METRES_PER_DEGREE} * cos(radians(a.lat))))"
    dist = _haversine_m_sql("p.lon", "p.lat", "a.lon", "a.lat")
    # floor(), not CAST/round(): floor is the only one that buckets negative
    # longitudes (every NYC lon is negative) the same way it buckets positive
    # latitudes, and both sides must agree on the cell edge exactly.
    cell = "CAST(floor({v} / " + str(grid_deg) + ") AS BIGINT)"
    return f"""
        WITH poi AS MATERIALIZED (
            SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat
            FROM {poi_view}
            WHERE poi_status <> 'closed' AND category IN ({cats})
        ),
        poi_cells AS (
            SELECT poi.lon, poi.lat,
                   {cell.format(v='poi.lon')} + ox.dx AS cell_lon,
                   {cell.format(v='poi.lat')} + oy.dy AS cell_lat
            FROM poi
            CROSS JOIN (VALUES (-1), (0), (1)) AS ox(dx)
            CROSS JOIN (VALUES (-1), (0), (1)) AS oy(dy)
        )
        SELECT a.address_id
        FROM {address_table} a
        JOIN poi_cells p
          ON p.cell_lon = {cell.format(v='a.lon')}
         AND p.cell_lat = {cell.format(v='a.lat')}
         AND p.lon BETWEEN a.lon - {pad_lon} AND a.lon + {pad_lon}
         AND p.lat BETWEEN a.lat - {pad_lat} AND a.lat + {pad_lat}
         AND {dist} <= {radius_m}
        GROUP BY a.address_id
    """


def open_poi_match_reference_sql(*, address_table: str = "analysis.address",
                                 poi_view: str = "analysis.poi_supply_status",
                                 radius_m: float = POI_MATCH_RADIUS_M) -> str:
    """The pre-GTM-169 single-stage form of `open_poi_match_sql`: bounding
    box then haversine, no grid bucket, no equality condition.

    KEPT DELIBERATELY, and only as a REFERENCE -- nothing in the pipeline
    calls it. It is the definition the bucketed query is pinned against
    (`test_bucketed_match_agrees_with_the_reference_on_boundary_cases`), so
    "the fast path returns the same rows" stays a machine-checked claim
    rather than an argument in a docstring. It is far too slow to run over
    the full frame (see `open_poi_match_sql` for the measurement)."""
    cats = ", ".join(f"'{c}'" for c in sorted(commercial_poi_categories()))
    pad_lat = pad_lat_deg(radius_m)
    pad_lon = f"({radius_m} / ({METRES_PER_DEGREE} * cos(radians(a.lat))))"
    dist = _haversine_m_sql("p.lon", "p.lat", "a.lon", "a.lat")
    return f"""
        SELECT a.address_id
        FROM {address_table} a
        JOIN (
            SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat
            FROM {poi_view}
            WHERE poi_status <> 'closed' AND category IN ({cats})
        ) p
          ON p.lon BETWEEN a.lon - {pad_lon} AND a.lon + {pad_lon}
         AND p.lat BETWEEN a.lat - {pad_lat} AND a.lat + {pad_lat}
         AND {dist} <= {radius_m}
        GROUP BY a.address_id
    """


# ------------------------------------------------------------ population

def build_legality_columns(con, pluto_csv: pathlib.Path | str = PLUTO_CSV,
                           *, dry_run: bool = False) -> dict:
    """Populate the nine raw PLUTO columns (seven original, plus `retailarea`
    and `bldgclass` added D97 item 3) plus `has_open_commercial_poi`,
    `legality` and `legality_basis` on `analysis.address`.

    THREE PASSES, all UPDATE ... FROM against the live table -- never a
    rebuild: `analysis.address` is DELETEd and re-INSERTed by
    `loci address-gaps` (D78), so this is a RE-APPLY step in the canonical
    pipeline order, exactly like `address-character build` /
    `address-access` / `transit-profile --re-sweep`. Idempotent; safe to run
    again; must be re-run after every `address-gaps` pass or these twelve
    columns come back NULL/FALSE.

      1. The nine raw PLUTO columns, by BBL join, read straight off the CSV
         with `read_csv_auto` -- never materialized into a pandas frame in
         this process (the file is 334 MB).
      2. `has_open_commercial_poi`, via `open_poi_match_sql()` -- this used
         to be the expensive step and the longest single step in the whole
         canonical order (178 s for the bare SELECT read-only, 3,449 s for
         the enclosing build in the 2026-09-15 re-baseline, against 345 s for
         the next longest step; D106). GTM-169 gave it a grid-bucket
         equi-join and the SELECT now runs in ~1 s over the full frame; what
         remains here is UPDATE write cost, not join cost. Still computed
         once and stored, not left as a live view -- see the module
         docstring.
      3. `legality` / `legality_basis`, via `legality_case_sql()` against the
         now-stored `has_open_commercial_poi` (cheap).

    Returns a report dict used both for the CLI's printed table and for
    AC-1's drift check: `with_bbl`, `null_zonedist1`, `null_rate` (over rows
    that HAVE a bbl -- a street-frame point with no bbl was never going to
    carry PLUTO fields and must not be counted against the 1% budget).
    """
    pluto_csv = pathlib.Path(pluto_csv)
    if not pluto_csv.exists():
        raise FileNotFoundError(
            f"MapPLUTO CSV not found at {pluto_csv}. Download it once from "
            "https://data.cityofnewyork.us/api/views/64uk-42ks/rows.csv?accessType=DOWNLOAD")

    cols = PLUTO_LEGALITY_COLUMNS
    if not dry_run:
        set_clause = ", ".join(f"{c} = p.{c}" for c in cols)
        con.execute(f"""
            UPDATE analysis.address AS a
            SET {set_clause}
            FROM (
                SELECT bbl, {', '.join(cols)}
                FROM (
                    SELECT bbl, {', '.join(cols)},
                           row_number() OVER (PARTITION BY bbl) AS rn
                    FROM read_csv_auto(?, ALL_VARCHAR = TRUE)
                    WHERE bbl IS NOT NULL AND bbl <> ''
                )
                WHERE rn = 1
            ) AS p
            WHERE p.bbl = a.bbl
        """, [str(pluto_csv)])

        # GTM-169: the bucketed pre-filter in open_poi_match_sql is only a
        # superset of the bounding box while a grid cell is at least as wide
        # as the pad. Check it against the latitudes THIS frame actually
        # holds, before the join runs, and raise rather than silently drop
        # grandfathering evidence.
        max_lat = con.execute(
            "SELECT max(abs(lat)) FROM analysis.address WHERE lat IS NOT NULL"
        ).fetchone()[0]
        if max_lat is not None:
            assert_grid_covers_pad(float(max_lat))

        con.execute("UPDATE analysis.address SET has_open_commercial_poi = FALSE")
        con.execute(f"""
            UPDATE analysis.address AS a
            SET has_open_commercial_poi = TRUE
            FROM ({open_poi_match_sql()}) AS m
            WHERE m.address_id = a.address_id
        """)

        legality, basis = legality_case_sql("a")
        con.execute(f"""
            UPDATE analysis.address AS a
            SET legality = {legality}, legality_basis = {basis},
                legality_run_at = now()
        """)

    with_bbl, null_z = con.execute("""
        SELECT count(*) FILTER (WHERE bbl IS NOT NULL AND bbl <> ''),
               count(*) FILTER (WHERE bbl IS NOT NULL AND bbl <> '' AND zonedist1 IS NULL)
        FROM analysis.address
    """).fetchone()
    null_rate = (null_z / with_bbl) if with_bbl else 0.0
    return {"with_bbl": int(with_bbl or 0), "null_zonedist1": int(null_z or 0),
            "null_rate": null_rate, "dry_run": dry_run,
            "pluto_csv": str(pluto_csv)}


def passthrough_view_sql(view_name: str = VIEW_NAME,
                         address_table: str = "analysis.address") -> str:
    """The DDL for `analysis.address_legality` -- a CHEAP passthrough over the
    stored columns (see module docstring for why this is no longer a live
    computation). GENERATED so sql/031's committed rendering cannot drift
    from this; `tests/test_address_legality.py::test_sql_file_matches_generator`
    pins the two together."""
    return (f"CREATE OR REPLACE VIEW {view_name} AS\n"
            f"SELECT address_id, has_open_commercial_poi, legality, legality_basis\n"
            f"FROM {address_table}")


def legality_distribution(con) -> dict:
    """{legality: count} over `analysis.address_legality` -- what
    `address-legality stats` and the report both print."""
    rows = con.execute(
        f"SELECT legality, count(*) FROM {VIEW_NAME} WHERE legality IS NOT NULL "
        "GROUP BY 1").fetchall()
    out = {v: 0 for v in LEGALITY_VALUES}
    out.update({k: int(v) for k, v in rows})
    return out
