"""Citi Bike ORIGIN-DESTINATION leakage -> `analysis.bike_od_leakage` (phase 2).

WHAT THIS ADDS THAT PHASE 1 CANNOT
---------------------------------------------------------------------------
`staging.citibike_station_month` (phase 1, sql/034) is a MARGINAL: a dock's
departures and a dock's arrivals, with the PAIRING thrown away. Every question
this module exists to answer lives in the joint distribution and cannot be
recovered from a marginal:

    "Riders leave Bushwick's residential docks on a Saturday afternoon.
     WHERE DO THEY ARRIVE?"

That is leakage -- the trips a neighbourhood exports to somebody else's
retail -- and it is the one thing the trip file can say that no count of
entries, taps or footfalls can. This module reads the same published trip
files phase 1 reads and aggregates them at ORIGIN NTA x DESTINATION NTA.

Everything about the FEED -- the bucket, the zips, the 2021+ Lyft schema, the
pre-2021 refusal, the New York dock-id pattern, the trailing-underscore fusion,
the dayparts, the day types, the holiday list -- is `citibike.py`'s and is
IMPORTED HERE, never restated. There is one definition of "am_peak is 06-10"
and one definition of "a New York public dock" in this codebase; a second copy
would drift and the two panels would silently stop meaning the same thing.

CARD CONTEXT ONLY, on the D76 footing (R1, owner 2026-09-15). Nothing built
from this table enters `gap_score`, `supply_ratio_vs_base`, a recommendation
grade, or the Huff lambda in `model/revenue.py`.

A TRIP IS DATED BY ITS DEPARTURE HERE, AND 034 DATES AN ARRIVAL BY ITS ARRIVAL
---------------------------------------------------------------------------
This looks like an inconsistency and is not. In 034 a start and an end are two
DIFFERENT EVENTS at two different docks, so each is dated by its own timestamp.
Here a trip is ONE event with two places, and it has to be dated once.

It is dated by `started_at`, the ORIGIN end, because the origin is what this
table partitions on: `origin_type` is a property of the origin dock,
`origin_nta` is the share denominator, and the whole object is "what this
neighbourhood's riders did". Dating by the origin is also what makes an OD cell
RECONCILE to 034's `starts` for the same dock, month, day type and daypart --
the conservation test in tests/test_citibike_od.py -- and it makes the month
the clean unit of idempotence, because the published file is KEYED on
`started_at` and therefore has no month-boundary spill on this side at all.

The cost is bounded and named: the median Citi Bike trip is about thirteen
minutes, so a trip's arrival falls in a LATER daypart than its departure only
when it leaves in the last minutes of a window. It is a real, small, stated
smear, not a hidden one.

ORIGIN TYPE IS A RATIO OF RATIOS, NOT AN AM/PM VOLUME SHARE (R2)
---------------------------------------------------------------------------
    am_pm_share = (am_peak starts / am_peak ends)
                / (pm_peak starts / pm_peak ends)

on WEEKDAY cells of `staging.citibike_station_month`, per station-month.
`> 1.2` residential, `< 0.8` destination, otherwise mixed; under
`MIN_STATION_MONTH_TRIPS` weekday trips, or a zero in any denominator,
'unknown'.

THE TICKET'S LITERAL FORM -- "am share > pm share", i.e. am volume over pm
volume > 1 -- WAS REPLACED, AND THE REASON IS MEASURED, NOT AESTHETIC. The pm
peak carries more volume than the am peak at essentially every dock in the
system, because the 15-19 window is four hours of commuting plus errands plus
leisure while 06-10 is four hours of commuting. So the literal test calls only
59 of 2,611 docks residential over the whole 2023-01..2026-08 panel (64 of the
2,225 docks active in 2024-08). That is not a neighbourhood typology; it is the
shape of the citywide diurnal curve, and using it would have left the
residential class nearly empty and quietly biased toward a handful of outer
docks.

Dividing the am start:end ratio by the pm one CANCELS the dock's overall volume
and leaves the DIRECTION of the peak flow: a dock people leave in the morning
and return to in the evening is where they sleep. On 2024-08 that types 1,204
docks residential, 586 destination, 302 mixed and 133 unknown, which is a
distribution you can do arithmetic with.

It is equivalent, at the threshold 1, to the net-flow form

    (am_s - am_e)/(am_s + am_e) - (pm_s - pm_e)/(pm_s + pm_e) > 0

because (x-1)/(x+1) is strictly increasing in x. That identity is asserted in
the tests, so a future edit cannot quietly change what the bands mean.

'unknown' IS A REAL VALUE AND NEVER A SILENT 'residential'. A quiet dock is a
dock we cannot type, and typing it anyway would put a phantom residential
origin -- and therefore a phantom leakage flow -- on exactly the blocks where
the evidence is thinnest.

DOCK -> NTA IS THE ADDRESSES' OWN RULE
---------------------------------------------------------------------------
h3 res-9 cell from the python `h3` package, looked up in `analysis.hex`. That
is literally `model/address_gaps.py`'s rule, and using the same one on both
sides is what bounds the boundary-misassignment error: a dock and an address
20 m apart across an NTA line are misassigned TOGETHER.

Note for anyone writing SQL against `analysis.hex`: `h3_index` is the
15-character STRING form. DuckDB's `h3_latlng_to_cell` returns the BIGINT form
and joins to NOTHING; `h3_latlng_to_cell_string` is the one that matches. A
silent empty join here would read downstream as a city where nobody rode.

FAIL LOUD
---------------------------------------------------------------------------
* every guard in `citibike.py` still runs (truncated month, missing calendar
  date, pre-2021 header, Jersey City file, disagreeing underscore twins);
* a month with no phase-1 station-month rows RAISES rather than typing every
  dock 'unknown' -- an untyped panel is an empty residential class, which is a
  silent zero wearing a dimension's clothes;
* a month whose docks do not map to `analysis.hex` above
  `MAX_UNMAPPED_DOCK_SHARE` RAISES (measured: 0 unmapped of 2,611);
* a month that aggregates to zero OD cells RAISES.

CAVEATS THE DATABASE CANNOT ENFORCE
---------------------------------------------------------------------------
1. RIDERS ARE NOT RESIDENTS. Citi Bike mode share is low single digits and
   skews young, male and higher-income. This is where CYCLISTS go, and the card
   wording says "riders" for that reason.
2. DOCKS ARE ENDOGENOUS TO RETAIL AND DENSITY. 133 of 262 NTAs have a dock; the
   operator builds where the trips will be, and the trips are where the retail
   is. A busy destination NTA is partly a place with many docks, which is partly
   a place with much retail -- reverse causality in a mobility costume, the D1
   error exactly. An NTA with no dock reads as no flow: that is a fact about a
   capital plan, never about the sidewalk.
3. THERE IS NO TRIP PURPOSE IN THE FEED. Evening-and-weekend is a PROXY for
   non-commute and it is the weakest joint in the chain.
4. ROUND TRIPS (2.58% measured) CARRY NO DESTINATION. Stored in their own
   column and never folded into `trips` by any consumer; the view subtracts
   them. Folding them in would inflate every NTA's own-NTA share and manufacture
   "this neighbourhood keeps its riders".
5. EVENING IS LEISURE; DAILY NEEDS ARE NOT. A pharmacy run is 18:30 on a
   Tuesday, inside the weekday pm_peak the window deliberately excludes. The
   measure is biased toward discretionary categories.
6. H3 BOUNDARY MISASSIGNMENT -- mitigated, not removed, by using one rule for
   docks and addresses.
7. CAPACITY CENSORING AND REBALANCING, inherited from phase 1: a full dock turns
   an arrival into an arrival somewhere else, and a rebalancing truck is not a
   trip.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import time

from loci.sources.cities.nyc import citibike as _cb
from loci.sources.cities.nyc.citibike import (
    CACHE_DIR,
    CitibikeError,
    assert_holidays_cover,
    assert_month_complete,
    assert_out_of_system_bounded,
    assert_underscore_twins_agree,
    audit_sql,
    day_type_case_sql,
    daypart_case_sql,
    days_by_type,
    download,
    extract_month,
    holiday_predicate_sql,
    is_ny_station_sql,
    month_bounds,
    month_range,
    plan,
    read_csv_sql,
    station_id_sql,
    twin_sql,
)

SOURCE_ID = "citibike_tripdata"          # the same feed as phase 1, no new source

#: h3 resolution of `analysis.hex`. The addresses' resolution, not a choice made
#: here (model/address_gaps.py, model/conveniences.py).
H3_RES = 9

ORIGIN_TYPES = ("residential", "mixed", "destination", "unknown")

#: R2's bands. A dock people LEAVE in the morning and RETURN to in the evening
#: is where they sleep.
RESIDENTIAL_ABOVE = 1.2
DESTINATION_BELOW = 0.8

#: Under this many weekday trips (starts + ends, all dayparts) in the
#: station-month, the ratio of ratios is four small numbers divided by each
#: other and the band it lands in is noise. Such a dock is 'unknown'.
MIN_STATION_MONTH_TRIPS = 200

#: Docks whose h3 cell is not in `analysis.hex`. Measured 2026-09-15: ZERO of
#: 2,611. A non-zero share is either a dock outside the hex frame or an h3 join
#: written against the BIGINT form of the index, and both must stop the run
#: rather than quietly shrink the panel.
MAX_UNMAPPED_DOCK_SHARE = 0.01

OD_COLUMNS = [
    "origin_nta", "destination_nta", "month", "day_type", "daypart",
    "origin_type", "trips", "member_trips", "round_trips",
    "n_origin_stations", "n_dest_stations", "ingested_at",
]

#: The leakage window, in ONE place. Mirrors
#: `analysis.address.bike_evening_ends_share_400m` (034) exactly, and the union
#: is counted ONCE -- a Saturday evening trip is one trip, not two. Weekday
#: pm_peak is deliberately absent: that is the commute home, the largest flow in
#: the system and the one that says nothing about where a rider CHOSE to go.
LEAKAGE_WINDOW_SQL = "(daypart = 'evening' OR day_type IN ('saturday', 'sunday'))"


# ------------------------------------------------------- origin type (R2)

def origin_type_sql(year: int, month: int,
                    table: str = "staging.citibike_station_month") -> str:
    """Per-dock `origin_type` for one month, from the phase-1 station-month panel.

    Weekday cells only: the ratio is about the COMMUTE direction, and a Saturday
    has no am peak to speak of. See the module docstring for why this is a ratio
    of ratios rather than the ticket's literal am/pm volume share.
    """
    first, _ = month_bounds(year, month)
    return f"""
    WITH wk AS (
        SELECT station_id,
               sum(starts) FILTER (daypart = 'am_peak') AS am_starts,
               sum(ends)   FILTER (daypart = 'am_peak') AS am_ends,
               sum(starts) FILTER (daypart = 'pm_peak') AS pm_starts,
               sum(ends)   FILTER (daypart = 'pm_peak') AS pm_ends,
               sum(starts) + sum(ends)                  AS weekday_trips
        FROM {table}
        WHERE month = DATE '{first.isoformat()}' AND day_type = 'weekday'
        GROUP BY 1
    ), r AS (
        SELECT *,
               -- nullif on EVERY denominator: a dock with no am arrivals is a
               -- dock we cannot type, not a dock with an infinite ratio.
               (am_starts::DOUBLE / nullif(am_ends, 0))
               / nullif(pm_starts::DOUBLE / nullif(pm_ends, 0), 0) AS am_pm_share
        FROM wk
    )
    SELECT station_id, am_starts, am_ends, pm_starts, pm_ends, weekday_trips,
           am_pm_share,
           CASE
               WHEN weekday_trips < {MIN_STATION_MONTH_TRIPS} THEN 'unknown'
               WHEN am_pm_share IS NULL                       THEN 'unknown'
               WHEN am_pm_share > {RESIDENTIAL_ABOVE}          THEN 'residential'
               WHEN am_pm_share < {DESTINATION_BELOW}          THEN 'destination'
               ELSE 'mixed'
           END AS origin_type
    FROM r
    """


def classify_origin_type(con, year: int, month: int,
                         table: str = "staging.citibike_station_month"):
    """(frame, report) of `origin_type` per dock for one month. READ-ONLY.

    RAISES on an empty month rather than returning an empty frame: every dock
    would then type 'unknown', the residential class would be empty, and the
    leakage view would be silently zero rows -- a silent zero wearing a
    dimension's clothes.
    """
    df = con.execute(origin_type_sql(year, month, table)).fetchdf()
    if df.empty:
        first, _ = month_bounds(year, month)
        raise CitibikeError(
            f"citibike-od: {table} holds no row for {first}. origin_type (R2) is "
            f"computed FROM the phase-1 panel, so an OD pass over this month "
            f"would type every dock 'unknown' and leave the residential class -- "
            f"the only class the leakage view reads -- empty. Run "
            f"`loci citibike ingest --start {year}-{month:02d} "
            f"--end {year}-{month:02d}` first.")
    counts = df["origin_type"].value_counts().to_dict()
    rep = {"docks": len(df),
           **{t: int(counts.get(t, 0)) for t in ORIGIN_TYPES}}
    return df[["station_id", "origin_type", "am_pm_share", "weekday_trips"]], rep


def net_swing(am_starts: float, am_ends: float,
              pm_starts: float, pm_ends: float) -> float:
    """R2's equivalent net-flow form, for the identity test.

    (am_s-am_e)/(am_s+am_e) - (pm_s-pm_e)/(pm_s+pm_e). Positive exactly when
    `am_pm_share > 1`, because (x-1)/(x+1) is strictly increasing in x. It is
    NOT the thing the bands are cut on (1.2 / 0.8 do not map to a round number
    here); it exists so the direction of the classifier has a second, independent
    statement in the codebase.
    """
    am = (am_starts - am_ends) / (am_starts + am_ends)
    pm = (pm_starts - pm_ends) / (pm_starts + pm_ends)
    return am - pm


# ----------------------------------------------------------- dock -> NTA

def dock_nta(con, year: int, month: int,
             table: str = "staging.citibike_station_month"):
    """(frame[station_id, nta_code], report) for the docks active in one month.

    THE ADDRESSES' OWN RULE: python `h3.latlng_to_cell(lat, lon, 9)` looked up in
    `analysis.hex`, exactly as `model/address_gaps.py` does it. Coordinates are
    the MODAL published position of that dock IN THAT MONTH (phase 1 stores
    them per station-month), not the roster's latest position: a dock that moved
    around a corner in 2025 must be mapped where it stood in 2024.

    Unmapped docks are COUNTED and, above `MAX_UNMAPPED_DOCK_SHARE`, RAISE. They
    are never passed through as NULL: a NULL origin_nta would become its own
    share partition and a NULL destination would make `out_of_nta` NULL, both of
    which read as a real answer.
    """
    import h3

    first, _ = month_bounds(year, month)
    docks = con.execute(f"""
        SELECT station_id, any_value(lon) AS lon, any_value(lat) AS lat
        FROM {table}
        WHERE month = DATE '{first.isoformat()}'
          AND lon IS NOT NULL AND lat IS NOT NULL
        GROUP BY 1
    """).fetchdf()
    if docks.empty:
        raise CitibikeError(
            f"citibike-od: no dock position for {first} in {table}. Run "
            f"`loci citibike ingest` for that month before the OD pass.")
    lut = dict(con.execute(
        "SELECT h3_index, nta_code FROM analysis.hex").fetchall())
    docks["h3_index"] = [h3.latlng_to_cell(la, lo, H3_RES)
                         for la, lo in zip(docks["lat"], docks["lon"])]
    docks["nta_code"] = docks["h3_index"].map(lut)
    mapped = docks[docks["nta_code"].notna()][["station_id", "nta_code"]]
    unmapped = int(len(docks) - len(mapped))
    share = unmapped / max(len(docks), 1)
    if share > MAX_UNMAPPED_DOCK_SHARE:
        bad = sorted(docks.loc[docks["nta_code"].isna(), "station_id"])[:5]
        raise CitibikeError(
            f"citibike-od: {unmapped} of {len(docks)} docks ({share:.2%}) have no "
            f"cell in analysis.hex for {first} (e.g. {bad}). Measured baseline is "
            f"ZERO unmapped of 2,611. Either the hex frame does not cover a new "
            f"part of the system, or an h3 index was built in the BIGINT form "
            f"(h3_latlng_to_cell) against a VARCHAR h3_index. Do not ingest a "
            f"panel with a hole in its geography.")
    return mapped.reset_index(drop=True), {
        "docks": len(docks), "mapped": len(mapped),
        "unmapped": unmapped,
        "ntas": int(mapped["nta_code"].nunique())}


# ------------------------------------------------------------------ the SQL

def od_month_sql(glob: str, year: int, month: int, *,
                 dock_rel: str = "_od_dock", type_rel: str = "_od_type") -> str:
    """The ONE query that turns a month of trips into NTA-pair OD cells.

    `dock_rel` is [station_id, nta_code] and `type_rel` is [station_id,
    origin_type]; both are registered frames, so the CSV scan, the geography and
    the classifier meet in a single pass.

    Both ends must be New York PUBLIC docks with published coordinates -- the
    dock-to-dock restriction. A dockless e-bike end has no dock to attribute, a
    JC/HB dock is another operator, and a SYS/shop id is a mechanic's bay; all
    three are excluded here and counted in `od_audit_sql`.

    The join to `dock_rel` is an INNER join on BOTH ends, so a trip either has
    two known NTAs or is not an OD observation at all. `type_rel` is a LEFT join
    coalescing to 'unknown', which is a real class, not a gap.
    """
    first, last = month_bounds(year, month)
    sid_s, sid_e = station_id_sql("start_station_id"), station_id_sql("end_station_id")
    dt_s, dp_s = day_type_case_sql("started_at"), daypart_case_sql("started_at")
    in_month = (f"started_at::DATE BETWEEN DATE '{first.isoformat()}' "
                f"AND DATE '{last.isoformat()}'"
                + holiday_predicate_sql("started_at", year, month))
    return f"""
    WITH t AS (
        SELECT {sid_s}  AS o_station,
               {sid_e}  AS d_station,
               {dt_s}   AS day_type,
               {dp_s}   AS daypart,
               member_casual
        FROM {read_csv_sql(glob)}
        WHERE {is_ny_station_sql('start_station_id')}
          AND {is_ny_station_sql('end_station_id')}
          AND started_at IS NOT NULL AND ended_at IS NOT NULL
          AND start_lat IS NOT NULL AND start_lng IS NOT NULL
          AND end_lat   IS NOT NULL AND end_lng   IS NOT NULL
          AND {in_month}
    )
    SELECT o.nta_code                         AS origin_nta,
           d.nta_code                         AS destination_nta,
           DATE '{first.isoformat()}'         AS month,
           t.day_type                         AS day_type,
           t.daypart                          AS daypart,
           COALESCE(ty.origin_type, 'unknown') AS origin_type,
           count(*)                                            AS trips,
           count(*) FILTER (t.member_casual = 'member')        AS member_trips,
           count(*) FILTER (t.o_station = t.d_station)         AS round_trips,
           count(DISTINCT t.o_station)                         AS n_origin_stations,
           count(DISTINCT t.d_station)                         AS n_dest_stations
    FROM t
    JOIN {dock_rel} o  ON o.station_id  = t.o_station
    JOIN {dock_rel} d  ON d.station_id  = t.d_station
    LEFT JOIN {type_rel} ty ON ty.station_id = t.o_station
    GROUP BY 1, 2, 3, 4, 5, 6
    """


def od_audit_sql(glob: str, year: int, month: int) -> str:
    """The OD-specific facts the report must state, in one pass over the file.

    Phase 1's `audit_sql` already states the file-level ones (dates, dockless,
    out-of-system, bounding box) and is run unchanged. This adds the numbers
    that only exist once a trip is treated as a PAIR: how many trips survive the
    dock-to-dock restriction, and what each exclusion class costs.
    """
    first, last = month_bounds(year, month)
    in_month = (f"started_at::DATE BETWEEN DATE '{first.isoformat()}' "
                f"AND DATE '{last.isoformat()}'"
                + holiday_predicate_sql("started_at", year, month))
    both = (f"{is_ny_station_sql('start_station_id')} "
            f"AND {is_ny_station_sql('end_station_id')}")
    coords = ("start_lat IS NOT NULL AND start_lng IS NOT NULL "
              "AND end_lat IS NOT NULL AND end_lng IS NOT NULL")
    return f"""
    SELECT count(*)                                              AS rows_in_file,
           count(*) FILTER ({in_month})                          AS trips_in_month,
           count(*) FILTER ({in_month} AND {both} AND {coords})   AS od_trips,
           count(*) FILTER ({in_month} AND {both} AND {coords}
                            AND {station_id_sql('start_station_id')}
                              = {station_id_sql('end_station_id')})
                                                                 AS od_round_trips,
           -- what the dock-to-dock restriction costs, by class, so the
           -- exclusion is auditable rather than a number that quietly shrinks.
           count(*) FILTER ({in_month}
                            AND (end_station_id IS NULL OR trim(end_station_id) = ''))
                                                                 AS dropped_dockless_end,
           count(*) FILTER ({in_month}
                            AND (start_station_id IS NULL OR trim(start_station_id) = ''))
                                                                 AS dropped_dockless_start,
           count(*) FILTER ({in_month} AND NOT ({both})
                            AND start_station_id IS NOT NULL
                            AND trim(start_station_id) <> ''
                            AND end_station_id IS NOT NULL
                            AND trim(end_station_id) <> '')       AS dropped_out_of_system,
           count(*) FILTER ({in_month} AND {both} AND NOT ({coords}))
                                                                 AS dropped_no_coords
    FROM {read_csv_sql(glob)}
    """


# --------------------------------------------------------------- the ingest

def od_month_frame(con, csv_glob: str, year: int, month: int,
                   tmp_dir: pathlib.Path, min_trips: int | None = None):
    """(OD cell frame, audit dict) for ONE month of CSVs.

    `con` is the WAREHOUSE (read is enough): it supplies the phase-1 panel that
    `origin_type` and the dock geography are derived from. The CSV scan itself
    runs in an IN-MEMORY DuckDB, for phase 1's reasons -- a multi-GB scan must
    not hold the warehouse's single writer lock, and the pass must be runnable
    against a read-only snapshot.

    Pure with respect to the warehouse: it reads and returns a frame. Every
    assertion runs here, so nothing that fails one can reach a writer.
    """
    types, type_rep = classify_origin_type(con, year, month)
    docks, dock_rep = dock_nta(con, year, month)

    mem = _cb._mem(tmp_dir)
    try:
        audit = mem.execute(audit_sql(csv_glob, year, month)).fetchdf() \
                   .to_dict("records")[0]
        audit = {k: (v.item() if hasattr(v, "item") else v) for k, v in audit.items()}
        assert_month_complete(audit, year, month, min_trips)
        assert_out_of_system_bounded(audit, year, month)
        # On the RAW ids, BEFORE station_id_sql fuses them -- afterwards the
        # evidence for the fusion is gone.
        audit["underscore_twins"] = assert_underscore_twins_agree(
            mem.execute(twin_sql(csv_glob)).fetchdf())
        od_audit = mem.execute(od_audit_sql(csv_glob, year, month)).fetchdf() \
                      .to_dict("records")[0]
        audit.update({k: (v.item() if hasattr(v, "item") else v)
                      for k, v in od_audit.items()})
        mem.register("_od_dock", docks)
        mem.register("_od_type", types[["station_id", "origin_type"]])
        try:
            df = mem.execute(od_month_sql(csv_glob, year, month)).fetchdf()
        finally:
            mem.unregister("_od_dock")
            mem.unregister("_od_type")
    finally:
        mem.close()

    if df.empty:                                          # pragma: no cover
        raise CitibikeError(
            f"citibike-od: {year}-{month:02d} aggregated to ZERO OD cells from "
            f"{audit['rows_in_file']:,} trips. Refusing to write an empty month "
            f"-- downstream that is a city where nobody rode.")

    audit.update({
        "cells": len(df),
        "nta_pairs": int(df.groupby(["origin_nta", "destination_nta"]).ngroups),
        "trips": int(df["trips"].sum()),
        "round_trips": int(df["round_trips"].sum()),
        "round_trip_share": float(df["round_trips"].sum()
                                  / max(int(df["trips"].sum()), 1)),
        "origin_types": type_rep,
        "dock_nta": dock_rep,
        "days_by_type": days_by_type(year, month),
        # Trips whose start and end are both real New York docks but whose dock
        # fell out of the hex frame. Bounded by MAX_UNMAPPED_DOCK_SHARE above;
        # stated here so the loss is named rather than inferred.
        "trips_dropped_unmapped_dock": int(audit["od_trips"] - df["trips"].sum()),
    })
    return df, audit


def write_od_month(con, df, year: int, month: int, run_at: dt.datetime) -> int:
    """DELETE-then-INSERT one month. The month is the unit of idempotence."""
    first, _ = month_bounds(year, month)
    out = df.copy()
    out["ingested_at"] = run_at
    out["month"] = first
    con.execute("DELETE FROM analysis.bike_od_leakage WHERE month = ?", [first])
    con.register("_cb_od_month", out[OD_COLUMNS])
    try:
        cols = ", ".join(OD_COLUMNS)
        # Named column lists, never SELECT * -- D72 records this exact shape
        # silently mis-mapping two type-compatible columns when a new one landed.
        con.execute(f"INSERT INTO analysis.bike_od_leakage ({cols}) "
                    f"SELECT {cols} FROM _cb_od_month")
    finally:
        con.unregister("_cb_od_month")
    return len(out)


def ingest_od(con, start: tuple[int, int] = (2023, 1),
              end: tuple[int, int] | None = None, *,
              workdir: pathlib.Path | None = None,
              refresh: bool = False, dry_run: bool = False,
              keep_csv: bool = False, skip_existing: bool = False,
              on_month=None) -> dict:
    """Download -> extract -> aggregate -> write, one calendar month at a time.

    Same shape and same reasons as phase 1's `ingest`: one month is the unit of
    work AND of idempotence, its CSVs are extracted, aggregated, written and
    DELETED before the next month is touched (peak disk is one month, ~4 GB, not
    the window's ~25 GB), and `skip_existing` makes an interrupted run resumable
    without re-reading everything.

    Per-month TIMINGS are recorded in the report (`unzip_s`, `aggregate_s`,
    `write_s`): a 44-month pass is a multi-hour commitment and the report is
    where a future session finds out what it will cost before starting it.
    """
    import shutil

    months_plan, prep = plan(start, end, refresh=refresh)
    assert_holidays_cover([(e["year"], e["month"]) for e in months_plan])
    work = pathlib.Path(workdir) if workdir else (CACHE_DIR / "_work_od")
    work.mkdir(parents=True, exist_ok=True)
    run_at = dt.datetime.now()

    have: set[dt.date] = set()
    if skip_existing:
        have = {r[0] for r in con.execute(
            "SELECT DISTINCT month FROM analysis.bike_od_leakage").fetchall()}

    months, rows = [], 0
    for e in months_plan:
        y, m = e["year"], e["month"]
        first, _ = month_bounds(y, m)
        if first in have:
            months.append({"month": f"{y}-{m:02d}", "skipped": "already ingested"})
            continue
        zip_path = download(e["key"], refresh=False)
        scratch = work / f"{y}{m:02d}"
        if scratch.exists():
            shutil.rmtree(scratch)
        try:
            t0 = time.perf_counter()
            files = extract_month(zip_path, y, m, scratch)
            t1 = time.perf_counter()
            df, audit = od_month_frame(con, str(scratch / "*.csv"), y, m, work)
            t2 = time.perf_counter()
            written = 0 if dry_run else write_od_month(con, df, y, m, run_at)
            t3 = time.perf_counter()
            rows += written
            audit.update({"month": f"{y}-{m:02d}", "key": e["key"],
                          "csv_members": len(files), "rows_written": written,
                          "unzip_s": round(t1 - t0, 1),
                          "aggregate_s": round(t2 - t1, 1),
                          "write_s": round(t3 - t2, 1)})
            months.append(audit)
            if on_month:
                on_month(audit)
        finally:
            if scratch.exists() and not keep_csv:
                shutil.rmtree(scratch, ignore_errors=True)

    done = [x for x in months if "skipped" not in x]
    return {**prep, "run_at": run_at.isoformat(timespec="seconds"),
            "rows_written": rows, "months_detail": months,
            "months_ingested": len(done),
            "trips_in_files": sum(x.get("rows_in_file", 0) for x in done),
            "od_trips": sum(x.get("od_trips", 0) for x in done),
            "round_trips": sum(x.get("round_trips", 0) for x in done),
            "dropped_dockless_end": sum(x.get("dropped_dockless_end", 0) for x in done),
            "dropped_out_of_system": sum(x.get("dropped_out_of_system", 0) for x in done),
            "trips_dropped_unmapped_dock":
                sum(x.get("trips_dropped_unmapped_dock", 0) for x in done),
            "seconds": round(sum(x.get("unzip_s", 0) + x.get("aggregate_s", 0)
                                 + x.get("write_s", 0) for x in done), 1)}


# -------------------------------------------------------------- the read-back

OD_VALIDATION_SQL = """
-- Proves on the WAREHOUSE (not on the frames this run built):
--   1. row counts and distinct NTA pairs per month, so a month that silently
--      halved is visible against its neighbours;
--   2. the panel is CONTIGUOUS -- n_months equals the month span;
--   3. round_trips never exceeds trips (they are a SUBSET stored separately,
--      and a round_trip_share above 1 would mean the diagonal was double
--      counted -- the edge-mirroring bug this project has been bitten by);
--   4. member_trips never exceeds trips;
--   5. the origin_type mix, because an empty 'residential' class is the failure
--      mode that turns the whole leakage view into zero rows.
SELECT month,
       count(*)                                          AS cells,
       count(DISTINCT origin_nta || '>' || destination_nta) AS nta_pairs,
       count(DISTINCT origin_nta)                        AS origin_ntas,
       sum(trips)                                        AS trips,
       sum(round_trips)                                  AS round_trips,
       round(100.0 * sum(round_trips) / nullif(sum(trips), 0), 2)
                                                         AS round_trip_pct,
       round(100.0 * sum(member_trips) / nullif(sum(trips), 0), 2)
                                                         AS member_pct,
       sum(trips) FILTER (origin_type = 'residential')    AS residential_trips,
       sum(trips) FILTER (origin_type = 'destination')    AS destination_trips,
       sum(trips) FILTER (origin_type = 'unknown')        AS unknown_trips,
       sum(trips) FILTER (daypart = 'evening'
                          OR day_type IN ('saturday', 'sunday')) AS window_trips,
       max(CASE WHEN round_trips > trips THEN 1 ELSE 0 END)      AS bad_round,
       max(CASE WHEN member_trips > trips THEN 1 ELSE 0 END)     AS bad_member
FROM analysis.bike_od_leakage
GROUP BY ROLLUP(month)
ORDER BY month NULLS LAST
"""

#: The arithmetic proof that OD did not invent or lose trips. An OD cell's
#: trips, summed over every destination, must equal phase 1's `starts` for that
#: origin dock, month, day type and daypart -- NET of the exclusions OD makes and
#: phase 1 does not (a dockless end, a Jersey City end, an end with no
#: coordinate). `od_trips - phase1_starts` is therefore <= 0 and equals exactly
#: the counted exclusions.
OD_CONSERVATION_SQL = """
WITH od AS (
    SELECT month, day_type, daypart, sum(trips) AS od_trips
    FROM analysis.bike_od_leakage GROUP BY 1, 2, 3
), p1 AS (
    SELECT month, day_type, daypart, sum(starts) AS p1_starts
    FROM staging.citibike_station_month GROUP BY 1, 2, 3
)
SELECT month, day_type, daypart, od_trips, p1_starts,
       p1_starts - od_trips                                       AS excluded,
       round(100.0 * (p1_starts - od_trips) / nullif(p1_starts, 0), 3)
                                                                  AS excluded_pct
FROM od JOIN p1 USING (month, day_type, daypart)
ORDER BY month, day_type, daypart
"""


__all__ = [
    "DESTINATION_BELOW",
    "H3_RES",
    "LEAKAGE_WINDOW_SQL",
    "MAX_UNMAPPED_DOCK_SHARE",
    "MIN_STATION_MONTH_TRIPS",
    "OD_COLUMNS",
    "OD_CONSERVATION_SQL",
    "OD_VALIDATION_SQL",
    "ORIGIN_TYPES",
    "RESIDENTIAL_ABOVE",
    "SOURCE_ID",
    "CitibikeError",
    "classify_origin_type",
    "dock_nta",
    "ingest_od",
    "month_range",
    "net_swing",
    "od_audit_sql",
    "od_month_frame",
    "od_month_sql",
    "origin_type_sql",
    "write_od_month",
]
