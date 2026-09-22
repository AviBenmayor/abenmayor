"""Where riders GO: Citi Bike OD leakage on the card (Citi Bike phase 2, GTM-167).

    analysis.address.bike_od_top_nta          the single most common destination
    analysis.address.bike_od_top_nta_share    its share of the neighbourhood's flow
    analysis.address.bike_od_out_share        share that leaves the NTA entirely
    analysis.address.bike_od_outside_share    of that, the share the supply join
                                              could NOT look at
    analysis.address.bike_od_window / bike_od_supply_hash / bike_od_run_at
    analysis.address_category.bike_od_supplied_share

WHAT THIS ANSWERS, IN ONE SENTENCE
---------------------------------------------------------------------------
Phase 1 (`model/address_bike.py`) counts how many bikes START and END within a
five-minute walk. It cannot tell a neighbourhood whose riders stay from one
whose riders leave. This module reads `analysis.bike_od_leakage` -- the
origin->destination table phase 2 ingests -- restricted to EVENING AND WEEKEND
trips out of RESIDENTIAL docks, and asks: when the people who live here get on a
bike on a Thursday night or a Saturday, where do they end up, and does the place
they end up already have the category this address is missing?

A high `bike_od_supplied_share` for `grocery` at an address is evidence AGAINST
the gap: the demand is already being met somewhere else, on a bike, and a new
shop here would have to win it back.

NTA GRAIN, STAMPED ON EVERY ADDRESS (owner ruling R3, 2026-09-15)
---------------------------------------------------------------------------
There is no address-level OD. A dock serves a few hundred addresses and the
trip table knows nothing finer than the dock, so every one of these numbers is
NEIGHBOURHOOD-WIDE and identical for every address in the NTA. That is a
deliberate, stated flattening, not an accident of the join: the value is
stamped on each address so the card can render it without a second query, and
every renderer MUST say "neighbourhood-wide" beside it. `card_line()` and
`category_card_line()` below are the sanctioned wordings and they say so.

They also say RIDERS, never RESIDENTS (owner ruling, same date). Citi Bike mode
share is low single digits and skews young, male and higher-income. This is
where CYCLISTS go. It is not where the neighbourhood goes.

NULL, NEVER ZERO
---------------------------------------------------------------------------
An NTA with no residential-type dock, or fewer than `MIN_ORIGIN_TRIPS` non-round
evening/weekend trips in the window, gets NULL -- while still carrying
`bike_od_window` and `bike_od_run_at`, so "we measured and there is no dock" is
distinguishable from "never run". A 0.0 would assert that riders here go
nowhere, which is a claim about the operator's capital plan wearing the costume
of a claim about the street. Same convention as phase 1's two shares.

CONTEXT ONLY (D76)
---------------------------------------------------------------------------
Nothing built here enters `gap_score`, `supply_ratio_vs_base`, a recommendation
grade, or the revenue model's lambda (owner ruling R1, 2026-09-15: `model/
revenue.py` is untouched and is never imported from this module). Dock placement
is endogenous to retail and density -- the D1 error in a mobility costume -- and
this measure has to clear the placebo below before it is even allowed to be a
number on a card rather than a sentence in prose.

THE SUPPLY SIDE, AND THE ONE H3 RULE
---------------------------------------------------------------------------
"Category c is present above the median density" is POIs PER 1,000 RESIDENTIAL
UNITS in the destination NTA, from `analysis.poi_supply_status` with the D94 gate
(`poi_status <> 'closed'`; 'unknown' is NEVER gated, D79). POIs carry a point,
not an NTA, so they are mapped point -> h3 res-9 -> `analysis.hex.nta_code`
using the PYTHON h3 package, exactly as `model/address_gaps.py:530` maps
addresses. Not the DuckDB h3 extension: one rule for docks, addresses and POIs
is the only mitigation there is for boundary misassignment, and the phase-1 rule
is the python one. (The extension is loaded by `db.connect` and would give the
same cells; using it here would still be a SECOND definition.)

THE UNIVERSE, AND WHY THE DENOMINATOR IS CONDITIONAL
---------------------------------------------------------------------------
`analysis.hex` is citywide but `analysis.address` is MN+BK, so supply density is
only measurable in the NTAs that carry a real address frame -- 110 before the
phantom-NTA floor, fewer after (verified live 2026-09-15; the dock->NTA rule maps
all 2,611 docks onto 133 NTAs). An NTA under `MIN_UNIVERSE_ADDRESSES` lot-frame
addresses is treated as outside the universe however many POIs sit in it: BX0401
holds ONE address and 728 open POIs, and a density built on that denominator
clears every threshold by arithmetic accident.

An outbound trip landing
in Long Island City can be neither "supplied" nor "not supplied" -- it is
unmeasured. Counting it in the denominator would silently push every share DOWN
in proportion to how close the neighbourhood is to Queens, which is a geography
artefact, not a retail finding. So the denominator is outbound trips landing
INSIDE the measurable universe.

EVERY ORIGIN NTA STILL GETS A NUMBER (owner ruling D44, 2026-09-15, on the D75
no-eligibility-gate footing). An earlier draft NULLed any origin sending more
than 20% of its riders outside the universe; that dropped precisely the
neighbourhoods nearest the borough edge, which is a geography filter, not a
quality control. The conditionality is DISCLOSED rather than enforced:
`bike_od_outside_share` is stored on every address and BOTH card lines print it,
always, so a reader can see how much of the flow the number does not cover and
discount it themselves.

RE-APPLY AFTER EVERY SCREEN RE-RUN
---------------------------------------------------------------------------
`loci address-gaps` DELETEs and re-INSERTs the rows these columns live on, so
like every sibling annotation this one comes back NULL. `bike_od_run_at IS NULL`
is the flag; `--re-sweep` forces the rewrite. Unlike phase 1 there is no
persisted expensive object to recover -- no Dijkstra, no reachable set -- so the
recovery is seconds, and `--re-sweep` exists for parity and for forcing a
rewrite when the window has not moved.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from loci.categories import CATEGORIES

#: The ONLY columns this module may name in a SET clause on analysis.address.
BIKE_OD_ADDRESS_COLUMNS = [
    "bike_od_top_nta",
    "bike_od_top_nta_share",
    "bike_od_out_share",
    "bike_od_outside_share",
    "bike_od_window",
    "bike_od_supply_hash",
    "bike_od_run_at",
]

#: ... and on analysis.address_category.
BIKE_OD_CATEGORY_COLUMNS = ["bike_od_supplied_share"]

#: Res-9, the project's one hex resolution (analysis.hex holds nothing else).
H3_RES = 9

#: Twelve months, for phase 1's reason: Citi Bike's seasonality is far larger
#: than the subway's (August runs ~2.5x February) and a shorter window is a
#: summer reading of where people go.
DEFAULT_WINDOW_MONTHS = 12

#: Below this many non-round evening/weekend trips out of an NTA's residential
#: docks over the WHOLE window, write NULL. The same floor R2 puts on a station
#: -month, applied to the NTA-window cell; deliberately low, because the R2
#: classifier has already sent thin docks to origin_type='unknown'.
MIN_ORIGIN_TRIPS = 200

#: An NTA enters the measurable universe only with at least this many lot-frame
#: addresses. PHANTOM NTAs are the reason: BX0401 carries ONE address and 728
#: open POIs, so its "supply density" is an arithmetic accident that clears every
#: threshold and makes any destination there look maximally served. BX0401,
#: BX0802, BX0803, QN1003, QN0905, QN1002 and QN0502 all sat inside the universe
#: before this floor. Below it an NTA is treated as OUTSIDE the universe --
#: unmeasured, which is true, rather than "well supplied", which is an artefact.
MIN_UNIVERSE_ADDRESSES = 500

#: The leakage window, ONE definition, counted once: an evening arrival on a
#: Saturday is ONE arrival, which is why this is an OR and never a sum. Weekday
#: pm_peak is deliberately absent -- that is the commute home, not a choice
#: about where to spend an evening.
LEAKAGE_WINDOW_SQL = "(daypart = 'evening' OR day_type IN ('saturday', 'sunday'))"

#: Placebo bar (§Validation), REPLACED 2026-09-15 after the red-team pass. The
#: old bar was a mean off-diagonal rank correlation below 0.95, and it was not a
#: bar at all: the raw cross-category correlation of destination supply DENSITY
#: is already 0.76 mean / 0.94 max, so 0.95 passes anything that is not a
#: literal copy. The gate is now the NULL BASELINE in `placebo()` -- the share of
#: a neighbourhood's outbound trips landing in destinations that are above median
#: in ALL FIFTEEN categories. A category's `bike_od_supplied_share` has to beat
#: that by at least this much, or it is measuring "riders go to busy
#: neighbourhoods" and ships as prose. The off-diagonal matrix is still computed
#: and still reported -- as a description, no longer as a test.
NULL_BASELINE_MIN_EXCESS = 0.05

#: Graduation bar: destination-NTA inflow vs DOT PM pedestrian counts.
DOT_RHO_BAR = 0.5


# ----------------------------------------------------------------- the window

def window_bounds(con, months: int = DEFAULT_WINDOW_MONTHS) -> tuple[dt.date, dt.date]:
    """The latest `months` months present in analysis.bike_od_leakage, inclusive.

    Taken from the TABLE's own max month and never from today's date, for the
    reason `address_bike.window_bounds` gives: a month's file lands days into the
    next one, so anchoring on `today` silently shortens the window whenever the
    command is run early in a month.
    """
    row = con.execute(
        "SELECT min(month), max(month) FROM analysis.bike_od_leakage").fetchone()
    if not row or row[1] is None:
        raise RuntimeError(
            "analysis.bike_od_leakage is empty: run `loci citibike od-ingest` "
            "first. Refusing to stamp a leakage measure of NULL on every address "
            "from an empty table, which is indistinguishable from a city whose "
            "riders never leave their block.")
    last = row[1]
    y, m = last.year, last.month - (months - 1)
    while m <= 0:
        y, m = y - 1, m + 12
    return max(dt.date(y, m, 1), row[0]), last


def window_label(first: dt.date, last: dt.date) -> str:
    """`bike_od_window`, in phase 1's format so the two columns read alike."""
    return f"{first:%Y-%m}..{last:%Y-%m}"


# -------------------------------------------------------- point -> NTA (h3)

def hex_nta_lookup(con) -> dict[str, str]:
    """{h3_index: nta_code} from analysis.hex. Citywide; res-9 only."""
    return {
        h: nta
        for h, nta in con.execute(
            "SELECT h3_index, nta_code FROM analysis.hex "
            "WHERE nta_code IS NOT NULL AND resolution = ?", [H3_RES]).fetchall()
    }


def points_to_nta(lon, lat, lookup: dict[str, str]) -> np.ndarray:
    """Map (lon, lat) arrays onto NTA codes through h3 res-9. Unmapped -> None.

    The ONE rule (module docstring): python h3, `latlng_to_cell(lat, lon, 9)`,
    then a dict lookup against analysis.hex -- byte-identical to the address
    rule in model/address_gaps.py.
    """
    import h3

    lon = np.asarray(lon, dtype="float64")
    lat = np.asarray(lat, dtype="float64")
    out = np.empty(len(lon), dtype=object)
    for i, (x, y) in enumerate(zip(lon, lat)):
        if not np.isfinite(x) or not np.isfinite(y):
            out[i] = None
            continue
        out[i] = lookup.get(h3.latlng_to_cell(float(y), float(x), H3_RES))
    return out


def dock_nta_map(con) -> pd.DataFrame:
    """(station_id, nta_code) for every dock with a coordinate.

    The ingest stores origin_nta/destination_nta already, so nothing in the
    measures path needs this -- it exists so the validation functions and any
    later audit resolve a dock to a neighbourhood through the SAME rule the
    ingest used, rather than inventing a second one.
    """
    df = con.execute(
        "SELECT station_id, lon, lat FROM staging.citibike_station "
        "WHERE lon IS NOT NULL AND lat IS NOT NULL").fetchdf()
    df["nta_code"] = points_to_nta(df["lon"], df["lat"], hex_nta_lookup(con))
    return df[["station_id", "nta_code"]]


# ----------------------------------------------------------------- the supply

def supply_density(con, lot_frame_only: bool = True,
                   min_addresses: int = MIN_UNIVERSE_ADDRESSES) -> pd.DataFrame:
    """(nta_code, category, n_pois, n_addresses, n_units, poi_per_1k_units) per
    NTA x category, over the measurable universe.

    PER 1,000 RESIDENTIAL UNITS, NOT PER ADDRESS (red-team fix, 2026-09-15).
    POIs per ADDRESS is a Manhattan indicator: an address ROW is a tax lot, and a
    Manhattan lot holds forty households where a Brooklyn lot holds two. Under
    that denominator 27 of 110 NTAs came out above median in ALL FIFTEEN
    categories and 36 in none -- 86.6% of category pairs gave an identical
    above/below verdict, and the origin-side mean ran 0.90 in Manhattan against
    0.13 in Brooklyn. That is a borough dummy, not a retail measure. `units`
    (PLUTO residential units, the same column `homes_400m` and `supply_per_1k`
    are built from) is the denominator the rest of the project already uses, so
    this is also one definition rather than a second.

    Only NTAs with at least `min_addresses` lot-frame addresses AND a positive
    unit count are in the universe -- see `MIN_UNIVERSE_ADDRESSES` for the
    phantom-NTA reason. Categories absent from a universe NTA appear with
    n_pois = 0, so the share below says "not supplied" about a real absence
    rather than dropping the destination.

    `lot_frame_only` (default True) keeps D84's STREET rows out of the
    denominator: a second frame over the same kerb, added at a different time in
    different neighbourhoods, would move the threshold whenever it is re-run.
    """
    where = "WHERE COALESCE(frame, 'lot') = 'lot'" if lot_frame_only else ""
    addrs = con.execute(
        f"SELECT nta_code, count(*) AS n_addresses, "
        f"       sum(COALESCE(units, 0))::DOUBLE AS n_units "
        f"FROM analysis.address {where} GROUP BY 1 "
        f"HAVING nta_code IS NOT NULL AND count(*) >= ? "
        f"   AND sum(COALESCE(units, 0)) > 0", [int(min_addresses)]).fetchdf()
    if addrs.empty:
        raise RuntimeError(
            f"no NTA in analysis.address clears {min_addresses} lot-frame "
            f"addresses with a positive unit count; run `loci address-gaps` "
            f"first. Without a denominator every destination would read "
            f"'not supplied', which is the silent zero this project refuses.")

    pois = con.execute(
        "SELECT category, ST_X(geom) AS lon, ST_Y(geom) AS lat "
        "FROM analysis.poi_supply_status "
        "WHERE geom IS NOT NULL AND COALESCE(poi_status, 'unknown') <> 'closed'"
    ).fetchdf()
    pois["nta_code"] = points_to_nta(pois["lon"], pois["lat"], hex_nta_lookup(con))
    counts = (pois.dropna(subset=["nta_code"])
                  .groupby(["nta_code", "category"], as_index=False)
                  .size().rename(columns={"size": "n_pois"}))

    cats = pd.DataFrame({"category": sorted(CATEGORIES)})
    grid = addrs.merge(cats, how="cross")
    out = grid.merge(counts, on=["nta_code", "category"], how="left")
    out["n_pois"] = out["n_pois"].fillna(0).astype("int64")
    out["poi_per_1k_units"] = out["n_pois"] / (out["n_units"] / 1000.0)
    return out[["nta_code", "category", "n_pois", "n_addresses", "n_units",
                "poi_per_1k_units"]]


def supply_thresholds(density: pd.DataFrame) -> pd.DataFrame:
    """(category, threshold) -- the median POIs per 1,000 residential units among
    the universe NTAs where the category is PRESENT.

    Present-only on purpose, and it is the load-bearing choice in this measure.
    Zero-filling the absent NTAs into the median drags most thresholds to 0 (a
    category missing from half the city has a median of zero), after which every
    destination with a single shop counts as 'supplied' and the share is ~1
    everywhere -- a measure that cannot distinguish anything. The cost of the
    present-only median is the opposite bias: the bar is the typical neighbourhood
    that HAS the category, so 'supplied' means 'as well served as a median
    serving neighbourhood', which is the comparison the card is making anyway.
    """
    present = density[density["n_pois"] > 0]
    thr = (present.groupby("category", as_index=False)["poi_per_1k_units"]
                  .median().rename(columns={"poi_per_1k_units": "threshold"}))
    missing = sorted(set(density["category"]) - set(thr["category"]))
    if missing:
        # A category with no open POI anywhere in the universe has no median.
        # Threshold 0 would call every destination supplied; NaN makes the
        # share NULL, which is the truth: unmeasurable.
        thr = pd.concat([thr, pd.DataFrame(
            {"category": missing, "threshold": [np.nan] * len(missing)})],
            ignore_index=True)
    return thr.sort_values("category", ignore_index=True)


# ------------------------------------------------------------------ the flow

def flow(con, first: dt.date, last: dt.date) -> pd.DataFrame:
    """(origin_nta, destination_nta, trips) over the leakage window.

    NON-ROUND trips only (`trips - round_trips`): a trip that ends at the dock it
    started from has no destination to leak to, and folding 2.58% of the flow
    into the origin NTA would inflate every 'stays here' reading. Round trips are
    a separate stored column precisely so this subtraction is visible.
    """
    df = con.execute(f"""
        SELECT origin_nta, destination_nta,
               sum(trips) - sum(round_trips) AS trips
        FROM analysis.bike_od_leakage
        WHERE origin_type = 'residential'
          AND {LEAKAGE_WINDOW_SQL}
          AND month BETWEEN ? AND ?
          AND origin_nta IS NOT NULL AND destination_nta IS NOT NULL
        GROUP BY 1, 2
        HAVING sum(trips) - sum(round_trips) > 0
    """, [first, last]).fetchdf()
    df["trips"] = df["trips"].astype("float64")
    return df


#: One row per origin NTA. `bike_od_top_nta_share` is over ALL destinations
#: including the origin itself -- the same SHAPE as `share` in the view
#: `analysis.bike_od_leakage_evening` (sql/037), with one deliberate difference:
#: the view partitions by (origin_nta, month) because it is a per-month view,
#: and the card pools the whole window, so this partitions by origin_nta alone.
#: A card number that moved every month would not be a neighbourhood's habit.
#: The top destination is frequently the origin NTA, and that IS the answer
#: ("they stay"); `card_line` words that case differently rather than hiding it.
NTA_MEASURES_SQL = f"""
WITH f AS (
    SELECT origin_nta, destination_nta, sum(trips) - sum(round_trips) AS trips
    FROM analysis.bike_od_leakage
    WHERE origin_type = 'residential'
      AND {LEAKAGE_WINDOW_SQL}
      AND month BETWEEN ? AND ?
      AND origin_nta IS NOT NULL AND destination_nta IS NOT NULL
    GROUP BY 1, 2
    HAVING sum(trips) - sum(round_trips) > 0
), tot AS (
    SELECT origin_nta,
           sum(trips)                                            AS trips_total,
           COALESCE(sum(trips) FILTER (destination_nta <> origin_nta), 0)
                                                                 AS trips_out
    FROM f GROUP BY 1
), ranked AS (
    SELECT origin_nta, destination_nta, trips,
           row_number() OVER (PARTITION BY origin_nta
                              ORDER BY trips DESC, destination_nta) AS rn
    FROM f
)
SELECT t.origin_nta                              AS nta_code,
       r.destination_nta                         AS bike_od_top_nta,
       r.trips / nullif(t.trips_total, 0)        AS bike_od_top_nta_share,
       t.trips_out / nullif(t.trips_total, 0)    AS bike_od_out_share,
       t.trips_total, t.trips_out
FROM tot t JOIN ranked r ON r.origin_nta = t.origin_nta AND r.rn = 1
WHERE t.trips_total >= ?
ORDER BY 1
"""


def nta_measures(con, first: dt.date, last: dt.date,
                 min_trips: int = MIN_ORIGIN_TRIPS) -> pd.DataFrame:
    """(nta_code, the three address-grain measures, trips_total, trips_out).

    An NTA below `min_trips` is simply absent from the frame, which is how it
    ends up NULL on the address: the writer stamps the window on every in-scope
    address and the values only where this frame has a row.
    """
    return con.execute(NTA_MEASURES_SQL, [first, last, int(min_trips)]).fetchdf()


def nta_labels(con=None, graph_path=None) -> dict[str, str]:
    """{nta_code: neighbourhood name}, CITYWIDE.

    `data/interim/nta_names.json` -- the same file `model/address_gaps.py:532`
    reads to fill `analysis.address.neighborhood`, so the card and the screen
    name a neighbourhood identically. It has to be the file and not the address
    column: `analysis.address` is MN+BK, and the destination of an evening ride
    out of Greenpoint is frequently in Queens. A raw `QN0201` on a card is not an
    answer to "where do riders go".

    Falls back to the warehouse's own labels, then to the bare code -- a missing
    names file degrades the wording, it must never fail the build.
    """
    import json
    import pathlib

    labels: dict[str, str] = {}
    try:
        from loci.score.walkgraph import OUT as _GRAPH

        base = pathlib.Path(graph_path or _GRAPH).resolve().parents[1]
        p = base / "interim" / "nta_names.json"
        if p.exists():
            labels = {str(k): str(v) for k, v in json.loads(p.read_text()).items()}
    except Exception:                                # noqa: BLE001 - cosmetic only
        labels = {}
    if con is not None:
        try:
            for code, name in con.execute(
                "SELECT DISTINCT nta_code, neighborhood FROM analysis.address "
                "WHERE nta_code IS NOT NULL AND neighborhood IS NOT NULL"
            ).fetchall():
                labels.setdefault(str(code), str(name))
        except Exception:                            # noqa: BLE001 - cosmetic only
            labels = dict(labels)   # the warehouse has no labels; the file's stand
    return labels


#: Per (origin NTA, month), the share of that month's non-round evening/weekend
#: flow that went to the origin's POOLED top destination. The pooled window is
#: SUMMER-WEIGHTED -- August runs ~2.5x February -- so a single top-share number
#: is mostly a reading of where people ride in warm weather. The IQR across the
#: window's months is the honest width of that number and goes in the REPORT, not
#: into a column: it is a property of the window, not of the address.
TOP_SHARE_BY_MONTH_SQL = f"""
WITH f AS (
    SELECT origin_nta, destination_nta, month,
           sum(trips) - sum(round_trips) AS trips
    FROM analysis.bike_od_leakage
    WHERE origin_type = 'residential'
      AND {LEAKAGE_WINDOW_SQL}
      AND month BETWEEN ? AND ?
      AND origin_nta IS NOT NULL AND destination_nta IS NOT NULL
    GROUP BY 1, 2, 3
)
SELECT f.origin_nta AS nta_code, f.month,
       sum(f.trips) FILTER (f.destination_nta = t.bike_od_top_nta)
           / nullif(sum(f.trips), 0) AS top_share
FROM f JOIN _od_top t ON t.nta_code = f.origin_nta
GROUP BY 1, 2
HAVING sum(f.trips) > 0
"""


def top_share_monthly_iqr(con, first: dt.date, last: dt.date,
                          nta: pd.DataFrame) -> dict:
    """How much the pooled top-share moves month to month. REPORT ONLY."""
    if nta.empty:
        return {"months": 0, "median_iqr": float("nan")}
    con.register("_od_top", nta[["nta_code", "bike_od_top_nta"]])
    try:
        m = con.execute(TOP_SHARE_BY_MONTH_SQL, [first, last]).fetchdf()
    finally:
        con.unregister("_od_top")
    if m.empty:
        return {"months": 0, "median_iqr": float("nan")}
    q = m.groupby("nta_code")["top_share"].agg(
        lambda s: float(s.quantile(0.75) - s.quantile(0.25)))
    return {
        "months": int(m["month"].nunique()),
        "median_iqr": float(q.median()),
        "p90_iqr": float(q.quantile(0.9)),
        "max_iqr": float(q.max()),
    }


def supplied_share(flow_df: pd.DataFrame, density: pd.DataFrame,
                   thresholds: pd.DataFrame,
                   min_trips: int = MIN_ORIGIN_TRIPS,
                   ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """((nta_code, category, bike_od_supplied_share), per-origin frame, report).

    Share of OUT-OF-NTA, non-round, evening/weekend trips out of the origin's
    residential docks that land in a destination NTA where the category sits
    above `thresholds`. Computed once per (origin NTA, category) and stamped on
    every address in the NTA (R3).

    EVERY ORIGIN NTA IS REPORTED (owner ruling D44, 2026-09-15, on the D75
    no-eligibility-gate footing). There is no cut on how much of a neighbourhood's
    outbound flow left the measurable universe. An earlier draft NULLed an origin
    above 20% outside; that was an eligibility gate wearing a quality label, and
    it removed exactly the neighbourhoods nearest the borough edge -- a geography
    filter, which is the thing D75 forbids. The conditionality is DISCLOSED
    instead: `bike_od_outside_share` is stored per origin and BOTH card lines
    print it, always.

    TWO WAYS TO BE NULL, neither of them an eligibility gate, neither of them zero:
      * the category has no threshold (nowhere open in the universe) -- nothing to
        compare against;
      * the origin's INSIDE-UNIVERSE outbound total is below `min_trips` -- no
        denominator. This is not a quality cut on a measurable neighbourhood: it
        is the absence of one. It has to be applied HERE as well as in
        `nta_measures`, whose floor is on the origin's TOTAL flow (staying trips
        included), so an NTA whose riders almost all stay could clear that with 20
        outbound trips and publish a share read off twenty rides.

    The denominator is outbound trips landing INSIDE the measurable universe --
    see the module docstring for why, and the per-origin frame (returned second,
    and stored as `bike_od_outside_share`) for how much it excludes.
    """
    universe = set(density["nta_code"])
    out = flow_df[flow_df["destination_nta"] != flow_df["origin_nta"]]
    inside = out[out["destination_nta"].isin(universe)]

    by_origin = out.groupby("origin_nta")["trips"].sum()
    by_origin_inside = inside.groupby("origin_nta")["trips"].sum().reindex(
        by_origin.index).fillna(0.0)
    outside = pd.DataFrame({
        "nta_code": by_origin.index,
        "trips_outbound": by_origin.to_numpy(dtype="float64"),
        "trips_outbound_inside": by_origin_inside.to_numpy(dtype="float64"),
    })
    outside["bike_od_outside_share"] = (
        1.0 - outside["trips_outbound_inside"]
        / outside["trips_outbound"].replace(0, np.nan))
    too_thin = set(outside.loc[outside["trips_outbound_inside"] < float(min_trips),
                               "nta_code"])

    d = density.merge(thresholds, on="category", how="left")
    m = inside.merge(d, left_on="destination_nta", right_on="nta_code", how="inner")
    if m.empty:
        return (pd.DataFrame(columns=["nta_code", "category",
                                      "bike_od_supplied_share"]),
                outside,
                {"origins": 0, "rows": 0, "origins_dropped_thin_outbound": 0,
                 "min_outbound_trips": int(min_trips)})
    m["supplied_trips"] = np.where(
        m["poi_per_1k_units"] > m["threshold"], m["trips"], 0.0)
    g = (m.groupby(["origin_nta", "category"], as_index=False)
          .agg(supplied=("supplied_trips", "sum"), total=("trips", "sum"),
               threshold=("threshold", "first")))
    g["bike_od_supplied_share"] = g["supplied"] / g["total"].replace(0, np.nan)
    # A category with no median (nowhere open in the universe) is unmeasurable,
    # not "nothing is supplied": NaN, never 0.
    g.loc[g["threshold"].isna(), "bike_od_supplied_share"] = np.nan
    g.loc[g["origin_nta"].isin(too_thin), "bike_od_supplied_share"] = np.nan
    g = g.rename(columns={"origin_nta": "nta_code"})
    rep = {
        "origins": int(g["nta_code"].nunique()),
        "rows": len(g),
        "origins_dropped_thin_outbound": len(too_thin),
        "min_outbound_trips": int(min_trips),
        "outbound_outside_universe_share": float(
            1.0 - inside["trips"].sum() / max(out["trips"].sum(), 1.0)),
        # The DISTRIBUTION, not a count of exclusions: nothing is excluded for
        # being far from the universe any more (D44), so what a reader needs is
        # how conditional the typical and the worst-case number is.
        "outside_share_p50": float(
            outside["bike_od_outside_share"].median(skipna=True)),
        "outside_share_p90": float(
            outside["bike_od_outside_share"].quantile(0.9)),
        "outside_share_max": float(
            outside["bike_od_outside_share"].max()),
        "median_supplied_share": float(
            g["bike_od_supplied_share"].median(skipna=True))
        if len(g) else float("nan"),
    }
    return g[["nta_code", "category", "bike_od_supplied_share"]], outside, rep


def check_shares_in_bounds(df: pd.DataFrame, cols: list[str]) -> dict:
    """Every column here is a share. Outside [0, 1] means the numerator is not a
    subset of the denominator -- the leakage window counted twice, or round trips
    subtracted from one side only. RAISES, because 1.3 reads as a plausible
    'very leaky' number to every downstream reader."""
    rep = {}
    for col in cols:
        v = (pd.to_numeric(df[col], errors="coerce").dropna()
             if col in df else pd.Series(dtype="float64"))
        lo, hi = (float(v.min()), float(v.max())) if len(v) else (float("nan"),) * 2
        rep[col] = {"n": len(v), "min": lo, "max": hi,
                    "median": float(v.median()) if len(v) else float("nan")}
        if len(v) and (lo < -1e-12 or hi > 1 + 1e-12):
            raise RuntimeError(
                f"{col} ranges [{lo}, {hi}] -- outside [0, 1]. Either the "
                f"evening/weekend window was counted twice (it is an OR, and a "
                f"Saturday evening trip is ONE trip), or round_trips was "
                f"subtracted from the numerator but not the denominator.")
    return rep


# ----------------------------------------------------------------- the write

def _guard(address_cols: list[str], category_cols: list[str]) -> None:
    """Refuse to write if either SET list touches a column another module owns."""
    from loci.model.address_access import ACCESS_COLUMNS
    from loci.model.address_access import _guard as access_guard
    from loci.model.address_bike import BIKE_ADDRESS_COLUMNS
    from loci.model.address_transit_profile import PROFILE_ADDRESS_COLUMNS

    access_guard(address_cols)                     # every sibling annotation
    overlap = sorted(set(address_cols) & (set(ACCESS_COLUMNS)
                                          | set(BIKE_ADDRESS_COLUMNS)
                                          | set(PROFILE_ADDRESS_COLUMNS)))
    if overlap:
        raise RuntimeError(
            f"citibike od-measures would clobber analysis.address columns owned "
            f"elsewhere: {overlap}")
    from loci.model.supply_ratio import CATEGORY_RATIO_COLUMNS

    cat_overlap = sorted(set(category_cols) & set(CATEGORY_RATIO_COLUMNS))
    if cat_overlap:
        raise RuntimeError(
            f"citibike od-measures would clobber analysis.address_category "
            f"columns owned elsewhere: {cat_overlap}")


def write_measures(con, nta: pd.DataFrame, cat: pd.DataFrame,
                   outside: pd.DataFrame,
                   boroughs: list[str] | None, meta: dict) -> dict:
    """UPDATE-only, RESET-then-UPDATE, scoped by borough. Never an INSERT.

    Four statements on analysis.address:
      1. reset every column in scope (an NTA that drops below the trip floor must
         not keep last run's destination);
      2. stamp `bike_od_window`, `bike_od_supply_hash` and `bike_od_run_at` on
         EVERY in-scope address -- "measured, and there is no residential dock
         here" is a result;
      3. set the three values from the NTA frame, joined on nta_code;
      4. set `bike_od_outside_share` from the per-origin frame -- the share of
         this neighbourhood's outbound riders the measure could NOT look at,
         stored rather than reported, because a card that quotes a conditional
         share has to be able to say what it is conditional on.
    Then the same reset-and-set on analysis.address_category, gated to the rows
    where the category is MISSING (`ratio > 1`, D39) -- the only rows the measure
    is about.
    """
    _guard(BIKE_OD_ADDRESS_COLUMNS, BIKE_OD_CATEGORY_COLUMNS)
    run_at = meta["run_at"]

    def _scope(alias: str = "") -> str:
        if not boroughs:
            return ""
        return (f" AND {alias}borough IN "
                f"({', '.join('?' for _ in boroughs)})")

    scope = _scope()
    params = list(boroughs) if boroughs else []

    con.register("_od_nta", nta[["nta_code", "bike_od_top_nta",
                                 "bike_od_top_nta_share", "bike_od_out_share"]])
    con.register("_od_cat", cat[["nta_code", "category",
                                 "bike_od_supplied_share"]])
    con.register("_od_out", outside[["nta_code", "bike_od_outside_share"]])
    try:
        reset = ", ".join(f"{c} = NULL" for c in BIKE_OD_ADDRESS_COLUMNS)
        con.execute(f"UPDATE analysis.address SET {reset} WHERE TRUE{scope}", params)
        con.execute(
            f"UPDATE analysis.address SET bike_od_window = ?, "
            f"    bike_od_supply_hash = ?, bike_od_run_at = ? "
            f"WHERE TRUE{scope}",
            [meta["window"], meta["supply_hash"], run_at, *params])
        con.execute(
            f"UPDATE analysis.address AS a SET "
            f"    bike_od_top_nta = n.bike_od_top_nta, "
            f"    bike_od_top_nta_share = n.bike_od_top_nta_share, "
            f"    bike_od_out_share = n.bike_od_out_share "
            f"FROM _od_nta n WHERE a.nta_code = n.nta_code{scope}", params)
        con.execute(
            f"UPDATE analysis.address AS a "
            f"SET bike_od_outside_share = o.bike_od_outside_share "
            f"FROM _od_out o WHERE a.nta_code = o.nta_code{scope}", params)

        con.execute(
            f"UPDATE analysis.address_category SET bike_od_supplied_share = NULL "
            f"WHERE TRUE{scope}", params)
        con.execute(
            f"UPDATE analysis.address_category AS g "
            f"SET bike_od_supplied_share = c.bike_od_supplied_share "
            f"FROM _od_cat c, analysis.address a "
            f"WHERE a.address_id = g.address_id AND a.nta_code = c.nta_code "
            f"  AND g.category = c.category AND g.ratio > 1{_scope('g.')}",
            params)
    finally:
        for v in ("_od_nta", "_od_cat", "_od_out"):
            con.unregister(v)

    stamped, valued = con.execute(
        f"SELECT count(bike_od_run_at), count(bike_od_out_share) "
        f"FROM analysis.address WHERE TRUE{scope}", params).fetchone()
    cat_rows = con.execute(
        f"SELECT count(bike_od_supplied_share) FROM analysis.address_category "
        f"WHERE TRUE{scope}", params).fetchone()[0]
    return {
        "addresses_stamped": int(stamped),
        "addresses_with_a_destination": int(valued),
        "addresses_null_no_residential_dock": int(stamped) - int(valued),
        "address_category_rows": int(cat_rows),
        "ntas_measured": len(nta),
    }


def live_supply_hash(con) -> str:
    """The identity of the POI set this run counted, through `model/forecast.py`'s
    one reader so nothing here can compute a second answer. Returns the literal
    `'unmeasured'` -- never a 12-hex hash -- on a fixture with no supply-set
    tables, exactly as `forecast.live_supply_hash` does."""
    from loci.model.forecast import live_supply_hash as _h

    return _h(con)


def needs_rebuild(con, boroughs: list[str] | None, window: str,
                  supply_hash: str, cat: pd.DataFrame | None = None) -> bool:
    """True when the stored measure no longer describes the current warehouse.

    THREE triggers, because the window string alone catches only one of them:

    1. `loci address-gaps` DELETEs and re-INSERTs the address rows, so every
       column comes back NULL -- caught by the window stamp.
    2. A POI CLOSURE SWEEP changes `supply_density` under an unchanged window.
       `bike_od_supplied_share` would then be a statement about a supply set that
       no longer exists, and nothing about the window would say so. Keyed on
       `score.supply.supply_hash` (via `model/forecast.live_supply_hash`), which
       is the project's existing answer to exactly this question -- the same hash
       `analysis.forecast_run` stamps.
    3. An `analysis.address_category` rebuild wipes `bike_od_supplied_share`
       while leaving `analysis.address` fully stamped, so an address-only
       detector reports "nothing to do" and the category column stays NULL
       FOREVER. Checked by asking the frame we just computed: wherever this run
       has a non-NULL value for an (NTA, category) pair, every in-scope
       `ratio > 1` row in that pair must already be non-NULL.
    """
    scope = (f" AND borough IN ({', '.join('?' for _ in boroughs)})"
             if boroughs else "")
    params = list(boroughs or [])
    n = con.execute(
        f"SELECT count(*) FROM analysis.address "
        f"WHERE (bike_od_window IS DISTINCT FROM ? "
        f"       OR bike_od_supply_hash IS DISTINCT FROM ?){scope}",
        [window, supply_hash, *params]).fetchone()[0]
    if n:
        return True
    if cat is None or cat.empty:
        return False
    # No con.register here: this runs on read-only connections too, and 1,650
    # rows of (nta, category) is a pandas merge, not a join worth a temp view.
    live = con.execute(
        f"SELECT a.nta_code, g.category, "
        f"       count(*) FILTER (g.bike_od_supplied_share IS NULL) AS n_null "
        f"FROM analysis.address_category g "
        f"JOIN analysis.address a USING (address_id) "
        f"WHERE g.ratio > 1{scope.replace(' AND borough', ' AND g.borough')} "
        f"GROUP BY 1, 2", params).fetchdf()
    if live.empty:
        return False
    want = cat[cat["bike_od_supplied_share"].notna()]
    merged = want.merge(live, on=["nta_code", "category"], how="inner")
    return bool((merged["n_null"] > 0).any())


# ---------------------------------------------------------------- the build

def build_bike_od(con, boroughs: list[str] | None = None,
                  window_months: int = DEFAULT_WINDOW_MONTHS,
                  min_trips: int = MIN_ORIGIN_TRIPS,
                  re_sweep: bool = False,
                  dry_run: bool = False,
                  ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(NTA frame, NTA x category frame, report). Reads only; writes under
    `not dry_run`."""
    first, last = window_bounds(con, window_months)
    window = window_label(first, last)

    nta = nta_measures(con, first, last, min_trips=min_trips)
    flow_df = flow(con, first, last)
    density = supply_density(con)
    thresholds = supply_thresholds(density)
    cat, outside, crep = supplied_share(flow_df, density, thresholds,
                                        min_trips=min_trips)

    bounds = {
        **check_shares_in_bounds(nta, ["bike_od_top_nta_share",
                                       "bike_od_out_share"]),
        **check_shares_in_bounds(outside, ["bike_od_outside_share"]),
        **check_shares_in_bounds(cat, ["bike_od_supplied_share"]),
    }
    supply_hash = live_supply_hash(con)
    run_at = dt.datetime.now()
    report = {
        "window": window,
        "supply_hash": supply_hash,
        "min_origin_trips": int(min_trips),
        "boroughs": list(boroughs) if boroughs else "ALL",
        "origin_ntas": len(nta),
        "destination_pairs": len(flow_df),
        "universe_ntas": int(density["nta_code"].nunique()),
        "universe_min_addresses": MIN_UNIVERSE_ADDRESSES,
        "median_out_share": float(nta["bike_od_out_share"].median())
        if len(nta) else float("nan"),
        "median_outside_share": float(
            outside["bike_od_outside_share"].median(skipna=True))
        if len(outside) else float("nan"),
        "p90_outside_share": float(
            outside["bike_od_outside_share"].quantile(0.9))
        if len(outside) else float("nan"),
        # The pooled window is summer-weighted (August ~2.5x February), so the
        # top-share on a card is mostly a warm-weather reading. Report only.
        "top_share_monthly_iqr": top_share_monthly_iqr(con, first, last, nta),
        "supplied": crep,
        "share_bounds": bounds,
        "run_at": run_at.isoformat(timespec="seconds"),
        "rebuild_needed": needs_rebuild(con, boroughs, window, supply_hash, cat),
        "re_sweep": bool(re_sweep),
    }
    if not dry_run:
        if not re_sweep and not report["rebuild_needed"]:
            report["_written"] = {"skipped": "every in-scope address already "
                                             "carries this window and supply "
                                             "hash, and every category row is "
                                             "filled; --re-sweep to rewrite anyway"}
        else:
            report["_written"] = write_measures(
                con, nta, cat, outside, boroughs,
                {"run_at": run_at, "window": window, "supply_hash": supply_hash})
    return nta, cat, report


# ------------------------------------------------------------- the card line

#: The sanctioned wording. RIDERS, never residents; NEIGHBOURHOOD-WIDE, always
#: stated; and the D76 footing named, so nobody reads it as part of the grade.
CARD_PREAMBLE = ("Neighbourhood-wide, not this address. Citi Bike riders are "
                 "not residents — context only, never part of the grade.")


def _isnull(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v))


def _outside_clause(outside_share: float | None) -> str:
    """The disclosure both card lines carry, ALWAYS (owner ruling D44). No origin
    is dropped for sending its riders somewhere we cannot measure, so every card
    has to say how much of the flow that was."""
    if _isnull(outside_share):
        return ("How much of that flow left the neighbourhoods we can measure is "
                "not recorded for this run.")
    return (f"{outside_share:.0%} of the riders who left went to a neighbourhood "
            f"outside Manhattan and Brooklyn, or to one too small to measure "
            f"supply in, and are not in the supply reading below.")


def card_line(nta_code: str, top_nta: str | None, top_share: float | None,
              out_share: float | None, window: str | None = None,
              outside_share: float | None = None,
              labels: dict[str, str] | None = None) -> str:
    """One sentence for the address card, plus the standing caveat.

    THE DENOMINATOR IS NAMED, because there are two of them and they are not the
    same (red-team fix). `top_share` and `out_share` are over ALL of the
    neighbourhood's non-round evening/weekend trips, trips that stay included.
    `bike_od_supplied_share` (below) is over the OUT-of-NTA subset that lands
    somewhere supply is measurable. Quoting both without saying so invites a
    reader to subtract one from the other.

    Returns a STATED ABSENCE rather than nothing when the measure is NULL: "no
    residential dock here" is a fact about the operator's network and the card
    says so, the same way a phase-1 zero does. `labels` should be
    `nta_labels(con)` -- a raw `QN0201` on a card is not an answer to "where do
    riders go", and Queens and Bronx destinations are common.
    """
    labels = labels or {}
    here = labels.get(nta_code, nta_code)
    win = f" ({window})" if window else ""
    if _isnull(top_nta) or _isnull(top_share) or _isnull(out_share):
        return (f"No residential Citi Bike dock in {here} with enough "
                f"evening and weekend trips to read{win}, so where its riders go "
                f"is not measured. That is a fact about the dock network, not "
                f"about this street. {CARD_PREAMBLE}")
    there = labels.get(top_nta, top_nta)
    if top_nta == nta_code:
        where = (f"most evening and weekend Citi Bike trips out of {here}'s "
                 f"residential docks stay in {here} ({top_share:.0%})")
    else:
        where = (f"the commonest destination of evening and weekend Citi Bike "
                 f"trips out of {here}'s residential docks is {there} "
                 f"({top_share:.0%} of them)")
    return (f"Where riders go{win}: {where}, and {out_share:.0%} leave "
            f"{here} altogether — both out of every non-round evening and "
            f"weekend trip from those docks, trips that stay included. "
            f"{_outside_clause(outside_share)} {CARD_PREAMBLE}")


def category_card_line(nta_code: str, category: str,
                       supplied: float | None,
                       outside_share: float | None = None,
                       labels: dict[str, str] | None = None) -> str:
    """The category half: is the missing category already being reached by bike?

    The denominator is stated in the sentence (red-team fix): outbound trips
    landing in a Manhattan or Brooklyn neighbourhood whose supply can be
    measured. `outside_share` -- `bike_od_outside_share` on the address -- is the
    rest, and under owner ruling D44 it is ALWAYS quoted, never used to suppress
    the row: a conditional share that does not name its condition reads as an
    unconditional one, and a neighbourhood dropped for being near the borough
    edge is an eligibility gate (D75).
    """
    labels = labels or {}
    here = labels.get(nta_code, nta_code)
    name = (CATEGORIES[category].label.lower() if category in CATEGORIES
            else category)
    if _isnull(supplied):
        return (f"Whether {here}'s riders already reach a {name} elsewhere is "
                f"not measured here. {_outside_clause(outside_share)} "
                f"{CARD_PREAMBLE}")
    elsewhere = ("" if _isnull(outside_share)
                 else f" ({outside_share:.0%} went elsewhere)")
    return (f"{supplied:.0%} of the evening and weekend Citi Bike trips that "
            f"leave {here} for a Manhattan or Brooklyn neighbourhood we can "
            f"measure{elsewhere} end somewhere already better supplied with "
            f"{name}, per 1,000 homes, than the median neighbourhood that has "
            f"one — demand this address would have to win back. {CARD_PREAMBLE}")


# ------------------------------------------------------------ the read-back

VALIDATION_SQL = """
-- Proves on the WAREHOUSE, not on the frames this run built:
--   1. every in-scope address carries a window and a run_at, so the
--      no-eligibility-gate rule is visible rather than asserted;
--   2. an address with no reading has NULL, never 0 (impossible_zero = 0);
--   3. both address-grain shares lie in [0, 1];
--   4. the values are IDENTICAL for every address in an NTA (R3) --
--      distinct_values_per_nta must be 1 everywhere.
SELECT a.borough,
       count(*)                                           AS addresses,
       count(a.bike_od_run_at)                            AS stamped,
       count(a.bike_od_out_share)                         AS with_a_reading,
       round(median(a.bike_od_outside_share), 4)          AS p50_outside_share,
       count(*) FILTER (WHERE a.bike_od_out_share = 0
                          AND a.bike_od_top_nta IS NULL)  AS impossible_zero,
       round(median(a.bike_od_out_share), 4)              AS p50_out_share,
       min(a.bike_od_out_share)                           AS min_out_share,
       max(a.bike_od_out_share)                           AS max_out_share,
       max(a.bike_od_top_nta_share)                       AS max_top_share,
       (SELECT max(n) FROM (SELECT count(DISTINCT bike_od_out_share) AS n
                            FROM analysis.address GROUP BY nta_code))
                                                          AS distinct_values_per_nta
FROM analysis.address a
GROUP BY ROLLUP(a.borough)
ORDER BY a.borough NULLS LAST
"""


# ------------------------------------------------------------- §Validation
# Both of these run AFTER the real ingest, against the real table. They are
# here, not in a notebook, because the bars they check are the conditions on
# which this measure is allowed to be a column at all.

def placebo(con, window: tuple[dt.date, dt.date] | None = None,
            ) -> tuple[pd.DataFrame, dict]:
    """PRE-CONDITION. The 15x15 category alignment matrix, and its verdict.

    THE QUESTION. `bike_od_supplied_share` for `grocery` is supposed to be about
    where groceries are. If the number computed with the grocery threshold ranks
    origin NTAs the same way as the number computed with the bar threshold, then
    it is not about groceries: it is destination retail density in a costume, and
    every category is the same column fifteen times.

    THE TEST IS THE NULL BASELINE, NOT THE OFF-DIAGONAL (changed 2026-09-15
    after the red-team pass). The old gate was "mean off-diagonal rank
    correlation below 0.95", which gated nothing: destination supply density
    correlates across categories at 0.76 mean / 0.94 max before any of this runs,
    so 0.95 passes anything short of a literal copy.

    The null instead asks the question the card claims to answer. Some
    destinations are above median in ALL FIFTEEN categories -- they are simply
    the busy neighbourhoods. `null_baseline` is the share of an origin's
    measurable outbound trips that land in one of those, i.e. what
    `bike_od_supplied_share` would read if "supplied with a pharmacy" meant
    nothing beyond "busy". A category EARNS its column only by beating that null
    by at least `NULL_BASELINE_MIN_EXCESS` at the median origin. Categories that
    do not are listed in the summary and ship as PROSE ONLY -- no column, no card
    number, per category, not all-or-nothing.

    DEMOTED TO DESCRIPTIVE 2026-09-16 (D43). Everything in this function --
    including `null_baseline` and the null-excess verdict -- is now a
    DESCRIPTION. It compares LEVELS, and a destination above the grocery median
    is nine times in ten above every median, so beating the all-fifteen share
    does not separate a specific category from one riding the same
    destination-attractiveness factor. The GATE is `category_specificity`
    below, which compares the RESIDUAL of each category's density on the other
    fourteen. `dot_validation` reads its verdicts and no longer reads `passes`
    from here.

    The 15x15 matrix is still computed and returned. It is a DESCRIPTION of how
    interchangeable the categories are, and no longer a test.

    Returns (matrix indexed and columned by category, summary dict with
    `null_baseline`, `per_category`, `categories_passing`, `categories_failing`,
    `mean_offdiag`, `median_offdiag`, `max_offdiag`, `diag`, `passes`).
    """
    from scipy.stats import spearmanr

    first, last = window or window_bounds(con)
    flow_df = flow(con, first, last)
    density = supply_density(con)
    thresholds = supply_thresholds(density)
    cat, _outside, _ = supplied_share(flow_df, density, thresholds)
    wide = cat.pivot(index="nta_code", columns="category",
                     values="bike_od_supplied_share")
    cats = [c for c in sorted(CATEGORIES) if c in wide.columns]
    wide = wide[cats]
    n = len(cats)
    mat = pd.DataFrame(np.eye(n), index=cats, columns=cats)
    for i, a in enumerate(cats):
        for b in cats[i + 1:]:
            pair = wide[[a, b]].dropna()
            rho = (float(spearmanr(pair[a], pair[b]).statistic)
                   if len(pair) >= 3 and pair[a].nunique() > 1
                   and pair[b].nunique() > 1 else float("nan"))
            mat.loc[a, b] = mat.loc[b, a] = rho
    off = mat.to_numpy()[~np.eye(n, dtype=bool)]
    off = off[np.isfinite(off)]

    null_by_origin, all_cat_ntas = null_baseline(flow_df, density, thresholds)
    per_cat = []
    for c in cats:
        pair = pd.concat([wide[c].rename("v"), null_by_origin.rename("null")],
                         axis=1).dropna()
        excess = (pair["v"] - pair["null"]) if len(pair) else pd.Series(dtype=float)
        med = float(excess.median()) if len(excess) else float("nan")
        per_cat.append({
            "category": c,
            "n_origins": len(pair),
            "median_share": float(pair["v"].median()) if len(pair) else float("nan"),
            "median_null": float(pair["null"].median()) if len(pair) else float("nan"),
            "median_excess": med,
            "share_of_origins_beating_null": (
                float((excess > 0).mean()) if len(excess) else float("nan")),
            "passes": bool(not np.isnan(med)
                           and med >= NULL_BASELINE_MIN_EXCESS),
        })
    per_cat = pd.DataFrame(per_cat)
    passing = sorted(per_cat.loc[per_cat["passes"], "category"])
    failing = sorted(per_cat.loc[~per_cat["passes"], "category"])
    summary = {
        "n_origin_ntas": len(wide),
        "categories": n,
        "diag": 1.0,
        "mean_offdiag": float(np.mean(off)) if off.size else float("nan"),
        "median_offdiag": float(np.median(off)) if off.size else float("nan"),
        "max_offdiag": float(np.max(off)) if off.size else float("nan"),
        "null_baseline": float(null_by_origin.median(skipna=True))
        if len(null_by_origin) else float("nan"),
        "null_baseline_all_category_ntas": len(all_cat_ntas),
        "per_category": per_cat,
        "categories_passing": passing,
        "categories_failing": failing,
        # `bar` is kept under its old name so the spliced CLI keeps running; it
        # now means the minimum excess over the null, not an off-diagonal rho.
        "bar": NULL_BASELINE_MIN_EXCESS,
        "passes": bool(len(passing) == n and n > 0),
    }
    return mat, summary


def null_baseline(flow_df: pd.DataFrame, density: pd.DataFrame,
                  thresholds: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """(share per origin NTA, the all-category destination NTAs).

    What `bike_od_supplied_share` would read for ANY category if "supplied" meant
    no more than "a destination that is above median in everything". Any category
    that cannot beat this is measuring busyness.
    """
    d = density.merge(thresholds, on="category", how="left")
    d["above"] = d["poi_per_1k_units"] > d["threshold"]
    per_nta = d.groupby("nta_code")["above"].agg(["sum", "count"])
    all_cat = sorted(per_nta.index[(per_nta["sum"] == per_nta["count"])
                                   & (per_nta["count"] > 0)])
    universe = set(density["nta_code"])
    out = flow_df[flow_df["destination_nta"] != flow_df["origin_nta"]]
    inside = out[out["destination_nta"].isin(universe)]
    if inside.empty:
        return pd.Series(dtype="float64", name="null"), all_cat
    tot = inside.groupby("origin_nta")["trips"].sum()
    hit = (inside[inside["destination_nta"].isin(all_cat)]
           .groupby("origin_nta")["trips"].sum().reindex(tot.index).fillna(0.0))
    return (hit / tot.replace(0, np.nan)).rename("null"), all_cat


# ======================================================================== D43
# CATEGORY SPECIFICITY -- the placebo that decides whether
# `bike_od_supplied_share` may be a STORED NUMBER at all.
#
# THE QUESTION `null_baseline` could not answer. `placebo()` above asks whether a
# category beats "riders go to the busy neighbourhoods". It cannot tell a
# category that is genuinely specific from one that rides on the same
# destination-attractiveness factor with a slightly different loading, because
# the quantity it compares is still a LEVEL: a destination above the grocery
# median is, nine times in ten, above every median. D43 replaces the level with
# a RESIDUAL. For each category c it regresses log1p(density_c) on log1p(the sum
# of the other fourteen densities) across destinations, ranks the residual, and
# asks whether a neighbourhood's riders go to destinations that are unusually
# WELL supplied with c GIVEN how well supplied they are with everything else.
#
#     r_c(d)  = rank-percentile in [0, 1] of that residual among destinations
#     W_c(o)  = sum_d w_od * r_c(d) - 0.5,  w_od = the origin's inside-universe
#               outbound non-round evening/weekend trip share
#
# W_c(o) is centred so that an origin whose riders spread evenly over
# destinations reads 0.0. A positive median over origins says "riders from here
# go where c is denser than expected"; a negative one says "sparser than
# expected", and the card may use either (P6).
#
# THRESHOLDS ARE NOT SET HERE. Every bar below was fixed by a blind ratifier on
# 2026-09-16 who saw the design and no data (`D43 pre-registration`, binding),
# and each one is a keyword argument so that re-running under a different bar is
# an argument change rather than an edit. `THRESHOLDS_PENDING` gates the verdict
# column: while it is True every verdict prints as "thresholds pending
# ratification" and nothing may be stored or swept.
#
# THE EFFECTIVE SAMPLE IS DESTINATIONS, NEVER ORIGINS. One permutation per draw
# is applied to every origin, so the ~110 origin readings are ~78 destination
# ranks wearing 110 hats. Every diagnostic in this section exists to keep that
# fact in front of the reader: sum w^2 per origin, the cosine similarity of the
# origin weight vectors, the number of distinct weight vectors, and Moran's I of
# r_c over destinations.
#
# REPORT ONLY. Nothing here writes; `resweep_failing_categories` is the one
# function that can, it defaults to a dry run, and it is wired to no automatic
# path.

#: The five categories whose demand happens during WEEKDAY BUSINESS HOURS, which
#: is exactly the window `LEAKAGE_WINDOW_SQL` excludes. They are NOT dropped --
#: P8 of the pre-registration forbids a structural exclusion, and all fifteen sit
#: in ONE Benjamini-Hochberg family. They are flagged IN ADVANCE as a built-in
#: negative control: an evening bike trip is not how anyone reaches a bank.
EXPECTED_UNINFORMATIVE = frozenset({
    "childcare", "clinic", "bank", "tailor_repair", "hardware"})

#: THE KILL RULE (P8). If two or more of the five above PASS with a positive
#: sign, the statistic is not measuring category specificity -- it is measuring
#: destination attractiveness through a residual that failed to remove it, and NO
#: category may carry a stored number. Two, not one, because a single flagged
#: category passing is within what fifteen tests at q = 0.10 will produce.
KILL_RULE_MIN_PASSES = 2
KILL_RULE_MESSAGE = "confounded by destination attractiveness"

#: False since the blind ratification of 2026-09-16. Flip to True to re-blind:
#: every verdict then reads `THRESHOLDS_PENDING_MESSAGE`, nothing is storable,
#: and `resweep_failing_categories` refuses to write.
THRESHOLDS_PENDING = False
THRESHOLDS_PENDING_MESSAGE = "thresholds pending ratification"

#: P1. Ten thousand permutation draws, and the SAME ten thousand random index
#: sets reused for all fifteen categories -- cross-category dependence is
#: preserved, which is what makes a max-T check possible later.
SPECIFICITY_N_PERM = 10_000
#: P1/P5. Two thousand resamples, for both bootstraps.
SPECIFICITY_N_BOOT = 2_000
#: P2. One family of SEVENTEEN, q = 0.10 (the D111 precedent). No second q.
#: Fifteen until 2026-09-17, then sixteen (GTM-198, bathhouse_sauna); widened
#: to seventeen by owner ruling (D137, brewery) -- P8 forbids a structural
#: exclusion, so each new slug joins the family rather than being carved out
#: of it.
SPECIFICITY_BH_Q = 0.10
#: P3. |median W| >= 0.05 is about four rank positions of seventy-nine; the rank
#: grid itself is 1/79 = 0.0127, so this is four grid steps, not one.
SPECIFICITY_MIN_EFFECT = 0.05
#: P3. MDE = 2.8 * sigma-hat-0, sigma-hat-0 read off the permutation draws of
#: median W. Above `SPECIFICITY_MIN_EFFECT` the run cannot resolve the floor and
#: every non-PASS says so rather than claiming a null.
SPECIFICITY_MDE_Z = 2.8
#: P4, all three declared before the run. A category tripping any of them is
#: LOW_POWER: still reported, still counted in the BH family, never storable.
SPECIFICITY_AUX_R2_CUTOFF = 0.75
SPECIFICITY_MIN_SUPPLIED_DESTINATIONS = 20
SPECIFICITY_MIN_MEDIAN_POIS = 3

#: P1 strata: quintile of the other-fourteen density x tercile of destination
#: dock count. Dock count is in the stratum definition because dock siting is the
#: endogeneity this whole measure is exposed to (D76) -- permuting a rank onto a
#: destination with a tenth of the docks would manufacture a null the flow could
#: never produce.
SPECIFICITY_STRATA = (5, 3)
#: ... collapsing to tercile x median-split when the 5x3 grid leaves the median
#: stratum under four destinations. Declared in advance, applied automatically,
#: and printed in the diagnostics.
SPECIFICITY_STRATA_COLLAPSED = (3, 2)
SPECIFICITY_MIN_STRATUM_MEDIAN = 4

#: Diagnostics. k = 6 nearest destinations and 199 permutations for Moran's I;
#: three flagged categories is the point at which a spatially-blocked null
#: becomes primary (`--spatial-block`); 0.9 is the cosine above which the median
#: over origins is one number wearing 110 hats.
SPECIFICITY_MORAN_K = 6
SPECIFICITY_MORAN_PERMUTATIONS = 199
SPECIFICITY_MORAN_FLAG_CATEGORIES = 3
SPECIFICITY_COSINE_FLAG = 0.9

#: Arithmetic floors, not bars: below these the statistic does not exist at all
#: and there is nothing for a ratifier to set.
MIN_SPECIFICITY_DESTINATIONS = 3
MIN_SPECIFICITY_ORIGINS = 3


def rank_percentile(values) -> np.ndarray:
    """(rank - 0.5) / n, average ranks for ties.

    The -0.5 is not cosmetic. It makes the vector average EXACTLY 0.5 for every
    n, so `W_c(o) = sum_d w_od r_c(d) - 0.5` is exactly zero for an origin whose
    riders spread evenly -- and a test can assert that rather than approximate
    it. `rank/n` averages (n+1)/2n and would put a silent +1/2n on every origin.
    """
    v = pd.Series(np.asarray(values, dtype="float64"))
    n = int(v.notna().sum())
    if n == 0:
        return np.full(len(v), np.nan)
    return ((v.rank(method="average") - 0.5) / n).to_numpy(dtype="float64")


def destination_residual_rank(density_df: pd.DataFrame,
                              ) -> tuple[pd.DataFrame, dict]:
    """((destination_nta, category, density, other_density, residual, r), aux R2).

    ONE ordinary least squares per category, fifteen in all: log1p(density_c)
    on log1p(sum of the other fourteen densities), across destinations. The
    residual is what the other fourteen cannot account for, and `r` is its
    rank-percentile among destinations.

    WHY log1p AND NOT log. A universe NTA with no open pharmacy has density 0,
    and it is a real destination, not a missing one -- dropping it would rebuild
    the eligibility gate D75 forbids, from the supply side. log1p keeps it at 0
    and leaves the scale near-logarithmic where the counts are large. (Whether
    log1p on POIs per 1,000 units is the right scale at all is the last open
    item on the pre-registration; it is recorded, not settled, and the
    unresidualised robustness column is the check on it.)

    The auxiliary R2 -- how much of a category's density the other fourteen
    already explain -- is returned beside the ranks because it IS the power of
    the test: at R2 = 0.95 the residual is noise and the rank is a coin flip,
    which is what `SPECIFICITY_AUX_R2_CUTOFF` refuses to read.
    """
    wide = density_df.pivot_table(index="nta_code", columns="category",
                                  values="poi_per_1k_units", aggfunc="first")
    cats = [c for c in sorted(CATEGORIES) if c in wide.columns]
    wide = wide[cats].fillna(0.0)
    dest = list(wide.index.astype(str))
    D = wide.to_numpy(dtype="float64")
    total = D.sum(axis=1)

    rows, aux = [], {}
    for j, c in enumerate(cats):
        other = total - D[:, j]
        y = np.log1p(D[:, j])
        x = np.log1p(other)
        xc = x - x.mean()
        var = float(xc @ xc)
        if var <= 0.0:
            resid = y - y.mean()
            r2 = 0.0
        else:
            b = float(xc @ (y - y.mean())) / var
            resid = y - (y.mean() + b * xc)
            sst = float(((y - y.mean()) ** 2).sum())
            r2 = 0.0 if sst <= 0.0 else 1.0 - float((resid ** 2).sum()) / sst
        aux[c] = float(r2)
        rows.append(pd.DataFrame({
            "destination_nta": dest,
            "category": c,
            "density": D[:, j],
            "other_density": other,
            "residual": resid,
            "r": rank_percentile(resid),
        }))
    out = (pd.concat(rows, ignore_index=True) if rows
           else pd.DataFrame(columns=["destination_nta", "category", "density",
                                      "other_density", "residual", "r"]))
    return out, aux


def origin_weight_matrix(flow_df: pd.DataFrame, destinations: list[str],
                         min_trips: int = MIN_ORIGIN_TRIPS,
                         dest_weight: pd.Series | None = None,
                         weighted: bool = True,
                         ) -> tuple[list[str], np.ndarray, pd.Series]:
    """(origins, W of shape origins x destinations with rows summing to 1, trips).

    The SAME window, universe and floor the stored measure uses, and it has to be
    the same or the placebo would be testing a different number than the one it
    licenses: non-round evening/weekend trips out of residential docks
    (`flow()`), destination != origin, destination inside the measurable
    universe, and at least `min_trips` of them.

    `dest_weight` multiplies each destination's trips before renormalising --
    1/docks for the trips-per-dock robustness column. `weighted=False` gives every
    destination an origin reaches the same weight, which is the unweighted arm of
    the weighted-vs-unweighted lift.
    """
    idx = {d: i for i, d in enumerate(destinations)}
    out = flow_df[flow_df["destination_nta"] != flow_df["origin_nta"]]
    inside = out[out["destination_nta"].isin(idx)]
    if inside.empty:
        return [], np.zeros((0, len(destinations))), pd.Series(dtype="float64")
    w = inside.copy()
    w["trips"] = w["trips"].astype("float64")
    if not weighted:
        w["trips"] = 1.0
    if dest_weight is not None:
        w["trips"] = w["trips"] * w["destination_nta"].map(dest_weight).astype(
            "float64").fillna(0.0)
    trips = inside.groupby("origin_nta")["trips"].sum().astype("float64")
    keep = sorted(trips.index[trips >= float(min_trips)])
    if not keep:
        return [], np.zeros((0, len(destinations))), trips
    oidx = {o: i for i, o in enumerate(keep)}
    w = w[w["origin_nta"].isin(oidx)]
    M = np.zeros((len(keep), len(destinations)), dtype="float64")
    np.add.at(M,
              (w["origin_nta"].map(oidx).to_numpy(dtype="int64"),
               w["destination_nta"].map(idx).to_numpy(dtype="int64")),
              w["trips"].to_numpy(dtype="float64"))
    tot = M.sum(axis=1, keepdims=True)
    ok = (tot[:, 0] > 0)
    M[ok] = M[ok] / tot[ok]
    keep = [o for o, k in zip(keep, ok) if k]
    M = M[ok]
    return keep, M, trips.reindex(keep)


def trip_weighted_rank(flow_df: pd.DataFrame, ranks: pd.DataFrame,
                       min_trips: int = MIN_ORIGIN_TRIPS,
                       dest_weight: pd.Series | None = None,
                       weighted: bool = True) -> pd.DataFrame:
    """(origin_nta, category, w_rank) -- W_c(o), NULL under the trip floor.

    NULL, NEVER ZERO, for the module's standing reason: an origin with fewer than
    `min_trips` inside-universe outbound trips has no denominator, and a 0.0
    would assert that its riders go nowhere in particular, which is a claim about
    the dock network in the costume of a claim about the street. Origins below
    the floor appear with NaN rather than vanishing, so a caller cannot mistake
    the frame for the universe.
    """
    destinations = sorted(ranks["destination_nta"].unique())
    cats = sorted(ranks["category"].unique())
    origins, M, _ = origin_weight_matrix(flow_df, destinations, min_trips,
                                         dest_weight=dest_weight,
                                         weighted=weighted)
    wide = (ranks.pivot(index="destination_nta", columns="category", values="r")
                 .reindex(destinations)[cats])
    R = wide.to_numpy(dtype="float64")
    all_origins = sorted(pd.Series(flow_df["origin_nta"]).dropna().unique())
    vals = pd.DataFrame(np.nan, index=all_origins, columns=cats)
    if origins:
        vals.loc[origins, cats] = M @ R - 0.5
    return (vals.rename_axis("origin_nta").reset_index()
                .melt(id_vars="origin_nta", var_name="category",
                      value_name="w_rank"))


def permute_within_strata(values, strata, rng=None, n_draws: int | None = None,
                          randoms: np.ndarray | None = None) -> np.ndarray:
    """(n_draws x n) -- `values` shuffled WITHIN each stratum, never across one.

    `randoms`, an (n_draws x n) uniform matrix, is how P1's "the same ten
    thousand index sets reused for all fifteen categories" is honoured. The
    strata themselves differ between categories (the quintile is of that
    category's other-fourteen density), so the index sets cannot be literally
    identical; reusing the same uniforms and argsorting them inside each
    category's strata is the faithful version, and it keeps the cross-category
    dependence a max-T check would need.
    """
    v = np.asarray(values, dtype="float64")
    s = np.asarray(strata, dtype=object)
    n = len(v)
    if randoms is None:
        rng = rng or np.random.default_rng(0)
        n_draws = int(n_draws or 1)
        randoms = rng.random((n_draws, n))
    else:
        # `n_draws` FOLLOWS the supplied matrix unless it is asked for
        # explicitly. Defaulting it to 1 here silently reduced a 10,000-draw
        # permutation null to a single draw, and a p-value read off one draw is
        # 0.5 or 1.0 with nothing in between.
        randoms = np.asarray(randoms, dtype="float64")
        n_draws = int(n_draws or randoms.shape[0])
    out = np.repeat(v[None, :], n_draws, axis=0)
    for code in pd.unique(s):
        idx = np.flatnonzero(s == code)
        if idx.size < 2:
            continue
        order = np.argsort(randoms[:n_draws][:, idx], axis=1, kind="stable")
        out[:, idx] = v[idx][order]
    return out


def benjamini_hochberg(pvals, q: float) -> np.ndarray:
    """Which p-values survive Benjamini-Hochberg at false-discovery rate `q`.

    STEP-UP, not per-p: the largest k with p_(k) <= q k/m rejects everything at
    or below it, including any p above its own line. Comparing each p to its own
    q i/m is the classic off-by-one and it is conservative in the wrong place.
    Non-finite p-values are never rejected and never counted in m -- a category
    whose statistic does not exist is not a test that was run.
    """
    p = np.asarray(pvals, dtype="float64")
    out = np.zeros(p.shape, dtype=bool)
    idx = np.flatnonzero(np.isfinite(p))
    if idx.size == 0:
        return out
    order = idx[np.argsort(p[idx], kind="mergesort")]
    m = order.size
    passed = p[order] <= (q * np.arange(1, m + 1) / m)
    if passed.any():
        out[order[:int(np.flatnonzero(passed).max()) + 1]] = True
    return out


def _bca_interval(theta: float, boot, jack, alpha: float = 0.05,
                  ) -> tuple[float, float, str]:
    """95% BCa, falling back to the percentile interval and SAYING so.

    BCa needs two corrections the percentile interval skips: z0 for the median
    bias of the bootstrap distribution, and `a` for how fast the statistic's
    variance moves with the data, estimated by a leave-one-destination-out
    jackknife. Both can be undefined here -- z0 when every draw falls on one side
    of the estimate, `a` when the jackknife is degenerate -- and in either case
    the returned method string names the fallback rather than letting a
    percentile interval pass as a BCa one.
    """
    from scipy.stats import norm

    b = np.asarray(boot, dtype="float64")
    b = b[np.isfinite(b)]
    if b.size < 20:
        return float("nan"), float("nan"), "too few bootstrap draws"
    lo_p = float(np.percentile(b, 100 * alpha / 2))
    hi_p = float(np.percentile(b, 100 * (1 - alpha / 2)))
    n_less = int((b < theta).sum())
    if n_less == 0 or n_less == b.size:
        return lo_p, hi_p, "percentile (z0 undefined)"
    j = np.asarray(jack, dtype="float64")
    j = j[np.isfinite(j)]
    if j.size < 3:
        return lo_p, hi_p, "percentile (no jackknife)"
    z0 = float(norm.ppf(n_less / b.size))
    d = j.mean() - j
    denom = 6.0 * float((d ** 2).sum()) ** 1.5
    a = 0.0 if denom == 0 else float((d ** 3).sum()) / denom
    ends = []
    for z in (float(norm.ppf(alpha / 2)), float(norm.ppf(1 - alpha / 2))):
        num = z0 + z
        adj = z0 + num / (1.0 - a * num)
        ends.append(float(np.percentile(b, 100 * float(norm.cdf(adj)))))
    lo, hi = sorted(ends)
    return lo, hi, "BCa"


def _strata_codes(other_density, dock_count, grid: tuple[int, int]) -> np.ndarray:
    """quintile(other density) x tercile(dock count), as string codes.

    Cut on the RANK, not the value: dock counts are heavily tied at the low end
    (many NTAs carry three or four docks) and `qcut` on raw values drops most of
    its edges to duplicates, silently collapsing the tercile to a single bin.
    """
    nq, nt = grid
    q = pd.qcut(pd.Series(other_density).rank(method="first"), nq,
                labels=False, duplicates="drop").astype("float64")
    t = pd.qcut(pd.Series(dock_count).rank(method="first"), nt,
                labels=False, duplicates="drop").astype("float64")
    return (q.fillna(-1).astype(int).astype(str) + "|"
            + t.fillna(-1).astype(int).astype(str)).to_numpy(dtype=object)


def _spatial_order(destinations: list[str],
                   centroids: pd.DataFrame | None) -> np.ndarray:
    """Destinations in a one-dimensional spatial order, community districts kept
    contiguous. The order the `--spatial-block` cyclic-shift null shifts along."""
    key = []
    cds = _cd_codes(destinations)
    xy = {}
    if centroids is not None and len(centroids):
        c = centroids.set_index("nta_code")
        for d in destinations:
            if d in c.index:
                xy[d] = (float(c.loc[d, "lat"]), float(c.loc[d, "lon"]))
    for i, d in enumerate(destinations):
        lat, lon = xy.get(d, (0.0, 0.0))
        key.append((str(cds[i]), lat, lon, d))
    return np.asarray([i for i, _ in sorted(enumerate(key), key=lambda t: t[1])],
                      dtype="int64")


def _cd_codes(ntas) -> np.ndarray:
    """Community district per NTA, through `validation/retrodiction.cd_code` --
    ONE derivation of the CD in the project, not a second one. The fallback is
    the same four characters, so a circular import would degrade the provenance
    of the rule and never its result."""
    try:
        from loci.validation.retrodiction import cd_code as _cd
    except Exception:                               # noqa: BLE001 - provenance only
        def _cd(v):
            return None if v is None else str(v)[:4]
    return np.asarray([_cd(v) for v in ntas], dtype=object)


def _morans_i(values, xy, k: int, permutations: int, seed: int) -> dict:
    """Moran's I through `validation/retrodiction.morans_i_knn` -- one
    implementation, not a second."""
    try:
        from loci.validation.retrodiction import morans_i_knn
    except Exception:                               # noqa: BLE001
        return {"i": None, "p_perm": None, "note": "morans_i_knn unavailable"}
    return morans_i_knn(values, xy, k=k, permutations=permutations, seed=seed)


def _median_weighted(M: np.ndarray, R: np.ndarray) -> np.ndarray:
    """median over origins of (M @ R) - 0.5, column by column of R."""
    return np.median(M @ R - 0.5, axis=0)


def _rerank_multiset(resid: np.ndarray, mult: np.ndarray) -> np.ndarray:
    """Rank-percentiles after resampling destinations with multiplicities.

    A destination drawn three times is three tied observations, so every copy
    takes the same average rank -- which is why this is exact arithmetic on the
    sorted order rather than a materialised expansion of the multiset.
    `mult` is (draws x n_destinations); the result is the same shape.
    """
    order = np.argsort(resid, kind="mergesort")
    mo = mult[:, order]
    cum_before = np.cumsum(mo, axis=1) - mo
    avg_rank = cum_before + (mo + 1.0) / 2.0
    n = mo.sum(axis=1, keepdims=True)
    r_sorted = np.where(n > 0, (avg_rank - 0.5) / np.maximum(n, 1), np.nan)
    out = np.empty_like(r_sorted)
    out[:, order] = r_sorted
    return out


def _median_W_resampled(M: np.ndarray, mult: np.ndarray,
                        resid: np.ndarray) -> np.ndarray:
    """median over origins of W_c under each destination resample.

    The resample re-weights rather than re-materialises: a destination drawn
    twice carries twice the trip weight, and the row is renormalised, which is
    exactly what resampling the destination would do to the share.
    """
    r = _rerank_multiset(resid, mult)
    num = M @ (mult * np.nan_to_num(r)).T
    den = M @ mult.T
    with np.errstate(invalid="ignore", divide="ignore"):
        vals = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan) - 0.5
    return np.nanmedian(vals, axis=0)


def dock_counts(con) -> pd.Series:
    """Docks per NTA, through `dock_nta_map` -- the module's one dock -> NTA rule.

    In the P1 stratum definition because dock siting is the endogeneity the whole
    measure is exposed to (D76). A null that moves a rank from a 40-dock
    destination onto a 3-dock one manufactures a flow the network could not
    produce, and the test would then reject against an impossibility.
    """
    m = dock_nta_map(con)
    if m.empty:
        return pd.Series(dtype="float64")
    return (m.dropna(subset=["nta_code"]).groupby("nta_code")["station_id"]
             .nunique().astype("float64"))


def nta_centroids(con) -> pd.DataFrame:
    """(nta_code, lon, lat) -- the mean lot-frame address point per NTA.

    Only Moran's I and the `--spatial-block` ordering use it, so a warehouse
    without coordinates degrades those two diagnostics to "unavailable" and
    changes no verdict.
    """
    try:
        return con.execute(
            "SELECT nta_code, avg(lon) AS lon, avg(lat) AS lat "
            "FROM analysis.address "
            "WHERE nta_code IS NOT NULL AND lon IS NOT NULL AND lat IS NOT NULL "
            "  AND COALESCE(frame, 'lot') = 'lot' GROUP BY 1").fetchdf()
    except Exception:                               # noqa: BLE001 - diagnostic only
        return pd.DataFrame(columns=["nta_code", "lon", "lat"])


def specificity_verdict(bh_pass: bool, ci_excludes_zero: bool,
                        effect_pass: bool, low_power: bool,
                        underpowered: bool) -> str:
    """The CONJUNCTIVE verdict of pre-registration P7, in one place.

    PASS needs all three: a BH-surviving p, a destination CI clear of zero, and
    |median W| at or above the floor. NULL is RESERVED for the case where none of
    the three holds -- it is a positive claim that the category is not specific,
    and it is the only verdict `resweep_failing_categories` will act on. Anything
    in between is INCONCLUSIVE: both numbers are printed, nothing is stored, and
    it is explicitly NOT a null.

    UNDERPOWERED (P3): when 2.8 * sigma-hat-0 exceeds the floor, the run cannot
    resolve the floor, so what would have been NULL becomes CANNOT_RESOLVE.
    INCONCLUSIVE and LOW_POWER keep their names -- neither asserts a null, both
    already store nothing, and collapsing them would throw away the reason. The
    CLI renders every non-PASS verdict in an underpowered run as "cannot
    resolve" regardless, which is the wording the pre-registration asks for.
    """
    if THRESHOLDS_PENDING:
        return "PENDING"
    if low_power:
        return "LOW_POWER"
    if bh_pass and ci_excludes_zero and effect_pass:
        return "PASS"
    if not bh_pass and not ci_excludes_zero and not effect_pass:
        return "CANNOT_RESOLVE" if underpowered else "NULL"
    return "INCONCLUSIVE"


def _destination_bootstrap_mult(strata: np.ndarray, n_boot: int,
                                rng) -> np.ndarray:
    """(n_boot x n_destinations) multiplicities, resampled WITHIN strata.

    Within strata, not over all destinations, for the reason the permutation is
    stratified: a resample free to replace a 40-dock destination with a 3-dock
    one is not a resample of this city.
    """
    n = len(strata)
    mult = np.zeros((n_boot, n), dtype="float64")
    for code in pd.unique(strata):
        idx = np.flatnonzero(strata == code)
        m = idx.size
        mult[:, idx] = rng.multinomial(m, np.full(m, 1.0 / m), size=n_boot)
    return mult


def _cd_bootstrap_draws(origins: list[str], n_boot: int, rng) -> list[np.ndarray]:
    """Index sets for the SECONDARY bootstrap: community districts resampled with
    replacement, every origin in a drawn district coming with it.

    Secondary, and under P-open-item-4 possibly decorative: if the origin weight
    vectors are near-collinear (median pairwise cosine > 0.9) then 110 origins
    are one number wearing 110 hats and clustering them changes nothing. The
    diagnostic that says so prints above the verdicts.
    """
    cds = _cd_codes(origins)
    groups = {c: np.flatnonzero(cds == c) for c in pd.unique(cds)}
    keys = list(groups)
    if not keys:
        return []
    return [np.concatenate([groups[keys[i]] for i in
                            rng.integers(0, len(keys), len(keys))])
            for _ in range(n_boot)]


def specificity_from_frames(flow_df: pd.DataFrame, density: pd.DataFrame,
                            docks: pd.Series | None = None,
                            centroids: pd.DataFrame | None = None,
                            n_perm: int = SPECIFICITY_N_PERM,
                            n_boot: int = SPECIFICITY_N_BOOT,
                            bh_q: float = SPECIFICITY_BH_Q,
                            min_effect: float = SPECIFICITY_MIN_EFFECT,
                            aux_r2_cutoff: float = SPECIFICITY_AUX_R2_CUTOFF,
                            min_supplied_destinations: int =
                            SPECIFICITY_MIN_SUPPLIED_DESTINATIONS,
                            min_median_pois: float = SPECIFICITY_MIN_MEDIAN_POIS,
                            seed: int = 0,
                            expected_uninformative=EXPECTED_UNINFORMATIVE,
                            min_trips: int = MIN_ORIGIN_TRIPS,
                            spatial_block: bool = False,
                            window: str | None = None) -> dict:
    """The whole D43 test, on FRAMES -- `category_specificity` is this plus a
    warehouse read. The seam is here so the synthetic worlds the tests build
    (trips proportional to one category's density; trips proportional to total
    density) exercise the statistic itself and not a fixture of the warehouse.
    """
    ranks, aux_r2 = destination_residual_rank(density)
    destinations = sorted(ranks["destination_nta"].unique())
    cats = [c for c in sorted(CATEGORIES) if c in set(ranks["category"])]
    n_dest = len(destinations)
    dock = (pd.Series(dtype="float64") if docks is None else docks).reindex(
        destinations).fillna(0.0).to_numpy(dtype="float64")
    origins, M, _trips = origin_weight_matrix(flow_df, destinations, min_trips)

    bars = {"n_perm": int(n_perm), "n_boot": int(n_boot), "bh_q": float(bh_q),
            "min_effect": float(min_effect), "aux_r2_cutoff": float(aux_r2_cutoff),
            "min_supplied_destinations": int(min_supplied_destinations),
            "min_median_pois": float(min_median_pois),
            "min_origin_trips": int(min_trips), "seed": int(seed),
            "mde_z": SPECIFICITY_MDE_Z, "spatial_block": bool(spatial_block)}
    if n_dest < MIN_SPECIFICITY_DESTINATIONS or len(origins) < MIN_SPECIFICITY_ORIGINS:
        return {"window": window, "bars": bars, "thresholds_pending": THRESHOLDS_PENDING,
                "n_destination_ntas": n_dest, "n_origin_ntas": len(origins),
                "per_category": pd.DataFrame(), "robustness": pd.DataFrame(),
                "verdicts": {}, "diagnostics": {"note": "too few origins or destinations"},
                "kill_rule": {"fired": False, "passing_flagged": []},
                "underpowered": True,
                "gate": {"passes": False, "pending": THRESHOLDS_PENDING,
                         "confounded": False, "passing": [], "failing": [],
                         "message": (f"{n_dest} destinations and {len(origins)} "
                                     f"origins clear the floor: the statistic "
                                     f"does not exist on this warehouse.")}}

    # --- strata, and the collapse the pre-registration declared in advance ----
    wide_r = (ranks.pivot(index="destination_nta", columns="category", values="r")
                   .reindex(destinations)[cats])
    wide_e = (ranks.pivot(index="destination_nta", columns="category",
                          values="residual").reindex(destinations)[cats])
    wide_o = (ranks.pivot(index="destination_nta", columns="category",
                          values="other_density").reindex(destinations)[cats])
    wide_d = (ranks.pivot(index="destination_nta", columns="category",
                          values="density").reindex(destinations)[cats])

    def _all_strata(grid):
        return {c: _strata_codes(wide_o[c].to_numpy(), dock, grid) for c in cats}

    grid = SPECIFICITY_STRATA
    strata = _all_strata(grid)
    med_size = float(np.median([np.median(np.unique(s, return_counts=True)[1])
                                for s in strata.values()]))
    collapsed = med_size < SPECIFICITY_MIN_STRATUM_MEDIAN
    if collapsed:
        grid = SPECIFICITY_STRATA_COLLAPSED
        strata = _all_strata(grid)
        med_size = float(np.median([np.median(np.unique(s, return_counts=True)[1])
                                    for s in strata.values()]))

    # --- the shared random draws (P1) ----------------------------------------
    rng = np.random.default_rng(seed)
    U = rng.random((n_perm, n_dest))                 # ONE set, all 15 categories
    label_perm = np.argsort(rng.random((n_perm, n_dest)), axis=1, kind="stable")
    cd_draws = _cd_bootstrap_draws(origins, n_boot, rng)
    jack_mult = 1.0 - np.eye(n_dest)
    order = _spatial_order(destinations, centroids)
    shifts = np.arange(1, n_dest)

    npois = (density.pivot_table(index="nta_code", columns="category",
                                 values="n_pois", aggfunc="first")
                    .reindex(destinations).reindex(columns=cats).fillna(0.0))

    per, rob, moran = [], [], {}
    for c in cats:
        r = wide_r[c].to_numpy(dtype="float64")
        e = wide_e[c].to_numpy(dtype="float64")
        s = strata[c]
        obs = float(np.median(M @ r - 0.5))

        null = _median_weighted(M, permute_within_strata(r, s, randoms=U).T)
        p_perm = float((1 + int((np.abs(null) >= abs(obs)).sum())) / (n_perm + 1))
        sigma0 = float(np.std(null, ddof=1)) if null.size > 1 else float("nan")
        mde = SPECIFICITY_MDE_Z * sigma0

        boot_rng = np.random.default_rng(seed + 1_000 + cats.index(c))
        mult = _destination_bootstrap_mult(s, n_boot, boot_rng)
        boot = _median_W_resampled(M, mult, e)
        jack = _median_W_resampled(M, jack_mult, e)
        ci_lo, ci_hi, ci_method = _bca_interval(obs, boot, jack)
        ci_excl = bool(np.isfinite(ci_lo) and np.isfinite(ci_hi)
                       and (ci_lo > 0 or ci_hi < 0))

        w_obs = M @ r - 0.5
        cd = ([float(np.median(w_obs[i])) for i in cd_draws] if cd_draws else [])
        cd_lo, cd_hi = ((float(np.percentile(cd, 2.5)),
                         float(np.percentile(cd, 97.5))) if len(cd) >= 20
                        else (float("nan"), float("nan")))

        n_supplied = int((npois[c].to_numpy() >= 1).sum())
        med_pois = float(np.median(npois[c].to_numpy()))
        low_power = bool(aux_r2[c] >= aux_r2_cutoff
                         or n_supplied < min_supplied_destinations
                         or med_pois < min_median_pois)

        per.append({
            "category": c, "median_W": obs, "p_perm": p_perm,
            "ci_lo": ci_lo, "ci_hi": ci_hi, "ci_method": ci_method,
            "ci_excludes_zero": ci_excl,
            "cd_ci_lo": cd_lo, "cd_ci_hi": cd_hi,
            "sigma0": sigma0, "mde": mde,
            "effect_pass": bool(abs(obs) >= min_effect),
            "low_power": low_power, "aux_r2": float(aux_r2[c]),
            "n_supplied_destinations": n_supplied, "median_pois": med_pois,
            "expected_uninformative": bool(c in expected_uninformative),
            "n_origins": len(origins),
        })

        # ------------------------------------------------ robustness columns
        per_dock = pd.Series(1.0 / np.maximum(dock, 1.0), index=destinations)
        _, Mpd, _ = origin_weight_matrix(flow_df, destinations, min_trips,
                                         dest_weight=per_dock)
        _, Mun, _ = origin_weight_matrix(flow_df, destinations, min_trips,
                                         weighted=False)
        w_pd = float(np.median(Mpd @ r - 0.5)) if len(Mpd) else float("nan")
        w_un = float(np.median(Mun @ r - 0.5)) if len(Mun) else float("nan")

        r_raw = rank_percentile(wide_d[c].to_numpy(dtype="float64"))
        obs_raw = float(np.median(M @ r_raw - 0.5))
        null_raw = _median_weighted(M, permute_within_strata(r_raw, s,
                                                             randoms=U).T)
        p_raw = float((1 + int((np.abs(null_raw) >= abs(obs_raw)).sum()))
                      / (n_perm + 1))

        null_lab = _median_weighted(M, r[label_perm].T)
        p_lab = float((1 + int((np.abs(null_lab) >= abs(obs)).sum()))
                      / (n_perm + 1))

        shifted = np.stack([np.roll(r[order], int(k))[np.argsort(order)]
                            for k in shifts])
        null_sh = _median_weighted(M, shifted.T)
        p_shift = float((1 + int((np.abs(null_sh) >= abs(obs)).sum()))
                        / (shifts.size + 1))

        rob.append({"category": c, "median_W": obs,
                    "median_W_per_dock": w_pd,
                    "median_W_unweighted": w_un,
                    "weighted_lift": obs - w_un,
                    "median_W_unresidualised": obs_raw,
                    "p_unresidualised": p_raw,
                    "p_label_permutation": p_lab,
                    "p_spatial_block": p_shift})

        if centroids is not None and len(centroids):
            cxy = centroids.set_index("nta_code").reindex(destinations)
            moran[c] = _morans_i(r, cxy[["lon", "lat"]].to_numpy(dtype="float64"),
                                 SPECIFICITY_MORAN_K,
                                 SPECIFICITY_MORAN_PERMUTATIONS, seed)
        else:
            moran[c] = {"i": None, "p_perm": None, "note": "no centroids"}

    per = pd.DataFrame(per)
    rob = pd.DataFrame(rob)

    # --- one BH family of fifteen (P2/P8), on the PRIMARY p ------------------
    p_primary = (rob["p_spatial_block"].to_numpy() if spatial_block
                 else per["p_perm"].to_numpy())
    per["p_primary"] = p_primary
    per["bh_pass"] = benjamini_hochberg(p_primary, bh_q)

    underpowered = bool(np.nanmedian(per["mde"].to_numpy()) > min_effect)
    per["underpowered"] = per["mde"].to_numpy() > min_effect
    per["verdict"] = [
        specificity_verdict(bool(row.bh_pass), bool(row.ci_excludes_zero),
                            bool(row.effect_pass), bool(row.low_power),
                            bool(row.underpowered))
        for row in per.itertuples()]

    # --- the kill rule (P8) --------------------------------------------------
    flagged_pass = sorted(per.loc[(per["expected_uninformative"])
                                  & (per["verdict"] == "PASS")
                                  & (per["median_W"] > 0), "category"])
    killed = len(flagged_pass) >= KILL_RULE_MIN_PASSES
    if killed:
        per["verdict"] = "NO_STORED_NUMBER"

    verdicts = dict(zip(per["category"], per["verdict"]))
    passing = sorted(per.loc[per["verdict"] == "PASS", "category"])
    failing = sorted(per.loc[per["verdict"] == "NULL", "category"])

    # --- diagnostics, which the CLI prints BEFORE the verdicts ---------------
    sumsq = (M ** 2).sum(axis=1)
    wbar = M.mean(axis=0)
    norm = M / np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-12)
    cos = norm @ norm.T
    iu = np.triu_indices(len(origins), k=1)
    moran_flagged = sorted(c for c, m in moran.items()
                           if m.get("p_perm") is not None and m["p_perm"] < 0.05)
    diagnostics = {
        "n_origins": len(origins), "n_destinations": n_dest,
        "n_destinations_with_trips": int((M > 0).any(axis=0).sum()),
        "n_cds": len(set(_cd_codes(origins))),
        "sum_w2_p50": float(np.median(sumsq)),
        "sum_w2_p90": float(np.percentile(sumsq, 90)),
        "sum_w2_max": float(sumsq.max()),
        "n_eff_destinations_p50": float(np.median(1.0 / np.maximum(sumsq, 1e-12))),
        "sum_w2_mean_vector": float((wbar ** 2).sum()),
        "n_eff_mean_vector": float(1.0 / max(float((wbar ** 2).sum()), 1e-12)),
        "distinct_weight_vectors": len(np.unique(np.round(M, 6), axis=0)),
        "median_pairwise_cosine": (float(np.median(cos[iu])) if iu[0].size
                                   else float("nan")),
        "cosine_flag": (bool(iu[0].size
                             and np.median(cos[iu]) > SPECIFICITY_COSINE_FLAG)),
        "strata_grid": f"{grid[0]}x{grid[1]}",
        "strata_collapsed": bool(collapsed),
        "median_stratum_size": med_size,
        "strata_singletons": {c: int((np.unique(strata[c], return_counts=True)[1]
                                      == 1).sum()) for c in cats},
        "morans_i": moran,
        "moran_k": SPECIFICITY_MORAN_K,
        "moran_permutations": SPECIFICITY_MORAN_PERMUTATIONS,
        "moran_flagged": moran_flagged,
        "moran_flag_trips": bool(len(moran_flagged)
                                 >= SPECIFICITY_MORAN_FLAG_CATEGORIES),
        "sigma0_median": float(np.nanmedian(per["sigma0"].to_numpy())),
        "mde_median": float(np.nanmedian(per["mde"].to_numpy())),
        "underpowered": underpowered,
    }

    if THRESHOLDS_PENDING:
        message = THRESHOLDS_PENDING_MESSAGE
    elif killed:
        message = (f"{KILL_RULE_MESSAGE}: {len(flagged_pass)} of the five "
                   f"expected-uninformative categories PASS with a positive sign "
                   f"({', '.join(flagged_pass)}). No category may carry a stored "
                   f"number.")
    elif passing:
        message = (f"{len(passing)} of {len(cats)} categories are specific: "
                   f"{', '.join(passing)}.")
    else:
        message = ("no category clears all three gates; "
                   f"bike_od_supplied_share stays prose for all {len(cats)}.")

    return {
        "window": window, "bars": bars,
        "thresholds_pending": THRESHOLDS_PENDING,
        "n_origin_ntas": len(origins), "n_destination_ntas": n_dest,
        "per_category": per, "robustness": rob, "verdicts": verdicts,
        "diagnostics": diagnostics, "underpowered": underpowered,
        "expected_uninformative": sorted(expected_uninformative),
        "kill_rule": {"fired": bool(killed), "passing_flagged": flagged_pass,
                      "min_passes": KILL_RULE_MIN_PASSES,
                      "message": KILL_RULE_MESSAGE},
        "gate": {"passes": bool(not THRESHOLDS_PENDING and not killed
                                and bool(passing)),
                 "pending": bool(THRESHOLDS_PENDING), "confounded": bool(killed),
                 "passing": passing, "failing": failing, "message": message},
    }


def category_specificity(con, window: tuple[dt.date, dt.date] | None = None,
                         n_perm: int = SPECIFICITY_N_PERM,
                         n_boot: int = SPECIFICITY_N_BOOT,
                         bh_q: float = SPECIFICITY_BH_Q,
                         min_effect: float = SPECIFICITY_MIN_EFFECT,
                         aux_r2_cutoff: float = SPECIFICITY_AUX_R2_CUTOFF,
                         seed: int = 0,
                         expected_uninformative=EXPECTED_UNINFORMATIVE,
                         min_trips: int = MIN_ORIGIN_TRIPS,
                         spatial_block: bool = False) -> dict:
    """D43. Is `bike_od_supplied_share` about the CATEGORY, or about the
    destination? Read-only; writes nothing.

    The warehouse read is four frames -- the flow, the supply density, the dock
    counts and the NTA centroids -- and every one of them comes through the
    function the stored measure already uses, so the placebo cannot pass a number
    the build does not compute.
    """
    first, last = window or window_bounds(con)
    return specificity_from_frames(
        flow(con, first, last), supply_density(con),
        docks=dock_counts(con), centroids=nta_centroids(con),
        n_perm=n_perm, n_boot=n_boot, bh_q=bh_q, min_effect=min_effect,
        aux_r2_cutoff=aux_r2_cutoff, seed=seed,
        expected_uninformative=expected_uninformative, min_trips=min_trips,
        spatial_block=spatial_block, window=window_label(first, last))


def resweep_failing_categories(con, verdicts, dry_run: bool = True,
                               confounded: bool = False) -> dict:
    """NULL `bike_od_supplied_share` for the categories D43 declares NULL.

    THE ONLY WRITE IN THIS SECTION, and it is wired to NO automatic path: a
    `--re-sweep` that silently dropped a column because a permutation test moved
    would be a methodology change disguised as a maintenance job. It is called by
    hand, after a ratified run, and it defaults to `dry_run=True`.

    WHAT IT WILL NOT TOUCH, and why each one matters:
      * PASS -- the category earned its column;
      * INCONCLUSIVE -- exactly one gate held. That is not a null, and deleting a
        number on it would turn "we could not tell" into "we established there is
        nothing", which is the single most expensive confusion in this project;
      * LOW_POWER -- the test could not be run at usable power, which says
        nothing about the category;
      * CANNOT_RESOLVE -- the run's own MDE exceeds the floor (P3);
      * anything at all while `THRESHOLDS_PENDING`, or while the kill rule has
        fired, unless `confounded=True` is passed explicitly -- in which case ALL
        FIFTEEN go, because a confounded statistic licenses no category.
    """
    if isinstance(verdicts, dict) and "verdicts" in verdicts:
        report = verdicts
        verdicts = report["verdicts"]
        killed = bool(report.get("kill_rule", {}).get("fired"))
    else:
        killed = False
    verdicts = {str(k): str(v) for k, v in dict(verdicts).items()}
    if THRESHOLDS_PENDING:
        raise RuntimeError(
            f"refusing to sweep while THRESHOLDS_PENDING: every verdict reads "
            f"'{THRESHOLDS_PENDING_MESSAGE}', so there is no NULL to act on. "
            f"Ratify the bars first.")
    if killed and not confounded:
        raise RuntimeError(
            f"the D43 kill rule fired ({KILL_RULE_MESSAGE}): no category may "
            f"carry a stored number, and sweeping only the NULL ones would leave "
            f"the rest standing on a confounded statistic. Pass confounded=True "
            f"to clear all fifteen, deliberately.")
    if killed and confounded:
        targets = sorted(verdicts)
        reason = KILL_RULE_MESSAGE
    else:
        targets = sorted(c for c, v in verdicts.items() if v == "NULL")
        reason = "verdict NULL"

    rep = {"dry_run": bool(dry_run), "reason": reason, "categories": targets,
           "kill_rule_fired": killed,
           "verdict_counts": {v: int(sum(1 for x in verdicts.values() if x == v))
                              for v in sorted(set(verdicts.values()))}}
    if not targets:
        rep["rows_matched"] = rep["rows_nulled"] = 0
        return rep
    marks = ", ".join("?" for _ in targets)
    rep["rows_matched"] = int(con.execute(
        f"SELECT count(*) FROM analysis.address_category "
        f"WHERE category IN ({marks}) AND bike_od_supplied_share IS NOT NULL",
        targets).fetchone()[0])
    if dry_run:
        rep["rows_nulled"] = 0
        return rep
    con.execute(
        f"UPDATE analysis.address_category SET bike_od_supplied_share = NULL "
        f"WHERE category IN ({marks})", targets)
    rep["rows_nulled"] = rep["rows_matched"]
    return rep


#: DOT publishes am / md / pm and NO evening period (staging.dot_pedestrian_count
#: verified live, 2026-09-15). PM -- the 4-7 pm screenline count -- is therefore
#: the closest published thing to the leakage window, and the mismatch is named
#: in the report rather than papered over: DOT's PM includes the commute home,
#: which the leakage window deliberately excludes.
DOT_PERIOD = "pm"

DOT_POINTS_SQL = """
WITH latest AS (
    SELECT point_id, max(round) AS round
    FROM staging.dot_pedestrian_count
    WHERE period = ? AND count IS NOT NULL AND NOT is_bridge
    GROUP BY 1
)
SELECT d.point_id, d.lon, d.lat, max(d.count) AS count
FROM staging.dot_pedestrian_count d JOIN latest l USING (point_id, round)
WHERE d.period = ?
GROUP BY 1, 2, 3
"""


def dot_validation(con, window: tuple[dt.date, dt.date] | None = None,
                   n_perm: int = SPECIFICITY_N_PERM,
                   n_boot: int = SPECIFICITY_N_BOOT,
                   seed: int = 0) -> dict:
    """GRADUATION. Convergent validity against an independent instrument.

    THE QUESTION. Evening/weekend bike INFLOW to a destination NTA is supposed to
    measure where people go to spend an evening. DOT's biannual screenline counts
    measure feet on a sidewalk, from a different agency with a different sampling
    frame and no relationship to dock siting. If the two disagree, the bike
    number is measuring the bike network.

    THE BARS, BOTH OF WHICH MUST HOLD (§Validation):
      * Spearman rho >= +0.5 between destination-NTA inflow and DOT PM counts
        aggregated to NTA (`DOT_RHO_BAR`);
      * the D43 CATEGORY-SPECIFICITY placebo must pass -- at least one category
        must clear all three of its gates, and the kill rule must not have
        fired. `placebo()` above is reported beside it as a description and is
        no longer the test; while `THRESHOLDS_PENDING` is True the gate is False
        and says `THRESHOLDS_PENDING_MESSAGE`.
    Reported beside the BASELINE TO BEAT: destination-NTA open-POI density
    (per 1,000 residential units) against the same DOT counts. If the baseline
    correlates as well, the trip table has added nothing that a POI count did not
    already say, and the measure ships as prose.

    DOT points are mapped to NTAs through the same python-h3 rule as everything
    else here. Bridge midpoints are excluded, as in model/address_dot_context.py
    -- a count taken 400 m out over the East River is not a reading of any
    neighbourhood.
    """
    from scipy.stats import spearmanr

    first, last = window or window_bounds(con)
    flow_df = flow(con, first, last)
    inflow = (flow_df.groupby("destination_nta", as_index=False)["trips"].sum()
                     .rename(columns={"destination_nta": "nta_code",
                                      "trips": "inflow"}))

    pts = con.execute(DOT_POINTS_SQL, [DOT_PERIOD, DOT_PERIOD]).fetchdf()
    if pts.empty:
        raise RuntimeError(
            "staging.dot_pedestrian_count has no usable points: run "
            "`loci dot ingest` first. An empty instrument would validate "
            "nothing while returning a number.")
    pts["nta_code"] = points_to_nta(pts["lon"], pts["lat"], hex_nta_lookup(con))
    dot = (pts.dropna(subset=["nta_code"])
              .groupby("nta_code", as_index=False)
              .agg(dot_count=("count", "sum"), dot_points=("point_id", "count")))

    density = supply_density(con)
    base = (density.groupby("nta_code", as_index=False)
                   .agg(supply_density=("poi_per_1k_units", "sum")))

    j = dot.merge(inflow, on="nta_code", how="inner").merge(
        base, on="nta_code", how="left")
    if len(j) < 3:
        raise RuntimeError(
            f"only {len(j)} NTAs carry both a DOT count and bike inflow — too "
            f"few to rank-correlate. Ingest more DOT rounds before reading this.")
    rho = float(spearmanr(j["inflow"], j["dot_count"]).statistic)
    base_rho = float(spearmanr(j["supply_density"].fillna(0.0),
                               j["dot_count"]).statistic)
    _, pl = placebo(con, (first, last))
    spec = category_specificity(con, (first, last), n_perm=n_perm,
                                n_boot=n_boot, seed=seed)
    gate = spec["gate"]
    return {
        "window": window_label(first, last),
        "dot_period": DOT_PERIOD,
        "n_ntas": len(j),
        "dot_points": int(j["dot_points"].sum()),
        "rho_inflow_vs_dot": rho,
        "rho_baseline_supply_density_vs_dot": base_rho,
        # kept under the old key so the spliced CLI keeps running; the measure
        # is now POIs per 1,000 residential units, not per address.
        "rho_baseline_poi_per_addr_vs_dot": base_rho,
        "beats_baseline": bool(rho > base_rho),
        "bar": DOT_RHO_BAR,
        # DESCRIPTIVE, both of them (D43): the level-based placebo is reported
        # beside the gate, never as the gate.
        "placebo_mean_offdiag": pl["mean_offdiag"],
        "placebo_null_baseline": pl["null_baseline"],
        "placebo_null_excess_failing": pl["categories_failing"],
        # THE GATE: the D43 per-category verdicts.
        "placebo_categories_failing": gate["failing"],
        "placebo_categories_passing": gate["passing"],
        "placebo_passes": bool(gate["passes"]),
        "placebo_pending": bool(gate["pending"]),
        "placebo_confounded": bool(gate["confounded"]),
        "placebo_message": gate["message"],
        "specificity_verdicts": spec["verdicts"],
        "passes": bool(rho >= DOT_RHO_BAR and gate["passes"]),
    }
