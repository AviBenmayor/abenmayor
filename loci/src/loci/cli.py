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
    loci age-fit fit   [--boroughs MN,BK] [--dry-run]   (D63: re-estimate the
                                                        supply-revealed bar age curve;
                                                        exits non-zero on the F2 gate)
    loci age-fit apply [--boroughs MN,BK] [--dry-run]   (D63: age_fit on bar rows,
                                                        gap_score_fit beside gap_score)
    loci anchor-coverage [--borough Manhattan,Brooklyn] [--write]   (D52 step 1)
    loci ingest --source overture_places --city nyc [--dry-run]
    loci citywide-income [--refresh]                     (ACS B19025/B11001, read-only)
    loci address-demographics [--dry-run]               (address-grain ACS, D56)
    loci ingest-zbp [--year 2023] [--dry-run]           (validation only)
    loci ingest-ll84 [--dry-run]                        (LL84 in-building laundry, D51(d))
    loci ingest-alcohol [--limit N] [--dry-run]         (SLA alcohol overlay, not a category)
    loci ingest-dcwp [--limit N] [--apply]              (DCWP retail-laundry anchor, D55;
                                                        defaults to pending/dry, --apply promotes)
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
from loci import questions, registry, tickets as tickets_mod
from loci import sources as source_adapters
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
    from loci.score.supply import ANCHOR_COVERAGE_MIN, build_category_anchor, measure_anchor_coverage

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
                      f"{cov_s:>9} {str(bool(r['qualifies'])):>10}  {r['anchor_sources'] or '-'}",
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
                  f"[bold]{100*summary['eligible_unit_share']:.1f}%[/] of units")

    console.print("[bold]per-category gap counts (eligible only, ratio > 1):[/]")
    for cat in ag.ALLCATS:
        n_addr = summary["per_cat_gap_addr"][cat]
        if n_addr:
            console.print(f"  {cat:14} {n_addr:>8,} addr  {summary['per_cat_gap_units'][cat]:>10,.0f} units")

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
    from loci.validation.google_places import GooglePlacesClient
    from loci.validation import sample as smp
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
    from loci.model.spacing import same_type_spacing, _graph, WALK_M_PER_MIN
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


age_fit_app = typer.Typer(add_completion=False, help=(
    "The D63 age-fit ranking signal: a SUPPLY-REVEALED age multiplier for the "
    "`bar` category, estimated from New York's own licensed-venue composition "
    "(docs/bar_age_nyc.md), not from the BLS CEX household survey that "
    "docs/age_demand_fit.md rejected for bar. BAR ONLY -- every other category "
    "keeps a NULL age_fit, because no curve exists for it. NON-FILTERING: "
    "`fit` and `apply` never touch gap_score, ratio, nearest_m, eligible, "
    "lead_category, n_missing or cluster_id; gap_score_fit is a SECOND ranking "
    "column beside gap_score. `fit` exits NON-ZERO and writes nothing if the "
    "curve fails its own F2/F3 criterion."))
app.add_typer(age_fit_app, name="age-fit")


@age_fit_app.command("fit")
def age_fit_fit(
    boroughs: str = typer.Option("MN,BK", help="Estimation sample (D48 default MN,BK)."),
    acs_year: int = typer.Option(None, help="ACS vintage; default the pinned 2023."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Estimate and print; write no JSON."),
) -> None:
    """Re-estimate `age_fit_bar` from the warehouse and write the coefficients.

    SUPPLY-REVEALED, BAR ONLY. The specification is the COMPOSITION one
    (docs/bar_age_nyc.md §7): outcome = bar-type share of on-premises SLA
    licences within 400 m of the tract's residential centroid; regressors =
    adult 18-34 share, adult 65+ share, log units, log(1 + CNS07 retail jobs),
    log walk-to-subway, log median household income, renter share, borough FE;
    Conley spatial-HAC standard errors (Bartlett, 2 km) because the residuals'
    Moran's I is ~0.42 and HC3 is unusable.

    THE F2 GATE IS ENFORCED HERE, NOT DOCUMENTED HERE. If the Brooklyn-only
    Conley CI on the Carnegie-Hill -> East-Village contrast includes 1.0, or the
    dispersion gate (p90-p10 of the multiplier over the estimation tracts /
    median MOE) falls below 1.0, this command exits non-zero and writes nothing:
    the multiplier must not be applied from a curve that fails its own
    criterion, and Brooklyn is where 98% of the bar-lead gap set lives.
    """
    from loci.model import age_fit as af

    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=True)   # estimation NEVER writes to the database
    console.print(f"[dim]estimating {af.SPEC_VERSION} on {','.join(boros)} "
                  f"(ACS {acs_year or af.ACS_YEAR}, Conley {af.CONLEY_CUTOFF_M:.0f} m)…[/]")
    try:
        fit, path = af.fit_bar_curve(
            con, boros, acs_year=acs_year or af.ACS_YEAR, dry_run=dry_run)
    except af.AgeFitGateFailure as exc:
        console.print(f"[red]GATE FAILED[/] {exc}")
        raise typer.Exit(1) from exc

    t = Table(title=f"{fit['spec']} — n = {fit['n_tracts']:,} tracts, "
                    f"R² = {fit['r_squared']:.3f}")
    t.add_column("term"); t.add_column("coef", justify="right")
    t.add_column("Conley se", justify="right"); t.add_column("t", justify="right")
    t.add_row("w18 (adult 18-34 share)", f"{fit['b18']:+.3f}",
              f"{fit['b18_se_conley']:.3f}", f"{fit['b18_t_conley']:+.2f}")
    t.add_row("w65 (adult 65+ share)", f"{fit['b65']:+.3f}",
              f"{fit['b65_se_conley']:.3f}", f"{fit['b65_t_conley']:+.2f}")
    console.print(t)

    c = fit["contrast"]["pooled"]
    console.print(f"Carnegie Hill -> East Village partial effect: "
                  f"[bold]{c['ratio']:.3f}[/] "
                  f"Conley 95% CI [{c['ci_low']:.3f}, {c['ci_high']:.3f}] (pooled)")
    for boro, b in sorted(fit["by_borough"].items()):
        bc = b["contrast"]
        console.print(f"  {boro} only (n={b['n_tracts']:,}): b18={b['b18']:+.3f} "
                      f"b65={b['b65']:+.3f}  ratio {bc['ratio']:.3f} "
                      f"CI [{bc['ci_low']:.3f}, {bc['ci_high']:.3f}]")
    m = fit["multiplier"]
    console.print(f"multiplier over estimation tracts: p10/p50/p90 = "
                  f"{m['p10']:.3f} / {m['p50']:.3f} / {m['p90']:.3f}; "
                  f"spread {m['spread']:.3f} vs median MOE {m['median_moe']:.3f} "
                  f"-> dispersion [bold]{m['dispersion_ratio']:.2f}×[/] "
                  f"(gate needs >= {af.DISPERSION_GATE_MIN})")
    console.print(f"[dim]inputs {fit['inputs']['hash']}: supply "
                  f"{fit['inputs']['supply_hash']}, ACS {fit['inputs']['acs_year']}, "
                  f"{fit['inputs']['n_bar_licences']:,} bar-type of "
                  f"{fit['inputs']['n_onprem_licences']:,} on-premises licences[/]")
    if path is None:
        console.print("[dim]--dry-run:[/] gates pass, nothing written.")
    else:
        console.print(f"[green]ok[/] gates pass -> {path}")


@age_fit_app.command("apply")
def age_fit_apply(
    boroughs: str = typer.Option("MN,BK", help="Where to apply (D48 default MN,BK)."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Compute and print the summary; write nothing."),
) -> None:
    """Write `age_fit` onto bar rows and `gap_score_fit` beside `gap_score`.

    UPDATE-ONLY on analysis.address_category (age_fit, age_fit_moe,
    age_fit_source) and analysis.address (age_fit_lead, age_fit_lead_moe,
    gap_score_fit). Both SET lists are asserted disjoint from the screen's own
    columns before either UPDATE runs, so this command cannot move gap_score,
    ratio, nearest_m, eligible, lead_category, n_missing or cluster_id -- the
    gap set is bit-identical before and after, and a test pins that.

    BAR ONLY: every other category's age_fit is NULL (no curve exists), and
    age_fit_lead is exactly 1.0 wherever the lead category has no fitted curve,
    so gap_score_fit == gap_score there. Refuses to run if the stored curve was
    fitted against a different supply set or ACS vintage than the database now
    holds -- a supply-revealed coefficient is only valid against the supply set
    it was revealed from.
    """
    from loci.model import age_fit as af

    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    try:
        fit = af.load_fit()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    try:
        cat_df, addr_df, report = af.apply_age_fit(con, boros, fit=fit, dry_run=dry_run)
    except af.AgeFitStale as exc:
        console.print(f"[red]STALE CURVE[/] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"[dim]{report['spec']}: b18={report['b18']:+.3f} "
                  f"b65={report['b65']:+.3f}[/]")
    console.print(f"{report['n_category_rows']:,} fitted (address, category) rows "
                  f"over {report['n_addresses']:,} addresses; "
                  f"{report['n_lead_multiplied']:,} addresses have a bar lead and are "
                  f"actually re-weighted")
    if report["fitted_p50"] is not None:
        console.print(f"age_fit p10/p50/p90 = {report['fitted_p10']:.3f} / "
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


if __name__ == "__main__":
    app()
