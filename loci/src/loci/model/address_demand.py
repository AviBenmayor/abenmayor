"""The D49 demand-side annotation, ported to the D38 address grain (GTM-110).

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

NON-FILTERING BY CONSTRUCTION
--------------------------------------------------------------------------
The table is a SIBLING of `analysis.address_gaps`, keyed by address_id, and
this module opens address_gaps read-only. It cannot change `gap_score`,
`lead_category`, `n_missing` or membership in the missing set, because it
never writes to that table -- the D48 rule ("the output is graded, never
filtered") is enforced by the shape of the code, not by a convention.
`tests/test_address_demand.py` pins that: address_gaps' `gap_score` and
`lead_category` are byte-identical before and after a build, and the
ratio > 1 rows here are exactly address_gaps' own missing set.

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
    eligible address carries its demand context even in the rare case where
    the lead's own ratio is <= 1 (an eligible address with no gap at all).
    Those rows are flagged `is_lead` and are the ONLY rows with ratio <= 1.

WHICH INCOME, OF THE TWO NOW ON DISK
--------------------------------------------------------------------------
`income_ratio`'s numerator is deliberately `analysis.address_demographics.
median_hh_income` -- the address's own 2020 census TRACT median, assigned by
a BBL lookup with no apportionment (a PLUTO lot sits in exactly one tract).
It is NOT `analysis.address_gaps.median_hh_income`, the hex-interpolated
column that migration 008 added to that table: that one is the H3 res-9
cell's value, doubly modelled (tract -> hex by PLUTO unit share, then hex ->
address by containment) and a step function across hex boundaries. Both are
legitimate for their own purposes; a demand caveat that names a household
income has to use the least-modelled one available.

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
import datetime

import pandas as pd

from loci.demand import (
    X6_DISCLAIMER,
    caveat_categories,
    load_demand,
    load_low_income_cutoff,
    ratio_moe,
)
from loci.model.conveniences import ALLCATS

#: The ACS vintage this annotation reads, matching model/address_demographics.py
#: and gaps.py's own pinned 2023. A single vintage, stated once: pooling two
#: vintages' medians into one ratio would silently mix denominators.
ACS_YEAR = 2023

#: Column list of analysis.address_demand, in DDL order. The drift test asserts
#: the table's column list matches this constant, so editing one without the
#: other fails loudly instead of writing a silently mis-shaped row.
ADDRESS_DEMAND_COLUMNS = [
    "address_id", "bbl", "borough", "category",
    "is_lead", "eligible", "ratio", "nearest_m",
    "demand_class", "elasticity",
    "income_ratio", "income_ratio_moe", "income_indeterminate",
    "demand_caveat", "demand_caveat_text",
    "acs_year", "reach_hash", "supply_hash", "run_at",
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
    """address_gaps' 15 wide `{cat}_nearest_m` / `{cat}_ratio` column pairs,
    unpivoted to one row per (address, category), keeping only rows that are
    missing (ratio > 1, the D41 continuous reading) or are the address's lead.

    Written as a generated UNION ALL rather than DuckDB's UNPIVOT so the
    category order is `loci.categories.CATEGORIES` order exactly, the same
    order address_gaps writes its column pairs in -- one list, one source of
    truth, no chance of a nearest_m landing beside the wrong category's ratio.
    """
    holes = ", ".join("?" for _ in boroughs)
    arms = "\n        UNION ALL\n".join(
        f"        SELECT address_id, bbl, borough, eligible, lead_category, "
        f"reach_hash, supply_hash, '{c}' AS category, "
        f"{c}_ratio AS ratio, {c}_nearest_m AS nearest_m FROM g"
        for c in ALLCATS
    )
    return f"""
        WITH g AS (
            SELECT * FROM analysis.address_gaps WHERE borough IN ({holes})
        ), longform AS (
{arms}
        )
        SELECT l.address_id, l.bbl, l.borough, l.category,
               -- IS NOT NULL guard, not just an equality: an INELIGIBLE
               -- address has lead_category NULL, and `x = NULL` is NULL, not
               -- FALSE -- a NULL here would land in a NOT NULL column.
               (l.lead_category IS NOT NULL AND l.category = l.lead_category) AS is_lead,
               l.eligible, l.ratio, l.nearest_m,
               l.reach_hash, l.supply_hash,
               d.median_hh_income, d.median_hh_income_moe
        FROM longform l
        LEFT JOIN analysis.address_demographics d
               ON d.address_id = l.address_id AND d.acs_year = ?
        WHERE l.ratio > 1.0 OR l.category = l.lead_category
    """


def compute_address_demand(
    con, boroughs: list[str],
    citywide: tuple[float | None, float | None] | None = None,
    cutoff: float | None = None,
    acs_year: int = ACS_YEAR,
) -> pd.DataFrame:
    """Build the annotation frame. READ-ONLY over analysis.address_gaps and
    analysis.address_demographics -- it issues no UPDATE, no DELETE and no
    INSERT against either.

    `citywide` and `cutoff` are injectable for tests; in production both come
    from the same places D49 fixed them: the ACS B19025/B11001 citywide mean
    and demand.yaml's `low_income_cutoff` (0.80).
    """
    cutoff = load_low_income_cutoff() if cutoff is None else cutoff
    citywide_mean, citywide_moe = citywide if citywide is not None else _citywide_income()
    demand = load_demand()
    eligible_for_caveat = caveat_categories()

    df = con.execute(_long_form_sql(boroughs), [*boroughs, acs_year]).fetchdf()
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
        "reach_hash": df["reach_hash"],
        "supply_hash": df["supply_hash"],
    })
    out["demand_caveat_text"] = [
        caveat_text(ic, c, demand) if caveated else None
        for ic, c, caveated in zip(ctxs, cats, out["demand_caveat"])
    ]
    out["run_at"] = datetime.datetime.now(datetime.timezone.utc)
    return out[ADDRESS_DEMAND_COLUMNS]


# ---------------------------------------------------------------- the write

def write_address_demand(con, df: pd.DataFrame) -> int:
    """Persist to analysis.address_demand, replacing every
    (borough, reach_hash, supply_hash) present in `df`.

    Delete-then-insert on the RUN KEY, not on the borough alone (which is what
    write_address_gaps does): re-running the same reach/supply configuration
    replaces its own rows, while a run under a different supply set lands
    beside the old one instead of silently erasing it -- the D51/D52 finding
    was that two defensible supply sets give two different cities, so both
    have to be comparable after the fact.
    """
    if df.empty:
        return 0
    keys = df[["borough", "reach_hash", "supply_hash"]].drop_duplicates()
    for b, rh, sh in keys.itertuples(index=False):
        con.execute(
            "DELETE FROM analysis.address_demand "
            "WHERE borough = ? AND reach_hash = ? AND supply_hash = ?", [b, rh, sh])
    con.register("_ad", df)
    try:
        cols = ", ".join(ADDRESS_DEMAND_COLUMNS)
        con.execute(f"INSERT INTO analysis.address_demand ({cols}) SELECT {cols} FROM _ad")
    finally:
        con.unregister("_ad")
    return len(df)


def build_address_demand(con, boroughs: list[str], **kwargs) -> tuple[int, pd.DataFrame]:
    """compute + write. Returns (rows written, the frame) so the CLI prints
    the same summary on the write path as under --dry-run."""
    df = compute_address_demand(con, boroughs, **kwargs)
    return write_address_demand(con, df), df


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
