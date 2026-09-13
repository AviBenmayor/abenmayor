"""The government-filing lifecycle vocabulary: what a business must declare,
and in what order, on its way to opening a door.

Owner's ask (2026-09-13): "find when stores go live via what they must declare
to the government -- not just for chains." A chain announces a lease; an
independent operator announces nothing. But BOTH must file. This module is the
ordered vocabulary those filings are mapped onto, and it lives at package root
-- not under sources/ and not under model/ -- because both halves import it and
neither may depend on the other (see sources/cities/nyc/dob_permits.py, which
duplicates a helper rather than import a model).

--------------------------------------------------------------------------
THE STAGES, IN ORDER
--------------------------------------------------------------------------
`STAGES` is ORDERED, and the order is the claim: earlier is earlier in real
time, so `min(stage_rank)` over a business is "the earliest thing we saw" and
`max(stage_rank)` is "how far along it got". The rank is an ORDINAL, never a
duration -- the gap between rank 1 and 2 is not the gap between 2 and 3.

  rank stage               feed                              what it means
  ---- ------------------- --------------------------------- -------------
   1  liquor_application   SLA Pending Licenses f8i8-k2gm    somebody signed a
                                                             lease and wants to
                                                             serve alcohol there
   2  fitout_filing        DOB NOW Job Filings w9ak-ipjd     an architect filed
                                                             plans for an interior
                                                             build-out
   3  license_application  DCWP License Applications         the operator applied
                           ptev-4hud                         for the trade licence
   4  permit_issued        DOB NOW Approved Permits          DOB authorised the
                           rbx6-tga4 (General Construction)  work; crews can start
   5  sign_permit          DOB NOW Approved Permits          an awning is going
                           rbx6-tga4 (work_type='Sign')      up -- the most
                                                             storefront-specific
                                                             permit DOB issues
   6  license_issued       DCWP Issued Licenses w7w3-xahh    the trade licence
                                                             exists
   7  liquor_active        NYS SLA Active 9s3h-dpkz          the liquor licence
                                                             exists
   8  first_inspection     DOHMH 43nn-pn8j                   DOHMH walked in the
                                                             door. For food this
                                                             is the closest thing
                                                             the city publishes to
                                                             an OPENING DATE.
   9  outdoor_dining       (RESERVED -- not ingested)        DOT Dining Out NYC.
                                                             Declared so the
                                                             vocabulary is stable;
                                                             see below.

CAVEATS THE DATABASE CANNOT ENFORCE
-----------------------------------
1. **The order is typical, not guaranteed.** A restaurant can get its DOHMH
   permit before its liquor licence clears; a landlord can pull a sign permit
   for a tenant who never opens. Nothing here asserts a business passes through
   every stage, or passes through them in this order -- only that these are the
   stages, ranked by when they USUALLY happen.

2. **Only rank 5 and rank 8 are storefront-specific.** A `fitout_filing` on a
   mixed-use building may be a lobby renovation; a `permit_issued` may be for
   apartments upstairs. The DOB NOW storefront filter (sources/cities/nyc/
   dob_now_filings.py) narrows this and does not eliminate it.

3. **`outdoor_dining` is declared and never emitted.** DOT's Dining Out NYC
   roster is not a registered source and was not ingested in this pass.
   Reserving the label keeps `STAGES` stable when it lands -- adding a stage in
   the MIDDLE later would renumber every stored rank. Anything that persists a
   rank must therefore store the stage STRING, not the integer.

4. **Absence of an early stage is not absence of the event.** A business that
   needs no liquor licence, no DCWP licence and no DOB permit (a retail shop in
   a space already fitted out) appears ONLY at `first_inspection` if it serves
   food, and NOWHERE if it does not. Lead-time statistics computed over this
   table are conditioned on "filed something", which is a selected sample.
"""
from __future__ import annotations

#: The ordered stage vocabulary. Index+1 is the rank. NEVER reorder; never
#: insert in the middle without re-reading caveat 3 above.
STAGES: tuple[str, ...] = (
    "liquor_application",
    "fitout_filing",
    "license_application",
    "permit_issued",
    "sign_permit",
    "license_issued",
    "liquor_active",
    "first_inspection",
    "outdoor_dining",
)

#: stage -> 1-based rank.
STAGE_RANK: dict[str, int] = {s: i + 1 for i, s in enumerate(STAGES)}

#: Stages that mean "somebody is spending money to open here, but the door is
#: not open yet". The LEAD half of the lead-time measurement.
EARLY_STAGES: frozenset[str] = frozenset({
    "liquor_application", "fitout_filing", "license_application",
    "permit_issued", "sign_permit",
})

#: Stages that mean "the business exists and a regulator has seen it". The
#: TERMINAL half. `liquor_active` is deliberately NOT here: SLA's active file
#: carries `originalissuedate`, which for a renewed licence is the date the
#: FIRST licence issued at that premises, possibly decades ago -- using it as an
#: opening date would compute negative lead times.
OPEN_STAGES: frozenset[str] = frozenset({"license_issued", "first_inspection"})

#: Stages declared but not populated by any ingested feed. Asserted by the
#: ingest so a silently-empty stage is a known gap, not a broken adapter.
UNPOPULATED_STAGES: frozenset[str] = frozenset({"outdoor_dining"})


def stage_rank(stage: str) -> int:
    """1-based rank of `stage`. Raises on an unknown stage -- a typo'd stage
    string that silently sorted last would reorder the whole lifecycle."""
    try:
        return STAGE_RANK[stage]
    except KeyError:
        raise ValueError(
            f"unknown filing stage {stage!r}; expected one of {list(STAGES)}"
        ) from None


#: The `match_method` vocabulary for how a filing got its BBL. Ordered best to
#: worst; `unmatched` means the row has no BBL at all and is kept anyway.
MATCH_METHODS: tuple[str, ...] = (
    "feed_bbl",             # the feed published a BBL that exists in PLUTO
    "feed_bbl_unverified",  # well-formed BBL, absent from PLUTO 26v2 (new lot,
                            # condo unit BBL, or a demolished/merged lot)
    "pluto_address",        # house number + street + borough -> exactly one lot
    "pluto_nearest_30m",    # published point -> nearest PLUTO lot centroid <=30 m
    "unmatched",
)
