"""Loci command line.

    loci init-db
    loci check-sources [--urls]
    loci check-questions
    loci check-tickets [--hook]
    loci reach-table [--quantile 0.80] [--write]        (read-only unless --write)
    loci spacing                                        (read-only)
    loci conveniences [--borough MN]                    (read-only, D58: queries
                                                        analysis.address_category)
    loci address-gaps [--borough ALL] [--reach tiers|p80] [--supply-set principled]
                      [--limit 0] [--dry-run]
    loci address-demand [--borough MNBK|MN|BK|ALL] [--dry-run]  (D49 annotation, GTM-110)
    loci address-access [--boroughs MN,BK] [--months 3] [--complex-point] [--dry-run]
                                                       (transit_entries_400m + jobs_400m
                                                        beside homes_400m; UPDATE-only,
                                                        never a filter on the screen)
    loci age-fit fit   [--category <registry category>|all] [--boroughs MN,BK] [--dry-run]
                                                       (D63/D64: re-estimate the
                                                        supply-revealed age curves;
                                                        exits non-zero on the F2 gate)
    loci age-fit apply [--category <registry category>|all] [--boroughs MN,BK] [--dry-run]
                                                       (D63/D64: age_fit on each fitted
                                                        category's rows, gap_score_fit
                                                        beside gap_score)
    loci anchor-coverage [--borough Manhattan,Brooklyn] [--write]   (D52 step 1)
    loci ingest --source overture_places --city nyc [--dry-run]
    loci citywide-income [--refresh]                     (ACS B19025/B11001, read-only)
    loci address-demographics [--dry-run]               (address-grain ACS, D56)
    loci ingest-zbp [--year 2023] [--dry-run]           (validation only)
    loci ingest-ll84 [--dry-run]                        (LL84 in-building laundry, D51(d))
    loci ingest-alcohol [--limit N] [--dry-run]         (SLA alcohol overlay, not a category)
    loci ingest-dcwp [--limit N] [--apply]              (DCWP retail-laundry anchor, D55;
                                                        defaults to pending/dry, --apply promotes)
    loci ingest-nys-medicaid-pharmacy [--limit N] [--apply]
                                                       (NYS Medicaid retail-pharmacy
                                                        anchor; defaults to pending/dry,
                                                        --apply promotes)
    loci zbp-compare [--year] [--by-source] [--supply-set all|principled|corroborated|
                     registry_anchored|active|active_corroborated] [--supply-sets]
                     [--borough Manhattan,Brooklyn]
    loci grid   --city nyc --resolution 9
    loci score  [--limit-min 30] [--supply-set principled]
    loci export-webmap [--boroughs MN,BK] [--supply-set principled] [--dry-run]

No analysis logic lives here; commands are thin wrappers over the packages.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from loci import db as locidb
from loci import questions, registry
from loci import sources as source_adapters
from loci import tickets as tickets_mod
from loci.score.supply import DEFAULT_SUPPLY_SET as SUPPLY_DEFAULT

REPO_ROOT = Path(__file__).resolve().parents[2]

# GOOGLE_PLACES_KEY etc. live in loci/.env, but nothing was loading it — `loci
# validate --run` failed with "GOOGLE_PLACES_KEY is not set" even with a
# populated .env. override=False: a real environment variable always wins over
# the file.
load_dotenv(REPO_ROOT / ".env", override=False)

app = typer.Typer(add_completion=False, help=__doc__)
console = Console()


@app.command(name="init-db")
def init_db() -> None:
    """Create the DuckDB database and apply the schema. Idempotent."""
    con = locidb.connect()
    locidb.init_schema(con)
    n = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema IN ('staging', 'analysis')"
    ).fetchone()[0]
    console.print(f"[green]ok[/] {locidb.DEFAULT_PATH} — {n} tables in staging/analysis")


@app.command()
def sources(role: str = typer.Option(None, help="Filter by role.")) -> None:
    """List the data source registry (loci/registry.yaml)."""
    reg = registry.load()
    table = Table(title=f"Loci sources — verified {reg['verified_on']}")
    for col in ("id", "tier", "role", "geography", "cost", "status"):
        table.add_column(col)
    for s in reg["sources"]:
        if role and s["role"] != role:
            continue
        cost = s.get("cost", {})
        cost_s = "$0" if cost.get("amount") == 0 else f"${cost.get('amount')}/{cost.get('unit')}"
        table.add_row(s["id"], s["tier"], s["role"], str(s.get("geography", "-")),
                      cost_s, s["status"])
    console.print(table)


@app.command(name="check-sources")
def check_sources(urls: bool = typer.Option(False, "--urls", help="Also check every URL resolves.")) -> None:
    """Validate the registry and assert it agrees with docs/CONTEXT.md."""
    errors = registry.validate(check_urls=urls)
    for e in errors:
        console.print(f"[red]FAIL[/] {e}")
    raise typer.Exit(1 if errors else 0)


@app.command(name="check-questions")
def check_questions() -> None:
    """Validate docs/QUESTIONS.md: statuses, cited tickets exist, P1–P3 each claimed."""
    errors, warnings = questions.validate()
    for w in warnings:
        console.print(f"[yellow]WARN[/] {w}")
    for e in errors:
        console.print(f"[red]FAIL[/] {e}")
    raise typer.Exit(1 if errors else 0)


@app.command(name="check-tickets")
def check_tickets(
    hook: bool = typer.Option(False, "--hook", help="Emit one line of JSON for the Claude Code Stop hook."),
) -> None:
    """Assert every CHECKPOINT decision since D29 has a ticket (or a recorded ruling)."""
    import json as _json

    from loci import decisions as decisions_mod

    rows, unpushed = decisions_mod.run()
    uncovered = [r for r in rows if r.how == "uncovered"]

    if hook:
        if uncovered or unpushed:
            parts = []
            if uncovered:
                ids = ", ".join(r.decision.id for r in uncovered)
                parts.append(
                    f"CHECKPOINT decision(s) {ids} have no Linear ticket. Add a definition to "
                    "src/loci/tickets.py (title = the work, description = the reasoning, ending "
                    "`Done <date> (CHECKPOINT <id>)`), or add the id to tickets.RULINGS with a "
                    "one-line reason it needs none, then run `loci gen-tickets`."
                )
            if unpushed:
                titles = "; ".join(t for t, _ in unpushed)
                parts.append(
                    f"{len(unpushed)} ticket definition(s) not pushed to Linear: {titles}. "
                    "Create them in Linear and write the GTM id back into the description."
                )
            print(_json.dumps({"decision": "block", "reason": " ".join(parts)}))
        else:
            print(_json.dumps({"systemMessage": f"tickets: all {len(rows)} decisions covered"}))
        raise typer.Exit(0)

    table = Table(title=f"Decision coverage since {tickets_mod.TICKET_COVERAGE_SINCE}")
    table.add_column("Decision")
    table.add_column("Date")
    table.add_column("Covered by")
    table.add_column("Detail")
    style = {"ticket": "green", "ruling": "cyan", "uncovered": "red"}
    for r in rows:
        detail = r.detail if r.how == "ruling" else "; ".join(r.tickets[:2])
        if r.how == "ticket" and len(r.tickets) > 2:
            detail += f" (+{len(r.tickets) - 2} more)"
        table.add_row(r.decision.id, r.decision.date,
                      f"[{style[r.how]}]{r.how}[/]", detail[:80] or r.decision.title[:80])
    console.print(table)

    for t, cites in unpushed:
        console.print(f"[yellow]UNPUSHED[/] {t} — covers {cites}, no GTM id")
    if uncovered:
        console.print(f"[red]FAIL[/] {len(uncovered)} uncovered: "
                      + ", ".join(r.decision.id for r in uncovered))
    else:
        console.print(f"[green]ok[/] {len(rows)} decisions covered")
    raise typer.Exit(1 if (uncovered or unpushed) else 0)


@app.command(name="gen-tickets")
def gen_tickets() -> None:
    """Regenerate docs/TICKETS.md and the Linear export files."""
    n, m, pts = tickets_mod.generate()
    console.print(f"[green]ok[/] {n} issues across {m} milestones, {pts} points")


@app.command()
def ignition(
    lag: bool = typer.Option(False, "--lag", help="Catalyst→change timing study instead of the screen."),
) -> None:
    """Pre-ignition screen (Axis 4b), or --lag for the historical catalyst→change lag study."""
    from loci.model import ignition as ig
    ig.lag() if lag else ig.run()


@app.command()
def premium() -> None:
    """Axis 3: where a premium destination amenity (spa, padel, boutique fitness) could open."""
    from loci.model import premium as pr
    pr.run()


@app.command()
def ingest(
    source: str = typer.Option(..., help="Source id from the registry."),
    city: str = typer.Option("nyc"),
    limit: int = typer.Option(None, help="Cap records fetched (for smoke tests)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch + normalize; write nothing."),
) -> None:
    """Land a source and normalize it into staging.poi."""
    reg = registry.load()
    match = next((s for s in reg["sources"] if s["id"] == source), None)
    if match is None:
        ids = ", ".join(s["id"] for s in reg["sources"])
        raise typer.BadParameter(f"unknown source '{source}'. known: {ids}")
    if match["status"] == "excluded":
        console.print(f"[yellow]{source} is deliberately excluded:[/] {match['exclusion_reason']}")
        raise typer.Exit(0)

    console.print(f"[bold]{match['name']}[/]  ({match.get('cost')})")

    adapter = source_adapters.get_adapter(source)
    if adapter is None:
        console.print(f"[yellow]no adapter built yet for {source}.[/] "
                      f"bias to watch: {match.get('bias', '-').strip()}")
        raise typer.Exit(0)

    if dry_run:
        recs = adapter.load(None, limit=limit, dry_run=True)
        from collections import Counter
        by_cat = Counter(r.category for r in recs)
        console.print(f"[dim]--dry-run:[/] {len(recs)} records, no write. by category: {dict(by_cat)}")
        raise typer.Exit(0)

    con = locidb.connect()
    locidb.init_schema(con)
    recs = adapter.load(con, limit=limit)
    n = con.execute("SELECT count(*) FROM staging.poi WHERE source_id = ?", [source]).fetchone()[0]
    console.print(f"[green]ok[/] {len(recs)} normalized, {n} rows in staging.poi for {source}")


@app.command()
def grid(city: str = "nyc", resolution: int = 9) -> None:
    """Build the shoreline-clipped H3 grid (ACS interpolation is GTM-24)."""
    from loci.grid.build import build_grid
    con = locidb.connect()
    locidb.init_schema(con)
    n = build_grid(con, res=resolution)
    stats = con.execute("""SELECT borough, count(*), round(avg(land_fraction),3)
                           FROM analysis.hex GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    console.print(f"[green]ok[/] {n} hexes")
    for b, c, lf in stats:
        console.print(f"  {b or '(unlabelled)':16} {c:>5}  avg land_fraction {lf}")


@app.command()
def controls(source: str = typer.Option(
        "pluto", help="Control source: pluto | mta | mta-ridership.")) -> None:
    """Build analysis.hex_controls from a control source.

    `mta-ridership` fills `subway_riders_2024`, which was NULL on all 8,321
    rows because nothing ever wrote it (D63): the column landed ahead of its
    loader. It costs twelve requests to data.ny.gov (~4 min) -- the hourly feed
    is ~110M rows and a whole-year server-side aggregation times out, so it is
    chunked by calendar month.
    """
    con = locidb.connect()
    locidb.init_schema(con)
    if source == "mta-ridership":
        from loci.grid.mta import RIDERSHIP_YEAR, build_subway_ridership
        console.print(f"[dim]summing {RIDERSHIP_YEAR} subway ridership by station "
                      f"complex, month by month (12 requests)…[/]")
        n, complexes = build_subway_ridership(con)
        console.print(f"[green]ok[/] subway_riders_2024 for {n:,} hexes "
                      f"from {complexes:,} station complexes")
    elif source == "pluto":
        from loci.grid.pluto import build_pluto_controls
        n = build_pluto_controls(con)
        console.print(f"[green]ok[/] PLUTO controls for {n} hexes")
    elif source == "mta":
        from loci.grid.mta import build_mta_controls
        n = build_mta_controls(con)
        console.print(f"[green]ok[/] MTA transit controls for {n} hexes")
    else:
        raise typer.BadParameter(f"unknown control source '{source}'")


@app.command()
def acs() -> None:
    """Interpolate ACS demographics onto the grid (dasymetric via PLUTO)."""
    from loci.grid.acs import build_acs
    con = locidb.connect()
    locidb.init_schema(con)
    n = build_acs(con)
    console.print(f"[green]ok[/] demographics for {n} hexes")


@app.command(name="address-demographics")
def address_demographics_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print the summary; write nothing."),
) -> None:
    """Address-level ACS demographics (D56): income, tenure, and vehicle
    ownership per residential PLUTO lot, taken DIRECTLY from the lot's 2020
    census tract (no apportionment -- unlike `acs`, which interpolates onto
    hexes because a hex can straddle several tracts, an address sits in
    exactly one). Replaces analysis.hex_demographics as the demographic
    carrier for the address screen (D38/D56); hex_demographics is frozen
    history. Writes analysis.address_demographics unless --dry-run."""
    import pandas as pd

    from loci.grid.acs import CITYWIDE_INCOME_CACHE, load_citywide_mean_hh_income
    from loci.model import address_demographics as ad
    from loci.sources.cities.nyc.addresses import BOROCODE, load_residential_addresses

    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    frames = []
    for boro in BOROCODE:
        d = load_residential_addresses(con, boro)
        d["borough"] = boro
        frames.append(d)
    addresses_df = pd.concat(frames, ignore_index=True)
    console.print(f"[dim]{len(addresses_df):,} residential addresses (all 5 boroughs); "
                  f"assigning 2020 census tracts + ACS 2023 5-year...[/]")

    df = ad.build_address_demographics(con, addresses_df)

    if dry_run:
        console.print("[dim]--dry-run: computed, nothing written.[/]")
    else:
        n = ad.write_address_demographics(con, df)
        console.print(f"[green]ok[/] wrote {n:,} rows -> analysis.address_demographics")

    # D49's citywide-income cache is the 0.80x-mean threshold this report
    # checks addresses against; if it's missing, run `loci citywide-income`
    # first rather than silently skipping that stat.
    threshold = None
    if CITYWIDE_INCOME_CACHE.exists():
        rec = load_citywide_mean_hh_income()
        threshold = 0.80 * rec["mean_hh_income"]

    summary = ad.summarize(df, addresses_df, income_threshold=threshold)
    console.print(f"{summary['n_addresses']:,} addresses, "
                  f"{summary['n_with_tract']:,} with a tract "
                  f"({100*summary['tract_assignment_rate']:.4f}%)")
    console.print(f"  citywide median household income   ${summary['citywide_median_income']:,.0f}")
    console.print(f"  MN+BK median household income       ${summary['mnbk_median_income']:,.0f}")
    console.print(f"  citywide median zero-vehicle-HH share {summary['citywide_median_zero_vehicle_hh_share']:.1%}")
    console.print(f"  MN+BK median zero-vehicle-HH share     {summary['mnbk_median_zero_vehicle_hh_share']:.1%}")
    if summary.get("median_income_moe_share") is not None:
        console.print(f"  median income MOE as share of estimate {summary['median_income_moe_share']:.1%}")
    if threshold is not None and summary.get("share_within_one_moe_of_threshold") is not None:
        console.print(f"  income threshold (0.80x citywide MEAN, D49) ${threshold:,.0f}")
        console.print(f"  share of addresses within 1 MOE of that threshold "
                      f"{summary['share_within_one_moe_of_threshold']:.1%}")
    elif threshold is None:
        console.print("[yellow]citywide mean income cache not found -- run `loci citywide-income` "
                      "for the threshold stat[/]")


@app.command(name="citywide-income")
def citywide_income(refresh: bool = typer.Option(False, "--refresh",
                                                 help="Re-fetch from ACS instead of reading the cache.")) -> None:
    """Citywide MEAN household income (ACS B19025/B11001) — the demand-caveat denominator."""
    from loci.grid.acs import load_citywide_mean_hh_income
    rec = load_citywide_mean_hh_income(refresh=refresh)
    from loci.demand import load_low_income_cutoff
    cut = load_low_income_cutoff()
    console.print(f"[green]ok[/] ACS {rec['acs_year']} 5-year citywide mean household income "
                  f"${rec['mean_hh_income']:,.0f} (±${rec['mean_hh_income_moe']:,.0f}, 90%) "
                  f"over {rec['households']:,.0f} households")
    console.print(f"      low-income cutoff = {cut:.0%} × mean = ${cut * rec['mean_hh_income']:,.0f}")
    console.print(f"      {rec['source']}")


@app.command(name="ingest-zbp")
def ingest_zbp(
    year: int = typer.Option(None, help="CBP vintage; defaults to census_zbp.DEFAULT_YEAR (latest published)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request plan and row estimate; write nothing."),
) -> None:
    """Land Census ZBP/CBP establishment counts for NYC ZIPs (VALIDATION ONLY --
    never feeds the gap flag; see registry.yaml `census_zbp`)."""
    from loci.sources.universal import census_zbp

    y = year or census_zbp.DEFAULT_YEAR
    con = locidb.connect()
    locidb.init_schema(con)

    if dry_run:
        plan = census_zbp.request_plan(con, y)
        console.print(f"[dim]--dry-run:[/] year={plan['year']}  n_zips={plan['n_zips']}")
        console.print(f"  GET {plan['url']}")
        console.print(f"    get={plan['get']}")
        console.print(f"    for={plan['for']}")
        console.print("[dim]fetching to compute a row estimate (no write)...[/]")
        summary = census_zbp.build_zip_establishments(con, y, dry_run=True)
        console.print(f"[green]ok[/] would write {summary['rows_finest_level']} rows "
                       f"({summary['n_zips_returned']} zips x {summary['n_naics_codes']} NAICS codes, "
                       f"6-digit level only; {summary['rows_fetched_all_levels']} rows fetched across all NAICS levels)")
        raise typer.Exit(0)

    summary = census_zbp.build_zip_establishments(con, y)
    console.print(f"[green]ok[/] {summary['rows_written']} rows -> analysis.zip_establishments "
                   f"(year={y}, {summary['n_zips_returned']} zips, {summary['n_naics_codes']} NAICS codes)")
    n_cat = census_zbp.build_zip_category_establishments(con, y)
    console.print(f"[green]ok[/] {n_cat} rows -> analysis.zip_category_establishments")


@app.command(name="ingest-ll84")
def ingest_ll84(
    limit: int = typer.Option(None, help="Cap rows fetched PER VINTAGE (smoke tests)."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Resolve fields and count per vintage; write nothing."),
) -> None:
    """Land LL84/LL133 in-building laundry hookups as a BBL-keyed supply
    annotation (D51(d)). Attribute source -- nothing reaches staging.poi, and
    nothing in score/ or model/ reads the result."""
    from loci.sources.cities.nyc import ll84_laundry as ll84

    con = None if dry_run else locidb.connect()
    if con is not None:
        locidb.init_schema(con)

    report = ll84.build_ll84_laundry(con, limit=limit, dry_run=dry_run)
    written = report.pop("_written", None)

    t = Table(title="LL84 laundry hookups by vintage")
    for c in ("dataset", "rows", "answered", "bbl unparsable", "multi-BBL", "exploded",
              "common-area fieldName", "in-unit fieldName"):
        t.add_column(c, justify="right" if c not in ("dataset",) else "left")
    for did, s in report.items():
        t.add_row(did, f"{s['rows']:,}", f"{s['answered']:,}",
                  f"{s['bbl_unparsable']:,}", f"{s['multi_bbl_rows']:,}",
                  f"{s['exploded_rows']:,}", s["resolved_common"], s["resolved_in_unit"])
    console.print(t)

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)

    console.print(f"[green]ok[/] {written['rows']:,} rows -> staging.ll84_laundry")
    n = ll84.build_address_laundry(con)
    console.print(f"[green]ok[/] {n:,} BBLs -> analysis.address_laundry_evidence (source=ll84)")
    row = con.execute("""
        SELECT count(*) FILTER (WHERE laundry_measured),
               count(*) FILTER (WHERE has_common_laundry),
               count(*) FILTER (WHERE has_in_unit_laundry),
               count(*) FILTER (WHERE n_vintages_disagree > 0)
        FROM analysis.address_laundry_evidence WHERE source = 'll84'""").fetchone()
    console.print(f"      measured {row[0]:,}  common-area yes {row[1]:,}  "
                  f"in-unit yes {row[2]:,}  vintages disagree {row[3]:,}")


@app.command(name="ingest-listings")
def ingest_listings(
    borough: str = typer.Option("BK", help="Borough code (BK/MN)."),
    neighborhood: str = typer.Option(None, help="Restrict to one NTA name."),
    limit: int = typer.Option(50, help="Addresses to fetch, highest gap_score first."),
    min_units: int = typer.Option(0, help="Minimum residential units on the lot."),
    max_calls: int = typer.Option(200, help="HARD call cap; raises at the cap. Ceiling 40,000."),
    pace: float = typer.Option(0.0, help="Seconds to sleep between Tavily calls. Use >0 for "
                                         "anything larger than one NTA: the Bay Ridge pilot's "
                                         "unpaced extract failure rate rose 23%% -> 82%% across "
                                         "the run and Tavily bills failed URLs."),
    cooldown: float = typer.Option(0.0, help="Seconds to pause after an extract call that "
                                             "rendered NOTHING (the signature of throttling). "
                                             "The pace also doubles, then decays back."),
    sweep: bool = typer.Option(False, "--sweep",
                               help="Every laundry lead in --boroughs, ordered >=6 units first, "
                                    "then 3-5, then 1-2 (yield is size-selected). Ignores "
                                    "--neighborhood/--limit; --min-units still applies."),
    boroughs: str = typer.Option("MN,BK", help="--sweep only: comma-separated borough codes."),
    sink: str = typer.Option(None, help="Write results to parquet part files in this directory "
                                        "instead of the database. REQUIRED for a long run: "
                                        "DuckDB is single-writer and a sweep must not hold the "
                                        "file lock for hours. Land it later with --merge."),
    part_every: int = typer.Option(25, help="--sink: addresses per part file."),
    merge: str = typer.Option(None, help="Land a --sink directory into staging.listings and "
                                         "rebuild the rollup, in ONE short write transaction. "
                                         "Fetches nothing."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Print the call plan and estimated credits. NO network calls."),
) -> None:
    """Land ADVERTISED in-building laundry from StreetEasy listing pages as a
    BBL-keyed annotation (D51(d)). Attribute source -- nothing reaches
    staging.poi, and nothing in score/ or model/ reads the result.

    Laundry booleans are TRUE or NULL, never FALSE: a listing that omits
    laundry is not evidence the building lacks it (42 Carlton Ave: 1 of 4
    listings mentions the laundry room). See sql/005_listings_laundry.sql.
    """
    from loci.sources.cities.nyc import listings as L

    if merge:
        con = locidb.connect()
        locidb.init_schema(con)
        out = L.merge_sink(con, merge)
        t = Table(title=f"merged {merge}")
        t.add_column("field"); t.add_column("value", justify="right")
        for k, v in out.items():
            t.add_row(k, f"{v:,}" if isinstance(v, int) else str(v))
        console.print(t)
        raise typer.Exit(0)

    # The sweep opens the database READ-ONLY for target selection and closes it
    # before the first fetch: DuckDB allows one writer, and other agents write
    # to this file while a multi-hour sweep runs.
    read_only = bool(sink) or dry_run
    con = locidb.connect(read_only=read_only)
    if not read_only:
        locidb.init_schema(con)
    if sweep:
        targets = L.select_sweep_targets(
            con, boroughs=tuple(b.strip().upper() for b in boroughs.split(",")),
            min_units=max(min_units, 1))
    else:
        targets = L.select_targets(con, borough=borough, neighborhood=neighborhood,
                                   limit=limit, min_units=min_units)
    if sink and not dry_run:
        done = L.fetched_bbls(sink) if Path(sink).exists() else set()
        searched = L.searched_addresses(sink) if Path(sink).exists() else set()
        if done or searched:
            n0 = len(targets)
            targets = [t for t in targets if str(t["bbl"]) not in done
                       and L._addr_key(t["address"]) not in searched]
            console.print(f"[dim]resume:[/] {n0 - len(targets):,} addresses already in "
                          f"{sink}, {len(targets):,} left")
        con.close()
        con = locidb.connect(":memory:")     # spatial arithmetic only; no file lock
    if not targets:
        console.print("[yellow]no laundry-lead addresses matched[/]")
        raise typer.Exit(1)

    if dry_run:
        p = L.plan(targets)
        t = Table(title=f"ingest-listings plan — {borough}"
                        + (f" / {neighborhood}" if neighborhood else ""))
        t.add_column("field"); t.add_column("value", justify="right")
        for k, v in p.items():
            t.add_row(k, f"{v:,}" if isinstance(v, int) else str(v))
        console.print(t)
        for x in targets[:5]:
            console.print(f"  [dim]{x['bbl']}[/] {x['address']:<28} "
                          f"{L.candidate_urls(x['address'], x['borough'])[0]}")
        console.print(f"[dim]--dry-run:[/] no network calls, nothing written. "
                      f"Cap would be --max-calls {max_calls}.")
        raise typer.Exit(0)

    report = L.build_listings(con, targets, max_calls=max_calls, pace_s=pace,
                              cooldown_s=cooldown, sink_dir=sink,
                              part_every=part_every,
                              log=(print if sink else None))
    if sink:
        console.print(f"[green]fetch done[/] run {report['run_id']} -> {sink}")
        console.print(f"[dim]nothing written to the database yet. Land it with:[/] "
                      f"loci ingest-listings --merge {sink}")
        for k in ("addresses", "searched", "addresses_with_unit_pages",
                  "fallback_addresses", "fallback_rejected", "unit_pages",
                  "parsed", "with_amenities", "urls_failed", "backoffs",
                  "rows_written", "calls", "credits"):
            console.print(f"      {k:<26} {report.get(k)}")
        raise typer.Exit(0)

    n = L.build_address_listing_laundry(con)

    t = Table(title="StreetEasy advertised laundry")
    t.add_column("metric"); t.add_column("n", justify="right")
    for k in ("addresses", "searched", "unit_pages", "parsed", "with_amenities",
              "urls_failed", "rows_written", "calls", "credits"):
        v = report.get(k)
        t.add_row(k, f"{v:,.0f}" if isinstance(v, (int, float)) else str(v))
    console.print(t)
    if report.get("budget_stopped"):
        console.print("[yellow]stopped early: call cap reached[/]")
    console.print(f"[green]ok[/] {n:,} BBLs -> analysis.address_laundry_evidence "
                  f"(source=listing, run {report['run_id']})")
    row = con.execute("""
        SELECT count(*) FILTER (WHERE n_with_amenities > 0),
               count(*) FILTER (WHERE any_laundry_advertised),
               sum(n_in_building), sum(n_in_unit), sum(n_silent), sum(n_none)
        FROM analysis.address_laundry_evidence WHERE source = 'listing'""").fetchone()
    console.print(f"      BBLs with amenity data {row[0]:,}  laundry advertised {row[1]:,}  "
                  f"in-building {row[2] or 0:,}  in-unit {row[3] or 0:,}  "
                  f"silent {row[4] or 0:,}  explicit-none {row[5] or 0:,}")
    console.print("[dim]silent != none — a listing that omits laundry is not evidence "
                  "the building lacks it.[/]")


@app.command(name="zbp-compare")
def zbp_compare(
    year: int = typer.Option(None, help="Vintage to compare against; defaults to the latest ingested."),
    by_source: bool = typer.Option(False, "--by-source",
                                    help="Also build analysis.zip_coverage_by_source and print the "
                                         "per-category x per-source overcount attribution (QUESTIONS.md M9)."),
    supply_set: str = typer.Option("all", "--supply-set",
                                    help="Which supply set to count on the Loci side: all | principled "
                                         "| corroborated | registry_anchored | active | "
                                         "active_corroborated (sql/003_supply_sets.sql, "
                                         "sql/006_principled_supply.sql). "
                                         "Anything but 'all' computes without persisting."),
    supply_sets: bool = typer.Option(False, "--supply-sets",
                                     help="Print the category x supply-set comparison table (D47). "
                                          "Writes nothing."),
    borough: str = typer.Option(None, "--borough",
                                help="Comma-separated borough names to restrict to, e.g. "
                                     "'Manhattan,Brooklyn' (D48 scope). A ZIP is assigned whole to "
                                     "its majority borough -- ZBP counts cannot be split."),
) -> None:
    """Compare Loci's deduped POI counts to ZBP establishment counts, per
    category and NYC ZIP (VALIDATION ONLY -- see registry.yaml `census_zbp`)."""
    from loci.model.zbp_compare import run_comparison

    boroughs = tuple(b.strip() for b in borough.split(",")) if borough else None
    con = locidb.connect()
    locidb.init_schema(con)
    run_comparison(con, year=year, console=console, by_source=by_source,
                   supply_set=supply_set, boroughs=boroughs, supply_sets=supply_sets)


@app.command(name="anchor-coverage")
def anchor_coverage(
    borough: str = typer.Option("Manhattan,Brooklyn", "--borough",
                                help="Comma-separated borough names (D48 scope). 'ALL' for citywide."),
    year: int = typer.Option(None, help="ZBP vintage; defaults to the latest ingested."),
    write: bool = typer.Option(False, "--write",
                               help="Persist analysis.category_anchor. Without this the "
                                    "measurement is printed and nothing is written."),
) -> None:
    """D52 step 1: measure, per category, what share of the Census ZBP
    establishment count is accounted for by canonical POIs whose dedup cluster
    carries a REGISTRY-source member. A source only earns the right to veto an
    uncorroborated aggregator record where that coverage reaches
    score/supply.ANCHOR_COVERAGE_MIN -- a registry label is not evidence the
    registry was actually loaded and is dense enough."""
    from loci.score.supply import (
        ANCHOR_COVERAGE_MIN,
        build_category_anchor,
        measure_anchor_coverage,
    )

    boroughs = None if borough.upper() == "ALL" else tuple(b.strip() for b in borough.split(","))
    con = locidb.connect(read_only=not write)
    if write:
        locidb.init_schema(con)
        n = build_category_anchor(con, year=year, boroughs=boroughs)
        df = con.execute("SELECT * FROM analysis.category_anchor ORDER BY category").df()
        console.print(f"[green]ok[/] wrote {n} rows -> analysis.category_anchor")
    else:
        df = measure_anchor_coverage(con, year=year, boroughs=boroughs).sort_values("category")

    console.print(f"anchor coverage (threshold {ANCHOR_COVERAGE_MIN:.2f}, "
                  f"boroughs={borough}):")
    console.print(f"{'category':14} {'anchor_poi':>10} {'zbp':>7} {'coverage':>9} "
                  f"{'qualifies':>10}  anchor_sources")
    for _, r in df.iterrows():
        cov = r["anchor_coverage"]
        cov_s = "n/a" if cov != cov else f"{cov:.2f}"     # NaN-safe
        console.print(f"{r['category']:14} {int(r['anchor_poi']):>10} {int(r['zbp_estab']):>7} "
                      f"{cov_s:>9} {bool(r['qualifies'])!s:>10}  {r['anchor_sources'] or '-'}",
                      emoji=False)


@app.command()
def dedup() -> None:
    """Cross-source entity resolution: mark canonical POIs (GTM-20)."""
    from loci.score.dedup import build_dedup
    con = locidb.connect()
    locidb.init_schema(con)
    report = build_dedup(con)
    raw = sum(r for r, _ in report.values())
    canon = sum(c for _, c in report.values())
    console.print(f"[green]ok[/] {raw} POIs -> {canon} canonical ({100*(raw-canon)/raw:.1f}% collapsed)")
    for cat, (r, c) in sorted(report.items(), key=lambda kv: -kv[1][0]):
        console.print(f"  {cat:14} {r:>6} -> {c:>6}  (-{r-c})")
    # analysis.category_anchor is a measurement OVER the clusters this command
    # just rebuilt, and analysis.poi_supply.in_principled joins it -- leaving it
    # stale would silently veto against yesterday's clusters. Rebuilt here so
    # the two can never disagree. Skipped (loudly) when ZBP is not ingested.
    try:
        from loci.score.supply import build_category_anchor
        n_anchor = build_category_anchor(con, boroughs=("Manhattan", "Brooklyn"))
        n_q = con.execute("SELECT count(*) FROM analysis.category_anchor WHERE qualifies").fetchone()[0]
        console.print(f"[green]ok[/] analysis.category_anchor rebuilt: {n_anchor} categories, "
                      f"{n_q} with a qualifying anchor (D52)")
    except Exception as exc:                      # noqa: BLE001 -- reported, not swallowed
        console.print(f"[yellow]warning[/] analysis.category_anchor NOT rebuilt ({exc}); "
                      f"the PRINCIPLED supply set degrades to ALL until "
                      f"`loci anchor-coverage --write` is run")


@app.command()
def score(limit_min: int = typer.Option(30, help="Persist hex↔business network distances up to this many walk-minutes."),
          supply_set: str = typer.Option(SUPPLY_DEFAULT, "--supply-set",
                                         help="Which POIs count as supply: all | principled | "
                                              "corroborated (D52, score/supply.py).")) -> None:
    """Walk-network access: persist hex_poi_distance and derive hex_access.

    Still a HEX product and still required: the address screen
    (`loci address-gaps`) reads analysis.hex_poi_distance and the hex grid is
    the crosswalk that carries borough/NTA onto an address. It no longer builds
    the DNCI -- analysis.hex_dnci was retired with the hex screen under D38."""
    from loci.score.access import build_access
    con = locidb.connect(); locidb.init_schema(con)
    n_acc = build_access(con, limit=limit_min * 80.0, supply_set=supply_set)
    n_pairs = con.execute("SELECT count(*) FROM analysis.hex_poi_distance").fetchone()[0]
    console.print(f"[green]ok[/] {n_pairs:,} hex↔business pairs within {limit_min} min; "
                  f"{n_acc:,} hex_access rows")


# RETIRED UNDER D38 (2026-09-09): `loci gaps` built the HEX gap screen into
# analysis.hex_gaps / analysis.hex_gaps_reach. Both tables and the writer
# (model/gaps.build_gaps) are gone. The screen is `loci address-gaps`, whose
# unit is the residential PLUTO lot. model/gaps.py keeps its pure compute
# functions so the monotonicity battery that justified the reach rule stays
# runnable -- see the retirement note at the bottom of that module.
# Likewise retired here: `loci gaps-sweep` (a prevalence sweep of the hex
# window rule), `loci model` (the E3 supply-model stub; its
# model/supply.py read analysis.hex_dnci) and `loci export` (a PMTiles stub
# whose viz/export_webmap.py read analysis.hex_gaps). The live map export is
# `loci export-webmap`.

@app.command(name="reach-table")
def reach_table(quantile: float = typer.Option(0.80, help="Percentile of hex-to-nearest-c distance to use as reach."),
                write: bool = typer.Option(False, "--write", help="Overwrite src/loci/reach.yaml with the recomputed table."),
                min_pop: float = typer.Option(800.0, help="Population floor for a hex to count (matches `loci gaps`).")) -> None:
    """Recompute per-category REACH from revealed spacing. Read-only unless --write."""
    from loci.reach import compute_reach_table, write_reach_table
    con = locidb.connect(read_only=not write)
    rows = compute_reach_table(con, quantile=quantile, min_pop=min_pop)
    table = Table(title=f"revealed spacing -> reach (p{quantile:.0%} of hex-to-nearest-category network distance)")
    for col in ("category", "n_poi", "n_pop_hexes", "n_censored>30min", "median_m", "p75_m", f"reach_m (p{quantile:.0%})"):
        table.add_column(col, justify="right" if col != "category" else "left")
    for cat, n_poi, n_hex, n_cens, med, p75, reach_m in rows:
        table.add_row(cat, str(n_poi), str(n_hex), str(n_cens), f"{med:.0f}", f"{p75:.0f}", f"{reach_m:.0f}")
    console.print(table)
    if write:
        new = write_reach_table(con, quantile=quantile, min_pop=min_pop)
        console.print(f"[green]ok[/] wrote {len(new)} categories to src/loci/reach.yaml")


@app.command()
def conveniences(
    borough: str = typer.Option("MN", help="MN|BX|BK|QN|SI"),
) -> None:
    """Address-level convenience check: which of the 15 categories sit within the
    owner-set walk norm (src/loci/conveniences.yaml) of each residential address in
    `borough`. READ-ONLY (D58): a query over analysis.address_category.nearest_m,
    the SAME per-category network distances `loci address-gaps` already computed
    and wrote -- no second Dijkstra pass, nothing persisted. Requires
    `loci address-gaps` to have already run for `borough`."""
    from loci.model import conveniences as conv

    b = borough.upper()
    con = locidb.connect(read_only=True)

    try:
        summary = conv.convenience_report(con, b)
    except ValueError as e:
        console.print(f"[yellow]{e}[/]")
        raise typer.Exit(1)

    console.print(f"{summary['n_addresses']:,} addresses, {summary['n_units']:,.0f} units, borough={b}")
    for cat, share in summary["category_satisfied_share"].items():
        console.print(f"  {cat:14} satisfied {100*share:.1f}%")
    console.print(f"[bold]{100*summary['share_fully_satisfied']:.1f}%[/] of addresses "
                  f"(unit-weighted) have all 15 categories satisfied")


@app.command(name="address-gaps")
def address_gaps_cmd(
    borough: str = typer.Option("ALL", help="ALL|MN|BX|BK|QN|SI"),
    reach: str = typer.Option("tiers", help="'tiers' (CHECKPOINT D41, default) or 'p80' (reach.yaml)."),
    supply_set: str = typer.Option(SUPPLY_DEFAULT, "--supply-set",
                                   help="Which POIs count as supply: all | principled | "
                                        "corroborated (D52, score/supply.py). Recorded in "
                                        "analysis.address_gaps.supply_set/supply_hash."),
    limit: int = typer.Option(0, help="Cap addresses per borough, for smoke runs (0 = all)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print the summary; write nothing."),
) -> None:
    """Address-level gap screen (CHECKPOINT D33/D38/D39/D41): a fixed 800m/
    >=12-of-15 walkability gate (reach-independent), then a CONTINUOUS
    max(nearest_m/reach_m) ranking per residential PLUTO lot, clustered by
    lead category and proximity. Supersedes the old 800m/80% rule entirely.
    Writes analysis.address_gaps unless --dry-run."""
    import pandas as pd

    from loci.model import address_gaps as ag
    from loci.sources.cities.nyc.addresses import BOROCODE, load_residential_addresses

    b = borough.upper()
    if b != "ALL" and b not in BOROCODE:
        raise typer.BadParameter(f"unknown borough {borough!r}; expected ALL or one of {sorted(BOROCODE)}")
    boros = list(BOROCODE) if b == "ALL" else [b]

    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    frames = []
    for boro in boros:
        d = load_residential_addresses(con, boro)
        if limit:
            d = d.head(limit).reset_index(drop=True)
        d["borough"] = boro
        frames.append(d)
    addresses_df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    if addresses_df.empty:
        console.print(f"[yellow]no residential addresses for borough={b}[/]")
        raise typer.Exit(0)

    console.print(f"[dim]{len(addresses_df):,} addresses (borough={b}); "
                  f"loading walk graph + 15 Dijkstra passes…[/]")

    if dry_run:
        df = ag.compute_address_gaps(con, addresses_df, reach_source=reach,
                                     supply_set=supply_set)
        console.print("[dim]--dry-run: computed, nothing written.[/]")
    else:
        n, df = ag.build_address_gaps(con, addresses_df, reach_source=reach,
                                      supply_set=supply_set)
        console.print(f"[green]ok[/] wrote {n:,} rows -> analysis.address_gaps "
                      f"(borough={b}, reach={reach}, supply_set={supply_set}, "
                      f"supply_hash={df['supply_hash'].iloc[0]})")

    summary = ag.summarize_gap_run(df)
    console.print(f"{summary['n_addresses']:,} addresses, {summary['n_units']:,.0f} units, "
                  f"borough={b}, reach={reach}")
    console.print(f"eligible: [bold]{100*summary['eligible_addr_share']:.1f}%[/] of addresses, "
                  f"[bold]{100*summary['eligible_unit_share']:.1f}%[/] of units "
                  f"[dim](retired D75 — always 100%; every address is in the universe)[/]")
    # D75: how much of the screen is reading the Dijkstra cap rather than a
    # distance. The gate used to hide most of this; printing it beside the gap
    # counts is the whole point of exposing it.
    cap = summary["cap_m"]
    console.print(f"censored at {cap:,.0f} m (nothing of that category within the cap — "
                  f"a FLOOR, not a measurement): [bold]{summary['censored_pairs']:,}[/] "
                  f"(address, category) pairs; [bold]{summary['lead_censored_addr']:,}[/] "
                  f"addresses have a censored LEAD, so their gap_score is a floor")

    console.print("[bold]per-category gap counts (ratio > 1; censored = at the cap):[/]")
    for cat in ag.ALLCATS:
        n_addr = summary["per_cat_gap_addr"][cat]
        if n_addr:
            n_cens = summary["per_cat_censored"][cat]
            console.print(f"  {cat:14} {n_addr:>8,} addr  "
                          f"{summary['per_cat_gap_units'][cat]:>10,.0f} units  "
                          f"{n_cens:>8,} censored")

    console.print("[bold]lead category distribution:[/]")
    for cat, n_addr in sorted(summary["lead_distribution"].items(), key=lambda kv: -kv[1]):
        console.print(f"  {cat:14} {n_addr:>8,}")

    console.print("[bold]top 10 clusters by capped units:[/]")
    for row in summary["top_clusters"]:
        # emoji=False: cluster_id is "{borough}:{lead_category}:{n}" (e.g.
        # "BK:bank:12") and rich's default emoji shortcode parsing mangles
        # ":bank:" into a bank-emoji glyph, garbling the id -- data-derived
        # text with colons must never be printed with emoji parsing on.
        console.print(
            f"  {row['cluster_id']:28} {row['borough']:3} lead={row['lead_category']:14} "
            f"units_capped={row['units_capped']:>8,.0f}  n_addr={row['n_addresses']:>5}  "
            f"median_lead_excess_m={row['median_lead_excess_m']:>7.0f}",
            emoji=False,
        )


@app.command()
def validate(
    per_stratum: int = typer.Option(20, help="Gap ADDRESSES sampled per stratum "
                                             "(stratum = income decile × missing-this-category)."),
    categories: str = typer.Option("all", help="Comma-separated Loci categories, or 'all'."),
    boroughs: str = typer.Option("MN,BK", help="Comma-separated boroughs to sample; D48 scope is MN+BK."),
    unit_weighted: bool = typer.Option(False, "--unit-weighted",
        help="Draw proportional to units_capped instead of one draw per address. Use when the "
             "sample is to be read as a statement about households behind a gap, not about "
             "loci's inventory at a point."),
    seed: int = typer.Option(20260902, help="Sampling seed; the draw is reproducible from it."),
    dry_run: bool = typer.Option(True, "--dry-run/--run", help="Plan only (default) or spend calls."),
    recount_local: bool = typer.Option(False, "--recount-local",
        help="Recompute n_overture/n_osm/n_city_source/n_local_canonical for every EXISTING row "
             "in analysis.coverage_validation against current staging.poi/poi_dedup. Spends no "
             "Google calls and touches n_ground_truth for nobody; ignores --dry-run/--run/sampling."),
) -> None:
    """Coverage validation (P3): Google Places as SAMPLED ground truth, counts only, hard budget.

    The frame is gap ADDRESSES (D38/D58) — rows of analysis.address_gaps, not hex centroids.
    """
    from loci.categories import CATEGORIES
    from loci.validation import sample as smp
    from loci.validation.google_places import GooglePlacesClient
    con = locidb.connect(); locidb.init_schema(con)
    if recount_local:
        n = smp.recount_local(con)
        console.print(f"[green]ok[/] recomputed local counts for {n} existing rows "
                       f"in analysis.coverage_validation — no Google calls spent.")
        raise typer.Exit(0)
    cats = list(CATEGORIES) if categories == "all" else [c.strip() for c in categories.split(",")]
    boros = tuple(b.strip() for b in boroughs.split(",") if b.strip())
    s = smp.draw_sample(con, categories=cats, per_stratum=per_stratum, boroughs=boros,
                        seed=seed, unit_weighted=unit_weighted)
    p = smp.plan(s, cats)
    if p["skipped"]:
        console.print(f"[yellow]skipping {', '.join(p['skipped'])} — no Google Places type mapping "
                       f"(GTM-105 #7).[/]")
    client = GooglePlacesClient()
    weighting = "units_capped-weighted" if unit_weighted else "address-weighted"
    console.print(f"frame: {p['frame']} — {weighting}, {per_stratum}/stratum, seed {seed} "
                   f"(D38 address unit, D48 scope). Rows carrying h3_index are the frozen "
                   f"pre-D38 hex frame and are never pooled with these.")
    console.print(f"sample: {p['addresses']} addresses over {p['n_strata']} strata × "
                  f"{p['categories']} categories = {p['calls']} calls; "
                  f"radius {p['radius_m']} m straight-line (circuity-corrected, QUESTIONS M8/D53); "
                  f"est. ${p['est_cost_usd']} beyond the free tier. Budget {client.calls_used}/{client.budget} used.")
    if p["per_category"]:
        table = Table(title="calls per category — missing vs present (the coverage-bias control)")
        for col in ("category", "missing", "present", "total"):
            table.add_column(col, justify="right" if col != "category" else "left")
        for c, d in sorted(p["per_category"].items()):
            table.add_row(c, str(d["missing"]), str(d["present"]), str(d["missing"] + d["present"]))
        console.print(table)
    if dry_run:
        console.print("[dim]--dry-run: nothing spent, nothing written. Re-run with --run.[/]")
        raise typer.Exit(0)
    if p["calls"] > client.calls_left:
        console.print(f"[red]refusing:[/] {p['calls']} calls needed, {client.calls_left} left in budget.")
        raise typer.Exit(1)
    n = smp.run(con, client, s, cats, dry_run=False)
    console.print(f"[green]ok[/] {n} rows in analysis.coverage_validation; budget now {client.calls_used}/{client.budget}")


@app.command()
def spacing(citywide: bool = typer.Option(False, "--citywide", help="Include the NJ/Westchester fringe."),
            per_category: int = typer.Option(2000, help="Businesses sampled per category for the spacing table.")) -> None:
    """Read-only, on the WALK NETWORK: how far apart same-type businesses of the
    same category sit. This is the revealed-spacing evidence behind the D35/D41
    reach tiers.

    The second table this command used to print -- gap HEX to its lead-missing
    business -- is retired with analysis.hex_gaps under D38. Its replacement is
    per address, not per cell: `<lead_category>_nearest_m` and `lead_excess_m`
    on analysis.address_gaps."""
    from loci.model.spacing import WALK_M_PER_MIN, _graph, same_type_spacing
    con = locidb.connect(read_only=True)
    console.print("[dim]loading walk graph…[/]")
    graph = _graph()
    t1 = Table(title="Same-type spacing — network metres to the nearest OTHER business of the same category")
    for col in ("category", "n", "sampled", "p10", "median", "p90", "> 10 min", "> 30 min"):
        t1.add_column(col, justify="right" if col != "category" else "left")
    for cat, n, ns, p10, med, p90, far, cens in same_type_spacing(con, core_only=not citywide, per_category=per_category, graph=graph):
        t1.add_row(cat, str(n), str(ns), f"{p10:.0f}", f"{med:.0f}", f"{p90:.0f}" if cens < .10 else f">{p90:.0f}", f"{100*far:.1f}%", f"{100*cens:.1f}%")
    console.print(t1)
    console.print(f"[dim]Walking at {WALK_M_PER_MIN:.0f} m/min: 800 m = 10 min, 1,200 m = 15 min, 2,400 m = 30 min. "
                  "Same graph, snapping and component pruning as hex_access.[/]")


@app.command(name="export-webmap")
def export_webmap_cmd(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes (MN|BX|BK|QN|SI)."),
    out_dir: Path = typer.Option(REPO_ROOT / "webmap" / "data", help="Output directory."),
    supply_set: str = typer.Option(SUPPLY_DEFAULT, "--supply-set",
        help="Which POIs count as known locations: all | principled | corroborated. "
             "Must match analysis.address_gaps.supply_set or the map's two layers "
             "disagree (D52) — a mismatch is reported, not silently exported."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print counts per category and borough; write nothing."),
) -> None:
    """Export the webmap's two point layers: gap addresses (analysis.address_gaps,
    ratio > 1 per category) and every canonical business location, read through
    analysis.poi_supply under the named supply set. One file per category per
    layer, so the browser fetches only the category on screen. Corroborated =
    the dedup cluster is backed by 2+ distinct sources (CHECKPOINT D47);
    excluded = dropped by the supply set (D52) and drawn as its own class."""
    from loci.viz import webmap_export as wx

    boros = [b.strip().upper() for b in boroughs.split(",") if b.strip()]
    con = locidb.connect(read_only=True)
    bundle = wx.collect(con, boros, supply_set)
    counts = wx.summarize(bundle)

    # The supply set is the first thing printed, before any count, because
    # every "known locations" number below is conditional on it (D52).
    prov = bundle["supplyProvenance"]
    console.print(f"supply set [bold]{supply_set}[/] · analysis.address_gaps recorded "
                  f"[bold]{prov['supply_set'] or 'nothing'}[/]"
                  + (f" (supply_hash {prov['supply_hash']})" if prov["supply_hash"] else ""))
    if bundle["supplyWarning"]:
        console.print(Panel(bundle["supplyWarning"], title="[red]SUPPLY PROVENANCE[/]",
                            border_style="red"))

    # One table per borough: ten columns in a single table gets shrunk to
    # unreadable ellipses on a normal terminal.
    suffix = "  [DRY RUN — nothing written]" if dry_run else ""
    for b in boros:
        table = Table(title=f"{wx.BOROUGH_NAMES[b]} ({b}) — supply set {supply_set}{suffix}")
        table.add_column("category")
        table.add_column("gap addresses", justify="right")
        table.add_column("known locations", justify="right")
        table.add_column("corroborated", justify="right")
        table.add_column("single-source", justify="right")
        # Dropped by the supply set: under `principled`, a lone aggregator
        # record in an anchored category. Exported and drawn, never counted.
        table.add_column("excluded", justify="right")
        # DOHMH detail (cuisine/grade/active) exists only for the categories
        # the inspection file covers; "-" is not zero, it is "not applicable".
        table.add_column("DOHMH detail", justify="right")
        table.add_column("active", justify="right")
        tot = [0, 0, 0, 0, 0]
        for cat in wx.ALLCATS:
            p, g = counts["poi"][cat][b], counts["gap"][cat][b]
            x = counts["excluded"][cat][b]
            detail = f"{p['dohmh']:,}" if "dohmh" in p else "-"
            active = f"{p['active']:,}" if "active" in p else "-"
            table.add_row(cat, f"{g:,}", f"{p['all']:,}",
                          f"{p['corroborated']:,}", f"{p['single']:,}",
                          f"{x:,}" if x else "[dim]0[/]", detail, active)
            tot[0] += g; tot[1] += p["all"]
            tot[2] += p["corroborated"]; tot[3] += p["single"]; tot[4] += x
        table.add_row("[bold]total[/]", *[f"[bold]{v:,}[/]" for v in tot], "", "")
        console.print(table)

    # The development-pipeline overlay (sql/011). Counted per stage and per
    # size band because those are exactly the two things the map's symbol
    # encodes — if the table here and the legend there ever disagree, one of
    # them is drawing something it did not count.
    pipe = counts["pipeline"]
    if not pipe["available"]:
        console.print("[yellow]development pipeline:[/] analysis.dev_pipeline not loaded "
                      "— run `loci ingest-dcp-housing` then `loci pipeline`; "
                      "an empty overlay is exported.")
    else:
        pt = Table(title=f"Development pipeline — net units ≥ {wx.PIPELINE_MIN_UNITS}, "
                         f"stages {'/'.join(wx.PIPELINE_MAP_STAGES)}, "
                         f"completions within {wx.PIPELINE_COMPLETE_MONTHS} months{suffix}")
        pt.add_column("stage / band")
        for b in boros:
            pt.add_column(f"{b} jobs", justify="right")
        pt.add_column("units", justify="right")
        for s, lab in zip(pipe["stages"], pipe["stageLabels"]):
            pt.add_row(lab, *[f"{pipe['counts'][s][b]:,}" for b in boros],
                       f"{sum(pipe['units'][s][b] for b in boros):,}")
        pt.add_row("", *["" for _ in boros], "")
        for lab in pipe["bandLabels"]:
            pt.add_row(f"[dim]band[/] {lab}", *[f"{pipe['bands'][lab][b]:,}" for b in boros],
                       f"{pipe['bandUnits'][lab]:,}")
        pt.add_row("[bold]total[/]",
                   *[f"[bold]{sum(pipe['counts'][s][b] for s in pipe['stages']):,}[/]" for b in boros],
                   f"[bold]{sum(sum(v.values()) for v in pipe['units'].values()):,}[/]")
        console.print(pt)
        co = pipe["co"]
        console.print(f"[dim]certificate of occupancy: {co.get('final', 0):,} final · "
                      f"{co.get('temporary', 0):,} temporary · {co.get('none', 0):,} none[/]")
        # The vintage is not decoration. DCP publishes semiannually, so the
        # coming-units side of this layer is a floor that ages; the map is
        # required to print both dates and so is this.
        console.print(f"[bold]pipeline as of {pipe['asof']}[/] (completion windows) · "
                      f"DCP {pipe['vintage'] or '?'} carries filings and permits only to "
                      f"[bold]{pipe['cutoff'] or '?'}[/] — anything filed or permitted since "
                      "is absent, so the coming-units count is a floor, never a ceiling.")

    # The vacant-storefront overlay (sql/012). Counted per borough and per
    # consecutive-years band because those are what the symbol encodes, and
    # ALWAYS beside the registered-storefront denominator: in a self-reported
    # registry a vacancy count with no denominator cannot tell "nothing is
    # empty here" from "nobody here filed".
    shop = counts["storefront"]
    if not shop["available"]:
        console.print("[yellow]vacant storefronts:[/] analysis.storefront not loaded "
                      "— run `loci ingest-storefronts` then `loci storefronts`; "
                      "an empty overlay is exported.")
    else:
        st = Table(title=f"Vacant storefronts — snapshot {shop['asof']} "
                         f"({shop['universe']} filing, filed {shop['filingDate']}){suffix}")
        st.add_column("band")
        for b in boros:
            st.add_column(f"{b} premises", justify="right")
        for lab in shop["bandLabels"]:
            st.add_row(lab, *[f"{shop['bands'][lab][b]:,}" for b in boros])
        st.add_row("[dim]of which construction reported[/]",
                   *[f"[dim]{shop['construction'][b]:,}[/]" for b in boros])
        st.add_row("[bold]vacant premises drawn[/]",
                   *[f"[bold]{sum(shop['bands'][lab][b] for lab in shop['bandLabels']):,}[/]"
                     for b in boros])
        console.print(st)
        for b in boros:
            t = shop["totals"].get(b) or {}
            n_sf, n_vac = t.get("storefronts", 0), t.get("vacantStorefronts", 0)
            rate = f"{100 * n_vac / n_sf:.1f}%" if n_sf else "n/a"
            console.print(f"[dim]{b}: {n_vac:,} of {n_sf:,} registered storefronts vacant "
                          f"({rate}) · {t.get('vacantPremises', 0):,} vacant premises, "
                          f"{t.get('noGeom', 0):,} with no coordinate (not drawn)[/]")
        console.print(f"[bold]storefront registry snapshot {shop['asof']}[/] "
                      f"(DOF {shop['vintage'] or '?'}, filed {shop['filingDate']}) — "
                      "self-reported; a landlord who does not file is invisible, and "
                      "small buildings are mostly absent.")

    if dry_run:
        console.print("[dim]--dry-run: nothing written.[/]")
        raise typer.Exit(0)

    written = wx.write(bundle, out_dir)
    biggest = sorted(written.items(), key=lambda kv: -kv[1])[:3]
    console.print(f"[green]ok[/] wrote {len(written)} files -> {out_dir} "
                  f"({sum(written.values())/1e6:.1f} MB total)")
    console.print("[dim]largest: " + ", ".join(f"{k} {v/1e6:.2f} MB" for k, v in biggest) + "[/]")


@app.command(name="ingest-alcohol")
def ingest_alcohol(
    limit: int = typer.Option(None, help="Cap licences fetched (for smoke tests)."),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Fetch and classify; print counts by classification and borough; write nothing."),
) -> None:
    """Land every active NYS Liquor Authority licence into staging.alcohol_licences.

    The ALCOHOL OVERLAY (owner decision 2026-09-08) — a standalone map layer, NOT
    a 16th category and NOT part of staging.poi, so no score, gap or reach number
    moves. `nys_sla.py` keeps emitting bar-class licences into staging.poi
    unchanged. Classification comes from
    sources/cities/nyc/alcohol_licences.yaml; an unlisted licence type is
    labelled `unknown`, never dropped."""
    from collections import Counter

    from loci.sources.cities.nyc import nys_sla

    cls_labels = nys_sla.load_classification()["labels"]
    recs = nys_sla.load_alcohol_licences(None, limit=limit, dry_run=True)

    per = {c: Counter() for c in nys_sla.CLASSIFICATIONS}
    boros = sorted({r.borough for r in recs if r.borough})
    for r in recs:
        per[r.classification][r.borough or "?"] += 1
        per[r.classification]["all"] += 1
        if r.active:
            per[r.classification]["active"] += 1

    suffix = "  [DRY RUN — nothing written]" if dry_run else ""
    table = Table(title=f"NYS SLA licences by classification{suffix}")
    table.add_column("classification")
    for col in (*boros, "total", "active"):
        table.add_column(col, justify="right")
    for c in nys_sla.CLASSIFICATIONS:
        table.add_row(cls_labels.get(c, c), *[f"{per[c][b]:,}" for b in boros],
                      f"{per[c]['all']:,}", f"{per[c]['active']:,}")
    table.add_row("[bold]total[/]",
                  *[f"[bold]{sum(per[c][b] for c in per):,}[/]" for b in (*boros, "all", "active")])
    console.print(table)
    unknown = [r.description for r in recs if r.classification == "unknown"]
    if unknown:
        top = ", ".join(f"{d} ({n:,})" for d, n in Counter(unknown).most_common(5))
        console.print(f"[yellow]unclassified licence types:[/] {top}")

    if dry_run:
        console.print("[dim]--dry-run: nothing written.[/]")
        raise typer.Exit(0)

    con = locidb.connect()
    locidb.init_schema(con)
    n = nys_sla.write_licences(con, recs)   # one fetch, counted above, written here
    console.print(f"[green]ok[/] {n:,} rows in staging.alcohol_licences "
                  f"(map yaml version {nys_sla.load_classification()['version']})")


@app.command(name="ingest-dcwp")
def ingest_dcwp(
    limit: int = typer.Option(None, help="Cap inspection rows fetched (for smoke tests)."),
    apply: bool = typer.Option(False, "--apply",
        help="Promote staging.poi_dcwp_pending into staging.poi. Run `loci dedup` after."),
    stage: bool = typer.Option(True, "--stage/--no-stage",
        help="Fetch and land into the pending table. --no-stage --apply promotes what is already staged."),
) -> None:
    """Land the DCWP retail-laundry anchor (owner decision D55).

    DEFAULTS TO PENDING. The ingest writes staging.poi_dcwp_pending, never
    staging.poi, so it cannot race `loci dedup` reading the supply universe.
    `--apply` is the separate, explicit promotion step.

    Why this source and not the licence roster: DCWP's Legally Operating
    Businesses roster publishes no retail-laundry category at all (6 licences,
    all expired 2023-12-31), which is why `nyc_dcwp_licenses` ingests empty.
    Retail laundries are only published through the inspections feed. The full
    reasoning, including why the 2013 Historical Licences snapshot is NOT used,
    is in sources/cities/nyc/dcwp.py."""
    from loci.sources.cities.nyc import dcwp

    con = locidb.connect()
    locidb.init_schema(con)

    if stage:
        recs = dcwp.stage_pending(con, limit=limit)
        active = sum(1 for r in recs if r.attrs.get("active"))
        boros = Counter(r.attrs.get("borough") for r in recs)
        table = Table(title="DCWP retail laundry -> staging.poi_dcwp_pending")
        table.add_column("borough")
        table.add_column("staged", justify="right")
        for b in sorted(x for x in boros if x):
            table.add_row(b, f"{boros[b]:,}")
        table.add_row("[bold]total[/]", f"[bold]{len(recs):,}[/]")
        table.add_row("of which active", f"{active:,}")
        console.print(table)
        mnbk = sum(v for k, v in boros.items() if k in ("Manhattan", "Brooklyn"))
        console.print(f"[dim]MN+BK staged {mnbk:,}[/]")

    if not apply:
        n = con.execute(
            f"SELECT count(*) FROM {dcwp.PENDING_TABLE}").fetchone()[0]
        console.print(f"[green]ok[/] {n:,} rows pending in {dcwp.PENDING_TABLE}. "
                      f"Nothing written to staging.poi.")
        console.print("[dim]to promote:  loci ingest-dcwp --no-stage --apply "
                      "&&  loci dedup[/]")
        raise typer.Exit(0)

    deleted, inserted = dcwp.apply_pending(con)
    console.print(f"[green]ok[/] promoted {inserted:,} rows into staging.poi "
                  f"(replaced {deleted:,}). Re-run `loci dedup` before any score.")


@app.command(name="ingest-dohmh-childcare")
def ingest_dohmh_childcare(
    limit: int = typer.Option(None, help="Cap rows fetched (for smoke tests)."),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Fetch + normalize and print the summary; write nothing at all."),
    apply: bool = typer.Option(False, "--apply",
        help="Promote staging.poi_dohmh_childcare_pending into staging.poi. Run `loci dedup` after."),
    stage: bool = typer.Option(True, "--stage/--no-stage",
        help="Fetch and land into the pending table. --no-stage --apply promotes what is already staged."),
) -> None:
    """Land the DOHMH child-care anchor (D65) — the registry source `childcare` lacked.

    DEFAULTS TO PENDING, like `loci ingest-dcwp`: the ingest writes
    staging.poi_dohmh_childcare_pending, never staging.poi, so it cannot race
    `loci dedup` reading the supply universe. `--apply` is the separate,
    explicit promotion step.

    Dataset is gy3q-4tzp ("Active NYC Health Code Regulated Child Care
    Programs"), NOT the dsg6-ifza inspections file the registry originally
    planned against — that one is titled "(Historical)" and its own portal note
    says it reflects data as of 2019-05-14. Full reasoning, and the caveat that
    OCFS-licensed home-based family day care is absent from every NYC feed, is
    in sources/cities/nyc/dohmh_childcare.py."""
    from loci.sources.cities.nyc import dohmh_childcare as ccare

    if dry_run:
        recs = ccare.DohmhChildcareAdapter().load(None, limit=limit, dry_run=True)
        boros = Counter(r.attrs.get("borough") for r in recs)
        fac = Counter(r.attrs.get("facility_type") for r in recs)
        console.print(f"[dim]--dry-run:[/] {len(recs):,} childcare records, nothing written.")
        console.print(f"  by borough      {dict(sorted(boros.items(), key=lambda kv: -kv[1]))}")
        console.print(f"  by facility     {dict(fac)}")
        raise typer.Exit(0)

    con = locidb.connect()
    locidb.init_schema(con)

    if stage:
        recs = ccare.stage_pending(con, limit=limit)
        boros = Counter(r.attrs.get("borough") for r in recs)
        fac = Counter(r.attrs.get("facility_type") for r in recs)
        table = Table(title="DOHMH child care -> staging.poi_dohmh_childcare_pending")
        table.add_column("borough")
        table.add_column("staged", justify="right")
        for b in sorted(x for x in boros if x):
            table.add_row(b, f"{boros[b]:,}")
        table.add_row("[bold]total[/]", f"[bold]{len(recs):,}[/]")
        table.add_row("of which active", f"{sum(1 for r in recs if r.attrs.get('active')):,}")
        console.print(table)
        console.print(f"[dim]facility types {dict(fac)}; "
                      f"MN+BK staged {sum(v for k, v in boros.items() if k in ('MN', 'BK')):,}[/]")

    if not apply:
        n = con.execute(f"SELECT count(*) FROM {ccare.PENDING_TABLE}").fetchone()[0]
        console.print(f"[green]ok[/] {n:,} rows pending in {ccare.PENDING_TABLE}. "
                      f"Nothing written to staging.poi.")
        console.print("[dim]to promote:  loci ingest-dohmh-childcare --no-stage --apply "
                      "&&  loci dedup[/]")
        raise typer.Exit(0)

    deleted, inserted = ccare.apply_pending(con)
    console.print(f"[green]ok[/] promoted {inserted:,} rows into staging.poi "
                  f"(replaced {deleted:,}). Re-run `loci dedup` before any score.")


@app.command(name="ingest-nys-medicaid-pharmacy")
def ingest_nys_medicaid_pharmacy(
    limit: int = typer.Option(None, help="Cap rows fetched (for smoke tests)."),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Fetch + normalize and print the summary; write nothing at all."),
    apply: bool = typer.Option(False, "--apply",
        help="Promote staging.poi_nys_medicaid_pharmacy_pending into staging.poi. "
             "Run `loci dedup` after."),
    stage: bool = typer.Option(True, "--stage/--no-stage",
        help="Fetch and land into the pending table. --no-stage --apply promotes "
             "what is already staged."),
) -> None:
    """Land the pharmacy anchor — the registry source `pharmacy` lacked (D66/D69).

    DEFAULTS TO PENDING, like `loci ingest-dcwp` and `loci
    ingest-dohmh-childcare`: the ingest writes
    staging.poi_nys_medicaid_pharmacy_pending, never staging.poi, so it cannot
    race `loci dedup` reading the supply universe. `--apply` is the separate,
    explicit promotion step.

    Dataset is health.data.ny.gov `keti-qx5t`, the NYS Medicaid Enrolled
    Provider Listing, filtered to `profession_or_service = 'PHARMACY'`. It is
    NOT the NYSED Board of Pharmacy registry the registry originally planned
    against — that one has no bulk download at all, only a one-record
    verification form — and it stands in for it because Medicaid enrolment
    requires a current NYSED establishment registration. Full reasoning, the
    rejected NPPES alternative, the (0,0) null-island drop, the composite
    record key, and the legal-name-vs-trade-name double count are in
    sources/cities/nyc/nys_medicaid_pharmacy.py."""
    from loci.sources.cities.nyc import nys_medicaid_pharmacy as rx

    def _summary(recs, dropped) -> None:
        boros = Counter(r.attrs.get("borough") for r in recs)
        console.print(f"  by borough      "
                      f"{dict(sorted(boros.items(), key=lambda kv: -kv[1]))}")
        console.print(f"  MN+BK           "
                      f"{sum(v for k, v in boros.items() if k in ('MN', 'BK')):,}")
        console.print(f"  of which active {sum(1 for r in recs if r.attrs.get('active')):,}")
        # Every drop is printed. A drop nobody can see is how a silent zero
        # gets ingested -- `null_island` in particular is a failed State
        # geocode, not an absent pharmacy.
        console.print(f"  dropped         {dict(sorted(dropped.items())) or '{}'}")

    if dry_run:
        ad = rx.NysMedicaidPharmacyAdapter()
        recs = ad.load(None, limit=limit, dry_run=True)
        console.print(f"[dim]--dry-run:[/] {len(recs):,} retail-pharmacy records, "
                      f"nothing written.")
        _summary(recs, ad.dropped)
        raise typer.Exit(0)

    con = locidb.connect()
    locidb.init_schema(con)

    if stage:
        recs, dropped = rx.stage_pending(con, limit=limit)
        table = Table(title="NYS Medicaid pharmacies -> "
                            "staging.poi_nys_medicaid_pharmacy_pending")
        table.add_column("borough")
        table.add_column("staged", justify="right")
        boros = Counter(r.attrs.get("borough") for r in recs)
        for b in sorted(x for x in boros if x):
            table.add_row(b, f"{boros[b]:,}")
        table.add_row("[bold]total[/]", f"[bold]{len(recs):,}[/]")
        console.print(table)
        _summary(recs, dropped)

    if not apply:
        n = con.execute(f"SELECT count(*) FROM {rx.PENDING_TABLE}").fetchone()[0]
        console.print(f"[green]ok[/] {n:,} rows pending in {rx.PENDING_TABLE}. "
                      f"Nothing written to staging.poi.")
        console.print("[dim]to promote:  loci ingest-nys-medicaid-pharmacy "
                      "--no-stage --apply  &&  loci dedup[/]")
        raise typer.Exit(0)

    deleted, inserted = rx.apply_pending(con)
    console.print(f"[green]ok[/] promoted {inserted:,} rows into staging.poi "
                  f"(replaced {deleted:,}). Re-run `loci dedup` before any score.")


# ======================================================================
# GTM-110 region (address-level demand annotation). Appended by the
# GTM-110 session; keep edits inside this delimited block.
# ======================================================================

@app.command(name="address-demand")
def address_demand_cmd(
    borough: str = typer.Option("MNBK", help="MNBK (default, D48 scope) | MN | BK | ALL"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print the summary; write nothing."),
) -> None:
    """Address-level DEMAND ANNOTATION (D49 at the D38 grain, GTM-110; folded
    onto analysis.address_category under D58).

    Reads analysis.address_category/address_demographics READ-ONLY to learn
    what is known about demand at each (address, category) that is missing
    (ratio > 1, the D41 continuous reading), plus every address's lead
    category, then UPDATEs analysis.address_category's own demand annotation
    columns ONLY (never nearest_m/ratio/is_lead/eligible), so the screen
    stays graded, never filtered (D48).

    The caveat is MOE-gated: asserted only where the address is confidently
    below 0.80x the citywide MEAN household income (income_ratio +
    income_ratio_moe < cutoff) AND the category is discretionary (derived
    from spend.yaml's BLS CEX elasticity; clinic excluded per D30).
    demand_caveat_text must be rendered untruncated -- the X6 disclaimer is
    its tail.
    """
    from loci.model import address_demand as ad
    from loci.sources.cities.nyc.addresses import BOROCODE

    b = borough.upper()
    if b in ("MNBK", "DEFAULT"):
        boros = ["MN", "BK"]
    elif b == "ALL":
        boros = None  # resolved from address_gaps below
    elif b in BOROCODE:
        boros = [b]
    else:
        raise typer.BadParameter(
            f"unknown borough {borough!r}; expected MNBK, ALL, or one of {sorted(BOROCODE)}")

    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    if boros is None:
        boros = [r[0] for r in con.execute(
            "SELECT DISTINCT borough FROM analysis.address_gaps ORDER BY 1").fetchall()]
    if not boros:
        console.print("[yellow]analysis.address_gaps is empty -- run `loci address-gaps` first[/]")
        raise typer.Exit(0)

    console.print(f"[dim]annotating analysis.address_gaps (boroughs={','.join(boros)}) "
                  f"against address-grain ACS income…[/]")

    if dry_run:
        df = ad.compute_address_demand(con, boros)
        console.print("[dim]--dry-run: computed, nothing written.[/]")
    else:
        n, df = ad.build_address_demand(con, boros)
        console.print(f"[green]ok[/] annotated {n:,} rows -> analysis.address_category "
                       f"(demand columns; boroughs={','.join(boros)})")

    if df.empty:
        console.print("[yellow]no rows -- address_gaps has no matching boroughs[/]")
        raise typer.Exit(0)

    s = ad.summarize(df)
    console.print(f"{s['n_rows']:,} (address, category) rows over "
                  f"{s['n_addresses']:,} addresses")
    console.print(f"caveated: [bold]{s['n_caveated']:,}[/] rows "
                  f"({100*s['caveat_share']:.1f}%)")
    console.print(f"income-indeterminate (cutoff within one MOE): "
                  f"{s['n_indeterminate']:,} rows ({100*s['indeterminate_share']:.1f}%)")
    if s.get("indeterminate_share_of_known_moe") is not None:
        console.print(f"  of rows with a known MOE: "
                      f"{100*s['indeterminate_share_of_known_moe']:.1f}%")
    console.print(f"addresses whose LEAD category is caveated: "
                  f"{s['n_lead_caveated']:,} of {s['n_lead_rows']:,} lead rows "
                  f"({100*s['lead_caveat_share']:.1f}%)")
    console.print("[bold]caveated rows by category:[/]")
    for cat, k in s["caveated_by_category"].items():
        console.print(f"  {cat:14} {k:>10,}")


def _parse_boroughs(boroughs: str) -> list[str]:
    """"MN,BK" -> ["MN", "BK"]; "ALL" -> every borough. D48 default is MN+BK."""
    from loci.sources.cities.nyc.addresses import BOROCODE

    raw = (boroughs or "").strip().upper()
    if raw in ("ALL", "*"):
        return sorted(BOROCODE)
    out = [b.strip() for b in raw.split(",") if b.strip()]
    bad = [b for b in out if b not in BOROCODE]
    if bad:
        raise typer.BadParameter(f"unknown borough(s) {bad}; expected ALL or {sorted(BOROCODE)}")
    if not out:
        raise typer.BadParameter("no boroughs given")
    return out


@app.command(name="ingest-dcp-housing")
def ingest_dcp_housing(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL (D48 default MN,BK)."),
    limit: int = typer.Option(None, help="Cap rows fetched per dataset (smoke tests)."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Fetch, normalize and report; write nothing."),
) -> None:
    """Land the residential development pipeline: DCP Housing Database
    (project-level, `br6q-ssj3`) as the spine, DOB Certificates of Occupancy
    (`bs8b-p36w` + `pkdm-hqz6`, daily) as the freshness supplement, into
    analysis.dev_pipeline -- ONE ROW PER DOB JOB.

    DCP publishes semiannually and is up to eight months stale at the end of a
    cycle; the CO feeds correct the completion side only, so the forward
    pipeline is a floor, never a ceiling. Read sql/011_dev_pipeline.sql for
    the dedup rule (a job has many CO rows and they must NEVER be summed) and
    for why `under_construction` is not in the stage vocabulary.
    """
    import datetime as _dt

    from loci.sources.cities.nyc import dcp_housing as dcph

    boros = tuple(_parse_boroughs(boroughs))
    con = None if dry_run else locidb.connect()
    if con is not None:
        locidb.init_schema(con)

    console.print(f"[dim]fetching DCP {dcph.DCP_DATASET} + CO feeds "
                  f"{dcph.CO_BIS_DATASET}/{dcph.CO_NOW_DATASET} for {','.join(boros)}…[/]")
    rows, report = dcph.build(con, boros, limit=limit, dry_run=dry_run)
    written = report.pop("_written", None)

    console.print(f"DCP rows {report['dcp_rows']:,} · CO rows "
                  f"{report['co_bis_rows']:,} (BIS) + {report['co_now_rows']:,} (NOW) "
                  f"-> {report['co_jobs']:,} jobs with CO evidence")
    console.print(f"DCP version [bold]{report['vintage']}[/] · "
                  f"{report['co_overrode_dcp']:,} jobs whose CO is FRESHER than DCP's status "
                  f"· {report['no_geom']:,} rows without a coordinate")

    t = Table(title=f"analysis.dev_pipeline — {','.join(boros)}")
    t.add_column("stage"); t.add_column("jobs", justify="right")
    t.add_column("net units", justify="right")
    for stage in dcph.STAGES:
        s = report["by_stage"].get(stage)
        if s:
            t.add_row(stage, f"{int(s['count']):,}", f"{int(s['sum']):,}")
    console.print(t)

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] {written:,} rows -> analysis.dev_pipeline")
    by = con.execute("""SELECT borough, stage, count(*), sum(net_units)
                        FROM analysis.dev_pipeline GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    for b, stage, n, u in by:
        console.print(f"  {b} {stage:<20} {n:>7,} jobs  {int(u or 0):>9,} net units")
    _ = _dt


@app.command()
def pipeline(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL (D48 default MN,BK)."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Tight catchment radius in NETWORK metres (default 400 = the 5-min tier)."),
    asof: str = typer.Option(None, help="Run date the completion windows count back from (YYYY-MM-DD; default today)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Annotate analysis.address with development-pipeline exposure.

    For every address: net units PERMITTED (not yet occupied) and net units
    COMPLETED in the last 24 and 60 months, within a 5-minute (400 m) and a
    10-minute (800 m) NETWORK walk, plus the nearest project of >= 50 net
    units with its stage and date.

    UPDATE-only on analysis.address (model/dev_pipeline.PIPELINE_COLUMNS,
    pinned disjoint from the screen's own columns) -- pipeline exposure is an
    annotation, never a filter: it cannot move gap_score, lead_category,
    n_missing or eligible. 24mo is a SUBSET of 60mo; never add the two.
    """
    import datetime as _dt

    from loci.model import dev_pipeline as dp

    boros = _parse_boroughs(boroughs)
    when = _dt.date.fromisoformat(asof) if asof else _dt.date.today()

    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    console.print(f"[dim]pipeline exposure for {','.join(boros)} as of {when} "
                  f"at {radius_m:.0f} m / {dp.WIDE_RADIUS_M:.0f} m network…[/]")
    df, report = dp.build_pipeline(con, boros, asof=when, radius_m=radius_m, dry_run=dry_run)
    written = report.pop("_written", None)

    console.print(f"{report['projects']:,} jobs in scope "
                  f"({report['large_projects']:,} of >= {dp.LARGE_UNITS} units; "
                  f"{report['projects_no_geom']:,} without a coordinate, dropped from the "
                  f"spatial measures) over {report['addresses']:,} addresses")
    for label, units in report["units_by_measure"].items():
        console.print(f"  citywide-in-scope units {label:<18} {int(units):>9,}")

    t = Table(title="pipeline exposure")
    t.add_column("measure"); t.add_column("addresses > 0", justify="right")
    t.add_column("median where > 0", justify="right"); t.add_column("max", justify="right")
    for col in [c for c in dp.PIPELINE_COLUMNS if c.startswith("units_")]:
        nz = df[col][df[col] > 0]
        t.add_row(col, f"{len(nz):,}", f"{nz.median():.0f}" if len(nz) else "-",
                  f"{df[col].max():,.0f}")
    console.print(t)
    console.print(f"addresses with a large project within {dp.DIST_LIMIT:.0f} m: "
                  f"{report['addresses_with_large_project']:,}")

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] annotated {written:,} rows -> analysis.address "
                  f"(pipeline columns; graph {report['graph_version']})")
    if not report.get("activity_evidence"):
        console.print("[yellow]note:[/] analysis.dev_pipeline carries no permit-activity "
                      "evidence, so units_active_400m / units_stalled_400m were written "
                      "NULL (not 0). Run `loci pipeline-activity` then re-run this.")


@app.command(name="pipeline-activity")
def pipeline_activity(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL (D48 default MN,BK)."),
    asof: str = typer.Option(None, help="Date the 12-month / 5-year rule counts back from (YYYY-MM-DD; default today)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch, classify and report; write nothing."),
) -> None:
    """Split `permitted` into permitted-and-building vs permitted-and-stalled.

    Fetches DOB permit issuance and RENEWAL dates (`ipu4-2q9a` for BIS jobs,
    `rbx6-tga4` for DOB NOW jobs, both daily) for every analysis.dev_pipeline
    job in stage permitted / partially_complete, and UPDATEs five columns on
    that table: last_permit_issued, last_permit_expires, permit_evidence_source,
    activity_status and permit_activity_asof.

    `stage` IS NOT TOUCHED -- it stays DCP-derived. activity_status is an
    orthogonal axis: "permitted AND building" is a two-column read. The rule
    (active <= 12 months, lapsed 0-12 months expired, stalled > 12 months
    expired or > 5 years quiet) and every caveat live in the header of
    sql/014_dev_pipeline_activity.sql. A renewed permit is evidence somebody
    paid a fee, NOT that concrete was poured; this separates abandoned from
    not-abandoned, which is the falsifiable half of the question.

    The address-grain measures (units_active_400m, units_stalled_400m) are
    written by `loci pipeline`, not here -- run this first, then `loci pipeline`.
    """
    import datetime as _dt

    from loci.sources.cities.nyc import dob_permits as dobp

    boros = tuple(_parse_boroughs(boroughs))
    when = _dt.date.fromisoformat(asof) if asof else _dt.date.today()

    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    console.print(f"[dim]permit activity for {','.join(boros)} as of {when} "
                  f"({dobp.BIS_DATASET} + {dobp.NOW_DATASET})…[/]")
    out, report = dobp.build(con, boros, asof=when, dry_run=dry_run)
    written = report.pop("_written", None)

    console.print(f"{report['jobs_in_scope']:,} jobs in scope "
                  f"({report['bis_jobs']:,} BIS + {report['now_jobs']:,} DOB NOW"
                  + (f" + {report['other_shape']:,} unrecognised" if report["other_shape"] else "")
                  + f") · {report['bis_permit_rows']:,} + {report['now_permit_rows']:,} permit rows "
                  f"-> {report['jobs_with_evidence']:,} jobs with evidence, "
                  f"{report['jobs_without_evidence']:,} without")
    console.print(f"{report['renewed_last_12mo']:,} jobs issued or renewed a permit in the "
                  f"last {dobp.ACTIVE_MONTHS} months")

    t = Table(title=f"activity_status — {','.join(boros)} {'/'.join(dobp.ACTIVITY_STAGES)}")
    t.add_column("activity_status"); t.add_column("jobs", justify="right")
    t.add_column("net units", justify="right")
    for status in dobp.ACTIVITY_STATUSES:
        row = report["by_status"].get(status)
        if row:
            t.add_row(status, f"{int(row['count']):,}", f"{int(row['sum'] or 0):,}")
    console.print(t)

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] {written:,} jobs annotated -> analysis.dev_pipeline "
                  f"(activity columns; `stage` untouched)")
    console.print("[dim]next:[/] `loci pipeline` to push units_active_400m / "
                  "units_stalled_400m onto analysis.address.")


@app.command(name="ingest-storefronts")
def ingest_storefronts(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL (D48 default MN,BK)."),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-download the CSV even if data/raw/ already has it."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Download, transform and report; write nothing."),
) -> None:
    """Land the NYC DOF Storefront Registry (Local Law 157, `92iy-9c3n`) into
    analysis.storefront -- ONE ROW PER STOREFRONT PER FILING.

    The ~99 MB CSV export is STREAMED to data/raw/ and the whole normalisation
    runs as one query inside DuckDB; the 414,884 source rows never enter Python.

    Read sql/012_storefront_registry.sql before changing anything. Two things
    in that header decide whether the numbers mean anything: (1) DOF assigns no
    storefront identifier and `unit` is blank on 87% of rows, so NOTHING is
    ever collapsed -- four identical rows at one address are four ground
    floors, and fusing them would delete three of them; (2) five of the eleven
    filings contain ONLY storefronts reported vacant, so pooling them with the
    full filings reads as a 100% vacancy rate. `universe` carries that and is
    derived from the data, not hard-coded.
    """
    import datetime as _dt

    from loci.sources.cities.nyc import storefront_registry as sr

    boros = tuple(_parse_boroughs(boroughs))
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    console.print(f"[dim]fetching DOF {sr.DATASET} (streamed to disk) for "
                  f"{','.join(boros)}…[/]")
    report = sr.build(con, boros, dry_run=dry_run, force_download=refresh,
                      asof=_dt.date.today())
    written = report.pop("_written", None)

    console.print(f"CSV {report['csv_bytes']/1e6:.1f} MB at {report['csv_path']} · "
                  f"vintage [bold]{report['vintage']}[/]")
    console.print(f"{report['rows']:,} storefront-filing rows over "
                  f"{report['premises']:,} premises and {report['filings']} filings "
                  f"· {report['no_geom']:,} without any coordinate")

    t = Table(title=f"analysis.storefront — {','.join(boros)}")
    for c in ("filing due", "period", "universe", "12/31", "6/30", "rows",
              "premises", "vac 12/31", "vac 6/30", "w/ lease"):
        t.add_column(c, justify="right" if c not in ("period", "universe") else "left")
    for r in report["by_filing"].itertuples():
        t.add_row(str(r.filing_due_date), str(r.period), str(r.universe),
                  str(r.obs_1231 or "-"), str(r.obs_0630 or "-"),
                  f"{r.rows_in:,}", f"{r.premises:,}",
                  f"{r.vac_1231:,}", f"{r.vac_0630:,}", f"{r.with_lease:,}")
    console.print(t)
    console.print("[bold]geometry source:[/] " + " · ".join(
        f"{r.src} {r.n:,}" for r in report["geom_source"].itertuples()))

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] {written:,} rows -> analysis.storefront")


@app.command()
def storefronts(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL (D48 default MN,BK)."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Catchment radius in NETWORK metres (default 400 = the 5-min tier)."),
    asof: str = typer.Option(None, "--asof",
                             help="Observation date to snapshot (YYYY-MM-DD; default the "
                                  "latest FULL-universe 12/31 in analysis.storefront)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Annotate analysis.address with storefront-vacancy exposure.

    For every address: how many registered storefronts were reported VACANT on
    the snapshot's 12/31 within a 5-minute (400 m) NETWORK walk, how many
    registered storefronts there are in total at that radius (the denominator),
    and the nearest vacant one -- its id, its last reported business activity
    and whether its lease had expired.

    The default snapshot is the latest FULL-universe observation, not the
    latest observation. The vacant-only supplements are fresher but have no
    denominator, so counting them gives a numerator with nothing to divide by
    and a ~60% undercount (sql/012 caveat 4). `--asof 2023-12-31` is the
    lease-complete view: DOF stopped publishing the lease field on the annual
    file after the 2024-06-03 release.

    UPDATE-only on analysis.address (model/storefronts.STOREFRONT_COLUMNS,
    pinned disjoint from the screen's own columns, from D62's PIPELINE_COLUMNS
    and from D63's age_fit columns) -- vacancy is an ACTIONABILITY annotation,
    never a filter: it cannot move gap_score, lead_category, n_missing or
    eligible. `vacant_storefronts_400m` is a SUBSET of `storefronts_400m`;
    never add the two.
    """
    import datetime as _dt

    from loci.model import storefronts as sf
    from loci.sources.cities.nyc import storefront_registry as sr

    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    when = _dt.date.fromisoformat(asof) if asof else sr.latest_full_observation(con, boros)
    if when is None:
        console.print("[yellow]analysis.storefront is empty for these boroughs -- "
                      "run `loci ingest-storefronts` first[/]")
        raise typer.Exit(1)
    if abs(radius_m - sf.DEFAULT_RADIUS_M) > 1e-6:
        console.print(f"[yellow]warning:[/] --radius-m {radius_m:.0f} differs from the "
                      f"{sf.DEFAULT_RADIUS_M:.0f} m the COLUMN NAMES encode; the values "
                      f"will be at {radius_m:.0f} m and the names will still say 400.")

    console.print(f"[dim]storefront vacancy for {','.join(boros)} as of {when} "
                  f"at {radius_m:.0f} m network…[/]")
    df, report = sf.build_storefronts(con, boros, when, radius_m=radius_m, dry_run=dry_run)
    written = report.pop("_written", None)

    if report["universe"] != "full":
        console.print(f"[yellow]warning:[/] the only filing observing {when} is "
                      f"{report['universe']} -- `storefronts_400m` is NOT a universe "
                      f"count and the rate it implies is not a rate.")
    console.print(f"{report['storefronts']:,} storefronts in the {report['universe']} "
                  f"filing due {report['filing_due_date']} "
                  f"over {report['premises']:,} premises · "
                  f"[bold]{report['storefronts_vacant']:,} vacant[/] "
                  f"({100*report['vacancy_rate']:.2f}%) · "
                  f"{report['construction_reported']:,} reporting construction · "
                  f"{report['vacant_with_lease']:,} vacant rows carry a lease expiry")

    t = Table(title=f"storefront exposure — {','.join(boros)} @ {when}")
    t.add_column("measure"); t.add_column("addresses > 0", justify="right")
    t.add_column("median where > 0", justify="right"); t.add_column("max", justify="right")
    for col in ("vacant_storefronts_400m", "storefronts_400m"):
        nz = df[col][df[col] > 0]
        t.add_row(col, f"{len(nz):,}", f"{nz.median():.0f}" if len(nz) else "-",
                  f"{df[col].max():,.0f}")
    console.print(t)
    console.print(f"addresses with a vacant storefront within {sf.DIST_LIMIT:.0f} m: "
                  f"{report['addresses_with_vacant']:,} of {report['addresses']:,}")

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] annotated {written:,} rows -> analysis.address "
                  f"(storefront columns; graph {report['graph_version']})")


age_fit_app = typer.Typer(add_completion=False, help=(
    "The age-fit ranking signal: SUPPLY-REVEALED age multipliers, one curve per "
    "fitted category, estimated from New York's own composition of supply "
    "(docs/bar_age_nyc.md) rather than from the BLS CEX household survey that "
    "docs/age_demand_fit.md rejected. D63 shipped `bar`; D64 adds `childcare` "
    "under the SAME F2/F3 gate, unrelaxed (QUESTIONS D15). Every category NOT "
    "in the registry keeps a NULL age_fit, because no curve exists for it -- "
    "NULL is not 1.0. NON-FILTERING: `fit` and `apply` never touch gap_score, "
    "ratio, nearest_m, eligible, lead_category, n_missing or cluster_id; "
    "gap_score_fit is a SECOND ranking column beside gap_score. `fit` exits "
    "NON-ZERO and writes nothing if a curve fails its own F2/F3 criterion."))
app.add_typer(age_fit_app, name="age-fit")


def _age_fit_categories(category: str) -> list[str]:
    """`--category all` (the default) is every category in the registry; a
    single name is just that one. An unknown name RAISES rather than silently
    fitting nothing, because "nothing was written" and "the typo'd category has
    no curve" look identical in the output otherwise."""
    from loci.model import age_fit as af

    if category.lower() in ("all", "*"):
        return list(af.FITTED_CATEGORIES)
    cats = [c.strip() for c in category.split(",") if c.strip()]
    for c in cats:
        try:
            af.spec_for(c)        # raises ValueError naming the fitted set
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
    return cats


def _print_curve(fit: dict) -> None:
    """One fitted curve: coefficients with their Conley SEs, the contrast the F2
    gate reads, and the dispersion gate F3 reads."""
    from loci.model import age_fit as af

    t = Table(title=f"{fit['category']} — {fit['spec']} — n = {fit['n_tracts']:,} "
                    f"tracts, R\u00b2 = {fit['r_squared']:.3f}, r = {fit['radius_m']:.0f} m")
    t.add_column("term"); t.add_column("coef", justify="right")
    t.add_column("Conley se", justify="right"); t.add_column("t", justify="right")
    for term in fit["age_terms"]:
        mark = " *" if term == fit["primary_age_term"] else ""
        t.add_row(f"{term}{mark}", f"{fit['coefs'][term]:+.3f}",
                  f"{fit['se_conley'][term]:.3f}", f"{fit['t_conley'][term]:+.2f}")
    console.print(t)
    console.print("[dim]* the primary demand variable for this category[/]")

    c = fit["contrast"]
    label = (f"{c['from_name'] or c['from_nta']} -> {c['to_name'] or c['to_nta']}")
    console.print(f"{label} partial effect: [bold]{c['pooled']['ratio']:.3f}[/] "
                  f"Conley 95% CI [{c['pooled']['ci_low']:.3f}, "
                  f"{c['pooled']['ci_high']:.3f}] (pooled; contrast {c['kind']}"
                  + (f" on {c['variable']}" if c["variable"] else "") + ")")
    for boro, b in sorted(fit["by_borough"].items()):
        bc = b["contrast"]
        coefs = "  ".join(f"{k}={v:+.3f}" for k, v in b["coefs"].items())
        console.print(f"  {boro} only (n={b['n_tracts']:,}): {coefs}  "
                      f"ratio {bc['ratio']:.3f} "
                      f"CI [{bc['ci_low']:.3f}, {bc['ci_high']:.3f}]")
    m = fit["multiplier"]
    console.print(f"multiplier over estimation tracts: p10/p50/p90 = "
                  f"{m['p10']:.3f} / {m['p50']:.3f} / {m['p90']:.3f}; "
                  f"spread {m['spread']:.3f} vs median MOE {m['median_moe']:.3f} "
                  f"-> dispersion [bold]{m['dispersion_ratio']:.2f}\u00d7[/] "
                  f"(gate needs >= {af.DISPERSION_GATE_MIN})")
    for name, rob in sorted((fit.get("robustness") or {}).items()):
        if "skipped" in rob:
            console.print(f"[dim]robustness {name}: skipped ({rob['skipped']})[/]")
            continue
        bk = (rob.get("by_borough") or {}).get("BK", {})
        bkc = bk.get("contrast", {})
        coefs = "  ".join(f"{k}={v:+.3f} (se {rob['se_conley'][k]:.3f})"
                          for k, v in rob["coefs"].items())
        console.print(f"[dim]robustness {name} [{rob['outcome']}]: {coefs}; "
                      f"BK ratio {bkc.get('ratio', float('nan')):.3f} "
                      f"CI [{bkc.get('ci_low', float('nan')):.3f}, "
                      f"{bkc.get('ci_high', float('nan')):.3f}] "
                      f"-- REPORTED, NOT SHIPPED[/]")
    console.print(f"[dim]inputs {fit['inputs']['hash']}: supply "
                  f"{fit['inputs']['supply_hash']}, ACS {fit['inputs']['acs_year']}, "
                  f"{fit['inputs']['n_target']:,} outcome records of "
                  f"{fit['inputs']['n_universe']:,} in the denominator[/]")


@age_fit_app.command("fit")
def age_fit_fit(
    category: str = typer.Option("all", "--category",
                                 help="One of the registry categories "
                                      "(age_fit.FITTED_CATEGORIES), or 'all' "
                                      "(default)."),
    boroughs: str = typer.Option("MN,BK", help="Estimation sample (D48 default MN,BK)."),
    acs_year: int = typer.Option(None, help="ACS vintage; default the pinned 2023."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Estimate and print; write no JSON."),
) -> None:
    """Re-estimate one or every category's age curve and write the coefficients.

    SUPPLY-REVEALED. `bar` is the COMPOSITION spec of docs/bar_age_nyc.md §7:
    outcome = bar-type share of on-premises SLA licences within 400 m of the
    tract's residential centroid. `childcare` (D64) is the same shape at the
    category's own 640 m reach tier, outcome = childcare share of ALL canonical
    POIs, with `under_18_share` as the primary demand regressor. Both carry
    bar's controls (log units, log(1 + CNS07 retail jobs), log walk-to-subway,
    log median household income, renter share, borough FE) and Conley
    spatial-HAC standard errors (Bartlett, 2 km), because the residuals' Moran's
    I is ~0.42 and HC3 is unusable.

    THE F2 GATE IS ENFORCED HERE, NOT DOCUMENTED HERE, AND IS THE SAME FOR EVERY
    CATEGORY (QUESTIONS D15: corroboration is not a licence to relax it). If a
    curve's Brooklyn-only Conley CI on its own low-age -> high-age contrast
    includes 1.0 or carries the wrong sign, or the dispersion gate (p90-p10 of
    the multiplier over the estimation tracts / median MOE) falls below 1.0,
    this command exits non-zero and writes NOTHING for that category: the
    multiplier must not be applied from a curve that fails its own criterion,
    and Brooklyn is where 98% of the bar-lead gap set lives.
    """
    from loci.model import age_fit as af

    cats = _age_fit_categories(category)
    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=True)   # estimation NEVER writes to the database
    failures: list[str] = []
    for cat in cats:
        spec = af.spec_for(cat)
        console.print(f"[dim]estimating {spec.spec_version} for {cat} on "
                      f"{','.join(boros)} (ACS {acs_year or af.ACS_YEAR}, "
                      f"r = {spec.radius_m:.0f} m, Conley "
                      f"{af.CONLEY_CUTOFF_M:.0f} m)\u2026[/]")
        try:
            fit, path = af.fit_curve(con, cat, boros,
                                     acs_year=acs_year or af.ACS_YEAR, dry_run=dry_run)
        except af.AgeFitGateFailure as exc:
            console.print(f"[red]GATE FAILED[/] {exc}")
            failures.append(cat)
            continue
        _print_curve(fit)
        if path is None:
            console.print("[dim]--dry-run:[/] gates pass, nothing written.")
        else:
            console.print(f"[green]ok[/] gates pass -> {path}")
    if failures:
        raise typer.Exit(1)


@age_fit_app.command("apply")
def age_fit_apply(
    category: str = typer.Option("all", "--category",
                                 help="One of the registry categories "
                                      "(age_fit.FITTED_CATEGORIES), or 'all' "
                                      "(default)."),
    boroughs: str = typer.Option("MN,BK", help="Where to apply (D48 default MN,BK)."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Compute and print the summary; write nothing."),
) -> None:
    """Write `age_fit` onto each fitted category's rows and `gap_score_fit`
    beside `gap_score`.

    UPDATE-ONLY on analysis.address_category (age_fit, age_fit_moe,
    age_fit_source) and analysis.address (age_fit_lead, age_fit_lead_moe,
    gap_score_fit). Both SET lists are asserted disjoint from the screen's own
    columns before either UPDATE runs, so this command cannot move gap_score,
    ratio, nearest_m, eligible, lead_category, n_missing or cluster_id -- the
    gap set is bit-identical before and after, and a test pins that.

    Every category NOT in the registry keeps a NULL age_fit (no curve exists),
    and age_fit_lead is exactly 1.0 wherever the lead category has no fitted
    curve, so gap_score_fit == gap_score there. Refuses to run if a stored curve
    was fitted against a different supply set or ACS vintage than the database
    now holds -- a supply-revealed coefficient is only valid against the supply
    set it was revealed from.
    """
    from loci.model import age_fit as af

    cats = _age_fit_categories(category)
    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    # `--category all` tolerates a registry category with no curve on disk --
    # that is exactly the state a category sits in when its F2/F3 gate failed
    # and `fit` therefore wrote nothing. Its rows are still RESET to NULL, so
    # the map reads "no curve" rather than a stale multiplier. Naming a
    # category explicitly still fails loudly.
    everything = set(cats) == set(af.FITTED_CATEGORIES)
    try:
        fits = af.load_fits(cats, missing_ok=everything)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    missing = sorted(set(cats) - set(fits))
    if missing:
        console.print(f"[yellow]no curve on disk[/] for {', '.join(missing)} — "
                      "never fitted, or the fit failed its own F2/F3 gate and "
                      "wrote nothing. Those rows are reset to NULL, not left stale.")
    if not everything:
        console.print(f"[yellow]partial apply[/] {', '.join(cats)} of "
                      f"{', '.join(af.FITTED_CATEGORIES)}: the reset pass is scoped "
                      "to these categories, so the others keep their last run's "
                      "values rather than being blanked.")
    try:
        cat_df, addr_df, report = af.apply_age_fit(con, boros, fits=fits,
                                                   dry_run=dry_run, categories=cats)
    except af.AgeFitStale as exc:
        console.print(f"[red]STALE CURVE[/] {exc}")
        raise typer.Exit(1) from exc

    t = Table(title="applied curves")
    t.add_column("category"); t.add_column("spec")
    t.add_column("rows", justify="right"); t.add_column("coefficients")
    t.add_column("p10/p50/p90", justify="right")
    for cat, pc in report["per_category"].items():
        t.add_row(cat, str(pc["spec"]), f"{pc['n_rows']:,}",
                  "  ".join(f"{k}={v:+.3f}" for k, v in pc["coefs"].items()),
                  ("—" if pc["p50"] is None else
                   f"{pc['p10']:.3f} / {pc['p50']:.3f} / {pc['p90']:.3f}"))
    console.print(t)
    console.print(f"{report['n_category_rows']:,} fitted (address, category) rows "
                  f"over {report['n_addresses']:,} addresses; "
                  f"{report['n_lead_multiplied']:,} addresses have a FITTED lead and "
                  f"are actually re-weighted")
    if report["fitted_p50"] is not None:
        console.print(f"age_fit (all categories pooled) p10/p50/p90 = "
                      f"{report['fitted_p10']:.3f} / "
                      f"{report['fitted_p50']:.3f} / {report['fitted_p90']:.3f}  "
                      f"(min {report['fitted_min']:.3f}, max {report['fitted_max']:.3f}, "
                      f"median MOE {report['moe_median']:.3f})")
    assert report["n_missing_moe"] == 0, "a fitted row without an MOE is a bug"
    console.print(f"[yellow]{af.AGE_FIT_DISCLAIMER}[/]")
    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] {report['written_category_rows']:,} rows -> "
                  f"analysis.address_category (age_fit columns), "
                  f"{report['written_address_rows']:,} rows -> analysis.address "
                  f"(age_fit_lead, gap_score_fit)")


density_elasticity_app = typer.Typer(add_completion=False, help=(
    "The per-category clustering-vs-saturation coefficient (D68 -> GTM-138). "
    "One `beta` per category from the ZIP x category ZBP panel 2013->2023 on "
    "MN+BK ZIPs with 2013 population >= 5,000: beta > 0 means ZIPs already "
    "dense in the category added MORE of it (CLUSTERING), beta < 0 means they "
    "added less (SATURATION). It tells the grade which categories reward "
    "proximity to incumbents and which are punished by it. It is NOT a "
    "forecast -- D68 established headroom has no out-of-sample skill -- and "
    "it is not causal: the 2013 count sits on both sides of the equation, so "
    "the bias runs toward `saturating` and a clustering verdict is the "
    "conservative one. `fit` exits NON-ZERO and writes nothing unless the "
    "estimate clears its own gate."))
app.add_typer(density_elasticity_app, name="density-elasticity")


def _de_table(cats: dict, title: str) -> Table:
    """One form's coefficients, with everything the classification read."""
    t = Table(title=title)
    for col, just in (("category", "left"), ("beta", "right"), ("beta_std", "right"),
                      ("Conley t", "right"), ("HC3 t", "right"), ("n", "right"),
                      ("regime", "left"), ("LOZO", "right"), ("placebo p90", "right"),
                      ("Moran I", "right")):
        t.add_column(col, justify=just)
    for cat, v in sorted(cats.items()):
        colour = {"clustering": "green", "saturating": "yellow"}.get(v["regime"], "dim")
        t.add_row(cat, f"{v['beta']:+.3f}", f"{v['beta_std']:+.3f}",
                  f"{v['t_conley']:+.2f}", f"{v['t_hc3']:+.2f}", f"{v['n_zips']}",
                  f"[{colour}]{v['regime']}[/]", f"{v['lozo']['stability']:.2f}",
                  "—" if v["placebo"]["p90"] is None else f"{v['placebo']['p90']:.3f}",
                  "—" if v["moran"]["i"] is None
                  else f"{v['moran']['i']:+.3f}"
                       + ("*" if v["moran"]["p_perm"] < 0.05 else ""))
    t.caption = ("beta_std = beta x sd(regressor), the scale on which the placebo "
                 "is compared; * = Moran's I permutation p < 0.05 (residuals "
                 "spatially autocorrelated, which is why the gate reads the "
                 "Conley t and not the HC3 one)")
    return t


@density_elasticity_app.command("fit")
def density_elasticity_fit(
    bandwidth_km: float = typer.Option(3.0, "--bandwidth-km",
                                       help="Conley spatial-HAC bandwidth on ZCTA "
                                            "centroids (Bartlett kernel)."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Estimate and print both forms; write nothing."),
) -> None:
    """Re-estimate beta per category and write src/loci/model/density_elasticity.yaml.

    Reads `analysis.zip_category_establishments` READ ONLY (retrying the lock a
    concurrent writer holds) plus the cached ZCTA ACS and ZBP base-year pulls
    under data/raw/; it deliberately touches neither analysis.address nor
    analysis.address_category.

    BOTH functional forms are estimated every run -- the log form (the stated
    primary) and the level form -- each with HC3 and Conley SEs, Moran's I on
    the residuals, leave-one-ZIP-out sign stability and a placebo distribution
    built from every OTHER category's 2013 density. The log form is adopted
    unless it fails its gate, in which case the level form is promoted and the
    reason is recorded in the YAML. Gates first, write second: if no form
    clears, this exits NON-ZERO and leaves the previous YAML untouched, so a
    failed re-fit degrades to "yesterday's coefficients, explicitly stale"
    rather than "today's, quietly invalid".
    """
    from loci.model import density_elasticity as de

    try:
        doc, result, _ = de.fit(bandwidth_m=bandwidth_km * 1000.0, dry_run=True)
    except de.DensityElasticityGateFailure as exc:   # pragma: no cover
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    for form in de.FORM_ORDER:
        mark = " [green](ADOPTED)[/]" if form == result["adopted_form"] else ""
        console.print(_de_table(result["forms"][form]["categories"],
                                f"{form} form — {de.FORMS[form]['label']}{mark}"))
        bad = result["form_gate"].get(form) or []
        if bad:
            console.print(f"  [yellow]form `{form}` not admissible:[/] " + "; ".join(bad))
    for cat, why in sorted(result["skipped"].items()):
        console.print(f"[dim]not fitted:[/] {cat} — {why}")
    console.print(f"[yellow]{de.DISCLAIMER}[/]")

    bad = de.gate_failures(result)
    if bad:
        console.print("[red]GATE FAILED — nothing written:[/] " + "; ".join(bad))
        console.print("[dim]The gate requires a category in every regime "
                      f"({', '.join(de.REQUIRED_REGIMES)}). Relaxing "
                      "REQUIRED_REGIMES is an owner decision with a decision-log "
                      "entry, not a quiet edit.[/]")
        raise typer.Exit(1)
    if dry_run:
        console.print("[dim]--dry-run:[/] gate passes; nothing written.")
        raise typer.Exit(0)
    written = de.write_if_gate_passes(doc, result)
    console.print(f"[green]ok[/] adopted `{result['adopted_form']}` form -> {written}")


@density_elasticity_app.command("show")
def density_elasticity_show() -> None:
    """Print the shipped coefficients and what each regime means for the grade."""
    from loci.model import density_elasticity as de

    try:
        doc = de.load()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    t = Table(title=f"density elasticity — {doc['adopted_form']} form, "
                    f"fitted {doc['fitted_at']}")
    for col in ("category", "beta", "Conley t", "n", "regime", "LOZO", "placebo p90"):
        t.add_column(col, justify="left" if col in ("category", "regime") else "right")
    for cat, v in sorted(doc["categories"].items()):
        if v["regime"] == "not_fitted":
            t.add_row(cat, "—", "—", "—", "[dim]not fitted[/]", "—", "—")
            continue
        colour = {"clustering": "green", "saturating": "yellow"}.get(v["regime"], "dim")
        t.add_row(cat, f"{v['beta']:+.3f}", f"{v['t_conley']:+.2f}", str(v["n_zips"]),
                  f"[{colour}]{v['regime']}[/]", f"{v['lozo_sign_stability']:.2f}",
                  "—" if v["placebo_p90"] is None else f"{v['placebo_p90']:.3f}")
    console.print(t)
    console.print(f"form: {doc['form']}\nbeta units: {doc['beta_units']}")
    console.print(f"inference: {doc['inference']}\nrule: {doc['rule']['text']}")
    console.print("[bold]for the grade:[/] saturating -> demand pool ÷ incumbents; "
                  "clustering -> incumbents count in favour, cap from spend per "
                  "resident by age/income; no_signal -> residents only; "
                  "not_fitted -> no coefficient (NULL is not 1.0).")
    console.print(f"[yellow]{doc['disclaimer']}[/]")


@app.command(name="supply-ratio")
def supply_ratio(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL (D48 default MN,BK)."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Catchment radius in NETWORK metres (default 400 = the 5-min tier)."),
    supply_set: str = typer.Option(SUPPLY_DEFAULT, "--supply-set",
                                   help="Which POIs count as supply (default: principled, D52/D59)."),
    fit_baseline: bool = typer.Option(False, "--fit-baseline",
                                      help="Re-fit and REWRITE model/supply_baseline.yaml from this "
                                           "run. NOT part of the re-apply path."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Supply INTENSITY: how much of each category is within reach per 1,000 homes.

    The address screen answers "is the nearest business further than the
    category's reach". That is the wrong statistic for a category that is
    PRESENT but THIN -- one pharmacy 380 m away clears the test while the same
    walk elsewhere passes eight. This measures the other thing, per address:

        supply_400m  principled POIs of the category within 400 m network
        homes_400m   residential units within the same 400 m
        supply_per_1k = supply_400m / homes_400m * 1000
        supply_ratio_vs_base = supply_per_1k / the MN+BK median

    and, for laundry only, `addressable_homes_400m_laundry` -- homes_400m less
    a per-building haircut for in-unit and in-building laundry
    (model/laundry_haircut.yaml: NYCHVS 2023 for 1- and 2-unit structures,
    owner-adjustable priors above that, a positive
    analysis.address_laundry_evidence assertion overriding to 1.0).

    Counts come from `analysis.poi_supply WHERE in_principled` and NEVER from
    in_all; the live supply_hash is stamped on every row and compared with the
    baseline YAML's, because poi_supply is a VIEW and moves under you.

    UPDATE-only on analysis.address (five columns) and analysis.address_category
    (three), both pinned disjoint from the screen's own columns and from every
    other annotation. Intensity is a SECOND reading beside the screen, never a
    filter on it: a thin category does not become a gap and a thick one does
    not stop being one.

    RE-APPLY after a screen re-run with exactly this, and nothing else:

        loci supply-ratio --boroughs MN,BK

    It rebuilds all eight columns from the warehouse and the committed
    baseline; it does NOT re-baseline (that would measure every run against
    itself). Run it after `loci pipeline`, `loci storefronts` and age-fit.
    """
    from loci.model import supply_ratio as sr

    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    if abs(radius_m - sr.DEFAULT_RADIUS_M) > 1e-6:
        console.print(f"[yellow]warning:[/] --radius-m {radius_m:.0f} differs from the "
                      f"{sr.DEFAULT_RADIUS_M:.0f} m the COLUMN NAMES encode; the values "
                      f"will be at {radius_m:.0f} m and the names will still say 400.")

    console.print(f"[dim]supply intensity for {','.join(boros)} at {radius_m:.0f} m "
                  f"network, supply set '{supply_set}'…[/]")
    addr, long_df, report = sr.build_supply_ratio(
        con, boros, radius_m=radius_m, supply_set=supply_set,
        fit_baseline=fit_baseline, dry_run=dry_run)

    if report.get("baseline_hash") and report["baseline_hash"] != report["supply_hash"]:
        console.print(f"[yellow]warning:[/] baseline YAML was fitted on supply "
                      f"{report['baseline_hash']} but the live set is "
                      f"{report['supply_hash']} — the ratios mix two supply sets. "
                      f"Re-fit with --fit-baseline once the set has settled.")
    if not report["have_evidence_table"]:
        console.print("[yellow]warning:[/] analysis.address_laundry_evidence is absent — "
                      "every building keeps its size-class prior, which OVERSTATES the "
                      "addressable laundry pool.")

    console.print(f"{report['pois']:,} POIs in the '{report['supply_set']}' set "
                  f"(hash {report['supply_hash']}) · {report['home_rows']:,} addresses "
                  f"carry homes · {report['evidence_bbls']:,} BBLs have positive laundry "
                  f"evidence · {report['query_nodes']:,} distinct graph nodes swept")

    base = report.get("baselines") or {}
    t = Table(title=f"supply intensity — {','.join(boros)} @ {radius_m:.0f} m network")
    for col, j in (("category", "left"), ("supply_400m med", "right"),
                   ("homes_400m med", "right"), ("per 1k med", "right"),
                   ("baseline per 1k", "right"), ("aggregate per 1k", "right")):
        t.add_column(col, justify=j)
    med_homes = float(addr["homes_400m"].median())
    for cat in sorted(base) or []:
        s = long_df[long_df["category"] == cat]
        b = base[cat] or {}
        bv = sr.baseline_of(b)
        t.add_row(cat, f"{s['supply_400m'].median():.0f}", f"{med_homes:.0f}",
                  "—" if b.get("median") is None else f"{b['median']:.3f}",
                  "—" if bv is None else f"{bv:.3f} ({b.get('estimator', 'median')})",
                  "—" if b.get("aggregate_per_1k") is None else f"{b['aggregate_per_1k']:.3f}")
    console.print(t)
    n_nodenom = int((addr["homes_400m"] <= 0).sum())
    console.print(f"addresses with NO homes within {radius_m:.0f} m (supply_per_1k is "
                  f"NULL there, not 0): {n_nodenom:,} of {len(addr):,}")
    console.print(f"laundry demand pool: {addr['homes_400m'].sum():,.0f} home-slots within "
                  f"reach, of which {addr['addressable_homes_400m_laundry'].sum():,.0f} "
                  f"({100 * addr['addressable_homes_400m_laundry'].sum() / max(addr['homes_400m'].sum(), 1):.0f}%) "
                  f"survive the in-home haircut (v{report['haircut_version']})")

    if fit_baseline and not dry_run:
        console.print(f"[green]baseline written[/] -> {report['baseline_written']}")
    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] {report['_written_address']:,} rows -> analysis.address · "
                  f"{report['_written_category']:,} rows -> analysis.address_category "
                  f"(graph {report['graph_version']})")


@app.command(name="address-access")
def address_access(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Catchment radius in NETWORK metres (default 400 = the 5-min tier)."),
    months: int = typer.Option(3, "--months",
                               help="How many of the ridership feed's latest FULL months "
                                    "to average (3 = one quarter, 12 = a trailing year)."),
    complex_point: bool = typer.Option(False, "--complex-point",
                                       help="Snap each complex's entries to its own published "
                                            "point instead of splitting them over entrances. "
                                            "Coarser at 400 m; use only if i9wp-a4ja is down."),
    jobs_vintage: int = typer.Option(2023, "--jobs-vintage",
                                     help="LODES8 WAC vintage on disk (data/raw/lodes)."),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-pull the MTA feeds instead of using data/raw/mta cache."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Present-day NON-RESIDENTIAL demand at address grain, beside homes_400m.

        transit_entries_400m  average weekday daily subway ENTRIES at station
                              complexes within 400 m NETWORK metres
        jobs_400m             LODES8 WAC total jobs (C000, all sectors) in
                              census blocks within the same 400 m

    `homes_400m` is the resident half of demand and is currently the only half
    the screen can see. Two addresses with the same homes_400m are the same
    number downstream and are not the same retail location if one is 80 m from
    a complex putting 30,000 people on the sidewalk each weekday.

    Same engine as every other catchment column -- score/access._prune +
    _to_csr, then scipy Dijkstra on the pedestrian walk graph, sourced from the
    query nodes. No ST_DWithin and no straight line anywhere: 400 m of NETWORK
    distance is the project's one definition of "within reach".

    EVERY ADDRESS GETS BOTH VALUES. 0 means "nothing within a five-minute
    walk" -- a measurement, not a missing value -- and there is no censoring to
    record, because a catchment sum inside a hard radius has no ceiling the way
    a right-censored `nearest_m` does.

    UPDATE-only on analysis.address (seven columns), pinned disjoint from the
    screen's own columns and from every sibling annotation. These do NOT enter
    gap_score, supply_ratio_vs_base or any recommendation grade.

    Caveats that ride with the numbers: subway ENTRIES are not footfall (they
    are the morning-outbound direction at a residential complex); the default
    window is three SUMMER months; LODES counts payroll jobs at a block
    CENTROID, not people on a sidewalk. Never add these two to each other or
    to homes_400m -- they overlap by construction.

    RE-APPLY AFTER EVERY SCREEN RE-RUN. `loci address-gaps` DELETEs and
    re-INSERTs analysis.address, so these seven columns come back NULL exactly
    as every other annotation does. Run this in the same re-apply sequence as
    `loci pipeline`, `loci storefronts`, age-fit and `loci supply-ratio`;
    `access_run_at IS NULL` is the flag that says it has not been.

        loci address-access --boroughs MN,BK
    """
    from loci.model import address_access as aa

    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    if abs(radius_m - aa.DEFAULT_RADIUS_M) > 1e-6:
        console.print(f"[yellow]warning:[/] --radius-m {radius_m:.0f} differs from the "
                      f"{aa.DEFAULT_RADIUS_M:.0f} m the COLUMN NAMES encode; the values "
                      f"will be at {radius_m:.0f} m and the names will still say 400 "
                      f"(access_radius_m records what was actually used).")

    console.print(f"[dim]walkable transit entries + jobs for {','.join(boros)} at "
                  f"{radius_m:.0f} m network…[/]")
    df, report = aa.build_access(
        con, boros, radius_m=radius_m, months=months,
        use_entrances=not complex_point, jobs_vintage=jobs_vintage,
        refresh=refresh, dry_run=dry_run)

    t = report["transit"]
    console.print(f"ridership {t['dataset_id']} · window [bold]{report['transit_window']}[/] "
                  f"({t['n_weekdays']} weekdays, federal holidays excluded) · "
                  f"{t['complexes']:,} complexes · {t['total_entries_per_weekday']:,.0f} "
                  f"entries per average weekday citywide")
    console.print(f"snap '[bold]{t['snap']}[/]' · {t['weight_points']:,} weight points "
                  f"({t['complexes_without_entrances']} complexes fell back to their "
                  f"published point)")
    console.print(f"LODES WAC {report['jobs_vintage']} column {report['jobs_column']} · "
                  f"{report['job_blocks']:,} blocks with jobs inside the walk-graph bbox "
                  f"· {report['job_total_in_bbox']:,.0f} jobs")
    console.print(f"{report['addresses']:,} addresses over {report['query_nodes']:,} "
                  f"distinct graph nodes (graph {report['graph_version']})")

    tab = Table(title=f"walkable demand — {','.join(boros)} @ {radius_m:.0f} m network")
    for col, j in (("borough", "left"), ("addresses", "right"),
                   ("transit >0", "right"), ("transit p50", "right"),
                   ("transit p90", "right"), ("jobs >0", "right"),
                   ("jobs p50", "right"), ("jobs p90", "right")):
        tab.add_column(col, justify=j)
    for b in [*boros, "ALL"]:
        s = df if b == "ALL" else df[df["borough"] == b]
        if s.empty:
            continue
        te, jo = s["transit_entries_400m"], s["jobs_400m"]
        tab.add_row(b, f"{len(s):,}",
                    f"{(te > 0).mean():.0%}", f"{te.median():,.0f}", f"{te.quantile(0.9):,.0f}",
                    f"{(jo > 0).mean():.0%}", f"{jo.median():,.0f}", f"{jo.quantile(0.9):,.0f}")
    console.print(tab)
    console.print(f"[dim]zero is an observation ('nothing within {radius_m:.0f} m'), not a "
                  f"missing value; {report['addresses_censored']} addresses are censored "
                  f"(a catchment sum inside a hard radius cannot be).[/]")

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] {report['_written']:,} rows -> analysis.address")


@app.command(name="validate-pedestrian")
def validate_pedestrian(
    radius_m: float = typer.Option(400.0, "--radius-m", help="Catchment radius, NETWORK metres."),
    months: int = typer.Option(3, "--months", help="Ridership months to average."),
    out: Path = typer.Option(None, "--out", help="Write the per-point table to this CSV."),
) -> None:
    """External check: do the walkable-demand measures RANK real footfall?

    At each NYC DOT Bi-Annual Pedestrian Count screenline (cqsj-cfgu, the 100
    ON-STREET points; `loc` 101-114 are bridge midpoints and are excluded),
    recompute `transit_entries_400m`, `jobs_400m` and `homes_400m` with the
    same walk graph and the same Dijkstra, and report Spearman rho against the
    observed AM+MD+PM count of the latest complete round.

    READ-ONLY. Writes nothing to the warehouse; no score reads the result.

    What a high rho would NOT prove: DOT's points are traffic-engineering
    locations on busy commercial corridors, so the correlation is measured on a
    RESTRICTED RANGE and says nothing about how the measures order one quiet
    residential block against another -- which is most of the address universe.
    The three measures also overlap by construction, so three similar rhos are
    one piece of evidence, not three.
    """
    from loci.validation import pedestrian_counts as pc

    con = locidb.connect(read_only=True)
    console.print("[dim]fetching DOT pedestrian counts + sweeping the walk graph…[/]")
    df, report = pc.run_validation(con, radius_m=radius_m, months=months)

    console.print(f"round [bold]{report['round']}[/] ({report['fields']}) · "
                  f"{report['on_street_points']} on-street points "
                  f"({report['dropped_bridge_points']} bridge points excluded, "
                  f"{report['dropped_missing_count']} missing a period)")
    console.print(f"transit window {report['transit']['window_start']}.."
                  f"{report['transit']['window_end']} · LODES WAC "
                  f"{report['jobs_vintage']} · radius {report['radius_m']:.0f} m")

    t = Table(title="Spearman rho vs DOT observed pedestrian count")
    t.add_column("measure"); t.add_column("rho", justify="right"); t.add_column("N", justify="right")
    for k, v in report["correlations"].items():
        t.add_row(k, f"{v['spearman_rho']:+.3f}", str(v["n"]))
    console.print(t)
    if out:
        df.to_csv(out, index=False)
        console.print(f"[green]ok[/] per-point table -> {out}")


@app.command(name="supply-ratio-box")
def supply_ratio_box(
    lat: str = typer.Option(..., "--lat", help="min,max latitude of the box."),
    lon: str = typer.Option(..., "--lon", help="min,max longitude of the box."),
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    name: str = typer.Option("box", "--name", help="Label for the table title."),
    all_addresses: bool = typer.Option(False, "--all-addresses",
                                       help="Include ineligible addresses (default: eligible only)."),
) -> None:
    """READ-ONLY: rank a lat/lon box's categories by supply per 1,000 homes
    versus the MN+BK baseline. Nothing is written.

    The ranking IS the deliverable: it says which categories are thinnest
    relative to the city norm, which is a different and more useful question
    than "which categories are absent". Requires `loci supply-ratio` to have
    run for the boroughs concerned.
    """
    from loci.model import supply_ratio as sr

    boros = _parse_boroughs(boroughs)
    lat_lo, lat_hi = (float(x) for x in lat.split(","))
    lon_lo, lon_hi = (float(x) for x in lon.split(","))
    con = locidb.connect(read_only=True)
    holes = ", ".join("?" for _ in boros)
    addr_xy = con.execute(
        f"SELECT address_id, lat, lon, COALESCE(eligible, FALSE) AS eligible, "
        f"lead_category, homes_400m, addressable_homes_400m_laundry, "
        f"supply_ratio_supply_hash "
        f"FROM analysis.address WHERE borough IN ({holes}) "
        f"AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        [*boros, lat_lo, lat_hi, lon_lo, lon_hi]).fetchdf()
    if addr_xy.empty:
        console.print("[yellow]no addresses in that box[/]")
        raise typer.Exit(1)
    ids = tuple(addr_xy["address_id"])
    long_df = con.execute(f"""
        SELECT address_id, borough, category, supply_400m, supply_per_1k,
               supply_ratio_vs_base
        FROM analysis.address_category
        WHERE borough IN ({holes}) AND address_id IN {ids if len(ids) > 1 else "('" + ids[0] + "')"}
    """, list(boros)).fetchdf()
    long_df = long_df.merge(addr_xy[["address_id", "homes_400m"]], on="address_id", how="left")

    doc = sr.load_baselines()
    out = sr.box_summary(long_df, addr_xy, (lat_lo, lat_hi), (lon_lo, lon_hi),
                         doc["categories"], eligible_only=not all_addresses)
    hashes = sorted(set(addr_xy["supply_ratio_supply_hash"].dropna()))
    t = Table(title=f"{name} — supply per 1,000 homes vs MN+BK baseline "
                    f"(principled set {', '.join(hashes) or 'NOT RUN'})")
    for col, j in (("category", "left"), ("tier", "right"), ("supply_400m med", "right"),
                   ("homes_400m med", "right"), ("per 1k", "right"),
                   ("baseline", "right"), ("ratio", "right")):
        t.add_column(col, justify=j)
    for _, r in out.iterrows():
        ratio = r["ratio"]
        colour = "red" if ratio is not None and ratio < 0.5 else (
            "yellow" if ratio is not None and ratio < 0.9 else "dim")
        t.add_row(r["category"], str(r["tier"]),
                  "—" if r["supply_400m_median"] is None else f"{r['supply_400m_median']:.0f}",
                  "—" if r["homes_400m_median"] is None else f"{r['homes_400m_median']:,.0f}",
                  "—" if r["supply_per_1k"] is None else f"{r['supply_per_1k']:.3f}",
                  "—" if r["baseline_per_1k"] is None else f"{r['baseline_per_1k']:.3f}",
                  "—" if ratio is None else f"[{colour}]{ratio:.2f}×[/]")
    console.print(t)
    lp = addr_xy["addressable_homes_400m_laundry"]
    console.print(f"{len(addr_xy):,} addresses in the box · median homes within 400 m "
                  f"{addr_xy['homes_400m'].median():,.0f}, of which "
                  f"{lp.median():,.0f} survive the laundry haircut · "
                  f"{int((lp >= 1500).sum()):,} addresses clear 1,500 addressable homes")
    console.print("[yellow]The baseline is REVEALED SUPPLY (D6): what New York built, "
                  "not what it needs. 1.0× means normal for this city, never "
                  "'correctly provisioned'.[/]")


@app.command(name="recommend")
def recommend(
    area: str = typer.Option(..., "--area", help="Name for the area, e.g. \"Gowanus core\"."),
    bbox: str = typer.Option(None, "--bbox",
                             help="lat0,lon0,lat1,lon1 — the area's bounding box."),
    nta: str = typer.Option(None, "--nta", help="NTA code, e.g. BK0601. Combines with --bbox."),
    category: list[str] = typer.Option(None, "--category",
                                       help="Repeatable. Default: all 15, thinnest ratio first."),
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    fmt: str = typer.Option("md", "--format", help="md or json."),
    out: Path = typer.Option(None, "--out", help="Write to this path instead of stdout."),
    all_addresses: bool = typer.Option(False, "--all-addresses",
                                       help="Include ineligible addresses (default: eligible only)."),
) -> None:
    """READ-ONLY: the recommendation card for an area — seven graded claims per
    category and a verdict that is the WORST load-bearing grade (D72).

    The card may not say "act" while any load-bearing claim (arriving homes,
    supply thinness, addressable demand, economics, coverage) is at grade D;
    every D is printed with the cheapest check that would move it. No expected
    profit is ever emitted — economics reports a supportable rent only.

    Nothing is written to the warehouse, and the connection retries the lock a
    concurrent writer holds rather than failing.
    """
    import json

    from loci.model import recommend as rec

    if not bbox and not nta:
        raise typer.BadParameter("give --bbox lat0,lon0,lat1,lon1 and/or --nta CODE")
    box = None
    if bbox:
        parts = [p.strip() for p in bbox.split(",")]
        if len(parts) != 4:
            raise typer.BadParameter("--bbox must be lat0,lon0,lat1,lon1")
        try:
            lat0, lon0, lat1, lon1 = (float(p) for p in parts)
        except ValueError as exc:
            raise typer.BadParameter(f"--bbox is not four numbers: {exc}") from exc
        box = (lat0, lon0, lat1, lon1)
    if fmt not in ("md", "json"):
        raise typer.BadParameter("--format must be md or json")

    boros = tuple(_parse_boroughs(boroughs))
    cats = list(category) if category else None
    if cats:
        from loci.categories import CATEGORIES as _CATS
        bad = [c for c in cats if c not in _CATS]
        if bad:
            raise typer.BadParameter(f"unknown categor(ies) {bad}; expected {sorted(_CATS)}")

    rules = rec.load_rules()
    con = rec.connect_read_only()
    try:
        facts = rec.area_facts(con, area, bbox=box, nta=nta, boroughs=boros,
                               eligible_only=not all_addresses)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    warnings: list[str] = []
    if facts["hash_mismatch"]:
        # DELIBERATE: warn and cap section 3 at C rather than refusing the run.
        # The other six sections are unaffected by supply drift, a concurrent
        # rebuild is the normal state here (D69), and section 3 is load-bearing
        # — so capping it at C already makes "act" unreachable. Refusing would
        # throw away six sound readings to punish one stale one.
        warnings.append(
            f"supply-hash drift — the baseline was fitted on `{facts['baseline_hash']}` "
            f"but the live principled set is `{facts['live_hash']}`. Every supply ratio "
            f"below mixes two supply sets; section 3 is capped at grade C. Re-run "
            f"`loci supply-ratio --fit-baseline` once the set has settled.")
        console.print(f"[yellow]warning:[/] {warnings[-1]}")

    cards = rec.build_cards(facts, rules, cats)

    if fmt == "json":
        text = json.dumps(rec.to_json(cards, facts, rules, warnings), indent=2, default=str)
    else:
        text = rec.render_markdown(cards, facts, rules, warnings)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
        console.print(f"[green]written[/] -> {out}")
    else:
        print(text)

    noun = "category" if len(cards) == 1 else "categories"
    t = Table(title=f"{area} — {len(cards)} {noun}, verdict = worst load-bearing grade")
    for col, j in (("category", "left"), ("ratio", "right"), ("regime", "left"),
                   ("grade", "center"), ("verdict", "left"), ("D sections", "left")):
        t.add_column(col, justify=j)
    for r in rec.summary_rows(cards):
        colour = {"A": "green", "B": "green", "C": "yellow", "D": "red"}[r["grade"]]
        t.add_row(r["category"],
                  "—" if r["supply_ratio_vs_base"] is None else f"{r['supply_ratio_vs_base']:.2f}×",
                  r["regime"], f"[{colour}]{r['grade']}[/]",
                  f"[{colour}]{r['verdict']}[/]", r["blockers"])
    console.print(t)
    console.print("[yellow]The supply baseline is REVEALED SUPPLY (D6); permit 'activity' is "
                  "a renewal, not a shovel; no expected profit is emitted.[/]")


# ===========================================================================
# SITE-REVENUE MODEL v0 (2026-09-13) -- appended block, see model/revenue.py.
# ===========================================================================
def _connect_retrying(read_only: bool, retries: int = 40, wait_s: float = 45.0):
    """Open the warehouse, waiting out the lock a concurrent writer holds.
    Never kills anything: another session rebuilding is normal (D69), and the
    same pattern recommend.connect_read_only already uses."""
    import time as _time

    last = None
    for i in range(retries):
        try:
            return locidb.connect(read_only=read_only)
        except Exception as exc:            # noqa: BLE001 -- duckdb raises several types
            last = exc
            if i == 0:
                console.print(f"[dim]warehouse is locked by another session; "
                              f"retrying every {wait_s:.0f}s…[/]")
            if i < retries - 1:
                _time.sleep(wait_s)
    raise RuntimeError(f"warehouse still locked after {retries} tries: {last}")


revenue_app = typer.Typer(add_completion=False, help=(
    "What a TYPICAL new store of a category could take at an address.\n\n"
    "`loci revenue fit` calibrates and GATES; `loci revenue` applies the shipped "
    "calibration to the warehouse. Fitting is deliberately NOT part of the "
    "re-apply path -- a re-apply must not silently re-calibrate, or every run is "
    "measured against itself."))
app.add_typer(revenue_app, name="revenue")


@revenue_app.callback(invoke_without_command=True)
def revenue_apply(
    ctx: typer.Context,
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Apply the shipped calibration: revenue_p25/p50/p75, rent_ceiling and
    revenue_model_version on analysis.address_category, homes_800m on
    analysis.address, by UPDATE only.

        revenue_p50 = lambda_c x homes_400m x CEX spend/household at the
                      address's income quintile x Huff capture share

    A category whose calibration FAILED the out-of-sample gate is left NULL --
    NULL is "not modelled", never a revenue of zero -- and keeps grade D on the
    recommendation card.

    RE-APPLY after a screen re-run with exactly this, at the END of the
    canonical order (it reads nothing from supply-ratio, but shares its sweep
    engine and belongs after it):

        uv run loci revenue --boroughs MN,BK
    """
    if ctx.invoked_subcommand is not None:
        return
    from loci.model import revenue as rev

    boros = _parse_boroughs(boroughs)
    con = _connect_retrying(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    console.print(f"[dim]site revenue for {','.join(boros)}…[/]")
    report = rev.build_revenue(con, boros, dry_run=dry_run,
                               log=lambda m: console.print(f"[dim]{m}[/]"))
    console.print(
        f"{report['addresses']:,} addresses swept ({report['query_nodes']:,} distinct "
        f"nodes, {report['sweep_seconds']:.0f}s) · shipped categories: "
        f"{', '.join(report['shipped_categories']) or 'NONE'} · "
        f"{report['rows_predicted']:,} address x category rows predicted")
    agree = report.get("homes_400m_agrees_with_supply_ratio")
    if agree is not None:
        colour = "green" if agree > 0.999 else "yellow"
        console.print(f"[{colour}]homes_400m recomputed here matches the stored D73 column "
                      f"on {agree:.3%} of addresses[/] — this module recomputes rather than "
                      f"reads, so the two sweeps cross-check each other.")
    if report.get("supply_hash_drift"):
        console.print("[yellow]warning:[/] lambda was calibrated against a different "
                      "incumbent set than the live one — re-run `loci revenue fit`.")
    console.print("[yellow]p25/p75 are a PARAMETER band (lambda spread, income MOE, beta "
                  "refit spread), NOT the dispersion of real store outcomes. The model "
                  "describes a typical operator at a site and says nothing about concept "
                  "quality; county anchors blur Park Slope with Gowanus.[/]")


@revenue_app.command("fit")
def revenue_fit(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Fit and print the table; do NOT write the YAML."),
) -> None:
    """Calibrate lambda and beta, backtest out of sample, and write
    src/loci/model/revenue_calibration.yaml -- IF the gate passes.

    lambda_c is fitted per county so the mean prediction over that county's
    existing establishments equals the Economic Census mean revenue per
    establishment; beta is fitted by leave-one-ZIP-out skill against CBP 2023
    employees per establishment, never assumed. A category ships only if it
    beats BOTH the county-average and homes-only baselines out of sample and
    passes the cross-category placebo. If nothing passes, nothing is written.
    """
    from loci.model import revenue as rev

    boros = _parse_boroughs(boroughs)
    con = _connect_retrying(read_only=True)
    console.print(f"[dim]calibrating site revenue on {','.join(boros)}…[/]")
    doc = rev.fit(con, boros, log=lambda m: console.print(f"[dim]{m}[/]"))

    t = Table(title="site-revenue calibration — lambda from EC county anchors, "
                    "beta from leave-one-ZIP-out skill")
    for col, j in (("category", "left"), ("beta", "right"), ("gamma", "right"),
                   ("competition", "left"), ("lambda BK", "right"),
                   ("lambda MN", "right"), ("EC $/estab BK", "right"),
                   ("rho oos", "right"), ("vs county", "right"), ("vs homes", "right"),
                   ("placebo", "center"), ("gate", "center")):
        t.add_column(col, justify=j)
    for cat, d in doc["categories"].items():
        bt = d.get("backtest") or {}
        lam = d.get("lambda") or {}
        pl = d.get("placebo") or {}
        colour = "green" if d.get("gate") == "pass" else "red"

        def _l(f):
            v = (lam.get(f) or {}).get("lambda_per_store")
            return "—" if v is None else f"{v:.3f}"
        ec = (lam.get("047") or {}).get("ec_rev_per_estab_usd")
        t.add_row(cat, "—" if d.get("beta") is None else f"{d['beta']:.2f}",
                  "—" if d.get("gamma") is None else f"{d['gamma']:+.2f}",
                  d.get("competition_sign") or "—",
                  _l("047"), _l("061"),
                  "—" if ec is None else f"${ec:,.0f}",
                  "—" if bt.get("spearman_oos") is None else f"{bt['spearman_oos']:+.3f}",
                  "—" if bt.get("baseline_county_average_spearman") is None
                       else f"{bt['baseline_county_average_spearman']:+.3f}",
                  "—" if bt.get("baseline_homes_only_spearman") is None
                       else f"{bt['baseline_homes_only_spearman']:+.3f}",
                  "pass" if pl.get("passes") else "FAIL",
                  f"[{colour}]{d.get('gate')}[/]")
    console.print(t)
    for cat, d in doc["categories"].items():
        if d.get("gate") != "pass":
            console.print(f"[red]not modelled[/] {cat}: {d.get('gate_reason')}")

    if dry_run:
        console.print("[yellow]--dry-run: revenue_calibration.yaml NOT written.[/]")
        return
    try:
        path = rev.save_calibration(doc)
    except RuntimeError as exc:
        console.print(f"[red]gate refused the write:[/] {exc}")
        raise typer.Exit(code=1) from None
    console.print(f"[green]written[/] -> {path}")
    console.print("[yellow]The backtest target is CBP employees per establishment, a "
                  "REVENUE PROXY: it validates cross-sectional ranking, never the level. "
                  "The level is fitted to the EC county mean by construction and has no "
                  "out-of-sample test anywhere — no public source publishes retail "
                  "receipts below county grain.[/]")


# ---------------------------------------------------------------------------
# loci chains -- the NYC chain watchlist (detect / research / import / render)
# ---------------------------------------------------------------------------
chains_app = typer.Typer(add_completion=False, help=(
    "Retail and consumer brands expanding in NYC. Two uses: companies to sell "
    "to, and -- later -- the \"brand X is opening nearby\" signal on a recommend "
    "card (nothing consumes that yet; `loci_category` is the join key that will "
    "make it possible). THREE LAYERS, deliberately separate: `detect` is open "
    "data only and deterministic; `research` costs Tavily credits and is "
    "budgeted in code; `watchlist.yaml` is hand-maintained and OUTRANKS both. "
    "`render` writes docs/CHAINS.md, which is generated and never hand-edited."))
app.add_typer(chains_app, name="chains")

#: Mirrors loci.chains.research.MAX_QUERIES. Duplicated here only because Typer
#: evaluates option defaults at import time and cli.py imports the analysis
#: packages lazily; `loci chains research --help` asserts they agree.
_CHAINS_DEFAULT_BUDGET = 60


def _chains_connect(read_only: bool):
    """Open the warehouse, retrying the lock a concurrent writer holds (D69:
    another session rebuilding is the normal state here, not an error)."""
    from loci.model.recommend import connect_read_only

    if read_only:
        return connect_read_only()
    con = locidb.connect()
    from loci.chains.detect import ensure_schema
    ensure_schema(con)
    return con


@chains_app.command("detect")
def chains_detect(
    month: str = typer.Option(None, "--month", help="Snapshot month YYYY-MM; "
                                                    "default the current month."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Compute and print; write no snapshot."),
    limit: int = typer.Option(25, "--limit", help="Rows to print (0 = all flagged)."),
) -> None:
    """Detect chains from the warehouse and write one month of snapshot.

    Reads `analysis.poi_supply` at the DEDUPED LOCATION grain, groups by
    `loci.chains.normalize.brand_key`, and flags brands that are growing.
    Idempotent: re-running a month DELETEs and re-INSERTs it.

    `locations_new_12m` is a FLOOR -- only four of the nine POI sources carry a
    usable first-seen date, so it is counted over `locations_dated`, which is
    printed beside it. The date-independent measure is the difference between
    two monthly snapshots, which is why this command exists as a cron job and
    not only as a query."""
    from loci.chains import detect as det

    con = _chains_connect(read_only=dry_run)
    try:
        result, rows = det.build(con, month=month, dry_run=dry_run)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    flagged = [r for r in rows if r["flagged"]]
    shown = flagged if not limit else flagged[:limit]
    t = Table(title=f"chains detect {result.snapshot_month} — "
                    f"{result.n_flagged:,} flagged of {result.n_brands:,} "
                    f"multi-location brands")
    for col, j in (("brand", "left"), ("loci_category", "left"), ("total", "right"),
                   ("dated", "right"), ("new 12m", "right"), ("new 3m", "right"),
                   ("boro", "right"), ("src", "right"), ("why", "left")):
        t.add_column(col, justify=j)
    for r in shown:
        t.add_row(str(r.get("display_name") or r["brand_key"])[:40],
                  str(r.get("loci_category") or "—"),
                  f"{r['locations_total']:,}", f"{r['locations_dated']:,}",
                  f"{r['locations_new_12m']:,}", f"{r['locations_new_3m']:,}",
                  str(r["n_boroughs"]), str(r["n_sources"]),
                  str(r.get("flag_reason") or ""))
    console.print(t)
    console.print(f"[dim]{result.n_locations:,} brand-locations, "
                  f"{result.n_dated:,} ({result.n_dated / max(result.n_locations, 1):.0%}) "
                  f"carry a first-seen date — `new 12m` is a floor over that subset.[/]")
    if dry_run:
        console.print("[yellow]--dry-run: nothing written.[/]")
    else:
        console.print(f"[green]ok[/] chains.brand_snapshot / chains.brand_location "
                      f"@ {result.snapshot_month}")


@chains_app.command("research")
def chains_research(
    month: str = typer.Option(None, "--month", help="Snapshot to take brands from."),
    max_queries: int = typer.Option(None, "--max-queries",
                                    help=f"Hard budget; default "
                                         f"{_CHAINS_DEFAULT_BUDGET}."),
    days: int = typer.Option(None, "--days", help="Press window in days."),
    detected: int = typer.Option(0, "--detected",
                                 help="Also query the top N flagged brands from "
                                      "the snapshot, not just the watchlist."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Print the exact queries; spend nothing. "
                                      "Needs no API key."),
) -> None:
    """Press enrichment via Tavily. Budgeted in code; --dry-run spends nothing.

    Discovery queries run FIRST so that a truncated budget keeps the channel
    that finds brands nobody listed. A hit is a headline in a reading queue,
    not evidence: promoting one to the watchlist is a human decision."""
    from loci.chains import detect as det
    from loci.chains import research as res
    from loci.chains import watchlist as wl

    budget = max_queries if max_queries is not None else res.MAX_QUERIES
    window = days if days is not None else res.DEFAULT_DAYS
    if budget <= 0:
        raise typer.BadParameter("--max-queries must be positive")

    rows = wl.brands()
    keys = [r["brand_key"] for r in rows if r.get("brand_key")]
    names = {r["brand_key"]: r.get("brand") for r in rows if r.get("brand_key")}

    con = _chains_connect(read_only=dry_run)
    if detected:
        for r in det.flagged_brands(con, month, limit=detected):
            if r["brand_key"] not in names:
                keys.append(r["brand_key"])
                names[r["brand_key"]] = r.get("display_name")

    plan = res.build_plan(keys, names, max_queries=budget)
    t = Table(title=f"chains research — {plan.n_queries} queries of a {budget} budget"
                    + (f", {plan.truncated} dropped" if plan.truncated else ""))
    t.add_column("#", justify="right"); t.add_column("kind"); t.add_column("query")
    for i, (kind, _key, q) in enumerate(plan.queries, 1):
        t.add_row(str(i), kind, q)
    console.print(t)
    console.print(f"[dim]window: last {window} days · domains: "
                  f"{', '.join(res.PRESS_DOMAINS)}[/]")

    if dry_run:
        console.print("[yellow]--dry-run: no queries sent, nothing spent.[/]")
        raise typer.Exit(0)

    try:
        out = res.run(con, plan, days=window)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[green]ok[/] {out['queries_spent']} queries spent, "
                  f"{out['hits']} hits, {out['written']} rows in chains.press_hits "
                  f"(since {out['since']})"
                  + (f", [red]{out['errors']} failed[/]" if out["errors"] else ""))


@chains_app.command("import")
def chains_import(
    path: Path = typer.Argument(..., help="JSON array of brand records "
                                          "(snake_case keys, see watchlist.yaml)."),
    overwrite: bool = typer.Option(False, "--overwrite",
                                   help="Let incoming values replace non-empty "
                                        "curated ones. OFF by default."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report; write nothing."),
) -> None:
    """Upsert a research JSON into src/loci/chains/watchlist.yaml.

    FILL-ONLY by default: an incoming value is written only where the curated
    value is empty, so a hand-corrected row survives the next import. `evidence`
    is UNIONed by url and `first_added` is never overwritten."""
    import json

    from loci.chains import watchlist as wl

    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        console.print(f"[red]cannot read {path}: {exc}[/]")
        raise typer.Exit(1) from exc
    if isinstance(payload, dict):
        payload = payload.get("brands") or payload.get("records") or []
    if not isinstance(payload, list):
        console.print("[red]expected a JSON array of brand records[/]")
        raise typer.Exit(1)

    doc = wl.load()
    doc, counts = wl.upsert(doc, payload, overwrite=overwrite)
    errors = wl.validate(doc)
    for e in errors:
        console.print(f"[red]FAIL[/] {e}")
    if errors:
        console.print("[red]watchlist not written — fix the records above.[/]")
        raise typer.Exit(1)

    console.print(f"{counts['added']} added, {counts['updated']} updated, "
                  f"{counts['skipped']} skipped (no resolvable brand_key); "
                  f"{len(doc['brands'])} brands total")
    if counts["unplaced_keys"]:
        # Loud, not silent: a key nobody mapped is DATA THAT WAS DROPPED. Add it
        # to watchlist.KEY_ALIASES (or IGNORED_KEYS) and re-import.
        console.print("[yellow]unmapped keys in the payload, NOT imported: "
                      + ", ".join(counts["unplaced_keys"])
                      + " — add them to chains/watchlist.py KEY_ALIASES[/]")
    if counts["dropped_categories"]:
        # Nulled, not invented: these brands have no daily-needs category to
        # join to. They are still worth selling to; they just cannot be a
        # recommendation signal.
        console.print("[yellow]loci_category set to null for unmappable values: "
                      + ", ".join(counts["dropped_categories"]) + "[/]")
    if dry_run:
        console.print("[yellow]--dry-run: watchlist not written.[/]")
        raise typer.Exit(0)
    console.print(f"[green]written[/] -> {wl.write(doc)}")


@chains_app.command("render")
def chains_render(
    month: str = typer.Option(None, "--month", help="Snapshot to render; default newest."),
    out: Path = typer.Option(None, "--out", help="Override docs/CHAINS.md."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print; write nothing."),
) -> None:
    """Generate docs/CHAINS.md from watchlist + newest snapshot + press hits.

    Fails before writing if the watchlist is structurally invalid -- a
    `brand_key` that the normalizer would never produce joins to nothing, and
    the document would report a tracked brand as undetected."""
    from loci.chains import render as ren
    from loci.chains import watchlist as wl

    doc = wl.load()
    errors = wl.validate(doc)
    for e in errors:
        console.print(f"[red]FAIL[/] {e}")
    if errors:
        raise typer.Exit(1)

    con = _chains_connect(read_only=True)
    text = ren.render(con, doc=doc, month=month)
    if dry_run:
        print(text)
        console.print("[yellow]--dry-run: docs/CHAINS.md not written.[/]")
        raise typer.Exit(0)
    console.print(f"[green]written[/] -> {ren.write(text, out)}")


@chains_app.command("refresh")
def chains_refresh(
    month: str = typer.Option(None, "--month", help="Snapshot month YYYY-MM."),
    max_queries: int = typer.Option(None, "--max-queries", help="Tavily budget."),
    skip_research: bool = typer.Option(False, "--skip-research",
                                       help="detect + render only; spend nothing."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Every step dry: no snapshot, no queries, no doc."),
) -> None:
    """detect -> research -> render. The monthly job (`make chains-refresh`).

    Research failure does NOT abort the run: the snapshot is the load-bearing
    artefact and it is already written by then, so a Tavily outage must not
    cost the month its count."""
    console.rule("[bold]1/3 detect")
    chains_detect(month=month, dry_run=dry_run, limit=25)
    if skip_research:
        console.rule("[bold]2/3 research — skipped (--skip-research)")
    else:
        console.rule("[bold]2/3 research")
        try:
            chains_research(month=month, max_queries=max_queries, days=None,
                            detected=0, dry_run=dry_run)
        except typer.Exit as exc:
            if exc.exit_code:
                console.print("[yellow]research failed — continuing to render; "
                              "the snapshot is already written.[/]")
        except Exception as exc:            # noqa: BLE001
            console.print(f"[yellow]research failed ({exc}) — continuing to render.[/]")
    console.rule("[bold]3/3 render")
    try:
        chains_render(month=month, out=None, dry_run=dry_run)
    except typer.Exit as exc:
        if exc.exit_code:
            raise


if __name__ == "__main__":
    app()
