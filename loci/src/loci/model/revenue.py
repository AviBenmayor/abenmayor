"""Site-revenue model -- what a TYPICAL new store of category c could take at a
given address, with a range, a rent ceiling, and a gate that refuses to ship a
category the backtest cannot support.

TWO VERSIONS LIVE IN THIS FILE. `revenue.yaml`'s `model_version` selects one
and `revenue.yaml`'s `versions:` block holds everything that differs, so the
D81 numbers stay regenerable:

  revenue-v0    the shipped D81 model. epsilon pinned to 1 (revenue LINEAR in
                the local spend pool), lambda anchored on the Economic Census
                MEAN receipts per establishment, no capacity ceiling, no
                site-level cap on a negative gamma.
  revenue-v0.2  this file's default, built 2026-09-13 after the owner's
                critique of the Lion's Milk overshoot. Four changes, in the
                order they were diagnosed; section (7) below is the whole of
                it.

WHAT THIS ANSWERS, AND WHAT IT DOES NOT
---------------------------------------------------------------------------
The owner's question was "can we try to predict what a business could make?"
This module answers it for a TYPICAL operator of a category at a location. It
says nothing whatever about a SPECIFIC operator: concept quality, menu, price
point, operator skill, hours, frontage, corner-vs-midblock, and the lease
itself are all outside the model and are the larger part of the variance in
real outcomes. A number out of here is a property of the SITE, not of a
business plan.

THE FIVE EQUATIONS, IN FULL
---------------------------------------------------------------------------
For an address `a` and category `c`:

  (1) SPEND PER HOUSEHOLD -- CEX Table 1101 quintile columns, NY-MSA rebased.

        q(a)   = the quintile whose income bracket contains the address's own
                 census tract median_hh_income (breaks = the real published
                 Table 1101 "Lower limit" row)
        E_c(a) = L_c[q(a)] * share_c * ny_ratio_c

      L_c is the REAL per-quintile column of the CEX line mapped to c;
      `share_c` the documented allocation of that line to c; `ny_ratio_c` the
      Table 3004 New York figure over the Table 1101 national figure for the
      same line (1.0 where the line does not survive the MSA rollup). The
      rebase is flat across quintiles because no BLS table crosses metro and
      quintile at once -- stated as the assumption it is.

      `convenience` has no CEX line at all and falls back to spend.yaml's
      documented affine form, E = s0 * (1 + eta * (idx_q - 1)).

  (2) SPEND POOL -- the 400 m walk-shed, the project's one "within reach".

        Pool_c(a) = homes_400m(a) * E_c(a)

      homes_400m is residential UNITS within 400 m network metres (D73), read,
      not recomputed. Units are treated as households; the ACS occupancy gap
      is one more constant that lambda absorbs.

  (3) CAPTURE SHARE -- Huff, with every store of equal attractiveness.

      A new entrant at the address is one competitor among n+1 of average
      attractiveness, so attractiveness cancels and only distance survives:

        s_c(a) = d_0^-beta / (d_0^-beta + SUM_i d_i^-beta)

      Incumbent distances are not stored individually (11.5M address-category
      pairs x n incumbents is not a table). They enter through RINGS: one
      Dijkstra sweep to 800 m yields, per address and category, the count
      n_r of principled incumbents in each network-distance ring, and the
      denominator is the exact expectation of d^-beta over a uniform annulus:

        K_r(beta) = E[d^-beta | r_in < d <= r_out]
                  = 2 (r_out^(2-beta) - r_in^(2-beta)) / ((2-beta)(r_out^2 - r_in^2))
        K_r(2)    = 2 ln(r_out/r_in) / (r_out^2 - r_in^2)
        Dnm_c(a)  = SUM_r n_r(a,c) * K_r(beta)
        s_c(a)    = 1 / (1 + Dnm_c(a) / K_self(beta))

      K_self is K over the innermost ring [d_floor, r_1] -- the entrant's own
      ring. The inner edge of ring 0 is floored at `d_floor_m` (50 m) because
      d^-beta diverges at zero and a store is not at zero distance from its own
      customers. Incumbents beyond 800 m are truncated, which biases every
      share UP by a known, one-signed and small amount (at beta = 2 a
      competitor at 1,200 m carries 0.7% of the pull of one at 100 m).

      The APPROXIMATION here is within-ring: two laundromats 110 m and 190 m
      away are both charged K_1. At 100 m rings that is small relative to the
      distance measurement itself.

      THE EXPONENT ON THE WHOLE DENOMINATOR IS ALSO FITTED. The shipped form
      is s = (1 + D/K_self)^-gamma, and gamma is selected inside every
      backtest fold alongside beta:

        gamma = 1   textbook Huff, the pre-registered v0 form
        gamma = 0   no competition term: revenue is demand alone
        gamma < 0   agglomeration dominates -- more nearby establishments
                    means a BIGGER business

      Fitting gamma rather than fixing it at 1 is the honest response to what
      the backtest found: against CBP establishment size the textbook capture
      share correlates NEGATIVELY in 7 of 10 categories (restaurant -0.81,
      bar -0.74). That is not a bug and it is consistent with D70 -- nothing
      clusters at ZIP grain, but a ZIP-grain incumbent count is partly a proxy
      for "is this a retail street", and a closed walk-shed model cannot see
      corridor demand. The fitted sign is reported per category; a negative
      gamma is a statement about the BACKTEST GRAIN, not a licence to believe
      competition is good for a business.

      beta is FITTED (section 5), never assumed. The density-elasticity regime
      from density_elasticity.yaml is carried as a REPORTED FLAG only and
      enters no equation -- D70's coefficients are descriptive decade averages
      and D68 ruled that a rejected predictor may not be quoted forward.

  (4) CALIBRATION -- lambda from the Economic Census county anchor.

      R_hat_c(a) = Pool_c(a) * s_c(a) is uncalibrated: it is household spend
      inside one walk-shed times a share, which is neither a revenue nor a
      total. lambda_c makes it one:

        lambda_c(county) = (RCPTOT_c / ESTAB_c)          [EC, county grain]
                           / mean_{p in principled POIs of c in county} R_hat_c(p)

      i.e. the constant that makes the MEAN predicted revenue over the
      county's existing establishments equal the real mean revenue per
      establishment. R_hat at an existing establishment excludes that
      establishment from its own incumbent set (one count removed from ring 0).

      TWO ESTIMATORS EXIST AND BOTH SHIP. The per-store form above is the one
      used, because the deliverable is per-site revenue. The total-conserving
      alternative, lambda = RCPTOT / SUM_p R_hat, is reported beside it; they
      differ exactly by our establishment count over the EC's, which is itself
      a coverage diagnostic (D40's 2-8x POI/ZBP gap, measured again here).

      WHAT lambda MEANS AND WHAT IT HIDES. It is NOT leakage alone. It is one
      scalar absorbing: true leakage out of the walk-shed, inflow from
      commuters and visitors, non-household demand, the CEX mapping error, the
      unit-to-household gap, and the POI-count-vs-EC-count gap. It therefore
      makes the model's LEVEL correct by construction at county grain and
      leaves only the CROSS-SECTIONAL VARIATION as a claim. Kings and New York
      County are calibrated separately and the two lambdas are reported side by
      side precisely so a disagreement is visible: if they disagree, no single
      constant describes New York and the level for a third county is unknown.

  (5) THE BACKTEST -- out of sample, against two baselines and a placebo.

      No revenue figure exists below county grain anywhere public (verified:
      ecnbasic's finest sub-state geography is county; CBP/ZBP never publish
      receipts; the NYS DTF file is 4-digit NAICS and does not break out the
      boroughs). So the out-of-sample target is a PROXY: CBP 2023
      ZIP x NAICS establishment counts by employment-size band, converted to
      expected employees per establishment through band midpoints.

        emp_per_estab(zip, c) = SUM_b ESTAB_b * midpoint_b / SUM_b ESTAB_b

      A cell whose bands account for less than 80% of its own "001" total has
      suppressed rows and is dropped, never imputed.

      Test: does predicted revenue per establishment track employees per
      establishment across MN+BK ZIPs, leave-one-ZIP-out, better than

        baseline 1  the county's EC revenue per establishment (no site
                    information at all -- constant inside a county), and
        baseline 2  homes_400m alone (demand pool, no spend gradient, no
                    competition)?

      plus a PLACEBO: category c's model must predict c's own employees per
      establishment better than it predicts the other modelled categories'. A
      model that tracks every category equally is tracking generic density.

      THE PROXY IS THE WEAKEST LINK AND IT IS NAMED HERE. Employees per
      establishment is a revenue proxy only insofar as revenue per employee is
      roughly constant within a category. For a coin laundry it is close to
      meaningless (staffing is near-flat in revenue), and that is a reason to
      expect laundry to fail the gate rather than a reason to excuse it if it
      does.

      WHAT THE FIRST RUN FOUND, recorded here because it shaped the form.
      With the competition exponent pinned at the textbook gamma = 1, the
      capture share correlated NEGATIVELY with establishment size in 7 of 10
      categories (restaurant -0.81, bar -0.74, fitness -0.74, cafe_bakery
      -0.72, hair_barber -0.65, nails_beauty -0.62, laundry -0.33) and every
      category lost to at least one baseline. The demand pool alone
      (homes x CEX spend) was the strongest component everywhere, and it beat
      homes-only in 8 of 10 -- so the CEX income gradient earns its place. The
      competition term did not. gamma was therefore made a fitted parameter
      with a grid spanning competitive, neutral and agglomerative, selected
      inside every fold; see revenue.yaml's disclosure of that ordering.

      THE FAILURE CRITERION IS CONCRETE. A category ships iff, on held-out
      ZIPs, Spearman(model) >= 0.20 AND exceeds BOTH baselines by >= 0.05 AND
      passes the placebo. A category that does not is recorded in the
      calibration YAML as `gate: fail`, its revenue columns are left NULL, and
      its recommendation card keeps grade D. `loci revenue fit` refuses to
      write the YAML at all if NO category passes -- there would be nothing to
      ship and a file saying so would be mistaken for a shipped model.

  (6) THE RANGE. p25/p75 are a PARAMETER band, not a prediction interval:

        p{25,75} = p50 * exp(-/+ 0.6745 * sigma_log)
        sigma_log^2 = sigma_lambda^2 + sigma_income^2 + sigma_beta^2

      sigma_lambda from the Kings-vs-New York disagreement (floored, because
      two counties agreeing is not evidence a third would); sigma_income from
      moving the tract median income by +/- 1 SE (= MOE / 1.645) and re-reading
      the quintile, which is a genuine discrete jump at a boundary;
      sigma_beta from the spread of the leave-one-ZIP-out refits. It says
      NOTHING about how far a real store's takings sit from the model -- that
      dispersion needs P&Ls and is exactly what keeps the card at grade C.

  (7) WHAT v0.2 CHANGES, AND WHY
---------------------------------------------------------------------------

      v0 overshot a real business by a factor of roughly two (Lion's Milk, 104
      Roebling: v0 shipped $2.49M against a bottom-up build of ~$1.4-1.5M and
      an Economic Census Kings cafe mean of $676k). Four corrections, each
      independently switchable, each one-signed DOWNWARD at a high-pool site:

      (7a) POOL ELASTICITY epsilon, FITTED.

             R_hat_c(a) = Pool_c(a)^epsilon_c * P_c(a)^delta_c * s_c(a)

           v0's Pool^1 is elasticity 1 BY CONSTRUCTION: double the households
           in the walk-shed and the model doubles the revenue. Neither the
           owner's prior nor the retail literature supports that; a cafe in a
           dense, rich walk-shed is a somewhat better cafe, not a four-times
           bigger one, once price level is accounted for. epsilon is therefore
           a fitted parameter on [0.0 .. 1.0] step 0.1, selected INSIDE every
           leave-one-ZIP-out fold jointly with beta and gamma, against the same
           CBP employees-per-establishment target.

           IDENTIFICATION, STATED PLAINLY AND IT IS WEAK. Spearman is
           rank-based and x -> x^epsilon is monotone for epsilon > 0, so if the
           prediction for a ZIP were simply that ZIP's pool, epsilon would be
           EXACTLY unidentified. It is identified only through two channels:
           (i) the prediction for a ZIP is the MEAN over that ZIP's
           establishments of Pool^epsilon * s, and a mean of powers is not a
           power of the mean, so the within-ZIP dispersion of pools enters; and
           (ii) lambda is fitted per county, so epsilon moves the two counties'
           predictions relative to each other. Both channels are thin. The
           skill-versus-epsilon profile is therefore REPORTED IN FULL per
           category (`epsilon_profile`) so a flat profile is visible as a flat
           profile rather than hidden behind an argmax.

           WHAT THE FIT CAME BACK WITH, AND WHY epsilon IS NOT TAKEN FROM IT.
           The unconstrained search was run first (2026-09-13) and chose
           epsilon = 0 in seven of nine categories: it DELETED the household
           spend pool. Three facts, not one:

             - the profile is nearly flat. Restaurant ran 0.8375 at epsilon = 0
               to 0.8024 at epsilon = 1 -- 0.035 of Spearman across the entire
               grid, inside the fold-to-fold spread of the held-out score. A
               flat profile is not an estimate of anything.
             - at ZIP grain the pool, tract income and incumbent count are
               collinear; all three read "is this a dense retail district". With
               P^delta and a negative gamma free to absorb that, the pool adds
               nothing to the RANKING and the search drops it.
             - what remains once it is dropped is lambda * P^delta *
               (incumbent density)^-gamma, whose only spatial signal is HOW MANY
               SHOPS ARE ALREADY THERE. That is the rejected D1 thesis wearing a
               fitted exponent, and THE PLACEBO CAUGHT IT: at epsilon = 0 every
               category's model predicted every other category's employment
               about equally well (restaurant's own target: own model 0.837,
               cafe's 0.871, bar's 0.854), because the only category-specific
               content in the whole model -- the CEX spend gradient -- lives in
               the pool that had just been deleted.

           SO THE GATE PICKS EPSILON, NOT AN ARGMAX AND NOT A PRIOR. The whole
           model family is refitted at every epsilon on the grid -- beta,
           gamma, delta and lambda all re-selected inside every
           leave-one-ZIP-out fold at each one -- the FULL gate (both baselines
           plus the cross-category placebo) is evaluated at each one, and a
           category ships at THE SMALLEST EPSILON IT STILL SURVIVES, subject to
           a structural floor. That is the most compression of the spend pool
           the out-of-sample evidence will support, and it answers the owner's
           question directly: how modest can the difference between two sites
           be before the model stops being a model of THIS category?

           THE FLOOR IS LOAD-BEARING (revenue.yaml `epsilon_floor` = 0.3).
           "Smallest passing epsilon" needs one, because the gate can be passed
           by a model with no demand pool at all: on the 2026-09-13 scan
           cafe_bakery passed at epsilon = 0.0, where the only spatial signal
           left is incumbent density. 0.3 is the bottom of the owner's stated
           range and of the published retail demand elasticities; a model
           claiming less responsiveness to the local spend pool than any
           published estimate is not a demand model whatever its Spearman. A
           category that passed only below the floor is RECORDED as such
           (`epsilon_passed_below_floor`) and refused on the D1 guardrail, not
           on skill.

           WHAT IT FOUND (2026-09-13). Restaurant passes at epsilon 0.6, 0.7,
           0.8, 0.9 and 1.0 and fails the placebo at 0.5 and below, so 0.6
           ships. The owner's prior was 0.3-0.5 and the backtest REFUSES it:
           under about 0.6 the restaurant model stops being distinguishable
           from the cafe model, which is exactly what the placebo exists to
           detect. 0.6 is still a real move off v0's 1.0 and it is not bought
           with skill -- the held-out Spearman RISES, 0.763 to 0.822.

           `epsilon_gate_scan` records the gate verdict, the held-out Spearman
           and the placebo margin at EVERY epsilon, so the shape of that cliff
           is in the shipped artefact rather than in someone's notes. The
           parsimony tie-break (`epsilon_parsimony_tolerance`) still runs
           inside every fold and breaks ties among the remaining axes.

           THE SELECTION BIAS THIS INTRODUCES, NAMED. beta, gamma, delta and
           lambda are re-selected inside every fold, so their contribution to
           the reported skill is honestly out of sample. EPSILON IS NOT: it is
           chosen once per category by reading the gate verdict off the same 73
           held-out folds that then report the skill. The reported Spearman at
           the shipped epsilon is therefore optimistic by the usual
           one-parameter selection amount. What the scan legitimately
           establishes is the SHAPE -- that the placebo margin crosses zero
           between 0.5 and 0.6 for restaurant, sharply and monotonically -- not
           a re-validated level. Removing this would need a held-out CITY, not
           a held-out ZIP, and there is not one.

      (7b) PRICE INDEX delta -- the owner's "difference in avg price" channel,
           REPORTED SEPARATELY, kept distinct from the household-count channel.

             P_c(a) = tract median_hh_income / county median tract income

           Revenue = customers x ticket. (7a) damps the CUSTOMERS channel;
           P^delta is the TICKET channel, and it is a different claim: a
           Williamsburg cafe charges more per flat white than a Sunset Park
           cafe. delta is fitted on [0 .. 0.5] step 0.1 inside every fold, and
           the calibration records the held-out Spearman WITH and WITHOUT it
           (`price_index`), so "does an income price level add skill beyond an
           income-graded spend pool?" is answered as a number and not asserted.
           It is shipped only where it adds skill; where it does not,
           delta = 0 and the term is absent from the equation.

           It is NOT double-counting the CEX income gradient. E_c(a) already
           moves with the tract's income QUINTILE because the household budget
           shifts; P^delta is the price level of the same basket. They are
           collinear enough that the fit will struggle to separate them, and
           that is precisely why the delta = 0 comparison is reported.

      (7c) MEDIAN ANCHOR, not the mean.

           v0 set lambda so the MEAN prediction over a county's establishments
           equalled RCPTOT/ESTAB -- Kings cafes $676k. That is a mean over a
           right-skewed distribution: a handful of large operators pull it up
           and a model calibrated to it over-predicts the TYPICAL shop, which
           is the one an owner is deciding about. v0.2 anchors the MEDIAN:

             rev_per_emp(county, c) = RCPTOT_c / EMP_c            [EC]
             emp_median(county, c)  = the band midpoint of the CBP
                                      employment-size band containing the
                                      median establishment, bands ordered
                                      ascending and cumulated over ESTAB
             M_target               = emp_median * rev_per_emp
             lambda_median          = M_target / median_p R_hat_c(p)

           The band -> revenue map is EC's own revenue per employee for that
           county x NAICS applied to the existing `band_midpoints` constant, so
           there is one definition of "how many employees is band 220" in the
           codebase and the backtest target and the anchor cannot disagree
           about it. Worked, Kings 722515: EC RCPTOT $642.1M / EMP 7,809 =
           $82,227 per employee; CBP 2023 bands 492/276/201/71/3 cumulate past
           half of 1,043 inside band 220 (5-9 employees, midpoint 7.0); 7.0 x
           $82,227 = $575,589 against the EC mean of $675,905, a ratio of
           0.852. Both lambdas are computed and BOTH ship in the calibration
           (`lambda_per_store`, `lambda_median`, `lambda_median_over_mean`) so
           the size of this correction is visible per category and county.

           WHAT IT DOES NOT FIX: survivorship. The Economic Census and CBP both
           observe businesses that EXIST. Neither the mean nor the median of a
           surviving population is the expectation for a new entrant, which
           includes the ones that fail. The median anchor narrows the bias; it
           does not remove it, and no public source can.

      (7d) CAPACITY CEILING -- the term v0 did not have at all.

             area(a)      = PLUTO `retailarea` on the address's BBL, divided by
                            the DOF Storefront Registry count of storefronts on
                            that BBL when that count exceeds 1 (flagged), or a
                            category-typical footprint from revenue.yaml when
                            retailarea is 0/NULL (flagged)
             cap_q(a, c)  = area(a) * psf_q[c]          q in {25, 50, 75}
             revenue_q    = min(model_q, cap_q)

           A 1,000 sq ft one-register cafe and a 5,000 sq ft cafe got the same
           number in v0, because nothing in (1)-(4) knows how big the box is.
           `psf` is a CEILING band, not a central estimate of productivity: it
           is roughly the 75th-to-95th percentile of realised sales per square
           foot for the category, because the question it answers is "what is
           the most this box could plausibly turn over", not "what does a
           typical box turn over". Sources and the per-category band are in
           revenue.yaml's `capacity:` block.

           The cap is applied AFTER lambda and is NOT inside the fit. It cannot
           be: the calibration's observations are POIs with a lat/lon and no
           BBL, so no retail area exists for them. Consequences, stated: the
           county median of the SHIPPED (capped) numbers can fall below the
           median anchor, by construction and only downward; and the cap has no
           out-of-sample test of its own. `capacity_bound` is stored per
           address x category so every capped row is identifiable, and
           `revenue_cap_p50` is stored beside it so the cap is auditable
           without re-deriving it.

      (7e) GAMMA AT SITE LEVEL -- capped at the corridor-neutral value.

             s_site = min(s(beta, gamma), 1.0)   equivalently  gamma_site =
                                                 max(gamma, 0)

           gamma < 0 came out of the ZIP-grain backtest and it is REAL AT THAT
           GRAIN: a ZIP with many restaurants per household is a ZIP with
           restaurant corridors, and corridors draw demand from outside any
           400 m walk-shed. But the sign does not transfer to an address, for a
           reason that is about what the regression saw. At ZIP grain the
           incumbent count varies BETWEEN neighbourhoods and proxies "is this a
           retail district" -- an omitted-variable channel the closed walk-shed
           model has no other way to see. At site grain, within one corridor,
           the incumbent count varies because of ENTRY, and entry is the thing
           competition theory says divides a fixed pool. Reading the
           between-neighbourhood coefficient as a within-corridor causal effect
           is the ecological fallacy in its textbook form, and at the extreme
           it is absurd: v0 multiplied 104 Roebling's restaurant number by
           (1 + D/K_self)^0.25 purely for having 104 restaurants within 400 m,
           and 104 Roebling's CAFE number by (1 + D/K_self)^0.75 for having 28
           cafes within 400 m -- a 6.7x multiplier on a cafe for being
           surrounded by cafes. The cap keeps gamma in the FIT (it carries the
           ZIP-level skill that the gate measures and it is what makes the
           reported Spearman honest) and refuses to let it RAISE any single
           site above the corridor-neutral share. For a category whose fitted
           gamma is negative this makes the site-level competition term vanish
           entirely -- every site gets s = 1 -- which is the correct statement
           of what we actually know: at one address, we do not know that
           neighbours help, and we are not willing to say they do.

           Categories with gamma > 0 are untouched: there the fit and the site
           agree that competition divides the pool, and it still bites.

           LAMBDA IS FITTED ON THE CAPPED FUNCTION, and that is not a detail.
           An establishment sits on a retail corridor, so for gamma < 0 its
           UNCAPPED share is a multiplier of several while every shipped site
           gets exactly 1.0. Calibrating lambda against the uncapped mean and
           applying it to capped predictions divides the entire level by the
           median establishment's agglomeration multiplier -- measured at ~13x
           for Manhattan restaurants on the first v0.2 apply, which put the
           median Manhattan restaurant at $130k against a median anchor of
           $1.67M. So the division of labour is explicit: THE BACKTEST
           validates the RANKING and keeps gamma free and uncapped, because
           that is where its ZIP-grain skill lives; LAMBDA sets the LEVEL and
           sees exactly the predictor that reaches an address.

RETAIL IS THE DEPENDENT READ (the standing honesty guardrail)
---------------------------------------------------------------------------
Nothing here predicts neighbourhood growth from retail. The causal arrow runs
households -> spend -> revenue. Incumbent stores enter ONLY as competition in
the Huff denominator, never as a demand signal, and the density-elasticity
regime is printed, never multiplied in. The rejected D1 thesis stays rejected.

WRITE DISCIPLINE (D61 / D48)
---------------------------------------------------------------------------
`write_revenue` issues ONLY `UPDATE analysis.address_category SET
<CATEGORY_REVENUE_COLUMNS>` and `write_address_revenue` only `UPDATE
analysis.address SET <ADDRESS_REVENUE_COLUMNS>`. Neither INSERTs nor DELETEs;
both SET lists are pinned disjoint from the screen's columns, from the demand
annotation, from the pipeline, storefront, age-fit and supply-ratio columns by
tests/test_revenue.py. A site with a big number does not become a gap, and a
site with a small one does not stop being one.

RE-APPLY: `uv run loci revenue --boroughs MN,BK`, at the END of the canonical
order (after `loci supply-ratio`), because it reads homes_400m. `loci revenue
fit` is the ONLY path that rewrites revenue_calibration.yaml and is
deliberately NOT in the re-apply path -- a re-apply must not silently
re-calibrate, or every run is measured against itself.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import pathlib
import time

import numpy as np
import pandas as pd
import yaml

from loci.db import PKG as _PKG
from loci.db import REPO_ROOT as _REPO_ROOT

PKG_ROOT = _PKG
SPEC_PATH = PKG_ROOT / "model" / "revenue.yaml"
CALIBRATION_PATH = PKG_ROOT / "model" / "revenue_calibration.yaml"
BENCHMARKS_PATH = PKG_ROOT / "benchmarks.yaml"
SPEND_PATH = PKG_ROOT / "spend.yaml"
DENSITY_PATH = PKG_ROOT / "model" / "density_elasticity.yaml"
RINGS_CACHE = _REPO_ROOT / "data" / "interim" / "revenue_rings.npz"

#: A real browser UA. BLS 403s default python-requests/urllib agents at the
#: edge, for robots.txt as well as for the workbooks (spend.yaml records the
#: same finding). Census does not care but is sent the same header.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: The ONLY columns write_revenue may name in a SET clause. Per-category grain.
CATEGORY_REVENUE_COLUMNS = [
    "revenue_p25",
    "revenue_p50",
    "revenue_p75",
    "rent_ceiling",
    "revenue_model_version",
    # v0.2 (7d). revenue_cap_p50 is the capacity ceiling the p50 was compared
    # against -- stored so the cap is auditable without re-deriving it, and
    # populated even where it did not bind. capacity_bound says it DID bind.
    "revenue_cap_p50",
    "capacity_bound",
]

#: The ONLY columns write_address_revenue may name. Category-INDEPENDENT (D61):
#: the same homes are within 800 m whether the question is bars or pharmacies.
ADDRESS_REVENUE_COLUMNS = [
    "homes_800m",
]

#: Query nodes per Dijkstra call. Smaller than supply_ratio's 48 because the
#: sweep runs to 800 m and this machine is memory-constrained: (BATCH,
#: n_nodes) float64 at 24 x 605,130 x 8 = 116 MB is the peak allocation.
BATCH = 24


# ------------------------------------------------------------------ config

def load_spec(path: pathlib.Path | None = None) -> dict:
    """revenue.yaml -- the hand-maintained spec. Never generated."""
    return yaml.safe_load((path or SPEC_PATH).read_text())


def spec_hash(path: pathlib.Path | None = None) -> str:
    """Short stable hash of revenue.yaml's BYTES, stamped into the calibration
    so a shipped lambda can be tied to the exact spec that produced it (the
    same provenance pattern as comps.benchmarks_hash)."""
    return hashlib.sha256((path or SPEC_PATH).read_bytes()).hexdigest()[:12]


def load_calibration(path: pathlib.Path | None = None) -> dict | None:
    """revenue_calibration.yaml, or None if `loci revenue fit` has never run."""
    p = path or CALIBRATION_PATH
    return yaml.safe_load(p.read_text()) if p.exists() else None


def shipped_categories(cal: dict | None = None) -> set[str]:
    """Categories whose calibration PASSED the gate. The only ones with
    revenue columns, and the only ones recommend.py may lift off grade D."""
    cal = cal if cal is not None else load_calibration()
    if not cal:
        return set()
    return {c for c, d in (cal.get("categories") or {}).items()
            if (d or {}).get("gate") == "pass"}


def load_benchmarks() -> dict:
    return yaml.safe_load(BENCHMARKS_PATH.read_text())


def load_spend() -> dict:
    return yaml.safe_load(SPEND_PATH.read_text())


def regime_of(category: str) -> str | None:
    """The D70 density-elasticity regime, REPORTED ONLY. Never an input."""
    try:
        doc = yaml.safe_load(DENSITY_PATH.read_text())
    except OSError:                                          # pragma: no cover
        return None
    return ((doc.get("categories") or {}).get(category) or {}).get("regime")


# ------------------------------------------------------- the version switch

def version_settings(spec: dict | None = None) -> dict:
    """Everything that differs between revenue-v0 and revenue-v0.2, read from
    revenue.yaml's `versions:` block.

    The ONE place the version string is interpreted. Every other function takes
    the resulting settings dict, so `model_version: revenue-v0` reproduces D81
    through the same code paths that produce v0.2 rather than through a
    preserved fork that would rot.
    """
    spec = spec or load_spec()
    mv = spec.get("model_version")
    versions = spec.get("versions") or {}
    if mv not in versions:
        raise RuntimeError(
            f"revenue.yaml model_version {mv!r} has no entry under `versions:` "
            f"(have {sorted(versions)}). Refusing to guess which model to run.")
    d = dict(versions[mv])
    d.setdefault("epsilon_grid", [1.0])
    d.setdefault("delta_grid", [0.0])
    d.setdefault("epsilon_parsimony_tolerance", 0.0)
    d.setdefault("epsilon_shipped", None)
    d.setdefault("epsilon_selection", "fixed")
    d.setdefault("epsilon_floor", 0.0)
    d.setdefault("delta_min_skill_gain", 0.0)
    d.setdefault("anchor_statistic", "mean")
    d.setdefault("gamma_site_cap", False)
    d.setdefault("capacity_cap", False)
    d["model_version"] = mv
    return d


# --------------------------------------------------------------- the spend

def load_cex_quintiles(spec: dict | None = None) -> dict[str, list[float]]:
    """{CEX line item -> [q1..q5]} from the cached Table 1101 CSV.

    The cache already lives under data/raw/bls/ (spend.yaml's fetch, 2026-09-05)
    and is READ here rather than copied to a second directory -- one table, one
    place. `fetch_cex_tables` refreshes it in situ.
    """
    spec = spec or load_spec()
    csv_path = _REPO_ROOT / spec["cex"]["table_1101_csv"]
    df = pd.read_csv(csv_path)
    cols = spec["cex"]["quintile_columns"]
    out: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        vals = [row.get(c) for c in cols]
        if any(pd.isna(v) for v in vals):
            continue
        out[str(row["item"]).strip()] = [float(v) for v in vals]
    return out


def load_cex_national(spec: dict | None = None) -> dict[str, float]:
    spec = spec or load_spec()
    df = pd.read_csv(_REPO_ROOT / spec["cex"]["table_1101_csv"])
    return {str(r["item"]).strip(): float(r["all_cu"])
            for _, r in df.iterrows() if not pd.isna(r.get("all_cu"))}


def load_cex_ny_msa(spec: dict | None = None) -> dict[str, float]:
    spec = spec or load_spec()
    df = pd.read_csv(_REPO_ROOT / spec["cex"]["table_3004_csv"])
    out = {}
    for _, r in df.iterrows():
        try:
            out[str(r["item"]).strip()] = float(r["new_york"])
        except (TypeError, ValueError):
            continue
    return out


def fetch_cex_tables(refresh: bool = False, spec: dict | None = None) -> dict:
    """Re-download the two BLS CEX workbooks into data/raw/bls/.

    BLS returns HTTP 403 to default python user agents at the edge (spend.yaml
    records the same finding for plain curl), so a real browser UA is
    mandatory. Existing parsed CSVs are NOT overwritten by this function --
    only the .xlsx workbooks are refreshed, because the CSVs are the parsed
    product of a human pass over the workbooks and re-deriving them is a
    separate job with its own review.
    """
    import requests

    spec = spec or load_spec()
    dest = _REPO_ROOT / "data" / "raw" / "bls"
    dest.mkdir(parents=True, exist_ok=True)
    urls = {
        "cu-income-quintiles-before-taxes-2024.xlsx":
            "https://www.bls.gov/cex/tables/calendar-year/mean-item-share-average-standard-error/cu-income-quintiles-before-taxes-2024.xlsx",
        "cu-msa-northeast-2-year-average-2023-2024.xlsx":
            "https://www.bls.gov/cex/tables/geographic/mean/cu-msa-northeast-2-year-average-2023-2024.xlsx",
    }
    report = {}
    for name, url in urls.items():
        target = dest / name
        if target.exists() and not refresh:
            report[name] = "cached"
            continue
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
        r.raise_for_status()
        head = r.content[:4]
        if head[:2] != b"PK":                                # xlsx is a zip
            raise RuntimeError(f"{name}: not an OOXML workbook (got {head!r}) -- "
                               f"BLS served an error page, not the table")
        target.write_bytes(r.content)
        report[name] = f"fetched {len(r.content):,} bytes"
    return report


def quintile_of(income: float | None, breaks: list[float]) -> int | None:
    """0-based quintile index for a household income against the four real
    published Table 1101 lower limits. `breaks[i]` is the LOWER limit of
    quintile i+1, so income exactly ON a break belongs to the HIGHER
    quintile -- BLS's own convention, and the boundary a test pins."""
    if income is None or (isinstance(income, float) and math.isnan(income)):
        return None
    q = 0
    for b in breaks:
        if income >= b:
            q += 1
        else:
            break
    return q


def spend_vector(category: str, spec: dict, quintiles: dict, national: dict,
                 ny_msa: dict, spend_yaml: dict) -> tuple[np.ndarray, str]:
    """(array of 5 annual $/household, source tag) for one category.

    source tag is one of:
      cex_quintile_ny_msa   -- real quintile column, rebased to New York
      cex_quintile_national -- real quintile column, no MSA figure exists
      elasticity_fallback   -- no CEX line at all (convenience only)
    """
    cat = spec["categories"][category]
    line = cat.get("cex_line")
    share = float(cat.get("share_of_line", 1.0))
    if line is None:
        idx = np.asarray(spend_yaml["quintile_income_index"], dtype=float)
        s0 = float(cat["fallback_annual_spend"])
        eta = float(cat["fallback_income_elasticity"])
        return s0 * (1.0 + eta * (idx - 1.0)), "elasticity_fallback"
    if line not in quintiles:
        raise KeyError(f"CEX line {line!r} for category {category!r} is not in "
                       f"Table 1101 -- the spec and the cached table disagree")
    base = np.asarray(quintiles[line], dtype=float) * share
    ny_line = cat.get("ny_msa_line")
    if ny_line and ny_line in ny_msa and line in national and national[line]:
        ratio = ny_msa[ny_line] / national[line]
        return base * ratio, "cex_quintile_ny_msa"
    return base, "cex_quintile_national"


# ------------------------------------------------------------- the geometry

def ring_kernel(edges: list[float], beta: float, d_floor: float) -> np.ndarray:
    """E[d^-beta | d in ring r] for each ring, under a uniform planar density
    on the annulus. The inner edge of the first ring is floored at `d_floor`
    because d^-beta diverges at zero.

    Pure arithmetic, no data -- tests check it against numerical integration.
    """
    e = list(edges)
    e[0] = max(e[0], d_floor)
    out = np.empty(len(e) - 1, dtype=float)
    for i in range(len(e) - 1):
        a, b = float(e[i]), float(e[i + 1])
        a = max(a, d_floor)
        if b <= a:
            out[i] = a ** (-beta)
            continue
        denom = b * b - a * a
        if abs(beta - 2.0) < 1e-12:
            out[i] = 2.0 * math.log(b / a) / denom
        else:
            out[i] = 2.0 * (b ** (2.0 - beta) - a ** (2.0 - beta)) / ((2.0 - beta) * denom)
    return out


def self_kernel(edges: list[float], beta: float, d_floor: float) -> float:
    """K for the ENTRANT's own ring -- the innermost one. The entrant sits at
    the site, so its distance to the walk-shed it serves is the same
    floored-annulus expectation every other ring-0 store gets. Using the same
    kernel for the entrant and for a ring-0 incumbent is what makes the share
    'one of n+1 stores of average attractiveness' literally true."""
    return float(ring_kernel(edges, beta, d_floor)[0])


def huff_share(ring_counts: np.ndarray, beta: float, edges: list[float],
               d_floor: float, exclude_self: bool = False,
               gamma: float = 1.0) -> np.ndarray:
    """Capture share of a new entrant, given ring counts of incumbents:

        s = (1 + D/K_self) ** -gamma,   D = SUM_r n_r * K_r(beta)

    `gamma` is the NET COMPETITION ELASTICITY and is FITTED, not assumed:

        gamma = 1   textbook Huff -- the entrant is one of n+1 stores of equal
                    attractiveness and takes exactly 1/(n+1) when they share a
                    ring. This is the pre-registered v0 form.
        gamma = 0   no competition term at all: the site takes the whole local
                    pool and revenue is demand alone.
        gamma < 0   AGGLOMERATION DOMINATES: a site with more nearby
                    establishments does BETTER, because a retail corridor
                    draws demand a closed local walk-shed model cannot see.

    Allowing gamma to go negative is the honest response to what the backtest
    found (see the module docstring's calibration section): at ZIP grain the
    incumbent count is partly a proxy for "is this a retail street", and the
    textbook sign loses to no competition term at all in most categories.
    Forcing gamma = 1 would be assuming the answer.

    `ring_counts` is (..., n_rings). `exclude_self=True` removes ONE
    establishment from the innermost ring, which is what you want when
    evaluating an EXISTING store at its own location: it is the entrant, not
    its own competitor.
    """
    n = np.asarray(ring_counts, dtype=float)
    if exclude_self:
        n = n.copy()
        n[..., 0] = np.maximum(n[..., 0] - 1.0, 0.0)
    if gamma == 0.0:
        return np.ones(n.shape[:-1], dtype=float)
    K = ring_kernel(edges, beta, d_floor)
    dnm = n @ K
    return (1.0 + dnm / self_kernel(edges, beta, d_floor)) ** (-gamma)


def ring_sums(A, query_nidx: np.ndarray, W: np.ndarray, edges: list[float],
              batch: int = BATCH, progress=None) -> np.ndarray:
    """(n_query, k, n_rings) sum of every weight falling in each network-
    distance ring of each query node.

    ONE Dijkstra sweep to the outermost edge; every ring is read off the same
    distance matrix, so the ring decomposition is free relative to a single
    catchment. Same reversal as model/supply_ratio.catchment_sums -- sourced
    from the query nodes, licensed by the walk graph being undirected -- and
    pure in the same way: a CSR matrix and arrays in, an array out, no
    database, no pickle, so tests run it on a synthetic line graph.
    """
    from scipy.sparse.csgraph import dijkstra

    n_rings = len(edges) - 1
    n_q, k = len(query_nidx), W.shape[1]
    out = np.zeros((n_q, k, n_rings), dtype=np.float64)
    if n_q == 0:
        return out
    wnz = np.flatnonzero(np.abs(W).sum(axis=1) > 0)
    if wnz.size == 0:
        return out
    Wsub = W[wnz]
    limit = float(edges[-1])
    for s in range(0, n_q, batch):
        chunk = query_nidx[s:s + batch]
        D = dijkstra(A, directed=False, indices=chunk, limit=limit)[:, wnz]
        for r in range(n_rings):
            lo, hi = float(edges[r]), float(edges[r + 1])
            M = ((D > lo) & (D <= hi)) if r else (D <= hi)
            out[s:s + batch, :, r] = M.astype(np.float64) @ Wsub
        if progress is not None:
            progress(min(s + batch, n_q), n_q)
    return out


# ------------------------------------------------- the Economic Census anchor

def _census_key() -> str:
    import os

    key = os.environ.get("CENSUS_API_KEY")
    if key:
        return key.strip()
    env = _REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CENSUS_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("CENSUS_API_KEY not in the environment or loci/.env")


def _ec_cache_path(vintage: int, spec: dict) -> pathlib.Path:
    return _REPO_ROOT / spec["ec"]["cache_dir"] / f"ec{vintage}_county_naics.json"


def fetch_ec_county(vintage: int, naics: list[str], spec: dict | None = None,
                    refresh: bool = False) -> pd.DataFrame:
    """EC receipts/establishments by county x 6-digit NAICS, cached on disk.

    County is the FINEST sub-state geography ecnbasic offers -- verified
    against its own geography.json, which lists county, economic place and
    CSA/MSA/metro division and no ZCTA or ZIP. That is the whole reason the
    backtest has to reach for a proxy (employment-size bands) instead of
    validating revenue against revenue.
    """
    import requests

    spec = spec or load_spec()
    path = _ec_cache_path(vintage, spec)
    cached = json.loads(path.read_text()) if path.exists() else {"rows": []}
    have = {(r["naics"], r["county"]) for r in cached["rows"]}
    want = [c for c in naics
            if refresh or any((c, f) not in have for f in spec["ec"]["counties"].values())]
    rows = [] if refresh else list(cached["rows"])
    if want:
        key = _census_key()
        fips = ",".join(spec["ec"]["counties"].values())
        var = f"NAICS{vintage}"
        for code in want:
            r = requests.get(
                spec["ec"]["dataset"].format(year=vintage),
                params={"get": f"NAME,{var},RCPTOT,ESTAB,EMP,PAYANN",
                        "for": f"county:{fips}", "in": f"state:{spec['ec']['state']}",
                        var: code, "key": key},
                headers={"User-Agent": USER_AGENT}, timeout=90)
            if r.status_code == 204:
                # A REAL finding, not a transport error: the NAICS code is
                # absent from this vintage. 446110 behaves this way in 2022 at
                # every geography including us:1.
                rows.append({"naics": code, "county": None, "absent": True})
                continue
            r.raise_for_status()
            j = r.json()
            hdr = j[0]
            for row in j[1:]:
                d = dict(zip(hdr, row))
                rows.append({"naics": code, "county": d["county"],
                             "name": d["NAME"],
                             "rcptot_k": float(d["RCPTOT"]), "estab": float(d["ESTAB"]),
                             "emp": float(d["EMP"]), "payann_k": float(d["PAYANN"]),
                             "absent": False})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"vintage": vintage, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
             "rows": rows}, indent=1) + "\n")
    return pd.DataFrame(rows)


def ec_anchor(category: str, spec: dict, ec_rows: pd.DataFrame) -> dict:
    """{county_fips: {rcptot, estab, rev_per_estab}} summed over the category's
    NAICS codes. Summing receipts across codes is exact; summing establishments
    is exact too, so the ratio is a true weighted mean of per-store revenue
    across the codes that make up the category."""
    codes = spec["categories"][category]["naics"]
    sub = ec_rows[ec_rows["naics"].isin(codes) & (~ec_rows["absent"].astype(bool))]
    out = {}
    for fips, g in sub.groupby("county"):
        rcptot = float(g["rcptot_k"].sum()) * 1000.0
        estab = float(g["estab"].sum())
        out[str(fips)] = {
            "rcptot_usd": rcptot, "estab": estab,
            "rev_per_estab_usd": (rcptot / estab) if estab else None,
            "naics": sorted(codes),
        }
    return out


def fetch_cbp_county_bands(naics: list[str], spec: dict | None = None,
                           refresh: bool = False) -> pd.DataFrame:
    """CBP county x NAICS x EMPSZES establishment counts, cached on disk.

    The SAME dataset and the SAME vintage as the ZIP-grain backtest target, at
    a coarser geography, used for one thing only: to locate the MEDIAN
    establishment's employment-size band inside each calibration county so
    lambda can be anchored on a median instead of a mean (docstring 7c).
    """
    import requests

    spec = spec or load_spec()
    year = spec["cbp"]["year"]
    name = (spec.get("anchor") or {}).get(
        "cbp_county_cache", "cbp{year}_county_empszes_mnbk.json").format(year=year)
    path = _REPO_ROOT / spec["cbp"]["cache_dir"] / name
    cached = json.loads(path.read_text())["rows"] if path.exists() and not refresh else None
    if cached is not None and set(naics) <= {r["NAICS2017"] for r in cached}:
        rows = cached
    else:
        key = _census_key()
        fips = ",".join(spec["ec"]["counties"].values())
        rows = []
        for code in naics:
            r = requests.get(spec["cbp"]["dataset"].format(year=year),
                             params={"get": "ESTAB,EMPSZES,EMPSZES_LABEL,NAICS2017",
                                     "for": f"county:{fips}",
                                     "in": f"state:{spec['ec']['state']}",
                                     "NAICS2017": code, "key": key},
                             headers={"User-Agent": USER_AGENT}, timeout=120)
            if r.status_code == 204:
                continue
            r.raise_for_status()
            j = r.json()
            hdr = j[0]
            rows += [dict(zip(hdr, row)) for row in j[1:]]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"dataset": f"cbp {year} county", "naics_vintage": "NAICS2017",
             "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
             "n": len(rows), "rows": rows}))
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["county", "NAICS2017", "EMPSZES", "estab"])
    df["estab"] = df["ESTAB"].astype(float)
    return df[["county", "NAICS2017", "EMPSZES", "estab"]]


def _cbp_codes(category: str, spec: dict) -> list[str]:
    """The category's NAICS codes in the CBP (NAICS2017) vintage. ONE
    definition of the renumbering, shared by the county anchor and the ZIP
    target, so the two cannot silently select different codes."""
    remap = {"445131": "445120", "444140": "444130"}
    return [remap.get(str(c), str(c)) for c in spec["categories"][category]["naics"]]


def median_band_employees(cbp_county: pd.DataFrame, category: str, spec: dict) -> dict:
    """{county_fips: {emp_median, band, band_coverage, n_estab}} -- the band
    midpoint of the MEDIAN establishment, bands ordered ascending by midpoint
    and ESTAB cumulated.

    A step function on purpose: the bands are what CBP publishes and
    interpolating inside one would invent a within-band distribution. The
    midpoints come from `cbp.band_midpoints`, the same constant the backtest
    target uses.
    """
    mids = {str(k): float(v) for k, v in spec["cbp"]["band_midpoints"].items()}
    order = sorted(mids, key=lambda b: mids[b])
    out: dict[str, dict] = {}
    if cbp_county.empty:
        return out
    sub = cbp_county[cbp_county["NAICS2017"].isin(_cbp_codes(category, spec))]
    min_cov = float((spec.get("anchor") or {}).get("min_band_coverage", 0.8))
    for fips, g in sub.groupby("county"):
        total = float(g.loc[g["EMPSZES"] == "001", "estab"].sum())
        banded = g[g["EMPSZES"].isin(mids)].groupby("EMPSZES")["estab"].sum()
        n_band = float(banded.sum())
        if total <= 0 or n_band <= 0:
            continue
        cum, pick = 0.0, None
        for b in order:
            cum += float(banded.get(b, 0.0))
            if cum >= n_band / 2.0:
                pick = b
                break
        if pick is None:                                     # pragma: no cover
            continue
        emp_mean = float(sum(mids[b] * float(banded.get(b, 0.0)) for b in order)) / n_band
        out[str(fips)] = {
            "emp_median": mids[pick], "band": pick,
            "emp_mean": emp_mean,
            "band_coverage": round(n_band / total, 4),
            "n_estab_banded": n_band, "n_estab_total": total,
            "usable": bool(n_band / total >= min_cov),
        }
    return out


def median_anchor(category: str, spec: dict, ec_rows: pd.DataFrame,
                  cbp_county: pd.DataFrame) -> dict:
    """{county_fips: {...}} -- the MEDIAN revenue per establishment implied by
    the CBP size-band distribution priced at the Economic Census's own revenue
    per employee for that county x NAICS. See docstring (7c).

    Falls back to the EC mean, with `usable: False` and a stated reason, where
    EC EMP is missing/zero or the CBP bands do not cover enough of the county's
    own establishment total. A fallback is recorded, never silently taken.
    """
    codes = spec["categories"][category]["naics"]
    sub = ec_rows[ec_rows["naics"].isin(codes) & (~ec_rows["absent"].astype(bool))]
    bands = median_band_employees(cbp_county, category, spec)
    out = {}
    for fips, g in sub.groupby("county"):
        fips = str(fips)
        rcptot = float(g["rcptot_k"].sum()) * 1000.0
        emp = float(g["emp"].sum())
        estab = float(g["estab"].sum())
        b = bands.get(fips)
        rpe_mean = (rcptot / estab) if estab else None
        d = {"ec_rev_per_estab_usd": rpe_mean,
             "ec_rev_per_emp_usd": (rcptot / emp) if emp > 0 else None,
             "ec_emp_per_estab": (emp / estab) if estab else None}
        if b:
            d.update({"cbp_median_band": b["band"], "cbp_median_employees": b["emp_median"],
                      "cbp_mean_employees": round(b["emp_mean"], 3),
                      "cbp_band_coverage": b["band_coverage"]})
            # RECONCILIATION. The band -> revenue map priced at EC's own revenue
            # per employee must reproduce EC's own MEAN receipts per
            # establishment when applied to the CBP MEAN band employment. If it
            # does not, the two sources disagree about what an establishment is
            # and the median derived from the same map is not trustworthy
            # either. Reported, never corrected for -- a correction would hide
            # the disagreement it exists to expose.
            if emp > 0 and rpe_mean:
                d["mean_reconciliation_ratio"] = round(
                    b["emp_mean"] * (rcptot / emp) / rpe_mean, 4)
        if emp > 0 and b and b["usable"]:
            med = b["emp_median"] * (rcptot / emp)
            d.update({"median_rev_per_estab_usd": med, "usable": True,
                      "median_over_mean": round(med / rpe_mean, 4) if rpe_mean else None})
        else:
            d.update({"median_rev_per_estab_usd": rpe_mean, "usable": False,
                      "anchor_fallback": "mean",
                      "fallback_reason": ("EC EMP is zero or missing" if emp <= 0 else
                                          "CBP county bands do not cover enough of the "
                                          "county establishment total" if b else
                                          "no CBP county band rows for this NAICS")})
        out[fips] = d
    return out


# --------------------------------------------------- the backtest target

def fetch_cbp_zip_bands(zips: list[str], naics: list[str], spec: dict | None = None,
                        refresh: bool = False) -> pd.DataFrame:
    """CBP ZIP x NAICS x EMPSZES establishment counts, cached on disk.

    CBP publishes NO revenue field, ever, and at ZIP grain EMP and PAYANN are
    suppressed to 0 for most of these cells -- the size BANDS are the only
    establishment-size signal that survives. Since reference year 2019 there is
    no standalone `zbp` dataset; ZIP geography lives inside `cbp` under
    `for=zipcode:`. The variable is named NAICS2017 even in the 2023 vintage.
    """
    import requests

    spec = spec or load_spec()
    year = spec["cbp"]["year"]
    path = _REPO_ROOT / spec["cbp"]["cache_dir"] / f"cbp{year}_zip_empszes_mnbk.json"
    if path.exists() and not refresh:
        rows = json.loads(path.read_text())["rows"]
    else:
        key = _census_key()
        rows = []
        for code in naics:
            r = requests.get(spec["cbp"]["dataset"].format(year=year),
                             params={"get": "ESTAB,EMPSZES,EMPSZES_LABEL,NAICS2017",
                                     "for": f"zipcode:{','.join(zips)}",
                                     "NAICS2017": code, "key": key},
                             headers={"User-Agent": USER_AGENT}, timeout=300)
            r.raise_for_status()
            j = r.json()
            hdr = j[0]
            rows += [dict(zip(hdr, row)) for row in j[1:]]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"dataset": f"cbp {year} zipcode", "naics_vintage": "NAICS2017",
             "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
             "n": len(rows), "rows": rows}))
    df = pd.DataFrame(rows)
    df = df.rename(columns={"zip code": "zipcode"})
    df["estab"] = df["ESTAB"].astype(float)
    return df[["zipcode", "NAICS2017", "EMPSZES", "estab"]]


def employees_per_estab(cbp: pd.DataFrame, category: str, spec: dict) -> pd.DataFrame:
    """(zipcode, emp_per_estab, n_estab, band_coverage) for one category.

    Establishment-weighted mean of the band midpoints. A cell whose bands
    account for < min_band_coverage of its own '001' total has suppressed rows
    and is DROPPED -- imputing the missing band would put the model's own
    assumptions into its own test set.
    """
    mids = {str(k): float(v) for k, v in spec["cbp"]["band_midpoints"].items()}
    # CBP is NAICS2017; the spec's codes are NAICS2022 where they were
    # renumbered. _cbp_codes holds the single definition of that remap, shared
    # with the county median anchor.
    sub = cbp[cbp["NAICS2017"].isin(_cbp_codes(category, spec))]
    if sub.empty:
        return pd.DataFrame(columns=["zipcode", "emp_per_estab", "n_estab", "band_coverage"])
    tot = (sub[sub["EMPSZES"] == "001"].groupby("zipcode")["estab"].sum()
           .rename("total_estab"))
    bands = sub[sub["EMPSZES"].isin(mids)].copy()
    bands["mid"] = bands["EMPSZES"].map(mids)
    bands["emp"] = bands["mid"] * bands["estab"]
    g = bands.groupby("zipcode").agg(banded_estab=("estab", "sum"),
                                     emp=("emp", "sum")).join(tot, how="inner")
    g = g[g["total_estab"] > 0]
    g["band_coverage"] = g["banded_estab"] / g["total_estab"]
    g["emp_per_estab"] = g["emp"] / g["banded_estab"]
    g = g[(g["band_coverage"] >= float(spec["cbp"]["min_band_coverage"])) &
          (g["total_estab"] >= float(spec["cbp"]["min_estab_per_zip"]))]
    return (g.reset_index()
             .rename(columns={"total_estab": "n_estab"})
             [["zipcode", "emp_per_estab", "n_estab", "band_coverage"]])


# ------------------------------------------------------------- the skill

def _spearman(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return float("nan")
    xr = pd.Series(x[ok]).rank().to_numpy()
    yr = pd.Series(y[ok]).rank().to_numpy()
    if xr.std() == 0 or yr.std() == 0:
        return 0.0
    return float(np.corrcoef(xr, yr)[0, 1])


def _r2(y_true, y_pred) -> float:
    """R^2 of a RANK-PRESERVING monotone check -- here the plain coefficient of
    determination of standardised log predictions against log truth, which is
    the number a reader expects beside a Spearman. It is not the fit statistic
    of any regression this module estimates; nothing is regressed."""
    y, p = np.asarray(y_true, float), np.asarray(y_pred, float)
    ok = np.isfinite(y) & np.isfinite(p) & (y > 0) & (p > 0)
    if ok.sum() < 3:
        return float("nan")
    ly, lp = np.log(y[ok]), np.log(p[ok])
    lp = (lp - lp.mean()) / (lp.std() or 1.0) * (ly.std() or 1.0) + ly.mean()
    ss_res = float(((ly - lp) ** 2).sum())
    ss_tot = float(((ly - ly.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


# ---------------------------------------------------------- the capacity

def lot_retail_area(con, spec: dict | None = None) -> pd.DataFrame:
    """(bbl, retail_area_sqft, storefronts_on_bbl, demise_sqft) for every lot.

    `retailarea` is PLUTO's RETAIL floor area on the whole TAX LOT, not one
    tenant's demise. Where the DOF Storefront Registry files more than one
    storefront at that BBL, the lot's retail area is divided by the count --
    one storefront of several does not get the building's whole retail floor.
    That is an equal split and it is wrong in detail (a corner unit is bigger
    than the one beside it); it is right in expectation and it is the only
    split any public source supports.

    READ-ONLY. PLUTO is read from the raw CSV the rest of the codebase reads
    (model/address_character.py, model/invest.py, model/premium.py all read the
    same file), not from a derived table, so the capacity term and the
    character layer cannot disagree about a lot's retail area.
    """
    spec = spec or load_spec()
    csv = _REPO_ROOT / (spec.get("capacity") or {}).get("pluto_csv", "data/raw/pluto.csv")
    lots = con.execute(f"""
        SELECT lpad(CAST(TRY_CAST(BBL AS BIGINT) AS VARCHAR), 10, '0') AS bbl,
               COALESCE(TRY_CAST(retailarea AS DOUBLE), 0.0)           AS retail_area_sqft
        FROM read_csv_auto('{csv.as_posix()}', header=true, all_varchar=true)
        WHERE TRY_CAST(BBL AS BIGINT) IS NOT NULL
    """).fetchdf()
    try:
        # The MAXIMUM number of distinct storefront_ids filed at the BBL in any
        # single reporting year, not the count in the latest year. Two reasons,
        # both found in the data: `premises_id` is the LOT's id (both units at
        # BBL 3027550006 share `3027550006|6`), so it counts one storefront for
        # a two-storefront lot; and the registry is a self-reported annual
        # snapshot with gaps -- 376 Graham filed two units in 2019-2022 and
        # 2024 and nothing in 2023 or 2025. Counting only the latest year would
        # reset that lot to zero storefronts and SILENTLY DOUBLE its tenant's
        # capacity ceiling. A lot that ever filed two units in one year has two
        # units; a lapsed filing is missing evidence, not a demolished wall.
        sf = con.execute("""
            SELECT bbl, max(n) AS storefronts_on_bbl FROM (
                SELECT bbl, reporting_year, COUNT(DISTINCT storefront_id) AS n
                FROM analysis.storefront
                WHERE bbl IS NOT NULL
                GROUP BY bbl, reporting_year)
            GROUP BY bbl
        """).fetchdf()
    except Exception:                     # noqa: BLE001 -- registry may not be loaded
        sf = pd.DataFrame(columns=["bbl", "storefronts_on_bbl"])
    out = lots.merge(sf, on="bbl", how="left")
    out["storefronts_on_bbl"] = out["storefronts_on_bbl"].fillna(0).astype(int)
    n = np.maximum(out["storefronts_on_bbl"].to_numpy(dtype=float), 1.0)
    out["demise_sqft"] = out["retail_area_sqft"].to_numpy(dtype=float) / n
    return out


def capacity_band(category: str, spec: dict | None = None) -> dict:
    """{p25, p50, p75} dollars of annual sales per square foot -- the CEILING
    band from revenue.yaml's `capacity:` block, whose sources are cited there.
    It is NOT a central estimate of productivity (docstring 7d)."""
    spec = spec or load_spec()
    psf = ((spec.get("capacity") or {}).get("psf_per_year") or {}).get(category)
    return {k: float(v) for k, v in psf.items()} if psf else {}


def capacity_area(demise_sqft: np.ndarray, category: str,
                  spec: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(area_sqft, used_typical). Where PLUTO gives no retail area on the lot,
    the category-typical footprint from revenue.yaml stands in and the row is
    FLAGGED -- never silently substituted, because "we do not know how big the
    box is" and "the box is 2,000 sq ft" are different statements."""
    spec = spec or load_spec()
    typ = float(((spec.get("capacity") or {}).get("typical_sqft") or {}).get(category, 0.0))
    a = np.asarray(demise_sqft, dtype=float)
    bad = ~np.isfinite(a) | (a <= 0)
    return np.where(bad, typ, a), bad


# ------------------------------------------------------------- the sweep

def _walk_graph(graph_path=None):
    import pickle

    from loci.score.access import MIN_COMPONENT, _prune, _to_csr
    from loci.score.walkgraph import OUT as GRAPH_PATH

    with pathlib.Path(graph_path or GRAPH_PATH).open("rb") as fh:
        G = pickle.load(fh)
    Gp = _prune(G, MIN_COMPONENT)
    A, idx = _to_csr(Gp)
    return Gp, A, idx


def _zip_of_points(con, lon, lat) -> np.ndarray:
    """ZIP per point via the SAME majority-vote hex->zip crosswalk
    model/zbp_compare.py already uses -- one definition of "which ZIP is this",
    so a revenue prediction and a ZBP comparison cannot disagree about it."""
    import h3

    from loci.model.zbp_compare import RES, _hex_zip_crosswalk

    xw = _hex_zip_crosswalk(con)
    m = dict(zip(xw["h3_index"], xw["zipcode"]))
    cells = [h3.latlng_to_cell(float(la), float(lo), RES) for lo, la in zip(lon, lat)]
    return np.array([m.get(c) for c in cells], dtype=object)


def _county_of_zip(zips: np.ndarray) -> np.ndarray:
    """Kings (047) / New York (061) from the ZIP prefix. Exact for these two
    counties: every Manhattan ZIP is 100xx/101xx/102xx and every Brooklyn ZIP
    is 112xx. Anything else is outside the calibration counties and returns
    None -- it still competes, it just does not calibrate."""
    out = []
    for z in zips:
        s = str(z) if z is not None else ""
        out.append("061" if s[:3] in ("100", "101", "102")
                   else "047" if s[:3] == "112" else None)
    return np.array(out, dtype=object)


class RingPack:
    """Everything the sweep produced, for addresses AND for existing
    establishments, in one object so the calibration and the prediction cannot
    drift apart by being computed from different sweeps."""

    def __init__(self, addr, addr_rings, poi, poi_rings, cats, edges, report):
        self.addr, self.addr_rings = addr, addr_rings
        self.poi, self.poi_rings = poi, poi_rings
        self.cats, self.edges, self.report = cats, edges, report

    def homes(self, which: str, radius_m: float) -> np.ndarray:
        rings = self.addr_rings if which == "addr" else self.poi_rings
        n = sum(1 for i in range(len(self.edges) - 1) if self.edges[i + 1] <= radius_m)
        return rings["homes"][:, :n].sum(axis=1)

    def supply(self, which: str, category: str) -> np.ndarray:
        rings = self.addr_rings if which == "addr" else self.poi_rings
        return rings["supply"][:, self.cats.index(category), :]


def compute_rings(con, boroughs: list[str], spec: dict | None = None,
                  supply_set: str = "principled", graph_path=None,
                  log=print) -> RingPack:
    """ONE Dijkstra sweep to 800 m, sourced from the distinct graph nodes that
    the scope's addresses AND the two counties' principled establishments
    collapse onto. READ-ONLY on the warehouse."""
    import osmnx as ox

    from loci.model.supply_ratio import node_weights
    from loci.score.supply import supply_hash, supply_predicate

    spec = spec or load_spec()
    edges = [float(x) for x in spec["huff"]["ring_edges_m"]]
    cats = list(spec["modelled"]) + list(spec["flagged"])

    pois = con.execute(f"""
        SELECT category, ST_X(geom) AS lon, ST_Y(geom) AS lat
        FROM analysis.poi_supply
        WHERE {supply_predicate(supply_set)}
          AND category IN ({','.join("'" + c + "'" for c in cats)})
          AND geom IS NOT NULL
    """).fetchdf()
    if pois.empty:
        raise RuntimeError(
            f"revenue: analysis.poi_supply has no '{supply_set}' rows in the modelled "
            f"categories. A zero incumbent count everywhere would give every site the "
            f"whole neighbourhood's spend -- a confident, enormous false positive.")

    # Homes are CITYWIDE (edge effects: a Bushwick address is served by, and
    # serves, the block across the Queens line) -- same reasoning as
    # supply_ratio.load_home_points.
    #
    # D84: and LOT-frame only, for both of the roles this one query plays.
    # As WEIGHTS, a street point contributes units 0 -- including it would
    # change no number and would make the "spend pool is unchanged" claim
    # approximate instead of arithmetic. As the QUERY set, a street point is
    # not an observation of realised receipts: lambda_c is fitted so that the
    # mean prediction over a county's establishments matches the Economic
    # Census, and the leave-one-ZIP-out backtest scores predictions against
    # ZIP-level CBP employment. A units-0 point has no spend pool, so it would
    # enter every fold as a structural zero and drag the fit toward a model
    # that predicts nothing well. So revenue is NOT applied to street rows:
    # their revenue_* columns stay NULL, which is this module's own convention
    # for "not modelled" and never a revenue of zero.
    homes = con.execute("""
        SELECT address_id, borough, bbl, lon, lat, COALESCE(units, 0) AS units
        FROM analysis.address
        WHERE lon IS NOT NULL AND lat IS NOT NULL
          AND COALESCE(frame, 'lot') = 'lot'
    """).fetchdf()
    demo = con.execute("""
        SELECT address_id, median_hh_income, median_hh_income_moe
        FROM analysis.address_demographics
    """).fetchdf()
    homes = homes.merge(demo, on="address_id", how="left")

    log("  graph: loading and pruning")
    Gp, A, idx = _walk_graph(graph_path)
    n_nodes = A.shape[0]

    poi_nodes = ox.distance.nearest_nodes(Gp, X=pois["lon"].tolist(), Y=pois["lat"].tolist())
    poi_nidx = np.array([idx[n] for n in np.atleast_1d(poi_nodes)], dtype=np.int64)
    home_nodes = ox.distance.nearest_nodes(Gp, X=homes["lon"].tolist(), Y=homes["lat"].tolist())
    home_nidx = np.array([idx[n] for n in np.atleast_1d(home_nodes)], dtype=np.int64)

    cat_arr = pois["category"].to_numpy()
    nodes_of = {"homes": home_nidx}
    weights = {"homes": homes["units"].to_numpy(dtype=np.float64)}
    for c in cats:
        m = cat_arr == c
        nodes_of[c] = poi_nidx[m]
        weights[c] = np.ones(int(m.sum()), dtype=np.float64)
    keys = ["homes", *cats]
    W = node_weights(idx, nodes_of, {k: weights[k] for k in keys}, n_nodes)

    # Query set: scope addresses + the establishments inside the two counties.
    scope_mask = homes["borough"].isin(boroughs).to_numpy()
    addr = homes[scope_mask].reset_index(drop=True)
    addr_nidx = home_nidx[scope_mask]

    log("  crosswalk: hex -> zip for addresses and establishments")
    pois = pois.assign(zipcode=_zip_of_points(con, pois["lon"].to_numpy(), pois["lat"].to_numpy()))
    pois = pois.assign(county=_county_of_zip(pois["zipcode"].to_numpy()))
    addr = addr.assign(zipcode=_zip_of_points(con, addr["lon"].to_numpy(), addr["lat"].to_numpy()))
    addr = addr.assign(county=_county_of_zip(addr["zipcode"].to_numpy()))

    in_county = pois["county"].notna().to_numpy()
    poi_scope = pois[in_county].reset_index(drop=True)
    poi_scope_nidx = poi_nidx[in_county]

    q_nidx = np.concatenate([addr_nidx, poi_scope_nidx])
    uniq, inv = np.unique(q_nidx, return_inverse=True)
    log(f"  sweep: {len(addr):,} addresses + {len(poi_scope):,} establishments "
        f"-> {uniq.size:,} distinct nodes, {len(edges)-1} rings to {edges[-1]:.0f} m")

    t0 = time.time()
    last = [0.0]

    def prog(done, total):
        if time.time() - last[0] > 30:
            last[0] = time.time()
            log(f"    {done:,}/{total:,} nodes ({done/total:.0%}, {time.time()-t0:.0f}s)")

    acc = ring_sums(A, uniq, W, edges, batch=BATCH, progress=prog)[inv]
    log(f"  sweep done in {time.time()-t0:.0f}s")

    n_a = len(addr)
    hi = keys.index("homes")
    ci = [keys.index(c) for c in cats]
    addr_rings = {"homes": acc[:n_a, hi, :].astype(np.float64),
                  "supply": acc[:n_a][:, ci, :].astype(np.float32)}
    poi_rings = {"homes": acc[n_a:, hi, :].astype(np.float64),
                 "supply": acc[n_a:][:, ci, :].astype(np.float32)}

    report = {
        "boroughs": list(boroughs), "supply_set": supply_set,
        "supply_hash": supply_hash(con, supply_set),
        "ring_edges_m": edges, "categories": cats,
        "addresses": int(n_a),
        # The CITYWIDE address count that carried the homes weights, not just
        # the scope. Stamped because it is the one input that can silently
        # change a calibration WITHOUT changing the supply hash: if
        # analysis.address is ever rebuilt to hold fewer boroughs, every MN+BK
        # address near a borough line loses real households from its 400 m shed
        # and lambda moves, and no other provenance field would register it.
        "home_rows_citywide": int(len(homes)),
        "establishments_in_scope": int(len(poi_scope)),
        "establishments_total": int(len(pois)),
        "query_nodes": int(uniq.size),
        "sweep_seconds": round(time.time() - t0, 1),
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    return RingPack(addr, addr_rings, poi_scope, poi_rings, cats, edges, report)


# ------------------------------------------------------------ prediction

def _quintile_index(income: np.ndarray, breaks: list[float]) -> np.ndarray:
    """Vectorised quintile_of. NaN income -> -1, carried as 'unknown' and
    dropped rather than imputed to the middle."""
    inc = np.asarray(income, dtype=float)
    q = np.full(inc.shape, -1, dtype=np.int8)
    ok = np.isfinite(inc)
    q[ok] = np.searchsorted(np.asarray(breaks, dtype=float), inc[ok], side="right")
    return q


def spend_per_household(income: np.ndarray, evec: np.ndarray,
                        breaks: list[float]) -> np.ndarray:
    q = _quintile_index(income, breaks)
    out = np.full(q.shape, np.nan, dtype=float)
    ok = q >= 0
    out[ok] = evec[q[ok]]
    return out


def pool_factor(pool: np.ndarray, epsilon: float) -> np.ndarray:
    """Pool^epsilon, WITH THE MISSING-VALUE SEMANTICS PRESERVED.

    numpy evaluates nan ** 0 as 1.0. Left alone, that would make the epsilon = 0
    candidate silently score on a LARGER sample than every other candidate --
    every establishment whose tract income is unknown, and therefore has no
    spend pool, would re-enter the fit as a 1.0 instead of being dropped. A
    grid search comparing candidates fitted on different samples is not a grid
    search. An unknown pool stays unknown at every epsilon.
    """
    p = np.asarray(pool, dtype=float)
    if epsilon == 1.0:
        return p
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.power(np.maximum(p, 0.0), epsilon)
    return np.where(np.isfinite(p), out, np.nan)


def uncalibrated(pool: np.ndarray, rings: np.ndarray, beta: float,
                 edges: list[float], d_floor: float,
                 exclude_self: bool = False, gamma: float = 1.0,
                 epsilon: float = 1.0, pindex: np.ndarray | None = None,
                 delta: float = 0.0, gamma_site_cap: bool = False) -> np.ndarray:
    """R_hat = Pool^epsilon * P^delta * capture share. The whole model bar lambda.

    epsilon = 1, delta = 0 and gamma_site_cap = False is revenue-v0 exactly.

    `gamma_site_cap` clips the competition multiplier at 1.0 (docstring 7e):
    neighbours may not RAISE a site above the corridor-neutral share. It is a
    SITE-level transform and is off inside the ZIP-grain fit by default.
    """
    base = pool_factor(pool, epsilon)
    if pindex is not None and delta != 0.0:
        base = base * np.power(np.maximum(np.asarray(pindex, dtype=float), 1e-9), delta)
    s = huff_share(rings, beta, edges, d_floor, exclude_self=exclude_self, gamma=gamma)
    if gamma_site_cap:
        s = np.minimum(s, 1.0)
    return base * s


# ----------------------------------------------------------- calibration

def _lambdas(rhat: np.ndarray, county: np.ndarray, anchor: dict,
             mask: np.ndarray | None = None, med_anchor: dict | None = None) -> dict:
    """{county_fips: {lambda_per_store, lambda_total, n_ours, n_ec, ...}}.

    `lambda_per_store` makes the MEAN prediction over that county's
    establishments equal the EC mean revenue per establishment; it is the one
    used, because the deliverable is per-site revenue. `lambda_total` makes the
    SUM equal RCPTOT; it ships beside it and the two differ by exactly
    n_ours / n_EC, which is the coverage diagnostic."""
    out = {}
    m = np.ones(len(rhat), dtype=bool) if mask is None else mask
    for fips, a in anchor.items():
        sel = m & (county == fips) & np.isfinite(rhat)
        n = int(sel.sum())
        if n == 0 or a.get("rev_per_estab_usd") is None:
            continue
        mean_rhat = float(rhat[sel].mean())
        sum_rhat = float(rhat[sel].sum())
        med_rhat = float(np.median(rhat[sel]))
        d = {
            "lambda_per_store": (a["rev_per_estab_usd"] / mean_rhat) if mean_rhat > 0 else None,
            "lambda_total": (a["rcptot_usd"] / sum_rhat) if sum_rhat > 0 else None,
            "n_ours": n, "n_ec": a["estab"],
            "estab_ratio_ours_over_ec": n / a["estab"] if a["estab"] else None,
            "ec_rev_per_estab_usd": a["rev_per_estab_usd"],
            "mean_rhat": mean_rhat,
            "median_rhat": med_rhat,
        }
        # v0.2 (7c): the MEDIAN-anchored lambda, computed whenever the median
        # anchor is available. Both ship; `anchor_statistic` decides which one
        # `lambda_shipped` points at, so the size of the correction is always
        # visible rather than only its result.
        ma = (med_anchor or {}).get(fips) or {}
        tgt = ma.get("median_rev_per_estab_usd")
        d["lambda_median"] = (tgt / med_rhat) if (tgt and med_rhat > 0) else None
        d["median_anchor_usd"] = tgt
        d["median_anchor_usable"] = ma.get("usable")
        if d["lambda_median"] and d["lambda_per_store"]:
            d["lambda_median_over_mean"] = round(d["lambda_median"] / d["lambda_per_store"], 4)
        out[fips] = d
    return out


def _lambda_key(settings: dict) -> str:
    """Which lambda the shipped model uses -- the ONE place the anchor
    statistic is turned into a field name."""
    return "lambda_median" if settings.get("anchor_statistic") == "median" else "lambda_per_store"


def _apply_lambda(rhat: np.ndarray, county: np.ndarray, lam: dict,
                  key: str = "lambda_per_store") -> np.ndarray:
    out = np.full(len(rhat), np.nan)
    for fips, d in lam.items():
        v = d.get(key)
        if v is None:
            continue
        sel = county == fips
        out[sel] = rhat[sel] * v
    return out


def _zip_mean(values: np.ndarray, zips: np.ndarray, keep: list[str]) -> pd.Series:
    s = pd.Series(values, index=pd.Index(zips, name="zipcode"))
    g = s.groupby(level=0).mean()
    return g.reindex(keep)


def sigma_shape(med_rings: np.ndarray, fold_shapes: list[tuple[float, float]],
                star: tuple[float, float], edges: list[float], d_floor: float) -> float:
    """Log-scale spread the fitted (beta, gamma) contributes to the p25/p75
    band: log(share at each FOLD's shape / share at the shipped shape),
    evaluated at the median incumbent profile.

    ONE ENTRY PER FOLD, not per distinct candidate. The quantity wanted is the
    sampling spread of the fitted shape, so a candidate that one fold in 73
    chose must carry one fold's weight. Deduplicating first gives a lone
    outlier fold the same weight as the mode and inflates the band severalfold
    -- it did exactly that on the first run (sigma 0.98, a 4x band, from two
    stray folds out of 73).

    ROOT MEAN SQUARE about zero, not standard deviation about the folds' mean:
    the question is how far the SHIPPED number could sit from what an
    out-of-sample fit would say, so a systematic offset between the in-sample
    pick and every fold's pick has to count rather than be centred away.
    """
    s_star = float(huff_share(med_rings, star[0], edges, d_floor, gamma=star[1])[0])
    if s_star <= 0 or not fold_shapes:
        return 0.0
    shares = [float(huff_share(med_rings, b, edges, d_floor, gamma=g)[0])
              for b, g in fold_shapes]
    devs = [math.log(s / s_star) for s in shares if s > 0]
    return float(np.sqrt(np.mean(np.square(devs)))) if devs else 0.0


def _beats(s_model: float, s_base: float, margin: float) -> bool:
    """The model must clear a baseline BY A MARGIN. A non-finite baseline is
    treated as zero skill, never as a free pass."""
    if not np.isfinite(s_model):
        return False
    base = 0.0 if not np.isfinite(s_base) else float(s_base)
    return bool(s_model >= base + margin)


def _grid(spec: dict) -> list[tuple[float, float]]:
    """(beta, gamma) combinations. beta is irrelevant when gamma == 0 (no
    competition term), so that row appears exactly once instead of once per
    beta -- otherwise the grid would be ten identical candidates and an
    argmax tie would pick one arbitrarily."""
    betas = [float(b) for b in spec["huff"]["beta_grid"]]
    gammas = [float(g) for g in spec["huff"]["gamma_grid"]]
    out = []
    for g in gammas:
        out += [(betas[0], 0.0)] if g == 0.0 else [(b, g) for b in betas]
    return out


def _grid3(spec: dict, settings: dict) -> list[tuple[float, float, float, float]]:
    """(beta, gamma, epsilon, delta) candidates -- the v0.2 search space.

    The shape axis (beta, gamma) is _grid's, unchanged, so a v0 run whose
    epsilon grid is [1.0] and delta grid is [0.0] enumerates EXACTLY _grid in
    the same order and reproduces D81's candidate indexing.

    epsilon = 0 makes the pool term constant, and then beta/gamma still vary
    the share, so no deduplication is possible on that axis. delta = 0 likewise
    leaves the shape free. The grid is therefore the full product, and it is
    the reason the fold loop is vectorised rather than looped (see
    `_loo_spearman_rows`).
    """
    eps = [float(e) for e in settings["epsilon_grid"]]
    dls = [float(d) for d in settings["delta_grid"]]
    return [(b, g, e, d) for e in eps for d in dls for b, g in _grid(spec)]


def _ranks(a: np.ndarray, axis: int = -1) -> np.ndarray:
    """Average ranks along an axis -- scipy.stats.rankdata, vectorised."""
    from scipy.stats import rankdata
    return rankdata(a, axis=axis)


def _loo_spearman_rows(preds: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Spearman of row i of `preds` against `y`, EXCLUDING column i, for every
    row at once. `preds` is (n, n): row i is the prediction vector produced by
    the fold that held ZIP i out.

    Removing one element from a ranking does not need a re-rank: an element's
    rank among the survivors is its full-sample rank minus one for every
    survivor it outranked, i.e. minus 1 exactly when it ranked above the
    removed element. That is exact whenever the values in a row are distinct,
    which continuous predictions and an employees-per-establishment target are;
    `test_loo_spearman_matches_the_scalar_loop` pins it against the naive
    per-fold rank-and-correlate on random data.

    Written vectorised because the v0.2 grid is (beta x gamma x epsilon x
    delta) -- thousands of candidates x tens of folds -- and the naive loop is
    a rank call per pair.
    """
    n = len(y)
    R = _ranks(np.where(np.isfinite(preds), preds, -np.inf), axis=1)
    ry = _ranks(y)
    diag = R[np.arange(n), np.arange(n)][:, None]
    Rk = R - (R > diag)                      # ranks among the survivors
    ryk = ry[None, :] - (ry[None, :] > ry[:, None])
    keep = ~np.eye(n, dtype=bool)
    out = np.full(n, np.nan)
    for i in range(n):                        # n is the ZIP count, tens not thousands
        a, b = Rk[i][keep[i]], ryk[i][keep[i]]
        ok = np.isfinite(preds[i][keep[i]])
        if ok.sum() < 3:
            continue
        a, b = a[ok], b[ok]
        if a.std() == 0 or b.std() == 0:
            out[i] = 0.0
            continue
        out[i] = float(np.corrcoef(a, b)[0, 1])
    return out


def _parsimonious_argmax(scores: np.ndarray, cands: list, tol: float) -> int:
    """THE PRE-REGISTERED TIE-BREAK (docstring 7a). Among candidates within
    `tol` of the best score, take the SMALLEST epsilon; break what remains on
    score, then on the candidate's position in the grid so the choice is
    deterministic. tol = 0 reduces to a plain argmax, which is what
    revenue-v0 gets."""
    s = np.asarray(scores, dtype=float)
    if not np.any(np.isfinite(s)):
        return 0
    best = float(np.nanmax(s))
    feasible = [k for k in range(len(s)) if np.isfinite(s[k]) and s[k] >= best - tol]
    return min(feasible, key=lambda k: (cands[k][2], -s[k], k))


def price_index(income: np.ndarray, reference: float) -> np.ndarray:
    """P = tract median household income / the county's median tract income.

    The TICKET channel of docstring (7b), deliberately separate from the
    household-COUNT channel. 1.0 where income is unknown -- a missing income is
    "no information about price level", never "a cheap neighbourhood".
    """
    inc = np.asarray(income, dtype=float)
    if not reference or not np.isfinite(reference) or reference <= 0:
        return np.ones(inc.shape, dtype=float)
    out = np.where(np.isfinite(inc) & (inc > 0), inc / float(reference), 1.0)
    return out.astype(float)


class _CatFit:
    """Precomputed aggregates for one category, so the leave-one-ZIP-out loop
    is arithmetic on sums instead of a groupby per fold.

    For each (beta, gamma) candidate this holds the per-ZIP sum and count of
    R_hat and the per-county sum and count. A fold's lambda then comes from
    (county total - held-out ZIP's contribution), and the fold's prediction for
    any ZIP is (that ZIP's mean R_hat) x (that ZIP's county's fold lambda) --
    both O(1). Without this, refitting beta and gamma inside every fold would
    be tens of thousands of groupbys.
    """

    def __init__(self, rhat_by_cand, zips_eval, zp, cp, anchor):
        self.anchor = anchor
        self.zips = list(zips_eval)
        self.zc = _county_of_zip(np.array(self.zips, dtype=object))
        zi = {z: i for i, z in enumerate(self.zips)}
        self.zidx = np.array([zi.get(z, -1) for z in zp], dtype=np.int64)
        self.counties = sorted(anchor)
        ci = {f: i for i, f in enumerate(self.counties)}
        self.cidx = np.array([ci.get(f, -1) for f in cp], dtype=np.int64)
        nz, nc = len(self.zips), len(self.counties)
        self.nz, self.nc = nz, nc
        self.zsum, self.zcnt = [], []
        self.csum, self.ccnt = [], []
        self.zcsum, self.zccnt = [], []          # per (zip, county) for the fold subtraction
        # `rhat_by_cand` is consumed as an ITERABLE, never indexed: v0.2's grid
        # is thousands of candidates x tens of thousands of establishments, and
        # materialising all of them at once is hundreds of megabytes for no
        # reason -- only these aggregates are ever read again. Passing a list
        # still works and is what the tests do.
        for r in rhat_by_cand:
            r = np.asarray(r, dtype=float)
            ok = np.isfinite(r)
            m = ok & (self.zidx >= 0)
            # bincount, not np.add.at: same arithmetic, roughly 20x faster, and
            # the candidate count in v0.2 makes that the difference between a
            # fit that runs and one that does not.
            zs = np.bincount(self.zidx[m], weights=r[m], minlength=nz).astype(float)
            zn = np.bincount(self.zidx[m], minlength=nz).astype(float)
            m2 = ok & (self.cidx >= 0)
            cs = np.bincount(self.cidx[m2], weights=r[m2], minlength=nc).astype(float)
            cn = np.bincount(self.cidx[m2], minlength=nc).astype(float)
            m3 = m & (self.cidx >= 0)
            flat = self.zidx[m3] * nc + self.cidx[m3]
            zcs = np.bincount(flat, weights=r[m3], minlength=nz * nc).astype(float).reshape(nz, nc)
            zcn = np.bincount(flat, minlength=nz * nc).astype(float).reshape(nz, nc)
            self.zsum.append(zs); self.zcnt.append(zn)
            self.csum.append(cs); self.ccnt.append(cn)
            self.zcsum.append(zcs); self.zccnt.append(zcn)
        self.n_cands = len(self.zsum)
        self.rpe = np.array([(self.anchor[f].get("rev_per_estab_usd") or np.nan)
                             for f in self.counties], dtype=float)
        self.zcounty = np.array([self.counties.index(f) if f in ci else -1
                                 for f in self.zc], dtype=np.int64)

    def lambdas_all_folds(self, k: int) -> np.ndarray:
        """(n_zips, n_counties) -- row i is candidate k's per-county lambda
        fitted with ZIP i held out. Identical arithmetic to `lambdas(k,
        drop_zip=i)` for every i, computed in one array op; a test pins the
        two against each other."""
        cs = self.csum[k][None, :] - self.zcsum[k]
        cn = self.ccnt[k][None, :] - self.zccnt[k]
        with np.errstate(invalid="ignore", divide="ignore"):
            lam = np.where((cn > 0) & (cs > 0), self.rpe[None, :] * cn / cs, np.nan)
        return lam

    def predict_all_folds(self, k: int) -> np.ndarray:
        """(n_zips, n_zips) -- row i is the vector of predictions every ZIP
        receives from the fold that held ZIP i out. The diagonal is the
        held-out prediction; the off-diagonal is what that fold is SCORED on."""
        lam = self.lambdas_all_folds(k)
        # NaN lambdas are DROPPED from the sum (nansum's semantics in
        # `predict`), not propagated: a county with no establishments left in a
        # fold must not annihilate a ZIP that lies wholly in the other county.
        lam0 = np.where(np.isfinite(lam), lam, 0.0)
        num = lam0 @ self.zcsum[k].T                     # (folds, zips)
        den = np.where(np.isfinite(lam), 1.0, 0.0) @ self.zccnt[k].T
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)

    def lambdas(self, k: int, drop_zip: int | None = None) -> np.ndarray:
        """Per-county lambda_per_store for candidate k, optionally excluding
        one ZIP's establishments from the fit."""
        cs, cn = self.csum[k].copy(), self.ccnt[k].copy()
        if drop_zip is not None:
            cs -= self.zcsum[k][drop_zip]
            cn -= self.zccnt[k][drop_zip]
        out = np.full(len(self.counties), np.nan)
        for i, f in enumerate(self.counties):
            rpe = self.anchor[f].get("rev_per_estab_usd")
            if rpe and cn[i] > 0 and cs[i] > 0:
                out[i] = rpe / (cs[i] / cn[i])
        return out

    def predict(self, k: int, lam: np.ndarray) -> np.ndarray:
        """Predicted revenue per establishment for every evaluation ZIP.

        Averages the LAMBDA-APPLIED R_hat, county by county, rather than
        applying one county's lambda to a whole ZIP's mean. In practice a ZIP
        lies entirely inside one county so the two agree, but only the former
        is identically `_apply_lambda` followed by a per-ZIP mean, and a test
        pins that equality on a deliberately mixed fixture."""
        num = np.nansum(self.zcsum[k] * lam[None, :], axis=1)
        den = np.where(np.isfinite(lam)[None, :], self.zccnt[k], 0.0).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)


def fit(con, boroughs=("MN", "BK"), spec: dict | None = None, pack: RingPack | None = None,
        log=print) -> dict:
    """Calibrate lambda, beta, gamma, epsilon and delta, run the
    leave-one-ZIP-out backtest against both baselines and the placebo, and
    return the calibration document. Writing it is `save_calibration`'s job and
    is GATED.

    Under `epsilon_selection: smallest_gate_passing` (v0.2) this refits the
    WHOLE model family at every epsilon on the grid and lets the GATE choose:
    a category ships at the smallest epsilon it still survives. See
    revenue.yaml for why an argmax and a bare prior were both rejected.
    """
    spec = spec or load_spec()
    vs = version_settings(spec)
    if vs.get("epsilon_selection") != "smallest_gate_passing":
        return _fit_at(con, boroughs, spec, vs, [float(e) for e in vs["epsilon_grid"]],
                       pack=pack, log=log)

    pack = pack or compute_rings(con, list(boroughs), spec, log=log)
    grid = sorted(float(e) for e in vs["epsilon_grid"])
    docs = {}
    for e in grid:
        log(f"  epsilon scan: refitting the whole family at epsilon = {e}")
        docs[e] = _fit_at(con, boroughs, spec, vs, [e], pack=pack, log=lambda *_: None)
        passing = sorted(c for c, d in docs[e]["categories"].items()
                         if (d or {}).get("gate") == "pass")
        log(f"    epsilon {e}: gate passes {passing or '(none)'}")

    # THE GATE CHOOSES, SUBJECT TO THE STRUCTURAL FLOOR. Smallest epsilon at or
    # above `epsilon_floor` that passes; if none does, the record kept is the
    # LARGEST epsilon's (the v0-like end of the family), so the failure reason
    # a reader sees is the one for the least-compressed model.
    #
    # The floor is load-bearing, not cosmetic: on the 2026-09-13 scan
    # cafe_bakery passed the gate at epsilon = 0.0, where the model has no
    # demand pool at all and its only spatial signal is incumbent density --
    # the rejected D1 thesis. A gate that cannot see that is not a licence to
    # ship it. The full grid is still scanned and recorded.
    floor = float(vs.get("epsilon_floor") or 0.0)
    eligible = [e for e in grid if e >= floor - 1e-9]
    out = dict(docs[grid[-1]])
    cats = list(out["categories"])
    chosen = {}
    for cat in cats:
        hit = next((e for e in eligible
                    if (docs[e]["categories"].get(cat) or {}).get("gate") == "pass"), None)
        chosen[cat] = hit
        d = dict(docs[hit if hit is not None else grid[-1]]["categories"][cat])
        d["epsilon_selection"] = "smallest_gate_passing"
        d["epsilon_gate_scan"] = {
            str(e): {
                "gate": (docs[e]["categories"].get(cat) or {}).get("gate"),
                "spearman_oos": ((docs[e]["categories"].get(cat) or {}).get("backtest")
                                 or {}).get("spearman_oos"),
                "placebo": (((docs[e]["categories"].get(cat) or {}).get("placebo") or {})
                            .get("passes")),
                "placebo_margin": _placebo_margin(docs[e]["categories"].get(cat) or {}),
            } for e in grid}
        below = sorted(e for e in grid if e < floor - 1e-9
                       and (docs[e]["categories"].get(cat) or {}).get("gate") == "pass")
        d["epsilon_floor"] = floor
        d["epsilon_passed_below_floor"] = below
        d["epsilon_shipped_reason"] = (
            f"smallest epsilon >= the structural floor {floor} at which this category passes "
            f"the full gate (both baselines + the cross-category placebo); it fails at every "
            f"smaller eligible one"
            + (f". It ALSO passed at {below}, below the floor, where the demand pool is "
               f"effectively absent and the only spatial signal is incumbent density -- "
               f"refused on the D1 guardrail, not on skill." if below else "")
            if hit is not None else
            "no eligible epsilon passes the gate; the record shown is the largest on the grid"
            + (f" (it DID pass at {below}, below the structural floor, where the model has no "
               f"demand pool -- refused on the D1 guardrail)" if below else ""))
        out["categories"][cat] = d
    out["epsilon_selection"] = "smallest_gate_passing"
    out["epsilon_floor"] = floor
    out["epsilon_chosen"] = {c: chosen[c] for c in cats}
    return out


def _placebo_margin(d: dict) -> float | None:
    p = d.get("placebo") or {}
    own, riv = p.get("own_spearman"), p.get("best_rival_spearman")
    return None if (own is None or riv is None) else round(own - riv, 4)


def _fit_at(con, boroughs, spec: dict, vs: dict, eps_list: list[float],
            pack: RingPack | None = None, log=print) -> dict:
    """One full calibration at a FIXED epsilon grid (usually one value)."""
    from scipy.spatial import cKDTree

    vs = {**vs, "epsilon_grid": list(eps_list),
          "epsilon_shipped": eps_list[0] if len(eps_list) == 1 else vs.get("epsilon_shipped")}
    cats = list(spec["modelled"]) + list(spec["flagged"])
    edges = [float(x) for x in spec["huff"]["ring_edges_m"]]
    d_floor = float(spec["huff"]["d_floor_m"])
    cands = _grid3(spec, vs)
    shapes = _grid(spec)
    eps_tol = float(vs.get("epsilon_parsimony_tolerance", 0.0))
    lam_key = _lambda_key(vs)
    breaks = spec["cex"]["quintile_income_breaks_usd"]
    pool_r = float(spec["huff"]["pool_radius_m"])
    log(f"  model_version {vs['model_version']}: {len(cands)} candidates "
        f"(beta x gamma x epsilon x delta), anchor = {vs['anchor_statistic']}")

    pack = pack or compute_rings(con, list(boroughs), spec, log=log)
    quint, national, ny_msa = load_cex_quintiles(spec), load_cex_national(spec), load_cex_ny_msa(spec)
    spend_yaml = load_spend()

    log("  anchors: Economic Census county cells")
    n22 = sorted({c for k in cats for c in spec["categories"][k]["naics"]
                  if spec["categories"][k].get("ec_vintage", 2022) == 2022})
    n17 = sorted({c for k in cats for c in spec["categories"][k]["naics"]
                  if spec["categories"][k].get("ec_vintage", 2022) == 2017})
    ec = {2022: fetch_ec_county(2022, n22, spec)}
    if n17:
        ec[2017] = fetch_ec_county(2017, n17, spec)

    all_cbp_codes = sorted({c for k in cats for c in _cbp_codes(k, spec)})
    cbp_county = fetch_cbp_county_bands(all_cbp_codes, spec)

    # An establishment's customers are the households around IT, so it gets the
    # income of the nearest residential address -- the same tract figure an
    # address 30 m away would carry.
    tree = cKDTree(pack.addr[["lon", "lat"]].to_numpy())
    _, nn = tree.query(pack.poi[["lon", "lat"]].to_numpy())
    poi_income = pack.addr["median_hh_income"].to_numpy()[nn]

    zips_scope = sorted({z for z in pack.addr["zipcode"].dropna().unique()})
    all_naics = sorted({c for k in cats for c in spec["categories"][k]["naics"]})
    log(f"  backtest target: CBP {spec['cbp']['year']} ZIP x EMPSZES, {len(zips_scope)} ZIPs")
    cbp = fetch_cbp_zip_bands(zips_scope, all_naics, spec)

    homes400_poi_all = pack.homes("poi", pool_r)
    poi_cat = pack.poi["category"].to_numpy()
    poi_zip = pack.poi["zipcode"].to_numpy()
    poi_county = pack.poi["county"].to_numpy()

    # The price-index reference (docstring 7b): the MEDIAN TRACT INCOME of the
    # county, taken over the scope's addresses, not over establishments -- the
    # reference is "how rich is this county's typical household", and weighting
    # it by where shops happen to be would make the index partly a shop-density
    # measure. Computed once, from the same frame every other term is read off.
    county_ref = {}
    _ai, _ac = pack.addr["median_hh_income"].to_numpy(dtype=float), pack.addr["county"].to_numpy()
    for f in sorted({str(c) for c in _ac if isinstance(c, str)}):
        v = _ai[(_ac == f) & np.isfinite(_ai)]
        county_ref[f] = float(np.median(v)) if v.size else np.nan
    log(f"  price-index reference (county median tract income): "
        f"{ {k: round(v) for k, v in county_ref.items() if np.isfinite(v)} }")

    per_cat, zip_preds = {}, {}
    for cat in cats:
        vintage = int(spec["categories"][cat].get("ec_vintage", 2022))
        anchor = ec_anchor(cat, spec, ec[vintage])
        med_anchor = median_anchor(cat, spec, ec[vintage], cbp_county)
        evec, spend_src = spend_vector(cat, spec, quint, national, ny_msa, spend_yaml)
        m = poi_cat == cat
        if m.sum() == 0 or not anchor:
            per_cat[cat] = {"gate": "fail", "reason": "no establishments or no EC anchor"}
            continue
        pool = homes400_poi_all[m] * spend_per_household(poi_income[m], evec, breaks)
        rings = pack.supply("poi", cat)[m]
        zp, cp = poi_zip[m], poi_county[m]
        ref = np.array([county_ref.get(f, np.nan) for f in cp], dtype=float)
        pidx = np.where(np.isfinite(poi_income[m]) & (poi_income[m] > 0)
                        & np.isfinite(ref) & (ref > 0), poi_income[m] / ref, 1.0)

        truth = employees_per_estab(cbp, cat, spec).set_index("zipcode")
        zips_eval = sorted(set(pd.Series(zp).dropna()) & set(truth.index))
        if len(zips_eval) < int(spec["gate"]["min_zips"]):
            per_cat[cat] = {"gate": "fail", "spend_source": spend_src,
                            "reason": f"only {len(zips_eval)} ZIPs have both a "
                                      f"prediction and an unsuppressed CBP cell"}
            continue
        y = truth.loc[zips_eval, "emp_per_estab"].to_numpy()

        # R_hat = Pool^epsilon * P^delta * s(beta, gamma). The pool factor
        # depends only on (epsilon, delta) and the share only on (beta, gamma),
        # so both are computed ONCE per axis value and multiplied -- otherwise
        # v0.2's grid would recompute the same Dijkstra-ring kernel thousands of
        # times. `_grid3` enumerates epsilon-major / delta / shape, in exactly
        # this order.
        def _pool_factor(e, d):
            b = pool if e == 1.0 else np.where(pool > 0, np.power(np.maximum(pool, 0.0), e),
                                               0.0 if e > 0 else 1.0)
            return b if d == 0.0 else b * np.power(np.maximum(pidx, 1e-9), d)

        shares = {(b, g): huff_share(rings, b, edges, d_floor, exclude_self=True, gamma=g)
                  for b, g in shapes}

        def _rhats():
            for e in [float(x) for x in vs["epsilon_grid"]]:
                for d in [float(x) for x in vs["delta_grid"]]:
                    pf = _pool_factor(e, d)
                    for b, g in shapes:
                        yield pf * shares[(b, g)]

        F = _CatFit(_rhats(), zips_eval, zp, cp, anchor)
        nz = len(zips_eval)

        # ---- in-sample candidate choice (reported, NEVER the shipped skill)
        in_scores = np.array([_spearman(F.predict(k, F.lambdas(k)), y)
                              for k in range(len(cands))], dtype=float)
        if not np.any(np.isfinite(in_scores)):
            per_cat[cat] = {"gate": "fail", "spend_source": spend_src,
                            "reason": "no candidate produced a finite score -- the "
                                      "prediction is constant or all-NULL across ZIPs"}
            continue
        # THE SHIPPED CANDIDATE POOL. The full grid is searched for the
        # REPORTED epsilon profile; selection, the folds and the gate run on
        # the SHIPPED specification only (revenue.yaml's `epsilon_shipped`), so
        # the backtest measures the model that actually ships rather than one
        # the argmax of a flat profile preferred. See revenue.yaml for why the
        # unconstrained argmax is not used.
        eps_ship = vs.get("epsilon_shipped")
        cand_eps_all = np.array([c[2] for c in cands])
        pool_idx = (np.flatnonzero(np.isclose(cand_eps_all, float(eps_ship)))
                    if eps_ship is not None else np.arange(len(cands)))
        if pool_idx.size == 0:                                # pragma: no cover
            raise RuntimeError(f"epsilon_shipped {eps_ship} is not on epsilon_grid")

        def _pick(scores_1d, idx):
            """argmax under the parsimony rule, restricted to `idx`."""
            sub = np.asarray(scores_1d)[idx]
            return int(idx[_parsimonious_argmax(sub, [cands[k] for k in idx], eps_tol)])

        k_star = _pick(in_scores, pool_idx)

        # ---- leave-one-ZIP-out: beta, gamma, epsilon, delta AND lambda all
        # refitted without the held-out ZIP. The model selection is INSIDE the
        # fold, which is what makes the reported number out of sample despite a
        # grid search over thousands of candidates.
        #
        # Vectorised over folds: `predict_all_folds` produces, for one
        # candidate, the (fold x ZIP) matrix of predictions, and
        # `_loo_spearman_rows` scores every fold's held-out-excluded ranking in
        # one pass. The arithmetic is identical to the scalar loop v0 ran and
        # `test_predict_all_folds_matches_the_scalar_fold_loop` pins it.
        fold_scores = np.full((len(cands), nz), np.nan)
        fold_diag = np.full((len(cands), nz), np.nan)
        for k in range(len(cands)):
            P = F.predict_all_folds(k)
            fold_scores[k] = _loo_spearman_rows(P, y)
            fold_diag[k] = np.diag(P)
        fold_cands = [_pick(fold_scores[:, i], pool_idx) for i in range(nz)]
        oos = np.array([fold_diag[fold_cands[i], i] for i in range(nz)], dtype=float)

        # ---- the two baselines (parameter-free, so no LOZO penalty applies to
        # them -- the comparison is conservative in the MODEL's disfavour)
        b_county = np.array([(anchor.get(f) or {}).get("rev_per_estab_usd", np.nan)
                             for f in F.zc], dtype=float)
        b_homes = _zip_mean(homes400_poi_all[m], zp, zips_eval).to_numpy()

        s_model, s_county, s_homes = _spearman(oos, y), _spearman(b_county, y), _spearman(b_homes, y)
        margin = float(spec["gate"]["spearman_margin"])
        beats_county = _beats(s_model, s_county, margin)
        beats_homes = _beats(s_model, s_homes, margin)

        # ---- PRICE INDEX: does it add skill? The same leave-one-ZIP-out
        # machinery restricted to delta = 0, scored the same way. A term that
        # does not beat its own absence by `delta_min_skill_gain` does not
        # travel in the shipped equation.
        cand_del = np.array([c[3] for c in cands])
        d0_idx = pool_idx[cand_del[pool_idx] == 0.0]
        fold_cands_d0 = [_pick(fold_scores[:, i], d0_idx) for i in range(nz)]
        oos_d0 = np.array([fold_diag[fold_cands_d0[i], i] for i in range(nz)], dtype=float)
        s_d0, s_all = _spearman(oos_d0, y), _spearman(oos, y)
        gain = float(vs.get("delta_min_skill_gain", 0.0))
        delta_earns = bool(np.isfinite(s_d0) and np.isfinite(s_all) and s_all > s_d0 + gain)
        if not delta_earns:
            k_star, fold_cands, oos = _pick(in_scores, d0_idx), fold_cands_d0, oos_d0

        beta_star, gamma_star, eps_star, delta_star = cands[k_star]
        # LAMBDA IS FITTED ON THE FUNCTION THAT SHIPS, not on the one the
        # backtest scored. The two differ by the site-level gamma cap (7e), and
        # the difference is enormous: an establishment sits on a retail
        # corridor, so for gamma < 0 its uncapped share is a multiplier of
        # several, while every shipped site gets exactly 1.0. Calibrating
        # lambda against the uncapped mean and then applying it to capped
        # predictions divides the whole level by the median establishment's
        # agglomeration multiplier -- measured at ~13x for Manhattan
        # restaurants, which put the median Manhattan restaurant at $130k
        # against a median anchor of $1.67M. The division of labour is:
        # the BACKTEST validates the RANKING and keeps gamma free and uncapped
        # (that is where its ZIP-grain skill lives); LAMBDA sets the LEVEL and
        # must therefore see exactly the predictor that reaches an address.
        rhat_star = _pool_factor(eps_star, delta_star) * shares[(beta_star, gamma_star)]
        s_ship = shares[(beta_star, gamma_star)]
        if vs.get("gamma_site_cap"):
            s_ship = np.minimum(s_ship, 1.0)
        rhat_ship = _pool_factor(eps_star, delta_star) * s_ship
        lam_full = _lambdas(rhat_ship, cp, anchor, med_anchor=med_anchor)
        for d_ in lam_full.values():
            d_["fitted_on"] = ("site-capped share (the shipped predictor)"
                               if vs.get("gamma_site_cap") else "uncapped share")
        zip_preds[cat] = pd.Series(F.predict(k_star, F.lambdas(k_star)), index=zips_eval)

        fold_gammas = [cands[k][1] for k in fold_cands]
        fold_betas = [cands[k][0] for k in fold_cands]
        fold_eps = [cands[k][2] for k in fold_cands]
        fold_deltas = [cands[k][3] for k in fold_cands]

        # ---- epsilon PROFILE, not just the argmax (docstring 7a). For each
        # epsilon on the grid, the best held-out Spearman any candidate at that
        # epsilon reached, averaged over folds. A flat profile is the finding
        # that the ZIP-grain target cannot identify epsilon, and it has to be
        # visible as a flat profile.
        mean_fold = np.nanmean(fold_scores, axis=1)
        eps_profile = {}
        for e in sorted(set(cand_eps_all.tolist())):
            v = mean_fold[cand_eps_all == e]
            eps_profile[str(e)] = (None if not np.any(np.isfinite(v))
                                   else round(float(np.nanmax(v)), 4))
        finite = [v for v in eps_profile.values() if v is not None]
        eps_range = round(max(finite) - min(finite), 4) if len(finite) > 1 else None
        eps_fitted = (max((k for k in eps_profile if eps_profile[k] is not None),
                          key=lambda k: eps_profile[k]) if finite else None)
        # The fold-to-fold spread of the held-out score at the SHIPPED
        # specification. The epsilon profile's whole range has to be read
        # against this: if the range is smaller, the profile is noise.
        fold_sd = float(np.nanstd(fold_scores[k_star])) if np.any(
            np.isfinite(fold_scores[k_star])) else None

        # ---- sigmas for the p25/p75 band
        lv = [d["lambda_per_store"] for d in lam_full.values() if d.get("lambda_per_store")]
        sig_lambda = (abs(math.log(max(lv) / min(lv))) / 2.0) if len(lv) > 1 else 0.0
        sig_lambda = max(sig_lambda, float(spec["uncertainty"]["lambda_min_sigma"]))
        med_rings = np.median(rings, axis=0)[None, :]
        sig_beta = sigma_shape(med_rings, [(cands[k][0], cands[k][1]) for k in fold_cands],
                               (beta_star, gamma_star), edges, d_floor)

        per_cat[cat] = {
            "gate": None,                      # filled by gate_verdict
            "beta": beta_star,
            "gamma": gamma_star,
            "epsilon": eps_star,
            "delta": delta_star,
            "competition_sign": ("competitive" if gamma_star > 0 else
                                 "none" if gamma_star == 0 else "agglomerative"),
            "gamma_site_capped": bool(vs["gamma_site_cap"] and gamma_star < 0),
            "gamma_lozo_folds": {str(g): fold_gammas.count(g) for g in sorted(set(fold_gammas))},
            "beta_lozo_folds": {str(b): fold_betas.count(b) for b in sorted(set(fold_betas))},
            "epsilon_lozo_folds": {str(e): fold_eps.count(e) for e in sorted(set(fold_eps))},
            # WHAT SHIPS vs WHAT THE UNCONSTRAINED SEARCH WANTED. Reported side
            # by side, always, so the gap is never invisible. See revenue.yaml.
            "epsilon_source": ("pinned by the caller (one point of the epsilon scan)"
                               if vs.get("epsilon_shipped") is not None
                               else "unconstrained argmax over the grid"),
            "epsilon_fitted_unconstrained": None if eps_fitted is None else float(eps_fitted),
            "epsilon_profile": eps_profile,
            "epsilon_profile_range": eps_range,
            "fold_score_sd_at_shipped": None if fold_sd is None else round(fold_sd, 4),
            "epsilon_identified": (None if (eps_range is None or fold_sd is None)
                                   else bool(eps_range > fold_sd)),
            "delta_lozo_folds": {str(d): fold_deltas.count(d) for d in sorted(set(fold_deltas))},
            "price_index": {
                "spearman_oos_with_delta": None if not np.isfinite(s_all) else round(s_all, 4),
                "spearman_oos_delta_zero": None if not np.isfinite(s_d0) else round(s_d0, 4),
                "min_gain_required": gain,
                "adds_skill": delta_earns,
                "shipped_delta": delta_star,
                "county_median_tract_income": {k: (None if not np.isfinite(v) else round(v))
                                               for k, v in county_ref.items()},
            },
            "anchor": {
                "statistic": vs["anchor_statistic"],
                "lambda_field": lam_key,
                "per_county": {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv)
                                   for kk, vv in v.items()} for k, v in med_anchor.items()},
            },
            "spend_source": spend_src,
            "annual_spend_by_quintile_usd": [round(float(v), 2) for v in evec],
            "ec_vintage": vintage,
            "lambda": {k: {kk: (round(vv, 6) if isinstance(vv, float) else vv)
                           for kk, vv in v.items()} for k, v in lam_full.items()},
            "backtest": {
                "n_zips": nz,
                "spearman_oos": None if not np.isfinite(s_model) else round(s_model, 4),
                "spearman_insample": None if not np.isfinite(in_scores[k_star])
                                     else round(float(in_scores[k_star]), 4),
                "r2_oos": None if not np.isfinite(_r2(y, oos)) else round(_r2(y, oos), 4),
                "baseline_county_average_spearman": None if not np.isfinite(s_county)
                                                    else round(s_county, 4),
                "baseline_homes_only_spearman": None if not np.isfinite(s_homes)
                                                else round(s_homes, 4),
                "beats_county_average": beats_county,
                "beats_homes_only": beats_homes,
                "frac_zips_model_closer_than_county": _frac_closer(y, oos, b_county),
                "frac_zips_model_closer_than_homes": _frac_closer(y, oos, b_homes),
            },
            "sigma_log": {"lambda": round(sig_lambda, 4), "beta": round(sig_beta, 4)},
            "regime_flag_only": regime_of(cat),
        }

    _placebo(per_cat, zip_preds, cbp, spec, cats)
    for cat in cats:
        gate_verdict(per_cat[cat], spec)

    return {
        "version": 2,
        "model_version": spec["model_version"],
        "settings": {k: v for k, v in version_settings(spec).items() if k != "model_version"},
        "capacity_psf_per_year": ((spec.get("capacity") or {}).get("psf_per_year")
                                  if vs.get("capacity_cap") else None),
        "spec_hash": spec_hash(),
        "asof": dt.datetime.now().isoformat(timespec="seconds"),
        "sweep": pack.report,
        "ec_vintages": {"default": 2022, "pharmacy": 2017},
        "cbp_year": spec["cbp"]["year"],
        "counties": spec["ec"]["counties"],
        "categories": per_cat,
        "not_modelled": list(spec["benchmark_only"]),
    }


def _frac_closer(y, pred, base) -> float | None:
    """Fraction of ZIPs where the model's RANK error is smaller than the
    baseline's. Ranks, not levels: the baselines are not on a revenue scale
    that is comparable to the model's, so an absolute error comparison would
    be scored on units rather than on skill."""
    y, pred, base = np.asarray(y, float), np.asarray(pred, float), np.asarray(base, float)
    ok = np.isfinite(y) & np.isfinite(pred) & np.isfinite(base)
    if ok.sum() < 3:
        return None
    ry = pd.Series(y[ok]).rank(pct=True).to_numpy()
    rp = pd.Series(pred[ok]).rank(pct=True).to_numpy()
    rb = pd.Series(base[ok]).rank(pct=True).to_numpy()
    return round(float(np.mean(np.abs(rp - ry) < np.abs(rb - ry))), 4)


def _placebo(per_cat: dict, zip_preds: dict, cbp: pd.DataFrame, spec: dict,
             cats: list[str]) -> None:
    """Category c's own model must predict c's employees/establishment at least
    as well as any OTHER category's model does. A model that tracks every
    category equally well is tracking generic density, not this business."""
    truths = {c: employees_per_estab(cbp, c, spec).set_index("zipcode")["emp_per_estab"]
              for c in cats}
    for c in cats:
        d = per_cat.get(c) or {}
        if c not in zip_preds or truths[c].empty:
            d["placebo"] = {"passes": False, "reason": "no prediction or no target"}
            continue
        scores = {}
        for other in cats:
            if other not in zip_preds:
                continue
            common = sorted(set(zip_preds[other].index) & set(truths[c].index))
            if len(common) < 8:
                continue
            scores[other] = round(_spearman(zip_preds[other].reindex(common).to_numpy(),
                                            truths[c].reindex(common).to_numpy()), 4)
        own = scores.get(c)
        rivals = {k: v for k, v in scores.items() if k != c and v is not None}
        best_rival = max(rivals, key=rivals.get) if rivals else None
        d["placebo"] = {
            "own_spearman": own,
            "best_rival": best_rival,
            "best_rival_spearman": rivals.get(best_rival) if best_rival else None,
            "passes": bool(own is not None and (best_rival is None or own >= rivals[best_rival])),
            "all": scores,
        }


def gate_verdict(d: dict, spec: dict) -> str:
    """THE CONCRETE FAILURE CRITERION. Mutates `d['gate']` and `d['gate_reason']`."""
    g = spec["gate"]
    if d.get("gate") == "fail":
        d.setdefault("gate_reason", d.get("reason", "no backtest possible"))
        return "fail"
    bt = d.get("backtest") or {}
    s = bt.get("spearman_oos")
    fails = []
    if s is None or s < float(g["min_spearman"]):
        fails.append(f"out-of-sample Spearman {s} < {g['min_spearman']}")
    if "county_average" in g["must_beat"] and not bt.get("beats_county_average"):
        fails.append(f"does not beat the county-average baseline by "
                     f"{g['spearman_margin']} ({s} vs {bt.get('baseline_county_average_spearman')})")
    if "homes_only" in g["must_beat"] and not bt.get("beats_homes_only"):
        fails.append(f"does not beat the homes-only baseline by "
                     f"{g['spearman_margin']} ({s} vs {bt.get('baseline_homes_only_spearman')})")
    if not (d.get("placebo") or {}).get("passes"):
        p = d.get("placebo") or {}
        fails.append(f"placebo: {p.get('best_rival')}'s model predicts this category's "
                     f"employment better ({p.get('best_rival_spearman')} vs {p.get('own_spearman')})")
    d["gate"] = "fail" if fails else "pass"
    d["gate_reason"] = "; ".join(fails) if fails else "beats both baselines out of sample and passes the placebo"
    return d["gate"]


# ------------------------------------------------- the calibration document

_CAL_HEADER = """\
# Site-revenue calibration -- GENERATED by `loci revenue fit`. Do not hand-edit.
# The hand-maintained spec is src/loci/model/revenue.yaml; this file is what
# the gate in src/loci/model/revenue.py let through.
#
# `gate: pass` means, and means ONLY: on leave-one-ZIP-out held-out ZIPs this
# category's predicted revenue per establishment tracked CBP employees per
# establishment with Spearman >= the spec's floor, beat BOTH the county-average
# and homes-only baselines by the spec's margin, and passed the cross-category
# placebo. It does NOT mean the LEVEL is validated -- the level is fitted to the
# Economic Census county mean by construction and has no out-of-sample test
# anywhere, because no public source publishes retail receipts below county
# grain.
#
# `gate: fail` categories are NOT written to the warehouse, keep NULL revenue
# columns, and keep grade D on the recommendation card. That is the point of
# the file: it records which categories the model cannot support.
"""


def save_calibration(doc: dict, path: pathlib.Path | None = None) -> pathlib.Path:
    """Write revenue_calibration.yaml. REFUSES if no category passed the gate:
    a file saying nothing works would be read as a shipped model."""
    passing = [c for c, d in doc["categories"].items() if (d or {}).get("gate") == "pass"]
    if not passing:
        raise RuntimeError(
            "revenue fit: NO category beat both baselines out of sample, so there is "
            "nothing to ship and the calibration file is not written. Every category "
            "stays 'not modelled' and every economics section stays grade D. "
            "Reasons per category: " + "; ".join(
                f"{c}: {(d or {}).get('gate_reason')}" for c, d in doc["categories"].items()))
    clean = json.loads(json.dumps(doc, default=str))
    for d in clean["categories"].values():
        d.pop("_oos", None)
    p = path or CALIBRATION_PATH
    p.write_text(_CAL_HEADER + yaml.safe_dump(clean, sort_keys=False, width=100))
    return p


# ------------------------------------------------------- address prediction

def predict_addresses(pack: RingPack, cal: dict, spec: dict | None = None,
                      areas: pd.DataFrame | None = None) -> tuple:
    """(category long frame, address frame). Only categories whose calibration
    PASSED the gate get rows; everything else stays NULL by omission.

    `areas` is `lot_retail_area`'s frame, required when the calibration's
    version switches the capacity ceiling on; without it the ceiling cannot be
    evaluated and the run REFUSES rather than shipping uncapped numbers under a
    version string that claims a cap.
    """
    spec = spec or load_spec()
    edges = [float(x) for x in spec["huff"]["ring_edges_m"]]
    d_floor = float(spec["huff"]["d_floor_m"])
    breaks = spec["cex"]["quintile_income_breaks_usd"]
    pool_r = float(spec["huff"]["pool_radius_m"])
    z90 = float(spec["cex"]["moe_z90"])
    ocr = load_benchmarks()["occupancy_cost_ratio"]
    quint, national, ny_msa = load_cex_quintiles(spec), load_cex_national(spec), load_cex_ny_msa(spec)
    spend_yaml = load_spend()

    vs = version_settings(spec)
    lam_key = _lambda_key(vs)

    homes400 = pack.homes("addr", pool_r)
    homes800 = pack.homes("addr", edges[-1])
    inc = pack.addr["median_hh_income"].to_numpy(dtype=float)
    moe = pack.addr["median_hh_income_moe"].to_numpy(dtype=float)
    se = np.where(np.isfinite(moe), moe / z90, np.nan)
    county = pack.addr["county"].to_numpy()

    # The price-index reference, recomputed the same way the fit computed it
    # (county median tract income over the address frame). It is a property of
    # the county, not of the fit, so recomputing it here rather than reading it
    # back is what keeps the apply path independent of the calibration file's
    # rounding.
    cref = np.full(len(inc), np.nan)
    for f in sorted({str(c) for c in county if isinstance(c, str)}):
        sel = county == f
        v = inc[sel & np.isfinite(inc)]
        if v.size:
            cref[sel] = float(np.median(v))
    pidx_addr = np.where(np.isfinite(inc) & (inc > 0) & np.isfinite(cref) & (cref > 0),
                         inc / cref, 1.0)

    # Capacity: PLUTO retail area on the lot, split by the storefront count.
    cap_area_by_row = None
    if vs.get("capacity_cap"):
        if areas is None:
            raise RuntimeError(
                "revenue: model_version declares a capacity ceiling but no PLUTO retail-area "
                "frame was supplied. Shipping uncapped numbers under a version string that "
                "claims a cap would be the worst of both. Pass `areas=lot_retail_area(con)`.")
        bbl = pack.addr["bbl"].astype("string").to_numpy()
        a = (pd.DataFrame({"bbl": bbl})
             .merge(areas[["bbl", "demise_sqft", "storefronts_on_bbl"]], on="bbl", how="left"))
        cap_area_by_row = (a["demise_sqft"].to_numpy(dtype=float),
                           a["storefronts_on_bbl"].fillna(0).to_numpy(dtype=float))

    frames, cap_report = [], {}
    for cat, d in (cal.get("categories") or {}).items():
        if (d or {}).get("gate") != "pass":
            continue
        evec, _ = spend_vector(cat, spec, quint, national, ny_msa, spend_yaml)
        E = spend_per_household(inc, evec, breaks)
        # sigma_income: the tract median moves +/- 1 SE and the address can
        # cross a quintile boundary. A genuine discrete jump, not a smooth
        # derivative -- which is why it is evaluated, not differentiated.
        E_lo = spend_per_household(np.where(np.isfinite(se), inc - se, inc), evec, breaks)
        E_hi = spend_per_household(np.where(np.isfinite(se), inc + se, inc), evec, breaks)
        with np.errstate(divide="ignore", invalid="ignore"):
            sig_inc = np.where((E_lo > 0) & (E_hi > 0), np.abs(np.log(E_hi / E_lo)) / 2.0, 0.0)
        sig_inc = np.nan_to_num(sig_inc, nan=0.0)

        beta, gamma = float(d["beta"]), float(d.get("gamma", 1.0))
        eps, dlt = float(d.get("epsilon", 1.0)), float(d.get("delta", 0.0))
        rhat = uncalibrated(homes400 * E, pack.supply("addr", cat), beta, edges,
                            d_floor, gamma=gamma, epsilon=eps,
                            pindex=pidx_addr, delta=dlt,
                            gamma_site_cap=bool(vs.get("gamma_site_cap")))
        lam = np.full(len(rhat), np.nan)
        for fips, ld in (d.get("lambda") or {}).items():
            v = ld.get(lam_key)
            if v is None:                # the anchor fell back; the mean lambda ships
                v = ld.get("lambda_per_store")
            if v is not None:
                lam[county == fips] = float(v)
        p50 = rhat * lam

        sg = d.get("sigma_log") or {}
        sig = np.sqrt(float(sg.get("lambda", 0.0)) ** 2 + float(sg.get("beta", 0.0)) ** 2
                      + sig_inc ** 2)
        z = 0.6744897501960817                       # the 75th-percentile normal deviate
        p25 = p50 * np.exp(-z * sig)
        p75 = p50 * np.exp(z * sig)

        # ---- the capacity ceiling (docstring 7d). ONE-SIGNED: it can only
        # lower a number, never raise one, and `test_capacity_cap_never_raises`
        # pins that.
        band = capacity_band(cat, spec)
        cap50 = np.full(len(p50), np.nan)
        bound = np.zeros(len(p50), dtype=bool)
        typical = np.zeros(len(p50), dtype=bool)
        split = np.zeros(len(p50), dtype=bool)
        if vs.get("capacity_cap") and band:
            demise, sf_count = cap_area_by_row
            area, typical = capacity_area(demise, cat, spec)
            split = sf_count > 1
            cap25, cap50, cap75 = (area * band["p25"], area * band["p50"], area * band["p75"])
            ok_cap = np.isfinite(cap50) & (cap50 > 0)
            bound = ok_cap & np.isfinite(p50) & (cap50 < p50)
            p25 = np.where(ok_cap, np.minimum(p25, cap25), p25)
            p50 = np.where(ok_cap, np.minimum(p50, cap50), p50)
            p75 = np.where(ok_cap, np.minimum(p75, cap75), p75)

        ok = np.isfinite(p50) & (p50 > 0)
        frames.append(pd.DataFrame({
            "address_id": pack.addr["address_id"].to_numpy()[ok],
            "borough": pack.addr["borough"].to_numpy()[ok],
            "category": cat,
            "revenue_p25": p25[ok],
            "revenue_p50": p50[ok],
            "revenue_p75": p75[ok],
            "rent_ceiling": p50[ok] * float(ocr[cat]),
            "revenue_model_version": cal["model_version"],
            "revenue_cap_p50": cap50[ok],
            "capacity_bound": bound[ok],
        }))
        n = int(ok.sum())
        cap_report[cat] = {
            "rows": n,
            "capacity_bound": int(bound[ok].sum()),
            "capacity_bound_share": round(float(bound[ok].mean()), 4) if n else None,
            # FLAGS, per docstring 7d: a typical-footprint row does not know how
            # big its box is, and a split row is one storefront of several on a
            # lot whose retail area PLUTO reports whole.
            "area_from_typical_footprint": int(typical[ok].sum()) if vs.get("capacity_cap") else 0,
            "area_split_by_storefront_count": int(split[ok].sum()) if vs.get("capacity_cap") else 0,
            "median_cap_p50_usd": (None if not np.isfinite(np.nanmedian(cap50[ok]))
                                   else round(float(np.nanmedian(cap50[ok])))) if n else None,
            "median_model_p50_before_cap_usd": (round(float(np.nanmedian((rhat * lam)[ok])))
                                                if n else None),
            "median_shipped_p50_usd": round(float(np.nanmedian(p50[ok]))) if n else None,
        }

    long_df = (pd.concat(frames, ignore_index=True) if frames
               else pd.DataFrame(columns=["address_id", "borough", "category",
                                          *CATEGORY_REVENUE_COLUMNS]))
    long_df.attrs["capacity"] = cap_report
    addr_df = pd.DataFrame({
        "address_id": pack.addr["address_id"],
        "borough": pack.addr["borough"],
        "homes_800m": np.rint(homes800).astype("int64"),
    })
    return long_df, addr_df


# --------------------------------------------------------------- the write

def _guard(cols: list[str], table: str) -> None:
    """Refuse to write if the SET list touches a column another module owns."""
    forbidden: set[str] = set()
    try:
        from loci.model.address_demand import DEMAND_ANNOTATION_COLUMNS
        from loci.model.address_gaps import ADDRESS_CATEGORY_SCREEN_COLUMNS
        from loci.model.dev_pipeline import PIPELINE_COLUMNS
        from loci.model.storefronts import AGE_FIT_COLUMNS, STOREFRONT_COLUMNS
        from loci.model.supply_ratio import (ADDRESS_RATIO_COLUMNS, ADDRESS_SCREEN_COLUMNS,
                                             CATEGORY_RATIO_COLUMNS)
        forbidden |= set(ADDRESS_SCREEN_COLUMNS) | set(ADDRESS_CATEGORY_SCREEN_COLUMNS)
        forbidden |= set(PIPELINE_COLUMNS) | set(STOREFRONT_COLUMNS) | set(AGE_FIT_COLUMNS)
        forbidden |= set(DEMAND_ANNOTATION_COLUMNS)
        forbidden |= set(ADDRESS_RATIO_COLUMNS) | set(CATEGORY_RATIO_COLUMNS)
    except ImportError:                                      # pragma: no cover
        pass
    overlap = sorted(set(cols) & forbidden)
    if overlap:
        raise RuntimeError(f"revenue would clobber {table} columns: {overlap}")


def write_revenue(con, long_df: pd.DataFrame, boroughs: list[str]) -> int:
    """UPDATE-only on analysis.address_category. RESET then UPDATE, so a
    category that LOST its calibration (the gate now fails) loses its numbers
    instead of keeping last run's."""
    if not boroughs:
        return 0
    _guard(CATEGORY_REVENUE_COLUMNS, "analysis.address_category")
    holes = ", ".join("?" for _ in boroughs)
    reset = ", ".join(f"{c} = NULL" for c in CATEGORY_REVENUE_COLUMNS)
    con.execute(f"UPDATE analysis.address_category SET {reset} WHERE borough IN ({holes})",
                list(boroughs))
    if long_df.empty:
        return 0
    # A column the caller did not produce is written NULL, not omitted: the
    # RESET above already cleared the scope, and a v0 calibration legitimately
    # produces no capacity columns. Adding it here keeps the SET list one fixed
    # pinned list rather than something that varies with the model version.
    long_df = long_df.copy()
    for c in CATEGORY_REVENUE_COLUMNS:
        if c not in long_df.columns:
            long_df[c] = None
    payload = long_df[["address_id", "borough", "category", *CATEGORY_REVENUE_COLUMNS]]
    con.register("_rev_cat", payload)
    try:
        sets = ", ".join(f"{c} = _rev_cat.{c}" for c in CATEGORY_REVENUE_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address_category AS ac SET {sets}
            FROM _rev_cat
            WHERE ac.address_id = _rev_cat.address_id
              AND ac.borough  = _rev_cat.borough
              AND ac.category = _rev_cat.category
        """)
    finally:
        con.unregister("_rev_cat")
    return len(payload)


def write_address_revenue(con, addr_df: pd.DataFrame, boroughs: list[str]) -> int:
    """UPDATE-only on analysis.address -- homes_800m only (D61: it does not
    vary by category, so it does not go on address_category)."""
    if not boroughs:
        return 0
    _guard(ADDRESS_REVENUE_COLUMNS, "analysis.address")
    holes = ", ".join("?" for _ in boroughs)
    reset = ", ".join(f"{c} = NULL" for c in ADDRESS_REVENUE_COLUMNS)
    con.execute(f"UPDATE analysis.address SET {reset} WHERE borough IN ({holes})",
                list(boroughs))
    if addr_df.empty:
        return 0
    con.register("_rev_addr", addr_df)
    try:
        sets = ", ".join(f"{c} = _rev_addr.{c}" for c in ADDRESS_REVENUE_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address AS a SET {sets}
            FROM _rev_addr
            WHERE a.address_id = _rev_addr.address_id AND a.borough = _rev_addr.borough
        """)
    finally:
        con.unregister("_rev_addr")
    return len(addr_df)


def build_revenue(con, boroughs: list[str], spec: dict | None = None,
                  dry_run: bool = False, log=print) -> dict:
    """Re-appliable apply path: read the SHIPPED calibration, sweep, predict,
    UPDATE. Never re-calibrates -- `loci revenue fit` is the only path that
    touches revenue_calibration.yaml."""
    spec = spec or load_spec()
    cal = load_calibration()
    if not cal:
        raise RuntimeError(
            "no src/loci/model/revenue_calibration.yaml -- run `loci revenue fit` first. "
            "Applying an uncalibrated model would write household spend times a share "
            "and call it revenue.")
    if cal.get("spec_hash") != spec_hash():
        log("  WARNING: revenue.yaml has changed since the calibration was fitted "
            f"(spec_hash {cal.get('spec_hash')} -> {spec_hash()}); re-fit before trusting "
            "these numbers.")
    pack = compute_rings(con, boroughs, spec, log=log)
    live = pack.report["supply_hash"]
    stamped = (cal.get("sweep") or {}).get("supply_hash")
    if stamped and stamped != live:
        log(f"  WARNING: supply hash drift {stamped} -> {live}: lambda was calibrated "
            f"against a different incumbent set.")
    vs = version_settings(spec)
    areas = lot_retail_area(con, spec) if vs.get("capacity_cap") else None
    if areas is not None:
        log(f"  capacity: {len(areas):,} PLUTO lots, "
            f"{int((areas['retail_area_sqft'] > 0).sum()):,} with retailarea > 0, "
            f"{int((areas['storefronts_on_bbl'] > 1).sum()):,} with >1 registered storefront")
    long_df, addr_df = predict_addresses(pack, cal, spec, areas=areas)

    # VERIFICATION, not a dependency: this module recomputes homes_400m from
    # its own sweep rather than reading D73's column, so a revenue run does not
    # silently depend on whether `loci supply-ratio` has run since the last
    # screen re-apply. The two must nevertheless agree -- they are the same
    # measure off the same graph -- and a disagreement means one of the two
    # sweeps is wrong. Reported, never silently reconciled.
    agree = None
    try:
        holes = ", ".join("?" for _ in boroughs)
        stored = con.execute(
            f"SELECT address_id, homes_400m FROM analysis.address "
            f"WHERE homes_400m IS NOT NULL AND borough IN ({holes})",
            list(boroughs)).fetchdf()
        mine = pd.DataFrame({
            "address_id": pack.addr["address_id"].to_numpy(),
            "mine": np.rint(pack.homes("addr", float(spec["huff"]["pool_radius_m"])))})
        j = stored.merge(mine, on="address_id", how="inner")
        if len(j):
            agree = float((j["homes_400m"].astype(float) == j["mine"].astype(float)).mean())
    except Exception:                  # noqa: BLE001 -- the column may not exist yet
        agree = None

    report = dict(pack.report)
    report["homes_400m_agrees_with_supply_ratio"] = agree
    report.update({
        "shipped_categories": sorted(shipped_categories(cal)),
        "not_modelled": sorted((set(spec["modelled"]) | set(spec["flagged"])
                                | set(spec["benchmark_only"])) - shipped_categories(cal)),
        "rows_predicted": int(len(long_df)),
        "model_version": cal.get("model_version"),
        "capacity": long_df.attrs.get("capacity") or {},
        "calibration_spec_hash": cal.get("spec_hash"),
        "calibration_supply_hash": stamped,
        "supply_hash_drift": bool(stamped and stamped != live),
    })
    if not dry_run:
        report["_written_category"] = write_revenue(con, long_df, boroughs)
        report["_written_address"] = write_address_revenue(con, addr_df, boroughs)
    return report
