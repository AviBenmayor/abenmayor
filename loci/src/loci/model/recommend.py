"""The recommendation card: one area, one category, seven graded claims, and a
verdict that is the MINIMUM of the load-bearing grades (D72 standing ruling).

WHY A CARD AND NOT A SCORE
---------------------------------------------------------------------------
The D72 red-team of the Gowanus reading is the whole reason this module exists.
Four claims of completely different evidential quality -- a clean DOB permit
record, a timing inference with no construction-start date behind it anywhere
in any NYC feed, a supply count taken from `in_all` instead of the principled
set, and a demand pool of 17,628 homes that had never been discounted for the
59% living in 51+-unit buildings with their own laundry rooms -- were averaged
into one confident paragraph. Averaging is exactly the operation that destroys
the information a reader needs: WHICH claim is holding the recommendation up,
and how good is that claim.

So the card states each claim separately, grades it A-D on its own evidence
with the rule written in `recommend_grades.yaml`, and takes the verdict from
the WORST load-bearing grade. A chain is as strong as its weakest link, and
here the weakest link is named, printed, and given the cheapest check that
would move it.

    A   measured, with a margin, from a source that enumerates the universe
    B   measured, but from a self-reported / prior-driven / coarser source
    C   thin, or the right measurement on the wrong universe
    D   not evidence: NULL, or a number that does not answer the question

THE RULING, IN CODE
---------------------------------------------------------------------------
`verdict_for()` may not return "act" while any load-bearing section is D. That
is not a convention in a docstring: `load_bearing` in the YAML names the five
sections, `overall_grade()` takes the max (= worst) over them, and
tests/test_recommend.py brute-forces every grade combination to prove no input
reaches "act" with a D present.

The current state of the world is that section 6 (economics) grades D for every
category in every borough, because the BizBuySell collection 403'd and
`comps_for()` returns n_comps=0 everywhere (model/comps.py's own docstring).
That means EVERY card this tool produces today says "do not act on this data",
and it names 3-5 P&Ls as the thing that would change it. That is the correct
output, not a bug: the project has a supply model and a demand model and no
income statement, and the ruling says you do not get to skip the income
statement by grading it generously.

WHAT THE CARD NEVER SAYS
---------------------------------------------------------------------------
No numeric "expected profit", ever. `comps_for()` yields a SUPPORTABLE RENT --
the rent a median comp's revenue could carry -- and a cushion. A profit figure
would require an operator's cost structure that Loci has never seen, and the
distance between "this rent is supportable" and "you will make $X" is exactly
where a screening tool turns into a pitch deck.

WHAT IS AN "AREA"
---------------------------------------------------------------------------
Every ELIGIBLE address inside a lat/lon box and/or an NTA, restricted to the
requested boroughs. Not a hex, not a corridor, not a single site: the card is a
statement about a neighbourhood-sized set of doorways, and every statistic in
it is a median (or a share) over that set. A box straddling two neighbourhoods
gets one card, and the card names both -- see `facts["neighborhoods"]`.

READ-ONLY, ALWAYS
---------------------------------------------------------------------------
Nothing here writes to the warehouse, and `connect_read_only()` retries the
lock rather than failing: a concurrent writer is the normal state of this
project (D69/D72 both landed against a warehouse another session was
rebuilding). `loci recommend` is safe to run mid-rebuild; the numbers it reads
are whatever was last committed.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import json
import math
import pathlib
import time

import pandas as pd
import yaml

from loci.categories import CATEGORIES
from loci.db import DEFAULT_PATH
from loci.db import PKG as PKG_ROOT
from loci.validation.google_places import GOOGLE_TYPES

RULES_PATH = PKG_ROOT / "model" / "recommend_grades.yaml"
CATEGORIES_YAML = PKG_ROOT / "categories.yaml"

#: The categories.yaml key that demotes a category from HEADLINE use (owner
#: ruling 2026-09-14, on the D30 clinic precedent). See
#: `non_headline_categories` for what the demotion does and does not touch.
HEADLINE_KEY = "headline"

#: Worst-first ordering. `worst()` is max() under this index, so "D" wins.
GRADES = ("A", "B", "C", "D")

SECTION_TITLES = {
    "demand_now": "Demand now",
    "arriving_homes": "Arriving homes",
    "supply_thinness": "Supply thinness",
    "addressable_demand": "Addressable demand",
    "space": "Space",
    "economics": "Economics",
    "coverage": "Coverage",
}
SECTION_ORDER = ("demand_now", "arriving_homes", "supply_thinness",
                 "addressable_demand", "space", "economics", "coverage")

BOROUGH_NAMES = {"MN": "Manhattan", "BK": "Brooklyn", "QN": "Queens",
                 "BX": "Bronx", "SI": "Staten Island"}


# ------------------------------------------------------------------ grades

def worst(*grades: str) -> str:
    """The worst of several grades. Unknown letters raise -- a typo and a real
    grade must not look the same (the `spec_for` habit, D63)."""
    for g in grades:
        if g not in GRADES:
            raise ValueError(f"not a grade: {g!r} (expected one of {GRADES})")
    return max(grades, key=GRADES.index) if grades else "D"


def cap(grade: str, ceiling: str) -> str:
    """`grade`, but never better than `ceiling`. Used for the supply-hash
    drift cap, where the measurement is sound but the universe is wrong."""
    return worst(grade, ceiling)


@dataclasses.dataclass(frozen=True)
class Section:
    key: str
    title: str
    grade: str
    reason: str
    facts: dict
    load_bearing: bool

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def load_rules(path: pathlib.Path | None = None) -> dict:
    """The owner-adjustable grading rules."""
    p = path or RULES_PATH
    return yaml.safe_load(p.read_text())


# -------------------------------------------------------- section grading
# Every function below is PURE: facts in, (grade, reason) out. No DB, no YAML
# read of its own. That is what lets tests walk the boundaries directly
# instead of assembling a warehouse.

def grade_demand_now(facts: dict, rules: dict) -> tuple[str, str]:
    """Context. ACS 5-year income + PLUTO units are an enumeration with a
    published margin; the grade is about the MARGIN, not the level."""
    r = rules["sections"]["demand_now"]
    inc = facts.get("median_hh_income")
    moe = facts.get("median_hh_income_moe")
    if inc is None or not inc or moe is None:
        return "D", "no ACS income for this area (no tract joined)"
    share = float(moe) / float(inc)
    if share < r["moe_share_max"]:
        return "A", (f"ACS 5-year + PLUTO units; income MOE {share:.0%} of the "
                     f"estimate (< {r['moe_share_max']:.0%})")
    return "B", (f"ACS 5-year + PLUTO units; income MOE {share:.0%} of the "
                 f"estimate (>= {r['moe_share_max']:.0%}) -- the level is soft")


def grade_arriving_homes(facts: dict, rules: dict) -> tuple[str, str]:
    """D72. `active` = a DOB permit was ISSUED OR RENEWED within 12 months (or
    expires in the future). It is NOT construction observed -- no NYC feed
    publishes a construction-start date, so a renewal separates "not abandoned"
    from "abandoned" and nothing finer.

    Two shares are computed and the worse band wins when they disagree:

      exposure-weighted  sum(units_active) / sum(units_permitted) over the
                         area's addresses -- "of the permitted units within
                         walking reach of this area, what share is alive"
      median address     the median over addresses of the per-address share --
                         "what does a TYPICAL doorway here see"

    They diverge when the activity is concentrated in a few large catchments,
    which is a real and adverse fact about the area, so the card does not get
    to pick the flattering one.
    """
    r = rules["sections"]["arriving_homes"]
    permitted = facts.get("units_permitted_sum")
    if permitted in (None, 0) or facts.get("units_active_sum") is None:
        return r["null_grade"], ("no permit-activity evidence on these addresses "
                                 "(NULL is not zero -- D72)")

    def band(share: float) -> str:
        if share >= r["active_share_b"]:
            return "B"
        if share >= r["active_share_c"]:
            return "C"
        return "D"

    ex = float(facts["units_active_sum"]) / float(permitted)
    med = facts.get("active_share_median")
    g = band(ex)
    if r.get("disagreement_takes_worse") and med is not None:
        g2 = band(float(med))
        if g2 != g:
            g = worst(g, g2)
            return g, (f"{ex:.0%} of permitted units active by exposure but the "
                       f"median address sees only {float(med):.0%} -- activity is "
                       f"concentrated, worse band taken; a renewal is not a shovel")
    return g, (f"{ex:.0%} of permitted units active (permit renewed, NOT "
               f"construction observed); {facts.get('units_stalled_sum', 0) or 0:,.0f} "
               f"units stalled")


def grade_supply_thinness(facts: dict, rules: dict) -> tuple[str, str]:
    """The ratio is only meaningful on the principled set (D52/D59) measured
    against a baseline fitted on the SAME supply hash. `analysis.poi_supply` is
    a VIEW: it moves the moment dedup re-runs or an anchor loads."""
    r = rules["sections"]["supply_thinness"]
    n = int(facts.get("n_ratio_addresses") or 0)
    if facts.get("ratio_median") is None or n == 0:
        return "D", "no supply ratio on these addresses -- `loci supply-ratio` has not run"

    if facts.get("supply_set") != "principled":
        grade, why = "C", (f"ratio computed on the '{facts.get('supply_set')}' set, "
                           f"not the principled one (D52/D59)")
    elif n >= r["n_addresses_a"]:
        grade, why = "A", f"principled set, hash {facts.get('live_hash')}, n = {n:,} addresses"
    elif n >= r["n_addresses_b"]:
        grade, why = "B", f"principled set, hash {facts.get('live_hash')}, only n = {n:,} addresses"
    else:
        grade, why = "C", f"only n = {n:,} addresses carry a ratio -- too few to median"

    if facts.get("hash_mismatch"):
        grade = cap(grade, r["hash_mismatch_max_grade"])
        why = (f"baseline fitted on supply {facts.get('baseline_hash')} but the live "
               f"set is {facts.get('live_hash')} -- ratio and baseline are not "
               f"comparable; capped at {r['hash_mismatch_max_grade']}")
    return grade, why


def regime_note(category: str, regime: str, rules: dict) -> str:
    notes = rules["sections"]["supply_thinness"]["regime_note"]
    return notes.get(regime, notes["not_fitted"])


def grade_addressable_demand(category: str, facts: dict, rules: dict) -> tuple[str, str]:
    """Homes within reach are not households in the market. Only laundry has a
    haircut today (laundry_haircut.yaml, D72 red-team finding 3); every other
    category reports raw `homes_400m` and says so, at C."""
    r = rules["sections"]["addressable_demand"]
    if category not in (r.get("haircut_categories") or []):
        return r["no_haircut_grade"], ("no category-specific haircut yet -- this is "
                                       "homes within reach, not households in the market")
    cov = facts.get("evidence_coverage")
    if cov is not None and float(cov) > r["evidence_coverage_a"]:
        return "A", (f"in-home haircut with building evidence on {float(cov):.0%} of "
                     f"addresses (> {r['evidence_coverage_a']:.0%})")
    return r["prior_grade"], (f"in-home haircut is size-class PRIORS "
                              f"(laundry_haircut v{facts.get('haircut_version', '?')}); "
                              f"building evidence covers only "
                              f"{0.0 if cov is None else float(cov):.1%} of addresses")


def grade_space(facts: dict, rules: dict) -> tuple[str, str]:
    """Context. DOF Storefront Registry (Local Law 157): self-reported, annual
    snapshot, never a listing, and NO rent or square footage exists at address
    grain anywhere public (D67)."""
    r = rules["sections"]["space"]
    reg = facts.get("storefronts_median")
    if reg is None:
        return "D", "no storefront registry coverage on these addresses"
    if float(reg) <= 0:
        return r["no_registry_grade"], ("median address has ZERO registered storefronts "
                                        "within 400 m -- nobody filed, so absence here "
                                        "is not evidence of absence")
    return r["base_grade"], (f"DOF Storefront Registry, self-reported, annual snapshot "
                             f"{facts.get('storefront_asof', 'unknown')} -- a filing, "
                             f"never a listing; no rent or sqft exists")


def grade_economics(comps: dict, rules: dict, revenue: dict | None = None) -> tuple[str, str]:
    """comps_for(), with the site-revenue model as the floor.

    Real P&Ls (comps with cash flow) are the only evidence that reaches B or A,
    and that is deliberate: nothing short of an operator's books tells you what
    a business at this site actually clears. But a category with a SHIPPED,
    GATED site-revenue calibration is no longer at "no evidence of economics"
    either -- there is a modelled revenue range and a rent ceiling, calibrated
    to the Economic Census county mean and shown out of sample to rank ZIPs
    better than both baselines. That earns C ("modelled, uncalibrated to local
    P&Ls"), never better, and the D74 rule that "act" needs >= B is untouched:
    C still makes "act" unreachable.

    A category whose calibration FAILED the gate, or that was never modelled at
    all, gets nothing from this path and stays D.
    """
    r = rules["sections"]["economics"]
    n = int(comps.get("n_comps") or 0)
    has_cash_flow = comps.get("cash_flow_p50") is not None
    modelled = bool((revenue or {}).get("revenue_p50") is not None)
    if n == 0 or not has_cash_flow:
        if modelled:
            rev = revenue or {}
            return r.get("modelled_grade", "C"), (
                f"no cash-flow comps, but the site-revenue model ships for this "
                f"category ({rev.get('revenue_model_version')}): median revenue "
                f"${rev.get('revenue_p50'):,.0f}/yr over {rev.get('n_revenue_addresses', 0):,} "
                f"addresses -- modelled, uncalibrated to local P&Ls")
        return r["no_cash_flow_grade"], (f"n_comps = {n}, no cash-flow data -- "
                                         f"rent_source '{comps.get('rent_source')}'")
    if n < r["n_comps_min"]:
        return r["thin_grade"], f"only {n} comps at {comps.get('level_used')} level"
    if comps.get("level_used") == r["a_level"]:
        return "A", f"{n} comps with cash flow at {r['a_level']} level"
    if comps.get("level_used") == r["b_level"]:
        return "B", f"{n} comps with cash flow at {r['b_level']} level"
    return r["thin_grade"], f"{n} comps, but only citywide -- not this market"


# ------------------------------------------------- coverage: the G9 ladder
# Owner ruling 2026-09-14, evidence in docs/coverage-validation-2026-09.md
# (§4 the per-category table, §9(2) the ruling), gate G9 of
# docs/CATEGORY-EXPANSION.md. The rule this replaced graded A whenever ANY
# analysis.coverage_validation row existed for the card's addresses -- a fact
# about whether the stratified sampler happened to draw this box, not about
# whether loci can see the category. Nothing about a drawn box makes a
# tailor_repair gap (37.5% of which are coverage holes) better evidence than a
# restaurant gap (1.0%), and the old rule graded the two identically.
#
# THE MEASUREMENT, exactly as the memo defines it (§2, §4, §10):
#   frame        analysis.coverage_validation rows with address_id IS NOT NULL
#                (the D58 address frame). The 2,970 h3_index rows are the
#                frozen pre-D38 hex frame -- a different unit, geometry and
#                radius -- and are NEVER pooled with these.
#   denominator  the MISSING arm: rows the screen still flags missing, i.e.
#                `analysis.address_category.ratio > 1.0` for that
#                (address, category). The present arm is the control, not a
#                denominator for a hole rate.
#   numerator    the D29-style split: Google returned >= 1 ON-TYPE place AND
#                loci's canonical layer holds none (n_local_canonical = 0), at
#                the same point and the same radius.
#   grade        the Wilson 95% UPPER bound on that share against the two
#                thresholds in recommend_grades.yaml. The bound, not the point
#                estimate: a grade is a promise, and the bound is the part of
#                the interval a promise has to survive.
#
# ON-TYPE RECOUNT, and why it matters more than it sounds. `includedPrimaryTypes`
# is looser than its name: fitness's 64 "holes" were sports_club and marina
# returns with ZERO gym or fitness_center hits (memo §8), and hair's query
# returned 945 nail_salon and 163 medical_clinic places nobody asked for. So the
# numerator is recomputed from the STORED per-row primaryType histogram
# (`ground_truth_types`) filtered to the CURRENT GOOGLE_TYPES entry -- which is
# what lets the 2026-09-14 removal of sports_club from fitness regrade fitness
# C -> A off rows already paid for, with no new Google spend. A row whose
# histogram is NULL contributes no on-type place; that is the conservative
# direction here -- it can only make a category look BETTER covered.

Z95 = 1.959963984540054   #: normal quantile for a two-sided 95% interval

#: One query, one frame. The join to analysis.address_category is what supplies
#: the missing/present arm: the sample was drawn against the screen as it stood,
#: so the arm is re-read from the screen as it stands now rather than frozen at
#: sample time. Rows for addresses the screen no longer carries drop out.
COVERAGE_FRAME_SQL = """
    SELECT cv.category, cv.n_local_canonical, cv.ground_truth_types, ac.ratio
    FROM analysis.coverage_validation cv
    JOIN analysis.address_category ac
      ON ac.address_id = cv.address_id AND ac.category = cv.category
    WHERE cv.address_id IS NOT NULL
"""


def wilson_upper(k: int, n: int, z: float = Z95) -> float | None:
    """Upper bound of the Wilson score interval for k successes in n trials.

    Wilson and not Wald: at k = 0 (convenience) the Wald interval is the single
    point 0.0, which would promise a perfectly-seen category off 251 rows."""
    if n <= 0:
        return None
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return min(1.0, centre + half)


def on_type_count(types_json, category: str) -> int:
    """Places Google returned whose primaryType is one loci ASKED for.

    `types_json` is the stored per-call histogram (VARCHAR JSON; NULL on rows
    written before D50). Absent or unparseable reads as zero on-type places."""
    wanted = set(GOOGLE_TYPES.get(category) or ())
    if not wanted or not isinstance(types_json, str):
        return 0
    try:
        hist = json.loads(types_json)
    except ValueError:
        return 0
    return sum(int(v) for k, v in hist.items() if k in wanted)


def coverage_hole_rates(con) -> dict[str, dict]:
    """Per-category true-coverage-hole rate over the whole address frame.

    CITY-WIDE, deliberately, and not restricted to the card's own addresses:
    the validation sample is a stratified draw over MN+BK (20 rows per category
    x income decile x arm), so any one box holds ~0 of its rows and an
    area-restricted rate would grade a category on whether the sampler happened
    to visit it. The claim a coverage grade makes is about the CATEGORY's
    visibility in this city, which is exactly what the sample measures.

    Every category in CATEGORIES gets an entry, including the ones with no
    validation data at all (clinic): a missing measurement has to be visible as
    one, not absent from the dict.
    """
    rows = con.execute(COVERAGE_FRAME_SQL).fetchdf()
    ratio = pd.to_numeric(rows["ratio"], errors="coerce")
    missing = rows[ratio > 1.0]                      # the MISSING arm, and only it
    out: dict[str, dict] = {}
    for cat in CATEGORIES:
        sub = missing[missing["category"] == cat]
        n = len(sub)
        holes = int(sum(1 for r in sub.itertuples()
                        if on_type_count(r.ground_truth_types, cat) >= 1
                        and r.n_local_canonical == 0))
        out[cat] = {"coverage_n_missing": n, "coverage_n_holes": holes,
                    "coverage_hole_rate": (holes / n) if n else None,
                    "coverage_hole_hi95": wilson_upper(holes, n)}
    return out


def grade_coverage(facts: dict, rules: dict) -> tuple[str, str]:
    """Can the model SEE this category's supply? PURE: the rate, the bound and
    n are measured by `coverage_hole_rates`; this reads the ladder only."""
    r = rules["sections"]["coverage"]
    n = int(facts.get("coverage_n_missing") or 0)
    hi = facts.get("coverage_hole_hi95")
    if not n or hi is None:
        return r["unvalidated_grade"], (
            "UNVALIDATED -- no address-frame coverage-validation rows for this "
            "category, so its gaps have never been checked against ground truth")
    rate = facts.get("coverage_hole_rate") or 0.0
    holes = int(facts.get("coverage_n_holes") or 0)
    band = (f"{holes}/{n} missing-arm rows are coverage holes: {rate:.1%}, "
            f"Wilson 95% upper bound {hi:.1%}")
    if hi <= r["hole_rate_hi95_a"]:
        return "A", f"{band} (<= {r['hole_rate_hi95_a']:.0%})"
    if hi <= r["hole_rate_hi95_b"]:
        return "B", (f"{band} (<= {r['hole_rate_hi95_b']:.0%}) -- a thin supply reading "
                     f"here may be a coverage hole")
    return "C", (f"{band} (> {r['hole_rate_hi95_b']:.0%}) -- a gap in this category is "
                 f"not decidable at site level")


@functools.cache
def non_headline_categories(path: pathlib.Path | None = None) -> frozenset[str]:
    """Categories carrying `headline: false` in categories.yaml.

    Owner ruling 2026-09-14 on the D30 precedent: clinic, tailor_repair and
    hair_barber, each at a 34-45% chance that a gap of theirs is a hole in the
    data rather than in the market. A demoted category may not LEAD:
    `rank_categories` sorts it behind every headline category, so it is never
    the first card, and `build_card` stamps `headline: False` so the card says
    why. It is demoted NOWHERE else -- it keeps its gap rows, its supply ratio,
    its gap_score contribution and its map layer (the signal-vs-filter rule,
    docs/CATEGORY-EXPANSION.md §4). Cached: the file cannot change mid-run."""
    doc = yaml.safe_load((path or CATEGORIES_YAML).read_text())
    return frozenset(slug for slug, entry in (doc.get("categories") or {}).items()
                     if (entry or {}).get(HEADLINE_KEY) is False)


# ---------------------------------------------------------------- verdict

def overall_grade(sections: list[Section]) -> str:
    """The worst LOAD-BEARING grade. Context sections cannot move it."""
    lb = [s.grade for s in sections if s.load_bearing]
    return worst(*lb) if lb else "D"


def verdict_for(sections: list[Section], rules: dict) -> dict:
    """The verdict, the blockers, and the cheapest check for each blocker.

    THE RULING: `by_grade` maps D to "do not act on this data", and since
    `overall_grade` is the max over load-bearing grades, a single load-bearing
    D makes "act" unreachable by construction. tests/test_recommend.py proves
    it over every combination rather than trusting this paragraph.
    """
    g = overall_grade(sections)
    blockers = [s for s in sections if s.load_bearing and s.grade == "D"]
    cheap = rules.get("cheapest_check") or {}
    return {
        "overall_grade": g,
        "verdict": rules["verdict"]["by_grade"][g],
        "blockers": [{"section": s.key, "title": s.title, "reason": s.reason,
                      "cheapest_check": cheap.get(s.key, "no cheap check recorded")}
                     for s in blockers],
    }


# ------------------------------------------------------- card assembly

def build_card(category: str, facts: dict, comps: dict, rules: dict) -> dict:
    """One category's card from already-assembled `facts`. Pure."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown Loci category {category!r}")
    lb = set(rules["load_bearing"])
    cat_facts = (facts.get("categories") or {}).get(category, {})
    merged = {**facts, **cat_facts}

    graders = {
        "demand_now": lambda: grade_demand_now(merged, rules),
        "arriving_homes": lambda: grade_arriving_homes(merged, rules),
        "supply_thinness": lambda: grade_supply_thinness(merged, rules),
        "addressable_demand": lambda: grade_addressable_demand(category, merged, rules),
        "space": lambda: grade_space(merged, rules),
        "economics": lambda: grade_economics(comps, rules, cat_facts.get("revenue")),
        "coverage": lambda: grade_coverage(merged, rules),
    }
    sections: list[Section] = []
    for key in SECTION_ORDER:
        grade, reason = graders[key]()
        sections.append(Section(key=key, title=SECTION_TITLES[key], grade=grade,
                                reason=reason, facts=_section_facts(key, category, merged,
                                                                    comps, rules),
                                load_bearing=key in lb))
    v = verdict_for(sections, rules)
    return {
        "area": facts.get("area"),
        "category": category,
        # Owner ruling 2026-09-14: a `headline: false` category may not lead a
        # recommendation (see `non_headline_categories`). It still gets a full
        # card -- the demotion is of the CLAIM, not of the measurement.
        "headline": category not in non_headline_categories(),
        "category_label": CATEGORIES[category].label,
        "tier": CATEGORIES[category].tier,
        "n_addresses": facts.get("n_addresses"),
        "boroughs": facts.get("boroughs"),
        "neighborhoods": facts.get("neighborhoods"),
        "supply_ratio_vs_base": cat_facts.get("ratio_median"),
        "regime": cat_facts.get("regime"),
        "regime_note": regime_note(category, cat_facts.get("regime", "not_fitted"), rules),
        "sections": [s.as_dict() for s in sections],
        **v,
        "asof": facts.get("asof"),
        "rules_version": rules.get("version"),
        "supply_hash": facts.get("live_hash"),
    }


def _section_facts(key: str, category: str, m: dict, comps: dict, rules: dict) -> dict:
    """The numbers the card PRINTS for a section -- deliberately separate from
    the numbers it GRADES on, so a reader can check the grade against the
    evidence rather than taking the letter on faith."""
    if key == "demand_now":
        return {k: m.get(k) for k in
                ("homes_400m_median", "median_hh_income", "median_hh_income_moe",
                 "reference_median_hh_income", "age_18_34_share", "renter_share")}
    if key == "arriving_homes":
        return {k: m.get(k) for k in
                ("units_permitted_sum", "units_active_sum", "units_stalled_sum",
                 "units_other_sum", "active_share_median", "units_permitted_median")}
    if key == "supply_thinness":
        return {"ratio_median": m.get("ratio_median"), "per_1k_median": m.get("per_1k_median"),
                "baseline_per_1k": m.get("baseline_per_1k"),
                "supply_400m_median": m.get("supply_400m_median"),
                "n_ratio_addresses": m.get("n_ratio_addresses"),
                "supply_set": m.get("supply_set"), "live_hash": m.get("live_hash"),
                "baseline_hash": m.get("baseline_hash"), "regime": m.get("regime"),
                "regime_note": regime_note(category, m.get("regime", "not_fitted"), rules)}
    if key == "addressable_demand":
        return {k: m.get(k) for k in
                ("homes_400m_median", "addressable_homes_median", "addressable_share",
                 "evidence_coverage", "haircut_version")}
    if key == "space":
        return {k: m.get(k) for k in
                ("share_with_vacant", "vacant_storefronts_median", "storefronts_median",
                 "storefront_asof")}
    if key == "economics":
        d = {k: comps.get(k) for k in
             ("n_comps", "level_used", "geo_value", "expected_revenue",
              "supportable_rent", "rent_source", "cushion", "cushion_basis")}
        d["revenue"] = m.get("revenue")
        return d
    if key == "coverage":
        return {k: m.get(k) for k in
                ("anchor_qualifies", "anchor_coverage", "anchor_sources",
                 "coverage_n_missing", "coverage_n_holes", "coverage_hole_rate",
                 "coverage_hole_hi95")}
    return {}


def rank_categories(facts: dict, categories: list[str] | None = None) -> list[str]:
    """Categories ordered by supply_ratio_vs_base ASCENDING -- thinnest first.
    A category with no ratio sorts last: absence of a measurement is not a
    thin measurement.

    A `headline: false` category (owner ruling 2026-09-14) sorts behind EVERY
    headline category, whatever its ratio, so it can never be the first card --
    which is what "may not lead a recommendation" means here. It keeps its
    place in the run and its own card; only the lead is denied it."""
    cats = categories or list(CATEGORIES)
    per = facts.get("categories") or {}
    demoted = non_headline_categories()

    def key(c):
        r = (per.get(c) or {}).get("ratio_median")
        return (c in demoted,) + ((1, 0.0) if r is None else (0, float(r)))
    return sorted(cats, key=key)


# ------------------------------------------------------------ warehouse

def connect_read_only(path=None, retries: int = 8, wait_s: float = 15.0):
    """Open the warehouse READ ONLY, retrying the lock a concurrent writer
    holds. Never kills anything: another session rebuilding is normal (D69)."""
    from loci import db as locidb

    target = path or DEFAULT_PATH
    last = None
    for i in range(retries):
        try:
            return locidb.connect(target, read_only=True)
        except Exception as exc:      # noqa: BLE001 -- duckdb raises several types
            last = exc
            if i < retries - 1:
                time.sleep(wait_s)
    raise RuntimeError(f"could not open {target} read-only after {retries} tries: {last}")


def _area_predicate(bbox: tuple[float, float, float, float] | None,
                    nta: str | None) -> tuple[str, list]:
    """SQL fragment + params selecting the area on `analysis.address a`."""
    clauses, params = [], []
    if bbox:
        lat0, lon0, lat1, lon1 = bbox
        clauses.append("a.lat BETWEEN ? AND ? AND a.lon BETWEEN ? AND ?")
        params += [min(lat0, lat1), max(lat0, lat1), min(lon0, lon1), max(lon0, lon1)]
    if nta:
        clauses.append("a.nta_code = ?")
        params.append(nta)
    if not clauses:
        raise ValueError("an area needs a --bbox or an --nta (or both)")
    return " AND ".join(clauses), params


def area_facts(con, area: str, *, bbox=None, nta=None, boroughs=("MN", "BK"),
               eligible_only: bool = True, supply_set: str = "principled") -> dict:
    """Every number the seven sections need, for one area, in six queries.

    Area-level statistics are MEDIANS over the area's addresses (shares and
    sums where a median would be meaningless), because each address's 400 m
    catchment overlaps its neighbours' and a mean would be dragged by
    whichever corner of the box happens to hold the most doorways.

    `eligible_only` is a NO-OP on any current run: D75 (2026-09-13, owner
    ruling) retired the eligibility gate and `analysis.address.eligible` is
    TRUE on every row. The predicate and the flag are kept so that a restored
    pre-D75 database still answers the question it was asked; new code should
    not reach for either.
    """
    from loci.model import density_elasticity as de
    from loci.model import supply_ratio as sr
    from loci.score.supply import supply_hash

    where, params = _area_predicate(bbox, nta)
    boro_holes = ", ".join("?" for _ in boroughs)
    # D84: LOT frame only, and in the ONE fragment every section's query reuses
    # so the pin cannot be applied to five of six. Every number below is a
    # median or a share over "the area's addresses": homes_400m, the supply
    # ratios, the active/stalled shares, the vacancy rate, the revenue band.
    # The street frame roughly doubles the point count in an industrial area
    # and contributes ZERO homes, so leaving it in would halve the median
    # homes_400m of exactly the areas this card is most often asked about, and
    # dilute every share toward the street network's geometry rather than the
    # neighbourhood's.
    base = (f"FROM analysis.address a WHERE a.borough IN ({boro_holes}) AND {where}"
            + " AND COALESCE(a.frame, 'lot') = 'lot'"
            + (" AND COALESCE(a.eligible, FALSE)" if eligible_only else ""))
    p = [*boroughs, *params]

    addr = con.execute(f"""
        SELECT a.address_id, a.bbl, a.borough, a.neighborhood, a.nta_code,
               a.homes_400m, a.addressable_homes_400m_laundry,
               a.units_permitted_400m, a.units_active_400m, a.units_stalled_400m,
               a.vacant_storefronts_400m, a.storefronts_400m, a.storefront_asof,
               a.supply_ratio_supply_hash
        {base}""", p).fetchdf()
    if addr.empty:
        raise ValueError(f"no eligible addresses in area {area!r}")   # wording pinned by a test

    demo = con.execute(f"""
        SELECT median(d.median_hh_income) AS median_hh_income,
               median(d.median_hh_income_moe) AS median_hh_income_moe,
               median(d.age_18_34_share) AS age_18_34_share,
               median(d.renter_share) AS renter_share
        FROM analysis.address_demographics d
        WHERE d.address_id IN (SELECT a.address_id {base})""", p).fetchdf().iloc[0]

    reference = con.execute(f"""
        SELECT median(d.median_hh_income) AS median_hh_income,
               median(d.age_18_34_share) AS age_18_34_share
        FROM analysis.address_demographics d
        JOIN analysis.address a USING (address_id)
        WHERE a.borough IN ({boro_holes}) AND COALESCE(a.eligible, FALSE)
          AND COALESCE(a.frame, 'lot') = 'lot'
    """, list(boroughs)).fetchdf().iloc[0]

    cats = con.execute(f"""
        SELECT c.category,
               median(c.supply_ratio_vs_base) AS ratio_median,
               median(c.supply_per_1k)        AS per_1k_median,
               median(c.supply_400m)          AS supply_400m_median,
               count(c.supply_ratio_vs_base)  AS n_ratio_addresses
        FROM analysis.address_category c
        WHERE c.address_id IN (SELECT a.address_id {base})
        GROUP BY 1""", p).fetchdf().set_index("category")

    # Site-revenue (D76): its own query, and TOLERANT of the columns being
    # absent. A warehouse built before the revenue migration, or one where
    # `loci revenue` has never run, must still produce a card -- it just
    # produces one whose economics section stays at grade D, which is the
    # honest reading of "no model has been applied here".
    try:
        revenue = con.execute(f"""
            SELECT c.category,
                   median(c.revenue_p25)  AS revenue_p25,
                   median(c.revenue_p50)  AS revenue_p50,
                   median(c.revenue_p75)  AS revenue_p75,
                   median(c.rent_ceiling) AS rent_ceiling,
                   count(c.revenue_p50)   AS n_revenue_addresses,
                   max(c.revenue_model_version) AS revenue_model_version,
                   median(c.revenue_cap_p50) AS revenue_cap_p50,
                   avg(CASE WHEN c.revenue_p50 IS NULL THEN NULL
                            WHEN c.capacity_bound THEN 1.0 ELSE 0.0 END) AS share_capacity_bound
            FROM analysis.address_category c
            WHERE c.address_id IN (SELECT a.address_id {base})
            GROUP BY 1""", p).fetchdf().set_index("category")
    except Exception:                     # noqa: BLE001 -- duckdb raises several types
        revenue = pd.DataFrame().rename_axis("category")

    anchors = con.execute(
        "SELECT category, anchor_sources, anchor_coverage, qualifies "
        "FROM analysis.category_anchor").fetchdf().set_index("category")

    # G9, owner ruling 2026-09-14: the per-category coverage-hole RATE over the
    # whole MN+BK address frame, not a count of validation rows inside this box.
    # See `coverage_hole_rates` for why the measurement is city-wide.
    coverage = coverage_hole_rates(con)

    evidence_bbls = {r[0] for r in con.execute(
        "SELECT DISTINCT bbl FROM analysis.address_laundry_evidence").fetchall()}

    live_hash = supply_hash(con, supply_set)
    baseline_doc = sr.load_baselines()
    baseline_hash = baseline_doc.get("supply_hash")
    haircut = sr.load_haircut()
    try:
        elast = de.load()
    except FileNotFoundError:
        elast = {"categories": {}}

    permitted = _fsum(addr["units_permitted_400m"])
    active = _fsum(addr["units_active_400m"])
    stalled = _fsum(addr["units_stalled_400m"])
    share_series = (pd.to_numeric(addr["units_active_400m"], errors="coerce")
                    / pd.to_numeric(addr["units_permitted_400m"], errors="coerce")
                    .replace(0, pd.NA))
    bbls = set(addr["bbl"].dropna().astype(str))

    facts = {
        "area": area,
        "bbox": list(bbox) if bbox else None,
        "nta": nta,
        "boroughs": list(boroughs),
        # The boroughs the area's addresses ACTUALLY sit in, which is what
        # decides the comp geography -- `boroughs` is only the request filter.
        "address_boroughs": sorted(set(addr["borough"].dropna())),
        "neighborhoods": sorted(set(addr["neighborhood"].dropna())),
        "n_addresses": len(addr),
        "asof": dt.date.today().isoformat(),
        # 1. demand now
        "homes_400m_median": _fmed(addr["homes_400m"]),
        "median_hh_income": _f(demo["median_hh_income"]),
        "median_hh_income_moe": _f(demo["median_hh_income_moe"]),
        "age_18_34_share": _f(demo["age_18_34_share"]),
        "renter_share": _f(demo["renter_share"]),
        "reference_median_hh_income": _f(reference["median_hh_income"]),
        "reference_age_18_34_share": _f(reference["age_18_34_share"]),
        # 2. arriving homes
        "units_permitted_sum": permitted,
        "units_active_sum": active,
        "units_stalled_sum": stalled,
        "units_other_sum": None if permitted is None else permitted - (active or 0) - (stalled or 0),
        "units_permitted_median": _fmed(addr["units_permitted_400m"]),
        "active_share_median": _fmed(share_series),
        # 3. supply thinness (per-category parts land below)
        "supply_set": supply_set,
        "live_hash": live_hash,
        "baseline_hash": baseline_hash,
        "hash_mismatch": bool(baseline_hash and live_hash and baseline_hash != live_hash),
        # 4. addressable demand
        "addressable_homes_median": _fmed(addr["addressable_homes_400m_laundry"]),
        "addressable_share": _ratio(_fsum(addr["addressable_homes_400m_laundry"]),
                                    _fsum(addr["homes_400m"])),
        "evidence_coverage": (len(bbls & evidence_bbls) / len(bbls)) if bbls else None,
        "haircut_version": haircut.get("version"),
        # 5. space
        "share_with_vacant": float((pd.to_numeric(addr["vacant_storefronts_400m"],
                                                  errors="coerce").fillna(0) >= 1).mean()),
        "vacant_storefronts_median": _fmed(addr["vacant_storefronts_400m"]),
        "storefronts_median": _fmed(addr["storefronts_400m"]),
        "storefront_asof": _asof(addr["storefront_asof"]),
    }

    per_cat = {}
    for cat in CATEGORIES:
        row = cats.loc[cat] if cat in cats.index else None
        anch = anchors.loc[cat] if cat in anchors.index else None
        base_doc = (baseline_doc.get("categories") or {}).get(cat)
        per_cat[cat] = {
            "ratio_median": None if row is None else _f(row["ratio_median"]),
            "per_1k_median": None if row is None else _f(row["per_1k_median"]),
            "supply_400m_median": None if row is None else _f(row["supply_400m_median"]),
            "n_ratio_addresses": 0 if row is None else int(row["n_ratio_addresses"]),
            "baseline_per_1k": sr.baseline_of(base_doc),
            "regime": ((elast.get("categories") or {}).get(cat) or {}).get("regime", "not_fitted"),
            "anchor_qualifies": None if anch is None else bool(anch["qualifies"]),
            "anchor_coverage": None if anch is None else _f(anch["anchor_coverage"]),
            "anchor_sources": None if anch is None else anch["anchor_sources"],
            **coverage[cat],
            "revenue": _revenue_facts(revenue, cat),
        }
    facts["categories"] = per_cat
    return facts


def _revenue_facts(revenue: pd.DataFrame, cat: str) -> dict | None:
    """The modelled revenue block for one category, or None when the model does
    not ship for it. None and a zero are different things and a card must never
    print the second when it means the first."""
    if revenue.empty or cat not in revenue.index:
        return None
    row = revenue.loc[cat]
    if _f(row.get("revenue_p50")) is None:
        return None
    return {"revenue_p25": _f(row.get("revenue_p25")),
            "revenue_p50": _f(row.get("revenue_p50")),
            "revenue_p75": _f(row.get("revenue_p75")),
            "rent_ceiling": _f(row.get("rent_ceiling")),
            "n_revenue_addresses": int(row.get("n_revenue_addresses") or 0),
            "revenue_model_version": row.get("revenue_model_version"),
            "revenue_cap_p50": _f(row.get("revenue_cap_p50")),
            "share_capacity_bound": _f(row.get("share_capacity_bound"))}


def _f(v):
    return None if v is None or pd.isna(v) else float(v)


def _fmed(s):
    v = pd.to_numeric(s, errors="coerce").dropna()
    return float(v.median()) if len(v) else None


def _fsum(s):
    v = pd.to_numeric(s, errors="coerce").dropna()
    return float(v.sum()) if len(v) else None


def _ratio(a, b):
    return None if a is None or not b else float(a) / float(b)


def _asof(s):
    v = s.dropna()
    return str(v.max())[:10] if len(v) else None


def borough_for_comps(facts: dict) -> str | None:
    """The comps CSV names boroughs in full ('Brooklyn'); the warehouse uses
    two-letter codes. A multi-borough area has no single comp geography, so it
    falls through to citywide rather than picking one."""
    boros = sorted({b for b in (facts.get("boroughs") or [])})
    addr_boros = facts.get("address_boroughs") or boros
    return BOROUGH_NAMES.get(addr_boros[0]) if len(addr_boros) == 1 else None


def neighborhood_for_comps(facts: dict) -> str | None:
    """Only when the area sits in ONE neighbourhood; a box straddling two has
    no neighbourhood-level comp set."""
    n = facts.get("neighborhoods") or []
    return n[0] if len(n) == 1 else None


def build_cards(facts: dict, rules: dict, categories: list[str] | None = None) -> list[dict]:
    """Cards for the requested categories, thinnest supply ratio first."""
    from loci.model.comps import comps_for

    boro = borough_for_comps(facts)
    hood = neighborhood_for_comps(facts)
    return [build_card(cat, facts, comps_for(cat, borough=boro, neighborhood=hood), rules)
            for cat in rank_categories(facts, categories)]


# -------------------------------------------------------------- rendering

def _n(v, fmt="{:,.0f}", dash="—"):
    return dash if v is None else fmt.format(v)


def summary_rows(cards: list[dict]) -> list[dict]:
    """The one-page area x category table: ratio, regime, grade, verdict."""
    return [{"area": c["area"], "category": c["category"],
             "supply_ratio_vs_base": c["supply_ratio_vs_base"],
             "regime": c["regime"], "grade": c["overall_grade"],
             "verdict": c["verdict"],
             "blockers": ", ".join(b["section"] for b in c["blockers"]) or "—"}
            for c in cards]


def render_summary_table(cards: list[dict]) -> str:
    out = ["| area | category | supply ratio | regime | grade | verdict | D sections |",
           "|---|---|---:|---|:-:|---|---|"]
    for r in summary_rows(cards):
        out.append(f"| {r['area']} | {r['category']} | "
                   f"{_n(r['supply_ratio_vs_base'], '{:.2f}×')} | {r['regime']} | "
                   f"**{r['grade']}** | {r['verdict']} | {r['blockers']} |")
    return "\n".join(out)


def render_card(card: dict, rules: dict) -> str:
    """One category's Markdown card. Every section prints its grade, its
    one-line reason, and the numbers behind it."""
    lines = [f"## {card['category_label']} (`{card['category']}`, tier {card['tier']})",
             "",
             f"**Verdict: {card['verdict'].upper()}** — overall grade "
             f"**{card['overall_grade']}** (worst load-bearing section). "
             f"Supply ratio {_n(card['supply_ratio_vs_base'], '{:.2f}×')} of the MN+BK "
             f"baseline, regime `{card['regime']}`.",
             ""]

    for s in card["sections"]:
        k, d = s["key"], s["facts"]
        tag = "load-bearing" if s["load_bearing"] else "context"
        lines.append(f"### {SECTION_ORDER.index(k) + 1}. {s['title']} — grade "
                     f"**{s['grade']}** ({tag})")
        lines.append(f"*{s['reason']}*")
        lines.append("")
        if k == "demand_now":
            ref = d.get("reference_median_hh_income")
            inc = d.get("median_hh_income")
            rel = "—" if not (ref and inc) else f"{inc / ref:.2f}× MN+BK"
            lines += [f"- Homes within 400 m (median address): **{_n(d['homes_400m_median'])}**",
                      f"- Median household income: **${_n(inc)}** ± ${_n(d['median_hh_income_moe'])}"
                      f" ({rel})",
                      f"- 18–34 share: **{_n(d['age_18_34_share'], '{:.1%}')}** · renter share "
                      f"{_n(d['renter_share'], '{:.1%}')}"]
        elif k == "arriving_homes":
            lines += [f"- Permitted units in the area's 400 m catchments, summed over "
                      f"addresses: **{_n(d['units_permitted_sum'])}** — catchments "
                      f"OVERLAP, so this is an exposure total, not a unit count",
                      f"- Active (permit renewed ≤12 mo or expiring in future): "
                      f"**{_n(d['units_active_sum'])}** · stalled "
                      f"**{_n(d['units_stalled_sum'])}** · lapsed-or-unknown "
                      f"**{_n(d['units_other_sum'])}**",
                      f"- Median address sees {_n(d['units_permitted_median'])} permitted units, "
                      f"{_n(d['active_share_median'], '{:.0%}')} of them active",
                      "- *Active means the permit was renewed, **not** that construction was "
                      "observed — no NYC feed publishes a construction-start date (D72).*"]
        elif k == "supply_thinness":
            lines += [f"- Median `supply_ratio_vs_base`: **{_n(d['ratio_median'], '{:.2f}×')}** "
                      f"({_n(d['per_1k_median'], '{:.3f}')} per 1,000 homes vs baseline "
                      f"{_n(d['baseline_per_1k'], '{:.3f}')})",
                      f"- Median supply within 400 m: {_n(d['supply_400m_median'])} POIs · "
                      f"n = {_n(d['n_ratio_addresses'])} addresses",
                      f"- Supply set `{d['supply_set']}`, live hash `{d['live_hash']}`, "
                      f"baseline hash `{d['baseline_hash']}`",
                      f"- Regime `{d['regime']}` — {d['regime_note']}"]
        elif k == "addressable_demand":
            lines += [f"- Homes within 400 m (median): **{_n(d['homes_400m_median'])}**"]
            if card["category"] in (rules["sections"]["addressable_demand"]
                                    .get("haircut_categories") or []):
                lines += [f"- Addressable after the in-home haircut: "
                          f"**{_n(d['addressable_homes_median'])}** "
                          f"({_n(d['addressable_share'], '{:.0%}')} of homes survive)",
                          f"- Building-level laundry evidence covers "
                          f"{_n(d['evidence_coverage'], '{:.1%}')} of addresses "
                          f"(haircut v{d['haircut_version']}; the rest carry size-class priors)"]
            else:
                lines += ["- *No category-specific haircut yet: this is homes within reach, "
                          "not households in the market.*"]
        elif k == "space":
            lines += [f"- Addresses with ≥1 vacant storefront within 400 m: "
                      f"**{_n(d['share_with_vacant'], '{:.0%}')}**",
                      f"- Median vacant storefronts nearby: {_n(d['vacant_storefronts_median'])} "
                      f"of {_n(d['storefronts_median'])} registered",
                      f"- DOF Storefront Registry snapshot {d.get('storefront_asof') or 'unknown'} "
                      f"— self-reported, never a listing; no rent or sqft published."]
        elif k == "economics":
            lines += [f"- Comps: **n = {_n(d['n_comps'])}** at `{d['level_used']}` level "
                      f"({d['geo_value']})",
                      f"- Expected revenue: {_n(d['expected_revenue'], '${:,.0f}')} · "
                      f"**supportable rent {_n(d['supportable_rent'], '${:,.0f}/yr')}** "
                      f"(source `{d['rent_source']}`)",
                      f"- Cushion: {_n(d['cushion'], '{:.0%}')} (`{d['cushion_basis']}`)"]
            rev = d.get("revenue") or {}
            if rev.get("revenue_p50") is not None:
                lines += [f"- **Modelled revenue** (site-revenue {rev.get('revenue_model_version')}, "
                          f"median of {_n(rev.get('n_revenue_addresses'))} addresses): "
                          f"**{_n(rev.get('revenue_p50'), '${:,.0f}/yr')}** "
                          f"(p25 {_n(rev.get('revenue_p25'), '${:,.0f}')} – "
                          f"p75 {_n(rev.get('revenue_p75'), '${:,.0f}')})",
                          f"- **Rent ceiling** at the category occupancy-cost ratio: "
                          f"{_n(rev.get('rent_ceiling'), '${:,.0f}/yr')} "
                          f"({_n((rev.get('rent_ceiling') or 0) / 12, '${:,.0f}/mo')})",
                          "- *The range is a PARAMETER band (lambda spread, income MOE, beta "
                          "refit spread), not the spread of real store outcomes; the level is "
                          "fitted to a county-wide anchor and has no out-of-sample test. A "
                          "typical operator at this site, not a specific one.*"]
                if rev.get("share_capacity_bound") is not None:
                    lines += [
                        f"- **Capacity ceiling** (PLUTO retail area on the lot x a per-category "
                        f"$/sq ft/yr band): median "
                        f"{_n(rev.get('revenue_cap_p50'), '${:,.0f}/yr')}; "
                        f"**{_n(rev.get('share_capacity_bound'), '{:.0%}')}** of addresses here "
                        f"are capped by it rather than by demand. A capped number is a statement "
                        f"about the size of the box, not about the catchment.*"]
            lines += [
                      f"- *No expected profit is emitted, ever — "
                      f"{rules['verdict']['never_emit']} is not a number this model has.*"]
        elif k == "coverage":
            lines += [f"- Registry anchor qualifies: **{d['anchor_qualifies']}** "
                      f"(coverage {_n(d['anchor_coverage'], '{:.2f}')}, "
                      f"sources `{d.get('anchor_sources')}`)",
                      (f"- True-coverage-hole rate (MN+BK address frame, on-type): "
                       f"**{_n(d['coverage_hole_rate'], '{:.1%}')}** "
                       f"(Wilson 95% upper bound {_n(d['coverage_hole_hi95'], '{:.1%}')}, "
                       f"{_n(d['coverage_n_holes'])} of {_n(d['coverage_n_missing'])} "
                       f"missing-arm rows)")
                      if d.get("coverage_n_missing") else
                      ("- True-coverage-hole rate: **never measured** — this category has "
                       "no address-frame validation rows, so nothing here has been checked "
                       "against ground truth"),
                      "- *A hole is: Google returns an on-type business inside the same "
                      "649 m circle where loci's canonical layer has none. The rate is "
                      "city-wide by design — the validation sample is stratified over "
                      "MN+BK, not over this box (docs/coverage-validation-2026-09.md).*"]
            if not card["headline"]:
                lines.append("- **Not a headline category** (owner ruling 2026-09-14, D30 "
                             "precedent): a gap here is not decidable at site level, so "
                             "this category may not LEAD a recommendation. It stays in the "
                             "screen as a signal.")
        lines.append("")

    if card["blockers"]:
        lines += ["### What would change the verdict", ""]
        for b in card["blockers"]:
            lines.append(f"- **{b['title']} (D)** — {b['reason']}. "
                         f"Cheapest check: {b['cheapest_check']}.")
        lines.append("")
    else:
        lines += ["*No load-bearing section grades D.*", ""]
    return "\n".join(lines)


def render_markdown(cards: list[dict], facts: dict, rules: dict,
                    warnings: list[str] | None = None) -> str:
    area = facts.get("area")
    head = [f"# Recommendation card — {area}", "",
            f"{facts['n_addresses']:,} eligible addresses · "
            f"{', '.join(facts['neighborhoods']) or 'unnamed'} · "
            f"boroughs {', '.join(facts.get('address_boroughs') or facts['boroughs'])} · "
            f"bbox `{facts.get('bbox')}`" + (f" · NTA `{facts['nta']}`" if facts.get("nta") else ""),
            "",
            f"Generated {facts['asof']} · grading rules v{rules.get('version')} "
            f"(`src/loci/model/recommend_grades.yaml`) · supply hash "
            f"`{facts.get('live_hash')}`",
            ""]
    for w in (warnings or []):
        head += [f"> **Warning:** {w}", ""]
    head += ["## Summary — area × category", "", render_summary_table(cards), "",
             "Grades: **A** measured with a margin from an enumerating source · "
             "**B** self-reported, prior-driven or coarser · **C** thin, or the right "
             "measurement on the wrong universe · **D** not evidence. The verdict is the "
             "WORST load-bearing grade (sections 2, 3, 4, 6, 7); sections 1 and 5 are "
             "context and cannot move it. A card may not say *act* while any load-bearing "
             "claim is at **D** (D72).", "",
             ("Caveats that travel with every number here: the supply baseline is REVEALED "
              "SUPPLY (D6) — 1.0× is normal for this city, never *correctly provisioned*, and "
              "under-provision is correlated with race net of income (Meltzer & Schuetz). "
              "Permit *activity* is a renewal, not a shovel. The storefront registry is "
              "self-reported and annual. No rent or square footage exists at address grain "
              "anywhere public."), "", "---", ""]
    body = "\n".join(head) + "\n\n---\n\n".join(render_card(c, rules) for c in cards)
    return body


def to_json(cards: list[dict], facts: dict, rules: dict,
            warnings: list[str] | None = None) -> dict:
    """The same fields as the Markdown, machine-readable."""
    ctx = {k: facts.get(k) for k in
           ("area", "bbox", "nta", "boroughs", "neighborhoods", "n_addresses", "asof",
            "live_hash", "baseline_hash", "hash_mismatch", "supply_set")}
    return {"area": ctx, "rules_version": rules.get("version"),
            "warnings": warnings or [], "summary": summary_rows(cards), "cards": cards}
