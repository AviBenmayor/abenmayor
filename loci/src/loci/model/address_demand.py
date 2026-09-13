"""The D49 demand-side annotation, ported to the D38 address grain (GTM-110),
FOLDED onto analysis.address_category (D58).

WHAT THIS IS
--------------------------------------------------------------------------
`analysis.address_gaps` says WHERE a category is missing. This module says
what is KNOWN ABOUT DEMAND at that address for that category, and nothing
else. It is the address-grain re-implementation of the annotation D49 built
for `model/gaps.py`'s hex screen; that hex annotation is frozen history
(D38: address is the unit of analysis, the hex tables take no new work), so
this is now the ONLY live copy.

It is emphatically NOT the retired binary badge. D49 retired
`income_class`-as-a-verdict because ACS median-income MOE is ~27% of the
estimate and more than half of gap units sit within one MOE of the 0.80 line
-- a boolean there is a coin flip wearing a label. What survives is
continuous and MOE-gated: `income_ratio` with its propagated MOE,
`income_indeterminate` for the units the data cannot separate, and a caveat
asserted ONLY when the address is confidently below the line
(`income_ratio + income_ratio_moe < low_income_cutoff`).

NON-FILTERING BY CODE, NOT BY TABLE BOUNDARY (D58)
--------------------------------------------------------------------------
D57 made this a SIBLING table (analysis.address_demand) precisely so the
D48 rule ("the output is graded, never filtered") was mechanical: the module
had no write path to the screen's own columns at all. D58 folded the
annotation columns onto analysis.address_category instead (one row per
address x category already; a second table with the same key was pure
overhead), which gives that mechanical guarantee up -- so it is replaced by
a narrower one, enforced here in code: `write_address_demand` issues ONLY
`UPDATE analysis.address_category SET <DEMAND_ANNOTATION_COLUMNS>`. It never
INSERTs, never DELETEs, and the SET list is built exclusively from
DEMAND_ANNOTATION_COLUMNS, which is disjoint from the screen's own columns
(nearest_m, ratio, is_lead, eligible) by construction -- a test pins that
disjointness, and `tests/test_address_demand.py` still re-runs the D57 proof
on real shape: analysis.address_gaps' `gap_score`, `lead_category`,
`n_missing` and `eligible` are byte-identical before and after a build, and
the ratio > 1 rows annotated here are exactly address_gaps' own missing set.
A RESET-then-UPDATE pattern (see write_address_demand) clears a stale
verdict from a category that leaves the missing/lead set on a re-run,
without ever touching a row this module does not own.

GRAIN
--------------------------------------------------------------------------
One row per (address_id, category, run key), where the run key is
(reach_hash, supply_hash) -- the two inputs that decide what "missing" and
"nearest" mean, carried over from address_gaps so an annotation row is always
traceable to the run it annotates. Rows are emitted for:

  * every category whose address-level `ratio` exceeds 1.0 -- the CONTINUOUS
    reading of "missing" adopted in D41/D39 (nearest business sits beyond the
    category's reach), not a binary gap flag; plus
  * the address's `lead_category`, always, so the headline category of every
    address carries its demand context even in the rare case where the
    lead's own ratio is <= 1 (an address with no gap at all).
    Those rows are flagged `is_lead` and are the ONLY rows with ratio <= 1.

WHICH INCOME
--------------------------------------------------------------------------
`income_ratio`'s numerator is `analysis.address_demographics.median_hh_income`
-- the address's own 2020 census TRACT median, assigned by a BBL lookup with
no apportionment (a PLUTO lot sits in exactly one tract; D56). An earlier
version of migration 008 briefly added a SECOND, hex-interpolated
median_hh_income to analysis.address_gaps (tract -> hex by PLUTO unit share,
then hex -> address by containment, a step function across hex boundaries);
that copy is gone (D56/D58: address_gaps carries no demographics at all, see
model/address_gaps.py), so there is now only one number, and it is this one.

CLINIC
--------------------------------------------------------------------------
Clinic rows exist (it can be missing like anything else) but can never be
caveated: `demand.caveat_categories()` excludes it via `annotate: false`, per
D30 -- loci's clinic category deliberately excludes doctors' offices and no
external source reproduces that exclusion, so the layer is not trusted enough
to assert a demand explanation on top of it. The exclusion is independent of
the derived class, so a later coverage fix cannot silently start caveating it.

RENDERING
--------------------------------------------------------------------------
`demand_caveat_text` must be rendered UNTRUNCATED. The X6 disclaimer is its
TAIL, and it is the sentence that stops the annotation from laundering
under-provision as absent demand (Meltzer & Schuetz find race predicts retail
NET of income). A UI that clips the string keeps the income claim and drops
the warning -- exactly backwards.
"""
from __future__ import annotations

import dataclasses

import pandas as pd

from loci.demand import (
    X6_DISCLAIMER,
    caveat_categories,
    load_demand,
    load_low_income_cutoff,
    ratio_moe,
)
#: The ACS vintage this annotation reads, matching model/address_demographics.py
#: and gaps.py's own pinned 2023. A single vintage, stated once: pooling two
#: vintages' medians into one ratio would silently mix denominators.
ACS_YEAR = 2023

#: The ONLY columns write_address_demand is allowed to name in a SET clause
#: (D58). Disjoint from analysis.address_category's screen-owned columns
#: (address_id, borough, category, nearest_m, ratio, is_lead, eligible) by
#: construction -- tests/test_address_demand.py asserts that disjointness --
#: so this module cannot accidentally clobber the screen with a plain re-run
#: of the annotation, even though it shares a table with the screen now.
DEMAND_ANNOTATION_COLUMNS = [
    "demand_class", "elasticity",
    "income_ratio", "income_ratio_moe", "income_indeterminate",
    "demand_caveat", "demand_caveat_text", "acs_year",
]

#: compute_address_demand's output frame, in column order: the screen
#: context it read (address_id/bbl/borough/category/is_lead/eligible/ratio/
#: nearest_m, all read-only copies off analysis.address_category /
#: analysis.address) followed by DEMAND_ANNOTATION_COLUMNS, the only part of
#: this list write_address_demand ever writes.
ADDRESS_DEMAND_COLUMNS = [
    "address_id", "bbl", "borough", "category",
    "is_lead", "eligible", "ratio", "nearest_m",
    *DEMAND_ANNOTATION_COLUMNS,
]


# ----------------------------------------------------------- income context

@dataclasses.dataclass(frozen=True)
class AddressIncomeContext:
    """Per-address demand-side context. Purely additive: nothing in this
    dataclass may gate membership in address_gaps' missing set, or any rank
    or score there -- this module has no write path to that table at all."""
    income_ratio: float | None        # tract median_hh_income / citywide MEAN
    income_ratio_moe: float | None    # 90%-confidence MOE on that ratio
    income_indeterminate: bool | None # cutoff sits within one MOE of the ratio
    confidently_low: bool             # ratio + moe < cutoff; the ONLY caveat trigger


#: No income (address with no tract, or a tract with no ACS median). Fails
#: closed: no ratio, no MOE, no assertion, no caveat.
NO_INCOME = AddressIncomeContext(None, None, None, False)


def _citywide_income() -> tuple[float | None, float | None]:
    """(mean, MOE) of citywide household income, from
    `loci.grid.acs.load_citywide_mean_hh_income` (ACS B19025/B11001 over the
    five NYC counties, cached under data/interim/).

    Its own function, and also injectable through `compute_address_demand`'s
    `citywide=` argument, so tests can pin it: the real value is a live ACS
    quantity behind a gitignored cache and no unit test should depend on the
    network or on a machine's cache state. Production still fails closed --
    the loader raises rather than guessing a dollar figure."""
    from loci.grid.acs import load_citywide_mean_hh_income
    rec = load_citywide_mean_hh_income()
    return rec["mean_hh_income"], rec["mean_hh_income_moe"]


def income_context(income: float | None, income_moe: float | None,
                   citywide_mean: float | None, citywide_moe: float | None,
                   cutoff: float) -> AddressIncomeContext:
    """The D49 test, at one address.

    `income` is the address's TRACT median household income (B19013, taken
    directly -- a PLUTO lot sits in exactly one 2020 tract, so there is
    nothing to apportion; see model/address_demographics.py). The denominator
    is the citywide MEAN household income, household-weighted -- Meltzer &
    Schuetz's own quantity, NOT a mean of tract medians (D49 §denominator).

    Three states, and the difference between them is the whole point:

      * confidently low   -- ratio + moe < cutoff. The only state that can
        produce a caveat.
      * indeterminate     -- |ratio - cutoff| <= moe. The cutoff sits inside
        the margin; the classification is a coin flip and must not be read.
      * unknown MOE       -- income known, MOE not. `income_ratio_moe` and
        `income_indeterminate` are both None and `confidently_low` is False:
        no MOE, no assertion (fail closed).
    """
    if income is None or citywide_mean in (None, 0):
        return NO_INCOME
    ratio = income / citywide_mean
    moe = ratio_moe(income, income_moe, citywide_mean, citywide_moe)
    return AddressIncomeContext(
        income_ratio=ratio,
        income_ratio_moe=moe,
        income_indeterminate=None if moe is None else abs(ratio - cutoff) <= moe,
        confidently_low=False if moe is None else (ratio + moe) < cutoff,
    )


def caveat_text(ic: AddressIncomeContext, category: str,
                demand: dict[str, dict]) -> str | None:
    """The worded, continuous caveat for ONE (address, category) row --
    emitted only when the address is confidently below the cutoff.

    Wording deliberately mirrors `model/gaps._caveat_text` character for
    character (the hex version lists every caveated category of the hex; at
    this grain the row IS one category, so the list has one element). The
    mirror is pinned by tests/test_address_demand.py rather than shared by
    import: gaps.py is frozen history under D38 and takes no edits.

    Always ends with `loci.demand.X6_DISCLAIMER`. Do not render the ratio
    without it, and do not truncate the string -- the disclaimer is the tail.
    """
    if not ic.confidently_low or ic.income_ratio is None:
        return None
    pts = "" if ic.income_ratio_moe is None else f" (±{ic.income_ratio_moe * 100:.0f} pts)"
    cats = f"{category} {demand[category]['elasticity']:.2f}"
    return (f"household income {ic.income_ratio * 100:.0f}% of citywide mean{pts}; "
            f"category income elasticity (BLS CEX): {cats}. {X6_DISCLAIMER}")


# ----------------------------------------------------------------- the read

def _long_form_sql(boroughs: list[str]) -> str:
    """analysis.address_category IS the long-form table already (D58) -- one
    row per (address, category), is_lead/eligible/ratio/nearest_m all native
    columns -- so there is no unpivot to write any more; this is a plain
    read, keeping only rows that are missing (ratio > 1, the D41 continuous
    reading) or are the address's lead.
    """
    holes = ", ".join("?" for _ in boroughs)
    return f"""
        SELECT c.address_id, a.bbl, c.borough, c.category,
               c.is_lead, c.eligible, c.ratio, c.nearest_m,
               d.median_hh_income, d.median_hh_income_moe
        FROM analysis.address_category c
        JOIN analysis.address a ON a.address_id = c.address_id AND a.borough = c.borough
        LEFT JOIN analysis.address_demographics d
               ON d.address_id = c.address_id AND d.acs_year = ?
        WHERE c.borough IN ({holes})
          AND (c.ratio > 1.0 OR c.is_lead)
    """


def compute_address_demand(
    con, boroughs: list[str],
    citywide: tuple[float | None, float | None] | None = None,
    cutoff: float | None = None,
    acs_year: int = ACS_YEAR,
) -> pd.DataFrame:
    """Build the annotation frame. READ-ONLY over analysis.address_category,
    analysis.address and analysis.address_demographics -- it issues no
    UPDATE, no DELETE and no INSERT against any of them; only
    write_address_demand does, and only on DEMAND_ANNOTATION_COLUMNS.

    `citywide` and `cutoff` are injectable for tests; in production both come
    from the same places D49 fixed them: the ACS B19025/B11001 citywide mean
    and demand.yaml's `low_income_cutoff` (0.80).
    """
    cutoff = load_low_income_cutoff() if cutoff is None else cutoff
    citywide_mean, citywide_moe = citywide if citywide is not None else _citywide_income()
    demand = load_demand()
    eligible_for_caveat = caveat_categories()

    df = con.execute(_long_form_sql(boroughs), [acs_year, *boroughs]).fetchdf()
    if df.empty:
        return pd.DataFrame(columns=ADDRESS_DEMAND_COLUMNS)

    # One IncomeContext per DISTINCT (income, moe) pair, not per row: the
    # income is a tract attribute repeated across every address in the tract
    # (~2,300 tracts vs ~1.5M rows), and computing it once per distinct pair
    # means the scalar `income_context` -- the function the MOE-gating tests
    # exercise -- is literally the code that runs in production. No second,
    # vectorized implementation to drift.
    inc = df["median_hh_income"].astype(object).where(df["median_hh_income"].notna(), None)
    inc_moe = df["median_hh_income_moe"].astype(object).where(
        df["median_hh_income_moe"].notna(), None)
    keys = list(zip(inc, inc_moe))
    ctx_by_key = {
        k: income_context(k[0], k[1], citywide_mean, citywide_moe, cutoff)
        for k in dict.fromkeys(keys)
    }
    ctxs = [ctx_by_key[k] for k in keys]

    cats = df["category"].tolist()
    out = pd.DataFrame({
        "address_id": df["address_id"],
        "bbl": df["bbl"],
        "borough": df["borough"],
        "category": df["category"],
        "is_lead": df["is_lead"].astype(bool),
        "eligible": df["eligible"].astype(bool),
        "ratio": df["ratio"],
        "nearest_m": df["nearest_m"],
        "demand_class": [demand[c]["income_elasticity"] for c in cats],
        "elasticity": [demand[c]["elasticity"] for c in cats],
        "income_ratio": [ic.income_ratio for ic in ctxs],
        "income_ratio_moe": [ic.income_ratio_moe for ic in ctxs],
        "income_indeterminate": pd.Series([ic.income_indeterminate for ic in ctxs],
                                          dtype="object"),
        # THE gate, in one expression: discretionary AND not excluded from the
        # annotation (clinic, D30) AND confidently below the cutoff. A category
        # that is a necessity, or an address whose MOE is unknown or straddles
        # the line, is never caveated.
        "demand_caveat": [c in eligible_for_caveat and ic.confidently_low
                          for c, ic in zip(cats, ctxs)],
        "acs_year": acs_year,
    })
    out["demand_caveat_text"] = [
        caveat_text(ic, c, demand) if caveated else None
        for ic, c, caveated in zip(ctxs, cats, out["demand_caveat"])
    ]
    return out[ADDRESS_DEMAND_COLUMNS]


# ---------------------------------------------------------------- the write

def write_address_demand(con, df: pd.DataFrame, boroughs: list[str]) -> int:
    """Annotate analysis.address_category for `boroughs`. Issues ONLY
    `UPDATE ... SET <DEMAND_ANNOTATION_COLUMNS>` -- never INSERT, never
    DELETE, and the SET list never names a screen-owned column (D58; see the
    module docstring's non-filtering note).

    Two passes, both UPDATE:
      1. RESET every row in scope (every (address, category) pair whose
         borough is in `boroughs`) to NULL on the annotation columns. Without
         this, a category that WAS caveated/annotated on a previous run but
         falls out of the missing-or-lead set on this run (a tightened reach
         table, a different supply set) would keep last run's verdict
         forever -- UPDATE has no DELETE to fall back on to clear it.
      2. UPDATE ... FROM the computed frame, joined on (address_id, borough,
         category), for the rows actually in scope this run.
    `boroughs` is passed explicitly (not inferred from `df`) so an empty-df
    run (nothing missing, nothing led -- impossible in practice since every
    address always has a lead row, but not assumed here) still
    resets rather than silently leaving stale annotations in place.
    """
    if not boroughs:
        return 0
    reset_cols = ", ".join(f"{c} = NULL" for c in DEMAND_ANNOTATION_COLUMNS)
    holes = ", ".join("?" for _ in boroughs)
    con.execute(
        f"UPDATE analysis.address_category SET {reset_cols} WHERE borough IN ({holes})",
        list(boroughs),
    )
    if df.empty:
        return 0
    con.register("_ad", df)
    try:
        set_clause = ", ".join(f"{c} = _ad.{c}" for c in DEMAND_ANNOTATION_COLUMNS)
        con.execute(f"""
            UPDATE analysis.address_category AS ac
            SET {set_clause}
            FROM _ad
            WHERE ac.address_id = _ad.address_id
              AND ac.borough = _ad.borough
              AND ac.category = _ad.category
        """)
    finally:
        con.unregister("_ad")
    return len(df)


def build_address_demand(con, boroughs: list[str], **kwargs) -> tuple[int, pd.DataFrame]:
    """compute + write. Returns (rows written, the frame) so the CLI prints
    the same summary on the write path as under --dry-run."""
    df = compute_address_demand(con, boroughs, **kwargs)
    return write_address_demand(con, df, boroughs), df


# ------------------------------------------------------------- reporting

def summarize(df: pd.DataFrame, top_n: int = 6) -> dict:
    """Pure, DB-free summary shared by --dry-run and the post-write report."""
    n = len(df)
    if not n:
        return {"n_rows": 0, "n_caveated": 0, "caveat_share": 0.0,
                "n_indeterminate": 0, "indeterminate_share": 0.0,
                "indeterminate_share_of_known_moe": None,
                "caveated_by_category": {}, "n_addresses": 0,
                "n_lead_caveated": 0, "lead_caveat_share": 0.0}

    caveat = df["demand_caveat"].astype(bool)
    indet = df["income_indeterminate"].fillna(False).astype(bool)
    known_moe = df["income_ratio_moe"].notna()
    lead = df["is_lead"].astype(bool)

    by_cat = (df.loc[caveat, "category"].value_counts().head(top_n).to_dict())
    n_addr = int(df["address_id"].nunique())
    n_lead_cav = int((lead & caveat).sum())
    n_lead = int(lead.sum())

    return {
        "n_rows": n,
        "n_caveated": int(caveat.sum()),
        "caveat_share": float(caveat.mean()),
        "n_indeterminate": int(indet.sum()),
        "indeterminate_share": float(indet.mean()),
        "indeterminate_share_of_known_moe": (
            float(indet[known_moe].mean()) if known_moe.any() else None),
        "caveated_by_category": by_cat,
        "n_addresses": n_addr,
        "n_lead_rows": n_lead,
        "n_lead_caveated": n_lead_cav,
        "lead_caveat_share": float(n_lead_cav / n_lead) if n_lead else 0.0,
    }
